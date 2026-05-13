from __future__ import annotations

import os
import re
from typing import Dict, List

from langchain.tools import tool


_CONFIG_NAMES = {
    "Cargo.toml",
    "Cargo.lock",
    "Makefile",
    "makefile",
    "CMakeLists.txt",
    "rust-toolchain.toml",
    "linker.ld",
}


def _read_head(path: str, limit: int = 6000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except OSError:
        return ""


@tool
def parse_build_config(repo_path: str) -> str:
    """
    结构化扫描 OS 仓库的构建/平台配置，返回 Cargo/Make/CMake/linker/QEMU/CI 等线索摘要。
    """
    if not os.path.isdir(repo_path):
        return f"❌ repo_path 不存在: {repo_path}"
    hits: List[Dict[str, str]] = []
    ci_files: List[str] = []
    for root, dirs, files in os.walk(repo_path):
        rel_root = os.path.relpath(root, repo_path)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "dist", "node_modules", ".os_agent_ra_target"}]
        if depth > 4:
            dirs[:] = []
            continue
        for name in files:
            rel = os.path.join(rel_root, name) if rel_root != "." else name
            if name in _CONFIG_NAMES or name.endswith((".ld", ".lds", ".dts", ".dtsi", ".toml")):
                text = _read_head(os.path.join(root, name))
                if not text:
                    continue
                markers = []
                for pat in ("qemu-system", "-machine", "riscv", "loongarch", "aarch64", "x86_64", "ENTRY", "target", "kernel-rv", "disk.img"):
                    if re.search(re.escape(pat), text, re.IGNORECASE):
                        markers.append(pat)
                if markers:
                    hits.append({"path": rel.replace("\\", "/"), "markers": ", ".join(markers), "excerpt": text[:800]})
            if ".github" in rel.replace("\\", "/") or name.lower().startswith(".gitlab-ci"):
                ci_files.append(rel.replace("\\", "/"))
    if not hits and not ci_files:
        return "未发现明显构建/平台配置线索。"
    lines = ["## Build Config Summary"]
    for hit in hits[:20]:
        lines.append(f"- {hit['path']} markers=[{hit['markers']}]\n  excerpt: {hit['excerpt'][:300].replace(chr(10), ' ')}")
    if ci_files:
        lines.append("## CI Files")
        lines.extend(f"- {p}" for p in ci_files[:20])
    return "\n".join(lines)
