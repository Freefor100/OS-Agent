## 数据结构对比

### 1. 进程/线程结构体对比

**oskernel2023-avx 的 `struct thread`** (repos\oskernel2023-avx\kernel\include\thread.h):
```c
struct thread {
    struct spinlock lock;
    enum threadState state;
    struct proc *p;
    void *chan;
    int tid;
    uint64 awakeTime;
    uint64 kstack;
    uint64 vtf;
    uint64 sz;
    struct trapframe *trapframe;
    context context;
    uint64 kstack_pa;
    uint64 clear_child_tid;
    struct thread *next_thread;
    struct thread *pre_thread;
}
```

**xv6-k210 的 `struct proc`** (repos\xv6-k210\include\sched\proc.h):
```c
struct proc {
    int xstate, pid;
    struct proc *hash_next, **hash_pprev;
    struct proc *sched_next, **sched_pprev;
    int timer;
    enum procstate state;
    void *chan;
    uint64 sleep_expire;
    struct tms proc_tms;
    uint64 ikstmp, okstmp;
    int64 vswtch, ivswtch;
    struct spinlock lk;
    struct proc *child, *parent, *sibling_next, **sibling_pprev;
    uint64 kstack, badaddr;
    pagetable_t pagetable;
    struct trapframe *trapframe;
    struct seg *segment;
    uint64 pbrk;
    struct fdtable fds;
    struct inode *cwd, *elf;
    struct context context;
    ksigaction_t *sig_act;
    __sigset_t sig_set, sig_pending;
    struct sig_frame *sig_frame;
    int killed, tmask;
    char name[16];
}
```

**【结构体差异分析】**:
- oskernel2023-avx 采用 **进程-线程分离模型** (`struct proc` + `struct thread`)，支持多线程
- xv6-k210 采用 **单线程进程模型**，所有线程相关字段内嵌在 `struct proc` 中
- 共同字段：`state`, `chan`, `kstack`, `trapframe`, `context`, `pid`/`tid`
- oskernel2023-avx 独有：`thread` 链表 (`next_thread`, `pre_thread`), `awakeTime`, `clear_child_tid`
- xv6-k210 独有：`segment` 链表, `sig_act/sig_set/sig_pending/sig_frame` 信号系统, `fds/cwd/elf` 文件系统, `proc_tms` 时间统计

### 2. 内存管理结构体对比

**oskernel2023-avx 的 `struct vma`** (repos\oskernel2023-avx\kernel\include\vma.h):
```c
struct vma {
    enum segtype type;  // NONE, MMAP, STACK
    int perm;
    uint64 addr, sz, end;
    int flags, fd;
    uint64 f_off;
    struct vma *prev, *next;
}
```

**xv6-k210 的 `struct seg`** (repos\xv6-k210\include\mm\usrmm.h):
```c
struct seg {
    enum segtype type;  // NONE, LOAD, TEXT, DATA, BSS, HEAP, MMAP, STACK
    int flag;
    uint64 addr, sz;
    struct seg *next;
    uint64 mmap, f_off, f_sz;
}
```

**【结构体相似证据】**:
- 字段名高度一致：`type`, `addr`, `sz`, `next` (oskernel2023-avx 为 `prev/next` 双向链表)
- 都使用 `enum segtype` 枚举类型，但 xv6-k210 类型更丰富 (8 种 vs 3 种)
- oskernel2023-avx 独有：`perm`, `end`, `fd`
- xv6-k210 独有：`mmap`, `f_sz`

---

## 双维 Jaccard 汇总表

| 函数 | Token Jaccard | CG Jaccard | 备注 |
|------|-------------|------------|------|
| `sys_fork` | 0.643 | 0.000 | xv6-k210 无 sys_fork，fork 是用户态函数 |
| `usertrap` | 0.604 | 0.000 | xv6-k210 无 usertrap 函数名 |
| `scheduler` | 0.465 | 0.500 | 调度核心，有一定相似性 |
| `uvmcopy` | 0.577 | 0.000 | CG 对比失败 |
| `clone` | N/A | 0.070 | Token 对比未执行，CG 差异极大 |
| `handle_page_fault` | N/A | 0.000 | oskernel2023-avx 无此函数 |
| `trap_handler` | N/A | N/A | 两者都未找到 |
| `kalloc`/`alloc_frame` | N/A | N/A | 函数名不匹配 |

**统计计算**:
- **Token Jaccard 均值** = (0.643 + 0.604 + 0.465 + 0.577) / 4 = **0.572**
- **CG Jaccard 均值** = (0.500 + 0.070) / 2 = **0.285** (仅 scheduler 和 clone 有效)
- **综合相似度** = 0.572 × 0.5 + 0.285 × 0.5 = **0.429**

---

## oskernel2023-avx 创新点列表

### 1. 【创新点】多线程支持架构
- **证据**: `struct thread` 独立于 `struct proc`，支持 `thread_clone()` (repos\oskernel2023-avx\kernel\proc.c:1073)
- xv6-k210 仅支持单线程进程模型，无独立线程结构

### 2. 【创新点】VMA 双向链表管理
- **证据**: `struct vma` 含 `prev` 和 `next` 指针 (repos\oskernel2023-avx\kernel\include\vma.h)
- xv6-k210 的 `struct seg` 仅单向链表

### 3. 【创新点】动态栈增长机制
- **证据**: `handle_stack_page_fault()` 实现按需栈扩展 (repos\oskernel2023-avx\kernel\vma.c)
- 使用 `INCREASE_STACK_SIZE_PER_FAULT = 100 * PGSIZE` 增量
- xv6-k210 虽有 `handle_page_fault` 但栈增长逻辑不同

### 4. 【创新点】Futex 支持
- **证据**: `futexClear()` 在 scheduler 中调用 (repos\oskernel2023-avx\kernel\proc.c:669)
- xv6-k210 未发现 futex 相关实现

### 5. 【创新点】简化信号处理
- **证据**: `sighandle()` 直接使用 `SIGTRAMPOLINE` (repos\oskernel2023-avx\kernel\signal.c)
- 相比 xv6-k210 复杂的 `sig_frame` 链表管理更简洁

### 6. 接口/实现分离设计
- **证据**: 大量使用 `include/*.h` 声明接口，实现在 `kernel/*.c`
- 如 `kernel/include/vm.h` 声明 `uvmcopy`，实现在 `kernel/vm.c`

---

## xv6-k210 优势列表

### 1. 更完善的 Copy-on-Write (COW) 机制
- **证据**: `uvmcopy` 中明确使用 `PTE_COW` 标记 (repos\xv6-k210\kernel\mm\vm.c)
- oskernel2023-avx 的 `uvmcopy` 无 COW 逻辑 (Token 独有关键词对比显示)

### 2. 更丰富的段类型支持
- **证据**: `enum segtype` 含 8 种类型 (LOAD, TEXT, DATA, BSS, HEAP, MMAP, STACK)
- oskernel2023-avx 仅 3 种 (NONE, MMAP, STACK)

### 3. 更完善的信号系统
- **证据**: `struct sig_frame` 链表管理，支持信号掩码 (repos\xv6-k210\kernel\sched\signal.c)
- oskernel2023-avx 信号处理较简化

### 4. 多级页面分配器
- **证据**: `_allocpage()` 支持 single/multiple 两级分配 (repos\xv6-k210\kernel\mm\pm.c)
- oskernel2023-avx 的 `kalloc` 是简单空闲链表

### 5. 更完善的调试体系
- **证据**: 大量使用 `__debug_info`, `__debug_warn`, `__debug_assert` 宏
- oskernel2023-avx 主要使用 `printf` 和 `serious_print`

### 6. 文件系统抽象层
- **证据**: `struct fdtable`, `struct inode`, `copyfdtable()` 等完整文件描述符管理
- oskernel2023-avx 使用简化的 `ofile[]` 数组

---

## 总体结论与评分

### 综合相似度分析

| 指标 | 数值 | 说明 |
|------|------|------|
| Token Jaccard 均值 | 0.572 | 中等相似，核心函数有共同逻辑 |
| CG Jaccard 均值 | 0.285 | 差异较大，调用链设计不同 |
| **综合相似度** | **0.429** | 落在 0.30-0.60 区间 |

### 关键发现

1. **代码重合度中等**: Token Jaccard 均值 0.572 表明核心函数（如 `sys_fork`, `usertrap`）有约 57% 的 token 重叠，说明**设计思路相似但实现细节不同**

2. **架构差异显著**: CG Jaccard 均值仅 0.285，反映两项目在函数调用组织、模块划分上有本质区别

3. **数据结构部分相似**: `struct vma`/`struct seg` 字段名高度一致，但 `struct proc`/`struct thread` 设计哲学完全不同

4. **功能覆盖互补**: 
   - oskernel2023-avx 强在多线程、futex
   - xv6-k210 强在 COW、信号系统、调试工具

### 最终评定

**综合相似度 0.429 → 改进版**

**建议评分: 55/100**

**评定等级: 改进版**

**理由**:
- 综合相似度 0.429 落在 0.30-0.60 区间，符合"改进版"定义
- 两项目共享 xv6 基础设计思路（trap 处理、调度框架、内存管理接口）
- 但 oskernel2023-avx 在以下方面进行了实质性改进：
  - 引入独立线程模型支持多线程
  - 简化信号处理机制
  - 实现动态栈增长
  - 添加 futex 同步原语
- 同时缺失了 xv6-k210 的部分高级特性（完善 COW、多级分配器）

**客观依据**:
- 综合相似度: **0.429**
- Token Jaccard 均值: **0.572**
- CG Jaccard 均值: **0.285**