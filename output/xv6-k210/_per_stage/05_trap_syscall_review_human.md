# 审阅说明 · 中断、异常与系统调用

- **stage_id**: `05_trap_syscall`
- **passed**: False
- **score**: 0.75
- **severity**: major

## failed_rules
- `must_cover_gap`

## missing_evidence
- {'paragraph_id': None, 'claim_id': 'must_cover_9', 'reason': '正文未提及对 _impl 后缀函数模式的检查过程与结论（本仓未见此模式）'}
- {'paragraph_id': None, 'claim_id': 'must_cover_11', 'reason': 'syscall 实现深度分级未与 README 声称进行对比，未说明是否存在冲突'}
- {'paragraph_id': None, 'claim_id': 'must_cover_8', 'reason': '用户指针校验部分仅展示 copyin2/copyinstr2，缺失 fetchaddr 实现证据'}

## weak_claims
- {'paragraph_id': None, 'claim_id': 'syscall_stub_behavior', 'reason': '指出桩函数返回 0 而非 -ENOSYS 可能导致误判，但未引用 README 是否承诺了严格错误码'}

## repair_actions（人工改进建议，不自动执行）
1. `append_missing_module` — 新增小节说明代码库中是否存在 _impl 后缀函数模式，明确结论为未见此模式
2. `rewrite_paragraph` — 在系统调用覆盖度统计部分，补充与 README 文档声称功能的对比，说明是否存在冲突
3. `add_evidence` — 在用户指针校验部分补充 fetchaddr 函数的源码路径与逻辑说明

_结构化完整数据：`05_trap_syscall_review.json`_
