from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.comparison_db import reference_sets, representatives, resolve_database, run_metadata, search_units
from core.evidence import stable_id
from core.kernel_tree import (
    ANALYSIS_BATCHES_V2,
    ANALYSIS_ORDER_V2,
    EXTRA_NODE_SPECS,
    ROOT_NODES_V2,
    VOCAB_BY_NODE,
    node_scope,
    node_title_en,
    node_title_zh,
)

JUDGE_REPORT_SCHEMA = "judge_report_v1"
CLAIM_TYPES = {"lineage", "difference", "independent_work", "implementation", "absence", "risk"}
VERDICTS = {
    "inherited", "inherited_modified", "independently_added", "implemented", "partial",
    "absent", "not_applicable", "uncertain",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
IMPLEMENTATION_LEVELS = {"complete", "partial", "minimal", "absent", "not_applicable", "unknown"}
ORIGINALITY_LEVELS = {"independent", "substantial_rework", "incremental", "inherited", "not_applicable", "unknown"}
MODULE_IDS = [module_id for module_id in ROOT_NODES_V2 if module_id != "Metadata"]
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


def write_judge_report(report: dict[str, Any], path: str, *, require_complete: bool = False) -> str:
    errors = validate_judge_report(report, require_complete=require_complete)
    if errors:
        raise ValueError("invalid judge report: " + "; ".join(errors))
    with _file_lock(path):
        _atomic_write(Path(path), report)
    return path


def claim_submit(report_path: str, claim: dict[str, Any]) -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        row = _prepare_claim(report, claim)
        report["claims"] = [x for x in report["claims"] if x.get("claim_id") != row["claim_id"]] + [row]
        _validate_write(report_path, report)
        return row


def claim_list(report_path: str, node_id: str = "") -> dict[str, Any]:
    rows = _load(report_path).get("claims") or []
    if node_id:
        rows = [x for x in rows if x.get("node_id") == node_id]
    return {"total": len(rows), "rows": rows}


def node_review_submit(report_path: str, review: dict[str, Any]) -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        node_id = str(review.get("node_id") or "")
        report["node_reviews"] = [x for x in report["node_reviews"] if x.get("node_id") != node_id] + [dict(review)]
        _validate_write(report_path, report)
        return dict(review)


def node_review_bundle_submit(report_path: str, node_id: str, claims: list[dict[str, Any]], review: dict[str, Any]) -> dict[str, Any]:
    """Atomically register all Claims and the NodeReview produced by one analysis worker."""
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        prepared = [_prepare_claim(report, {**claim, "node_id": node_id}) for claim in claims]
        incoming_ids = {x["claim_id"] for x in prepared}
        report["claims"] = [x for x in report["claims"] if x.get("claim_id") not in incoming_ids] + prepared
        row = {**review, "node_id": node_id}
        report["node_reviews"] = [x for x in report["node_reviews"] if x.get("node_id") != node_id] + [row]
        _validate_write(report_path, report)
        return {"node_id": node_id, "claims": prepared, "review": row}


def module_review_submit(report_path: str, review: dict[str, Any]) -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        module_id = str(review.get("module_id") or "")
        report["module_reviews"] = [x for x in report["module_reviews"] if x.get("module_id") != module_id] + [dict(review)]
        _validate_write(report_path, report)
        return dict(review)


def overall_assessment_submit(report_path: str, assessment: dict[str, Any]) -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
        report["overall_assessment"] = dict(assessment)
        _validate_write(report_path, report)
        return dict(assessment)


def report_highlights_submit(report_path: str, highlights: dict[str, Any]) -> dict[str, Any]:
    with _report_lock(report_path), _file_lock(report_path):
        report = _load(report_path)
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
    node_ids = {x.get("node_id") for x in report.get("node_reviews") or []}
    claimed_nodes = {x.get("node_id") for x in report.get("claims") or []}
    modules = {x.get("module_id") for x in report.get("module_reviews") or []}
    key_chains = sum(len(x.get("key_chains") or []) for x in report.get("module_reviews") or [])
    missing_by_batch = []
    for index, batch in enumerate(ANALYSIS_BATCHES_V2, 1):
        missing = [node_id for node_id in batch if node_id not in node_ids or node_id not in claimed_nodes]
        if missing:
            missing_by_batch.append({"batch": index, "missing_nodes": missing})
    manifest, _ = find_manifest_for(report_path)
    artifacts = artifact_status(manifest, str(Path(report_path).parent))
    return {
        "valid": not errors,
        "errors": errors,
        "claims": len(report.get("claims") or []),
        "node_reviews": len(node_ids),
        "node_reviews_required": len(ANALYSIS_ORDER_V2),
        "nodes_with_claims": len(claimed_nodes & set(ANALYSIS_ORDER_V2)),
        "module_reviews": len(modules),
        "module_reviews_required": len(MODULE_IDS),
        "module_key_chains": key_chains,
        "architecture_edges": len((report.get("overall_assessment") or {}).get("architecture_edges") or []),
        "missing_by_batch": missing_by_batch,
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
    vocab = VOCAB_BY_NODE.get(node_id, {})
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
            "vocab": [x.get("tag") for x in vocab.get("mechanisms", []) if x.get("tag")],
        },
        "comparison_representatives": representatives(database, "global", "", 12),
        "located_work_units": list(located_work.values())[:50],
        "located_reference_units": list(located_reference.values())[:50],
        "located_comparison_ids": located_comparison_ids[:100],
        "located_work_files": located_files[:30],
        "batch": {"index": batch_index, "nodes": ANALYSIS_BATCHES_V2[batch_index - 1]},
        "existing_claims": [x for x in report.get("claims") or [] if x.get("node_id") == node_id],
        "existing_review": next((x for x in report.get("node_reviews") or [] if x.get("node_id") == node_id), None),
    }


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

    for claim in report.get("claims") or []:
        claim_id = str(claim.get("claim_id") or "")
        node_id = str(claim.get("node_id") or "")
        if not claim_id:
            errors.append("claim without claim_id")
        elif claim_id in claims:
            errors.append(f"duplicate claim_id {claim_id}")
        claims[claim_id] = claim
        if node_id not in standard_nodes:
            errors.append(f"claim {claim_id} references unknown node {node_id}")
        if claim.get("claim_type") not in CLAIM_TYPES:
            errors.append(f"claim {claim_id} has invalid claim_type")
        if claim.get("verdict") not in VERDICTS:
            errors.append(f"claim {claim_id} has invalid verdict")
        if claim.get("confidence") not in CONFIDENCE_LEVELS:
            errors.append(f"claim {claim_id} has invalid confidence")
        if not str(claim.get("statement") or "").strip():
            errors.append(f"claim {claim_id} requires statement")
        comparison_ids = claim.get("comparison_ids") or []
        for comparison_id in comparison_ids:
            if comparison_id not in refs["comparison_ids"]:
                errors.append(f"claim {claim_id} references missing comparison {comparison_id}")
        evidence_ids = claim.get("evidence_ids") or []
        if not evidence_ids:
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
        _validate_claim_evidence(claim_id, claim, records, meta, errors)

    node_reviews: dict[str, dict[str, Any]] = {}
    for review in report.get("node_reviews") or []:
        node_id = str(review.get("node_id") or "")
        if node_id not in standard_nodes:
            errors.append(f"node review references unknown node {node_id}")
        if node_id in node_reviews:
            errors.append(f"duplicate node review for {node_id}")
        node_reviews[node_id] = review
        if not str(review.get("overview") or "").strip():
            errors.append(f"node review {node_id} requires overview")
        if not str(review.get("difference_from_reference") or "").strip():
            errors.append(f"node review {node_id} requires difference_from_reference")
        _validate_degree(node_id, "implementation_degree", review.get("implementation_degree"), IMPLEMENTATION_LEVELS, claims, errors)
        _validate_degree(node_id, "originality", review.get("originality"), ORIGINALITY_LEVELS, claims, errors)
        for claim_id in review.get("claim_ids") or []:
            if claim_id not in claims:
                errors.append(f"node review {node_id} references missing claim {claim_id}")
            elif claims[claim_id].get("node_id") != node_id:
                errors.append(f"node review {node_id} references claim from another node {claim_id}")
        for ref in review.get("provenance_refs") or []:
            if ref.get("target_file") and ref["target_file"] not in refs["target_files"]:
                errors.append(f"node review {node_id} references missing provenance file {ref['target_file']}")

    modules: dict[str, dict[str, Any]] = {}
    for review in report.get("module_reviews") or []:
        module_id = str(review.get("module_id") or "")
        if module_id not in MODULE_IDS:
            errors.append(f"module review references unknown module {module_id}")
        if module_id in modules:
            errors.append(f"duplicate module review for {module_id}")
        modules[module_id] = review
        for field in ("overview", "difference_summary", "original_work_summary", "implementation_summary"):
            if not str(review.get(field) or "").strip():
                errors.append(f"module review {module_id} requires {field}")
        for claim_id in review.get("featured_claim_ids") or []:
            if claim_id not in claims:
                errors.append(f"module review {module_id} references missing claim {claim_id}")
        chains = review.get("key_chains") or []
        if require_complete and not chains:
            errors.append(f"module review {module_id} requires key_chains")
        for chain in chains:
            if not str(chain.get("title") or "").strip() or not str(chain.get("explanation") or "").strip():
                errors.append(f"module review {module_id} key chain requires title and explanation")
            if not chain.get("node_ids") or not chain.get("claim_ids") or not chain.get("evidence_ids"):
                errors.append(f"module review {module_id} key chain requires node_ids, claim_ids, and evidence_ids")
            for node_id in chain.get("node_ids") or []:
                if node_id not in standard_nodes:
                    errors.append(f"module review {module_id} key chain references unknown node {node_id}")
            for claim_id in chain.get("claim_ids") or []:
                if claim_id not in claims:
                    errors.append(f"module review {module_id} key chain references missing claim {claim_id}")
            for evidence_id in chain.get("evidence_ids") or []:
                if evidence_id not in evidence or not evidence[evidence_id].get("verified"):
                    errors.append(f"module review {module_id} key chain references missing or unverified evidence {evidence_id}")

    highlights = report.get("report_highlights") or {}
    for module_id in highlights.get("expanded_module_ids") or []:
        if module_id not in MODULE_IDS:
            errors.append(f"highlight references unknown module {module_id}")
    for claim_id in highlights.get("featured_claim_ids") or []:
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
        assessment = report.get("overall_assessment") or {}
        for field in ("summary", "source_relation", "main_inherited", "main_modified", "main_independent", "incomplete_or_risks", "review_focus"):
            value = assessment.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                errors.append(f"overall assessment requires {field}")
        edges = assessment.get("architecture_edges") or []
        if not edges:
            errors.append("overall assessment requires architecture_edges")
        for edge in edges:
            if edge.get("from_module") not in MODULE_IDS or edge.get("to_module") not in MODULE_IDS:
                errors.append("architecture edge references unknown module")
            if not str(edge.get("label") or "").strip():
                errors.append("architecture edge requires label")
            for claim_id in edge.get("claim_ids") or []:
                if claim_id not in claims:
                    errors.append(f"architecture edge references missing claim {claim_id}")
    return errors


def _validate_claim_evidence(claim_id: str, claim: dict[str, Any], records: list[dict[str, Any]],
                             meta: dict[str, Any], errors: list[str]) -> None:
    claim_type = claim.get("claim_type")
    verdict = claim.get("verdict")
    target_commit = meta["target_snapshot"].get("commit")
    reference_commit = meta["base_snapshot"].get("commit")
    commits = {x.get("metadata", {}).get("snapshot_commit") for x in records}
    comparison_claim = claim_type in {"lineage", "difference"} or verdict in {"inherited", "inherited_modified"}
    if comparison_claim and not ({target_commit, reference_commit} <= commits):
        errors.append(f"comparison claim {claim_id} requires bilateral source evidence")
    if claim_type == "independent_work" or verdict == "independently_added":
        kinds = {x.get("kind") for x in records}
        has_complete_negative = any(x.get("kind") == "negative_search" and x.get("metadata", {}).get("coverage_complete") for x in records)
        if target_commit not in commits or "formal_search" not in kinds or not has_complete_negative:
            errors.append(f"independent claim {claim_id} requires work source, formal search, and complete negative search evidence")
    if claim_type == "absence" or verdict == "absent":
        complete = any(x.get("kind") == "negative_search" and x.get("metadata", {}).get("coverage_complete") for x in records)
        architecture_evidence = verdict == "not_applicable" and any(x.get("kind") in {"config_entry", "documentation", "source_span"} for x in records)
        if not complete and not architecture_evidence:
            errors.append(f"absence claim {claim_id} requires complete negative search evidence")


def _validate_degree(node_id: str, label: str, value: Any, allowed: set[str],
                     claims: dict[str, dict[str, Any]], errors: list[str]) -> None:
    row = value if isinstance(value, dict) else {}
    if row.get("level") not in allowed:
        errors.append(f"node review {node_id} has invalid {label} level")
    if not str(row.get("rationale") or "").strip():
        errors.append(f"node review {node_id} requires {label} rationale")
    claim_ids = row.get("claim_ids") or []
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


def _module_id(node_id: str) -> str:
    return node_id.split(".", 1)[0]


def _display_name(repo: str) -> str:
    name = Path(repo).name
    return name.removeprefix("oskernel2023-") or name


def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _prepare_claim(report: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    row = dict(claim)
    row["claim_id"] = row.get("claim_id") or stable_id("claim", {
        "run": report["comparison_run_id"],
        "node_id": row.get("node_id"),
        "type": row.get("claim_type"),
        "statement": row.get("statement"),
    }, 16)
    return row


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
