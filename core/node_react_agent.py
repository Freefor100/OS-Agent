from __future__ import annotations

import json
import os
import gc
import threading
import time
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


_MODEL_SEMAPHORE: threading.BoundedSemaphore | None = None
_MODEL_SEMAPHORE_LOCK = threading.Lock()


def _model_semaphore() -> threading.BoundedSemaphore:
    global _MODEL_SEMAPHORE
    with _MODEL_SEMAPHORE_LOCK:
        if _MODEL_SEMAPHORE is None:
            _MODEL_SEMAPHORE = threading.BoundedSemaphore(max(1, int(os.environ.get("AGENT_D_LLM_CONCURRENCY", "2"))))
        return _MODEL_SEMAPHORE


def _process_rss_gb() -> float:
    if os.name != "nt":
        try:
            import resource

            raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return raw / (1024 * 1024) if raw > 1024 * 1024 else raw / 1024
        except Exception:
            return 0.0
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return float(counters.WorkingSetSize) / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def _enforce_memory_budget() -> None:
    # Optional emergency guard only. Correctness relies on bounded live state
    # and immediate persistence, so normal runs do not need a memory limit.
    limit = max(0.0, float(os.environ.get("AGENT_D_MEMORY_SOFT_LIMIT_GB", "0")))
    if not limit:
        return
    rss = _process_rss_gb()
    if rss <= limit:
        return
    gc.collect()
    wait_seconds = max(0.0, float(os.environ.get("AGENT_D_MEMORY_WAIT_SECONDS", "20")))
    deadline = time.time() + wait_seconds
    while _process_rss_gb() > limit and time.time() < deadline:
        time.sleep(0.5)
        gc.collect()
    rss = _process_rss_gb()
    if rss > limit:
        raise MemoryError(
            f"Agent D RSS {rss:.2f} GB exceeds AGENT_D_MEMORY_SOFT_LIMIT_GB={limit:.2f}; "
            "checkpoint/message state must be compacted before more LLM calls."
        )


class ClaimDraft(BaseModel):
    canonical_tag: str
    claim_type: str = "mechanism"
    statement_zh: str
    statement_en: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    maturity: Literal["textbook", "simplified", "production"] = "simplified"


class DependencyDraft(BaseModel):
    dst: str
    relation: str = "depends_on"
    reason_zh: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class FlowStepDraft(BaseModel):
    role: str
    symbol: str = ""
    evidence_id: str


class FlowDraft(BaseModel):
    title_zh: str
    title_en: str
    role_sequence: list[str] = Field(default_factory=list)
    steps: list[FlowStepDraft] = Field(default_factory=list)


class ExtensionRequestDraft(BaseModel):
    tag: str
    reason: str


class ArchitectureDraft(BaseModel):
    architecture_name: str
    design_highlights: str
    mermaid_graph: str


class NodeDraft(BaseModel):
    status: Literal["implemented", "partial", "not_found", "unknown"]
    confidence: Literal["high", "medium", "low"] = "medium"
    summary_zh: str = ""
    summary_en: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    mechanisms: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    data_structures: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    negative_features: list[str] = Field(default_factory=list)
    design_choices: list[str] = Field(default_factory=list)
    claims: list[ClaimDraft] = Field(default_factory=list, max_length=4)
    dependencies: list[DependencyDraft] = Field(default_factory=list, max_length=2)
    flows: list[FlowDraft] = Field(default_factory=list, max_length=2)
    extension_requests: list[ExtensionRequestDraft] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class DeepSeekChatOpenAI:
    """Factory for a ChatOpenAI adapter that preserves DeepSeek reasoning_content."""

    @staticmethod
    def build():
        from langchain_openai import ChatOpenAI

        class ReasoningChatOpenAI(ChatOpenAI):
            def _generate(self, *args, **kwargs):
                with _model_semaphore():
                    _enforce_memory_budget()
                    return super()._generate(*args, **kwargs)

            def _create_chat_result(self, response, generation_info=None):
                response_dict = response if isinstance(response, dict) else response.model_dump()
                result = super()._create_chat_result(response, generation_info)
                for choice, generation in zip(response_dict.get("choices") or [], result.generations):
                    reasoning = (choice.get("message") or {}).get("reasoning_content")
                    if reasoning:
                        generation.message.additional_kwargs["reasoning_content"] = reasoning
                return result

            def _get_request_payload(self, input_, *, stop=None, **kwargs):
                payload = super()._get_request_payload(input_, stop=stop, **kwargs)
                if "deepseek" in str(self.model_name).lower() and "max_completion_tokens" in payload:
                    payload["max_tokens"] = payload.pop("max_completion_tokens")
                if os.environ.get("AGENT_D_THINKING", "enabled").strip().lower() in {"enabled", "on", "true", "1", "max"}:
                    # DeepSeek thinking supports tool calls, but rejects forced
                    # tool_choice values used by structured-output strategies.
                    payload.pop("tool_choice", None)
                messages = self._convert_input(input_).to_messages()
                for source, target in zip(messages, payload.get("messages") or []):
                    reasoning = getattr(source, "additional_kwargs", {}).get("reasoning_content")
                    if reasoning and target.get("role") == "assistant":
                        target["reasoning_content"] = reasoning
                return payload

        thinking = os.environ.get("AGENT_D_THINKING", "enabled").strip().lower()
        reasoning_effort = os.environ.get("AGENT_D_REASONING_EFFORT", "high").strip()
        extra_body: dict[str, Any] = {}
        kwargs: dict[str, Any] = {
            "model": os.environ.get("MODEL_NAME") or "gpt-4o-mini",
            "api_key": os.environ.get("OPENAI_API_KEY", ""),
            "base_url": os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
            "timeout": float(os.environ.get("AGENT_D_LLM_TIMEOUT_SECONDS", "180")),
            "max_retries": int(os.environ.get("AGENT_D_LLM_RETRY_MAX", "3")),
            "max_tokens": int(os.environ.get("AGENT_D_MAX_OUTPUT_TOKENS", "32768")),
        }
        if thinking in {"enabled", "on", "true", "1", "max"}:
            extra_body["thinking"] = {"type": "enabled"}
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
        elif thinking in {"disabled", "off", "false", "0"}:
            extra_body["thinking"] = {"type": "disabled"}
        if extra_body:
            kwargs["extra_body"] = extra_body
        return ReasoningChatOpenAI(**kwargs)


def run_node_react_agent(
    *,
    node_id: str,
    node_context: dict[str, Any],
    execute_request: Callable[[dict[str, Any], str], dict[str, Any]],
    checkpointer: Any = None,
    thread_id: str,
    verifier_feedback: list[str] | None = None,
    recorder: Any = None,
) -> dict[str, Any]:
    """Run one autonomous LangChain tool-calling agent and return NodeDraft."""

    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.tools import StructuredTool

    class RecorderCallback(BaseCallbackHandler):
        def on_llm_start(self, serialized, prompts, **kwargs):
            if recorder:
                recorder.graph_event("llm_start", node_id=node_id, phase="react")

        def on_llm_end(self, response, **kwargs):
            usage: dict[str, Any] = {}
            try:
                message = response.generations[0][0].message
                usage = dict(message.usage_metadata or {})
            except Exception:
                pass
            if recorder:
                recorder.llm_call({"template_id": f"langchain_node:{node_id}", "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }})

    observations: list[dict[str, Any]] = []

    def call_tool(tool: str, **kwargs: Any) -> str:
        if recorder:
            recorder.graph_event("tool_start", node_id=node_id, phase="tool", data={"active_tool": tool, "tool": tool})
        result = execute_request({"tool": tool, **kwargs}, "langchain_react")
        observations.append(_compact_observation(result))
        del observations[:-24]
        return json.dumps(result, ensure_ascii=False, default=str)

    def glossary_lookup(query: str) -> str:
        """Look up a mechanism definition, boundaries, recognition cues, and generic examples. Never evidence."""
        return call_tool("glossary_lookup", query=query)

    def atlas_search(query: str, limit: int = 12) -> str:
        """Search the compact code atlas for navigation hints. Atlas results are never strong evidence."""
        return call_tool("atlas_search", query=query, limit=limit)

    def atlas_symbol(symbol: str) -> str:
        """Inspect one atlas symbol summary for navigation only."""
        return call_tool("atlas_symbol", symbol=symbol)

    def atlas_neighbors(symbol: str) -> str:
        """Inspect rough atlas neighbors for navigation only."""
        return call_tool("atlas_neighbors", symbol=symbol)

    def atlas_fingerprint(symbol: str) -> str:
        """Inspect a normalized structural fingerprint for navigation/comparison hints only."""
        return call_tool("atlas_fingerprint", symbol=symbol)

    def read_symbol(symbol: str) -> str:
        """Read and verify source definitions matching a semantic symbol."""
        return call_tool("read_symbol", symbol=symbol)

    def read_path(path: str, line: int = 1, symbol: str = "") -> str:
        """Read and verify a source, config, linker, or assembly location."""
        return call_tool("read_path", path=path, line=line, symbol=symbol)

    def grep(query: str) -> str:
        """Search source text for a semantic cue and return verified source locations."""
        return call_tool("grep", query=query)

    def lsp_definition(path: str, symbol: str, line: int = 1) -> str:
        """Resolve a symbol definition using LSP."""
        return call_tool("lsp_definition", path=path, symbol=symbol, line=line)

    def lsp_references(path: str, symbol: str, line: int = 1) -> str:
        """Find symbol references using LSP."""
        return call_tool("lsp_references", path=path, symbol=symbol, line=line)

    def call_graph(path: str, symbol: str, line: int = 1) -> str:
        """Trace a symbol call graph using LSP."""
        return call_tool("call_graph", path=path, symbol=symbol, line=line)

    def negative_search(query: str) -> str:
        """Prove a feature is absent with a verified repository-wide negative search."""
        return call_tool("negative_search", query=query)

    def git_history() -> str:
        """Read verified recent commits and module-oriented git history for EvolutionHistory."""
        return call_tool("git_history")

    def git_history_drill(path_filter: str) -> str:
        """Drill into one subsystem's git history by repo path (e.g. 'kernel/fs'). EvolutionHistory only."""
        return call_tool("git_history", query=path_filter)

    def trace_file_evolution(file_path: str) -> str:
        """Trace one file's commit lifecycle (rename-aware, churn only). EvolutionHistory only."""
        return call_tool("trace_file_evolution", path=file_path)

    def symbol_first_commit(symbol: str) -> str:
        """Find the first commit that introduced a symbol/keyword (pickaxe). EvolutionHistory only."""
        return call_tool("symbol_first_commit", query=symbol)

    def commit_diff(commit_sha: str) -> str:
        """Inspect one commit's minimal, comment-stripped diff. EvolutionHistory only."""
        return call_tool("commit_diff", query=commit_sha)

    tools = [
        StructuredTool.from_function(fn)
        for fn in (
            glossary_lookup,
            atlas_search,
            atlas_symbol,
            atlas_neighbors,
            atlas_fingerprint,
            read_symbol,
            read_path,
            grep,
            lsp_definition,
            lsp_references,
            call_graph,
            negative_search,
            git_history,
            git_history_drill,
            trace_file_evolution,
            symbol_first_commit,
            commit_diff,
        )
    ]
    system_prompt = (
        "你是 Agent D 的内核叶子节点深读 Agent。你必须自主使用工具阅读源码、定义、引用和调用图，"
        "然后提交结构化 NodeDraft。候选词和 CodeAtlas 只是导航提示，不能作为 claim evidence。"
        "implemented/partial claim 必须引用工具生成的 verified strong evidence_id；not_found 必须引用"
        " negative_search evidence。注意概念卡的 include/exclude/confusions。"
        "每个 claim 必须基于证据判断 maturity 成熟度："
        "textbook=教科书/原型级最小实现（如 xv6 的 round-robin、free-list）；"
        "simplified=有一定工程化但简化的实现；production=生产级完整实现（如 CFS 红黑树、buddy+slab、RCU）。"
        "【特定硬件属性处理】禁止在候选词或声明中捏造或硬编码任何特定芯片/板子特有特性（如 thead_c906_pbmt 属性、cv1811h_sdcard 等）。"
        "如果工具发现了特定芯片的定制（如特殊页表最高位属性、PIO外设轮询），必须在 extension_requests 中通过 extension:<feature>（如 extension:custom_pte_attributes, extension:pio_device_io）动态声明扩展标签，并绑定其源码强证据。"
        "【Mock/Stub 审查原则】严防 Mock 伪装的桩函数。若系统调用仅包含空体、硬编码返回值（如直接 return 0/1/0xAA）、或在 shm 中映射完全隔离的私有进程内存，该节点的状态绝对不能判定为 implemented，必须降级为 partial 或 not_found，并且必须在 summary_zh 和 claim 描述中包含 'Mock 伪装实现 (Stub / Placeholder)' 关键字，写明在真实多进程/多线程通信下的失效性质。"
        "【ArceOS 与自研内核表征】必须精确区分 ArceOS 组件封装与自研单体内核。若发现是基于 ArceOS 组件包（如 axtask、axmem、axfs），请说明这仅是独核（Unikernel）底座的包装层，并非自主研发的抢占式调度与页表管理。"
        "【异步调度表征】识别异步协程调度模型。若是这类设计，请说明进程/线程以 Future 形式运行且在协作式出让点出让，而非传统的时钟中断抢占调度。"
        "不要输出内部思维链。"
    )
    agent = create_agent(
        DeepSeekChatOpenAI.build(),
        tools,
        system_prompt=system_prompt,
        response_format=ToolStrategy(NodeDraft),
        # Full LangChain message checkpoints duplicate every source/tool result
        # and reasoning_content at each ReAct step. Evidence and behavior are
        # already durable in JSONL, so interrupted nodes restart from their
        # compact node boundary instead of deserializing an unbounded chat log.
        checkpointer=None,
        name=f"agent_d_{node_id.replace('.', '_')}",
    )
    payload = {
        "node_context": node_context,
        "verifier_feedback": verifier_feedback or [],
        "instruction": (
            "自由 ReAct 探索当前节点。需要时调用工具；证据足够后提交 NodeDraft。"
            "只引用工具返回的 evidence_id，不要把 glossary 或 atlas 当证据。"
            "探索预算有限；接近预算时必须基于已有 evidence 提交 NodeDraft。"
            "若确认机制不存在，调用 negative_search 后提交 not_found/unknown，不要无限搜索。"
        ),
    }
    started = time.time()
    max_steps = max(4, int(os.environ.get("AGENT_D_REACT_MAX_STEPS", "40")))
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": max_steps * 2 + 8,
                "callbacks": [RecorderCallback()],
            },
        )
    except Exception as exc:
        if type(exc).__name__ != "GraphRecursionError":
            raise
        if recorder:
            recorder.graph_event(
                "react_budget_exhausted",
                node_id=node_id,
                phase="commit",
                data={"summary": f"ReAct reached {max_steps} steps; forcing NodeCommitter"},
            )
        draft = _force_node_commit(
            node_id=node_id,
            node_context=node_context,
            verifier_feedback=[
                *(verifier_feedback or []),
                f"ReAct exploration reached its {max_steps}-step budget; commit from existing evidence now.",
            ],
            observations=observations,
            recorder=recorder,
        )
        if recorder:
            recorder.graph_event("node_draft", node_id=node_id, phase="verifier", data={"elapsed_seconds": round(time.time() - started, 3)})
        return draft.model_dump(mode="json")
    draft = result.get("structured_response")
    if draft is None:
        draft = _force_node_commit(
            node_id=node_id,
            node_context=node_context,
            verifier_feedback=verifier_feedback or [],
            observations=observations,
            recorder=recorder,
        )
    if recorder:
        recorder.graph_event("node_draft", node_id=node_id, phase="verifier", data={"elapsed_seconds": round(time.time() - started, 3)})
    return draft.model_dump(mode="json") if hasattr(draft, "model_dump") else dict(draft)


def _force_node_commit(
    *,
    node_id: str,
    node_context: dict[str, Any],
    verifier_feedback: list[str],
    observations: list[dict[str, Any]],
    recorder: Any,
) -> NodeDraft:
    """Ask the LLM to commit after exploration when it forgot ToolStrategy."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from core.llm.backend import parse_llm_json

    payload = {
        "node_id": node_id,
        "node_context": node_context,
        "verified_tool_observations": observations,
        "verifier_feedback": verifier_feedback,
        "output_schema": NodeDraft.model_json_schema(),
    }
    system = (
        "你是 Agent D NodeCommitter。探索已经结束，不允许继续调用工具。"
        "只根据输入中的 verified evidence 生成一个 NodeDraft JSON；不得创造 evidence_id。"
        "证据不足时使用 unknown，确认缺失且有 negative_search 时使用 not_found。"
        "只输出 JSON，不输出解释或思维链。"
    )
    model = DeepSeekChatOpenAI.build()
    response = model.invoke([
        SystemMessage(content=system),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
    ])
    content = str(getattr(response, "content", "") or "")
    if recorder:
        usage = dict(getattr(response, "usage_metadata", {}) or {})
        recorder.llm_call({"template_id": f"langchain_node:{node_id}", "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }})
        recorder.graph_event("forced_node_commit", node_id=node_id, phase="commit")
    try:
        return NodeDraft.model_validate(parse_llm_json(content))
    except Exception as exc:
        raise RuntimeError(
            f"LangChain node agent {node_id} returned no structured_response and forced commit failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def _compact_observation(result: dict[str, Any]) -> dict[str, Any]:
    evidence = []
    for row in result.get("evidence") or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        if item.get("excerpt"):
            item["excerpt"] = str(item["excerpt"])[:900]
        evidence.append(item)
    return {
        "tool": result.get("tool"),
        "added_evidence_ids": list(result.get("added_evidence_ids") or [])[:16],
        "concept_results": list(result.get("concept_results") or [])[:8],
        "evidence": evidence[:16],
    }


def run_architecture_react_agent(
    *,
    repo_path: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    from langchain.agents import create_tool_calling_agent, AgentExecutor
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.tools import StructuredTool
    from tools.file_ops import list_directory, read_code_segment, grep_in_repo
    import re

    def list_dir(dir_path: str = "") -> str:
        """List contents of a directory within the repository."""
        return list_directory(repo_path, dir_path)

    def read_doc(file_path: str) -> str:
        """Read text from a markdown, pdf, txt, or source file."""
        return read_code_segment(os.path.join(repo_path, file_path))

    def grep(pattern: str, file_extensions: str = "") -> str:
        """Search repository files for a keyword or regex pattern."""
        exts = file_extensions if file_extensions else None
        return grep_in_repo(repo_path, pattern, max_results=30, file_extensions=exts)

    tools = [
        StructuredTool.from_function(list_dir),
        StructuredTool.from_function(read_doc),
        StructuredTool.from_function(grep),
    ]

    system_prompt = (
        "你是一个资深的操作系统架构分析师。你的任务是为当前评测的 OS 项目输出一幅 Mermaid 格式的内核架构图。\n\n"
        "已知当前项目的模块和依赖事实：\n{context}\n\n"
        "你的行动指南：\n"
        "1. 使用 list_dir 工具探索项目根目录，观察它的目录划分（例如：是否将驱动独立成库？文件系统是 VFS 还是写死在内核侧？这是传统宏内核还是类似 ArceOS 的组件化库OS？）。\n"
        "2. 寻找并使用 read_doc 阅读设计文档（如 README.md、docs/ 目录下的 md、txt）。找出作者自己声明的架构划分和设计亮点。\n"
        "3. 结合传入的已知机制列表（如 sv39, buddy_allocator 等），把这些作为标签（Badge）融入到你即将画出的架构图的各个模块节点中。\n"
        "4. 使用 `graph TD` 语法的 Mermaid 文本绘制出能反映该项目真实物理和逻辑分层的架构图。\n\n"
        "请调用你的工具去完成分析，不要猜测。分析完成后，由于你需要输出 JSON 结构，所以最后请输出以下格式（在思考和分析完成后）：\n"
        "```json\n"
        "{{\n"
        '  "architecture_name": "名称",\n'
        '  "design_highlights": "设计亮点总结",\n'
        '  "mermaid_graph": "graph TD\\n..."\n'
        "}}\n"
        "```"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("placeholder", "{agent_scratchpad}"),
    ])
    
    agent = create_tool_calling_agent(DeepSeekChatOpenAI.build(), tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False, max_iterations=10)
    
    try:
        response = agent_executor.invoke({"context": json.dumps(context, ensure_ascii=False)})
        output_str = response.get("output", "")
        # Extract JSON from output
        json_match = re.search(r"```json\s*(.*?)\s*```", output_str, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        # Fallback to general `{` parse
        start = output_str.find("{")
        end = output_str.rfind("}")
        if start != -1 and end != -1:
            return json.loads(output_str[start:end+1])
        return {}
    except Exception as exc:
        print(f"Error in ArchitectureGenerator: {exc}")
        return {}
