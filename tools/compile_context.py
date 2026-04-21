"""
与 LSP / libclang 共用的编译标志生成逻辑。
供 clangd 根目录 compile_flags.txt（会话期临时文件）与 callgraph_semantic 内存解析共用，
避免行为分叉。
"""

from __future__ import annotations

import os
from typing import List, Optional


def _abspath(p: str) -> str:
    res = os.path.abspath(os.path.expanduser(p))
    if os.name == "nt" and len(res) >= 2 and res[1] == ":":
        return res[0].upper() + res[1:]
    return res


def detect_target_arch(repo_path: str) -> Optional[str]:
    """尝试从仓库结构中推测目标架构 (riscv64, loongarch64 等)。"""
    repo_path = _abspath(repo_path)
    override_marker = os.path.join(repo_path, ".os_agent_lsp_target")
    if os.path.exists(override_marker):
        try:
            with open(override_marker, "r", encoding="utf-8") as f:
                target = f.read().strip()
                if target:
                    return target
        except OSError:
            pass

    target = os.environ.get("LSP_TARGET")
    if target:
        return target

    arch_dir = os.path.join(repo_path, "os", "src", "arch")
    if os.path.exists(arch_dir):
        subdirs = [d for d in os.listdir(arch_dir) if os.path.isdir(os.path.join(arch_dir, d))]
        if "riscv64" in subdirs:
            return "riscv64gc-unknown-none-elf"
        if "loongarch64" in subdirs or "la64" in subdirs:
            return "loongarch64-unknown-none-elf"
        if "x86_64" in subdirs:
            return "x86_64-unknown-none-elf"
        if "aarch64" in subdirs:
            return "aarch64-unknown-none-elf"

    try:
        for root, dirs, files in os.walk(os.path.join(repo_path, "os", "src")):
            if "target" in dirs:
                dirs.remove("target")
            for fn in files:
                if fn.endswith(".rs"):
                    with open(os.path.join(root, fn), "r", encoding="utf-8", errors="ignore") as f_in:
                        content = f_in.read(2048)
                        if 'target_arch = "riscv64"' in content:
                            return "riscv64gc-unknown-none-elf"
                        if 'target_arch = "loongarch64"' in content:
                            return "loongarch64-unknown-none-elf"
    except OSError:
        pass

    return None


def build_compile_flag_lines(repo_path: str) -> List[str]:
    """
    生成与历史 lsp_ops polyfill 一致的 clang 参数行列表（每行一个参数，不含换行符）。
    用于内存中的 libclang 解析；clangd 仍需要在仓库根短暂写入 compile_flags.txt。
    """
    repo_path = _abspath(repo_path)
    lines: List[str] = ["-xc", "-ffreestanding", "-fno-builtin"]
    target_arch = detect_target_arch(repo_path)
    if target_arch:
        base_arch = target_arch.split("-")[0].replace("gc", "")
        lines.append(f"--target={base_arch}")

    include_dirs = {repo_path}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [
            d
            for d in dirs
            if d not in {".git", ".github", "target", "vendor", "node_modules", "build", "dist"}
        ]
        if any(f.endswith(".h") or f.endswith(".hpp") for f in files):
            ar = _abspath(root)
            include_dirs.add(ar)
            include_dirs.add(os.path.dirname(ar))
        if os.path.basename(os.path.normpath(root)) == "include":
            include_dirs.add(_abspath(root))

    for d in sorted(include_dirs):
        lines.append(f"-I{d.replace(chr(92), '/')}")
    return lines
