#!/usr/bin/env python3
"""Deterministic pipeline: build fingerprints + search + deep compare.

This stage produces all the data that the MCP server exposes to Claude Code.
The report (HTML + natural-language analysis) is produced by Claude Code
via MCP + SKILL.md — NOT by this script.

Usage:
  python scripts/run.py <target>            # single repo: build + search + compare
  python scripts/run.py --build             # pre-build corpus fingerprints (once)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run_one(target: str):
    print(f"\n=== {target} ===")

    # [0] compile_flags for LSP (clangd reads compile_flags.txt)
    subprocess.run([sys.executable, "scripts/compile_flags.py", f"repos/{target}"], check=False)

    # [A] declarations → Cargo structure + git deps + lineage refs
    print("  [A] declarations...")
    subprocess.run([sys.executable, "scripts/declarations.py", target], check=False)

    # [B] fingerprint → units cached to .fp_cache/ (c/cpp/rust + asm)
    print("  [B] fingerprint...")
    subprocess.run([sys.executable, "-c",
                    f"from scripts.fingerprint import build_units; u=build_units('repos/{target}'); print(f'  units={len(u)}')"],
                   check=False)

    # [C] 1-vs-N search → top-K similar corpus members
    print("  [C] search...")
    subprocess.run([sys.executable, "scripts/search.py", target, "10"], check=False)

    # [D] deep compare vs best candidate (COPIED/DISGUISE/MODIFIED/NOVEL)
    print("  [D] deep compare...")
    subprocess.run([sys.executable, "scripts/attribute.py", target], check=False)

    # Done — all MCP tools now have cached data. Claude Code + Skill produces the report.
    print(f"\n  pipeline complete. MCP tools now have cached data for {target}.")
    print(f"  Run Claude Code with .mcp.json + SKILL.md to produce the report.")


def main():
    if sys.argv[1:] == ["--build"]:
        print("pre-building corpus fingerprints (one-time, then cached)...")
        subprocess.run([sys.executable, "-c",
                        "from scripts.search import corpus_fingerprints; "
                        "c=corpus_fingerprints(build_missing=True); "
                        "print(f'corpus: {len(c)} repos indexed')"],
                       check=False)
    else:
        run_one(sys.argv[1])


if __name__ == "__main__":
    main()
