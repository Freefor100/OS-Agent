import os
from collections import defaultdict
from typing import Optional

import git  # 依赖 gitpython 库
from langchain.tools import tool

# 定义一个工作目录，专门存放 Agent 下载的代码
WORKSPACE_DIR = "./repos"

# 忽略的顶层目录（如 vendor、.git 等），不参与“按模块”统计
EXCLUDE_TOP_DIRS = {"vendor", ".git", ".github", "target", "node_modules", ".devcontainer"}


def _module_from_path(path: str) -> Optional[str]:
    """从文件路径提取顶层模块名，用于按模块统计开发历史。"""
    parts = path.replace("\\", "/").strip("/").split("/")
    if not parts:
        return None
    top = parts[0]
    if top.startswith(".") or top in EXCLUDE_TOP_DIRS:
        return None
    return top


@tool
def clone_repository(repo_url: str) -> str:
    """
    根据给定的 URL 克隆 Git 仓库。
    如果仓库已经存在，则直接返回本地路径，避免重复下载。
    返回: 本地仓库的绝对路径。
    """
    try:
        # 1. 提取仓库名作为文件夹名 (例如 os-kernel.git -> os-kernel)
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        local_path = os.path.join(WORKSPACE_DIR, repo_name)
        
        # 2. 检查目录是否存在
        if os.path.exists(local_path):
            # 检查目录是否为空
            if os.listdir(local_path):
                return f"Repository already exists at: {local_path}"
        else:
            os.makedirs(local_path, exist_ok=True)
            
        # 3. 如果不存在或为空，执行克隆
        print(f"Cloning {repo_url} to {local_path}...")
        try:
            # First try normal clone, but with protectNTFS=false to bypass Windows colon issues
            git.Repo.clone_from(repo_url, local_path, c='core.protectNTFS=false', allow_unsafe_protocols=True, allow_unsafe_options=True)
        except git.exc.GitCommandError as e:
            # If clone succeeds but checkout failed (e.g. invalid path with colon on Windows)
            err_str = str(e).lower()
            if "invalid path" in err_str or "clone succeeded, but checkout failed" in err_str:
                print(f"\n--- [Git Native Error Log] ---")
                print(e.stderr if e.stderr else str(e))
                print(f"------------------------------\n")
                print(f"Clone succeeded but checkout failed due to invalid paths. Attempting force checkout...")
                # Open the partially cloned repo
                repo = git.Repo(local_path)
                # Ensure the config is set for this specific repo
                with repo.config_writer() as cw:
                    cw.set_value("core", "protectNTFS", "false")
                # Force checkout to HEAD
                repo.git.checkout('-f', 'HEAD')
            else:
                raise
        
        return f"Successfully cloned to: {local_path}"
        
    except Exception as e:
        return f"Error cloning repository: {str(e)}"


@tool
def get_repo_local_path(repo_url: str) -> str:
    """
    根据 Git 仓库 URL 返回克隆后的本地路径（不执行克隆）。
    用于在 clone_repository 之后统一获取 repo_path，供 list_repo_structure、analyze_git_history 等使用。
    """
    name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    return os.path.normpath(os.path.join(WORKSPACE_DIR, name))


@tool
def analyze_git_history(repo_path: str, max_commits: int = 50, skip: int = 0) -> str:
    """
    获取 Git 仓库的原始提交历史（包含文件变更详情），供 LLM 自行进行语义分析。
    
    Args:
        repo_path: 本地仓库路径
        max_commits: 一次最多返回的提交数量（防止超长，建议50-100）
        skip: 分页跳过的提交数量，用于查看更早的历史
    
    Returns:
        包含日期、作者、摘要、涉及的变更文件及其增删行数的原始记录
    """
    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        
        repo = git.Repo(repo_path)
        commits = list(repo.iter_commits(max_count=max_commits, skip=skip))
        
        if not commits:
            return "No commits found in this range."
            
        lines = [f"Showing {len(commits)} commits (skip={skip}):\n"]
        for c in commits:
            dt = c.committed_datetime.strftime("%Y-%m-%d %H:%M")
            msg = (c.message or "").strip().replace("\n", " ")[:100]
            sha = c.hexsha[:8]
            
            lines.append(f"[{dt}] SHA:{sha} Author:{c.author.name}")
            lines.append(f"Message: {msg}")
            
            # Extract file changes
            file_changes = []
            try:
                # Use commit.stats.files which provides insertions and deletions without needing the full patch
                if c.stats.files:
                    for filepath, stats in c.stats.files.items():
                        adds = stats.get('insertions', 0)
                        dels = stats.get('deletions', 0)
                        file_changes.append(f"  {filepath} (+{adds} -{dels})")
            except Exception:
                pass
            
            if file_changes:
                lines.append("Changed Files:")
                lines.extend(file_changes)
            else:
                lines.append("Changed Files: (No explicit file diff available)")
            lines.append("-" * 40)
            
        return "\n".join(lines)
        
    except Exception as e:
        return f"Error analyzing git history: {str(e)}"


@tool
def get_git_history_summary(repo_path: str, max_commits: int = 200) -> str:
    """
    获取 Git 仓库的精炼提交历史摘要，按模块聚合变更统计。
    专为开发历史分析设计，一次调用即可获取全局概览，无需分页。

    与 analyze_git_history 的区别：
    - 不列出每个变更文件，而是按顶层模块（目录）聚合增删行数
    - 每个 commit 只显示：日期、SHA、作者、消息、总增删行数、变更最多的 Top-3 模块
    - 总返回字符数控制在 8000 以内，超出时自动省略中间的小提交

    Args:
        repo_path: 本地仓库路径
        max_commits: 最多返回的提交数量（默认200，覆盖大部分项目完整生命周期）

    Returns:
        精炼的提交历史摘要文本
    """
    MAX_CHARS = 8000

    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"

        repo = git.Repo(repo_path)
        commits = list(repo.iter_commits(max_count=max_commits))

        if not commits:
            return "No commits found."

        # 先收集所有 commit 的摘要信息
        summaries = []
        for c in commits:
            dt = c.committed_datetime.strftime("%Y-%m-%d")
            msg = (c.message or "").strip().replace("\n", " ")[:80]
            sha = c.hexsha[:8]
            author = (c.author.name or "unknown")[:20]

            # 按模块聚合文件变更
            module_stats = defaultdict(lambda: {"adds": 0, "dels": 0})
            total_adds = 0
            total_dels = 0
            try:
                if c.stats.files:
                    for filepath, stats in c.stats.files.items():
                        adds = stats.get('insertions', 0)
                        dels = stats.get('deletions', 0)
                        total_adds += adds
                        total_dels += dels
                        module = _module_from_path(filepath) or "(root)"
                        module_stats[module]["adds"] += adds
                        module_stats[module]["dels"] += dels
            except Exception:
                pass

            # 只取变更量 Top-3 的模块
            sorted_modules = sorted(
                module_stats.items(),
                key=lambda x: x[1]["adds"] + x[1]["dels"],
                reverse=True
            )[:3]
            modules_str = ", ".join(
                f"{m}(+{s['adds']}-{s['dels']})" for m, s in sorted_modules
            )

            line = f"[{dt}] {sha} {author} | +{total_adds}-{total_dels} | {modules_str}\n  {msg}"
            summaries.append(line)

        # 组装输出，控制总字符数
        header = f"Total: {len(commits)} commits | Range: {commits[-1].committed_datetime.strftime('%Y-%m-%d')} ~ {commits[0].committed_datetime.strftime('%Y-%m-%d')}\n"
        header += "-" * 60 + "\n"

        result_lines = [header]
        total_len = len(header)

        if total_len + sum(len(s) + 1 for s in summaries) <= MAX_CHARS:
            # 全部放得下
            result_lines.extend(summaries)
        else:
            # 需要截断：保留前 40% 和后 30%，省略中间
            keep_head = max(5, int(len(summaries) * 0.4))
            keep_tail = max(5, int(len(summaries) * 0.3))

            # 先放头部
            for s in summaries[:keep_head]:
                result_lines.append(s)
                total_len += len(s) + 1

            # 省略提示
            skipped = len(summaries) - keep_head - keep_tail
            if skipped > 0:
                skip_msg = f"\n... [省略 {skipped} 条小提交] ...\n"
                result_lines.append(skip_msg)
                total_len += len(skip_msg)

            # 放尾部（最早的提交）
            for s in summaries[-keep_tail:]:
                result_lines.append(s)
                total_len += len(s) + 1

        return "\n".join(result_lines)

    except Exception as e:
        return f"Error getting git history summary: {str(e)}"


@tool
def find_symbol_first_commit(repo_path: str, keywords: list[str]) -> str:
    """
    寻找某些核心关键字（如 _start, FrameAllocator, sys_fork 等）首次被引入仓库的 commit。
    
    Args:
        repo_path: 本地仓库路径
        keywords: 需要搜索的关键词列表，例如 ["_start", "rust_main"]
        
    Returns:
        文本形式的搜索结果，格式为 "Keyword: xxx | First appeared in: SHA (Date) - Message | File: yyy"
    """
    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        repo = git.Repo(repo_path)
        
        # 为了高效，按时间正序遍历较少的 commit（或者是从 git log -S 搜索，这里我们用基础命令模拟）
        # GitPython 原生不支持高效的分页搜索 keyword 历史，这里直接调用 git log -S
        out = []
        for kw in keywords:
            try:
                # --reverse 确保按时间正序排列（最早在前）
                # 注意：不使用 -1，因为某些 git 版本中 -1 会在 --reverse 之前生效，
                # 导致返回最后修改该符号的 commit 而非首次引入
                log_output = repo.git.log('-S', kw, '--reverse', '--format=%H|%aI|%s', '--name-only')
                if not log_output:
                    out.append(f"Keyword: `{kw}` | Not found in history.")
                else:
                    # 取第一个 commit（--reverse 后最早的在前）
                    # git log --name-only 输出格式：meta_line\nfile1\nfile2\n\nmeta_line2\n...
                    # 用空行分隔不同 commit，取第一个 block
                    blocks = log_output.strip().split('\n\n')
                    first_block_lines = blocks[0].strip().split('\n') if blocks else []
                    if len(first_block_lines) >= 2:
                        meta = first_block_lines[0].split('|')
                        sha, date, msg = meta[0][:8], meta[1][:10], meta[2][:40]
                        file_path = first_block_lines[1].strip()
                        out.append(f"Keyword: `{kw}` | First appeared: {date} (SHA: {sha}) - {msg} | File: {file_path}")
                    elif first_block_lines:
                        # 只有 meta 没有文件名
                        meta = first_block_lines[0].split('|')
                        sha, date, msg = meta[0][:8], meta[1][:10], meta[2][:40]
                        out.append(f"Keyword: `{kw}` | First appeared: {date} (SHA: {sha}) - {msg}")
                    else:
                        out.append(f"Keyword: `{kw}` | Not found in history.")
            except Exception as e:
                out.append(f"Keyword: `{kw}` | Error: {str(e)}")
        
        return "\n".join(out)
    except Exception as e:
        return f"Error: {str(e)}"







if __name__ == "__main__":
    # print(type(clone_repository))
    # print(dir(clone_repository))
    print(clone_repository.run("https://gitlab.eduxiji.net/educg-group-36002-2710490/T202510003995291-2331.git"))