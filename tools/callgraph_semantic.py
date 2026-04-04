"""
Call Graph 语义过滤：用 Clang AST（与 compile_flags / compile_commands 一致）收集
「预处理后的翻译单元中存在的函数定义」，用于从 Tree-sitter 全源码图中剔除条件编译裁掉的符号。

可选依赖：pip install clang，且系统需能加载 libclang（Windows 常为 LLVM 安装目录下的 libclang.dll）。
不可用时跳过过滤并打日志，不静默假装已裁剪。
"""

from __future__ import annotations

import ctypes.util
import glob
import hashlib
import json
import logging
import os
import shlex
import subprocess
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 与 callgraph_overview.CALLGRAPH_CACHE_VERSION 解耦；算法变更时 bump
SEMANTIC_PIPELINE_VERSION = 1

# 进程内缓存：是否已成功加载 libclang（避免重复探测）
_libclang_ready: Optional[bool] = None


def _abspath(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))


def _find_libclang_library_path() -> Optional[str]:
    """
    定位 libclang 动态库路径。

    - 优先环境变量 LIBCLANG_PATH（文件路径，指向 .dll/.so/.dylib）
    - Windows：常见 LLVM 安装目录
    - Linux/mac：ctypes.util.find_library("clang")
    """
    env = os.environ.get("LIBCLANG_PATH", "").strip()
    if env and os.path.isfile(env):
        return env
    if os.name == "nt":
        for c in (
            r"C:\Program Files\LLVM\bin\libclang.dll",
            r"C:\Program Files (x86)\LLVM\bin\libclang.dll",
        ):
            if os.path.isfile(c):
                return c
    else:
        found = ctypes.util.find_library("clang")
        if found:
            return found
        # Linux 等：部分发行版未把 libclang 注册进 ldconfig 的「clang」别名，但已安装到 /usr/lib/...
        if os.name == "posix":
            candidates: List[str] = []
            for base in (
                "/usr/lib/x86_64-linux-gnu",
                "/usr/lib/aarch64-linux-gnu",
                "/usr/lib/riscv64-linux-gnu",
                "/usr/lib64",
                "/usr/lib",
            ):
                if not os.path.isdir(base):
                    continue
                for p in sorted(glob.glob(os.path.join(base, "libclang*.so*"))):
                    if os.path.isfile(p):
                        candidates.append(p)
            if candidates:
                return candidates[-1]
    return None


def _ensure_libclang_loaded() -> bool:
    """
    导入 clang.cindex 并加载 libclang；仅 pip install clang 不够，还需系统带 libclang 动态库。
    Windows 可只装 LLVM（含 libclang.dll），本函数会尝试常见路径，无需手工设环境变量。
    """
    global _libclang_ready
    if _libclang_ready is not None:
        return _libclang_ready
    try:
        import clang.cindex as ci  # type: ignore
    except ImportError:
        logger.warning(
            "[CallGraph semantic] 未安装 Python 包：请执行 pip install clang"
        )
        _libclang_ready = False
        return False

    path = _find_libclang_library_path()
    if path:
        try:
            # Windows：始终用探测到的 dll；Unix：仅当为真实路径时设置（find_library 可能返回短名）
            if os.name == "nt" or os.path.isfile(path):
                ci.Config.set_library_file(path)
                logger.info("[CallGraph semantic] 已加载 libclang: %s", path)
        except Exception as e:
            logger.debug("[CallGraph semantic] set_library_file(%s): %s", path, e)

    try:
        ci.Index.create()
        _libclang_ready = True
        return True
    except Exception as e:
        logger.warning(
            "[CallGraph semantic] libclang 无法初始化（需安装 LLVM 或设置 LIBCLANG_PATH 指向 libclang）：%s",
            e,
        )
        _libclang_ready = False
        return False


def libclang_runtime_ok() -> bool:
    """能否创建 Index（用于指纹与降级判断）。"""
    return _ensure_libclang_loaded()


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _git_head(repo_path: str) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return out.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def compute_input_fingerprint(
    repo_path: str,
    *,
    lsp_depth: int = 4,
    top_k: int = 30,
) -> str:
    """
    输入指纹：compile 配置 + git + 语义管线版本 + libclang 可用性 + 影响输出的参数。
    用于 callgraph 缓存：变更则全量重建。
    """
    abs_repo = _abspath(repo_path)
    parts: List[str] = [
        str(SEMANTIC_PIPELINE_VERSION),
        abs_repo,
        f"lsp_depth={lsp_depth}",
        f"top_k={top_k}",
        "libclang_ok=" + ("1" if libclang_runtime_ok() else "0"),
        "git=" + _git_head(abs_repo),
    ]
    cf = os.path.join(abs_repo, "compile_flags.txt")
    if os.path.isfile(cf):
        parts.append("compile_flags=" + _file_sha256(cf))
    cc = os.path.join(abs_repo, "compile_commands.json")
    if os.path.isfile(cc):
        parts.append("compile_commands=" + _file_sha256(cc))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


def _read_compile_flags_lines(repo_path: str) -> List[str]:
    path = os.path.join(_abspath(repo_path), "compile_flags.txt")
    if not os.path.isfile(path):
        return []
    out: List[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(line)
    except OSError:
        pass
    return out


def _load_compile_commands(repo_path: str) -> Optional[List[dict]]:
    path = os.path.join(_abspath(repo_path), "compile_commands.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.warning("[CallGraph semantic] 读取 compile_commands.json 失败: %s", e)
    return None


def _norm_rel(repo: str, path: str) -> str:
    try:
        return os.path.relpath(os.path.normpath(path), _abspath(repo)).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def _build_cc_index(compile_commands: List[dict], repo_path: str) -> Dict[str, dict]:
    """file 绝对路径 -> entry"""
    idx: Dict[str, dict] = {}
    abs_repo = _abspath(repo_path)
    for ent in compile_commands:
        f = ent.get("file")
        if not f:
            continue
        af = os.path.normpath(f if os.path.isabs(f) else os.path.join(abs_repo, f))
        idx[af] = ent
        idx.setdefault(os.path.normcase(af), ent)
    return idx


def _entry_argv(entry: dict) -> List[str]:
    args = entry.get("arguments")
    if isinstance(args, list) and len(args) >= 1:
        skip = 0
        bn = os.path.basename(str(args[0])).lower()
        if any(x in bn for x in ("clang", "gcc", "g++", "c++", "cl.exe")) or bn in (
            "cc",
            "c++",
        ):
            skip = 1
        return list(args[skip:])
    cmd = entry.get("command")
    if isinstance(cmd, str) and cmd.strip():
        try:
            sp = shlex.split(cmd, posix=os.name != "nt")
            return sp[1:] if len(sp) > 1 else []
        except ValueError:
            pass
    return []


def _strip_linker_only_flags(argv: List[str]) -> List[str]:
    """parseTranslationUnit 不需要 -o/-c 等链接/输出参数。"""
    out: List[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "-MF", "-MT", "-MQ"):
            i += 2
            continue
        if a == "-c":
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def _argv_strip_source_path(argv: List[str], abs_path: str) -> List[str]:
    """compile_commands 的 arguments 常含源文件路径，与 parse 的首参重复则去掉。"""
    ap = os.path.normcase(os.path.normpath(abs_path))
    return [a for a in argv if os.path.normcase(os.path.normpath(a)) != ap]


def _lang_flags_for_ext(ext: str) -> List[str]:
    if ext in (".c", ".h"):
        return ["-xc"]
    if ext in (".cc", ".cpp", ".hpp"):
        return ["-xc++"]
    return ["-xc"]


def _collect_function_names_from_tu(tu) -> Set[str]:
    import clang.cindex as ci  # type: ignore

    names: Set[str] = set()

    def visit(cursor: "ci.Cursor") -> None:
        if cursor.kind == ci.CursorKind.FUNCTION_DECL:
            if cursor.is_definition() and cursor.spelling:
                names.add(cursor.spelling)
        elif cursor.kind == ci.CursorKind.CXX_METHOD:
            if cursor.is_definition() and cursor.spelling:
                names.add(cursor.spelling)
        for ch in cursor.get_children():
            visit(ch)

    visit(tu.cursor)
    return names


def collect_active_functions_by_file(
    repo_path: str,
    fn_meta: Dict[str, dict],
) -> Tuple[Dict[str, Set[str]], Set[str], bool, str]:
    """
    返回 (active_by_file, parsed_ok_files, used_libclang, message)。
    active_by_file[rel_path] = 该 TU 中 Clang 认为存在的函数定义名集合。
    parsed_ok_files = 成功完成 parse 的文件集合（rel_path）。
    若 libclang 不可用，返回 ({}, set(), False, reason)。
    """
    if not libclang_runtime_ok():
        return {}, set(), False, "libclang 未就绪，跳过语义过滤（保留 Tree-sitter 全图）"

    try:
        import clang.cindex as ci  # type: ignore
    except ImportError:
        return {}, set(), False, "未安装 clang Python 绑定（pip install clang），跳过语义过滤"

    abs_repo = _abspath(repo_path)
    files_needed: Set[str] = set()
    for _n, meta in fn_meta.items():
        if meta.get("kind") != "function":
            continue
        if meta.get("lang") not in ("c", "cpp"):
            continue
        f = (meta.get("file") or "").strip().replace("\\", "/")
        if not f:
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext not in (".c", ".cc", ".cpp", ".h", ".hpp"):
            continue
        files_needed.add(f)

    if not files_needed:
        return {}, set(), True, "无 C/C++ 函数定义文件需语义解析"

    cc_list = _load_compile_commands(repo_path)
    cc_idx: Optional[Dict[str, dict]] = None
    if cc_list:
        cc_idx = _build_cc_index(cc_list, repo_path)

    flag_lines = _read_compile_flags_lines(repo_path)
    base_flags = flag_lines[:] if flag_lines else ["-xc", "-std=gnu17", "-ffreestanding", "-fno-builtin"]

    active_by_file: Dict[str, Set[str]] = {}
    parsed_ok: Set[str] = set()
    errors = 0

    index = ci.Index.create()

    for rel in sorted(files_needed):
        abs_path = os.path.join(abs_repo, rel.replace("/", os.sep))
        if not os.path.isfile(abs_path):
            continue
        ext = os.path.splitext(rel)[1].lower()
        argv: List[str] = []

        if cc_idx is not None:
            ent = cc_idx.get(os.path.normpath(abs_path))
            if ent is None:
                ent = cc_idx.get(os.path.normcase(os.path.normpath(abs_path)))
            if ent:
                argv = _strip_linker_only_flags(_entry_argv(ent))
                argv = _argv_strip_source_path(argv, abs_path)
                cwd = ent.get("directory") or abs_repo
            else:
                argv = _lang_flags_for_ext(ext) + base_flags
                cwd = abs_repo
        else:
            argv = _lang_flags_for_ext(ext) + base_flags
            cwd = abs_repo

        try:
            old_cwd = os.getcwd()
            try:
                os.chdir(cwd)
                tu = index.parse(
                    abs_path,
                    args=argv,
                    options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
                )
            finally:
                os.chdir(old_cwd)
        except Exception as e:
            logger.debug("[CallGraph semantic] parse 失败 %s: %s", rel, e)
            errors += 1
            continue

        if tu is None:
            errors += 1
            continue

        names = _collect_function_names_from_tu(tu)
        active_by_file[rel] = names
        parsed_ok.add(rel)

    msg = (
        f"语义解析 {len(parsed_ok)}/{len(files_needed)} 个文件"
        + (f"，{errors} 个失败" if errors else "")
    )
    return active_by_file, parsed_ok, True, msg


def apply_semantic_prune_inactive_functions(
    G: "object",  # nx.DiGraph
    fn_meta: Dict[str, dict],
    active_by_file: Dict[str, Set[str]],
    parsed_ok: Set[str],
) -> int:
    """
    从图中删除：kind=function、lang c/cpp、定义文件已成功 parse 且函数名不在活跃集中。
    返回删除节点数。
    """
    to_remove: List[str] = []
    for n in list(G.nodes()):
        meta = fn_meta.get(n) or {}
        if meta.get("kind") != "function":
            continue
        if meta.get("lang") not in ("c", "cpp"):
            continue
        f = (meta.get("file") or "").strip().replace("\\", "/")
        if not f:
            continue
        if f not in parsed_ok:
            continue
        names = active_by_file.get(f) or set()
        if n not in names:
            to_remove.append(n)

    if not to_remove:
        return 0

    G.remove_nodes_from(to_remove)
    for n in to_remove:
        fn_meta.pop(n, None)
    return len(to_remove)
