#!/usr/bin/env python3
"""MCP server — exposes fingerprint & comparison data for Claude Code + Skill.

12 tools. The Agent drives the analysis: it reads the repo, decides what to exclude,
picks a base, and interprets similarity results. Scripts only provide raw computation.

Branch handling: Agent uses bash (git branch -a, git log, git show) to explore
branches. All branches are pre-fingerprinted (run.py --all-branches). Search
returns per-branch candidates so preference emerges from data, not script judgment.

Tools:
  repo_metadata       lookup submission metadata from collected-data.xlsx
  build_fingerprint   build fingerprints for a repo (branch-aware, all-branches)
  search_similar      1-vs-N similarity search (token + AST + per-dir overlap)
  compare_functions   function-level COPIED/DISGUISE/MODIFIED/NOVEL vs base
  node_taxonomy       kernel design tree skeleton (14 subsystems / 112 leaves)
  compile_flags       generate clangd compile_flags.txt (arch + includes)
  lsp_definition      LSP goto-def (clangd/rust-analyzer, tree-sitter fallback)
  lsp_references      LSP find-all-references (cross-file symbol usage)
  lsp_document_outline LSP document symbols (functions/structs with line numbers)
  lsp_call_graph      LSP call hierarchy (outgoing + incoming, recursive tree)
  lsp_set_target_arch override target triple for architecture-specific analysis
  read_doc            read PDF/Docx documents (bash can't do this)
"""
from __future__ import annotations

import sys
from pathlib import Path

# ensure repo root on sys.path BEFORE importing project modules
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("os-agent")

# ── singletons (lazy init) ──────────────────────────────────────────

_metadata_mgr = None


def _get_metadata():
    global _metadata_mgr
    if _metadata_mgr is None:
        from core.metadata import MetadataManager
        _metadata_mgr = MetadataManager()
    return _metadata_mgr


# ── helpers ──────────────────────────────────────────────────────────

def _target_path(target: str) -> str:
    return f"repos/{target}" if "/" not in target else target


# ── tool: repo_metadata ──────────────────────────────────────────────

@mcp.tool()
def repo_metadata(target: str) -> dict:
    """Lookup submission metadata from collected-data.xlsx by repo name or path.
    Returns year, school, team_name, competition, sub_event, is_framework.
    If the repo is not found in xlsx, returns is_framework=true with no school/team info.
    Use this in Phase 1 to get authoritative metadata instead of guessing from repo names."""
    mm = _get_metadata()
    # Try by repo name first, then by path
    meta = mm.lookup_by_repo_name(target)
    if not meta:
        meta = mm.lookup_by_repo_path(target)
    if meta:
        return {
            "repo": target,
            "year": meta["year"],
            "school": meta["school"],
            "team": meta["team_name"],
            "competition": meta["competition"],
            "sub_event": meta["sub_event"],
            "repo_url": meta["repo_url"],
            "is_framework": False,
        }
    return {
        "repo": target,
        "is_framework": True,
        "note": "Not found in xlsx — likely a framework or baseline reference",
    }



# ── tool: build_fingerprint ──────────────────────────────────────────

@mcp.tool()
def build_fingerprint(target: str, branch: str = "", all_branches: bool = False) -> dict:
    """Build code fingerprints for a repo (c/cpp/rust + asm) and add to corpus cache.
    Use this when a declared dependency is not in the local repos/ — clone it first,
    then call this to index it.

    branch: cache namespace key for a single branch. Does NOT checkout.
    all_branches: if True, builds fingerprints for ALL branches of the repo.
      Agent should first: git -C repos/<target> branch -a
      Then: build_fingerprint(target, all_branches=True)
      This enables search_similar to find which branch of another repo is most similar."""
    from scripts.fingerprint import build_units, fingerprint_set, ast_fingerprint_set, lang_summary
    import subprocess

    if all_branches:
        # List all branches via git, then build each
        repo_path = _target_path(target)
        r = subprocess.run(
            ["git", "-C", repo_path, "branch", "-a", "--format=%(refname:short)"],
            capture_output=True, text=True, timeout=10,
        )
        branches = []
        for line in r.stdout.strip().split("\n"):
            line = line.strip()
            if line and "->" not in line:
                short = line.replace("origin/", "")
                if short not in branches:
                    branches.append(short)

        results = {}
        for br in branches:
            units = build_units(repo_path, branch=br)
            fps = fingerprint_set(repo_path, branch=br)
            ast = ast_fingerprint_set(repo_path, branch=br)
            results[br] = {"units": len(units), "fingerprints": len(fps),
                           "ast_fingerprints": len(ast), "languages": lang_summary(units)}
        return {"target": target, "all_branches": True, "branches": len(results),
                "results": results}

    units = build_units(_target_path(target), branch=branch)
    fps = fingerprint_set(_target_path(target), branch=branch)
    ast = ast_fingerprint_set(_target_path(target), branch=branch)
    return {"target": target, "branch": branch or "(default)", "units": len(units),
            "fingerprints": len(fps), "ast_fingerprints": len(ast),
            "languages": lang_summary(units)}


# ── tool: search_similar ─────────────────────────────────────────────

@mcp.tool()
def search_similar(target: str, exclude_prefixes: list[str] | None = None,
                   top_k: int = 10, branch: str = "") -> dict:
    """1-vs-N similarity search. Pass exclude_prefixes (e.g. ["vendor/", "dependency/"])
    to filter out external code before computing similarity — the Agent decides these
    after reading the repo structure.

    Returns per-candidate combined score + overlap_by_dir showing which directories
    contributed to the similarity. is_framework and year are driven by xlsx metadata.

    branch: fingerprint cache namespace (matches build_fingerprint's branch parameter)."""
    from scripts.search import search, corpus_fingerprints
    mm = _get_metadata()
    corpus = corpus_fingerprints(branch=branch, build_missing=True)
    results = search(target, corpus=corpus, top_k=top_k,
                     exclude_prefixes=exclude_prefixes, branch=branch,
                     metadata=mm)
    return {"target": target, "branch": branch or "(default)",
            "corpus_size": len(corpus), "candidates": results}


# ── tool: compare_functions ──────────────────────────────────────────

@mcp.tool()
def compare_functions(target: str, base: str,
                      exclude_prefixes: list[str] | None = None,
                      branch: str = "", base_branch: str = "") -> dict:
    """Function-level comparison vs a base repo. Returns summary counts and per-file
    breakdown of COPIED/DISGUISE/MODIFIED/NOVEL.

    Pass exclude_prefixes to focus on student code only. The Agent picks base after
    reviewing search_similar results.

    branch: target repo's cache namespace.
    base_branch: base repo's cache namespace."""
    from scripts.attribute import compare_units
    return compare_units(target, base, exclude_prefixes=exclude_prefixes,
                         branch=branch, base_branch=base_branch)


# ── tool: node_taxonomy ──────────────────────────────────────────────

@mcp.tool()
def node_taxonomy(node_id: str = "") -> dict:
    """Kernel design tree skeleton — the report framework. 14 subsystems, 112 leaf nodes.

    Pass node_id to get one node's detail (title + scope + vocab terms).
    Empty = full tree + analysis batches.

    The tree ORGANIZES the report; it does NOT judge plagiarism or workload.
    - scope: one-line boundary — what work counts as this node. Read it before
      deciding which functions belong here. Function→node assignment is YOUR call.
    - vocab: naming SUGGESTIONS so you describe mechanisms in standard terms
      (e.g. "MLFQ scheduler"). NOT a checklist, NOT graded, NOT evidence of work.
      You may name mechanisms not listed here. Judge by fingerprint diff; name by vocab.
    - batches: explore in this cross-module dependency order. Earlier batches feed
      later judgement (e.g. context-switch + lock are analyzed alongside scheduler).
    """
    from core.kernel_tree import (
        ROOT_NODES_V2, ANALYSIS_ORDER_V2, ANALYSIS_BATCHES_V2,
        VOCAB_BY_NODE, node_title_zh, node_title_en, node_scope,
    )

    def _vocab_terms(nid: str) -> list[str]:
        v = VOCAB_BY_NODE.get(nid, {})
        return [m["tag"] for m in v.get("mechanisms", [])]

    if node_id:
        return {
            "node_id": node_id,
            "title_zh": node_title_zh(node_id),
            "title_en": node_title_en(node_id),
            "scope": node_scope(node_id),
            "vocab": _vocab_terms(node_id),
        }

    tree = {}
    for root, children in ROOT_NODES_V2.items():
        tree[root] = {
            "title_zh": node_title_zh(root),
            "title_en": node_title_en(root),
            "children": [
                {"id": c, "title_zh": node_title_zh(c), "scope": node_scope(c),
                 "vocab": _vocab_terms(c)}
                for c in children
            ],
        }
    return {
        "roots": tree,
        "leaf_count": len(ANALYSIS_ORDER_V2),
        "order": ANALYSIS_ORDER_V2,
        "batches": ANALYSIS_BATCHES_V2,
        "batch_note": "Explore batch-by-batch in this cross-module dependency order; "
                      "write findings back to report_data.json context after each batch.",
    }


# ── tool: compile_flags ──────────────────────────────────────────────

@mcp.tool()
def compile_flags(target: str) -> dict:
    """Generate compile_flags.txt for LSP (clangd/rust-analyzer). Detects
    architecture, include paths, and defines from Makefile/Cargo.toml.
    clangd reads this automatically — no GCC cross-compiler needed."""
    from scripts.compile_flags import generate, _detect_arch
    repo = _target_path(target)
    content = generate(repo)
    Path(repo, "compile_flags.txt").write_text(content + "\n")
    return {"target": target, "arch": _detect_arch(Path(repo)),
            "flags": content.splitlines()}


# ── tools: LSP (exposing 5 lsp_ops.py @tool functions) ──────────────

@mcp.tool()
def lsp_definition(target: str, symbol: str, file: str = "") -> str:
    """Real LSP goto-definition via clangd/rust-analyzer. Falls back through
    tree-sitter → language-aware regex → grep → asm lexical parser if LSP
    is unavailable. Returns file:line locations with confidence metadata."""
    from tools.lsp_ops import lsp_get_definition
    return lsp_get_definition(_target_path(target), file, symbol)


@mcp.tool()
def lsp_references(target: str, symbol: str, file: str = "") -> str:
    """LSP find-all-references. Returns file:line locations where the symbol is used
    across the entire project. Falls back through tree-sitter → language-aware regex
    → grep → asm lexical parser.

    Use this when tracing copy patterns — see if a suspicious function is called from
    the same places as in the base repo, or if it has been integrated differently."""
    from tools.lsp_ops import lsp_get_references
    return lsp_get_references(_target_path(target), file, symbol)


@mcp.tool()
def lsp_document_outline(target: str, file: str) -> str:
    """LSP document symbol outline. Returns all functions, structs, enums, constants
    with line numbers. Useful as a pre-read map before diving into large kernel files
    (500+ lines). Saves the Agent from blindly reading entire files."""
    from tools.lsp_ops import lsp_get_document_outline
    return lsp_get_document_outline(_target_path(target), file)


@mcp.tool()
def lsp_call_graph(target: str, symbol: str, file: str,
                   direction: str = "outgoing", max_depth: int = 3) -> str:
    """LSP call hierarchy — recursively builds a call graph tree.
    'outgoing' = functions called BY this symbol (who does it call).
    'incoming' = functions that call THIS symbol (who calls it).
    'both' = both directions.

    Essential for tracing kernel critical paths (fork, page_fault, syscall handler)
    and verifying whether copied code has been re-integrated or just pasted in.

    max_depth: 1-5 (default 3). Contains built-in crash recovery for build.rs failures."""
    from tools.lsp_ops import lsp_get_call_graph
    return lsp_get_call_graph(_target_path(target), file, symbol, direction, max_depth)


@mcp.tool()
def lsp_set_target_arch(target: str, arch: str) -> str:
    """Override auto-detected target triple for LSP. Force-restarts clangd/rust-analyzer
    for the repo. Use when #[cfg] code is grayed out or LSP returns empty results due
    to wrong architecture detection.

    Common target triples:
    - riscv64gc-unknown-none-elf (RISC-V 64)
    - loongarch64-unknown-none-elf (LoongArch 64)
    - x86_64-unknown-none-elf (x86_64 Bare Metal)
    - aarch64-unknown-none-elf (ARM64 Bare Metal)"""
    from tools.lsp_ops import lsp_set_target_arch
    return lsp_set_target_arch(_target_path(target), arch)


# ── tool: read_doc ───────────────────────────────────────────────────

@mcp.tool()
def read_doc(target: str, path: str, start_page: int = 1, end_page: int = 0) -> str:
    """Read a PDF or Docx document from the target repo. For PDF, reads pages.
    For Docx, reads paragraphs. Claude Code's built-in bash can't do this."""
    from tools.file_ops import read_code_segment
    return read_code_segment(f"{_target_path(target)}/{path}",
                             start_page=start_page, end_page=end_page or None)


# ── entry ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
