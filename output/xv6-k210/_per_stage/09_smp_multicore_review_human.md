# 审阅说明 · 多核支持与并行机制

- **stage_id**: `09_smp_multicore`
- **passed**: False
- **score**: 0.85
- **severity**: major

## failed_rules
- `must_cover_gap`

## missing_evidence
- {'paragraph_id': '多核架构设计（SMP/AMP）', 'claim_id': 'NCPU 配置', 'reason': 'must_cover 明确要求分析「NCPU=2 配置与 link-k210.ld 中_max_hart_id=1 的对应关系」，正文仅引用 include/param.h:5，缺失链接脚本配置证据'}

## repair_actions（人工改进建议，不自动执行）
1. `add_evidence` — 补充 link-k210.ld 文件分析，明确指出 _max_hart_id=1 如何限制硬件可用核数，并说明其与 NCPU=2 宏定义的对应逻辑

_结构化完整数据：`09_smp_multicore_review.json`_
