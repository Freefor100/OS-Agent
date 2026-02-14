"""
评估专用工具 — 供评估模块 (evaluate.py) 使用

复用 file_ops 中的 read_code_segment / grep_in_repo，
新增面向评估场景的文档搜索和源码验证工具。
"""
import os
import re
from typing import Optional

from langchain.tools import tool

# 复用已有工具模块的路径检查
from tools.file_ops import _is_path_allowed, ALLOWED_ROOTS, MAX_FILE_CHARS


# ============================================================
# 评估专用工具
# ============================================================

@tool
def find_human_docs(repo_path: str, keywords: str = "") -> str:
    """
    在 OS 仓库中搜索人类编写的文档文件。

    搜索策略：
    1. 所有 PDF 文件（通常是参赛文档/设计文档）
    2. 根目录及各级目录下的 README / DESIGN / 文档文件
    3. 如提供关键词，则额外匹配 .md/.txt/.rst 文件名

    Args:
        repo_path: 仓库本地路径（如 repos/my-os）
        keywords: 可选，空格分隔的关键词（如 "memory mm paging"），用于匹配文档文件名

    Returns:
        找到的文档文件列表（带相对路径和类型标签）
    """
    if not _is_path_allowed(repo_path):
        return f"❌ 错误：不允许访问路径 '{repo_path}'。"
    if not os.path.isdir(repo_path):
        return f"❌ 错误：'{repo_path}' 不是有效目录。"

    kw_list = keywords.lower().split() if keywords.strip() else []
    found = []

    text_exts = {".md", ".txt", ".rst", ".doc", ".docx"}
    global_exts = {".pdf"}
    important_names = {
        "readme.md", "design.md", "documentation.md", "guide.md",
        "readme.txt", "design.txt", "report.md", "设计文档.md",
        "设计说明.md", "技术报告.md",
    }

    exclude_dirs = {".git", ".github", "target", "node_modules",
                    "vendor", "__pycache__", ".devcontainer", "build",
                    ".vscode", "deps", ".venv"}

    for root, dirs, files in os.walk(repo_path):
        # 排除无关目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for f in files:
            ext = os.path.splitext(f)[1].lower()
            f_lower = f.lower()
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, repo_path)

            # 1. PDF 文件（高优先级）
            if ext in global_exts:
                size_kb = os.path.getsize(full_path) / 1024
                found.append(f"[PDF {size_kb:.0f}KB] {rel_path}")
                continue

            # 2. 全局重要文档
            if f_lower in important_names:
                found.append(f"[DOC] {rel_path}")
                continue

            # 3. 关键词匹配
            if ext in text_exts and kw_list:
                path_lower = rel_path.lower().replace("\\", "/")
                if any(k in f_lower or k in path_lower for k in kw_list):
                    found.append(f"[MATCH] {rel_path}")

    if not found:
        return "未找到相关人类文档。"

    found = sorted(set(found), key=lambda x: (
        not x.startswith("[PDF"),
        not x.startswith("[DOC"),
        x
    ))
    return "\n".join(found[:50])


@tool
def read_human_doc(file_path: str, max_chars: int = 80000) -> str:
    """
    读取人类文档内容（支持 .md, .txt, .pdf 等）。

    Args:
        file_path: 文档文件路径
        max_chars: 最大读取字符数，默认 80000

    Returns:
        文档文本内容
    """
    if not _is_path_allowed(file_path):
        return f"❌ 错误：不允许访问文件 '{file_path}'。"
    if not os.path.exists(file_path):
        return f"❌ 错误：文件不存在 '{file_path}'。"

    try:
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            try:
                import PyPDF2
                text_parts = []
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    num_pages = len(reader.pages)
                    max_pages = min(num_pages, 80)
                    text_parts.append(f"--- PDF ({max_pages}/{num_pages} pages) ---")
                    for i in range(max_pages):
                        page_text = reader.pages[i].extract_text()
                        if page_text:
                            text_parts.append(page_text)
                content = "\n".join(text_parts)
            except ImportError:
                return "❌ 未安装 PyPDF2，无法读取 PDF。"
            except Exception as e:
                return f"❌ PDF 读取失败: {e}"
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n... [已截断，原文共 {len(content)} 字符]"
        return content

    except Exception as e:
        return f"❌ 读取失败: {e}"


@tool
def verify_claim_in_source(repo_path: str, claim: str, search_patterns: str) -> str:
    """
    在 OS 源码中验证某个技术声明是否属实。

    使用方法：提供一个技术声明（如 "使用 Buddy System 分配物理内存"），
    以及用于搜索的关键模式（如 "buddy|BuddyAllocator|buddy_alloc"），
    工具会在源码中搜索并返回匹配结果。

    Args:
        repo_path: 仓库本地路径
        claim: 要验证的技术声明（自然语言描述）
        search_patterns: 用于在源码中搜索的正则模式，多个模式用竖线 | 分隔

    Returns:
        搜索结果 + 验证建议
    """
    if not _is_path_allowed(repo_path):
        return f"❌ 不允许访问 '{repo_path}'。"
    if not os.path.isdir(repo_path):
        return f"❌ '{repo_path}' 不存在。"

    exclude_dirs = {".git", ".github", "target", "node_modules", "vendor",
                    "__pycache__", ".devcontainer", "build", ".vscode"}

    code_exts = {
        ".rs", ".c", ".cpp", ".h", ".hpp", ".cc", ".cxx",
        ".s", ".S", ".asm",
        ".py", ".go", ".js", ".ts",
        ".toml", ".yaml", ".yml", ".json", ".md",
        ".ld", ".x", ".mk", ".cmake",
    }

    try:
        regex = re.compile(search_patterns, re.IGNORECASE)
    except re.error as e:
        return f"❌ 正则表达式错误: {e}"

    results = []
    files_searched = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for fname in files:
            fpath = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext not in code_exts:
                continue
            try:
                if os.path.getsize(fpath) > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue

            files_searched += 1
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = os.path.relpath(fpath, repo_path).replace("\\", "/")
                            text = line.rstrip()[:200]
                            results.append(f"{rel}:{line_num}: {text}")
                            if len(results) >= 30:
                                break
                if len(results) >= 30:
                    break
            except Exception:
                continue

    output = [f"🔍 验证声明: \"{claim}\"",
              f"   搜索模式: {search_patterns}",
              f"   搜索文件数: {files_searched}",
              f"   匹配数: {len(results)}",
              ""]

    if results:
        output.append("匹配结果:")
        output.extend(results)
        output.append("")
        output.append("✅ 源码中找到了相关匹配，声明可能属实。请结合上下文判断。")
    else:
        output.append("❌ 源码中未找到匹配，声明可能不准确。")

    return "\n".join(output)


@tool
def list_directory(path: str, max_items: int = 50) -> str:
    """
    列出目录下的文件和子目录（用于探索仓库或输出目录结构）。

    Args:
        path: 目录路径（如 repos/my-os 或 output/my-os）
        max_items: 最多返回的项数，默认 50

    Returns:
        目录项列表（目录以 / 结尾）
    """
    if not _is_path_allowed(path):
        return f"❌ 错误：不允许访问路径 '{path}'。"
    if not os.path.isdir(path):
        return f"❌ 错误：'{path}' 不是有效目录。"

    try:
        exclude = {".git", "__pycache__", "target", "node_modules", ".venv", "deps"}
        items = [i for i in os.listdir(path) if i not in exclude]
        items.sort()
        result = []
        for item in items[:max_items]:
            full = os.path.join(path, item)
            result.append(f"{item}/" if os.path.isdir(full) else item)
        if len(items) > max_items:
            result.append(f"... (共 {len(items)} 项)")
        return "\n".join(result) if result else "(空目录)"
    except Exception as e:
        return f"❌ 错误: {e}"


@tool
def list_section_files(output_dir: str) -> str:
    """
    列出 Agent 生成的所有章节文件。

    Args:
        output_dir: OS 输出目录（如 output/T202510003995291-2331）

    Returns:
        章节文件列表（带大小信息）
    """
    if not _is_path_allowed(output_dir):
        return f"❌ 错误：不允许访问路径 '{output_dir}'。"
    sections_dir = os.path.join(output_dir, "sections")
    if not os.path.isdir(sections_dir):
        return f"❌ sections 目录不存在: {sections_dir}"

    files = sorted(f for f in os.listdir(sections_dir) if f.endswith(".md"))
    if not files:
        return "❌ 未找到任何章节文件。"

    result = []
    for f in files:
        fpath = os.path.join(sections_dir, f)
        size_kb = os.path.getsize(fpath) / 1024
        result.append(f"  {f} ({size_kb:.1f} KB)")

    return f"找到 {len(files)} 个章节:\n" + "\n".join(result)
