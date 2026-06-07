"""
tools/callgraph_overview.py

全OS函数级 + 文件级 Call Graph 构建与分类模块。

流程：
  1. Tree-sitter 枚举全部函数 → 节点
  2. Tree-sitter 提取 outgoing calls → 边（单文件内）
  3. 构建 NetworkX DiGraph
  4. PageRank 排出枢纽函数 Top-k
  5. LSP 精化 Top-k 节点的跨文件边
  6. LLM 批量分类 domain × layer（含代码片段）
  7. 聚合文件级 Call Graph
  8. 输出 SVG + Markdown 表格；缓存为同目录 ``.svg`` / ``.md`` / ``meta.json``（见文件头常量）

domain（9类）: arch_platform / trap_syscall / process_sched / memory_vm /
               fs_storage / sync_ipc / runtime_common / user_programs / unknown
layer（5类）:  userspace / syscall_boundary / kernel / hardware / unknown
"""

from __future__ import annotations

import html
import os
import re
import sys
import json
import base64
import logging
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

from tools.callgraph_semantic import (
    apply_semantic_prune_inactive_functions,
    collect_active_functions_by_file,
    compute_input_fingerprint,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DOMAINS = [
    "arch_platform", "trap_syscall", "process_sched", "memory_vm",
    "fs_storage", "sync_ipc", "runtime_common", "user_programs", "unknown",
]

LAYERS = ["userspace", "syscall_boundary", "kernel", "hardware", "unknown"]


# 含 .h/.hpp：解析宏、typedef，便于节点标注类型与路径
_CODE_EXTS = {".c", ".h", ".cc", ".cpp", ".hpp", ".rs", ".go", ".zig"}

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

# LSP callHierarchy 递归深度默认值（与 lsp_ops 约定 1～5；须在 refine_with_lsp 之前定义）
LSP_REFINE_MAX_DEPTH_DEFAULT = 4


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


# SVG 表头（domain / layer）用深色 + 略大字号，保证缩略图里仍可读
_SVG_HEADER_FILL = "#111827"

# 全图默认字体：系统 UI / 无衬线 + 中英文字体回退（比纯 monospace 更易读）
_SVG_FONT_FAMILY = (
    'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", '
    'Arial, "PingFang SC", "Microsoft YaHei", sans-serif'
)
# 根元素 font-size，子元素未指定时继承
_SVG_FONT_BASE = 13
# 坐标轴标签：左侧 layer 固定字号；上方 domain 在 11～13 间随列宽变化（与左侧主档对齐为 12）
_SVG_AXIS_LABEL_FS = 12


def _svg_domain_header(cx: float, col_w: float, domain: str) -> str:
    """
    domain 列表头：始终完整显示，不用省略号。
    列窄时用略小字号 + 双行 tspan，保证可读。
    """
    parts = domain.split("_")
    # 与左侧 layer 标签统一刻度：常用 12px，宽列 13、极窄列 11（不再用 10，避免与左侧差一档）
    if col_w >= 100:
        fs = "13"
        dy = _DOMAIN_LABEL_LINE_GAP
    elif col_w >= 64:
        fs = "12"
        dy = _DOMAIN_LABEL_LINE_GAP
    else:
        fs = "11"
        dy = 10.0

    if len(parts) == 1:
        return (
            f'<text x="{cx:.1f}" y="{_DOMAIN_LABEL_LINE1_Y + 11:.1f}" text-anchor="middle" '
            f'font-size="{fs}" font-weight="600" fill="{_SVG_HEADER_FILL}">{_safe_xml(domain)}</text>'
        )
    line1 = parts[0]
    line2 = "_".join(parts[1:])
    y1 = _DOMAIN_LABEL_LINE1_Y
    return (
        f'<text text-anchor="middle" font-size="{fs}" font-weight="600" fill="{_SVG_HEADER_FILL}">'
        f'<tspan x="{cx:.1f}" y="{y1:.1f}">{_safe_xml(line1)}</tspan>'
        f'<tspan x="{cx:.1f}" dy="{dy:.1f}">{_safe_xml(line2)}</tspan>'
        f"</text>"
    )


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


def _c_extract_fn_ident_from_declarator(node, code_bytes: bytes) -> Optional[str]:
    """
    从 C/C++ 声明符链中取出函数名。
    覆盖：void f(void) 顶层 function_declarator；
    以及 struct T *f(void) 中 pointer_declarator → function_declarator → identifier。
    """
    if node.type == "identifier":
        return code_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
    if node.type == "function_declarator":
        for ch in node.children:
            if ch.type == "identifier":
                return code_bytes[ch.start_byte : ch.end_byte].decode("utf-8", errors="ignore")
            if ch.type in ("pointer_declarator", "array_declarator", "parenthesized_declarator"):
                r = _c_extract_fn_ident_from_declarator(ch, code_bytes)
                if r:
                    return r
        return None
    if node.type == "pointer_declarator":
        for ch in node.children:
            if ch.type == "*":
                continue
            r = _c_extract_fn_ident_from_declarator(ch, code_bytes)
            if r:
                return r
    return None


def _extract_fn_name(node, code_bytes: bytes, lang: str) -> Optional[str]:
    if lang in ("c", "cpp"):
        for child in node.children:
            if child.type == "function_declarator":
                name = _c_extract_fn_ident_from_declarator(child, code_bytes)
                if name:
                    return name
            # struct cpu *mycpu(void) { } — 顶层为 pointer_declarator
            if child.type == "pointer_declarator":
                name = _c_extract_fn_ident_from_declarator(child, code_bytes)
                if name:
                    return name
    elif lang in ("rust", "go", "zig"):
        for child in node.children:
            if child.type == "identifier":
                return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
    return None


def _extract_preproc_macro_name(node, code_bytes: bytes) -> Optional[str]:
    """#define NAME … / #define NAME(…) 的宏名（取第一个 identifier）。"""
    if node.type not in ("preproc_def", "preproc_function_def"):
        return None
    for ch in node.children:
        if ch.type == "identifier":
            return code_bytes[ch.start_byte : ch.end_byte].decode("utf-8", errors="ignore")
    return None


def _extract_typedef_name(node, code_bytes: bytes) -> Optional[str]:
    """typedef 最终别名：取子树中最后一个 type_identifier（适配 typedef … uint16 等）。"""
    if node.type != "type_definition":
        return None
    last: Optional[str] = None

    def walk(n) -> None:
        nonlocal last
        if n.type == "type_identifier":
            last = code_bytes[n.start_byte : n.end_byte].decode("utf-8", errors="ignore")
        for ch in n.children:
            walk(ch)

    walk(node)
    return last


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


def _parse_file(abs_path: str, rel_path: str, lang: str) -> Tuple[List[dict], List[Tuple[str, str]], List[dict]]:
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
    extras: List[dict] = []

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

    def _traverse_symbols(node):
        if lang in ("c", "cpp"):
            if node.type in ("preproc_def", "preproc_function_def"):
                mname = _extract_preproc_macro_name(node, code_bytes)
                if mname and mname not in _KEYWORD_SKIP:
                    extras.append(
                        {
                            "name": mname,
                            "file": rel_path,
                            "line": node.start_point[0] + 1,
                            "lang": lang,
                            "kind": "macro",
                        }
                    )
            elif node.type == "type_definition":
                tname = _extract_typedef_name(node, code_bytes)
                if tname and tname not in _KEYWORD_SKIP:
                    extras.append(
                        {
                            "name": tname,
                            "file": rel_path,
                            "line": node.start_point[0] + 1,
                            "lang": lang,
                            "kind": "typedef",
                        }
                    )
        for ch in node.children:
            _traverse_symbols(ch)

    _traverse(tree.root_node)
    _traverse_symbols(tree.root_node)
    return functions, edges, extras


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

            fns, file_edges, extras = _parse_file(abs_path, rel_path, lang)
            total_files += 1

            for fn in fns:
                name = fn["name"]
                if name not in fn_meta:
                    fn_meta[name] = {
                        "file": fn["file"],
                        "line": fn["line"],
                        "lang": fn["lang"],
                        "kind": "function",
                    }
                    G.add_node(name, **fn_meta[name])

            for ex in extras:
                ename = ex["name"]
                if ename not in fn_meta:
                    fn_meta[ename] = {
                        "file": ex["file"],
                        "line": ex["line"],
                        "lang": ex["lang"],
                        "kind": ex["kind"],
                    }
                    G.add_node(ename, **fn_meta[ename])

            for caller, callee in file_edges:
                if caller in fn_meta:
                    G.add_edge(caller, callee)

    logger.info(f"[CallGraph] 扫描 {total_files} 文件 → {G.number_of_nodes()} 节点, {G.number_of_edges()} 边")
    return G, fn_meta


def _backfill_fn_meta_refs(G: nx.DiGraph, fn_meta: Dict[str, dict]) -> None:
    """
    对无定义路径的节点，从调用边收集「引用侧」文件，便于图中/表里展示 ref: …
    """
    for n in G.nodes():
        meta = fn_meta.get(n)
        if meta and (meta.get("file") or "").strip():
            continue
        refs: List[str] = []
        for p in G.predecessors(n):
            pf = (fn_meta.get(p) or {}).get("file", "")
            if pf:
                refs.append(pf)
        if not refs:
            continue
        seen: Set[str] = set()
        uniq: List[str] = []
        for r in refs:
            if r not in seen:
                seen.add(r)
                uniq.append(r)
        if n not in fn_meta:
            fn_meta[n] = {"file": "", "line": 0, "lang": ""}
        fn_meta[n]["ref_files"] = uniq[:5]
        fn_meta[n].setdefault("kind", "call_only")
        if n in G:
            G.nodes[n]["ref_files"] = fn_meta[n]["ref_files"]
            G.nodes[n]["kind"] = fn_meta[n].get("kind", "call_only")


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

# clangd / rust-analyzer 树形输出常见：`│   ├── name  [detail]  ← path:line`（无 name() 后缀）
_RE_LSP_TREE_NAME_BRACKET = re.compile(r"\s*[\│├└├─]+\s*(\w+)\s+\[")
# 旧式或 grep 回退：`├── foo()`
_RE_LSP_TREE_NAME_PAREN = re.compile(r"[├└─] +(\w+)\(\)")


def _lsp_section_header_outgoing(line: str) -> bool:
    """clangd 文本里「出向调用」/ Outgoing 区块标题行。"""
    return "Outgoing" in line or "出向" in line


def _lsp_section_header_incoming(line: str) -> bool:
    """「入向调用」/ Incoming 区块标题行。"""
    return "Incoming" in line or "入向" in line


def _lsp_get_call_graph_text(
    lsp_tool: object,
    repo_path: str,
    file_path: str,
    symbol: str,
    direction: str,
    max_depth: int,
) -> str:
    """
    调用 lsp_ops.lsp_get_call_graph。该符号在 LangChain 下多为 StructuredTool，不可 () 直接调用。
    """
    kwargs = {
        "repo_path": repo_path,
        "file_path": file_path,
        "symbol": symbol,
        "direction": direction,
        "max_depth": max_depth,
    }
    if hasattr(lsp_tool, "invoke"):
        return str(lsp_tool.invoke(kwargs))
    return str(
        lsp_tool(repo_path, file_path, symbol, direction, max_depth=max_depth)  # type: ignore[misc]
    )


def _parse_lsp_call_graph_edges(result: str, fn: str) -> List[Tuple[str, str]]:
    """
    从 LSP 树形文本解析有向调用边 (caller, callee)。

    出向树：fn 调用子节点 → (fn, child)。
    入向树：父节点调用 fn → (parent, fn)。旧实现把入向也当成 (fn, parent)，图方向会错。
    """
    seen: Set[Tuple[str, str]] = set()
    out: List[Tuple[str, str]] = []
    mode: Optional[str] = None  # "out" | "in"
    for line in result.splitlines():
        if _lsp_section_header_incoming(line):
            mode = "in"
            continue
        if _lsp_section_header_outgoing(line):
            mode = "out"
            continue
        if mode is None:
            continue
        m = _RE_LSP_TREE_NAME_BRACKET.search(line) or _RE_LSP_TREE_NAME_PAREN.search(line)
        if not m:
            continue
        name = m.group(1)
        if name in _KEYWORD_SKIP or not name[0].islower():
            continue
        if mode == "out":
            if name == fn:
                continue
            key = (fn, name)
        else:
            if name == fn:
                continue
            key = (name, fn)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def refine_with_lsp(
    G: nx.DiGraph,
    fn_meta: Dict[str, dict],
    repo_path: str,
    top_k_nodes: List[str],
    limit: int = 30,
    max_depth: int = LSP_REFINE_MAX_DEPTH_DEFAULT,
) -> int:
    """用 LSP callHierarchy 补充 Top-k 节点的跨文件边（in-place 修改 G）。返回成功精化的节点数。"""
    try:
        from tools.lsp_ops import lsp_get_call_graph
    except ImportError:
        return 0

    md = max(1, min(5, int(max_depth)))
    refined = 0
    err_n = 0
    for fn in top_k_nodes[:limit]:
        info = fn_meta.get(fn, {})
        file_path = info.get("file", "")
        if not file_path:
            continue
        try:
            result = _lsp_get_call_graph_text(
                lsp_get_call_graph, repo_path, file_path, fn, "both", md
            )
            if not result or "DEGRADED" in result:
                continue
            for caller, callee in _parse_lsp_call_graph_edges(result, fn):
                if caller not in G:
                    G.add_node(caller)
                if callee not in G:
                    G.add_node(callee)
                G.add_edge(caller, callee)
            refined += 1
        except Exception as e:
            err_n += 1
            if err_n <= 3:
                logger.warning("[CallGraph] LSP 精化单节点失败 %s: %s", fn, e)

    logger.info(f"[CallGraph] LSP 精化了 {refined} 个节点")
    return refined


# ---------------------------------------------------------------------------
# Step 6: 关键调用路径（BFS）
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Step 7: 分类 domain × layer
# ---------------------------------------------------------------------------

# 发给 LLM 的每个函数源码行数（从 Tree-sitter 给出的函数起始行起，向下连续截取）。
# 20 行对长函数往往只看到开头；40 行在信息量与 prompt 体积之间较均衡，可按需调大。
CLASSIFY_SNIPPET_LINES = 40
# 定义行上方额外行数：函数（注释/static）、宏/typedef（#if/#ifdef）
CLASSIFY_BEFORE_FUNCTION = 4
CLASSIFY_BEFORE_MACRO = 6
CLASSIFY_BEFORE_CALLSITE = 12
# 过短的符号名在引用文件中搜索误命中率高，跳过「首处匹配」
MIN_SYMBOL_LEN_FOR_GREP = 3


def _read_fn_snippet(
    abs_path: str,
    start_line: int,
    max_lines: int = 40,
    *,
    before_extra: int = 0,
) -> str:
    """
    从 start_line 起读取最多 max_lines 行；若 before_extra>0，再向上附带若干行（注释/#if 等）。
    行号为 1-based。
    """
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if start_line < 1:
            return ""
        lo = max(0, start_line - 1 - max(0, before_extra))
        hi = min(len(lines), start_line - 1 + max_lines)
        return "".join(lines[lo:hi]).strip()
    except Exception:
        return ""


def _find_first_symbol_line(abs_path: str, symbol: str) -> Optional[int]:
    """在单文件中查找符号名首次出现的行号（词边界），用于 call_only 调用点邻域。"""
    if len(symbol) < MIN_SYMBOL_LEN_FOR_GREP:
        return None
    try:
        pat = re.compile(r"\b" + re.escape(symbol) + r"\b")
    except re.error:
        return None
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, 1):
                if pat.search(line):
                    return i
    except OSError:
        return None
    return None


def _resolve_call_only_snippet(
    repo_path: str,
    symbol: str,
    ref_files: List[str],
) -> Tuple[str, str, str]:
    """
    为「仅调用」节点解析代码片段。

    返回 (snippet, rel_path_used, note)。
    """
    refs = [r for r in (ref_files or []) if r and isinstance(r, str)]
    for rel in refs:
        abs_path = os.path.join(repo_path, rel)
        ln = _find_first_symbol_line(abs_path, symbol)
        if ln:
            sn = _read_fn_snippet(
                abs_path,
                ln,
                max_lines=CLASSIFY_SNIPPET_LINES,
                before_extra=CLASSIFY_BEFORE_CALLSITE,
            )
            return sn, rel, f"调用点邻域（{rel} 第 {ln} 行附近）"
    if refs:
        rel = refs[0]
        abs_path = os.path.join(repo_path, rel)
        sn = _read_fn_snippet(abs_path, 1, max_lines=min(CLASSIFY_SNIPPET_LINES, 36))
        reason = (
            "符号名过短未搜索"
            if len(symbol) < MIN_SYMBOL_LEN_FOR_GREP
            else "未在引用文件中词边界命中"
        )
        return sn, rel, f"{reason}，退化为文件开头（{rel}）"
    return "", "", "无引用文件"


def _symbol_kind_zh(kind: str) -> str:
    return {
        "function": "函数（有定义）",
        "macro": "宏（#define 等）",
        "typedef": "typedef / 类型定义",
        "call_only": "仅调用（本仓库未解析到定义）",
        "unknown": "未知",
    }.get(kind, kind)


def _resolve_kind_for_classify(info: dict, rel_path: str) -> str:
    k = info.get("kind")
    if k:
        return str(k)
    if rel_path:
        return "function"
    if info.get("ref_files"):
        return "call_only"
    return "unknown"


def _format_caller_hints(
    G: nx.DiGraph,
    fn: str,
    fn_meta: Dict[str, dict],
    limit: int = 8,
) -> str:
    """有向边 predecessor → fn，即「谁调用了该符号」。"""
    parts: List[str] = []
    for p in G.predecessors(fn):
        if p == fn:
            continue
        meta = fn_meta.get(p) or {}
        fp = (meta.get("file") or "").strip()
        k = meta.get("kind") or ("function" if fp else "unknown")
        if fp:
            parts.append(f"{p} [{k}] in {fp}")
        else:
            parts.append(f"{p} [{k}]")
        if len(parts) >= limit:
            break
    return "；".join(parts) if parts else ""


def _extract_token_usage_from_response(response) -> Dict[str, int]:
    """从 LLM 响应中提取 token usage。"""
    metadata = getattr(response, "response_metadata", None) or {}
    usage = metadata.get("token_usage", {}) or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def _llm_classify_batch(nodes: List[dict]) -> Tuple[dict, int]:
    """
    用 LLM 批量分类 domain × layer。
    nodes: fn_name, file_path, symbol_kind, code_snippet, snippet_note, caller_hints
    返回: ({fn_name: {"domain": ..., "layer": ...}}, 本次 invoke 的 total_tokens；失败为 0)
    """
    if not nodes:
        return {}, 0

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
        "userspace: 运行在用户态的代码（用户程序/用户态库）\n"
        "syscall_boundary: 系统调用入口/分发（函数名常为 sys_* 或位于 syscall 分发表路径）\n"
        "kernel: 内核态通用逻辑（调度/内存/VFS 等，但不要把 sys_* 或 trap 入口标成 kernel）\n"
        "hardware: 直接 MMIO、寄存器、PLIC/CLINT/UART/VirtIO 等硬件抽象层\n"
        "unknown: 无法确定\n\n"
        "重要：不要图省事把大量符号都标成 kernel。"
        "若函数名为 sys_* 应标 syscall_boundary；"
        "若为 trap/exception/syscall_handler 入口应标 syscall_boundary 或与 trap 相关的 domain；"
        "若代码片段里出现 MMIO/寄存器读写应标 hardware。\n\n"
        "非函数符号（macro / typedef）时：layer 仍按语义——寄存器/MMIO 宏可标 hardware；"
        "纯类型别名多为 kernel（或 userspace 若片段明显在用户态头文件）。\n"
        "symbol_kind 为 call_only 时：优先根据「入边调用方」与「调用点邻域」推断 domain；"
        "无代码片段时勿猜具体实现，可 unknown。"
    )

    # 格式化节点信息，包含代码片段
    nodes_text = ""
    for n in nodes:
        sk = n.get("symbol_kind", "function")
        sk_zh = _symbol_kind_zh(sk)
        nodes_text += f"\n### {n['fn_name']}\n"
        nodes_text += f"symbol_kind: {sk_zh} ({sk})\n"
        nodes_text += f"文件: {n.get('file_path', '')}\n"
        if n.get("snippet_note"):
            nodes_text += f"代码片段说明: {n['snippet_note']}\n"
        ch = (n.get("caller_hints") or "").strip()
        if ch:
            nodes_text += f"入边调用方（谁引用/调用该符号）: {ch}\n"
        if n.get("code_snippet"):
            nodes_text += f"```c\n{n['code_snippet']}\n```\n"
        else:
            nodes_text += "代码片段: （无；请根据路径与入边调用方推断，不确定则 domain/layer 用 unknown）\n"

    prompt = (
        "你是操作系统内核专家。根据「符号类型 symbol_kind、符号名、文件路径、"
        "入边调用方、代码片段与片段说明」，对每个符号按 domain 与 layer 分类，只输出 JSON。\n\n"
        "domain/layer 最初按函数语义设计；对宏、typedef、仅调用符号，按其在系统中的**角色**归类："
        "例如硬件寄存器宏 → arch_platform + hardware；VFS 相关类型 → fs_storage；"
        "无法从片段判断时用 unknown。\n\n"
        f"domain（选一个）:\n{domain_desc}\n\n"
        f"layer（选一个）:\n{layer_desc}\n\n"
        f"符号列表:{nodes_text}\n"
        '输出格式（只输出JSON，不要markdown代码块）:\n'
        '{"fn_name": {"domain": "...", "layer": "..."}, ...}'
    )

    try:
        from core.agent_builder import build_chat_model
        from langchain_core.messages import HumanMessage
        llm = build_chat_model(temperature=0)
        resp = llm.invoke([HumanMessage(content=prompt)])
        u = _extract_token_usage_from_response(resp)
        total_tok = int(u.get("total_tokens", 0) or 0)
        text = resp.content.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip()), total_tok
    except Exception as e:
        logger.warning(f"[ClassifyNodes] LLM 批量分类失败: {e}")
        print(f"   ⚠️  LLM domain×layer 分类失败: {e}")
        sys.stdout.flush()
        return {}, 0


def _refine_layer_after_llm(fn: str, rel_path: str, layer: str) -> str:
    """
    LLM 之后做少量确定性修正，缓解「几乎全是 kernel」：
    - 系统调用入口命名约定 → syscall_boundary
    """
    if fn.startswith("sys_") or fn.startswith("SYS_"):
        return "syscall_boundary"
    rel_lower = (rel_path or "").replace("\\", "/").lower()
    if "/syscall" in rel_lower or "syscall_" in rel_lower or "sys_call" in rel_lower:
        if layer == "kernel":
            return "syscall_boundary"
    return layer


def _normalize_llm_classify_result(preds: dict) -> Dict[str, Dict[str, str]]:
    merged: Dict[str, Dict[str, str]] = {}
    if not isinstance(preds, dict):
        return merged
    for fn, v in preds.items():
        if isinstance(v, dict):
            d = v.get("domain", "unknown")
            ly = v.get("layer", "kernel")
            if d not in DOMAINS:
                d = "unknown"
            if ly not in LAYERS:
                ly = "unknown"
            merged[str(fn)] = {"domain": d, "layer": ly}
    return merged


def classify_nodes(top_k: List[str], G: nx.DiGraph,
                   fn_meta: Dict[str, dict],
                   repo_path: str = "") -> Tuple[Dict[str, dict], int]:
    """
    对 Top-k 节点分类 domain × layer。
    **仅**通过 LLM（一次请求，含代码片段）分类。
    返回 (classified 字典, 本次 LLM total_tokens)。
    """
    batch_items: List[dict] = []
    for fn in top_k:
        info = fn_meta.get(fn, {})
        rel_path = (info.get("file") or "").strip()
        if not rel_path and info.get("ref_files"):
            rel_path = (info["ref_files"][0] or "").strip()
        kind = _resolve_kind_for_classify(info, rel_path)
        line_no = int(info.get("line") or 0)
        snippet = ""
        snippet_note = ""
        display_path = rel_path
        caller_hints = _format_caller_hints(G, fn, fn_meta, limit=8)

        if repo_path and kind == "call_only":
            snippet, display_path, snippet_note = _resolve_call_only_snippet(
                repo_path, fn, list(info.get("ref_files") or [])
            )
            if not (display_path or "").strip() and rel_path:
                display_path = rel_path
        elif repo_path and rel_path and line_no >= 1:
            abs_path = os.path.join(repo_path, rel_path)
            if kind == "function":
                snippet = _read_fn_snippet(
                    abs_path,
                    line_no,
                    max_lines=CLASSIFY_SNIPPET_LINES,
                    before_extra=CLASSIFY_BEFORE_FUNCTION,
                )
                snippet_note = (
                    f"函数定义自第 {line_no} 行起 {CLASSIFY_SNIPPET_LINES} 行"
                    f"（含上方 {CLASSIFY_BEFORE_FUNCTION} 行上下文）"
                )
            elif kind in ("macro", "typedef"):
                snippet = _read_fn_snippet(
                    abs_path,
                    line_no,
                    max_lines=CLASSIFY_SNIPPET_LINES,
                    before_extra=CLASSIFY_BEFORE_MACRO,
                )
                snippet_note = (
                    f"{kind} 定义自第 {line_no} 行"
                    f"（含上方 {CLASSIFY_BEFORE_MACRO} 行预处理器/注释上下文）"
                )
            else:
                snippet = _read_fn_snippet(abs_path, line_no, max_lines=CLASSIFY_SNIPPET_LINES)
                snippet_note = f"自第 {line_no} 行起"
        elif repo_path and rel_path and line_no < 1 and kind != "call_only":
            abs_path = os.path.join(repo_path, rel_path)
            snippet = _read_fn_snippet(
                abs_path, 1, max_lines=min(CLASSIFY_SNIPPET_LINES, 28)
            )
            snippet_note = "无有效行号，使用文件开头"

        batch_items.append({
            "fn_name": fn,
            "file_path": display_path or rel_path,
            "symbol_kind": kind,
            "code_snippet": snippet,
            "snippet_note": snippet_note,
            "caller_hints": caller_hints,
        })

    raw, classify_llm_tokens = _llm_classify_batch(batch_items)
    llm_preds = _normalize_llm_classify_result(raw)
    result: Dict[str, dict] = {}

    for fn in top_k:
        info = dict(fn_meta.get(fn, G.nodes.get(fn, {}) or {}))
        rel_path = (info.get("file") or "").strip()
        pred = llm_preds.get(fn, {})
        domain = pred.get("domain", "unknown")
        hint_path = rel_path or ((info.get("ref_files") or [""])[0] or "")
        layer = _refine_layer_after_llm(fn, hint_path, pred.get("layer", "kernel"))

        kind = info.get("kind")
        if not kind:
            if rel_path:
                kind = "function"
            elif info.get("ref_files"):
                kind = "call_only"
            else:
                kind = "unknown"

        result[fn] = {
            "domain": domain,
            "layer": layer,
            "file": rel_path,
            "line": info.get("line", 0),
            "kind": kind,
            "ref_files": list(info.get("ref_files", [])),
            "in_degree": G.in_degree(fn),
            "out_degree": G.out_degree(fn),
            "pagerank": G.nodes[fn].get("pagerank", 0.0) if fn in G else 0.0,
            "method": "llm",
        }

    return result, classify_llm_tokens


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

# SVG 布局参数（有节点列宽由 _compute_variable_grid_layout 按格内最长标签动态算）
_CELL_W_BASE = 188.0
_CELL_W_FULL = _CELL_W_BASE * 0.8 * 1.1  # 无「按内容」时的回退宽度
_CELL_W_MIN = 108.0          # 有节点列下限（随字号略增）
_CELL_W_CAP = 520.0          # 有节点列上限（避免极长路径撑爆画布）
_CELL_INNER_PAD = 24.0       # 列宽在「最长节点」估算值上的额外留白
# 无节点列仍须能放下完整 domain 表头（双行、无省略号），过窄会被迫缩写
_CELL_W_COMPACT = 82.0
_CELL_H_COMPACT = 40.0       # 无节点行压缩高度
# 按「该行所有格中函数个数的最大值」估算行高，避免 2 个与 8 个函数共用同一行高
_ROW_GAP = 8.0               # 格内相邻函数节点之间的竖向空隙
_ROW_CELL_PAD = 8.0          # 格内上下留白（与 _layout_group_in_cell 的 pad 协调）
_ROW_PLAN_NODE_H = 36.0      # 估算行高用（与 _NODE_H 协调）
_NODE_W = 140                # 节点矩形宽（上限，实际受格宽约束）
_NODE_H = 48                 # 节点矩形高（上限；与略大字号匹配）
_PAD_X = 16                 # 标签区与网格之间的空隙
# 顶边：domain 表头 + 略大行距；第一条网格横线在 _GRID_Y0
_GRID_Y0 = 46.0
_DOMAIN_LABEL_LINE1_Y = 19.0
_DOMAIN_LABEL_LINE_GAP = 12.0
_PAD_Y = _GRID_Y0  # 首行格子顶边（与 _GRID_Y0 一致）
_LABEL_W = 142.0     # 左侧 layer 表头列（容纳 syscall_boundary 等）


_KIND_LABEL_ZH = {
    "function": "函数定义",
    "macro": "宏（#define）",
    "typedef": "类型别名（typedef）",
    "call_only": "仅引用（调用侧）",
    "unknown": "未知",
}


def _resolve_symbol_kind(info: dict) -> str:
    """与 classify / 建图一致的 kind 字符串。"""
    k = info.get("kind") or ("function" if (info.get("file") or "").strip() else "unknown")
    if k == "function" and not (info.get("file") or "").strip() and (info.get("ref_files") or []):
        return "call_only"
    return k


def _svg_node_main_line(fn: str, info: dict) -> str:
    """节点第一行：仅符号名（不写 fn / ref / t / # 等英文前缀）。"""
    return fn


def _svg_node_sub_line(info: dict) -> str:
    """
    节点第二行：函数定义仅显示相对路径；
    非函数（宏、typedef、仅引用）用中文说明类别并附路径或调用侧文件。
    """
    k = _resolve_symbol_kind(info)
    fp = (info.get("file") or "").replace("\\", "/").strip()
    refs = info.get("ref_files") or []
    label = _KIND_LABEL_ZH.get(k, "未知")

    if k == "function" and fp:
        return fp
    if fp:
        return f"{label} · {fp}"
    if refs:
        rels = [r.replace("\\", "/") for r in refs[:3]]
        tail = "…" if len(refs) > 3 else ""
        return f"{label} · " + ", ".join(rels) + tail
    return "—"


def _node_label_width_nominal(fn: str, info: dict, nh: float) -> float:
    """
    估算节点两行标签（等宽字体）在字号未缩放时所需宽度，用于布局矩形宽与渲染时按比例缩小字号。
    """
    line1 = _svg_node_main_line(fn, info)
    line2 = _svg_node_sub_line(info)
    fs_main = 15.0 if nh >= 30 else (13.0 if nh >= 20 else 11.0)
    fs_sub = 13.0 if nh >= 30 else (11.0 if nh >= 20 else 9.0)
    pad = 12.0

    def _mono_w(s: str, fs: float) -> float:
        return len(s) * fs * 0.62

    return pad + max(_mono_w(line1, fs_main), _mono_w(line2, fs_sub))


def _row_height_for_max_cell_count(n: int) -> float:
    """
    某 layer 行的高度：由该行所有 domain 格中「函数个数的最大值」决定，
    使 2 个函数的行与 8 个函数的行高度不同，而不是整行固定同一高度。
    """
    if n <= 0:
        return float(_CELL_H_COMPACT)
    inner = n * _ROW_PLAN_NODE_H + max(0, n - 1) * _ROW_GAP
    return float(max(64.0, _ROW_CELL_PAD * 2 + inner))


def _compute_variable_grid_layout(
    top_k: List[str], classified: Dict[str, dict]
) -> Dict[str, object]:
    """
    按 Top-k 分布：有节点的 domain **列宽**按该列下所有格中最长节点标签动态估算；
    无节点列压缩；行高按该行「单格内函数个数」的最大值计算。
    """
    groups: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    domains_used: Set[str] = set()
    layers_used: Set[str] = set()
    for fn in top_k:
        info = classified.get(fn, {})
        d = info.get("domain", "unknown")
        ly = info.get("layer", "unknown")
        domains_used.add(d)
        layers_used.add(ly)
        groups[(d, ly)].append(fn)

    domain_max_w: Dict[str, float] = defaultdict(float)
    for domain in _DOMAIN_ORDER:
        for ly in _LAYER_ORDER:
            for fn in groups.get((domain, ly), []):
                info = classified.get(fn, {})
                need = _node_label_width_nominal(fn, info, float(_NODE_H))
                domain_max_w[domain] = max(domain_max_w[domain], need)

    col_w: List[float] = []
    for domain in _DOMAIN_ORDER:
        if domain in domains_used:
            need = float(domain_max_w.get(domain, _CELL_W_FULL) or _CELL_W_FULL)
            w = max(_CELL_W_MIN, min(_CELL_W_CAP, need + _CELL_INNER_PAD))
            col_w.append(w)
        else:
            col_w.append(float(_CELL_W_COMPACT))

    row_h: List[float] = []
    for ly in _LAYER_ORDER:
        max_n = 0
        for domain in _DOMAIN_ORDER:
            max_n = max(max_n, len(groups.get((domain, ly), [])))
        row_h.append(_row_height_for_max_cell_count(max_n))

    col_left: List[float] = []
    x = float(_LABEL_W + _PAD_X)
    for w in col_w:
        col_left.append(x)
        x += w
    row_top: List[float] = []
    y = float(_PAD_Y)
    for h in row_h:
        row_top.append(y)
        y += h

    W = x + 20.0
    H = y + 20.0
    return {
        "col_w": col_w,
        "row_h": row_h,
        "col_left": col_left,
        "row_top": row_top,
        "W": W,
        "H": H,
        "domains_used": domains_used,
        "layers_used": layers_used,
    }


def _cell_rect_from_layout(
    domain: str, layer: str, layout: Dict[str, object]
) -> Tuple[float, float, float, float]:
    """格子矩形 (left, top, right, bottom)，使用可变列宽/行高。"""
    col_w: List[float] = layout["col_w"]  # type: ignore
    row_h: List[float] = layout["row_h"]  # type: ignore
    col_left: List[float] = layout["col_left"]  # type: ignore
    row_top: List[float] = layout["row_top"]  # type: ignore
    ci = _DOMAIN_ORDER.index(domain) if domain in _DOMAIN_ORDER else len(_DOMAIN_ORDER) - 1
    ri = _LAYER_ORDER.index(layer) if layer in _LAYER_ORDER else len(_LAYER_ORDER) - 1
    left = col_left[ci]
    top = row_top[ri]
    right = left + col_w[ci]
    bottom = top + row_h[ri]
    return left, top, right, bottom


def _layout_group_in_cell(
    fns_sorted: List[str],
    left: float, top: float, right: float, bottom: float,
    classified: Dict[str, dict],
) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, Tuple[float, float]]]:
    """
    在单个格子矩形内排布节点，**不溢出格**：先单列上下排；放不下则缩高度；仍不行则双列。
    返回 (pos, sizes) 其中 sizes[fn] = (width, height)；宽度按函数名与文件路径估算（动态加宽）。
    """
    pad = 4.0
    inner_left = left + pad
    inner_top = top + pad
    inner_right = right - pad
    inner_bottom = bottom - pad
    avail_w = inner_right - inner_left
    avail_h = inner_bottom - inner_top
    n = len(fns_sorted)
    pos: Dict[str, Tuple[float, float]] = {}
    sizes: Dict[str, Tuple[float, float]] = {}
    gap = _ROW_GAP
    col_gap = 8.0
    col_avail_w = max(0.0, (avail_w - col_gap) / 2.0)

    if n == 0:
        return pos, sizes

    cx = (left + right) / 2

    def _width_single(fn: str, h_ref: float) -> float:
        info = classified.get(fn, {})
        need = _node_label_width_nominal(fn, info, h_ref)
        return min(avail_w, max(28.0, need))

    def _width_twocol(fn: str, h_ref: float) -> float:
        info = classified.get(fn, {})
        need = _node_label_width_nominal(fn, info, h_ref)
        cap = col_avail_w if col_avail_w > 1e-6 else avail_w
        return min(cap, max(28.0, need))

    # 单列：高度取 min(标准高, 均分可用高度)
    h_fit = (avail_h - (n - 1) * gap) / max(n, 1)
    h_single = max(6.0, min(_NODE_H, h_fit))
    single_fits = n * h_single + (n - 1) * gap <= avail_h + 1e-6

    if single_fits:
        total_h = n * h_single + (n - 1) * gap
        y_start = inner_top + (avail_h - total_h) / 2 + h_single / 2
        for i, fn in enumerate(fns_sorted):
            pos[fn] = (cx, y_start + i * (h_single + gap))
            sizes[fn] = (_width_single(fn, h_single), h_single)
        return pos, sizes

    # 双列
    cols = 2
    rows = (n + cols - 1) // cols
    h = (avail_h - (rows - 1) * gap) / max(rows, 1)
    h = max(6.0, min(_NODE_H, h))
    total_block_h = rows * h + (rows - 1) * gap
    while total_block_h > avail_h + 1e-6 and h > 6:
        h -= 0.5
        total_block_h = rows * h + (rows - 1) * gap
    y0 = inner_top + (avail_h - total_block_h) / 2 + h / 2
    x0 = inner_left + col_avail_w / 2.0
    x1 = inner_left + col_avail_w + col_gap + col_avail_w / 2.0
    for i, fn in enumerate(fns_sorted):
        col = i % cols
        row = i // cols
        cx_c = x0 if col == 0 else x1
        cy = y0 + row * (h + gap)
        pos[fn] = (cx_c, cy)
        sizes[fn] = (_width_twocol(fn, h), h)
    return pos, sizes


def _layout_top_k_in_grid(
    top_k: List[str],
    classified: Dict[str, dict],
    layout: Dict[str, object],
) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, Tuple[float, float]], float, float]:
    """
    为 Top-k 分配坐标与尺寸。同 (domain,layer) 格内上下/双列排布，**限制在格内**。
    返回 (pos, node_sizes, svg_width, svg_height)。
    """
    rank_order = {fn: i for i, fn in enumerate(top_k)}

    groups: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for fn in top_k:
        info = classified.get(fn, {})
        key = (info.get("domain", "unknown"), info.get("layer", "unknown"))
        groups[key].append(fn)

    pos: Dict[str, Tuple[float, float]] = {}
    node_sizes: Dict[str, Tuple[float, float]] = {}

    for (_domain, _layer), fns in groups.items():
        fns_sorted = sorted(
            fns,
            key=lambda f: (
                -float(classified.get(f, {}).get("pagerank") or 0.0),
                rank_order.get(f, 9999),
            ),
        )
        left, top, right, bottom = _cell_rect_from_layout(_domain, _layer, layout)
        p, s = _layout_group_in_cell(fns_sorted, left, top, right, bottom, classified)
        pos.update(p)
        node_sizes.update(s)

    W = float(layout["W"])  # type: ignore
    H = float(layout["H"])  # type: ignore
    return pos, node_sizes, W, H


def _edge_endpoints_on_rects(
    cx1: float,
    cy1: float,
    w1: float,
    h1: float,
    cx2: float,
    cy2: float,
    w2: float,
    h2: float,
) -> Tuple[float, float, float, float]:
    """
    有向边 caller→callee：连线端点取两矩形**四边中点**上的一对，
    按两中心相对方向自适应（左右用左右边中点，上下用上下边中点），避免总是底→顶导致侧向边极短、箭头看不见。
    """
    dx = cx2 - cx1
    dy = cy2 - cy1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return cx1, cy1 + h1 / 2, cx2, cy2 - h2 / 2
    if abs(dx) >= abs(dy):
        if dx > 0:
            return cx1 + w1 / 2, cy1, cx2 - w2 / 2, cy2
        return cx1 - w1 / 2, cy1, cx2 + w2 / 2, cy2
    if dy > 0:
        return cx1, cy1 + h1 / 2, cx2, cy2 - h2 / 2
    return cx1, cy1 - h1 / 2, cx2, cy2 + h2 / 2


def _svg_arrow(x1: float, y1: float, x2: float, y2: float, color: str = "#555") -> str:
    """贝塞尔箭头；控制点随主方向（横/纵）变化，避免与边走向不一致。"""
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return ""
    s = 0.38
    if abs(dx) >= abs(dy):
        cp1x, cp1y = x1 + dx * s, y1
        cp2x, cp2y = x2 - dx * s, y2
    else:
        cp1x, cp1y = x1, y1 + dy * s
        cp2x, cp2y = x2, y2 - dy * s
    return (
        f'<path d="M{x1:.1f},{y1:.1f} C{cp1x:.1f},{cp1y:.1f} {cp2x:.1f},{cp2y:.1f} {x2:.1f},{y2:.1f}" '
        f'stroke="{color}" stroke-width="2" fill="none" '
        f'marker-end="url(#arr)" opacity="0.88"/>'
    )


def render_svg(top_k: List[str], classified: Dict[str, dict],
               G: nx.DiGraph) -> str:
    """
    渲染 domain×layer 网格 SVG（不含标题；标题仅在 Markdown 中书写，避免与表头重叠）。
    列 = domain，行 = layer，节点画在对应格子，边画贝塞尔箭头。
    """
    n_cols = len(_DOMAIN_ORDER)
    n_rows = len(_LAYER_ORDER)

    top_set = set(top_k)
    layout = _compute_variable_grid_layout(top_k, classified)
    pos, node_sizes, W, H = _layout_top_k_in_grid(top_k, classified, layout)
    col_left: List[float] = layout["col_left"]  # type: ignore
    row_top: List[float] = layout["row_top"]  # type: ignore
    col_w: List[float] = layout["col_w"]  # type: ignore
    row_h: List[float] = layout["row_h"]  # type: ignore

    # font-family 用单引号属性值，便于内含 "Segoe UI" 等带空格字体名
    lines = [
        f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" '
        f"font-family='{_SVG_FONT_FAMILY}' font-size='{_SVG_FONT_BASE}'>",
        # 箭头 marker（略放大，与 2px 线宽匹配）
        '<defs><marker id="arr" markerWidth="10" markerHeight="10" refX="9" refY="3.5" '
        'orient="auto" markerUnits="userSpaceOnUse">'
        '<path d="M0,0 L0,7 L10,3.5 z" fill="#444"/></marker></defs>',
        # 背景
        f'<rect width="{W}" height="{H}" fill="#fafafa"/>',
    ]

    # 网格线（随列宽/行高变化）
    for row in range(n_rows + 1):
        y = row_top[row] if row < n_rows else row_top[-1] + row_h[-1]
        lines.append(f'<line x1="{_LABEL_W}" y1="{y:.1f}" x2="{W-20}" y2="{y:.1f}" '
                     f'stroke="#ddd" stroke-width="1"/>')
    for col in range(n_cols + 1):
        x = col_left[col] if col < n_cols else col_left[-1] + col_w[-1]
        lines.append(f'<line x1="{x:.1f}" y1="{_GRID_Y0:.1f}" x2="{x:.1f}" y2="{H-20}" '
                     f'stroke="#ddd" stroke-width="1"/>')

    # layer 行标签（左侧）：与上方 domain 表头「主档」同为 _SVG_AXIS_LABEL_FS（宽列 domain 可为 13）
    for row, layer in enumerate(_LAYER_ORDER):
        cy = row_top[row] + row_h[row] / 2
        lines.append(
            f'<text x="{_LABEL_W - 5}" y="{cy + 5}" text-anchor="end" '
            f'fill="{_SVG_HEADER_FILL}" font-size="{_SVG_AXIS_LABEL_FS}" '
            f'font-weight="600">{layer}</text>'
        )

    # domain 列标签（表头区，双行/缩写见 _svg_domain_header）
    for col, domain in enumerate(_DOMAIN_ORDER):
        cx = col_left[col] + col_w[col] / 2
        lines.append(_svg_domain_header(cx, col_w[col], domain))

    # 边（先画，节点盖在上面）；端点在两矩形四边中点上自适应，见 _edge_endpoints_on_rects
    for caller in top_k:
        for callee in G.successors(caller):
            if callee not in top_set or caller == callee:
                continue
            cx1, cy1 = pos[caller]
            cx2, cy2 = pos[callee]
            w1, h1 = node_sizes.get(caller, (_NODE_W, _NODE_H))
            w2, h2 = node_sizes.get(callee, (_NODE_W, _NODE_H))
            x1, y1, x2, y2 = _edge_endpoints_on_rects(cx1, cy1, w1, h1, cx2, cy2, w2, h2)
            color = _DOMAIN_COLOR.get(classified.get(caller, {}).get("domain", "unknown"), "#aaa")
            lines.append(_svg_arrow(x1, y1, x2, y2, color))

    # 节点（尺寸按格内布局，可小于默认）
    for fn in top_k:
        info = classified.get(fn, {})
        domain = info.get("domain", "unknown")
        color  = _DOMAIN_COLOR.get(domain, "#bdc3c7")
        cx, cy = pos[fn]
        nw, nh = node_sizes.get(fn, (_NODE_W, _NODE_H))
        rx, ry = cx - nw / 2, cy - nh / 2
        label = _svg_node_main_line(fn, info)
        sub = _svg_node_sub_line(info)
        base_main = 15.0 if nh >= 30 else (13.0 if nh >= 20 else 11.0)
        base_sub = 13.0 if nh >= 30 else (11.0 if nh >= 20 else 9.0)
        w_nom = _node_label_width_nominal(fn, info, nh)
        scale = min(1.0, float(nw) / max(w_nom, 1e-6))
        fs_main = max(5.0, float(base_main) * scale)
        fs_sub = max(4.0, float(base_sub) * scale)
        ty1 = ry + min(17, nh * 0.42)
        ty2 = ry + min(32, nh * 0.78)
        rx_attr = min(6, nh / 6)

        lines.append(f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{nw:.1f}" height="{nh:.1f}" '
                     f'rx="{rx_attr:.1f}" fill="{color}" stroke="#fff" stroke-width="1"/>')
        lines.append(f'<text x="{cx:.1f}" y="{ty1:.1f}" text-anchor="middle" '
                     f'font-weight="bold" font-size="{fs_main:.1f}" fill="#222">{_safe_xml(label)}</text>')
        if nh >= 16:
            lines.append(f'<text x="{cx:.1f}" y="{ty2:.1f}" text-anchor="middle" '
                         f'fill="#555" font-size="{fs_sub:.1f}">{_safe_xml(sub)}</text>')

    lines.append("</svg>")
    return "\n".join(lines)


def svg_to_md(svg: str) -> str:
    """将 SVG 字符串编码为 base64 嵌入 Markdown 图片"""
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img src="data:image/svg+xml;base64,{b64}" style="max-width:100%;"/>'


# 缓存文件（output_dir 下）：比单文件 JSON 塞整段 markdown+base64 更易维护、可单独打开 SVG
CALLGRAPH_SVG_FILENAME = "callgraph_overview.svg"
CALLGRAPH_MD_FILENAME = "callgraph_overview.md"
CALLGRAPH_META_FILENAME = "callgraph_overview_meta.json"
CALLGRAPH_LEGACY_JSON = "callgraph_overview.json"
CALLGRAPH_CACHE_VERSION = 5


def _svg_embed_markdown(relative_svg_name: str) -> str:
    """与总报告同目录时用相对路径引用 SVG，体积小、可 git diff、浏览器可直接打开 svg。"""
    return (
        f"![函数级 Call Graph]({relative_svg_name})\n\n"
        f"*（图：`{relative_svg_name}`，与报告同目录）*"
    )


def _classified_for_meta(classified: Dict[str, dict]) -> Dict[str, dict]:
    """只保留可 JSON 序列化、便于复现表格的字段。"""
    out: Dict[str, dict] = {}
    for fn, info in classified.items():
        out[fn] = {
            "domain": info.get("domain"),
            "layer": info.get("layer"),
            "kind": info.get("kind", "unknown"),
            "file": info.get("file", ""),
            "line": info.get("line", 0),
            "ref_files": list(info.get("ref_files", [])),
            "in_degree": info.get("in_degree", 0),
            "out_degree": info.get("out_degree", 0),
            "pagerank": float(info.get("pagerank") or 0.0),
            "method": info.get("method", "llm"),
        }
    return out


# ---------------------------------------------------------------------------
# 表格渲染
# ---------------------------------------------------------------------------


def render_node_table(top_k: List[str], classified: Dict[str, dict]) -> str:
    """HTML 表格：宽度随内容伸缩（不写死列宽）。"""
    th = ' style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa"'
    td = ' style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"'
    lines = [
        '<table style="border-collapse:collapse;width:auto;max-width:100%;table-layout:auto">',
        "<thead><tr>",
        f"<th{th}>符号</th>",
        f"<th{th}>类型</th>",
        f"<th{th}>domain</th>",
        f"<th{th}>layer</th>",
        f"<th{th}>定义路径 / 引用位置</th>",
        f"<th{th}>PR</th>",
        f"<th{th}>in°</th>",
        f"<th{th}>out°</th>",
        "</tr></thead>",
        "<tbody>",
    ]
    for rank, fn in enumerate(top_k, 1):
        info = classified.get(fn, {})
        kind_zh = _KIND_LABEL_ZH.get(_resolve_symbol_kind(info), "未知")
        path_cell = html.escape(_svg_node_sub_line(info))
        lines.append(
            "<tr>"
            f"<td{td}><code>{html.escape(fn)}</code></td>"
            f"<td{td}>{html.escape(kind_zh)}</td>"
            f"<td{td}>{html.escape(str(info.get('domain', '?')))}</td>"
            f"<td{td}>{html.escape(str(info.get('layer', '?')))}</td>"
            f"<td{td}><code style='white-space:pre-wrap;word-break:break-all'>{path_cell}</code></td>"
            f"<td{td}>#{rank}</td>"
            f"<td{td}>{info.get('in_degree', 0)}</td>"
            f"<td{td}>{info.get('out_degree', 0)}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")
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

    th = ' style="text-align:left;padding:6px 10px;border:1px solid #ddd;background:#f6f8fa"'
    td = ' style="text-align:left;padding:6px 10px;border:1px solid #ddd;vertical-align:top"'
    lines = [
        '<table style="border-collapse:collapse;width:auto;max-width:100%;table-layout:auto">',
        "<thead><tr>",
        f"<th{th}>源文件</th>",
        f"<th{th}>domain</th>",
        f"<th{th}>调用的文件（权重）</th>",
        "</tr></thead>",
        "<tbody>",
    ]
    for src in sorted(FG.nodes()):
        targets = sorted(FG.successors(src),
                         key=lambda d: FG[src][d].get("weight", 0), reverse=True)
        if not targets:
            continue
        target_str = ", ".join(
            f"{os.path.basename(t)}×{FG[src][t].get('weight', 1)}"
            for t in targets[:5]
        )
        src_disp = html.escape((src or "").replace("\\", "/"))
        lines.append(
            "<tr>"
            f"<td{td}><code style='white-space:pre-wrap;word-break:break-all'>{src_disp}</code></td>"
            f"<td{td}>{html.escape(str(_fd(src)))}</td>"
            f"<td{td}>{html.escape(target_str)}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _compose_callgraph_markdown(
    G: nx.DiGraph,
    FG: nx.DiGraph,
    fn_meta: Dict[str, dict],
    top_k_nodes: List[str],
    top_k: int,
    classified: Dict[str, dict],
    figure_block: str,
    semantic_note: str = "",
) -> str:
    """拼装 Call Graph 章节 Markdown（figure_block 为 SVG 引用或 base64）。"""
    sem_line = (
        f"> {semantic_note}\n>\n"
        if semantic_note
        else ""
    )
    return f"""## Call Graph 概览


### 函数级 Call Graph（PageRank Top-{top_k}，图示 {len(top_k_nodes)} 个函数）

{figure_block}


节点**第一行**仅为**符号名**；
**第二行**：**函数定义**只写相对源路径；
**宏**、**类型别名（typedef）**、**仅引用（调用侧）**等在第二行用**中文**标明类别并附路径或调用方文件（来自静态解析或调用边）。


"""


def _callgraph_subbanner() -> str:
    """与 os_agent_d_describe 各阶段内的 ━ 分段风格一致。"""
    return "━" * 22 + " Call Graph 概览块 " + "━" * 22


def _resolve_lsp_max_depth(explicit: Optional[int]) -> int:
    """参数或默认常量，限制在 1～5。"""
    if explicit is not None:
        return max(1, min(5, int(explicit)))
    return LSP_REFINE_MAX_DEPTH_DEFAULT


def generate_callgraph_section(
    repo_path: str,
    output_dir: str,
    top_k: int = 30,
    lsp_refine: bool = True,
    use_embedding: bool = True,  # 保留参数兼容旧调用，已不使用
    force_regenerate: bool = False,
    lsp_max_depth: Optional[int] = None,
) -> Tuple[str, int]:
    """
    生成完整的 Call Graph 报告块（Markdown + SVG）。
    返回 ``(markdown 字符串, domain×layer LLM 消耗的 total_tokens)``；缓存命中或未调用 LLM 时第二项为 0。

    缓存（output_dir 下）：
      - ``callgraph_overview.svg``、``callgraph_overview.md``、``callgraph_overview_meta.json``

    **输入指纹**：``compile_flags.txt`` / ``compile_commands.json``、git HEAD、语义管线版本、
    ``lsp_max_depth`` / ``top_k``、libclang 可用性；与 ``meta.json`` 一致则命中缓存，**无需**环境变量。

    **语义过滤**：对 C/C++ 用 Clang AST 剔除条件编译未进入 TU 的函数节点（需 ``pip install clang`` 与系统 libclang）。

    **强制重算**：仅 ``force_regenerate=True``（API），用于调试或忽略缓存。
    """
    md_path = os.path.join(output_dir, CALLGRAPH_MD_FILENAME)
    meta_path = os.path.join(output_dir, CALLGRAPH_META_FILENAME)
    depth_use = _resolve_lsp_max_depth(lsp_max_depth)
    input_fp = compute_input_fingerprint(
        repo_path, lsp_depth=depth_use, top_k=top_k
    )

    if force_regenerate:
        print("\n" + _callgraph_subbanner())
        print("=" * 80)
        print("🔄 Call Graph：强制重算（忽略 callgraph_overview 缓存）")
        print("=" * 80)
        sys.stdout.flush()

    # 指纹命中则直接返回 md（旧版无 input_fingerprint 的 meta 视为失效）
    if not force_regenerate and os.path.exists(md_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as mf:
                meta = json.load(mf)
            if (
                meta.get("cache_version") == CALLGRAPH_CACHE_VERSION
                and meta.get("input_fingerprint")
                and meta.get("input_fingerprint") == input_fp
            ):
                with open(md_path, "r", encoding="utf-8") as f:
                    md = f.read()
                if md.strip():
                    fn_n = meta.get("fn_count", "?")
                    e_n = meta.get("edge_count", "?")
                    print("\n" + _callgraph_subbanner())
                    print("=" * 80)
                    print("⏭️  Call Graph：缓存命中（输入指纹未变），未重新扫描仓库")
                    print(f"   章节文件: {md_path}")
                    print(f"   上次统计: {fn_n} 个节点, {e_n} 条边（见 meta.json）")
                    print("=" * 80)
                    sys.stdout.flush()
                    return md, 0
        except Exception:
            pass

    print("\n" + _callgraph_subbanner())
    print("=" * 80)
    print("📦 Call Graph 概览块（附于全部章节完成之后）")
    print("   作用：用 PageRank 与 domain 分类为评委提供该参赛 OS 的「枢纽符号」与调用关系鸟瞰。")
    print("   全量重建时：每次从头遍历仓库源码并建图，不沿用 callgraph 目录以外的图缓存。")
    print(f"   仓库路径: {repo_path}")
    print("=" * 80)
    sys.stdout.flush()

    # Step 1-3: 构建 DiGraph
    G, fn_meta = build_digraph(repo_path)
    if G.number_of_nodes() == 0:
        return "> ⚠️  Call Graph 构建失败：未检测到函数\n", 0

    print(
        f"   [CallGraph 1/6] Tree-sitter 扫描完成: {G.number_of_nodes()} 个符号节点, "
        f"{G.number_of_edges()} 条边（单文件内调用关系，同名合并为单节点）"
    )

    active_by_file, parsed_ok, _sem_used, sem_msg = collect_active_functions_by_file(
        repo_path, fn_meta
    )
    pruned_n = apply_semantic_prune_inactive_functions(
        G, fn_meta, active_by_file, parsed_ok
    )
    semantic_note = ""
    if pruned_n:
        semantic_note = (
            f"Clang 语义过滤已移除 {pruned_n} 个在条件编译下未进入翻译单元的 C/C++ 函数节点"
            f"（{sem_msg}）。"
        )
        print(
            f"   [CallGraph 1b/6] {semantic_note} "
            f"当前 {G.number_of_nodes()} 节点, {G.number_of_edges()} 边"
        )
    else:
        print(f"   [CallGraph 1b/6] Clang 语义：{sem_msg}")
        if sem_msg and "跳过" not in sem_msg:
            semantic_note = sem_msg + "。"

    if G.number_of_nodes() == 0:
        return (
            "> ⚠️  Call Graph 构建失败：图中无节点（语义过滤后为空，请检查 libclang 与 compile 配置）\n",
            0,
        )

    # Step 4: PageRank Top-k
    pr = nx.pagerank(G, alpha=0.85, max_iter=200) if G.number_of_nodes() > 0 else {}
    nx.set_node_attributes(G, pr, "pagerank")
    top_k_nodes = select_top_k_pagerank(G, k=top_k)
    print(
        f"   [CallGraph 2/6] PageRank 选出 Top-{len(top_k_nodes)} 个枢纽（图与表仅展示这些节点，"
        f"不是全库）"
    )
    print(f"   可调参数 top_k={top_k}，在 os_agent_d_describe.py 的 generate_callgraph_section(top_k=...) 修改")

    # Step 5: LSP 精化
    edges_before_lsp = G.number_of_edges()
    refined_n = 0
    if lsp_refine:
        lim = min(30, len(top_k_nodes))
        print(
            f"   [CallGraph 3/6] LSP callHierarchy 精化前 {lim} 个枢纽的跨文件调用边，"
            f"递归深度 max_depth={depth_use}（范围 1～5，可用参数 lsp_max_depth 覆盖）"
        )
        refined_n = refine_with_lsp(
            G, fn_meta, repo_path, top_k_nodes, limit=lim, max_depth=depth_use
        )
        print(
            f"   LSP 成功精化节点数: {refined_n}；边数 {edges_before_lsp} -> {G.number_of_edges()}"
        )
        if refined_n == 0:
            print(
                "   说明：精化数为 0 时常见原因包括缺少 compile_commands.json、"
                "clangd 未索引该工程，或符号不在 LSP 可解析的语义范围内；"
                "图中仍以 Tree-sitter 单文件内边为主。"
            )
    else:
        print("   [CallGraph 3/6] 已跳过 LSP 精化 (lsp_refine=False)")

    _backfill_fn_meta_refs(G, fn_meta)

    print("   [CallGraph 4/6] domain×layer 分类（LLM）")
    classified, cg_llm_tokens = classify_nodes(
        top_k_nodes, G, fn_meta, repo_path=repo_path
    )
    dc = Counter(info.get("domain", "?") for info in classified.values())
    print(
        "   分类结果 domain 分布: "
        + ", ".join(f"{k}={v}" for k, v in dc.most_common(8))
    )

    # Step 8: 文件级图
    FG = build_file_graph(G, top_k_nodes, fn_meta)
    print("   [CallGraph 5/6] 渲染 SVG 网格图并拼装 Markdown（含文件级表与枢纽表）")

    # Step 9: SVG + 表格
    fn_svg   = render_svg(top_k_nodes, classified, G)
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
    ) if False else ""  # 文件级改用表格，SVG节点太多

    figure_block = _svg_embed_markdown(CALLGRAPH_SVG_FILENAME)
    markdown = _compose_callgraph_markdown(
        G,
        FG,
        fn_meta,
        top_k_nodes,
        top_k,
        classified,
        figure_block,
        semantic_note=semantic_note,
    )

    try:
        os.makedirs(output_dir, exist_ok=True)
        svg_path = os.path.join(output_dir, CALLGRAPH_SVG_FILENAME)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(fn_svg)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        meta_path = os.path.join(output_dir, CALLGRAPH_META_FILENAME)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "cache_version": CALLGRAPH_CACHE_VERSION,
                    "input_fingerprint": input_fp,
                    "k_param": top_k,
                    "lsp_max_depth": depth_use,
                    "fn_count": G.number_of_nodes(),
                    "edge_count": G.number_of_edges(),
                    "top_k": top_k_nodes,
                    "classified": _classified_for_meta(classified),
                    "semantic_pruned_nodes": pruned_n,
                    "semantic_message": sem_msg,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"   [CallGraph 6/6] 已写入输出目录")
        print(f"      {svg_path}")
        print(f"      {md_path}")
        print(f"      {meta_path}")
    except Exception as e:
        logger.warning(f"[CallGraph] 缓存写入失败: {e}")

    print("   Call Graph 概览块就绪（内容已并入总报告前的独立章节文件）")
    print("=" * 80)
    sys.stdout.flush()
    return markdown, cg_llm_tokens
