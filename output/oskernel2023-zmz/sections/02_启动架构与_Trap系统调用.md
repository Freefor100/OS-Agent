### Q02_001 启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）

启动入口位于汇编文件中的 `_entry`（QEMU 平台）和 `_start`（K210 平台）标签。证据：`linker/qemu.ld:2` 设置 `ENTRY(_entry)`，`kernel/entry_qemu.S:2` 定义 `_entry` 标签；`linker/k210.ld:2` 设置 `ENTRY(_start)`，`kernel/entry_k210.S:2` 定义 `_start` 标签。两个入口均设置栈指针后跳转到 `main()` 函数（`kernel/main.c:42`）。

### Q02_002 启动链更接近哪种交接方式？

固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）

### Q02_003 是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）

已实现

### Q02_004 模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）

RISC-V sstatus 寄存器的关键位：SSTATUS_SPP（位 8，Previous mode）、SSTATUS_SPIE（位 5，Supervisor Previous Interrupt Enable）、SSTATUS_SIE（位 1，Supervisor Interrupt Enable）。证据：`include/hal/riscv.h:48-50` 定义这些宏，`kernel/trap/trap.c:176-177` 在 usertrapret() 中操作这些位实现模式切换。

### Q02_005 是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）

已实现

### Q02_006 从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）

启动跳转链：1) 固件 (SBI/OpenSBI) 传递控制权给 `_entry`/`_start`（`kernel/entry_qemu.S:2`/`kernel/entry_k210.S:2`）→ 2) 汇编入口设置栈指针（`add sp, sp, t0`）→ 3) 调用 `main()`（`call main`）→ 4) `main()` 初始化 CPU、页表、陷阱、进程等（`kernel/main.c:42-105`）→ 5) 创建第一个用户进程 `userinit()` → 6) 进入调度器 `scheduler()`。

### Q02_007 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）

BSS 清零 (BSS Clearing): implemented [linker/k210.ld:43-46 定义 sbss_clear/ebss_clear 符号，链接脚本自动处理]
早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:consoleinit() 初始化串口，kernel/main.c:50 调用 consoleinit()]
设备树解析 (Device Tree Blob parsing, DTB): not_found [main() 接收 dtb_pa 参数但未发现解析代码，仅传递给后续初始化]
页表初始化时机 (Page Table Init): implemented [kernel/main.c:53-54: kvminit() 创建页表，kvminithart() 启用 MMU，在 trapinithart() 之前]

### Q02_008 是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）

已实现

### Q02_009 是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）

已实现

### Q02_010 构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）

通过 Makefile 中的 platform 变量和条件编译区分平台。证据：`Makefile` 支持 `platform=qemu` 选项，默认构建 K210 版本。链接脚本选择：`linker/k210.ld`（ENTRY=_start）用于 K210，`linker/qemu.ld`（ENTRY=_entry）用于 QEMU。汇编入口文件：`kernel/entry_k210.S` 和 `kernel/entry_qemu.S` 分别编译。

### Q02_011 对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）

已实现

### Q02_012 MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）

已实现

### Q02_013 是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）

已实现

### Q02_014 是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）

支持双平台启动：K210 和 QEMU。证据：`kernel/entry_k210.S` 和 `kernel/entry_qemu.S` 分别为两个平台提供入口；`linker/k210.ld` 和 `linker/qemu.ld` 提供不同链接脚本。未发现 VisionFive2、JH7110 或 LoongArch 支持（搜索 visionfive|jh7110|loongarch 无命中）。

### Q02_015 trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）

陷阱向量入口位于 `kernel/trap/kernelvec.S:9` 的 `kernelvec` 标签（内核陷阱）和 `kernel/trap/trampoline.S:15` 的 `uservec` 标签（用户陷阱）。`trapinithart()` 通过 `w_stvec((uint64)kernelvec)` 设置内核陷阱向量；用户态通过 trampoline.S 中的 uservec 进入 `usertrap()`。

### Q02_016 trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？

用户地址空间预留页（trampoline/trap_context page）

### Q02_017 TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）

定义在 `include/trap.h:19-54` 的 `struct trapframe`。包含 39 个 64 位寄存器字段：kernel_satp、kernel_sp、kernel_trap、epc、kernel_hartid、ra、sp、gp、tp、t0-t6、s0-s11、a0-a7、t3-t6、ft0-ft11、fs0-fs11、fa0-fa7、fcsr。总大小为 552 字节（40-544 字节为整数寄存器，288-536 字节为 FPU 寄存器，加上 8 字节 fcsr）。

### Q02_018 是否存在系统调用分发表（syscall table / match 分发）？（必须三态）

已实现

### Q02_019 系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）

已实现

### Q02_020 选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。

sys_write 调用链：1) 用户态执行 ecall 指令 → 2) `usertrap()` 捕获异常（`kernel/trap/trap.c:105` 检测 EXCP_ENV_CALL）→ 3) 调用 `syscall()`（`kernel/syscall/syscall.c:348`）→ 4) 通过 syscalls 数组分发到 `sys_write()`（`kernel/syscall/sysfile.c`）→ 5) `sys_write()` 调用 `filewrite()` 实现写入。关键证据：`kernel/trap/trap.c:115` 调用 syscall()，`kernel/syscall/syscall.c:368` 通过 `syscalls[num]()` 间接调用。

### Q02_021 列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。

高价值 syscall 实现状态：
- fork: implemented [kernel/syscall/sysproc.c:sys_fork() 调用 fork()]
- exec/execve: implemented [kernel/syscall/sysproc.c:sys_exec() 调用 execve()]
- mmap: implemented [kernel/syscall/sysmem.c:sys_mmap() 调用 do_mmap()]
- munmap: implemented [kernel/syscall/sysmem.c:sys_munmap() 调用 do_munmap()]
- openat: implemented [kernel/syscall/sysfile.c:sys_openat() 调用 nameifrom()]
- write: implemented [kernel/syscall/sysfile.c:sys_write() 调用 filewrite()]
- read: implemented [kernel/syscall/sysfile.c:sys_read() 调用 fileread()]
- clone: implemented [kernel/syscall/sysproc.c:sys_clone()]
- brk/sbrk: implemented [kernel/syscall/sysmem.c:sys_brk()/sys_sbrk()]
- kill: implemented [kernel/syscall/syssignal.c:sys_kill() 调用 kill()]

### Q02_022 是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）

已实现

### Q02_023 时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）

已实现

### Q02_024 是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）

已实现

### Q02_025 缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）

存在联动。入口点：`kernel/trap/trap.c:405` 的 `handle_excp()` 函数检测 EXCP_STORE_PAGE/EXCP_LOAD_PAGE 等异常，调用 `handle_page_fault()`（`include/mm/vm.h:76`）。`handle_page_fault()` 在 `kernel/mm/vm.c` 中实现，处理 CoW（写时复制）和懒分配。证据：`kernel/mm/vm.c` 中的 `page_ref_table` 用于 COW 引用计数，`kernel/mm/mmap.c` 处理懒分配。

### Q02_026 与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）

多核一致。证据：`kernel/main.c:77-92` 显示 hart 0 初始化完成后通过 `sbi_send_ipi()` 唤醒其他 hart；其他 hart（hart 1+）执行 `kvminithart()`、`trapinithart()`、`plicinithart()` 初始化。每个 hart 独立调用 `trapinithart()` 设置自己的 stvec，符合 per-CPU 陷阱初始化模式。与第 9 章多核启动流程一致。

### Q02_027 Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）

分发表路径：kernel/syscall/syscall.c:193-268 (syscalls[] 数组)
完整实现 ✅ (implemented): 约 60 个（基于 syscalls[] 数组中注册的 syscall 数量，大多数有实际实现逻辑）
桩/ENOSYS/return 0 🔸 (stub): 约 5 个，代表性例子：sys_getuid() 始终返回 0（kernel/syscall/sysproc.c:260），sys_prlimit64() 返回 0（kernel/syscall/sysproc.c:265），sys_rt_sigtimedwait() 返回 0（kernel/syscall/syssignal.c:144）
未注册 ❌ (not_found): 0 个（所有 SYS_* 宏在 sysnum.h 中定义并在 syscalls[] 中有对应条目）
统计依据：通过 read_code_segment 阅读 kernel/syscall/syscall.c:193-268 的 syscalls[] 数组，统计约 70 个注册 syscall；抽样检查 sysproc.c、sysfile.c、sysmem.c、syssignal.c 中的实现体，发现少数返回 0 的桩函数。

### Q02_028 README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）

README.md 未明确列出 syscall 兼容性声称，仅提及支持进程管理、文件系统、用户程序等高级功能。代码实际实现了约 70 个 syscall（见 kernel/syscall/syscall.c 的 syscalls[] 数组），包括 fork、exec、wait、read、write、openat、mmap、brk 等 POSIX 风格 syscall。无 README 声称与代码不一致的情况。

### Q02_029 `_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）

未见该命名模式。在仓库 193 个文件中搜索 `_impl\b|sys_[a-z0-9_]*_impl` 正则表达式，0 命中。该仓库采用直接命名（如 sys_write、sys_fork）而非 `_impl` 后缀分离接口与实现的模式。

### Q02_030 是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）

已实现

### Q02_031 非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）

未发现

### Q02_032 信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）

仅支持进程级信号发送。证据：`kernel/syscall/syssignal.c:134` 实现 `sys_kill()`，调用 `kill(pid, sig)` 向进程发送信号。未搜索到 sys_tkill 或 sys_tgkill 实现（grep 搜索无命中），不支持线程级或进程组级信号发送。

### Q02_033 中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）

通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）

### Q02_034 是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）

未发现
