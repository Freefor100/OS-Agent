"""Git history analysis helpers (ported from the `liu` branch's git_ops).

These are progressive-disclosure tools: cheap churn aggregates first, narrow
drill-downs second, and a single-commit minimal diff last. They never emit raw
multi-file diffs, so an LLM can reason about evolution without token explosion.

All functions are plain callables (no LangChain decorator) so Agent D can call
them directly and wrap them as tools where needed.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Optional

try:
    import git  # gitpython
except Exception:  # pragma: no cover - optional dependency
    git = None  # type: ignore


EXCLUDE_TOP_DIRS = {"vendor", ".git", ".github", "target", "node_modules", ".devcontainer", "__pycache__"}


def _module_from_path(path: str) -> Optional[str]:
    """Top-level directory of a path, used as a repo-agnostic module bucket."""
    if not path:
        return None
    norm = path.replace("\\", "/").strip("/")
    parts = norm.split("/")
    if not parts or not parts[0]:
        return None
    top = parts[0]
    if top.startswith(".") or top.lower() in {d.lower() for d in EXCLUDE_TOP_DIRS}:
        return None
    return top


def _open(repo_path: str):
    if git is None:
        raise RuntimeError("gitpython is not installed")
    if not os.path.exists(repo_path):
        raise FileNotFoundError(f"Repository path not found: {repo_path}")
    return git.Repo(repo_path)


def git_history_summary(repo_path: str, max_commits: int = 200) -> str:
    """Compact history: per commit show date/sha/author/msg + total churn + Top-3 modules.

    Aggregates file changes by top-level module instead of listing files, and
    caps total output at 8000 chars (head 40% / tail 30% elision) so the whole
    project lifecycle fits in one cheap call.
    """
    MAX_CHARS = 8000
    try:
        repo = _open(repo_path)
    except Exception as exc:
        return f"Error: {exc}"
    commits = list(repo.iter_commits(max_count=max_commits))
    if not commits:
        return "No commits found."

    summaries = []
    for c in commits:
        dt = c.committed_datetime.strftime("%Y-%m-%d")
        msg = (c.message or "").strip().replace("\n", " ")[:80]
        sha = c.hexsha[:8]
        author = (c.author.name or "unknown")[:20]
        module_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"adds": 0, "dels": 0})
        total_adds = total_dels = 0
        try:
            for filepath, stats in (c.stats.files or {}).items():
                adds = int(stats.get("insertions", 0))
                dels = int(stats.get("deletions", 0))
                total_adds += adds
                total_dels += dels
                module = _module_from_path(filepath) or "(root)"
                module_stats[module]["adds"] += adds
                module_stats[module]["dels"] += dels
        except Exception:
            pass
        top = sorted(module_stats.items(), key=lambda x: x[1]["adds"] + x[1]["dels"], reverse=True)[:3]
        mods = ", ".join(f"{m}(+{s['adds']}-{s['dels']})" for m, s in top)
        summaries.append(f"[{dt}] {sha} {author} | +{total_adds}-{total_dels} | {mods}\n  {msg}")

    header = (
        f"Total: {len(commits)} commits | Range: "
        f"{commits[-1].committed_datetime.strftime('%Y-%m-%d')} ~ "
        f"{commits[0].committed_datetime.strftime('%Y-%m-%d')}\n" + "-" * 60 + "\n"
    )
    if len(header) + sum(len(s) + 1 for s in summaries) <= MAX_CHARS:
        return "\n".join([header, *summaries])
    keep_head = max(5, int(len(summaries) * 0.4))
    keep_tail = max(5, int(len(summaries) * 0.3))
    skipped = len(summaries) - keep_head - keep_tail
    parts = [header, *summaries[:keep_head]]
    if skipped > 0:
        parts.append(f"\n... [省略 {skipped} 条小提交] ...\n")
    parts.extend(summaries[-keep_tail:])
    return "\n".join(parts)


def analyze_git_history(repo_path: str, max_commits: int = 50, skip: int = 0, path_filter: str = "") -> str:
    """Per-commit changes aggregated by directory (numstat), with optional drill-down.

    ``path_filter`` narrows to one subsystem (e.g. "kernel/fs") so the LLM can
    request detail progressively. Caps at 25000 chars.
    """
    try:
        repo = _open(repo_path)
    except Exception as exc:
        return f"Error: {exc}"
    commits = list(repo.iter_commits(max_count=max_commits, skip=skip))
    if not commits:
        return "No commits found in this range."
    pf = path_filter.replace("\\", "/").strip("/") if path_filter else ""
    lines = [f"Showing {len(commits)} commits (skip={skip}{', filter='+pf if pf else ''}):\n"]
    for c in commits:
        dt = c.committed_datetime.strftime("%Y-%m-%d %H:%M")
        msg = (c.message or "").strip().replace("\n", " ")[:100]
        lines.append(f"[{dt}] SHA:{c.hexsha[:8]} Author:{c.author.name}")
        lines.append(f"Message: {msg}")
        dir_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"adds": 0, "dels": 0, "count": 0})
        try:
            for filepath, stats in (c.stats.files or {}).items():
                norm = filepath.replace("\\", "/")
                if pf and not norm.startswith(pf):
                    continue
                dir_stats[os.path.dirname(norm) or "(root)"]["adds"] += int(stats.get("insertions", 0))
                dir_stats[os.path.dirname(norm) or "(root)"]["dels"] += int(stats.get("deletions", 0))
                dir_stats[os.path.dirname(norm) or "(root)"]["count"] += 1
        except Exception:
            pass
        if pf and not dir_stats:
            lines.pop(); lines.pop()
            continue
        ordered = sorted(dir_stats.items(), key=lambda x: x[1]["adds"] + x[1]["dels"], reverse=True)
        changes = [f"  [{d}/] {s['count']} files (+{s['adds']} -{s['dels']})" for d, s in ordered]
        if changes:
            total_files = sum(s["count"] for s in dir_stats.values())
            lines.append(f"Changed Subsystems (Total: {total_files} files in {len(dir_stats)} dirs):")
            if len(changes) > 20:
                lines.extend(changes[:20])
                lines.append(f"  ... and {len(changes) - 20} more directories omitted. (Use path_filter to drill down)")
            else:
                lines.extend(changes)
        lines.append("-" * 40)
    result = "\n".join(lines)
    return result if len(result) <= 25000 else result[:25000] + "\n... [truncated to 25000 chars] ..."


def trace_file_evolution(repo_path: str, file_path: str, max_commits: int = 50) -> str:
    """Lifecycle of one file via `git log --follow --numstat` (rename-aware, numstat only)."""
    try:
        repo = _open(repo_path)
    except Exception as exc:
        return f"Error: {exc}"
    try:
        log = repo.git.log("--follow", "--numstat", "--format=COMMIT|%h|%aI|%s", "-n", str(max_commits), "--", file_path)
    except Exception as exc:
        return f"Error tracing file evolution: {exc}"
    if not log.strip():
        return f"No history found for file: {file_path}"
    out = [f"Evolution of `{file_path}`:"]
    current = ""
    for line in log.strip().split("\n"):
        if line.startswith("COMMIT|"):
            p = line.split("|")
            current = f"[{p[2][:10]}] SHA:{p[1]} - {p[3]}"
        elif line.strip():
            sp = line.split("\t")
            if len(sp) >= 2 and current:
                adds = sp[0] if sp[0] != "-" else "0"
                dels = sp[1] if sp[1] != "-" else "0"
                out.append(f"{current} (+{adds} -{dels})")
                current = ""
    return "\n".join(out)


def find_symbol_first_commit(repo_path: str, keywords: list[str]) -> str:
    """First commit that introduced each keyword (pickaxe `git log -S`, no diff body)."""
    try:
        repo = _open(repo_path)
    except Exception as exc:
        return f"Error: {exc}"
    out = []
    for kw in keywords:
        try:
            log = repo.git.log("-S", kw, "--reverse", "--format=%H|%aI|%s", "--name-only")
            if not log:
                out.append(f"Keyword: `{kw}` | Not found in history.")
                continue
            block = log.strip().split("\n\n")[0].strip().split("\n")
            meta = block[0].split("|")
            sha, date, msg = meta[0][:8], meta[1][:10], meta[2][:40]
            f = block[1].strip() if len(block) >= 2 else ""
            out.append(f"Keyword: `{kw}` | First appeared: {date} (SHA: {sha}) - {msg}" + (f" | File: {f}" if f else ""))
        except Exception as exc:
            out.append(f"Keyword: `{kw}` | Error: {exc}")
    return "\n".join(out)


def commit_diff_summary(repo_path: str, commit_sha: str) -> str:
    """Minimal single-commit diff: --unified=0, whitespace-ignored, comments stripped, 20000-char cap.

    The ONLY function here that touches real diff text, and only for one chosen SHA.
    """
    try:
        repo = _open(repo_path)
    except Exception as exc:
        return f"Error: {exc}"
    try:
        diff_str = repo.git.show(commit_sha, "--format=", "--unified=0", "--ignore-all-space", "--ignore-blank-lines")
    except Exception as exc:
        return f"Error getting commit diff: {exc}"
    if not diff_str.strip():
        return "No text-based diff available or only whitespace changed."
    out = []
    current = ""
    adds = dels = 0
    for line in diff_str.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            current = parts[-1] if len(parts) > 1 else line.split()[-1]
            adds = dels = 0
            out.append(f"\nFile: {current}")
        elif line.startswith("@@"):
            continue
        elif line.startswith("+") and not line.startswith("+++"):
            c = line[1:].strip()
            if not (c.startswith("//") or c.startswith("/*") or c.startswith("*")):
                out.append(line); adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            c = line[1:].strip()
            if not (c.startswith("//") or c.startswith("/*") or c.startswith("*")):
                out.append(line); dels += 1
    res = "\n".join(out)
    return res if len(res) <= 20000 else res[:20000] + "\n\n... [Diff too large, truncated to 20000 chars] ..."


def module_history(repo_path: str, max_commits: int = 200) -> dict[str, list[dict[str, str]]]:
    """Churn-ranked per-module commit index (repo-agnostic, replaces keyword buckets).

    Returns {module -> [{commit, subject, adds, dels}]} sorted by churn, top 8 each.
    """
    try:
        repo = _open(repo_path)
    except Exception:
        return {}
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for c in repo.iter_commits(max_count=max_commits):
        per_module: dict[str, dict[str, int]] = defaultdict(lambda: {"adds": 0, "dels": 0})
        try:
            for filepath, stats in (c.stats.files or {}).items():
                module = _module_from_path(filepath)
                if not module:
                    continue
                per_module[module]["adds"] += int(stats.get("insertions", 0))
                per_module[module]["dels"] += int(stats.get("deletions", 0))
        except Exception:
            continue
        subject = (c.message or "").strip().replace("\n", " ")[:80]
        for module, s in per_module.items():
            buckets[module].append({
                "commit": c.hexsha[:8],
                "subject": subject,
                "adds": str(s["adds"]),
                "dels": str(s["dels"]),
                "churn": s["adds"] + s["dels"],
            })
    out: dict[str, list[dict[str, str]]] = {}
    for module, rows in buckets.items():
        rows.sort(key=lambda r: r["churn"], reverse=True)
        out[module] = [{k: v for k, v in r.items() if k != "churn"} for r in rows[:8]]
    return out
