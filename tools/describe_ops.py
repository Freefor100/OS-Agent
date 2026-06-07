"""
Describe 相关工具：列出仓库结构、写文件、MD 转 PDF 等。
"""
import os
import glob
import re
import threading
from typing import List, Optional

from langchain.tools import tool


_path_lock_guard = threading.Lock()
_path_locks = {}


def _get_path_lock(path: str):
    key = os.path.abspath(path)
    with _path_lock_guard:
        if key not in _path_locks:
            _path_locks[key] = threading.RLock()
        return _path_locks[key]


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

    # 统计信息
    stats = {"dirs": 0, "files": 0, "truncated_dirs": 0}
    
    def _tree(d: str, prefix: str, depth: int) -> List[str]:
        if depth <= 0:
            # 检查是否还有子目录被截断
            try:
                subdirs = [n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)) and n not in exclude]
                if subdirs:
                    stats["truncated_dirs"] += len(subdirs)
            except OSError:
                pass
            return []
        lines = []
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return []
        dirs = [n for n in names if os.path.isdir(os.path.join(d, n)) and n not in exclude]
        files = [n for n in names if os.path.isfile(os.path.join(d, n))]
        
        stats["dirs"] += len(dirs)
        stats["files"] += len(files)
        
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
    
    # 添加统计信息和截断提示
    out.append(f"\n📊 统计: {stats['dirs']} 个目录, {stats['files']} 个文件 (深度限制: {max_depth} 层)")
    if stats["truncated_dirs"] > 0:
        out.append(f"⚠️ [深度截断] 还有约 {stats['truncated_dirs']} 个子目录未展开。如需查看更深层级，请增加 max_depth 参数。")
    
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
        with _get_path_lock(path):
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

    try:
        with _get_path_lock(pdf_path):
            os.makedirs(os.path.dirname(pdf_path) or ".", exist_ok=True)
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
    通过目录名、文件名识别关键模块。
    
    注意：此工具通过关键词匹配识别模块，可能遗漏非标准命名的模块。
    建议结合 list_repo_structure 手动检查未识别的目录。

    Args:
        repo_path: 本地仓库路径

    Returns:
        核心模块列表 + 未识别的顶层目录（供手动检查）
    """
    if not os.path.isdir(repo_path):
        return f"Error: Path not found: {repo_path}"

    # OS 核心模块关键词映射（扩展版：包含拼音、缩写、变体）
    module_keywords = {
        "进程管理": [
            "process", "task", "scheduler", "thread", "proc", "pid", "sched",
            "jincheng", "renwu", "diaodu",  # 拼音
            "pcb", "tcb", "context",  # 缩写/术语
        ],
        "内存管理": [
            "mm", "memory", "alloc", "page", "heap", "vm", "vmm", "pmm",
            "neicun", "fenye", "duizhan",  # 拼音
            "frame", "paging", "mmap", "buddy", "slab",  # 术语
        ],
        "文件系统": [
            "fs", "filesystem", "vfs", "ext", "fat", "procfs", "devfs", "tmpfs",
            "wenjian", "file",  # 拼音/英文
            "inode", "dentry", "super", "rootfs",  # 术语
        ],
        "网络": [
            "net", "network", "tcp", "udp", "socket", "ip", "ethernet",
            "wangluo", "sock",  # 拼音/缩写
            "nic", "arp", "icmp", "dhcp",  # 协议
        ],
        "设备驱动": [
            "driver", "device", "dev", "pci", "usb", "block", "char",
            "qudong", "shebei",  # 拼音
            "uart", "gpio", "i2c", "spi", "dma", "mmio",  # 硬件接口
        ],
        "系统调用": [
            "syscall", "sys", "api", "uapi",
            "xitong", "diaoyon",  # 拼音
            "svc", "ecall", "trap_handler",  # 架构相关
        ],
        "中断处理": [
            "irq", "interrupt", "exception", "trap", "handler",
            "zhongduan", "yichang",  # 拼音
            "idt", "gdt", "isr", "vector", "plic", "clint",  # 术语
        ],
        "同步原语": [
            "sync", "mutex", "lock", "semaphore", "spinlock", "rwlock",
            "tongbu", "suo",  # 拼音
            "condvar", "barrier", "atomic", "futex",  # 术语
        ],
        "启动/初始化": [
            "boot", "init", "entry", "startup", "loader",
            "qidong", "chushi",  # 拼音
            "bootloader", "bios", "uefi", "main", "start",  # 术语
        ],
        "内核核心": [
            "kernel", "core", "arch", "platform", "hal",
            "neihe",  # 拼音
            # 国际架构
            "cpu", "riscv", "x86", "x86_64", "arm", "arm64", "aarch64", "mips",
            # 国产架构
            "loongarch", "longarch", "la64", "la32",  # 龙芯
            "sunway", "sw64", "sw_64", "shenwei",  # 申威
            "phytium", "ft2000", "ft2500", "feiteng",  # 飞腾
            "kunpeng", "hisilicon", "kunpeng920", "kunpeng930",  # 鲲鹏/华为
            "hygon", "haiguang", "dhyana",  # 海光
            "zhaoxin", "centaur",  # 兆芯
            "c910", "c906", "thead", "xuantie",  # 平头哥玄铁
        ],
        "用户空间": [
            "user", "ulib", "libc", "userspace", "app",
            "yonghu", "yingyong",  # 拼音
            "shell", "init", "bin",  # 术语
        ],
    }

    found_modules = {}
    all_matched_paths = set()
    top_level_dirs = []
    exclude = {"vendor", ".git", ".github", "target", "node_modules", ".devcontainer", "__pycache__"}

    def _scan_dir(d: str, depth: int = 0, max_depth: int = 3):
        if depth > max_depth:
            return
        try:
            items = os.listdir(d)
        except OSError:
            return

        for item in items:
            if item in exclude or item.startswith("."):
                continue
            item_path = os.path.join(d, item)
            rel_path = os.path.relpath(item_path, repo_path).replace("\\", "/")

            # 记录顶层目录
            if depth == 0 and os.path.isdir(item_path):
                top_level_dirs.append(rel_path)

            # 检查目录名和文件名
            item_lower = item.lower()
            matched = False
            for mod_type, keywords in module_keywords.items():
                for kw in keywords:
                    if kw in item_lower:
                        if mod_type not in found_modules:
                            found_modules[mod_type] = []
                        found_modules[mod_type].append(rel_path)
                        all_matched_paths.add(rel_path)
                        matched = True
                        break
                if matched:
                    break

            # 递归扫描目录
            if os.path.isdir(item_path):
                _scan_dir(item_path, depth + 1, max_depth)

    _scan_dir(repo_path)

    lines = []
    
    if found_modules:
        lines.append("## 🔍 识别到的 OS 核心模块\n")
        for mod_type in sorted(found_modules.keys()):
            paths = sorted(set(found_modules[mod_type]))[:10]
            lines.append(f"\n### {mod_type}")
            for p in paths:
                lines.append(f"  - {p}")
            if len(found_modules[mod_type]) > 10:
                lines.append(f"  ... 还有 {len(found_modules[mod_type]) - 10} 个相关路径")
    else:
        lines.append("## ⚠️ 未找到明显的 OS 核心模块")
        lines.append("可能原因：命名不标准、使用拼音/编号、或项目结构特殊")

    # 找出未匹配的顶层目录
    unmatched_dirs = [d for d in top_level_dirs if d not in all_matched_paths]
    if unmatched_dirs:
        lines.append(f"\n## ❓ 未识别的顶层目录（共 {len(unmatched_dirs)} 个）")
        lines.append("以下目录未被自动识别，可能包含重要模块，建议手动检查：")
        for d in sorted(unmatched_dirs)[:15]:
            lines.append(f"  - {d}/")
        if len(unmatched_dirs) > 15:
            lines.append(f"  ... 还有 {len(unmatched_dirs) - 15} 个")
        lines.append("\n💡 提示：使用 `lsp_get_document_outline` 查看文件结构，`lsp_get_definition` 定位符号，或 `read_code_segment` 读取具体内容")

    # 统计信息
    lines.append(f"\n📊 统计: 识别了 {len(found_modules)} 个模块类型，匹配了 {len(all_matched_paths)} 个路径")

    return "\n".join(lines)

