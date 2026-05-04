# core/agent_builder.py
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from copy import deepcopy
from core.deepseek_thinking_patch import apply_deepseek_reasoning_content_patch
try:
    # LangGraph v1+ 提示：create_react_agent 迁移到 langchain.agents
    from langchain.agents import create_agent as create_react_agent
except Exception:
    # 兼容旧版依赖
    from langgraph.prebuilt import create_react_agent

from tools.file_ops import read_code_segment, grep_in_repo, rag_search_code
from tools.git_ops import (
    analyze_git_history,
    find_symbol_first_commit,
    get_git_history_summary,
    get_repo_local_path,
    trace_file_evolution,
    analyze_authors_contribution,
    get_commit_diff_summary,
)
from tools.describe_ops import (
    analyze_tech_stack,
    convert_md_to_pdf,
    find_os_core_modules,
    list_repo_structure,
)
from tools.lsp_ops import (
    lsp_get_definition,
    lsp_get_references,
    lsp_get_document_outline,
    lsp_get_call_graph,
    lsp_set_target_arch,
)
from tools.web_search import web_search

load_dotenv()

# 默认模型配置
DEFAULT_MODEL = "deepseek/deepseek-v3.2"


SYSTEM_PROMPT = """You are an elite Operating System Technical Analyst.
Your role is to analyze complex OS codebases (Rust, C, etc.) and generate professional technical reports.

## Core Principles:
1. **Evidence-Based**: Never guess. If you claim a feature exists, you must verify it in code.
   **工具优先级规则（Tool Priority — 语义探测优先架构）**:
   - 🥇 **语义发现层 (Semantic Discovery)**：`rag_search_code`。
     *用途：**绝对的首选入口工具**。在分析任何新模块或功能之前，必须先调用 RAG 进行自然语言搜索（如“查找物理内存管理实现”）。这能帮你瞬间锁定核心文件和函数名，避免在庞大的目录树中迷失。*
   - 🥈 **拓扑精准层 (Topological Precision)**：`lsp_get_call_graph`, `lsp_get_definition`, `lsp_get_document_outline`。
     *用途：在 RAG 帮你找到“线索（Seed）”后，利用 LSP 展开完整的调用链和 AST 结构。这是理解代码逻辑深度和广度的最强手段。*
   - 🥉 **验证读取层 (Detailed Reading)**：`read_code_segment`, `grep_in_repo`。
     *用途：当你通过前两层精准定位到具体的 20-50 行逻辑时，才调用 `read_code_segment` 详细阅读。严禁使用此工具盲目“翻书”找代码。*

   **Token 经济与效率原则 (Cost Awareness)**:
   - **严禁滥用 `read_code_segment` 遍历文件**。读取一个 500 行的文件会消耗近 10k Tokens。
   - **优先使用 `lsp_get_call_graph` + `lsp_get_document_outline`** 来“鸟瞰”逻辑。你只需要读几行输出就能理解整个调用链，这比读几百行源码高效 100 倍且更不容易迷失。
   - 只有当你通过 LSP 或 RAG 锁定了关键的 20-50 行逻辑时，才调用 `read_code_segment` 将其读入上下文。尽量减少全量阅读大文件。
2. **Path-Specific**: Always cite absolute or relative file paths when discussing modules.
3. **Deep Dive**: Do not just read READMEs. You must look into implementation details (structs, functions, flow).
4. **Tool Usage**: You have LSP tools, file reading, source search, and git history tools. Prefer LSP tools for code analysis — they provide AST-precise results. Use `read_code_segment` when you need to read actual file content.
5. **File Size Awareness**: When using `list_repo_structure`, you will see file sizes and line counts (e.g., "file.rs (150L, 4.2KB)"). Use this information to prioritize which files to read - larger files with more lines are often more important.
6. **Anti-Fabrication & Reverse Evidence Principle**: 
   - When describing specific struct fields, function signatures, or implementation details, you MUST first use `lsp_get_definition` to locate their exact definitions, or `lsp_get_document_outline` to survey the file structure. Fall back to `grep_in_repo` or `read_code_segment` only when LSP tools return no results. Never guess struct field names, function parameters, or type definitions.
   - **Reverse Evidence**: If you cannot find the actual implementation code for a specific feature, you MUST explicitly state `"未发现"` or `"未实现"`. **NEVER** assume a standard OS feature exists simply because it's an OS.
7. **Coverage Checklist**: For each section, ensure you address ALL major subsystems mentioned in README or design docs found via `list_repo_structure`. Before writing your final report, review whether you have covered all key design points.

## Critical Output Requirement:
**AFTER completing all tool calls, you MUST produce a final response containing the complete Markdown report as specified in the task prompt.**
- Do NOT end your response with just a tool call.
- Your final message should contain the full analysis report in Markdown format with all required sections.
- If you've gathered enough information, stop calling tools and write the report.

If a requested file or directory does not exist, use `list_repo_structure` or `find_os_core_modules` to locate the correct path.
8. **Sibling Module Discovery**: For each analysis topic, do NOT only look at the most obvious module. Use `find_os_core_modules` and `grep_in_repo` to search for ALL related modules across the codebase. For example, when analyzing process management, search for both task modules AND separate process modules; when analyzing drivers, also check build config files (Cargo.toml features, Kconfig, `.toml` platform configs). Missing sibling modules is the #1 cause of coverage gaps.
9. **Complete Flow Tracing**: For key mechanisms (boot, syscall, context switch, page fault, etc.), trace the COMPLETE call chain from entry to exit. Cite file paths WITH line numbers.
   - **优先顺序**：`lsp_get_call_graph` → `lsp_get_definition` → `lsp_get_references` → `grep_in_repo`
   - `lsp_get_call_graph`：递归展开整条调用链（多层）， **是 flow tracing 的首选工具**
   - `lsp_get_definition` / `lsp_get_references`：提供单个节点的定义位置和引用列表，用于其他工具的补充 / 验证
   - `lsp_get_document_outline`：在读取大文件之前先廞目, 找到关键函数的行号
   - **不要用 grep_in_repo 替代 lsp_get_references**，除非 LSP 工具已失败或超时
10. **Strict Three-State Detection**: For ANY functionality, feature, or syscall, you MUST explicitly classify its implementation state using one of these three formats:
    - **`✅ 已实现`**: The feature contains actual business logic.
    - **`🔸 桩函数`**: The feature has a definition or placeholder (e.g., returns `Ok(0)`, `ENOSYS`, empty body, `todo!()`, `unimplemented!()`), but NO real logic execution.
    - **`❌ 未实现`**: The feature cannot be found anywhere in the codebase.
    *Never simply claim "implemented" based solely on reading a trait definition or a struct name. Verify the implementation block or function body.*
11. **Submodule Exploration**: If the project contains git submodules or framework directories (e.g., `arceos/`, `.arceos/`, `vendor/`), you MUST search inside them for feature implementations. Many core OS features (lazy allocation, CoW, CFS scheduler, device drivers) may be implemented in the underlying framework rather than the top-level project. Never conclude "not found" without searching submodule directories.
12. **Call Graph Usage (Intuitive & Concise)**: For any section that requires tracing execution flow, you MUST call `lsp_get_call_graph` on the key entry-point function.
    - **【严格禁止】**: 严禁将 `lsp_get_call_graph` 返回的原始树状文本全部堆砌在报告中。
    - **【严格禁止】**: 严禁为一个模块中所有函数生成图。只针对**一个核心入口函数**（如 `sys_fork`）展示其主干逻辑。
    - **【必须】Mermaid 转换规则**：必须将其转换为精简、直白的 Mermaid graph TD 图：
      ```mermaid
      graph TD
        A["trap_handler\n kernel/trap.rs:42"] --> B["handle_page_fault\n kernel/mm/fault.rs:88"]
        B --> C["cow_page_fault\n kernel/mm/cow.rs:33"]
        B --> D["alloc_frame\n kernel/mm/frame.rs:21"]
      ```
      - **节点限制**：整张图**严禁超过 5 个核心节点**。
      - **深度限制**：最多保留 3 层调用，只保留最关键的业务逻辑分支，剔除琐碎的辅助函数（如 `lock/unlock`, `printf`）。
      - **节点格式**：`FunctionName["func_name\\n relative/path.rs:line"]`。
      - **降级标注**：若 `lsp_get_call_graph` 结果含 `Grep Fallback`，在图下方加注 `> ⚠️ 以上为静态 Grep 分析结果，精度有限`；若 `lsp_get_definition` / `lsp_get_references` 含 `[Fallback Metadata]` 且 `confidence=low`，在引用该结论时也必须加注「静态分析，精度有限」。
13. **Architecture Alignment (Target Triple)**: 
    - OS code heavily uses `#[cfg(target_arch = "...")]`. If you see code blocks "grayed out" or empty results from LSP despite the code being present, you MUST verify the target architecture.
    - **Discovery**: Look for the correct Target Triple in `rust-toolchain.toml`, `Makefile`, `.cargo/config.toml`, or architecture-specific directories (e.g., `os/src/arch/la64` → `loongarch64`).
    - **Action**: Call `lsp_set_target_arch` to explicitly command the LSP to use the correct Target Triple (e.g., `loongarch64-unknown-none-elf`).
    - This will **force restart** the LSP with the correct context. After setting, retry your previous LSP calls to get full semantic data.
14. **评测/交付适配层（启发式，非臆测具体赛题）**:
    - You do **not** know any single competition's secret tests. Infer **evaluation / submission glue** only from **this repo**: build scripts, CI, names of artifacts, strings in code, and **README/docs** as *claims* to be cross-checked against source.
    - **Document use (allowed)**: Use `list_repo_structure` and `read_code_segment` on `README.md`, `docs/*.md`, and similar for **how to build**, **how to run** (e.g. QEMU command lines), dependencies, directory map, and **stated** grading/competition/CI goals.
    - **Document use (forbidden for proof)**: Never treat README/docs alone as proof that a kernel mechanism is implemented. After reading docs, you MUST verify with `grep_in_repo`, LSP, or `read_code_segment` on **source**; state **README 声称 vs 代码实际** with paths when they differ.
    - **Signal gradient (weak → strong)**: (weak) README mentions "submit"/"grade"/"CI"/"autograde" → (strong) `Makefile` targets like `all` with fixed artifact names (`kernel-rv`, `kernel-la`, `disk.img`), scripts under `scripts/`, `grep` hits for test harness markers (e.g. fixed banner strings, `*testcode*`, serial test drivers), multiple virtio-blk / dual-drive hints, or workflow files (`.github/workflows`, `gitlab-ci`).
    - **Layered reporting when signals exist**: Briefly separate **Delivery** (artifact names, `make` goals), **Harness** (in-kernel or userland test runner, output contract, shutdown path), **PlatformProfile** (QEMU `virt` vs physical board `#[cfg]`), and **SubsystemDepth** (syscall/FS/net depth for heavy libc-style tests)—each bullet backed by file paths or say **未发现相关适配**.
    - **No fabrication**: If no strong signals, write explicitly that no evaluation-specific glue was found; do not invent a specific contest year or undisclosed test list."""


DESCRIBE_SYSTEM_PROMPT_JSON = """You are an elite Operating System Technical Analyst.
Your role is to analyze complex OS codebases (Rust, C, etc.) and produce structured, evidence-backed answers.

## Core Principles (same as default):
1. Evidence-based. Never guess; cite code.
2. Prefer RAG then LSP, then minimal reading.
3. Reverse evidence: if not found, say so explicitly.
4. Strict stub detection: classify implemented|stub|not_found when asked.
5. Path- and symbol-specific: every key claim must be backed by a repo-relative path and symbol.

## Critical Output Requirement (JSON-QA):
- After completing all tool calls, your FINAL message MUST be a single JSON object, and nothing else.
- The JSON MUST be valid (parseable by `json.loads`) and MUST follow the schema described in the user prompt.
- Do NOT include any extra prose before/after the JSON.
- If any answer `value` contains Mermaid or multi-line text, you MUST JSON-escape newlines as `\\n` and quotes as `\\\"` inside strings. Never paste raw multi-line ``` fences inside a JSON string (that breaks parsing).
"""


DESCRIBE_REVIEW_SYSTEM_PROMPT = """你是 OS-Agent Describe 管线的**审计员**（只读评审），不是分析执行者。你评估的是**答案 JSON 作为阶段技术报告片段**的题面落实、契约与证据充分性，**不**评价参赛 OS 设计优劣。

## 唯一允许的评审对象（三者之外一律不写）
1. **题面相符**：B 中各题 `value` 是否与 A 中对应 `stem`（及 `choices` 等题面约束）一致、是否跑题。
2. **格式与契约**：B 是否满足 JSON-QA 输出契约（字段齐全、类型合理、枚举合法等）。
3. **证据支撑结论**：**仅**依据 B 中 `answers[].evidence[]` 与对应 `value` 是否对得上；缺证据、错引、与结论矛盾须指出。

**禁止**（出现在 `review`、`summary_zh`、`findings`、降低 `confidence`/`dimensions` 的理由中 **皆禁止**）：
- 对**参赛操作系统设计/实现**作优劣评价，除非 **stem 明确要求**判断该项且你仅核对题答与证据是否一致。
- 与上「三者」无关的扩展点评、教学建议、替代实现、生产/运维类告诫。

## 硬性规则
1. **仅依据**用户消息中的 **A**（题单）与 **B**（答案 JSON，覆写题面前版本）。**禁止**引用 A/B 之外信息或假装打开仓库。
2. **不得调用工具**；输出**仅**一个 JSON 对象（可用 ```json 围栏），不得输出围栏外解释。
3. **逐题**输出 `question_reviews`，题量与顺序须与 A 的 `questions[]` 完全一致，不得漏题或乱序。

## 逐题打分（0.00~1.00，两位小数）
**严禁无脑给高分（如全篇 0.95+）。必须拉开区分度。** 对每一题，你需要分别给出两个维度的分数：

1. **`score_evidence`（证据支撑度）**：评估 `evidence` 中的代码摘录是否能直接、有效地证明 `value` 中的结论。
   - **1.00**：证据极其详实，完全覆盖所有核对点，无多余或缺失。
   - **0.90~0.95**：至少 1 条 `evidence` 且 `excerpt` 非空，能直接支撑关键事实。
   - **0.75~0.85**：有路径/符号但 `excerpt` 过短，或需推断才能连上结论。
   - **0.50~0.70**：证据与结论关联弱，或明显欠展开。
   - **0.00~0.49**：无有效证据却下强结论，或证据与结论矛盾。
   - **硬约束**：若该题所有 `excerpt` 全为空，`score_evidence` 不得高于 0.90。

2. **`score_consistency`（题面相符度）**：评估 `value` 是否严格遵守了 `stem` 的要求（含数量、三态、选项等）。
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
      "review": "<中文，仅题面/契约/证据，勿评内核设计>"
    }
  ],
  "findings": [],
  "summary_zh": "<中文，报告质量式概括>"
}

`question_reviews` 条数 = 题单题数，顺序 = 题单 `questions[]` 顺序。在 `summary_zh` 中**可一句话**说明全阶段分按「各题均值的方案 A 汇总」等（不展开公式细节）。
"""


def get_model_name() -> str:
    """获取模型名称，优先从环境变量读取"""
    return os.environ.get("MODEL_NAME", DEFAULT_MODEL)


def _is_deepseek_backend(model_name: str) -> bool:
    base_url = (os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL") or "").strip()
    model_l = (model_name or "").strip().lower()
    return ("deepseek" in base_url.lower()) or model_l.startswith("deepseek-") or model_l.startswith("deepseek/")


def _apply_deepseek_thinking_defaults(model_name: str, model_kwargs: dict | None) -> dict:
    """
    DeepSeek V4 Thinking Mode 兼容处理（OpenAI 兼容接口）：

    - 当启用 thinking 且发生 tool-calls 时，DeepSeek 要求后续请求回传历史 assistant message 中的 `reasoning_content`。
      但 LangChain 的消息序列化/反序列化链路通常不会稳定保留该字段，易触发 400：
      `The reasoning_content in the thinking mode must be passed back to the API.`

    因此：在 LangChain 路径下默认 **禁用** DeepSeek thinking（可用环境变量开启）。
    """
    mk = deepcopy(model_kwargs or {})
    if not _is_deepseek_backend(model_name):
        return mk

    thinking = (os.environ.get("OS_AGENT_DEEPSEEK_THINKING") or "").strip().lower()
    extra_body = dict(mk.get("extra_body") or {})

    # thinking 开关：
    # - 默认禁用：保证 tool-call agent 稳定运行
    # - 若用户开启：启用兼容补丁，确保 reasoning_content 能被保留并回传，避免 400
    if thinking in ("", "0", "false", "no", "off", "disabled"):
        extra_body.setdefault("thinking", {"type": "disabled"})
    else:
        # 确保在开启 thinking 时，消息序列化会携带 reasoning_content
        apply_deepseek_reasoning_content_patch()
        extra_body.setdefault("thinking", {"type": "enabled"})

        # 可选：reasoning_effort（DeepSeek 支持 high/max 等）
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
    # langchain-openai 对部分参数（如 extra_body）要求显式传递，否则会给出 UserWarning
    extra_body = None
    if isinstance(merged_kwargs, dict) and "extra_body" in merged_kwargs:
        extra_body = merged_kwargs.pop("extra_body")
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        request_timeout=request_timeout,
        max_retries=max_retries,
        extra_body=extra_body,
        model_kwargs=merged_kwargs,
    )


def get_describe_tools(stage_id: str = ""):
    """
    获取 describe 主链路的工具列表。
    """
    base_tools = [
        get_repo_local_path,
        list_repo_structure,
        find_os_core_modules,
        # │ 🥇 语义发现与模糊搜索 (首选，用于全局快速定位入口)
        rag_search_code,
        # │ 🥈 LSP 工具 (拓扑精准追踪)
        lsp_get_definition,
        lsp_get_call_graph,
        lsp_get_references,
        lsp_get_document_outline,
        lsp_set_target_arch,
        # │ 🥉 文件读取与存量匹配 (仅用于精读或兜底)
        read_code_segment,
        grep_in_repo,
        # │ 辅助
        convert_md_to_pdf,
    ]

    tools = base_tools.copy()

    if "01_overview" in stage_id:
        tools.append(analyze_tech_stack)
        tools.append(web_search)

    if "10_history" in stage_id:
        tools.extend([
            get_git_history_summary,
            analyze_git_history,
            find_symbol_first_commit,
            trace_file_evolution,
            analyze_authors_contribution,
            get_commit_diff_summary,
        ])
    return tools


def get_planning_tools(stage_id: str = ""):
    """
    规划阶段工具：在出 JSON 计划前摸底仓库。
    含目录/语义搜索 + LSP 鸟瞰 + 小段精读（与执行阶段能力对齐，但系统提示要求少轮次、浅调用）。
    """
    tools = [
        get_repo_local_path,
        list_repo_structure,
        find_os_core_modules,
        rag_search_code,
        grep_in_repo,
        read_code_segment,
        lsp_get_definition,
        lsp_get_document_outline,
        lsp_get_references,
        lsp_get_call_graph,
        lsp_set_target_arch,
    ]
    if "01_overview" in stage_id:
        tools.append(analyze_tech_stack)
        tools.append(web_search)
    if "10_history" in stage_id:
        tools.extend(
            [
                get_git_history_summary,
                analyze_git_history,
                find_symbol_first_commit,
                trace_file_evolution,
                analyze_authors_contribution,
                get_commit_diff_summary,
            ]
        )
    return tools


def build_planner_agent(model: str = None, stage_id: str = ""):
    """构建「先摸底再出计划 JSON」的 ReAct Agent；工具集随 stage_id 变化（概览/历史等）。"""
    llm = build_chat_model(model=model, temperature=0)
    return create_react_agent(llm, get_planning_tools(stage_id))


def build_executor_agent(model: str = None, stage_id: str = "", tools=None, *, model_kwargs: dict | None = None):
    """构建执行阶段使用的 ReAct Agent。"""
    llm = build_chat_model(model=model, model_kwargs=model_kwargs)
    agent = create_react_agent(llm, tools or get_describe_tools(stage_id))
    return agent


def build_sub_agent(model: str = None, stage_id: str = "", tool_names=None):
    """构建受限工具集的子 Agent。"""
    tools = get_describe_tools(stage_id)
    if tool_names:
        wanted = set(tool_names)
        tools = [tool for tool in tools if getattr(tool, "name", getattr(tool, "__name__", "")) in wanted]
    return build_executor_agent(model=model, stage_id=stage_id, tools=tools)


def build_agent(model: str = None, stage_id: str = ""):
    """兼容旧接口，默认构建 describe 执行 Agent。"""
    return build_executor_agent(model=model, stage_id=stage_id)

