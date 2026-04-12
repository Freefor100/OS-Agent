# 审阅说明 · 调试机制与错误处理

- **stage_id**: `12_debug_error`
- **passed**: False
- **score**: 0.75
- **severity**: major

## failed_rules
- `must_cover_gap`
- `readme_only`
- `missing_path_citation`

## missing_evidence
- {'paragraph_id': None, 'claim_id': 'panic_flow_reg_dump', 'reason': 'must_cover 要求明确 Panic 流程中是否包含寄存器 dump，正文仅展示代码未明确文字结论'}
- {'paragraph_id': None, 'claim_id': 'backtrace_grep_method', 'reason': 'must_cover 要求使用 grep 搜索 backtrace/unwind，正文使用 lsp_get_call_graph 且未展示 grep 输出'}
- {'paragraph_id': None, 'claim_id': 'doc_as_evidence', 'reason': '引用 doc/构建调试 - 调试指南.md 作为功能证据，违反‘不把 README/文档当实现证据’原则'}

## weak_claims
- {'paragraph_id': None, 'claim_id': 'backtrace_feature', 'reason': '依赖文档截图佐证 backtrace 功能存在，应仅依赖源码分析'}

## repair_actions（人工改进建议，不自动执行）
1. `rewrite_paragraph` — 明确文字说明 Panic 流程中‘无寄存器 dump'，仅包含栈回溯与停机
2. `add_evidence` — 补充 grep backtrace|unwind 的搜索命令及结果截图/文本，替代 lsp_get_call_graph
3. `drop_unsupported_claim` — 删除 doc/构建调试 - 调试指南.md 的引用，仅保留 kernel/printf.c 源码作为证据
4. `normalize_terminology` — 保持 grep 搜索证据风格一致，确保所有未实现功能均有 grep 负向证据

_结构化完整数据：`12_debug_error_review.json`_
