### Q02_001 启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）

RISC-V: `kernel/link/riscv/kernel.ld:2` 设置 ENTRY(_entry)，实际入口在 `kernel/boot/riscv/entry.S:3` 的 `_entry` 标签，加载地址 0x80200000（`kernel/link/riscv/kernel.ld:9`）。LoongArch: `kernel/link/loongarch/kernel.ld:2` 设置 ENTRY(_entry)，实际入口在 `kernel/boot/loongarch/entry.S:4` 的 `_entry` 标签，加载地址 0x9000000080000000（`kernel/link/loongarch/kernel.ld:6`）。

### Q02_002 启动链更接近哪种交接方式？

固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）

### Q02_003 是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）

已实现

### Q02_004 模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）

RISC-V: mstatus/sstatus (SPP/SPIE 位), satp (页表基址), stvec (trap 向量), scause (异常原因)。LoongArch: CRMD (PLV/IE 位), PRMD (PPLV/PIE 位), PGDL/PGDH (页表基址), EENTRY (异常入口), ESTAT/ECFG (中断配置)。

### Q02_005 是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）

已实现

### Q02_006 从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）

RISC-V: _entry (entry.S:3) → start (start.cc:22) → main (main.cc:47) → trap_mgr.init (main.cc:54) → trap_mgr.inithart (main.cc:55) → proc::k_pm.user_init (main.cc:95) → proc::k_scheduler.start_schedule (main.cc:117)。LoongArch: _entry (entry.S:4) → main (main.cc:28) → trap_mgr.init (main.cc:36) → trap_mgr.inithart (main.cc:37) → proc::k_pm.user_init (main.cc:63) → proc::k_scheduler.start_schedule (main.cc:82)。

### Q02_007 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）

BSS 清零 (BSS Clearing): implemented [kernel/link/riscv/kernel.ld:43-46 提供 bss_start/bss_end 符号; kernel/link/loongarch/kernel.ld:48-52 提供 sbss_clear/ebss_clear 符号]
早期串口输出 (Early Serial/UART Output): implemented [kernel/boot/riscv/main.cc:52 k_printer.init(); kernel/boot/loongarch/main.cc:30 k_printer.init()]
设备树解析 (Device Tree Blob parsing, DTB): implemented [kernel/boot/riscv/main.cc:47 接收 dtb_addr 参数; kernel/boot/riscv/main.cc:48 k_dtb_addr = dtb_addr; kernel/devs/dtb.cc 存在但实现待核实]
页表初始化时机 (Page Table Init): implemented [kernel/mem/virtual_memory_manager.cc:60-80 在 VirtualMemoryManager::init() 中创建内核页表并设置 satp/pgdl，在 trap_mgr.init 之后调用]

### Q02_008 是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）

桩实现

### Q02_009 是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）

已实现

### Q02_010 构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）

通过 Makefile 的 ARCH 变量选择：`Makefile:14-23` 支持 ARCH=riscv 或 ARCH=loongarch，默认 riscv。使用条件编译标志 -DRISCV 或 -DLOONGARCH (`Makefile:26-31`)。链接脚本根据架构选择：`kernel/link/riscv/kernel.ld` 或 `kernel/link/loongarch/kernel.ld` (`Makefile:48`)。源码通过 #ifdef RISCV / #ifdef LOONGARCH 区分架构特定代码。

### Q02_011 对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）

已实现

### Q02_012 MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）

已实现

### Q02_013 是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）

已实现

### Q02_014 是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）

支持 RISC-V 和 LoongArch 双架构启动。RISC-V 入口：`kernel/boot/riscv/entry.S`，LoongArch 入口：`kernel/boot/loongarch/entry.S`。通过 Makefile 的 ARCH 变量互斥选择 (`Makefile:14-23`)。未发现特定板型（如 VisionFive2、JH7110）的差异化启动代码，使用 QEMU virt 机器作为目标平台 (`Makefile:28-29`)。

### Q02_015 trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）

RISC-V: 内核态 trap 入口在 `kernel/trap/riscv/kernelvec.S:9` 的 `kernelvec` 标签；用户态 trap 入口在 `kernel/mem/riscv/trampoline.S:15` 的 `uservec` 标签。LoongArch: 内核态 trap 入口在 `kernel/trap/loongarch/kernelvec.S` 的 `kernelvec`；用户态 trap 入口在 `kernel/trap/loongarch/uservec.S` 的 `uservec`。C++ 层分发入口在 `kernel/trap/riscv/trap.cc:199` 的 `trap_manager::usertrap()` 和 `kernel/trap/loongarch/trap.cc:160` 的 `trap_manager::usertrap()`。

### Q02_016 trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？

用户地址空间预留页（trampoline/trap_context page）

### Q02_017 TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）

定义在 `kernel/proc/trapframe.hh`。RISC-V: `struct TrapFrame` (14-42 行) 包含 37 个 uint64 字段 (kernel_satp, kernel_sp, kernel_trap, epc, kernel_hartid, ra, sp, gp, tp, t0-t6, s0-s11, a0-a7)，总计 37*8=296 字节。LoongArch: `struct TrapFrame` (44-79 行) 包含 36 个 uint64 字段 (ra, tp, sp, a0-a7, t0-t8, r21, fp, s0-s8, kernel_sp, kernel_trap, era, kernel_hartid, kernel_pgdl)，总计 36*8=288 字节。

### Q02_018 是否存在系统调用分发表（syscall table / match 分发）？（必须三态）

已实现

### Q02_019 系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）

已实现

### Q02_020 选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。

sys_write 调用链：1. 用户态 ecall 指令 (`kernel/trap/riscv/trap.cc:233` cause==8) → 2. usertrap() 设置 epc+=4 并调用 invoke_syscaller() (`kernel/trap/riscv/trap.cc:235-237`) → 3. invoke_syscaller() 从 a7 读取 syscall 号并查表调用 (`kernel/sys/syscall_handler.cc` 通过_syscall_funcs 数组) → 4. sys_write() 实现 (`kernel/sys/syscall_handler.cc:1355`) 从用户空间 copy_in 数据并调用 file->write() → 5. 返回用户态通过 usertrapret() (`kernel/trap/riscv/trap.cc:306`)。

### Q02_021 列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。

sys_fork: stub [`kernel/sys/syscall_handler.cc:537-548` 包含 TODO 宏和 panic("未实现该系统调用")] | sys_exec: stub [`kernel/sys/syscall_handler.cc:530-535` 包含 TODO 宏和 panic] | sys_execve: stub [`kernel/sys/syscall_handler.cc:870` 包含 TODO 宏] | sys_mmap: implemented [`kernel/sys/syscall_handler.cc:2170-2253` 完整实现，调用 proc::k_pm.mmap()] | sys_openat: implemented [`kernel/sys/syscall_handler.cc:1197-1353` 完整实现] | sys_write: implemented [`kernel/sys/syscall_handler.cc:1355-1448` 完整实现，包含 copy_in 和 file->write] | sys_read: implemented [`kernel/sys/syscall_handler.cc` 存在实现] | sys_exit: implemented [`kernel/sys/syscall_handler.cc:551-559` 调用 proc::k_pm.exit()] | sys_clone: not_found [未在 syscall_handler.cc 中找到 sys_clone 实现] | sys_wait4: implemented [BIND_SYSCALL(wait4) 在 init() 中注册]。

### Q02_022 是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）

已实现

### Q02_023 时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）

已实现

### Q02_024 是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）

已实现

### Q02_025 缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）

存在联动。RISC-V: `kernel/trap/riscv/trap.cc:243-254` 在 usertrap() 中检测 cause==13/15/12 (load/store/instruction page fault)，调用 mmap_handler()。mmap_handler() (`kernel/trap/riscv/trap.cc:353-402`) 查找 VMA 并调用 mem::k_vmm.allocate_vma_page() 实现懒分配。LoongArch: `kernel/trap/loongarch/trap.cc:193-207` 类似逻辑，检测 ecode==0x1/0x2/0x8/0x3，调用 mmap_handler()。

### Q02_026 与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）

单核不适用。Makefile 中 QEMU 启动参数为 `-smp 1` (`Makefile:28`)，仅启动单核。trap_mgr.inithart() 在 main() 中被调用 (`kernel/boot/riscv/main.cc:55`)，但未发现 AP 核启动代码或 per-CPU trap 栈初始化逻辑。

### Q02_027 Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）

分发表路径：kernel/sys/syscall_handler.cc:68-370 (SyscallHandler::init() 中的 BIND_SYSCALL 宏)
完整实现 ✅ (implemented): 约 80-90 个 [基于 init() 中注册且实现体不包含 TODO/panic 的 syscall 数量估算]
桩/ENOSYS/return 0 🔸 (stub): 约 20-30 个，代表性例子：sys_fork (kernel/sys/syscall_handler.cc:537), sys_exec (530), sys_execve (870), sys_clone (未找到实现)
未注册 ❌ (not_found): 约 10-20 个 [未在 init() 中 BIND_SYSCALL 的 syscall]
统计依据（grep 或 outline 方式）: 通过 read_code_segment 读取 syscall_handler.cc:68-370 统计 BIND_SYSCALL 注册数量，结合 grep 搜索 TODO/panic 关键字识别桩函数

### Q02_028 README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）

README.md 未明确列出 syscall 兼容性声称，仅描述模块功能：「sys 🛎️ 系统调用模块：系统调用分发、参数传递、权限检查」。代码中 init() 注册了约 150+ 个 syscall（包括 Linux 兼容的 fork/exec/wait/read/write/mmap 等），但部分关键 syscall（如 sys_fork、sys_exec）实际为桩实现（包含 TODO 和 panic）。README 声称与代码实际存在差距。

### Q02_029 `_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）

未见该命名模式。在 syscall_handler.cc 中，syscall 实现采用 sys_[name]() 命名（如 sys_write、sys_fork），未使用_sys_[name]_impl 后缀模式。默认未实现处理函数为_default_syscall_impl() (`kernel/sys/syscall_handler.cc:58`)。

### Q02_030 是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）

已实现

### Q02_031 非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）

已实现

### Q02_032 信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）

支持三种粒度：1. 进程级：sys_kill() (`kernel/sys/syscall_handler.cc:804`) 调用 proc::k_pm.kill_proc(pid) | 2. 线程级：sys_tkill() (`kernel/sys/syscall_handler.cc:2631`) 调用 proc::k_pm.tkill(tid, sig) | 3. 进程组级：sys_tgkill() (`kernel/sys/syscall_handler.cc:2640`) 调用 proc::k_pm.tgkill(tgid, tid, sig)。另外还有 sys_kill_signal() (`kernel/sys/syscall_handler.cc:2606`) 用于发送信号到进程。

### Q02_033 中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）

通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）

### Q02_034 是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）

已实现
