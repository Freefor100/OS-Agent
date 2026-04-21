"""
LSP Operations Tool (Dynamic Multiplexing Gateway)
"""
import os

def _abspath(p: str) -> str:
    res = os.path.abspath(p)
    if os.name == 'nt' and len(res) >= 2 and res[1] == ':':
        # 强制将 Windows 盘符大写化，确保与 Cargo Metadata 的物理路径输出一致，防止 rust-analyzer 产生 VFS 分叉
        return res[0].upper() + res[1:]
    return res
import re
import json
import asyncio
import logging
import threading
import atexit
import platform
from typing import Dict, Any, Optional, List, Tuple

from langchain.tools import tool

logger = logging.getLogger("lsp_ops")
logger.setLevel(logging.INFO)

# --- 阶段 1：编译配置的深度扫描 (Pre-flight Workspace Scan) ---
def _pre_flight_workspace_scan(repo_path: str) -> Dict[str, bool]:
    """探测核心构建配置是否存在"""
    return {
        "compile_commands.json": os.path.exists(os.path.join(repo_path, "compile_commands.json")),
        "Makefile": os.path.exists(os.path.join(repo_path, "Makefile")),
        "CMakeLists.txt": os.path.exists(os.path.join(repo_path, "CMakeLists.txt")),
        "Cargo.toml": os.path.exists(os.path.join(repo_path, "Cargo.toml")),
        "build.zig": os.path.exists(os.path.join(repo_path, "build.zig")),
        "go.mod": os.path.exists(os.path.join(repo_path, "go.mod")),
    }

async def _ensure_cargo_fetched(repo_path: str):
    """Run `cargo fetch` once per repo so rust-analyzer can resolve all dependencies.
    
    This function should be called within an async context using asyncio.to_thread if we want to avoid blocking, 
    but since we are moving it here, we will change it to an async function.
    
    Without this, rust-analyzer crashes when Cargo.toml has git dependencies
    that haven't been downloaded yet. Uses a marker file to avoid re-fetching.
    """
    import subprocess
    import shutil
    
    marker = os.path.join(repo_path, ".lsp_cargo_fetched")
    if os.path.exists(marker):
        return  # already fetched
    
    cargo = shutil.which("cargo")
    if not cargo:
        # Try common fallback paths
        home = os.path.expanduser("~")
        for candidate in [os.path.join(home, ".cargo", "bin", "cargo.exe"),
                         os.path.join(home, ".cargo", "bin", "cargo")]:
            if os.path.isfile(candidate):
                cargo = candidate
                break
    
    if not cargo:
        logger.warning("cargo not found — skipping cargo fetch. rust-analyzer may fail on git dependencies.")
        return
    
    logger.info(f"Running 'cargo fetch' in {repo_path} (first-time LSP setup, may take 1-2 minutes)...")
    try:
        # Use asyncio.create_subprocess_exec to avoid blocking the event loop
        process = await asyncio.create_subprocess_exec(
            cargo, "fetch",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180)
            if process.returncode == 0:
                logger.info(f"cargo fetch completed successfully in {repo_path}")
            else:
                logger.warning(f"cargo fetch failed (rc={process.returncode}): {stderr.decode('utf-8')[:300]}\nProceeding anyway with partial deps.")
        except asyncio.TimeoutError:
            process.kill()
            logger.warning("cargo fetch timed out after 180s — continuing without full dependency resolution")
    except Exception as e:
        logger.warning(f"cargo fetch error: {e} — continuing anyway")
    finally:
        # ALWAYS write marker so we don't repeatedly fetch and hang on broken repos
        try:
            with open(marker, 'w') as f:
                f.write("ok")
        except Exception:
            pass

# --- 阶段 2：编译上下文的动态生成 (Dynamic Context Polyfill) ---
def _detect_target_arch(repo_path: str) -> Optional[str]:
    """尝试从仓库结构中推测目标架构 (riscv64, loongarch64 etc)"""
    # 0. 极高优先级：检查 LLM 手动设置的本地标记文件
    override_marker = os.path.join(repo_path, ".os_agent_lsp_target")
    if os.path.exists(override_marker):
        try:
            with open(override_marker, 'r', encoding='utf-8') as f:
                target = f.read().strip()
                if target:
                    logger.info(f"Using LLM-driven target override from {override_marker}: {target}")
                    return target
        except Exception:
            pass

    # 1. 优先使用环境变量强制覆盖
    target = os.environ.get("LSP_TARGET")
    if target:
        return target
    
    # 2. 检查常见的目录名
    arch_dir = os.path.join(repo_path, "os", "src", "arch")
    if os.path.exists(arch_dir):
        subdirs = [d for d in os.listdir(arch_dir) if os.path.isdir(os.path.join(arch_dir, d))]
        # 优先级探测：如果同时存在，目前保持现有顺序，但增加 la64 识别
        if "riscv64" in subdirs: return "riscv64gc-unknown-none-elf"
        if "loongarch64" in subdirs or "la64" in subdirs: return "loongarch64-unknown-none-elf"
        if "x86_64" in subdirs: return "x86_64-unknown-none-elf"
        if "aarch64" in subdirs: return "aarch64-unknown-none-elf"
    
    # 3. 语义搜索 (启发式)
    try:
        # 只看核心模块
        for root, dirs, files in os.walk(os.path.join(repo_path, "os", "src")):
            if "target" in dirs: dirs.remove("target")
            for f in files:
                if f.endswith(".rs"):
                    with open(os.path.join(root, f), 'r', encoding='utf-8', errors='ignore') as f_in:
                        content = f_in.read(2048) # 只看开头
                        if 'target_arch = "riscv64"' in content: return "riscv64gc-unknown-none-elf"
                        if 'target_arch = "loongarch64"' in content: return "loongarch64-unknown-none-elf"
    except:
        pass
        
    return None

async def _polyfill_context(repo_path: str, scan_results: Dict[str, bool], lang: str):
    async with _get_polyfill_lock(repo_path):
        # C/C++ (clangd) 补全逻辑
        # 哪怕有 Makefile/CMakeLists，如果没有 compile_commands.json，clangd 依然是个瞎子
        has_c_config = False
        if lang in ["c", "cpp"]:
            has_c_config = scan_results.get("compile_commands.json", False)

        if lang in ["c", "cpp"] and not has_c_config:
            compile_flags_path = os.path.join(repo_path, "compile_flags.txt")
            # 总是重新生成，以防克隆后文件变动
            include_dirs = {_abspath(repo_path)}
            for root, dirs, files in os.walk(repo_path):
                # 跳过无关目录，防止生成的 flags 过载
                dirs[:] = [d for d in dirs if d not in {".git", ".github", "target", "vendor", "node_modules", "build", "dist"}]
                if any(f.endswith('.h') or f.endswith('.hpp') for f in files):
                    include_dirs.add(_abspath(root))
                    # Also add the parent directory to handle includes like "proc/thread.h"
                    include_dirs.add(os.path.dirname(_abspath(root)))
                # If the directory is named 'include', proactively add it even if it directly contains no headers
                if os.path.basename(os.path.normpath(root)) == "include":
                    include_dirs.add(_abspath(root))
            if include_dirs:
                try:
                    with open(compile_flags_path, 'w', encoding='utf-8') as f:
                        # 声明这大概率是一个 C 语言或 C++ 内核项目
                        f.write("-xc\n")

                        # 裸机/内核环境标志：
                        # -ffreestanding: 告知 clangd 不假设标准 C 运行时存在（无 main 入口、无 libc）
                        # -fno-builtin:   禁止将 exit/exec/memcpy 等识别为编译器内建函数，
                        #                 避免与内核自定义同名函数冲突导致 prepareCallHierarchy 失败
                        f.write("-ffreestanding\n")
                        f.write("-fno-builtin\n")

                        # 注入交叉编译目标架构，防止 clangd 在 x86 主机上解析异构汇编报错
                        target_arch = _detect_target_arch(repo_path)
                        if target_arch:
                            base_arch = target_arch.split('-')[0].replace('gc', '')
                            f.write(f"--target={base_arch}\n")

                        # 将根目录和所有包含头文件的目录加入搜索路径
                        for d in include_dirs:
                            # 对于 Windows 上的 clangd，路径中的反斜杠可能需要转义或统一替换为正斜杠
                            sanitized_path = d.replace('\\', '/')
                            f.write(f"-I{sanitized_path}\n")
                except Exception as e:
                    logger.error(f"Failed to generate compile_flags.txt: {e}")

        # Rust (rust-analyzer) 补全逻辑
        if lang == "rust":
            if not scan_results["Cargo.toml"]:
                has_rs = False
                for root, dirs, files in os.walk(repo_path):
                    dirs[:] = [d for d in dirs if d not in {".git", "target", "vendor"}]
                    if any(f.endswith('.rs') for f in files):
                        has_rs = True
                        break

                if has_rs:
                    cargo_toml_path = os.path.join(repo_path, "Cargo.toml")
                    if not os.path.exists(cargo_toml_path):
                        # 收集子目录中的所有 Cargo.toml 路径，组装成 workspace members
                        members = []
                        for root, dirs, files in os.walk(repo_path):
                            dirs[:] = [d for d in dirs if d not in {".git", "target", "vendor", ".github"}]
                            if root != repo_path and "Cargo.toml" in files:
                                rel_path = os.path.relpath(root, repo_path).replace('\\', '/')
                                members.append(rel_path)

                        try:
                            with open(cargo_toml_path, 'w', encoding='utf-8') as f:
                                if members:
                                    # 这种情况下生成 "Virtual Manifest"，即只有 [workspace] 而没有 [package]
                                    # 这样 cargo metadata 就不会报错要求根目录必须有 src/lib.rs 了
                                    f.write('[workspace]\nmembers = [\n')
                                    for m in members:
                                        f.write(f'    "{m}",\n')
                                    f.write(']\n')
                                else:
                                    f.write('[package]\nname = "os_kernel_dummy"\nversion = "0.1.0"\nedition = "2021"\n')
                        except Exception as e:
                            logger.error(f"Failed to generate Cargo.toml: {e}")

                    # 如果存在 Cargo.toml，检查是否存在有效的 target 文件 (src/lib.rs 或 src/main.rs) 或者包含 members
                    # 防止 rust-analyzer 的 cargo metadata 报错 `no targets specified in the manifest` 而彻底罢工
                    if os.path.exists(cargo_toml_path):
                        with open(cargo_toml_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        # 只有如果是 [package] 类型的 manifest 且没有目标文件时，才强制创建 dummy src
                        # Virtual Manifest ([workspace]) 模式下不需要也不能在根目录创建 src/lib.rs
                        if "[package]" in content:
                            src_dir = os.path.join(repo_path, "src")
                            has_target = os.path.exists(os.path.join(src_dir, "lib.rs")) or os.path.exists(os.path.join(src_dir, "main.rs"))
                            if not has_target:
                                os.makedirs(src_dir, exist_ok=True)
                                try:
                                    with open(os.path.join(src_dir, "lib.rs"), 'w', encoding='utf-8') as f:
                                        f.write("// Dummy lib created by os-agent to satisfy rust-analyzer workspace loader\n")
                                except Exception as e:
                                    logger.error(f"Failed to generate dummy src/lib.rs: {e}")

            # Rust: cargo fetch — 让 rust-analyzer 能解析 git 远程依赖
            if scan_results["Cargo.toml"] or os.path.exists(os.path.join(repo_path, "Cargo.toml")):
                await _ensure_cargo_fetched(repo_path)

# --- 阶段 3：多路复用 LSP 客户端构建 (Multiplexing LSP Gateway) ---
class LSPClient:
    def __init__(self, cmd: List[str], cwd: str):
        self.cmd = cmd
        self.cwd = cwd
        self.process: Optional[asyncio.subprocess.Process] = None
        self.request_id = 0
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.initialized_event = asyncio.Event()
        self._dead = False  # marked True when reader_loop exits
        self.opened_uris = set()
        self.build_scripts_disabled = False
        self.build_script_failed = False

    @property
    def is_alive(self) -> bool:
        """Check if the LSP subprocess is still running."""
        if self._dead:
            return False
        if self.process is None:
            return False
        # In asyncio.subprocess, returncode is None until you read it or wait for it.
        # But if the reader loop marked _dead=True, we already know it's dead.
        return self.process.returncode is None

    async def start(self, disable_build_scripts: bool = False):
        self._dead = False
        self.build_scripts_disabled = disable_build_scripts
        env = os.environ.copy()
        
        # 强化外部路径注入：确保 rust-analyzer 能看到 check_env.py 深度扫描到的 make 和 cmake
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(_abspath(__file__))))
            from check_env import _find_build_tool, get_git_usr_bin
            
            extra_paths = []
            for tool in ["make", "cmake", "gcc", "clang"]:
                p = _find_build_tool(tool)
                if p:
                    extra_paths.append(os.path.dirname(p))
            
            # --- 交叉编译器注入 (Multi-Arch Context) ---
            target_arch = _detect_target_arch(self.cwd)
            # 定义架构到编译器的映射
            arch_to_cc = {
                "riscv64": "riscv64-linux-musl-cc",
                "riscv32": "riscv64-linux-musl-cc",
                "aarch64": "arm-none-eabi-gcc",
                "arm": "arm-none-eabi-gcc",
                "loongarch64": "loongarch64-unknown-elf-gcc",
            }
            
            # 无论是否匹配架构，先扫描所有已知编译器并注入 PATH
            for arch_key, cc_base in arch_to_cc.items():
                cc_path = _resolve_lsp_binary(cc_base, cwd=self.cwd)
                if os.path.isabs(cc_path):
                    cc_dir = os.path.dirname(cc_path)
                    if cc_dir not in extra_paths:
                        extra_paths.append(cc_dir)
                    
                    # 如果匹配当前检测到的架构，或者尚未设置 CC，则注入环境变量
                    if (target_arch and arch_key in target_arch.lower()) or "CC" not in env:
                        env["CC"] = cc_path
                        env["CXX"] = cc_path.replace("gcc", "g++").replace("-cc", "-c++")
                        ld_base = cc_base.replace("-cc", "-ld").replace("-gcc", "-ld")
                        ld_path = _resolve_lsp_binary(ld_base, cwd=self.cwd)
                        if os.path.isabs(ld_path):
                            env["LD"] = ld_path

            # Windows 特供：注入 Git 内置的 Linux 命令环境 (包含 rm, test, sh 等)，解决跨平台 Makefile 报错
            if platform.system() == "Windows":
                git_usr_bin = get_git_usr_bin()
                if git_usr_bin and git_usr_bin not in extra_paths:
                    extra_paths.append(git_usr_bin)
            
            if extra_paths:
                # prepend the discovered tool directories to PATH
                current_path = env.get("PATH", "")
                env["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + current_path
        except Exception as e:
            logger.warning(f"Failed to inject check_env build tool paths into LSP environment: {e}")

        # 强化隔离：防止在线拉取卡死，允许不稳定特性 (全局对 rust-analyzer 生效)
        if "rust-analyzer" in self.cmd[0]:
            # 强制解除 Windows 平台下目标仓库通过 rust-toolchain.toml 锁定极其古老版本 (比如 nightly-2024-02-03) 
            # 导致的 line-index offset panic BUG，直接提权使用 stable 通道下最新修复版的 rust-analyzer
            env["RUSTUP_TOOLCHAIN"] = "stable"
            # 出于稳定性考量目前暂不强制阻断网络，使得 metadata 能够去拉取最新版本 crate
            # env["CARGO_NET_OFFLINE"] = "true" 
            env["RUSTC_BOOTSTRAP"] = "1"

        if disable_build_scripts and "rust-analyzer" in self.cmd[0]:
            # 核心漏洞防御：阻止 rust-analyzer 执行目标机器特有的、可能直接 Crash 的构建脚本
            env["RUST_ANALYZER_CARGO_RUN_BUILD_SCRIPTS"] = "false"
            env["RUST_ANALYZER_CARGO_FEATURES"] = "all"
            env["RUST_ANALYZER_CARGO_NO_DEFAULT_FEATURES"] = "false"
            # 终极 Workspace 防御：忽略不存在的 target 报错
            env["RUST_ANALYZER_CARGO_UNSET_TEST"] = "true"
            env["CARGO_TARGET_DIR"] = os.path.join(self.cwd, ".os_agent_ra_target")
        
        self.process = await asyncio.create_subprocess_exec(
            *self.cmd,
            cwd=self.cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        asyncio.create_task(self._reader_loop())
        asyncio.create_task(self._stderr_loop())
        await self._initialize()
        
    async def _stderr_loop(self):
        """Consume and log stderr so we know WHY the LSP process crashes."""
        # Fatal 关键词：命中时标记 build_script_failed
        _fatal_keywords = [
            "failed to run custom build command", "could not compile",
            "linker `cc` not found", "program not found",
            "crashed", "fatal error", "SIGSEGV", "Assertion failed",
        ]
        # 纯 LSP 协议收发行前缀：仅做 debug，避免淹没有用信息
        # 形如 "I[...] <-- textDocument/didOpen" 或 "I[...] --> reply:callHierarchy/..."
        _protocol_prefixes = ("<--", "-->")

        while self.process and self.process.stderr:
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                decoded_line = line.decode('utf-8', errors='ignore').strip()
                if not decoded_line:
                    continue

                if any(kw in decoded_line for kw in _fatal_keywords):
                    # 真正的错误：WARNING + 标记
                    logger.warning(f"LSP [{self.cmd[0]}] STDERR: {decoded_line}")
                    self.build_script_failed = True
                elif any(p in decoded_line for p in _protocol_prefixes):
                    # 纯 LSP 协议收发追踪行：降为 DEBUG（不污染日志）
                    logger.debug(f"LSP [{self.cmd[0]}] STDERR: {decoded_line}")
                else:
                    # 有意义的 clangd 状态行（ASTWorker、preamble、compilation db 等）
                    logger.warning(f"LSP [{self.cmd[0]}] STDERR: {decoded_line}")
            except Exception:
                break

    async def _initialize(self):
        # Build proper file URI — Windows needs file:///C:/... (3 slashes)
        raw_abs = _abspath(self.cwd).replace(chr(92), '/')
        # 移除 Windows 扩展路径前缀 //?/ 以免干扰某些 Linux 风格的构建工具 (如 make)
        if raw_abs.startswith('//?/'):
            abs_cwd = raw_abs[4:]
        else:
            abs_cwd = raw_abs
            
        if not abs_cwd.startswith('/'):
            abs_cwd = '/' + abs_cwd  # Windows: /C:/Users/...
        root_uri = f"file://{abs_cwd}"
        
        init_req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "capabilities": {
                    # 强硬声明：客户端的 offset 规范严格遵守 UTF-16 code units (解决多字节和中文混合 panic)
                    "offsetEncoding": ["utf-16"],
                    "general": {
                        "positionEncodings": ["utf-16"]
                    },
                    "textDocument": {
                        "callHierarchy": {"dynamicRegistration": False},
                        "synchronization": {"dynamicRegistration": False}
                    }
                },
                "initializationOptions": {
                    "cargo": {
                        "buildScripts": {
                            "enable": not getattr(self, "build_scripts_disabled", False)
                        },
                        "target": _detect_target_arch(self.cwd),
                    },
                    "checkOnSave": False
                } if "rust-analyzer" in self.cmd[0] else {}
            }
        }
        await self.send_request(init_req)
        
        # LSP spec REQUIRES 'initialized' notification after initialize response
        await self.send_notification({
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {}
        })
        
        # Give server time to start workspace indexing (rust-analyzer needs this for cargo workspaces)
        await asyncio.sleep(5.0)
        self.initialized_event.set()

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    async def _reader_loop(self):
        while True:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break  # EOF — process exited
                
                line_str = line.decode('utf-8').strip()
                if not line_str.startswith("Content-Length:"):
                    continue  # skip non-header lines (stderr leakage, etc.)
                
                content_length = int(line_str.split(":")[1].strip())
                
                # Read remaining headers until empty line
                while True:
                    header_line = await self.process.stdout.readline()
                    if not header_line or header_line.strip() == b'':
                        break
                
                # Read Body strictly by Content-Length
                body = await self.process.stdout.readexactly(content_length)
                response = json.loads(body.decode('utf-8'))
                
                res_id = response.get("id")
                if res_id is not None and res_id in self.pending_requests:
                    self.pending_requests[res_id].set_result(response)
                # else: server notification (progress, diagnostics, etc.) — ignore
                    
            except asyncio.IncompleteReadError:
                break  # pipe closed
            except (ConnectionError, BrokenPipeError, OSError):
                break  # connection lost
            except json.JSONDecodeError as e:
                logger.debug(f"LSP reader: malformed JSON, skipping: {e}")
                continue  # don't die on one bad message
            except Exception as e:
                logger.warning(f"LSP reader loop error (non-fatal): {e}")
                continue  # keep reading — don't kill connection on transient errors
                
        # 标记客户端已死亡，清理所有挂起的请求
        self._dead = True
        logger.warning(f"LSP process {self.cmd[0]} exited (reader_loop ended). Marking client as dead. Check STDERR above for crash reason.")
        for fut in self.pending_requests.values():
            if not fut.done() and not fut.cancelled():
                fut.set_exception(RuntimeError("LSP process terminated unexpectedly"))
        self.pending_requests.clear()

    async def send_request(self, message: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = message.get("id")
        fut = None
        if msg_id is not None:
            fut = asyncio.get_running_loop().create_future()
            self.pending_requests[msg_id] = fut

        # 最高优先级：基于 len(bytes) 构建精确的 Content-Length
        payload_bytes = json.dumps(message, separators=(',', ':')).encode('utf-8')
        content_length = len(payload_bytes)
        header = f"Content-Length: {content_length}\r\n\r\n".encode('utf-8')
        
        try:
            self.process.stdin.write(header + payload_bytes)
            await self.process.stdin.drain()
        except Exception as e:
            if fut and not fut.done():
                fut.set_exception(e)
            raise e

        if msg_id is not None:
            try:
                # rust-analyzer needs time for large cargo workspaces with git deps
                res = await asyncio.wait_for(fut, timeout=30.0)
                return res
            except asyncio.TimeoutError:
                raise TimeoutError("LSP request timed out")
            finally:
                if msg_id in self.pending_requests:
                    del self.pending_requests[msg_id]
        return {}

    async def send_notification(self, message: Dict[str, Any]):
        payload_bytes = json.dumps(message, separators=(',', ':')).encode('utf-8')
        header = f"Content-Length: {len(payload_bytes)}\r\n\r\n".encode('utf-8')
        self.process.stdin.write(header + payload_bytes)
        await self.process.stdin.drain()

    async def stop(self):
        if self.process:
            try:
                self.process.stdin.write(b"Content-Length: 0\r\n\r\n")
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=3.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass


def _resolve_lsp_binary(base_name: str, cwd: Optional[str] = None) -> str:
    """Resolve LSP binary path with cross-platform fallback and alias support.
    
    Args:
        base_name: The target tool name (e.g., 'riscv64-linux-musl-cc')
        cwd: Current working directory
    """
    import shutil
    import platform
    import subprocess
    
    # 别名映射：允许一个工具对应多个可能的名称（比如在不同系统或分发版下）
    aliases = {
        # Arch/Debian 常见为 riscv64-linux-gnu-gcc（pacman/apt），而非 musl-cc / bare-metal 名
        "riscv64-linux-musl-cc": [
            "riscv64-linux-musl-cc",
            "riscv64-linux-gnu-gcc",
            "riscv-none-elf-gcc",
            "riscv64-unknown-elf-gcc",
        ],
        "riscv64-linux-musl-ld": [
            "riscv64-linux-musl-ld",
            "riscv64-linux-gnu-ld",
            "riscv-none-elf-ld",
            "riscv64-unknown-elf-ld",
        ],
        "arm-none-eabi-gcc": [
            "arm-none-eabi-gcc",
            "aarch64-linux-gnu-gcc",
            "arm-linux-gnueabi-gcc",
            "arm-linux-gnueabihf-gcc",
            "arm-none-linux-gnueabihf-gcc",
        ],
        "arm-none-eabi-ld": [
            "arm-none-eabi-ld",
            "aarch64-linux-gnu-ld",
            "arm-linux-gnueabi-ld",
            "arm-linux-gnueabihf-ld",
        ],
        "loongarch64-unknown-elf-gcc": ["loongarch64-unknown-elf-gcc", "loongarch64-linux-gnu-gcc", "loongarch64-unknown-linux-gnu-gcc"],
        # xpack RISC-V 工具链别名（Windows 安装的实际可执行文件名）
        "riscv-none-elf-gcc": ["riscv-none-elf-gcc", "riscv64-unknown-elf-gcc", "riscv64-linux-musl-cc"],
    }
    
    search_names = aliases.get(base_name, [base_name])
    
    # --- 1. 特殊逻辑：rust-analyzer 的自动安装与 rustup 环境处理 ---
    if base_name == "rust-analyzer":
        try:
            # Bypass rustup proxy bug on Windows
            res = subprocess.run(["rustup", "which", "rust-analyzer"], cwd=cwd, capture_output=True, text=True, check=True)
            candidate = res.stdout.strip()
            if candidate and os.path.isfile(candidate):
                return candidate
        except Exception:
            # 尝试自动安装
            try:
                subprocess.run(["rustup", "component", "add", "rust-analyzer"], cwd=cwd, capture_output=True)
                res2 = subprocess.run(["rustup", "which", "rust-analyzer"], cwd=cwd, capture_output=True, text=True)
                candidate2 = res2.stdout.strip()
                if candidate2 and os.path.isfile(candidate2):
                    return candidate2
            except Exception:
                pass

    # --- 2. 基于 PATH 的搜索 (优先尝试所有别名) ---
    for name in search_names:
        found = shutil.which(name)
        if found:
            return found
    
    # --- 3. 平台特定的后备路径搜索 ---
    home = os.path.expanduser("~")
    system = platform.system()
    ext = ".exe" if system == "Windows" else ""
    
    for name in search_names:
        candidates = []
        candidates.append(os.path.join(home, ".cargo", "bin", f"{name}{ext}"))
        # Go 工具链默认安装到 ~/go/bin（gopls、dlv 等）
        candidates.append(os.path.join(home, "go", "bin", f"{name}{ext}"))
        
        if system == "Windows":
            candidates.append(os.path.join(home, "AppData", "Local", name, f"{name}.exe"))
            candidates.append(os.path.join(home, "scoop", "shims", f"{name}.exe"))
            if name == "clangd":
                candidates.append(r"C:\Program Files\LLVM\bin\clangd.exe")

            # ── 已知 Windows 工具链硬编码路径 ──────────────────────────────
            import glob as _glob
            # xpack RISC-V（支持所有版本，通配符匹配）
            if "riscv" in name:
                for xpack_bin in _glob.glob(r"C:\xpack-riscv-none-elf-gcc-*\bin"):
                    candidates.append(os.path.join(xpack_bin, f"{name}.EXE"))
                    candidates.append(os.path.join(xpack_bin, f"{name}.exe"))
                    # xpack 内部的实际可执行文件名可能与 canonical name 不同
                    candidates.append(os.path.join(xpack_bin, "riscv-none-elf-gcc.EXE"))
            # Arm GNU Toolchain (arm-none-eabi)
            if "arm" in name and "linux" not in name:
                for arm_bin in _glob.glob(r"C:\Program Files (x86)\Arm GNU Toolchain arm-none-eabi\*\bin"):
                    candidates.append(os.path.join(arm_bin, f"{name}.EXE"))
                    candidates.append(os.path.join(arm_bin, f"{name}.exe"))
                    candidates.append(os.path.join(arm_bin, "arm-none-eabi-gcc.EXE"))
            # ─────────────────────────────────────────────────────────────

            # WinGet Packages 递归搜索
            local_appdata = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
            winget_base = os.path.join(local_appdata, "Microsoft", "WinGet", "Packages")
            if os.path.isdir(winget_base):
                patterns = [
                    os.path.join(winget_base, f"*{name}*", f"{name}.exe"),
                    os.path.join(winget_base, f"*{name}*", "*", f"{name}.exe"),
                ]
                for p in patterns:
                    for match in _glob.glob(p):
                        if os.path.isfile(match):
                            candidates.append(match)
        elif system == "Darwin":
            candidates.append(f"/opt/homebrew/bin/{name}")
            candidates.append(f"/usr/local/bin/{name}")
        else:
            candidates.append(f"/usr/bin/{name}")
            candidates.append(f"/usr/local/bin/{name}")
            candidates.append(os.path.join(home, ".local", "bin", name))
        # 龙芯交叉工具链常见解压路径（未加入 PATH 时 check_env / LSP 仍可探测）
            if "loongarch" in name:
                candidates.append(os.path.join("/opt", "loongarch64-tools", "bin", name))
           
        for c in candidates:
            if os.path.isfile(c):
                logger.info(f"Resolved {base_name} via {name} at fallback path: {c}")
                return c
    
    logger.debug(f"Failed to resolve any candidates for {base_name}: {search_names}")
    return base_name

class MultiplexingLSPGateway:
    def __init__(self):
        self.clients: Dict[str, LSPClient] = {}
        self.lock = asyncio.Lock()

    async def get_client(self, repo_path: str, lang: str) -> Optional[LSPClient]:
        abs_repo = _abspath(repo_path)
        key = f"{abs_repo}_{lang}"
        
        async with self.lock:
            # Check cache — evict dead clients
            if key in self.clients:
                existing = self.clients[key]
                if existing.is_alive:
                    return existing
                else:
                    logger.warning(f"Evicting dead LSP client for {lang}, will restart.")
                    try:
                        await existing.stop()
                    except Exception:
                        pass
                    del self.clients[key]

            scan_res = _pre_flight_workspace_scan(abs_repo)
            await _polyfill_context(abs_repo, scan_res, lang)

            cmd = []
            if lang in ["c", "cpp"]:
                clangd_path = _resolve_lsp_binary("clangd", cwd=abs_repo)
                cmd = [clangd_path]

                # 注入 query-driver 允许 clangd 调用交叉编译器提取系统头文件路径
                # 这是一个逗号分隔的通配符/路径列表。我们把探测到的所有已知交叉编译器都加进去。
                drivers = [
                    "riscv64-unknown-elf-gcc", "riscv64-linux-musl-cc", "riscv-none-elf-gcc",
                    "loongarch64-unknown-elf-gcc", "loongarch64-linux-gnu-gcc",
                    "arm-none-eabi-gcc", "arm-linux-gnueabi-gcc"
                ]
                resolved_drivers = []
                for d in drivers:
                    p = _resolve_lsp_binary(d, cwd=abs_repo)
                    if os.path.isabs(p):
                        resolved_drivers.append(p.replace('\\', '/'))
                
                if resolved_drivers:
                    # 去重并组装参数
                    driver_patterns = ",".join(list(dict.fromkeys(resolved_drivers)))
                    cmd.append(f"--query-driver={driver_patterns}")
                    logger.info(f"Injected clangd --query-driver with: {driver_patterns}")
                    
                # 额外增加一些通用的标志以提升分析稳定性
                cmd.extend(["--background-index", "--clang-tidy", "--header-insertion=never"])
            elif lang == "rust":
                cmd = [_resolve_lsp_binary("rust-analyzer", cwd=abs_repo)]
            elif lang == "go":
                cmd = [_resolve_lsp_binary("gopls", cwd=abs_repo)]
            elif lang == "zig":
                cmd = [_resolve_lsp_binary("zls", cwd=abs_repo)]
            else:
                return None

            try:
                # 必须在这个单例锁内加上全局锁，防止 OOM 轰炸
                async with _lsp_global_lock:
                    client = LSPClient(cmd, abs_repo)
                    await client.start(disable_build_scripts=False)
                    # Give rust-analyzer time to start indexing (large workspaces)
                    await asyncio.sleep(2.0)
                    
                    # Check if it crashed immediately or build script failed (e.g. panicking build.rs)
                    if (not client.is_alive or getattr(client, "build_script_failed", False)) and lang == "rust":
                        logger.warning(f"LSP {cmd[0]} died or build script failed. Retrying with build scripts disabled.")
                        try:
                            await client.stop()
                        except Exception:
                            pass
                        client = LSPClient(cmd, abs_repo)
                        await client.start(disable_build_scripts=True)
                        await asyncio.sleep(2.0)
                        
                if not client.is_alive:
                    logger.error(f"Failed to start LSP {cmd[0]}: Process died after startup.")
                    return None
                    
                self.clients[key] = client
                logger.info(f"LSP {cmd[0]} started successfully for {abs_repo}")
                return client
            except Exception as e:
                logger.error(f"Failed to start LSP {cmd[0]}: {e}")
                return None

    async def force_restart_client(self, repo_path: str, lang: str):
        """强制清理并关闭特定语言的 LSP 客户端，以便在配置更改（如架构切换）后重建。

        加锁顺序必须与 get_client 保持一致：先 self.lock，再 _lsp_global_lock。
        否则会与“先拿全局锁、再进 gateway 锁”的路径形成 ABBA 死锁。
        """
        abs_repo = _abspath(repo_path)
        key = f"{abs_repo}_{lang}"
        async with self.lock:
            async with _lsp_global_lock:
                if key in self.clients:
                    logger.info(f"Force restarting LSP client for {lang} in {abs_repo}...")
                    client = self.clients.pop(key)
                    try:
                        await client.stop()
                    except Exception:
                        pass

    async def stop_all(self):
        async with self.lock:
            for client in self.clients.values():
                await client.stop()
            self.clients.clear()

# 在单独的后台线程中启动持久的事件循环，维护持久化的 LSP 子进程生命周期
_lsp_loop = asyncio.new_event_loop()
def _start_lsp_loop(loop):
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

_lsp_thread = threading.Thread(target=_start_lsp_loop, args=(_lsp_loop,), daemon=True)
_lsp_thread.start()

_gateway = MultiplexingLSPGateway()
# 全局并发锁：防止大模型并发调用多个 LSP 搜索导致 LSP 服务端直接崩溃
_lsp_global_lock = asyncio.Lock()
_polyfill_lock_guard = threading.Lock()
_polyfill_repo_locks = {}


def _get_polyfill_lock(repo_path: str):
    key = _abspath(repo_path)
    with _polyfill_lock_guard:
        if key not in _polyfill_repo_locks:
            _polyfill_repo_locks[key] = asyncio.Lock()
        return _polyfill_repo_locks[key]


def _cancel_future_safely(future):
    try:
        future.cancel()
    except Exception:
        pass

def _cleanup_lsp():
    # 退出前清理子进程
    if _lsp_loop.is_running():
        asyncio.run_coroutine_threadsafe(_gateway.stop_all(), _lsp_loop).result(timeout=5.0)
atexit.register(_cleanup_lsp)


# --- 阶段 4：接口封装与汇编降级 (API Wrapper & ASM Fallback) ---
class ASMLexicalParser:
    """正则表达式匹配机制，强制作为 .S 或 .asm 文件及高级语言超时的降级方案"""
    @staticmethod
    def fallback_definition(repo_path: str, file_path: str, symbol: str) -> str:
        abs_path = _abspath(os.path.join(repo_path, file_path))
        if not os.path.exists(abs_path):
            return f"Error: 文件未找到 {abs_path}"
        
        matches = []
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                for idx, line in enumerate(f, 1):
                    # 匹配伪指令 .globl/global 或宏定义，或标签 (symbol:)
                    if re.search(rf'^\s*{re.escape(symbol)}\s*:', line) or \
                       re.search(rf'^\s*\.globl\s+{re.escape(symbol)}', line) or \
                       re.search(rf'^\s*\.global\s+{re.escape(symbol)}', line) or \
                       re.search(rf'^\s*\.macro\s+{re.escape(symbol)}', line):
                        matches.append(f"{file_path}:{idx}: {line.strip()}")
            
            if matches:
                return f"[ASM Fallback] 找到 {symbol} 的定义:\n" + "\n".join(matches)
            return f"[ASM Fallback] 未在 {file_path} 找到 {symbol} 的显式定义。"
        except Exception as e:
            return f"ASM 解析失败: {e}"
            
    @staticmethod
    def fallback_references(repo_path: str, file_path: str, symbol: str) -> str:
        abs_path = _abspath(os.path.join(repo_path, file_path))
        if not os.path.exists(abs_path):
            return f"Error: 文件未找到 {abs_path}"
        
        matches = []
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                for idx, line in enumerate(f, 1):
                    if re.search(rf'\b{re.escape(symbol)}\b', line):
                        content = line.strip()
                        if len(content) > 100:
                            content = content[:100] + "..."
                        matches.append(f"{file_path}:{idx}: {content}")
            if matches:
                 return f"[ASM Fallback] 找到 {symbol} 的粗略引用 (共 {len(matches)} 处):\n" + "\n".join(matches[:20]) + ("\n... (截断剩余结果)" if len(matches)>20 else "")
            return f"[ASM Fallback] 未在 {file_path} 找到 {symbol} 的引用。"
        except Exception as e:
            return f"ASM 解析失败: {e}"


def _fallback_metadata(fallback_path: str, confidence: str, reason: str) -> str:
    return (
        "\n"
        f"[Fallback Metadata] fallback_path={fallback_path}; "
        f"confidence={confidence}; reason={reason}"
    )


def _extract_hits_from_result(result: str) -> bool:
    negative_tokens = ["未在", "未找到", "无匹配", "解析失败", "Error:"]
    return bool(result) and not any(token in result for token in negative_tokens)


class TreeSitterFallback:
    """Tree-sitter AST 解析作为 LSP 首选降级，支持 C/C++/Rust/Go/Zig。"""

    _SUPPORTED_LANGS = {"c", "cpp", "rust", "go", "zig"}
    _langs: Optional[Dict[str, Any]] = None
    _parser_cls: Optional[Any] = None

    @classmethod
    def _ensure_loaded(cls) -> bool:
        if cls._langs is not None:
            return True
        cls._langs = {}
        try:
            from tree_sitter import Language, Parser
            cls._parser_cls = Parser
            for name, mod in [
                ("c", "tree_sitter_c"),
                ("cpp", "tree_sitter_cpp"),
                ("rust", "tree_sitter_rust"),
                ("go", "tree_sitter_go"),
                ("zig", "tree_sitter_zig"),
            ]:
                try:
                    imp = __import__(mod)
                    cls._langs[name] = Language(getattr(imp, "language")())
                except ImportError:
                    logger.debug(f"Tree-sitter Fallback: 未安装 {mod}")
            if cls._langs:
                logger.info(f"Tree-sitter Fallback: 加载成功 ({', '.join(cls._langs)})")
                return True
        except ImportError as e:
            logger.debug(f"Tree-sitter Fallback: 未安装或加载失败 ({e})，将跳过")
        cls._langs = {}
        return False

    @classmethod
    def _lang_for_ext(cls, ext: str) -> Optional[str]:
        m = {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
             ".rs": "rust", ".go": "go", ".zig": "zig"}
        return m.get(ext)

    @classmethod
    def _get_definition_name(cls, node: Any, code_bytes: bytes, lang: str) -> Optional[str]:
        """从定义节点中提取符号名。"""
        def first_id(n: Any) -> Optional[str]:
            for c in n.children:
                if c.type in ("identifier", "type_identifier", "field_identifier") and c.child_count == 0:
                    return code_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore")
            return None

        if lang == "rust":
            for child in node.children:
                if child.type in ("identifier", "type_identifier") and child.child_count == 0:
                    return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
        if lang in ("c", "cpp"):
            if node.type == "function_definition":
                for child in node.children:
                    if child.type == "function_declarator":
                        for sc in child.children:
                            if sc.type == "identifier":
                                return code_bytes[sc.start_byte:sc.end_byte].decode("utf-8", errors="ignore")
            if node.type == "preproc_def":
                for child in node.children[1:]:
                    if child.type == "identifier":
                        return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
            if node.type in ("struct_specifier", "class_specifier"):
                for child in node.children:
                    if child.type in ("type_identifier", "identifier"):
                        return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
        if lang == "go":
            if node.type in ("function_declaration", "method_declaration"):
                return first_id(node)
            if node.type == "type_declaration":
                for child in node.children:
                    if child.type == "type_spec":
                        return first_id(child)
            if node.type in ("var_declaration", "const_declaration"):
                return first_id(node)
        if lang == "zig":
            if node.type == "function_declaration":
                for child in node.children:
                    if child.type == "_function_prototype":
                        return first_id(child)
            if node.type == "variable_declaration":
                for child in node.children:
                    if child.type == "_variable_declaration_header":
                        for c2 in child.children:
                            if c2.type == "identifier":
                                return code_bytes[c2.start_byte:c2.end_byte].decode("utf-8", errors="ignore")
        return None

    @classmethod
    def fallback_definition(cls, repo_path: str, file_path: str, symbol: str, lang: str) -> str:
        if lang not in cls._SUPPORTED_LANGS:
            return ""
        if not cls._ensure_loaded() or lang not in cls._langs:
            return ""
        abs_path = _abspath(os.path.join(repo_path, file_path))
        if not os.path.exists(abs_path):
            return ""
        try:
            with open(abs_path, "rb") as f:
                code_bytes = f.read()
        except Exception:
            return ""
        parser = cls._parser_cls()
        parser.language = cls._langs[lang]
        try:
            tree = parser.parse(code_bytes)
        except Exception:
            return ""
        root = tree.root_node
        if root.has_error:
            return ""
        matches = []
        if lang == "rust":
            def_types = ["function_item", "struct_item", "enum_item", "static_item", "const_item", "type_item", "macro_definition"]
        elif lang in ("c", "cpp"):
            def_types = ["function_definition", "preproc_def", "struct_specifier", "class_specifier"]
        elif lang == "go":
            def_types = ["function_declaration", "method_declaration", "type_declaration", "var_declaration", "const_declaration"]
        elif lang == "zig":
            def_types = ["function_declaration", "variable_declaration"]
        else:
            def_types = []
        def traverse(node: Any) -> None:
            if node.type in def_types:
                name = cls._get_definition_name(node, code_bytes, lang)
                if name == symbol:
                    line = node.start_point[0] + 1
                    snippet = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")[:200]
                    if len(snippet) >= 200:
                        snippet += "..."
                    matches.append(f"{file_path}:{line}: {snippet.strip()}")
            for child in node.children:
                traverse(child)
        traverse(root)
        if not matches:
            return ""
        return f"[Tree-sitter Fallback] 找到 {symbol} 的定义:\n" + "\n".join(matches[:15])

    @classmethod
    def fallback_references(cls, repo_path: str, file_path: str, symbol: str, lang: str) -> str:
        if lang not in cls._SUPPORTED_LANGS:
            return ""
        if not cls._ensure_loaded() or lang not in cls._langs:
            return ""
        abs_repo = _abspath(repo_path)
        _ext_map = {"c": {".c", ".h"}, "cpp": {".cc", ".cpp", ".hpp", ".h"}, "rust": {".rs"}, "go": {".go"}, "zig": {".zig"}}
        allowed = _ext_map.get(lang, set())
        files = LanguageAwareFallback._iter_candidate_files(repo_path, lang)
        parser = cls._parser_cls()
        parser.language = cls._langs[lang]
        hits = []
        for fpath in files:
            if len(hits) >= 50:
                break
            ext = os.path.splitext(fpath)[1].lower()
            if ext not in allowed:
                continue
            try:
                with open(fpath, "rb") as f:
                    code_bytes = f.read()
            except Exception:
                continue
            try:
                tree = parser.parse(code_bytes)
            except Exception:
                continue
            if tree.root_node.has_error:
                continue
            def collect_ids(node: Any) -> None:
                if node.type == "identifier" and node.child_count == 0:
                    text = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
                    if text == symbol:
                        rel = os.path.relpath(fpath, abs_repo)
                        line = node.start_point[0] + 1
                        hits.append(f"{rel}:{line}")
                for child in node.children:
                    collect_ids(child)
            collect_ids(tree.root_node)
        if not hits:
            return ""
        return f"[Tree-sitter Fallback] 找到 {symbol} 的引用 (共 {len(hits)} 处):\n" + "\n".join(hits[:30])


class LanguageAwareFallback:
    """按语言进行静态词法回退，避免非汇编场景直接套用 ASM 规则。"""

    _SUPPORTED_EXTS = {".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".go", ".zig"}

    @staticmethod
    def _iter_candidate_files(repo_path: str, lang: str) -> List[str]:
        lang_ext_map = {
            "c": {".c", ".h"},
            "cpp": {".cc", ".cpp", ".hpp", ".h"},
            "rust": {".rs"},
            "go": {".go"},
            "zig": {".zig"},
        }
        allowed_exts = lang_ext_map.get(lang, LanguageAwareFallback._SUPPORTED_EXTS)
        files = []
        abs_repo = _abspath(repo_path)
        for root, dirs, fs in os.walk(abs_repo):
            dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "dist", "node_modules", ".os_agent_ra_target"}]
            for f in fs:
                ext = os.path.splitext(f)[1].lower()
                if ext in allowed_exts:
                    files.append(os.path.join(root, f))
        return files

    @staticmethod
    def _is_comment_line(lang: str, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return True
        if lang in {"c", "cpp", "rust", "go", "zig"} and (
            stripped.startswith("//")
            or stripped.startswith("/*")
            or stripped.startswith("*")
            or stripped.startswith("*/")
        ):
            return True
        if lang == "c" and stripped.startswith("#"):
            return True
        return False

    @staticmethod
    def _definition_patterns(lang: str, symbol: str) -> List[str]:
        s = re.escape(symbol)
        if lang in {"c", "cpp"}:
            return [
                rf"^\s*#\s*define\s+{s}\b",
                rf"^\s*(?:[\w\*\s]+)\b{s}\s*\([^;]*\)\s*\{{?",
                rf"^\s*(?:extern\s+)?(?:const\s+)?[\w\*\s]+\b{s}\b\s*(?:=\s*.+)?;",
            ]
        if lang == "rust":
            return [
                rf"^\s*(?:pub\s+)?(?:async\s+)?fn\s+{s}\b",
                rf"^\s*(?:pub\s+)?(?:static|const|type)\s+{s}\b",
                rf"^\s*macro_rules!\s*{s}\b",
            ]
        if lang == "go":
            return [
                rf"^\s*func\s+{s}\s*\(",
                rf"^\s*func\s+\([^)]+\)\s+{s}\s*\(",
                rf"^\s*(?:var|const|type)\s+{s}\b",
            ]
        if lang == "zig":
            return [
                rf"^\s*(?:pub\s+)?fn\s+{s}\s*\(",
                rf"^\s*(?:pub\s+)?(?:const|var)\s+{s}\b",
            ]
        return [rf"\b{s}\b"]

    @staticmethod
    def _reference_pattern(lang: str, symbol: str) -> str:
        s = re.escape(symbol)
        if lang in {"c", "cpp", "rust", "go", "zig"}:
            return rf"\b{s}\b"
        return rf"\b{s}\b"

    @staticmethod
    def fallback_definition(repo_path: str, file_path: str, symbol: str, lang: str) -> str:
        abs_path = _abspath(os.path.join(repo_path, file_path))
        if not os.path.exists(abs_path):
            return f"[Lang Static Fallback] 文件不存在: {file_path}"

        patterns = [re.compile(p) for p in LanguageAwareFallback._definition_patterns(lang, symbol)]
        matches = []
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f, 1):
                    if LanguageAwareFallback._is_comment_line(lang, line):
                        continue
                    if any(p.search(line) for p in patterns):
                        matches.append(f"{file_path}:{idx}: {line.strip()}")
        except Exception as e:
            return f"[Lang Static Fallback] 解析失败: {e}"

        if not matches:
            return f"[Lang Static Fallback] 未在 {file_path} 找到 {symbol} 的定义。"
        return f"[Lang Static Fallback] 找到 {symbol} 的定义:\n" + "\n".join(matches[:20])

    @staticmethod
    def fallback_references(repo_path: str, file_path: str, symbol: str, lang: str) -> str:
        base_abs = _abspath(os.path.join(repo_path, file_path))
        if not os.path.exists(base_abs):
            return f"[Lang Static Fallback] 文件不存在: {file_path}"

        pattern = re.compile(LanguageAwareFallback._reference_pattern(lang, symbol))
        hits = []
        for path in LanguageAwareFallback._iter_candidate_files(repo_path, lang):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for idx, line in enumerate(f, 1):
                        if LanguageAwareFallback._is_comment_line(lang, line):
                            continue
                        if pattern.search(line):
                            rel = os.path.relpath(path, _abspath(repo_path))
                            content = line.strip()
                            if len(content) > 120:
                                content = content[:120] + "..."
                            hits.append(f"{rel}:{idx}: {content}")
                            if len(hits) >= 50:
                                break
                if len(hits) >= 50:
                    break
            except Exception:
                continue

        if not hits:
            return f"[Lang Static Fallback] 未找到 {symbol} 的引用。"
        return f"[Lang Static Fallback] 找到 {symbol} 的引用 (共 {len(hits)} 处):\n" + "\n".join(hits[:30])


class GenericLexicalFallback:
    """通用 grep 风格回退，作为语言感知层失败后的后备。"""

    _EXTS = {".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".go", ".zig", ".s", ".S", ".asm", ".inc"}

    @staticmethod
    def _scan(repo_path: str, symbol: str, max_hits: int = 40) -> List[str]:
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        hits = []
        abs_repo = _abspath(repo_path)
        for root, dirs, files in os.walk(abs_repo):
            dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "dist", "node_modules", ".os_agent_ra_target"}]
            for fname in files:
                if os.path.splitext(fname)[1] not in GenericLexicalFallback._EXTS:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for lineno, line in enumerate(f, 1):
                            if pattern.search(line):
                                rel = os.path.relpath(fpath, abs_repo)
                                text = line.strip()
                                if len(text) > 120:
                                    text = text[:120] + "..."
                                hits.append(f"{rel}:{lineno}: {text}")
                                if len(hits) >= max_hits:
                                    return hits
                except Exception:
                    continue
        return hits

    @staticmethod
    def fallback_definition(repo_path: str, symbol: str) -> str:
        hits = GenericLexicalFallback._scan(repo_path, symbol, max_hits=30)
        if not hits:
            return f"[Generic Fallback] 未找到 {symbol} 的定义候选。"
        return f"[Generic Fallback] {symbol} 定义候选:\n" + "\n".join(hits[:20])

    @staticmethod
    def fallback_references(repo_path: str, symbol: str) -> str:
        hits = GenericLexicalFallback._scan(repo_path, symbol, max_hits=50)
        if not hits:
            return f"[Generic Fallback] 未找到 {symbol} 的引用候选。"
        return f"[Generic Fallback] {symbol} 引用候选 (共 {len(hits)} 处):\n" + "\n".join(hits[:30])


def _resolve_non_asm_fallback(
    repo_path: str, file_path: str, symbol: str, lang: str, method: str, reason: str
) -> str:
    # 1. 首选 Tree-sitter（仅 C/Rust，解析失败则空字符串会触发下层降级）
    if method == "textDocument/definition":
        ts_res = TreeSitterFallback.fallback_definition(repo_path, file_path, symbol, lang)
        if _extract_hits_from_result(ts_res):
            return ts_res + _fallback_metadata("lsp->treesitter", "high", reason)
    else:
        ts_res = TreeSitterFallback.fallback_references(repo_path, file_path, symbol, lang)
        if _extract_hits_from_result(ts_res):
            return ts_res + _fallback_metadata("lsp->treesitter", "high", reason)

    # 2. 语言感知正则
    path_prefix = "lsp->lang_static"
    if method == "textDocument/definition":
        lang_res = LanguageAwareFallback.fallback_definition(repo_path, file_path, symbol, lang)
        if _extract_hits_from_result(lang_res):
            return lang_res + _fallback_metadata(path_prefix, "medium", reason)
        grep_res = GenericLexicalFallback.fallback_definition(repo_path, symbol)
        if _extract_hits_from_result(grep_res):
            return grep_res + _fallback_metadata("lsp->lang_static->grep", "low", reason)
        asm_res = ASMLexicalParser.fallback_definition(repo_path, file_path, symbol)
        return asm_res + _fallback_metadata("lsp->lang_static->grep->asm", "low", "parse_empty")

    lang_res = LanguageAwareFallback.fallback_references(repo_path, file_path, symbol, lang)
    if _extract_hits_from_result(lang_res):
        return lang_res + _fallback_metadata(path_prefix, "medium", reason)
    grep_res = GenericLexicalFallback.fallback_references(repo_path, symbol)
    if _extract_hits_from_result(grep_res):
        return grep_res + _fallback_metadata("lsp->lang_static->grep", "low", reason)
    asm_res = ASMLexicalParser.fallback_references(repo_path, file_path, symbol)
    return asm_res + _fallback_metadata("lsp->lang_static->grep->asm", "low", "parse_empty")

def _find_symbol_positions(abs_path: str, symbol: str) -> List[Tuple[int, int]]:
    """在文件当中寻找符号的第一次出现的位置，用于提供给 LSP 锚点"""
    positions = []
    try:
        # 强制以 rb 读取并解码，完全保留真实的字节偏移量，避免任何隐式 \r\n 转换
        with open(abs_path, "rb") as f:
            raw = f.read()
            text = raw.decode("utf-8", errors="ignore")
            
        lines = text.split('\n')
        for line_idx, line in enumerate(lines):
            # 处理可能的 \r
            clean_line = line.rstrip('\r')
            col_idx = clean_line.find(symbol)
            if col_idx != -1:
                # LSP 默认规范中，character 偏移量基于 UTF-16 code units
                utf16_col_idx = len(clean_line[:col_idx].encode('utf-16-le')) // 2
                positions.append((line_idx, utf16_col_idx))
    except Exception:
        pass
    return positions


def _diagnose_call_graph_prepare_failure(symbol: str, file_lines: List[str]) -> str:
    """
    prepareCallHierarchy 在所有锚点均为空时，根据当前文件内容给出**可打印的成因说明**
    （常见：宏名、token 拼接宏、索引/编译数据库问题、锚点落在非函数实体等）。
    """
    if not file_lines:
        return (
            f"无法读取 `{symbol}` 所在文件内容，无法判断根因；"
            "请确认路径与编码。后续将尝试语义引用或静态兜底。"
        )
    text = "\n".join(line.rstrip("\r") for line in file_lines)
    # 符号作为 #define 的宏名（callHierarchy 通常不支持以宏名为根）
    if re.search(rf"(?m)^\s*#\s*define\s+{re.escape(symbol)}\b", text):
        return (
            f"宏名：本文件存在 `#define {symbol}`，该名是预处理宏而非函数实体；"
            "callHierarchy 无法以宏名为根，故 prepareCallHierarchy 为空。"
        )
    # token 粘贴类宏（如 SYSCALL(name) → sys_##name），展开处常无稳定函数根节点
    if re.search(
        rf"(?m)^\s*#\s*define\b.*##.*\b{re.escape(symbol)}\b", text
    ) or re.search(rf"(?m)^\s*#\s*define\b.*\b{re.escape(symbol)}\b.*##", text):
        return (
            f"宏展开/token 拼接：`{symbol}` 出现在带 ## 的 #define 附近，符号可能由宏展开生成；"
            "LSP 常无法对其建立标准 callHierarchy，prepareCallHierarchy 为空。"
        )
    # 非 # 行中是否存在「标识符 + (」形态（粗判函数定义/声明）
    non_pp = "\n".join(
        ln.rstrip("\r")
        for ln in file_lines
        if ln.strip() and not ln.lstrip().startswith("#")
    )
    if re.search(rf"\b{re.escape(symbol)}\s*\(", non_pp):
        return (
            f"索引或实体类别：本文件非 # 行中存在 `{symbol}(...)` 形声明/定义，但 prepareCallHierarchy 仍全空；"
            "多见 compile_commands 与当前 TU 不一致、条件编译导致索引不全，或该实体不被视为可层级化的函数根。"
        )
    return (
        f"锚点/定义形态：预处理行外未见典型 `{symbol}(...)` 定义；"
        f"可能仅在 syscall 表、extern 或宏体中出现，callHierarchy 锚点无效。"
    )


async def _async_lsp_request(repo_path: str, file_path: str, symbol: str, method: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    
    # 【优先降级检查】：汇编文件不需要走真实的 LSP 解析，强制直接路由至 ASMLexicalParser
    if ext in ['.s', '.asm', '.S', '.inc']:
        if method == "textDocument/definition":
            return ASMLexicalParser.fallback_definition(repo_path, file_path, symbol)
        elif method == "textDocument/references":
            return ASMLexicalParser.fallback_references(repo_path, file_path, symbol)
        return "不支持该操作的 ASM Fallback"
        
    lang_map = {
        '.c': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.h': 'c', '.hpp': 'cpp',
        '.rs': 'rust',
        '.go': 'go',
        '.zig': 'zig'
    }
    lang = lang_map.get(ext)
    
    if not lang:
        return f"Error: 不支持的文件扩展名 '{ext}'，无法匹配可用的 Language Server。"

    abs_file = _abspath(os.path.join(repo_path, file_path))
    if not os.path.exists(abs_file):
        return f"Error: 文件未找到 {file_path}"
        
    positions = _find_symbol_positions(abs_file, symbol)
    if not positions:
        return f"Error: 符号 '{symbol}' 未在文件 '{file_path}' 中存在，无法生成锚定请求至 LSP。"

    client = await _gateway.get_client(repo_path, lang)
    if not client:
        # 非汇编场景优先走语言感知降级，再考虑 grep/ASM 最终兜底
        logger.warning(f"LSP Process for language {lang} failed to start. Downgrading to language-aware fallback.")
        return _resolve_non_asm_fallback(repo_path, file_path, symbol, lang, method, "lsp_start_failed")

    abs_file_unix = abs_file.replace(chr(92), '/')
    if not abs_file_unix.startswith('/'):
        abs_file_unix = '/' + abs_file_unix
    uri = f"file://{abs_file_unix}"
    
    # 检查客户端是否还活着
    if not client.is_alive:
        logger.warning(f"LSP client for {lang} is dead before request. Triggering reconnect.")
        # Evict dead client and get a fresh one
        client = await _gateway.get_client(repo_path, lang)
        if not client:
            logger.warning(f"LSP reconnect failed for {lang}. Falling back.")
            return _resolve_non_asm_fallback(repo_path, file_path, symbol, lang, method, "process_dead")
    
    # 【新增强化】：位置打分机制。
    # 优先选择非注释、非预处理、且看起来像定义或活跃使用的行。
    # 避免 LSP 锚点落在 doc comment (/// ...) 导致解析失效。
    try:
        with open(abs_file, 'r', encoding='utf-8', errors='ignore') as _f:
            _file_lines = _f.readlines()
    except Exception:
        _file_lines = []

    def _score_position(p: Tuple[int, int]) -> int:
        l_idx = p[0]
        if l_idx >= len(_file_lines): return 100
        line_content = _file_lines[l_idx].strip()
        # 排除常见非代码行
        if line_content.startswith(('///', '//!')): return 90  # Doc comments 最不优先
        if line_content.startswith(('/*', '//', '*', '#')): return 80 # 普通注释或宏预处理
        # 优先选择 pub static, fn, struct 等关键词所在的行
        if any(kw in line_content for kw in ['pub ', 'fn ', 'struct ', 'static ', 'const ', 'use ']): return 0
        return 50 # 普通代码行

    sorted_positions = sorted(positions, key=_score_position)
    line_idx, col_idx = sorted_positions[0]

    
    req = {
        "jsonrpc": "2.0",
        "id": 0, # 将在获取锁后分配
        "method": method,
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": line_idx, "character": col_idx}
        }
    }

    if method == "textDocument/references":
        req["params"]["context"] = {"includeDeclaration": True}

    # 通过模拟打开文档，准备 didOpen 数据
    try:
        with open(abs_file, 'r', encoding='utf-8', newline='') as f:
            text = f.read()
        did_open = {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "cpp" if lang in ["c", "cpp"] else lang,
                    "version": 1,
                    "text": text
                }
            }
        }
    except Exception:
        did_open = None

    try:
        async with _lsp_global_lock:
            # 1. 尝试触发文档打开 (并处理异常重连)
            if did_open:
                try:
                    if uri not in client.opened_uris:
                        await client.send_notification(did_open)
                        client.opened_uris.add(uri)
                        await asyncio.sleep(0.5)
                except (BrokenPipeError, ConnectionError, OSError) as e:
                    logger.warning(f"LSP pipe broken during didOpen: {e}. Reconnecting...")
                    client = await _gateway.get_client(repo_path, lang)
                    if not client or not client.is_alive:
                        return _resolve_non_asm_fallback(repo_path, file_path, symbol, lang, method, "didopen_pipe_broken")
                    try:
                        if uri not in client.opened_uris:
                            await client.send_notification(did_open)
                            client.opened_uris.add(uri)
                            await asyncio.sleep(0.5)
                    except Exception:
                        pass
                except Exception:
                    pass

            # 2. 发送实际请求
            req["id"] = client._next_id()
            try:
                result = await asyncio.wait_for(client.send_request(req), timeout=25.0)
            except (asyncio.TimeoutError, TimeoutError):
                logger.warning(f"LSP request timed out for {lang}. Engine deadlocked? Falling back to language-aware parser.")
                # Force restart the deadlocked client so it doesn't block future requests
                asyncio.create_task(_gateway.force_restart_client(repo_path, lang))
                return _resolve_non_asm_fallback(repo_path, file_path, symbol, lang, method, "lsp_timeout")
            
        if "error" in result:
             raise RuntimeError(f"LSP Error Response: {result['error']}")
             
        res_data = result.get('result')
        if not res_data:
            return f"Language Server Analytics: 未能解析出关于符号 '{symbol}' 的相关映射关系。"
            
        if isinstance(res_data, dict):
            res_data = [res_data]
            
        out = []
        for loc in res_data:
            target_uri = loc.get("uri") or loc.get("targetUri", "")
            target_range = loc.get("range") or loc.get("targetRange", {})
            if target_uri and target_range:
                if target_uri.startswith("file://"):
                    file_sys_path = target_uri[7:]
                    # 剥离 Windows下的文件前缀规范 (e.g. file:///C:/Users...)
                    if os.name == 'nt' and file_sys_path.startswith('/'):
                        file_sys_path = file_sys_path[1:]
                    try:
                        rel = os.path.relpath(file_sys_path, _abspath(repo_path))
                    except ValueError:
                        rel = file_sys_path
                    target_uri = rel
                
                start_l = target_range.get("start", {}).get("line", 0) + 1
                out.append(f"{target_uri}:{start_l}")

        # 整理输出并返回前 30 个有效引用
        out = list(dict.fromkeys(out))
        if len(out) > 30:
            out_str = f"[{method}] '{symbol}' 共被解析出 {len(out)} 处:\n" + "\n".join(out[:30]) + f"\n... (已自动截断剩余 {len(out) - 30} 处)"
        else:
            out_str = f"[{method}] '{symbol}' 结果列表:\n" + "\n".join(out)
        
        if client.build_scripts_disabled:
            out_str += "\n\n[⚠️ Warning: 该仓库的 build.rs 脚本导致 LSP 崩溃，本次查询在强行禁用构建脚本的备用安全模式下进行。个别由 C 语言绑定或宏动态生成的代码（如 bindings.rs）可能无法进行定义跳转。]"
            
        return out_str

    except (TimeoutError, Exception) as e:
        logger.warning(f"LSP execution for {symbol} triggered an exception or timeout: {e}. Executing language-aware fallback downgrade.")
        # 当大型项目超时或 AST 解析失败时，非汇编先走语言感知回退
        return _resolve_non_asm_fallback(repo_path, file_path, symbol, lang, method, "lsp_exception")


@tool
def lsp_get_definition(repo_path: str, file_path: str, symbol: str) -> str:
    """
    基于底层 Language Server Protocol (LSP) 获取源代码中符号（函数、结构体、宏等）的精准全域定义。
    此工具专为高级语言设计（C/C++、Rust、Zig、Go），底层挂载真实的 clangd / rust-analyzer，并对大型操作系统架构实施动态上下文注入以保障解析可用性。若查询目标为系统底层汇编 (.s/.S) 或抛出未定义的异常错误，工具会自动将执行流路由降级并匹配汇编标签，确保防崩溃的稳健获取能力。
    LSP 失败时会自动退避至 Tree-sitter / 语言感知正则 / grep / ASM，退避结果会附带 `[Fallback Metadata]` 供 Agent 判断置信度 (confidence=high|medium|low)。
    
    Args:
        repo_path: 仓库绝对或相对根路径 (e.g. repos/my-os)
        file_path: 包含被查询目标（symbol）的某个文件路径 (需提供相对 repo_path 的路径名)
        symbol: 需要查询其定义的精确符号名称 (e.g. "task_init", "page_alloc")
    """
    future = asyncio.run_coroutine_threadsafe(
        _async_lsp_request(repo_path, file_path, symbol, "textDocument/definition"),
        _lsp_loop
    )
    try:
        return future.result(timeout=60.0)
    except TimeoutError:
        _cancel_future_safely(future)
        return f"Error: LSP 获取定义超时 (60s)。此符号可能解析较深，请尝试使用 grep_search 作为替代方案。"
    except Exception as e:
        _cancel_future_safely(future)
        return f"Error: LSP 执行异常: {e}"
    except BaseException:
        _cancel_future_safely(future)
        raise

@tool
def lsp_get_references(repo_path: str, file_path: str, symbol: str) -> str:
    """
    基于真实 LSP 查询符号在整个项目中的全局引用（跨文件级别的方法调用的引用图谱）。
    由于它使用了编译时的 AST 上下文信息，这对于生成反转调用图 (Reverse Call Graph) 及探测某个底层抽象接口的所有实现十分有效。同样地，该方法强制支持了异常捕捉后的汇编退化流程和预查填补机制。
    LSP 失败时会自动退避至 Tree-sitter / 语言感知正则 / grep / ASM，退避结果会附带 `[Fallback Metadata]` 供 Agent 判断置信度 (confidence=high|medium|low)。
    
    Args:
        repo_path: 仓库根路径
        file_path: 包含该符号某个实现或调用的相对文件路径
        symbol: 精确符号名称
    """
    future = asyncio.run_coroutine_threadsafe(
        _async_lsp_request(repo_path, file_path, symbol, "textDocument/references"),
        _lsp_loop
    )
    try:
        return future.result(timeout=60.0)
    except TimeoutError:
        _cancel_future_safely(future)
        return f"Error: LSP 获取引用超时 (60s)。请尝试缩小搜索范围或使用 grep_search。"
    except Exception as e:
        _cancel_future_safely(future)
        return f"Error: LSP 执行异常: {e}"
    except BaseException:
        _cancel_future_safely(future)
        raise



# --- 阶段 5：文件大纲提取 (Document Symbol Outline) ---
async def _async_lsp_document_symbols(repo_path: str, file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    lang_map = {
        '.c': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.h': 'c', '.hpp': 'cpp',
        '.rs': 'rust',
        '.go': 'go',
        '.zig': 'zig'
    }
    lang = lang_map.get(ext)
    
    if not lang:
        return f"Error: 当前文件类型不被 LSP Outline 支持 '{ext}'"

    abs_file = _abspath(os.path.join(repo_path, file_path))
    if not os.path.exists(abs_file):
        return f"Error: 文件未找到 {file_path}"
        
    client = await _gateway.get_client(repo_path, lang)
    if not client:
        return "Error: LSP client failed to start."

    abs_file_unix = abs_file.replace(chr(92), '/')
    if not abs_file_unix.startswith('/'):
        abs_file_unix = '/' + abs_file_unix
    uri = f"file://{abs_file_unix}"
    
    # Health check before request
    if not client.is_alive:
        client = await _gateway.get_client(repo_path, lang)
        if not client:
            return "Error: LSP client failed to restart."
    
    try:
        with open(abs_file, 'r', encoding='utf-8', newline='') as f:
            text = f.read()
            
        did_open = {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "cpp" if lang in ["c", "cpp"] else lang,
                    "version": 1,
                    "text": text
                }
            }
        }
        
        async with _lsp_global_lock:
            if uri not in client.opened_uris:
                await client.send_notification(did_open)
                client.opened_uris.add(uri)
                await asyncio.sleep(0.5)
            
            req = {
                "jsonrpc": "2.0",
                "id": client._next_id(),
                "method": "textDocument/documentSymbol",
                "params": {
                    "textDocument": {"uri": uri}
                }
            }
            result = await client.send_request(req)
            
        if "error" in result:
             raise RuntimeError(f"LSP Error: {result['error']}")
             
        symbols = result.get('result', [])
        if not symbols:
             return "此文件为空或 LSP 无法提取任何结构大纲。"
             
        kind_map = {
            1: 'File', 2: 'Module', 3: 'Namespace', 4: 'Pkg', 5: 'Class', 
            6: 'Method', 7: 'Prop', 8: 'Field', 9: 'Constructor', 10: 'Enum', 
            11: 'Interface', 12: 'Function', 13: 'Var', 14: 'Const', 22: 'EnumMem', 
            23: 'Struct'
        }
             
        def format_symbols(syms, indent=""):
            out = []
            for s in syms:
                name = s.get('name', 'Unknown')
                # Some servers return DocumentSymbol (with children), some return SymbolInformation (with location)
                start_l = 0
                if 'range' in s:
                    start_l = s['range'].get('start', {}).get('line', 0) + 1
                elif 'location' in s:
                    start_l = s['location'].get('range', {}).get('start', {}).get('line', 0) + 1
                    
                kind_id = s.get('kind', 0)
                kind_str = kind_map.get(kind_id, str(kind_id))
                
                out.append(f"{indent}- [{kind_str}] {name} (Line {start_l})")
                if 'children' in s and s['children']:
                    out.extend(format_symbols(s['children'], indent + "  "))
            return out
            
        lines = format_symbols(symbols)
        out_str = f"[{file_path} 文件精确大纲] (LSP AST Parsed):\n" + "\n".join(lines)
        
        if client.build_scripts_disabled:
            out_str += "\n\n[⚠️ Warning: 该仓库的 build.rs 脚本导致 LSP 崩溃，本次大纲提取在强行禁用构建脚本的备用安全模式下进行。个别由宏动态生成的结构或常量节点可能由于未展开而不会出现在大纲结构中。]"
            
        return out_str
    except Exception as e:
         return f"LSP Outline 提取失败: {e}"

@tool
def lsp_get_document_outline(repo_path: str, file_path: str) -> str:
    """
    调用底层的真正的 Language Server 提取文件的精确 AST 结构大纲（返回该文件中存在的所有 Struct、Function、Class 及其起始行号）。
    对于动辄千行的内核代码文件，你可以优先调用此工具，获取文件中所有代码模块的全貌分布，再决定去精准读取哪一行的实现。
    
    Args:
        repo_path: 仓库绝对或相对根路径 (e.g. repos/my-os)
        file_path: 解析目标的相对文件路径
    """
    import asyncio
    future = asyncio.run_coroutine_threadsafe(
        _async_lsp_document_symbols(repo_path, file_path),
        _lsp_loop
    )
    try:
        return future.result(timeout=30.0)
    except TimeoutError:
        _cancel_future_safely(future)
        return f"Error: LSP 获取 {file_path} 大纲超时 (30s)。文件可能过大或解析器挂起，请直接阅读文件。"
    except Exception as e:
        _cancel_future_safely(future)
        return f"Error: LSP Outline 执行异常: {e}"
    except BaseException:
        _cancel_future_safely(future)
        raise


# --- 阶段 6：函数调用链图谱 (Call Graph / Call Hierarchy) ---

def _grep_fallback_call_graph(repo_path: str, file_path: str, symbol: str, direction: str) -> str:
    """
    静态 Grep 退避方案：当 LSP callHierarchy 不可用时自动调用。
    - outgoing: 读取函数体源码，用正则提取被调用函数名称
    - incoming: 全局搜索 `symbol(` 模式，找出所有调用点
    输出价小于 LSP 的精确结果，但能提供有用的静态调用镜像。
    """
    abs_repo = _abspath(repo_path)
    abs_file = _abspath(os.path.join(repo_path, file_path))
    banner = (
        f"\n⚠️  [Call Graph DEGRADED — Grep Fallback] symbol='{symbol}'  file={file_path}\n"
        f"    LSP callHierarchy 不可用，已自动降级至静态正则分析。\n"
        f"    精度低于 LSP（宏/内联函数/跨文件间接调用可能缺失）。\n"
    )
    print(banner, flush=True)
    lines_out = [f"[Call Graph — Grep Fallback ⚠️] {symbol}  ← {file_path}"]
    lines_out.append(
        "[⚠️ DEGRADED MODE] LSP callHierarchy 不可用，本结果由静态 Grep 正则分析生成。\n"
        "  · 宏展开、内联函数、trait 动态分发 均无法追踪\n"
        "  · outgoing: 提取函数体内的 identifier() 调用模式\n"
        "  · incoming: 全库搜索 symbol( 匹配\n"
        "  建议: 若 LSP 可用后请重新调用 lsp_get_call_graph 以获取精确结果\n"
    )

    # --- Outgoing: 解析函数体，提取调用 ---
    if direction in ("outgoing", "both"):
        lines_out.append("》出向调用 [Grep Fallback] — 正则解析函数体")
        try:
            with open(abs_file, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()

            # 在 Rust 和 C 中找到函数定义起始行
            # Rust: `fn symbol(` / `pub fn symbol(` / `async fn symbol(`
            # C:   `ret_type symbol(` / `symbol {`
            fn_start = -1
            for pat in [
                rf"(?:pub\s+)?(?:async\s+)?fn\s+{re.escape(symbol)}\s*[(<]",  # Rust
                rf"\b{re.escape(symbol)}\s*\(",                                 # C
            ]:
                m = re.search(pat, src)
                if m:
                    fn_start = src.count("\n", 0, m.start())
                    break

            if fn_start >= 0:
                # 提取函数体：找到开括号，配对关括号
                body_start = src.find("{", m.end())
                if body_start == -1:
                    body_text = ""
                else:
                    depth, pos = 0, body_start
                    for pos, ch in enumerate(src[body_start:], body_start):
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                break
                    body_text = src[body_start:pos + 1]

                # 从 body 提取调用：`identifier(` 模式（排除关键字、if/for/while）
                SKIP = {"if","for","while","match","return","let","fn","use","pub","mod",
                        "unsafe","impl","trait","struct","enum","type","const","static",
                        "super","self","Self","loop","continue","break","println","format",
                        "assert","panic","todo","unimplemented","dbg","write","writeln"}
                calls_found = {}
                for cm in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", body_text):
                    fname = cm.group(1)
                    if fname not in SKIP and not fname[0].isupper():
                        # 找出该调用在原文件中的行号
                        call_abs_pos = body_start + cm.start()
                        call_line = src.count("\n", 0, call_abs_pos) + 1
                        calls_found.setdefault(fname, call_line)

                if calls_found:
                    for fname, lineno in sorted(calls_found.items(), key=lambda x: x[1]):
                        lines_out.append(f"  ├── {fname}()  ← {file_path}:{lineno} (grep)")
                else:
                    lines_out.append("  未在函数体中提取到调用（可能为宏展开）")
            else:
                lines_out.append(f"  未定位到 '{symbol}' 的函数体，无法提取 outgoing calls")
        except Exception as e:
            lines_out.append(f"  Outgoing grep 失败: {e}")

    # --- Incoming: 全局搜索调用点 ---
    if direction in ("incoming", "both"):
        lines_out.append(f"\n》入向调用 [Grep Fallback] — 搜索 `{symbol}(` 模式")
        seen_files: Dict[str, List[int]] = {}
        src_exts = {'.c', '.cpp', '.cc', '.rs', '.go', '.zig', '.h', '.hpp'}
        try:
            for root, dirs, files in os.walk(abs_repo):
                # 跳过构建产物目录
                dirs[:] = [d for d in dirs if d not in {"target", "node_modules", ".git", ".os_agent_ra_target"}]
                for fname in files:
                    if os.path.splitext(fname)[1].lower() not in src_exts:
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            for lineno, line in enumerate(f, 1):
                                if re.search(rf"\b{re.escape(symbol)}\s*\(", line):
                                    rel = os.path.relpath(fpath, abs_repo)
                                    seen_files.setdefault(rel, []).append(lineno)
                    except Exception:
                        pass
        except Exception as e:
            lines_out.append(f"  Incoming grep 失败: {e}")

        if seen_files:
            for rel_path, linenos in sorted(seen_files.items()):
                for ln in linenos[:3]:  # 每个文件最多显示 3 处
                    lines_out.append(f"  ├── {rel_path}:{ln}  (grep)")
            if sum(len(v) for v in seen_files.values()) > 30:
                lines_out.append(f"  ... 共 {sum(len(v) for v in seen_files.values())} 处匹配（已截断）")
        else:
            lines_out.append(f"  未在全库中不到 `{symbol}(` 的调用点")

    lines_out.append(_fallback_metadata("lsp->treesitter->lang_static->grep", "low", "callHierarchy_unavailable"))
    return "\n".join(lines_out)


def _static_call_graph_fallback(repo_path: str, file_path: str, symbol: str, direction: str, lang: str) -> str:
    """
    按你要求的链路做 Call Graph 兜底：
      Tree-sitter -> Language-aware Static -> Grep -> ASM

    注意：这里的输出目标是“可用的静态调用镜像”，精度低于 LSP，但比纯 Grep 更接近语言语义。
    """
    abs_repo = _abspath(repo_path)
    abs_file = _abspath(os.path.join(repo_path, file_path))

    banner = (
        f"\n⚠️  [Call Graph DEGRADED — Static Fallback] symbol='{symbol}'  file={file_path}\n"
        f"    已按链路降级：LSP → Tree-sitter → Language-aware Static → Grep → ASM。\n"
    )
    print(banner, flush=True)

    # ---------- 1) Tree-sitter: 尝试定位函数体并提取 call sites ----------
    try:
        if TreeSitterFallback._ensure_loaded() and lang in (TreeSitterFallback._langs or {}):
            try:
                with open(abs_file, "rb") as f:
                    code_bytes = f.read()
            except Exception:
                code_bytes = b""

            if code_bytes:
                parser = TreeSitterFallback._parser_cls()
                parser.language = TreeSitterFallback._langs[lang]
                tree = parser.parse(code_bytes)
                root = tree.root_node

                # 抽取函数节点：Rust=function_item / C=function_definition / Go=function_declaration/method_declaration / Zig=function_declaration
                if lang == "rust":
                    fn_types = {"function_item"}
                elif lang in ("c", "cpp"):
                    fn_types = {"function_definition"}
                elif lang == "go":
                    fn_types = {"function_declaration", "method_declaration"}
                elif lang == "zig":
                    fn_types = {"function_declaration"}
                else:
                    fn_types = set()

                def _node_name(n):
                    return TreeSitterFallback._get_definition_name(n, code_bytes, lang)

                target_fn = None

                def _find(n):
                    nonlocal target_fn
                    if target_fn is not None:
                        return
                    if n.type in fn_types:
                        nm = _node_name(n)
                        if nm == symbol:
                            target_fn = n
                            return
                    for ch in n.children:
                        _find(ch)

                _find(root)

                if target_fn is not None:
                    fn_src = code_bytes[target_fn.start_byte:target_fn.end_byte].decode("utf-8", errors="ignore")

                    SKIP = {
                        "if", "for", "while", "match", "return", "let", "fn", "use", "pub", "mod",
                        "unsafe", "impl", "trait", "struct", "enum", "type", "const", "static",
                        "super", "self", "Self", "loop", "continue", "break",
                        "println", "format", "assert", "panic", "todo", "unimplemented", "dbg",
                        "write", "writeln",
                    }

                    calls = {}
                    if direction in ("outgoing", "both"):
                        # Rust: 支持 foo( 与 foo::bar( 与 foo!( ；C/Go/Zig: 支持 foo(
                        for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:(?:!?\s*)\(|::\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\()", fn_src):
                            name = m.group(1)
                            if name in SKIP or (name and name[0].isupper()):
                                continue
                            # 行号估算：基于函数片段内的换行
                            line_in_fn = fn_src.count("\n", 0, m.start()) + 1
                            calls.setdefault(name, line_in_fn)

                    if calls:
                        out = [f"[Call Graph — Tree-sitter Static ⚠️] {symbol}  ← {file_path}"]
                        out.append("[⚠️ DEGRADED MODE] LSP callHierarchy 不可用，本结果由 Tree-sitter + 语言规则静态提取生成。")
                        out.append(_fallback_metadata("lsp->treesitter->lang_static", "medium", "callHierarchy_unavailable"))
                        if direction in ("outgoing", "both"):
                            out.append("》出向调用 [Tree-sitter] — 静态提取函数体内 call sites")
                            for name, ln in sorted(calls.items(), key=lambda x: x[1]):
                                # 用 file_path 的起始行+偏移不可靠，这里只给“函数体内相对行”
                                out.append(f"  ├── {name}()  ← {file_path}:(fn+{ln})")
                        if direction in ("incoming", "both"):
                            out.append("\n》入向调用 [Tree-sitter] — 需要全库索引，静态层仅给出 Grep 模式候选")
                        return "\n".join(out)
    except Exception:
        # Tree-sitter 失败就继续向下
        pass

    # ---------- 2) Language-aware static ----------
    try:
        if direction in ("outgoing", "both"):
            # 语言感知层目前只有 definition/references 能力；call graph 用“函数体级正则”近似
            # 如果能在该文件里定位到定义行，就用 _grep_fallback_call_graph 的 outgoing 提取（它本质就是语言感知正则）
            lang_like = _grep_fallback_call_graph(repo_path, file_path, symbol, "outgoing")
            if lang_like and "[Call Graph — Grep Fallback" in lang_like:
                # 复用 grep 的输出结构，但提升语义标签并修正 metadata
                upgraded = lang_like.replace("Grep Fallback", "Language-aware Static")
                upgraded = upgraded.replace(
                    _fallback_metadata("lsp->treesitter->lang_static->grep", "low", "callHierarchy_unavailable"),
                    _fallback_metadata("lsp->treesitter->lang_static", "medium", "callHierarchy_unavailable"),
                )
                return upgraded
    except Exception:
        pass

    # ---------- 3) Generic Grep ----------
    try:
        return _grep_fallback_call_graph(repo_path, file_path, symbol, direction)
    except Exception:
        pass

    # ---------- 4) ASM ----------
    if direction in ("outgoing", "both"):
        asm_res = ASMLexicalParser.fallback_references(repo_path, file_path, symbol)
        return asm_res + _fallback_metadata("lsp->treesitter->lang_static->grep->asm", "low", "static_all_failed")
    asm_res = ASMLexicalParser.fallback_references(repo_path, file_path, symbol)
    return asm_res + _fallback_metadata("lsp->treesitter->lang_static->grep->asm", "low", "static_all_failed")


async def _async_lsp_call_graph(
    repo_path: str,
    file_path: str,
    symbol: str,
    direction: str,   # "outgoing" | "incoming" | "both"
    max_depth: int,
) -> str:
    """异步核心：递归构建调用图谱，返回树形文本。"""
    ext = os.path.splitext(file_path)[1].lower()
    lang_map = {
        '.c': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.h': 'c', '.hpp': 'cpp',
        '.rs': 'rust', '.go': 'go', '.zig': 'zig'
    }
    lang = lang_map.get(ext)
    if not lang:
        return f"Error: 不支持的文件类型 '{ext}'"

    abs_file = _abspath(os.path.join(repo_path, file_path))
    if not os.path.exists(abs_file):
        return f"Error: 文件未找到 {file_path}"

    positions = _find_symbol_positions(abs_file, symbol)
    if not positions:
        msg = (
            f"Error: [call_graph] 符号 `{symbol}` 在 `{file_path}` 中未出现，无法生成调用图。"
            "请先用 `grep_in_repo` 或 `read_code_segment` 确认定义所在文件，"
            "再以「定义所在路径 + 符号名」重新调用 `lsp_get_call_graph`。"
            "（不在此场景下做静态兜底，以免在错误文件上产生误导性结果。）"
        )
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return msg

    client = await _gateway.get_client(repo_path, lang)
    if not client:
        msg = f"[call_graph] LSP 客户端启动失败，自动转入分层静态兜底 (symbol={symbol})"
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return _static_call_graph_fallback(repo_path, file_path, symbol, direction, lang)

    abs_file_unix = abs_file.replace(chr(92), '/')
    if not abs_file_unix.startswith('/'):
        abs_file_unix = '/' + abs_file_unix
    uri = f"file://{abs_file_unix}"

    # 确保文档已打开
    try:
        with open(abs_file, 'r', encoding='utf-8', newline='') as f:
            text = f.read()
        did_open = {
            "jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "cpp" if lang in ["c","cpp"] else lang, "version": 1, "text": text}}
        }
    except Exception:
        did_open = None

    async def prepare_hierarchy(line_idx: int, col_idx: int) -> Optional[List[Dict]]:
        req = {
            "jsonrpc": "2.0", "id": client._next_id(),
            "method": "textDocument/prepareCallHierarchy",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": line_idx, "character": col_idx}
            }
        }
        try:
            res = await asyncio.wait_for(client.send_request(req), timeout=20.0)
            return res.get("result") or []
        except Exception:
            return []

    async def get_calls(item: Dict, method: str) -> List[Dict]:
        req = {
            "jsonrpc": "2.0", "id": client._next_id(),
            "method": method,
            "params": {"item": item}
        }
        try:
            res = await asyncio.wait_for(client.send_request(req), timeout=20.0)
            return res.get("result") or []
        except Exception:
            return []

    def uri_to_rel(raw_uri: str) -> str:
        """Convert file URI to repo-relative path."""
        if raw_uri.startswith("file://"):
            p = raw_uri[7:]
            if os.name == 'nt' and p.startswith('/'):
                p = p[1:]
            try:
                return os.path.relpath(p, _abspath(repo_path))
            except ValueError:
                return p
        return raw_uri

    # 递归构建树，返回 lines 列表
    visited: set = set()

    async def build_tree_outgoing(item: Dict, depth: int, prefix: str) -> List[str]:
        if depth > max_depth:
            return [f"{prefix}└── ... (max depth {max_depth} reached)"]
        name = item.get("name", "?")
        detail = item.get("detail", "")
        src_uri = item.get("uri", "")
        src_range = item.get("selectionRange", {}).get("start", {})
        src_line = src_range.get("line", 0) + 1
        rel_path = uri_to_rel(src_uri)
        node_key = f"{name}@{rel_path}:{src_line}"

        detail_str = f"  [{detail}]" if detail else ""
        loc_str = f"  ← {rel_path}:{src_line}"
        lines_out = [f"{prefix}├── {name}{detail_str}{loc_str}"]

        if node_key in visited:
            lines_out[-1] += "  (循环引用，已省略)"
            return lines_out
        visited.add(node_key)

        calls = await get_calls(item, "callHierarchy/outgoingCalls")
        child_items = [c.get("to", {}) for c in calls]
        for i, child in enumerate(child_items):
            is_last = (i == len(child_items) - 1)
            child_prefix = prefix + ("    " if is_last else "│   ")
            lines_out.extend(await build_tree_outgoing(child, depth + 1, child_prefix))
        return lines_out

    async def build_tree_incoming(item: Dict, depth: int, prefix: str) -> List[str]:
        if depth > max_depth:
            return [f"{prefix}└── ... (max depth {max_depth} reached)"]
        name = item.get("name", "?")
        detail = item.get("detail", "")
        src_uri = item.get("uri", "")
        src_range = item.get("selectionRange", {}).get("start", {})
        src_line = src_range.get("line", 0) + 1
        rel_path = uri_to_rel(src_uri)
        node_key = f"{name}@{rel_path}:{src_line}"

        detail_str = f"  [{detail}]" if detail else ""
        loc_str = f"  ← {rel_path}:{src_line}"
        lines_out = [f"{prefix}├── {name}{detail_str}{loc_str}"]

        if node_key in visited:
            lines_out[-1] += "  (循环引用，已省略)"
            return lines_out
        visited.add(node_key)

        callers = await get_calls(item, "callHierarchy/incomingCalls")
        parent_items = [c.get("from", {}) for c in callers]
        for i, parent in enumerate(parent_items):
            is_last = (i == len(parent_items) - 1)
            child_prefix = prefix + ("    " if is_last else "│   ")
            lines_out.extend(await build_tree_incoming(parent, depth + 1, child_prefix))
        return lines_out

    try:
        async with _lsp_global_lock:
            if did_open and uri not in client.opened_uris:
                await client.send_notification(did_open)
                client.opened_uris.add(uri)
                await asyncio.sleep(0.5)

            # 健壮化：遍历所有出现位置，优先选函数定义行
            # 原因：positions[0] 可能是注释、#include 或声明行，prepareCallHierarchy 会返回空
            # 函数定义行的特征：行内含有 symbol 且紧随其后有 '(' 或 '('
            root_items = []
            # 读取文件行，用于后续判断是否是定义行
            try:
                with open(abs_file, 'r', encoding='utf-8', errors='ignore') as _f:
                    _file_lines = _f.readlines()
            except Exception:
                _file_lines = []

            def _is_definition_line(line_idx: int) -> bool:
                """粗判断：该行是否看起来像函数定义（不是注释/include/typedef）"""
                if line_idx >= len(_file_lines):
                    return False
                line_content = _file_lines[line_idx]
                stripped = line_content.strip()
                if stripped.startswith(('/*', '*', '//', '#')):
                    return False  # 注释或预处理指令
                # 包含函数调用特征：symbol 后跟 '('
                col = line_content.find(symbol)
                if col >= 0:
                    after = line_content[col + len(symbol):].lstrip()
                    if after.startswith('('):
                        return True
                return False

            # 按定义行优先排序
            sorted_positions = sorted(
                positions,
                key=lambda p: (0 if _is_definition_line(p[0]) else 1)
            )

            for line_idx, col_idx in sorted_positions:
                root_items = await prepare_hierarchy(line_idx, col_idx)
                if root_items and isinstance(root_items, list) and len(root_items) > 0:
                    logger.debug(f"[call_graph] prepareCallHierarchy 成功，使用位置 line={line_idx+1}, col={col_idx}")
                    break

        if not root_items or not isinstance(root_items, list) or len(root_items) == 0:
            # prepareCallHierarchy 全空：先用源码启发式判断根因（宏 / 宏展开 / 索引问题等），再降级
            diag = _diagnose_call_graph_prepare_failure(symbol, _file_lines)
            print(f"\n💡 [call_graph] prepareCallHierarchy 全空 — 根因分析:\n   {diag}", flush=True)
            logger.info(
                "[call_graph] prepareCallHierarchy empty for symbol=%s file=%s — %s",
                symbol,
                file_path,
                diag.replace("\n", " "),
            )

            reason = (
                f"{diag} "
                "系统将依次尝试【语义引用 textDocument/references】；若仍无效则进入分层静态兜底。"
            )

            ref_result = await _async_lsp_request(repo_path, file_path, symbol, "textDocument/references")

            if "结果列表" in ref_result or "共被解析出" in ref_result:
                header = f"\n💡 [call_graph] {reason}\n"
                return header + ref_result

            msg = f"[call_graph] LSP 语义解析（CallGraph & References）均无效，自动转入分层静态兜底 (symbol={symbol})"
            logger.warning("%s | %s", msg, diag.replace("\n", " "))
            print(f"\n⚠️  {msg}\n   根因摘要: {diag}", flush=True)
            static_body = _static_call_graph_fallback(repo_path, file_path, symbol, direction, lang)
            return f"[call_graph 根因] {diag}\n\n{static_body}"


        root_item = root_items[0]
        root_name = root_item.get("name", symbol)
        root_uri_raw = root_item.get("uri", "")
        root_line = root_item.get("selectionRange", {}).get("start", {}).get("line", 0) + 1
        root_rel = uri_to_rel(root_uri_raw)

        result_lines = [f"[Call Graph] 根节点: {root_name}  ← {root_rel}:{root_line}"]

        if direction in ("outgoing", "both"):
            visited.clear()
            result_lines.append(f"\n》出向调用 (Outgoing Calls) — '{root_name}' 调用了谁？")
            async with _lsp_global_lock:
                calls = await get_calls(root_item, "callHierarchy/outgoingCalls")
            child_items = [c.get("to", {}) for c in calls]
            visited.add(f"{root_name}@{root_rel}:{root_line}")
            for i, child in enumerate(child_items):
                is_last = (i == len(child_items) - 1)
                child_prefix = "    " if is_last else "│   "
                async with _lsp_global_lock:
                    subtree = await build_tree_outgoing(child, 1, child_prefix)
                result_lines.extend(subtree)

        if direction in ("incoming", "both"):
            visited.clear()
            result_lines.append(f"\n》入向调用 (Incoming Calls) — 谁调用了 '{root_name}'？")
            async with _lsp_global_lock:
                callers = await get_calls(root_item, "callHierarchy/incomingCalls")
            parent_items = [c.get("from", {}) for c in callers]
            visited.add(f"{root_name}@{root_rel}:{root_line}")
            for i, parent in enumerate(parent_items):
                is_last = (i == len(parent_items) - 1)
                child_prefix = "    " if is_last else "│   "
                async with _lsp_global_lock:
                    subtree = await build_tree_incoming(parent, 1, child_prefix)
                result_lines.extend(subtree)

        return "\n".join(result_lines)

    except Exception as e:
        msg = f"[call_graph] 内部异常: {e}，自动转入分层静态兜底 (symbol={symbol})"
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return _static_call_graph_fallback(repo_path, file_path, symbol, direction, lang)


@tool
def lsp_get_call_graph(repo_path: str, file_path: str, symbol: str,
                       direction: str = "outgoing", max_depth: int = 3) -> str:
    """
    基于 LSP callHierarchy 协议递归构建函数调用链图（Call Graph），
    以树形缩进文本输出"函数 A 调用了谁" / "谁调用了函数 A"两个方向的完整相关关系。

    适用场景：
    - 分析内核关键路径（如 fork、handle_page_fault、syscall_handler）的完整调用链
    - 验证某个函数是否被正确调用，以及调用层次是否合理
    - 为 OS-Agent C 的细粒度比对提供 Call Graph 快照

    注意：需要 Language Server 支持 callHierarchy 协议。
    clangd (v12+) 和 rust-analyzer 均支持。
    若 LSP 无法解析（如符号为变量、常量或宏生成的代码），本工具会自动识别并尝试切换至“语义引用查找”
    （Semantic References）模式以确保高精度的分析结果，并会在输出中告知 Agent 切换的原因。
    若语义解析完全不可用，则最后降级为正则匹配。


    Args:
        repo_path: 仓库它对或相对根路径 (e.g. repos/my-os)
        file_path: 包含该符号的相对文件路径
        symbol: 目标函数/方法名称 (e.g. "handle_page_fault", "sys_fork")
        direction: 调用方向 —
            "outgoing" : 列出该函数调用了哪些熱数 (默认)
            "incoming" : 列出谁调用了该函数 (反调用图)
            "both"     : 同时输出两个方向
        max_depth: 递归深度限制 (1-5，默认 3。过大会导致超时)
    """
    future = asyncio.run_coroutine_threadsafe(
        _async_lsp_call_graph(repo_path, file_path, symbol, direction, max_depth),
        _lsp_loop
    )
    try:
        return future.result(timeout=120.0)
    except TimeoutError:
        _cancel_future_safely(future)
        msg = f"[call_graph] LSP 超时 (120s)，自动转入 Grep Fallback (symbol={symbol})"
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return _grep_fallback_call_graph(repo_path, file_path, symbol, direction)
    except Exception as e:
        _cancel_future_safely(future)
        msg = f"[call_graph] 外层异常: {e}，自动转入 Grep Fallback (symbol={symbol})"
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return _grep_fallback_call_graph(repo_path, file_path, symbol, direction)
    except BaseException:
        _cancel_future_safely(future)
        raise


async def _async_lsp_set_target_arch(repo_path: str, target: str) -> str:
    """内部异步实现：保存架构标记并强制重启 rust-analyzer。"""
    repo_path = _abspath(repo_path)
    marker = os.path.join(repo_path, ".os_agent_lsp_target")

    try:
        async with _get_polyfill_lock(repo_path):
            with open(marker, 'w', encoding='utf-8') as f:
                f.write(target)

            # 注意：重启内部会按 self.lock -> _lsp_global_lock 的顺序拿锁，
            # 必须避免在这里先拿 _lsp_global_lock 再去调用 force_restart_client，
            # 否则会与 get_client 的锁顺序相反，形成潜在死锁。
            await _gateway.force_restart_client(repo_path, "rust")
        return f"Successfully set LSP target to '{target}' and restarted rust-analyzer for {repo_path}."
    except Exception as e:
        return f"Error setting target arch: {e}"


@tool
def lsp_set_target_arch(repo_path: str, target: str) -> str:
    """
    显式通过 LLM 指令设置特定仓库的 LSP 目标架构 (Target Triple)。
    仅在以下情况调用：
    1. 自动探测失败或选错了架构（例如同时存在 riscv64 和 loongarch64 目录）。
    2. 你在源码中读到了明确的架构要求（如 target_arch = "..."），但 LSP 却返回了空结果或大量错误。
    3. 代码块由于 #[cfg] 显式被 LSP 灰化。

    调用后，系统会保存设置并【强制重启】LSP 服务端，以确保所有语义分析能够基于正确的架构进行重算。

    常见 Target Triples:
    - riscv64gc-unknown-none-elf (RISC-V 64)
    - loongarch64-unknown-none-elf (LoongArch 64)
    - x86_64-unknown-none-elf (x86_64 Bare Metal)
    - aarch64-unknown-none-elf (ARM64 Bare Metal)

    Args:
        repo_path: 仓库绝对或相对根路径 (e.g. repos/my-os)
        target: 目标架构标识符 (Target Triple)
    """
    future = asyncio.run_coroutine_threadsafe(
        _async_lsp_set_target_arch(repo_path, target),
        _lsp_loop
    )
    try:
        return future.result(timeout=10.0)
    except Exception as e:
        _cancel_future_safely(future)
        return f"Error executing lsp_set_target_arch: {e}"
    except BaseException:
        _cancel_future_safely(future)
        raise
