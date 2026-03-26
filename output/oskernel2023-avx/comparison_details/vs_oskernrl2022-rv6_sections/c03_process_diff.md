## 任务模型差异

### oskernel2023-avx：严格的 PCB/TCB 分离设计

**✅ 已实现独立的 TCB 结构体**

目标项目采用类 Unix 的**进程-线程分离模型**，明确区分 PCB（进程控制块）和 TCB（线程控制块）：

**证据文件**：`kernel/include/proc.h:52-98` 和 `kernel/include/thread.h:22-44`

```c
// PCB: 进程是资源分配单位
struct proc {
  struct spinlock lock;
  enum procstate state;
  int pid, uid, gid, pgid;          // ✅ 包含 pgid 进程组 ID
  thread *main_thread;              // ✅ 指向主线程 TCB
  thread *thread_queue;             // ✅ 线程双向链表头
  int thread_num;
  uint64 kstack;
  pagetable_t pagetable;
  struct vma *vma;
  sigaction sigaction[SIGRTMAX + 1]; // ✅ 65 个信号处理函数
  __sigset_t sig_set, sig_pending;
  // ... 文件表、当前目录等
};

// TCB: 线程是调度基本单位
struct thread {
  enum threadState state;           // 6 种状态（含 t_TIMING）
  struct proc *p;                   // 所属进程指针
  int tid;                          // 线程 ID
  uint64 awakeTime;                 // 定时唤醒时间（Futex 用）
  uint64 kstack;                    // 独立内核栈
  struct trapframe *trapframe;
  context context;
  struct thread *next_thread, *pre_thread;  // 双向链表
};
```

**关键特征**：
- **1:N 模型**：一个 `proc` 通过 `thread_queue` 双向链表管理多个 `thread`
- **主线程特殊**：`fork()` 时自动创建 `main_thread`，调度时实际切换的是线程
- **独立内核栈**：每个线程有独立的 `kstack` 和 `trapframe`

---

### oskernrl2022-rv6：统一的 proc 结构

**❌ 未实现独立 TCB**

候选项目采用**统一结构体设计**，进程和线程均使用 `struct proc` 表示：

**证据文件**：`src/include/proc.h:115-171`

```c
struct proc {
  int magic;
  struct spinlock lock;
  enum procstate state;
  int pid, uid, gid;                // ❌ 无 pgid 字段
  uint64 kstack;
  pagetable_t pagetable;
  struct trapframe *trapframe;
  struct context context;
  struct vma *vma;
  ksigaction_t *sig_act;            // 链表式信号处理
  __sigset_t sig_set, sig_pending;
  uint64 set_child_tid;
  uint64 clear_child_tid;
  struct robust_list_head *robust_list;
  // ❌ 无 thread_queue, main_thread 字段
};
```

**关键特征**：
- **统一表示**：通过 `clone()` 系统调用的 `CLONE_THREAD|CLONE_VM` 标志区分进程/线程
- **共享资源**：线程共享父进程的 `pagetable`、`vma`、`ofile`
- **独立资源**：每个线程有独立的 `kstack`、`trapframe`、`context`、`pid`

---

### 核心差异对比表

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **TCB 结构体** | ✅ `struct thread` 独立定义 | ❌ 未定义，复用 `struct proc` |
| **进程-线程关系** | ✅ 1:N（`thread_queue` 双向链表） | 🔸 通过 `clone()` 标志隐式区分 |
| **主线程指针** | ✅ `main_thread` 字段 | ❌ 无 |
| **线程状态枚举** | ✅ 6 态（含 `t_TIMING`） | ❌ 复用进程 5 态 |
| **PGID 支持** | ✅ `int pgid` 字段 | ❌ 无 |

---

## 调度算法差异

### oskernel2023-avx：线程级轮转调度

**✅ 已实现基于线程的简单轮转调度**

**证据文件**：`kernel/proc.c:669-753`

```c
void scheduler(void) {
  struct cpu *c = mycpu();
  c->proc = 0;
  for (;;) {
    intr_on();
    int found = 0;
    // 线性扫描全局进程表
    for (p = proc; p < &proc[NPROC]; p++) {
      acquire(&p->lock);
      if (p->state == RUNNABLE) {
        // ✅ 遍历线程链表找可运行线程
        thread *t = p->thread_queue;
        while (NULL != t) {
          if (t->state == t_RUNNABLE ||
              (t->state == t_TIMING && t->awakeTime < r_time() + (1LL << 35)))
            break;
          t = t->next_thread;
        }
        if (NULL == t) continue;  // 该进程无可运行线程
        
        // ✅ 将找到的线程移到队列头部
        if (p->thread_queue != t) {
          // 链表重排逻辑（省略）
          p->thread_queue = t;
        }
        p->main_thread = t;  // 设置为主线程
        copycontext(&p->context, &p->main_thread->context);
        copytrapframe(p->trapframe, p->main_thread->trapframe);
        p->main_thread->state = t_RUNNING;
        p->state = RUNNING;
        futexClear(p->main_thread);  // ✅ 清理 Futex 等待
        
        w_satp(MAKE_SATP(p->kpagetable));
        sfence_vma();
        swtch(&c->context, &p->context);
        // ...
      }
      release(&p->lock);
    }
    if (found == 0) {
      intr_on();
      asm volatile("wfi");
    }
  }
}
```

**调度策略分析**：
- **✅ 线程级调度**：在进程内遍历 `thread_queue`，选择第一个可运行线程
- **✅ 简单轮转**：线性扫描 `proc[NPROC]` 数组，按 PID 顺序选择
- **✅ Futex 集成**：调用 `futexClear()` 清理退出线程的 Futex 等待
- **❌ 无优先级**：代码中未发现 `priority`、`stride`、`nice` 等字段
- **❌ 非 CFS**：无虚拟运行时间、红黑树等 CFS 特征
- **🔸 TODO 注释**：`// TODO: 改进线程枚举算法` 表明作者意识到当前算法简陋

---

### oskernrl2022-rv6：进程级 FIFO 调度

**✅ 已实现基于全局就绪队列的 FIFO 调度**

**证据文件**：`src/proc.c:119-152`

```c
void scheduler(){
  struct cpu *c = mycpu();
  c->proc = 0;
  while(1){
    // ✅ 从全局就绪队列取出进程
    struct proc* p = readyq_pop();
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

**就绪队列实现**：
- **全局单队列**：`readyq`（`src/proc.c:29`）
- **FIFO 操作**：`queue_push`/`queue_pop`（`src/include/queue.h:36-52`）
- **无优先级**：`readyq_pop()` 直接返回队列头，未进行优先级比较

**调度策略分析**：
- **✅ 进程级调度**：直接操作 `struct proc`，无线程概念
- **✅ FIFO 队列**：使用 `readyq_pop()` 从全局队列取进程
- **❌ 无时间片**：无 `counter`、`time_slice` 等字段
- **❌ 无 Futex 集成**：未调用任何 Futex 清理函数

---

### 调度算法对比表

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **调度粒度** | ✅ 线程级 | ✅ 进程级 |
| **调度策略** | ✅ 简单轮转（线性扫描） | ✅ FIFO 队列 |
| **就绪队列** | ❌ 无全局队列，线性扫描 `proc[]` | ✅ 全局 `readyq` 链表 |
| **优先级支持** | ❌ 无 | ❌ 无 |
| **时间片轮转** | ❌ 无 | ❌ 无 |
| **Futex 集成** | ✅ `futexClear()` | ❌ 无 |
| **多调度器支持** | ❌ 无 feature flag | ❌ 无 |

---

## Call Graph 差异

### `scheduler` 调用图对比

**Jaccard 相似度：0.467**（7 共同 / 15 全集）

| 共同调用 | oskernel2023-avx 独有 | oskernrl2022-rv6 独有 |
|----------|----------------------|----------------------|
| `acquire` | `copycontext` | `queue_pop` |
| `intr_on` | `copytrapframe` | `readyq_pop` |
| `mycpu` | `futexClear` | |
| `release` | `r_time` | |
| `sfence_vma` | `cpuid`/`r_tp` | |
| `swtch` | | |
| `w_satp` | | |

**关键差异**：
- **oskernel2023-avx**：额外调用 `copycontext`、`copytrapframe` 进行线程上下文复制，调用 `futexClear` 清理 Futex 等待
- **oskernrl2022-rv6**：使用 `readyq_pop()` → `queue_pop()` 从就绪队列取进程，无线程操作

---

### `fork`/`clone` 调用图对比

**oskernel2023-avx** 有独立的 `sys_fork` 系统调用，**oskernrl2022-rv6** 无 `sys_fork`，仅通过 `clone()` 实现。

#### `sys_fork` 调用链（仅 oskernel2023-avx）

```
sys_fork (kernel/sysproc.c:263)
└── fork (kernel/proc.c:443)
    ├── allocproc()          # 分配新 PCB + 主线程
    ├── uvmcopy()            # ✅ 复制用户地址空间（写时复制）
    ├── vma_copy() + vma_map()  # ✅ 复制 VMA 链表
    ├── filedup()            # ✅ 复制文件描述符
    ├── edup()               # ✅ 复制当前目录
    └── copytrapframe()      # ✅ 复制 Trapframe 到主线程
```

**关键验证**：
- ✅ **地址空间复制**：调用 `uvmcopy()` 实现写时复制（COW）
- ✅ **文件表复制**：循环调用 `filedup()` 增加引用计数
- ✅ **VMA 复制**：`vma_copy()` + `vma_map()` 重建虚拟内存区域

#### `clone` 调用链对比

**Jaccard 相似度：0.109**（6 共同 / 55 全集）

| 共同调用 | oskernel2023-avx 独有 | oskernrl2022-rv6 独有 |
|----------|----------------------|----------------------|
| `copyout` | `allocNewThread` | `allocproc` |
| `forkret` | `copycontext_from_trapframe` | `allocparent` |
| `myproc` | `copyin` | `vma_deep_mapping` |
| `panic` | `copytrapframe` | `vma_shallow_mapping` |
| `release` | `either_copyout` | `sigaction_copy` |
| `usertrapret` | `kalloc`, `mappages` | `readyq_push` |

**关键差异**：
- **oskernel2023-avx**：
  - 调用 `allocNewThread()` 创建新线程
  - 调用 `copytrapframe()` 复制 Trapframe 到线程
  - 无 `readyq_push()`，线程通过 `p->thread_queue` 管理

- **oskernrl2022-rv6**：
  - 调用 `allocproc(p, thread_create)` 统一分配进程/线程
  - 调用 `vma_deep_mapping()`（深拷贝）或 `vma_shallow_mapping()`（浅拷贝）
  - 调用 `readyq_push()` 将新进程加入就绪队列
  - 调用 `sigaction_copy()` 复制信号处理函数

---

### 重要差异：fork 地址空间复制

**✅ oskernel2023-avx 的 `fork()` 真正复制了地址空间**

**证据文件**：`kernel/proc.c:443-516`

```c
int fork(void) {
  struct proc *np;
  struct proc *p = myproc();
  
  if ((np = allocproc()) == NULL) return -1;
  
  // ✅ 1. 复制用户内存（写时复制）
  if (uvmcopy(p->pagetable, np->pagetable, np->kpagetable, p->sz) < 0) {
    freeproc(np);
    return -1;
  }
  
  // ✅ 2. 复制 VMA 链表（支持 mmap 区域）
  struct vma *nvma = vma_copy(np, p->vma);
  if (NULL != nvma) {
    nvma = nvma->next;
    while (nvma != np->vma) {
      if (vma_map(p->pagetable, np->pagetable, nvma) < 0) {
        printf("clone: vma deep mapping failed\n");
        return -1;
      }
      nvma = nvma->next;
    }
  }
  
  // ✅ 3. 复制 Trapframe 到主线程
  copytrapframe(np->main_thread->trapframe, np->trapframe);
  
  // ✅ 4. 复制文件描述符
  for (i = 0; i < NOFILE; i++)
    if (p->ofile[i])
      np->ofile[i] = filedup(p->ofile[i]);
  
  np->state = RUNNABLE;
  np->main_thread->state = t_RUNNABLE;
  return np->pid;
}
```

**✅ oskernrl2022-rv6 的 `clone()` 也复制了地址空间**

**证据文件**：`src/proc.c:408-492`

```c
int clone(uint64 flag, uint64 stack, uint64 ptid, uint64 tls, uint64 ctid) {
  struct proc *np;
  struct proc *p = myproc();
  
  if((flag & CLONE_THREAD) && (flag & CLONE_VM)) {
    // 线程创建：共享地址空间（浅拷贝 VMA）
    np = allocproc(p, 1);  // thread_create=1
  } else {
    // 进程创建：独立地址空间（深拷贝 VMA）
    np = allocproc(p, 0);  // thread_create=0
  }
  
  // 在 allocproc() → proc_pagetable() 中调用：
  // - vma_copy()
  // - vma_deep_mapping()  // ✅ 深拷贝物理页
  
  // 复制文件表
  for(i = 0; i < NOFILE; i++)
    if(p->ofile[i])
      np->ofile[i] = filedup(p->ofile[i]);
  np->cwd = edup(p->cwd);
  
  np->state = RUNNABLE;
  readyq_push(np);  // ✅ 加入就绪队列
  return pid;
}
```

**结论**：两个项目都实现了地址空间复制，但方式不同：
- **oskernel2023-avx**：在 `fork()` 中显式调用 `uvmcopy()` + `vma_map()`
- **oskernrl2022-rv6**：在 `allocproc()` → `proc_pagetable()` 中调用 `vma_deep_mapping()`

---

## 信号/Futex 差异

### 信号机制对比

#### oskernel2023-avx：数组式信号处理

**✅ 已实现完整的信号机制**

**证据文件**：
- `kernel/signal.c`：信号处理核心逻辑
- `kernel/include/signal.h`：信号常量定义（`SIGRTMIN=32` 到 `SIGRTMAX=64`）
- `kernel/sysproc.c`：系统调用接口

**核心功能**：

1. **信号注册**：`set_sigaction()`（`kernel/signal.c:9-19`）
   ```c
   int set_sigaction(int signum, sigaction const *act, sigaction *oldact) {
     struct proc *p = myproc();
     if (oldact != NULL)
       *oldact = p->sigaction[signum];
     if (act != NULL)
       p->sigaction[signum] = *act;
     return 0;
   }
   ```
   - **数组式存储**：`sigaction[SIGRTMAX + 1]`（65 个元素）

2. **信号发送**：`kill(pid, sig)`（`kernel/proc.c:876-896`）
   ```c
   int kill(int pid, int sig) {
     for (p = proc; p < &proc[NPROC]; p++) {
       if (p->pid == pid) {
         p->sig_pending.__val[0] |= (1 << sig);  // 设置待处理位
         if (p->killed == 0 || p->killed > sig)
           p->killed = sig;
         if (p->state == SLEEPING)
           p->state = RUNNABLE;
         return 0;
       }
     }
     return -1;
   }
   ```

3. **信号分发**：`sighandle()`（`kernel/signal.c:59-79`）
   ```c
   void sighandle(void) {
     struct proc *p = myproc();
     int signum = p->killed;
     if (p->sigaction[signum].__sigaction_handler.sa_handler != NULL) {
       p->sig_tf = kalloc();  // 保存当前 trapframe
       memcpy(p->sig_tf, p->trapframe, sizeof(struct trapframe));
       p->trapframe->epc = (uint64)p->sigaction[signum].__sigaction_handler.sa_handler;
       p->trapframe->ra = (uint64)SIGTRAMPOLINE;
       p->trapframe->sp -= PGSIZE;
       p->sig_pending.__val[0] &= ~(1ul << signum);
     } else {
       exit(-1);  // 默认处理：终止进程
     }
   }
   ```

**系统调用支持**：
- ✅ `sys_kill`（`kernel/syscall.c:210`）
- ✅ `sys_rt_sigaction`（`kernel/syscall.c:270`）
- ✅ `sys_getpgid`/`sys_setpgid`（`kernel/sysproc.c:404-418`）

---

#### oskernrl2022-rv6：链表式信号处理

**✅ 已实现信号机制（部分功能）**

**证据文件**：
- `src/signal.c`：信号处理核心逻辑
- `src/include/signal.h`：信号常量定义
- `src/sysproc.c`：系统调用接口

**核心功能**：

1. **信号注册**：`set_sigaction()`（`src/signal.c:46-82`）
   ```c
   int set_sigaction(int signum, struct sigaction const *act, struct sigaction *oldact) {
     struct proc *p = myproc();
     ksigaction_t *tmp = __search_sig(p, signum);
     if (tmp != NULL) {
       if (oldact != NULL)
         oldact->__sigaction_handler = tmp->sigact.__sigaction_handler;
       if (act != NULL)
         tmp->sigact = *act;
     } else {
       // ✅ 链表式存储：动态分配 ksigaction_t 节点
       ksigaction_t *new = kmalloc(sizeof(ksigaction_t));
       // ... 插入链表 ...
     }
   }
   ```
   - **链表式存储**：`ksigaction_t *sig_act` 链表，动态分配节点

2. **信号分发**：`sighandle()`（`src/signal.c:118-170`）
   ```c
   void sighandle(void) {
     struct proc *p = myproc();
     int signum = 0;
     if (p->killed) {
       signum = p->killed;
       // 遍历 sig_pending 位图找下一个待处理信号
       for (; i < SIGSET_LEN; i ++) {
         while (bit < len) {
           if (p->sig_pending.__val[i] & (1ul << bit)) {
             p->killed = i * len + bit;
             goto start_handle;
           }
           bit ++;
         }
       }
     }
     
   start_handle:
     sigact = __search_sig(p, signum);  // 链表搜索
     if (SIGCHLD == signum && (NULL == sigact || ...))
       return;  // 忽略 SIGCHLD
     
     frame = allocpage();  // 分配信号栈帧
     // ... 构建信号栈帧 ...
   }
   ```

**系统调用支持**：
- ✅ `sys_kill`（通过 `kill()` 设置 `p->killed`）
- ✅ `sys_rt_sigaction`（`src/syssig.c:54-85`）
- ❌ **无 `sys_getpgid`/`sys_setpgid`**（grep 搜索未找到）

---

### 信号机制对比表

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **存储结构** | ✅ 数组 `sigaction[65]` | ✅ 链表 `ksigaction_t *sig_act` |
| **信号数量** | ✅ 65 个（`SIGRTMAX=64`） | ✅ 64 个（`SIGSET_LEN=1`） |
| **信号分发** | ✅ 同步（trap 返回时检查） | ✅ 同步（trap 返回时检查） |
| **SIGCHLD 特殊处理** | ❌ 无 | ✅ 忽略无处理函数的 SIGCHLD |
| **信号栈帧** | ✅ `sig_tf` 单帧 | ✅ `sig_frame` 链表 |
| **PGID 系统调用** | ✅ `sys_getpgid`/`sys_setpgid` | ❌ 未实现 |

---

### Futex 机制对比

#### oskernel2023-avx：完整实现

**✅ 已实现 Futex 等待/唤醒/重队列**

**证据文件**：`kernel/futex.c:1-70`

```c
typedef struct FutexQueue {
  uint64 addr;      // futex 地址
  thread *thread;   // ✅ 等待的线程
  uint8 valid;      // 槽位有效性
} FutexQueue;

FutexQueue futexQueue[FUTEX_COUNT];  // 全局等待队列，FUTEX_COUNT=1024

// ✅ FUTEX_WAIT
void futexWait(uint64 addr, thread *th, TimeSpec2 *ts) {
  for (int i = 0; i < FUTEX_COUNT; i++) {
    if (!futexQueue[i].valid) {
      futexQueue[i].valid = 1;
      futexQueue[i].addr = addr;
      futexQueue[i].thread = th;
      if (ts) {
        th->awakeTime = ts->tv_sec * 1000000 + ts->tv_nsec / 1000;
        th->state = t_TIMING;  // ✅ 定时等待
      } else {
        th->state = t_SLEEPING;
      }
      acquire(&th->p->lock);
      th->p->state = RUNNABLE;  // 进程保持 RUNNABLE
      sched();  // 让出 CPU
      release(&th->p->lock);
      return;
    }
  }
  panic("No futex Resource!\n");
}

// ✅ FUTEX_WAKE
void futexWake(uint64 addr, int n) {
  for (int i = 0; i < FUTEX_COUNT && n; i++) {
    if (futexQueue[i].valid && futexQueue[i].addr == addr) {
      futexQueue[i].thread->state = t_RUNNABLE;
      futexQueue[i].thread->trapframe->a0 = 0;  // 返回 0
      futexQueue[i].valid = 0;
      n--;
    }
  }
}

// ✅ 线程退出清理
void futexClear(thread *thread) {
  for (int i = 0; i < FUTEX_COUNT; i++) {
    if (futexQueue[i].valid && futexQueue[i].thread == thread) {
      futexQueue[i].valid = 0;
    }
  }
}
```

**系统调用集成**：
- ✅ `sys_futex`（`kernel/sysproc.c:527-530`）调用 `futexWait()`/`futexWake()`
- ✅ `scheduler()` 调用 `futexClear()` 清理退出线程

**设计特点**：
- **固定大小哈希表**：1024 个槽位，线性探测
- **线程级等待**：`futexQueue` 存储 `thread*`，支持多线程进程
- **超时支持**：通过 `t_TIMING` 状态和 `awakeTime` 实现定时唤醒

---

#### oskernrl2022-rv6：仅接口定义

**❌ 未实现 Futex 核心逻辑**

**证据**：
- **接口定义**：`src/include/proc.h:18-50` 定义了 `FUTEX_WAIT`、`FUTEX_WAKE` 等操作码
- **函数声明**：`src/include/proc.h:199` 声明了 `do_futex()` 函数
- **❌ 无实现**：grep 搜索 `do_futex(|futexWait(|futexWake(` 未找到任何实现代码

**结论**：Futex 机制**仅有接口定义和文档规划**，**未实际实现**。

---

### Futex 对比表

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **核心实现** | ✅ `futexWait()`/`futexWake()`/`futexRequeue()` | ❌ 未实现 |
| **等待队列** | ✅ 全局 `FutexQueue[1024]` | ❌ 无 |
| **超时支持** | ✅ `t_TIMING` 状态 + `awakeTime` | ❌ 无 |
| **线程级等待** | ✅ 存储 `thread*` | ❌ 无 |
| **退出清理** | ✅ `futexClear()` 在 `scheduler()` 中调用 | ❌ 无 |
| **系统调用** | ✅ `sys_futex` 已实现 | ❌ 未找到 |

---

## 进程管理扩展差异

### 进程组（PGID）与会话（SID）

#### oskernel2023-avx

**✅ 已实现 PGID 支持**

**证据**：
- **结构体字段**：`kernel/include/proc.h:66` 有 `int pgid;`
- **初始化**：`kernel/proc.c:237` 设置 `p->pgid = 0;`
- **系统调用**：`kernel/sysproc.c:404-418` 实现 `sys_setpgid()` 和 `sys_getpgid()`
- **系统调用表**：`kernel/syscall.c:275-276` 注册 `[SYS_getpgid]` 和 `[SYS_setpgid]`

```c
uint64 sys_setpgid(void) {
  int pid, pgid;
  if (argint(0, &pid) < 0 || argint(1, &pgid) < 0)
    return -1;
  myproc()->pgid = pgid;
  return 0;
}

uint64 sys_getpgid(void) {
  int pid;
  if (argint(0, &pid) < 0)
    return -1;
  return myproc()->pgid;
}
```

**❌ 未实现会话（SID）**：grep 搜索 `session|SID` 仅找到注释，无实际实现。

---

#### oskernrl2022-rv6

**❌ 未实现 PGID 和 SID**

**证据**：
- **结构体字段**：`src/include/proc.h:115-171` 无 `pgid` 字段
- **grep 搜索**：`pgid|session|SID|PGID` 仅找到 16 个匹配，均为无关内容（如 `fsid_t`、`csid` 等）
- **系统调用**：未找到 `sys_getpgid`/`sys_setpgid` 实现

---

### 资源限制（rlimit）

#### oskernel2023-avx

**❌ 未找到 rlimit 相关代码**

grep 搜索 `rlimit|RLIMIT` 未找到相关定义或实现。

---

#### oskernrl2022-rv6

**🔸 桩函数（仅结构体定义）**

**证据**：`src/include/proc.h:91-111` 定义了完整的 POSIX 资源限制结构体：

```c
#define RLIMIT_CPU     0
#define RLIMIT_FSIZE   1
#define RLIMIT_DATA    2
#define RLIMIT_STACK   3
#define RLIMIT_NOFILE  7
// ... 共 16 种限制

struct rlimit {
  rlim_t rlim_cur;
  rlim_t rlim_max;
};
```

**❌ 未实现系统调用**：grep 搜索 `getrlimit|setrlimit|sys_prlimit64` 未找到实现代码。

---

### 进程管理扩展对比表

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **PGID 字段** | ✅ `int pgid` | ❌ 无 |
| **sys_getpgid/setpgid** | ✅ 已实现 | ❌ 未实现 |
| **SID 支持** | ❌ 未实现 | ❌ 未实现 |
| **rlimit 结构体** | ❌ 无定义 | ✅ 已定义（16 种限制） |
| **sys_getrlimit/setrlimit** | ❌ 未实现 | ❌ 未实现（桩函数） |

---

## 上下文切换差异

### 寄存器保存对比

两个项目的 `swtch.S` 实现高度相似，均保存 **callee-saved 寄存器**（RISC-V 调用约定）。

#### oskernel2023-avx

**证据文件**：`kernel/swtch.S:1-46`

```assembly
.globl swtch
swtch:
    sd ra, 0(a0)
    sd sp, 8(a0)
    sd s0, 16(a0)
    sd s1, 24(a0)
    # ... 保存 s2-s11
    sd s11, 104(a0)

    ld ra, 0(a1)
    ld sp, 8(a1)
    # ... 恢复 s0-s11
    ld s11, 104(a1)
    
    ret
```

**保存的寄存器**：`ra, sp, s0-s11`（共 14 个寄存器，112 字节）

**❌ 不保存浮点寄存器**：代码中无 `fs0-fs11`、`ft0-ft7` 等浮点寄存器保存指令。

---

#### oskernrl2022-rv6

**证据文件**：`src/swtch.S:1-42`

```assembly
.globl swtch
swtch:
        sd ra, 0(a0)
        sd sp, 8(a0)
        sd s0, 16(a0)
        # ... 保存 s1-s11

        ld ra, 0(a1)
        ld sp, 8(a1)
        # ... 恢复 s0-s11

        ret
```

**保存的寄存器**：`ra, sp, s0-s11`（共 14 个寄存器，112 字节）

**❌ 不保存浮点寄存器**：代码中无浮点寄存器保存指令。

---

### 上下文切换对比表

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **保存寄存器** | ✅ `ra, sp, s0-s11`（14 个） | ✅ `ra, sp, s0-s11`（14 个） |
| **浮点寄存器** | ❌ 不保存 | ❌ 不保存 |
| **caller-saved 寄存器** | ❌ 不保存（由调用者保存） | ❌ 不保存（由调用者保存） |
| **切换流程** | ✅ `copytrapframe` 保存用户态寄存器 | ✅ `trapframe` 保存用户态寄存器 |

---

## 总结

### 核心差异概览

| 维度 | oskernel2023-avx | oskernrl2022-rv6 | 差异程度 |
|------|------------------|------------------|----------|
| **任务模型** | ✅ PCB/TCB 分离（`struct proc` + `struct thread`） | ❌ 统一 `struct proc` | 🔴 大 |
| **调度算法** | ✅ 线程级轮转（线性扫描 + 线程链表） | ✅ 进程级 FIFO（全局队列） | 🟡 中 |
| **上下文切换** | ✅ 14 个寄存器，无浮点 | ✅ 14 个寄存器，无浮点 | 🟢 小 |
| **fork 实现** | ✅ 独立 `sys_fork`，`uvmcopy()` + `vma_map()` | ✅ 通过 `clone()`，`vma_deep_mapping()` | 🟡 中 |
| **信号机制** | ✅ 数组式 `sigaction[65]` | ✅ 链表式 `ksigaction_t *` | 🟡 中 |
| **Futex** | ✅ 完整实现（`futexWait/Wake/Clear`） | ❌ 仅接口定义 | 🔴 大 |
| **PGID 支持** | ✅ `int pgid` + `sys_getpgid/setpgid` | ❌ 未实现 | 🔴 大 |
| **rlimit** | ❌ 无定义 | 🔸 仅结构体定义 | 🟡 中 |

### 【创新点】标注

1. **oskernel2023-avx 的创新点**：
   - ✅ **独立 TCB 设计**：明确的 `struct thread` 结构体，支持 1:N 进程-线程模型
   - ✅ **线程级 Futex**：`futexQueue` 存储 `thread*`，支持多线程进程的 Futex 等待
   - ✅ **PGID 系统调用**：实现 `sys_getpgid`/`sys_setpgid`，支持进程组管理
   - ✅ **Futex 超时机制**：通过 `t_TIMING` 状态和 `awakeTime` 实现定时唤醒

2. **oskernrl2022-rv6 的创新点**：
   - ✅ **链表式信号处理**：动态分配 `ksigaction_t` 节点，节省内存
   - ✅ **SIGCHLD 特殊处理**：忽略无处理函数的 SIGCHLD，符合 POSIX 语义
   - ✅ **rlimit 结构体定义**：定义了完整的 16 种 POSIX 资源限制（虽未实现系统调用）

### 重要差异结论

1. **任务模型**：oskernel2023-avx 采用更现代的 PCB/TCB 分离设计，oskernrl2022-rv6 采用传统的统一结构体设计。

2. **Futex 实现**：oskernel2023-avx 完整实现了 Futex 机制（等待/唤醒/重队列/清理），oskernrl2022-rv6 仅有接口定义，**这是最大的功能差距**。

3. **进程组支持**：oskernel2023-avx 实现了 PGID 字段和系统调用，oskernrl2022-rv6 完全未实现。

4. **fork 地址空间复制**：两个项目都实现了地址空间复制，但 oskernel2023-avx 在 `fork()` 中显式调用 `uvmcopy()`，oskernrl2022-rv6 在 `allocproc()` 中调用 `vma_deep_mapping()`。