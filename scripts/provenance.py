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

import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.code_atlas.builder import build_code_atlas
from agent_d import _fn_structure_fingerprint

FP = "normalized_token_fingerprint"

# vendored third-party code lives in many places, NOT just vendor/. Top-level
# dirs like bash-5.1.16/, dependency/, busybox/ are GNU/third-party sources that
# would otherwise dominate the metric (npucore: bash=345k tok, dependency=248k).
# This is path-based detection of *known third-party project layouts*, distinct
# from fingerprint-based provenance. See DESIGN.md §9.2. The stage-3 LLM later
# confirms these against declared deps (Cargo.toml/Makefile/.gitmodules).
VENDOR_RE = re.compile(
    r"(^|/)(bash-[\d.]+|busybox\w*|dependency|vendor|third[_-]?party|deps|extern(al)?|"
    r"lwext4\w*|fat32[\w-]*|libc-test|musl\w*|lua|sqlite|riscv-tests|\.cargo)(/|$)",
    re.IGNORECASE,
)


def is_vendor(path: str) -> bool:
    return bool(VENDOR_RE.search(path))


def fingerprints(repo_path: str, want_meta=False):
    """Return set of fingerprints, or list of {name,file,line,fp,sz} if want_meta.

    The set form is cached to .fp_cache/fpset_<name>.pkl so --all batch runs reuse
    peer fingerprints across targets instead of rebuilding each atlas. The meta
    form is not cached (per-target, includes fn_id/edges).
    """
    name = Path(repo_path).name
    if not want_meta:
        cf = Path(".fp_cache") / f"fpset_{name}.pkl"
        if cf.exists():
            return pickle.loads(cf.read_bytes())
        atlas = build_code_atlas(repo_path=repo_path, repo_name=name)
        s = set()
        for fn in atlas.get("functions", {}).values():
            if fn.get("lang") in ("c", "cpp", "rust"):
                s.add(_fn_structure_fingerprint(fn)[FP])
        cf.parent.mkdir(exist_ok=True)
        cf.write_bytes(pickle.dumps(s))
        return s
    atlas = build_code_atlas(repo_path=repo_path, repo_name=name)
    out = []
    for fn_id, fn in atlas.get("functions", {}).items():
        if fn.get("lang") not in ("c", "cpp", "rust"):
            continue
        out.append({
            "fn_id": fn_id,
            "name": fn.get("name", ""),
            "file": str(fn.get("file", "")).replace("\\", "/"),
            "line": fn.get("line", 0),
            "fp": _fn_structure_fingerprint(fn)[FP],
            "sz": len(fn.get("tokens_normalized") or []),
        })
    return out


def functions_and_edges(repo_path: str):
    """One atlas build -> (fn_meta_list, internal_edges).

    internal_edges = [(src_fn_id, dst_fn_id)] for resolved intra-repo calls only
    (dst_fn_id is None for external/unresolved). Used by stage-4 to build a
    module-level call graph. fn_ids are consistent with the returned meta list.
    """
    atlas = build_code_atlas(repo_path=repo_path, repo_name=Path(repo_path).name)
    fns = {}
    for fn_id, fn in atlas.get("functions", {}).items():
        if fn.get("lang") not in ("c", "cpp", "rust"):
            continue
        fns[fn_id] = {
            "fn_id": fn_id,
            "name": fn.get("name", ""),
            "file": str(fn.get("file", "")).replace("\\", "/"),
            "line": fn.get("line", 0),
            "fp": _fn_structure_fingerprint(fn)[FP],
            "sz": len(fn.get("tokens_normalized") or []),
        }
    edges = [(e["src_fn_id"], e["dst_fn_id"]) for e in atlas.get("edges", [])
             if e.get("dst_fn_id") and e.get("src_fn_id") in fns and e.get("dst_fn_id") in fns]
    return list(fns.values()), edges


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


def classify_provenance(tfns: list, fw: set, peer_fps: set, floor: int = PEER_TOKEN_FLOOR) -> dict:
    """Four-way + TRIVIAL classification. Shared by stage-2 CLI and stage-4 report.

    tfns: list of {name,file,line,fp,sz}; fw/peer_fps: fingerprint sets.
    Returns {class_name: [fn,...]}.
    """
    classes = {"EXTERNAL": [], "PORTED-FRAMEWORK": [], "PORTED-PEER": [], "ORIGINAL": [], "TRIVIAL": []}
    for f in tfns:
        if is_vendor(f["file"]):
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

    # token floor: see classify_provenance / DESIGN.md §5.7
    classes = classify_provenance(tfns, fw, peer_fps)

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
