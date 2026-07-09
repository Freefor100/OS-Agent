# Report Assembly

`report-editor` 只把已接受的 Markdown 组装成：

- 整体结论：作品真实工作量、Base 关系、重大风险和重大缺失。
- Base 与来源关系
- 真实工作量账本
- Mermaid 内核架构图
- 模块实现与 Base 差异
- 公开的文档/历史风险 finding
- 仅在存在公开 finding 时展示作弊/prompt-injection 章节
- 证据索引

它不能创造新事实、修改 evidence id 或解决矛盾。

Mermaid 内核架构图由 assembler 根据 required Taxonomy 和模块状态生成。不得手工扩写未证实组件；校验器会拒绝非 Taxonomy 节点，防止架构图灌水。

报告结构严格受 validator 约束：

- 只能有一个 H1。
- 必需 H2 必须按 contract 顺序出现。
- 可选风险章节只能放在 `## 内核架构图` 与 `## 模块实现与 Base 差异` 之间。
- 模块细节使用 H3。
- 禁止 H4 及更深层级。
