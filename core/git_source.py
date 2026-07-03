from __future__ import annotations

import subprocess
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable


SOURCE_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".hpp", ".cxx", ".rs", ".S", ".s"}


@dataclass(frozen=True)
class GitBlob:
    path: str
    object_id: str
    data: bytes

    @property
    def suffix(self) -> str:
        return Path(self.path).suffix


@dataclass(frozen=True)
class GitTreeEntry:
    mode: str
    kind: str
    object_id: str
    path: str


def git_text(repo_path: str, *args: str, timeout: int = 60) -> str:
    return subprocess.run(
        ["git", "-C", str(Path(repo_path).resolve()), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    ).stdout


def list_tree(repo_path: str, commit: str) -> list[GitTreeEntry]:
    raw = subprocess.run(
        ["git", "-C", str(Path(repo_path).resolve()), "ls-tree", "-r", "-z", "--full-tree", commit],
        check=True,
        stdout=subprocess.PIPE,
        timeout=120,
    ).stdout
    entries: list[GitTreeEntry] = []
    for chunk in raw.split(b"\0"):
        if not chunk:
            continue
        meta, sep, path_raw = chunk.partition(b"\t")
        if not sep:
            continue
        parts = meta.decode("ascii", errors="ignore").split()
        if len(parts) != 3:
            continue
        entries.append(GitTreeEntry(parts[0], parts[1], parts[2], path_raw.decode("utf-8", errors="surrogateescape")))
    return entries


def iter_source_blobs(repo_path: str, commit: str, *, suffixes: set[str] | None = None,
                      max_bytes: int = 4 * 1024 * 1024,
                      exclude_prefixes: list[str] | tuple[str, ...] | None = None) -> Iterable[GitBlob]:
    selected_suffixes = suffixes or SOURCE_SUFFIXES
    excluded = tuple(_clean_rel(prefix).rstrip("/") + "/" for prefix in (exclude_prefixes or []) if _clean_rel(prefix))
    entries = [
        entry for entry in list_tree(repo_path, commit)
        if entry.kind == "blob" and Path(entry.path).suffix in selected_suffixes
        and not any(entry.path == prefix[:-1] or entry.path.startswith(prefix) for prefix in excluded)
    ]
    yield from cat_file_blobs(repo_path, entries, max_bytes=max_bytes)


def cat_file_blobs(repo_path: str, entries: list[GitTreeEntry], *, max_bytes: int = 4 * 1024 * 1024) -> Iterable[GitBlob]:
    if not entries:
        return
    proc = subprocess.Popen(
        ["git", "-C", str(Path(repo_path).resolve()), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None
    request = "".join(f"{entry.object_id}\n" for entry in entries).encode("ascii")
    stdout, _ = proc.communicate(request, timeout=300)
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, proc.args)
    stream = BytesIO(stdout)
    for entry in entries:
        header = stream.readline().decode("ascii", errors="ignore").strip()
        if not header:
            break
        parts = header.split()
        if len(parts) < 3 or parts[1] != "blob":
            size = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
            stream.read(size + 1)
            continue
        size = int(parts[2])
        data = stream.read(size)
        stream.read(1)  # trailing newline inserted by cat-file --batch
        if size <= max_bytes:
            yield GitBlob(entry.path, entry.object_id, data)


def blob_sizes(repo_path: str, entries: list[GitTreeEntry]) -> dict[str, int]:
    if not entries:
        return {}
    proc = subprocess.run(
        ["git", "-C", str(Path(repo_path).resolve()), "cat-file", "--batch-check=%(objectname) %(objectsize)"],
        input="".join(f"{entry.object_id}\n" for entry in entries),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    sizes: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        oid, _, size = line.partition(" ")
        if oid and size.isdigit():
            sizes[oid] = int(size)
    return sizes


def read_blob(repo_path: str, commit: str, path: str, *, max_bytes: int = 5 * 1024 * 1024) -> bytes:
    spec = f"{commit}:{_clean_rel(path)}"
    data = subprocess.run(
        ["git", "-C", str(Path(repo_path).resolve()), "show", spec],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=60,
    ).stdout
    if len(data) > max_bytes:
        raise ValueError(f"git blob is too large: {path} ({len(data)} bytes)")
    return data


def read_text(repo_path: str, commit: str, path: str, *, max_bytes: int = 5 * 1024 * 1024) -> str:
    return read_blob(repo_path, commit, path, max_bytes=max_bytes).decode("utf-8", errors="ignore")


def path_exists(repo_path: str, commit: str, path: str) -> bool:
    clean = _clean_rel(path).rstrip("/")
    if not clean:
        return True
    try:
        subprocess.run(
            ["git", "-C", str(Path(repo_path).resolve()), "cat-file", "-e", f"{commit}:{clean}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return True
    except subprocess.CalledProcessError:
        prefix = f"{clean}/"
        return any(entry.path.startswith(prefix) for entry in list_tree(repo_path, commit))


def top_level_dirs(repo_path: str, commit: str) -> list[str]:
    dirs = {
        entry.path.split("/", 1)[0]
        for entry in list_tree(repo_path, commit)
        if "/" in entry.path and not entry.path.startswith(".")
    }
    return sorted(dirs)


def _clean_rel(path: str) -> str:
    clean = str(path).replace("\\", "/").strip()
    while clean.startswith("./"):
        clean = clean[2:]
    return clean.strip("/")
