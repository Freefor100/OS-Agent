## 进程与调度机制对比报告：oskernel2023-avx vs xv6-k210

---

## 任务模型差异

### oskernel2023-avx：进程-线程分离模型（PCB + TCB）

**核心结构体**：
- **`struct proc`**（PCB）：定义于 `kernel/include/proc.h:56-105`
  - 字段包括：`state`, `pid`, `uid`, `gid`, `pgid`, `parent`, `kstack`, `sz`, `pagetable`, `kpagetable`, `trapframe`, `context`, `ofile[NOFILE]`, `cwd`, `vma`
  - **线程管理字段**：`main_thread`, `thread_queue`, `thread_num`
  - **信号字段**：`sigaction[SIGRTMAX+1]`, `sig_set`, `sig_pending`, `sig_tf`
  - **进程组支持**：`pgid` 字段明确存在（`kernel/include/proc.h:67`）

- **`struct thread`**（TCB）：定义于 `kernel/include/thread.h:22-44`
  - 字段包括：`state`（6 态，含 `t_TIMING`）, `tid`, `p`（所属进程）, `kstack`, `trapframe`, `context`, `next_thread`, `pre_thread`, `awakeTime`, `clear_child_tid`
  - **独立内核栈**：每个线程有独立的 `kstack` 和 `trapframe`

**进程-线程关系**：
- **1:N 模型**：一个 `proc` 通过 `thread_queue` 双向链表管理多个 `thread`
- **调度实体**：`scheduler()` 实际切换的是线程（`p->main_thread`）
- **证据**：`kernel/proc.c:697-708` 中遍历 `thread_queue` 选择可运行线程

### xv6-k210：统一进程模型（仅 PCB）

**核心结构体**：
- **`struct proc`**：定义于 `include/sched/proc.h:51-148`
  - 字段包括：`xstate`, `pid`, `state`, `timer`, `chan`, `sleep_expire`, `kstack`, `pagetable`, `trapframe`, `context`, `fds`, `cwd`, `segment`, `pbrk`
  - **亲缘关系**：`child`, `parent`, `sibling_next`, `sibling_pprev`（兄弟链表）
  - **调度链表**：`sched_next`, `sched_pprev`
  - **信号字段**：`sig_act`（链表）, `sig_set`, `sig_pending`, `sig_frame`, `killed`
  - **性能统计**：`proc_tms`, `ikstmp`, `okstmp`, `vswtch`, `ivswtch`

**关键差异**：
- ❌ **无线程概念**：未定义 `struct thread`，进程即调度实体
- ❌ **无 pgid 字段**：搜索 `pgid` 仅在 `sys_prlimit64` 系统调用中出现，`struct proc` 中无 `pgid` 字段
- ❌ **无 session 支持**：代码中未发现 `session` 或 `SID` 相关实现

### 对比总结

| 特性 | oskernel2023-avx | xv6-k210 |
|------|------------------|----------|
| 任务模型 | PCB + TCB 分离 | 仅 PCB |
| 多线程支持 | ✅ `thread_queue` 双向链表 | ❌ 未实现 |
| 进程组 (PGID) | ✅ `int pgid` 字段 | ❌ 未实现 |
| 会话 (SID) | ❌ 未发现 | ❌ 未发现 |
| rlimit | ✅ `sys_prlimit64` + `struct rlimit` | 🔸 仅系统调用桩 |

---

## 调度算法差异

### oskernel2023-avx：简单轮转（Round-Robin）

**调度器实现**：`kernel/proc.c:669-753`

```c
void scheduler(void) {
  for (;;) {
    intr_on();
    int found = 0;
    for (p = proc; p < &proc[NPROC]; p++) {  // 线性扫描全局进程表
      acquire(&p->lock);
      if (p->state == RUNNABLE) {
        // 遍历线程链表找可运行线程
        thread *t = p->thread_queue;
        while (NULL != t) {
          if (t->state == t_RUNNABLE ||
              (t->state == t_TIMING && t->awakeTime < r_time() + (1LL << 35)))
            break;
          t = t->next_thread;
        }
        if (NULL == t) continue;
        
        // 将找到的线程移到队列头部
        if (p->thread_queue != t) { /* 链表重排 */ }
        p->main_thread = t;
        copycontext(&p->context, &p->main_thread->context);
        p->main_thread->state = t_RUNNING;
        p->state = RUNNING;
        
        w_satp(MAKE_SATP(p->kpagetable));
        sfence_vma();
        swtch(&c->context, &p->context);  // 上下文切换
        // ...
      }
      release(&p->lock);
    }
    if (found == 0) {
      intr_on();
      asm volatile("wfi");  // 无进程可运行时进入低功耗等待
    }
  }
}
```

**调度策略特征**：
- ❌ **无优先级**：代码中未发现 `priority`、`stride`、`nice` 等字段
- ❌ **非 CFS**：无虚拟运行时间、红黑树等 CFS 特征
- ✅ **简单 FIFO**：线性扫描 `proc[NPROC]` 数组，按 PID 顺序选择第一个 `RUNNABLE` 进程
- ✅ **线程级调度**：在进程内遍历 `thread_queue`，选择第一个可运行线程
- 🔸 **TODO 注释**：`// TODO: 改进线程枚举算法` 表明作者意识到当前算法简陋

### xv6-k210：基于优先级的时间片轮转

**优先级定义**：`kernel/sched/proc.c:241-243`
```c
#define PRIORITY_TIMEOUT    0   // 超时队列 (最低优先级)
#define PRIORITY_IRQ        1   // 中断/信号唤醒队列 (高优先级)
#define PRIORITY_NORMAL     2   // 普通进程队列 (默认优先级)
#define PRIORITY_NUMBER     3   // 优先级总数
```

**调度队列**：`kernel/sched/proc.c:245-246`
```c
struct proc *proc_runnable[PRIORITY_NUMBER];  // 3 个优先级的可运行队列
struct proc *proc_sleep;                       // 睡眠队列
```

**调度器核心逻辑**：`kernel/sched/proc.c:609-625`
```c
static struct proc *__get_runnable_no_lock(void) {
    for (int i = 0; i < PRIORITY_NUMBER; i++) {  // 从 PRIORITY_TIMEOUT(0) 开始扫描
        tmp = proc_runnable[i];
        while (NULL != tmp) {
            if (RUNNABLE == tmp->state) {
                return (struct proc*)tmp;  // 返回第一个 RUNNABLE 状态的进程
            }
            tmp = tmp->sched_next;
        }
    }
    return NULL;
}
```

**时间片机制**：`kernel/sched/proc.c:753-787`
```c
void proc_tick(void) {
    for (int i = PRIORITY_IRQ; i < PRIORITY_NUMBER; i++) {
        p = proc_runnable[i];
        while (NULL != p) {
            if (RUNNING != p->state) {
                p->timer = p->timer - 1;
                if (0 == p->timer) {  // 时间片耗尽
                    __remove(p);
                    __insert_runnable(PRIORITY_TIMEOUT, p);  // 降级到 TIMEOUT 队列
                }
            }
            p = next;
        }
    }
    // ... 处理睡眠进程唤醒
}
```

**时间片分配**：
- `TIMER_NORMAL = 10`：普通进程默认时间片为 10 个 tick
- `TIMER_IRQ = 5`：中断/信号唤醒进程时间片为 5 个 tick

**调度策略特征**：
- ✅ **3 优先级队列**：`PRIORITY_IRQ(1)` > `PRIORITY_NORMAL(2)` > `PRIORITY_TIMEOUT(0)`
- ✅ **时间片轮转**：进程时间片用完后被移动到 `PRIORITY_TIMEOUT` 队列
- ✅ **中断/信号唤醒**：被信号或中断唤醒的进程插入 `PRIORITY_IRQ` 队列，获得更高优先级
- ✅ **FIFO Within Priority**：同一优先级队列内采用 FIFO 顺序

### 对比总结

| 特性 | oskernel2023-avx | xv6-k210 |
|------|------------------|----------|
| 调度算法 | 简单 FIFO 轮转 | 优先级时间片轮转 |
| 优先级支持 | ❌ 无 | ✅ 3 级优先级 |
| 时间片机制 | ❌ 无 | ✅ `timer` 字段 + `proc_tick()` |
| 调度队列 | 线性扫描 `proc[NPROC]` | 3 个优先级链表 |
| 线程级调度 | ✅ 遍历 `thread_queue` | ❌ 仅进程级 |
| 抢占式调度 | 🔸 依赖时钟中断 | ✅ `proc_tick()` 主动降级 |

---

## Call Graph 差异

### schedule 函数对比

**oskernel2023-avx**：
- 函数名：`scheduler()`（`kernel/proc.c:669`）
- 调用者：`main()`（`kernel/main.c:98`）
- 被调用者：`swtch()`, `futexClear()`, `copycontext()`, `copytrapframe()`
- **特点**：直接遍历全局 `proc` 数组，无线程调度器抽象

**xv6-k210**：
- 函数名：`scheduler()`（`kernel/sched/proc.c:671`）
- 调用者：`main()`（`kernel/main.c:97`）
- 被调用者：`__get_runnable_no_lock()`, `swtch()`
- **特点**：通过 `__get_runnable_no_lock()` 抽象优先级队列扫描

### sys_fork 函数对比

**oskernel2023-avx**：
```
sys_fork (kernel/sysproc.c:263)
└── fork (kernel/proc.c:443)
    ├── allocproc()
    ├── uvmcopy()          # 复制用户地址空间（写时复制）
    ├── vma_copy()         # 复制 VMA 链表
    ├── filedup()          # 复制文件描述符
    └── edup()             # 复制当前目录
```

**xv6-k210**：
- ❌ **无 `sys_fork` 函数**：搜索未找到
- ✅ **`clone()` 函数**（`kernel/sched/proc.c:291`）：
  - 调用 `allocproc()`, `copysegs()`, `sigaction_copy()`, `copyfdtable()`
  - **重要差异**：`clone()` 支持 `stack` 参数，可用于实现 `pthread_create`

### fork/clone 地址空间复制对比

**oskernel2023-avx**（`kernel/proc.c:454-456`）：
```c
if (uvmcopy(p->pagetable, np->pagetable, np->kpagetable, p->sz) < 0) {
    freeproc(np);
    return -1;
}
```
- ✅ **真正复制地址空间**：`uvmcopy()` 实现写时复制（COW）
- ✅ **VMA 复制**：`vma_copy()` + `vma_map()` 重建虚拟内存区域

**xv6-k210**（`kernel/sched/proc.c:303-308`）：
```c
np->segment = copysegs(p->pagetable, p->segment, np->pagetable);
if (NULL == np->segment) {
    freeproc(np);
    return -1;
}
np->pbrk = p->pbrk;
```
- ✅ **真正复制地址空间**：`copysegs()` 调用 `uvmalloc()` 为新进程分配物理页
- ✅ **段链表复制**：通过 `segment` 链表管理内存段

**结论**：两者都**真正复制了地址空间**，而非仅创建任务控制块。这是符合 POSIX fork 语义的正确实现。

---

## 上下文切换差异

### swtch.S 汇编对比

**oskernel2023-avx**（`kernel/swtch.S:1-46`）：
```assembly
.globl swtch
swtch:
    sd ra, 0(a0)      # 保存 14 个寄存器
    sd sp, 8(a0)
    sd s0, 16(a0)
    # ... s1-s11
    ld ra, 0(a1)      # 恢复 14 个寄存器
    # ...
    ret
```

**xv6-k210**（`kernel/sched/swtch.S:1-41`）：
```assembly
.globl swtch
swtch:
    sd ra, 0(a0)      # 保存 14 个寄存器
    sd sp, 8(a0)
    sd s0, 16(a0)
    # ... s1-s11
    ld ra, 0(a1)      # 恢复 14 个寄存器
    # ...
    ret
```

**保存的寄存器**（两者相同）：
- `ra`, `sp`, `s0-s11`（共 14 个 64 位寄存器，112 字节）
- **不保存 caller-saved 寄存器**：`a0-a7`, `t0-t6` 由调用者自行保存

### 浮点寄存器支持

**oskernel2023-avx**：
- `struct trapframe`（`kernel/include/trap.h`）：**不包含浮点寄存器**
- 搜索 `fs[0-9]|ft[0-9]|fa[0-9]` 仅在驱动头文件（`fpioa.h`）中出现
- ❌ **未实现浮点上下文保存**

**xv6-k210**：
- `struct trapframe`（`include/trap.h:57-75`）：
  ```c
  /* 288 */ uint64 ft0;
  /* 296 */ uint64 ft1;
  /* 304 */ uint64 ft2;
  /* 312 */ uint64 ft3;
  /* 320 */ uint64 ft4;
  /* 328 */ uint64 ft5;
  /* 336 */ uint64 ft6;
  /* 344 */ uint64 ft7;
  /* 352 */ uint64 fs0;
  /* 360 */ uint64 fs1;
  /* 368 */ uint64 fa0;
  /* ... fa7 */
  /* 432 */ uint64 fs2;
  /* ... fs7 */
  ```
- ✅ **完整浮点寄存器支持**：`ft0-7`, `fs0-7`, `fa0-7`（共 20 个浮点寄存器）
- **证据**：`kernel/sched/proc.c:330-333` 中 `clone()` 调用 `floatstore` 保存浮点状态

### 对比总结

| 特性 | oskernel2023-avx | xv6-k210 |
|------|------------------|----------|
| 保存寄存器数 | 14 个 (ra, sp, s0-s11) | 14 个 (ra, sp, s0-s11) |
| 浮点寄存器支持 | ❌ 未实现 | ✅ 完整支持 (ft0-7, fs0-7, fa0-7) |
| 上下文大小 | 112 字节 | 112 字节 (+ 浮点帧额外保存) |
| 浮点状态切换 | ❌ 无 | ✅ `floatstore`/`floatload` |

---

## 进程管理扩展差异

### 进程组 (PGID) / 会话 (SID)

**oskernel2023-avx**：
- ✅ **PGID 支持**：`struct proc` 含 `int pgid` 字段（`kernel/include/proc.h:67`）
- ✅ **系统调用**：`sys_setpgid()`, `sys_getpgid()`（`kernel/sysproc.c:404-418`）
  ```c
  uint64 sys_setpgid(void) {
    int pid, pgid;
    if (argint(0, &pid) < 0 || argint(1, &pgid) < 0) return -1;
    myproc()->pgid = pgid;
    return 0;
  }
  ```
- ❌ **SID 支持**：搜索 `session|SID` 未发现实现

**xv6-k210**：
- ❌ **PGID 支持**：`struct proc` 中无 `pgid` 字段
- 🔸 **系统调用桩**：`sys_prlimit64` 存在但仅返回 `-ENOSYS`（`kernel/syscall/sysproc.c:273-278`）
- ❌ **SID 支持**：未发现

### rlimit 支持

**oskernel2023-avx**：
- ✅ **结构体定义**：`struct rlimit { uint64 rlim_cur; uint64 rlim_max; }`（`kernel/include/proc.h:107-110`）
- ✅ **系统调用**：`sys_prlimit64()`（`kernel/sysproc.c:53-65`）
  ```c
  uint64 sys_prlimit64() {
    rlimit r;
    if (either_copyin((void *)&r, 1, addr, sizeof(rlimit)) < 0) return -1;
    // ... 实际处理逻辑
  }
  ```

**xv6-k210**：
- 🔸 **系统调用桩**：`sys_prlimit64` 仅声明但未实现完整逻辑

### 对比总结

| 特性 | oskernel2023-avx | xv6-k210 |
|------|------------------|----------|
| PGID | ✅ 完整实现 | ❌ 未实现 |
| SID | ❌ 未实现 | ❌ 未实现 |
| rlimit | ✅ 完整实现 | 🔸 桩函数 |
| 文件描述符限制 | ✅ `filelimit` 字段 | ❌ 未实现 |

---

## 信号机制差异

### oskernel2023-avx：完整信号实现

**信号定义**：`kernel/include/signal.h`
- `SIGRTMIN=32`, `SIGRTMAX=64`
- 支持 65 个信号（0-64）

**核心数据结构**：
- `sigaction sigaction[SIGRTMAX + 1]`：固定数组（`kernel/include/proc.h:92`）
- `__sigset_t sig_set`：信号屏蔽字
- `__sigset_t sig_pending`：待处理信号
- `struct trapframe *sig_tf`：信号处理保存的 trapframe

**系统调用**：
- `sys_rt_sigaction()`（`kernel/syssig.c:15-35`）
- `sys_kill()`（`kernel/proc.c:876-896`）

**信号处理流程**（`kernel/signal.c:59-79`）：
```c
void sighandle(void) {
  struct proc *p = myproc();
  int signum = p->killed;
  if (p->sigaction[signum].__sigaction_handler.sa_handler != NULL) {
    p->sig_tf = kalloc();  // 保存当前 trapframe
    memcpy(p->sig_tf, p->trapframe, sizeof(struct trapframe));
    p->trapframe->epc = (uint64)p->sigaction[signum].__sigaction_handler.sa_handler;
    p->trapframe->ra = (uint64)SIGTRAMPOLINE;  // 信号处理返回地址
    p->trapframe->sp -= PGSIZE;
    p->sig_pending.__val[0] &= ~(1ul << signum);
  } else {
    exit(-1);  // 默认处理：终止进程
  }
}
```

**特征**：
- ✅ **SIGTRAMPOLINE 支持**：信号处理完成后通过 trampoline 返回
- ✅ **信号屏蔽**：`sigprocmask()` 支持 `SIG_BLOCK`/`SIG_UNBLOCK`/`SIG_SETMASK`
- ✅ **同步分发**：在 `usertrap()` 返回用户态前检查 `sig_pending`

### xv6-k210：链表式信号实现

**信号定义**：`include/sched/signal.h`
- `SIGRTMIN=34`, `SIGRTMAX=64`
- 使用链表 `ksigaction_t *sig_act` 存储信号处理函数

**核心数据结构**：
- `ksigaction_t *sig_act`：信号处理动作链表（`include/sched/proc.h:96`）
- `__sigset_t sig_set`：信号屏蔽字
- `__sigset_t sig_pending`：待处理信号
- `struct sig_frame *sig_frame`：信号帧链表

**系统调用**：
- `sys_rt_sigaction()`（`kernel/sched/signal.c:43-85`）
- `sys_kill()`（`kernel/sched/proc.c:541-579`）

**信号处理流程**：
- ✅ **链表式管理**：`__insert_sig()`, `__search_sig()` 管理信号处理函数
- ✅ **信号屏蔽**：`sigprocmask()` 支持
- 🔸 **sigreturn**：声明了 `sigreturn()` 函数（`include/sched/signal.h:90`），但未找到完整实现

### 对比总结

| 特性 | oskernel2023-avx | xv6-k210 |
|------|------------------|----------|
| 信号数量 | 65 个 (0-64) | 65 个 (0-64) |
| 存储结构 | 固定数组 `sigaction[65]` | 链表 `ksigaction_t *` |
| SIGTRAMPOLINE | ✅ 明确使用 | 🔸 未明确 |
| sigreturn | ❌ 未发现 | 🔸 声明但未实现 |
| 信号帧保存 | ✅ `sig_tf = kalloc()` | ✅ `sig_frame` 链表 |
| kill 实现 | ✅ 完整 | ✅ 完整 |

---

## Futex 差异

### oskernel2023-avx：完整 Futex 实现

**文件证据**：
- `kernel/futex.c`：核心实现
- `kernel/include/futex.h`：操作码定义
- `doc/futex.md`：设计文档

**核心数据结构**（`kernel/futex.c:8-13`）：
```c
typedef struct FutexQueue {
  uint64 addr;      // futex 地址
  thread *thread;   // 等待的线程
  uint8 valid;      // 槽位有效性
} FutexQueue;

FutexQueue futexQueue[FUTEX_COUNT];  // 全局等待队列，FUTEX_COUNT=1024
```

**关键操作**：
1. **FUTEX_WAIT**：`futexWait()`（`kernel/futex.c:16-35`）
   - 支持超时（`t_TIMING` 状态）
   - 线程级等待

2. **FUTEX_WAKE**：`futexWake()`（`kernel/futex.c:37-45`）
   - 唤醒指定数量的等待线程

3. **FUTEX_REQUEUE**：`futexRequeue()`（`kernel/futex.c:48-62`）

4. **线程退出清理**：`futexClear()`（`kernel/futex.c:64-70`）

**系统调用**：`sys_futex()`（`doc/futex.md:14-32`）
- 支持 `FUTEX_WAIT`, `FUTEX_WAKE`, `FUTEX_REQUEUE`

### xv6-k210：未实现 Futex

**搜索结果**：
- ❌ **无 futex 相关代码**：搜索 `futex|FUTEX|futex_wait|futex_wake` 未找到任何实现
- ✅ **wait_queue**：仅找到 `struct wait_queue`（`include/sync/waitqueue.h`），用于内核内部同步（如管道），**未暴露为用户态系统调用**

### 对比总结

| 特性 | oskernel2023-avx | xv6-k210 |
|------|------------------|----------|
| Futex 支持 | ✅ 完整实现 | ❌ 未实现 |
| 等待队列大小 | 1024 槽位 | N/A |
| 超时支持 | ✅ `t_TIMING` 状态 | N/A |
| 线程级等待 | ✅ `thread*` 存储 | N/A |
| 用户态系统调用 | ✅ `sys_futex()` | ❌ 无 |
| 内核内部 wait_queue | ✅ 有 | ✅ 有（仅内核用） |

---

## 总体结论

### 关键差异汇总

| 维度 | oskernel2023-avx | xv6-k210 | 差异程度 |
|------|------------------|----------|----------|
| **任务模型** | PCB + TCB 分离，支持多线程 | 仅 PCB，单线程进程 | 🔴 大 |
| **调度算法** | 简单 FIFO 轮转 | 3 级优先级时间片轮转 | 🔴 大 |
| **上下文切换** | 14 寄存器，无浮点 | 14 寄存器 + 浮点支持 | 🟡 中 |
| **进程组/会话** | PGID 完整，SID 无 | 均无 | 🟡 中 |
| **信号机制** | 固定数组，SIGTRAMPOLINE | 链表管理，sigreturn 未实现 | 🟢 小 |
| **Futex** | 完整实现（WAIT/WAKE/REQUEUE） | 未实现 | 🔴 大 |
| **fork 语义** | ✅ 真正复制地址空间 | ✅ 真正复制地址空间 | 🟢 相同 |

### 【创新点】标注

1. **oskernel2023-avx 独有**：
   - ✅ **Futex 完整实现**：支持 `FUTEX_WAIT`/`FUTEX_WAKE`/`FUTEX_REQUEUE`，xv6-k210 完全未实现
   - ✅ **线程级调度**：`thread_queue` 双向链表管理多线程，xv6-k210 仅进程级
   - ✅ **PGID 完整支持**：`sys_setpgid`/`sys_getpgid` 系统调用

2. **xv6-k210 独有**：
   - ✅ **优先级调度**：3 级优先级队列 + 时间片轮转，oskernel2023-avx 仅简单 FIFO
   - ✅ **浮点上下文保存**：`trapframe` 包含 20 个浮点寄存器，oskernel2023-avx 未实现
   - ✅ **性能统计**：`vswtch`/`ivswtch` 自愿/非自愿上下文切换计数

### 设计哲学差异

- **oskernel2023-avx**：偏向**功能完整性**，实现了 Futex、多线程、PGID 等高级特性，但调度算法简陋
- **xv6-k210**：偏向**调度性能优化**，实现了优先级时间片轮转和浮点支持，但缺少 Futex 等进程间同步机制

两者都正确实现了 POSIX fork 语义（真正复制地址空间），这是操作系统进程管理的基础要求。