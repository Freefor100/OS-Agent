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
def analyze_git_history(repo_path: str) -> str:
    """
    分析 Git 仓库的提交历史。
    
    Args:
        repo_path: 本地仓库路径
    
    Returns:
        仓库提交历史的分析结果
    """
    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        
        repo = git.Repo(repo_path)
        
        # 获取提交历史
        commits = list(repo.iter_commits(max_count=50))  # 最多50个提交
        
        if not commits:
            return "No commits found in repository"
        
        # 分析提交信息
        result = f"Found {len(commits)} commits:\n\n"
        
        for i, commit in enumerate(commits[:10], 1):  # 显示前10个
            result += f"{i}. {commit.hexsha[:8]} - {commit.author.name}\n"
            result += f"   Date: {commit.committed_datetime}\n"
            result += f"   Message: {commit.message.strip()[:80]}\n\n"
        
        if len(commits) > 10:
            result += f"... and {len(commits) - 10} more commits\n"
        
        return result
        
    except Exception as e:
        return f"Error analyzing git history: {str(e)}"


@tool
def analyze_git_history_detailed(repo_path: str, max_commits: int = 100) -> str:
    """
    分析 Git 仓库的详细提交历史，包含每次提交的增删行数、变更文件等。
    用于撰写项目开发历史描述。

    Args:
        repo_path: 本地仓库路径（如 repos/RepoName）
        max_commits: 最多分析的提交数量，默认 100

    Returns:
        按时间倒序的提交列表，每项含：日期、作者、摘要、增/删行数、涉及顶层模块
    """
    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        repo = git.Repo(repo_path)
        commits = list(repo.iter_commits(max_count=max_commits))
        if not commits:
            return "No commits found in repository."
        lines = [f"共 {len(commits)} 条提交（最多 {max_commits}）：\n"]
        for i, c in enumerate(commits[:50], 1):
            dt = c.committed_datetime.strftime("%Y-%m-%d %H:%M")
            msg = (c.message or "").strip().replace("\n", " ")[:80]
            try:
                st = c.stats.total
                add, dec = st.get("insertions", 0), st.get("deletions", 0)
            except Exception:
                add, dec = 0, 0
            modules = set()
            try:
                for p in (c.stats.files or {}):
                    m = _module_from_path(p)
                    if m:
                        modules.add(m)
            except Exception:
                pass
            mod_str = ",".join(sorted(modules)) if modules else "-"
            lines.append(
                f"{i}. [{dt}] {c.author.name} | +{add} -{dec} | 模块:{mod_str}\n"
                f"   {msg}\n"
            )
        if len(commits) > 50:
            lines.append(f"\n... 以及另外 {len(commits) - 50} 条提交\n")
        return "".join(lines)
    except Exception as e:
        return f"Error analyzing git history: {str(e)}"


@tool
def get_dev_history_by_module(repo_path: str, max_commits: int = 150) -> str:
    """
    按顶层模块汇总开发历史，标出各模块的「初步提交」与「较大改动」提交。
    用于生成开发时间线描述和柱状图：例如「进程调度」某日初步 commit，某日较大改动。

    Args:
        repo_path: 本地仓库路径
        max_commits: 最多分析的提交数

    Returns:
        文本形式的按模块时间线，含日期、说明（初步/较大改动）、增删行数
    """
    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        repo = git.Repo(repo_path)
        commits = list(repo.iter_commits(max_count=max_commits))
        if not commits:
            return "No commits found."
        # (module -> [(date_str, msg, add, del, is_initial, is_major)])
        by_module = defaultdict(list)
        for c in commits:
            try:
                st = c.stats.total
                add = st.get("insertions", 0)
                dec = st.get("deletions", 0)
            except Exception:
                add, dec = 0, 0
            diff_sum = add + dec
            dt = c.committed_datetime.strftime("%Y-%m-%d")
            msg = (c.message or "").strip().replace("\n", " ")[:60]
            seen = set()
            for p in (c.stats.files or {}):
                m = _module_from_path(p)
                if not m or m in seen:
                    continue
                seen.add(m)
                by_module[m].append((dt, msg, add, dec, diff_sum))
        # 每个模块按时间正序，标记 初步 / 较大改动
        out = []
        total_commits_shown = 0
        max_commits_per_module = 20  # 每个模块最多显示的提交数
        truncated_modules = 0
        
        for mod in sorted(by_module.keys()):
            rows = by_module[mod]
            rows.sort(key=lambda x: x[0])
            diffs = [r[4] for r in rows]
            thresh = max(diffs) * 0.5 if diffs else 0
            out.append(f"\n## 模块 [{mod}] ({len(rows)} 条提交)\n")
            
            rows_to_show = rows[:max_commits_per_module]
            for i, (dt, msg, add, dec, _) in enumerate(rows_to_show):
                is_initial = i == 0
                is_major = rows[i][4] >= thresh and rows[i][4] > 20
                tag = "【初步】" if is_initial else ("【较大改动】" if is_major else "")
                out.append(f"  {dt}  +{add} -{dec}  {tag} {msg}\n")
                total_commits_shown += 1
            
            if len(rows) > max_commits_per_module:
                out.append(f"  ... 还有 {len(rows) - max_commits_per_module} 条提交未显示\n")
                truncated_modules += 1
        
        # 添加统计信息
        out.append(f"\n📊 统计: 分析了 {len(commits)} 条提交，涉及 {len(by_module)} 个模块")
        if len(commits) >= max_commits:
            out.append(f"\n⚠️ [提交数限制] 只分析了最近 {max_commits} 条提交")
        if truncated_modules > 0:
            out.append(f"\n⚠️ [显示限制] {truncated_modules} 个模块的提交记录被截断（每模块最多显示 {max_commits_per_module} 条）")
        
        return "".join(out) if out else "No module history."
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def generate_dev_history_charts(repo_path: str, output_dir: str) -> str:
    """
    根据仓库提交历史生成开发历史柱状图，保存为 PNG。
    包含：总体 commits 随时间分布；各顶层模块的提交量/变更量柱状图。

    Args:
        repo_path: 本地仓库路径
        output_dir: 图片输出目录（如 ./output/charts），若不存在会自动创建

    Returns:
        生成的图片路径列表，可在 Markdown 中通过 ![](path) 引用
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime
    except ImportError:
        return "Error: matplotlib not installed. pip install matplotlib"

    # 配置中文字体，避免绘图中文乱码；Matplotlib 会使用列表中第一个可用字体
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
        "KaiTi",
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "Noto Sans CJK SC",
        "PingFang SC",
        "Heiti SC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False  # 负号正常显示，避免显示为方框

    try:
        if not os.path.exists(repo_path):
            return f"Error: Repository path not found: {repo_path}"
        os.makedirs(output_dir, exist_ok=True)
        repo = git.Repo(repo_path)
        commits = list(repo.iter_commits(max_count=500))
        if not commits:
            return "No commits; no charts generated."

        by_module = defaultdict(list)
        monthly = defaultdict(int)
        for c in commits:
            dt = c.committed_datetime
            monthly[dt.strftime("%Y-%m")] += 1
            try:
                st = c.stats.total
                add = st.get("insertions", 0)
                dec = st.get("deletions", 0)
            except Exception:
                add, dec = 0, 0
            diff_sum = add + dec
            msg = (c.message or "").strip().split("\n")[0][:50]
            for p in (c.stats.files or {}):
                m = _module_from_path(p)
                if m:
                    by_module[m].append((dt, diff_sum, msg, c.hexsha[:7]))
                    break

        paths = []
        # 1. 总体月度提交量柱状图
        months = sorted(monthly.keys())
        counts = [monthly[m] for m in months]
        if months:
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.bar(months, counts, color="steelblue", edgecolor="navy", alpha=0.8)
            ax.set_xlabel("月份")
            ax.set_ylabel("提交数")
            ax.set_title("仓库提交历史（按月）")
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            p = os.path.join(output_dir, "commits_monthly.png")
            fig.savefig(p, dpi=120, bbox_inches="tight")
            plt.close()
            paths.append(os.path.abspath(p))

        # 2. 各模块提交量柱状图
        if by_module:
            mods = list(by_module.keys())[:12]
            totals = [sum(x[1] for x in by_module[m]) for m in mods]
            fig, ax = plt.subplots(figsize=(max(8, len(mods) * 0.8), 4))
            ax.bar(mods, totals, color="teal", edgecolor="darkgreen", alpha=0.8)
            ax.set_xlabel("模块")
            ax.set_ylabel("变更行数（增+删）")
            ax.set_title("各模块开发活跃度")
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            p = os.path.join(output_dir, "modules_activity.png")
            fig.savefig(p, dpi=120, bbox_inches="tight")
            plt.close()
            paths.append(os.path.abspath(p))

        # 3. 模块开发里程碑时间线图（新增）
        if by_module:
            # 筛选前 8 个最活跃的模块
            top_mods = sorted(by_module.keys(), key=lambda m: len(by_module[m]), reverse=True)[:8]
            
            fig, ax = plt.subplots(figsize=(14, max(6, len(top_mods) * 0.8)))
            
            colors = plt.cm.Set2(range(len(top_mods)))
            
            for i, mod in enumerate(top_mods):
                commits_data = sorted(by_module[mod], key=lambda x: x[0])  # 按时间排序
                if not commits_data:
                    continue
                
                # 计算阈值：变更量超过平均值 2 倍且超过 30 行的为"较大改动"
                all_diffs = [c[1] for c in commits_data]
                avg_diff = sum(all_diffs) / len(all_diffs) if all_diffs else 0
                threshold = max(avg_diff * 2, 30)
                
                # 提取里程碑
                milestones = []
                # 第一个 commit 是"初步"
                first = commits_data[0]
                milestones.append((first[0], "初步", first[2], first[1]))
                
                # 找出所有"较大改动"
                for dt, diff, msg, sha in commits_data[1:]:
                    if diff >= threshold:
                        milestones.append((dt, "较大改动", msg, diff))
                
                # 最多显示 5 个里程碑（1 个初步 + 4 个较大改动）
                if len(milestones) > 5:
                    milestones = [milestones[0]] + sorted(milestones[1:], key=lambda x: x[3], reverse=True)[:4]
                    milestones.sort(key=lambda x: x[0])
                
                # 绘制时间线
                y = len(top_mods) - i
                dates = [m[0] for m in milestones]
                
                # 绘制水平线（模块时间跨度）
                if len(dates) > 1:
                    ax.hlines(y, min(dates), max(dates), colors=colors[i], linewidth=2, alpha=0.6)
                
                # 绘制里程碑点
                for dt, tag, msg, diff in milestones:
                    marker = 'o' if tag == "初步" else 's'
                    size = 100 if tag == "初步" else 60 + min(diff / 10, 100)
                    ax.scatter(dt, y, s=size, c=[colors[i]], marker=marker, edgecolors='black', linewidths=0.5, zorder=5)
                    
                    # 添加日期标签（只显示初步和较大改动的日期）
                    label = f"{dt.strftime('%m/%d')}"
                    if tag == "初步":
                        label = f"初步\n{dt.strftime('%Y-%m-%d')}"
                    ax.annotate(label, (dt, y), textcoords="offset points", xytext=(0, 10), ha='center', fontsize=7, alpha=0.8)
            
            # 设置 Y 轴为模块名
            ax.set_yticks(range(1, len(top_mods) + 1))
            ax.set_yticklabels(reversed(top_mods))
            
            # 设置 X 轴日期格式
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
            plt.xticks(rotation=45, ha='right')
            
            ax.set_xlabel("时间")
            ax.set_ylabel("模块")
            ax.set_title("模块开发里程碑时间线（○=初步提交，□=较大改动）")
            ax.grid(True, axis='x', alpha=0.3)
            
            plt.tight_layout()
            p = os.path.join(output_dir, "modules_timeline.png")
            fig.savefig(p, dpi=120, bbox_inches="tight")
            plt.close()
            paths.append(os.path.abspath(p))

        return "Charts saved:\n" + "\n".join(paths)
    except Exception as e:
        import traceback
        return f"Error generating charts: {str(e)}\n{traceback.format_exc()}"


if __name__ == "__main__":
    # print(type(clone_repository))
    # print(dir(clone_repository))
    print(clone_repository.run("https://gitlab.eduxiji.net/educg-group-36002-2710490/T202510003995291-2331.git"))