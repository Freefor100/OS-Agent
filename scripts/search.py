#!/usr/bin/env python3
"""Stage-3 1-vs-N rough search — single target against the corpus.

Replaces v1's all-pairs N×N approach. Takes one target repo, scans all cached
fingerprint sets in .fp_cache/, computes bidirectional containment, and returns
top-K candidates ranked by min(A in B, B in A). Pure deterministic — no LLM.

Corpus fingerprints are built lazily on first scan and cached; subsequent
searches are instant.

Output: list of {repo, containment_a_in_b, containment_b_in_a, min} sorted by min.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fingerprint import fingerprint_set, ast_fingerprint_set

CACHE = Path(".fp_cache")
# repos that are frameworks/baselines, not competition submissions — they appear
# in search results but are tagged so the caller can distinguish
FRAMEWORKS = {"_baseline_oscomp-arceos", "arceos", "rCore-Tutorial-v3", "ucore_os_lab",
              "ucore-smp", "Starry", "starry-mix", "zCore", "xv6-riscv", "xv6-public",
              "xv6-k210"}


def corpus_fingerprints(build_missing: bool = False) -> dict[str, set[str]]:
    """Corpus fingerprint index. Cached-only by default (fast). Pass build_missing=True
    to lazily build uncached repos (slow first run, then cached forever)."""
    fpsets: dict[str, set[str]] = {}
    for f in sorted(CACHE.glob("fpset_*.pkl")):
        name = f.stem.replace("fpset_", "")
        fpsets[name] = pickle.loads(f.read_bytes())
    if not build_missing:
        return fpsets
    repos = Path("repos")
    if repos.is_dir():
        for d in sorted(repos.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if d.name in fpsets:
                continue
            try:
                fpsets[d.name] = fingerprint_set(str(d))
            except Exception:
                pass
    return fpsets


def search(target: str, corpus: dict[str, set[str]] | None = None,
           top_k: int = 20) -> list[dict]:
    """1-vs-N bidirectional containment search (token + AST).

    Returns [{repo, token_min, ast_min, combined, a_in_b, b_in_a, is_framework}]
    sorted by combined descending. AST similarity catches structural reuse even
    when identifiers/directories/formatting differ (restructured forks).
    """
    t_fps = fingerprint_set(f"repos/{target}" if "/" not in target else target)
    t_ast = ast_fingerprint_set(f"repos/{target}" if "/" not in target else target)
    if corpus is None:
        corpus = corpus_fingerprints()
    results = []
    for name in corpus:
        if name == target or not corpus[name]:
            continue
        # token containment
        c_fps = corpus[name]
        inter_tok = len(t_fps & c_fps)
        tok_min = min(inter_tok / len(t_fps), inter_tok / len(c_fps)) if t_fps and c_fps else 0.0

        # AST containment (build on demand, cached)
        try:
            c_ast = ast_fingerprint_set(f"repos/{name}")
        except Exception:
            c_ast = set()
        inter_ast = len(t_ast & c_ast)
        ast_min = min(inter_ast / len(t_ast), inter_ast / len(c_ast)) if t_ast and c_ast else 0.0

        # combined: max of both dimensions — either signal is sufficient evidence
        combined = max(tok_min, ast_min)

        year = _extract_year(name)
        results.append({
            "repo": name,
            "token_min": round(tok_min, 3),
            "ast_min": round(ast_min, 3),
            "combined": round(combined, 3),
            "is_framework": name in FRAMEWORKS,
            "year": year,
        })
    results.sort(key=lambda r: -r["combined"])
    return results[:top_k]


def _extract_year(name: str) -> int:
    """Extract contest year from repo name. T20241xxx → 2024, oskernel2023-xxx → 2023."""
    import re
    m = re.search(r"T20(2[0-9])", name) or re.search(r"20(19|2[0-5])", name)
    return int(m.group(0)[1:]) if m and m.group(0).startswith("T") else (int(m.group(0)) if m else 0)


if __name__ == "__main__":
    target = sys.argv[1]
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    candidates = search(target, top_k=top)
    print(f"{target}  vs  corpus ({len(corpus_fingerprints())} members):\n")
    for r in candidates:
        tag = " [base]" if r["is_framework"] else ""
        print(f"  comb={r['combined']:.3f}  tok={r['token_min']:.3f}  ast={r['ast_min']:.3f}  {r['repo'][:36]}{tag}")
