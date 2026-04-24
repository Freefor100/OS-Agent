# 03_mem_mgmt — Baseline vs Agent

- 题库题数: 34
- baseline `report_quality_score`: 0.97
- agent `report_quality_score`: 0.97

| question_id | type | agreement | better_side(初值) | baseline_se | baseline_sc | agent_se | agent_sc | baseline_value | agent_value |
|---|---|:---|:---|---:|---:|---:|---:|---|---|
| Q03_001 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | B. C/Makefile 风格内核（xv6 类） | B. C/Makefile 风格内核（xv6 类） |
| Q03_002 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q03_003 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | D. 空闲链表 run list（xv6 风格） | D. 空闲链表 run list（xv6 风格） |
| Q03_004 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | struct run 单链表 + struct pm_allocator。struct run 包含 next 指针和 npage 字段表示连续空闲页数；pm_allocator 包含 freelist 链表头、锁和总页数 | 核心数据结构是 struct run 单链表和 struct pm_allocator 分配器结构。struct run 包含 next 指针和 npage 字段表示连续页数；struct pm_allocator 包含 spinlock 锁、freelist 链表头和 npage 总页数。系统维护 single 和 multiple 两个分配器实例，single 管理 400 页以下的小区域，multiple 管理大区域。 |
| Q03_005 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 全局大锁（两个独立的全局锁：multiple.lock 和 single.lock）。使用 struct spinlock，在分配/释放时通过 acquire/release 保护整个分配器 | 使用全局大锁（global spinlock），每个分配器（single/multiple）各有一个独立的 spinlock。持锁范围覆盖整个分配/释放操作。通过 acquire(&single.lock) 和 acquire(&multiple.lock) 实现互斥，使用宏 __enter_sin_cs/__leave_sin_cs 和 __enter_mul_cs/__leave_mul_cs 封装临界区。 |
| Q03_006 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q03_007 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | walk() - 页表遍历; mappages() - 建立映射; unmappages() - 解除映射。均在 kernel/mm/vm.c 中实现 | 关键入口函数：1) walk(pagetable_t pagetable, uint64 va, int alloc) - 三级页表遍历，kernel/mm/vm.c:210-232；2) mappages(pagetable_t pagetable, uint64 va, uint64 size, uint64 pa, int perm) - 建立映射，kernel/mm/vm.c:296-330；3) unmappages(p... |
| Q03_008 | short_answer | 表述差异 | 待酌 | 0.90 | 1.00 | 0.95 | 1.00 | 每进程地址空间锁（通过 proc->lk 和 pagetable 归属保护）。页表操作在进程上下文中进行，通过进程锁和内存管理函数内部的同步机制保护。修改后调用 sfence_vma() 刷新 TLB | 页表修改路径未使用显式的页表锁。页引用计数使用全局锁 page_ref_lock（spinlock）保护 page_ref_table 数组。mappages/unmappages 本身无锁，依赖调用者（如 uvmalloc/uvmcopy）保证单线程访问。页故障处理时通过 monopolizepage() 获取 page_ref_lock 实现 COW 页面的原子操作。未使用每进程地址空间锁，未显式关中断。 |
| **Q03_009** | single_choice | 结论冲突 | 待核验 | 0.95 | 1.00 | 0.90 | 1.00 | A. 内核与用户独立页表（切换 CR3/SATP） | B. 共享同一页表（内核映射常驻，高半核等） |
| Q03_010 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q03_011 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 1. kerneltrap() (kernel/trap/trap.c) 捕获异常 → 2. handle_excp() 识别缺页类型 → 3. handle_page_fault() 根据段类型分发 → 4. uvmalloc/allocpage 分配物理页 → 5. mappages 建立页表映射 | 缺页链路：1) usertrap() [kernel/trap/trap.c:78-130] 捕获异常并调用 handle_excp()；2) handle_excp() [kernel/trap/trap.c:405-425] 根据 scause 调用 handle_page_fault(kind, r_stval())；3) handle_page_fault() [kernel/mm/vm.c:1025-1091] 根据段类... |
| Q03_012 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q03_013 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | implemented | implemented |
| Q03_014 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | not_found | not_found |
| Q03_015 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | implemented | implemented |
| Q03_016 | tri_state_impl | 结论冲突 | 待核验 | 0.95 | 1.00 | 0.90 | 1.00 | stub | not_found |
| Q03_017 | tri_state_impl | 结论冲突 | 待核验 | 0.95 | 1.00 | 0.90 | 1.00 | stub | not_found |
| Q03_018 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | not_found | not_found |
| Q03_019 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | RISC-V sfence.vma 指令，封装在 sfence_vma() 函数中。在 include/hal/riscv.h 定义 | 使用 RISC-V sfence.vma 指令。封装函数为 sfence_vma()，定义于 include/hal/riscv.h:362-367。调用点包括：kernel/mm/vm.c:584（uvmcopy 后）、kernel/mm/vm.c:1001（handle_page_fault_lazy 后）、kernel/mm/vm.c:1018（handle_page_fault_loadelf 后）、kernel/mm/m... |
| Q03_020 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 通过 copyin/copyout/copyinstr 系列函数检查。使用 rangeinseg() 验证地址在进程段内，walkaddr() 验证页表映射存在。内核访问用户空间必须通过这些函数 | 使用 copyout/copyin/copyinstr 系列函数进行用户指针检查。copyout() [kernel/mm/vm.c:750-770] 通过 walkaddr() 验证虚拟地址是否映射；copyout2() [kernel/mm/vm.c:772-782] 使用 partofseg() 检查地址是否在合法段内；safememmove() [kernel/mm/vm.c:715-745] 通过设置 save_poin... |
| Q03_021 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | F. 未实现页面置换（无 swap） | F. 未实现页面置换（无 swap） |
| Q03_022 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | not_found | not_found |
| Q03_023 | fill_in | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 物理内存总量：6 MB (PHYSTOP 0x80600000 - KERNBASE 0x80020000 ≈ 6MB usable); 页大小：4096 bytes; 最大进程虚拟地址空间：39 bits (Sv39, MAXVA = 1L << 38) | 物理内存总量：6 MB（PHYSTOP 0x80600000 - KERNBASE 0x80020000 = 0x5E0000 ≈ 6MB）；页大小：4096 bytes（PGSIZE）；最大进程虚拟地址空间：39 bits（Sv39，MAXVA = 1L << (9+9+9+12-1) = 2^38，但实际为 39 位地址空间）。 |
| Q03_024 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | C. 硬件页表 + 软件指针检查双重保护 | C. 硬件页表 + 软件指针检查双重保护 |
| Q03_025 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 是，通过 struct seg 链表维护。enum segtype 定义 LOAD, TEXT, DATA, BSS, HEAP, MMAP, STACK 类型。每个进程 proc->segment 指向段链表头 | 使用 struct seg 链表维护进程地址空间区域。struct seg 定义于 include/mm/usrmm.h:10-19，包含 type（enum segtype：LOAD/TEXT/DATA/BSS/HEAP/MMAP/STACK）、addr（起始地址）、sz（大小）、flag（权限）、next（链表指针）等字段。通过 locateseg() [kernel/mm/usrmm.c:120-138] 查找地址所属段，n... |
| Q03_026 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | C. 纯分页无分段（RISC-V/AArch64 常见） | C. 纯分页无分段（RISC-V/AArch64 常见） |
| Q03_027 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | A. 按需调页 (Demand Paging)：缺页时才分配物理页 | A. 按需调页 (Demand Paging)：缺页时才分配物理页 |
| Q03_028 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | 首次适配（first-fit）。mmap 从 VUMMAP (0x70000000) 开始向上查找第一个足够大的空闲区间。通过遍历段链表查找间隙 | 使用段链表管理，新段通过 newseg() 创建并插入链表。堆区域增长通过 uvmalloc() 从 start 到 end 连续分配。mmap 区域使用固定起始地址 VUMMAP (0x70000000)。未发现动态地址选择策略（如首次适配/最佳适配），段地址由 exec/mmap 系统调用直接指定。 |
| Q03_029 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | not_found | not_found |
| Q03_030 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 0.95 | 1.00 | kerneltrap [kernel/trap/trap.c] --> handle_excp [kernel/trap/trap.c] --> handle_page_fault [kernel/mm/vm.c] --> handle_page_fault_lazy [kernel/mm/vm.c] --> uvmalloc [kernel/mm/vm.c] --> allocpage [kernel/mm/pm.c] --> ... | graph TD<br>usertrap[kernel/trap/trap.c:78] --> handle_excp[kernel/trap/trap.c:405]<br>handle_excp --> handle_page_fault[kernel/mm/vm.c:1025]<br>handle_page_fault --> handle_page_fault_lazy[kernel/mm/vm.c:988]<br>hand... |
| Q03_031 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | B. 外部碎片 (External Fragmentation)：空闲块分散无法满足大连续请求 | B. 外部碎片 (External Fragmentation)：空闲块分散无法满足大连续请求 |
| Q03_032 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.95 | 1.00 | C. 运行时动态绑定 (Run-time / Dynamic Relocation)：通过 MMU 基址+界限或页表在每次访问时转换 | C. 运行时动态绑定 (Run-time / Dynamic Relocation)：通过 MMU 基址+界限或页表在每次访问时转换 |
| Q03_033 | single_choice | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | C. 未实现置换（无 swap） | C. 未实现置换（无 swap） |
| Q03_034 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | not_found | not_found |

统计: 一致=20, 表述差异=11, 结论冲突=3
