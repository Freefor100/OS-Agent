# 审阅说明 · 内存管理（物理/虚拟/分配器）

- **stage_id**: `03_mem_mgmt`
- **passed**: False
- **score**: 0.85
- **severity**: minor

## failed_rules
- `must_cover_gap`
- `inconsistent_claim`

## missed_modules
- `vm.c:unmappages`
- `feature_config`

## missing_evidence
- {'paragraph_id': '虚拟内存与页表操作', 'claim_id': 'unmappages 实现', 'reason': 'must_cover 明确要求展示 vm.c 中 unmappages() 解映射实现代码，正文仅提供了 walk() 和 mappages() 的代码片段，缺失 unmappages 相关源码证据'}
- {'paragraph_id': '高级内存特性清单', 'claim_id': 'feature 控制的内存子系统裁剪', 'reason': 'must_cover 要求说明 feature 控制的内存子系统裁剪情况，正文未提及该特性是否存在、实现状态或搜索依据'}

## weak_claims
- {'paragraph_id': '双链表分配器设计', 'claim_id': '双链表结构', 'reason': "正文标题及描述声称采用'双链表'结构，但展示的 struct run 定义仅包含 next 指针（单链表特征），技术术语与代码证据存在矛盾，易误导读者"}

## repair_actions（人工改进建议，不自动执行）
1. `add_evidence` — 补充 vm.c 中 unmappages() 或 uvmunmap() 的核心代码片段，以完整覆盖 must_cover 中关于解映射实现的要求
2. `append_missing_module` — 增加关于'feature 控制的内存子系统裁剪'的判定项，明确说明是否支持及代码依据（如搜索宏定义结果或明确标注未找到）
3. `normalize_terminology` — 核实分配器链表类型，若 struct run 仅含 next 指针，应修正术语为'单链表'或'双区单链表'，确保描述与代码定义一致

_结构化完整数据：`03_mem_mgmt_review.json`_
