## 题单作答（JSON-QA 渲染）

- stage_id: `02_boot_trap`
- terminology_profile: `stallings_en_zh`

## 第 02_boot_trap 阶段：启动/架构与 Trap/系统调用

### Q02_001（short_answer）

- 题干：启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据）
- 答案："QEMU 平台：`linker/qemu.ld` 中 `ENTRY(_entry)`，汇编入口为 `kernel/entry_qemu.S:_entry`。VisionFive 平台：`linker/visionfive.ld` 中 `ENTRY(_start)`，汇编入口为 `kernel/entry_visionfive.S:_start`。两者均跳转到 `kernel/main.c:main()` 函数。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `linker/qemu.ld` | `linker_script ENTRY` | OUTPUT_ARCH(riscv) ENTRY(_entry) |
| `kernel/entry_qemu.S` | `assembly _entry` | .section .text<br>    .globl _entry<br>_entry:<br>    add t0, a0, 1<br>    slli t0, t0, 14<br>    la sp, boot_stack<br>    add sp, sp, t0<br>    call main |
| `linker/visionfive.ld` | `linker_script ENTRY` | OUTPUT_ARCH(riscv) ENTRY(_start) |
| `kernel/entry_visionfive.S` | `assembly _start` | .section .text.entry<br>    .globl _start<br>_start:<br>    add t0, a0, 1<br>    slli t0, t0, 14<br>    la sp, boot_stack<br>    add sp, sp, t0<br>    call main |

### Q02_002（single_choice）

- 题干：启动链更接近哪种交接方式？
- 答案："固件/引导加载器 → 内核入口（如 SBI/OpenSBI/U-Boot/BIOS/UEFI）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/main.c` | `function main` | void main(unsigned long hartid, unsigned long dtb_pa) { ... } 函数签名表明由固件传递 hartid 和设备树 DTB 指针，符合 SBI/OpenSBI 规范 |
| `kernel/include/sbi.h` | `header sbi_hart_start` | SBI 调用接口定义，用于多核启动 |

### Q02_003（tri_state_impl）

- 题干：是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function usertrapret` | usertrapret() 中：x &= ~SSTATUS_SPP; // clear SPP to 0 for user mode; x |= SSTATUS_SPIE; // enable interrupts in user mode; w_sstatus(x); 明确设置 S 态返回用户态 |
| `kernel/trampoline.S` | `assembly userret` | userret: ... sret  // return to user mode and user pc. usertrapret() set up sstatus and sepc. |
| `kernel/include/riscv.h` | `header SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User |

### Q02_004（short_answer）

- 题干：模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录）
- 答案："RISC-V S 态关键寄存器：sstatus（SSTATUS_SPP 位控制 Previous Mode，SSTATUS_SPIE 控制中断使能）、sepc（异常返回地址）、satp（页表基址）、stvec（陷阱向量基址）。证据：`kernel/include/riscv.h` 定义 SSTATUS_SPP=(1L<<8)、SSTATUS_SPIE=(1L<<5)；`kernel/trap.c:usertrapret()` 操作 sstatus 设置用户模式。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/include/riscv.h` | `macro SSTATUS_SPP` | #define SSTATUS_SPP (1L << 8)  // Previous mode, 1=Supervisor, 0=User<br>#define SSTATUS_SPIE (1L << 5) // Supervisor Previous Interrupt Enable |
| `kernel/trap.c` | `function usertrapret` | unsigned long x = r_sstatus();<br>  x &= ~SSTATUS_SPP; // clear SPP to 0 for user mode<br>  x |= SSTATUS_SPIE; // enable interrupts in user mode<br>  w_sstatus(x);<br>  w_sepc(p->trapframe->epc);<br>  uint64 satp = MAKE_SATP(p->pagetable); |

### Q02_005（tri_state_impl）

- 题干：是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/vm.c` | `function kvminit` | void kvminit() { ... kernel_pagetable = (pagetable_t)kalloc(); ... kvmmap(...) } 创建内核页表并映射设备/内存 |
| `kernel/vm.c` | `function kvminithart` | void kvminithart() { sfence_vma(); w_satp(MAKE_SATP(kernel_pagetable)); uart8250_change_base_addr(UART_V); } 设置 satp 启用分页 |
| `kernel/main.c` | `function main` | kvminit();      // create kernel page table<br>  kvminithart();  // turn on paging |

### Q02_006（short_answer）

- 题干：从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据）
- 答案："QEMU 平台：1. `_entry` (kernel/entry_qemu.S) → 2. 设置栈指针 boot_stack → 3. `call main` → 4. `main()` (kernel/main.c) → 5. cpuinit/consoleinit/kvminit/trapinithart/procinit → 6. scheduler()。VisionFive 平台类似，入口为 `_start` (kernel/entry_visionfive.S)。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/entry_qemu.S` | `assembly _entry` | _entry:<br>    add t0, a0, 1<br>    slli t0, t0, 14<br>    la sp, boot_stack<br>    add sp, sp, t0<br>    call main |
| `kernel/main.c` | `function main` | void main(unsigned long hartid, unsigned long dtb_pa) {<br>  inithartid(hartid);<br>  ...<br>  cpuinit();<br>  consoleinit();<br>  kvminit();<br>  kvminithart();<br>  trapinithart();<br>  procinit();<br>  ...<br>  scheduler();<br>} |

### Q02_007（fill_in）

- 题干：早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found + 证据路径，格式：`项目: 状态 [路径]`）：
- BSS 清零 (BSS Clearing): ___
- 早期串口输出 (Early Serial/UART Output): ___
- 设备树解析 (Device Tree Blob parsing, DTB): ___
- 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？）
- 答案："BSS 清零 (BSS Clearing): implemented [linker/qemu.ld: .bss 段定义，sbss_clear/ebss_clear 符号]\n早期串口输出 (Early Serial/UART Output): implemented [kernel/console.c:consoleinit() 调用 uartinit()/uart8250_init()]\n设备树解析 (Device Tree Blob parsing, DTB): not_found [main() 接收 dtb_pa 参数但未见解析代码]\n页表初始化时机 (Page Table Init): implemented [kernel/main.c: kvminit()/kvminithart() 在 trapinithart() 之前调用，MMU 启用前完成页表建立]"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `linker/qemu.ld` | `linker_script bss_section` | .bss : {<br>    *(.bss.stack)<br>    sbss_clear = .;<br>    *(.sbss .bss .bss.*)<br>    ebss_clear = .;<br>} |
| `kernel/console.c` | `function consoleinit` | void consoleinit(void) {<br>  initlock(&cons.lock, "cons");<br>#ifdef QEMU<br>  uartinit();<br>#endif<br>#ifdef visionfive<br>  uart8250_init(UART, 24000000, 115200, 2, 4, 0);<br>#endif<br>} |
| `kernel/main.c` | `function main` | kvminit();      // create kernel page table<br>  kvminithart();  // turn on paging<br>  timerinit();    // init a lock for timer<br>  trapinithart(); // install kernel trap vector |

### Q02_008（tri_state_impl）

- 题干：是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/include/riscv.h` | `search fpu_scan` | 搜索 sstatus.fs、FS 位、mstatus.FS、fcsr 等 FPU 相关寄存器/位，0 命中。未见 FPU 初始化代码 |

### Q02_009（tri_state_impl）

- 题干：是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function trapinithart` | void trapinithart(void) {<br>  w_stvec((uint64)kernelvec);<br>  w_sstatus(r_sstatus() | SSTATUS_SIE);<br>  w_sie(r_sie() | SIE_SEIE | SIE_SSIE | SIE_STIE);<br>  set_next_timeout();<br>} |
| `kernel/trap.c` | `function usertrapret` | w_stvec(TRAMPOLINE + (uservec - trampoline)); // 设置用户陷阱向量到 trampoline.S |

### Q02_010（short_answer）

- 题干：构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据）
- 答案："Makefile 通过 `platform` 变量选择：`platform := visionfive` 或 `platform := qemu`。条件编译：`-D QEMU` / `-D visionfive` / `-D k210`。入口文件：QEMU 用 `kernel/entry_qemu.o`，VisionFive 用 `kernel/entry_visionfive.o`。链接脚本：qemu 用 `linker/qemu.ld`，visionfive 用 `linker/visionfive.ld`。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `Makefile` | `makefile platform_selection` | platform	:= visionfive<br>#platform	:= qemu<br>...<br>ifeq ($(platform), visionfive)<br>OBJS += $K/entry_visionfive.o<br>else<br>OBJS += $K/entry_qemu.o<br>endif<br>...<br>ifeq ($(platform), qemu)<br>CFLAGS += -D QEMU<br>else ifeq ($(platform), visionfive)<br>CFLAGS += -D visionfive<br>endif |

### Q02_011（tri_state_impl）

- 题干：对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi|opensbi|u-boot；非 RISC-V 平台写 not_found 并说明架构）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/include/sbi.h` | `header sbi_console_getchar` | SBI 调用接口定义：sbi_console_getchar, sbi_set_timer, sbi_shut_down, sbi_hart_start 等 |
| `kernel/main.c` | `function main` | #ifdef visionfive<br>    sbi_hart_start(2, (unsigned long)_start, 0);<br>#endif  // 使用 SBI 启动次级核 |
| `kernel/timer.c` | `function set_next_timeout` | sbi_set_timer(r_time() + INTERVAL);  // 使用 SBI 设置定时器 |

### Q02_012（tri_state_impl）

- 题干：MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt|virt_to_phys 及 UART 基址常量）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/vm.c` | `function kvminithart` | void kvminithart() {<br>  sfence_vma();<br>  w_satp(MAKE_SATP(kernel_pagetable));<br>  uart8250_change_base_addr(UART_V);  // MMU 启用后切换 UART 到虚拟地址<br>} |
| `kernel/include/memlayout.h` | `header UART_V` | UART_V 定义为虚拟地址，kvmmap 映射 UART 物理地址到 UART_V |

### Q02_013（tri_state_impl）

- 题干：是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function usertrapret` | void usertrapret(void) {<br>  w_stvec(TRAMPOLINE + (uservec - trampoline));<br>  ...<br>  uint64 fn = TRAMPOLINE + (userret - trampoline);<br>  ((void (*)(uint64, uint64))fn)(TRAPFRAME, satp);<br>} |
| `kernel/trampoline.S` | `assembly userret` | userret:<br>  ...<br>  csrw satp, a1<br>  sfence.vma<br>  ...<br>  sret  // return to user mode and user pc. |

### Q02_014（short_answer）

- 题干：是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive|jh7110|loongarch；有则描述差异入口与互斥关系；无则写未发现）
- 答案："支持 QEMU 和 VisionFive 双平台。Makefile 中 `platform := visionfive` 或 `platform := qemu` 切换。QEMU 用 entry_qemu.S + qemu.ld，VisionFive 用 entry_visionfive.S + visionfive.ld。未见 LoongArch 支持（搜索 loongarch 0 命中）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `Makefile` | `makefile platform_config` | platform	:= visionfive<br>#platform	:= qemu<br>...<br>ifeq ($(platform), visionfive)<br>linker = ./linker/visionfive.ld<br>endif<br>ifeq ($(platform), qemu)<br>linker = ./linker/qemu.ld<br>endif |
| `kernel/entry_visionfive.S` | `assembly _start` | VisionFive 专用入口，含注释"add by retrhelo, write tp reg" |

### Q02_015（short_answer）

- 题干：trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据）
- 答案："内核陷阱向量：`kernel/kernelvec.S:kernelvec`（通过 `kernel/trap.c:trapinithart()` 设置 `w_stvec((uint64)kernelvec)`）。用户陷阱向量：`kernel/trampoline.S:uservec`（通过 `kernel/trap.c:usertrapret()` 设置 `w_stvec(TRAMPOLINE + (uservec - trampoline))`）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function trapinithart` | void trapinithart(void) {<br>  w_stvec((uint64)kernelvec);<br>} |
| `kernel/trampoline.S` | `assembly uservec` | .globl uservec<br>uservec:    <br>	#<br>        # trap.c sets stvec to point here, so<br>        # traps from user space start here,<br>        # in supervisor mode, but with a<br>        # user page table. |

### Q02_016（single_choice）

- 题干：trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？
- 答案："用户地址空间预留页（trampoline/trap_context page）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/include/trap.h` | `struct trapframe` | struct trapframe { ... }; // sits in a page by itself just under the trampoline page in the user page table. not specially mapped in the kernel page table. |
| `kernel/trampoline.S` | `assembly uservec` | # sscratch points to where the process's p->trapframe is<br>        # mapped into user space, at TRAPFRAME. |

### Q02_017（short_answer）

- 题干：TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据）
- 答案："定义于 `kernel/include/trap.h:struct trapframe`。包含 37 个 uint64 字段（kernel_satp/kernel_sp/kernel_trap/epc/kernel_hartid + 32 个通用寄存器），总计 37*8=296 字节。实际布局：0-32 字节为内核元数据，40-280 字节为寄存器保存区。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/include/trap.h` | `struct trapframe` | struct trapframe {<br>  /*   0 */ uint64 kernel_satp;<br>  /*   8 */ uint64 kernel_sp;<br>  /*  16 */ uint64 kernel_trap;<br>  /*  24 */ uint64 epc;<br>  /*  32 */ uint64 kernel_hartid;<br>  /*  40 */ uint64 ra;<br>  /*  48 */ uint64 sp;<br>  ...<br>  /* 280 */ uint64 t6;<br>}; |

### Q02_018（tri_state_impl）

- 题干：是否存在系统调用分发表（syscall table / match 分发）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall.c` | `array syscalls` | static uint64 (*syscalls[])(void) = {<br>    [SYS_fork] sys_fork,<br>    [SYS_exit] sys_exit,<br>    [SYS_write] sys_write,<br>    ...<br>}; |
| `kernel/syscall.c` | `function syscall` | void syscall(void) {<br>  int num = p->trapframe->a7;<br>  if (num > 0 && num < NELEM(syscalls) && syscalls[num]) {<br>    p->trapframe->a0 = syscalls[num]();<br>  }<br>} |

### Q02_019（tri_state_impl）

- 题干：系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall.c` | `function syscall` | void syscall(void) {<br>  num = p->trapframe->a7;<br>  if (num > 0 && num < NELEM(syscalls) && syscalls[num]) {<br>    p->trapframe->a0 = syscalls[num]();<br>  } else {<br>    debug_print("pid %d %s: unknown sys call %d\n", p->pid, p->name, num);<br>    p->trapframe->a0 = -1;  // 越界返回 -1<br>  }<br>} |

### Q02_020（short_answer）

- 题干：选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。
- 答案："sys_write 调用链：1. 用户态 ecall 指令 → 2. `kernel/trampoline.S:uservec` 保存上下文 → 3. `kernel/trap.c:usertrap()` 识别 scause=8（系统调用）→ 4. `kernel/syscall.c:syscall()` 分发 → 5. `kernel/sysfile.c:sys_write()` 实现。证据：trap.c:usertrap() 中 `if (r_scause() == 8) { syscall(); }`；syscall.c 中 `[SYS_write] sys_write` 注册。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function usertrap` | if (r_scause() == 8) {<br>    // system call<br>    ...<br>    syscall();<br>  } |
| `kernel/syscall.c` | `function syscall` | p->trapframe->a0 = syscalls[num](); |
| `kernel/syscall.c` | `array syscalls` | [SYS_write] sys_write, |

### Q02_021（short_answer）

- 题干：列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现三态（implemented/stub/not_found），并为每个至少给一条证据。
- 答案："sys_fork: implemented [kernel/sysproc.c:263: uint64 sys_fork(void) { return fork(); }]\nsys_exec: implemented [kernel/sysproc.c:86-135 完整实现 exec 逻辑]\nsys_write: implemented [kernel/sysfile.c 中实现]\nsys_open: implemented [kernel/sysfile.c 中实现]\nsys_mmap: implemented [kernel/sysproc.c 中声明，vm.c 实现]\nsys_exit: implemented [kernel/sysproc.c:179: uint64 sys_exit(void)]\nsys_clone: implemented [kernel/sysproc.c:20-56 完整实现]\nsys_kill: implemented [kernel/sysproc.c:339 声明]\nsys_wait: implemented [kernel/sysproc.c 中实现]\nsys_brk: implemented [kernel/sysproc.c 中声明]"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sysproc.c` | `function sys_fork` | uint64 sys_fork(void) { return fork(); } |
| `kernel/sysproc.c` | `function sys_exec` | uint64 sys_exec(void) {<br>  char path[FAT32_MAX_PATH], *argv[MAXARG];<br>  int i;<br>  uint64 uargv, uarg;<br>  if (argstr(0, path, FAT32_MAX_PATH) < 0 || argaddr(1, &uargv) < 0) {<br>    return -1;<br>  }<br>  ... exec(path, argv, 0) ... |
| `kernel/syscall.c` | `array syscalls` | [SYS_fork] sys_fork,<br>    [SYS_exit] sys_exit,<br>    [SYS_exec] sys_exec,<br>    [SYS_write] sys_write,<br>    [SYS_open] sys_open,<br>    [SYS_mmap] sys_mmap, |

### Q02_022（tri_state_impl）

- 题干：是否存在用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/vm.c` | `function copyin` | int copyin(pagetable_t pagetable, char *dst, uint64 srcva, uint64 len) {<br>  while (len > 0) {<br>    va0 = PGROUNDDOWN(srcva);<br>    pa0 = walkaddr(pagetable, va0);<br>    if (pa0 == NULL) return -1;<br>    ...<br>  }<br>} |
| `kernel/vm.c` | `function copyout` | int copyout(pagetable_t pagetable, uint64 dstva, char *src, uint64 len) {<br>  uint64 n, va0, pa0;<br>  while (len > 0) {<br>    va0 = PGROUNDDOWN(dstva);<br>    pa0 = walkaddr(pagetable, va0);<br>    if (pa0 == NULL) return -1;<br>    ...<br>  }<br>} |
| `kernel/syscall.c` | `function fetchaddr` | int fetchaddr(uint64 addr, uint64 *ip) {<br>  if (copyin(p->pagetable, (char *)ip, addr, sizeof(*ip)) != 0) {<br>    return -1;<br>  }<br>  return 0;<br>} |

### Q02_023（tri_state_impl）

- 题干：时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function usertrap` | // give up the CPU if this is a timer interrupt.<br>  if (which_dev == 2) {<br>    p->utime++;<br>    yield();<br>  } |
| `kernel/trap.c` | `function kerneltrap` | if (which_dev == 2 && myproc() != 0 && myproc()->state == RUNNING) {<br>    yield();<br>  } |
| `kernel/timer.c` | `function timer_tick` | void timer_tick() {<br>  acquire(&tickslock);<br>  ticks++;<br>  wakeup(&ticks);<br>  release(&tickslock);<br>  set_next_timeout();<br>} |

### Q02_024（tri_state_impl）

- 题干：是否存在信号处理链路（trap 返回前处理 pending signal、sigreturn/trampoline）？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function usertrap` | if (p->killed) {<br>    if (p->killed == SIGTERM) {<br>      exit(-1);<br>    }<br>    sighandle();  // 处理信号<br>  } |
| `kernel/signal.c` | `function sighandle` | void sighandle(void) {<br>  struct proc *p = myproc();<br>  int signum = p->killed;<br>  if (p->sigaction[signum].__sigaction_handler.sa_handler != NULL) {<br>    p->sig_tf = kalloc();<br>    memcpy(p->sig_tf, p->trapframe, sizeof(struct trapframe));<br>    p->trapframe->epc = (uint64)p->sigaction[signum].__sigaction_handler.sa_handler;<br>    p->trapframe->ra = (uint64)SIGTRAMPOLINE;<br>    ...<br>  }<br>} |
| `kernel/syssig.c` | `function sys_rt_sigreturn` | uint64 sys_rt_sigreturn(void) { return rt_sigreturn(); } |

### Q02_025（short_answer）

- 题干：缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据）
- 答案："存在栈缺页处理：`kernel/trap.c:usertrap()` 中 `if ((r_scause() == 13 || r_scause() == 15) && (handle_stack_page_fault(myproc(), r_stval()) == 0))` 调用 `kernel/vma.c:handle_stack_page_fault()` 动态扩展栈空间。未见 CoW/lazy allocation 实现（搜索 cow/lazy 仅见测试注释）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function usertrap` | } else if ((r_scause() == 13 || r_scause() == 15) &&<br>             (handle_stack_page_fault(myproc(), r_stval()) == 0)) {<br>    // load page fault or store page fault<br>    // check if the page fault is caused by stack growth<br>    printf("handle stack page fault\n"); |
| `kernel/vma.c` | `function handle_stack_page_fault` | uint64 handle_stack_page_fault(struct proc *p, uint64 va) {<br>  if (!(va >= USER_STACK_DOWN && va < USER_STACK_TOP)) return -1;<br>  ...<br>  if (uvmalloc1(p->pagetable, start, end, PTE_R | PTE_W | PTE_U) != 0) {<br>    printf("user stack vma alloc failed\n");<br>    return -1;<br>  }<br>  vma->addr = start;<br>  return 0;<br>} |

### Q02_026（short_answer）

- 题干：与 09 多核交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用）
- 答案："多核支持：`kernel/main.c:main()` 中 BSP 核（hartid==1 或 first==0）先初始化 cpuinit/consoleinit/kvminit/trapinithart/procinit，然后通过 `sbi_hart_start(2, (unsigned long)_start, 0)` 启动 AP 核。AP 核等待 started 标志后调用 kvminithart/trapinithart/plicinithart。trapinithart 每核独立调用，符合 per-CPU 初始化顺序。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/main.c` | `function main` | if (hartid == 1) {<br>    ...<br>    trapinithart();<br>    ...<br>    started = 1;<br>  } else {<br>    while (started == 0) ;<br>    kvminithart();<br>    trapinithart();<br>    plicinithart();<br>  } |

### Q02_027（fill_in）

- 题干：Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写：
- 分发表路径: ___
- 完整实现 ✅ (implemented): ___ 个
- 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___
- 未注册 ❌ (not_found): ___ 个
- 统计依据（grep 或 outline 方式）: ___
（若无法精确计数，给出区间估计并说明理由）
- 答案："分发表路径：kernel/syscall.c:syscalls[] 数组（约 90 项）\n完整实现 ✅ (implemented): 约 70 个（sys_fork/sys_exec/sys_write/sys_open/sys_clone 等均有完整逻辑）\n桩/ENOSYS/return 0 🔸 (stub): 约 10 个，代表性例子：sys_exit_group [kernel/sysproc.c:427: return 0;]、sys_tkill [kernel/thread.c:74-76: return 0;]、sys_rt_sigtimedwait [kernel/syssig.c:105: return 0;]\n未注册 ❌ (not_found): 约 10 个（syscalls[] 数组中未填充的索引）\n统计依据：grep_in_repo 搜索 kernel/syscall.c:syscalls[] 数组元素 + kernel/sysproc.c/kernel/sysfile.c/kernel/syssig.c 中函数实现检查"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/syscall.c` | `array syscalls` | static uint64 (*syscalls[])(void) = {<br>    [SYS_fork] sys_fork,<br>    [SYS_exit] sys_exit,<br>    ...<br>    [SYS_shutdown] sys_shutdown,<br>}; |
| `kernel/sysproc.c` | `function sys_exit_group` | uint64 sys_exit_group(void) { return 0; } |
| `kernel/thread.c` | `function sys_tkill` | uint64 sys_tkill() {<br>  int tid;<br>  int signum;<br>  if (argint(0, &tid) < 0 || argint(1, &signum) < 0)<br>    return -1;<br>  debug_print("sys_tkill: tid = %d, signum = %d\n", tid, signum);<br>  return 0;  // 桩实现<br>} |

### Q02_028（short_answer）

- 题干：README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」）
- 答案："README.md 仅含构建/运行说明（qemu-system-riscv64、make all、make qemu-run），未声称 syscall 兼容性。README 文件（无.md 后缀）同样无 syscall 声称。仅以代码为准：syscall.c 中 syscalls[] 数组注册约 90 个 syscall，与 xv6 传统 syscall 兼容但扩展了大量 Linux syscall（如 clone/mmap/rt_sigaction 等）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `README.md` | `document readme` | # xv6-riscv<br># dependency<br>- qemu-system-riscv64 version 7.0.0<br>- riscv64-linux-gnu toolchain<br># run on qemu<br>    make all<br>    make qemu-run |

### Q02_029（short_answer）

- 题干：`_impl` 命名模式搜索结论：grep `_impl\b|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论）
- 答案："搜索 `_impl\\b|sys_[a-z0-9_]*_impl` 命中 64 处，但均为 lwip 网络栈内部实现（如 pbuf_add_header_impl/ppp_dbglog_impl 等），非 syscall 实现。内核 syscall 未见 `_impl` 命名模式，所有 syscall 直接以 `sys_xxx` 命名并在 syscall.c 中注册。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/lwip/core/pbuf.c` | `search impl_pattern` | 搜索 '_impl\b|sys_[a-z0-9_]*_impl' 的结果 (64 个匹配):<br>kernel/lwip/core/pbuf.c:480: static u8_t pbuf_add_header_impl(...)<br>kernel/lwip/include/netif/ppp/ppp_impl.h:619: void ppp_dbglog_impl(...)<br>... 均为 lwip 网络栈内部函数，非 syscall |

### Q02_030（tri_state_impl）

- 题干：是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function devintr` | int devintr(void) {<br>  uint64 scause = r_scause();<br>  if ((0x8000000000000000L & scause) && 9 == (scause & 0xff)) {<br>    int irq = plic_claim();<br>    if (UART_IRQ == irq) {<br>      consoleintr(c);<br>    } else if (DISK_IRQ == irq) {<br>      disk_intr();<br>    }<br>    plic_complete(irq);<br>    return 1;<br>  }<br>} |
| `kernel/plic.c` | `function plic_claim` | PLIC 中断控制器驱动，处理外部设备中断 |

### Q02_031（tri_state_impl）

- 题干：非法内存访问时是否向进程发送 SIGSEGV 信号？（必须三态；搜索 SIGSEGV|sig_segv）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/include/signal.h` | `search sigsegv_scan` | 搜索 'SIGSEGV|sig_segv|signal.*11' 的结果 (3 个匹配):<br>kernel/include/signal.h:16: #define SIGSEGV    11   // Segmentation violation<br>但 trap.c 中非法内存访问仅设置 p->killed = SIGTERM 并 exit(-1)，未发送 SIGSEGV |
| `kernel/trap.c` | `function usertrap` | else {<br>    serious_print("\nusertrap(): unexpected scause %p pid=%d %s\n", r_scause(), p->pid, p->name);<br>    p->killed = SIGTERM;  // 使用 SIGTERM 而非 SIGSEGV<br>  } |

### Q02_032（short_answer）

- 题干：信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据）
- 答案："已实现：sys_kill（进程级）[kernel/sysproc.c:339]、sys_tgkill（线程组级）[kernel/syssig.c:101]、sys_tkill（线程级）[kernel/thread.c:69]。sys_tkill 目前为桩实现（return 0），sys_tgkill 调用 tgkill()，sys_kill 调用 kill()。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/sysproc.c` | `function sys_kill` | uint64 sys_kill(void); // 声明，实际实现在 proc.c |
| `kernel/syssig.c` | `function sys_tgkill` | uint64 sys_tgkill(void) {<br>  int sig;<br>  int tid;<br>  int pid;<br>  argint(0, &pid);<br>  argint(1, &tid);<br>  argint(2, &sig);<br>  return tgkill(tid, pid, sig);<br>} |
| `kernel/thread.c` | `function sys_tkill` | uint64 sys_tkill() {<br>  int tid;<br>  int signum;<br>  if (argint(0, &tid) < 0 || argint(1, &signum) < 0)<br>    return -1;<br>  return 0;  // 桩实现<br>} |

### Q02_033（single_choice）

- 题干：中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch5；即 trap handler 如何区分「外部中断」与「同步异常」）
- 答案："通过 scause/mcause/VBAR 中断原因寄存器区分（硬件编码原因号）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `function devintr` | int devintr(void) {<br>  uint64 scause = r_scause();<br>  if ((0x8000000000000000L & scause) && 9 == (scause & 0xff)) {<br>    // 外部中断：scause 最高位为 1<br>    int irq = plic_claim();<br>    ...<br>  } else if (0x8000000000000005L == scause) {<br>    // 定时器中断<br>    timer_tick();<br>    return 2;<br>  }<br>} |
| `kernel/trap.c` | `function usertrap` | if (r_scause() == 8) {<br>    // system call (ecall)<br>    syscall();<br>  } else if ((r_scause() == 13 || r_scause() == 15) && ...) {<br>    // page fault<br>    handle_stack_page_fault();<br>  } |

### Q02_034（tri_state_impl）

- 题干：是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch5)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `kernel/trap.c` | `search nested_irq_scan` | 搜索 'nested_irq|enable_irq_in_handler|interrupt.*nest' 0 命中。usertrap() 中 syscall 处理前调用 intr_on() 开中断，但 kerneltrap() 中检查 intr_get() != 0 则 panic，表明内核陷阱处理期间禁止中断嵌套 |
| `kernel/trap.c` | `function kerneltrap` | void kerneltrap() {<br>  ...<br>  if (intr_get() != 0)<br>    panic("kerneltrap: interrupts enabled");<br>  ...<br>} |
