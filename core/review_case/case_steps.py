from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from .contracts import ValidationReport
from .fingerprint_search import compare_fingerprint_caches, search_fingerprint_cache, search_historical_blob_objects
from .fingerprints import BLOB_SCHEMA_VERSION, SCHEMA_VERSION, write_blob_fingerprint_cache, write_fingerprint_cache
from .identity import ROOT, find_work, git_text, init_case, load_works, validate_work_identity
from .structural import ast_algorithm_version

def init_by_work_id(work_id: str, works_path: str = "config/works.yaml", output_root: str = "output") -> Path:
    work = find_work(work_id, works_path)
    if not work:
        report = ValidationReport()
        report.add("identity.unknown_work", f"work_id not found in {works_path}: {work_id}")
        report.raise_for_errors()
    assert work is not None
    return init_case(work, output_root)


def build_inventory(case_dir: str | Path) -> tuple[Path, Path]:
    root = Path(case_dir)
    manifest = _load_manifest(root)
    repo = Path(manifest["work"]["canonical_dir"])
    if not repo.is_absolute():
        repo = ROOT / repo
    commit = manifest["repo"]["commit"]
    files = git_text(repo, "ls-tree", "-r", "--name-only", commit).splitlines()
    suffix_counts: dict[str, int] = {}
    for rel in files:
        suffix = Path(rel).suffix.lower() or "<none>"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
    out_dir = root / "case_state" / "facts"
    out_dir.mkdir(parents=True, exist_ok=True)
    inventory_json = out_dir / "repository_inventory.json"
    inventory_md = out_dir / "repository_inventory.md"
    payload = {
        "schema": "review_case.repository_inventory.v1",
        "commit": commit,
        "notice": "Raw Git tree inventory only. The Agent decides source, dependency, test, generated, and student-work boundaries.",
        "path_count": len(files),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "paths": files,
    }
    inventory_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Repository Inventory",
        "",
        f"Commit: `{commit}`",
        "",
        "以下为 Git tree 原始路径，不进行第三方、测试、生成物或学生代码分类。",
        "",
        f"Paths: {len(files)}",
        "",
    ]
    lines.extend(f"- `{path}`" for path in files)
    inventory_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return inventory_json, inventory_md


def build_fingerprint(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    manifest = _load_manifest(root)
    repo = Path(manifest["work"]["canonical_dir"])
    if not repo.is_absolute():
        repo = ROOT / repo
    commit = manifest["repo"]["commit"]
    work_id = str(manifest["work"]["work_id"])
    cache_dir = ROOT / "fp_cache" / work_id / commit
    if not _complete_head_fingerprint(cache_dir, work_id, commit):
        cache_dir = write_fingerprint_cache(
            repo=repo,
            commit=commit,
            work_id=work_id,
            display_name=str(manifest["work"].get("display_name", "")),
            cache_root=ROOT / "fp_cache",
        )
    fp_manifest = {
        "schema": "review_case.fp_manifest.v1",
        "work_id": manifest["work"]["work_id"],
        "display_name": manifest["work"].get("display_name", ""),
        "year": manifest["work"].get("year", 0),
        "repository_type": manifest["work"].get("repository_type", "competition"),
        "reference_kind": manifest["work"].get("reference_kind", ""),
        "module_ids": manifest["work"].get("module_ids", []),
        "review_ref": manifest["repo"].get("review_branch", ""),
        "commit": commit,
        "cache_dir": str(cache_dir.relative_to(ROOT) if cache_dir.is_relative_to(ROOT) else cache_dir),
        "blob": str((cache_dir / "blob.json").relative_to(ROOT) if (cache_dir / "blob.json").is_relative_to(ROOT) else cache_dir / "blob.json"),
        "structural": str((cache_dir / "ast.json").relative_to(ROOT) if (cache_dir / "ast.json").is_relative_to(ROOT) else cache_dir / "ast.json"),
    }
    out = root / "case_state" / "facts" / "fingerprint.json"
    _write_json_atomic(out, fp_manifest)
    return out


def _complete_head_fingerprint(cache_dir: Path, work_id: str, commit: str) -> bool:
    try:
        fingerprint = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
        blob = json.loads((cache_dir / "blob.json").read_text(encoding="utf-8"))
        ast = json.loads((cache_dir / "ast.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        fingerprint.get("schema") == SCHEMA_VERSION
        and fingerprint.get("work_id") == work_id
        and fingerprint.get("commit") == commit
        and fingerprint.get("components", {}).get("blob") is True
        and fingerprint.get("components", {}).get("ast") is True
        and fingerprint.get("ast_shape_version") == ast_algorithm_version()
        and blob.get("schema") == BLOB_SCHEMA_VERSION
        and blob.get("commit") == commit
        and ast.get("schema") == "review_case.structural_fingerprint.v2"
        and ast.get("commit") == commit
    )


def build_fingerprint_cache(works_path: str | Path = "config/works.yaml", cache_root: str | Path = "fp_cache", work_ids: list[str] | None = None) -> Path:
    works = load_works(works_path)
    by_id = {work.work_id: work for work in works}
    requested = list(dict.fromkeys(work_ids or []))
    unknown = [work_id for work_id in requested if work_id not in by_id]
    if unknown:
        raise ValueError(f"unknown work_id: {', '.join(unknown)}")
    cache_base = Path(cache_root)
    if not cache_base.is_absolute():
        cache_base = ROOT / cache_base
    cache_base.mkdir(parents=True, exist_ok=True)
    selected_works = [by_id[work_id] for work_id in requested] if requested else works
    for work in selected_works:
        report = validate_work_identity(work)
        report.raise_for_errors()
        commit = git_text(work.repo_path, "rev-parse", work.review_branch)
        write_fingerprint_cache(work.repo_path, commit, work.work_id, work.display_name, cache_base)
    return cache_base


def search_head_candidates(
    case_dir: str | Path,
    works_path: str | Path = "config/works.yaml",
    cache_root: str | Path = "fp_cache",
) -> Path:
    root = Path(case_dir)
    out_dir = root / "case_state" / "facts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "head_candidates.json"
    cache_base = Path(cache_root)
    if not cache_base.is_absolute():
        cache_base = ROOT / cache_base
    candidate_caches: list[dict[str, object]] = []
    missing: list[str] = []
    for work in load_works(works_path):
        validate_work_identity(work).raise_for_errors()
        commit = git_text(work.repo_path, "rev-parse", work.review_branch)
        cache_dir = cache_base / work.work_id / commit
        required = [cache_dir / "manifest.json", cache_dir / "blob.json", cache_dir / "ast.json"]
        if not all(path.is_file() for path in required):
            missing.append(work.work_id)
            continue
        candidate_caches.append(
            {
                "cache_dir": cache_dir,
                "year": work.year,
                "repository_type": work.repository_type,
                "reference_kind": work.reference_kind,
                "module_ids": work.module_ids,
                "review_ref": work.review_branch,
            }
        )
    if missing:
        sample = ", ".join(missing[:8])
        suffix = " ..." if len(missing) > 8 else ""
        raise ValueError(f"missing HEAD fingerprints for: {sample}{suffix}; run build-fp-cache for these works")
    return search_fingerprint_cache(
        out_dir / "fingerprint.json",
        candidate_caches,
        out,
    )


def compare_commits(
    left_work_id: str,
    left_commit: str,
    right_work_id: str,
    right_commit: str,
    *,
    left_ref: str,
    right_ref: str,
    works_path: str | Path = "config/works.yaml",
    cache_root: str | Path = "fp_cache",
    include_ast: bool = False,
    left_include_prefixes: list[str] | None = None,
    right_include_prefixes: list[str] | None = None,
    left_exclude_prefixes: list[str] | None = None,
    right_exclude_prefixes: list[str] | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Build and compare two explicit commit snapshots without judging lineage."""
    left = find_work(left_work_id, works_path)
    right = find_work(right_work_id, works_path)
    report = ValidationReport()
    if left is None:
        report.add("identity.unknown_work", f"work_id not found in {works_path}: {left_work_id}")
    if right is None:
        report.add("identity.unknown_work", f"work_id not found in {works_path}: {right_work_id}")
    report.raise_for_errors()
    assert left is not None and right is not None
    validate_work_identity(left).raise_for_errors()
    validate_work_identity(right).raise_for_errors()

    left_locked = git_text(left.repo_path, "rev-parse", f"{left_commit}^{{commit}}")
    right_locked = git_text(right.repo_path, "rev-parse", f"{right_commit}^{{commit}}")
    left_ref_commit = _validate_commit_reachable(left.repo_path, left_ref, left_locked, "left")
    right_ref_commit = _validate_commit_reachable(right.repo_path, right_ref, right_locked, "right")
    cache_base = Path(cache_root)
    if not cache_base.is_absolute():
        cache_base = ROOT / cache_base
    writer = write_fingerprint_cache if include_ast else write_blob_fingerprint_cache
    left_cache = writer(left.repo_path, left_locked, left.work_id, left.display_name, cache_base)
    right_cache = writer(right.repo_path, right_locked, right.work_id, right.display_name, cache_base)
    if output_path is None:
        pair_dir = cache_base / "comparisons" / f"{_safe_name(left.work_id)}--{_safe_name(right.work_id)}"
        suffix = "ast" if include_ast else "blob"
        scope_payload = {
            "left_include": sorted(set(left_include_prefixes or [])),
            "right_include": sorted(set(right_include_prefixes or [])),
            "left_exclude": sorted(set(left_exclude_prefixes or [])),
            "right_exclude": sorted(set(right_exclude_prefixes or [])),
        }
        scope_digest = hashlib.sha256(
            json.dumps(scope_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:10]
        out = pair_dir / f"{left_locked[:12]}--{right_locked[:12]}-{suffix}-{scope_digest}.json"
    else:
        out = Path(output_path)
        if not out.is_absolute():
            out = ROOT / out
    return compare_fingerprint_caches(
        left_cache,
        right_cache,
        out,
        include_ast=include_ast,
        left_ref=left_ref,
        left_ref_commit=left_ref_commit,
        right_ref=right_ref,
        right_ref_commit=right_ref_commit,
        left_include_prefixes=left_include_prefixes or [],
        right_include_prefixes=right_include_prefixes or [],
        left_exclude_prefixes=left_exclude_prefixes or [],
        right_exclude_prefixes=right_exclude_prefixes or [],
    )


def search_history_blobs(
    target_work_id: str,
    target_commit: str,
    *,
    works_path: str | Path = "config/works.yaml",
    cache_root: str | Path = "fp_cache",
    top_k: int = 30,
    target_prefixes: list[str] | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Recall all repositories containing blobs from one selected commit."""
    target = find_work(target_work_id, works_path)
    report = ValidationReport()
    if target is None:
        report.add("identity.unknown_work", f"work_id not found in {works_path}: {target_work_id}")
        report.raise_for_errors()
    assert target is not None
    validate_work_identity(target).raise_for_errors()
    locked = git_text(target.repo_path, "rev-parse", f"{target_commit}^{{commit}}")
    cache_base = Path(cache_root)
    if not cache_base.is_absolute():
        cache_base = ROOT / cache_base
    target_cache = write_blob_fingerprint_cache(target.repo_path, locked, target.work_id, target.display_name, cache_base)

    candidates = []
    for work in load_works(works_path):
        validate_work_identity(work).raise_for_errors()
        candidates.append(
            {
                "work_id": work.work_id,
                "display_name": work.display_name,
                "year": work.year,
                "repository_type": work.repository_type,
                "reference_kind": work.reference_kind,
                "module_ids": work.module_ids,
                "repo_path": str(work.repo_path),
                "review_ref": work.review_branch,
                "review_commit": git_text(work.repo_path, "rev-parse", work.review_branch),
            }
        )
    if output_path is None:
        out = cache_base / "history_searches" / _safe_name(target.work_id) / f"{locked}.json"
    else:
        out = Path(output_path)
        if not out.is_absolute():
            out = ROOT / out
    return search_historical_blob_objects(
        target_cache,
        candidates,
        out,
        top_k=top_k,
        target_prefixes=target_prefixes or [],
    )


def _validate_commit_reachable(repo: Path, ref: str, commit: str, side: str) -> str:
    ref = ref.strip()
    if not ref:
        raise ValueError(f"{side} ref is required")
    ref_commit = git_text(repo, "rev-parse", f"{ref}^{{commit}}")
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, ref_commit],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 1:
        raise ValueError(f"{side} commit {commit} is not reachable from ref {ref}")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"cannot verify {side} ref {ref}")
    return ref_commit


def build_evidence(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    _load_manifest(root)
    evidence_path = root / "evidence.jsonl"
    evidence_path.touch(exist_ok=True)
    return evidence_path


def _load_manifest(case_dir: Path) -> dict:
    path = case_dir / "case_state" / "manifest.json"
    if not path.exists():
        report = ValidationReport()
        report.add("case.manifest_missing", "run init before this stage", path)
        report.raise_for_errors()
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)

def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "work"
