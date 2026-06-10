#!/usr/bin/env python3
"""Stage-2 function-level attribution — zero LLM.

Given a NEWER repo (target) and an OLDER repo (base) in the same lineage,
classify every target function against the base:

  COPIED   exact normalized-token hash present in base, same name  -> carried over
  DISGUISE exact hash present in base, but renamed                 -> copy + rename
  MODIFIED same name exists in base, hash differs                  -> changed (flagged)
  NOVEL    neither name nor hash found in base                     -> new code

Aggregates per top-level module dir -> a contribution skeleton:
"how much of this submission is inherited vs the student's real work."

Emits NOVEL + MODIFIED function lists (the only inputs an LLM would need to read).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.code_atlas.builder import build_code_atlas
from agent_d import _fn_structure_fingerprint

LANGS = {"c", "cpp", "rust"}


def fingerprints(repo: str):
    atlas = build_code_atlas(repo_path=f"repos/{repo}", repo_name=repo)
    fns = []
    skipped = 0
    for fn in atlas.get("functions", {}).values():
        if fn.get("lang") not in LANGS:
            continue
        path = str(fn.get("file", "")).replace("\\", "/")
        if path.startswith("vendor/"):
            skipped += 1
            continue
        fp = _fn_structure_fingerprint(fn)
        fns.append({
            "name": fn.get("name", ""),
            "file": path,
            "line": fn.get("line", 0),
            "ntok": fp["normalized_token_fingerprint"],
            "ntoks": len(fn.get("tokens_normalized") or []),
        })
    if skipped:
        print(f"  [{repo}] excluded {skipped} vendored/third-party functions")
    return fns


def module_of(path: str) -> str:
    """Coarse module = first meaningful path segment."""
    parts = [p for p in path.split("/") if p not in ("", ".", "src", "kernel", "os")]
    return parts[0] if parts else "(root)"


def main():
    base_name, target_name = sys.argv[1], sys.argv[2]
    print(f"BASE (older):  {base_name}")
    print(f"TARGET (newer): {target_name}\n")

    base = fingerprints(base_name)
    target = fingerprints(target_name)
    print(f"base fns: {len(base)}  target fns: {len(target)}\n")

    base_hashes = {f["ntok"] for f in base}
    base_names = defaultdict(list)
    for f in base:
        base_names[f["name"]].append(f)
    hash_to_basename = defaultdict(set)
    for f in base:
        hash_to_basename[f["ntok"]].add(f["name"])

    classes = {"COPIED": [], "DISGUISE": [], "MODIFIED": [], "NOVEL": []}
    # weight by token count so big functions count more than trivial getters
    mod_stats = defaultdict(lambda: defaultdict(int))

    for f in target:
        same_name = base_names.get(f["name"])
        w = max(1, f["ntoks"])
        if f["ntok"] in base_hashes:
            if same_name and any(b["ntok"] == f["ntok"] for b in same_name):
                cls = "COPIED"
            else:
                cls = "DISGUISE"
        elif same_name:
            cls = "MODIFIED"
        else:
            cls = "NOVEL"
        classes[cls].append(f)
        mod_stats[module_of(f["file"])][cls] += w

    total = len(target)
    print("=" * 72)
    print("ATTRIBUTION SUMMARY (function counts)")
    print("=" * 72)
    for c in ("COPIED", "DISGUISE", "MODIFIED", "NOVEL"):
        n = len(classes[c])
        print(f"  {c:9s}: {n:5d}  ({100*n/total:.0f}%)")
    inherited = len(classes["COPIED"]) + len(classes["DISGUISE"])
    realwork = len(classes["MODIFIED"]) + len(classes["NOVEL"])
    print(f"  {'-'*40}")
    print(f"  inherited (copied+disguise): {100*inherited/total:.0f}%")
    print(f"  real work (modified+novel) : {100*realwork/total:.0f}%   <-- student contribution")

    print("\n" + "=" * 72)
    print("PER-MODULE (token-weighted: inherited% vs real-work%)")
    print("=" * 72)
    rows = []
    for mod, st in mod_stats.items():
        inh = st["COPIED"] + st["DISGUISE"]
        rw = st["MODIFIED"] + st["NOVEL"]
        tot = inh + rw
        rows.append((tot, mod, inh, rw, st))
    for tot, mod, inh, rw, st in sorted(rows, reverse=True)[:18]:
        print(f"  {mod[:28]:28s} {tot:6d}tok  inherited={100*inh/tot:3.0f}%  realwork={100*rw/tot:3.0f}%"
              f"  (N={st['NOVEL']} M={st['MODIFIED']} C={st['COPIED']} D={st['DISGUISE']})")

    print("\n" + "=" * 72)
    print("DISGUISE samples (copied + renamed — strongest plagiarism signal)")
    print("=" * 72)
    for f in sorted(classes["DISGUISE"], key=lambda x: -x["ntoks"])[:12]:
        origins = sorted(hash_to_basename[f["ntok"]])[:3]
        print(f"  {f['name'][:30]:30s} ({f['file'].split('/')[-1]}, {f['ntoks']}tok)  <== base: {origins}")

    print("\n" + "=" * 72)
    print("NOVEL samples (new code — what the LLM would read & describe)")
    print("=" * 72)
    for f in sorted(classes["NOVEL"], key=lambda x: -x["ntoks"])[:15]:
        print(f"  {f['name'][:34]:34s} ({f['file'].split('/')[-1]}, {f['ntoks']}tok)")

    # dump the LLM work-list (modified+novel) so stage-3 has a concrete input
    worklist = {
        "base": base_name, "target": target_name,
        "modified": [{"name": f["name"], "file": f["file"], "line": f["line"]} for f in classes["MODIFIED"]],
        "novel": [{"name": f["name"], "file": f["file"], "line": f["line"]} for f in classes["NOVEL"]],
    }
    out = Path(f"/tmp/worklist_{target_name}.json")
    out.write_text(json.dumps(worklist, ensure_ascii=False, indent=2))
    print(f"\nLLM work-list ({len(worklist['modified'])} modified + {len(worklist['novel'])} novel) -> {out}")


if __name__ == "__main__":
    main()
