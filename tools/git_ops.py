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
def analyze_git_history(repo_path: str, max_commits: int = 50, skip: int = 0, path_filter: str = "") -> str:
    """
    获取 Git 仓库的原始提交历史（包含文件变更详情），供 LLM 自行进行语义分析。
    
    Args:
        repo_path: 本地仓库路径
        max_commits: 一次最多返回的提交数量（防止超长，建议50-100）
        skip: 分页跳过的提交数量，用于查看更早的历史
        path_filter: 可选。指定要过滤查看的具体目录或文件路径（如 "kernel/fs"），常用于递进式深入分析某模块的提交情况。
    
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
            
            # Extract file changes and group by exact directory
            file_changes = []
            try:
                if c.stats.files:
                    from collections import defaultdict
                    dir_stats = defaultdict(lambda: {"adds": 0, "dels": 0, "count": 0})
                    
                    # Normalize filter path
                    pf = path_filter.replace("\\", "/").strip("/") if path_filter else ""
                    
                    for filepath, stats in c.stats.files.items():
                        norm_path = filepath.replace("\\", "/")
                        if pf and not norm_path.startswith(pf):
                            continue
                            
                        adds = stats.get('insertions', 0)
                        dels = stats.get('deletions', 0)
                        
                        group_key = os.path.dirname(norm_path)
                        if not group_key:
                            group_key = "(root)"
                            
                        dir_stats[group_key]["adds"] += adds
                        dir_stats[group_key]["dels"] += dels
                        dir_stats[group_key]["count"] += 1
                        
                    # If absolutely no files matched the filter in this commit, skip printing changed files.
                    if not dir_stats and pf:
                        continue 
                        
                    sorted_dirs = sorted(
                        dir_stats.items(),
                        key=lambda x: x[1]["adds"] + x[1]["dels"],
                        reverse=True
                    )
                    
                    for d, s in sorted_dirs:
                        file_changes.append(f"  [{d}/] {s['count']} files (+{s['adds']} -{s['dels']})")
            except Exception:
                pass
            
            if file_changes:
                total_files = sum(s['count'] for s in dir_stats.values())
                lines.append(f"Changed Subsystems (Total: {total_files} files in {len(dir_stats)} dirs):")
                if len(file_changes) > 20:
                    lines.extend(file_changes[:20])
                    lines.append(f"  ... and {len(file_changes) - 20} more directories omitted. (Use `path_filter` to drill down)")
                else:
                    lines.extend(file_changes)
            elif not pf:
                lines.append("Changed Files: (No explicit file diff available)")
            else:
                lines.append(f"Changed Files: (None matching filter '{path_filter}')")
            lines.append("-" * 40)
            
        result = "\n".join(lines)
        if len(result) > 25000:
            result = result[:25000] + "\n... [Output truncated to 25000 chars to prevent token explosion] ..."
        return result
        
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







@tool
def trace_file_evolution(repo_path: str, file_path: str, max_commits: int = 50) -> str:
    """
    跟踪核心文件从诞生到现在的演进轨迹（生命周期）。
    
    Args:
        repo_path: 本地仓库路径
        file_path: 需要追踪的具体文件路径（相对仓库根目录，如 "kernel/sched.rs"）
        max_commits: 最多返回的变更节点数（默认50）
        
    Returns:
        该文件历次被修改的 Commit 列表，包含由于重命名或移动引发的变更，以及对应行的增删。
    """
    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        repo = git.Repo(repo_path)
        
        # 使用 git log --follow 追踪文件重命名历史
        # --numstat 输出: adds dels filename
        log_output = repo.git.log('--follow', '--numstat', '--format=COMMIT|%h|%aI|%s', '-n', str(max_commits), '--', file_path)
        
        if not log_output.strip():
            return f"No history found for file: {file_path}"
            
        lines = log_output.strip().split('\n')
        out = [f"Evolution of `{file_path}`:"]
        
        current_commit = ""
        for line in lines:
            if line.startswith('COMMIT|'):
                parts = line.split('|')
                sha, date, msg = parts[1], parts[2][:10], parts[3]
                current_commit = f"[{date}] SHA:{sha} - {msg}"
            elif line.strip() and not line.startswith('COMMIT|'):
                # numstat line: 12  3   filename
                stat_parts = line.split('\t')
                if len(stat_parts) >= 2:
                    adds = stat_parts[0] if stat_parts[0] != '-' else '0'
                    dels = stat_parts[1] if stat_parts[1] != '-' else '0'
                    out.append(f"{current_commit} (+{adds} -{dels})")
                    current_commit = "" # prevent double printing if multiple numstat lines appear for renames
        
        return "\n".join(out)
    except Exception as e:
        return f"Error tracing file evolution: {str(e)}"


@tool
def analyze_authors_contribution(repo_path: str, days: int = 365) -> str:
    """
    分析仓库的贡献者开发图谱与模块分工。
    
    Args:
        repo_path: 本地仓库路径
        days: 分析最近多少天的提交（默认 365 天，如果要全量可传 9999）
        
    Returns:
        每个贡献者的总 Commit 数、总增删行数，以及他们主力贡献的 Top-3 目录，用于分析项目是单人作业还是社区分工协作。
    """
    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        repo = git.Repo(repo_path)
        
        import datetime
        since_date = datetime.datetime.now() - datetime.timedelta(days=days)
        
        authors = defaultdict(lambda: {"commits": 0, "adds": 0, "dels": 0, "dirs": defaultdict(int)})
        
        # 为了防卡死，最多遍历最近 2000 个 commit
        commits = list(repo.iter_commits(max_count=2000))
        for c in commits:
            if c.committed_datetime.replace(tzinfo=None) < since_date:
                continue
                
            author = (c.author.name or "unknown")[:25]
            authors[author]["commits"] += 1
            
            try:
                if c.stats.files:
                    for filepath, stats in c.stats.files.items():
                        adds = stats.get('insertions', 0)
                        dels = stats.get('deletions', 0)
                        authors[author]["adds"] += adds
                        authors[author]["dels"] += dels
                        
                        top_dir = filepath.replace("\\", "/").split("/")[0]
                        if not top_dir or top_dir.startswith('.'):
                            top_dir = "(root)"
                        authors[author]["dirs"][top_dir] += (adds + dels)
            except Exception:
                pass
                
        if not authors:
            return "No contributions found in the given time range."
            
        out = [f"Author Contribution Graph (Last {days} days, max 2000 commits):", "-" * 50]
        
        # Sort authors by total edits
        sorted_authors = sorted(authors.items(), key=lambda x: x[1]["adds"] + x[1]["dels"], reverse=True)
        
        for author, data in sorted_authors:
            # Sort top directories for this author
            sorted_dirs = sorted(data["dirs"].items(), key=lambda x: x[1], reverse=True)[:3]
            top_dirs_str = ", ".join(f"{d}({v} lines)" for d, v in sorted_dirs)
            
            out.append(f"Author: {author}")
            out.append(f"  Commits: {data['commits']} | Edits: +{data['adds']} -{data['dels']}")
            out.append(f"  Focus Areas: {top_dirs_str if top_dirs_str else 'N/A'}")
            out.append("")
            
        return "\n".join(out)
    except Exception as e:
        return f"Error analyzing authors: {str(e)}"


@tool
def get_commit_diff_summary(repo_path: str, commit_sha: str) -> str:
    """
    获取某次特定 Commit 的轻量级代码变更语义摘要（过滤空白，仅提取真正变动的核心逻辑）。
    
    Args:
        repo_path: 本地仓库路径
        commit_sha: 想要透视的特定 Commit SHA 哈希值
        
    Returns:
        精简后的代码 Diff，去除了大量的上下文和注释，让你一眼看穿这次提交在函数级别新增或删除了什么核心逻辑。
    """
    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        repo = git.Repo(repo_path)
        
        commit = repo.commit(commit_sha)
        
        # 只取单次提交的代码变更树
        diff_str = repo.git.show(commit_sha, '--format=', '--unified=0', '--ignore-all-space', '--ignore-blank-lines')
        
        if not diff_str.strip():
            return "No text-based diff available or only invisible spaces changed."
            
        # 净化 Diff：只保留带有 + 或 - 的行，以及文件名
        clean_out = []
        current_file = ""
        added_lines = 0
        deleted_lines = 0
        
        lines = diff_str.split('\n')
        for line in lines:
            if line.startswith('diff --git'):
                if current_file and (added_lines > 0 or deleted_lines > 0):
                    clean_out.append(f"\n--- {current_file} (+{added_lines} -{deleted_lines}) ---")
                
                parts = line.split(' b/')
                if len(parts) > 1:
                    current_file = parts[-1]
                else:
                    current_file = line.split()[-1]
                added_lines = 0
                deleted_lines = 0
                clean_out.append(f"\nFile: {current_file}")
                
            elif line.startswith('@@'):
                pass # skip chunk headers in minimal mode
            elif line.startswith('+') and not line.startswith('+++'):
                # 过滤掉注释行
                c_line = line[1:].strip()
                if not (c_line.startswith('//') or c_line.startswith('/*') or c_line.startswith('*')):
                    clean_out.append(line)
                    added_lines += 1
            elif line.startswith('-') and not line.startswith('---'):
                c_line = line[1:].strip()
                if not (c_line.startswith('//') or c_line.startswith('/*') or c_line.startswith('*')):
                    clean_out.append(line)
                    deleted_lines += 1
                    
        # 保护机制防止巨型重构透视导致炸裂
        full_res = "\n".join(clean_out)
        if len(full_res) > 20000:
            return full_res[:20000] + "\n\n... [Diff too large, truncated to 20000 chars] ..."
            
        return full_res
    except Exception as e:
        return f"Error getting commit diff: {str(e)}"

if __name__ == "__main__":
    # print(type(clone_repository))
    # print(dir(clone_repository))
    print(clone_repository.run("https://gitlab.eduxiji.net/educg-group-36002-2710490/T202510003995291-2331.git"))