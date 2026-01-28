"""
Describe 相关工具：列出仓库结构、写文件、MD 转 PDF 等。
"""
import os
import glob
import re
from typing import List, Optional

from langchain.tools import tool


@tool
def list_repo_structure(repo_path: str, exclude_vendor: bool = True, max_depth: int = 4) -> str:
    """
    列出仓库的目录与关键文件结构，用于了解项目布局、定位 README / 文档等。
    默认排除 vendor、.git 等无关目录。
    显示每个文件的行数和大小，帮助判断文件重要性。

    Args:
        repo_path: 本地仓库根路径（如 repos/RepoName）
        exclude_vendor: 是否排除 vendor、.git、.github、target 等
        max_depth: 最多展示的目录层级，默认 4

    Returns:
        树形文本结构（含文件行数/大小）+ 根目录下的 README / 文档列表
    """
    exclude = {"vendor", ".git", ".github", "target", "node_modules", ".devcontainer"}
    if not exclude_vendor:
        exclude = set()

    def _get_file_info(fpath: str) -> str:
        """获取文件的行数和大小信息"""
        try:
            size = os.path.getsize(fpath)
            if size > 1024 * 1024:
                size_str = f"{size / (1024*1024):.1f}MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f}KB"
            else:
                size_str = f"{size}B"
            
            # 只对代码文件统计行数
            code_exts = {".rs", ".c", ".cpp", ".h", ".hpp", ".py", ".js", ".ts", ".go", ".md", ".toml", ".s", ".S", ".asm"}
            if any(fpath.lower().endswith(ext) for ext in code_exts):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        line_count = sum(1 for _ in f)
                    return f" ({line_count}L, {size_str})"
                except Exception:
                    pass
            return f" ({size_str})"
        except Exception:
            return ""

    def _tree(d: str, prefix: str, depth: int) -> List[str]:
        if depth <= 0:
            return []
        lines = []
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return []
        dirs = [n for n in names if os.path.isdir(os.path.join(d, n)) and n not in exclude]
        files = [n for n in names if os.path.isfile(os.path.join(d, n))]
        for i, n in enumerate(dirs):
            last = (i == len(dirs) - 1) and not files
            add = "└── " if last else "├── "
            lines.append(prefix + add + n + "/")
            sub = _tree(os.path.join(d, n), prefix + ("    " if last else "│   "), depth - 1)
            lines.extend(sub)
        for i, n in enumerate(files):
            last = i == len(files) - 1
            add = "└── " if last else "├── "
            fpath = os.path.join(d, n)
            file_info = _get_file_info(fpath)
            lines.append(prefix + add + n + file_info)
        return lines

    if not os.path.isdir(repo_path):
        return f"Error: Path not found: {repo_path}"

    root_name = os.path.basename(os.path.normpath(repo_path))
    out = [f"{root_name}/"]
    out.extend(_tree(repo_path, "", max_depth))

    # 根目录下的文档
    doc_patterns = ["README*", "readme*", "*.md", "*.MD", "*.pdf", "*.PDF", "docs"]
    docs = []
    for pat in doc_patterns:
        if pat == "docs":
            p = os.path.join(repo_path, "docs")
            if os.path.isdir(p):
                docs.append("docs/")
            continue
        for p in glob.glob(os.path.join(repo_path, pat)):
            if os.path.isfile(p):
                docs.append(os.path.basename(p))
    if docs:
        out.append("\n根目录文档: " + ", ".join(sorted(set(docs))))
    return "\n".join(out)


@tool
def write_file(file_path: str, content: str) -> str:
    """
    将字符串内容写入指定文件。若父目录不存在则创建。
    用于保存 Agent 生成的 Markdown 描述等。

    Args:
        file_path: 目标文件路径（相对或绝对）
        content: 要写入的完整内容

    Returns:
        成功则返回写入的绝对路径；失败返回错误信息
    """
    try:
        path = os.path.normpath(file_path)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written: {os.path.abspath(path)}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


@tool
def convert_md_to_pdf(md_path: str, pdf_path: Optional[str] = None) -> str:
    """
    将 Markdown 文件转换为 PDF。若未提供 pdf_path，则输出到同目录同名的 .pdf。

    Args:
        md_path: Markdown 文件路径
        pdf_path: 可选，输出 PDF 路径

    Returns:
        成功则返回生成的 PDF 绝对路径；失败返回错误信息
    """
    try:
        import markdown
        import weasyprint
        from weasyprint import HTML
    except ImportError as e:
        return f"Error: missing dependency. pip install markdown weasyprint. {e}"

    if not os.path.isfile(md_path):
        return f"Error: File not found: {md_path}"

    if pdf_path is None:
        base = os.path.splitext(md_path)[0]
        pdf_path = base + ".pdf"
    pdf_path = os.path.normpath(pdf_path)
    os.makedirs(os.path.dirname(pdf_path) or ".", exist_ok=True)

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()
        exts = ["extra", "tables", "toc"]
        try:
            import pygments  # noqa: F401
            exts.append("codehilite")
        except ImportError:
            pass
        kwargs = {"extensions": exts}
        if "codehilite" in exts:
            kwargs["extension_configs"] = {"codehilite": {"css_class": "highlight"}}
        html_text = markdown.markdown(md_text, **kwargs)
        html_full = (
            f'<!DOCTYPE html><html><head><meta charset="utf-8"/>'
            f'<style>body {{ font-family: "SimSun", "Microsoft YaHei", sans-serif; '
            f'margin: 1.5em; line-height: 1.5; }} '
            f'pre {{ background: #f5f5f5; padding: 0.8em; overflow-x: auto; }} '
            f'img {{ max-width: 100%; }} '
            f'table {{ border-collapse: collapse; }} '
            f'th, td {{ border: 1px solid #ccc; padding: 4px 8px; }}</style></head><body>'
            f"{html_text}</body></html>"
        )
        HTML(string=html_full).write_pdf(pdf_path)
        return f"PDF saved: {os.path.abspath(pdf_path)}"
    except Exception as e:
        return f"Error converting to PDF: {str(e)}"


@tool
def find_os_core_modules(repo_path: str) -> str:
    """
    查找并分析 OS 核心模块（进程管理、内存管理、文件系统、网络、设备驱动等）。
    通过目录名、文件名、代码内容识别关键模块。

    Args:
        repo_path: 本地仓库路径

    Returns:
        核心模块列表，每个模块包含：模块名、路径、功能描述（基于目录/文件名推断）
    """
    if not os.path.isdir(repo_path):
        return f"Error: Path not found: {repo_path}"

    # OS 核心模块关键词映射
    module_keywords = {
        "进程管理": ["process", "task", "scheduler", "thread", "proc", "pid"],
        "内存管理": ["mm", "memory", "alloc", "page", "heap", "vm"],
        "文件系统": ["fs", "filesystem", "vfs", "ext", "fat", "procfs", "devfs", "tmpfs"],
        "网络": ["net", "network", "tcp", "udp", "socket", "ip", "ethernet"],
        "设备驱动": ["driver", "device", "dev", "pci", "usb", "block"],
        "系统调用": ["syscall", "sys", "api"],
        "中断处理": ["irq", "interrupt", "exception", "trap"],
        "同步原语": ["sync", "mutex", "lock", "semaphore", "spinlock"],
        "启动/初始化": ["boot", "init", "entry", "startup"],
    }

    found_modules = {}
    exclude = {"vendor", ".git", ".github", "target", "node_modules", ".devcontainer"}

    def _scan_dir(d: str, depth: int = 0, max_depth: int = 3):
        if depth > max_depth:
            return
        try:
            items = os.listdir(d)
        except OSError:
            return

        for item in items:
            if item in exclude:
                continue
            item_path = os.path.join(d, item)
            rel_path = os.path.relpath(item_path, repo_path).replace("\\", "/")

            # 检查目录名和文件名
            item_lower = item.lower()
            for mod_type, keywords in module_keywords.items():
                for kw in keywords:
                    if kw in item_lower:
                        if mod_type not in found_modules:
                            found_modules[mod_type] = []
                        found_modules[mod_type].append(rel_path)
                        break

            # 递归扫描目录
            if os.path.isdir(item_path):
                _scan_dir(item_path, depth + 1, max_depth)

    _scan_dir(repo_path)

    if not found_modules:
        return "未找到明显的 OS 核心模块（可能命名不标准）"

    lines = ["发现的 OS 核心模块：\n"]
    for mod_type in sorted(found_modules.keys()):
        paths = sorted(set(found_modules[mod_type]))[:10]  # 每个模块最多显示10个路径
        lines.append(f"\n## {mod_type}")
        for p in paths:
            lines.append(f"  - {p}")
        if len(found_modules[mod_type]) > 10:
            lines.append(f"  ... 还有 {len(found_modules[mod_type]) - 10} 个相关路径")

    return "\n".join(lines)


@tool
def analyze_code_architecture(repo_path: str, module_path: str) -> str:
    """
    分析指定模块的代码架构：主要函数、数据结构、依赖关系、设计模式等。
    通过解析代码文件（.rs, .c, .h, .cpp, .hpp）提取关键信息。

    Args:
        repo_path: 仓库根路径
        module_path: 要分析的模块路径（相对 repo_path）

    Returns:
        架构分析结果：主要结构体/类、关键函数、依赖关系
    """
    full_path = os.path.normpath(os.path.join(repo_path, module_path))
    if not os.path.exists(full_path):
        return f"Error: Path not found: {full_path}"

    results = []
    code_exts = {".rs", ".c", ".cpp", ".h", ".hpp", ".cc", ".cxx"}

    def _analyze_file(fpath: str):
        if not any(fpath.lower().endswith(ext) for ext in code_exts):
            return None

        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return None

        info = {"file": os.path.relpath(fpath, repo_path).replace("\\", "/"), "structs": [], "functions": [], "imports": []}

        # Rust: 提取 struct, enum, impl, fn
        if fpath.endswith(".rs"):
            structs = re.findall(r"(?:pub\s+)?(?:struct|enum)\s+(\w+)", content)
            functions = re.findall(r"(?:pub\s+)?fn\s+(\w+)", content)
            imports = re.findall(r"use\s+([^;]+)", content)
            info["structs"] = list(set(structs))[:15]
            info["functions"] = list(set(functions))[:20]
            info["imports"] = list(set(imports))[:15]

        # C/C++: 提取 struct, typedef, function
        elif fpath.endswith((".c", ".cpp", ".h", ".hpp")):
            structs = re.findall(r"(?:struct|typedef\s+struct)\s+(\w+)", content)
            functions = re.findall(r"(?:\w+\s+)*(\w+)\s*\([^)]*\)\s*\{", content)
            info["structs"] = list(set(structs))[:15]
            info["functions"] = list(set(functions))[:20]

        if info["structs"] or info["functions"]:
            return info
        return None

    if os.path.isfile(full_path):
        files_to_analyze = [full_path]
    elif os.path.isdir(full_path):
        files_to_analyze = []
        for root, dirs, filenames in os.walk(full_path):
            dirs[:] = [d for d in dirs if d not in {"vendor", ".git", "target"}]
            for fn in filenames:
                if any(fn.lower().endswith(ext) for ext in code_exts):
                    files_to_analyze.append(os.path.join(root, fn))
                    if len(files_to_analyze) >= 20:  # 限制分析文件数
                        break
            if len(files_to_analyze) >= 20:
                break
    else:
        return f"Error: {module_path} is neither file nor directory"

    for fpath in files_to_analyze[:10]:  # 最多分析10个文件
        info = _analyze_file(fpath)
        if info:
            results.append(info)

    if not results:
        return f"未在 {module_path} 中找到可分析的代码结构"

    lines = [f"代码架构分析：{module_path}\n"]
    for r in results:
        lines.append(f"\n### {r['file']}")
        if r["structs"]:
            lines.append(f"  结构体/枚举: {', '.join(r['structs'][:10])}")
        if r["functions"]:
            lines.append(f"  关键函数: {', '.join(r['functions'][:10])}")
        if r.get("imports"):
            lines.append(f"  主要依赖: {', '.join(r['imports'][:5])}")

    return "\n".join(lines)


@tool
def analyze_tech_stack(repo_path: str) -> str:
    """
    分析项目的技术栈：编程语言、框架、库、构建工具、依赖等。
    通过分析 Cargo.toml、Makefile、CMakeLists.txt、package.json 等配置文件。

    Args:
        repo_path: 仓库根路径

    Returns:
        技术栈分析结果
    """
    if not os.path.isdir(repo_path):
        return f"Error: Path not found: {repo_path}"

    tech_info = {
        "languages": set(),
        "build_tools": [],
        "dependencies": [],
        "config_files": [],
    }

    # 检查配置文件
    config_patterns = {
        "Cargo.toml": ("Rust", "cargo"),
        "Makefile": ("Make", "make"),
        "CMakeLists.txt": ("CMake", "cmake"),
        "package.json": ("Node.js", "npm"),
        "go.mod": ("Go", "go"),
        "requirements.txt": ("Python", "pip"),
    }

    for config_file, (lang, tool) in config_patterns.items():
        config_path = os.path.join(repo_path, config_file)
        if os.path.isfile(config_path):
            tech_info["config_files"].append(config_file)
            tech_info["languages"].add(lang)
            tech_info["build_tools"].append(tool)

            # 读取 Cargo.toml 获取依赖
            if config_file == "Cargo.toml":
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        deps = re.findall(r'(\w+)\s*=\s*["\']([^"\']+)["\']', content)
                        tech_info["dependencies"].extend([f"{name} ({ver})" for name, ver in deps[:20]])
                except Exception:
                    pass

    # 通过文件扩展名推断语言
    code_exts = {
        ".rs": "Rust",
        ".c": "C",
        ".cpp": "C++",
        ".h": "C/C++",
        ".hpp": "C++",
        ".py": "Python",
        ".go": "Go",
        ".js": "JavaScript",
        ".ts": "TypeScript",
    }

    ext_counts = {}
    for root, dirs, filenames in os.walk(repo_path):
        if "vendor" in root or ".git" in root:
            continue
        for fn in filenames:
            for ext, lang in code_exts.items():
                if fn.lower().endswith(ext):
                    ext_counts[lang] = ext_counts.get(lang, 0) + 1
                    tech_info["languages"].add(lang)
                    break

    lines = ["技术栈分析：\n"]
    if tech_info["languages"]:
        lines.append(f"\n编程语言: {', '.join(sorted(tech_info['languages']))}")
    if tech_info["build_tools"]:
        lines.append(f"\n构建工具: {', '.join(set(tech_info['build_tools']))}")
    if tech_info["config_files"]:
        lines.append(f"\n配置文件: {', '.join(tech_info['config_files'])}")
    if tech_info["dependencies"]:
        lines.append(f"\n主要依赖（前20个）:")
        for dep in tech_info["dependencies"][:20]:
            lines.append(f"  - {dep}")
    if ext_counts:
        lines.append(f"\n代码文件统计:")
        for lang, count in sorted(ext_counts.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  {lang}: {count} 个文件")

    return "\n".join(lines) if lines else "未检测到明显的技术栈信息"
