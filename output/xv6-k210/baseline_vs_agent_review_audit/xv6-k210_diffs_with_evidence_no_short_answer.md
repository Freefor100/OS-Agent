# xv6-k210

（由 `diffs_with_evidence.json` 生成；已排除 `short_answer`，保留 25 / 82 题；选择题已附备选项）

## 02_boot_trap — 启动/架构与 Trap/系统调用

### `Q02_007` · `fill_in`

### 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）： - BSS 清零 (BSS Clearing): ___ - 早期串口输出 (Early Serial/UART Output): ___ - 设备树解析 (Device Tree Blob parsing, DTB): ___ - 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | BSS 清零 (BSS Clearing): implemented [linker/linker64.ld:53-56 .bss 段定义，链接器自动处理]<br>早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:consoleinit() + sbi_console_putchar 通过 SBI 调用]<br>设备树解析 (Device Tree Blob parsing, DTB): not_found [main.c 接收 dtb_pa 参数但未显式解析 DTB]<br>页表初始化时机 (Page Table Init): implemented [kernel/mm/vm.c:kvminit() 在 kvminithart() 之前，MMU 启用前建立映射] | BSS 清零 (BSS Clearing): implemented [bootloader/SBI/rustsbi-k210/src/main.rs]<br>早期串口输出 (Early Serial/UART Output): implemented [bootloader/SBI/rustsbi-k210/src/main.rs]<br>设备树解析 (Device Tree Blob parsing, DTB): implemented [bootloader/SBI/rustsbi-qemu/src/main.rs]<br>页表初始化时机 (Page Table Init): 在 MMU 启用前 [kernel/mm/vm.c] |
| **证据** | [1] `linker/linker64.ld` · .bss<br><code>.bss : { sbss_clear = .; *(.sbss .bss .bss.*) ebss_clear = .; }</code><br>[2] `kernel/console.c` · consoleinit<br><code>void consoleinit() { ... sbi_console_putchar ... }</code><br>[3] `kernel/main.c` · main<br><code>void main(unsigned long hartid, unsigned long dtb_pa) { ... }</code><br>[4] `kernel/mm/vm.c` · kvminit<br><code>void kvminit() { ... kvmmap(...) ... } // 在 kvminithart 之前调用</code> | [1] `bootloader/SBI/rustsbi-k210/src/main.rs` · main<br><code>r0::zero_bss(&amp;mut _sbss, &amp;mut _ebss); r0::init_data(...)</code><br>[2] `bootloader/SBI/rustsbi-k210/src/main.rs` · main<br><code>let serial = p.UARTHS.configure(115_200.bps(), &amp;clocks);</code><br>[3] `bootloader/SBI/rustsbi-qemu/src/main.rs` · main<br><code>let dtb_pa = ...; if let Ok(dt) = DeviceTree::load(data)</code><br>[4] `kernel/mm/vm.c` · kvminit<br><code>kvminit() creates page table before kvminithart() enables MMU via w_satp()</code> |

### `Q02_027` · `fill_in`

### Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写： - 分发表路径: ___ - 完整实现 ✅ (implemented): ___ 个 - 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___ - 未注册 ❌ (not_found): ___ 个 - 统计依据（grep 或 outline 方式）: ___ （若无法精确计数，给出区间估计并说明理由）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | 分发表路径：kernel/syscall/syscall.c:194-258 (syscalls[] 数组)<br>完整实现 ✅ (implemented): 约 55 个 (sys_fork, sys_exec, sys_write, sys_read, sys_openat, sys_mmap, sys_clone, sys_wait4 等有完整逻辑)<br>桩/ENOSYS/return 0 🔸 (stub): 约 5 个，代表性例子：sys_getuid (仅返回 0), sys_geteuid (指向 sys_getuid), sys_getgid (指向 sys_getuid), sys_getegid (指向 sys_getuid), sys_prlimit64 (仅返回 0)<br>未注册 ❌ (not_found): 0 个 (所有 SYS_* 常量都在 syscalls[] 中有注册，即使是指向桩函数)<br>统计依据：grep kernel/syscall/syscall.c 的 syscalls[] 数组，共 68 个条目；逐个检查 sys_*.c 文件中的实现体深度 | 分发表路径：kernel/syscall/syscall.c (syscalls[] 数组)<br>完整实现 ✅ (implemented): 约 50+ 个<br>桩/ENOSYS/return 0 🔸 (stub): 少数几个，如 sys_prlimit64 return 0<br>未注册 ❌ (not_found): 约 10-15 个（sysnum.h 中定义但未在 syscalls[] 中注册）<br>统计依据（grep 或 outline 方式）: 对比 include/sysnum.h 中 SYS_* 定义与 kernel/syscall/syscall.c 中 syscalls[] 数组索引 |
| **证据** | [1] `kernel/syscall/syscall.c` · syscalls[]<br><code>static uint64 (*syscalls[])(void) = { [SYS_fork] sys_fork, ... [SYS_msync] sys_msync }; // 共 68 个条目</code><br>[2] `kernel/syscall/sysproc.c` · sys_getuid<br><code>uint64 sys_getuid(void) { return 0; }</code> | [1] `include/sysnum.h` · SYS_*<br><code>#define SYS_fork 1 ... #define SYS_msync 227 (约 70+ syscall numbers defined)</code><br>[2] `kernel/syscall/syscall.c` · syscalls<br><code>static uint64 (*syscalls[])(void) = { [SYS_fork] sys_fork, ... [SYS_msync] sys_msync };</code><br>[3] `kernel/syscall/sysproc.c` · sys_prlimit64<br><code>uint64 sys_prlimit64(void) { return 0; } // stub implementation</code> |

## 03_mem_mgmt — 内存管理（物理/虚拟/分配器）

### `Q03_016` · `tri_state_impl`

### 是否存在 Page Cache（页缓存/文件页缓存）管理？（必须三态）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | stub |
| **证据** | [1] `kernel/fs/bio.c` · bio.c<br><code>Buffer cache 实现，使用 struct buf 缓存磁盘块，LRU 链表管理</code><br>[2] `kernel/fs/bio.c` · bcache<br><code>static list_node_t *bcache[BCACHE_TABLE_SIZE] 哈希表</code><br>[3] `kernel/fs/bio.c` · lru_head<br><code>static struct d_list lru_head LRU 链表头</code> | [1] `kernel/fs/buf.c` · buf<br><code>struct buf with LRU list and hash table for block caching, but this is block cache not page cache</code><br>[2] `kernel/mm/mmap.c` · mmap_page<br><code>struct mmap_page for tracking mapped file pages with ref count, but limited to mmap not general page cache</code><br>[3] `kernel/fs` · page_cache_search<br><code>No general page cache implementation like Linux page_cache, only buffer cache for disk blocks</code> |

### `Q03_017` · `tri_state_impl`

### 是否存在脏页回写 (dirty page writeback) 机制？（必须三态；若 implemented 需指出同步/异步与触发条件）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | stub |
| **证据** | [1] `kernel/fs/bio.c` · bwrite<br><code>行 199，异步写回：disk_submit() 提交到磁盘驱动队列，不等待完成</code><br>[2] `kernel/fs/bio.c` · dirty_buffer_writeback<br><code>注释说明：Dirty buffer write back no-block mechanism，异步提交到磁盘驱动</code> | [1] `kernel/fs/buf.c` · bwrite<br><code>void bwrite(struct buf *b) - writes dirty buffer to disk, but this is block-level not page-level</code><br>[2] `kernel/mm/mmap.c` · do_msync<br><code>int do_msync(uint64 addr, uint64 len, int flags) - syncs mmap&#x27;d pages to file, triggered by msync() syscall</code><br>[3] `kernel/fs` · writeback_search<br><code>No background writeback daemon or periodic dirty page writeback found</code> |

### `Q03_023` · `fill_in`

### 物理内存总量（Physical Memory Size）：____ KB/MB；页大小（Page Size）：____ bytes；最大进程虚拟地址空间（Virtual Address Space）：____ bits。（必须从代码常量/链接脚本/配置中给出证据；无法确定则写 unknown 并说明已搜路径）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | 物理内存总量：6 MB（PHYSTOP 0x80600000 - KERNBASE 0x80020000 ≈ 6MB）；页大小：4096 bytes（PGSIZE）；最大进程虚拟地址空间：39 bits（Sv39，MAXVA = 1L << (9+9+9+12-1) = 2^38，实际可用 38 位，但 Sv39 支持 39 位虚拟地址）。 | 物理内存总量：4 MB (PHYSTOP 0x80600000 - KERNBASE 0x80020000)；页大小：4096 bytes；最大进程虚拟地址空间：39 bits (Sv39) |
| **证据** | [1] `include/memlayout.h` · PHYSTOP<br><code>#define PHYSTOP 0x80600000UL 行 102</code><br>[2] `include/memlayout.h` · KERNBASE<br><code>#define KERNBASE 0x80020000UL 行 99</code><br>[3] `include/hal/riscv.h` · PGSIZE<br><code>#define PGSIZE 4096 行 378</code><br>[4] `include/hal/riscv.h` · MAXVA<br><code>#define MAXVA (1L &lt;&lt; (9 + 9 + 9 + 12 - 1)) 行 408</code> | [1] `include/memlayout.h` · PHYSTOP<br><code>#define PHYSTOP 0x80600000UL - end of physical memory</code><br>[2] `include/memlayout.h` · KERNBASE<br><code>#define KERNBASE 0x80020000UL - kernel base address</code><br>[3] `include/hal/riscv.h` · PGSIZE<br><code>#define PGSIZE 4096 - page size in bytes</code><br>[4] `include/hal/riscv.h` · MAXVA<br><code>#define MAXVA (1L &lt;&lt; (9 + 9 + 9 + 12 - 1)) - Sv39 39-bit virtual address space</code><br>[5] `linker/linker64.ld` · memory_layout<br><code>BASE_ADDRESS = 0x80020000 - kernel load address matches KERNBASE</code> |

### `Q03_034` · `tri_state_impl`

### 是否存在清理策略 (Cleaning Policy, Stallings Ch8.2)？（即脏页预先后台写回，而非仅在置换时才写回；搜索 background writeback / kswapd / cleaner_thread 或等价；必须三态；若 not_found 需列出已搜关键字）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | not_found |
| **证据** | [1] `kernel/fs/bio.c` · bwrite<br><code>异步写回机制：disk_submit() 提交到磁盘驱动队列，不等待完成 行 199</code><br>[2] `kernel/fs/bio.c` · dirty_writeback<br><code>注释：Dirty buffer write back no-block mechanism，异步提交</code> | [1] `kernel` · writeback_search<br><code>Searched for background_writeback, kswapd, cleaner_thread, pdflush keywords - none found</code><br>[2] `kernel/fs/buf.c` · bsync<br><code>void bsync(void) - synchronous buffer write, not background writeback daemon</code><br>[3] `kernel/mm/mmap.c` · do_msync<br><code>Triggered by msync() syscall, not automatic background cleaning</code> |

## 04_process_smp — 进程/线程/调度与多核

### `Q04_018` · `tri_state_impl`

### 是否实现 POSIX 资源限制（rlimit/RLIMIT/getrlimit/setrlimit）？（必须三态；若 implemented 需说明支持的资源类型数量及软/硬限制机制）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | stub | not_found |
| **证据** | [1] `kernel/syscall/sysproc.c` · sys_prlimit64<br><code>uint64 sys_prlimit64(void) { // for now it&#x27;s not very necessary to implement this syscall // may be implemented later return 0; }</code> | [1] `include/sysnum.h` · rlimit<br><code>在 include/sysnum.h 中未找到 SYS_getrlimit, SYS_setrlimit 等系统调用号</code><br>[2] `kernel/syscall/` · rlimit<br><code>在 kernel/syscall/ 目录中未找到 rlimit 相关实现</code> |

### `Q04_023` · `multi_choice`

### 调度器是否追踪/优化以下哪些性能指标 (Scheduling Criteria, Stallings Ch9)？（多选；未发现则留空并在 notes 写 not_found）

**备选项：**

- **A.** CPU 利用率 (CPU Utilization)
- **B.** 吞吐量 (Throughput)
- **C.** 周转时间 (Turnaround Time)
- **D.** 等待时间 (Waiting Time)
- **E.** 响应时间 (Response Time)
- **F.** 未发现调度性能统计

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | ["CPU 利用率 (CPU Utilization)", "周转时间 (Turnaround Time)", "等待时间 (Waiting Time)", "响应时间 (Response Time)"] | ["F. 未发现调度性能统计"] |
| **证据** | [1] `include/sched/proc.h` · tms<br><code>struct tms { uint64 utime; uint64 stime; uint64 cutime; uint64 cstime; };</code><br>[2] `include/sched/proc.h` · proc<br><code>int64 vswtch; int64 ivswtch;</code><br>[3] `kernel/syscall/sysproc.c` · sys_getrusage<br><code>r.ru_nvcsw = p-&gt;vswtch; r.ru_nivcsw = p-&gt;ivswtch;</code> | [1] `include/sched/proc.h` · proc<br><code>struct proc { ... int64 vswtch; int64 ivswtch; ... } // 仅有上下文切换计数，无完整性能统计</code><br>[2] `kernel/sched/proc.c` · throughput|turnaround|waiting|response<br><code>未找到吞吐量、周转时间、等待时间、响应时间等性能指标的计算或优化代码</code> |

## 05_fs_drivers — 文件系统与设备 I/O

### `Q05_017` · `single_choice`

### 文件数据块分配方式 (File Allocation Method, Stallings Ch12) 更接近哪种？

**备选项：**

- **A.** 连续分配 (Contiguous Allocation)：文件占连续磁盘块
- **B.** 链式分配 (Chained/Linked Allocation)：块通过指针链接
- **C.** 索引分配 (Indexed Allocation)：inode 索引块列表
- **D.** extent 分配 (Extent-based)：连续块区间的索引
- **E.** 混合（如 Unix 直接+间接块）
- **F.** 未发现/不适用（内存FS无磁盘分配）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | FAT 表内嵌空闲链（FAT32 特有） | B. 链式分配 (Chained/Linked Allocation)：块通过指针链接 |
| **证据** | [1] `kernel/fs/fat32/fat32.c` · fat32_sb<br><code>FAT32 使用 FAT 表记录簇链，通过 fat-&gt;bpb.fat_sz 和 fat-&gt;free_count 管理空闲簇</code> | [1] `kernel/fs/fat32/fat.c` · read_fat<br><code>uint32 read_fat(struct superblock *sb, uint32 cluster) { ... uint32 fat_sec = fat_sec_of_clus(fat, cluster, 1); uint32 sec_off = fat_offset_of_clus(fat, cluster); ... next = *(uint32 *)(fat-&gt;fatcache.page + idx * SECSZ + sec_off); ...</code><br>[2] `kernel/fs/fat32/cluster.c` · reloc_clus<br><code>uint32 reloc_clus(struct inode *ip, uint off, int alloc) { ... clus = read_fat(sb, preclus); // get next cluster number ... table-&gt;clus[i] = clus; ...</code> |

### `Q05_021` · `single_choice`

### 设备发现/枚举机制更接近哪种？

**备选项：**

- **A.** Device Tree (DTB/DTS) 解析
- **B.** PCI/总线扫描
- **C.** 硬编码设备表/固定 MMIO 地址
- **D.** 混合（多种并存）
- **E.** 未发现/待核实

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | 混合（多种并存） | C. 硬编码设备表/固定 MMIO 地址 |
| **证据** | [1] `include/memlayout.h` · UART<br><code>#define UART 0x10000000L (QEMU) / 0x38000000L (k210) 硬编码地址</code><br>[2] `bootloader/SBI/rustsbi-qemu/src/main.rs` · count_harts<br><code>使用 device_tree 解析 DTB 获取 CPU 核心数</code> | [1] `include/memlayout.h` · MMIO_addresses<br><code>#define UART 0x38000000L #define CLINT 0x02000000L #define PLIC 0x0c000000L #ifndef QEMU #define GPIOHS 0x38001000 #define DMAC 0x50000000 #define GPIO 0x50200000 #define SPI0 0x52000000 #define SYSCTL 0x50440000 #endif</code><br>[2] `kernel/main.c` · main<br><code>void main(unsigned long hartid, unsigned long dtb_pa) { ... #ifndef QEMU fpioa_pin_init(); dmac_init(); #endif disk_init(); binit(); ...</code> |

### `Q05_022` · `tri_state_impl`

### 是否能在代码中证实解析了 `.dtb`/DeviceTree？（必须三态；若 implemented 必须指出解析入口）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | stub |
| **证据** | [1] `bootloader/SBI/rustsbi-qemu/src/main.rs` · count_harts<br><code>unsafe fn count_harts(dtb_pa: usize) { use device_tree::{DeviceTree, Node}; ... if let Ok(dt) = DeviceTree::load(data) { ... }</code> | [1] `bootloader/SBI/rustsbi-qemu/src/main.rs` · count_harts<br><code>unsafe fn count_harts(dtb_pa: usize) -&gt; usize { use device_tree::{DeviceTree, Node}; ... let header = &amp;*(dtb_pa as *const DtbHeader); let magic = u32::from_be(header.magic); if magic == DEVICE_TREE_MAGIC { let size = u32::from_be(header.size); let data = core::slice::from_raw_parts(dtb_pa as *const u8, size as usize); if let Ok(dt) = DeviceTree::load(data) { if let Some(cpu_map) = dt.find(&quot;/cpus/cpu-map&quot;) { return enumerate_cpu_map(cpu_map) } } }</code><br>[2] `kernel/main.c` · main<br><code>void main(unsigned long hartid, unsigned long dtb_pa) { ... // dtb_pa is passed but not used for device discovery on K210 #ifndef QEMU fpioa_pin_init(); dmac_init(); #endif</code> |

### `Q05_031` · `tri_state_impl`

### 是否存在 MMU 启用前后串口地址切换（phys/virt 切换）逻辑？（必须三态）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | not_found |
| **证据** | [1] `include/memlayout.h` · UART_V<br><code>#define UART_V (UART + VIRT_OFFSET)</code><br>[2] `kernel/mm/vm.c` · kvminit<br><code>kvmmap(UART_V, UART, PGSIZE, PTE_R | PTE_W);</code> | [1] `kernel/console.c` · uart_address_search<br><code>在附件源码中检索 UART 地址切换逻辑，console.c 中使用 sbi_console_putchar() 通过 SBI 调用输出，未直接使用 MMIO 地址。未找到 MMU 启用前后串口地址切换的显式逻辑。</code><br>[2] `include/memlayout.h` · uart_virt_search<br><code>虽然定义了 UART_V = (UART + VIRT_OFFSET)，但在实际代码中未找到 MMU 启用后使用 UART_V 而非 UART 的切换逻辑。</code> |

### `Q05_033` · `single_choice`

### 块设备（磁盘/eMMC/NVMe）I/O 请求调度算法 (Scheduling Algorithm) (Disk Scheduling Algorithm) 更接近哪种？（Stallings Ch11；若无显式调度则选「FCFS 顺序提交」）

**备选项：**

- **A.** FCFS（先来先服务 First-Come First-Served）
- **B.** SSTF（最短寻道时间优先 Shortest Seek Time First）
- **C.** SCAN / Elevator（电梯算法）
- **D.** C-SCAN（循环扫描 Circular SCAN）
- **E.** 基于 virtio 环（queue 顺序提交，无显式磁盘调度）
- **F.** 未发现

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | 基于 virtio 环（queue 顺序提交，无显式磁盘调度） | A. FCFS（先来先服务 First-Come First-Served） |
| **证据** | [1] `kernel/hal/virtio_disk.c` · virtio_disk_rw<br><code>通过 virtio descriptor ring 顺序提交请求，无电梯算法</code><br>[2] `kernel/hal/sdcard.c` · sdcard_submit<br><code>请求按提交顺序进入 wait_queue，无重排序</code> | [1] `kernel/hal/sdcard.c` · disk_scheduling_search<br><code>在附件源码中检索磁盘调度算法，sdcard.c 和 virtio_disk.c 中未找到 SSTF、SCAN、C-SCAN 等调度算法实现。请求按提交顺序处理，无显式调度逻辑。</code><br>[2] `kernel/fs/bio.c` · bwrite<br><code>void bwrite(struct buf *b) { ... res = disk_submit(b); b-&gt;valid = 1; releasesleep(&amp;b-&gt;lock); if ((res &amp; 0x1) == 0) bput(b); if ((res &amp; 0x2) == 0) disk_write_start(); }</code> |

## 06_sync_ipc — 同步互斥与进程间通信

### `Q06_004` · `fill_in`

### sleep / wakeup 不变量 (Sleep-Wakeup Invariant) 分析，按格式填写： - sleep 入口函数: ___（路径） - 入睡前持有的锁: ___（无则写 none） - 防丢 wakeup (Lost Wakeup Prevention) 机制: ___（如：持队列锁检查条件 / 无防护） - wakeup 函数: ___（路径） - 唤醒与锁释放顺序: ___（先唤醒后释放 / 先释放后唤醒 / 其他）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | sleep 入口函数: `kernel/sched/proc.c:582` (sleep(void *chan, struct spinlock *lk))<br>入睡前持有的锁: proc_lock（通过__enter_proc_cs 获取）+ 调用者传入的 lk（先释放后在 sleep 返回后重新获取）<br>防丢 wakeup (Lost Wakeup Prevention) 机制: 持 proc_lock 检查条件并调用__insert_sleep() 将进程加入睡眠队列，确保在释放 lk 前已完成入队，wakeup 持 proc_lock 遍历睡眠队列，避免丢失唤醒<br>wakeup 函数: `kernel/sched/proc.c:392` (wakeup(void *chan))<br>唤醒与锁释放顺序: 先唤醒（__wakeup_no_lock 在 proc_lock 保护下执行）后释放（__leave_proc_cs 释放 proc_lock），符合 Stallings 描述的防丢 wakeup 不变量 | sleep 入口函数：kernel/sched/proc.c::sleep()<br>入睡前持有的锁：调用者传入的 lk（自旋锁）<br>防丢 wakeup (Lost Wakeup Prevention) 机制：持队列锁检查条件 / 无防护（在 sleep() 中先 acquire 进程锁，然后插入睡眠队列，再调用 sched() 释放 CPU）<br>wakeup 函数：kernel/sched/proc.c::wakeup()<br>唤醒与锁释放顺序：先唤醒后释放（wakeup 遍历 proc_sleep 队列，将匹配 chan 的进程移到 runnable 队列，然后被唤醒的进程在 scheduler 中获得 CPU 后继续执行） |
| **证据** | [1] `kernel/sched/proc.c` · sleep<br><code>行 582-606：if (&amp;proc_lock != lk) { acquire(&amp;proc_lock); release(lk); } ... __insert_sleep(p); sched(); ... release(&amp;proc_lock); acquire(lk);</code><br>[2] `kernel/sched/proc.c` · wakeup<br><code>行 392-405：acquire(&amp;proc_lock); int flag = __wakeup_no_lock(chan); release(&amp;proc_lock); if (flag &amp;&amp; avail) { sbi_send_ipi(...); }</code><br>[3] `kernel/sched/proc.c` · lock ordering comment<br><code>行 249-253：NOTICE! To avoid any potential deadlock with proc_lock, proc_lock should be acquired last</code> | [1] `kernel/sched/proc.c` · sleep<br><code>void sleep(void *chan, struct spinlock *lk) { struct proc *p = myproc(); acquire(&amp;p-&gt;lk); p-&gt;chan = chan; __remove(p); __insert_sleep(p); release(&amp;p-&gt;lk); sched(); acquire(&amp;p-&gt;lk); p-&gt;chan = NULL; release(&amp;p-&gt;lk); }</code><br>[2] `kernel/sched/proc.c` · wakeup<br><code>void wakeup(void *chan) { struct proc *p = proc_sleep; while (NULL != p) { struct proc *next = p-&gt;sched_next; if ((uint64)chan == (uint64)p-&gt;chan) { __remove(p); p-&gt;timer = TIMER_IRQ; p-&gt;chan = NULL; __insert_runnable(PRIORITY_IRQ, p); } p = next; } }</code> |

### `Q06_013` · `single_choice`

### 底层原子操作来源更接近哪种？

**备选项：**

- **A.** Rust core::sync::atomic（标准库）
- **B.** 自定义汇编（ldxr/stxr、lock xchg 等）
- **C.** 两者均有
- **D.** 未发现/不确定

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | 自定义汇编（ldxr/stxr、lock xchg 等） | A. Rust core::sync::atomic（标准库） |
| **证据** | [1] `kernel/sync/spinlock.c` · acquire<br><code>行 34：while(__sync_lock_test_and_set(&amp;lk-&gt;locked, 1) != 0); 使用 GCC 内置原子操作，RISC-V 后端生成 amoswap.w.aq 指令</code><br>[2] `kernel/sync/spinlock.c` · release<br><code>行 71：__sync_lock_release(&amp;lk-&gt;locked); 生成 amoswap.w 指令</code><br>[3] `kernel/sync/spinlock.c` · atomic comment<br><code>行 31-33 注释说明：On RISC-V, sync_lock_test_and_set turns into an atomic swap</code> | [1] `kernel/sync/spinlock.c` · acquire<br><code>while(__sync_lock_test_and_set(&amp;lk-&gt;locked, 1) != 0); __sync_synchronize();</code><br>[2] `kernel/sync/spinlock.c` · release<br><code>__sync_synchronize(); __sync_lock_release(&amp;lk-&gt;locked);</code> |

### `Q06_015` · `single_choice`

### 内核对死锁 (Deadlock) 的处理策略更接近哪种？

**备选项：**

- **A.** 死锁预防 (Deadlock Prevention)：通过锁顺序等消除 Coffman 必要条件
- **B.** 死锁避免 (Deadlock Avoidance)：运行时检查资源分配安全性（如 Banker 算法）
- **C.** 死锁检测与恢复 (Detection & Recovery)：允许死锁发生后恢复
- **D.** 忽略 (Ostrich Algorithm)：不处理，依赖外部重启
- **E.** 未发现相关机制

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | 死锁预防 (Deadlock Prevention)：通过锁顺序等消除 Coffman 必要条件 | D. 忽略 (Ostrich Algorithm)：不处理，依赖外部重启 |
| **证据** | [1] `kernel/sched/proc.c` · lock ordering<br><code>行 249-253：NOTICE! To avoid any potential deadlock with proc_lock, proc_lock should be acquired last</code><br>[2] `kernel/sched/proc.c` · exit lock order<br><code>行 454-458：acquire proc_lock after parent&#x27;s lock, to avoid deadlock with parent calling sleep(p, &amp;p-&gt;lk) in wait4()</code><br>[3] `kernel/sched/proc.c` · sleep lock order<br><code>行 603-605：release proc_lock first to avoid deadlock in case another call to sleep() with the same lk</code> | [1] `kernel` · deadlock_detection<br><code>在整个 kernel 目录中搜索死锁检测、避免或恢复相关代码，未找到 deadlock detection/avoidance/recovery 实现</code><br>[2] `kernel/sched/proc.c` · lock_ordering<br><code>在 proc.c 中未发现锁顺序检查或死锁预防机制</code> |

### `Q06_016` · `tri_state_impl`

### 是否存在全局锁顺序（Lock Ordering）规范或注释，以预防嵌套锁导致的循环等待死锁 (Circular Wait Deadlock)？（必须三态；若 implemented 需给出锁排序规则或 ABBA 锁检测代码证据）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | not_found |
| **证据** | [1] `kernel/sched/proc.c` · proc_lock ordering<br><code>行 249-253：proc_lock should be acquired last with any situation requiring multiple spinlocks</code><br>[2] `kernel/sched/proc.c` · exit lock order<br><code>行 454-458：acquire proc_lock after parent&#x27;s lock, to avoid deadlock with parent calling sleep(p, &amp;p-&gt;lk) in wait4()</code><br>[3] `kernel/sched/proc.c` · sleep lock release order<br><code>行 603-605：release proc_lock first to avoid deadlock in case another call to sleep() with the same lk</code> | [1] `kernel` · lock_order<br><code>在整个 kernel 目录中搜索 lock ordering/lock order/锁顺序 相关注释或规范，未找到全局锁顺序定义</code><br>[2] `include/sync` · lock_hierarchy<br><code>在 sync 头文件中搜索锁层次结构或锁获取顺序规范，未找到相关文档</code> |

### `Q06_017` · `tri_state_impl`

### 是否实现管程/条件变量 (Monitor / Condition Variable, Stallings Ch5)？（必须三态；搜索 Condvar / condition_variable / monitor / wait/notify/signal 等；若 implemented 需区分 Hoare 语义（等待者立即恢复）vs Mesa 语义（等待者重新竞争锁））

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | not_found | implemented |
| **证据** | [1] `repos/xv6-k210` · condvar/condition_variable<br><code>grep 搜索 &#x27;condvar|condition_variable|Condition|notify|wait.*notify&#x27; 仅找到无关匹配（license 头文件、VIRTIO_MMIO_QUEUE_NOTIFY 等），无条件变量实现</code><br>[2] `include/sync/` · sync headers<br><code>仅含 spinlock.h、sleeplock.h、waitqueue.h，无 condvar.h 或类似定义</code> | [1] `kernel/sched/proc.c` · sleep<br><code>void sleep(void *chan, struct spinlock *lk) { struct proc *p = myproc(); acquire(&amp;p-&gt;lk); p-&gt;chan = chan; __remove(p); __insert_sleep(p); release(&amp;p-&gt;lk); sched(); acquire(&amp;p-&gt;lk); p-&gt;chan = NULL; release(&amp;p-&gt;lk); }</code><br>[2] `kernel/sched/proc.c` · wakeup<br><code>void wakeup(void *chan) { struct proc *p = proc_sleep; while (NULL != p) { struct proc *next = p-&gt;sched_next; if ((uint64)chan == (uint64)p-&gt;chan) { __remove(p); p-&gt;timer = TIMER_IRQ; p-&gt;chan = NULL; __insert_runnable(PRIORITY_IRQ, p); } p = next; } }</code><br>[3] `kernel/fs/pipe.c` · pipelock<br><code>static void pipelock(struct pipe *pi, struct wait_node *wait, int who) { struct wait_queue *q; q = (who == PIPE_READER) ? &amp;pi-&gt;rqueue : &amp;pi-&gt;wqueue; acquire(&amp;q-&gt;lock); wait_queue_add(q, wait); while (!wait_queue_is_first(q, wait)) { sleep(wait-&gt;chan, &amp;q-&gt;lock); } release(&amp;q-&gt;lock); }</code> |

## 07_security — 安全机制与权限模型

### `Q07_002` · `tri_state_impl`

### 是否存在凭证/权限数据结构（UID/GID/Credential/Capability/ACL 等）？（必须三态）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | stub | implemented |
| **证据** | [1] `include/fs/stat.h` · kstat<br><code>struct kstat { ... uint32_t uid; uint32_t gid; ... };</code><br>[2] `include/sched/proc.h` · proc<br><code>struct proc { ... // 无 uid/gid/credential 字段 }</code><br>[3] `kernel/exec.c` · execve<br><code>{AT_UID, 0}, {AT_EUID, 0}, {AT_GID, 0}, {AT_EGID, 0} // 硬编码为 0</code> | [1] `include/fs/stat.h` · kstat<br><code>struct kstat { uint32 uid; uint32 gid; ... } - UID/GID fields exist in file stat structure</code><br>[2] `include/fs/fs.h` · inode<br><code>struct inode contains mode field for file permissions (S_IFMT, S_IFDIR, S_IFREG, etc.)</code> |

### `Q07_003` · `tri_state_impl`

### 是否能证实在 syscall 路径上真实执行了权限检查（open/exec/write 等）？（必须三态；仅有字段不算 implemented）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | not_found | stub |
| **证据** | [1] `kernel/syscall/sysproc.c` · sys_getuid<br><code>uint64 sys_getuid(void) { return 0; }</code><br>[2] `kernel/exec.c` · execve<br><code>{AT_UID, 0}, {AT_EUID, 0}, {AT_GID, 0}, {AT_EGID, 0} // 无权限检查逻辑</code> | [1] `kernel/syscall/sysfile.c` · sys_faccessat<br><code>sys_faccessat checks file existence and mode bits but returns 0 for root user without actual permission enforcement - assumes user as root</code><br>[2] `kernel/syscall/sysfile.c` · sys_openat<br><code>openat checks file type (directory vs regular file) but no UID/GID based permission checking implemented</code><br>[3] `kernel/fs/fs.c` · create<br><code>File creation uses mode parameter but no actual owner/permission enforcement in FAT32 implementation</code> |

### `Q07_007` · `tri_state_impl`

### 是否存在栈保护/溢出防护（stack canary/guard page）或等价机制？（必须三态）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | stub | implemented |
| **证据** | [1] `include/memlayout.h:113` · guard_page_comment<br><code>// each surrounded by invalid guard pages.</code><br>[2] `kernel/mm/vm.c:596` · stack_guard_comment<br><code>// used by exec for the user stack guard page.</code> | [1] `Makefile` · stack_protector<br><code>CFLAGS += $(shell $(CC) -fno-stack-protector -E -x c /dev/null &gt;/dev/null 2&gt;&amp;1 &amp;&amp; echo -fno-stack-protector) - stack protector explicitly disabled but...</code><br>[2] `include/memlayout.h` · KSTACK<br><code>// map kernel stacks beneath the trampoline, each surrounded by invalid guard pages. 保护页的 PTE 无效（即，PTE_V 置 0），因此，如果内核溢出内核堆栈，则很可能会导致异常</code><br>[3] `doc/内核原理 - 内存管理.md` · stack_protection<br><code>内核堆栈页面。每个进程都有自己的内核堆栈，该堆栈被映射到较高的位置，因此 xv6 在其下方可以留下未映射的保护页。保护页的 PTE 无效，如果内核溢出内核堆栈，则很可能会导致异常</code> |

### `Q07_011` · `tri_state_impl`

### 是否实现了内核/用户页表隔离 (Kernel/User Page Table Isolation, KPTI 或等价机制)？ （x86: CR3 KPTI / SMEP / SMAP；RISC-V: PMP / S-mode 分离；AArch64: TTBR0/TTBR1 隔离； 必须三态；无则写未发现并列出已搜关键字）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | not_found |
| **证据** | [1] `include/memlayout.h` · TRAMPOLINE<br><code>#define TRAMPOLINE (MAXVA - PGSIZE) // map the trampoline page to the highest address</code><br>[2] `kernel/trap/trampoline.S` · uservec<br><code># this code is mapped at the same virtual address (TRAMPOLINE) in user and kernel space</code><br>[3] `kernel/trap/trap.c` · usertrapret<br><code>p-&gt;trapframe-&gt;kernel_satp = r_satp(); // kernel page table ... w_satp(MAKE_SATP(p-&gt;pagetable)); // user page table</code><br>[4] `include/hal/riscv.h` · SSTATUS_PUM<br><code>#define SSTATUS_PUM (1L &lt;&lt; 18) // 控制用户态访问内核内存</code> | [1] `doc/内核设计 - 页表映射.md` · page_table_design<br><code>在 xv6-k210 这个较为简单的内核上，为了提高效率，我们取消了原本的用户、内核页表分离的规则，将用户空间与内核空间合并在一个页表中 - KPTI explicitly NOT implemented</code><br>[2] `kernel/mm/vm.c` · kvmcreate<br><code>pagetable_t kvmcreate() creates kernel page table that is copied for each process - user and kernel share same page table structure</code><br>[3] `include/memlayout.h` · address_layout<br><code>User space: 0x1000 to 0x80000000, Kernel space: 0x80000000 and above - both mapped in same page table with PTE_U flag controlling access</code><br>[4] `include/hal/riscv.h` · kpti_keywords<br><code>Searched for KPTI, CR3 switch, SMEP, SMAP, TTBR0/TTBR1 - none found. Only PTE_U flag for user/kernel separation</code> |

### `Q07_013` · `single_choice`

### 访问控制模型 (Access Control Model, Stallings Ch15) 更接近哪种？

**备选项：**

- **A.** 自主访问控制 DAC (Discretionary Access Control)：所有者自主设置权限（Unix 权限位）
- **B.** 强制访问控制 MAC (Mandatory Access Control)：系统强制安全标签（SELinux/AppArmor 类）
- **C.** 基于角色的访问控制 RBAC (Role-Based Access Control)
- **D.** 仅有特权级隔离（ring0/ring3），无细粒度访问控制
- **E.** 未发现访问控制机制

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | 仅有特权级隔离（ring0/ring3），无细粒度访问控制 | 自主访问控制 DAC (Discretionary Access Control)：所有者自主设置权限（Unix 权限位） |
| **证据** | [1] `include/hal/riscv.h` · SSTATUS_SPP<br><code>#define SSTATUS_SPP (1L &lt;&lt; 8) // Previous mode, 1=Supervisor, 0=User</code><br>[2] `kernel/syscall/sysproc.c` · sys_getuid<br><code>return 0; // 无真实权限检查</code> | [1] `include/fs/stat.h` · permission_bits<br><code>#define S_IFMT 0170000 #define S_IFDIR 0040000 #define S_IFREG 0100000 - Unix-style file type and permission bits</code><br>[2] `kernel/syscall/sysfile.c` · sys_faccessat<br><code>Checks file mode bits (read/write/execute) against requested access - classic DAC model</code><br>[3] `kernel/fs/fat32/fat32.c` · fat_alloc_entry<br><code>File creation uses mode parameter (S_IFDIR, S_IFREG) but FAT32 doesn&#x27;t store Unix permissions - permissions are virtual/in-memory only</code><br>[4] `doc/内核设计 - 文件系统 v2.md` · vfs_design<br><code>简单虚拟文件系统实现，基于 Linux VFS 概念但简化，支持 Unix-style operations like mount, but FAT32 underlying filesystem doesn&#x27;t support full Unix permissions</code> |

## 09_debug_error — 调试机制与错误处理

### `Q09_005` · `tri_state_impl`

### 是否存在 **内核驻留的交互式监视器（kernel monitor）**？（对齐 Stallings《操作系统：精髓与设计原理》语境：**在内核态上下文**接受命令、用于探查/操控系统的监视器；**不包括**仅在用户态运行的常规 shell，如 `xv6-user/sh.c`、`user/` 下用户程序等——除非题面另有定义。必须三态；若 `implemented`：须给出 3–10 个 **用户可键入的 monitor 命令名** 及对应 **内核内** 解析/分发入口的 `路径:行号` 证据；仅以用户态 shell 充当内核 monitor 视为 **未切题** 应判 `stub` 或 `not_found` 并说明理由。）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | not_found |
| **证据** | [1] `xv6-user/sh.c` · export<br><code>int export(char *argv) - 支持 -p 打印所有环境变量或设置新环境变量</code><br>[2] `xv6-user/sh.c` · runcmd<br><code>void runcmd(struct cmd *cmd) - 执行命令，支持 EXEC/REDIR/PIPE/LIST/BACK 等类型</code><br>[3] `xv6-user/sh.c` · parsecmd<br><code>struct cmd *parsecmd(char*) - 解析 shell 命令行</code><br>[4] `xv6-user/sh.c` · replace<br><code>int replace(char *buf) - 替换环境变量引用 $VAR</code> | [1] `xv6-user/sh.c` · shell<br><code>User-space shell implementation. Runs in user mode, parses commands like cd, export, exec. Not a kernel-resident monitor.</code><br>[2] `kernel/console.c` · consoleintr<br><code>Console input handler processes special keys (Ctrl-P prints process list, Ctrl-E prints file-entry list, Ctrl-K prints mem-alloc list, Ctrl-B prints buffer cache, Ctrl-Q prints physical memory). These are debug triggers, not interactive monitor commands with command parsing/dispatch.</code><br>[3] `kernel/trap/trap.c` · usertrap<br><code>No kernel monitor command parsing. Trap handling is for exceptions/interrupts/syscalls, not interactive command interpretation in kernel context.</code> |

### `Q09_008` · `tri_state_impl`

### 是否存在 trace/perf/ftrace 等跟踪机制或 tracepoints？（必须三态）

| 项目 | 方法A | 方法B |
| --- | --- | --- |
| **答案** | implemented | stub |
| **证据** | [1] `kernel/syscall/sysproc.c` · sys_trace<br><code>sys_trace(void) { myproc()-&gt;tmask = 1; return 0; }</code><br>[2] `xv6-user/strace.c` · main<br><code>strace 用户工具：调用 trace() 系统调用后 execve 执行目标程序</code> | [1] `include/sysnum.h` · SYS_trace<br><code>SYS_trace syscall number defined (value 18).</code><br>[2] `kernel/syscall/sysproc.c` · sys_trace<br><code>sys_trace() sets myproc()-&gt;tmask = 1. Enables syscall tracing for the process.</code><br>[3] `kernel/syscall/syscall.c` · syscall<br><code>If p-&gt;tmask is set, prints syscall name and arguments before execution, and return value after. Basic syscall tracing, not full ftrace/perf infrastructure with tracepoints.</code><br>[4] `xv6-user/strace.c` · strace<br><code>User-space strace utility that calls trace() syscall and execs target program. Traces syscalls of child process.</code> |
