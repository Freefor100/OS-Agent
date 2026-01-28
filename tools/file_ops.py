"""
文件操作工具
"""
from langchain.tools import tool
import os

@tool
def read_code_segment(file_path: str, start_line: int = None, end_line: int = None) -> str:
    """
    读取代码文件的指定片段。
    
    Args:
        file_path: 文件路径（相对于工作目录或绝对路径）
        start_line: 起始行号（可选，从1开始）
        end_line: 结束行号（可选）
    
    Returns:
        文件内容或指定行的内容
    """
    try:
        # 如果文件路径是相对路径，可能需要相对于工作目录
        if not os.path.isabs(file_path):
            # 可以在这里添加工作目录的逻辑
            pass
        
        if not os.path.exists(file_path):
            return f"Error: File not found: {file_path}"
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 如果指定了行号范围
        if start_line is not None or end_line is not None:
            start = (start_line - 1) if start_line else 0
            end = end_line if end_line else len(lines)
            selected_lines = lines[start:end]
            return ''.join(selected_lines)
        
        # 返回整个文件
        return ''.join(lines)
        
    except Exception as e:
        return f"Error reading file: {str(e)}"
