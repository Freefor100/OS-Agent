from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Set

from core.agent_graph_state import TaskSpec
from core.feature_schema_bank import (
    collect_feature_ids,
    feature_context_for_question,
    negative_search_policy_for_question,
    required_evidence_types_for_question,
)
from core.per_planner import STAGE_HINTS


def _slug(s: str, limit: int = 40) -> str:
    out = re.sub(r"[^A-Za-z0-9_]+", "_", (s or "").strip())
    out = re.sub(r"_+", "_", out).strip("_")
    return (out or "task")[:limit]


def _qid_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:8]


def _question_keywords(q: Dict[str, Any]) -> List[str]:
    hints = q.get("task_hints") if isinstance(q.get("task_hints"), dict) else {}
    kws = hints.get("keywords") if isinstance(hints.get("keywords"), list) else []
    out = [str(x).strip() for x in kws if str(x).strip()]
    stem = str(q.get("stem", ""))
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", stem):
        if token.lower() not in {"the", "and", "with", "must", "impl", "state"}:
            out.append(token)
    zh_markers = [
        "页表",
        "物理页",
        "调度",
        "上下文切换",
        "系统调用",
        "trap",
        "文件系统",
        "网络",
        "权限",
        "锁",
        "Futex",
        "fork",
        "exec",
        "wait",
    ]
    for marker in zh_markers:
        if marker in stem:
            out.append(marker)
    seen = set()
    deduped = []
    for item in out:
        low = item.lower()
        if low not in seen:
            seen.add(low)
            deduped.append(item)
    return deduped[:8]


def build_tasks_for_stage(
    *,
    stage_id: str,
    stage_title: str,
    questions: List[Dict[str, Any]],
    plan: Any,
) -> List[TaskSpec]:
    hints = STAGE_HINTS.get(stage_id, {})
    stage_seed_paths = list(getattr(plan, "seed_paths", None) or hints.get("seed_paths", []))
    stage_entry_symbols = list(getattr(plan, "entry_symbols", None) or hints.get("entry_symbols", []))
    tasks: List[TaskSpec] = []

    if not questions:
        base = _slug(stage_id)
        tasks.extend(
            [
                TaskSpec(
                    task_id=f"task_{base}_discovery",
                    stage_id=stage_id,
                    task_type="discovery",
                    query=f"{stage_title} 相关核心模块和入口",
                    seed_paths=stage_seed_paths,
                    entry_symbols=stage_entry_symbols,
                    expected_evidence_types=["search"],
                ),
                TaskSpec(
                    task_id=f"task_{base}_build_platform",
                    stage_id=stage_id,
                    task_type="build_platform",
                    query=f"{stage_title} 相关构建、平台、文档线索",
                    seed_paths=stage_seed_paths,
                    entry_symbols=stage_entry_symbols,
                    expected_evidence_types=["documentation", "build_config"],
                ),
            ]
        )
        if "10_history" in stage_id:
            tasks.append(
                TaskSpec(
                    task_id=f"task_{base}_git_history",
                    stage_id=stage_id,
                    task_type="git_history",
                    query="开发历史、作者贡献和关键文件演进",
                    expected_evidence_types=["git_history"],
                )
            )
        return tasks

    for q in questions:
        qid = str(q.get("question_id", "")).strip() or _qid_hash(str(q))
        qtype = str(q.get("question_type", "")).strip()
        stem = str(q.get("stem", "")).strip()
        task_hints = q.get("task_hints") if isinstance(q.get("task_hints"), dict) else {}
        evidence_policy = q.get("evidence_policy") if isinstance(q.get("evidence_policy"), dict) else {}
        hinted_types = task_hints.get("task_types") if isinstance(task_hints.get("task_types"), list) else []
        expected_types = required_evidence_types_for_question(q)
        seed_paths = [str(x) for x in task_hints.get("seed_paths", [])] if isinstance(task_hints.get("seed_paths"), list) else []
        entry_symbols = [str(x) for x in task_hints.get("entry_symbols", [])] if isinstance(task_hints.get("entry_symbols"), list) else []
        seed_paths = (seed_paths + stage_seed_paths)[:10]
        entry_symbols = (entry_symbols + stage_entry_symbols)[:10]
        keywords = _question_keywords(q)
        feature_ids = collect_feature_ids(q)
        feature_context = feature_context_for_question(q)
        negative_search_policy = negative_search_policy_for_question(q)
        diagnostic_checks = _list_str(task_hints.get("diagnostic_checks"), 12)
        structured_facts = _list_dict(task_hints.get("structured_facts"), 12) or _list_dict(q.get("structured_facts"), 12)
        answer_contract = q.get("answer_contract") if isinstance(q.get("answer_contract"), dict) else {}
        concept_boundary = str(q.get("concept_boundary") or "")
        llm_answer_steps = _list_str(q.get("llm_answer_steps"), 12)
        fact_brief = _structured_fact_brief(structured_facts, 10)
        query = (
            f"{stage_title} / {qid}: {stem}\n"
            f"关键词: {', '.join(keywords)}\n"
            f"概念边界: {concept_boundary}\n"
            f"结构化事实: {fact_brief}\n"
            f"LLM作答步骤: {' | '.join(llm_answer_steps)}\n"
            f"局部判断步骤: {' | '.join(diagnostic_checks)}"
        )
        base = f"task_{stage_id}_{qid}"

        task_types = list(hinted_types)
        if not task_types:
            # Keep v1 task fanout conservative. One semantic discovery task per
            # question usually yields enough evidence for Writer/Review; add one
            # specialized task only when the question clearly needs it.
            task_types.append("discovery")
            if any(x in stem for x in ("构建", "平台", "架构", "Makefile", "Cargo", "QEMU")):
                task_types.append("build_platform")
            elif any(x.lower() in stem.lower() for x in ("调用链", "跳转链", "路径", "call graph", "flow")):
                task_types.append("flow")
            elif "definition" in expected_types or any(x in stem for x in ("结构体", "字段", "类型", "接口")):
                task_types.append("definition")
            elif qtype == "tri_state_impl" and any(x in stem for x in ("桩", "stub", "todo", "ENOSYS")):
                task_types.append("implementation_state")

        for task_type in dict.fromkeys(task_types):
            tasks.append(
                TaskSpec(
                    task_id=f"{base}_{_slug(task_type)}",
                    stage_id=stage_id,
                    question_id=qid,
                    task_type=str(task_type),
                    query=query,
                    seed_paths=seed_paths,
                    entry_symbols=entry_symbols,
                    expected_evidence_types=expected_types,
                    metadata={
                        "question_type": qtype,
                        "stem": stem,
                        "keywords": keywords,
                        "feature_ids": feature_ids,
                        "feature_context": feature_context,
                        "negative_search_policy": negative_search_policy,
                        "diagnostic_checks": diagnostic_checks,
                        "structured_facts": structured_facts,
                        "answer_contract": answer_contract,
                        "concept_boundary": concept_boundary,
                        "llm_answer_steps": llm_answer_steps,
                    },
                )
            )
    return tasks


def build_tasks_from_llm_plan(
    *,
    stage_id: str,
    stage_title: str,
    questions: List[Dict[str, Any]],
    plan: Any,
    llm_task_plan: Iterable[Dict[str, Any]],
) -> List[TaskSpec]:
    """Validate LLM-proposed grouped tasks and fill missing fields safely.

    The Plan Agent proposes; this function disposes. Invalid question ids are
    dropped, but grouping size remains the LLM planner's responsibility.
    """

    qmap = {str(q.get("question_id") or "").strip(): q for q in questions if isinstance(q, dict)}
    valid_qids: Set[str] = {qid for qid in qmap if qid}
    if not valid_qids:
        return build_tasks_for_stage(stage_id=stage_id, stage_title=stage_title, questions=questions, plan=plan)

    hints = STAGE_HINTS.get(stage_id, {})
    stage_seed_paths = list(getattr(plan, "seed_paths", None) or hints.get("seed_paths", []))
    stage_entry_symbols = list(getattr(plan, "entry_symbols", None) or hints.get("entry_symbols", []))
    seen: Set[str] = set()
    tasks: List[TaskSpec] = []

    for idx, raw in enumerate(llm_task_plan or [], 1):
        if not isinstance(raw, dict):
            continue
        raw_qids = raw.get("question_ids")
        if not isinstance(raw_qids, list):
            raw_qids = [raw.get("question_id")]
        qids = [str(x).strip() for x in raw_qids if str(x).strip() in valid_qids]
        if not qids:
            continue
        for chunk_i, qchunk in enumerate([_dedupe(qids)], 1):
            task_type = _normalize_task_type(str(raw.get("task_type") or raw.get("agent_type") or "react_code"))
            seed_paths = _list_str(raw.get("seed_paths"), 20) or stage_seed_paths[:20]
            entry_symbols = _list_str(raw.get("entry_symbols"), 20) or stage_entry_symbols[:20]
            expected = _list_str(raw.get("expected_evidence_types"), 12)
            allowed_tools = _list_str(raw.get("allowed_tools") or raw.get("tool_policy"), 12)
            goal = str(raw.get("task_goal") or raw.get("query") or "").strip()
            if not goal:
                stems = "；".join(str(qmap[qid].get("stem", "")) for qid in qchunk)
                goal = f"{stage_title}: 查证并回答这些题：{stems[:500]}"
            base = str(raw.get("task_id") or f"task_{stage_id}_group_{idx}_{chunk_i}")
            task_id = _slug(base, 80)
            if not task_id.startswith("task_"):
                task_id = f"task_{stage_id}_{task_id}"
            if task_id in seen:
                task_id = f"{task_id}_{chunk_i}"
            seen.add(task_id)
            keywords: List[str] = []
            feature_ids: List[str] = []
            negative_search_policy: Dict[str, Any] = {}
            negative_search_policies: Dict[str, Dict[str, Any]] = {}
            feature_contexts: Dict[str, Any] = {}
            diagnostic_checks: List[str] = []
            structured_facts: List[Dict[str, Any]] = []
            answer_contracts: Dict[str, Any] = {}
            concept_boundaries: Dict[str, str] = {}
            llm_answer_steps: List[str] = []
            for qid in qchunk:
                keywords.extend(_question_keywords(qmap[qid]))
                feature_ids.extend(collect_feature_ids(qmap[qid]))
                feature_contexts[qid] = feature_context_for_question(qmap[qid])
                q_required = required_evidence_types_for_question(qmap[qid])
                expected = _dedupe(list(expected) + q_required)[:12]
                q_negative_policy = negative_search_policy_for_question(qmap[qid])
                if q_negative_policy:
                    negative_search_policies[qid] = q_negative_policy
                hints = qmap[qid].get("task_hints") if isinstance(qmap[qid].get("task_hints"), dict) else {}
                diagnostic_checks.extend(_list_str(hints.get("diagnostic_checks"), 12))
                structured_facts.extend(_list_dict(hints.get("structured_facts"), 12) or _list_dict(qmap[qid].get("structured_facts"), 12))
                if isinstance(qmap[qid].get("answer_contract"), dict):
                    answer_contracts[qid] = qmap[qid]["answer_contract"]
                if qmap[qid].get("concept_boundary"):
                    concept_boundaries[qid] = str(qmap[qid].get("concept_boundary") or "")
                llm_answer_steps.extend(_list_str(qmap[qid].get("llm_answer_steps"), 12))
                negative_search_policy = _merge_negative_search_policies(negative_search_policies.values())
            tasks.append(
                TaskSpec(
                    task_id=task_id,
                    stage_id=stage_id,
                    question_id=qchunk[0],
                    question_ids=qchunk,
                    task_type=task_type,
                    agent_type=str(raw.get("agent_type") or task_type),
                    task_goal=goal,
                    query=str(raw.get("query") or goal),
                    seed_paths=seed_paths,
                    entry_symbols=entry_symbols,
                    expected_evidence_types=expected,
                    tool_policy={"allowed_tools": allowed_tools} if allowed_tools else {},
                    metadata={
                        "source": "llm_task_plan",
                        "group_reason": str(raw.get("group_reason") or ""),
                        "keywords": _dedupe(keywords)[:12],
                        "feature_ids": _dedupe(feature_ids),
                        "feature_context_by_question": feature_contexts,
                        "negative_search_policy": negative_search_policy,
                        "negative_search_policy_by_question": negative_search_policies,
                        "diagnostic_checks": _dedupe(diagnostic_checks)[:20],
                        "structured_facts": _dedupe_dicts_by_id(structured_facts)[:30],
                        "answer_contract_by_question": answer_contracts,
                        "concept_boundary_by_question": concept_boundaries,
                        "llm_answer_steps": _dedupe(llm_answer_steps)[:30],
                    },
                )
            )

    if tasks:
        return tasks
    return []


def _list_str(value: Any, limit: int) -> List[str]:
    if isinstance(value, dict):
        value = value.get("allowed_tools") or value.get("tools")
    if not isinstance(value, list):
        return []
    out = [str(x).strip() for x in value if str(x).strip()]
    return _dedupe(out)[:limit]


def _list_dict(value: Any, limit: int) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out = [dict(x) for x in value if isinstance(x, dict)]
    return out[:limit]


def _structured_fact_brief(facts: List[Dict[str, Any]], limit: int) -> str:
    parts: List[str] = []
    for fact in facts[:limit]:
        fid = str(fact.get("fact_id") or "").strip()
        key = str(fact.get("fact_key") or "").strip()
        answer_type = str(fact.get("answer_type") or "").strip()
        allowed = fact.get("allowed_values") if isinstance(fact.get("allowed_values"), list) else []
        allowed_brief = "/".join(str(x) for x in allowed[:5])
        parts.append(f"{fid}:{key}({answer_type}:{allowed_brief})")
    return " | ".join(parts)


def _dedupe_dicts_by_id(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        key = str(item.get("fact_id") or item.get("fact_key") or item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _merge_negative_search_policies(policies: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    merged_keywords: List[str] = []
    merged_seed_paths: List[str] = []
    min_keyword_coverage = 0.0
    min_directory_coverage = 0.0
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        keywords = policy.get("keywords") if isinstance(policy.get("keywords"), list) else []
        seed_paths = policy.get("seed_paths") if isinstance(policy.get("seed_paths"), list) else []
        merged_keywords.extend(str(x).strip() for x in keywords if str(x).strip())
        merged_seed_paths.extend(str(x).strip() for x in seed_paths if str(x).strip())
        min_keyword_coverage = max(min_keyword_coverage, float(policy.get("minimum_keyword_coverage", 0.0) or 0.0))
        min_directory_coverage = max(min_directory_coverage, float(policy.get("minimum_directory_coverage", 0.0) or 0.0))
    out: Dict[str, Any] = {}
    if merged_keywords:
        out["keywords"] = _dedupe(merged_keywords)[:40]
    if merged_seed_paths:
        out["seed_paths"] = _dedupe(merged_seed_paths)[:30]
    if min_keyword_coverage:
        out["minimum_keyword_coverage"] = min_keyword_coverage
    if min_directory_coverage:
        out["minimum_directory_coverage"] = min_directory_coverage
    return out


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _normalize_task_type(value: str) -> str:
    value = (value or "").strip().lower()
    mapping = {
        "react": "react_code",
        "code": "react_code",
        "lsp": "react_lsp",
        "rag": "react_rag",
        "history": "react_history",
        "git": "react_history",
        "build": "react_build",
        "platform": "react_build",
    }
    return mapping.get(value, value or "react_code")
