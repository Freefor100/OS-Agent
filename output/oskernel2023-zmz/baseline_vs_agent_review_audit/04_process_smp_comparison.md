# 04_process_smp — Baseline vs Agent

- 题库题数: 41
- baseline `report_quality_score`: 0.97
- agent `report_quality_score`: 0.99

| question_id | type | agreement | better_side(初值) | baseline_se | baseline_sc | agent_se | agent_sc | baseline_value | agent_value |
|---|---|:---|:---|---:|---:|---:|---:|---|---|
| Q04_001 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 1.00 | 顶层类型名：proc<br>结构体路径：include/sched/proc.h<br>关键字段：Context=context, State=state, PID=pid, TrapFrame=trapframe<br>是否区分 PCB 与 TCB：否 | 顶层类型名: struct proc（进程控制块 PCB）<br>结构体路径: include/sched/proc.h:51<br>关键字段: Context=context (include/sched/proc.h:93), State=state (enum procstate, include/sched/proc.h:38), PID=pid (include/sched/proc.h:55), TrapFrame=t... |
| Q04_002 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 状态枚举：RUNNABLE, RUNNING, SLEEPING, ZOMBIE<br>流转点：scheduler() 选择 RUNNABLE->RUNNING, sleep() 导致 RUNNING->SLEEPING, wakeup() 导致 SLEEPING->RUNNABLE, exit() 导致 RUNNING->ZOMBIE | 状态枚举 (include/sched/proc.h:38-41): RUNNABLE, RUNNING, SLEEPING, ZOMBIE<br>流转点:<br>- RUNNABLE→RUNNING: scheduler() 中选中后设置 state=RUNNING (kernel/sched/proc.c:672)<br>- RUNNING→SLEEPING: sleep() 调用 sched() 前设置 state=SLEE... |
| Q04_003 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q04_004 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 1.00 | 1.00 | 保存的寄存器：ra, sp, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11 (callee-saved registers) | 保存的寄存器 (kernel/sched/swtch.S:12-26): ra, sp, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11（共 14 个 RISC-V 被调用者保存寄存器）。不保存调用者保存寄存器（如 a0-a7, t0-t6）或程序计数器（由 ra 间接保存）。 |
| Q04_005 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 算法名称：Priority<br>代码证据（关键字段/函数）：<br>  - Priority: priority 字段参与 pick_next 排序证据=proc_runnable[PRIORITY_NUMBER] 数组，__get_runnable_no_lock() 按优先级顺序选择 | 算法名称: Priority（优先级调度）+ Round-Robin (RR) 混合<br>代码证据:<br>- 优先级队列: PRIORITY_TIMEOUT=0, PRIORITY_IRQ=1, PRIORITY_NORMAL=2 (kernel/sched/proc.c:239-242)<br>- 时间片机制: proc_tick() 中递减 timer 字段，超时则从 PRIORITY_IRQ/PRIORITY_NORMA... |
| Q04_006 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 核心入口：scheduler() in kernel/sched/proc.c<br>关键函数：sched(), yield(), __get_runnable_no_lock() | 核心入口:<br>1. scheduler() (kernel/sched/proc.c:658): 主调度循环，每核进入后无限循环选择 runnable 进程<br>2. sched() (kernel/sched/proc.c:701): 主动让出 CPU，调用 swtch() 切换到 scheduler<br>3. __get_runnable_no_lock() (kernel/sched/proc.c:596): 按优先... |
| Q04_007 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q04_008 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 1.00 | 是，复制地址空间通过 copysegs() in kernel/mm/usrmm.c，复制文件表通过 copyfdtable() in kernel/fs/file.c | 是，完整复制:<br>- 地址空间: np->segment = copysegs(p->pagetable, p->segment, np->pagetable) (kernel/sched/proc.c:302)<br>- 文件表: copyfdtable(&p->fds, &np->fds) (kernel/sched/proc.c:317)<br>- 当前目录: np->cwd = idup(p->cwd) (kernel... |
| Q04_009 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q04_010 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q04_011 | single_choice | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | A. 真正阻塞：移出就绪队列 + WaitQueue/条件变量唤醒 (Wait Queue or Condition Variable) | 真正阻塞：移出就绪队列 + WaitQueue/条件变量唤醒 (Wait Queue or Condition Variable) |
| Q04_012 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 1.00 | 自增计数器，全局变量__pid 在 kernel/sched/proc.c 中递增分配 | 单调自增分配（只分配不回收）:<br>- 全局变量: int __pid (kernel/sched/proc.c:36)<br>- 分配逻辑: p->pid = __pid++ (kernel/sched/proc.c:228)，在 hash_lock 保护下原子递增<br>- 无回收机制：未见 free_pid() 或 pid 复用逻辑 |
| Q04_013 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 1.00 | 1.00 | 使用 children 链表 + parent+sibling 指针：struct proc 中有 child, parent, sibling_next, sibling_pprev 字段 | 双向链表 +  sibling 指针 (include/sched/proc.h:71-74):<br>- child: struct proc *child（指向第一个子进程）<br>- sibling_next: struct proc *sibling_next（指向下一个兄弟）<br>- sibling_pprev: struct proc **sibling_pprev（指向前一个兄弟的 sibling_next 字段）... |
| Q04_014 | tri_state_impl | 一致 | tie | 0.85 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q04_015 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 不存在每核运行队列，使用全局 proc_runnable 数组；无任务迁移；无 IPI resched 实现 | 每核调度：每核独立调用 scheduler() 循环 (kernel/main.c:104)，共享全局 proc_runnable[] 数组<br>任务迁移：未发现显式负载均衡/迁移逻辑<br>IPI resched：未发现 IPI 触发 resched 路径<br>锁保护：proc_lock 保护全局 runnable 队列访问 (kernel/sched/proc.c:277-284) |
| Q04_016 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 1.00 | exit() -> freeproc() -> 回收 pagetable, trapframe, kstack, signal handlers; 通知父进程通过 wakeup(p->parent) | 调用链 (kernel/sched/proc.c:392-458):<br>1. delsegs(p->pagetable, p->segment) - 释放地址空间段<br>2. uvmfree(p->pagetable) - 释放页表<br>3. dropfdtable(&p->fds) - 关闭文件表<br>4. iput(p->cwd), iput(p->elf) - 释放 inode<br>5. 子进程重父：将所有子进程... |
| Q04_017 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_018 | tri_state_impl | 结论冲突 | 待核验 | 0.90 | 1.00 | 1.00 | 1.00 | not_found | stub |
| Q04_019 | single_choice | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | B. 仅有统一 Task 结构（无区分） | 仅有统一 Task 结构（无区分） |
| Q04_020 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q04_021 | single_choice | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | D. 仅内核线程（无独立用户线程库） | 仅内核线程（无独立用户线程库） |
| Q04_022 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_023 | multi_choice | 结论冲突 | 待核验 | 0.95 | 1.00 | 0.90 | 1.00 | ["F. 未发现调度性能统计"] | ["等待时间 (Waiting Time)"] |
| Q04_024 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_025 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_026 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | A. 完全抢占 (Fully Preemptive)：时钟中断可随时抢占运行进程 | 完全抢占 (Fully Preemptive)：时钟中断可随时抢占运行进程 |
| Q04_027 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_028 | single_choice | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | A. SMP（对称多处理） | SMP（对称多处理） |
| Q04_029 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q04_030 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q04_031 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 1.00 | 发送路径：sbi_send_ipi() in include/sbi.h<br>处理路径：通过 CLINT 软件中断，在 kernel/trap/trap.c 的 handle_intr() 中处理 INTR_SOFTWARE | 发送路径:<br>- kernel/main.c:78-79: sbi_send_ipi(mask, 0) - BSP 唤醒 AP<br>- sbi/psicasbi/src/trap/sbi/ipi.rs:28-32: clint::send_ipi(i) - SBI 层实现<br><br>处理路径:<br>- kernel/trap/trap.c:373: sbi_clear_ipi() - 清除 IPI 标志<br>- sb... |
| Q04_032 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q04_033 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 1.00 | 1.00 | 使用 tp 寄存器存储 hartid，通过 cpuid() 返回 r_tp() 值索引 cpus[] 数组 | 数组索引 + tp 寄存器 (include/sched/proc.h:165-168):<br>- cpuid() 通过 r_tp() 读取 tp 寄存器获取当前 hartid<br>- mycpu() 返回 &cpus[cpuid()]<br>- 每核栈空间：kernel/main.c:93-94 中通过 boot_stack + hartid * 4 * PGSIZE 计算 |
| Q04_034 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_035 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_036 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.75 | 1.00 | 03 TLB: 多核页表修改后 TLB 刷新策略=单核 sfence.vma，多核无 shootdown<br>04 调度：每核运行队列/负载均衡/IPI resched=全局队列，无负载均衡，无 IPI resched<br>05 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上线顺序=每核独立 trapinithart()，BSP 先初始化后唤醒 AP<br>08 锁：SpinLock 关中断行为在多核下是... | 03 TLB: 多核页表修改后 TLB 刷新策略=未发现跨核 TLB 刷新机制，仅单核 sfence_vma() (kernel/sched/proc.c:675)<br>04 调度: 每核运行队列/负载均衡/IPI resched=全局 proc_runnable[] 数组 + proc_lock 保护，无每核队列/负载均衡/IPI resched<br>05 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上... |
| Q04_037 | single_choice | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | A. 是，获取时关中断、释放时恢复 | 是，获取时关中断、释放时恢复 |
| Q04_038 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | NCPU=2 in include/param.h，链接脚本 linker/linker64.ld 中 boot_stack 分配 4096*4*2 字节支持 2 核 | NCPU=2 (include/param.h:5)<br>链接脚本：linker/qemu.ld 未显式定义每 hart 栈布局<br>启动代码：kernel/main.c:93-94 中通过 boot_stack + hartid * 4 * PGSIZE 计算每核栈，每核 4 页 (16KB)<br>对应关系：NCPU=2 与 main.c 中 for 循环 (i=1; i<NCPU) 一致，但链接脚本未显式定义 hart 栈区 |
| Q04_039 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_040 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q04_041 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |

统计: 一致=25, 表述差异=14, 结论冲突=2
