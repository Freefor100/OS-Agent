from __future__ import annotations

import os
import re
from typing import Any


_CONFIG_NAMES = {
    "Cargo.toml",
    "Cargo.lock",
    "Makefile",
    "makefile",
    "CMakeLists.txt",
    "rust-toolchain.toml",
    "linker.ld",
    "kernel.ld",
}


def _read_head(path: str, limit: int = 6000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except OSError:
        return ""


def parse_build_config_structured(repo_path: str) -> dict[str, Any]:
    """Scan build/target configuration without mutating the repository."""
    hits: list[dict[str, Any]] = []
    ci_files: list[str] = []
    markers_seen: set[str] = set()
    if not os.path.isdir(repo_path):
        return {"error": f"repo_path does not exist: {repo_path}"}

    for root, dirs, files in os.walk(repo_path):
        rel_root = os.path.relpath(root, repo_path)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        dirs[:] = [
            d for d in dirs
            if d not in {".git", "target", "build", "dist", "node_modules", "vendor", "__pycache__"}
        ]
        if depth > 4:
            dirs[:] = []
            continue
        for name in files:
            rel = os.path.join(rel_root, name) if rel_root != "." else name
            rel = rel.replace("\\", "/")
            lower = name.lower()
            interesting = (
                name in _CONFIG_NAMES
                or lower.endswith((".ld", ".lds", ".dts", ".dtsi", ".toml", ".mk", ".cmake"))
            )
            if interesting:
                text = _read_head(os.path.join(root, name))
                if not text:
                    continue
                markers = []
                for pat in (
                    "qemu-system", "-machine", "riscv", "loongarch", "aarch64",
                    "x86_64", "ENTRY", "target", "kernel", "fs.img", "virt",
                    "riscv64-unknown-elf", "riscv64-linux-gnu", "clang", "gcc",
                ):
                    if re.search(re.escape(pat), text, re.IGNORECASE):
                        markers.append(pat)
                        markers_seen.add(pat.lower())
                if markers:
                    hits.append({
                        "path": rel,
                        "markers": markers,
                        "excerpt": text[:800],
                    })
            if ".github" in rel or lower.startswith(".gitlab-ci"):
                ci_files.append(rel)

    target_arch = "unknown"
    joined = " ".join(sorted(markers_seen))
    if "riscv" in joined:
        target_arch = "riscv64" if "riscv64" in joined or "qemu-system" in joined else "riscv"
    elif "loongarch" in joined:
        target_arch = "loongarch64"
    elif "aarch64" in joined:
        target_arch = "aarch64"
    elif "x86_64" in joined:
        target_arch = "x86_64"

    build_systems = []
    names = {os.path.basename(h["path"]) for h in hits}
    if "Makefile" in names or "makefile" in names:
        build_systems.append("make")
    if "Cargo.toml" in names:
        build_systems.append("cargo")
    if "CMakeLists.txt" in names:
        build_systems.append("cmake")

    return {
        "build_systems": build_systems,
        "target_arch": target_arch,
        "config_hits": hits[:50],
        "ci_files": ci_files[:50],
    }


def parse_build_config(repo_path: str) -> str:
    """Return a readable build/target configuration summary."""
    data = parse_build_config_structured(repo_path)
    if data.get("error"):
        return f"Error: {data['error']}"
    if not data.get("config_hits") and not data.get("ci_files"):
        return "未发现明显构建/平台配置线索。"
    lines = [
        "## Build Config Summary",
        f"- build_systems: {data.get('build_systems')}",
        f"- target_arch: {data.get('target_arch')}",
    ]
    for hit in data.get("config_hits", [])[:20]:
        excerpt = str(hit.get("excerpt", ""))[:300].replace("\n", " ")
        lines.append(f"- {hit['path']} markers={hit['markers']}\n  excerpt: {excerpt}")
    if data.get("ci_files"):
        lines.append("## CI Files")
        lines.extend(f"- {p}" for p in data["ci_files"][:20])
    return "\n".join(lines)
