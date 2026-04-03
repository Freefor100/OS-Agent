"""
tools/callgraph_overview.py

全OS函数级 + 文件级 Call Graph 构建与分类模块。

流程：
  1. Tree-sitter 枚举全部函数 → 节点
  2. Tree-sitter 提取 outgoing calls → 边（单文件内）
  3. 构建 NetworkX DiGraph
  4. PageRank 排出枢纽函数 Top-k
  5. LSP 精化 Top-k 节点的跨文件边
  6. 路径规则 + LLM 批量分类 domain × layer
  7. 聚合文件级 Call Graph
  8. 输出 SVG（domain列 × layer行 + 连线）+ Markdown 表格

domain（9类）: arch_platform / trap_syscall / process_sched / memory_vm /
               fs_storage / sync_ipc / runtime_common / user_programs / unknown
layer（5类）:  userspace / syscall_boundary / kernel / hardware / unknown
"""

from __future__ import annotations

import os
import re
import json
import base64
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DOMAINS = [
    "arch_platform", "trap_syscall", "process_sched", "memory_vm",
    "fs_storage", "sync_ipc", "runtime_common", "user_programs", "unknown",
]

LAYERS = ["userspace", "syscall_boundary", "kernel", "hardware", "unknown"]


_PATH_DOMAIN_RULES: List[Tuple[str, str]] = [
    (r"(arch|platform|boot|entry|start|trampoline|linker|asm|assembly)", "arch_platform"),
    (r"(trap|syscall|interrupt|irq|exception|ecall|stvec)",              "trap_syscall"),
    (r"(proc|sched|task|thread|pcb|tcb|fork|exec)",                      "process_sched"),
    (r"(mm|memory|mem|vm|page|buddy|alloc|heap|vma|pagefault|mmap)",     "memory_vm"),
    (r"(fs|vfs|fat|ext|inode|file|block|bio|buffer|storage)",            "fs_storage"),
    (r"(sync|lock|mutex|spin|semaphore|futex|ipc|pipe|signal|shm)",      "sync_ipc"),
    (r"(user|usr|bin|app|shell|test)",                                   "user_programs"),
    (r"(util|common|lib|string|print|log|debug|error|panic)",            "runtime_common"),
]

_PATH_LAYER_RULES: List[Tuple[str, str]] = [
    (r"(user|usr|bin|app|shell)",               "userspace"),
    (r"(syscall|ecall|svc|sys_)",               "syscall_boundary"),
    (r"(driver|device|uart|virtio|plic|clint|mmio|hardware|hw)", "hardware"),
]

_CODE_EXTS = {".c", ".cc", ".cpp", ".rs", ".go", ".zig"}

_KEYWORD_SKIP = {
    "if", "for", "while", "match", "return", "let", "fn", "use", "pub", "mod",
    "unsafe", "impl", "trait", "struct", "enum", "type", "const", "static",
    "super", "self", "Self", "loop", "continue", "break", "println", "format",
    "assert", "panic", "todo", "unimplemented", "dbg", "write", "writeln",
    "sizeof", "typeof", "alignof", "NULL", "true", "false",
}

_DOMAIN_COLOR = {
    "arch_platform":  "#f4d03f",
    "trap_syscall":   "#e74c3c",
    "process_sched":  "#3498db",
    "memory_vm":      "#2ecc71",
    "fs_storage":     "#9b59b6",
    "sync_ipc":       "#e67e22",
    "runtime_common": "#95a5a6",
    "user_programs":  "#1abc9c",
    "unknown":        "#bdc3c7",
}



# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _abspath(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))

def _rel(path: str, base: str) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path

def _lang_for_ext(ext: str) -> Optional[str]:
    return {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
            ".rs": "rust", ".go": "go", ".zig": "zig"}.get(ext)

def _skip_dirs() -> Set[str]:
    return {".git", "target", "node_modules", ".os_agent_ra_target",
            "vendor", "build", "dist", ".github"}

def _safe_xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# Tree-sitter 加载
# ---------------------------------------------------------------------------

class _TSLoader:
    _langs: Optional[Dict] = None
    _Parser = None

    @classmethod
    def load(cls) -> bool:
        if cls._langs is not None:
            return bool(cls._langs)
        cls._langs = {}
        try:
            from tree_sitter import Language, Parser
            cls._Parser = Parser
            for name, mod in [("c", "tree_sitter_c"), ("cpp", "tree_sitter_cpp"),
                               ("rust", "tree_sitter_rust"), ("go", "tree_sitter_go"),
                               ("zig", "tree_sitter_zig")]:
                try:
                    imp = __import__(mod)
                    cls._langs[name] = Language(getattr(imp, "language")())
                except ImportError:
                    pass
        except ImportError:
            pass
        return bool(cls._langs)

    @classmethod
    def parser(cls, lang: str):
        if not cls._langs or lang not in cls._langs:
            return None
        p = cls._Parser()
        p.language = cls._langs[lang]
        return p


_FN_NODE_TYPES = {
    "c": {"function_definition"}, "cpp": {"function_definition"},
    "rust": {"function_item"}, "go": {"function_declaration", "method_declaration"},
    "zig": {"function_declaration"},
}
_CALL_NODE_TYPES = {
    "c": {"call_expression"}, "cpp": {"call_expression"},
    "rust": {"call_expression", "method_call_expression"},
    "go": {"call_expression"}, "zig": {"call_expression"},
}


def _extract_fn_name(node, code_bytes: bytes, lang: str) -> Optional[str]:
    if lang in ("c", "cpp"):
        for child in node.children:
            if child.type == "function_declarator":
                for sc in child.children:
                    if sc.type == "identifier":
                        return code_bytes[sc.start_byte:sc.end_byte].decode("utf-8", errors="ignore")
    elif lang in ("rust", "go", "zig"):
        for child in node.children:
            if child.type == "identifier":
                return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
    return None


def _extract_call_name(node, code_bytes: bytes) -> Optional[str]:
    if not node.children:
        return None
    fn_node = node.children[0]
    if fn_node.type == "identifier" and fn_node.child_count == 0:
        return code_bytes[fn_node.start_byte:fn_node.end_byte].decode("utf-8", errors="ignore")
    # field/scoped expr: 取最后一个 identifier
    for child in reversed(fn_node.children):
        if child.type == "identifier" and child.child_count == 0:
            return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
    return None


def _parse_file(abs_path: str, rel_path: str, lang: str) -> Tuple[List[dict], List[Tuple[str, str]]]:
    parser = _TSLoader.parser(lang)
    if parser is None:
        return [], []
    try:
        with open(abs_path, "rb") as f:
            code_bytes = f.read()
        tree = parser.parse(code_bytes)
    except Exception:
        return [], []

    fn_types = _FN_NODE_TYPES.get(lang, set())
    call_types = _CALL_NODE_TYPES.get(lang, set())
    functions, edges = [], []

    def _collect_calls(fn_node, caller: str):
        def _walk(n):
            if n.type in call_types:
                callee = _extract_call_name(n, code_bytes)
                if callee and callee not in _KEYWORD_SKIP and callee[0].islower():
                    edges.append((caller, callee))
            for ch in n.children:
                _walk(ch)
        _walk(fn_node)

    def _traverse(node):
        if node.type in fn_types:
            name = _extract_fn_name(node, code_bytes, lang)
            if name and name not in _KEYWORD_SKIP:
                functions.append({"name": name, "file": rel_path,
                                  "line": node.start_point[0] + 1, "lang": lang})
                _collect_calls(node, name)
            return
        for ch in node.children:
            _traverse(ch)

    _traverse(tree.root_node)
    return functions, edges


# ---------------------------------------------------------------------------
# Step 1-3: 构建 NetworkX DiGraph
# ---------------------------------------------------------------------------

def build_digraph(repo_path: str) -> Tuple[nx.DiGraph, Dict[str, dict]]:
    """
    遍历全库，构建函数调用有向图。

    返回：
      G:         nx.DiGraph，节点属性包含 file/line/lang
      fn_meta:   {fn_name: {file, line, lang}}
    """
    if not _TSLoader.load():
        logger.warning("[CallGraph] Tree-sitter 未加载")
        return nx.DiGraph(), {}

    abs_repo = _abspath(repo_path)
    G = nx.DiGraph()
    fn_meta: Dict[str, dict] = {}

    total_files = 0
    for dirpath, dirs, files in os.walk(abs_repo):
        dirs[:] = [d for d in dirs if d not in _skip_dirs()]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            lang = _lang_for_ext(ext)
            if lang is None or ext not in _CODE_EXTS:
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = _rel(abs_path, abs_repo)

            fns, file_edges = _parse_file(abs_path, rel_path, lang)
            total_files += 1

            for fn in fns:
                name = fn["name"]
                if name not in fn_meta:
                    fn_meta[name] = {"file": fn["file"], "line": fn["line"], "lang": fn["lang"]}
                    G.add_node(name, **fn_meta[name])

            for caller, callee in file_edges:
                if caller in fn_meta:
                    G.add_edge(caller, callee)

    logger.info(f"[CallGraph] 扫描 {total_files} 文件 → {G.number_of_nodes()} 节点, {G.number_of_edges()} 边")
    return G, fn_meta


# ---------------------------------------------------------------------------
# Step 4: PageRank 选 Top-k
# ---------------------------------------------------------------------------

def select_top_k_pagerank(G: nx.DiGraph, k: int = 30) -> List[str]:
    """
    用 PageRank 选出架构上最重要的 Top-k 函数节点。
    PageRank 考虑"被重要函数调用"比"被普通函数调用"权重更高。
    """
    if G.number_of_nodes() == 0:
        return []
    try:
        pr = nx.pagerank(G, alpha=0.85, max_iter=200)
    except nx.PowerIterationFailedConvergence:
        # 收敛失败时退化为度数排序
        pr = {n: G.in_degree(n) + G.out_degree(n) for n in G.nodes()}

    ranked = sorted(pr.items(), key=lambda x: x[1], reverse=True)
    return [fn for fn, _ in ranked[:k]]


# ---------------------------------------------------------------------------
# Step 5: LSP 精化 Top-k 跨文件边
# ---------------------------------------------------------------------------

def refine_with_lsp(G: nx.DiGraph, fn_meta: Dict[str, dict],
                    repo_path: str, top_k_nodes: List[str], limit: int = 30):
    """用 LSP callHierarchy 补充 Top-k 节点的跨文件边（in-place 修改 G）"""
    try:
        from tools.lsp_ops import lsp_get_call_graph
    except ImportError:
        return

    refined = 0
    for fn in top_k_nodes[:limit]:
        info = fn_meta.get(fn, {})
        file_path = info.get("file", "")
        if not file_path:
            continue
        try:
            result = lsp_get_call_graph(repo_path, file_path, fn, "both", max_depth=2)
            if not result or "DEGRADED" in result:
                continue
            for line in result.splitlines():
                m = re.search(r"[├└─] +(\w+)\(\)", line)
                if m:
                    callee = m.group(1)
                    if callee not in _KEYWORD_SKIP and callee != fn:
                        if callee not in G:
                            G.add_node(callee)
                        G.add_edge(fn, callee)
            refined += 1
        except Exception:
            pass

    logger.info(f"[CallGraph] LSP 精化了 {refined} 个节点")


# ---------------------------------------------------------------------------
# Step 6: 关键调用路径（BFS）
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Step 7: 分类 domain × layer
# ---------------------------------------------------------------------------

def _path_domain(rel_path: str) -> Optional[str]:
    lower = rel_path.lower().replace("\\", "/")
    for pat, domain in _PATH_DOMAIN_RULES:
        if re.search(pat, lower):
            return domain
    return None

def _path_layer(rel_path: str, fn_name: str) -> Optional[str]:
    if re.search(r"\bsys_", fn_name):
        return "syscall_boundary"
    lower = (rel_path + " " + fn_name).lower()
    for pat, layer in _PATH_LAYER_RULES:
        if re.search(pat, lower):
            return layer
    return None


def _read_fn_snippet(abs_path: str, start_line: int, max_lines: int = 20) -> str:
    """读取函数体前 max_lines 行作为代码片段（用于给 LLM 更多上下文）。"""
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if start_line < 1:
            return ""
        snippet = lines[start_line - 1 : start_line - 1 + max_lines]
        return "".join(snippet).strip()
    except Exception:
        return ""


def _llm_classify_batch(nodes: List[dict]) -> Dict[str, dict]:
    """
    用 LLM 批量分类 domain × layer。
    nodes: [{"fn_name": ..., "file_path": ..., "code_snippet": ...}, ...]
    返回: {fn_name: {"domain": ..., "layer": ...}}
    """
    if not nodes:
        return {}

    domain_desc = (
        "arch_platform: 启动汇编、平台初始化、硬件驱动（uart/virtio/plic/timer等）\n"
        "trap_syscall: 中断异常向量、系统调用入口分发（trap_handler/uservec等）\n"
        "process_sched: 进程创建/调度/上下文切换（fork/exec/schedule等）\n"
        "memory_vm: 内存分配、页表、虚拟内存、缺页处理\n"
        "fs_storage: 文件系统、磁盘I/O、inode/dentry\n"
        "sync_ipc: 锁、信号量、管道、消息、进程间通信\n"
        "runtime_common: 通用库函数（string/copy/print等）\n"
        "user_programs: 用户态程序、用户态库\n"
        "unknown: 无法确定"
    )
    layer_desc = (
        "userspace: 运行在用户态的代码\n"
        "syscall_boundary: sys_开头的系统调用入口函数\n"
        "kernel: 内核态通用逻辑\n"
        "hardware: 直接操作硬件寄存器/设备的驱动代码\n"
        "unknown: 无法确定"
    )

    # 格式化节点信息，包含代码片段
    nodes_text = ""
    for n in nodes:
        nodes_text += f"\n### {n['fn_name']}\n文件: {n['file_path']}\n"
        if n.get("code_snippet"):
            nodes_text += f"```c\n{n['code_snippet']}\n```\n"

    prompt = (
        "你是操作系统内核专家。根据函数名、文件路径和代码片段，对每个函数按 domain 和 layer 分类，只输出 JSON。\n\n"
        f"domain（选一个）:\n{domain_desc}\n\n"
        f"layer（选一个）:\n{layer_desc}\n\n"
        f"函数列表:{nodes_text}\n"
        '输出格式（只输出JSON，不要markdown代码块）:\n'
        '{"fn_name": {"domain": "...", "layer": "..."}, ...}'
    )

    try:
        from core.agent_builder import build_chat_model
        from langchain_core.messages import HumanMessage
        llm = build_chat_model(temperature=0)
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = resp.content.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        logger.warning(f"[ClassifyNodes] LLM 批量分类失败: {e}")
        return {}


def classify_nodes(top_k: List[str], G: nx.DiGraph,
                   fn_meta: Dict[str, dict],
                   repo_path: str = "") -> Dict[str, dict]:
    """
    对 Top-k 节点分类 domain × layer。
    路径规则优先（~80% 覆盖），无法确定时批量调用 LLM（含函数体片段）。
    """
    result = {}
    unresolved = []  # 需要 LLM 兜底的节点

    for fn in top_k:
        info = fn_meta.get(fn, G.nodes.get(fn, {}))
        rel_path = info.get("file", "")

        domain = _path_domain(rel_path)
        layer  = _path_layer(rel_path, fn)

        result[fn] = {
            "domain":     domain,
            "layer":      layer,
            "file":       rel_path,
            "line":       info.get("line", 0),
            "in_degree":  G.in_degree(fn),
            "out_degree": G.out_degree(fn),
            "pagerank":   G.nodes[fn].get("pagerank", 0.0) if fn in G else 0.0,
            "method":     "path_rule" if (domain and layer) else "llm",
        }
        if domain is None or layer is None:
            # 读取函数体片段供 LLM 参考
            snippet = ""
            if repo_path and rel_path and info.get("line"):
                abs_path = os.path.join(repo_path, rel_path)
                snippet = _read_fn_snippet(abs_path, info["line"], max_lines=20)
            unresolved.append({
                "fn_name":      fn,
                "file_path":    rel_path,
                "code_snippet": snippet,
            })

    # LLM 批量补全未能用路径规则分类的节点
    if unresolved:
        llm_preds = _llm_classify_batch(unresolved)
        for item in unresolved:
            fn = item["fn_name"]
            pred = llm_preds.get(fn, {})
            if result[fn]["domain"] is None:
                result[fn]["domain"] = pred.get("domain", "unknown")
            if result[fn]["layer"] is None:
                result[fn]["layer"] = pred.get("layer", "kernel")

    # 最终 fallback
    for fn in top_k:
        result[fn]["domain"] = result[fn]["domain"] or "unknown"
        result[fn]["layer"]  = result[fn]["layer"]  or "kernel"

    return result


# ---------------------------------------------------------------------------
# Step 8: 文件级聚合
# ---------------------------------------------------------------------------

def build_file_graph(G: nx.DiGraph, top_k: List[str],
                     fn_meta: Dict[str, dict]) -> nx.DiGraph:
    """从函数级图聚合文件级有向图（只保留 Top-k 涉及的文件）"""
    top_set = set(top_k)
    FG = nx.DiGraph()
    for caller in top_k:
        cf = fn_meta.get(caller, {}).get("file", "")
        if not cf:
            continue
        FG.add_node(cf)
        for callee in G.successors(caller):
            ef = fn_meta.get(callee, {}).get("file", "")
            if ef and ef != cf:
                FG.add_node(ef)
                if not FG.has_edge(cf, ef):
                    FG.add_edge(cf, ef, weight=0)
                FG[cf][ef]["weight"] += 1
    return FG


# ---------------------------------------------------------------------------
# Step 9: SVG 渲染（domain列 × layer行 网格 + 连线）
# ---------------------------------------------------------------------------

_LAYER_ORDER  = ["userspace", "syscall_boundary", "kernel", "hardware", "unknown"]
_DOMAIN_ORDER = ["arch_platform", "trap_syscall", "process_sched", "memory_vm",
                 "fs_storage", "sync_ipc", "runtime_common", "user_programs", "unknown"]

# SVG 布局参数
_CELL_W  = 160   # 每列宽度
_CELL_H  = 110   # 每行高度
_NODE_W  = 140   # 节点矩形宽
_NODE_H  = 36    # 节点矩形高
_PAD_X   = 20    # 左边距（留给 layer 标签）
_PAD_Y   = 30    # 顶边距（留给 domain 标签）
_LABEL_W = 110   # 左侧 layer 标签列宽


def _grid_pos(domain: str, layer: str) -> Tuple[float, float]:
    """返回节点中心 (cx, cy)"""
    col = _DOMAIN_ORDER.index(domain) if domain in _DOMAIN_ORDER else len(_DOMAIN_ORDER) - 1
    row = _LAYER_ORDER.index(layer)   if layer  in _LAYER_ORDER  else len(_LAYER_ORDER)  - 1
    cx = _LABEL_W + _PAD_X + col * _CELL_W + _CELL_W // 2
    cy = _PAD_Y   + row * _CELL_H + _CELL_H // 2
    return cx, cy


def _svg_arrow(x1, y1, x2, y2, color="#555") -> str:
    """贝塞尔曲线箭头"""
    dx = x2 - x1
    cp1x, cp1y = x1 + dx * 0.3, y1
    cp2x, cp2y = x2 - dx * 0.3, y2
    return (f'<path d="M{x1:.0f},{y1:.0f} C{cp1x:.0f},{cp1y:.0f} '
            f'{cp2x:.0f},{cp2y:.0f} {x2:.0f},{y2:.0f}" '
            f'stroke="{color}" stroke-width="1.5" fill="none" '
            f'marker-end="url(#arr)" opacity="0.6"/>')


def render_svg(top_k: List[str], classified: Dict[str, dict],
               G: nx.DiGraph, title: str = "函数级 Call Graph") -> str:
    """
    渲染 domain×layer 网格 SVG。
    列 = domain，行 = layer，节点画在对应格子，边画贝塞尔箭头。
    """
    n_cols = len(_DOMAIN_ORDER)
    n_rows = len(_LAYER_ORDER)
    W = _LABEL_W + _PAD_X + n_cols * _CELL_W + 20
    H = _PAD_Y   + n_rows * _CELL_H + 20

    top_set = set(top_k)
    pos: Dict[str, Tuple[float, float]] = {}
    for fn in top_k:
        info = classified.get(fn, {})
        pos[fn] = _grid_pos(info.get("domain", "unknown"), info.get("layer", "unknown"))

    lines = [
        f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="monospace" font-size="11">',
        # 箭头 marker
        '<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" '
        'orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#555"/></marker></defs>',
        # 背景
        f'<rect width="{W}" height="{H}" fill="#fafafa"/>',
        # 标题
        f'<text x="{W//2}" y="16" text-anchor="middle" font-weight="bold" font-size="13">'
        f'{_safe_xml(title)}</text>',
    ]

    # 网格线
    for row in range(n_rows + 1):
        y = _PAD_Y + row * _CELL_H
        lines.append(f'<line x1="{_LABEL_W}" y1="{y}" x2="{W-20}" y2="{y}" '
                     f'stroke="#ddd" stroke-width="1"/>')
    for col in range(n_cols + 1):
        x = _LABEL_W + _PAD_X + col * _CELL_W
        lines.append(f'<line x1="{x}" y1="{_PAD_Y}" x2="{x}" y2="{H-20}" '
                     f'stroke="#ddd" stroke-width="1"/>')

    # layer 行标签（左侧）
    for row, layer in enumerate(_LAYER_ORDER):
        cy = _PAD_Y + row * _CELL_H + _CELL_H // 2
        lines.append(f'<text x="{_LABEL_W - 5}" y="{cy + 4}" text-anchor="end" '
                     f'fill="#444" font-size="10">{layer}</text>')

    # domain 列标签（顶部）
    for col, domain in enumerate(_DOMAIN_ORDER):
        cx = _LABEL_W + _PAD_X + col * _CELL_W + _CELL_W // 2
        short = domain.replace("_", "\n")
        lines.append(f'<text x="{cx}" y="{_PAD_Y - 6}" text-anchor="middle" '
                     f'fill="#444" font-size="9">{domain}</text>')

    # 边（先画，节点盖在上面）
    for caller in top_k:
        for callee in G.successors(caller):
            if callee not in top_set or caller == callee:
                continue
            x1, y1 = pos[caller]
            x2, y2 = pos[callee]
            color = _DOMAIN_COLOR.get(classified.get(caller, {}).get("domain", "unknown"), "#aaa")
            lines.append(_svg_arrow(x1, y1 + _NODE_H // 2,
                                    x2, y2 - _NODE_H // 2, color))

    # 节点
    for fn in top_k:
        info = classified.get(fn, {})
        domain = info.get("domain", "unknown")
        color  = _DOMAIN_COLOR.get(domain, "#bdc3c7")
        cx, cy = pos[fn]
        rx, ry = cx - _NODE_W // 2, cy - _NODE_H // 2
        pr_val = info.get("pagerank", 0.0)
        ind    = info.get("in_degree", 0)
        outd   = info.get("out_degree", 0)
        label  = fn[:18] + ("…" if len(fn) > 18 else "")
        sub    = f"in:{ind} out:{outd}"

        lines.append(f'<rect x="{rx}" y="{ry}" width="{_NODE_W}" height="{_NODE_H}" '
                     f'rx="6" fill="{color}" stroke="#fff" stroke-width="1.5"/>')
        lines.append(f'<text x="{cx}" y="{ry + 14}" text-anchor="middle" '
                     f'font-weight="bold" fill="#222">{_safe_xml(label)}</text>')
        lines.append(f'<text x="{cx}" y="{ry + 28}" text-anchor="middle" '
                     f'fill="#555" font-size="9">{sub}</text>')

    lines.append("</svg>")
    return "\n".join(lines)


def svg_to_md(svg: str) -> str:
    """将 SVG 字符串编码为 base64 嵌入 Markdown 图片"""
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img src="data:image/svg+xml;base64,{b64}" style="max-width:100%;"/>'


# ---------------------------------------------------------------------------
# 表格渲染
# ---------------------------------------------------------------------------


def render_node_table(top_k: List[str], classified: Dict[str, dict]) -> str:
    lines = ["| 函数名 | domain | layer | 文件 | PageRank排名 | in° | out° |",
             "|--------|--------|-------|------|-------------|-----|------|"]
    for rank, fn in enumerate(top_k, 1):
        info = classified.get(fn, {})
        short_f = os.path.basename(info.get("file", ""))
        lines.append(
            f"| `{fn}` | {info.get('domain','?')} | {info.get('layer','?')} "
            f"| `{short_f}` | #{rank} "
            f"| {info.get('in_degree',0)} | {info.get('out_degree',0)} |"
        )
    return "\n".join(lines)


def render_file_table(FG: nx.DiGraph, classified: Dict[str, dict],
                      fn_meta: Dict[str, dict]) -> str:
    # 文件 → 主 domain
    file_domain: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for fn, info in classified.items():
        f = info.get("file", "")
        if f:
            file_domain[f][info.get("domain", "unknown")] += 1

    def _fd(f):
        counts = file_domain.get(f, {})
        return max(counts, key=counts.get) if counts else "unknown"

    lines = ["| 源文件 | domain | 调用的文件（权重）|",
             "|--------|--------|-----------------|"]
    for src in sorted(FG.nodes()):
        targets = sorted(FG.successors(src),
                         key=lambda d: FG[src][d].get("weight", 0), reverse=True)
        if not targets:
            continue
        target_str = ", ".join(
            f"`{os.path.basename(t)}`×{FG[src][t].get('weight',1)}"
            for t in targets[:5]
        )
        lines.append(f"| `{os.path.basename(src)}` | {_fd(src)} | {target_str} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def generate_callgraph_section(
    repo_path: str,
    output_dir: str,
    top_k: int = 30,
    lsp_refine: bool = True,
    use_embedding: bool = True,  # 保留参数兼容旧调用，已不使用
) -> str:
    """
    生成完整的 Call Graph 报告块（Markdown + 内嵌 SVG）。
    缓存到 output_dir/callgraph_overview.json。
    """
    cache_path = os.path.join(output_dir, "callgraph_overview.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f).get("markdown", "")
        except Exception:
            pass

    print(f"\n{'='*60}")
    print(f"[CallGraph] 构建全库 Call Graph: {repo_path}")

    # Step 1-3: 构建 DiGraph
    G, fn_meta = build_digraph(repo_path)
    if G.number_of_nodes() == 0:
        return "> ⚠️  Call Graph 构建失败：未检测到函数\n"

    # Step 4: PageRank Top-k
    pr = nx.pagerank(G, alpha=0.85, max_iter=200) if G.number_of_nodes() > 0 else {}
    nx.set_node_attributes(G, pr, "pagerank")
    top_k_nodes = select_top_k_pagerank(G, k=top_k)
    print(f"[CallGraph] {G.number_of_nodes()} 节点, {G.number_of_edges()} 边 → Top-{len(top_k_nodes)}")

    # Step 5: LSP 精化
    if lsp_refine:
        refine_with_lsp(G, fn_meta, repo_path, top_k_nodes)

    # Step 6: 分类（路径规则 + LLM 批量兜底，附函数体片段）
    classified = classify_nodes(top_k_nodes, G, fn_meta, repo_path=repo_path)

    # Step 8: 文件级图
    FG = build_file_graph(G, top_k_nodes, fn_meta)

    # Step 9: SVG + 表格
    fn_svg   = render_svg(top_k_nodes, classified, G, title="函数级 Call Graph（PageRank Top-k）")
    file_svg = render_svg(
        list(FG.nodes()),
        {f: {"domain": max(({fn: classified.get(fn, {}).get("domain", "unknown")
               for fn in top_k_nodes if fn_meta.get(fn, {}).get("file") == f}).values(),
              default="unknown"),
             "layer": "kernel",
             "file": f, "in_degree": FG.in_degree(f), "out_degree": FG.out_degree(f),
             "pagerank": 0.0}
         for f in FG.nodes()},
        FG,
        title="文件级 Call Graph",
    ) if False else ""  # 文件级改用表格，SVG节点太多

    markdown = f"""## Call Graph 概览

> 基于 Tree-sitter 静态分析全库 **{G.number_of_nodes()}** 个函数、**{G.number_of_edges()}** 条调用边，
> 用 **PageRank** 选出架构枢纽 Top-{len(top_k_nodes)} 函数，
> 按 **domain（列）× layer（行）** 二维网格布局，连线体现调用关系。

### 函数级 Call Graph

{svg_to_md(fn_svg)}

**图例**：列 = domain 分类，行 = layer 层次（userspace→syscall\_boundary→kernel→hardware）
节点颜色：{" / ".join(f"`{d}`={c}" for d, c in list(_DOMAIN_COLOR.items())[:5])}

### 文件级调用关系

{render_file_table(FG, classified, fn_meta)}

### PageRank Top-{len(top_k_nodes)} 枢纽函数

{render_node_table(top_k_nodes, classified)}
"""

    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"markdown": markdown,
                       "fn_count": G.number_of_nodes(),
                       "edge_count": G.number_of_edges(),
                       "top_k": top_k_nodes}, f, ensure_ascii=False, indent=2)
        print(f"[CallGraph] 已缓存 → {cache_path}")
    except Exception as e:
        logger.warning(f"[CallGraph] 缓存写入失败: {e}")

    print(f"{'='*60}\n")
    return markdown
