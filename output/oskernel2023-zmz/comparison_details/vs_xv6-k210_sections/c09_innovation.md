## 数据结构对比

### 1. `struct proc` (TaskInner 对应结构)

**【结构体相似证据】** 两个项目的 `struct proc` 定义**完全一致**，位于：
- `repos/oskernel2023-zmz/include/sched/proc.h` (行 48-104)
- `repos/xv6-k210/include/sched/proc.h` (行 48-104)

字段完全相同，包括：
- 基本信息：`xstate`, `pid`, `hash_next`, `hash_pprev`
- 调度链表：`sched_next`, `sched_pprev`, `timer`, `state`, `chan`, `sleep_expire`
- 性能计时：`proc_tms`, `ikstmp`, `okstmp`, `vswtch`, `ivswtch`
- 父子关系：`lk`, `child`, `parent`, `sibling_next`, `sibling_pprev`
- 内存管理：`kstack`, `badaddr`, `pagetable`, `trapframe`, `segment`, `pbrk`
- 文件系统：`fds`, `cwd`, `elf`
- 调度上下文：`context`
- 信号处理：`sig_act`, `sig_set`, `sig_pending`, `sig_frame`, `killed`
- 调试信息：`name[16]`, `tmask`

### 2. `struct seg` (MemorySet 对应结构)

**【结构体相似证据】** 两个项目的 `struct seg` 定义**完全一致**，位于：
- `repos/oskernel2023-zmz/include/mm/usrmm.h` (行 10-18)
- `repos/xv6-k210/include/mm/usrmm.h` (行 10-18)

```c
struct seg{
    enum segtype type;  // NONE, LOAD, TEXT, DATA, BSS, HEAP, MMAP, STACK
    int flag;
    uint64 addr;
    uint64 sz;
    struct seg *next;
    uint64 mmap;
    uint64 f_off;
    uint64 f_sz;
};
```

### 3. PageTable 相关

两个项目均使用 RISC-V 标准的 `pagetable_t` 类型（定义为 `uint64*`），未定义独立的 `PageTable` 结构体，而是通过 `struct seg` 链表管理用户内存区域。

---

## 双维 Jaccard 汇总表

| 函数 | Token Jaccard | CG Jaccard | 说明 |
|------|-------------|------------|------|
| `handle_page_fault` | 1.000 | 1.000 | 完全相同，65 tokens 完全一致，调用图30节点完全重合 |
| `sys_fork` | 1.000 | 0.968 | Token 完全相同；CG 中 oskernel2023-zmz 独有 `floatstore` 调用 |
| `sched` | 0.750 | 0.600 | Token 差异：oskernel2023-zmz 有完整锁检查逻辑，xv6-k210 已注释掉；CG 差异显著 |
| `usertrap` | 0.963 | 0.875 | Token 高度相似；oskernel2023-zmz 独有 `idlepages`, `trapframedump` 调试功能 |
| `_allocpage` | 1.000 | 1.000 | 完全相同，39 tokens 完全一致，调用图4节点完全重合 |

**统计计算：**
- **Token Jaccard 均值** = (1.000 + 1.000 + 0.750 + 0.963 + 1.000) / 5 = **0.9426**
- **CG Jaccard 均值** = (1.000 + 0.968 + 0.600 + 0.875 + 1.000) / 5 = **0.8886**
- **综合相似度** = 0.9426 × 0.5 + 0.8886 × 0.5 = **0.9156**

---

## oskernel2023-zmz 创新点列表

经详细代码审查，**oskernel2023-zmz 相对于 xv6-k210 未发现显著的独特技术创新**。两个项目在核心功能实现上高度一致。但 oskernel2023-zmz 在以下方面有**增强实现**（非创新，而是更完整的实现）：

1. **更完整的调度锁检查** (`kernel/sched/proc.c:701-714`)
   - oskernel2023-zmz 保留了完整的 `holding(&proc_lock)`, `noff` 检查，`RUNNING` 状态检查，`intr_get()` 中断检查
   - xv6-k210 将这些安全检查全部注释掉（行 716-723）
   - 证据：`repos/oskernel2023-zmz/kernel/sched/proc.c:707-713` vs `repos/xv6-k210/kernel/sched/proc.c:716-723`

2. **更活跃的调试功能** (`kernel/trap/trap.c`)
   - oskernel2023-zmz 在 `usertrap` 中启用 `trapframedump()` 和 `idlepages()` 打印（行 129-130）
   - xv6-k210 将这些调试输出注释掉（行 124-125）
   - 证据：`repos/oskernel2023-zmz/kernel/trap/trap.c:129-130` vs `repos/xv6-k210/kernel/trap/trap.c:124-125`

3. **直接的浮点寄存器保存/恢复调用**
   - oskernel2023-zmz 直接调用 `floatstore(p->trapframe)` 和 `floatload(p->trapframe)`
   - xv6-k210 使用函数指针转换 `((floattrap)floatstore)(p->trapframe)`
   - 这可能反映两种不同的实现策略，但功能等价

**注意**：以下特性在两个项目中**均存在**，不属于 oskernel2023-zmz 独有：
- COW (Copy-on-Write) fork 机制：两项目均有 `PTE_COW` 标记和 `handle_store_page_fault_cow`
- Lazy 分配：两项目均有 `handle_page_fault_lazy`
- MMAP 支持：两项目均有 `include/mm/mmap.h` 和 `SYS_mmap` 系统调用
- 信号处理：两项目均有 `sigaction`, `sighandle`, `SIG_TRAMPOLINE`
- 系统调用追踪：两项目均有 `tmask` 和 `SYS_trace`

---

## xv6-k210 优势列表

经详细代码审查，**xv6-k210 相对于 oskernel2023-zmz 未发现显著的独特技术优势**。唯一观察到的差异：

1. **usertrap 中的 syncfs 调用** (`kernel/trap/trap.c:129`)
   - xv6-k210 在特定条件下调用 `syncfs()` 同步文件系统
   - oskernel2023-zmz 未在此处调用 `syncfs`
   - 证据：`repos/xv6-k210/kernel/trap/trap.c:129` 存在 `syncfs();`，而 oskernel2023-zmz 对应位置无此调用
   - **注意**：两项目均有 `syncfs()` 函数定义，但调用位置不同

2. **注释掉的调试代码**
   - xv6-k210 倾向于将调试代码注释掉（如 `trapframedump`, `idlepages` 打印，`sched` 锁检查）
   - 这可能反映 xv6-k210 是更"生产就绪"的版本，而 oskernel2023-zmz 保留更多调试功能用于开发

---

## 总体结论与评分

### 客观数据汇总
| 指标 | 数值 |
|------|------|
| Token Jaccard 均值 | 0.9426 |
| CG Jaccard 均值 | 0.8886 |
| **综合相似度** | **0.9156** |

### 评定等级：**高度相似**

**依据**：
1. 综合相似度 0.9156 ≥ 0.60，落入"高度相似"区间
2. 核心数据结构 `struct proc` 和 `struct seg` 字段定义**完全一致**
3. 5个核心函数中，3个 Token Jaccard = 1.000（`handle_page_fault`, `sys_fork`, `_allocpage`）
4. Call Graph 分析显示调用链高度重合，差异主要在调试功能和锁检查的启用/禁用

### 建议评分：**88/100**

**评分理由**：
- 基础分 75 分（高度相似区间下限）
- +10 分：Token Jaccard 均值高达 0.94，代码层面几乎完全一致
- +3 分：oskernel2023-zmz 保留了更完整的调度锁检查逻辑，安全性略优
- -0 分：未发现实质性创新点，但代码质量与 xv6-k210 相当

### 最终评定：**高度相似**

**结论陈述**：
oskernel2023-zmz 与 xv6-k210 在代码层面呈现**极高的相似性**（综合相似度 0.9156）。两个项目共享：
- 完全相同的进程控制块 (`struct proc`) 和内存段 (`struct seg`) 数据结构
- 完全相同的页面故障处理、fork 系统调用、页面分配器实现
- 相同的 COW、Lazy 分配、MMAP、信号处理等高级特性

主要差异仅在于：
1. `sched()` 函数中锁检查逻辑的启用/禁用
2. 调试功能（`trapframedump`, `idlepages` 打印）的启用/禁用
3. `floatstore/floatload` 的调用方式（直接调用 vs 函数指针）

这些差异属于**配置级别**或**调试策略**的不同，而非架构或算法层面的创新。因此，oskernel2023-zmz 应被评定为 xv6-k210 的**高度相似实现**，而非独立开发或受启发项目。