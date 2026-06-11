#!/usr/bin/env python3
"""Pre-build corpus fingerprints — one-time, then cached.

Usage:
  python scripts/run.py --build                   # all repos, current branch
  python scripts/run.py --build --branch main     # all repos, specific branch
  python scripts/run.py --build --all-branches    # ALL repos × ALL branches

After this, the MCP server (mcp_server.py) reads from .fp_cache/. The Agent
drives the analysis workflow via MCP tools — build_fingerprint for new repos,
search_similar for 1-vs-N search, compare_functions for deep comparison.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _git_branches(repo_path: str) -> list[str]:
    """List all branch names (local + remote, deduplicated)."""
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "branch", "-a", "--format=%(refname:short)"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return []
        branches = []
        for line in r.stdout.strip().split("\n"):
            line = line.strip()
            if not line or "->" in line:
                continue
            # origin/main → main (prefer short name)
            short = line.replace("origin/", "")
            if short not in branches:
                branches.append(short)
        return branches
    except Exception:
        return []


def build_all(repos_dir: str = "repos", branch: str = "",
              all_branches: bool = False):
    """Pre-build fingerprints for all repos."""
    from scripts.fingerprint import build_units, fingerprint_set, ast_fingerprint_set, lang_summary

    repos = Path(repos_dir)
    if not repos.is_dir():
        print(f"repos dir not found: {repos}")
        return

    entries = sorted(d for d in repos.iterdir() if d.is_dir() and not d.name.startswith("."))
    total_units = 0
    total_fps = 0

    for i, d in enumerate(entries):
        print(f"[{i+1}/{len(entries)}] {d.name}", end="", flush=True)

        branches_to_build = []
        if all_branches:
            branches_to_build = _git_branches(str(d))
            print(f" ({len(branches_to_build)} branches)", end="", flush=True)
        else:
            branches_to_build = [branch] if branch else [""]

        for br in branches_to_build:
            try:
                units = build_units(str(d), branch=br, use_cache=not all_branches or False)
                fps = fingerprint_set(str(d), branch=br)
                ast = ast_fingerprint_set(str(d), branch=br)
                langs = lang_summary(units)
                if all_branches and len(branches_to_build) > 1:
                    print(f"\n    {br}: {len(units)} units, {langs}")
                total_units += len(units)
                total_fps += len(fps)
            except Exception as e:
                print(f"\n    {br}: ERROR — {e}")

        if all_branches and len(branches_to_build) <= 1:
            print()
        elif not all_branches:
            print()

    print(f"\nDone: {len(entries)} repos, {total_units} units, {total_fps} fingerprints")


def main():
    parser = argparse.ArgumentParser(description="Pre-build corpus fingerprints")
    parser.add_argument("--build", action="store_true", help="Build fingerprints for all repos")
    parser.add_argument("--branch", type=str, default="",
                        help="Specific branch to build (default: current branch)")
    parser.add_argument("--all-branches", action="store_true",
                        help="Build fingerprints for ALL branches of ALL repos")
    args = parser.parse_args()

    if not args.build:
        parser.print_help()
        sys.exit(1)

    build_all(branch=args.branch, all_branches=args.all_branches)


if __name__ == "__main__":
    main()
