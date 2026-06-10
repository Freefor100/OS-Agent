#!/usr/bin/env python3
"""All-pairs lineage matrix over repos/ — zero LLM.

For every repo we pool all normalized C/Rust function tokens into a set of
5-gram hashes (robust to function extract/inline, unlike per-function align).
Then asymmetric containment  C(A,B) = |A∩B| / |A|  answers:
  "how much of A's code also exists in B" -> A borrowed from / shares ancestor B.

Outputs per-repo nearest sources (relative ranking, NOT absolute threshold),
same-source clusters, and orphans (originality candidates).

Gram sets are cached to .fp_cache/ so reruns are instant.
"""
from __future__ import annotations

import hashlib
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.code_atlas.builder import build_code_atlas

K = 5
CACHE = Path(".fp_cache")
CACHE.mkdir(exist_ok=True)
LANGS = {"c", "cpp", "rust"}


def _h(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def gram_set(repo_dir: Path) -> set[int]:
    """Pooled 5-gram hash set over all normalized C/Rust tokens. Cached."""
    cf = CACHE / f"{repo_dir.name}.pkl"
    if cf.exists():
        return pickle.loads(cf.read_bytes())
    atlas = build_code_atlas(repo_path=str(repo_dir), repo_name=repo_dir.name)
    grams: set[int] = set()
    for fn in atlas.get("functions", {}).values():
        if fn.get("lang") not in LANGS:
            continue
        t = fn.get("tokens_normalized") or []
        for i in range(len(t) - K + 1):
            grams.add(_h(" ".join(t[i : i + K])))
    cf.write_bytes(pickle.dumps(grams))
    return grams


def main():
    repos = sorted(p for p in Path("repos").iterdir() if p.is_dir() and not p.name.startswith("."))
    print(f"{len(repos)} repos. building/loading gram sets...")
    sets: dict[str, set[int]] = {}
    t0 = time.time()
    for i, r in enumerate(repos, 1):
        try:
            g = gram_set(r)
        except Exception as e:
            print(f"  [skip] {r.name}: {type(e).__name__}: {str(e)[:80]}")
            continue
        if len(g) >= 200:  # ignore near-empty repos (no parseable code)
            sets[r.name] = g
        if i % 20 == 0:
            print(f"  {i}/{len(repos)}  ({time.time()-t0:.0f}s)")
    print(f"usable repos: {len(sets)}  (built in {time.time()-t0:.0f}s)\n")

    names = list(sets)
    # asymmetric containment matrix
    cont: dict[str, dict[str, float]] = {a: {} for a in names}
    for a in names:
        ga = sets[a]
        la = len(ga)
        for b in names:
            if a == b:
                continue
            inter = len(ga & sets[b])
            cont[a][b] = inter / la

    # per-repo nearest sources: who contains the most of me
    print("=" * 78)
    print("PER-REPO NEAREST SOURCE  (C(me,other) = fraction of MY code found in OTHER)")
    print("=" * 78)
    rows = []
    for a in names:
        top = sorted(cont[a].items(), key=lambda kv: -kv[1])[:3]
        rows.append((top[0][1], a, top))
    rows.sort(key=lambda x: -x[0])
    for best, a, top in rows:
        tops = "  ".join(f"{b}:{c:.2f}" for b, c in top)
        print(f"  {a[:34]:34s} -> {tops}")

    # orphans: nothing contains much of them -> originality candidates
    print("\n" + "=" * 78)
    print("ORPHANS (lowest best-containment = least derivative / originality candidates)")
    print("=" * 78)
    for best, a, top in sorted(rows)[:20]:
        print(f"  {a[:40]:40s}  best={best:.2f}  ({top[0][0]})")

    # clusters: mutual high containment (symmetric strong link)
    print("\n" + "=" * 78)
    print("STRONG MUTUAL LINKS  (min(C(a,b),C(b,a)) >= 0.40 — likely same lineage)")
    print("=" * 78)
    seen = set()
    links = []
    for a in names:
        for b in cont[a]:
            if (b, a) in seen:
                continue
            seen.add((a, b))
            m = min(cont[a][b], cont[b].get(a, 0.0))
            if m >= 0.40:
                links.append((m, a, b))
    for m, a, b in sorted(links, reverse=True)[:40]:
        print(f"  {m:.2f}  {a[:30]:30s} <=> {b[:30]}")
    print(f"\n  total strong mutual links: {len(links)}")


if __name__ == "__main__":
    main()
