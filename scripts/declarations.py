#!/usr/bin/env python3
"""Stage-3a declaration extraction — deterministic, no LLM.

Parses what a submission *declares* about its dependencies and lineage from its
own manifest/doc files. This is the factual half of the declaration cross-check
(§5.6): the LLM later only judges declared-vs-fingerprint conflicts, it does not
hunt for the declarations itself.

Sources:
  Cargo.toml / Cargo.lock   git deps + crates.io deps (Rust)
  .gitmodules               submodule git URLs (C/C++ third-party)
  README* / *.md            github.com references in prose (self-reported lineage)

Output: /tmp/declared_<target>.json  -> {git_deps, crates, submodules, readme_refs}
The stage-4 report reads this to populate the cross-check, and a future LLM step
reconciles it against the fingerprint provenance.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

GIT_RE = re.compile(r'git\s*=\s*"(https://[^"]+)"')
# code-host references in prose: github.com AND gitlab.eduxiji.net (the contest's
# own GitLab — most submissions cite lineage there, not github). Missing this
# host blanked readme_refs for nearly all contest entries.
HOST_RE = re.compile(r'https://(?:github\.com|gitlab\.eduxiji\.net)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
CRATE_RE = re.compile(r'^\s*([a-zA-Z0-9_-]+)\s*=\s*"[\d.]+"', re.MULTILINE)
SUBMOD_RE = re.compile(r'url\s*=\s*(\S+)')


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def extract(repo: Path) -> dict:
    git_deps, crates, submodules, readme_refs = set(), set(), set(), set()

    # Cargo.toml (workspace root + nested, but skip vendored/third-party trees)
    for cargo in repo.rglob("Cargo.toml"):
        rel = str(cargo.relative_to(repo))
        if any(seg in rel for seg in ("vendor/", "third", ".cargo", "dependency/")):
            continue
        txt = read(cargo)
        git_deps.update(GIT_RE.findall(txt))
        crates.update(CRATE_RE.findall(txt))

    # .gitmodules
    gm = repo / ".gitmodules"
    if gm.exists():
        submodules.update(SUBMOD_RE.findall(read(gm)))

    # README / top-level markdown — self-reported lineage ("基于 xv6", "参考 AVX"...)
    for md in list(repo.glob("README*")) + list(repo.glob("*.md")):
        readme_refs.update(HOST_RE.findall(read(md)))

    # normalize code-host refs to owner/repo for matching (github + contest gitlab)
    def owner_repo(url: str) -> str:
        m = re.search(r'(?:github\.com|gitlab\.eduxiji\.net)/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$',
                      url.rstrip("/"))
        return m.group(1) if m else url

    return {
        "git_deps": sorted({owner_repo(u) for u in git_deps}),
        "crates": sorted(crates)[:40],
        "submodules": sorted({owner_repo(u) for u in submodules}),
        "readme_refs": sorted({owner_repo(u) for u in readme_refs}),
    }


def main():
    target = sys.argv[1]
    repo = Path(f"repos/{target}")
    decl = extract(repo)
    out = Path(f"/tmp/declared_{target}.json")
    out.write_text(json.dumps(decl, ensure_ascii=False, indent=2))
    print(f"declarations -> {out}")
    for k, v in decl.items():
        print(f"  {k:12s}: {len(v)}  {v[:6]}")


if __name__ == "__main__":
    main()
