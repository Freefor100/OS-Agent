#!/usr/bin/env python3
"""Stage-4 function-level deep comparison — COPIED / DISGUISE / MODIFIED / NOVEL.

Takes a target repo and a base (from search.py or explicit), classifies every
non-excluded target function against the base:

  COPIED    exact fp in base, same name    — carried over unchanged
  DISGUISE  exact fp in base, name differs — renamed copy (plagiarism signal)
  MODIFIED  same name, fp differs          — changed (most interesting to read)
  NOVEL     neither name nor fp in base    — new code

Uses fingerprint.build_units (code + asm) and exclude.load_rules (EXTERNAL skip).
Outputs a JSON work-list (MODIFIED + NOVEL by module) for the LLM / report stage.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fingerprint import build_units, fingerprint_set
from scripts.exclude import load_rules

PEER_TOKEN_FLOOR = 100


def deep_compare(target: str, base: str) -> dict:
    """Classify every target unit against base. Returns {COPIED/DISGUISE/MODIFIED/NOVEL: [unit]}."""
    units = build_units(f"repos/{target}")
    rules = load_rules(target)
    if base:
        base_fps = fingerprint_set(f"repos/{base}")
    else:
        base_fps = set()

    # index base functions by name for MODIFIED detection
    base_units = build_units(f"repos/{base}") if base else []
    base_names: dict[str, list[dict]] = defaultdict(list)
    base_hash_to_names: dict[str, set[str]] = defaultdict(set)
    for u in base_units:
        base_names[u["name"].lower()].append(u)
        base_hash_to_names[u["fp"]].add(u["name"])

    classes = {"COPIED": [], "DISGUISE": [], "MODIFIED": [], "NOVEL": []}

    for u in units:
        # skip excluded units (EXTERNAL — not the student's code anyway)
        from scripts.exclude import apply_exclude
        excluded, _ = apply_exclude(rules, u["file"])
        if excluded:
            continue

        name = u["name"].lower()
        fp = u["fp"]
        if fp and fp in base_fps:
            if name in base_names and any(b["fp"] == fp for b in base_names[name]):
                classes["COPIED"].append(u)
            else:
                classes["DISGUISE"].append(u)
        elif name in base_names:
            classes["MODIFIED"].append(u)
        else:
            classes["NOVEL"].append(u)

    return classes


def module_of(path: str) -> str:
    parts = [p for p in path.split("/") if p not in ("", ".", "src", "kernel", "os")]
    return parts[0] if parts else "(root)"


def main():
    target = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else ""

    # auto-resolve base from search if not given (cached-only — fast)
    if not base:
        from scripts.search import search, corpus_fingerprints
        corpus = corpus_fingerprints(build_missing=False)  # only cached, fast
        candidates = search(target, corpus=corpus, top_k=3)
        peers = [c for c in candidates if not c.get("is_framework")]
        base = peers[0]["repo"] if peers else ""
        print(f"[auto] base = {base} (from {len(corpus)} cached members)")

    print(f"TARGET: {target}  BASE: {base}\n")
    classes = deep_compare(target, base)

    total = sum(len(v) for v in classes.values()) or 1
    print("=" * 72)
    print("DEEP COMPARISON")
    print("=" * 72)
    for c in ("COPIED", "DISGUISE", "MODIFIED", "NOVEL"):
        n = len(classes[c])
        print(f"  {c:9s}: {n:5d}  ({100*n/total:.0f}%)")

    inherited = len(classes["COPIED"]) + len(classes["DISGUISE"])
    realwork = len(classes["MODIFIED"]) + len(classes["NOVEL"])
    print(f"  {'-'*40}")
    print(f"  inherited: {100*inherited/total:.0f}%   real work: {100*realwork/total:.0f}%")

    # per-module breakdown
    print("\n" + "=" * 72)
    print("PER-MODULE")
    print("=" * 72)
    modst = defaultdict(lambda: defaultdict(int))
    for cls, fns in classes.items():
        for f in fns:
            modst[module_of(f["file"])][cls] += max(1, f["sz"])
    for mod, st in sorted(modst.items(), key=lambda kv: -sum(kv[1].values())):
        inh = st["COPIED"] + st["DISGUISE"]
        rw = st["MODIFIED"] + st["NOVEL"]
        tot = inh + rw
        if tot < 50:
            continue
        print(f"  {mod[:28]:28s} {tot:6d}tok  inh={100*inh/tot:3.0f}%  rw={100*rw/tot:3.0f}%  "
              f"(N={st['NOVEL']} M={st['MODIFIED']} C={st['COPIED']} D={st['DISGUISE']})")

    # work-list for LLM
    worklist = {
        "target": target, "base": base,
        "modified": [{"name": f["name"], "file": f["file"], "line": f.get("line", 0), "lang": f.get("lang", "")}
                     for f in classes["MODIFIED"]],
        "novel": [{"name": f["name"], "file": f["file"], "line": f.get("line", 0), "lang": f.get("lang", "")}
                  for f in classes["NOVEL"]],
    }
    out = Path(f"/tmp/worklist_{target}.json")
    out.write_text(json.dumps(worklist, ensure_ascii=False, indent=2))
    print(f"\nwork-list ({len(worklist['modified'])}M + {len(worklist['novel'])}N) -> {out}")


if __name__ == "__main__":
    main()
