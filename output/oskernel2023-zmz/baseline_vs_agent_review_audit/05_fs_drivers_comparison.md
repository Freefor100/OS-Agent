# 05_fs_drivers — Baseline vs Agent

- 题库题数: 35
- baseline `report_quality_score`: 0.99
- agent `report_quality_score`: 0.92

| question_id | type | agreement | better_side(初值) | baseline_se | baseline_sc | agent_se | agent_sc | baseline_value | agent_value |
|---|---|:---|:---|---:|---:|---:|---:|---|---|
| Q05_001 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.85 | 1.00 | C 操作表 (C operation table)。VFS 使用 C 语言的结构体包含函数指针来定义接口，包括 struct fs_op、struct inode_op、struct dentry_op、struct file_op。 | C 语言函数指针操作表（op 表）形态。证据：`include/fs/fs.h:43-68` 定义了 `struct fs_op`（超级块操作）、`struct inode_op`（索引节点操作）、`struct dentry_op`（目录项操作）、`struct file_op`（文件操作）四个操作表结构体，每个包含函数指针成员如 `alloc_inode`、`create`、`lookup`、`read`、`write` 等。... |
| Q05_002 | single_choice | 一致 | tie | 0.90 | 1.00 | 0.85 | 1.00 | A. 真实磁盘文件系统（FAT32/Ext4/其他，持久化存储） | 真实磁盘文件系统（FAT32/Ext4/其他，持久化存储） |
| Q05_003 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 0.85 | 1.00 | 自研实现。FAT32 文件系统代码位于 kernel/fs/fat32/目录下，是内核源码的一部分，没有通过 Cargo.toml 或 Makefile 引入第三方库。 | 自研实现。证据：`kernel/fs/fat32/` 目录下包含完整的 FAT32 实现文件（`fat32.c`、`fat.c`、`dirent.c`、`cluster.c`、`fat32.h`），无第三方库依赖。项目为纯 C 语言内核（非 Rust），`Cargo.toml` 仅用于 SBI 固件（`sbi/psicasbi/Cargo.toml`），内核构建使用 `Makefile`（行 1-294）直接编译 `kernel/... |
| Q05_004 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 0.85 | 1.00 | 1. sys_openat (kernel/syscall/sysfile.c) → 2. nameifrom (kernel/fs/fs.c) → 3. lookup_path (kernel/fs/fs.c) → 4. dirlookup (kernel/fs/fs.c) → 5. fat_lookup_dir (kernel/fs/fat32/dirent.c) → 6. filealloc/fdalloc (kernel/... | 文件打开调用链：1. `sys_openat` (`kernel/syscall/sysfile.c:253`) → 2. `nameifrom`/`create` (`kernel/fs/fs.c:473`/`kernel/fs/fs.c:24`) → 3. `lookup_path` (`kernel/fs/fs.c:412`) → 4. `dirlookup` (`kernel/fs/fs.c:319`) → 5. `fat... |
| Q05_005 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 0.85 | 1.00 | 固定数组。struct fdtable 使用固定大小的数组 struct file *arr[NOFILE]，其中 NOFILE=16 定义在 param.h 中。 | 固定数组 + 链表扩展形态。证据：`include/fs/file.h:29-37` 定义 `struct fdtable` 包含 `struct file *arr[NOFILE]` 固定大小数组（NOFILE 为常量），并通过 `struct fdtable *next` 指针支持多表链表扩展。`kernel/fs/file.c:434-470` 的 `fdalloc` 函数实现：当当前表满时（`nextfd == NOFIL... |
| Q05_006 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_007 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.85 | 1.00 | LRU (Least Recently Used)。通过 lru_head 双向链表实现，最近使用的 buffer 移到链表头部，驱逐时从尾部获取。bget() 中从 lru_head.prev 获取最久未使用的 buffer。 | LRU（最近最少使用）策略。证据：`kernel/fs/bio.c:84-147` 的 `bget` 函数实现：1. 使用 `d_list lru_head`（行 69）作为 LRU 链表，未使用缓冲在链表尾部；2. 缓存命中时将缓冲移到链表头部（行 105-109：`_list_remove` + `_list_push_front`）；3. 驱逐时从链表尾部获取（行 122-132：`lru_head.prev`），符合 LR... |
| Q05_008 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_009 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_010 | tri_state_impl | 结论冲突 | 待核验 | 1.00 | 1.00 | 0.85 | 1.00 | implemented | stub |
| Q05_011 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_012 | tri_state_impl | 结论冲突 | 待核验 | 1.00 | 1.00 | 0.85 | 1.00 | not_found | stub |
| Q05_013 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_014 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | not_found | not_found |
| Q05_015 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_016 | single_choice | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | A. Per-Process（每进程独立 fd 表，fork 时复制/共享） | Per-Process（每进程独立 fd 表，fork 时复制/共享） |
| Q05_017 | single_choice | 结论冲突 | 待核验 | 0.95 | 1.00 | 0.85 | 0.40 | B. 链式分配 (Chained/Linked Allocation)：块通过指针链接 | FAT 表内嵌空闲链（FAT32 特有） |
| Q05_018 | single_choice | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | E. FAT 表内嵌空闲链（FAT32 特有） | FAT 表内嵌空闲链（FAT32 特有） |
| Q05_019 | single_choice | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | C. 树形层次目录 (Tree-Structured Hierarchy)（最常见） | 树形层次目录 (Tree-Structured Hierarchy)（最常见） |
| Q05_020 | single_choice | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | A. 字节流 (Byte Stream / Unstructured)：无固定记录结构 | 字节流 (Byte Stream / Unstructured)：无固定记录结构 |
| Q05_021 | single_choice | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | C. 硬编码设备表/固定 MMIO 地址 | 硬编码设备表/固定 MMIO 地址 |
| Q05_022 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | not_found | not_found |
| Q05_023 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 0.85 | 1.00 | C 函数接口。驱动通过直接调用 C 函数实现，没有统一的 driver ops 表或注册机制。每个驱动模块（uart, disk, plic 等）有独立的初始化函数。 | C 语言直接初始化模式，无统一驱动框架接口。证据：`kernel/hal/` 目录下各驱动（`virtio_disk.c`、`sdcard.c`、`plic.c`）均通过独立的 `*_init` 函数直接初始化（如 `virtio_disk_init`、`sdcard_init`、`plicinit`），无 `driver_ops` 结构体或注册表机制。`kernel/main.c:60-66` 直接顺序调用 `disk_init... |
| Q05_024 | short_answer | 表述差异 | 待酌 | 1.00 | 0.85 | 0.85 | 1.00 | 1. cpuinit() → 2. consoleinit() → 3. kpminit() → 4. kvminit() → 5. trapinithart() → 6. plicinit() → 7. disk_init() → 8. binit()。在 kernel/main.c 的 main() 函数中按固定顺序初始化。 | 无驱动注册机制，采用硬编码顺序初始化。关键节点：1. `plicinit` (`kernel/hal/plic.c:20`) → 2. `plicinithart` (`kernel/hal/plic.c:33`) → 3. `disk_init` (`kernel/hal/disk.c`) → 4. `binit` (`kernel/fs/bio.c:84`) → 5. `rootfs_init` (`kernel/fs/roo... |
| Q05_025 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_026 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_027 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | not_found | not_found |
| Q05_028 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |
| Q05_029 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 0.85 | 1.00 | 常量硬编码。MMIO 地址在 include/memlayout.h 中定义为宏常量，根据平台 (QEMU/k210) 使用条件编译选择不同值。 | 常量硬编码 + 物理→虚拟转换。证据：`include/memlayout.h:40-68` 硬编码物理地址（如 `UART 0x10000000/0x38000000`、`VIRTIO0 0x10001000`、`PLIC 0x0c000000`），并通过 `*_V` 宏（如 `UART_V = UART + VIRT_OFFSET`，`VIRT_OFFSET=0x3F00000000L`）转换为虚拟地址。`kernel/mm/... |
| Q05_030 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 0.85 | 1.00 | Makefile 条件编译。通过 platform 变量 (k210/qemu) 控制，使用 #ifdef QEMU / #ifndef QEMU 条件编译选择不同驱动代码。 | Makefile 平台宏 + `#ifdef QEMU` 条件编译。证据：`Makefile:1-2` 通过 `platform := k210` 或 `platform := qemu` 选择平台，行 34-36 添加 `-D QEMU` 编译标志。`include/memlayout.h:40-45` 使用 `#ifdef QEMU` 区分 UART 地址（QEMU: 0x10000000，K210: 0x38000000）。... |
| Q05_031 | tri_state_impl | 结论冲突 | 待核验 | 1.00 | 1.00 | 0.85 | 1.00 | not_found | implemented |
| Q05_032 | single_choice | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | D. 缓冲池 (Buffer Pool) | 缓冲池 (Buffer Pool) |
| Q05_033 | single_choice | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | A. FCFS（先来先服务 First-Come First-Served） | FCFS（先来先服务 First-Come First-Served） |
| Q05_034 | single_choice | 结论冲突 | 待核验 | 0.90 | 1.00 | 0.85 | 1.00 | D. 混合（小传输用中断，大传输用 DMA） | 中断驱动 I/O (Interrupt-Driven I/O)：设备完成后发中断通知 CPU |
| Q05_035 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.85 | 1.00 | implemented | implemented |

统计: 一致=21, 表述差异=9, 结论冲突=5
