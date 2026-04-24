# 02_boot_trap — Baseline vs Agent

- 题库题数: 34
- baseline `report_quality_score`: 0.98
- agent `report_quality_score`: 0.98

| question_id | type | agreement | better_side(初值) | baseline_se | baseline_sc | agent_se | agent_sc | baseline_value | agent_value |
|---|---|:---|:---|---:|---:|---:|---:|---|---|
| Q02_001 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 1.00 | 1.00 | linker/linker64.ld: ENTRY(_entry); kernel/entry.S: _entry:; kernel/entry_k210.S: _start:; kernel/entry_qemu.S: _entry: | 启动入口位于汇编文件中的 `_entry`（QEMU 平台）和 `_start`（K210 平台）标签。证据：`linker/qemu.ld:2` 设置 `ENTRY(_entry)`，`kernel/entry_qemu.S:2` 定义 `_entry` 标签；`linker/k210.ld:2` 设置 `ENTRY(_start)`，`kernel/entry_k210.S:2` 定义 `_start` 标签。两个入口均设置栈... |
| Q02_002 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | 固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI） | 固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI） |
| Q02_003 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q02_004 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 1.00 | mstatus (MPP bits), mepc, mtvec, sstatus, satp, stvec | RISC-V sstatus 寄存器的关键位：SSTATUS_SPP（位 8，Previous mode）、SSTATUS_SPIE（位 5，Supervisor Previous Interrupt Enable）、SSTATUS_SIE（位 1，Supervisor Interrupt Enable）。证据：`include/hal/riscv.h:48-50` 定义这些宏，`kernel/trap/trap.c:176-17... |
| Q02_005 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_006 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | SBI rust_main → _entry (entry.S) → main (main.c) → scheduler() | 启动跳转链：1) 固件 (SBI/OpenSBI) 传递控制权给 `_entry`/`_start`（`kernel/entry_qemu.S:2`/`kernel/entry_k210.S:2`）→ 2) 汇编入口设置栈指针（`add sp, sp, t0`）→ 3) 调用 `main()`（`call main`）→ 4) `main()` 初始化 CPU、页表、陷阱、进程等（`kernel/main.c:42-105`）→ ... |
| Q02_007 | fill_in | 表述差异 | 待酌 | 0.95 | 1.00 | 0.90 | 1.00 | BSS 清零 (BSS Clearing): implemented [sbi/psicasbi/src/main.rs]<br>早期串口输出 (Early Serial/UART Output): implemented [sbi/psicasbi/src/hal/uart/]<br>设备树解析 (Device Tree Blob parsing, DTB): not_found [kernel/main.c 接收 dtb_pa... | BSS 清零 (BSS Clearing): implemented [linker/k210.ld:43-46 定义 sbss_clear/ebss_clear 符号，链接脚本自动处理]<br>早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:consoleinit() 初始化串口，kernel/main.c:50 调用 consoleinit()]... |
| Q02_008 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_009 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_010 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.85 | 1.00 | Makefile 使用 platform 变量 (k210/qemu) 选择不同入口文件和 SBI | 通过 Makefile 中的 platform 变量和条件编译区分平台。证据：`Makefile` 支持 `platform=qemu` 选项，默认构建 K210 版本。链接脚本选择：`linker/k210.ld`（ENTRY=_start）用于 K210，`linker/qemu.ld`（ENTRY=_entry）用于 QEMU。汇编入口文件：`kernel/entry_k210.S` 和 `kernel/entry_qemu... |
| Q02_011 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q02_012 | tri_state_impl | 一致 | tie | 0.80 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q02_013 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_014 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 未发现 visionfive/jh7110/loongarch 支持。仅支持 k210 和 qemu 平台，通过 Makefile 的 platform 变量选择 | 支持双平台启动：K210 和 QEMU。证据：`kernel/entry_k210.S` 和 `kernel/entry_qemu.S` 分别为两个平台提供入口；`linker/k210.ld` 和 `linker/qemu.ld` 提供不同链接脚本。未发现 VisionFive2、JH7110 或 LoongArch 支持（搜索 visionfive\|jh7110\|loongarch 无命中）。 |
| Q02_015 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 1.00 | 1.00 | kernelvec (kernel/trap/kernelvec.S), uservec (kernel/trap/trampoline.S) | 陷阱向量入口位于 `kernel/trap/kernelvec.S:9` 的 `kernelvec` 标签（内核陷阱）和 `kernel/trap/trampoline.S:15` 的 `uservec` 标签（用户陷阱）。`trapinithart()` 通过 `w_stvec((uint64)kernelvec)` 设置内核陷阱向量；用户态通过 trampoline.S 中的 uservec 进入 `usertrap()`。 |
| Q02_016 | single_choice | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | C. 用户地址空间预留页（trampoline/trap_context page） | 用户地址空间预留页（trampoline/trap_context page） |
| Q02_017 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | include/trap.h: struct trapframe，包含 32 个通用寄存器 + 32 个浮点寄存器 + fcsr，共 552 字节 | 定义在 `include/trap.h:19-54` 的 `struct trapframe`。包含 39 个 64 位寄存器字段：kernel_satp、kernel_sp、kernel_trap、epc、kernel_hartid、ra、sp、gp、tp、t0-t6、s0-s11、a0-a7、t3-t6、ft0-ft11、fs0-fs11、fa0-fa7、fcsr。总大小为 552 字节（40-544 字节为整数寄存器，288... |
| Q02_018 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_019 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_020 | short_answer | 表述差异 | 待酌 | 1.00 | 1.00 | 0.95 | 1.00 | ecall → usertrap → syscall() → sys_write() → filewrite() | sys_write 调用链：1) 用户态执行 ecall 指令 → 2) `usertrap()` 捕获异常（`kernel/trap/trap.c:105` 检测 EXCP_ENV_CALL）→ 3) 调用 `syscall()`（`kernel/syscall/syscall.c:348`）→ 4) 通过 syscalls 数组分发到 `sys_write()`（`kernel/syscall/sysfile.c`）→ 5) ... |
| Q02_021 | short_answer | 表述差异 | 待酌 | 0.70 | 1.00 | 0.80 | 1.00 | fork: implemented [kernel/syscall/sysproc.c], exec: implemented [kernel/syscall/sysfile.c], mmap: implemented [kernel/syscall/sysmem.c], open: implemented [kernel/syscall/sysfile.c], write: implemented [kernel/syscall... | 高价值 syscall 实现状态：<br>- fork: implemented [kernel/syscall/sysproc.c:sys_fork() 调用 fork()]<br>- exec/execve: implemented [kernel/syscall/sysproc.c:sys_exec() 调用 execve()]<br>- mmap: implemented [kernel/syscall/sysmem.c:... |
| Q02_022 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_023 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_024 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_025 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 是，handle_page_fault() 在 kernel/trap/trap.c 中调用，处理 LOAD/HEAP/STACK/MMAP 段的缺页 | 存在联动。入口点：`kernel/trap/trap.c:405` 的 `handle_excp()` 函数检测 EXCP_STORE_PAGE/EXCP_LOAD_PAGE 等异常，调用 `handle_page_fault()`（`include/mm/vm.h:76`）。`handle_page_fault()` 在 `kernel/mm/vm.c` 中实现，处理 CoW（写时复制）和懒分配。证据：`kernel/mm/vm... |
| Q02_026 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 多核支持：hart 0 初始化后通过 IPI 唤醒其他 hart，每个 hart 独立初始化 trap/时钟 | 多核一致。证据：`kernel/main.c:77-92` 显示 hart 0 初始化完成后通过 `sbi_send_ipi()` 唤醒其他 hart；其他 hart（hart 1+）执行 `kvminithart()`、`trapinithart()`、`plicinithart()` 初始化。每个 hart 独立调用 `trapinithart()` 设置自己的 stvec，符合 per-CPU 陷阱初始化模式。与第 9 章多... |
| Q02_027 | fill_in | 表述差异 | 待酌 | 0.90 | 1.00 | 0.90 | 1.00 | 分发表路径：kernel/syscall/syscall.c<br>完整实现 ✅ (implemented): 约 60 个<br>桩/ENOSYS/return 0 🔸 (stub): 约 5 个，代表性例子：sys_rt_sigtimedwait, sys_clock_settime<br>未注册 ❌ (not_found): 约 10 个<br>统计依据（grep 或 outline 方式）: grep -c 'sys_' ... | 分发表路径：kernel/syscall/syscall.c:193-268 (syscalls[] 数组)<br>完整实现 ✅ (implemented): 约 60 个（基于 syscalls[] 数组中注册的 syscall 数量，大多数有实际实现逻辑）<br>桩/ENOSYS/return 0 🔸 (stub): 约 5 个，代表性例子：sys_getuid() 始终返回 0（kernel/syscall/sysproc.... |
| Q02_028 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | README.md/README_cn.md 未明确列出 syscall 清单，仅说明是 xv6-riscv 移植。代码实现与 xv6 标准 syscall 基本一致 | README.md 未明确列出 syscall 兼容性声称，仅提及支持进程管理、文件系统、用户程序等高级功能。代码实际实现了约 70 个 syscall（见 kernel/syscall/syscall.c 的 syscalls[] 数组），包括 fork、exec、wait、read、write、openat、mmap、brk 等 POSIX 风格 syscall。无 README 声称与代码不一致的情况。 |
| Q02_029 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 1.00 | 未见该命名模式 | 未见该命名模式。在仓库 193 个文件中搜索 `_impl\b\|sys_[a-z0-9_]*_impl` 正则表达式，0 命中。该仓库采用直接命名（如 sys_write、sys_fork）而非 `_impl` 后缀分离接口与实现的模式。 |
| Q02_030 | tri_state_impl | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q02_031 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q02_032 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 1.00 | 仅实现进程级 sys_kill，未见 tkill/tgkill | 仅支持进程级信号发送。证据：`kernel/syscall/syssignal.c:134` 实现 `sys_kill()`，调用 `kill(pid, sig)` 向进程发送信号。未搜索到 sys_tkill 或 sys_tgkill 实现（grep 搜索无命中），不支持线程级或进程组级信号发送。 |
| Q02_033 | single_choice | 一致 | tie | 1.00 | 1.00 | 1.00 | 1.00 | A. 通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号） | 通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号） |
| Q02_034 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | not_found | not_found |

统计: 一致=18, 表述差异=16, 结论冲突=0
