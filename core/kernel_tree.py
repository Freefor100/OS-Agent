from __future__ import annotations

from copy import deepcopy
from typing import Any


ROOT_NODES_V2: dict[str, list[str]] = {
    "Metadata": [],
    "BuildAndConfig": ["MakeTargets", "LinkerScript", "Toolchain", "KernelConfig", "CargoFeatures", "Initramfs"],
    "ArchitectureLayer": ["Boot", "EarlyConsole", "TrapException", "SyscallEntry", "InterruptTimer", "ContextSwitch", "SMPBringup", "PerCpuState"],
    "ProcessManagement": [
        "TaskStruct", "ThreadModel", "Scheduler", "SchedulerClass", "ForkClone", "Exec",
        "WaitExit", "Signal", "IPC", "Futex", "Namespace", "Cgroup",
    ],
    "MemoryManagement": [
        "PhysicalAllocator", "KernelHeap", "SlabObjectCache", "PageTable", "KernelAddressSpace",
        "UserAddressSpace", "Mmap", "PageFault", "CopyUser", "PageCache", "Swap", "TLBManagement",
    ],
    "FileSystem": [
        "VFS", "FileDescriptorTable", "InodeDentry", "ConcreteFS.FAT32", "ConcreteFS.ext4",
        "ConcreteFS.ramfs", "ConcreteFS.devfs", "PipeOrProcFS", "BlockCache", "JournalOrLog",
        "BlockDevice", "PageCacheIntegration",
    ],
    "DeviceDriver": [
        "DriverModel", "InterruptController", "ConsoleUART", "VirtIO", "PCI", "PlatformBus",
        "DMA", "GPUDisplay", "InputDevice", "ClockTimerDevice", "SDCard", "BlockDevice",
    ],
    "Network": ["Socket", "TCPUDP", "NetDevice", "PacketBuffer", "Netfilter", "UnixDomainSocket", "Loopback"],
    "Synchronization": ["SpinLock", "Mutex", "Semaphore", "SleepLock", "WaitQueue", "RCU", "AtomicRefCount", "ReadWriteLock"],
    "UserLibAndTests": ["LibcOrSyscallWrapper", "Shell", "InitProc", "TestPrograms", "ELFABI", "PosixCompat", "DynamicLinker", "VDSO"],
    "KernelServices": ["WorkQueue", "SoftIRQ", "TimerWheel", "ModuleLoader", "Randomness", "PowerManagement", "KernelCommandLine"],
    "SecurityAndIsolation": ["PrivilegeMode", "UserKernelIsolation", "CapabilityOrACL", "SeccompSandbox", "KASLR", "WriteXorExecute", "StackProtector", "ModuleSignature"],
    "ObservabilityAndDebug": ["Logging", "Panic", "Backtrace", "Tracing", "PerfCounter", "GDBStub", "Sanitizer"],
    "Virtualization": ["HypervisorMode", "VirtioGuest", "ContainerPrimitives"],
    "EvolutionHistory": [],
}


ANALYSIS_BATCHES_V2: list[list[str]] = [
    ["Metadata", "BuildAndConfig.MakeTargets", "BuildAndConfig.LinkerScript", "BuildAndConfig.Toolchain", "BuildAndConfig.KernelConfig", "BuildAndConfig.CargoFeatures", "BuildAndConfig.Initramfs"],
    ["ArchitectureLayer.Boot", "ArchitectureLayer.EarlyConsole", "DeviceDriver.ConsoleUART"],
    ["MemoryManagement.PhysicalAllocator", "MemoryManagement.PageTable", "MemoryManagement.KernelAddressSpace", "MemoryManagement.UserAddressSpace", "MemoryManagement.CopyUser"],
    ["ArchitectureLayer.TrapException", "ArchitectureLayer.SyscallEntry", "ArchitectureLayer.InterruptTimer"],
    ["ProcessManagement.TaskStruct", "ArchitectureLayer.ContextSwitch", "ProcessManagement.Scheduler", "Synchronization.SpinLock", "Synchronization.WaitQueue"],
    ["ProcessManagement.ForkClone", "ProcessManagement.Exec", "ProcessManagement.WaitExit", "ProcessManagement.Signal", "ProcessManagement.IPC"],
    ["MemoryManagement.KernelHeap", "MemoryManagement.SlabObjectCache", "MemoryManagement.Mmap", "MemoryManagement.PageFault", "MemoryManagement.PageCache", "MemoryManagement.Swap", "MemoryManagement.TLBManagement"],
    ["Synchronization.Mutex", "Synchronization.Semaphore", "Synchronization.SleepLock", "Synchronization.RCU", "Synchronization.AtomicRefCount", "Synchronization.ReadWriteLock"],
    ["FileSystem.FileDescriptorTable", "FileSystem.VFS", "FileSystem.InodeDentry", "FileSystem.PipeOrProcFS"],
    ["FileSystem.BlockCache", "FileSystem.JournalOrLog", "FileSystem.BlockDevice", "DeviceDriver.VirtIO", "DeviceDriver.InterruptController", "DeviceDriver.BlockDevice", "DeviceDriver.SDCard"],
    ["FileSystem.ConcreteFS.FAT32", "FileSystem.ConcreteFS.ext4", "FileSystem.ConcreteFS.ramfs", "FileSystem.ConcreteFS.devfs", "FileSystem.PageCacheIntegration"],
    ["DeviceDriver.DriverModel", "DeviceDriver.PCI", "DeviceDriver.PlatformBus", "DeviceDriver.DMA", "DeviceDriver.GPUDisplay", "DeviceDriver.InputDevice", "DeviceDriver.ClockTimerDevice"],
    ["Network.Socket", "Network.TCPUDP", "Network.NetDevice", "Network.PacketBuffer", "Network.Netfilter", "Network.UnixDomainSocket", "Network.Loopback"],
    ["SecurityAndIsolation.PrivilegeMode", "SecurityAndIsolation.UserKernelIsolation", "SecurityAndIsolation.CapabilityOrACL", "SecurityAndIsolation.SeccompSandbox", "SecurityAndIsolation.KASLR", "SecurityAndIsolation.WriteXorExecute", "SecurityAndIsolation.StackProtector", "SecurityAndIsolation.ModuleSignature"],
    ["KernelServices.WorkQueue", "KernelServices.SoftIRQ", "KernelServices.TimerWheel", "KernelServices.ModuleLoader", "KernelServices.Randomness", "KernelServices.PowerManagement", "KernelServices.KernelCommandLine"],
    ["ArchitectureLayer.SMPBringup", "ArchitectureLayer.PerCpuState", "ProcessManagement.ThreadModel", "ProcessManagement.SchedulerClass", "ProcessManagement.Futex", "ProcessManagement.Namespace", "ProcessManagement.Cgroup"],
    ["ObservabilityAndDebug.Logging", "ObservabilityAndDebug.Panic", "ObservabilityAndDebug.Backtrace", "ObservabilityAndDebug.Tracing", "ObservabilityAndDebug.PerfCounter", "ObservabilityAndDebug.GDBStub", "ObservabilityAndDebug.Sanitizer"],
    ["UserLibAndTests.LibcOrSyscallWrapper", "UserLibAndTests.Shell", "UserLibAndTests.InitProc", "UserLibAndTests.TestPrograms", "UserLibAndTests.ELFABI", "UserLibAndTests.PosixCompat", "UserLibAndTests.DynamicLinker", "UserLibAndTests.VDSO"],
    ["Virtualization.HypervisorMode", "Virtualization.VirtioGuest", "Virtualization.ContainerPrimitives"],
    ["EvolutionHistory"],
]


ANALYSIS_ORDER_V2: list[str] = [node for batch in ANALYSIS_BATCHES_V2 for node in batch]
VALID_NODE_IDS: set[str] = set(ANALYSIS_ORDER_V2)
VALID_ROOT_IDS: set[str] = set(ROOT_NODES_V2)
VALID_IDS: set[str] = VALID_NODE_IDS | VALID_ROOT_IDS


TITLE_ZH: dict[str, str] = {
    "KernelProject": "内核项目",
    "Metadata": "元信息",
    "BuildAndConfig": "构建与配置",
    "ArchitectureLayer": "架构与启动",
    "ProcessManagement": "进程管理",
    "MemoryManagement": "内存管理",
    "FileSystem": "文件系统",
    "DeviceDriver": "设备驱动",
    "Network": "网络",
    "Synchronization": "同步机制",
    "UserLibAndTests": "用户库与测试",
    "KernelServices": "内核服务",
    "SecurityAndIsolation": "安全与隔离",
    "ObservabilityAndDebug": "调试与可观测性",
    "Virtualization": "虚拟化",
    "EvolutionHistory": "演进历史",
    "MakeTargets": "Make 目标",
    "LinkerScript": "链接脚本",
    "Toolchain": "工具链",
    "KernelConfig": "内核配置",
    "CargoFeatures": "Cargo 特性",
    "Initramfs": "初始根文件系统",
    "Boot": "启动入口",
    "EarlyConsole": "早期控制台",
    "TrapException": "Trap 与异常",
    "SyscallEntry": "系统调用入口",
    "InterruptTimer": "定时器中断",
    "ContextSwitch": "上下文切换",
    "SMPBringup": "多核启动",
    "PerCpuState": "每 CPU 状态",
    "TaskStruct": "任务结构",
    "ThreadModel": "线程模型",
    "Scheduler": "调度器",
    "SchedulerClass": "调度类",
    "ForkClone": "Fork/Clone",
    "Exec": "Exec 装载",
    "WaitExit": "等待与退出",
    "Signal": "信号",
    "IPC": "进程间通信",
    "Futex": "Futex 快速用户锁",
    "Namespace": "命名空间",
    "Cgroup": "控制组",
    "PhysicalAllocator": "物理页分配器",
    "KernelHeap": "内核堆",
    "SlabObjectCache": "对象缓存",
    "PageTable": "页表",
    "KernelAddressSpace": "内核地址空间",
    "UserAddressSpace": "用户地址空间",
    "Mmap": "内存映射",
    "PageFault": "缺页异常",
    "CopyUser": "用户拷贝",
    "PageCache": "页缓存",
    "Swap": "交换空间",
    "TLBManagement": "TLB 管理",
    "VFS": "虚拟文件系统",
    "FileDescriptorTable": "文件描述符表",
    "InodeDentry": "Inode/Dentry",
    "ConcreteFS.FAT32": "FAT32 文件系统",
    "ConcreteFS.ext4": "ext4 文件系统",
    "ConcreteFS.ramfs": "内存文件系统",
    "ConcreteFS.devfs": "设备文件系统",
    "PipeOrProcFS": "Pipe/ProcFS",
    "BlockCache": "块缓存",
    "JournalOrLog": "日志/Journaling",
    "BlockDevice": "块设备",
    "PageCacheIntegration": "页缓存集成",
    "DriverModel": "驱动模型",
    "InterruptController": "中断控制器",
    "ConsoleUART": "串口控制台",
    "VirtIO": "VirtIO 虚拟设备",
    "PCI": "PCI 总线",
    "PlatformBus": "平台总线",
    "DMA": "DMA 直接内存访问",
    "GPUDisplay": "图形显示",
    "InputDevice": "输入设备",
    "ClockTimerDevice": "时钟/定时器设备",
    "SDCard": "SD 卡",
    "Socket": "Socket 套接字",
    "TCPUDP": "TCP/UDP",
    "NetDevice": "网络设备",
    "PacketBuffer": "包缓冲",
    "Netfilter": "包过滤",
    "UnixDomainSocket": "Unix 域套接字",
    "Loopback": "Loopback 回环",
    "SpinLock": "自旋锁",
    "Mutex": "互斥锁",
    "Semaphore": "信号量",
    "SleepLock": "睡眠锁",
    "WaitQueue": "等待队列",
    "RCU": "RCU 读拷贝更新",
    "AtomicRefCount": "原子引用计数",
    "ReadWriteLock": "读写锁",
    "LibcOrSyscallWrapper": "用户库/系统调用封装",
    "Shell": "Shell 命令行",
    "InitProc": "Init 进程",
    "TestPrograms": "测试程序",
    "ELFABI": "ELF ABI",
    "PosixCompat": "POSIX 兼容",
    "DynamicLinker": "动态链接器",
    "VDSO": "VDSO 虚拟动态库",
    "WorkQueue": "工作队列",
    "SoftIRQ": "软中断",
    "TimerWheel": "定时器轮",
    "ModuleLoader": "模块加载器",
    "Randomness": "随机数",
    "PowerManagement": "电源管理",
    "KernelCommandLine": "内核命令行",
    "PrivilegeMode": "特权级",
    "UserKernelIsolation": "用户/内核隔离",
    "CapabilityOrACL": "能力/ACL",
    "SeccompSandbox": "Seccomp 沙箱",
    "KASLR": "KASLR 地址随机化",
    "WriteXorExecute": "W^X",
    "StackProtector": "栈保护",
    "ModuleSignature": "模块签名",
    "Logging": "日志",
    "Panic": "Panic 崩溃处理",
    "Backtrace": "回溯",
    "Tracing": "跟踪",
    "PerfCounter": "性能计数器",
    "GDBStub": "GDB Stub",
    "Sanitizer": "Sanitizer 运行时检测",
    "HypervisorMode": "Hypervisor 模式",
    "VirtioGuest": "VirtIO Guest",
    "ContainerPrimitives": "容器原语",
}


TITLE_EN: dict[str, str] = {
    "Metadata": "Metadata",
    "BuildAndConfig": "Build & Configuration",
    "ArchitectureLayer": "Architecture & Boot",
    "ProcessManagement": "Process Management",
    "MemoryManagement": "Memory Management",
    "FileSystem": "File System",
    "DeviceDriver": "Device Drivers",
    "Network": "Network",
    "Synchronization": "Synchronization",
    "UserLibAndTests": "User Library & Tests",
    "KernelServices": "Kernel Services",
    "SecurityAndIsolation": "Security & Isolation",
    "ObservabilityAndDebug": "Observability & Debug",
    "Virtualization": "Virtualization",
    "EvolutionHistory": "Evolution History",
}


# NODE_SCOPE: 每个叶子节点一句「什么工作算这里」的边界描述。
# Agent 到节点先读 scope 明边界，再决定哪些函数挂进来。用于划分归属、防归错，
# 不参与工作量判断（工作量靠指纹 diff）。
NODE_SCOPE: dict[str, str] = {
    "Metadata": "内核范式（宏/微/exo）、目标架构、目标平台、boot 协议等整体身份信息",
    # ── 构建与配置 ──
    "BuildAndConfig.MakeTargets": "Makefile 构建/运行目标、qemu 启动命令、文件系统镜像构建规则",
    "BuildAndConfig.LinkerScript": "链接脚本：段布局、入口符号、各平台 .ld 内存布局",
    "BuildAndConfig.Toolchain": "交叉编译工具链选择：gcc/llvm、objdump/gdb 等工具配置",
    "BuildAndConfig.KernelConfig": "编译期平台/单板选择、CPU 数、CFLAGS/CPPFLAGS 等内核配置",
    "BuildAndConfig.CargoFeatures": "Cargo features、rust-toolchain、workspace 成员等 Rust 构建配置",
    "BuildAndConfig.Initramfs": "initramfs/rootfs 镜像打包、根文件系统构建",
    # ── 架构与启动 ──
    "ArchitectureLayer.Boot": "汇编入口、栈建立、SBI/multiboot 握手、跳转 kernel_main、多架构启动抽象",
    "ArchitectureLayer.EarlyConsole": "早期裸机控制台：bootlog、未初始化驱动前的 putchar",
    "ArchitectureLayer.TrapException": "trap 向量、用户/内核 trap 分流、trapframe 保存恢复、scause 分派、缺页检测入口",
    "ArchitectureLayer.SyscallEntry": "系统调用号分派、syscall 表、trapframe 取参 ABI",
    "ArchitectureLayer.InterruptTimer": "定时器中断设置、时钟 tick、时间片到期触发抢占",
    "ArchitectureLayer.ContextSwitch": "汇编上下文切换 swtch、callee-saved 保存、调度器与进程间切换",
    "ArchitectureLayer.SMPBringup": "多核启动、从核 hart 唤醒、IPI 核间中断启动",
    "ArchitectureLayer.PerCpuState": "每 CPU 私有状态：per-cpu 调度状态、每核内核栈",
    # ── 进程管理 ──
    "ProcessManagement.TaskStruct": "进程/任务控制块结构、全局进程表、进程状态机、每任务内核栈与 trapframe",
    "ProcessManagement.ThreadModel": "线程模型：单线程进程 / 内核线程 / 用户线程",
    "ProcessManagement.Scheduler": "就绪队列管理、选下一个运行进程、时间片抢占、yield·sleep·wakeup",
    "ProcessManagement.SchedulerClass": "多调度类框架：优先级/公平/CFS红黑树/EEVDF/O(1)/deadline 调度策略",
    "ProcessManagement.ForkClone": "fork/clone：复制地址空间、复制 trapframe、分配子进程、clone flags",
    "ProcessManagement.Exec": "ELF 装载、参数栈建立、地址空间替换、解释器/auxv",
    "ProcessManagement.WaitExit": "进程退出、僵尸态、子进程重定父、wait 回收退出码、kill",
    "ProcessManagement.Signal": "Unix 信号：信号掩码、信号处理表、sigaction、信号 trampoline",
    "ProcessManagement.IPC": "进程间通信：管道、共享内存、消息队列",
    "ProcessManagement.Futex": "Linux futex 快速用户态锁",
    "ProcessManagement.Namespace": "命名空间隔离：pid/mount/network/user namespace",
    "ProcessManagement.Cgroup": "控制组：资源限制、memcg",
    # ── 内存管理 ──
    "MemoryManagement.PhysicalAllocator": "物理页帧分配器：free-list/buddy/bitmap，分配释放空闲页",
    "MemoryManagement.KernelHeap": "内核堆：kmalloc/subpage/buddy 堆，内核动态内存分配",
    "MemoryManagement.SlabObjectCache": "slab/对象缓存：固定大小对象的高效分配",
    "MemoryManagement.PageTable": "sv39 多级页表 walk/map/unmap、PTE 权限位、satp 切换、TLB flush",
    "MemoryManagement.KernelAddressSpace": "内核地址空间：直接映射、内核页表、高半区映射",
    "MemoryManagement.UserAddressSpace": "用户地址空间：每进程页表、fork 时地址空间复制、懒分配 VMA",
    "MemoryManagement.Mmap": "mmap 系统调用、mmap VMA、文件映射、匿名映射、munmap",
    "MemoryManagement.PageFault": "缺页处理：懒分配、写时复制 COW、mmap 缺页填充、COW 引用计数",
    "MemoryManagement.CopyUser": "内核与用户空间拷贝：copyin/copyout/copyinstr、用户指针校验",
    "MemoryManagement.PageCache": "页缓存：文件页缓存、统一页缓存、透明大页",
    "MemoryManagement.Swap": "交换空间：swap 文件/分区、页回收 kswapd、OOM killer",
    "MemoryManagement.TLBManagement": "TLB 管理：sfence.vma 刷新、TLB shootdown（多核）",
    # ── 文件系统 ──
    "FileSystem.VFS": "虚拟文件系统层：file 抽象、vnode 层、挂载分派",
    "FileSystem.FileDescriptorTable": "每进程文件描述符表：fdalloc、dup/close 引用计数、socket fd 集成",
    "FileSystem.InodeDentry": "inode/dentry 缓存、目录项查找、路径解析 namei、inode 锁",
    "FileSystem.ConcreteFS.FAT32": "FAT32 文件系统：簇链、FAT 目录项、FAT 表缓存",
    "FileSystem.ConcreteFS.ext4": "ext4 文件系统：超级块、extent 树、journal",
    "FileSystem.ConcreteFS.ramfs": "内存文件系统：内存后端 fs、rootfs 镜像",
    "FileSystem.ConcreteFS.devfs": "设备文件系统：设备 inode、major/minor 分派、devsw",
    "FileSystem.PipeOrProcFS": "管道环形缓冲、procfs 虚拟文件",
    "FileSystem.BlockCache": "块缓冲缓存：buffer cache、块哈希、LRU",
    "FileSystem.JournalOrLog": "文件系统日志：write-ahead log、事务日志、崩溃恢复",
    "FileSystem.BlockDevice": "块设备抽象：bio 请求队列、缓冲块 IO",
    "FileSystem.PageCacheIntegration": "fs 与页缓存集成：page-cache 后端 fs vs 仅 buffer-cache",
    # ── 设备驱动 ──
    "DeviceDriver.DriverModel": "驱动模型：扁平驱动表 vs Linux 式驱动模型、平台设备表",
    "DeviceDriver.InterruptController": "中断控制器：PLIC/APIC、IRQ 分派、设备中断应答",
    "DeviceDriver.ConsoleUART": "串口控制台驱动：UART MMIO、console 设备、中断驱动控制台",
    "DeviceDriver.VirtIO": "VirtIO：virtqueue 描述符环、mmio/pci 传输、virtio 块设备",
    "DeviceDriver.PCI": "PCI 总线探测、设备枚举",
    "DeviceDriver.PlatformBus": "平台总线：平台设备表、设备树探测",
    "DeviceDriver.DMA": "DMA 控制器、bounce buffer",
    "DeviceDriver.GPUDisplay": "图形显示：framebuffer 驱动、GPU MMIO",
    "DeviceDriver.InputDevice": "输入设备：键盘/鼠标/触摸驱动",
    "DeviceDriver.ClockTimerDevice": "时钟/定时器设备：timer device、clock event device",
    "DeviceDriver.SDCard": "SD 卡块设备：SPI SD 驱动、PIO 块传输",
    "DeviceDriver.BlockDevice": "块设备驱动层：virtio/SD 块设备、缓冲块 IO",
    # ── 网络 ──
    "Network.Socket": "BSD socket API、socket 与 fd 集成、raw socket",
    "Network.TCPUDP": "TCP 状态机、UDP 数据报、端口解复用",
    "Network.NetDevice": "网络设备：以太网驱动、virtio-net",
    "Network.PacketBuffer": "包缓冲：mbuf/skb 数据结构",
    "Network.Netfilter": "包过滤钩子、netfilter",
    "Network.UnixDomainSocket": "Unix 域套接字 AF_UNIX",
    "Network.Loopback": "回环设备、本地 socket 转发",
    # ── 同步机制 ──
    "Synchronization.SpinLock": "自旋锁：test-and-set/ticket/MCS qspinlock、关中断锁、lockdep",
    "Synchronization.Mutex": "阻塞互斥锁、sleeplock 式 mutex",
    "Synchronization.Semaphore": "计数信号量",
    "Synchronization.SleepLock": "睡眠锁、阻塞锁",
    "Synchronization.WaitQueue": "等待队列、sleep/wakeup channel、条件变量",
    "Synchronization.RCU": "RCU 读拷贝更新",
    "Synchronization.AtomicRefCount": "原子引用计数、锁保护引用计数",
    "Synchronization.ReadWriteLock": "读写锁、seqlock",
    # ── 用户库与测试 ──
    "UserLibAndTests.LibcOrSyscallWrapper": "用户态 syscall stub、最小 libc、系统调用封装",
    "UserLibAndTests.Shell": "用户 shell、命令解析",
    "UserLibAndTests.InitProc": "initcode 第一个进程、用户 init 程序",
    "UserLibAndTests.TestPrograms": "用户测试程序：usertests、文件系统/mmap 测试",
    "UserLibAndTests.ELFABI": "ELF 二进制 ABI",
    "UserLibAndTests.PosixCompat": "POSIX 兼容层",
    "UserLibAndTests.DynamicLinker": "动态链接器 ABI",
    "UserLibAndTests.VDSO": "VDSO 页",
    # ── 内核服务 ──
    "KernelServices.WorkQueue": "延迟工作队列、tasklet 式延迟处理",
    "KernelServices.SoftIRQ": "下半部软中断",
    "KernelServices.TimerWheel": "定时器：timer list、timer wheel、hrtimer",
    "KernelServices.ModuleLoader": "可加载内核模块",
    "KernelServices.Randomness": "熵池、简单 PRNG",
    "KernelServices.PowerManagement": "电源管理：reboot/poweroff、挂起恢复、SBI shutdown",
    "KernelServices.KernelCommandLine": "内核命令行、bootargs 解析",
    # ── 安全与隔离 ──
    "SecurityAndIsolation.PrivilegeMode": "特权级切换：降权到用户态、U/S 模式分离、ring3/ring0",
    "SecurityAndIsolation.UserKernelIsolation": "用户/内核隔离：用户地址校验、PTE_U 位、拷贝校验",
    "SecurityAndIsolation.CapabilityOrACL": "权限模型：Unix uid/gid、capability、ACL",
    "SecurityAndIsolation.SeccompSandbox": "seccomp 系统调用过滤沙箱",
    "SecurityAndIsolation.KASLR": "内核地址空间随机化",
    "SecurityAndIsolation.WriteXorExecute": "W^X 策略、PTE 不可执行位",
    "SecurityAndIsolation.StackProtector": "栈金丝雀保护",
    "SecurityAndIsolation.ModuleSignature": "模块签名校验",
    # ── 调试与可观测性 ──
    "ObservabilityAndDebug.Logging": "内核 printf、日志缓冲、qemu 调试控制台",
    "ObservabilityAndDebug.Panic": "内核 panic、assert/bug trap",
    "ObservabilityAndDebug.Backtrace": "栈回溯：帧指针回溯、DWARF 展开",
    "ObservabilityAndDebug.Tracing": "跟踪：syscall trace、event trace、ftrace 式跟踪",
    "ObservabilityAndDebug.PerfCounter": "硬件性能计数器",
    "ObservabilityAndDebug.GDBStub": "GDB 远程调试 stub",
    "ObservabilityAndDebug.Sanitizer": "Sanitizer 运行时检测",
    # ── 虚拟化 ──
    "Virtualization.HypervisorMode": "Hypervisor：RISC-V H 扩展、KVM 式 vCPU、二级页表、trap-and-emulate",
    "Virtualization.VirtioGuest": "VirtIO guest 驱动、mmio/pci 传输、半虚拟时钟",
    "Virtualization.ContainerPrimitives": "容器原语：namespace+cgroup 组合、chroot 隔离",
    # ── 演进历史 ──
    "EvolutionHistory": "跨版本/分支演进历史（仅展示，不参与工作量）",
}


def node_title_zh(node_id: str) -> str:
    parts = node_id.split(".")
    # Try full id, then progressively shorter suffixes so two-segment keys like
    # "ConcreteFS.FAT32" resolve before falling back to the bare leaf segment.
    for start in range(len(parts)):
        key = ".".join(parts[start:])
        if key in TITLE_ZH:
            return TITLE_ZH[key]
    return parts[-1]


def node_title_en(node_id: str) -> str:
    parts = node_id.split(".")
    for start in range(len(parts)):
        key = ".".join(parts[start:])
        if key in TITLE_EN:
            return TITLE_EN[key]
    return parts[-1]


def node_scope(node_id: str) -> str:
    """节点工作范围一句话边界描述。叶子节点查 NODE_SCOPE；根节点返回空串。"""
    return NODE_SCOPE.get(node_id, "")


# TAG_ZH: 机制标签中文翻译，覆盖常用子系统。_tag() 优先查表，未命中回退到下划线替换。
# 仅作命名建议（统一术语），不分级、不判工作量。
TAG_ZH: dict[str, str] = {
    # ── 进程管理 ──
    "global_process_table": "全局进程表", "task_struct": "任务控制块",
    "trapframe_per_task": "每任务 trapframe", "kernel_stack_per_task": "每任务内核栈",
    "process_state_machine": "进程状态机", "single_thread_process": "单线程进程",
    "kernel_thread": "内核线程", "user_thread": "用户线程",
    "round_robin_scheduler": "轮转调度", "global_proc_table_scan": "全表扫描选进程",
    "cooperative_yield": "协作式 yield", "timer_preemption": "时钟抢占",
    "sleep_wakeup": "sleep/wakeup", "mlfq_scheduler": "多级反馈队列调度",
    "load_balancing": "负载均衡", "cpu_affinity": "CPU 亲和性",
    "async_coroutine_executor": "异步协程执行器", "single_scheduler_class": "单一调度类",
    "priority_scheduler": "优先级调度", "fair_scheduler": "公平调度",
    "deadline_scheduler": "截止期调度", "cfs_rbtree_vruntime": "CFS 红黑树 vruntime",
    "eevdf_scheduler": "EEVDF 调度", "o1_bitmap_scheduler": "O(1) 位图调度",
    "scheduler_class_interface": "调度类接口", "fork_copy_address_space": "fork 复制地址空间",
    "clone_task": "clone 任务", "copy_trapframe": "复制 trapframe", "allocproc": "分配进程",
    "elf_exec_loader": "ELF 装载器", "argument_stack_setup": "参数栈建立",
    "address_space_replace": "地址空间替换", "flat_binary_loader": "扁平二进制装载",
    "elf_interpreter_auxv": "ELF 解释器/auxv", "zombie_state": "僵尸态",
    "reparent_children": "子进程重定父", "wait_collect_exit_status": "wait 回收退出码",
    "kill_flag": "kill 标志", "zombie_wait": "僵尸 wait",
    "unix_like_signal": "Unix 式信号", "signal_mask": "信号掩码",
    "signal_action_table": "信号处理表", "pipe_ipc": "管道 IPC",
    "shared_memory_ipc": "共享内存 IPC", "message_queue_ipc": "消息队列 IPC",
    "linux_futex": "Linux futex", "futex": "futex",
    "pid_namespace": "PID 命名空间", "mount_namespace": "挂载命名空间",
    "network_namespace": "网络命名空间", "user_namespace": "用户命名空间",
    "namespace": "命名空间", "cgroup": "控制组",
    "resource_control_group": "资源控制组", "memcg": "内存 cgroup",
    # ── 内存管理 ──
    "free_list_physical_allocator": "空闲链表物理分配器", "buddy_allocator": "伙伴分配器",
    "bitmap_allocator": "位图分配器", "page_frame_allocator": "页帧分配器",
    "numa_aware_alloc": "NUMA 感知分配", "kmalloc_heap": "kmalloc 堆",
    "subpage_allocator": "子页分配器", "buddy_heap": "伙伴堆",
    "simple_bump_allocator": "简单 bump 分配器", "slab_allocator": "slab 分配器",
    "object_cache": "对象缓存", "slab": "slab",
    "sv39_three_level_page_table": "sv39 三级页表", "x86_64_four_level_page_table": "x86_64 四级页表",
    "walk_map_unmap": "walk/map/unmap", "pte_flag_protection": "PTE 权限位",
    "satp_switch": "satp 切换", "tlb_flush": "TLB 刷新",
    "iterative_hint_mapping": "迭代式映射", "kernel_direct_map": "内核直接映射",
    "kernel_pagetable": "内核页表", "high_half_kernel": "高半区内核",
    "per_process_pagetable": "每进程页表", "uvmcopy_fork": "fork 地址空间复制",
    "lazy_user_allocation": "用户懒分配", "lazy_paging_vma": "懒分页 VMA",
    "eager_page_copy": "立即页复制", "posix_mmap_syscall": "POSIX mmap 系统调用",
    "mmap_vma": "mmap VMA", "file_backed_mapping": "文件映射",
    "anonymous_mapping": "匿名映射", "munmap": "munmap", "mmap": "mmap",
    "lazy_page_fault_allocation": "缺页懒分配", "copy_on_write_fault": "写时复制缺页",
    "mmap_fault_resolution": "mmap 缺页填充", "fault_kill_process": "缺页杀进程",
    "cow_btree_refcount": "COW B 树引用计数", "cow_arc_refcount": "COW Arc 引用计数",
    "reverse_mapping_rmap": "反向映射 rmap", "copyin_copyout": "copyin/copyout",
    "copyinstr": "copyinstr", "user_pointer_walkaddr": "用户指针 walkaddr",
    "copy_user_validation": "用户拷贝校验", "page_cache": "页缓存",
    "file_page_cache": "文件页缓存", "unified_page_cache": "统一页缓存",
    "transparent_huge_page": "透明大页", "page cache": "页缓存",
    "swap_file_or_partition": "交换文件/分区", "swap_file": "交换文件",
    "swap_partition": "交换分区", "page_reclaim_kswapd": "页回收 kswapd",
    "oom_killer": "OOM killer", "swap": "交换",
    "sfence_vma_flush": "sfence.vma 刷新", "tlb_shootdown": "TLB shootdown",
    # ── 文件系统 ──
    "vfs_layer": "VFS 层", "file_table_abstraction": "文件表抽象",
    "vnode_like_layer": "vnode 式层", "mount_dispatch": "挂载分派",
    "per_process_fd_table": "每进程 fd 表", "fdalloc": "fdalloc",
    "dup_close_refcount": "dup/close 引用计数", "socket_fd_integration": "socket fd 集成",
    "inode_cache": "inode 缓存", "dentry_cache": "dentry 缓存",
    "directory_entry_lookup": "目录项查找", "namei_path_resolution": "namei 路径解析",
    "inode_locking": "inode 锁", "fat32_cluster_chain": "FAT32 簇链",
    "fat_directory_entry": "FAT 目录项", "fat_table_cache": "FAT 表缓存",
    "ext4_superblock": "ext4 超级块", "ext4_extent_tree": "ext4 extent 树",
    "ext4_journal": "ext4 journal", "ext4": "ext4",
    "memory_backed_fs": "内存后端 fs", "rootfs_image": "rootfs 镜像",
    "device_inode": "设备 inode", "major_minor_dispatch": "major/minor 分派",
    "device_switch": "devsw 设备开关", "devfs_bypass_interceptor": "devfs 旁路拦截",
    "pipe_ring_buffer": "管道环形缓冲", "procfs_virtual_file": "procfs 虚拟文件",
    "buffer_cache": "缓冲缓存", "block_cache_hash": "块缓存哈希",
    "block_lru_cache": "块 LRU 缓存", "write_ahead_log": "预写日志 WAL",
    "transaction_log": "事务日志", "block_device_abstraction": "块设备抽象",
    "bio_request_queue": "bio 请求队列", "buffered_block_io": "缓冲块 IO",
    "page_cache_backed_fs": "页缓存后端 fs", "buffer_cache_only": "仅缓冲缓存",
    "page_cache_integration": "页缓存集成",
    # ── 设备驱动 ──
    "flat_driver_table": "扁平驱动表", "linux_driver_model": "Linux 驱动模型",
    "platform_device_table": "平台设备表", "plic_interrupt_controller": "PLIC 中断控制器",
    "apic_interrupt_controller": "APIC 中断控制器", "irq_dispatch": "IRQ 分派",
    "device_interrupt_ack": "设备中断应答", "uart_mmio_driver": "UART MMIO 驱动",
    "console_device": "console 设备", "interrupt_driven_console": "中断驱动控制台",
    "virtqueue_descriptor_ring": "virtqueue 描述符环", "virtio_mmio": "virtio mmio",
    "virtio_pci_transport": "virtio pci 传输", "virtio_disk_driver": "virtio 磁盘驱动",
    "virtio_block_device": "virtio 块设备", "pci_bus_probe": "PCI 总线探测", "pci": "PCI",
    "device_tree_probe": "设备树探测", "dma_controller": "DMA 控制器",
    "bounce_buffer": "bounce buffer", "framebuffer_driver": "framebuffer 驱动",
    "gpu_mmio_driver": "GPU MMIO 驱动", "keyboard_driver": "键盘驱动",
    "mouse_driver": "鼠标驱动", "touch_input_driver": "触摸输入驱动",
    "timer_device": "定时器设备", "clock_event_device": "时钟事件设备",
    "sd_card_block_device": "SD 卡块设备", "spi_sd_card_driver": "SPI SD 卡驱动",
    "pio_block_transfer": "PIO 块传输",
    # ── 网络 ──
    "bsd_socket_api": "BSD socket API", "raw_socket": "raw socket",
    "tcp_state_machine": "TCP 状态机", "udp_datagram": "UDP 数据报",
    "port_demux": "端口解复用", "ethernet_driver": "以太网驱动",
    "virtio_net_driver": "virtio-net 驱动", "mbuf_packet_buffer": "mbuf 包缓冲",
    "skb_packet_buffer": "skb 包缓冲", "packet_filter_hook": "包过滤钩子",
    "netfilter": "netfilter", "unix_domain_socket": "Unix 域套接字",
    "AF_UNIX": "AF_UNIX", "loopback_device": "回环设备",
    "loopback_socket_forward": "回环 socket 转发",
    # ── 同步机制 ──
    "test_and_set_spinlock": "test-and-set 自旋锁", "interrupt_disable_locking": "关中断加锁",
    "ticket_spinlock": "ticket 自旋锁", "mcs_qspinlock": "MCS qspinlock",
    "lock_owner_debug": "锁持有者调试", "lock_order_check": "锁序检查",
    "lockdep_deadlock_detect": "lockdep 死锁检测", "blocking_mutex": "阻塞互斥锁",
    "sleeplock_mutex": "sleeplock 互斥锁", "counting_semaphore": "计数信号量",
    "sleep_lock": "睡眠锁", "blocking_lock": "阻塞锁", "wait_queue": "等待队列",
    "sleep_wakeup_channel": "sleep/wakeup channel", "condition_variable": "条件变量",
    "read_copy_update": "RCU 读拷贝更新", "RCU": "RCU",
    "atomic_refcount": "原子引用计数", "lock_protected_refcount": "锁保护引用计数",
    "read_write_lock": "读写锁", "seqlock": "seqlock", "percpu_counter": "per-cpu 计数器",
}


def _tag(tag: str, role: str = "primary", category: str = "mechanism", aliases: list[str] | None = None, zh: str | None = None, en: str | None = None) -> dict[str, Any]:
    title = tag.replace("_", " ")
    zh_title = zh or TAG_ZH.get(tag) or title
    return {
        "tag": tag,
        "compare_role": role,
        "category": category,
        "aliases": aliases or [],
        "title_zh": zh_title,
        "title_en": en or title,
        "description_zh": zh_title,
        "description_en": en or title,
    }


def _tags(primary: list[str], display: list[str] | None = None, weak: list[str] | None = None, category: str = "mechanism") -> list[dict[str, Any]]:
    return [_tag(x, "primary", category) for x in primary] + [_tag(x, "display", category) for x in (display or [])] + [_tag(x, "weak_hint", category) for x in (weak or [])]


VOCAB_BY_NODE: dict[str, dict[str, Any]] = {
    "Metadata": {"mechanisms": _tags(["monolithic_kernel", "microkernel", "exokernel_like", "riscv64", "loongarch64", "x86_64", "aarch64", "qemu_virt", "k210_board", "sbi_boot", "rustsbi_boot"], ["language_profile", "platform_profile"])},
    "BuildAndConfig.MakeTargets": {"mechanisms": _tags(["make_build", "qemu_run_target", "fs_image_build"], ["kernel_cpp_flags"])},
    "BuildAndConfig.LinkerScript": {"mechanisms": _tags(["linker_script_layout", "entry_symbol", "section_layout"], ["platform_specific_linker_script"])},
    "BuildAndConfig.Toolchain": {"mechanisms": _tags(["cross_compile_toolchain", "riscv_gcc_toolchain", "llvm_clang_toolchain"], ["objdump_toolchain", "gdb_toolchain"])},
    "BuildAndConfig.KernelConfig": {"mechanisms": _tags(["compile_time_platform_config", "board_selection"], ["kernel_cpp_flags"])},
    "BuildAndConfig.CargoFeatures": {"mechanisms": _tags(["cargo_build"], ["cargo_features", "rust_toolchain"])},
    "BuildAndConfig.Initramfs": {"mechanisms": _tags(["initramfs_packaging", "rootfs_image"], ["fs_image_build"])},
    "ArchitectureLayer.Boot": {"mechanisms": _tags(["riscv_entry_assembly", "x86_boot_entry", "aarch64_el_entry", "sbi_handoff", "rustsbi_handoff", "multiboot_handoff", "qemu_direct_kernel", "kernel_main", "polyhal_dual_arch"], ["linker_script_entry"], ["early_console_bootlog"])},
    "ArchitectureLayer.EarlyConsole": {"mechanisms": _tags(["early_console_bootlog", "uart_early_putchar"], ["kernel_printf"])},
    "ArchitectureLayer.TrapException": {"mechanisms": _tags(["trap_vector", "riscv_trap_vector", "user_kernel_trap_split", "trapframe_save_restore", "scause_dispatch", "page_fault_detection"])},
    "ArchitectureLayer.SyscallEntry": {"mechanisms": _tags(["syscall_number_dispatch", "syscall_table_dispatch", "syscall_table", "trapframe_argument_abi", "syscall_stub_generated"])},
    "ArchitectureLayer.InterruptTimer": {"mechanisms": _tags(["sbi_timer", "timer_tick", "clock_interrupt", "preemptive_yield_on_timer", "timer_interrupt"])},
    "ArchitectureLayer.ContextSwitch": {"mechanisms": _tags(["assembly_context_switch", "callee_saved_context", "scheduler_proc_switch"])},
    "ArchitectureLayer.SMPBringup": {"mechanisms": _tags(["smp_bringup", "secondary_hart_start", "ipi_startup"], ["single_core_only"])},
    "ArchitectureLayer.PerCpuState": {"mechanisms": _tags(["per_cpu_state", "per_cpu_scheduler_state", "per_cpu_kernel_stack"])},
    "ProcessManagement.TaskStruct": {"mechanisms": _tags(["global_process_table", "task_struct", "trapframe_per_task", "kernel_stack_per_task", "process_state_machine"])},
    "ProcessManagement.ThreadModel": {"mechanisms": _tags(["single_thread_process", "kernel_thread", "user_thread"])},
    "ProcessManagement.Scheduler": {"mechanisms": _tags(["round_robin_scheduler", "global_proc_table_scan", "cooperative_yield", "timer_preemption", "sleep_wakeup", "mlfq_scheduler", "load_balancing", "cpu_affinity", "async_coroutine_executor"])},
    "ProcessManagement.SchedulerClass": {"mechanisms": _tags(["single_scheduler_class", "priority_scheduler", "fair_scheduler", "deadline_scheduler", "cfs_rbtree_vruntime", "eevdf_scheduler", "o1_bitmap_scheduler"], ["scheduler_class_interface"])},
    "ProcessManagement.ForkClone": {"mechanisms": _tags(["fork_copy_address_space", "clone_task", "copy_trapframe", "allocproc"])},
    "ProcessManagement.Exec": {"mechanisms": _tags(["elf_exec_loader", "argument_stack_setup", "address_space_replace", "flat_binary_loader", "elf_interpreter_auxv"])},
    "ProcessManagement.WaitExit": {"mechanisms": _tags(["zombie_state", "reparent_children", "wait_collect_exit_status", "kill_flag", "zombie_wait"])},
    "ProcessManagement.Signal": {"mechanisms": _tags(["unix_like_signal", "signal_mask", "signal_action_table"], ["kill_flag"])},
    "ProcessManagement.IPC": {"mechanisms": _tags(["pipe_ipc", "shared_memory_ipc", "message_queue_ipc"])},
    "ProcessManagement.Futex": {"mechanisms": _tags(["linux_futex"], [], ["futex"])},
    "ProcessManagement.Namespace": {"mechanisms": _tags(["pid_namespace", "mount_namespace", "network_namespace", "user_namespace", "namespace"], [], ["namespace"])},
    "ProcessManagement.Cgroup": {"mechanisms": _tags(["cgroup", "resource_control_group", "memcg"], [], ["cgroup"])},
    "MemoryManagement.PhysicalAllocator": {"mechanisms": _tags(["free_list_physical_allocator", "buddy_allocator", "bitmap_allocator", "page_frame_allocator"], ["numa_aware_alloc"])},
    "MemoryManagement.KernelHeap": {"mechanisms": _tags(["kmalloc_heap", "subpage_allocator", "buddy_heap"], ["simple_bump_allocator"])},
    "MemoryManagement.SlabObjectCache": {"mechanisms": _tags(["slab_allocator", "object_cache"], [], ["slab"])},
    "MemoryManagement.PageTable": {"mechanisms": _tags(["sv39_three_level_page_table", "x86_64_four_level_page_table", "walk_map_unmap", "pte_flag_protection", "satp_switch", "tlb_flush", "iterative_hint_mapping"])},
    "MemoryManagement.KernelAddressSpace": {"mechanisms": _tags(["kernel_direct_map", "kernel_pagetable", "high_half_kernel"])},
    "MemoryManagement.UserAddressSpace": {"mechanisms": _tags(["per_process_pagetable", "uvmcopy_fork", "address_space_replace", "lazy_user_allocation", "lazy_paging_vma", "eager_page_copy"])},
    "MemoryManagement.Mmap": {"mechanisms": _tags(["posix_mmap_syscall", "mmap_vma", "file_backed_mapping", "anonymous_mapping", "munmap"], [], ["mmap"])},
    "MemoryManagement.PageFault": {"mechanisms": _tags(["lazy_page_fault_allocation", "copy_on_write_fault", "mmap_fault_resolution", "fault_kill_process", "cow_btree_refcount", "cow_arc_refcount"], ["reverse_mapping_rmap"])},
    "MemoryManagement.CopyUser": {"mechanisms": _tags(["copyin_copyout", "copyinstr", "user_pointer_walkaddr", "copy_user_validation"])},
    "MemoryManagement.PageCache": {"mechanisms": _tags(["page_cache", "file_page_cache", "unified_page_cache", "transparent_huge_page"], [], ["page cache"])},
    "MemoryManagement.Swap": {"mechanisms": _tags(["swap_file_or_partition", "swap_file", "swap_partition", "page_reclaim_kswapd", "oom_killer"], [], ["swap"])},
    "MemoryManagement.TLBManagement": {"mechanisms": _tags(["sfence_vma_flush", "tlb_flush", "tlb_shootdown"])},
    "FileSystem.VFS": {"mechanisms": _tags(["vfs_layer", "file_table_abstraction", "vnode_like_layer", "mount_dispatch"])},
    "FileSystem.FileDescriptorTable": {"mechanisms": _tags(["per_process_fd_table", "fdalloc", "dup_close_refcount", "socket_fd_integration"])},
    "FileSystem.InodeDentry": {"mechanisms": _tags(["inode_cache", "dentry_cache", "directory_entry_lookup", "namei_path_resolution", "inode_locking"])},
    "FileSystem.ConcreteFS.FAT32": {"mechanisms": _tags(["fat32_cluster_chain", "fat_directory_entry", "fat_table_cache"])},
    "FileSystem.ConcreteFS.ext4": {"mechanisms": _tags(["ext4_superblock", "ext4_extent_tree", "ext4_journal"], [], ["ext4"])},
    "FileSystem.ConcreteFS.ramfs": {"mechanisms": _tags(["memory_backed_fs", "rootfs_image"])},
    "FileSystem.ConcreteFS.devfs": {"mechanisms": _tags(["device_inode", "major_minor_dispatch", "device_switch", "devfs_bypass_interceptor"])},
    "FileSystem.PipeOrProcFS": {"mechanisms": _tags(["pipe_ring_buffer", "procfs_virtual_file"])},
    "FileSystem.BlockCache": {"mechanisms": _tags(["buffer_cache", "block_cache_hash", "block_lru_cache"])},
    "FileSystem.JournalOrLog": {"mechanisms": _tags(["write_ahead_log", "transaction_log", "ext4_journal"])},
    "FileSystem.BlockDevice": {"mechanisms": _tags(["block_device_abstraction", "bio_request_queue", "buffered_block_io"])},
    "FileSystem.PageCacheIntegration": {"mechanisms": _tags(["page_cache_backed_fs", "buffer_cache_only"], [], ["page_cache_integration"])},
    "DeviceDriver.DriverModel": {"mechanisms": _tags(["flat_driver_table", "linux_driver_model", "platform_device_table"])},
    "DeviceDriver.InterruptController": {"mechanisms": _tags(["plic_interrupt_controller", "apic_interrupt_controller", "irq_dispatch", "device_interrupt_ack"])},
    "DeviceDriver.ConsoleUART": {"mechanisms": _tags(["uart_mmio_driver", "console_device", "interrupt_driven_console"])},
    "DeviceDriver.VirtIO": {"mechanisms": _tags(["virtqueue_descriptor_ring", "virtio_mmio", "virtio_pci_transport", "virtio_disk_driver", "virtio_block_device"])},
    "DeviceDriver.PCI": {"mechanisms": _tags(["pci_bus_probe"], [], ["pci"])},
    "DeviceDriver.PlatformBus": {"mechanisms": _tags(["platform_device_table", "device_tree_probe"])},
    "DeviceDriver.DMA": {"mechanisms": _tags(["dma_controller", "bounce_buffer"])},
    "DeviceDriver.GPUDisplay": {"mechanisms": _tags(["framebuffer_driver", "gpu_mmio_driver"])},
    "DeviceDriver.InputDevice": {"mechanisms": _tags(["keyboard_driver", "mouse_driver", "touch_input_driver"])},
    "DeviceDriver.ClockTimerDevice": {"mechanisms": _tags(["timer_device", "clock_event_device"])},
    "DeviceDriver.SDCard": {"mechanisms": _tags(["sd_card_block_device", "spi_sd_card_driver", "pio_block_transfer"])},
    "DeviceDriver.BlockDevice": {"mechanisms": _tags(["virtio_block_device", "sd_card_block_device", "buffered_block_io"])},
    "Network.Socket": {"mechanisms": _tags(["bsd_socket_api", "socket_fd_integration", "raw_socket"])},
    "Network.TCPUDP": {"mechanisms": _tags(["tcp_state_machine", "udp_datagram", "port_demux"])},
    "Network.NetDevice": {"mechanisms": _tags(["ethernet_driver", "virtio_net_driver"])},
    "Network.PacketBuffer": {"mechanisms": _tags(["mbuf_packet_buffer", "skb_packet_buffer"])},
    "Network.Netfilter": {"mechanisms": _tags(["packet_filter_hook"], [], ["netfilter"])},
    "Network.UnixDomainSocket": {"mechanisms": _tags(["unix_domain_socket"], [], ["AF_UNIX"])},
    "Network.Loopback": {"mechanisms": _tags(["loopback_device", "loopback_socket_forward"])},
    "Synchronization.SpinLock": {"mechanisms": _tags(["test_and_set_spinlock", "interrupt_disable_locking", "ticket_spinlock", "mcs_qspinlock"], ["lock_owner_debug", "lock_order_check", "lockdep_deadlock_detect"])},
    "Synchronization.Mutex": {"mechanisms": _tags(["blocking_mutex", "sleeplock_mutex"])},
    "Synchronization.Semaphore": {"mechanisms": _tags(["counting_semaphore"])},
    "Synchronization.SleepLock": {"mechanisms": _tags(["sleep_lock", "blocking_lock"])},
    "Synchronization.WaitQueue": {"mechanisms": _tags(["wait_queue", "sleep_wakeup_channel", "condition_variable"])},
    "Synchronization.RCU": {"mechanisms": _tags(["read_copy_update"], [], ["RCU"])},
    "Synchronization.AtomicRefCount": {"mechanisms": _tags(["atomic_refcount", "lock_protected_refcount"])},
    "Synchronization.ReadWriteLock": {"mechanisms": _tags(["read_write_lock", "seqlock"], ["percpu_counter"])},
    "UserLibAndTests.LibcOrSyscallWrapper": {"mechanisms": _tags(["user_syscall_stubs", "minimal_libc", "syscall_wrapper"])},
    "UserLibAndTests.Shell": {"mechanisms": _tags(["user_shell", "xv6_shell"], ["command_parser"])},
    "UserLibAndTests.InitProc": {"mechanisms": _tags(["initcode_first_process", "user_init_program"])},
    "UserLibAndTests.TestPrograms": {"mechanisms": _tags(["user_test_programs"], ["usertests", "filesystem_tests", "mmap_tests"])},
    "UserLibAndTests.ELFABI": {"mechanisms": _tags(["elf_binary_abi"])},
    "UserLibAndTests.PosixCompat": {"mechanisms": _tags(["posix_compat_layer"])},
    "UserLibAndTests.DynamicLinker": {"mechanisms": _tags(["dynamic_linker_abi"], [], ["dynamic linker"])},
    "UserLibAndTests.VDSO": {"mechanisms": _tags(["vdso_page"], [], ["vdso"])},
    "KernelServices.WorkQueue": {"mechanisms": _tags(["deferred_work_queue", "tasklet_like_deferred_work"], [], ["workqueue"])},
    "KernelServices.SoftIRQ": {"mechanisms": _tags(["bottom_half_softirq"], [], ["softirq"])},
    "KernelServices.TimerWheel": {"mechanisms": _tags(["timer_list", "timer_wheel", "hrtimer"])},
    "KernelServices.ModuleLoader": {"mechanisms": _tags(["loadable_kernel_module"], ["static_kernel_only"], ["module_loader"])},
    "KernelServices.Randomness": {"mechanisms": _tags(["entropy_pool", "simple_prng"])},
    "KernelServices.PowerManagement": {"mechanisms": _tags(["reboot_poweroff", "suspend_resume", "sbi_shutdown"])},
    "KernelServices.KernelCommandLine": {"mechanisms": _tags(["kernel_command_line"], [], ["bootargs"])},
    "SecurityAndIsolation.PrivilegeMode": {"mechanisms": _tags(["privilege_drop_to_user", "riscv_user_supervisor_split", "x86_ring3_ring0_split"])},
    "SecurityAndIsolation.UserKernelIsolation": {"mechanisms": _tags(["user_kernel_address_check", "pte_user_bit", "copy_user_validation"])},
    "SecurityAndIsolation.CapabilityOrACL": {"mechanisms": _tags(["unix_uid_gid", "capability_model", "acl"])},
    "SecurityAndIsolation.SeccompSandbox": {"mechanisms": _tags(["seccomp_filter"], [], ["seccomp"])},
    "SecurityAndIsolation.KASLR": {"mechanisms": _tags(["kernel_address_randomization"], [], ["kaslr"])},
    "SecurityAndIsolation.WriteXorExecute": {"mechanisms": _tags(["write_xor_execute_policy", "pte_execute_disable"])},
    "SecurityAndIsolation.StackProtector": {"mechanisms": _tags(["stack_canary"], [], ["stack protector"])},
    "SecurityAndIsolation.ModuleSignature": {"mechanisms": _tags(["signed_module_check"], [], ["module signature"])},
    "ObservabilityAndDebug.Logging": {"mechanisms": _tags(["kernel_printf", "log_buffer", "qemu_debug_console"])},
    "ObservabilityAndDebug.Panic": {"mechanisms": _tags(["kernel_panic", "assert_bug_trap"])},
    "ObservabilityAndDebug.Backtrace": {"mechanisms": _tags(["frame_pointer_backtrace", "dwarf_unwind_backtrace"])},
    "ObservabilityAndDebug.Tracing": {"mechanisms": _tags(["syscall_trace", "event_trace", "ftrace_like_tracing"])},
    "ObservabilityAndDebug.PerfCounter": {"mechanisms": _tags(["hardware_perf_counter"])},
    "ObservabilityAndDebug.GDBStub": {"mechanisms": _tags(["gdb_remote_stub"])},
    "ObservabilityAndDebug.Sanitizer": {"mechanisms": _tags(["sanitizer_runtime"])},
    "Virtualization.HypervisorMode": {"mechanisms": _tags(["riscv_h_extension", "kvm_like_vcpu", "second_stage_page_table", "trap_and_emulate"])},
    "Virtualization.VirtioGuest": {"mechanisms": _tags(["virtio_guest_driver", "virtio_mmio_transport", "virtio_pci_transport", "paravirtual_clock"])},
    "Virtualization.ContainerPrimitives": {"mechanisms": _tags(["namespace_cgroup_container", "pid_namespace", "mount_namespace", "chroot_isolation"], ["user_mode_linux_like"], ["qemu_only_platform"])},
    "EvolutionHistory": {"mechanisms": _tags([], ["display_only_history"])},
}


EXTRA_NODE_SPECS: dict[str, dict[str, Any]] = {
    "BuildAndConfig.MakeTargets": {"symbols": [], "patterns": ["qemu-system", "fs.img", "platform\\s*:=", "^qemu:", "^kernel/kernel"]},
    "BuildAndConfig.LinkerScript": {"symbols": [], "patterns": ["ENTRY\\(", "SECTIONS", "kernel\\.ld", "k210\\.ld", "qemu\\.ld"]},
    "BuildAndConfig.Toolchain": {"symbols": [], "patterns": ["riscv64-unknown-elf", "qemu-system-riscv64", "OBJDUMP", "GDB", "clang", "llvm"]},
    "BuildAndConfig.KernelConfig": {"symbols": [], "patterns": ["platform\\s*:=", "CPUS\\s*:=", "K210", "QEMU", "CPPFLAGS", "CFLAGS"]},
    "BuildAndConfig.CargoFeatures": {"symbols": [], "patterns": ["\\[features\\]", "rust-toolchain", "Cargo\\.toml"]},
    "ArchitectureLayer.Boot": {"symbols": ["entry", "_entry", "start", "main", "timerinit"], "patterns": ["entry_k210", "RustSBI", "sbi-k210", "kernelvec", "ENTRY\\("]},
    "DeviceDriver.ConsoleUART": {"symbols": ["uartinit", "uartputc", "uartgetc", "consoleinit", "consoleread", "consolewrite"], "patterns": ["UART", "console"]},
    "MemoryManagement.PhysicalAllocator": {"symbols": ["kinit", "kalloc", "kfree", "freerange"], "patterns": ["freelist", "PGSIZE", "struct run"]},
    "MemoryManagement.PageTable": {"symbols": ["walk", "mappages", "uvmunmap", "kvminit", "kvminithart"], "patterns": ["PTE_V", "PTE_U", "SATP", "sfence\\.vma", "Sv39"]},
    "MemoryManagement.KernelAddressSpace": {"symbols": ["kvmmake", "kvminit", "kvmmap"], "patterns": ["kernel_pagetable", "direct map", "KERNBASE"]},
    "MemoryManagement.UserAddressSpace": {"symbols": ["uvmcreate", "uvmalloc", "uvmdealloc", "uvmcopy", "proc_pagetable"], "patterns": ["pagetable", "sz"]},
    "MemoryManagement.CopyUser": {"symbols": ["copyin", "copyout", "copyinstr", "walkaddr"], "patterns": ["copyin", "copyout", "PTE_U"]},
    "ArchitectureLayer.TrapException": {"symbols": ["usertrap", "kerneltrap", "trapinit", "trapinithart"], "patterns": ["scause", "stvec", "sepc"]},
    "ArchitectureLayer.SyscallEntry": {"symbols": ["syscall", "argraw", "argint", "argaddr"], "patterns": ["syscalls\\[", "SYS_"]},
    "ArchitectureLayer.InterruptTimer": {"symbols": ["clockintr", "timerinit", "devintr"], "patterns": ["mtimecmp", "timer"]},
    "ProcessManagement.TaskStruct": {"symbols": ["proc", "allocproc", "myproc", "userinit"], "patterns": ["struct proc", "enum procstate"]},
    "ArchitectureLayer.ContextSwitch": {"symbols": ["swtch", "sched", "yield"], "patterns": ["swtch", "context"]},
    "ProcessManagement.Scheduler": {"symbols": ["scheduler", "sched", "yield", "sleep", "wakeup"], "patterns": ["RUNNABLE", "RUNNING"]},
    "ProcessManagement.ForkClone": {"symbols": ["fork", "clone", "uvmcopy"], "patterns": ["fork", "clone"]},
    "ProcessManagement.Exec": {"symbols": ["exec", "loadseg"], "patterns": ["ELF", "argv"]},
    "ProcessManagement.WaitExit": {"symbols": ["exit", "wait", "kill"], "patterns": ["ZOMBIE", "reparent"]},
    "ProcessManagement.Signal": {"symbols": ["signal", "sys_signal", "sigreturn", "kill"], "patterns": ["SIG", "signal"]},
    "ProcessManagement.IPC": {"symbols": ["pipe", "piperead", "pipewrite"], "patterns": ["pipe", "IPC"]},
    "Synchronization.SpinLock": {"symbols": ["acquire", "release", "initlock"], "patterns": ["__sync_lock_test_and_set", "push_off"]},
    "Synchronization.WaitQueue": {"symbols": ["sleep", "wakeup"], "patterns": ["chan", "wait"]},
    "Synchronization.SleepLock": {"symbols": ["acquiresleep", "releasesleep", "initsleeplock"], "patterns": ["sleeplock"]},
    "FileSystem.FileDescriptorTable": {"symbols": ["filealloc", "filedup", "fileclose", "fdalloc"], "patterns": ["ofile", "NOFILE"]},
    "FileSystem.VFS": {"symbols": ["fileread", "filewrite", "fileopen"], "patterns": ["struct file", "FD_INODE", "FD_DEVICE"]},
    "FileSystem.InodeDentry": {"symbols": ["namei", "dirlookup", "ilock", "iget", "readi", "writei"], "patterns": ["struct inode", "namei"]},
    "FileSystem.PipeOrProcFS": {"symbols": ["pipealloc", "piperead", "pipewrite"], "patterns": ["pipe", "procfs"]},
    "FileSystem.BlockCache": {"symbols": ["bget", "bread", "bwrite", "brelse"], "patterns": ["bcache", "buf"]},
    "FileSystem.JournalOrLog": {"symbols": ["begin_op", "end_op", "log_write", "commit"], "patterns": ["struct log", "write-ahead"]},
    "FileSystem.BlockDevice": {"symbols": ["virtio_disk_rw", "iderw", "sd_read"], "patterns": ["block", "disk"]},
    "FileSystem.ConcreteFS.FAT32": {"symbols": ["fat32", "fat", "cluster"], "patterns": ["FAT32", "cluster"]},
    "FileSystem.ConcreteFS.ext4": {"symbols": ["ext4"], "patterns": ["ext4", "extent"]},
    "FileSystem.ConcreteFS.ramfs": {"symbols": ["ramfs", "rootfs"], "patterns": ["ramfs", "rootfs"]},
    "FileSystem.ConcreteFS.devfs": {"symbols": ["devsw", "mknod"], "patterns": ["devsw", "major"]},
    "DeviceDriver.VirtIO": {"symbols": ["virtio_disk_init", "virtio_disk_rw", "virtio_disk_intr"], "patterns": ["VIRTIO", "virtqueue"]},
    "DeviceDriver.InterruptController": {"symbols": ["plicinit", "plicinithart", "plic_claim", "plic_complete"], "patterns": ["PLIC", "IRQ"]},
    "DeviceDriver.SDCard": {"symbols": ["sd_init", "sd_read", "sd_write"], "patterns": ["SD", "sdcard", "spi"]},
    "Network.Socket": {"symbols": ["socket", "sys_socket", "sockalloc"], "patterns": ["AF_INET", "SOCK"]},
    "Network.TCPUDP": {"symbols": ["tcp", "udp"], "patterns": ["TCP", "UDP"]},
    "Network.NetDevice": {"symbols": ["netdev", "ethernet", "virtio_net"], "patterns": ["ethernet", "virtio_net"]},
    "Network.PacketBuffer": {"symbols": ["mbuf", "skb"], "patterns": ["mbuf", "skb", "packet"]},
    "ObservabilityAndDebug.Logging": {"symbols": ["printf", "cprintf", "printk"], "patterns": ["printf", "printk"]},
    "ObservabilityAndDebug.Panic": {"symbols": ["panic"], "patterns": ["panic"]},
    "ObservabilityAndDebug.Backtrace": {"symbols": ["backtrace"], "patterns": ["backtrace", "stack trace"]},
    "UserLibAndTests.ELFABI": {"symbols": ["exec", "loadseg"], "patterns": ["ELF", "elfhdr"]},
}


def apply_kernel_taxonomy(concepts: dict[str, Any], vocab: dict[str, Any], node_specs: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    concepts = deepcopy(concepts)
    vocab = deepcopy(vocab)
    node_specs = deepcopy(node_specs)
    _reject_unknown_nodes("concepts", concepts)
    _reject_unknown_nodes("vocab", {k: v for k, v in vocab.items() if k not in {"global", "negative_features", "schema_version"}})
    for node_id in ANALYSIS_ORDER_V2:
        if node_id in EXTRA_NODE_SPECS:
            base = node_specs.get(node_id, {})
            merged = deepcopy(base)
            for key, value in EXTRA_NODE_SPECS[node_id].items():
                if isinstance(value, list):
                    merged[key] = list(dict.fromkeys([*merged.get(key, []), *value]))
                else:
                    merged[key] = value
            node_specs[node_id] = merged
        concepts[node_id] = _merge_concept(node_id, concepts.get(node_id))
        loaded_vocab = vocab.get(node_id)
        if loaded_vocab:
            vocab[node_id] = _normalize_vocab_node(loaded_vocab, node_id)
        else:
            vocab[node_id] = deepcopy(VOCAB_BY_NODE.get(node_id, {"mechanisms": _tags([])}))
        vocab[node_id]["navigation_hints"] = _navigation_hints(node_id, node_specs.get(node_id, {}), vocab[node_id])
    _validate_taxonomy(concepts, vocab)
    return concepts, vocab, node_specs


def _reject_unknown_nodes(label: str, data: dict[str, Any]) -> None:
    unknown = sorted(k for k in data if "." in k and k not in VALID_NODE_IDS)
    if unknown:
        raise ValueError(f"{label} contains node ids outside current KernelProject tree: {unknown[:20]}")


def _merge_concept(node_id: str, loaded: Any) -> dict[str, Any]:
    base = _default_concept(node_id)
    if isinstance(loaded, dict):
        for key, value in loaded.items():
            if value:
                base[key] = value
    base.setdefault("title_zh", node_title_zh(node_id))
    base.setdefault("title_en", node_title_en(node_id))
    return base


def _normalize_vocab_node(raw: Any, node_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    mechanisms = raw.get("mechanisms", [])
    out = {k: deepcopy(v) for k, v in raw.items() if k != "mechanisms"}
    out["mechanisms"] = [_normalize_tag(x) for x in mechanisms]
    if not out["mechanisms"]:
        out["mechanisms"] = deepcopy(VOCAB_BY_NODE.get(node_id, {"mechanisms": []})["mechanisms"])
    return out


def _normalize_tag(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return _tag(item)
    if not isinstance(item, dict):
        return _tag(str(item))
    tag = str(item.get("tag") or "").strip()
    if not tag:
        tag = str(item.get("name") or "").strip()
    rec = _tag(tag)
    rec.update({k: deepcopy(v) for k, v in item.items() if v is not None})
    rec["tag"] = tag
    rec["compare_role"] = rec.get("compare_role") if rec.get("compare_role") in {"primary", "display", "weak_hint"} else "primary"
    rec["category"] = rec.get("category") or "mechanism"
    rec["aliases"] = rec.get("aliases") if isinstance(rec.get("aliases"), list) else []
    return rec


def _navigation_hints(node_id: str, specs: dict[str, Any], vocab: dict[str, Any]) -> dict[str, Any]:
    weak = [x["tag"] for x in vocab.get("mechanisms", []) if x.get("compare_role") == "weak_hint"]
    aliases = [alias for x in vocab.get("mechanisms", []) for alias in x.get("aliases", [])]
    return {
        "warning": "这些只是导航提示，不是证据；claim 必须引用工具生成的 evidence_id。",
        "possible_terms": list(dict.fromkeys([*specs.get("patterns", []), *weak, *aliases]))[:15],
        "possible_entry_symbols": list(dict.fromkeys(specs.get("symbols", [])))[:12],
    }


def _validate_taxonomy(concepts: dict[str, Any], vocab: dict[str, Any]) -> None:
    missing_concepts = sorted(node for node in ANALYSIS_ORDER_V2 if node not in concepts)
    missing_vocab = sorted(node for node in ANALYSIS_ORDER_V2 if node not in vocab)
    if missing_concepts or missing_vocab:
        raise ValueError(f"taxonomy incomplete: missing_concepts={missing_concepts[:10]}, missing_vocab={missing_vocab[:10]}")
    for node_id in ANALYSIS_ORDER_V2:
        for item in vocab[node_id].get("mechanisms", []):
            if item.get("compare_role") not in {"primary", "display", "weak_hint"}:
                raise ValueError(f"{node_id} tag {item.get('tag')} has invalid compare_role")
            for field in ("title_zh", "title_en", "description_zh", "description_en"):
                if not item.get(field):
                    raise ValueError(f"{node_id} tag {item.get('tag')} missing {field}")


def _default_concept(node_id: str) -> dict[str, Any]:
    root, _, leaf = node_id.partition(".")
    title_zh = node_title_zh(node_id)
    title_en = node_title_en(node_id)
    return {
        "title_zh": title_zh,
        "title_en": title_en,
        # No templated definition: a real per-mechanism definition comes from the
        # glossary at claim level. Leaving this empty keeps the node header from
        # echoing the title/role back as a fake "concept".
        "definition": "",
        "include": [f"实现或配置 {title_zh} 的源码证据", "public interfaces", "data structures", "policy choices"],
        "exclude": ["相似名字但语义无关的符号", "没有实现证据的纯注释"],
        "confusions": [
            "Use evidence semantics and call relationships, not file names alone.",
            "If evidence is weak or absent, mark unknown/not_found instead of guessing.",
        ],
    }
