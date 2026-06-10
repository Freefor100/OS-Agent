#!/usr/bin/env python3
"""Stage-B exclusion rules — what code counts as "the student's own"?

After stage-A (Agent reads Cargo/Makefile/.gitmodules/README), we know:
  - which dirs are vendored frameworks (arceos/, rCore/...)
  - which dirs are external deps (vendor/, bash-*, dependency/, submodules...)
  - which dirs are workspace members (Cargo.toml [workspace] members)
  - which dirs contain the student's own crates (path deps with no external git)

This module turns those facts into deterministic exclude/include rules so the
fingerprint layer only processes the student's WORK, not their environment.

It does NOT:
  - read Cargo/Makefile itself (stage-A does that) — it CONSUMES their output
  - do similarity / classification
  - guess which dirs are external (no preset dictionary — LLM fills the gaps)

Output: .fp_cache/exclude_<name>.json = list of {"rule": "include|exclude",
"pattern": "prefix/path/**", "reason": "..."}

The rules are consumed by provenance.classify_provenance (stage-2) to tag
EXTERNAL / FRAMEWORK units without relying on fingerprint overlap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def default_exclude_rules(repo_root: Path, declarations: dict) -> list[dict]:
    """Generate exclude/include rules from deterministic manifest sources ONLY.

    What's covered here (no LLM needed — the project declares these itself):
      - Cargo.toml [workspace] members/exclude
      - Cargo.toml path dependencies
      - .gitmodules submodule paths
      - vendor/ directory (cargo vendor — tool convention, not a guess)

    What is NOT covered (waits for stage-A LLM):
      - prose lineage ("we forked xv6-loongson")
      - vendored framework dirs not in Cargo exclude (e.g. arceos/ without Cargo)
      - GNU bash / busybox / musl / ... as top-level dirs without .gitmodules
      - Makefile-linked third-party code

    The LLM stage (stage-3b) fills the gaps by reading README, Makefile, prose
    docs, and writing additional entries into the declared JSON. This module
    consumes whatever is there — no preset dictionary, no guessing.
    """
    rules: list[dict] = []

    # ---- Cargo vendored crates (tool convention, not a guess) ----
    if (repo_root / "vendor").is_dir():
        rules.append({"rule": "exclude", "pattern": "vendor/**", "reason": "cargo vendored crates"})

    # ---- .gitmodules submodule paths (project's own declaration) ----
    gm = repo_root / ".gitmodules"
    if gm.exists():
        for line in gm.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("path"):
                d = line.split("=", 1)[1].strip()
                rules.append({"rule": "exclude", "pattern": f"{d}/**", "reason": f"git submodule: {d}"})

    # ---- vendored frameworks (from Cargo.toml [workspace] exclude) ----
    for d in declarations.get("vendored_frameworks", []):
        rules.append({"rule": "exclude", "pattern": f"{d}/**", "reason": f"vendored framework: {d}"})

    # ---- external directories (from Cargo.toml [workspace] exclude, non-framework) ----
    for d in declarations.get("external_dirs", []):
        rules.append({"rule": "exclude", "pattern": f"{d}/**", "reason": f"cargo workspace exclude: {d}"})

    # ---- explicit external dirs (filled by LLM after reading docs/structure) ----
    for d in declarations.get("llm_external_dirs", []):
        rules.append({"rule": "exclude", "pattern": f"{d}/**", "reason": f"LLM-identified external: {d}"})

    # ---- workspace members = student's own code (Cargo.toml) ----
    for m in declarations.get("workspace_members", []):
        if m.strip("."):
            rules.append({"rule": "include", "pattern": f"{m}/**", "reason": "workspace member"})

    # ---- path dependencies = student's own crates ----
    for p in declarations.get("path_deps", []):
        rules.append({"rule": "include", "pattern": f"{p}/**", "reason": "path dependency"})

    # ---- LLM-identified student dirs (e.g. os/src/ in a non-Cargo project) ----
    for d in declarations.get("llm_student_dirs", []):
        rules.append({"rule": "include", "pattern": f"{d}/**", "reason": "LLM-identified student dir"})

    # dedup
    seen = set()
    out = []
    for r in rules:
        k = (r["rule"], r["pattern"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def apply_exclude(rules: list[dict], file_path: str) -> tuple[bool, str]:
    """Check a single filepath against the rule set.

    Returns (is_excluded: bool, matched_reason: str). Include rules take
    priority over exclude rules (student's own crates override blanket excludes).
    """
    reason = ""
    excluded = False
    for r in rules:
        pattern = r["pattern"].rstrip("/**")
        if file_path == pattern or file_path.startswith(pattern + "/") or file_path.startswith(pattern):
            if r["rule"] == "include":
                return False, ""  # explicit include always wins
            excluded = True
            reason = r["reason"]
    return excluded, reason


def load_rules(target: str) -> list[dict]:
    """Load or build exclude rules for a target repo, cached to .fp_cache."""
    cf = Path(".fp_cache") / f"exclude_{target}.json"
    if cf.exists():
        return json.loads(cf.read_text())

    repo = Path(f"repos/{target}") if not target.startswith("repos/") else Path(target)
    # declarations come from stage-A (Agent or declarations.py structural pass)
    decl_path = Path(f"/tmp/declared_{repo.name}.json")
    decl = json.loads(decl_path.read_text()) if decl_path.exists() else {}
    rules = default_exclude_rules(repo, decl)
    cf.parent.mkdir(exist_ok=True)
    cf.write_text(json.dumps(rules, ensure_ascii=False, indent=2))
    return rules


if __name__ == "__main__":
    target = sys.argv[1]
    rules = load_rules(target)
    for r in rules:
        print(f"  {r['rule']:8s}  {r['pattern']:28s}  # {r['reason']}")
