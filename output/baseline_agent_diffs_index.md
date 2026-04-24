# Baseline vs Agent 答案差异摘录（索引）

由 `output/oskernel2023-zmz/baseline_vs_agent_review_audit/export_diffs_with_evidence.py` 生成。  
条件：`baseline_output/<repo>/_per_stage` 与 `output/<repo>/_per_stage` 均存在，且各章有 `*_answers.json`。

| 仓库 | 差异题数 | `diffs_with_evidence.md` |
|------|-----------|---------------------------|
| oskernel2023-avx | 48 | [oskernel2023-avx/baseline_vs_agent_review_audit/diffs_with_evidence.md](oskernel2023-avx/baseline_vs_agent_review_audit/diffs_with_evidence.md) |
| oskernel2023-zmz | 76 | [oskernel2023-zmz/baseline_vs_agent_review_audit/diffs_with_evidence.md](oskernel2023-zmz/baseline_vs_agent_review_audit/diffs_with_evidence.md) |
| oskernrl2022-rv6 | 91 | [oskernrl2022-rv6/baseline_vs_agent_review_audit/diffs_with_evidence.md](oskernrl2022-rv6/baseline_vs_agent_review_audit/diffs_with_evidence.md) |
| xv6-k210 | 82 | [xv6-k210/baseline_vs_agent_review_audit/diffs_with_evidence.md](xv6-k210/baseline_vs_agent_review_audit/diffs_with_evidence.md) |

重生成（在仓库根目录执行）：

```bash
python3 output/oskernel2023-zmz/baseline_vs_agent_review_audit/export_diffs_with_evidence.py
python3 output/oskernel2023-zmz/baseline_vs_agent_review_audit/export_diffs_with_evidence.py xv6-k210   # 仅一仓
```
