# evaluate.py
"""
OS-Agent D 评估模块（增强版：重试机制 + 错误追溯 + 鲁棒性）

工作原理：
1. 从 .env 读取 MODEL_NAME、REPO_URL，解析 repo_path 和 output_dir
2. 扫描 output/<os>/sections/*.md 的生成报告
3. 每个章节启动独立 Agent（无共享记忆），对比人类文档与生成报告
4. 冲突时以 OS 源码为权威，使用工具验证
5. 输出至 evaluation/<os_name>/：sections/*.json、summary.json、evaluation_report.md
6. 14(开发历史)、15(执行摘要) 不参与验证，评估仅覆盖 01-13 章

增强功能：
- 智能重试机制（指数退避、错误分类）
- 完整错误追溯（堆栈、上下文、诊断报告）
- 鲁棒性提升（超时控制、输入验证、优雅降级）
"""

import time
import logging
import argparse
import json
import os
import sys
import glob
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

from tools.eval_ops import (
    find_human_docs,
    read_human_doc,
    verify_claim_in_source,
    list_section_files,
    list_directory,
    read_generated_section,
)
from tools.file_ops import read_code_segment, grep_in_repo
from tools.describe_ops import analyze_tech_stack
from tools.git_ops import get_dev_history_by_module

load_dotenv()


# ============================================================
# 错误分类与重试策略
# ============================================================

class ErrorType(Enum):
    """错误类型枚举"""
    NETWORK_ERROR = "网络错误"
    API_ERROR = "API错误"
    TIMEOUT_ERROR = "超时错误"
    PARSE_ERROR = "解析错误"
    VALIDATION_ERROR = "验证错误"
    TOOL_ERROR = "工具执行错误"
    UNKNOWN_ERROR = "未知错误"


class RetryConfig:
    """重试配置"""
    MAX_RETRIES = 3  # 最大重试次数
    INITIAL_BACKOFF = 2  # 初始退避时间（秒）
    MAX_BACKOFF = 60  # 最大退避时间（秒）
    BACKOFF_MULTIPLIER = 2  # 退避倍数

    # 不同错误类型的重试策略
    RETRYABLE_ERRORS = {
        ErrorType.NETWORK_ERROR: True,
        ErrorType.API_ERROR: True,
        ErrorType.TIMEOUT_ERROR: True,
        ErrorType.PARSE_ERROR: False,  # 解析错误重试无意义
        ErrorType.VALIDATION_ERROR: False,
        ErrorType.TOOL_ERROR: True,
        ErrorType.UNKNOWN_ERROR: True,
    }


def classify_error(exception: Exception) -> ErrorType:
    """分类异常类型"""
    error_msg = str(exception).lower()
    error_type_name = type(exception).__name__.lower()

    # 网络相关错误
    if any(keyword in error_msg for keyword in ["connection", "network", "socket", "dns"]):
        return ErrorType.NETWORK_ERROR
    if any(keyword in error_type_name for keyword in ["connection", "timeout", "socket"]):
        return ErrorType.NETWORK_ERROR

    # API 错误
    if any(keyword in error_msg for keyword in ["api", "rate limit", "quota", "429", "503"]):
        return ErrorType.API_ERROR
    if "openai" in error_type_name or "api" in error_type_name:
        return ErrorType.API_ERROR

    # 超时错误
    if "timeout" in error_msg or "timeout" in error_type_name:
        return ErrorType.TIMEOUT_ERROR

    # JSON 解析错误
    if "json" in error_msg or "json" in error_type_name:
        return ErrorType.PARSE_ERROR

    # 工具执行错误
    if "tool" in error_msg:
        return ErrorType.TOOL_ERROR

    return ErrorType.UNKNOWN_ERROR


def calculate_backoff(retry_count: int) -> int:
    """计算退避时间（指数退避）"""
    backoff = RetryConfig.INITIAL_BACKOFF * (RetryConfig.BACKOFF_MULTIPLIER ** retry_count)
    return min(backoff, RetryConfig.MAX_BACKOFF)


# ============================================================
# 错误记录与追溯
# ============================================================

class ErrorTracker:
    """错误追踪器"""

    def __init__(self, eval_dir: str):
        self.eval_dir = eval_dir
        self.errors = []
        self.error_stats = {error_type: 0 for error_type in ErrorType}

    def record_error(
        self,
        section_name: str,
        error_type: ErrorType,
        exception: Exception,
        retry_count: int,
        context: Dict[str, Any] = None
    ):
        """记录错误信息"""
        error_record = {
            "timestamp": datetime.now().isoformat(),
            "section": section_name,
            "error_type": error_type.value,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "traceback": traceback.format_exc(),
            "retry_count": retry_count,
            "context": context or {}
        }

        self.errors.append(error_record)
        self.error_stats[error_type] += 1

        # 记录到日志
        logging.error(
            f"[{section_name}] {error_type.value} (重试: {retry_count}): "
            f"{type(exception).__name__}: {exception}"
        )
        logging.debug(f"错误堆栈:\n{error_record['traceback']}")

    def save_error_report(self):
        """保存错误报告"""
        if not self.errors:
            return

        error_report_path = os.path.join(self.eval_dir, "error_report.json")
        try:
            with open(error_report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "total_errors": len(self.errors),
                    "error_statistics": {k.value: v for k, v in self.error_stats.items()},
                    "errors": self.errors
                }, f, ensure_ascii=False, indent=2)

            logging.info(f"错误报告已保存: {error_report_path}")
            print(f"📋 错误报告已保存: {error_report_path}")
        except Exception as e:
            logging.error(f"保存错误报告失败: {e}")

    def generate_error_summary(self) -> str:
        """生成错误摘要（Markdown格式）"""
        if not self.errors:
            return "## 错误统计\n\n✅ 无错误发生\n"

        lines = [
            "## 错误统计",
            "",
            f"- **总错误数**: {len(self.errors)}",
            ""
        ]

        # 按错误类型统计
        lines.append("### 错误类型分布")
        lines.append("")
        for error_type, count in self.error_stats.items():
            if count > 0:
                lines.append(f"- **{error_type.value}**: {count} 次")

        lines.append("")
        lines.append("### 详细错误列表")
        lines.append("")

        for i, error in enumerate(self.errors, 1):
            lines.append(f"#### 错误 {i}: {error['section']}")
            lines.append(f"- **类型**: {error['error_type']}")
            lines.append(f"- **异常**: {error['exception_type']}")
            lines.append(f"- **消息**: {error['exception_message']}")
            lines.append(f"- **重试次数**: {error['retry_count']}")
            lines.append(f"- **时间**: {error['timestamp']}")
            lines.append("")

        return "\n".join(lines)

# ============================================================
# 配置与常量
# ============================================================

DEFAULT_MODEL = os.environ.get("MODEL_NAME", "deepseek/deepseek-v3.2")
EVAL_MODEL = os.environ.get("EVAL_MODEL_NAME") or DEFAULT_MODEL

# 章节关键词映射（用于 find_human_docs）
SECTION_KEYWORDS = {
    "启动": ["boot", "init", "startup", "entry", "arch"],
    "内存": ["mm", "memory", "paging", "heap", "alloc"],
    "进程": ["process", "task", "thread", "scheduler", "sched"],
    "中断": ["interrupt", "irq", "trap", "exception", "handler"],
    "文件": ["fs", "filesystem", "file", "vfs"],
    "设备": ["driver", "device", "hal", "bsp"],
    "同步": ["sync", "mutex", "lock", "atomic"],
    "多核": ["smp", "multicore", "hart", "cpu"],
    "网络": ["net", "network", "tcp", "ip", "socket"],
    "安全": ["security", "permission", "user", "access"],
    "调试": ["debug", "panic", "log", "error"],
    "测试": ["test", "ci", "spec"],
    "历史": ["history", "log", "commit", "dev"],
}

# 维度权重
DIMENSION_WEIGHTS = {
    "coverage": 0.25,
    "accuracy": 0.35,
    "depth": 0.20,
    "citations": 0.10,
    "highlights": 0.10,
}

# 评估工具列表（含 analyze_tech_stack 用于验证文件数量统计等）
EVAL_TOOLS = [
    find_human_docs,
    read_human_doc,
    read_generated_section,
    verify_claim_in_source,
    list_section_files,
    list_directory,
    read_code_segment,
    grep_in_repo,
    analyze_tech_stack,
    get_dev_history_by_module,
]

# JSON Schema 示例（供 LLM 输出参考）
SECTION_JSON_SCHEMA = '''
{
  "section_name": "02_内存管理",
  "coverage": {
    "score": 75,
    "human_doc_point_count": 12,
    "covered_points": ["Buddy System", "PageTable 操作"],
    "missing_points": ["Slab 分配器", "缺页处理"],
    "deduction_reasons": [{"point": "Slab 分配器", "severity": "major", "deduct": 5}]
  },
  "accuracy": {
    "score": 82,
    "errors": [{"desc": "FrameAllocator 路径描述错误", "severity": "minor", "verified": "false", "source_ref": "mm/alloc.rs"}],
    "fabrications": []
  },
  "depth": {"score": 70, "reason": "有代码引用但缺少完整流程"},
  "citations": {"score": 65, "file_refs": 5, "code_refs": 3},
  "highlights": {"score": 55, "items": [{"desc": "补充了 heap 初始化调用链", "evidence": "heap_init -> ..."}]},
  "weighted_total": 74.2,
  "summary": "覆盖较好，但在 Slab 和缺页方面缺失；有一处路径错误。"
}
'''


def _repo_name_from_url(repo_url: str) -> str:
    name = repo_url.rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".git") else name


def _format_tool_call_summary(tool_name: str, tool_args: dict) -> str:
    """格式化工具调用为简洁摘要"""
    if tool_name in ("read_code_segment", "read_human_doc"):
        file_path = tool_args.get("file_path", tool_args.get("path", "?"))
        start = tool_args.get("start_line", tool_args.get("start", ""))
        end = tool_args.get("end_line", tool_args.get("end", ""))
        if start and end:
            return f"{file_path} L{start}-L{end}"
        elif start:
            return f"{file_path} L{start}"
        return file_path or "?"

    elif tool_name in ("list_directory", "list_section_files"):
        path = tool_args.get("path", tool_args.get("output_dir", "?"))
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

    elif tool_name == "grep_in_repo":
        path = tool_args.get("repo_path", "")
        pattern = str(tool_args.get("pattern", "?"))[:30]
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else ""
        return f'"{pattern}"' + (f" in {dirname}/" if dirname else "")

    elif tool_name == "analyze_tech_stack":
        path = tool_args.get("repo_path", "?")
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/"

    elif tool_name == "get_dev_history_by_module":
        path = tool_args.get("repo_path", "?")
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/"

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

    if tool_name in ("read_code_segment", "read_human_doc"):
        return f"返回 {line_count} 行 ({content_len} 字符)"
    elif tool_name in ("list_directory", "list_section_files"):
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
    elif tool_name == "grep_in_repo":
        match_count = content.count("\n") if content.strip() else 0
        return f"找到 {match_count} 个匹配"
    elif tool_name == "analyze_tech_stack":
        if "代码文件统计" in content or "Rust" in content:
            return "返回技术栈与文件统计"
        return f"返回 {len(content)} 字符"
    elif tool_name == "get_dev_history_by_module":
        return f"返回开发历史 ({line_count} 行)"
    else:
        return f"返回 {content_len} 字符 ({line_count} 行)"


def _print_eval_step(
    step_num: int,
    node_name: str,
    state: dict,
    max_steps: int = 500,
) -> int:
    """打印评估 Agent 每一步的执行信息"""
    token_count = 0
    messages = state.get("messages", [])
    if not messages:
        return 0

    msg_to_show = messages if step_num == 1 else [messages[-1]]

    for msg in msg_to_show:
        if isinstance(msg, AIMessage):
            content = msg.content or ""
            tool_calls = getattr(msg, "tool_calls", None) or []

            if step_num > 0:
                print(f"\n【Step {step_num}/{max_steps}】", end=" ")

            if tool_calls:
                print("🔧 Tool Calls:")
                for tc in tool_calls:
                    tool_name = tc.get("name", "unknown") if isinstance(tc, dict) else getattr(tc, "name", "unknown")
                    tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    summary = _format_tool_call_summary(tool_name, tool_args)
                    print(f"   {tool_name}({summary})")
            elif content.strip():
                preview = content.strip()[:200] + ("..." if len(content) > 200 else "")
                print(f"🤔 Agent: {preview}")

            metadata = getattr(msg, "response_metadata", {})
            usage = metadata.get("token_usage", {})
            if usage:
                total_this = usage.get("total_tokens", 0)
                if total_this > 0:
                    token_count += total_this
                    inp = usage.get("prompt_tokens", 0)
                    out = usage.get("completion_tokens", 0)
                    print(f"   📄 Tokens: {total_this:,} (输入:{inp:,} + 输出:{out:,})")

        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "unknown")
            content = msg.content or ""
            summary = _format_tool_result_summary(tool_name, content)
            print(f"   ✅ {tool_name}: {summary}")

    sys.stdout.flush()
    return token_count


def _get_keywords_for_section(section_name: str) -> str:
    kw = ["os", "kernel", "design"]
    for key, vals in SECTION_KEYWORDS.items():
        if key in section_name:
            kw.extend(vals)
            break
    return " ".join(kw)


def _build_section_prompt(
    section_name: str,
    section_path: str,
    repo_path: str,
    output_dir: str,
    keywords: str,
) -> str:
    # 针对“开发历史”章节的特殊验证指令
    extra_instructions = ""
    # if "14_" in section_name ... (Reverted as per user request)

    return f'''你是一个严格的 OS 报告评分员。你的任务是：对比【人类文档】和【Agent 生成报告】，以【OS 源码】为冲突时的最终权威，对生成报告进行非对称评估。

## 重要规则（必须遵守）
1. **冲突裁决**：人类文档说 A、生成报告说 B 时，必须用 grep_in_repo 或 verify_claim_in_source 在源码中验证，以源码为准。
2. **缺失**：人类文档有的关键点，生成报告没有 -> coverage 扣分。
3. **捏造**：人类文档和源码都没有，生成报告却写了 -> accuracy 扣分。
4. **超越**：人类文档简略，生成报告通过源码分析补充了正确细节 -> highlights 加分。
5. **禁止空洞褒奖**：每个扣分/加分必须有具体依据（point_id、reason、evidence），不得写"分析透彻"等空话。

## 评估目标
- 章节文件：{section_path}
- 仓库路径：{repo_path}
- 输出目录：{output_dir}
- 关键词（用于 find_human_docs）：{keywords}

## 你必须执行的工作流
1. 用 find_human_docs(repo_path="{repo_path}", keywords="{keywords}") 找到人类文档。
2. 用 read_human_doc 阅读人类文档（优先 PDF、README、Design），提炼本模块的**所有关键设计点**。若文档提示 [TRUNCATED] 或仅读取了部分页面，请通过调整 start_page 参数分页阅读。若 PDF 较大（>20页），务必分段阅读，确保不遗漏后续章节中的关键设计点。注意人类文档中"已实现"和"计划实现"的区别。
   **完成后，将关键设计点编号列成清单**（如 P1: xxx, P2: xxx, ...），便于后续逐条检查。
3. 用 read_generated_section(file_path="{section_path}") 阅读 Agent 生成的章节报告。
4. **结构化对照检查**：对照步骤 2 的关键点清单，逐条在生成报告中搜索是否覆盖。对于每个点，标注「已覆盖」或「缺失」。
5. 对生成报告中的**每个重要技术论断**，用 grep_in_repo 或 verify_claim_in_source 在源码中验证；对于**文件数量、技术栈**等统计类论断，使用 analyze_tech_stack 验证。对于每个验证结果，必须标注 "verified": "true"|"false"|"partial"。**禁止出现未经验证的 "verified": "false" 条目**——如果时间不够，优先验证疑似错误的论断。{extra_instructions}
6. 按以下细则打分，并在最后输出**唯一一条 JSON 消息**（不要其他任何文字）。

## 打分细则（严格执行，防止虚高）

### coverage（0-100）
- 人类文档关键点总数 N，报告中覆盖 M 个：基础分 = (M/N)*80
- 重要点（架构、核心算法）未覆盖：每点扣 5 分
- 次要点（配置、可选特性）未覆盖：每点扣 2 分
- **一致性保护**：如果 missing_points 为空（即全部覆盖），score 不得低于 (M/N)*80
- 必须列出：covered_points、missing_points、human_doc_point_count、deduction_reasons

### accuracy（0-100）
- 与源码明显矛盾（错误的结构体名、不存在的函数）：每处扣 15 分
- 描述模糊或部分错误：每处扣 8 分
- 细微不准确（参数顺序、常量值）：每处扣 3 分
- 无依据捏造（人类+源码均无）：每处扣 12 分
- 捏造具体数据结构字段/函数签名（代码中完全不存在的命名）：每处扣 18 分
- 必须列出：errors（含 desc、severity、verified、source_ref）、fabrications

### depth（0-100）
- 仅复述人类文档：30 分
- 有代码级分析但无引用：50 分
- 引用具体文件/函数/行号：70 分
- 对关键流程有完整代码追踪：90-100 分

### citations（0-100）
- 无路径引用：0 分
- 有路径但无行号或片段：40 分
- 有路径+函数/结构体名：70 分
- 有路径+行号或代码片段：100 分

### highlights（0-100，可超额）
- 基础分 50
- 人类文档基础上的合理扩展：每处 +10，上限 30
- 正确的源码级洞察：每处 +15，上限 45
- 高质量图表/流程梳理：+10
- 最终 = min(100, 50 + 加分)

### weighted_total
weighted_total = coverage*0.25 + accuracy*0.35 + depth*0.20 + citations*0.10 + highlights*0.10

## 自检清单（输出 JSON 前必须确认）
- coverage: missing_points 中的每个点是否确实在生成报告中找不到？
- coverage: **一致性检查**——如果 missing_points 为空，score 是否 >= (M/N)*80？
- accuracy: 每个 error 是否都有 source_ref 引用？verified 字段是否已如实填写？
- accuracy: 是否检查了生成报告中所有结构体/函数名在源码中的真实存在性？
- highlights: 加分项是否有具体 evidence？
- weighted_total: 是否按公式 coverage*0.25 + accuracy*0.35 + depth*0.20 + citations*0.10 + highlights*0.10 计算？

## 输出要求
完成所有工具调用后，你的**最后一条消息**必须且仅包含一个符合以下结构的 JSON 对象（可参考 schema，不要包含其他说明文字）：

{SECTION_JSON_SCHEMA.strip()}

请现在开始执行。'''


def _parse_section_json(text: str) -> Dict[str, Any]:
    """从 Agent 最终消息中解析 JSON"""
    if not text or not isinstance(text, str):
        return {}
    # 尝试提取 ```json ... ``` 块
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()
    elif "{" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if end > start:
            text = text[start:end]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def evaluate_section(
    section_path: str,
    repo_path: str,
    output_dir: str,
    model_name: str,
    error_tracker: Optional[ErrorTracker] = None,
) -> Dict[str, Any]:
    """
    评估单个章节（增强版：智能重试 + 错误追溯）

    Args:
        section_path: 章节文件路径
        repo_path: 仓库路径
        output_dir: 输出目录
        model_name: 模型名称
        error_tracker: 错误追踪器（可选）

    Returns:
        评估结果字典
    """
    section_name = os.path.basename(section_path)
    print(f"\n📌 评估章节: {section_name}")

    # 输入验证
    if not os.path.exists(section_path):
        error_msg = f"章节文件不存在: {section_path}"
        logging.error(f"[evaluate_section] {error_msg}")
        return {
            "section_name": section_name,
            "error": error_msg,
            "weighted_total": 0,
            "summary": "输入验证失败",
        }

    keywords = _get_keywords_for_section(section_name)
    prompt = _build_section_prompt(
        section_name=section_name,
        section_path=os.path.abspath(section_path),
        repo_path=os.path.abspath(repo_path),
        output_dir=os.path.abspath(output_dir),
        keywords=keywords,
    )

    # 初始化模型和 agent
    use_json_mode = os.environ.get("EVAL_USE_JSON_MODE", "false").lower() == "true"

    # 添加超时配置
    request_timeout = int(os.environ.get("EVAL_REQUEST_TIMEOUT", "300"))  # 默认300秒

    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        request_timeout=request_timeout,
        model_kwargs={"response_format": {"type": "json_object"}} if use_json_mode else {},
    )
    agent = create_agent(llm, EVAL_TOOLS)

    inputs = {"messages": [HumanMessage(content=prompt)]}
    RECURSION_LIMIT = 500
    final_state = None
    stage_step_count = 0
    stage_tokens = 0
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
                        f"[{section_name}] 错误类型 {error_type.value} 不适合重试，跳过"
                    )
                    break

                # 计算退避时间
                backoff = calculate_backoff(retry_count - 1)
                print(f"   🔄 正在重试 ({retry_count}/{RetryConfig.MAX_RETRIES})...")
                print(f"   ⏱️  等待 {backoff} 秒后重试（{error_type.value}）...")
                time.sleep(backoff)

                # 记录重试信息
                logging.info(
                    f"[{section_name}] 第 {retry_count} 次重试 "
                    f"(错误类型: {error_type.value}, 退避: {backoff}s)"
                )

            # 执行 agent
            for event in agent.stream(inputs, config={"recursion_limit": RECURSION_LIMIT}):
                stage_step_count += 1
                for node_name, state in event.items():
                    step_tokens = _print_eval_step(stage_step_count, node_name, state, RECURSION_LIMIT)
                    stage_tokens += step_tokens
                    final_state = state

            # 成功执行完成，跳出重试循环
            logging.info(f"[{section_name}] Agent 执行成功（步骤数: {stage_step_count}）")

            # 打印章节 Token 统计
            if stage_tokens > 0:
                print(f"\n{'='*60}")
                print(f"📊 章节评估总结: {section_name}")
                print(f"   - 步骤数: {stage_step_count}")
                print(f"   - Token使用: {stage_tokens:,}")
                print(f"{'='*60}")
                sys.stdout.flush()

            break

        except KeyboardInterrupt:
            logging.warning(f"[{section_name}] 用户中断执行")
            raise  # 用户中断直接抛出，不重试

        except Exception as e:
            last_exception = e
            error_type = classify_error(e)

            # 记录错误到追踪器
            if error_tracker:
                error_tracker.record_error(
                    section_name=section_name,
                    error_type=error_type,
                    exception=e,
                    retry_count=retry_count,
                    context={
                        "step_count": stage_step_count,
                        "model": model_name,
                        "recursion_limit": RECURSION_LIMIT,
                    }
                )

            # 打印错误信息
            print(f"   ❌ {error_type.value}: {type(e).__name__}: {e}")

            retry_count += 1

            # 如果达到最大重试次数
            if retry_count > RetryConfig.MAX_RETRIES:
                error_msg = f"超过最大重试次数 {RetryConfig.MAX_RETRIES}"
                logging.critical(
                    f"[{section_name}] {error_msg} - 最后错误: {type(e).__name__}: {e}"
                )
                logging.debug(f"完整堆栈:\n{traceback.format_exc()}")

                return {
                    "section_name": section_name,
                    "error": str(e),
                    "error_type": error_type.value,
                    "retry_count": retry_count - 1,
                    "weighted_total": 0,
                    "summary": f"评估失败 ({error_type.value})",
                    "traceback": traceback.format_exc()[:500],  # 保存部分堆栈
                }

    # 验证 final_state
    if not final_state:
        logging.error(f"[{section_name}] Agent 未返回有效状态")
        print(f"   ❌ Agent 未返回有效状态")
        return {
            "section_name": section_name,
            "error": "未返回有效状态",
            "weighted_total": 0,
            "summary": "评估失败（无状态）",
        }

    # 提取并解析 JSON 结果
    messages = final_state.get("messages", [])
    json_text = _extract_json_from_messages(messages)

    if not json_text:
        logging.warning(f"[{section_name}] 未找到 JSON 响应")
        # 尝试追问机制（类似 os_agent_d.py）
        json_text = _try_followup_for_json(agent, messages, section_name, RECURSION_LIMIT)

    result = _parse_section_json(json_text)

    # 验证结果
    if not result or not _validate_evaluation_result(result):
        logging.warning(
            f"[{section_name}] JSON 解析失败或验证失败. Raw: {json_text[:200] if json_text else 'None'}..."
        )
        result = {
            "section_name": section_name,
            "error": "无法解析或验证 JSON",
            "raw_preview": json_text[:500] if json_text else "",
            "weighted_total": 0,
            "summary": "解析失败",
        }
    else:
        result.setdefault("section_name", section_name)
        result["tokens_used"] = stage_tokens
        score = result.get("weighted_total", 0)
        logging.info(f"[{section_name}] 评估成功, 分数={score:.1f}")
        print(f"   ✅ {section_name}: {score:.1f} 分 - {result.get('summary', '')[:60]}...")

    return result


def _extract_json_from_messages(messages: List) -> str:
    """从消息列表中提取 JSON 文本"""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            content = (m.content or "").strip()
            tool_calls = getattr(m, "tool_calls", None) or []
            if content and not tool_calls:
                return content
    return ""


def _try_followup_for_json(agent, messages: List, section_name: str, recursion_limit: int) -> str:
    """尝试追问以获取 JSON 响应"""
    try:
        print(f"   🔄 [{section_name}] 未找到 JSON，尝试追问...")
        followup_msg = HumanMessage(content="""请直接输出评估 JSON（不要其他文字），格式如下：
```json
{
  "section_name": "...",
  "coverage": {"score": 75, ...},
  "accuracy": {"score": 82, ...},
  "depth": {"score": 70, ...},
  "citations": {"score": 65, ...},
  "highlights": {"score": 55, ...},
  "weighted_total": 74.2,
  "summary": "..."
}
```""")

        followup_inputs = {"messages": messages + [followup_msg]}
        followup_state = None

        for event in agent.stream(followup_inputs, config={"recursion_limit": min(10, recursion_limit)}):
            for node_name, state in event.items():
                followup_state = state

        if followup_state:
            return _extract_json_from_messages(followup_state.get("messages", []))

    except Exception as e:
        logging.warning(f"[{section_name}] 追问失败: {e}")

    return ""


def _validate_evaluation_result(result: Dict[str, Any]) -> bool:
    """验证评估结果的完整性"""
    required_fields = ["coverage", "accuracy", "depth", "citations", "highlights", "weighted_total"]

    for field in required_fields:
        if field not in result:
            logging.warning(f"评估结果缺少字段: {field}")
            return False

    # 验证分数范围
    score = result.get("weighted_total", -1)
    if not isinstance(score, (int, float)) or score < 0 or score > 100:
        logging.warning(f"weighted_total 超出范围: {score}")
        return False

    return True


def _aggregate_summary(section_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总各章节结果为 summary.json"""
    total = 0
    dim_scores = {"coverage": [], "accuracy": [], "depth": [], "citations": [], "highlights": []}
    all_missing = []
    all_errors = []
    all_highlights = []

    for r in section_results:
        w = r.get("weighted_total")
        if isinstance(w, (int, float)):
            total += w
        for dim in dim_scores:
            val = r.get(dim)
            if isinstance(val, dict) and "score" in val:
                dim_scores[dim].append(val["score"])
            elif isinstance(val, (int, float)):
                dim_scores[dim].append(val)
        cov = r.get("coverage", {})
        if isinstance(cov, dict):
            all_missing.extend(
                [{"section": r.get("section_name"), "point": p} for p in cov.get("missing_points", [])]
            )
        acc = r.get("accuracy", {})
        if isinstance(acc, dict):
            for e in acc.get("errors", []) + acc.get("fabrications", []):
                if isinstance(e, dict):
                    all_errors.append({"section": r.get("section_name"), **e})
                else:
                    all_errors.append({"section": r.get("section_name"), "desc": str(e)})
        hl = r.get("highlights", {})
        if isinstance(hl, dict):
            for item in hl.get("items", []):
                if isinstance(item, dict):
                    all_highlights.append({"section": r.get("section_name"), **item})
                else:
                    all_highlights.append({"section": r.get("section_name"), "desc": str(item)})

    n = len(section_results)
    avg = round(total / n, 1) if n > 0 else 0
    dim_avgs = {
        k: round(sum(v) / len(v), 1) if v else 0
        for k, v in dim_scores.items()
    }

    # 生成改进建议
    improvement_suggestions = []
    # 基于最低分维度
    if dim_avgs:
        weakest_dim = min(dim_avgs, key=dim_avgs.get)
        improvement_suggestions.append(f"最薄弱维度: {weakest_dim} ({dim_avgs[weakest_dim]}分), 建议优先改进")
    # 基于缺失项频次
    if all_missing:
        from collections import Counter
        missing_sections = Counter(m.get("section") for m in all_missing)
        top_missing = missing_sections.most_common(3)
        for sec, cnt in top_missing:
            improvement_suggestions.append(f"章节 {sec} 有 {cnt} 个缺失项, 需重点补充")
    # 基于捏造项
    fab_count = sum(1 for e in all_errors if "捏造" in str(e.get("desc", "")) or "fabricat" in str(e.get("desc", "")).lower())
    if fab_count > 0:
        improvement_suggestions.append(f"发现 {fab_count} 处捏造, 建议增强描述模块的源码验证要求")

    # 标记最低分章节
    section_scores_list = [{"name": r.get("section_name"), "score": r.get("weighted_total")} for r in section_results]
    valid_scores = [s for s in section_scores_list if isinstance(s.get("score"), (int, float)) and s["score"] > 0]
    weakest_sections = sorted(valid_scores, key=lambda x: x["score"])[:3] if valid_scores else []

    return {
        "overall_score": avg,
        "section_count": n,
        "dimension_averages": dim_avgs,
        "dimension_details": dim_scores,
        "all_missing": all_missing,
        "all_errors": all_errors,
        "all_highlights": all_highlights,
        "section_scores": section_scores_list,
        "improvement_suggestions": improvement_suggestions,
        "weakest_sections": weakest_sections,
    }


def _generate_report_md(
    summary: Dict[str, Any],
    section_results: List[Dict[str, Any]],
) -> str:
    """生成 evaluation_report.md"""
    lines = [
        "# OS-Agent D 评估报告",
        "",
        f"**综合评分**: {summary.get('overall_score', 0)} / 100",
        f"**评估时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**评估章节数**: {summary.get('section_count', 0)}",
        "",
        "---",
        "",
        "## 各维度平均分",
        "",
    ]
    for dim, score in summary.get("dimension_averages", {}).items():
        lines.append(f"- **{dim}**: {score}")
    lines.extend(["", "---", "", "## 分章节详细评分", ""])

    for r in section_results:
        name = r.get("section_name", "?")
        score = r.get("weighted_total", 0)
        s = r.get("summary", "")
        lines.append(f"### {name} (评分: {score})")
        lines.append("")
        lines.append(f"**总结**: {s}")
        lines.append("")

        cov = r.get("coverage", {})
        if isinstance(cov, dict):
            lines.append("- **覆盖情况**:")
            lines.append(f"  - 人类文档关键点数: {cov.get('human_doc_point_count', '?')}")
            lines.append(f"  - 已覆盖: {', '.join(cov.get('covered_points', [])) or '无'}")
            lines.append(f"  - 缺失: {', '.join(cov.get('missing_points', [])) or '无'}")
            for dr in cov.get("deduction_reasons", []):
                if isinstance(dr, dict):
                    lines.append(f"  - 扣分: {dr.get('point', '')} ({dr.get('severity', '')}) -{dr.get('deduct', 0)}")
            lines.append("")

        acc = r.get("accuracy", {})
        if isinstance(acc, dict):
            errs = acc.get("errors", [])
            fab = acc.get("fabrications", [])
            if errs or fab:
                lines.append("- **准确性**:")
                for e in errs:
                    if isinstance(e, dict):
                        lines.append(f"  - 错误: {e.get('desc', '')} (severity: {e.get('severity', '')}, 验证: {e.get('verified', '')})")
                    else:
                        lines.append(f"  - 错误: {e}")
                for f in fab:
                    if isinstance(f, dict):
                        lines.append(f"  - 捏造: {f.get('desc', f)}")
                    else:
                        lines.append(f"  - 捏造: {f}")
                lines.append("")

        hl = r.get("highlights", {})
        if isinstance(hl, dict):
            items = hl.get("items", [])
            if items:
                lines.append("- **亮点**:")
                for it in items:
                    if isinstance(it, dict):
                        lines.append(f"  - {it.get('desc', '')} (证据: {it.get('evidence', '')})")
                    else:
                        lines.append(f"  - {it}")
                lines.append("")

        lines.append("---")
        lines.append("")

    # 各章节维度评分表格
    lines.extend(["", "## 各章节维度评分", ""])
    lines.append("| 章节 | 综合 | coverage | accuracy | depth | citations | highlights |")
    lines.append("|------|------|----------|----------|-------|-----------|------------|")
    for r in section_results:
        name = r.get("section_name", "?")[:20]
        wt = r.get("weighted_total", 0)
        cov_s = r.get("coverage", {}).get("score", "-") if isinstance(r.get("coverage"), dict) else r.get("coverage", "-")
        acc_s = r.get("accuracy", {}).get("score", "-") if isinstance(r.get("accuracy"), dict) else r.get("accuracy", "-")
        dep_s = r.get("depth", {}).get("score", "-") if isinstance(r.get("depth"), dict) else r.get("depth", "-")
        cit_s = r.get("citations", {}).get("score", "-") if isinstance(r.get("citations"), dict) else r.get("citations", "-")
        hl_s = r.get("highlights", {}).get("score", "-") if isinstance(r.get("highlights"), dict) else r.get("highlights", "-")
        lines.append(f"| {name} | {wt} | {cov_s} | {acc_s} | {dep_s} | {cit_s} | {hl_s} |")
    lines.append("")

    lines.extend([
        "---",
        "",
        "## 汇总",
        "",
        f"- **缺失项总数**: {len(summary.get('all_missing', []))}",
        f"- **错误/捏造总数**: {len(summary.get('all_errors', []))}",
        f"- **亮点总数**: {len(summary.get('all_highlights', []))}",
        "",
    ])

    # 改进建议
    suggestions = summary.get("improvement_suggestions", [])
    if suggestions:
        lines.extend(["## 改进建议", ""])
        for i, sug in enumerate(suggestions, 1):
            lines.append(f"{i}. {sug}")
        lines.append("")

    # 最低分章节
    weakest = summary.get("weakest_sections", [])
    if weakest:
        lines.extend(["## 最需改进的章节", ""])
        for ws in weakest:
            lines.append(f"- **{ws.get('name', '?')}**: {ws.get('score', 0)} 分")
        lines.append("")

    lines.append("*本报告由 OS-Agent D 评估模块生成*")
    return "\n".join(lines)


def run_evaluation(
    repo_url: Optional[str] = None,
    repo_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    """
    运行评估流程（增强版：错误追踪 + 鲁棒性提升）
    """
    start_time = datetime.now()

    # 输入验证
    repo_url = repo_url or os.environ.get("REPO_URL", "").strip()
    if not repo_url:
        print("❌ 未设置 REPO_URL，请在 .env 中配置或通过 --repo-url 传入")
        sys.exit(1)

    repo_name = _repo_name_from_url(repo_url)
    repo_path = repo_path or os.path.normpath(os.path.join(".", "repos", repo_name))
    output_dir = output_dir or os.path.normpath(os.path.join(".", "output", repo_name))
    eval_dir = os.path.normpath(os.path.join(".", "evaluation", repo_name))
    sections_dir = os.path.join(output_dir, "sections")

    # 配置日志（增强版）
    os.makedirs(eval_dir, exist_ok=True)
    log_file = os.path.join(eval_dir, "evaluation.log")

    # 配置日志处理器（文件保存详细 DEBUG，控制台只显示核心 INFO）
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # 1. 文件处理器 (Detailed DEBUG)
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s - %(message)s"))

    # 2. 控制台处理器 (Concise INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s")) # 控制台只输出消息内容，干净利落

    # 清理已有 handlers 并添加新 handler
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logging.info("=" * 60)
    logging.info(f"评估任务启动: {repo_name}")
    logging.info(f"时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("=" * 60)

    # 初始化错误追踪器
    error_tracker = ErrorTracker(eval_dir)

    # 路径验证
    if not os.path.isdir(sections_dir):
        error_msg = f"未找到 sections 目录: {sections_dir}"
        logging.error(error_msg)
        print(f"❌ {error_msg}")
        print("   请先运行 os_agent_d.py 生成报告")
        sys.exit(1)

    if not os.path.isdir(repo_path):
        error_msg = f"未找到仓库目录: {repo_path}"
        logging.error(error_msg)
        print(f"❌ {error_msg}")
        sys.exit(1)

    # 查找章节文件
    sections = sorted(glob.glob(os.path.join(sections_dir, "*.md")))
    if not sections:
        error_msg = f"sections 目录为空: {sections_dir}"
        logging.error(error_msg)
        print(f"❌ {error_msg}")
        sys.exit(1)

    model_name = model or EVAL_MODEL
    sections_out_dir = os.path.join(eval_dir, "sections")
    os.makedirs(sections_out_dir, exist_ok=True)

    # 打印配置信息
    print("=" * 60)
    print("🚀 OS-Agent D 评估开始（增强版）")
    print(f"   仓库: {repo_name}")
    print(f"   repo_path: {repo_path}")
    print(f"   output_dir: {output_dir}")
    print(f"   评估输出: {eval_dir}")
    print(f"   模型: {model_name}")
    print(f"   章节总数: {len(sections)}")
    print(f"   日志文件: {log_file}")
    print(f"   重试配置: 最大{RetryConfig.MAX_RETRIES}次, 退避{RetryConfig.INITIAL_BACKOFF}-{RetryConfig.MAX_BACKOFF}秒")
    print("=" * 60)

    logging.info(f"配置: 模型={model_name}, 章节数={len(sections)}, 重试={RetryConfig.MAX_RETRIES}")

    # 评估各章节
    section_results = []
    success_count = 0
    fail_count = 0
    skip_count = 0
    total_tokens_used = 0

    for idx, sec_path in enumerate(sections, 1):
        sec_name = os.path.basename(sec_path)

        # 跳过不需要验证的章节
        if sec_name.startswith("14_") or sec_name.startswith("15_"):
            print(f"\n⏭️  [{idx}/{len(sections)}] 跳过（不验证）: {sec_name}")
            logging.info(f"Skipping section: {sec_name}")
            skip_count += 1
            continue

        logging.info(f"\n📊 进度: [{idx}/{len(sections)}] 评估中: {sec_name}")

        try:
            # 调用增强版评估函数
            result = evaluate_section(
                section_path=sec_path,
                repo_path=repo_path,
                output_dir=output_dir,
                model_name=model_name,
                error_tracker=error_tracker,
            )

            section_results.append(result)

            # 判断是否成功
            # 累计 token
            section_tokens = result.get("tokens_used", 0)
            total_tokens_used += section_tokens

            if result.get("error"):
                fail_count += 1
                logging.warning(f"章节评估失败: {sec_name}")
            else:
                success_count += 1
                logging.info(f"章节评估成功: {sec_name}, 分数={result.get('weighted_total', 0):.1f}")

            # 保存每章节的 JSON（增加错误处理）
            out_name = os.path.splitext(sec_name)[0] + ".json"
            out_path = os.path.join(sections_out_dir, out_name)

            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                logging.info(f"   📄 已保存结果: {out_name}")
            except Exception as e:
                logging.error(f"   ⚠️  保存报告章节失败 {out_path}: {e}")

        except KeyboardInterrupt:
            logging.warning("用户中断评估")
            print("\n\n⚠️  用户中断评估")
            break

        except Exception as e:
            # 捕获意外异常
            logging.exception(f"评估章节 {sec_name} 时发生意外错误: {e}")
            error_tracker.record_error(
                section_name=sec_name,
                error_type=ErrorType.UNKNOWN_ERROR,
                exception=e,
                retry_count=0,
                context={"stage": "run_evaluation"}
            )
            fail_count += 1

            # 优雅降级：继续评估下一章节
            print(f"   ⚠️  意外错误，跳过该章节: {e}")
            section_results.append({
                "section_name": sec_name,
                "error": f"意外错误: {str(e)}",
                "weighted_total": 0,
                "summary": "评估失败（意外错误）",
            })

    # 保存错误报告
    error_tracker.save_error_report()

    # 生成汇总报告
    if section_results:
        try:
            summary = _aggregate_summary(section_results)
            summary["evaluation_stats"] = {
                "total_sections": len(sections),
                "success": success_count,
                "failed": fail_count,
                "skipped": skip_count,
                "success_rate": f"{success_count / max(len(section_results), 1) * 100:.1f}%"
            }

            summary_path = os.path.join(eval_dir, "summary.json")
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            print(f"\n📄 汇总已保存: {summary_path}")
            logging.info(f"汇总报告已保存: {summary_path}")

        except Exception as e:
            logging.exception(f"生成汇总失败: {e}")
            print(f"\n⚠️  生成汇总失败: {e}")

        # 生成 Markdown 报告（包含错误摘要）
        try:
            report_md = _generate_report_md(summary, section_results)

            # 添加错误摘要
            error_summary = error_tracker.generate_error_summary()
            report_md += "\n\n---\n\n" + error_summary

            report_path = os.path.join(eval_dir, "evaluation_report.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_md)
            print(f"📄 评估报告已保存: {report_path}")
            logging.info(f"Markdown 报告已保存: {report_path}")

        except Exception as e:
            logging.exception(f"生成 Markdown 报告失败: {e}")
            print(f"\n⚠️  生成 Markdown 报告失败: {e}")

    # 最终统计
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print("\n" + "=" * 60)
    print("✅ 评估任务完成")
    print(f"   📊 统计:")
    print(f"      - 总章节数: {len(sections)}")
    print(f"      - 成功: {success_count}")
    print(f"      - 失败: {fail_count}")
    print(f"      - 跳过: {skip_count}")
    print(f"      - Token累计: {total_tokens_used:,}")
    if section_results:
        print(f"   🎯 综合评分: {summary.get('overall_score', 0):.1f} / 100")
    print(f"   ⏱️  耗时: {elapsed:.2f} 秒 ({elapsed / 60:.2f} 分钟)")
    print(f"   📋 日志: {log_file}")
    if error_tracker.errors:
        print(f"   ⚠️  错误数: {len(error_tracker.errors)} (详见错误报告)")
    print("=" * 60)

    logging.info("=" * 60)
    logging.info(f"评估任务完成: 成功={success_count}, 失败={fail_count}, 跳过={skip_count}")
    logging.info(f"耗时: {elapsed:.2f} 秒")
    logging.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="OS-Agent D 报告评估（分阶段、记忆隔离）")
    parser.add_argument("--repo-url", help="OS 仓库 URL（覆盖 .env 中的 REPO_URL）")
    parser.add_argument("--repo-path", help="仓库本地路径（默认从 REPO_URL 解析）")
    parser.add_argument("--output-dir", help="生成报告目录（默认 output/<repo_name>）")
    parser.add_argument("--model", help="LLM 模型名称（覆盖 .env）")

    args = parser.parse_args()

    run_evaluation(
        repo_url=args.repo_url,
        repo_path=args.repo_path,
        output_dir=args.output_dir,
        model=args.model,
    )


if __name__ == "__main__":
    main()
