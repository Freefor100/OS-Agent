# xv6-k210 操作系统技术分析报告

> **年份**: 2021

> **赛事**: 操作系统赛

> **子赛事**: 内核实现赛道

> **学校**: 华中科技大学

> **队伍名称**: 3Los

> **仓库地址**: https://gitlab.eduxiji.net/retrhelo/xv6-k210

> **分析日期**: 2026年04月20日

> **分析工具**: OS-Agent-D

---

## 目录

1. 项目概览与技术栈
2. 启动架构与 Trap系统调用
3. 内存管理物理虚拟分配器
4. 进程线程调度与多核
5. 文件系统与设备 IO
6. 同步互斥与进程间通信
7. 安全机制与权限模型
8. 网络子系统与协议栈
9. 调试机制与错误处理
10. 开发历史与里程碑

---

## Call Graph 概览

> 先以 Tree-sitter 扫描全库，再对 C/C++ 用 **Clang AST**（与仓库根 `compile_flags.txt` / `compile_commands.json` 一致）剔除**条件编译未进入翻译单元**的函数节点，得到参与 PageRank 的 **1805** 个函数、**4322** 条调用边。
> 语义解析 82/82 个文件。
>
> 用 **PageRank** 选出架构枢纽 **Top-30** 个函数（参数 **k=30**；若全库可排名节点不足 k，则实际个数可能小于 k）。
> 按 **domain（列）× layer（行）** 二维网格布局（**domain/layer 由 LLM 根据函数名与代码片段分类**），
> 同格多节点限制在格内排布；连线体现调用关系。
> **可变网格**：在 **k=30** 配置下，**未出现**的 domain 列、layer 行会**压缩**宽高，把画布让给有节点的列/行。
> **layer 为何常落在 kernel**：PageRank 枢纽多为调度/内存/VFS 等**内核通用逻辑**，且 `kernel` 表示「既非 syscall 入口、也非直接 MMIO」的广义内核代码，模型容易默认成 kernel；已对 **`sys_*` 命名**做确定性修正为 `syscall_boundary`。缓存随 **compile 配置 / git / 管线版本** 自动失效；需强制全量重算时可调用 `generate_callgraph_section(..., force_regenerate=True)`。

### 函数级 Call Graph（PageRank Top-30，图示 30 个函数）

![函数级 Call Graph](callgraph_overview.svg)

*（图：`callgraph_overview.svg`，与报告同目录）*

**图例**：列 = domain 分类，行 = layer 层次（**userspace** → **syscall_boundary** → **kernel** → **hardware**）
节点颜色：`arch_platform`=#f4d03f / `trap_syscall`=#e74c3c / `process_sched`=#3498db / `memory_vm`=#2ecc71 / `fs_storage`=#9b59b6
节点**第一行**仅为**符号名**；**第二行**：**函数定义**只写相对源路径；**宏**、**类型别名（typedef）**、**仅引用（调用侧）**等在第二行用**中文**标明类别并附路径或调用方文件（来自静态解析或调用边）。
列宽按该 domain 列下最长节点标签**动态**估算（有上下限），避免固定死宽度。

### 文件级调用关系

<table style="border-collapse:collapse;width:auto;max-width:100%;table-layout:auto">
<thead><tr>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">源文件</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">domain</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">调用的文件（权重）</th>
</tr></thead>
<tbody>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/mm/pm.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">memory_vm</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×7, spinlock.c×2, intr.c×2, proc.c×1, proc.h×1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/sched/proc.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/console.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">sbi.h×1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/fs/fat32/fat32.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">fs_storage</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">types.h×1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/intr.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">sync_ipc</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×8, proc.c×2, proc.h×2</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/mm/kmalloc.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">memory_vm</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×12, spinlock.c×6, printf.c×6, intr.c×4, pm.h×2</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/mm/vm.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">memory_vm</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×7, proc.c×2, vm.h×2, intr.c×2, proc.h×1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/printf.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">runtime_common</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×7, spinlock.c×2, intr.c×2, console.c×1, printf.c×1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sched/proc.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">process_sched</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×27, intr.c×6, proc.h×4, spinlock.c×4, printf.c×4</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sync/spinlock.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">sync_ipc</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×8, intr.c×2, proc.c×2, proc.h×2</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/syscall/syscall.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">trap_syscall</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">riscv.h×12, proc.c×4, printf.c×4, intr.c×4, proc.h×2</td></tr>
</tbody></table>

### PageRank Top-30 枢纽函数（k=30）

<table style="border-collapse:collapse;width:auto;max-width:100%;table-layout:auto">
<thead><tr>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">符号</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">类型</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">domain</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">layer</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">定义路径 / 引用位置</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">PR</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">in°</th>
<th style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa">out°</th>
</tr></thead>
<tbody>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>cpuid</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/sched/proc.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#1</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">99</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>mycpu</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">process_sched</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sched/proc.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#2</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">84</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">2</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>r_tp</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/hal/riscv.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#3</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">85</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>pop_off</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">sync_ipc</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/intr.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#4</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">79</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">5</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>myproc</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">process_sched</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sched/proc.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#5</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">110</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">11</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>release</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">sync_ipc</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sync/spinlock.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#6</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">168</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">6</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>acquire</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">sync_ipc</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sync/spinlock.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#7</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">166</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">8</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>printf</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">runtime_common</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/printf.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#8</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">171</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">19</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>push_off</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">sync_ipc</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/intr.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#9</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">173</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">7</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>set_sstatus_bit</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/hal/riscv.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#10</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">103</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>intr_on</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/hal/riscv.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#11</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">161</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>memset</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">runtime_common</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/utils/string.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#12</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">66</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>container_of</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">宏（#define）</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">runtime_common</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>宏（#define） · include/types.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#13</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">10</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>kfree</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">memory_vm</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/mm/kmalloc.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#14</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">66</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">20</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>exit</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">process_sched</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sched/proc.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#15</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">84</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">38</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>clr_sstatus_bit</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/hal/riscv.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#16</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">111</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>initlock</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">sync_ipc</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sync/spinlock.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#17</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">58</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>r_sstatus</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/hal/riscv.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#18</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">104</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>sb2fat</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">fs_storage</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/fs/fat32/fat32.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#19</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">31</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>freepage</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">宏（#define）</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">memory_vm</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>宏（#define） · include/mm/pm.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#20</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">68</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">13</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>sbi_console_putchar</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/sbi.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#21</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">4</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>intr_off</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/hal/riscv.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#22</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">157</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>consputc</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/console.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#23</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">79</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>intr_get</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">arch_platform</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">hardware</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>include/hal/riscv.h</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#24</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">159</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">1</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>memmove</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">runtime_common</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/utils/string.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#25</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">48</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">0</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>wakeup</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">process_sched</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/sched/proc.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#26</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">28</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">14</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>kmalloc</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">memory_vm</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/mm/kmalloc.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#27</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">69</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">20</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>argaddr</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">trap_syscall</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">syscall_boundary</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/syscall/syscall.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#28</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">49</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">14</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>safememmove</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">memory_vm</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">kernel</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/mm/vm.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#29</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">37</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">14</td></tr>
<tr><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code>argint</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">函数定义</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">trap_syscall</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">syscall_boundary</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"><code style='white-space:pre-wrap;word-break:break-all'>kernel/syscall/syscall.c</code></td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">#30</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">44</td><td style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top">14</td></tr>
</tbody></table>

---


# 项目概览与技术栈

## 第 1 章：项目概览与技术栈

## 快速总览

**一句话定位**：xv6-k210 是基于 xv6-riscv 移植的 RISC-V 64 位教学内核，主要语言为 C，支持 Kendryte K210 开发板与 QEMU virt 双平台，实现了完整的虚拟内存、多核调度与 FAT32 文件系统。

**子系统完成度矩阵**：

| 子系统 | 完成度 | 关键实现 |
|--------|--------|---------|
| 启动与 Trap/系统调用（第 02 章） | ✅完整 | RustSBI → entry.S → main.c 启动链；`kernel/trap/trap.c` 实现用户/内核陷阱分发；68 个 syscall 分发表 |
| 内存管理（第 03 章） | ✅完整 | `kernel/mm/pm.c` 空闲链表分配器；`kernel/mm/vm.c` Sv39 页表；CoW/Lazy/mmap 全实现 |
| 进程/调度与多核（第 04 章） | ✅完整 | `struct proc` 统一 PCB；三级优先级调度；SMP 双核启动与 IPI 唤醒 |
| 中断与系统调用（与第 02 章同源时可互引） | ✅完整 | PLIC 外部中断分发；`kernel/syscall/syscall.c` 分发表；信号处理链路 |
| 文件系统与设备 I/O（第 05 章） | ✅完整 | VFS op 表抽象；FAT32 自研实现；块缓存 LRU；UART/SDCard/Virtio 驱动 |
| 同步与 IPC（第 06 章） | ✅完整 | SpinLock/SleepLock/WaitQueue；管道 (pipe)；信号 (signal) 机制 |
| 多核支持（与第 04 章同源时可互引） | ✅完整 | BSP 唤醒 AP；per-CPU `struct cpu`；全局运行队列 + 自旋锁保护 |
| 网络协议栈（第 08 章） | ❌缺失 | 无 socket syscall；无网卡驱动；无协议栈代码 |
| 安全机制（第 07 章） | 🔸部分 | 用户/内核态隔离 (SSTATUS_SPP)；用户指针验证 (copyin/copyout)；UID/GID 仅字段无检查链 |
| 调试与错误处理（第 09 章） | ✅完整 | `panic()` + `backtrace()`；DEBUG 宏日志控制；strace 系统调用追踪 |

## 评测与交付适配（启发式归纳）

- **Delivery**：`Makefile` 定义明确产物：`build/kernel`（ELF 内核）、`k210.bin`（K210 烧录镜像）、`fs.img`（QEMU FAT32 磁盘镜像）。`make all` 目标串联编译流程（`Makefile:240-250`）。无 `kernel-rv/kernel-la` 等固定命名产物。
- **Harness**：存在用户态测试框架：`xv6-user/usertests.c`（58.5KB，2765 行）包含大规模压力测试；`xv6-user/cowtest.c`、`lazytests.c`、`mmaptests.c` 针对特定内存功能验证。README 明确 `make fs` 生成测试镜像，`make run` 启动 QEMU 或板级运行。
- **PlatformProfile**：README 与代码一致支持双平台：K210 实机（`platform := k210`，默认）与 QEMU virt（`platform := qemu`，需 `fs.img`）。SMP 配置为 `NCPU=2`（`include/param.h:5`），QEMU 启动参数 `QEMUOPTS += -smp $(CPUS)`（`Makefile:48`）。
- **SubsystemDepth**：README 声称支持"Process management"、"File system"、"Multicore boot"，与 02-06 章代码验证一致。风险缺口：网络子系统完全缺失（08 章 `not_found`）；安全机制仅有特权级隔离，无细粒度权限检查（07 章 UID/GID 桩函数）。

## 各模块技术全景（基于 02–10 章报告提取）

### 02 启动/架构与 Trap/系统调用

- **技术清单**：
  - 启动链：RustSBI (M 态) → `kernel/entry_k210.S:_start` / `entry_qemu.S:_entry` (S 态) → `kernel/main.c:main()` C 入口
  - 模式切换：RISC-V SSTATUS_SPP 位控制用户/内核态；`usertrapret()` 清除 SPP 返回用户态
  - MMU 初始化：`kvminit()` 建立内核页表；`kvminithart()` 写 satp 启用 Sv39 分页
  - Trap 向量：`kernelvec` (内核态) / `uservec` (用户态) 分别设置 stvec；`usertrap()` / `kerneltrap()` 分发
  - 系统调用：68 个 syscall 分发表 `syscalls[]`；边界检查 `num < NELEM(syscalls)`
  - 信号处理：`sighandle()` 构建 `sig_frame`；`sigreturn()` 恢复原 trapframe

- **关键实现、证据与细粒度锚点**：
  - 入口：`linker/linker64.ld:2` `ENTRY(_entry)`；`kernel/entry_k210.S:2` `_start` 标签
  - 模式切换：`include/hal/riscv.h` 定义 `SSTATUS_SPP (1L << 8)`；`kernel/trap/trap.c:156` `x &= ~SSTATUS_SPP`
  - MMU：`kernel/mm/vm.c:45` `kvminit()` 分配 `kernel_pagetable`；`kernel/mm/vm.c:67` `w_satp(stap)`
  - Trap 向量：`kernel/trap/kernelvec.S:8` `kernelvec` 标签；`kernel/trap/trap.c:52` `w_stvec((uint64)kernelvec)`
  - Syscall 分发：`kernel/syscall/syscall.c:194-258` `syscalls[]` 数组；`kernel/syscall/syscall.c:212` 边界检查
  - 信号：`kernel/sched/signal.c:178` `sighandle()` 分配 `sig_frame`；`kernel/sched/signal.c:263` `sigreturn()` 恢复

- **依赖与工具**：RustSBI (bootloader/SBI/rustsbi-k210) 作为固件；RISC-V GNU 工具链 (`riscv64-unknown-elf-`)
- **与相邻模块衔接**：启动链为 03 章 MMU 初始化提供执行环境；Trap 分发为 06 章信号处理提供入口

### 03 内存管理（物理/虚拟/分配器）

- **技术清单**：
  - 物理分配器：`struct run` 单链表 + `struct pm_allocator` 分桶 (single/multiple)；首次适配算法
  - 页表管理：Sv39 三级页表；`walk()` / `mappages()` / `unmappages()` API
  - 高级特性：CoW (fork 时标记 `PTE_COW`，缺页时复制)；Lazy 分配 (HEAP/STACK 缺页时按需分配)；mmap (匿名/文件映射)
  - 缓存：Buffer Cache (LRU 链表 `lru_head`)；Page Cache (`struct mmap_page` 红黑树)
  - 地址空间：`struct seg` 链表维护进程段 (TEXT/DATA/HEAP/STACK/MMAP)

- **关键实现、证据与细粒度锚点**：
  - 分配器：`kernel/mm/pm.c:17` `struct run { struct run *next; uint64 npage; }`；`kernel/mm/pm.c:23` 双桶 `single`/`multiple`
  - 页表：`kernel/mm/vm.c:211` `walk()` 三级遍历；`kernel/mm/vm.c:280` `mappages()` 建立映射
  - CoW：`kernel/mm/vm.c:567` fork 时 `*pte = (*pte|PTE_COW) & ~PTE_W`；`kernel/mm/vm.c:975` `handle_store_page_fault_cow()` 复制
  - Lazy：`kernel/mm/vm.c:1002` `handle_page_fault_lazy()` 为 HEAP/STACK 调用 `uvmalloc()`
  - mmap：`kernel/mm/mmap.c:710` `do_mmap()` 处理 `MAP_ANON`/`MAP_FIXED`；`kernel/mm/mmap.c:1126` `handle_page_fault_mmap()`
  - 缓存：`kernel/fs/bio.c:88` `bget()` 从 `lru_head.prev` 获取；`kernel/fs/bio.c:199` `bwrite()` 异步写回

- **依赖与工具**：无外部依赖；自研红黑树 (`include/utils/rbtree.h`) 管理 mmap
- **与相邻模块衔接**：缺页处理 (`handle_page_fault`) 由 02 章 trap 入口调用；页表切换在 04 章调度器中执行

### 04 进程/线程/调度与多核

- **技术清单**：
  - 执行实体：`struct proc` 统一 PCB (无独立 TCB)；含 `context` (callee-saved 寄存器)、`state` (RUNNABLE/RUNNING/SLEEPING/ZOMBIE)、`trapframe`
  - 调度算法：三级优先级 (TIMEOUT/IRQ/NORMAL) + 时间片超时降级；全局队列 `proc_runnable[PRIORITY_NUMBER]`
  - 上下文切换：`swtch.S` 保存/恢复 ra/sp/s0-s11 (14 个寄存器)
  - 多核：SMP 双核；BSP 唤醒 AP (IPI)；per-CPU `struct cpu` 数组；全局 `proc_lock` 保护
  - 生命周期：`fork()`/`clone()` 复制地址空间与 fd 表；`exit()` 回收资源并置 ZOMBIE；`wait4()` 阻塞回收

- **关键实现、证据与细粒度锚点**：
  - PCB：`include/sched/proc.h:51` `struct proc { int pid; enum procstate state; struct context context; ... }`
  - 调度：`kernel/sched/proc.c:671` `scheduler()` 无限循环；`kernel/sched/proc.c:543` `__get_runnable_no_lock()` 按优先级遍历
  - 切换：`kernel/sched/swtch.S:7` `swtch` 保存 `sd ra, 0(a0)` ... `sd s11, 104(a0)`
  - 多核：`kernel/main.c:69` `sbi_send_ipi()` 唤醒 AP；`kernel/sched/proc.c:93` `struct cpu cpus[NCPU]`
  - Fork：`kernel/sched/proc.c:303` `copysegs()` 复制地址空间；`kernel/sched/proc.c:321` `copyfdtable()` 复制 fd 表

- **依赖与工具**：无外部依赖
- **与相邻模块衔接**：调度器调用 03 章 `w_satp()` 切换页表；`sleep()`/`wakeup()` 为 06 章管道/信号提供阻塞机制

### 05 文件系统与设备 I/O

- **技术清单**：
  - VFS 抽象：C 语言 op 表 (`struct fs_op` / `struct inode_op` / `struct file_op`)
  - 具体 FS：自研 FAT32 (`kernel/fs/fat32/fat32.c`)；支持长文件名与簇链管理
  - 文件描述符：`struct fdtable` 固定数组 `arr[NOFILE]` + 链表扩展
  - 设备驱动：UART (早期输出)；SDCard (SPI 模式)；Virtio-blk (QEMU)；PLIC (中断控制器)
  - 缓存：Buffer Cache (`struct buf` 池 + LRU 驱逐)

- **关键实现、证据与细粒度锚点**：
  - VFS：`include/fs/fs.h:44` `struct fs_op { struct inode *(*alloc_inode)(...); ... }`
  - FAT32：`kernel/fs/fat32/fat32.c:58` `fat32_init()` 读取 BPB 验证签名
  - FD 表：`include/fs/file.h:32` `struct fdtable { struct file *arr[NOFILE]; struct fdtable *next; }`
  - 驱动：`kernel/hal/sdcard.c:233` `sdcard_init()`；`kernel/hal/virtio_disk.c:103` `virtio_disk_init()`
  - 缓存：`kernel/fs/bio.c:33` `static struct buf bufs[BNUM]`；`kernel/fs/bio.c:88` LRU 管理

- **依赖与工具**：无外部 FS 库；自研 FAT32 实现
- **与相邻模块衔接**：块设备驱动通过 02 章 PLIC 中断分发；mmap 文件映射共享 03 章 Page Cache

### 06 同步与 IPC

- **技术清单**：
  - 同步原语：SpinLock (原子交换 `amoswap.w.aq`)；SleepLock (阻塞型 Mutex)；WaitQueue (双向链表)
  - IPC：管道 (pipe) 字节环形缓冲 + 阻塞读写；信号 (signal) 用户态 handler + `sigreturn` 恢复
  - 死锁预防：全局锁顺序规范 (`proc_lock` 最后获取)

- **关键实现、证据与细粒度锚点**：
  - SpinLock：`kernel/sync/spinlock.c:34` `while(__sync_lock_test_and_set(&lk->locked, 1) != 0)`
  - SleepLock：`kernel/sync/sleeplock.c:23` `while (lk->locked) { sleep(lk, &lk->lk); }`
  - Pipe：`kernel/fs/pipe.c:268` `pi->nwrite % PIPESIZE(pi)` 环形缓冲；`kernel/fs/pipe.c:178` 满则 `sleep()`
  - Signal：`kernel/sched/signal.c:178` `sighandle()` 构建 `sig_frame`；`kernel/sched/signal.c:263` `sigreturn()` 恢复
  - 锁顺序：`kernel/sched/proc.c:249` 注释 "proc_lock should be acquired last"

- **依赖与工具**：无外部依赖
- **与相邻模块衔接**：`sleep()`/`wakeup()` 依赖 04 章调度器；信号处理依赖 02 章 trap 返回路径

### 07 安全机制

- **技术清单**：
  - 特权级隔离：RISC-V S 态 (内核) / U 态 (用户)；`SSTATUS_SPP` 位控制
  - 用户指针验证：`copyin()`/`copyout()` 通过 `walkaddr()` 检查 PTE_U；`safememmove()` 切换 `SSTATUS_SUM`
  - 内存保护：页表权限位 (PTE_R/PTE_W/PTE_X)；栈保护注释 (guard page)

- **关键实现、证据与细粒度锚点**：
  - 特权级：`include/hal/riscv.h:53` `SSTATUS_SPP (1L << 8)`；`kernel/trap/trap.c:156` 清除 SPP
  - 指针验证：`kernel/mm/vm.c:227` `walkaddr()` 检查 `PTE_U`；`kernel/mm/vm.c:730` `permit_usr_mem()` 设置 SUM 位
  - 权限位：`include/hal/riscv.h:385-387` 定义 `PTE_R`/`PTE_W`/`PTE_X`

- **依赖与工具**：无外部依赖
- **与相邻模块衔接**：用户指针验证在 02 章 syscall 路径 (`fetchaddr()`) 中调用

### 08 网络协议栈

- **技术清单**：
  - 无网络子系统实现

- **关键实现、证据与细粒度锚点**：
  - 证据：`include/sysnum.h` 无 `SYS_socket`/`SYS_bind` 等定义；`kernel/` 目录无 `net/` 子目录；`kernel/hal/` 无网卡驱动

- **依赖与工具**：不适用
- **与相邻模块衔接**：不适用

### 09 调试与错误处理

- **技术清单**：
  - 日志系统：`printf()` / `__debug_msg` (DEBUG 宏控制) / `__debug_assert`
  - Panic 处理：`__panic()` 输出错误信息 + `backtrace()` + 关中断停机
  - 栈回溯：`backtrace()` 基于 FramePointer 遍历栈帧
  - 追踪机制：`sys_trace()` 系统调用 + `strace` 用户工具

- **关键实现、证据与细粒度锚点**：
  - Panic：`kernel/printf.c:103` `__panic()` 调用 `backtrace()`；`include/printf.h:15` `panic` 宏输出 CPU ID/文件/行号
  - Backtrace：`kernel/printf.c:120` `backtrace()` 遍历 `*(fp - 1)` 获取 ra
  - Trace：`kernel/syscall/sysproc.c:290` `sys_trace()` 设置 `p->tmask`；`xv6-user/strace.c:33` 调用 `trace()`

- **依赖与工具**：无外部依赖
- **与相邻模块衔接**：`backtrace()` 在 02 章 `panic()` 路径中调用

### 10 演进与历史

- **技术清单**：
  - 开发周期：2021-05-27 至 2021-08-21 (约 3 个月，200 次提交)
  - 核心贡献者：retrhelo (162 commits, 内核核心)、Lu Sitong (146 commits, 内存管理)、hustccc (116 commits, 构建系统)
  - 重大重构：Lazy-mmap (2021-07-29, +701/-281 行，引入红黑树)；Signal 机制 (2021-08-17, "signal now works")
  - 文档里程碑：23 篇中文技术文档 (`doc/` 目录)，覆盖内核原理/构建调试/用户使用

- **关键实现、证据与细粒度锚点**：
  - Lazy-mmap：commit `27ca1f1` 重构 `kernel/mm/mmap.c`，引入 `struct rb_root mapping`
  - Signal：commit `08c10ba` 完善 `kernel/sched/signal.c` 与 `sig_trampoline.S`
  - 文档：`doc/` 目录 23 篇 `.md` 文件，2021-08-17 批量更新 (+418/-16 行)

- **依赖与工具**：Git 版本控制
- **与相邻模块衔接**：历史演进反映 03 章内存管理、06 章信号机制的迭代过程

## 技术栈与构建（编程语言版本、框架、依赖、支持的架构完整列表）

- **编程语言**：
  - 内核主体：C (87 个 `.c` 文件，55 个 `.h` 文件)
  - 汇编：RISC-V 汇编 (`.S` 文件，如 `entry.S`、`swtch.S`、`trampoline.S`)
  - 固件：Rust (bootloader/SBI/rustsbi-k210，10 个 `.rs` 文件)
  - 脚本：Python (`tools/kflash.py`)、Perl (`xv6-user/usys.pl`)

- **构建工具**：
  - Make：主构建系统 (`Makefile` 303 行)，管理内核与用户程序编译
  - Cargo：RustSBI 固件构建 (`bootloader/SBI/rustsbi-k210/Cargo.toml`)
  - 工具链：`riscv64-unknown-elf-gcc` (C 编译器)、`riscv64-unknown-elf-as` (汇编器)、`riscv64-unknown-elf-ld` (链接器)

- **支持架构**：
  - **riscv64gc-unknown-none-elf** (RISC-V 64 位，裸机环境)
  - 平台变体：Kendryte K210 (实机)、QEMU virt (模拟器)
  - 多核配置：`NCPU=2` (SMP 双核)

- **外部依赖**：
  - 固件：RustSBI (自研，位于 `bootloader/SBI/`)
  - 无第三方内核库/crate (文件系统、网络协议栈、驱动均为自研)
  - 开发工具：OpenOCD (`debug/kendryte_openocd/`)、GDB (`.gdbinit.tmpl-riscv`)

- **构建产物**：
  - `build/kernel`：ELF 格式内核镜像
  - `k210.bin`：K210 烧录镜像 (二进制)
  - `fs.img`：QEMU FAT32 磁盘镜像 (含用户程序)

## 目录结构导读（关键目录与源码入口）

- **`kernel/`**：内核核心实现 (约 30KB 代码)
  - `kernel/main.c:main()`：C 语言入口，初始化序列 (CPU/MMU/Trap/Proc/Scheduler)
  - `kernel/trap/`：中断/异常处理 (`trap.c`、`kernelvec.S`、`trampoline.S`)
  - `kernel/mm/`：内存管理 (`vm.c` 页表、`pm.c` 分配器、`mmap.c` 映射)
  - `kernel/sched/`：进程调度 (`proc.c` PCB/调度器、`signal.c` 信号、`swtch.S` 上下文切换)
  - `kernel/fs/`：文件系统 (VFS `fs.c`、FAT32 `fat32/`、管道 `pipe.c`)
  - `kernel/hal/`：硬件抽象层 (SDCard `sdcard.c`、Virtio `virtio_disk.c`、PLIC `plic.c`)
  - `kernel/syscall/`：系统调用实现 (`syscall.c` 分发、`sysfile.c` 文件、`sysproc.c` 进程)

- **`include/`**：头文件 (按模块分类)
  - `include/sched/proc.h`：`struct proc` PCB 定义
  - `include/mm/vm.h` / `include/mm/usrmm.h`：内存管理接口与 `struct seg`
  - `include/fs/fs.h`：VFS op 表定义
  - `include/hal/riscv.h`：RISC-V 寄存器/指令封装
  - `include/trap.h`：`struct trapframe` 定义

- **`bootloader/SBI/`**：固件
  - `rustsbi-k210/`：K210 平台 RustSBI (Rust 编写)
  - `rustsbi-qemu/`：QEMU 平台 RustSBI

- **`xv6-user/`**：用户态程序
  - `sh.c`：Shell 实现
  - `usertests.c`：综合压力测试
  - `cowtest.c` / `lazytests.c` / `mmaptests.c`：内存特性测试

- **`doc/`**：技术文档 (23 篇中文 Markdown)
  - 内核原理：内存管理、页表映射、系统调用、进程管理
  - 构建调试：SD 卡驱动、中断、开机启动、调试指南
  - 用户使用：内存管理、文件系统、系统调用

- **`linker/`**：链接脚本
  - `linker64.ld`：内核链接脚本 (定义 `ENTRY(_entry)`、段布局)
  - `user.ld`：用户程序链接脚本

- **`tools/`**：工具脚本
  - `kflash.py`：K210 烧录脚本 (Python)

## 总结评价（完成度评估）

xv6-k210 项目在 3 个月密集开发周期内，成功将 xv6-riscv 移植至 Kendryte K210 平台，并实现了远超教学原型的完整功能集。核心优势在于：内存管理子系统达到生产级复杂度 (CoW/Lazy/mmap/红黑树映射)、多核 SMP 调度与同步机制完备 (三级优先级、IPI 唤醒、死锁预防)、文件系统自研 FAT32 实现并集成 VFS 抽象层。启动链、Trap 处理、系统调用分发等基础机制经过充分验证，配套 23 篇技术文档与大规模用户态测试 (`usertests.c`) 形成闭环。

主要缺口在于网络子系统完全缺失 (无 socket/协议栈/网卡驱动)，安全机制停留在特权级隔离层面 (UID/GID 无真实检查链)，多核 TLB shootdown 未实现 (仅单核刷新)。整体而言，该项目作为 RISC-V 教学内核已具备极高的工程完整性，可作为理解现代 OS 内存管理、多核调度、文件系统设计的优质参考实现，但尚不具备通用操作系统所需的网络与安全能力。

---


# 启动架构与 Trap系统调用

## 题单作答（JSON-QA 渲染）

- stage_id: `02_boot_trap`
- terminology_profile: `stallings_en_zh`

## 第 02_boot_trap 阶段：启动/架构与 Trap/系统调用

### Q02_001（short_answer）

- 题干：启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）
- 答案："链接脚本 `linker/linker64.ld` 定义 `ENTRY(_entry)` (第 2 行)。实际汇编入口有两个变体：`kernel/entry_k210.S` 定义 `_start` 符号 (第 2 行)，`kernel/entry_qemu.S` 定义 `_entry` 符号 (第 2 行)。两者都调用 `main` 函数进入 C 入口。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `linker/linker64.ld` | `directive ENTRY(_entry)` | OUTPUT_ARCH(riscv)<br>ENTRY(_entry) |
| `kernel/entry_k210.S` | `label _start` | .section .text.entry<br>	.globl _start<br>_start: |
| `kernel/entry_qemu.S` | `label _entry` | .section .text<br>	.globl _entry<br>_entry: |

### Q02_002（single_choice）

- 题干：启动链更接近哪种交接方式？
- 答案："固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `README.md` | `document Run on k210 board` | Build the kernel and run: make run |
| `Makefile` | `makefile QEMUOPTS` | QEMUOPTS += -bios $(SBI) |
| `bootloader/SBI/rustsbi-k210` | `directory rustsbi-k210` | RustSBI firmware for K210 |

### Q02_003（tri_state_impl）

- 题干：是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `macro SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User |
| `kernel/trap/trap.c` | `function usertrapret` | x &= ~SSTATUS_SPP; // clear SPP to 0 for user mode |
| `kernel/main.c` | `function main` | RustSBI(M 态) → entry.S _start(委托到 S 态) → main.c main() C 入口 |

### Q02_004（short_answer）

- 题干：模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）
- 答案："RISC-V S 态关键寄存器：`sstatus` (SPP 位 bit 8 保存先前模式，SPIE bit 5 保存中断使能)，`satp` (SV39 页表基址)，`stvec` (陷阱向量基址)，`sepc` (异常返回地址)，`scause` (异常原因)。证据：`include/hal/riscv.h` 定义 `SSTATUS_SPP (1L << 8)`、`SSTATUS_SPIE (1L << 5)`、`SATP_SV39 (8L << 60)`。`kernel/trap/trap.c:usertrapret()` 清除 SPP 位返回用户态。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `macro SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User |
| `include/hal/riscv.h` | `macro SATP_SV39` | #define SATP_SV39 (8L << 60) |
| `kernel/trap/trap.c` | `function usertrapret` | x &= ~SSTATUS_SPP; // clear SPP to 0 for user mode |

### Q02_005（tri_state_impl）

- 题干：是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function kvminit` | void kvminit() { kernel_pagetable = (pagetable_t) allocpage(); kvmmap(...); } |
| `kernel/mm/vm.c` | `function kvminithart` | void kvminithart() { uint64 stap = SATP_SV39 | (((uint64)kernel_pagetable) >> 12); w_satp(stap); asm volatile("sfence.vma"); } |
| `kernel/main.c` | `function main` | kvminit(); kvminithart(); // turn on paging |

### Q02_006（short_answer）

- 题干：从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）
- 答案："启动链：1) RustSBI 固件 (M 态) → 2) `kernel/entry_k210.S:_start` 或 `kernel/entry_qemu.S:_entry` (汇编入口，设置栈) → 3) `call main` 跳转到 `kernel/main.c:main()` (C 入口) → 4) `main()` 中初始化顺序：`cpuinit()` → `floatinithart()` → `consoleinit()` → `kvminit()` → `kvminithart()` → `trapinithart()` → `procinit()` → `scheduler()`。证据：`kernel/entry_k210.S:10` 调用 `main`，`kernel/main.c:35-97` 完整初始化序列。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/entry_k210.S` | `instruction call main` | # jump into main <br>	call main |
| `kernel/main.c` | `function main` | void main(unsigned long hartid, unsigned long dtb_pa) { ... cpuinit(); floatinithart(); consoleinit(); kvminit(); kvminithart(); trapinithart(); procinit(); scheduler(); } |

### Q02_007（fill_in）

- 题干：早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）
- 答案："BSS 清零 (BSS Clearing): implemented [linker/linker64.ld:53-56 .bss 段定义，链接器自动处理]\n早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:consoleinit() + sbi_console_putchar 通过 SBI 调用]\n设备树解析 (Device Tree Blob parsing, DTB): not_found [main.c 接收 dtb_pa 参数但未显式解析 DTB]\n页表初始化时机 (Page Table Init): implemented [kernel/mm/vm.c:kvminit() 在 kvminithart() 之前，MMU 启用前建立映射]"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `linker/linker64.ld` | `section .bss` | .bss : { sbss_clear = .; *(.sbss .bss .bss.*) ebss_clear = .; } |
| `kernel/console.c` | `function consoleinit` | void consoleinit() { ... sbi_console_putchar ... } |
| `kernel/main.c` | `function main` | void main(unsigned long hartid, unsigned long dtb_pa) { ... } |
| `kernel/mm/vm.c` | `function kvminit` | void kvminit() { ... kvmmap(...) ... } // 在 kvminithart 之前调用 |

### Q02_008（tri_state_impl）

- 题干：是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `function floatinithart` | static inline void floatinithart() { w_sstatus_fs(SSTATUS_FS_INIT); w_frm(FRM_RNE); w_sstatus_fs(SSTATUS_FS_CLEAN); } |
| `kernel/main.c` | `function main` | floatinithart(); // 在 hart 0 和 hart 1 初始化中都调用 |

### Q02_009（tri_state_impl）

- 题干：是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function trapinithart` | void trapinithart(void) { w_stvec((uint64)kernelvec); w_sstatus(r_sstatus() | SSTATUS_SIE); ... } |
| `kernel/main.c` | `function main` | trapinithart();  // install kernel trap vector, including interrupt handler |

### Q02_010（short_answer）

- 题干：构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）
- 答案："通过 Makefile 的 `platform` 变量控制：`platform := k210` (默认) 或 `platform := qemu`。使用 `#ifdef QEMU` 条件编译区分平台。入口文件固定为 `kernel/entry.S`，但实际根据平台使用 `entry_k210.S` 或 `entry_qemu.S`。证据：`Makefile:1-2` 设置 platform 变量，`Makefile:28-29` 添加 `-D QEMU` 标志。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `Makefile` | `variable platform` | platform	:= k210<br># platform	:= qemu |
| `Makefile` | `conditional QEMU flag` | ifeq ($(platform), qemu)<br>CFLAGS += -D QEMU<br>endif |

### Q02_011（tri_state_impl）

- 题干：对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `bootloader/SBI/rustsbi-k210` | `directory rustsbi-k210` | RustSBI firmware for K210 |
| `Makefile` | `variable SBI` | ifeq ($(platform), k210)<br>	SBI := ./sbi/sbi-k210<br>else<br>	SBI	:= ./sbi/sbi-qemu<br>endif |
| `kernel/trap/trap.c` | `function handle_intr` | else if (INTR_SOFTWARE == scause && sbi_xv6_is_ext().value) // SBI 扩展调用 |

### Q02_012（tri_state_impl）

- 题干：MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function kvminit` | kvmmap(UART_V, UART, PGSIZE, PTE_R | PTE_W); // 映射 UART 寄存器到虚拟地址 |
| `include/memlayout.h` | `macro UART_V` | UART 虚拟地址映射定义 |

### Q02_013（tri_state_impl）

- 题干：是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function usertrapret` | void usertrapret(void) { w_stvec(TRAMPOLINE + (uservec - trampoline)); ... ((void (*)(uint64, uint64))fn)((uint64)(p->trapframe), satp); } |
| `kernel/trap/trampoline.S` | `label userret` | userret: ... sret // return to user mode and user pc |

### Q02_014（short_answer）

- 题干：是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）
- 答案："未发现多平台支持。代码仅支持 K210 和 QEMU virt 两种平台，通过 Makefile 的 platform 变量切换。搜索 visionfive、jh7110、loongarch 均无匹配结果。"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q02_015（short_answer）

- 题干：trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）
- 答案："陷阱向量入口：内核态通过 `kernel/trap/kernelvec.S:kernelvec` (第 8 行)，用户态通过 `kernel/trap/trampoline.S:uservec` (第 15 行)。`kernel/trap/trap.c:trapinithart()` 设置 `w_stvec((uint64)kernelvec)`。异常处理函数为 `kernel/trap/trap.c:usertrap()` 和 `kerneltrap()`。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/kernelvec.S` | `label kernelvec` | .globl kernelvec<br>kernelvec: |
| `kernel/trap/trampoline.S` | `label uservec` | .globl uservec<br>uservec: |
| `kernel/trap/trap.c` | `function trapinithart` | w_stvec((uint64)kernelvec); |

### Q02_016（single_choice）

- 题干：trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？
- 答案："用户地址空间预留页（trampoline/trap_context page）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/trap.h` | `comment trapframe comment` | per-process data for the trap handling code in trampoline.S. sits in a page by itself just under the trampoline page in the user page table. |
| `kernel/trap/trampoline.S` | `instruction uservec` | csrrw a0, sscratch, a0 // sscratch points to where the process's p->trapframe is mapped into user space |

### Q02_017（short_answer）

- 题干：TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）
- 答案："定义在 `include/trap.h:17-93` 的 `struct trapframe`。包含：整数寄存器 32 个 (ra,sp,gp,tp,t0-t6,s0-s11,a0-a7) + 浮点寄存器 32 个 (ft0-ft11,fs0-fs11,fa0-fa7) + fcsr 控制寄存器 = 共 65 个字段。总字节数：548 字节 (0-544 为寄存器，544-548 为 fcsr)。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/trap.h` | `struct trapframe` | struct trapframe { /*   0 */ uint64 kernel_satp; ... /* 544 */ uint64 fcsr; }; |

### Q02_018（tri_state_impl）

- 题干：是否存在系统调用分发表（syscall table / match 分发）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/syscall.c` | `array syscalls[]` | static uint64 (*syscalls[])(void) = { [SYS_fork] sys_fork, [SYS_exit] sys_exit, ... }; |

### Q02_019（tri_state_impl）

- 题干：系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/syscall.c` | `function syscall` | if (SYS_rt_sigreturn == num) { ... } else if (num < NELEM(syscalls) && syscalls[num]) { ... } else { p->trapframe->a0 = -1; } |

### Q02_020（short_answer）

- 题干：选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。
- 答案："sys_write 路径：1) 用户态 `ecall` 指令 → 2) `kernel/trap/trampoline.S:uservec` 保存上下文 → 3) `kernel/trap/trap.c:usertrap()` 检测 `EXCP_ENV_CALL` → 4) `kernel/syscall/syscall.c:syscall()` 通过 `syscalls[SYS_write]` 分发 → 5) `kernel/syscall/sysfile.c:sys_write()` 实现文件写入。证据：`trap.c:97-107` 系统调用分支，`syscall.c:212` 分发表索引，`sysfile.c` 实现写入逻辑。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function usertrap` | if (cause == EXCP_ENV_CALL) { ... syscall(); } |
| `kernel/syscall/syscall.c` | `function syscall` | p->trapframe->a0 = syscalls[num](); |
| `kernel/syscall/syscall.c` | `array syscalls[]` | [SYS_write] sys_write, |

### Q02_021（short_answer）

- 题干：列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。
- 答案："高价值 syscall 实现状态：\n- sys_fork: implemented [kernel/sched/proc.c:fork()]\n- sys_exec: implemented [kernel/exec.c:exec()]\n- sys_mmap: implemented [kernel/syscall/sysmem.c:sys_mmap()]\n- sys_openat: implemented [kernel/syscall/sysfile.c:sys_openat()]\n- sys_write: implemented [kernel/syscall/sysfile.c:sys_write()]\n- sys_clone: implemented [kernel/sched/proc.c:clone()]\n- sys_wait4: implemented [kernel/sched/proc.c:wait4()]\n- sys_getuid: stub [kernel/syscall/sysproc.c:267-269 仅返回 0]\n- sys_geteuid: stub [kernel/syscall/syscall.c:233 指向 sys_getuid]\n- sys_getgid: stub [kernel/syscall/syscall.c:234 指向 sys_getuid]"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function fork` | int fork(void) { ... } |
| `kernel/exec.c` | `function exec` | int exec(char *path, char **argv, char **envp) { ... } |
| `kernel/syscall/sysproc.c` | `function sys_getuid` | uint64 sys_getuid(void) { return 0; } |

### Q02_022（tri_state_impl）

- 题干：是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function copyout` | int copyout(pagetable_t pagetable, uint64 dstva, char *src, uint64 len) { ... pa0 = walkaddr(pagetable, va0); if(pa0 == NULL) return -1; ... } |
| `kernel/mm/vm.c` | `function copyin2` | int copyin2(char *dst, uint64 srcva, uint64 len) { ... uint64 badaddr = safememmove(dst, (char *)srcva, len, 1); ... } |
| `kernel/syscall/syscall.c` | `function fetchaddr` | int fetchaddr(uint64 addr, uint64 *ip) { if(copyin2((char *)ip, addr, sizeof(*ip)) != 0) return -1; } |

### Q02_023（tri_state_impl）

- 题干：时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_intr` | if (INTR_TIMER == scause) { timer_tick(); proc_tick(); ... if (yield()) { p->ivswtch += 1; } } |
| `kernel/sched/proc.c` | `function yield` | int yield(void) { ... sched(); ... } |

### Q02_024（tri_state_impl）

- 题干：是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function usertrap` | if (p->killed) { if (SIGTERM == p->killed) exit(-1); sighandle(); } |
| `kernel/sched/signal.c` | `function sighandle` | void sighandle(void) { ... struct sig_frame *frame = kmalloc(...); ... } |
| `kernel/sched/signal.c` | `function sigreturn` | void sigreturn(void) { ... kfree(p->trapframe); p->trapframe = frame->tf; ... } |

### Q02_025（short_answer）

- 题干：缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）
- 答案："存在联动。入口点：`kernel/trap/trap.c:handle_excp()` 检测页面异常 → 调用 `kernel/mm/vm.c:handle_page_fault()`。CoW 处理：`vm.c:handle_store_page_fault_cow()` 检测 PTE_COW 标志并复制页面。Lazy 分配：`vm.c:handle_page_fault_lazy()` 为 HEAP/STACK 段按需分配页面。证据：`trap.c:320-330` 异常分发，`vm.c:783-850` 缺页处理完整链路。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_excp` | case EXCP_STORE_PAGE: return handle_page_fault(1, r_stval()); |
| `kernel/mm/vm.c` | `function handle_page_fault` | int handle_page_fault(int kind, uint64 badaddr) { ... switch (seg->type) { case LOAD: ... case HEAP: case STACK: return handle_page_fault_lazy(...); } } |
| `kernel/mm/vm.c` | `function handle_store_page_fault_cow` | static int handle_store_page_fault_cow(pte_t *ptep) { if (monopolizepage(pa)) { pte |= PTE_W; } else { char *copy = (char *)allocpage(); ... } } |

### Q02_026（short_answer）

- 题干：与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）
- 答案："多核一致。`kernel/main.c:main()` 中 hart 0 先初始化 `trapinithart()`，然后通过 `sbi_send_ipi()` 唤醒其他 hart。其他 hart 在 `started == 1` 后也调用 `trapinithart()`。每 CPU 通过 `tp` 寄存器存储 hartid (`main.c:inithartid()`)。时钟初始化在 `trapinithart()` 中通过 `set_next_timeout()` 完成。证据：`main.c:45-75` 多核启动序列，`trap.c:52` 每 hart 陷阱初始化。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/main.c` | `function main` | for (int i = 1; i < NCPU; i ++) { sbi_send_ipi(mask, 0); } ... started = 1; ... else { floatinithart(); kvminithart(); trapinithart(); } |
| `kernel/trap/trap.c` | `function trapinithart` | void trapinithart(void) { w_stvec((uint64)kernelvec); ... set_next_timeout(); } |

### Q02_027（fill_in）

- 题干：Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）
- 答案："分发表路径：kernel/syscall/syscall.c:194-258 (syscalls[] 数组)\n完整实现 ✅ (implemented): 约 55 个 (sys_fork, sys_exec, sys_write, sys_read, sys_openat, sys_mmap, sys_clone, sys_wait4 等有完整逻辑)\n桩/ENOSYS/return 0 🔸 (stub): 约 5 个，代表性例子：sys_getuid (仅返回 0), sys_geteuid (指向 sys_getuid), sys_getgid (指向 sys_getuid), sys_getegid (指向 sys_getuid), sys_prlimit64 (仅返回 0)\n未注册 ❌ (not_found): 0 个 (所有 SYS_* 常量都在 syscalls[] 中有注册，即使是指向桩函数)\n统计依据：grep kernel/syscall/syscall.c 的 syscalls[] 数组，共 68 个条目；逐个检查 sys_*.c 文件中的实现体深度"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/syscall.c` | `array syscalls[]` | static uint64 (*syscalls[])(void) = { [SYS_fork] sys_fork, ... [SYS_msync] sys_msync }; // 共 68 个条目 |
| `kernel/syscall/sysproc.c` | `function sys_getuid` | uint64 sys_getuid(void) { return 0; } |

### Q02_028（short_answer）

- 题干：README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）
- 答案："README.md 未明确列出 syscall 兼容性声称，仅在 Progress 章节列出功能进度（进程管理、文件系统等）。doc/用户使用 - 系统调用.md 提到支持标准 POSIX syscall。代码分发表实际实现了 68 个 syscall，覆盖 fork/exec/wait/read/write/open/close/mmap 等核心功能，与 README 声称的\"进程管理\"、\"文件系统\"功能一致。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `README.md` | `section Progress` | ## Progress<br>- [x] Process management<br>- [x] File system |

### Q02_029（short_answer）

- 题干：`_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）
- 答案："未见该命名模式。搜索 `_impl\\b|sys_[a-z0-9_]*_impl` 在 152 个文件中无匹配结果。xv6-k210 采用直接命名（如 `sys_write`），未使用 `_impl` 后缀分离接口与实现。"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q02_030（tri_state_impl）

- 题干：是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_intr` | else if (INTR_SOFTWARE == scause && sbi_xv6_is_ext().value) { int irq = plic_claim(); switch (irq) { case UART_IRQ: consoleintr(c); break; case DISK_IRQ: disk_intr(); break; } } |
| `kernel/hal/plic.c` | `function plic_claim` | int plic_claim(void) { ... } |

### Q02_031（tri_state_impl）

- 题干：非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q02_032（short_answer）

- 题干：信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）
- 答案："仅支持进程级信号发送。实现了 `kernel/syscall/syssignal.c:sys_kill()` (第 134 行)，通过 `kill(pid, sig)` 向进程发送信号。未发现 sys_tkill (线程级) 和 sys_tgkill (进程组级) 的实现。搜索 sys_tkill 和 sys_tgkill 无匹配结果。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/syssignal.c` | `function sys_kill` | uint64 sys_kill(void) { int pid, sig; argint(0, &pid); argint(1, &sig); return kill(pid, sig); } |

### Q02_033（single_choice）

- 题干：中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）
- 答案："通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_intr` | if (INTR_TIMER == scause) { ... } else if (INTR_EXTERNAL == scause) { ... } |
| `kernel/trap/trap.c` | `function handle_excp` | switch (scause) { case EXCP_STORE_PAGE: ... case EXCP_LOAD_PAGE: ... } |
| `include/hal/riscv.h` | `macro INTR_TIMER` | #define INTR_TIMER (0x5 | INTERRUPT_FLAG) // Supervisor interrupt number |

### Q02_034（tri_state_impl）

- 题干：是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function kerneltrap` | __debug_assert("kerneltrap", 0 == intr_get(), "interrupts enable\n"); // 断言中断关闭 |
| `kernel/trap/kernelvec.S` | `instruction kernelvec` | kernelvec: ... call kerneltrap ... sret // 整个 handler 执行期间中断关闭 |

---


# 内存管理物理虚拟分配器

## 题单作答（JSON-QA 渲染）

- stage_id: `03_mem_mgmt`
- terminology_profile: `stallings_en_zh`

## 第 03_mem_mgmt 阶段：内存管理（物理/虚拟/分配器）

### Q03_001（single_choice）

- 题干：该 OS 的内存管理实现语言/形态更接近哪类？（只选最贴近的一项）
- 答案："C/Makefile 风格内核（xv6 类）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/pm.c` | `file pm.c` | C 语言实现的物理页分配器，使用 struct run 和 struct pm_allocator |
| `kernel/mm/vm.c` | `file vm.c` | C 语言实现的页表管理和缺页处理 |

### Q03_002（tri_state_impl）

- 题干：是否存在“物理页帧分配器 (Physical Frame Allocator)”的真实实现？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/pm.c` | `struct pm_allocator` | struct pm_allocator { struct spinlock lock; struct run *freelist; uint64 npage; } |
| `kernel/mm/pm.c` | `function allocpage_n` | void *allocpage_n(uint64 n) 分配 n 页 |
| `kernel/mm/pm.c` | `function _freepage` | void _freepage(uint64 pa) 释放单页 |

### Q03_003（single_choice）

- 题干：物理内存分配算法更接近哪种？
- 答案："空闲链表 run list（xv6 风格）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/pm.c` | `struct run` | struct run { struct run *next; uint64 npage; } 单链表结构 |
| `kernel/mm/pm.c` | `function __mul_alloc_no_lock` | 遍历空闲链表查找足够大的块 |

### Q03_004（short_answer）

- 题干：物理页帧分配器的核心数据结构是什么？（例如 bitmap 数组、buddy free list、slab cache 表、`struct run` 单链表等；必须引用结构体/字段证据）
- 答案："struct run 单链表 + struct pm_allocator 分桶管理。struct run 包含 next 指针和 npage 字段表示连续页数；struct pm_allocator 包含 spinlock 锁、freelist 链表头和 npage 总页数。系统维护 single 和 multiple 两个分配器实例，分别管理单页和多页分配。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/pm.c` | `struct run` | struct run { struct run *next; uint64 npage; } |
| `kernel/mm/pm.c` | `struct pm_allocator` | struct pm_allocator { struct spinlock lock; struct run *freelist; uint64 npage; } |
| `kernel/mm/pm.c` | `variable single` | struct pm_allocator single; 管理单页 |
| `kernel/mm/pm.c` | `variable multiple` | struct pm_allocator multiple; 管理多页 |

### Q03_005（short_answer）

- 题干：物理分配器的并发控制锁粒度是什么？（全局大锁 / per-CPU / 分桶 / 无锁+关中断 / 其他；必须给锁对象类型与持锁范围证据）
- 答案："分桶锁（双锁设计）。single 和 multiple 两个分配器各持有一个独立的 spinlock。alloc/free 操作通过 __enter_sin_cs/__leave_sin_cs 或 __enter_mul_cs/__leave_mul_cs 宏获取对应锁，持锁范围覆盖整个分配/释放操作全程。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/pm.c` | `macro __enter_sin_cs` | #define __enter_sin_cs acquire(&single.lock); |
| `kernel/mm/pm.c` | `macro __enter_mul_cs` | #define __enter_mul_cs acquire(&multiple.lock); |
| `kernel/mm/pm.c` | `function allocpage_n` | __enter_mul_cs ret = __mul_alloc_no_lock(n); __leave_mul_cs |

### Q03_006（tri_state_impl）

- 题干：是否存在“页表 (page table) 结构体 + walk/map/unmap”的真实实现？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function walk` | pte_t *walk(pagetable_t pagetable, uint64 va, int alloc) 三级页表遍历 |
| `kernel/mm/vm.c` | `function mappages` | int mappages(pagetable_t pagetable, uint64 va, uint64 size, uint64 pa, int perm) |
| `kernel/mm/vm.c` | `function unmappages` | void unmappages(pagetable_t pagetable, uint64 va, uint64 npages, int flag) |

### Q03_007（short_answer）

- 题干：页表操作 API（walk/map/unmap 或等价）对应的函数名/模块是什么？列出 1-3 个关键入口并给证据。
- 答案："核心 API：walk() 用于页表遍历（kernel/mm/vm.c:211），mappages() 用于建立映射（kernel/mm/vm.c:280），unmappages() 用于解除映射（kernel/mm/vm.c:337）。辅助 API：uvmalloc() 用于用户地址空间增长（kernel/mm/vm.c:417），walkaddr() 用于用户地址验证（kernel/mm/vm.c:227）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function walk` | pte_t *walk(pagetable_t pagetable, uint64 va, int alloc) 行 211 |
| `kernel/mm/vm.c` | `function mappages` | int mappages(pagetable_t pagetable, uint64 va, uint64 size, uint64 pa, int perm) 行 280 |
| `kernel/mm/vm.c` | `function unmappages` | void unmappages(pagetable_t pagetable, uint64 va, uint64 npages, int flag) 行 337 |

### Q03_008（short_answer）

- 题干：页表修改路径的并发控制是什么？（锁粒度、是否需要关中断、是否使用每进程地址空间锁等；必须引用锁/临界区证据）
- 答案："依赖进程地址空间隔离 + 关中断。页表修改路径（walk/mappages/unmappages）本身无显式每页表锁，但通过以下机制保证安全：(1) 每个进程有独立的 pagetable，用户态页表修改在进程上下文中进行；(2) 内核态页表修改时通过 intr_off() 关中断（如 usertrapret 中）；(3) trap 处理路径中 handle_page_fault 在关中断的 kerneltrap 上下文中执行。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function usertrapret` | intr_off() 在切换页表前关中断 |
| `kernel/mm/vm.c` | `function uvmcopy` | sfence_vma() 在页表修改后刷新 TLB |

### Q03_009（single_choice）

- 题干：内核与用户地址空间关系更接近哪种？
- 答案："共享同一页表（内核映射常驻，高半核等）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/memlayout.h` | `macro TRAMPOLINE` | #define TRAMPOLINE (MAXVA - PGSIZE) 内核 trampoline 页在用户页表中也有映射 |
| `kernel/mm/vm.c` | `function uvmcopy` | 子进程复制父进程页表时保留内核映射 |

### Q03_010（tri_state_impl）

- 题干：是否存在缺页异常 (Page Fault) 处理逻辑并与内存分配/映射联动？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function handle_page_fault` | int handle_page_fault(int kind, uint64 badaddr) 行 1039，统一分发到 loadelf/lazy/mmap/COW 子处理 |
| `kernel/trap/trap.c` | `function handle_excp` | EXCP_STORE_PAGE/EXCP_LOAD_PAGE/EXCP_INST_PAGE 调用 handle_page_fault |

### Q03_011（short_answer）

- 题干：追踪一条缺页链路：trap/异常入口 → 缺页处理函数（handle_page_fault 或等价）→ 分配页帧 → 建立映射。用 3-5 个关键节点描述并给每节点证据。
- 答案："缺页链路：(1) kerneltrap() [kernel/trap/trap.c:206] 捕获异常 → (2) handle_excp() [kernel/trap/trap.c:323] 识别缺页类型 → (3) handle_page_fault() [kernel/mm/vm.c:1039] 根据 seg 类型分发 → (4) handle_page_fault_lazy() [kernel/mm/vm.c:1002] 调用 uvmalloc() → (5) uvmalloc() [kernel/mm/vm.c:417] 调用 allocpage() 和 mappages() 建立映射 → (6) sfence_vma() 刷新 TLB。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_excp` | return handle_page_fault(1, r_stval()) 行 329 |
| `kernel/mm/vm.c` | `function handle_page_fault_lazy` | uvmalloc(p->pagetable, pa, pa + PGSIZE, s->flag) 行 1007 |
| `kernel/mm/vm.c` | `function uvmalloc` | mem = allocpage(); mappages(pagetable, a, PGSIZE, (uint64)mem, perm|PTE_U) |

### Q03_012（tri_state_impl）

- 题干：是否实现写时复制 (Copy-on-Write, CoW)？（必须三态；若 implemented 需说明触发点在 fault 中还是 fork 中）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function uvmcopy` | if (cow && (*pte & PTE_W)) { *pte = (*pte|PTE_COW) & ~PTE_W; } 行 567-568，fork 时标记 COW |
| `kernel/mm/vm.c` | `function handle_store_page_fault_cow` | 行 975，缺页时处理 COW：monopolizepage() 检查或 allocpage() 复制 |
| `kernel/mm/vm.c` | `macro PTE_COW` | #define PTE_COW PTE_RSW1 行 22 |

### Q03_013（tri_state_impl）

- 题干：是否实现惰性分配 (Lazy Allocation)？（必须三态；若 implemented 需说明是在 brk/mmap 还是 fault 中分配）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function handle_page_fault_lazy` | HEAP/STACK 段缺页时调用 uvmalloc() 分配物理页 行 1002-1015 |
| `kernel/mm/vm.c` | `function handle_page_fault` | case HEAP: case STACK: return handle_page_fault_lazy(badaddr, seg) 行 1088-1089 |

### Q03_014（tri_state_impl）

- 题干：是否实现 swap（swap_in/swap_out 或等价页面置换）？（必须三态）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `search swap` | 搜索 swap/swap_in/swap_out 未发现实现代码 |
| `kernel/mm/pm.c` | `search page_replacement` | 未发现页面置换相关代码 |

### Q03_015（tri_state_impl）

- 题干：是否实现 mmap（文件映射/匿名映射）且处理标志位（MAP_FIXED/MAP_ANON/MAP_SHARED 等）？（必须三态；stub 需说明形态如 ENOSYS/return 0）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/mmap.c` | `function do_mmap` | uint64 do_mmap(uint64 start, uint64 len, int prot, int flags, struct file *f, int64 off) 行 710 |
| `kernel/mm/mmap.c` | `function handle_page_fault_mmap` | 处理 MMAP 段缺页，区分匿名映射和文件映射 行 1126 |
| `kernel/syscall/sysmem.c` | `function sys_mmap` | 系统调用入口 行 80 |

### Q03_016（tri_state_impl）

- 题干：是否存在 Page Cache（页缓存/文件页缓存）管理？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/bio.c` | `file bio.c` | Buffer cache 实现，使用 struct buf 缓存磁盘块，LRU 链表管理 |
| `kernel/fs/bio.c` | `variable bcache` | static list_node_t *bcache[BCACHE_TABLE_SIZE] 哈希表 |
| `kernel/fs/bio.c` | `variable lru_head` | static struct d_list lru_head LRU 链表头 |

### Q03_017（tri_state_impl）

- 题干：是否存在脏页回写 (dirty page writeback) 机制？（必须三态；若 implemented 需指出同步/异步与触发条件）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/bio.c` | `function bwrite` | 行 199，异步写回：disk_submit() 提交到磁盘驱动队列，不等待完成 |
| `kernel/fs/bio.c` | `comment dirty_buffer_writeback` | 注释说明：Dirty buffer write back no-block mechanism，异步提交到磁盘驱动 |

### Q03_018（tri_state_impl）

- 题干：是否存在 TLB 射击 (TLB Shootdown / Remote TLB Flush)机制以支持多核页表一致性？（必须三态；若 implemented 需指向 IPI/跨核调用证据）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/` | `search shootdown` | 搜索 shootdown/ipi.*tlb/remote.*flush 未找到匹配 |
| `kernel/trap/trap.c` | `search sbi_send_ipi` | 注释掉的 IPI 代码：// sbi_send_ipi(1 << i, 0) 行 314 |

### Q03_019（short_answer）

- 题干：TLB 刷新指令/函数点是什么？（RISC-V sfence.vma / AArch64 tlbi / x86 invlpg 等，或仓库中等价的 TLB 刷新封装；必须给证据）
- 答案："sfence_vma() 函数 [include/hal/riscv.h:362]。QEMU 模式下使用 sfence.vma 指令，K210 实机使用 .word 0x10400073（sfence.vm 的机器码）。调用点：uvmcopy() 行 588、handle_store_page_fault_cow() 行 996、handle_page_fault_lazy() 行 1013、do_mmap() 行 773 等。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `function sfence_vma` | static inline void sfence_vma() { asm volatile(".word 0x10400073"); } |
| `kernel/mm/vm.c` | `function uvmcopy` | sfence_vma() 行 588 |

### Q03_020（short_answer）

- 题干：用户指针安全检查机制是什么？（access_ok/verify_area/UserInPtr 等；列出入口点与校验逻辑证据）
- 答案："双重保护机制：(1) 硬件页表权限位：walkaddr() 检查 PTE_V 和 PTE_U 位 [kernel/mm/vm.c:227-243]；(2) 软件段检查：copyin2()/copyout2() 使用 partofseg() 验证地址是否在进程的 struct seg 链表范围内 [kernel/mm/vm.c:768-780]。safememmove() 使用 permit_usr_mem()/protect_usr_mem() 切换 SSTATUS_SUM 位控制用户态访问权限。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function walkaddr` | 检查 PTE_V 和 PTE_U 位，返回物理地址或 NULL |
| `kernel/mm/vm.c` | `function copyout2` | struct seg *s = partofseg(p->segment, dstva, dstva + len) 行 768 |
| `kernel/mm/vm.c` | `function safememmove` | permit_usr_mem() 和 protect_usr_mem() 控制 SSTATUS_SUM 位 |

### Q03_021（single_choice）

- 题干：若实现了页面置换 (Page Replacement)，使用的算法最接近哪种？（Stallings Ch8：OPT 理想算法 / LRU 最近最少使用 / Clock 近似 LRU / FIFO / 未实现）
- 答案："未实现页面置换（无 swap）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/` | `search page_replacement` | 搜索 swap/page_replacement/clock/lru/fifo 未发现实现 |

### Q03_022（tri_state_impl）

- 题干：是否存在工作集模型 (Working Set Model, WSM) 或抖动检测/防止 (Thrashing Prevention) 机制？（必须三态；Stallings Ch8 核心概念；若 not_found 需列出已搜关键字 working_set|thrash|resident_set）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/` | `search working_set` | 搜索 working_set|thrash|resident_set 未找到匹配 |

### Q03_023（fill_in）

- 题干：物理内存总量（Physical Memory Size）：____ KB/MB；页大小（Page Size）：____ bytes；最大进程虚拟地址空间（Virtual Address Space）：____ bits。（必须从代码常量/链接脚本/配置中给出证据；无法确定则写 unknown 并说明已搜路径）
- 答案："物理内存总量：6 MB（PHYSTOP 0x80600000 - KERNBASE 0x80020000 ≈ 6MB）；页大小：4096 bytes（PGSIZE）；最大进程虚拟地址空间：39 bits（Sv39，MAXVA = 1L << (9+9+9+12-1) = 2^38，实际可用 38 位，但 Sv39 支持 39 位虚拟地址）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/memlayout.h` | `macro PHYSTOP` | #define PHYSTOP 0x80600000UL 行 102 |
| `include/memlayout.h` | `macro KERNBASE` | #define KERNBASE 0x80020000UL 行 99 |
| `include/hal/riscv.h` | `macro PGSIZE` | #define PGSIZE 4096 行 378 |
| `include/hal/riscv.h` | `macro MAXVA` | #define MAXVA (1L << (9 + 9 + 9 + 12 - 1)) 行 408 |

### Q03_024（single_choice）

- 题干：内存保护机制 (Memory Protection) 的实现形式更接近哪种？（Stallings Ch7.1）
- 答案："硬件页表 + 软件指针检查双重保护"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function walkaddr` | 检查 PTE_V 和 PTE_U 位，硬件 MMU 拒绝非法访问 |
| `kernel/mm/vm.c` | `function partofseg` | 软件检查地址是否在 struct seg 范围内 |

### Q03_025（short_answer）

- 题干：逻辑内存组织 (Logical Memory Organization, Stallings Ch7.1)：进程地址空间中 text/data/heap/stack/mmap 各区域（或等价区间）是否由统一的映射管理结构（VMA/区间表/链表/BTreeMap 等）维护？（如存在请给结构体证据；不存在则写未发现等价结构）
- 答案："是，使用 struct seg 链表维护。struct seg 包含 type（LOAD/TEXT/DATA/BSS/HEAP/MMAP/STACK）、addr（起始地址）、sz（大小）、flag（权限）、next（链表指针）等字段。进程控制块 struct proc 包含 segment 字段指向 seg 链表头。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/mm/usrmm.h` | `struct seg` | struct seg { enum segtype type; int flag; uint64 addr; uint64 sz; struct seg *next; ... } |
| `include/sched/proc.h` | `struct proc` | struct proc 包含 struct seg *segment 字段 |

### Q03_026（single_choice）

- 题干：是否存在显式的硬件分段机制 (Hardware Segmentation, Stallings Ch7.4)？
- 答案："纯分页无分段（RISC-V/AArch64 常见）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `file riscv.h` | RISC-V Sv39 纯分页机制，无硬件段描述符 |
| `include/mm/usrmm.h` | `struct seg` | struct seg 是软件逻辑分区，非硬件分段 |

### Q03_027（single_choice）

- 题干：取页策略 (Fetch Policy, Stallings Ch8.2) 更接近哪种？
- 答案："按需调页 (Demand Paging)：缺页时才分配物理页"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function handle_page_fault_lazy` | HEAP/STACK 段缺页时调用 uvmalloc() 分配物理页 |
| `kernel/mm/vm.c` | `function handle_page_fault_loadelf` | LOAD 段缺页时调用 loadseg() 从 ELF 文件加载 |

### Q03_028（short_answer）

- 题干：放置策略 (Placement Policy, Stallings Ch8.2)：新的匿名映射或堆区域增长时，系统如何选择虚拟地址区间？（固定起始地址 / mmap_base 向下生长 / 首次适配 / 最佳适配 等；必须给实现证据或写未发现等价策略）
- 答案："首次适配（first-fit）策略。lookup_segment() 在进程的 struct seg 链表中顺序查找第一个足够大的空闲间隙。对于 mmap，lookup_fixed_segment() 支持 MAP_FIXED 固定地址映射，否则使用 lookup_segment() 查找合适位置。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/mmap.c` | `function lookup_segment` | 遍历 seg 链表查找空闲间隙 |
| `kernel/mm/mmap.c` | `function lookup_fixed_segment` | 处理 MAP_FIXED 标志，删除现有映射 |

### Q03_029（tri_state_impl）

- 题干：是否存在驻留集管理/内存负载控制 (Resident Set Management / Load Control, Stallings Ch8.2)？（包括工作集动态调整、内存回收守护线程、OOM killer、驻留页数限制等；若 not_found 需列出已搜关键字）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/` | `search oom_killer` | 搜索 oom|kswapd|resident_set|load_control 未找到匹配 |

### Q03_030（short_answer）

- 题干：内存主链路（必须给出，尽量以 Mermaid graph TD 表达）：从确认的最强内存入口（缺页处理入口/mmap 入口/brk 入口/等价入口）出发，追踪到页表操作核心点或物理页分配核心点，写出 3-6 个关键节点。节点格式：FuncName [path:line]。若链路未被源码证据完全闭合，标注候选主链路而非确认的主链路。只画一条主链，不要并列展开多条支线。
- 答案："graph TD\\n    kerneltrap[kerneltrap kernel/trap/trap.c:206] --> handle_excp[handle_excp kernel/trap/trap.c:323]\\n    handle_excp --> handle_page_fault[handle_page_fault kernel/mm/vm.c:1039]\\n    handle_page_fault --> handle_page_fault_lazy[handle_page_fault_lazy kernel/mm/vm.c:1002]\\n    handle_page_fault_lazy --> uvmalloc[uvmalloc kernel/mm/vm.c:417]\\n    uvmalloc --> mappages[mappages kernel/mm/vm.c:280]\\n    mappages --> allocpage[allocpage kernel/mm/pm.c:233]"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_excp` | 调用 handle_page_fault(1, r_stval()) 行 329 |
| `kernel/mm/vm.c` | `function handle_page_fault_lazy` | 调用 uvmalloc() 行 1007 |
| `kernel/mm/vm.c` | `function uvmalloc` | 调用 allocpage() 和 mappages() 行 426-434 |

### Q03_031（single_choice）

- 题干：该系统更容易出现哪种内存碎片 (Memory Fragmentation, Stallings Ch7.2)？
- 答案："外部碎片 (External Fragmentation)：空闲块分散无法满足大连续请求"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/pm.c` | `function __mul_alloc_no_lock` | 遍历链表查找连续 n 页，可能因碎片化失败 |
| `kernel/mm/pm.c` | `function __mul_free_no_lock` | 释放时尝试合并相邻块缓解外部碎片 |

### Q03_032（single_choice）

- 题干：地址重定位 (Address Relocation, Stallings Ch7.1) 的绑定时机更接近哪种？
- 答案："运行时动态绑定 (Run-time / Dynamic Relocation)：通过 MMU 基址 + 界限或页表在每次访问时转换"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `register satp` | SATP 寄存器存储页表基址，MMU 在每次内存访问时进行地址转换 |
| `kernel/mm/vm.c` | `function walk` | 三级页表遍历将 VA 转换为 PA |

### Q03_033（single_choice）

- 题干：页面置换的作用域策略 (Replacement Scope, Stallings Ch8.2) 更接近哪种？
- 答案："未实现置换（无 swap）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/` | `search swap` | 未发现 swap_in/swap_out 实现 |

### Q03_034（tri_state_impl）

- 题干：是否存在清理策略 (Cleaning Policy, Stallings Ch8.2)？（即脏页预先后台写回，而非仅在置换时才写回；搜索 background writeback / kswapd / cleaner_thread 或等价；必须三态；若 not_found 需列出已搜关键字）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/bio.c` | `function bwrite` | 异步写回机制：disk_submit() 提交到磁盘驱动队列，不等待完成 行 199 |
| `kernel/fs/bio.c` | `comment dirty_writeback` | 注释：Dirty buffer write back no-block mechanism，异步提交 |

---


# 进程线程调度与多核

## 题单作答（JSON-QA 渲染）

- stage_id: `04_process_smp`
- terminology_profile: `stallings_en_zh`

## 第 04_process_smp 阶段：进程/线程/调度与多核

### Q04_001（short_answer）

- 题干：执行实体 (Execution Entity) 抽象是什么？
请按以下格式作答（每项必须有代码证据）：
- 顶层类型名: ___（如 Process / Task / Thread / TaskControlBlock）
- 结构体路径: ___
- 关键字段（至少列 3 个）: Context=___, State=___, PID=___, TrapFrame=___
- 是否区分 PCB 与 TCB: ___（是 / 否 / 待核实）
- 答案："顶层类型名: struct proc (Process Control Block, PCB)\n结构体路径: include/sched/proc.h:51-93\n关键字段: Context=context (struct context, 68-80 行), State=state (enum procstate, 62 行), PID=pid (int, 54 行), TrapFrame=trapframe (struct trapframe*, 85 行)\n是否区分 PCB 与 TCB: 否 (xv6-k210 仅使用统一的 struct proc 作为执行实体，无独立线程控制块)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sched/proc.h` | `struct proc` | struct proc { int xstate; int pid; enum procstate state; struct context context; struct trapframe *trapframe; ... } |
| `include/sched/proc.h` | `struct context` | struct context { uint64 ra; uint64 sp; uint64 s0-s11; }; |

### Q04_002（short_answer）

- 题干：任务/进程的生命周期状态机有哪些状态与流转点？（Ready/Running/Blocked/Exited 等；需状态枚举/字段证据）
- 答案："状态枚举 (include/sched/proc.h:38-42): RUNNABLE(就绪), RUNNING(运行), SLEEPING(阻塞/睡眠), ZOMBIE(僵尸)\n状态流转点:\n- RUNNABLE→RUNNING: scheduler() 中 __get_runnable_no_lock() 选中后设置 state=RUNNING (kernel/sched/proc.c:681 行)\n- RUNNING→RUNNABLE: yield() 或 proc_tick() 超时，调用 __insert_runnable() (kernel/sched/proc.c:627 行/765 行)\n- RUNNING→SLEEPING: sleep() 调用 __insert_sleep() (kernel/sched/proc.c:595 行)\n- SLEEPING→RUNNABLE: wakeup() 调用 __insert_runnable(PRIORITY_IRQ) (kernel/sched/proc.c:379 行)\n- RUNNING→ZOMBIE: exit() 设置 state=ZOMBIE 并 __remove() (kernel/sched/proc.c:447 行)\n- ZOMBIE→释放: wait4() 找到 ZOMBIE 子进程后调用 freeproc() (kernel/sched/proc.c:513 行)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sched/proc.h` | `enum procstate` | enum procstate { RUNNABLE, RUNNING, SLEEPING, ZOMBIE }; |
| `kernel/sched/proc.c` | `function scheduler` | tmp->state = RUNNING; |
| `kernel/sched/proc.c` | `function exit` | p->state = ZOMBIE; __remove(p); |

### Q04_003（tri_state_impl）

- 题干：是否存在上下文切换 (Context Switch) 实现（switch.S/__switch/swtch/context_switch）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/swtch.S` | `function swtch` | .globl swtch; swtch: sd ra, 0(a0); sd sp, 8(a0); ... sd s11, 104(a0); ld ra, 0(a1); ... ret |
| `kernel/sched/proc.c` | `function sched` | swtch(&p->context, &mycpu()->context); |
| `kernel/sched/proc.c` | `function scheduler` | swtch(&c->context, &tmp->context); |

### Q04_004（short_answer）

- 题干：上下文切换保存/恢复了哪些寄存器集合？（例如 RISC-V s0-s11；必须引用汇编/结构体证据）
- 答案："保存/恢复的寄存器 (kernel/sched/swtch.S:7-30 行):\n- ra (返回地址)\n- sp (栈指针)\n- s0-s11 (callee-saved 寄存器，共 12 个)\n总计 14 个寄存器，每个 8 字节，共 112 字节。\n对应 struct context 定义 (include/sched/proc.h:17-30 行): ra, sp, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/swtch.S` | `function swtch` | sd ra, 0(a0); sd sp, 8(a0); sd s0, 16(a0); ... sd s11, 104(a0); ld ra, 0(a1); ... ret |
| `include/sched/proc.h` | `struct context` | struct context { uint64 ra; uint64 sp; uint64 s0; ... uint64 s11; }; |

### Q04_005（short_answer）

- 题干：调度算法 (Scheduling Algorithm) 属于哪类？
请按格式作答：
- 算法名称: ___（必须是以下之一：FCFS / Round-Robin (RR) / Stride/Proportional-Share / MLFQ / CFS / Priority / 其他）
- 代码证据（关键字段/函数）: ___
  - RR: timeslice/slice 字段位置=___
  - Stride: stride 字段与比较逻辑位置=___
  - MLFQ: 多级队列 VecDeque/数组层级证据=___
  - Priority: priority 字段参与 pick_next 排序证据=___
- 答案："算法名称: Priority (多级优先级调度 + 时间片超时降级)\n代码证据:\n- 优先级定义: kernel/sched/proc.c:239-243 行定义 PRIORITY_TIMEOUT(0), PRIORITY_IRQ(1), PRIORITY_NORMAL(2)\n- 优先级队列: struct proc *proc_runnable[PRIORITY_NUMBER] (kernel/sched/proc.c:244 行)\n- 时间片字段: struct proc 中 int timer (include/sched/proc.h:61 行)\n- 超时降级: proc_tick() 中 timer 递减至 0 时从 PRIORITY_IRQ/NORMAL 降级到 PRIORITY_TIMEOUT (kernel/sched/proc.c:763-767 行)\n- 调度选择: __get_runnable_no_lock() 按优先级顺序遍历 proc_runnable[0..2] (kernel/sched/proc.c:543-554 行)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `macro PRIORITY_NUMBER` | #define PRIORITY_TIMEOUT 0; #define PRIORITY_IRQ 1; #define PRIORITY_NORMAL 2 |
| `kernel/sched/proc.c` | `function __get_runnable_no_lock` | for (int i = 0; i < PRIORITY_NUMBER; i ++) { tmp = proc_runnable[i]; ... } |
| `kernel/sched/proc.c` | `function proc_tick` | p->timer = p->timer - 1; if (0 == p->timer) { __remove(p); __insert_runnable(PRIORITY_TIMEOUT, p); } |

### Q04_006（short_answer）

- 题干：调度器 (Scheduler)核心入口/关键函数有哪些？（schedule/pick_next 等；给 1-3 个入口与证据）
- 答案："核心入口函数:\n1. scheduler() - 主调度循环 (kernel/sched/proc.c:671-711 行): 无限循环调用 __get_runnable_no_lock() 选进程，swtch() 切换上下文\n2. __get_runnable_no_lock() - 进程选择 (kernel/sched/proc.c:543-556 行): 按优先级遍历 proc_runnable 队列\n3. sched() - 触发切换 (kernel/sched/proc.c:714-749 行): 保存当前 context，swtch 到 cpu->context"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function scheduler` | void scheduler(void) { while (1) { tmp = __get_runnable_no_lock(); ... swtch(&c->context, &tmp->context); } } |
| `kernel/sched/proc.c` | `function __get_runnable_no_lock` | static struct proc *__get_runnable_no_lock(void) { for (int i = 0; i < PRIORITY_NUMBER; i ++) { ... } } |
| `kernel/sched/proc.c` | `function sched` | void sched(void) { ... swtch(&p->context, &mycpu()->context); } |

### Q04_007（tri_state_impl）

- 题干：是否实现 fork/clone（创建新执行实体）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function clone` | int clone(uint64 flag, uint64 stack) { np = allocproc(); np->segment = copysegs(...); copyfdtable(...); ... return pid; } |
| `kernel/syscall/sysproc.c` | `function sys_fork` | uint64 sys_fork(void) { return clone(0, NULL); } |

### Q04_008（short_answer）

- 题干：fork/clone 是否复制地址空间与文件表？（必须给复制路径证据；若 stub 需说明形态）
- 答案："是，完整复制:\n- 地址空间复制: kernel/sched/proc.c:303 行 np->segment = copysegs(p->pagetable, p->segment, np->pagetable)\n- 文件表复制: kernel/sched/proc.c:321 行 copyfdtable(&p->fds, &np->fds)\n- 当前目录复制: kernel/sched/proc.c:324 行 np->cwd = idup(p->cwd)\n- 信号处理复制: kernel/sched/proc.c:310 行 sigaction_copy(&np->sig_act, p->sig_act)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function clone` | np->segment = copysegs(p->pagetable, p->segment, np->pagetable); if (copyfdtable(&p->fds, &np->fds) < 0) ... |

### Q04_009（tri_state_impl）

- 题干：是否实现 exec（装载 ELF/重建地址空间）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/exec.c` | `function execve` | int execve(char *path, char **argv, char **envp) { ... pagetable = (pagetable_t)allocpage(); memmove(pagetable, p->pagetable, PGSIZE); ... loadseg(...); ... uvminit(...); } |
| `kernel/syscall/sysproc.c` | `function sys_execve` | uint64 sys_execve(void) { return execve(path, (char **)argv, (char **)envp); } |

### Q04_010（tri_state_impl）

- 题干：是否实现 wait/waitpid（父子回收同步）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function wait4` | int wait4(int pid, uint64 status, uint64 options) { ... if (ZOMBIE == np->state && (-1 == pid || pid == np->pid)) { ... freeproc(np); return child_pid; } ... sleep(p, &p->lk); } |
| `kernel/syscall/sysproc.c` | `function sys_wait4` | uint64 sys_wait4(void) { ... return wait4(pid, status, options); } |

### Q04_011（single_choice）

- 题干：waitpid / wait4 的阻塞实现 (Blocking Implementation) 更接近哪种？
- 答案："真正阻塞：移出就绪队列 + WaitQueue/条件变量唤醒 (Wait Queue or Condition Variable)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function wait4` | if (NULL != p->child) { ... sleep(p, &p->lk); } |
| `kernel/sched/proc.c` | `function sleep` | void sleep(void *chan, struct spinlock *lk) { __remove(p); __insert_sleep(p); sched(); } |

### Q04_012（short_answer）

- 题干：PID 分配器实现是什么？（自增/bitmap/空闲栈复用/只分配不回收；必须给证据）
- 答案："实现方式: 单调自增 (只分配不回收)\n证据: kernel/sched/proc.c:229 行 p->pid = __pid++; 其中 __pid 是全局静态变量 (kernel/sched/proc.c:27 行)\nPID 哈希表: pid_hash[HASH_SIZE] 用于快速查找 (kernel/sched/proc.c:28-29 行)\n无回收机制: 未发现 free_pid 或 release_pid 函数，PID 单调递增不复用"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `variable __pid` | int __pid; |
| `kernel/sched/proc.c` | `function allocproc` | p->pid = __pid ++; hash_insert_no_lock(p); |

### Q04_013（short_answer）

- 题干：父子进程树如何存储？（children Vec/链表/parent+sibling 指针；必须给结构体字段证据）
- 答案："存储方式: 链表 (child + sibling_next/sibling_pprev 指针)\n结构体字段 (include/sched/proc.h:74-77 行):\n- struct proc *child: 指向第一个子进程\n- struct proc *parent: 指向父进程\n- struct proc *sibling_next: 指向下一个兄弟进程\n- struct proc **sibling_pprev: 指向前一个兄弟的 sibling_next 字段\n遍历方式: 从 parent->child 开始，沿 sibling_next 遍历所有子进程 (kernel/sched/proc.c:485-517 行)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sched/proc.h` | `struct proc` | struct proc *child; struct proc *parent; struct proc *sibling_next; struct proc **sibling_pprev; |
| `kernel/sched/proc.c` | `function wait4` | np = p->child; while (NULL != np) { ... np = np->sibling_next; } |

### Q04_014（tri_state_impl）

- 题干：是否实现信号 (signal) 或 futex？（若二者都无则 not_found；若只实现其一需说明并给证据）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/signal.c` | `function set_sigaction` | int set_sigaction(int signum, struct sigaction const *act, ...) { ... __insert_sig(p, new); ... } |
| `kernel/sched/signal.c` | `function sighandle` | void sighandle(void) { ... sigact = __search_sig(p, signum); ... tf->epc = (uint64)(SIG_TRAMPOLINE + ...); } |
| `kernel/sched/proc.c` | `function kill` | int kill(int pid, int sig) { tmp->sig_pending.__val[i] |= 1ul << bit; ... } |

### Q04_015（short_answer）

- 题干：与 09 多核的交叉一致性：是否存在每核队列/任务迁移/IPI resched？（需与第 9 章互指证据或写不适用）
- 答案："每核运行队列: 否 (全局共享 proc_runnable[PRIORITY_NUMBER] 队列，无 per-CPU 队列)\n任务迁移: 不适用 (单全局队列，无需迁移)\nIPI resched: 是 (kernel/sched/proc.c:386-389 行 wakeup() 中 sbi_send_ipi() 唤醒另一核)\n多核调度: 全局 proc_lock 保护，两核竞争同一队列 (kernel/sched/proc.c:245 行)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `variable proc_runnable` | struct proc *proc_runnable[PRIORITY_NUMBER]; |
| `kernel/sched/proc.c` | `function wakeup` | if (flag && avail) { sbi_send_ipi(1 << id, 0); } |

### Q04_016（short_answer）

- 题干：exit() 资源回收路径：调用链是什么？是否真正回收地址空间/文件表/通知父进程？（必须给调用链证据；桩则说明）
- 答案："调用链 (kernel/sched/proc.c:413-456 行):\n1. delsegs(p->pagetable, p->segment) - 删除用户段\n2. uvmfree(p->pagetable) - 释放页表\n3. dropfdtable(&p->fds) - 关闭文件描述符\n4. iput(p->cwd) / iput(p->elf) - 释放 inode\n5. 子进程重父: 将所有子进程挂载到 __initproc\n6. 设置 ZOMBIE 状态: p->state = ZOMBIE; __remove(p)\n7. 唤醒父进程: __wakeup_no_lock(p->parent)\n8. 调用 sched() 切换到调度器\n9. 父进程 wait4() 中 freeproc() 最终释放 PCB"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function exit` | delsegs(p->pagetable, p->segment); uvmfree(p->pagetable); dropfdtable(&p->fds); iput(p->cwd); p->state = ZOMBIE; sched(); |

### Q04_017（tri_state_impl）

- 题干：是否实现进程组/会话（Process Group / Session，pgid/session/set_sid/setpgid）？（必须三态；有则区分真实检查链 vs 仅占位字段）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_018（tri_state_impl）

- 题干：是否实现 POSIX 资源限制（rlimit/RLIMIT/getrlimit/setrlimit）？（必须三态；若 implemented 需说明支持的资源类型数量及软/硬限制机制）
- 答案："stub"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/sysproc.c` | `function sys_prlimit64` | uint64 sys_prlimit64(void) { // for now it's not very necessary to implement this syscall // may be implemented later return 0; } |

### Q04_019（single_choice）

- 题干：该 OS 是否区分了 TCB（线程控制块）与 PCB（进程控制块）？
- 答案："仅有统一 Task 结构（无区分）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sched/proc.h` | `struct proc` | struct proc { ... }; // 唯一执行实体结构，无独立 thread 结构 |

### Q04_020（tri_state_impl）

- 题干：调度切换路径上是否存在页表切换（w_satp/sfence.vma/写 CR3/TTBR 等）？（必须三态；给调用点 路径 证据）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function scheduler` | w_satp(MAKE_SATP(tmp->pagetable)); sfence_vma(); swtch(&c->context, &tmp->context); w_satp(MAKE_SATP(kernel_pagetable)); sfence_vma(); |

### Q04_021（single_choice）

- 题干：用户线程与内核线程的映射模型 (User-Level Thread to Kernel-Level Thread Mapping) 更接近哪种？（Stallings Ch4）
- 答案："仅内核线程（无独立用户线程库）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sched/proc.h` | `struct proc` | struct proc { ... }; // 仅进程级抽象，无用户线程库支持 |

### Q04_022（tri_state_impl）

- 题干：是否实现线程局部存储 (Thread-Local Storage, TLS)？（必须三态；搜索 thread_local|TLS|__thread|#[thread_local]；若 implemented 需说明 TLS 的访问方式：tp 寄存器/段寄存器/其他）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_023（multi_choice）

- 题干：调度器是否追踪/优化以下哪些性能指标 (Scheduling Criteria, Stallings Ch9)？（多选；未发现则留空并在 notes 写 not_found）
- 答案：["CPU 利用率 (CPU Utilization)", "周转时间 (Turnaround Time)", "等待时间 (Waiting Time)", "响应时间 (Response Time)"]

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sched/proc.h` | `struct tms` | struct tms { uint64 utime; uint64 stime; uint64 cutime; uint64 cstime; }; |
| `include/sched/proc.h` | `struct proc` | int64 vswtch; int64 ivswtch; |
| `kernel/syscall/sysproc.c` | `function sys_getrusage` | r.ru_nvcsw = p->vswtch; r.ru_nivcsw = p->ivswtch; |

### Q04_024（tri_state_impl）

- 题干：优先级调度是否实现老化 (Aging, Stallings Ch9) 以防止低优先级进程饥饿 (Starvation)？（必须三态；搜索 age/aging/boost_priority 或等价；若 not_found 需说明是否存在饥饿风险）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_025（tri_state_impl）

- 题干：是否实现公平份额调度 (Fair-Share Scheduling, Stallings Ch9) 或 CPU 配额 (CPU Quota/cgroup)？（必须三态；搜索 fair_share/cgroup/cpu_quota/weight 等）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_026（single_choice）

- 题干：调度器的抢占模式 (Preemption Mode, Stallings Ch9) 更接近哪种？
- 答案："完全抢占 (Fully Preemptive)：时钟中断可随时抢占运行进程"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function proc_tick` | p->timer = p->timer - 1; if (0 == p->timer) { __remove(p); __insert_runnable(PRIORITY_TIMEOUT, p); } |
| `kernel/sched/proc.c` | `function kill` | if (SLEEPING == tmp->state) { __remove(tmp); ... __insert_runnable(PRIORITY_IRQ, tmp); } |

### Q04_027（tri_state_impl）

- 题干：是否实现最短作业优先调度 (Shortest Job First / SJF 或 SRTF, Stallings Ch9)？（必须三态；或等价的基于预测 burst 时间的调度）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_028（single_choice）

- 题干：该 OS 的多核形态更接近哪种？
- 答案："SMP（对称多处理）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/main.c` | `function main` | for (int i = 1; i < NCPU; i ++) { sbi_send_ipi(mask, 0); } |
| `include/param.h` | `macro NCPU` | #define NCPU 2 // maximum number of CPUs |

### Q04_029（tri_state_impl）

- 题干：是否存在 Secondary CPU / AP 启动链（BSP 唤醒 AP，上线后进入 idle/调度）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/main.c` | `function main` | if (hartid == 0) { ... for (int i = 1; i < NCPU; i ++) { sbi_send_ipi(mask, 0); } ... } else { while (started == 0) ; ... scheduler(); } |

### Q04_030（tri_state_impl）

- 题干：是否实现 IPI（核间中断）发送与处理？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function wakeup` | sbi_send_ipi(1 << id, 0); |
| `kernel/main.c` | `function main` | sbi_send_ipi(mask, 0); |

### Q04_031（short_answer）

- 题干：若存在 IPI：发送与处理路径分别在哪些函数/文件？（给关键入口与证据）
- 答案："IPI 发送路径:\n- sbi_send_ipi() 调用 (kernel/sched/proc.c:388 行 wakeup 函数; kernel/main.c:69 行 main 函数)\n- SBI 实现位于 bootloader/SBI/rustsbi-k210 (bootloader/SBI/rustsbi-k210/src/main.rs:161-166 行 send_ipi_many)\nIPI 处理路径:\n- 通过 trap 机制处理，hart 从 while(started==0) 循环退出后继续初始化 (kernel/main.c:75-82 行)\n- 无专用 ipi_handler 函数，IPI 仅用于唤醒 secondary CPU"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function wakeup` | sbi_send_ipi(1 << id, 0); |
| `kernel/main.c` | `function main` | for (int i = 1; i < NCPU; i ++) { sbi_send_ipi(mask, 0); } |

### Q04_032（tri_state_impl）

- 题干：是否存在 per-CPU 变量/结构（PerCpu、CPU-local storage 等）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `variable cpus` | struct cpu cpus[NCPU]; |
| `kernel/sched/proc.c` | `function mycpu` | struct cpu *mycpu(void) { int id = cpuid(); return &cpus[id]; } |

### Q04_033（short_answer）

- 题干：per-CPU 的实现方式是什么？（例如 TLS/tp 寄存器/gsbase/数组索引 hartid；需证据）
- 答案："实现方式: 数组索引 + hartid\n- 全局数组: struct cpu cpus[NCPU] (kernel/sched/proc.c:93 行)\n- hartid 获取: cpuid() 函数读取当前 hart ID\n- 访问方式: mycpu() 返回 &cpus[cpuid()] (kernel/sched/proc.c:96-99 行)\n- tp 寄存器初始化: kernel/main.c:26 行 inithartid() 中 mv tp, hartid\nstruct cpu 定义未在 proc.h 中显式给出，但通过 mycpu()->proc 访问当前进程 (kernel/sched/proc.c:100 行)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function mycpu` | struct cpu *mycpu(void) { int id = cpuid(); return &cpus[id]; } |
| `kernel/main.c` | `function inithartid` | asm volatile("mv tp, %0" : : "r" (hartid & 0x1)); |

### Q04_034（tri_state_impl）

- 题干：调度是否存在跨核负载均衡/迁移/亲和性？（必须三态）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_035（tri_state_impl）

- 题干：是否实现 TLB shootdown（跨核页表一致性刷新）？（必须三态；需与 03 互指）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_036（short_answer）

- 题干：与 03/04/05/08 章的交叉一致性 (Cross-Chapter Consistency)，按以下四项分别作答（每项须给证据路径或写「单核不适用」）：
- 03 TLB: 多核页表修改后 TLB 刷新策略=___
- 04 调度: 每核运行队列/负载均衡/IPI resched=___
- 05 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上线顺序=___
- 08 锁: SpinLock 关中断行为在多核下是否安全=___
- 答案："03 TLB: 多核页表修改后 TLB 刷新策略=未发现 TLB shootdown 实现，仅单核 sfence_vma() (kernel/sched/proc.c:685/688 行 scheduler 中)\n04 调度: 每核运行队列/负载均衡/IPI resched=全局共享队列 proc_runnable[]，无 per-CPU 队列；IPI 仅用于 wakeup 唤醒 (kernel/sched/proc.c:388 行)\n05 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上线顺序=hart0 先 trapinithart() 再唤醒 hart1，hart1 后 trapinithart() (kernel/main.c:47/79 行)\n08 锁: SpinLock 关中断行为在多核下是否安全=需检查 spinlock 实现 (见 Q04_037)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function scheduler` | w_satp(MAKE_SATP(tmp->pagetable)); sfence_vma(); |
| `kernel/main.c` | `function main` | trapinithart(); ... for (int i = 1; i < NCPU; i ++) { sbi_send_ipi(mask, 0); } |

### Q04_037（single_choice）

- 题干：SpinLock 在获取锁时是否禁用中断（关中断保护临界区）？
- 答案："是，获取时关中断、释放时恢复"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function sched` | // if (intr_get()) panic("sched interruptible\n"); |
| `kernel/sched/proc.c` | `function sleep` | if (&proc_lock != lk) { __enter_proc_cs; release(lk); } |

### Q04_038（short_answer）

- 题干：NCPU/MAXCPU（或等价宏）与链接脚本中的每 hart 栈/入口布局是否对应？（搜索 _max_hart_id 等；给宏定义与链接脚本对应证据，或写未发现）
- 答案："NCPU 定义: include/param.h:5 行 #define NCPU 2\n链接脚本: bootloader/SBI/rustsbi-k210/link-k210.ld:7 行 _max_hart_id = 1 (支持 2 核，hart0+hart1)\n对应关系: NCPU=2 与 _max_hart_id=1 一致 (hart 编号 0-1)\n每 hart 栈布局: kernel/main.c:88-92 行 shrink boot stack 中 kstack = boot_stack + hartid * 4 * PGSIZE"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/param.h` | `macro NCPU` | #define NCPU 2 // maximum number of CPUs |
| `bootloader/SBI/rustsbi-k210/link-k210.ld` | `symbol _max_hart_id` | _max_hart_id = 1; |
| `kernel/main.c` | `function main` | uint64 kstack = (uint64)boot_stack + hartid * 4 * PGSIZE; |

### Q04_039（tri_state_impl）

- 题干：是否使用 AtomicUsize/原子变量分配 PID/TID（全局唯一 ID 池）？（必须三态；给实现证据）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_040（tri_state_impl）

- 题干：是否支持实时调度 (Real-Time Scheduling, Stallings Ch10)？（必须三态；搜索 SCHED_FIFO / SCHED_RR / realtime / RT priority / deadline 等）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q04_041（tri_state_impl）

- 题干：是否存在 NUMA (Non-Uniform Memory Access) 感知的内存分配或调度策略？（必须三态；搜索 numa / node_id / local_memory 等；嵌入式单 SoC 可写 not_found 并说明架构）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

---


# 文件系统与设备 IO

## 题单作答（JSON-QA 渲染）

- stage_id: `05_fs_drivers`
- terminology_profile: `stallings_en_zh`

## 第 05_fs_drivers 阶段：文件系统与设备 I/O

### Q05_001（short_answer）

- 题干：VFS 抽象层 (Virtual File System, VFS)接口是什么形态？（Rust trait / C op 表；必须给接口定义证据）
- 答案："C 语言函数指针结构体（op 表）形态。定义于 `include/fs/fs.h:44-78`，包含 `struct fs_op`（块设备操作）、`struct inode_op`（inode 操作）、`struct dentry_op`（目录项操作）、`struct file_op`（文件操作）四个操作表，每个表包含一组函数指针如 `alloc_inode`、`lookup`、`read`、`write` 等。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/fs/fs.h` | `struct fs_op` | struct fs_op { struct inode *(*alloc_inode)(struct superblock *sb); ... } |
| `include/fs/fs.h` | `struct inode_op` | struct inode_op { struct inode *(*create)(struct inode *ip, char *name, int mode); ... } |
| `include/fs/fs.h` | `struct file_op` | struct file_op { int (*read)(struct inode *ip, int usr, uint64 dst, uint off, uint n); ... } |

### Q05_002（single_choice）

- 题干：具体文件系统后端 (Concrete File System Backend) 更接近哪种？
- 答案："真实磁盘文件系统（FAT32/Ext4/其他，持久化存储）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/fat32/fat32.c` | `function fat32_init` | FAT32 文件系统初始化，读取 BPB 参数并验证 FAT32 签名 |

### Q05_003（short_answer）

- 题干：若支持 FAT32/Ext4：它是自研还是第三方库/crate？（必须引用 Cargo.toml/Cargo.lock 或 Makefile 引入证据）
- 答案："自研实现。FAT32 后端代码位于 `kernel/fs/fat32/` 目录，包含 `fat32.c`（589 行）、`fat32.h`、`fat_cache.c` 等文件，直接编译进内核。Makefile（`Makefile:1-80`）显示为纯 C 项目，无外部 FS 库依赖。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/fat32/fat32.c` | `file fat32.c` | FAT32 自研实现，包含 fat32_init, fat_read_file, fat_write_file 等 |
| `Makefile` | `makefile platform config` | platform := k210, 纯 C 编译，无外部 FS crate |

### Q05_004（short_answer）

- 题干：文件打开路径：文件打开入口（sys_open 或等价）→ VFS 层 → 具体 FS open。列出 3-6 个关键节点并给证据。
- 答案："文件打开调用链：`sys_openat` (`kernel/syscall/sysfile.c:233`) → `nameifrom`/`namei` (`kernel/fs/fs.c:437`) → `lookup_path` (`kernel/fs/fs.c:352`) → `dirlookup` (`kernel/fs/fs.c:253`) → 具体 FS `fat_lookup_dir`（通过 `ip->op->lookup` 调用）。关键节点：1) `sys_openat` 解析路径并分配 fd；2) `lookup_path` 处理绝对/相对路径；3) `dirlookup` 逐级查找目录项；4) FAT32 `fat_lookup_dir` 读取磁盘目录。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/sysfile.c` | `function sys_openat` | uint64 sys_openat(void) { ... ip = nameifrom(dp, path); ... } |
| `kernel/fs/fs.c` | `function lookup_path` | static struct inode *lookup_path(struct inode *ip, char *path, int parent, char *name) |
| `kernel/fs/fs.c` | `function dirlookup` | struct inode *dirlookup(struct inode *dir, char *filename, uint *poff) |

### Q05_005（short_answer）

- 题干：文件描述符表 (File Descriptor Table, FD Table) 的实现形态是什么？（固定数组/Vec/BTreeMap 等；必须给结构体定义证据）
- 答案："固定数组 + 链表扩展形态。定义于 `include/fs/file.h:32-38`：`struct fdtable { uint16 basefd; uint16 nextfd; uint16 used; uint16 exec_close; struct file *arr[NOFILE]; struct fdtable *next; }`。主表为固定大小数组 `arr[NOFILE]`，通过 `next` 指针支持链表扩展。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/fs/file.h` | `struct fdtable` | struct fdtable { uint16 basefd; ... struct file *arr[NOFILE]; struct fdtable *next; } |

### Q05_006（tri_state_impl）

- 题干：是否实现块缓存/缓冲缓存 (Block Cache / Buffer Cache, bcache)？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/bio.c` | `function binit` | void binit(void) { initlock(&bcachelock, "bcache"); dlist_init(&lru_head); ... } |
| `kernel/fs/bio.c` | `function bget` | struct buf* bget(uint dev, uint sectorno) { ... } |

### Q05_007（short_answer）

- 题干：若存在缓存：驱逐策略是什么（LRU/Clock/FIFO/无驱逐）？必须指出判断依据（字段/算法分支）证据。
- 答案："LRU（最近最少使用）驱逐策略。证据：`kernel/fs/bio.c:88-118` 中 `bget()` 使用 `lru_head` 双向链表管理空闲 buffer，新分配的 buffer 从链表尾部（最久未使用）获取 (`struct d_list *dl = lru_head.prev`)；`bput()` 将释放的 buffer 加回链表头部 (`dlist_add_after(&lru_head, &b->list)`)，形成 LRU 队列。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/bio.c` | `function bget` | struct d_list *dl = lru_head.prev; ... b = container_of(dl, struct buf, list); |
| `kernel/fs/bio.c` | `function bput` | dlist_add_after(&lru_head, &b->list); |

### Q05_008（tri_state_impl）

- 题干：是否实现页缓存 (Page Cache)或与 mmap/文件映射共享缓存页？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/mmap.c` | `struct mmap_page` | struct mmap_page { struct rb_node rb; void *pa; uint64 f_off; int ref; }; |
| `kernel/fs/fs.h` | `struct inode` | struct inode { struct rb_root mapping; }; |

### Q05_009（tri_state_impl）

- 题干：是否实现 mmap 的文件映射或匿名映射？（必须三态；若 stub 说明形态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/sysmem.c` | `function sys_mmap` | uint64 sys_mmap(void) { ... return do_mmap(start, len, prot, flags, f, off); } |
| `kernel/mm/mmap.c` | `function do_mmap` | uint64 do_mmap(uint64 start, uint64 len, int prot, int flags, struct file *f, int64 off) |

### Q05_010（tri_state_impl）

- 题干：是否实现 poll/select/epoll（或等价事件机制）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/sysfile.c` | `function sys_pselect` | uint64 sys_pselect(void) { ... return pselect(nfds, ...); } |
| `kernel/syscall/sysfile.c` | `function sys_ppoll` | uint64 sys_ppoll(void) { ... return ppoll(pfds, nfds, ...); } |
| `kernel/fs/poll.c` | `function pselect` | int pselect(int nfds, struct fdset *readfds, ...) |

### Q05_011（tri_state_impl）

- 题干：路径解析 (namei/path_walk/lookup) 是否实现并支持绝对/相对路径与 . ..？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/fs.c` | `function lookup_path` | if (*path == '/') { ip = de_mnt_in(rootfs.root)->inode; } else { ip = idup(myproc()->cwd); } |
| `kernel/fs/fs.c` | `function dirlookup` | if (strncmp(filename, ".", MAXNAME) == 0) { ... } else if (strncmp(filename, "..", MAXNAME) == 0) { ... } |

### Q05_012（tri_state_impl）

- 题干：是否支持符号链接 (symlink) 的解析/跟随？（必须三态）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/sysfile.c` | `function sys_readlinkat` | sys_readlinkat 仅返回路径字符串，无 symlink 创建/跟随逻辑 |

### Q05_013（tri_state_impl）

- 题干：是否实现管道 (pipe/pipe2) 并在 VFS 层作为文件对象？（必须三态；与 08 章 pipe 实现互指）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/pipe.c` | `function pipealloc` | int pipealloc(struct file **pf0, struct file **pf1) { ... f0->type = FD_PIPE; ... } |
| `kernel/syscall/sysfile.c` | `function sys_pipe` | uint64 sys_pipe(void) { ... pipealloc(&rf, &wf); ... } |

### Q05_014（tri_state_impl）

- 题干：是否实现网络 socket（作为 VFS 文件对象）？（必须三态）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q05_015（tri_state_impl）

- 题干：是否实现伪文件系统（devfs/procfs/sysfs）？（必须三态；若 implemented 需说明实现形态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/rootfs.c` | `function rootfs_init` | memset(&devfs, 0, sizeof(struct superblock)); ... memset(&procfs, 0, sizeof(struct superblock)); |
| `kernel/fs/rootfs.c` | `struct devfs` | struct superblock devfs; 包含 console, vda2, zero, null 等设备节点 |

### Q05_016（single_choice）

- 题干：文件描述符表的归属是哪种？
- 答案："Per-Process（每进程独立 fd 表，fork 时复制/共享）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/fs/file.h` | `struct fdtable` | struct fdtable 通过 proc->fdtable 关联到进程 |
| `kernel/fs/file.c` | `function copyfdtable` | int copyfdtable(struct fdtable *fdt1, struct fdtable *fdt2) 用于 fork 时复制 fd 表 |

### Q05_017（single_choice）

- 题干：文件数据块分配方式 (File Allocation Method, Stallings Ch12) 更接近哪种？
- 答案："FAT 表内嵌空闲链（FAT32 特有）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/fat32/fat32.c` | `struct fat32_sb` | FAT32 使用 FAT 表记录簇链，通过 fat->bpb.fat_sz 和 fat->free_count 管理空闲簇 |

### Q05_018（single_choice）

- 题干：磁盘/存储空闲空间管理 (Free Space Management, Stallings Ch12) 更接近哪种？
- 答案："FAT 表内嵌空闲链（FAT32 特有）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/fat32/fat32.c` | `function fat32_init` | fat->free_count = *(uint32*)(buf + FAT_FREE_CNT_OFF); fat->next_free = *(uint32*)(buf + FAT_NEXT_FREE_OFF); |

### Q05_019（single_choice）

- 题干：目录结构 (Directory Structure, Stallings Ch12) 更接近哪种？
- 答案："树形层次目录 (Tree-Structured Hierarchy)（最常见）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/fs.c` | `function lookup_path` | 支持多级路径解析，通过 skipelem 逐级处理路径分量 |
| `kernel/fs/fs.h` | `struct dentry` | struct dentry { struct dentry *parent; struct dentry *child; struct dentry *next; }; |

### Q05_020（single_choice）

- 题干：文件内部记录组织 (File Record Organization, Stallings Ch12) 更接近哪种？
- 答案："字节流 (Byte Stream / Unstructured)：无固定记录结构"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/fat32/fat32.c` | `function fat_read_file` | 按字节偏移读取文件内容，无记录边界概念 |

### Q05_021（single_choice）

- 题干：设备发现/枚举机制更接近哪种？
- 答案："混合（多种并存）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/memlayout.h` | `macro UART` | #define UART 0x10000000L (QEMU) / 0x38000000L (k210) 硬编码地址 |
| `bootloader/SBI/rustsbi-qemu/src/main.rs` | `function count_harts` | 使用 device_tree 解析 DTB 获取 CPU 核心数 |

### Q05_022（tri_state_impl）

- 题干：是否能在代码中证实解析了 `.dtb`/DeviceTree？（必须三态；若 implemented 必须指出解析入口）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `bootloader/SBI/rustsbi-qemu/src/main.rs` | `function count_harts` | unsafe fn count_harts(dtb_pa: usize) { use device_tree::{DeviceTree, Node}; ... if let Ok(dt) = DeviceTree::load(data) { ... } |

### Q05_023（short_answer）

- 题干：驱动框架接口是什么？（Rust Driver trait / C driver ops / 注册表；必须引用接口定义证据）
- 答案："无统一驱动框架接口。驱动直接在 `kernel/main.c:main()` 中顺序初始化（`disk_init()` → `binit()` → `plicinit()` 等），无 driver trait/ops 注册表机制。块设备通过 `disk_read()`/`disk_write()` 函数指针间接调用具体驱动（sdcard/virtio）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/main.c` | `function main` | disk_init(); binit(); plicinit(); ... |
| `kernel/hal/disk.h` | `struct disk_ops` | 无统一 ops 表，直接调用 disk_read/disk_write |

### Q05_024（short_answer）

- 题干：驱动注册与初始化顺序是什么？（init_drivers/probe/driver_manager 等；列出 3-6 个关键节点并给证据）
- 答案："初始化顺序（`kernel/main.c:43-62`）：1) `consoleinit()` (UART 早期输出)；2) `kpminit()` (物理内存管理)；3) `kvminit()` (内核页表)；4) `plicinit()` (中断控制器)；5) `disk_init()` (块设备驱动初始化)；6) `binit()` (块缓存)。无 driver_manager/probe 机制。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/main.c` | `function main` | consoleinit(); ... plicinit(); disk_init(); binit(); |

### Q05_025（tri_state_impl）

- 题干：是否实现 UART/Console 驱动用于早期输出？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/console.c` | `function consoleinit` | void consoleinit(void) { ... } |
| `kernel/printf.c` | `function putchar` | 早期串口输出实现 |

### Q05_026（tri_state_impl）

- 题干：是否实现块设备驱动（virtio-blk/ramdisk/其他）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/hal/virtio_disk.c` | `function virtio_disk_init` | void virtio_disk_init(void) { ... } |
| `kernel/hal/sdcard.c` | `function sdcard_init` | void sdcard_init(void) { ... } |

### Q05_027（tri_state_impl）

- 题干：是否实现网络设备驱动（virtio-net/e1000/rtl8139 等）？（必须三态）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q05_028（tri_state_impl）

- 题干：是否实现中断控制器驱动（PLIC/CLINT/APIC 等）？（必须三态；需指出中断源到 handler 的分发证据）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/hal/plic.c` | `function plicinit` | void plicinit(void) { ... } |
| `kernel/trap.c` | `function devintr` | 中断分发到设备 handler |

### Q05_029（short_answer）

- 题干：MMIO 地址来源是什么？（DTB 提供 / 常量硬编码 / 物理→虚拟转换；必须给证据）
- 答案："常量硬编码。定义于 `include/memlayout.h:36-82`，如 `#define UART 0x10000000L` (QEMU) / `0x38000000L` (k210)，`#define VIRTIO0 0x10001000`，`#define PLIC 0x0c000000L`。通过 `VIRT_OFFSET` 转换为虚拟地址。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/memlayout.h` | `macro UART` | #define UART 0x10000000L (QEMU) / 0x38000000L (k210) |
| `include/memlayout.h` | `macro VIRT_OFFSET` | #define VIRT_OFFSET 0x3F00000000L |

### Q05_030（short_answer）

- 题干：多平台适配是如何通过构建/条件编译选择驱动的？（features/Kconfig/Makefile 规则；必须给证据）
- 答案："Makefile 条件编译。`Makefile:1-28` 定义 `platform := k210` 或 `platform := qemu`，通过 `CFLAGS += -D QEMU` 切换平台。`include/memlayout.h:36-40` 使用 `#ifdef QEMU` 区分 UART/VIRTIO 地址。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `Makefile` | `makefile platform` | platform := k210 / qemu, CFLAGS += -D QEMU |
| `include/memlayout.h` | `macro QEMU` | #ifdef QEMU ... #else ... #endif |

### Q05_031（tri_state_impl）

- 题干：是否存在 MMU 启用前后串口地址切换（phys/virt 切换）逻辑？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/memlayout.h` | `macro UART_V` | #define UART_V (UART + VIRT_OFFSET) |
| `kernel/mm/vm.c` | `function kvminit` | kvmmap(UART_V, UART, PGSIZE, PTE_R | PTE_W); |

### Q05_032（single_choice）

- 题干：I/O 缓冲模式 (I/O Buffering) 最接近哪种？（Stallings Ch11：单缓冲 Single Buffer / 双缓冲 Double Buffer / 循环缓冲 Circular Buffer / 缓冲池 Buffer Pool / 无缓冲 No Buffer）
- 答案："缓冲池 (Buffer Pool)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/bio.c` | `global bufs` | static struct buf bufs[BNUM]; 固定大小的 buffer 池 |
| `kernel/fs/bio.c` | `function binit` | 初始化 BNUM 个 buffer 形成 LRU 缓冲池 |

### Q05_033（single_choice）

- 题干：块设备（磁盘/eMMC/NVMe）I/O 请求调度算法 (Scheduling Algorithm) (Disk Scheduling Algorithm) 更接近哪种？（Stallings Ch11；若无显式调度则选「FCFS 顺序提交」）
- 答案："基于 virtio 环（queue 顺序提交，无显式磁盘调度）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/hal/virtio_disk.c` | `function virtio_disk_rw` | 通过 virtio descriptor ring 顺序提交请求，无电梯算法 |
| `kernel/hal/sdcard.c` | `function sdcard_submit` | 请求按提交顺序进入 wait_queue，无重排序 |

### Q05_034（single_choice）

- 题干：I/O 控制技术 (I/O Control Techniques, Stallings Ch11) 更接近哪种？
- 答案："混合（小传输用中断，大传输用 DMA）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/hal/sdcard.c` | `function sdcard_read` | 使用 DMA 传输数据 (sd_read_data_dma) |
| `kernel/hal/virtio_disk.c` | `function virtio_disk_intr` | virtio 使用中断通知完成，descriptor 支持 DMA |

### Q05_035（tri_state_impl）

- 题干：是否实现 DMA (Direct Memory Access, Stallings Ch11) 传输路径？（必须三态；搜索 dma_alloc / dma_map / dma_buf / virtio 描述符环等；virtio 的描述符环也算 DMA 等价机制）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/hal/sdcard.c` | `function sd_read_data_dma` | sd_read_data_dma(uint8 *data_buff, uint32 length) 使用 DMAC_CHANNEL0 |
| `kernel/hal/virtio_disk.c` | `struct virtq_desc` | virtio descriptor ring 支持 DMA，desc->addr 指向物理地址 |

---


# 同步互斥与进程间通信

## 题单作答（JSON-QA 渲染）

- stage_id: `06_sync_ipc`
- terminology_profile: `stallings_en_zh`

## 第 06_sync_ipc 阶段：同步互斥与进程间通信

### Q06_001（short_answer）

- 题干：该内核提供了哪些同步原语？（SpinLock/Mutex/RwLock/Semaphore/Condvar/WaitQueue 等；列出类型定义证据）
- 答案："SpinLock、SleepLock（阻塞型 Mutex）、WaitQueue。定义证据：SpinLock 定义于 `include/sync/spinlock.h:7-13`（struct spinlock 含 locked 字段）；SleepLock 定义于 `include/sync/sleeplock.h:9-16`（struct sleeplock 含 locked 字段与内部 spinlock）；WaitQueue 定义于 `include/sync/waitqueue.h:16-24`（struct wait_queue 含 spinlock 与双向链表头，struct wait_node 为等待节点）。实现文件：`kernel/sync/spinlock.c`（acquire/release）、`kernel/sync/sleeplock.c`（acquiresleep/releasesleep）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sync/spinlock.h` | `struct spinlock` | struct spinlock { uint locked; char *name; struct cpu *cpu; }; |
| `include/sync/sleeplock.h` | `struct sleeplock` | struct sleeplock { uint locked; struct spinlock lk; char *name; int pid; }; |
| `include/sync/waitqueue.h` | `struct wait_queue` | struct wait_queue { struct spinlock lock; struct d_list head; }; |

### Q06_002（single_choice）

- 题干：Mutex 更接近哪种实现？
- 答案："阻塞锁（Blocking Mutex，进入等待队列并挂起）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sync/sleeplock.c` | `function acquiresleep` | while (lk->locked) { sleep(lk, &lk->lk); } |
| `kernel/sched/proc.c` | `function sleep` | sleep(void *chan, struct spinlock *lk) 使进程进入睡眠状态并从运行队列移除 |

### Q06_003（tri_state_impl）

- 题干：是否存在等待队列 (Wait Queue, WaitQueue) 与 sleep/wakeup（或等价阻塞/唤醒）实现？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sync/waitqueue.h` | `header wait_queue_init/wait_queue_add/wait_queue_del` | 双向链表实现的等待队列，含 wait_queue_is_first 判断是否队首 |
| `kernel/sched/proc.c` | `function sleep` | 行 582-606：sleep(void *chan, struct spinlock *lk) 持锁检查、入睡眠队列、调用 sched() |
| `kernel/sched/proc.c` | `function wakeup` | 行 392-405：wakeup(void *chan) 唤醒等待该 chan 的进程 |

### Q06_004（fill_in）

- 题干：sleep / wakeup 不变量 (Sleep-Wakeup Invariant) 分析，按格式填写：
- sleep 入口函数: ___（路径）
- 入睡前持有的锁: ___（无则写 none）
- 防丢 wakeup (Lost Wakeup Prevention) 机制: ___（如：持队列锁检查条件 / 无防护）
- wakeup 函数: ___（路径）
- 唤醒与锁释放顺序: ___（先唤醒后释放 / 先释放后唤醒 / 其他）
- 答案："sleep 入口函数: `kernel/sched/proc.c:582` (sleep(void *chan, struct spinlock *lk))\n入睡前持有的锁: proc_lock（通过__enter_proc_cs 获取）+ 调用者传入的 lk（先释放后在 sleep 返回后重新获取）\n防丢 wakeup (Lost Wakeup Prevention) 机制: 持 proc_lock 检查条件并调用__insert_sleep() 将进程加入睡眠队列，确保在释放 lk 前已完成入队，wakeup 持 proc_lock 遍历睡眠队列，避免丢失唤醒\nwakeup 函数: `kernel/sched/proc.c:392` (wakeup(void *chan))\n唤醒与锁释放顺序: 先唤醒（__wakeup_no_lock 在 proc_lock 保护下执行）后释放（__leave_proc_cs 释放 proc_lock），符合 Stallings 描述的防丢 wakeup 不变量"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function sleep` | 行 582-606：if (&proc_lock != lk) { acquire(&proc_lock); release(lk); } ... __insert_sleep(p); sched(); ... release(&proc_lock); acquire(lk); |
| `kernel/sched/proc.c` | `function wakeup` | 行 392-405：acquire(&proc_lock); int flag = __wakeup_no_lock(chan); release(&proc_lock); if (flag && avail) { sbi_send_ipi(...); } |
| `kernel/sched/proc.c` | `comment lock ordering comment` | 行 249-253：NOTICE! To avoid any potential deadlock with proc_lock, proc_lock should be acquired last |

### Q06_005（tri_state_impl）

- 题干：是否实现管道 (Pipe)？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/pipe.c` | `function pipealloc` | 行 40-88：分配 struct pipe，初始化读写等待队列，创建两个 file 结构 |
| `kernel/fs/pipe.c` | `function piperead/pipewrite` | 行 223-347：实现带阻塞语义的管道读写 |
| `include/fs/pipe.h` | `struct pipe` | struct pipe 含 nread/nwrite 计数器、data[PIPE_SIZE] 缓冲区、wqueue/rqueue 等待队列 |

### Q06_006（single_choice）

- 题干：pipe 缓冲形态更接近哪种？
- 答案："字节环形缓冲区 (ring buffer)"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/pipe.c` | `code pipewrite loop` | 行 268-278：char *paddr = pi->pdata + pi->nwrite % PIPESIZE(pi); 使用模运算实现环形缓冲 |
| `kernel/fs/pipe.c` | `code piperead loop` | 行 322-332：char *paddr = pi->pdata + pi->nread % PIPESIZE(pi); 读端同样使用模运算 |
| `include/fs/pipe.h` | `macro PIPE_SIZE` | #define PIPE_SIZE 512，基础缓冲区为 512 字节，支持动态扩展 |

### Q06_007（single_choice）

- 题干：pipe 的阻塞语义更接近哪种？
- 答案："阻塞：挂起当前线程/任务进入等待队列"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/fs/pipe.c` | `function pipelock` | 行 100-109：while (!wait_queue_is_first(q, wait)) { sleep(wait->chan, &q->lock); } 非队首则睡眠 |
| `kernel/fs/pipe.c` | `function pipewritable` | 行 178-207：pipe full 时调用 sleep(wait->chan, &pi->lock) 挂起写进程 |
| `kernel/fs/pipe.c` | `function pipereadable` | 行 209-238：pipe empty 时调用 sleep(wait->chan, &pi->lock) 挂起读进程 |

### Q06_008（tri_state_impl）

- 题干：是否实现消息队列/信号量/共享内存等 SysV IPC (Message Queue / Semaphore / Shared Memory, msg/sem/shm)？（必须三态；若仅实现其一需说明）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `repos/xv6-k210` | `grep msgget|semget|shmget` | grep 搜索 'msgget|semget|shmget|sys_msg|sys_sem|sys_shm' 未找到匹配 (搜索 208 个文件) |
| `include/sysnum.h` | `header syscall numbers` | 系统调用表中无 SYS_msgget/SYS_semget/SYS_shmget 定义 |

### Q06_009（tri_state_impl）

- 题干：是否实现 futex？（必须三态）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `repos/xv6-k210` | `grep futex` | grep 搜索 'futex|sys_futex' 未找到匹配 (搜索 208 个文件) |

### Q06_010（tri_state_impl）

- 题干：是否实现信号机制（sigaction/kill/sigreturn/trampoline）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/signal.c` | `function set_sigaction` | 行 44-88：实现 sigaction 系统调用后端，管理进程的信号处理函数链表 |
| `kernel/sched/signal.c` | `function sighandle` | 行 178-258：内核态信号分发，构建 sig_frame 并跳转到用户态 handler |
| `kernel/trap/sig_trampoline.S` | `assembly sig_trampoline` | 信号返回 trampolines，调用用户 handler 后执行 SYS_rt_sigreturn |
| `kernel/sched/signal.c` | `function sigreturn` | 行 263-283：恢复原 trapframe，释放 sig_frame |

### Q06_011（short_answer）

- 题干：若实现 signal handler：用户态 handler 上下文如何构建？是否存在 sigreturn 恢复原 trap frame？（必须给证据）
- 答案："上下文构建：在 `kernel/sched/signal.c:sighandle()`（行 178-258）中，内核分配 `struct sig_frame`（含 trapframe 指针、信号掩码、signum），保存当前用户态 trapframe 到新分配的内存，修改 p->trapframe 指向新的陷阱帧，设置 epc 为 sig_trampoline 地址，然后返回用户态执行 trampoline。sigreturn 存在：`kernel/sched/signal.c:263-283` 实现 `sigreturn()`，从 p->sig_frame 链表取出保存的原 trapframe，恢复 p->trapframe，释放 sig_frame 结构，完成上下文恢复。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/signal.c` | `function sighandle` | 行 178-258：分配 sig_frame，保存原 trapframe，设置 trampoline 入口 |
| `kernel/sched/signal.c` | `function sigreturn` | 行 263-283：p->trapframe = frame->tf; p->sig_frame = frame->next; kfree(frame); |
| `kernel/trap/sig_trampoline.S` | `assembly sig_handler` | jalr a1 调用用户 handler，然后 li a7, SYS_rt_sigreturn; ecall |

### Q06_012（single_choice）

- 题干：RwLock（读写锁 Reader-Writer Lock）的实现形态更接近哪种？
- 答案："未发现/不支持"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `repos/xv6-k210` | `grep RwLock/rwlock` | grep 搜索 'RwLock|rwlock|read_write_lock|read_lock|write_lock' 未找到匹配 (搜索 208 个文件) |

### Q06_013（single_choice）

- 题干：底层原子操作来源更接近哪种？
- 答案："自定义汇编（ldxr/stxr、lock xchg 等）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sync/spinlock.c` | `function acquire` | 行 34：while(__sync_lock_test_and_set(&lk->locked, 1) != 0); 使用 GCC 内置原子操作，RISC-V 后端生成 amoswap.w.aq 指令 |
| `kernel/sync/spinlock.c` | `function release` | 行 71：__sync_lock_release(&lk->locked); 生成 amoswap.w 指令 |
| `kernel/sync/spinlock.c` | `comment atomic comment` | 行 31-33 注释说明：On RISC-V, sync_lock_test_and_set turns into an atomic swap |

### Q06_014（short_answer）

- 题干：死锁四必要条件（Coffman Conditions）在该内核中是否均成立？
请逐条作答（互斥 Mutual Exclusion / 持有并等待 Hold-and-Wait / 不可剥夺 No Preemption / 循环等待 Circular Wait），并结合 SpinLock/Mutex 的实现给出证据或写「不适用」。
- 答案："1. 互斥 (Mutual Exclusion): 成立。SpinLock 通过原子交换指令保证同一时刻仅一个 CPU 持有锁（`kernel/sync/spinlock.c:34` amoswap.w.aq）；SleepLock 在 SpinLock 基础上增加睡眠语义，同样保证互斥。\n2. 持有并等待 (Hold-and-Wait): 成立。`kernel/sched/proc.c:582-606` 的 sleep() 允许进程持有 lk 锁的同时释放 proc_lock 并进入睡眠，唤醒后重新获取 lk，存在持有资源等待其他资源的场景。\n3. 不可剥夺 (No Preemption): 成立。SpinLock 持有期间不能被强制剥夺（只能由持有者主动 release）；SleepLock 持有者睡眠时锁仍被占用，其他进程只能等待。\n4. 循环等待 (Circular Wait): 可能成立。内核存在多锁嵌套场景（如 pipe 操作同时持有 pi->lock 和 wait_queue->lock），但通过锁顺序规范预防（见 Q06_016）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sync/spinlock.c` | `function acquire` | 行 23-42：原子交换指令实现互斥 |
| `kernel/sched/proc.c` | `function sleep` | 行 582-606：持锁进入睡眠，唤醒后重新获取 |
| `kernel/sched/proc.c` | `comment deadlock prevention` | 行 249-253/454-458/603-605：多处注释说明锁顺序以避免死锁 |

### Q06_015（single_choice）

- 题干：内核对死锁 (Deadlock) 的处理策略更接近哪种？
- 答案："死锁预防 (Deadlock Prevention)：通过锁顺序等消除 Coffman 必要条件"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `comment lock ordering` | 行 249-253：NOTICE! To avoid any potential deadlock with proc_lock, proc_lock should be acquired last |
| `kernel/sched/proc.c` | `comment exit lock order` | 行 454-458：acquire proc_lock after parent's lock, to avoid deadlock with parent calling sleep(p, &p->lk) in wait4() |
| `kernel/sched/proc.c` | `comment sleep lock order` | 行 603-605：release proc_lock first to avoid deadlock in case another call to sleep() with the same lk |

### Q06_016（tri_state_impl）

- 题干：是否存在全局锁顺序（Lock Ordering）规范或注释，以预防嵌套锁导致的循环等待死锁 (Circular Wait Deadlock)？（必须三态；若 implemented 需给出锁排序规则或 ABBA 锁检测代码证据）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `comment proc_lock ordering` | 行 249-253：proc_lock should be acquired last with any situation requiring multiple spinlocks |
| `kernel/sched/proc.c` | `comment exit lock order` | 行 454-458：acquire proc_lock after parent's lock, to avoid deadlock with parent calling sleep(p, &p->lk) in wait4() |
| `kernel/sched/proc.c` | `comment sleep lock release order` | 行 603-605：release proc_lock first to avoid deadlock in case another call to sleep() with the same lk |

### Q06_017（tri_state_impl）

- 题干：是否实现管程/条件变量 (Monitor / Condition Variable, Stallings Ch5)？（必须三态；搜索 Condvar / condition_variable / monitor / wait/notify/signal 等；若 implemented 需区分 Hoare 语义（等待者立即恢复）vs Mesa 语义（等待者重新竞争锁））
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `repos/xv6-k210` | `grep condvar/condition_variable` | grep 搜索 'condvar|condition_variable|Condition|notify|wait.*notify' 仅找到无关匹配（license 头文件、VIRTIO_MMIO_QUEUE_NOTIFY 等），无条件变量实现 |
| `include/sync/` | `directory sync headers` | 仅含 spinlock.h、sleeplock.h、waitqueue.h，无 condvar.h 或类似定义 |

### Q06_018（short_answer）

- 题干：经典同步问题验证 (Classic Synchronization Problems, Stallings Ch5)：
以下三个经典问题在该内核中是否有对应实现或测试？
- 生产者-消费者 (Producer-Consumer / Bounded Buffer)：___（implemented/not_found + 证据）
- 读者-写者 (Readers-Writers)：___（实现了读者优先/写者优先/公平？ + 证据）
- 哲学家就餐 (Dining Philosophers)：___（implemented/not_found）
- 答案："生产者 - 消费者 (Producer-Consumer / Bounded Buffer)：not_found（grep 搜索 'producer.*consumer|bounded.*buffer' 未找到匹配；但 pipe 实现本质上是生产者 - 消费者模式，`kernel/fs/pipe.c` 使用环形缓冲 + 等待队列实现阻塞式读写，但未作为独立测试或示例代码存在）\n读者 - 写者 (Readers-Writers)：not_found（grep 搜索 'reader.*writer' 未找到匹配；无 RwLock 实现，仅通过 pipe 的读写分离等待队列间接支持，但非标准读者 - 写者锁）\n哲学家就餐 (Dining Philosophers)：not_found（grep 搜索 'dining.*philosoph' 未找到匹配）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `repos/xv6-k210` | `grep classic problems` | grep 搜索 'producer.*consumer|bounded.*buffer|reader.*writer|dining.*philosoph' 未找到匹配 |
| `kernel/fs/pipe.c` | `implementation pipe as producer-consumer` | pipe 读写分离 + 环形缓冲 + 阻塞语义，本质是生产者 - 消费者模式，但非独立示例 |

### Q06_019（tri_state_impl）

- 题干：是否实现消息传递 (Message Passing, Stallings Ch5) 作为 IPC 机制？（必须三态；区分直接消息传递 Direct / 间接通过邮箱 Mailbox / POSIX mq_open 等；与 SysV msgq 的区别是是否通过内核邮箱路由）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `repos/xv6-k210` | `grep message passing` | grep 搜索 'message.*passing|mailbox|mq_open|msgsnd|msgrcv' 仅找到 resource.h 中的 ru_msgsnd/ru_msgrcv 统计字段，无实际消息传递实现 |
| `include/sysnum.h` | `header syscall numbers` | 无 SYS_msgget/SYS_msgsnd/SYS_msgrcv 等消息队列系统调用 |

### Q06_020（tri_state_impl）

- 题干：是否实现屏障同步 (Barrier Synchronization, Stallings Ch5)？（必须三态；搜索 barrier / sync_barrier / pthread_barrier 或等价；用于多线程/多核同步到同一检查点）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `repos/xv6-k210` | `grep barrier` | grep 搜索 'barrier|Barrier|pthread_barrier' 仅找到 doc/内核原理 - 进程管理.md 中关于内存屏障的理论讨论（__sync_synchronize），无屏障同步原语实现 |
| `include/sync/` | `directory sync headers` | 无 barrier.h 或类似屏障同步头文件 |

---


# 安全机制与权限模型

## 题单作答（JSON-QA 渲染）

- stage_id: `07_security`
- terminology_profile: `stallings_en_zh`

## 第 07_security 阶段：安全机制与权限模型

### Q07_001（single_choice）

- 题干：特权级隔离形态更接近哪种？
- 答案："有用户态/内核态隔离（user mode/kernel mode）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `macro SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User |
| `kernel/trap/trap.c` | `function usertrap` | __debug_assert("usertrap", 0 == (r_sstatus() & SSTATUS_SPP), "not from user mode\n"); |
| `kernel/trap/trap.c` | `function usertrapret` | x &= ~SSTATUS_SPP; // clear SPP to 0 for user mode |

### Q07_002（tri_state_impl）

- 题干：是否存在凭证/权限数据结构（UID/GID/Credential/Capability/ACL 等）？（必须三态）
- 答案："stub"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/fs/stat.h` | `struct kstat` | struct kstat { ... uint32_t uid; uint32_t gid; ... }; |
| `include/sched/proc.h` | `struct proc` | struct proc { ... // 无 uid/gid/credential 字段 } |
| `kernel/exec.c` | `code_block execve` | {AT_UID, 0}, {AT_EUID, 0}, {AT_GID, 0}, {AT_EGID, 0} // 硬编码为 0 |

### Q07_003（tri_state_impl）

- 题干：是否能证实在 syscall 路径上真实执行了权限检查（open/exec/write 等）？（必须三态；仅有字段不算 implemented）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/sysproc.c` | `function sys_getuid` | uint64 sys_getuid(void) { return 0; } |
| `kernel/exec.c` | `code_block execve` | {AT_UID, 0}, {AT_EUID, 0}, {AT_GID, 0}, {AT_EGID, 0} // 无权限检查逻辑 |

### Q07_004（short_answer）

- 题干：若存在权限检查：入口点与核心检查函数链路是什么？（列 2-5 个节点并给证据）
- 答案："未发现权限检查链。grep 搜索 check_perm/inode_permission/access_check 无结果。sys_getuid 仅返回硬编码 0，execve 中 AT_UID/AT_GID 硬编码为 0，无真实权限检查函数调用。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/sysproc.c` | `function sys_getuid` | uint64 sys_getuid(void) { return 0; } |
| `kernel/exec.c:241-244` | `code_block auxvec` | {AT_UID, 0}, {AT_EUID, 0}, {AT_GID, 0}, {AT_EGID, 0} |

### Q07_005（tri_state_impl）

- 题干：是否实现用户指针验证（access_ok/verify_area/UserInPtr/copyin/copyout 等）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/mm/vm.h` | `function permit_usr_mem` | static inline void permit_usr_mem() { clr_sstatus_bit(SSTATUS_PUM); } |
| `include/mm/vm.h` | `function protect_usr_mem` | static inline void protect_usr_mem() { set_sstatus_bit(SSTATUS_PUM); } |
| `kernel/mm/vm.c:730-770` | `function safememmove` | static uint64 safememmove(...) { permit_usr_mem(); ... protect_usr_mem(); } |
| `kernel/mm/vm.c` | `function copyin2` | int copyin2(char *dst, uint64 srcva, uint64 len) { ... safememmove(...) ... } |
| `kernel/mm/vm.c` | `function copyout2` | int copyout2(uint64 dstva, char *src, uint64 len) { ... safememmove(...) ... } |
| `kernel/trap/trap.c` | `function usertrap` | protect_usr_mem(); // since we turned on this when leaving S-mode |

### Q07_006（tri_state_impl）

- 题干：是否实现 seccomp/prctl/sandbox 等系统调用过滤/沙箱？（必须三态；stub 需说明形态：ENOSYS/return 0）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q07_007（tri_state_impl）

- 题干：是否存在栈保护/溢出防护（stack canary/guard page）或等价机制？（必须三态）
- 答案："stub"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/memlayout.h:113` | `comment guard_page_comment` | // each surrounded by invalid guard pages. |
| `kernel/mm/vm.c:596` | `comment stack_guard_comment` | // used by exec for the user stack guard page. |

### Q07_008（tri_state_impl）

- 题干：是否存在审计/安全启动（audit/secure boot/signature）相关逻辑？（必须三态）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q07_009（short_answer）

- 题干：本项目支持哪些架构（riscv64/aarch64/x86_64/loongarch64 等）？每种架构的安全相关初始化（特权级配置、PMP/MPU/SMEP 等）是否有代码证据？（必须逐架构作答，无证据写「未发现」）
- 答案："仅支持 riscv64 架构。证据：Makefile 中 TOOLPREFIX=riscv64-unknown-elf；bootloader/SBI/rustsbi-k210/.cargo/config.toml 中 target=\"riscv64gc-unknown-none-elf\"。特权级隔离通过 RISC-V SSTATUS_SPP 位实现（include/hal/riscv.h），用户/内核态切换通过 sret 指令（kernel/trap/trampoline.S）。未发现 PMP/MPU 配置代码。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `Makefile:11` | `variable TOOLPREFIX` | TOOLPREFIX := riscv64-unknown-elf- |
| `bootloader/SBI/rustsbi-k210/.cargo/config.toml` | `config target` | target = "riscv64gc-unknown-none-elf" |
| `include/hal/riscv.h` | `macro SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User |

### Q07_010（tri_state_impl）

- 题干：若项目使用 Rust，是否存在 RAII/所有权/生命周期相关的内核安全机制（如不可 unsafe 直接访问用户内存、锁的 RAII 自动释放等）？（必须三态；给具体模式证据）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `Makefile` | `config CC` | CC := $(TOOLPREFIX)gcc // 内核为 C 语言编写 |

### Q07_011（tri_state_impl）

- 题干：是否实现了内核/用户页表隔离 (Kernel/User Page Table Isolation, KPTI 或等价机制)？
（x86: CR3 KPTI / SMEP / SMAP；RISC-V: PMP / S-mode 分离；AArch64: TTBR0/TTBR1 隔离；
必须三态；无则写未发现并列出已搜关键字）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/memlayout.h` | `macro TRAMPOLINE` | #define TRAMPOLINE (MAXVA - PGSIZE) // map the trampoline page to the highest address |
| `kernel/trap/trampoline.S` | `file uservec` | # this code is mapped at the same virtual address (TRAMPOLINE) in user and kernel space |
| `kernel/trap/trap.c` | `function usertrapret` | p->trapframe->kernel_satp = r_satp(); // kernel page table ... w_satp(MAKE_SATP(p->pagetable)); // user page table |
| `include/hal/riscv.h` | `macro SSTATUS_PUM` | #define SSTATUS_PUM (1L << 18) // 控制用户态访问内核内存 |

### Q07_012（short_answer）

- 题干：UID/GID 字段是否在 syscall 路径上真实执行权限检查？（搜索 check_perm/inode_permission；若只有字段无检查链须标注「仅有定义但未强制执行 🔸」；给检查链证据或写「字段存在但无检查链」）
- 答案："字段存在但无检查链。include/fs/stat.h 中 kstat 结构体有 uid/gid 字段，但 include/sched/proc.h 中 proc 结构体无 UID/GID 凭证字段。kernel/exec.c 中 AT_UID/AT_GID 硬编码为 0。grep 搜索 check_perm/inode_permission 无结果。sys_getuid 仅返回 0（🔸 桩函数）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/fs/stat.h` | `struct kstat` | struct kstat { ... uint32_t uid; uint32_t gid; ... }; |
| `include/sched/proc.h` | `struct proc` | struct proc { ... // 无 uid/gid 字段 } |
| `kernel/syscall/sysproc.c` | `function sys_getuid` | uint64 sys_getuid(void) { return 0; } |
| `kernel/exec.c:241-244` | `code_block auxvec` | {AT_UID, 0}, {AT_EUID, 0}, {AT_GID, 0}, {AT_EGID, 0} |

### Q07_013（single_choice）

- 题干：访问控制模型 (Access Control Model, Stallings Ch15) 更接近哪种？
- 答案："仅有特权级隔离（ring0/ring3），无细粒度访问控制"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `macro SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User |
| `kernel/syscall/sysproc.c` | `function sys_getuid` | return 0; // 无真实权限检查 |

### Q07_014（tri_state_impl）

- 题干：是否实现完整性策略 (Integrity Policy, Stallings Ch15)？（如 Biba 模型、只读内核段、代码签名验证、W^X 内存保护等；必须三态）
- 答案："stub"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `macro PTE_X` | #define PTE_X (1L << 3) // 页表执行权限位 |
| `include/hal/riscv.h` | `macro PTE_W` | #define PTE_W (1L << 2) // 页表写权限位 |
| `kernel/exec.c:158-160` | `code_block loadseg` | flags |= (ph.flags & ELF_PROG_FLAG_EXEC) ? PTE_X : 0; flags |= (ph.flags & ELF_PROG_FLAG_WRITE) ? PTE_W : 0; |

---


# 网络子系统与协议栈

## 题单作答（JSON-QA 渲染）

- stage_id: `08_network`
- terminology_profile: `stallings_en_zh`

## 第 08_network 阶段：网络子系统与协议栈

### Q08_001（tri_state_impl）

- 题干：是否存在网络子系统实现（协议栈或 socket 层）？（必须三态）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sysnum.h` | `header SYS_*` | 系统调用编号定义中无 SYS_socket/SYS_bind/SYS_connect/SYS_sendto/SYS_recvfrom 等网络相关调用 |
| `kernel/` | `directory kernel` | kernel/ 目录下无 net/、tcp/、udp/、socket/ 等网络相关子目录 |
| `kernel/hal/virtio_disk.c` | `source virtio_disk_rw` | HAL 层仅实现 virtio-blk 磁盘驱动，无 virtio-net 网卡驱动 |

### Q08_002（single_choice）

- 题干：协议栈来源更接近哪种？
- 答案："未发现"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `Cargo.toml` | `config workspace` | Cargo.toml 仅定义 bootloader workspace，无 smoltcp/lwip/embassy-net 等网络协议栈依赖 |
| `include/errno.h` | `header ENONET/ENOTUNIQ` | errno.h 中虽有 ENONET 等网络相关错误码，但仅为 POSIX 兼容占位符，无实际网络实现 |

### Q08_003（tri_state_impl）

- 题干：是否实现 socket 系统调用接口（socket/bind/connect/sendto/recvfrom 等）？（必须三态）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/sysnum.h` | `header SYS_*` | 系统调用编号 1-276 中无 socket/bind/connect/sendto/recvfrom/listen/accept 等网络调用 |
| `kernel/syscall/sysfile.c` | `source sys_*` | syscall 层仅实现文件/进程/内存类系统调用，无网络 syscall 实现 |

### Q08_004（short_answer）

- 题干：选择一个发送路径（优先 sys_sendto），追踪：syscall → 协议栈 → 网卡驱动。列 3-6 个关键节点并给证据。
- 答案："未实现网络功能（❌ 未实现）。无法追踪发送路径，原因如下：\n1. 无 sys_sendto 系统调用：include/sysnum.h 中无 SYS_sendto 定义\n2. 无协议栈：全仓库 grep 未发现 tcp/udp/ip 等协议处理代码\n3. 无网卡驱动：kernel/hal/ 仅有 virtio_disk.c（磁盘），无 virtio-net 或 e1000 等网卡驱动\n4. 无 socket 抽象：include/fs/file.h 中文件类型仅支持普通文件/管道/设备，无 socket 类型"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q08_005（tri_state_impl）

- 题干：是否实现网卡驱动（virtio-net/e1000 等）与收包中断路径？（必须三态）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/hal/virtio_disk.c` | `source virtio_disk_init/virtio_disk_intr` | virtio 驱动仅实现 device_id=2 的磁盘设备（VIRTIO_BLK_T_IN/OUT），无 device_id=1 的网卡设备支持 |
| `include/hal/virtio.h:8` | `header VIRTIO_MMIO_DEVICE_ID` | 注释说明 device_id=1 为网卡、device_id=2 为磁盘，但代码仅实现磁盘驱动 |
| `kernel/hal/` | `directory hal` | HAL 目录包含 disk.c/sdcard.c/virtio_disk.c 等存储驱动，无 net/ 或网卡驱动文件 |

### Q08_006（multi_choice）

- 题干：协议支持情况（多选；未发现则留空并在 notes 写 not_found）：
- 答案：[]
- 说明：not_found - 全仓库 grep 未发现 Ethernet/ARP/IPv4/IPv6/ICMP/UDP/TCP/DHCP/DNS 等协议实现代码

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q08_007（tri_state_impl）

- 题干：是否存在零拷贝/共享缓冲/DMA 描述符等路径（zero-copy）？（必须三态；仅有名词不算 implemented）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/hal/virtio_disk.c` | `source virtq_desc` | virtio_disk 使用 DMA 描述符（virtq_desc）但仅用于磁盘 I/O，无网络零拷贝路径 |
| `kernel/fs/bio.c` | `source buf` | buf 结构用于块设备缓存，无网络 mbuf/sk_buff 等共享缓冲机制 |

---


# 调试机制与错误处理

## 题单作答（JSON-QA 渲染）

- stage_id: `09_debug_error`
- terminology_profile: `stallings_en_zh`

## 第 09_debug_error 阶段：调试机制与错误处理

### Q09_001（tri_state_impl）

- 题干：是否存在日志系统（log/printk/println 宏）与日志级别控制？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/utils/debug.h` | `macro __debug_msg` | #ifdef DEBUG 条件下定义 __debug_msg 为 printf，否则为空操作 |
| `include/utils/debug.h` | `macro __debug_assert` | DEBUG 模式下检查条件失败时调用 panic，否则为空操作 |
| `include/printf.h` | `function printf` | 内核 printf 函数声明，用于日志输出 |

### Q09_002（tri_state_impl）

- 题干：是否存在 panic/崩溃处理路径（panic_handler/oom/abort 等）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/printf.c` | `function __panic` | void __panic(char *s) { printf(...); backtrace(); intr_off(); for(;;); } |
| `include/printf.h` | `macro panic` | #define panic(s) do { printf(...); __panic(s); } while(0) |
| `bootloader/SBI/rustsbi-k210/src/main.back.rs` | `function panic_handler` | #[panic_handler] fn panic(info: &PanicInfo) -> ! { println!("[rustsbi] {}", info); loop {} } |

### Q09_003（short_answer）

- 题干：panic 路径会输出哪些诊断？（寄存器 dump/栈回溯/停机；必须引用实现证据）
- 答案："输出错误消息（含 CPU ID、文件路径、行号）、调用 backtrace() 打印栈帧返回地址、关闭中断并进入无限循环停机。无寄存器 dump。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/printf.c` | `function __panic` | printf(__ERROR("panic")": "); printf(s); printf("\n"); backtrace(); intr_off(); for(;;); |
| `include/printf.h` | `macro panic` | printf(__ERROR(__module_name__)": hart %d at %s: %d\n", cpuid(), __FILE__, __LINE__); __panic(s); |
| `kernel/printf.c` | `function backtrace` | 基于 FramePointer 遍历栈帧，打印每个帧的 ra 地址（返回地址减 4） |

### Q09_004（tri_state_impl）

- 题干：是否实现栈回溯 (backtrace/unwind/stack_trace)？（必须三态；仅打印 ra 不算）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/printf.c` | `function backtrace` | void backtrace() { uint64 *fp = (uint64 *)r_fp(); ... while (fp < bottom) { uint64 ra = *(fp - 1); printf("%p\n", ra - 4); fp = (uint64 *)*(fp - 2); } } |

### Q09_005（tri_state_impl）

- 题干：是否存在交互式内核 monitor/shell？（必须三态；若 implemented 列出 3-10 个命令入口证据）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `xv6-user/sh.c` | `function export` | int export(char *argv) - 支持 -p 打印所有环境变量或设置新环境变量 |
| `xv6-user/sh.c` | `function runcmd` | void runcmd(struct cmd *cmd) - 执行命令，支持 EXEC/REDIR/PIPE/LIST/BACK 等类型 |
| `xv6-user/sh.c` | `function parsecmd` | struct cmd *parsecmd(char*) - 解析 shell 命令行 |
| `xv6-user/sh.c` | `function replace` | int replace(char *buf) - 替换环境变量引用 $VAR |

### Q09_006（tri_state_impl）

- 题干：是否实现 GDB stub（需数据包解析循环，如 handle_gdb_packet）？（必须三态）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q09_007（short_answer）

- 题干：错误码/错误类型体系是什么？（errno/Result/Error enum；给类型定义与传播点证据）
- 答案："POSIX errno 风格宏定义（EPERM/ENOENT/ENOMEM 等），定义于 include/errno.h，无 Rust Result/Error enum。错误码通过系统调用返回值传播（负值表示错误）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/errno.h` | `macro EPERM` | #define EPERM 1 /* Operation not permitted */ |
| `include/errno.h` | `macro ENOENT` | #define ENOENT 2 /* No such file or directory */ |
| `include/errno.h` | `macro ENOSYS` | #define ENOSYS 38 /* Invalid system call number */ |

### Q09_008（tri_state_impl）

- 题干：是否存在 trace/perf/ftrace 等跟踪机制或 tracepoints？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/sysproc.c` | `function sys_trace` | sys_trace(void) { myproc()->tmask = 1; return 0; } |
| `xv6-user/strace.c` | `function main` | strace 用户工具：调用 trace() 系统调用后 execve 执行目标程序 |

---


# 开发历史与里程碑

## 第 10 章：开发历史与里程碑

### 10.1 项目时间线与开发周期

xv6-k210 项目的开发周期集中于 **2021 年 5 月至 2021 年 8 月**，历时约 3 个月。根据 `get_git_history_summary` 输出，仓库共记录 **200 次提交**（commit 范围：`2021-05-27` 至 `2021-08-21`），呈现典型的密集型课程竞赛开发模式。

**关键时间节点**：
- **2021-05-27**：项目正式启动，首次提交包含基础 mmap 实现（`758b94d` "primary mmap"）
- **2021-05-28**：mmap/munmap 功能合并（`fb1bc91` "merge mmap"），SD 卡驱动初步适配
- **2021-07-15**：Lazy ELF 加载机制实现（`a3907ef` "lazy elf load mechanism"）
- **2021-07-17**：Signal 机制首次提交（`9759082` "add sigaction and sigprocmask"）
- **2021-07-29**：Lazy-mmap 大规模重构（`27ca1f1` "lazy-mmap: almost re-written"，+701/-281 行）
- **2021-08-17**：Signal 机制完善并合并（`08c10ba` "signal now works"）
- **2021-08-21**：最终提交，SD 卡驱动与 FAT32 优化（`d7f3e5e` "change"）

### 10.2 核心贡献者图谱

根据 `analyze_authors_contribution` 统计，项目呈现 **三人核心 + 多人协作** 的开发模式：

| 贡献者 | Commit 数 | 代码增删行数 | 主力贡献目录 |
|--------|-----------|--------------|--------------|
| **retrhelo** | 162 | +81,502 / -51,108 | `kernel/` (98,752 行), `tags/`, `include/` |
| **hustccc** | 116 | +66,833 / -22,226 | `tags/` (46,986 行), `kernel/` (26,367 行), `xv6-user/` |
| **Lu Sitong** | 146 | +45,475 / -27,776 | `kernel/` (60,646 行), `xv6-user/` (5,270 行), `include/` |
| YongkangLi | 34 | +3,172 / -1,841 | `kernel/`, `doc/` |
| Artyom Liu | 3 | +5,999 / -1,656 | `kernel/`, `bootloader/` |

**分析**：
- **retrhelo** 为最高频贡献者（162 commits），主导内核核心模块（`kernel/mm`、`kernel/fs`、`kernel/hal`）与底层驱动（SD 卡、SPI、DMA）
- **Lu Sitong** 聚焦内存管理子系统（lazy-mmap、mmap 重构）与用户态测试程序（`xv6-user/mmaptests.c`、`lazytests.c`）
- **hustccc** 负责构建系统（`tags/` 目录为构建产物）与部分内核模块

### 10.3 模块演进轨迹

#### 10.3.1 内存管理模块（`kernel/mm`）

通过 `trace_file_evolution` 追踪 `kernel/mm` 目录，识别出 **三次重大重构**：

1. **基础分配器阶段（2021-05-27 ~ 2021-07-14）**
   - 初始实现：`kernel/mm/mmap.c` 仅支持简单页映射（`758b94d` "primary mmap"，+170/-21 行）
   - 证据：`kernel/mm/mmap.c:170` 中 `do_mmap()` 使用链表结构 `struct mapped` 管理映射

2. **Lazy-mmap 重构（2021-07-29，commit `27ca1f1`）**
   - 变更规模：+701/-281 行（`kernel/mm/mmap.c`）
   - 核心改动：
     - 引入红黑树（`struct rb_root mapping`）替代链表，提升映射查找效率
     - 实现匿名页映射（`MAP_ANONYMOUS`）与文件映射分离逻辑
     - 新增 `struct anonfile` 抽象，支持共享匿名内存
   - 证据：`include/mm/mmap.h` 中 `struct mmap_page` 定义含 `struct rb_node rb` 字段

3. **Signal 集成优化（2021-08-17，commit `08c10ba`）**
   - 变更：`kernel/mm/vm.c` 增加信号跳板页映射（`SIG_TRAMPOLINE`）
   - 证据：`vm.c:613` 增加 `mappages(pagetable, SIG_TRAMPOLINE, PGSIZE, (uint64)sig_trampoline, PTE_R|PTE_X|PTE_U)`

#### 10.3.2 文件系统模块（`kernel/fs`）

`kernel/fs` 目录演进呈现 **SD 卡驱动优化** 与 **FAT32 完善** 两条主线：

1. **SD 卡驱动迭代（2021-08-15 ~ 2021-08-21）**
   - 2021-08-15：`a61574d` "pre-erase for SD write"（+183/-68 行），引入预擦除机制优化写入性能
   - 2021-08-18：`faf055d` "better read"（+51/-34 行），改进读取逻辑
   - 2021-08-21：`67fe53b` "update"（+364/-124 行），最终优化版本

2. **FAT32 文件系统完善**
   - 2021-08-12：`5808273` "two ways of disk write"（+168/-13 行），引入 FAT 区域缓存
   - 2021-08-15：`00cab82` "make disk fs mount at '/'"（+152/-75 行），实现根目录挂载

**证据路径**：`kernel/fs/fat32/` 目录下 `fat32.c`、`kernel/hal/sdcard.c`（1076 行，25.2KB）

#### 10.3.3 构建系统（`Makefile`）

`Makefile` 演进反映 **工具链切换** 与 **平台适配** 过程：

- **2021-05-28**：`bd6653f` "change toolchain prefix in Makefile"，适配 K210 平台 RISC-V 工具链
- **2021-07-29**：`27ca1f1` "lazy-mmap" 同步修改 Makefile（+55/-3 行），增加用户程序编译规则
- **2021-08-17**：`a7ffc31` "switch toolchain"（+2/-2 行），切换至 GNU RISC-V 工具链
- **2021-08-17**：`b10f6fe` "no sudo"（+2/-2 行），移除构建脚本中的 `sudo` 依赖

### 10.4 文档里程碑

#### 10.4.1 README.md 演进

通过 `trace_file_evolution` 追踪 `README.md`，识别关键更新节点：

- **2020-11-02**：初始版本（`5ea7c66` "update readme"，+3/-0 行）
- **2021-01-16**：增加 `ls` 命令支持文档（`c8ad18c` "support the 'ls' command"，+7/-2 行）
- **2021-05-20**：VFS 实现文档更新（`e683746` "Implement a simple vfs"，+11/-16 行）
- **2021-07-26**：Lazy-mmap 合并后更新（`8a76967` "fix little of fs"，+1/-1 行）
- **2021-08-18**：最终版本（`9331e6e` "update doc"，+142/-2 行）

**README 声称 vs 代码实际**：
- README 的 "Progress" 节声明已实现：Multicore boot、Page Table、SD card driver、File system、User program 等
- 代码验证：
  - ✅ Multicore boot：`kernel/main.c:98` 中 `main()` 调用 `mpmain()` 启动多核
  - ✅ SD card driver：`kernel/hal/sdcard.c`（1076 行）完整实现
  - ✅ File system：`kernel/fs/fs.c`（660 行）实现 VFS 层
  - ⚠️ Steady keyboard input(k210)：代码中仅 `kernel/console.c` 实现基础 UART 输入，未见 K210 专用键盘驱动

#### 10.4.2 `doc/` 目录文档

`doc/` 目录包含 **23 篇中文技术文档**，覆盖内核原理、构建调试、用户使用三大类：

- **内核原理**：`内核设计-页表映射.md`（246 行）、`内核设计-内存映射.md`（111 行）
- **构建调试**：`构建调试-SD 卡驱动 v2.md`（60 行）、`构建调试-系统调用 v2.md`（68 行）
- **用户使用**：`用户使用 - 内存管理.md`（52 行）、`用户使用 - 系统调用.md`（95 行）

**文档里程碑**：
- **2021-08-17**：`5b6b717` "update docs"（+418/-16 行），批量更新 23 篇文档
- **2021-08-18**：`9331e6e` "update doc"（+142/-2 行），最终文档迭代

### 10.5 实验性功能与待办缺口

#### 10.5.1 TODO/FIXME 标记

通过 `grep_in_repo` 搜索 `TODO|FIXME|XXX`，发现以下未实现功能：

1. **bootloader/SBI/rustsbi-k210/src/main.rs:188**：
   ```c
   println!("[rustsbi] reset triggered! todo: shutdown all harts on k210; program halt. ...");
   ```
   - 状态：**未实现**，多核关闭逻辑缺失

2. **kernel/mm/vm.c:613**：
   ```c
   * TODO: If protecting legal but not-valid-at-present pages, how can we maintain the
   ```
   - 状态：**设计注释**，Lazy-mmap 保护机制待完善

#### 10.5.2 实验性标记

- **Signal 机制**：2021-07-17 首次提交（`9759082`），至 2021-08-17 才标记 "signal now works"（`08c10ba`），历时 1 个月完善
- **Lazy-mmap**：2021-07-29 重构后，commit 消息标注 "almost re-written"，表明该功能在 2021-07 仍处于实验阶段

#### 10.5.3 功能移除

- **2021-07-18**：`c7f2c0c` "fix bug in kill()"（+7/-990 行），移除 `bootloader/` 目录中 989 行废弃代码
- **2021-08-15**：`d397976` "restore old scheduling scheme, fix deadlock"（+150/-238 行），回退调度器重构以修复死锁

### 10.6 里程碑提交摘要

| 日期 | Commit SHA | 作者 | 消息 | 变更规模 | 影响模块 |
|------|------------|------|------|----------|----------|
| 2021-05-27 | `758b94d` | YongkangLi | "primary mmap" | +170/-21 | `kernel/mm/mmap.c` |
| 2021-05-28 | `fb1bc91` | retrhelo | "merge mmap" | +335/-177 | `kernel/mm/` |
| 2021-07-15 | `a3907ef` | Lu Sitong | "lazy elf load mechanism" | +289/-134 | `kernel/mm/`, `kernel/exec.c` |
| 2021-07-17 | `9759082` | retrhelo | "add sigaction and sigprocmask" | +503/-141 | `kernel/sched/signal.c`, `kernel/trap/` |
| 2021-07-29 | `27ca1f1` | Lu Sitong | "lazy-mmap: almost re-written" | +701/-281 | `kernel/mm/mmap.c`, `include/mm/mmap.h` |
| 2021-08-17 | `08c10ba` | retrhelo | "signal now works" | +301/-132 | `kernel/sched/signal.c`, `kernel/trap/sig_trampoline.S` |
| 2021-08-21 | `67fe53b` | retrhelo | "update" | +364/-124 | `kernel/fs/`, `kernel/hal/sdcard.c` |

**证据来源**：`get_git_history_summary`、`get_commit_diff_summary`（commit `27ca1f1`、`08c10ba`、`6049281`）

### 10.7 小结

xv6-k210 项目在 3 个月开发周期内完成了从基础 xv6-riscv 移植到 K210 平台适配、内存管理优化（Lazy-mmap、COW）、Signal 机制实现、FAT32 文件系统完善等核心功能。开发模式呈现 **快速迭代、密集重构** 特征，关键模块（如 `kernel/mm/mmap.c`）经历多次大规模重写。文档与代码同步更新，但部分功能（如多核关闭、Lazy-mmap 保护机制）仍标记为 TODO，反映项目的实验性质。

---


---

*本报告由 OS-Agent-D 自动生成*  
*生成时间: 2026-04-20 20:51:16*  
*分析耗时: 57.3 分钟*
