"""CodeAtlasBuilder（无 LLM）。

输入: 仓库源码
输出: code_atlas.json
    {
      "schema_version": "code_atlas_v1",
      "repo_meta": {...},
      "stats": {...},
      "functions": { fn_id: {...} },
      "types":     { type_id: {...} },
      "edges":     [ {src_fn_id, dst_fn_id?, callee_name, callsite_*} ],
      "_lineage":  {...}
    }

流程:
  1. tree-sitter 全仓库扫描   → extractor.extract_repo
  2. 函数 normalized tokens   → normalize.normalize_function_tokens
  3. AST shape merkle hash    → ast_shape.ast_shape_hash
  4. 字面量集合 (literal_set)  → 简易扫描函数体里的字面量节点
  5. 调用边 callee → fn_id 解析（同名歧义保留所有候选）
  6. PageRank
  7. 落 code_atlas.json + _lineage

不依赖 LLM。所有"分数"特征都在这一阶段产出。
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import asdict
from typing import Optional

import networkx as nx

from core.code_atlas.lineage import attach_lineage, make_lineage
from core.code_atlas.config import (
    PAGERANK_ALPHA,
    PAGERANK_MAX_ITER,
    PAGERANK_TOL,
)
from tools.code_atlas.ast_shape import ast_shape_hash
from tools.code_atlas.extractor import (
    CallEdge,
    FileExtraction,
    FunctionRecord,
    TypeRecord,
    extract_repo,
)
from tools.code_atlas.normalize import normalize_function_tokens

logger = logging.getLogger(__name__)


# ─── 字面量抽取（给 L1 literal_minhash 用）──────────────────────


_LITERAL_NODE_TYPES = frozenset({
    "number_literal", "integer_literal", "float_literal",
    "string_literal", "raw_string_literal", "concatenated_string",
    "char_literal", "boolean_literal",
    "interpreted_string_literal",
})


def _extract_literal_set(fn_node, code_bytes: bytes) -> list[str]:
    """收集函数体内所有字面量的去空白文本。

    给 L1 literal_minhash 用：同函数 + 用同样的常量集合 → 高 jaccard。
    """
    literals: set[str] = set()

    def visit(node):
        if node.type in _LITERAL_NODE_TYPES:
            text = code_bytes[node.start_byte:node.end_byte].decode(
                "utf-8", errors="ignore"
            ).strip()
            if text and len(text) <= 200:
                literals.add(text)
            return
        for c in node.children:
            visit(c)

    visit(fn_node)
    return sorted(literals)


# ─── 边 callee 解析（同名歧义保留多候选）────────────────────────


def _resolve_edges(
    edges: list[CallEdge],
    name_to_fn_ids: dict[str, list[str]],
) -> list[dict]:
    """把 callee_name 解析成 dst_fn_id 或 dst_candidates。"""
    resolved = []
    for e in edges:
        candidates = name_to_fn_ids.get(e.callee_name, [])
        rec = {
            "src_fn_id": e.src_fn_id,
            "callee_name": e.callee_name,
            "callsite_file": e.callsite_file,
            "callsite_line": e.callsite_line,
        }
        if len(candidates) == 1:
            rec["dst_fn_id"] = candidates[0]
            rec["resolution"] = "unique"
        elif len(candidates) > 1:
            rec["dst_fn_id"] = None
            rec["dst_candidates"] = candidates
            rec["resolution"] = "ambiguous"
        else:
            rec["dst_fn_id"] = None
            rec["resolution"] = "external"
        resolved.append(rec)
    return resolved


# ─── PageRank ────────────────────────────────────────────────


def _compute_pagerank(
    fn_ids: list[str],
    edges_resolved: list[dict],
) -> dict[str, dict]:
    """返回 fn_id → {pagerank, in_degree, out_degree}。"""
    G = nx.DiGraph()
    G.add_nodes_from(fn_ids)
    for e in edges_resolved:
        dst = e.get("dst_fn_id")
        if dst:
            G.add_edge(e["src_fn_id"], dst)

    if G.number_of_edges() == 0:
        # 全是孤立节点 → pagerank 退化为均匀分布
        n = max(1, G.number_of_nodes())
        pr = {fn_id: 1.0 / n for fn_id in fn_ids}
    else:
        try:
            pr = nx.pagerank(
                G,
                alpha=PAGERANK_ALPHA,
                tol=PAGERANK_TOL,
                max_iter=PAGERANK_MAX_ITER,
            )
        except Exception as exc:
            logger.warning("[D-1] pagerank 失败 (%s)，用均匀分布兜底", exc)
            n = max(1, G.number_of_nodes())
            pr = {fn_id: 1.0 / n for fn_id in fn_ids}

    return {
        fn_id: {
            "pagerank": pr.get(fn_id, 0.0),
            "in_degree": G.in_degree(fn_id) if fn_id in G else 0,
            "out_degree": G.out_degree(fn_id) if fn_id in G else 0,
        }
        for fn_id in fn_ids
    }


# ─── 主入口 ────────────────────────────────────────────────


def build_code_atlas(
    *,
    repo_path: str,
    repo_name: Optional[str] = None,
    progress_cb=None,
) -> dict:
    """主入口。返回 code_atlas dict（已含 _lineage，可直接 json.dump）。

    progress_cb(stage, info) 用来上报进度，None = 安静。
    """
    started = time.time()
    repo_name = repo_name or os.path.basename(os.path.normpath(repo_path))

    if progress_cb:
        progress_cb("scan_start", {"repo": repo_name})

    # 1. tree-sitter 抽取
    extractions, code_cache = extract_repo(
        repo_path,
        progress_cb=lambda f, l, n_fn, n_e: progress_cb(
            "file", {"file": f, "lang": l, "fns": n_fn, "edges": n_e}
        ) if progress_cb else None,
    )

    # 2. 收集所有函数 + 名字索引（给边解析和 normalize 用）
    all_functions: list[FunctionRecord] = []
    fn_id_to_record: dict[str, FunctionRecord] = {}
    fn_id_to_node: dict[str, object] = {}
    fn_id_to_code_bytes: dict[str, bytes] = {}
    name_to_fn_ids: dict[str, list[str]] = defaultdict(list)
    all_types: list[TypeRecord] = []
    type_id_to_record: dict[str, TypeRecord] = {}
    all_edges: list[CallEdge] = []
    file_lang_count: dict[str, int] = defaultdict(int)

    for ext in extractions:
        file_lang_count[ext.lang] += 1
        for fn in ext.functions:
            all_functions.append(fn)
            fn_id_to_record[fn.fn_id] = fn
            fn_id_to_node[fn.fn_id] = ext.fn_nodes_by_id[fn.fn_id]
            fn_id_to_code_bytes[fn.fn_id] = code_cache[fn.file]
            name_to_fn_ids[fn.name].append(fn.fn_id)
        for t in ext.types:
            # 同名 type 在多文件出现是常见情况（forward decl）
            # 用 type_id 已经按 (file:line:name:kind) 唯一化，全部入库
            all_types.append(t)
            type_id_to_record[t.type_id] = t
        all_edges.extend(ext.edges)

    if progress_cb:
        progress_cb("scan_done", {
            "files": len(extractions),
            "fns": len(all_functions),
            "types": len(all_types),
            "edges": len(all_edges),
        })

    # 3. 收集"全局保留名"（normalize 时不 alpha-rename）
    #   - 函数名（任意函数）→ caller/callee 文本对齐用
    #   - 类型名
    keep_names: set[str] = set()
    for fn in all_functions:
        keep_names.add(fn.name)
    for t in all_types:
        keep_names.add(t.name)

    # 4. 每函数算 normalize tokens + ast_shape_hash + literal_set
    fn_features: dict[str, dict] = {}
    for fn in all_functions:
        fn_node = fn_id_to_node[fn.fn_id]
        cb = fn_id_to_code_bytes[fn.fn_id]
        try:
            tokens = normalize_function_tokens(
                fn_node, cb, keep_text_identifiers=keep_names,
            )
        except Exception as exc:
            logger.warning("[D-1] normalize fail %s: %s", fn.fn_id, exc)
            tokens = []
        try:
            shape = ast_shape_hash(fn_node)
        except Exception as exc:
            logger.warning("[D-1] ast_shape fail %s: %s", fn.fn_id, exc)
            shape = "ERROR"
        try:
            literals = _extract_literal_set(fn_node, cb)
        except Exception as exc:
            logger.warning("[D-1] literal_set fail %s: %s", fn.fn_id, exc)
            literals = []
        fn_features[fn.fn_id] = {
            "tokens_normalized": tokens,
            "ast_shape_hash": shape,
            "literal_set": literals,
        }

    if progress_cb:
        progress_cb("features_done", {"fns_with_tokens": len(fn_features)})

    # 5. 边解析（callee_name → dst_fn_id）
    edges_resolved = _resolve_edges(all_edges, name_to_fn_ids)
    edge_stats = {
        "unique": sum(1 for e in edges_resolved if e["resolution"] == "unique"),
        "ambiguous": sum(1 for e in edges_resolved if e["resolution"] == "ambiguous"),
        "external": sum(1 for e in edges_resolved if e["resolution"] == "external"),
    }

    if progress_cb:
        progress_cb("edges_resolved", edge_stats)

    # 6. PageRank
    fn_ids = [fn.fn_id for fn in all_functions]
    pr_info = _compute_pagerank(fn_ids, edges_resolved)

    if progress_cb:
        progress_cb("pagerank_done", {})

    # 7. 组装产物
    functions_out: dict[str, dict] = {}
    for fn in all_functions:
        feat = fn_features.get(fn.fn_id, {})
        pr = pr_info.get(fn.fn_id, {})
        functions_out[fn.fn_id] = {
            "name": fn.name,
            "file": fn.file,
            "line": fn.line,
            "end_line": fn.end_line,
            "lang": fn.lang,
            "signature": fn.signature,
            "body_text": fn.body_text,         # 给后续 D-2 LLM 用
            "body_len_bytes": fn.body_len_bytes,
            "tokens_normalized": feat.get("tokens_normalized", []),
            "ast_shape_hash": feat.get("ast_shape_hash"),
            "literal_set": feat.get("literal_set", []),
            "pagerank": pr.get("pagerank", 0.0),
            "in_degree": pr.get("in_degree", 0),
            "out_degree": pr.get("out_degree", 0),
            # 后续 phase 填:
            "fine_grained_role": None,           # D-2 FunctionRoleAgent 写
            "l1_module": None, "l2_module": None,  # D-3 ModuleBuilderAgent 写
        }

    types_out: dict[str, dict] = {}
    for t in all_types:
        types_out[t.type_id] = {
            "name": t.name, "kind": t.kind,
            "file": t.file, "line": t.line, "end_line": t.end_line, "lang": t.lang,
            "fields": t.fields,
            "l2_module": None,                   # D-3 写
        }

    # repo meta
    commit_hash = None
    head_file = os.path.join(repo_path, ".git", "HEAD")
    if os.path.isfile(head_file):
        try:
            with open(head_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content.startswith("ref:"):
                ref = os.path.join(repo_path, ".git", content[4:].strip())
                if os.path.isfile(ref):
                    with open(ref, "r", encoding="utf-8") as rf:
                        commit_hash = rf.read().strip()
            else:
                commit_hash = content
        except OSError:
            pass

    elapsed = time.time() - started

    atlas = {
        "schema_version": "code_atlas_v1",
        "repo_meta": {
            "name": repo_name,
            "path": os.path.abspath(repo_path),
            "commit_hash": commit_hash,
            "lang_distribution": dict(file_lang_count),
        },
        "stats": {
            "files": len(extractions),
            "function_count": len(all_functions),
            "type_count": len(all_types),
            "edge_count": len(edges_resolved),
            "edge_resolution": edge_stats,
            # build_seconds 不放这里 —— 时间是噪声，会破坏产物 byte-level 可复现。
            # 放到 _lineage.extra_meta 里。
        },
        "functions": functions_out,
        "types": types_out,
        "edges": edges_resolved,
    }

    lineage = make_lineage(
        repo_path=repo_path,
        llm_model=None,           # D-1 不调 LLM
        llm_calls_total=0,
        llm_miss_rate=None,
        extra_meta={
            "phase": "D-1", "agent": "CodeAtlasAgent",
            "build_seconds": round(elapsed, 2),
        },
    )
    attach_lineage(atlas, lineage)

    if progress_cb:
        progress_cb("done", {"elapsed": round(elapsed, 2)})

    return atlas


def run_code_atlas_for_repo(
    repo_path: str,
    *,
    output_dir: str,
    repo_name: Optional[str] = None,
    progress_cb=None,
) -> str:
    """运行 D-1 并落盘到 <output_dir>/code_atlas.json，返回路径。"""
    atlas = build_code_atlas(
        repo_path=repo_path, repo_name=repo_name, progress_cb=progress_cb,
    )
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "code_atlas.json")
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(atlas, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)
    return out_path
