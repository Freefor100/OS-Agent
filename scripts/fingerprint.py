#!/usr/bin/env python3
"""Fingerprint building — pure computation, no judgment, no similarity.

Two fingerprint sources, unified output schema:
  - c / cpp / rust  -> in-memory Git blob tree-sitter parse -> token hash + AST shape hash
  - asm (.S/.s)     -> asm_tokenize label-blocks -> minhash exact-token hash

Unit schema (one dict per code unit, function or asm label-block):
  {
    "lang":  "c"|"cpp"|"rust"|"asm",
    "file":  "rel/path",
    "name":  symbol / label,
    "line":  int,
    "fp":    exact normalized-token hash (str)    # cross-repo identity key
    "sz":    token count (int)                     # for the PEER floor
    "sig":   minhash signature (list[int]) | None  # graded similarity (asm uses it)
  }

Caching: per-repo commit unit list -> .fp_cache/units_*.pkl; fingerprint-only
sets -> .fp_cache/fpset_*.pkl and .fp_cache/astset_*.pkl.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.evidence import stable_id
from core.git_source import iter_source_blobs
from core.snapshot import RepoSnapshot, resolve_snapshot
from tools.code_atlas.ast_shape import ast_shape_hash
from tools.code_atlas.asm_tokenize import tokenize_asm
from tools.code_atlas.extractor import CallEdge, FileExtraction, extract_file
from tools.code_atlas.minhash import signature_from_tokens
from tools.code_atlas.normalize import normalize_function_tokens
from tools.code_atlas.ts_loader import TSLoader, lang_for_path


def _semantic_fn_id(fn: dict) -> str:
    """Stable id from normalized tokens + AST shape — same inputs, same id."""
    tokens = fn.get("tokens_normalized") or fn.get("normalized_tokens") or fn.get("signature") or fn.get("name", "")
    text = " ".join(tokens) if isinstance(tokens, list) else str(tokens)
    return stable_id("sfn", {"tokens": text, "ast": fn.get("ast_shape_hash", "")}, 16)


def _fn_structure_fingerprint(fn: dict) -> dict:
    """Normalized-token fingerprint + AST shape hash for a code unit."""
    tokens = fn.get("tokens_normalized") or fn.get("normalized_tokens") or []
    token_text = " ".join(tokens) if isinstance(tokens, list) else str(tokens)
    literals = fn.get("literal_set") or []
    return {
        "semantic_fn_id": _semantic_fn_id(fn),
        "path": str(fn.get("file", "")).replace("\\", "/"),
        "symbol": fn.get("name", ""),
        "ast_shape_hash": fn.get("ast_shape_hash"),
        "normalized_token_fingerprint": stable_id("ntok", {"tokens": token_text}, 64),
        "literal_fingerprint": stable_id("lit", {"literals": sorted(map(str, literals))}, 16) if literals else "",
    }

CODE_LANGS = ("c", "cpp", "rust")
ASM_MIN_TOK = 12          # asm blocks below this are too generic (save/restore stubs)
CACHE = Path(".fp_cache")
FINGERPRINT_SCHEMA = "fingerprint_v4_sha256_full_token_commit_snapshot"


class FingerprintCacheMissing(RuntimeError):
    pass


def _cache_path(prefix: str, repo_path: str, commit: str = "", tree_hash: str = "") -> Path:
    """Commit-aware cache key. Branch aliases that point to one commit share a cache."""
    name = Path(repo_path).name
    if commit:
        schema_tag = FINGERPRINT_SCHEMA.replace("fingerprint_", "fp-").replace("_", "-")
        return CACHE / f"{prefix}_{name}__{commit[:16]}__{tree_hash[:12] or 'tree-unknown'}__{schema_tag}.pkl"
    return CACHE / f"{prefix}_{name}.pkl"


def _asm_fp(tokens: list[str]) -> str:
    """Exact hash of normalized asm token stream (mirrors the code ntok hash)."""
    return "ntok_" + hashlib.sha256(" ".join(tokens).encode()).hexdigest()


def build_units(repo_path: str, *, branch: str = "", ref: str = "", snapshot: RepoSnapshot | None = None,
                use_cache: bool = True) -> list[dict]:
    """Load prebuilt units for an immutable Git commit snapshot.

    MCP search and comparison must not rebuild fingerprints implicitly. Run
    scripts/run.py --build, or call build_units_from_git_commit explicitly.
    """
    snap = snapshot or resolve_snapshot(repo_path, ref or branch or "HEAD")
    cf = _cache_path("units", repo_path, snap.commit, snap.tree_hash)
    if use_cache and cf.exists():
        return _load_units_cache(str(cf.resolve()), *_cache_stat(cf))
    raise FingerprintCacheMissing(
        f"fingerprint cache missing; run scripts/run.py --build first: {Path(repo_path).name}@{snap.commit[:12]}"
    )


def _clean_exclude_prefixes(prefixes: list[str] | tuple[str, ...] | None) -> list[str]:
    out: list[str] = []
    for prefix in prefixes or []:
        clean = str(prefix).replace("\\", "/").strip().lstrip("./").strip("/")
        if clean:
            out.append(clean + "/")
    return sorted(set(out))


def build_units_from_git_commit(repo_path: str, *, snapshot: RepoSnapshot | None = None,
                                ref: str = "HEAD", use_cache: bool = True,
                                exclude_prefixes: list[str] | tuple[str, ...] | None = None) -> list[dict]:
    """Build units from Git blobs without checkout, archive, or source-tree writes."""
    snap = snapshot or resolve_snapshot(repo_path, ref, materialize=False)
    cleaned_excludes = _clean_exclude_prefixes(exclude_prefixes)
    cf = _cache_path("units", repo_path, snap.commit, snap.tree_hash)
    if use_cache and cf.exists():
        return _load_units_cache(str(cf.resolve()), *_cache_stat(cf))

    units: list[dict] = []
    extractions: list[FileExtraction] = []
    function_nodes: dict[str, tuple[object, bytes]] = {}
    function_records: dict[str, dict[str, Any]] = {}
    name_to_fn_ids: dict[str, list[str]] = {}
    all_edges: list[CallEdge] = []

    for blob in iter_source_blobs(repo_path, snap.commit, exclude_prefixes=cleaned_excludes):
        rel = blob.path.replace("\\", "/")
        if blob.suffix in {".S", ".s"}:
            for label, toks in tokenize_asm(blob.data.decode("utf-8", errors="ignore")):
                if len(toks) >= ASM_MIN_TOK:
                    units.append({
                        "unit_id": stable_id("unit", {"snapshot": snap.snapshot_id, "file": rel, "label": label}, 16),
                        "lang": "asm", "file": rel, "name": label, "line": 0, "end_line": 0,
                        "fp": _asm_fp(toks), "ast": "", "sz": len(toks), "sig": signature_from_tokens(toks),
                        "snapshot_id": snap.snapshot_id, "commit": snap.commit,
                        "outgoing_names": [], "incoming_names": [],
                    })
            continue
        lang = lang_for_path(rel)
        if lang not in CODE_LANGS:
            continue
        parser = TSLoader.parser(lang)
        if parser is None:
            continue
        try:
            tree = parser.parse(blob.data)
        except Exception:
            continue
        ext, _ = extract_file(abs_path=rel, rel_path=rel, lang=lang, code_bytes=blob.data, root_node=tree.root_node)
        extractions.append(ext)
        for fn in ext.functions:
            row = {
                "name": fn.name,
                "file": fn.file,
                "line": fn.line,
                "end_line": fn.end_line,
                "lang": fn.lang,
                "signature": fn.signature,
            }
            function_records[fn.fn_id] = row
            function_nodes[fn.fn_id] = (ext.fn_nodes_by_id[fn.fn_id], blob.data)
            name_to_fn_ids.setdefault(fn.name, []).append(fn.fn_id)
        all_edges.extend(ext.edges)

    functions = _functions_with_features(function_records, function_nodes, name_to_fn_ids)
    edges = _resolve_edges(all_edges, name_to_fn_ids)
    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {}
    for edge in edges:
        src = str(edge.get("src_fn_id") or "")
        dst = str(edge.get("dst_fn_id") or "")
        callee = str(edge.get("callee_name") or "")
        if src and callee:
            outgoing.setdefault(src, set()).add(callee)
        if dst and src:
            incoming.setdefault(dst, set()).add(str(functions.get(src, {}).get("name") or src))

    for fn_id, fn in functions.items():
        lang = fn.get("lang")
        if lang not in CODE_LANGS:
            continue
        fp = _fn_structure_fingerprint(fn)
        tokens = fn.get("tokens_normalized") or []
        units.append({
            "unit_id": stable_id("unit", {"snapshot": snap.snapshot_id, "fn": fn_id}, 16),
            "lang": lang, "file": str(fn.get("file", "")).replace("\\", "/"),
            "name": fn.get("name", ""), "line": fn.get("line", 0), "end_line": fn.get("end_line", 0),
            "fp": fp["normalized_token_fingerprint"], "ast": fp.get("ast_shape_hash", ""),
            "sz": len(tokens), "sig": signature_from_tokens(tokens), "fn_id": fn_id,
            "snapshot_id": snap.snapshot_id, "commit": snap.commit,
            "outgoing_names": sorted(outgoing.get(fn_id, set())),
            "incoming_names": sorted(incoming.get(fn_id, set())),
        })

    CACHE.mkdir(exist_ok=True)
    cf.write_bytes(pickle.dumps(units))
    _write_cache_meta(repo_path, snap, source_excluded_prefixes=cleaned_excludes)
    return units


def _cache_stat(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=512)
def _load_units_cache(path: str, mtime_ns: int, size: int) -> list[dict]:
    del mtime_ns, size
    return pickle.loads(Path(path).read_bytes())


def fingerprint_set(repo_path: str, *, branch: str = "", ref: str = "", snapshot: RepoSnapshot | None = None,
                    use_cache: bool = True) -> set[str]:
    snap = snapshot or resolve_snapshot(repo_path, ref or branch or "HEAD")
    cf = _cache_path("fpset", repo_path, snap.commit, snap.tree_hash)
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())
    result = {u["fp"] for u in build_units_from_git_commit(repo_path, snapshot=snap, use_cache=use_cache)}
    CACHE.mkdir(exist_ok=True); cf.write_bytes(pickle.dumps(result))
    return result


def ast_fingerprint_set(repo_path: str, *, branch: str = "", ref: str = "", snapshot: RepoSnapshot | None = None,
                        use_cache: bool = True) -> set[str]:
    snap = snapshot or resolve_snapshot(repo_path, ref or branch or "HEAD")
    cf = _cache_path("astset", repo_path, snap.commit, snap.tree_hash)
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())
    units = build_units_from_git_commit(repo_path, snapshot=snap, use_cache=use_cache)
    result = {u["ast"] for u in units if u.get("ast") and u["lang"] != "asm"}
    CACHE.mkdir(exist_ok=True); cf.write_bytes(pickle.dumps(result))
    return result


def cache_metadata(repo_path: str, ref: str = "HEAD") -> dict[str, Any]:
    snap = resolve_snapshot(repo_path, ref, materialize=False)
    path = _cache_path("meta", repo_path, snap.commit, snap.tree_hash).with_suffix(".json")
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return snap.to_dict() | {"fingerprint_schema": FINGERPRINT_SCHEMA}


def _write_cache_meta(repo_path: str, snapshot: RepoSnapshot, *,
                      source_excluded_prefixes: list[str] | tuple[str, ...] | None = None) -> None:
    path = _cache_path("meta", repo_path, snapshot.commit, snapshot.tree_hash).with_suffix(".json")
    meta = snapshot.to_dict() | {"fingerprint_schema": FINGERPRINT_SCHEMA}
    cleaned_excludes = _clean_exclude_prefixes(source_excluded_prefixes)
    if cleaned_excludes:
        meta["source_excluded_prefixes"] = cleaned_excludes
    path.write_text(json.dumps(meta,
                               ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _functions_with_features(functions: dict[str, dict[str, Any]], nodes: dict[str, tuple[object, bytes]],
                             name_to_fn_ids: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    keep_names = set(name_to_fn_ids)
    out: dict[str, dict[str, Any]] = {}
    for fn_id, row in functions.items():
        node, code_bytes = nodes[fn_id]
        try:
            tokens = normalize_function_tokens(node, code_bytes, keep_text_identifiers=keep_names)
        except Exception:
            tokens = []
        try:
            shape = ast_shape_hash(node)
        except Exception:
            shape = "ERROR"
        out[fn_id] = {
            **row,
            "tokens_normalized": tokens,
            "ast_shape_hash": shape,
            "literal_set": _extract_literal_set(node, code_bytes),
        }
    return out


def _resolve_edges(edges: list[CallEdge], name_to_fn_ids: dict[str, list[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for edge in edges:
        candidates = name_to_fn_ids.get(edge.callee_name, [])
        row: dict[str, Any] = {
            "src_fn_id": edge.src_fn_id,
            "callee_name": edge.callee_name,
            "callsite_file": edge.callsite_file,
            "callsite_line": edge.callsite_line,
        }
        if len(candidates) == 1:
            row["dst_fn_id"] = candidates[0]
        else:
            row["dst_fn_id"] = None
            if candidates:
                row["dst_candidates"] = candidates
        rows.append(row)
    return rows


_LITERAL_NODE_TYPES = frozenset({
    "number_literal", "integer_literal", "float_literal",
    "string_literal", "raw_string_literal", "concatenated_string",
    "char_literal", "boolean_literal", "interpreted_string_literal",
})


def _extract_literal_set(fn_node, code_bytes: bytes) -> list[str]:
    literals: set[str] = set()

    def visit(node):
        if node.type in _LITERAL_NODE_TYPES:
            text = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
            if text and len(text) <= 200:
                literals.add(text)
            return
        for child in node.children:
            visit(child)

    try:
        visit(fn_node)
    except Exception:
        return []
    return sorted(literals)


def lang_summary(units: list[dict]) -> dict[str, int]:
    """Unit count per language — for the report's explicit coverage statement."""
    out: dict[str, int] = {}
    for u in units:
        out[u["lang"]] = out.get(u["lang"], 0) + 1
    return out


if __name__ == "__main__":  # build only; proves no similarity is computed
    repo = sys.argv[1]
    units = build_units_from_git_commit(f"repos/{repo}" if "/" not in repo else repo)
    summ = lang_summary(units)
    print(f"{repo}: {len(units)} units  {summ}")
    print(f"  asm units: {summ.get('asm', 0)}")
