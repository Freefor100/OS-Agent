"""AST shape merkle hash（pipeline_config.AST_SHAPE_VER = "v1"）。

设计:
    leaf:  hash(node.type)                          # ★ 不要 node.text
    inner: hash(node.type + '|' + ','.join(child_hashes))

性质:
    同结构（无视变量名 / 字面量值）→ 同 hash
    跨语言不同 grammar 即使语义相同也不同 hash（C 的 function_definition vs
    Rust 的 function_item）—— 可接受，跨语言对齐由 fine_grained_role 兜底

可复现:
    - sha256 跨机器一致
    - leaf 不读文本 → 变量重命名 / 字面量值变化不影响 hash
    - delimiter / child_sep 在 pipeline_config 固定

调用方:
    from tools.code_atlas.ast_shape import ast_shape_hash
    fn_hash = ast_shape_hash(fn_node)
"""

from __future__ import annotations

import hashlib

from core.code_atlas.config import AST_SHAPE_RULES, AST_SHAPE_VER


_DELIMITER = AST_SHAPE_RULES["delimiter"]
_CHILD_SEP = AST_SHAPE_RULES["child_sep"]
_HASH_ALGO = AST_SHAPE_RULES["hash_algo"]


def _hasher():
    return hashlib.new(_HASH_ALGO)


def ast_shape_hash(node) -> str:
    """递归 merkle hash 一个 tree-sitter Node。返回 hex 字符串。"""
    children = node.children
    if not children:
        h = _hasher()
        h.update(node.type.encode("utf-8"))
        return h.hexdigest()

    # 跳过纯标点 leaf（{ ; ( ) , 等）会让 hash 噪声大；保留——
    # 实际上同源代码 grammar 输出固定，标点该出现就出现，反而增强结构区分度
    child_hashes = [ast_shape_hash(c) for c in children]
    h = _hasher()
    h.update(node.type.encode("utf-8"))
    h.update(_DELIMITER.encode("utf-8"))
    h.update(_CHILD_SEP.join(child_hashes).encode("utf-8"))
    return h.hexdigest()


def algorithm_version() -> str:
    return AST_SHAPE_VER
