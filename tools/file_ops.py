from __future__ import annotations

import os
import re
from typing import Optional


MAX_FILE_CHARS = 100000


def _is_under(path: str, root: str) -> bool:
    try:
        path_abs = os.path.abspath(path)
        root_abs = os.path.abspath(root)
        return os.path.commonpath([path_abs, root_abs]) == root_abs
    except ValueError:
        return False


def _safe_repo_path(repo_path: str, path: str = "") -> bool:
    cwd = os.getcwd()
    target = os.path.join(repo_path, path) if path else repo_path
    return _is_under(target, cwd)


def read_code_segment(
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> str:
    if not _safe_repo_path(os.getcwd(), file_path):
        return f"Error: path outside workspace: {file_path}"
    if not os.path.isfile(file_path):
        return f"Error: File not found: {file_path}"
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    start = max(0, (start_line or 1) - 1)
    end = end_line if end_line else len(lines)
    content = "".join(lines[start:end])
    limit = max_chars or MAX_FILE_CHARS
    if len(content) > limit:
        content = content[:limit] + "\n... [truncated]"
    return content


def grep_in_repo(
    repo_path: str,
    pattern: str,
    max_results: int = 20,
    file_extensions: Optional[str] = None,
) -> str:
    if not os.path.isdir(repo_path):
        return f"Error: directory not found: {repo_path}"
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return f"Error: invalid regex {pattern!r}: {exc}"
    ext_filter = None
    if file_extensions:
        ext_filter = {"." + e.strip().lstrip(".").lower() for e in file_extensions.split(",") if e.strip()}
    default_exts = {
        ".rs", ".c", ".h", ".cpp", ".hpp", ".cc", ".s", ".S", ".asm",
        ".toml", ".mk", ".ld", ".lds", ".x", ".go", ".zig",
    }
    results: list[str] = []
    files_searched = 0
    total_matches = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "vendor", "node_modules"}]
        for name in files:
            ext = os.path.splitext(name)[1]
            if ext_filter:
                if ext.lower() not in ext_filter:
                    continue
            elif ext not in default_exts and ext.lower() not in default_exts:
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            files_searched += 1
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        if regex.search(line):
                            total_matches += 1
                            if len(results) < max_results:
                                rel = os.path.relpath(path, repo_path).replace("\\", "/")
                                results.append(f"{rel}:{line_no}: {line.rstrip()[:220]}")
            except OSError:
                continue
    if not results:
        return f"未找到匹配 '{pattern}' 的内容 (已搜索 {files_searched} 个文件)"
    head = f"搜索 '{pattern}' 的结果 ({total_matches} 个匹配, 搜索了 {files_searched} 个文件):"
    return "\n".join([head, *results])


def confirm_symbol_absent(repo_path: str, patterns: str, file_extensions: Optional[str] = None) -> str:
    raw_patterns = [p.strip() for p in re.split(r"[,\n]", patterns) if p.strip()]
    if not raw_patterns:
        return "Error: patterns is empty"
    per_pattern = []
    files_searched = 0
    ext_filter = None
    if file_extensions:
        ext_filter = {"." + e.strip().lstrip(".").lower() for e in file_extensions.split(",") if e.strip()}
    default_exts = {".rs", ".c", ".h", ".cpp", ".hpp", ".cc", ".s", ".S", ".asm", ".toml", ".mk", ".ld", ".x"}
    files: list[str] = []
    for root, dirs, names in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "vendor", "node_modules"}]
        for name in names:
            ext = os.path.splitext(name)[1]
            if ext_filter:
                if ext.lower() not in ext_filter:
                    continue
            elif ext not in default_exts and ext.lower() not in default_exts:
                continue
            files.append(os.path.join(root, name))
    files_searched = len(files)
    for pat in raw_patterns:
        try:
            regex = re.compile(pat, re.IGNORECASE)
        except re.error as exc:
            per_pattern.append((pat, -1, [f"regex error: {exc}"]))
            continue
        count = 0
        examples = []
        for path in files:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        if regex.search(line):
                            count += 1
                            if len(examples) < 3:
                                rel = os.path.relpath(path, repo_path).replace("\\", "/")
                                examples.append(f"{rel}:{line_no}: {line.rstrip()[:160]}")
            except OSError:
                continue
        per_pattern.append((pat, count, examples))
    all_absent = all(count == 0 for _, count, _ in per_pattern)
    verdict = "[CONFIRMED_ABSENT]" if all_absent else "[FOUND]"
    lines = [
        f"负向搜索报告 — {verdict}",
        f"仓库: {repo_path}  |  搜索文件数: {files_searched}  |  patterns: {len(raw_patterns)}",
        "",
    ]
    for pat, count, examples in per_pattern:
        if count == 0:
            lines.append(f"  ✓ [{pat}] 零匹配 — 确认不存在")
        else:
            lines.append(f"  ✗ [{pat}] {count} 处匹配 — 存在")
            lines.extend(f"    {ex}" for ex in examples)
    return "\n".join(lines)
