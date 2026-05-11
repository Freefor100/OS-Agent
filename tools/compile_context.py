"""
与 LSP / libclang 共用的编译标志生成逻辑。
供 clangd 根目录 compile_flags.txt（会话期临时文件）与 callgraph_semantic 内存解析共用，
避免行为分叉。
"""

from __future__ import annotations

import os
import re
from typing import List, Optional


def _abspath(p: str) -> str:
    res = os.path.abspath(os.path.expanduser(p))
    if os.name == "nt" and len(res) >= 2 and res[1] == ":":
        return res[0].upper() + res[1:]
    return res


def _target_from_text(text: str) -> Optional[str]:
    """Infer a target triple/arch from build config snippets."""
    lowered = text.lower()
    is_os_kernel_context = any(
        token in lowered
        for token in (
            "-ffreestanding",
            "-nostdlib",
            "output_arch(riscv)",
            "output_arch(loongarch",
            "qemu-system-riscv64",
            "qemu-system-loongarch64",
            "kernel",
            "sbi",
            "rustsbi",
            "k210",
            "visionfive",
            "la64",
        )
    )
    is_explicit_hosted_userland = any(
        token in lowered
        for token in (
            "glibc",
            "/usr/include",
            "pthread",
            "linux user",
            "userspace",
            "userland",
        )
    ) and not is_os_kernel_context

    explicit_triples = [
        "riscv64gc-unknown-none-elf",
        "riscv64imac-unknown-none-elf",
        "riscv64imac-unknown-elf-none",
        "riscv64-unknown-none-elf",
        "riscv64-unknown-elf",
        "loongarch64-unknown-none-elf",
        "loongarch64-unknown-none",
        "loongarch64-unknown-elf",
        "aarch64-unknown-none-elf",
        "arm-none-eabi",
        "x86_64-unknown-none-elf",
    ]
    for triple in explicit_triples:
        if triple in lowered:
            return triple

    hosted_to_bare = {
        "riscv64-linux-gnu": "riscv64-unknown-elf",
        "riscv64-linux-musl": "riscv64-unknown-elf",
        "loongarch64-linux-gnu": "loongarch64-unknown-elf",
        "aarch64-linux-gnu": "aarch64-unknown-none-elf",
    }
    for hosted, bare in hosted_to_bare.items():
        if hosted in lowered:
            return hosted if is_explicit_hosted_userland else bare

    # Makefile-style tool prefixes, e.g. TOOLPREFIX := riscv64-unknown-elf-
    m = re.search(
        r"(?m)^\s*(?:toolprefix|cross_compile)\s*[:?+]?=\s*([A-Za-z0-9_./-]+-)\s*$",
        text,
        re.IGNORECASE,
    )
    if m:
        prefix = os.path.basename(m.group(1)).rstrip("-").lower()
        if prefix.endswith("-gcc"):
            prefix = prefix[:-4]
        if prefix.startswith("riscv64"):
            if not is_explicit_hosted_userland and ("linux-gnu" in prefix or "linux-musl" in prefix):
                return "riscv64-unknown-elf"
            return prefix
        if prefix.startswith("loongarch64"):
            if not is_explicit_hosted_userland and "linux-gnu" in prefix:
                return "loongarch64-unknown-elf"
            return prefix
        if prefix.startswith("aarch64"):
            if not is_explicit_hosted_userland and "linux-gnu" in prefix:
                return "aarch64-unknown-none-elf"
            return prefix
        if prefix.startswith("arm"):
            return prefix

    if "qemu-system-riscv64" in lowered or "output_arch(riscv)" in lowered:
        return "riscv64-unknown-elf"
    if "loongarch64" in lowered or "qemu-system-loongarch64" in lowered or "output_arch(loongarch" in lowered:
        return "loongarch64-unknown-elf"
    if "qemu-system-aarch64" in lowered or "output_arch(aarch64)" in lowered:
        return "aarch64-unknown-none-elf"

    return None


def detect_target_arch(repo_path: str) -> Optional[str]:
    """尝试从仓库结构和构建配置中推测目标架构 / target triple。"""
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
        config_files = [
            "rust-toolchain.toml",
            ".cargo/config.toml",
            ".cargo/config",
            "Cargo.toml",
            "Makefile",
            "GNUmakefile",
            "makefile",
            "CMakeLists.txt",
            "build.zig",
        ]
        for rel in config_files:
            path = os.path.join(repo_path, rel)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as f_in:
                target = _target_from_text(f_in.read(16384))
                if target:
                    return target

        linker_dir = os.path.join(repo_path, "linker")
        if os.path.isdir(linker_dir):
            for fn in os.listdir(linker_dir):
                if not fn.endswith((".ld", ".lds")):
                    continue
                with open(os.path.join(linker_dir, fn), "r", encoding="utf-8", errors="ignore") as f_in:
                    target = _target_from_text(f_in.read(4096))
                    if target:
                        return target

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
        target_head = target_arch.split("-")[0].lower()
        if target_head.startswith("riscv64"):
            base_arch = "riscv64"
        elif target_head.startswith("riscv32"):
            base_arch = "riscv32"
        else:
            base_arch = target_head
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
