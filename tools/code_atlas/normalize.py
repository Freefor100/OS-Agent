"""token normalize（pipeline_config.NORMALIZE_VER = "v1"）。

输入: 函数体 tree-sitter Node + 语言名
输出: 一个 token 字符串列表，给 L1 token_minhash 用

规则（pipeline_config.NORMALIZE_RULES）:
  1. 去注释 → 完全跳过 comment / line_comment / block_comment
  2. 局部变量 alpha-rename → V0/V1/...，全局符号、函数名、类型名保留原文
  3. 字面量占位 → 数字 N，字符串 S，字符 C
  4. 关键字保留
  5. 空白统一压缩（输出列表本身就不含空白）

判断"局部变量"的近似规则（不依赖完整类型推断）:
  - declaration / parameter_declaration / let_declaration 内引入的 identifier 即"局部"
  - 函数 body 范围内首次出现的 identifier 是局部的可能性高
  → 取折中: 在函数内部，所有 identifier 默认局部 alpha-rename；
    例外集合（函数名、type 名、宏名）保留原文 —— 由调用方传入 keep_set
  - 跨函数引用的 identifier (call expression 的 callee) 必须保留原文（callee_name 抽边用）

跨语言通用：用 tree-sitter 的 node.type 作为 token 来源，identifier 类型节点参与重命名，
其他节点直接拿 node.type（'(' ')' '{' 'if' '+' 等结构 token）。

可复现:
  - 同输入同输出（不依赖随机数）
  - 没有外部依赖
"""

from __future__ import annotations

from typing import Iterable

from core.code_atlas.config import NORMALIZE_VER


# ─── 节点类型分类 ───────────────────────────────────────────


# 跳过的节点（不入 token 序列）
_SKIP_TYPES = frozenset({
    "comment", "line_comment", "block_comment",
})

# 字面量类型 → 占位符
_LITERAL_PLACEHOLDERS = {
    # C/C++
    "number_literal":  "N",
    "string_literal":  "S",
    "char_literal":    "C",
    "raw_string_literal": "S",
    "concatenated_string": "S",
    # Rust
    "integer_literal": "N",
    "float_literal":   "N",
    "boolean_literal": "B",
    # Go
    "int_literal":     "N",
    "float_literal_go": "N",          # 占位避免冲突
    "interpreted_string_literal": "S",
    "raw_string_literal_go": "S",
}


# identifier 节点类型（参与 alpha-rename）
_IDENTIFIER_TYPES = frozenset({
    "identifier",
    "field_identifier",
    "type_identifier",     # 类型名也参与重命名（很多教学 OS 习惯把 struct 起短名）
    "primitive_type",      # int / void —— 不重命名，直接用文本
})

# 这些 identifier 类型保留原文不 rename
_KEEP_TEXT_IDENTIFIER_TYPES = frozenset({
    "primitive_type",      # int / char / void
})


# ─── 主流程 ─────────────────────────────────────────────────


def normalize_function_tokens(
    fn_node,
    code_bytes: bytes,
    *,
    keep_text_identifiers: Iterable[str] = (),
) -> list[str]:
    """从一个函数的 tree-sitter Node 抽出 normalized token 列表。

    keep_text_identifiers: 不参与 alpha-rename 的 identifier 集合（如全局符号、
    被调函数名、类型名）。调用方在 atlas extractor 里收集所有函数名/类型名传进来。
    """
    keep = set(keep_text_identifiers)
    var_map: dict[str, str] = {}     # 原始名 → V{n}
    next_var = [0]

    tokens: list[str] = []

    def emit(tok: str) -> None:
        if tok:
            tokens.append(tok)

    def visit(node) -> None:
        ntype = node.type
        if ntype in _SKIP_TYPES:
            return

        # 字面量
        if ntype in _LITERAL_PLACEHOLDERS:
            emit(_LITERAL_PLACEHOLDERS[ntype])
            return

        # identifier
        if ntype in _IDENTIFIER_TYPES:
            text = code_bytes[node.start_byte:node.end_byte].decode(
                "utf-8", errors="ignore"
            )
            if ntype in _KEEP_TEXT_IDENTIFIER_TYPES or text in keep:
                emit(text)
            else:
                renamed = var_map.get(text)
                if renamed is None:
                    renamed = f"V{next_var[0]}"
                    next_var[0] += 1
                    var_map[text] = renamed
                emit(renamed)
            return

        # 叶子节点（括号、分号、关键字）
        if not node.children:
            # 关键字 / 标点：直接用 node.type 作为 token（跨语言通用）
            # 例外：单字符标点 type 就是字符本身（'(' '{' ';'）—— 也直接用
            emit(ntype)
            return

        # 内部节点：不 emit 自己，递归子节点
        for c in node.children:
            visit(c)

    visit(fn_node)
    return tokens


def algorithm_version() -> str:
    return NORMALIZE_VER
