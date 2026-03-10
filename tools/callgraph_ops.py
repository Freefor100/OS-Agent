# tools/callgraph_ops.py
import os
import re
import shutil
import tempfile
import subprocess
import logging
from typing import List, Optional, Set, Dict

logger = logging.getLogger("callgraph_ops")

def generate_doxyfile(repo_path: str, output_dir: str, target_files: Optional[List[str]] = None) -> str:
    """动态生成用于生成 Call Graph 的 Doxyfile。"""
    doxyfile_content = [
        f"PROJECT_NAME           = \"OS-Agent Analysis\"",
        f"OUTPUT_DIRECTORY       = \"{output_dir}\"",
        f"INPUT                  = \"{repo_path}\"" if not target_files else f"INPUT                  = " + " ".join([f'"{f}"' for f in target_files]),
        "RECURSIVE              = YES",
        "OPTIMIZE_OUTPUT_FOR_C  = YES",
        "EXTRACT_ALL            = YES",
        "EXTRACT_PRIVATE        = YES",
        "EXTRACT_STATIC         = YES",
        "GENERATE_HTML          = NO",
        "GENERATE_LATEX         = NO",
        "GENERATE_XML           = NO",
        "HAVE_DOT               = YES",
        "CALL_GRAPH             = YES",
        "CALLER_GRAPH           = NO",
        "DOT_CLEANUP            = NO", # 保留 .dot 文件以便我们解析
        # 容错降级关键配置 (模糊解析)
        "ENABLE_PREPROCESSING   = YES",
        "MACRO_EXPANSION        = NO",
        "SKIP_FUNCTION_MACROS   = YES",
        "SEARCH_INCLUDES        = NO", 
        "ALPHABETICAL_INDEX     = NO"
    ]
    
    doxyfile_path = os.path.join(output_dir, "Doxyfile")
    with open(doxyfile_path, "w", encoding="utf-8") as f:
        f.write("\n".join(doxyfile_content))
    return doxyfile_path

def parse_dot_to_mermaid(dot_file_path: str, root_func: str, max_depth: int = 3) -> str:
    """提取 .dot 文件中的有向边，并将其转化为 Mermaid 格式，控制最大深度。"""
    try:
        with open(dot_file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"无法读取 dot 文件 {dot_file_path}: {e}")
        return ""

    # 解析节点标签 Node1 [label="schedule", ...];
    node_pattern = re.compile(r'(Node\d+)\s*\[.*?label="([^"]+)"')
    nodes: Dict[str, str] = {}
    for match in node_pattern.finditer(content):
        nodes[match.group(1)] = match.group(2)
        
    # 解析边 Node1 -> Node2;
    edge_pattern = re.compile(r'(Node\d+)\s*->\s*(Node\d+)')
    edges: List[tuple] = []
    for match in edge_pattern.finditer(content):
        edges.append((match.group(1), match.group(2)))
        
    if not nodes or not edges:
        return ""

    # 寻找根节点 (假设标签包含 root_func，或者是第一个节点)
    root_node_id = None
    for n_id, label in nodes.items():
        if root_func in label:
            root_node_id = n_id
            break
            
    if not root_node_id:
        root_node_id = list(nodes.keys())[0]

    # BFS 控制深度
    visited = set()
    queue = [(root_node_id, 0)]
    valid_edges = set()
    
    while queue:
        curr_id, depth = queue.pop(0)
        if curr_id in visited or depth >= max_depth:
            continue
        visited.add(curr_id)
        
        for src, dst in edges:
            if src == curr_id:
                valid_edges.add((src, dst))
                queue.append((dst, depth + 1))
                
    if not valid_edges:
        return ""

    # 构建 Mermaid 字符串
    mermaid_lines = ["```mermaid", "graph TD"]
    for src, dst in valid_edges:
        src_label = nodes.get(src, src).replace('"', '').strip()
        dst_label = nodes.get(dst, dst).replace('"', '').strip()
        # 清理非法字符
        src_label = re.sub(r'[^a-zA-Z0-9_]', '_', src_label)
        dst_label = re.sub(r'[^a-zA-Z0-9_]', '_', dst_label)
        if src_label and dst_label:
             mermaid_lines.append(f"    {src_label} --> {dst_label}")
             
    mermaid_lines.append("```")
    return "\n".join(mermaid_lines)


def generate_fallback_callgraph(repo_path: str, entry_function: str, max_depth: int = 3, target_dirs: Optional[List[str]] = None) -> str:
    """
    使用 Doxygen 模糊解析生成退避式的 Mermaid 调用关系图。
    
    Args:
        repo_path: 目标仓库根目录
        entry_function: 核心入口函数名 (如 handle_page_fault)
        max_depth: 最大调用深度限制
        target_dirs: 仅扫描的特定子目录列表（减小解析范围）
    
    Returns:
        Mermaid 代码块字符串，失败则返回空字符串。
    """
    if not shutil.which("doxygen"):
        logger.warning("系统中未安装 Doxygen，无法使用 Call Graph 降级备份。")
        return ""

    input_paths = None
    if target_dirs:
        input_paths = [os.path.join(repo_path, d) for d in target_dirs if os.path.exists(os.path.join(repo_path, d))]

    temp_dir = tempfile.mkdtemp(prefix="os_agent_doxy_")
    try:
        doxyfile_path = generate_doxyfile(repo_path, temp_dir, target_files=input_paths)
        
        # 运行 Doxygen
        result = subprocess.run(
            ["doxygen", doxyfile_path],
            cwd=temp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60 # Doxygen 非常快，特别是我们关闭了预处理和 HTML
        )
        
        if result.returncode != 0:
            logger.warning(f"Doxygen 运行失败: {result.stderr}")
            return ""
            
        # 寻找包含 entry_function 的 .dot 文件
        html_dir = os.path.join(temp_dir, "html")
        if not os.path.exists(html_dir):
            return ""
            
        target_dot_file = None
        for filename in os.listdir(html_dir):
            if filename.endswith(".dot") and "cgraph" in filename:
                # Doxygen dot file names are hashed, we need to grep inside or guess.
                # Since we don't know the exact hash, let's just find the dot file that 
                # contains the entry_function as a label.
                file_path = os.path.join(html_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        if f'label="{entry_function}"' in f.read() or f'label="{entry_function}\\n' in f.read():
                            target_dot_file = file_path
                            break
                except Exception:
                    continue

        if not target_dot_file:
            logger.info(f"Doxygen 跑完，未找到匹配入口 '{entry_function}' 的调用图 dot 文件。")
            return ""
            
        return parse_dot_to_mermaid(target_dot_file, entry_function, max_depth)
        
    except subprocess.TimeoutExpired:
        logger.warning("Doxygen 执行超时")
        return ""
    except Exception as e:
        logger.error(f"Fallback CallGraph 生成期间遭遇错误: {e}")
        return ""
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

