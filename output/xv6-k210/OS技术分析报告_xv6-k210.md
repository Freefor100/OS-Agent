# xv6-k210 操作系统技术分析报告

> **年份**: 2021

> **赛事**: 操作系统赛

> **子赛事**: 内核实现赛道

> **学校**: 华中科技大学

> **队伍名称**: 3Los

> **仓库地址**: https://gitlab.eduxiji.net/retrhelo/xv6-k210

> **分析日期**: 2026年04月30日

> **分析工具**: OS-Agent-D

> **报告质量打分**: 95/100

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

Now I have all the evidence needed. Let me compile the final JSON answer.

```json
{
  "schema_version": "v1",
  "stage_id": "01_overview",
  "stage_title": "项目概览与技术栈",
  "terminology_profile": "stallings_en_zh",
  "answers": [
    {
      "question_id": "Q01_001",
      "question_type": "long_answer",
      "question_text": "第 1 章：项目概览与技术栈",
      "value": "## 第 1 章：项目概览与技术栈\n\n本章关注**部署与可运行性层**及**内核机制层**的宏观架构，以源码、构建配置、文档为证据基础，系统梳理 xv6-k210 的项目定位、技术栈、构建体系、目录结构及模块完成度。证据类型包括 Makefile、链接脚本、入口汇编、头文件组织、目录树及前置各章报告。\n\n### 快速总览\n\n**一句话定位**：xv6-k210 基于 MIT xv6-riscv 移植到 Kendryte K210 (RISC-V 64) 的宏内核教学/竞赛操作系统，主要语言 C（内核）+ Rust（SBI），最突出技术点为自研 FAT32 文件系统 + COW/Lazy Allocation 内存管理 + 三级优先级调度。\n\n### 评测与交付适配\n\n- **Delivery**：`Makefile:152-158` 的 `all` 目标生成固定产物 `k210.bin`（由 `kernel.bin` 拼接到 SBI 偏移 128KB 处），`tools/flash-list.json:11` 引用 `k210.bin` 作为烧录目标。QEMU 平台产物为 `target/kernel`（ELF 格式），通过 `-kernel` 参数加载。\n- **Harness**：存在自测框架 `xv6-user/ostest.c` 和 `xv6-user/ostest2.c`，后者通过 `execve(\"busybox\", [\"sh\", \"testcode_scene.sh\"], ...)` 运行场景测试脚本。`xv6-user/usertests.c`（2765 行）包含大量单元测试。README 未描述 CI/CD 流水线，未发现 `.github/workflows` 或 `gitlab-ci` 配置。\n- **PlatformProfile**：README 描述的双平台（K210 物理板 + QEMU `-machine virt`）与代码一致：`Makefile:1-2` 通过 `platform` 变量切换，`Makefile:36-37` 条件定义 `-D QEMU` 宏，`Makefile:53` QEMU 使用 `-machine virt -smp 2`。与第 02 章启动链、第 05 章块设备驱动（SD 卡 vs virtio）的结论完全吻合。\n- **SubsystemDepth**：第 08 章确认网络子系统完全未实现；第 07 章确认 UID/GID 仅为桩实现（`sys_getuid` 恒返回 0）；第 03 章确认无 swap/page cache/TLB shootdown；第 04 章确认无线程模型/负载均衡/futex。这些缺口意味着无法运行依赖网络或完整多用户权限的测试套件（如 LTP）。\n\n### 各模块技术全景（基于 02–10 章报告提取）\n\n#### 02 启动/架构与 Trap/系统调用\n\n##### 技术清单\n\n启动链与引导交接：SBI 固件 (M 态) → 内核入口 `_entry`/`_start` (S 态) → `main()`，典型 RISC-V SBI 交接模式。\n特权级与执行模式（硬件隔离模型）：RISC-V S/U 双特权级，通过 `sstatus.SPP` 位区分，trampoline 蹦床实现用户态↔内核态切换。\nMMU 与内核地址空间初建：Sv39 页表，`kvminit()` 建立内核直接映射（VIRT_OFFSET=0x3F00000000），`kvminithart()` 写 SATP 启用分页。\n同步异常与用户态陷阱入口（含 syscall 路径）：`uservec` (trampoline.S) → `usertrap()` → `syscall()` → `syscalls[]` 分发表（65 项）。\n异步设备中断与中断控制器抽象：PLIC 中断控制器，`plicinit()`/`plic_claim()`/`plic_complete()`，K210 通过 SBI 代理 S 态外部中断。\n时钟源与定时中断（tick/计账/抢占触发）：CLINT 定时器，`set_next_timeout()` 设置下一次时钟中断，`proc_tick()` 递减进程 timer 并触发调度。\n用户内存访问与系统调用参数安全（copyin/out 等）：`copyout2()`/`copyin2()` 通过 `partofseg()` 验证地址段合法性，`safememmove()` 安全拷贝。\n\n##### 关键实现、证据与细粒度锚点\n\n- 启动入口：K210 平台 `kernel/entry_k210.S:2` 的 `_start`，QEMU 平台 `kernel/entry_qemu.S:2` 的 `_entry`，统一入口 `kernel/entry.S:2` 的 `_entry`。链接脚本 `linker/linker64.ld:2` 指定 `ENTRY(_entry)`，`linker/k210.ld:2` 指定 `ENTRY(_start)`。\n- 平台差异：`linker/k210.ld:4` 和 `linker/linker64.ld:4` 的 `BASE_ADDRESS = 0x80020000`（K210 偏移 128KB 留给 SBI），`linker/qemu.ld:4` 的 `BASE_ADDRESS = 0x80200000`。\n- 初始化序列：`kernel/main.c:34-98` 的 `main()` 按 hart 0/1 分支，hart 0 执行 `cpuinit→floatinithart→consoleinit→printfinit→kpminit→kvminit→kvminithart→kmallocinit→trapinithart→procinit→plicinit→plicinithart→disk_init→binit→userinit→scheduler`。\n- Trap 向量：`kernel/trap/trap.c:68` 的 `trapinithart()` 设置 `w_stvec((uint64)kernelvec)`，`kernel/trap/kernelvec.S:7` 的 `kernelvec` 保存全部 32 个通用寄存器后调用 `kerneltrap()`。\n- 系统调用分发表：`kernel/syscall/syscall.c:188-280` 的 `static uint64 (*syscalls[])(void)` 含 65 个表项，`syscall()` 在 `kernel/syscall/syscall.c:340-345` 做边界检查 `num < NELEM(syscalls)`。\n- TrapFrame：`include/trap.h:18-76` 的 `struct trapframe` 含 32 个通用寄存器 + 32 个浮点寄存器 + 5 个内核元数据字段，共 560 字节。\n- 用户态返回：`kernel/trap/trampoline.S:147` 的 `userret` 末尾执行 `sret` 从 S 态返回 U 态，`kernel/trap/trap.c:76` 的 `usertrapret()` 设置 `SSTATUS_SPP=0`。\n\n##### 依赖与工具\n\n- 工具链：`riscv64-unknown-elf-gcc` + `ld` + `objcopy` + `objdump`（`Makefile:13-18`），编译标志 `-march=rv64imafdc -mcmodel=medany`。\n- SBI 层：自研 PsicaSBI（Rust/cargo），子模块 `sbi/psicasbi`（`.gitmodules:1-3`），通过 `cargo build --no-default-features --features=$(platform)` 编译。\n- 模拟器：`qemu-system-riscv64`，参数 `-machine virt -smp 2 -m 6M -bios $(SBI)`。\n\n##### 与相邻模块的衔接\n\n- 为第 03 章内存管理提供页表基础：`kvminit()` 建立的内核页表被 `kvmcreate()` 复制为每个进程的根页表，`kvminithart()` 的 SATP 写入是 MMU 启用的唯一入口。\n- 为第 04 章进程调度提供 trap 入口：`usertrap()` 中的 `syscall()` 调用是进程执行系统调用的必经路径，`usertrapret()` 中的 `sret` 是进程返回用户态的唯一出口。\n- 为第 05 章文件系统提供系统调用分发：`syscalls[]` 表中的 `sys_read`/`sys_write`/`sys_openat` 等将用户态 I/O 请求路由到 VFS 层。\n\n#### 03 内存管理\n\n##### 技术清单\n\n物理内存组织与页帧分配器：双池架构（`struct pm_allocator` multiple + single），multiple 用 first-fit 分配多页，single 用 LIFO 栈分配单页。\n页表、地址空间与虚实地址转换：Sv39 三级页表，`walk()`/`mappages()`/`unmappages()` 实现 VA→PA 映射，内核与用户共享同一页表（高半核模型）。\n缺页与页面错误处理（含按需分页/惰性路径）：`handle_page_fault()` 按段类型四路分发（COW/懒分配/ELF 加载/mmap），`handle_excp()` 将 scause 映射为 kind。\n进程虚拟地址空间布局与映射接口：段链表 `struct seg` 管理用户地址空间，`newseg()` 创建段描述符，`uvmalloc()`/`uvmfree()` 管理映射。\n高级策略（CoW/Lazy/换页/mmap 等）：CoW fork（`PTE_COW` 标记 + `handle_store_page_fault_cow` 断点复制）、Lazy Allocation（HEAP/STACK 段推迟到缺页分配）、Lazy ELF Load（按需加载程序段）、mmap（`do_mmap`/`do_munmap` 支持匿名/文件/固定映射）。\n页缓存或与 FS 块缓存的边界（归入本章或与第 05 章交叉说明）：无独立页缓存；mmap 文件映射使用 inode 内嵌红黑树 `i_rb_page_cache` 索引映射页，块缓存 `bio.c` 归第 05 章。\n\n##### 关键实现、证据与细粒度锚点\n\n- 双池分配器：`kernel/mm/pm.c:31-38` 定义 `struct pm_allocator`（含 `spinlock lock` + `struct run *freelist` + `uint64 npage`），`kernel/mm/pm.c:179-296` 的 `kpminit()` 初始化双池，`allocpage_n()` 从 multiple 分配，`_allocpage()` 从 single 分配。\n- Sv39 页表：`kernel/mm/vm.c:211-230` 的 `walk()` 三级 for 循环遍历 PX(2)/PX(1)/PX(0)，`kernel/mm/vm.c:298-333` 的 `mappages()` 逐页建立映射。\n- CoW：`kernel/mm/vm.c:22` 定义 `#define PTE_COW PTE_RSW1`，`kernel/mm/vm.c:556-615` 的 `uvmcopy()` 在 fork 时清除 PTE_W 并标记 PTE_COW，`kernel/mm/vm.c:975-999` 的 `handle_store_page_fault_cow()` 在缺页时断点复制。\n- 缺页总入口：`kernel/mm/vm.c:1039-1105` 的 `handle_page_fault()` 通过 `locateseg()` 查段后按 `seg->type` 分发到 COW/懒分配/ELF 加载/mmap 子处理器。\n- mmap：`kernel/mm/mmap.c:710-771` 的 `do_mmap()` 支持 MAP_FIXED/MAP_ANONYMOUS/MAP_SHARED/MAP_PRIVATE，`kernel/mm/mmap.c:773-817` 的 `do_munmap()` 支持段分割释放。\n- 用户指针安全：`kernel/mm/vm.c:786-802` 的 `copyout2()` 调用 `partofseg()` 验证地址段，`kernel/mm/vm.c:719-754` 的 `safememmove()` 设置存档点后逐字节拷贝。\n- 物理内存范围：`include/memlayout.h:99-102` 定义 `KERNBASE=0x80020000`、`PHYSTOP=0x80600000`，可用约 6 MB。页大小 `PGSIZE=4096`（`include/hal/riscv.h:378`），MAXVA=256 GB（`include/hal/riscv.h:408`）。\n\n##### 依赖与工具\n\n- 无外部 crate/库依赖。物理页分配器、页表操作、mmap 均为自研 C 实现。红黑树 `kernel/utils/rbtree.c` 用于 mmap 文件映射页索引。\n\n##### 与相邻模块的衔接\n\n- 为第 04 章进程创建提供地址空间复制：`uvmcopy()` 在 `clone()` 中被调用以复制父进程页表（含 CoW 语义），`uvmfree()` 在 `exit()` 中释放进程地址空间。\n- 为第 05 章文件系统提供 mmap 文件映射：`do_mmap()` 接收 `struct file *` 参数，`handle_page_fault_mmap()` 在缺页时从文件读取数据（调用 `filewrite`/`fileread` 路径）。\n- 为第 02 章 trap 处理提供缺页分发：`handle_excp()` 将 EXCP_LOAD_PAGE/EXCP_STORE_PAGE/EXCP_INST_PAGE 路由到 `handle_page_fault()`。\n\n#### 04 进程/调度与多核\n\n##### 技术清单\n\n进程或线程抽象与调度实体（PCB/TCB）：统一 `struct proc`（无独立 TCB），含 context、trapframe、segment、fds、signal 等全部字段。\n调度策略与就绪队列结构：三级优先级数组 `proc_runnable[PRIORITY_NUMBER]`（TIMEOUT=0 > IRQ=1 > NORMAL=2），全局链表非 per-CPU。\n抢占模型与时间片/优先级（可协作则注明）：优先级抢占式，timer 字段递减到 0 后迁移到 PRIORITY_TIMEOUT 队列，无独立时间片轮转。\n上下文切换与内核栈/寄存器约定：`swtch.S` 保存/恢复 ra, sp, s0-s11（14 个 callee-saved 寄存器），浮点寄存器通过 `floatstore`/`floatload` 二进制片段单独保存到 trapframe。\n生命周期（创建/执行/阻塞/退出/wait 与僵尸）：RUNNABLE→RUNNING→SLEEPING→RUNNABLE→ZOMBIE 状态机，`clone()` 创建、`exit()` 退出、`wait4()` 回收。\n多核、每 CPU 状态与 IPI/迁移（若适用）：双核支持（NCPU=2），全局调度队列 + `proc_lock`，`wakeup()` 通过 `sbi_send_ipi()` 跨核唤醒，无负载均衡/任务迁移。\n\n##### 关键实现、证据与细粒度锚点\n\n- PCB 结构体：`include/sched/proc.h:51-104` 的 `struct proc` 含 pid、state、parent/child/sibling 树指针、context、trapframe、segment、fds、sig_act/sig_pending 等全部字段。\n- 调度器：`kernel/sched/proc.c:671-713` 的 `scheduler()` 每核 idle 循环，`kernel/sched/proc.c:609-627` 的 `__get_runnable_no_lock()` 按优先级从高到低遍历选择。\n- 上下文切换：`kernel/sched/swtch.S:1-41` 的 `swtch` 保存/恢复 14 个寄存器，`kernel/sched/proc.c:714-752` 的 `sched()` 在切换前保存浮点上下文。\n- 进程创建：`kernel/sched/proc.c:291-372` 的 `clone()` 复制地址空间（`copysegs`）、文件表（`copyfdtable`）、信号设置，建立父子树关系。\n- 进程退出：`kernel/sched/proc.c:405-476` 的 `exit()` 释放资源（`delsegs`+`uvmfree`+`dropfdtable`），孤儿重父给 `__initproc`，唤醒父进程。\n- 信号机制：`kernel/sched/signal.c:177-262` 的 `sighandle()` 构造用户态 handler 上下文（分配 sig_frame + 新 trapframe），`kernel/sched/signal.c:263-283` 的 `sigreturn()` 恢复原 trapframe。\n- PID 分配：`kernel/sched/proc.c:38` 的 `static int __pid` 单调自增（`kernel/sched/proc.c:233`），不回收。\n\n##### 依赖与工具\n\n- 无外部 crate/库依赖。调度器、进程管理、信号机制均为自研 C 实现。浮点上下文保存/恢复使用手工编写的二进制机器码片段（`floatstore`/`floatload`）。\n\n##### 与相邻模块的衔接\n\n- 为第 03 章内存管理提供进程地址空间生命周期：`clone()` 调用 `copysegs()`/`uvmcopy()` 复制地址空间，`exit()` 调用 `delsegs()`/`uvmfree()` 释放。\n- 为第 05 章文件系统提供 fd 表归属：`struct proc` 内嵌 `fdtable fds`，`fdalloc()` 操作 `myproc()->fds`，`clone()` 调用 `copyfdtable()` 复制。\n- 为第 06 章同步机制提供 sleep/wakeup：`sleep()`/`wakeup()` 基于 `proc_lock` 保护的进程链表实现阻塞/唤醒，是 sleeplock 和管道阻塞的基础。\n\n#### 05 文件系统与设备 I/O\n\n##### 技术清单\n\nVFS 与 inode/file 等对象模型：四层 C 函数指针操作表（`fs_op`/`inode_op`/`dentry_op`/`file_op`），`struct superblock`/`inode`/`dentry`/`file` 构成 VFS 对象模型。\n路径解析与挂载/命名空间：`lookup_path()` 支持绝对/相对路径与 `.`/`..`，`do_mount()` 支持将 FAT32/devfs/procfs 挂载到统一命名空间。\n具体文件系统实现形态：自研 FAT32（BPB 解析、FAT 表簇链、VFAT LFN 支持），内存虚拟 FS（rootfs/devfs/procfs）。\n文件描述符与打开文件表：链表扩展的固定数组 `struct fdtable`（NOFILE=16），`fdalloc()` 动态扩展链表，每进程独立 fd 表。\n块缓存、写回与磁盘 I/O 路径：LRU 块缓存 `bio.c`（BNUM=2500 个 buf），`bget()`/`bread()`/`bwrite()` 接口，异步 SD 卡写回。\n字符设备与块设备驱动框架（含 virtio 等）：`disk_read`/`disk_write` 抽象接口，K210 平台 SD 卡驱动（SPI 模式 + DMAC），QEMU 平台 virtio 块设备驱动。\n\n##### 关键实现、证据与细粒度锚点\n\n- VFS 操作表：`include/fs/fs.h:45-76` 定义 `struct fs_op`（7 个函数指针）、`struct inode_op`（8 个）、`struct file_op`（5 个）、`struct dentry_op`（2 个）。\n- FAT32 实现：`kernel/fs/fat32/fat32.c:47-140` 的 `fat32_init()` 解析 BPB 并验证 FAT32 签名，`kernel/fs/fat32/fat.c:1-100` 的 `read_fat()` 遍历簇链，`kernel/fs/fat32/cluster.c:50-80` 的 `alloc_clus()` 分配空闲簇。\n- 块缓存：`kernel/fs/bio.c:84-106` 的 `binit()` 初始化 2500 个 buf 和 LRU 链表，`kernel/fs/bio.c:108-183` 的 `bget()` 实现 LRU 驱逐（从 `lru_head.prev` 取最久未使用 buf）。\n- 文件打开路径：`kernel/syscall/sysfile.c:194-267` 的 `sys_openat` → `kernel/fs/fs.c:24/474` 的 `create`/`nameifrom` → `kernel/fs/fs.c:413-462` 的 `lookup_path` → `kernel/fs/fs.c:320-388` 的 `dirlookup` → `kernel/fs/fat32/fat32.c:562` 的 `fat_lookup_dir`。\n- 管道：`kernel/fs/pipe.c:39-93` 的 `pipealloc()` 创建环形缓冲区 + 两个 file 对象，`kernel/fs/pipe.c:240-300` 的 `pipewrite()` 支持动态扩展缓冲区。\n- poll：`kernel/fs/poll.c:125-243` 的 `pselect()` 完整实现（遍历 fdset、注册 wait_queue、支持超时和信号中断），`ppoll()` 为桩实现。\n- 伪文件系统：`kernel/fs/rootfs.c:230-313` 的 `rootfs_init()` 创建 devfs（`/dev/console`、`/dev/vda2`、`/dev/zero`、`/dev/null`）和 procfs（`/proc/mounts`、`/proc/meminfo`）。\n\n##### 依赖与工具\n\n- 无外部 crate/库依赖。FAT32、VFS、块缓存、管道、poll 均为自研 C 实现。`mkfs.vfat` 用于生成 FAT32 磁盘镜像（`Makefile:278`）。\n\n##### 与相邻模块的衔接\n\n- 为第 04 章进程提供 fd 表操作：`fdalloc()`/`fdclose()`/`copyfdtable()` 操作 `myproc()->fds`，`exec()` 中 `fdcloexec()` 关闭 O_CLOEXEC fd。\n- 为第 03 章内存管理提供 mmap 文件映射后端：`do_mmap()` 接收 `struct file *`，缺页时 `handle_page_fault_mmap()` 通过 `fileread()` 从文件读取数据。\n- 为第 06 章 IPC 提供管道实现：`pipealloc()` 创建的两个 `file` 对象通过 `sys_pipe` 返回给用户态，`pipewrite`/`piperead` 使用 `sleep`/`wakeup` 实现阻塞语义。\n\n#### 06 同步与 IPC\n\n##### 技术清单\n\n自旋锁与中断上下文临界区规则：`struct spinlock`（`__sync_lock_test_and_set` 原子 swap），`push_off()`/`pop_off()` 关中断，持有锁期间不可抢占。\n可睡眠互斥与锁序/死锁约束（若述及）：`struct sleeplock`（内部 spinlock + `sleep`/`wakeup`），`proc_lock` 必须最后获取（注释规定锁顺序）。\n等待队列、睡眠与唤醒：`struct wait_queue`（双向链表 + spinlock），`sleep()`/`wakeup()` 基于 `proc_lock` 保护的进程链表，防丢唤醒（持锁检查条件后入睡）。\n管道等字节流 IPC：环形缓冲区管道（`struct pipe`），动态扩展缓冲区，阻塞读写（`sleep`/`wakeup`），通过 `file` 对象暴露为 FD。\n信号与异步通知：完整 POSIX 信号（`rt_sigaction`/`rt_sigprocmask`/`kill`/`sighandle`/`sigreturn`），SIGCHLD 通知父进程。\n共享内存或 futex 等（若本仓库有）：不适用。未发现 SysV shm 或 futex 实现（前置第 06 章确认 0 命中）。\n\n##### 关键实现、证据与细粒度锚点\n\n- 自旋锁：`include/sync/spinlock.h:7-12` 定义 `struct spinlock`，`kernel/sync/spinlock.c:34` 使用 `__sync_lock_test_and_set` 原子操作，`kernel/intr.c:12-22` 的 `push_off()`/`pop_off()` 关中断。\n- 睡眠锁：`include/sync/sleeplock.h:10-16` 定义 `struct sleeplock`（内嵌 spinlock），`kernel/sync/sleeplock.c` 基于 `sleep`/`wakeup` 实现阻塞。\n- 等待队列：`include/sync/waitqueue.h:17-25` 定义 `struct wait_queue` 和 `struct wait_node`，用于管道和 poll 的阻塞等待。\n- sleep/wakeup：`kernel/sched/proc.c:582-598` 的 `sleep()` 持 `proc_lock` 检查 chan 后移入 sleep 链表，`kernel/sched/proc.c:392-403` 的 `wakeup()` 持 `proc_lock` 遍历唤醒。\n- 管道：`kernel/fs/pipe.c:39-93` 的 `pipealloc()` 创建 `struct pipe`（含 `data[PIPE_SIZE]` 环形缓冲区、`nread`/`nwrite` 指针、`lock` 自旋锁、两个 wait_queue）。\n- 信号：`kernel/sched/signal.c:177-262` 的 `sighandle()` 分配 sig_frame + 新 trapframe 构造用户态 handler 上下文，`kernel/sched/signal.c:263-283` 的 `sigreturn()` 恢复原 trapframe。\n- 锁顺序：`kernel/sched/proc.c:249-251` 注释规定 `proc_lock` 必须最后获取，`kernel/fs/fs.c:582` 注释 \"just try, in case of deadlock\" 表明死锁预防意识。\n\n##### 依赖与工具\n\n- 无外部 crate/库依赖。自旋锁使用 GCC 内置 `__sync_*` 原子操作，无 Rust `std::sync` 或 `core::sync::atomic` 依赖。\n\n##### 与相邻模块的衔接\n\n- 为第 04 章进程调度提供 sleep/wakeup 阻塞机制：`sleep()` 将进程从 `proc_runnable` 移除并插入 `proc_sleep`，`wakeup()` 将进程移回 `proc_runnable` 并可选发送 IPI。\n- 为第 05 章管道和 poll 提供阻塞语义：`pipewrite`/`piperead` 在缓冲区满/空时调用 `sleep`，`pipewakeup` 调用 `wakeup`；`pselect` 通过 `wait_queue` 注册等待节点。\n- 为第 03 章物理页分配器提供临界区保护：`pm_allocator.lock` 保护 `multiple` 和 `single` 分配器的 freelist 操作。\n\n#### 07 安全机制\n\n##### 技术清单\n\n硬件隔离与特权域模型：RISC-V S/U 双特权级，通过 `sstatus.SPP` 位区分，页表 PTE_U 位控制用户可访问。\n访问控制模型（DAC/MAC/Capability 等，无则写不适用）：仅有特权级隔离，无 UID/GID 细粒度访问控制（`sys_getuid` 恒返回 0，`struct proc` 无 uid/gid 字段）。\n用户指针验证与内核/用户空间数据拷贝边界：`copyout2()`/`copyin2()` 通过 `partofseg()` 验证地址段合法性，`safememmove()` 设置存档点安全拷贝。\n可执行空间保护与权限位策略（W^X 等）：桩实现。页表 PTE_R/W/X 位控制权限，但无显式 W^X 策略代码。\n其他沙箱或策略（seccomp/namespace/cgroup 等，无则写不适用）：不适用。未发现 seccomp/prctl/cgroup 实现（前置第 07 章确认 0 命中）。\n\n##### 关键实现、证据与细粒度锚点\n\n- 特权级隔离：`include/hal/riscv.h:48` 定义 `SSTATUS_SPP`，`kernel/trap/trap.c:76` 的 `usertrapret()` 设置 `x &= ~SSTATUS_SPP` 返回 U 态。\n- 用户内存访问控制：`include/mm/vm.h:13-33` 的 `permit_usr_mem()`/`protect_usr_mem()` 通过 SSTATUS_SUM (QEMU) 或 SSTATUS_PUM (K210) 位切换内核访问用户内存权限。\n- 用户指针验证：`kernel/mm/vm.c:786-802` 的 `copyout2()` 调用 `kernel/mm/usrmm.c:103-115` 的 `partofseg()` 验证 `[start, end)` 完全落在同一段内。\n- 文件访问权限：`kernel/fs/file.c:119-120` 的 `fileread()` 检查 `f->readable`，`kernel/fs/file.c:163-164` 的 `filewrite()` 检查 `f->writable`，基于 `file` 对象标志而非 UID/GID。\n- 权限检查链路：`usertrap` → `syscall` → `sys_read`/`sys_write` → `fileread`/`filewrite` → 检查 `f->readable`/`f->writable` → 失败返回 `-EPERM`。\n\n##### 依赖与工具\n\n- 无外部安全框架或 TEE 依赖。安全机制完全基于 RISC-V 硬件特权级 + 自研软件检查。\n\n##### 与相邻模块的衔接\n\n- 为第 02 章 trap 处理提供用户态隔离：`usertrap()` 断言 `(r_sstatus() & SSTATUS_SPP) == 0` 确保来自用户态，`kerneltrap()` 断言 `(r_sstatus() & SSTATUS_SPP) == 1` 确保来自内核态。\n- 为第 03 章内存管理提供用户指针安全：`copyout2()`/`copyin2()` 在访问用户空间前调用 `partofseg()` 验证，`safememmove()` 通过 `kern_pgfault_escape` 处理缺页失败。\n- 为第 05 章文件系统提供访问控制：`fileread`/`filewrite` 的 `readable`/`writable` 检查是文件访问的唯一权限控制点。\n\n#### 08 网络协议栈\n\n##### 技术清单\n\n套接字抽象与用户态 API：不适用。未发现 socket 系统调用（`sys_socket`/`sys_bind`/`sys_connect` 等 0 命中）。\n协议栈分层与数据面实现形态：不适用。未发现任何协议栈实现（TCP/IP/UDP/ARP 等均无）。\n网卡驱动与收发包/DMA 路径：不适用。未发现网卡驱动（`virtio.h:21` 仅注释 \"1 is net\"，无 virtio-net 驱动实现）。\n与协议栈缓冲与 sk_buff 类抽象（若适用）：不适用。\n与文件层或块设备的衔接（若适用）：不适用。\n\n##### 关键实现、证据与细粒度锚点\n\n- 网络子系统完全未实现。`kernel/syscall/syscall.c:188-280` 的 `syscalls[]` 表中无任何网络相关系统调用。\n- `include/errno.h:95` 定义了 `ENOTSOCK 88`，`include/fs/stat.h:11` 定义了 `S_IFSOCK 0140000`，但仅为头文件定义，无任何代码使用。\n- `include/hal/virtio.h:21` 注释 `// 1 is net` 表明 virtio-net 设备 ID 已知，但无对应驱动实现。\n\n##### 依赖与工具\n\n- 无网络相关依赖。\n\n##### 与相邻模块的衔接\n\n- 与第 05 章文件系统的潜在衔接点（socket 作为 VFS 文件对象）未实现：`S_IFSOCK` 宏已定义但无创建 socket 文件对象的代码路径。\n- 与第 02 章设备中断的潜在衔接点（网卡中断处理）未实现：无网卡驱动，`devintr()` 中无网络设备中断分支。\n\n#### 09 调试与错误处理\n\n##### 技术清单\n\nPanic/oops 与致命错误停机路径：`panic()` 输出红色 `[ERROR]` 消息 + 栈回溯 + 关中断 + 无限循环停机，`panicked=1` 冻结其他 CPU 输出。\n日志级别与可观测输出：`__debug_info`/`__debug_warn`/`__debug_error` 三级调试宏，编译时 `mode=debug` + `module=` 按文件精准开关。\n栈回溯与符号化/调试钩子：`backtrace()` 基于 `r_fp` (s0) 帧指针链遍历，打印每个栈帧的返回地址 (ra-4)。\n断言与运行时检查：`__debug_assert`（仅 DEBUG 模式生效）和 `__assert`（始终生效），失败时调用 `panic()`。\n系统调用级追踪或 strace 类能力：桩实现。`xv6-user/strace.c` 存在但仅为用户态测试程序，无内核级系统调用追踪机制。\n\n##### 关键实现、证据与细粒度锚点\n\n- 调试宏体系：`include/utils/debug.h:1-58` 定义 `__INFO`/`__WARN`/`__ERROR` 颜色标签，`__debug_info`/`__debug_warn`/`__debug_error` 三级输出，`__debug_assert` 条件断言。\n- panic：`kernel/printf.c` 中的 `panic()` 输出红色 `[ERROR]` 消息，调用 `backtrace()` 打印栈回溯，`intr_off()` 关中断后 `for(;;);` 停机。\n- 栈

---


# 第02章 启动架构与 Trap系统调用

Now I have all the evidence needed. Let me compile the final JSON answer.

```json
{
  "schema_version": "v1",
  "stage_id": "02_boot_trap",
  "stage_title": "启动/架构与 Trap/系统调用",
  "terminology_profile": "stallings_en_zh",
  "answers": [
    {
      "question_id": "Q02_001",
      "question_type": "short_answer",
      "stem": "启动入口在哪里？",
      "value": "启动入口因平台而异：K210 平台使用 `kernel/entry_k210.S:2` 的 `_start` 标签（链接脚本 `linker/k210.ld:2` 指定 `ENTRY(_start)`）；QEMU 平台使用 `kernel/entry_qemu.S:2` 的 `_entry` 标签（链接脚本 `linker/qemu.ld:2` 指定 `ENTRY(_entry)`）。另有一个通用 `kernel/entry.S:2` 也定义了 `_entry`。",
      "evidence": [
        {
          "path": "kernel/entry_k210.S",
          "symbol_kind": "label",
          "symbol_name": "_start",
          "excerpt": ".section .text.entry\n\t.globl _start\n_start:\n\tadd t0, a0, 1\n\tslli t0, t0, 14\n\tla sp, boot_stack\n\tadd sp, sp, t0\n\tcall main"
        },
        {
          "path": "kernel/entry_qemu.S",
          "symbol_kind": "label",
          "symbol_name": "_entry",
          "excerpt": ".section .text\n\t.globl _entry\n_entry:\n\tadd t0, a0, 1\n\tslli t0, t0, 14\n\tla sp, boot_stack\n\tadd sp, sp, t0\n\tcall main"
        },
        {
          "path": "linker/k210.ld",
          "symbol_kind": "linker_directive",
          "symbol_name": "ENTRY(_start)",
          "excerpt": "OUTPUT_ARCH(riscv)\nENTRY(_start)\n\nBASE_ADDRESS = 0x80020000;"
        },
        {
          "path": "linker/qemu.ld",
          "symbol_kind": "linker_directive",
          "symbol_name": "ENTRY(_entry)",
          "excerpt": "OUTPUT_ARCH(riscv)\nENTRY(_entry)\n\nBASE_ADDRESS = 0x80200000;"
        }
      ]
    },
    {
      "question_id": "Q02_002",
      "question_type": "single_choice",
      "stem": "启动链更接近哪种交接方式？",
      "value": "固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）",
      "evidence": [
        {
          "path": "Makefile",
          "symbol_kind": "build_config",
          "symbol_name": "SBI build and QEMUOPTS",
          "excerpt": "QEMUOPTS += -bios $(SBI)  // SBI 固件作为 BIOS 加载；K210 平台使用 sbi/sbi-k210，QEMU 平台使用 sbi/sbi-qemu。SBI 由 sbi/psicasbi Rust 项目编译。"
        },
        {
          "path": "kernel/entry_k210.S",
          "symbol_kind": "label",
          "symbol_name": "_start",
          "excerpt": "入口汇编从 a0 寄存器获取 hartid，设置栈指针后直接 call main——这是典型的 SBI 固件交接方式（SBI 在 M 态完成初始化后跳转到 S 态内核入口）。"
        }
      ]
    },
    {
      "question_id": "Q02_003",
      "question_type": "tri_state_impl",
      "stem": "是否能在代码中证实发生了 CPU 特权级/模式切换？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/trap/trampoline.S",
          "symbol_kind": "instruction",
          "symbol_name": "sret",
          "excerpt": "userret 末尾执行 sret 指令从 S 态返回 U 态：\n# return to user mode and user pc.\n# usertrapret() set up sstatus and sepc.\nsret"
        },
        {
          "path": "kernel/trap/trap.c",
          "symbol_kind": "function",
          "symbol_name": "usertrapret",
          "excerpt": "// set S Previous Privilege mode to User.\nunsigned long x = r_sstatus();\nx &= ~SSTATUS_SPP; // clear SPP to 0 for user mode\nx |= SSTATUS_SPIE; // enable interrupts in user mode\nw_sstatus(x);"
        },
        {
          "path": "include/hal/riscv.h",
          "symbol_kind": "macro",
          "symbol_name": "SSTATUS_SPP",
          "excerpt": "#define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User"
        }
      ]
    },
    {
      "question_id": "Q02_004",
      "question_type": "short_answer",
      "stem": "模式切换涉及的关键寄存器/位是什么？",
      "value": "RISC-V sstatus 寄存器的 SPP 位（bit 8）控制 S 态返回时的特权级：SPP=0 返回 U 态，SPP=1 返回 S 态。此外 SSTATUS_SPIE（bit 5）控制返回后中断使能，SSTATUS_SIE（bit 1）控制当前中断使能。SATP 寄存器用于页表切换（Sv39 模式）。stvec 寄存器指向 trap 向量。sepc 保存异常返回地址。",
      "evidence": [
        {
          "path": "include/hal/riscv.h",
          "symbol_kind": "macro",
          "symbol_name": "SSTATUS_SPP",
          "excerpt": "#define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User\n#define SSTATUS_SPIE (1L << 5) // Supervisor Previous Interrupt Enable\n#define SSTATUS_SIE (1L << 1)  // Supervisor Interrupt Enable"
        },
        {
          "path": "include/hal/riscv.h",
          "symbol_kind": "macro",
          "symbol_name": "SATP_SV39",
          "excerpt": "#define SATP_SV39 (8L << 60)"
        },
        {
          "path": "kernel/trap/trap.c",
          "symbol_kind": "function",
          "symbol_name": "usertrapret",
          "excerpt": "x &= ~SSTATUS_SPP; // clear SPP to 0 for user mode\nx |= SSTATUS_SPIE; // enable interrupts in user mode\nw_sstatus(x);\nw_sepc(p->trapframe->epc);"
        }
      ]
    },
    {
      "question_id": "Q02_005",
      "question_type": "tri_state_impl",
      "stem": "是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/mm/vm.c",
          "symbol_kind": "function",
          "symbol_name": "kvminit",
          "excerpt": "kernel_pagetable = (pagetable_t) allocpage();\nmemset(kernel_pagetable, 0, PGSIZE);\n// uart registers\nkvmmap(UART_V, UART, PGSIZE, PTE_R | PTE_W);\n// ... 映射 CLINT, PLIC, 内核代码/数据, trampoline 等"
        },
        {
          "path": "kernel/mm/vm.c",
          "symbol_kind": "function",
          "symbol_name": "kvminithart",
          "excerpt": "uint64 stap = SATP_SV39 | (((uint64)kernel_pagetable) >> 12);\nw_satp(stap);\nasm volatile(\"sfence.vma\");"
        },
        {
          "path": "kernel/main.c",
          "symbol_kind": "function",
          "symbol_name": "main",
          "excerpt": "kvminit();       // create kernel page table\nkvminithart();   // turn on paging"
        }
      ]
    },
    {
      "question_id": "Q02_006",
      "question_type": "short_answer",
      "stem": "从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？",
      "value": "跳转链（K210 平台）：1) SBI 固件 (sbi/psicasbi, M 态) → 2) `_start` (kernel/entry_k210.S:2, S 态) → 3) `main()` (kernel/main.c:34) → 4) `kvminit()` + `kvminithart()` (kernel/mm/vm.c) → 5) `trapinithart()` (kernel/trap/trap.c:68) → 6) `userinit()` (kernel/sched/proc.c:1028) → 7) `scheduler()` (kernel/sched/proc.c:673)。QEMU 平台入口为 `_entry` (kernel/entry_qemu.S:2)。",
      "evidence": [
        {
          "path": "kernel/entry_k210.S",
          "symbol_kind": "label",
          "symbol_name": "_start",
          "excerpt": "_start:\n\tadd t0, a0, 1\n\tslli t0, t0, 14\n\tla sp, boot_stack\n\tadd sp, sp, t0\n\tcall main"
        },
        {
          "path": "kernel/main.c",
          "symbol_kind": "function",
          "symbol_name": "main",
          "excerpt": "void main(unsigned long hartid, unsigned long dtb_pa) {\n\tinithartid(hartid);\n\tif (hartid == 0) {\n\t\tcpuinit();\n\t\tfloatinithart();\n\t\tconsoleinit();\n\t\tprintfinit();\n\t\tkpminit();\n\t\tkvminit();\n\t\tkvminithart();\n\t\tkmallocinit();\n\t\ttrapinithart();\n\t\tprocinit();\n\t\tplicinit();\n\t\tplicinithart();\n\t\tdisk_init();\n\t\tbinit();\n\t\tuserinit();\n\t\t// ...\n\t}\n\tscheduler();\n}"
        },
        {
          "path": "Makefile",
          "symbol_kind": "build_config",
          "symbol_name": "SBI",
          "excerpt": "ifeq ($(platform), k210)\n\tSBI := ./sbi/sbi-k210\nelse\n\tSBI := ./sbi/sbi-qemu\nendif"
        }
      ]
    },
    {
      "question_id": "Q02_007",
      "question_type": "fill_in",
      "stem": "早期初始化各项状态",
      "value": "BSS 清零 (BSS Clearing): implemented [linker/k210.ld:44-48, sbss_clear/ebss_clear 符号标记 BSS 段边界，由 SBI/引导加载器在加载时清零]\n早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:38, consputc() 通过 sbi_console_putchar() 输出；kernel/main.c:44 consoleinit() 初始化]\n设备树解析 (Device Tree Blob parsing, DTB): not_found [main() 接收 dtb_pa 参数但未使用；搜索 DTB/FDT 解析代码无命中]\n页表初始化时机 (Page Table Init): implemented [kernel/main.c:47-48, kvminit() 在 kvminithart()（MMU 启用）之前调用，即页表初始化在 MMU 启用前完成]",
      "evidence": [
        {
          "path": "linker/k210.ld",
          "symbol_kind": "linker_symbol",
          "symbol_name": "sbss_clear/ebss_clear",
          "excerpt": ".bss : {\n\t*(.bss.stack)\n\tsbss_clear = .;\n\t*(.sbss .bss .bss.*)\n\tebss_clear = .;\n}"
        },
        {
          "path": "kernel/console.c",
          "symbol_kind": "function",
          "symbol_name": "consputc",
          "excerpt": "void consputc(int c) {\n\tif(c == BACKSPACE){\n\t\tsbi_console_putchar('\\b');\n\t\tsbi_console_putchar(' ');\n\t\tsbi_console_putchar('\\b');\n\t} else {\n\t\tsbi_console_putchar(c);\n\t}\n}"
        },
        {
          "path": "kernel/main.c",
          "symbol_kind": "function",
          "symbol_name": "main",
          "excerpt": "void main(unsigned long hartid, unsigned long dtb_pa)  // dtb_pa 参数未被使用"
        },
        {
          "path": "kernel/main.c",
          "symbol_kind": "function_call",
          "symbol_name": "kvminit/kvminithart",
          "excerpt": "kvminit();       // create kernel page table\nkvminithart();   // turn on paging"
        }
      ]
    },
    {
      "question_id": "Q02_008",
      "question_type": "tri_state_impl",
      "stem": "是否初始化/启用了 FPU？",
      "value": "implemented",
      "evidence": [
        {
          "path": "include/hal/riscv.h",
          "symbol_kind": "function",
          "symbol_name": "floatinithart",
          "excerpt": "static inline void floatinithart()\n{\n\tw_sstatus_fs(SSTATUS_FS_INIT);\n\tw_frm(FRM_RNE);\n\tw_sstatus_fs(SSTATUS_FS_CLEAN);\n}"
        },
        {
          "path": "kernel/main.c",
          "symbol_kind": "function_call",
          "symbol_name": "floatinithart",
          "excerpt": "floatinithart();  // 在 hart 0 和 hart 1 初始化路径中均调用"
        },
        {
          "path": "include/hal/riscv.h",
          "symbol_kind": "macro",
          "symbol_name": "SSTATUS_FS_INIT",
          "excerpt": "#define SSTATUS_FS_INIT\t\t(1L << 13)\n#define SSTATUS_FS_CLEAN\t(2L << 13)\n#define SSTATUS_FS_DIRTY\t(3L << 13)\n#define SSTATUS_FS_BITS\t\t(3L << 13)"
        }
      ]
    },
    {
      "question_id": "Q02_009",
      "question_type": "tri_state_impl",
      "stem": "是否设置 trap/中断向量并能指出设置点？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/trap/trap.c",
          "symbol_kind": "function",
          "symbol_name": "trapinithart",
          "excerpt": "void trapinithart(void)\n{\n\tw_stvec((uint64)kernelvec);\n\tw_sstatus(r_sstatus() | SSTATUS_SIE);\n\tw_sie(r_sie() | SIE_SEIE | SIE_SSIE | SIE_STIE);\n\tset_next_timeout();\n}"
        },
        {
          "path": "kernel/trap/trap.c",
          "symbol_kind": "function",
          "symbol_name": "usertrap",
          "excerpt": "w_stvec((uint64)kernelvec);  // 进入内核后切换到内核 trap 向量"
        },
        {
          "path": "kernel/trap/trap.c",
          "symbol_kind": "function",
          "symbol_name": "usertrapret",
          "excerpt": "w_stvec(TRAMPOLINE + (uservec - trampoline));  // 返回用户态前切换到用户 trap 向量"
        }
      ]
    },
    {
      "question_id": "Q02_010",
      "question_type": "short_answer",
      "stem": "构建系统如何选择目标平台/架构与入口文件？",
      "value": "通过 Makefile 顶部的 `platform` 变量选择：`platform := k210`（默认）或 `platform := qemu`。平台选择影响：(1) CFLAGS 添加 `-D QEMU` 宏（仅 QEMU 平台）；(2) SBI 固件路径（k210→sbi/sbi-k210，qemu→sbi/sbi-qemu）；(3) 源文件列表（K210 包含 hal/spi.c, hal/sdcard.c 等，QEMU 包含 hal/virtio_disk.c）；(4) 链接脚本统一使用 linker/linker64.ld（但 k210.ld 和 qemu.ld 也存在，分别指定 ENTRY(_start) 和 ENTRY(_entry)）。架构固定为 riscv64（-march=rv64imafdc）。",
      "evidence": [
        {
          "path": "Makefile",
          "symbol_kind": "variable",
          "symbol_name": "platform",
          "excerpt": "platform\t:= k210\n# platform\t:= qemu\n# mode \t\t:= debug\nmode\t\t:= release"
        },
        {
          "path": "Makefile",
          "symbol_kind": "conditional",
          "symbol_name": "ifeq ($(platform), qemu)",
          "excerpt": "ifeq ($(platform), qemu)\nCFLAGS += -D QEMU\nendif"
        },
        {
          "path": "Makefile",
          "symbol_kind": "conditional",
          "symbol_name": "SRC platform conditional",
          "excerpt": "ifeq ($(platform), k210) \nSRC += $K/hal/spi.c $K/hal/gpiohs.c $K/hal/fpioa.c $K/hal/sdcard.c $K/hal/dmac.c $K/hal/sysctl.c $K/utils/utils.c\nelse \nSRC += $K/hal/virtio_disk.c\nendif"
        }
      ]
    },
    {
      "question_id": "Q02_011",
      "question_type": "tri_state_impl",
      "stem": "对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链？",
      "value": "implemented",
      "evidence": [
        {
          "path": "Makefile",
          "symbol_kind": "build_target",
          "symbol_name": "$(SBI)",
          "excerpt": "$(SBI): \n\tcd ./sbi/psicasbi && cargo build --no-default-features --features=$(platform)\n\tcp ./sbi/psicasbi/target/riscv64imac-unknown-none-elf/$(mode)/psicasbi $@"
        },
        {
          "path": "Makefile",
          "symbol_kind": "qemu_option",
          "symbol_name": "QEMUOPTS -bios",
          "excerpt": "QEMUOPTS += -bios $(SBI)"
        },
        {
          "path": "include/sbi.h",
          "symbol_kind": "macro",
          "symbol_name": "LEGACY_SBI_CALL",
          "excerpt": "#define LEGACY_SBI_CALL(eid, arg0) ({ \\\n\tregister uintptr_t a0 asm (\"a0\") = (uintptr_t)(arg0); \\\n\tregister uintptr_t a7 asm (\"a7\") = (uintptr_t)(eid); \\\n\tasm volatile (\"ecall\" ...); \\\n\ta0; \\\n})"
        },
        {
          "path": "kernel/main.c",
          "symbol_kind": "function_call",
          "symbol_name": "sbi_send_ipi",
          "excerpt": "sbi_send_ipi(mask, 0);  // 使用 SBI IPI 唤醒其他 hart"
        }
      ]
    },
    {
      "question_id": "Q02_012",
      "question_type": "tri_state_impl",
      "stem": "MMU 启用前后是否存在串口/UART 地址切换逻辑？",
      "value": "implemented",
      "evidence": [
        {
          "path": "include/memlayout.h",
          "symbol_kind": "macro",
          "symbol_name": "UART / UART_V",
          "excerpt": "#ifdef QEMU\n#define UART                    0x10000000L\n#else\n#define UART                    0x38000000L\n#endif\n#define UART_V                  (UART + VIRT_OFFSET)  // VIRT_OFFSET = 0x3F00000000L"
        },
        {
          "path": "kernel/mm/vm.c",
          "symbol_kind": "function_call",
          "symbol_name": "kvmmap(UART_V, UART, ...)",
          "excerpt": "// uart registers\nkvmmap(UART_V, UART, PGSIZE, PTE_R | PTE_W);"
        },
        {
          "path": "include/memlayout.h",
          "symbol_kind": "macro",
          "symbol_name": "VIRT_OFFSET",
          "excerpt": "#define VIRT_OFFSET             0x3F00000000L"
        }
      ]
    },
    {
      "question_id": "Q02_013",
      "question_type": "tri_state_impl",
      "stem": "是否存在从内核返回用户态的路径并设置 stvec？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/trap/trap.c",
          "symbol_kind": "function",
          "symbol_name": "usertrapret",
          "excerpt": "void usertrapret(void) {\n\tstruct proc *p = myproc();\n\tintr_off();\n\tw_stvec(TRAMPOLINE + (uservec - trampoline));\n\t// ...\n\tuint64 fn = TRAMPOLINE + (userret - trampoline);\n\t((void (*)(uint64, uint64))fn)((uint64)(p->trapframe), satp);\n}"
        },
        {
          "path": "kernel/trap/trampoline.S",
          "symbol_kind": "label",
          "symbol_name": "userret",
          "excerpt": "userret:\n\t# ... restore all registers from TRAPFRAME\n\tcsrrw a0, sscratch, a0\n\tsret"
        },
        {
          "path": "kernel/trap/trampoline.S",
          "symbol_kind": "label",
          "symbol_name": "uservec",
          "excerpt": "uservec:\n\tcsrrw a0, sscratch, a0\n\t# save user registers in TRAPFRAME\n\t# ...\n\tld t0, 16(a0)  # load usertrap()\n\tjr t0"
        }
      ]
    },
    {
      "question_id": "Q02_014",
      "question_type": "short_answer",
      "stem": "是否支持多平台启动？",
      "value": "未发现 StarFive VisionFive2 / LoongArch 等多板型支持。仓库仅支持两种平台：K210 真实硬件（`platform := k210`）和 QEMU `-machine virt`（`platform := qemu`）。搜索 visionfive、jh7110、loongarch 均无命中。",
      "evidence": [
        {
          "path": "Makefile",
          "symbol_kind": "variable",
          "symbol_name": "platform",
          "excerpt": "platform\t:= k210\n# platform\t:= qemu"
        },
        {
          "path": "Makefile",
          "symbol_kind": "search",
          "symbol_name": "grep_visionfive_jh7110_loongarch",
          "excerpt": "于全仓搜索 visionfive、jh7110、loongarch 标识符，0 命中。"
        }
      ]
    },
    {
      "question_id": "Q02_015",
      "question_type": "short_answer",
      "stem": "trap/异常向量入口在哪里？",
      "value": "内核态 trap 入口为 `kernelvec` (kernel/trap/kernelvec.S:7)，用户态 trap 入口为 `uservec` (kernel/trap/trampoline.S:14)。`kernelvec` 保存全部 32 个通用寄存器后调用 `kerneltrap()` (kernel/trap/trap.c:193)；`uservec` 通过 sscratch 交换 a0 后保存寄存器到 trapframe，然后跳转到 `usertrap()` (kernel/trap/trap.c:76)。",
      "evidence": [
        {
          "path": "kernel/trap/kernelvec.S",
          "symbol_kind": "label",
          "symbol_name": "kernelvec",
          "excerpt": "kernelvec:\n\taddi sp, sp, -256\n\t// save the registers.\n\tsd ra, 0(sp)\n\t// ... 保存全部 32 个寄存器\n\tcall kerneltrap"
        },
        {
          "path": "kernel/trap/trampoline.S",
          "symbol_kind": "label",
          "symbol_name": "uservec",
          "excerpt": "uservec:\n\tcsrrw a0, sscratch, a0\n\tsd ra, 40(a0)\n\t// ... 保存用户寄存器到 trapframe\n\tld t0, 16(a0)  # load usertrap()\n\tjr t0"
        },
        {
          "path": "kernel/trap/trap.c",
          "symbol_kind": "function",
          "symbol_name": "trapinithart",
          "excerpt": "w_stvec((uint64)kernelvec);  // 初始设置 stvec 指向 kernelvec"
        }
      ]
    },
    {
      "question_id": "Q02_016",
      "question_type": "single_choice",
      "stem": "trap 上下文更可能存放在哪里？",
      "value": "用户地址空间预留页（trampoline/trap_context page）",
      "evidence": [
        {
          "path": "include/trap.h",
          "symbol_kind": "struct",
          "symbol_name": "trapframe",
          "excerpt": "// per-process data for the trap handling code in trampoline.S.\n// sits in a page by itself just under the trampoline page in the\n// user page table. not specially mapped in the kernel page table.\n// the sscratch register points here."
        },
        {
          "path": "include/memlayout.h",
          "symbol_kind": "macro",
          "symbol_name": "TRAPFRAME",
          "excerpt": "#define TRAPFRAME               (VKSTACK + 2 * PGSIZE)"
        },
        {
          "path": "kernel/trap/trampoline.S",
          "symbol_kind": "instruction",
          "symbol_name": "csrrw a0, sscratch, a0",
          "excerpt": "csrrw a0, sscratch, a0  // sscratch 指向 p->trapframe，位于用户地址空间"
        }
      ]
    },
    {
      "question_id": "Q02_017",
      "question_type": "short_answer",
      "stem": "TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？",
      "value": "定义在 `include/trap.h:18-76` 的 `struct trapframe`。包含 32 个通用寄存器（ra, sp, gp, tp, t0-t6, s0-s11, a0-a7）各 8 字节 = 256 字节，5 个内核元数据字段（kernel_satp, kernel_sp, kernel_trap, epc, kernel_hartid）各 8 字节 = 40 字节，32 个浮点寄存器（ft0-ft11, fs0-fs11, fa0-fa7）各 8 字节 = 256 字节，1 个 fcsr 8 字节。总计 70 个 uint64 字段 = 560 字节。",
      "evidence": [
        {
          "path": "include/trap.h",
          "symbol_kind": "struct",
          "symbol_name": "trapframe",
          "excerpt": "struct trapframe {\n\t/*   0 */ uint64 kernel_satp;\n\t/*   8 */ uint64 kernel_sp;\n\t/*  16 */ uint64 kernel_trap;\n\t/*  24 */ uint64 epc;\n\t/*  32 */ uint64 kernel_hartid;\n\t/*  40 */ uint64 ra;\n\t/*  48 */ uint64 sp;\n\t/*  56 */ uint64 gp;\n\t/*  64 */ uint64 tp;\n\t/*  72 */ uint64 t0;\n\t/*  80 */ uint64 t1;\n\t/*  88 */ uint64 t2;\n\t/*  96 */ uint64 s0;\n\t/* 104 */ uint64 s1;\n\t/* 112 */ uint64 a0;\n\t/* 120 */ uint64 a1;\n\t/* 128 */ uint64 a2;\n\t/* 136 */ uint64 a3;\n\t/* 144 */ uint64 a4;\n\t/* 152 */ uint64 a5;\n\t/* 160 */ uint64 a6;\n\t/* 168 */ uint64 a7;\n\t/* 176 */ uint64 s2;\n\t/* 184 */ uint64 s3;\n\t/* 192 */ uint64 s4;\n\t/* 200 */ uint64 s5;\n\t/* 208 */ uint64 s6;\n\t/* 216 */ uint64 s7;\n\t/* 224 */ uint64 s8;\n\t/* 232 */ uint64 s9;\n\t/* 240 */ uint64 s10;\n\t/* 248 */ uint64 s11;\n\t/* 256 */ uint64 t3;\n\t/* 264 */ uint64 t4;\n\t/* 272 */ uint64 t5;\n\t/* 280 */ uint64 t6;\n\t/* 288 */ uint64 ft0;\n\t/* ... 32 个浮点寄存器 ... */\n\t/* 536 */ uint64 ft11;\n\t/* 544 */ uint64 fcsr;\n};"
        }
      ]
    },
    {
      "question_id": "Q02_018",
      "question_type": "tri_state_impl",
      "stem": "是否存在系统调用分发表？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/syscall/syscall.c",
          "symbol_kind": "array",
          "symbol_name": "syscalls",
          "excerpt": "static uint64 (*syscalls[])(void) = {\n\t[SYS_fork]\t\t\tsys_fork,\n\t[SYS_exit]\t\t\tsys_exit,\n\t[SYS_wait]\t\t\tsys_wait,\n\t[SYS_pipe2]\t\t\tsys_pipe,\n\t[SYS_read]\t\t\tsys_read,\n\t// ... 共 65 个表项\n};"
        },
        {
          "path": "kernel/syscall/syscall.c",
          "symbol_kind": "function",
          "symbol_name": "syscall",
          "excerpt": "if (num < NELEM(syscalls) && syscalls[num]) {\n\tp->trapframe->a0 = syscalls[num]();\n} else {\n\tp->trapframe->a0 = -1;\n}"
        }
      ]
    },
    {
      "question_id": "Q02_019",
      "question_type": "tri_state_impl",
      "stem": "系统调用号是否做边界检查？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/syscall/syscall.c",
          "symbol_kind": "function",
          "symbol_name": "syscall",
          "excerpt": "num = p->trapframe->a7;\nif (SYS_rt_sigreturn == num) {\n\tsigreturn();\n}\nelse if (num < NELEM(syscalls) && syscalls[num]) {\n\tp->trapframe->a0 = syscalls[num]();\n} else {\n\tp->trapframe->a0 = -1;\n}"
        },
        {
          "path": "include/types.h",
          "symbol_kind": "macro",
          "symbol_name": "NELEM",
          "excerpt": "#define NELEM(x) (sizeof(x)/sizeof((x)[0]))"
        }
      ]
    },
    {
      "question_id": "Q02_020",
      "question_type": "short_answer",
      "stem": "追踪 sys_write：用户指令 → trap → 分发 → 实现体",
      "value": "1) 用户态执行 `ecall`（通过 usys.pl 生成的 usys.S），a7=SYS_write(64)；2) 硬件 trap 到 S 态，stvec 指向 uservec (kernel/trap/trampoline.S:14)；3) uservec 保存寄存器到 trapframe，跳转到 usertrap() (kernel/trap/trap.c:76)；4) usertrap() 检测 scause==EXCP_ENV_CALL(8)，调用 syscall() (kernel/syscall/syscall.c:340)；5) syscall() 从 a7 取号 64，查表调用 sys_write (kernel/syscall/sysfile.c:117)；6) sys_write() 通过 argfd/argaddr/argint 提取参数，调用 filewrite() 执行实际写入。",
      "evidence": [
        {
          "path": "xv6-user/usys.pl",
          "symbol_kind": "script",
          "symbol_name": "usys.pl",
          "excerpt": "生成 ecall 包装：li a7, SYS_write; ecall; ret"
        },
        {
          "path": "kernel/trap/trap.c",
          "symbol_kind": "function",
          "symbol_name": "usertrap",
          "excerpt": "if (cause == EXCP_ENV_CALL) {\n\tp->trapframe->epc += 4;\n\tintr_on();\n\tsyscall();\n}"
        },
        {
          "path": "kernel/syscall/syscall.c",
          "symbol_kind": "function",
          "symbol_name": "syscall",
          "excerpt": "num = p->trapframe->a7;\n// ...\nelse if (num < NELEM(syscalls) && syscalls[num]) {\n\tp->trapframe->a0 = syscalls[num]();\n}"
        },
        {
          "path": "kernel/syscall/sysfile.c",
          "symbol_kind": "function",
          "symbol_name": "sys_write",
          "excerpt": "uint64 sys_write(void)\n{\n\tstruct file *f;\n\tint n;\n\tuint64 p;\n\tif (argfd(0, 0, &f) < 0)\n\t\treturn -EBADF;\n\targaddr(1, &p);

---


# 第03章 内存管理物理虚拟分配器

Now let me verify the `MAXVA` value:

From `include/hal/riscv.h:408`: `#define MAXVA (1L << (9 + 9 + 9 + 12 - 1))` = `1L << 38` = 256 GB (Sv39, but with one bit less to avoid sign extension). So virtual address space is 38 bits.

Physical memory: `KERNBASE = 0x80020000`, `PHYSTOP = 0x80600000`. So physical RAM = `0x80600000 - 0x80020000` = `0x5E0000` = 6,160,384 bytes ≈ 6 MB. But wait, the K210 has 8 MB RAM starting at 0x80000000. Let me recalculate: `PHYSTOP - KERNBASE = 0x80600000 - 0x80020000 = 0x5E0000 = 6029312 bytes ≈ 5.75 MB` usable (RustSBI takes 0x80000000-0x80020000 = 128KB). Actually the total physical RAM on K210 is 8 MB (0x80000000 to 0x80800000), but PHYSTOP is set to 0x80600000, so only 6 MB is used.

Now I have all the evidence. Let me compile the JSON.

```json
{
  "schema_version": "v1",
  "stage_id": "03_mem_mgmt",
  "stage_title": "内存管理（物理/虚拟/分配器）",
  "terminology_profile": "stallings_en_zh",
  "answers": [
    {
      "question_id": "Q03_001",
      "question_type": "single_choice",
      "stem": "该 OS 的内存管理实现语言/形态更接近哪类？",
      "value": "C/Makefile 风格内核（xv6 类）",
      "evidence": [
        {
          "path": "kernel/mm/pm.c",
          "symbol_kind": "file",
          "symbol_name": "pm.c",
          "excerpt": "物理页分配器使用 C 语言实现，包含 struct run 单链表、struct pm_allocator 等 xv6 风格数据结构，通过 Makefile 构建。"
        },
        {
          "path": "kernel/mm/vm.c",
          "symbol_kind": "file",
          "symbol_name": "vm.c",
          "excerpt": "页表操作（walk/mappages/unmappages）均为 C 函数，继承 xv6 命名与设计范式。"
        }
      ]
    },
    {
      "question_id": "Q03_002",
      "question_type": "tri_state_impl",
      "stem": "是否存在"物理页帧分配器 (Physical Frame Allocator)"的真实实现？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/mm/pm.c:31-38",
          "symbol_kind": "struct",
          "symbol_name": "pm_allocator",
          "excerpt": "struct pm_allocator { struct spinlock lock; struct run *freelist; uint64 npage; }; 两个全局实例: struct pm_allocator multiple; struct pm_allocator single; 构成双分配器架构。"
        },
        {
          "path": "kernel/mm/pm.c:179-296",
          "symbol_kind": "function",
          "symbol_name": "kpminit/allocpage_n/_allocpage",
          "excerpt": "kpminit() 初始化双分配器，__mul_freerange 填充多页分配器，__sin_freerange 填充单页分配器。allocpage_n() 从 multiple 分配 n 页，_allocpage() 从 single 分配 1 页（不足时从 multiple 借）。"
        }
      ]
    },
    {
      "question_id": "Q03_003",
      "question_type": "single_choice",
      "stem": "物理内存分配算法更接近哪种？",
      "value": "空闲链表 run list（xv6 风格）",
      "evidence": [
        {
          "path": "kernel/mm/pm.c:26-29",
          "symbol_kind": "struct",
          "symbol_name": "run",
          "excerpt": "struct run { struct run *next; uint64 npage; }; 典型的空闲链表节点，npage 记录连续页数。"
        },
        {
          "path": "kernel/mm/pm.c:54-85",
          "symbol_kind": "function",
          "symbol_name": "__mul_alloc_no_lock",
          "excerpt": "多页分配器使用 first-fit 算法遍历 freelist，找到 npage>=n 的块后从块尾部分配。"
        },
        {
          "path": "kernel/mm/pm.c:149-158",
          "symbol_kind": "function",
          "symbol_name": "__sin_alloc_no_lock",
          "excerpt": "单页分配器使用 LIFO 栈式 freelist（取链表头）。"
        }
      ]
    },
    {
      "question_id": "Q03_004",
      "question_type": "short_answer",
      "stem": "物理页帧分配器的核心数据结构是什么？",
      "value": "双分配器架构：struct pm_allocator（含 spinlock + struct run *freelist + npage 计数），其中 struct run 为单链表节点（next 指针 + npage 连续页数）。全局实例 multiple 用于多页连续分配（first-fit），single 用于单页快速分配（LIFO 栈）。",
      "evidence": [
        {
          "path": "kernel/mm/pm.c:26-38",
          "symbol_kind": "struct",
          "symbol_name": "run/pm_allocator",
          "excerpt": "struct run { struct run *next; uint64 npage; }; struct pm_allocator { struct spinlock lock; struct run *freelist; uint64 npage; }; struct pm_allocator multiple; struct pm_allocator single;"
        }
      ]
    },
    {
      "question_id": "Q03_005",
      "question_type": "short_answer",
      "stem": "物理分配器的并发控制锁粒度是什么？",
      "value": "全局大锁：每个 pm_allocator 实例（multiple/single）各自持有一个 spinlock，通过 __enter_mul_cs/__leave_mul_cs 和 __enter_sin_cs/__leave_sin_cs 宏在分配/释放全程持锁。锁粒度覆盖整个分配器实例，非 per-CPU。",
      "evidence": [
        {
          "path": "kernel/mm/pm.c:31-34",
          "symbol_kind": "field",
          "symbol_name": "pm_allocator.lock",
          "excerpt": "struct pm_allocator { struct spinlock lock; ... }; 每个分配器实例内嵌一把 spinlock。"
        },
        {
          "path": "kernel/mm/pm.c:43-52",
          "symbol_kind": "macro",
          "symbol_name": "__enter_mul_cs/__leave_mul_cs",
          "excerpt": "#define __enter_mul_cs acquire(&multiple.lock); #define __leave_mul_cs release(&multiple.lock); 以及对应的 single 版本。"
        },
        {
          "path": "kernel/mm/pm.c:200-216",
          "symbol_kind": "function",
          "symbol_name": "allocpage_n",
          "excerpt": "void *allocpage_n(uint64 n) { __enter_mul_cs; ret = __mul_alloc_no_lock(n); __leave_mul_cs; ... } 持锁范围覆盖整个分配操作。"
        }
      ]
    },
    {
      "question_id": "Q03_006",
      "question_type": "tri_state_impl",
      "stem": "是否存在"页表 (page table) 结构体 + walk/map/unmap"的真实实现？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/mm/vm.c:211-230",
          "symbol_kind": "function",
          "symbol_name": "walk",
          "excerpt": "pte_t *walk(pagetable_t pagetable, uint64 va, int alloc) — Sv39 三级页表遍历，按需分配中间页表页。"
        },
        {
          "path": "kernel/mm/vm.c:298-333",
          "symbol_kind": "function",
          "symbol_name": "mappages",
          "excerpt": "int mappages(pagetable_t pagetable, uint64 va, uint64 size, uint64 pa, int perm) — 建立 VA→PA 映射，逐页调用 walk 获取 PTE 并写入。"
        },
        {
          "path": "kernel/mm/vm.c:335-373",
          "symbol_kind": "function",
          "symbol_name": "unmappages",
          "excerpt": "void unmappages(pagetable_t pagetable, uint64 va, uint64 npages, int flag) — 解除映射，可选释放物理页（通过 pageput 引用计数）。"
        }
      ]
    },
    {
      "question_id": "Q03_007",
      "question_type": "short_answer",
      "stem": "页表操作 API（walk/map/unmap 或等价）对应的函数名/模块是什么？",
      "value": "核心入口均在 kernel/mm/vm.c：1) walk() [vm.c:211] — Sv39 三级页表遍历；2) mappages() [vm.c:298] — 建立 VA→PA 映射；3) unmappages() [vm.c:335] — 解除映射并可选释放物理页。",
      "evidence": [
        {
          "path": "kernel/mm/vm.c:211",
          "symbol_kind": "function",
          "symbol_name": "walk",
          "excerpt": "pte_t *walk(pagetable_t pagetable, uint64 va, int alloc) — 三级 for 循环遍历 PX(2)/PX(1)/PX(0)，alloc=1 时按需分配中间页表页。"
        },
        {
          "path": "kernel/mm/vm.c:298",
          "symbol_kind": "function",
          "symbol_name": "mappages",
          "excerpt": "int mappages(pagetable_t pagetable, uint64 va, uint64 size, uint64 pa, int perm) — 逐页调用 walk 获取 PTE，写入 PA2PTE(pa)|perm|PTE_V。"
        },
        {
          "path": "kernel/mm/vm.c:335",
          "symbol_kind": "function",
          "symbol_name": "unmappages",
          "excerpt": "void unmappages(pagetable_t pagetable, uint64 va, uint64 npages, int flag) — 逐页 walk 后 *pte=0，若 VM_FREE 且引用计数归零则 freepage。"
        }
      ]
    },
    {
      "question_id": "Q03_008",
      "question_type": "short_answer",
      "stem": "页表修改路径的并发控制是什么？",
      "value": "无显式每进程地址空间锁。页表修改依赖以下机制：(1) 物理页分配器自身的 spinlock（pm_allocator.lock）保护物理页分配/释放；(2) COW 引用计数表 page_ref_table 由 page_ref_lock（spinlock）保护；(3) 内核态缺页安全逃生机制（safememmove + kern_pgfault_escape）避免内核访问用户空间时的竞态。页表 walk/map/unmap 本身无锁，依赖单核或调用者已持锁的假设。",
      "evidence": [
        {
          "path": "kernel/mm/vm.c:28",
          "symbol_kind": "variable",
          "symbol_name": "page_ref_lock",
          "excerpt": "static struct spinlock page_ref_lock; — 保护 page_ref_table 的全局锁。"
        },
        {
          "path": "kernel/mm/vm.c:154-159",
          "symbol_kind": "function",
          "symbol_name": "pagereg",
          "excerpt": "void pagereg(uint64 pa, uint8 init) { acquire(&page_ref_lock); page_ref_table[__hash_page_idx(pa)] = init; release(&page_ref_lock); }"
        },
        {
          "path": "kernel/mm/vm.c:211-230",
          "symbol_kind": "function",
          "symbol_name": "walk",
          "excerpt": "walk() 函数体内无任何锁操作，仅做页表遍历和 allocpage() 调用（allocpage 内部有 spinlock）。"
        }
      ]
    },
    {
      "question_id": "Q03_009",
      "question_type": "single_choice",
      "stem": "内核与用户地址空间关系更接近哪种？",
      "value": "共享同一页表（内核映射常驻，高半核等）",
      "evidence": [
        {
          "path": "kernel/mm/vm.c:673-685",
          "symbol_kind": "function",
          "symbol_name": "kvmcreate",
          "excerpt": "pagetable_t kvmcreate() { pagetable = allocpage(); memmove(pagetable, kernel_pagetable, PGSIZE); return pagetable; } — 进程页表直接复制内核根页表，内核映射常驻。"
        },
        {
          "path": "doc/内核设计-页表映射.md",
          "symbol_kind": "doc",
          "symbol_name": "shared_pagetable_design",
          "excerpt": "文档明确说明：'将用户空间与内核空间合并在一个页表中...当从用户模式进入监管者模式时，就可以不用切换页表了'。"
        },
        {
          "path": "include/memlayout.h:126",
          "symbol_kind": "macro",
          "symbol_name": "MAXUVA",
          "excerpt": "#define MAXUVA RUSTSBI_BASE (0x80000000) — 用户空间上限为 0x80000000，以上为内核直接映射空间。"
        }
      ]
    },
    {
      "question_id": "Q03_010",
      "question_type": "tri_state_impl",
      "stem": "是否存在缺页异常 (Page Fault) 处理逻辑并与内存分配/映射联动？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/mm/vm.c:1039-1105",
          "symbol_kind": "function",
          "symbol_name": "handle_page_fault",
          "excerpt": "int handle_page_fault(int kind, uint64 badaddr) — 缺页总入口：通过 locateseg 查找段，按 seg->type 四路分发到 COW/懒分配/ELF加载/mmap 子处理器。"
        },
        {
          "path": "kernel/trap/trap.c:328-350",
          "symbol_kind": "function",
          "symbol_name": "handle_excp",
          "excerpt": "handle_excp 将 EXCP_LOAD_PAGE/EXCP_STORE_PAGE/EXCP_INST_PAGE 分别路由到 handle_page_fault(0/1/2, r_stval())。"
        }
      ]
    },
    {
      "question_id": "Q03_011",
      "question_type": "short_answer",
      "stem": "追踪一条缺页链路：trap/异常入口 → 缺页处理函数 → 分配页帧 → 建立映射。",
      "value": "1) usertrap() [kernel/trap/trap.c:74] 读取 scause，调用 handle_excp(scause)；2) handle_excp() [kernel/trap/trap.c:328] 按 scause 类型映射 kind (0=load/1=store/2=inst)，调用 handle_page_fault(kind, r_stval())；3) handle_page_fault() [kernel/mm/vm.c:1039] 通过 locateseg 查段，按 seg->type 分发；4) 以 HEAP/STACK 懒分配为例 → handle_page_fault_lazy() [kernel/mm/vm.c:1002] 调用 uvmalloc() [kernel/mm/vm.c:414]；5) uvmalloc() 调用 allocpage() [_allocpage, kernel/mm/pm.c:232] 获取物理页帧，再调用 mappages() [kernel/mm/vm.c:298] 建立 VA→PA 映射。",
      "evidence": [
        {
          "path": "kernel/trap/trap.c:74-145",
          "symbol_kind": "function",
          "symbol_name": "usertrap",
          "excerpt": "usertrap() 读取 r_scause()，调用 handle_excp(cause) 处理异常。"
        },
        {
          "path": "kernel/trap/trap.c:328-350",
          "symbol_kind": "function",
          "symbol_name": "handle_excp",
          "excerpt": "switch(scause) { case EXCP_STORE_PAGE: return handle_page_fault(1, r_stval()); case EXCP_LOAD_PAGE: return handle_page_fault(0, r_stval()); ... }"
        },
        {
          "path": "kernel/mm/vm.c:1039-1105",
          "symbol_kind": "function",
          "symbol_name": "handle_page_fault",
          "excerpt": "switch(seg->type) { case HEAP: case STACK: return handle_page_fault_lazy(badaddr, seg); ... }"
        },
        {
          "path": "kernel/mm/vm.c:1002-1016",
          "symbol_kind": "function",
          "symbol_name": "handle_page_fault_lazy",
          "excerpt": "调用 uvmalloc(p->pagetable, pa, pa+PGSIZE, s->flag) 分配物理页并建立映射。"
        },
        {
          "path": "kernel/mm/vm.c:414-452",
          "symbol_kind": "function",
          "symbol_name": "uvmalloc",
          "excerpt": "mem = allocpage(); ... mappages(pagetable, a, PGSIZE, (uint64)mem, perm|PTE_U);"
        }
      ]
    },
    {
      "question_id": "Q03_012",
      "question_type": "tri_state_impl",
      "stem": "是否实现写时复制 (Copy-on-Write, CoW)？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/mm/vm.c:556-615",
          "symbol_kind": "function",
          "symbol_name": "uvmcopy",
          "excerpt": "fork 时 uvmcopy() 检测父进程 PTE_W 位：若 cow=1 且 (*pte & PTE_W)，则 *pte = (*pte|PTE_COW) & ~PTE_W 取消写权限并标记 COW，子进程共享同一物理页。"
        },
        {
          "path": "kernel/mm/vm.c:975-999",
          "symbol_kind": "function",
          "symbol_name": "handle_store_page_fault_cow",
          "excerpt": "缺页时若 kind==1 且 PTE_COW 标记，monopolizepage() 检查引用计数：若唯一占用则恢复 PTE_W；否则分配新页、memmove 拷贝、更新 PTE。"
        },
        {
          "path": "kernel/mm/vm.c:22",
          "symbol_kind": "macro",
          "symbol_name": "PTE_COW",
          "excerpt": "#define PTE_COW PTE_RSW1 — 利用 RISC-V S 态保留位标记 COW 页。"
        }
      ]
    },
    {
      "question_id": "Q03_013",
      "question_type": "tri_state_impl",
      "stem": "是否实现惰性分配 (Lazy Allocation)？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/mm/vm.c:1002-1016",
          "symbol_kind": "function",
          "symbol_name": "handle_page_fault_lazy",
          "excerpt": "缺页时若段类型为 HEAP 或 STACK，调用 uvmalloc() 在 fault 中真正分配物理页并建立映射。"
        },
        {
          "path": "kernel/mm/usrmm.c:16-70",
          "symbol_kind": "function",
          "symbol_name": "newseg",
          "excerpt": "newseg() 仅创建段描述符（struct seg）插入链表，不分配物理页（uvmalloc 调用被注释掉），物理页推迟到缺页时分配。"
        },
        {
          "path": "doc/内核设计-页表映射.md",
          "symbol_kind": "doc",
          "symbol_name": "lazy_allocation_doc",
          "excerpt": "文档说明：'当用户进程请求扩展其堆空间时，内核只需要判断其需求的合理性...简单地改变该进程的堆空间记录即可，当用户真正访问其堆空间时...引发异常，这时才真正为其分配物理页。'"
        }
      ]
    },
    {
      "question_id": "Q03_014",
      "question_type": "tri_state_impl",
      "stem": "是否实现 swap（swap_in/swap_out 或等价页面置换）？",
      "value": "not_found",
      "evidence": [
        {
          "path": "kernel/mm/",
          "symbol_kind": "search",
          "symbol_name": "swap_grep",
          "excerpt": "在 kernel/mm/ 及整个源码树中搜索 swap_in/swap_out/swap_page/page_swap/SWAP，仅在 mmap.c 中发现被注释掉的 __page_file_swap() 函数（行 908-975，已整体注释），以及 doc/内核设计-内存映射.md 中提到'可以引入 swap 机制'作为未来方向。无实际 swap 实现。"
        },
        {
          "path": "include/resource.h:19",
          "symbol_kind": "field",
          "symbol_name": "ru_nswap",
          "excerpt": "struct rusage 中有 ru_nswap 字段，但仅为结构体定义，无任何代码读写该字段。"
        }
      ]
    },
    {
      "question_id": "Q03_015",
      "question_type": "tri_state_impl",
      "stem": "是否实现 mmap（文件映射/匿名映射）且处理标志位（MAP_FIXED/MAP_ANON/MAP_SHARED 等）？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/mm/mmap.c:710-771",
          "symbol_kind": "function",
          "symbol_name": "do_mmap",
          "excerpt": "uint64 do_mmap(uint64 start, uint64 len, int prot, int flags, struct file *f, int64 off) — 完整实现：支持 MAP_FIXED（调用 lookup_fixed_segment）、MAP_ANONYMOUS（调用 mmap_anonymous）、MAP_SHARED/MAP_PRIVATE（通过 flags 传递到 mmap_file）。"
        },
        {
          "path": "kernel/mm/mmap.c:773-817",
          "symbol_kind": "function",
          "symbol_name": "do_munmap",
          "excerpt": "int do_munmap(uint64 start, uint64 len) — 支持任意段分割与释放，调用 lookup_fixed_segment 处理段分裂。"
        },
        {
          "path": "kernel/mm/mmap.c:1126-1159",
          "symbol_kind": "function",
          "symbol_name": "handle_page_fault_mmap",
          "excerpt": "缺页时按匿名私有（直接 uvmalloc）、匿名共享（handle_anonymous_shared）、文件映射（handle_file_mmap）三分支处理。"
        }
      ]
    },
    {
      "question_id": "Q03_016",
      "question_type": "tri_state_impl",
      "stem": "是否存在 Page Cache（页缓存/文件页缓存）管理？",
      "value": "not_found",
      "evidence": [
        {
          "path": "include/utils/rbtree.h:34-87",
          "symbol_kind": "function",
          "symbol_name": "rb_search_page_cache/rb_insert_page_cache",
          "excerpt": "rbtree.h 中定义了 rb_search_page_cache 和 rb_insert_page_cache 辅助函数，操作 inode->i_rb_page_cache 红黑树。但这是 mmap 文件映射的页索引树（用于共享映射页查找），并非通用 Page Cache（不涉及文件数据缓存、预读、回写等）。"
        },
        {
          "path": "kernel/fs/",
          "symbol_kind": "search",
          "symbol_name": "page_cache_search",
          "excerpt": "在 fs/ 目录搜索 page_cache/pagecache 无命中。buffer cache (binit/brelse) 存在于 fs/buf.c，但那是块缓存而非页缓存。"
        }
      ]
    },
    {
      "question_id": "Q03_017",
      "question_type": "tri_state_impl",
      "stem": "是否存在脏页回写 (dirty page writeback) 机制？",
      "value": "not_found",
      "evidence": [
        {
          "path": "kernel/mm/mmap.c:819-873",
          "symbol_kind": "function",
          "symbol_name": "do_msync",
          "excerpt": "do_msync() 实现 msync 系统调用，支持 MS_ASYNC/MS_SYNC 标志，将 mmap 共享映射的脏页写回文件。但这是用户显式调用的同步操作，非后台自动回写。"
        },
        {
          "path": "kernel/",
          "symbol_kind": "search",
          "symbol_name": "writeback_search",
          "excerpt": "搜索 writeback/kswapd/cleaner/bdflush/background_write 等关键字，0 命中。无后台脏页回写线程或守护进程。"
        }
      ]
    },
    {
      "question_id": "Q03_018",
      "question_type": "tri_state_impl",
      "stem": "是否存在 TLB 射击 (TLB Shootdown / Remote TLB Flush)机制以支持多核页表一致性？",
      "value": "not_found",
      "evidence": [
        {
          "path": "kernel/",
          "symbol_kind": "search",
          "symbol_name": "tlb_shootdown_search",
          "excerpt": "搜索 shootdown/remote_flush/ipi.*tlb/smp_call.*tlb 等模式，0 命中。搜索 sfence_vma 调用点共 16 处，均为本地 sfence_vma（当前 hart），无跨核 IPI 触发远程 TLB 刷新。"
        },
        {
          "path": "include/hal/riscv.h:362-370",
          "symbol_kind": "function",
          "symbol_name": "sfence_vma",
          "excerpt": "static inline void sfence_vma() — 仅执行本地 sfence.vma（或 K210 上 .word 0x10400073 模拟），无 ASID 参数，无远程刷新逻辑。"
        },
        {
          "path": "include/param.h:5",
          "symbol_kind": "macro",
          "symbol_name": "NCPU",
          "excerpt": "#define NCPU 2 — 系统支持最多 2 个 hart，但未发现 TLB shootdown 机制。"
        }
      ]
    },
    {
      "question_id": "Q03_019",
      "question_type": "short_answer",
      "stem": "TLB 刷新指令/函数点是什么？",
      "value": "sfence_vma() [include/hal/riscv.h:362-370]：QEMU 下使用 sfence.vma 指令，K210 硬件下使用 .word 0x10400073（sfence.vma 机器码）加 fence.i。调用点分布在 vm.c（kvminithart/uvmcopy/uvmprotect/handle_store_page_fault_cow/handle_page_fault_lazy/handle_page_fault_loadelf）、mmap.c（do_mmap/do_munmap/handle_anonymous_shared/handle_file_mmap/handle_page_fault_mmap）、proc.c（fork/exec 路径）、exec.c。均为本地 hart TLB 刷新，无远程 shootdown。",
      "evidence": [
        {
          "path": "include/hal/riscv.h:362-370",
          "symbol_kind": "function",
          "symbol_name": "sfence_vma",
          "excerpt": "static inline void sfence_vma() { #ifdef QEMU asm volatile(\"sfence.vma\"); #else asm volatile(\".word 0x10400073\"); asm volatile(\"fence.i\"); #endif }"
        },
        {
          "path": "kernel/mm/vm.c:124",
          "symbol_kind": "call",
          "symbol_name": "kvminithart_sfence",
          "excerpt": "kvminithart() 中 w_satp(stap); asm volatile(\"sfence.vma\"); — 开启分页后刷新 TLB。"
        }
      ]
    },
    {
      "question_id": "Q03_020",
      "question_type": "short_answer",
      "stem": "用户指针安全检查机制是什么？",
      "value": "两级检查：(1) 段合法性检查 — copyout2()/copyin2() [vm.c:786/836] 调用 partofseg() [usrmm.c:103] 验证 [start, end) 完全落在同一段内；(2) 安全内存拷贝 — safememmove() [vm.c:719] 在访问用户空间前设置安全状态，通过 PUM/SUM 位临时允许内核访问用户页，若触发缺页且处理失败则通过 kern_pgfault_escape() 跳转到存档点返回错误。",
      "evidence": [
        {
          "path": "kernel/mm/vm.c:786-802",
          "symbol_kind": "function",
          "symbol_name": "copyout2",
          "excerpt": "int copyout2(uint64 dstva, char *src, uint64 len) { struct seg *s = partofseg(p->segment, dstva, dstva+len); if (s==NULL) return -1; ... safememmove(...); }"
        },
        {
          "path": "kernel/mm/usrmm.c:103-115",
          "symbol_kind": "function",
          "symbol_name": "partofseg",
          "excerpt": "struct seg *partofseg(struct seg *head, uint64 start, uint64 end) — 验证地址区间完全落在同一段内。"
        },
        {
          "path": "kernel/mm/vm.c:719-754",
          "symbol_kind": "function",
          "symbol_name": "safememmove",
          "excerpt": "设置 save_point 存档点，permit_usr_mem() 临时关闭 PUM/开启 SUM，逐字节拷贝；若 kerneltrap 中缺页处理失败则 kern_pgfault_escape() 将 sepc 设为存档点。"
        }
      ]
    },
    {
      "question_id": "Q03_021",
      "question_type": "single_choice",
      "stem": "若实现了页面置换 (Page Replacement)，使用的算法最接近哪种？",
      "value": "未实现页面置换（无 swap）",
      "evidence": [
        {
          "path": "kernel/mm/mmap.c:908-975",
          "symbol_kind": "function",
          "symbol_name": "__page_file_swap",
          "excerpt": "__page_file_swap() 函数整体被 /* ... */ 注释掉，且调用点也被注释（行 1048: // pa = __page_file_swap(ip, off, badaddr);）。"
        },
        {
          "path": "kernel/mm/",
          "symbol_kind": "search",
          "symbol_name": "swap_search",
          "excerpt": "搜索 swap_in/swap_out/page_swap/SWAP 无活跃实现。doc/内核设计-内存映射.md 提到'可以引入 swap 机制'作为未来方向。"
        }
      ]
    },
    {
      "question_id": "Q03_022",
      "question_type": "tri_state_impl",
      "stem": "是否存在工作集模型 (Working Set Model, WSM) 或抖动检测/防止 (Thrashing Prevention) 机制？",
      "value": "not_found",
      "evidence": [
        {
          "path": "kernel/",
          "symbol_kind": "search",
          "symbol_name": "working_set_search",
          "excerpt": "搜索 working_set/thrash/resident_set/OOM/oom_kill/load_control/memory_pressure 等关键字。OOM 仅在 RustSBI bootloader 中出现（Rust allocator OOM handler），与内核内存管理无关。xv6-user/lazytests.c:77 有 oom 测试函数但仅为用户态测试。无工作集模型或抖动防止实现。"
        }
      ]
    },
    {
      "question_id": "Q03_023",
      "question_type": "fill_in",
      "stem": "物理内存总量 / 页大小 / 最大进程虚拟地址空间",
      "value": "物理内存总量：约 6 MB（PHYSTOP - KERNBASE = 0x80600000 - 0x80020000 = 0x5E0000 = 6029312 bytes）；页大小：4096 bytes（PGSIZE）；最大进程虚拟地址空间：38 bits（MAXVA = 1L << 38 = 256 GB，Sv39 减一位避免符号扩展）。",
      "evidence": [
        {
          "path": "include/memlayout.h:99-102",
          "symbol_kind": "macro",
          "symbol_name": "KERNBASE/PHYSTOP",
          "excerpt": "#define KERNBASE 0x80020000UL, #define PHYSTOP 0x80600000UL — 物理内存可用范围。"
        },
        {
          "path": "include/hal/riscv.h:378-379",
          "symbol_kind": "macro",
          "symbol_name": "PGSIZE/PGSHIFT",
          "excerpt": "#define PGSIZE 4096, #define PGSHIFT 12 — 页大小 4KB。"
        },
        {
          "path": "include/hal/riscv.h:408",
          "symbol_kind": "macro",
          "symbol_name": "MAXVA",
          "excerpt": "#define MAXVA (1L << (9 + 9 + 9 + 12 - 1)) = 1L << 38 — 38 位虚拟地址空间。"
        }
      ]
    },
    {
      "question_id": "Q03_024",
      "question_type": "single_choice",
      "stem": "内存保护机制 (Memory Protection) 的实现形式更接近哪种？",
      "value": "硬件页表 + 软件指针检查双重保护",
      "evidence": [
        {
          "path": "include/hal/riscv.h:382-387",
          "symbol_kind": "macro",
          "symbol_name": "PTE_R/W/X/U",
          "excerpt": "#define PTE_R (1L<<1), PTE_W (1L<<2), PTE_X (1L<<3), PTE_U (1L<<4) — 硬件页表权限位，MMU 在访问时检查。"
        },
        {
          "path": "kernel/mm/vm.c:786-802",
          "symbol_kind": "function",
          "symbol_name": "copyout2/copyin2",
          "excerpt": "copyout2/copyin2 在访问用户空间前调用 partofseg() 验证地址合法性，再通过 safememmove() 进行安全拷贝。"
        },
        {
          "path": "include/mm/vm.h:12-30",
          "symbol_kind": "function",
          "symbol_name": "permit_usr_mem/protect_usr_mem",
          "excerpt": "内核通过

---


# 第04章 进程线程调度与多核

Now I have all the evidence needed. Let me compile the final JSON answer.

```json
{
  "schema_version": "v1",
  "stage_id": "04_process_smp",
  "stage_title": "进程/线程/调度与多核",
  "terminology_profile": "stallings_en_zh",
  "answers": [
    {
      "question_id": "Q04_001",
      "question_type": "short_answer",
      "stem": "执行实体 (Execution Entity) 抽象是什么？",
      "value": "- 顶层类型名: Process (struct proc)\n- 结构体路径: include/sched/proc.h:51-104\n- 关键字段: Context=struct context context (include/sched/proc.h:93), State=enum procstate state (include/sched/proc.h:62), PID=int pid (include/sched/proc.h:54), TrapFrame=struct trapframe *trapframe (include/sched/proc.h:84)\n- 是否区分 PCB 与 TCB: 否（仅有统一 struct proc，无独立 TCB）",
      "evidence": [
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "struct",
          "symbol_name": "proc",
          "excerpt": "struct proc { int xstate; int pid; struct proc *hash_next; struct proc **hash_pprev; struct proc *sched_next; struct proc **sched_pprev; int timer; enum procstate state; void *chan; uint64 sleep_expire; ... struct context context; ... struct trapframe *trapframe; ... };"
        },
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "struct",
          "symbol_name": "context",
          "excerpt": "struct context { uint64 ra; uint64 sp; uint64 s0; uint64 s1; ... uint64 s11; };"
        },
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "enum",
          "symbol_name": "procstate",
          "excerpt": "enum procstate { RUNNABLE, RUNNING, SLEEPING, ZOMBIE, };"
        }
      ]
    },
    {
      "question_id": "Q04_002",
      "question_type": "short_answer",
      "stem": "任务/进程的生命周期状态机有哪些状态与流转点？",
      "value": "状态枚举 enum procstate (include/sched/proc.h:38-40): RUNNABLE (就绪), RUNNING (运行), SLEEPING (阻塞/睡眠), ZOMBIE (僵尸/已退出)。\n\n流转点:\n- RUNNABLE→RUNNING: scheduler() 中 __get_runnable_no_lock() 选中后置 state=RUNNING (kernel/sched/proc.c:684)\n- RUNNING→RUNNABLE: yield() 中 __remove 后 __insert_runnable(PRIORITY_NORMAL) (kernel/sched/proc.c:640-642)\n- RUNNING→SLEEPING: sleep() 中 __remove 后 __insert_sleep (kernel/sched/proc.c:596-597)\n- SLEEPING→RUNNABLE: wakeup()/__wakeup_no_lock() 中 __remove 后 __insert_runnable(PRIORITY_IRQ) (kernel/sched/proc.c:383-385)\n- RUNNING→ZOMBIE: exit() 中置 state=ZOMBIE (kernel/sched/proc.c:455)\n- ZOMBIE→释放: wait4() 中父进程回收后调用 freeproc() (kernel/sched/proc.c:521)",
      "evidence": [
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "enum",
          "symbol_name": "procstate",
          "excerpt": "enum procstate { RUNNABLE, RUNNING, SLEEPING, ZOMBIE, };"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "scheduler",
          "excerpt": "tmp->state = RUNNING; c->proc = tmp; (line 684)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "exit",
          "excerpt": "p->state = ZOMBIE; __remove(p); (line 455-456)"
        }
      ]
    },
    {
      "question_id": "Q04_003",
      "question_type": "tri_state_impl",
      "stem": "是否存在上下文切换 (Context Switch) 实现？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/sched/swtch.S",
          "symbol_kind": "function",
          "symbol_name": "swtch",
          "excerpt": "swtch: sd ra, 0(a0); sd sp, 8(a0); sd s0, 16(a0); ... sd s11, 104(a0); ld ra, 0(a1); ld sp, 8(a1); ... ld s11, 104(a1); ret"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "sched",
          "excerpt": "swtch(&p->context, &mycpu()->context); (line 740)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "scheduler",
          "excerpt": "swtch(&c->context, &tmp->context); (line 690)"
        }
      ]
    },
    {
      "question_id": "Q04_004",
      "question_type": "short_answer",
      "stem": "上下文切换保存/恢复了哪些寄存器集合？",
      "value": "swtch.S (kernel/sched/swtch.S:1-41) 保存/恢复 RISC-V callee-saved 寄存器全集: ra, sp, s0-s11。共 14 个寄存器，对应 struct context (include/sched/proc.h:19-35) 的字段布局。\n\n注意: 浮点寄存器 (f0-f31 + fcsr) 不在 swtch 中保存，而是在 sched() 中通过 floatstore/floatload 二进制机器码片段单独保存到 trapframe (kernel/sched/proc.c:731-748)。通用寄存器 (a0-a7, t0-t6, gp, tp) 由 kernelvec.S 的 trap 帧 (kernel/trap/kernelvec.S:1-86) 或 trampoline.S 的 uservec/userret (kernel/trap/trampoline.S:1-147) 保存。",
      "evidence": [
        {
          "path": "kernel/sched/swtch.S",
          "symbol_kind": "function",
          "symbol_name": "swtch",
          "excerpt": "sd ra, 0(a0); sd sp, 8(a0); sd s0, 16(a0); sd s1, 24(a0); sd s2, 32(a0); sd s3, 40(a0); sd s4, 48(a0); sd s5, 56(a0); sd s6, 64(a0); sd s7, 72(a0); sd s8, 80(a0); sd s9, 88(a0); sd s10, 96(a0); sd s11, 104(a0)"
        },
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "struct",
          "symbol_name": "context",
          "excerpt": "struct context { uint64 ra; uint64 sp; uint64 s0; uint64 s1; ... uint64 s11; };"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "sched",
          "excerpt": "((floattrap)floatstore)(p->trapframe); ... ((floattrap)floatload)(p->trapframe); (lines 732, 748)"
        }
      ]
    },
    {
      "question_id": "Q04_005",
      "question_type": "short_answer",
      "stem": "调度算法 (Scheduling Algorithm) 属于哪类？",
      "value": "- 算法名称: Priority (基于优先级的抢占式调度，三级优先级队列)\n- 代码证据（关键字段/函数）: __get_runnable_no_lock() (kernel/sched/proc.c:609-627) 按 PRIORITY_TIMEOUT(0) → PRIORITY_IRQ(1) → PRIORITY_NORMAL(2) 顺序遍历 proc_runnable[] 数组，选择第一个 RUNNABLE 进程。\n  - RR: 无独立 timeslice/slice 字段；timer 字段 (include/sched/proc.h:61) 用于定时器递减，超时后迁移到 PRIORITY_TIMEOUT 队列 (kernel/sched/proc.c:772-774)，但这不是经典 RR 时间片轮转。\n  - Stride: 未发现 stride 字段与比较逻辑。\n  - MLFQ: 三级优先级数组 proc_runnable[PRIORITY_NUMBER] (kernel/sched/proc.c:245) 构成多级队列，但无动态优先级升降/老化机制，非经典 MLFQ。\n  - Priority: 优先级通过 PRIORITY_TIMEOUT=0 / PRIORITY_IRQ=1 / PRIORITY_NORMAL=2 宏定义 (kernel/sched/proc.c:248-251)，__get_runnable_no_lock() 按优先级从高到低遍历选择。",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "__get_runnable_no_lock",
          "excerpt": "for (int i = 0; i < PRIORITY_NUMBER; i ++) { tmp = proc_runnable[i]; while (NULL != tmp) { if (RUNNABLE == tmp->state) { return (struct proc*)tmp; } tmp = tmp->sched_next; } }"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "macro",
          "symbol_name": "PRIORITY_TIMEOUT/PRIORITY_IRQ/PRIORITY_NORMAL",
          "excerpt": "#define PRIORITY_TIMEOUT 0\n#define PRIORITY_IRQ 1\n#define PRIORITY_NORMAL 2\n#define PRIORITY_NUMBER 3"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "var",
          "symbol_name": "proc_runnable",
          "excerpt": "struct proc *proc_runnable[PRIORITY_NUMBER];"
        }
      ]
    },
    {
      "question_id": "Q04_006",
      "question_type": "short_answer",
      "stem": "调度器 (Scheduler)核心入口/关键函数有哪些？",
      "value": "1. scheduler() (kernel/sched/proc.c:671-713): 每核 idle 循环，调用 __get_runnable_no_lock() 选进程，swtch() 切换上下文。\n2. sched() (kernel/sched/proc.c:714-752): 当前进程主动让出 CPU 的唯一路径，保存浮点上下文后 swtch 到 cpu->context。\n3. __get_runnable_no_lock() (kernel/sched/proc.c:609-627): 三级优先级选择算法，按 PRIORITY_TIMEOUT → PRIORITY_IRQ → PRIORITY_NORMAL 遍历。",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "scheduler",
          "excerpt": "void scheduler(void) { ... while (1) { ... tmp = __get_runnable_no_lock(); if (NULL != tmp) { tmp->state = RUNNING; c->proc = tmp; swtch(&c->context, &tmp->context); } ... } }"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "sched",
          "excerpt": "void sched(void) { ... swtch(&p->context, &mycpu()->context); ... }"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "__get_runnable_no_lock",
          "excerpt": "static struct proc *__get_runnable_no_lock(void) { for (int i = 0; i < PRIORITY_NUMBER; i ++) { ... } }"
        }
      ]
    },
    {
      "question_id": "Q04_007",
      "question_type": "tri_state_impl",
      "stem": "是否实现 fork/clone（创建新执行实体）？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "clone",
          "excerpt": "int clone(uint64 flag, uint64 stack) { struct proc *p = myproc(); struct proc *np; np = allocproc(); ... np->segment = copysegs(p->pagetable, p->segment, np->pagetable); ... copyfdtable(&p->fds, &np->fds); ... np->parent = p; ... return pid; }"
        },
        {
          "path": "kernel/syscall/sysproc.c",
          "symbol_kind": "function",
          "symbol_name": "sys_fork",
          "excerpt": "uint64 sys_fork(void) { return clone(0, NULL); }"
        },
        {
          "path": "kernel/syscall/sysproc.c",
          "symbol_kind": "function",
          "symbol_name": "sys_clone",
          "excerpt": "uint64 sys_clone(void) { ... return clone(flag, stack); }"
        }
      ]
    },
    {
      "question_id": "Q04_008",
      "question_type": "short_answer",
      "stem": "fork/clone 是否复制地址空间与文件表？",
      "value": "是。clone() (kernel/sched/proc.c:291-372) 中:\n- 地址空间复制: copysegs(p->pagetable, p->segment, np->pagetable) (line 308) 复制父进程的段列表和页表映射\n- 文件表复制: copyfdtable(&p->fds, &np->fds) (line 326) 复制文件描述符表\n- 当前目录复制: np->cwd = idup(p->cwd) (line 331)\n- ELF 文件引用: np->elf = p->elf ? idup(p->elf) : NULL (line 332)\n- 信号设置复制: sigaction_copy() 和 sig_set 逐元素复制 (lines 314-320)\n- trapframe 复制: *(np->trapframe) = *(p->trapframe) (line 338)",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "clone",
          "excerpt": "np->segment = copysegs(p->pagetable, p->segment, np->pagetable); ... copyfdtable(&p->fds, &np->fds); np->cwd = idup(p->cwd); np->elf = p->elf ? idup(p->elf) : NULL;"
        },
        {
          "path": "kernel/mm/usrmm.c",
          "symbol_kind": "function",
          "symbol_name": "copysegs",
          "excerpt": "copysegs copies segment list and page table mappings from parent to child"
        },
        {
          "path": "include/fs/file.h",
          "symbol_kind": "function",
          "symbol_name": "copyfdtable",
          "excerpt": "copyfdtable copies file descriptor table"
        }
      ]
    },
    {
      "question_id": "Q04_009",
      "question_type": "tri_state_impl",
      "stem": "是否实现 exec（装载 ELF/重建地址空间）？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/exec.c",
          "symbol_kind": "function",
          "symbol_name": "execve",
          "excerpt": "int execve(char *path, char **argv, char **envp) { ... Check ELF header ... Load program into memory ... p->pagetable = pagetable; p->segment = seghead; p->trapframe->epc = elf.entry; p->trapframe->sp = sp; ... w_satp(MAKE_SATP(p->pagetable)); sfence_vma(); ... }"
        }
      ]
    },
    {
      "question_id": "Q04_010",
      "question_type": "tri_state_impl",
      "stem": "是否实现 wait/waitpid（父子回收同步）？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "wait4",
          "excerpt": "int wait4(int pid, uint64 status, uint64 options) { ... while (1) { np = p->child; while (NULL != np) { if (ZOMBIE == np->state && (-1 == pid || pid == np->pid)) { ... freeproc(np); return child_pid; } } ... sleep(p, &p->lk); ... } }"
        },
        {
          "path": "kernel/syscall/sysproc.c",
          "symbol_kind": "function",
          "symbol_name": "sys_wait4",
          "excerpt": "uint64 sys_wait4(void) { ... return wait4(pid, status, options); }"
        }
      ]
    },
    {
      "question_id": "Q04_011",
      "question_type": "single_choice",
      "stem": "waitpid / wait4 的阻塞实现 (Blocking Implementation) 更接近哪种？",
      "value": "真正阻塞：移出就绪队列 + WaitQueue/条件变量唤醒 (Wait Queue or Condition Variable)",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "wait4",
          "excerpt": "sleep(p, &p->lk); (line 514) — 调用 sleep() 将当前进程从 proc_runnable 移除并插入 proc_sleep 链表，然后调用 sched() 切换走"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "sleep",
          "excerpt": "p->chan = chan; __remove(p); __insert_sleep(p); sched(); (lines 595-598)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "exit",
          "excerpt": "__wakeup_no_lock(p->parent); (line 458) — 子进程退出时唤醒父进程"
        }
      ]
    },
    {
      "question_id": "Q04_012",
      "question_type": "short_answer",
      "stem": "PID 分配器实现是什么？",
      "value": "单调自增 (monotonic increment)，只分配不回收。\n- 全局变量 __pid (kernel/sched/proc.c:38) 初始值在 procinit() 中设为 1 (kernel/sched/proc.c:1072)\n- allocproc() 中: p->pid = __pid ++ (kernel/sched/proc.c:233)\n- 无 PID 回收机制 (freeproc 中不回收 PID)，无 bitmap/空闲栈复用。",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "var",
          "symbol_name": "__pid",
          "excerpt": "static int __pid; (line 38)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "allocproc",
          "excerpt": "p->pid = __pid ++; (line 233)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "procinit",
          "excerpt": "__pid = 1; (line 1072)"
        }
      ]
    },
    {
      "question_id": "Q04_013",
      "question_type": "short_answer",
      "stem": "父子进程树如何存储？",
      "value": "使用 parent/child/sibling 指针构成树形结构:\n- struct proc *parent (include/sched/proc.h:76): 指向父进程\n- struct proc *child (include/sched/proc.h:75): 指向第一个子进程\n- struct proc *sibling_next (include/sched/proc.h:77): 指向下一个兄弟进程\n- struct proc **sibling_pprev (include/sched/proc.h:78): 指向前一个兄弟的 sibling_next 指针\n\nclone() 中建立父子关系 (kernel/sched/proc.c:343-350): 新进程插入父进程 child 链表头部。\nexit() 中孤儿重父 (kernel/sched/proc.c:420-436): 将退出进程的所有子进程转移给 __initproc。",
      "evidence": [
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "struct",
          "symbol_name": "proc",
          "excerpt": "struct proc *child; struct proc *parent; struct proc *sibling_next; struct proc **sibling_pprev; (lines 75-78)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "clone",
          "excerpt": "np->parent = p; np->sibling_pprev = &(p->child); np->sibling_next = p->child; ... p->child = np; (lines 343-350)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "exit",
          "excerpt": "first->sibling_pprev = &(__initproc->child); last->sibling_next = __initproc->child; ... __initproc->child = first; (lines 428-433)"
        }
      ]
    },
    {
      "question_id": "Q04_014",
      "question_type": "tri_state_impl",
      "stem": "是否实现信号 (signal) 或 futex？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/sched/signal.c",
          "symbol_kind": "function",
          "symbol_name": "sighandle",
          "excerpt": "void sighandle(void) { ... search for signal handler; allocate sig_frame and trapframe; set up trampoline for user-space handler ... }"
        },
        {
          "path": "kernel/sched/signal.c",
          "symbol_kind": "function",
          "symbol_name": "sigreturn",
          "excerpt": "void sigreturn(void) { ... restore original trapframe from sig_frame list ... }"
        },
        {
          "path": "kernel/sched/signal.c",
          "symbol_kind": "function",
          "symbol_name": "set_sigaction",
          "excerpt": "int set_sigaction(int signum, struct sigaction const *act, struct sigaction *oldact, int len) { ... }"
        },
        {
          "path": "kernel/syscall/syssignal.c",
          "symbol_kind": "function",
          "symbol_name": "sys_kill",
          "excerpt": "uint64 sys_kill(void) { ... return kill(pid, sig); }"
        }
      ],
      "notes": "信号机制已实现 (rt_sigaction, rt_sigprocmask, kill, sighandle, sigreturn)。Futex 未实现 (grep 'futex|FUTEX' 0 命中)。"
    },
    {
      "question_id": "Q04_015",
      "question_type": "short_answer",
      "stem": "与 09 多核的交叉一致性：是否存在每核队列/任务迁移/IPI resched？",
      "value": "不存在每核运行队列: proc_runnable[] 和 proc_sleep 是全局链表 (kernel/sched/proc.c:245-246)，所有 CPU 共享同一调度队列，通过 proc_lock 保护。\n不存在任务迁移: 无 migration/load_balance/affinity 相关代码 (grep 0 命中)。\n存在 IPI 跨核唤醒: wakeup() (kernel/sched/proc.c:392-403) 在唤醒睡眠进程后，若另一核空闲则通过 sbi_send_ipi() 发送 IPI 通知其重新进入调度循环。\n不存在 IPI resched: 无专门的 resched IPI 机制，yield() 不发送 IPI。",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "var",
          "symbol_name": "proc_runnable",
          "excerpt": "struct proc *proc_runnable[PRIORITY_NUMBER]; (line 245) — 全局数组，非 per-CPU"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "wakeup",
          "excerpt": "if (flag && avail) { sbi_send_ipi(1 << id, 0); } (lines 400-401)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "search",
          "symbol_name": "grep_load_balance_migration",
          "excerpt": "grep 'load_balance|migration|affinity|cpu_affinity' 0 命中"
        }
      ]
    },
    {
      "question_id": "Q04_016",
      "question_type": "short_answer",
      "stem": "exit() 资源回收路径：调用链是什么？是否真正回收地址空间/文件表/通知父进程？",
      "value": "调用链: exit() (kernel/sched/proc.c:405-476) → delsegs() 释放段列表 → uvmfree() 释放用户页表物理页 → dropfdtable() 关闭所有文件 → iput(cwd)/iput(elf) 释放 inode → 孤儿重父给 __initproc → 设置 SIGCHLD 通知父进程 → __wakeup_no_lock(parent) 唤醒父进程 → sched() 切换走。\n\n父进程在 scheduler() 中检测到 ZOMBIE 后释放 p->parent->lk (kernel/sched/proc.c:697-699)，然后 wait4() 中调用 freeproc() 回收 PCB (kernel/sched/proc.c:521)。\n\n是，真正回收地址空间 (delsegs+uvmfree)、文件表 (dropfdtable)、通知父进程 (SIGCHLD + wakeup)。",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "exit",
          "excerpt": "delsegs(p->pagetable, p->segment); uvmfree(p->pagetable); dropfdtable(&p->fds); iput(p->cwd); iput(p->elf); ... p->parent->sig_pending.__val[0] |= 1ul << SIGCHLD; ... __wakeup_no_lock(p->parent); sched();"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "wait4",
          "excerpt": "freeproc(np); return child_pid; (line 521)"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "scheduler",
          "excerpt": "if (ZOMBIE == tmp->state) { release(&(tmp->parent->lk)); } (lines 697-699)"
        }
      ]
    },
    {
      "question_id": "Q04_017",
      "question_type": "tri_state_impl",
      "stem": "是否实现进程组/会话（Process Group / Session，pgid/session/set_sid/setpgid）？",
      "value": "not_found",
      "evidence": [
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "search",
          "symbol_name": "grep_pgid_session",
          "excerpt": "grep 'ProcessGroup|Session|set_sid|setpgid|pgid|session_id' 全仓 0 命中。struct proc 中无 pgid/session/sid 字段。"
        },
        {
          "path": "kernel/syscall/syscall.c",
          "symbol_kind": "search",
          "symbol_name": "syscall_table_scan",
          "excerpt": "系统调用表中无 setpgid/getpgid/setsid/getsid 相关条目"
        }
      ]
    },
    {
      "question_id": "Q04_018",
      "question_type": "tri_state_impl",
      "stem": "是否实现 POSIX 资源限制（rlimit/RLIMIT/getrlimit/setrlimit）？",
      "value": "stub",
      "evidence": [
        {
          "path": "kernel/syscall/sysproc.c",
          "symbol_kind": "function",
          "symbol_name": "sys_prlimit64",
          "excerpt": "uint64 sys_prlimit64(void) { // for now it's not very necessary to implement this syscall // may be implemented later return 0; } (lines 273-277)"
        },
        {
          "path": "include/sysnum.h",
          "symbol_kind": "macro",
          "symbol_name": "SYS_prlimit64",
          "excerpt": "#define SYS_prlimit64 261 (line 76)"
        }
      ],
      "notes": "仅有 sys_prlimit64 桩函数，始终返回 0，无实际资源限制检查逻辑。不支持任何 RLIMIT 类型，无软/硬限制双机制。"
    },
    {
      "question_id": "Q04_019",
      "question_type": "single_choice",
      "stem": "该 OS 是否区分了 TCB（线程控制块）与 PCB（进程控制块）？",
      "value": "仅有统一 Task 结构（无区分）",
      "evidence": [
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "struct",
          "symbol_name": "proc",
          "excerpt": "struct proc 同时包含调度上下文 (context)、内存管理 (pagetable/segment)、文件系统 (fds/cwd)、信号 (sig_act/sig_pending) 等所有字段，无独立 TCB 结构体"
        },
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "search",
          "symbol_name": "grep_TCB_thread",
          "excerpt": "全仓搜索无独立 Thread/TCB 结构体定义"
        }
      ]
    },
    {
      "question_id": "Q04_020",
      "question_type": "tri_state_impl",
      "stem": "调度切换路径上是否存在页表切换（w_satp/sfence.vma/写 CR3/TTBR 等）？",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "scheduler",
          "excerpt": "w_satp(MAKE_SATP(tmp->pagetable)); sfence_vma(); // swtch context swtch(&c->context, &tmp->context); // switch back to kernel pagetable w_satp(MAKE_SATP(kernel_pagetable)); sfence_vma(); (lines 687-693)"
        },
        {
          "path": "kernel/exec.c",
          "symbol_kind": "function",
          "symbol_name": "execve",
          "excerpt": "w_satp(MAKE_SATP(p->pagetable)); sfence_vma(); (lines 290-291)"
        }
      ]
    },
    {
      "question_id": "Q04_021",
      "question_type": "single_choice",
      "stem": "用户线程与内核线程的映射模型 (User-Level Thread to Kernel-Level Thread Mapping) 更接近哪种？",
      "value": "无线程（仅进程/Task 不可再分）",
      "evidence": [
        {
          "path": "include/sched/proc.h",
          "symbol_kind": "struct",
          "symbol_name": "proc",
          "excerpt": "struct proc 无 thread 相关字段，clone() 创建的是完整进程副本而非线程。无 pthread 库、无用户态线程调度器、无 clone(CLONE_THREAD) 支持。"
        },
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "function",
          "symbol_name": "clone",
          "excerpt": "clone() 复制完整地址空间 (copysegs)、文件表 (copyfdtable)、信号设置，创建独立进程而非共享地址空间的线程"
        }
      ]
    },
    {
      "question_id": "Q04_022",
      "question_type": "tri_state_impl",
      "stem": "是否实现线程局部存储 (Thread-Local Storage, TLS)？",
      "value": "not_found",
      "evidence": [
        {
          "path": "kernel/",
          "symbol_kind": "search",
          "symbol_name": "grep_TLS",
          "excerpt": "grep 'thread_local|TLS|__thread|#[thread_local]' 全仓 0 命中。tp 寄存器仅用于存储 hartid (cpuid)，不用于 TLS。"
        }
      ]
    },
    {
      "question_id": "Q04_023",
      "question_type": "multi_choice",
      "stem": "调度器是否追踪/优化以下哪些性能指标 (Scheduling Criteria, Stallings Ch9)？",
      "value": [
        "未发现调度性能统计"
      ],
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "search",
          "symbol_name": "scheduling_stats_scan",
          "excerpt": "struct proc 中有 proc_tms (utime/stime/cutime/cstime) 和 vswtch/ivswtch 计数器 (include/sched/proc.h:67-71)，但这些是进程级别的计时统计，非调度器全局性能指标 (CPU利用率/吞吐量/周转时间/等待时间/响应时间)。无全局调度统计数据结构。"
        }
      ]
    },
    {
      "question_id": "Q04_024",
      "question_type": "tri_state_impl",
      "stem": "优先级调度是否实现老化 (Aging, Stallings Ch9) 以防止低优先级进程饥饿 (Starvation)？",
      "value": "not_found",
      "evidence": [
        {
          "path": "kernel/sched/proc.c",
          "symbol_kind": "search",
          "symbol_name": "grep_aging",
          "excerpt": "grep 'aging|boost_priority|starvation' 在 .c/.h/.S 文件中 0 命中 (仅匹配到 'paging' 无关项)。proc_tick() 中仅将 timer 递减到 0 的 RUNNABLE 进程迁移到 PRIORITY_TIMEOUT，无

---


# 第05章 文件系统与设备 IO

Now I have all the evidence needed. Let me compile the final JSON answer.

```json
{
  "schema_version": "v1",
  "stage_id": "05_fs_drivers",
  "stage_title": "文件系统与设备 I/O",
  "terminology_profile": "stallings_en_zh",
  "answers": [
    {
      "question_id": "Q05_001",
      "question_type": "short_answer",
      "stem": "VFS 抽象层 (Virtual File System, VFS)接口是什么形态？（Rust trait / C op 表；必须给接口定义证据）",
      "value": "C 函数指针操作表（op 表）。VFS 定义了四层操作接口：fs_op（超级块操作）、inode_op（索引节点操作）、dentry_op（目录项操作）、file_op（文件操作），每层均为包含函数指针的结构体。例如 `include/fs/fs.h:45-76` 定义了 `struct fs_op`（含 alloc_inode/destroy_inode/write/read/clear/statfs/sync）、`struct inode_op`（含 create/lookup/truncate/unlink/update/getattr/setattr/rename）、`struct dentry_op`（含 delete/cache）、`struct file_op`（含 read/write/readdir/readv/writev）。具体文件系统通过填充这些 op 表的实例来注册到 VFS。",
      "evidence": [
        {
          "path": "include/fs/fs.h",
          "symbol_kind": "struct",
          "symbol_name": "fs_op",
          "excerpt": "struct fs_op { struct inode *(*alloc_inode)(struct superblock *sb); void (*destroy_inode)(struct inode *ip); int (*write)(struct superblock *sb, int usr, char *src, uint64 blockno, uint64 off, uint64 len); int (*read)(...); int (*clear)(...); int (*statfs)(...); void (*sync)(...); }; (L45-52)"
        },
        {
          "path": "include/fs/fs.h",
          "symbol_kind": "struct",
          "symbol_name": "inode_op",
          "excerpt": "struct inode_op { struct inode *(*create)(...); struct inode *(*lookup)(...); int (*truncate)(...); int (*unlink)(...); int (*update)(...); int (*getattr)(...); int (*setattr)(...); int (*rename)(...); }; (L55-63)"
        },
        {
          "path": "include/fs/fs.h",
          "symbol_kind": "struct",
          "symbol_name": "file_op",
          "excerpt": "struct file_op { int (*read)(struct inode *ip, int usr, uint64 dst, uint off, uint n); int (*write)(...); int (*readdir)(...); int (*readv)(...); int (*writev)(...); }; (L71-76)"
        }
      ]
    },
    {
      "question_id": "Q05_002",
      "question_type": "single_choice",
      "stem": "具体文件系统后端 (Concrete File System Backend) 更接近哪种？",
      "value": "混合挂载（磁盘 FS + 内存 FS 均支持）",
      "evidence": [
        {
          "path": "kernel/fs/rootfs.c",
          "symbol_kind": "function",
          "symbol_name": "rootfs_init",
          "excerpt": "rootfs_init() (L230-313) 创建 rootfs（内存虚拟 FS）、devfs（含 console/vda2/zero/null 设备节点）、procfs（含 mounts/meminfo），然后通过 do_mount(vda->inode, rootfs.root->inode, \"fat32\", 0, 0) 将 FAT32 磁盘镜像挂载到根，再将 devfs/procfs 挂载到 /dev 和 /proc。"
        },
        {
          "path": "kernel/fs/fat32/fat32.c",
          "symbol_kind": "function",
          "symbol_name": "fat32_init",
          "excerpt": "fat32_init() (L47-140) 解析 FAT32 BPB（BIOS Parameter Block），验证 'FAT32' 签名，读取 FS Info Sector，初始化根目录 inode。"
        },
        {
          "path": "kernel/fs/blkdev.c",
          "symbol_kind": "function",
          "symbol_name": "fs_install",
          "excerpt": "fs_install() (L169-245) 根据设备类型（S_IFBLK 或 S_IFREG）绑定 disk_read_block/disk_write_block 或 img_read_block/img_write_block 回调到 superblock->op。"
        }
      ]
    },
    {
      "question_id": "Q05_003",
      "question_type": "short_answer",
      "stem": "若支持 FAT32/Ext4：它是自研还是第三方库/crate？（必须引用 Cargo.toml/Cargo.lock 或 Makefile 引入证据）",
      "value": "自研实现。FAT32 文件系统完全由本仓库 C 代码实现，未引入任何第三方 FAT32 库或 crate。Makefile 中所有 FAT32 相关源文件均为本仓库 kernel/fs/fat32/ 目录下的自研代码：fat32.c、fat.c、cluster.c、dirent.c。",
      "evidence": [
        {
          "path": "Makefile",
          "symbol_kind": "build_config",
          "symbol_name": "SRC_fat32",
          "excerpt": "Makefile L88-91: SRC += $K/fs/fat32/cluster.c $K/fs/fat32/dirent.c $K/fs/fat32/fat.c $K/fs/fat32/fat32.c — 全部为仓库内自研源文件，无外部依赖。"
        },
        {
          "path": "kernel/fs/fat32/fat32.c",
          "symbol_kind": "file_header",
          "symbol_name": "fat32_module",
          "excerpt": "L1-20: 仅包含本仓库头文件（types.h, printf.h, errno.h, hal/riscv.h, fs/stat.h, fs/fs.h, fat32.h, mm/kmalloc.h 等），无任何第三方库引用。"
        }
      ]
    },
    {
      "question_id": "Q05_004",
      "question_type": "short_answer",
      "stem": "文件打开路径：文件打开入口（sys_open 或等价）→ VFS 层 → 具体 FS open。列出 3-6 个关键节点并给证据。",
      "value": "1) sys_openat (kernel/syscall/sysfile.c:194) — 系统调用入口，解析路径参数和标志；2) create 或 nameifrom (kernel/fs/fs.c:24/474) — 根据 O_CREATE 标志选择创建或查找路径；3) nameiparentfrom / lookup_path (kernel/fs/fs.c:480/413) — 逐级路径解析，处理 '/' 和挂载点穿越 (de_mnt_in)；4) dirlookup (kernel/fs/fs.c:320) — 在目录中查找文件名，先查 dentry 缓存再调用具体 FS 的 lookup；5) fat_lookup_dir (kernel/fs/fat32/fat32.c:562) — FAT32 具体实现，遍历目录簇链匹配文件名；6) filealloc + fdalloc (kernel/fs/file.c:30/411) — 分配 file 结构和 fd 号，设置 FD_INODE/FD_DEVICE 类型。",
      "evidence": [
        {
          "path": "kernel/syscall/sysfile.c",
          "symbol_kind": "function",
          "symbol_name": "sys_openat",
          "excerpt": "L194-267: 解析 dirfd/path/omode/fmode → 若 O_CREATE 则 create(dp, path, ...) 否则 nameifrom(dp, path) → filealloc() → fdalloc(f, omode & O_CLOEXEC) → 设置 f->type = FD_INODE 或 FD_DEVICE。"
        },
        {
          "path": "kernel/fs/fs.c",
          "symbol_kind": "function",
          "symbol_name": "lookup_path",
          "excerpt": "L413-462: 处理 '/' 开头（从 rootfs.root 开始）或相对路径（从 cwd 开始），循环调用 skipelem + dirlookup 逐级解析。"
        },
        {
          "path": "kernel/fs/fs.c",
          "symbol_kind": "function",
          "symbol_name": "dirlookup",
          "excerpt": "L320-388: 处理 '.' 和 '..'（含挂载点穿越），先查 dentry 缓存 (de->op->cache)，未命中则调用 dir->op->lookup（即 fat_lookup_dir）并创建新 dentry 插入缓存。"
        }
      ]
    },
    {
      "question_id": "Q05_005",
      "question_type": "short_answer",
      "stem": "文件描述符表 (File Descriptor Table, FD Table) 的实现形态是什么？（固定数组/Vec/BTreeMap 等；必须给结构体定义证据）",
      "value": "链表扩展的固定数组。每个 fdtable 包含一个固定大小 `struct file *arr[NOFILE]` 数组（NOFILE=16，定义于 include/param.h），通过 `next` 指针链接多个 fdtable 形成链表以支持超过 16 个 fd。basefd 记录该表的起始 fd 偏移，nextfd 记录下一个空闲 fd 位置。",
      "evidence": [
        {
          "path": "include/fs/file.h",
          "symbol_kind": "struct",
          "symbol_name": "fdtable",
          "excerpt": "L32-38: struct fdtable { uint16 basefd; uint16 nextfd; uint16 used; uint16 exec_close; struct file *arr[NOFILE]; struct fdtable *next; };"
        },
        {
          "path": "kernel/fs/file.c",
          "symbol_kind": "function",
          "symbol_name": "fdalloc",
          "excerpt": "L411-446: 当 fdt->nextfd == NOFILE 时通过 newfdtable() 分配新的 fdtable 节点并链接到链表尾部，实现动态扩展。"
        }
      ]
    },
    {
      "question_id": "Q05_006",
      "question_type": "tri_state_impl",
      "stem": "是否实现块缓存/缓冲缓存 (Block Cache / Buffer Cache, bcache)？（必须三态）",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/fs/bio.c",
          "symbol_kind": "function",
          "symbol_name": "binit",
          "excerpt": "L84-106: 初始化 BNUM(2500) 个 buf 结构体，全部加入 LRU 链表 lru_head，初始化哈希表 bcache[BCACHE_TABLE_SIZE]。"
        },
        {
          "path": "kernel/fs/bio.c",
          "symbol_kind": "function",
          "symbol_name": "bget",
          "excerpt": "L108-183: 先查哈希表 bcache[idx] 命中则增加 refcnt 并从 LRU 链表移除；未命中则从 LRU 链表尾部取空闲 buf，若 LRU 为空则 sleep 等待。"
        },
        {
          "path": "kernel/fs/bio.c",
          "symbol_kind": "function",
          "symbol_name": "bread",
          "excerpt": "L185-196: bread(dev, sectorno) → bget() 获取锁定的 buf，若 !b->valid 则调用 disk_read(b) 从磁盘读取数据。"
        }
      ]
    },
    {
      "question_id": "Q05_007",
      "question_type": "short_answer",
      "stem": "若存在缓存：驱逐策略是什么（LRU/Clock/FIFO/无驱逐）？必须指出判断依据（字段/算法分支）证据。",
      "value": "LRU（最近最少使用）驱逐策略。bget() 中：命中时通过 _list_remove + _list_push_front 将 buf 移到哈希链表头部（L127-129）；未命中时从 LRU 链表尾部 (lru_head.prev) 取最久未使用的 buf 进行驱逐复用（L148-163）。buf 通过 d_list 结构维护在 lru_head 双向链表中，refcnt==0 时 buf 在 LRU 链表中，refcnt>0 时从 LRU 链表移除。",
      "evidence": [
        {
          "path": "kernel/fs/bio.c",
          "symbol_kind": "function",
          "symbol_name": "bget",
          "excerpt": "L127-129: if (l != bcache[idx]) { _list_remove(l); _list_push_front(&bcache[idx], l); } — 命中时移到链表头部（LRU 语义）。L148-163: struct d_list *dl = lru_head.prev; if (dl != &lru_head) { b = container_of(dl, struct buf, list); ... } — 从 LRU 尾部取最久未使用的 buf 驱逐。"
        },
        {
          "path": "kernel/fs/bio.c",
          "symbol_kind": "variable",
          "symbol_name": "lru_head",
          "excerpt": "L73: static struct d_list lru_head; — 全局 LRU 双向链表头，所有 refcnt==0 的 buf 挂在此链表上。"
        }
      ]
    },
    {
      "question_id": "Q05_008",
      "question_type": "tri_state_impl",
      "stem": "是否实现页缓存 (Page Cache)或与 mmap/文件映射共享缓存页？（必须三态）",
      "value": "not_found",
      "evidence": [
        {
          "path": "kernel/fs",
          "symbol_kind": "search",
          "symbol_name": "page_cache_search",
          "excerpt": "在 kernel/fs/ 及 include/fs/ 中搜索 page_cache、PageCache、pagecache 等关键词，仅在 include/utils/rbtree.h 中发现 rb_search_page_cache/rb_insert_page_cache 辅助函数（用于 inode 的 mapping 红黑树），但这是 mmap 映射页管理而非通用页缓存。未发现独立的页缓存层（如 page cache 用于缓存文件数据页而非块设备块）。"
        }
      ]
    },
    {
      "question_id": "Q05_009",
      "question_type": "tri_state_impl",
      "stem": "是否实现 mmap 的文件映射或匿名映射？（必须三态；若 stub 说明形态）",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/syscall/sysmem.c",
          "symbol_kind": "function",
          "symbol_name": "sys_mmap",
          "excerpt": "L80-112: 解析 prot/flags/fd/off 参数，支持 MAP_ANONYMOUS（匿名映射）和 MAP_SHARED/MAP_PRIVATE（文件映射），调用 do_mmap()。"
        },
        {
          "path": "kernel/mm/mmap.c",
          "symbol_kind": "function",
          "symbol_name": "do_mmap",
          "excerpt": "L710-770: 检查文件权限与 prot 匹配，调用 lookup_segment/lookup_fixed_segment 查找空闲地址段，根据是否有文件分别调用 mmap_file() 或 mmap_anonymous()，最后插入进程 segment 链表。"
        },
        {
          "path": "kernel/syscall/sysmem.c",
          "symbol_kind": "function",
          "symbol_name": "sys_munmap",
          "excerpt": "L116-130: 实现 munmap 系统调用，调用 do_munmap() 解除映射。"
        }
      ]
    },
    {
      "question_id": "Q05_010",
      "question_type": "tri_state_impl",
      "stem": "是否实现 poll/select/epoll（或等价事件机制）？（必须三态）",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/syscall/sysfile.c",
          "symbol_kind": "function",
          "symbol_name": "sys_pselect",
          "excerpt": "L679-737: 实现 pselect 系统调用，解析 nfds/readfds/writefds/exceptfds/timeout/sigmask，调用 pselect() 核心函数。"
        },
        {
          "path": "kernel/syscall/sysfile.c",
          "symbol_kind": "function",
          "symbol_name": "sys_ppoll",
          "excerpt": "L739-787: 实现 ppoll 系统调用入口。"
        },
        {
          "path": "kernel/fs/poll.c",
          "symbol_kind": "function",
          "symbol_name": "pselect",
          "excerpt": "L125-243: 完整实现 pselect：遍历 fdset 中每个 fd，调用 file_poll() 检查状态，通过 poll_wait_queue 注册到各文件的 wait_queue，支持超时（poll_sched_timeout）和信号中断。"
        },
        {
          "path": "kernel/fs/poll.c",
          "symbol_kind": "function",
          "symbol_name": "ppoll",
          "excerpt": "L100-103: ppoll() 实现为桩——直接设置所有 pfds[i].revents = POLLIN|POLLOUT 并返回 nfds，未真正检查文件状态。但 pselect 是完整实现。"
        }
      ]
    },
    {
      "question_id": "Q05_011",
      "question_type": "tri_state_impl",
      "stem": "路径解析 (namei/path_walk/lookup) 是否实现并支持绝对/相对路径与 . ..？（必须三态）",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/fs/fs.c",
          "symbol_kind": "function",
          "symbol_name": "lookup_path",
          "excerpt": "L413-462: 支持绝对路径（'/' 开头从 rootfs.root 开始）和相对路径（从 ip 或 myproc()->cwd 开始），循环调用 skipelem 分割路径分量，dirlookup 逐级查找。"
        },
        {
          "path": "kernel/fs/fs.c",
          "symbol_kind": "function",
          "symbol_name": "dirlookup",
          "excerpt": "L320-340: 显式处理 '.'（返回 idup(de->inode)）和 '..'（含挂载点穿越逻辑：当 de==sb->root 时沿 de->parent 回溯到父文件系统的根）。"
        },
        {
          "path": "kernel/fs/fs.c",
          "symbol_kind": "function",
          "symbol_name": "namei",
          "excerpt": "L463-467: namei(path) → lookup_path(NULL, path, 0, name) 的简单包装。"
        }
      ]
    },
    {
      "question_id": "Q05_012",
      "question_type": "tri_state_impl",
      "stem": "是否支持符号链接 (symlink) 的解析/跟随？（必须三态）",
      "value": "not_found",
      "evidence": [
        {
          "path": "include/fs/stat.h",
          "symbol_kind": "macro",
          "symbol_name": "S_IFLNK",
          "excerpt": "L12: #define S_IFLNK 0120000 — 定义了符号链接的文件类型宏，但未发现创建符号链接的系统调用（无 sys_symlink/symlinkat）。"
        },
        {
          "path": "kernel/syscall/sysfile.c",
          "symbol_kind": "function",
          "symbol_name": "sys_readlinkat",
          "excerpt": "L616-654: sys_readlinkat 实现为通过 namepath() 返回文件路径名，而非读取符号链接目标内容。未在 open/lookup_path 路径中发现 symlink 跟随逻辑。"
        },
        {
          "path": "kernel/syscall",
          "symbol_kind": "search",
          "symbol_name": "symlink_search",
          "excerpt": "在 kernel/syscall/ 和 include/ 中搜索 sys_symlink、symlinkat、S_IFLNK 使用，仅发现 S_IFLNK 宏定义和 sys_readlinkat（非真正 symlink 解析），无 symlink 创建或跟随实现。"
        }
      ]
    },
    {
      "question_id": "Q05_013",
      "question_type": "tri_state_impl",
      "stem": "是否实现管道 (pipe/pipe2) 并在 VFS 层作为文件对象？（必须三态；与 08 章 pipe 实现互指）",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/fs/pipe.c",
          "symbol_kind": "function",
          "symbol_name": "pipealloc",
          "excerpt": "L39-93: 分配 pipe 结构体（含环形缓冲区 data[PIPE_SIZE]、读写指针 nread/nwrite、自旋锁 lock、两个 wait_queue），创建两个 file 对象（f0 可读 FD_PIPE，f1 可写 FD_PIPE），设置 f->poll = pipepoll。"
        },
        {
          "path": "kernel/fs/pipe.c",
          "symbol_kind": "function",
          "symbol_name": "pipewrite",
          "excerpt": "L240-300: 环形缓冲写入，支持动态扩展（当数据量 > PIPE_SIZE 时分配更大缓冲区），通过 pipelock 互斥写者，写完后 pipewakeup 唤醒读者。"
        },
        {
          "path": "kernel/fs/pipe.c",
          "symbol_kind": "function",
          "symbol_name": "piperead",
          "excerpt": "L301-348: 环形缓冲读取，通过 pipereadable 检查可读数据，数据不足时 sleep 等待，读完后 pipewakeup 唤醒写者。"
        },
        {
          "path": "kernel/syscall/sysfile.c",
          "symbol_kind": "function",
          "symbol_name": "sys_pipe",
          "excerpt": "L317-355: sys_pipe 系统调用 → pipealloc(&rf, &wf) → fdalloc(rf, 0) + fdalloc(wf, 0) → copyout2 返回两个 fd 给用户空间。"
        }
      ]
    },
    {
      "question_id": "Q05_014",
      "question_type": "tri_state_impl",
      "stem": "是否实现网络 socket（作为 VFS 文件对象）？（必须三态）",
      "value": "not_found",
      "evidence": [
        {
          "path": "include/errno.h",
          "symbol_kind": "macro",
          "symbol_name": "ENOTSOCK",
          "excerpt": "L95: #define ENOTSOCK 88 — 定义了 socket 相关错误码，但仅为头文件定义。"
        },
        {
          "path": "include/fs/stat.h",
          "symbol_kind": "macro",
          "symbol_name": "S_IFSOCK",
          "excerpt": "L11: #define S_IFSOCK 0140000 — 定义了 socket 文件类型宏，但未发现任何 socket 创建或操作实现。"
        },
        {
          "path": "kernel/syscall",
          "symbol_kind": "search",
          "symbol_name": "socket_search",
          "excerpt": "在 kernel/syscall/ 和 kernel/fs/ 中搜索 sys_socket、sys_bind、sys_listen、sys_accept、sys_connect 等 socket 系统调用，0 命中。未发现网络协议栈或 socket 文件对象实现。"
        }
      ]
    },
    {
      "question_id": "Q05_015",
      "question_type": "tri_state_impl",
      "stem": "是否实现伪文件系统（devfs/procfs/sysfs）？（必须三态；若 implemented 需说明实现形态）",
      "value": "implemented",
      "evidence": [
        {
          "path": "kernel/fs/rootfs.c",
          "symbol_kind": "function",
          "symbol_name": "rootfs_init",
          "excerpt": "L230-313: 初始化 devfs（创建 /dev/console 字符设备、/dev/vda2 块设备、/dev/zero、/dev/null）和 procfs（创建 /proc/mounts、/proc/meminfo），均为纯内存虚拟文件系统，通过 de_root_generate() 创建虚拟 inode/dentry。"
        },
        {
          "path": "kernel/fs/rootfs.c",
          "symbol_kind": "variable",
          "symbol_name": "devfs",
          "excerpt": "L17: struct superblock devfs; — 全局 devfs 超级块实例。L15-16: struct superblock rootfs; struct superblock procfs;"
        },
        {
          "path": "kernel/fs/rootfs.c",
          "symbol_kind": "function",
          "symbol_name": "de_root_generate",
          "excerpt": "L183-226: 分配并初始化 dentry + inode，设置 op 为 rootfs_inode_op/rootfs_file_op（大部分为 dummy 函数返回 -1 或 0），插入父目录的 child 链表。"
        },
        {
          "path": "kernel/fs/mount.c",
          "symbol_kind": "function",
          "symbol_name": "mountsysfs",
          "excerpt": "L200-222: mountsysfs() 将内存文件系统（devfs/procfs）挂载到指定目录，设置 dentry->mount 指向对应 superblock。"
        }
      ]
    },
    {
      "question_id": "Q05_016",
      "question_type": "single_choice",
      "stem": "文件描述符表的归属是哪种？",
      "value": "Per-Process（每进程独立 fd 表，fork 时复制/共享）",
      "evidence": [
        {
          "path": "kernel/fs/file.c",
          "symbol_kind": "function",
          "symbol_name": "fdalloc",
          "excerpt": "L413: struct proc *p = myproc(); struct fdtable *fdt = &p->fds; — fdtable 嵌入在 proc 结构体中，每个进程独立拥有。"
        },
        {
          "path": "kernel/fs/file.c",
          "symbol_kind": "function",
          "symbol_name": "copyfdtable",
          "excerpt": "L313-345: fork 时调用 copyfdtable(fdt1, fdt2) 复制整个 fdtable 链表，每个 file 通过 filedup() 增加引用计数（ref++），实现父子进程共享文件对象。"
        },
        {
          "path": "kernel/fs/file.c",
          "symbol_kind": "function",
          "symbol_name": "fdcloexec",
          "excerpt": "L497-529: exec 时调用 fdcloexec() 遍历 fdtable 链表，关闭所有设置了 O_CLOEXEC 标志的 fd。"
        }
      ]
    },
    {
      "question_id": "Q05_017",
      "question_type": "single_choice",
      "stem": "文件数据块分配方式 (File Allocation Method, Stallings Ch12) 更接近哪种？",
      "value": "FAT 表内嵌空闲链（FAT32 特有）",
      "evidence": [
        {
          "path": "kernel/fs/fat32/fat32.h",
          "symbol_kind": "struct",
          "symbol_name": "fat32_entry",
          "excerpt": "L89-103: struct fat32_entry { ... uint32 first_clus; uint32 file_size; struct clus_table *cur_clus; struct rb_root rb_clus; ... } — 文件通过 first_clus 指向首簇，后续簇通过 FAT 表链式查找。"
        },
        {
          "path": "kernel/fs/fat32/fat.c",
          "symbol_kind": "function",
          "symbol_name": "read_fat",
          "excerpt": "L1-100: read_fat() 从 FAT 表中读取指定簇的下一簇号，FAT32 的 FAT 表本身就是簇链索引。"
        },
        {
          "path": "kernel/fs/fat32/cluster.c",
          "symbol_kind": "function",
          "symbol_name": "alloc_clus",
          "excerpt": "L50-80: alloc_clus() 从 fat->next_free 分配空闲簇，通过 fat_update_next_free() 在 FAT 表中查找下一个空闲簇。"
        }
      ]
    },
    {
      "question_id": "Q05_018",
      "question_type": "single_choice",
      "stem": "磁盘/存储空闲空间管理 (Free Space Management, Stallings Ch12) 更接近哪种？",
      "value": "FAT 表内嵌空闲链（FAT32 特有）",
      "evidence": [
        {
          "path": "kernel/fs/fat32/fat32.h",
          "symbol_kind": "struct",
          "symbol_name": "fat32_sb",
          "excerpt": "L54-80: struct fat32_sb { ... uint32 free_count; uint32 next_free; uint16 fs_info; ... } — 通过 FS Info Sector 中的 free_count 和 next_free 字段跟踪空闲簇。"
        },
        {
          "path": "kernel/fs/fat32/fat32.c",
          "symbol_kind": "function",
          "symbol_name": "fat32_init",
          "excerpt": "L108-118: 读取 FS Info Sector（验证签名 0x41615252/0x61417272/0xaa550000），获取 fat->free_count 和 fat->next_free。"
        },
        {
          "path": "kernel/fs/fat32/cluster.c",
          "symbol_kind": "function",
          "symbol_name": "alloc_clus",
          "excerpt": "L50-80: 分配簇时使用 fat->next_free，然后调用 fat_update_next_free() 在 FAT 表中扫描下一个值为 0 的条目（即空闲簇）。"
        }
      ]
    },
    {
      "question_id": "Q05_019",
      "question_type": "single_choice",
      "stem": "目录结构 (Directory Structure, Stallings Ch12) 更接近哪种？",
      "value": "树形层次目录 (Tree-Structured Hierarchy)（最常见）",
      "evidence": [
        {
          "path": "kernel/fs/fs.c",
          "symbol_kind": "function",
          "symbol_name": "dirlookup",
          "excerpt": "L320-388: 支持 '.' 和 '..' 导航，dentry 通过 parent/child/next 指针形成树形层次结构。"
        },
        {
          "path": "include/fs/fs.h",
          "symbol_kind": "struct",
          "symbol_name": "dentry",
          "excerpt": "L128-137: struct dentry { char filename[MAXNAME+1]; struct inode *inode; struct dentry *parent; struct dentry *next; struct dentry *child; ... } — 典型的树形目录结构（parent 指向父目录，child 指向第一个子项，next 链接兄弟节点）。"
        },
        {
          "path": "kernel/fs/rootfs.c",
          "symbol_kind": "function",
          "symbol_name": "rootfs_init",
          "excerpt": "L230-313: 创建 /、/dev、/proc、/bin 等多级目录，通过 create() 在磁盘上创建目录 inode，通过 mountsysfs() 挂载子文件系统。"
        }
      ]
    },
    {
      "question_id": "Q05_020",
      "question_type": "single_choice",
      "stem": "文件内部记录组织 (File Record Organization, Stallings Ch12) 更接近哪种？",
      "value": "字节流 (Byte Stream / Unstructured)：无固定记录结构",
      "evidence": [
        {
          "path": "kernel/fs/file.c",
          "symbol_kind": "function",
          "symbol_name": "fileread",
          "excerpt": "L113-155: fileread() 按字节流方式读取——从 f->off 偏移开始读取 n 字节，读后 f->off += r。无记录边界概念。"
        },
        {
          "path": "kernel/fs/file.c",
          "symbol_kind": "function",
          "symbol_name": "filewrite",
          "excerpt": "L157-192: filewrite() 按字节流方式写入——从 f->off 偏移开始写入 n 字节，写后 f->off += n。"
        },
        {
          "path": "kernel/fs/fat32/fat32.c",
          "symbol_kind": "function",
          "symbol_name": "fat_read_file",
          "excerpt": "L273-304: fat_read_file() 按字节偏移和长度读取，通过簇链定位数据，无记录结构。"
        }
      ]
    },
    {
      "question_id": "Q05_021",
      "question_type": "single_choice",
      "stem": "设备发现/枚举机制更接近哪种？",
      "value": "硬编码设备表/固定 MMIO 地址",
      "evidence": [
        {
          "path": "include/memlayout.h",
          "symbol_kind": "macro",
          "symbol_name": "UART",
          "excerpt": "L37-41: #ifdef QEMU → #define UART 0x10000000L, #else → #define UART 0x38000000L — UART 地址硬编码，通过编译宏区分平台。"
        },
        {
          "path": "include/memlayout.h",
          "symbol_kind": "macro",
          "symbol_name": "VIRTIO0",
          "excerpt": "L49-50: #define VIRTIO0 0x10001000 — virtio MMIO 基址硬编码。"
        },
        {
          "path": "include/memlayout.h",
          "symbol_kind": "macro",
          "symbol_name": "PLIC",
          "excerpt": "L55-56: #define PLIC 0x0c000000L — PLIC 基址硬编码。"
        },
        {
          "path": "kernel/hal/disk.c",
          "symbol_kind": "function",
          "symbol_name": "disk_init",
          "excerpt": "L22-33: #ifdef QEMU → virtio_disk_init(), #else → sdcard_init() — 通过编译宏选择驱动，无运行时设备探测。"
        }
      ]
    },
    {
      "question_id": "Q05_022",
      "question_type": "tri_state_impl",
      "stem": "是否能在代码中证实解析了 `.dtb`/DeviceTree？（必须三态；若 implemented 必须指出解析入口）",
      "value": "not_found",
      "evidence": [
        {
          "path": "bootloader/SBI/rustsbi-qemu/src/main.rs",
          "symbol_kind": "function",
          "symbol_name": "count_harts",
          "excerpt": "L245-280: RustSBI 引导加载器中通过 device_tree crate 解析 DTB 以计数 CPU 核心数，但这是引导加载器行为，内核本身不解析 DTB。"
        },
        {
          "path": "kernel",
          "symbol_kind": "search",
          "symbol_name": "dtb_search",
          "excerpt": "在 kernel/ 目录中搜索 fdt、dtb、device_tree、libfdt、of_ 等关键词，0 命中。内核所有 MMIO 地址均通过 include/memlayout.h 中的硬编码宏定义。"
        }

---


# 第06章 同步互斥与进程间通信

### Q06_001 该内核提供了哪些同步原语？（SpinLock/Mutex/RwLock/Semaphore/Condvar/WaitQueue 等；列出类型定义证据）

该内核提供以下同步原语：
1. **自旋锁 (Spinlock)**：`struct spinlock` 定义于 `include/sync/spinlock.h:7-12`，字段含 `uint locked`、`char *name`、`struct cpu *cpu`。实现于 `kernel/sync/spinlock.c`，使用 GCC 内置 `__sync_lock_test_and_set` / `__sync_lock_release` 原子操作 + `push_off`/`pop_off` 中断屏蔽。
2. **睡眠锁 (Sleeplock)**：`struct sleeplock` 定义于 `include/sync/sleeplock.h:10-16`，内部嵌入 `struct spinlock lk` 保护状态，字段含 `uint locked`、`int pid`。实现于 `kernel/sync/sleeplock.c`，基于 spinlock + `sleep`/`wakeup` 实现阻塞语义。
3. **等待队列 (Wait Queue)**：`struct wait_queue` 定义于 `include/sync/waitqueue.h:17-20`，基于双向链表 `struct d_list head` + `struct spinlock lock`。`struct wait_node` 定义于同文件行 22-25。提供 `wait_queue_init`/`wait_queue_add`/`wait_queue_del`/`wait_queue_is_first` 等内联操作。
4. **sleep/wakeup 条件同步**：`sleep()` 定义于 `kernel/sched/proc.c:582`，`wakeup()` 定义于 `kernel/sched/proc.c:392`，基于 `proc_lock` 保护的进程链表实现阻塞/唤醒。
5. **未发现**：Mutex（独立阻塞互斥锁）、RwLock（读写锁）、Semaphore（信号量）、Condvar（条件变量）均未在代码库中检索到对应类型定义或实现。

### Q06_002 Mutex 更接近哪种实现？

未发现/待核实

### Q06_003 是否存在等待队列 (Wait Queue, WaitQueue) 与 sleep/wakeup（或等价阻塞/唤醒）实现？（必须三态）

已实现

### Q06_004 sleep / wakeup 不变量 (Sleep-Wakeup Invariant) 分析，按格式填写：
- sleep 入口函数: ___（路径）
- 入睡前持有的锁: ___（无则写 none）
- 防丢 wakeup (Lost Wakeup Prevention) 机制: ___（如：持队列锁检查条件 / 无防护）
- wakeup 函数: ___（路径）
- 唤醒与锁释放顺序: ___（先唤醒后释放 / 先释放后唤醒 / 其他）

- sleep 入口函数: kernel/sched/proc.c:582 (sleep)
- 入睡前持有的锁: 调用者持有的 spinlock（参数 lk），在 sleep 内部若 lk != &proc_lock 则先 acquire(&proc_lock) 再 release(lk)，保证原子性
- 防丢 wakeup (Lost Wakeup Prevention) 机制: 持 proc_lock 检查/设置 chan 并移入 sleep 链表，wakeup 同样持 proc_lock 遍历；调用者（如 pipewritable）在检查条件前持有 pi->lock，sleep 以该锁为参数传入，确保条件检查和入睡原子
- wakeup 函数: kernel/sched/proc.c:392 (wakeup)
- 唤醒与锁释放顺序: 先唤醒后释放 — wakeup 内部持 proc_lock 将目标进程移回 runnable，释放 proc_lock 后若目标 CPU 空闲则发送 IPI；sleep 返回后重新 acquire(lk)（原调用者锁）

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

用户态 handler 上下文构建流程（`kernel/sched/signal.c:177-262` sighandle()）：
1. 分配新的 `struct sig_frame` 和 `struct trapframe`。
2. 将进程当前的 `p->trapframe` 保存到 `frame->tf`（即保存原上下文）。
3. 构造新的 trapframe：`tf->epc` 设为 `SIG_TRAMPOLINE + (sig_handler - sig_trampoline)`（即用户态 trampoline 页中的 sig_handler 入口）；`tf->sp` 继承原 trapframe 的 sp；`tf->a0` = signum；`tf->a1` = handler 函数指针（或默认 handler）。
4. 将 `p->trapframe` 替换为新 tf，将 frame 插入 `p->sig_frame` 链表头部。
5. 当进程返回用户态时，CPU 从新 trapframe 恢复上下文，跳转到 sig_handler 执行。

sigreturn 恢复（`kernel/sched/signal.c:263-283` sigreturn()）：
1. 从 `p->sig_frame` 链表弹出头部 frame。
2. `kfree(p->trapframe)` 释放信号处理期间的 trapframe。
3. `p->trapframe = frame->tf` 恢复原 trapframe。
4. `kfree(frame)` 释放 sig_frame。
5. sigreturn 在 `kernel/syscall/syscall.c:340-345` 被特殊处理：当 syscall num == SYS_rt_sigreturn 时直接调用 sigreturn() 而不走常规 syscall 分发，因为需要恢复 trapframe 而非向其写入返回值。

### Q06_012 RwLock（读写锁 Reader-Writer Lock）的实现形态更接近哪种？

未发现/不支持

### Q06_013 底层原子操作来源更接近哪种？

自定义汇编（ldxr/stxr、lock xchg 等）

### Q06_014 死锁四必要条件（Coffman Conditions）在该内核中是否均成立？
请逐条作答（互斥 Mutual Exclusion / 持有并等待 Hold-and-Wait / 不可剥夺 No Preemption / 循环等待 Circular Wait），并结合 SpinLock/Mutex 的实现给出证据或写「不适用」。

逐条分析：
1. **互斥 (Mutual Exclusion)**：成立。spinlock 通过 `__sync_lock_test_and_set` 原子 swap 实现互斥（`kernel/sync/spinlock.c:34`），同一时刻仅一个 CPU 可持有锁。sleeplock 同样通过内部 spinlock 保护 locked 字段实现互斥。
2. **持有并等待 (Hold-and-Wait)**：成立。内核中存在多处持锁后申请另一锁的场景，如 `kernel/fs/fs.c:582` 中 `trysleeplock(&iold->lock)` 注释 "just try, in case of deadlock"，说明存在持锁等待另一锁的可能。`kernel/sched/proc.c:454` 注释 "acquire proc_lock after parent's lock, to avoid deadlock" 也证实嵌套持锁存在。
3. **不可剥夺 (No Preemption)**：成立。spinlock 通过 `push_off()` 关中断（`kernel/intr.c:12-22`），持有锁期间不可被抢占。sleeplock 持有期间进程虽可 sleep 但锁不释放给其他进程。
4. **循环等待 (Circular Wait)**：可能成立但内核通过锁排序预防。`kernel/sched/proc.c:249-251` 注释 "proc_lock should be acquired last with any situation requiring multiple spinlocks" 定义了 proc_lock 的获取顺序规则。但若调用者不遵守，循环等待仍可能发生。

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

- 生产者-消费者 (Producer-Consumer / Bounded Buffer)：not_found。在全部 .c/.h 文件中检索 producer/consumer/bounded.buffer，0 命中。管道 (pipe) 的读写模型本质上是生产者-消费者问题的实例，但仓库内无独立的经典问题测试或演示代码。
- 读者-写者 (Readers-Writers)：not_found。未发现 RwLock 实现（见 Q06_012），亦无读者-写者问题的测试代码。
- 哲学家就餐 (Dining Philosophers)：not_found。检索 dining/philosopher，0 命中。

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

已实现

### Q07_004 若存在权限检查：入口点与核心检查函数链路是什么？（列 2-5 个节点并给证据）

权限检查链路（基于 file.readable/writable 标志）：
1. usertrap (kernel/trap/trap.c:75) → syscall (kernel/syscall/syscall.c:333) → sys_read/sys_write → fileread/filewrite (kernel/fs/file.c:113/157)
2. fileread: 检查 f->readable==0 → -EPERM (kernel/fs/file.c:119-120)
3. filewrite: 检查 f->writable==0 → -EPERM (kernel/fs/file.c:163-164)
4. sys_faccessat: 基于 inode mode 位检查 (kernel/syscall/sysfile.c:789-820)
5. do_mmap: 检查 f->readable/f->writable 与 prot 匹配 (kernel/mm/mmap.c:720-724)

注意：无 UID/GID 检查链（sys_getuid 恒返回 0），无 check_perm/inode_permission 函数。

### Q07_005 是否实现用户指针验证（access_ok/verify_area/UserInPtr/copyin/copyout 等）？（必须三态）

已实现

### Q07_006 是否实现 seccomp/prctl/sandbox 等系统调用过滤/沙箱？（必须三态；stub 需说明形态：ENOSYS/return 0）

未发现

### Q07_007 是否存在栈保护/溢出防护（stack canary/guard page）或等价机制？（必须三态）

桩实现

### Q07_008 是否存在审计/安全启动（audit/secure boot/signature）相关逻辑？（必须三态）

未发现

### Q07_009 本项目支持哪些架构（riscv64/aarch64/x86_64/loongarch64 等）？每种架构的安全相关初始化（特权级配置、PMP/MPU/SMEP 等）是否有代码证据？（必须逐架构作答，无证据写「未发现」）

仅支持 riscv64 架构。

riscv64:
- 特权级隔离：通过 SSTATUS_SPP 位区分 U/S 模式 (include/hal/riscv.h:48)，usertrap/kerneltrap 分别断言进入来源 (kernel/trap/trap.c:75-76, 200-202)
- 用户内存访问控制：permit_usr_mem()/protect_usr_mem() 通过 SSTATUS_SUM (QEMU) 或 SSTATUS_PUM (K210) 位切换内核访问用户内存权限 (include/mm/vm.h:13-33)
- 页表保护：PTE_U 位控制用户可访问 (include/hal/riscv.h:387)，PTE_COW=PTE_RSW1 实现写时复制 (kernel/mm/vm.c:22)
- PMP：搜索 'PMP|pmp' 0 命中，未发现 PMP 配置代码
- KPTI：搜索 'KPTI|kpti' 0 命中，未实现内核/用户页表隔离

aarch64: 未发现。搜索 'aarch64' 0 命中。
x86_64: 未发现。搜索 'x86_64' 0 命中。
loongarch64: 未发现。搜索 'loongarch64' 0 命中。

### Q07_010 若项目使用 Rust，是否存在 RAII/所有权/生命周期相关的内核安全机制（如不可 unsafe 直接访问用户内存、锁的 RAII 自动释放等）？（必须三态；给具体模式证据）

未发现

### Q07_011 是否实现了内核/用户页表隔离 (Kernel/User Page Table Isolation, KPTI 或等价机制)？
（x86: CR3 KPTI / SMEP / SMAP；RISC-V: PMP / S-mode 分离；AArch64: TTBR0/TTBR1 隔离；
必须三态；无则写未发现并列出已搜关键字）

未发现

### Q07_012 UID/GID 字段是否在 syscall 路径上真实执行权限检查？（搜索 check_perm/inode_permission；若只有字段无检查链须标注「仅有定义但未强制执行 🔸」；给检查链证据或写「字段存在但无检查链」）

仅有定义但未强制执行 🔸。sys_getuid/sys_geteuid/sys_getgid/sys_getegid 全部返回 0 (kernel/syscall/sysproc.c:266-269)，struct proc 中无 uid/gid 字段 (include/sched/proc.h:51-170)。exec 中 AT_UID/AT_EUID/AT_GID/AT_EGID 硬编码为 0 (kernel/exec.c:241-244)。搜索 'check_perm|inode_permission|permission_check' 0 命中。文件访问控制仅依赖 file.readable/writable 标志和 inode mode 位，不涉及 UID/GID 比对。

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

无法追踪：该仓库不存在 sys_sendto 系统调用、无协议栈实现、无网卡驱动。syscalls[] 表中无任何网络相关 syscall（kernel/syscall/syscall.c:188-280），virtio.h 仅定义了 VIRTIO_MMIO_DEVICE_ID 中 '1 is net' 的注释（include/hal/virtio.h:21），但无 virtio-net 驱动实现文件。

### Q08_005 是否实现网卡驱动（virtio-net/e1000 等）与收包中断路径？（必须三态）

未发现

### Q08_006 协议支持情况（多选；未发现则留空并在 notes 写 not_found）：

[]

### Q08_007 是否存在零拷贝/共享缓冲/DMA 描述符等路径（zero-copy）？（必须三态；仅有名词不算 implemented）

未发现

---


# 第09章 调试机制与错误处理

### Q09_001 是否存在日志系统（log/printk/println 宏）与日志级别控制？（必须三态）

已实现

### Q09_002 是否存在 panic/崩溃处理路径（panic_handler/oom/abort 等）？（必须三态）

已实现

### Q09_003 panic 路径会输出哪些诊断？（寄存器 dump/栈回溯/停机；必须引用实现证据）

panic 路径输出：(1) 红色 [ERROR] 标签的 panic 消息；(2) 调用者传入的描述字符串；(3) 栈回溯 (backtrace) — 基于 r_fp (s0 寄存器) 的帧指针链遍历，打印每个栈帧的返回地址 (ra-4)；(4) 设置 panicked=1 冻结其他 CPU 的 UART 输出；(5) 关中断 (intr_off) 后进入无限循环 (for(;;);) 停机。panic 宏在调用 __panic 前还会额外打印 hart ID、__FILE__ 和 __LINE__。

### Q09_004 是否实现栈回溯 (backtrace/unwind/stack_trace)？（必须三态；仅打印 ra 不算）

已实现

### Q09_005 是否存在 **内核驻留的交互式监视器（kernel monitor）**？（对齐 Stallings《操作系统：精髓与设计原理》语境：**在内核态上下文**接受命令、用于探查/操控系统的监视器；**不包括**仅在用户态运行的常规 shell，如 `xv6-user/sh.c`、`user/` 下用户程序等——除非题面另有定义。必须三态；若 `implemented`：须给出 3–10 个 **用户可键入的 monitor 命令名** 及对应 **内核内** 解析/分发入口的 `路径:行号` 证据；仅以用户态 shell 充当内核 monitor 视为 **未切题** 应判 `stub` 或 `not_found` 并说明理由。）

已实现

### Q09_006 是否实现 GDB stub（需数据包解析循环，如 handle_gdb_packet）？（必须三态）

未发现

### Q09_007 错误码/错误类型体系是什么？（errno/Result/Error enum；给类型定义与传播点证据）

采用 POSIX errno 风格的整数错误码体系。定义于 include/errno.h，共 98 个宏 (EPERM=1 到 EAFNOSUPPORT=98)，涵盖文件系统 (ENOENT/EACCES/ENOSPC/EROFS 等)、进程 (ESRCH/ECHILD)、内存 (ENOMEM)、I/O (EIO/ENXIO)、网络 (ENOTSOCK/EPROTONOSUPPORT 等，但网络子系统未实现)。系统调用返回负 errno 值 (如 return -ENOENT)，用户态通过 trapframe->a0 获取。典型传播点：sys_openat (kernel/syscall/sysfile.c:194-267) 返回 -EBADF/-ENOENT/-EISDIR 等；console.c 读写路径返回 -EFAULT。

### Q09_008 是否存在 trace/perf/ftrace 等跟踪机制或 tracepoints？（必须三态）

桩实现

---


# 第10章 开发历史与里程碑

Now I have all the evidence needed. Let me compile the final chapter.

```json
{
  "schema_version": "v1",
  "stage_id": "10_history",
  "stage_title": "开发历史与里程碑",
  "terminology_profile": "stallings_en_zh",
  "answers": [
    {
      "question_id": "Q10_001",
      "question_type": "long_answer",
      "question_text": "开发历史与里程碑完整章节",
      "value": "## 第 10 章：开发历史与里程碑\n\n本章关注**部署与可运行性层**及**内核机制层**的演进轨迹，以 Git 提交历史为证据基础，分析 xv6-k210 从 MIT xv6-riscv 移植起点到最终交付的完整开发历程。证据类型包括 Git 提交记录、diff 摘要、文件演进追踪、作者贡献统计及文档交叉验证。\n\n### 10.1 项目概览与时间跨度\n\nxv6-k210 是华中科技大学 (HUST) OS 课程团队在 2021 年全国大学生操作系统大赛 (OSCOMP) 中的参赛项目。项目基于 MIT xv6-riscv 教学操作系统，将其从 QEMU virt 平台移植到 Kendryte K210 RISC-V 64 位双核开发板，并在此基础上进行了大量功能增强与重构。\n\n**时间跨度**：根据 `get_git_history_summary` 的 200 条提交记录，项目活跃期为 **2021-05-27 至 2021-08-21**（约 87 天），但首次提交 (SHA: `754610f2`) 的实际日期为 2020-10-19，表明前期有约 7 个月的独立移植准备期。整个仓库共约 466 条提交（含合并提交），其中 200 条摘要覆盖了从早期移植到最终冲刺的完整周期。\n\n**高频变更目录**（按提交摘要统计）：\n- `kernel/` — 绝对核心，几乎所有提交都涉及内核代码变更\n- `kernel/fs/` 及 `kernel/fs/fat32/` — 文件系统模块，后期密集迭代\n- `kernel/mm/` — 内存管理模块，经历多次重构\n- `kernel/sched/` — 调度器模块，经历从复杂状态机到简化设计的回退\n- `kernel/hal/` — 硬件抽象层，SD 卡驱动持续优化\n- `xv6-user/` — 用户态程序与测试框架\n- `doc/` — 文档丰富（30+ 篇），与代码同步更新\n- `Makefile` — 构建系统频繁调整（工具链切换、SBI 切换、平台切换）\n\n### 10.2 贡献者图谱与分工模式\n\n根据 `analyze_authors_contribution(days=9999)` 的输出，项目共有 **8 位贡献者**，但核心开发集中在 3 人：\n\n| 作者 | 提交数 | 总增删行数 | 主力模块 (Top-3) |\n|------|--------|-----------|-------------------|\n| **retrhelo** (刘一鸣) | 162 | +81,502 / -51,108 | kernel (98,752 行), tags, include |\n| **Lu Sitong** (陆思彤) | 146 | +45,475 / -27,776 | kernel (60,646 行), xv6-user, include |\n| **hustccc** (车春池) | 116 | +66,833 / -22,226 | tags (46,986 行), kernel, xv6-user |\n| YongkangLi (李永康) | 34 | +3,172 / -1,841 | kernel, doc |\n| Artyom Liu | 3 | +5,999 / -1,656 | kernel, bootloader, doc |\n| Sitong Lu | 2 | +1,924 / -3,623 | kernel, xv6-user |\n| Phoebas | 2 | +40 / -14 | xv6-user |\n| AtomHeartCoder | 3 | +2 / -1 | doc |\n\n**分工模式分析**：\n- **双核心驱动**：retrhelo 和 Lu Sitong 合计贡献了 308 次提交（约 66%），覆盖内核所有核心模块。这与 `doc/总言.md` 中描述的分工一致——刘一鸣负责调度器、信号机制、SD 卡驱动、SBI 开发；陆思彤负责文件系统 (VFS + FAT32)、内存管理 (COW/Lazy Allocation)、缺页处理。\n- **早期移植者**：hustccc (车春池) 的 116 次提交主要集中在项目早期（2020-10 至 2021-03），完成了从 xv6-riscv 到 K210 的基础移植工作（多核启动、虚拟内存、中断处理、SD 卡驱动框架），其贡献在 `doc/report_2020_12_26.md` 中有详细记录。\n- **专项贡献者**：YongkangLi 专注于 mmap 系统调用与用户空间管理；Artyom Liu 参与了 bootloader 和早期内核开发。\n- **协作模式**：项目采用 GitHub Fork + Merge Request 模式，存在多个并行分支（`ostest`、`signal`、`benchmark`、`sched`、`lazyload`、`scene`），通过频繁的合并保持同步。\n\n### 10.3 重大里程碑时间线\n\n基于 `find_symbol_first_commit`、`get_commit_diff_summary` 和 `get_git_history_summary` 的综合分析，梳理关键里程碑如下：\n\n#### 第一阶段：基础移植 (2020-10-19 ~ 2021-01-12)\n\n| 日期 | 提交 SHA | 里程碑事件 | 证据 |\n|------|----------|-----------|------|\n| 2020-10-19 | `754610f2` | **首次提交**：从 MIT xv6-riscv 移植的初始代码骨架。包含 `kernel/main.c`（多核启动框架）、`kernel/kalloc.c`（物理页分配器）、`kernel/entry_k210.S`（K210 入口）、`kernel/console.c`（SBI 控制台）、`kernel/printf.c`（格式化输出）、`kernel/riscv.h`（RISC-V CSR 操作宏）、`kernel/memlayout.h`（内存布局定义）、`kernel/defs.h`（全局函数声明）。构建系统使用 `riscv64-unknown-elf-` 工具链，链接脚本为 `linker/k210.ld`，SBI 层使用 RustSBI。 | `get_commit_diff_summary(754610f2)` |\n| 2020-11-01 | `01ec2b38` | **SD 卡驱动首次引入** (`sdcard` 符号出现) | `find_symbol_first_commit(\"sdcard\")` |\n| 2021-01-12 | `2aac809a` | **FAT32 文件系统引入（只读）**：这是项目最重大的架构转折之一。将 xv6 原生的 inode-based 文件系统替换为 FAT32。新增 `kernel/fat32.c`（约 600+ 行），实现了 FAT32 BPB 解析、簇链遍历 (`read_fat`)、目录项缓存 (`ecache`)、目录查找 (`lookup_dir`)。`kernel/exec.c` 中的 `exec()` 从 `namei()`/`readi()` 切换到 `get_entry()`/`eread()`。`kernel/bio.c` 中的缓冲区层从块号 (`blockno`) 改为扇区号 (`sectorno`)，通过 `disk_read()`/`disk_write()` 抽象接口统一了 virtio 和 SD 卡两种后端。构建系统新增 `fs.img` 磁盘镜像生成和 `userproc` 目标。工具链从 `riscv64-unknown-elf-` 切换到 `riscv64-linux-gnu-`。 | `get_commit_diff_summary(2aac809a)` |\n\n#### 第二阶段：系统调用与用户态扩展 (2021-05-27 ~ 2021-07-13)\n\n| 日期 | 提交 SHA | 里程碑事件 | 证据 |\n|------|----------|-----------|------|\n| 2021-05-27 | `5a0963ed` | **ostest 自测框架引入**：新增 `xv6-user/ostest.c` 和 `xv6-user/ostest_asm.S`，实现了自动运行 27 个测试用例的框架（覆盖 `brk`、`chdir`、`clone`、`close`、`dup`、`execve`、`exit`、`fork`、`fstat`、`getcwd`、`getdents`、`getpid`、`getppid`、`mkdir`、`mount`、`openat`、`open`、`pipe`、`read`、`umount`、`uname`、`unlink`、`wait`、`waitpid`、`write`、`yield`）。每个测试用例通过 `fork()` + `exec()` 独立运行。 | `get_commit_diff_summary(5a0963ed)` |\n| 2021-05-27 | `56ea7cdc` | **虚拟文件系统根 (VFS root)**：引入 VFS 层，支持将不同文件系统挂载到统一命名空间。 | `get_git_history_summary` |\n| 2021-05-28 | `7b854c6b` | **mmap 支持**：YongkangLi 和 Lu Sitong 协作实现 `mmap`/`munmap` 系统调用，支持文件映射和匿名映射。 | `get_git_history_summary` |\n| 2021-07-13 | `3e1d0165` | **busybox 启动**：这是用户态兼容性的重大里程碑。新增 `sys_writev`、`sys_readlinkat`、`sys_getuid`/`sys_geteuid`/`sys_getgid`/`sys_getegid`（桩实现，始终返回 0）、`sys_mprotect` 等系统调用。`exec()` 中新增 ELF 辅助向量 (aux vector) 支持，包括 `AT_PAGESZ`、`AT_PHDR`、`AT_PHENT`、`AT_PHNUM`、`AT_UID`、`AT_RANDOM` 等标准字段。`kernel/include/elf.h` 新增完整的 `AT_*` 宏定义。`uname` 版本号从 `\"v1.0\"` 改为 `\"5.0\"` 以兼容 busybox。 | `get_commit_diff_summary(3e1d0165)` |\n\n#### 第三阶段：内存管理深度重构 (2021-07-14 ~ 2021-08-16)\n\n| 日期 | 提交 SHA | 里程碑事件 | 证据 |\n|------|----------|-----------|------|\n| 2021-07-14 | `a3907ef4` | **Lazy ELF Load 机制**：实现了按需加载 ELF 程序段。`exec()` 不再在启动时加载所有程序段，而是仅记录段的文件偏移 (`f_off`) 和文件大小 (`f_sz`)，在缺页时通过 `handle_page_fault_loadelf()` 按需加载。`struct proc` 新增 `elf` 字段保存可执行文件的 inode 引用。`loadseg()` 函数重构为按需分配物理页并映射。`uvmprotect()` 新增页保护修改功能。`safememmove()` 重构为支持在缺页时触发 ELF 段加载。 | `get_commit_diff_summary(a3907ef4)` |\n| 2021-08-16 | `4e4d180e` | **物理内存分配器重构 (Single/Multiple 双池)**：将原有的单一空闲链表分配器重构为双池架构。`struct pm_allocator` 引入 `multiple`（多页分配器，用于 2+ 页的连续分配）和 `single`（单页分配器，用于 1 页分配）两个独立池。`START_SINGLE = PHYSTOP - 400 * PGSIZE` 定义了单页池的起始地址（预留 400 页）。`allocpage()` 优先从 single 池分配，失败时回退到 multiple 池。`allocpage_n()` 仅从 multiple 池分配。这种设计避免了多页分配时的外部碎片问题。 | `get_commit_diff_summary(4e4d180e)` |\n\n#### 第四阶段：调度器重构与信号机制 (2021-08-15 ~ 2021-08-17)\n\n| 日期 | 提交 SHA | 里程碑事件 | 证据 |\n|------|----------|-----------|------|\n| 2021-08-15 | `d3979764` | **调度器回退重构**：从复杂的多核占用状态机回退到简化的调度器设计。原有的 `__occupy(state)`/`__liberate(state)` 机制（将 hart ID 编码到进程状态的高 8 位）被移除，`procstate` 从 `uint64` 改为 `enum procstate { RUNNABLE, RUNNING, SLEEPING, ZOMBIE }`。`scheduler()` 不再通过 `enter_user()` 跳转到用户态，而是通过 `swtch()` 切换到目标进程的上下文。新增 `sched()` 函数作为统一的调度入口，包含浮点上下文保存/恢复 (`floatstore`/`floatload`)、时间统计 (`proc_tms`) 和中断使能状态管理。`yield()` 返回值从 `void` 改为 `int`（0 表示无其他可运行进程）。`swtch.S` 中移除了 `load_context` 函数。 | `get_commit_diff_summary(d3979764)` |\n| 2021-08-17 | `f6753c87` | **Signal 机制合并**：这是代码量最大的单次合并（+1345/-1279 行）。引入完整的 POSIX 信号机制，包括 `sigaction`、`sigprocmask`、`sighandle`、`SIGCHLD` 等。进程控制块新增 `killed` 字段从布尔值改为信号编号 (`SIGTERM`)。系统调用路径中新增信号检查，被中断的系统调用返回 `-EINTR`。`exit()` 中新增段清除 (`delsegs`) 和页表释放 (`uvmfree`)。`usertrap()` 中新增 `sighandle()` 调用路径。管道和 poll 机制中的 `wait_node` 从内核地址转换 (`kwalkaddr`) 改为直接使用栈上节点。 | `get_commit_diff_summary(f6753c87)` |\n\n#### 第五阶段：SBI 迁移与最终冲刺 (2021-08-08 ~ 2021-08-21)\n\n| 日期 | 提交 SHA | 里程碑事件 | 证据 |\n|------|----------|-----------|------|\n| 2021-08-08 | `8839ace` | **PsicaSBI 引入**：SBI 层从 RustSBI 迁移到自研的 PsicaSBI。`Makefile` 中 SBI 编译目标从 `cargo build` 改为 `cargo build --no-default-features --features=$(platform)`。SBI 调用接口从 Legacy SBI (`SBI_CALL_1` 等) 升级为 v0.2+ 标准的 EID/FID 格式 (`SBI_CALL(eid, fid, ...)`)。新增 `TIME_EID`、`IPI_EID`、`XV6_EID` 等扩展 ID。`sbi_send_ipi` 从单参数改为双参数 (`hart_mask` + `hart_mask_base`)。`sbi_set_timer` 返回值从 `void` 改为 `struct sbiret`。 | `get_commit_diff_summary(8839ace)` |\n| 2021-08-09 | `a4b0c38` | **PsicaSBI 完整移植**：统一链接脚本为 `linker/linker64.ld`（不再区分 k210/qemu）。统一入口点为 `kernel/entry.S`（不再区分 `entry_k210.S`/`entry_qemu.S`）。`KERNBASE` 不再通过 `#ifdef QEMU` 条件编译区分。SBI 头文件 `include/sbi.h` 完全重写，新增 `sbi_xv6_set_ext()`、`sbi_xv6_console_puts()`、`sbi_xv6_get_timer()` 等 xv6 专用扩展。`sbi_clear_ipi()` 改为直接操作 `sip` CSR 而非通过 SBI 调用。 | `get_commit_diff_summary(a4b0c38)` |\n| 2021-08-21 | `46437d1d` | **多核信号支持 (multihart)**：信号处理在多核环境下正确路由到对应 hart。 | `get_git_history_summary` |\n| 2021-08-21 | `d7f3e5e7` | **最终提交**：项目最后一条提交，标记开发周期结束。 | `get_git_history_summary` |\n\n### 10.4 核心模块演进轨迹\n\n#### 10.4.1 文件系统 (kernel/fs/)\n\n文件系统模块经历了从 xv6 原生 FS → FAT32（只读）→ FAT32（读写）→ VFS 抽象 → 异步 SD 卡写入的完整演进：\n\n1. **基线** (`754610f2`)：xv6 原生文件系统，含 `bio.c`（缓冲区缓存）、`fs.c`（inode 操作）、`file.c`（文件描述符表）、`log.c`（日志层），通过 `virtio_disk_rw()` 访问块设备。\n2. **FAT32 引入** (`2aac809a`, 2021-01-12)：新增 `kernel/fat32.c`，实现 FAT32 BPB 解析、簇链遍历、目录项缓存 (`ecache`)、8.3 短文件名 + 长文件名 (VFAT LFN) 支持。`bio.c` 重构为扇区号寻址。`exec.c` 从 inode 接口切换到 FAT32 目录项接口。\n3. **VFS 层** (`56ea7cdc`, 2021-05-27)：引入虚拟文件系统根，支持将 FAT32、设备文件系统挂载到统一命名空间。\n4. **FAT32 写入支持** (`9c1828ee`, 2021-08-18)：`kernel/fs/fat32/` 目录下的密集迭代（\"first blood\"、\"better improve\"、\"write_start\" 等提交），实现了 FAT 表写入 (`write_fat`)、簇分配 (`alloc_clus`)、目录项更新 (`eupdate`)。\n5. **异步 SD 卡写入** (`15cc513`, 2021-08-15)：实现非阻塞磁盘写机制，通过写回缓冲区减少 SD 卡写入延迟对系统的影响。\n6. **FAT 区域缓存** (`db9b955`, 2021-07-23)：新增 FAT 表缓存减少 SD 卡读取次数。\n\n`analyze_git_history(path_filter='kernel/fs')` 显示最后 30 条提交中有 15 条直接涉及 `kernel/fs/fat32/` 或 `kernel/fs/`，表明文件系统是项目后期最活跃的模块。\n\n#### 10.4.2 内存管理 (kernel/mm/)\n\n内存管理模块经历了从简单到复杂的多次重构：\n\n1. **基线** (`754610f2`)：`kernel/kalloc.c` 实现简单的空闲链表物理页分配器（`kalloc`/`kfree`），基于 xv6 原生设计。\n2. **kmalloc 引入** (`3f3ed61d`, 2021-04-25)：`kalloc.c` 重命名为 `pm.c`，新增 `kmalloc.c` 实现内核动态内存分配（小对象分配器），但初期未被使用。\n3. **COW Fork** (`eb77508`, 2021-05-04)：实现写时复制 (Copy-on-Write) 的 `fork()` 机制。\n4. **Lazy Allocation** (`3a452157`, 2021-07-15)：实现懒分配策略，用户栈和堆在缺页时才分配物理页。\n5. **Lazy ELF Load** (`a3907ef4`, 2021-07-14)：按需加载 ELF 程序段（见上文）。\n6. **Lazy mmap** (`27ca1f1`, 2021-07-29)：mmap 映射也采用懒分配策略。\n7. **双池分配器** (`4e4d180e`, 2021-08-16)：Single/Multiple 双池物理页分配器（见上文）。\n8. **页表映射优化** (`67fe53be`, 2021-08-21)：用户页表和内核页表共享内存存储，减少页表内存占用。\n\n`analyze_git_history(path_filter='kernel/mm')` 显示最后 30 条提交中 `kernel/mm/` 有 6 次显著变更，其中 `67fe53be` 单次变更 +260/-70 行。\n\n#### 10.4.3 调度器 (kernel/sched/)\n\n调度器模块经历了从 xv6 原始调度器 → 多核占用状态机 → 简化调度器的演进：\n\n1. **基线** (`754610f2`)：xv6 原生调度器，`scheduler()` 遍历进程表，`swtch()` 切换上下文。\n2. **多核占用状态机** (2021-07 期间)：引入 `__occupy(state)`/`__liberate(state)` 机制，将 hart ID 编码到进程状态中，实现多核间的进程占用标记。`enter_user()` 函数作为调度器到用户态的跳转入口。\n3. **回退重构** (`d3979764`, 2021-08-15)：移除多核占用状态机，恢复简化的 `enum procstate`。`scheduler()` 不再通过 `enter_user()` 跳转，改为通过 `swtch()` 直接切换。新增 `sched()` 统一调度入口，集成浮点上下文管理 (`floatstore`/`floatload`) 和进程时间统计 (`proc_tms`)。`yield()` 增加返回值指示是否有其他可运行进程。\n4. **信号集成** (`f6753c87`, 2021-08-17)：调度器与信号机制深度集成，`exit()` 中新增段清除和页表释放。\n\n`analyze_git_history(path_filter='kernel/sched')` 显示最后 30 条提交中 `kernel/sched/` 有 7 次变更，集中在信号和多核支持的集成。\n\n#### 10.4.4 硬件抽象层 (kernel/hal/)\n\n硬件抽象层是 K210 平台适配的核心，包含以下驱动的演进：\n\n1. **PLIC 中断控制器** (`754610f2`)：基线包含 `plicinit()`/`plicinithart()`/`plic_claim()`/`plic_complete()`。\n2. **UART 串口** (`754610f2`)：基线包含 `uartinit()`/`uartputc()`/`uartgetc()`。\n3. **Virtio 磁盘** (`754610f2`)：基线包含 `virtio_disk_init()`/`virtio_disk_rw()`，用于 QEMU 平台。\n4. **SD 卡驱动** (`01ec2b38`, 2020-11-01)：K210 平台的 SD 卡驱动，通过 SPI 模式访问。\n5. **FPIOA (现场可编程 IO 阵列)**：K210 特有的引脚映射控制器。\n6. **DMAC (DMA 控制器)**：用于 SD 卡数据的高速传输。\n7. **SD 卡驱动持续优化** (2021-08-18 ~ 2021-08-21)：最后 4 天内有 10+ 条提交涉及 SD 卡驱动的改进（\"sdcard improve\"、\"better read\"、\"change sdcard\"、\"sdcard rate\" 等），包括超时调整、读取性能优化、外部中断处理修复。\n\n`analyze_git_history(path_filter='kernel/hal')` 显示最后 30 条提交中有 16 条涉及 `kernel/hal/`，是项目最后阶段最密集迭代的模块。\n\n#### 10.4.5 系统调用层 (kernel/syscall/)\n\n系统调用数量从 xv6 原生的约 20 个增长到支持 busybox 所需的 50+ 个：\n\n- **基线** (`754610f2`)：xv6 原生系统调用（`fork`、`exec`、`exit`、`wait`、`read`、`write`、`open`、`close`、`pipe`、`kill`、`fstat`、`chdir`、`dup`、`getpid`、`sbrk`、`sleep`、`uptime`、`mkdir`、`mknod`、`link`、`unlink`）。\n- **mmap/munmap** (`7b854c6b`, 2021-05-28)：内存映射系统调用。\n- **信号系统调用** (`9759082`, 2021-07-17)：`sigaction`、`sigprocmask`、`sigreturn`。\n- **busybox 兼容** (`3e1d0165`, 2021-07-13)：`writev`、`readlinkat`、`getuid`/`geteuid`/`getgid`/`getegid`（桩实现）、`mprotect`。\n- **ppoll** (`c417322f`, 2021-07-16)：为运行 shell 脚本实现的 `ppoll` 系统调用。\n- **renameat2** (`95eec864`, 2021-07-18)：文件重命名系统调用。\n- **adjtimex/prlimit** (`c8ba3cf8`, 2021-07-18)：时间调整和资源限制（伪实现）。\n- **exit_group** (`a3907ef4`, 2021-07-14)：线程组退出。\n\n`analyze_git_history(path_filter='kernel/syscall')` 显示最后 30 条提交中仅有 3 次涉及系统调用层，表明系统调用接口在项目中后期已趋于稳定。\n\n#### 10.4.6 Trap 处理 (kernel/trap/)\n\nTrap 处理模块的演进主要体现在：\n\n1. **基线** (`754610f2`)：`usertrap()`/`kerneltrap()` 框架，`devintr()` 设备中断分发。\n2. **S 态外部中断代理** (2020-12 ~ 2021-03)：通过 RustSBI 的 `sbi_set_extern_interrupt()` 接口注册 S 态处理函数，解决 K210 无 S 态外部中断的硬件限制。\n3. **缺页处理增强** (`a3907ef4`, 2021-07-14)：`handle_page_fault()` 新增指令缺页 (`EXCP_INST_PAGE`) 和指令访问异常 (`EXCP_INST_ACCESS`) 的处理，支持 lazy ELF load。\n4. **信号集成** (`f6753c87`, 2021-08-17)：`usertrap()` 中新增 `sighandle()` 调用，在返回用户态前检查并处理待决信号。\n5. **PsicaSBI 适配** (`a4b0c38`, 2021-08-09)：外部中断注册从 `sbi_set_mie()` 改为 `sbi_xv6_set_ext()`。\n\n`analyze_git_history(path_filter='kernel/trap')` 显示最后 30 条提交中仅有 4 次涉及 trap 模块，表明该模块在项目后期相对稳定。\n\n### 10.5 构建系统演进\n\n`trace_file_evolution('Makefile')` 揭示了构建系统的关键变更：\n\n1. **工具链切换**：`riscv64-unknown-elf-` → `riscv64-linux-gnu-` (`2aac809a`) → 回退到 `riscv64-unknown-elf-` (`a7ffc31`) → 最终使用 `riscv64-unknown-elf-`。\n2. **SBI 切换**：RustSBI 二进制直接链接 (`b7def1f6`) → RustSBI 子模块编译 (`8839ace` 之前) → PsicaSBI 子模块编译 (`8839ace`)。\n3. **平台统一**：`k210.ld` + `qemu.ld` 双链接脚本 → 统一 `linker64.ld` (`a4b0c38`)。`entry_k210.S` + `entry_qemu.S` 双入口 → 统一 `entry.S` (`a4b0c38`)。\n4. **调试支持**：新增 `mode=debug` 条件编译和模块级调试开关 (`d3979764`)。\n5. **用户程序构建**：从硬编码用户程序列表 → `UPROGS` 变量 → 支持 `make userprogs` 单独构建。\n6. **文件系统镜像**：新增 `make fs` 生成 FAT32 磁盘镜像，`make sdcard` 拷贝用户程序到 SD 卡。\n\n### 10.6 启动流程演进\n\n`trace_file_evolution('kernel/main.c')` 揭示了启动流程的关键变化：\n\n1. **基线** (`754610f2`)：`main()` 接收 `hartid` 和 `dtb_pa` 参数，hart 0 执行初始化序列（`consoleinit` → `printfinit` → `kinit` → `kvminit` → `kvminithart` → `procinit` → `trapinit` → `trapinithart` → `plicinit` → `plicinithart` → `binit` → `iinit` → `fileinit` → `virtio_disk_init` → `userinit`），其他 hart 等待 `started` 标志后执行 `kvminithart`/`trapinithart`/`plicinithart`，最后进入 `scheduler()`。\n2. **FAT32 适配** (`2aac809a`)：`iinit()` 替换为 `fat32_init()`，`virtio_disk_init()` 替换为 `disk_init()`。\n3. **kmalloc 引入** (`3f3ed61d`)：新增 `kmallocinit()` 调用。\n4. **浮点支持** (`40d247f`, 2021-08-05)：新增浮点单元初始化。\n5. **双核启用** (`013439e`, 2021-08-08)：修复多核启动的竞态条件。\n6. **PsicaSBI 适配** (`8839ace`/`a4b0c38`)：IPI 发送接口从 `sbi_send_ipi(&mask)` 改为 `sbi_send_ipi(mask, 0)`，增加错误检查。\n7. **调度器重构** (`d3979764`)：移除 `enter_user()` 调用，改为 `scheduler()` 直接调度。\n8. **多核信号** (`46437d1d`/`f92fd63b`, 2021-08-21)：信号处理与 hart 绑定。\n\n### 10.7 文档与代码同步\n\n`analyze_git_history(path_filter='doc')` 显示文档提交与代码提交高度同步：\n\n- `doc/` 目录包含 30+ 篇设计/调试文档，涵盖内核原理、系统调用、内存分配器、IO 策略、信号机制等。\n- 关键文档提交与代码里程碑对齐：\n  - `d41d58b8` (2021-05-28)：新增 kmalloc 文档\n  - `1ff41581` (2021-05-28)：新增 mmap 文档\n  - `5b6b717e` (2021-08-17)：批量更新文档 (+252 行)\n  - `9331e6eb` (2021-08-18)：更新文档 (+138 行)\n- `doc/总言.md` 提供了完整的项目架构说明、开发计划和分工描述，与代码实际高度一致。\n- `doc/report_2020_12_26.md` 和 `doc/xv6-k210-report-车春池.md` 记录了早期移植阶段的技术细节（K210 与 QEMU 差异、RustSBI 黑科技、S 态外部中断代理）。\n\n### 10.8 当前缺口与未完成特性\n\n#### 10.8.1 README 中的 TODO\n\n`README.md` 和 `README_cn.md` 的 Progress 段列出了 12 项已完成特性（多核启动、裸机 printf、内存分配、页表、时钟中断、S 态外部中断、UARTHS 串口、SD 卡驱动、进程管理、文件系统、用户程序、键盘输入），TODO 段仅写 \"See Issues\"，未列出具体未完成项。\n\n#### 10.8.2 代码中的 TODO/FIXME\n\n`grep_in_repo('TODO|FIXME|HACK|XXX', file_extensions='c,h')` 仅命中 4 条：\n- `kernel/mm/vm.c:613`：`uvmprotect()` 中的 TODO 注释，关于保护未生效页面的边界情况处理。\n- `xv6-user/test.c:5`：测试字符串 `\"env1=xxx\"`（非 TODO）。\n- `xv6-user/usertests.c:360`：测试代码中的 `\"xxx\"` 字符串（非 TODO）。\n- `xv6-user/usertests.c:428`：注释 \"needs a hacked kernel\"（非 TODO）。\n\n这表明代码中几乎没有遗留的未完成标记，项目在交付时达到了较高的完成度。\n\n#### 10.8.3 已知缺口\n\n基于前文各章的分析，以下特性在代码中未实现或仅为桩实现：\n\n1. **网络子系统**：完全未实现（第 8 章已确认）。\n2. **UID/GID 权限检查**：`sys_getuid()` 等始终返回 0，无实际凭证系统（第 7 章已确认）。\n3. **`sys_readlinkat`**：仅硬编码返回 `\"/home/busybox\"`，非通用实现（`kernel/sysfile.c`）。\n4. **`sys_adjtimex`/`sys_prlimit`**：标注为 \"psedo-finish\"（`c8ba3cf8` 提交消息）。\n5. **多核调度**：最终版本支持多核 (multihart)，但调度器采用简化设计，无负载均衡或 CPU affinity。\n6. **设备驱动**：仅支持 virtio 块设备 (QEMU) 和 SD 卡 (K210)，无网络设备驱动、无 USB 驱动、无显示驱动。\n\n#### 10.8.4 CI/CD 基础设施\n\n`grep_in

---


---

*本报告由 OS-Agent-D 自动生成*  
*生成时间: 2026-04-30 22:11:06*  
*分析耗时: 140.0 分钟*
