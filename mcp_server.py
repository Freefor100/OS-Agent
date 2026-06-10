#!/usr/bin/env python3
"""MCP server — thin read-only layer over the deterministic pipeline.

Exposes 11 tools so Claude Code (with the Skill) can produce judge-facing
reports. Every tool is read-only; all the heavy computation lives in scripts/.

Tools:
  search_candidates  1-vs-N rough search → top similar repos (token + AST)
  deep_compare       function-level COPIED/DISGUISE/MODIFIED/NOVEL vs base
  attribution        per-function provenance + coarse node assignment
  unit_source        read source code at file:line
  read_code          read source file with line range (PDF/Docx support)
  grep_repo          regex search across the repo (find symbols/patterns)
  lsp_lookup         jump to symbol definition (clangd/rust-analyzer or grep)
  list_dir           list directory contents (explore project structure)
  node_taxonomy      kernel design tree skeleton (112 leaf nodes)
  declared_deps      extracted declarations (Cargo/gitmodules/README)
  exclude_rules      what was excluded and why
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


# ── tool: unit_source ────────────────────────────────────────────────

@mcp.tool()
def unit_source(target: str, file: str, line: int = 0, context: int = 40) -> dict:
    """Read source code around file:line for a given target repo."""
    p = Path(_target_path(target)) / file
    if not p.exists():
        # try without first segment (some atlas paths drop the repo dir)
        for alt in Path(_target_path(target)).rglob(file.split("/")[-1]):
            if "/.git/" not in str(alt):
                p = alt
                break
    if not p.exists():
        return {"error": f"file not found: {file}", "path": str(p)}
    lines = p.read_text(errors="ignore").splitlines()
    if line <= 0:
        return {"file": file, "total_lines": len(lines), "content": "\n".join(lines[:context])}
    start = max(0, line - 1 - context // 2)
    end = min(len(lines), line + context // 2)
    excerpt = []
    for i in range(start, end):
        prefix = ">>>" if i == line - 1 else "   "
        excerpt.append(f"{i+1:5d} {prefix} {lines[i]}")
    return {"file": file, "line": line, "total_lines": len(lines),
            "excerpt": "\n".join(excerpt)}


# ── tool: grep_repo ──────────────────────────────────────────────

@mcp.tool()
def grep_repo(target: str, pattern: str, max_results: int = 20) -> str:
    """Search source code in a target repo with regex. Returns file:line matches.
    Use to find symbols, patterns, or evidence when writing analysis."""
    from tools.file_ops import grep_in_repo
    return grep_in_repo(_target_path(target), pattern, max_results=max_results)


# ── tool: list_dir ───────────────────────────────────────────────

@mcp.tool()
def list_dir(target: str, path: str = "") -> str:
    """List a directory within the target repo. Use to explore project structure."""
    from tools.file_ops import list_directory
    return list_directory(_target_path(target), path)


# ── tool: lsp_lookup ──────────────────────────────────────────────

@mcp.tool()
def lsp_lookup(target: str, symbol: str, file: str = "") -> str:
    """Jump to a symbol's definition using regex grep.
    Matches function defs, labels, .globl/.global/.macro directives."""
    from tools.file_ops import grep_in_repo
    repo = _target_path(target)
    return grep_in_repo(repo, symbol, max_results=20,
                        file_extensions=".c,.h,.rs,.cpp,.s,.S,.asm")


# ── tool: read_code ───────────────────────────────────────────────

@mcp.tool()
def read_code(target: str, path: str, start_line: int = 1, end_line: int = 0) -> str:
    """Read source code from a file in the target repo. For PDF/Docx, reads pages."""
    from tools.file_ops import read_code_segment
    return read_code_segment(f"{_target_path(target)}/{path}",
                              start_line=start_line, end_line=end_line or None)


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
