## 数据结构对比

### TaskInner / proc 结构体对比

**oskernel2023-zmz** (`repos/oskernel2023-zmz/include/sched/proc.h:51`):
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
    int killed;
}
```

**oskernrl2022-rv6** (`repos/oskernrl2022-rv6/src/include/proc.h:128`):
```c
struct proc {
    int magic;
    struct spinlock lock;
    enum procstate state;
    struct proc *parent;
    void *chan;
    int killed, xstate, pid, uid, gid;
    uint64 kstack, sz;
    pagetable_t pagetable;
    struct trapframe *trapframe;
    struct context context;
    int64 filelimit;
    struct file **ofile;
    int *exec_close;
    struct dirent *cwd;
    char name[16];
    int tmask;
    struct tms proc_tms;
    struct list dlist;
    struct vma *vma;
    uint64 q;
    map_fix *mf;
    ksigaction_t *sig_act;
    __sigset_t sig_set, sig_pending;
    struct sig_frame *sig_frame;
    uint64 set_child_tid, clear_child_tid;
    struct robust_list_head *robust_list;
}
```

**【结构体相似证据】**:
- 共同核心字段: `pid`, `state`, `parent`, `chan`, `killed`, `xstate`, `kstack`, `pagetable`, `trapframe`, `context`, `proc_tms`, `sig_act`, `sig_set`, `sig_pending`, `sig_frame`, `cwd`
- 字段名和类型高度一致，尤其是进程调度、信号处理相关字段几乎完全相同
- 差异点: oskernel2023-zmz 有 `segment`/`pbrk`/`badaddr` 等内存管理字段，oskernrl2022-rv6 有 `vma`/`sz`/`ofile` 等字段

### MemorySet / 内存管理结构对比

**oskernel2023-zmz**: 使用 `struct seg` 链表管理内存段 (`include/mm/usrmm.h:16`):
```c
struct seg {
    enum segtype type;  // NONE, LOAD, TEXT, DATA, BSS, HEAP, MMAP, STACK
    uint64 addr, sz;
    int flag;
    uint64 mmap;
    struct seg *next;
}
```

**oskernrl2022-rv6**: 使用 `struct vma` 链表 (`src/include/vma.h`):
```c
struct vma {
    enum segtype type;
    int perm;
    uint64 addr, sz, end;
    int flags, fd;
    uint64 f_off;
    struct vma *prev, *next;
}
```

**【结构体相似证据】**: 两者采用几乎相同的 `segtype` 枚举类型和字段设计，表明内存段管理思路高度一致。

---

## 双维 Jaccard 汇总表

| 函数 | Token Jaccard | CG Jaccard | 备注 |
|------|-------------|------------|------|
| handle_page_fault | N/A | N/A | oskernrl2022-rv6 未找到该函数实现 |
| clone (sys_fork) | 0.403 | 0.293 | 进程创建核心函数 |
| scheduler | 0.627 | 0.438 | 调度器核心函数 |
| kerneltrap (trap_handler) | 0.703 | 0.268 | Trap 处理核心 |
| sched | 0.625 | 0.421 | 上下文切换 |
| usertrap | N/A | 0.372 | 用户态 Trap 入口 |
| allocpage | N/A | 0.000 | oskernrl2022-rv6 函数体为空/无法追踪 |

**统计计算**:
- **Token Jaccard 均值** = (0.403 + 0.627 + 0.703 + 0.625) / 4 = **0.5895**
- **CG Jaccard 均值** = (0.293 + 0.438 + 0.268 + 0.421 + 0.372 + 0.000) / 6 = **0.2987**
- **综合相似度** = 0.5895 × 0.5 + 0.2987 × 0.5 = **0.4441**

---

## oskernel2023-zmz 创新点列表

### ✅ 已实现的独特功能

1. **【创新点】Copy-on-Write (COW) 机制**
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:22` 定义 `PTE_COW` 标志
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:961` 实现 `handle_store_page_fault_cow()` 函数
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:564-565` 在 `uvmcopy()` 中激活 COW
   - oskernrl2022-rv6: **未找到**任何 COW 相关实现 (`grep` 搜索无结果)

2. **【创新点】Lazy Allocation (延迟分配)**
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:988` 实现 `handle_page_fault_lazy()` 函数
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:1081` 在 `handle_page_fault()` 中调用 lazy 处理
   - oskernrl2022-rv6: **未找到** lazy 相关实现 (`grep` 搜索无结果)

3. **【创新点】mmap 系统调用完整实现**
   - 证据: `repos/oskernel2023-zmz/include/sysnum.h:72` 定义 `SYS_mmap`
   - 证据: `repos/oskernel2023-zmz/include/mm/mmap.h` 完整的 mmap 头文件
   - 证据: `repos/oskernel2023-zmz/kernel/mm/mmap.c` 实现 `do_mmap()`, `handle_page_fault_mmap()`
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:1019` mmap 页故障处理
   - oskernrl2022-rv6: 仅有文档提及 mmap，**未发现**完整实现代码

4. **【创新点】ELF 懒加载 (Lazy Loading)**
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:1004` 实现 `handle_page_fault_loadelf()`
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:1046` 注释明确说明 "elf-load/lazy-alloc"

5. **【创新点】更完善的页故障处理架构**
   - 证据: `repos/oskernel2023-zmz/kernel/mm/vm.c:1025` `handle_page_fault()` 函数区分 LOAD/HEAP/STACK/MMAP 四种段类型
   - 证据: 支持 COW 页故障、懒加载、mmap 文件映射等多种场景
   - oskernrl2022-rv6: 仅在 `src/include/vm.h:42` 声明函数，**未发现**实现

6. **【创新点】物理内存分配器优化**
   - 证据: `repos/oskernel2023-zmz/kernel/mm/pm.c:232` `_allocpage()` 实现单页/多页分级分配
   - 证据: `__sin_alloc_no_lock()` / `__mul_alloc_no_lock()` 分离单页和多页分配路径
   - oskernrl2022-rv6: `allocpage()` 函数体为空或无法追踪

7. **【创新点】更丰富的 Trap 处理**
   - 证据: `repos/oskernel2023-zmz/kernel/trap/trap.c:287` `handle_intr()` 支持 UART/DISK/PLIC 中断
   - 证据: `repos/oskernel2023-zmz/kernel/trap/trap.c:405` `handle_excp()` 统一异常处理
   - 证据: `repos/oskernel2023-zmz/kernel/trap/trap.c:200` `kerneltrap()` 调用 `handle_excp`/`handle_intr`
   - oskernrl2022-rv6: 使用 `devintr()` 简化处理，功能较少

8. **【创新点】浮点寄存器保存/恢复**
   - 证据: `repos/oskernel2023-zmz/kernel/sched/proc.c:701` `sched()` 中调用 `floatstore()`/`floatload()`
   - 证据: 检查 `SSTATUS_FS_DIRTY` 标志优化性能
   - oskernrl2022-rv6: **未发现**浮点寄存器处理

---

## oskernrl2022-rv6 优势列表

1. **VMA 结构更简洁**
   - 使用 `struct vma` 统一管理内存段，代码组织更清晰
   - 但功能上不如 oskernel2023-zmz 的 COW+Lazy 组合强大

2. **Futex 支持**
   - 证据: `doc/内核实现--Futex.md` 文档描述 Futex 机制
   - 证据: `struct robust_list_head` 字段存在于 proc 结构体
   - oskernel2023-zmz: **未发现** Futex 相关实现

3. **线程创建支持 (CLONE_*)**
   - 证据: `repos/oskernrl2022-rv6/src/proc.c:408` `clone()` 函数支持 `CLONE_THREAD`/`CLONE_VM` 等标志
   - 证据: `set_child_tid`/`clear_child_tid`/`robust_list` 字段支持 POSIX 线程
   - oskernel2023-zmz: 虽有 `clone()` 但**未发现**完整线程标志支持

4. **文件描述符管理更直接**
   - 使用 `struct file **ofile` 数组直接管理
   - oskernel2023-zmz: 使用 `struct fdtable` 封装，但本质相似

---

## 总体结论与评分

### 客观数据汇总

| 指标 | 数值 |
|------|------|
| Token Jaccard 均值 | 0.5895 |
| CG Jaccard 均值 | 0.2987 |
| **综合相似度** | **0.4441** |

### 相似度分析

1. **代码层面 (Token Jaccard = 0.5895)**:
   - `scheduler` (0.627) 和 `kerneltrap` (0.703) 函数体高度相似
   - `sched` (0.625) 上下文切换逻辑几乎相同
   - `clone` (0.403) 中等相似，但 oskernel2023-zmz 增加了更多检查

2. **调用图层面 (CG Jaccard = 0.2987)**:
   - 调用链差异显著，oskernel2023-zmz 调用更多辅助函数
   - `kerneltrap` CG Jaccard 仅 0.268，因为 oskernel2023-zmz 增加了 `handle_excp`/`handle_intr`/`handle_page_fault` 等分层处理
   - `allocpage` CG Jaccard 为 0.000，实现架构完全不同

3. **功能覆盖差异**:
   - oskernel2023-zmz 独有: COW、Lazy Allocation、mmap、ELF 懒加载、浮点寄存器优化
   - oskernrl2022-rv6 独有: Futex、完整线程支持

### 评定结论

**综合相似度 0.44 落在 0.30-0.60 区间** → **改进版**

**最终评定**: **改进版** (建议分 55-65 分)

**理由**:
1. 核心调度器和 Trap 处理函数体高度相似 (Token Jaccard > 0.60)，表明**设计思路同源**
2. 但 oskernel2023-zmz 在内存管理方面有**显著创新**:
   - 完整实现 COW 机制 (31 处代码引用)
   - 完整实现 Lazy Allocation (25 处代码引用)
   - 完整实现 mmap 系统调用 (272 处代码引用)
   - 这些功能在 oskernrl2022-rv6 中**完全缺失**
3. 调用图差异大 (CG Jaccard = 0.2987) 表明 oskernel2023-zmz 增加了大量新功能模块
4. 数据结构字段名高度一致，但 oskernel2023-zmz 扩展了 `segment`/`badaddr`/`pbrk` 等新字段

**最终评分**: **60 分** (改进版中偏高，因为内存管理创新点显著)

**四级评定**: **改进版** (受 oskernrl2022-rv6 启发，但增加了 COW/Lazy/mmap 等重要特性)