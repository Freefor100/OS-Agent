# 06_sync_ipc — Baseline vs Agent

- 题库题数: 20
- baseline `report_quality_score`: 0.95
- agent `report_quality_score`: 0.95

| question_id | type | agreement | better_side(初值) | baseline_se | baseline_sc | agent_se | agent_sc | baseline_value | agent_value |
|---|---|:---|:---|---:|---:|---:|---:|---|---|
| Q06_001 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 1.00 | 1.00 | SpinLock: include/sync/spinlock.h struct spinlock { uint locked; char *name; struct cpu *cpu; }; SleepLock: include/sync/sleeplock.h struct sleeplock { uint locked; struct spinlock lk; char *name; int pid; }; WaitQueu... | 已实现 SpinLock（自旋锁）、SleepLock（睡眠锁）、WaitQueue（等待队列）。证据：`include/sync/spinlock.h:7-13` 定义 `struct spinlock`（含 `locked`、`name`、`cpu` 字段）；`include/sync/sleeplock.h:9-16` 定义 `struct sleeplock`（含 `locked`、`lk`、`name`、`pid` 字段... |
| Q06_002 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | B. 阻塞锁（Blocking Mutex，进入等待队列并挂起） | 阻塞锁（Blocking Mutex，进入等待队列并挂起） |
| Q06_003 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q06_004 | fill_in | 表述差异 | 待酌 | 0.90 | 1.00 | 0.80 | 0.90 | sleep 入口函数：kernel/sched/proc.c::sleep()<br>入睡前持有的锁：传入的 lk（调用者持有）+ proc_lock（内部获取）<br>防丢 wakeup (Lost Wakeup Prevention) 机制：持队列锁检查条件 / 在 proc_lock 保护下插入睡眠队列<br>wakeup 函数：kernel/sched/proc.c::wakeup()<br>唤醒与锁释放顺序：先唤醒后释放... | sleep 入口函数: kernel/sched/proc.c:569 (sleep)<br>入睡前持有的锁: 必须持有 proc_lock 或传入的 lk（若 lk 非 proc_lock 则释放 lk 后持 proc_lock 进入 sleep）<br>防丢 wakeup (Lost Wakeup Prevention) 机制: 持 proc_lock 检查条件并进入睡眠，wakeup 也持 proc_lock 遍历睡眠队列，... |
| Q06_005 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q06_006 | single_choice | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | A. 字节环形缓冲区 (ring buffer) | 字节环形缓冲区 (ring buffer) |
| Q06_007 | single_choice | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | A. 阻塞：挂起当前线程/任务进入等待队列 | 阻塞：挂起当前线程/任务进入等待队列 |
| Q06_008 | tri_state_impl | 一致 | tie | 0.85 | 1.00 | 0.85 | 1.00 | not_found | not_found |
| Q06_009 | tri_state_impl | 一致 | tie | 0.85 | 1.00 | 0.85 | 1.00 | not_found | not_found |
| Q06_010 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q06_011 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 0.95 | 1.00 | 用户态 handler 上下文构建：在 kernel/sched/signal.c::sighandle() 中，分配 sig_frame 结构保存当前 trapframe，设置新的 trapframe 指向 sig_trampoline 中的 sig_handler。sigreturn 恢复：存在，在 kernel/sched/signal.c::sigreturn() 中从 sig_frame 链表中恢复之前的 trapfra... | 用户态 handler 上下文构建：在 kernel/sched/signal.c:177-264 的 sighandle() 中，分配 sig_frame 保存原 trapframe（`frame->tf = p->trapframe`），新建 trapframe 设置 epc 为 sig_trampoline 中的 sig_handler 地址（`tf->epc = (uint64)(SIG_TRAMPOLINE + ((ui... |
| Q06_012 | single_choice | 一致 | tie | 0.85 | 1.00 | 0.85 | 1.00 | C. 未发现/不支持 | 未发现/不支持 |
| Q06_013 | single_choice | 结论冲突 | 待核验 | 0.30 | 1.00 | 0.85 | 1.00 | A. Rust core::sync::atomic（标准库） | 自定义汇编（ldxr/stxr、lock xchg 等） |
| Q06_014 | short_answer | 表述差异 | 待酌 | 0.90 | 1.00 | 0.90 | 1.00 | 互斥 Mutual Exclusion：成立。spinlock 使用__sync_lock_test_and_set 保证同一时刻只有一个 CPU 持有锁。持有并等待 Hold-and-Wait：成立。sleep() 函数中进程持有 lk 锁时调用 sched() 放弃 CPU，可能等待其他资源。不可剥夺 No Preemption：成立。锁只能由持有者主动 release() 释放，内核不会强制剥夺。循环等待 Circular ... | 1. 互斥 (Mutual Exclusion)：成立。SpinLock 通过原子操作 `__sync_lock_test_and_set` 确保同一时刻仅一个 CPU 持有锁（`kernel/sync/spinlock.c:34`）。SleepLock 在 spinlock 基础上增加睡眠机制，同样保证互斥（`kernel/sync/sleeplock.c:22-28`）。<br>2. 持有并等待 (Hold-and-Wait)... |
| Q06_015 | single_choice | 一致 | tie | 0.85 | 1.00 | 0.85 | 1.00 | D. 忽略 (Ostrich Algorithm)：不处理，依赖外部重启 | 忽略 (Ostrich Algorithm)：不处理，依赖外部重启 |
| Q06_016 | tri_state_impl | 一致 | tie | 0.85 | 1.00 | 0.85 | 1.00 | not_found | not_found |
| Q06_017 | tri_state_impl | 结论冲突 | 待核验 | 0.90 | 1.00 | 0.85 | 1.00 | implemented | not_found |
| Q06_018 | short_answer | 表述差异 | 待酌 | 0.90 | 1.00 | 0.90 | 1.00 | 生产者 - 消费者 (Producer-Consumer / Bounded Buffer)：implemented - kernel/fs/pipe.c 中的 pipe 实现使用环形缓冲区和 wait_queue 实现生产者 - 消费者模式<br>读者 - 写者 (Readers-Writers)：not_found - 未找到读写锁或读者 - 写者问题测试代码<br>哲学家就餐 (Dining Philosophers)：no... | 生产者 - 消费者 (Producer-Consumer / Bounded Buffer)：not_found（管道 pipe 实现了有界缓冲区的生产者 - 消费者模式，但无专门的测试或示例代码；`kernel/fs/pipe.c` 使用 PIPESIZE=1024 的环形缓冲，pipewrite 为生产者，piperead 为消费者）<br>读者 - 写者 (Readers-Writers)：not_found（未实现读写锁，... |
| Q06_019 | tri_state_impl | 一致 | tie | 0.85 | 1.00 | 0.85 | 1.00 | not_found | not_found |
| Q06_020 | tri_state_impl | 一致 | tie | 0.85 | 1.00 | 0.85 | 1.00 | not_found | not_found |

统计: 一致=13, 表述差异=5, 结论冲突=2
