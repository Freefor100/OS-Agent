from __future__ import annotations

import os
import re
import uuid
import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.agent_graph_state import DraftAnswerRecord, EvidenceRecord, TaskResult, TaskSpec
from core.evidence_verifier import verify_evidence


def _invoke_tool(tool: Any, args: Dict[str, Any]) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        if hasattr(tool, "invoke"):
            result = str(tool.invoke(args))
        else:
            result = str(tool(**args))
    captured = (stdout.getvalue() + stderr.getvalue()).strip()
    if captured:
        return result + "\n\n[tool_output]\n" + captured
    return result


def _safe_rel_path(repo_path: str, path: str) -> str:
    if not path:
        return ""
    norm_repo = os.path.normpath(repo_path)
    repo_name = os.path.basename(norm_repo)
    norm_path = os.path.normpath(path)
    parts = norm_path.split(os.sep)
    if len(parts) >= 2 and parts[0] == "repos" and parts[1] == repo_name:
        try:
            return os.path.relpath(norm_path, norm_repo).replace("\\", "/")
        except ValueError:
            return norm_path.replace("\\", "/")
    if os.path.isabs(path):
        try:
            return os.path.relpath(path, repo_path).replace("\\", "/")
        except ValueError:
            return path.replace("\\", "/")
    return path.replace("\\", "/")


def _extract_paths(text: str, repo_path: str, limit: int = 5) -> List[str]:
    paths: List[str] = []
    for match in re.finditer(r"([A-Za-z]:)?[^\s`'\"]+\.(?:rs|c|h|cpp|hpp|go|zig|S|s|toml|ld|lds|md|py)(?::\d+(?:-\d+)?)?", text or ""):
        raw = match.group(0).strip("`'\".,;)")
        if not raw or raw.startswith("http"):
            continue
        if ":" in raw[2:]:
            raw = raw.rsplit(":", 1)[0]
        rel = _safe_rel_path(repo_path, raw)
        if rel not in paths:
            paths.append(rel)
        if len(paths) >= limit:
            break
    return paths


def _first_existing_source_file(repo_path: str, seeds: List[str]) -> str:
    exts = (".rs", ".c", ".h", ".cpp", ".hpp", ".go", ".zig", ".S", ".s")
    for seed in seeds:
        candidate = os.path.join(repo_path, seed)
        if os.path.isfile(candidate) and candidate.endswith(exts):
            return _safe_rel_path(repo_path, candidate)
        if os.path.isdir(candidate):
            for root, dirs, files in os.walk(candidate):
                dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "dist", "node_modules", ".os_agent_ra_target"}]
                for name in files:
                    if name.endswith(exts):
                        return _safe_rel_path(repo_path, os.path.join(root, name))
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "dist", "node_modules", ".os_agent_ra_target"}]
        for name in files:
            if name.endswith(exts):
                return _safe_rel_path(repo_path, os.path.join(root, name))
    return ""


def _task_question_ids(task: TaskSpec) -> List[str]:
    qids = list(task.question_ids or [])
    if task.question_id and task.question_id not in qids:
        qids.insert(0, task.question_id)
    return [str(q).strip() for q in qids if str(q).strip()]


def _make_evidence(
    *,
    task: TaskSpec,
    repo_path: str,
    tool_name: str,
    evidence_type: str,
    output: str,
    path: str = "",
    source_type: str = "source_code",
) -> EvidenceRecord:
    excerpt = (output or "").strip()
    if len(excerpt) > 1800:
        excerpt = excerpt[:1800] + "\n... [truncated]"
    rec = EvidenceRecord(
        evidence_id=f"ev_{task.task_id}_{uuid.uuid4().hex[:8]}",
        stage_id=task.stage_id,
        question_ids=_task_question_ids(task),
        task_id=task.task_id,
        path=path,
        source_type=source_type,
        evidence_type=evidence_type,
        tool_name=tool_name,
        excerpt=excerpt,
        metadata={"query": task.query},
    )
    return verify_evidence(rec, repo_path=repo_path)


def run_task_agent(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord], List[DraftAnswerRecord]]:
    mode = (os.environ.get("OS_AGENT_TASK_AGENT_MODE") or "react").strip().lower()
    if mode not in {"tool", "tools", "program"}:
        result, records, drafts = _run_react_task_agent(task, repo_path=repo_path)
        if result.status == "done" or mode in {"react_only", "llm_only"}:
            return result, records, drafts
    result, records = _run_tool_task_agent(task, repo_path=repo_path)
    drafts = _drafts_from_tool_result(task, records)
    result.draft_answer_ids = [d.draft_answer_id for d in drafts]
    result.metadata["mode"] = "tool_fallback" if mode not in {"tool", "tools", "program"} else "tool"
    return result, records, drafts


def _run_tool_task_agent(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    try:
        if task.task_type in {"discovery", "implementation_state"}:
            return _run_rag_task(task, repo_path=repo_path)
        if task.task_type in {"definition", "flow"}:
            return _run_lsp_task(task, repo_path=repo_path)
        if task.task_type == "build_platform":
            return _run_build_platform_task(task, repo_path=repo_path)
        if task.task_type == "git_history":
            return _run_git_history_task(task, repo_path=repo_path)
        return _run_code_evidence_task(task, repo_path=repo_path)
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
            ),
            [],
        )


def _run_react_task_agent(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord], List[DraftAnswerRecord]]:
    from core.agent_builder import build_task_agent, get_task_agent_tools
    from core.per_llm_stages import extract_json_object

    max_steps = _env_int("OS_AGENT_TASK_AGENT_MAX_STEPS", 10)
    tool_names = [getattr(t, "name", getattr(t, "__name__", "")) for t in get_task_agent_tools(task.task_type, task.stage_id)]
    prompt = _react_task_prompt(task, repo_path=repo_path, tool_names=tool_names)
    try:
        agent = build_task_agent(task_type=task.task_type, stage_id=task.stage_id)
        final_state = agent.invoke(
            {"messages": [SystemMessage(content=_TASK_AGENT_SYSTEM), HumanMessage(content=prompt)]},
            config={"recursion_limit": max(6, max_steps + 6)},
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


_TASK_AGENT_SYSTEM = """你是 OS-Agent D 的 question-bound Task ReAct Agent。
你负责一个小任务或一组相近题。你必须主动使用工具查证据，然后输出结构化 JSON。

硬性要求：
- 可以思考和调用工具，但最终回复必须只包含一个 JSON 对象。
- 不直接写最终章节，只输出 evidence 和 draft_answers。
- 每个关键结论必须有 used_evidence_ids。
- 证据不足时明确 status=blocked 或 draft value 写 not_found/待核实。
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
        f"available_tools: {tool_names}\n\n"
        "请用工具查证后输出如下 JSON（不要 Markdown 围栏）：\n"
        "{\n"
        '  "status": "done|blocked|failed",\n'
        '  "summary": "简短说明查到了什么",\n'
        '  "evidence": [\n'
        "    {\n"
        '      "evidence_type": "definition|implementation_body|call_site|search|build_config|git_history|other",\n'
        '      "question_ids": ["Qxx_001"],\n'
        '      "path": "repo-relative/path",\n'
        '      "line_start": 1,\n'
        '      "line_end": 20,\n'
        '      "symbol": "optional_symbol",\n'
        '      "claim": "这条证据能支撑的最小事实",\n'
        '      "snippet": "关键摘录，不超过 1200 字"\n'
        "    }\n"
        "  ],\n"
        '  "draft_answers": [\n'
        "    {\n"
        '      "question_id": "Qxx_001",\n'
        '      "value": "草稿答案或枚举值",\n'
        '      "used_evidence_ids": ["可留空，系统会用本 task evidence 补齐"],\n'
        '      "confidence": "high|medium|low",\n'
        '      "notes": "可选"\n'
        "    }\n"
        "  ],\n"
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
    for item in parsed.get("evidence", []) if isinstance(parsed.get("evidence"), list) else []:
        if not isinstance(item, dict):
            continue
        qids = item.get("question_ids") if isinstance(item.get("question_ids"), list) else _task_question_ids(task)
        excerpt = str(item.get("snippet") or item.get("excerpt") or item.get("claim") or "").strip()
        if len(excerpt) > 1800:
            excerpt = excerpt[:1800] + "\n... [truncated]"
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
            metadata={"query": task.query, "task_goal": task.task_goal},
        )
        records.append(verify_evidence(rec, repo_path=repo_path))
    return records


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
        used = [str(x) for x in item.get("used_evidence_ids", [])] if isinstance(item.get("used_evidence_ids"), list) else []
        if not used:
            used = by_qid.get(qid, [])
        answer = dict(item)
        answer.setdefault("question_id", qid)
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
            )
        )
    return drafts


def _drafts_from_tool_result(task: TaskSpec, records: List[EvidenceRecord]) -> List[DraftAnswerRecord]:
    drafts: List[DraftAnswerRecord] = []
    by_qid: Dict[str, List[str]] = {}
    for rec in records:
        for qid in rec.question_ids:
            by_qid.setdefault(qid, []).append(rec.evidence_id)
    for qid in _task_question_ids(task):
        evidence_ids = by_qid.get(qid, [r.evidence_id for r in records])
        drafts.append(
            DraftAnswerRecord(
                draft_answer_id=f"draft_{task.task_id}_{qid}_{uuid.uuid4().hex[:8]}",
                task_id=task.task_id,
                stage_id=task.stage_id,
                question_id=qid,
                answer={
                    "question_id": qid,
                    "value": "待核实：Task Agent 已收集证据，需由 Assembler 结合题面整理。",
                    "used_evidence_ids": evidence_ids,
                },
                used_evidence_ids=evidence_ids,
                confidence="medium" if evidence_ids else "low",
                notes="programmatic tool fallback draft",
            )
        )
    return drafts


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


def _run_rag_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.file_ops import grep_in_repo, rag_search_code

    records: List[EvidenceRecord] = []
    query = task.query[:1000]
    out = _invoke_tool(rag_search_code, {"repo_path": repo_path, "query": query, "top_k": 5})
    paths = _extract_paths(out, repo_path)
    records.append(
        _make_evidence(
            task=task,
            repo_path=repo_path,
            tool_name="rag_search_code",
            evidence_type="semantic_search",
            output=out,
            path=paths[0] if paths else "",
        )
    )
    if not paths and task.metadata.get("keywords"):
        pattern = "|".join(re.escape(k) for k in task.metadata["keywords"][:4])
        grep_out = _invoke_tool(grep_in_repo, {"repo_path": repo_path, "pattern": pattern, "max_results": 20})
        grep_paths = _extract_paths(grep_out, repo_path)
        records.append(
            _make_evidence(
                task=task,
                repo_path=repo_path,
                tool_name="grep_in_repo",
                evidence_type="search",
                output=grep_out,
                path=grep_paths[0] if grep_paths else "",
            )
        )
    return _result_from_records(task, records), records


def _run_lsp_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.file_ops import grep_in_repo
    from tools.lsp_ops import lsp_get_call_graph, lsp_get_definition, lsp_get_document_outline

    records: List[EvidenceRecord] = []
    default_file_path = _first_existing_source_file(repo_path, task.seed_paths)
    symbols = [s for s in task.entry_symbols if s][:3]
    if not symbols:
        symbols = [k for k in task.metadata.get("keywords", []) if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k)][:3]
    for sym in symbols[:2]:
        grep_out = _invoke_tool(grep_in_repo, {"repo_path": repo_path, "pattern": re.escape(sym), "max_results": 5})
        grep_paths = _extract_paths(grep_out, repo_path)
        file_path = grep_paths[0] if grep_paths else default_file_path
        if task.task_type == "flow":
            out = _invoke_tool(lsp_get_call_graph, {"repo_path": repo_path, "file_path": file_path, "symbol": sym, "max_depth": 3})
            tool_name = "lsp_get_call_graph"
            evidence_type = "call_graph"
        else:
            out = _invoke_tool(lsp_get_definition, {"repo_path": repo_path, "file_path": file_path, "symbol": sym})
            tool_name = "lsp_get_definition"
            evidence_type = "definition"
        paths = _extract_paths(out, repo_path)
        records.append(
            _make_evidence(
                task=task,
                repo_path=repo_path,
                tool_name=tool_name,
                evidence_type=evidence_type,
                output=out,
                path=paths[0] if paths else "",
            )
        )
    if not records and task.seed_paths:
        candidate = default_file_path or task.seed_paths[0]
        out = _invoke_tool(lsp_get_document_outline, {"repo_path": repo_path, "file_path": candidate})
        records.append(
            _make_evidence(
                task=task,
                repo_path=repo_path,
                tool_name="lsp_get_document_outline",
                evidence_type="outline",
                output=out,
                path=_safe_rel_path(repo_path, candidate),
            )
        )
    return _result_from_records(task, records), records


def _run_code_evidence_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.file_ops import grep_in_repo

    pattern = "|".join(re.escape(k) for k in task.metadata.get("keywords", [])[:4]) or re.escape(task.question_id or task.stage_id)
    out = _invoke_tool(grep_in_repo, {"repo_path": repo_path, "pattern": pattern, "max_results": 20})
    paths = _extract_paths(out, repo_path)
    records = [
        _make_evidence(
            task=task,
            repo_path=repo_path,
            tool_name="grep_in_repo",
            evidence_type="search",
            output=out,
            path=paths[0] if paths else "",
        )
    ]
    return _result_from_records(task, records), records


def _run_build_platform_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.build_config_ops import parse_build_config

    out = _invoke_tool(parse_build_config, {"repo_path": repo_path})
    paths = _extract_paths(out, repo_path)
    records = [
        _make_evidence(
            task=task,
            repo_path=repo_path,
            tool_name="parse_build_config",
            evidence_type="build_config",
            output=out,
            path=paths[0] if paths else "README.md",
            source_type="documentation",
        )
    ]
    return _result_from_records(task, records), records


def _run_git_history_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.git_ops import get_git_history_summary

    out = _invoke_tool(get_git_history_summary, {"repo_path": repo_path, "max_commits": 30})
    records = [
        _make_evidence(
            task=task,
            repo_path=repo_path,
            tool_name="get_git_history_summary",
            evidence_type="git_history",
            output=out,
            path=".git",
            source_type="git_history",
        )
    ]
    return _result_from_records(task, records), records


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
