# Validation

运行 `python scripts/review.py check-all --case-dir <dir>`。

校验是编译门禁，不是修补工具。失败必须明确指向可回退阶段：缺 evidence、机器名泄漏、缺 Base delta、模块灌水、未解决矛盾、可选章节泄漏、deleted taxonomy feature 泄漏。

Markdown 结构校验包含：

- contract frontmatter。
- H2 必需标题与顺序。
- report H1/H2/H3 层级。
- Mermaid 架构图节点和边复杂度。
- absent/minimal 模块不允许灌水。
