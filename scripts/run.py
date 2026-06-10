#!/usr/bin/env python3
"""One-button 1-vs-N pipeline driver.

Per-repo flow:
  [A] declarations.py   extract Cargo structure + submodules + lineage refs
  [B] fingerprint.py    build unified fingerprints (code + asm), cached
  [C] search.py         1-vs-N search -> top-K similar corpus members
  [D] report.py          provenance + report (peers = search candidates)

Framework baseline is auto-detected from search results: if a known framework
appears among top candidates, use it. Otherwise macrokernel -> framework=none.

Usage:
  python scripts/run.py <target>            # single repo
  python scripts/run.py --build             # pre-build corpus fingerprints (once)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# frameworks whose presence in search results signals a component-based paradigm
FRAMEWORKS = {
    "_baseline_oscomp-arceos": "repos/_baseline_oscomp-arceos",
    "arceos": "repos/_baseline_oscomp-arceos",
    "rCore-Tutorial-v3": "repos/rCore-Tutorial-v3",
    "ucore_os_lab": "repos/ucore_os_lab",
}


def pick_framework(candidates: list[dict], threshold: float = 0.10) -> str:
    """If a known framework appears among top candidates above threshold,
    it's the component baseline. Otherwise macrokernel."""
    for c in candidates:
        if c["repo"] in FRAMEWORKS and c["combined"] >= threshold:
            return FRAMEWORKS[c["repo"]]
    return "none"


def run_one(target: str):
    print(f"\n=== {target} ===")

    # [0] compile_flags for LSP (clangd needs --target=riscv64 etc.)
    subprocess.run([sys.executable, "scripts/compile_flags.py", f"repos/{target}"], check=False)

    # [A] declarations
    print("  [A] declarations...")
    subprocess.run([sys.executable, "scripts/declarations.py", target], check=False)

    # [B] build fingerprint (cached — instant if already built)
    print("  [B] fingerprint...")
    subprocess.run([sys.executable, "-c",
                    f"from scripts.fingerprint import build_units; u=build_units('repos/{target}'); print('  units='+str(len(u)))"],
                   check=False)

    # [C] 1-vs-N search (cached corpus — instant if pre-built with --build)
    print("  [C] search...")
    subprocess.run([sys.executable, "scripts/search.py", target, "10"], check=False)

    # auto-detect paradigm from search results
    from scripts.search import search as do_search
    candidates = do_search(target, top_k=20)
    fw = pick_framework(candidates)

    # [D] deep comparison vs best candidate
    print("  [D] deep compare...")
    subprocess.run([sys.executable, "scripts/attribute.py", target], check=False)

    # [E] report — pass top candidates as peers
    peers = [c["repo"] for c in candidates[:10] if not c["is_framework"]]
    paradigm = "组件化" if fw != "none" else "宏内核"
    print(f"  [{paradigm}] framework={fw}  peers={len(peers)}")
    cmd = [sys.executable, "scripts/report.py", target, fw] + peers
    subprocess.run(cmd, check=False)


def main():
    if sys.argv[1:] == ["--build"]:
        print("pre-building corpus fingerprints (one-time, then cached)...")
        subprocess.run([sys.executable, "-c",
                        "from scripts.search import corpus_fingerprints; "
                        "c=corpus_fingerprints(build_missing=True); "
                        "print(f'corpus: {len(c)} repos indexed')"],
                       check=False)
    else:
        run_one(sys.argv[1])


if __name__ == "__main__":
    main()
