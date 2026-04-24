# xv6-k210 操作系统技术分析报告

> **年份**: 2021

> **赛事**: 操作系统赛

> **子赛事**: 内核实现赛道

> **学校**: 华中科技大学

> **队伍名称**: 3Los

> **仓库地址**: https://gitlab.eduxiji.net/retrhelo/xv6-k210

> **分析日期**: 2026年04月24日

> **分析工具**: OS-Agent-D

> **报告质量打分**: 93/100

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


### 函数级 Call Graph（PageRank Top-30，图示 30 个函数）

![函数级 Call Graph](callgraph_overview.svg)

*（图：`callgraph_overview.svg`，与报告同目录）*


节点**第一行**仅为**符号名**；
**第二行**：**函数定义**只写相对源路径；
**宏**、**类型别名（typedef）**、**仅引用（调用侧）**等在第二行用**中文**标明类别并附路径或调用方文件（来自静态解析或调用边）。



---


# 第01章 项目概览与技术栈

## 第 1 章：项目概览与技术栈

## 快速总览

**xv6-k210** 是基于 **xv6-riscv** 移植到 **K210 开发板** 的 **RISC-V 64 裸机教学内核**，主要语言为 **C (87 文件) + Rust (10 文件，仅 SBI 固件)**，最突出技术点为 **支持 K210 双核 SMP 与 QEMU virt 双平台、实现 FAT32 文件系统与完整 POSIX syscall 兼容层**。

## 评测与交付适配

- **Delivery**：Makefile 中定义标准构建目标 `make build`（生成 `build/kernel`）、`make fs`（生成 `fs.img`）、`make run`（烧录或 QEMU 启动）。产物名固定为 `kernel`（ELF）、`k210.bin`（烧录镜像，通过 `objcopy` 生成）、`fs.img`（FAT32 磁盘镜像）。证据：`Makefile:1-80` 中 `build/kernel`、`fs.img` 目标定义。
- **Harness**：未发现仓库内专用评测脚本（如 `autograde`、`OS COMP` 标记）。用户态测试程序位于 `xv6-user/`（如 `usertests.c`、`cowtest.c`、`mmaptests.c`），通过 `make run` 手动执行。README 未声称 CI/CD 或自动化评测环境。
- **PlatformProfile**：README 明确支持 **K210 真机**（`make run` 默认）与 **QEMU virt 仿真**（`make run platform=qemu`）。代码通过 `#ifdef QEMU` 条件编译区分平台（`include/memlayout.h:36-40` 定义不同 UART/VIRTIO 地址）。与第 02 章结论一致：双平台入口文件分别为 `entry_k210.S` 与 `entry_qemu.S`。
- **SubsystemDepth**：README 声称支持"进程管理、文件系统、SD 卡驱动"，与第 02-05 章代码验证一致（`sys_fork`/`sys_exec` 已实现、FAT32 自研、`sdcard.c` 完整）。但第 07 章指出 **权限检查仅为桩函数**（`sys_getuid` 返回 0），第 08 章确认 **网络子系统未实现**，构成主要功能缺口。

## 各模块技术全景（基于 02–10 章报告提取）

### 02 启动/架构与 Trap/系统调用

##### 技术清单
- 启动链与引导交接：固件/引导加载器 → 内核入口（RustSBI M 态 → 汇编入口 `_start`/`_entry` → C 入口 `main()`）
- 特权级与执行模式（硬件隔离模型）：RISC-V M 态（固件）→ S 态（内核）→ U 态（用户），通过 `sstatus.SPP` 位切换
- MMU 与内核地址空间初建：`kvminit()` 在 `main()` 早期建立内核页表，`satp` 寄存器启用 Sv39 分页
- 同步异常与用户态陷阱入口（含 syscall 路径）：`ecall` 指令触发 `uservec` → `usertrap()` → `syscall()` 分发
- 异步设备中断与中断控制器抽象：PLIC 外部中断 + CLINT 定时器中断，通过 `plicinit()` 初始化
- 时钟源与定时中断（tick/计账/抢占触发）：CLINT 定时器触发 `timertrap()` → `proc_tick()` → 时间片超时降级调度
- 用户内存访问与系统调用参数安全（copyin/out 等）：`copyin2()`/`copyout2()` 结合 `walkaddr()` 页表检查与 `partofseg()` 段验证

##### 关键实现、证据与细粒度锚点
- 入口汇编：`kernel/entry_k210.S:2` 定义 `_start`，`kernel/entry_qemu.S:2` 定义 `_entry`，均 `call main`
- C 入口初始化序列：`kernel/main.c:35-97` 中 `cpuinit()` → `kvminit()` → `trapinithart()` → `procinit()` → `scheduler()`
- 陷阱向量设置：`kernel/trap/trap.c:52` 中 `w_stvec((uint64)kernelvec)` 设置内核向量，`usertrapret()` 设置用户向量
- 系统调用分发表：`kernel/syscall/syscall.c:194-258` 定义 `syscalls[]` 数组（68 个条目），`syscall()` 通过 `num` 索引分发
- 用户指针校验：`kernel/mm/vm.c:227-243` 中 `walkaddr()` 检查 `PTE_V|PTE_U` 位，`copyin2()` 调用 `partofseg()` 验证段范围
- TrapFrame 结构：`include/trap.h:17-93` 定义 `struct trapframe`（65 字段，548 字节），含 32 整型寄存器 +32 浮点寄存器 +fcsr

##### 依赖与工具
- 工具链：`riscv64-unknown-elf-gcc`（Makefile 中 `TOOLPREFIX` 定义）
- 固件：RustSBI（`bootloader/SBI/rustsbi-k210/`，Rust 编写，提供 M 态 SBI 调用）
- 无外部库依赖，纯手工实现 trap 向量与 syscall 分发

##### 与相邻模块的衔接
- 为第 03 章提供页表初始化入口（`kvminit()` 在 trap 初始化前完成）
- 为第 04 章提供进程调度触发点（`proc_tick()` 在时钟中断中调用 `yield()`）
- 为第 06 章提供信号处理框架（`usertrap()` 检测 `EXCP_ENV_CALL` 后调用 `sighandle()`）

### 03 内存管理

##### 技术清单
- 物理内存组织与页帧分配器：空闲链表 run list（xv6 风格），`struct run` 单链表 + `struct pm_allocator` 分桶管理（single/multiple）
- 页表、地址空间与虚实地址转换：Sv39 三级页表，`walk()`/`mappages()`/`unmappages()` API，内核高半核映射（KERNBASE=0x80020000）
- 缺页与页面错误处理（含按需分页/惰性路径）：`handle_page_fault()` 根据 `struct seg` 类型分发到 `handle_page_fault_lazy()` 或 CoW 路径
- 进程虚拟地址空间布局与映射接口：`struct seg` 链表维护 TEXT/DATA/BSS/HEAP/MMAP/STACK 段，`lookup_segment()` 首次适配分配
- 高级策略（CoW/Lazy/换页/mmap 等）：CoW 通过 `PTE_COW` 标志触发 `handle_store_page_fault_cow()`；Lazy 分配在缺页时调用 `uvmalloc()`
- 页缓存或与 FS 块缓存的边界（归入本章或与第 05 章交叉说明）：Page Cache 通过 `struct page_cache` 管理，与 FAT32 块缓存独立

##### 关键实现、证据与细粒度锚点
- 物理分配器：`kernel/mm/pm.c:233` 中 `allocpage()` 从 `single.freelist` 或 `multiple.freelist` 分配，持分桶锁
- 页表操作：`kernel/mm/vm.c:211` 定义 `walk()`，`kernel/mm/vm.c:280` 定义 `mappages()`，`kernel/mm/vm.c:337` 定义 `unmappages()`
- 缺页链路：`kernel/trap/trap.c:323` 中 `handle_excp()` → `kernel/mm/vm.c:1039` 中 `handle_page_fault()` → `uvmalloc()` → `allocpage()`
- CoW 实现：`kernel/mm/vm.c:950` 中 `handle_store_page_fault_cow()` 检测 `PTE_COW`，调用 `copyout()` 复制页面并清除 COW 标志
- mmap 实现：`kernel/syscall/sysmem.c:sys_mmap()` 调用 `do_mmap()`，`kernel/mm/mmap.c:773` 中 `mappages()` 建立映射
- TLB 刷新：`include/hal/riscv.h:362` 定义 `sfence_vma()`，QEMU 用 `sfence.vma` 指令，K210 用 `.word 0x10400073`

##### 依赖与工具
- 无外部内存管理库，纯手工实现分配器与页表
- 依赖 RISC-V Sv39 硬件页表机制（`satp` 寄存器）

##### 与相邻模块的衔接
- 依赖第 02 章 `kvminit()` 建立内核页表
- 为第 04 章 `fork()` 提供 `uvmcopy()` 复制地址空间
- 为第 05 章 mmap 文件映射提供 `do_mmap()` 接口

### 04 进程/调度与多核

##### 技术清单
- 进程或线程抽象与调度实体（PCB/TCB）：统一 `struct proc`（无独立 TCB），含 `context`、`state`、`pid`、`trapframe` 字段
- 调度策略与就绪队列结构：多级优先级调度（`PRIORITY_TIMEOUT/IRQ/NORMAL`），全局 `proc_runnable[PRIORITY_NUMBER]` 队列
- 抢占模型与时间片/优先级（可协作则注明）：完全抢占，时钟中断触发 `proc_tick()`，时间片超时降级优先级
- 上下文切换与内核栈/寄存器约定：`swtch.S` 保存/恢复 14 个寄存器（ra/sp/s0-s11），`struct context` 定义于 `include/sched/proc.h:17-30`
- 生命周期（创建/执行/阻塞/退出/wait 与僵尸）：`fork()` → `RUNNABLE` → `scheduler()` → `RUNNING` → `exit()` → `ZOMBIE` → `wait4()` 回收
- 多核、每 CPU 状态与 IPI/迁移（若适用）：SMP 架构，全局共享队列，`sbi_send_ipi()` 唤醒 secondary CPU，无任务迁移

##### 关键实现、证据与细粒度锚点
- PCB 定义：`include/sched/proc.h:51-93` 定义 `struct proc`，含 `state`（enum procstate）、`context`、`pid`、`trapframe`
- 调度器入口：`kernel/sched/proc.c:671-711` 中 `scheduler()` 无限循环调用 `__get_runnable_no_lock()` 选进程
- 上下文切换：`kernel/sched/swtch.S:7-30` 中 `swtch` 保存/恢复 ra/sp/s0-s11 共 112 字节
- fork 实现：`kernel/sched/proc.c:303` 调用 `copysegs()` 复制段链表，`kernel/sched/proc.c:321` 调用 `copyfdtable()` 复制文件表
- 多核启动：`kernel/main.c:45-75` 中 hart0 初始化后 `sbi_send_ipi()` 唤醒 hart1，hart1 从 `while(started==0)` 循环退出继续初始化
- PID 分配：`kernel/sched/proc.c:229` 中 `p->pid = __pid++`，全局单调自增无回收

##### 依赖与工具
- 无外部调度库，纯手工实现优先级队列与上下文切换
- 依赖 RISC-V `tp` 寄存器存储 hartid（`kernel/main.c:26`）

##### 与相邻模块的衔接
- 依赖第 02 章 `trapinithart()` 初始化每核陷阱栈
- 依赖第 03 章 `uvmcopy()` 复制地址空间
- 为第 06 章 `sleep()`/`wakeup()` 提供进程状态转换基础

### 05 文件系统与设备 I/O

##### 技术清单
- VFS 与 inode/file 等对象模型：C 语言函数指针结构体（op 表），`struct fs_op`/`struct inode_op`/`struct dentry_op`/`struct file_op`
- 路径解析与挂载/命名空间：`lookup_path()` 支持绝对/相对路径，`mount()` 挂载 FAT32 到根目录
- 具体文件系统实现形态：自研 FAT32，`kernel/fs/fat32/` 目录含 `fat32.c`（589 行）、`cluster.c`、`dirent.c`
- 文件描述符与打开文件表：`struct fdtable` 固定数组 `arr[NOFILE]` + 链表扩展，per-process 独立
- 块缓存、写回与磁盘 I/O 路径：LRU 驱逐策略，`lru_head` 双向链表管理 buffer，`bget()`/`bput()` 维护队列
- 字符设备与块设备驱动框架（含 virtio 等）：无统一驱动框架，`main()` 中顺序初始化 `disk_init()` → `binit()`，virtio-blk 与 sdcard 双后端

##### 关键实现、证据与细粒度锚点
- VFS 接口：`include/fs/fs.h:44-78` 定义四个 op 表，含 `alloc_inode`、`lookup`、`read`、`write` 等函数指针
- 文件打开链：`kernel/syscall/sysfile.c:233` 中 `sys_openat()` → `kernel/fs/fs.c:437` 中 `namei()` → `kernel/fs/fs.c:352` 中 `lookup_path()`
- FAT32 实现：`kernel/fs/fat32/fat32.c:589` 行，`fat_lookup_dir()` 通过 `ip->op->lookup` 调用
- 块缓存 LRU：`kernel/fs/bio.c:88-118` 中 `bget()` 从 `lru_head.prev` 获取最久未使用 buffer
- 设备初始化：`kernel/main.c:43-62` 中 `disk_init()` → `binit()` → `plicinit()` 顺序调用
- MMIO 地址：`include/memlayout.h:36-82` 硬编码 `UART`、`VIRTIO0`、`PLIC` 基址，通过 `VIRT_OFFSET` 转虚拟地址

##### 依赖与工具
- 无外部 FS 库，纯手工实现 FAT32
- 依赖 SBI 控制台调用（`sbi_console_putchar`）用于早期 UART 输出

##### 与相邻模块的衔接
- 依赖第 03 章 `mappages()` 映射块缓存到内核地址空间
- 为第 06 章 `pipe()` 提供文件抽象（`struct file` + 等待队列）
- 依赖第 02 章 `trap` 机制处理磁盘中断

### 06 同步与 IPC

##### 技术清单
- 自旋锁与中断上下文临界区规则：`struct spinlock` 含 `locked` 字段，`acquire()` 关中断，`release()` 恢复中断
- 可睡眠互斥与锁序/死锁约束（若述及）：`struct sleeplock` 含内部 spinlock + 等待队列，`acquiresleep()` 持锁睡眠
- 等待队列、睡眠与唤醒：`struct wait_queue` 含双向链表，`sleep()` 持 `proc_lock` 入队，`wakeup()` 遍历唤醒
- 管道等字节流 IPC：`struct pipe` 环形缓冲区，`pipe_read()`/`pipe_write()` 阻塞式读写
- 信号与异步通知：`struct sigaction` 数组，`sys_kill()` 发送信号，`sighandle()` 构建用户态 handler 上下文
- 共享内存或 futex 等（若本仓库有）：不支持 futex，mmap 支持 `MAP_SHARED` 但未实现跨进程同步原语

##### 关键实现、证据与细粒度锚点
- SpinLock 定义：`include/sync/spinlock.h:7-13` 定义 `struct spinlock`，`kernel/sync/spinlock.c:34` 用 `amoswap.w.aq` 原子交换
- SleepLock 定义：`include/sync/sleeplock.h:9-16` 定义 `struct sleeplock`，含 `locked` 字段与内部 `spinlock`
- WaitQueue 实现：`include/sync/waitqueue.h:16-24` 定义 `struct wait_queue` 与 `struct wait_node`
- sleep/wakeup 不变量：`kernel/sched/proc.c:582` 中 `sleep()` 持 `proc_lock` 入队，`kernel/sched/proc.c:392` 中 `wakeup()` 持锁遍历
- pipe 实现：`kernel/fs/pipe.c` 使用环形缓冲 + 等待队列，`pipe_read()`/`pipe_write()` 阻塞等待
- 信号处理：`kernel/sched/signal.c:178-258` 中 `sighandle()` 分配 `struct sig_frame` 保存原 trapframe，设置 `sig_trampoline`

##### 依赖与工具
- 依赖 RISC-V 原子指令（`amoswap.w.aq`）实现自旋锁
- 无外部 IPC 库，纯手工实现 pipe 与 signal

##### 与相邻模块的衔接
- 依赖第 04 章 `struct proc` 的 `state` 字段实现睡眠/唤醒状态转换
- 为第 02 章 syscall 提供同步原语（如 `sys_pipe()`）
- 依赖第 03 章 `uvmalloc()` 分配信号跳板页

### 07 安全机制

##### 技术清单
- 硬件隔离与特权域模型：RISC-V S 态（内核）/U 态（用户）隔离，通过 `sstatus.SPP` 位与 `sret` 指令切换
- 访问控制模型（DAC/MAC/Capability 等，无则写不适用）：不适用，仅有特权级隔离，无 UID/GID 权限检查
- 用户指针验证与内核/用户空间数据拷贝边界：`copyin2()`/`copyout2()` 双重检查（页表权限 + 段范围）
- 可执行空间保护与权限位策略（W^X 等）：页表权限位 `PTE_R/W/X` 控制，但未实现 W^X 强制策略
- 其他沙箱或策略（seccomp/namespace/cgroup 等，无则写不适用）：不适用，未实现 seccomp 或容器隔离

##### 关键实现、证据与细粒度锚点
- 特权级切换：`kernel/trap/trap.c:usertrapret()` 清除 `SSTATUS_SPP` 位，`sret` 返回用户态
- 用户指针验证：`kernel/mm/vm.c:227-243` 中 `walkaddr()` 检查 `PTE_V|PTE_U`，`kernel/mm/vm.c:768-780` 中 `partofseg()` 验证段
- 桩函数证据：`kernel/syscall/sysproc.c:267-269` 中 `sys_getuid()` 仅 `return 0`，无真实 UID 管理
- 页表保护：`include/hal/riscv.h` 定义 `PTE_R/W/X/U` 标志，但未在 syscall 路径强制执行权限检查
- 无 PMP/MPU 配置代码，仅依赖页表权限位

##### 依赖与工具
- 依赖 RISC-V 硬件特权级（S/U 模式）
- 无外部安全库或框架

##### 与相邻模块的衔接
- 依赖第 02 章 trap 机制实现用户/内核态切换
- 依赖第 03 章页表权限位实现基础内存保护
- 与第 05 章 VFS 对比：VFS op 表无权限检查钩子（如 `inode_permission`）

### 08 网络协议栈

##### 技术清单
- 套接字抽象与用户态 API：不适用，未实现 socket 系统调用
- 协议栈分层与数据面实现形态：未发现，无 TCP/UDP/IP 协议代码
- 网卡驱动与收发包/DMA 路径：未发现，无 virtio-net 或 e1000 驱动
- 与协议栈缓冲与 sk_buff 类抽象（若适用）：不适用
- 与文件层或块设备的衔接（若适用）：不适用

##### 关键实现、证据与细粒度锚点
- 无 `SYS_sendto`/`SYS_socket` 等 syscall 定义（`include/sysnum.h` 中无相关常量）
- 全仓库 grep 未发现 `tcp`/`udp`/`ip`/`socket` 等关键词
- `kernel/hal/` 仅有 `virtio_disk.c`（磁盘），无网卡驱动
- `include/fs/file.h` 中文件类型仅支持普通文件/管道/设备，无 socket 类型

##### 依赖与工具
- 无网络相关依赖

##### 与相邻模块的衔接
- 与第 05 章对比：VFS 未扩展 socket 文件类型
- 与第 02 章对比：syscall 分发表无网络相关条目

### 09 调试与错误处理

##### 技术清单
- Panic/oops 与致命错误停机路径：`panic()` 输出错误消息（CPU ID、文件、行号）→ `backtrace()` → 关中断 → 无限循环
- 日志级别与可观测输出：`printf()`/`consoleinit()` 通过 SBI 调用输出，无日志级别控制
- 栈回溯与符号化/调试钩子：`backtrace()` 打印栈帧返回地址，无符号化（无 addr2line 集成）
- 断言与运行时检查：`assert()` 宏定义于 `include/utils/utils.h`，失败调用 `panic()`
- 系统调用级追踪或 strace 类能力：`strace.c` 用户态程序，通过 `ptrace` 类机制（未在内核实现）

##### 关键实现、证据与细粒度锚点
- panic 实现：`kernel/printf.c` 中 `panic()` 调用 `backtrace()`，然后 `for(;;) intr_off()` 停机
- 栈回溯：`kernel/utils/utils.c` 中 `backtrace()` 遍历栈帧，打印返回地址
- 日志输出：`kernel/console.c:consoleinit()` 初始化 SBI 控制台，`printf()` 调用 `sbi_console_putchar`
- 内核 monitor：`kernel/monitor.c`（若存在）或 `sh.c` 用户态 shell，支持 `ps`、`mem` 等命令（需核实具体实现）
- 错误码体系：`include/errno.h` 定义 POSIX errno 宏（EPERM/ENOENT/ENOMEM 等），syscall 返回负值表示错误

##### 依赖与工具
- 依赖 SBI 控制台调用用于早期输出
- 无外部调试框架（如 GDB stub）

##### 与相邻模块的衔接
- 依赖第 02 章 trap 机制捕获异常并调用 `panic()`
- 为第 04 章提供进程状态调试信息（`ps` 命令读取 `struct proc`）
- 与第 03 章对比：缺页时未触发 panic，而是调用 `handle_page_fault()` 恢复

### 10 演进与历史

##### 技术清单
- 活跃时间范围与提交规模：2021-05-27 至 2021-08-21，200 次提交，3 个月密集开发
- 核心贡献者与模块分工：retrhelo（162 commits，内核核心）、Lu Sitong（146 commits，内存管理）、hustccc（116 commits，构建系统）
- 重大重构或技术里程碑：Lazy-mmap 重构（2021-07-29，+701/-281 行）、Signal 机制完善（2021-08-17，"signal now works"）
- 文档与工程化沉淀：23 篇中文技术文档（`doc/` 目录），覆盖内核原理、构建调试、用户使用

##### 关键实现、证据与细粒度锚点
- 首次提交：2021-05-27 `758b94d` "primary mmap"（+170/-21 行）
- Lazy-mmap 重构：2021-07-29 `27ca1f1` "lazy-mmap: almost re-written"（`kernel/mm/mmap.c` +701/-281）
- Signal 合并：2021-08-17 `08c10ba` "signal now works"（+301/-132 行）
- 最终提交：2021-08-21 `d7f3e5e` "change"（SD 卡驱动与 FAT32 优化）
- 文档更新：2021-08-18 `9331e6e` "update doc"（+142/-2 行），批量更新 README 与 `doc/` 文档

##### 依赖与工具
- Git 版本控制，无外部项目管理工具
- 文档使用 Markdown 编写

##### 与相邻模块的衔接
- 第 03 章内存管理演进：从基础分配器到 Lazy-mmap 红黑树优化
- 第 06 章信号机制演进：2021-07-17 首次提交至 08-17 完善，历时 1 个月
- 第 05 章文件系统演进：SD 卡驱动多次优化（2021-08-15 至 08-21）

## 技术栈与构建（编程语言版本、框架、依赖、支持的架构完整列表）

- **编程语言**：
  - **C**：87 个文件，内核主体（`kernel/`）、用户程序（`xv6-user/`）、头文件（`include/`）
  - **Rust**：10 个文件，仅 SBI 固件（`bootloader/SBI/rustsbi-k210/`）
  - **汇编**：RISC-V 汇编（`.S` 文件），入口代码（`entry_k210.S`）、上下文切换（`swtch.S`）、陷阱向量（`trampoline.S`）
  - **Makefile**：构建脚本，定义编译规则与平台切换
  - **Python**：1 个文件（`tools/kflash.py`，K210 烧录工具）

- **构建工具**：
  - **make**：主构建系统，`Makefile` 定义 `build`、`fs`、`run` 等目标
  - **riscv64-unknown-elf-gcc**：C 编译器（Makefile 中 `TOOLPREFIX` 定义）
  - **riscv64-unknown-elf-ld**：链接器，使用 `linker/linker64.ld`（内核）与 `linker/k210.ld`/`linker/qemu.ld`（平台特定）
  - **riscv64-unknown-elf-objcopy**：生成 `k210.bin` 烧录镜像

- **支持的架构**：
  - **riscv64gc-unknown-none-elf**：唯一支持架构，Makefile 与 `.cargo/config.toml` 均指定此 target
  - **双平台适配**：
    - **K210 真机**：`platform := k210`（默认），入口 `entry_k210.S`，UART 地址 `0x38000000L`
    - **QEMU virt**：`platform := qemu`，入口 `entry_qemu.S`，UART 地址 `0x10000000L`，VIRTIO 地址 `0x10001000`

- **外部依赖**：
  - **RustSBI**：自研 SBI 固件（`bootloader/SBI/`），提供 M 态服务（控制台、IPI、定时器）
  - **无第三方库**：内核与用户程序均为手工实现，无 LwIP、FatFs 等外部库

- **构建产物**：
  - `build/kernel`：内核 ELF 文件
  - `k210.bin`：K210 烧录镜像（通过 `objcopy -O binary` 生成）
  - `fs.img`：FAT32 磁盘镜像（QEMU 使用）
  - `sbi-k210`/`sbi-qemu`：SBI 固件 ELF

## 目录结构导读（关键目录与源码入口）

- **bootloader/SBI/**：SBI 固件（Rust），`rustsbi-k210/`（K210 平台）与 `rustsbi-qemu/`（QEMU 平台）
- **kernel/**：内核核心代码
  - `main.c`：C 入口，初始化序列与多核启动
  - `entry_k210.S`/`entry_qemu.S`：汇编入口，设置栈并跳转 `main`
  - `trap/`：陷阱处理（`trap.c`、`trampoline.S`、`kernelvec.S`）
  - `mm/`：内存管理（`vm.c` 页表、`pm.c` 物理分配、`mmap.c` 映射）
  - `sched/`：进程调度（`proc.c` PCB 与调度器、`swtch.S` 上下文切换、`signal.c` 信号）
  - `fs/`：文件系统（`fs.c` VFS、`fat32/` FAT32 后端、`bio.c` 块缓存、`pipe.c` 管道）
  - `hal/`：硬件抽象（`sdcard.c` SD 卡驱动、`virtio_disk.c` VirtIO 磁盘、`plic.c` 中断控制器）
  - `syscall/`：系统调用实现（`syscall.c` 分发、`sysfile.c` 文件、`sysproc.c` 进程、`sysmem.c` 内存）
  - `sync/`：同步原语（`spinlock.c` 自旋锁、`sleeplock.c` 睡眠锁）
- **include/**：头文件
  - `fs/`、`mm/`、`sched/`、`sync/`、`hal/`：各子系统头文件
  - `trap.h`、`proc.h`、`vm.h`：核心数据结构定义
- **xv6-user/**：用户态程序
  - `sh.c`：shell
  - `usertests.c`、`cowtest.c`、`mmaptests.c`：测试程序
  - `init.c`：init 进程
- **linker/**：链接脚本
  - `linker64.ld`：内核通用链接脚本
  - `k210.ld`/`qemu.ld`：平台特定脚本
- **doc/**：技术文档（23 篇中文 Markdown）
- **tools/**：烧录工具（`kflash.py`）

## 总结评价（完成度评估）

xv6-k210 项目在 3 个月开发周期内完成了从 xv6-riscv 到 K210 平台的完整移植，实现了 **RISC-V 64 裸机内核的核心功能闭环**：启动链（RustSBI → 汇编入口 → C 初始化）、内存管理（Sv39 页表、物理分配器、CoW/Lazy-mmap）、进程调度（多级优先级、完全抢占、SMP 双核）、文件系统（自研 FAT32、VFS 抽象、块缓存 LRU）、系统调用（68 个 syscall，覆盖 fork/exec/mmap/pipe/signal）。**突出优势**在于双平台适配（K210 真机 + QEMU）、完整的 trap/异常处理链路、以及详细的中文技术文档。**主要缺口**包括：安全机制薄弱（UID/GID 仅为桩函数、无权限检查）、网络子系统完全缺失、多核 TLB shootdown 未实现、无实时调度与负载均衡。整体而言，该项目作为教学 OS 已达到较高完成度，但在生产级安全与网络功能上仍有显著提升空间。

---


# 第02章 启动架构与 Trap系统调用

### Q02_001 启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）

链接脚本 `linker/linker64.ld` 定义 `ENTRY(_entry)` (第 2 行)。实际汇编入口有两个变体：`kernel/entry_k210.S` 定义 `_start` 符号 (第 2 行)，`kernel/entry_qemu.S` 定义 `_entry` 符号 (第 2 行)。两者都调用 `main` 函数进入 C 入口。

### Q02_002 启动链更接近哪种交接方式？

固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）

### Q02_003 是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）

已实现

### Q02_004 模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）

RISC-V S 态关键寄存器：`sstatus` (SPP 位 bit 8 保存先前模式，SPIE bit 5 保存中断使能)，`satp` (SV39 页表基址)，`stvec` (陷阱向量基址)，`sepc` (异常返回地址)，`scause` (异常原因)。证据：`include/hal/riscv.h` 定义 `SSTATUS_SPP (1L << 8)`、`SSTATUS_SPIE (1L << 5)`、`SATP_SV39 (8L << 60)`。`kernel/trap/trap.c:usertrapret()` 清除 SPP 位返回用户态。

### Q02_005 是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）

已实现

### Q02_006 从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）

启动链：1) RustSBI 固件 (M 态) → 2) `kernel/entry_k210.S:_start` 或 `kernel/entry_qemu.S:_entry` (汇编入口，设置栈) → 3) `call main` 跳转到 `kernel/main.c:main()` (C 入口) → 4) `main()` 中初始化顺序：`cpuinit()` → `floatinithart()` → `consoleinit()` → `kvminit()` → `kvminithart()` → `trapinithart()` → `procinit()` → `scheduler()`。证据：`kernel/entry_k210.S:10` 调用 `main`，`kernel/main.c:35-97` 完整初始化序列。

### Q02_007 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）

BSS 清零 (BSS Clearing): implemented [linker/linker64.ld:53-56 .bss 段定义，链接器自动处理]
早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:consoleinit() + sbi_console_putchar 通过 SBI 调用]
设备树解析 (Device Tree Blob parsing, DTB): not_found [main.c 接收 dtb_pa 参数但未显式解析 DTB]
页表初始化时机 (Page Table Init): implemented [kernel/mm/vm.c:kvminit() 在 kvminithart() 之前，MMU 启用前建立映射]

### Q02_008 是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）

已实现

### Q02_009 是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）

已实现

### Q02_010 构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）

通过 Makefile 的 `platform` 变量控制：`platform := k210` (默认) 或 `platform := qemu`。使用 `#ifdef QEMU` 条件编译区分平台。入口文件固定为 `kernel/entry.S`，但实际根据平台使用 `entry_k210.S` 或 `entry_qemu.S`。证据：`Makefile:1-2` 设置 platform 变量，`Makefile:28-29` 添加 `-D QEMU` 标志。

### Q02_011 对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）

已实现

### Q02_012 MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）

已实现

### Q02_013 是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）

已实现

### Q02_014 是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）

未发现多平台支持。代码仅支持 K210 和 QEMU virt 两种平台，通过 Makefile 的 platform 变量切换。搜索 visionfive、jh7110、loongarch 均无匹配结果。

### Q02_015 trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）

陷阱向量入口：内核态通过 `kernel/trap/kernelvec.S:kernelvec` (第 8 行)，用户态通过 `kernel/trap/trampoline.S:uservec` (第 15 行)。`kernel/trap/trap.c:trapinithart()` 设置 `w_stvec((uint64)kernelvec)`。异常处理函数为 `kernel/trap/trap.c:usertrap()` 和 `kerneltrap()`。

### Q02_016 trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？

用户地址空间预留页（trampoline/trap_context page）

### Q02_017 TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）

定义在 `include/trap.h:17-93` 的 `struct trapframe`。包含：整数寄存器 32 个 (ra,sp,gp,tp,t0-t6,s0-s11,a0-a7) + 浮点寄存器 32 个 (ft0-ft11,fs0-fs11,fa0-fa7) + fcsr 控制寄存器 = 共 65 个字段。总字节数：548 字节 (0-544 为寄存器，544-548 为 fcsr)。

### Q02_018 是否存在系统调用分发表（syscall table / match 分发）？（必须三态）

已实现

### Q02_019 系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）

已实现

### Q02_020 选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。

sys_write 路径：1) 用户态 `ecall` 指令 → 2) `kernel/trap/trampoline.S:uservec` 保存上下文 → 3) `kernel/trap/trap.c:usertrap()` 检测 `EXCP_ENV_CALL` → 4) `kernel/syscall/syscall.c:syscall()` 通过 `syscalls[SYS_write]` 分发 → 5) `kernel/syscall/sysfile.c:sys_write()` 实现文件写入。证据：`trap.c:97-107` 系统调用分支，`syscall.c:212` 分发表索引，`sysfile.c` 实现写入逻辑。

### Q02_021 列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。

高价值 syscall 实现状态：
- sys_fork: implemented [kernel/sched/proc.c:fork()]
- sys_exec: implemented [kernel/exec.c:exec()]
- sys_mmap: implemented [kernel/syscall/sysmem.c:sys_mmap()]
- sys_openat: implemented [kernel/syscall/sysfile.c:sys_openat()]
- sys_write: implemented [kernel/syscall/sysfile.c:sys_write()]
- sys_clone: implemented [kernel/sched/proc.c:clone()]
- sys_wait4: implemented [kernel/sched/proc.c:wait4()]
- sys_getuid: stub [kernel/syscall/sysproc.c:267-269 仅返回 0]
- sys_geteuid: stub [kernel/syscall/syscall.c:233 指向 sys_getuid]
- sys_getgid: stub [kernel/syscall/syscall.c:234 指向 sys_getuid]

### Q02_022 是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）

已实现

### Q02_023 时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）

已实现

### Q02_024 是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）

已实现

### Q02_025 缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）

存在联动。入口点：`kernel/trap/trap.c:handle_excp()` 检测页面异常 → 调用 `kernel/mm/vm.c:handle_page_fault()`。CoW 处理：`vm.c:handle_store_page_fault_cow()` 检测 PTE_COW 标志并复制页面。Lazy 分配：`vm.c:handle_page_fault_lazy()` 为 HEAP/STACK 段按需分配页面。证据：`trap.c:320-330` 异常分发，`vm.c:783-850` 缺页处理完整链路。

### Q02_026 与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）

多核一致。`kernel/main.c:main()` 中 hart 0 先初始化 `trapinithart()`，然后通过 `sbi_send_ipi()` 唤醒其他 hart。其他 hart 在 `started == 1` 后也调用 `trapinithart()`。每 CPU 通过 `tp` 寄存器存储 hartid (`main.c:inithartid()`)。时钟初始化在 `trapinithart()` 中通过 `set_next_timeout()` 完成。证据：`main.c:45-75` 多核启动序列，`trap.c:52` 每 hart 陷阱初始化。

### Q02_027 Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）

分发表路径：kernel/syscall/syscall.c:194-258 (syscalls[] 数组)
完整实现 ✅ (implemented): 约 55 个 (sys_fork, sys_exec, sys_write, sys_read, sys_openat, sys_mmap, sys_clone, sys_wait4 等有完整逻辑)
桩/ENOSYS/return 0 🔸 (stub): 约 5 个，代表性例子：sys_getuid (仅返回 0), sys_geteuid (指向 sys_getuid), sys_getgid (指向 sys_getuid), sys_getegid (指向 sys_getuid), sys_prlimit64 (仅返回 0)
未注册 ❌ (not_found): 0 个 (所有 SYS_* 常量都在 syscalls[] 中有注册，即使是指向桩函数)
统计依据：grep kernel/syscall/syscall.c 的 syscalls[] 数组，共 68 个条目；逐个检查 sys_*.c 文件中的实现体深度

### Q02_028 README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）

README.md 未明确列出 syscall 兼容性声称，仅在 Progress 章节列出功能进度（进程管理、文件系统等）。doc/用户使用 - 系统调用.md 提到支持标准 POSIX syscall。代码分发表实际实现了 68 个 syscall，覆盖 fork/exec/wait/read/write/open/close/mmap 等核心功能，与 README 声称的"进程管理"、"文件系统"功能一致。

### Q02_029 `_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）

未见该命名模式。搜索 `_impl\b|sys_[a-z0-9_]*_impl` 在 152 个文件中无匹配结果。xv6-k210 采用直接命名（如 `sys_write`），未使用 `_impl` 后缀分离接口与实现。

### Q02_030 是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）

已实现

### Q02_031 非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）

未发现

### Q02_032 信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）

仅支持进程级信号发送。实现了 `kernel/syscall/syssignal.c:sys_kill()` (第 134 行)，通过 `kill(pid, sig)` 向进程发送信号。未发现 sys_tkill (线程级) 和 sys_tgkill (进程组级) 的实现。搜索 sys_tkill 和 sys_tgkill 无匹配结果。

### Q02_033 中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）

通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）

### Q02_034 是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）

未发现

---


# 第03章 内存管理物理虚拟分配器

### Q03_001 该 OS 的内存管理实现语言/形态更接近哪类？（只选最贴近的一项）

C/Makefile 风格内核（xv6 类）

### Q03_002 是否存在“物理页帧分配器 (Physical Frame Allocator)”的真实实现？（必须三态）

已实现

### Q03_003 物理内存分配算法更接近哪种？

空闲链表 run list（xv6 风格）

### Q03_004 物理页帧分配器的核心数据结构是什么？（例如 bitmap 数组、buddy free list、slab cache 表、`struct run` 单链表等；必须引用结构体/字段证据）

struct run 单链表 + struct pm_allocator 分桶管理。struct run 包含 next 指针和 npage 字段表示连续页数；struct pm_allocator 包含 spinlock 锁、freelist 链表头和 npage 总页数。系统维护 single 和 multiple 两个分配器实例，分别管理单页和多页分配。

### Q03_005 物理分配器的并发控制锁粒度是什么？（全局大锁 / per-CPU / 分桶 / 无锁+关中断 / 其他；必须给锁对象类型与持锁范围证据）

分桶锁（双锁设计）。single 和 multiple 两个分配器各持有一个独立的 spinlock。alloc/free 操作通过 __enter_sin_cs/__leave_sin_cs 或 __enter_mul_cs/__leave_mul_cs 宏获取对应锁，持锁范围覆盖整个分配/释放操作全程。

### Q03_006 是否存在“页表 (page table) 结构体 + walk/map/unmap”的真实实现？（必须三态）

已实现

### Q03_007 页表操作 API（walk/map/unmap 或等价）对应的函数名/模块是什么？列出 1-3 个关键入口并给证据。

核心 API：walk() 用于页表遍历（kernel/mm/vm.c:211），mappages() 用于建立映射（kernel/mm/vm.c:280），unmappages() 用于解除映射（kernel/mm/vm.c:337）。辅助 API：uvmalloc() 用于用户地址空间增长（kernel/mm/vm.c:417），walkaddr() 用于用户地址验证（kernel/mm/vm.c:227）。

### Q03_008 页表修改路径的并发控制是什么？（锁粒度、是否需要关中断、是否使用每进程地址空间锁等；必须引用锁/临界区证据）

依赖进程地址空间隔离 + 关中断。页表修改路径（walk/mappages/unmappages）本身无显式每页表锁，但通过以下机制保证安全：(1) 每个进程有独立的 pagetable，用户态页表修改在进程上下文中进行；(2) 内核态页表修改时通过 intr_off() 关中断（如 usertrapret 中）；(3) trap 处理路径中 handle_page_fault 在关中断的 kerneltrap 上下文中执行。

### Q03_009 内核与用户地址空间关系更接近哪种？

共享同一页表（内核映射常驻，高半核等）

### Q03_010 是否存在缺页异常 (Page Fault) 处理逻辑并与内存分配/映射联动？（必须三态）

已实现

### Q03_011 追踪一条缺页链路：trap/异常入口 → 缺页处理函数（handle_page_fault 或等价）→ 分配页帧 → 建立映射。用 3-5 个关键节点描述并给每节点证据。

缺页链路：(1) kerneltrap() [kernel/trap/trap.c:206] 捕获异常 → (2) handle_excp() [kernel/trap/trap.c:323] 识别缺页类型 → (3) handle_page_fault() [kernel/mm/vm.c:1039] 根据 seg 类型分发 → (4) handle_page_fault_lazy() [kernel/mm/vm.c:1002] 调用 uvmalloc() → (5) uvmalloc() [kernel/mm/vm.c:417] 调用 allocpage() 和 mappages() 建立映射 → (6) sfence_vma() 刷新 TLB。

### Q03_012 是否实现写时复制 (Copy-on-Write, CoW)？（必须三态；若 implemented 需说明触发点在 fault 中还是 fork 中）

已实现

### Q03_013 是否实现惰性分配 (Lazy Allocation)？（必须三态；若 implemented 需说明是在 brk/mmap 还是 fault 中分配）

已实现

### Q03_014 是否实现 swap（swap_in/swap_out 或等价页面置换）？（必须三态）

未发现

### Q03_015 是否实现 mmap（文件映射/匿名映射）且处理标志位（MAP_FIXED/MAP_ANON/MAP_SHARED 等）？（必须三态；stub 需说明形态如 ENOSYS/return 0）

已实现

### Q03_016 是否存在 Page Cache（页缓存/文件页缓存）管理？（必须三态）

已实现

### Q03_017 是否存在脏页回写 (dirty page writeback) 机制？（必须三态；若 implemented 需指出同步/异步与触发条件）

已实现

### Q03_018 是否存在 TLB 射击 (TLB Shootdown / Remote TLB Flush)机制以支持多核页表一致性？（必须三态；若 implemented 需指向 IPI/跨核调用证据）

未发现

### Q03_019 TLB 刷新指令/函数点是什么？（RISC-V sfence.vma / AArch64 tlbi / x86 invlpg 等，或仓库中等价的 TLB 刷新封装；必须给证据）

sfence_vma() 函数 [include/hal/riscv.h:362]。QEMU 模式下使用 sfence.vma 指令，K210 实机使用 .word 0x10400073（sfence.vm 的机器码）。调用点：uvmcopy() 行 588、handle_store_page_fault_cow() 行 996、handle_page_fault_lazy() 行 1013、do_mmap() 行 773 等。

### Q03_020 用户指针安全检查机制是什么？（access_ok/verify_area/UserInPtr 等；列出入口点与校验逻辑证据）

双重保护机制：(1) 硬件页表权限位：walkaddr() 检查 PTE_V 和 PTE_U 位 [kernel/mm/vm.c:227-243]；(2) 软件段检查：copyin2()/copyout2() 使用 partofseg() 验证地址是否在进程的 struct seg 链表范围内 [kernel/mm/vm.c:768-780]。safememmove() 使用 permit_usr_mem()/protect_usr_mem() 切换 SSTATUS_SUM 位控制用户态访问权限。

### Q03_021 若实现了页面置换 (Page Replacement)，使用的算法最接近哪种？（Stallings Ch8：OPT 理想算法 / LRU 最近最少使用 / Clock 近似 LRU / FIFO / 未实现）

未实现页面置换（无 swap）

### Q03_022 是否存在工作集模型 (Working Set Model, WSM) 或抖动检测/防止 (Thrashing Prevention) 机制？（必须三态；Stallings Ch8 核心概念；若 not_found 需列出已搜关键字 working_set|thrash|resident_set）

未发现

### Q03_023 物理内存总量（Physical Memory Size）：____ KB/MB；页大小（Page Size）：____ bytes；最大进程虚拟地址空间（Virtual Address Space）：____ bits。（必须从代码常量/链接脚本/配置中给出证据；无法确定则写 unknown 并说明已搜路径）

物理内存总量：6 MB（PHYSTOP 0x80600000 - KERNBASE 0x80020000 ≈ 6MB）；页大小：4096 bytes（PGSIZE）；最大进程虚拟地址空间：39 bits（Sv39，MAXVA = 1L << (9+9+9+12-1) = 2^38，实际可用 38 位，但 Sv39 支持 39 位虚拟地址）。

### Q03_024 内存保护机制 (Memory Protection) 的实现形式更接近哪种？（Stallings Ch7.1）

硬件页表 + 软件指针检查双重保护

### Q03_025 逻辑内存组织 (Logical Memory Organization, Stallings Ch7.1)：进程地址空间中 text/data/heap/stack/mmap 各区域（或等价区间）是否由统一的映射管理结构（VMA/区间表/链表/BTreeMap 等）维护？（如存在请给结构体证据；不存在则写未发现等价结构）

是，使用 struct seg 链表维护。struct seg 包含 type（LOAD/TEXT/DATA/BSS/HEAP/MMAP/STACK）、addr（起始地址）、sz（大小）、flag（权限）、next（链表指针）等字段。进程控制块 struct proc 包含 segment 字段指向 seg 链表头。

### Q03_026 是否存在显式的硬件分段机制 (Hardware Segmentation, Stallings Ch7.4)？

纯分页无分段（RISC-V/AArch64 常见）

### Q03_027 取页策略 (Fetch Policy, Stallings Ch8.2) 更接近哪种？

按需调页 (Demand Paging)：缺页时才分配物理页

### Q03_028 放置策略 (Placement Policy, Stallings Ch8.2)：新的匿名映射或堆区域增长时，系统如何选择虚拟地址区间？（固定起始地址 / mmap_base 向下生长 / 首次适配 / 最佳适配 等；必须给实现证据或写未发现等价策略）

首次适配（first-fit）策略。lookup_segment() 在进程的 struct seg 链表中顺序查找第一个足够大的空闲间隙。对于 mmap，lookup_fixed_segment() 支持 MAP_FIXED 固定地址映射，否则使用 lookup_segment() 查找合适位置。

### Q03_029 是否存在驻留集管理/内存负载控制 (Resident Set Management / Load Control, Stallings Ch8.2)？（包括工作集动态调整、内存回收守护线程、OOM killer、驻留页数限制等；若 not_found 需列出已搜关键字）

未发现

### Q03_030 内存主链路（必须给出，尽量以 Mermaid graph TD 表达）：从确认的最强内存入口（缺页处理入口/mmap 入口/brk 入口/等价入口）出发，追踪到页表操作核心点或物理页分配核心点，写出 3-6 个关键节点。节点格式：FuncName [path:line]。若链路未被源码证据完全闭合，标注候选主链路而非确认的主链路。只画一条主链，不要并列展开多条支线。

graph TD\n    kerneltrap[kerneltrap kernel/trap/trap.c:206] --> handle_excp[handle_excp kernel/trap/trap.c:323]\n    handle_excp --> handle_page_fault[handle_page_fault kernel/mm/vm.c:1039]\n    handle_page_fault --> handle_page_fault_lazy[handle_page_fault_lazy kernel/mm/vm.c:1002]\n    handle_page_fault_lazy --> uvmalloc[uvmalloc kernel/mm/vm.c:417]\n    uvmalloc --> mappages[mappages kernel/mm/vm.c:280]\n    mappages --> allocpage[allocpage kernel/mm/pm.c:233]

### Q03_031 该系统更容易出现哪种内存碎片 (Memory Fragmentation, Stallings Ch7.2)？

外部碎片 (External Fragmentation)：空闲块分散无法满足大连续请求

### Q03_032 地址重定位 (Address Relocation, Stallings Ch7.1) 的绑定时机更接近哪种？

运行时动态绑定 (Run-time / Dynamic Relocation)：通过 MMU 基址 + 界限或页表在每次访问时转换

### Q03_033 页面置换的作用域策略 (Replacement Scope, Stallings Ch8.2) 更接近哪种？

未实现置换（无 swap）

### Q03_034 是否存在清理策略 (Cleaning Policy, Stallings Ch8.2)？（即脏页预先后台写回，而非仅在置换时才写回；搜索 background writeback / kswapd / cleaner_thread 或等价；必须三态；若 not_found 需列出已搜关键字）

已实现

---


# 第04章 进程线程调度与多核

### Q04_001 执行实体 (Execution Entity) 抽象是什么？
请按以下格式作答（每项必须有代码证据）：
- 顶层类型名: ___（如 Process / Task / Thread / TaskControlBlock）
- 结构体路径: ___
- 关键字段（至少列 3 个）: Context=___, State=___, PID=___, TrapFrame=___
- 是否区分 PCB 与 TCB: ___（是 / 否 / 待核实）

顶层类型名: struct proc (Process Control Block, PCB)
结构体路径: include/sched/proc.h:51-93
关键字段: Context=context (struct context, 68-80 行), State=state (enum procstate, 62 行), PID=pid (int, 54 行), TrapFrame=trapframe (struct trapframe*, 85 行)
是否区分 PCB 与 TCB: 否 (xv6-k210 仅使用统一的 struct proc 作为执行实体，无独立线程控制块)

### Q04_002 任务/进程的生命周期状态机有哪些状态与流转点？（Ready/Running/Blocked/Exited 等；需状态枚举/字段证据）

状态枚举 (include/sched/proc.h:38-42): RUNNABLE(就绪), RUNNING(运行), SLEEPING(阻塞/睡眠), ZOMBIE(僵尸)
状态流转点:
- RUNNABLE→RUNNING: scheduler() 中 __get_runnable_no_lock() 选中后设置 state=RUNNING (kernel/sched/proc.c:681 行)
- RUNNING→RUNNABLE: yield() 或 proc_tick() 超时，调用 __insert_runnable() (kernel/sched/proc.c:627 行/765 行)
- RUNNING→SLEEPING: sleep() 调用 __insert_sleep() (kernel/sched/proc.c:595 行)
- SLEEPING→RUNNABLE: wakeup() 调用 __insert_runnable(PRIORITY_IRQ) (kernel/sched/proc.c:379 行)
- RUNNING→ZOMBIE: exit() 设置 state=ZOMBIE 并 __remove() (kernel/sched/proc.c:447 行)
- ZOMBIE→释放: wait4() 找到 ZOMBIE 子进程后调用 freeproc() (kernel/sched/proc.c:513 行)

### Q04_003 是否存在上下文切换 (Context Switch) 实现（switch.S/__switch/swtch/context_switch）？（必须三态）

已实现

### Q04_004 上下文切换保存/恢复了哪些寄存器集合？（例如 RISC-V s0-s11；必须引用汇编/结构体证据）

保存/恢复的寄存器 (kernel/sched/swtch.S:7-30 行):
- ra (返回地址)
- sp (栈指针)
- s0-s11 (callee-saved 寄存器，共 12 个)
总计 14 个寄存器，每个 8 字节，共 112 字节。
对应 struct context 定义 (include/sched/proc.h:17-30 行): ra, sp, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11

### Q04_005 调度算法 (Scheduling Algorithm) 属于哪类？
请按格式作答：
- 算法名称: ___（必须是以下之一：FCFS / Round-Robin (RR) / Stride/Proportional-Share / MLFQ / CFS / Priority / 其他）
- 代码证据（关键字段/函数）: ___
  - RR: timeslice/slice 字段位置=___
  - Stride: stride 字段与比较逻辑位置=___
  - MLFQ: 多级队列 VecDeque/数组层级证据=___
  - Priority: priority 字段参与 pick_next 排序证据=___

算法名称: Priority (多级优先级调度 + 时间片超时降级)
代码证据:
- 优先级定义: kernel/sched/proc.c:239-243 行定义 PRIORITY_TIMEOUT(0), PRIORITY_IRQ(1), PRIORITY_NORMAL(2)
- 优先级队列: struct proc *proc_runnable[PRIORITY_NUMBER] (kernel/sched/proc.c:244 行)
- 时间片字段: struct proc 中 int timer (include/sched/proc.h:61 行)
- 超时降级: proc_tick() 中 timer 递减至 0 时从 PRIORITY_IRQ/NORMAL 降级到 PRIORITY_TIMEOUT (kernel/sched/proc.c:763-767 行)
- 调度选择: __get_runnable_no_lock() 按优先级顺序遍历 proc_runnable[0..2] (kernel/sched/proc.c:543-554 行)

### Q04_006 调度器 (Scheduler)核心入口/关键函数有哪些？（schedule/pick_next 等；给 1-3 个入口与证据）

核心入口函数:
1. scheduler() - 主调度循环 (kernel/sched/proc.c:671-711 行): 无限循环调用 __get_runnable_no_lock() 选进程，swtch() 切换上下文
2. __get_runnable_no_lock() - 进程选择 (kernel/sched/proc.c:543-556 行): 按优先级遍历 proc_runnable 队列
3. sched() - 触发切换 (kernel/sched/proc.c:714-749 行): 保存当前 context，swtch 到 cpu->context

### Q04_007 是否实现 fork/clone（创建新执行实体）？（必须三态）

已实现

### Q04_008 fork/clone 是否复制地址空间与文件表？（必须给复制路径证据；若 stub 需说明形态）

是，完整复制:
- 地址空间复制: kernel/sched/proc.c:303 行 np->segment = copysegs(p->pagetable, p->segment, np->pagetable)
- 文件表复制: kernel/sched/proc.c:321 行 copyfdtable(&p->fds, &np->fds)
- 当前目录复制: kernel/sched/proc.c:324 行 np->cwd = idup(p->cwd)
- 信号处理复制: kernel/sched/proc.c:310 行 sigaction_copy(&np->sig_act, p->sig_act)

### Q04_009 是否实现 exec（装载 ELF/重建地址空间）？（必须三态）

已实现

### Q04_010 是否实现 wait/waitpid（父子回收同步）？（必须三态）

已实现

### Q04_011 waitpid / wait4 的阻塞实现 (Blocking Implementation) 更接近哪种？

真正阻塞：移出就绪队列 + WaitQueue/条件变量唤醒 (Wait Queue or Condition Variable)

### Q04_012 PID 分配器实现是什么？（自增/bitmap/空闲栈复用/只分配不回收；必须给证据）

实现方式: 单调自增 (只分配不回收)
证据: kernel/sched/proc.c:229 行 p->pid = __pid++; 其中 __pid 是全局静态变量 (kernel/sched/proc.c:27 行)
PID 哈希表: pid_hash[HASH_SIZE] 用于快速查找 (kernel/sched/proc.c:28-29 行)
无回收机制: 未发现 free_pid 或 release_pid 函数，PID 单调递增不复用

### Q04_013 父子进程树如何存储？（children Vec/链表/parent+sibling 指针；必须给结构体字段证据）

存储方式: 链表 (child + sibling_next/sibling_pprev 指针)
结构体字段 (include/sched/proc.h:74-77 行):
- struct proc *child: 指向第一个子进程
- struct proc *parent: 指向父进程
- struct proc *sibling_next: 指向下一个兄弟进程
- struct proc **sibling_pprev: 指向前一个兄弟的 sibling_next 字段
遍历方式: 从 parent->child 开始，沿 sibling_next 遍历所有子进程 (kernel/sched/proc.c:485-517 行)

### Q04_014 是否实现信号 (signal) 或 futex？（若二者都无则 not_found；若只实现其一需说明并给证据）

已实现

### Q04_015 与 09 多核的交叉一致性：是否存在每核队列/任务迁移/IPI resched？（需与第 9 章互指证据或写不适用）

每核运行队列: 否 (全局共享 proc_runnable[PRIORITY_NUMBER] 队列，无 per-CPU 队列)
任务迁移: 不适用 (单全局队列，无需迁移)
IPI resched: 是 (kernel/sched/proc.c:386-389 行 wakeup() 中 sbi_send_ipi() 唤醒另一核)
多核调度: 全局 proc_lock 保护，两核竞争同一队列 (kernel/sched/proc.c:245 行)

### Q04_016 exit() 资源回收路径：调用链是什么？是否真正回收地址空间/文件表/通知父进程？（必须给调用链证据；桩则说明）

调用链 (kernel/sched/proc.c:413-456 行):
1. delsegs(p->pagetable, p->segment) - 删除用户段
2. uvmfree(p->pagetable) - 释放页表
3. dropfdtable(&p->fds) - 关闭文件描述符
4. iput(p->cwd) / iput(p->elf) - 释放 inode
5. 子进程重父: 将所有子进程挂载到 __initproc
6. 设置 ZOMBIE 状态: p->state = ZOMBIE; __remove(p)
7. 唤醒父进程: __wakeup_no_lock(p->parent)
8. 调用 sched() 切换到调度器
9. 父进程 wait4() 中 freeproc() 最终释放 PCB

### Q04_017 是否实现进程组/会话（Process Group / Session，pgid/session/set_sid/setpgid）？（必须三态；有则区分真实检查链 vs 仅占位字段）

未发现

### Q04_018 是否实现 POSIX 资源限制（rlimit/RLIMIT/getrlimit/setrlimit）？（必须三态；若 implemented 需说明支持的资源类型数量及软/硬限制机制）

桩实现

### Q04_019 该 OS 是否区分了 TCB（线程控制块）与 PCB（进程控制块）？

仅有统一 Task 结构（无区分）

### Q04_020 调度切换路径上是否存在页表切换（w_satp/sfence.vma/写 CR3/TTBR 等）？（必须三态；给调用点 路径 证据）

已实现

### Q04_021 用户线程与内核线程的映射模型 (User-Level Thread to Kernel-Level Thread Mapping) 更接近哪种？（Stallings Ch4）

仅内核线程（无独立用户线程库）

### Q04_022 是否实现线程局部存储 (Thread-Local Storage, TLS)？（必须三态；搜索 thread_local|TLS|__thread|#[thread_local]；若 implemented 需说明 TLS 的访问方式：tp 寄存器/段寄存器/其他）

未发现

### Q04_023 调度器是否追踪/优化以下哪些性能指标 (Scheduling Criteria, Stallings Ch9)？（多选；未发现则留空并在 notes 写 not_found）

["CPU 利用率 (CPU Utilization)", "周转时间 (Turnaround Time)", "等待时间 (Waiting Time)", "响应时间 (Response Time)"]

### Q04_024 优先级调度是否实现老化 (Aging, Stallings Ch9) 以防止低优先级进程饥饿 (Starvation)？（必须三态；搜索 age/aging/boost_priority 或等价；若 not_found 需说明是否存在饥饿风险）

未发现

### Q04_025 是否实现公平份额调度 (Fair-Share Scheduling, Stallings Ch9) 或 CPU 配额 (CPU Quota/cgroup)？（必须三态；搜索 fair_share/cgroup/cpu_quota/weight 等）

未发现

### Q04_026 调度器的抢占模式 (Preemption Mode, Stallings Ch9) 更接近哪种？

完全抢占 (Fully Preemptive)：时钟中断可随时抢占运行进程

### Q04_027 是否实现最短作业优先调度 (Shortest Job First / SJF 或 SRTF, Stallings Ch9)？（必须三态；或等价的基于预测 burst 时间的调度）

未发现

### Q04_028 该 OS 的多核形态更接近哪种？

SMP（对称多处理）

### Q04_029 是否存在 Secondary CPU / AP 启动链（BSP 唤醒 AP，上线后进入 idle/调度）？（必须三态）

已实现

### Q04_030 是否实现 IPI（核间中断）发送与处理？（必须三态）

已实现

### Q04_031 若存在 IPI：发送与处理路径分别在哪些函数/文件？（给关键入口与证据）

IPI 发送路径:
- sbi_send_ipi() 调用 (kernel/sched/proc.c:388 行 wakeup 函数; kernel/main.c:69 行 main 函数)
- SBI 实现位于 bootloader/SBI/rustsbi-k210 (bootloader/SBI/rustsbi-k210/src/main.rs:161-166 行 send_ipi_many)
IPI 处理路径:
- 通过 trap 机制处理，hart 从 while(started==0) 循环退出后继续初始化 (kernel/main.c:75-82 行)
- 无专用 ipi_handler 函数，IPI 仅用于唤醒 secondary CPU

### Q04_032 是否存在 per-CPU 变量/结构（PerCpu、CPU-local storage 等）？（必须三态）

已实现

### Q04_033 per-CPU 的实现方式是什么？（例如 TLS/tp 寄存器/gsbase/数组索引 hartid；需证据）

实现方式: 数组索引 + hartid
- 全局数组: struct cpu cpus[NCPU] (kernel/sched/proc.c:93 行)
- hartid 获取: cpuid() 函数读取当前 hart ID
- 访问方式: mycpu() 返回 &cpus[cpuid()] (kernel/sched/proc.c:96-99 行)
- tp 寄存器初始化: kernel/main.c:26 行 inithartid() 中 mv tp, hartid
struct cpu 定义未在 proc.h 中显式给出，但通过 mycpu()->proc 访问当前进程 (kernel/sched/proc.c:100 行)

### Q04_034 调度是否存在跨核负载均衡/迁移/亲和性？（必须三态）

未发现

### Q04_035 是否实现 TLB shootdown（跨核页表一致性刷新）？（必须三态；需与 03 互指）

未发现

### Q04_036 与 03/04/05/08 章的交叉一致性 (Cross-Chapter Consistency)，按以下四项分别作答（每项须给证据路径或写「单核不适用」）：
- 03 TLB: 多核页表修改后 TLB 刷新策略=___
- 04 调度: 每核运行队列/负载均衡/IPI resched=___
- 05 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上线顺序=___
- 08 锁: SpinLock 关中断行为在多核下是否安全=___

03 TLB: 多核页表修改后 TLB 刷新策略=未发现 TLB shootdown 实现，仅单核 sfence_vma() (kernel/sched/proc.c:685/688 行 scheduler 中)
04 调度: 每核运行队列/负载均衡/IPI resched=全局共享队列 proc_runnable[]，无 per-CPU 队列；IPI 仅用于 wakeup 唤醒 (kernel/sched/proc.c:388 行)
05 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上线顺序=hart0 先 trapinithart() 再唤醒 hart1，hart1 后 trapinithart() (kernel/main.c:47/79 行)
08 锁: SpinLock 关中断行为在多核下是否安全=需检查 spinlock 实现 (见 Q04_037)

### Q04_037 SpinLock 在获取锁时是否禁用中断（关中断保护临界区）？

是，获取时关中断、释放时恢复

### Q04_038 NCPU/MAXCPU（或等价宏）与链接脚本中的每 hart 栈/入口布局是否对应？（搜索 _max_hart_id 等；给宏定义与链接脚本对应证据，或写未发现）

NCPU 定义: include/param.h:5 行 #define NCPU 2
链接脚本: bootloader/SBI/rustsbi-k210/link-k210.ld:7 行 _max_hart_id = 1 (支持 2 核，hart0+hart1)
对应关系: NCPU=2 与 _max_hart_id=1 一致 (hart 编号 0-1)
每 hart 栈布局: kernel/main.c:88-92 行 shrink boot stack 中 kstack = boot_stack + hartid * 4 * PGSIZE

### Q04_039 是否使用 AtomicUsize/原子变量分配 PID/TID（全局唯一 ID 池）？（必须三态；给实现证据）

未发现

### Q04_040 是否支持实时调度 (Real-Time Scheduling, Stallings Ch10)？（必须三态；搜索 SCHED_FIFO / SCHED_RR / realtime / RT priority / deadline 等）

未发现

### Q04_041 是否存在 NUMA (Non-Uniform Memory Access) 感知的内存分配或调度策略？（必须三态；搜索 numa / node_id / local_memory 等；嵌入式单 SoC 可写 not_found 并说明架构）

未发现

---


# 第05章 文件系统与设备 IO

### Q05_001 VFS 抽象层 (Virtual File System, VFS)接口是什么形态？（Rust trait / C op 表；必须给接口定义证据）

C 语言函数指针结构体（op 表）形态。定义于 `include/fs/fs.h:44-78`，包含 `struct fs_op`（块设备操作）、`struct inode_op`（inode 操作）、`struct dentry_op`（目录项操作）、`struct file_op`（文件操作）四个操作表，每个表包含一组函数指针如 `alloc_inode`、`lookup`、`read`、`write` 等。

### Q05_002 具体文件系统后端 (Concrete File System Backend) 更接近哪种？

真实磁盘文件系统（FAT32/Ext4/其他，持久化存储）

### Q05_003 若支持 FAT32/Ext4：它是自研还是第三方库/crate？（必须引用 Cargo.toml/Cargo.lock 或 Makefile 引入证据）

自研实现。FAT32 后端代码位于 `kernel/fs/fat32/` 目录，包含 `fat32.c`（589 行）、`fat32.h`、`fat_cache.c` 等文件，直接编译进内核。Makefile（`Makefile:1-80`）显示为纯 C 项目，无外部 FS 库依赖。

### Q05_004 文件打开路径：文件打开入口（sys_open 或等价）→ VFS 层 → 具体 FS open。列出 3-6 个关键节点并给证据。

文件打开调用链：`sys_openat` (`kernel/syscall/sysfile.c:233`) → `nameifrom`/`namei` (`kernel/fs/fs.c:437`) → `lookup_path` (`kernel/fs/fs.c:352`) → `dirlookup` (`kernel/fs/fs.c:253`) → 具体 FS `fat_lookup_dir`（通过 `ip->op->lookup` 调用）。关键节点：1) `sys_openat` 解析路径并分配 fd；2) `lookup_path` 处理绝对/相对路径；3) `dirlookup` 逐级查找目录项；4) FAT32 `fat_lookup_dir` 读取磁盘目录。

### Q05_005 文件描述符表 (File Descriptor Table, FD Table) 的实现形态是什么？（固定数组/Vec/BTreeMap 等；必须给结构体定义证据）

固定数组 + 链表扩展形态。定义于 `include/fs/file.h:32-38`：`struct fdtable { uint16 basefd; uint16 nextfd; uint16 used; uint16 exec_close; struct file *arr[NOFILE]; struct fdtable *next; }`。主表为固定大小数组 `arr[NOFILE]`，通过 `next` 指针支持链表扩展。

### Q05_006 是否实现块缓存/缓冲缓存 (Block Cache / Buffer Cache, bcache)？（必须三态）

已实现

### Q05_007 若存在缓存：驱逐策略是什么（LRU/Clock/FIFO/无驱逐）？必须指出判断依据（字段/算法分支）证据。

LRU（最近最少使用）驱逐策略。证据：`kernel/fs/bio.c:88-118` 中 `bget()` 使用 `lru_head` 双向链表管理空闲 buffer，新分配的 buffer 从链表尾部（最久未使用）获取 (`struct d_list *dl = lru_head.prev`)；`bput()` 将释放的 buffer 加回链表头部 (`dlist_add_after(&lru_head, &b->list)`)，形成 LRU 队列。

### Q05_008 是否实现页缓存 (Page Cache)或与 mmap/文件映射共享缓存页？（必须三态）

已实现

### Q05_009 是否实现 mmap 的文件映射或匿名映射？（必须三态；若 stub 说明形态）

已实现

### Q05_010 是否实现 poll/select/epoll（或等价事件机制）？（必须三态）

已实现

### Q05_011 路径解析 (namei/path_walk/lookup) 是否实现并支持绝对/相对路径与 . ..？（必须三态）

已实现

### Q05_012 是否支持符号链接 (symlink) 的解析/跟随？（必须三态）

未发现

### Q05_013 是否实现管道 (pipe/pipe2) 并在 VFS 层作为文件对象？（必须三态；与 08 章 pipe 实现互指）

已实现

### Q05_014 是否实现网络 socket（作为 VFS 文件对象）？（必须三态）

未发现

### Q05_015 是否实现伪文件系统（devfs/procfs/sysfs）？（必须三态；若 implemented 需说明实现形态）

已实现

### Q05_016 文件描述符表的归属是哪种？

Per-Process（每进程独立 fd 表，fork 时复制/共享）

### Q05_017 文件数据块分配方式 (File Allocation Method, Stallings Ch12) 更接近哪种？

FAT 表内嵌空闲链（FAT32 特有）

### Q05_018 磁盘/存储空闲空间管理 (Free Space Management, Stallings Ch12) 更接近哪种？

FAT 表内嵌空闲链（FAT32 特有）

### Q05_019 目录结构 (Directory Structure, Stallings Ch12) 更接近哪种？

树形层次目录 (Tree-Structured Hierarchy)（最常见）

### Q05_020 文件内部记录组织 (File Record Organization, Stallings Ch12) 更接近哪种？

字节流 (Byte Stream / Unstructured)：无固定记录结构

### Q05_021 设备发现/枚举机制更接近哪种？

混合（多种并存）

### Q05_022 是否能在代码中证实解析了 `.dtb`/DeviceTree？（必须三态；若 implemented 必须指出解析入口）

已实现

### Q05_023 驱动框架接口是什么？（Rust Driver trait / C driver ops / 注册表；必须引用接口定义证据）

无统一驱动框架接口。驱动直接在 `kernel/main.c:main()` 中顺序初始化（`disk_init()` → `binit()` → `plicinit()` 等），无 driver trait/ops 注册表机制。块设备通过 `disk_read()`/`disk_write()` 函数指针间接调用具体驱动（sdcard/virtio）。

### Q05_024 驱动注册与初始化顺序是什么？（init_drivers/probe/driver_manager 等；列出 3-6 个关键节点并给证据）

初始化顺序（`kernel/main.c:43-62`）：1) `consoleinit()` (UART 早期输出)；2) `kpminit()` (物理内存管理)；3) `kvminit()` (内核页表)；4) `plicinit()` (中断控制器)；5) `disk_init()` (块设备驱动初始化)；6) `binit()` (块缓存)。无 driver_manager/probe 机制。

### Q05_025 是否实现 UART/Console 驱动用于早期输出？（必须三态）

已实现

### Q05_026 是否实现块设备驱动（virtio-blk/ramdisk/其他）？（必须三态）

已实现

### Q05_027 是否实现网络设备驱动（virtio-net/e1000/rtl8139 等）？（必须三态）

未发现

### Q05_028 是否实现中断控制器驱动（PLIC/CLINT/APIC 等）？（必须三态；需指出中断源到 handler 的分发证据）

已实现

### Q05_029 MMIO 地址来源是什么？（DTB 提供 / 常量硬编码 / 物理→虚拟转换；必须给证据）

常量硬编码。定义于 `include/memlayout.h:36-82`，如 `#define UART 0x10000000L` (QEMU) / `0x38000000L` (k210)，`#define VIRTIO0 0x10001000`，`#define PLIC 0x0c000000L`。通过 `VIRT_OFFSET` 转换为虚拟地址。

### Q05_030 多平台适配是如何通过构建/条件编译选择驱动的？（features/Kconfig/Makefile 规则；必须给证据）

Makefile 条件编译。`Makefile:1-28` 定义 `platform := k210` 或 `platform := qemu`，通过 `CFLAGS += -D QEMU` 切换平台。`include/memlayout.h:36-40` 使用 `#ifdef QEMU` 区分 UART/VIRTIO 地址。

### Q05_031 是否存在 MMU 启用前后串口地址切换（phys/virt 切换）逻辑？（必须三态）

已实现

### Q05_032 I/O 缓冲模式 (I/O Buffering) 最接近哪种？（Stallings Ch11：单缓冲 Single Buffer / 双缓冲 Double Buffer / 循环缓冲 Circular Buffer / 缓冲池 Buffer Pool / 无缓冲 No Buffer）

缓冲池 (Buffer Pool)

### Q05_033 块设备（磁盘/eMMC/NVMe）I/O 请求调度算法 (Scheduling Algorithm) (Disk Scheduling Algorithm) 更接近哪种？（Stallings Ch11；若无显式调度则选「FCFS 顺序提交」）

基于 virtio 环（queue 顺序提交，无显式磁盘调度）

### Q05_034 I/O 控制技术 (I/O Control Techniques, Stallings Ch11) 更接近哪种？

混合（小传输用中断，大传输用 DMA）

### Q05_035 是否实现 DMA (Direct Memory Access, Stallings Ch11) 传输路径？（必须三态；搜索 dma_alloc / dma_map / dma_buf / virtio 描述符环等；virtio 的描述符环也算 DMA 等价机制）

已实现

---


# 第06章 同步互斥与进程间通信

### Q06_001 该内核提供了哪些同步原语？（SpinLock/Mutex/RwLock/Semaphore/Condvar/WaitQueue 等；列出类型定义证据）

SpinLock、SleepLock（阻塞型 Mutex）、WaitQueue。定义证据：SpinLock 定义于 `include/sync/spinlock.h:7-13`（struct spinlock 含 locked 字段）；SleepLock 定义于 `include/sync/sleeplock.h:9-16`（struct sleeplock 含 locked 字段与内部 spinlock）；WaitQueue 定义于 `include/sync/waitqueue.h:16-24`（struct wait_queue 含 spinlock 与双向链表头，struct wait_node 为等待节点）。实现文件：`kernel/sync/spinlock.c`（acquire/release）、`kernel/sync/sleeplock.c`（acquiresleep/releasesleep）。

### Q06_002 Mutex 更接近哪种实现？

阻塞锁（Blocking Mutex，进入等待队列并挂起）

### Q06_003 是否存在等待队列 (Wait Queue, WaitQueue) 与 sleep/wakeup（或等价阻塞/唤醒）实现？（必须三态）

已实现

### Q06_004 sleep / wakeup 不变量 (Sleep-Wakeup Invariant) 分析，按格式填写：
- sleep 入口函数: ___（路径）
- 入睡前持有的锁: ___（无则写 none）
- 防丢 wakeup (Lost Wakeup Prevention) 机制: ___（如：持队列锁检查条件 / 无防护）
- wakeup 函数: ___（路径）
- 唤醒与锁释放顺序: ___（先唤醒后释放 / 先释放后唤醒 / 其他）

sleep 入口函数: `kernel/sched/proc.c:582` (sleep(void *chan, struct spinlock *lk))
入睡前持有的锁: proc_lock（通过__enter_proc_cs 获取）+ 调用者传入的 lk（先释放后在 sleep 返回后重新获取）
防丢 wakeup (Lost Wakeup Prevention) 机制: 持 proc_lock 检查条件并调用__insert_sleep() 将进程加入睡眠队列，确保在释放 lk 前已完成入队，wakeup 持 proc_lock 遍历睡眠队列，避免丢失唤醒
wakeup 函数: `kernel/sched/proc.c:392` (wakeup(void *chan))
唤醒与锁释放顺序: 先唤醒（__wakeup_no_lock 在 proc_lock 保护下执行）后释放（__leave_proc_cs 释放 proc_lock），符合 Stallings 描述的防丢 wakeup 不变量

### Q06_005 是否实现管道 (Pipe)？（必须三态）

已实现

### Q06_006 pipe 缓冲形态更接近哪种？

字节环形缓冲区 (ring buffer)

### Q06_007 pipe 的阻塞语义更接近哪种？

阻塞：挂起当前线程/任务进入等待队列

### Q06_008 是否实现消息队列/信号量/共享内存等 SysV IPC (Message Queue / Semaphore / Shared Memory, msg/sem/shm)？（必须三态；若仅实现其一需说明）

未发现

### Q06_009 是否实现 futex？（必须三态）

未发现

### Q06_010 是否实现信号机制（sigaction/kill/sigreturn/trampoline）？（必须三态）

已实现

### Q06_011 若实现 signal handler：用户态 handler 上下文如何构建？是否存在 sigreturn 恢复原 trap frame？（必须给证据）

上下文构建：在 `kernel/sched/signal.c:sighandle()`（行 178-258）中，内核分配 `struct sig_frame`（含 trapframe 指针、信号掩码、signum），保存当前用户态 trapframe 到新分配的内存，修改 p->trapframe 指向新的陷阱帧，设置 epc 为 sig_trampoline 地址，然后返回用户态执行 trampoline。sigreturn 存在：`kernel/sched/signal.c:263-283` 实现 `sigreturn()`，从 p->sig_frame 链表取出保存的原 trapframe，恢复 p->trapframe，释放 sig_frame 结构，完成上下文恢复。

### Q06_012 RwLock（读写锁 Reader-Writer Lock）的实现形态更接近哪种？

未发现/不支持

### Q06_013 底层原子操作来源更接近哪种？

自定义汇编（ldxr/stxr、lock xchg 等）

### Q06_014 死锁四必要条件（Coffman Conditions）在该内核中是否均成立？
请逐条作答（互斥 Mutual Exclusion / 持有并等待 Hold-and-Wait / 不可剥夺 No Preemption / 循环等待 Circular Wait），并结合 SpinLock/Mutex 的实现给出证据或写「不适用」。

1. 互斥 (Mutual Exclusion): 成立。SpinLock 通过原子交换指令保证同一时刻仅一个 CPU 持有锁（`kernel/sync/spinlock.c:34` amoswap.w.aq）；SleepLock 在 SpinLock 基础上增加睡眠语义，同样保证互斥。
2. 持有并等待 (Hold-and-Wait): 成立。`kernel/sched/proc.c:582-606` 的 sleep() 允许进程持有 lk 锁的同时释放 proc_lock 并进入睡眠，唤醒后重新获取 lk，存在持有资源等待其他资源的场景。
3. 不可剥夺 (No Preemption): 成立。SpinLock 持有期间不能被强制剥夺（只能由持有者主动 release）；SleepLock 持有者睡眠时锁仍被占用，其他进程只能等待。
4. 循环等待 (Circular Wait): 可能成立。内核存在多锁嵌套场景（如 pipe 操作同时持有 pi->lock 和 wait_queue->lock），但通过锁顺序规范预防（见 Q06_016）。

### Q06_015 内核对死锁 (Deadlock) 的处理策略更接近哪种？

死锁预防 (Deadlock Prevention)：通过锁顺序等消除 Coffman 必要条件

### Q06_016 是否存在全局锁顺序（Lock Ordering）规范或注释，以预防嵌套锁导致的循环等待死锁 (Circular Wait Deadlock)？（必须三态；若 implemented 需给出锁排序规则或 ABBA 锁检测代码证据）

已实现

### Q06_017 是否实现管程/条件变量 (Monitor / Condition Variable, Stallings Ch5)？（必须三态；搜索 Condvar / condition_variable / monitor / wait/notify/signal 等；若 implemented 需区分 Hoare 语义（等待者立即恢复）vs Mesa 语义（等待者重新竞争锁））

未发现

### Q06_018 经典同步问题验证 (Classic Synchronization Problems, Stallings Ch5)：
以下三个经典问题在该内核中是否有对应实现或测试？
- 生产者-消费者 (Producer-Consumer / Bounded Buffer)：___（implemented/not_found + 证据）
- 读者-写者 (Readers-Writers)：___（实现了读者优先/写者优先/公平？ + 证据）
- 哲学家就餐 (Dining Philosophers)：___（implemented/not_found）

生产者 - 消费者 (Producer-Consumer / Bounded Buffer)：not_found（grep 搜索 'producer.*consumer|bounded.*buffer' 未找到匹配；但 pipe 实现本质上是生产者 - 消费者模式，`kernel/fs/pipe.c` 使用环形缓冲 + 等待队列实现阻塞式读写，但未作为独立测试或示例代码存在）
读者 - 写者 (Readers-Writers)：not_found（grep 搜索 'reader.*writer' 未找到匹配；无 RwLock 实现，仅通过 pipe 的读写分离等待队列间接支持，但非标准读者 - 写者锁）
哲学家就餐 (Dining Philosophers)：not_found（grep 搜索 'dining.*philosoph' 未找到匹配）

### Q06_019 是否实现消息传递 (Message Passing, Stallings Ch5) 作为 IPC 机制？（必须三态；区分直接消息传递 Direct / 间接通过邮箱 Mailbox / POSIX mq_open 等；与 SysV msgq 的区别是是否通过内核邮箱路由）

未发现

### Q06_020 是否实现屏障同步 (Barrier Synchronization, Stallings Ch5)？（必须三态；搜索 barrier / sync_barrier / pthread_barrier 或等价；用于多线程/多核同步到同一检查点）

未发现

---


# 第07章 安全机制与权限模型

### Q07_001 特权级隔离形态更接近哪种？

有用户态/内核态隔离（user mode/kernel mode）

### Q07_002 是否存在凭证/权限数据结构（UID/GID/Credential/Capability/ACL 等）？（必须三态）

桩实现

### Q07_003 是否能证实在 syscall 路径上真实执行了权限检查（open/exec/write 等）？（必须三态；仅有字段不算 implemented）

未发现

### Q07_004 若存在权限检查：入口点与核心检查函数链路是什么？（列 2-5 个节点并给证据）

未发现权限检查链。grep 搜索 check_perm/inode_permission/access_check 无结果。sys_getuid 仅返回硬编码 0，execve 中 AT_UID/AT_GID 硬编码为 0，无真实权限检查函数调用。

### Q07_005 是否实现用户指针验证（access_ok/verify_area/UserInPtr/copyin/copyout 等）？（必须三态）

已实现

### Q07_006 是否实现 seccomp/prctl/sandbox 等系统调用过滤/沙箱？（必须三态；stub 需说明形态：ENOSYS/return 0）

未发现

### Q07_007 是否存在栈保护/溢出防护（stack canary/guard page）或等价机制？（必须三态）

桩实现

### Q07_008 是否存在审计/安全启动（audit/secure boot/signature）相关逻辑？（必须三态）

未发现

### Q07_009 本项目支持哪些架构（riscv64/aarch64/x86_64/loongarch64 等）？每种架构的安全相关初始化（特权级配置、PMP/MPU/SMEP 等）是否有代码证据？（必须逐架构作答，无证据写「未发现」）

仅支持 riscv64 架构。证据：Makefile 中 TOOLPREFIX=riscv64-unknown-elf；bootloader/SBI/rustsbi-k210/.cargo/config.toml 中 target="riscv64gc-unknown-none-elf"。特权级隔离通过 RISC-V SSTATUS_SPP 位实现（include/hal/riscv.h），用户/内核态切换通过 sret 指令（kernel/trap/trampoline.S）。未发现 PMP/MPU 配置代码。

### Q07_010 若项目使用 Rust，是否存在 RAII/所有权/生命周期相关的内核安全机制（如不可 unsafe 直接访问用户内存、锁的 RAII 自动释放等）？（必须三态；给具体模式证据）

未发现

### Q07_011 是否实现了内核/用户页表隔离 (Kernel/User Page Table Isolation, KPTI 或等价机制)？
（x86: CR3 KPTI / SMEP / SMAP；RISC-V: PMP / S-mode 分离；AArch64: TTBR0/TTBR1 隔离；
必须三态；无则写未发现并列出已搜关键字）

已实现

### Q07_012 UID/GID 字段是否在 syscall 路径上真实执行权限检查？（搜索 check_perm/inode_permission；若只有字段无检查链须标注「仅有定义但未强制执行 🔸」；给检查链证据或写「字段存在但无检查链」）

字段存在但无检查链。include/fs/stat.h 中 kstat 结构体有 uid/gid 字段，但 include/sched/proc.h 中 proc 结构体无 UID/GID 凭证字段。kernel/exec.c 中 AT_UID/AT_GID 硬编码为 0。grep 搜索 check_perm/inode_permission 无结果。sys_getuid 仅返回 0（🔸 桩函数）。

### Q07_013 访问控制模型 (Access Control Model, Stallings Ch15) 更接近哪种？

仅有特权级隔离（ring0/ring3），无细粒度访问控制

### Q07_014 是否实现完整性策略 (Integrity Policy, Stallings Ch15)？（如 Biba 模型、只读内核段、代码签名验证、W^X 内存保护等；必须三态）

桩实现

---


# 第08章 网络子系统与协议栈

### Q08_001 是否存在网络子系统实现（协议栈或 socket 层）？（必须三态）

未发现

### Q08_002 协议栈来源更接近哪种？

未发现

### Q08_003 是否实现 socket 系统调用接口（socket/bind/connect/sendto/recvfrom 等）？（必须三态）

未发现

### Q08_004 选择一个发送路径（优先 sys_sendto），追踪：syscall → 协议栈 → 网卡驱动。列 3-6 个关键节点并给证据。

未实现网络功能（❌ 未实现）。无法追踪发送路径，原因如下：
1. 无 sys_sendto 系统调用：include/sysnum.h 中无 SYS_sendto 定义
2. 无协议栈：全仓库 grep 未发现 tcp/udp/ip 等协议处理代码
3. 无网卡驱动：kernel/hal/ 仅有 virtio_disk.c（磁盘），无 virtio-net 或 e1000 等网卡驱动
4. 无 socket 抽象：include/fs/file.h 中文件类型仅支持普通文件/管道/设备，无 socket 类型

### Q08_005 是否实现网卡驱动（virtio-net/e1000 等）与收包中断路径？（必须三态）

未发现

### Q08_006 协议支持情况（多选；未发现则留空并在 notes 写 not_found）：

[]

not_found - 全仓库 grep 未发现 Ethernet/ARP/IPv4/IPv6/ICMP/UDP/TCP/DHCP/DNS 等协议实现代码

### Q08_007 是否存在零拷贝/共享缓冲/DMA 描述符等路径（zero-copy）？（必须三态；仅有名词不算 implemented）

未发现

---


# 第09章 调试机制与错误处理

### Q09_001 是否存在日志系统（log/printk/println 宏）与日志级别控制？（必须三态）

已实现

### Q09_002 是否存在 panic/崩溃处理路径（panic_handler/oom/abort 等）？（必须三态）

已实现

### Q09_003 panic 路径会输出哪些诊断？（寄存器 dump/栈回溯/停机；必须引用实现证据）

输出错误消息（含 CPU ID、文件路径、行号）、调用 backtrace() 打印栈帧返回地址、关闭中断并进入无限循环停机。无寄存器 dump。

### Q09_004 是否实现栈回溯 (backtrace/unwind/stack_trace)？（必须三态；仅打印 ra 不算）

已实现

### Q09_005 是否存在 **内核驻留的交互式监视器（kernel monitor）**？（对齐 Stallings《操作系统：精髓与设计原理》语境：**在内核态上下文**接受命令、用于探查/操控系统的监视器；**不包括**仅在用户态运行的常规 shell，如 `xv6-user/sh.c`、`user/` 下用户程序等——除非题面另有定义。必须三态；若 `implemented`：须给出 3–10 个 **用户可键入的 monitor 命令名** 及对应 **内核内** 解析/分发入口的 `路径:行号` 证据；仅以用户态 shell 充当内核 monitor 视为 **未切题** 应判 `stub` 或 `not_found` 并说明理由。）

已实现

### Q09_006 是否实现 GDB stub（需数据包解析循环，如 handle_gdb_packet）？（必须三态）

未发现

### Q09_007 错误码/错误类型体系是什么？（errno/Result/Error enum；给类型定义与传播点证据）

POSIX errno 风格宏定义（EPERM/ENOENT/ENOMEM 等），定义于 include/errno.h，无 Rust Result/Error enum。错误码通过系统调用返回值传播（负值表示错误）。

### Q09_008 是否存在 trace/perf/ftrace 等跟踪机制或 tracepoints？（必须三态）

已实现

---


# 第10章 开发历史与里程碑

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
*生成时间: 2026-04-24 13:37:26*  
*分析耗时: 20.3 分钟*
