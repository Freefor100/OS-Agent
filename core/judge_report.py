from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.comparison_db import directory_summary, reference_sets, representatives, resolve_database, run_metadata, search_units
from core.evidence import stable_id
from core.kernel_tree import (
    ANALYSIS_BATCHES_V2,
    ANALYSIS_ORDER_V2,
    EXTRA_NODE_SPECS,
    ROOT_NODES_V2,
    node_scope,
    node_title_en,
    node_title_zh,
)

JUDGE_REPORT_SCHEMA = "judge_report_v1"
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
CLAIM_TYPES = {"lineage", "difference", "independent_work", "implementation", "absence", "risk"}
VERDICTS = {
    "inherited", "inherited_modified", "independently_added", "implemented", "partial",
    "absent", "not_applicable", "uncertain",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
IMPLEMENTATION_LEVELS = {"complete", "partial", "minimal", "absent", "not_applicable", "unknown"}
ORIGINALITY_LEVELS = {"independent", "substantial_rework", "incremental", "inherited", "not_applicable", "unknown"}
MODULE_IDS = [module_id for module_id in ROOT_NODES_V2 if module_id != "Metadata"]
CLAIM_CONTRACT = {
    "claim_types": sorted(CLAIM_TYPES),
    "verdicts": sorted(VERDICTS),
    "confidence_levels": sorted(CONFIDENCE_LEVELS),
    "implementation_levels": sorted(IMPLEMENTATION_LEVELS),
    "originality_levels": sorted(ORIGINALITY_LEVELS),
    "recommended_pairs": [
        {"claim_type": "lineage", "verdicts": ["inherited", "inherited_modified", "uncertain"], "evidence": "双侧源码证据"},
        {"claim_type": "difference", "verdicts": ["partial", "uncertain"], "evidence": "普通差异可用中文说明和源码定位；继承/新增方向结论需要关键 Evidence"},
        {"claim_type": "independent_work", "verdicts": ["independently_added"], "evidence": "目标源码证据、formal_search、完整 negative_search"},
        {"claim_type": "implementation", "verdicts": ["implemented", "partial", "not_applicable", "uncertain"], "evidence": "普通实现说明可无 evidence；写清中文代码事实和功能抽象"},
        {"claim_type": "absence", "verdicts": ["absent", "not_applicable"], "evidence": "完整 negative_search 或架构不适用证据"},
        {"claim_type": "risk", "verdicts": ["uncertain", "partial"], "evidence": "普通风险可无 evidence；关键风险再锚定源码、文档或审计证据"},
    ],
}
_REPORT_LOCKS: dict[str, threading.RLock] = {}
_REPORT_LOCKS_GUARD = threading.Lock()


def create_judge_report(*, comparison_database: str, evidence_store: str, work_display_name: str = "",
                        reference_display_name: str = "") -> dict[str, Any]:
    database = resolve_database(comparison_database)
    meta = run_metadata(database)
    target = meta["target_snapshot"]
    reference = meta["base_snapshot"]
    work_name = work_display_name or _display_name(str(target.get("repo") or "作品"))
    reference_name = reference_display_name or _display_name(str(reference.get("repo") or "参考作品"))
    return {
        "schema_version": JUDGE_REPORT_SCHEMA,
        "report_generation": stable_id("gen", {"run": meta["run_id"], "evidence_store": evidence_store}, 12),
        "comparison_run_id": meta["run_id"],
        "comparison_database": database,
        "evidence_store": evidence_store,
        "work": {"display_name": work_name, "snapshot": target},
        "reference": {"display_name": reference_name, "snapshot": reference},
        "taxonomy": {
            "roots": list(ROOT_NODES_V2),
            "modules": MODULE_IDS,
            "nodes": ANALYSIS_ORDER_V2,
            "analysis_batches": ANALYSIS_BATCHES_V2,
        },
        "claims": [],
        "node_reviews": [],
        "module_reviews": [],
        "overall_assessment": {},
        "report_highlights": {"expanded_module_ids": [], "featured_claim_ids": []},
        "provenance_href": "provenance.html",
    }


def fork_judge_report_for_comparison(old_report_path: str, *, comparison_database: str, evidence_store: str,
                                     work_display_name: str = "", reference_display_name: str = "") -> dict[str, Any]:
    """Create a new draft report from an old one after the Base/Comparison changes.

    Human-written node/module/overall text is preserved, but claims are marked
    needs_rebind so they cannot render until the Agent revalidates evidence and
    comparison ids against the new database.
    """
    old = _load(old_report_path)
    report = create_judge_report(
        comparison_database=comparison_database,
        evidence_store=evidence_store,
        work_display_name=work_display_name or ((old.get("work") or {}).get("display_name") or ""),
        reference_display_name=reference_display_name,
    )
    old_evidence = _evidence_records(str(old.get("evidence_store") or ""))
    new_target_commit = (report.get("work") or {}).get("snapshot", {}).get("commit")
    migrated_claims = []
    for claim in _as_dict_rows(old.get("claims"), "claims", []):
        row = dict(claim)
        row["migration_status"] = "needs_rebind"
        row["comparison_ids"] = []
        kept_evidence = []
        removed_evidence = []
        for evidence_id in row.get("evidence_ids") or []:
            record = old_evidence.get(evidence_id)
            if record and (record.get("metadata") or {}).get("snapshot_commit") == new_target_commit and record.get("kind") != "formal_search":
                kept_evidence.append(evidence_id)
            else:
                removed_evidence.append(evidence_id)
        row["evidence_ids"] = kept_evidence
        row["migration_notes"] = {
            "from_report_generation": old.get("report_generation"),
            "removed_evidence_ids": removed_evidence,
            "reason": "Base/Comparison changed; reference-side and formal-search evidence must be rebound",
        }
        migrated_claims.append(row)
    report["claims"] = migrated_claims
    report["node_reviews"] = [dict(x) for x in _as_dict_rows(old.get("node_reviews"), "node_reviews", [])]
    report["module_reviews"] = [dict(x) for x in _as_dict_rows(old.get("module_reviews"), "module_reviews", [])]
    report["overall_assessment"] = dict(old.get("overall_assessment")) if isinstance(old.get("overall_assessment"), dict) else {}
    report["report_highlights"] = dict(old.get("report_highlights")) if isinstance(old.get("report_highlights"), dict) else {"expanded_module_ids": [], "featured_claim_ids": []}
    report["migration"] = {
        "kind": "comparison_fork",
        "source_report": old_report_path,
        "source_generation": old.get("report_generation"),
        "status": "needs_rebind",
    }
    return report


def write_judge_report(report: dict[str, Any], path: str, *, require_complete: bool = False) -> str:
    errors = validate_judge_report(report, require_complete=require_complete)
    if errors:
        raise ValueError("invalid judge report: " + "; ".join(errors))
    with _file_lock(path):
        _atomic_write(Path(path), report)
    return path


def claim_submit(report_path: str, claim: dict[str, Any], expected_generation: str = "") -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        _assert_generation(report, expected_generation)
        row = _prepare_claim(report, claim)
        report["claims"] = [x for x in report["claims"] if x.get("claim_id") != row["claim_id"]] + [row]
        _validate_write(report_path, report)
        return row


def claim_list(report_path: str, node_id: str = "") -> dict[str, Any]:
    rows = _load(report_path).get("claims") or []
    if node_id:
        rows = [x for x in rows if x.get("node_id") == node_id]
    return {"total": len(rows), "rows": rows}


def node_review_submit(report_path: str, review: dict[str, Any], expected_generation: str = "") -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        _assert_generation(report, expected_generation)
        node_id = str(review.get("node_id") or "")
        report["node_reviews"] = [x for x in report["node_reviews"] if x.get("node_id") != node_id] + [dict(review)]
        _validate_write(report_path, report)
        return dict(review)


def node_review_bundle_submit(report_path: str, node_id: str, claims: list[dict[str, Any]], review: dict[str, Any],
                              expected_generation: str = "") -> dict[str, Any]:
    """Atomically replace one node's Claims and NodeReview with one worker result."""
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        _assert_generation(report, expected_generation)
        prepared = [_prepare_claim(report, {**claim, "node_id": node_id}) for claim in claims]
        report["claims"] = [x for x in report["claims"] if x.get("node_id") != node_id] + prepared
        row = _bind_review_claims({**review, "node_id": node_id}, [x["claim_id"] for x in prepared])
        report["node_reviews"] = [x for x in report["node_reviews"] if x.get("node_id") != node_id] + [row]
        _validate_write(report_path, report)
        return {"node_id": node_id, "claims": prepared, "review": row}


def module_review_submit(report_path: str, review: dict[str, Any], expected_generation: str = "") -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        _assert_generation(report, expected_generation)
        module_id = str(review.get("module_id") or "")
        report["module_reviews"] = [x for x in report["module_reviews"] if x.get("module_id") != module_id] + [dict(review)]
        _validate_write(report_path, report)
        return dict(review)


def overall_assessment_submit(report_path: str, assessment: dict[str, Any], expected_generation: str = "") -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        _assert_generation(report, expected_generation)
        report["overall_assessment"] = dict(assessment)
        _validate_write(report_path, report)
        return dict(assessment)


def report_highlights_submit(report_path: str, highlights: dict[str, Any], expected_generation: str = "") -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        _assert_generation(report, expected_generation)
        report["report_highlights"] = {
            "expanded_module_ids": sorted(set(highlights.get("expanded_module_ids") or [])),
            "featured_claim_ids": sorted(set(highlights.get("featured_claim_ids") or [])),
        }
        _validate_write(report_path, report)
        return report["report_highlights"]


def judge_report_status(report_path: str) -> dict[str, Any]:
    from core.audit_manifest import artifact_status, find_manifest_for
    report = _load(report_path)
    errors = validate_judge_report(report, require_complete=True)
    node_review_rows = [x for x in (report.get("node_reviews") or []) if isinstance(x, dict)]
    claim_rows = [x for x in (report.get("claims") or []) if isinstance(x, dict)]
    module_rows = [x for x in (report.get("module_reviews") or []) if isinstance(x, dict)]
    node_ids = {x.get("node_id") for x in node_review_rows}
    claimed_nodes = {x.get("node_id") for x in claim_rows}
    modules = {x.get("module_id") for x in module_rows}
    key_chains = sum(len(x.get("key_chains") or []) for x in module_rows if isinstance(x.get("key_chains") or [], list))
    missing_by_batch = []
    for index, batch in enumerate(ANALYSIS_BATCHES_V2, 1):
        missing = [node_id for node_id in batch if node_id not in node_ids or node_id not in claimed_nodes]
        if missing:
            missing_by_batch.append({"batch": index, "missing_nodes": missing})
    manifest, _ = find_manifest_for(report_path)
    artifacts = artifact_status(manifest, str(Path(report_path).parent))
    assessment = report.get("overall_assessment") if isinstance(report.get("overall_assessment"), dict) else {}
    missing_modules = [module_id for module_id in MODULE_IDS if module_id not in modules]
    missing_nodes = [node_id for node_id in ANALYSIS_ORDER_V2 if node_id not in node_ids]
    missing_claim_nodes = [node_id for node_id in ANALYSIS_ORDER_V2 if node_id not in claimed_nodes]
    missing_overall = [
        field for field in ("summary", "source_relation", "base_selection_reason", "scope_exclusion_process", "main_inherited", "main_modified", "main_independent", "incomplete_or_risks", "review_focus", "directory_overview")
        if not assessment.get(field)
    ]
    missing_architecture_description = not (
        _text_present(assessment.get("architecture_overview")) or _text_present(assessment.get("architecture_diagram"))
    )
    missing_key_evidence = [error for error in errors if "requires verified evidence" in error or "requires key evidence" in error or "requires complete negative search evidence" in error or "requires work source" in error or "requires bilateral source evidence" in error]
    return {
        "valid": not errors,
        "errors": errors,
        "report_generation": report.get("report_generation"),
        "claims": len(report.get("claims") or []),
        "node_reviews": len(node_ids),
        "node_reviews_required": len(ANALYSIS_ORDER_V2),
        "nodes_with_claims": len(claimed_nodes & set(ANALYSIS_ORDER_V2)),
        "module_reviews": len(modules),
        "module_reviews_required": len(MODULE_IDS),
        "module_key_chains": key_chains,
        "architecture_edges": len(assessment.get("architecture_edges") or []),
        "missing_by_batch": missing_by_batch,
        "missing_summary": {
            "modules": missing_modules,
            "node_reviews": missing_nodes,
            "nodes_with_claims": missing_claim_nodes,
            "overall_fields": missing_overall,
            "architecture_description": missing_architecture_description,
            "key_evidence_errors": missing_key_evidence,
        },
        "audit_manifest": manifest,
        "artifact_status": artifacts,
        "product_ready": not errors and not artifacts["missing_artifacts"],
    }


def node_analysis_packet(report_path: str, node_id: str) -> dict[str, Any]:
    if node_id not in ANALYSIS_ORDER_V2:
        raise ValueError(f"unknown analysis node: {node_id}")
    report = _load(report_path)
    database = resolve_database(report["comparison_database"])
    spec = EXTRA_NODE_SPECS.get(node_id, {})
    batch_index = next(index for index, batch in enumerate(ANALYSIS_BATCHES_V2, 1) if node_id in batch)
    located_work: dict[str, dict[str, Any]] = {}
    located_reference: dict[str, dict[str, Any]] = {}
    for query in (spec.get("symbols") or [])[:12]:
        for row in search_units(database, query=query, side="target", limit=10)["rows"]:
            located_work[row["unit_id"]] = row
        for row in search_units(database, query=query, side="primary_base", limit=10)["rows"]:
            located_reference[row["unit_id"]] = row
    located_comparison_ids = sorted({row.get("comparison_id") for row in [*located_work.values(), *located_reference.values()] if row.get("comparison_id")})
    located_files = sorted({row.get("file") for row in located_work.values() if row.get("file")})
    return {
        "node": {
            "node_id": node_id,
            "module_id": _module_id(node_id),
            "title_zh": node_title_zh(node_id),
            "title_en": node_title_en(node_id),
            "scope": node_scope(node_id),
        },
        "navigation_hints": {
            "warning": "这些词与符号仅用于定位，不能独立支撑 Claim。",
            "possible_entry_symbols": spec.get("symbols") or [],
            "possible_terms": spec.get("patterns") or [],
        },
        "report_generation": report.get("report_generation"),
        "comparison_summary": directory_summary(database, "", "target"),
        "comparison_representatives": representatives(database, "global", "", 12),
        "located_work_units": list(located_work.values())[:50],
        "located_reference_units": list(located_reference.values())[:50],
        "located_comparison_ids": located_comparison_ids[:100],
        "located_work_files": located_files[:30],
        "batch": {"index": batch_index, "nodes": ANALYSIS_BATCHES_V2[batch_index - 1]},
        "existing_claims": [x for x in report.get("claims") or [] if isinstance(x, dict) and x.get("node_id") == node_id],
        "existing_review": next((x for x in report.get("node_reviews") or [] if isinstance(x, dict) and x.get("node_id") == node_id), None),
    }


def module_analysis_packet(report_path: str, module_id: str) -> dict[str, Any]:
    if module_id not in MODULE_IDS:
        raise ValueError(f"unknown module: {module_id}")
    report = _load(report_path)
    database = resolve_database(report["comparison_database"])
    children = ROOT_NODES_V2[module_id]
    node_ids = [module_id] if not children else [f"{module_id}.{child}" for child in children]
    nodes = []
    located_work: dict[str, dict[str, Any]] = {}
    located_reference: dict[str, dict[str, Any]] = {}
    for node_id in node_ids:
        spec = EXTRA_NODE_SPECS.get(node_id, {})
        for query in (spec.get("symbols") or [])[:8]:
            for row in search_units(database, query=query, side="target", limit=8)["rows"]:
                located_work[row["unit_id"]] = row
            for row in search_units(database, query=query, side="primary_base", limit=8)["rows"]:
                located_reference[row["unit_id"]] = row
        nodes.append({
            "node_id": node_id,
            "title_zh": node_title_zh(node_id),
            "title_en": node_title_en(node_id),
            "scope": node_scope(node_id),
            "existing_claims": [x for x in report.get("claims") or [] if isinstance(x, dict) and x.get("node_id") == node_id],
            "existing_review": next((x for x in report.get("node_reviews") or [] if isinstance(x, dict) and x.get("node_id") == node_id), None),
        })
    return {
        "module": {
            "module_id": module_id,
            "title_zh": node_title_zh(module_id),
            "title_en": node_title_en(module_id),
            "scope": node_scope(module_id),
        },
        "report_generation": report.get("report_generation"),
        "workflow_note": "按模块形成中文抽象描述；节点 scope 是功能边界，不是证据。",
        "nodes": nodes,
        "comparison_summary": directory_summary(database, "", "target"),
        "comparison_representatives": representatives(database, "global", "", 20),
        "located_work_units": list(located_work.values())[:120],
        "located_reference_units": list(located_reference.values())[:120],
        "located_comparison_ids": sorted({row.get("comparison_id") for row in [*located_work.values(), *located_reference.values()] if row.get("comparison_id")})[:200],
        "located_work_files": sorted({row.get("file") for row in located_work.values() if row.get("file")})[:80],
        "existing_module_review": next((x for x in report.get("module_reviews") or [] if isinstance(x, dict) and x.get("module_id") == module_id), None),
    }


def claim_contract() -> dict[str, Any]:
    return dict(CLAIM_CONTRACT)


def node_review_draft_batch(report_path: str, node_ids: list[str], mode: str = "candidate_absent") -> dict[str, Any]:
    if mode not in {"candidate_absent", "candidate_inherited"}:
        raise ValueError("mode must be candidate_absent or candidate_inherited")
    report = _load(report_path)
    database = resolve_database(report["comparison_database"])
    rows = []
    for node_id in node_ids:
        if node_id not in ANALYSIS_ORDER_V2:
            raise ValueError(f"unknown analysis node: {node_id}")
        summary = directory_summary(database, "", "target")
        if mode == "candidate_absent":
            claim = {
                "node_id": node_id,
                "claim_type": "absence",
                "verdict": "absent",
                "statement": f"候选草稿：{node_title_zh(node_id)} 未在当前 comparison 摘要中显示明确实现，需要 Agent 用负向搜索和源码复核确认。",
                "comparison_ids": [],
                "evidence_ids": [],
                "confidence": "low",
                "draft": True,
            }
            review = {
                "node_id": node_id,
                "overview": f"候选草稿：暂未确认 {node_title_zh(node_id)} 的有效实现。",
                "difference_from_reference": "候选草稿：需复核参考作品与目标作品对应源码后填写。",
                "implementation_degree": {"level": "unknown", "rationale": "草稿未绑定 verified evidence，不能作为正式结论。", "claim_ids": []},
                "originality": {"level": "unknown", "rationale": "草稿未绑定 verified evidence，不能作为正式结论。", "claim_ids": []},
                "claim_ids": [],
                "risks": ["草稿需要 Agent 审核、补充 evidence 后才能提交。"],
            }
        else:
            claim = {
                "node_id": node_id,
                "claim_type": "lineage",
                "verdict": "inherited",
                "statement": f"候选草稿：{node_title_zh(node_id)} 可能主体继承参考实现，需要 Agent 用双侧源码证据确认。",
                "comparison_ids": [],
                "evidence_ids": [],
                "confidence": "low",
                "draft": True,
            }
            review = {
                "node_id": node_id,
                "overview": f"候选草稿：{node_title_zh(node_id)} 可能与参考作品高度一致。",
                "difference_from_reference": "候选草稿：需绑定 comparison 与双侧源码 evidence 后才能形成正式差异结论。",
                "implementation_degree": {"level": "unknown", "rationale": "草稿未绑定 verified evidence，不能作为正式结论。", "claim_ids": []},
                "originality": {"level": "unknown", "rationale": "草稿未绑定 verified evidence，不能作为正式结论。", "claim_ids": []},
                "claim_ids": [],
                "risks": ["草稿需要 Agent 审核、补充 evidence 后才能提交。"],
            }
        rows.append({"node_id": node_id, "mode": mode, "comparison_summary": summary, "claim_draft": claim, "review_draft": review})
    return {"report_generation": report.get("report_generation"), "writes_report": False, "rows": rows}


def validate_judge_report(report: dict[str, Any], *, require_complete: bool = True) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != JUDGE_REPORT_SCHEMA:
        errors.append(f"schema_version must be {JUDGE_REPORT_SCHEMA}")
    try:
        database = resolve_database(str(report.get("comparison_database") or report.get("comparison_run_id") or ""))
        meta = run_metadata(database)
    except (ValueError, OSError) as exc:
        return errors + [str(exc)]
    if report.get("comparison_run_id") != meta["run_id"]:
        errors.append("comparison_run_id does not match database")
    refs = reference_sets(database)
    evidence = _evidence_records(str(report.get("evidence_store") or ""))
    claims: dict[str, dict[str, Any]] = {}
    standard_nodes = set(ANALYSIS_ORDER_V2)

    for claim in _as_dict_rows(report.get("claims"), "claims", errors):
        claim_id = str(claim.get("claim_id") or "")
        node_id = str(claim.get("node_id") or "")
        if not claim_id:
            errors.append("claim without claim_id")
        elif claim_id in claims:
            errors.append(f"duplicate claim_id {claim_id}")
        claims[claim_id] = claim
        if node_id not in standard_nodes:
            errors.append(f"claim {claim_id} references unknown node {node_id}")
        if require_complete and claim.get("migration_status") == "needs_rebind":
            errors.append(f"claim {claim_id} requires evidence/comparison rebind after report fork")
        if claim.get("claim_type") not in CLAIM_TYPES:
            errors.append(f"claim {claim_id} has invalid claim_type {claim.get('claim_type')!r}; allowed={sorted(CLAIM_TYPES)}")
        if claim.get("verdict") not in VERDICTS:
            errors.append(f"claim {claim_id} has invalid verdict {claim.get('verdict')!r}; allowed={sorted(VERDICTS)}")
        if claim.get("confidence") not in CONFIDENCE_LEVELS:
            errors.append(f"claim {claim_id} has invalid confidence {claim.get('confidence')!r}; allowed={sorted(CONFIDENCE_LEVELS)}")
        if not str(claim.get("statement") or "").strip():
            errors.append(f"claim {claim_id} requires statement")
        elif require_complete and not _contains_cjk(claim.get("statement")):
            errors.append(f"claim {claim_id} statement must be Chinese")
        comparison_ids = _as_list(claim.get("comparison_ids"), f"claim {claim_id} comparison_ids", errors)
        for comparison_id in comparison_ids:
            if comparison_id not in refs["comparison_ids"]:
                errors.append(f"claim {claim_id} references missing comparison {comparison_id}")
        evidence_ids = _as_list(claim.get("evidence_ids"), f"claim {claim_id} evidence_ids", errors)
        if claim.get("migration_status") == "needs_rebind" and not require_complete:
            continue
        requires_evidence = _claim_requires_evidence(claim)
        if requires_evidence and not evidence_ids:
            errors.append(f"claim {claim_id} requires verified evidence")
        records = []
        for evidence_id in evidence_ids:
            record = evidence.get(evidence_id)
            if not record:
                errors.append(f"claim {claim_id} references missing evidence {evidence_id}")
            elif not record.get("verified"):
                errors.append(f"claim {claim_id} references unverified evidence {evidence_id}")
            else:
                records.append(record)
        if requires_evidence or records:
            _validate_claim_evidence(claim_id, claim, records, meta, errors)

    node_reviews: dict[str, dict[str, Any]] = {}
    for review in _as_dict_rows(report.get("node_reviews"), "node_reviews", errors):
        node_id = str(review.get("node_id") or "")
        if node_id not in standard_nodes:
            errors.append(f"node review references unknown node {node_id}")
        if node_id in node_reviews:
            errors.append(f"duplicate node review for {node_id}")
        node_reviews[node_id] = review
        if not _text_present(review.get("overview")):
            errors.append(f"node review {node_id} requires overview")
        elif require_complete and not _contains_cjk(review.get("overview")):
            errors.append(f"node review {node_id} overview must be Chinese")
        if not _text_present(review.get("difference_from_reference")):
            errors.append(f"node review {node_id} requires difference_from_reference")
        elif require_complete and not _contains_cjk(review.get("difference_from_reference")):
            errors.append(f"node review {node_id} difference_from_reference must be Chinese")
        _validate_degree(node_id, "implementation_degree", review.get("implementation_degree"), IMPLEMENTATION_LEVELS, claims, errors)
        _validate_degree(node_id, "originality", review.get("originality"), ORIGINALITY_LEVELS, claims, errors)
        for claim_id in _as_list(review.get("claim_ids"), f"node review {node_id} claim_ids", errors):
            if claim_id not in claims:
                errors.append(f"node review {node_id} references missing claim {claim_id}")
            elif claims[claim_id].get("node_id") != node_id:
                errors.append(f"node review {node_id} references claim from another node {claim_id}")
        for ref in _as_dict_rows(review.get("provenance_refs"), f"node review {node_id} provenance_refs", errors):
            if ref.get("target_file") and ref["target_file"] not in refs["target_files"]:
                errors.append(f"node review {node_id} references missing provenance file {ref['target_file']}")

    modules: dict[str, dict[str, Any]] = {}
    for review in _as_dict_rows(report.get("module_reviews"), "module_reviews", errors):
        module_id = str(review.get("module_id") or "")
        if module_id not in MODULE_IDS:
            errors.append(f"module review references unknown module {module_id}")
        if module_id in modules:
            errors.append(f"duplicate module review for {module_id}")
        modules[module_id] = review
        for field in ("overview", "difference_summary", "original_work_summary", "implementation_summary"):
            if not _text_present(review.get(field)):
                errors.append(f"module review {module_id} requires {field}")
            elif require_complete and not _contains_cjk(review.get(field)):
                errors.append(f"module review {module_id} {field} must be Chinese")
        for claim_id in _as_list(review.get("featured_claim_ids"), f"module review {module_id} featured_claim_ids", errors):
            if claim_id not in claims:
                errors.append(f"module review {module_id} references missing claim {claim_id}")
            elif require_complete and not _claim_has_verified_evidence(claims[claim_id], evidence):
                errors.append(f"module review {module_id} featured claim {claim_id} requires key evidence")
        chains = _as_dict_rows(review.get("key_chains"), f"module review {module_id} key_chains", errors)
        if require_complete and not chains:
            errors.append(f"module review {module_id} requires key_chains")
        for chain in chains:
            if not str(chain.get("title") or "").strip() or not str(chain.get("explanation") or "").strip():
                errors.append(f"module review {module_id} key chain requires title and explanation")
            node_refs = _as_list(chain.get("node_ids"), f"module review {module_id} key chain node_ids", errors)
            claim_refs = _as_list(chain.get("claim_ids"), f"module review {module_id} key chain claim_ids", errors)
            evidence_refs = _as_list(chain.get("evidence_ids"), f"module review {module_id} key chain evidence_ids", errors)
            if not node_refs or not claim_refs or not evidence_refs:
                errors.append(f"module review {module_id} key chain requires node_ids, claim_ids, and evidence_ids")
            for node_id in node_refs:
                if node_id not in standard_nodes:
                    errors.append(f"module review {module_id} key chain references unknown node {node_id}")
            for claim_id in claim_refs:
                if claim_id not in claims:
                    errors.append(f"module review {module_id} key chain references missing claim {claim_id}")
            for evidence_id in evidence_refs:
                if evidence_id not in evidence or not evidence[evidence_id].get("verified"):
                    errors.append(f"module review {module_id} key chain references missing or unverified evidence {evidence_id}")

    highlights = report.get("report_highlights") if isinstance(report.get("report_highlights"), dict) else {}
    if report.get("report_highlights") and not isinstance(report.get("report_highlights"), dict):
        errors.append("report_highlights must be object")
    for module_id in _as_list(highlights.get("expanded_module_ids"), "report_highlights expanded_module_ids", errors):
        if module_id not in MODULE_IDS:
            errors.append(f"highlight references unknown module {module_id}")
    for claim_id in _as_list(highlights.get("featured_claim_ids"), "report_highlights featured_claim_ids", errors):
        if claim_id not in claims:
            errors.append(f"highlight references missing claim {claim_id}")

    if require_complete:
        for node_id in ANALYSIS_ORDER_V2:
            if node_id not in node_reviews:
                errors.append(f"missing node review {node_id}")
            if not any(x.get("node_id") == node_id for x in claims.values()):
                errors.append(f"node {node_id} requires at least one claim")
        for module_id in MODULE_IDS:
            if module_id not in modules:
                errors.append(f"missing module review {module_id}")
        assessment = report.get("overall_assessment") if isinstance(report.get("overall_assessment"), dict) else {}
        if report.get("overall_assessment") and not isinstance(report.get("overall_assessment"), dict):
            errors.append("overall_assessment must be object")
        for field in ("summary", "source_relation", "base_selection_reason", "scope_exclusion_process", "main_inherited", "main_modified", "main_independent", "incomplete_or_risks", "review_focus", "directory_overview"):
            value = assessment.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                errors.append(f"overall assessment requires {field}")
            elif isinstance(value, str) and not _contains_cjk(value):
                errors.append(f"overall assessment {field} must be Chinese")
            elif isinstance(value, list) and not any(_contains_cjk(x) for x in value):
                errors.append(f"overall assessment {field} must be Chinese")
        architecture_value = assessment.get("architecture_overview") or assessment.get("architecture_diagram")
        if not _text_present(architecture_value):
            errors.append("overall assessment requires architecture_overview or architecture_diagram")
        elif not _contains_cjk(architecture_value):
            errors.append("overall assessment architecture description must be Chinese")
        diagram = str(assessment.get("architecture_diagram") or "").strip()
        if diagram:
            errors.extend(_validate_mermaid_diagram(diagram))
        edges = _as_dict_rows(assessment.get("architecture_edges"), "overall assessment architecture_edges", errors)
        if not edges:
            errors.append("overall assessment requires architecture_edges")
        for index, edge in enumerate(edges, 1):
            _validate_architecture_edge_refs(index, edge, standard_nodes, errors)
            if not str(edge.get("label") or "").strip():
                errors.append(f"architecture edge {index} requires label")
            elif not _contains_cjk(edge.get("label")):
                errors.append(f"architecture edge {index} label must be Chinese")
            claim_refs = _as_list(edge.get("claim_ids"), f"architecture edge {index} claim_ids", errors)
            if not claim_refs:
                errors.append(f"architecture edge {index} requires claim_ids")
            for claim_id in claim_refs:
                if claim_id not in claims:
                    errors.append(f"architecture edge {index} references missing claim {claim_id}")
                elif not _claim_has_verified_evidence(claims[claim_id], evidence):
                    errors.append(f"architecture edge {index} claim {claim_id} requires key evidence")
    return errors


def _validate_architecture_edge_refs(index: int, edge: dict[str, Any], standard_nodes: set[str], errors: list[str]) -> None:
    """Validate explicit structured refs while allowing free-form diagram endpoints.

    Agent-authored architecture is intentionally not limited to module-to-module
    edges. Generic keys such as source/target/from/to are display labels unless
    the Agent chooses explicit *_module, *_node, module_ids, or node_ids fields.
    """
    module_fields = ("from_module", "to_module", "source_module", "target_module", "module_id")
    node_fields = ("from_node", "to_node", "source_node", "target_node", "node_id")
    for field in module_fields:
        value = edge.get(field)
        if value and value not in MODULE_IDS:
            errors.append(f"architecture edge {index} references unknown module {value!r}; allowed={MODULE_IDS}")
    for value in _as_list(edge.get("module_ids"), f"architecture edge {index} module_ids", errors):
        if value not in MODULE_IDS:
            errors.append(f"architecture edge {index} references unknown module {value!r}; allowed={MODULE_IDS}")
    for field in node_fields:
        value = edge.get(field)
        if value and value not in standard_nodes:
            errors.append(f"architecture edge {index} references unknown node {value!r}")
    for value in _as_list(edge.get("node_ids"), f"architecture edge {index} node_ids", errors):
        if value not in standard_nodes:
            errors.append(f"architecture edge {index} references unknown node {value!r}")


def _validate_mermaid_diagram(value: str) -> list[str]:
    source = _strip_mermaid_fence(value)
    errors: list[str] = []
    if not _looks_like_mermaid(source):
        return ["overall assessment architecture_diagram must be pure Mermaid starting with graph/flowchart/sequenceDiagram/etc.; put prose in architecture_overview"]
    for line_no, line in enumerate(source.splitlines(), 1):
        if _is_mermaid_line(line):
            continue
        errors.append(
            f"overall assessment architecture_diagram line {line_no} is not valid Mermaid syntax: {line.strip()!r}; "
            "put explanatory prose in architecture_overview"
        )
    return errors


def _strip_mermaid_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in {"```mermaid", "```mmd", "```"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _looks_like_mermaid(value: str) -> bool:
    first = value.lstrip().split(None, 1)[0].lower() if value.strip() else ""
    return first in {
        "graph", "flowchart", "sequencediagram", "classdiagram", "statediagram",
        "erdiagram", "gantt", "journey", "gitgraph", "pie", "mindmap", "timeline",
    }


def _is_mermaid_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if lowered.startswith((
        "graph ", "flowchart ", "sequencediagram", "classdiagram", "statediagram",
        "erdiagram", "gantt", "journey", "gitgraph", "pie", "mindmap", "timeline",
        "subgraph ", "end", "%%", "classdef ", "class ", "style ", "linkstyle ",
        "direction ", "accdescr", "acctitle", "title ",
    )):
        return True
    if "-->" in stripped or "---" in stripped or "-.->" in stripped or "==>" in stripped:
        return True
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_]*\s*(\[|\(|\{|>)", stripped))


def _validate_claim_evidence(claim_id: str, claim: dict[str, Any], records: list[dict[str, Any]],
                             meta: dict[str, Any], errors: list[str]) -> None:
    claim_type = claim.get("claim_type")
    verdict = claim.get("verdict")
    target_commit = meta["target_snapshot"].get("commit")
    reference_commit = meta["base_snapshot"].get("commit")
    commits = {_record_metadata(x).get("snapshot_commit") for x in records}
    comparison_claim = claim_type in {"lineage", "difference"} or verdict in {"inherited", "inherited_modified"}
    if comparison_claim and not ({target_commit, reference_commit} <= commits):
        errors.append(f"comparison claim {claim_id} requires bilateral source evidence")
    if claim_type == "independent_work" or verdict == "independently_added":
        kinds = {x.get("kind") for x in records}
        has_complete_negative = any(x.get("kind") == "negative_search" and _record_metadata(x).get("coverage_complete") for x in records)
        if target_commit not in commits or "formal_search" not in kinds or not has_complete_negative:
            errors.append(f"independent claim {claim_id} requires work source, formal search, and complete negative search evidence")
    if claim_type == "absence" or verdict == "absent":
        complete = any(x.get("kind") == "negative_search" and _record_metadata(x).get("coverage_complete") for x in records)
        architecture_evidence = verdict == "not_applicable" and any(x.get("kind") in {"config_entry", "documentation", "source_span"} for x in records)
        if not complete and not architecture_evidence:
            errors.append(f"absence claim {claim_id} requires complete negative search evidence")


def _claim_requires_evidence(claim: dict[str, Any]) -> bool:
    claim_type = claim.get("claim_type")
    verdict = claim.get("verdict")
    return (
        claim_type in {"lineage", "independent_work", "absence"}
        or verdict in {"inherited", "inherited_modified", "independently_added", "absent"}
    )


def _claim_has_verified_evidence(claim: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> bool:
    for evidence_id in claim.get("evidence_ids") or []:
        record = evidence.get(evidence_id)
        if record and record.get("verified"):
            return True
    return False


def _contains_cjk(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_cjk(x) for x in value)
    return bool(_CJK_RE.search(str(value or "")))


def _text_present(value: Any) -> bool:
    if isinstance(value, list):
        return any(_text_present(x) for x in value)
    return bool(str(value or "").strip())


def _validate_degree(node_id: str, label: str, value: Any, allowed: set[str],
                     claims: dict[str, dict[str, Any]], errors: list[str]) -> None:
    row = value if isinstance(value, dict) else {}
    if row.get("level") not in allowed:
        errors.append(f"node review {node_id} has invalid {label} level {row.get('level')!r}; allowed={sorted(allowed)}")
    if not _text_present(row.get("rationale")):
        errors.append(f"node review {node_id} requires {label} rationale")
    claim_ids = _as_list(row.get("claim_ids"), f"node review {node_id} {label} claim_ids", errors)
    if not claim_ids:
        errors.append(f"node review {node_id} requires supporting claims for {label}")
    for claim_id in claim_ids:
        if claim_id not in claims:
            errors.append(f"node review {node_id} {label} references missing claim {claim_id}")
        elif claims[claim_id].get("node_id") != node_id:
            errors.append(f"node review {node_id} {label} references claim from another node {claim_id}")


def _evidence_records(path: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path or not Path(path).is_file():
        return records
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
            records[str(row["evidence_id"])] = row
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return records


def _record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _module_id(node_id: str) -> str:
    return node_id.split(".", 1)[0]


def _display_name(repo: str) -> str:
    name = Path(repo).name
    return name.removeprefix("oskernel2023-") or name


def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _assert_generation(report: dict[str, Any], expected_generation: str = "") -> None:
    if expected_generation and expected_generation != report.get("report_generation"):
        raise ValueError(f"stale report generation: expected {expected_generation}, current {report.get('report_generation')}")


def _bind_review_claims(review: dict[str, Any], prepared_ids: list[str]) -> dict[str, Any]:
    row = dict(review)
    if not prepared_ids:
        return row
    prepared = set(prepared_ids)
    current = _list_without_errors(row.get("claim_ids"))
    if not current or any(claim_id not in prepared for claim_id in current):
        row["claim_ids"] = list(prepared_ids)
    for field in ("implementation_degree", "originality"):
        degree = row.get(field)
        if not isinstance(degree, dict):
            continue
        ids = _list_without_errors(degree.get("claim_ids"))
        if not ids or any(claim_id not in prepared for claim_id in ids):
            degree = dict(degree)
            degree["claim_ids"] = list(prepared_ids)
            row[field] = degree
    return row


def _prepare_claim(report: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    row = dict(claim)
    row["claim_id"] = row.get("claim_id") or stable_id("claim", {
        "run": report["comparison_run_id"],
        "node_id": row.get("node_id"),
        "type": row.get("claim_type"),
        "statement": row.get("statement"),
    }, 16)
    return row


def _as_list(value: Any, label: str, errors: list[str]) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{label} must be list")
        return []
    return value


def _list_without_errors(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict_rows(value: Any, label: str, errors: list[str]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{label} must be list")
        return []
    rows = []
    for index, row in enumerate(value):
        if isinstance(row, dict):
            rows.append(row)
        else:
            errors.append(f"{label}[{index}] must be object")
    return rows


def _report_lock(path: str) -> threading.RLock:
    key = str(Path(path).resolve())
    with _REPORT_LOCKS_GUARD:
        return _REPORT_LOCKS.setdefault(key, threading.RLock())


def _validate_write(path: str, report: dict[str, Any]) -> None:
    errors = validate_judge_report(report, require_complete=False)
    if errors:
        raise ValueError("invalid judge report: " + "; ".join(errors))
    _atomic_write(Path(path), report)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _file_lock(path: str):
    lock_path = Path(path).with_suffix(Path(path).suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        handle.close()
