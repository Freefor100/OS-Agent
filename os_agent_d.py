# os_agent_d.py
import os
import re
import sys
from datetime import datetime

import langchain
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage

from core.agent_builder import build_agent, SYSTEM_PROMPT

langchain.debug = True
load_dotenv()

OUTPUT_DIR = "./output"


def _repo_name_from_url(repo_url: str) -> str:
    name = repo_url.rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".git") else name


def _slug(s: str) -> str:
    keep = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    out = "".join(keep).strip("_")
    return out[:60] if out else "section"


def _build_base_context(repo_url: str, output_dir: str, is_prep_stage: bool = False) -> str:
    """构建基础上下文信息。
    
    Args:
        repo_url: 仓库 URL
        output_dir: 输出目录
        is_prep_stage: 是否是仓库准备阶段（第0阶段）
    """
    repo_name = _repo_name_from_url(repo_url)
    # 与 tools.git_ops.get_repo_local_path 保持一致：./repos/<repo_name>
    repo_path = os.path.normpath(os.path.join("./repos", repo_name))
    charts_dir = os.path.normpath(os.path.join(output_dir, "charts"))
    sections_dir = os.path.normpath(os.path.join(output_dir, "sections"))
    
    # 准备阶段需要克隆，后续阶段直接使用 repo_path
    if is_prep_stage:
        repo_hint = f"请使用 clone_repository(repo_url) 克隆仓库，仓库 URL: {repo_url}"
    else:
        repo_hint = f"**仓库已就绪**: 直接使用 repo_path = \"{repo_path}\"，无需调用 clone_repository。"
    
    if is_prep_stage:
        return f"""你是一个操作系统项目的技术分析 Agent。

基础信息：
- 仓库 URL: {repo_url}
- 本地路径 repo_path: {repo_path}

{repo_hint}

请只完成 Prompt 指定的任务（repo 准备），不需要生成长篇报告。输出要极其简练。
"""

    return f"""你是一个操作系统项目的技术分析 Agent。请严格基于仓库中的代码与文档输出结论，避免空泛。

基础信息：
- 仓库 URL: {repo_url}
- 本地路径 repo_path: {repo_path}
- 输出目录 output_dir: {output_dir}
- 图表目录 charts_dir: {charts_dir}
- 分段输出目录 sections_dir: {sections_dir}

{repo_hint}

全局要求：
- 必须使用工具获取证据：结构用 list_repo_structure / find_os_core_modules / analyze_code_architecture；细节用 read_code_segment；历史用 analyze_git_history_detailed / get_dev_history_by_module / generate_dev_history_charts。
- 论证要"可追溯"：提到结论时，给出对应文件路径、关键结构体/函数名（必要时用 read_code_segment 引用片段）。
- 默认忽略 vendor/；只有当分析依赖实现细节时才进入 vendor。
- 输出使用 Markdown，面向"懂 OS 的读者"，每个小节都要解释组件原理 + 在本仓库的具体实现方式。

**Markdown 格式规范**（严格遵守）：
1. **标题层级**：
   - 本章节已有一级标题（由系统自动添加），请从二级标题（##）开始
   - 禁止重复一级标题（#）
   - 标题层级递进：## → ### → ####，不要跳级
   - 禁止使用错误格式如 `### ##`

2. **正文输出**：
   - 直接输出分析内容，不要包含"现在我开始..."、"让我总结..."等思考过程
   - 不要输出分析前的准备文字

3. **代码块**：
   - 使用三个反引号包围，并标注语言（如 ```rust、```c）
   - 代码片段控制在50行以内，过长时使用注释省略

4. **列表**：
   - 有序列表使用 `1.`、`2.`，无序列表使用 `-` 或 `*`
   - 保持同级列表标记一致

5. **文件路径引用**：
   - 使用反引号包围：`arceos/modules/axtask/src/task.rs`
   - 在分析时总是给出完整相对路径

6. **代码元素引用**：
   - 结构体/函数/变量使用反引号：`TaskInner`、`spawn_task()`
   - 配置项使用反引号：`sched_fifo`

7. **图表引用**：
   - 使用标准 Markdown 格式：`![描述](charts/filename.png)`

8. **专业性**：
   - 使用准确的OS术语（如"页表"非"分页表"、"互斥锁"非"互斥"）
   - 中英文混排时注意空格（`进程 (Process)`）
"""


STAGES = [
    {
        "id": "00_repo_prep",
        "title": "仓库准备",
        "prompt": """目标：克隆仓库并确认本地路径。

请完成：
1) clone_repository(repo_url)：克隆仓库到本地。
2) 确认 repo_path 路径正确（工具会返回本地路径）。

输出：简短确认仓库已就绪，包含 repo_path。
""",
        "skip_in_report": True,
    },
    {
        "id": "01_overview",
        "title": "项目概览与技术栈",
        "prompt": """目标：建立"这是什么 OS、怎么构建、关键入口在哪"。

请按顺序完成（仓库已克隆到 repo_path，直接使用即可）：
1) analyze_tech_stack(repo_path)：总结语言/构建/依赖。
2) list_repo_structure(repo_path, max_depth=5)：总结关键目录。注意输出中的文件行数和大小信息。
3) read_code_segment 读取并总结：README.md、Cargo.toml、Makefile（如存在）。

输出格式：
- ## 结论摘要（3-5 条）
- ## 技术栈与构建（含关键命令/入口文件）
- ## 目录结构导读（列出"子系统→目录→入口文件"）
- ## 证据列表（文件路径清单）

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "01_boot_arch",
        "title": "启动流程与架构初始化",
        "prompt": """目标：分析“从复位/Bootloader 到内核 main 函数”的完整流程及架构相关初始化。

必须回答：
- 启动入口在哪里？（汇编文件如 entry.S 或 head.S，链接脚本 linker.ld 中的 ENTRY）
- CPU 模式切换与初始化（如 RISC-V M-Mode -> S-Mode，x86实模式->保护模式->长模式）。
- 关键寄存器设置（栈指针 SP、页表基址 SATP/CR3、中断向量表 stvec 等）。
- 它是如何跳转到 Rust/C 入口函数的？
- 早期初始化做了什么（BSS 清零、早期串口打印、设备树解析）？
- 若项目基于某个已有框架/内核（如 ArceOS、rCore、xv6 等），该框架提供了什么核心能力？项目代码与框架代码如何协作？
- 是否存在平台配置文件机制？用 grep_in_repo 搜索 `.toml`/`defconfig`/`Kconfig` 配置文件，分析构建系统如何选择编译目标和平台参数。
- 若支持多种硬件平台/开发板，不同平台的启动流程有何区别？

要求：
- 使用 grep_in_repo 或 list_repo_structure 查找 entry.S/start.S/linker.ld。
- 重点关注 arch/、platform/、boot/ 目录下的初始化代码。
- 必须引用 entry 汇编代码片段和 Rust/C main 函数入口。
- **完整追踪**：从 `_start` 到内核 main 函数的每一步调用链，引用文件路径和行号。

输出格式：
- ## 启动入口与链接脚本分析
- ## 架构初始化流程（关键寄存器与模式切换）
- ## 到达内核主函数的路径（完整调用链）
- ## 框架与项目关系（如适用）
- ## 平台配置机制（如适用）
- ## 关键代码片段分析

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "02_mem_mgmt",
        "title": "内存管理（物理/虚拟/分配器）",
        "prompt": """目标：深挖“物理内存管理 + 虚拟内存管理 + 堆/页分配器”。

必须回答：
- 物理内存管理：使用什么算法（Bitmap/Buddy System）？FrameAllocator 接口在哪里？
- 虚拟内存管理：页表如何操作（PageTable 结构、walk/map/unmap 实现）？
- 内核与用户地址空间设计：是否独立？内核重映射？
- 堆分配器：使用了什么 Allocator（GlobalAlloc, slab, buddy）？
- 缺页异常（Page Fault）处理逻辑（如有）。
- **高级特性**：使用 grep_in_repo 搜索以下特性是否已实现（搜索关键词 `cow|CoW|copy_on_write|lazy|SharedMemory|shm|mmap|swap|huge_page|reverse_map`）：
  - 写时复制（Copy-on-Write）
  - 懒分配（Lazy Allocation）
  - 共享内存管理（生命周期、映射机制）
  - 交换区/页面置换
  - 大页支持
  - 反向映射

要求：
- 定位 mm/memory 相关入口，使用 read_code_segment 读取 FrameAllocator 和 PageTable 实现。
- 分析堆初始化逻辑（heap_init）。
- 对于上述高级特性，如找到实现代码则详细分析；如仅有定义/占位则明确说明。

输出格式：
- ## 物理内存管理实现
- ## 虚拟内存与页表操作
- ## 地址空间布局（内核 vs 用户）
- ## 堆分配器解析
- ## 高级内存特性（CoW/懒分配/共享内存等）
- ## 关键代码片段

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "03_process_sched",
        "title": "进程/线程与调度机制",
        "prompt": """目标：深挖“任务模型 + 调度算法 + 上下文切换”。

必须回答：
- 执行实体：Process/Thread/Task 结构体包含哪些字段（Context, State, TrapFrame）？
- **兄弟模块搜索**：除了主要的任务/线程模块外，使用 grep_in_repo 搜索 `Process|ProcessGroup|Session|process` 检查是否存在独立的进程管理模块。若存在，分析其与任务模块的关系。
- 进程/线程层次结构设计（如有）：进程组、会话等概念。
- PID/TID 分配与管理机制。
- 进程与线程的数据分离设计（各自持有什么资源）。
- 调度策略：算法是什么（FIFO, RR, Priority, Stride, CFS）？Scheduler 实现细节。
- 状态流转：Ready/Running/Blocked/Exited 状态机。
- 上下文切换：switch.S 或类似汇编代码，保存了哪些寄存器？
- 进程创建：fork/exec/spawn 的实现逻辑。完整追踪 fork 调用链。
- 安全与权限：是否有 Capability、ACL 或 User/Group 权限模型？

要求：
- 查找 Task/Process 结构体定义。
- **重要**：不要只看一个模块！用 find_os_core_modules 或 grep_in_repo 搜索所有进程/线程相关模块。
- 查找调度器 run/schedule 函数。
- 查找 context_switch 汇编代码。

输出格式：
- ## 任务模型与核心数据结构
- ## 进程管理模块（如独立存在）
- ## 调度算法与策略
- ## 任务状态机
- ## 上下文切换实现（汇编分析）
- ## 进程创建流程（完整调用链）

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "04_trap_syscall",
        "title": "中断、异常与系统调用",
        "prompt": """目标：分析“Trap 处理流程 + 系统调用分发”。

必须回答：
- Trap 入口：trap_handler / trap_vector 在哪里？如何区分中断（Interrupt）和异常（Exception）？
- 上下文保存：TrapFrame 结构，如何保存/恢复用户态寄存器？
- 系统调用（Syscall）：
    - 用户态 ecall/syscall 指令封装。
    - 内核态 syscall 分发函数（syscall_handler）。
    - 3-5 个关键 syscall 实现分析（如 write, yield, exit）。
- 外部中断处理：时钟中断（Timer）、外部设备中断处理流程。

要求：
- 找到 trap.S / trap.rs。
- 分析 syscall 分发表。
- 引用关键的 Trap 处理代码。

输出格式：
- ## Trap 处理流程（用户态 <-> 内核态）
- ## 异常向量表与入口
- ## 系统调用分发机制
- ## 核心 Syscall 实现分析
- ## 中断处理（时钟/外设）

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "05_fs_vfs",
        "title": "文件系统（VFS + 具体 FS）",
        "prompt": """目标：深挖"VFS 抽象 + 挂载 + 具体文件系统实现"。

必须回答：
- VFS 抽象层：File/Inode/Dentry Traits 定义。
- 具体文件系统：支持哪些 FS（fat32, ext4, simple-fs, host-fs）？
- **伪文件系统**：使用 grep_in_repo 搜索 `devfs|procfs|sysfs|tmpfs|ramfs` 检查是否实现了伪文件系统。若有，分析其实现方式。
- 根文件系统：如何挂载 RootFS？
- 文件操作：open/read/write/close 的内核路径。
- 特殊文件系统：是否有 stdio/stdout, pipe, socket？
- 文件描述符表：全局 / 进程级 FD 管理实现。
- **缓存机制**：是否有文件系统缓存（page cache、block cache、目录项缓存）？

要求：
- 定位 fs/vfs 模块。
- 分析 File trait 或类似接口。
- 深入一个具体 FS 的实现。
- **重要**：描述任何结构体（如文件描述符表、FsContext）的字段时，必须先用 grep_in_repo 搜索确认其真实名称和字段定义，不得臆测。如找不到准确定义，请明确说明。
- 使用 grep_in_repo 搜索 "FdTable|FileDescriptor|fd_table" 确认文件描述符表实际命名。

输出格式：
- ## VFS 架构与接口设计
- ## 具体文件系统支持情况
- ## 伪文件系统（devfs/procfs/sysfs 等）
- ## 根文件系统挂载流程
- ## 文件操作核心路径
- ## 文件描述符表与进程关联
- ## 缓存机制（如有）
- ## 特殊文件系统与 IPC 支持

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "06_device_drivers",
        "title": "设备驱动与硬件抽象",
        "prompt": """目标：分析“设备树/总线 + 驱动框架 + 具体设备驱动”。

必须回答：
- 设备发现：Device Tree (DTS) 解析或 PCI/Bus 扫描？
- 驱动框架：Driver Trait，如何注册/初始化驱动？
- **组件化/可配置设计**：搜索构建配置文件（Cargo.toml 的 features、Kconfig、条件编译宏），分析如何通过编译选项选择不同的驱动/模块实现。
- **平台配置机制**：搜索 `.toml`/`.yaml`/`.dts` 等配置文件，分析平台参数（内存布局、设备地址、中断号）如何配置。
- 常见设备：
    - UART/Serial（控制台输出）
    - Block Device（磁盘读写，VirtIO-Blk）
    - Net Device（网卡，VirtIO-Net）及网络协议栈（TCP/IP, smoltcp 等实现）
    - GPU/Input（如有）
- 中断控制器：PLIC/CLINT/APIC 驱动。
- **目标平台适配**：搜索 `platform/` 或 `boards/` 目录，列出所有支持的目标平台/开发板及其特有驱动。

要求：
- 搜索 drivers/、platform/、boards/ 目录。
- 分析 VirtIO 或 UART 驱动实现。
- 查看设备初始化链（完整追踪 init_drivers 调用链）。
- 使用 grep_in_repo 搜索构建配置中的 feature flags。

输出格式：
- ## 驱动框架与设备发现
- ## 组件化设计与配置机制
- ## 字符设备驱动（UART/Console）
- ## 块设备驱动（VirtIO-Blk等）
- ## 网络设备驱动
- ## 中断控制器驱动
- ## 目标平台适配情况
- ## 其他外设支持

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "07_sync_ipc",
        "title": "同步互斥与进程间通信",
        "prompt": """目标：分析“内核锁机制 + IPC 机制”。

必须回答：
- 同步原语：SpinLock, Mutex, Semaphore, CondVar 的实现。
- 关中断与原子操作：如何保证单核/多核并发安全？
- IPC 机制：
    - Pipe（管道）实现。
    - Signal（信号）处理。
    - Shared Mem（共享内存）或 Message Queue（如有）。

要求：
- 搜索 sync/ 或 lock/ 模块。
- 分析 SpinLock 实现（是否关中断）。
- 查找 IPC 相关 syscall 实现。

输出格式：
- ## 同步互斥原语（锁与原子操作）
- ## 并发安全机制（关中断/CPU核心）
- ## 进程间通信（Pipe/Signal等）
- ## 关键代码实现分析

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "08_smp_multicore",
        "title": "多核支持与并行机制",
        "prompt": """目标：分析多核/SMP（对称多处理）支持实现。

必须回答：
- 是否支持多核？架构设计是 SMP 还是 AMP？
- Secondary CPU 启动流程（如 smp_boot、cpu_up）。
- 核间中断（IPI - Inter-Processor Interrupt）实现。
- Per-CPU 变量设计与访问方式。
- 多核调度策略：负载均衡、CPU 亲和性（affinity）。
- 自旋锁/RCU 在多核下的实现差异。

要求：
- 搜索 smp/、cpu/、percpu 相关模块。
- 查找 CPU 启动入口和 IPI 处理函数。
- 分析多核安全的数据结构设计。

输出格式：
- ## 多核架构设计（SMP/AMP）
- ## Secondary CPU 启动流程
- ## 核间通信与 IPI 机制
- ## Per-CPU 变量与数据结构
- ## 多核调度策略
- ## 关键代码片段

**重要**：如果项目不支持多核，请明确说明并分析其单核设计。完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "08_security",
        "title": "安全机制与权限模型",
        "prompt": """目标：分析安全隔离与权限控制机制。

必须回答：
- 用户态/内核态隔离如何实现（页表隔离、特权级切换）？
- 权限检查点在哪里（syscall 入口、文件访问、内存访问）？
- 是否有 Capability/ACL/RBAC 权限模型？
- 进程间隔离机制（地址空间隔离、资源限制）。
- 是否有沙箱（Sandbox）或容器支持？如有 seccomp 相关实现，需区分"有实际过滤逻辑"还是"仅有 /proc 静态数据"。
- 安全启动/可信启动支持（如有）。
- **内存安全特性**：使用 grep_in_repo 搜索 `cow|CoW|copy_on_write|lazy_alloc|UserInPtr|UserOutPtr|check_ptr|verify_area`，分析内存保护机制（CoW、懒分配、用户指针验证）如何在安全层面发挥作用。
- **系统调用接口安全设计**：搜索系统调用参数验证、边界检查、接口与实现分离的设计模式。
- Rust 语言自身的安全特性如何在项目中体现（unsafe 使用情况等）。

要求：
- 搜索 security/、auth/、permission/、capability 相关模块。
- 查找 syscall 入口处的权限检查逻辑。
- 分析用户/组/权限位的实现。
- 使用 grep_in_repo 搜索 "seccomp|sandbox|filter|capability|prctl" 确认安全沙箱是否有实际实现（不仅仅是定义）。
- 特别注意：区分"仅有定义/头文件"和"有实际实现"，如实汇报。

输出格式：
- ## 特权级与隔离机制
- ## 权限检查与访问控制
- ## 用户/组/权限模型
- ## 进程间隔离与资源限制
- ## 安全沙箱与过滤机制（seccomp 等）
- ## 内存安全与语言层面安全
- ## 其他安全特性（如有）
- ## 关键代码片段

**重要**：如果项目安全机制较简单，请如实描述。完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "08_network",
        "title": "网络子系统与协议栈",
        "prompt": """目标：深入分析网络子系统与 TCP/IP 协议栈实现。

必须回答：
- 网络协议栈架构：自实现还是使用 smoltcp/lwip 等库？
- Socket 接口实现：socket/bind/listen/accept/connect/send/recv。
- 网络设备抽象：NetDevice Trait 或接口定义。
- 协议层实现：
    - 链路层（Ethernet）
    - 网络层（IP/ARP/ICMP）
    - 传输层（TCP/UDP）
- 数据包收发流程：从网卡中断到用户态 recv。
- 网络配置：IP 地址配置、路由表（如有）。
- 网络测试与验证工具（iperf/netperf/LTP 等）的集成情况。

要求：
- 搜索 net/、network/、socket/、tcp/ 相关模块。
- 查找 Socket syscall 实现。
- 分析数据包处理流程（完整追踪：从网卡中断到用户态 recv）。
- 使用 grep_in_repo 搜索 "iperf|netperf|ltp|bench|test_net" 检查是否有网络性能测试工具集成。
- **严格反捌造**：对于声称支持的高级特性（如零拷贝、多网卡路由、地址复用、Jumbo Frame、多队列 RSS），必须找到**实际实现代码**验证，不能仅凭头文件定义或类型别名。如仅有定义而无实现，明确说明"仅有定义/占位，未找到实际实现代码"。
- 明确区分"通过 smoltcp 间接支持"和"项目自身实现"。

输出格式：
- ## 网络子系统架构
- ## Socket 接口实现
- ## 协议栈层次分析
- ## 数据包收发流程
- ## 网络配置与路由
- ## 网络测试与验证
- ## 关键代码片段

**重要**：如果项目不支持网络功能，请明确说明。完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "08_debug_error",
        "title": "调试机制与错误处理",
        "prompt": """目标：分析调试支持、日志系统与错误处理机制。

必须回答：
- 日志系统：print/log 宏如何实现？日志级别设计？
- Panic 处理：panic! 触发后的流程（栈回溯、寄存器 dump、停机）。
- 异常处理：未处理异常的默认行为。
- 调试接口：
    - GDB stub 支持（如有）
    - 调试控制台/Monitor
    - 内核调试选项
- 错误码设计：Result/Error 类型定义。
- 断言与检查：debug_assert、运行时检查。

要求：
- 搜索 panic、log、debug、error 相关实现。
- 查找 print!/println! 或类似宏的定义。
- 分析 panic_handler 实现。

输出格式：
- ## 日志与打印系统
- ## Panic 处理流程
- ## 错误码与 Result 设计
- ## 调试接口与工具
- ## 断言与运行时检查
- ## 关键代码片段

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "08_test_ci",
        "title": "测试框架与验证机制",
        "prompt": """目标：分析测试框架、测试用例与持续集成配置。

必须回答：
- 测试框架：使用什么测试框架（#[test]、自定义测试框架）？
- 测试类型：
    - 单元测试（模块级）
    - 集成测试（系统级）
    - 用户程序测试
    - 标准测试套件（LTP、libc-test、busybox 等）的集成情况
- 测试用例分析：关键测试用例覆盖了哪些功能？
- QEMU/模拟器测试：如何在模拟器中运行测试？
- CI/CD 配置：.github/workflows、.gitlab-ci.yml 等。
- 测试覆盖度：是否有覆盖率统计？
- 网络性能测试工具（iperf/netperf 等）的验证方式。
- **测试通过率**：搜索测试日志/结果文件（如 `run_log.txt`、`test_result`、`*.log`），区分“已集成测试套件”和“测试实际通过”的差别。

要求：
- 搜索 tests/、test、spec 目录。
- 查找 CI 配置文件。
- 分析 Makefile 中的 test 目标。
- 使用 grep_in_repo 搜索 "ltp|libc-test|busybox|iperf|oscomp_test" 确认是否集成标准测试套件。
- 验证 Makefile 中的每个 test target 是否真实存在并可运行（使用 read_code_segment 查看 Makefile 相关部分）。
- **重要**：搜索所有测试脚本（`*.sh`、`*.py`）并分析测试覆盖范围。

输出格式：
- ## 测试框架与运行方式
- ## 单元测试分析
- ## 集成测试与系统测试
- ## 标准测试套件集成与通过情况
- ## 用户程序测试
- ## CI/CD 配置分析
- ## 测试覆盖与质量评估

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "14_history",
        "title": "开发历史与里程碑（含图表）",
        "prompt": """目标：给出"按模块的开发时间线"和"活跃度图表解释"。

请完成：
1) analyze_git_history_detailed(repo_path, max_commits=150)：总结关键阶段。
2) get_dev_history_by_module(repo_path, max_commits=200)：提炼每个核心子系统的【初步】与【较大改动】里程碑。
3) generate_dev_history_charts(repo_path, output_dir=charts_dir)：生成图表（charts_dir 见基础信息）。

图表说明（会自动生成以下 3 张图）：
- commits_monthly.png：每月提交量柱状图
- modules_activity.png：各模块变更量柱状图
- modules_timeline.png：**模块开发里程碑时间线**（显示每个模块的初步提交和较大改动日期）

输出格式：
- ## 总体时间线（按月/阶段）
- ## 子系统里程碑（每个子系统 2-4 条，说明初步完成和关键改动的日期）
- ## 图表展示与解读

请在报告中插入图表引用：
![每月提交量](charts/commits_monthly.png)
![模块活跃度](charts/modules_activity.png)
![模块开发里程碑时间线](charts/modules_timeline.png)

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告，包含上述所有章节内容和图表引用。
""",
    },
    {
        "id": "15_final",
        "title": "执行摘要与总结评价",
        "prompt": """目标：基于前面所有章节的分析，生成执行摘要和项目总结评价。

你已经完成了对该OS项目的详细分析（包括：项目概览、启动流程、内存管理、进程调度、中断系统调用、文件系统、设备驱动、同步IPC、多核支持、安全机制、网络协议栈、调试机制、测试框架、开发历史等）。

现在需要你输出两个部分：

## 1. 执行摘要（Executive Summary）

用200-300字概括：
- 项目定位与目标（教学OS/实验OS/微内核等）
- 技术栈概览（编程语言、目标架构、关键技术）
- 核心特性与亮点（列出3-5项最突出的特性）
- 实现完成度评估（核心功能是否完整）

## 2. 项目总结与评价

### 技术成熟度
评估实现完整度、代码质量、文档完善度等

### 设计亮点
列举2-3个突出的架构设计或技术实现

### 不足与改进空间
客观指出可优化的地方（如性能、功能、代码规范等）

### 适用场景
说明这个项目适合什么场景使用或学习

---

**输出要求**：
1. 只输出上述两个部分（执行摘要 + 项目总结与评价）
2. 不要重复前面章节的内容
3. 基于实际分析内容，不要臆测或夸大
4. 语气专业客观，类似技术评审报告
5. 使用严格的Markdown格式

**前面阶段的分析内容将附在下面供参考...**
""",
        "needs_previous_sections": True,
        "skip_in_report": False,  # 改为False，要保存到sections并包含在最终报告中
    },
]


def _format_tool_call_summary(tool_name: str, tool_args: dict) -> str:
    """格式化工具调用为简洁摘要"""
    if tool_name in ("read_code_segment", "read_file", "read_human_doc"):
        file_path = tool_args.get("file_path", tool_args.get("path", "?"))
        start = tool_args.get("start_line", tool_args.get("start", tool_args.get("start_page", "")))
        end = tool_args.get("end_line", tool_args.get("end", ""))
        if start and end:
            return f"{file_path} L{start}-L{end}"
        elif start:
            return f"{file_path} L{start}"
        return file_path or "?"

    elif tool_name in ("list_repo_structure", "list_directory", "list_section_files"):
        path = tool_args.get("repo_path", tool_args.get("path", tool_args.get("output_dir", "?")))
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/"

    elif tool_name == "find_human_docs":
        path = tool_args.get("repo_path", "?")
        kw = tool_args.get("keywords", "")[:30]
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/" + (f' "{kw}"' if kw else "")

    elif tool_name == "verify_claim_in_source":
        claim = str(tool_args.get("claim", ""))[:40]
        return f'"{claim}..."' if len(claim) >= 40 else f'"{claim}"'

    elif tool_name in ("grep_search", "grep_in_repo"):
        pattern = str(tool_args.get("pattern", tool_args.get("query", "?")))[:30]
        path = tool_args.get("repo_path", tool_args.get("path", ""))
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else ""
        return f'"{pattern}"' + (f" in {dirname}/" if dirname else "")

    elif tool_name == "clone_repository":
        url = tool_args.get("repo_url", "?")
        repo_name = url.rstrip("/").split("/")[-1] if url else "?"
        return repo_name

    elif tool_name in ("analyze_tech_stack", "find_os_core_modules", "analyze_code_architecture"):
        path = tool_args.get("repo_path", tool_args.get("path", "?"))
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/"

    elif tool_name in ("analyze_git_history_detailed", "get_dev_history_by_module", "generate_dev_history_charts"):
        path = tool_args.get("repo_path", "?")
        max_commits = tool_args.get("max_commits", "")
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/" + (f" (max={max_commits})" if max_commits else "")

    else:
        if tool_args:
            first_key = list(tool_args.keys())[0]
            first_val = str(tool_args[first_key])[:40]
            return f"{first_key}={first_val}"
        return ""


def _format_tool_result_summary(tool_name: str, content: str) -> str:
    """格式化工具返回结果为简洁摘要"""
    content_len = len(content)
    line_count = len(content.split("\n")) if content else 0

    if tool_name in ("read_code_segment", "read_file", "read_human_doc"):
        return f"返回 {line_count} 行 ({content_len} 字符)"
    elif tool_name in ("list_repo_structure", "list_directory", "list_section_files"):
        return f"返回 {line_count} 项"
    elif tool_name == "find_human_docs":
        doc_count = content.count("[PDF") + content.count("[DOC") + content.count("[MATCH]")
        return f"找到 {doc_count} 个文档" if doc_count else f"返回 {content_len} 字符"
    elif tool_name == "verify_claim_in_source":
        if "✅" in content or "找到" in content:
            return "✓ 源码有匹配"
        if "❌" in content:
            return "✗ 源码无匹配"
        return f"返回 {content_len} 字符"
    elif tool_name in ("grep_search", "grep_in_repo"):
        match_count = content.count("\n") if content.strip() else 0
        return f"找到 {match_count} 个匹配"
    elif tool_name == "clone_repository":
        if "成功" in content or "success" in content.lower() or "cloned" in content.lower():
            return "✓ 克隆成功"
        elif "已存在" in content or "exists" in content.lower():
            return "✓ 仓库已存在"
        else:
            return f"返回 {content_len} 字符"
    elif tool_name == "analyze_tech_stack":
        if "代码文件统计" in content or "Rust" in content:
            return "返回技术栈与文件统计"
        return f"返回 {content_len} 字符"
    elif tool_name in ("get_dev_history_by_module", "analyze_git_history_detailed"):
        return f"返回开发历史 ({line_count} 行)"
    else:
        return f"返回 {content_len} 字符 ({line_count} 行)"


def print_step(step_num: int, node_name: str, state: dict, stage_step_num: int = 0, max_steps: int = 500) -> int:
    """打印每一步的执行信息（简洁的 agent 风格）
    
    Args:
        step_num: 全局步骤号
        node_name: 节点名称
        state: 状态字典
        stage_step_num: 阶段内步骤号
        max_steps: 全局最大步数限制
        
    Returns:
        int: 本次步骤消耗的 token 数量
    """
    token_count = 0
    messages = state.get("messages", [])
    if not messages:
        return 0
    
    # 只显示新增的消息（避免重复）
    if step_num == 1:
        msg_to_show = messages
    else:
        msg_to_show = [messages[-1]] if messages else []
    
    for msg in msg_to_show:
        if isinstance(msg, AIMessage):
            content = msg.content or ""
            tool_calls = getattr(msg, "tool_calls", None) or []
            
            if step_num > 0:
                print(f"\n【Step {step_num}/{max_steps}】(Stage: {stage_step_num})", end=" ")

            if tool_calls:
                print("🔧 Tool Calls:")
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tool_name = tc.get("name", "unknown")
                        tool_args = tc.get("args", {})
                    else:
                        tool_name = getattr(tc, "name", "unknown")
                        tool_args = getattr(tc, "args", {})
                    
                    summary = _format_tool_call_summary(tool_name, tool_args)
                    print(f"   {tool_name}({summary})")
            
            # 如果有思考内容且没有工具调用，显示思考（这通常是最终输出）
            elif content.strip():
                # 显示简短预览
                preview = content.strip()[:200]
                if len(content) > 200:
                    preview += "..."
                print(f"🤔 Agent: {preview}")
            
            # 打印 Token Usage
            metadata = getattr(msg, "response_metadata", {})
            usage = metadata.get("token_usage", {})
            if usage:
                total_this_call = usage.get("total_tokens", 0)
                if total_this_call > 0:
                    token_count += total_this_call
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)
                    print(f"   📄 Tokens: {total_this_call:,} (输入:{input_tokens:,} + 输出:{output_tokens:,})")
        
        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "unknown")
            content = msg.content or ""
            summary = _format_tool_result_summary(tool_name, content)
            print(f"   ✅ {tool_name}: {summary}")
            
    return token_count


def main():
    repo_url = os.environ.get("REPO_URL", "").strip()
    
    if not repo_url:
        print("❌ 错误：未设置 REPO_URL 环境变量")
        print("   请在 .env 文件中设置 REPO_URL，或通过命令行设置：")
        print("   export REPO_URL=\"https://github.com/example/os-project.git\"")
        sys.exit(1)

    repo_name = _repo_name_from_url(repo_url)
    
    # 按 OS 名称创建独立的输出目录
    repo_output_dir = os.path.join(OUTPUT_DIR, repo_name)
    charts_dir = os.path.join(repo_output_dir, "charts")
    sections_dir = os.path.join(repo_output_dir, "sections")
    
    os.makedirs(repo_output_dir, exist_ok=True)
    os.makedirs(charts_dir, exist_ok=True)
    os.makedirs(sections_dir, exist_ok=True)

    agent = build_agent()

    print("=" * 80)
    print("📋 多阶段任务：开始")
    print(f"Repo: {repo_name}")
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    all_section_paths = []
    overall_step_count = 0
    total_tokens_used = 0  # 累计token使用量
    start_time = datetime.now()
    
    # 计算有效章节数（用于文件命名）
    chapter_counter = 0  # 实际章节计数器
    
    GLOBAL_MAX_STEPS = 800  # 全局最大步数限制（用于显示）

    for idx, stage in enumerate(STAGES, 1):
        stage_id = stage["id"]
        title = stage["title"]
        prompt = stage["prompt"]
        
        # 检查是否跳过此阶段
        skip_in_report = stage.get("skip_in_report", False)
        
        # 只有非skip阶段才计入章节号
        if not skip_in_report:
            chapter_counter += 1
            section_name = f"{chapter_counter:02d}_{_slug(title)}.md"
        else:
            # skip阶段使用idx作为前缀（避免冲突，但不会保存）
            section_name = f"00_{_slug(title)}.md"
        
        section_path = os.path.join(sections_dir, section_name)

        # 简单的断点续传：如果文件已存在且内容看起来正常（>200字节），则跳过
        if os.path.exists(section_path):
            if os.path.getsize(section_path) > 200:
                print("\\n" + "=" * 80)
                print(f"⏭️  阶段 {idx}/{len(STAGES)}：{title} (已存在，跳过)")
                print(f"   文件: {section_path}")
                print("=" * 80)
                if not skip_in_report:
                    all_section_paths.append(section_path)
                continue
            else:
                print(f"♻️  检测到残留的失败文件 (Size: {os.path.getsize(section_path)} bytes)，将删除并重试: {section_name}")
                try:
                    os.remove(section_path)
                except OSError:
                    pass


        # 每个阶段构建 base_ctx，仓库准备阶段需要克隆，后续阶段直接使用 repo_path
        is_prep_stage = "prep" in stage_id.lower()
        base_ctx = _build_base_context(repo_url=repo_url, output_dir=repo_output_dir, is_prep_stage=is_prep_stage)
        
        # 如果是最后整合阶段，需要读取前面所有 section 的内容
        previous_sections_content = ""
        if stage.get("needs_previous_sections", False) and all_section_paths:
            print(f"\n📚 读取前面 {len(all_section_paths)} 个阶段的分析内容...")
            sections_texts = []
            
            # 限制每个 section 的最大字符数，避免 "lost in the middle" 问题
            MAX_CHARS_PER_SECTION = 15000  # 每个 section 最多 15000 字符
            total_chars = 0
            
            for sp in all_section_paths:
                try:
                    with open(sp, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read().strip()
                        if content:
                            # 如果内容太长，截取前面部分 + 提示
                            if len(content) > MAX_CHARS_PER_SECTION:
                                truncated = content[:MAX_CHARS_PER_SECTION]
                                # 尝试在段落边界截断
                                last_para = truncated.rfind("\n\n")
                                if last_para > MAX_CHARS_PER_SECTION * 0.7:
                                    truncated = truncated[:last_para]
                                content = truncated + f"\n\n... [此部分已截断，原文 {len(content)} 字符]"
                            
                            sections_texts.append(f"--- 来自: {os.path.basename(sp)} ---\n{content}")
                            total_chars += len(content)
                except Exception as e:
                    print(f"  ⚠️  无法读取 {sp}: {e}")
            
            if sections_texts:
                previous_sections_content = "\n\n" + "=" * 60 + "\n[前面阶段的分析内容摘要]\n" + "=" * 60 + "\n\n"
                previous_sections_content += "\n\n".join(sections_texts)
                previous_sections_content += "\n\n" + "=" * 60 + "\n[以上是前面阶段的分析内容，请基于这些内容整合生成最终报告]\n" + "=" * 60 + "\n"
                print(f"  ✅ 已加载 {len(sections_texts)} 个 section，共 {total_chars} 字符（每个最多 {MAX_CHARS_PER_SECTION} 字符）")
        
        # 计算章节号（跳过 repo_prep 阶段）
        # 章节号从 1 开始，用于非跳过阶段
        chapter_stages = [s for s in STAGES if not s.get("skip_in_report", False)]
        chapter_num = None
        for i, cs in enumerate(chapter_stages, 1):
            if cs["id"] == stage_id:
                chapter_num = i
                break
        
        # 构建任务 prompt
        if chapter_num and not stage.get("needs_previous_sections", False):
            # 这是一个正式章节，告诉 Agent 输出的是第几章
            chapter_hint = f"""
**本阶段是最终报告的第 {chapter_num} 章：{title}**

请按照以下格式输出本章内容（这将直接作为最终报告的一部分）：

## 第 {chapter_num} 章：{title}

（你的分析内容）

"""
            task = base_ctx + "\n" + chapter_hint + prompt + previous_sections_content
        else:
            task = base_ctx + "\n" + f"## 阶段 {idx}/{len(STAGES)}：{title}\n\n" + prompt + previous_sections_content
        
        inputs = {"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=task)]}

        print("\\n" + "=" * 80)
        print(f"🧩 阶段 {idx}/{len(STAGES)}：{title}")
        print("=" * 80)
        print(f"🚀 开始执行 Agent (模型: {os.getenv('MODEL_NAME')})...")
        sys.stdout.flush()  # 强制刷新输出缓冲区

        final_state = None
        stage_step_count = 0  # 阶段内步骤计数
        recursion_limit = 500
        
        stage_tokens = 0  # 阶段内 token 计数
        
        try:
            # 增加 recursion_limit 防止复杂任务因步数过多而中断
            for event in agent.stream(inputs, config={"recursion_limit": recursion_limit}):
                overall_step_count += 1
                stage_step_count += 1
                for node_name, state in event.items():
                    step_tokens = print_step(overall_step_count, node_name, state, stage_step_count, GLOBAL_MAX_STEPS)
                    stage_tokens += step_tokens
                    final_state = state
        except KeyboardInterrupt:
            print("\\n\\n⚠️  用户中断执行")
            sys.exit(1)
        except Exception as e:
            print(f"\\n\\n❌ 执行出错: {e}")
            # 不直接退出，而是尝试保存已有的部分（如果有）或错误信息
            import traceback
            traceback.print_exc()

        stage_text = ""
        is_complete = False
        all_ai_content = []  # 收集所有 AI 回复内容
        
        if final_state and final_state.get("messages"):
            messages = final_state["messages"]
            if messages:
                # 收集所有 AIMessage 的内容（降低阈值到 20 字符）
                for m in messages:
                    if isinstance(m, AIMessage):
                        content = (m.content or "").strip()
                        if content and len(content) > 20:
                            all_ai_content.append(content)
                
                # 优先查找：最后一条包含实际内容且没有工具调用的 AIMessage
                for m in reversed(messages):
                    if isinstance(m, AIMessage):
                        content = (m.content or "").strip()
                        tool_calls = getattr(m, "tool_calls", None) or []
                        
                        # 理想情况：有内容且没有工具调用（这是最终总结）
                        if content and not tool_calls and len(content) > 200:
                            print(f"\n✅ 找到有效 AI 回复（无工具调用，长度: {len(content)} 字符）")
                            stage_text = content
                            is_complete = True
                            break
                
                # 如果没找到理想的最终回复，尝试合并所有 AI 内容
                if not is_complete and all_ai_content:
                    print(f"\n⚠️  未找到独立最终回复，合并 {len(all_ai_content)} 条 AI 回复内容")
                    # 取最长的那条
                    stage_text = max(all_ai_content, key=len)
                    # 如果最长的不够长，合并所有内容
                    if len(stage_text) < 500 and len(all_ai_content) > 1:
                        stage_text = "\n\n---\n\n".join(all_ai_content)
                
                # 如果仍然没有内容，且该阶段需要生成报告，则发送追问消息
                if (not stage_text or len(stage_text) < 100) and not skip_in_report:
                    print(f"\n🔄 内容不足，发送追问消息请求生成报告...")
                    followup_msg = HumanMessage(content=f"""你已经收集了关于"{title}"的信息。

现在请根据你收集到的信息，立即输出完整的 Markdown 格式分析报告。

不要再调用任何工具，直接写出报告内容。报告必须包含：
1. 设计概览
2. 核心数据结构
3. 关键实现分析
4. 代码片段引用

请现在输出报告：""")
                    
                    try:
                        # 继续对话，追加 followup 消息
                        followup_inputs = {"messages": messages + [followup_msg]}
                        for event in agent.stream(followup_inputs, config={"recursion_limit": 10}):
                            overall_step_count += 1
                            stage_step_count += 1
                            for node_name, state in event.items():
                                step_tokens = print_step(overall_step_count, node_name, state, stage_step_count, GLOBAL_MAX_STEPS)
                                stage_tokens += step_tokens
                                # 提取追问后的回复
                                if state.get("messages"):
                                    for m in reversed(state["messages"]):
                                        if isinstance(m, AIMessage):
                                            content = (m.content or "").strip()
                                            tool_calls = getattr(m, "tool_calls", None) or []
                                            if content and not tool_calls and len(content) > 100:
                                                print(f"\n✅ 追问后获得有效回复（长度: {len(content)} 字符）")
                                                stage_text = content
                                                is_complete = True
                                                break
                                    if is_complete:
                                        break
                            if is_complete:
                                break
                    except Exception as e:
                        print(f"\n⚠️  追问失败: {e}")
                
                if not stage_text:
                    print(f"\n❌ 未找到任何有效 AI 回复内容。")
                    last_msg = messages[-1]
                    stage_text = f"> ⚠️ **生成警告**: 该章节未能完整生成. Last msg type: {type(last_msg).__name__}"

        if not stage_text.strip():
             stage_text = "> ⚠️ **生成警告**: Agent 未返回有效内容。"

        # 保存阶段结果（除非标记为 skip_in_report）
        # skip_in_report 在前面文件命名时已经获取
        if skip_in_report:
            print(f"\n⏭️  阶段 {idx} 标记为 skip_in_report，不写入报告")
        else:
            try:
                with open(section_path, "w", encoding="utf-8") as f:
                    # 不添加一级标题，由拼接时统一添加
                    # LLM输出应从二级标题开始
                    f.write(stage_text.strip() + "\n")
                all_section_paths.append(section_path)
                print(f"\n✅ 已保存阶段输出: {section_path}")
            except Exception as e:
                print(f"\n⚠️  无法写入阶段文件 {section_path}: {e}")
        
        
        # 统计本阶段的token使用（已在 print_step 中累加）
        # stage_tokens 已准备好
        
        total_tokens_used += stage_tokens
        if stage_tokens > 0:
            print(f"\n{'='*80}")
            print(f"📊 阶段总结:")
            print(f"   - 步骤数: {stage_step_count}")
            print(f"   - Token使用: {stage_tokens:,} (累加{stage_step_count}次LLM调用)")
            print(f"   - 全局累计: {total_tokens_used:,}")
            print(f"{'='*80}")
            sys.stdout.flush()

    # 合并总报告 - 生成专业的、类似人类撰写的技术文档
    final_report_path = os.path.join(repo_output_dir, f"OS技术分析报告_{repo_name}.md")
    try:
        # 查找第15阶段的内容（执行摘要和总结评价）
        executive_summary = ""
        project_evaluation = ""
        final_stage_path = None
        
        for p in all_section_paths:
            if "15_" in os.path.basename(p) or "执行摘要" in os.path.basename(p):
                final_stage_path = p
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    final_content = f.read()
                    # 提取执行摘要和总结评价部分（使用正则表达式支持多种格式）
                    if "执行摘要" in final_content and "项目总结与评价" in final_content:
                        # 按"项目总结与评价"分割，支持一级标题(#)或二级标题(##)
                        parts = re.split(r'##?\s*项目总结与评价', final_content, maxsplit=1)
                        if len(parts) >= 2:
                            # 移除顶部的"执行摘要与总结评价"标题（支持 # 或 ##）
                            executive_summary = re.sub(r'##?\s*执行摘要与总结评价', '', parts[0]).strip()
                            # 保留"## 项目总结与评价"标题
                            project_evaluation = "## 项目总结与评价" + parts[1]
                        else:
                            # 如果分割失败，整个内容作为执行摘要
                            executive_summary = final_content
                    elif "执行摘要" in final_content:
                        # 只有执行摘要，没有项目总结与评价
                        executive_summary = re.sub(r'##?\s*执行摘要与总结评价', '', final_content).strip()
                    else:
                        # 都没有，整个内容作为执行摘要
                        executive_summary = final_content
                break
        
        # 其他章节（排除第15阶段）
        content_sections = [p for p in all_section_paths if p != final_stage_path]
        
        with open(final_report_path, "w", encoding="utf-8") as out:
            # 标题和元数据
            out.write(f"# {repo_name} 操作系统技术分析报告\n\n")
            out.write(f"> **仓库地址**: {repo_url}\n")
            out.write(f"> **分析日期**: {datetime.now().strftime('%Y年%m月%d日')}\n")
            out.write(f"> **分析工具**: OS-Agent-D\n\n")
            out.write("---\n\n")
            
            # 执行摘要
            if executive_summary:
                out.write(executive_summary + "\n\n")
                out.write("---\n\n")
            
            # 目录
            out.write("## 目录\n\n")
            for i, p in enumerate(content_sections, 1):
                # 从文件名提取章节标题（因为section文件不再包含一级标题）
                try:
                    # 文件名格式：01_项目概览与技术栈.md
                    filename = os.path.basename(p)
                    # 去除编号前缀和.md后缀
                    title = os.path.splitext(filename)[0]
                    if '_' in title:
                        title = title.split('_', 1)[1]  # 去除 "01_" 前缀
                    # 将下划线替换为空格（如果有）
                    title = title.replace('_', ' ')
                    out.write(f"{i}. {title}\n")
                except Exception:
                    filename = os.path.splitext(os.path.basename(p))[0]
                    out.write(f"{i}. {filename}\n")
            
            # 添加总结评价到目录
            if project_evaluation:
                out.write(f"{len(content_sections) + 1}. 项目总结与评价\n")
            
            out.write("\n---\n\n")
            
            # 正文：依次输出各章节内容
            for i, p in enumerate(content_sections, 1):
                try:
                    # 从文件名提取标题
                    filename = os.path.basename(p)
                    chapter_title = os.path.splitext(filename)[0]
                    if '_' in chapter_title:
                        chapter_title = chapter_title.split('_', 1)[1]
                    chapter_title = chapter_title.replace('_', ' ')
                    
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read().strip()
                        
                        # 添加章节标题（一级标题）
                        out.write(f"\n# {chapter_title}\n\n")
                        
                        # 内容应该从二级标题开始，直接写入
                        # 如果LLM错误地输出了一级标题，降级处理
                        if content.startswith("# "):
                            # 将一级标题转为二级标题
                            content = "##" + content[1:]
                        
                        out.write(content + "\n\n")
                        out.write("---\n\n")
                except Exception as e:
                    print(f"  ⚠️  无法读取章节 {p}: {e}")
            
            # 总结评价
            if project_evaluation:
                out.write(f"\n# 项目总结与评价\n\n")
                out.write(project_evaluation + "\n\n")
                out.write("---\n\n")
            
            # 页脚
            out.write(f"\n---\n\n")
            out.write(f"*本报告由 OS-Agent-D 自动生成*  \n")
            out.write(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*  \n")
            out.write(f"*分析耗时: {(datetime.now() - start_time).total_seconds()/60:.1f} 分钟*\n")
        
        print(f"\n📄 已生成最终报告: {final_report_path}")
        print(f"   报告包含 {len(content_sections)} 个主要章节{'+ 执行摘要和总结' if executive_summary else ''}")
    except Exception as e:
        print(f"\n⚠️  无法生成总报告: {e}")
        import traceback
        traceback.print_exc()

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print("\\n" + "=" * 80)
    print("✅ 多阶段任务完成！")
    print(f"   总步数: {overall_step_count}")
    print(f"   总Token使用: {total_tokens_used:,}")
    print(f"   耗时: {elapsed:.2f} 秒 ({elapsed/60:.2f} 分钟)")
    print(f"⏰ 结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
