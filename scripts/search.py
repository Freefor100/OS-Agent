#!/usr/bin/env python3
"""1-vs-N similarity search — single target against the corpus.

Computes bidirectional containment (token + AST) and returns top-K candidates.
Accepts an optional exclude_prefixes list so the caller (Agent) can filter out
external dependencies before searching — without this, shared vendored code
dominates the ranking and hides real student-code similarity.

Output: [{repo, token_min, ast_min, combined, is_framework, year, overlap_by_dir}]
sorted by combined descending.
"""
from __future__ import annotations

import os
import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fingerprint import build_units, fingerprint_set, ast_fingerprint_set

CACHE = Path(".fp_cache")


def corpus_fingerprints(*, branch: str = "", build_missing: bool = False) -> dict[str, set[str]]:
    """Corpus fingerprint index — branch-aware.

    branch="" (default) → loads ALL branch caches, keyed by "repo__branch".
      search_similar returns per-branch candidates. This is the normal mode:
      pre-fingerprint all branches, then search naturally reveals which
      branch of a competitor's repo is most similar.

    branch="main" → loads only fpset_*__main.pkl, keyed by "repo" (old behavior).
      This is for focused searches where Agent has already determined which
      branch matters.

    build_missing=True → lazily build uncached repos.
    """
    safe_branch = branch.replace("/", "-") if branch else ""
    fpsets: dict[str, set[str]] = {}
    for f in sorted(CACHE.glob("fpset_*.pkl")):
        stem = f.stem.replace("fpset_", "")
        if safe_branch:
            # Filtered mode: load only matching branch, key by repo name
            suffix = f"__{safe_branch}"
            if stem.endswith(suffix):
                name = stem[:-len(suffix)]
                fpsets[name] = pickle.loads(f.read_bytes())
        else:
            # Default mode: ALL branches, key by "repo__branch"
            if "__" in stem:
                name = stem[:stem.index("__")]
                br = stem[stem.index("__") + 2:]
                key = f"{name}__{br}"
            else:
                key = stem  # old format, no branch info
            fpsets[key] = pickle.loads(f.read_bytes())

    if not build_missing:
        return fpsets
    repos = Path("repos")
    if repos.is_dir():
        for d in sorted(repos.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if any(k.startswith(d.name) for k in fpsets):
                continue
            try:
                fpsets[d.name] = fingerprint_set(str(d), branch=branch)
            except Exception:
                pass
    return fpsets


def _filtered_sets(target: str, exclude_prefixes: list[str] | None, branch: str = ""):
    """Build filtered fingerprint + AST sets for target, skipping excluded paths.

    Returns (fp_set, ast_set, fp_to_dir) where fp_to_dir maps each fingerprint
    to its source directory (for overlap_by_dir breakdown).
    """
    units = build_units(f"repos/{target}" if "/" not in target else target,
                        branch=branch, use_cache=True)

    fp_set: set[str] = set()
    ast_set: set[str] = set()
    fp_to_dir: dict[str, str] = {}

    prefixes = exclude_prefixes or []
    for u in units:
        f = u["file"]
        if any(f == p or f.startswith(p + "/") or f.startswith(p) for p in prefixes):
            continue
        fp_set.add(u["fp"])
        if u.get("ast") and u["lang"] != "asm":
            ast_set.add(u["ast"])
        d = os.path.dirname(f) or "(root)"
        fp_to_dir[u["fp"]] = d

    return fp_set, ast_set, fp_to_dir


def _overlap_breakdown(fp_set: set[str], candidate_fps: set[str],
                       fp_to_dir: dict[str, str]) -> dict[str, dict]:
    """Compute per-directory overlap between target and candidate."""
    inter = fp_set & candidate_fps
    dir_shared: dict[str, int] = defaultdict(int)
    dir_target: dict[str, int] = defaultdict(int)

    for fp, d in fp_to_dir.items():
        dir_target[d] += 1
        if fp in inter:
            dir_shared[d] += 1

    result = {}
    for d in sorted(dir_shared, key=lambda k: -dir_shared[k]):
        result[d] = {"shared": dir_shared[d], "target": dir_target[d]}
    return result


def _parse_corpus_key(key: str) -> tuple[str, str]:
    """Parse corpus dict key into (repo_name, branch).
    "xv6-k210__scene" → ("xv6-k210", "scene")
    "xv6-k210" → ("xv6-k210", "")
    """
    if "__" in key:
        idx = key.index("__")
        return key[:idx], key[idx + 2:]
    return key, ""


def search(target: str, corpus: dict[str, set[str]] | None = None,
           top_k: int = 20,
           exclude_prefixes: list[str] | None = None,
           branch: str = "",
           metadata=None) -> list[dict]:
    """1-vs-N bidirectional containment search (token + AST).

    exclude_prefixes: dir/file prefixes to skip in target.
    branch: target repo's cache namespace.
    metadata: MetadataManager instance for authoritative year/is_framework.

    Returns [{repo, branch, token_min, ast_min, combined, is_framework, year, school, overlap_by_dir}]
    sorted by combined descending. When corpus keys are "repo__branch" (all-branch mode),
    the 'repo' and 'branch' fields show which specific branch matched.
    """
    t_fps, t_ast, fp_to_dir = _filtered_sets(target, exclude_prefixes, branch)

    if corpus is None:
        corpus = corpus_fingerprints(branch=branch)

    results = []
    for key in corpus:
        # Parse compound key: "repo_name__branch" or "repo_name"
        c_name, c_branch = _parse_corpus_key(key)

        # Skip self (same repo name, regardless of branch)
        target_name = target if "/" not in target else Path(target).name
        if c_name == target_name or not corpus[key]:
            continue

        c_fps = corpus[key]
        inter_tok = len(t_fps & c_fps)
        tok_min = (min(inter_tok / len(t_fps), inter_tok / len(c_fps))
                   if t_fps and c_fps else 0.0)

        try:
            c_ast = ast_fingerprint_set(f"repos/{c_name}", branch=c_branch)
        except Exception:
            c_ast = set()
        inter_ast = len(t_ast & c_ast)
        ast_min = (min(inter_ast / len(t_ast), inter_ast / len(c_ast))
                   if t_ast and c_ast else 0.0)

        combined = max(tok_min, ast_min)

        overlap = _overlap_breakdown(t_fps, c_fps, fp_to_dir) if t_fps else {}

        # Metadata-driven framework/year (preferred) or regex fallback
        if metadata:
            meta = metadata.lookup_by_repo_name(c_name)
            is_fw = metadata.is_framework(c_name)
            year = meta["year"] if meta else _extract_year(c_name)
            school = meta["school"] if meta else ""
        else:
            is_fw = False
            year = _extract_year(c_name)
            school = ""

        results.append({
            "repo": c_name,
            "branch": c_branch,
            "token_min": round(tok_min, 3),
            "ast_min": round(ast_min, 3),
            "combined": round(combined, 3),
            "is_framework": is_fw,
            "year": year,
            "school": school,
            "overlap_by_dir": overlap,
        })

    results.sort(key=lambda r: -r["combined"])
    return results[:top_k]


def _extract_year(name: str) -> int:
    """Extract contest year from repo name (fallback when no xlsx metadata).
    T20241xxx → 2024, oskernel2023-xxx → 2023."""
    m = re.search(r"T20(2[0-9])", name) or re.search(r"20(19|2[0-5])", name)
    if m and m.group(0).startswith("T"):
        return int(m.group(0)[1:])
    return int(m.group(0)) if m else 0


if __name__ == "__main__":
    target = sys.argv[1]
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    prefixes = sys.argv[3:] if len(sys.argv) > 3 else None
    candidates = search(target, top_k=top, exclude_prefixes=prefixes)
    filt = " (filtered)" if prefixes else ""
    print(f"{target}{filt}  vs  corpus ({len(corpus_fingerprints())} members):\n")
    for r in candidates:
        tag = " [fw]" if r["is_framework"] else ""
        print(f"  combined={r['combined']:.3f}  tok={r['token_min']:.3f}  ast={r['ast_min']:.3f}  "
              f"{r['repo'][:36]}{tag}")
        if r.get("overlap_by_dir"):
            for d, st in list(r["overlap_by_dir"].items())[:5]:
                print(f"    {d:40s} shared={st['shared']:4d}/{st['target']:4d}")
