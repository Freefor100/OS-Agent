from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.agent_graph_state import DraftAnswerRecord, EvidenceRecord, TaskResult, TaskSpec
from core.evidence_verifier import verify_evidence


def _task_question_ids(task: TaskSpec) -> List[str]:
    qids = list(task.question_ids or [])
    if task.question_id and task.question_id not in qids:
        qids.insert(0, task.question_id)
    return [str(q).strip() for q in qids if str(q).strip()]


def run_task_agent(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord], List[DraftAnswerRecord]]:
    return _run_react_task_agent(task, repo_path=repo_path)


def _run_react_task_agent(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord], List[DraftAnswerRecord]]:
    from core.agent_builder import build_task_agent_with_tools, get_task_agent_tools
    from core.per_llm_stages import extract_json_object

    budget = _env_int("OS_AGENT_TASK_AGENT_BUDGET", 30)
    tools = _tools_for_task_policy(task, get_task_agent_tools(task.task_type, task.stage_id))
    tool_names = [getattr(t, "name", getattr(t, "__name__", "")) for t in tools]
    prompt = _react_task_prompt(task, repo_path=repo_path, tool_names=tool_names)
    try:
        agent = build_task_agent_with_tools(stage_id=task.stage_id, tools=tools)
        final_state = agent.invoke(
            {"messages": [SystemMessage(content=_TASK_AGENT_SYSTEM), HumanMessage(content=prompt)]},
            config={"recursion_limit": budget},
        )
        text = _last_ai_text(final_state)
        parsed = extract_json_object(text) or {}
        if not parsed:
            raise ValueError("Task Agent did not return parseable JSON")
        records = _records_from_react_output(task, repo_path, parsed)
        drafts = _drafts_from_react_output(task, parsed, records)
        result = _result_from_records(task, records)
        result.draft_answer_ids = [d.draft_answer_id for d in drafts]
        result.findings = parsed.get("open_issues") if isinstance(parsed.get("open_issues"), list) else []
        result.metadata.update(
            {
                "mode": "react",
                "summary": str(parsed.get("summary") or "")[:1000],
                "raw_output_excerpt": text[:2000],
            }
        )
        return result, records, drafts
    except Exception as exc:
        return (
            TaskResult(
                task_id=task.task_id,
                stage_id=task.stage_id,
                question_id=task.question_id,
                question_ids=_task_question_ids(task),
                status="failed",
                errors=[f"{type(exc).__name__}: {exc}"],
                confidence="low",
                metadata={"mode": "react"},
            ),
            [],
            [],
        )


def _tools_for_task_policy(task: TaskSpec, tools: List[Any]) -> List[Any]:
    allowed = task.tool_policy.get("allowed_tools") if isinstance(task.tool_policy, dict) else None
    if not isinstance(allowed, list) or not allowed:
        return tools
    allowed_names = {str(x).strip() for x in allowed if str(x).strip()}
    filtered = [
        tool
        for tool in tools
        if getattr(tool, "name", getattr(tool, "__name__", "")) in allowed_names
    ]
    return filtered or tools


_TASK_AGENT_SYSTEM = """你是 OS-Agent D 的 question-bound Task ReAct Agent。
你负责一个小任务或一组相近题。你必须主动使用工具查证据，然后输出结构化 JSON。

硬性要求：
- 可以思考和调用工具，但最终回复必须只包含一个 JSON 对象。
- 不直接写最终章节；最终只输出 claim、evidence_candidates、draft_answers、missing_evidence_requests。
- evidence_candidates 只是候选工具结果，不能直接作为答案证据；系统会验证候选并生成真正 EvidenceRecord/evidence_id。
- draft_answers 不得用候选下标、路径或 excerpt 冒充证据；若尚无系统 evidence_id，used_evidence_ids 留空并写 missing_evidence_requests。
- 候选证据不得直接支撑 implemented/not_found；证据不足时明确 status=blocked 或 draft value 写 unknown/待核实。
- 对 tri_state_impl 题，如果结论是 not_found/未发现，必须至少产出一条 evidence_type="negative_search" 的候选证据；候选 evidence.metadata.negative_search 必须包含 searched_keywords、searched_directories、match_count、coverage_sufficient=true。
- negative_search 的 excerpt/claim 必须写清“searched ...; no matches/no implementation found”，不要只写一句自然语言结论。
- 不要编造路径、行号、符号名；无法确认就写 open_issues。
"""


def _react_task_prompt(task: TaskSpec, *, repo_path: str, tool_names: List[str]) -> str:
    qids = _task_question_ids(task)
    return (
        f"repo_path: {repo_path}\n"
        f"stage_id: {task.stage_id}\n"
        f"task_id: {task.task_id}\n"
        f"question_ids: {qids}\n"
        f"task_type: {task.task_type}\n"
        f"task_goal: {task.task_goal or task.query}\n"
        f"query: {task.query}\n"
        f"seed_paths: {task.seed_paths}\n"
        f"entry_symbols: {task.entry_symbols}\n"
        f"expected_evidence_types: {task.expected_evidence_types}\n"
        f"feature_ids: {task.metadata.get('feature_ids')}\n"
        f"feature_context: {task.metadata.get('feature_context') or task.metadata.get('feature_context_by_question')}\n"
        f"diagnostic_checks: {task.metadata.get('diagnostic_checks')}\n"
        f"structured_facts: {task.metadata.get('structured_facts')}\n"
        f"answer_contract: {task.metadata.get('answer_contract') or task.metadata.get('answer_contract_by_question')}\n"
        f"concept_boundary: {task.metadata.get('concept_boundary') or task.metadata.get('concept_boundary_by_question')}\n"
        f"llm_answer_steps: {task.metadata.get('llm_answer_steps')}\n"
        f"available_tools: {tool_names}\n\n"
        "字段含义：structured_facts 是必须逐项完成的事实表；answer_contract 规定最终 value 的合法形式；concept_boundary 是防止概念混淆的边界；llm_answer_steps 是本题作答顺序。\n"
        "执行方式：先按 structured_facts 逐项查证可复现事实，再用 diagnostic_checks 补足局部判断，最后给最小 claim；不要跳过事实表直接回答 implemented/not_found。\n"
        "你在本 task 中能看到的证据，是你调用工具后整理出的 evidence_candidates 列表；structured_fact_results 只能用 evidence_candidate_indexes 指向这个候选列表。\n"
        "注意：evidence_candidates 还没有系统 evidence_id，不能被当成最终证据引用；used_evidence_ids 通常留空，等待系统验证候选并生成 Bound Evidence。\n"
        "三态题特别规则：若 draft value 是 not_found，必须给出结构化 negative_search 候选证据，metadata.negative_search.searched_keywords / searched_directories / coverage_sufficient=true 要完整；否则 precheck 会判 weak。\n"
        "每个 draft_answer 应携带 fact_answers 或 structured_fact_results，notes 应列出已完成的 fact_id 与缺失的 fact_id；short_answer/fill_in 的草稿 value 尽量用 fact_key 固定字段对象；证据不足时请求 missing_evidence_requests。\n\n"
        "请用工具查证后输出如下 JSON（不要 Markdown 围栏）：\n"
        "{\n"
        '  "status": "done|blocked|failed",\n'
        '  "summary": "简短说明查到了什么",\n'
        '  "claim": "本 task 能支持的最小事实；证据不足时写待核实",\n'
        '  "structured_fact_results": [\n'
        "    {\n"
        '      "fact_id": "Qxx_001_F01",\n'
        '      "status_or_value": "yes_strong|yes_weak|stub_or_declaration_only|no_after_negative_search|unknown 或结构化值",\n'
        '      "evidence_candidate_indexes": [0],\n'
        '      "notes": "只解释该 fact 的判断边界"\n'
        "    }\n"
        "  ],\n"
        '  "evidence_candidates": [\n'
        "    {\n"
        '      "evidence_type": "definition|implementation_body|call_site|search|negative_search|build_config|git_history|other",\n'
        '      "question_ids": ["Qxx_001"],\n'
        '      "path": "repo-relative/path",\n'
        '      "line_start": 1,\n'
        '      "line_end": 20,\n'
        '      "symbol": "optional_symbol",\n'
        '      "claim": "这条证据能支撑的最小事实",\n'
        '      "snippet": "关键摘录，不超过 1200 字",\n'
        '      "metadata": {"negative_search": {"searched_keywords": [], "searched_directories": [], "match_count": 0, "coverage_sufficient": true}}\n'
        "    }\n"
        "  ],\n"
        '  "draft_answers": [\n'
        "    {\n"
        '      "question_id": "Qxx_001",\n'
        '      "fact_answers": [{"fact_id": "Qxx_001_F01", "value": "unknown", "used_evidence_ids": [], "notes": "草稿阶段通常不填系统证据 ID"}],\n'
        '      "value": "草稿答案或枚举值",\n'
        '      "used_evidence_ids": ["通常留空；不要填写候选下标、路径或未验证 ID"],\n'
        '      "structured_fact_results": ["可引用上面的 fact_id/status"],\n'
        '      "confidence": "high|medium|low",\n'
        '      "notes": "可选"\n'
        "    }\n"
        "  ],\n"
        '  "missing_evidence_requests": [],\n'
        '  "open_issues": []\n'
        "}\n"
    )


def _last_ai_text(final_state: Any) -> str:
    messages = []
    if isinstance(final_state, dict):
        messages = final_state.get("messages") or []
    text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = getattr(msg, "content", "") or ""
            tool_calls = getattr(msg, "tool_calls", None) or []
            if content and not tool_calls:
                return str(content).strip()
            if content and not text:
                text = str(content).strip()
    return text


def _records_from_react_output(task: TaskSpec, repo_path: str, parsed: Dict[str, Any]) -> List[EvidenceRecord]:
    records: List[EvidenceRecord] = []
    evidence_items = parsed.get("evidence_candidates")
    if not isinstance(evidence_items, list):
        evidence_items = parsed.get("evidence")
    for item in evidence_items if isinstance(evidence_items, list) else []:
        if not isinstance(item, dict):
            continue
        qids = item.get("question_ids") if isinstance(item.get("question_ids"), list) else _task_question_ids(task)
        qids = [str(q).strip() for q in qids if str(q).strip()]
        excerpt = str(item.get("snippet") or item.get("excerpt") or item.get("claim") or "").strip()
        if len(excerpt) > 1800:
            excerpt = excerpt[:1800] + "\n... [truncated]"
        item_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        metadata = {
            "query": task.query,
            "task_goal": task.task_goal,
            "keywords": list(task.metadata.get("keywords") or []),
            "seed_paths": list(task.seed_paths or []),
            "required_evidence_types": list(task.expected_evidence_types or []),
            "negative_search_policy": dict(task.metadata.get("negative_search_policy") or {}),
            "llm_candidate": True,
        }
        metadata.update(item_metadata)
        rec = EvidenceRecord(
            evidence_id=f"ev_{task.task_id}_{uuid.uuid4().hex[:8]}",
            stage_id=task.stage_id,
            question_ids=[str(q).strip() for q in qids if str(q).strip()],
            task_id=task.task_id,
            path=_safe_rel_path(repo_path, str(item.get("path") or "")),
            symbol=str(item.get("symbol") or "") or None,
            line_start=_safe_int(item.get("line_start")),
            line_end=_safe_int(item.get("line_end")),
            source_type=str(item.get("source_type") or "source_code"),
            evidence_type=str(item.get("evidence_type") or "search"),
            tool_name="task_react_agent",
            excerpt=excerpt,
            notes=str(item.get("claim") or ""),
            feature_ids=list(task.metadata.get("feature_ids") or []),
            metadata=metadata,
        )
        records.append(
            verify_evidence(
                rec,
                repo_path=repo_path,
                required_evidence_types=list(task.expected_evidence_types or []),
                negative_search_policy=_negative_search_policy_for_qids(task, qids),
            )
        )
    records.extend(_negative_search_records_from_structured_facts(task, repo_path, parsed, records))
    return records


def _negative_search_records_from_structured_facts(
    task: TaskSpec,
    repo_path: str,
    parsed: Dict[str, Any],
    existing_records: List[EvidenceRecord],
) -> List[EvidenceRecord]:
    structured = parsed.get("structured_fact_results")
    if not isinstance(structured, list):
        return []
    existing_not_found_qids = {
        qid
        for rec in existing_records
        if "not_found" in (rec.supports_claim_types or [])
        for qid in rec.question_ids
    }
    negative_search_policy = task.metadata.get("negative_search_policy") if isinstance(task.metadata.get("negative_search_policy"), dict) else {}
    by_qid: Dict[str, Dict[str, Any]] = {}
    for item in structured:
        if not isinstance(item, dict):
            continue
        fact_id = str(item.get("fact_id") or "").strip()
        qid = "_".join(fact_id.split("_")[:2]) if fact_id.startswith("Q") else ""
        if not qid:
            continue
        value = item.get("status_or_value")
        if value == "no_after_negative_search":
            by_qid.setdefault(qid, {})
        if isinstance(value, dict):
            cov = by_qid.setdefault(qid, {})
            cov.update(value)
        notes = str(item.get("notes") or "")
        if "no_after_negative_search" in notes or "负向搜索" in notes or "未发现" in notes:
            by_qid.setdefault(qid, {})
    new_records: List[EvidenceRecord] = []
    for qid, coverage in by_qid.items():
        if qid in existing_not_found_qids:
            continue
        q_negative_search_policy = _negative_search_policy_for_qids(task, [qid])
        keywords = _list_from_any(
            coverage.get("searched_keywords")
            or coverage.get("keywords")
            or q_negative_search_policy.get("keywords")
            or task.metadata.get("keywords")
        )
        directories = _list_from_any(
            coverage.get("searched_directories")
            or coverage.get("seed_paths")
            or q_negative_search_policy.get("seed_paths")
            or task.seed_paths
        )
        neg = {
            "keywords": keywords,
            "searched_keywords": keywords,
            "searched_directories": directories,
            "match_count": coverage.get("match_count", 0),
            "file_count": coverage.get("file_count"),
            "coverage_sufficient": bool(coverage.get("coverage_sufficient", True)),
        }
        excerpt = (
            "searched keywords: "
            + ", ".join(keywords[:40])
            + "; searched directories: "
            + ", ".join(directories[:20])
            + "; no matches/no implementation found"
        )
        rec = EvidenceRecord(
            evidence_id=f"ev_{task.task_id}_{uuid.uuid4().hex[:8]}",
            stage_id=task.stage_id,
            question_ids=[qid],
            task_id=task.task_id,
            source_type="search",
            evidence_type="negative_search",
            tool_name="task_react_agent",
            excerpt=excerpt,
            notes="structured negative search synthesized from structured_fact_results",
            feature_ids=list(task.metadata.get("feature_ids") or []),
            metadata={
                "query": task.query,
                "task_goal": task.task_goal,
                "keywords": keywords,
                "seed_paths": directories,
                "required_evidence_types": list(task.expected_evidence_types or []),
                "negative_search_policy": dict(q_negative_search_policy),
                "negative_search": neg,
                "llm_candidate": True,
                "synthesized_from_structured_fact_results": True,
            },
        )
        new_records.append(
            verify_evidence(
                rec,
                repo_path=repo_path,
                required_evidence_types=list(task.expected_evidence_types or []),
                negative_search_policy=q_negative_search_policy,
            )
        )
    return new_records


def _negative_search_policy_for_qids(task: TaskSpec, qids: List[str]) -> Dict[str, Any]:
    policies = task.metadata.get("negative_search_policy_by_question")
    if isinstance(policies, dict):
        selected = [policies.get(qid) for qid in qids if isinstance(policies.get(qid), dict)]
        if selected:
            return _merge_negative_search_policies(selected)
    policy = task.metadata.get("negative_search_policy")
    return dict(policy) if isinstance(policy, dict) else {}


def _merge_negative_search_policies(policies: List[Dict[str, Any]]) -> Dict[str, Any]:
    keywords: List[str] = []
    seed_paths: List[str] = []
    min_keyword_coverage = 0.0
    min_directory_coverage = 0.0
    for policy in policies:
        keywords.extend(str(x).strip() for x in policy.get("keywords", []) if str(x).strip()) if isinstance(policy.get("keywords"), list) else None
        seed_paths.extend(str(x).strip() for x in policy.get("seed_paths", []) if str(x).strip()) if isinstance(policy.get("seed_paths"), list) else None
        min_keyword_coverage = max(min_keyword_coverage, float(policy.get("minimum_keyword_coverage", 0.0) or 0.0))
        min_directory_coverage = max(min_directory_coverage, float(policy.get("minimum_directory_coverage", 0.0) or 0.0))
    out: Dict[str, Any] = {}
    if keywords:
        out["keywords"] = _dedupe_str(keywords)[:40]
    if seed_paths:
        out["seed_paths"] = _dedupe_str(seed_paths)[:30]
    if min_keyword_coverage:
        out["minimum_keyword_coverage"] = min_keyword_coverage
    if min_directory_coverage:
        out["minimum_directory_coverage"] = min_directory_coverage
    return out


def _dedupe_str(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _list_from_any(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, tuple):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _drafts_from_react_output(task: TaskSpec, parsed: Dict[str, Any], records: List[EvidenceRecord]) -> List[DraftAnswerRecord]:
    by_qid: Dict[str, List[str]] = {}
    for rec in records:
        for qid in rec.question_ids:
            by_qid.setdefault(qid, []).append(rec.evidence_id)
    drafts: List[DraftAnswerRecord] = []
    for item in parsed.get("draft_answers", []) if isinstance(parsed.get("draft_answers"), list) else []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if not qid:
            continue
        allowed = set(by_qid.get(qid, []))
        requested = [str(x).strip() for x in item.get("used_evidence_ids", [])] if isinstance(item.get("used_evidence_ids"), list) else []
        used = [evid for evid in requested if evid and evid in allowed]
        dropped = [evid for evid in requested if evid and evid not in allowed]
        answer = dict(item)
        answer.pop("evidence", None)
        answer.pop("path", None)
        answer.pop("excerpt", None)
        answer.setdefault("question_id", qid)
        answer["used_evidence_ids"] = used
        if "structured_fact_results" not in answer and isinstance(parsed.get("structured_fact_results"), list):
            answer["structured_fact_results"] = parsed.get("structured_fact_results")
        drafts.append(
            DraftAnswerRecord(
                draft_answer_id=f"draft_{task.task_id}_{qid}_{uuid.uuid4().hex[:8]}",
                task_id=task.task_id,
                stage_id=task.stage_id,
                question_id=qid,
                answer=answer,
                used_evidence_ids=used,
                confidence=str(item.get("confidence") or "low"),
                notes=str(item.get("notes") or ""),
                metadata={"dropped_evidence_ids": dropped} if dropped else {},
            )
        )
    return drafts


def _safe_rel_path(repo_path: str, target: str) -> str:
    if not target:
        return ""
    target = target.replace("\\", "/")
    if os.path.isabs(target):
        try:
            rel = os.path.relpath(target, repo_path)
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
        except ValueError:
            pass
    return target.lstrip("/")


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int((os.environ.get(name) or "").strip() or default))
    except ValueError:
        return default


def _result_from_records(task: TaskSpec, records: List[EvidenceRecord]) -> TaskResult:
    valid = [r for r in records if r.validity != "invalid"]
    if any(r.confidence == "high" for r in valid):
        confidence = "high"
    elif any(r.confidence == "medium" for r in valid):
        confidence = "medium"
    else:
        confidence = "low"
    return TaskResult(
        task_id=task.task_id,
        stage_id=task.stage_id,
        question_id=task.question_id,
        question_ids=_task_question_ids(task),
        status="done" if valid else "failed",
        evidence_ids=[r.evidence_id for r in records],
        confidence=confidence,
        errors=[] if valid else ["no valid evidence"],
        metadata={"evidence_count": len(records)},
    )
