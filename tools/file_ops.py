"""
文件操作工具
"""
from langchain.tools import tool
import os
import re
from typing import Optional

# 允许访问的根目录（相对于工作目录）
ALLOWED_ROOTS = ["./repos", "./output", "repos", "output"]

# 最大读取字符数
MAX_FILE_CHARS = 100000


def _is_path_allowed(file_path: str) -> bool:
    """检查路径是否在允许的目录下"""
    abs_path = os.path.abspath(file_path)
    cwd = os.getcwd()
    
    for root in ALLOWED_ROOTS:
        allowed_abs = os.path.abspath(os.path.join(cwd, root))
        if abs_path.startswith(allowed_abs):
            return True
    return False


@tool
def read_code_segment(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None, max_chars: Optional[int] = None) -> str:
    """
    读取代码文件的指定片段。
    
    安全限制：只能访问 repos/、output/ 目录下的文件。
    
    Args:
        file_path: 文件路径（相对于工作目录或绝对路径）
        start_line: 起始行号（可选，从1开始）
        end_line: 结束行号（可选）
        max_chars: 最大读取字符数（可选，默认 100000）
    
    Returns:
        文件内容或指定行的内容。如果内容被截断，会在末尾标注。
    """
    try:
        # 路径安全检查
        if not _is_path_allowed(file_path):
            return (
                f"❌ 安全限制：不允许访问 '{file_path}'。\n"
                f"只能访问 repos/ 和 output/ 目录下的文件。\n"
                f"请使用类似 'repos/<project>/src/main.rs' 的路径。"
            )
        
        if not os.path.exists(file_path):
            return f"Error: File not found: {file_path}"
        
        if not os.path.isfile(file_path):
            return f"Error: '{file_path}' is not a file"
        
        # 获取文件大小
        file_size = os.path.getsize(file_path)
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        
        # 如果指定了行号范围
        if start_line is not None or end_line is not None:
            start = (start_line - 1) if start_line else 0
            end = end_line if end_line else len(lines)
            selected_lines = lines[start:end]
            content = ''.join(selected_lines)
            line_info = f"[显示行 {start+1}-{min(end, total_lines)}/{total_lines}]"
        else:
            content = ''.join(lines)
            line_info = f"[全部 {total_lines} 行]"
        
        # 检查是否需要截断
        limit = max_chars or MAX_FILE_CHARS
        if len(content) > limit:
            truncated_content = content[:limit]
            # 尝试在行边界截断
            last_newline = truncated_content.rfind('\n')
            if last_newline > limit * 0.8:
                truncated_content = truncated_content[:last_newline]
            
            truncated_lines = truncated_content.count('\n') + 1
            return (
                f"{truncated_content}\n\n"
                f"⚠️ [已截断] 显示了前 {truncated_lines} 行 / {len(truncated_content)} 字符\n"
                f"   原文共 {total_lines} 行 / {len(content)} 字符\n"
                f"   如需查看更多，请指定 start_line 和 end_line 参数"
            )
        
        return f"{content}\n\n{line_info} 共 {len(content)} 字符"
        
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool
def grep_in_repo(repo_path: str, pattern: str, max_results: int = 20, file_extensions: Optional[str] = None) -> str:
    """
    在仓库源代码中搜索关键词或正则模式。
    用于验证技术断言：如函数名、结构体名、算法名是否真实存在于源代码中。

    安全限制：只能搜索 repos/ 目录下的文件。

    Args:
        repo_path: 仓库本地路径（如 repos/my-os）
        pattern: 搜索模式（支持正则表达式，如 "struct PageTable" 或 "buddy|slab"）
        max_results: 最多返回的匹配数，默认 20
        file_extensions: 可选，用逗号分隔的文件扩展名过滤（如 "rs,c,h,S"），不含点号

    Returns:
        匹配结果列表，每条含：文件路径、行号、匹配行内容。
        如结果被截断会标注。
    """
    try:
        # 安全检查
        if not _is_path_allowed(repo_path):
            return (
                f"❌ 安全限制：不允许访问 '{repo_path}'。\n"
                f"只能搜索 repos/ 目录下的仓库。"
            )

        if not os.path.isdir(repo_path):
            return f"Error: 目录不存在: {repo_path}"

        # 解析扩展名过滤
        ext_filter = None
        if file_extensions:
            ext_filter = set("." + e.strip().lstrip(".") for e in file_extensions.split(","))

        # 编译正则
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"Error: 无效正则表达式 '{pattern}': {e}"

        exclude_dirs = {".git", ".github", "target", "node_modules", "vendor",
                        "__pycache__", ".devcontainer", "build", ".vscode"}

        # 默认搜索的代码文件扩展名
        default_code_exts = {
            ".rs", ".c", ".cpp", ".h", ".hpp", ".cc", ".cxx",
            ".s", ".S", ".asm",
            ".py", ".go", ".js", ".ts",
            ".toml", ".yaml", ".yml", ".json", ".md", ".txt",
            ".ld", ".x",  # 链接脚本
            ".mk", ".cmake",
        }

        results = []
        files_searched = 0
        total_matches = 0

        for root, dirs, files in os.walk(repo_path):
            # 排除无关目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for fname in files:
                fpath = os.path.join(root, fname)
                _, ext = os.path.splitext(fname)
                ext_lower = ext.lower()

                # 扩展名过滤
                if ext_filter:
                    if ext_lower not in ext_filter:
                        continue
                elif ext_lower not in default_code_exts:
                    continue

                # 跳过过大文件（>2MB）
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
                                total_matches += 1
                                if len(results) < max_results:
                                    rel_path = os.path.relpath(fpath, repo_path).replace("\\", "/")
                                    line_text = line.rstrip()
                                    if len(line_text) > 200:
                                        line_text = line_text[:200] + "..."
                                    results.append(f"{rel_path}:{line_num}: {line_text}")
                except Exception:
                    continue

        if not results:
            return f"未找到匹配 '{pattern}' 的内容 (已搜索 {files_searched} 个文件)"

        output_lines = [f"搜索 '{pattern}' 的结果 ({total_matches} 个匹配, 搜索了 {files_searched} 个文件):\n"]
        output_lines.extend(results)

        if total_matches > max_results:
            output_lines.append(f"\n⚠️ [已截断] 显示了前 {max_results}/{total_matches} 个匹配")

        return "\n".join(output_lines)

    except Exception as e:
        return f"Error: {str(e)}"

@tool
def rag_search_code(repo_path: str, query: str, top_k: int = 3) -> str:
    """
    使用 RAG 引擎在整个代码库中进行自然语言语义或模糊搜索。
    当使用 grep_in_repo 和 lsp 工具由于无法猜准具体的函数名而找不到目标代码时，请使用本工具。
    只需描述你要找的功能，例如："物理页面的分配与回收机制"、"page replacement" 等。

    Args:
        repo_path: 仓库本地路径（如 repos/my-os）
        query: 自然语言描述的搜索意图或功能说明
        top_k: 最多返回的匹配代码块数量（默认 3）

    Returns:
        包含最相关代码块详细信息（所处文件、行数和具体代码段）的字符串。
    """
    try:
        from core.code_rag import CodeRAGEngine
        if not _is_path_allowed(repo_path):
            return f"❌ 安全限制：不允许访问 '{repo_path}'。"
        if not os.path.exists(repo_path):
            return f"Error: 目录不存在: {repo_path}"

        project_name = os.path.basename(os.path.normpath(repo_path))
        # CodeRAGEngine 默认会在 ./output/<project_name>/_vector_db 中建库
        engine = CodeRAGEngine(project_name=project_name)
        
        # 构建或加载索引（force=False表示如果已有则直接加载）
        engine.build_index(repo_path, force=False)

        results = engine.search(query, top_k=top_k)
        if not results:
            return "❌ 未找到任何高度相关的代码片段。请尝试不同的关键词描述。"
        
        out = [f"RAG 语义搜索 '{query}' 找到的 Top {top_k} 代码块:\n"]
        for i, res in enumerate(results, 1):
            score = res.get('similarity_score', 0.0)
            node_type = res.get('node_type', 'unknown')
            file_path = res.get('file_path', 'unknown')
            name = res.get('name', 'unnamed')
            start_line = res.get('start_line', 0)
            end_line = res.get('end_line', 0)
            code = res.get('code', '')[:800] # 截断部分代码防止过长
            out.append(f"[{i}] 相似度: {score:.4f} | 文件: {file_path}:{start_line}-{end_line} | 类型: {node_type} | 符号名: {name}")
            out.append(f"```\n{code}\n```\n")
            if len(res.get('code', '')) > 800:
                out.append("... [代码段被截断，可使用 read_code_segment 工具查看完整内容]\n")
                
        return "\n".join(out)
    except Exception as e:
        import traceback
        return f"Error running RAG search: {str(e)}\n{traceback.format_exc()}"
