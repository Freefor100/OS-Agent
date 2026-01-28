"""
文件操作工具
"""
from langchain.tools import tool
import os

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
def read_code_segment(file_path: str, start_line: int = None, end_line: int = None, max_chars: int = None) -> str:
    """
    读取代码文件的指定片段。
    
    安全限制：只能访问 repos/ 和 output/ 目录下的文件。
    
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

