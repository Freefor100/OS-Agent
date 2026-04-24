# Review 效果与总分并列的综合说明

## 1. 数据来源

- 逐题表：`02_boot_trap_comparison.md` … `09_debug_error_comparison.md`（由 `generate_audit_tables.py` 从 JSON 汇总）。
- 事实裁定：**仅**见 `kernel_verification.md`（仓库 `/home/leo/OS-Agent/repos/oskernel2023-zmz`）。
- 假阳性说明：`pseudo_conflict_explanation.md`（大量 `single_choice` 仅差 `A.` 前缀被判「结论冲突」）。

## 2. 为何 baseline / agent `review_score.json` 总分可同为 96？

管线（`DESCRIBE_REVIEW_SYSTEM_PROMPT` + `enrich_review_with_report_quality`）评的是 **单次答案 JSON** 的：

1. 题面约束是否满足；  
2. 字段契约；  
3. **`evidence` 摘录能否支撑当题的 `value`**。

**不**打开真实仓库、**不**与另一套答案对照。因此：

- 两套答案只要 **各自自洽**、证据像样，**章级 `report_quality_score` 都可落在 0.9+**。  
- **总分**为 8 章均值：一章略低可被另一章略高拉回，**总分相同不表示与内核一致度相同**。

本批数据中 **agent 在 05_fs_drivers 章明显更低（0.92 vs 0.99）**，与 **Q05_010 等实质误判**方向一致，说明 review **对「本套答案内部证据不足」仍有一定灵敏度**，但 **无法保证与「跨 run 真值」对齐**。

## 3. Review 分数 vs 内核裁定：错侧反而更高分的例子

| 题号 | 内核更优侧 | baseline 均分 `(se+sc)/2` | agent 均分 | 说明 |
|------|------------|---------------------------|------------|------|
| **Q05_010** | baseline | 1.00 | 0.85 | agent 将已实现 `pselect` 判为 `stub`，评审仍给 agent 较高证据分，**未对照仓库**无法发现。 |
| **Q03_009** | baseline | 0.975 | 0.95 | agent 错选「共享页表」，两侧 review 仍接近满分档，体现 **「题面↔自洽证据」≠ 真值**。 |
| **Q09_005** | agent | 0.95 | 0.95 | 三态结论相反但逐题均分相同，说明评审 **未按 Stallings 内核 monitor 定义** 收紧证据。 |

（均分来自各章 `*_review.json` 中 `question_reviews` 的 `score_evidence`、`score_consistency`。）

## 4. 结论（给评测/迭代用）

1. **`report_quality_score` 适合衡量「报告片段质量」**，不适合作为 **跨 baseline/agent 的 ground-truth 排名**。  
2. 若要对齐真值，必须在 **`oskernel2023-zmz` 源码**上做 **冲突题后验**（见 `kernel_verification.md`）。  
3. 自动化对比表应 **规范化单选题字符串**（去掉 `A.` 前缀），减少假阳性「结论冲突」行数。

## 5. 章级统计（`agreement` 列；`single_choice` 已剥离 `A.` 前缀后再比）

| stage_id | 一致 | 表述差异 | 结论冲突 |
|----------|------|----------|----------|
| 02_boot_trap | 18 | 16 | 0 |
| 03_mem_mgmt | 20 | 11 | 3 |
| 04_process_smp | 25 | 14 | 2 |
| 05_fs_drivers | 21 | 9 | 5 |
| 06_sync_ipc | 13 | 5 | 2 |
| 07_security | 10 | 3 | 1 |
| 08_network | 6 | 1 | 0 |
| 09_debug_error | 4 | 2 | 2 |

更细粒度 **better_side** 以 `kernel_verification.md` 为准；`multi_choice` 的 JSON 字符串差异仍可能产生「结论冲突」行，见 `pseudo_conflict_explanation.md`。
