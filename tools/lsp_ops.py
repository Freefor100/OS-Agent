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

# --- 阶段 2：编译上下文的动态生成 (Dynamic Context Polyfill) ---
def _polyfill_context(repo_path: str, scan_results: Dict[str, bool]):
    # C/C++ (clangd) 补全逻辑
    has_c_config = (scan_results["compile_commands.json"] or 
                    scan_results["Makefile"] or 
                    scan_results["CMakeLists.txt"])
    
    if not has_c_config:
        compile_flags_path = os.path.join(repo_path, "compile_flags.txt")
        if not os.path.exists(compile_flags_path):
            include_dirs = set()
            for root, dirs, files in os.walk(repo_path):
                # 跳过无关目录，防止生成的 flags 过载
                dirs[:] = [d for d in dirs if d not in {".git", ".github", "target", "vendor", "node_modules", "build", "dist"}]
                if any(f.endswith('.h') or f.endswith('.hpp') for f in files):
                    include_dirs.add(root)
            if include_dirs:
                try:
                    with open(compile_flags_path, 'w', encoding='utf-8') as f:
                        for d in include_dirs:
                            f.write(f"-I{os.path.abspath(d)}\n")
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
                try:
                    with open(cargo_toml_path, 'w', encoding='utf-8') as f:
                        f.write('[package]\nname = "os_kernel_dummy"\nversion = "0.1.0"\nedition = "2021"\n')
                except Exception as e:
                    logger.error(f"Failed to generate Cargo.toml: {e}")

# --- 阶段 3：多路复用 LSP 客户端构建 (Multiplexing LSP Gateway) ---
class LSPClient:
    def __init__(self, cmd: List[str], cwd: str):
        self.cmd = cmd
        self.cwd = cwd
        self.process: Optional[asyncio.subprocess.Process] = None
        self.request_id = 0
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.initialized_event = asyncio.Event()

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.cmd,
            cwd=self.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        asyncio.create_task(self._reader_loop())
        await self._initialize()

    async def _initialize(self):
        init_req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "rootUri": f"file://{os.path.abspath(self.cwd).replace(chr(92), '/')}",
                "capabilities": {}
            }
        }
        await self.send_request(init_req)
        self.initialized_event.set()

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    async def _reader_loop(self):
        while True:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break
                
                line_str = line.decode('utf-8').strip()
                if not line_str.startswith("Content-Length:"):
                    continue
                
                content_length = int(line_str.split(":")[1].strip())
                
                # 读取接下来的空行 
                await self.process.stdout.readline()
                
                # 读取 Body，严格按 Content-Length 读取
                body = await self.process.stdout.readexactly(content_length)
                response = json.loads(body.decode('utf-8'))
                
                res_id = response.get("id")
                if res_id is not None and res_id in self.pending_requests:
                    self.pending_requests[res_id].set_result(response)
                    
            except asyncio.IncompleteReadError:
                break
            except Exception as e:
                logger.error(f"LSP reader loop error: {e}")
                break
                
        # 异常清理所有挂起的请求，防止阻塞
        for fut in self.pending_requests.values():
            if not fut.done():
                fut.set_exception(RuntimeError("LSP process terminated unexpectedly"))

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
                # 严格限制 LSP 的响应时间，防止超时挂起
                res = await asyncio.wait_for(fut, timeout=12.0)
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


def _resolve_lsp_binary(name: str) -> str:
    """Resolve LSP binary path with cross-platform fallback.
    
    Search order:
    1. shutil.which() — current PATH
    2. Platform-specific common installation directories
    3. Return bare name as last resort (subprocess will report clear error)
    """
    import shutil
    import platform
    
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
            if key in self.clients:
                return self.clients[key]

            scan_res = _pre_flight_workspace_scan(abs_repo)
            _polyfill_context(abs_repo, scan_res)

            cmd = []
            if lang in ["c", "cpp"]:
                cmd = [_resolve_lsp_binary("clangd")]
            elif lang == "rust":
                cmd = [_resolve_lsp_binary("rust-analyzer")]
            elif lang == "go":
                cmd = [_resolve_lsp_binary("gopls")]
            elif lang == "zig":
                cmd = [_resolve_lsp_binary("zls")]
            else:
                return None

            try:
                client = LSPClient(cmd, abs_repo)
                await client.start()
                self.clients[key] = client
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

    uri = f"file://{abs_file.replace(chr(92), '/')}"
    
    # 通过模拟打开文档，强制 LSP 构建该文件的 AST 分析缓存
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
        await client.send_notification(did_open)
        # 提供几百毫秒的预缓冲时间让 LSP 消费 AST
        await asyncio.sleep(0.3)
    except Exception:
        pass

    # 取文件内部符号扫描的最高优先级位置，下发至 LSP 引擎
    line_idx, col_idx = positions[0]
    
    req = {
        "jsonrpc": "2.0",
        "id": client._next_id(),
        "method": method,
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": line_idx, "character": col_idx}
        }
    }

    if method == "textDocument/references":
        req["params"]["context"] = {"includeDeclaration": True}

    try:
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
            return f"[{method}] '{symbol}' 共被解析出 {len(out)} 处:\n" + "\n".join(out[:30]) + f"\n... (已自动截断剩余 {len(out) - 30} 处)"
        return f"[{method}] '{symbol}' 结果列表:\n" + "\n".join(out)

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
    return future.result(timeout=25.0)

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
    return future.result(timeout=25.0)



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

    uri = f"file://{abs_file.replace(chr(92), '/')}"
    
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
        await client.send_notification(did_open)
        import asyncio
        await asyncio.sleep(0.3)
    except Exception:
        pass

    req = {
        "jsonrpc": "2.0",
        "id": client._next_id(),
        "method": "textDocument/documentSymbol",
        "params": {
            "textDocument": {"uri": uri}
        }
    }

    try:
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
        return f"[{file_path} 文件精确大纲] (LSP AST Parsed):\n" + "\n".join(lines)
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
    return future.result(timeout=15.0)
