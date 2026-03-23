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

def _detect_linux_pkg_manager():
    """检测 Linux 发行版并返回包管理器及是否需要 sudo。"""
    if platform.system() != "Linux":
        return None, False
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            content = f.read().lower()
        if "debian" in content or "ubuntu" in content or "pop" in content:
            return "apt", True
        if "arch" in content:
            return "pacman", True
        if "fedora" in content or "rhel" in content or "rocky" in content or "alma" in content:
            return "dnf", True
        if "opensuse" in content or "suse" in content:
            return "zypper", True
        if "alpine" in content:
            return "apk", True
    except Exception:
        pass
    return "apt", True  # 默认按 Debian 处理

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
    elif platform.system() == "Linux":
        for d in ["/usr/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin")]:
            p = os.path.join(d, tool_name)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
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
    # 检查 requirements.txt 依赖：dry-run 预检，避免每次运行都触发 pip 重装
    req_path = "requirements.txt"
    if not os.path.isfile(req_path):
        all_ok = False
        _check("requirements.txt 依赖", False, "文件不存在")
    else:
        dry = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--dry-run", "-r", req_path],
            capture_output=True, text=True, timeout=60
        )
        needs_install = ("Would install" in dry.stdout or "Would upgrade" in dry.stdout) or (dry.returncode != 0)
        if needs_install:
            all_ok = False
            _check("requirements.txt 依赖", False, "部分包缺失或版本不符，请运行: pip install -r requirements.txt")
        else:
            _check("requirements.txt 依赖", True, "所有包已满足")
    

    for imp, pip_name in pkgs.items():
        try:
            __import__(imp)
            _check(pip_name, True)
        except ImportError:
            all_ok = False
            _check(pip_name, False, f"未找到，请手动运行: pip install {pip_name}")

    # --- .env file ---
    print("\n⚙️  配置文件:")
    env_exists = os.path.isfile(".env")
    all_ok &= _check(".env 文件", env_exists, "缺失 — 请复制 .env.example 并填写 API_KEY" if not env_exists else "")

    # --- C/C++ Build Tools ---
    print("\n🛠️  C/C++ Build Tools (OS 编译依赖):")
    pkg_mgr, _ = _detect_linux_pkg_manager()
    linux_make = {"apt": "sudo apt install build-essential", "pacman": "sudo pacman -S make",
                  "dnf": "sudo dnf install make", "zypper": "sudo zypper install make",
                  "apk": "sudo apk add make"}.get(pkg_mgr, "sudo apt install build-essential")
    linux_cmake = {"apt": "sudo apt install cmake", "pacman": "sudo pacman -S cmake",
                   "dnf": "sudo dnf install cmake", "zypper": "sudo zypper install cmake",
                   "apk": "sudo apk add cmake"}.get(pkg_mgr, "sudo apt install cmake")
    build_tools = {
        "make": {
            "Windows": "scoop install make 或者 choco install make 或者 winget install ezwinports.make",
            "Linux": linux_make,
            "Darwin": "brew install make"
        },
        "cmake": {
            "Windows": "scoop install cmake 或者 winget install Kitware.CMake",
            "Linux": linux_cmake,
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
        linux_cc = {"apt": "sudo apt install build-essential clang", "pacman": "sudo pacman -S gcc clang",
                    "dnf": "sudo dnf install gcc clang", "zypper": "sudo zypper install gcc clang",
                    "apk": "sudo apk add gcc clang"}.get(pkg_mgr, "sudo apt install build-essential clang")
        hints = {
            "Windows": "scoop install gcc 或者 winget install LLVM.LLVM",
            "Linux": linux_cc,
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
            
    # --- 提前导入 _resolve_lsp_binary，用于 Cross Compilers 和 LSP 工具检查 ---
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from tools.lsp_ops import _resolve_lsp_binary
        use_resolve = True
    except ImportError:
        use_resolve = False

    # --- Cross Compilers ---
    print("\n🌍 Cross Compilers (多架构支持):")
    linux_riscv = {"apt": "sudo apt install gcc-riscv64-linux-gnu", "pacman": "sudo pacman -S riscv64-linux-gnu-gcc",
                   "dnf": "sudo dnf install gcc-riscv64-linux-gnu"}.get(pkg_mgr, "apt 系: sudo apt install gcc-riscv64-linux-gnu")
    linux_arm = {"apt": "sudo apt install gcc-arm-none-eabi", "pacman": "sudo pacman -S arm-none-eabi-gcc",
                 "dnf": "sudo dnf install arm-none-eabi-gcc"}.get(pkg_mgr, "apt 系: sudo apt install gcc-arm-none-eabi")
    cross_compilers = {
        "riscv64-linux-musl-cc": {
            "label": "RISC-V CC",
            "hint": {"Windows": "请前往 https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases",
                    "Linux": linux_riscv,
                    "Darwin": "brew install riscv-none-elf-gcc"}
        },
        "loongarch64-unknown-elf-gcc": {
            "label": "LoongArch CC",
            "hint": {"Windows": "请从龙芯社区 https://github.com/loongson/build-tools 下载",
                    "Linux": "请从 https://github.com/loongson/build-tools 下载或使用发行版包",
                    "Darwin": "请从龙芯社区下载"}
        },
        "arm-none-eabi-gcc": {
            "label": "ARM CC",
            "hint": {"Windows": "winget install Arm.GnuArmEmbeddedToolchain",
                    "Linux": linux_arm,
                    "Darwin": "brew install arm-none-eabi-gcc"}
        }
    }
    
    for base_name, info in cross_compilers.items():
        found_path = _resolve_lsp_binary(base_name) if use_resolve else shutil.which(base_name)
        hint_val = info["hint"]
        hint_str = hint_val.get(sys_name, hint_val.get("Linux", str(hint_val))) if isinstance(hint_val, dict) else hint_val
        if found_path and found_path != base_name:
            _check(info["label"], True, found_path)
        else:
            _check(info["label"], False, f"未找到。建议: {hint_str}")

    # --- LSP tools ---
    print("\n🔧 Language Servers (LSP):")
    linux_rust = {"apt": "rustup component add rust-analyzer 或 sudo apt install rust-analyzer",
                  "pacman": "rustup component add rust-analyzer 或 sudo pacman -S rust-analyzer",
                  "dnf": "rustup component add rust-analyzer 或 sudo dnf install rust-analyzer",
                  "zypper": "rustup component add rust-analyzer 或 sudo zypper install rust-analyzer",
                  "apk": "rustup component add rust-analyzer 或 sudo apk add rust-analyzer"}.get(pkg_mgr, "rustup component add rust-analyzer")
    linux_clangd = {"apt": "sudo apt install clangd", "pacman": "sudo pacman -S clang",
                    "dnf": "sudo dnf install clang-tools-extra", "zypper": "sudo zypper install clang-tools",
                    "apk": "sudo apk add clang"}.get(pkg_mgr, "sudo apt install clangd")
    # install_cmd: 可自动执行的单条命令；install: 展示给用户的完整提示
    lsp_tools = {
        "rust-analyzer": {"required": "Rust OS 分析必需", "install": {
            "Windows": "rustup component add rust-analyzer",
            "Linux":   linux_rust,
            "Darwin":  "brew install rust-analyzer 或 rustup component add rust-analyzer",
        }, "install_cmd": {
            "Windows": "rustup component add rust-analyzer",
            "Linux":   "rustup component add rust-analyzer",
            "Darwin":  "rustup component add rust-analyzer",
        }},
        "clangd": {"required": "C/C++ OS 分析必需", "install": {
            "Windows": "winget install LLVM.LLVM",
            "Linux":   linux_clangd,
            "Darwin":  "brew install llvm",
        }, "install_cmd": {
            "Windows": "winget install LLVM.LLVM",
            "Linux":   linux_clangd,
            "Darwin":  "brew install llvm",
        }},
        "gopls": {"required": "Go OS 分析可选", "install": {
            "Windows": "go install golang.org/x/tools/gopls@latest",
            "Linux":   "go install golang.org/x/tools/gopls@latest",
            "Darwin":  "go install golang.org/x/tools/gopls@latest",
        }, "install_cmd": {
            "Windows": "go install golang.org/x/tools/gopls@latest",
            "Linux":   "go install golang.org/x/tools/gopls@latest",
            "Darwin":  "go install golang.org/x/tools/gopls@latest",
        }},
        "zls": {"required": "Zig 分析可选", "install": {
            "Windows": "请参考 https://github.com/zigtools/zls",
            "Linux":   "请参考 https://github.com/zigtools/zls",
            "Darwin":  "请参考 https://github.com/zigtools/zls",
        }, "install_cmd": None},
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
            install_cmd = info.get("install_cmd")
            run_cmd = (install_cmd.get(sys_name, install_cmd.get("Linux")) if install_cmd else None)
            _check(name, False, f'{info["required"]} — 未找到' + (f'，准备自动执行: {run_cmd}' if run_cmd else f'，建议: {install_hint}'))
            
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

            if not run_cmd:
                all_ok = False
                continue

            try:
                subprocess.run(run_cmd, shell=True, check=True)
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
