#!/usr/bin/env python3
"""Hardened lineage analysis — IDF-weighted k-gram containment.

Upgrades over lineage_matrix.py:
  * IDF weighting: a gram shared by many repos (libc/boilerplate) is muted;
    a gram in only 2-3 repos dominates. Kills both noise sources we observed
    (strlen-type collisions AND the big-repo pseudo-hub like T...106).
  * weighted containment normalized by the SMALLER repo's own weight mass.
  * year extraction -> directed edges (who copied whom).
  * union-find clustering on strong mutual links.

Reuses .fp_cache/ (set[int] of gram hashes per repo). No atlas rebuild, no LLM.
"""
from __future__ import annotations

import json
import math
import pickle
import re
from collections import defaultdict
from pathlib import Path

CACHE = Path(".fp_cache")
# teaching prototypes / well-known upstreams: treated as ancestors (year 0)
PROTOTYPES = {"xv6-riscv", "xv6-public", "xv6-k210", "rCore-Tutorial-v3", "ucore_os_lab",
              "ucore-smp", "arceos", "zCore", "Starry", "starry-mix"}


def repo_year(name: str) -> int:
    """Extract contest year for direction. Prototypes -> 0 (oldest)."""
    if name in PROTOTYPES:
        return 0
    m = re.search(r"T20(2[0-9])", name) or re.search(r"20(19|2[0-5])", name)
    if m:
        g = m.group(0)
        return int(g[1:]) if g.startswith("T") else int(g)
    return 9999  # unknown -> treat as newest (conservative)


def load_sets() -> dict[str, set[int]]:
    sets = {}
    for f in sorted(CACHE.glob("*.pkl")):
        g = pickle.loads(f.read_bytes())
        if len(g) >= 200:
            sets[f.stem] = g
    return sets


def main():
    sets = load_sets()
    N = len(sets)
    print(f"loaded {N} repos from cache\n")

    # ---- document frequency per gram -> IDF weight ----
    df: dict[int, int] = defaultdict(int)
    for g in sets.values():
        for gram in g:
            df[gram] += 1
    # IDF: grams in >50% of repos are boilerplate -> near-zero weight
    idf = {gram: math.log(N / d) for gram, d in df.items()}

    # precompute each repo's total IDF mass
    mass = {a: sum(idf[x] for x in g) for a, g in sets.items()}

    names = list(sets)
    # ---- IDF-weighted asymmetric containment ----
    # C(a,b) = weighted |a∩b| / weighted |a|  (fraction of a's *distinctive* code in b)
    cont: dict[str, dict[str, float]] = {a: {} for a in names}
    for i, a in enumerate(names):
        ga = sets[a]
        ma = mass[a] or 1.0
        for b in names:
            if a == b:
                continue
            gb = sets[b]
            inter = ga & gb if len(ga) <= len(gb) else gb & ga
            w = sum(idf[x] for x in inter)
            cont[a][b] = w / ma

    # ---- per-repo nearest source (IDF-weighted) ----
    print("=" * 90)
    print("NEAREST SOURCE (IDF-weighted: fraction of MY *distinctive* code found in OTHER)")
    print("=" * 90)
    rows = []
    for a in names:
        top = sorted(cont[a].items(), key=lambda kv: -kv[1])[:3]
        rows.append((top[0][1], a, top))
    for best, a, top in sorted(rows, key=lambda x: -x[0]):
        tops = "  ".join(f"{b}:{c:.2f}" for b, c in top)
        print(f"  {a[:32]:32s}({repo_year(a)}) -> {tops}")

    # ---- directed edges: strong link + year decides direction ----
    print("\n" + "=" * 90)
    print("DIRECTED LINEAGE  (min weighted containment >= 0.30; arrow = older <- newer)")
    print("=" * 90)
    seen = set()
    edges = []
    for a in names:
        for b in cont[a]:
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            m = min(cont[a][b], cont[b].get(a, 0.0))
            if m >= 0.30:
                ya, yb = repo_year(a), repo_year(b)
                if ya < yb:
                    older, newer = a, b
                elif yb < ya:
                    older, newer = b, a
                else:
                    older, newer = None, None  # same year -> undirected
                edges.append((m, older, newer, a, b))
    for m, older, newer, a, b in sorted(edges, reverse=True, key=lambda x: x[0]):
        if older:
            print(f"  {m:.2f}  {newer[:34]:34s} derives from <- {older}")
        else:
            print(f"  {m:.2f}  {a[:34]:34s} <=> {b}  (same year, undirected)")

    # ---- union-find clustering ----
    parent = {a: a for a in names}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for m, older, newer, a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    clusters = defaultdict(list)
    for a in names:
        clusters[find(a)].append(a)
    multi = sorted((c for c in clusters.values() if len(c) > 1), key=len, reverse=True)

    # ---- persist clusters + per-repo peers so stages 2/4 consume them automatically
    # (closes the seam where peers were hand-typed on the CLI). For each repo, its
    # "peers" = other cluster members; "older_peers" = members with a smaller year.
    cluster_export = {
        "families": [sorted(c, key=repo_year) for c in multi],
        "peers": {a: sorted((m for m in clusters[find(a)] if m != a), key=repo_year)
                  for a in names},
        "older_peers": {a: sorted((m for m in clusters[find(a)]
                                   if m != a and repo_year(m) < repo_year(a)), key=repo_year)
                        for a in names},
        "year": {a: repo_year(a) for a in names},
        # directed edges (older <- newer) and same-year edges (review targets for
        # same-cohort plagiarism). m = min bidirectional containment.
        "edges": [{"score": round(m, 3), "older": older, "newer": newer,
                   "a": a, "b": b, "same_year": older is None}
                  for m, older, newer, a, b in sorted(edges, reverse=True, key=lambda x: x[0])],
        # orphans: singleton cluster + low best-containment = originality candidates
        "orphans": [{"repo": a, "best": round(best, 3), "year": repo_year(a)}
                    for best, a, top in sorted(rows)
                    if len(clusters[find(a)]) == 1][:25],
    }
    Path("output").mkdir(exist_ok=True)
    Path("output/lineage_clusters.json").write_text(
        json.dumps(cluster_export, ensure_ascii=False, indent=2))
    print("\nwrote output/lineage_clusters.json")

    print("\n" + "=" * 90)
    print(f"LINEAGE CLUSTERS  ({len(multi)} multi-member families, "
          f"{sum(1 for c in clusters.values() if len(c)==1)} singletons)")
    print("=" * 90)
    for c in multi:
        c_sorted = sorted(c, key=repo_year)
        print(f"  [{len(c)}] " + " | ".join(f"{n}({repo_year(n)})" for n in c_sorted))

    # ---- orphans: low best-containment AND singleton ----
    print("\n" + "=" * 90)
    print("ORPHANS (singleton cluster + low best-containment = originality candidates)")
    print("=" * 90)
    for best, a, top in sorted(rows)[:20]:
        if len(clusters[find(a)]) == 1:
            print(f"  {a[:42]:42s}({repo_year(a)})  best={best:.2f}")


if __name__ == "__main__":
    main()
