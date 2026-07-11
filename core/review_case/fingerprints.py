from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.git_source import iter_source_blobs, list_tree
from tools.code_atlas.asm_tokenize import tokenize_asm
from tools.code_atlas.ast_shape import algorithm_version, ast_shape_hash
from tools.code_atlas.extractor import CallEdge, extract_file
from tools.code_atlas.ts_loader import TSLoader, lang_for_path


CODE_LANGS = {"c", "cpp", "rust"}
BLOB_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".hpp", ".cxx", ".rs", ".S", ".s", ".ld", ".lds", ".toml", ".mk"}
ASM_MIN_TOKENS = 12
SCHEMA_VERSION = "review_case.fingerprint.v2"


def write_fingerprint_cache(
    repo: Path,
    commit: str,
    work_id: str,
    display_name: str,
    cache_root: str | Path,
) -> Path:
    cache_base = Path(cache_root)
    if not cache_base.is_absolute():
        cache_base = Path.cwd() / cache_base
    cache_dir = cache_base / work_id / commit[:12]
    cache_dir.mkdir(parents=True, exist_ok=True)

    entries = [
        entry
        for entry in list_tree(str(repo), commit)
        if entry.kind == "blob" and Path(entry.path).suffix in BLOB_SUFFIXES
    ]
    blobs = [
        {"mode": entry.mode, "kind": entry.kind, "blob": entry.object_id, "path": entry.path}
        for entry in entries
    ]
    blob_by_path = {entry.path: entry.object_id for entry in entries}
    units, parser_warnings = _extract_units(repo, commit, blob_by_path)

    _write_json(
        cache_dir / "fingerprint_manifest.json",
        {
            "schema": SCHEMA_VERSION,
            "work_id": work_id,
            "display_name": display_name,
            "commit": commit,
            "source_file_count": len(blobs),
            "structural_unit_count": len(units),
            "ast_shape_version": algorithm_version(),
            "parser_warnings": parser_warnings,
        },
    )
    _write_json(
        cache_dir / "target_blob.json",
        {"schema": "review_case.blob_fingerprint.v2", "commit": commit, "files": blobs},
    )
    _write_json(
        cache_dir / "target_ast.json",
        {
            "schema": "review_case.structural_fingerprint.v2",
            "commit": commit,
            "algorithm": "tree-sitter function AST shape plus normalized assembly label blocks",
            "units": units,
        },
    )
    return cache_dir


def _extract_units(repo: Path, commit: str, blob_by_path: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    units: list[dict[str, Any]] = []
    functions: dict[str, dict[str, Any]] = {}
    function_nodes: dict[str, tuple[Any, bytes]] = {}
    name_to_ids: dict[str, list[str]] = {}
    edges: list[CallEdge] = []
    warnings: list[str] = []

    for blob in iter_source_blobs(str(repo), commit):
        path = blob.path.replace("\\", "/")
        if blob.suffix in {".S", ".s"}:
            for label, tokens in tokenize_asm(blob.data.decode("utf-8", errors="ignore")):
                if len(tokens) < ASM_MIN_TOKENS:
                    continue
                units.append(
                    {
                        "unit_id": _stable_id(path, label, "asm"),
                        "path": path,
                        "symbol": label,
                        "kind": "assembly_block",
                        "lang": "asm",
                        "line": 0,
                        "end_line": 0,
                        "shape": hashlib.sha256(" ".join(tokens).encode()).hexdigest(),
                        "blob": blob.object_id,
                        "outgoing_names": [],
                        "incoming_names": [],
                        "literals": [],
                    }
                )
            continue

        lang = lang_for_path(path)
        if lang not in CODE_LANGS:
            continue
        parser = TSLoader.parser(lang)
        if parser is None:
            warnings.append(f"parser unavailable: {lang}:{path}")
            continue
        try:
            tree = parser.parse(blob.data)
            extraction, _ = extract_file(
                abs_path=path,
                rel_path=path,
                lang=lang,
                code_bytes=blob.data,
                root_node=tree.root_node,
            )
        except Exception as exc:
            warnings.append(f"parse failed: {path}: {type(exc).__name__}")
            continue
        for fn in extraction.functions:
            functions[fn.fn_id] = {
                "path": fn.file,
                "symbol": fn.name,
                "kind": "function",
                "lang": fn.lang,
                "line": fn.line,
                "end_line": fn.end_line,
                "blob": blob_by_path.get(path, blob.object_id),
            }
            function_nodes[fn.fn_id] = (extraction.fn_nodes_by_id[fn.fn_id], blob.data)
            name_to_ids.setdefault(fn.name, []).append(fn.fn_id)
        edges.extend(extraction.edges)

    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {}
    for edge in edges:
        outgoing.setdefault(edge.src_fn_id, set()).add(edge.callee_name)
        candidates = name_to_ids.get(edge.callee_name, [])
        if len(candidates) == 1:
            caller = functions.get(edge.src_fn_id, {}).get("symbol", edge.src_fn_id)
            incoming.setdefault(candidates[0], set()).add(str(caller))

    for fn_id, row in functions.items():
        node, code = function_nodes[fn_id]
        try:
            shape = ast_shape_hash(node)
        except Exception as exc:
            warnings.append(f"shape failed: {row['path']}:{row['symbol']}: {type(exc).__name__}")
            continue
        units.append(
            {
                "unit_id": _stable_id(str(row["path"]), str(row["symbol"]), str(row["line"])),
                **row,
                "shape": shape,
                "outgoing_names": sorted(outgoing.get(fn_id, set())),
                "incoming_names": sorted(incoming.get(fn_id, set())),
                "literals": _literal_set(node, code),
            }
        )
    units.sort(key=lambda unit: (str(unit["path"]), int(unit["line"]), str(unit["symbol"])))
    return units, warnings[:200]


_LITERAL_TYPES = {
    "number_literal",
    "integer_literal",
    "float_literal",
    "string_literal",
    "raw_string_literal",
    "concatenated_string",
    "char_literal",
    "boolean_literal",
    "interpreted_string_literal",
}


def _literal_set(node: Any, code: bytes) -> list[str]:
    values: set[str] = set()

    def visit(current: Any) -> None:
        if current.type in _LITERAL_TYPES:
            value = code[current.start_byte : current.end_byte].decode("utf-8", errors="ignore").strip()
            if value and len(value) <= 200:
                values.add(value)
            return
        for child in current.children:
            visit(child)

    visit(node)
    return sorted(values)


def _stable_id(*parts: str) -> str:
    return "unit_" + hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
