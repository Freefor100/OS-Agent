from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

try:
    import openpyxl
except Exception:  # openpyxl is optional at import time
    openpyxl = None  # type: ignore


# Teaching prototype kernels: for these we only label "教学原型 OS" and never
# attribute a competition team, because they are upstream references rather
# than contest submissions.
BASE_OS_MARKERS: tuple[str, ...] = (
    "xv6", "rcore", "ucore", "arceos", "starry", "zcore", "nimbos",
    "egos", "mit-pdos", "rust-raspberrypi-os", "blog_os",
)


def _norm_url_key(url: str) -> str:
    """Reduce a git URL to a stable basename key (last path segment, no .git)."""
    raw = str(url or "").strip().rstrip("/")
    if not raw:
        return ""
    raw = raw.removesuffix(".git")
    # handle scp-style git@host:owner/repo
    raw = raw.replace("\\", "/")
    return raw.split("/")[-1].lower()


def classify_base_os(repo_name: str, repo_path: str = "") -> dict[str, Any] | None:
    """Return a teaching-prototype label when the repo is a known base OS."""
    hay = f"{repo_name} {repo_path}".lower()
    for marker in BASE_OS_MARKERS:
        if marker in hay:
            return {"is_base_os": True, "label_zh": "教学原型 OS", "label_en": "Teaching prototype OS", "marker": marker}
    return None


def load_submission_index(xlsx_path: str | Path) -> dict[str, dict[str, Any]]:
    """Build {url_basename_key -> submission row} from the contest spreadsheet."""
    path = Path(xlsx_path)
    if openpyxl is None or not path.is_file():
        return {}
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            continue
        cols = [str(c).strip() if c is not None else "" for c in header]

        def col(name: str) -> int:
            return cols.index(name) if name in cols else -1

        idx = {k: col(k) for k in ("年份", "赛事", "子赛事", "学校", "队伍名称", "仓库地址")}
        if idx["仓库地址"] < 0:
            continue
        for raw in rows:
            if raw is None:
                continue
            url = str(raw[idx["仓库地址"]] or "").strip() if idx["仓库地址"] < len(raw) else ""
            key = _norm_url_key(url)
            if not key:
                continue
            index[key] = {
                "year": _cell(raw, idx["年份"]),
                "contest": _cell(raw, idx["赛事"]),
                "track": _cell(raw, idx["子赛事"]),
                "school": _cell(raw, idx["学校"]),
                "team": _cell(raw, idx["队伍名称"]),
                "repo_url": url,
            }
    return index


def _cell(row: tuple[Any, ...], i: int) -> str:
    if i is None or i < 0 or i >= len(row):
        return ""
    val = row[i]
    return "" if val is None else str(val).strip()


def _git_remote_url(repo_path: str) -> str:
    try:
        cp = subprocess.run(
            ["git", "-C", repo_path, "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=8,
        )
        return cp.stdout.strip()
    except Exception:
        return ""


def match_submission(repo_name: str, repo_path: str, xlsx_path: str | Path) -> dict[str, Any]:
    """Resolve display metadata for one repo.

    Membership in the contest spreadsheet is authoritative: a repo found there
    is a submission, even if its name contains a base-OS marker (e.g. the
    contest entry ``retrhelo/xv6-k210`` is a submission, not a prototype).
    Only repos absent from the spreadsheet that match a base-OS marker are
    labelled teaching prototypes. Returns a dict always carrying ``is_base_os``.
    """
    index = load_submission_index(xlsx_path)
    candidates = [
        _norm_url_key(_git_remote_url(repo_path)),
        _norm_url_key(repo_name),
        repo_name.strip().lower(),
    ]
    for key in candidates:
        if key and key in index:
            return {"repo_name": repo_name, "is_base_os": False, **index[key]}

    base = classify_base_os(repo_name, repo_path)
    if base:
        return {"repo_name": repo_name, **base}
    return {"repo_name": repo_name, "is_base_os": False, "unmatched": True}
