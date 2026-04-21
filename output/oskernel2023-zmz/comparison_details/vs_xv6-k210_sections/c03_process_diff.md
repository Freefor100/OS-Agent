## 任务模型差异

### 核心数据结构对比

**oskernel2023-zmz** 与 **xv6-k210** 在任务模型上采用**完全相同的设计**：

| 维度 | oskernel2023-zmz | xv6-k210 | 差异判定 |
|------|------------------|----------|----------|
| 控制块结构 | `struct proc` (PCB/TCB合一) | `struct proc` (PCB/TCB合一) | ✅ 相同 |
| 结构体定义位置 | `include/sched/proc.h:51-105` | `include/sched/proc.h:51-148` | ✅ 相同 |
| 上下文结构 | `struct context` (ra+sp+s0-s11) | `struct context` (ra+sp+s0-s11) | ✅ 相同 |
| 进程状态枚举 | `RUNNABLE/RUNNING/SLEEPING/ZOMBIE` | `RUNNABLE/RUNNING/SLEEPING/ZOMBIE` | ✅ 相同 |

**关键字段完全一致**（证据：`clone` 函数 Jaccard 相似度 **0.990**）：
- 基础标识：`pid`, `xstate`, `hash_next`, `hash_pprev`
- 调度链表：`sched_next`, `sched_pprev`, `timer`, `state`, `chan`, `sleep_expire`
- 亲缘关系：`child`, `parent`, `sibling_next`, `sibling_pprev`, `lk` (自旋锁)
- 内存管理：`kstack`, `pagetable`, `trapframe`, `segment`, `pbrk`
- 文件系统：`fds`, `cwd`, `elf`
- 信号机制：`sig_act`, `sig_set`, `sig_pending`, `sig_frame`, `killed`

**结论**：两个项目在任务模型层面**代码高度一致**，非设计思路相似，而是**实际代码复用**。

---

## 调度算法差异

### 调度器实现对比

| 维度 | oskernel2023-zmz | xv6-k210 | 差异判定 |
|------|------------------|----------|----------|
| 调度算法类型 | 基于优先级的多级队列 | 基于优先级的多级队列 | ✅ 相同 |
| 优先级数量 | 3 (TIMEOUT/IRQ/NORMAL) | 3 (TIMEOUT/IRQ/NORMAL) | ✅ 相同 |
| 优先级定义 | `PRIORITY_TIMEOUT=0`, `PRIORITY_IRQ=1`, `PRIORITY_NORMAL=2` | 同左 | ✅ 相同 |
| 时间片默认值 | `TIMER_NORMAL=10`, `TIMER_IRQ=5` | 同左 | ✅ 相同 |
| 调度器入口 | `kernel/sched/proc.c:658` | `kernel/sched/proc.c:671` | ✅ 相同 |
| 优先级选择逻辑 | `__get_runnable_no_lock()` 按优先级顺序遍历 | 同左 | ✅ 相同 |

### 调度策略细节

**共同特征**（证据：`scheduler` Call Graph Jaccard 相似度 **1.000**）：
1. **严格优先级调度**：从 `PRIORITY_TIMEOUT(0)` → `PRIORITY_IRQ(1)` → `PRIORITY_NORMAL(2)` 顺序扫描
2. **同优先级 FIFO**：同一优先级队列内按 `sched_next` 链表顺序调度
3. **时间片降级机制**：`proc_tick()` 中时间片耗尽的进程从 `PRIORITY_NORMAL` 降级到 `PRIORITY_TIMEOUT`
4. **中断/信号唤醒优先**：被信号唤醒的进程插入 `PRIORITY_IRQ` 队列

**❌ 未实现功能**（两项目均缺失）：
- **时间片轮转（RR）抢占**：`proc_tick()` 仅对**非 RUNNING 状态**进程递减 timer，运行中进程不会被时间片耗尽抢占
- **动态优先级调整**：无 CFS/Stride 等公平调度算法
- **多调度器支持**：未发现 feature flag 切换调度器的代码

**代码证据**（`kernel/sched/proc.c`）：
```c
// 两项目相同的调度器主循环
void scheduler(void) {
    struct cpu *c = mycpu();
    while (1) {
        intr_on();
        __enter_proc_cs 
        tmp = __get_runnable_no_lock();  // 按优先级查找
        if (NULL != tmp) {
            tmp->state = RUNNING;
            c->proc = tmp;
            w_satp(MAKE_SATP(tmp->pagetable));
            sfence_vma();
            swtch(&c->context, &tmp->context);  // 上下文切换
            w_satp(MAKE_SATP(kernel_pagetable));
            sfence_vma();
        }
        c->proc = NULL;
        __leave_proc_cs 
        if (!found) {
            intr_on();
            asm volatile("wfi");  // 无进程可运行时进入低功耗等待
        }
    } 
}
```

**结论**：两项目调度算法**完全一致**，均实现了简化版优先级调度，但**未实现真正的抢占式时间片轮转**。

---

## Call Graph 差异

### scheduler 函数调用链对比

| 项目 | 调用函数列表 | Jaccard 相似度 |
|------|-------------|---------------|
| oskernel2023-zmz | `__get_runnable_no_lock`, `__panic`, `acquire`, `cpuid`, `intr_on`, `mycpu`, `printf`, `release`, `sfence_vma`, `swtch`, `w_satp` | **1.000** |
| xv6-k210 | `__get_runnable_no_lock`, `__panic`, `acquire`, `cpuid`, `intr_on`, `mycpu`, `printf`, `release`, `sfence_vma`, `swtch`, `w_satp` | |

**差异分析**：
- **共同调用**：11 个函数完全一致
- **oskernel2023-zmz 独有**：无
- **xv6-k210 独有**：无

### sys_fork 函数调用链对比

**重要发现**：`compare_call_graphs` 未找到 `sys_fork` 定义，但通过 `grep` 验证：

**oskernel2023-zmz**（证据：`kernel/syscall/sysproc.c:85`）：
```c
uint64 sys_fork(void) {
    return clone(0, NULL);
}
```

**xv6-k210**（证据：`kernel/syscall/sysproc.c:85`）：
```c
uint64 sys_fork(void) {
    return clone(0, NULL);
}
```

**fork 完整调用链**（两项目相同）：
```
sys_fork → clone → allocproc → proc_pagetable
                ↓
           copysegs (复制地址空间)
                ↓
           copyfdtable (复制文件表)
                ↓
           sigaction_copy (复制信号处理)
                ↓
           __insert_runnable (插入就绪队列)
```

### clone 函数 Token 相似度

| 指标 | 数值 |
|------|------|
| oskernel2023-zmz token 数 | 98 |
| xv6-k210 token 数 | 99 |
| **Jaccard 相似度** | **0.990** |
| oskernel2023-zmz 独有关键词 | 无 |
| xv6-k210 独有关键词 | `floattrap` |

**关键差异点**（唯一区别）：
```c
// oskernel2023-zmz
if (r_sstatus_fs() == SSTATUS_FS_DIRTY) {
    floatstore(p->trapframe);
    w_sstatus_fs(SSTATUS_FS_CLEAN);
}

// xv6-k210
if (r_sstatus_fs() == SSTATUS_FS_DIRTY) {
    ((floattrap)floatstore)(p->trapframe);  // 多了类型转换
    w_sstatus_fs(SSTATUS_FS_CLEAN);
}
```

**结论**：`sys_fork`/`clone` 调用链**几乎完全相同**，仅浮点保存处有细微语法差异。

---

## 上下文切换差异

### swtch.S 汇编代码对比

**oskernel2023-zmz**（证据：`kernel/sched/swtch.S:1-41`）与 **xv6-k210**（证据：`kernel/sched/swtch.S:1-41`）**完全相同**：

```asm
.globl swtch
swtch:
    # 保存当前上下文到 old (a0 指向)
    sd ra, 0(a0)
    sd sp, 8(a0)
    sd s0, 16(a0)
    sd s1, 24(a0)
    sd s2, 32(a0)
    sd s3, 40(a0)
    sd s4, 48(a0)
    sd s5, 56(a0)
    sd s6, 64(a0)
    sd s7, 72(a0)
    sd s8, 80(a0)
    sd s9, 88(a0)
    sd s10, 96(a0)
    sd s11, 104(a0)

    # 从 new (a1 指向) 恢复上下文
    ld ra, 0(a1)
    ld sp, 8(a1)
    # ... (s0-s11 恢复)
    ret
```

### 保存寄存器集合对比

| 寄存器类别 | oskernel2023-zmz | xv6-k210 | 差异 |
|-----------|------------------|----------|------|
| `ra` (返回地址) | ✅ 保存 | ✅ 保存 | 无 |
| `sp` (栈指针) | ✅ 保存 | ✅ 保存 | 无 |
| `s0-s11` (callee-saved) | ✅ 保存 (12 个) | ✅ 保存 (12 个) | 无 |
| `t0-t6` (caller-saved) | ❌ 不保存 | ❌ 不保存 | 无 |
| `a0-a7` (参数/返回值) | ❌ 不保存 | ❌ 不保存 | 无 |
| **浮点寄存器** | ❌ 不保存 (惰性处理) | ❌ 不保存 (惰性处理) | 无 |

**浮点寄存器处理策略**（两项目相同）：
- **惰性保存（Lazy FPU Save）**：仅在 `sched()` 中检查 `sstatus.FS` 标志
- 若 `SSTATUS_FS_DIRTY`，调用 `floatstore(p->trapframe)` 保存到 trapframe
- 切换后调用 `floatload(p->trapframe)` 恢复

**代码证据**：
```c
// kernel/sched/proc.c (两项目相同)
void sched(void) {
    // ...
    if (r_sstatus_fs() == SSTATUS_FS_DIRTY) {
        floatstore(p->trapframe);
        w_sstatus_fs(SSTATUS_FS_CLEAN);
    }
    swtch(&p->context, &mycpu()->context);
    // ...
    floatload(p->trapframe);
    w_sstatus_fs(SSTATUS_FS_CLEAN);
}
```

**结论**：上下文切换实现**完全相同**，均仅保存 callee-saved 寄存器，浮点寄存器采用惰性保存策略。

---

## 进程管理扩展差异

### 进程组 (PGID) / 会话 (SID) 支持

**oskernel2023-zmz**：
- **❌ 未实现**：搜索 `getpgid|setpgid|struct.*pgid|session|getsid` 未找到任何实现
- `struct proc` 中**无** `pgid` 或 `sid` 字段

**xv6-k210**：
- **❌ 未实现**：搜索结果同上
- `struct proc` 中**无** `pgid` 或 `sid` 字段

**结论**：两项目均**不支持**进程组和会话管理。

### rlimit 资源限制支持

**oskernel2023-zmz**（证据：`kernel/syscall/sysproc.c:273-277`）：
```c
sys_prlimit64(void) {
    // for now it's not very necessary to implement this syscall 
    // may be implemented later 
    return 0;  // 🔸 桩函数：仅返回 0
}
```

**xv6-k210**（证据：`kernel/syscall/sysproc.c:273-277`）：
```c
sys_prlimit64(void) {
    // for now it's not very necessary to implement this syscall 
    // may be implemented later 
    return 0;  // 🔸 桩函数：仅返回 0
}
```

**结论**：两项目均定义了 `SYS_prlimit64` 系统调用号，但实现为**桩函数**，仅返回 0，**未实现实际资源限制功能**。

---

## 信号/Futex 差异

### 信号机制实现程度对比

| 功能 | oskernel2023-zmz | xv6-k210 | 差异判定 |
|------|------------------|----------|----------|
| 信号定义 | ✅ `SIGRTMIN`~`SIGRTMAX`, `SIGTERM`, `SIGKILL` 等 | 同左 | ✅ 相同 |
| `struct sigaction` | ✅ 支持 `sa_handler`, `sa_mask`, `sa_flags` | 同左 | ✅ 相同 |
| `kill()` 系统调用 | ✅ 完整实现 (`kernel/sched/proc.c:541-579`) | 同左 | ✅ 相同 |
| `sys_rt_sigaction` | ✅ 完整实现 (`kernel/syscall/syssignal.c`) | 🔸 部分实现（注释掉 sa_mask/sa_flags 复制） | ⚠️ 差异 |
| `sigprocmask` | ✅ 声明但未找到完整实现 | 同左 | ✅ 相同 |
| 信号处理帧 | ✅ `struct sig_frame` 定义 | 同左 | ✅ 相同 |
| 信号唤醒机制 | ✅ 睡眠进程可被 `kill()` 唤醒到 `PRIORITY_IRQ` | 同左 | ✅ 相同 |

### sys_rt_sigaction 实现差异（关键发现）

**oskernel2023-zmz**（证据：`kernel/syscall/syssignal.c` 搜索片段）：
```c
uint64 sys_rt_sigaction(void) {
    // ... 参数提取
    if (uptr_act) {
        if (
            copyin2((char*)&(act.__sigaction_handler), uptr_act, sizeof(__sighandler_t)) < 0 || 
            copyin2((char*)&(act.sa_mask), uptr_act + sizeof(__sighandler_t), size) < 0 ||  // ✅ 复制 sa_mask
            copyin2((char*)&(act.sa_flags), uptr_act + sizeof(__sigaction_handler) + size, sizeof(int)) < 0  // ✅ 复制 sa_flags
        ) {
            return -EFAULT;
        }
    }
    // ...
}
```

**xv6-k210**（证据：`kernel/syscall/syssignal.c` 搜索片段）：
```c
uint64 sys_rt_sigaction(void) {
    // ... 参数提取
    if (uptr_act) {
        if (
            copyin2((char*)&(act.__sigaction_handler), uptr_act, sizeof(__sighandler_t)) < 0 
            // copyin2((char*)&(act.sa_mask), uptr_act + sizeof(__sighandler_t), size) < 0 ||  // ❌ 注释掉
            // copyin2((char*)&(act.sa_flags), uptr_act + sizeof(__sighandler_t) + size, sizeof(int)) < 0  // ❌ 注释掉
        ) {
            return -EFAULT;
        }
    }
    // ...
}
```

**set_sigaction 差异**：
```c
// oskernel2023-zmz: 完整复制 sa_flags 和 sa_mask
tmp->sigact.sa_flags = act->sa_flags;
for (int i = 0; i < len; i ++) {
    tmp->sigact.sa_mask.__val[i] = act->sa_mask.__val[i];
}

// xv6-k210: 注释掉 sa_flags 和 sa_mask 复制
// tmp->sigact.sa_flags = act->sa_flags;  // ❌ 注释掉
// for (int i = 0; i < len; i ++) { ... }  // ❌ 注释掉
tmp->sigact.__sigaction_handler = act->__sigaction_handler;  // ✅ 仅复制 handler
```

**结论**：
- **oskernel2023-zmz**：✅ **完整实现** `sigaction` 的 `sa_handler`、`sa_mask`、`sa_flags` 复制
- **xv6-k210**：🔸 **部分实现**，仅支持 `sa_handler`，`sa_mask` 和 `sa_flags` 被注释掉

### Futex 支持对比

**oskernel2023-zmz**：
- **❌ 未实现**：搜索 `futex_wait|futex_wake|futex` 未找到任何实现
- 仅存在内核内部使用的 `struct wait_queue`（用于管道阻塞），**未暴露为用户态系统调用**

**xv6-k210**：
- **❌ 未实现**：搜索结果同上
- 同样仅存在 `struct wait_queue`，**无用户态 futex 支持**

**结论**：两项目均**不支持**用户态 Futex 系统调用。

---

## 重要差异总结

### 1. fork 地址空间复制（无差异）

**验证结果**：两项目 `clone()` 函数均调用 `copysegs()` 真正复制地址空间：

```c
// 两项目相同 (kernel/sched/proc.c)
np->segment = copysegs(p->pagetable, p->segment, np->pagetable);
if (NULL == np->segment) {
    freeproc(np);
    return -1;
}
```

**结论**：**不存在**"oskernel2023-zmz 复制地址空间而 xv6-k210 仅创建 TCB"的差异，两项目均**完整复制地址空间**。

### 2. 唯一实质性差异

| 维度 | oskernel2023-zmz | xv6-k210 | 重要性 |
|------|------------------|----------|--------|
| `sys_rt_sigaction` 实现 | ✅ 完整复制 `sa_mask` 和 `sa_flags` | 🔸 仅复制 `sa_handler`，其他字段注释掉 | **中等** |
| `clone` 浮点保存 | `floatstore(p->trapframe)` | `((floattrap)floatstore)(p->trapframe)` | 低（语法差异） |

### 3. 共同缺失功能

两项目均**未实现**以下功能：
- ❌ 进程组 (PGID) / 会话 (SID) 管理
- ❌ Futex 用户态系统调用
- ❌ 真正的抢占式时间片轮转（RR）
- ❌ CFS/Stride 等公平调度算法
- ❌ `prlimit64` 实际功能（仅桩函数）

---

## 总体结论

**oskernel2023-zmz** 与 **xv6-k210** 在进程与调度维度的对比结果：

1. **代码复用程度极高**：`clone` 函数 Jaccard 相似度 **0.990**，`scheduler` Call Graph Jaccard 相似度 **1.000**，`swtch.S` 汇编代码**完全相同**。

2. **设计思路完全一致**：任务模型、调度算法、上下文切换、信号机制等核心设计**无本质差异**。

3. **唯一实质性差异**：`sys_rt_sigaction` 中 `sa_mask` 和 `sa_flags` 字段的处理，oskernel2023-zmz 实现更完整。

4. **无创新点发现**：未发现 oskernel2023-zmz 有而 xv6-k210 没有的独特实现。

5. **共同局限性**：两项目均未实现进程组/会话管理、Futex、抢占式 RR 调度等高级功能。

**最终判定**：两项目在进程与调度维度**代码高度同源**，差异极小，非独立设计实现。