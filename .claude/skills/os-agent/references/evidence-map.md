# Evidence 证据映射

Evidence 不是只服务一个结论。映射阶段把每条 evidence 对应到多个结论域，再按角色切片给 agent。

典型映射：

- `git_history`：真实工作量、开发历史、AI 痕迹、抄袭过程、抄袭方向、批量导入/拆文件/函数改名。
- `doc_claim`：Base 声明、外部依赖声明、模块设计声明、AI 使用声明、开发历程声明。
- `source_span`：模块实现、真实改动、架构节点、外部模块适配。
- `base_delta_summary`：Base 身份、来源关系、相对 Base 的工作量、抄袭方向候选。
- `risk_signal`：作弊、刷分、runner 绕过、prompt injection。
- `negative_search`：文档声明缺证、功能缺失、Base 声明不成立。

一条 evidence 可以被多个结论复用。例如 git history 可以同时支撑真实工作量、AI 使用痕迹、抄袭过程和同届方向；设计书可以同时支撑 Base 声明、外部依赖、模块设计、AI 使用声明和开发历程；代码 span 可以同时支撑模块实现、Base delta、架构节点和外部模块适配。

同届抄袭方向必须同时进入 `same_year_direction`、`plagiarism_direction` 和 `development_history` 相关任务；只看到结构相似或只看到提交时间线，都不能给出强方向结论。

角色切片：

- `base-lineage-reviewer` 读取 Base、来源、抄袭方向、外部依赖、开发历史相关 evidence。
- `module-*` 读取本模块 source evidence、Base 上下文 evidence、本模块 doc claim evidence。
- `doc-claim-reviewer` 读取 doc claim evidence 和模块复核结果，不重新全仓读代码。
- `history-ai-reviewer` 读取 git history、AI 声明、生成痕迹 evidence。
- `cheat-detector` 读取 test/runner/prompt surface risk evidence。
- `report-editor` 只读取已接受评审片段 和 evidence 索引。

目标是降低长上下文注意力稀释：不同 agent 看到的是与结论域匹配的 evidence slice，而不是全仓、全证据、全报告。
