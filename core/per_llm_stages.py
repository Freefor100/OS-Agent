"""
LLM 驱动的 Plan / Review 阶段（与规则式 per_planner / per_reviewer 配合）。

describe 主流程中：每阶段调用「LLM 规划 Agent」、③ Verify / ④ Patch 计划（默认 ReAct + stream，与 ② 同构）及失败时的 invoke 回退；
审阅 JSON 仍失败时回退规则审阅（见 per_reviewer.review_stage）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError

from core.agent_builder import build_patch_plan_agent, build_verifier_agent
from core.per_io_preview import (
    log_llm_response_tokens,
    log_llm_text_call_out,
    print_agent_long_preview,
)
from core.per_types import PlanSpec, ReviewResult, StageState

logger = logging.getLogger(__name__)

PLANNER_RECURSION_LIMIT = 64
VERIFY_RECURSION_LIMIT = 48
PATCH_PLAN_RECURSION_LIMIT = 40

VERIFIER_AGENT_SYSTEM = """你是 describe 流水线里「③ Verify」子过程的 ReAct 智能体，与「② Execute」使用**同一套工具类型**（`get_planning_tools`：目录/RAG/LSP/小段精读等，只读）。
- 若对某条结论是否真有代码支撑存疑，可**按需**调用工具做 spot-check；不要漫无目的扫仓，建议工具轮次 ≤10。
- 你也可以在证据已足时**不调用工具**，直接根据用户给出的草稿与证据摘要下判断。
- 当你准备给出最终审查结论时：**最后一条**助手消息必须**只包含**一段 ```json ... ```，字段与用户在 Human 消息中要求的 JSON 完全一致；不要在代码块外再写任何文字。"""

PATCH_PLAN_AGENT_SYSTEM = """你是「④ Patch 计划」子过程的 ReAct 智能体，工具集与 Plan/Verify 相同（只读）。
- 若需确认某 `paragraph_id` 与仓库是否匹配，可少量用 `list_repo_structure` / `grep_in_repo` 等；多数情况可直接压缩用户给出的 repair_actions。
- **最后一条**助手消息必须**只包含** ```json ... ```，内含 patch_summary 与 patch_plan；代码块外勿写文字。"""
PLANNER_SYSTEM = """你是操作系统代码分析任务的「规划员」，只做两件事：
1) 使用工具摸清本仓库与当前阶段相关的目录/模块/符号/调用关系（不要写正式分析报告）。
2) 在信息足够后，输出**唯一**一段 Markdown 的 ```json ... ``` 围栏，其中为一个 JSON 对象，字段如下（均为选填，与启发式计划合并）：
   - goal: string，本阶段一句话目标（≤120 字）
   - must_cover: string[]，必须覆盖的要点（短句）
   - evidence_targets: string[]，应用代码证据回答的子主题
   - seed_paths: string[]，建议优先查看的相对路径或目录（≤12 条）
   - entry_symbols: string[]，值得追踪的符号名（≤10 条）
   - preferred_tools: string[]，推荐给**下一阶段执行 Agent** 的工具名（须为当前已挂载工具）
   - repo_structure_notes: string，仓库结构与本阶段相关性的简短说明（≤400 字）
   - execution_steps: string[]，**必填**，4～8 条；按顺序写「执行 Agent 下一步该做什么」的短句（类似 Cursor 里锁定的 to-do），须覆盖：如何找入口、如何取证、如何对照 must_cover 收束；禁止泛泛的「分析代码」。

可用工具（按推荐顺序）：
- 布局：`list_repo_structure`、`find_os_core_modules`、`grep_in_repo`
- 语义：`rag_search_code`
- LSP：`lsp_get_document_outline`（先鸟瞰再读）、`lsp_get_definition`、`lsp_get_references`；`lsp_get_call_graph` 仅对**一个**关键入口且 max_depth≤3
- 若 LSP 与架构不匹配：可 `lsp_set_target_arch` 后再查
- 精读：仅对已锁定文件用 `read_code_segment` **小段**（禁止批量通读大文件）
- 若本阶段附带：`analyze_tech_stack`、`web_search`（概览）或 Git 历史类工具（历史章节）——按需少用

硬性要求：
- 工具轮次建议 ≤12；优先 outline/RAG，避免连续多次 read_code_segment。
- 最后一轮助手回复**必须**包含且仅包含一个 ```json ... ``` 块；不要在代码块外交谈。
- 路径相对仓库根目录。"""


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text or not text.strip():
        return None
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        blob = fence.group(1).strip()
        try:
            obj = json.loads(blob)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw)):
        c = raw[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(raw[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def run_llm_planning_agent(
    planner_agent: Any,
    state: StageState,
    repo_profile: Dict[str, Any],
    repo_local_path: str,
    *,
    global_memory: Optional[Dict[str, Any]] = None,
    recursion_limit: int = PLANNER_RECURSION_LIMIT,
    on_stream_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    log_io: bool = True,
) -> Tuple[Dict[str, Any], str]:
    """
    运行规划 Agent，返回 (patch 字典, repo_structure_notes)。
    patch 可交给 per_planner.apply_llm_plan_overlay。
    on_stream_step(node_name, state)：每个 graph 事件回调，便于与 Execute 一样打印 Tool/Token。
    """
    global_memory = global_memory or {}
    baseline = state.plan.to_dict() if state.plan else {}
    recent = list((global_memory.get("section_summaries") or {}).items())[-4:]
    recent_txt = "\n".join(f"- {k}: {str(v)[:200]}" for k, v in recent) or "（无）"

    human = f"""## 仓库根路径（调用工具时 repo_path 请使用该路径）
`{repo_local_path}`

## 当前阶段
- stage_id: {state.stage_id}
- title: {state.stage_title}

## 启发式基线计划（JSON，可在 JSON 输出中改进/补充）
{json.dumps(baseline, ensure_ascii=False, indent=2)}

## 仓库画像摘要
- framework_guess: {repo_profile.get("framework_guess", [])}
- arch_guess: {repo_profile.get("arch_guess", [])}
- core_paths 抽样: {(repo_profile.get("core_paths") or [])[:15]}

## 近期已完成章节摘要
{recent_txt}

请先调用工具摸底与本阶段相关的目录与线索；JSON 里 **必须包含 execution_steps（4～8 条）**。最后**只输出** ```json 计划对象```。"""
    messages = [
        SystemMessage(content=PLANNER_SYSTEM),
        HumanMessage(content=human),
    ]
    if log_io:
        print(
            f"   📤 Plan 已发送: SystemMessage(规划员规则) + HumanMessage（≈{len(human)} 字符）"
        )
        print(
            f"      · 含 stage_id={state.stage_id}、启发式基线计划 JSON、repo 画像、近期章节摘要、须输出 execution_steps 等"
        )
    final_state = None
    try:
        for event in planner_agent.stream(
            {"messages": messages},
            config={"recursion_limit": recursion_limit},
        ):
            for node_name, current_state in event.items():
                final_state = current_state
                if on_stream_step is not None:
                    on_stream_step(node_name, current_state)
    except GraphRecursionError:
        logger.warning(
            "run_llm_planning_agent 已达 recursion_limit=%s，尝试从已生成消息解析 JSON",
            recursion_limit,
        )

    if not final_state or not final_state.get("messages"):
        return {}, ""

    text = ""
    for m in reversed(final_state["messages"]):
        if isinstance(m, AIMessage):
            content = (m.content or "").strip()
            tool_calls = getattr(m, "tool_calls", None) or []
            if content and not tool_calls:
                text = content
                break
            if content:
                text = content
    data = extract_json_object(text) or {}
    notes = ""
    if isinstance(data.get("repo_structure_notes"), str):
        notes = data["repo_structure_notes"].strip()[:800]
    if log_io:
        keys = list(data.keys()) if data else []
        n_steps = len(data.get("execution_steps") or []) if isinstance(data.get("execution_steps"), list) else 0
        print(f"   📥 Plan 解析结果: JSON 键 {keys or '（空/解析失败）'}")
        if n_steps:
            print(f"      · execution_steps: {n_steps} 条")
        print(f"      · repo_structure_notes: {'有' if notes else '无'}")
        raw_out = (text or "").strip()
        if raw_out:
            print_agent_long_preview(
                "【① Plan】(规划子图) Agent:",
                raw_out,
                max_chars=8000,
                max_lines=150,
            )
        if data:
            print_agent_long_preview(
                "【① Plan】解析 JSON（将合并进 PlanSpec） Agent:",
                json.dumps(data, ensure_ascii=False, indent=2),
                max_chars=8000,
                max_lines=200,
            )
    return data, notes


def _truncate(s: str, limit: int) -> str:
    s = s or ""
    if len(s) <= limit:
        return s
    head = limit // 2
    return s[:head] + f"\n\n... [省略 {len(s) - limit} 字符] ...\n\n" + s[-head:]


def _evidence_brief(items: List[Any], cap: int = 35) -> str:
    lines: List[str] = []
    for i, it in enumerate(items[:cap]):
        if hasattr(it, "path"):
            path, sym = it.path or "", it.symbol or ""
            excerpt = (it.excerpt or "")[:180].replace("\n", " ")
            lines.append(f"{i+1}. {path} | {sym} | {it.source_type} | {excerpt}")
        elif isinstance(it, dict):
            lines.append(json.dumps(it, ensure_ascii=False)[:220])
    return "\n".join(lines) if lines else "（无）"


def _final_ai_text_for_json(messages: Optional[List[Any]]) -> str:
    """取「最后一条无 tool_calls 的 AIMessage」全文；否则退化为最后一条有内容的 AI。"""
    if not messages:
        return ""
    fallback = ""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            content = (m.content or "").strip()
            tcs = getattr(m, "tool_calls", None) or []
            if content and not tcs:
                return content
            if content:
                fallback = content
    return fallback


def _review_result_from_parsed_dict(data: Dict[str, Any], log_io: bool) -> Optional[ReviewResult]:
    if not data:
        return None

    def _obj_list(key: str) -> List[Dict[str, Any]]:
        v = data.get(key)
        if not isinstance(v, list):
            return []
        out: List[Dict[str, Any]] = []
        for x in v:
            if isinstance(x, dict):
                out.append(x)
        return out

    def _str_list(key: str) -> List[str]:
        v = data.get(key)
        if not isinstance(v, list):
            return []
        return [str(x) for x in v if str(x).strip()][:40]

    try:
        passed = bool(data.get("passed", False))
        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        severity = str(data.get("severity") or "minor")
        if severity not in ("minor", "major", "critical"):
            severity = "minor"

        failed_rules_f = _str_list("failed_rules")
        repair_actions_f = _obj_list("repair_actions")
        if log_io:
            print(
                f"   📥 ③ Verify 结果: passed={passed}, score={score}, severity={severity}, "
                f"repair_actions={len(repair_actions_f)} 条, failed_rules={len(failed_rules_f)} 条"
            )
            preview_obj: Dict[str, Any] = {
                "passed": passed,
                "score": score,
                "severity": severity,
                "failed_rules": failed_rules_f,
                "missing_evidence": _obj_list("missing_evidence")[:6],
                "repair_actions": repair_actions_f[:10],
            }
            print_agent_long_preview(
                "【③ Verify】解析结构化结果预览 Agent:",
                json.dumps(preview_obj, ensure_ascii=False, indent=2),
                max_chars=7000,
                max_lines=200,
            )
        return ReviewResult(
            passed=passed,
            score=score,
            severity=severity,
            failed_rules=failed_rules_f,
            missing_evidence=_obj_list("missing_evidence"),
            weak_claims=_obj_list("weak_claims"),
            format_issues=_obj_list("format_issues"),
            missed_modules=_str_list("missed_modules"),
            repair_actions=repair_actions_f,
        )
    except (TypeError, ValueError) as e:
        logger.warning("run_llm_review 字段解析失败: %s", e)
        if log_io:
            print(f"   📥 ③ Verify 结果: 字段校验失败 — {e}")
        return None


def run_llm_review(
    state: StageState,
    llm: Any,
    *,
    log_io: bool = True,
    on_stream_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    stage_id: str = "",
) -> Optional[ReviewResult]:
    """
    ③ Verify：默认与 ② Execute 同构 —— ReAct + stream +（可选）print_step；
    若未产出可解析 JSON，则回退为单次 llm.invoke（仍无工具）。
    """
    plan = state.plan
    draft = state.draft_markdown or ""
    if not draft.strip():
        return None

    checklist = (plan.review_checklist if plan else []) or []
    must_cover = (plan.must_cover if plan else [])[:12]
    n_ev = len(state.evidence_index or [])
    sid = stage_id or state.stage_id

    prompt = f"""你是技术报告审阅员。根据「草稿正文 + 证据摘要 + 必答要点」输出**仅一段** ```json 代码块。

## 审阅原则
1. 重要技术结论是否带有具体源码路径（反引号路径或 file:line）？
2. 是否明显把 README 当实现证据、或臆测未在证据中出现的实现？
3. 阶段 must_cover 是否在正文中有实质回答（允许同义表述）？
4. 宁严勿松：证据不足应判未通过并给出可执行的修补动作。

## must_cover（阶段要点）
{json.dumps(must_cover, ensure_ascii=False, indent=2)}

## review_checklist
{json.dumps(checklist, ensure_ascii=False, indent=2)}

## 证据索引摘要
{_evidence_brief(state.evidence_index)}

## 草稿正文
{_truncate(draft, 36000)}

## 输出 JSON 字段（类型必须正确）
- passed: boolean
- score: number 0~1
- severity: "minor" | "major" | "critical"
- failed_rules: string[]  简短规则码，如 missing_path_citation / readme_only / must_cover_gap
- missing_evidence: object[]  每项含 paragraph_id(可空), claim_id(可空), reason
- weak_claims: object[]
- format_issues: object[]
- missed_modules: string[]
- repair_actions: object[]  每项须含 action_type（add_evidence|rewrite_paragraph|append_missing_module|normalize_terminology|drop_unsupported_claim）、可选 target_paragraph_id、hint

最后一轮回复**只包含** ```json ... ```，不要其它文字。"""

    if log_io:
        print(
            f"   📤 ③ Verify: ReAct Agent（与 ② Execute 同构：langgraph.stream + 工具集=get_planning_tools）"
        )
        print(
            f"      · recursion_limit={VERIFY_RECURSION_LIMIT}；Human ≈{len(prompt):,} 字符；"
            f"stage_id={sid}；证据 {n_ev} 条；must_cover {len(must_cover)} 条"
        )
        print("      · 若 ReAct 未产出可解析 JSON，将自动回退「单次 llm.invoke」（无工具）")

    messages = [
        SystemMessage(content=VERIFIER_AGENT_SYSTEM),
        HumanMessage(content=prompt),
    ]
    final_state = None
    try:
        agent = build_verifier_agent(stage_id=sid)
        for event in agent.stream(
            {"messages": messages},
            config={"recursion_limit": VERIFY_RECURSION_LIMIT},
        ):
            for node_name, current_state in event.items():
                final_state = current_state
                if on_stream_step is not None:
                    on_stream_step(node_name, current_state)
    except GraphRecursionError:
        logger.warning(
            "run_llm_review ReAct 已达 recursion_limit=%s，尝试解析已生成消息或回退 invoke",
            VERIFY_RECURSION_LIMIT,
        )

    content = ""
    if final_state and final_state.get("messages"):
        content = _final_ai_text_for_json(final_state["messages"])
        if log_io and content:
            for m in reversed(final_state["messages"]):
                if isinstance(m, AIMessage) and (m.content or "").strip():
                    meta = getattr(m, "response_metadata", None) or {}
                    if isinstance(meta, dict) and meta.get("token_usage"):
                        log_llm_response_tokens("③ Verify ReAct（末条含 usage 的 AI）", m)
                        break
            else:
                print(
                    "   📄 ③ Verify ReAct: 各轮 token 见上方 print_step；末条 AI 无 token_usage 聚合"
                )
            print_agent_long_preview(
                "【③ Verify】ReAct 最终 JSON 文本预览 Agent:",
                content,
                max_chars=8000,
                max_lines=150,
            )

    data = extract_json_object(content) if content else None
    if data:
        return _review_result_from_parsed_dict(data, log_io)

    if log_io:
        print("   ⚠️ ③ Verify: ReAct 未得到可解析 JSON → 回退单次 llm.invoke（无工具）")
    if log_io:
        log_llm_text_call_out(
            "③ Verify（回退 invoke）",
            prompt,
            extras=[f"阶段: {state.stage_id}", "与上方 ReAct 共用同一 Human 文本"],
        )
    try:
        resp = llm.invoke(prompt)
        content_fb = (getattr(resp, "content", None) or "").strip()
    except Exception as e:
        logger.warning("run_llm_review invoke 失败: %s", e)
        if log_io:
            print(f"   📥 ③ Verify 结果: invoke 失败 — {e}")
        return None

    if log_io:
        log_llm_response_tokens("③ Verify invoke", resp)
        print_agent_long_preview(
            "【③ Verify】invoke 回退 · 模型回复预览 Agent:",
            content_fb,
            max_chars=8000,
            max_lines=150,
        )

    data_fb = extract_json_object(content_fb)
    if not data_fb:
        logger.warning("run_llm_review 无法解析 JSON")
        if log_io:
            print("   📥 ③ Verify 结果: JSON 解析失败，将回退规则审阅")
        return None

    return _review_result_from_parsed_dict(data_fb, log_io)


_PATCH_ACTION_TYPES = frozenset(
    {"add_evidence", "rewrite_paragraph", "append_missing_module", "normalize_terminology", "drop_unsupported_claim"}
)


def _patch_plan_from_parsed_dict(
    data: Optional[Dict[str, Any]],
    valid_para: set[str],
    max_actions: int,
    log_io: bool,
    *,
    invalid_json_msg: bool = True,
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """从 LLM 解析出的 dict 生成 (cleaned_actions, patch_summary)；无效时 (None, '')。"""
    if not data or not isinstance(data.get("patch_plan"), list):
        if log_io and invalid_json_msg:
            print("   📥 ④ Patch 计划 结果: JSON 无效，将回退使用全部 repair_actions")
        return None, ""

    if log_io:
        print_agent_long_preview(
            "【④ Patch 计划】解析 JSON 预览 Agent:",
            json.dumps(data, ensure_ascii=False, indent=2),
            max_chars=7000,
            max_lines=180,
        )

    rows: List[Dict[str, Any]] = []
    for item in data["patch_plan"]:
        if not isinstance(item, dict):
            continue
        at = str(item.get("action_type") or "").strip()
        if at not in _PATCH_ACTION_TYPES:
            continue
        pid = str(item.get("target_paragraph_id") or "").strip()
        if at == "append_missing_module":
            if pid and pid not in valid_para:
                continue
        else:
            if not pid or pid not in valid_para:
                continue
        hint = str(item.get("hint") or "").strip()[:800]
        order = item.get("order")
        try:
            oi = int(order) if order is not None else len(rows) + 1
        except (TypeError, ValueError):
            oi = len(rows) + 1
        rows.append({"order": oi, "action_type": at, "target_paragraph_id": pid, "hint": hint})

    rows.sort(key=lambda x: x.get("order", 99))
    cleaned = [
        {"action_type": x["action_type"], "target_paragraph_id": x["target_paragraph_id"], "hint": x["hint"]}
        for x in rows[:max_actions]
    ]

    if not cleaned:
        if log_io:
            print("   📥 ④ Patch 计划 结果: 校验后无有效动作，回退全部 repair_actions")
        return None, ""
    summary = ""
    ps = data.get("patch_summary")
    if isinstance(ps, str) and ps.strip():
        summary = ps.strip()[:500]
        logger.info("patch_plan: %s", summary[:200])
    if log_io:
        print(f"   📥 ④ Patch 计划 结果: 有效动作 {len(cleaned)} 条；summary={'有' if summary else '无'}")
        print_agent_long_preview(
            "【④ Patch 计划】最终动作队列（将交给 ⑤ Apply） Agent:",
            json.dumps({"patch_summary": summary, "patch_plan": cleaned}, ensure_ascii=False, indent=2),
            max_chars=5000,
            max_lines=100,
        )
    return cleaned, summary


def run_llm_patch_plan(
    state: StageState,
    review_result: ReviewResult,
    llm: Any,
    *,
    max_actions: int = 6,
    log_io: bool = True,
    on_stream_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    stage_id: str = "",
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """
    ④ Patch 计划：默认与 ② Execute 同构 —— ReAct + stream；
    若未产出有效 patch JSON，回退单次 llm.invoke。
    """
    if not state.draft_document:
        return None, ""
    valid_para = {p.paragraph_id for p in state.draft_document.paragraphs}
    ra = review_result.repair_actions[:24]
    ra_json = json.dumps(ra, ensure_ascii=False, indent=2)[:12000]
    para_list = ", ".join(sorted(valid_para))[:2000]
    sid = stage_id or state.stage_id

    prompt = f"""你是技术编辑。审阅未通过，但修补要**小而准**（类似 IDE 里只改几处），不要大而全重写。

## 阶段
{state.stage_title} ({state.stage_id})

## 段落 id（target_paragraph_id 只能从中选；append_missing_module 可无 id）
{para_list}

## failed_rules
{json.dumps(review_result.failed_rules, ensure_ascii=False)}

## 当前 repair_actions（可能过多，请你压缩为最少步骤）
{ra_json}

## 要求
输出**仅一段** ```json```，结构如下：
{{
  "patch_summary": "一句话说明本轮只修什么",
  "patch_plan": [
    {{
      "order": 1,
      "action_type": "add_evidence|rewrite_paragraph|append_missing_module|normalize_terminology|drop_unsupported_claim",
      "target_paragraph_id": "p001 或空字符串",
      "hint": "给执行修补用的最短提示"
    }}
  ]
}}

规则：
- patch_plan 最多 {max_actions} 条，按 order 升序；合并同类项。
- 优先：补路径引用、改一段、术语统一；避免无的放矢的 append。
- target_paragraph_id 必须与上面列表一致，否则不要该项。
- 不要编造不存在的 paragraph_id。"""

    if log_io:
        print(
            f"   📤 ④ Patch 计划: ReAct Agent（langgraph.stream + get_planning_tools；"
            f"recursion_limit={PATCH_PLAN_RECURSION_LIMIT}）"
        )
        print(
            f"      · Human ≈{len(prompt):,} 字符；stage_id={sid}；"
            f"repair_actions 输入约 {len(ra)} 条；合法段落 id 约 {len(valid_para)} 个；输出上限 {max_actions} 条"
        )
        print("      · 若 ReAct 未产出有效 JSON，将回退「单次 llm.invoke」")

    messages = [
        SystemMessage(content=PATCH_PLAN_AGENT_SYSTEM),
        HumanMessage(content=prompt),
    ]
    final_state = None
    try:
        agent = build_patch_plan_agent(stage_id=sid)
        for event in agent.stream(
            {"messages": messages},
            config={"recursion_limit": PATCH_PLAN_RECURSION_LIMIT},
        ):
            for node_name, current_state in event.items():
                final_state = current_state
                if on_stream_step is not None:
                    on_stream_step(node_name, current_state)
    except GraphRecursionError:
        logger.warning(
            "run_llm_patch_plan ReAct 已达 recursion_limit=%s，尝试解析或回退 invoke",
            PATCH_PLAN_RECURSION_LIMIT,
        )

    content = ""
    if final_state and final_state.get("messages"):
        content = _final_ai_text_for_json(final_state["messages"])
        if log_io and content:
            for m in reversed(final_state["messages"]):
                if isinstance(m, AIMessage) and (m.content or "").strip():
                    meta = getattr(m, "response_metadata", None) or {}
                    if isinstance(meta, dict) and meta.get("token_usage"):
                        log_llm_response_tokens("④ Patch 计划 ReAct（末条含 usage 的 AI）", m)
                        break
            else:
                print(
                    "   📄 ④ Patch 计划 ReAct: 各轮 token 见上方 print_step；末条 AI 无 token_usage 聚合"
                )
            print_agent_long_preview(
                "【④ Patch 计划】ReAct 最终 JSON 文本预览 Agent:",
                content,
                max_chars=6000,
                max_lines=120,
            )

    data = extract_json_object(content) if content else None
    cleaned, summary = _patch_plan_from_parsed_dict(
        data, valid_para, max_actions, log_io, invalid_json_msg=False
    )
    if cleaned is not None:
        return cleaned, summary

    if log_io:
        print("   ⚠️ ④ Patch 计划: ReAct 未得到有效 patch JSON → 回退单次 llm.invoke")
    if log_io:
        log_llm_text_call_out(
            "④ Patch 计划（回退 invoke）",
            prompt,
            extras=[
                f"阶段: {state.stage_id}",
                f"repair_actions 约 {len(ra)} 条",
                "与上方 ReAct 共用同一 Human 文本",
            ],
        )

    try:
        resp = llm.invoke(prompt)
        content_fb = (getattr(resp, "content", None) or "").strip()
    except Exception as e:
        logger.warning("run_llm_patch_plan invoke 失败: %s", e)
        if log_io:
            print(f"   📥 ④ Patch 计划 结果: invoke 失败 — {e}")
        return None, ""

    if log_io:
        log_llm_response_tokens("④ Patch 计划 invoke", resp)
        print_agent_long_preview(
            "【④ Patch 计划】invoke 回退 · 模型回复预览 Agent:",
            content_fb,
            max_chars=6000,
            max_lines=120,
        )

    data_fb = extract_json_object(content_fb)
    return _patch_plan_from_parsed_dict(data_fb, valid_para, max_actions, log_io, invalid_json_msg=True)
