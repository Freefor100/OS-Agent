"""LLM 驱动的 Plan 阶段（与启发式 per_planner 配合）。describe 主流程中每阶段调用「LLM 规划 Agent」。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from core.per_io_preview import print_agent_long_preview
from core.per_types import PlanSpec, StageState

logger = logging.getLogger(__name__)

PLANNER_RECURSION_LIMIT = 80

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
    运行规划 Agent，返回 (规划增量 JSON 字典, repo_structure_notes)。
    字典可交给 per_planner.apply_llm_plan_overlay 合并进 PlanSpec。
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
        if data:
            # 解析成功：只打一份规范化 JSON（避免与「原始含围栏的回复」重复刷屏）
            print_agent_long_preview(
                "【① Plan】解析 JSON（将合并进 PlanSpec） Agent:",
                json.dumps(data, ensure_ascii=False, indent=2),
                max_chars=8000,
                max_lines=200,
            )
        elif raw_out:
            print_agent_long_preview(
                "【① Plan】未解析到有效 JSON，原始回复 Agent:",
                raw_out,
                max_chars=8000,
                max_lines=150,
            )
    return data, notes
