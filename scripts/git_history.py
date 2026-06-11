#!/usr/bin/env python3
"""Git history analysis for temporal evidence in plagiarism detection.

Usage (via bash):
  python scripts/git_history.py timeline <repo> [branch]
  python scripts/git_history.py compare <repo_a> <repo_b>
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import subprocess
from datetime import datetime


def _git(args: list[str], cwd: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(["git"] + args, cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _target_path(target: str) -> str:
    return str(ROOT / "repos" / target) if "/" not in target else target


def get_repo_timeline(repo_path: str, branch: str = "") -> dict:
    """Get first/last commit dates, author count, commit count."""
    repo = _target_path(repo_path)
    ref = branch if branch else "HEAD"

    first = _git(["log", "--reverse", "--format=%aI", "-1", ref], cwd=repo).strip()
    last = _git(["log", "--format=%aI", "-1", ref], cwd=repo).strip()
    count = _git(["rev-list", "--count", ref], cwd=repo).strip()
    authors = _git(["log", "--format=%an", ref], cwd=repo)
    unique_authors = sorted(set(authors.strip().split("\n")) - {""})

    return {
        "repo": repo_path,
        "branch": branch or "HEAD",
        "first_commit": first,
        "last_commit": last,
        "commit_count": int(count) if count.isdigit() else 0,
        "author_count": len(unique_authors),
        "authors": unique_authors[:10],
    }


def compare_timelines(repo_a: str, repo_b: str) -> dict:
    """Compare two repos' timelines for temporal ordering."""
    tl_a = get_repo_timeline(repo_a)
    tl_b = get_repo_timeline(repo_b)

    def parse_dt(s):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    dt_a = parse_dt(tl_a["first_commit"])
    dt_b = parse_dt(tl_b["first_commit"])

    gap_days = abs((dt_a - dt_b).days) if dt_a and dt_b else None

    return {
        "repo_a": {"name": repo_a, "first_commit": tl_a["first_commit"]},
        "repo_b": {"name": repo_b, "first_commit": tl_b["first_commit"]},
        "earlier": repo_a if (dt_a and dt_b and dt_a < dt_b) else repo_b,
        "time_gap_days": gap_days,
        "note": (f"{repo_a} started earlier" if (dt_a and dt_b and dt_a < dt_b)
                 else f"{repo_b} started earlier" if (dt_a and dt_b)
                 else "Cannot determine — missing dates"),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/git_history.py timeline <repo> [branch]")
        print("  python scripts/git_history.py compare <repo_a> <repo_b>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "timeline":
        repo = sys.argv[2]
        branch = sys.argv[3] if len(sys.argv) > 3 else ""
        import json
        print(json.dumps(get_repo_timeline(repo, branch), indent=2, ensure_ascii=False))
    elif cmd == "compare":
        import json
        print(json.dumps(compare_timelines(sys.argv[2], sys.argv[3]),
                         indent=2, ensure_ascii=False))
