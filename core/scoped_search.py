from __future__ import annotations

from collections import defaultdict
import pickle
from pathlib import Path
from typing import Any, Iterable

from core.scope import ScopeManifest, filter_units, load_scope_manifest
from core.snapshot import RepoSnapshot
from scripts.fingerprint import FINGERPRINT_SCHEMA, build_units


FORMAL_SCOPE_STATUSES = {"verified", "auto_candidate", "candidate_reviewed"}
SCOPED_SET_SCHEMA = "scoped_search_sets_v1"
SCOPED_SET_ROOT = Path(".fp_cache") / "scoped_sets"


def search_scoped(target_snapshot: RepoSnapshot, target_scope: ScopeManifest, candidates: Iterable[tuple[RepoSnapshot, ScopeManifest | None]],
                  *, top_k: int = 20, metadata=None, formal_only: bool = False) -> list[dict[str, Any]]:
    target_token, target_ast, target_unit_count, target_fp_dirs = _scoped_index(target_snapshot, target_scope)
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
        candidate_token, candidate_ast, candidate_unit_count, _ = _scoped_index(snapshot, scope)
        token = _containment(target_token, candidate_token)
        ast = _containment(target_ast, candidate_ast)
        combined = max(token["balanced"], ast["balanced"])
        rows.append({
            "repo": snapshot.repo, "commit": snapshot.commit, "canonical_branch": snapshot.canonical_branch,
            "ref_aliases": snapshot.ref_aliases,
            "candidate_snapshot": snapshot.to_public_dict(),
            "target_scope_id": target_scope.scope_id if target_scope else "",
            "scope_id": scope.scope_id if scope else "",
            "candidate_scope_id": scope.scope_id if scope else "",
            "scope_status": scope.status if scope else "unreviewed",
            "score_kind": "formal" if formal_scope else "rough", "combined": round(combined, 3),
            "token": token, "ast": ast, "target_unit_count": target_unit_count, "candidate_unit_count": candidate_unit_count,
            "_snapshot": snapshot, "_scope": scope,
        })
    rows.sort(key=lambda row: (-row["combined"], row["repo"], row["commit"]))
    top_rows = rows[:top_k]
    for index, row in enumerate(top_rows, 1):
        row["rank"] = index
        candidate_token, _, _, _ = _scoped_index(row["_snapshot"], row["_scope"])
        row["overlap_by_dir"] = _overlap_by_dir(target_fp_dirs, candidate_token)
        meta = metadata.lookup_by_repo_name(row["repo"]) if metadata else None
        row["year"] = meta["year"] if meta else 0
        row["school"] = meta["school"] if meta else ""
        row["is_framework"] = metadata.is_framework(row["repo"]) if metadata else False
        row.pop("_snapshot", None)
        row.pop("_scope", None)
    return top_rows


def cached_candidate_snapshots(repos_dir: str = "repos") -> list[tuple[RepoSnapshot, ScopeManifest | None]]:
    del repos_dir
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
            snap = _snapshot_from_meta(raw)
            rows.append((snap, load_scope_manifest(repo, commit)))
        except (OSError, KeyError, ValueError):
            continue
    return rows


def _snapshot_from_meta(raw: dict[str, Any]) -> RepoSnapshot:
    return RepoSnapshot(
        snapshot_id=str(raw["snapshot_id"]),
        repo=str(raw["repo"]),
        repo_path=str(raw["repo_path"]),
        commit=str(raw["commit"]),
        tree_hash=str(raw["tree_hash"]),
        canonical_branch=str(raw.get("canonical_branch") or ""),
        ref_aliases=list(raw.get("ref_aliases") or []),
        materialized_path=str(raw.get("materialized_path") or raw["repo_path"]),
        schema_version=str(raw.get("schema_version") or "git_snapshot_v1"),
    )


def _sets(units: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    return ({str(x['fp']) for x in units if x.get('fp')}, {str(x['ast']) for x in units if x.get('ast') and x.get('lang') != 'asm'})


def _scoped_units(snapshot: RepoSnapshot, scope: ScopeManifest | None) -> list[dict[str, Any]]:
    return filter_units(build_units(snapshot.repo_path, snapshot=snapshot), scope)


def warm_scoped_index(snapshot: RepoSnapshot, scope: ScopeManifest | None) -> dict[str, Any]:
    token, ast, unit_count, _ = _scoped_index(snapshot, scope)
    return {"repo": snapshot.repo, "commit": snapshot.commit, "scope_id": scope.scope_id if scope else "", "units": unit_count, "fingerprints": len(token), "ast_fingerprints": len(ast)}


def _scoped_index(snapshot: RepoSnapshot, scope: ScopeManifest | None) -> tuple[set[str], set[str], int, list[tuple[str, str]]]:
    path = _scoped_set_path(snapshot, scope)
    if path.is_file():
        try:
            payload = pickle.loads(path.read_bytes())
            return set(payload["token"]), set(payload["ast"]), int(payload["unit_count"]), list(payload["fp_dirs"])
        except (OSError, KeyError, TypeError, pickle.PickleError, ValueError):
            pass
    units = _scoped_units(snapshot, scope)
    token, ast = _sets(units)
    fp_dirs = _fp_dirs(units)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps({"token": token, "ast": ast, "unit_count": len(units), "fp_dirs": fp_dirs}))
    return token, ast, len(units), fp_dirs


def _scoped_set_path(snapshot: RepoSnapshot, scope: ScopeManifest | None) -> Path:
    scope_key = scope.scope_id if scope else "all"
    schema = FINGERPRINT_SCHEMA.replace("fingerprint_", "fp-").replace("_", "-")
    return SCOPED_SET_ROOT / (
        f"sets_{snapshot.repo}__{snapshot.commit[:16]}__{snapshot.tree_hash[:12]}__"
        f"{scope_key}__{schema}__{SCOPED_SET_SCHEMA}.pkl"
    )


def _containment(left: set[str], right: set[str]) -> dict[str, Any]:
    shared = len(left & right)
    lc = shared / len(left) if left else 0.0; rc = shared / len(right) if right else 0.0
    return {"shared": shared, "target_total": len(left), "candidate_total": len(right), "target_containment": round(lc, 3),
            "candidate_containment": round(rc, 3), "balanced": round(min(lc, rc), 3)}


def _fp_dirs(units: list[dict[str, Any]]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for unit in units:
        fp = str(unit.get("fp") or "")
        if not fp:
            continue
        directory = str(Path(str(unit.get('file') or '')).parent)
        if directory == ".":
            directory = "(root)"
        rows.append((fp, directory))
    return rows


def _overlap_by_dir(target_fp_dirs: list[tuple[str, str]], candidate_fps: set[str]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(lambda: {"shared": 0, "target": 0})
    for fp, directory in target_fp_dirs:
        result[directory]["target"] += 1
        if fp in candidate_fps: result[directory]["shared"] += 1
    return dict(sorted(result.items(), key=lambda x: -x[1]["shared"]))
