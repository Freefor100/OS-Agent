#!/usr/bin/env python3
"""One-button driver — auto-detect paradigm, pick baseline, run report.

Closes the last manual seam: the operator no longer decides "is this ArceOS or
macrokernel?" nor types a framework baseline. Both are derived from the stage-1
cluster file (output/lineage_clusters.json).

Paradigm = if the target's lineage family contains a known framework baseline
(arceos/rCore/...), it's component-based -> use that baseline; else macrokernel
-> framework=none, earlier same-family member acts as base via PORTED-PEER.

Usage:
  python scripts/run.py <target>            # single repo
  python scripts/run.py --all               # every clustered repo + overview
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# known framework baselines and the repo dir that holds the version-correct copy
FRAMEWORK_BASELINE = {
    "arceos": "repos/_baseline_oscomp-arceos",       # contest fork, see DESIGN §9
    "Starry": "repos/_baseline_oscomp-arceos",
    "starry-mix": "repos/_baseline_oscomp-arceos",
    "rCore-Tutorial-v3": "repos/rCore-Tutorial-v3",
    "ucore_os_lab": "repos/ucore_os_lab",
}


def pick_framework(target: str, clusters: dict) -> str:
    """Return baseline repo path, or 'none' for macrokernel paradigm."""
    fam = next((f for f in clusters["families"] if target in f), [target])
    for member in fam:
        if member in FRAMEWORK_BASELINE and Path(FRAMEWORK_BASELINE[member]).exists():
            return FRAMEWORK_BASELINE[member]
    return "none"


def run_one(target: str, clusters: dict):
    fw = pick_framework(target, clusters)
    paradigm = "组件化" if fw != "none" else "宏内核"
    print(f"\n=== {target}  [{paradigm}]  framework={fw} ===")
    # 3a: deterministic declaration extraction (Cargo/.gitmodules/README github refs)
    subprocess.run([sys.executable, "scripts/declarations.py", target], check=False)
    # 4: report assembly
    subprocess.run([sys.executable, "scripts/report.py", target, fw], check=False)


def main():
    clusters = json.loads(Path("output/lineage_clusters.json").read_text())
    if sys.argv[1:] == ["--all"]:
        targets = [t for t in clusters["year"]
                   if t not in FRAMEWORK_BASELINE and not t.startswith("_baseline")]
        print(f"running {len(targets)} repos...")
        for t in targets:
            run_one(t, clusters)
        subprocess.run([sys.executable, "scripts/overview.py"], check=False)
    else:
        run_one(sys.argv[1], clusters)


if __name__ == "__main__":
    main()
