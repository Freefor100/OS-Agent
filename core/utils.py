"""
公共工具函数模块

从 os_agent_d_describe.py 和 os_agent_d_evaluate.py 中提取的共享函数，
合并为超集版本，兼容两者的工具名称映射。
"""
import ast
import os
import json
import re


def _stringify_tool_arg(v):
    """尽量完整、单行地 stringify tool args（便于终端展示）。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        # 终端里保持单行可读
        return v.replace("\n", "\\n")
    if isinstance(v, (list, tuple, dict)):
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v).replace("\n", "\\n")
    return str(v).replace("\n", "\\n")


def repo_name_from_url(repo_url: str) -> str:
    """从 Git 仓库 URL 提取仓库名称"""
    # 移除末尾斜杠
    url = repo_url.rstrip("/\\")
    # 统一转换路径分隔符并取最后一部分
    name = url.replace(chr(92), "/").split("/")[-1]
    # 移除 .git 后缀
    if name.lower().endswith(".git"):
        name = name[:-4]
    return name


def _split_env_list_items(text: str) -> list:
    text = (text or "").strip()
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = []
    for item in re.split(r"[\n,]", normalized):
        item = item.strip().strip("'\"")
        if item:
            parts.append(item)
    return parts


def _parse_env_list_value(text: str):
    text = (text or "").strip()
    if not text:
        return []
    if text in {"{", "["}:
        return None

    if (text.startswith("[") and text.endswith("]")) or (text.startswith("(") and text.endswith(")")):
        try:
            value = ast.literal_eval(text)
            if isinstance(value, (list, tuple, set)):
                return [str(x).strip() for x in value if str(x).strip()]
        except Exception:
            pass

    if text.startswith("{") and text.endswith("}"):
        return _split_env_list_items(text[1:-1])

    return _split_env_list_items(text)


def _read_raw_env_assignment(var_name: str, dotenv_path: str = ".env") -> str:
    if not os.path.exists(dotenv_path):
        return ""

    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return ""

    pattern = re.compile(rf"^\s*{re.escape(var_name)}\s*=\s*(.*)$")
    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip("\n")
        match = pattern.match(line)
        if not match:
            idx += 1
            continue

        value = match.group(1).strip()
        if value.startswith("{") and not value.endswith("}"):
            collected = [value[1:]]
            idx += 1
            while idx < len(lines):
                current = lines[idx].rstrip("\n")
                stripped = current.strip()
                if stripped.endswith("}"):
                    collected.append(stripped[:-1])
                    break
                collected.append(current)
                idx += 1
            return "{" + "\n".join(collected) + "}"

        if value.startswith("[") and not value.endswith("]"):
            collected = [value[1:]]
            idx += 1
            while idx < len(lines):
                current = lines[idx].rstrip("\n")
                stripped = current.strip()
                if stripped.endswith("]"):
                    collected.append(stripped[:-1])
                    break
                collected.append(current)
                idx += 1
            return "[" + "\n".join(collected) + "]"

        return value

    return ""


def parse_env_repo_list(var_name: str, dotenv_path: str = ".env") -> list:
    """
    解析 .env 中的仓库列表变量，支持以下格式：
    - 单行逗号分隔：a,b,c
    - 单行大括号：{a, b, c}
    - 多行大括号：
      {
      a,
      b
      }
    - Python 风格列表：["a", "b"]
    """
    parsed = _parse_env_list_value(os.environ.get(var_name, ""))
    if parsed is not None:
        return parsed

    raw_value = _read_raw_env_assignment(var_name, dotenv_path=dotenv_path)
    parsed = _parse_env_list_value(raw_value)
    return parsed or []


def format_tool_call_summary(tool_name: str, tool_args: dict) -> str:
    """格式化工具调用为简洁摘要（合并 describe + evaluate 两个版本的超集）"""

    # OS-Agent C：调用图对比（避免只显示第一个参数）
    if tool_name == "compare_call_graphs":
        repo_a = tool_args.get("repo_a", "?")
        repo_b = tool_args.get("repo_b", "?")
        entry = tool_args.get("entry_function", tool_args.get("function_name", "?"))
        return f"repo_a={repo_a}, repo_b={repo_b}, entry_function={entry}"

    # OS-Agent C：函数 Token 相似度（避免只显示第一个参数）
    if tool_name == "compare_function_tokens":
        repo_a = tool_args.get("repo_a", "?")
        repo_b = tool_args.get("repo_b", "?")
        fn = tool_args.get("function_name", tool_args.get("entry_function", "?"))
        return f"repo_a={repo_a}, repo_b={repo_b}, function_name={fn}"

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
        kw = tool_args.get("keywords", "")
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/" + (f' "{kw}"' if kw else "")

    # 声明验证
    elif tool_name == "verify_claim_in_source":
        claim = str(tool_args.get("claim", ""))
        return f'"{claim}"'

    # 搜索类工具
    elif tool_name in ("grep_search", "grep_in_repo"):
        pattern = str(tool_args.get("pattern", tool_args.get("query", "?")))
        path = tool_args.get("repo_path", tool_args.get("path", ""))
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else ""
        extra = []
        # 兼容 grep_in_repo 的可选参数（如果存在就一起展示）
        if "file_extensions" in tool_args:
            extra.append(f"ext={tool_args.get('file_extensions')}")
        if "max_results" in tool_args:
            extra.append(f"max={tool_args.get('max_results')}")
        suffix = f" in {dirname}/" if dirname else ""
        return f'"{pattern}"{suffix}' + (f" ({', '.join(extra)})" if extra else "")

    # 技术栈分析 / 核心模块发现
    elif tool_name in ("analyze_tech_stack", "find_os_core_modules"):
        path = tool_args.get("repo_path", tool_args.get("path", "?"))
        dirname = os.path.basename(str(path).rstrip("/\\")) if path else "?"
        return f"{dirname}/"

    # Git 历史分析
    elif tool_name in ("analyze_git_history_detailed", "analyze_git_history", "get_git_history_summary", "get_dev_history_by_module", "generate_dev_history_charts", "trace_file_evolution", "analyze_authors_contribution", "get_commit_diff_summary"):
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

    # LSP 调用图
    elif tool_name == "lsp_get_call_graph":
        symbol = str(tool_args.get("symbol", "?"))
        file_path = str(tool_args.get("file_path", "?"))
        direction = str(tool_args.get("direction", "both"))
        return f"{symbol}({direction}) in {os.path.basename(file_path)}"

    # LSP 架构设置
    elif tool_name == "lsp_set_target_arch":
        target = str(tool_args.get("target", "?"))
        return f"target={target}"

    # 默认：显示第一个参数
    else:
        # 默认：尽量显示全部参数（避免“括号内容显示不全”）
        if not tool_args:
            return ""
        parts = []
        for k in sorted(tool_args.keys()):
            parts.append(f"{k}={_stringify_tool_arg(tool_args.get(k))}")
        return ", ".join(parts)


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
    elif tool_name == "lsp_set_target_arch":
        return f"成功切换架构并重启 LSP" if "Successfully" in content else f"切换失败: {content[:30]}..."
    elif tool_name == "analyze_tech_stack":
        if "代码文件统计" in content or "Rust" in content:
            return "返回技术栈与文件统计"
        return f"返回 {content_len} 字符"
    elif tool_name in ("get_dev_history_by_module", "analyze_git_history_detailed", "analyze_git_history", "get_git_history_summary", "trace_file_evolution", "analyze_authors_contribution", "get_commit_diff_summary"):
        return f"返回开发历史分析 ({line_count} 行, {content_len} 字符)"
    else:
        return f"返回 {content_len} 字符 ({line_count} 行)"
