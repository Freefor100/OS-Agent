### Q02_001 启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）

K210 平台：linker/k210.ld 中 ENTRY(_start)，对应 kernel/entry_k210.S 的 _start 标签。QEMU 平台：linker/linker64.ld 中 ENTRY(_entry)，对应 kernel/entry.S 的 _entry 标签。两个入口均设置栈指针后 call main。

### Q02_002 启动链更接近哪种交接方式？

固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）

### Q02_003 是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）

已实现

### Q02_004 模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）

RISC-V sstatus.SPP (bit 8) 控制 S-mode 返回时的特权级：0=User, 1=Supervisor。sstatus.SPIE (bit 5) 控制中断使能。K210 平台使用 sstatus.PUM (bit 18) 保护用户内存，QEMU 平台使用 sstatus.SUM (bit 18) 允许内核访问用户内存。sepc 保存异常返回地址。satp 控制页表基址与 Sv39 模式。stvec 指向 trap 向量。

### Q02_005 是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）

已实现

### Q02_006 从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）

RustSBI (M-mode) → 链接脚本 ENTRY(_start 或 _entry) → entry_k210.S:_start / entry.S:_entry（设置栈指针 sp=boot_stack+hartid*4*PGSIZE）→ call main → kernel/main.c:main(unsigned long hartid, unsigned long dtb_pa) → inithartid(hartid) 将 hartid 写入 tp 寄存器 → hart0 执行完整初始化序列 → scheduler()

### Q02_007 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）

BSS 清零 (BSS Clearing): not_found [linker/k210.ld:43-47 定义了 bss_start/sbss_clear/ebss_clear 符号，但未在 C/汇编代码中发现显式 BSS 清零循环；链接脚本将 .bss 段标记为 NOLOAD 类型，依赖加载器或固件清零]
早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:44-48 通过 sbi_console_putchar() 实现早期输出，在 consoleinit() 之后可用]
设备树解析 (Device Tree Blob parsing, DTB): not_found [main() 接收 dtb_pa 参数但未使用；搜索 DTB/FDT/device_tree 无命中]
页表初始化时机 (Page Table Init): implemented [在 MMU 启用前：kvminit() 先建立内核页表，随后 kvminithart() 写 satp 启用分页]

### Q02_008 是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）

已实现

### Q02_009 是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）

已实现

### Q02_010 构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）

Makefile 第 1 行 `platform := k210` 设置默认平台。通过 `ifeq ($(platform), qemu)` 条件编译：定义 `-D QEMU` 宏、选择不同 SBI 固件（sbi-k210 vs sbi-qemu）、选择不同链接脚本（k210.ld vs linker64.ld）、选择不同源文件（K210 用 hal/spi.c/gpiohs.c/fpioa.c/sdcard.c/dmac.c/sysctl.c，QEMU 用 hal/virtio_disk.c）。入口文件统一为 `$K/entry.S`（但链接脚本决定 ENTRY 符号：k210.ld→_start，linker64.ld→_entry）。

### Q02_011 对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）

已实现

### Q02_012 MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）

已实现

### Q02_013 是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）

已实现

### Q02_014 是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）

未发现。仅支持 K210 和 QEMU virt 两个目标，通过 Makefile 中 `platform := k210` 切换。搜索 visionfive/jh7110/loongarch/loongson 均无命中。

### Q02_015 trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）

用户态 trap 入口：kernel/trap/trampoline.S:uservec（通过 stvec=TRAMPOLINE+offset 设置）。内核态 trap 入口：kernel/trap/kernelvec.S:kernelvec（通过 stvec=kernelvec 设置）。

### Q02_016 trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？

用户地址空间预留页（trampoline/trap_context page）

### Q02_017 TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）

定义在 include/trap.h:struct trapframe。包含 32 个通用寄存器（kernel_satp/kernel_sp/kernel_trap/epc/kernel_hartid/ra/sp/gp/tp/t0-t6/s0-s11/a0-a7）+ 32 个浮点寄存器（ft0-ft11/fs0-fs11/fa0-fa7）+ fcsr，共 69 个 uint64 字段，总大小 552 字节。

### Q02_018 是否存在系统调用分发表（syscall table / match 分发）？（必须三态）

已实现

### Q02_019 系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）

已实现

### Q02_020 选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。

1) 用户态执行 ecall（a7=SYS_write=64）→ 2) 硬件跳转到 stvec 指向的 uservec (kernel/trap/trampoline.S:14) → 3) uservec 保存寄存器到 trapframe，加载 kernel_trap 地址，jr 到 usertrap() (kernel/trap/trap.c:74) → 4) usertrap 检测 scause==EXCP_ENV_CALL，调用 syscall() (kernel/syscall/syscall.c:332) → 5) syscall() 从 trapframe->a7 取号 64，查 syscalls[64]=sys_write，调用之 → 6) sys_write() (kernel/syscall/sysfile.c:118) 通过 argfd/argaddr/argint 提取参数，调用 filewrite()

### Q02_021 列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。

fork: implemented [kernel/syscall/sysproc.c 中 sys_fork 调用 fork()]
exec: implemented [kernel/syscall/sysproc.c 中 sys_exec 调用 exec()]
mmap: implemented [kernel/syscall/sysmem.c 中 sys_mmap 调用 mmap()]
open: implemented [kernel/syscall/sysfile.c 中 sys_openat 调用 create() 或 openat()]
write: implemented [kernel/syscall/sysfile.c:118 sys_write→filewrite]
read: implemented [kernel/syscall/sysfile.c 中 sys_read→fileread]
kill: implemented [kernel/syscall/syssignal.c:134 sys_kill→kill]
clone: implemented [kernel/syscall/sysproc.c 中 sys_clone]
wait: implemented [kernel/syscall/sysproc.c 中 sys_wait/sys_wait4]
brk: implemented [kernel/syscall/sysmem.c 中 sys_brk]

### Q02_022 是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）

已实现

### Q02_023 时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）

已实现

### Q02_024 是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）

已实现

### Q02_025 缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）

是。缺页异常入口：handle_excp() (kernel/trap/trap.c:328) 根据 scause 分发到 handle_page_fault() (kernel/mm/vm.c:1039)。handle_page_fault 通过 locateseg 定位 segment，walk 查 PTE，然后根据 seg->type 分发：LOAD→handle_page_fault_loadelf（按需加载 ELF）、HEAP/STACK→handle_page_fault_lazy（懒分配）、MMAP→handle_page_fault_mmap。若 PTE 含 COW 标记且为 store 类型，调用 handle_store_page_fault_cow() 执行写时复制。

### Q02_026 与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）

单核结论一致。hart0 执行完整初始化（trapinithart→plicinithart），hart1 等待 started 标志后仅执行 floatinithart→kvminithart→trapinithart（不执行 plicinithart）。每个 hart 使用独立的 boot_stack 区域（hartid*4*PGSIZE 偏移），trap 栈在 kernelvec.S 中通过 addi sp,sp,-256 在当前内核栈上分配。时钟中断通过 CLINT_MTIME（全局）和 sbi_set_timer（per-hart）设置。

### Q02_027 Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）

分发表路径: kernel/syscall/syscall.c:188 (syscalls[] 数组)
完整实现 ✅ (implemented): 约 55-60 个（基于 syscalls[] 注册条目减去已知桩函数）
桩/ENOSYS/return 0 🔸 (stub): 约 5-10 个，代表性例子: sys_getuid/sys_geteuid/sys_getgid/sys_getegid 均指向 sys_getuid（可能返回固定值），sys_pselect/sys_ppoll/sys_prlimit64/sys_adjtimex/sys_clock_settime/sys_clock_gettime/sys_statfs/sys_getrusage/sys_setitimer/sys_msync 等可能为桩
未注册 ❌ (not_found): 0 个（syscalls[] 中所有已注册条目均有对应函数指针）
统计依据: lsp_get_document_outline 列出 65 个 extern 声明 + syscalls[] 数组 65 个条目；部分如 sys_getuid 系列指向同一函数，实际独立实现约 55 个

### Q02_028 README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）

README.md 未明确声称兼容特定 syscall 标准或列表。其 Progress 清单列出 Multicore boot / Memory alloc / Page Table / Timer interrupt / S mode extern interrupt / SD card driver / Process management / File system / User program / Steady keyboard input 等均已勾选完成。代码分发表实际注册约 65 个系统调用，覆盖进程管理、文件系统、内存管理、信号、时间等类别，与 README 声称的功能模块一致。

### Q02_029 `_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）

未见该命名模式。grep 搜索 `_impl\b|sys_[a-z0-9_]*_impl` 在全部 207 个文件中 0 命中。本仓库采用标准 xv6 风格：syscall 分发函数命名为 `sys_xxx`（如 sys_write、sys_fork），不区分 `sys_xxx` 与 `sys_xxx_impl` 两层。

### Q02_030 是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）

已实现

### Q02_031 非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）

未发现

### Q02_032 信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）

仅支持进程级信号发送。sys_kill (kernel/syscall/syssignal.c:134) 通过 kill(pid, sig) 向指定 pid 发送信号。未发现 sys_tkill（线程级）和 sys_tgkill（进程组级）的实现。

### Q02_033 中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）

通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）

### Q02_034 是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）

未发现
