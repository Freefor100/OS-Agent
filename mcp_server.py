#!/usr/bin/env python3
"""MCP server — exposes deterministic pipeline data for Claude Code + Skill.

6 compute-only tools. Claude Code has bash for file ops (ls/cat/grep) so
those aren't exposed here — only what bash can't do.

Tools:
  search_candidates  1-vs-N similarity search (token + AST dual dimension)
  deep_compare       function-level COPIED/DISGUISE/MODIFIED/NOVEL vs base
  attribution        per-function provenance + node-level grouping
  node_taxonomy      kernel design tree skeleton (14 subsystems / 112 leaves)
  declared_deps      extracted declarations (Cargo/gitmodules/README refs)
  exclude_rules      exclusion rules applied to this target
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ensure repo root on sys.path BEFORE importing project modules
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("os-agent")


# ── helpers ──────────────────────────────────────────────────────────

def _target_path(target: str) -> str:
    return f"repos/{target}" if "/" not in target else target


# ── tool: search_candidates ──────────────────────────────────────────

@mcp.tool()
def search_candidates(target: str, top_k: int = 10) -> dict:
    """1-vs-N rough similarity search. Returns top-K corpus members ranked by
    bidirectional containment (min). Higher min = more shared code. Frameworks
    (arceos/xv6/rCore) tagged with is_framework=True."""
    from scripts.search import search, corpus_fingerprints

    corpus = corpus_fingerprints(build_missing=True)
    results = search(target, corpus=corpus, top_k=top_k)
    return {"target": target, "corpus_size": len(corpus), "candidates": results}


# ── tool: attribution ────────────────────────────────────────────────

@mcp.tool()
def attribution(target: str, base: str = "", top_k: int = 5) -> dict:
    """Per-function provenance vs a base (or vs top search candidates if base='').
    Returns {node_id: {status, functions: [{name, file, line, provenance}]}}
    node_id is a coarse directory-based grouping (refined by the LLM later)."""
    from scripts.fingerprint import build_units
    from scripts.provenance import classify_provenance, PEER_TOKEN_FLOOR
    from scripts.exclude import load_rules as load_exclude_rules
    from scripts.search import search
    from collections import defaultdict

    units = build_units(_target_path(target))
    rules = load_exclude_rules(target)

    # resolve base
    if not base:
        candidates = search(target, top_k=top_k)
        # pick the non-framework peer with highest min score
        peers = [c for c in candidates if not c.get("is_framework")]
        base = peers[0]["repo"] if peers else ""

    # build peer fingerprint set from base
    peer_fps: set[str] = set()
    if base:
        from scripts.fingerprint import fingerprint_set
        try:
            peer_fps = fingerprint_set(_target_path(base))
        except Exception:
            pass

    classes = classify_provenance(units, set(), peer_fps, floor=PEER_TOKEN_FLOOR,
                                   exclude_rules=rules)

    # map provenance class name to our labels
    LABEL = {"EXTERNAL": "EXTERNAL", "PORTED-FRAMEWORK": "COPIED",
             "PORTED-PEER": "COPIED", "ORIGINAL": "NOVEL", "TRIVIAL": "TRIVIAL"}

    # group by coarse node (directory prefix)
    nodes: dict[str, dict] = defaultdict(lambda: {"status": "unimplemented", "functions": []})
    for cname, fns in classes.items():
        label = LABEL.get(cname, cname)
        for f in fns:
            d = f["file"].split("/")[0] if "/" in f["file"] else "(root)"
            # refine: os/src/mm -> mm, api/src/fs -> fs
            parts = f["file"].split("/")
            if len(parts) >= 3 and parts[0] in ("os", "kernel", "src"):
                d = parts[1] if parts[1] != "src" else parts[2] if len(parts) > 2 else parts[1]
            elif len(parts) >= 3 and parts[0] in ("api", "core"):
                d = "syscall" if "syscall" in f["file"] or "imp" in f["file"] else parts[0]
            nodes[d]["functions"].append({
                "name": f["name"],
                "file": f["file"],
                "line": f.get("line", 0),
                "lang": f.get("lang", ""),
                "provenance": label,
                "tokens": f["sz"],
            })

    # set status per node
    for nd in nodes.values():
        provs = {fn["provenance"] for fn in nd["functions"]}
        if not provs or provs == {"TRIVIAL"}:
            nd["status"] = "unimplemented"
        elif provs <= {"COPIED", "TRIVIAL"}:
            nd["status"] = "inherited"
        elif provs <= {"COPIED", "NOVEL", "TRIVIAL"}:
            nd["status"] = "partial"
        else:
            nd["status"] = "implemented"

    return {
        "target": target, "base": base,
        "total_units": len(units),
        "nodes": dict(nodes),
        "summary": {c: len(fns) for c, fns in classes.items()},
    }


# ── tool: node_taxonomy ──────────────────────────────────────────────

@mcp.tool()
def node_taxonomy(node_id: str = "") -> dict:
    """Kernel design tree skeleton. 14 subsystems, 112 leaf nodes.
    Pass node_id to get one node's details; empty = full tree."""
    from core.kernel_tree import ROOT_NODES_V2, ANALYSIS_ORDER_V2, node_title_zh, node_title_en

    if node_id:
        return {
            "node_id": node_id,
            "title_zh": node_title_zh(node_id),
            "title_en": node_title_en(node_id),
        }

    tree = {}
    for root, children in ROOT_NODES_V2.items():
        tree[root] = {
            "title_zh": node_title_zh(root),
            "title_en": node_title_en(root),
            "children": [{"id": c, "title_zh": node_title_zh(c), "title_en": node_title_en(c)}
                         for c in children],
        }
    return {"roots": tree, "leaf_count": len(ANALYSIS_ORDER_V2),
            "order": ANALYSIS_ORDER_V2}


# ── tool: deep_compare ──────────────────────────────────────────────

@mcp.tool()
def deep_compare(target: str, base: str = "") -> dict:
    """Function-level comparison vs a base repo. Returns COPIED/DISGUISE/MODIFIED/NOVEL counts and per-module breakdown. If base is empty, auto-resolves from search."""
    from scripts.attribute import deep_compare as dc
    if not base:
        from scripts.search import search, corpus_fingerprints
        candidates = search(target, corpus=corpus_fingerprints(), top_k=3)
        peers = [c for c in candidates if not c.get("is_framework")]
        base = peers[0]["repo"] if peers else ""
    classes = dc(target, base)
    summary = {k: len(v) for k, v in classes.items()}
    # per-module
    from collections import defaultdict
    mods = defaultdict(lambda: defaultdict(int))
    for cls, fns in classes.items():
        for f in fns:
            parts = [p for p in f["file"].split("/") if p not in ("", "src", "kernel", "os")]
            m = parts[0] if parts else "(root)"
            mods[m][cls] += max(1, f["sz"])
    return {"target": target, "base": base, "summary": summary,
            "per_module": {m: dict(st) for m, st in mods.items()}}


# ── tool: declared_deps ──────────────────────────────────────────────

@mcp.tool()
def declared_deps(target: str) -> dict:
    """Extracted declarations: Cargo workspace, git deps, submodules, README refs."""
    from scripts.declarations import extract
    return extract(Path(_target_path(target)))


# ── tool: exclude_rules ──────────────────────────────────────────────

@mcp.tool()
def exclude_rules(target: str) -> dict:
    """Exclusion rules applied to this target (what was removed and why)."""
    from scripts.exclude import load_rules as load_exclude_rules
    return {"target": target, "rules": load_exclude_rules(target)}


# ── entry ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
