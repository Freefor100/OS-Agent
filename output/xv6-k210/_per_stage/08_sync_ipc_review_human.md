# 审阅说明 · 同步互斥与进程间通信

- **stage_id**: `08_sync_ipc`
- **passed**: False
- **score**: 0.85
- **severity**: minor

## failed_rules
- `must_cover_gap`

## missed_modules
- `RwLock`

## missing_evidence
- {'paragraph_id': None, 'claim_id': None, 'reason': 'must_cover 要求覆盖 RwLock 锁机制实现状态，正文完全未提及 RwLock'}
- {'paragraph_id': None, 'claim_id': None, 'reason': 'must_cover 要求说明 sleep/wakeup 不变量（如锁持有要求），正文仅展示代码未明确论述不变量规则'}

## weak_claims
- {'paragraph_id': None, 'claim_id': None, 'reason': 'SleepLock 部分未明确验证 sleep 调用前的锁持有不变量，仅展示代码片段'}

## repair_actions（人工改进建议，不自动执行）
1. `append_missing_module` — 补充 RwLock 实现状态（已实现/未实现）及对应源码路径
2. `rewrite_paragraph` — 在 sleep/wakeup 章节明确论述不变量规则（如调用 sleep 前必须持有锁）而非仅展示代码片段

_结构化完整数据：`08_sync_ipc_review.json`_
