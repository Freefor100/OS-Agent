# OS-Agent Spec

本文记录 OS-Agent D 的实现细节。系统以一个操作系统仓库为输入，按内置题单分模块取证，调用代码搜索、LSP、RAG、Git 等工具收集证据，再生成结构化答案、审计分数和最终 HTML 报告。所有结论都要回到 `_agent_state/evidence_store.jsonl` 里有 `evidence_id` 的证据条目。

## 1. 项目目标

把"让模型写一份操作系统分析报告"这件事拆成可审计的多 Agent 流水线。题单决定要查什么，证据决定能说什么，答案只能引用 `evidence_id`。三态题（`tri_state_impl`）特别区分实现状态：搜到关键词不算实现；要判 `not_found` 必须做覆盖度足够的负向搜索。这套约束让生成的报告可复核，也让 Review Agent 有打分依据。

主入口：`os_agent_d_describe.py`。运行时读 `REPO_URL` 等环境变量后进入 `core.describe_graph.run_describe_graph()`，调度类是 `MultiAgentRuntime`。

## 2. Agent 流程

### 2.1 阶段编排

`MultiAgentRuntime.run()` 把 9 个技术章（`02_boot_trap` ~ `10_history`）放线程池并行，并发数由 `OS_AGENT_MAX_PARALLEL_STAGES` 控制（默认 2）。`01_overview` 永远最后跑——它依赖前置章节内容，且只有在所有前置阶段都没有 blocked 时才会启动；只要技术阶段中有任意一个 `assembler_precheck` 或 `review_quality` 卡住，`01_overview` 整章跳过，`run_state.json.status` 写成 `blocked`。

每章流程见 `_run_stage()`：

1. **复用判断**：若 `output/<repo>/_per_stage/<stage>_answers.json` 已存在且 `OS_AGENT_FORCE_STAGES` 没强制重跑，则直接跳过整章；若 `_agent_state/stages/<stage>_state.json` 上次以 `blocked` 收尾且原因是 `assembler_precheck`，走 `_resume_blocked_stage()` 只补证据再装配，不重新规划。
2. **启发式 plan**：`core.per_planner.plan_stage()` 给出每章的 `seed_paths`、`entry_symbols` 和执行步骤。
3. **Stage Plan Agent**：`_run_stage_plan_agent()` 把题单 + 启发式 plan 喂给 LLM，让它产出 grouped task（一个或多组相近题合成一个 task）。原始 LLM 输出落到 `_agent_state/stages/<stage>_task_plan_raw.json`。
4. **Task Builder**：`build_tasks_from_llm_plan()` 校验 LLM 给的 `question_ids`（剔除非法题号）、按 topic 拆分高风险合并、把题单的 `evidence_policy / negative_search_policy / structured_facts / answer_contract / concept_boundary / llm_answer_steps` 全部塞进 `TaskSpec.metadata`。
5. **Task ReAct Agent 取证**：`_run_tasks()` 用线程池跑 task，并发数由 `OS_AGENT_MAX_PARALLEL_TASKS_PER_STAGE` 控制（默认 3）。每个 task 内部调用 `core.task_agents.run_task_agent`，详见 §2.3。
6. **证据校验入库**：返回的候选证据走 `core.evidence_verifier.verify_evidence()`，再 append 到 `evidence_store.jsonl`；草稿答案 append 到 `draft_answer_store.jsonl`。
7. **Assembler Precheck**：`_assembler_precheck()` 逐题检查证据 + 草稿是否齐全，三态题还要保证至少有支持 `implemented / stub / not_found` 之一的证据，否则该题进 `weak_question_ids`。
8. **Stage Assembler**：`_assemble_stage()` 逐题让 LLM 把 Bound Evidence + Task Drafts 拼成最终 JSON answer，然后跑 `coerce_answers_payload_by_stage_qa` + `validate_answers_payload` 做契约校验，结果写到 `_per_stage/<stage>_answers.json` 和 `_agent_state/assembler/<stage>_assembled.json`。
9. **Review Agent**：`_review_stage()` 逐题调用 `run_describe_stage_review`，只读审计；结果写 `_per_stage/<stage>_review.json`。
10. **回灌补证据**：若 `_review_needs_fix()` 判定阶段分或某题 `score_evidence` 低于 0.75，`_build_fix_tasks()` 把 review 的 `fix_hints` 翻译成新的 `TaskSpec`，再跑一遍流水线（Tools → Verify → Assemble → Review）。最多 3 轮，由 `self.max_review_fix_rounds` 限定。

### 2.2 Stage Plan Agent

位置：`core/describe_graph.py` 的 `_run_stage_plan_agent` / `_stage_task_planner_prompt`。

它只规划，不取证。输入是题单 + 启发式 plan + repo_profile，输出 `task_plan` 数组。每个 grouped task 至少包含：`task_id`、`question_ids`、`task_type`（`react_code` 或 `react_history`）、`agent_type`、`task_goal`、`group_reason`、`query`、`seed_paths`、`entry_symbols`、`expected_evidence_types`。

prompt 里写明几条硬约束：相近题才能合并；`task_goal` 要写到具体查什么证据；三态题必须按题单的 `required_evidence_types` 和 `negative_search_policy` 规划；RAG/grep 命中只算 hint，要证 `implemented` 必须规划 `read / LSP / function body / call_site` 之类强证据。

`build_tasks_from_llm_plan()` 里有保护：

- **非法题号丢弃**：不在题单里的 `question_id` 直接抛掉。
- **topic 拆分**：`_lint_task_question_chunks` 按 stem 推 topic tag（`cache_eviction`、`uart_address_switch`、`network_socket` 等），不同 topic 的题不会合并；`_ISOLATED_TOPIC_TAGS` 里的题永远单独跑。
- **元数据补齐**：把每题的 `feature_ids / negative_search_policy / structured_facts / answer_contract / concept_boundary / llm_answer_steps` 全装进 `TaskSpec.metadata`，且按 `*_by_question` 形式按 qid 存一份，避免合并题相互污染。

### 2.3 Task ReAct Agent

位置：`core/task_agents.py` 的 `_run_react_task_agent`，配套 prompt 在同文件 `_TASK_AGENT_SYSTEM` / `_react_task_prompt`。

Agent 由 `langchain.agents.create_agent`（旧版回退到 `langgraph.prebuilt.create_react_agent`）驱动，工具集由 `core/agent_builder.py` 的 `get_task_agent_tools(task_type)` 给出（详见 §6）。Agent 可以多轮调用工具，但最终只能输出一个 JSON 对象，必须包含：

- `status`：`done | blocked | failed`
- `summary`：自然语言简述
- `claim`：本任务能撑住的最小事实
- `structured_fact_results`：逐 fact 的状态或结构化值，可用 `evidence_candidate_indexes` 指向候选证据下标
- `evidence_candidates`：候选证据，含 `evidence_type / tool_name / path / line_start / line_end / symbol / claim / snippet / metadata`
- `draft_answers`：草稿答案，必填 `confidence`（high/medium/low），`used_evidence_ids` 通常留空
- `missing_evidence_requests` / `open_issues`

边界由 system prompt 强约束：

- 候选证据不带系统 `evidence_id`，不能直接用作最终证据，必须由 `verify_evidence()` 过审后再写入证据库。
- 三态题判 `not_found` 时，必须先调 `confirm_symbol_absent`，工具返回 `[CONFIRMED_ABSENT]` 才能产生 `not_found`；至少有一条 `evidence_type=negative_search` 的候选，且 `metadata.negative_search.searched_keywords / searched_directories / match_count` 必须填全；只有真实工具搜索覆盖足够时 `coverage_sufficient` 才能为 `true`。
- 草稿不填 `confidence` 默认 low，stub 草稿在 Schema Guard 那一关会被拒。

`_records_from_react_output` 把候选转成 `EvidenceRecord`：每条分配 `ev_<task_id>_<rand8>` 形式的 `evidence_id`；解析 confirm_symbol_absent 文本输出补全 `match_count / file_count / coverage_sufficient`；最后调用 `verify_evidence()` 完成校验并落库。

`_negative_search_records_from_structured_facts` 处理一种边角情况：Task Agent 在 `structured_fact_results` 里写了 `no_after_negative_search` 但没产生 negative_search 证据，系统会按题单里登记的 keywords / seed_paths 合成一条 `synthetic` 证据，metadata 里打 `synthetic=true`。校验时这种合成证据不会被计入"结构化负向搜索覆盖"，避免 LLM 自报覆盖直接通过。

### 2.4 Stage Assembler Agent

位置：`_assemble_stage` / `_one_question_assembler_prompt` / `_ask_one_question_json_with_retry`。

Assembler 不调工具，只看两类材料：本题 Bound Evidence（系统校验过的证据）、Task Drafts（含可信度的草稿）。每题 prompt 里只把当题可见的 Bound Evidence 列出；`used_evidence_ids` 必须是这批里的 `evidence_id`，引用别的题或编出来的 ID 都会被 `_extract_requested_evidence_ids` 抓到，并触发 `answer_evidence_refs_dropped` 事件。

每题最多重试 `OS_AGENT_ANSWER_JSON_MAX_ATTEMPTS` 次（默认 3），失败时进入 `_fallback_answer`：写一个 `answer_status: fallback_unusable` 的占位答案，原文存进 `_meta.fallback.raw_model_answer_excerpt`，方便事后人工核查。

候选答案再过两道程序化加工：

- `_resolve_answer_evidence_refs`：丢掉非 Bound 的 `evidence_id`，按 ID 回填 `evidence` 数组里的 path/line/excerpt/strength/validity/supports_claim_types 等字段。
- `_enforce_answer_schema`：补齐 `fact_answers`、按 `answer_contract.value_shape` 调整 `value`；三态题再过一遍 `_tri_state_value_allowed`：`implemented` 必须有正向强证据或两条以上 `yes_strong` 的 fact_answers；`stub` 必须有支持 stub 的证据或草稿语义；`not_found` 必须有 `evidence_can_support_claim` 的负向证据。条件不满足时把建议降级写到 `_meta.guardrails.tri_state` 和 `_meta.audit`，并发 `answer_guardrail_flagged` 事件。

所有程序化改动都会写到 `_meta.programmatic_mutations`，列出 phase（如 `stage_qa_coerce`、`evidence_ref_resolution`、`schema_enforce`）和 diff，便于追溯每一处改动。

### 2.5 Review Agent

位置：`core/describe_stage_review.py`，调用入口在 `describe_graph._review_stage`。

Review Agent 是只读审计员，没有工具权限。审计三件事：

1. **题面相符**：`fact_answers` 与 `value` 是否切题。
2. **JSON 契约**：字段是否齐、`structured_facts[].fact_id` 是否都有对应的 `fact_answers[]`。
3. **证据 ↔ 结论**：`answers[].evidence[]` 与 `fact_answers[*].used_evidence_ids` 是否真的能撑住结论。

System prompt（见 `core/agent_builder.py:DESCRIBE_REVIEW_SYSTEM_PROMPT`）禁止它评价被分析 OS 的设计优劣，只看报告质量本身。每题输出两个分数，都在 0~1 之间：

- `score_evidence`：证据是否能直接支撑结论
- `score_consistency`：是否符合题干 / 选项 / `structured_facts` / `answer_contract`

打分不允许全部给 0.95+。System prompt 给了分段含义：证据完整且能直接支撑约 0.90~1.00；只有路径或符号、需推断约 0.75~0.85；明显欠缺约 0.50~0.70；无证据下强结论 < 0.50。

为了节省 review 输入 token，调用前先把答案 JSON 做有损压缩（删掉 `stem / question_type / notes / line_start / line_end` 等，因为这些题单已含），再按 `DESCRIBE_REVIEW_MAX_CHARS` 上限（默认 80000）截断。Review Agent 一次只看一道题（per-question 模式），减少跨题串台和上下文过载。

每题除两个分数外，还可以给一个 `fix_hints` 对象：`finding_type`（`missing_evidence / weak_evidence / wrong_evidence / duplicate_evidence / contract_only`）、`missing_evidence_types`、`recommended_keywords`、`recommended_seed_paths`、`fix_goal`。`contract_only` 的题如果证据本身够，`_build_targeted_review_fix_task` 会跳过——因为这种问题 Task Agent 修不了，要么交给 Assembler retry，要么落到 Review fallback。

阶段 confidence 由程序按"方案 A"重算：`mean_score = (score_evidence + score_consistency) / 2`；阶段 confidence 是逐题 `mean_score` 的算术平均，保留两位小数；任一题 `mean_score < 0.7` 时，阶段 confidence 上限封到 0.75。`enrich_review_with_report_quality` 同时写 `report_quality_score = mean_q`，并在 `_meta.quality.confidence_source` 里记 `program_recomputed_from_question_scores`，区分模型自报值与程序计算值。

最后 `write_review_score_json` 把 02 ~ 09 的 `report_quality_score` 折成 0~100，写 `output/<repo>/review_score.json`，作为 HTML 报告首页的总分。

## 3. Evidence 设计

### 3.1 EvidenceRecord 字段

定义在 `core/agent_graph_state.py`：

| 字段 | 含义 |
| --- | --- |
| `evidence_id` | `ev_<task_id>_<rand8>`，由系统在校验时分配 |
| `stage_id` / `question_ids` / `task_id` | 归属信息 |
| `path` / `symbol` / `line_start` / `line_end` | 仓内定位 |
| `source_type` | `source_code / documentation / search / readme` 等 |
| `evidence_type` | 证据形态，见下表 |
| `tool_name` | 产生证据的工具，如 `read_code_segment / lsp_get_definition / confirm_symbol_absent / grep_in_repo` |
| `excerpt` / `notes` | 摘录与说明（excerpt ≤1800 字） |
| `feature_ids` | 关联功能点（题单层面） |
| `metadata` | 包括 `keywords / seed_paths / negative_search` 等，由 verify 阶段补 `path_exists / line_readable / excerpt_matches_file / negative_search_structured` 等审计字段 |
| `verifier_score` | 0~1，由 verify 计算 |
| `validity` | `valid / weak / invalid` |
| `confidence` | `high / medium / low` |
| `strength` | `strong / weak / hint / invalid` |
| `supports_claim_types` | `implemented / stub / not_found`，决定能不能撑 tri_state 结论 |

### 3.2 证据形态分类

`core/qa_contract.py` 把 `evidence_type` 分两组：

- **强证据**（`STRONG_EVIDENCE_TYPES`）：`definition`、`implementation_body`、`function_body`、`call_site`、`usage_flow`、`call_graph`。这些类型加上 LSP / `read_code_segment` 工具命中，且摘录确实能在文件里匹配，才能被判 `strong` 并支撑 `implemented`。
- **线索证据**（`HINT_EVIDENCE_TYPES`）：`search`、`semantic_search`、`rag`、`grep`、`outline`。RAG/grep 命中是入口，不是结论；这些类型在打分时直接 −0.10，且最高只能给到 `hint`。

另外有 `negative_search` 一类，专为 `not_found` 题型存在，规则单列。

### 3.3 绑定流程

```
工具结果（自由文本）
  ↓ Task Agent 整理
evidence_candidates（无 ID，待校验）
  ↓ _records_from_react_output
EvidenceRecord（候选 + 分配 ID）
  ↓ verify_evidence
EvidenceRecord（写入 verifier_score / validity / strength / supports_claim_types）
  ↓ EvidenceStore.append
_agent_state/evidence_store.jsonl
  ↓ Assembler 引用
answers[].used_evidence_ids 只能填这一步落库的 evidence_id
```

进入最终答案的只有"Bound Evidence"——经过校验、有 `evidence_id`、由系统按 ID 回填 path/line/excerpt 的证据。LLM 写不出 ID 也填不出 path，避免编造。

### 3.4 负向搜索

`not_found` 必须由结构化负向搜索支撑，规则集中在 `evidence_verifier._parse_negative_search_metadata` 和 `_negative_search_covers_policy`：

- Task Agent 必须调 `confirm_symbol_absent`；该工具产生的文本里有 `[CONFIRMED_ABSENT]` / `[FOUND]` 标识、搜索文件数、每个 pattern 的命中数。
- `metadata.negative_search` 至少要有 `searched_keywords / searched_directories / match_count`；若为合成证据（`synthetic=true`），不认作"结构化负向搜索"。
- 题单 `evidence_policy.negative_search_policy` 给出 `keywords`、`seed_paths`、`minimum_keyword_coverage`、`minimum_directory_coverage`；`_coverage_ratio` 计算 keyword 与目录覆盖率，必须同时达到阈值才算覆盖足够。
- 仅在题单未给任何阈值时，才信任 LLM 自报的 `coverage_sufficient=true`。

只有"结构化负向搜索 + 覆盖足够"才会得到 `strength=strong / supports_claim_types=[not_found]`；其余形态降级为 `hint` 或 `weak`。

## 4. Evidence 校验

入口：`core/evidence_verifier.py:verify_evidence`。给一条 `EvidenceRecord` 算 `verifier_score`，按累加扣分，最后落到 4 档。

### 4.1 加分项（最高 +1.5）

- `path_exists`（路径在仓内能找到）+0.25
- `line_readable`（行号在文件范围里、能读到非空行）+0.15
- `excerpt_nonempty` +0.15
- `excerpt_matches_file`（摘录在窗口或前 200 KB 文本里能去空白匹配）+0.20
- `source_type == "source_code"` +0.10
- `tool_name` 以 `lsp_` 开头 +0.10
- `tool_name == "read_code_segment"` 或 `metadata.read_confirmed=true` +0.15
- `evidence_type ∈ STRONG_EVIDENCE_TYPES` +0.10
- `negative_search`（任何形态）+0.15
- `negative_search_structured`（覆盖达标的结构化负向搜索）再 +0.30

### 4.2 扣分项

- `evidence_type ∈ HINT_EVIDENCE_TYPES` 或 `tool_name ∈ {rag_search_code, grep_in_repo}` −0.10
- 题单要求的 `required_evidence_types` 不在本条 `evidence_type` 里 −0.20（合规的 negative_search 不扣）
- 文本含 `confidence=low / Generic Fallback / ASM Fallback` −0.25
- 文本以 `Error:` 开头或包含 `无法生成调用图 / 未出现，无法生成` −0.35
- 文档/README 类来源却声称支撑实现 −0.30
- 摘录像声明（trait / typedef / `struct X;` / `extern` / 函数签名+`;`）但又声称撑实现 −0.40
- 路径不存在且不是负向搜索，或摘录为空 −0.50
- 路径在但行号不可读 −0.35
- 路径在 + 摘录非空但摘录无法在文件里匹配 −0.35

### 4.3 分档与 strength

`verifier_score` 截到 [0, 1] 后：

| 分数区间 | confidence | validity |
| --- | --- | --- |
| ≥ 0.80 | high | valid |
| 0.50 ~ 0.80 | medium | valid |
| 0.20 ~ 0.50 | low | weak |
| < 0.20 | low | invalid |

`strength` 由 validity + 类型组合判定：

- 结构化负向搜索 → `strong` + `supports_claim_types=[not_found]`
- 普通负向搜索 → `weak`
- 线索类型 / RAG / grep → `hint`
- 强证据类型且摘录可核（或 LSP/`read_code_segment` 工具确认）→ `strong`，再判 `supports_claim_types`：摘录像声明或 `todo!() / unimplemented!() / panic!() / ENOSYS / ENOTSUP / unsupported` 时归 `[stub]`，否则 `[implemented]`
- 其他 → `weak`

存证时 `metadata` 还会被补一组审计字段：`path_exists`、`line_readable`、`excerpt_matches_file`、`negative_search`、`negative_search_synthetic`、`negative_search_structured`、`can_support_implemented`，方便后续排查。

### 4.4 Assembler 端的二次约束

`_question_has_schema_sufficient_evidence`（见 `describe_graph.py`）对三态题再加一道门：题面绑定的证据集合里至少有一条能撑 `implemented`、`stub` 或 `not_found` 之一，否则该题进 `weak_question_ids`，整个阶段进入 `assembler_precheck=blocked`。`_tri_state_value_allowed` 还会逐答案检查：写 `implemented` 但只有 stub / negative 证据，或写 `not_found` 但没有 `not_found` 支撑，都会触发 schema guard，把建议改写记到 `_meta.guardrails.tri_state` / `_meta.audit`，并发 `answer_guardrail_flagged` blocker 事件。

## 5. 题单设计

### 5.1 文件与规模

题单存在 `core/describe_stage_qa/<stage_id>.json`，由 `load_stage_qa()` 读取。02~09 阶段总共 201 题：

| 阶段 | 文件 | 题量 | 题型分布 |
| --- | --- | ---: | --- |
| 02 启动/架构与 Trap/系统调用 | `02_boot_trap.json` | 34 | tri_state_impl 15 / short_answer 14 / single_choice 3 / fill_in 2 |
| 03 内存管理 | `03_mem_mgmt.json` | 34 | tri_state_impl 13 / short_answer 10 / single_choice 10 / fill_in 1 |
| 04 进程/线程/调度与多核 | `04_process_smp.json` | 43 | tri_state_impl 20 / short_answer 15 / single_choice 7 / multi_choice 1 |
| 05 文件系统与设备 I/O | `05_fs_drivers.json` | 38 | tri_state_impl 17 / single_choice 11 / short_answer 10 |
| 06 同步互斥与 IPC | `06_sync_ipc.json` | 21 | tri_state_impl 8 / single_choice 6 / short_answer 6 / fill_in 1 |
| 07 安全机制 | `07_security.json` | 16 | tri_state_impl 8 / short_answer 6 / single_choice 2 |
| 08 网络协议栈 | `08_network.json` | 7 | tri_state_impl 3 / short_answer 2 / single_choice 1 / multi_choice 1 |
| 09 调试与错误处理 | `09_debug_error.json` | 8 | tri_state_impl 6 / short_answer 2 |

10 章是 Git 历史，没有题单，靠 `react_history` 工具组直接产 Markdown。01 章是项目概览，依赖 02~10 完稿后再写。

### 5.2 单题字段

每道题至少包含：

- `question_id`：稳定题号（如 `Q02_001`）
- `question_type`：`tri_state_impl / short_answer / single_choice / multi_choice / fill_in`
- `stem`：题干
- `choices`：选择题选项
- `feature_ids`：功能点 ID（接 feature graph）
- `concept_boundary`：概念边界，告诉 Agent"哪些不算这道题"
- `structured_facts`：必答事实表，每项有 `fact_id / fact_key / kind / answer_type / allowed_values 或 fields / evidence_required / conclusion_role`
- `answer_contract`：最终答案约束，含 `mode / final_field / final_type / required_fact_ids / value_shape / evidence_reference / free_text_policy / reproducibility_rule`
- `evidence_policy`：`required_evidence_types` + `negative_search_policy`（keywords / seed_paths / 阈值）
- `tri_state_rule`：三态题专属，规定什么算 implemented / stub / not_found
- `anti_examples`：容易混淆的相邻概念
- `task_hints`：`keywords / seed_paths / entry_symbols / task_types / structured_facts / diagnostic_checks` 等
- `llm_answer_steps`：作答顺序，给弱模型用
- `textbook_basis`：教科书出处，便于审稿溯源
- `diagnostic_checks`：5 道局部判断（答题前自检）

### 5.3 三态题（tri_state_impl）

`value` 只能取 `implemented / stub / not_found / unknown`，由 `JSON_QA_SCHEMA_V1` 与 `coerce_answers_payload_by_stage_qa` 共同保证。`tri_state_rule` 给出每态判定要点：

- `implemented`：必须看到实现体、调用点、状态变化、数据结构读写或调用链。
- `stub`：空实现、固定返回、`ENOSYS / ENOTSUP / unsupported`、`todo!() / unimplemented!() / panic!()`、仅有 trait/struct 壳。
- `not_found`：必须有结构化负向搜索证据，且覆盖题单 `negative_search_policy`。
- `unknown`：证据不够时的默认值，相当于"待人工核实"。

### 5.4 short_answer / fill_in

不是枚举题。只有当 `answer_contract.value_shape` 显式给出固定字段时，`value` 才必须是结构化对象；否则 `value` 直接回答题干。`short_answer` 仍要逐项填 `fact_answers`，`value` 是 fact_answers 的汇总结论。

### 5.5 单选 / 多选

`single_choice.value` 必须等于 `choices` 里某一项原文（不带 A/B/C/D 字母前缀）；`multi_choice.value` 必须是数组。`coerce_answers_payload_by_stage_qa` 会把模型偶尔写出的 `"A. xxx"` 自动归一到选项原文。

### 5.6 题单与答案的契约

- `validate_answers_payload`（在 `core/describe_json_qa.py`）按 JSON Schema 校验：题号顺序、`question_type` 枚举、`fact_answers` 必须覆盖 `structured_facts.fact_id`、`used_evidence_ids` 必须是数组、`evidence` 数组里 `path / symbol_kind / symbol_name` 必填等。
- `tests/test_qa_contract.py` 还做交叉检查：每个题至少绑一个 feature；feature 的 `concept_boundary / structured_facts / required_fact_ids` 与题保持一致。

## 6. Tool 设计

### 6.1 工具集分层

工具集合在 `core/agent_builder.py:get_task_agent_tools(task_type)`：

- `react_code`（默认）：`rag_search_code`、`grep_in_repo`、`confirm_symbol_absent`、`find_os_core_modules`、`read_code_segment`、`lsp_get_definition`、`lsp_get_references`、`lsp_get_document_outline`、`lsp_get_call_graph`、`lsp_set_target_arch`、`parse_build_config`。
- `react_history`：`get_git_history_summary`、`analyze_git_history`、`find_symbol_first_commit`、`trace_file_evolution`、`analyze_authors_contribution`、`get_commit_diff_summary`。

按用途区分：

| 用途 | 工具 |
| --- | --- |
| 找线索 | `rag_search_code`、`grep_in_repo`、`find_os_core_modules`、`lsp_get_document_outline` |
| 确认实现 | `read_code_segment`、`lsp_get_definition`、`lsp_get_references`、`lsp_get_call_graph`、`lsp_set_target_arch` |
| 否定证据 | `confirm_symbol_absent` |
| 构建/平台 | `parse_build_config` |
| Git 历史 | `analyze_git_history` 等 6 个 git_ops 工具 |

工具选择由 LLM 决定，但题单 `task_hints.task_types` 与 Plan Agent 的 `task_type` 共同筛掉无关工具。`TaskSpec.tool_policy.allowed_tools` 还能进一步收窄；`_tools_for_task_policy` 在 task 启动前按白名单过滤一次。

### 6.2 安全限制

- `read_code_segment`、`grep_in_repo`、`rag_search_code`、`confirm_symbol_absent` 都走 `_is_path_allowed`，只允许访问 `./repos/` 和 `./output/` 下面的文件。
- `grep_in_repo`、`confirm_symbol_absent` 默认排除 `.git / target / node_modules / vendor / build / .vscode / __pycache__` 等目录，只搜代码扩展名（含 `.rs / .c / .cpp / .h / .S / .toml / .ld / .x / .mk` 等），单文件超 2 MB 跳过。
- `confirm_symbol_absent` 一次跑多个 pattern，全零匹配才返回 `[CONFIRMED_ABSENT]`，输出里有"搜索文件数 / 每 pattern 匹配数 / 命中示例 ≤3"，方便人工复核。

### 6.3 运行时保护

`_wrap_task_tool_runtime` 给每个工具套一层运行时层：

- **事件埋点**：`tool_start / tool_done / tool_error / tool_blocked`，写到 `_agent_state/events.jsonl`，结果摘录前 5000 字写到 `metadata.result_excerpt`。
- **预算控制**：每个 task 最多 `OS_AGENT_TASK_AGENT_BUDGET` 次工具调用（默认 50）；超出后剩下的调用直接返回 `Error: tool-call limit exceeded`，把控制权还给 ReAct Agent。
- **死循环检测**：`_detect_tool_loop` 看最近 20 步签名（`tool_name + args 的 sha1`）：
  - AAA：连续 3 次同工具同参数。
  - ABABAB / ABCABCABC：周期 2 或 3 的循环至少跑 3 个完整周期。
    命中后直接 block 当次调用，并在错误信息里建议"换关键词、换工具或基于已有信息回答"。
- **LSP 并发保护**：`lsp_tool_guard` 用 `LSP_TOOL_CONCURRENCY=1` 的进程级 semaphore + 读写锁；普通 LSP 查询走读锁共享，`lsp_set_target_arch` 走写锁（要重启 rust-analyzer / clangd）。
- **RAG 并发保护**：`rag_tool_guard` 用 `RAG_TOOL_CONCURRENCY=1` 的 semaphore，因为 SentenceTransformer 在多线程下不安全。

### 6.4 LSP 旁路与缓存

`tools/lsp_ops.py` 在 `output/_lsp_sidecar/<repo>_<hash>` 下放 `compile_flags.txt` 等临时文件，避免污染被分析的仓库。`cleanup_os_agent_repo_ephemeral` 在每次 describe 启动时清理上次留下的临时文件，并按引用计数避免误删活跃 LSP 会话使用的占位。`lsp_set_target_arch` 切换架构会强制重启对应 LSP，常见 triple 在工具 docstring 里列了（`riscv64gc-unknown-none-elf` / `loongarch64-unknown-none-elf` / `aarch64-unknown-none-elf` / `x86_64-unknown-none-elf`）。

## 7. 容错机制

### 7.1 Task 层

- **JSON 解析失败**：`run_task_agent` 抛异常 → `TaskResult.status=failed` + `errors=["..."]`，不入证据库。
- **Task 重试**：`_run_one_task_with_limits` 按 `OS_AGENT_TASK_RETRIES`（默认 1）重试，指数退避 `2^attempt` 秒。
- **递归限制**：`OS_AGENT_TASK_AGENT_RECURSION_LIMIT`（默认 60）控制 ReAct agent 内部图的最大递归步。
- **工具循环**：见 §6.3。
- **task 状态复用**：task 完成后写 `_agent_state/tasks/<task_id>.json`，`status=done` 的 task 在重新调度时直接跳过（`OS_AGENT_FORCE_STAGES` 会强制重跑指定阶段）。

### 7.2 Evidence 层

- **路径错 / 摘录假**：扣分到 `validity=invalid`，`_curate_grouped_evidence` 在装配阶段会把 invalid 证据滤掉（合格的负向搜索除外）。
- **excerpt 截断**：`_refresh_weak_evidence` 在 fix round 之前把弱题的证据从源文件按行号重读一次，覆盖 task 阶段被截断的旧 excerpt。
- **合成负向搜索**：标 `synthetic=true`，不算结构化负向，避免 LLM"自我宣告覆盖"绕过校验。

### 7.3 Assembler 层

- **schema 修复**：`coerce_answers_payload_by_stage_qa` 自动归一选项格式、补齐 `fact_answers`、按 `value_shape` 调整 `value`；改动写入 `_meta.programmatic_mutations`。
- **JSON 重试**：单题最多 `OS_AGENT_ANSWER_JSON_MAX_ATTEMPTS` 次（默认 3）。第二次起的 prompt 会附上一轮原始输出和 issues 列表，告诉模型必须改什么。
- **fallback answer**：重试用尽时构造可写入但明确标记不可用的占位答案（`answer_status=fallback_unusable`，notes 写"模型输出未通过 JSON/契约校验"），原始模型输出前 4000 字记到 `_meta.fallback.raw_model_answer_excerpt`。
- **三态 schema guard**：见 §2.4 / §4.4，违规答案不直接改 `value`，只把建议值和理由写到 `_meta.guardrails.tri_state` 与 `_meta.audit`，发 `answer_guardrail_flagged` blocker 事件，便于人工核查。
- **assembler precheck**：缺证据 / 缺草稿 / 三态题 schema 不足 → `status=blocked`，阶段进入 `_resume_blocked_stage` 路径，下次运行时只补证据再装配。

### 7.4 Review 层

- **review JSON 解析失败**：`run_describe_stage_review` 按 `DESCRIBE_REVIEW_MAX_ATTEMPTS`（默认 3）重试，每轮把上次原文 + 错误信息 + 修复指令再喂给同一个 review 模型。
- **review 失败**：失败后写 `_per_stage/<stage>_review_error.json`，阶段直接走"无 review"路径，跳过 fix round。
- **fix round**：阶段 confidence < 0.75 或任一题 `score_evidence < 0.75` → 进入 `_build_fix_tasks`。`finding_type=contract_only` 且 score_evidence ≥ 0.75 的题不会再生成 task（这种问题 Task Agent 没法补，只能 Assembler 改 schema）。每轮按 review 给的 `recommended_keywords / recommended_seed_paths / missing_evidence_types` 构造定向取证 task，最多 3 轮。
- **review_quality 阻塞**：3 轮后仍 needs_fix，阶段标 `block_reason=review_quality`，但答案文件还是落盘——给人工接手用。

### 7.5 Stage / Run 层

- **阶段 blocked**：技术阶段任何一个 blocked，`01_overview` 不跑，`run_state.json.status=blocked`，`blocked_stages` 列在 `extra` 里。
- **图状态快照**：每个阶段结束都会刷新 `_agent_state/graph_state.json`，含 stage 状态、task 结果、整个证据库；崩溃后下次启动可凭此恢复。
- **文件锁**：所有写出口（answers / state / review / graph snapshot）都过 `FileLock(lock_path("output_write"))`，多进程并发不会互相覆盖；`FileLock` 自带 1 小时 TTL，过期自动清理（`_clear_stale_locks` 也会在 run 启动时主动清残锁）。
- **原子写**：`_atomic_save_json` 写到 `<path>.tmp` 再 `os.replace`，避免断电留下半截 JSON。
- **runtime 复用**：`run_state.json.run_id` 持久化；同一仓库二次执行复用 run_id，`reviewed` 状态的阶段直接跳过（除非命中 `OS_AGENT_FORCE_STAGES`）。

## 8. 输出与状态文件

每个仓库的输出根是 `output/<repo_name>`：

```
output/<repo>/
├─ repo_profile.json                 仓库画像（架构、入口猜测、构建文件）
├─ review_score.json                 02~09 阶段审计分汇总（0~100）
├─ index.html                        最终 HTML 报告入口
├─ feature_graph.json                feature 关联图（页面用）
├─ _per_stage/
│  ├─ <stage>_plan.json              阶段执行计划 + LLM task plan
│  ├─ <stage>_answers.json           最终 JSON 答案
│  ├─ <stage>_answers_raw.txt        逐题原始 LLM 输出（含 retry 记录）
│  └─ <stage>_review.json            阶段审计结果（带 report_quality_score 与 _meta.quality）
├─ sections/
│  └─ <stage>_<slug>.md              01 / 10 章 Markdown，HTML 渲染用
└─ _agent_state/
   ├─ run_state.json                 整体运行状态（status / completed_stages）
   ├─ graph_state.json               图快照
   ├─ events.jsonl                   事件流（stage / task / tool 起止）
   ├─ debug_events.jsonl             reasoning_content / tool_trace 调试日志
   ├─ evidence_store.jsonl           证据库（append-only）
   ├─ draft_answer_store.jsonl       草稿答案库
   ├─ tasks/<task_id>.json           每个 task 的 TaskResult
   ├─ stages/<stage>_state.json      阶段状态
   ├─ stages/<stage>_task_plan_raw.json  Plan Agent 原始 LLM 输出
   ├─ assembler/<stage>_precheck.json    Assembler precheck 结果
   ├─ assembler/<stage>_assembled.json   Assembler 输出（与 _per_stage 镜像）
   ├─ reviews/<stage>_review.json        Review 输出（与 _per_stage 镜像）
   ├─ reviews/<stage>_review_raw.txt     Review 原始输出
   ├─ reviews/<stage>_review_input_manifest.json  Review 输入 manifest
   └─ locks/                              FileLock 占用文件
```

`_per_stage` 是给最终报告与人工查看用，`_agent_state` 是给运行时复用与排查用，二者镜像存放。

## 9. 校验与阻塞 Pipeline

按时间顺序，一道题要通过下面这些门：

1. **Task Agent JSON 解析**：失败 → task `failed`，不留证据。
2. **Evidence 校验**：`verify_evidence` 对每条候选打 verifier_score → `valid / weak / invalid`。
3. **Schema verify grouped evidence**：用题单的 `required_evidence_types` 和 `negative_search_policy` 重过一遍，更新 strength。
4. **Assembler precheck**：每题既要有有效证据，也要有草稿；三态题还要有支撑 `implemented / stub / not_found` 之一的证据。任一题不达标 → `status=blocked`。
5. **JSON-QA 契约校验**：`validate_answers_payload` 检查 schema、题型、fact_answers 完整、`used_evidence_ids` 是数组等。
6. **Schema guard**：`_enforce_answer_schema` 对三态值再过一遍 `_tri_state_value_allowed`，不通过则记 guardrail，不直接改 value。
7. **Review 打分**：每题 `score_evidence / score_consistency`；阶段 confidence 由程序按方案 A 重算。
8. **Fix round**：阶段或单题分低于 0.75 → 触发定向取证 task，最多 3 轮。
9. **Stage 状态固化**：通过则 `reviewed`，否则 `blocked`，写 `block_reason=assembler_precheck | review_quality`。
10. **Overview 阻塞**：任何技术阶段 blocked → `01_overview` 不运行，`run_state=blocked`。

## 10. 环境变量

按用途分组列出，全部都是可选项（除 `REPO_URL` 外）。

### 10.1 入口与仓库元信息

- `REPO_URL`（必填）：目标仓库 URL，用于克隆与 `repo_name` 推断。
- `REPO_YEAR / REPO_COMPETITION / REPO_SUB_COMPETITION / REPO_SCHOOL / REPO_TEAM`：写入 HTML 报告头部的元信息。

### 10.2 模型与 OpenAI 兼容接口

- `MODEL_NAME`：主模型名。
- `OPENAI_API_KEY`：API Key。
- `OPENAI_API_BASE` / `OPENAI_BASE_URL`：兼容接口地址。代码靠 base_url 与 model 名识别 DeepSeek / Qwen / 其他后端，并切换 thinking 注入策略。
- `DESCRIBE_MAX_OUTPUT_TOKENS`：限制单次输出 token 数。DeepSeek 后端走 `extra_body.max_tokens`，其他后端走原生 `max_tokens`。

### 10.3 Thinking / Reasoning

- `OS_AGENT_THINKING`：全局 thinking 开关。
- `OS_AGENT_DEEPSEEK_THINKING`：DeepSeek 专用开关（与上面互通，任意一个开就开）。
- `OS_AGENT_PLANNER_THINKING`：仅 Stage Plan Agent 单独控制。
- `OS_AGENT_THINKING_BUDGET` / `OS_AGENT_DEEPSEEK_THINKING_BUDGET`：thinking token 预算。
- `OS_AGENT_DEEPSEEK_REASONING_EFFORT`：DeepSeek `reasoning_effort` 字段。

代码里 Task 与 Review 始终关 thinking（节省 token），Planner 默认随全局开关，可通过 `OS_AGENT_PLANNER_THINKING` 单独控制。

### 10.4 并发、预算、重试

- `OS_AGENT_MAX_PARALLEL_STAGES`：技术阶段并发数（默认 2）。
- `OS_AGENT_MAX_PARALLEL_TASKS_PER_STAGE`：单阶段 task 并发数（默认 3）。
- `OS_AGENT_TASK_AGENT_BUDGET`：单 task 工具调用上限（默认 50）。
- `OS_AGENT_TASK_AGENT_RECURSION_LIMIT`：ReAct agent 递归上限（默认 60）。
- `OS_AGENT_TASK_RETRIES`：task 失败重试次数（默认 1，指数退避）。
- `OS_AGENT_ANSWER_JSON_MAX_ATTEMPTS`：单题 Assembler JSON 重试次数（默认 3）。
- `OS_AGENT_FORCE_STAGES`：逗号分隔 stage_id，强制重跑指定阶段（绕过 `reviewed` 缓存）。

### 10.5 Review

- `DESCRIBE_STAGE_REVIEW`：Review Agent 总开关（默认 0；baseline_test 把它强制开为 1）。
- `DESCRIBE_REVIEW_MODEL`：审计专用模型；不设则退到 `MODEL_NAME`。
- `DESCRIBE_REVIEW_MAX_ATTEMPTS`：审计 JSON 解析重试次数（默认 3）。
- `DESCRIBE_REVIEW_MAX_CHARS`：审计输入字符上限（默认 80000，支持 `80k / 8w` 这类后缀）。

### 10.6 RAG 与 Embedding

- `CODE_EMBEDDING_MODEL`：代码 embedding 模型，默认 `jinaai/jina-embeddings-v2-base-code`。
- `CODE_EMBEDDING_ENCODE_BATCH`：embedding 批大小（默认 8）。
- `CODE_EMBEDDING_QUERY_PROMPT_NAME`：查询侧 prompt 名（用于带 prompt 的模型）。
- `OS_AGENT_USE_HF_MIRROR`：是否启用 Hugging Face 镜像（默认 true）。
- `OS_AGENT_HF_ENDPOINT`：自定义 Hugging Face 镜像地址（默认 `https://hf-mirror.com`）。
- `HF_ENDPOINT`：上游 endpoint。代码逻辑：用户已显式设置则尊重原值；未设且 `OS_AGENT_USE_HF_MIRROR` 开启则写国内镜像；都关掉就走库默认。
- `HF_HUB_DOWNLOAD_TIMEOUT` / `HF_HUB_ETAG_TIMEOUT`：默认值 `apply_hf_hub_env_defaults` 写为 180 / 60。

### 10.7 LSP 与编译上下文

- `LSP_TARGET`：手动指定 LSP target triple（覆盖自动探测）。
- `LIBCLANG_PATH`：给 callgraph 语义解析用的 libclang 路径。
- `LOCALAPPDATA`：Windows 下查找 rust-analyzer / clangd 路径用（`tools/lsp_ops.py`）。

### 10.8 终端显示

- `OS_AGENT_TERMINAL_MODE`：`compact / silent / dashboard / verbose`，默认 `compact`。
