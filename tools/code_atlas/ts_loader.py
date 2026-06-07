"""tree-sitter 语言加载器 + 解析入口。

借鉴 tools/callgraph_overview.py:_TSLoader 的 lazy load 思路，但去掉旧设计的耦合：
- 直接用 tree-sitter 0.21+ 的新 API（Language(modX.language())）
- 缺失语言静默跳过，不抛
- 提供统一的 parse_file() 入口

不放在 callgraph_overview 旁边是因为它会被旧代码 import；这里独立。

设计书 §7.2 "tree-sitter 基础解析"对应。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# 语言名 ↔ pip 包名 ↔ 文件后缀
_LANG_PKG = {
    "c":    "tree_sitter_c",
    "cpp":  "tree_sitter_cpp",
    "rust": "tree_sitter_rust",
    "go":   "tree_sitter_go",
    "zig":  "tree_sitter_zig",
}

_EXT_TO_LANG = {
    ".c": "c",   ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".cxx": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".zig": "zig",
}


def lang_for_path(path: str) -> Optional[str]:
    """根据后缀推断语言；无法识别返回 None。"""
    ext = os.path.splitext(path)[1].lower()
    return _EXT_TO_LANG.get(ext)


class TSLoader:
    """单例式 lazy loader。第一次访问时加载所有可用语言。"""

    _languages: dict | None = None
    _parsers: dict | None = None

    @classmethod
    def _load(cls) -> None:
        if cls._languages is not None:
            return
        try:
            from tree_sitter import Language, Parser
        except ImportError:
            logger.warning("[TSLoader] tree_sitter 未安装；所有解析将返回 None")
            cls._languages = {}
            cls._parsers = {}
            return

        cls._languages = {}
        cls._parsers = {}
        for name, pkg in _LANG_PKG.items():
            try:
                mod = __import__(pkg)
                lang = Language(mod.language())
                cls._languages[name] = lang
                cls._parsers[name] = Parser(lang)
            except Exception as exc:
                logger.warning("[TSLoader] %s 加载失败: %s", pkg, exc)

    @classmethod
    def parser(cls, lang: str):
        cls._load()
        return cls._parsers.get(lang) if cls._parsers else None

    @classmethod
    def language(cls, lang: str):
        cls._load()
        return cls._languages.get(lang) if cls._languages else None

    @classmethod
    def available_languages(cls) -> list[str]:
        cls._load()
        return sorted(cls._parsers or {})


def parse_file(abs_path: str, *, max_bytes: int = 4 * 1024 * 1024) -> tuple[bytes, object] | None:
    """读文件 + tree-sitter 解析。

    返回 (code_bytes, root_node)；解析失败、无对应语言、文件过大时返回 None。

    max_bytes 限制：单个超大文件（生成代码 / 第三方 vendor）跳过。
    """
    lang = lang_for_path(abs_path)
    if lang is None:
        return None
    parser = TSLoader.parser(lang)
    if parser is None:
        return None
    try:
        size = os.path.getsize(abs_path)
        if size > max_bytes:
            logger.info("[parse_file] skip oversize %s (%d bytes)", abs_path, size)
            return None
        with open(abs_path, "rb") as f:
            code_bytes = f.read()
    except OSError as exc:
        logger.warning("[parse_file] read fail %s: %s", abs_path, exc)
        return None
    try:
        tree = parser.parse(code_bytes)
    except Exception as exc:
        logger.warning("[parse_file] parse fail %s: %s", abs_path, exc)
        return None
    return code_bytes, tree.root_node


# 默认跳过的目录（借鉴 callgraph_overview._skip_dirs）
DEFAULT_SKIP_DIRS = frozenset({
    ".git", ".svn", ".hg",
    "target", "build", "out", "output", "dist",
    "cmake-build-debug", "cmake-build-release",
    "node_modules", "vendor", "third_party",
    ".github", ".vscode", ".idea",
    "__pycache__",
    ".os_agent_ra_target",
})


def walk_source_files(repo_path: str, *, skip_dirs: frozenset = DEFAULT_SKIP_DIRS):
    """遍历仓库内可解析的源文件，yield (abs_path, rel_path, lang)。"""
    for dirpath, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _EXT_TO_LANG:
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, repo_path)
            yield abs_path, rel_path, _EXT_TO_LANG[ext]
