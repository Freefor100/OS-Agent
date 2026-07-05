#!/usr/bin/env python3
"""Prepare immutable fingerprints and auditable search inputs.

The host Agent chooses scopes and the Base. This driver only materializes commits,
builds deterministic fingerprints, creates default manifests, and runs scoped search.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def split_repo_ref(spec: str, default_ref: str = "HEAD") -> tuple[str, str]:
    """Parse repo@ref while keeping the old repo + --ref calling style."""
    if "@" not in spec:
        return spec, default_ref
    repo, ref = spec.rsplit("@", 1)
    if not repo or not ref:
        raise ValueError("expected repo@ref, for example oskernel2023-zmz@main")
    return repo, ref


def build_snapshot(snapshot, exclude_prefixes: list[str] | None = None) -> dict:
    from core.scope import build_scope_manifest
    from core.scoped_search import warm_scoped_index
    from scripts.fingerprint import build_units_from_git_commit, fingerprint_set, lang_summary
    excluded = [
        {"prefix": prefix, "category": "source_excluded", "reason": "excluded during fingerprint build"}
        for prefix in (exclude_prefixes or [])
    ]
    units = build_units_from_git_commit(snapshot.repo_path, snapshot=snapshot, exclude_prefixes=exclude_prefixes)
    scope = build_scope_manifest(snapshot, excluded=excluded, status="draft")
    candidate_scope = build_scope_manifest(snapshot, excluded=excluded, status="auto_candidate")
    scoped_index = warm_scoped_index(snapshot, candidate_scope)
    return {"snapshot": snapshot.to_dict(), "scope_suggestion": scope.to_dict(), "units": len(units), "languages": lang_summary(units),
            "fingerprints": len(fingerprint_set(snapshot.repo_path, snapshot=snapshot)),
            "scoped_index": scoped_index}


def build_all(repos_dir: str = "repos", ref: str = "HEAD", all_branches: bool = True,
              exclude_prefixes: list[str] | None = None) -> list[dict]:
    from core.snapshot import discover_commit_snapshots, resolve_snapshot
    results=[]; entries=sorted(x for x in Path(repos_dir).iterdir() if x.is_dir() and not x.name.startswith("."))
    for i, repo in enumerate(entries,1):
        try:
            snapshots=discover_commit_snapshots(str(repo), materialize=False) if all_branches else [resolve_snapshot(str(repo), ref, materialize=False)]
            for snap in snapshots:
                result=build_snapshot(snap, exclude_prefixes=exclude_prefixes); results.append(result); print(f"[{i}/{len(entries)}] {repo.name} {snap.commit[:12]} {result['units']} units")
        except Exception as exc:
            print(f"[{i}/{len(entries)}] {repo.name}: ERROR {exc}", file=sys.stderr)
    return results


def build_one(target: str, ref: str, exclude_prefixes: list[str] | None = None) -> dict:
    from core.snapshot import resolve_snapshot
    path = str(Path("repos") / target) if "/" not in target else target
    snapshot = resolve_snapshot(path, ref, materialize=False)
    result = build_snapshot(snapshot, exclude_prefixes=exclude_prefixes)
    print(f"{snapshot.repo} {snapshot.canonical_branch or ref} {snapshot.commit[:12]} {result['units']} units")
    return result


def prepare_target(target: str, ref: str, top_k: int) -> dict:
    from core.scope import load_scope_manifest
    from core.scoped_search import cached_candidate_snapshots, search_scoped
    from core.snapshot import resolve_snapshot
    path = str(Path("repos") / target) if "/" not in target else target
    snapshot = resolve_snapshot(path, ref); built = build_snapshot(snapshot); scope=load_scope_manifest(snapshot.repo,snapshot.commit)
    candidates=search_scoped(snapshot, scope, cached_candidate_snapshots(), top_k=top_k, formal_only=False)
    return {"prepared":built,"rough_and_formal_candidates":candidates,
            "next":"Agent reviews candidates_requiring_scope, creates their ScopeManifest, then reruns formal search"}


def main() -> None:
    parser=argparse.ArgumentParser(description="Prepare fingerprints and scoped search inputs")
    parser.add_argument("target",nargs="?",help="repo name/path, optionally repo@ref; with --build this builds only that repo")
    parser.add_argument("--build",action="store_true",help="build fingerprint cache; add repo@ref to build one repo/ref")
    parser.add_argument("--ref",default="HEAD",help="Git ref used when target does not include @ref")
    parser.add_argument("--all-branches",action="store_true",help="compatibility no-op: --build already builds each unique branch-tip commit")
    parser.add_argument("--current-only",action="store_true",help="build only the selected ref, usually the checked-out HEAD")
    parser.add_argument("--exclude-prefix",action="append",default=[],help="source path prefix to skip while building fingerprints; repeatable")
    parser.add_argument("--top-k",type=int,default=20)
    args=parser.parse_args()
    if args.build:
        if args.target:
            target, ref = split_repo_ref(args.target, args.ref)
            build_one(target, ref, exclude_prefixes=args.exclude_prefix)
            return
        build_all(ref=args.ref,all_branches=not args.current_only,exclude_prefixes=args.exclude_prefix)
        return
    if not args.target: parser.error("target is required unless --build is used")
    target, ref = split_repo_ref(args.target, args.ref)
    print(json.dumps(prepare_target(target,ref,args.top_k),ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
