#!/usr/bin/env python3
"""MCP server — exposes fingerprint & comparison data for Claude Code + Skill.

7 tools. The Agent drives the analysis: it reads the repo, decides what to exclude,
picks a base, and interprets similarity results. Scripts only provide raw computation.

Tools:
  build_fingerprint  build fingerprints for a repo (clone + index flow)
  search_similar     1-vs-N similarity search (token + AST + per-dir overlap)
  compare_functions  function-level COPIED/DISGUISE/MODIFIED/NOVEL vs base
  node_taxonomy      kernel design tree skeleton (14 subsystems / 112 leaves)
  compile_flags      generate clangd compile_flags.txt (arch + includes)
  lsp_definition     LSP goto-def (clangd/rust-analyzer, tree-sitter fallback)
  read_doc           read PDF/Docx documents (bash can't do this)
"""
from __future__ import annotations

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


# ── tool: search_similar ─────────────────────────────────────────────

@mcp.tool()
def search_similar(target: str, exclude_prefixes: list[str] | None = None,
                   top_k: int = 10) -> dict:
    """1-vs-N similarity search. Pass exclude_prefixes (e.g. ["vendor/", "dependency/"])
    to filter out external code before computing similarity — the Agent decides these
    after reading the repo structure.

    Returns per-candidate combined score + overlap_by_dir showing which directories
    contributed to the similarity."""
    from scripts.search import search, corpus_fingerprints
    corpus = corpus_fingerprints(build_missing=True)
    results = search(target, corpus=corpus, top_k=top_k,
                     exclude_prefixes=exclude_prefixes)
    return {"target": target, "corpus_size": len(corpus), "candidates": results}


# ── tool: build_fingerprint ──────────────────────────────────────────

@mcp.tool()
def build_fingerprint(target: str) -> dict:
    """Build code fingerprints for a repo (c/cpp/rust + asm) and add to corpus cache.
    Use this when a declared dependency is not in the local repos/ — clone it first,
    then call this to index it."""
    from scripts.fingerprint import build_units, fingerprint_set, ast_fingerprint_set, lang_summary
    units = build_units(_target_path(target))
    fps = fingerprint_set(_target_path(target))
    ast = ast_fingerprint_set(_target_path(target))
    return {"target": target, "units": len(units), "fingerprints": len(fps),
            "ast_fingerprints": len(ast), "languages": lang_summary(units)}


# ── tool: compare_functions ──────────────────────────────────────────

@mcp.tool()
def compare_functions(target: str, base: str,
                      exclude_prefixes: list[str] | None = None) -> dict:
    """Function-level comparison vs a base repo. Returns summary counts and per-file
    breakdown of COPIED/DISGUISE/MODIFIED/NOVEL.

    Pass exclude_prefixes to focus on student code only. The Agent picks base after
    reviewing search_similar results."""
    from scripts.attribute import compare_units
    return compare_units(target, base, exclude_prefixes=exclude_prefixes)


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


# ── tool: lsp_definition ────────────────────────────────────────────

@mcp.tool()
def lsp_definition(target: str, symbol: str, file: str = "") -> str:
    """Real LSP goto-definition via clangd/rust-analyzer. Falls back through
    tree-sitter → language-aware regex → grep → asm lexical parser if LSP
    is unavailable. Returns file:line locations with confidence metadata."""
    from tools.lsp_ops import lsp_get_definition
    return lsp_get_definition(_target_path(target), file, symbol)


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
