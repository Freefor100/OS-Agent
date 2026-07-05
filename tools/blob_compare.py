#!/usr/bin/env python3
"""Blob-level cross-repo comparison using git ls-tree -r.

Same file content = same SHA-1, always. No parsing, no normalization, O(1) per file.
Cross-repo fully reproducible — the preferred baseline tool before AST fingerprinting.

Usage:
    from tools.blob_compare import get_blobs, compare

    blobs_a = get_blobs('/path/to/repo_a')
    blobs_b = get_blobs('/path/to/repo_b')
    result = compare(blobs_a, blobs_b)
    print(f"Coverage: {result['coverage_a']:.1%}")
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


DEFAULT_EXTS = frozenset({".rs", ".c", ".h", ".S", ".cpp", ".cc", ".cxx"})


def get_blobs(repo_path: str | Path, *,
              exts: frozenset[str] | set[str] | None = None) -> set[tuple[str, str]]:
    """Return set of (blob_hash, path) for all source files in a repo commit.

    Args:
        repo_path: Path to git repo (working directory is changed temporarily)
        exts: File extensions to include (default: .rs .c .h .S .cpp .cc .cxx)
    """
    exts = exts if exts is not None else DEFAULT_EXTS
    result: set[tuple[str, str]] = set()
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "ls-tree", "-r", "HEAD"],
        capture_output=True, text=True,
    )
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            blob, path = parts[2], parts[3]
            if any(path.endswith(ext) for ext in exts):
                result.add((blob, path))
    return result


def compare(repo_a: str | Path, repo_b: str | Path, *,
            exts: frozenset[str] | set[str] | None = None,
            base_repo: str | Path | None = None) -> dict[str, Any]:
    """Compare two repos at the blob level.

    Returns dict with:
        total_a, total_b: file counts
        same_path: files with same hash and same relative path
        same_blob_only: files with same hash but different path (reorganized)
        unique_a_blobs, unique_b_blobs: blobs only in one repo
        coverage_a: same_blob / total_a
        coverage_b: same_blob / total_b
        by_dir: per-directory breakdown
    """
    blobs_a = get_blobs(repo_a, exts=exts)
    blobs_b = get_blobs(repo_b, exts=exts)

    same_path = blobs_a & blobs_b

    a_blob_map: dict[str, str] = {}
    for blob, path in blobs_a:
        a_blob_map[blob] = path
    b_blob_map: dict[str, str] = {}
    for blob, path in blobs_b:
        b_blob_map[blob] = path

    a_blobs_only = set(a_blob_map) - set(b_blob_map)
    b_blobs_only = set(b_blob_map) - set(a_blob_map)
    shared_blobs = set(a_blob_map) & set(b_blob_map)

    # Files with same content, different path
    same_blob_diff_path = len(shared_blobs) - len(same_path)

    # Per-directory breakdown
    by_dir: dict[str, dict[str, int]] = {}
    dirs_a: dict[str, set[tuple[str, str]]] = {}
    dirs_b: dict[str, set[tuple[str, str]]] = {}
    for blob, path in blobs_a:
        d = str(Path(path).parent) or "(root)"
        dirs_a.setdefault(d, set()).add((blob, path))
    for blob, path in blobs_b:
        d = str(Path(path).parent) or "(root)"
        dirs_b.setdefault(d, set()).add((blob, path))

    all_dirs = sorted(set(dirs_a) | set(dirs_b))
    for d in all_dirs:
        aa = dirs_a.get(d, set())
        bb = dirs_b.get(d, set())
        same_d = aa & bb
        by_dir[d] = {"a": len(aa), "b": len(bb), "same": len(same_d)}

    # Base-aware comparison
    base_stats = None
    if base_repo:
        blobs_base = get_blobs(base_repo, exts=exts)
        # Blobs shared with base by each repo
        base_blob_set = {b for b, _ in blobs_base}
        a_base = len(set(a_blob_map) & base_blob_set)
        b_base = len(set(b_blob_map) & base_blob_set)
        base_stats = {
            "base_total": len(blobs_base),
            "a_vs_base_same": a_base,
            "a_vs_base_coverage": a_base / len(blobs_a) if blobs_a else 0.0,
            "b_vs_base_same": b_base,
            "b_vs_base_coverage": b_base / len(blobs_b) if blobs_b else 0.0,
        }

    return {
        "total_a": len(blobs_a),
        "total_b": len(blobs_b),
        "same_path": len(same_path),
        "same_blob_diff_path": same_blob_diff_path,
        "shared_blobs": len(shared_blobs),
        "unique_a_blobs": len(a_blobs_only),
        "unique_b_blobs": len(b_blobs_only),
        "coverage_a": len(shared_blobs) / len(blobs_a) if blobs_a else 0.0,
        "coverage_b": len(shared_blobs) / len(blobs_b) if blobs_b else 0.0,
        "by_dir": by_dir,
        "base_stats": base_stats,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <repo_a> <repo_b> [base_repo]")
        sys.exit(1)
    base = sys.argv[3] if len(sys.argv) > 3 else None
    result = compare(sys.argv[1], sys.argv[2], base_repo=base)
    for k, v in result.items():
        if k == "by_dir":
            print(f"{k}: {len(v)} directories")
        elif k == "base_stats":
            if v:
                print(f"base: {v['base_total']} files, a_cov={v['a_vs_base_coverage']:.1%}, b_cov={v['b_vs_base_coverage']:.1%}")
        else:
            if isinstance(v, float):
                print(f"{k}: {v:.4f}")
            else:
                print(f"{k}: {v}")
