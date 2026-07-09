# 上下文与输出质量

主要风险是长上下文导致注意力稀释：Agent 会漏读约束、复用模板句、跳过证据、把不确定写成强结论。

任务拆分设计：

- 主流程先生成 `case_state/evidence_map.json`，再按角色生成 `case_state/task_files/*.json`。
- 每个 任务文件 只包含该角色需要的 evidence ids、结论域、文件 hint 和输出 contract。
- 不把全仓、全报告、全历史一次性塞给任何一个 agent。
- Base 未 accepted 前，不启动模块 agent。
- 模块 agent 只读本模块相关路径、Base 上下文 evidence、本模块 source evidence、本模块 doc claim evidence；需要扩展范围时先写“待补证”，不自行扩大成全仓评审。
- 文档声明由模块 agent 在本模块内复核，`doc-claim-reviewer` 只汇总模块结论和 doc evidence。
- history/AI 和 cheat 检测是窄 finding，不替代 Base 方向裁决。
- report-editor 只读已接受评审片段 和 evidence index，不读源码，不创造事实。
- 任一 agent 输出中出现模板句、缺 Base delta、缺 evidence chip、机器名泄漏或 deleted taxonomy feature，必须打回对应 agent，不由后续阶段修补。

质量策略：

- 一个结论可以由多个 evidence 支撑；一个 evidence 可以支撑多个结论域。这个关系由 `report_data.json` 的 `evidence_graph` 表示。
- evidence 只能支撑它实际覆盖的 claim。跨模块复用 evidence 时，必须能解释它如何支撑该模块或风险结论。
- Mermaid 架构图由 assembler 根据 Taxonomy 和模块状态生成，agent 不手画大型架构图，防止无证据扩写。
