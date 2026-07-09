from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .contracts import ValidationReport

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WorkIdentity:
    work_id: str
    year: int
    school: str
    team: str
    work_name: str
    display_name: str
    machine_repo: str
    canonical_dir: str
    review_branch: str
    urls: dict[str, str]

    @property
    def repo_path(self) -> Path:
        path = Path(self.canonical_dir)
        return path if path.is_absolute() else ROOT / path

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_works(path: str | Path = "config/works.yaml") -> list[WorkIdentity]:
    works_path = Path(path)
    if not works_path.is_absolute():
        works_path = ROOT / works_path
    if not works_path.exists():
        return []
    raw = yaml.safe_load(works_path.read_text(encoding="utf-8")) or []
    if isinstance(raw, dict) and "works" in raw:
        raw = raw["works"]
    works: list[WorkIdentity] = []
    for item in raw:
        urls = item.get("urls") or {}
        works.append(
            WorkIdentity(
                work_id=str(item.get("work_id", "")).strip(),
                year=int(item.get("year") or 0),
                school=str(item.get("school", "")).strip(),
                team=str(item.get("team", "")).strip(),
                work_name=str(item.get("work_name", "")).strip(),
                display_name=str(item.get("display_name", "")).strip(),
                machine_repo=str(item.get("machine_repo", "")).strip(),
                canonical_dir=str(item.get("canonical_dir", "")).strip(),
                review_branch=str(item.get("review_branch", "")).strip() or "main",
                urls={str(k): str(v or "") for k, v in urls.items()},
            )
        )
    return works


def find_work(work_id: str, path: str | Path = "config/works.yaml") -> WorkIdentity | None:
    return next((work for work in load_works(path) if work.work_id == work_id), None)


def validate_work_identity(work: WorkIdentity) -> ValidationReport:
    report = ValidationReport()
    required = {
        "work_id": work.work_id,
        "school": work.school,
        "work_name": work.work_name,
        "display_name": work.display_name,
        "canonical_dir": work.canonical_dir,
        "machine_repo": work.machine_repo,
    }
    for field, value in required.items():
        if not value:
            report.add("identity.missing_field", f"work identity missing {field}")
    if work.machine_repo and work.machine_repo in work.display_name:
        report.add("identity.machine_name_in_display", "display_name must not contain machine_repo")
    if work.repo_path.exists():
        if not (work.repo_path / ".git").exists():
            report.add("identity.not_git_repo", "canonical_dir exists but is not a git repo", work.repo_path)
    else:
        report.add("identity.repo_missing", "canonical_dir does not exist", work.repo_path)
    return report


def git_text(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def init_case(work: WorkIdentity, output_root: str | Path = "output") -> Path:
    report = validate_work_identity(work)
    report.raise_for_errors()
    case_dir = (ROOT / output_root / work.work_id).resolve()
    meta_dir = case_dir / "case_state"
    meta_dir.mkdir(parents=True, exist_ok=True)
    commit = git_text(work.repo_path, "rev-parse", work.review_branch)
    tree = git_text(work.repo_path, "rev-parse", f"{commit}^{{tree}}")
    branch = git_text(work.repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    manifest = {
        "schema": "review_case.manifest.v1",
        "work": work.as_dict(),
        "repo": {
            "path": str(work.repo_path),
            "review_branch": work.review_branch,
            "current_branch": branch,
            "commit": commit,
            "tree": tree,
        },
    }
    (meta_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (meta_dir / "repo_snapshot.json").write_text(json.dumps(manifest["repo"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (meta_dir / "works.snapshot.yaml").write_text(yaml.safe_dump([work.as_dict()], allow_unicode=True, sort_keys=False), encoding="utf-8")
    return case_dir
