#!/usr/bin/env python3
"""Bidirectional deterministic function comparison for immutable snapshots.

Raw statuses are exact_copied, renamed_exact, modified_candidate, target_only,
base_only, and ambiguous. Agent interpretation may add semantic explanations but
must never overwrite these raw statuses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fingerprint import build_units


def _is_excluded(file_path: str, prefixes: list[str]) -> bool:
    for p in prefixes:
        if file_path == p or file_path.startswith(p + "/") or file_path.startswith(p):
            return True
    return False


def compare_units(target: str, base: str, exclude_prefixes: list[str] | None = None,
                  branch: str = "", base_branch: str = "", *,
                  target_snapshot: "RepoSnapshot | None" = None,
                  base_snapshot: "RepoSnapshot | None" = None,
                  target_scope=None, base_scope=None,
                  output_dir: str = "") -> dict:
    """Bidirectional immutable-snapshot comparison.

    The legacy exclude_prefixes argument remains available for callers that have
    not created ScopeManifest objects yet. New callers should pass both scopes.
    target_snapshot/base_snapshot: pre-resolved RepoSnapshot objects (avoids double resolution).
    """
    from core.comparison import compare_unit_sets, write_comparison
    from core.scope import ScopeExclusion, build_scope_manifest, filter_units
    from core.snapshot import RepoSnapshot, resolve_snapshot

    target_path = f"repos/{target}" if "/" not in target else target
    base_path = f"repos/{base}" if "/" not in base else base
    if target_snapshot is None:
        target_snapshot = resolve_snapshot(target_path, branch or "HEAD")
    if base_snapshot is None:
        base_snapshot = resolve_snapshot(base_path, base_branch or "HEAD")
    if target_scope is None:
        target_scope = build_scope_manifest(target_snapshot, excluded=[ScopeExclusion(p, "agent_excluded", "legacy exclude_prefixes") for p in (exclude_prefixes or [])])
    if base_scope is None:
        base_scope = build_scope_manifest(base_snapshot)
    target_units = filter_units(build_units(target_path, snapshot=target_snapshot), target_scope)
    base_units = filter_units(build_units(base_path, snapshot=base_snapshot), base_scope)
    result = compare_unit_sets(target_units, base_units, target_snapshot=target_snapshot.to_dict(), base_snapshot=base_snapshot.to_dict())
    result["target_scope"] = target_scope.to_dict(); result["base_scope"] = base_scope.to_dict()
    if output_dir:
        result["artifacts"] = write_comparison(result, output_dir)
        result["database_counts"] = {"target_units": len(result.get("target_units") or []), "base_units": len(result.get("base_units") or []), "match_edges": len(result.get("match_edges") or []), "comparisons": len(result.get("comparisons") or [])}
        result.pop("target_units", None); result.pop("base_units", None); result.pop("match_edges", None); result.pop("comparisons", None)
    return result


if __name__ == "__main__":
    target = sys.argv[1]
    base = sys.argv[2]
    output_dir = sys.argv[3] if len(sys.argv) > 3 else ""
    result = compare_units(target, base, output_dir=output_dir)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))
