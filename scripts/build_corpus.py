#!/usr/bin/env python3
"""Batch-run Agent D for Agent D corpus repositories.

用法:
    python scripts/build_corpus.py                # 用 .env AGENT_C_CORPUS_REPOS
    python scripts/build_corpus.py repo1 repo2    # 显式指定
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


def main():
    parser = argparse.ArgumentParser(description="批量跑 Agent D 生成 output/<repo>/_agent_d")
    parser.add_argument("repos", nargs="*",
                        help="仓库名列表（默认 AGENT_C_CORPUS_REPOS）")
    parser.add_argument("--repos-root", default="repos",
                        help="仓库源码根目录（默认 repos/）")
    parser.add_argument("--ui", action="store_true", help="为每个仓库启动进度 UI")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    repos = args.repos or [
        n.strip()
        for n in os.environ.get("AGENT_C_CORPUS_REPOS", "").split(",")
        if n.strip()
    ]
    if not repos:
        print("错误：corpus 列表为空。命令行参数或 AGENT_C_CORPUS_REPOS 至少给一个", file=sys.stderr)
        sys.exit(2)

    here = os.path.dirname(os.path.abspath(__file__))
    describe_script = os.path.join(here, "run_describe.py")

    failed = []
    for repo in repos:
        repo_path = os.path.join(args.repos_root, repo)
        if not os.path.isdir(repo_path):
            print(f"⚠ 跳过 {repo}（{repo_path} 不存在）")
            failed.append(repo)
            continue
        print(f"\n=========== {repo} ===========")
        cmd = [sys.executable, describe_script, repo_path, "--repo-name", repo]
        if args.ui:
            cmd.append("--ui")
        if args.verbose: cmd.append("-v")
        rc = subprocess.call(cmd)
        if rc != 0:
            print(f"  ⚠ {repo} 失败 (exit {rc})")
            failed.append(repo)

    print(f"\n== build_corpus 完成 == 成功 {len(repos)-len(failed)} / 失败 {len(failed)}")
    if failed:
        print(f"  失败列表: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()

