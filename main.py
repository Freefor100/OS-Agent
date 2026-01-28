# main.py
import os
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

要求：
- 使用 grep_search 或 list_repo_structure 查找 entry.S/start.S/linker.ld。
- 重点关注 arch/ 目录下的初始化代码。
- 必须引用 entry 汇编代码片段和 Rust/C main 函数入口。

输出格式：
- ## 启动入口与链接脚本分析
- ## 架构初始化流程（关键寄存器与模式切换）
- ## 到达内核主函数的路径
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

要求：
- 定位 mm/memory 相关入口，使用 read_code_segment 读取 FrameAllocator 和 PageTable 实现。
- 分析堆初始化逻辑（heap_init）。

输出格式：
- ## 物理内存管理实现
- ## 虚拟内存与页表操作
- ## 地址空间布局（内核 vs 用户）
- ## 堆分配器解析
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
- 调度策略：算法是什么（FIFO, RR, Priority, Stride）？Scheduler 实现细节。
- 状态流转：Ready/Running/Video/Zombine 状态机。
- 上下文切换：switch.S 或类似汇编代码，保存了哪些寄存器？
- 进程创建：fork/exec/spawn 的实现逻辑。
- 安全与权限：是否有 Capability、ACL 或 User/Group 权限模型？

要求：
- 查找 Task/Process 结构体定义。
- 查找调度器 run/schedule 函数。
- 查找 context_switch 汇编代码。

输出格式：
- ## 任务模型与核心数据结构
- ## 调度算法与策略
- ## 任务状态机
- ## 上下文切换实现（汇编分析）
- ## 进程创建流程

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
        "prompt": """目标：深挖“VFS 抽象 + 挂载 + 具体文件系统实现”。

必须回答：
- VFS 抽象层：File/Inode/Dentry Traits 定义。
- 具体文件系统：支持哪些 FS（fat32, ext4, simple-fs, host-fs）？
- 根文件系统：如何挂载 RootFS？
- 文件操作：open/read/write/close 的内核路径。
- 特殊文件系统：是否有 stdio/stdout, pipe, socket？

要求：
- 定位 fs/vfs 模块。
- 分析 File trait 或类似接口。
- 深入一个具体 FS 的实现。

输出格式：
- ## VFS 架构与接口设计
- ## 具体文件系统支持情况
- ## 根文件系统挂载流程
- ## 文件操作核心路径
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
- 常见设备：
    - UART/Serial（控制台输出）
    - Block Device（磁盘读写，VirtIO-Blk）
    - Net Device（网卡，VirtIO-Net）及网络协议栈（TCP/IP, smoltcp 等实现）
    - GPU/Input（如有）
- 中断控制器：PLIC/CLINT/APIC 驱动。

要求：
- 搜索 drivers/ 目录。
- 分析 VirtIO 或 UART 驱动实现。
- 查看设备初始化链。

输出格式：
- ## 驱动框架与设备发现
- ## 字符设备驱动（UART/Console）
- ## 块设备驱动（VirtIO-Blk等）
- ## 中断控制器驱动
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
- 是否有沙箱（Sandbox）或容器支持？
- 安全启动/可信启动支持（如有）。

要求：
- 搜索 security/、auth/、permission/、capability 相关模块。
- 查找 syscall 入口处的权限检查逻辑。
- 分析用户/组/权限位的实现。

输出格式：
- ## 特权级与隔离机制
- ## 权限检查与访问控制
- ## 用户/组/权限模型
- ## 进程间隔离
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

要求：
- 搜索 net/、network/、socket/、tcp/ 相关模块。
- 查找 Socket syscall 实现。
- 分析数据包处理流程。

输出格式：
- ## 网络子系统架构
- ## Socket 接口实现
- ## 协议栈层次分析
- ## 数据包收发流程
- ## 网络配置与路由
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
- 测试用例分析：关键测试用例覆盖了哪些功能？
- QEMU/模拟器测试：如何在模拟器中运行测试？
- CI/CD 配置：.github/workflows、.gitlab-ci.yml 等。
- 测试覆盖度：是否有覆盖率统计？

要求：
- 搜索 tests/、test、spec 目录。
- 查找 CI 配置文件。
- 分析 Makefile 中的 test 目标。

输出格式：
- ## 测试框架与运行方式
- ## 单元测试分析
- ## 集成测试与系统测试
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
        "title": "执行摘要与报告整合",
        "prompt": """目标：生成执行摘要，并将前面所有章节整合成完整报告。

**重要**：前面每个阶段已经按照最终报告的章节格式输出了内容。你只需要：
1. 阅读下面 [前面阶段的分析内容] 部分
2. 提取关键发现，生成执行摘要（3-5 条核心结论）
3. 生成目录
4. 将各章内容按顺序组织

输出格式：

# [项目名] 操作系统技术分析报告

## 执行摘要
（基于下面内容提取 3-5 条核心发现：项目性质、技术特点、设计亮点）

## 目录
1. 项目概览与技术栈
2. 启动流程与架构初始化
3. 内存管理
4. 进程与调度
5. 中断与系统调用
6. 文件系统
7. 设备驱动
8. 同步与IPC
9. 多核支持与并行机制
10. 安全机制与权限模型
11. 网络子系统与协议栈
12. 调试机制与错误处理
13. 测试框架与验证机制
14. 开发历史与里程碑
15. 总结与评价

---
（然后直接输出下面各章的内容，保持原有格式，在最后添加"总结与评价"章节）

**重要**：
- 执行摘要必须基于下面的实际分析内容
- 各章内容保持原样，不要修改
- 在最后添加一个"## 15. 总结与评价"章节，综合评价项目质量
- 不要调用任何工具
""",
        "needs_previous_sections": True,
        "skip_in_report": True,  # 这个阶段的输出直接作为最终报告，不再重复包含
    },
]


def _format_tool_call_summary(tool_name: str, tool_args: dict) -> str:
    """格式化工具调用为简洁的摘要，模仿现代 agent 风格"""
    # 针对不同工具类型生成简洁摘要
    if tool_name in ("read_code_segment", "read_file"):
        file_path = tool_args.get("file_path", tool_args.get("path", "?"))
        start = tool_args.get("start_line", tool_args.get("start", ""))
        end = tool_args.get("end_line", tool_args.get("end", ""))
        # 显示完整路径
        if start and end:
            return f"{file_path} L{start}-L{end}"
        elif start:
            return f"{file_path} L{start}"
        else:
            return file_path
    
    elif tool_name in ("list_repo_structure", "list_directory"):
        path = tool_args.get("repo_path", tool_args.get("path", "?"))
        depth = tool_args.get("max_depth", "")
        dirname = os.path.basename(path.rstrip("/\\")) if path else "?"
        return f"{dirname}/" + (f" (depth={depth})" if depth else "")
    
    elif tool_name == "grep_search":
        pattern = tool_args.get("pattern", tool_args.get("query", "?"))
        path = tool_args.get("path", tool_args.get("repo_path", ""))
        dirname = os.path.basename(path.rstrip("/\\")) if path else ""
        pattern_short = pattern[:30] + "..." if len(str(pattern)) > 30 else pattern
        return f'"{pattern_short}"' + (f" in {dirname}/" if dirname else "")
    
    elif tool_name == "clone_repository":
        url = tool_args.get("repo_url", "?")
        repo_name = url.rstrip("/").split("/")[-1] if url else "?"
        return repo_name
    
    elif tool_name in ("analyze_tech_stack", "find_os_core_modules", "analyze_code_architecture"):
        path = tool_args.get("repo_path", tool_args.get("path", "?"))
        dirname = os.path.basename(path.rstrip("/\\")) if path else "?"
        return f"{dirname}/"
    
    elif tool_name in ("analyze_git_history_detailed", "get_dev_history_by_module", "generate_dev_history_charts"):
        path = tool_args.get("repo_path", "?")
        max_commits = tool_args.get("max_commits", "")
        dirname = os.path.basename(path.rstrip("/\\")) if path else "?"
        return f"{dirname}/" + (f" (max={max_commits})" if max_commits else "")
    
    else:
        # 对于其他工具，显示第一个参数的简短版本
        if tool_args:
            first_key = list(tool_args.keys())[0]
            first_val = str(tool_args[first_key])
            if len(first_val) > 40:
                first_val = first_val[:40] + "..."
            return f"{first_key}={first_val}"
        return ""


def _format_tool_result_summary(tool_name: str, content: str) -> str:
    """格式化工具返回结果为简洁摘要"""
    content_len = len(content)
    lines = content.split("\n") if content else []
    line_count = len(lines)
    
    # 根据工具类型生成不同的摘要
    if tool_name in ("read_code_segment", "read_file"):
        return f"返回 {line_count} 行代码 ({content_len} 字符)"
    
    elif tool_name in ("list_repo_structure", "list_directory"):
        # 尝试统计目录和文件数量
        dir_count = content.count("/\n") + content.count("/,")
        return f"返回目录结构 ({line_count} 项)"
    
    elif tool_name == "grep_search":
        match_count = content.count("\n") if content.strip() else 0
        return f"找到 {match_count} 个匹配"
    
    elif tool_name == "clone_repository":
        if "成功" in content or "success" in content.lower() or "cloned" in content.lower():
            return "✓ 克隆成功"
        elif "已存在" in content or "exists" in content.lower():
            return "✓ 仓库已存在"
        else:
            return f"返回 {content_len} 字符"
    
    else:
        return f"返回 {content_len} 字符 ({line_count} 行)"


def print_step(step_num: int, node_name: str, state: dict):
    """打印每一步的执行信息（简洁的 agent 风格）"""
    messages = state.get("messages", [])
    if not messages:
        return
    
    # 只显示新增的消息（避免重复）
    if step_num == 1:
        msg_to_show = messages
    else:
        msg_to_show = [messages[-1]] if messages else []
    
    for msg in msg_to_show:
        if isinstance(msg, AIMessage):
            content = msg.content or ""
            tool_calls = getattr(msg, "tool_calls", None) or []
            
            # 如果有工具调用，简洁显示
            if tool_calls:
                print(f"\n🔧 调用工具:")
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
                print(f"\n🤔 Agent: {preview}")
            
            # 打印 Token Usage（简洁版）
            metadata = getattr(msg, "response_metadata", {})
            usage = metadata.get("token_usage", {})
            if usage:
                total = usage.get("total_tokens", 0)
                if total > 0:
                    print(f"   � Tokens: {total}")
        
        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "unknown")
            content = msg.content or ""
            summary = _format_tool_result_summary(tool_name, content)
            print(f"   ✅ {tool_name}: {summary}")


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
    start_time = datetime.now()

    for idx, stage in enumerate(STAGES, 1):
        stage_id = stage["id"]
        title = stage["title"]
        prompt = stage["prompt"]

        # 文件命名：只用 title 的 slug，避免重复编号
        section_name = f"{idx:02d}_{_slug(title)}.md"
        section_path = os.path.join(sections_dir, section_name)

        # 简单的断点续传：如果文件已存在且内容看起来正常（>200字节），则跳过
        if os.path.exists(section_path):
            if os.path.getsize(section_path) > 200:
                print("\\n" + "=" * 80)
                print(f"⏭️  阶段 {idx}/{len(STAGES)}：{title} (已存在，跳过)")
                print(f"   文件: {section_path}")
                print("=" * 80)
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

        final_state = None
        try:
            # 增加 recursion_limit 防止复杂任务因步数过多而中断
            for event in agent.stream(inputs, config={"recursion_limit": 500}):
                overall_step_count += 1
                for node_name, state in event.items():
                    print_step(overall_step_count, node_name, state)
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
                
                # 如果仍然没有内容，发送追问消息让 Agent 生成报告
                if not stage_text or len(stage_text) < 100:
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
                            for node_name, state in event.items():
                                print_step(overall_step_count, node_name, state)
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
        skip_in_report = stage.get("skip_in_report", False)
        if skip_in_report:
            print(f"\n⏭️  阶段 {idx} 标记为 skip_in_report，不写入报告")
        else:
            try:
                with open(section_path, "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n\n")
                    f.write(stage_text.strip() + "\n")
                all_section_paths.append(section_path)
                print(f"\n✅ 已保存阶段输出: {section_path}")
            except Exception as e:
                print(f"\n⚠️  无法写入阶段文件 {section_path}: {e}")

    # 合并总报告（简单拼接；最终质量可在 15_final 阶段内由模型完成）
    final_report_path = os.path.join(repo_output_dir, "report.md")
    try:
        with open(final_report_path, "w", encoding="utf-8") as out:
            out.write(f"# {repo_name} OS 项目技术分析报告\\n\\n")
            out.write("## 目录\\n\\n")
            for p in all_section_paths:
                t = os.path.splitext(os.path.basename(p))[0]
                out.write(f"- {t}\\n")
            out.write("\\n---\\n\\n")
            for p in all_section_paths:
                out.write(f"\\n\\n---\\n\\n")
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    out.write(f.read())
        print(f"\\n📄 已生成总报告: {final_report_path}")
    except Exception as e:
        print(f"\\n⚠️  无法生成总报告: {e}")

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print("\\n" + "=" * 80)
    print("✅ 多阶段任务完成！")
    print(f"   总步数: {overall_step_count}")
    print(f"   耗时: {elapsed:.2f} 秒 ({elapsed/60:.2f} 分钟)")
    print(f"⏰ 结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
