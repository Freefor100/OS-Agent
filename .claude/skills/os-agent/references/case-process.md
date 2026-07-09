# 分工顺序

评审案件按下面顺序推进：

`works.yaml -> init -> scope -> fp_cache/search -> base.md -> base-delta evidence -> 任务文件 -> subagents -> contradictions -> report.md -> report_data.json -> review_viewer`.

不要跳阶段。校验失败时，根据错误码回到对应阶段重做，不允许在渲染或组装时容错修补。

fingerprint 是跨作品缓存，批量命令写入 `fp_cache/`；单作品 `output/<work_id>/case_state/` 只保存 `case_state/fp_manifest.json`、`case_state/base_candidates.json` 和证据摘要。
