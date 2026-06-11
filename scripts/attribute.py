#!/usr/bin/env python3
"""Function-level comparison — COPIED / DISGUISE / MODIFIED / NOVEL.

Takes a target repo and a base, classifies every non-excluded function:
  COPIED    exact fp in base, same name    — carried over unchanged
  DISGUISE  exact fp in base, name differs — renamed copy
  MODIFIED  same name, fp differs          — changed
  NOVEL     neither name nor fp in base    — new code

The caller (Agent) provides exclude_prefixes based on its own understanding
of which directories are external dependencies. No exclude rules engine needed.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fingerprint import build_units, fingerprint_set


def _is_excluded(file_path: str, prefixes: list[str]) -> bool:
    for p in prefixes:
        if file_path == p or file_path.startswith(p + "/") or file_path.startswith(p):
            return True
    return False


def compare_units(target: str, base: str,
                  exclude_prefixes: list[str] | None = None) -> dict:
    """Classify target units against base.

    Returns {summary: {copied, disguise, modified, novel}, by_file: {...}}.
    """
    prefixes = exclude_prefixes or []

    t_units = build_units(f"repos/{target}" if "/" not in target else target)
    b_units = build_units(f"repos/{base}" if "/" not in base else base) if base else []
    b_fps = fingerprint_set(f"repos/{base}" if "/" not in base else base) if base else set()

    # index base functions
    base_by_name: dict[str, list[dict]] = defaultdict(list)
    for u in b_units:
        base_by_name[u["name"].lower()].append(u)

    # classify
    classified: dict[str, list[dict]] = {"copied": [], "disguise": [], "modified": [], "novel": []}

    for u in t_units:
        if _is_excluded(u["file"], prefixes):
            continue

        name = u["name"].lower()
        fp = u["fp"]

        if fp and fp in b_fps:
            if name in base_by_name and any(b["fp"] == fp for b in base_by_name[name]):
                classified["copied"].append(u)
            else:
                classified["disguise"].append(u)
        elif name in base_by_name:
            classified["modified"].append(u)
        else:
            classified["novel"].append(u)

    # summary
    summary = {k: len(v) for k, v in classified.items()}

    # group by file
    by_file: dict[str, dict] = defaultdict(lambda: {"functions": []})
    for status, fns in classified.items():
        for f in fns:
            by_file[f["file"]]["functions"].append({
                "name": f["name"],
                "status": status,
                "tokens": f["sz"],
                "line": f.get("line", 0),
                "lang": f.get("lang", ""),
            })

    # sort functions within each file by status priority: modified > novel > disguise > copied
    _order = {"modified": 0, "novel": 1, "disguise": 2, "copied": 3}
    for fi in by_file.values():
        fi["functions"].sort(key=lambda x: _order.get(x["status"], 9))

    return {
        "target": target,
        "base": base,
        "summary": summary,
        "by_file": dict(by_file),
    }


if __name__ == "__main__":
    target = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else ""
    prefixes = sys.argv[3:] if len(sys.argv) > 3 else None

    # auto-resolve base from search if not given
    if not base:
        from scripts.search import search, corpus_fingerprints
        corpus = corpus_fingerprints(build_missing=False)
        candidates = search(target, corpus=corpus, top_k=3)
        peers = [c for c in candidates if not c.get("is_framework")]
        base = peers[0]["repo"] if peers else ""
        print(f"[auto] base = {base} (from {len(corpus)} cached members)")

    print(f"TARGET: {target}  BASE: {base}  exclude: {prefixes or 'none'}\n")
    result = compare_units(target, base, exclude_prefixes=prefixes)

    total = sum(result["summary"].values()) or 1
    s = result["summary"]
    print(f"  COPIED:   {s['copied']:5d}  ({100*s['copied']/total:.0f}%)")
    print(f"  DISGUISE: {s['disguise']:5d}  ({100*s['disguise']/total:.0f}%)")
    print(f"  MODIFIED: {s['modified']:5d}  ({100*s['modified']/total:.0f}%)")
    print(f"  NOVEL:    {s['novel']:5d}  ({100*s['novel']/total:.0f}%)")
    print(f"  real work (M+N): {s['modified']+s['novel']} "
          f"({100*(s['modified']+s['novel'])/total:.0f}%)")

    # top files by modified count
    print(f"\n  files: {len(result['by_file'])}")
    top_files = sorted(result["by_file"].items(),
                       key=lambda kv: sum(1 for f in kv[1]["functions"] if f["status"] in ("modified", "novel")),
                       reverse=True)[:12]
    for path, fi in top_files:
        ms = sum(1 for f in fi["functions"] if f["status"] == "modified")
        ns = sum(1 for f in fi["functions"] if f["status"] == "novel")
        if ms + ns == 0:
            continue
        print(f"  {path:50s}  M={ms:3d}  N={ns:3d}")
