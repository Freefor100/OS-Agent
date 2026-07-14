from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import ValidationReport


VALID_ARCHITECTURE_ROLES = {"build", "runtime", "support"}
VALID_POINT_STATUS = {"implemented", "partial", "minimal", "absent", "unclear"}
VALID_DELTA_CLASS = {
    "inherited",
    "config_enabled",
    "glue_adaptation",
    "adapted_minor",
    "adapted_major",
    "novel",
    "external",
    "none",
    "unclear",
}
VALID_EFFORT_LEVEL = {"none", "low", "medium", "high", "uncertain"}


@dataclass(frozen=True)
class TaxonomyNode:
    node_id: str
    title: str
    scope: str
    description_requirements: tuple[str, ...]

    def as_dict(self, evidence_ids: Iterable[str] = ()) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "scope": self.scope,
            "description_requirements": list(self.description_requirements),
            "evidence_ids": list(evidence_ids),
        }


@dataclass(frozen=True)
class TaxonomyModule:
    module_id: str
    title: str
    architecture_role: str
    nodes: tuple[TaxonomyNode, ...]


def N(node_id: str, title: str, scope: str, *requirements: str) -> TaxonomyNode:
    return TaxonomyNode(node_id, title, scope, tuple(requirements))


MODULES: dict[str, TaxonomyModule] = {
    "build-config": TaxonomyModule(
        "build-config",
        "构建与配置",
        "build",
        (
            N("build-system", "构建系统", "从标准入口生成可运行内核和必要镜像的构建组织。", "构建入口、产物、失败位置", "增量/全量构建与宿主依赖"),
            N("toolchain", "工具链", "编译、链接、二进制处理和目标架构工具链。", "版本与获取方式", "离线和可复现边界"),
            N("linker-layout", "链接与映像布局", "链接脚本、入口地址、段布局和装载约定。", "各段权限与地址", "启动代码如何使用布局"),
            N("kernel-configuration", "内核配置", "Kconfig、Make 变量、Cargo feature 或等价配置体系。", "配置传播到编译单元的路径", "默认配置和无效配置"),
            N("component-composition", "组件与依赖组合", "workspace、crate、组件接口及其初始化组合。", "组件边界和初始化顺序", "上游依赖、本地替换与适配位置"),
            N("rootfs-image", "根文件系统与镜像", "rootfs、initramfs、磁盘镜像及用户程序打包。", "镜像格式与内容来源", "内核如何发现并挂载"),
            N("platform-targets", "平台构建目标", "RISC-V、LoongArch、QEMU 和开发板等目标的构建分层。", "共享代码与平台专属代码", "目标选择和实际可达性"),
        ),
    ),
    "architecture-boot": TaxonomyModule(
        "architecture-boot",
        "体系结构与启动",
        "runtime",
        (
            N("boot", "启动", "从固件或模拟器入口到内核主初始化和首个用户进程。", "栈、BSS、页表与主入口", "多架构启动差异"),
            N("privilege-mode", "特权级切换", "内核态、用户态及其切换约定。", "CSR/寄存器准备", "返回用户态的安全条件"),
            N("trap-exception", "Trap 与异常", "异常入口、上下文保存恢复和异常分派。", "用户/内核异常分流", "可恢复与致命异常"),
            N("syscall-entry", "系统调用入口", "用户调用进入内核后的 ABI 取参与顶层分派。", "调用号和参数寄存器", "错误返回和未知调用"),
            N("interrupt-timer", "中断与时钟入口", "时钟和外部中断的识别、确认与分派。", "中断控制器交互", "调度和设备通知"),
            N("context-switch", "上下文切换", "任务切换时的寄存器、栈和地址空间切换。", "保存恢复集合", "切换前后不变量"),
            N("smp-bringup", "多核启动", "主核启动从核并使其进入统一内核运行环境。", "从核栈和初始化屏障", "失败核与在线状态"),
            N("per-cpu-state", "每核状态", "每 CPU 的当前任务、调度、中断和本地数据。", "定位和访问方式", "跨核共享边界"),
        ),
    ),
    "process-management": TaxonomyModule(
        "process-management",
        "进程、线程与调度",
        "runtime",
        (
            N("task-model", "任务与资源模型", "进程或任务对象及地址空间、文件、信号和父子关系的归属。", "生命周期和状态机", "资源拥有与共享"),
            N("thread-model", "线程模型", "内核线程、用户线程及线程组模型。", "线程私有和进程共享状态", "创建与退出"),
            N("scheduler", "调度器", "就绪队列、任务选择、抢占和上下文切换协作。", "状态迁移和队列不变量", "阻塞、唤醒和空闲路径"),
            N("scheduler-policy", "调度策略", "优先级、公平、实时或其他可替换调度策略。", "策略状态如何参与决策", "时间片、权重和抢占条件"),
            N("fork-clone", "Fork/Clone", "创建进程或线程并选择资源复制/共享关系。", "clone flags 或等价合同", "失败回滚和父子可见性"),
            N("exec", "Exec", "用新程序替换当前进程映像。", "ELF、参数和地址空间提交点", "旧资源释放与失败原子性"),
            N("wait-exit", "等待、退出与回收", "退出状态、僵尸、父进程等待和最终回收。", "退出提交点", "重父、WNOHANG 和并发等待"),
            N("signal", "信号", "信号产生、目标选择、屏蔽、用户处理和返回。", "pending/mask/handler 状态", "线程组和系统调用重启"),
            N("process-ipc", "进程间通信", "共享内存、消息队列、邮箱或其他进程级通信对象。", "对象生命周期和权限", "阻塞、容量与删除语义"),
            N("process-timers", "进程定时器", "睡眠、interval/POSIX timer 和 timerfd 等进程可见定时能力。", "时钟选择和到期通知", "重复装载、取消与退出清理"),
        ),
    ),
    "memory-management": TaxonomyModule(
        "memory-management",
        "内存管理",
        "runtime",
        (
            N("physical-allocator", "物理页分配", "物理页帧的发现、分配和回收。", "页元数据和空闲结构", "耗尽、并发和回收"),
            N("kernel-heap", "内核堆", "内核动态内存和子页分配。", "页后端和碎片策略", "并发与失败语义"),
            N("slab-object-cache", "Slab/对象缓存", "面向固定大小内核对象的缓存分配子系统。", "cache/slab/object 元数据", "空闲对象、页归还和真实调用者"),
            N("page-table", "页表", "多级页表、映射、解除映射和权限管理。", "PTE 状态和页表所有权", "修改与 TLB 同步"),
            N("kernel-address-space", "内核地址空间", "内核页表、直接映射或高半区布局。", "映射范围与权限", "各平台布局差异"),
            N("user-address-space", "用户地址空间", "每进程用户映射及内核访问用户内存的边界。", "VMA/映射所有权", "用户指针复制和校验"),
            N("mmap", "内存映射", "匿名和文件映射、共享/私有语义及解除映射。", "VMA 拆分合并", "offset、权限和错误路径"),
            N("page-fault-cow", "缺页与 COW", "懒分配、写时复制和文件映射缺页修复。", "fault 分类和修复提交点", "引用计数、权限与失败回滚"),
            N("page-cache", "页缓存", "文件页的查找、装入、脏化、回写和回收。", "缓存键和页生命周期", "read/write/mmap 一致性"),
            N("shared-memory", "共享内存", "跨进程共享的内存对象和映射生命周期。", "命名/ID、权限和页所有权", "attach/detach 与退出清理"),
            N("swap-reclaim", "换页与内存回收", "主动页回收、swap 存储和 fault-in。", "匿名页与文件页区分", "slot、写回和 OOM 边界"),
            N("tlb-management", "TLB 管理", "本地刷新、ASID 和多核 TLB shootdown。", "刷新范围和时机", "跨核完成条件"),
        ),
    ),
    "file-system": TaxonomyModule(
        "file-system",
        "文件系统与 I/O",
        "runtime",
        (
            N("file-descriptor", "文件描述符", "每进程 fd 表和共享 open-file 状态。", "dup/close/继承和文件偏移", "socket/pipe/设备 fd 统一"),
            N("vfs", "VFS", "文件、文件系统实例和操作分派的统一抽象。", "对象所有权和操作表", "根文件系统、多文件系统、页缓存和块层连接"),
            N("inode-dentry", "Inode/Dentry 与路径", "路径解析、目录项、inode 和元数据缓存。", "查找、链接、重命名和删除", "锁与引用生命周期"),
            N("mount", "挂载体系", "文件系统注册、挂载树和卸载生命周期。", "挂载点与路径穿越", "引用占用和卸载失败"),
            N("fat32", "FAT32", "FAT32 文件系统及其 VFS/块层适配。", "BPB、FAT、簇链和目录项", "读写、扩展、截断、同步和错误路径"),
            N("ext4", "Ext4", "Ext4 文件系统及其 VFS/块层适配。", "超级块、inode、extent 和目录", "挂载、读写、截断、同步与来源边界"),
            N("native-file-system", "原生文件系统", "作品自有或 Base 原生的磁盘文件系统。", "目录/inode 等价对象与块分配", "缓存、元数据更新和一致性"),
            N("memory-file-system", "内存文件系统", "ramfs、tmpfs 或内存后端 rootfs。", "对象生命周期和容量", "与磁盘文件系统的语义差异"),
            N("pseudo-file-system", "虚拟文件系统", "procfs、devfs 等由内核对象生成内容的文件系统。", "节点生成与权限", "设备/进程对象连接"),
            N("pipe-fifo", "管道与 FIFO", "以 fd 暴露的字节流 IPC。", "缓冲区、端点引用和 EOF/EPIPE", "阻塞、非阻塞和唤醒"),
            N("block-cache", "块缓存", "面向块设备的 buffer/block cache。", "缓存键、替换和脏块", "写回、同步和错误传播"),
            N("journal-log", "文件系统日志", "事务日志、WAL 和崩溃恢复。", "事务边界与提交顺序", "回放和故障边界"),
        ),
    ),
    "device-driver": TaxonomyModule(
        "device-driver",
        "设备与平台驱动",
        "runtime",
        (
            N("driver-model", "驱动模型", "设备、驱动和上层接口的注册与绑定。", "对象生命周期和操作表", "初始化顺序与失败清理"),
            N("interrupt-controller", "中断控制器", "PLIC 等控制器的 IRQ 注册、屏蔽、确认和分派。", "IRQ 状态和处理顺序", "多核路由和计数"),
            N("console-uart", "控制台与 UART", "早期输出、UART 驱动和用户终端入口。", "轮询/中断收发", "缓冲、阻塞和 TTY 接入"),
            N("clock-timer-device", "时钟与定时器设备", "硬件时钟源、clock event 和 RTC。", "频率换算和精度", "单调/实时时钟与中断"),
            N("block-device-driver", "块设备驱动", "VirtIO block、SD/eMMC 等块设备实现。", "请求队列和 buffer ownership", "轮询/中断完成、多设备和错误恢复"),
            N("network-device-driver", "网络设备驱动", "VirtIO net 和物理网卡的收发驱动。", "RX/TX queue 和 packet ownership", "中断/轮询、链路与协议栈接入"),
            N("platform-discovery", "平台与设备发现", "设备树、平台总线和板级设备描述。", "发现、匹配和 MMIO 映射", "QEMU/开发板差异"),
            N("pci", "PCI/PCIe", "PCI 配置空间、枚举、BAR、IRQ 和设备绑定。", "总线扫描和资源分配", "与具体驱动的连接"),
            N("dma", "DMA", "DMA 地址、描述符和缓存一致性管理。", "descriptor/buffer 生命周期", "完成、错误和回收"),
            N("display-input", "显示与输入设备", "framebuffer/GPU 及键盘、鼠标、触摸等输入设备。", "设备接口和事件路径", "用户可见接口与缺失边界"),
        ),
    ),
    "network-stack": TaxonomyModule(
        "network-stack",
        "网络栈",
        "runtime",
        (
            N("socket", "Socket", "socket API、fd 集成和 socket 生命周期。", "bind/connect/listen/accept/close", "阻塞、非阻塞和事件等待"),
            N("ipv4-routing", "IPv4 与路由", "IPv4 地址、路由、ARP/邻居和转发。", "接口与路由选择", "本地、外发和接收路径"),
            N("tcp", "TCP", "TCP 连接和可靠字节流。", "状态机、队列与定时器", "重传、关闭和错误"),
            N("udp", "UDP", "UDP 数据报传输。", "端口解复用和报文边界", "错误与阻塞语义"),
            N("unix-domain-socket", "Unix 域套接字", "AF_UNIX/AF_LOCAL 本地 socket IPC。", "地址、连接和消息对象", "fd 就绪和关闭"),
            N("ipv6", "IPv6", "IPv6 地址、路由、邻居发现和传输接入。", "地址与路由状态", "TCP/UDP 和 socket ABI"),
            N("network-device-interface", "网络设备接口", "协议栈与网卡驱动之间的统一接口。", "收发入口和设备状态", "真实网卡与 loopback 边界"),
            N("packet-buffer", "网络包缓冲", "mbuf/skb 等数据包所有权与生命周期。", "分配、切片、复用和回收", "跨协议层和设备队列所有权"),
            N("loopback", "Loopback", "本地回环接口和数据路径。", "路由和收发闭环", "不得替代真实设备网络"),
        ),
    ),
    "synchronization": TaxonomyModule(
        "synchronization",
        "同步机制",
        "runtime",
        (
            N("spinlock", "自旋锁", "短临界区和中断上下文同步。", "锁状态和内存序", "IRQ-safe、递归和锁层级"),
            N("mutex", "互斥锁", "可睡眠互斥同步。", "所有权和等待者队列", "优先级反转与退出清理"),
            N("semaphore", "信号量", "计数资源同步。", "计数与等待队列不变量", "超时、唤醒和删除"),
            N("sleep-lock", "睡眠锁", "持锁期间允许阻塞的长临界区锁。", "持有者和睡眠条件", "与自旋锁的边界"),
            N("wait-queue", "等待队列", "条件等待、阻塞和唤醒基础设施。", "检查-入队-睡眠原子性", "丢失唤醒与取消"),
            N("futex", "Futex", "用户值与内核等待队列结合的同步机制。", "等待键、值检查和唤醒", "超时、robust list 和退出清理"),
            N("atomic-refcount", "原子操作与引用计数", "无锁原子状态和对象生命周期计数。", "内存序与可见性", "最后释放竞态"),
            N("read-write-lock", "读写锁与序列锁", "读多写少场景的并发同步。", "读写状态和饥饿策略", "seqlock 重试与一致性"),
        ),
    ),
    "user-abi-compat": TaxonomyModule(
        "user-abi-compat",
        "用户 ABI 与兼容层",
        "runtime",
        (
            N("elf-abi", "ELF ABI", "ELF 校验、段装载、权限和架构 ABI。", "PT_LOAD、BSS 和入口", "无效 ELF 与架构差异"),
            N("dynamic-runtime", "动态装载与 TLS", "PT_INTERP、共享库映射、重定位职责和 TLS。", "解释器启动合同", "线程 TLS 和清理"),
            N("process-startup-abi", "进程启动 ABI", "argc/argv/envp/auxv 和初始用户栈。", "布局、对齐和辅助向量", "exec 输入到用户入口"),
            N("syscall-uapi", "系统调用 UAPI", "系统调用号、寄存器、用户结构体和 errno 合同。", "多架构布局和位宽", "用户复制与错误转换"),
            N("libc", "Libc 兼容", "musl/glibc 或自有 libc 的系统调用和线程运行支持。", "wrapper、errno 和缺失符号", "静态/动态及线程依赖"),
            N("posix-linux-compat", "POSIX/Linux 兼容", "复杂用户程序依赖的进程、文件、时间、信号和网络接口集合。", "真实语义、空壳和 ENOSYS 区分", "splice/sendfile/copy_file_range、eventfd/inotify 等扩展接口", "不得用 syscall 数量代替完成度"),
            N("init-shell-userland", "Init、Shell 与用户程序", "首个用户进程、Shell 和随系统提供的用户程序。", "装载和依赖闭环", "程序文件存在不等于可运行"),
            N("vdso-vvar", "vDSO/vvar", "用户态快速系统服务页和共享内核数据。", "映射、导出符号和数据同步", "架构 ABI 与 syscall fallback"),
        ),
    ),
    "kernel-services": TaxonomyModule(
        "kernel-services",
        "内核服务",
        "support",
        (
            N("deferred-work", "延后工作", "workqueue、tasklet 或等价异步内核工作。", "排队、执行上下文和取消", "flush、关机和错误"),
            N("softirq", "软中断", "中断下半部和延后中断处理。", "触发与执行上下文", "并发、预算和普通工作队列边界"),
            N("timer-subsystem", "定时器子系统", "timer list、时间轮、hrtimer 或等价内核定时器。", "排序、插入、取消和推进", "回调上下文与竞态"),
            N("randomness", "随机数服务", "随机设备、getrandom、熵池和 PRNG。", "种子与熵来源", "并发、阻塞和安全边界"),
            N("ebpf", "eBPF", "eBPF 程序、Map、fd、验证和 hook 子系统。", "装载、执行器和 helper", "Map 生命周期、验证边界、attach/detach"),
            N("shutdown-reset", "关机与复位", "从用户请求到 QEMU/开发板关机或复位。", "平台接口与退出状态", "失败和重复请求"),
        ),
    ),
    "security-isolation": TaxonomyModule(
        "security-isolation",
        "安全与隔离",
        "support",
        (
            N("user-kernel-isolation", "用户/内核隔离", "地址、权限和访问路径上的用户/内核隔离。", "PTE 权限和用户指针边界", "内核异常与越权失败"),
            N("credentials-permissions", "身份与权限", "UID/GID、文件权限和进程凭据。", "继承、修改和检查点", "固定身份与真实权限模型区分"),
            N("capability-acl", "Capability/ACL", "细粒度 capability 或 ACL 权限模型。", "对象、授权和检查位置", "默认拒绝与绕过边界"),
            N("write-xor-execute", "W^X", "可写和可执行权限互斥策略。", "映射建立和权限变更", "架构 NX/PTE 支持与例外"),
        ),
    ),
    "observability-debug": TaxonomyModule(
        "observability-debug",
        "调试与可观测性",
        "support",
        (
            N("logging", "内核日志", "内核日志输出、缓冲和级别控制。", "并发与中断上下文", "丢失、截断和用户接口"),
            N("panic", "Panic 与故障处理", "不可恢复错误、assert 和内核故障终止。", "现场保存和多核停止", "退出、复位和递归故障"),
            N("backtrace", "调用栈回溯", "帧指针、符号表或展开信息生成调用栈。", "栈遍历和符号解析", "优化、跨架构和损坏栈边界"),
            N("tracing", "运行跟踪", "系统调用、事件或调度跟踪设施。", "事件模型和缓冲", "启停、开销和读取接口"),
        ),
    ),
}


DELETED_MODULES = {"metadata", "evolution-history", "virtualization"}
DELETED_NODES = {
    "namespace",
    "cgroup",
    "rcu",
    "netfilter",
    "module-loader",
    "power-management",
    "seccomp",
    "kaslr",
    "stack-protector",
    "module-signature",
    "perf-counter",
    "gdb-stub",
    "sanitizer",
    "hypervisor-mode",
    "virtio-guest",
    "container-primitives",
}


NODE_INDEX: dict[str, tuple[str, TaxonomyNode]] = {
    node.node_id: (module.module_id, node)
    for module in MODULES.values()
    for node in module.nodes
}

REQUIRED_MODULES = MODULES


def required_module_ids() -> list[str]:
    return list(MODULES)


def node_owner(node_id: str) -> str | None:
    item = NODE_INDEX.get(node_id)
    return item[0] if item else None


def validate_taxonomy() -> ValidationReport:
    report = ValidationReport()
    seen: set[str] = set()
    for module in MODULES.values():
        if module.architecture_role not in VALID_ARCHITECTURE_ROLES:
            report.add("taxonomy.invalid_architecture_role", f"{module.module_id}: {module.architecture_role}")
        if not module.nodes:
            report.add("taxonomy.empty_module", f"module has no nodes: {module.module_id}")
        for node in module.nodes:
            if node.node_id in seen:
                report.add("taxonomy.duplicate_node", f"duplicate node_id: {node.node_id}")
            seen.add(node.node_id)
            if not node.scope or not node.description_requirements:
                report.add("taxonomy.incomplete_node", f"{node.node_id} needs scope and description requirements")
    for required in {"ext4", "fat32", "slab-object-cache", "page-cache", "smp-bringup", "socket"}:
        if required not in NODE_INDEX:
            report.add("taxonomy.required_missing", f"missing required node: {required}")
    forbidden_text = " ".join(
        [module.module_id for module in MODULES.values()]
        + [node.node_id for module in MODULES.values() for node in module.nodes]
    )
    for deleted in DELETED_MODULES | DELETED_NODES:
        if deleted in forbidden_text:
            report.add("taxonomy.deleted_present", f"deleted module/node appears in taxonomy: {deleted}")
    return report


def scan_deleted_features(text: str) -> list[str]:
    lowered = re.sub(r"[\s_/]+", "-", text.lower())
    labels = DELETED_NODES | {"virtualization"}
    return sorted(label for label in labels if label in lowered)
