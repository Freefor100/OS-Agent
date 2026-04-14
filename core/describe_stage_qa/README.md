# JSON-QA 题库（Describe 管线）

本目录用于存放各阶段（`stage_id`）的“评委友好小题单”，供 `os_agent_d_describe.py` 运行时组装 prompt 并约束 LLM 输出 JSON。

约定：
- 每个阶段一个 JSON 文件：`<stage_id>.json`
- 文件结构：
  - `stage_id`：必须与文件名一致
  - `stage_title`：阶段标题（用于校验与渲染）
  - `questions`：有序数组；每题至少包含：
    - `question_id`：稳定且唯一（建议 `Q<NN>_<XXX>`）
    - `question_type`：`fill_in` | `single_choice` | `multi_choice` | `short_answer` | `tri_state_impl`
    - `stem`：题干（中文为主，首次出现可括注英文术语）
    - `choices`：选择题可选

注意：题库本身不含“答案”，答案由 LLM 输出并在 `_per_stage/<stage_id>_answers.json` 保存。

