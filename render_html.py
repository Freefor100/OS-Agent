"""Standalone HTML re-render script.

Usage:
    python render_html.py                        # uses REPO_URL from .env
    python render_html.py output/xv6-k210        # pass repo output dir directly
    python render_html.py output/xv6-k210 --force  # re-render even if index.html exists

Reads _per_stage/xx_answers.json (02-09) and sections/01_*.md / sections/10_*.md,
then writes index.html + html/02-09.html into the repo output directory.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)


def main() -> None:
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if not a.startswith("--")]

    if args:
        repo_output_dir = args[0].rstrip("/\\")
    else:
        repo_url = os.environ.get("REPO_URL", "").strip()
        if not repo_url:
            print("Usage: python render_html.py <repo_output_dir> [--force]")
            print("       or set REPO_URL in .env")
            sys.exit(1)
        from core.utils import repo_name_from_url
        repo_name = repo_name_from_url(repo_url)
        repo_output_dir = os.path.join("output", repo_name)

    if not os.path.isdir(repo_output_dir):
        print(f"Error: directory not found: {repo_output_dir}")
        sys.exit(1)

    index_path = os.path.join(repo_output_dir, "index.html")
    if os.path.isfile(index_path) and not force:
        print(f"index.html already exists at {index_path}")
        print("Use --force to re-render.")
        sys.exit(0)

    repo_name = os.path.basename(os.path.abspath(repo_output_dir))
    repo_url = os.environ.get("REPO_URL", "")
    if not repo_url:
        profile_path = os.path.join(repo_output_dir, "repo_profile.json")
        if os.path.isfile(profile_path):
            import json
            with open(profile_path, encoding="utf-8") as f:
                profile = json.load(f)
            repo_url = profile.get("repo_url", "")

    repo_meta = {}
    for env_key, meta_key in [
        ("REPO_YEAR", "year"),
        ("REPO_COMPETITION", "competition"),
        ("REPO_SUB_COMPETITION", "sub_competition"),
        ("REPO_SCHOOL", "school"),
        ("REPO_TEAM", "team"),
    ]:
        val = os.environ.get(env_key, "").strip()
        if val:
            repo_meta[meta_key] = val

    from datetime import datetime
    from core.html_renderer import publish_html_report

    path = publish_html_report(
        repo_output_dir=repo_output_dir,
        repo_name=repo_name,
        repo_url=repo_url,
        analysis_date=datetime.now().strftime("%Y年%m月%d日"),
        repo_meta=repo_meta or None,
    )
    print(f"Generated: {path}")
    html_dir = os.path.join(repo_output_dir, "html")
    if os.path.isdir(html_dir):
        for f in sorted(os.listdir(html_dir)):
            if f.endswith(".html"):
                size = os.path.getsize(os.path.join(html_dir, f))
                print(f"  html/{f}: {size:,} bytes")


if __name__ == "__main__":
    main()
