## 进程与调度机制对比报告：oskernel2023-zmz vs oskernrl2022-rv6

---

## 任务模型差异

### 核心数据结构对比

**oskernel2023-zmz**：
- **结构体**：`struct proc`（PCB/TCB 合一）
- **文件路径**：`include/sched/proc.h:51-105`
- **关键字段**：
  ```c
  struct proc {
      int pid;                        // 进程 ID
      struct proc *hash_next;         // 哈希链表
      struct proc *sched_next;        // 调度队列
      enum procstate state;           // 进程状态
      void *chan;                     // 睡眠通道
      uint64 kstack;                  // 内核栈
      pagetable_t pagetable;          // 用户页表
      struct trapframe *trapframe;    // 陷阱帧
      struct context context;         // 内核上下文
      struct fdtable fds;             // 文件描述符表
      struct inode *cwd;              // 当前目录
      ksigaction_t *sig_act;          // 信号处理动作
      __sigset_t sig_set;             // 阻塞信号集
      char name[16];                  // 进程名
  };
  ```

**oskernrl2022-rv6**：
- **结构体**：`struct proc`（统一表示进程/线程）
- **文件路径**：`src/include/proc.h:128-171`
- **关键字段**：
  ```c
  struct proc {
      int pid;                        // 进程 ID
      int uid, gid;                   // 用户/组 ID（oskernel2023-zmz 缺失）
      enum procstate state;
      struct proc *parent;
      void *chan;
      uint64 kstack;
      uint64 sz;                      // 进程内存大小（oskernel2023-zmz 无此字段）
      pagetable_t pagetable;
      struct trapframe *trapframe;
      struct context context;
      struct file **ofile;            // 打开文件表
      struct dirent *cwd;
      struct vma *vma;                // VMA 链表（oskernel2023-zmz 使用 segment）
      ksigaction_t *sig_act;
      uint64 set_child_tid;           // 线程支持字段（oskernel2023-zmz 缺失）
      uint64 clear_child_tid;
      struct robust_list_head *robust_list;
  };
  ```

### 关键差异

| 特性 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **PCB/TCB 区分** | ❌ 未区分，统一 `struct proc` | ❌ 未区分，统一 `struct proc` |
| **用户/组 ID** | ❌ 未发现 `uid`/`gid` 字段 | ✅ 已实现 `uid`, `gid` |
| **内存管理结构** | ✅ 使用 `struct seg *segment` + `pbrk` | ✅ 使用 `struct vma *vma` |
| **线程支持字段** | ❌ 未发现 `set_child_tid`/`clear_child_tid` | ✅ 已实现线程相关字段 |
| **进程内存大小** | ❌ 无 `sz` 字段 | ✅ 有 `sz` 字段 |

**结论**：两个项目均采用统一的 `struct proc` 表示执行实体，未严格区分 PCB 与 TCB。oskernrl2022-rv6 在线程支持和用户权限管理方面更完善。

---

## 调度算法差异

### oskernel2023-zmz：多级优先级调度

**实现位置**：`kernel/sched/proc.c:239-243`, `kernel/sched/proc.c:596-612`

```c
#define PRIORITY_TIMEOUT    0   // 超时队列（最低优先级）
#define PRIORITY_IRQ        1   // 中断唤醒队列（高优先级）
#define PRIORITY_NORMAL     2   // 正常队列（默认优先级）
#define PRIORITY_NUMBER     3
struct proc *proc_runnable[PRIORITY_NUMBER];  // 优先级队列数组
```

**调度逻辑**（`kernel/sched/proc.c:596-612`）：
```c
static struct proc *__get_runnable_no_lock(void) {
    struct proc const *tmp;
    for (int i = 0; i < PRIORITY_NUMBER; i ++) {  // 按优先级顺序遍历
        tmp = proc_runnable[i];
        while (NULL != tmp) {
            if (RUNNABLE == tmp->state) {
                return (struct proc*)tmp;  // 返回第一个 RUNNABLE 进程
            }
            tmp = tmp->sched_next;
        }
    }
    return NULL;
}
```

**调度策略分析**：
- ✅ **已实现**：严格优先级调度（Priority 0 < 1 < 2）
- ✅ **已实现**：中断唤醒进程插入高优先级队列（`PRIORITY_IRQ`）
- ❌ **未实现**：同一优先级内为**FIFO 顺序**，**非时间片轮转（RR）**
- ❌ **未实现**：无动态优先级调整、无 CFS/Stride 等公平调度算法
- 🔸 **部分实现**：`proc_tick()` 实现定时器递减，但仅对**非 RUNNING 状态**进程递减（逻辑可疑）

**时间片管理**（`kernel/sched/proc.c:740-774`）：
```c
void proc_tick(void) {
    // 仅对非 RUNNING 状态进程递减 timer
    for (int i = PRIORITY_IRQ; i < PRIORITY_NUMBER; i ++) {
        p = proc_runnable[i];
        while (NULL != p) {
            if (RUNNING != p->state) {
                p->timer = p->timer - 1;
                if (0 == p->timer) {
                    __remove(p);
                    __insert_runnable(PRIORITY_TIMEOUT, p);  // 超时降级
                }
            }
            p = next;
        }
    }
}
```

### oskernrl2022-rv6：简单 FIFO 轮转

**实现位置**：`src/proc.c:119-152`, `src/proc.c:100-106`

```c
void scheduler(){
    struct cpu *c = mycpu();
    c->proc = 0;
    while(1){
        struct proc* p = readyq_pop();  // 从全局单队列取出
        if(p){
            acquire(&p->lock);
            if(p->state == RUNNABLE) {
                p->state = RUNNING;
                c->proc = p;
                w_satp(MAKE_SATP(p->pagetable));
                sfence_vma();
                swtch(&c->context, &p->context);
                w_satp(MAKE_SATP(kernel_pagetable));
                sfence_vma();
                c->proc = 0;
            }
            release(&p->lock);
        }else{
            intr_on();
            asm volatile("wfi");
        }
    }
}
```

**就绪队列**（`src/proc.c:29`）：
```c
queue readyq;  // 全局单队列
```

**调度策略分析**：
- ✅ **已实现**：简单 FIFO 轮转调度
- ❌ **未实现**：无优先级概念
- ❌ **未实现**：无时间片机制
- ❌ **未实现**：无多调度器支持（无 feature flag 切换）

### 调度算法对比总结

| 特性 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **调度算法** | ✅ 多级优先级（3 级） | ✅ 简单 FIFO |
| **优先级数量** | 3 级（TIMEOUT/IRQ/NORMAL） | 无优先级 |
| **时间片轮转** | ❌ 未实现（同一优先级内 FIFO） | ❌ 未实现 |
| **动态优先级** | ❌ 未实现 | N/A |
| **多调度器支持** | ❌ 未发现 feature flag | ❌ 未发现 feature flag |
| **抢占式调度** | 🔸 部分实现（timer 递减逻辑可疑） | ❌ 仅依赖 `yield()` |

---

## 上下文切换差异

### 汇编实现对比

**oskernel2023-zmz**（`kernel/sched/swtch.S:3-41`）：
```assembly
.globl swtch
swtch:
    sd ra, 0(a0)      # 保存 ra
    sd sp, 8(a0)      # 保存 sp
    sd s0, 16(a0)     # 保存 s0-s11
    # ... (s1-s11)
    sd s11, 104(a0)

    ld ra, 0(a1)      # 恢复 ra
    ld sp, 8(a1)      # 恢复 sp
    # ... (s0-s11)
    ld s11, 104(a1)
    
    ret
```

**oskernrl2022-rv6**（`src/swtch.S:1-42`）：
```assembly
.globl swtch
swtch:
    sd ra, 0(a0)
    sd sp, 8(a0)
    sd s0, 16(a0)
    # ... (s1-s11)
    sd s11, 104(a0)

    ld ra, 0(a1)
    ld sp, 8(a1)
    # ... (s0-s11)
    ld s11, 104(a1)

    ret
```

### 保存寄存器对比

| 寄存器 | oskernel2023-zmz | oskernrl2022-rv6 | 用途 |
|--------|------------------|------------------|------|
| ra | ✅ 保存（偏移 0） | ✅ 保存（偏移 0） | 返回地址 |
| sp | ✅ 保存（偏移 8） | ✅ 保存（偏移 8） | 栈指针 |
| s0-s11 | ✅ 保存（偏移 16-104） | ✅ 保存（偏移 16-104） | callee-saved |
| **总计** | **13 个寄存器，104 字节** | **13 个寄存器，104 字节** | |
| **浮点寄存器** | 🔸 惰性保存（`floatstore()`/`floatload()`） | ❌ 未发现浮点保存逻辑 | |

### 浮点寄存器处理

**oskernel2023-zmz**（`kernel/sched/proc.c:714-720`）：
```c
void sched(void) {
    // ...
    if (r_sstatus_fs() == SSTATUS_FS_DIRTY) {
        floatstore(p->trapframe);  // 惰性保存到 trapframe
        w_sstatus_fs(SSTATUS_FS_CLEAN);
    }
    swtch(&p->context, &mycpu()->context);
    // ...
    floatload(p->trapframe);  // 从 trapframe 恢复
    w_sstatus_fs(SSTATUS_FS_CLEAN);
}
```

**oskernrl2022-rv6**：
- ❌ **未发现**：`floatstore()`/`floatload()` 或类似的浮点寄存器保存逻辑
- ❌ **未发现**：`sstatus.FS` 位检查

**结论**：两个项目的 `swtch.S` 汇编代码**几乎完全相同**，均仅保存 callee-saved 寄存器（ra + sp + s0-s11）。**关键差异**：oskernel2023-zmz 实现了浮点寄存器的惰性保存机制，而 oskernrl2022-rv6 未发现相关实现。

---

## Call Graph 差异

### `scheduler` 函数调用链对比

**共同调用**（7 个）：`acquire`, `intr_on`, `mycpu`, `release`, `sfence_vma`, `swtch`, `w_satp`

**oskernel2023-zmz 独有**（4 个）：
- `__get_runnable_no_lock` — 优先级队列选择逻辑
- `__panic` — 错误处理
- `cpuid` — CPU ID 获取
- `printf` — 调试输出

**oskernrl2022-rv6 独有**（2 个）：
- `readyq_pop` — 全局队列弹出
- `queue_pop` — 底层队列操作

**Call Graph 节点 Jaccard 相似度**：0.538（7 共同 / 13 全集）

### `clone` 函数调用链对比

**共同调用**（17 个）：`acquire`, `allocproc`, `forkret`, `freeproc`, `kfree`, `kmalloc`, `kvmcreate`, `memset`, `myproc`, `proc_freepagetable`, `proc_pagetable`, `release`, `safestrcpy`, `sigaction_copy`, `sigaction_free`, `sigframefree`, `usertrapret`

**oskernel2023-zmz 独有**（22 个）：
- 内存分配：`__mul_alloc_no_lock`, `__sin_alloc_no_lock`, `_allocpage`, `_freepage`
- 进程管理：`__proc_list_insert_no_lock`, `hash_insert_no_lock`, `hash_remove_no_lock`
- 内存复制：`copysegs`, `copyfdtable`, `idup`
- 浮点处理：`floatstore`, `r_sstatus_fs`, `w_sstatus_fs`
- 文件系统：`namei`, `rootfs_init`
- 其他：`initlock`, `kvmfree`, `uvmfree`, `delsegs`, `readtime`

**oskernrl2022-rv6 独有**（17 个）：
- 进程管理：`allocparent`, `allocpid`, `readyq_push`, `queue_push`
- 内存管理：`vma_copy`, `vma_deep_mapping`, `vma_shallow_mapping`, `vma_list_init`, `free_vma_list`, `freewalk`
- 文件系统：`filedup`, `edup`, `copyout`
- 其他：`free_map_fix`, `allocpage`, `freepage`, `panic`

**Call Graph 节点 Jaccard 相似度**：0.304（17 共同 / 56 全集）

### 关键差异分析

1. **内存管理架构差异**：
   - oskernel2023-zmz 使用 `segment` 链表 + `copysegs()` 进行地址空间复制
   - oskernrl2022-rv6 使用 `vma` 链表 + `vma_copy()`/`vma_deep_mapping()` 进行地址空间复制

2. **进程队列管理差异**：
   - oskernel2023-zmz 使用优先级队列数组 `proc_runnable[PRIORITY_NUMBER]` + `__insert_runnable()`
   - oskernrl2022-rv6 使用全局单队列 `readyq` + `readyq_push()`/`readyq_pop()`

3. **浮点处理差异**：
   - oskernel2023-zmz 在 `clone()` 中显式处理浮点寄存器保存（`floatstore()`）
   - oskernrl2022-rv6 未发现浮点处理逻辑

---

## 进程管理扩展

### 进程组（PGID）与会话（SID）

**oskernel2023-zmz**：
- ❌ **未实现**：搜索 `pgid|session_id|setpgid|getsid|set_sid` 未找到任何相关代码（已搜索 193 个文件）

**oskernrl2022-rv6**：
- ❌ **未实现**：搜索 `pgid|session_id|setpgid|getsid|set_sid` 未找到任何相关代码（已搜索 145 个文件）

**结论**：两个项目均**未实现** POSIX 进程组（Process Group）和会话（Session）机制。

### 资源限制（rlimit）

**oskernel2023-zmz**：
- ❌ **未发现**：`struct rlimit` 定义或 `getrlimit()`/`setrlimit()` 系统调用

**oskernrl2022-rv6**：
- 🔸 **桩函数**：`src/include/proc.h:91-111` 定义了完整的 POSIX 资源限制结构体和常量（`RLIMIT_CPU` 到 `RLIMIT_RTTIME` 共 16 种）
- ❌ **未实现**：搜索 `getrlimit|setrlimit|sys_prlimit64` 未找到任何实现代码

**结论**：oskernrl2022-rv6 仅有结构体定义，**未实现任何系统调用**；oskernel2023-zmz 完全未实现。

### fork() 地址空间复制差异（重要）

**oskernel2023-zmz**（`kernel/sched/proc.c:289-368`）：
```c
int clone(uint64 flag, uint64 stack) {
    // ...
    np->segment = copysegs(p->pagetable, p->segment, np->pagetable);  // 复制段链表
    if (NULL == np->segment) {
        freeproc(np);
        return -1;
    }
    np->pbrk = p->pbrk;
    // ...
    *(np->trapframe) = *(p->trapframe);
    np->trapframe->a0 = 0;
    // ...
}
```

**oskernrl2022-rv6**（`src/proc.c:408-492`）：
```c
int clone(uint64 flag, uint64 stack, uint64 ptid, uint64 tls, uint64 ctid) {
    if((flag & CLONE_THREAD) && (flag & CLONE_VM)) {
        // 线程创建：共享地址空间（浅拷贝 VMA）
        np = allocproc(p, 1);  // thread_create=1
    } else {
        // 进程创建：独立地址空间（深拷贝 VMA）
        np = allocproc(p, 0);  // thread_create=0
    }
    // ...
    *(np->trapframe) = *(p->trapframe);
    np->trapframe->a0 = 0;
    // ...
}
```

**关键差异**：
- oskernel2023-zmz：`clone()` **始终复制地址空间**（通过 `copysegs()`），**不支持线程共享地址空间**
- oskernrl2022-rv6：`clone()` 根据 `CLONE_THREAD | CLONE_VM` 标志**区分进程/线程**：
  - 进程：深拷贝 VMA（`vma_deep_mapping()`）
  - 线程：浅拷贝 VMA（`vma_shallow_mapping()`）— 但**未实现写时复制（CoW）**

**⚠️ 重要差异标注**：oskernrl2022-rv6 支持通过 `clone()` 创建线程（共享地址空间），而 oskernel2023-zmz 的 `clone()` 仅支持创建进程（始终复制地址空间）。

---

## 信号/Futex 差异

### 信号机制对比

#### 核心实现

**oskernel2023-zmz**：
- ✅ **已实现**：`sighandle()`（`kernel/sched/signal.c`）
- ✅ **已实现**：`set_sigaction()`（`kernel/sched/signal.c:90-130`）
- ✅ **已实现**：`sigprocmask()`（`kernel/sched/signal.c:90-110`）
- ✅ **已实现**：`kill()`（`kernel/sched/proc.c:528-560`）
- ✅ **已实现**：系统调用 `sys_rt_sigaction`, `sys_rt_sigprocmask`, `sys_rt_sigreturn`（`kernel/syscall/syscall.c:170-171`, `kernel/syscall/syscall.c:235-236`）

**oskernrl2022-rv6**：
- ✅ **已实现**：`sighandle()`（`src/signal.c`）
- ✅ **已实现**：`set_sigaction()`（`src/signal.c:53-82`）
- ✅ **已实现**：`sigprocmask()`（`src/signal.c:85-105`）
- ✅ **已实现**：`kill()`（`src/proc.c:752-770`）
- ✅ **已实现**：系统调用 `sys_rt_sigaction`, `sys_rt_sigprocmask`, `sys_rt_sigreturn`, `sys_kill`（`src/syssig.c:54-93`）

#### 信号处理细节对比

| 特性 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **信号帧分配** | `kmalloc(sizeof(struct sig_frame))` | `allocpage()`（整页分配） |
| **trapframe 分配** | `kmalloc(sizeof(struct trapframe))` | `allocpage()`（整页分配） |
| **sa_flags 处理** | ✅ 完整复制 `sa_flags` | 🔸 注释掉 `sa_flags` 复制 |
| **sa_mask 处理** | ✅ 完整处理阻塞掩码 | 🔸 注释掉 `sa_mask` 处理 |
| **handler 设置** | ✅ 正确设置 `tf->a1 = handler` | 🔸 始终使用 `default_sigaction`（代码可疑） |

**oskernrl2022-rv6 信号处理代码问题**（`src/signal.c:118-170`）：
```c
if (NULL != sigact && sigact->sigact.__sigaction_handler.sa_handler) {
    //temp way
    tf->a1 = (uint64)(SIG_TRAMPOLINE + ((uint64)default_sigaction - (uint64)sig_trampoline));
}
else {
    tf->a1 = (uint64)(SIG_TRAMPOLINE + ((uint64)default_sigaction - (uint64)sig_trampoline));
}
```
**问题**：无论是否注册了自定义 handler，**始终使用 `default_sigaction`**，这是一个明显的实现缺陷。

#### 支持的信号

两个项目均支持相同的信号集合（`SIGTERM(15)`, `SIGKILL(9)`, `SIGABRT(6)`, `SIGHUP(1)`, `SIGINT(2)`, `SIGQUIT(3)`, `SIGILL(4)`, `SIGTRAP(5)`, `SIGCHLD(17)`, `SIGRTMIN(34)` 到 `SIGRTMAX(64)`）。

### Futex 机制对比

**oskernel2023-zmz**：
- ❌ **未实现**：搜索 `futex_wait|futex_wake|do_futex|sys_futex` 未找到任何代码（已搜索 193 个文件）
- ❌ **未发现**：`FUTEX_WAIT`/`FUTEX_WAKE` 等常量定义

**oskernrl2022-rv6**：
- 🔸 **接口定义**：`src/include/proc.h:18-50` 定义了 `FUTEX_WAIT`, `FUTEX_WAKE`, `FUTEX_REQUEUE` 等 15 种操作
- 🔸 **函数声明**：`src/include/proc.h:199` 声明了 `int do_futex(...)`
- ❌ **未实现**：搜索 `fn do_futex|int do_futex|void do_futex` 未找到具体实现（已搜索 145 个文件）
- 📄 **文档规划**：`doc/内核实现--Futex.md` 描述了设计思路，但代码未实现
- ❌ **未实现**：`sys_futex` 系统调用未在系统调用表中找到

**结论**：两个项目均**未完整实现 Futex 机制**。oskernrl2022-rv6 仅有接口定义和文档规划，oskernel2023-zmz 完全未实现。

### 信号/Futex 对比总结

| 特性 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **信号基础机制** | ✅ 已实现 | ✅ 已实现 |
| **sigaction 注册** | ✅ 完整实现 | ✅ 已实现（但有缺陷） |
| **sigprocmask** | ✅ 完整实现 | ✅ 已实现（部分注释掉） |
| **信号分发** | ✅ 正确设置自定义 handler | 🔸 始终使用 default_sigaction（缺陷） |
| **信号帧分配** | `kmalloc()` | `allocpage()`（浪费内存） |
| **Futex** | ❌ 未实现 | 🔸 仅接口定义，未实现 |

---

## 总体结论

### 核心差异总结

1. **调度算法**：
   - oskernel2023-zmz：✅ 多级优先级调度（3 级），但同一优先级内为 FIFO
   - oskernrl2022-rv6：✅ 简单 FIFO 轮转，无优先级

2. **任务模型**：
   - oskernel2023-zmz：❌ 不支持线程（`clone()` 始终复制地址空间）
   - oskernrl2022-rv6：✅ 支持线程（通过 `CLONE_VM` 标志共享地址空间）

3. **上下文切换**：
   - oskernel2023-zmz：✅ 浮点寄存器惰性保存
   - oskernrl2022-rv6：❌ 未发现浮点处理逻辑

4. **信号机制**：
   - oskernel2023-zmz：✅ 完整实现，正确处理自定义 handler
   - oskernrl2022-rv6：🔸 实现有缺陷（始终使用 default_sigaction）

5. **Futex**：
   - 两个项目均**未实现**

6. **进程组/会话/rlimit**：
   - 两个项目均**未实现**或仅有桩代码

### 创新点标注

**oskernel2023-zmz 独有特性**：
- 【创新点】多级优先级调度（3 级队列：TIMEOUT/IRQ/NORMAL）
- 【创新点】浮点寄存器惰性保存机制（`floatstore()`/`floatload()`）
- 【创新点】完整的 `sigprocmask()` 实现（包括 `sa_mask` 处理）

**oskernrl2022-rv6 独有特性**：
- 【创新点】线程支持（通过 `CLONE_THREAD | CLONE_VM` 标志）
- 【创新点】用户/组 ID（`uid`, `gid`）支持
- 【创新点】VMA（虚拟内存区域）管理机制
- 【创新点】POSIX 资源限制结构体定义（虽未实现系统调用）

### 代码相似度评估

- **`swtch.S`**：几乎完全相同（Jaccard 相似度接近 1.0）
- **`scheduler()`**：设计思路相似（均调用 `swtch()`），但队列管理逻辑不同（Jaccard 0.538）
- **`clone()`**：设计思路相似（均复制 trapframe、建立亲缘关系），但内存管理架构不同（Jaccard 0.304）
- **`sighandle()`**：代码高度相似，但 oskernrl2022-rv6 存在 handler 设置缺陷

**总体评价**：两个项目在核心调度/上下文切换机制上**设计思路相似**，但实现细节存在显著差异。oskernel2023-zmz 在调度算法和浮点处理上更完善，oskernrl2022-rv6 在线程支持和内存管理架构上更灵活。