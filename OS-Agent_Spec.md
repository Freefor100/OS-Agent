# OS-Agent Spec

本文说明 OS-Agent D 的代码分析流程。系统以一个操作系统代码仓库为输入，按内置题单拆分分析任务，调用代码搜索、LSP、RAG、Git 等工具收集证据，再生成结构化答案、审计分数和报告材料。本文只依据当前代码整理，不引用 README 中的项目描述。

## 1. 项目定位

OS-Agent D 面向小型操作系统仓库做结构化分析。它把分析目标拆成固定题单，并要求每道题的关键结论能够追溯到代码、构建配置或 Git 历史证据。对于 `implemented / stub / not_found / unknown` 这类实现状态判断，系统会区分搜索线索、源码实现、调用链和负向搜索覆盖，避免只根据关键词命中给出结论。

主入口在 `os_agent_d_describe.py`。运行时读取 `REPO_URL`，准备仓库，然后调用 `core.describe_graph.run_describe_graph()`。真正的调度逻辑在 `core/describe_graph.py` 的 `MultiAgentRuntime`。

## 2. 总体流程

Agent 流程可以分为 8 步。

1. 读取配置与仓库信息  
   `os_agent_d_describe.py` 从环境变量读取 `REPO_URL`，以及 `REPO_YEAR`、`REPO_COMPETITION`、`REPO_SUB_COMPETITION`、`REPO_SCHOOL`、`REPO_TEAM` 等可选元信息。

2. 准备仓库  
   `MultiAgentRuntime._repo_prepare()` 检查 `./repos/<repo_name>` 是否已有仓库。已有仓库会尝试恢复 Git 跟踪文件；没有则调用 `clone_repository`。随后清理 LSP 临时文件，并尝试构建 RAG 向量索引。

3. 建立阶段计划  
   `TECH_STAGE_IDS` 包含 `02_boot_trap` 到 `10_history`。这些技术阶段会并行执行。`01_overview` 放在最后，只有前面阶段没有阻塞时才运行。  
   每个阶段先由 `core.per_planner.plan_stage()` 生成启发式计划，再由 Stage Plan Agent 根据题单生成 grouped task plan。

4. 构造 TaskSpec  
   `core/task_builder.py` 把题单问题转成 `TaskSpec`。每个 task 带有：
   - `question_id` / `question_ids`
   - `task_goal` / `query`
   - `seed_paths` / `entry_symbols`
   - `expected_evidence_types`
   - `tool_policy`
   - `metadata` 中的 `structured_facts`、`answer_contract`、`concept_boundary`、`negative_search_policy`

5. Task ReAct Agent 查证据  
   `core/task_agents.py` 中的 Task Agent 会调用工具查代码，输出 JSON。这里输出的是 `evidence_candidates` 和 `draft_answers`，属于待校验材料。  
   系统提示要求候选证据先经过校验；草稿答案通常不填写系统 `evidence_id`。

6. 系统校验证据并生成 EvidenceRecord  
   `_records_from_react_output()` 把 `evidence_candidates` 转成 `EvidenceRecord`，再交给 `core.evidence_verifier.verify_evidence()`。  
   只有这一步之后，证据才有系统生成的 `evidence_id`，格式类似 `ev_<task_id>_<随机后缀>`。证据会写入 `_agent_state/evidence_store.jsonl`。

7. Stage Assembler 组装最终答案  
   `_assemble_stage()` 按题读取 Bound Evidence 和 Task Draft，调用 Stage Assembler 逐题生成最终 JSON answer。  
   Assembler 只引用当前题可见的 `evidence_id`，路径、行号和摘录由系统根据证据 ID 回填。最后会执行 JSON-QA 契约校验。

8. Review Agent 审计并触发补证据  
   `_review_stage()` 让 Review Agent 逐题检查题面相符、格式契约、证据支撑。若分数低或证据弱，系统会构造 review fix task，最多进行 3 轮补证据和重组装。

### 2.1 Multi-Agent 协作方式

这套流程由多个 Agent 分工完成。代码里的 Multi-Agent 体现在三层。

第一层是阶段并行。`MultiAgentRuntime.run()` 会把 `02_boot_trap` 到 `10_history` 放入线程池并行执行，并发数由 `OS_AGENT_MAX_PARALLEL_STAGES` 控制。`01_overview` 不参与并行，它依赖前面阶段结果，最后执行。

第二层是阶段内 task 并行。每个 stage 先由 Stage Plan Agent 拆成多个 `TaskSpec`，再由 `_run_tasks()` 放入线程池执行。并发数由 `OS_AGENT_MAX_PARALLEL_TASKS_PER_STAGE` 控制。每个 Task Agent 只处理一个题或一组相近题，避免一次性把整个阶段交给一个模型。

第三层是角色串联。Stage Plan Agent 负责规划任务，Task ReAct Agent 负责取证和草稿，Stage Assembler 使用 Bound Evidence 组装答案，Review Agent 负责只读审计。它们之间通过 `TaskSpec`、`EvidenceRecord`、`DraftAnswerRecord`、review JSON 等结构化数据传递信息。

## 3. Agent 角色设计

### 3.1 Stage Plan Agent

位置：`core/describe_graph.py` 的 `_run_stage_plan_agent()` 和 `_stage_task_planner_prompt()`。

职责是把一个阶段的题单拆成若干 grouped task。它决定哪些题可以合并、应从哪些路径和符号查起、需要哪些证据类型；实际取证由后续 Task Agent 完成。

它的输出字段包括：

- `task_id`
- `question_ids`
- `task_type`
- `agent_type`
- `task_goal`
- `group_reason`
- `query`
- `seed_paths`
- `entry_symbols`
- `expected_evidence_types`

代码随后用 `build_tasks_from_llm_plan()` 做保护：丢弃非法题号、按 topic 拆开高风险合并、补齐题单里的证据要求和负向搜索策略。

### 3.2 Task ReAct Agent

位置：`core/task_agents.py`。

职责是查代码并产生候选证据。它可以调用工具，但最终只能输出一个 JSON 对象。输出重点是：

- `structured_fact_results`：逐个 fact 的状态或值
- `evidence_candidates`：候选证据
- `draft_answers`：草稿答案
- `missing_evidence_requests`
- `open_issues`

Task Agent 的边界很明确：它不直接写最终章节，也不直接决定系统证据 ID。它的候选证据需要经过 `verify_evidence()` 后才会进入证据库。

### 3.3 Stage Assembler Agent

位置：`core/describe_graph.py` 的 `_assemble_stage()` 和 `_one_question_assembler_prompt()`。

职责是把 Task Draft 和 Bound Evidence 组装成题单答案。它不调用工具，输入材料只有两类：

- Task Drafts：任务草稿，可能包含低可信结论
- Bound Evidence：系统校验过、带 `evidence_id` 的证据

最终答案必须包含：

- `question_id`
- `question_type`
- `stem`
- `fact_answers`
- `value`
- `used_evidence_ids`
- `notes`

`used_evidence_ids` 和 `fact_answers[*].used_evidence_ids` 来自当前 Bound Evidence。证据不足时应写 `unknown` 或待核实。

### 3.4 Stage Writer Agent

位置：`core/describe_graph.py` 的 `_write_stage()`、`_write_questions_json()`、`_markdown_writer_prompt()`。

对 02-09 这类有题单的阶段，当前代码主要走 JSON 答案路径，Markdown 不再直接生成。`01_overview` 和没有题单的阶段会走 Markdown 写作路径。

### 3.5 Review Agent

位置：`core/describe_stage_review.py` 和 `core/describe_graph.py` 的 `_review_stage()`。

Review Agent 是只读审计员。它不调用工具，只看题单和答案 JSON。审计范围限制在三件事：

- 题面相符
- JSON 契约
- evidence 与 value / fact_answers 是否对得上

它不评价参赛 OS 的设计优劣，只检查答案质量。每题输出 `score_evidence` 和 `score_consistency`，并可给出 `fix_hints`。后续 `_build_fix_tasks()` 会把这些 hints 转成补证据任务。

Review Agent 的结果还会被程序二次计算。`enrich_review_with_report_quality()` 会按逐题分数重算阶段 `confidence`，并写入 `report_quality_score` 和 `_meta.quality`。因此最终阶段分来自逐题审计结果的汇总。

## 4. Evidence 设计

### 4.1 Evidence 绑定流程

代码里 evidence 的绑定流程是：

1. 工具返回文本结果。
2. Task Agent 从工具结果中整理 `evidence_candidates`。
3. 系统把 candidate 转成 `EvidenceRecord`。
4. `verify_evidence()` 检查路径、行号、摘录、证据类型、负向搜索覆盖等。
5. 系统生成 `evidence_id`。
6. EvidenceStore 持久化到 `_agent_state/evidence_store.jsonl`。
7. Assembler 只能引用这些系统生成的 `evidence_id`。

本地工具结果是原始材料。进入最终答案的是经过校验并带有 `evidence_id` 的 Bound Evidence。

### 4.2 EvidenceRecord 字段

定义在 `core/agent_graph_state.py`。

主要字段：

- `evidence_id`：系统生成的证据 ID
- `stage_id`
- `question_ids`
- `task_id`
- `path`
- `symbol`
- `line_start` / `line_end`
- `source_type`
- `evidence_type`
- `tool_name`
- `confidence`
- `strength`
- `supports_claim_types`
- `verifier_score`
- `validity`
- `excerpt`
- `notes`
- `feature_ids`
- `metadata`

其中 `confidence`、`strength`、`supports_claim_types`、`verifier_score`、`validity` 是校验后写入的判断结果。

### 4.3 证据类型

`core/qa_contract.py` 把证据分成强证据和线索证据。

强证据包括：

- `definition`
- `implementation_body`
- `function_body`
- `call_site`
- `usage_flow`
- `call_graph`

线索证据包括：

- `search`
- `semantic_search`
- `rag`
- `grep`
- `outline`

RAG / grep 在该系统中属于线索证据，不能单独支撑 `implemented`。要证明实现存在，需要实现体、调用点、状态变化、数据结构读写或调用链证据。

### 4.4 not_found 的负向搜索

`not_found` 需要由结构化负向搜索支撑。代码要求：

- Task Agent 必须调用 `confirm_symbol_absent`
- 工具输出需要能解析出结构化负向搜索信息
- metadata 中要有 `searched_keywords`、`searched_directories`、`match_count` 等字段
- `verify_evidence()` 会检查负向搜索是否覆盖题单的 `negative_search_policy`

覆盖不足时，`not_found` 不会被视为强结论，应降级为 `unknown` 或弱证据。

## 5. Evidence 校验

校验入口是 `core/evidence_verifier.py` 的 `verify_evidence()`。

校验会给每条证据打 `verifier_score`，范围是 0 到 1。分数由程序按规则累加和扣减，主要看：

- `path` 是否存在
- 行号是否可读
- `excerpt` 是否非空
- `excerpt` 是否能在文件窗口中匹配
- 是否来自源码
- 是否由 LSP 或 `read_code_segment` 这类强工具确认
- `evidence_type` 是否满足题单要求
- 是否只是 RAG / grep 线索
- 是否是结构化负向搜索
- 是否像声明、空实现、固定返回、`todo!`、`unimplemented!`、`ENOSYS`、`unsupported`

校验结果分为：

- `validity`: `valid` / `weak` / `invalid`
- `confidence`: `high` / `medium` / `low`
- `strength`: `strong` / `weak` / `hint` / `invalid`
- `supports_claim_types`: 例如 `implemented`、`stub`、`not_found`

程序里的分档规则是：

- `verifier_score >= 0.80`：`confidence=high`，`validity=valid`
- `0.50 <= verifier_score < 0.80`：`confidence=medium`，`validity=valid`
- `0.20 <= verifier_score < 0.50`：`confidence=low`，`validity=weak`
- `< 0.20`：`confidence=low`，`validity=invalid`

`strength` 同时受分数和证据类型影响。结构化负向搜索可以成为 `strong` 并支撑 `not_found`；RAG、grep、outline 一般是 `hint`；LSP、`read_code_segment`、强证据类型在摘录可核实时才可能支撑 `implemented`。如果摘录像声明或 stub，系统会把支持类型改成 `stub`。

对于三态题，Assembler precheck 会调用 `_question_has_schema_sufficient_evidence()`。`tri_state_impl` 题至少要有可支撑 `implemented`、`stub` 或 `not_found` 的证据，否则阶段会被阻塞。

## 6. 打分机制

系统里有三类分数：证据分、逐题审计分、阶段质量分。它们用途不同。

### 6.1 证据分

证据分由 `verify_evidence()` 计算，字段是 `verifier_score`。它衡量的是一条 `EvidenceRecord` 自身是否可靠，包括路径、行号、摘录匹配、工具类型、证据类型、负向搜索覆盖等。

证据分会影响：

- `confidence`
- `validity`
- `strength`
- `supports_claim_types`

这些字段会进入 Assembler 的 Bound Evidence。Assembler 使用的是带校验结果的证据对象。

### 6.2 逐题审计分

Review Agent 对每题输出两个分：

- `score_evidence`：证据是否能支撑 `fact_answers` 和最终 `value`
- `score_consistency`：答案是否符合题干、选项、结构化事实和答案契约

这两个分都在 0 到 1 之间。Review 的系统提示给了分段含义：证据完整且能直接支撑关键事实时接近 0.90-1.00；只有路径或符号、需要推断时会降到 0.75-0.85；证据弱或结论矛盾会更低。

### 6.3 阶段 confidence 与 report_quality_score

程序会在 `recompute_confidence_scheme_a()` 中重算阶段 `confidence`：

```text
每题 mean_score = (score_evidence + score_consistency) / 2
阶段 confidence = 所有 mean_score 的平均值，保留两位小数
如果任一题 mean_score < 0.7，则阶段 confidence 最高只能是 0.75
```

`enrich_review_with_report_quality()` 还会写入 `report_quality_score`。该字段也是由逐题均值计算出的阶段级质量分，用来表示这一阶段答案 JSON 的报告质量。

### 6.4 分数如何驱动返工

`_review_needs_fix()` 使用两个阈值：

- 阶段 `confidence < 0.75`：需要返工
- 任一题 `score_evidence < 0.75`：需要返工

`_review_weak_question_ids()` 会把 `score_evidence < 0.75` 或 `score_consistency < 0.75` 的题列为弱题。随后 `_build_fix_tasks()` 根据 review 的 `fix_hints`、题干、概念边界、证据策略生成定向补证据 task。补证据后，系统重新 precheck、重新 assemble、重新 review，最多 3 轮。

## 7. 题单设计

题单位于 `core/describe_stage_qa/*.json`，加载入口是 `core.describe_stage_qa.load_stage_qa()`。测试 `tests/test_qa_contract.py` 显示，02-09 阶段共有 201 题。题单不是一组松散问题，而是按操作系统模块拆分，每个模块用不同题型覆盖“是否存在、如何实现、关键路径在哪里、证据是否足够”。

### 7.1 模块划分

| 模块 | 题单文件 | 题量 | 题型分布 |
| --- | --- | ---: | --- |
| 02 启动、架构与 Trap/系统调用 | `02_boot_trap.json` | 34 | `tri_state_impl` 15，`short_answer` 14，`single_choice` 3，`fill_in` 2 |
| 03 内存管理 | `03_mem_mgmt.json` | 34 | `tri_state_impl` 13，`short_answer` 10，`single_choice` 10，`fill_in` 1 |
| 04 进程、调度与多核 | `04_process_smp.json` | 43 | `tri_state_impl` 20，`short_answer` 15，`single_choice` 7，`multi_choice` 1 |
| 05 文件系统与设备 I/O | `05_fs_drivers.json` | 38 | `tri_state_impl` 17，`single_choice` 11，`short_answer` 10 |
| 06 同步互斥与 IPC | `06_sync_ipc.json` | 21 | `tri_state_impl` 8，`single_choice` 6，`short_answer` 6，`fill_in` 1 |
| 07 安全机制与权限模型 | `07_security.json` | 16 | `tri_state_impl` 8，`short_answer` 6，`single_choice` 2 |
| 08 网络子系统与协议栈 | `08_network.json` | 7 | `tri_state_impl` 3，`short_answer` 2，`single_choice` 1，`multi_choice` 1 |
| 09 调试机制与错误处理 | `09_debug_error.json` | 8 | `tri_state_impl` 6，`short_answer` 2 |

### 7.2 各模块题目重点

`02_boot_trap` 关注系统从入口到内核主流程的早期路径，包括入口符号、启动链、特权级切换、MMU 初始化、FPU 初始化、trap 向量、系统调用分发、用户指针检查等。题目会要求给出入口文件、符号、寄存器位、跳转链和实现状态。

`03_mem_mgmt` 关注物理页帧分配器、页表结构、walk/map/unmap API、并发控制、地址空间布局、缺页处理、CoW/Lazy、Swap、mmap、TLB 和页缓存边界。题目把“有无实现”和“实现形态”分开，避免把接口声明当作完整实现。

`04_process_smp` 覆盖执行实体、生命周期状态机、上下文切换、调度算法、fork/exec/wait/exit、文件表复制、信号/futex、锁与多核。该模块题量最多，因为进程、调度和多核之间共享大量调用链和状态字段。

`05_fs_drivers` 覆盖 VFS 接口、具体文件系统后端、第三方 FS 依赖、文件打开路径、文件描述符表、块缓存、页缓存、mmap、设备驱动和 I/O 路径。题目要求区分 VFS 抽象、具体 FS、缓存层和驱动层。

`06_sync_ipc` 覆盖同步原语、Mutex 形态、等待队列、sleep/wakeup 不变量、管道、SysV IPC、信号、futex、死锁风险和锁序。这里的题目强调阻塞、唤醒和锁保护范围，因为这些结论需要路径证据。

`07_security` 覆盖特权级隔离、凭证或保护域、syscall 路径权限检查、用户指针验证、seccomp/prctl/sandbox、栈保护、audit、secure boot 和签名校验。题目会把“有字段或接口”和“真实执行检查”分开。

`08_network` 覆盖网络子系统、协议栈来源、socket 系统调用、发送路径、网卡驱动、收包中断、协议支持和 zero-copy/DMA descriptor。该模块题量较少，但每题通常要求沿 syscall、协议栈和驱动链路查证。

`09_debug_error` 覆盖日志系统、panic 路径、panic 诊断内容、backtrace、内核调试监视器、GDB stub、错误码体系和 trace/perf/ftrace 类跟踪机制。题目重点是区分普通打印、真正日志级别、崩溃诊断和调试协议。

### 7.3 单题结构

每题常见字段包括：

- `question_id`：稳定题号。
- `question_type`：题型，如 `tri_state_impl`、`short_answer`、`single_choice`、`multi_choice`。
- `stem`：题干。
- `choices`：选择题选项。
- `feature_ids`：绑定功能点。
- `concept_boundary`：概念边界，用于区分相近机制。
- `structured_facts`：必须逐项完成的事实表。
- `answer_contract`：最终答案约束。
- `evidence_policy`：证据要求和负向搜索策略。
- `tri_state_rule`：实现状态判断规则。
- `anti_examples`：容易与实现结论混淆的相邻概念。
- `task_hints`：关键词、路径、结构化事实等提示。
- `llm_answer_steps`：作答顺序提示。

题单的重点是把模块分析拆成可检查的事实项。每个 fact 都要有 `used_evidence_ids`，最终 `value` 应该由 fact_answers 推出。

### 7.4 tri_state_impl

`tri_state_impl` 只能输出：

- `implemented`
- `stub`
- `not_found`
- `unknown`

测试要求这类题的 `answer_contract.final_type` 必须是 `enum`，合法值必须与上面四个完全一致。

### 7.5 short_answer

`short_answer` 不强制是枚举。只有当 `answer_contract.value_shape` 明确给出字段时，`value` 才必须是固定字段对象。否则 `value` 应直接回答题干。

### 7.6 feature 与 question 的一致性

`tests/test_qa_contract.py` 要求每个问题都能映射到一个 feature，且 feature 的描述、概念边界、结构化事实、必需 fact id 与问题保持一致。

## 8. Tool 设计

工具由 `core/agent_builder.py` 组装，并通过 `_wrap_task_tool_runtime()` 包一层运行时保护。保护包括：

- 记录 tool_start / tool_done / tool_error 事件
- 统计每个 task 的工具调用次数
- 超过 `OS_AGENT_TASK_AGENT_BUDGET` 后阻断
- 检测重复工具调用循环，如 AAA、ABABAB、ABCABCABC
- LSP 工具和 RAG 工具用专门的并发保护

### 8.1 react_code 工具集

默认代码分析任务使用这些工具：

- `rag_search_code`：基于代码向量索引做语义搜索
- `grep_in_repo`：正则搜索仓库
- `confirm_symbol_absent`：结构化负向搜索
- `find_os_core_modules`：扫描 OS 核心模块线索
- `read_code_segment`：读取指定代码片段
- `lsp_get_definition`：查定义
- `lsp_get_references`：查引用
- `lsp_get_document_outline`：查文档符号轮廓
- `lsp_get_call_graph`：查调用图
- `lsp_set_target_arch`：设置 LSP 目标架构
- `parse_build_config`：解析构建配置

### 8.2 react_history 工具集

历史阶段或 Git 历史任务使用这些工具：

- `get_git_history_summary`
- `analyze_git_history`
- `find_symbol_first_commit`
- `trace_file_evolution`
- `analyze_authors_contribution`
- `get_commit_diff_summary`

### 8.3 工具分层

工具返回的是待整理材料。代码通过证据类型把工具结果分层：

- RAG / grep / outline：找线索
- read / LSP / call graph：确认定义、实现、调用关系
- confirm_symbol_absent：确认缺失，但必须带覆盖信息
- Git 工具：支撑历史阶段
- build config 工具：支撑构建、架构、平台判断

## 9. 输出与状态文件

每个仓库的输出目录是 `./output/<repo_name>`。

主要产物：

- `repo_profile.json`：仓库画像
- `_agent_state/run_state.json`：运行状态
- `_agent_state/graph_state.json`：图状态快照
- `_agent_state/events.jsonl`：事件日志
- `_agent_state/debug_events.jsonl`：调试事件
- `_agent_state/evidence_store.jsonl`：证据库
- `_agent_state/draft_answer_store.jsonl`：草稿答案库
- `_agent_state/tasks/*.json`：task 执行状态
- `_agent_state/stages/*_state.json`：stage 状态
- `_agent_state/assembler/*_precheck.json`：组装前检查
- `_agent_state/assembler/*_assembled.json`：组装后的答案
- `_agent_state/reviews/*_review.json`：审计结果
- `_per_stage/*_plan.json`：阶段计划
- `_per_stage/*_answers.json`：阶段答案
- `_per_stage/*_answers_raw.txt`：原始组装日志
- `_per_stage/*_review.json`：阶段审计结果

02-09 阶段以 JSON-QA 为主。最终 HTML / 报告发布逻辑由 `core.html_renderer.publish_html_report()` 和相关渲染函数处理。

## 10. 校验与阻塞机制

系统有多层校验。

1. Task 层  
   Task Agent 输出必须是 JSON。解析失败则 task failed。工具调用有预算和循环检测。

2. Evidence 层  
   `verify_evidence()` 对候选证据打分，生成 `valid / weak / invalid` 等状态。

3. Assembler precheck  
   `_assembler_precheck()` 要求每题既有证据，也有草稿答案。三态题还要有能支撑实现状态的证据。

4. JSON-QA 层  
   `validate_answers_payload()` 检查 schema_version、stage_id、题号顺序、题型、value、fact_answers、evidence、used_evidence_ids 等。

5. Review 层  
   Review Agent 逐题打 `score_evidence` 和 `score_consistency`。低质量题会触发补证据任务。

6. Overview 阻塞  
   如果 02-10 的技术阶段有阻塞，`01_overview` 不运行。代码会把运行状态标为 `blocked`。

## 11. 可由环境变量控制的配置

### 11.1 入口与仓库元信息

- `REPO_URL`：必填，目标仓库 URL。
- `REPO_YEAR`：可选，年份元信息。
- `REPO_COMPETITION`：可选，比赛元信息。
- `REPO_SUB_COMPETITION`：可选，子赛道元信息。
- `REPO_SCHOOL`：可选，学校元信息。
- `REPO_TEAM`：可选，团队元信息。

### 11.2 模型与 OpenAI 兼容接口

- `MODEL_NAME`：主模型名，默认 `deepseek/deepseek-v3.2`。
- `OPENAI_API_KEY`：OpenAI 兼容接口 key。
- `OPENAI_API_BASE` / `OPENAI_BASE_URL`：OpenAI 兼容接口地址。
- `DESCRIBE_MAX_OUTPUT_TOKENS`：限制模型输出 token。DeepSeek 后端会放入 `extra_body.max_tokens`。

### 11.3 Thinking / Reasoning

- `OS_AGENT_THINKING`：全局 thinking 开关。
- `OS_AGENT_DEEPSEEK_THINKING`：DeepSeek thinking 开关。
- `OS_AGENT_PLANNER_THINKING`：Planner 专用 thinking 开关。
- `OS_AGENT_THINKING_BUDGET`：thinking token 预算。
- `OS_AGENT_DEEPSEEK_THINKING_BUDGET`：DeepSeek thinking 预算。
- `OS_AGENT_DEEPSEEK_REASONING_EFFORT`：DeepSeek reasoning effort。

代码里 Task 和 Review 默认不启用 thinking，主要为节省 token；Planner 可以通过环境变量开启。

### 11.4 并发、重试与预算

- `OS_AGENT_MAX_PARALLEL_STAGES`：技术阶段并发数，默认 2。
- `OS_AGENT_MAX_PARALLEL_TASKS_PER_STAGE`：单阶段 task 并发数，默认 3。
- `OS_AGENT_TASK_AGENT_BUDGET`：每个 Task Agent 最大工具调用数，默认 50。
- `OS_AGENT_TASK_AGENT_RECURSION_LIMIT`：ReAct agent 递归限制，默认 60。
- `OS_AGENT_TASK_RETRIES`：task 失败后的重试次数，默认 1。
- `OS_AGENT_ANSWER_JSON_MAX_ATTEMPTS`：单题 JSON 答案重试次数，默认 3。
- `OS_AGENT_FORCE_STAGES`：逗号分隔的 stage id，强制重跑指定阶段。

### 11.5 Review

- `DESCRIBE_STAGE_REVIEW`：是否启用阶段审计。
- `DESCRIBE_REVIEW_MODEL`：Review Agent 使用的模型；未设置时用 `MODEL_NAME`。
- `DESCRIBE_REVIEW_MAX_ATTEMPTS`：Review JSON 解析最大尝试次数，默认 3。
- `DESCRIBE_REVIEW_MAX_CHARS`：Review 输入最大字符数，默认 80000。

### 11.6 终端显示

- `OS_AGENT_TERMINAL_MODE`：终端输出模式。代码中支持 `compact`、`silent`、`dashboard`、`verbose` 等分支。

### 11.7 RAG 与 embedding

- `CODE_EMBEDDING_MODEL`：代码 embedding 模型，默认 `jinaai/jina-embeddings-v2-base-code`。
- `CODE_EMBEDDING_ENCODE_BATCH`：embedding 批大小，默认 8。
- `CODE_EMBEDDING_QUERY_PROMPT_NAME`：查询侧 prompt name。
- `OS_AGENT_USE_HF_MIRROR`：是否使用 Hugging Face 镜像，默认开启。
- `OS_AGENT_HF_ENDPOINT`：自定义 Hugging Face 镜像地址。
- `HF_ENDPOINT`：Hugging Face endpoint；如已设置会被优先使用。
- `HF_HUB_DOWNLOAD_TIMEOUT`：下载超时默认值由代码设置为 180。
- `HF_HUB_ETAG_TIMEOUT`：etag 超时默认值由代码设置为 60。

### 11.8 LSP 与编译上下文

- `LSP_TARGET`：手动指定 LSP 目标架构。
- `LIBCLANG_PATH`：给 call graph / clang 相关逻辑使用的 libclang 路径。
- `LOCALAPPDATA`：Windows 下查找部分工具路径时使用。

### 11.9 Baseline / 测试脚本

- `BASELINE_MAX_USER_CHARS`：baseline 脚本最大用户输入字符数。
- `BASELINE_REQUEST_TIMEOUT`：baseline 请求超时。

这些变量属于 `baseline_test.py` 等辅助脚本，不属于主 Agent 流程的核心控制项。

## 12. 设计取舍总结

这套系统的关键设计是把“模型写分析”拆成可审计的 multi-agent 流水线。Task Agent 负责找材料，Evidence Verifier 负责把材料变成可引用证据，Assembler 负责按题单生成结构化答案，Review Agent 负责查证据与答案是否对得上。

题单、证据、答案三者互相约束：题单规定要查什么，证据规定能说什么，答案引用 evidence_id。这样生成的报告结论可以追溯到 `_agent_state/evidence_store.jsonl`。
