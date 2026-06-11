#!/usr/bin/env python3
"""Pre-build corpus fingerprints — one-time, then cached.

Usage:
  python scripts/run.py --build    # pre-build fingerprints for all repos in repos/

After this, the MCP server (mcp_server.py) reads from .fp_cache/. The Agent
drives the analysis workflow via MCP tools — build_fingerprint for new repos,
search_similar for 1-vs-N search, compare_functions for deep comparison.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if sys.argv[1:] != ["--build"]:
        print("Usage: python scripts/run.py --build")
        print()
        print("  --build  Pre-build fingerprints for all repos in repos/ (one-time, cached)")
        print()
        print("  For single-repo analysis, use the MCP server + Agent (SKILL.md).")
        sys.exit(1)

    print("Pre-building corpus fingerprints (one-time, then cached forever)...")
    subprocess.run([sys.executable, "-c",
                    "from scripts.search import corpus_fingerprints; "
                    "c=corpus_fingerprints(build_missing=True); "
                    f"print(f'corpus: {{len(c)}} repos indexed')"],
                   check=False)


if __name__ == "__main__":
    main()
