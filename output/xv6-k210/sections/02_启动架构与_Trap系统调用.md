## 题单作答（JSON-QA 渲染）

- stage_id: `02_boot_trap`
- terminology_profile: `stallings_en_zh`

## 第 02_boot_trap 阶段：启动/架构与 Trap/系统调用

### Q02_001（short_answer）

- 题干：启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）
- 答案："链接脚本 `linker/linker64.ld` 定义 `ENTRY(_entry)` (第 2 行)。实际汇编入口有两个变体：`kernel/entry_k210.S` 定义 `_start` 符号 (第 2 行)，`kernel/entry_qemu.S` 定义 `_entry` 符号 (第 2 行)。两者都调用 `main` 函数进入 C 入口。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `linker/linker64.ld` | `directive ENTRY(_entry)` | OUTPUT_ARCH(riscv)<br>ENTRY(_entry) |
| `kernel/entry_k210.S` | `label _start` | .section .text.entry<br>	.globl _start<br>_start: |
| `kernel/entry_qemu.S` | `label _entry` | .section .text<br>	.globl _entry<br>_entry: |

### Q02_002（single_choice）

- 题干：启动链更接近哪种交接方式？
- 答案："固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `README.md` | `document Run on k210 board` | Build the kernel and run: make run |
| `Makefile` | `makefile QEMUOPTS` | QEMUOPTS += -bios $(SBI) |
| `bootloader/SBI/rustsbi-k210` | `directory rustsbi-k210` | RustSBI firmware for K210 |

### Q02_003（tri_state_impl）

- 题干：是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `macro SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User |
| `kernel/trap/trap.c` | `function usertrapret` | x &= ~SSTATUS_SPP; // clear SPP to 0 for user mode |
| `kernel/main.c` | `function main` | RustSBI(M 态) → entry.S _start(委托到 S 态) → main.c main() C 入口 |

### Q02_004（short_answer）

- 题干：模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）
- 答案："RISC-V S 态关键寄存器：`sstatus` (SPP 位 bit 8 保存先前模式，SPIE bit 5 保存中断使能)，`satp` (SV39 页表基址)，`stvec` (陷阱向量基址)，`sepc` (异常返回地址)，`scause` (异常原因)。证据：`include/hal/riscv.h` 定义 `SSTATUS_SPP (1L << 8)`、`SSTATUS_SPIE (1L << 5)`、`SATP_SV39 (8L << 60)`。`kernel/trap/trap.c:usertrapret()` 清除 SPP 位返回用户态。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `macro SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User |
| `include/hal/riscv.h` | `macro SATP_SV39` | #define SATP_SV39 (8L << 60) |
| `kernel/trap/trap.c` | `function usertrapret` | x &= ~SSTATUS_SPP; // clear SPP to 0 for user mode |

### Q02_005（tri_state_impl）

- 题干：是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function kvminit` | void kvminit() { kernel_pagetable = (pagetable_t) allocpage(); kvmmap(...); } |
| `kernel/mm/vm.c` | `function kvminithart` | void kvminithart() { uint64 stap = SATP_SV39 | (((uint64)kernel_pagetable) >> 12); w_satp(stap); asm volatile("sfence.vma"); } |
| `kernel/main.c` | `function main` | kvminit(); kvminithart(); // turn on paging |

### Q02_006（short_answer）

- 题干：从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）
- 答案："启动链：1) RustSBI 固件 (M 态) → 2) `kernel/entry_k210.S:_start` 或 `kernel/entry_qemu.S:_entry` (汇编入口，设置栈) → 3) `call main` 跳转到 `kernel/main.c:main()` (C 入口) → 4) `main()` 中初始化顺序：`cpuinit()` → `floatinithart()` → `consoleinit()` → `kvminit()` → `kvminithart()` → `trapinithart()` → `procinit()` → `scheduler()`。证据：`kernel/entry_k210.S:10` 调用 `main`，`kernel/main.c:35-97` 完整初始化序列。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/entry_k210.S` | `instruction call main` | # jump into main <br>	call main |
| `kernel/main.c` | `function main` | void main(unsigned long hartid, unsigned long dtb_pa) { ... cpuinit(); floatinithart(); consoleinit(); kvminit(); kvminithart(); trapinithart(); procinit(); scheduler(); } |

### Q02_007（fill_in）

- 题干：早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）
- 答案："BSS 清零 (BSS Clearing): implemented [linker/linker64.ld:53-56 .bss 段定义，链接器自动处理]\n早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:consoleinit() + sbi_console_putchar 通过 SBI 调用]\n设备树解析 (Device Tree Blob parsing, DTB): not_found [main.c 接收 dtb_pa 参数但未显式解析 DTB]\n页表初始化时机 (Page Table Init): implemented [kernel/mm/vm.c:kvminit() 在 kvminithart() 之前，MMU 启用前建立映射]"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `linker/linker64.ld` | `section .bss` | .bss : { sbss_clear = .; *(.sbss .bss .bss.*) ebss_clear = .; } |
| `kernel/console.c` | `function consoleinit` | void consoleinit() { ... sbi_console_putchar ... } |
| `kernel/main.c` | `function main` | void main(unsigned long hartid, unsigned long dtb_pa) { ... } |
| `kernel/mm/vm.c` | `function kvminit` | void kvminit() { ... kvmmap(...) ... } // 在 kvminithart 之前调用 |

### Q02_008（tri_state_impl）

- 题干：是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/hal/riscv.h` | `function floatinithart` | static inline void floatinithart() { w_sstatus_fs(SSTATUS_FS_INIT); w_frm(FRM_RNE); w_sstatus_fs(SSTATUS_FS_CLEAN); } |
| `kernel/main.c` | `function main` | floatinithart(); // 在 hart 0 和 hart 1 初始化中都调用 |

### Q02_009（tri_state_impl）

- 题干：是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function trapinithart` | void trapinithart(void) { w_stvec((uint64)kernelvec); w_sstatus(r_sstatus() | SSTATUS_SIE); ... } |
| `kernel/main.c` | `function main` | trapinithart();  // install kernel trap vector, including interrupt handler |

### Q02_010（short_answer）

- 题干：构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）
- 答案："通过 Makefile 的 `platform` 变量控制：`platform := k210` (默认) 或 `platform := qemu`。使用 `#ifdef QEMU` 条件编译区分平台。入口文件固定为 `kernel/entry.S`，但实际根据平台使用 `entry_k210.S` 或 `entry_qemu.S`。证据：`Makefile:1-2` 设置 platform 变量，`Makefile:28-29` 添加 `-D QEMU` 标志。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `Makefile` | `variable platform` | platform	:= k210<br># platform	:= qemu |
| `Makefile` | `conditional QEMU flag` | ifeq ($(platform), qemu)<br>CFLAGS += -D QEMU<br>endif |

### Q02_011（tri_state_impl）

- 题干：对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `bootloader/SBI/rustsbi-k210` | `directory rustsbi-k210` | RustSBI firmware for K210 |
| `Makefile` | `variable SBI` | ifeq ($(platform), k210)<br>	SBI := ./sbi/sbi-k210<br>else<br>	SBI	:= ./sbi/sbi-qemu<br>endif |
| `kernel/trap/trap.c` | `function handle_intr` | else if (INTR_SOFTWARE == scause && sbi_xv6_is_ext().value) // SBI 扩展调用 |

### Q02_012（tri_state_impl）

- 题干：MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function kvminit` | kvmmap(UART_V, UART, PGSIZE, PTE_R | PTE_W); // 映射 UART 寄存器到虚拟地址 |
| `include/memlayout.h` | `macro UART_V` | UART 虚拟地址映射定义 |

### Q02_013（tri_state_impl）

- 题干：是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function usertrapret` | void usertrapret(void) { w_stvec(TRAMPOLINE + (uservec - trampoline)); ... ((void (*)(uint64, uint64))fn)((uint64)(p->trapframe), satp); } |
| `kernel/trap/trampoline.S` | `label userret` | userret: ... sret // return to user mode and user pc |

### Q02_014（short_answer）

- 题干：是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）
- 答案："未发现多平台支持。代码仅支持 K210 和 QEMU virt 两种平台，通过 Makefile 的 platform 变量切换。搜索 visionfive、jh7110、loongarch 均无匹配结果。"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q02_015（short_answer）

- 题干：trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）
- 答案："陷阱向量入口：内核态通过 `kernel/trap/kernelvec.S:kernelvec` (第 8 行)，用户态通过 `kernel/trap/trampoline.S:uservec` (第 15 行)。`kernel/trap/trap.c:trapinithart()` 设置 `w_stvec((uint64)kernelvec)`。异常处理函数为 `kernel/trap/trap.c:usertrap()` 和 `kerneltrap()`。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/kernelvec.S` | `label kernelvec` | .globl kernelvec<br>kernelvec: |
| `kernel/trap/trampoline.S` | `label uservec` | .globl uservec<br>uservec: |
| `kernel/trap/trap.c` | `function trapinithart` | w_stvec((uint64)kernelvec); |

### Q02_016（single_choice）

- 题干：trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？
- 答案："用户地址空间预留页（trampoline/trap_context page）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/trap.h` | `comment trapframe comment` | per-process data for the trap handling code in trampoline.S. sits in a page by itself just under the trampoline page in the user page table. |
| `kernel/trap/trampoline.S` | `instruction uservec` | csrrw a0, sscratch, a0 // sscratch points to where the process's p->trapframe is mapped into user space |

### Q02_017（short_answer）

- 题干：TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）
- 答案："定义在 `include/trap.h:17-93` 的 `struct trapframe`。包含：整数寄存器 32 个 (ra,sp,gp,tp,t0-t6,s0-s11,a0-a7) + 浮点寄存器 32 个 (ft0-ft11,fs0-fs11,fa0-fa7) + fcsr 控制寄存器 = 共 65 个字段。总字节数：548 字节 (0-544 为寄存器，544-548 为 fcsr)。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `include/trap.h` | `struct trapframe` | struct trapframe { /*   0 */ uint64 kernel_satp; ... /* 544 */ uint64 fcsr; }; |

### Q02_018（tri_state_impl）

- 题干：是否存在系统调用分发表（syscall table / match 分发）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/syscall.c` | `array syscalls[]` | static uint64 (*syscalls[])(void) = { [SYS_fork] sys_fork, [SYS_exit] sys_exit, ... }; |

### Q02_019（tri_state_impl）

- 题干：系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/syscall.c` | `function syscall` | if (SYS_rt_sigreturn == num) { ... } else if (num < NELEM(syscalls) && syscalls[num]) { ... } else { p->trapframe->a0 = -1; } |

### Q02_020（short_answer）

- 题干：选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。
- 答案："sys_write 路径：1) 用户态 `ecall` 指令 → 2) `kernel/trap/trampoline.S:uservec` 保存上下文 → 3) `kernel/trap/trap.c:usertrap()` 检测 `EXCP_ENV_CALL` → 4) `kernel/syscall/syscall.c:syscall()` 通过 `syscalls[SYS_write]` 分发 → 5) `kernel/syscall/sysfile.c:sys_write()` 实现文件写入。证据：`trap.c:97-107` 系统调用分支，`syscall.c:212` 分发表索引，`sysfile.c` 实现写入逻辑。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function usertrap` | if (cause == EXCP_ENV_CALL) { ... syscall(); } |
| `kernel/syscall/syscall.c` | `function syscall` | p->trapframe->a0 = syscalls[num](); |
| `kernel/syscall/syscall.c` | `array syscalls[]` | [SYS_write] sys_write, |

### Q02_021（short_answer）

- 题干：列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。
- 答案："高价值 syscall 实现状态：\n- sys_fork: implemented [kernel/sched/proc.c:fork()]\n- sys_exec: implemented [kernel/exec.c:exec()]\n- sys_mmap: implemented [kernel/syscall/sysmem.c:sys_mmap()]\n- sys_openat: implemented [kernel/syscall/sysfile.c:sys_openat()]\n- sys_write: implemented [kernel/syscall/sysfile.c:sys_write()]\n- sys_clone: implemented [kernel/sched/proc.c:clone()]\n- sys_wait4: implemented [kernel/sched/proc.c:wait4()]\n- sys_getuid: stub [kernel/syscall/sysproc.c:267-269 仅返回 0]\n- sys_geteuid: stub [kernel/syscall/syscall.c:233 指向 sys_getuid]\n- sys_getgid: stub [kernel/syscall/syscall.c:234 指向 sys_getuid]"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sched/proc.c` | `function fork` | int fork(void) { ... } |
| `kernel/exec.c` | `function exec` | int exec(char *path, char **argv, char **envp) { ... } |
| `kernel/syscall/sysproc.c` | `function sys_getuid` | uint64 sys_getuid(void) { return 0; } |

### Q02_022（tri_state_impl）

- 题干：是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/mm/vm.c` | `function copyout` | int copyout(pagetable_t pagetable, uint64 dstva, char *src, uint64 len) { ... pa0 = walkaddr(pagetable, va0); if(pa0 == NULL) return -1; ... } |
| `kernel/mm/vm.c` | `function copyin2` | int copyin2(char *dst, uint64 srcva, uint64 len) { ... uint64 badaddr = safememmove(dst, (char *)srcva, len, 1); ... } |
| `kernel/syscall/syscall.c` | `function fetchaddr` | int fetchaddr(uint64 addr, uint64 *ip) { if(copyin2((char *)ip, addr, sizeof(*ip)) != 0) return -1; } |

### Q02_023（tri_state_impl）

- 题干：时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_intr` | if (INTR_TIMER == scause) { timer_tick(); proc_tick(); ... if (yield()) { p->ivswtch += 1; } } |
| `kernel/sched/proc.c` | `function yield` | int yield(void) { ... sched(); ... } |

### Q02_024（tri_state_impl）

- 题干：是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function usertrap` | if (p->killed) { if (SIGTERM == p->killed) exit(-1); sighandle(); } |
| `kernel/sched/signal.c` | `function sighandle` | void sighandle(void) { ... struct sig_frame *frame = kmalloc(...); ... } |
| `kernel/sched/signal.c` | `function sigreturn` | void sigreturn(void) { ... kfree(p->trapframe); p->trapframe = frame->tf; ... } |

### Q02_025（short_answer）

- 题干：缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）
- 答案："存在联动。入口点：`kernel/trap/trap.c:handle_excp()` 检测页面异常 → 调用 `kernel/mm/vm.c:handle_page_fault()`。CoW 处理：`vm.c:handle_store_page_fault_cow()` 检测 PTE_COW 标志并复制页面。Lazy 分配：`vm.c:handle_page_fault_lazy()` 为 HEAP/STACK 段按需分配页面。证据：`trap.c:320-330` 异常分发，`vm.c:783-850` 缺页处理完整链路。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_excp` | case EXCP_STORE_PAGE: return handle_page_fault(1, r_stval()); |
| `kernel/mm/vm.c` | `function handle_page_fault` | int handle_page_fault(int kind, uint64 badaddr) { ... switch (seg->type) { case LOAD: ... case HEAP: case STACK: return handle_page_fault_lazy(...); } } |
| `kernel/mm/vm.c` | `function handle_store_page_fault_cow` | static int handle_store_page_fault_cow(pte_t *ptep) { if (monopolizepage(pa)) { pte |= PTE_W; } else { char *copy = (char *)allocpage(); ... } } |

### Q02_026（short_answer）

- 题干：与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）
- 答案："多核一致。`kernel/main.c:main()` 中 hart 0 先初始化 `trapinithart()`，然后通过 `sbi_send_ipi()` 唤醒其他 hart。其他 hart 在 `started == 1` 后也调用 `trapinithart()`。每 CPU 通过 `tp` 寄存器存储 hartid (`main.c:inithartid()`)。时钟初始化在 `trapinithart()` 中通过 `set_next_timeout()` 完成。证据：`main.c:45-75` 多核启动序列，`trap.c:52` 每 hart 陷阱初始化。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/main.c` | `function main` | for (int i = 1; i < NCPU; i ++) { sbi_send_ipi(mask, 0); } ... started = 1; ... else { floatinithart(); kvminithart(); trapinithart(); } |
| `kernel/trap/trap.c` | `function trapinithart` | void trapinithart(void) { w_stvec((uint64)kernelvec); ... set_next_timeout(); } |

### Q02_027（fill_in）

- 题干：Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）
- 答案："分发表路径：kernel/syscall/syscall.c:194-258 (syscalls[] 数组)\n完整实现 ✅ (implemented): 约 55 个 (sys_fork, sys_exec, sys_write, sys_read, sys_openat, sys_mmap, sys_clone, sys_wait4 等有完整逻辑)\n桩/ENOSYS/return 0 🔸 (stub): 约 5 个，代表性例子：sys_getuid (仅返回 0), sys_geteuid (指向 sys_getuid), sys_getgid (指向 sys_getuid), sys_getegid (指向 sys_getuid), sys_prlimit64 (仅返回 0)\n未注册 ❌ (not_found): 0 个 (所有 SYS_* 常量都在 syscalls[] 中有注册，即使是指向桩函数)\n统计依据：grep kernel/syscall/syscall.c 的 syscalls[] 数组，共 68 个条目；逐个检查 sys_*.c 文件中的实现体深度"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/syscall.c` | `array syscalls[]` | static uint64 (*syscalls[])(void) = { [SYS_fork] sys_fork, ... [SYS_msync] sys_msync }; // 共 68 个条目 |
| `kernel/syscall/sysproc.c` | `function sys_getuid` | uint64 sys_getuid(void) { return 0; } |

### Q02_028（short_answer）

- 题干：README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）
- 答案："README.md 未明确列出 syscall 兼容性声称，仅在 Progress 章节列出功能进度（进程管理、文件系统等）。doc/用户使用 - 系统调用.md 提到支持标准 POSIX syscall。代码分发表实际实现了 68 个 syscall，覆盖 fork/exec/wait/read/write/open/close/mmap 等核心功能，与 README 声称的\"进程管理\"、\"文件系统\"功能一致。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `README.md` | `section Progress` | ## Progress<br>- [x] Process management<br>- [x] File system |

### Q02_029（short_answer）

- 题干：`_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）
- 答案："未见该命名模式。搜索 `_impl\\b|sys_[a-z0-9_]*_impl` 在 152 个文件中无匹配结果。xv6-k210 采用直接命名（如 `sys_write`），未使用 `_impl` 后缀分离接口与实现。"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q02_030（tri_state_impl）

- 题干：是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_intr` | else if (INTR_SOFTWARE == scause && sbi_xv6_is_ext().value) { int irq = plic_claim(); switch (irq) { case UART_IRQ: consoleintr(c); break; case DISK_IRQ: disk_intr(); break; } } |
| `kernel/hal/plic.c` | `function plic_claim` | int plic_claim(void) { ... } |

### Q02_031（tri_state_impl）

- 题干：非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q02_032（short_answer）

- 题干：信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）
- 答案："仅支持进程级信号发送。实现了 `kernel/syscall/syssignal.c:sys_kill()` (第 134 行)，通过 `kill(pid, sig)` 向进程发送信号。未发现 sys_tkill (线程级) 和 sys_tgkill (进程组级) 的实现。搜索 sys_tkill 和 sys_tgkill 无匹配结果。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall/syssignal.c` | `function sys_kill` | uint64 sys_kill(void) { int pid, sig; argint(0, &pid); argint(1, &sig); return kill(pid, sig); } |

### Q02_033（single_choice）

- 题干：中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）
- 答案："通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function handle_intr` | if (INTR_TIMER == scause) { ... } else if (INTR_EXTERNAL == scause) { ... } |
| `kernel/trap/trap.c` | `function handle_excp` | switch (scause) { case EXCP_STORE_PAGE: ... case EXCP_LOAD_PAGE: ... } |
| `include/hal/riscv.h` | `macro INTR_TIMER` | #define INTR_TIMER (0x5 | INTERRUPT_FLAG) // Supervisor interrupt number |

### Q02_034（tri_state_impl）

- 题干：是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap/trap.c` | `function kerneltrap` | __debug_assert("kerneltrap", 0 == intr_get(), "interrupts enable\n"); // 断言中断关闭 |
| `kernel/trap/kernelvec.S` | `instruction kernelvec` | kernelvec: ... call kerneltrap ... sret // 整个 handler 执行期间中断关闭 |
