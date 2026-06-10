#!/usr/bin/env python3
"""Stage-2 four-way provenance — zero LLM, first end-to-end run.

Classifies every function in a target repo into:
  EXTERNAL          fingerprint in framework baseline's *own* vendored deps,
                    OR physically under vendor/ (cargo-vendored crates.io deps)
  PORTED-FRAMEWORK  fingerprint matches the framework baseline (oscomp/arceos)
  PORTED-PEER       fingerprint matches an earlier/peer corpus member
  ORIGINAL          no match anywhere -> student's own work

Deterministic layer only. The LLM layer (stage 3) later reads Cargo.toml to
confirm what's declared external and to cross-check these fingerprint verdicts.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Stage-1 fingerprint building lives in fingerprint.py now (build vs compare split,
# DESIGN §7 阶段1). Stage-B exclusion rules come from exclude.py.
from scripts.fingerprint import build_units, fingerprint_set, lang_summary
from scripts.exclude import load_rules as load_exclude_rules, apply_exclude


def fingerprints(repo_path: str, want_meta=False):
    """Return the fingerprint set, or the unit list if want_meta.

    Delegates to fingerprint.py (build vs compare split). Now includes asm units,
    which v1 dropped. The set form is cached there for 1-vs-N peer reuse.
    """
    if not want_meta:
        return fingerprint_set(repo_path)
    return build_units(repo_path)


def functions_and_edges(repo_path: str):
    """(unit_list, internal_edges) for the architecture graph.

    Returns all units from fingerprint.py (code + asm) plus call edges from the
    atlas. Code units already carry fn_id from fingerprint.build_units();
    asm units have no fn_id (no call graph).
    """
    from core.code_atlas.builder import build_code_atlas

    units = build_units(repo_path)
    name = Path(repo_path).name
    atlas = build_code_atlas(repo_path=repo_path, repo_name=name)
    fn_ids = {u["fn_id"] for u in units if u.get("fn_id")}
    edges = [(e["src_fn_id"], e["dst_fn_id"]) for e in atlas.get("edges", [])
             if e.get("dst_fn_id") and e.get("src_fn_id") in fn_ids and e.get("dst_fn_id") in fn_ids]
    return units, edges


def top_dir(path: str) -> str:
    parts = [p for p in path.split("/") if p not in ("", ".")]
    return parts[0] if parts else "(root)"


# token floor for PEER attribution ONLY: below this, a function (Rust new()/get()/
# drop() etc.) is boilerplate whose normalized fingerprint matches by language
# convention, not by copying — so a sub-floor match to a peer must NOT be reported
# as plagiarism. It goes to TRIVIAL. But a sub-floor function with NO match anywhere
# is still the student's own code -> ORIGINAL (the floor is an anti-false-positive
# guard for PEER, not a discount on authorship). See DESIGN.md §5.7.
PEER_TOKEN_FLOOR = 100


def classify_provenance(tfns: list, fw: set, peer_fps: set, floor: int = PEER_TOKEN_FLOOR,
                        exclude_rules: list[dict] | None = None) -> dict:
    """Four-way + TRIVIAL classification. Shared by stage-2 CLI and stage-4 report.

    tfns: list of {name,file,line,fp,sz}; fw/peer_fps: fingerprint sets.
    exclude_rules: from exclude.load_rules(), for stage-B EXTERNAL tagging.
    Returns {class_name: [fn,...]}.
    """
    classes = {"EXTERNAL": [], "PORTED-FRAMEWORK": [], "PORTED-PEER": [], "ORIGINAL": [], "TRIVIAL": []}
    for f in tfns:
        if exclude_rules is not None:
            is_excluded, _ = apply_exclude(exclude_rules, f["file"])
        else:
            # no exclude rules = LLM hasn't run yet; only vendor/ is certain (tool convention)
            is_excluded = f["file"].startswith("vendor/")
        if is_excluded:
            cls = "EXTERNAL"
        elif f["fp"] in fw:
            cls = "PORTED-FRAMEWORK"
        elif f["fp"] in peer_fps:
            # peer match: only count as plagiarism if above the floor; a tiny
            # boilerplate collision is not evidence -> TRIVIAL
            cls = "PORTED-PEER" if f["sz"] >= floor else "TRIVIAL"
        else:
            # no match anywhere = student's own work, regardless of size
            cls = "ORIGINAL"
        classes[cls].append(f)
    return classes


def main():
    target = sys.argv[1]
    framework = sys.argv[2]  # e.g. repos/_baseline_oscomp-arceos
    peers = sys.argv[3:]     # earlier/same-cluster corpus members

    print(f"TARGET:    {target}")
    print(f"FRAMEWORK: {framework}")
    print(f"PEERS:     {len(peers)} repos\n")

    tfns = fingerprints(f"repos/{target}", want_meta=True)
    fw = fingerprints(framework)
    print(f"  framework baseline: {len(fw)} fps")
    peer_fps = set()
    for p in peers:
        peer_fps |= fingerprints(f"repos/{p}")
    print(f"  peer corpus: {len(peer_fps)} fps\n")

    # stage-B exclude rules (Agent understanding -> deterministic exclusion)
    rules = load_exclude_rules(target)

    # token floor: see classify_provenance / DESIGN.md §5.7
    classes = classify_provenance(tfns, fw, peer_fps, exclude_rules=rules)

    total = len(tfns)
    tot_sz = sum(f["sz"] for f in tfns) or 1
    print("=" * 70)
    print(f"PROVENANCE (function count / token-weighted)  [PEER floor={PEER_TOKEN_FLOOR}tok]")
    print("=" * 70)
    for c in ("EXTERNAL", "PORTED-FRAMEWORK", "PORTED-PEER", "ORIGINAL", "TRIVIAL"):
        n = len(classes[c])
        sz = sum(f["sz"] for f in classes[c])
        print(f"  {c:18s}: {n:5d} fns ({100*n/total:3.0f}%)   {sz:7d} tok ({100*sz/tot_sz:3.0f}%)")

    print("\n" + "=" * 70)
    print("PER-DIR provenance mix (token-weighted, excludes vendor/)")
    print("=" * 70)
    dirstat = defaultdict(lambda: defaultdict(int))
    for c, fns in classes.items():
        for f in fns:
            dirstat[top_dir(f["file"])][c] += f["sz"]
    for d, st in sorted(dirstat.items(), key=lambda kv: -sum(kv[1].values())):
        if d == "vendor":
            continue
        tot = sum(st.values()) or 1
        print(f"  {d[:16]:16s} {tot:7d}tok  "
              f"FW={100*st['PORTED-FRAMEWORK']/tot:3.0f}% "
              f"PEER={100*st['PORTED-PEER']/tot:3.0f}% "
              f"ORIG={100*st['ORIGINAL']/tot:3.0f}% "
              f"TRIV={100*st['TRIVIAL']/tot:3.0f}%")

    print("\n" + "=" * 70)
    print("ORIGINAL samples (student's own work — what stage-3 LLM reads)")
    print("=" * 70)
    for f in sorted(classes["ORIGINAL"], key=lambda x: -x["sz"])[:15]:
        print(f"  {f['name'][:32]:32s} ({f['file']}, {f['sz']}tok)")


if __name__ == "__main__":
    main()
