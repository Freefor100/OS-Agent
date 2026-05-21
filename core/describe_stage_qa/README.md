# JSON-QA 题库（Describe 管线）

本目录用于存放各阶段（`stage_id`）的“评委友好小题单”，供 `os_agent_d_describe.py` 运行时组装 prompt 并约束 LLM 输出 JSON。

题单 JSON 本体是唯一运行来源。运行时 `load_stage_qa()` 只读取本目录 JSON，
不会自动补全、生成、覆盖或校验任何题目字段；需要改题时直接人工编辑本目录 JSON。

约定：
- 每个阶段一个 JSON 文件：`<stage_id>.json`（无小题单的阶段可不建该文件，运行时按空 `questions` 处理）
- 文件结构：
  - `stage_id`：必须与文件名一致
  - `stage_title`：阶段标题（用于校验与渲染）
  - `questions`：有序数组；每题至少包含：
    - `question_id`：稳定且唯一（建议 `Q<NN>_<XXX>`）
    - `question_type`：`fill_in` | `single_choice` | `multi_choice` | `short_answer` | `tri_state_impl`
    - `stem`：题干（中文为主，首次出现可括注英文术语）
    - `choices`：选择题可选
- `tri_state_impl` 的答案枚举为 `implemented | stub | not_found | unknown`；`unknown` 用于证据不足或搜索覆盖不足，不得强行归类。
- 题单文件本体应保留 Feature Schema Bank materialize 后的字段，方便人工评审：
  - `feature_ids`
  - `evidence_policy`
  - `diagnostic_checks`
  - `structured_facts`
  - `answer_contract`
  - `textbook_basis`
  - `concept_boundary`
  - `tri_state_rule`
  - `anti_examples`
  - `task_hints.diagnostic_checks`
  - `task_hints.structured_facts`
  - 顶层 `features`
- RAG / grep 命中是 hint；`implemented` 需要强证据，`not_found` 需要结构化负向搜索覆盖 feature policy。

注意：题库本身不含“答案”，答案由 LLM 输出并在 `_per_stage/<stage_id>_answers.json` 保存。

题库当前合计 **193** 题。`10_history` 使用 `os_agent_d_describe.py` 中内联 `prompt`，无对应 JSON 题单。若你本地题量数字不符，说明题库文件未同步仓库或已被截断。

