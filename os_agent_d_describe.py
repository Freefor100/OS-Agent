# os_agent_d_describe.py
#
# 每阶段 Cursor 式管线（固定）:
#   ① Plan     — 阶段提示词 + 启发式 plan + LLM 自主探索 → 锁定计划与 execution_steps（须按序执行）
#   ② Execute  — 按锁定步骤与「执行契约」ReAct 写章节
#   ③ Verify   — ReAct+stream 审阅（与 ② 同构；JSON 失败则 invoke 回退，再失败则规则审阅）
#   ④ Patch 计划 — ReAct+stream 压缩为 ≤6 条修补步骤（失败则 invoke 回退）
#   ⑤ Apply    — 仅按 ④ 执行 repair；必要时 re-review
#
# API Key / MODEL_NAME 等仍从仓库根目录 .env 读取（load_dotenv）。
#
import os
import re
import sys
import time
import logging
from datetime import datetime

import langchain
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage

from core.agent_builder import (
    build_executor_agent,
    build_planner_agent,
    build_reviewer_llm,
    SYSTEM_PROMPT,
)
from core.utils import repo_name_from_url, format_tool_call_summary, format_tool_result_summary
from core.error_handling import ErrorType, RetryConfig, classify_error, calculate_backoff, ErrorTracker
from core.per_types import StageState
from core.per_planner import (
    apply_llm_plan_overlay,
    build_repo_profile,
    build_dynamic_context,
    ensure_execution_steps,
    plan_stage,
    render_plan_context,
)
from core.per_executor import extract_stage_artifacts
from core.per_reviewer import review_stage, re_review_stage
from core.per_llm_stages import (
    PATCH_PLAN_RECURSION_LIMIT,
    PLANNER_RECURSION_LIMIT,
    VERIFY_RECURSION_LIMIT,
    run_llm_planning_agent,
    run_llm_patch_plan,
)
from core.per_repair import DEFAULT_REPAIR_RECURSION_LIMIT, repair_stage

langchain.debug = True
load_dotenv()

OUTPUT_DIR = "./output"

# 注入 Execute 任务：约束范围与顺序（对齐 Cursor scoped agent）
CURSOR_EXECUTION_CONTRACT = """
---
## 【执行契约 — 已锁定计划】
上文「阶段执行计划」与「须按序完成的执行步骤」为本阶段**唯一**工作范围与顺序约束。你必须：
1. **严格按 execution_steps 顺序** 调用工具并组织正文，勿跳步、勿倒序。
2. 步骤未点名的话题不要擅自展开成长篇；优先满足 must_cover 与 evidence_targets。
3. 结论须带可核验的源码路径（反引号）；证据不足时显式降级，禁止无路径硬断言。
---
"""

import openpyxl
def normalize_url(url: str) -> str:
    """标准化仓库 URL，剔除 .git 后缀、结尾斜杠并统一小写"""
    if not url:
        return ""
    url = str(url).strip().lower()
    # 先剔除结尾斜杠
    while url.endswith("/"):
        url = url[:-1]
    # 再剔除 .git 后缀
    if url.endswith(".git"):
        url = url[:-4]
    # 再次剔除可能出现的结尾斜杠（例如 .git/ 情况）
    while url.endswith("/"):
        url = url[:-1]
    return url


def get_author_info(repo_url: str) -> dict:
    """从 collected-data.xlsx 提取作者信息"""
    try:
        xlsx_path = "collected-data.xlsx"
        if not os.path.exists(xlsx_path):
            return {}
            
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        sheet = wb.active
        
        # 寻找列索引
        headers = {}
        for col_idx, cell in enumerate(sheet[1], 1):
            if cell.value:
                headers[str(cell.value).strip()] = col_idx
                
        repo_col = headers.get("仓库地址")
        if not repo_col:
            return {}
            
        for row in range(2, sheet.max_row + 1):
            cell_url = sheet.cell(row=row, column=repo_col).value
            if cell_url and normalize_url(cell_url) == normalize_url(repo_url):
                result = {}
                mapping = {
                    "year": "年份",
                    "competition": "赛事",
                    "sub_competition": "子赛事",
                    "school": "学校",
                    "team": "队伍名称"
                }
                for key, col_name in mapping.items():
                    col_idx = headers.get(col_name)
                    if col_idx:
                        val = sheet.cell(row=row, column=col_idx).value
                        result[key] = str(val).strip() if val is not None else ""
                return result
    except Exception as e:
        print(f"  ⚠️  读取 collected-data.xlsx 失败: {e}")
    return {}


def _slug(s: str) -> str:
    keep = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    out = "".join(keep).strip("_")
    return out[:60] if out else "section"


def _build_base_context(repo_url: str, output_dir: str) -> str:
    """构建基础上下文信息。
    
    Args:
        repo_url: 仓库 URL
        output_dir: 输出目录
    """
    repo_name = repo_name_from_url(repo_url)
    # 与 tools.git_ops.get_repo_local_path 保持一致：./repos/<repo_name>
    repo_path = os.path.normpath(os.path.join("./repos", repo_name))
    charts_dir = os.path.normpath(os.path.join(output_dir, "charts"))
    sections_dir = os.path.normpath(os.path.join(output_dir, "sections"))
    
    # 后续阶段直接使用 repo_path
    repo_hint = f"**仓库已就绪**: 直接使用 repo_path = \"{repo_path}\"。"

    return f"""你是一个操作系统项目的技术分析 Agent。请严格基于仓库中的代码与文档输出结论，避免空泛。

基础信息：
- 仓库 URL: {repo_url}
- 本地路径 repo_path: {repo_path}
- 输出目录 output_dir: {output_dir}
- 图表目录 charts_dir: {charts_dir}
- 分段输出目录 sections_dir: {sections_dir}

{repo_hint}

全局要求（严格遵守）：
1. **反向证据原则**：如果未找到某功能的实现代码，你必须明确说明“未发现”或“未实现”。**严禁**仅仅因为它是“操作系统”就假设它实现了某些标准功能（如分页、多户）。
2. **证据引用**：描述任何关键结论（如“支持分页”）时，必须附带文件路径或代码片段引用（如 `mm/page.rs: map_page()`）。
3. **语义发现与拓扑追踪**：
   - 🔍 **第一优先级：语义切入**。在分析任何子系统前，**必须首先调用 `rag_search_code` 进行语义搜索**（例如：“寻找页表映射的实现”）。这能帮你穿透复杂的目录结构，直接定位到最相关的代码块。
   - 🌳 **第二优先级：拓扑展开**。通过 RAG 获得核心符号后，立即使用 `lsp_get_call_graph` 展开多层递归调用树，利用 `lsp_get_definition` 等 LSP 工具构建精确的 AST 画布。
   - 🛠️ **第三优先级：降级与查漏**。仅当 RAG 和 LSP 均返回为空或需要确切宏定义时，才触发 `grep_in_repo`。读取代码片段必须使用 `read_code_segment` 且仅限于关键逻辑。
4. **LSP 退避策略（必读）**：当 LSP 不可用或超时时，`lsp_get_definition` / `lsp_get_references` 会自动退避（Tree-sitter → 语言感知正则 → 通用 grep → ASM）。退避结果会附带 `[Fallback Metadata]`，含 `confidence=high|medium|low`。当 `confidence=low` 或结果含 `[Generic Fallback]` / `[ASM Fallback]` 时，在报告中必须标注「以上为静态分析结果，精度有限」，与 Call Graph 的 Grep 降级标注保持一致。
5. **多模块搜索**：不要局限于单一目录。使用 `find_os_core_modules` 寻找分散的实现（例如驱动可能在 `drivers/` 也可能在 `modules/`）。
6. **区分规划与实现**：README 中提到的功能可能是“画饼”，必须通过代码验证。未能验证的特性即使出现在文档中，也必须标注为“文档提及但未见代码”。
7. **桩代码检测（Strict Stub Detection）**：
   - 遇到函数体为空、返回 `unimplemented!()`、`todo!()`、`ENOSYS` 或仅有一行 `Ok(0)` 的情况，**必须**标注为 **“桩函数”** 或 **“未实现”**。
   - **严禁**将桩函数描述为“已实现功能”。如果一个系统调用仅返回 0 而无实际逻辑（如 `sys_getuid` 始终返回 0），必须指出“仅有接口无实现”。
8. **文件路径验证（Anti-Hallucination）**：
   - 在引用文件路径前，**必须**确保该文件在 `list_repo_structure` 或 `find_by_name` 的结果中真实存在。
   - **严禁**捏造不存在的文件路径（如声称 `riscv/boot.rs` 存在但实际不在）。如果不确定，不要写路径。
9. **头文件 vs 实现**：
   - 不要把头文件（`.h`）或 Trait 定义（`.rs` 中的 `trait`）作为功能已实现的证据。必须找到对应的 C 文件（`.c`）或 Rust `impl` 代码块。

输出使用 Markdown，面向"懂 OS 的读者"，每个小节都要解释组件原理 + 在本仓库的具体实现方式。

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
        "id": "02_boot_arch",
        "title": "启动流程与架构初始化",
        "prompt": """目标：分析“从复位/Bootloader 到内核 main 函数”的完整流程及架构相关初始化。

必须回答：
- 启动入口在哪里？（汇编文件如 entry.S 或 head.S，链接脚本 linker.ld 中的 ENTRY）
- CPU 模式切换与初始化（如 RISC-V M-Mode -> S-Mode，x86实模式->保护模式->长模式）。**必须验证是否真的发生了模式切换（查找 sstatus.spp, mstatus.mpp, cr0 等寄存器操作）。**
- 关键寄存器设置（栈指针 SP、页表基址 SATP/CR3、中断向量表 stvec 等）。
- 它是如何跳转到 Rust/C 入口函数的？
- 早期初始化做了什么（BSS 清零、早期串口打印、设备树解析、页表初始化时机）？
- **浮点单元 (FPU) 初始化**：搜索 `sstatus.fs` (RISC-V) 或 `cpacr_el1` (AArch64) 或 `cr4` (x86_64)。如果没有找到相关代码，**必须明确说明未启用 FPU（状态为未实现）**。
- **多平台适配**：
    - **StarFive VisionFive2**：搜索 `visionfive` 或 `jh7110`，分析其启动流程特异性（SBI -> U-Boot）。
    - **LoongArch**：搜索 `loongarch`，分析其启动流程。
- **平台与构建配置**：使用 grep_in_repo 搜索 `.toml`/`defconfig`/`Kconfig` 配置文件，分析构建系统如何选择编译目标和平台参数。
- **固件级启动链（RISC-V 必须）**：如果是 RISC-V，必须描述 SBI->U-Boot->OS 的完整固件级启动链。搜索 `sbi|opensbi|u-boot` 关键词。分析 SBI 如何将控制权移交给内核。
- **MMU 启用前后串口地址切换**：在 UART 初始化代码中，分析 MMU 启用前（物理地址直接访问）和 MMU 启用后（虚拟地址访问）的串口地址切换逻辑。搜索 `phys_to_virt|virt_to_phys` 或 UART 基址相关常量。
- **架构对齐检查（Architecture Alignment Check）**：在深入分析初始化代码前，先确认当前 LSP 的 Target Triple 与你正在分析的架构分支（如 `arch/riscv64`）是否匹配。通过读取 `.cargo/config.toml` 或 `Makefile` 获取精准 Triple。**如果发现不匹配或代码块被 `#[cfg]` 灰化，必须调用 `lsp_set_target_arch` 进行强制校准并重启分析。**

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "boot", "_start", "kernel_main", "architecture initialization" 锁定启动入口文件。
- 使用 `lsp_get_document_outline` **先**查看 arch 初始化文件的整体结构（函数列表+行号），然后有目的地 `read_code_segment` 关键段。
- 使用 `lsp_get_definition` 追踪 `_start` → `rust_main` / `kernel_main` 的跨文件调用链。每一跳都用 LSP 定位下一个函数的定义位置，**不要凭经验猜路径**。
- **【必须】使用 `lsp_get_call_graph` 生成启动函数完整调用链**：
  - 对 `rust_main` 或 `kernel_main`（定位到实际文件后）调用 `lsp_get_call_graph(repo_path, file_path, "rust_main", direction="outgoing", max_depth=4)`
  - 如返回 `[⚠️ DEGRADED MODE]`，说明 LSP 降级至 Grep 分析，仍需使用该结果并在报告中标注"DEGRADED — 静态 Grep 分析"。
- 使用 `lsp_get_references` 查找谁调用了关键初始化函数（如 `init_mmu`、`setup_trap`），验证其在启动流程中的位置。
- 辅以 `grep_in_repo` 搜索汇编入口（`entry.S`/`start.S`）和 `list_repo_structure` 浏览目录。
- 重点关注 arch/、platform/、boot/ 目录下的初始化代码。
- **完整追踪**：从 `_start` 到内核 main 函数的每一步调用链，引用文件路径和行号。
- **严禁幻觉**：
    1. **汇编入口**：先在 `arch/` 或 `platform/` 下找 `entry.S`, `head.S`, `start.S`。
    2. **Rust入口**：如果找不到汇编入口，可能是通过 SBI/U-Boot 直接跳转到 Rust 入口，请寻找 `#[entry]`。
    3. **路径验证**：写下任何文件路径前，必须确认该文件真实存在。
- **FPU/模式切换验证**：
    - RISC-V: 搜索 `sstatus.fs` 或 `FS:` 常量。
    - AArch64: 搜索 `cpacr_el1` 或 `CPACR`。
    - x86_64: 搜索 `cr0`, `cr4` 寄存器位操作。

输出格式：
- ## 启动入口与链接脚本分析
- ## 架构初始化流程（模式切换/FPU/MMU）
- ## 到达内核主函数的路径（完整调用链）
- ## 多平台启动流程（StarFive/LoongArch 等）
- ## 平台配置与构建机制
- ## 关键代码片段分析

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "03_mem_mgmt",
        "title": "内存管理（物理/虚拟/分配器）",
        "prompt": """目标：深挖“物理内存管理 + 虚拟内存管理 + 堆/页分配器”。

必须回答（并在源码中找到对应实现）：
- 物理内存管理：使用什么算法（Bitmap/Buddy System）？FrameAllocator 接口在哪里？
- 虚拟内存管理：页表如何操作（PageTable 结构、walk/map/unmap 实现）？
- 内核与用户地址空间设计：是否独立？内核重映射？
- 堆分配器：使用了什么 Allocator（GlobalAlloc, slab, buddy）？
- **堆管理 (brk/sbrk)**：搜索 `sys_brk`，是否支持惰性分配（仅调整边界不立即分配物理页）？
- **用户指针安全**：搜索 `UserInPtr|UserOutPtr|verify_area|check_region`，分析系统调用入口处如何验证用户空间指针合法性。
- 缺页异常（Page Fault）处理逻辑（如有）。**追踪 handle_page_fault 调用链**。
- **进程级映射管理**：搜索地址空间管理结构（如 `VmAreaStruct`、`BTreeMap` 管理的映射区间），分析是否有反向映射表（rmap）支持。
- **高级特性验证**（必须分类为 `✅ 已实现`、`🔸 桩函数`、`❌ 未实现`，并寻找具体代码）：
  - 写时复制（Copy-on-Write）：搜索 `cow|copy_on_write`，确认是否在 page fault 中处理了 CoW。
  - 懒分配（Lazy Allocation）：搜索 `lazy|populate`，确认是否推迟了物理页分配。
  - 共享内存管理（SharedMem）：是否有 `shm` 相关系统调用和数据结构？**深入分析**：搜索 `sys_shmdt` 实现，检查是否使用 `BTreeMap` 进行 O(log n) 定位。搜索 `SharedMemoryManager`，分析 `IPC_RMID` 删除策略（立即删除 vs Arc 引用计数延迟释放）。
  - **反向映射表（rmap）**：搜索 `rmap|reverse_map|page_to_vma`，检查是否有物理页到虚拟页的反向映射机制。
  - 交换区/页面置换（Swap）：是否实现了 `swap_out`/`swap_in`？
  - **大页支持（Huge Page）**：在页表映射中是否处理了 2M/1G 页面？搜索 `HugePage|MapSize::2M|MapSize::1G`。
  - **零拷贝与 mmap**：搜索 `mmap` 实现，验证是否支持文件映射？是否支持零拷贝IO（sendfile/splice）？**注意：如果是 `mmap` 系统调用，检查它是否真的实现了 MAP_FIXED/MAP_ANON 等标志的处理，还是仅仅是一个空壳？（如果是空壳/仅返回0，标注为桩函数）**

**强制要求**：
- **语义发现（🥇 首选）**：调用 `rag_search_code` 搜索 "page table", "buddy system", "slab allocator", "mmap implementation" 定位核心内存管理源码。
- 对于上述每一个特性，如果支持，必须引用代码文件和行号。
- 如果不支持，必须明确写“未发现实现”或“❌ 未实现”。
- 追踪一个完整的 `page fault` -> `alloc_frame` -> `map_page` 流程。
- **LSP 工具使用要求**：
    - 使用 `lsp_get_definition` 定位 `PageTable`、`FrameAllocator`、`MemorySet` 等核心结构体的精确定义，**不要凭记忆描述字段**。
    - **【必须】使用 `lsp_get_call_graph` 追踪缺页异常完整链路**：
      - `lsp_get_call_graph(repo_path, file_of_handle_page_fault, "handle_page_fault", direction="both", max_depth=3)` — 谁触发缺页，它又调用什么？
      - `lsp_get_call_graph(repo_path, file_of_alloc_frame, "alloc_frame", direction="incoming", max_depth=2)` — 谁调用了物理页分配？
      - 如返回 `[⚠️ DEGRADED MODE]`，在报告中标注"DEGRADED — 基于 Grep 静态分析"并继续使用结果。
    - 使用 `lsp_get_references` 追踪 `handle_page_fault` 的调用方（谁调用了它？）。
    - 使用 `lsp_get_document_outline` 快速浏览内存管理大文件的函数列表，再有目的地读取关键实现。
- **防幻觉检查**：
    - **mmap**: 不要看到 `Mmap` 结构体就认为实现了 mmap。检查系统调用入口 `sys_mmap`。
    - **Stub检测**：如果 `sys_mmap` 只是返回 `0` 或 `Ok`，没有处理 `MAP_FIXED` / `MAP_ANON` 等标志，必须标记为 **Stub**。
    - **Swap**: 必须找到 `swap_out` / `swap_in` 的实际逻辑，而不仅仅是特质定义。

输出格式：
- ## 物理内存管理实现（代码引用）
- ## 虚拟内存与页表操作（代码引用）
- ## 地址空间布局（内核 vs 用户）
- ## 堆分配器解析
- ## 高级内存特性清单（CoW/Lazy/Swap/HugePage - 已实现/未实现）
- ## 关键代码片段与调用链分析

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "04_process_sched",
        "title": "进程/线程与调度机制",
        "prompt": """目标：深挖“任务模型 + 调度算法 + 上下文切换”。

必须回答：
- 执行实体：Process/Thread/Task 结构体包含哪些字段（Context, State, TrapFrame）？
- **任务模型扩展**：使用 grep_in_repo 搜索 `Process|ProcessGroup|Session|process`，检查是否存在进程组、会话管理以及 PID/TID 分配机制。
- 调度策略：算法是什么（FIFO, RR, Priority, Stride, CFS）？Scheduler 实现细节。
- 状态流转：Ready/Running/Blocked/Exited 状态机。
- 上下文切换：switch.S 或类似汇编代码，保存了哪些寄存器？
- **高级特性验证**（必须分类为 `✅ 已实现`、`🔸 桩函数`、`❌ 未实现`，并寻找具体代码）：
    - **信号机制 (Signal)**：使用 grep_in_repo 搜索 `signal|sigaction|kill`，确认是否实现了信号注册与分发？
    - **Futex**：搜索 `futex|wait_queue`，是否支持快速用户态互斥锁？
- **深度调用链追踪（必须）**：
    - `fork()`: 追踪从系统调用到 `clone_task` / `copy_task` 的完整流程。**必须验证**是否真的复制了地址空间（`memory_set.copy()`）和文件表？
    - `exec()`: 如何加载 ELF？如何重建地址空间？
    - `schedule()`: 调度器被谁调用？**验证优先级**：`pick_next_task` 是否真的使用了 `priority` / `stride`，还是仅仅 FIFO？
    - `exit()`: 资源回收流程，父进程通知。
- 进程与线程的区别：代码中是否区分了 TCB 和 PCB？还是只有 Task？
- **层次结构 ID 规则**：搜索 `pgid|session_id|set_sid|setpgid`，分析 PGID（进程组 ID = 组长 PID）和 SID（会话 ID = 会话组长 PGID）的分配规则。
- **POSIX 资源限制**（必须分类为 `✅ 已实现`、`🔸 桩函数`、`❌ 未实现`）：搜索 `rlimit|RLIMIT|getrlimit|setrlimit|resource_limit`，检查是否实现了资源限制。如果找到，列出支持的资源类型数量（POSIX 定义了 16 种）及软/硬限制双机制。

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "task structure", "scheduler algorithm", "context switch", "fork implementation" 快速锁定进程管理模块。
- 使用 `lsp_get_definition` 定位 `Task`/`Process`/`TaskInner` 结构体定义，精确列出其字段（不要猜）。
- 使用 `lsp_get_references` 追踪 `fork`/`exec`/`schedule`/`exit` 的完整跨文件调用链。
- 使用 `lsp_get_document_outline` 快速查看调度器文件中的所有函数，找到 `pick_next_task`、`schedule` 等关键入口。
- **【必须】使用 `lsp_get_call_graph` 生成核心进程操作的调用树**：
  - `lsp_get_call_graph(repo_path, file_of_sys_fork, "sys_fork", direction="outgoing", max_depth=4)` — fork 从 syscall 到内存复制的完整下行链
  - `lsp_get_call_graph(repo_path, file_of_schedule, "schedule", direction="both", max_depth=3)` — 谁触发调度？调度器下一步调什么？
  - 如返回 `[⚠️ DEGRADED MODE]`，标注"DEGRADED — 基于 Grep 静态分析"并继续使用结果。
- **重要**：不要只看一个模块！用 find_os_core_modules 或 grep_in_repo 搜索所有进程/线程相关模块。
- 查找 context_switch 汇编代码。

输出格式：
- ## 任务模型与核心数据结构
- ## 调度算法与策略（代码证据）
- ## 任务状态机
- ## 上下文切换实现（汇编分析）
- ## 进程间通信与同步（Signal/Futex）
- ## 关键流程追踪（Fork/Exec/Schedule/Exit）
- ## 进程/线程管理模块扩展

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "05_trap_syscall",
        "title": "中断、异常与系统调用",
        "prompt": """目标：分析“Trap 处理流程 + 系统调用分发”。

**注意**：不要假设所有代码都在 `src/` 下。如果基于 ArceOS，Trap 和 Syscall 可能在 `modules/axhal` 或 `modules/axruntime` 中。

必须回答：
- Trap 入口：trap_handler / trap_vector 在哪里？如何区分中断（Interrupt）和异常（Exception）？
- 上下文保存：TrapFrame / GeneralRegisters 结构体。**必须用 `lsp_get_definition` 或 `read_code_segment` 读取结构体定义，精确统计包含的寄存器数量和总字节数**，不要凭经验估算。
- **系统调用分发追踪**：
    - 用户态 `ecall`/`syscall` 指令。
    - 内核态 `syscall_handler` 分发逻辑。
    - **必须找到分发表**（syscall table 或 match 语句）。
    - **Stub验证**：检查核心 syscall（如 `sys_clone`, `sys_exec`, `sys_mmap`, `sys_write`）等是否直接返回错误、返回 0，或者包含了 `todo!()`/`unimplemented!()`？
    - **覆盖度统计**：基于上述验证，明确区分并列出“已注册但仅为桩特征（`🔸 桩函数`）”的 syscall 数量，与“完整功能实现（`✅ 已实现`）”的 syscall 数量。
    - 选择一个具体 syscall（如 `sys_write`）追踪其从 Trap 到真正处理逻辑的路径。
- **接口/实现分离模式**：如果项目采用了 syscall 接口与实现分离的设计（如 `sys_xxx` 为接口，`sys_xxx_impl` 为实现），必须明确描述此模式。搜索 `_impl` 后缀函数。
- **用户指针语义化包装**：搜索 `UserInPtr|UserOutPtr|UserInOutPtr`，如果存在此类类型安全包装，需描述其在 syscall 入口处的作用。
- **外部中断流**：详细分析时钟中断（Timer）处理流程与外部设备中断（如 PLIC/APIC）的分发处理。
- **信号机制（必须深入）**：
    - 搜索 `handle_signal|do_signal|POST_TRAP`，分析信号是否在 Trap 返回前被处理。
    - **三种粒度**：搜索 `sys_kill|sys_tkill|sys_tgkill`，分析是否支持线程级/进程级/进程组级信号发送。
    - **SIGSEGV**：搜索 `SIGSEGV|sig_segv`，分析非法内存访问时是否发送 SIGSEGV 信号。
    - **用户自定义信号处理函数**：搜索 `sigreturn|signal_trampoline|trampoline`，分析是否有从内核跳到用户态信号处理函数的跳板代码机制。
- **缺页异常与内存特性关联（必须）**：
    - 追踪缺页异常处理链，分析它如何触发 **CoW**（写时复制）和 **Lazy Allocation**（懒分配）。
    - 搜索 `handle_page_fault|do_page_fault|cow|lazy|alloc`，追踪从 Trap 入口到内存管理模块的完整调用链。

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "trap handler", "syscall table", "interrupt vector", "ecall handling" 精准定位异常分发代码。
- 使用 `lsp_get_definition` 追踪 syscall 分发链：从 `trap_handler` → `syscall_handler` → 具体 `sys_xxx`，每一跳精确定位。
- 使用 `lsp_get_document_outline` 查看 trap.rs / syscall.rs 的完整函数列表，掌握所有已实现的 syscall。
- 使用 `lsp_get_references` 查找 `TrapFrame` 在哪些函数中被使用，验证上下文保存/恢复的完整性。
- **【必须】使用 `lsp_get_call_graph` 追踪 Trap 完整调用链**：
  - `lsp_get_call_graph(repo_path, file_of_trap_handler, "trap_handler", direction="outgoing", max_depth=4)` — 从 trap 入口展开完整分发树
  - `lsp_get_call_graph(repo_path, file_of_sys_write, "sys_write", direction="incoming", max_depth=2)` — 谁调用了 sys_write？
  - 如返回 `[⚠️ DEGRADED MODE]`，标注降级模式继续使用，关注 outgoing 结果中分发表函数的覆盖情况。
- 辅以 `grep_in_repo` 搜索 `trap_handler|trap_return|syscall_handler` 确定文件位置。
- 找到 trap.S / trap.rs，分析 syscall 分发表。

输出格式：
- ## Trap 处理流程（用户态 <-> 内核态）
- ## 异常向量表与入口
- ## 系统调用分发机制（追踪 sys_write）
- ## 核心 Syscall 实现列表
- ## 中断处理与信号关联
- ## 关键代码片段

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "06_fs_vfs",
        "title": "文件系统（VFS + 具体 FS）",
        "prompt": """目标：深挖"VFS 抽象 + 挂载 + 具体文件系统实现"。

必须回答：
- VFS 抽象层：File/Inode/Dentry Traits 定义。
- **具体文件系统（必须代码验证）**：
  - FAT32/Ext4：是否自己实现了？还是用的 crate？（check Cargo.toml）。**注意：对于组件化的 OS（如 ArceOS），具体的文件系统实现可能独立于 VFS 存在于诸如 `arceos/modules/axfs-ng/src/fs/fat/` 或 `ext4/` 目录中，务必使用搜索功能仔细查找，绝对不要仅仅因为特定目录下没有就断言未实现！**
  - **具体 FS 的抽象层结构**：搜索 `FatFilesystemInner|Ext4Filesystem|FatFileNode|FatDirNode` 等，分析各层如何实现 VFS trait。这是文件系统架构的核心。
  - RamFS/TmpFS：是否有内存文件系统？
- **伪文件系统**：使用 grep_in_repo 搜索 `devfs|procfs|sysfs` 检查是否实现了伪文件系统。若有，分析其实现方式。
- 文件描述符表：Global 还是 Per-Process？`fd_table` 结构在哪？
- **功能细节**（必须分类为 `✅ 已实现`、`🔸 桩函数`、`❌ 未实现`）：
  - 是否支持 `pipe` 套接字？
  - 是否支持网络 `socket`？
  - 是否支持 `mmap`？**注意**：必须检查 `sys_mmap` 实现。如果是 **零拷贝**，必须看到 `VmArea` 结构体中有 `shared` 字段或 `MAP_SHARED` 处理逻辑。如果是 `sys_mmap` 仅返回 Ok(0) 没有处理标志位，标注为'桩函数'。
  - **高级特性**：`poll`/`select`/`epoll` 是否实现？搜索 `sys_poll` / `sys_select` / `sys_epoll`，检查是一律返回 Ready 还是真的检查了文件状态？
  - **如果上述功能未找到代码，明确写“未实现（❌ 未实现）”**。

- **文件打开流程**：追踪从 `sys_open` 到最终获得文件描述符的完整调用链，说明超级块、Inode、Dentry、File 四大核心数据结构如何协同。

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "VFS trait", "FAT32 implementation", "file descriptor table", "mount logic" 锁定文件系统核心实现。
- 使用 `lsp_get_definition` 定位 `File` trait、`Inode` trait、`SuperBlock` 等 VFS 核心抽象的精确定义。
- 使用 `lsp_get_references` 追踪 `sys_open` → `vfs_open` → 具体 FS `open` 的完整调用链。
- **【必须】使用 `lsp_get_call_graph` 追踪文件打开完整路径**：
  - `lsp_get_call_graph(repo_path, file_of_sys_open, "sys_open", direction="outgoing", max_depth=4)` — 从 syscall 到 VFS 再到具体 FS 的完整下行链
  - `lsp_get_call_graph(repo_path, file_of_vfs_open, "vfs_open", direction="both", max_depth=3)` — VFS 中枢节点双向（谁调它，它调谁）
  - 如返回 `[⚠️ DEGRADED MODE]`，标注"DEGRADED — 静态 Grep 分析"并继续使用，重点关注 outgoing 中 FS trait impl 的调用。
- 使用 `lsp_get_document_outline` 快速摸清 VFS 和具体 FS 实现文件的内部结构。
- 使用 grep_in_repo 搜索 "FdTable|FileDescriptor|fd_table" 确认文件描述符表实际命名。
- **路径精确性（关键）**：注意区分相似目录（如 `core/file/` vs `core/fs/`，`src/fs/imp/` vs `api/src/core/fs/imp/`）。引用每个文件前必须用 `lsp_get_definition` 确认函数的真实定义位置。如果同一模块在多个目录中有实现（如 TmpFS 在 `src/` 和 `api/src/` 中都有），必须全部列出。

输出格式：
- ## VFS 架构与接口设计
- ## 具体文件系统支持情况（FAT32/Ext4/RamFS）
- ## 文件描述符与进程关联
- ## 管道(Pipe)与套接字(Socket)支持情况
- ## 缓存机制（Block/Page Cache）
- ## 零拷贝映射验证（mmap 实现分析）
- ## 关键代码验证

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "07_device_drivers",
        "title": "设备驱动与硬件抽象",
        "prompt": """目标：分析“设备树/总线 + 驱动框架 + 具体设备驱动”。

**注意**：如果是组件化 OS（如 ArceOS），驱动可能位于 `modules/axdriver` 或独立的 crate 中，不要只在 `drivers/` 目录下找。

必须回答：
- 设备发现：Device Tree (DTS) 解析或 PCI/Bus 扫描？**必须验证**是否真的解析了 `.dtb` 文件，还是硬编码了地址？
- 驱动框架：Driver Trait，如何注册/初始化驱动？
- **组件化与配置**：搜索构建配置文件（Cargo.toml 的 features、Kconfig、条件编译宏），分析如何通过编译选项选择不同的驱动/模块实现。
- **平台适配**：搜索 `platform/` 或 `boards/` 目录，列出所有支持的目标平台/开发板及其特有驱动，分析项目如何适配不同硬件。
- 常见设备：
    - UART/Serial（控制台输出）
    - Block Device（磁盘读写，VirtIO-Blk）
    - Net Device（网卡，VirtIO-Net）及网络协议栈（TCP/IP, smoltcp 等实现）
    - GPU/Input（如有）
- 中断控制器：PLIC/CLINT/APIC 驱动。
- **MMU 前后串口地址切换**：分析 UART 驱动在 MMU 启用前（使用物理地址）和 MMU 启用后（使用虚拟地址）的地址切换机制。搜索串口基址常量的不同定义。

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "device driver trait", "virtio-blk driver", "UART initialization", "PCI bus scanning" 快速锁定驱动程序。
- 使用 `lsp_get_definition` 定位 Driver trait 定义和各设备驱动的 trait impl。
- 使用 `lsp_get_references` 追踪 `init_drivers` / `probe` 的调用链，理解驱动注册与初始化顺序。
- 使用 `lsp_get_document_outline` 浏览驱动文件结构，快速发现所有设备相关的 struct 和 impl。
- 辅以 grep_in_repo 搜索 `axdriver` 或 `driver::` 和构建配置中的 feature flags。

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
        "id": "08_sync_ipc",
        "title": "同步互斥与进程间通信",
        "prompt": """目标：分析“同步原语 + 锁机制 + IPC”。

必须回答：
- 锁机制：SpinLock / Mutex / Semaphore / RwLock 实现。
    - **原子操作**：是使用 Rust `core::sync::atomic` 还是自定义汇编？(grep `ldxr/stxr`, `lock xchg`)
    - **等待队列 (WaitQueue)**：线程获取锁失败时如何挂起？（find `WaitQueue`, `sleep`, `block`）
- **IPC 机制（必须代码验证并分类为 `✅ 已实现`、`🔸 桩函数`、`❌ 未实现`，谨防桩代码）**：
    - 管道 (Pipe)：**实现验证**：是否使用了环形缓冲区 (Ring Buffer) 还是简单字节流？
    - 消息队列 (MessageQueue)：**必须检查实现**。grep `sys_msgget` 或 `msgget`。
        - 如果函数体为空、`Ok(0)` 但没有队列逻辑，必须标记为 **`🔸 桩函数`**。
        - 只有看到了完整的队列结构体操作（push/pop），才可标记为 **`✅ 已实现`**。
    - 共享内存 (SharedMem)：结合内存管理章节分析（SharedMemoryManager 实现）。
    - 信号量 (Semaphore)：PV 操作实现。同样需要检查 `sys_semget`, `semop` 区分是否为桩代码。
    - **信号 (Signal) 作为 IPC**：搜索 `sys_kill|sig_send|signal_send`，分析信号分发机制是否也用于进程间通信。
    - **信号处理时机**：搜索 `POST_TRAP|do_signal|handle_pending_signal`，分析信号在 Trap 返回用户态前的确切处理位置。
- **关键流程的跨文件调用链**：对 Futex 等待/唤醒流程，使用 `lsp_get_call_graph` 递归展开完整调用树（优先于 `lsp_get_references` 的单层查找）。

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "SpinLock implementation", "Mutex wait queue", "Pipe ring buffer", "shared memory manager" 锁定同步与 IPC 源码。
- 使用 `lsp_get_definition` 定位 `Mutex`、`SpinLock`、`WaitQueue` 的结构体定义和 `lock()`/`unlock()` 实现。
- **【必须】使用 `lsp_get_call_graph` 展开关键 IPC 流程调用链**（`sys_futex` → `futex_wait` → `WaitQueue::sleep`）：
  - `lsp_get_call_graph(repo_path, file_of_sys_futex, "sys_futex", direction="outgoing", max_depth=4)`
  - 如返回 `[⚠️ DEGRADED MODE]`，标注后继续使用 Grep 结果。
- 使用 `lsp_get_references` 查找单节点引用（如哪些地方调用了 `futex_wake`）。
- 使用 `lsp_get_document_outline` 浏览 IPC 模块文件，发现所有 Pipe/Sem/Shm 实现。
- 辅以 grep_in_repo 搜索 sync/、ipc/ 模块。
- **验证消息队列与信号量**：务必区分 Stub（桩）与 Real Implementation（真实实现）。

输出格式：
- ## 同步与互斥原语（锁与原子操作）
- ## 等待队列实现机制
- ## 进程间通信（Pipe/MsgQueue/Sem）
- ## 关键代码片段
- ## 未实现/桩函数功能列表（明确列出哪些是“画饼”）

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "09_smp_multicore",
        "title": "多核支持与并行机制",
        "prompt": """目标：分析多核/SMP（对称多处理）支持实现。

必须回答：
- **核心任务：一定要极其仔细地在源码中寻找有没有真正实现多核！** 架构设计是 SMP 还是 AMP？**绝不能仅凭看到一两个宏定义就断言支持多核，必须找到唤醒其他核的切实验证。如果不支持多核，务必明确写“仅支持单核（❌ 未实现）”**。
- Secondary CPU 启动等主要功能机制：**必须清晰、详尽地描述其详细的底层工作机制**。具体描述 BSP（主核）是如何通过 IPI 或中断控制器发送信号唤醒 AP（从核）的链条，精确到对应文件的代码逻辑。搜索 `smp_boot`, `__cpu_up`。如果找不到启动其他核的代码，那就是单核。
- 核间中断 (IPI)：搜索 `send_ipi`, `ipi_handler`。
- **锁的实现**：SpinLock 是否禁用了中断？Mutex 是否支持优先级继承？
- Per-CPU 变量设计与访问方式。搜索 `axns` 模块，分析 PerCPU 命名空间实现。
- 多核调度策略：负载均衡、CPU 亲和性（affinity）。
- 自旋锁/RCU 在多核下的实现差异。
- **交叉引用前面章节（必须）**：本章与前面章节有大量交叉，必须引用并深化：
    - 进程调度中的全局唯一 ID 池（搜索 `AtomicUsize` 用于 PID/TID 分配）
    - 双级注册机制（线程注册到 Process + 全局管理器）
    - 同步互斥中的 Futex 实现（在多核场景下的行为）
    - 原子操作（`core::sync::atomic`）在多核下的内存序保证

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "SMP boot", "IPI send", "Per-CPU variables", "multicore scheduler" 锁定多核支持代码。
- 使用 `lsp_get_definition` 定位 `PerCpu` 结构和 `smp_boot`/`__cpu_up` 的定义。
- **【必须】使用 `lsp_get_call_graph` 追踪 Secondary CPU 启动链**：
  - `lsp_get_call_graph(repo_path, file_of_start_secondary, "start_secondary", direction="outgoing", max_depth=4)` — 从 secondary 入口到初始化完成
  - 如返回 `[⚠️ DEGRADED MODE]`，标注后继续使用 Grep 结果。
- 使用 `lsp_get_references` 追踪 IPI 分发路径（单层引用）。
- 辅以 grep_in_repo 搜索 smp/、cpu/、percpu 相关模块。
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
        "id": "10_security",
        "title": "安全机制与权限模型",
        "prompt": """目标：分析安全隔离与权限控制机制。

**严格反幻觉要求**：
1. **证据为王**：描述任何特性（如 Seccomp, Audit, ACL）必须附带 `[Source: path/to/file:L1-L10]` 引用。
2. **否定确认**：如果搜索不到相关关键词，你必须明确地写“**未发现实现**”。
3. **禁止臆测**：禁止将 Linux 通用机制套用到当前 OS。

必须回答：
- **多架构覆盖要求**：本章分析必须覆盖项目支持的所有架构（riscv64, aarch64, x86_64, loongarch64 等），不得仅以某一个架构为视角描述。
- **Rust 安全性机制**：如果项目使用 Rust 编写，必须指出 RAII、所有权分析、基于生命周期的锁等机制带来的安全性。
- 用户态/内核态隔离：页表隔离（KPTI）、SMEP/SMAP 是否开启？
- **权限模型深度验证（关键）**：
    - **用户/组（UID/GID）**：不仅要看 `Task` 结构体是否有 `uid` 字段，**必须验证**这些字段是否在 `open/write/exec` 等系统调用中被用于权限检查！（grep `check_perm`, `inode_permission`）。如果仅有字段但无检查逻辑，必须注明“**仅有定义但未强制执行（🔸 桩函数）**”。
    - **Capability/ACL**：搜索 `capability`, `acl`。
- **安全沙箱 (Seccomp/Prctl)**：
    - 搜索 `prctl` 或 `seccomp`。
    - **必须检查实现**：是返回 `ENOSYS`（未实现），还是直接返回 `0`（假装成功），还是真的解析了 BPF 规则？
    - **Stub判断**：如果 `sys_prctl` 只是 returning 0 without doing anything，标记为 **`🔸 桩函数`**。
    - 如未找到，明确写“未实现安全沙箱（❌ 未实现）”。
- **审计与安全启动**：
    - 搜索 `audit`（审计日志）、`secure_boot`、`signature`（签名验证）。
- **内存安全**：
    - 用户指针验证：搜索 `UserInPtr`, `verify_area`, `access_ok`。确认系统调用入口是否严格检查了用户指针？
    - 缓冲区溢出保护：是否有 `stack_guard`, `canary`？

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "capability check", "seccomp filter", "user pointer verification", "stack canary" 锁定安全机制实现。
- 使用 `lsp_get_definition` 定位 `Credential`/`UID`/`GID` 等安全相关结构体的定义。
- **【必须】使用 `lsp_get_call_graph` 追踪权限检查链**：
  - `lsp_get_call_graph(repo_path, file_of_check_perm, "check_perm", direction="incoming", max_depth=3)` — 哪些 syscall 调用了权限检查？
  - 如返回 `[⚠️ DEGRADED MODE]`，标注后继续使用 Grep 结果，并用 `lsp_get_references` 补充单层引用。
- 辅以 grep_in_repo 搜索 security/、auth/、capability 相关模块和 "seccomp|sandbox|prctl"。
- 查找 syscall 入口处的权限检查逻辑，分析用户/组/权限位的实现。

输出格式：
- ## 特权级与隔离机制
- ## 权限检查与访问控制
- ## 用户/组/权限模型
- ## 进程间隔离与资源限制（追踪检查链路）
- ## 安全沙箱与过滤机制（如无则写“未发现”）
- ## 审计与安全启动机制（如无则写“未发现”）
- ## 内存安全与系统调用检查
- ## Rust 语言级安全性机制（如适用）
- ## 关键代码片段

**重要**：如果项目安全机制较简单，请如实描述。完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "11_network",
        "title": "网络子系统与协议栈",
        "prompt": """目标：深入分析网络子系统与 TCP/IP 协议栈实现。

必须回答：
- 网络协议栈架构：自实现还是使用 `smoltcp`/`lwip` 等库？（**检查 Cargo.toml 依赖**）**如果完全没有网络支持，明确写“未实现网络功能（❌ 未实现）”**。
- Socket 接口实现：是否有 `socket`/`bind`/`connect` 等 syscall？还是仅有 Loopback？
- **功能限制声明（必须）**：分析项目是否已在真实物理网卡上测试过网络功能。如果仅在 QEMU 环境测试或仅支持本地回环通信，必须明确写出该限制。搜索 `loopback|LOOPBACK|127.0.0.1` 确认是否仅有回环设备。
- **网卡驱动细节**：
  - 搜索 `drivers/net/`, `virtio-drivers`, `ixgbe` 等。
  - 列出支持的网卡类型（VirtIO, E1000, RTL8139, Intel 82599 等）。
  - **PHY/MAC 层抽象**：是否存在独立的 PHY 驱动层？
  - **错误处理**：描述一个网络操作失败（如 connect timeout）时的错误码传递流程。
- **高级特性验证（必须 grep 代码）**：
  - 零拷贝（Zero Copy）：搜索 `DMA` 或 `shared` buffer。只有在驱动层看到 DMA 描述符操作，或者协议栈层有 `mbuf` 传递引用，才算零拷贝。
  - 多队列（Multi-queue）：是否有 RSS 支持？
  - **协议支持**：DHCP, DNS, ARP, ICMP, TCP, UDP。
  - **如果未找到代码，明确说明“不支持”**。
- 数据包收发流程：追踪从 `virtio-net` 中断到 `tcp_recv` 的路径。

要求：
- **语义发现（🥇 首选）**：使用 `rag_search_code` 搜索 "smoltcp integration", "socket syscall", "VirtIO-Net driver", "network stack architecture" 锁定网络源码。
- 使用 `lsp_get_definition` 定位 `Socket` trait、`TcpSocket`/`UdpSocket` 结构体定义。
- **【必须】使用 `lsp_get_call_graph` 追踪数据发送路径**（`sys_sendto` → 协议栈 → 网卡驱动）：
  - `lsp_get_call_graph(repo_path, file_of_sys_sendto, "sys_sendto", direction="outgoing", max_depth=4)`
  - 如返回 `[⚠️ DEGRADED MODE]`，标注后继续使用 Grep 结果。
- 使用 `lsp_get_references` 查找单层引用（如哪些地方调用了 `socket_write`、`tcp_send`）。
- 使用 `lsp_get_document_outline` 浏览网络模块文件，发现所有 socket 操作和协议处理函数。
- 辅以 grep_in_repo 搜索 net/、socket/、tcp/ 相关模块。
- **严格区分**：使用了网络库（如 smoltcp）vs 自己实现了协议栈。

输出格式：
- ## 网络子系统架构（自研 vs 第三方库）
- ## Socket 接口与系统调用
- ## 协议栈支持详情（TCP/UDP/IP/Ethernet）
- ## 数据包收发流程追踪
- ## 高级特性支持验证（零拷贝等）

**重要**：如果项目不支持网络功能，请明确说明。完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "12_debug_error",
        "title": "调试机制与错误处理",
        "prompt": """目标：分析调试支持、日志系统与错误处理机制。

必须回答：
- 日志系统：print/log 宏如何实现？日志级别设计？
- Panic 处理：panic! 触发后的流程（栈回溯、寄存器 dump、停机）。
- **栈回溯 (Backtrace)**：是否支持 `dwarf` 解析或基于 FramePointer 的回溯？使用 grep 搜索 `backtrace` 或 `unwind`。**注意不要被 panic 时的简单 PC 打印误导，Backtrace 指的是打印完整的函数调用栈。**
- 异常处理：未处理异常的默认行为。
- 调试接口：
    - **交互式 Shell**: 是否提供 Monitor/Shell？支持哪些命令（`ps`, `ls`, `help`）？
    - GDB stub 支持（如有）：**严格检查**。搜索 `handle_gdb_packet`。如果找不到数据包解析循环，就不是 GDB Stub。
    - 调试控制台/Monitor
    - 内核调试选项
    - 是否支持 `perf` 或 `ftrace`？**Tracepoints** 是否插入到了关键路径？
- 错误码设计：Result/Error 类型定义。
- 断言与检查：debug_assert、运行时检查。

要求：
- 使用 `lsp_get_definition` 定位 `panic_handler`、`log` 宏的实现位置。
- **【必须】使用 `lsp_get_call_graph` 追踪 panic 处理链**（`panic!` → `panic_handler` → 栈回溯 → 停机）：
  - `lsp_get_call_graph(repo_path, file_of_panic_handler, "panic_handler", direction="incoming", max_depth=3)` — 谁触发了 panic？
  - 如返回 `[⚠️ DEGRADED MODE]`，标注后继续使用，用 `lsp_get_references` 补充单层引用。
- 使用 `lsp_get_document_outline` 浏览调试模块，发现所有调试相关函数（backtrace、dump、monitor命令）。
- 辅以 grep_in_repo 搜索 `gdbstub|monitor|perf|trace` 确认调试工具支持。

输出格式：
- ## 日志与打印系统
- ## Panic 处理与栈回溯（明确是否支持 Backtrace）
- ## 错误码与 Result 设计
- ## 调试接口与交互式 Shell
- ## GDB Stub 支持情况（验证代码，排除配置文件干扰）
- ## 断言与运行时检查
- ## 关键代码片段

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },


    {
        "id": "13_history",
        "title": "开发历史与里程碑",
        "prompt": """目标：自主阅读 Git 原始提交记录，推演操作系统的开发时间线。你需要总结"初始版本工作量"、"后续版本的功能演进轨迹"，并将历次重要 Commit 涉及的具体变更归类到对应的操作系统模块中。

**强烈注意：本阶段不使用任何第三方脚本生成图表。你需要完全依赖自己的代码语义理解能力。**

**⚠️ Token 节约与防死循环规则（绝对红线）**：
- **严禁**把 `get_git_history_summary` 放在循环里调用。你只需要调用**一次**，它会自动返回贯穿仓库生命周期的浓缩摘要。
- **严禁**无脑遍历所有的历史节点。
- 当 `get_git_history_summary` 的结果显示某次重大 Commit 涉及了海量文件（如 `[arceos/modules/] 3500 files`）且你需要知道具体加了什么功能时，**必须且只能**使用 `analyze_git_history(repo_path, max_commits=1, skip=N, path_filter="arceos/modules")` 对该重点目录进行定点下钻。
- **绝不允许**在未设定 `path_filter` 的情况下对几千个文件的重大提交使用 `analyze_git_history`，这会导致上万行的输出撑爆监控。
- `find_symbol_first_commit` 可以批量传入多个关键词，请严格合并为 1-2 次统一调用。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段一：【总体提交浏览与模块分类】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) **调用且仅调用一次** `get_git_history_summary(repo_path)` 获取全局提交概览。
   该工具会自动返回精炼摘要，包含：日期、SHA、作者、总增删行数、以及**变更量最大的前 3 个确切目录**。
2) **调用且仅调用一次** `analyze_authors_contribution(repo_path)` 获取该项目的开发者图谱。
   分析该操作系统是属于“单人独立开发”还是“多人模块化协作”，各个核心目录的主力作者是谁。
3) 根据以上返回摘要进行**语义归类**：
   - 识别出提交密集期（快速开发阶段）和平稳期。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段二：【初始版本工作量深度核实】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
定义"初始版本"为时间线最早的一批 commit（通常是建立仓库骨架的那几天）。

A. **初始代码规模评估**
   - 从 `get_git_history_summary` 的返回中找到最早的几个 commit，汇总其增加的代码行数。
   - 观察这些最早 commit 涉及的模块，总结第一版已经搭起了哪几个子系统。

B. **核心子系统首次引入时间（重点查验）**：
   调用 `find_symbol_first_commit(repo_path, keywords=[...])` 批量查询以下关键词是何时从无到有被加入的（**尽量合并为 1-2 次调用**）：
   - 启动入口：`["_start", "rust_main", "kernel_main"]`
   - 内存管理：`["FrameAllocator", "PageTable", "MemorySet"]`
   - 进程/任务：`["TaskInner", "spawn_task", "ProcessInner"]`
   - 文件系统：`["VfsNode", "fat32", "ramfs", "sys_open"]`
   - 系统调用：`["syscall_handler", "sys_write", "sys_read", "sys_exec"]`
   - 中断/Trap：`["trap_handler", "TrapFrame", "stvec"]`
   - 进程间通信(IPC)：`["sys_pipe", "Mailbox", "sys_msgget", "sys_shmget"]`
   - 设备驱动：`["virtio_blk", "UART", "plic", "device_init"]`
   - 网络(Network)：`["sys_socket", "smoltcp", "TcpSocket", "udp_send"]`

   根据工具返回的时间：
   - 若【首次引入】日期在仓库头几天 → 标记为 "**初始版本已有**"
   - 若【首次引入】日期在中后期 → 标记为 "**后续版本引入**"
   - 若查询结果显示未找到 → 标记为 "**暂不支持该功能**"

C. **使用 grep_in_repo 探索隐藏功能**（可选）：
   - 如果遇到分析瓶颈，可用 `grep_in_repo` 搜索关键字（如 `SMP`, `signal`, `mmap`）核实功能是否存在。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段三：【后续重要功能的代码演进轨迹】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
根据 `get_git_history_summary` 返回的概览，挑选 **最有代表性的 8-12 次大变动**（通过增删行数和模块判断）。
对每次大变动，基于概览中的信息写出分析：
1. **所属模块**：这是在改网络、改内存，还是在改驱动？
2. **改动性质**：
   - 【新增功能】：引入了全新的机制（如第一次带入多核 SMP）
   - 【重构/优化】：大面积重写了既有模块
   - 【Bug修复】：修复了重大架构缺陷
3. **工作量与事实**：列出增删规模 (+xxx/-yyy) 以及涉及的主要模块。

**【高级钻取工具（按需使用）】**：
- 如果某个大变动在 `get_git_history_summary` 中显示修改了大量的核心子系统（例如 `[arceos/modules/] 3500 files`），你需要弄清楚里面包含了什么文件，**必须**使用带目录过滤的精确下钻：`analyze_git_history(repo_path, max_commits=1, skip=N, path_filter="arceos/modules")`。
- 如果你看到一个极其关键的 Commit（比如标为"Add Network Stack"），但你想知道它到底在底层新增了什么函数接口？调用 `get_commit_diff_summary(repo_path, commit_sha)` 一键透视其底层增删的具体代码逻辑，而不是光靠猜。
- 如果你想知道一个至关重要的大文件（如 `kernel/sched.rs`）从立项起经历了几次重构，调用 `trace_file_evolution(repo_path, "kernel/sched.rs")` 拉出它演进的生命线。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出格式要求（纯文本 Markdown 历史报告）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**必须**严格按照以下结构输出，清晰回答这三个核心问题：

- ## 一、 项目概览与人员协作
  - **总规模与协作模式**：基于代码规模和作者贡献图，总结这是个单人作业还是社区协作项目？各作者主力负责什么模块。
  - **初始完成功能**：第一版建立时就已经搭起了哪几个子系统（核心功能引入时点检测结果）。

- ## 二、 后续版本演进与功能完善
  - 详细罗列后续的历次重大 Commit/迭代中，完成（完善/修改）了哪些 OS 功能模块。
  - 按模块分类（如：内存管理、驱动、文件系统）列出其演进轨迹及其增加/减少的代码量估算。列出最具代表性的演进记录。

- ## 三、 现状评估与后续修改建议（核心总结）
  - **目前还缺什么**：基于前面对整个仓库历史和现状的分析，目前这个 OS 还有哪些明显的缺失功能或尚未完善的半成品模块？
  - **现在还需要怎么改**：给出 3-5 条对该项目当下最迫切的代码修改、架构重构或功能补全的建议方向。

**重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
""",
    },
    {
        "id": "01_overview",
        "title": "项目概览与技术栈",
        "needs_previous_sections": True,
        "prompt": """目标：建立"这是什么 OS、怎么构建、关键入口在哪"的简明技术字典，并生成全项目的完成度评价。

        **严格注意**：区分项目本身名称（如 Undefined OS）与底层框架（如 ArceOS、rCore、xv6等）。如果项目是基于 ArceOS 修改的，必须明确说明"基于 ArceOS 开发"。
        由于你是最后执行的综合阶段，此时**其他章节（02-13章）的生成报告已经全部提供在你的上下文末尾**，你需要直接利用这些信息来宏观总结整个项目。

        请按顺序完成（仓库已克隆到 repo_path，直接使用即可）：
        1) **融会贯通**：直接阅读并深刻理解上下文中附带的前置章节报告，了解系统整体完成情况，无需再调用工具去查阅底层细枝末节的代码（除非是为了寻找内核入口）。
        2) analyze_tech_stack(repo_path)：总结语言/构建/依赖。**必须明确提取编程语言（版本、是否no_std）、基础框架来源（rCore/ArceOS/xv6等）、内核类型（宏内核/微内核/混合等）。**
        3) list_repo_structure(repo_path, max_depth=5)：总结关键目录。
        4) **寻找架构支持**：代码验证并明确列出该项目支持的所有架构（x86_64, aarch64, riscv64, loongarch64 等）。
        5) **寻找入口**：搜索并确定真正的 OS 内核入口函数（可借用 LSP 或 grep 快速定位）。

        输出格式要求（严格按此顺序输出，不得调换）：

        - ## 快速总览
          **必须是报告的第一个内容块**，让评委在30秒内掌握全貌。包含以下两部分，不得省略：

          **第一部分：一句话定位**（≤60字）
          格式："[OS名称] 是一个基于 [框架/从零] 开发的 [架构] [内核类型]，采用 [主要语言]，[最突出的1个技术特点]。"
          若基于已有框架（xv6/rCore/ArceOS/往年参赛作品等），必须在此明确说明，并指出在原框架基础上新增/修改了什么。

          **第二部分：子系统完成度矩阵**（固定表格，不得删减行）
          | 子系统 | 完成度 | 关键实现 |
          |--------|--------|---------|
          | 启动与初始化 | ✅完整 / 🔸部分 / ❌缺失 | 一句话 |
          | 内存管理 | ... | ... |
          | 进程/线程调度 | ... | ... |
          | 中断与系统调用 | ... | ... |
          | 文件系统 | ... | ... |
          | 设备驱动 | ... | ... |
          | 同步与IPC | ... | ... |
          | 多核支持 | ... | ... |
          | 网络协议栈 | ... | ... |
          | 安全机制 | ... | ... |

        - ## 技术栈与构建（含编程语言版本、所有支持的架构完整列表）
        - ## 目录结构导读（列出系统关键目录与源码入口）
        - ## 总结评价（完成度评估）
          深度结合下文附带的各模块报告情况，用200-300字概括：项目定位与目标、技术栈概览、实现完成度评估（系统主要功能模块是否闭环）。**注意：只做客观的定性评价，绝不要打分（如不要出现x/10这样的评分）。**

        **重要**：完成所有工具调用后，你必须输出一个完整的 Markdown 格式分析报告。
        """,
    },
]

# _format_tool_call_summary 和 _format_tool_result_summary 已移至 core.utils 模块


def _strip_llm_preamble(text: str) -> str:
    """剥掉 LLM 输出中第一个 Markdown 标题（# 开头）之前的过渡性思考文字。

    LLM 有时会在正式报告内容之前输出一段口语化的过渡文字，例如：
      "现在我已经收集了足够的信息来撰写...让我整理分析结果..."
    这类文字不属于报告内容，需要在写入文件前过滤掉。

    策略：找到第一个以 '#' 开头的行，从该行开始作为有效内容。
    如果全文均无 '#' 标题行，则保留原文（避免误删真实内容）。
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith('#'):
            stripped = "\n".join(lines[i:]).strip()
            if i > 0:
                dropped = "\n".join(lines[:i]).strip()
                # 只在确实有内容被剥掉时打印提示
                if dropped:
                    preview = dropped[:120].replace('\n', ' ')
                    print(f"  ✂️  已剥除 LLM 前缀（{len(dropped)} 字符）: {preview}...")
            return stripped
    # 没有找到 '#' 标题，保留原文
    return text


def print_step(step_num: int, node_name: str, state: dict, stage_step_num: int = 0, max_steps: int = 1500, stage_limit: int = 500) -> int:
    """打印每一步的执行信息（简洁的 agent 风格）
    
    Args:
        step_num: 全局步骤号
        node_name: 节点名称
        state: 状态字典
        stage_step_num: 阶段内步骤号
        max_steps: 全局最大步数估计（仅显示用）
        stage_limit: 阶段递归步数限制
        
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
                print(f"\n【Total Step {step_num}/{max_steps}】(Stage step: {stage_step_num}/{stage_limit})", end=" ")

            if tool_calls:
                print("🔧 Tool Calls:")
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tool_name = tc.get("name", "unknown")
                        tool_args = tc.get("args", {})
                    else:
                        tool_name = getattr(tc, "name", "unknown")
                        tool_args = getattr(tc, "args", {})
                    
                    summary = format_tool_call_summary(tool_name, tool_args)
                    print(f"   {tool_name}({summary})")
            
            # 如果有思考内容且没有工具调用，显示思考（这通常是最终输出）
            elif content.strip():
                # 显示简短预览
                preview = content.strip()[:200]
                if len(content) > 200:
                    preview += "..."
                print(f"Agent: {preview}")
            
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
            summary = format_tool_result_summary(tool_name, content)
            print(f"   ✅ {tool_name}: {summary}")
            
    return token_count


def _save_json(path: str, payload: dict):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️  无法写入 JSON 文件 {path}: {e}")


def _summarize_section_text(text: str, max_chars: int = 500) -> str:
    text = _strip_llm_preamble((text or "").strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _extract_path_mentions(text: str) -> list[str]:
    pattern = re.compile(r"`([^`\n]*/[^`\n]+\.(?:rs|c|h|cpp|go|zig|S|s|toml|ld|md|py)(?::\d+(?:-\d+)?)?)`")
    return [m.group(1) for m in pattern.finditer(text or "")]


def _print_review_result(result, title: str):
    print(f"\n🧪 Reviewer: {title}")
    print(f"   - passed: {result.passed}")
    print(f"   - score: {result.score}")
    if result.failed_rules:
        print(f"   - failed_rules: {', '.join(result.failed_rules)}")
    if result.missed_modules:
        print(f"   - missed_modules: {', '.join(result.missed_modules[:4])}")
    if result.repair_actions:
        print(f"   - repair_actions: {len(result.repair_actions)}")


def main():
    repo_url = os.environ.get("REPO_URL", "").strip()
    
    if not repo_url:
        print("❌ 错误：未设置 REPO_URL 环境变量")
        print("   请在 .env 文件中设置 REPO_URL，或通过命令行设置：")
        print("   export REPO_URL=\"https://github.com/example/os-project.git\"")
        sys.exit(1)

    repo_name = repo_name_from_url(repo_url)
    
    # 按 OS 名称创建独立的输出目录
    repo_output_dir = os.path.join(OUTPUT_DIR, repo_name)
    sections_dir = os.path.join(repo_output_dir, "sections")
    
    os.makedirs(repo_output_dir, exist_ok=True)
    os.makedirs(sections_dir, exist_ok=True)

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
    
    GLOBAL_ESTIMATED_STEPS = 1500  # 全局估计总步数（用于显示进度条分母）

    # 初始化错误追踪器
    error_tracker = ErrorTracker(output_dir=repo_output_dir)


    # 在此处增加直接克隆逻辑
    repo_local_path = os.path.normpath(os.path.join("./repos", repo_name))
    print("=" * 80)
    print(f"📦 阶段 0：仓库准备 (直接执行，无需 LLM)")
    print("=" * 80)
    if os.path.exists(repo_local_path) and os.path.isdir(repo_local_path) and os.listdir(repo_local_path):
        print(f"⏭️  仓库已存在，跳过克隆。 路径: {repo_local_path}")
    else:
        print(f"🚀 正在克隆仓库: {repo_url} ...")
        from tools.git_ops import clone_repository
        result = clone_repository.invoke({"repo_url": repo_url})
        print(result)
    
    # --- 增加：RAG 预索引 (加速后续分析阶段) ---
    print(f"\n🚀 阶段 0.5：RAG 预索引 (代码向量化)...")
    try:
        from core.code_rag import CodeRAGEngine
        # 注意：这里传入的 repo_local_path 是 ./repos/xv6-k210
        rag_engine = CodeRAGEngine(project_name=repo_name)
        # build_index 会自动检测并跳过已存在的索引
        rag_engine.build_index(repo_local_path, force=False)
        print(f"✅ RAG 预索引完成，后续语义搜索将秒开。")
    except Exception as e:
        print(f"⚠️ RAG 预索引跳过 (将在首次调用时重试): {e}")
    # ------------------------------------------

    reviewer_llm = build_reviewer_llm()
    repo_profile = build_repo_profile(repo_url=repo_url, repo_path=repo_local_path)
    _save_json(os.path.join(repo_output_dir, "repo_profile.json"), repo_profile)
    global_memory = {
        "section_summaries": {},
        "mentioned_paths": [],
        "external_background": {},
    }

    for idx, stage in enumerate(STAGES, 1):
        stage_id = stage["id"]
        title = stage["title"]
        prompt = stage["prompt"]
        stage_state = StageState(
            stage_id=stage_id,
            stage_title=title,
            stage_type="describe",
            stage_prompt=prompt,
        )


        # 检查是否跳过此阶段
        skip_in_report = stage.get("skip_in_report", False)
        
        # 只有非skip阶段才计入章节号
        if not skip_in_report:
            # 优先从 stage_id 提取章节号 (例如 "02_boot_arch" -> "02")
            chapter_prefix = stage_id.split('_')[0]
            if not chapter_prefix.isdigit():
                chapter_counter += 1
                chapter_prefix = f"{chapter_counter:02d}"
            else:
                chapter_counter = int(chapter_prefix)
                
            section_name = f"{chapter_prefix}_{_slug(title)}.md"
        else:
            # skip阶段使用idx作为前缀（避免冲突，但不会保存）
            section_name = f"00_{_slug(title)}.md"
        
        section_path = os.path.join(sections_dir, section_name)

        # 简单的断点续传：如果文件已存在且内容看起来正常（>200字节），则跳过
        if os.path.exists(section_path):
            if os.path.getsize(section_path) > 200:
                print("=" * 80)
                print(f"⏭️  阶段 {idx}/{len(STAGES)}：{title} (已存在，跳过)")
                print(f"   文件: {section_path}")
                print("=" * 80)
                if not skip_in_report:
                    all_section_paths.append(section_path)
                    try:
                        with open(section_path, "r", encoding="utf-8", errors="ignore") as existing_f:
                            existing_text = existing_f.read().strip()
                        global_memory["section_summaries"][stage_id] = _summarize_section_text(existing_text)
                        global_memory["mentioned_paths"].extend(_extract_path_mentions(existing_text))
                        global_memory["mentioned_paths"] = list(dict.fromkeys(global_memory["mentioned_paths"]))[-100:]
                    except Exception:
                        pass
                continue
            else:
                print(f"♻️  检测到残留的失败文件 (Size: {os.path.getsize(section_path)} bytes)，将删除并重试: {section_name}")
                try:
                    os.remove(section_path)
                except OSError:
                    pass


        # 每个阶段构建 base_ctx
        base_ctx = _build_base_context(repo_url=repo_url, output_dir=repo_output_dir)
        print("\n" + "━" * 26 + " ① Plan · 探索并锁定本阶段计划 " + "━" * 26)
        stage_state.plan = plan_stage(stage_state, repo_profile=repo_profile, global_memory=global_memory)
        try:
            planner_agent = build_planner_agent(stage_id=stage_id)
            plan_stream_step = 0

            def _on_plan_stream(node_name: str, st: dict) -> None:
                nonlocal overall_step_count, plan_stream_step
                overall_step_count += 1
                plan_stream_step += 1
                print_step(
                    overall_step_count,
                    node_name,
                    st,
                    plan_stream_step,
                    GLOBAL_ESTIMATED_STEPS,
                    PLANNER_RECURSION_LIMIT,
                )

            patch, plan_notes = run_llm_planning_agent(
                planner_agent,
                stage_state,
                repo_profile,
                repo_local_path,
                global_memory=global_memory,
                on_stream_step=_on_plan_stream,
            )
            stage_state.metadata["llm_plan_patch_applied"] = bool(patch)
            if patch:
                stage_state.plan = apply_llm_plan_overlay(stage_state.plan, patch)
            if plan_notes:
                stage_state.metadata["llm_plan_notes"] = plan_notes
            if patch or plan_notes:
                print(f"   🧩 LLM 规划已合并（patch_keys={list(patch.keys()) if patch else []}）")
        except Exception as e:
            stage_state.metadata["llm_plan_patch_applied"] = False
            logging.warning("LLM 规划失败，沿用启发式计划: %s", e)
        stage_state.plan = ensure_execution_steps(stage_state.plan)
        stage_state.dynamic_context = build_dynamic_context(stage_state, repo_profile=repo_profile, global_memory=global_memory)
        plan_context = render_plan_context(stage_state)
        
        # 如果是最后整合阶段，需要读取前面所有 section 的内容
        previous_sections_content = ""
        if stage.get("needs_previous_sections", False) and all_section_paths:
            print(f"\n📚 读取前面 {len(all_section_paths)} 个阶段的分析内容...")
            sections_texts = []
            
            # 限制每个 section 的最大字符数，避免 "lost in the middle" 问题
            MAX_CHARS_PER_SECTION = 17000  # 每个 section 最多 17000 字符
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
        
        # 从已解析的 chapter_counter 直接获取章节号
        chapter_num = chapter_counter if not skip_in_report else None
        
        # 构建任务 prompt
        if chapter_num:
            # 这是一个正式章节，告诉 Agent 输出的是第几章
            chapter_hint = f"""
**本阶段是最终报告的第 {chapter_num} 章：{title}**

请按照以下格式输出本章内容（这将直接作为最终报告的一部分）：

## 第 {chapter_num} 章：{title}

（你的分析内容）

"""
            task = (
                base_ctx
                + "\n"
                + chapter_hint
                + "\n"
                + plan_context
                + "\n"
                + CURSOR_EXECUTION_CONTRACT
                + "\n\n"
                + prompt
                + previous_sections_content
            )
        else:
            task = (
                base_ctx
                + "\n"
                + f"## 阶段 {idx}/{len(STAGES)}：{title}\n\n"
                + plan_context
                + "\n"
                + CURSOR_EXECUTION_CONTRACT
                + "\n\n"
                + prompt
                + previous_sections_content
            )
        
        inputs = {"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=task)]}

        print("\n" + "=" * 80)
        print(f"🧩 阶段 {idx}/{len(STAGES)}：{title}")
        print("=" * 80)
        print("   ✅ ① Plan 已锁定 → 执行步骤条数:", len(stage_state.plan.execution_steps) if stage_state.plan else 0)
        print("━" * 26 + " ② Execute · 按锁定计划执行 " + "━" * 26)
        print(f"   模型: {os.getenv('MODEL_NAME')} — 以下 Tool 日志均为 Execute")
        sys.stdout.flush()  # 强制刷新输出缓冲区

        agent = build_executor_agent(stage_id=stage_id)
        
        final_state = None
        stage_step_count = 0  # 阶段内步骤计数
        recursion_limit = 500
        
        stage_tokens = 0  # 阶段内 token 计数
        retry_count = 0
        last_exception = None
        
        # 智能重试循环
        while retry_count <= RetryConfig.MAX_RETRIES:
            try:
                if retry_count > 0:
                    # 分类错误并决定是否重试
                    error_type = classify_error(last_exception)
                    
                    if not RetryConfig.RETRYABLE_ERRORS.get(error_type, False):
                        logging.warning(
                            f"[{title}] 错误类型 {error_type.value} 不适合重试，跳过"
                        )
                        break
                    
                    # 计算退避时间
                    backoff = calculate_backoff(retry_count - 1)
                    print(f"   🔄 正在重试 ({retry_count}/{RetryConfig.MAX_RETRIES})...")
                    print(f"   ⏱️  等待 {backoff} 秒后重试（{error_type.value}）...")
                    time.sleep(backoff)
                    
                    logging.info(
                        f"[{title}] 第 {retry_count} 次重试 "
                        f"(错误类型: {error_type.value}, 退避: {backoff}s)"
                    )
                
                # 执行 agent
                for event in agent.stream(inputs, config={"recursion_limit": recursion_limit}):
                    overall_step_count += 1
                    stage_step_count += 1
                    for node_name, state in event.items():
                        step_tokens = print_step(overall_step_count, node_name, state, stage_step_count, GLOBAL_ESTIMATED_STEPS, recursion_limit)
                        stage_tokens += step_tokens
                        final_state = state
                
                # 成功执行完成，跳出重试循环
                logging.info(f"[{title}] Agent 执行成功（步骤数: {stage_step_count}）")
                break
                
            except KeyboardInterrupt:
                print("\\n\\n⚠️  用户中断执行")
                error_tracker.save_error_report(filename="describe_error_report.json")
                sys.exit(1)
            except Exception as e:
                last_exception = e
                error_type = classify_error(e)
                
                # 记录错误到追踪器
                error_tracker.record_error(
                    section_name=title,
                    error_type=error_type,
                    exception=e,
                    retry_count=retry_count,
                    context={
                        "stage_id": stage_id,
                        "step_count": stage_step_count,
                        "model": os.getenv('MODEL_NAME'),
                        "recursion_limit": recursion_limit,
                    }
                )
                
                print(f"\n   ❌ {error_type.value}: {type(e).__name__}: {e}")
                retry_count += 1
                
                if retry_count > RetryConfig.MAX_RETRIES:
                    error_msg = f"超过最大重试次数 {RetryConfig.MAX_RETRIES}"
                    logging.critical(
                        f"[{title}] {error_msg} - 最后错误: {type(e).__name__}: {e}"
                    )
                    import traceback
                    traceback.print_exc()
                    # 不退出，继续下一阶段

        stage_text = ""
        is_complete = False
        all_ai_content = []  # 收集所有 AI 回复内容
        execution_messages = []
        
        if final_state and final_state.get("messages"):
            messages = final_state["messages"]
            execution_messages = messages
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
                        # 必须清理掉末尾带有未解析 tool_calls 的 AIMessage，否则大模型会抛出验证错误
                        # 并导致部分模型（如 Qwen）重置上下文。
                        safe_messages = messages.copy()
                        while safe_messages and isinstance(safe_messages[-1], AIMessage) and getattr(safe_messages[-1], "tool_calls", None):
                            safe_messages.pop()
                            
                        # 继续对话，追加 followup 消息
                        followup_inputs = {"messages": safe_messages + [followup_msg]}
                        for event in agent.stream(followup_inputs, config={"recursion_limit": 10}):
                            overall_step_count += 1
                            stage_step_count += 1
                            for node_name, state in event.items():
                                step_tokens = print_step(overall_step_count, node_name, state, stage_step_count, GLOBAL_ESTIMATED_STEPS, recursion_limit)
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
                                                execution_messages = state["messages"]
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

        stage_text = _strip_llm_preamble(stage_text.strip())
        artifacts = extract_stage_artifacts(stage_text, execution_messages)
        stage_state.draft_markdown = artifacts["draft_markdown"] or stage_text
        stage_state.draft_document = artifacts["draft_document"]
        stage_state.evidence_index = artifacts["evidence_index"]
        stage_state.status = "executed"

        sidecar_dir = os.path.join(repo_output_dir, "_per_stage")
        _save_json(os.path.join(sidecar_dir, f"{stage_id}_plan.json"), stage_state.plan.to_dict() if stage_state.plan else {})
        _save_json(
            os.path.join(sidecar_dir, f"{stage_id}_evidence_index.json"),
            {"items": [item.to_dict() for item in stage_state.evidence_index]},
        )

        if not skip_in_report:
            print("\n" + "━" * 28 + " ③ Verify · 审查 " + "━" * 28)
            verify_stream_step = 0

            def _on_verify_stream(node_name: str, st: dict) -> None:
                nonlocal overall_step_count, verify_stream_step
                overall_step_count += 1
                verify_stream_step += 1
                print_step(
                    overall_step_count,
                    node_name,
                    st,
                    verify_stream_step,
                    GLOBAL_ESTIMATED_STEPS,
                    VERIFY_RECURSION_LIMIT,
                )

            review_result = review_stage(
                stage_state,
                reviewer_llm,
                llm_primary=True,
                on_llm_stream_step=_on_verify_stream,
            )
            _print_review_result(review_result, title)
            _save_json(os.path.join(sidecar_dir, f"{stage_id}_review.json"), review_result.to_dict())

            if not review_result.passed:
                print("\n" + "━" * 22 + " ④ Patch 计划 · 收缩为小范围步骤 " + "━" * 22)
                patch_stream_step = 0

                def _on_patch_stream(node_name: str, st: dict) -> None:
                    nonlocal overall_step_count, patch_stream_step
                    overall_step_count += 1
                    patch_stream_step += 1
                    print_step(
                        overall_step_count,
                        node_name,
                        st,
                        patch_stream_step,
                        GLOBAL_ESTIMATED_STEPS,
                        PATCH_PLAN_RECURSION_LIMIT,
                    )

                patch_actions, patch_summary = run_llm_patch_plan(
                    stage_state,
                    review_result,
                    reviewer_llm,
                    max_actions=6,
                    on_stream_step=_on_patch_stream,
                    stage_id=stage_id,
                )
                stage_state.metadata["patch_plan_summary"] = patch_summary
                if patch_actions:
                    stage_state.metadata["patch_plan_actions"] = patch_actions
                    _save_json(
                        os.path.join(sidecar_dir, f"{stage_id}_patch_plan.json"),
                        {"summary": patch_summary, "actions": patch_actions},
                    )
                    if patch_summary:
                        print(f"   📌 {patch_summary}")
                    print(
                        f"   → 已生成 {len(patch_actions)} 条定向修补（详见 _per_stage/{stage_id}_patch_plan.json）"
                    )
                else:
                    print("   ⚠️ 未生成小型 patch 计划，将使用审阅返回的全部 repair_actions（最多 8 条）")
                print("━" * 26 + " ⑤ Apply patches " + "━" * 26)
                stage_state.metadata["repair_context"] = (
                    patch_actions if patch_actions else review_result.repair_actions
                )
                repair_stream_step = 0

                def _on_repair_stream(node_name: str, st: dict) -> None:
                    nonlocal overall_step_count, repair_stream_step
                    overall_step_count += 1
                    repair_stream_step += 1
                    print_step(
                        overall_step_count,
                        node_name,
                        st,
                        repair_stream_step,
                        GLOBAL_ESTIMATED_STEPS,
                        DEFAULT_REPAIR_RECURSION_LIMIT,
                    )

                touched_paragraph_ids = repair_stage(
                    stage_state,
                    agent=agent,
                    llm=reviewer_llm,
                    base_messages=execution_messages,
                    repair_actions_override=patch_actions if patch_actions else None,
                    on_stream_step=_on_repair_stream,
                    repair_verbose=True,
                )
                if touched_paragraph_ids:
                    re_result = re_review_stage(stage_state, touched_paragraph_ids)
                    _print_review_result(re_result, f"{title} (re-review)")
                    _save_json(os.path.join(sidecar_dir, f"{stage_id}_review_after_repair.json"), re_result.to_dict())

        # 保存阶段结果（除非标记为 skip_in_report）
        # skip_in_report 在前面文件命名时已经获取
        if skip_in_report:
            print(f"\n⏭️  阶段 {idx} 标记为 skip_in_report，不写入报告")
        else:
            try:
                os.makedirs(os.path.dirname(section_path), exist_ok=True)
                with open(section_path, "w", encoding="utf-8") as f:
                    clean_text = _strip_llm_preamble(stage_state.draft_markdown.strip())
                    f.write(clean_text + "\n")
                all_section_paths.append(section_path)
                global_memory["section_summaries"][stage_id] = _summarize_section_text(clean_text)
                global_memory["mentioned_paths"].extend(_extract_path_mentions(clean_text))
                global_memory["mentioned_paths"] = list(dict.fromkeys(global_memory["mentioned_paths"]))[-100:]
                if stage_id == "01_overview":
                    background_items = [
                        item.excerpt[:300]
                        for item in stage_state.evidence_index
                        if item.source_type == "web_background" and item.excerpt
                    ]
                    if background_items:
                        global_memory["external_background"]["competition_background"] = background_items[:4]
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

    # 生成 Call Graph 概览块
    callgraph_md = ""
    try:
        from tools.callgraph_overview import generate_callgraph_section
        callgraph_md = generate_callgraph_section(
            repo_path=repo_local_path,
            output_dir=repo_output_dir,
            top_k=30,
            use_embedding=True,
            lsp_refine=True,
        )
        print(f"\n✅ Call Graph 概览生成完成")
    except Exception as e:
        print(f"\n⚠️  Call Graph 生成失败: {e}")
        import traceback; traceback.print_exc()

    # 合并总报告 - 生成专业的、类似人类撰写的技术文档
    final_report_path = os.path.join(repo_output_dir, f"OS技术分析报告_{repo_name}.md")
    try:
        # 01_overview 排最前，其余按文件名排序
        overview_sections = [p for p in all_section_paths if os.path.basename(p).startswith("01_")]
        other_sections = sorted([p for p in all_section_paths if not os.path.basename(p).startswith("01_")])
        content_sections = overview_sections + other_sections

        with open(final_report_path, "w", encoding="utf-8") as out:
            # 标题和元数据
            out.write(f"# {repo_name} 操作系统技术分析报告\n\n")

            # 加载作者信息
            author_info = get_author_info(repo_url)
            if author_info:
                if author_info.get("year"):
                    out.write(f"> **年份**: {author_info['year']}\n\n")
                if author_info.get("competition"):
                    out.write(f"> **赛事**: {author_info['competition']}\n\n")
                if author_info.get("sub_competition"):
                    out.write(f"> **子赛事**: {author_info['sub_competition']}\n\n")
                if author_info.get("school"):
                    out.write(f"> **学校**: {author_info['school']}\n\n")
                if author_info.get("team"):
                    out.write(f"> **队伍名称**: {author_info['team']}\n\n")

            out.write(f"> **仓库地址**: {repo_url}\n\n")
            out.write(f"> **分析日期**: {datetime.now().strftime('%Y年%m月%d日')}\n\n")
            out.write(f"> **分析工具**: OS-Agent-D\n\n")
            out.write("---\n\n")

            # 目录
            out.write("## 目录\n\n")
            for i, p in enumerate(content_sections, 1):
                try:
                    filename = os.path.basename(p)
                    title = os.path.splitext(filename)[0]
                    if '_' in title:
                        title = title.split('_', 1)[1]
                    title = title.replace('_', ' ')
                    out.write(f"{i}. {title}\n")
                except Exception:
                    filename = os.path.splitext(os.path.basename(p))[0]
                    out.write(f"{i}. {filename}\n")

            out.write("\n---\n\n")

            # Call Graph 概览（放在目录之后、章节正文之前）
            if callgraph_md:
                out.write(callgraph_md)
                out.write("\n---\n\n")

            # 正文：依次输出各章节内容
            for i, p in enumerate(content_sections, 1):
                try:
                    filename = os.path.basename(p)
                    chapter_title = os.path.splitext(filename)[0]
                    if '_' in chapter_title:
                        chapter_title = chapter_title.split('_', 1)[1]
                    chapter_title = chapter_title.replace('_', ' ')

                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read().strip()

                        out.write(f"\n# {chapter_title}\n\n")

                        if content.startswith("# "):
                            content = "##" + content[1:]

                        out.write(content + "\n\n")
                        out.write("---\n\n")
                except Exception as e:
                    print(f"  ⚠️  无法读取章节 {p}: {e}")

            # 页脚
            out.write(f"\n---\n\n")
            out.write(f"*本报告由 OS-Agent-D 自动生成*  \n")
            out.write(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*  \n")
            out.write(f"*分析耗时: {(datetime.now() - start_time).total_seconds()/60:.1f} 分钟*\n")

        print(f"\n📄 已生成最终报告: {final_report_path}")
        print(f"   报告包含 {len(content_sections)} 个主要章节")
    except Exception as e:
        print(f"\n⚠️  无法生成总报告: {e}")
        import traceback
        traceback.print_exc()

    # 保存错误报告（如果有错误）
    error_tracker.save_error_report(filename="describe_error_report.json")
    if error_tracker.errors:
        print(f"\n⚠️  运行过程中发生 {len(error_tracker.errors)} 个错误")
        print(error_tracker.generate_error_summary())

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print("=" * 80)
    print("✅ 多阶段任务完成！")
    print(f"   总步数: {overall_step_count}")
    print(f"   总Token使用: {total_tokens_used:,}")
    print(f"   耗时: {elapsed:.2f} 秒 ({elapsed/60:.2f} 分钟)")
    if error_tracker.errors:
        print(f"   错误数: {len(error_tracker.errors)} (详见 describe_error_report.json)")
    print(f"⏰ 结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
