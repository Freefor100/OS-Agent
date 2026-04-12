# 审阅说明 · 安全机制与权限模型

- **stage_id**: `10_security`
- **passed**: True
- **score**: 0.9
- **severity**: minor

## missing_evidence
- {'paragraph_id': '特权级与隔离机制', 'claim_id': '项目仅支持 riscv64 架构', 'reason': '架构范围结论未提供构建配置（如 Makefile）或目录结构路径作为证据，仅凭文本陈述'}

## weak_claims
- {'paragraph_id': '特权级与隔离机制', 'claim': '项目仅支持 riscv64 架构，未发现多架构支持', 'reason': '缺乏配置文件佐证，虽符合项目命名惯例但证据链不完整'}

## repair_actions（人工改进建议，不自动执行）
1. `add_evidence` — 补充 Makefile 或 arch 目录列表的具体文件路径，证明项目仅支持 riscv64
2. `normalize_terminology` — 确保所有状态标记（✅/❌/🔸）在图例中统一说明

_结构化完整数据：`10_security_review.json`_
