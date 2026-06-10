#!/usr/bin/env python3
"""Zero-LLM fingerprint validation: is the function-level fingerprint load-bearing?

xv6-k210 is a known contest port of xv6-riscv. We test three things:
  1. alignment  -- can same-source functions be aligned and split into
                   verbatim / drifted / missing?
  2. disguise   -- are renamed-but-identical functions caught (name differs,
                   normalized fingerprint equal)?
  3. noise      -- do unrelated C kernels collide a lot (false positives)?
"""
from __future__ import annotations

import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.code_atlas.builder import build_code_atlas
from tools.code_atlas.minhash import signature_from_tokens, jaccard_estimate

# reuse the exact production fingerprint so we test what Agent D actually emits
from agent_d import _fn_structure_fingerprint


def fingerprint_functions(repo_path: str, repo_name: str) -> dict:
    """repo -> {fn_key: {name, path, ntok, ast, lit, sig}} for C/H functions only.

    `sig` is a MinHash signature over the normalized tokens, giving a graded
    jaccard similarity (vs the exact-equal-only `ntok` hash).
    """
    atlas = build_code_atlas(repo_path=repo_path, repo_name=repo_name)
    out = {}
    for fn_id, fn in atlas.get("functions", {}).items():
        if fn.get("lang") not in {"c", "cpp"}:
            continue
        fp = _fn_structure_fingerprint(fn)
        toks = fn.get("tokens_normalized") or []
        out[fn_id] = {
            "name": fn.get("name", ""),
            "path": str(fn.get("file", "")).replace("\\", "/"),
            "ntok": fp["normalized_token_fingerprint"],
            "ast": fp.get("ast_shape_hash"),
            "lit": fp.get("literal_fingerprint"),
            "ntoks": len(toks),
            "sig": signature_from_tokens(toks) if toks else None,
        }
    return out


def drift_gradient(base: dict, fork: dict):
    """For name-aligned, ntok-differing pairs: measure MinHash jaccard.

    Answers 'can we quantify how much a changed function changed?'
    """
    base_by_name = defaultdict(list)
    for f in base.values():
        base_by_name[f["name"]].append(f)

    buckets = {"~unchanged .95+": 0, "light .7-.95": 0, "moderate .4-.7": 0, "heavy .1-.4": 0, "rewrite <.1": 0}
    samples = []
    for f in fork.values():
        cands = base_by_name.get(f["name"])
        if not cands or f["sig"] is None:
            continue
        if any(c["ntok"] == f["ntok"] for c in cands):
            continue  # verbatim, not drift
        # best jaccard against any same-name base candidate
        best = max((jaccard_estimate(f["sig"], c["sig"]) for c in cands if c["sig"]), default=0.0)
        if best >= 0.95:
            buckets["~unchanged .95+"] += 1
        elif best >= 0.7:
            buckets["light .7-.95"] += 1
        elif best >= 0.4:
            buckets["moderate .4-.7"] += 1
        elif best >= 0.1:
            buckets["heavy .1-.4"] += 1
        else:
            buckets["rewrite <.1"] += 1
        samples.append((best, f["name"], basename(f["path"]), f["ntoks"]))

    print("\n=== DRIFT GRADIENT (name-aligned, ntok differs) — MinHash jaccard ===")
    for k, v in buckets.items():
        print(f"  {k:18s}: {v}")
    samples.sort()
    print("  most-changed (lowest jaccard):")
    for j, n, p, sz in samples[:8]:
        print(f"     j={j:.2f}  {n} ({p}, {sz} toks)")
    print("  least-changed (highest jaccard, still flagged drift):")
    for j, n, p, sz in samples[-8:]:
        print(f"     j={j:.2f}  {n} ({p}, {sz} toks)")


def by_name(funcs: dict) -> dict:
    d = defaultdict(list)
    for f in funcs.values():
        d[f["name"]].append(f)
    return d


def basename(p: str) -> str:
    return p.rsplit("/", 1)[-1]


def compare_aligned(base: dict, fork: dict, label: str):
    """Align fork->base by function name; classify each fork fn."""
    base_by_name = by_name(base)
    base_ntoks = {f["ntok"] for f in base.values()}

    verbatim = drift = newfn = 0
    moved = 0  # same name+ntok but different file (relocated, still verbatim)
    examples_drift, examples_new = [], []

    for f in fork.values():
        cands = base_by_name.get(f["name"])
        if cands:  # identity alignment succeeded (same name exists in base)
            if any(c["ntok"] == f["ntok"] for c in cands):
                verbatim += 1
                if not any(basename(c["path"]) == basename(f["path"]) for c in cands):
                    moved += 1
            else:
                drift += 1
                if len(examples_drift) < 8:
                    examples_drift.append(f"{f['name']} ({basename(f['path'])})")
        else:
            newfn += 1
            if len(examples_new) < 8:
                examples_new.append(f"{f['name']} ({basename(f['path'])})")

    total = len(fork)
    print(f"\n=== {label} ===")
    print(f"fork functions (C): {total}  | base functions (C): {len(base)}")
    print(f"  verbatim (name aligned, ntok identical) : {verbatim:4d}  ({100*verbatim/total:.0f}%)  [of which relocated file: {moved}]")
    print(f"  drift    (name aligned, ntok changed)   : {drift:4d}  ({100*drift/total:.0f}%)  <-- real work")
    print(f"  new      (name not in base)             : {newfn:4d}  ({100*newfn/total:.0f}%)  <-- real work / unmatched")
    if examples_drift:
        print(f"  drift examples: {', '.join(examples_drift)}")
    if examples_new:
        print(f"  new examples:   {', '.join(examples_new)}")

    # disguise: fork fn whose NAME is not in base, but whose ntok IS in base
    disguised = []
    base_name_to_ntoks = defaultdict(set)
    for f in base.values():
        base_name_to_ntoks[f["name"]].add(f["ntok"])
    for f in fork.values():
        if f["name"] not in base_by_name and f["ntok"] in base_ntoks:
            # find which base name(s) carry this ntok
            origin = [n for n, s in base_name_to_ntoks.items() if f["ntok"] in s]
            disguised.append((f["name"], origin[:3]))
    print(f"  DISGUISE (renamed but ntok matches base): {len(disguised)}")
    for newname, origins in disguised[:10]:
        print(f"     {newname}  <==  {origins}")


def noise_collision(a: dict, b: dict, label: str):
    """Unrelated repos: how many ntok fingerprints collide by chance."""
    a_ntoks = {f["ntok"] for f in a.values()}
    b_ntoks = {f["ntok"] for f in b.values()}
    inter = a_ntoks & b_ntoks
    print(f"\n=== NOISE: {label} ===")
    print(f"  distinct ntok A: {len(a_ntoks)}  B: {len(b_ntoks)}  collisions: {len(inter)}")
    print(f"  collision rate vs smaller set: {100*len(inter)/max(1,min(len(a_ntoks),len(b_ntoks))):.1f}%")
    # show what collided (likely trivial getters/empty bodies)
    b_by_ntok = defaultdict(list)
    for f in b.values():
        b_by_ntok[f["ntok"]].append(f["name"])
    a_by_ntok = defaultdict(list)
    for f in a.values():
        a_by_ntok[f["ntok"]].append(f["name"])
    shown = 0
    for nt in inter:
        print(f"     {a_by_ntok[nt][:3]}  ==  {b_by_ntok[nt][:3]}")
        shown += 1
        if shown >= 10:
            break


if __name__ == "__main__":
    print("building atlases (no LLM)...")
    riscv = fingerprint_functions("repos/xv6-riscv", "xv6-riscv")
    print(f"  xv6-riscv: {len(riscv)} C functions")
    k210 = fingerprint_functions("repos/xv6-k210", "xv6-k210")
    print(f"  xv6-k210:  {len(k210)} C functions")
    unrel = fingerprint_functions("repos/exaros", "exaros")
    print(f"  exaros:    {len(unrel)} C functions")

    compare_aligned(riscv, k210, "xv6-riscv (base)  ->  xv6-k210 (fork)")
    drift_gradient(riscv, k210)
    noise_collision(riscv, unrel, "xv6-riscv  vs  exaros (unrelated C kernel)")
