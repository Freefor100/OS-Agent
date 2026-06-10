#!/usr/bin/env python3
"""Generate compile_flags.txt for LSP (clangd/rust-analyzer) per repo.

Reads Makefile / Cargo.toml to detect architecture, include paths, and build
defines. Produces a compile_flags.txt in the repo root. clangd reads this
automatically on open and uses it for correct cross-target parsing.

clangd does NOT need a GCC cross-compiler installed — it has built-in target
support for riscv64/loongarch64/arm64/x86. Only the flags matter.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


# architecture → clang target triple + march
ARCH_MAP = {
    "riscv64":  ("--target=riscv64-unknown-elf", "-march=rv64gc"),
    "riscv32":  ("--target=riscv32-unknown-elf", "-march=rv32gc"),
    "loongarch64": ("--target=loongarch64-unknown-elf", "-march=la64"),
    "arm64":    ("--target=aarch64-unknown-elf", "-march=armv8-a"),
    "arm":      ("--target=arm-unknown-eabi", "-march=armv7-a"),
    "x86_64":   ("--target=x86_64-unknown-elf", ""),
}


def _detect_arch(repo: Path) -> str:
    """Best-effort arch detection from Makefile or Cargo.toml."""
    mf = repo / "Makefile"
    if mf.exists():
        txt = mf.read_text(errors="ignore")
        # riscv64-unknown-elf- toolchain prefix
        if re.search(r"riscv64-unknown-elf-|riscv64-linux-gnu-|qemu-system-riscv64", txt):
            return "riscv64"
        if re.search(r"loongarch64|loongson", txt):
            return "loongarch64"
        if re.search(r"aarch64-|arm-none-eabi", txt):
            return "arm64"
    cargo = repo / "Cargo.toml"
    if cargo.exists():
        # check cargo config for target
        cfg = repo / ".cargo" / "config.toml"
        if cfg.exists():
            ct = cfg.read_text(errors="ignore")
            for arch in ("riscv64", "loongarch64", "arm64"):
                if arch in ct:
                    return arch
        # check target dirs
        if list(repo.glob("target/riscv64*")):
            return "riscv64"
        if list(repo.glob("target/loongarch64*")):
            return "loongarch64"
        # check linker scripts
        for ld in repo.rglob("*.ld"):
            if "riscv" in ld.read_text(errors="ignore")[:500]:
                return "riscv64"
        # try configs/ dir (ArceOS)
        for cfg_dir in (repo / "configs").iterdir() if (repo / "configs").is_dir() else []:
            if "riscv" in cfg_dir.name.lower():
                return "riscv64"
    # scan for linker scripts as last resort
    for ld in repo.rglob("*.ld"):
        try:
            if "riscv" in ld.read_text(errors="ignore")[:500]:
                return "riscv64"
        except Exception:
            pass
    return ""


def _find_includes(repo: Path) -> list[str]:
    """Find include directories used by this repo."""
    includes: list[str] = []
    # common include directory names (non-recursive)
    for name in ("include", "inc", "includes"):
        d = repo / name
        if d.is_dir():
            includes.append(f"-I{name}")
    # kernel/ or src/ dirs
    for name in ("kernel", "src", "os/src", "lib"):
        d = repo / name
        if d.is_dir():
            includes.append(f"-I{name}")
    # Makefile INCLUDE paths
    mf = repo / "Makefile"
    if mf.exists():
        for m in re.finditer(r"-I\s*(\S+)", mf.read_text(errors="ignore")):
            inc = m.group(1).rstrip("/\\")
            includes.append(f"-I{inc}")
    return sorted(set(includes))


def _find_defines(repo: Path) -> list[str]:
    """Extract -D defines from Makefile (simple ones only, skip shell expansions)."""
    defines: list[str] = []
    mf = repo / "Makefile"
    if mf.exists():
        txt = mf.read_text(errors="ignore")
        for m in re.finditer(r"-D\s*(\S+)", txt):
            d = m.group(1).rstrip("\\")
            # skip shell/$(...) expanded tokens
            if "$(" in d or "${" in d or '"' in d or "'" in d:
                continue
            defines.append(f"-D{d}")
    # detect platform
    if mf.exists() and "K210" in mf.read_text(errors="ignore"):
        defines.append("-DPLATFORM_K210")
    return sorted(set(defines))


def generate(repo_path: str) -> str:
    """Generate compile_flags.txt content for a repo. Returns the content."""
    repo = Path(repo_path)
    arch = _detect_arch(repo)
    flags: list[str] = []

    if arch and arch in ARCH_MAP:
        target, march = ARCH_MAP[arch]
        flags.append(target)
        if march:
            flags.append(march)
    else:
        # no arch detected — assume host native; add freestanding flag anyway
        pass

    flags.extend([
        "-ffreestanding",
        "-nostdinc",
        "-fno-common",
        "-nostdlib",
    ])
    flags.extend(_find_includes(repo))
    flags.extend(_find_defines(repo))
    return "\n".join(flags)


if __name__ == "__main__":
    repo = sys.argv[1]
    content = generate(repo)
    out = Path(repo) / "compile_flags.txt"
    out.write_text(content + "\n")
    arch = _detect_arch(Path(repo))
    print(f"compile_flags.txt -> {out}  (arch={arch or 'unknown'}, {len(content.splitlines())} flags)")
