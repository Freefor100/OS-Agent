"""
OS-Agent C: 精比阶段的 Agent 工具集

提供 Call Graph 差异对比、section 报告加载等 LangChain 工具，
供精比阶段的 LangGraph Agent 使用。
"""
import os
import re
import logging
from typing import Optional

from langchain.tools import tool

logger = logging.getLogger("compare_ops")

OUTPUT_DIR = "./output"


# ---------------------------------------------------------------------------
# 报告加载
# ---------------------------------------------------------------------------
@tool
def load_project_report(repo_name: str, section_id: str = "") -> str:
    """
    加载指定项目的分析报告内容。

    Args:
        repo_name:  项目名称（对应 output/<repo_name>/）
        section_id: 可选的 section 前缀过滤（如 "03_" 只加载内存管理章节）。
                    留空则加载全部 sections。

    Returns:
        报告内容文本。如果指定了 section_id，只返回匹配的 section 内容。
    """
    sections_dir = os.path.join(OUTPUT_DIR, repo_name, "sections")
    if not os.path.isdir(sections_dir):
        return f"❌ 未找到项目 {repo_name} 的分析报告目录: {sections_dir}"

    parts = []
    for fname in sorted(os.listdir(sections_dir)):
        if not fname.endswith(".md"):
            continue
        if section_id and not fname.startswith(section_id):
            continue
        fpath = os.path.join(sections_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
            # 截断保护
            if len(content) > 15000:
                content = content[:15000] + "\n... [截断，原文更长]"
            parts.append(f"--- {fname} ---\n{content}")
        except Exception as e:
            parts.append(f"--- {fname} ---\n[读取失败: {e}]")

    if not parts:
        return f"未找到匹配 section_id='{section_id}' 的报告文件"

    return "\n\n".join(parts)


@tool
def load_project_fingerprint(repo_name: str) -> str:
    """
    加载指定项目的特征指纹摘要。

    Args:
        repo_name: 项目名称

    Returns:
        各维度的结构化特征文本
    """
    import json
    fp_path = os.path.join(OUTPUT_DIR, repo_name, "fingerprint.json")
    if not os.path.exists(fp_path):
        return f"❌ 未找到项目 {repo_name} 的指纹文件: {fp_path}"

    try:
        with open(fp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        features = data.get("features", {})
        lines = [f"## {repo_name} 特征指纹\n"]
        for dim_id in sorted(features.keys()):
            lines.append(f"### {dim_id}\n{features[dim_id]}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 加载指纹失败: {e}"


# ---------------------------------------------------------------------------
# Call Graph 差异对比
# ---------------------------------------------------------------------------
# 关键入口函数列表
KEY_ENTRY_POINTS = [
    ("trap_handler",      "中断处理入口"),
    ("schedule",          "调度器入口"),
    ("handle_page_fault", "缺页异常处理"),
    ("sys_write",         "系统调用示例"),
    ("alloc_frame",       "物理内存分配"),
]


def _parse_call_tree_nodes(tree_text: str) -> set:
    """
    从 lsp_get_call_graph 的树形文本输出中提取函数名集合。

    输出格式示例：
        trap_handler (kernel/trap.rs:42)
        ├── handle_page_fault (kernel/mm/fault.rs:88)
        │   ├── cow_handler (kernel/mm/cow.rs:33)
        │   └── lazy_alloc (kernel/mm/lazy.rs:55)
        └── syscall_handler (kernel/syscall.rs:10)
    """
    nodes = set()
    for line in tree_text.splitlines():
        # 移除树状前缀
        cleaned = re.sub(r'^[\s│├└─]+', '', line).strip()
        if not cleaned:
            continue
        # 提取函数名（空格或括号之前的部分）
        match = re.match(r'(\w+)', cleaned)
        if match:
            nodes.add(match.group(1))
    return nodes


@tool
def compare_call_graphs(
    repo_a: str, repo_b: str, entry_function: str
) -> str:
    """
    对比两个项目中同一入口函数的 Call Graph 差异。

    内部分别调用 lsp_get_call_graph 获取两个项目的调用树，
    然后分析差异（共同调用、A 独有、B 独有）。

    Args:
        repo_a:         项目 A 名称（对应 repos/<repo_a>）
        repo_b:         项目 B 名称（对应 repos/<repo_b>）
        entry_function: 要对比的入口函数名（如 "trap_handler", "schedule"）

    Returns:
        差异对比报告文本
    """
    from tools.lsp_ops import lsp_get_call_graph
    from tools.file_ops import grep_in_repo

    results = {}
    for repo_name in [repo_a, repo_b]:
        repo_path = f"repos/{repo_name}"
        if not os.path.isdir(repo_path):
            results[repo_name] = f"[仓库不存在: {repo_path}]"
            continue

        # 先用 grep 找到函数所在文件
        grep_result = grep_in_repo.invoke({
            "repo_path": repo_path,
            "pattern": f"fn {entry_function}|def {entry_function}",
            "max_results": 5,
            "file_extensions": "rs,c,h,S",
        })

        # 解析第一个匹配的文件路径
        file_path = None
        for line in str(grep_result).splitlines():
            if ":" in line and not line.startswith("搜索") and not line.startswith("未找到"):
                file_path = line.split(":")[0].strip()
                break

        if not file_path:
            results[repo_name] = f"[未找到函数 {entry_function} 的定义]"
            continue

        # 调用 Call Graph
        try:
            cg = lsp_get_call_graph.invoke({
                "repo_path": repo_path,
                "file_path": file_path,
                "symbol": entry_function,
                "direction": "outgoing",
                "max_depth": 3,
            })
            results[repo_name] = str(cg)
        except Exception as e:
            results[repo_name] = f"[Call Graph 获取失败: {e}]"

    # 解析差异
    nodes_a = _parse_call_tree_nodes(results.get(repo_a, ""))
    nodes_b = _parse_call_tree_nodes(results.get(repo_b, ""))
    common = nodes_a & nodes_b
    only_a = nodes_a - nodes_b
    only_b = nodes_b - nodes_a

    report = [
        f"## Call Graph 对比：{entry_function}",
        f"",
        f"### {repo_a} 的调用树",
        f"```",
        results.get(repo_a, "[无数据]"),
        f"```",
        f"",
        f"### {repo_b} 的调用树",
        f"```",
        results.get(repo_b, "[无数据]"),
        f"```",
        f"",
        f"### 差异分析",
        f"- **共同调用** ({len(common)}): {', '.join(sorted(common)) or '无'}",
        f"- **{repo_a} 独有** ({len(only_a)}): {', '.join(sorted(only_a)) or '无'}",
        f"- **{repo_b} 独有** ({len(only_b)}): {', '.join(sorted(only_b)) or '无'}",
    ]
    return "\n".join(report)


@tool
def compare_feature_summary(repo_a: str, repo_b: str, dimension: str) -> str:
    """
    加载并并排显示两个项目在指定维度的特征摘要，方便 LLM 进行语义差异分析。

    Args:
        repo_a:    项目 A 名称
        repo_b:    项目 B 名称
        dimension: 维度 ID（如 "D3_memory", "D4_process_sched"）

    Returns:
        并排特征摘要文本
    """
    import json

    summaries = {}
    for name in [repo_a, repo_b]:
        fp_path = os.path.join(OUTPUT_DIR, name, "fingerprint.json")
        if os.path.exists(fp_path):
            with open(fp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            summaries[name] = data.get("features", {}).get(dimension, "[无此维度数据]")
        else:
            summaries[name] = "[未找到指纹文件]"

    return (
        f"## {dimension} 特征对比\n\n"
        f"### {repo_a}\n{summaries[repo_a]}\n\n"
        f"### {repo_b}\n{summaries[repo_b]}"
    )
