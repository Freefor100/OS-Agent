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
