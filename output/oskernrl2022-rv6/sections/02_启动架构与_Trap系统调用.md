### Q02_001 启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）

启动入口位于 `linker/kernel.ld:2` 定义的 `ENTRY(_entry)`，实际汇编入口标签为 `src/entry.S:5` 的 `_entry`。链接脚本设置基址为 0x80200000，`_entry` 标签处开始执行多核启动检测逻辑。

### Q02_002 启动链更接近哪种交接方式？

固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）

### Q02_003 是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）

已实现

### Q02_004 模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）

RISC-V S 模式切换涉及：
1. sstatus 寄存器的 SPP 位 (bit 8)：清除为 0 表示返回用户模式
2. sstatus 寄存器的 SPIE 位 (bit 5)：设置使能用户模式中断
3. sepc 寄存器：设置返回用户态的 PC
4. satp 寄存器：切换用户页表
5. sret 指令：执行特权级切换返回
证据：`src/trap.c:154-170` usertrapret() 函数中通过 w_sstatus/w_sepc/w_satp 设置后调用 sret。

### Q02_005 是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）

已实现

### Q02_006 从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）

启动跳转链：
1. `linker/kernel.ld:ENTRY(_entry)` 设置入口点
2. `src/entry.S:_entry` 汇编入口，检测__first_boot_magic判断是否首核启动
3. `src/entry.S:_secondary_boot` 次级核启动路径，设置每核独立栈
4. `src/main.c:main()` C 语言内核主入口，执行 kvminit/trapinithart/procinit 等初始化
5. `src/main.c:scheduler()` 启动调度器运行第一个用户进程
证据：`src/entry.S:5-22` 调用 `call main`，`src/main.c:44-95` 完整初始化流程。

### Q02_007 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）

BSS 清零 (BSS Clearing): implemented [linker/kernel.ld:48-52 定义.sbss.bss.bss.*段，由链接器自动处理]
早期串口输出 (Early Serial/UART Output): implemented [src/printf.c:30-34 使用 sbi_console_putchar 输出]
设备树解析 (Device Tree Blob parsing, DTB): not_found [main() 接收 dtb_pa 参数但未发现解析代码]
页表初始化时机 (Page Table Init): implemented [src/main.c:63-64 kvminit 在 MMU 启用前建立映射，kvminithart 开启 MMU]

### Q02_008 是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）

未发现

### Q02_009 是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）

已实现

### Q02_010 构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）

Makefile 条件编译：
1. 平台选择：`MAC?=SIFIVE_U`，支持 QEMU 和 SIFIVE_U，通过-D$(MAC) 传递宏定义
2. 文件系统选择：`FS?=FAT`，支持 FAT 和 RAM，通过-D$(FS) 传递
3. 架构固定为 RISC-V 64：`CFLAGS += -march=rv64g -mcmodel=medany`
4. 入口文件固定：`$K/entry.o` 始终链接，由 linker/kernel.ld 的 ENTRY(_entry) 指定
证据：`Makefile:6-15` 平台宏定义，`Makefile:73-77` 编译标志。

### Q02_011 对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）

已实现

### Q02_012 MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）

已实现

### Q02_013 是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）

已实现

### Q02_014 是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）

未发现多平台支持。代码仅支持 QEMU sifive_u 机和 FU740 板型（通过 MAC=SIFIVE_U 或 MAC=QEMU 切换）。搜索 visionfive、jh7110、loongarch 关键词均 0 命中。Makefile 中仅通过-D$(MAC) 条件编译区分 QEMU 和 SIFIVE_U 两种平台，差异在于磁盘驱动链接对象不同（link_null.o vs link_disk.o）。

### Q02_015 trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）

Trap 向量入口分两种：
1. 用户态 trap：`src/trampoline.S:17` 的 `uservec` 标签，通过 w_stvec 设置到 stvec 寄存器
2. 内核态 trap：`src/kernelvec.S:9` 的 `kernelvec` 标签，在 trapinithart() 中设置
证据：`src/trap.c:54` w_stvec((uint64)kernelvec) 设置内核向量，`src/trap.c:138` w_stvec(TRAMPOLINE + (uservec - trampoline)) 设置用户向量。

### Q02_016 trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？

用户地址空间预留页（trampoline/trap_context page）

### Q02_017 TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）

定义于 `src/include/trap.h:17-60` 的 `struct trapframe`。
包含寄存器：
- 内核元数据：kernel_satp/kernel_sp/kernel_trap/epc/kernel_hartid (5 个，40 字节)
- 通用寄存器：ra/sp/gp/tp/t0-t2/s0-s1/a0-a7/s2-s11/t3-t6 (33 个，264 字节)
总计 38 个字段，288 字节（0-280 行，最后一个 t6 在偏移 280，占 8 字节）。
证据：`src/include/trap.h:17-60` 完整定义，注释标明每个字段偏移。

### Q02_018 是否存在系统调用分发表（syscall table / match 分发）？（必须三态）

已实现

### Q02_019 系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）

已实现

### Q02_020 选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。

sys_write 调用链：
1. 用户态执行 ecall 指令触发 trap
2. `src/trampoline.S:uservec` 保存寄存器到 trapframe，切换到内核页表，跳转到 usertrap
3. `src/trap.c:usertrap:93` 检测 scause==EXCP_ENV_CALL(8)，调用 syscall()
4. `syscall/syscall.c:syscall:8` 从 a7 读取 syscall 号，从 syscalls[] 数组索引获取函数指针
5. `src/sysfile.c:sys_write:234` 执行实际写操作，调用 filewrite()
6. `src/trap.c:usertrapret:133` 恢复用户态上下文，通过 trampoline.S:userret 的 sret 返回
证据：`src/trap.c:93-105` syscall 分发，`src/sysfile.c:234-246` sys_write 实现。

### Q02_021 列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。

高价值 syscall 实现状态：
1. sys_execve: implemented [src/sysproc.c:11-34 完整实现，调用 exec()]
2. sys_write: implemented [src/sysfile.c:234-246 调用 filewrite()]
3. sys_read: implemented [src/sysfile.c:218-232 调用 fileread()]
4. sys_openat: implemented [src/sysfile.c:39-143 完整实现]
5. sys_mmap: implemented [src/sysfile.c:895-922 调用 do_mmap()]
6. sys_munmap: implemented [src/sysfile.c:924-932 调用 do_munmap()]
7. sys_clone: implemented [src/sysproc.c:109-124 调用 clone()]
8. sys_exit: implemented [src/sysproc.c:173-181 调用 exit()]
9. sys_kill: implemented [src/syssig.c:94-100 调用 kill()]
10. sys_brk: implemented [src/sysproc.c:163-171 调用 growproc()]
所有 syscall 均有实际逻辑实现，非桩函数。

### Q02_022 是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）

已实现

### Q02_023 时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）

已实现

### Q02_024 是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）

已实现

### Q02_025 缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）

声明但未发现完整实现。`src/include/vm.h:42-43` 声明了 handle_page_fault 和 kernel_handle_page_fault 函数，但在代码中搜索 handle_page_fault 仅找到声明，未发现实际实现和调用点。README 声称"完成了缺页中断的处理"，但代码中 usertrap() 的异常处理分支仅处理 EXCP_ENV_CALL(系统调用) 和 devintr(设备中断)，对缺页异常 (EXCP_LOAD_PAGE=13/EXCP_STORE_PAGE=15) 仅打印错误并设置 p->killed=SIGTERM，未调用页故障处理函数。证据：`src/trap.c:120-126` 缺页时仅打印错误。

### Q02_026 与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）

多核实现一致。`src/main.c:44-95` 显示：
1. 首核 (hart 0)：执行 kvminit()->kvminithart()->trapinithart()->procinit()，然后启动其他核
2. 次级核 (hart 1-4)：等待 started==0 自旋，然后执行 kvminithart()->trapinithart()
每核独立调用 trapinithart() 设置 stvec，符合 per-CPU trap 初始化要求。时钟初始化 timerinit() 仅在首核执行一次（全局 tickslock），但 set_next_timeout() 在每核 trapinithart() 中调用，确保每核都有独立的定时器中断。证据：`src/main.c:63-68` 首核初始化序列，`src/main.c:83-88` 次级核初始化。

### Q02_027 Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）

分发表路径：syscall/syscall.c:8-17（引用 syscalls[] 数组）
完整实现 ✅ (implemented): 40+ 个（基于 src/sysproc.c、src/sysfile.c、src/systime.c、src/syssig.c、src/syspoll.c 中的 sys_* 函数统计）
桩/ENOSYS/return 0 🔸 (stub): 2 个，代表性例子：sys_exit_group [src/syssig.c:18-21 直接 return 0]、sys_ppoll [src/syspoll.c:14-16 直接 return 0]
未注册 ❌ (not_found): 0 个（所有 syscall 均通过 sys.sh 脚本生成到 syscalls[] 数组）
统计依据：grep_in_repo 搜索 'sys_[a-z0-9_]*(' 命中 53 个函数定义，检查 syscall/syscall.c 的 syscall() 函数通过 syscalls[num]() 间接调用，sys.sh 脚本生成分发表。文档 doc/内核实现--系统调用.md:374 列出 syscalls[] 数组结构。

### Q02_028 README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）

README.md 未明确列出 syscall 兼容性声称，仅在工作总结中提到：
- "完善了用户内存管理和内核内存管理"
- "完善了 mmap 的机制"
- "完成了缺页中断的处理"
- "完成了信号相关的操作"
- "完成了对本地回环地址的 Socket 支持"
代码验证：
- mmap：已实现 sys_mmap/sys_munmap [src/sysfile.c:895-932]
- 信号：已实现 sys_kill/sys_rt_sigaction/sys_rt_sigprocmask/sys_rt_sigreturn [src/syssig.c]
- 缺页中断：仅声明 handle_page_fault [src/include/vm.h:42-43]，未发现实现和调用
- Socket：未发现 socket 相关 syscall 实现（搜索 socket 仅找到头文件声明）
结论：README 声称部分与代码一致（mmap、信号），缺页中断和 Socket 声称与代码不符。

### Q02_029 `_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）

未见该命名模式。在 repos/oskernrl2022-rv6 全仓库搜索 `_impl\b|sys_[a-z0-9_]*_impl` 模式，0 命中。该仓库采用直接命名方式（如 sys_write、sys_execve），未使用 `_impl` 后缀分离接口与实现的命名模式。syscall 分发直接通过 syscalls[] 数组索引调用 sys_* 函数。

### Q02_030 是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）

桩实现

### Q02_031 非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）

未发现

### Q02_032 信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）

已实现：
1. 进程级：sys_kill [src/syssig.c:94-100] 通过 kill(pid, sig) 向指定 pid 进程发送信号
2. 线程组级：sys_tgkill [src/syssig.c:102-110] 通过 tgkill(pid, tid, sig) 向指定线程组内的线程发送信号
未发现：sys_tkill（纯线程级信号发送）
kill() 实现 [src/proc.c:752-768] 遍历 procs 数组查找 pid，设置 p->sig_pending 和 p->killed。
tgkill() 实现 [src/proc.c:785-791] 先通过 cmp_parent() 验证 pid-tid 的父子关系，再调用 kill(tid, sig)。
证据：`src/syssig.c:94-110` sys_kill/sys_tgkill 定义，`src/proc.c:752-791` kill/tgkill 实现。

### Q02_033 中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）

通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）

### Q02_034 是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）

未发现
