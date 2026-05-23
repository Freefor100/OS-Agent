# 02-09 QA Audit

本表记录 02-09 全部 201 题的逐题重构结果。本轮不再使用“高风险精修、其余默认 ok”的口径；每题均已重写 concept_boundary、structured_facts、diagnostic_checks、answer_contract，并同步 features 镜像。

- Total questions: 201
- rewritten: 201
- remaining_generic_facts: 0

| Stage | Question | Type | Status | Action | Stem |
|---|---|---|---|---|---|
| 02_boot_trap | Q02_001 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 启动入口在哪里？（例如 linker.ld 的 ENTRY、`_start`/`start`/`head`/`entry` 标签；必须给文件路径+符号证据） |
| 02_boot_trap | Q02_002 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 启动链更接近哪种交接方式？ |
| 02_boot_trap | Q02_003 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否能在代码中证实发生了 CPU 特权级/模式切换？（RISC-V M→S、x86 实→保→长等；必须三态） |
| 02_boot_trap | Q02_004 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 模式切换涉及的关键寄存器/位是什么？（例如 RISC-V mstatus/sstatus、x86 cr0/cr4/eflags；必须给证据摘录） |
| 02_boot_trap | Q02_005 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否启用/初始化了 MMU（设置 SATP/CR3 等并建立页表）？（必须三态） |
| 02_boot_trap | Q02_006 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 从入口汇编/固件交接到 C/Rust 主入口函数的跳转链是什么？（列出 3-6 个关键节点并给证据） |
| 02_boot_trap | Q02_007 | fill_in | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 早期初始化 (Early Initialization) 各项状态（每项必须 implemented / stub / not_found / unknown + 证据路径，格式：`项目: 状态 [路径]`）： - BSS 清零 (BSS Clearing): ___ - 早期串口输出 (Early Serial/UART Output): ___ - 设备树解析 (Device Tree Blob parsing, DTB): ___ - 页表初始化时机 (Page Table Init): ___（在 MMU 启用前/后？） |
| 02_boot_trap | Q02_008 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否初始化/启用了 FPU（如 sstatus.fs / cpacr_el1 / cr4）？（必须三态） |
| 02_boot_trap | Q02_009 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否设置 trap/中断向量（如 stvec/idt 等）并能指出设置点？（必须三态） |
| 02_boot_trap | Q02_010 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 构建系统如何选择目标平台/架构与入口文件？（Cargo features/Kconfig/Makefile 条件；必须引用配置证据） |
| 02_boot_trap | Q02_011 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 对 RISC-V 平台：是否能证实 SBI/OpenSBI/U-Boot 固件链（固件将控制权移交内核）？（必须三态；搜索 sbi\|opensbi\|u-boot；非 RISC-V 平台写 not_found 并说明架构） |
| 02_boot_trap | Q02_012 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | MMU 启用前后是否存在串口/UART 地址切换逻辑（物理地址→虚拟地址）？（必须三态；搜索 phys_to_virt\|virt_to_phys 及 UART 基址常量） |
| 02_boot_trap | Q02_013 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在从内核返回用户态的路径（usertrapret/trap_return/trampoline/eret 等）并设置 stvec/VBAR/IDT？（必须三态） |
| 02_boot_trap | Q02_014 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否支持多平台启动（StarFive VisionFive2/LoongArch/多板型）？（搜索 visionfive\|jh7110\|loongarch；有则描述差异入口与互斥关系；无则写未发现） |
| 02_boot_trap | Q02_015 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | trap/异常向量入口在哪里？（trap_handler/trap_vector/__alltraps 等；必须给证据） |
| 02_boot_trap | Q02_016 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | trap 上下文 (TrapFrame/TrapContext) 更可能存放在哪里？ |
| 02_boot_trap | Q02_017 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | TrapFrame/寄存器保存结构体定义在哪里？寄存器数量与字节数是多少？（必须引用结构体定义证据） |
| 02_boot_trap | Q02_018 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在系统调用分发表（syscall table / match 分发）？（必须三态） |
| 02_boot_trap | Q02_019 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 系统调用号是否做边界检查？（越界默认分支/返回错误/panic；必须三态） |
| 02_boot_trap | Q02_020 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 选择一个具体 syscall（优先 sys_write），追踪：用户指令 → trap → 分发 → 实现体。列出 3-6 个关键节点并给证据。 |
| 02_boot_trap | Q02_021 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 列出 5-10 个“高价值 syscall”（fork/exec/mmap/open/write 等）的实现状态（implemented/stub/not_found/unknown），并为每个至少给一条证据。 |
| 02_boot_trap | Q02_022 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在 syscall 边界的用户指针访问安全检查（copyin/copyout/access_ok/UserInPtr 等）？（必须三态） |
| 02_boot_trap | Q02_023 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 时钟中断是否触发抢占调度（timer tick 中调用 yield/schedule/resched）？（必须三态） |
| 02_boot_trap | Q02_024 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | trap 返回用户态前是否存在信号投递链路（pending signal 检查、用户 handler 上下文构造、sigreturn/trampoline 恢复）？（必须三态；本题只看 trap-return 集成点，完整 signal API 见 Q06_010） |
| 02_boot_trap | Q02_025 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 缺页异常与内存特性（CoW/lazy）是否在 trap 中联动？（若存在，说明入口点与调用到内存模块的证据） |
| 02_boot_trap | Q02_026 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 与 04 SMP/多核题交叉一致性：per-CPU trap 栈/时钟初始化顺序与 AP 上线是否一致？（互指证据或写单核不适用） |
| 02_boot_trap | Q02_027 | fill_in | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | Syscall 实现全量统计 (Syscall Coverage Analysis)，请按格式填写： - 分发表路径: ___ - 完整实现 ✅ (implemented): ___ 个 - 桩/ENOSYS/return 0 🔸 (stub): ___ 个，代表性例子: ___ - 未注册 ❌ (not_found): ___ 个 - 统计依据（grep 或 outline 方式）: ___ （若无法精确计数，给出区间估计并说明理由） |
| 02_boot_trap | Q02_028 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | README 与 syscall 声称对照：README 中声称兼容/实现了哪些 syscall 或标准？与代码分发表实际是否一致？（无 README 则写「无 README，仅以代码为准」） |
| 02_boot_trap | Q02_029 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | `_impl` 命名模式搜索结论：grep `_impl\b\|sys_[a-z0-9_]*_impl`，结果是命中了哪些函数（列出），还是「未见该命名模式」？（必须给搜索结论） |
| 02_boot_trap | Q02_030 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在外部中断（PLIC/APIC 等）的分发处理逻辑？（必须三态；与时钟中断分开作答） |
| 02_boot_trap | Q02_031 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 同步非法内存访问/page fault 处理后，是否会向当前进程投递 SIGSEGV 或等价用户可见故障信号？（必须三态；仅 kill 进程或 panic 不算 SIGSEGV 投递） |
| 02_boot_trap | Q02_032 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 信号发送支持哪些粒度？（搜索 sys_kill/sys_tkill/sys_tgkill；分别是进程级/线程级/进程组级；列出已实现的与其证据） |
| 02_boot_trap | Q02_033 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 中断 (Interrupt)、异常 (Exception/Fault/Trap) 的区分机制更接近哪种？（Stallings Ch1；即 trap handler 如何区分「外部中断」与「同步异常」） |
| 02_boot_trap | Q02_034 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否支持中断嵌套 (Nested Interrupt / Interrupt Nesting, Stallings Ch1)？（必须三态；搜索 enable_irq_in_handler / nested_irq / 中断处理时是否重开中断；若 not_found 需说明是否关中断运行整个 handler） |
| 03_mem_mgmt | Q03_001 | single_choice | rewritten | final_action=keep；语言/形态是单选分类题，事实要求覆盖候选集、正证据、排除项和 unknown 处理，保留。 | 该 OS 的内存管理实现语言/形态更接近哪类？（只选最贴近的一项） |
| 03_mem_mgmt | Q03_002 | tri_state_impl | rewritten | final_action=keep；物理页帧分配器是单一能力，三态闭环要求定义、实现体、调用路径和状态变化，保留。 | 是否存在“物理页帧分配器 (Physical Frame Allocator)”的真实实现？（必须三态） |
| 03_mem_mgmt | Q03_003 | single_choice | rewritten | final_action=rewrite；修正 Buddy 候选项重复表述，保持物理页帧算法与 slab/对象池、普通 malloc、文件缓存分离。 | 物理内存分配算法更接近哪种？ |
| 03_mem_mgmt | Q03_004 | short_answer | rewritten | final_action=keep；短答要求结构体/字段证据，能区分 bitmap、buddy、slab、run list 等核心数据结构，保留。 | 物理页帧分配器的核心数据结构是什么？（例如 bitmap 数组、buddy free list、slab cache 表、`struct run` 单链表等；必须引用结构体/字段证据） |
| 03_mem_mgmt | Q03_005 | short_answer | rewritten | final_action=keep；锁粒度必须给锁对象类型和持锁范围，覆盖全局、per-CPU、分桶、关中断等并发边界，保留。 | 物理分配器的并发控制锁粒度是什么？（全局大锁 / per-CPU / 分桶 / 无锁+关中断 / 其他；必须给锁对象类型与持锁范围证据） |
| 03_mem_mgmt | Q03_006 | tri_state_impl | rewritten | final_action=keep；页表结构体加 walk/map/unmap 是单一页表能力，三态事实足以防止只凭 PTE 名称误判，保留。 | 是否存在“页表 (page table) 结构体 + walk/map/unmap”的真实实现？（必须三态） |
| 03_mem_mgmt | Q03_007 | short_answer | rewritten | final_action=keep；要求列 1-3 个页表操作入口并给证据，避免把页表常量或 PTE 位当 API，保留。 | 页表操作 API（walk/map/unmap 或等价）对应的函数名/模块是什么？列出 1-3 个关键入口并给证据。 |
| 03_mem_mgmt | Q03_008 | short_answer | rewritten | final_action=keep；专问页表修改路径锁/关中断/地址空间锁，能和物理分配器锁分开审，保留。 | 页表修改路径的并发控制是什么？（锁粒度、是否需要关中断、是否使用每进程地址空间锁等；必须引用锁/临界区证据） |
| 03_mem_mgmt | Q03_009 | single_choice | rewritten | final_action=keep；内核/用户页表关系是单选分类，候选项覆盖独立页表、共享页表、纯内核和待核实，保留。 | 内核与用户地址空间关系更接近哪种？ |
| 03_mem_mgmt | Q03_010 | tri_state_impl | rewritten | final_action=keep；缺页处理与分配/映射联动是单一能力，三态事实要求 trap 入口、处理体和映射效果闭环，保留。 | 是否存在缺页异常 (Page Fault) 处理逻辑并与内存分配/映射联动？（必须三态） |
| 03_mem_mgmt | Q03_011 | short_answer | rewritten | final_action=keep；链路题要求 trap 到 fault handler、页帧分配、建立映射的逐节点证据，适合短答，保留。 | 追踪一条缺页链路：trap/异常入口 → 缺页处理函数（handle_page_fault 或等价）→ 分配页帧 → 建立映射。用 3-5 个关键节点描述并给每节点证据。 |
| 03_mem_mgmt | Q03_012 | tri_state_impl | rewritten | final_action=keep；CoW 是单一 VM 能力，并要求说明触发点在 fault 或 fork，足以排除仅引用计数或只读映射，保留。 | 是否实现写时复制 (Copy-on-Write, CoW)？（必须三态；若 implemented 需说明触发点在 fault 中还是 fork 中） |
| 03_mem_mgmt | Q03_013 | tri_state_impl | rewritten | final_action=keep；Lazy Allocation 是单一延迟物理页分配能力，题干明确 brk/mmap/fault 触发位置，保留。 | 是否实现惰性分配 (Lazy Allocation)？（必须三态；若 implemented 需说明是在 brk/mmap 还是 fault 中分配） |
| 03_mem_mgmt | Q03_014 | tri_state_impl | rewritten | final_action=keep；swap_in/swap_out 或等价页面置换构成单一 swap 能力，需真实 I/O/置换证据，保留。 | 是否实现 swap（swap_in/swap_out 或等价页面置换）？（必须三态） |
| 03_mem_mgmt | Q03_015 | tri_state_impl | rewritten | final_action=keep；mmap 作为单一 syscall/映射能力审查，flags 只作为实现完整性条件；stub 形态已要求说明，保留。 | 是否实现 mmap（文件映射/匿名映射）且处理标志位（MAP_FIXED/MAP_ANON/MAP_SHARED 等）？（必须三态；stub 需说明形态如 ENOSYS/return 0） |
| 03_mem_mgmt | Q03_016 | tri_state_impl | rewritten | final_action=keep；Page Cache 边界已固定为 inode/文件对象 + page offset，并排除 block/buffer cache，保留。 | 是否存在文件页缓存 Page Cache（以 inode/文件对象 + page offset 为 key，并与 read/write/mmap/page fault/writeback 共享）？（必须三态） |
| 03_mem_mgmt | Q03_017 | tri_state_impl | rewritten | final_action=keep；dirty writeback 只看文件页/映射页脏页回写，并要求同步/异步触发条件，和 Page Cache 边界一致，保留。 | 是否存在文件页/映射页的脏页回写 (dirty page writeback) 机制？（必须三态；若 implemented 需指出同步/异步与触发条件） |
| 03_mem_mgmt | Q03_018 | tri_state_impl | rewritten | final_action=keep；TLB shootdown 明确要求 IPI/跨核调用证据，阶段约束已再次区分本地 flush，保留。 | 是否存在 TLB 射击 (TLB Shootdown / Remote TLB Flush)机制以支持多核页表一致性？（必须三态；若 implemented 需指向 IPI/跨核调用证据） |
| 03_mem_mgmt | Q03_019 | short_answer | rewritten | final_action=keep；本题只收集本地 TLB 刷新指令/封装点，不等价于 shootdown，和 Q03_018 分工清楚，保留。 | TLB 刷新指令/函数点是什么？（RISC-V sfence.vma / AArch64 tlbi / x86 invlpg 等，或仓库中等价的 TLB 刷新封装；必须给证据） |
| 03_mem_mgmt | Q03_020 | short_answer | rewritten | final_action=keep；用户指针检查要求入口点与校验逻辑，能和普通 copy 或裸指针使用区分，保留。 | 用户指针安全检查机制是什么？（access_ok/verify_area/UserInPtr 等；列出入口点与校验逻辑证据） |
| 03_mem_mgmt | Q03_021 | single_choice | rewritten | final_action=keep；页面置换算法是单选分类，候选项覆盖 LRU/Clock/FIFO/未实现，需先由 swap/reclaim 证据支撑，保留。 | 若实现了页面置换 (Page Replacement)，使用的算法最接近哪种？（Stallings Ch8：OPT 理想算法 / LRU 最近最少使用 / Clock 近似 LRU / FIFO / 未实现） |
| 03_mem_mgmt | Q03_022 | tri_state_impl | rewritten | final_action=keep；WSM/thrashing prevention 作为 Stallings 单一机制族审查，负向搜索关键词明确，保留。 | 是否存在工作集模型 (Working Set Model, WSM) 或抖动检测/防止 (Thrashing Prevention) 机制？（必须三态；Stallings Ch8 核心概念；若 not_found 需列出已搜关键字 working_set\|thrash\|resident_set） |
| 03_mem_mgmt | Q03_023 | fill_in | rewritten | final_action=keep；物理内存总量、页大小、虚拟地址位数是参数填空，要求常量/链接脚本/配置证据，保留。 | 物理内存总量（Physical Memory Size）：____ KB/MB；页大小（Page Size）：____ bytes；最大进程虚拟地址空间（Virtual Address Space）：____ bits。（必须从代码常量/链接脚本/配置中给出证据；无法确定则写 unknown 并说明已搜路径） |
| 03_mem_mgmt | Q03_024 | single_choice | rewritten | final_action=keep；内存保护形态是单选分类，需由页表权限、特权级或硬件保护证据支撑，保留。 | 内存保护机制 (Memory Protection) 的实现形式更接近哪种？（Stallings Ch7.1） |
| 03_mem_mgmt | Q03_025 | short_answer | rewritten | final_action=keep；逻辑内存组织要求 VMA/区间表/链表等统一结构证据，能排除零散常量和 loader 临时区间，保留。 | 逻辑内存组织 (Logical Memory Organization, Stallings Ch7.1)：进程地址空间中 text/data/heap/stack/mmap 各区域（或等价区间）是否由统一的映射管理结构（VMA/区间表/链表/BTreeMap 等）维护？（如存在请给结构体证据；不存在则写未发现等价结构） |
| 03_mem_mgmt | Q03_026 | single_choice | rewritten | final_action=keep；硬件分段与软件 VMA/纯分页明确分离，适合架构相关单选分类，保留。 | 是否存在显式的硬件分段机制 (Hardware Segmentation, Stallings Ch7.4)？ |
| 03_mem_mgmt | Q03_027 | single_choice | rewritten | final_action=keep；取页策略候选覆盖 demand paging、lazy、prepaging、pre-allocation 和不适用，保留。 | 取页策略 (Fetch Policy, Stallings Ch8.2) 更接近哪种？ |
| 03_mem_mgmt | Q03_028 | short_answer | rewritten | final_action=keep；放置策略需描述虚拟地址区间选择算法，短答能容纳固定地址、mmap_base、first-fit 等证据，保留。 | 放置策略 (Placement Policy, Stallings Ch8.2)：新的匿名映射或堆区域增长时，系统如何选择虚拟地址区间？（固定起始地址 / mmap_base 向下生长 / 首次适配 / 最佳适配 等；必须给实现证据或写未发现等价策略） |
| 03_mem_mgmt | Q03_029 | tri_state_impl | rewritten | final_action=keep；驻留集/负载控制按单一 Load Control 机制族判断，题干列举的回收线程/OOM/限制只作证据形态，保留。 | 是否存在驻留集管理/内存负载控制 (Resident Set Management / Load Control, Stallings Ch8.2)？（包括工作集动态调整、内存回收守护线程、OOM killer、驻留页数限制等；若 not_found 需列出已搜关键字） |
| 03_mem_mgmt | Q03_030 | short_answer | rewritten | final_action=keep；主链路题要求只画一条 3-6 节点证据链，能避免并列堆砌 grep 命中，保留。 | 内存主链路（必须给出，尽量以 Mermaid graph TD 表达）：从确认的最强内存入口（缺页处理入口/mmap 入口/brk 入口/等价入口）出发，追踪到页表操作核心点或物理页分配核心点，写出 3-6 个关键节点。节点格式：FuncName [path:line]。若链路未被源码证据完全闭合，标注候选主链路而非确认的主链路。只画一条主链，不要并列展开多条支线。 |
| 03_mem_mgmt | Q03_031 | single_choice | rewritten | final_action=keep；碎片类型单选依赖分配算法和页/对象粒度证据，能区分内部、外部、两者和未发现，保留。 | 该系统更容易出现哪种内存碎片 (Memory Fragmentation, Stallings Ch7.2)？ |
| 03_mem_mgmt | Q03_032 | single_choice | rewritten | final_action=keep；重定位绑定时机是 Stallings 分类题，候选项覆盖编译时、加载时、运行时 MMU 和不适用，保留。 | 地址重定位 (Address Relocation, Stallings Ch7.1) 的绑定时机更接近哪种？ |
| 03_mem_mgmt | Q03_033 | single_choice | rewritten | final_action=keep；页面置换作用域只能在存在 replacement/swap 后分类为全局或局部，否则选未实现/未发现，保留。 | 页面置换的作用域策略 (Replacement Scope, Stallings Ch8.2) 更接近哪种？ |
| 03_mem_mgmt | Q03_034 | tri_state_impl | rewritten | final_action=keep；Cleaning Policy 明确限定后台/预先写回，阶段约束补充不得把 block/buffer cache 混作 Page Cache，保留。 | 是否存在清理策略 (Cleaning Policy, Stallings Ch8.2)：后台/预先写回脏页或脏缓存，而非仅在置换或 fsync 时同步写回？（必须三态） |
| 04_process_smp | Q04_001 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 执行实体 (Execution Entity) 抽象是什么？ 请按以下格式作答（每项必须有代码证据）： - 顶层类型名: ___（如 Process / Task / Thread / TaskControlBlock） - 结构体路径: ___ - 关键字段（至少列 3 个）: Context=___, State=___, PID=___, TrapFrame=___ - 是否区分 PCB 与 TCB: ___（是 / 否 / 待核实） |
| 04_process_smp | Q04_002 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 任务/进程的生命周期状态机有哪些状态与流转点？（Ready/Running/Blocked/Exited 等；需状态枚举/字段证据） |
| 04_process_smp | Q04_003 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在上下文切换 (Context Switch) 实现（switch.S/__switch/swtch/context_switch）？（必须三态） |
| 04_process_smp | Q04_004 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 上下文切换保存/恢复了哪些寄存器集合？（例如 RISC-V s0-s11；必须引用汇编/结构体证据） |
| 04_process_smp | Q04_005 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 调度算法 (Scheduling Algorithm) 属于哪类？ 请按格式作答： - 算法名称: ___（必须是以下之一：FCFS / Round-Robin (RR) / Stride/Proportional-Share / MLFQ / CFS / Priority / 其他） - 代码证据（关键字段/函数）: ___ - RR: timeslice/slice 字段位置=___ - Stride: stride 字段与比较逻辑位置=___ - MLFQ: 多级队列 VecDeque/数组层级证据=___ - Priority: priority 字段参与 pick_next 排序证据=___ |
| 04_process_smp | Q04_006 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 调度器 (Scheduler)核心入口/关键函数有哪些？（schedule/pick_next 等；给 1-3 个入口与证据） |
| 04_process_smp | Q04_007 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 fork/clone（创建新执行实体）？（必须三态） |
| 04_process_smp | Q04_008 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | fork/clone 是否复制地址空间与文件表？（必须给复制路径证据；若 stub 需说明形态） |
| 04_process_smp | Q04_009 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 exec（装载 ELF/重建地址空间）？（必须三态） |
| 04_process_smp | Q04_010 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 wait/waitpid（父子回收同步）？（必须三态） |
| 04_process_smp | Q04_011 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | waitpid / wait4 的阻塞实现 (Blocking Implementation) 更接近哪种？ |
| 04_process_smp | Q04_012 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | PID 分配器实现是什么？（自增/bitmap/空闲栈复用/只分配不回收；必须给证据） |
| 04_process_smp | Q04_013 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 父子进程树如何存储？（children Vec/链表/parent+sibling 指针；必须给结构体字段证据） |
| 04_process_smp | Q04_014 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 进程/线程模块中 signal 与 futex 的进程状态集成情况如何？请分别给 signal、futex 的状态与证据；二者不能合并成一个三态结论。 |
| 04_process_smp | Q04_015 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 与本阶段 SMP/多核题的交叉一致性：是否存在每核队列/任务迁移/IPI resched？（需与本阶段 SMP 题互指证据或写不适用） |
| 04_process_smp | Q04_016 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | exit() 资源回收路径：调用链是什么？是否真正回收地址空间/文件表/通知父进程？（必须给调用链证据；桩则说明） |
| 04_process_smp | Q04_017 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现进程组/会话（Process Group / Session，pgid/session/set_sid/setpgid）？（必须三态；有则区分真实检查链 vs 仅占位字段） |
| 04_process_smp | Q04_018 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 POSIX 资源限制（rlimit/RLIMIT/getrlimit/setrlimit）？（必须三态；若 implemented 需说明支持的资源类型数量及软/硬限制机制） |
| 04_process_smp | Q04_019 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 该 OS 是否区分了 TCB（线程控制块）与 PCB（进程控制块）？ |
| 04_process_smp | Q04_020 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 调度切换路径上是否存在页表切换（w_satp/sfence.vma/写 CR3/TTBR 等）？（必须三态；给调用点 路径 证据） |
| 04_process_smp | Q04_021 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 用户线程与内核线程的映射模型 (User-Level Thread to Kernel-Level Thread Mapping) 更接近哪种？（Stallings Ch4） |
| 04_process_smp | Q04_022 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现线程局部存储 (Thread-Local Storage, TLS)？（必须三态；搜索 thread_local\|TLS\|__thread\|#[thread_local]；若 implemented 需说明 TLS 的访问方式：tp 寄存器/段寄存器/其他） |
| 04_process_smp | Q04_023 | multi_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 调度器是否追踪/优化以下哪些性能指标 (Scheduling Criteria, Stallings Ch9)？（多选；未发现则留空并在 notes 写 not_found） |
| 04_process_smp | Q04_024 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 优先级调度是否实现老化 (Aging, Stallings Ch9) 以防止低优先级进程饥饿 (Starvation)？（必须三态；搜索 age/aging/boost_priority 或等价；若 not_found 需说明是否存在饥饿风险） |
| 04_process_smp | Q04_025 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现公平份额调度（Fair-Share Scheduling）或可执行的 CPU 配额/权重控制？（必须三态；implemented 需证明份额/权重参与 CPU 时间分配） |
| 04_process_smp | Q04_026 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 调度器的抢占模式 (Preemption Mode, Stallings Ch9) 更接近哪种？ |
| 04_process_smp | Q04_027 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现最短作业优先调度 (Shortest Job First / SJF 或 SRTF, Stallings Ch9)？（必须三态；或等价的基于预测 burst 时间的调度） |
| 04_process_smp | Q04_028 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 该 OS 的多核形态更接近哪种？ |
| 04_process_smp | Q04_029 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在 Secondary CPU / AP 启动链（BSP 唤醒 AP，上线后进入 idle/调度）？（必须三态） |
| 04_process_smp | Q04_030 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 IPI（核间中断）发送与处理？（必须三态） |
| 04_process_smp | Q04_031 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 若存在 IPI：发送与处理路径分别在哪些函数/文件？（给关键入口与证据） |
| 04_process_smp | Q04_032 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在 per-CPU 变量/结构（PerCpu、CPU-local storage 等）？（必须三态） |
| 04_process_smp | Q04_033 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | per-CPU 的实现方式是什么？（例如 TLS/tp 寄存器/gsbase/数组索引 hartid；需证据） |
| 04_process_smp | Q04_034 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 调度是否存在跨核负载均衡/迁移/亲和性？（必须三态） |
| 04_process_smp | Q04_035 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 TLB shootdown（跨核页表一致性刷新）？（必须三态；需与 03 互指） |
| 04_process_smp | Q04_036 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 与 02/03/04/06 章的交叉一致性 (Cross-Chapter Consistency)，按以下四项分别作答（每项须给证据路径或写「单核不适用」）： - 03 TLB: 多核页表修改后 TLB 刷新策略=___ - 04 调度: 每核运行队列/负载均衡/IPI resched=___ - 02 Trap: per-CPU trap 栈/时钟中断初始化与 AP 上线顺序=___ - 06 锁: SpinLock 关中断行为在多核下是否安全=___ |
| 04_process_smp | Q04_037 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | SpinLock 在获取锁时是否禁用中断（关中断保护临界区）？ |
| 04_process_smp | Q04_038 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | NCPU/MAXCPU（或等价宏）与链接脚本中的每 hart 栈/入口布局是否对应？（搜索 _max_hart_id 等；给宏定义与链接脚本对应证据，或写未发现） |
| 04_process_smp | Q04_039 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否使用 AtomicUsize/原子变量分配 PID/TID（全局唯一 ID 池）？（必须三态；给实现证据） |
| 04_process_smp | Q04_040 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否支持实时调度 (Real-Time Scheduling, Stallings Ch10)？（必须三态；搜索 SCHED_FIFO / SCHED_RR / realtime / RT priority / deadline 等） |
| 04_process_smp | Q04_041 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在 NUMA (Non-Uniform Memory Access) 感知的内存分配或调度策略？（必须三态；搜索 numa / node_id / local_memory 等；嵌入式单 SoC 可写 not_found 并说明架构） |
| 04_process_smp | Q04_042 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 调度层级 (Long-Term / Medium-Term / Short-Term Scheduling, Stallings Ch9) 更接近哪种？ |
| 04_process_smp | Q04_043 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现优先级反转处理 (Priority Inversion Handling, Stallings Ch10)？（必须三态；如 priority inheritance / priority ceiling / 禁用抢占临界区等） |
| 05_fs_drivers | Q05_001 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | VFS 抽象层 (Virtual File System, VFS)接口是什么形态？（Rust trait / C op 表；必须给接口定义证据） |
| 05_fs_drivers | Q05_002 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 具体文件系统后端 (Concrete File System Backend) 更接近哪种？ |
| 05_fs_drivers | Q05_003 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 若支持 FAT32/Ext4：它是自研还是第三方库/crate？（必须引用 Cargo.toml/Cargo.lock 或 Makefile 引入证据） |
| 05_fs_drivers | Q05_004 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 文件打开路径：文件打开入口（sys_open 或等价）→ VFS 层 → 具体 FS open。列出 3-6 个关键节点并给证据。 |
| 05_fs_drivers | Q05_005 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 文件描述符表 (File Descriptor Table, FD Table) 的实现形态是什么？（固定数组/Vec/BTreeMap 等；必须给结构体定义证据） |
| 05_fs_drivers | Q05_006 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现块缓存/缓冲缓存 (Block Cache / Buffer Cache, bcache；以 device/blockno 或文件系统块号为 key)？（必须三态） |
| 05_fs_drivers | Q05_007 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 若存在块缓存/缓冲缓存：驱逐策略是什么（LRU/Clock/FIFO/引用计数保护/无驱逐）？必须指出判断依据（字段/算法分支）证据。 |
| 05_fs_drivers | Q05_008 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现文件页缓存 Page Cache（inode/文件对象 + page offset）或 mmap/文件映射共享缓存页？（必须三态） |
| 05_fs_drivers | Q05_009 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 mmap 的文件映射或匿名映射？（必须三态；若 stub 说明形态） |
| 05_fs_drivers | Q05_010 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 poll/select/epoll（或等价 fd 事件等待机制），并真实检查文件/socket/pipe readiness？（必须三态） |
| 05_fs_drivers | Q05_011 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 路径解析 (namei/path_walk/lookup) 是否实现并支持绝对/相对路径与 . ..？（必须三态） |
| 05_fs_drivers | Q05_012 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否支持符号链接 (symlink) 的解析/跟随？（必须三态） |
| 05_fs_drivers | Q05_013 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现管道 (pipe/pipe2) 并在 VFS 层作为文件对象？（必须三态；与 06 同步/IPC 的 pipe 实现互指） |
| 05_fs_drivers | Q05_014 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现网络 socket（作为 VFS 文件对象）？（必须三态） |
| 05_fs_drivers | Q05_015 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现伪文件系统（devfs/procfs/sysfs）？（必须三态；若 implemented 需说明实现形态） |
| 05_fs_drivers | Q05_016 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 文件描述符表的归属是哪种？ |
| 05_fs_drivers | Q05_017 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 文件数据块分配方式 (File Allocation Method, Stallings Ch12) 更接近哪种？ |
| 05_fs_drivers | Q05_018 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 磁盘/存储空闲空间管理 (Free Space Management, Stallings Ch12) 更接近哪种？ |
| 05_fs_drivers | Q05_019 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 目录结构 (Directory Structure, Stallings Ch12) 更接近哪种？ |
| 05_fs_drivers | Q05_020 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 文件内部记录组织 (File Record Organization, Stallings Ch12) 更接近哪种？ |
| 05_fs_drivers | Q05_021 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 设备发现/枚举机制更接近哪种？ |
| 05_fs_drivers | Q05_022 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否能在代码中证实解析了 `.dtb`/DeviceTree？（必须三态；若 implemented 必须指出解析入口） |
| 05_fs_drivers | Q05_023 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 驱动框架接口是什么？（Rust Driver trait / C driver ops / 注册表；必须引用接口定义证据） |
| 05_fs_drivers | Q05_024 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 驱动注册与初始化顺序是什么？（init_drivers/probe/driver_manager 等；列出 3-6 个关键节点并给证据） |
| 05_fs_drivers | Q05_025 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 UART/Console 驱动用于早期输出？（必须三态） |
| 05_fs_drivers | Q05_026 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现块设备驱动（virtio-blk/ramdisk/其他）？（必须三态） |
| 05_fs_drivers | Q05_027 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现网络设备驱动（virtio-net/e1000/rtl8139 等）？（必须三态） |
| 05_fs_drivers | Q05_028 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现中断控制器驱动（PLIC/CLINT/APIC 等）？（必须三态；需指出中断源到 handler 的分发证据） |
| 05_fs_drivers | Q05_029 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | MMIO 地址来源是什么？（DTB 提供 / 常量硬编码 / 物理→虚拟转换；必须给证据） |
| 05_fs_drivers | Q05_030 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 多平台适配是如何通过构建/条件编译选择驱动的？（features/Kconfig/Makefile 规则；必须给证据） |
| 05_fs_drivers | Q05_031 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在 MMU 启用前后串口地址切换（phys/virt 切换）逻辑？（必须三态） |
| 05_fs_drivers | Q05_032 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | I/O 缓冲模式 (I/O Buffering) 最接近哪种？（Stallings Ch11：单缓冲 Single Buffer / 双缓冲 Double Buffer / 循环缓冲 Circular Buffer / 缓冲池 Buffer Pool / 无缓冲 No Buffer） |
| 05_fs_drivers | Q05_033 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 块设备（磁盘/eMMC/NVMe）I/O 请求调度算法 (Scheduling Algorithm) (Disk Scheduling Algorithm) 更接近哪种？（Stallings Ch11；若无显式调度则选「FCFS 顺序提交」） |
| 05_fs_drivers | Q05_034 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | I/O 控制技术 (I/O Control Techniques, Stallings Ch11) 更接近哪种？ |
| 05_fs_drivers | Q05_035 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 DMA (Direct Memory Access, Stallings Ch11) 传输路径？（必须三态；搜索 dma_alloc / dma_map / dma_buf / virtio 描述符环等；virtio 的描述符环也算 DMA 等价机制） |
| 05_fs_drivers | Q05_036 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | I/O 软件分层 (Logical Structure of the I/O Function, Stallings Ch11) 是什么？请追踪一个 read/write 请求从 syscall/VFS 到驱动提交的 3-6 个层级。 |
| 05_fs_drivers | Q05_037 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 异步与同步 I/O (Asynchronous vs Synchronous I/O, Stallings Ch11) 的实现更接近哪种？ |
| 05_fs_drivers | Q05_038 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现文件共享访问权与并发访问控制 (File Sharing Access Rights / Simultaneous Access, Stallings Ch12)？（必须三态） |
| 06_sync_ipc | Q06_001 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 该内核提供了哪些同步原语？（SpinLock/Mutex/RwLock/Semaphore/Condvar/WaitQueue 等；列出类型定义证据） |
| 06_sync_ipc | Q06_002 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | Mutex 更接近哪种实现？ |
| 06_sync_ipc | Q06_003 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在等待队列 (Wait Queue, WaitQueue) 与 sleep/wakeup（或等价阻塞/唤醒）实现？（必须三态） |
| 06_sync_ipc | Q06_004 | fill_in | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | sleep / wakeup 不变量 (Sleep-Wakeup Invariant) 分析，按格式填写： - sleep 入口函数: ___（路径） - 入睡前持有的锁: ___（无则写 none） - 防丢 wakeup (Lost Wakeup Prevention) 机制: ___（如：持队列锁检查条件 / 无防护） - wakeup 函数: ___（路径） - 唤醒与锁释放顺序: ___（先唤醒后释放 / 先释放后唤醒 / 其他） |
| 06_sync_ipc | Q06_005 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现管道 (Pipe)？（必须三态） |
| 06_sync_ipc | Q06_006 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | pipe 缓冲形态更接近哪种？ |
| 06_sync_ipc | Q06_007 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | pipe 的阻塞语义更接近哪种？ |
| 06_sync_ipc | Q06_008 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | SysV IPC 覆盖情况如何？请分别回答 Message Queue、Semaphore、Shared Memory 三类系统调用/内核对象的状态（implemented/stub/not_found/unknown）并给证据。 |
| 06_sync_ipc | Q06_009 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 futex？（必须三态） |
| 06_sync_ipc | Q06_010 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现信号机制（sigaction/kill/sigreturn/trampoline）？（必须三态） |
| 06_sync_ipc | Q06_011 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 若实现 signal handler：用户态 handler 上下文如何构建？是否存在 sigreturn 恢复原 trap frame？（必须给证据） |
| 06_sync_ipc | Q06_012 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | RwLock（读写锁 Reader-Writer Lock）的实现形态更接近哪种？ |
| 06_sync_ipc | Q06_013 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 底层原子操作来源更接近哪种？ |
| 06_sync_ipc | Q06_014 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 死锁四必要条件（Coffman Conditions）在该内核中是否均成立？ 请逐条作答（互斥 Mutual Exclusion / 持有并等待 Hold-and-Wait / 不可剥夺 No Preemption / 循环等待 Circular Wait），并结合 SpinLock/Mutex 的实现给出证据或写「不适用」。 |
| 06_sync_ipc | Q06_015 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 内核对死锁 (Deadlock) 的处理策略更接近哪种？ |
| 06_sync_ipc | Q06_016 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在全局锁顺序（Lock Ordering）规范或注释，以预防嵌套锁导致的循环等待死锁 (Circular Wait Deadlock)？（必须三态；若 implemented 需给出锁排序规则或 ABBA 锁检测代码证据） |
| 06_sync_ipc | Q06_017 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现管程/条件变量 (Monitor / Condition Variable, Stallings Ch5)？（必须三态；搜索 Condvar / condition_variable / monitor / wait/notify/signal 等；若 implemented 需区分 Hoare 语义（等待者立即恢复）vs Mesa 语义（等待者重新竞争锁）） |
| 06_sync_ipc | Q06_018 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 经典同步问题验证 (Classic Synchronization Problems, Stallings Ch5)： 以下三个经典问题在该内核中是否有对应实现或测试？ - 生产者-消费者 (Producer-Consumer / Bounded Buffer)：___（implemented/not_found + 证据） - 读者-写者 (Readers-Writers)：___（实现了读者优先/写者优先/公平？ + 证据） - 哲学家就餐 (Dining Philosophers)：___（implemented/not_found） |
| 06_sync_ipc | Q06_019 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 Stallings Ch5 意义上的消息传递 IPC？请区分 direct message passing、indirect mailbox、POSIX/System V message queue，并给各自状态与证据。 |
| 06_sync_ipc | Q06_020 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现屏障同步 (Barrier Synchronization, Stallings Ch5)？（必须三态；搜索 barrier / sync_barrier / pthread_barrier 或等价；用于多线程/多核同步到同一检查点） |
| 06_sync_ipc | Q06_021 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现计数信号量 (Counting Semaphore, Stallings Ch5) 及 P/V(wait/signal) 语义？（必须三态；与 Mutex/SpinLock 区分） |
| 07_security | Q07_001 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 特权级隔离形态更接近哪种？ |
| 07_security | Q07_002 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在凭证/权限数据结构（UID/GID/Credential/Capability/ACL 等）？（必须三态） |
| 07_security | Q07_003 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否能证实在 syscall 路径上真实执行了权限检查（open/exec/write 等）？（必须三态；仅有字段不算 implemented） |
| 07_security | Q07_004 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 若存在权限检查：入口点与核心检查函数链路是什么？（列 2-5 个节点并给证据） |
| 07_security | Q07_005 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现用户指针验证（access_ok/verify_area/UserInPtr/copyin/copyout 等）？（必须三态） |
| 07_security | Q07_006 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 seccomp/prctl/sandbox 等系统调用过滤/沙箱？（必须三态；stub 需说明形态：ENOSYS/return 0） |
| 07_security | Q07_007 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在栈保护/溢出防护（stack canary/guard page）或等价机制？（必须三态） |
| 07_security | Q07_008 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 审计、Secure Boot、签名校验覆盖情况如何？请分别给 audit logging、secure boot、signature verification 的状态（implemented/stub/not_found/unknown）和证据。 |
| 07_security | Q07_009 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 本项目支持哪些架构（riscv64/aarch64/x86_64/loongarch64 等）？每种架构的安全相关初始化（特权级配置、PMP/MPU/SMEP 等）是否有代码证据？（必须逐架构作答，无证据写「未发现」） |
| 07_security | Q07_010 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 若项目使用 Rust，是否存在 RAII/所有权/生命周期相关的内核安全机制（如不可 unsafe 直接访问用户内存、锁的 RAII 自动释放等）？（必须三态；给具体模式证据） |
| 07_security | Q07_011 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 内核/用户地址空间隔离与架构安全保护覆盖情况如何？请按当前支持架构分别说明 KPTI/双页表、SMEP/SMAP、PMP/MPU、TTBR0/TTBR1 或等价机制的状态与证据。 |
| 07_security | Q07_012 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | UID/GID 字段是否在 syscall 路径上真实执行权限检查？（搜索 check_perm/inode_permission；若只有字段无检查链须标注「仅有定义但未强制执行 🔸」；给检查链证据或写「字段存在但无检查链」） |
| 07_security | Q07_013 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 访问控制模型 (Access Control Model, Stallings Ch15) 更接近哪种？ |
| 07_security | Q07_014 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在至少一条被内核强制执行的完整性策略（Biba/只读内核段/代码签名验证/W^X 等之一）？（必须三态；implemented 必须指出具体策略和拒绝/故障路径） |
| 07_security | Q07_015 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否启用至少一种可证实的缓冲区溢出防护（stack canary、guard page、NX/W^X、ASLR、边界检查等）？（必须三态；implemented 需指出具体防护类型和触发/检查路径） |
| 07_security | Q07_016 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 系统硬化与安全维护 (OS Hardening / Security Maintenance, Stallings Ch15) 在代码或构建中有哪些可证实措施？按“服务裁剪、权限最小化、审计日志、备份/恢复、补丁/版本策略”逐项回答。 |
| 08_network | Q08_001 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在网络子系统实现（协议栈或 socket 层）？（必须三态） |
| 08_network | Q08_002 | single_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 协议栈来源更接近哪种？ |
| 08_network | Q08_003 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 socket 系统调用接口（socket/bind/connect/sendto/recvfrom 等）？（必须三态） |
| 08_network | Q08_004 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 选择一个发送路径（优先 sys_sendto），追踪：syscall → 协议栈 → 网卡驱动。列 3-6 个关键节点并给证据。 |
| 08_network | Q08_005 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现网卡驱动（virtio-net/e1000 等）与收包中断路径？（必须三态） |
| 08_network | Q08_006 | multi_choice | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 协议支持情况（多选；未发现则留空并在 notes 写 not_found）： |
| 08_network | Q08_007 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 网络数据路径中是否存在用户可见 zero-copy、内核共享缓冲、或网卡 DMA descriptor？请分别给状态与证据；普通 DMA descriptor 不自动等于 zero-copy。 |
| 09_debug_error | Q09_001 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在日志系统（log/printk/println 宏）与日志级别控制？（必须三态） |
| 09_debug_error | Q09_002 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在 panic/崩溃处理路径（panic_handler/oom/abort 等）？（必须三态） |
| 09_debug_error | Q09_003 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | panic 路径会输出哪些诊断？（寄存器 dump/栈回溯/停机；必须引用实现证据） |
| 09_debug_error | Q09_004 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现栈回溯 (backtrace/unwind/stack_trace)？（必须三态；仅打印 ra 不算） |
| 09_debug_error | Q09_005 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在 **内核驻留的交互式调试监视器（kernel debug monitor）**？（本题指内核态命令解释器/调试控制台；不要与 Stallings Ch5 的 Monitor/Condition Variable 同步构造混淆；不包括仅在用户态运行的常规 shell。必须三态；若 implemented，须给出 3-10 个用户可键入的 monitor 命令名及对应内核内解析/分发入口证据。） |
| 09_debug_error | Q09_006 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否实现 GDB stub（需数据包解析循环，如 handle_gdb_packet）？（必须三态） |
| 09_debug_error | Q09_007 | short_answer | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 错误码/错误类型体系是什么？（errno/Result/Error enum；给类型定义与传播点证据） |
| 09_debug_error | Q09_008 | tri_state_impl | rewritten | 逐字定稿题干口径、概念边界、结构化事实、三态/短答合约，并同步 features 镜像。 | 是否存在 trace/perf/ftrace 等跟踪机制或 tracepoints？（必须三态） |
