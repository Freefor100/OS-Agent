from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.evidence import stable_id


CACHE_ROOT = Path(".fp_cache")
SNAPSHOT_ROOT = CACHE_ROOT / "snapshots"
SNAPSHOT_SCHEMA = "git_snapshot_v1"


@dataclass(frozen=True)
class RepoSnapshot:
    snapshot_id: str
    repo: str
    repo_path: str
    commit: str
    tree_hash: str
    canonical_branch: str
    ref_aliases: list[str]
    materialized_path: str
    schema_version: str = SNAPSHOT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["display_ref"] = self.canonical_branch or self.commit[:12]
        row["display_name"] = f"{self.repo}@{row['display_ref']}"
        return row

    def to_public_dict(self) -> dict[str, Any]:
        """Version identity safe to expose to the Agent and reports."""
        row = self.to_dict()
        row.pop("repo_path", None)
        row.pop("materialized_path", None)
        return row


def resolve_snapshot(repo_path: str, ref: str = "HEAD", *, materialize: bool = True) -> RepoSnapshot:
    root = Path(repo_path).resolve()
    if not (root / ".git").exists():
        raise ValueError(f"not a git repository: {repo_path}")

    commit = _git(root, "rev-parse", f"{ref}^{{commit}}")
    tree_hash = _git(root, "rev-parse", f"{commit}^{{tree}}")
    aliases = _aliases_for_commit(root, commit)
    canonical = _canonical_branch(ref, aliases)
    repo = root.name
    snapshot_id = stable_id(
        "snap",
        {"repo": repo, "commit": commit, "tree": tree_hash, "schema": SNAPSHOT_SCHEMA},
        16,
    )
    target = SNAPSHOT_ROOT / f"{repo}__{commit[:16]}"
    if materialize:
        _materialize(root, commit, target, snapshot_id, tree_hash)
    return RepoSnapshot(
        snapshot_id=snapshot_id,
        repo=repo,
        repo_path=str(root),
        commit=commit,
        tree_hash=tree_hash,
        canonical_branch=canonical,
        ref_aliases=aliases,
        materialized_path=str(target.resolve()),
    )


def discover_commit_snapshots(repo_path: str, *, materialize: bool = False) -> list[RepoSnapshot]:
    root = Path(repo_path).resolve()
    rows: dict[str, RepoSnapshot] = {}
    refs = _git_lines(
        root,
        "for-each-ref",
        "--format=%(refname)",
        "refs/heads",
        "refs/remotes",
    )
    for full_ref in refs:
        ref = _display_ref(full_ref)
        if not ref or ref.endswith("/HEAD"):
            continue
        try:
            snap = resolve_snapshot(str(root), ref, materialize=materialize)
        except (ValueError, subprocess.CalledProcessError):
            continue
        rows.setdefault(snap.commit, snap)
    return sorted(rows.values(), key=lambda s: (s.canonical_branch, s.commit))


def default_snapshot(repo_path: str, *, materialize: bool = False) -> RepoSnapshot:
    """Return the checked-out branch tip, which is the default version of a clone."""
    return resolve_snapshot(repo_path, "HEAD", materialize=materialize)


def branch_tip_snapshots(repo_path: str, *, materialize: bool = False) -> list[dict[str, Any]]:
    """Return one row per unique branch-tip commit; historical commits are excluded."""
    root = Path(repo_path).resolve()
    default = default_snapshot(str(root), materialize=materialize)
    rows = []
    for snap in discover_commit_snapshots(str(root), materialize=materialize):
        row = snap.to_public_dict()
        row["is_default"] = snap.commit == default.commit
        row["committed_at"] = _git(root, "show", "-s", "--format=%cI", snap.commit)
        rows.append(row)
    rows.sort(key=lambda row: row["display_name"])
    rows.sort(key=lambda row: row["committed_at"], reverse=True)
    rows.sort(key=lambda row: row["is_default"], reverse=True)
    return rows


def snapshot_manifest_path(snapshot: RepoSnapshot) -> Path:
    return Path(snapshot.materialized_path) / ".os_agent_snapshot.json"


def _materialize(root: Path, commit: str, target: Path, snapshot_id: str, tree_hash: str) -> None:
    manifest = target / ".os_agent_snapshot.json"
    if manifest.is_file():
        try:
            current = json.loads(manifest.read_text(encoding="utf-8"))
            if current.get("commit") == commit and current.get("tree_hash") == tree_hash:
                return
        except (OSError, json.JSONDecodeError):
            pass

    tmp = target.with_name(f".{target.name}.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", commit],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        _safe_extract(tar, tmp)
    (tmp / ".os_agent_snapshot.json").write_text(
        json.dumps(
            {
                "schema_version": SNAPSHOT_SCHEMA,
                "snapshot_id": snapshot_id,
                "repo": root.name,
                "commit": commit,
                "tree_hash": tree_hash,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    backup = target.with_name(f".{target.name}.backup")
    if target.exists():
        target.rename(backup)
    try:
        tmp.rename(target)
    except OSError:
        if backup.exists():
            backup.rename(target)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_extract(tar: tarfile.TarFile, target: Path) -> None:
    root = target.resolve()
    for member in tar.getmembers():
        out = (target / member.name).resolve()
        if root not in out.parents and out != root:
            raise ValueError(f"unsafe archive path: {member.name}")
    tar.extractall(target, filter='data')


def _aliases_for_commit(root: Path, commit: str) -> list[str]:
    refs = _git_lines(root, "for-each-ref", "--format=%(refname)|%(objectname)", "refs/heads", "refs/remotes")
    aliases = sorted(
        _display_ref(ref) for row in refs
        if "|" in row
        for ref, obj in [row.split("|", 1)]
        if obj == commit
    )
    return aliases


def _display_ref(ref: str) -> str:
    for prefix in ("refs/heads/", "refs/remotes/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


def _canonical_branch(requested: str, aliases: list[str]) -> str:
    if requested not in {"", "HEAD"}:
        return requested.replace("origin/", "")
    local = [x for x in aliases if "/" not in x]
    if local:
        return local[0]
    return aliases[0].replace("origin/", "") if aliases else requested or "HEAD"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _git_lines(root: Path, *args: str) -> list[str]:
    text = _git(root, *args)
    return [line.strip() for line in text.splitlines() if line.strip()]
