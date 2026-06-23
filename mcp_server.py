#!/usr/bin/env python3
"""MCP server for auditable immutable-snapshot Base discovery and difference reports.

The host Agent owns judgment. Tools own deterministic fingerprints, dual-scope search,
bidirectional comparisons, Evidence verification, and program admission checks.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ensure repo root on sys.path BEFORE importing project modules
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("os-agent")

# ── singletons (lazy init) ──────────────────────────────────────────

_metadata_mgr = None
_evidence_stores = {}


def _get_metadata():
    global _metadata_mgr
    if _metadata_mgr is None:
        from core.metadata import MetadataManager
        _metadata_mgr = MetadataManager()
    return _metadata_mgr


# ── helpers ──────────────────────────────────────────────────────────

def _target_path(target: str) -> str:
    return f"repos/{target}" if "/" not in target else target


def _get_evidence_store(repo_path: str, evidence_store: str):
    """Reuse one EvidenceStore per JSONL path so concurrent Agent workers share locks and cache."""
    from core.evidence import EvidenceStore
    key = (str(Path(evidence_store).resolve()), str(Path(repo_path).resolve()))
    store = _evidence_stores.get(key)
    if store is None:
        store = EvidenceStore(repo_path, evidence_store)
        _evidence_stores[key] = store
    return store


def _lsp_snapshot_path(target: str, ref: str) -> str:
    """Materialize an immutable commit for LSP analysis."""
    from core.snapshot import resolve_snapshot
    snap = resolve_snapshot(_target_path(target), ref)
    return snap.materialized_path


# ── tool: repo_metadata ──────────────────────────────────────────────

@mcp.tool()
def repo_metadata(target: str) -> dict:
    """Lookup submission metadata from collected-data.xlsx by repo name or path.
    Returns year, school, team_name, competition, sub_event, is_framework.
    If the repo is not found in xlsx, returns is_framework=true with no school/team info.
    Use this in Phase 1 to get authoritative metadata instead of guessing from repo names."""
    mm = _get_metadata()
    # Try by repo name first, then by path
    meta = mm.lookup_by_repo_name(target)
    if not meta:
        meta = mm.lookup_by_repo_path(target)
    if meta:
        return {
            "repo": target,
            "year": meta.get("year", 0),
            "school": meta.get("school", ""),
            "team": meta.get("team_name") or meta.get("team") or "",
            "competition": meta.get("competition", ""),
            "sub_event": meta.get("sub_event", ""),
            "repo_url": meta.get("repo_url", ""),
            "is_framework": False,
        }
    return {
        "repo": target,
        "is_framework": True,
        "note": "Not found in xlsx — likely a framework or baseline reference",
    }



# ── tool: build_fingerprint ──────────────────────────────────────────

@mcp.tool()
def repo_snapshots(target: str, materialize: bool = False, include_other_branches: bool = False,
                   offset: int = 0, limit: int = 20) -> dict:
    """Return the clone's default checked-out branch tip plus unique branch-tip
    versions. This never walks historical commits. Branch aliases pointing to the
    same commit are merged; commit SHA remains the internal audit lock. Other branch
    tips are omitted by default and paginated when explicitly requested."""
    from core.snapshot import branch_tip_snapshots, default_snapshot
    path = _target_path(target)
    default = default_snapshot(path, materialize=materialize)
    rows = branch_tip_snapshots(path, materialize=materialize)
    others = [row for row in rows if not row["is_default"]]
    limit = max(1, min(int(limit), 50))
    return {
        "target": target,
        "selection_policy": "default_checked_out_branch_tip; inspect other unique branch tips only when needed",
        "default_snapshot": default.to_public_dict(),
        "other_branch_tip_count": len(others),
        "other_branch_tips_included": include_other_branches,
        "offset": offset if include_other_branches else 0,
        "limit": limit if include_other_branches else 0,
        "other_branch_tips": others[offset:offset + limit] if include_other_branches else [],
    }


@mcp.tool()
def build_fingerprint(target: str, ref: str = "", branch: str = "", all_branches: bool = False) -> dict:
    """Build fingerprints from immutable commits. Branch aliases sharing a commit are deduplicated."""
    from core.snapshot import discover_commit_snapshots, resolve_snapshot
    from core.scope import build_scope_manifest
    from scripts.fingerprint import build_units, fingerprint_set, ast_fingerprint_set, lang_summary
    commit_ref = ref or branch or "HEAD"
    snapshots = discover_commit_snapshots(_target_path(target), materialize=True) if all_branches else [resolve_snapshot(_target_path(target), commit_ref)]
    results = {}
    for snap in snapshots:
        units = build_units(_target_path(target), snapshot=snap)
        fps = fingerprint_set(_target_path(target), snapshot=snap)
        ast = ast_fingerprint_set(_target_path(target), snapshot=snap)
        scope = build_scope_manifest(snap, status="draft")
        results[snap.commit] = {"snapshot": snap.to_dict(), "scope_suggestion": scope.to_dict(), "units": len(units), "fingerprints": len(fps),
                                "ast_fingerprints": len(ast), "languages": lang_summary(units)}
    return {"target": target, "commit_count": len(results), "results": results}


# ── tool: search_similar ─────────────────────────────────────────────

@mcp.tool()
def search_similar(target: str, exclude_prefixes: list[str] | None = None,
                   top_k: int = 10, ref: str = "", branch: str = "") -> dict:
    """Rough 1-vs-N similarity recall using immutable snapshots and draft scope.

    This is navigation only. It cannot be used for BaseDecision or report ranking;
    call create_scope_manifest for reviewed candidates and then search_formal."""
    from core.scope import ScopeExclusion, build_scope_manifest
    from core.scoped_search import cached_candidate_snapshots, search_scoped
    from core.snapshot import resolve_snapshot
    mm = _get_metadata()
    commit_ref = ref or branch or "HEAD"
    snap = resolve_snapshot(_target_path(target), commit_ref)
    excluded = [ScopeExclusion(prefix, "agent_excluded", "rough recall exclude_prefixes")
                for prefix in (exclude_prefixes or [])]
    target_scope = build_scope_manifest(snap, excluded=excluded, status="draft")
    results = search_scoped(snap, target_scope, cached_candidate_snapshots(), top_k=top_k,
                            metadata=mm, formal_only=False)
    for row in results:
        row["score_kind"] = "rough"
    return {"target": target, "ref": commit_ref or "(default)", "score_kind": "rough",
            "warning": "rough recall only; cannot be used for BaseDecision or report ranking",
            "target_scope_suggestion": target_scope.to_dict(),
            "candidate_snapshot_count": len(cached_candidate_snapshots()),
            "candidates": results}


# ── tools: immutable scope + formal search ────────────────────────────

@mcp.tool()
def audit_manifest_create(target: str, output_dir: str, ref: str = "HEAD",
                          artifacts: dict | None = None) -> dict:
    """Create the auditable run manifest that fixes standard artifact paths."""
    from core.audit_manifest import create_audit_manifest
    from core.snapshot import resolve_snapshot
    snap = resolve_snapshot(_target_path(target), ref, materialize=False)
    return create_audit_manifest(snap.to_public_dict(), output_dir, artifacts=artifacts)


@mcp.tool()
def create_scope_manifest(target: str, ref: str = "HEAD", included_prefixes: list[str] | None = None,
                          excluded: list[dict] | None = None, generated_prefixes: list[str] | None = None,
                          documentation_prefixes: list[str] | None = None, status: str = "verified",
                          evidence_store: str = "") -> dict:
    """Validate and persist the Agent-selected code scope for one immutable commit."""
    from core.evidence import EvidenceStore
    from core.snapshot import resolve_snapshot
    from core.scope import build_scope_manifest, save_scope_manifest, verified_exclusion_errors
    snap = resolve_snapshot(_target_path(target), ref)
    scope = build_scope_manifest(snap, included_prefixes=included_prefixes, excluded=excluded,
                                 generated_prefixes=generated_prefixes, documentation_prefixes=documentation_prefixes,
                                 status=status)
    evidence_records = None
    if evidence_store:
        evidence_records = {row.evidence_id: row.__dict__ for row in EvidenceStore("", evidence_store).iter_full()}
    errors = verified_exclusion_errors(scope, evidence_records)
    if status == "verified" and excluded and not evidence_store:
        non_auto = [row for row in scope.excluded
                    if not (row.category == "external_submodule" and row.reason == "declared git submodule")]
        if non_auto:
            errors.append("verified Agent exclusions require evidence_store so evidence_ids can be verified")
    if errors:
        raise ValueError("; ".join(errors))
    return {"snapshot": snap.to_dict(), "scope": scope.to_dict(), "path": save_scope_manifest(scope)}


@mcp.tool()
def search_formal(target: str, ref: str = "HEAD", top_k: int = 20, formal_only: bool = True) -> dict:
    """Formal 1-vs-N search using each side's own ScopeManifest. Only formal results may select a Base."""
    from core.snapshot import resolve_snapshot
    from core.scope import load_scope_manifest
    from core.scoped_search import cached_candidate_snapshots, search_scoped
    snap = resolve_snapshot(_target_path(target), ref)
    scope = load_scope_manifest(snap.repo, snap.commit)
    if scope is None:
        raise ValueError("target has no ScopeManifest; call create_scope_manifest first")
    all_rows = search_scoped(snap, scope, cached_candidate_snapshots(), top_k=top_k, metadata=_get_metadata(), formal_only=False)
    rough = [x for x in all_rows if x.get("score_kind") == "rough"]
    coverage = {"coverage_complete": not rough, "requested_top_k": top_k,
                "cached_candidate_count": len(cached_candidate_snapshots()),
                "reviewed_scope_count": len(all_rows) - len(rough),
                "unreviewed_rough_count": len(rough),
                "reviewed_in_top_k": len(all_rows)-len(rough),
                "returned_in_top_k": len(all_rows), "unreviewed_commits": [x.get("commit") for x in rough]}
    rows = [x for x in all_rows if x.get("score_kind") == "formal"] if formal_only else all_rows
    return {"target_snapshot": snap.to_dict(), "target_scope": scope.to_dict(), "formal_only": formal_only,
            "candidate_coverage": coverage, "candidates_requiring_scope": rough, "candidates": rows}


@mcp.tool()
def base_evidence_packet(target: str, ref: str, formal_candidates: list[dict], target_year: int = 0, include_declarations: bool = True,
                         candidate_coverage: dict | None = None) -> dict:
    """Assemble the structured packet the host Agent must use when choosing a Base."""
    from core.base_decision import build_base_evidence_packet
    from core.snapshot import resolve_snapshot
    snap = resolve_snapshot(_target_path(target), ref)
    return build_base_evidence_packet(snap, formal_candidates, target_year=target_year, include_declarations=include_declarations, candidate_coverage=candidate_coverage)


@mcp.tool()
def validate_base_decision(decision: dict, packet: dict) -> dict:
    """Program admission check: Base must reference a verified formal candidate by commit."""
    from core.base_decision import validate_base_decision as validate
    errors = validate(decision, packet)
    return {"valid": not errors, "errors": errors}


@mcp.tool()
def base_decision_submit(decision: dict, packet: dict, output_path: str) -> dict:
    """Validate and persist the Agent's BaseDecision packet for the audit run."""
    import json, os
    from core.audit_manifest import find_manifest_for, update_manifest
    from core.base_decision import resolve_primary_candidate, validate_base_decision as validate
    errors = validate(decision, packet)
    result = {"valid": not errors, "errors": errors, "packet": packet, "decision": decision,
              "selected_candidate": resolve_primary_candidate(decision, packet)}
    if errors:
        return result
    output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, output)
    manifest, manifest_path = find_manifest_for(str(output))
    if manifest:
        update_manifest(manifest_path, artifacts={"base_decision": str(output)},
                        stages={"base_decision_validated": True}, status="base_decision_validated")
    result["path"] = str(output)
    return result


# ── tool: compare_functions ──────────────────────────────────────────

@mcp.tool()
def compare_functions(target: str, base: str, ref: str = "", base_ref: str = "", *, branch: str = "", base_branch: str = "", output_dir: str = "") -> dict:
    """Bidirectional immutable-snapshot comparison. Emits copied, renamed, modified candidates, additions, deletions, and ambiguities."""
    from core.scope import load_scope_manifest
    from core.snapshot import resolve_snapshot
    from scripts.attribute import compare_units
    target_ref = ref or branch or "HEAD"; base_ref_resolved = base_ref or base_branch or "HEAD"
    ts = resolve_snapshot(_target_path(target), target_ref); bs = resolve_snapshot(_target_path(base), base_ref_resolved)
    target_scope = load_scope_manifest(ts.repo, ts.commit); base_scope = load_scope_manifest(bs.repo, bs.commit)
    if target_scope is None or base_scope is None:
        raise ValueError("both target and base require verified ScopeManifest records")
    result = compare_units(target, base, target_snapshot=ts, base_snapshot=bs, target_scope=target_scope, base_scope=base_scope, output_dir=output_dir)
    if output_dir and result.get("artifacts"):
        from core.audit_manifest import find_manifest_for, update_manifest
        manifest, manifest_path = find_manifest_for(output_dir)
        if manifest:
            artifacts = result["artifacts"]
            update_manifest(manifest_path, artifacts={
                "comparison_database": artifacts.get("database"),
                "comparisons_jsonl": artifacts.get("comparisons"),
            }, stages={"comparison_built": True}, status="comparison_built")
    return result


@mcp.tool()
def comparison_overview(run_id: str) -> dict:
    """Compact Comparison database overview; does not return all functions."""
    from core.comparison_db import overview, resolve_database
    return overview(resolve_database(run_id))


@mcp.tool()
def comparison_hotspots(run_id: str, order_by: str = "modified", offset: int = 0, limit: int = 20) -> dict:
    from core.comparison_db import hotspots, resolve_database
    return hotspots(resolve_database(run_id), order_by, offset, limit)


@mcp.tool()
def comparison_directory_summary(run_id: str, path: str = "", side: str = "target") -> dict:
    from core.comparison_db import directory_summary, resolve_database
    return directory_summary(resolve_database(run_id), path, side)


@mcp.tool()
def comparison_directory_files(run_id: str, path: str = "", status: str = "", offset: int = 0, limit: int = 50) -> dict:
    from core.comparison_db import directory_files, resolve_database
    return directory_files(resolve_database(run_id), path, status, offset, limit)


@mcp.tool()
def comparison_by_status(run_id: str, status: str, path: str = "", offset: int = 0, limit: int = 50) -> dict:
    """Page through deterministic comparison records by status, optionally within a directory."""
    from core.comparison_db import comparisons_by_status, resolve_database
    return comparisons_by_status(resolve_database(run_id), status, path, offset, limit)


@mcp.tool()
def comparison_search_units(run_id: str, query: str = "", side: str = "target", path: str = "",
                            status: str = "", offset: int = 0, limit: int = 50) -> dict:
    """Search function/assembly units by symbol or path before drilling into a function or source group."""
    from core.comparison_db import resolve_database, search_units
    return search_units(resolve_database(run_id), query, side, path, status, offset, limit)


@mcp.tool()
def comparison_directory_sources(run_id: str, path: str = "", offset: int = 0, limit: int = 50) -> dict:
    """Aggregate candidate source files for one work directory."""
    from core.comparison_db import directory_sources, resolve_database
    return directory_sources(resolve_database(run_id), path, offset, limit)


@mcp.tool()
def comparison_file_summary(run_id: str, target_file: str) -> dict:
    from core.comparison_db import file_summary, resolve_database
    return file_summary(resolve_database(run_id), target_file)


@mcp.tool()
def comparison_file_functions(run_id: str, target_file: str, status: str = "", offset: int = 0, limit: int = 50) -> dict:
    from core.comparison_db import file_functions, resolve_database
    return file_functions(resolve_database(run_id), target_file, status, offset, limit)


@mcp.tool()
def comparison_file_sources(run_id: str, target_file: str) -> dict:
    from core.comparison_db import file_sources, resolve_database
    return file_sources(resolve_database(run_id), target_file)


@mcp.tool()
def comparison_source_file_targets(run_id: str, source_repo: str, source_file: str) -> dict:
    from core.comparison_db import resolve_database, source_file_targets
    return source_file_targets(resolve_database(run_id), source_repo, source_file)


@mcp.tool()
def comparison_base_only_files(run_id: str, offset: int = 0, limit: int = 100) -> dict:
    """Page through primary-Base units without deterministic target matches, grouped by Base file."""
    from core.comparison_db import base_only_files, resolve_database
    return base_only_files(resolve_database(run_id), offset, limit)


@mcp.tool()
def comparison_function(run_id: str, unit_id: str) -> dict:
    from core.comparison_db import function_detail, resolve_database
    return function_detail(resolve_database(run_id), unit_id)


@mcp.tool()
def comparison_function_candidates(run_id: str, unit_id: str, source_role: str = "", offset: int = 0, limit: int = 50) -> dict:
    from core.comparison_db import function_candidates, resolve_database
    return function_candidates(resolve_database(run_id), unit_id, source_role, offset, limit)


@mcp.tool()
def comparison_detail(run_id: str, comparison_id: str) -> dict:
    from core.comparison_db import comparison_detail as detail, resolve_database
    return detail(resolve_database(run_id), comparison_id)


@mcp.tool()
def comparison_source_group(run_id: str, comparison_id_or_hint_id: str) -> dict:
    from core.comparison_db import resolve_database, source_group
    return source_group(resolve_database(run_id), comparison_id_or_hint_id)


@mcp.tool()
def comparison_call_context(run_id: str, comparison_id: str) -> dict:
    """Compare deterministic incoming/outgoing call-neighbor names for one matched function pair."""
    from core.comparison_db import comparison_detail, resolve_database, run_metadata
    from core.snapshot import resolve_snapshot
    from scripts.fingerprint import build_units
    database = resolve_database(run_id); detail = comparison_detail(database, comparison_id)
    if detail.get("status") == "not_found":
        return detail
    meta = run_metadata(database)
    target_snap = resolve_snapshot(meta["target_snapshot"]["repo_path"], meta["target_snapshot"]["commit"])
    base_snap = resolve_snapshot(meta["base_snapshot"]["repo_path"], meta["base_snapshot"]["commit"])
    target_units = {x["unit_id"]: x for x in build_units(target_snap.repo_path, snapshot=target_snap)}
    base_units = {x["unit_id"]: x for x in build_units(base_snap.repo_path, snapshot=base_snap)}
    work = target_units.get(detail.get("target_unit_id")) or {}; reference = base_units.get(detail.get("selected_base_unit_id")) or {}
    work_in, ref_in = set(work.get("incoming_names") or []), set(reference.get("incoming_names") or [])
    work_out, ref_out = set(work.get("outgoing_names") or []), set(reference.get("outgoing_names") or [])
    return {"comparison_id": comparison_id,
            "work": {"incoming": sorted(work_in), "outgoing": sorted(work_out)},
            "reference": {"incoming": sorted(ref_in), "outgoing": sorted(ref_out)},
            "delta": {"incoming_added": sorted(work_in-ref_in), "incoming_removed": sorted(ref_in-work_in),
                      "outgoing_added": sorted(work_out-ref_out), "outgoing_removed": sorted(ref_out-work_out)}}


@mcp.tool()
def comparison_relationship_hints(run_id: str, hint_type: str = "", offset: int = 0, limit: int = 50) -> dict:
    from core.comparison_db import relationship_hints, resolve_database
    return relationship_hints(resolve_database(run_id), hint_type, offset, limit)


@mcp.tool()
def comparison_representatives(run_id: str, scope_type: str = "global", scope_value: str = "", limit: int = 10) -> dict:
    from core.comparison_db import representatives, resolve_database
    return representatives(resolve_database(run_id), scope_type, scope_value, limit)


@mcp.tool()
def comparison_add_secondary_source(run_id: str, source: str, ref: str = "HEAD", extra_filter_prefixes: list[str] | None = None) -> dict:
    """Add local MatchEdges from an Agent-selected secondary source without changing primary-Base statuses.

    extra_filter_prefixes: additional path prefixes to further narrow the secondary source beyond what its ScopeManifest already defines."""
    from core.comparison import build_match_edges
    from core.comparison_db import add_secondary_source, resolve_database, run_metadata
    from core.scope import filter_units, load_scope_manifest
    from core.snapshot import resolve_snapshot
    from scripts.fingerprint import build_units
    database = resolve_database(run_id); meta = run_metadata(database)
    target = resolve_snapshot(meta["target_snapshot"]["repo_path"], meta["target_snapshot"]["commit"])
    secondary = resolve_snapshot(_target_path(source), ref); target_scope = load_scope_manifest(target.repo, target.commit); secondary_scope = load_scope_manifest(secondary.repo, secondary.commit)
    if target_scope is None or secondary_scope is None or secondary_scope.status != "verified": raise ValueError("target and secondary source require verified ScopeManifest records")
    target_units = filter_units(build_units(target.repo_path, snapshot=target), target_scope); source_units = filter_units(build_units(secondary.repo_path, snapshot=secondary), secondary_scope)
    if extra_filter_prefixes: source_units = [x for x in source_units if any(str(x.get("file") or "").startswith(prefix) for prefix in extra_filter_prefixes)]
    edges = build_match_edges(target_units, source_units, source_role="secondary_source", source_repo=secondary.repo)
    return add_secondary_source(database, secondary.to_dict(), source_units, edges)


@mcp.tool()
def judge_report_create(comparison_run_id: str, evidence_store: str, output_path: str,
                        work_display_name: str = "", reference_display_name: str = "", overwrite: bool = False) -> dict:
    """Create the incomplete Claim-driven judge report skeleton. It becomes renderable only after all 112 nodes are reviewed."""
    import json
    from core.judge_report import create_judge_report, write_judge_report
    output = Path(output_path)
    if output.is_file() and not overwrite:
        existing = json.loads(output.read_text(encoding="utf-8"))
        candidate = create_judge_report(comparison_database=comparison_run_id, evidence_store=evidence_store,
                                        work_display_name=work_display_name, reference_display_name=reference_display_name)
        if existing.get("comparison_run_id") == candidate["comparison_run_id"]:
            return {"path": output_path, "existing": True, "comparison_run_id": existing.get("comparison_run_id"),
                    "report_generation": existing.get("report_generation"), "required_nodes": len((existing.get("taxonomy") or {}).get("nodes") or []),
                    "required_modules": len((existing.get("taxonomy") or {}).get("modules") or [])}
        raise ValueError("judge_report_create refused to overwrite existing report with a different comparison_run_id; use judge_report_fork_for_comparison or overwrite=true")
    report = create_judge_report(comparison_database=comparison_run_id, evidence_store=evidence_store,
                                 work_display_name=work_display_name, reference_display_name=reference_display_name)
    write_judge_report(report, output_path)
    from core.audit_manifest import find_manifest_for, update_manifest
    manifest, manifest_path = find_manifest_for(output_path)
    if manifest:
        update_manifest(manifest_path, artifacts={"report_json": output_path, "evidence_store": evidence_store,
                                                  "comparison_database": report["comparison_database"]},
                        stages={"judge_report_created": True}, status="judge_report_created")
    return {"path": output_path, "comparison_run_id": report["comparison_run_id"], "required_nodes": len(report["taxonomy"]["nodes"]),
            "required_modules": len(report["taxonomy"]["modules"]), "report_generation": report["report_generation"]}


@mcp.tool()
def judge_report_fork_for_comparison(old_report_path: str, comparison_run_id: str, output_path: str, evidence_store: str,
                                     work_display_name: str = "", reference_display_name: str = "", overwrite: bool = False) -> dict:
    """Fork an existing report after Base/Comparison changes. Migrated claims require rebind before render."""
    from core.judge_report import fork_judge_report_for_comparison, write_judge_report
    output = Path(output_path)
    if output.is_file() and not overwrite:
        raise ValueError("output_path already exists; pass overwrite=true or choose a new audit directory")
    report = fork_judge_report_for_comparison(old_report_path, comparison_database=comparison_run_id,
                                             evidence_store=evidence_store, work_display_name=work_display_name,
                                             reference_display_name=reference_display_name)
    write_judge_report(report, output_path)
    return {"path": output_path, "comparison_run_id": report["comparison_run_id"], "report_generation": report["report_generation"],
            "migration": report.get("migration"), "claims_requiring_rebind": sum(1 for x in report.get("claims") or [] if x.get("migration_status") == "needs_rebind")}


@mcp.tool()
def node_analysis_packet(report_path: str, node_id: str) -> dict:
    """Return one node's Scope, navigation hints, compact comparison representatives, and existing Agent writeback."""
    from core.judge_report import node_analysis_packet as packet
    return packet(report_path, node_id)


@mcp.tool()
def claim_submit(report_path: str, claim: dict, expected_generation: str = "") -> dict:
    """Submit one atomic Agent conclusion. Function states and numeric statistics cannot be written here."""
    from core.judge_report import claim_submit as submit
    return submit(report_path, claim, expected_generation=expected_generation)


@mcp.tool()
def claim_update(report_path: str, claim: dict, expected_generation: str = "") -> dict:
    from core.judge_report import claim_submit as submit
    if not claim.get("claim_id"):
        raise ValueError("claim_update requires claim_id")
    return submit(report_path, claim, expected_generation=expected_generation)


@mcp.tool()
def claim_list(report_path: str, node_id: str = "") -> dict:
    from core.judge_report import claim_list as rows
    return rows(report_path, node_id)


@mcp.tool()
def node_review_submit(report_path: str, review: dict, expected_generation: str = "") -> dict:
    from core.judge_report import node_review_submit as submit
    return submit(report_path, review, expected_generation=expected_generation)


@mcp.tool()
def node_review_bundle_submit(report_path: str, node_id: str, claims: list[dict], review: dict, expected_generation: str = "") -> dict:
    """Atomically submit one node worker's Claims and NodeReview; safe for concurrent sub-agent completion."""
    from core.judge_report import node_review_bundle_submit as submit
    return submit(report_path, node_id, claims, review, expected_generation=expected_generation)


@mcp.tool()
def module_review_submit(report_path: str, review: dict, expected_generation: str = "") -> dict:
    from core.judge_report import module_review_submit as submit
    return submit(report_path, review, expected_generation=expected_generation)


@mcp.tool()
def overall_assessment_submit(report_path: str, assessment: dict, expected_generation: str = "") -> dict:
    from core.judge_report import overall_assessment_submit as submit
    return submit(report_path, assessment, expected_generation=expected_generation)


@mcp.tool()
def judge_report_highlights_submit(report_path: str, highlights: dict, expected_generation: str = "") -> dict:
    from core.judge_report import report_highlights_submit as submit
    return submit(report_path, highlights, expected_generation=expected_generation)


@mcp.tool()
def claim_contract() -> dict:
    """Return legal Claim/NodeReview enum values and evidence requirements."""
    from core.judge_report import claim_contract as contract
    return contract()


@mcp.tool()
def node_review_draft_batch(report_path: str, node_ids: list[str], mode: str = "candidate_absent") -> dict:
    """Return draft-only NodeReview/Claim suggestions. This never writes report.json."""
    from core.judge_report import node_review_draft_batch as draft
    return draft(report_path, node_ids, mode)


@mcp.tool()
def judge_report_status(report_path: str) -> dict:
    from core.judge_report import judge_report_status as status
    return status(report_path)


@mcp.tool()
def judge_report_validate(report_path: str) -> dict:
    import json
    from core.judge_report import validate_judge_report
    errors = validate_judge_report(json.loads(Path(report_path).read_text(encoding="utf-8")), require_complete=True)
    return {"valid": not errors, "errors": errors}


@mcp.tool()
def judge_report_render(report_path: str, output_path: str) -> dict:
    import json
    from core.audit_manifest import artifact_status, find_manifest_for, update_manifest
    from scripts.judge_report import render
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    manifest, manifest_path = find_manifest_for(report_path)
    artifacts = artifact_status(manifest, str(Path(report_path).parent))
    missing_before_render = [x for x in artifacts["missing_artifacts"] if x != "report_html"]
    if missing_before_render:
        raise ValueError("cannot render judge report before audit artifacts exist: " + ", ".join(missing_before_render))
    output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(render(report), encoding="utf-8")
    if manifest:
        update_manifest(manifest_path, artifacts={"report_html": output_path},
                        stages={"judge_report_rendered": True}, status="judge_report_rendered")
    return {"report_path": report_path, "output_path": output_path, "bytes": output.stat().st_size}


@mcp.tool()
def provenance_export(comparison_run_id: str, output_path: str, work_display_name: str = "",
                      reference_display_name: str = "") -> dict:
    """Export the complete deterministic function-provenance appendix without Agent originality conclusions."""
    from core.audit_manifest import find_manifest_for, update_manifest
    from core.provenance_report import export_provenance
    result = export_provenance(comparison_run_id, output_path, work_display_name=work_display_name,
                               reference_display_name=reference_display_name)
    manifest, manifest_path = find_manifest_for(output_path)
    if manifest:
        update_manifest(manifest_path, artifacts={"provenance_json": output_path},
                        stages={"provenance_exported": True}, status="provenance_exported")
    return result


@mcp.tool()
def provenance_render(provenance_path: str, output_path: str) -> dict:
    import json
    from core.audit_manifest import find_manifest_for, update_manifest
    from scripts.provenance_report import render
    report = json.loads(Path(provenance_path).read_text(encoding="utf-8"))
    output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(render(report), encoding="utf-8")
    manifest, manifest_path = find_manifest_for(output_path)
    if manifest:
        update_manifest(manifest_path, artifacts={"provenance_html": output_path},
                        stages={"provenance_rendered": True}, status="provenance_rendered")
    return {"provenance_path": provenance_path, "output_path": output_path, "bytes": output.stat().st_size}


@mcp.tool()
def evidence_source(target: str, ref: str, evidence_store: str, kind: str, path: str, line: int = 0, line_end: int = 0,
                    symbol: str = "", label: str = "", strength: str = "strong", metadata: dict | None = None) -> dict:
    """Verify an immutable source location and persist a stable EvidenceRecord."""
    from core.snapshot import resolve_snapshot
    snap = resolve_snapshot(_target_path(target), ref); store = _get_evidence_store(snap.materialized_path, evidence_store)
    meta = {"snapshot_commit": snap.commit, **(metadata or {})}
    evidence_id = store.add_source(kind=kind, path=path, line=line, line_end=line_end or None, symbol=symbol, label=label, strength=strength, metadata=meta)
    return {"evidence_id": evidence_id, "record": store.by_id(evidence_id).compact(), "evidence_store": evidence_store}


@mcp.tool()
def evidence_source_batch(target: str, ref: str, evidence_store: str, sources: list[dict]) -> dict:
    """Register several source spans from one immutable snapshot in one call."""
    from core.snapshot import resolve_snapshot
    snap = resolve_snapshot(_target_path(target), ref); store = _get_evidence_store(snap.materialized_path, evidence_store)
    rows = []
    for source in sources:
        metadata = {"snapshot_commit": snap.commit, **(source.get("metadata") or {})}
        evidence_id = store.add_source(kind=source.get("kind") or "source_span", path=source["path"], line=int(source.get("line") or 0),
                                       line_end=int(source.get("line_end") or 0) or None, symbol=source.get("symbol") or "",
                                       label=source.get("label") or "", strength=source.get("strength") or "strong", metadata=metadata)
        rows.append({"evidence_id": evidence_id, "record": store.by_id(evidence_id).compact()})
    return {"evidence_store": evidence_store, "total": len(rows), "rows": rows}


@mcp.tool()
def evidence_get(evidence_store: str, evidence_id: str) -> dict:
    """Read one full globally shared EvidenceRecord, including its verified excerpt."""
    from core.evidence import EvidenceStore
    store = EvidenceStore("", evidence_store); record = store.by_id(evidence_id)
    return {"status": "not_found", "evidence_id": evidence_id} if record is None else record.__dict__


@mcp.tool()
def evidence_list(evidence_store: str, kind: str = "", path: str = "", offset: int = 0, limit: int = 50) -> dict:
    """Page through the globally shared EvidenceStore so workers can reuse existing evidence IDs."""
    from core.evidence import EvidenceStore
    store = EvidenceStore("", evidence_store)
    rows = [{**record.compact(), "snapshot_commit": record.metadata.get("snapshot_commit"), "query": record.query}
            for record in store.iter_full() if (not kind or record.kind == kind) and (not path or record.path.startswith(path))]
    rows.sort(key=lambda x: (x.get("path") or "", x.get("line_start") or 0, x["evidence_id"]))
    return {"total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset+limit]}


@mcp.tool()
def evidence_structured(target: str, ref: str, evidence_store: str, kind: str, label: str,
                        metadata: dict, content: str = "", path: str = "", line: int = 0,
                        line_end: int = 0, strength: str = "strong") -> dict:
    """Register verified structured evidence such as call graph, git history, scope manifest, or documentation."""
    from core.evidence import EvidenceCandidate
    from core.snapshot import resolve_snapshot
    allowed = {"call_edge", "lsp_call_graph", "git_history", "scope_manifest", "documentation"}
    if kind not in allowed:
        raise ValueError(f"unsupported structured evidence kind: {kind}")
    snap = resolve_snapshot(_target_path(target), ref); store = _get_evidence_store(snap.materialized_path, evidence_store)
    candidate = EvidenceCandidate(tool="lsp_call_graph" if kind in {"call_edge", "lsp_call_graph"} else kind, kind=kind,
                                  label=label, content=content, path=path, line_start=line or None, line_end=line_end or None, strength=strength,
                                  metadata={"snapshot_commit": snap.commit, **metadata})
    evidence_id = store.add(candidate)
    return {"evidence_id": evidence_id, "record": store.by_id(evidence_id).compact(), "evidence_store": evidence_store}


@mcp.tool()
def evidence_document(target: str, ref: str, evidence_store: str, path: str, label: str,
                      start_page: int = 0, end_page: int = 0, start_line: int = 0, end_line: int = 0,
                      strength: str = "medium") -> dict:
    """Read and register a PDF, DOCX, Markdown, or text document from an immutable snapshot."""
    from core.evidence import EvidenceCandidate
    from core.snapshot import resolve_snapshot
    snap = resolve_snapshot(_target_path(target), ref); store = _get_evidence_store(snap.materialized_path, evidence_store)
    metadata = {"snapshot_commit": snap.commit, "start_page": start_page or None, "end_page": end_page or None}
    candidate = EvidenceCandidate(tool="documentation", kind="documentation", path=path, line_start=start_line or None,
                                  line_end=end_line or None, label=label, strength=strength, metadata=metadata)
    evidence_id = store.add(candidate); record = store.by_id(evidence_id)
    return {"evidence_id": evidence_id, "record": record.compact(), "verified": record.verified,
            "excerpt": record.excerpt, "evidence_store": evidence_store}


@mcp.tool()
def evidence_formal_search(target: str, ref: str, candidate: dict, evidence_store: str, label: str = "") -> dict:
    """Verify one formal dual-Scope search result and persist BaseDecision evidence."""
    from core.evidence import EvidenceCandidate
    from core.scope import load_scope_manifest
    from core.snapshot import resolve_snapshot
    snap = resolve_snapshot(_target_path(target), ref); scope = load_scope_manifest(snap.repo, snap.commit)
    if scope is None or scope.status != "verified": raise ValueError("target requires a verified ScopeManifest")
    metadata = {"target_scope_id": scope.scope_id, "candidate_scope_id": candidate.get("candidate_scope_id") or candidate.get("scope_id"), "candidate_commit": candidate.get("commit"), "candidate_repo": candidate.get("repo"), "score_kind": candidate.get("score_kind"), "rank": candidate.get("rank"), "combined": candidate.get("combined")}
    store = _get_evidence_store(snap.materialized_path, evidence_store)
    evidence_id = store.add(EvidenceCandidate(tool="formal_search", kind="formal_search", label=label or f"formal rank {candidate.get('rank')}", strength="strong", metadata=metadata))
    return {"evidence_id": evidence_id, "record": store.by_id(evidence_id).compact(), "evidence_store": evidence_store}


@mcp.tool()
def negative_search(target: str, ref: str, subject: str, queries: list[str], symbols: list[str], paths: list[str], extensions: list[str], evidence_store: str = "") -> dict:
    """Execute a fixed negative-search plan against an immutable snapshot and persist evidence."""
    from core.evidence import NegativeSearchPlan, execute_negative_search
    from core.snapshot import resolve_snapshot
    snap = resolve_snapshot(_target_path(target), ref)
    evidence_path = Path(evidence_store) if evidence_store else Path("output") / target / "_audit" / "evidence_store.jsonl"
    store = _get_evidence_store(snap.materialized_path, str(evidence_path))
    plan = NegativeSearchPlan(snapshot_commit=snap.commit, subject=subject, queries=queries, symbols=symbols, paths=paths, extensions=extensions)
    result = execute_negative_search(snap.materialized_path, plan, store); result["evidence_store"] = str(evidence_path); return result


# ── tool: node_taxonomy ──────────────────────────────────────────────

@mcp.tool()
def node_taxonomy(node_id: str = "") -> dict:
    """Kernel design tree skeleton — the report framework. 14 subsystems, 112 leaf nodes.

    Pass node_id to get one node's detail (title + scope).
    Empty = full tree + analysis batches.

    The tree ORGANIZES the report; it does NOT judge plagiarism or workload.
    - scope: one-line boundary — what work counts as this node. Read it before
      deciding which functions belong here. Function→node assignment is YOUR call.
    - batches: explore in this cross-module dependency order. Earlier batches feed
      later judgement (e.g. context-switch + lock are analyzed alongside scheduler).
    """
    from core.kernel_tree import (
        ROOT_NODES_V2, ANALYSIS_ORDER_V2, ANALYSIS_BATCHES_V2,
        node_title_zh, node_title_en, node_scope,
    )

    if node_id:
        return {
            "node_id": node_id,
            "title_zh": node_title_zh(node_id),
            "title_en": node_title_en(node_id),
            "scope": node_scope(node_id),
        }

    tree = {}
    for root, children in ROOT_NODES_V2.items():
        tree[root] = {
            "title_zh": node_title_zh(root),
            "title_en": node_title_en(root),
            "children": [
                {"id": c, "title_zh": node_title_zh(c), "scope": node_scope(c)}
                for c in children
            ],
        }
    return {
        "roots": tree,
        "leaf_count": len(ANALYSIS_ORDER_V2),
        "order": ANALYSIS_ORDER_V2,
        "batches": ANALYSIS_BATCHES_V2,
        "batch_note": "Explore batch-by-batch in this cross-module dependency order; "
                      "submit Claims and NodeReviews to report.json after each batch.",
    }


# ── tool: compile_flags ──────────────────────────────────────────────

@mcp.tool()
def compile_flags(target: str, ref: str = "HEAD") -> dict:
    """Generate compile_flags.txt for LSP (clangd/rust-analyzer). Detects
    architecture, include paths, and defines from Makefile/Cargo.toml.
    Returns flags for the immutable snapshot selected by ref. LSP applies equivalent
    flags through its managed temporary configuration; the repository working tree
    is not modified."""
    from scripts.compile_flags import generate, _detect_arch
    repo = _lsp_snapshot_path(target, ref)
    content = generate(repo)
    return {"target": target, "ref": ref, "snapshot_path": repo, "arch": _detect_arch(Path(repo)),
            "flags": content.splitlines()}


# ── tools: immutable CodeAtlas navigation ────────────────────────────

@mcp.tool()
def code_atlas_overview(target: str, ref: str = "HEAD", limit: int = 8) -> dict:
    """Return immutable whole-repository structural statistics and high-centrality
    function candidates. Use this for inexpensive architecture reconnaissance and
    entry-point discovery, not as semantic call-chain evidence."""
    from core.snapshot import resolve_snapshot
    from scripts.fingerprint import code_atlas
    snap = resolve_snapshot(_target_path(target), ref)
    atlas = code_atlas(snap.repo_path, snapshot=snap)
    limit = max(0, min(int(limit), 20))
    functions = sorted(atlas.get("functions", {}).items(), key=lambda x: -float(x[1].get("pagerank") or 0))[:limit]
    return {"snapshot": {"snapshot_id": snap.snapshot_id, "repo": snap.repo, "commit": snap.commit,
                         "tree_hash": snap.tree_hash, "ref_aliases": snap.ref_aliases},
            "stats": atlas.get("stats") or {}, "central_function_limit": limit,
            "note": "Central functions are reconnaissance candidates, not semantic call-chain evidence.",
            "central_functions": [{"fn_id": fn_id, "name": row.get("name"), "file": row.get("file"), "line": row.get("line"),
                                   "pagerank": row.get("pagerank"), "in_degree": row.get("in_degree"), "out_degree": row.get("out_degree")}
                                  for fn_id, row in functions]}


@mcp.tool()
def code_atlas_search(target: str, ref: str = "HEAD", query: str = "", path: str = "", kind: str = "function",
                      offset: int = 0, limit: int = 50) -> dict:
    """Search immutable CodeAtlas functions or types by name/path."""
    from core.snapshot import resolve_snapshot
    from scripts.fingerprint import code_atlas
    snap = resolve_snapshot(_target_path(target), ref); atlas = code_atlas(snap.repo_path, snapshot=snap)
    source = atlas.get("types" if kind == "type" else "functions", {})
    rows = [{"id": item_id, **{k: row.get(k) for k in ("name", "kind", "file", "line", "end_line", "lang", "signature", "pagerank", "in_degree", "out_degree", "fields")}}
            for item_id, row in source.items()
            if (not query or query.lower() in str(row.get("name") or "").lower()) and (not path or str(row.get("file") or "").startswith(path))]
    rows.sort(key=lambda x: (x.get("file") or "", x.get("line") or 0, x.get("name") or ""))
    return {"snapshot_commit": snap.commit, "kind": kind, "total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset+limit]}


@mcp.tool()
def code_atlas_call_neighbors(target: str, ref: str, symbol: str, file: str = "", direction: str = "both",
                              offset: int = 0, limit: int = 100) -> dict:
    """Return deterministic tree-sitter call-edge candidates around a symbol.
    Prefer lsp_call_graph for semantic confirmation of key chains; use this for
    broad navigation, pagination, cross-checking, or when LSP is unavailable."""
    from core.snapshot import resolve_snapshot
    from scripts.fingerprint import code_atlas
    snap = resolve_snapshot(_target_path(target), ref); atlas = code_atlas(snap.repo_path, snapshot=snap)
    functions = atlas.get("functions") or {}
    selected = {fn_id for fn_id, row in functions.items() if row.get("name") == symbol and (not file or row.get("file") == file)}
    rows = []
    for edge in atlas.get("edges") or []:
        outgoing = edge.get("src_fn_id") in selected
        incoming = edge.get("dst_fn_id") in selected
        if (direction in {"both", "outgoing"} and outgoing) or (direction in {"both", "incoming"} and incoming):
            src = functions.get(edge.get("src_fn_id")) or {}; dst = functions.get(edge.get("dst_fn_id")) or {}
            rows.append({"src": {"fn_id": edge.get("src_fn_id"), "name": src.get("name"), "file": src.get("file"), "line": src.get("line")},
                         "dst": {"fn_id": edge.get("dst_fn_id"), "name": dst.get("name") or edge.get("callee_name"), "file": dst.get("file"), "line": dst.get("line")},
                         "resolution": edge.get("resolution"), "callsite_line": edge.get("callsite_line")})
    return {"snapshot_commit": snap.commit, "symbol": symbol, "matched_functions": len(selected), "total": len(rows),
            "offset": offset, "limit": limit, "rows": rows[offset:offset+limit]}


# ── tools: LSP (exposing 5 lsp_ops.py @tool functions) ──────────────

@mcp.tool()
def lsp_definition(target: str, symbol: str, file: str = "", ref: str = "HEAD") -> str:
    """Real LSP goto-definition via clangd/rust-analyzer. Falls back through
    tree-sitter → language-aware regex → grep → asm lexical parser if LSP
    is unavailable. Runs against the immutable Git snapshot selected by ref and
    returns file:line locations with confidence metadata."""
    from tools.lsp_ops import lsp_get_definition
    return lsp_get_definition(_lsp_snapshot_path(target, ref), file, symbol)


@mcp.tool()
def lsp_references(target: str, symbol: str, file: str = "", ref: str = "HEAD") -> str:
    """LSP find-all-references. Returns file:line locations where the symbol is used
    across the entire project. Falls back through tree-sitter → language-aware regex
    → grep → asm lexical parser. Runs against the immutable Git snapshot selected by
    ref.

    Use this when tracing copy patterns — see if a suspicious function is called from
    the same places as in the base repo, or if it has been integrated differently."""
    from tools.lsp_ops import lsp_get_references
    return lsp_get_references(_lsp_snapshot_path(target, ref), file, symbol)


@mcp.tool()
def lsp_document_outline(target: str, file: str, ref: str = "HEAD") -> str:
    """LSP document symbol outline. Returns all functions, structs, enums, constants
    with line numbers. Useful as a pre-read map before diving into large kernel files
    (500+ lines). Runs against the immutable Git snapshot selected by ref."""
    from tools.lsp_ops import lsp_get_document_outline
    return lsp_get_document_outline(_lsp_snapshot_path(target, ref), file)


@mcp.tool()
def lsp_call_graph(target: str, symbol: str, file: str,
                   direction: str = "outgoing", max_depth: int = 3,
                   ref: str = "HEAD") -> str:
    """LSP call hierarchy — recursively builds a call graph tree.
    'outgoing' = functions called BY this symbol (who does it call).
    'incoming' = functions that call THIS symbol (who calls it).
    'both' = both directions.

    Essential for tracing kernel critical paths (fork, page_fault, syscall handler)
    and verifying whether copied code has been re-integrated or just pasted in.

    Runs against the immutable Git snapshot selected by ref.
    max_depth: 1-5 (default 3). Contains built-in crash recovery for build.rs failures."""
    from tools.lsp_ops import lsp_get_call_graph
    return lsp_get_call_graph(_lsp_snapshot_path(target, ref), file, symbol, direction, max_depth)


@mcp.tool()
def lsp_set_target_arch(target: str, arch: str, ref: str = "HEAD") -> str:
    """Override auto-detected target triple for LSP. Force-restarts clangd/rust-analyzer
    for the repo. Use when #[cfg] code is grayed out or LSP returns empty results due
    to wrong architecture detection.

    Common target triples:
    - riscv64gc-unknown-none-elf (RISC-V 64)
    - loongarch64-unknown-none-elf (LoongArch 64)
    - x86_64-unknown-none-elf (x86_64 Bare Metal)
    - aarch64-unknown-none-elf (ARM64 Bare Metal)"""
    from tools.lsp_ops import lsp_set_target_arch
    return lsp_set_target_arch(_lsp_snapshot_path(target, ref), arch)


# ── tool: read_doc ───────────────────────────────────────────────────

@mcp.tool()
def read_doc(target: str, path: str, start_page: int = 1, end_page: int = 0) -> str:
    """Read a PDF or Docx document from the target repo. For PDF, reads pages.
    For Docx, reads paragraphs. Claude Code's built-in bash can't do this."""
    from tools.file_ops import read_code_segment
    return read_code_segment(f"{_target_path(target)}/{path}",
                             start_page=start_page, end_page=end_page or None)


# ── entry ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
