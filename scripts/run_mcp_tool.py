#!/usr/bin/env python3
"""Run one os-agent MCP tool function with JSON args.

Usage: python3 scripts/run_mcp_tool.py <tool_name> '<json_args>'
"""
from __future__ import annotations
import json, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Ensure we have the right env
os.environ.setdefault("PYTHONUNBUFFERED", "1")

tool_name = sys.argv[1]
args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

if tool_name == "repo_metadata":
    from core.metadata import MetadataManager
    mm = MetadataManager()
    meta = mm.lookup_by_repo_name(args["target"])
    if not meta:
        meta = mm.lookup_by_repo_path(args["target"])
    if meta:
        result = {
            "repo": args["target"],
            "year": meta.get("year", 0),
            "school": meta.get("school", ""),
            "team": meta.get("team_name") or meta.get("team") or "",
            "competition": meta.get("competition", ""),
            "sub_event": meta.get("sub_event", ""),
            "repo_url": meta.get("repo_url", ""),
            "is_framework": False,
        }
    else:
        result = {"repo": args["target"], "is_framework": True, "note": "Not found in xlsx"}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "audit_manifest_create":
    from core.audit_manifest import create_audit_manifest
    from core.snapshot import resolve_snapshot
    target = args["target"]
    out_dir = args["output_dir"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref, materialize=False)
    artifacts = args.get("artifacts")
    result = create_audit_manifest(snap.to_public_dict(), out_dir, artifacts=artifacts)
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "build_fingerprint":
    from core.snapshot import resolve_snapshot
    from core.scope import build_scope_manifest
    from scripts.fingerprint import build_units_from_git_commit, fingerprint_set, ast_fingerprint_set, lang_summary
    target = args["target"]
    ref = args.get("ref", "") or args.get("branch", "") or "HEAD"
    all_branches = args.get("all_branches", False)
    path = f"repos/{target}" if "/" not in target else target
    if all_branches:
        from core.snapshot import discover_commit_snapshots
        snapshots = discover_commit_snapshots(path, materialize=False)
    else:
        snapshots = [resolve_snapshot(path, ref, materialize=False)]
    results = {}
    for snap in snapshots:
        units = build_units_from_git_commit(path, snapshot=snap)
        fps = fingerprint_set(path, snapshot=snap)
        ast_fps = ast_fingerprint_set(path, snapshot=snap)
        scope = build_scope_manifest(snap, status="draft")
        results[snap.commit] = {
            "snapshot": snap.to_dict(),
            "scope_suggestion": scope.to_dict(),
            "units": len(units),
            "fingerprints": len(fps),
            "ast_fingerprints": len(ast_fps),
            "languages": lang_summary(units),
        }
    result = {"target": target, "commit_count": len(results), "results": results}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "create_scope_manifest":
    from core.snapshot import resolve_snapshot
    from core.scope import build_scope_manifest, save_scope_manifest, verified_exclusion_errors
    from core.evidence import EvidenceStore
    target = args["target"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    included = args.get("included_prefixes")
    excluded = args.get("excluded")
    generated = args.get("generated_prefixes")
    documentation = args.get("documentation_prefixes")
    status = args.get("status", "verified")
    evidence_store_path = args.get("evidence_store", "")
    scope = build_scope_manifest(snap, included_prefixes=included, excluded=excluded,
                                 generated_prefixes=generated, documentation_prefixes=documentation,
                                 status=status)
    evidence_records = None
    if evidence_store_path:
        evidence_records = {row.evidence_id: row.__dict__ for row in EvidenceStore("", evidence_store_path).iter_full()}
    errors = verified_exclusion_errors(scope, evidence_records)
    if errors:
        result = {"error": f"Scope exclusion verification failed: {errors}", "errors": errors}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)
    saved = save_scope_manifest(scope)
    result = {"scope_id": scope.scope_id, "commit": snap.commit, "status": scope.status,
              "included_prefixes": len(scope.included_prefixes or []), "excluded": len(scope.excluded or []),
              "generated": len(scope.generated_prefixes or []), "documentation": len(scope.documentation_prefixes or []),
              "evidence_store": evidence_store_path, "save_path": str(saved)}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "evidence_source":
    from core.snapshot import resolve_snapshot
    from core.evidence import EvidenceStore, assert_clean_worktree
    target = args["target"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    store = EvidenceStore(snap.repo_path, args["evidence_store"])
    assert_clean_worktree(snap.repo_path, snap.commit)
    meta = {"snapshot_commit": snap.commit, **(args.get("metadata") or {})}
    evidence_id = store.add_source(kind=args["kind"], path=args["path"], line=args.get("line", 0),
                                   line_end=args.get("line_end") or None, symbol=args.get("symbol", ""),
                                   label=args.get("label", ""), strength=args.get("strength", "strong"),
                                   metadata=meta)
    result = {"evidence_id": evidence_id, "record": store.by_id(evidence_id).compact(),
              "evidence_store": args["evidence_store"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "evidence_source_batch":
    from core.snapshot import resolve_snapshot
    from core.evidence import EvidenceStore, assert_clean_worktree
    target = args["target"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    store = EvidenceStore(snap.repo_path, args["evidence_store"])
    assert_clean_worktree(snap.repo_path, snap.commit)
    rows = []
    for source in args.get("sources", []):
        meta = {"snapshot_commit": snap.commit, **(source.get("metadata") or {})}
        evidence_id = store.add_source(kind=source.get("kind", "source_span"), path=source["path"],
                                       line=int(source.get("line", 0)), line_end=int(source.get("line_end", 0)) or None,
                                       symbol=source.get("symbol", ""), label=source.get("label", ""),
                                       strength=source.get("strength", "strong"), metadata=meta)
        rows.append({"evidence_id": evidence_id, "record": store.by_id(evidence_id).compact()})
    result = {"evidence_store": args["evidence_store"], "total": len(rows), "rows": rows}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "evidence_structured":
    from core.evidence import EvidenceCandidate
    from core.snapshot import resolve_snapshot
    from core.evidence import EvidenceStore, assert_clean_worktree
    allowed = {"call_edge", "lsp_call_graph", "git_history", "scope_manifest", "scope_exclusion_decision", "documentation"}
    kind = args["kind"]
    if kind not in allowed:
        raise ValueError(f"unsupported structured evidence kind: {kind}")
    target = args["target"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    store = EvidenceStore(snap.repo_path, args["evidence_store"])
    assert_clean_worktree(snap.repo_path, snap.commit)
    candidate = EvidenceCandidate(tool="lsp_call_graph" if kind in {"call_edge", "lsp_call_graph"} else kind,
                                  kind=kind, label=args.get("label", ""), content=args.get("content", ""),
                                  path=args.get("path", ""), line_start=args.get("line") or None,
                                  line_end=args.get("line_end") or None, strength=args.get("strength", "strong"),
                                  metadata={"snapshot_commit": snap.commit, **(args.get("metadata") or {})})
    evidence_id = store.add(candidate)
    result = {"evidence_id": evidence_id, "record": store.by_id(evidence_id).compact(),
              "evidence_store": args["evidence_store"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "evidence_get":
    from core.evidence import EvidenceStore
    store = EvidenceStore("", args["evidence_store"])
    record = store.by_id(args["evidence_id"])
    if record is None:
        result = {"status": "not_found", "evidence_id": args["evidence_id"]}
    else:
        result = record.__dict__
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "evidence_list":
    from core.evidence import EvidenceStore
    store = EvidenceStore("", args["evidence_store"])
    kind_filter = args.get("kind", "")
    path_filter = args.get("path", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    rows = [{**record.compact(), "snapshot_commit": record.metadata.get("snapshot_commit"), "query": record.query}
            for record in store.iter_full()
            if (not kind_filter or record.kind == kind_filter) and (not path_filter or record.path.startswith(path_filter))]
    rows.sort(key=lambda x: (x.get("path") or "", x.get("line_start") or 0, x["evidence_id"]))
    result = {"total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset+limit]}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "search_formal":
    from core.snapshot import resolve_snapshot
    from core.scope import build_scope_manifest, load_scope_manifest
    from core.scoped_search import FORMAL_SCOPE_STATUSES, cached_candidate_snapshots, search_scoped
    target = args["target"]
    ref = args.get("ref", "HEAD")
    top_k = args.get("top_k", 20)
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    scope = load_scope_manifest(snap.repo, snap.commit)
    if scope is None or scope.status != "verified":
        raise ValueError("target requires a verified ScopeManifest; call create_scope_manifest for the target first")
    candidate_rows = []
    auto_candidate_count = 0
    mm = __import__('core.metadata', fromlist=['MetadataManager']).MetadataManager()
    for candidate_snap, candidate_scope in cached_candidate_snapshots():
        if candidate_scope is None or candidate_scope.status not in FORMAL_SCOPE_STATUSES:
            candidate_scope = build_scope_manifest(candidate_snap, status="auto_candidate")
            auto_candidate_count += 1
        candidate_rows.append((candidate_snap, candidate_scope))
    formal_results = search_scoped(snap, scope, candidate_rows, top_k=top_k, metadata=mm, formal_only=args.get("formal_only", True))
    result = {
        "target": target, "ref": ref, "formal_result_count": len(formal_results),
        "candidate_count": len(candidate_rows), "auto_candidate_count": auto_candidate_count,
        "formal_results": formal_results,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "base_evidence_packet":
    from core.base_decision import build_base_evidence_packet
    from core.snapshot import resolve_snapshot
    target = args["target"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    formal_candidates = args.get("formal_candidates", [])
    target_year = args.get("target_year", 0)
    include_declarations = args.get("include_declarations", True)
    candidate_coverage = args.get("candidate_coverage")
    result = build_base_evidence_packet(snap, formal_candidates, target_year=target_year,
                                        include_declarations=include_declarations,
                                        candidate_coverage=candidate_coverage)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "validate_base_decision":
    from core.base_decision import validate_base_decision as validate
    errors = validate(args["decision"], args.get("packet", {}), evidence_store=args.get("evidence_store", ""))
    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "base_decision_submit":
    import os as _os
    from pathlib import Path as _Path
    from core.audit_manifest import find_manifest_for, update_manifest
    from core.base_decision import resolve_primary_candidate, validate_base_decision as validate
    decision = args["decision"]
    packet = args.get("packet", {})
    output_path = args["output_path"]
    errors = validate(decision, packet)
    result = {"valid": not errors, "errors": errors, "packet": packet, "decision": decision,
              "selected_candidate": resolve_primary_candidate(decision, packet)}
    if errors:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)
    output = _Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.{_os.getpid()}.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    _os.replace(tmp, output)
    manifest, manifest_path = find_manifest_for(str(output))
    if manifest:
        update_manifest(manifest_path, artifacts={"base_decision": str(output)},
                        stages={"base_decision_validated": True}, status="base_decision_validated")
    result["path"] = str(output)
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "compare_functions":
    from core.snapshot import resolve_snapshot
    from core.scope import load_scope_manifest
    from scripts.attribute import compare_units
    target = args["target"]
    base = args["base"]
    target_ref = args.get("ref", "") or args.get("branch", "") or "HEAD"
    base_ref = args.get("base_ref", "") or args.get("base_branch", "") or "HEAD"
    output_dir = args.get("output_dir", "")
    tp = f"repos/{target}" if "/" not in target else target
    bp = f"repos/{base}" if "/" not in base else base
    ts = resolve_snapshot(tp, target_ref)
    bs = resolve_snapshot(bp, base_ref)
    target_scope = load_scope_manifest(ts.repo, ts.commit)
    base_scope = load_scope_manifest(bs.repo, bs.commit)
    if target_scope is None or base_scope is None:
        raise ValueError("both target and base require verified ScopeManifest records")
    result = compare_units(target, base, target_snapshot=ts, base_snapshot=bs,
                           target_scope=target_scope, base_scope=base_scope, output_dir=output_dir)
    if output_dir and result.get("artifacts"):
        from core.audit_manifest import find_manifest_for, update_manifest
        manifest, manifest_path = find_manifest_for(output_dir)
        if manifest:
            artifacts = result["artifacts"]
            update_manifest(manifest_path, artifacts={
                "comparison_database": artifacts.get("database"),
                "comparisons_jsonl": artifacts.get("comparisons"),
            }, stages={"comparison_built": True}, status="comparison_built")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_overview":
    from core.comparison_db import overview, resolve_database
    result = overview(resolve_database(args["run_id"]))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_hotspots":
    from core.comparison_db import hotspots, resolve_database
    order_by = args.get("order_by", "modified")
    offset = args.get("offset", 0)
    limit = args.get("limit", 20)
    result = hotspots(resolve_database(args["run_id"]), order_by, offset, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_search_units":
    from core.comparison_db import resolve_database, search_units
    query = args.get("query", "")
    side = args.get("side", "target")
    path = args.get("path", "")
    status = args.get("status", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    result = search_units(resolve_database(args["run_id"]), query, side, path, status, offset, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_by_status":
    from core.comparison_db import comparisons_by_status, resolve_database
    status = args["status"]
    path = args.get("path", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    result = comparisons_by_status(resolve_database(args["run_id"]), status, path, offset, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_directory_summary":
    from core.comparison_db import directory_summary, resolve_database
    path = args.get("path", "")
    side = args.get("side", "target")
    result = directory_summary(resolve_database(args["run_id"]), path, side)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_directory_files":
    from core.comparison_db import directory_files, resolve_database
    path = args.get("path", "")
    status = args.get("status", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    result = directory_files(resolve_database(args["run_id"]), path, status, offset, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_file_summary":
    from core.comparison_db import file_summary, resolve_database
    result = file_summary(resolve_database(args["run_id"]), args["target_file"])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_file_functions":
    from core.comparison_db import file_functions, resolve_database
    status = args.get("status", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    result = file_functions(resolve_database(args["run_id"]), args["target_file"], status, offset, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_function":
    from core.comparison_db import function_detail, resolve_database
    result = function_detail(resolve_database(args["run_id"]), args["unit_id"])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_function_candidates":
    from core.comparison_db import function_candidates, resolve_database
    source_role = args.get("source_role", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    result = function_candidates(resolve_database(args["run_id"]), args["unit_id"], source_role, offset, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_detail":
    from core.comparison_db import comparison_detail as detail, resolve_database
    result = detail(resolve_database(args["run_id"]), args["comparison_id"])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_call_context":
    from core.comparison_db import comparison_detail, resolve_database, run_metadata
    from core.snapshot import resolve_snapshot
    from scripts.fingerprint import build_units
    database = resolve_database(args["run_id"])
    detail = comparison_detail(database, args["comparison_id"])
    if detail.get("status") == "not_found":
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        sys.exit(0)
    meta = run_metadata(database)
    target_snap = resolve_snapshot(meta["target_snapshot"]["repo_path"], meta["target_snapshot"]["commit"])
    base_snap = resolve_snapshot(meta["base_snapshot"]["repo_path"], meta["base_snapshot"]["commit"])
    target_units = {x["unit_id"]: x for x in build_units(target_snap.repo_path, snapshot=target_snap)}
    base_units = {x["unit_id"]: x for x in build_units(base_snap.repo_path, snapshot=base_snap)}
    work = target_units.get(detail.get("target_unit_id")) or {}
    reference = base_units.get(detail.get("selected_base_unit_id")) or {}
    work_in, ref_in = set(work.get("incoming_names") or []), set(reference.get("incoming_names") or [])
    work_out, ref_out = set(work.get("outgoing_names") or []), set(reference.get("outgoing_names") or [])
    result = {"comparison_id": args["comparison_id"],
              "work": {"incoming": sorted(work_in), "outgoing": sorted(work_out)},
              "reference": {"incoming": sorted(ref_in), "outgoing": sorted(ref_out)},
              "delta": {"incoming_added": sorted(work_in-ref_in), "incoming_removed": sorted(ref_in-work_in),
                        "outgoing_added": sorted(work_out-ref_out), "outgoing_removed": sorted(ref_out-work_out)}}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_base_only_files":
    from core.comparison_db import base_only_files, resolve_database
    offset = args.get("offset", 0)
    limit = args.get("limit", 100)
    result = base_only_files(resolve_database(args["run_id"]), offset, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "judge_report_create":
    import json as _json
    from core.judge_report import create_judge_report, write_judge_report
    output_path = args["output_path"]
    output = Path(output_path)
    overwrite = args.get("overwrite", False)
    if output.is_file() and not overwrite:
        existing = _json.loads(output.read_text(encoding="utf-8"))
        candidate = create_judge_report(comparison_database=args["comparison_run_id"],
                                        evidence_store=args["evidence_store"],
                                        work_display_name=args.get("work_display_name", ""),
                                        reference_display_name=args.get("reference_display_name", ""))
        if existing.get("comparison_run_id") == candidate["comparison_run_id"]:
            result = {"path": output_path, "existing": True, "comparison_run_id": existing.get("comparison_run_id"),
                      "report_generation": existing.get("report_generation"),
                      "required_nodes": len((existing.get("taxonomy") or {}).get("nodes") or []),
                      "required_modules": len((existing.get("taxonomy") or {}).get("modules") or [])}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(0)
        raise ValueError("judge_report_create refused to overwrite existing report with a different comparison_run_id")
    report = create_judge_report(comparison_database=args["comparison_run_id"],
                                 evidence_store=args["evidence_store"],
                                 work_display_name=args.get("work_display_name", ""),
                                 reference_display_name=args.get("reference_display_name", ""))
    write_judge_report(report, output_path)
    from core.audit_manifest import find_manifest_for, update_manifest
    manifest, manifest_path = find_manifest_for(output_path)
    if manifest:
        update_manifest(manifest_path, artifacts={"report_json": output_path},
                        stages={"judge_report_created": True}, status="judge_report_created")
    result = {"path": output_path, "comparison_run_id": report["comparison_run_id"],
              "report_generation": report["report_generation"],
              "required_nodes": len((report.get("taxonomy") or {}).get("nodes") or []),
              "required_modules": len((report.get("taxonomy") or {}).get("modules") or [])}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "module_analysis_packet":
    from core.judge_report import module_analysis_packet as packet
    result = packet(args["report_path"], args["module_id"])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "node_analysis_packet":
    from core.judge_report import node_analysis_packet as packet
    result = packet(args["report_path"], args["node_id"])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "node_review_bundle_submit":
    from core.judge_report import node_review_bundle_submit as submit
    result = submit(args["report_path"], args["node_id"], args.get("claims", []),
                    args.get("review", {}), expected_generation=args.get("expected_generation", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "claim_submit":
    from core.judge_report import claim_submit as submit
    result = submit(args["report_path"], args["claim"], expected_generation=args.get("expected_generation", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "claim_update":
    from core.judge_report import claim_submit as submit
    if not args["claim"].get("claim_id"):
        raise ValueError("claim_update requires claim_id")
    result = submit(args["report_path"], args["claim"], expected_generation=args.get("expected_generation", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "claim_list":
    from core.judge_report import claim_list as rows
    result = rows(args["report_path"], args.get("node_id", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "node_review_submit":
    from core.judge_report import node_review_submit as submit
    result = submit(args["report_path"], args["review"], expected_generation=args.get("expected_generation", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "module_review_submit":
    from core.judge_report import module_review_submit as submit
    result = submit(args["report_path"], args["review"], expected_generation=args.get("expected_generation", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "overall_assessment_submit":
    from core.judge_report import overall_assessment_submit as submit
    result = submit(args["report_path"], args["assessment"], expected_generation=args.get("expected_generation", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "judge_report_status":
    from core.judge_report import judge_report_status as status
    result = status(args["report_path"])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "judge_report_validate":
    import json as _json
    from core.judge_report import validate_judge_report
    report = _json.loads(Path(args["report_path"]).read_text(encoding="utf-8"))
    errors = validate_judge_report(report, require_complete=True)
    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "judge_report_render":
    import json as _json
    from core.audit_manifest import artifact_status, find_manifest_for, update_manifest
    from scripts.judge_report import render_to_file
    report_path = args["report_path"]
    output_path = args["output_path"]
    report = _json.loads(Path(report_path).read_text(encoding="utf-8"))
    manifest, manifest_path = find_manifest_for(report_path)
    artifacts = artifact_status(manifest, str(Path(report_path).parent)) if manifest else {"missing_artifacts": []}
    missing = [x for x in artifacts.get("missing_artifacts", []) if x != "report_html"]
    if missing:
        raise ValueError("missing audit artifacts: " + ", ".join(missing))
    output = Path(output_path)
    render_to_file(report, output)
    if manifest:
        update_manifest(manifest_path, artifacts={"report_html": output_path},
                        stages={"judge_report_rendered": True}, status="judge_report_rendered")
    result = {"report_path": report_path, "output_path": output_path, "bytes": output.stat().st_size}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "provenance_export":
    from core.audit_manifest import find_manifest_for, update_manifest
    from core.provenance_report import export_provenance
    result = export_provenance(args["comparison_run_id"], args["output_path"],
                               work_display_name=args.get("work_display_name", ""),
                               reference_display_name=args.get("reference_display_name", ""))
    manifest, manifest_path = find_manifest_for(args["output_path"])
    if manifest:
        update_manifest(manifest_path, artifacts={"provenance_json": args["output_path"]},
                        stages={"provenance_exported": True}, status="provenance_exported")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "provenance_render":
    import json as _json
    from core.audit_manifest import find_manifest_for, update_manifest
    from scripts.provenance_report import render
    report = _json.loads(Path(args["provenance_path"]).read_text(encoding="utf-8"))
    output = Path(args["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(report), encoding="utf-8")
    manifest, manifest_path = find_manifest_for(args["output_path"])
    if manifest:
        update_manifest(manifest_path, artifacts={"provenance_html": args["output_path"]},
                        stages={"provenance_rendered": True}, status="provenance_rendered")
    result = {"provenance_path": args["provenance_path"], "output_path": args["output_path"], "bytes": output.stat().st_size}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "negative_search":
    from core.evidence import NegativeSearchPlan, execute_negative_search
    from core.snapshot import resolve_snapshot
    from pathlib import Path as _P
    target = args["target"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    from core.evidence import assert_clean_worktree
    assert_clean_worktree(snap.repo_path, snap.commit)
    evidence_path = Path(args.get("evidence_store", "")) if args.get("evidence_store") else _P("output") / target / "_audit" / "evidence_store.jsonl"
    from core.evidence import EvidenceStore
    store = EvidenceStore(snap.repo_path, str(evidence_path))
    plan = NegativeSearchPlan(snapshot_commit=snap.commit, subject=args["subject"],
                              queries=args.get("queries", []), symbols=args.get("symbols", []),
                              paths=args.get("paths", []), extensions=args.get("extensions", []))
    result = execute_negative_search(snap.repo_path, plan, store)
    result["evidence_store"] = str(evidence_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "node_taxonomy":
    from core.kernel_tree import (
        ROOT_NODES_V2, ANALYSIS_ORDER_V2, ANALYSIS_BATCHES_V2,
        node_title_zh, node_title_en, node_scope,
    )
    node_id = args.get("node_id", "")
    if node_id:
        result = {"node_id": node_id, "title_zh": node_title_zh(node_id),
                  "title_en": node_title_en(node_id), "scope": node_scope(node_id)}
    else:
        result = {
            "root_nodes": ROOT_NODES_V2,
            "analysis_order": ANALYSIS_ORDER_V2,
            "analysis_batches": ANALYSIS_BATCHES_V2,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "claim_contract":
    from core.judge_report import claim_contract as contract
    result = contract()
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "node_review_draft_batch":
    from core.judge_report import node_review_draft_batch as draft
    result = draft(args["report_path"], args["node_ids"], mode=args.get("mode", "candidate_absent"))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_relationship_hints":
    from core.comparison_db import relationship_hints, resolve_database
    hint_type = args.get("hint_type", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    result = relationship_hints(resolve_database(args["run_id"]), hint_type, offset, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_add_secondary_source":
    from core.comparison import build_match_edges
    from core.comparison_db import add_secondary_source, resolve_database, run_metadata
    from core.scope import filter_units, load_scope_manifest
    from core.snapshot import resolve_snapshot
    from scripts.fingerprint import build_units
    database = resolve_database(args["run_id"])
    meta = run_metadata(database)
    target = resolve_snapshot(meta["target_snapshot"]["repo_path"], meta["target_snapshot"]["commit"])
    src_path = f"repos/{args['source']}" if "/" not in args["source"] else args["source"]
    secondary = resolve_snapshot(src_path, args.get("ref", "HEAD"))
    target_scope = load_scope_manifest(target.repo, target.commit)
    secondary_scope = load_scope_manifest(secondary.repo, secondary.commit)
    if target_scope is None or secondary_scope is None or secondary_scope.status != "verified":
        raise ValueError("target and secondary source require verified ScopeManifest records")
    target_units = filter_units(build_units(target.repo_path, snapshot=target), target_scope)
    source_units = filter_units(build_units(secondary.repo_path, snapshot=secondary), secondary_scope)
    extra_filter = args.get("extra_filter_prefixes")
    if extra_filter:
        source_units = [x for x in source_units if any(str(x.get("file") or "").startswith(p) for p in extra_filter)]
    edges = build_match_edges(target_units, source_units, source_role="secondary_source", source_repo=secondary.repo)
    result = add_secondary_source(database, secondary.to_dict(), source_units, edges)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "evidence_formal_search":
    from core.evidence import EvidenceCandidate
    from core.scope import load_scope_manifest
    from core.snapshot import resolve_snapshot
    from core.evidence import EvidenceStore, assert_clean_worktree
    target = args["target"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    scope = load_scope_manifest(snap.repo, snap.commit)
    if scope is None or scope.status != "verified":
        raise ValueError("target requires a verified ScopeManifest")
    candidate = args["candidate"]
    metadata = {"target_scope_id": scope.scope_id,
                "candidate_scope_id": candidate.get("candidate_scope_id") or candidate.get("scope_id"),
                "candidate_commit": candidate.get("commit"), "candidate_repo": candidate.get("repo"),
                "score_kind": candidate.get("score_kind"), "rank": candidate.get("rank"),
                "combined": candidate.get("combined")}
    store = EvidenceStore(snap.repo_path, args["evidence_store"])
    assert_clean_worktree(snap.repo_path, snap.commit)
    evidence_id = store.add(EvidenceCandidate(tool="formal_search", kind="formal_search",
                                              label=args.get("label", "") or f"formal rank {candidate.get('rank')}",
                                              strength="strong", metadata=metadata))
    result = {"evidence_id": evidence_id, "record": store.by_id(evidence_id).compact(),
              "evidence_store": args["evidence_store"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "evidence_document":
    from core.evidence import EvidenceCandidate
    from core.snapshot import resolve_snapshot
    from core.evidence import EvidenceStore, assert_clean_worktree
    target = args["target"]
    ref = args.get("ref", "HEAD")
    path = f"repos/{target}" if "/" not in target else target
    snap = resolve_snapshot(path, ref)
    store = EvidenceStore(snap.repo_path, args["evidence_store"])
    assert_clean_worktree(snap.repo_path, snap.commit)
    metadata = {"snapshot_commit": snap.commit, "start_page": args.get("start_page") or None,
                "end_page": args.get("end_page") or None}
    candidate = EvidenceCandidate(tool="documentation", kind="documentation", path=args["path"],
                                  line_start=args.get("start_line") or None, line_end=args.get("end_line") or None,
                                  label=args.get("label", ""), strength=args.get("strength", "medium"),
                                  metadata=metadata)
    evidence_id = store.add(candidate)
    record = store.by_id(evidence_id)
    result = {"evidence_id": evidence_id, "record": record.compact(), "verified": record.verified,
              "excerpt": record.excerpt, "evidence_store": args["evidence_store"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "comparison_representatives":
    from core.comparison_db import representatives, resolve_database
    scope_type = args.get("scope_type", "global")
    scope_value = args.get("scope_value", "")
    limit = args.get("limit", 10)
    result = representatives(resolve_database(args["run_id"]), scope_type, scope_value, limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "comparison_source_group":
    from core.comparison_db import resolve_database, source_group
    result = source_group(resolve_database(args["run_id"]), args["comparison_id_or_hint_id"])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "compile_flags":
    from scripts.compile_flags import generate, _detect_arch
    repo = _lsp_snapshot_path(args["target"], args.get("ref", "HEAD"))
    content = generate(repo)
    result = {"target": args["target"], "ref": args.get("ref", "HEAD"), "snapshot_path": repo,
              "arch": _detect_arch(Path(repo)), "flags": content.splitlines()}
    print(json.dumps(result, ensure_ascii=False, indent=2))

elif tool_name == "read_doc":
    from tools.file_ops import read_code_segment
    target = args["target"]
    path_arg = args["path"]
    full_path = f"repos/{target}/{path_arg}" if "/" not in target else f"{target}/{path_arg}"
    result = read_code_segment(full_path, start_page=args.get("start_page", 1), end_page=args.get("end_page") or None)
    print(json.dumps({"content": result}, ensure_ascii=False, indent=2))

elif tool_name == "search_similar":
    from core.scope import ScopeExclusion, build_scope_manifest
    from core.scoped_search import cached_candidate_snapshots, search_scoped
    from core.snapshot import resolve_snapshot
    target = args["target"]
    exclude_prefixes = args.get("exclude_prefixes")
    top_k = args.get("top_k", 10)
    ref = args.get("ref", "") or args.get("branch", "") or "HEAD"
    path = f"repos/{target}" if "/" not in target else target
    mm = __import__('core.metadata', fromlist=['MetadataManager']).MetadataManager()
    snap = resolve_snapshot(path, ref)
    excluded = [ScopeExclusion(p, "agent_excluded", "rough recall exclude_prefixes") for p in (exclude_prefixes or [])]
    target_scope = build_scope_manifest(snap, excluded=excluded, status="draft")
    results = search_scoped(snap, target_scope, cached_candidate_snapshots(), top_k=top_k,
                            metadata=mm, formal_only=False)
    for row in results:
        row["score_kind"] = "rough"
    result = {"target": target, "ref": ref or "(default)", "score_kind": "rough",
              "result_count": len(results), "results": results}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

elif tool_name == "judge_report_fork_for_comparison":
    from core.judge_report import fork_judge_report_for_comparison, write_judge_report
    output_path = args["output_path"]
    output = Path(output_path)
    if output.is_file() and not args.get("overwrite", False):
        raise ValueError("output_path already exists; pass overwrite=true or choose a new audit directory")
    report = fork_judge_report_for_comparison(args["old_report_path"],
                                              comparison_database=args["comparison_run_id"],
                                              evidence_store=args["evidence_store"],
                                              work_display_name=args.get("work_display_name", ""),
                                              reference_display_name=args.get("reference_display_name", ""))
    write_judge_report(report, output_path)
    result = {"path": output_path, "comparison_run_id": report["comparison_run_id"],
              "report_generation": report["report_generation"],
              "migration": report.get("migration"),
              "claims_requiring_rebind": sum(1 for x in report.get("claims") or [] if x.get("migration_status") == "needs_rebind")}
    print(json.dumps(result, ensure_ascii=False, indent=2))

else:
    print(f"Unknown tool: {tool_name}", file=sys.stderr)
    sys.exit(1)
