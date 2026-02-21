#!/usr/bin/env python3
"""OS-Agent 环境检查脚本 — 验证 Python 依赖与 LSP 工具是否正确安装。

Usage:
    python check_env.py
"""
import sys
import shutil
import os
import platform

def _check(label: str, ok: bool, detail: str = ""):
    status = "✅" if ok else "❌"
    msg = f"  {status} {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return ok

def main():
    print(f"OS-Agent 环境检查  [{platform.system()} {platform.machine()}, Python {sys.version.split()[0]}]")
    print("=" * 60)
    all_ok = True

    # --- Python version ---
    py_ok = sys.version_info >= (3, 10)
    all_ok &= _check("Python >= 3.10", py_ok, sys.version.split()[0])

    # --- Core Python packages ---
    print("\n📦 Python 依赖:")
    pkgs = {
        "langchain": "langchain",
        "langchain_openai": "langchain-openai",
        "langgraph": "langgraph",
        "openai": "openai",
        "git": "gitpython",
        "dotenv": "python-dotenv",
        "matplotlib": "matplotlib",
        "pymupdf4llm": "pymupdf4llm",
    }
    for imp, pip_name in pkgs.items():
        try:
            __import__(imp)
            _check(pip_name, True)
        except ImportError:
            all_ok &= _check(pip_name, False, f"pip install {pip_name}")

    # --- .env file ---
    print("\n⚙️  配置文件:")
    env_exists = os.path.isfile(".env")
    all_ok &= _check(".env 文件", env_exists, "缺失 — 请复制 .env.example 并填写 API_KEY" if not env_exists else "")

    # --- LSP tools ---
    print("\n🔧 Language Servers (LSP):")
    # Import the resolve function to use the same logic as the agent
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from tools.lsp_ops import _resolve_lsp_binary
        use_resolve = True
    except ImportError:
        use_resolve = False

    lsp_tools = {
        "rust-analyzer": {"required": "Rust OS 分析必需", "install": {
            "Windows": "winget install rust-analyzer  或  rustup component add rust-analyzer",
            "Linux":   "rustup component add rust-analyzer  或  apt install rust-analyzer",
            "Darwin":  "brew install rust-analyzer  或  rustup component add rust-analyzer",
        }},
        "clangd": {"required": "C/C++ OS 分析必需", "install": {
            "Windows": "winget install LLVM.LLVM",
            "Linux":   "apt install clangd  或  pacman -S clang",
            "Darwin":  "brew install llvm  (clangd 已包含)",
        }},
        "gopls": {"required": "Go OS 分析可选", "install": {
            "Windows": "go install golang.org/x/tools/gopls@latest",
            "Linux":   "go install golang.org/x/tools/gopls@latest",
            "Darwin":  "go install golang.org/x/tools/gopls@latest",
        }},
    }

    sys_name = platform.system()
    for name, info in lsp_tools.items():
        if use_resolve:
            resolved = _resolve_lsp_binary(name)
            found = resolved != name  # bare name means not found
            path_info = resolved if found else ""
        else:
            path = shutil.which(name)
            found = path is not None
            path_info = path or ""

        if found:
            _check(name, True, path_info)
        else:
            install_hint = info["install"].get(sys_name, info["install"]["Linux"])
            all_ok &= _check(name, False, f'{info["required"]} — {install_hint}')

    # --- Summary ---
    print("\n" + "=" * 60)
    if all_ok:
        print("🎉 环境检查全部通过！可以运行 python os_agent_d_describe.py")
    else:
        print("⚠️  部分检查未通过，请按上述提示安装缺失组件。")
        print("   LSP 工具缺失不会导致崩溃（自动降级为正则解析），但分析精度会降低。")
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
