#!/usr/bin/env python3
"""Batch fingerprint building and analysis for all repos.

Usage (via bash):
  python scripts/batch.py --fingerprint --branch main
  python scripts/batch.py --search T202410487992457-1800 --branch main
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.metadata import MetadataManager
from scripts.fingerprint import build_units, fingerprint_set, ast_fingerprint_set, lang_summary


def batch_fingerprint(repos_dir: str = "repos", branch: str = "",
                      limit: int = 0, skip_existing: bool = True):
    """Build fingerprints for all repos. Returns dict of {name: summary}."""
    results = {}
    repos = Path(ROOT / repos_dir)
    if not repos.is_dir():
        print(f"repos dir not found: {repos}")
        return results

    entries = sorted(d for d in repos.iterdir() if d.is_dir() and not d.name.startswith("."))
    if limit:
        entries = entries[:limit]

    print(f"Building fingerprints for {len(entries)} repos (branch={branch or 'current'})")
    for i, d in enumerate(entries):
        try:
            if skip_existing:
                from scripts.fingerprint import _cache_path
                if _cache_path("fpset", str(d), branch).exists():
                    print(f"  [{i+1}/{len(entries)}] {d.name} — cached, skip")
                    continue

            units = build_units(str(d), branch=branch)
            fps = fingerprint_set(str(d), branch=branch)
            ast = ast_fingerprint_set(str(d), branch=branch)
            langs = lang_summary(units)
            results[d.name] = {"units": len(units), "fps": len(fps),
                               "ast_fps": len(ast), "langs": langs}
            print(f"  [{i+1}/{len(entries)}] {d.name}: {len(units)} units, {langs}")
        except Exception as e:
            print(f"  [{i+1}/{len(entries)}] {d.name}: ERROR — {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Batch operations for OS-Agent")
    parser.add_argument("--fingerprint", action="store_true", help="Build fingerprints for all repos")
    parser.add_argument("--branch", type=str, default="", help="Branch namespace for cache key")
    parser.add_argument("--limit", type=int, default=0, help="Limit to N repos")
    parser.add_argument("--no-skip", action="store_true", help="Don't skip cached repos")
    args = parser.parse_args()

    if args.fingerprint:
        results = batch_fingerprint(
            branch=args.branch, limit=args.limit,
            skip_existing=not args.no_skip,
        )
        total_units = sum(r["units"] for r in results.values())
        print(f"\nDone: {len(results)} repos, {total_units} total units")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
