from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


TECH_STAGE_IDS: Set[str] = {
    "02_boot_trap",
    "03_mem_mgmt",
    "04_process_smp",
    "05_fs_drivers",
    "06_sync_ipc",
    "07_security",
    "08_network",
    "09_debug_error",
}

TRI_STATE_VALUES = {"implemented", "stub", "not_found", "unknown"}

STRONG_EVIDENCE_TYPES = {
    "definition",
    "implementation_body",
    "function_body",
    "call_site",
    "usage_flow",
    "call_graph",
    "read_code_segment",
}

HINT_EVIDENCE_TYPES = {"search", "semantic_search", "rag", "grep", "outline"}

DEFAULT_TRI_STATE_RULE = {
    "allowed_values": ["implemented", "stub", "not_found", "unknown"],
    "implemented": (
        "Requires strong source evidence: a readable function body, concrete call site, "
        "state mutation, data-structure access, or verified execution flow. RAG/grep hits "
        "are hints only."
    ),
    "stub": (
        "Use when a symbol exists but the body is empty, returns a fixed placeholder, "
        "returns ENOSYS/unsupported, or contains todo!/unimplemented!/panic placeholder."
    ),
    "not_found": (
        "Requires structured negative search that covers the feature keywords and relevant "
        "seed directories."
    ),
    "unknown": (
        "Use when coverage is incomplete, evidence conflicts, or only weak hints exist."
    ),
}

DEFAULT_ANTI_EXAMPLES = [
    "RAG/grep 命中一个函数名，但没有读取实现体，不能判 implemented。",
    "只看到 trait/struct/extern 声明，不能判 implemented。",
    "只搜了一个关键词或一个目录，不能判 not_found。",
]

TEXTBOOK_BASIS_BY_STAGE: Dict[str, List[Dict[str, Any]]] = {
    "02_boot_trap": [
        {
            "source": "Stallings Operating Systems, Ch1.4 Interrupts; Ch2.3 Major Achievements",
            "concepts": ["interrupts", "exceptions", "mode switching", "system-call boundary", "protection"],
        },
        {
            "source": "Stallings Ch1.8 Multiprocessor and Multicore Organization",
            "concepts": ["per-CPU initialization", "multiprocessor boot", "interrupt routing"],
        },
    ],
    "03_mem_mgmt": [
        {
            "source": "Stallings Ch7 Memory Management",
            "concepts": ["relocation", "protection", "sharing", "paging", "segmentation", "buddy system"],
        },
        {
            "source": "Stallings Ch8 Virtual Memory",
            "concepts": ["fetch policy", "placement policy", "replacement policy", "resident set", "cleaning policy", "load control"],
        },
    ],
    "04_process_smp": [
        {
            "source": "Stallings Ch3 Process Description and Control; Ch4 Threads",
            "concepts": ["PCB", "TCB", "process states", "context switch", "process creation"],
        },
        {
            "source": "Stallings Ch9 Uniprocessor Scheduling; Ch10 Multiprocessor and Real-Time Scheduling",
            "concepts": ["scheduling criteria", "priorities", "fair-share", "real-time scheduling", "SMP scheduling"],
        },
    ],
    "05_fs_drivers": [
        {
            "source": "Stallings Ch11 I/O Management and Disk Scheduling",
            "concepts": ["I/O control techniques", "buffering", "disk scheduling", "DMA", "disk cache"],
        },
        {
            "source": "Stallings Ch12 File Management",
            "concepts": ["file organization", "directories", "file sharing", "file allocation", "free-space management", "VFS"],
        },
    ],
    "06_sync_ipc": [
        {
            "source": "Stallings Ch5 Concurrency: Mutual Exclusion and Synchronization",
            "concepts": ["mutual exclusion", "semaphores", "monitors", "message passing", "readers-writers"],
        },
        {
            "source": "Stallings Ch6 Deadlock and Starvation",
            "concepts": ["deadlock conditions", "prevention", "avoidance", "detection", "starvation"],
        },
    ],
    "07_security": [
        {
            "source": "Stallings Ch15 Operating System Security",
            "concepts": ["access control", "access rights", "buffer overflow defenses", "hardening", "integrity"],
        },
        {
            "source": "Stallings Ch7/Ch8 Memory Protection and Sharing",
            "concepts": ["kernel/user isolation", "memory protection", "sharing controls"],
        },
    ],
    "08_network": [
        {
            "source": "Stallings Ch16 Distributed Processing and Client/Server",
            "concepts": ["client/server", "message passing", "reliability", "networked system interface"],
        },
        {
            "source": "Stallings Ch11 I/O Management",
            "concepts": ["network device I/O", "interrupt-driven I/O", "DMA/buffer management"],
        },
    ],
    "09_debug_error": [
        {
            "source": "Stallings Ch2.5 Fault Tolerance; Ch15 Security Maintenance",
            "concepts": ["faults", "error handling", "diagnostics", "logging", "monitoring"],
        },
    ],
}


FACT_STATUS_VALUES = ["yes_strong", "yes_weak", "stub_or_declaration_only", "no_after_negative_search", "unknown"]


def _question_specific_tri_state_rule(stem: str, keywords: List[str], diagnostic_checks: List[str]) -> Dict[str, Any]:
    topic = stem[:120] or "该机制"
    checks = diagnostic_checks[:8] or [
        "定位相关结构/函数/配置入口。",
        "读取定义或实现体，确认不是声明或简单占位。",
        "查找调用点或数据流，确认该机制在主路径中被使用。",
        "若未找到，按 negative_search_policy 覆盖关键词和目录后再判 not_found。",
    ]
    return {
        "allowed_values": ["implemented", "stub", "not_found", "unknown"],
        "feature_scope": topic,
        "diagnostic_checks": checks,
        "implemented": (
            f"仅当 `{topic}` 的关键子问题被强证据闭合时才判 implemented："
            "至少要有实现体/调用点/状态变化/数据结构读写/流程证据之一，且不能只依赖 RAG/grep hint。"
        ),
        "stub": (
            f"若 `{topic}` 只发现接口、结构体壳、trait 声明、空实现、固定返回、ENOSYS/unsupported、"
            "todo!/unimplemented! 等占位形态，判 stub。"
        ),
        "not_found": (
            f"只有在按本题关键词与目录完成结构化负向搜索后，仍未发现 `{topic}` 的相关结构、实现体、"
            "调用点或配置入口，才判 not_found。"
        ),
        "unknown": (
            "当只找到弱线索、搜索覆盖不足、证据互相冲突、或 diagnostic_checks 未完成时，判 unknown；"
            "不要强迫模型二选一。"
        ),
        "required_reasoning": (
            "先逐项回答 diagnostic_checks，再根据 implemented/stub/not_found/unknown rubric 给最终值。"
        ),
        "keywords": keywords[:16],
    }


def _textbook_basis_for_question(stage_id: str, stem: str) -> List[Dict[str, Any]]:
    basis = list(TEXTBOOK_BASIS_BY_STAGE.get(stage_id, []))
    low = (stem or "").lower()
    extra: List[Dict[str, Any]] = []
    if "page cache" in low or "页缓存" in stem or "dirty" in low or "writeback" in low or "清理策略" in stem:
        extra.append(
            {
                "source": "Stallings Ch8.2 Operating System Software",
                "concepts": ["cleaning policy", "resident set management", "replacement policy", "virtual memory software"],
            }
        )
    if "buffer cache" in low or "block cache" in low or "块缓存" in stem or "disk cache" in low:
        extra.append(
            {
                "source": "Stallings Ch11.4 I/O Buffering; Ch11.7 Disk Cache",
                "concepts": ["buffering", "buffer pool", "disk cache", "write-back/write-through"],
            }
        )
    if "file allocation" in low or "free space" in low or "directory" in low or "vfs" in low or "文件" in stem:
        extra.append(
            {
                "source": "Stallings Ch12 File Management",
                "concepts": ["file allocation", "free-space management", "directories", "access rights", "VFS"],
            }
        )
    if "deadlock" in low or "死锁" in stem or "coffman" in low:
        extra.append(
            {
                "source": "Stallings Ch6.1 Principles of Deadlock",
                "concepts": ["mutual exclusion", "hold and wait", "no preemption", "circular wait"],
            }
        )
    if "monitor" in low or "condvar" in low or "condition" in low or "管程" in stem:
        extra.append(
            {
                "source": "Stallings Ch5.4 Monitors",
                "concepts": ["monitor", "condition variable", "Hoare semantics", "Mesa semantics"],
            }
        )
    if "message passing" in low or "消息传递" in stem:
        extra.append(
            {
                "source": "Stallings Ch5.5 Message Passing",
                "concepts": ["direct addressing", "indirect mailbox", "blocking", "nonblocking"],
            }
        )
    if "real-time" in low or "实时" in stem or "deadline" in low:
        extra.append(
            {
                "source": "Stallings Ch10.2 Real-Time Scheduling",
                "concepts": ["deadline scheduling", "rate monotonic", "priority inversion"],
            }
        )
    if "security" in low or "权限" in stem or "access control" in low or "完整性" in stem:
        extra.append(
            {
                "source": "Stallings Ch15.3 Access Control",
                "concepts": ["access control policy", "access matrix", "ACL", "capabilities", "integrity policy"],
            }
        )
    return _dedupe_basis(basis + extra)[:4]


def _dedupe_basis(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        source = str(item.get("source") or "")
        if not source or source in seen:
            continue
        seen.add(source)
        out.append(item)
    return out


def _concept_boundary_for_question(stem: str) -> str:
    low = (stem or "").lower()
    if "page cache" in low or "页缓存" in stem:
        return (
            "Page Cache 必须以文件对象/inode/address_space 与 page offset 为索引，并与读写、mmap 或缺页路径相连；"
            "仅 blockno keyed 的 buffer cache、孤立 mmap 页记录或名称命中不能等同于 Page Cache。"
        )
    if "buffer cache" in low or "block cache" in low or "块缓存" in stem:
        return (
            "Buffer/Block Cache 的对象是块设备块或文件系统块，通常以 device+blockno 为 key；"
            "它不自动证明存在文件页缓存或 inode+offset 级共享。"
        )
    if "dirty" in low or "writeback" in low or "脏页" in stem or "清理策略" in stem:
        return "脏页/脏块机制需要写路径设置 dirty 状态和 flush/writeback 清理路径；常量、注释或同步直写不等于清理策略。"
    if "mmap" in low:
        return "mmap 需要入口、flag 解析、VMA/地址空间登记以及 fault/readback 路径；固定返回或忽略 flags 是 stub。"
    if "cow" in low or "copy-on-write" in low or "写时复制" in stem:
        return "CoW 需要 fork/clone 共享页、写保护/COW 标志、fault 时复制、引用计数或等价生命周期管理闭环。"
    if "lazy" in low or "惰性" in stem:
        return "Lazy allocation 需要先登记虚拟区间，再由 page fault 按需分配；立即分配或仅有注释不能算实现。"
    if "syscall" in low or "系统调用" in stem:
        return "系统调用实现必须区分分发表注册、边界检查、参数复制和具体实现体；注册名字不等于实现。"
    if "signal" in low or "信号" in stem or "sigsegv" in low:
        return "信号机制至少要区分发送、pending 状态、trap 返回前派发和 sigreturn/trampoline；常量或 kill stub 不足以证明完整实现。"
    if "kernel monitor" in low or "内核驻留" in stem:
        return "Kernel monitor 是内核态命令解析/分发环境；用户态 shell 或测试程序不能替代内核 monitor。"
    if "condvar" in low or "condition" in low or "管程" in stem:
        return "条件变量/管程需要 wait 原子释放锁并睡眠、signal/broadcast 唤醒，并说明 Mesa/Hoare 语义；普通 WaitQueue 不自动等同。"
    if "deadlock" in low or "死锁" in stem:
        return "死锁分析必须逐条映射 Coffman 四条件和内核实际锁/资源，不应只凭存在锁就断言会死锁。"
    if "dma" in low:
        return "DMA 需要设备直接访问内存的描述符/映射/buffer 交接路径；普通 memcpy 或 PIO 不等同于 DMA。"
    if "device tree" in low or ".dtb" in low or "devicetree" in low:
        return "DeviceTree 需要解析 DTB/FDT 节点和属性；硬编码 MMIO 常量不等于解析设备树。"
    if "socket" in low or "tcp" in low or "udp" in low or "网络" in stem:
        return "网络实现需区分 socket syscall、协议栈、设备驱动和收发路径；依赖项或类型名不能单独证明端到端可用。"
    if "权限" in stem or "access control" in low or "uid" in low or "gid" in low:
        return "权限模型需要凭证/主体、对象权限元数据和 syscall/VFS 路径强制检查；字段定义不等于访问控制执行。"
    if "调度" in stem or "scheduling" in low or "scheduler" in low:
        return "调度算法需要 pick_next/queue/priority/timeslice 等决策逻辑证据；yield 或任务列表存在不等于特定算法。"
    if "tlb shootdown" in low or "ipi" in low or "核间" in stem:
        return "跨核一致性机制需要 IPI/remote call 与页表修改后的远端 TLB 刷新闭环；本地 sfence/invlpg 不等于 shootdown。"
    return "必须把概念实例、实现体、主路径调用和证据强度分开；名称命中、声明、注释、README 声称都不能单独推出实现。"


def _diagnostic_checks_for_question(stage_id: str, stem: str, keywords: List[str]) -> List[str]:
    text = (stem or "").lower()
    checks: List[str] = []

    if "page cache" in text or "页缓存" in stem or "文件页缓存" in stem:
        checks.extend(
            [
                "是否存在 page_cache / address_space / inode page mapping / file page 相关结构？",
                "是否存在 buffer cache / block cache？若存在，读取结构定义。",
                "缓存 key 是 blockno/device+block，还是 inode+page offset/file offset？",
                "是否存在 dirty page/dirty block 标记以及 page-level 或 block-level writeback 路径？",
                "是否有文件 mmap 页与页缓存共享，还是仅跟踪 mmap 文件页？",
                "缓存是否接入 read/write/page fault 主路径，而不是孤立工具结构？",
                "根据上述差异判定：完整 page cache、仅 buffer cache、mmap 文件页跟踪、stub、not_found 或 unknown。",
            ]
        )
    elif "buffer cache" in text or "block cache" in text or "块缓存" in stem:
        checks.extend(
            [
                "是否存在 buffer/block cache 数据结构和 get/read/write 接口？",
                "缓存 key 是否为 device+blockno 或等价块号？",
                "是否有脏块标记、同步/异步写回或 flush 路径？",
                "是否有驱逐策略，如 LRU/Clock/FIFO/引用计数保护？",
                "该缓存是否被真实块设备或文件系统 read/write 路径调用？",
            ]
        )
    elif "dirty" in text or "writeback" in text or "脏页" in stem or "回写" in stem:
        checks.extend(
            [
                "是否存在 dirty bit/dirty flag/脏页或脏块集合？",
                "脏标记在哪些写路径被设置？",
                "是否有 writeback/flush/sync/fsync 或后台 cleaner 路径清理脏数据？",
                "回写粒度是 page、block、inode 还是整个文件系统？",
                "若只有写 syscall 直接落盘而无脏状态管理，不应判完整 dirty page writeback。",
            ]
        )
    elif "mmap" in text:
        checks.extend(
            [
                "是否存在 sys_mmap/mmap 入口以及参数/flag 解析？",
                "是否处理匿名映射与文件映射的差异？",
                "是否处理 MAP_SHARED/MAP_PRIVATE/MAP_FIXED 等关键 flag，还是简单忽略？",
                "是否把 VMA/映射区加入进程地址空间结构？",
                "是否在 page fault 路径按映射类型分配或加载页面？",
                "若 sys_mmap 只返回固定值或未处理 flags，判 stub。",
            ]
        )
    elif "cow" in text or "copy-on-write" in text or "写时复制" in stem:
        checks.extend(
            [
                "fork/clone 时是否共享物理页并清除写权限或设置 COW 标志？",
                "page fault 写异常是否识别 COW 页？",
                "COW fault 是否分配新页、复制旧内容并更新页表？",
                "是否维护引用计数或等价共享页生命周期？",
                "若只有注释/枚举名而无 fault 处理闭环，不能判 implemented。",
            ]
        )
    elif "lazy" in text or "惰性" in stem:
        checks.extend(
            [
                "brk/mmap/alloc 路径是否只登记虚拟区间而不立即分配物理页？",
                "page fault 路径是否按需分配物理页并建立映射？",
                "是否区分合法 lazy fault 与非法访问？",
                "是否有失败回滚或错误返回路径？",
            ]
        )
    elif "syscall" in text or "系统调用" in stem:
        checks.extend(
            [
                "是否存在 syscall 分发表或 match 分发逻辑？",
                "是否存在 syscall 号边界检查和默认错误路径？",
                "目标 syscall 是否有真实实现体，而非 ENOSYS/return 0/todo？",
                "是否能从 trap/syscall handler 追踪到该实现体？",
                "README 声称与分发表实际是否一致？",
            ]
        )
    elif "抢占" in stem or "preempt" in text or "timer" in text or "时钟中断" in stem:
        checks.extend(
            [
                "是否存在 timer interrupt/tick handler 入口？",
                "时钟中断中是否调用 yield/schedule/resched 或设置 need_resched？",
                "是否区分仅 tick 计数与真正抢占调度？",
                "是否在 trap 返回或中断返回前执行调度检查？",
            ]
        )
    elif "signal" in text or "信号" in stem or "sigsegv" in text:
        checks.extend(
            [
                "是否存在 signal 数据结构、pending 集合或 handler 表？",
                "是否实现 sys_kill/sys_tkill/sys_tgkill 等发送路径？",
                "trap 返回前是否处理 pending signal？",
                "是否存在 sigreturn/trampoline 用户态返回机制？",
                "SIGSEGV 是否由非法内存访问路径触发，而不是仅有常量定义？",
            ]
        )
    elif "network" in text or "socket" in text or "tcp" in text or "udp" in text or "网络" in stem:
        checks.extend(
            [
                "是否存在 socket/sys_socket/sys_sendto/sys_recvfrom 等用户接口？",
                "是否存在协议栈结构或第三方协议栈依赖，如 smoltcp/lwip？",
                "是否支持 Ethernet/ARP/IP/ICMP/UDP/TCP 等协议中的哪些？",
                "send/recv 路径是否接入网卡驱动或 loopback，而非空返回？",
                "若只存在类型名或配置依赖，不能判完整网络实现。",
            ]
        )
    elif "启动入口" in stem or "_start" in text or "entry" in text or "linker" in text:
        checks.extend(
            [
                "链接脚本或构建配置中的 ENTRY/入口符号是什么？",
                "入口符号对应的汇编/源码定义是否可读？",
                "入口代码是否完成栈设置、BSS 清零或跳转到 Rust/C 主入口？",
                "构建系统是否按目标架构选择该入口文件？",
            ]
        )
    elif "启动链" in stem or "跳转链" in stem or "固件" in stem or "sbi" in text or "opensbi" in text or "u-boot" in text:
        checks.extend(
            [
                "固件/bootloader/链接入口到内核入口的第一个可证实节点是什么？",
                "每个跳转节点是否有 branch/call/函数调用证据？",
                "是否存在平台条件编译导致的多条互斥启动链？",
                "最终是否进入内核主初始化函数或调度/idle 入口？",
            ]
        )
    elif "特权级" in stem or "模式切换" in stem or "mstatus" in text or "sstatus" in text or "cr0" in text or "cr4" in text:
        checks.extend(
            [
                "是否写入特权级/模式控制寄存器，如 mstatus/sstatus/csr/cr0/cr4/eflags？",
                "是否存在从高特权级到低特权级或内核到用户的返回指令，如 mret/sret/iret/eret？",
                "是否设置入口 PC/返回地址、栈和中断使能位？",
                "若只是读取寄存器或定义常量，不能判真实模式切换。",
            ]
        )
    elif "mmu" in text or "satp" in text or "cr3" in text or "页表初始化" in stem or "页表切换" in stem:
        checks.extend(
            [
                "是否建立初始页表或内核地址空间映射？",
                "是否写入 SATP/CR3/TTBR 或等价 MMU 根寄存器？",
                "写入后是否执行 TLB flush/sfence/tlbi/invlpg 等同步？",
                "是否区分内核页表、用户页表或每进程地址空间切换？",
            ]
        )
    elif "fpu" in text or "sstatus.fs" in text or "cpacr" in text:
        checks.extend(
            [
                "是否写入 FPU/SIMD 使能位，如 sstatus.fs/cpacr_el1/cr4？",
                "是否存在 FPU 上下文保存/恢复结构或 lazy FPU 策略？",
                "trap/异常路径是否处理 FPU disabled 或 first-use fault？",
                "仅有常量或注释不能判 FPU 已初始化。",
            ]
        )
    elif "trapframe" in text or "trapcontext" in text or "寄存器保存" in stem:
        checks.extend(
            [
                "TrapFrame/TrapContext 结构体或汇编保存区在哪里定义？",
                "保存了哪些通用寄存器、PC/status/sp 等关键上下文？",
                "trap 入口是否实际写入该结构，返回路径是否实际恢复？",
                "结构大小/寄存器数量是否与架构 ABI 或汇编偏移一致？",
            ]
        )
    elif "trap" in text or "异常" in stem or "中断" in stem or "stvec" in text or "idt" in text:
        checks.extend(
            [
                "trap/interrupt vector 或 IDT/stvec/VBAR 的设置点在哪里？",
                "入口汇编是否保存上下文并跳转到高级语言 handler？",
                "handler 如何区分同步异常、外部中断、时钟中断和 syscall？",
                "返回路径是否恢复上下文并回到正确特权级？",
            ]
        )
    elif "物理页帧" in stem or "frame allocator" in text or "buddy" in text or "bitmap" in text or "slab" in text:
        checks.extend(
            [
                "是否存在物理页帧/连续页分配入口，如 alloc_frame/alloc_page/kalloc？",
                "核心空闲结构是 bitmap、buddy free list、slab/object cache 还是 run list？",
                "分配和释放路径是否都修改同一状态结构？",
                "是否有初始化物理内存范围、保留内核区间和并发保护？",
            ]
        )
    elif "页表" in stem or "page table" in text or "walk" in text or "map/unmap" in text:
        checks.extend(
            [
                "页表/地址空间结构体在哪里定义？",
                "是否存在 walk/map/unmap/translate 等核心 API 实现体？",
                "map/unmap 是否修改 PTE 权限位、物理页号和有效位？",
                "调用点是否接入进程创建、mmap、缺页或内核映射路径？",
            ]
        )
    elif "tlb" in text or "sfence" in text or "invlpg" in text or "tlbi" in text:
        checks.extend(
            [
                "本地 TLB flush 指令或封装函数在哪里？",
                "页表修改后是否调用该 flush 点？",
                "多核场景是否通过 IPI/remote call 触发其他核 flush？",
                "仅本地 flush 不能判 TLB shootdown。",
            ]
        )
    elif "fetch policy" in text or "placement policy" in text or "replacement policy" in text or "replacement scope" in text or "取页策略" in stem or "放置策略" in stem or "页面置换" in stem or "作用域策略" in stem:
        checks.extend(
            [
                "该题对应 Stallings Ch8 的 fetch/placement/replacement/resident set/cleaning/load control 中哪一类？",
                "源码是否存在 demand paging、prepaging、mmap_base、first-fit、LRU/Clock/FIFO 等策略证据？",
                "策略是否由实际 fault/mmap/reclaim/swap 路径调用？",
                "若无 swap/reclaim 或策略代码，只能选未实现/未发现，不应按术语猜测。",
            ]
        )
    elif "working set" in text or "resident set" in text or "thrash" in text or "驻留集" in stem or "抖动" in stem or "load control" in text:
        checks.extend(
            [
                "是否维护每进程驻留页集合、工作集大小或访问历史？",
                "是否根据缺页率/内存压力动态调整驻留集或换入换出？",
                "是否存在内存回收守护线程、OOM killer 或负载控制策略？",
                "没有 swap/reclaim 时通常不能判 implemented。",
            ]
        )
    elif "fragmentation" in text or "碎片" in stem or "relocation" in text or "重定位" in stem or "segmentation" in text or "分段" in stem:
        checks.extend(
            [
                "题面概念对应 Stallings 的哪一类：内部碎片/外部碎片/重定位/分段？",
                "源码中的分配单位、地址转换或段/页结构是否支撑该分类？",
                "是否存在配置或链接脚本决定绑定时机与地址布局？",
                "若代码没有对应机制，选择未发现/不适用而非猜测。",
            ]
        )
    elif "execution entity" in text or "pcb" in text or "tcb" in text or "执行实体" in stem or "生命周期" in stem:
        checks.extend(
            [
                "顶层执行实体结构是 Process、Task、Thread、PCB、TCB 还是合一结构？",
                "状态字段/枚举是否覆盖 Ready/Running/Blocked/Exited 等状态？",
                "创建、阻塞、唤醒、退出路径是否修改状态机？",
                "是否明确区分进程地址空间与线程执行上下文？",
            ]
        )
    elif "context switch" in text or "上下文切换" in stem or "__switch" in text or "swtch" in text:
        checks.extend(
            [
                "上下文切换汇编或函数入口在哪里？",
                "保存/恢复的寄存器集合是否与架构调用约定一致？",
                "调度器是否实际调用该 switch 入口？",
                "切换路径是否处理页表、内核栈或当前任务指针？",
            ]
        )
    elif "fork" in text or "clone" in text or "exec" in text or "wait" in text or "exit" in text or "pid" in text or "父子" in stem:
        checks.extend(
            [
                "目标进程 syscall 是否在分发表注册并有非桩实现体？",
                "实现是否修改进程表/父子关系/PID/状态等核心结构？",
                "是否处理地址空间、文件表、trap frame 或退出码等语义字段？",
                "是否存在阻塞/唤醒或资源回收闭环？",
            ]
        )
    elif "调度" in stem or "scheduler" in text or "schedule" in text or "timeslice" in text or "priority" in text:
        checks.extend(
            [
                "调度器数据结构是全局队列、每核队列、优先级队列还是其他？",
                "pick_next/schedule/yield 路径在哪里，是否真实选择下一个任务？",
                "算法证据是 timeslice、priority、stride、MLFQ 队列、CFS vruntime 还是简单 FIFO？",
                "时钟中断或阻塞唤醒是否接入调度路径？",
            ]
        )
    elif "ipi" in text or "per-cpu" in text or "percpu" in text or "secondary cpu" in text or "ap 启动" in stem or "多核" in stem or "numa" in text:
        checks.extend(
            [
                "是否存在 BSP/AP 或 hart/core 启动链与每核入口？",
                "per-CPU 数据通过 tp/gsbase/数组索引/hartid/TLS 中哪种方式实现？",
                "是否存在 IPI 发送、接收和 handler 分发路径？",
                "调度/内存/TLB 是否有跨核同步或明确单核限制？",
            ]
        )
    elif "vfs" in text or "inode" in text or "dentry" in text or "file descriptor" in text or "fd table" in text or "文件描述符" in stem:
        checks.extend(
            [
                "VFS 抽象是 Rust trait、C ops 表还是具体结构方法集？",
                "File/Inode/Dentry/SuperBlock 或等价对象在哪里定义？",
                "fd table 属于全局、进程还是线程，底层容器是什么？",
                "sys_open/read/write 是否通过 VFS 调用具体后端？",
            ]
        )
    elif "fat32" in text or "ext4" in text or "ramfs" in text or "tmpfs" in text or "文件系统后端" in stem:
        checks.extend(
            [
                "具体 FS 后端是 FAT32/Ext4/RamFS/TmpFS/其他，还是无后端？",
                "后端是自研源码、第三方 crate/库，还是构建时可选组件？",
                "构建配置是否把该后端链接到当前 profile？",
                "VFS trait/ops 是否由真实后端实现，而不是内存 mock。",
            ]
        )
    elif "file allocation" in text or "free space" in text or "directory structure" in text or "record organization" in text or "文件数据块" in stem or "空闲空间" in stem or "目录结构" in stem or "记录组织" in stem:
        checks.extend(
            [
                "该题对应 Stallings Ch12 的 file allocation/free-space/directory/file organization 哪一类？",
                "是否能从 inode、block map、bitmap、extent、FAT、directory entry 等结构读到证据？",
                "是否有分配/释放/查找路径实际维护这些结构？",
                "若后端由第三方 FS 提供，应以依赖和 wrapper 调用说明，而不是硬猜内部算法。",
            ]
        )
    elif "路径解析" in stem or "path" in text or "lookup" in text or "namei" in text or "symlink" in text:
        checks.extend(
            [
                "路径解析入口是 namei/path_walk/lookup/resolve_path 还是等价函数？",
                "是否分别处理绝对路径、相对路径、'.' 和 '..'？",
                "symlink/readlink/open follow 是否有循环/深度限制？",
                "路径解析是否连接到 sys_open 或 VFS lookup 主路径？",
            ]
        )
    elif "poll" in text or "select" in text or "epoll" in text:
        checks.extend(
            [
                "是否存在 sys_poll/sys_select/sys_epoll 或等价 syscall？",
                "实现是否检查文件对象/设备状态，而非一律 ready 或固定返回？",
                "是否有 wait queue/事件注册/唤醒机制支撑阻塞等待？",
                "是否接入 pipe/socket/设备等实际 file ops？",
            ]
        )
    elif "uart" in text or "console" in text or "virtio" in text or "plic" in text or "clint" in text or "apic" in text or "驱动" in stem:
        checks.extend(
            [
                "驱动接口/ops/trait 和注册表在哪里定义？",
                "设备发现来自 DTB/PCI/bus scan/硬编码常量中的哪一种？",
                "初始化顺序是否从平台 init/probe 接入具体驱动？",
                "中断或 DMA 路径是否把设备事件接回内核 handler？",
            ]
        )
    elif "io buffering" in text or "缓冲" in stem or "disk scheduling" in text or "i/o 控制" in stem or "dma" in text:
        checks.extend(
            [
                "I/O 控制方式是 program-controlled、interrupt-driven、DMA 还是通道/virtqueue 等价？",
                "缓冲模式是无缓冲、单缓冲、双缓冲、循环缓冲还是缓冲池？",
                "块请求是否有 FCFS/SSTF/SCAN/C-SCAN 或等价调度策略？",
                "DMA/virtqueue 描述符是否与物理地址映射和设备提交路径相连？",
            ]
        )
    elif "mutex" in text or "spinlock" in text or "rwlock" in text or "semaphore" in text or "原语" in stem or "锁" in stem:
        checks.extend(
            [
                "同步原语类型定义和内部状态字段在哪里？",
                "获取/释放路径使用关中断、原子指令、等待队列还是忙等？",
                "是否支持阻塞睡眠、公平性或读写者优先策略？",
                "锁保护的临界区和嵌套顺序是否有证据？",
            ]
        )
    elif "wait queue" in text or "sleep" in text or "wakeup" in text or "等待队列" in stem or "防丢 wakeup" in stem:
        checks.extend(
            [
                "等待队列结构和 sleep/wait 入口在哪里？",
                "入睡前是否持有队列锁或条件锁以避免 lost wakeup？",
                "wakeup/notify 是否把阻塞任务重新置为 ready？",
                "锁释放与唤醒顺序是否可由代码闭合？",
            ]
        )
    elif "pipe" in text or "管道" in stem or "sysv" in text or "message queue" in text or "shared memory" in text or "futex" in text:
        checks.extend(
            [
                "IPC syscall 或内核对象类型是否存在真实实现体？",
                "缓冲区/队列/共享区/等待队列等状态结构在哪里？",
                "读写或 wait/wake 路径是否处理阻塞、EOF、错误和资源释放？",
                "需要区分 pipe、SysV IPC、futex、message passing，不可混为一类。",
            ]
        )
    elif "producer-consumer" in text or "readers-writers" in text or "dining philosophers" in text or "生产者" in stem or "读者" in stem or "哲学家" in stem:
        checks.extend(
            [
                "是否存在经典同步问题对应的实现、测试或示例代码？",
                "生产者-消费者是否有 bounded buffer、空/满条件和互斥保护？",
                "读者-写者是否有读者优先、写者优先或公平策略证据？",
                "哲学家就餐若存在，是否展示死锁避免/资源排序策略？",
            ]
        )
    elif "访问控制" in stem or "权限" in stem or "uid" in text or "gid" in text or "credential" in text or "capability" in text:
        checks.extend(
            [
                "主体凭证结构是否含 UID/GID/capability/ACL 或等价字段？",
                "对象元数据是否含 owner/mode/ACL/security label？",
                "open/exec/write/chmod 等 syscall/VFS 路径是否调用权限检查？",
                "检查失败是否返回权限错误，而不是仅记录字段。",
            ]
        )
    elif "sandbox" in text or "seccomp" in text or "stack canary" in text or "guard page" in text or "kpti" in text or "完整性" in stem:
        checks.extend(
            [
                "安全机制对应的策略对象或配置入口在哪里？",
                "机制是否在 syscall/trap/mm/loader 路径被强制执行？",
                "是否有失败路径、拒绝路径或异常路径证据？",
                "仅编译选项、字段或文档声明不能判 implemented。",
            ]
        )
    elif "kernel monitor" in text or "内核驻留" in stem or "监视器" in stem:
        checks.extend(
            [
                "是否存在内核态可达的交互命令循环或调试 console？",
                "命令解析/分发表是否在内核源码中，而不是用户态 shell？",
                "能否列出 3-10 个用户可键入命令及其内核 handler？",
                "monitor 是否能读取/操作内核状态，如任务、内存、寄存器或设备？",
                "若只存在 user/ 下 shell 或测试程序，应判未切题而非 implemented。",
            ]
        )
    elif "log" in text or "printk" in text or "panic" in text or "backtrace" in text or "gdb" in text or "trace" in text or "错误码" in stem:
        checks.extend(
            [
                "日志/panic/error/trace 的核心宏、类型或 handler 在哪里定义？",
                "panic 或错误路径是否输出寄存器、栈、backtrace 或停机动作？",
                "GDB stub/tracepoint 是否有协议解析或关键路径插桩，而非仅有名字？",
                "错误类型是否从底层调用传播到 syscall 或上层接口？",
            ]
        )

    if not checks:
        checks.extend(
            [
                "先搜索并列出本题关键词对应的结构、函数、配置或目录入口。",
                "读取最相关定义/实现体，判断是否存在真实逻辑、桩逻辑或仅声明。",
                "查找至少一个调用点、使用点或主路径连接，避免孤立符号误判。",
                "若未找到，按 negative_search_policy 覆盖关键词和目录后再判 not_found；覆盖不足判 unknown。",
            ]
        )
    return checks[:10]


def _anti_examples_for_question(stem: str, diagnostic_checks: List[str]) -> List[str]:
    out = list(DEFAULT_ANTI_EXAMPLES)
    low = (stem or "").lower()
    if "page cache" in low or "页缓存" in stem:
        out.extend(
            [
                "只发现 block/buffer cache，且 key 是 blockno，不等价于完整 Page Cache。",
                "只发现 mmap 文件页记录，但没有 inode+page offset 共享缓存和 writeback，不能判完整 Page Cache。",
                "只发现 dirty 常量或注释，没有写路径设置与回写路径，不能判 dirty page writeback implemented。",
            ]
        )
    if "mmap" in low:
        out.append("sys_mmap 仅 return 0/固定地址、未处理 flags 或未接入 fault 路径，应判 stub。")
    if "syscall" in low or "系统调用" in stem:
        out.append("分发表注册了 syscall 名字但实现体 ENOSYS/unsupported/return 0，应判 stub 而非 implemented。")
    if "signal" in low or "信号" in stem:
        out.append("只发现 SIGSEGV 常量或 kill 函数名，没有 pending/dispatch/sigreturn 链路，不能判完整 signal implemented。")
    return _dedupe(out)[:8]


def _is_architecture_matrix_question(question: Dict[str, Any]) -> bool:
    stem = str(question.get("stem") or "").lower()
    return (
        ("支持哪些架构" in str(question.get("stem") or "") or "which architectures" in stem)
        and ("riscv64" in stem or "aarch64" in stem or "x86_64" in stem or "loongarch64" in stem)
    )


def _answer_contract_for_question(question: Dict[str, Any], structured_facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    qtype = str(question.get("question_type") or "").strip()
    choices = [str(x) for x in question.get("choices", [])] if isinstance(question.get("choices"), list) else []
    if _is_architecture_matrix_question(question):
        final_type = "architecture_matrix"
        allowed = []
    elif qtype == "tri_state_impl":
        final_type = "enum"
        allowed = ["implemented", "stub", "not_found", "unknown"]
    elif qtype == "single_choice":
        final_type = "enum"
        allowed = choices
    elif qtype == "multi_choice":
        final_type = "enum_array"
        allowed = choices
    elif qtype == "fill_in":
        final_type = "object"
        allowed = []
    else:
        final_type = "fact_table"
        allowed = []
    contract = {
        "mode": "structured_facts_first",
        "final_field": "value",
        "final_type": final_type,
        "allowed_final_values": allowed,
        "required_fact_ids": [str(f.get("fact_id")) for f in structured_facts],
        "evidence_reference": "evidence_id_only",
        "free_text_policy": "notes 只能解释 structured_facts 与最终值的关系，不能引入未被 evidence_id 支撑的新事实。",
        "reproducibility_rule": (
            "回答时先逐项给出 structured_facts 的 status/value 与 evidence_id，再由这些事实机械推出最终 value；"
            "缺少强证据时 final value 必须降级为 unknown/待核实。"
        ),
    }
    if _is_architecture_matrix_question(question):
        contract["value_shape"] = {
            "riscv64": {
                "support": "yes_strong|yes_weak|no_after_negative_search|unknown",
                "security_init": "yes_strong|yes_weak|stub_or_declaration_only|no_after_negative_search|unknown",
                "notes": "证据摘要",
            },
            "aarch64": "同上；无证据写 no_after_negative_search 或 unknown",
            "x86_64": "同上；无证据写 no_after_negative_search 或 unknown",
            "loongarch64": "同上；无证据写 no_after_negative_search 或 unknown",
            "negative_search_coverage": {
                "searched_keywords": "array<string>",
                "searched_directories": "array<string>",
                "file_count": "integer",
                "match_count": "integer",
                "coverage_sufficient": "boolean",
            },
        }
        contract["reproducibility_rule"] = (
            "逐架构回答支持状态和安全初始化证据；value 必须只包含 riscv64/aarch64/x86_64/"
            "loongarch64/negative_search_coverage 这些字段。未发现架构支持或安全初始化时，必须用结构化负向搜索支撑。"
        )
    return contract


def _architecture_matrix_facts_for_question(
    qid: str,
    *,
    keywords: List[str],
    seed_paths: List[str],
    required_evidence_types: List[str],
) -> List[Dict[str, Any]]:
    arch_specs = [
        ("riscv64", "RISC-V/riscv64 架构支持与安全相关初始化证据。"),
        ("aarch64", "AArch64 架构支持与安全相关初始化证据；无证据写未发现。"),
        ("x86_64", "x86_64 架构支持与 SMEP/SMAP/KPTI 等安全初始化证据；无证据写未发现。"),
        ("loongarch64", "LoongArch64 架构支持与安全相关初始化证据；无证据写未发现。"),
    ]
    facts: List[Dict[str, Any]] = []
    arch_keywords = _dedupe(keywords + ["riscv64", "aarch64", "x86_64", "loongarch64", "PMP", "MPU", "SMEP", "SMAP", "KPTI"])
    for idx, (arch, question) in enumerate(arch_specs, 1):
        facts.append(
            {
                "fact_id": f"{qid}_ARCH_{idx:02d}",
                "fact_key": arch,
                "kind": "architecture_support",
                "question": question,
                "answer_type": "object",
                "fields": {
                    "support": "yes_strong|yes_weak|no_after_negative_search|unknown",
                    "security_init": "yes_strong|yes_weak|stub_or_declaration_only|no_after_negative_search|unknown",
                    "notes": "string",
                },
                "evidence_required": required_evidence_types,
                "probe": {
                    "keywords": _dedupe([arch] + arch_keywords)[:24],
                    "seed_paths": seed_paths[:12],
                    "hint_tools": ["rag_search_code", "grep_in_repo"],
                    "strong_tools": ["read_code_segment", "lsp_get_definition", "lsp_get_references", "lsp_get_call_graph"],
                },
                "conclusion_role": "required_for_answer",
            }
        )
    facts.append(
        {
            "fact_id": f"{qid}_NEG",
            "fact_key": "negative_search_coverage",
            "kind": "negative_search",
            "question": "记录逐架构负向搜索覆盖；覆盖不足时对应架构只能 unknown，不能判未发现。",
            "answer_type": "object",
            "fields": {
                "searched_keywords": "array<string>",
                "searched_directories": "array<string>",
                "file_count": "integer",
                "match_count": "integer",
                "coverage_sufficient": "boolean",
            },
            "evidence_required": ["negative_search"],
            "probe": {
                "keywords": arch_keywords[:24],
                "seed_paths": seed_paths[:12],
                "hint_tools": ["grep_in_repo", "rag_search_code"],
                "strong_tools": [],
            },
            "conclusion_role": "required_for_not_found",
        }
    )
    return facts


def _structured_facts_for_question(
    stage_id: str,
    question: Dict[str, Any],
    *,
    keywords: List[str],
    seed_paths: List[str],
    diagnostic_checks: List[str],
    required_evidence_types: List[str],
) -> List[Dict[str, Any]]:
    qid = str(question.get("question_id") or "").strip() or "QXX_000"
    qtype = str(question.get("question_type") or "").strip()
    stem = str(question.get("stem") or "").strip()
    facts: List[Dict[str, Any]] = []
    used_fact_keys: Set[str] = set()

    if _is_architecture_matrix_question(question):
        return _architecture_matrix_facts_for_question(
            qid,
            keywords=keywords,
            seed_paths=seed_paths,
            required_evidence_types=required_evidence_types,
        )

    for idx, check in enumerate(diagnostic_checks[:10], 1):
        fact_key = _unique_fact_key(_fact_key_from_text(check, stem, idx), used_fact_keys, idx)
        facts.append(
            {
                "fact_id": f"{qid}_F{idx:02d}",
                "fact_key": fact_key,
                "kind": _fact_kind_from_text(check),
                "question": check,
                "answer_type": "enum",
                "allowed_values": FACT_STATUS_VALUES,
                "evidence_required": _evidence_required_for_fact(check, required_evidence_types),
                "probe": {
                    "keywords": _fact_keywords(check, keywords),
                    "seed_paths": seed_paths[:12],
                    "hint_tools": ["rag_search_code", "grep_in_repo"],
                    "strong_tools": ["read_code_segment", "lsp_get_definition", "lsp_get_references", "lsp_get_call_graph"],
                },
                "status_meaning": {
                    "yes_strong": "读到定义/实现体/调用点/状态变化等强证据。",
                    "yes_weak": "只有搜索/outline/README 等线索，不能单独支撑 implemented。",
                    "stub_or_declaration_only": "只有声明、空实现、固定返回、ENOSYS/unsupported、todo/unimplemented。",
                    "no_after_negative_search": "按本题 negative_search_policy 覆盖关键词和目录后仍未发现。",
                    "unknown": "证据冲突或覆盖不足。",
                },
                "conclusion_role": _conclusion_role_for_fact(check, qtype),
            }
        )

    if qtype in {"single_choice", "multi_choice"}:
        choices = [str(x) for x in question.get("choices", [])] if isinstance(question.get("choices"), list) else []
        facts.append(
            {
                "fact_id": f"{qid}_CHOICE",
                "fact_key": "choice_support_matrix",
                "kind": "classification",
                "question": "逐项判断 choices 中哪些选项被源码/配置证据支持，哪些被反证，最后只选择被最强证据支持的选项。",
                "answer_type": "object",
                "fields": {
                    "supported_choices": "array<string>",
                    "rejected_choices": "array<string>",
                    "selected_choice": "string",
                    "tie_break_reason": "string",
                },
                "allowed_choices": choices,
                "evidence_required": _dedupe(required_evidence_types + ["definition", "search"])[:8],
                "probe": {
                    "keywords": _fact_keywords(stem, keywords),
                    "seed_paths": seed_paths[:12],
                    "hint_tools": ["rag_search_code", "grep_in_repo"],
                    "strong_tools": ["read_code_segment", "lsp_get_definition", "parse_build_config"],
                },
                "conclusion_role": "drives_final_choice",
            }
        )

    if qtype in {"short_answer", "fill_in"}:
        facts.append(
            {
                "fact_id": f"{qid}_SHAPE",
                "fact_key": "required_answer_fields",
                "kind": "answer_shape",
                "question": "按题面要求抽取固定字段；每个字段必须绑定 evidence_id，不能只写自然语言总结。",
                "answer_type": "object",
                "fields": _required_fields_from_stem(stem, qtype),
                "evidence_required": _dedupe(required_evidence_types + ["definition", "implementation_body", "search"])[:8],
                "probe": {
                    "keywords": _fact_keywords(stem, keywords),
                    "seed_paths": seed_paths[:12],
                    "hint_tools": ["rag_search_code", "grep_in_repo"],
                    "strong_tools": ["read_code_segment", "lsp_get_definition", "lsp_get_call_graph", "parse_build_config"],
                },
                "conclusion_role": "answer_fields",
            }
        )

    facts.append(
        {
            "fact_id": f"{qid}_NEG",
            "fact_key": "negative_search_coverage",
            "kind": "negative_search",
            "question": "若关键事实未找到，记录已覆盖的关键词、目录、文件数和 match_count；覆盖不足时最终只能 unknown/待核实。",
            "answer_type": "object",
            "fields": {
                "searched_keywords": "array<string>",
                "searched_directories": "array<string>",
                "file_count": "integer",
                "match_count": "integer",
                "coverage_sufficient": "boolean",
            },
            "evidence_required": ["negative_search"],
            "probe": {
                "keywords": keywords[:16],
                "seed_paths": seed_paths[:16],
                "hint_tools": ["grep_in_repo", "rag_search_code"],
                "strong_tools": [],
            },
            "conclusion_role": "required_for_not_found",
        }
    )
    return facts[:14]


def _unique_fact_key(base_key: str, used_fact_keys: Set[str], idx: int) -> str:
    key = str(base_key or "").strip() or f"fact_{idx:02d}"
    if key not in used_fact_keys:
        used_fact_keys.add(key)
        return key
    suffix = 2
    while f"{key}_{suffix:02d}" in used_fact_keys:
        suffix += 1
    unique = f"{key}_{suffix:02d}"
    used_fact_keys.add(unique)
    return unique


def _repair_structured_facts_for_question(question: Dict[str, Any], existing: Any, generated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(existing, list):
        return generated
    qtype = str(question.get("question_type") or "").strip()
    facts = [deepcopy(f) for f in existing if isinstance(f, dict)]
    if _should_replace_stale_template(question, facts):
        return generated
    if _is_architecture_matrix_question(question):
        expected = {"riscv64", "aarch64", "x86_64", "loongarch64", "negative_search_coverage"}
        current = {str(f.get("fact_key") or "").strip() for f in facts}
        if not expected.issubset(current):
            return generated

    current_keys = {str(f.get("fact_key") or "").strip() for f in facts}
    generated_by_key = {str(f.get("fact_key") or "").strip(): f for f in generated if isinstance(f, dict)}
    required_keys: List[str] = []
    if qtype in {"single_choice", "multi_choice"}:
        required_keys.append("choice_support_matrix")
    if qtype in {"short_answer", "fill_in"}:
        required_keys.append("required_answer_fields")
    required_keys.append("negative_search_coverage")

    for key in required_keys:
        if key not in current_keys and key in generated_by_key:
            facts.append(deepcopy(generated_by_key[key]))
            current_keys.add(key)
    return _dedupe_fact_keys(facts)


def _dedupe_fact_keys(facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    used: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for idx, fact in enumerate(facts, 1):
        item = deepcopy(fact)
        item["fact_key"] = _unique_fact_key(str(item.get("fact_key") or "").strip(), used, idx)
        out.append(item)
    return out


def _repair_answer_contract_for_question(
    question: Dict[str, Any],
    existing: Any,
    generated: Dict[str, Any],
    structured_facts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    contract = deepcopy(existing) if isinstance(existing, dict) else deepcopy(generated)
    generated_contract = _answer_contract_for_question(question, structured_facts)
    qtype = str(question.get("question_type") or "").strip()
    if _is_architecture_matrix_question(question) or qtype in {"single_choice", "multi_choice", "tri_state_impl"}:
        contract["final_type"] = generated_contract.get("final_type")
        contract["allowed_final_values"] = generated_contract.get("allowed_final_values", [])
    contract["required_fact_ids"] = [str(f.get("fact_id")) for f in structured_facts if f.get("fact_id")]
    contract.setdefault("mode", generated_contract.get("mode", "structured_facts_first"))
    contract.setdefault("final_field", generated_contract.get("final_field", "value"))
    contract.setdefault("evidence_reference", generated_contract.get("evidence_reference", "evidence_id_only"))
    contract.setdefault("free_text_policy", generated_contract.get("free_text_policy"))
    contract.setdefault("reproducibility_rule", generated_contract.get("reproducibility_rule"))
    if "value_shape" in generated_contract:
        contract["value_shape"] = generated_contract["value_shape"]
    return contract


def _should_replace_stale_template(question: Dict[str, Any], facts: Any) -> bool:
    return _should_replace_stale_boot_template(question, facts) or _should_replace_stale_memory_template(question, facts)


def _should_replace_stale_boot_template(question: Dict[str, Any], facts: Any) -> bool:
    if not isinstance(facts, list):
        return False
    stem = str(question.get("stem") or "")
    low = stem.lower()
    is_boot_entry_question = (
        "启动入口" in stem
        or "启动链" in stem
        or "跳转链" in stem
        or "_start" in low
        or "entry" in low
        or "bootloader" in low
        or "固件" in stem
    )
    if is_boot_entry_question:
        return False
    keys = {str(f.get("fact_key") or "").strip() for f in facts if isinstance(f, dict)}
    stale_boot_keys = {"linker_entry", "entry_assembly", "main_handoff", "platform_selection"}
    return len(keys & stale_boot_keys) >= 3


def _should_replace_stale_memory_template(question: Dict[str, Any], facts: Any) -> bool:
    if not isinstance(facts, list):
        return False
    stem = str(question.get("stem") or "")
    low = stem.lower()
    is_mmu_init_question = "mmu" in low or "satp" in low or "cr3" in low or "ttbr" in low or "页表初始化" in stem
    if not is_mmu_init_question:
        return False
    keys = {str(f.get("fact_key") or "").strip() for f in facts if isinstance(f, dict)}
    stale_memory_keys = {"memory_constants", "allocator_state", "map_unmap_api", "protection_relocation"}
    return len(keys & stale_memory_keys) >= 3


def _fact_key_from_text(text: str, stem: str, idx: int) -> str:
    fact_low = (text or "").lower()
    combined = f"{text} {stem}".lower()
    patterns = [
        ("buffer_cache", ("buffer cache" in combined or "block cache" in combined or "块缓存" in stem)),
        ("cache_key_granularity", ("key" in combined or "blockno" in combined or "offset" in combined)),
        ("dirty_writeback", ("dirty" in combined or "writeback" in combined or "脏" in stem or "回写" in stem)),
        ("mmap_fault_path", ("mmap" in combined or "vma" in combined)),
        ("page_fault_flow", ("page fault" in combined or "缺页" in stem)),
        ("page_cache", ("page_cache" in combined or "页缓存" in stem or "address_space" in combined)),
        ("cow_lifecycle", ("cow" in combined or "copy-on-write" in combined or "写时复制" in stem)),
        ("lazy_allocation_fault", ("lazy" in combined or "惰性" in stem)),
        ("initial_page_table", ("初始页表" in text or "内核地址空间映射" in text)),
        ("satp_cr3_ttbr_mmu", ("satp" in fact_low or "cr3" in fact_low or "ttbr" in fact_low or "mmu 根寄存器" in text)),
        ("tlb_flush_sfence_tlbi_invlpg", ("tlb" in fact_low or "sfence" in fact_low or "tlbi" in fact_low or "invlpg" in fact_low)),
        ("address_space_switching", ("用户页表" in text or "内核页表" in text or "每进程地址空间" in text)),
        ("virtual_memory_policy", ("fetch policy" in combined or "placement policy" in combined or "replacement policy" in combined or "replacement scope" in combined or "取页策略" in stem or "放置策略" in stem or "页面置换" in stem or "作用域策略" in stem)),
        ("mode_control_registers", ("mstatus" in fact_low or "sstatus" in fact_low or "cr0" in fact_low or "cr4" in fact_low or "eflags" in fact_low or "控制寄存器" in text)),
        ("privilege_return_instruction", ("mret" in fact_low or "sret" in fact_low or "iret" in fact_low or "eret" in fact_low or "返回指令" in text)),
        ("entry_pc_stack_interrupt_bits", ("入口 pc" in fact_low or "返回地址" in text or "中断使能" in text)),
        ("stub_guardrail", ("不能判" in text or "只是" in text)),
        ("syscall_dispatch", ("syscall" in combined or "系统调用" in stem)),
        ("trap_interrupt_vector", ("trap" in combined or "stvec" in combined or "idt" in combined or "中断向量" in stem)),
        ("timer_preemption", ("timer" in combined or "时钟" in stem or "抢占" in stem)),
        ("signal_delivery", ("signal" in combined or "sigsegv" in combined or "信号" in stem)),
        ("context_switch", ("context switch" in combined or "上下文切换" in stem)),
        ("scheduler_policy", ("sched" in combined or "调度" in stem)),
        ("process_lifecycle", ("process" in combined or "fork" in combined or "exec" in combined or "wait" in combined)),
        ("per_cpu_smp", ("per-cpu" in combined or "percpu" in combined or "多核" in stem or "ipi" in combined)),
        ("vfs_interface", ("vfs" in combined or "inode" in combined or "dentry" in combined)),
        ("file_layout_policy", ("file allocation" in combined or "free space" in combined or "directory structure" in combined or "record organization" in combined or "文件数据块" in stem or "空闲空间" in stem or "目录结构" in stem or "记录组织" in stem)),
        ("call_flow", ("调用链" in stem or "跳转链" in stem or "调用点" in combined or "主路径" in combined or "flow" in combined)),
        ("path_resolution", ("namei" in combined or "path_walk" in combined or "lookup" in combined or "resolve_path" in combined or "symlink" in combined or "路径解析" in stem)),
        ("device_discovery", ("dtb" in combined or "devicetree" in combined or "device tree" in combined)),
        ("driver_probe", ("driver" in combined or "驱动" in stem or "probe" in combined)),
        ("dma_path", ("dma" in combined or "virtio" in combined)),
        ("wait_queue_sleep_wakeup", ("wait queue" in combined or "sleep" in combined or "wakeup" in combined or "等待队列" in stem)),
        ("lock_semantics", ("lock" in combined or "mutex" in combined or "spinlock" in combined or "锁" in stem)),
        ("deadlock_condition", ("deadlock" in combined or "死锁" in stem or "coffman" in combined)),
        ("classic_sync_problem", ("producer-consumer" in combined or "readers-writers" in combined or "dining philosophers" in combined or "生产者" in stem or "读者" in stem or "哲学家" in stem)),
        ("kernel_monitor", ("kernel monitor" in combined or "内核驻留" in stem)),
        ("monitor_condvar", ("monitor" in combined or "condvar" in combined or "condition" in combined or "管程" in stem)),
        ("credential_permission", ("uid" in combined or "gid" in combined or "permission" in combined or "权限" in stem)),
        ("user_pointer_safety", ("copyin" in combined or "copyout" in combined or "access_ok" in combined or "用户指针" in stem)),
        ("network_stack", ("socket" in combined or "tcp" in combined or "udp" in combined or "网络" in stem)),
        ("logging_panic_trace", ("panic" in combined or "log" in combined or "trace" in combined or "backtrace" in combined)),
    ]
    for key, matched in patterns:
        if matched:
            return key
    slug = _slug(text, 32)
    return slug if slug != "feature" else f"local_fact_{idx:02d}"


def _fact_kind_from_text(text: str) -> str:
    low = (text or "").lower()
    if "调用" in text or "路径" in text or "flow" in low or "接入" in text:
        return "flow"
    if "结构" in text or "定义" in text or "字段" in text or "trait" in low:
        return "definition"
    if "key" in low or "哪种" in text or "区分" in text:
        return "classification"
    if "是否" in text or "实现" in text or "存在" in text:
        return "presence"
    return "fact"


def _evidence_required_for_fact(text: str, required: List[str]) -> List[str]:
    low = (text or "").lower()
    out = list(required)
    if "调用" in text or "路径" in text or "flow" in low or "接入" in text:
        out.extend(["call_site", "usage_flow", "call_graph"])
    if "结构" in text or "定义" in text or "字段" in text:
        out.extend(["definition", "read_code_segment"])
    if "实现" in text or "处理" in text or "设置" in text:
        out.extend(["implementation_body", "function_body"])
    if "未找到" in text or "not_found" in low:
        out.append("negative_search")
    return _dedupe(out)[:8]


def _fact_keywords(text: str, base_keywords: List[str]) -> List[str]:
    return _dedupe(_keywords_from_text(text, 12) + base_keywords)[:12]


def _conclusion_role_for_fact(text: str, qtype: str) -> str:
    if qtype == "tri_state_impl":
        if "是否" in text or "实现" in text or "存在" in text:
            return "required_for_implemented_or_stub"
        return "disambiguates_tri_state"
    if qtype in {"single_choice", "multi_choice"}:
        return "supports_choice_classification"
    return "required_answer_component"


def _required_fields_from_stem(stem: str, qtype: str) -> Dict[str, str]:
    fields: Dict[str, str] = {
        "fact_summary": "string",
        "primary_symbols": "array<{symbol,path,line}>",
        "evidence_ids": "array<string>",
    }
    bullet_fields = re.findall(r"-\s*([^:：\n]+)\s*[:：]", stem or "")
    if bullet_fields:
        fields["required_items"] = "object with keys: " + ", ".join(_dedupe(bullet_fields)[:12])
    if "3-6" in stem or "3-5" in stem or "调用链" in stem or "跳转链" in stem or "路径" in stem:
        fields["flow_nodes"] = "array<{name,path,line,role}>"
        fields["flow_edges"] = "array<{from,to,reason}>"
    if "结构体" in stem or "字段" in stem or "类型" in stem:
        fields["definitions"] = "array<{type_or_struct,path,line,fields}>"
    if "统计" in stem or "个" in stem:
        fields["counts"] = "object"
    if qtype == "fill_in":
        fields["filled_slots"] = "object"
    return fields


def _bank_path() -> str:
    return os.path.join(os.path.dirname(__file__), "stage_defaults.json")


def load_schema_bank() -> Dict[str, Any]:
    with open(_bank_path(), "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {"stages": {}}


def _stage_default(stage_id: str) -> Dict[str, Any]:
    bank = load_schema_bank()
    stages = bank.get("stages", {}) if isinstance(bank.get("stages"), dict) else {}
    return dict(stages.get(stage_id, {})) if isinstance(stages.get(stage_id), dict) else {}


def _slug(text: str, limit: int = 48) -> str:
    raw = (text or "").strip().lower()
    raw = re.sub(r"[^a-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return (raw or "feature")[:limit]


def _keywords_from_text(text: str, limit: int = 16) -> List[str]:
    out: List[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_\-]{2,}", text or ""):
        if token.lower() not in {"the", "and", "with", "must", "impl", "state", "json"}:
            out.append(token)
    zh_markers = [
        "启动", "入口", "页表", "物理页", "调度", "上下文切换", "系统调用", "中断", "异常",
        "文件系统", "网络", "权限", "信号", "锁", "Futex", "缺页", "串口", "设备",
    ]
    for marker in zh_markers:
        if marker in (text or ""):
            out.append(marker)
    return _dedupe(out)[:limit]


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def feature_id_for_question(stage_id: str, question_id: str) -> str:
    return f"feat_{stage_id}_{_slug(question_id, 24)}"


def synthesize_feature(stage_id: str, question: Dict[str, Any]) -> Dict[str, Any]:
    qid = str(question.get("question_id") or "").strip()
    qtype = str(question.get("question_type") or "").strip()
    stem = str(question.get("stem") or "").strip()
    defaults = _stage_default(stage_id)
    hints = question.get("task_hints") if isinstance(question.get("task_hints"), dict) else {}
    policy = question.get("evidence_policy") if isinstance(question.get("evidence_policy"), dict) else {}

    feature_id = feature_id_for_question(stage_id, qid)
    keywords = _dedupe(
        list(defaults.get("keywords") or [])
        + list(hints.get("keywords") or [])
        + _keywords_from_text(stem)
    )[:24]
    seed_paths = _dedupe(list(hints.get("seed_paths") or []) + list(defaults.get("seed_paths") or []))[:24]
    diagnostic_checks = _diagnostic_checks_for_question(stage_id, stem, keywords)
    textbook_basis = _textbook_basis_for_question(stage_id, stem)
    concept_boundary = _concept_boundary_for_question(stem)

    required = _dedupe(list(policy.get("required_evidence_types") or []))
    if not required:
        if qtype == "tri_state_impl":
            required = ["implementation_body", "definition", "negative_search"]
        elif qtype in {"single_choice", "multi_choice"}:
            required = ["definition", "search"]
        else:
            required = ["definition", "implementation_body", "search"]

    tri_state_rule = _question_specific_tri_state_rule(stem, keywords, diagnostic_checks) if qtype == "tri_state_impl" else {}
    anti_examples = _anti_examples_for_question(stem, diagnostic_checks) if qtype == "tri_state_impl" else []
    structured_facts = _structured_facts_for_question(
        stage_id,
        question,
        keywords=keywords,
        seed_paths=seed_paths,
        diagnostic_checks=diagnostic_checks,
        required_evidence_types=required,
    )
    answer_contract = _answer_contract_for_question(question, structured_facts)

    return {
        "feature_id": feature_id,
        "stage_id": stage_id,
        "domain": str(defaults.get("domain") or stage_id),
        "feature_name": f"{qid} {stem[:80]}".strip(),
        "description": stem,
        "textbook_basis": textbook_basis,
        "concept_boundary": concept_boundary,
        "dependencies": list(defaults.get("dependencies") or []),
        "question_ids": [qid] if qid else [],
        "tri_state_rule": tri_state_rule,
        "required_evidence_types": required,
        "negative_search_policy": {
            "keywords": keywords[:16],
            "seed_paths": seed_paths[:16],
            "minimum_keyword_coverage": 0.6,
            "minimum_directory_coverage": 0.5,
        },
        "anti_examples": anti_examples,
        "diagnostic_checks": diagnostic_checks,
        "structured_facts": structured_facts,
        "answer_contract": answer_contract,
        "graph_tags": _dedupe(list(defaults.get("graph_tags") or []) + [qtype])[:12],
        "seed_paths": seed_paths,
        "keywords": keywords,
    }


def enrich_stage_qa(stage_qa: Dict[str, Any]) -> Dict[str, Any]:
    """Return the authored question sheet unchanged.

    The question JSON is the source of truth. Runtime code may read explicit
    per-question fields such as structured_facts and answer_contract, but must
    not synthesize or repair them from generic rules.
    """
    return deepcopy(stage_qa) if isinstance(stage_qa, dict) else stage_qa


def features_for_stage_qa(stage_qa: Dict[str, Any]) -> List[Dict[str, Any]]:
    features = stage_qa.get("features", []) if isinstance(stage_qa, dict) else []
    return [f for f in features if isinstance(f, dict)]


def feature_by_question(stage_qa: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for feature in features_for_stage_qa(stage_qa):
        for qid in feature.get("question_ids", []) if isinstance(feature.get("question_ids"), list) else []:
            out.setdefault(str(qid), []).append(feature)
    return out


def collect_feature_ids(question: Dict[str, Any]) -> List[str]:
    value = question.get("feature_ids")
    if isinstance(value, list):
        return _dedupe(str(x) for x in value)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def feature_context_for_question(question: Dict[str, Any]) -> Dict[str, Any]:
    stage_id = str(question.get("stage_id") or "").strip()
    if not stage_id:
        # Most loaded questions do not carry stage_id; infer from Qxx prefix.
        qid = str(question.get("question_id") or "")
        if qid.startswith("Q") and len(qid) >= 3:
            stage_id = f"{qid[1:3]}_"  # only used as fallback marker
    qid = str(question.get("question_id") or "").strip()
    if not qid:
        return {}
    feature_ids = collect_feature_ids(question)
    return {
        "feature_ids": feature_ids,
        "tri_state_rule": question.get("tri_state_rule") if isinstance(question.get("tri_state_rule"), dict) else {},
        "evidence_policy": question.get("evidence_policy") if isinstance(question.get("evidence_policy"), dict) else {},
        "anti_examples": question.get("anti_examples") if isinstance(question.get("anti_examples"), list) else [],
        "diagnostic_checks": question.get("diagnostic_checks") if isinstance(question.get("diagnostic_checks"), list) else [],
        "structured_facts": question.get("structured_facts") if isinstance(question.get("structured_facts"), list) else [],
        "answer_contract": question.get("answer_contract") if isinstance(question.get("answer_contract"), dict) else {},
        "textbook_basis": question.get("textbook_basis") if isinstance(question.get("textbook_basis"), list) else [],
        "concept_boundary": str(question.get("concept_boundary") or ""),
    }


def required_evidence_types_for_question(question: Dict[str, Any]) -> List[str]:
    policy = question.get("evidence_policy") if isinstance(question.get("evidence_policy"), dict) else {}
    required = policy.get("required_evidence_types") if isinstance(policy.get("required_evidence_types"), list) else []
    return _dedupe(str(x) for x in required)


def negative_search_policy_for_question(question: Dict[str, Any]) -> Dict[str, Any]:
    policy = question.get("evidence_policy") if isinstance(question.get("evidence_policy"), dict) else {}
    neg = policy.get("negative_search_policy") if isinstance(policy.get("negative_search_policy"), dict) else {}
    return dict(neg)


def normalize_tri_state_answer_value(value: Any) -> str:
    if isinstance(value, str) and value.strip() in TRI_STATE_VALUES:
        return value.strip()
    return "unknown"


def evidence_can_support_claim(evidence: Sequence[Any], claim_type: str) -> bool:
    claim_type = (claim_type or "").strip()
    for rec in evidence:
        supports = getattr(rec, "supports_claim_types", None) or []
        if claim_type in supports:
            return True
    return False


def strongest_evidence_strength(evidence: Sequence[Any]) -> str:
    rank = {"invalid": 0, "hint": 1, "weak": 2, "strong": 3}
    best = "invalid"
    for rec in evidence:
        strength = str(getattr(rec, "strength", "") or "weak")
        if rank.get(strength, 0) > rank.get(best, 0):
            best = strength
    return best


def tri_state_value_allowed_by_evidence(value: str, evidence: Sequence[Any]) -> bool:
    value = normalize_tri_state_answer_value(value)
    if value == "unknown":
        return True
    return evidence_can_support_claim(evidence, value)
