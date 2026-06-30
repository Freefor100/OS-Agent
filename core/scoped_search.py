from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from core.scope import ScopeManifest, filter_units, load_scope_manifest
from core.snapshot import RepoSnapshot, resolve_snapshot
from scripts.fingerprint import build_units


FORMAL_SCOPE_STATUSES = {"verified", "auto_candidate", "candidate_reviewed"}


def search_scoped(target_snapshot: RepoSnapshot, target_scope: ScopeManifest, candidates: Iterable[tuple[RepoSnapshot, ScopeManifest | None]],
                  *, top_k: int = 20, metadata=None, formal_only: bool = False) -> list[dict[str, Any]]:
    target_units = filter_units(build_units(target_snapshot.repo_path, snapshot=target_snapshot), target_scope)
    target_token, target_ast = _sets(target_units)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for snapshot, scope in candidates:
        key = (snapshot.repo, snapshot.commit)
        if key in seen or snapshot.commit == target_snapshot.commit and snapshot.repo == target_snapshot.repo:
            continue
        seen.add(key)
        formal_scope = scope is not None and scope.status in FORMAL_SCOPE_STATUSES
        if formal_only and not formal_scope:
            continue
        candidate_units = filter_units(build_units(snapshot.repo_path, snapshot=snapshot), scope)
        candidate_token, candidate_ast = _sets(candidate_units)
        token = _containment(target_token, candidate_token)
        ast = _containment(target_ast, candidate_ast)
        combined = max(token["balanced"], ast["balanced"])
        meta = metadata.lookup_by_repo_name(snapshot.repo) if metadata else None
        rows.append({
            "repo": snapshot.repo, "commit": snapshot.commit, "canonical_branch": snapshot.canonical_branch,
            "ref_aliases": snapshot.ref_aliases,
            "candidate_snapshot": snapshot.to_public_dict(),
            "target_scope_id": target_scope.scope_id if target_scope else "",
            "scope_id": scope.scope_id if scope else "",
            "candidate_scope_id": scope.scope_id if scope else "",
            "scope_status": scope.status if scope else "unreviewed",
            "score_kind": "formal" if formal_scope else "rough", "combined": round(combined, 3),
            "token": token, "ast": ast, "target_unit_count": len(target_units), "candidate_unit_count": len(candidate_units),
            "overlap_by_dir": _overlap_by_dir(target_units, candidate_token), "year": meta["year"] if meta else 0,
            "school": meta["school"] if meta else "", "is_framework": metadata.is_framework(snapshot.repo) if metadata else False,
        })
    rows.sort(key=lambda row: (-row["combined"], row["repo"], row["commit"]))
    for index, row in enumerate(rows, 1): row["rank"] = index
    return rows[:top_k]


def cached_candidate_snapshots(repos_dir: str = "repos") -> list[tuple[RepoSnapshot, ScopeManifest | None]]:
    rows: list[tuple[RepoSnapshot, ScopeManifest | None]] = []
    seen: set[tuple[str, str]] = set()
    for meta in sorted(Path('.fp_cache').glob('meta_*__*.json')):
        try:
            import json
            raw = json.loads(meta.read_text(encoding='utf-8'))
            repo, commit = str(raw['repo']), str(raw['commit'])
            key = (repo, commit)
            if key in seen: continue
            seen.add(key)
            snap = resolve_snapshot(str(Path(repos_dir) / repo), commit, materialize=False)
            rows.append((snap, load_scope_manifest(repo, commit)))
        except (OSError, KeyError, ValueError):
            continue
    return rows


def _sets(units: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    return ({str(x['fp']) for x in units if x.get('fp')}, {str(x['ast']) for x in units if x.get('ast') and x.get('lang') != 'asm'})


def _containment(left: set[str], right: set[str]) -> dict[str, Any]:
    shared = len(left & right)
    lc = shared / len(left) if left else 0.0; rc = shared / len(right) if right else 0.0
    return {"shared": shared, "target_total": len(left), "candidate_total": len(right), "target_containment": round(lc, 3),
            "candidate_containment": round(rc, 3), "balanced": round(min(lc, rc), 3)}


def _overlap_by_dir(target_units: list[dict[str, Any]], candidate_fps: set[str]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(lambda: {"shared": 0, "target": 0})
    for unit in target_units:
        directory = str(Path(str(unit.get('file') or '')).parent)
        if directory == ".": directory = "(root)"
        result[directory]["target"] += 1
        if unit.get('fp') in candidate_fps: result[directory]["shared"] += 1
    return dict(sorted(result.items(), key=lambda x: -x[1]["shared"]))
