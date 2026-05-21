# core/agent_builder.py
import os
import json
import hashlib
from copy import deepcopy

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from core.agent_locks import lsp_tool_guard, rag_tool_guard
from core.agent_events import current_task_event_context, emit_task_tool_event
from core.deepseek_thinking_patch import apply_deepseek_reasoning_content_patch

try:
    # LangGraph v1+ 提示：create_react_agent 迁移到 langchain.agents
    from langchain.agents import create_agent as create_react_agent
except Exception:
    # 兼容旧版依赖
    from langgraph.prebuilt import create_react_agent

from tools.build_config_ops import parse_build_config
from tools.describe_ops import find_os_core_modules, list_repo_structure
from tools.file_ops import grep_in_repo, rag_search_code, read_code_segment
from tools.git_ops import (
    analyze_authors_contribution,
    analyze_git_history,
    find_symbol_first_commit,
    get_commit_diff_summary,
    get_git_history_summary,
    trace_file_evolution,
)
from tools.lsp_ops import (
    lsp_get_call_graph,
    lsp_get_definition,
    lsp_get_document_outline,
    lsp_get_references,
    lsp_set_target_arch,
)

load_dotenv()

# 默认模型配置
DEFAULT_MODEL = "deepseek/deepseek-v3.2"


DESCRIBE_REVIEW_SYSTEM_PROMPT = """你是 OS-Agent Describe 管线的**审计员**（只读评审），不是分析执行者。你评估的是**答案 JSON 作为阶段技术报告片段**的题面落实、契约与证据充分性，**不**评价参赛 OS 设计优劣。

## 唯一允许的评审对象（三者之外一律不写）
1. **题面相符**：B 中各题 `fact_answers` 与汇总 `value` 是否与 A 中对应 `stem` / `structured_facts` / `choices` 等题面约束一致、是否跑题。
2. **格式与契约**：B 是否满足 JSON-QA 输出契约（字段齐全、类型合理、枚举合法等），尤其每个 `structured_facts[].fact_id` 是否都有对应 `fact_answers[]`；`short_answer/fill_in` 的 `value` 是否为按 `structured_facts[].fact_key` 固定展开的对象。
3. **证据支撑结论**：**仅**依据 B 中 `answers[].evidence[]`、`answers[].fact_answers[].used_evidence_ids` 与对应 fact/value 是否对得上；缺证据、错引、与结论矛盾须指出。

## Feature Schema / 三态规则
- 若 A 中题目包含 `feature_schema`、`structured_facts`、`answer_contract`、`tri_state_rule`、`evidence_policy` 或 `anti_examples`，必须按这些规则审查。
- `tri_state_impl` 只允许 `implemented | stub | not_found | unknown`。
- `implemented` 不能只由 RAG/grep/search 命中支撑，必须看到实现体、调用点、状态变化、数据结构读写或流程证据。
- `not_found` 必须有结构化负向搜索证据，覆盖题目要求的关键词和目录；覆盖不足时应判为 `unknown` 或证据弱。
- `stub` 包括空实现、固定返回、ENOSYS/unsupported、todo!/unimplemented!、仅接口/trait/struct 壳。

**禁止**（出现在 `review`、`summary_zh`、`findings`、降低 `confidence`/`dimensions` 的理由中 **皆禁止**）：
- 对**参赛操作系统设计/实现**作优劣评价，除非 **stem 明确要求**判断该项且你仅核对题答与证据是否一致。
- 与上「三者」无关的扩展点评、教学建议、替代实现、生产/运维类告诫。

## 硬性规则
1. **仅依据**用户消息中的 **A**（题单）与 **B**（答案 JSON，覆写题面前版本）。**禁止**引用 A/B 之外信息或假装打开仓库。
2. **不得调用工具**；输出**仅**一个 JSON 对象（可用 ```json 围栏），不得输出围栏外解释。
3. **逐题**输出 `question_reviews`，题量与顺序须与 A 的 `questions[]` 完全一致，不得漏题或乱序。

## 逐题打分（0.00~1.00，两位小数）
**严禁无脑给高分（如全篇 0.95+）。必须拉开区分度。** 对每一题，你需要分别给出两个维度的分数：

1. **`score_evidence`（证据支撑度）**：评估 `evidence` 中的代码摘录是否能直接、有效地证明 `fact_answers` 中各 fact 的判断，并进一步支撑汇总 `value`。
   - **1.00**：证据极其详实，完全覆盖所有核对点，无多余或缺失。
   - **0.90~0.95**：至少 1 条 `evidence` 且 `excerpt` 非空，能直接支撑关键事实。
   - **0.75~0.85**：有路径/符号但 `excerpt` 过短，或需推断才能连上结论。
   - **0.50~0.70**：证据与结论关联弱，或明显欠展开。
   - **0.00~0.49**：无有效证据却下强结论，或证据与结论矛盾。
   - **硬约束**：若该题所有 `excerpt` 全为空，`score_evidence` 不得高于 0.90。

2. **`score_consistency`（题面相符度）**：评估 `fact_answers` 是否逐项覆盖题单 `structured_facts`，以及汇总 `value` 是否严格遵守 `stem` 的要求（含数量、三态、选项等）；简答/填空题还要检查 `value` 固定字段是否与 fact_key 完全一致。
   - **0.95~1.00**：完全符合题干要求，无跑题，数量/选项完全匹配。
   - **0.75~0.85**：基本符合，但有微小瑕疵（如要求列举 5 个只列了 4 个，或回答稍显敷衍）。
   - **0.00~0.49**：严重跑题，或完全未遵守题干的硬性约束（如单选题答了非选项内容）。

## 全阶段 `confidence`（**方案 A**，须与逐题自洽系统提示如下）
- 设各题的平均分 `mean_score = (score_evidence + score_consistency) / 2`。
- 全阶段 `confidence` = 所有题目的 `mean_score` 的算术平均值，保留两位小数。
- 若存在**任一**题的 `mean_score < 0.7`，则全阶段 `confidence` = `min( 上式, 0.75 )`（worst-question 截断）。

## `findings` 与 `summary_zh`
- `findings`：默认 `[]`；在明确契约/题面/证据矛盾时列入。severity：info=轻微；warn=明显不符/证据明显不足/契约违例；blocker=严重失配。禁止「评价 OS 架构不好」式 warn。
- `summary_zh`：概括在题面/契约/证据上的**报告质量**（哪类题证据薄、哪类题落实得好），**不写**设计点评。
- 当某题 `score_evidence < 0.75` 或存在证据类 finding 时，必须在该题 `question_reviews[]` 内附加 `fix_hints`，供后续 Task Agent 补证据：
  - `finding_type`: missing_evidence | weak_evidence | wrong_evidence | duplicate_evidence | contract_only
  - `missing_evidence_types`: string[]，如 definition / implementation_body / call_site / usage_flow / search
  - `recommended_keywords`: string[]，必须是后续应搜索的具体英文符号/协议/函数/模块关键词，禁止写泛泛词
  - `recommended_seed_paths`: string[]，建议搜索的 repo-relative 目录
  - `fix_goal`: string，下一轮 Task Agent 应完成的具体取证目标
- 若问题只是单选/多选/枚举格式不合规且证据足够，`finding_type` 写 `contract_only`，不要建议无关源码搜索。

## 输出 JSON 模式（字段名必须一致；`report_quality_score` 由管线后处理写入，**你方勿输出**）
{
  "schema_version": "describe_review_v1",
  "stage_id": "<与材料一致>",
  "stage_title": "<与材料一致>",
  "confidence": <0~1, 全阶段, 与方案A一致>,
  "question_reviews": [
    {
      "question_id": "<与题单及B一致>",
      "score_evidence": <0~1 本题证据支撑度>,
      "score_consistency": <0~1 本题题面相符度>,
      "review": "<中文，仅题面/契约/证据，勿评内核设计>",
      "fix_hints": {
        "finding_type": "missing_evidence|weak_evidence|wrong_evidence|duplicate_evidence|contract_only",
        "missing_evidence_types": [],
        "recommended_keywords": [],
        "recommended_seed_paths": [],
        "fix_goal": ""
      }
    }
  ],
  "findings": [],
  "summary_zh": "<中文，报告质量式概括>"
}

`question_reviews` 条数 = 题单题数，顺序 = 题单 `questions[]` 顺序。在 `summary_zh` 中**可一句话**说明全阶段分按「各题均值的方案 A 汇总」等（不展开公式细节）。
"""


def get_model_name() -> str:
    """获取模型名称，优先从环境变量读取。"""
    return os.environ.get("MODEL_NAME", DEFAULT_MODEL)


def _is_deepseek_backend(model_name: str) -> bool:
    base_url = (os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL") or "").strip()
    model_l = (model_name or "").strip().lower()
    return ("deepseek" in base_url.lower()) or model_l.startswith("deepseek-") or model_l.startswith("deepseek/")


def _apply_deepseek_thinking_defaults(model_name: str, model_kwargs: dict | None) -> dict:
    """
    DeepSeek Thinking Mode 兼容处理。

    LangChain 工具调用路径默认禁用 thinking；用户显式开启时应用补丁，确保
    reasoning_content 能在后续请求中被回传。
    """
    mk = deepcopy(model_kwargs or {})
    if not _is_deepseek_backend(model_name):
        return mk

    thinking = (os.environ.get("OS_AGENT_DEEPSEEK_THINKING") or "").strip().lower()
    extra_body = dict(mk.get("extra_body") or {})

    if thinking in ("", "0", "false", "no", "off", "disabled"):
        extra_body.setdefault("thinking", {"type": "disabled"})
    else:
        apply_deepseek_reasoning_content_patch()
        extra_body.setdefault("thinking", {"type": "enabled"})
        effort = (os.environ.get("OS_AGENT_DEEPSEEK_REASONING_EFFORT") or "").strip().lower()
        if effort:
            mk.setdefault("reasoning_effort", effort)

    mk["extra_body"] = extra_body
    return mk


def build_chat_model(
    model: str = None,
    *,
    temperature: float = 0,
    request_timeout: int = 240,
    max_retries: int = 2,
    model_kwargs: dict | None = None,
):
    model_name = model or get_model_name()
    merged_kwargs = _apply_deepseek_thinking_defaults(model_name, model_kwargs)
    is_deepseek = _is_deepseek_backend(model_name)

    _mot = (os.environ.get("DESCRIBE_MAX_OUTPUT_TOKENS") or "").strip()
    configured_max_tokens = None
    if _mot.isdigit():
        configured_max_tokens = int(_mot)
    elif isinstance(merged_kwargs, dict) and "max_tokens" in merged_kwargs:
        configured_max_tokens = merged_kwargs.get("max_tokens")

    extra_body = None
    if isinstance(merged_kwargs, dict) and "extra_body" in merged_kwargs:
        extra_body = merged_kwargs.pop("extra_body")

    max_tokens = None
    if isinstance(merged_kwargs, dict) and "max_tokens" in merged_kwargs:
        merged_kwargs.pop("max_tokens")
    if configured_max_tokens is not None:
        if is_deepseek:
            extra_body = dict(extra_body or {})
            extra_body["max_tokens"] = int(configured_max_tokens)
        else:
            max_tokens = int(configured_max_tokens)

    llm_kwargs: dict = dict(
        model=model_name,
        temperature=temperature,
        request_timeout=request_timeout,
        max_retries=max_retries,
        extra_body=extra_body,
        model_kwargs=merged_kwargs,
    )
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**llm_kwargs)


def get_task_agent_tools(task_type: str, stage_id: str = ""):
    """Return a restricted tool set for Multi-Agent task workers."""
    task_type = (task_type or "").strip().lower()
    if task_type in {"react_rag", "discovery", "implementation_state", "rag"}:
        return _with_task_tool_runtime([
            rag_search_code,
            grep_in_repo,
            find_os_core_modules,
            read_code_segment,
        ])
    if task_type in {"react_code", "code_evidence", "code", "read"}:
        return _with_task_tool_runtime([
            rag_search_code,
            grep_in_repo,
            find_os_core_modules,
            read_code_segment,
            lsp_get_definition,
            lsp_get_references,
            lsp_get_document_outline,
        ])
    if task_type in {"react_lsp", "definition", "flow", "lsp"}:
        return _with_task_tool_runtime([
            rag_search_code,
            grep_in_repo,
            read_code_segment,
            lsp_get_definition,
            lsp_get_references,
            lsp_get_document_outline,
            lsp_get_call_graph,
            lsp_set_target_arch,
        ])
    if task_type in {"react_build", "build_platform", "platform", "build"}:
        return _with_task_tool_runtime([list_repo_structure, read_code_segment, grep_in_repo, parse_build_config])
    if task_type in {"react_history", "git_history", "history"}:
        return _with_task_tool_runtime([
            get_git_history_summary,
            analyze_git_history,
            find_symbol_first_commit,
            trace_file_evolution,
            analyze_authors_contribution,
            get_commit_diff_summary,
        ])
    return _with_task_tool_runtime([
        rag_search_code,
        grep_in_repo,
        find_os_core_modules,
        read_code_segment,
        lsp_get_definition,
        lsp_get_references,
        lsp_get_document_outline,
    ])


def _tool_name(tool) -> str:
    return getattr(tool, "name", getattr(tool, "__name__", ""))


def _with_task_tool_runtime(tools: list):
    return [_wrap_task_tool_runtime(tool) for tool in tools]


def _wrap_task_tool_runtime(tool):
    name = _tool_name(tool)

    def _runtime_tool(**kwargs):
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        allowed, reason, metadata = _record_tool_call_or_block(name, kwargs)
        if not allowed:
            emit_task_tool_event("tool_blocked", reason, level="warn", metadata=metadata)
            return f"Error: {reason}"

        emit_task_tool_event("tool_start", _tool_preview(name, kwargs), metadata=metadata)
        try:
            if name.startswith("lsp_"):
                with lsp_tool_guard(name):
                    result = _invoke_wrapped_tool(tool, kwargs)
            elif name == "rag_search_code":
                with rag_tool_guard():
                    result = _invoke_wrapped_tool(tool, kwargs)
            else:
                result = _invoke_wrapped_tool(tool, kwargs)
            emit_task_tool_event(
                "tool_done",
                _tool_result_preview(name, result),
                metadata={**metadata, "result_chars": len(str(result)), "result_excerpt": str(result)[:5000]},
            )
            return result
        except Exception as exc:
            emit_task_tool_event(
                "tool_error",
                f"{name}: {type(exc).__name__}: {exc}",
                level="warn",
                metadata=metadata,
            )
            raise

    return StructuredTool.from_function(
        func=_runtime_tool,
        name=name,
        description=getattr(tool, "description", None) or getattr(tool, "__doc__", "") or name,
        args_schema=getattr(tool, "args_schema", None),
        return_direct=getattr(tool, "return_direct", False),
    )


def _invoke_wrapped_tool(tool, kwargs: dict):
    if hasattr(tool, "invoke"):
        return tool.invoke(kwargs)
    return tool(**kwargs)


def _env_int(name: str, default: int) -> int:
    try:
        value = int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        value = default
    return max(1, value)


def _record_tool_call_or_block(tool_name: str, tool_args: dict) -> tuple[bool, str, dict]:
    ctx = current_task_event_context()
    metadata = {
        "tool_name": tool_name,
        "tool_args": _compact_tool_args(tool_args),
    }
    if not ctx:
        return True, "", metadata

    ctx["tool_call_count"] = int(ctx.get("tool_call_count") or 0) + 1
    metadata["tool_call_count"] = ctx["tool_call_count"]
    budget = _env_int("OS_AGENT_TASK_AGENT_BUDGET", 30)
    max_calls = budget
    if ctx["tool_call_count"] > max_calls:
        return False, f"Task Agent tool-call limit exceeded: {ctx['tool_call_count']}/{max_calls}", metadata

    sig = _tool_signature(tool_name, tool_args)
    metadata["tool_signature"] = sig
    history = ctx.setdefault("tool_signature_history", [])
    history.append(sig)
    del history[:-12]
    loop = _detect_tool_loop(history)
    if loop:
        metadata.update(loop)
        return False, f"Repeated tool-action loop blocked: pattern={loop['pattern']} length={loop['pattern_length']}", metadata

    return True, "", metadata


def _tool_signature(tool_name: str, tool_args: dict) -> str:
    payload = json.dumps(_compact_tool_args(tool_args), ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{tool_name}:{digest}"


def _detect_tool_loop(history: list[str]) -> dict:
    # AAA: same tool+args three times in a row.
    if len(history) >= 3 and len(set(history[-3:])) == 1:
        return {"pattern": "AAA", "pattern_length": 3}

    # ABABAB / ABCABCABC: short periodic loops with non-identical actions.
    for period in (2, 3):
        window = period * 3
        if len(history) < window:
            continue
        tail = history[-window:]
        unit = tail[:period]
        if len(set(unit)) < period:
            continue
        if tail == unit * 3:
            return {"pattern": "".join(chr(ord("A") + i) for i in range(period)) * 3, "pattern_length": window}
    return {}


def _compact_tool_args(tool_args: dict) -> dict:
    compact = {}
    for key, value in (tool_args or {}).items():
        text = str(value)
        compact[str(key)] = text[:240] + "..." if len(text) > 240 else value
    return compact


def _tool_preview(tool_name: str, tool_args: dict) -> str:
    try:
        from core.utils import format_tool_call_summary

        return format_tool_call_summary(tool_name, tool_args)
    except Exception:
        return f"{tool_name} {json.dumps(_compact_tool_args(tool_args), ensure_ascii=False)[:240]}"


def _tool_result_preview(tool_name: str, result) -> str:
    text = str(result)
    try:
        from core.utils import format_tool_result_summary

        return format_tool_result_summary(tool_name, text)
    except Exception:
        return f"{tool_name} result chars={len(text)}"


def build_task_agent(model: str = None, task_type: str = "", stage_id: str = ""):
    """Build a restricted ReAct agent for one Multi-Agent task type."""
    llm = build_chat_model(model=model, temperature=0)
    return create_react_agent(llm, get_task_agent_tools(task_type, stage_id))


def build_task_agent_with_tools(*, stage_id: str = "", tools: list | None = None, model: str = None):
    """Build a Task ReAct agent with an already-filtered tool set.

    Task planning decides the task type, then Task Builder may narrow the
    allowed tools per task. This entry keeps that filtered tool set intact.
    """
    llm = build_chat_model(model=model, temperature=0)
    return create_react_agent(llm, tools or get_task_agent_tools("", stage_id))
