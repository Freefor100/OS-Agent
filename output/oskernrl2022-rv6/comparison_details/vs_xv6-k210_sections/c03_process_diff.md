现在我已经收集了足够的证据来撰写完整的对比报告。让我整理所有发现并输出最终报告。

## 进程与调度机制对比报告：oskernrl2022-rv6 vs xv6-k210

---

## 任务模型差异

### 核心数据结构对比

**两个项目均采用统一的 `struct proc` 表示执行实体，未区分 PCB 与 TCB**。

#### oskernrl2022-rv6 的 `struct proc`
**文件位置**: `src/include/proc.h:128-171`

关键字段包括：
- **基础标识**: `pid`, `uid`, `gid`, `state`, `parent`
- **内存管理**: `kstack`, `sz`, `pagetable`, `trapframe`, `vma` (虚拟内存区域链表)
- **上下文**: `context` (内核寄存器), `trapframe` (用户寄存器)
- **文件系统**: `ofile[NOFILE]`, `cwd`
- **信号机制**: `sig_act`, `sig_set`, `sig_pending`, `sig_frame`, `killed`
- **线程支持**: `set_child_tid`, `clear_child_tid`, `robust_list`

#### xv6-k210 的 `struct proc`
**文件位置**: `include/sched/proc.h:51-148`

关键字段包括：
- **基础标识**: `pid`, `xstate`, `state`, `parent`, `child`, `sibling_next`
- **调度相关**: `sched_next`, `sched_pprev`, `timer` (时间片计数器)
- **性能统计**: `proc_tms`, `vswtch` (自愿切换), `ivswtch` (非自愿切换)
- **内存管理**: `kstack`, `pagetable`, `trapframe`, `segment` (内存段链表), `pbrk` (程序断点)
- **上下文**: `context`
- **文件系统**: `fds` (文件描述符表), `cwd`, `elf`
- **信号机制**: `sig_act`, `sig_set`, `sig_pending`, `sig_frame`, `killed`

### 关键差异

| 特性 | oskernrl2022-rv6 | xv6-k210 |
|------|------------------|----------|
| **线程标识** | ✅ 支持 `CLONE_THREAD`, `CLONE_VM` 标志区分进程/线程 | ❌ `clone()` 仅接受 `flag` 和 `stack` 两参数，未使用线程标志 |
| **VMA 管理** | ✅ 使用 `struct vma *vma` 链表 | ✅ 使用 `struct seg *segment` 链表 |
| **性能统计** | ❌ 无切换次数统计 | ✅ 有 `vswtch`/`ivswtch` 统计 |
| **时间片字段** | ❌ 无 `timer` 字段 | ✅ 有 `timer` 字段用于时间片轮转 |
| **亲缘关系** | 仅 `parent` 指针 | ✅ `parent` + `child` + `sibling` 完整树形结构 |

**结论**: 两者设计思路相似（统一 `struct proc`），但 xv6-k210 在亲缘关系管理和性能统计方面更完善，而 oskernrl2022-rv6 在线程支持方面有更明确的标志位设计。

---

## 调度算法差异

### oskernrl2022-rv6: FIFO 轮转调度

**实现位置**: `src/proc.c:119-152`

```c
void scheduler(){
  struct cpu *c = mycpu();
  c->proc = 0;
  while(1){
    struct proc* p = readyq_pop();  // 从全局单队列 FIFO 取出
    if(p){
      acquire(&p->lock);
      if(p->state == RUNNABLE) {
        p->state = RUNNING;
        c->proc = p;
        w_satp(MAKE_SATP(p->pagetable));
        sfence_vma();
        swtch(&c->context, &p->context);
        // ...
      }
      release(&p->lock);
    }else{
      intr_on();
      asm volatile("wfi");  // 无进程时低功耗
    }
  }
}
```

**关键特征**:
- ✅ **单就绪队列**: `readyq` 全局 FIFO 链表 (`src/proc.c:29`)
- ❌ **无优先级**: `readyq_pop()` 直接返回队列头，无优先级比较
- ❌ **无时间片**: 无 `timer` 字段，依赖 `yield()` 主动让出
- ❌ **无多调度器**: 未发现 feature flag 切换机制

**Call Graph 证据** (`compare_call_graphs` 结果):
- 调用链: `scheduler` → `readyq_pop` → `queue_pop` → `swtch`
- Jaccard 相似度 (vs xv6-k210): **0.538**

---

### xv6-k210: 基于优先级的时间片轮转

**实现位置**: `kernel/sched/proc.c:671-711`

**优先级定义** (`kernel/sched/proc.c:241-243`):
```c
#define PRIORITY_TIMEOUT    0   // 超时队列 (最低)
#define PRIORITY_IRQ        1   // 中断/信号唤醒 (高)
#define PRIORITY_NORMAL     2   // 普通进程 (默认)
#define PRIORITY_NUMBER     3
```

**调度器核心逻辑**:
```c
static struct proc *__get_runnable_no_lock(void) {
    for (int i = 0; i < PRIORITY_NUMBER; i++) {  // 从 0 开始扫描
        tmp = proc_runnable[i];
        while (NULL != tmp) {
            if (RUNNABLE == tmp->state)
                return (struct proc*)tmp;
            tmp = tmp->sched_next;
        }
    }
    return NULL;
}
```

**时间片机制** (`kernel/sched/proc.c:753-787`):
```c
void proc_tick(void) {
    for (int i = PRIORITY_IRQ; i < PRIORITY_NUMBER; i ++) {
        p = proc_runnable[i];
        while (NULL != p) {
            if (RUNNING != p->state) {
                p->timer = p->timer - 1;
                if (0 == p->timer) {
                    __remove(p);
                    __insert_runnable(PRIORITY_TIMEOUT, p);  // 降级
                }
            }
            p = p->sched_next;
        }
    }
}
```

**关键特征**:
- ✅ **3 优先级队列**: `proc_runnable[3]`
- ✅ **时间片轮转**: 默认 `TIMER_NORMAL = 10` tick
- ✅ **动态优先级**: 时间片耗尽降级到 `PRIORITY_TIMEOUT`，中断唤醒升级到 `PRIORITY_IRQ`
- ❌ **无 CFS/Stride**: 未发现更高级调度算法

**Call Graph 证据**:
- 调用链: `scheduler` → `__get_runnable_no_lock` → `swtch`
- `scheduler` 函数 Token Jaccard 相似度: **0.627** (高度相似)

---

### 调度算法对比总结

| 特性 | oskernrl2022-rv6 | xv6-k210 |
|------|------------------|----------|
| **调度策略** | FIFO 轮转 | 优先级 + 时间片轮转 |
| **就绪队列** | 单队列 | 3 优先级队列 |
| **时间片** | ❌ 无 | ✅ 10 tick (可降级) |
| **优先级** | ❌ 无 | ✅ 3 级动态调整 |
| **调度器切换** | ❌ 不支持 | ❌ 不支持 |

**【重要差异】**: xv6-k210 实现了更复杂的优先级调度机制，而 oskernrl2022-rv6 仅实现基础 FIFO 调度。

---

## Call Graph 差异

### `scheduler` 调用链对比

**共同调用** (7 个): `acquire`, `intr_on`, `mycpu`, `release`, `sfence_vma`, `swtch`, `w_satp`

**oskernrl2022-rv6 独有**:
- `readyq_pop` → `queue_pop` (FIFO 队列操作)

**xv6-k210 独有**:
- `__get_runnable_no_lock` (优先级扫描)
- `__panic`, `printf` (错误处理)
- `cpuid` (CPU ID 获取)

**Jaccard 相似度**: 0.538 (中度差异)

---

### `clone` 调用链对比

**共同调用** (17 个): `acquire`, `allocproc`, `forkret`, `freeproc`, `kfree`, `kmalloc`, `kvmcreate`, `memset`, `myproc`, `proc_freepagetable`, `proc_pagetable`, `release`, `safestrcpy`, `sigaction_copy`, `sigaction_free`, `sigframefree`, `usertrapret`

**oskernrl2022-rv6 独有** (17 个):
- `allocparent`, `allocpid` (亲缘/ID 分配)
- `copyout`, `filedup`, `edup` (文件/内存复制)
- `vma_copy`, `vma_deep_mapping`, `vma_shallow_mapping` (VMA 管理)
- `readyq_push`, `queue_push` (FIFO 队列)
- `CLONE_THREAD`, `CLONE_VM`, `CLONE_CHILD_SETTID`, `CLONE_CHILD_CLEARTID` (线程标志)

**xv6-k210 独有** (17 个):
- `copysegs` (内存段复制)
- `copyfdtable`, `idup` (文件表复制)
- `hash_insert_no_lock`, `hash_remove_no_lock` (哈希表管理)
- `__insert_runnable`, `__proc_list_insert_no_lock` (优先级队列)
- `r_sstatus_fs`, `w_sstatus_fs` (浮点状态)

**Jaccard 相似度**: 0.333 (差异明显)

**Token 级别相似度** (`compare_function_tokens`):
- `clone` 函数: **0.400** (中度相似)
- `scheduler` 函数: **0.627** (高度相似)

---

### 地址空间复制机制对比（重要）

**oskernrl2022-rv6** (`src/proc.c:408-492`):
```c
if((flag & CLONE_THREAD) && (flag & CLONE_VM)) {
    // 线程：共享地址空间
    np = allocproc(p, 1);
} else {
    // 进程：独立地址空间
    np = allocproc(p, 0);
}
// 调用 proc_pagetable() → vma_copy() + vma_deep_mapping()
```

**xv6-k210** (`kernel/sched/proc.c:291-370`):
```c
np = allocproc();
np->segment = copysegs(p->pagetable, p->segment, np->pagetable);  // 复制内存段
np->pbrk = p->pbrk;
```

**✅ 两者均真正复制了地址空间**：
- oskernrl2022-rv6: 通过 `vma_deep_mapping()` 分配新物理页并复制内容
- xv6-k210: 通过 `copysegs()` → `uvmalloc()` 分配新页

**❌ 两者均未实现写时复制 (CoW)**：
- oskernrl2022-rv6: `vma_shallow_mapping()` 未设置 CoW 标志
- xv6-k210: 未发现 CoW 相关代码

---

## 进程管理扩展差异

### 进程组 (PGID) 与会话 (SID)

**oskernrl2022-rv6**:
- `grep` 搜索结果: 仅在 `src/include/ff.h:186` 找到 "session" 一词（与 FAT 文件系统相关，非进程会话）
- **结论**: ❌ **未实现** PGID/SID 机制

**xv6-k210**:
- `grep` 搜索结果: 未找到任何 `pgid|session|setpgid|getsid` 匹配
- **结论**: ❌ **未实现** PGID/SID 机制

---

### 资源限制 (rlimit)

**oskernrl2022-rv6**:
- **定义**: `src/include/proc.h:91-111` 定义了完整的 16 种资源限制 (`RLIMIT_CPU` 到 `RLIMIT_RTTIME`) 和 `struct rlimit`
- **系统调用**: 仅在文档 `doc/内核实现--信号相关.md:160` 提到 `SYS_prlimit64`
- **实现状态**: ❌ **未找到** `sys_prlimit64()`, `getrlimit()`, `setrlimit()` 的实现代码
- **结论**: 🔸 **桩函数** (仅结构体定义，无系统调用实现)

**xv6-k210**:
- **系统调用声明**: `include/sysnum.h:76` 定义 `SYS_prlimit64`
- **系统调用表**: `kernel/syscall/syscall.c:178,249,321` 注册了 `sys_prlimit64`
- **实现代码**: `kernel/syscall/sysproc.c:273-277`:
```c
sys_prlimit64(void) {
    // for now it's not very necessary to implement this syscall 
    // may be implemented later 
    return 0;  // 桩函数
}
```
- **结论**: 🔸 **桩函数** (有系统调用框架，但返回 0 无实际功能)

---

## 信号机制差异

### 实现程度对比

**两者均实现了基础信号机制**，支持以下共同特性：

| 特性 | oskernrl2022-rv6 | xv6-k210 |
|------|------------------|----------|
| **信号定义** | ✅ `SIGTERM(15)`, `SIGKILL(9)`, `SIGABRT(6)` 等 9 种基本信号 | ✅ 相同 |
| **实时信号** | ✅ `SIGRTMIN(34)` 到 `SIGRTMAX(64)` | ✅ 相同 |
| **信号集** | ✅ `SIGSET_LEN = 1` (64 位) | ✅ 相同 |
| **sigaction** | ✅ `struct sigaction` + `ksigaction_t` 链表 | ✅ 相同 |
| **kill 系统调用** | ✅ `sys_kill()` → `kill()` | ✅ 相同 |
| **待处理信号** | ✅ `sig_pending`, `killed` 字段 | ✅ 相同 |
| **信号帧** | ✅ `struct sig_frame` 保存被中断上下文 | ✅ 相同 |

### 差异点

**oskernrl2022-rv6 特有**:
- `sig_frame` 链表直接挂在 `struct proc` 上
- `kill()` 设置 `p->killed` 标志后，在 `usertrap()` 中检查并调用 `sighandle()`

**xv6-k210 特有**:
- `kill()` 会将睡眠进程唤醒到 `PRIORITY_IRQ` 队列 (`kernel/sched/proc.c:541-579`)
- 信号唤醒具有优先级提升效果

**共同限制**:
- `sa_mask` 未完全实现（oskernrl2022-rv6 注释掉，xv6-k210 未深入实现）
- `siginfo_t` 未实现（仅支持简单 `sa_handler`）

---

## Futex 差异

### oskernrl2022-rv6

**接口定义**:
- `src/include/proc.h:18-50` 定义了 15 种 futex 操作 (`FUTEX_WAIT`, `FUTEX_WAKE`, `FUTEX_REQUEUE` 等)
- `src/include/proc.h:199` 声明 `do_futex()` 函数

**实现状态**:
- `grep` 搜索: 找到 63 个匹配，但**全部位于文档** `doc/内核实现--Futex.md`
- **源代码中未找到** `do_futex()`, `futex_wait()`, `futex_wake()` 的实现
- 系统调用表中未发现 `sys_futex`

**结论**: 🔸 **仅有接口定义和文档规划**，❌ **未实际实现**

---

### xv6-k210

**搜索结果**:
- `grep` 搜索 `futex|FUTEX`: **未找到任何匹配** (搜索 207 个文件)
- 仅有内核内部使用的 `struct wait_queue` (`include/sync/waitqueue.h`)，用于管道等同步

**结论**: ❌ **完全未实现** (无接口定义，无实现代码)

---

### Futex 对比总结

| 项目 | 接口定义 | 实现代码 | 系统调用 |
|------|----------|----------|----------|
| oskernrl2022-rv6 | ✅ 已定义 | ❌ 未实现 | ❌ 未注册 |
| xv6-k210 | ❌ 未定义 | ❌ 未实现 | ❌ 未实现 |

**【差异点】**: oskernrl2022-rv6 至少完成了接口设计和文档规划，而 xv6-k210 完全没有 futex 相关代码。

---

## 上下文切换差异

### 汇编代码对比

**oskernrl2022-rv6** (`src/swtch.S:1-42`):
```assembly
.globl swtch
swtch:
    sd ra, 0(a0)    # 保存 ra
    sd sp, 8(a0)    # 保存 sp
    sd s0, 16(a0)   # 保存 s0-s11 (省略)
    # ...
    ld ra, 0(a1)    # 恢复 ra
    ld sp, 8(a1)    # 恢复 sp
    # ...
    ret
```

**xv6-k210** (`kernel/sched/swtch.S:1-41`):
```assembly
.globl swtch
swtch:
    sd ra, 0(a0)
    sd sp, 8(a0)
    sd s0, 16(a0)   # 保存 s0-s11
    # ...
    ld ra, 0(a1)
    ld sp, 8(a1)
    # ...
    ret
```

### 保存的寄存器

**两者完全相同** (14 个 64 位寄存器，112 字节):
- `ra` (返回地址)
- `sp` (栈指针)
- `s0-s11` (12 个 callee-saved 寄存器)

**未保存的寄存器** (两者相同):
- `a0-a7` (caller-saved，由编译器处理)
- `t0-t6` (临时寄存器)
- `fp/gp/tp` (特殊处理)

**浮点寄存器**:
- ❌ **两者均未在 `swtch()` 中保存浮点寄存器**
- xv6-k210 在 `clone()` 中有检查 `SSTATUS_FS_DIRTY` 并调用 `floatstore()` 的逻辑，但这是在进程创建时，而非上下文切换时

---

## 总结

### 核心差异概览

| 维度 | oskernrl2022-rv6 | xv6-k210 | 差异程度 |
|------|------------------|----------|----------|
| **任务模型** | 统一 `struct proc`，支持线程标志 | 统一 `struct proc`，亲缘关系完善 | 🔸 中等 |
| **调度算法** | FIFO 轮转 (单队列) | 优先级 + 时间片 (3 队列) | 🔴 **大** |
| **上下文切换** | 14 寄存器 (ra,sp,s0-s11) | 相同 | ✅ 相同 |
| **地址空间复制** | 深拷贝 (vma_deep_mapping) | 深拷贝 (copysegs) | ✅ 相同 |
| **进程组/会话** | ❌ 未实现 | ❌ 未实现 | ✅ 相同 |
| **rlimit** | 🔸 仅结构体定义 | 🔸 桩函数 (返回 0) | 🔸 中等 |
| **信号机制** | ✅ 基础实现 | ✅ 基础实现 (+优先级唤醒) | 🔸 中等 |
| **Futex** | 🔸 仅接口定义 | ❌ 完全未实现 | 🔸 中等 |

### 【创新点】发现

1. **oskernrl2022-rv6**:
   - 明确的线程标志设计 (`CLONE_THREAD`, `CLONE_VM`, `CLONE_CHILD_SETTID`, `CLONE_CHILD_CLEARTID`)
   - VMA 链表管理 (`struct vma`) 支持更灵活的内存区域操作
   - Futex 接口设计和文档规划完整（虽未实现）

2. **xv6-k210**:
   - 优先级调度机制 (3 队列动态调整)
   - 时间片轮转与优先级降级
   - 进程亲缘关系树形结构 (`parent`/`child`/`sibling`)
   - 性能统计 (`vswtch`/`ivswtch`)
   - 信号唤醒优先级提升机制

### 重要结论

1. **调度算法差异最大**: xv6-k210 的优先级调度明显优于 oskernrl2022-rv6 的简单 FIFO。

2. **地址空间复制两者均实现**: 都真正复制了物理页，而非仅创建 TCB。

3. **Futex 均未完整实现**: oskernrl2022-rv6 有接口无实现，xv6-k210 完全缺失。

4. **代码相似度中等**: `clone` 函数 Token Jaccard 0.400，`scheduler` 函数 0.627，表明设计思路相似但实现细节有差异。