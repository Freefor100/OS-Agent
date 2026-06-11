#!/usr/bin/env python3
"""One-shot migration: rename .fp_cache/*.pkl to branch-aware format.

Detects the current checked-out branch for each repo and renames:
  fpset_{name}.pkl        → fpset_{name}__{branch}.pkl
  units_{name}.pkl        → units_{name}__{branch}.pkl
  astset_{name}.pkl       → astset_{name}__{branch}.pkl

Files that already have __branch suffix are skipped (idempotent).

Usage:
  python scripts/migrate_cache.py --dry-run    # preview only
  python scripts/migrate_cache.py --force      # execute renames
  python scripts/migrate_cache.py --force --repo xv6-k210  # single repo
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".fp_cache"
REPOS = ROOT / "repos"

PREFIXES = ("fpset_", "units_", "astset_")
__BRANCH_RE = re.compile(r"__(.+)$")


def _sanitize_branch(branch: str) -> str:
    """Replace / with - to make branch name filesystem-safe."""
    return branch.replace("/", "-")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("migrate")


def _git_current_branch(repo_path: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _git_default_branch(repo_path: str) -> str:
    """Try to detect the default branch from origin/HEAD."""
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        ref = r.stdout.strip()
        return ref.replace("refs/remotes/origin/", "") if ref else ""
    except Exception:
        return ""


def migrate(dry_run: bool = True, single_repo: str = "") -> list[str]:
    """Migrate cache files. Returns list of rename operations performed/planned."""
    renames = []

    # Collect affected repos from cache files
    repos_seen: set[str] = set()
    cache_files: list[Path] = []
    for pkl in sorted(CACHE.glob("*.pkl")):
        stem = pkl.stem
        # Check if already branch-aware
        if "__" in stem:
            continue
        # Extract repo name
        for prefix in PREFIXES:
            if stem.startswith(prefix):
                name = stem[len(prefix):]
                repos_seen.add(name)
                cache_files.append(pkl)
                break

    if single_repo:
        repos_seen = {single_repo}
        cache_files = [f for f in cache_files
                       if any(f.stem == f"{p}{single_repo}" for p in PREFIXES)]

    logger.info(f"Cache files to migrate: {len(cache_files)}")
    logger.info(f"Repos involved: {len(repos_seen)}")

    # Detect branch for each repo
    repo_branch: dict[str, str] = {}
    for name in sorted(repos_seen):
        repo_path = str(REPOS / name)
        if not Path(repo_path).is_dir():
            logger.warning(f"  Repo not found: {name} → using 'unknown'")
            repo_branch[name] = "unknown"
            continue
        branch = _git_current_branch(repo_path)
        if not branch:
            # detached HEAD — try default branch
            branch = _git_default_branch(repo_path)
        if not branch:
            branch = "detached"
        repo_branch[name] = branch

    # Show mapping
    branch_counts: dict[str, int] = {}
    for name, branch in sorted(repo_branch.items()):
        branch_counts[branch] = branch_counts.get(branch, 0) + 1
        logger.info(f"  {name:45s} → {branch}")

    logger.info(f"\nBranch distribution:")
    for branch, count in sorted(branch_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {branch}: {count} repos")

    # Rename
    for pkl in cache_files:
        stem = pkl.stem
        for prefix in PREFIXES:
            if stem.startswith(prefix):
                name = stem[len(prefix):]
                break
        else:
            continue

        if name not in repo_branch:
            continue

        branch = repo_branch[name]
        safe_branch = _sanitize_branch(branch)
        new_path = CACHE / f"{pkl.stem}__{safe_branch}.pkl"

        if new_path.exists():
            logger.warning(f"  SKIP (target exists): {pkl.name}")
            continue

        renames.append(f"{pkl.name} → {new_path.name}")
        if not dry_run:
            pkl.rename(new_path)

    return renames


def main():
    parser = argparse.ArgumentParser(description="Migrate .fp_cache to branch-aware naming")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview renames without executing (default)")
    parser.add_argument("--force", action="store_true",
                        help="Execute the migration")
    parser.add_argument("--repo", type=str, default="",
                        help="Migrate a single repo only")
    args = parser.parse_args()

    dry_run = not args.force
    if args.force:
        logger.info("=== EXECUTING MIGRATION ===")
    else:
        logger.info("=== DRY RUN (use --force to execute) ===")

    renames = migrate(dry_run=dry_run, single_repo=args.repo)

    logger.info(f"\n{'Would rename' if dry_run else 'Renamed'} {len(renames)} files:")
    for r in renames[:20]:
        logger.info(f"  {r}")
    if len(renames) > 20:
        logger.info(f"  ... and {len(renames) - 20} more")

    if dry_run and renames:
        logger.info("\nRun with --force to execute.")


if __name__ == "__main__":
    main()
