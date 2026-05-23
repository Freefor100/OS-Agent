from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Set


TECH_STAGE_IDS: Set[str] = {
    "02_boot_trap",
    "03_mem_mgmt",
    "04_process_smp",
    "05_fs_drivers",
    "06_sync_ipc",
    "07_security",
    "08_network",
    "09_debug_error",
}

TRI_STATE_VALUES = {"implemented", "stub", "not_found", "unknown"}

STRONG_EVIDENCE_TYPES = {
    "definition",
    "implementation_body",
    "function_body",
    "call_site",
    "usage_flow",
    "call_graph",
    "read_code_segment",
}

HINT_EVIDENCE_TYPES = {"search", "semantic_search", "rag", "grep", "outline"}


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        value = str(item).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def features_for_stage_qa(stage_qa: Dict[str, Any]) -> List[Dict[str, Any]]:
    features = stage_qa.get("features", []) if isinstance(stage_qa, dict) else []
    return [feature for feature in features if isinstance(feature, dict)]


def feature_by_question(stage_qa: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for feature in features_for_stage_qa(stage_qa):
        qids = feature.get("question_ids") if isinstance(feature.get("question_ids"), list) else []
        for qid in qids:
            out.setdefault(str(qid), []).append(feature)
    return out


def collect_feature_ids(question: Dict[str, Any]) -> List[str]:
    value = question.get("feature_ids") if isinstance(question, dict) else None
    if isinstance(value, list):
        return _dedupe(str(item) for item in value)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def feature_context_for_question(question: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(question, dict):
        return {}
    qid = str(question.get("question_id") or "").strip()
    if not qid:
        return {}
    return {
        "feature_ids": collect_feature_ids(question),
        "tri_state_rule": question.get("tri_state_rule") if isinstance(question.get("tri_state_rule"), dict) else {},
        "evidence_policy": question.get("evidence_policy") if isinstance(question.get("evidence_policy"), dict) else {},
        "anti_examples": question.get("anti_examples") if isinstance(question.get("anti_examples"), list) else [],
        "diagnostic_checks": question.get("diagnostic_checks") if isinstance(question.get("diagnostic_checks"), list) else [],
        "structured_facts": question.get("structured_facts") if isinstance(question.get("structured_facts"), list) else [],
        "answer_contract": question.get("answer_contract") if isinstance(question.get("answer_contract"), dict) else {},
        "textbook_basis": question.get("textbook_basis") if isinstance(question.get("textbook_basis"), list) else [],
        "concept_boundary": str(question.get("concept_boundary") or ""),
    }


def required_evidence_types_for_question(question: Dict[str, Any]) -> List[str]:
    policy = question.get("evidence_policy") if isinstance(question, dict) and isinstance(question.get("evidence_policy"), dict) else {}
    required = policy.get("required_evidence_types") if isinstance(policy.get("required_evidence_types"), list) else []
    return _dedupe(str(item) for item in required)


def negative_search_policy_for_question(question: Dict[str, Any]) -> Dict[str, Any]:
    policy = question.get("evidence_policy") if isinstance(question, dict) and isinstance(question.get("evidence_policy"), dict) else {}
    neg = policy.get("negative_search_policy") if isinstance(policy.get("negative_search_policy"), dict) else {}
    return dict(neg)


def normalize_tri_state_answer_value(value: Any) -> str:
    if isinstance(value, str) and value.strip() in TRI_STATE_VALUES:
        return value.strip()
    return "unknown"


def evidence_can_support_claim(evidence: Sequence[Any], claim_type: str) -> bool:
    claim_type = (claim_type or "").strip()
    if not claim_type:
        return False
    for rec in evidence:
        supports = getattr(rec, "supports_claim_types", None) or []
        if claim_type in supports:
            return True
    return False


def strongest_evidence_strength(evidence: Sequence[Any]) -> str:
    rank = {"invalid": 0, "hint": 1, "weak": 2, "strong": 3}
    best = "invalid"
    for rec in evidence:
        strength = str(getattr(rec, "strength", "") or "weak")
        if rank.get(strength, 0) > rank.get(best, 0):
            best = strength
    return best
