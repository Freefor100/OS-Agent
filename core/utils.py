"""
公共工具函数模块

从 os_agent_d_describe.py 和 os_agent_d_evaluate.py 中提取的共享函数，
合并为超集版本，兼容两者的工具名称映射。
"""
import os


def repo_name_from_url(repo_url: str) -> str:
    """从 Git 仓库 URL 提取仓库名称"""
    name = repo_url.rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".git") else name


def format_tool_call_summary(tool_name: str, tool_args: dict) -> str:
    """格式化工具调用为简洁摘要（合并 describe + evaluate 两个版本的超集）"""

    # 文件读取类工具
    if tool_name in ("read_code_segment", "read_file", "read_human_doc"):
        file_path = tool_args.get("file_path", tool_args.get("path", "?"))
        start = tool_args.get("start_line", tool_args.get("start", tool_args.get("start_page", "")))
        end = tool_args.get("end_line", tool_args.get("end", ""))
        if start and end:
            return f"{file_path} L{start}-L{end}"
        elif start:
            return f"{file_path} L{start}"
        return file_path or "?"

    # 目录列表类工具
    elif tool_name in ("list_repo_structure", "list_directory", "list_section_files"):
        path = tool_args.get("repo_path", tool_args.get("path", tool_args.get("output_dir", "?")))
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/"

    # 人类文档搜索
    elif tool_name == "find_human_docs":
        path = tool_args.get("repo_path", "?")
        kw = tool_args.get("keywords", "")[:30]
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/" + (f' "{kw}"' if kw else "")

    # 声明验证
    elif tool_name == "verify_claim_in_source":
        claim = str(tool_args.get("claim", ""))[:40]
        return f'"{claim}..."' if len(claim) >= 40 else f'"{claim}"'

    # 搜索类工具
    elif tool_name in ("grep_search", "grep_in_repo"):
        pattern = str(tool_args.get("pattern", tool_args.get("query", "?")))[:30]
        path = tool_args.get("repo_path", tool_args.get("path", ""))
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else ""
        return f'"{pattern}"' + (f" in {dirname}/" if dirname else "")

    # 技术栈分析 / 核心模块发现
    elif tool_name in ("analyze_tech_stack", "find_os_core_modules"):
        path = tool_args.get("repo_path", tool_args.get("path", "?"))
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/"

    # Git 历史分析
    elif tool_name in ("analyze_git_history_detailed", "analyze_git_history", "get_git_history_summary", "get_dev_history_by_module", "generate_dev_history_charts"):
        path = tool_args.get("repo_path", "?")
        max_commits = tool_args.get("max_commits", "")
        skip = tool_args.get("skip", "")
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        extra = []
        if max_commits:
            extra.append(f"max={max_commits}")
        if skip:
            extra.append(f"skip={skip}")
        return f"{dirname}/" + (f" ({', '.join(extra)})" if extra else "")

    # LSP 定义/引用
    elif tool_name in ("lsp_get_definition", "lsp_get_references"):
        symbol = str(tool_args.get("symbol", "?"))
        file_path = str(tool_args.get("file_path", "?"))
        return f"{symbol} in {os.path.basename(file_path)}"

    # LSP 文档大纲
    elif tool_name == "lsp_get_document_outline":
        file_path = str(tool_args.get("file_path", "?"))
        return f"{os.path.basename(file_path)}"

    # 默认：显示第一个参数
    else:
        if tool_args:
            first_key = list(tool_args.keys())[0]
            first_val = str(tool_args[first_key])[:40]
            return f"{first_key}={first_val}"
        return ""


def format_tool_result_summary(tool_name: str, content: str) -> str:
    """格式化工具返回结果为简洁摘要（合并 describe + evaluate 两个版本的超集）"""
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
    elif tool_name in ("lsp_get_definition", "lsp_get_references", "lsp_get_document_outline"):
        lines = len(content.split("\n")) if content else 0
        return f"返回 {lines} 行关联信息"
    elif tool_name == "analyze_tech_stack":
        if "代码文件统计" in content or "Rust" in content:
            return "返回技术栈与文件统计"
        return f"返回 {content_len} 字符"
    elif tool_name in ("get_dev_history_by_module", "analyze_git_history_detailed", "analyze_git_history", "get_git_history_summary"):
        return f"返回开发历史 ({line_count} 行, {content_len} 字符)"
    else:
        return f"返回 {content_len} 字符 ({line_count} 行)"
