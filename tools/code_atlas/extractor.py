"""tree-sitter 抽取：函数、类型、调用边。

借鉴 callgraph_overview._parse_file 的思路，但：
- fn_id = sha256(file:line:name) 解决同名碰撞（不像旧实现 fn_meta dict 第一个胜出）
- 跨语言节点类型表统一
- 边 callee 名先收集，dst_fn_id 在 atlas 组装阶段批量解析
- 函数体 body_text 也保留，给 LLM 后续 D-2/D-3 用
- 类型抽取（struct/enum/trait/impl/typedef）—— 旧实现只抽了 typedef 和宏

设计书 §6.2-6.4 / 7.2 对应。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# ─── 各语言节点类型表 ────────────────────────────────────────


_FN_DEF_TYPES = {
    "c":    {"function_definition"},
    "cpp":  {"function_definition"},
    "rust": {"function_item"},
    "go":   {"function_declaration", "method_declaration"},
    "zig":  {"function_declaration"},
}

_FN_SIGNATURE_TYPES = {
    # 仅声明无定义的（trait method 头），不入函数表
    "rust": {"function_signature_item"},
}

_TYPE_DEF_TYPES = {
    "c":    {"struct_specifier", "enum_specifier", "type_definition"},
    "cpp":  {"struct_specifier", "enum_specifier", "class_specifier", "type_definition"},
    "rust": {"struct_item", "enum_item", "trait_item", "type_item", "union_item"},
    "go":   {"type_declaration"},
    "zig":  {"type_definition"},
}

_CALL_EXPR_TYPES = {
    "c":    {"call_expression"},
    "cpp":  {"call_expression"},
    "rust": {"call_expression", "macro_invocation"},
    "go":   {"call_expression"},
    "zig":  {"call_expression"},
}


_KEYWORD_SKIP = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "match", "return", "break", "continue", "loop",
    "let", "const", "static", "fn", "func", "use", "pub", "mod", "package",
    "unsafe", "async", "await", "extern",
    "struct", "enum", "union", "trait", "impl", "type", "typedef",
    "self", "Self", "super",
    "true", "false", "null", "nil", "None", "Some", "Ok", "Err",
    "println", "print", "format", "panic", "assert", "todo", "unimplemented",
    "dbg", "write", "writeln",
    "sizeof", "typeof", "alignof",
})


# ─── 数据结构 ────────────────────────────────────────────────


@dataclass
class FunctionRecord:
    fn_id: str
    name: str
    file: str           # rel path
    line: int
    end_line: int
    lang: str
    signature: str
    body_text: str
    body_len_bytes: int
    raw_node_id: int = 0    # 进程内唯一，给后续 normalize/ast_shape 用


@dataclass
class TypeRecord:
    type_id: str
    name: str
    kind: str       # struct / enum / trait / impl / typedef / class / union
    file: str
    line: int
    end_line: int
    lang: str
    fields: list[str] = field(default_factory=list)


@dataclass
class CallEdge:
    src_fn_id: str
    callee_name: str    # 文本，dst_fn_id 在 atlas 组装阶段解析
    callsite_file: str
    callsite_line: int


@dataclass
class FileExtraction:
    """单文件解析产出。"""
    file: str
    lang: str
    functions: list[FunctionRecord] = field(default_factory=list)
    types: list[TypeRecord] = field(default_factory=list)
    edges: list[CallEdge] = field(default_factory=list)
    # fn_id → fn_node（tree-sitter Node，同进程内有效）。下游 D-1 主函数会用它跑
    # ast_shape 和 normalize_function_tokens；同进程跑完即可丢弃。
    fn_nodes_by_id: dict = field(default_factory=dict)


# ─── 工具函数 ────────────────────────────────────────────────


def _make_fn_id(file: str, line: int, name: str) -> str:
    return "fn_" + hashlib.sha256(
        f"{file}:{line}:{name}".encode("utf-8")
    ).hexdigest()[:16]


def _make_type_id(file: str, line: int, name: str, kind: str) -> str:
    return "ty_" + hashlib.sha256(
        f"{file}:{line}:{name}:{kind}".encode("utf-8")
    ).hexdigest()[:16]


def _walk(node, types: set, callback):
    """前序遍历，对每个 type ∈ types 的节点调 callback(node)，不进入它的子节点。"""
    if node.type in types:
        callback(node)
        return
    for c in node.children:
        _walk(c, types, callback)


def _walk_into(node, types: set, callback):
    """像 _walk 但遍历进入匹配节点（找子树里的 call 时用）。"""
    if node.type in types:
        callback(node)
    for c in node.children:
        _walk_into(c, types, callback)


def _node_text(node, code_bytes: bytes) -> str:
    return code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _find_first_identifier(node, code_bytes: bytes) -> Optional[str]:
    """在子树里找第一个 identifier 节点的文本。"""
    if node.type in ("identifier", "field_identifier", "type_identifier"):
        return _node_text(node, code_bytes)
    for c in node.children:
        r = _find_first_identifier(c, code_bytes)
        if r is not None:
            return r
    return None


def _extract_fn_name(fn_node, code_bytes: bytes, lang: str) -> Optional[str]:
    """各语言找函数名的简化规则。"""
    if lang in ("c", "cpp"):
        # function_definition → function_declarator → identifier
        for c in fn_node.children:
            if c.type == "function_declarator":
                # field_identifier 在 cpp 里也算
                return _find_first_identifier(c, code_bytes)
            # cpp 里有时是 reference_declarator → function_declarator
            if c.type in ("reference_declarator", "pointer_declarator"):
                return _find_first_identifier(c, code_bytes)
        return None
    if lang == "rust":
        # function_item → 'fn' identifier
        for i, c in enumerate(fn_node.children):
            if c.type == "identifier":
                return _node_text(c, code_bytes)
        return None
    if lang == "go":
        # function_declaration → 'func' identifier
        # method_declaration → 'func' parameter_list field_identifier parameter_list ...
        for c in fn_node.children:
            if c.type == "identifier" or c.type == "field_identifier":
                return _node_text(c, code_bytes)
        return None
    if lang == "zig":
        for c in fn_node.children:
            if c.type == "identifier":
                return _node_text(c, code_bytes)
    return None


def _extract_type_name_kind(type_node, code_bytes: bytes, lang: str) -> Optional[tuple[str, str]]:
    """返回 (name, kind)，无法识别返回 None。kind ∈ struct/enum/trait/typedef/impl/class/union/type"""
    nt = type_node.type
    if lang in ("c", "cpp"):
        if nt == "struct_specifier":
            n = _find_first_identifier(type_node, code_bytes)
            return (n, "struct") if n else None
        if nt == "enum_specifier":
            n = _find_first_identifier(type_node, code_bytes)
            return (n, "enum") if n else None
        if nt == "class_specifier":
            n = _find_first_identifier(type_node, code_bytes)
            return (n, "class") if n else None
        if nt == "type_definition":
            # typedef ... NAME ;  → 取最后一个 identifier
            last_id = None
            def walk(n):
                nonlocal last_id
                if n.type in ("type_identifier", "identifier"):
                    last_id = _node_text(n, code_bytes)
                for c in n.children:
                    walk(c)
            walk(type_node)
            return (last_id, "typedef") if last_id else None
    if lang == "rust":
        kind_map = {
            "struct_item": "struct",
            "enum_item":   "enum",
            "trait_item":  "trait",
            "type_item":   "typedef",
            "union_item":  "union",
        }
        kind = kind_map.get(nt)
        if not kind:
            return None
        for c in type_node.children:
            if c.type == "type_identifier":
                return (_node_text(c, code_bytes), kind)
        return None
    if lang == "go":
        # type_declaration → type_spec → type_identifier ...
        for c in type_node.children:
            if c.type == "type_spec":
                for cc in c.children:
                    if cc.type == "type_identifier":
                        # 看下一个兄弟判断是 struct / interface / 普通别名
                        kind = "typedef"
                        for sib in c.children:
                            if sib.type == "struct_type":
                                kind = "struct"; break
                            if sib.type == "interface_type":
                                kind = "interface"; break
                        return (_node_text(cc, code_bytes), kind)
        return None
    return None


def _extract_call_callee(call_node, code_bytes: bytes, lang: str) -> Optional[str]:
    """从 call_expression 抽出 callee 名（最尽力，间接调用返回 None）。"""
    if not call_node.children:
        return None
    callee_node = call_node.children[0]
    if callee_node.type == "identifier":
        return _node_text(callee_node, code_bytes)
    # field expression: a.b()  / scoped: A::b()  / Rust path: a::b
    if callee_node.type in (
        "field_expression",
        "scoped_identifier",
        "selector_expression",
        "scoped_type_identifier",
        "field_access",
    ):
        # 取最后一个 identifier
        last = None
        def walk(n):
            nonlocal last
            if n.type in ("identifier", "field_identifier", "type_identifier"):
                last = _node_text(n, code_bytes)
            for c in n.children:
                walk(c)
        walk(callee_node)
        return last
    if callee_node.type == "macro_invocation":
        # Rust 宏: foo!(...)
        for c in callee_node.children:
            if c.type == "identifier":
                return _node_text(c, code_bytes) + "!"
        return None
    return None


# ─── 主入口 ────────────────────────────────────────────────


def extract_file(
    *,
    abs_path: str,
    rel_path: str,
    lang: str,
    code_bytes: bytes,
    root_node,
) -> FileExtraction:
    """从一棵 parse tree 抽出函数 / 类型 / 调用边。"""
    out = FileExtraction(file=rel_path, lang=lang)

    fn_def_types = _FN_DEF_TYPES.get(lang, set())
    type_def_types = _TYPE_DEF_TYPES.get(lang, set())
    call_types = _CALL_EXPR_TYPES.get(lang, set())

    # 函数收集（不进入函数体内的嵌套 fn —— Rust 有但少见）
    seen_fn_ids = set()
    fn_node_id_to_record: dict[int, FunctionRecord] = {}

    def visit_fn(fn_node):
        name = _extract_fn_name(fn_node, code_bytes, lang)
        if not name or name in _KEYWORD_SKIP:
            return
        line = fn_node.start_point[0] + 1
        end_line = fn_node.end_point[0] + 1
        fn_id = _make_fn_id(rel_path, line, name)
        if fn_id in seen_fn_ids:
            return
        seen_fn_ids.add(fn_id)
        body_bytes = code_bytes[fn_node.start_byte : fn_node.end_byte]
        body_text = body_bytes.decode("utf-8", errors="ignore")
        # signature: 取函数体 { 之前的部分（粗略）
        brace_idx = body_text.find("{")
        signature = body_text[:brace_idx].strip() if brace_idx > 0 else body_text[:120]
        rec = FunctionRecord(
            fn_id=fn_id,
            name=name,
            file=rel_path,
            line=line,
            end_line=end_line,
            lang=lang,
            signature=signature[:400],
            body_text=body_text,
            body_len_bytes=len(body_bytes),
            raw_node_id=id(fn_node),
        )
        out.functions.append(rec)
        fn_node_id_to_record[id(fn_node)] = rec
        out.fn_nodes_by_id[fn_id] = fn_node

        # 抽这个函数体内的调用
        def visit_call(call_node):
            callee = _extract_call_callee(call_node, code_bytes, lang)
            if callee and callee not in _KEYWORD_SKIP:
                out.edges.append(CallEdge(
                    src_fn_id=fn_id,
                    callee_name=callee,
                    callsite_file=rel_path,
                    callsite_line=call_node.start_point[0] + 1,
                ))
        _walk_into(fn_node, call_types, visit_call)

    _walk(root_node, fn_def_types, visit_fn)

    # 类型收集
    seen_type_ids = set()

    def visit_type(type_node):
        info = _extract_type_name_kind(type_node, code_bytes, lang)
        if info is None:
            return
        name, kind = info
        if not name or name in _KEYWORD_SKIP:
            return
        line = type_node.start_point[0] + 1
        end_line = type_node.end_point[0] + 1
        tid = _make_type_id(rel_path, line, name, kind)
        if tid in seen_type_ids:
            return
        seen_type_ids.add(tid)
        out.types.append(TypeRecord(
            type_id=tid, name=name, kind=kind,
            file=rel_path, line=line, end_line=end_line, lang=lang,
        ))

    _walk_into(root_node, type_def_types, visit_type)

    # 注：Rust impl 块内的函数已被前面的 _walk 抓到（visit_fn 进入 function_item）
    # 因为 _walk 不进入匹配节点，但 impl_item 不在 _FN_DEF_TYPES 里，所以会进它
    # 的子树。

    return out, fn_node_id_to_record


# ─── 全仓库扫描 ────────────────────────────────────────────


def extract_repo(
    repo_path: str,
    *,
    progress_cb=None,
) -> tuple[list[FileExtraction], dict[str, bytes]]:
    """遍历仓库所有源文件，返回:

    - 每个文件的 FileExtraction 列表（含 fn_nodes_by_id：fn_id → tree-sitter Node）
    - rel_path → code_bytes（给 normalize/ast_shape 复用，不重复读盘）

    注意：fn_nodes_by_id 的 Node 对象只在本进程有效，不能跨进程复用。
    所以本函数后续的处理（normalize / ast_shape）要在同一进程内完成。
    """
    from tools.code_atlas.ts_loader import walk_source_files, parse_file

    extractions: list[FileExtraction] = []
    code_cache: dict[str, bytes] = {}

    for abs_path, rel_path, lang in walk_source_files(repo_path):
        parsed = parse_file(abs_path)
        if parsed is None:
            continue
        code_bytes, root_node = parsed
        extraction, _ = extract_file(
            abs_path=abs_path, rel_path=rel_path, lang=lang,
            code_bytes=code_bytes, root_node=root_node,
        )
        extractions.append(extraction)
        code_cache[rel_path] = code_bytes
        if progress_cb:
            progress_cb(rel_path, lang, len(extraction.functions), len(extraction.edges))

    return extractions, code_cache
