#!/usr/bin/env python3
"""OS-Agent 环境检查脚本 — 验证 Python 依赖与 LSP 工具是否正确安装。

Usage:
    python check_env.py
"""
import sys
import shutil
import os
import platform
import subprocess

def _find_build_tool(tool_name):
    path = shutil.which(tool_name)
    if path:
        return path
    if platform.system() == "Windows":
        import glob
        # Common fallback locations for Windows package managers and default installers
        fallbacks = [
            os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*{tool_name}*\*\bin\{tool_name}.exe"),
            os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*{tool_name}*\{tool_name}.exe"),
            os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*\*\{tool_name}.exe"),
            os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*\*\bin\{tool_name}.exe"),
            os.path.expandvars(rf"%USERPROFILE%\scoop\apps\*\current\bin\{tool_name}.exe"),
            rf"C:\Program Files\CMake\bin\{tool_name}.exe",
            rf"C:\Program Files\LLVM\bin\{tool_name}.exe",
            rf"C:\Program Files\Git\usr\bin\{tool_name}.exe"
        ]
        for pattern in fallbacks:
            matches = glob.glob(pattern)
            if matches:
                return matches[0]
    return None

def get_git_usr_bin():
    if platform.system() != "Windows":
        return None
    # Try from shutil.which
    git_path = shutil.which("git")
    if git_path:
        # Usually C:\Program Files\Git\cmd\git.exe -> we want C:\Program Files\Git\usr\bin
        git_dir = os.path.dirname(os.path.dirname(git_path))
        usr_bin = os.path.join(git_dir, "usr", "bin")
        if os.path.isdir(usr_bin):
            return usr_bin
            
        # Or C:\Program Files\Git\bin\git.exe
        usr_bin2 = os.path.join(os.path.dirname(git_path), "..", "usr", "bin")
        if os.path.isdir(usr_bin2):
            return os.path.abspath(usr_bin2)
            
    # Fallback default location
    fallback = r"C:\Program Files\Git\usr\bin"
    if os.path.isdir(fallback):
        return fallback
    return None

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
    # First check if we have a requirements.txt to install from
    req_path = "requirements.txt"
    if os.path.isfile(req_path):
        _check("requirements.txt", True)
        try:
            print(f"  正在通过 {req_path} 安装依赖...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path], check=True)
            _check("requirements.txt 依赖安装", True)
        except subprocess.CalledProcessError:
            all_ok = False
            _check("requirements.txt 依赖安装", False, "请手动运行 pip install -r requirements.txt")
    
    for imp, pip_name in pkgs.items():
        try:
            __import__(imp)
            _check(pip_name, True)
        except ImportError:
            _check(pip_name, False, f"未找到，正在自动安装 pip install {pip_name}...")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", pip_name], check=True)
                _check(f"{pip_name} (自动安装成功)", True)
            except subprocess.CalledProcessError:
                all_ok = False
                _check(f"{pip_name} (自动安装失败)", False, f"请手动运行 pip install {pip_name}")

    # --- .env file ---
    print("\n⚙️  配置文件:")
    env_exists = os.path.isfile(".env")
    all_ok &= _check(".env 文件", env_exists, "缺失 — 请复制 .env.example 并填写 API_KEY" if not env_exists else "")

    # --- C/C++ Build Tools ---
    print("\n🛠️  C/C++ Build Tools (OS 编译依赖):")
    build_tools = {
        "make": {
            "Windows": "scoop install make 或者 choco install make 或者 winget install ezwinports.make",
            "Linux": "apt install build-essential",
            "Darwin": "brew install make"
        },
        "cmake": {
            "Windows": "scoop install cmake 或者 winget install Kitware.CMake",
            "Linux": "apt install cmake",
            "Darwin": "brew install cmake"
        }
    }
    sys_name = platform.system()
    
    for tool, hints in build_tools.items():
        found_path = _find_build_tool(tool)
        if found_path:
            _check(tool, True, found_path)
        else:
            all_ok = False
            _check(tool, False, f"未找到，建议运行: {hints.get(sys_name, hints['Linux'])}")
            
    # Check for a C compiler (gcc or clang)
    gcc_path = _find_build_tool("gcc")
    clang_path = _find_build_tool("clang")
    
    if gcc_path or clang_path:
        compiler_path = gcc_path if gcc_path else clang_path
        _check("C Compiler (gcc/clang)", True, compiler_path)
    else:
        all_ok = False
        hints = {
            "Windows": "scoop install gcc 或者 winget install LLVM.LLVM",
            "Linux": "apt install build-essential clang",
            "Darwin": "brew install gcc llvm"
        }
        _check("C Compiler (gcc/clang)", False, f"未找到，建议运行: {hints.get(sys_name, hints['Linux'])}")
        
    # Check Git Windows tools specifically for MSYS2 utilities
    if sys_name == "Windows":
        git_usr_bin = get_git_usr_bin()
        if git_usr_bin:
            _check("Git Bash Utils (rm, sh 等)", True, git_usr_bin)
        else:
            _check("Git Bash Utils (rm, sh 等)", False, "未找到 Git 附带的 shell 环境，可能导致编译跨平台 C 代码失败。建议: winget install Git.Git")
            
    # --- Cross Compilers ---
    print("\n🌍 Cross Compilers (多架构支持):")
    cross_compilers = {
        "riscv64-linux-musl-cc": {
            "label": "RISC-V CC",
            "hint": "scoop install riscv-none-elf-gcc (Alias: riscv64-linux-musl-cc)"
        },
        "loongarch64-unknown-elf-gcc": {
            "label": "LoongArch CC",
            "hint": "请从龙芯社区下载 Windows 版交叉工具链"
        },
        "arm-none-eabi-gcc": {
            "label": "ARM CC",
            "hint": "winget install Arm.GnuArmEmbeddedToolchain"
        }
    }
    
    for base_name, info in cross_compilers.items():
        found_path = _resolve_lsp_binary(base_name) if use_resolve else shutil.which(base_name)
        if found_path and found_path != base_name:
            _check(info["label"], True, found_path)
        else:
            _check(info["label"], False, f"未找到。建议: {info['hint']}")

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
            "Windows": "rustup component add rust-analyzer",
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
        "zls": {"required": "Zig 分析可选", "install": {
            "Windows": "请参考 https://github.com/zigtools/zls",
            "Linux":   "请参考 https://github.com/zigtools/zls",
            "Darwin":  "请参考 https://github.com/zigtools/zls",
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
            _check(name, False, f'{info["required"]} — 未找到，准备自动执行: {install_hint}')
            
            # Special auto-handle for rust-analyzer if rustup is missing
            if name == "rust-analyzer" and shutil.which("rustup") is None:
                if sys_name == "Windows":
                    print("  [+] 未找到 rustup，开始下载 rustup-init...")
                    try:
                        import urllib.request
                        urllib.request.urlretrieve("https://win.rustup.rs", "rustup-init.exe")
                        print("  [+] 正在静默安装 rustup...")
                        subprocess.run([".\\rustup-init.exe", "-y", "--default-toolchain", "stable"], check=True)
                        os.remove("rustup-init.exe")
                        # Update PATH locally so subprocess can find rustup
                        rust_bin = os.path.expanduser("~/.cargo/bin")
                        os.environ["PATH"] += os.pathsep + rust_bin
                    except Exception as e:
                        all_ok = False
                        _check("rustup 下载/安装", False, f"错误: {e}")
                        continue
                else: # Linux or Darwin
                    print("  [+] 未找到 rustup，正在通过 curl 安装...")
                    try:
                        subprocess.run("curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y", shell=True, check=True)
                        # Update PATH locally so subprocess can find rustup
                        rust_bin = os.path.expanduser("~/.cargo/bin")
                        os.environ["PATH"] += os.pathsep + rust_bin
                    except Exception as e:
                        all_ok = False
                        _check("rustup 下载/安装", False, f"错误: {e}")
                        continue
                
                # Make sure default stable is set after any fresh rustup install
                try:
                    print("  [+] 设置 default stable toolchain...")
                    subprocess.run(["rustup", "default", "stable"], check=True)
                except Exception:
                    pass
                
                print("  [+] 安装 rust-analyzer...")

            # Skip auto-install for zls as it requires manual build/binary download
            if name == "zls":
                all_ok = False
                _check(f"{name} (无法自动安装)", False, f"{install_hint}")
                continue

            try:
                subprocess.run(install_hint, shell=True, check=True)
                _check(f"{name} (自动安装成功)", True, "可能需要重新运行脚本或重启终端使 PATH 生效")
            except subprocess.CalledProcessError:
                all_ok = False
                _check(f"{name} (自动安装失败)", False, f"请手动运行: {install_hint}")

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
