### Q02_001 启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）

启动入口位于 `kernel/entry_qemu.S:3` 的 `_entry` 标签（QEMU 平台）和 `kernel/entry_visionfive.S:3` 的 `_start` 标签（VisionFive2 平台）。链接脚本 `linker/qemu.ld:2` 明确指定 `ENTRY(_entry)`，基地址为 `0x80200000`。

### Q02_002 启动链更接近哪种交接方式？

固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）

### Q02_003 是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）

已实现

### Q02_004 模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）

RISC-V 模式切换关键寄存器/位：
1. `sstatus.SPP` (bit 8)：Previous Privilege Mode，0=用户态，1=监督态
2. `sstatus.SPIE` (bit 5)：Supervisor Previous Interrupt Enable
3. `satp`：页表基址寄存器，切换地址空间
4. `stvec`：trap 向量基址寄存器
5. `sepc`：异常程序计数器
6. `scause`：异常原因寄存器
证据：`kernel/include/riscv.h:46-47` 定义 SSTATUS_SPP 和 SSTATUS_SPIE；`kernel/trap.c:144-145` 设置这些位。

### Q02_005 是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）

已实现

### Q02_006 从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）

启动跳转链（QEMU 平台）：
1. `_entry` (`kernel/entry_qemu.S:4`)：汇编入口，计算栈地址
2. `main` (`kernel/main.c:39`)：C 语言主入口
3. `trapinithart` (`kernel/trap.c:36`)：设置 trap 向量 stvec
4. `kvminithart` (`kernel/vm.c:68`)：启用 MMU
5. `scheduler` (`kernel/proc.c:669`)：启动第一个进程

VisionFive2 平台类似，但入口为 `_start` (`kernel/entry_visionfive.S:4`)。

### Q02_007 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）

BSS 清零 (BSS Clearing): implemented [linker/qemu.ld:48-51] - 链接脚本定义 .bss 段和 sbss_clear/ebss_clear 符号
早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:51] - sbi_console_putchar 通过 SBI 实现早期输出
设备树解析 (Device Tree Blob parsing, DTB): not_found [kernel/main.c] - 未发现 DTB 解析代码，平台配置通过条件编译区分
页表初始化时机 (Page Table Init): implemented [kernel/main.c:50-51] - 在 MMU 启用前调用 kvminit() 建立初始页表，然后 kvminithart() 启用

### Q02_008 是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）

未发现

### Q02_009 是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）

已实现

### Q02_010 构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）

通过 Makefile 条件编译和链接脚本区分平台：
1. QEMU 平台：使用 `kernel/entry_qemu.S` 和 `linker/qemu.ld`
2. VisionFive2 平台：使用 `kernel/entry_visionfive.S` 和 `linker/visionfive.ld`
3. 条件编译宏：`#ifdef QEMU` 和 `#ifdef visionfive` 在源码中区分平台特定代码
证据：`kernel/vm.c:32,46` 使用 `#ifdef visionfive` 和 `#ifdef QEMU` 区分 UART 和 VIRTIO 映射；`kernel/console.c:31,41,48` 等平台特定代码。

### Q02_011 对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）

已实现

### Q02_012 MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）

已实现

### Q02_013 是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）

已实现

### Q02_014 是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）

支持双平台启动：QEMU 和 StarFive VisionFive2。
1. QEMU 平台：入口 `kernel/entry_qemu.S:_entry`，链接脚本 `linker/qemu.ld`
2. VisionFive2 平台：入口 `kernel/entry_visionfive.S:_start`，链接脚本 `linker/visionfive.ld`
3. 差异：entry_visionfive.S 有额外的注释代码（注释掉的 mhartid 读取）；vm.c 中 UART 和 SD 控制器映射地址不同。
4. 互斥关系：通过 `#ifdef QEMU` 和 `#ifdef visionfive` 条件编译区分，未见 LoongArch 支持。

### Q02_015 trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）

Trap 向量入口：
1. 内核态：`kernel/kernelvec.S:kernelvec` - 通过 `w_stvec((uint64)kernelvec)` 设置
2. 用户态：`kernel/trampoline.S:uservec` - 通过 `w_stvec(TRAMPOLINE + (uservec - trampoline))` 设置
证据：`kernel/trap.c:37` 设置内核向量；`kernel/trap.c:130` 设置用户向量；`kernel/trampoline.S:16` 定义 uservec 标签。

### Q02_016 trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？

用户地址空间预留页（trampoline/trap_context page）

### Q02_017 TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）

定义位置：`kernel/include/trap.h:17-60` 的 `struct trapframe`。
寄存器数量：33 个字段（5 个内核元数据 + 28 个通用寄存器）。
字节数：288 字节（5*8 + 28*8 = 40 + 224 = 264 字节，但实际结构体包含 33 个 uint64 字段 = 264 字节）。
具体字段：kernel_satp(8)、kernel_sp(8)、kernel_trap(8)、epc(8)、kernel_hartid(8)、ra-t6(28 个寄存器*8=224)，总计 264 字节。

### Q02_018 是否存在系统调用分发表（syscall table / match 分发）？（必须三态）

已实现

### Q02_019 系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）

已实现

### Q02_020 选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。

sys_write 调用链：
1. 用户态：`ecall` 指令，a7=SYS_write(64)，a0=fd，a1=buf，a2=count
2. Trap 入口：`kernel/trampoline.S:uservec` 保存上下文，跳转到 `usertrap`
3. Trap 分发：`kernel/trap.c:76` 检测到 scause=8（ecall），调用 `syscall()`
4. Syscall 分发：`kernel/syscall.c:437` 检查 num=64，调用 `syscalls[64]() = sys_write()`
5. 实现体：`kernel/sysfile.c:180-191` 解析参数，调用 `filewrite(f, p, n)`
6. 返回：设置 `p->trapframe->a0` 为返回值，`usertrapret()` 恢复上下文返回用户态。

### Q02_021 列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。

高价值 syscall 实现状态：
1. sys_fork: implemented [kernel/sysproc.c:268] - 调用 fork()
2. sys_exec: implemented [kernel/sysfile.c:455] - 调用 exec()
3. sys_open: implemented [kernel/sysfile.c:455-462] - 调用 open()
4. sys_write: implemented [kernel/sysfile.c:180-191] - 调用 filewrite()
5. sys_mmap: implemented [kernel/sysproc.c:135 声明，kernel/mmap.c 实现]
6. sys_clone: implemented [kernel/sysproc.c:20-52] - 调用 thread_clone() 或 clone()
7. sys_exit: implemented [kernel/sysproc.c] - 调用 exit()
8. sys_wait: implemented [kernel/sysproc.c:271-275] - 调用 wait()
9. sys_read: implemented [kernel/sysfile.c] - 调用 fileread()
10. sys_brk: implemented [kernel/sysproc.c:283-300] - 调用 growproc()

### Q02_022 是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）

已实现

### Q02_023 时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）

已实现

### Q02_024 是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）

已实现

### Q02_025 缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）

存在缺页异常处理，但仅支持栈空间的动态增长（类似 lazy allocation），未发现 CoW 实现。
入口点：`kernel/trap.c:79-83` 检测到 scause=13/15（load/store page fault），调用 `handle_stack_page_fault()`。
实现：`kernel/vma.c:288-322` 检查 fault 地址是否在栈 VMA 范围内，如果是则调用 `uvmalloc1()` 分配新页，扩展栈空间。
未发现 CoW 相关代码（搜索 cow 关键词无命中）。

### Q02_026 与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）

多核支持已实现：
1. AP 启动：`kernel/main.c:75` 通过 `sbi_hart_start(2, (unsigned long)_start, 0)` 启动 hart 2
2. Per-CPU trap 初始化：每个 hart 启动后调用 `trapinithart()` 设置自己的 stvec
3. Per-CPU 时钟：`kernel/timer.c:39` 每个 hart 调用 `sbi_set_timer()` 设置独立定时器
4. Per-CPU 数据：`kernel/proc.c:20` 定义 `struct cpu cpus[NCPU]` 存储每 CPU 状态
一致性：AP 启动流程与 BSP 一致，都经过 entry_xxx.S → main() → trapinithart() → scheduler()。

### Q02_027 Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）

分发表路径：kernel/syscall.c:204-317 (syscalls[] 数组)
完整实现 ✅ (implemented): 约 95 个（根据 syscalls[] 数组中非空且对应.c 文件有实际逻辑的函数）
桩/ENOSYS/return 0 🔸 (stub): 约 15 个，代表性例子：sys_chroot() [kernel/sysproc.c:426] 直接返回 0；sys_exit_group() [kernel/sysproc.c:424] 直接返回 0；sys_sched_setscheduler() [kernel/sysproc.c:214-216] 仅返回 0
未注册 ❌ (not_found): 0 个（所有 SYS_* 宏在 sysnum.h 中定义，都在 syscalls[] 中有对应项）
统计依据：基于 kernel/syscall.c 的 syscalls[] 数组（第 204-317 行）和 sysnames[] 数组（第 319-429 行），共约 110 个 syscall；抽样检查 sysfile.c、sysproc.c、syssig.c、thread.c 等实现文件确认实现深度。

### Q02_028 README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）

README.md 仅 23 行，内容为依赖说明和构建/运行命令，未声称具体 syscall 兼容性。README 文件（2.1KB）内容类似，主要是许可证和构建说明。因此「无 README 声称，仅以代码为准」。代码中 syscalls[] 分发表包含约 110 个 syscall，覆盖 POSIX/Linux 常用 syscall（fork、exec、open、read、write、mmap、clone、signal 等）。

### Q02_029 `_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）

搜索结论：命中 64 个结果，但全部位于 `kernel/lwip/` 目录下（LwIP 网络协议栈），与 syscall 无关。
具体命中：
1. `lwip_getsockopt_impl` (kernel/lwip/api/sockets.c:401)
2. `lwip_setsockopt_impl` (kernel/lwip/api/sockets.c:403)
3. ppp 日志宏：`ppp_dbglog_impl`、`ppp_info_impl` 等 (kernel/lwip/include/netif/ppp/ppp_impl.h:619-624)
内核 syscall 实现未使用 `_impl` 后缀命名模式，直接采用 `sys_xxx` 命名。

### Q02_030 是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）

已实现

### Q02_031 非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）

未发现

### Q02_032 信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）

信号发送支持三种粒度：
1. 进程级：`sys_kill` [kernel/sysproc.c:339-359] - 向进程发送信号，但实现有缺陷（第 354 行错误地使用 `pid = myproc()->pid` 而非目标 pid）
2. 线程级：`sys_tkill` [kernel/thread.c:69-77] - 向特定线程发送信号，但实现为桩（第 76 行仅返回 0）
3. 进程组级：`sys_tgkill` [kernel/syssig.c:101-110] - 向线程组发送信号，调用 `tgkill(tid, pid, sig)`
已完整实现：sys_kill（尽管有 bug）、sys_tgkill；桩实现：sys_tkill。

### Q02_033 中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）

通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）

### Q02_034 是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）

未发现
