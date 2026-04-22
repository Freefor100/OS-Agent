# oskernel2023-zmz 操作系统技术分析报告

> **年份**: 2023

> **赛事**: 操作系统赛

> **子赛事**: 内核实现赛道

> **学校**: 华中科技大学

> **队伍名称**: ZMZ

> **仓库地址**: https://gitlab.eduxiji.net/202310487101048/oskernel2023-zmz

> **分析日期**: 2026年04月22日

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

**一句话定位**：xv6-k210 是基于 xv6-riscv 移植的 RISC-V 64 位教学内核，采用 C/Rust 混合语言实现，支持 Kendryte K210 开发板与 QEMU 双平台运行，具备完整的多核调度、FAT32 文件系统与信号机制。

**子系统完成度矩阵**：

| 子系统 | 完成度 | 关键实现 |
|--------|--------|---------|
| 启动与 Trap/系统调用（第 02 章） | ✅完整 | 多核启动链、SBI 固件交接、用户/内核 trap 向量、50+ syscall 实现 |
| 内存管理（第 03 章） | ✅完整 | 双分配器 (single/multiple)、Sv39 页表、CoW/Lazy Allocation、mmap |
| 进程/调度与多核（第 04 章） | ✅完整 | struct proc PCB、多级优先级队列、swtch.S 上下文切换、IPI 唤醒 |
| 中断与系统调用（与第 02 章同源时可互引） | ✅完整 | scause 分发、trapframe 保存、syscall 分发表、用户指针校验 |
| 文件系统与设备 I/O（第 05 章） | ✅完整 | VFS 操作表、FAT32 自研实现、块缓存 LRU、virtio/SD 卡驱动 |
| 同步与 IPC（第 06 章） | ✅完整 | SpinLock/SleepLock、WaitQueue、pipe 环形缓冲、signal 机制 |
| 多核支持（与第 04 章同源时可互引） | ✅完整 | SMP 启动、per-CPU trap 栈、全局就绪队列、IPI 发送/处理 |
| 网络协议栈（第 08 章） | ❌缺失 | 未发现 socket/协议栈/网卡驱动代码 |
| 安全机制（第 07 章） | 🔸部分 | 用户/内核态隔离、DAC 权限位检查，UID/GID 仅为桩字段 |
| 调试与错误处理（第 09 章） | 🔸部分 | panic+ 栈回溯实现，日志级别/交互 monitor 为桩 |

## 评测与交付适配（启发式归纳）

- **Delivery**：Makefile 定义明确产物链：`target/kernel` (ELF 内核镜像)、`k210.bin` (烧录二进制)、`fs.img` (FAT32 磁盘镜像)。构建命令：`make build` 生成内核，`make fs` 创建文件系统镜像，`make sdcard dst=<mount>` 同步用户程序到 SD 卡。证据：`Makefile:1-50` 定义 platform/mode 变量与编译链，`Makefile:200-250` 定义 UPROGS 用户程序列表。
- **Harness**：存在自测框架但非标准化评测契约。`xv6-user/run_test.c` 定义 `unixben_testcode[]`、`cyclictest_testcode[]` 等测试脚本数组，支持 busybox/lua/libc 测试；`xv6-user/usertests.c` (2765 行) 为综合测试套件。未发现 `OS COMP`、`autograde`、`.github/workflows` 等 CI/评测专用信号（grep 仅命中注释提及"OS competition"历史背景）。
- **PlatformProfile**：README 与代码一致支持双平台：K210 开发板（默认）与 QEMU virt (`make run platform=qemu`)。代码通过 `#ifdef QEMU` 条件编译区分驱动（virtio_disk vs sdcard）、MMIO 地址（`include/memlayout.h`）、链接脚本（`linker/qemu.ld` vs `linker/k210.ld`）。与第 02/05 章结论一致：QEMU 使用 virtio-blk，K210 使用 SPI+SD 卡。
- **SubsystemDepth**：README 声称 12 项功能已实现，但第 07/08/09 章揭示风险缺口：(1) 安全机制仅有 mode 位 DAC 检查，UID/GID 字段未绑定权限验证（第 07 章 stub）；(2) 网络子系统完全缺失（第 08 章 not_found）；(3) 日志系统无级别控制，kernel monitor 仅为桩（第 09 章 stub）。与第 10 章演进历史对照：13 天开发周期优先实现核心功能，非关键特性留待后续迭代。

## 各模块技术全景（基于 02–10 章报告提取）

### 02 启动/架构与 Trap/系统调用

##### 技术清单
- 启动链与引导交接：固件/引导加载器 → 内核入口（SBI/OpenSBI 交接，RustSBI 子模块实现）
- 特权级与执行模式（硬件隔离模型）：RISC-V M-mode(SBI) → S-mode(内核) → U-mode(用户) 三级隔离
- MMU 与内核地址空间初建：kvminit() 在 MMU 启用前初始化页表，kvminithart() 设置 satp 启用 Sv39
- 同步异常与用户态陷阱入口（含 syscall 路径）：uservec(trampoline.S) → usertrap() → syscall() 分发
- 异步设备中断与中断控制器抽象：PLIC 驱动 (`kernel/hal/plic.c`) 处理外部中断，scause 区分中断/异常
- 时钟源与定时中断（tick/计账/抢占触发）：CLINT 定时器触发 timer interrupt，调用 yield() 实现抢占
- 用户内存访问与系统调用参数安全（copyin/out 等）：copyin2/copyout2 通过 struct seg 段检查 + badaddr 捕获机制

##### 关键实现、证据与细粒度锚点
- 入口汇编：`kernel/entry.S:10-21` 定义 `_entry` 标签，初始化栈后跳转 `main()`；`linker/linker64.ld` 定义 `ENTRY(_entry)` 基地址 `0x80020000`
- 多核启动链：`kernel/main.c:40-55` hart0 执行 `cpuinit()`→`kvminit()`→`procinit()` 后通过 `sbi_send_ipi()` 唤醒 AP；AP 执行 `floatinithart()`→`kvminithart()`→`scheduler()`
- Trap 向量设置：`kernel/trap/trap.c:150-160` 用户态 `w_stvec(TRAMPOLINE + (uservec - trampoline))`，内核态 `w_stvec((uint64)kernelvec)`
- Syscall 分发：`kernel/syscall/syscall.c:130-140` `syscalls[]` 数组注册 50+ syscall，`syscall()` 读取 `a7` 作为索引并边界检查
- TrapFrame 结构：`include/trap.h:15-70` `struct trapframe` 含 32 通用寄存器 +33FPU 寄存器，共 552 字节
- 用户指针校验：`kernel/mm/usrmm.c:200-220` `copyin2()` 调用 `partofseg()` 检查地址是否在 `struct seg` 链表定义的合法段内

##### 依赖与工具
- 外部依赖：RustSBI 子模块 (`sbi/psicasbi/`) 用 Rust 实现 M-mode SBI 固件，提供 `sbi_send_ipi()`、`sbi_clear_ipi()` 接口
- 构建工具：Makefile 通过 `platform` 变量选择链接脚本与入口汇编 (`entry_qemu.S` vs `entry_k210.S`)
- 调试工具：`include/hal/riscv.h` 封装 `r_stvec()`、`w_satp()`、`sfence_vma()` 等特权指令

##### 与相邻模块的衔接
- 与第 03 章页表切换衔接：`kvminithart()` 设置 `satp` 后，后续 trap 处理使用虚拟地址访问 UART 等 MMIO（第 03 章 Q03_019 TLB 刷新）
- 与第 04 章调度衔接：`usertrap()` 中时钟中断调用 `yield()` 触发 `sched()`→`scheduler()` 进程切换（第 04 章 Q04_006）
- 与第 06 章信号衔接：`usertrap()` 返回前检查 `p->killed` 与 pending signal，调用 `sighandle()` 构建用户态 handler 上下文（第 06 章 Q06_011）

### 03 内存管理

##### 技术清单
- 物理内存组织与页帧分配器：双分配器 (single 管理 400 页小内存，multiple 管理大内存区)，空闲链表 `struct run` 单链表
- 页表、地址空间与虚实地址转换：Sv39 三级页表，`walk()` 返回 PTE 指针，`mappages()` 建立映射，`sfence_vma()` 刷新 TLB
- 缺页与页面错误处理（含按需分页/惰性路径）：`handle_excp()` 捕获 EXCP_STORE/LOAD_PAGE → `handle_page_fault()` → `handle_page_fault_lazy()`
- 进程虚拟地址空间布局与映射接口：`struct seg` 链表统一管理 TEXT/DATA/BSS/HEAP/MMAP/STACK 段，`lookup_segment()` 首次适配分配
- 高级策略（CoW/Lazy/换页/mmap 等）：CoW 在 `uvmcopy()` 标记 `PTE_COW`，缺页时分配新页；Lazy 在 brk/mmap 时仅分配虚拟地址
- 页缓存或与 FS 块缓存的边界（归入本章或与第 05 章交叉说明）：未实现 Page Cache，仅 FS 层块缓存 (`kernel/fs/bio.c` LRU 驱逐)

##### 关键实现、证据与细粒度锚点
- 物理分配器：`kernel/mm/pm.c:220-240` `allocpage_n()` 从 `freelist` 首次适配，支持连续多页分配；`struct pm_allocator` 含 `spinlock` 锁
- 页表操作：`kernel/mm/vm.c:288-315` `mappages()` 遍历三级页表，若 `alloc=1` 则调用 `allocpage()` 创建中间页表
- 缺页处理：`kernel/mm/vm.c:1040-1091` `handle_page_fault()` 检查 `PTE_COW` 标志，写故障时分配新页并复制内容
- 段管理：`include/sched/proc.h:75-80` `struct proc` 含 `struct seg *segment` 链表头；`kernel/mm/usrmm.c:50-80` `allocseg()` 创建新段
- mmap 实现：`kernel/syscall/sysmem.c:50-80` `sys_mmap()` 调用 `do_mmap()`，`lookup_segment()` 从 `VUMMAP(0x70000000)` 向上查找空闲区间
- TLB 刷新：`include/hal/riscv.h:362` `sfence_vma()` 封装 `sfence.vma` 指令，在 `mappages()`/`uvmcopy()` 后调用

##### 依赖与工具
- 无外部 crate/库依赖，纯 C 实现
- 依赖第 02 章 trap 机制：缺页异常通过 `handle_excp()` 入口进入内存模块
- 构建配置：`include/memlayout.h` 定义 `PHYSTOP=0x80600000` (6MB 物理内存)、`KERNBASE=0x80020000`、`MAXVA=1L<<38` (Sv39)

##### 与相邻模块的衔接
- 与第 02 章 trap 衔接：`handle_excp()` 分发 EXCP_STORE_PAGE 到 `handle_page_fault()`（第 02 章 Q02_025）
- 与第 04 章进程衔接：`fork()` 调用 `uvmcopy()` 复制地址空间，CoW 标记 PTE（第 04 章 Q04_008）
- 与第 05 章 FS 衔接：`mmap()` 文件映射调用 `fileread()` 加载数据到页缓存（第 05 章 Q05_008 页缓存实现）

### 04 进程/调度与多核

##### 技术清单
- 进程或线程抽象与调度实体（PCB/TCB）：统一 `struct proc` 作为 PCB，无独立 TCB，含 `context`、`state`、`pid`、`trapframe` 字段
- 调度策略与就绪队列结构：多级优先级队列 `proc_runnable[PRIORITY_NUMBER]`，按 `PRIORITY_TIMEOUT/IRQ/NORMAL` 遍历
- 抢占模型与时间片/优先级（可协作则注明）：完全抢占，时钟中断递减 `p->timer`，超时降为 `PRIORITY_TIMEOUT` 并触发 `yield()`
- 上下文切换与内核栈/寄存器约定：`swtch.S` 保存/恢复 `ra/sp/s0-s11` 共 14 个寄存器到 `struct context`
- 生命周期（创建/执行/阻塞/退出/wait 与僵尸）：`allocproc()`→`scheduler()`→`sleep()`/`exit()`→`wait4()` 回收 ZOMBIE
- 多核、每 CPU 状态与 IPI/迁移（若适用）：SMP 架构，`tp` 寄存器存 hartid，`mycpu()` 数组索引访问 `cpus[id]`；IPI 仅用于启动，无任务迁移

##### 关键实现、证据与细粒度锚点
- PCB 结构：`include/sched/proc.h:38-107` `struct proc` 含 `state`(enum procstate)、`pid`(int)、`context`(struct context)、`trapframe`(struct trapframe*)
- 调度器：`kernel/sched/proc.c:663-693` `scheduler()` 无限循环调用 `__get_runnable_no_lock()` 选择进程，`swtch()` 切换上下文
- 优先级定义：`kernel/sched/proc.c:233-237` `PRIORITY_TIMEOUT=0`、`PRIORITY_IRQ=1`、`PRIORITY_NORMAL=2`
- 上下文切换：`kernel/sched/swtch.S:10-38` 汇编保存 `ra/sp/s0-s11` 到 `struct context`（`include/sched/proc.h:10-24`）
- 进程创建：`kernel/sched/proc.c:250-350` `clone()` 复制地址空间 (`copysegs()`)、文件表 (`copyfdtable()`)、信号处理 (`sigaction_copy()`)
- 多核启动：`kernel/main.c:78-80` hart0 调用 `sbi_send_ipi(mask, 0)` 唤醒 AP；`include/sched/proc.h:162` `cpuid()` 读 `tp` 寄存器

##### 依赖与工具
- 无外部库依赖，纯 C+ 汇编实现
- 依赖第 02 章 trap 机制：时钟中断调用 `yield()` 触发调度
- 依赖第 03 章内存：`clone()` 调用 `uvmcopy()` 复制页表，`exit()` 调用 `uvmfree()` 释放

##### 与相邻模块的衔接
- 与第 02 章 trap 衔接：`usertrap()` 中时钟中断调用 `yield()`→`sched()`→`scheduler()`（第 02 章 Q02_023）
- 与第 03 章内存衔接：`fork()` 调用 `uvmcopy()` 复制地址空间并标记 CoW（第 03 章 Q03_012）
- 与第 06 章同步衔接：`sleep()` 持有锁调用 `__remove()` 移出就绪队列，`wakeup()` 调用 `__insert_runnable()` 唤醒（第 06 章 Q06_004）

### 05 文件系统与设备 I/O

##### 技术清单
- VFS 与 inode/file 等对象模型：C 语言操作函数指针表 (`struct fs_op`/`struct inode_op`/`struct file_op`)，无 Rust trait
- 路径解析与挂载/命名空间：`lookup_path()` 遍历路径组件，调用 `ip->op->lookup` (FAT32 实现 `fat_lookup_dir()`)
- 具体文件系统实现形态：自研 FAT32 实现 (`kernel/fs/fat32/`)，FAT 表内嵌空闲链管理磁盘块
- 文件描述符与打开文件表：固定数组 `struct fdtable { struct file *arr[NOFILE]; }`，`NOFILE=16`，支持链表扩展
- 块缓存、写回与磁盘 I/O 路径：LRU 驱逐策略，`lru_head` 链表尾部驱逐最久未使用块，命中时移至头部
- 字符设备与块设备驱动框架（含 virtio 等）：条件编译选择 `virtio_disk_init()` (QEMU) 或 `sdcard_init()` (K210)

##### 关键实现、证据与细粒度锚点
- VFS 操作表：`include/fs/fs.h:53-78` 定义 `struct fs_op` (超级块操作)、`struct inode_op` (索引节点操作) 等函数指针表
- 路径解析：`kernel/fs/fs.c:412-458` `lookup_path()` 遍历路径，对每个目录组件调用 `dirlookup()`→`ip->op->lookup`
- FAT32 实现：`kernel/fs/fat32/fat32.c:22-38` 定义 `fat32_inode_op` 和 `fat32_file_op` 操作表，无外部 crate 依赖
- 文件描述符：`include/fs/file.h:34-40` `struct fdtable` 含 `arr[NOFILE]` 数组，`NOFILE=16` (`include/param.h:6`)
- 块缓存 LRU：`kernel/fs/bio.c:88-90` 定义 `static struct d_list lru_head`；`bio.c:147-163` 从 `lru_head.prev` 驱逐
- 驱动初始化：`kernel/hal/disk.c:19-24` 条件编译选择 `virtio_disk_init()` 或 `sdcard_init()`；`kernel/fs/bio.c:82-97` 初始化 `binit()`

##### 依赖与工具
- 无外部文件系统库，纯 C 自研 FAT32 实现
- 依赖第 02 章 syscall：`sys_openat()` 调用 `nameifrom()`→`lookup_path()` 进入 VFS 层
- 构建配置：Makefile 根据 `platform` 添加 `virtio_disk.c` 或 `sdcard.c`/`spi.c` 到编译列表

##### 与相邻模块的衔接
- 与第 02 章 syscall 衔接：`sys_write()` 调用 `filewrite()` 执行实际写操作（第 02 章 Q02_020）
- 与第 03 章内存衔接：`mmap()` 文件映射调用 `fileread()` 加载数据，与块缓存共享缓冲（第 03 章 Q03_016 页缓存未实现）
- 与第 06 章同步衔接：`pipe.c` 使用 `spinlock` 保护环形缓冲，读写阻塞调用 `sleep()`/`wakeup()`（第 06 章 Q06_006）

### 06 同步与 IPC

##### 技术清单
- 自旋锁与中断上下文临界区规则：`struct spinlock` 含 `locked` 字段，`acquire()` 使用 `__sync_lock_test_and_set` 原子操作，`push_off()` 关中断
- 可睡眠互斥与锁序/死锁约束（若述及）：`struct sleeplock` 含内部 `spinlock`，`acquiresleep()` 在锁被持有时调用 `sleep()` 挂起
- 等待队列、睡眠与唤醒：`struct wait_queue` 含 `lock` 和 `head` 双向链表，`wait_queue_add/del` 管理等待节点
- 管道等字节流 IPC：`pipe` 实现环形缓冲 (`struct pipe` 含 `data[PIPE_SIZE]`)，读写阻塞调用 `sleep()`/`wakeup()`
- 信号与异步通知：`struct sig_frame` 保存 handler 上下文，`sighandle()` 构建新 trapframe，`sigreturn()` 恢复原上下文
- 共享内存或 futex 等（若本仓库有）：未实现共享内存/futex，仅通过 `mmap()` 实现匿名/文件映射

##### 关键实现、证据与细粒度锚点
- SpinLock：`include/sync/spinlock.h:7-13` `struct spinlock` 含 `locked`、`name`、`cpu`；`kernel/sync/spinlock.c:29-32` `acquire()` 自旋
- SleepLock：`include/sync/sleeplock.h:9-16` `struct sleeplock` 含 `locked`、`lk`(spinlock)、`pid`；`kernel/sync/sleeplock.c:22-28` 阻塞等待
- WaitQueue：`include/sync/waitqueue.h:17-24` `struct wait_queue` 含 `lock` 和 `head`；`kernel/sched/proc.c:569` `sleep()` 入队
- Pipe 实现：`kernel/fs/pipe.c:90-102` `pipelock()` 先 `acquire(&q->lock)` 再 `sleep(wait->chan, &q->lock)` 实现生产者 - 消费者
- 信号处理：`kernel/sched/signal.c:173-224` `sighandle()` 分配 `sig_frame`，复制 trapframe，设置 `epc=SIG_TRAMPOLINE`
- 死锁预防：`kernel/sched/proc.c:410-429` `exit()` 重分配子进程给 `__initproc`，注释提及 parent-then-child 锁顺序

##### 依赖与工具
- 无外部库依赖，纯 C 实现
- 依赖第 04 章调度：`sleep()` 调用 `sched()` 切换进程，`wakeup()` 调用 `__insert_runnable()` 唤醒
- 底层原子操作：`__sync_lock_test_and_set`/`__sync_lock_release` 使用 RISC-V 原子指令 (amoswap)

##### 与相邻模块的衔接
- 与第 04 章调度衔接：`sleep()` 调用 `sched()` 进入调度器，`wakeup()` 将进程插入 `proc_runnable[]`（第 04 章 Q04_006）
- 与第 05 章 FS 衔接：`pipe.c` 作为 VFS 文件对象实现，`file_op->read/write` 调用 `piperead()/pipewrite()`（第 05 章 Q05_013）
- 与第 02 章 trap 衔接：`usertrap()` 返回前检查 `p->killed`，调用 `sighandle()` 处理 pending signal（第 02 章 Q02_024）

### 07 安全机制

##### 技术清单
- 硬件隔离与特权域模型：RISC-V U-mode/S-mode/M-mode 三级隔离，`sstatus.SPP` 位控制返回模式
- 访问控制模型（DAC/MAC/Capability 等，无则写不适用）：DAC (Discretionary Access Control)：基于 inode->mode 权限位 (owner/group/other)
- 用户指针验证与内核/用户空间数据拷贝边界：`copyin2()/copyout2()` 通过 `struct seg` 段检查 + `badaddr` 捕获机制
- 可执行空间保护与权限位策略（W^X 等）：未实现 W^X，页表权限位 `PTE_X` 可独立设置
- 其他沙箱或策略（seccomp/namespace/cgroup 等，无则写不适用）：不适用，未实现 seccomp/namespace/cgroup

##### 关键实现、证据与细粒度锚点
- 特权级切换：`kernel/trap/trap.c:175-185` `usertrapret()` 清除 `sstatus.SPP` 位，设置 `sepc` 返回 U-mode
- 权限检查桩：`kernel/syscall/sysfile.c:895` 注释 "// assume user as root"；`sys_faccessat()` 仅检查 `(ip->mode >> 6) & 0x7`
- 用户指针校验：`kernel/mm/usrmm.c:200-220` `copyin2()` 调用 `partofseg()` 检查地址是否在 `struct seg` 链表定义的合法段内
- PMP 初始化：`sbi/psicasbi/src/main.rs:161-187` Rust SBI 固件配置 PMP NAPOT 全访问权限（M-mode）
- UID/GID 桩：`kernel/syscall/sysproc.c:200-210` `sys_getuid()/sys_geteuid()` 均调用 `sys_getuid()` 返回 0

##### 依赖与工具
- 无外部安全库依赖
- 依赖第 02 章 trap 机制：`usertrapret()` 设置 `sstatus` 返回用户态
- 依赖第 03 章内存：`copyin2()` 使用 `struct seg` 段表进行地址合法性检查

##### 与相邻模块的衔接
- 与第 02 章 trap 衔接：`usertrapret()` 清除 `SPP` 位返回 U-mode，设置 `sepc` 为返回地址（第 02 章 Q02_004）
- 与第 05 章 FS 衔接：`sys_faccessat()` 调用 `nameifrom()` 获取 inode，检查 `ip->mode` 权限位（第 05 章 Q05_004）
- 与第 03 章内存衔接：`copyin2()` 使用 `struct seg` 段表验证用户指针，防止越界访问（第 03 章 Q03_020）

### 08 网络协议栈

##### 技术清单
- 套接字抽象与用户态 API：不适用，未实现 socket 系统调用
- 协议栈分层与数据面实现形态：未发现，无 TCP/IP 协议栈代码
- 网卡驱动与收发包/DMA 路径：未发现，无 virtio-net/e1000 等网卡驱动
- 与协议栈缓冲与 sk_buff 类抽象（若适用）：不适用
- 与文件层或块设备的衔接（若适用）：不适用

##### 关键实现、证据与细粒度锚点
- 无网络子系统代码：grep 搜索 `socket|tcp|udp|ethernet|virtio_net` 在 193 个文件中 0 命中
- 无网络 syscall：`include/sysnum.h` 无 `SYS_socket/SYS_bind/SYS_connect` 等调用号定义
- 无网卡驱动：`kernel/hal/` 目录仅含 `virtio_disk.c`、`sdcard.c` 块设备驱动，无网络驱动
- 无协议栈依赖：`Cargo.toml` 无 smoltcp/lwip 等协议栈 crate 依赖
- README 未声称网络功能：README.md Progress 清单 12 项功能无网络相关声明

##### 依赖与工具
- 无外部网络库依赖
- 无相关工具链配置

##### 与相邻模块的衔接
- 与第 05 章 FS 衔接：未实现 socket 作为 VFS 文件对象，`struct file_op` 无网络相关操作（第 05 章 Q05_014 not_found）
- 与第 02 章 syscall 衔接：无网络 syscall 注册到 `syscalls[]` 分发表（第 02 章 Q02_027）

### 09 调试与错误处理

##### 技术清单
- Panic/oops 与致命错误停机路径：`panic()` 输出消息 + 栈回溯（FramePointer 遍历），关中断并死循环停机
- 日志级别与可观测输出：桩实现，`printf()` 无级别控制，`debug.h` 宏 `__debug_info()` 依赖 `DEBUG` 编译选项
- 栈回溯与符号化/调试钩子：`panic()` 调用 `backtrace()` 遍历 FramePointer，打印 `ra` 寄存器值，无符号化
- 断言与运行时检查：`assert()` 宏定义于 `include/utils/debug.h`，失败时调用 `panic()`
- 系统调用级追踪或 strace 类能力：桩实现，`xv6-user/strace.c` 为用户态程序，内核无 tracepoints/ftrace 支持

##### 关键实现、证据与细粒度锚点
- Panic 路径：`kernel/printf.c:100-120` `panic()` 调用 `backtrace()` 打印栈帧，随后 `for(;;) ;` 死循环
- 栈回溯：`kernel/printf.c:80-95` `backtrace()` 遍历 `fp` (FramePointer)，打印 `ra` 值，无符号解析
- 日志宏：`include/utils/debug.h:20-30` `__debug_info()` 依赖 `#ifdef DEBUG` 编译选项，无运行时级别控制
- 断言：`include/utils/debug.h:10-15` `assert(x)` 定义为 `if(!(x)) panic("assertion failed: %s", #x)`
- strace 桩：`xv6-user/strace.c` 为用户态测试程序，内核无 `ptrace` 或 syscall 追踪钩子

##### 依赖与工具
- 无外部调试库依赖
- 依赖第 02 章 trap 机制：`usertrap()` 中非法访问触发 `panic()`
- 构建配置：`Makefile:20-25` `CFLAGS += -DDEBUG` 启用调试宏

##### 与相邻模块的衔接
- 与第 02 章 trap 衔接：`handle_excp()` 处理未知异常时调用 `panic()`（第 02 章 Q02_007）
- 与第 04 章进程衔接：`exit()` 资源回收失败时调用 `panic()`（第 04 章 Q04_016）
- 与第 03 章内存衔接：`allocpage()` 内存耗尽时调用 `panic("out of memory")`（第 03 章 Q03_004）

### 10 演进与历史

##### 技术清单
- 活跃时间范围与提交规模：13 天 (2023-08-09 至 2023-08-21)，48 commits，+52,533 行/-6,844 行
- 核心贡献者与模块分工：zrhxlhydjcx(25 commits, 内核核心逻辑)、ZEMINGMA(23 commits, SBI 集成与构建系统)
- 重大重构或技术里程碑：初始骨架搭建 (b7ffeec)、信号机制重构 (df1fdc3)、用户程序加载完善 (d17dd26)
- 文档与工程化沉淀：README 声明 12 项功能，doc/目录存架构图与运行截图，无 CHANGELOG/CI 配置

##### 关键实现、证据与细粒度锚点
- 提交历史：`get_git_history_summary` 输出 48 commits，密度最高模块为 `kernel/`、`xv6-user/`、`sbi/`
- 贡献者分工：`analyze_authors_contribution` 输出 zrhxlhydjcx 专注 `kernel`(25,466 行)、`include`(8,053 行)；ZEMINGMA 专注 `sbi`(2,471 行)、`tools`(1,813 行)
- 里程碑 1：commit `b7ffeec` (+42,627 行) 引入完整 xv6-riscv 骨架，含 `Makefile`、`kernel/`、`include/`、`xv6-user/`
- 里程碑 2：commit `df1fdc3` (+1,751/-1,839 行) 重构信号机制，迁移 `mesg/signal.c`→`sched/signal.c`，引入 `sig_trampoline.S`
- 里程碑 3：commit `d17dd26` (+869/-55 行) 恢复动态链接器加载，引入 `show_vm_load()` 内存调试工具与 `Guess.c` 测试程序
- 技术债务：`kernel/exec.c` 残留调试打印 (`printf("NNN: ...")`)、临时注释 (`//-------------A1!!!!!!!!!!`)

##### 依赖与工具
- Git 版本控制：48 commits 记录演进轨迹
- 构建工具：Makefile 随演进增加平台切换、SBI 集成规则
- 文档工具：doc/img/目录存架构图 (boot.jpg、mem_map.jpg、proc.jpg 等) 与运行截图

##### 与相邻模块的衔接
- 与第 02 章启动衔接：里程碑 1 引入多核启动链 (`kernel/main.c`)，里程碑 3 完善用户程序加载 (`kernel/exec.c`)
- 与第 06 章同步衔接：里程碑 2 重构信号机制 (`kernel/sched/signal.c`)，将信号从"消息传递"迁移至"进程调度"抽象
- 与第 05 章 FS 衔接：README 声明 FAT32 已实现，但第 10 章揭示 `kernel/fs/fat32/fat.c:336` 注释"FAT 表缓存层未实现"

## 技术栈与构建（编程语言版本、框架、依赖、支持的架构完整列表）

**编程语言**：
- **C** (91 个文件)：内核核心逻辑 (`kernel/`)、头文件 (`include/`)、用户程序 (`xv6-user/`)
- **Rust** (22 个文件)：SBI 固件 (`sbi/psicasbi/`)，使用 `#![no_std]` 裸机环境
- **汇编** (RISC-V)：启动代码 (`kernel/entry*.S`)、上下文切换 (`kernel/sched/swtch.S`)、trap 向量 (`kernel/trap/*.S`)
- **Python** (2 个文件)：烧录工具 (`tools/kflash.py`、`tools/ktool.py`)
- **Makefile**：构建系统主脚本 (294 行)

**构建工具**：
- **GNU Make**：主构建系统，支持 `platform=k210|qemu`、`mode=debug|release` 配置
- **Cargo**：Rust SBI 子项目构建 (`sbi/psicasbi/Cargo.toml`)
- **RISC-V GCC**：`riscv64-linux-gnu-gcc` 编译 C 代码，`-mcmodel=medany`、`-ffreestanding` 裸机选项
- **QEMU**：`qemu-system-riscv64` 模拟器，`-machine virt` 平台

**支持的架构**：
- **riscv64** (唯一支持)：`include/hal/riscv.h` 定义 RISC-V 特权指令封装，`linker/linker64.ld` 链接脚本针对 RV64
- 未发现 aarch64/x86_64/loongarch64 支持（grep 搜索 0 命中）

**外部依赖**：
- **RustSBI** (`sbi/psicasbi/`)：Rust 实现的 SBI 固件，提供 M-mode 服务（IPI、定时器、串口）
- **无其他第三方库**：文件系统、网络协议栈、同步原语均为自研 C 实现

**构建产物**：
- `target/kernel`：ELF 格式内核镜像
- `k210.bin`：K210 烧录二进制（ELF 转换）
- `fs.img`：FAT32 磁盘镜像（含用户程序）
- `sbi/sbi-k210`、`sbi/sbi-qemu`：平台特定 SBI 固件

## 目录结构导读（关键目录与源码入口）

**核心目录布局**：
- **`kernel/`** (内核核心，约 26KB 代码)：
  - `entry*.S`：平台特定入口汇编 (`_entry`/`_start` 标签)
  - `main.c`：C 入口 `main()`，多核初始化与调度器启动
  - `trap/`：中断/异常处理 (`trap.c`、`kernelvec.S`、`trampoline.S`)
  - `syscall/`：系统调用分发 (`syscall.c`) 与实现 (`sysfile.c`、`sysproc.c`)
  - `mm/`：内存管理 (`vm.c` 页表、`pm.c` 物理分配、`kmalloc.c` 小对象分配)
  - `sched/`：进程调度 (`proc.c` PCB、`swtch.S` 上下文切换、`signal.c` 信号)
  - `fs/`：文件系统 (`fs.c` VFS、`fat32/` FAT32 实现、`bio.c` 块缓存)
  - `hal/`：硬件抽象层 (`virtio_disk.c`、`sdcard.c`、`plic.c` 中断控制器)
  - `sync/`：同步原语 (`spinlock.c`、`sleeplock.c`)

- **`include/`** (头文件，约 8KB 定义)：
  - `fs/`：VFS 操作表 (`fs.h`)、文件描述符 (`file.h`)、FAT32 结构 (`stat.h`)
  - `mm/`：内存管理接口 (`vm.h`、`pm.h`、`mmap.h`)
  - `sched/`：进程/信号定义 (`proc.h`、`signal.h`)
  - `hal/`：RISC-V 特权指令 (`riscv.h`)、设备 MMIO 地址 (`memlayout.h`)

- **`xv6-user/`** (用户程序，约 58KB 代码)：
  - `sh.c`：shell 解释器 (661 行)
  - `usertests.c`：综合测试套件 (2765 行)
  - `run_test.c`：外部测试框架 (busybox/lua/libc)
  - `Guess.c`、`timer.c`：实验性测试程序

- **`sbi/psicasbi/`** (Rust SBI 固件)：
  - `src/main.rs`：SBI 入口，PMP 初始化
  - `src/trap/`：SBI trap 处理 (`sbi/legacy.rs` 处理 IPI)
  - `src/hal/`：K210 硬件抽象 (`sysctl/k210.rs` 时钟配置)

- **`linker/`** (链接脚本)：
  - `linker64.ld`：通用 RV64 链接脚本，`ENTRY(_entry)`，基地址 `0x80020000`
  - `qemu.ld`、`k210.ld`：平台特定脚本（MMIO 地址差异）

- **`tools/`** (烧录工具)：
  - `kflash.py`：K210 串口烧录脚本 (179KB)
  - `ktool.py`：K210 通信工具 (134KB)

- **`doc/img/`** (文档与架构图)：
  - `boot.jpg`：启动链架构图
  - `mem_map.jpg`：内存布局图
  - `proc.jpg`：进程状态转换图
  - `xv6-k210_run.gif`：K210 运行演示

**源码入口追踪**：
1. 汇编入口：`kernel/entry.S:10` `_entry` 标签 → 初始化栈 → 跳转 `main()`
2. C 入口：`kernel/main.c:40` `main(hartid, dtb_pa)` → hart0 初始化 → `sbi_send_ipi()` 唤醒 AP → `scheduler()`
3. Trap 入口：`kernel/trap/trampoline.S:20` `uservec` 标签 → 保存 trapframe → 调用 `usertrap()`
4. Syscall 入口：`kernel/syscall/syscall.c:100` `syscall()` → 读取 `a7` → 分发到 `syscalls[a7]`

## 总结评价（完成度评估）

xv6-k210 项目在 13 天开发周期内完成了从 xv6-riscv 到 K210 开发板的移植，实现了教学内核的核心功能闭环。启动与 Trap/系统调用（第 02 章）、内存管理（第 03 章）、进程/调度与多核（第 04 章）、文件系统与设备 I/O（第 05 章）、同步与 IPC（第 06 章）等核心子系统均达到"完整实现"级别，具备多核启动、Sv39 页表、CoW/Lazy Allocation、FAT32 文件系统、优先级调度、信号机制等高级特性。

然而，项目存在明显的功能缺口：网络协议栈（第 08 章）完全缺失，未实现 socket/协议栈/网卡驱动；安全机制（第 07 章）仅为部分实现，UID/GID 字段未绑定权限验证，仅依赖 mode 位 DAC 检查；调试与错误处理（第 09 章）中日志级别控制与 kernel monitor 为桩实现。这些缺口反映教学项目的典型特征：优先实现核心功能以通过评测，非关键特性（网络、安全）留待后续迭代。

技术债务方面，代码中存在调试打印残留（`exec.c` 的 `printf("NNN: ...")`）、临时注释（`//-------------A1!!!!!!!!!!`）、未实现功能标注（`fat.c:336`"FAT 表缓存层未实现"），需在后续维护中清理。总体而言，xv6-k210 为 K210 开发板提供了可运行的 xv6 移植版本，支持 FAT32 文件系统、多核调度、信号机制等高级特性，为后续课程实验（如添加系统调用、优化调度算法）奠定基础，但距离生产级内核仍有较大差距。

---


# 第02章 启动架构与 Trap系统调用

### Q02_001 启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）

链接脚本 `linker/linker64.ld` 定义 `ENTRY(_entry)`，基地址 `0x80020000`。汇编入口在 `kernel/entry.S`（通用）、`kernel/entry_qemu.S`（QEMU 平台）、`kernel/entry_k210.S`（K210 板）中的 `_entry` 标签（K210 使用 `_start`）。入口汇编初始化栈后跳转到 C 入口 `main()`（`kernel/main.c`）。

### Q02_002 启动链更接近哪种交接方式？

固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）

### Q02_003 是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）

implemented

### Q02_004 模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）

RISC-V sstatus 寄存器：SSTATUS_SPP(位 8，Previous mode)、SSTATUS_SPIE(位 5)、SSTATUS_SIE(位 1)、SSTATUS_FS(位 13-14，FPU 状态)。satp 寄存器控制页表基址。stvec 设置 trap 向量基址。sepc 保存异常返回地址。

### Q02_005 是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）

implemented

### Q02_006 从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）

_entry(汇编入口) → main(hart0) → cpuinit/floatinithart/consoleinit/kvminit/kvminithart/trapinithart/procinit/plicinit/disk_init/binit/userinit → scheduler()。多核：hart0 通过 sbi_send_ipi() 唤醒其他 hart，其他 hart 执行 floatinithart/kvminithart/trapinithart/plicinithart → scheduler()。

### Q02_007 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）

BSS 清零：not_found [linker/linker64.ld 定义 sbss_clear/ebss_clear 符号，但 entry.S 中未见显式清零代码]
早期串口输出：implemented [kernel/main.c: consoleinit() 在 hart0 初始化早期串口]
设备树解析：not_found [kernel/main.c main() 接收 dtb_pa 参数但未发现解析 DTB 的代码]
页表初始化时机：implemented [kernel/mm/vm.c: kvminit() 在 MMU 启用前初始化页表，kvminithart() 设置 satp 启用 MMU]

### Q02_008 是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）

implemented

### Q02_009 是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）

implemented

### Q02_010 构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）

Makefile 通过 platform 变量选择：`make run platform=qemu` 使用 QEMU 平台，默认使用 K210 板。链接脚本：`linker/linker64.ld`（通用）、`linker/qemu.ld`、`linker/k210.ld`。入口汇编：`kernel/entry.S`（通用）、`kernel/entry_qemu.S`、`kernel/entry_k210.S`。代码中通过 `#ifdef QEMU` 条件编译区分平台。

### Q02_011 对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）

implemented

### Q02_012 MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）

implemented

### Q02_013 是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）

implemented

### Q02_014 是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）

支持双平台：QEMU virt 和 K210 开发板。通过 `#ifdef QEMU` 条件编译区分。入口汇编：`kernel/entry_qemu.S`（QEMU）和 `kernel/entry_k210.S`（K210，使用 `_start` 标签）。链接脚本：`linker/qemu.ld` 和 `linker/k210.ld`。未发现 VisionFive2/JH7110/LoongArch 支持。

### Q02_015 trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）

内核 trap 向量：`kernel/trap/kernelvec.S` 的 `kernelvec` 标签（通过 `w_stvec((uint64)kernelvec)` 设置）。用户 trap 向量：`kernel/trap/trampoline.S` 的 `uservec` 标签（通过 `w_stvec(TRAMPOLINE + (uservec - trampoline))` 设置）。

### Q02_016 trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？

用户地址空间预留页（trampoline/trap_context page）

### Q02_017 TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）

定义在 `include/trap.h` 的 `struct trapframe`。包含 32 个通用寄存器（ra/sp/gp/tp/t0-t6/s0-s11/a0-a7）和 33 个 FPU 寄存器（ft0-ft11/fs0-fs11/fa0-fa7/fcsr），共 65 个寄存器字段。结构体大小：552 字节（0-544 字节为寄存器，544-552 字节为 fcsr）。

### Q02_018 是否存在系统调用分发表（syscall table / match 分发）？（必须三态）

implemented

### Q02_019 系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）

implemented

### Q02_020 选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。

sys_write 调用链：1. 用户态 ecall 指令（a7=SYS_write=64）→ 2. usertrap() 捕获 EXCP_ENV_CALL → 3. syscall() 读取 a7 作为 syscall 号 → 4. syscalls[SYS_write] 分发到 sys_write() → 5. sys_write() 调用 argfd() 获取文件描述符，argaddr() 获取缓冲区地址，argint() 获取长度 → 6. filewrite() 执行实际写操作。

### Q02_021 列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。

sys_fork: implemented [kernel/syscall/sysproc.c: sys_fork() 调用 clone(0, NULL)]
sys_exec: implemented [kernel/syscall/sysproc.c: sys_exec() 调用 execve()]
sys_write: implemented [kernel/syscall/sysfile.c: sys_write() 调用 filewrite()]
sys_openat: implemented [kernel/syscall/sysfile.c: sys_openat() 实现文件打开]
sys_mmap: implemented [kernel/syscall/sysmem.c: sys_mmap() 调用 do_mmap()]
sys_munmap: implemented [kernel/syscall/sysmem.c: sys_munmap() 调用 do_munmap()]
sys_clone: implemented [kernel/syscall/sysproc.c: sys_clone() 调用 clone()]
sys_kill: implemented [kernel/syscall/syssignal.c: sys_kill() 调用 kill()]
sys_brk: implemented [kernel/syscall/sysmem.c: sys_brk() 调用 growproc()]
sys_wait4: implemented [kernel/syscall/sysproc.c: sys_wait4() 调用 wait4()]

### Q02_022 是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）

implemented

### Q02_023 时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）

implemented

### Q02_024 是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）

implemented

### Q02_025 缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）

存在联动。trap 入口：`kernel/trap/trap.c` 的 `handle_excp()` 处理 EXCP_STORE_PAGE/EXCP_LOAD_PAGE/EXCP_INST_PAGE，调用 `handle_page_fault(type, r_stval())`。`handle_page_fault()` 在 `kernel/mm/vm.c` 中实现，处理 CoW（写时复制）和 lazy allocation（懒分配）。CoW 机制：`kernel/mm/vm.c` 的 `uvmcopy()` 中标记 PTE_COW，缺页时分配新页。

### Q02_026 与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）

多核初始化顺序一致。hart0 先完成初始化（cpuinit→kvminit→kvminithart→trapinithart→procinit→plicinit），然后通过 sbi_send_ipi() 发送 IPI 唤醒其他 hart。其他 hart 执行 floatinithart→kvminithart→trapinithart→plicinithart→scheduler()。trapinithart() 在每个 hart 上独立设置 stvec，确保 per-CPU trap 向量正确。时钟初始化：timerinit() 在 hart0 初始化 tickslock，set_next_timeout() 在每个 hart 上设置定时器。

### Q02_027 Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）

分发表路径：kernel/syscall/syscall.c (syscalls[] 数组)
完整实现 ✅ (implemented): 约 50 个（sys_fork/sys_exec/sys_write/sys_read/sys_openat/sys_close/sys_mmap/sys_munmap/sys_clone/sys_kill/sys_brk/sys_wait4 等均有实际实现）
桩/ENOSYS/return 0 🔸 (stub): 约 5 个（sys_rt_sigtimedwait 返回 0，sys_getuid/sys_geteuid/sys_getgid/sys_getegid 均调用 sys_getuid 返回 pid）
未注册 ❌ (not_found): 0 个（所有 sysnum.h 中定义的 syscall 号都在 syscalls[] 中有注册）
统计依据：grep_in_repo 搜索 syscalls[] 数组和 sys_ 函数实现，对比 include/sysnum.h 中的 syscall 号定义

### Q02_028 README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）

README.md 未明确声称兼容特定 syscall 标准或列出 syscall 表。README 主要描述：支持多核启动、内存分配、页表、定时器中断、S 模式外部中断、串口接收、SD 卡驱动、进程管理、文件系统、用户程序。代码中实现了大量 POSIX-like syscall（fork/exec/wait/read/write/open/close/mmap/munmap/kill 等），与 README 声称的"进程管理"和"文件系统"功能一致。

### Q02_029 `_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）

未见该命名模式。grep_in_repo 搜索 `_impl\b|sys_[a-z0-9_]*_impl` 在 191 个文件中 0 命中。该仓库采用直接实现 syscall 的方式（如 sys_write() 直接在 sysfile.c 中实现），未使用 `_impl` 后缀分离接口与实现的命名模式。

### Q02_030 是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）

implemented

### Q02_031 非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）

not_found

### Q02_032 信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）

仅支持进程级信号发送。实现了 sys_kill()（kernel/syscall/syssignal.c），调用 kill(pid, sig) 向进程发送信号。未发现 sys_tkill（线程级）或 sys_tgkill（进程组级）实现。kill() 函数在 kernel/sched/signal.c 中实现，通过 pid 查找进程并设置 p->killed。

### Q02_033 中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）

通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）

### Q02_034 是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）

not_found

---


# 第03章 内存管理物理虚拟分配器

### Q03_001 该 OS 的内存管理实现语言/形态更接近哪类？（只选最贴近的一项）

C/Makefile 风格内核（xv6 类）

### Q03_002 是否存在“物理页帧分配器 (Physical Frame Allocator)”的真实实现？（必须三态）

implemented

### Q03_003 物理内存分配算法更接近哪种？

空闲链表 run list（xv6 风格）

### Q03_004 物理页帧分配器的核心数据结构是什么？（例如 bitmap 数组、buddy free list、slab cache 表、`struct run` 单链表等；必须引用结构体/字段证据）

struct run 单链表 + struct pm_allocator 双分配器（single/multiple）。struct run 含 next 指针和 npage 字段表示连续页数；struct pm_allocator 含 spinlock 锁、freelist 链表头、npage 计数。single 管理 400 页小内存区，multiple 管理大内存区。

### Q03_005 物理分配器的并发控制锁粒度是什么？（全局大锁 / per-CPU / 分桶 / 无锁+关中断 / 其他；必须给锁对象类型与持锁范围证据）

全局自旋锁（struct spinlock），分 single/multiple 两把独立锁。持锁范围覆盖整个 allocpage_n/freepage_n 操作。使用 acquire/release 加锁解锁，宏__enter_mul_cs/__leave_mul_cs 包裹临界区。

### Q03_006 是否存在“页表 (page table) 结构体 + walk/map/unmap”的真实实现？（必须三态）

implemented

### Q03_007 页表操作 API（walk/map/unmap 或等价）对应的函数名/模块是什么？列出 1-3 个关键入口并给证据。

关键入口：walk(pagetable_t, uint64 va, int alloc) 返回 PTE 指针；mappages(pagetable_t, uint64 va, uint64 size, uint64 pa, int perm) 建立映射；unmappages(pagetable_t, uint64 va, uint64 npages, int flag) 解除映射。均在 kernel/mm/vm.c 中实现。

### Q03_008 页表修改路径的并发控制是什么？（锁粒度、是否需要关中断、是否使用每进程地址空间锁等；必须引用锁/临界区证据）

依赖进程地址空间隔离，无显式每进程页表锁。关键路径在 trap 处理中已关中断。页表修改后调用 sfence_vma() 刷新 TLB。fork 时 uvmcopy 完成后调用 sfence_vma()。

### Q03_009 内核与用户地址空间关系更接近哪种？

共享同一页表（内核映射常驻，高半核等）

### Q03_010 是否存在缺页异常 (Page Fault) 处理逻辑并与内存分配/映射联动？（必须三态）

implemented

### Q03_011 追踪一条缺页链路：trap/异常入口 → 缺页处理函数（handle_page_fault 或等价）→ 分配页帧 → 建立映射。用 3-5 个关键节点描述并给每节点证据。

handle_excp [kernel/trap/trap.c:405-425] → handle_page_fault [kernel/mm/vm.c:1040-1091] → handle_page_fault_lazy [kernel/mm/vm.c:981-995] → uvmalloc [kernel/mm/vm.c:410-440] → allocpage [kernel/mm/pm.c:220-240] → mappages [kernel/mm/vm.c:288-315] → sfence_vma [include/hal/riscv.h:362]

### Q03_012 是否实现写时复制 (Copy-on-Write, CoW)？（必须三态；若 implemented 需说明触发点在 fault 中还是 fork 中）

implemented

### Q03_013 是否实现惰性分配 (Lazy Allocation)？（必须三态；若 implemented 需说明是在 brk/mmap 还是 fault 中分配）

implemented

### Q03_014 是否实现 swap（swap_in/swap_out 或等价页面置换）？（必须三态）

not_found

### Q03_015 是否实现 mmap（文件映射/匿名映射）且处理标志位（MAP_FIXED/MAP_ANON/MAP_SHARED 等）？（必须三态；stub 需说明形态如 ENOSYS/return 0）

implemented

### Q03_016 是否存在 Page Cache（页缓存/文件页缓存）管理？（必须三态）

not_found

### Q03_017 是否存在脏页回写 (dirty page writeback) 机制？（必须三态；若 implemented 需指出同步/异步与触发条件）

not_found

### Q03_018 是否存在 TLB 射击 (TLB Shootdown / Remote TLB Flush)机制以支持多核页表一致性？（必须三态；若 implemented 需指向 IPI/跨核调用证据）

not_found

### Q03_019 TLB 刷新指令/函数点是什么？（RISC-V sfence.vma / AArch64 tlbi / x86 invlpg 等，或仓库中等价的 TLB 刷新封装；必须给证据）

使用 RISC-V sfence.vma 指令，封装为 sfence_vma() 函数。在 include/hal/riscv.h:362 定义。在页表修改后（mappages/unmappages/uvmcopy/handle_page_fault/do_mmap）调用。

### Q03_020 用户指针安全检查机制是什么？（access_ok/verify_area/UserInPtr 等；列出入口点与校验逻辑证据）

使用 struct seg 链表进行段检查。copyout2/copyin2 调用 partofseg/locateseg 检查地址是否在合法段内。safememmove 通过 permit_usr_mem/protect_usr_mem 和 badaddr 捕获机制进行安全访问。

### Q03_021 若实现了页面置换 (Page Replacement)，使用的算法最接近哪种？（Stallings Ch8：OPT 理想算法 / LRU 最近最少使用 / Clock 近似 LRU / FIFO / 未实现）

未实现页面置换（无 swap）

### Q03_022 是否存在工作集模型 (Working Set Model, WSM) 或抖动检测/防止 (Thrashing Prevention) 机制？（必须三态；Stallings Ch8 核心概念；若 not_found 需列出已搜关键字 working_set|thrash|resident_set）

not_found

### Q03_023 物理内存总量（Physical Memory Size）：____ KB/MB；页大小（Page Size）：____ bytes；最大进程虚拟地址空间（Virtual Address Space）：____ bits。（必须从代码常量/链接脚本/配置中给出证据；无法确定则写 unknown 并说明已搜路径）

物理内存总量：6 MB（PHYSTOP=0x80600000, KERNBASE=0x80020000）；页大小：4096 bytes（PGSIZE=4096）；最大进程虚拟地址空间：39 bits（MAXVA=1L<<38，Sv39）

### Q03_024 内存保护机制 (Memory Protection) 的实现形式更接近哪种？（Stallings Ch7.1）

硬件页表 + 软件指针检查双重保护

### Q03_025 逻辑内存组织 (Logical Memory Organization, Stallings Ch7.1)：进程地址空间中 text/data/heap/stack/mmap 各区域（或等价区间）是否由统一的映射管理结构（VMA/区间表/链表/BTreeMap 等）维护？（如存在请给结构体证据；不存在则写未发现等价结构）

是，使用 struct seg 链表统一管理。struct seg 含 type(enum segtype: NONE/LOAD/TEXT/DATA/BSS/HEAP/MMAP/STACK)、addr、sz、flag、next 指针。进程通过 p->segment 指向段链表头。

### Q03_026 是否存在显式的硬件分段机制 (Hardware Segmentation, Stallings Ch7.4)？

纯分页无分段（RISC-V/AArch64 常见）

### Q03_027 取页策略 (Fetch Policy, Stallings Ch8.2) 更接近哪种？

惰性分配 (Lazy Allocation)：分配虚拟地址但推迟物理页到缺页时

### Q03_028 放置策略 (Placement Policy, Stallings Ch8.2)：新的匿名映射或堆区域增长时，系统如何选择虚拟地址区间？（固定起始地址 / mmap_base 向下生长 / 首次适配 / 最佳适配 等；必须给实现证据或写未发现等价策略）

mmap 使用首次适配 (first-fit) 策略：lookup_segment 从 VUMMAP(0x70000000) 开始向上查找第一个足够大的空闲区间。堆增长通过 uvmalloc 连续分配。

### Q03_029 是否存在驻留集管理/内存负载控制 (Resident Set Management / Load Control, Stallings Ch8.2)？（包括工作集动态调整、内存回收守护线程、OOM killer、驻留页数限制等；若 not_found 需列出已搜关键字）

not_found

### Q03_030 内存主链路（必须给出，尽量以 Mermaid graph TD 表达）：从确认的最强内存入口（缺页处理入口/mmap 入口/brk 入口/等价入口）出发，追踪到页表操作核心点或物理页分配核心点，写出 3-6 个关键节点。节点格式：FuncName [path:line]。若链路未被源码证据完全闭合，标注候选主链路而非确认的主链路。只画一条主链，不要并列展开多条支线。

graph TD\nA[handle_excp kernel/trap/trap.c:405] --> B[handle_page_fault kernel/mm/vm.c:1040]\nB --> C[handle_page_fault_lazy kernel/mm/vm.c:981]\nC --> D[uvmalloc kernel/mm/vm.c:410]\nD --> E[allocpage kernel/mm/pm.c:220]\nE --> F[mappages kernel/mm/vm.c:288]\nF --> G[sfence_vma include/hal/riscv.h:362]

### Q03_031 该系统更容易出现哪种内存碎片 (Memory Fragmentation, Stallings Ch7.2)？

外部碎片 (External Fragmentation)：空闲块分散无法满足大连续请求

### Q03_032 地址重定位 (Address Relocation, Stallings Ch7.1) 的绑定时机更接近哪种？

运行时动态绑定 (Run-time / Dynamic Relocation)：通过 MMU 基址+界限或页表在每次访问时转换

### Q03_033 页面置换的作用域策略 (Replacement Scope, Stallings Ch8.2) 更接近哪种？

未实现置换（无 swap）

### Q03_034 是否存在清理策略 (Cleaning Policy, Stallings Ch8.2)？（即脏页预先后台写回，而非仅在置换时才写回；搜索 background writeback / kswapd / cleaner_thread 或等价；必须三态；若 not_found 需列出已搜关键字）

not_found

---


# 第04章 进程线程调度与多核

### Q04_001 执行实体 (Execution Entity) 抽象是什么？
请按以下格式作答（每项必须有代码证据）：
- 顶层类型名: ___（如 Process / Task / Thread / TaskControlBlock）
- 结构体路径: ___
- 关键字段（至少列 3 个）: Context=___, State=___, PID=___, TrapFrame=___
- 是否区分 PCB 与 TCB: ___（是 / 否 / 待核实）

顶层类型名: struct proc (Process Control Block, PCB)
结构体路径: include/sched/proc.h:38-107
关键字段: Context=context (struct context, kernel/sched/proc.c:100), State=state (enum procstate, kernel/sched/proc.c:33), PID=pid (int, kernel/sched/proc.c:25), TrapFrame=trapframe (struct trapframe*, kernel/sched/proc.c:98)
是否区分 PCB 与 TCB: 否 (仅有统一的 struct proc 结构，无独立 TCB)

### Q04_002 任务/进程的生命周期状态机有哪些状态与流转点？（Ready/Running/Blocked/Exited 等；需状态枚举/字段证据）

状态枚举 (include/sched/proc.h:27-31): RUNNABLE, RUNNING, SLEEPING, ZOMBIE 四态
流转点:
- RUNNABLE→RUNNING: scheduler() 中 __get_runnable_no_lock() 选中后设置 state=RUNNING (kernel/sched/proc.c:677)
- RUNNING→SLEEPING: sleep() 调用 __remove(p) 后 __insert_sleep(p) (kernel/sched/proc.c:578-580)
- RUNNING→ZOMBIE: exit() 设置 state=ZOMBIE 并 __remove(p) (kernel/sched/proc.c:443-444)
- SLEEPING→RUNNABLE: wakeup() 调用 __remove(p) 后 __insert_runnable(PRIORITY_IRQ, p) (kernel/sched/proc.c:378-380)
- ZOMBIE→回收: wait4() 找到 ZOMBIE 子进程后调用 freeproc() (kernel/sched/proc.c:497)

### Q04_003 是否存在上下文切换 (Context Switch) 实现（switch.S/__switch/swtch/context_switch）？（必须三态）

implemented

### Q04_004 上下文切换保存/恢复了哪些寄存器集合？（例如 RISC-V s0-s11；必须引用汇编/结构体证据）

保存/恢复的寄存器 (kernel/sched/swtch.S:10-38): ra, sp, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11 共 14 个寄存器 (RISC-V 被调用者保存寄存器)
对应 struct context 结构 (include/sched/proc.h:10-24): ra(0), sp(8), s0-s11(16-104)

### Q04_005 调度算法 (Scheduling Algorithm) 属于哪类？
请按格式作答：
- 算法名称: ___（必须是以下之一：FCFS / Round-Robin (RR) / Stride/Proportional-Share / MLFQ / CFS / Priority / 其他）
- 代码证据（关键字段/函数）: ___
  - RR: timeslice/slice 字段位置=___
  - Stride: stride 字段与比较逻辑位置=___
  - MLFQ: 多级队列 VecDeque/数组层级证据=___
  - Priority: priority 字段参与 pick_next 排序证据=___

算法名称: Priority (多级优先级队列)
代码证据:
- 优先级定义: PRIORITY_TIMEOUT=0, PRIORITY_IRQ=1, PRIORITY_NORMAL=2, PRIORITY_NUMBER=3 (kernel/sched/proc.c:233-237)
- 就绪队列数组: struct proc *proc_runnable[PRIORITY_NUMBER] (kernel/sched/proc.c:238)
- 调度选择: __get_runnable_no_lock() 按优先级从高到低遍历 proc_runnable[] (kernel/sched/proc.c:593-607)
- 时间片机制: timer 字段递减，超时后降为 PRIORITY_TIMEOUT (kernel/sched/proc.c:748-753)
- 非 RR/Stride/MLFQ/CFS: 无 timeslice 字段、无 stride 比较、无多级反馈队列结构

### Q04_006 调度器 (Scheduler)核心入口/关键函数有哪些？（schedule/pick_next 等；给 1-3 个入口与证据）

核心入口:
1. scheduler() - 主调度循环，无限循环选择可运行进程并切换 (kernel/sched/proc.c:663-693)
2. sched() - 切换入口，保存当前上下文并跳转到 scheduler (kernel/sched/proc.c:696-727)
3. __get_runnable_no_lock() - 选择下一个可运行进程，按优先级遍历 (kernel/sched/proc.c:593-607)
4. yield() - 主动让出 CPU，调用 sched() (kernel/sched/proc.c:613-635)

### Q04_007 是否实现 fork/clone（创建新执行实体）？（必须三态）

implemented

### Q04_008 fork/clone 是否复制地址空间与文件表？（必须给复制路径证据；若 stub 需说明形态）

是，clone() 完整复制:
- 地址空间复制: np->segment = copysegs(p->pagetable, p->segment, np->pagetable) (kernel/sched/proc.c:303-306)
- 文件表复制: copyfdtable(&p->fds, &np->fds) (kernel/sched/proc.c:318-321)
- 信号处理复制: sigaction_copy(&np->sig_act, p->sig_act) (kernel/sched/proc.c:309-312)
- 陷阱帧复制: *(np->trapframe) = *(p->trapframe) (kernel/sched/proc.c:332-335)

### Q04_009 是否实现 exec（装载 ELF/重建地址空间）？（必须三态）

implemented

### Q04_010 是否实现 wait/waitpid（父子回收同步）？（必须三态）

implemented

### Q04_011 waitpid / wait4 的阻塞实现 (Blocking Implementation) 更接近哪种？

真正阻塞：移出就绪队列 + WaitQueue/条件变量唤醒 (Wait Queue or Condition Variable)

### Q04_012 PID 分配器实现是什么？（自增/bitmap/空闲栈复用/只分配不回收；必须给证据）

全局自增计数器 __pid (kernel/sched/proc.c:23)，无回收机制 (只分配不回收)
分配位置: allocproc() 中 p->pid = __pid++ (kernel/sched/proc.c:223)
初始化: procinit() 中 __pid = 1 (kernel/sched/proc.c:1021)
无 bitmap/空闲栈复用机制

### Q04_013 父子进程树如何存储？（children Vec/链表/parent+sibling 指针；必须给结构体字段证据）

显式 parent/child/sibling 指针链表 (include/sched/proc.h:63-68):
- parent: struct proc *parent 指向父进程
- child: struct proc *child 指向第一个子进程
- sibling_next/sibling_pprev: 兄弟链表 (双向)
遍历方式: while (NULL != np->sibling_next) (kernel/sched/proc.c:414-428)

### Q04_014 是否实现信号 (signal) 或 futex？（若二者都无则 not_found；若只实现其一需说明并给证据）

stub

### Q04_015 与 09 多核的交叉一致性：是否存在每核队列/任务迁移/IPI resched？（需与第 9 章互指证据或写不适用）

不存在每核就绪队列/任务迁移/IPI resched
证据:
- 全局就绪队列: struct proc *proc_runnable[PRIORITY_NUMBER] 为全局数组 (kernel/sched/proc.c:238)
- 无 per-CPU 运行队列: 无 struct cpu 的 runnable 字段
- 无任务迁移代码: 未找到 migrate/task_balance 等
- IPI 仅用于启动: main.c 中 sbi_send_ipi 仅用于唤醒 AP (kernel/main.c:78-80)，无 IPI resched 路径

### Q04_016 exit() 资源回收路径：调用链是什么？是否真正回收地址空间/文件表/通知父进程？（必须给调用链证据；桩则说明）

exit() 调用链 (kernel/sched/proc.c:393-453):
1. delsegs(p->pagetable, p->segment) - 删除地址空间段 (line 398)
2. uvmfree(p->pagetable) - 释放页表 (line 399)
3. dropfdtable(&p->fds) - 关闭文件表 (line 403)
4. iput(p->cwd); iput(p->elf) - 释放 inode (line 404-405)
5. 重分配所有子进程给__initproc (line 410-429)
6. p->state = ZOMBIE; __remove(p) (line 443-444)
7. __wakeup_no_lock(p->parent) - 唤醒父进程 (line 446)
8. sched() - 切换到调度器 (line 450)
父进程 wait4() 调用 freeproc() 最终回收 (kernel/sched/proc.c:497)

### Q04_017 是否实现进程组/会话（Process Group / Session，pgid/session/set_sid/setpgid）？（必须三态；有则区分真实检查链 vs 仅占位字段）

not_found

### Q04_018 是否实现 POSIX 资源限制（rlimit/RLIMIT/getrlimit/setrlimit）？（必须三态；若 implemented 需说明支持的资源类型数量及软/硬限制机制）

stub

### Q04_019 该 OS 是否区分了 TCB（线程控制块）与 PCB（进程控制块）？

仅有统一 Task 结构（无区分）

### Q04_020 调度切换路径上是否存在页表切换（w_satp/sfence.vma/写 CR3/TTBR 等）？（必须三态；给调用点 路径 证据）

implemented

### Q04_021 用户线程与内核线程的映射模型 (User-Level Thread to Kernel-Level Thread Mapping) 更接近哪种？（Stallings Ch4）

仅内核线程（无独立用户线程库）

### Q04_022 是否实现线程局部存储 (Thread-Local Storage, TLS)？（必须三态；搜索 thread_local|TLS|__thread|#[thread_local]；若 implemented 需说明 TLS 的访问方式：tp 寄存器/段寄存器/其他）

not_found

### Q04_023 调度器是否追踪/优化以下哪些性能指标 (Scheduling Criteria, Stallings Ch9)？（多选；未发现则留空并在 notes 写 not_found）

["未发现调度性能统计"]

### Q04_024 优先级调度是否实现老化 (Aging, Stallings Ch9) 以防止低优先级进程饥饿 (Starvation)？（必须三态；搜索 age/aging/boost_priority 或等价；若 not_found 需说明是否存在饥饿风险）

not_found

### Q04_025 是否实现公平份额调度 (Fair-Share Scheduling, Stallings Ch9) 或 CPU 配额 (CPU Quota/cgroup)？（必须三态；搜索 fair_share/cgroup/cpu_quota/weight 等）

not_found

### Q04_026 调度器的抢占模式 (Preemption Mode, Stallings Ch9) 更接近哪种？

完全抢占 (Fully Preemptive)：时钟中断可随时抢占运行进程

### Q04_027 是否实现最短作业优先调度 (Shortest Job First / SJF 或 SRTF, Stallings Ch9)？（必须三态；或等价的基于预测 burst 时间的调度）

not_found

### Q04_028 该 OS 的多核形态更接近哪种？

SMP（对称多处理）

### Q04_029 是否存在 Secondary CPU / AP 启动链（BSP 唤醒 AP，上线后进入 idle/调度）？（必须三态）

implemented

### Q04_030 是否实现 IPI（核间中断）发送与处理？（必须三态）

implemented

### Q04_031 若存在 IPI：发送与处理路径分别在哪些函数/文件？（给关键入口与证据）

IPI 发送路径:
- kernel/main.c:78-80: sbi_send_ipi(mask, 0) BSP 唤醒 AP
- include/sbi.h:98-102: sbi_send_ipi 封装 SBI_CALL_2
IPI 处理路径:
- kernel/trap/trap.c:369-371: INTR_SOFTWARE 处理 sbi_clear_ipi()
- sbi/psicasbi/src/trap/sbi/legacy.rs:67-81: SBI EID_SEND_IPI 处理 (Rust SBI 实现)

### Q04_032 是否存在 per-CPU 变量/结构（PerCpu、CPU-local storage 等）？（必须三态）

implemented

### Q04_033 per-CPU 的实现方式是什么？（例如 TLS/tp 寄存器/gsbase/数组索引 hartid；需证据）

通过 tp 寄存器存储 CPU ID (hartid)，数组索引访问:
- kernel/main.c:17: inithartid(hartid) 中 asm volatile("mv tp, %0" : : "r" (hartid & 0x1))
- include/sched/proc.h:162: cpuid() 中 return r_tp()
- kernel/sched/proc.c:96-99: mycpu() 中 int id = cpuid(); return &cpus[id]
访问方式: tp 寄存器 → hartid → cpus[hartid] 数组索引

### Q04_034 调度是否存在跨核负载均衡/迁移/亲和性？（必须三态）

not_found

### Q04_035 是否实现 TLB shootdown（跨核页表一致性刷新）？（必须三态；需与 03 互指）

not_found

### Q04_036 与 03/04/05/08 章的交叉一致性 (Cross-Chapter Consistency)，按以下四项分别作答（每项须给证据路径或写「单核不适用」）：
- 03 TLB: 多核页表修改后 TLB 刷新策略=___
- 04 调度: 每核运行队列/负载均衡/IPI resched=___
- 05 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上线顺序=___
- 08 锁: SpinLock 关中断行为在多核下是否安全=___

03 TLB: 多核页表修改后 TLB 刷新策略=未发现 TLB shootdown，仅 sfence_vma 刷新当前核 (kernel/sched/proc.c:683)
04 调度: 每核运行队列/负载均衡/IPI resched=全局就绪队列 proc_runnable[]，无每核队列/负载均衡/IPI resched
05 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上线顺序=trapinithart() 每核独立调用 (kernel/main.c:59,88)，时钟中断 per-CPU
08 锁: SpinLock 关中断行为在多核下是否安全=acquire() 调用 push_off() 关中断 (kernel/sync/spinlock.c:25)，多核安全

### Q04_037 SpinLock 在获取锁时是否禁用中断（关中断保护临界区）？

是，获取时关中断、释放时恢复

### Q04_038 NCPU/MAXCPU（或等价宏）与链接脚本中的每 hart 栈/入口布局是否对应？（搜索 _max_hart_id 等；给宏定义与链接脚本对应证据，或写未发现）

NCPU=2 (include/param.h:5)
链接脚本 linker/linker64.ld 无 _max_hart_id 定义
boot_stack 分配: kernel/entry.S:18-20 .space 4096 * 4 * 2 = 32KB (2 核 × 4 页 × 4KB)
main.c:101: kstack = boot_stack + hartid * 4 * PGSIZE (每核 4 页栈)
对应关系: NCPU=2 与 boot_stack 大小 32KB 匹配 (2 核 × 16KB/核)

### Q04_039 是否使用 AtomicUsize/原子变量分配 PID/TID（全局唯一 ID 池）？（必须三态；给实现证据）

not_found

### Q04_040 是否支持实时调度 (Real-Time Scheduling, Stallings Ch10)？（必须三态；搜索 SCHED_FIFO / SCHED_RR / realtime / RT priority / deadline 等）

not_found

### Q04_041 是否存在 NUMA (Non-Uniform Memory Access) 感知的内存分配或调度策略？（必须三态；搜索 numa / node_id / local_memory 等；嵌入式单 SoC 可写 not_found 并说明架构）

not_found

---


# 第05章 文件系统与设备 IO

### Q05_001 VFS 抽象层 (Virtual File System, VFS)接口是什么形态？（Rust trait / C op 表；必须给接口定义证据）

C 语言操作函数指针表（C op table / function pointer struct）。定义于 `include/fs/fs.h:53-78`，包含 `struct fs_op`（超级块操作）、`struct inode_op`（索引节点操作）、`struct dentry_op`（目录项操作）、`struct file_op`（文件操作）四个操作表结构，每个结构包含一组函数指针如 `alloc_inode`、`lookup`、`read`、`write` 等。

### Q05_002 具体文件系统后端 (Concrete File System Backend) 更接近哪种？

真实磁盘文件系统（FAT32/Ext4/其他，持久化存储）

### Q05_003 若支持 FAT32/Ext4：它是自研还是第三方库/crate？（必须引用 Cargo.toml/Cargo.lock 或 Makefile 引入证据）

自研实现。证据：1) `Cargo.toml` 仅包含 `sbi/psicasbi` 子项目，无文件系统 crate 依赖；2) `Makefile:73-76` 显式列出 FAT32 源码文件 `kernel/fs/fat32/cluster.c`、`kernel/fs/fat32/dirent.c`、`kernel/fs/fat32/fat.c`、`kernel/fs/fat32/fat32.c` 直接编译进内核；3) `kernel/fs/fat32/fat32.c:22-38` 直接定义 `fat32_inode_op` 和 `fat32_file_op` 操作表，无外部 crate 引用。

### Q05_004 文件打开路径：文件打开入口（sys_open 或等价）→ VFS 层 → 具体 FS open。列出 3-6 个关键节点并给证据。

文件打开调用链：1) `sys_openat` (`kernel/syscall/sysfile.c:253`) → 2) `nameifrom` (`include/fs/fs.h:169` / `kernel/fs/fs.c:473-476`) → 3) `lookup_path` (`kernel/fs/fs.c:412-458`) → 4) `dirlookup` (`kernel/fs/fs.c:447`) → 5) `fat_lookup_dir` (FAT32 具体实现，通过 `inode_op->lookup` 调用) → 6) `filealloc` + `fdalloc` (`kernel/syscall/sysfile.c:318-325`) 分配文件描述符。关键路径：`sys_openat` 调用 `nameifrom(dp, path)` 进行路径解析，`lookup_path` 遍历路径组件，对每个目录组件调用 `ip->op->lookup` (即 `fat_lookup_dir`) 查找子目录项，最终返回 inode 并分配 fd。

### Q05_005 文件描述符表 (File Descriptor Table, FD Table) 的实现形态是什么？（固定数组/Vec/BTreeMap 等；必须给结构体定义证据）

固定数组实现。定义于 `include/fs/file.h:34-40`：`struct fdtable { uint16 basefd; uint16 nextfd; uint16 used; uint16 exec_close; struct file *arr[NOFILE]; struct fdtable *next; };` 其中 `NOFILE=16` (定义于 `include/param.h:6`)，每个进程可拥有多个 fdtable 形成链表以扩展 fd 数量。

### Q05_006 是否实现块缓存/缓冲缓存 (Block Cache / Buffer Cache, bcache)？（必须三态）

implemented

### Q05_007 若存在缓存：驱逐策略是什么（LRU/Clock/FIFO/无驱逐）？必须指出判断依据（字段/算法分支）证据。

LRU (Least Recently Used) 驱逐策略。证据：`kernel/fs/bio.c:88-90` 定义 `static struct d_list lru_head` 作为 LRU 链表头；`kernel/fs/bio.c:147-163` 在 `bget()` 缓存未命中时，从 `lru_head.prev` (链表尾部，即最久未使用) 获取缓冲块进行驱逐；`kernel/fs/bio.c:126-128` 在缓存命中时将块移动到哈希表头部 (也是 LRU 头部)，确保最近使用的块保留在链表前端。

### Q05_008 是否实现页缓存 (Page Cache)或与 mmap/文件映射共享缓存页？（必须三态）

implemented

### Q05_009 是否实现 mmap 的文件映射或匿名映射？（必须三态；若 stub 说明形态）

implemented

### Q05_010 是否实现 poll/select/epoll（或等价事件机制）？（必须三态）

implemented

### Q05_011 路径解析 (namei/path_walk/lookup) 是否实现并支持绝对/相对路径与 . ..？（必须三态）

implemented

### Q05_012 是否支持符号链接 (symlink) 的解析/跟随？（必须三态）

stub

### Q05_013 是否实现管道 (pipe/pipe2) 并在 VFS 层作为文件对象？（必须三态；与 08 章 pipe 实现互指）

implemented

### Q05_014 是否实现网络 socket（作为 VFS 文件对象）？（必须三态）

not_found

### Q05_015 是否实现伪文件系统（devfs/procfs/sysfs）？（必须三态；若 implemented 需说明实现形态）

implemented

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

硬编码设备表/固定 MMIO 地址

### Q05_022 是否能在代码中证实解析了 `.dtb`/DeviceTree？（必须三态；若 implemented 必须指出解析入口）

not_found

### Q05_023 驱动框架接口是什么？（Rust Driver trait / C driver ops / 注册表；必须引用接口定义证据）

C 语言驱动操作函数接口。通过条件编译 (#ifdef QEMU / #ifndef QEMU) 在 `kernel/hal/disk.c:19-24` 中选择不同的驱动实现：QEMU 平台调用 `virtio_disk_init()`，K210 平台调用 `sdcard_init()`。驱动接口通过 `disk_read()`、`disk_write()`、`disk_submit()` 等函数抽象，底层分别调用 `virtio_disk_*` 或 `sdcard_*` 函数。

### Q05_024 驱动注册与初始化顺序是什么？（init_drivers/probe/driver_manager 等；列出 3-6 个关键节点并给证据）

驱动初始化顺序：1) `kernel/main.c` 调用 `disk_init()` → 2) `kernel/hal/disk.c:19-24` 根据平台选择 `virtio_disk_init()` (QEMU) 或 `sdcard_init()` (K210) → 3) `kernel/hal/virtio_disk.c:78-140` 初始化 virtio 队列和描述符 / `kernel/hal/sdcard.c` 初始化 SD 卡 SPI 接口 → 4) `kernel/fs/bio.c:82-97` 初始化块缓存 `binit()` → 5) `kernel/fs/rootfs.c:285-340` 初始化根文件系统并挂载 FAT32。无统一的驱动注册框架，通过直接函数调用初始化。

### Q05_025 是否实现 UART/Console 驱动用于早期输出？（必须三态）

implemented

### Q05_026 是否实现块设备驱动（virtio-blk/ramdisk/其他）？（必须三态）

implemented

### Q05_027 是否实现网络设备驱动（virtio-net/e1000/rtl8139 等）？（必须三态）

not_found

### Q05_028 是否实现中断控制器驱动（PLIC/CLINT/APIC 等）？（必须三态；需指出中断源到 handler 的分发证据）

implemented

### Q05_029 MMIO 地址来源是什么？（DTB 提供 / 常量硬编码 / 物理→虚拟转换；必须给证据）

常量硬编码。证据：`include/memlayout.h:38-68` 通过条件编译定义固定 MMIO 地址：QEMU 平台 UART = 0x10000000L、VIRTIO0 = 0x10001000、CLINT = 0x02000000L、PLIC = 0x0c000000L；K210 平台 UART = 0x38000000L。虚拟地址通过 `VIRT_OFFSET = 0x3F00000000L` 进行物理→虚拟转换 (如 `UART_V = UART + VIRT_OFFSET`)。

### Q05_030 多平台适配是如何通过构建/条件编译选择驱动的？（features/Kconfig/Makefile 规则；必须给证据）

通过 Makefile 条件编译和 #ifdef 预处理指令实现多平台适配。证据：1) `Makefile:1-2` 定义 `platform := k210` 或 `platform := qemu`；2) `Makefile:34-36` 添加编译选项 `CFLAGS += -D QEMU` (仅 QEMU 平台)；3) `Makefile:107-117` 根据平台添加不同源码文件 (k210 添加 spi.c、sdcard.c 等，QEMU 添加 virtio_disk.c)；4) 源码中使用 `#ifdef QEMU` / `#ifndef QEMU` 区分平台特定代码 (如 `include/memlayout.h:38-42`、`kernel/hal/disk.c:19-24`)。

### Q05_031 是否存在 MMU 启用前后串口地址切换（phys/virt 切换）逻辑？（必须三态）

implemented

### Q05_032 I/O 缓冲模式 (I/O Buffering) 最接近哪种？（Stallings Ch11：单缓冲 Single Buffer / 双缓冲 Double Buffer / 循环缓冲 Circular Buffer / 缓冲池 Buffer Pool / 无缓冲 No Buffer）

缓冲池 (Buffer Pool)

### Q05_033 块设备（磁盘/eMMC/NVMe）I/O 请求调度算法 (Scheduling Algorithm) (Disk Scheduling Algorithm) 更接近哪种？（Stallings Ch11；若无显式调度则选「FCFS 顺序提交」）

FCFS（先来先服务 First-Come First-Served）

### Q05_034 I/O 控制技术 (I/O Control Techniques, Stallings Ch11) 更接近哪种？

中断驱动 I/O (Interrupt-Driven I/O)：设备完成后发中断通知 CPU

### Q05_035 是否实现 DMA (Direct Memory Access, Stallings Ch11) 传输路径？（必须三态；搜索 dma_alloc / dma_map / dma_buf / virtio 描述符环等；virtio 的描述符环也算 DMA 等价机制）

implemented

---


# 第06章 同步互斥与进程间通信

### Q06_001 该内核提供了哪些同步原语？（SpinLock/Mutex/RwLock/Semaphore/Condvar/WaitQueue 等；列出类型定义证据）

已实现同步原语：
1. SpinLock（自旋锁）：定义于 `include/sync/spinlock.h:7-13`，结构体 `struct spinlock` 含 `locked`、`name`、`cpu` 字段；实现于 `kernel/sync/spinlock.c`，`acquire()` 使用 `__sync_lock_test_and_set` 原子操作自旋，`release()` 使用 `__sync_lock_release`。
2. SleepLock（睡眠锁/阻塞锁）：定义于 `include/sync/sleeplock.h:9-16`，结构体 `struct sleeplock` 含 `locked`、`lk`（内部 spinlock）、`name`、`pid`；实现于 `kernel/sync/sleeplock.c`，`acquiresleep()` 在锁被持有时调用 `sleep()` 挂起进程，`releasesleep()` 调用 `wakeup()` 唤醒等待者。
3. WaitQueue（等待队列）：定义于 `include/sync/waitqueue.h:17-24`，结构体 `struct wait_queue` 含 `lock`（spinlock）和 `head`（双向链表头），`struct wait_node` 含 `chan` 和 `list`；基于双向链表 `dlist` 实现，提供 `wait_queue_add/del`、`wait_queue_is_first` 等接口。

未实现原语：
- Mutex：无独立 Mutex 结构体，SleepLock 充当阻塞型 Mutex 角色
- RwLock：未发现读写锁实现
- Semaphore：未发现信号量实现
- Condvar：未发现条件变量实现

### Q06_002 Mutex 更接近哪种实现？

阻塞锁（Blocking Mutex，进入等待队列并挂起）

### Q06_003 是否存在等待队列 (Wait Queue, WaitQueue) 与 sleep/wakeup（或等价阻塞/唤醒）实现？（必须三态）

implemented

### Q06_004 sleep / wakeup 不变量 (Sleep-Wakeup Invariant) 分析，按格式填写：
- sleep 入口函数: ___（路径）
- 入睡前持有的锁: ___（无则写 none）
- 防丢 wakeup (Lost Wakeup Prevention) 机制: ___（如：持队列锁检查条件 / 无防护）
- wakeup 函数: ___（路径）
- 唤醒与锁释放顺序: ___（先唤醒后释放 / 先释放后唤醒 / 其他）

sleep 入口函数: kernel/sched/proc.c:569 (sleep())
入睡前持有的锁: 调用者传入的 lk（非 proc_lock 时）或 proc_lock
防丢 wakeup (Lost Wakeup Prevention) 机制: 持队列锁检查条件后调用 sleep()，sleep() 内部先 release(lk) 再 sched()，确保原子性
wakeup 函数: kernel/sched/proc.c:386 (wakeup())
唤醒与锁释放顺序: 先唤醒后释放锁（wakeup() 获取 proc_lock 后调用 __wakeup_no_lock() 唤醒匹配 chan 的进程，然后释放 proc_lock）

### Q06_005 是否实现管道 (Pipe)？（必须三态）

implemented

### Q06_006 pipe 缓冲形态更接近哪种？

字节环形缓冲区 (ring buffer)

### Q06_007 pipe 的阻塞语义更接近哪种？

阻塞：挂起当前线程/任务进入等待队列

### Q06_008 是否实现消息队列/信号量/共享内存等 SysV IPC (Message Queue / Semaphore / Shared Memory, msg/sem/shm)？（必须三态；若仅实现其一需说明）

not_found

### Q06_009 是否实现 futex？（必须三态）

not_found

### Q06_010 是否实现信号机制（sigaction/kill/sigreturn/trampoline）？（必须三态）

implemented

### Q06_011 若实现 signal handler：用户态 handler 上下文如何构建？是否存在 sigreturn 恢复原 trap frame？（必须给证据）

用户态 handler 上下文构建流程（kernel/sched/signal.c:sighandle()）：
1. 分配 struct sig_frame（kmalloc），保存当前进程的 sig_set 掩码
2. 分配新的 struct trapframe（kmalloc），复制原 trapframe 内容
3. 设置新 trapframe.epc = SIG_TRAMPOLINE + (sig_handler - sig_trampoline)，即跳转到 trampoline 中的 sig_handler
4. 设置新 trapframe.a0 = signum（信号编号），a1 = handler 地址（或 default_sigaction）
5. 将进程 pagetable 切换为新 trapframe
6. 将 sig_frame 插入进程 sig_frame 链表

sigreturn 恢复逻辑（kernel/sched/signal.c:sigreturn()）：
1. 从进程 sig_frame 链表头部取出 frame
2. 恢复 sig_set = frame->mask
3. 释放当前 trapframe，恢复 p->trapframe = frame->tf（原陷阱帧）
4. 从链表移除并释放 sig_frame
5. 返回用户态时从原 trapframe 恢复上下文

证据：kernel/sched/signal.c:173-224 (sighandle 构建)、226-245 (sigreturn 恢复)

### Q06_012 RwLock（读写锁 Reader-Writer Lock）的实现形态更接近哪种？

未发现/不支持

### Q06_013 底层原子操作来源更接近哪种？

自定义汇编（ldxr/stxr、lock xchg 等）

### Q06_014 死锁四必要条件（Coffman Conditions）在该内核中是否均成立？
请逐条作答（互斥 Mutual Exclusion / 持有并等待 Hold-and-Wait / 不可剥夺 No Preemption / 循环等待 Circular Wait），并结合 SpinLock/Mutex 的实现给出证据或写「不适用」。

1. 互斥 (Mutual Exclusion): 成立。SpinLock 通过原子操作 `__sync_lock_test_and_set` 确保同一时刻仅一个 CPU 持有锁（kernel/sync/spinlock.c:29-32）；SleepLock 通过内部 spinlock 保护 `locked` 字段（kernel/sync/sleeplock.c:22-28）。

2. 持有并等待 (Hold-and-Wait): 成立。sleep() 实现中，调用者必须持有锁 lk 才能调用 sleep()，sleep() 内部释放 lk 后进入 sched() 挂起，但进程仍持有其他资源（如 pipe 锁）；pipe.c 中 pipelock() 先 acquire(&q->lock) 再 sleep(wait->chan, &q->lock)（kernel/fs/pipe.c:90-102）。

3. 不可剥夺 (No Preemption): 成立。SpinLock 持有期间不能被强制剥夺，必须显式调用 release()；SleepLock 持有期间其他进程只能 sleep 等待，不能强制获取（kernel/sync/sleeplock.c:22-28）。

4. 循环等待 (Circular Wait): 可能成立。内核未实现全局锁顺序规范（仅 xv6-user/usertests.c:952 注释提及 parent-then-child 锁顺序用于防止 exit() 与 init wait() 死锁），存在嵌套锁场景（如 pipe 操作中同时持有 pi->lock 和 q->lock），若锁获取顺序不一致可能导致循环等待。

### Q06_015 内核对死锁 (Deadlock) 的处理策略更接近哪种？

死锁预防 (Deadlock Prevention)：通过锁顺序等消除 Coffman 必要条件

### Q06_016 是否存在全局锁顺序（Lock Ordering）规范或注释，以预防嵌套锁导致的循环等待死锁 (Circular Wait Deadlock)？（必须三态；若 implemented 需给出锁排序规则或 ABBA 锁检测代码证据）

stub

### Q06_017 是否实现管程/条件变量 (Monitor / Condition Variable, Stallings Ch5)？（必须三态；搜索 Condvar / condition_variable / monitor / wait/notify/signal 等；若 implemented 需区分 Hoare 语义（等待者立即恢复）vs Mesa 语义（等待者重新竞争锁））

not_found

### Q06_018 经典同步问题验证 (Classic Synchronization Problems, Stallings Ch5)：
以下三个经典问题在该内核中是否有对应实现或测试？
- 生产者-消费者 (Producer-Consumer / Bounded Buffer)：___（implemented/not_found + 证据）
- 读者-写者 (Readers-Writers)：___（实现了读者优先/写者优先/公平？ + 证据）
- 哲学家就餐 (Dining Philosophers)：___（implemented/not_found）

生产者 - 消费者 (Producer-Consumer / Bounded Buffer): not_found - 检索 'producer.*consumer|bounded.*buffer' 无命中；Pipe 实现（kernel/fs/pipe.c）本质是生产者 - 消费者模式（环形缓冲 + 阻塞读写），但无专门测试用例或命名。

读者 - 写者 (Readers-Writers): not_found - 检索 'reader.*writer' 无命中；无 RwLock 实现，xv6-user/run_test.c 提及 pthread_rwlock_ebusy 测试但内核未实现读写锁。

哲学家就餐 (Dining Philosophers): not_found - 检索 'dining.*philosoph' 无命中；无相关实现或测试用例。

### Q06_019 是否实现消息传递 (Message Passing, Stallings Ch5) 作为 IPC 机制？（必须三态；区分直接消息传递 Direct / 间接通过邮箱 Mailbox / POSIX mq_open 等；与 SysV msgq 的区别是是否通过内核邮箱路由）

not_found

### Q06_020 是否实现屏障同步 (Barrier Synchronization, Stallings Ch5)？（必须三态；搜索 barrier / sync_barrier / pthread_barrier 或等价；用于多线程/多核同步到同一检查点）

not_found

---


# 第07章 安全机制与权限模型

### Q07_001 特权级隔离形态更接近哪种？

有用户态/内核态隔离（user mode/kernel mode）

### Q07_002 是否存在凭证/权限数据结构（UID/GID/Credential/Capability/ACL 等）？（必须三态）

stub

### Q07_003 是否能证实在 syscall 路径上真实执行了权限检查（open/exec/write 等）？（必须三态；仅有字段不算 implemented）

stub

### Q07_004 若存在权限检查：入口点与核心检查函数链路是什么？（列 2-5 个节点并给证据）

权限检查链路（仅基于 mode 位的 DAC 模型，无身份绑定）：
1. sys_faccessat (kernel/syscall/sysfile.c:870) - 入口点
2. nameifrom (kernel/fs/fs.c) - 路径解析获取 inode
3. mode 位检查 (kernel/syscall/sysfile.c:897-900) - (ip->mode >> 6) & 0x7 提取 owner 权限位
4. 比较 (imode & mode) != mode - 仅模式位匹配，无 UID/GID 验证

注：搜索 check_perm/inode_permission/capability 关键词 0 命中，无独立权限检查函数

### Q07_005 是否实现用户指针验证（access_ok/verify_area/UserInPtr/copyin/copyout 等）？（必须三态）

implemented

### Q07_006 是否实现 seccomp/prctl/sandbox 等系统调用过滤/沙箱？（必须三态；stub 需说明形态：ENOSYS/return 0）

not_found

### Q07_007 是否存在栈保护/溢出防护（stack canary/guard page）或等价机制？（必须三态）

stub

### Q07_008 是否存在审计/安全启动（audit/secure boot/signature）相关逻辑？（必须三态）

not_found

### Q07_009 本项目支持哪些架构（riscv64/aarch64/x86_64/loongarch64 等）？每种架构的安全相关初始化（特权级配置、PMP/MPU/SMEP 等）是否有代码证据？（必须逐架构作答，无证据写「未发现」）

仅支持 riscv64 架构：

**riscv64**：
- 特权级配置：include/hal/riscv.h:47-52 定义 SSTATUS_SPP/SSTATUS_SUM/SSTATUS_PUM
- 用户/内核态切换：kernel/trap/trap.c:175-185 usertrapret() 清除 SSTATUS_SPP 进入 U-mode
- PMP 初始化：sbi/psicasbi/src/main.rs:161-187（Rust SBI 固件）配置 PMP NAPOT 全访问权限
- 页表隔离：kernel/trap/trap.c:168 设置 p->pagetable 为用户页表，通过 trampoline.S 切换

**aarch64/x86_64/loongarch64**：
- 搜索 aarch64|x86_64|loongarch|arm64 关键词，0 命中
- 目录结构仅含 kernel/entry.S（通用）、kernel/entry_qemu.S、kernel/entry_k210.S，均为 RISC-V 汇编

### Q07_010 若项目使用 Rust，是否存在 RAII/所有权/生命周期相关的内核安全机制（如不可 unsafe 直接访问用户内存、锁的 RAII 自动释放等）？（必须三态；给具体模式证据）

not_found

### Q07_011 是否实现了内核/用户页表隔离 (Kernel/User Page Table Isolation, KPTI 或等价机制)？
（x86: CR3 KPTI / SMEP / SMAP；RISC-V: PMP / S-mode 分离；AArch64: TTBR0/TTBR1 隔离；
必须三态；无则写未发现并列出已搜关键字）

implemented

### Q07_012 UID/GID 字段是否在 syscall 路径上真实执行权限检查？（搜索 check_perm/inode_permission；若只有字段无检查链须标注「仅有定义但未强制执行 🔸」；给检查链证据或写「字段存在但无检查链」）

字段存在但无检查链 🔸

**证据**：
1. include/fs/stat.h:57-58 定义 struct kstat 含 uid/gid 字段
2. kernel/syscall/sysfile.c:895 注释 "// assume user as root" 表明权限检查假设所有用户为 root
3. 搜索 check_perm/inode_permission/capability 关键词，0 命中
4. sys_getuid/sys_geteuid/sys_getgid/sys_getegid 均指向同一桩函数（返回 0）

**结论**：stat 结构体有 uid/gid 字段，但 syscall 路径（faccessat/open/exec）未使用这些字段进行权限验证，仅检查 inode->mode 权限位（owner/group/other），无身份绑定。

### Q07_013 访问控制模型 (Access Control Model, Stallings Ch15) 更接近哪种？

自主访问控制 DAC (Discretionary Access Control)：所有者自主设置权限（Unix 权限位）

### Q07_014 是否实现完整性策略 (Integrity Policy, Stallings Ch15)？（如 Biba 模型、只读内核段、代码签名验证、W^X 内存保护等；必须三态）

not_found

---


# 第08章 网络子系统与协议栈

### Q08_001 是否存在网络子系统实现（协议栈或 socket 层）？（必须三态）

not_found

### Q08_002 协议栈来源更接近哪种？

未发现

### Q08_003 是否实现 socket 系统调用接口（socket/bind/connect/sendto/recvfrom 等）？（必须三态）

not_found

### Q08_004 选择一个发送路径（优先 sys_sendto），追踪：syscall → 协议栈 → 网卡驱动。列 3-6 个关键节点并给证据。

❌ 未实现网络功能，无发送路径可追踪。经全面搜索：1) sysnum.h 无 SYS_sendto/SYS_socket 等调用号；2) syscall.c 无网络 syscall 处理函数；3) include/hal/ 和 kernel/hal/ 无 virtio_net.c 网卡驱动；4) Cargo.toml 无 smoltcp/lwip 协议栈依赖。项目仅支持磁盘 I/O（virtio-blk）和串口通信，无网络数据包收发能力。

### Q08_005 是否实现网卡驱动（virtio-net/e1000 等）与收包中断路径？（必须三态）

not_found

### Q08_006 协议支持情况（多选；未发现则留空并在 notes 写 not_found）：

[]

not_found: 未发现任何网络协议栈实现

### Q08_007 是否存在零拷贝/共享缓冲/DMA 描述符等路径（zero-copy）？（必须三态；仅有名词不算 implemented）

not_found

---


# 第09章 调试机制与错误处理

### Q09_001 是否存在日志系统（log/printk/println 宏）与日志级别控制？（必须三态）

stub

### Q09_002 是否存在 panic/崩溃处理路径（panic_handler/oom/abort 等）？（必须三态）

implemented

### Q09_003 panic 路径会输出哪些诊断？（寄存器 dump/栈回溯/停机；必须引用实现证据）

输出 panic 消息 + 栈回溯 (FramePointer 遍历)，无寄存器 dump；随后关中断并死循环停机。

### Q09_004 是否实现栈回溯 (backtrace/unwind/stack_trace)？（必须三态；仅打印 ra 不算）

implemented

### Q09_005 是否存在 **内核驻留的交互式监视器（kernel monitor）**？（对齐 Stallings《操作系统：精髓与设计原理》语境：**在内核态上下文**接受命令、用于探查/操控系统的监视器；**不包括**仅在用户态运行的常规 shell，如 `xv6-user/sh.c`、`user/` 下用户程序等——除非题面另有定义。必须三态；若 `implemented`：须给出 3–10 个 **用户可键入的 monitor 命令名** 及对应 **内核内** 解析/分发入口的 `路径:行号` 证据；仅以用户态 shell 充当内核 monitor 视为 **未切题** 应判 `stub` 或 `not_found` 并说明理由。）

stub

### Q09_006 是否实现 GDB stub（需数据包解析循环，如 handle_gdb_packet）？（必须三态）

not_found

### Q09_007 错误码/错误类型体系是什么？（errno/Result/Error enum；给类型定义与传播点证据）

POSIX 风格 errno 宏定义（int 返回 + 全局 errno 模式），无 Rust Result/Error enum 类型。

### Q09_008 是否存在 trace/perf/ftrace 等跟踪机制或 tracepoints？（必须三态）

stub

---


# 第10章 开发历史与里程碑

## 第 10 章：开发历史与里程碑

本章关注**部署与可运行性层**与**内核机制层**的演进轨迹，基于 Git 提交历史（48 commits，2023-08-09 至 2023-08-21）、关键文件生命周期追踪与 README 文档声明，归纳 xv6-k210 在 13 天开发周期内的技术里程碑。证据来源包括 `get_git_history_summary`、`analyze_authors_contribution`、`trace_file_evolution` 与 `get_commit_diff_summary` 工具输出。

### 10.1 开发周期概览与贡献者分工

#### 10.1.1 提交密度与时间线

仓库在 **13 天**内完成 **48 次提交**（2023-08-09 至 2023-08-21），提交密度最高的模块为：
- `kernel/` 目录：核心内核逻辑（`exec.c`、`proc.c`、`signal.c`、`vm.c`）
- `xv6-user/` 目录：用户程序与测试框架
- `sbi/` 目录：RustSBI 子模块集成（K210 板级支持）

#### 10.1.2 两位核心贡献者的分工图谱

根据 `analyze_authors_contribution` 输出：

| 贡献者 | Commits | 增删行数 | 专注模块 (Top-3) |
|--------|---------|----------|------------------|
| **zrhxlhydjcx** | 25 | +45,437 / -4,222 | `kernel`(25,466 行)、`include`(8,053 行)、`xv6-user`(7,234 行) |
| **ZEMINGMA** | 23 | +7,096 / -2,622 | `kernel`(3,162 行)、`sbi`(2,471 行)、`tools`(1,813 行) |

**分工特征**：
- **zrhxlhydjcx**：主攻内核核心逻辑（进程管理 `proc.c`、执行加载 `exec.c`、内存管理 `vm.c`/`usrmm.c`）与用户程序调试工具
- **ZEMINGMA**：负责 SBI 集成（`sbi/psicasbi` Rust 子模块）、构建系统（`Makefile` 平台切换）、工具链（`tools/kflash.py` K210 烧录脚本）与信号机制重构

### 10.2 三大里程碑事件

#### 10.2.1 里程碑 1：初始骨架搭建 (2023-08-09, commit `b7ffeec`)

**提交信息**：`final start shell`  
**变更规模**：+42,627 行（一次性引入完整 xv6-riscv 代码骨架）

**核心文件清单**（基于 `get_commit_diff_summary` 输出）：
- **构建系统**：`Makefile`（285 行）定义双平台构建（`platform := k210|qemu`）、SBI 集成路径、用户程序编译链
- **内核骨架**：`kernel/` 目录下 22,636 行代码，包含：
  - 进程管理：`kernel/sched/proc.c`、`kernel/exec.c`（初始 316 行）
  - 内存管理：`kernel/mm/vm.c`、`kernel/mm/pm.c`、`kernel/mm/kmalloc.c`
  - 文件系统：`kernel/fs/fat32/`（FAT32 实现）、`kernel/fs/file.c`
  - 中断处理：`kernel/trap/trap.c`、`kernel/intr.c`
- **头文件体系**：`include/` 目录下 8,012 行，定义 `struct proc`、`struct seg`、系统调用号等核心抽象
- **用户程序**：`xv6-user/` 目录下 6,378 行，包含 `sh.c`（shell）、`usertests.c`（综合测试）
- **文档与工具**：`README.md` 声明 12 项功能进度清单、`tools/kflash.py` K210 烧录工具

**意义**：此提交并非从零开始，而是基于 xv6-riscv 上游代码（MIT 6.S081 教学内核）进行 K210 移植的**初始骨架搭建**，一次性引入完整的单核 xv6 功能框架，为后续 13 天的增量开发奠定基础。

#### 10.2.2 里程碑 2：信号机制重构与代码组织优化 (2023-08-16, commit `df1fdc3`)

**提交信息**：`fix signal`  
**变更规模**：+1,751 / -1,839 行（大规模重构）

**核心变更**（基于 `get_commit_diff_summary` 与 `trace_file_evolution` 输出）：

1. **信号代码目录迁移**：
   - 移除：`kernel/mesg/signal.c`（102 行旧实现）
   - 新增：`kernel/sched/signal.c`（283 行新实现）
   - 头文件更新：`include/sched/signal.h` 从 `mesg/signal.h` 迁移并重定义数据结构

2. **信号处理数据结构重构**：
   ```c
   // include/sched/signal.h (df1fdc3 之后)
   struct sig_frame {
       __sigset_t mask;
       struct trapframe *tf;
       struct sig_frame *next;
   };

typedef struct __ksigaction_t {
       struct __ksigaction_t *next;
       struct sigaction sigact;
   } ksigaction_t;
   ```
   从链表 (`list_node_t`) 改为显式指针链 (`next`)，简化内存管理。

3. **Makefile 更新**：
   ```makefile
   # 移除旧路径，添加新路径与汇编桩代码
   - $K/mesg/signal.c \
   + $K/sched/signal.c \
   + $K/trap/sig_trampoline.S \
   ```

4. **进程控制块字段调整**（`include/sched/proc.h`）：
   - 新增：`struct sig_frame *sig_frame`、`int killed`（存储当前信号编号）
   - 调度链表重命名：`next/prev` → `sched_next/sched_pprev`，明确区分调度队列与哈希表

**技术意义**：此次重构将信号机制从"消息传递"抽象 (`mesg/`) 迁移至"进程调度"抽象 (`sched/`)，更符合信号作为**进程间异步通知机制**的语义定位。同时引入 `sig_trampoline.S` 信号桩代码，为后续用户态信号处理函数调用提供汇编级入口。

#### 10.2.3 里程碑 3：用户程序加载与调试工具引入 (2023-08-21, commit `d17dd26`)

**提交信息**：`add userprogs, using dump/show_vm etc to see what happened on earth, but still confused`  
**变更规模**：+869 / -55 行（`kernel/exec.c` 单次最大变更 +295/-24）

**核心变更**：

1. **ELF 动态链接器加载逻辑恢复**（`kernel/exec.c`）：
   ```c
   // d17dd26 恢复动态链接支持
   if(dynamic_need){
       if((intprtr = namei("/libc.so")) == NULL){
           printf("interpreter not found\n");
           goto bad;
       }
       intprtr_sta_loc = load_elf_interp(pagetable, seghead, &intprtr_hdr, intprtr);
       prog_entry = intprtr_sta_loc + intprtr_hdr.entry;
   }
   ```
   在 `df1fdc3` 中曾删除动态链接器加载逻辑（`load_elf_interp` 被移除），此次提交重新引入三版本加载函数（`load_elf_interp`、`load_elf_interp_2`、`load_elf_interp_3`），支持不同映射策略。

2. **内存映射调试工具**：
   ```c
   void show_vm_load(pagetable_t pagetable, uint64 where_addr) {
       struct proc *p = myproc();
       w_satp(MAKE_SATP(pagetable));
       sfence_vma();
       permit_usr_mem();
       pageDump((char *)(where_addr));  // 打印页表项内容
       protect_usr_mem();
       w_satp(MAKE_SATP(p->pagetable));
       sfence_vma();
   }
   ```
   提供虚拟地址到物理地址的页表遍历打印功能，用于调试用户程序加载后的内存布局。

3. **用户测试程序引入**（`Makefile` 更新）：
   - `xv6-user/Guess.c`（157 行）：猜数字游戏，使用 `get_random()` 系统调用生成随机数
   - `xv6-user/timer.c`（49 行）：定时器测试程序
   - `xv6-user/whoIsme.c`（31 行）：打印 ASCII Logo 的标识程序

4. **随机数系统调用**（`kernel/syscall/systime.c`）：
   ```c
   uint64 sys_get_random(void) {
       uint64 seed = readtime();
       return seed;  // 使用时间戳作为伪随机种子
   }
   ```

**技术意义**：此提交标志着 xv6-k210 从"内核可启动"进入"用户程序可调试"阶段。通过引入内存映射调试工具与多样化测试程序，开发者能够直观观察 ELF 加载后的页表状态，加速定位用户态异常（如页面错误、地址映射失败）。

### 10.3 README 声明功能与代码证据对照

README.md 的 **Progress** 清单声明 12 项已实现功能，以下逐项对照代码证据：

| 序号 | README 声明 | 代码证据路径 | 验证状态 |
|------|------------|-------------|----------|
| 1 | Multicore boot | `kernel/main.c:40-55`（hartid 循环启动）、`kernel/entry.S`（多入口汇编） | ✅ implemented |
| 2 | Bare-metal printf | `kernel/printf.c`（152 行）、`kernel/sprintf.c`（170 行） | ✅ implemented |
| 3 | Memory alloc | `kernel/mm/kmalloc.c`（338 行）、`kernel/mm/pm.c`（296 行物理页分配） | ✅ implemented |
| 4 | Page Table | `kernel/mm/vm.c`（1091 行）、`kernel/mm/usrmm.c`（401 行用户态映射） | ✅ implemented |
| 5 | Timer interrupt | `kernel/timer.c`（60 行）、`kernel/trap/trap.c:200-250`（时钟中断处理） | ✅ implemented |
| 6 | S mode extern interrupt | `kernel/intr.c`（41 行）、`kernel/hal/plic.c`（83 行 PLIC 驱动） | ✅ implemented |
| 7 | Receive uarths message | `kernel/console.c`（331 行 UART 串口接收） | ✅ implemented |
| 8 | SD card driver | `kernel/hal/sdcard.c`（970 行 K210 SD 卡驱动）、`kernel/hal/spi.c`（726 行 SPI 控制器） | ✅ implemented |
| 9 | Process management | `kernel/sched/proc.c`（1036 行 `struct proc` 调度器）、`kernel/exec.c`（768 行 ELF 加载） | ✅ implemented |
| 10 | File system | `kernel/fs/fat32/`（FAT32 实现）、`kernel/fs/file.c`（607 行 VFS 抽象） | ✅ implemented |
| 11 | User program | `xv6-user/sh.c`（661 行 shell）、`xv6-user/usertests.c`（2765 行综合测试） | ✅ implemented |
| 12 | Steady keyboard input(k210) | `kernel/hal/gpiohs.c`（204 行 GPIO 按键中断）、`kernel/console.c:150-200` | ⚠️ stub（`blkdev.c:221` 标注 `stub 1`） |

**对照结论**：12 项声明功能中，11 项可在代码中找到完整实现证据，1 项（键盘输入）存在桩代码痕迹（`kernel/fs/blkdev.c:221` 打印 `stub 1`），与第 5 章文件系统分析一致。

### 10.4 当前缺口与未实现功能

基于 `grep_in_repo` 搜索 `TODO|FIXME|stub` 关键词与代码审查，识别以下缺口：

#### 10.4.1 明确标注的未实现功能

1. **文件系统缓存层缺失**（`kernel/fs/fat32/fat.c:336`）：
   ```c
   // here should be a cache layer for FAT table, but not implemented yet.
   ```
   FAT 表访问直接读写磁盘，无缓存优化，影响文件系统性能。

2. **块设备安装桩代码**（`kernel/fs/blkdev.c:221-226`）：
   ```c
   __debug_info("fs_install", "stub 1\n");
   __debug_info("fs_install", "stub 2\n");
   ```
   块设备注册流程未完整实现，可能导致某些存储设备无法挂载。

3. **进程暂停系统调用桩**（`kernel/syscall/sysproc.c:274`）：
   ```c
   // for now it's not very necessary to implement this syscall
   ```
   对应 `sys_pause()` 或类似功能未实现。

4. **SBI 外设时钟配置注释**（`sbi/psicasbi/src/hal/sysctl/k210.rs:87`）：
   ```rust
   // 	// !TODO: set APB for peripherals
   ```
   K210 的 APB 总线时钟未显式配置，可能影响外设时序。

#### 10.4.2 代码审查发现的隐性缺口

1. **网络子系统完全缺失**：
   - 无 `network/`、`net/` 目录
   - `grep_in_repo` 搜索 `socket|tcp|udp|ethernet` 无命中
   - 与第 8 章分析一致：**not_found**

2. **安全凭证机制为桩**（第 7 章验证）：
   - `struct proc` 中无 UID/GID 字段
   - 系统调用路径无权限检查逻辑
   - 仅 `kill()` 使用 `p->killed` 字段存储信号编号，非真实凭证

3. **动态链接器实现不完整**：
   - `exec.c` 中 `load_elf_interp_3` 存在未清理的调试打印（`pageDump()`）
   - `VUMMAP` 硬编码映射地址（`include/memlayout.h` 未定义该宏）
   - 注释残留：`//-------------A1!!!!!!!!!!`、`// 在 locate 之前请看 A1!!!`

4. **实验性调试代码痕迹**：
   - `xv6-user/Guess.c`、`xv6-user/timer.c` 为临时测试程序，非标准 Unix 工具
   - `kernel/exec.c:652` 注释 `// todo:` 未完成的错误处理路径

### 10.5 关键文件演进轨迹

#### 10.5.1 `kernel/exec.c` 的 12 次变更生命周期

根据 `trace_file_evolution` 输出，`exec.c` 经历以下关键演进节点：

| 日期 | Commit SHA | 变更规模 | 技术主题 |
|------|-----------|----------|----------|
| 2023-08-09 | `b7ffeec` | +316 | 初始引入（316 行基础 ELF 加载） |
| 2023-08-10 | `5c67f06` | +181/-41 | 修复 ELF 解析细节（`ph.type` 判断逻辑） |
| 2023-08-15 | `94b4317` | +40/-15 | 提交信息提及"a big step"，引入动态链接器框架 |
| 2023-08-16 | `df1fdc3` | +49/-225 | **信号重构**：删除动态链接器代码，简化 `exec` 流程 |
| 2023-08-19 | `30b8ca5` | +415/-53 | **恢复**：回退 `df1fdc3` 的部分删除，重新引入动态链接 |
| 2023-08-20 | `c980d73` | +53/-416 | **大幅精简**：删除调试打印与冗余逻辑，但仍保留动态链接框架 |
| 2023-08-21 | `d17dd26` | +506/-54 | **最终形态**：引入三版本 `load_elf_interp_*` 函数与内存调试工具 |

**演进特征**：`exec.c` 在 12 次变更中经历"引入→精简→恢复→再精简→最终完善"的迭代过程，反映开发者在动态链接器支持问题上的反复探索。最终版本（768 行）较初始版本（316 行）规模扩大 2.4 倍，主要增量来自：
- 动态链接器加载逻辑（`load_elf_interp` 系列函数）
- 内存映射调试工具（`show_vm_load`、`many_vm_load`、`show_stack`）
- 辅助函数（`size4mapping` 计算 ELF 映射范围）

#### 10.5.2 信号机制代码迁移轨迹

- **2023-08-16 之前**：信号代码位于 `kernel/mesg/signal.c`（102 行），采用链表抽象 (`list_node_t`)
- **2023-08-16 (`df1fdc3`)**：迁移至 `kernel/sched/signal.c`（283 行），重构为显式指针链，新增 `sig_frame` 结构体
- **2023-08-16 之后**：无进一步变更，信号机制稳定

迁移动因：信号本质是**进程调度时的异步事件处理**，归入 `sched/` 目录更符合抽象层次（内核机制层→调度子系统）。

### 10.6 构建系统与平台适配演进

#### 10.6.1 双平台构建支持（`Makefile` 历史）

初始提交 `b7ffeec` 即定义双平台切换机制：
```makefile
# platform := k210
platform := qemu
```

关键演进节点：
- **2023-08-10 (`b3cdaddd`)**：ZEMINGMA 引入 `sbi/psicasbi` Rust 子模块（+2,319 行），提供 K210 板级 SBI 实现
- **2023-08-15 (`fe04f6ea`)**：标准化构建流程，清理冗余 Makefile 规则（-285 行）
- **2023-08-19 (`15ff2742`)**：引入 `tools/` 目录（+1,813 行），包含 `kflash.py` K210 烧录脚本

#### 10.6.2 SBI 集成历史

- **2023-08-10 (`1edb9b77`)**：添加 PMP（Physical Memory Protection）支持
- **2023-08-10 (`bf1d110e`)**：修复 PMP 寄存器 bug（`pmp fix rg bug`）
- **2023-08-16 (`1c540ef8`)**：修复 SBI 编译配置（`fix sbi`）
- **2023-08-16 (`ebfda0cc`)**：在根目录添加 `.gitmodules` 声明 SBI 子模块

SBI 集成由 ZEMINGMA 主导，采用 Rust 语言实现（`sbi/psicasbi/` 目录），符合 RISC-V 生态趋势。

### 10.7 开发模式特征与局限性

#### 10.7.1 快速迭代模式

- **13 天 48 commits**：平均每天 3.7 次提交，符合课程项目冲刺节奏
- **大规模重构频繁**：`df1fdc3`（+1,751/-1,839）、`d17dd26`（+869/-55）等提交显示开发者敢于进行结构性调整
- **调试代码残留**：`exec.c` 中 `printf("NNN: ...")` 风格调试打印、`pageDump()` 直接调用，反映开发周期紧张，未及清理

#### 10.7.2 技术债务与局限性

1. **文档与代码脱节**：
   - README 声明"Steady keyboard input(k210)"已实现，但代码中存在 `stub` 标注
   - 无 CHANGELOG 或版本标签（`git tag` 为空）

2. **测试覆盖不足**：
   - 用户程序测试以手动交互为主（`Guess.c` 猜数字游戏）
   - 无自动化测试框架（如 CI/CD 配置）

3. **代码注释质量参差**：
   - 关键函数缺少文档注释（如 `load_elf_interp_3` 无参数说明）
   - 临时注释残留（`//-------------A1!!!!!!!!!!`）

4. **架构耦合度高**：
   - K210 特定驱动（`kernel/hal/sdcard.c`、`kernel/hal/spi.c`）与通用 xv6 代码混合
   - 条件编译依赖 `#ifdef QEMU` 宏，未采用模块化设计

### 10.8 本章小结

xv6-k210 项目在 13 天开发周期内完成从骨架搭建到用户程序调试的完整演进，三位里程碑事件（初始骨架、信号重构、用户程序加载）标志技术成熟度提升。两位贡献者分工明确：zrhxlhydjcx 主攻内核核心逻辑，ZEMINGMA 负责 SBI 集成与构建系统。

**已验证功能**：README 声明的 12 项功能中 11 项可在代码中找到实现证据，涵盖多核启动、内存管理、进程调度、文件系统、中断处理等核心机制。

**当前缺口**：网络子系统完全缺失、安全凭证机制为桩、文件系统缓存层未实现、部分实验性代码痕迹未清理。这些缺口反映教学项目的典型特征：优先实现核心功能以通过评测，非关键特性（网络、安全）留待后续迭代。

**技术遗产**：项目为 K210 开发板提供可运行的 xv6 移植版本，支持 FAT32 文件系统、多核调度、信号机制等高级特性，为后续课程实验（如添加系统调用、优化调度算法）奠定基础。然而，快速迭代模式遗留的技术债务（调试代码残留、注释不足、测试覆盖低）需在后续维护中逐步清理。

---


---

*本报告由 OS-Agent-D 自动生成*  
*生成时间: 2026-04-22 12:42:26*  
*分析耗时: 51.3 分钟*
