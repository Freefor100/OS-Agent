#!/usr/bin/env python3
"""
OS-Agent C 精比模块：基于 LLM Agent 的源码级深度比对

功能：
  读取粗筛结果（coarse_screening.json），对 Top-5 候选项目逐个执行源码级精比：
  - 逐维度技术差异分析
  - Call Graph 差异对比
  - 创新点与代码重合度分析

用法：
  # 基本用法（读取粗筛结果自动对比）
  python os_agent_c_fine.py --target nonix

  # 手动指定候选进行对比
  python os_agent_c_fine.py --target nonix --candidates starry-mix,rcore-v3

  # 仅对比排名第一的候选
  python os_agent_c_fine.py --target nonix --max-candidates 1

环境变量（通过 .env 配置）：
  MODEL_NAME   - LLM 模型名称
"""
import os
import sys
import time
import json
import logging
import argparse
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from core.agent_builder import get_model_name
from core.utils import repo_name_from_url

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("os_agent_c_fine")

DEFAULT_OUTPUT_DIR = "./output"

# ═══════════════════════════════════════════════════════════════════
# 精比 STAGES
# ═══════════════════════════════════════════════════════════════════
COMPARE_STAGES = [
    {
        "id": "c01_overview_diff",
        "title": "技术栈与架构差异",
        "prompt": """对比目标项目 {target} 与候选项目 {candidate} 的技术栈与架构：

1. **编程语言差异**：语言版本、no_std 环境、edition 配置
2. **框架差异**：是否基于同一框架（rCore/ArceOS/xv6/自研）？框架版本是否一致？
3. **目标架构差异**：支持的 ISA 完整列表对比
4. **内核类型差异**：宏内核 vs 微内核 vs unikernel
5. **关键依赖差异**：对比 Cargo.toml / Makefile 中的第三方库
6. **构建系统差异**：构建命令、feature flags 配置的区别

请使用 `load_project_report` 加载两个项目的 01_ section 报告，
使用 `compare_feature_summary` 对比 D1_tech_stack 维度摘要。

**同源性判断**：如果两个项目基于相同框架（如都是 ArceOS），重点分析框架之上的定制化程度。

输出格式：## 技术栈差异 → ## 框架差异 → ## 关键依赖对比 → ## 同源性评估""",
    },
    {
        "id": "c02_memory_diff",
        "title": "内存管理实现差异",
        "prompt": """对比 {target} 与 {candidate} 的内存管理实现：

1. **物理内存分配器差异**：Buddy/Bitmap/SLAB，是内部实现还是外部 crate？
2. **页表实现差异**：SV39/SV48，PageTable 结构体字段是否一致
3. **堆分配器差异**：GlobalAlloc 实现方式
4. **高级特性逐项对比**（对每项标注 已实现/桩函数/未实现）：
   - CoW 写时复制、Lazy Allocation 懒分配、Swap 页面置换
   - HugePage 大页、mmap 文件映射、SharedMem 共享内存、rmap 反向映射
5. **使用 `compare_call_graphs(repos/{target}, repos/{candidate}, "handle_page_fault")` 对比缺页处理调用链**
6. **关键结构体对比**：MemorySet / VmArea / FrameAllocator 字段差异

加载两个项目的 03_ section 报告，使用 `compare_feature_summary` 对比 D3_memory 维度。

**桩代码检测**：如果某项目的 sys_mmap 仅返回 Ok(0)，标注为'桩实现'。

输出格式：## 分配器差异 → ## 页表差异 → ## Call Graph 差异 → ## 高级特性对比表""",
    },
    {
        "id": "c03_process_diff",
        "title": "进程调度机制差异",
        "prompt": """对比 {target} 与 {candidate} 的进程与调度：

1. **任务模型差异**：Task vs Process+Thread / TCB vs PCB 区分
   - 关键结构体字段对比（TaskInner / ProcessInner）
2. **调度算法差异**：FIFO/RR/CFS/Stride，pick_next_task 实现逻辑
   - 是否有多调度器支持（feature flag 切换）
3. **上下文切换差异**：switch.S 保存的寄存器集合，是否包含浮点寄存器
4. **使用 `compare_call_graphs` 对比 schedule / sys_fork 函数调用链**
5. **进程管理扩展**：进程组 PGID / 会话 SID / rlimit 支持差异
6. **信号机制差异**：Signal 实现程度、sigaction/kill/tgkill/trampoline 覆盖度
7. **Futex 差异**：futex_wait/futex_wake 是否完整实现

加载两个项目的 04_ section 报告，使用 `compare_feature_summary` 对比 D4_process_sched 维度。

**注意**：如果 {target} 的 fork 真正复制了地址空间而 {candidate} 仅创建任务控制块，标注为重要差异。

输出格式：## 任务模型差异 → ## 调度算法差异 → ## Call Graph 差异 → ## 信号/Futex 差异""",
    },
    {
        "id": "c04_syscall_diff",
        "title": "系统调用与 Trap 差异",
        "prompt": """对比 {target} 与 {candidate} 的中断与系统调用：

1. **Trap 入口实现差异**：汇编 trap.S vs Rust #[naked] vs 内联汇编
2. **TrapFrame 差异**：结构体包含的寄存器数量和总字节数
3. **系统调用分发方式差异**：match 语句 vs 函数指针表 vs C switch
4. **已实现 syscall 数量与覆盖度差异**：
   - 分类统计：文件IO / 进程管理 / 内存管理 / 网络 / 信号
   - 区分'完整实现'与'桩实现'数量
5. **使用 `compare_call_graphs` 对比 trap_handler 调用链**
6. **接口/实现分离设计**：sys_xxx vs sys_xxx_impl 模式对比
7. **缺页异常处理差异**：是否与 CoW / Lazy Allocation 关联
8. **用户指针安全**：UserInPtr / UserOutPtr 类型安全包装对比

加载两个项目的 05_ section 报告，使用 `compare_feature_summary` 对比 D5_trap_syscall 维度。

输出格式：## Trap 差异 → ## syscall 分发差异 → ## Call Graph 差异 → ## 覆盖度对比""",
    },
    {
        "id": "c05_filesystem_diff",
        "title": "文件系统实现差异",
        "prompt": """对比 {target} 与 {candidate} 的文件系统：

1. **VFS 设计差异**：Trait 接口 vs 函数指针 vs 无 VFS 层
   - 核心抽象名称对比：VfsNode / File / Inode / Dentry / SuperBlock
2. **具体 FS 支持差异**（逐项）：
   - FAT32：自研 vs fatfs crate vs 未支持
   - ext4：自研 vs ext4_rs crate vs 未支持
   - RamFS / TmpFS / DevFS / ProcFS / SysFS 各自覆盖情况
3. **文件描述符管理差异**：FdTable 结构、Per-Process vs Global
4. **Pipe 管道实现差异**：环形缓冲区 vs 简单字节流
5. **mmap 实现深度差异**：MAP_FIXED/MAP_ANON/MAP_SHARED 支持程度
6. **poll/select/epoll 支持状态差异**
7. **使用 `compare_call_graphs` 对比 sys_open 或 vfs_open 调用链**

加载两个项目的 06_ section 报告，使用 `compare_feature_summary` 对比 D6_filesystem 维度。

**创新点发现**：如果 {target} 实现了 {candidate} 没有的伪文件系统（如 ProcFS），标注为创新点。

输出格式：## VFS 设计差异 → ## 具体 FS 支持表 → ## Call Graph 差异 → ## 高级特性差异""",
    },
    {
        "id": "c06_driver_ipc_diff",
        "title": "设备驱动与IPC差异",
        "prompt": """对比 {target} 与 {candidate} 的设备驱动与同步IPC：

【设备驱动部分】：
1. **驱动框架差异**：Driver Trait 设计、注册/初始化机制
2. **设备发现差异**：Device Tree 解析 vs PCI 枚举 vs 硬编码
3. **支持设备列表差异**：UART / VirtIO-Blk / VirtIO-Net / PLIC/CLINT
4. **目标平台/开发板差异**
5. **组件化配置差异**：Cargo features / Kconfig
6. **【必须】使用 `compare_call_graphs` 对比 `init_drivers` 或 `probe` 调用链**

【IPC 部分】：
1. **锁机制差异**：SpinLock / Mutex / RwLock / Semaphore 实现方式
2. **IPC 机制逐项对比**（标注 已实现/桩函数/未实现）：
   - Pipe、消息队列 MessageQueue、共享内存 SharedMem、信号量 Semaphore
3. **Futex 差异**：是否完整实现 futex_wait/futex_wake
4. **等待队列差异**：WaitQueue 实现方式
5. **【必须】使用 `compare_call_graphs` 对比 `sys_futex` 或 `futex_wait` 调用链**

加载两个项目的 07_ 和 08_ section 报告，使用 `compare_feature_summary` 分别对比 D7_device_driver 和 D8_sync_ipc 维度。

**桩代码检测**：如果 sys_msgget/sys_semget 函数体为空或仅返回 Ok(0)，标注为'桩函数'。

**Call Graph 退避策略**：如果 compare_call_graphs 返回'未找到函数'或'Call Graph 获取失败'，改用 `grep_in_repo` 搜索对应函数名进行文本级对比，并在报告中标注'降级分析'。

输出格式：## 驱动框架差异 → ## 设备支持Call Graph差异 → ## IPC 机制差异表 → ## Call Graph差异 → ## 桩代码/真实实现区分""",
    },
    {
        "id": "c07_smp_sec_net_diff",
        "title": "多核/安全/网络差异",
        "prompt": """对比 {target} 与 {candidate} 的多核支持、安全机制、网络子系统：

【多核部分】：
1. **多核架构差异**：SMP vs AMP vs 仅单核
2. **Secondary CPU 启动差异**
3. **核间中断 IPI 差异**
4. **Per-CPU 变量设计差异**
5. **【必须】使用 `compare_call_graphs` 对比 `start_secondary` 或 `smp_boot` 调用链**
   - 如果两个项目都不支持多核，此步跳过并在报告中注明

【安全部分】：
1. **权限模型差异**：UID/GID 是否在 syscall 中强制执行检查
   - 如果仅有 uid 字段但无 check_perm 调用，标注'仅有定义未强制执行'
2. **安全沙箱差异**：Seccomp/prctl 实现程度
3. **用户指针验证差异**：UserInPtr / verify_area

【网络部分】：
1. **协议栈差异**：smoltcp vs lwip vs 自研 vs 未实现
2. **Socket 接口差异**：syscall 覆盖度
3. **网卡驱动差异**：VirtIO-Net / E1000 / Loopback
4. **协议支持差异**：TCP / UDP / DHCP / DNS
5. **【必须】使用 `compare_call_graphs` 对比 `sys_sendto` 或 `socket_write` 调用链**
   - 如果两个项目都不支持网络，此步跳过并在报告中注明

加载两个项目的 09_/10_/11_ section 报告，使用 `compare_feature_summary` 对比 D9_smp_security 和 D10_net_debug 维度。

**Call Graph 退避策略**：如果 compare_call_graphs 返回'未找到函数'或'Call Graph 获取失败'，改用 `grep_in_repo` 搜索对应函数名进行文本级对比，并在报告中标注'降级分析'。

输出格式：## 多核差异 → ## 安全机制差异 → ## 网络差异 → ## Call Graph差异 → ## 功能覆盖对比表""",
    },
    {
        "id": "c08_debug_diff",
        "title": "调试与错误处理差异",
        "prompt": """对比 {target} 与 {candidate} 的调试与错误处理系统：

【调试部分】：
1. **日志系统差异**：print/log 宏实现、日志级别设计
2. **Panic 处理差异**：是否有完整的栈回溯（Backtrace / dwarf 解析）
3. **调试接口差异**：交互式 Shell / GDB Stub / Monitor
4. **错误码设计差异**：Result/Error 类型定义

加载两个项目的 12_ section 报告进行对比。

输出格式：## 调试机制差异 → ## 错误处理机制差异 → ## 日志系统对比""",
    },
    {
        "id": "c09_innovation",
        "title": "创新点与代码重合分析",
        "prompt": """综合分析 {target} 相对于 {candidate} 的创新性：

1. **代码重合度评估**：
   - 关键数据结构是否雷同（TaskInner / MemorySet / PageTable 字段对比）
   - 核心算法是否相同（调度算法 / 内存分配器 / 页表操作）
   - Call Graph 结构相似度（基于前面阶段的 compare_call_graphs 结果）

2. **【必须】补充源码比对**：
   - 使用 `compare_call_graphs` 对比 `alloc_frame` 或 `alloc_pages` 物理内存分配调用链
   - 如果遇到 LSP 解析失效、宏无法展开的问题，**必须**使用 `search_code_snippets` 对两个项目分别搜索相关代码片段供判断依据，而不要凭猜想。

3. **{target} 独有的技术创新点**（{candidate} 没有的特性）：
   - 有而对方没有的高级特性（如 CoW / Lazy / HugePage / Signal trampoline）
   - 独特的架构设计（如接口/实现分离、组件化机制）
   - 额外的 FS 类型 / 网络协议 / 设备驱动支持
   - 更完善的错误处理 / 调试工具 / 测试体系

4. **{candidate} 独有的优势**：
   - 反向列出 {candidate} 有而 {target} 没有的特性

5. **总体结论**：
   - 按 [独立开发 / 受启发 / 改进版 / 高度相似] 四级评估
   - 给出 0-100 相似度评分（含评分理由）
   - 明确列出判断依据（哪些证据支撑了你的结论）

使用 `load_project_fingerprint` 查看完整特征指纹进行综合判断。
使用 `compare_feature_summary` 对比所有 10 个维度的特征摘要。

**容错与退避策略**：遇到 `compare_call_graphs` 降级或失败时，搭配使用 `search_code_snippets` 和 `grep_in_repo` 来获取代码级别的特征供比对。

输出格式：## 代码重合度 → ## 源码/Call Graph 比对结果 → ## {target} 创新点列表 → ## {candidate} 优势列表 → ## 总体结论与评分""",
    },
]



def _build_compare_agent(target_name: str, candidate_name: str):
    """构建精比 Agent。"""
    from tools.compare_ops import (
        load_project_report,
        load_project_fingerprint,
        compare_call_graphs,
        compare_feature_summary,
        search_code_snippets,
    )
    from tools.file_ops import read_code_segment, grep_in_repo

    system_prompt = f"""你是 OS 技术比对专家。正在对比两个操作系统项目：
- 目标项目: {target_name}
- 候选项目: {candidate_name}

**全局分析要求（严格遵守）**：

1. **证据为王**：每一个差异结论必须引用具体文件路径或代码片段。不得凭经验或猜测下结论。
2. **反向证据原则**：如果未找到某功能的实现代码，必须明确说明'未发现'或'未实现'。严禁因为它是操作系统就假设它实现了某标准功能。
3. **桩代码检测**：对每个功能特性，必须区分三种状态：
   - ✅ 已实现：存在完整的业务逻辑代码
   - 🔸 桩函数：函数体为空、仅返回 Ok(0)/0/ENOSYS、或标注 todo!/unimplemented!
   - ❌ 未实现：代码中完全不存在相关结构或函数
4. **区分'代码相同'和'设计思路相似'**：
   - '代码相同'：数据结构字段名和函数调用链高度一致
   - '设计思路相似'：采用同类算法但实现细节不同
5. **创新点主动发现**：在每个维度比对时，如果发现目标项目有而候选项目没有的独特实现，标注为【创新点】。
6. **差异大的维度重点分析**，差异小的维度简要总结
7. **输出格式**：最终输出完整 Markdown 格式对比报告"""

    tools = [
        load_project_report,
        load_project_fingerprint,
        compare_call_graphs,
        compare_feature_summary,
        search_code_snippets,
        read_code_segment,
        grep_in_repo,
    ]

    llm = ChatOpenAI(
        model=get_model_name(),
        temperature=0,
        request_timeout=240,
        max_retries=2,
    )
    return create_react_agent(llm, tools), system_prompt


def run_fine_compare(
    target_name: str,
    candidates: list,
    output_dir: str = DEFAULT_OUTPUT_DIR,
):
    """
    执行精比流程。

    Args:
        target_name: 目标项目名称
        candidates:  候选列表 [{"name": str, "total_score": float, ...}, ...]
        output_dir:  输出根目录
    """
    print("\n" + "=" * 80)
    print("🔬 OS-Agent C 精比：源码级深度比对")
    print("=" * 80)
    print(f"   目标:   {target_name}")
    print(f"   候选数: {len(candidates)}")
    print(f"   ⏰ 开始: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80)

    comparison_dir = os.path.join(output_dir, target_name, "comparison_details")
    os.makedirs(comparison_dir, exist_ok=True)

    from core.error_handling import (
        ErrorTracker, classify_error, calculate_backoff, RetryConfig,
    )
    error_tracker = ErrorTracker(comparison_dir)

    all_reports = []

    for rank, cand_info in enumerate(candidates, 1):
        cand_name = cand_info["name"]
        total_score = cand_info.get("total_score", 0)

        report_path = os.path.join(comparison_dir, f"vs_{cand_name}.md")

        # 断点续传
        if os.path.exists(report_path) and os.path.getsize(report_path) > 200:
            print(f"\n⏭️  #{rank} vs {cand_name} (报告已存在)")
            all_reports.append(report_path)
            continue

        print(f"\n{'=' * 60}")
        print(f"🆚 #{rank}: {target_name} vs {cand_name} (粗筛得分: {total_score:.4f})")
        print(f"{'=' * 60}")

        agent, system_prompt = _build_compare_agent(target_name, cand_name)
        stage_texts = []

        for stage in COMPARE_STAGES:
            title = stage["title"]
            prompt = stage["prompt"].format(target=target_name, candidate=cand_name)
            print(f"\n   🧩 {stage['id']}: {title}")

            inputs = {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=prompt),
                ]
            }

            stage_text = ""
            succeeded = False

            # ── 重试循环（参考 Agent D 的退避机制） ──
            for retry in range(RetryConfig.MAX_RETRIES + 1):
                try:
                    if retry > 0:
                        backoff = calculate_backoff(retry - 1)
                        print(f"      🔄 第 {retry} 次重试（等待 {backoff}s）...")
                        time.sleep(backoff)

                    final_state = None
                    step_count = 0
                    for event in agent.stream(inputs, config={"recursion_limit": 100}):
                        step_count += 1
                        for _, state in event.items():
                            final_state = state
                        if step_count % 5 == 0:
                            print(f"      ... step {step_count}")

                    if final_state and final_state.get("messages"):
                        for m in reversed(final_state["messages"]):
                            if isinstance(m, AIMessage):
                                content = (m.content or "").strip()
                                tc = getattr(m, "tool_calls", None) or []
                                if content and not tc and len(content) > 100:
                                    stage_text = content
                                    break

                    if stage_text:
                        succeeded = True
                        break
                    else:
                        # 没有产出有效内容，视为 TOOL_ERROR 尝试重试
                        if retry < RetryConfig.MAX_RETRIES:
                            logger.warning(
                                f"[{stage['id']}] 未生成有效对比（attempt {retry + 1}），即将重试"
                            )
                        continue

                except Exception as e:
                    error_type = classify_error(e)
                    error_tracker.record_error(
                        section_name=stage["id"],
                        error_type=error_type,
                        exception=e,
                        retry_count=retry,
                        context={"candidate": cand_name},
                    )

                    # 判断是否可重试
                    if not RetryConfig.RETRYABLE_ERRORS.get(error_type, False):
                        logger.error(
                            f"[{stage['id']}] {error_type.value} 不可重试: {e}"
                        )
                        break

                    if retry >= RetryConfig.MAX_RETRIES:
                        logger.error(
                            f"[{stage['id']}] 已达最大重试次数 {RetryConfig.MAX_RETRIES}: {e}"
                        )
                        break

                    logger.warning(
                        f"[{stage['id']}] {error_type.value} (attempt {retry + 1}): {e}"
                    )

            # ── 生成最终阶段文本 ──
            if not stage_text:
                stage_text = f"> ⚠️ 阶段 {stage['id']} 未能生成有效对比（已重试 {retry} 次）"

            stage_texts.append(stage_text)
            if succeeded:
                retry_info = f"，重试 {retry} 次" if retry > 0 else ""
                print(f"      ✅ 完成 ({len(stage_text)} 字符{retry_info})")
            else:
                print(f"      ❌ 失败（已重试 {retry} 次）")

        # 合并为单个候选的对比报告
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# {target_name} vs {cand_name} 对比报告\n\n")
            f.write(f"> **粗筛相似度**: {total_score:.4f}\n")
            f.write(f"> **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write("---\n\n")
            for text in stage_texts:
                f.write(text + "\n\n---\n\n")

        all_reports.append(report_path)
        print(f"   📄 保存: {report_path}")

    # 错误报告
    error_tracker.save_error_report()
    if error_tracker.errors:
        print(f"\n⚠️  共发生 {len(error_tracker.errors)} 个错误，详见 {comparison_dir}/error_report.json")

    # 总报告
    _generate_summary(target_name, candidates, all_reports, output_dir)
    print(f"\n⏰ 完成: {datetime.now().strftime('%H:%M:%S')}")


def _generate_summary(target: str, candidates: list, reports: list, output_dir: str):
    """生成精比总报告。"""
    summary_path = os.path.join(output_dir, target, "comparison_report.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"# {target} 相似度对比总报告\n\n")
        f.write(f"> **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **分析工具**: OS-Agent-C (精比模块)\n\n---\n\n")
        f.write("## 粗筛结果\n\n| 排名 | 项目 | 相似度 |\n|------|------|--------|\n")
        for i, c in enumerate(candidates, 1):
            f.write(f"| {i} | {c['name']} | {c.get('total_score', 0):.4f} |\n")
        f.write("\n## 精比报告\n\n")
        for rp in reports:
            f.write(f"- [{os.path.basename(rp)}](comparison_details/{os.path.basename(rp)})\n")
        f.write(f"\n---\n*本报告由 OS-Agent-C 自动生成*\n")
    print(f"\n📄 总报告: {summary_path}")


# ═══════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="OS-Agent C 精比：源码级深度比对",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python os_agent_c_fine.py --target nonix
  python os_agent_c_fine.py --target nonix --candidates starry-mix,rcore-v3
  python os_agent_c_fine.py --target nonix --max-candidates 1
        """,
    )
    parser.add_argument(
        "--target", type=str, default=None,
        help="目标项目名称。未指定则从 REPO_URL 推断。",
    )
    parser.add_argument(
        "--candidates", type=str, default=None,
        help="手动指定候选项目列表（逗号分隔）。未指定则从粗筛结果读取。",
    )
    parser.add_argument(
        "--max-candidates", type=int, default=5,
        help="最多对比的候选数量（默认 5）",
    )
    parser.add_argument(
        "--output-dir", type=str, default=DEFAULT_OUTPUT_DIR,
        help="输出目录（默认 ./output）",
    )
    args = parser.parse_args()

    # 确定目标
    target_name = args.target
    if not target_name:
        repo_url = os.environ.get("REPO_URL", "").strip()
        if repo_url:
            target_name = repo_name_from_url(repo_url)
        else:
            print("❌ 请通过 --target 指定目标项目名，或在 .env 中设置 REPO_URL")
            sys.exit(1)

    # 确定候选列表
    candidates = []
    if args.candidates:
        # 手动指定
        for name in args.candidates.split(","):
            name = name.strip()
            if name:
                candidates.append({"name": name, "total_score": 0.0})
    else:
        # 从粗筛结果读取
        coarse_path = os.path.join(args.output_dir, target_name, "coarse_screening.json")
        if os.path.exists(coarse_path):
            with open(coarse_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            candidates = data.get("results", [])
            print(f"📂 从粗筛结果加载了 {len(candidates)} 个候选")
        else:
            print(f"❌ 未找到粗筛结果: {coarse_path}")
            print("   请先运行粗筛: python os_agent_c_coarse.py --target ...")
            sys.exit(1)

    candidates = candidates[: args.max_candidates]

    if not candidates:
        print("❌ 没有候选项目")
        sys.exit(1)

    run_fine_compare(target_name, candidates, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
