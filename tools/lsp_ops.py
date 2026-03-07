"""
LSP Operations Tool (Dynamic Multiplexing Gateway)
"""
import os
import re
import json
import asyncio
import logging
import threading
import atexit
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

def _ensure_cargo_fetched(repo_path: str):
    """Run `cargo fetch` once per repo so rust-analyzer can resolve all dependencies.
    
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
        result = subprocess.run(
            [cargo, "fetch"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=180  # 3 minutes max for large workspaces with git deps
        )
        if result.returncode == 0:
            logger.info(f"cargo fetch completed successfully in {repo_path}")
        else:
            logger.warning(f"cargo fetch failed (rc={result.returncode}): {result.stderr[:300]}\nProceeding anyway with partial deps.")
    except subprocess.TimeoutExpired:
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
def _polyfill_context(repo_path: str, scan_results: Dict[str, bool]):
    # C/C++ (clangd) 补全逻辑
    # C/C++ (clangd) 补全逻辑
    # 哪怕有 Makefile/CMakeLists，如果没有 compile_commands.json，clangd 依然是个瞎子
    has_c_config = scan_results["compile_commands.json"]
    
    if not has_c_config:
        compile_flags_path = os.path.join(repo_path, "compile_flags.txt")
        # 总是重新生成，以防克隆后文件变动
        include_dirs = {os.path.abspath(repo_path)}
        for root, dirs, files in os.walk(repo_path):
            # 跳过无关目录，防止生成的 flags 过载
            dirs[:] = [d for d in dirs if d not in {".git", ".github", "target", "vendor", "node_modules", "build", "dist"}]
            if any(f.endswith('.h') or f.endswith('.hpp') for f in files):
                include_dirs.add(os.path.abspath(root))
        if include_dirs:
            try:
                with open(compile_flags_path, 'w', encoding='utf-8') as f:
                    # 声明这大概率是一个 C 语言或 C++ 内核项目
                    f.write("-xc\n") 
                    # 将根目录和所有包含头文件的目录加入搜索路径
                    for d in include_dirs:
                        # 对于 Windows 上的 clangd，路径中的反斜杠可能需要转义或统一替换为正斜杠
                        sanitized_path = d.replace('\\', '/')
                        f.write(f"-I{sanitized_path}\n")
            except Exception as e:
                logger.error(f"Failed to generate compile_flags.txt: {e}")

    # Rust (rust-analyzer) 补全逻辑
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
                        f.write('[package]\nname = "os_kernel_dummy"\nversion = "0.1.0"\nedition = "2021"\n')
                        if members:
                            f.write('\n[workspace]\nmembers = [\n')
                            for m in members:
                                f.write(f'    "{m}",\n')
                            f.write(']\n')
                except Exception as e:
                    logger.error(f"Failed to generate Cargo.toml: {e}")
            
            # 如果存在 Cargo.toml，检查是否存在有效的 target 文件 (src/lib.rs 或 src/main.rs) 或者包含 members
            # 防止 rust-analyzer 的 cargo metadata 报错 `no targets specified in the manifest` 而彻底罢工
            if os.path.exists(cargo_toml_path):
                with open(cargo_toml_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 只有既没有 members 也没有目标文件时，才强制创建 dummy src
                if "[workspace]" not in content:
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
        _ensure_cargo_fetched(repo_path)

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
        
        # 强化隔离：防止在线拉取卡死，允许不稳定特性 (全局对 rust-analyzer 生效)
        if "rust-analyzer" in self.cmd[0]:
            env["CARGO_NET_OFFLINE"] = "true" 
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
        while self.process and self.process.stderr:
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                logger.warning(f"LSP [{self.cmd[0]}] STDERR: {line.decode('utf-8', errors='ignore').strip()}")
            except Exception:
                break

    async def _initialize(self):
        # Build proper file URI — Windows needs file:///C:/... (3 slashes)
        abs_cwd = os.path.abspath(self.cwd).replace(chr(92), '/')
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
                    "textDocument": {
                        "callHierarchy": {"dynamicRegistration": False},
                        "synchronization": {"dynamicRegistration": False}
                    }
                },
                "initializationOptions": {
                    "cargo": {
                        "extraArgs": ["--offline"],
                        "extraEnv": {
                            "CARGO_NET_OFFLINE": "true"
                        }
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


def _resolve_lsp_binary(name: str, cwd: Optional[str] = None) -> str:
    """Resolve LSP binary path with cross-platform fallback.
    
    Search order:
    1. rustup which (if name is rust-analyzer) to bypass proxy bugs
    2. shutil.which() — current PATH
    3. Platform-specific common installation directories
    4. Return bare name as last resort (subprocess will report clear error)
    """
    import shutil
    import platform
    import subprocess
    
    if name == "rust-analyzer":
        try:
            # Bypass rustup proxy bug on Windows where capitalized .EXE fails to resolve the component
            res = subprocess.run(["rustup", "which", "rust-analyzer"], cwd=cwd, capture_output=True, text=True, check=True)
            candidate = res.stdout.strip()
            if candidate and os.path.isfile(candidate):
                return candidate
        except subprocess.CalledProcessError as e:
            # If `rustup which` fails, it's likely because the rust-analyzer component is missing 
            # for the specific toolchain (e.g. toolchains specified in rust-toolchain.toml)
            # Let's try to automatically install it and retry once
            err_str = e.stderr.lower() if e.stderr else ""
            if "not installed" in err_str or "no component" in err_str or "error" in err_str:
                logger.info(f"rust-analyzer component seems missing for current toolchain. Attempting auto-install...")
                try:
                    subprocess.run(["rustup", "component", "add", "rust-analyzer"], cwd=cwd, capture_output=True, check=True)
                    # Retry
                    res2 = subprocess.run(["rustup", "which", "rust-analyzer"], cwd=cwd, capture_output=True, text=True, check=True)
                    candidate2 = res2.stdout.strip()
                    if candidate2 and os.path.isfile(candidate2):
                        logger.info(f"Successfully auto-installed and resolved rust-analyzer: {candidate2}")
                        return candidate2
                except Exception as ex:
                    logger.warning(f"Failed to auto-install rust-analyzer: {ex}")
        except Exception:
            pass

    found = shutil.which(name)
    if found:
        return found
    
    home = os.path.expanduser("~")
    system = platform.system()  # 'Windows', 'Linux', 'Darwin'
    ext = ".exe" if system == "Windows" else ""
    
    candidates = []
    
    # --- Cross-platform: cargo/rustup ---
    candidates.append(os.path.join(home, ".cargo", "bin", f"{name}{ext}"))
    
    if system == "Windows":
        # Windows standalone installers often use AppData/Local
        candidates.append(os.path.join(home, "AppData", "Local", name, f"{name}.exe"))
        # Scoop
        candidates.append(os.path.join(home, "scoop", "shims", f"{name}.exe"))
        # winget default for LLVM (clangd)
        if name == "clangd":
            candidates.append(r"C:\Program Files\LLVM\bin\clangd.exe")
    elif system == "Darwin":
        # Homebrew (Apple Silicon & Intel)
        candidates.append(f"/opt/homebrew/bin/{name}")
        candidates.append(f"/usr/local/bin/{name}")
    else:
        # Linux: common paths
        candidates.append(f"/usr/bin/{name}")
        candidates.append(f"/usr/local/bin/{name}")
        candidates.append(os.path.join(home, ".local", "bin", name))
        # Snap / Nix
        candidates.append(f"/snap/bin/{name}")
        candidates.append(os.path.join(home, ".nix-profile", "bin", name))
    
    for c in candidates:
        if os.path.isfile(c):
            logger.info(f"Resolved {name} via fallback path: {c}")
            return c
    
    logger.warning(
        f"LSP binary '{name}' not found in PATH or common locations. "
        f"Install it for better code analysis accuracy. "
        f"Searched: PATH + {len(candidates)} fallback paths. "
        f"See README.md '安装 Language Servers' section for instructions."
    )
    return name  # let subprocess fail with a clear error

class MultiplexingLSPGateway:
    def __init__(self):
        self.clients: Dict[str, LSPClient] = {}
        self.lock = asyncio.Lock()

    async def get_client(self, repo_path: str, lang: str) -> Optional[LSPClient]:
        abs_repo = os.path.abspath(repo_path)
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
            _polyfill_context(abs_repo, scan_res)

            cmd = []
            if lang in ["c", "cpp"]:
                cmd = [_resolve_lsp_binary("clangd", cwd=abs_repo)]
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
                    
                    # Check if it crashed immediately (e.g. panicking build.rs)
                    if not client.is_alive and lang == "rust":
                        logger.warning(f"LSP {cmd[0]} died immediately. Retrying with build scripts disabled.")
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
        abs_path = os.path.abspath(os.path.join(repo_path, file_path))
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
        abs_path = os.path.abspath(os.path.join(repo_path, file_path))
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

def _find_symbol_positions(abs_path: str, symbol: str) -> List[Tuple[int, int]]:
    """在文件当中寻找符号的第一次出现的位置，用于提供给 LSP 锚点"""
    positions = []
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_idx, line in enumerate(f):
                col_idx = line.find(symbol)
                if col_idx != -1:
                    positions.append((line_idx, col_idx))
    except Exception:
        pass
    return positions

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

    abs_file = os.path.abspath(os.path.join(repo_path, file_path))
    if not os.path.exists(abs_file):
        return f"Error: 文件未找到 {file_path}"
        
    positions = _find_symbol_positions(abs_file, symbol)
    if not positions:
        return f"Error: 符号 '{symbol}' 未在文件 '{file_path}' 中存在，无法生成锚定请求至 LSP。"

    client = await _gateway.get_client(repo_path, lang)
    if not client:
        # 当高级语言的 LSP 进程由于依赖缺失而抛出错误，或本地未安装该 LSP 时，执行自动降级
        logger.warning(f"LSP Process for language {lang} failed to start. Downgrading to ASMLexicalParser fallback.")
        if method == "textDocument/definition":
            return ASMLexicalParser.fallback_definition(repo_path, file_path, symbol)
        else:
            return ASMLexicalParser.fallback_references(repo_path, file_path, symbol)

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
            if method == "textDocument/definition":
                return ASMLexicalParser.fallback_definition(repo_path, file_path, symbol)
            else:
                return ASMLexicalParser.fallback_references(repo_path, file_path, symbol)
    
    # 取文件内部符号扫描的最高优先级位置，下发至 LSP 引擎
    line_idx, col_idx = positions[0]
    
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
        with open(abs_file, 'r', encoding='utf-8') as f:
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
                        if method == "textDocument/definition":
                            return ASMLexicalParser.fallback_definition(repo_path, file_path, symbol)
                        else:
                            return ASMLexicalParser.fallback_references(repo_path, file_path, symbol)
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
            result = await client.send_request(req)
            
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
                        rel = os.path.relpath(file_sys_path, os.path.abspath(repo_path))
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
        logger.warning(f"LSP execution for {symbol} triggered an exception or timeout: {e}. Executing ASM fallback downgrade.")
        # 当由于大型项目带来的超时，或 AST 解析彻底失效触发异常，统一退化回落至轻量级正则匹配
        if method == "textDocument/definition":
            return ASMLexicalParser.fallback_definition(repo_path, file_path, symbol)
        else:
            return ASMLexicalParser.fallback_references(repo_path, file_path, symbol)


@tool
def lsp_get_definition(repo_path: str, file_path: str, symbol: str) -> str:
    """
    基于底层 Language Server Protocol (LSP) 获取源代码中符号（函数、结构体、宏等）的精准全域定义。
    此工具专为高级语言设计（C/C++、Rust、Zig、Go），底层挂载真实的 clangd / rust-analyzer，并对大型操作系统架构实施动态上下文注入以保障解析可用性。若查询目标为系统底层汇编 (.s/.S) 或抛出未定义的异常错误，工具会自动将执行流路由降级并匹配汇编标签，确保防崩溃的稳健获取能力。
    
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
        return f"Error: LSP 获取定义超时 (60s)。此符号可能解析较深，请尝试使用 grep_search 作为替代方案。"
    except Exception as e:
        return f"Error: LSP 执行异常: {e}"

@tool
def lsp_get_references(repo_path: str, file_path: str, symbol: str) -> str:
    """
    基于真实 LSP 查询符号在整个项目中的全局引用（跨文件级别的方法调用的引用图谱）。
    由于它使用了编译时的 AST 上下文信息，这对于生成反转调用图 (Reverse Call Graph) 及探测某个底层抽象接口的所有实现十分有效。同样地，该方法强制支持了异常捕捉后的汇编退化流程和预查填补机制。
    
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
        return f"Error: LSP 获取引用超时 (60s)。请尝试缩小搜索范围或使用 grep_search。"
    except Exception as e:
        return f"Error: LSP 执行异常: {e}"



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

    abs_file = os.path.abspath(os.path.join(repo_path, file_path))
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
        with open(abs_file, 'r', encoding='utf-8') as f:
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
        return f"Error: LSP 获取 {file_path} 大纲超时 (30s)。文件可能过大或解析器挂起，请直接阅读文件。"
    except Exception as e:
        return f"Error: LSP Outline 执行异常: {e}"


# --- 阶段 6：函数调用链图谱 (Call Graph / Call Hierarchy) ---

def _grep_fallback_call_graph(repo_path: str, file_path: str, symbol: str, direction: str) -> str:
    """
    静态 Grep 退避方案：当 LSP callHierarchy 不可用时自动调用。
    - outgoing: 读取函数体源码，用正则提取被调用函数名称
    - incoming: 全局搜索 `symbol(` 模式，找出所有调用点
    输出价小于 LSP 的精确结果，但能提供有用的静态调用镜像。
    """
    abs_repo = os.path.abspath(repo_path)
    abs_file = os.path.abspath(os.path.join(repo_path, file_path))
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
        lines_out.append("》出升调用 [Grep Fallback] — 正则解析函数体")
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

    return "\n".join(lines_out)


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

    abs_file = os.path.abspath(os.path.join(repo_path, file_path))
    if not os.path.exists(abs_file):
        return f"Error: 文件未找到 {file_path}"

    positions = _find_symbol_positions(abs_file, symbol)
    if not positions:
        return f"Error: 符号 '{symbol}' 未在文件 '{file_path}' 中找到。"

    client = await _gateway.get_client(repo_path, lang)
    if not client:
        msg = f"[call_graph] LSP 客户端启动失败，自动转入 Grep Fallback (symbol={symbol})"
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return _grep_fallback_call_graph(repo_path, file_path, symbol, direction)

    abs_file_unix = abs_file.replace(chr(92), '/')
    if not abs_file_unix.startswith('/'):
        abs_file_unix = '/' + abs_file_unix
    uri = f"file://{abs_file_unix}"

    # 确保文档已打开
    try:
        with open(abs_file, 'r', encoding='utf-8') as f:
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
                return os.path.relpath(p, os.path.abspath(repo_path))
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
            lines_out[-1] += "  (循环引用，已剩略)"
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
            lines_out[-1] += "  (循环引用，已剩略)"
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

            line_idx, col_idx = positions[0]
            root_items = await prepare_hierarchy(line_idx, col_idx)

        if not root_items:
            msg = f"[call_graph] callHierarchy/prepare 返回空，自动转入 Grep Fallback (symbol={symbol})"
            logger.warning(msg)
            print(f"\n⚠️  {msg}", flush=True)
            return _grep_fallback_call_graph(repo_path, file_path, symbol, direction)

        root_item = root_items[0]
        root_name = root_item.get("name", symbol)
        root_uri_raw = root_item.get("uri", "")
        root_line = root_item.get("selectionRange", {}).get("start", {}).get("line", 0) + 1
        root_rel = uri_to_rel(root_uri_raw)

        result_lines = [f"[Call Graph] 根节点: {root_name}  ← {root_rel}:{root_line}"]

        if direction in ("outgoing", "both"):
            visited.clear()
            result_lines.append("\n》出吐调用 (Outgoing Calls) — '{root_name}' 调用了谁？")
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
        msg = f"[call_graph] 内部异常: {e}，自动转入 Grep Fallback (symbol={symbol})"
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return _grep_fallback_call_graph(repo_path, file_path, symbol, direction)


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
    若 LSP 无法解析（如符号为宏威码），会返回提示信息而非崩溃。

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
        msg = f"[call_graph] LSP 超时 (120s)，自动转入 Grep Fallback (symbol={symbol})"
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return _grep_fallback_call_graph(repo_path, file_path, symbol, direction)
    except Exception as e:
        msg = f"[call_graph] 外层异常: {e}，自动转入 Grep Fallback (symbol={symbol})"
        logger.warning(msg)
        print(f"\n⚠️  {msg}", flush=True)
        return _grep_fallback_call_graph(repo_path, file_path, symbol, direction)
