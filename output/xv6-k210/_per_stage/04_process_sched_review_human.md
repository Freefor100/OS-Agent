# 审阅说明 · 进程/线程与调度机制

- **stage_id**: `04_process_sched`
- **passed**: True
- **score**: 0.95
- **severity**: minor

## repair_actions（人工改进建议，不自动执行）
1. `rewrite_paragraph` — 在分析 `pick_next_task`/`schedule` 时，显式用文字标注 `w_satp(MAKE_SATP(tmp->pagetable))` 为与地址空间模块的‘硬耦合点’，以满足 must_cover 中关于明确指出的要求。
2. `rewrite_paragraph` — 修正 `proc_tick` 逻辑描述：代码显示 `if (RUNNING != p->state)` 即递减就绪队列中进程的时间片，而非‘RUNNING 态’进程，请确保文字描述与代码证据严格一致。

_结构化完整数据：`04_process_sched_review.json`_
