"""Structural fingerprint helpers for C, C++, Rust, and assembly."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)

AST_SHAPE_VERSION = "v1"
_AST_DELIMITER = "|"
_AST_CHILD_SEPARATOR = ","

_LANGUAGE_PACKAGES = {
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
    "rust": "tree_sitter_rust",
}

_EXTENSION_LANGUAGES = {
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cxx": "cpp",
    ".rs": "rust",
}

_FUNCTION_TYPES = {
    "c": {"function_definition"},
    "cpp": {"function_definition"},
    "rust": {"function_item"},
}

_CALL_TYPES = {
    "c": {"call_expression"},
    "cpp": {"call_expression"},
    "rust": {"call_expression", "macro_invocation"},
}

_KEYWORD_SKIP = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "default",
        "match",
        "return",
        "break",
        "continue",
        "loop",
        "let",
        "const",
        "static",
        "fn",
        "use",
        "pub",
        "mod",
        "unsafe",
        "async",
        "await",
        "extern",
        "struct",
        "enum",
        "union",
        "trait",
        "impl",
        "type",
        "typedef",
        "self",
        "Self",
        "super",
        "true",
        "false",
        "null",
        "None",
        "Some",
        "Ok",
        "Err",
        "println",
        "print",
        "format",
        "panic",
        "assert",
        "todo",
        "unimplemented",
        "dbg",
        "write",
        "writeln",
        "sizeof",
        "typeof",
        "alignof",
    }
)


class TreeSitterLoader:
    """Load only the parsers used by the current structural fingerprint."""

    _parsers: dict[str, Any] | None = None

    @classmethod
    def _load(cls) -> None:
        if cls._parsers is not None:
            return
        try:
            from tree_sitter import Language, Parser
        except ImportError:
            logger.warning("tree-sitter is unavailable; AST fingerprints will be empty")
            cls._parsers = {}
            return

        cls._parsers = {}
        for language_name, package_name in _LANGUAGE_PACKAGES.items():
            try:
                package = __import__(package_name)
                cls._parsers[language_name] = Parser(Language(package.language()))
            except Exception as exc:
                logger.warning("failed to load %s: %s", package_name, exc)

    @classmethod
    def parser(cls, language_name: str):
        cls._load()
        return cls._parsers.get(language_name) if cls._parsers else None


def lang_for_path(path: str) -> str | None:
    return _EXTENSION_LANGUAGES.get(os.path.splitext(path)[1].lower())


@dataclass
class FunctionRecord:
    fn_id: str
    name: str
    file: str
    line: int
    end_line: int
    lang: str


@dataclass
class CallEdge:
    src_fn_id: str
    callee_name: str


@dataclass
class FileExtraction:
    functions: list[FunctionRecord] = field(default_factory=list)
    edges: list[CallEdge] = field(default_factory=list)
    fn_nodes_by_id: dict[str, Any] = field(default_factory=dict)


def extract_file(*, rel_path: str, lang: str, code_bytes: bytes, root_node: Any) -> FileExtraction:
    """Extract function definitions and direct textual call names from one tree."""

    result = FileExtraction()
    seen_function_ids: set[str] = set()

    def visit_function(function_node: Any) -> None:
        name = _function_name(function_node, code_bytes, lang)
        if not name or name in _KEYWORD_SKIP:
            return
        line = function_node.start_point[0] + 1
        function_id = _function_id(rel_path, line, name)
        if function_id in seen_function_ids:
            return
        seen_function_ids.add(function_id)
        result.functions.append(
            FunctionRecord(
                fn_id=function_id,
                name=name,
                file=rel_path,
                line=line,
                end_line=function_node.end_point[0] + 1,
                lang=lang,
            )
        )
        result.fn_nodes_by_id[function_id] = function_node

        def visit_call(call_node: Any) -> None:
            callee = _call_name(call_node, code_bytes)
            if callee and callee not in _KEYWORD_SKIP:
                result.edges.append(CallEdge(src_fn_id=function_id, callee_name=callee))

        _walk_including_matches(function_node, _CALL_TYPES.get(lang, set()), visit_call)

    _walk_stopping_at_match(root_node, _FUNCTION_TYPES.get(lang, set()), visit_function)
    return result


def ast_shape_hash(node: Any) -> str:
    """Hash tree-sitter node types while ignoring identifiers and literal text."""

    children = node.children
    hasher = hashlib.sha256()
    hasher.update(node.type.encode("utf-8"))
    if children:
        child_hashes = [ast_shape_hash(child) for child in children]
        hasher.update(_AST_DELIMITER.encode("utf-8"))
        hasher.update(_AST_CHILD_SEPARATOR.join(child_hashes).encode("utf-8"))
    return hasher.hexdigest()


def ast_algorithm_version() -> str:
    return AST_SHAPE_VERSION


_ASSEMBLY_REGISTER = re.compile(
    r"^\$?(zero|ra|sp|gp|tp|fp|pc|lr|t[0-9]|t1[0-8]?|s[0-9]|s1[01]?|a[0-7]|"
    r"x[0-9]|x[12][0-9]|x3[01]|w[0-9]|w[12][0-9]|w3[01]|r[0-9]|r1[0-9]|"
    r"r2[0-9]|r3[01]|f[ats]?[0-9]+|xzr|wzr)$",
    re.IGNORECASE,
)
_ASSEMBLY_NUMBER = re.compile(r"^[-+]?(0x[0-9a-fA-F]+|[0-9]+)$")
_ASSEMBLY_LABEL = re.compile(r"^([A-Za-z_.$][\w.$]*):$")
_ASSEMBLY_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def assembly_shape_units(text: str) -> list[tuple[str, list[str]]]:
    """Return canonical instruction items for each assembly label block."""

    units: list[tuple[str, list[str]]] = []
    current_label = "(file)"
    current_items: list[str] = []

    def flush() -> None:
        if current_items:
            units.append((current_label, list(current_items)))

    for raw_line in _strip_assembly_comments(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label_match = _ASSEMBLY_LABEL.match(line)
        if label_match:
            flush()
            current_label = label_match.group(1)
            current_items = []
            continue
        current_items.extend(_canonical_assembly_line(line))
    flush()
    return units


def _strip_assembly_comments(text: str) -> str:
    text = _ASSEMBLY_BLOCK_COMMENT.sub(" ", text)
    lines: list[str] = []
    for line in text.splitlines():
        for marker in ("#", "//", ";"):
            marker_index = line.find(marker)
            if marker_index != -1:
                line = line[:marker_index]
        lines.append(line)
    return "\n".join(lines)


def _canonical_assembly_line(line: str) -> list[str]:
    words = line.replace("(", " ( ").replace(")", " ) ").replace(",", " , ").split()
    if not words:
        return []
    items = [words[0].lower()]
    for word in words[1:]:
        if word in {"(", ")", ","}:
            items.append(word)
        elif _ASSEMBLY_REGISTER.match(word):
            items.append("REG")
        elif _ASSEMBLY_NUMBER.match(word):
            items.append(word)
        else:
            items.append("LBL")
    return items


def _function_id(path: str, line: int, name: str) -> str:
    digest = hashlib.sha256(f"{path}:{line}:{name}".encode("utf-8")).hexdigest()
    return f"fn_{digest[:16]}"


def _walk_stopping_at_match(node: Any, node_types: set[str], callback: Any) -> None:
    if node.type in node_types:
        callback(node)
        return
    for child in node.children:
        _walk_stopping_at_match(child, node_types, callback)


def _walk_including_matches(node: Any, node_types: set[str], callback: Any) -> None:
    if node.type in node_types:
        callback(node)
    for child in node.children:
        _walk_including_matches(child, node_types, callback)


def _node_text(node: Any, code_bytes: bytes) -> str:
    return code_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _first_identifier(node: Any, code_bytes: bytes) -> str | None:
    if node.type in {"identifier", "field_identifier", "type_identifier"}:
        return _node_text(node, code_bytes)
    for child in node.children:
        identifier = _first_identifier(child, code_bytes)
        if identifier is not None:
            return identifier
    return None


def _function_name(function_node: Any, code_bytes: bytes, lang: str) -> str | None:
    if lang in {"c", "cpp"}:
        for child in function_node.children:
            if child.type in {"function_declarator", "reference_declarator", "pointer_declarator"}:
                return _first_identifier(child, code_bytes)
        return None
    if lang == "rust":
        for child in function_node.children:
            if child.type == "identifier":
                return _node_text(child, code_bytes)
    return None


def _call_name(call_node: Any, code_bytes: bytes) -> str | None:
    if not call_node.children:
        return None
    callee_node = call_node.children[0]
    if callee_node.type == "identifier":
        return _node_text(callee_node, code_bytes)
    if callee_node.type in {
        "field_expression",
        "scoped_identifier",
        "scoped_type_identifier",
        "field_access",
    }:
        identifiers: list[str] = []

        def collect(node: Any) -> None:
            if node.type in {"identifier", "field_identifier", "type_identifier"}:
                identifiers.append(_node_text(node, code_bytes))
            for child in node.children:
                collect(child)

        collect(callee_node)
        return identifiers[-1] if identifiers else None
    return None
