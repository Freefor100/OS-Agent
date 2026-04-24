# Baseline vs Agent — 逐题对比表索引（本目录以 `oskernel2023-zmz` 为例）

**多仓库差异摘录**：见仓库根 [`output/baseline_agent_diffs_index.md`](../baseline_agent_diffs_index.md)。  
全仓重生成：`python3 output/oskernel2023-zmz/baseline_vs_agent_review_audit/export_diffs_with_evidence.py`（在 `OS-Agent` 根目录执行）。

---

以下说明原先生成逻辑；`diffs_with_evidence.md` 仍由脚本写入本目录。

生成自 `baseline_output/oskernel2023-zmz/_per_stage` 与 `output/oskernel2023-zmz/_per_stage`。
`agreement` 为字面规范化后的初分：`一致` / `表述差异` / `结论冲突`（结构化题型 value 不同）。
`better_side` 初值为 `待核验`（结构化冲突）或 `待酌`（长文本差异）；**以 `kernel_verification.md` 与 `synthesis.md` 为准**。

`single_choice` 在判「一致」时已剥离 `A.` 类前缀（减少假阳性）。

## 汇总与核验

- **[diffs_with_evidence.md](diffs_with_evidence.md)** — **盲评版**：文头仅仓库名；每题先 `### id·题型`，再 `###` + **题干全文**（单行）；表列 **方法A / 方法B**。机器可读：[diffs_with_evidence.json](diffs_with_evidence.json)    
- [kernel_verification.md](kernel_verification.md) — **仅在 `repos/oskernel2023-zmz`** 上对实质分歧题的裁定  
- [synthesis.md](synthesis.md) — Review 效果与 `report_quality_score` 说明  
- [pseudo_conflict_explanation.md](pseudo_conflict_explanation.md) — 仍可能存在的格式/多选 JSON 差异说明  

## 分章表

- [02_boot_trap](02_boot_trap_comparison.md) — 一致 18 / 表述差异 16 / 结论冲突 0
- [03_mem_mgmt](03_mem_mgmt_comparison.md) — 一致 20 / 表述差异 11 / 结论冲突 3
- [04_process_smp](04_process_smp_comparison.md) — 一致 25 / 表述差异 14 / 结论冲突 2
- [05_fs_drivers](05_fs_drivers_comparison.md) — 一致 21 / 表述差异 9 / 结论冲突 5
- [06_sync_ipc](06_sync_ipc_comparison.md) — 一致 13 / 表述差异 5 / 结论冲突 2
- [07_security](07_security_comparison.md) — 一致 10 / 表述差异 3 / 结论冲突 1
- [08_network](08_network_comparison.md) — 一致 6 / 表述差异 1 / 结论冲突 0
- [09_debug_error](09_debug_error_comparison.md) — 一致 4 / 表述差异 2 / 结论冲突 2
