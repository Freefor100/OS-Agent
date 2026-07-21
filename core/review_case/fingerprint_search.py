from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Hashable, Iterable


def search_fingerprint_cache(
    target_manifest_path: Path,
    candidate_caches: Iterable[dict[str, Any]],
    output_path: Path,
    *,
    top_k: int = 30,
) -> Path:
    """Recall candidate HEAD snapshots; never decide Base or direction."""
    target_manifest = _load(target_manifest_path)
    target_work_id = str(target_manifest["work_id"])
    target_cache = _resolve_cache_path(str(target_manifest["cache_dir"]), target_manifest_path)
    target_blobs, target_units = _fingerprints(target_cache, include_ast=True)
    rows: list[dict[str, Any]] = []
    for candidate in candidate_caches:
        candidate_cache = Path(str(candidate["cache_dir"]))
        manifest_path = candidate_cache / "manifest.json"
        if not manifest_path.is_file():
            continue
        item = _load(manifest_path)
        if str(item.get("work_id", "")) == target_work_id:
            continue
        candidate_blobs, candidate_units = _fingerprints(candidate_cache, include_ast=True)
        blob = _blob_overlap(target_blobs, candidate_blobs, include_occurrences=False)
        ast = _ast_overlap(target_units, candidate_units)
        blob_score = float(blob["content_instances"]["balanced"])
        ast_score = float(ast["shape_instances"]["balanced"])
        rows.append(
            {
                "work_id": item.get("work_id", ""),
                "display_name": item.get("display_name", ""),
                "year": candidate.get("year", 0),
                "repository_type": candidate.get("repository_type", "competition"),
                "reference_kind": candidate.get("reference_kind", ""),
                "module_ids": candidate.get("module_ids", []),
                "review_ref": candidate.get("review_ref", ""),
                "review_commit": item.get("commit", ""),
                "commit": item.get("commit", ""),
                "blob_overlap": blob,
                "ast_overlap": ast,
                "combined_recall_score": round(max(blob_score, ast_score), 6),
                "overlap_by_target_directory": _overlap_by_directory(target_units, candidate_units),
            }
        )

    rows.sort(key=lambda row: (-float(row["combined_recall_score"]), str(row["display_name"]), str(row["commit"])))
    payload = {
        "schema": "review_case.search_candidates.v3",
        "target_work_id": target_work_id,
        "target_display_name": target_manifest.get("display_name", ""),
        "target_year": target_manifest.get("year", 0),
        "target_repository_type": target_manifest.get("repository_type", "competition"),
        "target_review_ref": target_manifest.get("review_ref", ""),
        "target_commit": target_manifest.get("commit", ""),
        "score_notice": "HEAD candidate recall only. Scores do not decide Base, originality, plagiarism, or direction.",
        "identity_notice": "Blob and AST matches preserve occurrence counts and full paths; content-only matches are reported separately from path-aligned matches.",
        "candidates": rows[:top_k],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def compare_fingerprint_caches(
    left_cache: Path,
    right_cache: Path,
    output_path: Path,
    *,
    include_ast: bool = False,
    left_ref: str,
    left_ref_commit: str,
    right_ref: str,
    right_ref_commit: str,
    left_include_prefixes: Iterable[str] = (),
    right_include_prefixes: Iterable[str] = (),
    left_exclude_prefixes: Iterable[str] = (),
    right_exclude_prefixes: Iterable[str] = (),
) -> Path:
    """Compare two selected commit snapshots and emit facts, not a judgment."""
    left_manifest = _load(left_cache / "manifest.json")
    right_manifest = _load(right_cache / "manifest.json")
    left_blobs, left_units = _fingerprints(left_cache, include_ast=include_ast)
    right_blobs, right_units = _fingerprints(right_cache, include_ast=include_ast)
    left_scope = _path_scope(left_include_prefixes, left_exclude_prefixes)
    right_scope = _path_scope(right_include_prefixes, right_exclude_prefixes)
    left_blobs = _filter_paths(left_blobs, left_scope)
    right_blobs = _filter_paths(right_blobs, right_scope)
    left_units = _filter_paths(left_units, left_scope)
    right_units = _filter_paths(right_units, right_scope)
    payload = {
        "schema": "review_case.commit_pair.v2",
        "notice": "Commit-pair fingerprint facts only. The Base reviewer must combine these facts with Git parent diffs, common-source subtraction, and repository history.",
        "left": {
            **_snapshot_identity(left_manifest),
            "ref": left_ref,
            "ref_commit": left_ref_commit,
            "compared_blob_instances": len(left_blobs),
            "compared_ast_units": len(left_units),
        },
        "right": {
            **_snapshot_identity(right_manifest),
            "ref": right_ref,
            "ref_commit": right_ref_commit,
            "compared_blob_instances": len(right_blobs),
            "compared_ast_units": len(right_units),
        },
        "path_filters": {"left": left_scope, "right": right_scope},
        "blob_overlap": _blob_overlap(left_blobs, right_blobs, include_occurrences=True),
        "ast_overlap": _ast_overlap(left_units, right_units) if include_ast else None,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def search_historical_blob_objects(
    target_cache: Path,
    candidate_repositories: list[dict[str, Any]],
    output_path: Path,
    *,
    top_k: int = 30,
    target_prefixes: Iterable[str] = (),
) -> Path:
    """Recall repositories whose reachable Git history contains target blobs."""
    target_manifest = _load(target_cache / "manifest.json")
    target_blobs, _ = _fingerprints(target_cache, include_ast=False)
    prefixes = tuple(_clean_prefix(prefix) for prefix in target_prefixes if _clean_prefix(prefix))
    if prefixes:
        target_blobs = [row for row in target_blobs if _under_prefix(str(row["path"]), prefixes)]
    target_counts = Counter(str(row["blob"]) for row in target_blobs)
    target_unique = set(target_counts)
    rows: list[dict[str, Any]] = []
    for candidate in candidate_repositories:
        if str(candidate.get("work_id", "")) == str(target_manifest.get("work_id", "")):
            continue
        present = _reachable_object_subset(Path(str(candidate["repo_path"])), target_unique)
        if not present:
            continue
        shared_instances = sum(target_counts[blob] for blob in present)
        rows.append(
            {
                "work_id": candidate.get("work_id", ""),
                "display_name": candidate.get("display_name", ""),
                "year": candidate.get("year", 0),
                "repository_type": candidate.get("repository_type", "competition"),
                "reference_kind": candidate.get("reference_kind", ""),
                "module_ids": candidate.get("module_ids", []),
                "review_ref": candidate.get("review_ref", ""),
                "review_commit": candidate.get("review_commit", ""),
                "shared_unique_blobs": len(present),
                "target_shared_instances": shared_instances,
                "target_total_instances": sum(target_counts.values()),
                "target_history_containment": round(shared_instances / sum(target_counts.values()), 6) if target_counts else 0.0,
                "matched_target_occurrences": [
                    {"path": str(row["path"]), "blob": str(row["blob"])}
                    for row in target_blobs
                    if str(row["blob"]) in present
                ],
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row["target_history_containment"]),
            -int(row["shared_unique_blobs"]),
            str(row["display_name"]),
        )
    )
    payload = {
        "schema": "review_case.history_blob_candidates.v1",
        "target": _snapshot_identity(target_manifest),
        "target_prefixes": list(prefixes),
        "notice": "Repository recall scans objects reachable from all refs. Configured review_ref is shown only as a representative HEAD and does not limit history search. Presence does not identify the source commit or prove lineage.",
        "next_step": "For shortlisted repositories, use git log --all --find-object=<blob> to locate historical windows, then compare explicit commit pairs.",
        "candidates": rows[:top_k],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _fingerprints(cache_dir: Path, *, include_ast: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blob_doc = _load(cache_dir / "blob.json")
    ast_path = cache_dir / "ast.json"
    ast_doc = _load(ast_path) if include_ast and ast_path.exists() else {}
    blobs = [
        row
        for row in blob_doc.get("occurrences", [])
        if row.get("blob") and row.get("path")
    ]
    return blobs, list(ast_doc.get("units", []))


def _path_scope(include_prefixes: Iterable[str], exclude_prefixes: Iterable[str]) -> dict[str, list[str]]:
    return {
        "include_prefixes": sorted({_clean_prefix(value) for value in include_prefixes if _clean_prefix(value)}),
        "exclude_prefixes": sorted({_clean_prefix(value) for value in exclude_prefixes if _clean_prefix(value)}),
    }


def _filter_paths(rows: list[dict[str, Any]], scope: dict[str, list[str]]) -> list[dict[str, Any]]:
    includes = tuple(scope["include_prefixes"])
    excludes = tuple(scope["exclude_prefixes"])
    selected = []
    for row in rows:
        path = str(row.get("path", ""))
        if includes and not _under_prefix(path, includes):
            continue
        if excludes and _under_prefix(path, excludes):
            continue
        selected.append(row)
    return selected


def _blob_overlap(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    include_occurrences: bool = False,
) -> dict[str, Any]:
    left_content = Counter(str(row["blob"]) for row in left)
    right_content = Counter(str(row["blob"]) for row in right)
    left_path = Counter((str(row["path"]), str(row["blob"])) for row in left)
    right_path = Counter((str(row["path"]), str(row["blob"])) for row in right)
    content = _counter_containment(left_content, right_content)
    path_aligned = _counter_containment(left_path, right_path)
    relocated = max(0, int(content["shared_instances"]) - int(path_aligned["shared_instances"]))
    result = {
        "content_instances": content,
        "path_aligned_instances": path_aligned,
        "relocated_instances": relocated,
        "shared_unique_blobs": len(set(left_content) & set(right_content)),
        "relocated_examples": _relocated_blob_examples(left, right),
    }
    if include_occurrences:
        result["shared_content_occurrences"] = _shared_content_occurrences(left, right, left_content, right_content)
        result["path_aligned_occurrences"] = [
            {"path": path, "blob": blob, "instances": count}
            for (path, blob), count in sorted((left_path & right_path).items())
        ]
        result["left_residual_occurrences"] = _content_residual(left, right)
        result["right_residual_occurrences"] = _content_residual(right, left)
    return result


def _ast_overlap(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    left_shapes = Counter(str(unit["shape"]) for unit in left if unit.get("shape"))
    right_shapes = Counter(str(unit["shape"]) for unit in right if unit.get("shape"))
    left_path_shapes = Counter((str(unit.get("path", "")), str(unit["shape"])) for unit in left if unit.get("shape"))
    right_path_shapes = Counter((str(unit.get("path", "")), str(unit["shape"])) for unit in right if unit.get("shape"))
    shapes = _counter_containment(left_shapes, right_shapes)
    path_aligned = _counter_containment(left_path_shapes, right_path_shapes)
    return {
        "shape_instances": shapes,
        "path_aligned_shape_instances": path_aligned,
        "renamed_or_relocated_instances": max(0, int(shapes["shared_instances"]) - int(path_aligned["shared_instances"])),
        "examples": _ast_examples(left, right),
    }


def _counter_containment(left: Counter[Hashable], right: Counter[Hashable]) -> dict[str, Any]:
    shared = sum((left & right).values())
    left_total = sum(left.values())
    right_total = sum(right.values())
    left_ratio = shared / left_total if left_total else 0.0
    right_ratio = shared / right_total if right_total else 0.0
    return {
        "shared_instances": shared,
        "target_total_instances": left_total,
        "candidate_total_instances": right_total,
        "target_containment": round(left_ratio, 6),
        "candidate_containment": round(right_ratio, 6),
        "balanced": round(min(left_ratio, right_ratio), 6),
    }


def _relocated_blob_examples(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    left_paths = _paths_by_value(left, "blob")
    right_paths = _paths_by_value(right, "blob")
    examples = []
    for blob in sorted(set(left_paths) & set(right_paths)):
        if left_paths[blob] == right_paths[blob]:
            continue
        examples.append({"blob": blob, "left_paths": sorted(left_paths[blob]), "right_paths": sorted(right_paths[blob])})
        if len(examples) == 30:
            break
    return examples


def _paths_by_value(rows: Iterable[dict[str, Any]], value_key: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        value = str(row.get(value_key, ""))
        path = str(row.get("path", ""))
        if value and path:
            result[value].add(path)
    return result


def _shared_content_occurrences(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    left_counts: Counter[str],
    right_counts: Counter[str],
) -> list[dict[str, Any]]:
    left_paths = _paths_by_value(left, "blob")
    right_paths = _paths_by_value(right, "blob")
    return [
        {
            "blob": blob,
            "shared_instances": min(left_counts[blob], right_counts[blob]),
            "left_paths": sorted(left_paths[blob]),
            "right_paths": sorted(right_paths[blob]),
        }
        for blob in sorted(set(left_counts) & set(right_counts))
    ]


def _content_residual(rows: list[dict[str, Any]], other_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda item: (str(item.get("blob", "")), str(item.get("path", ""))))
    exact_available = Counter((str(row.get("path", "")), str(row.get("blob", ""))) for row in other_rows)
    exact_matched: Counter[str] = Counter()
    unmatched: list[dict[str, Any]] = []
    for row in ordered:
        key = (str(row.get("path", "")), str(row.get("blob", "")))
        if exact_available[key] > 0:
            exact_available[key] -= 1
            exact_matched[key[1]] += 1
        else:
            unmatched.append(row)
    other_content = Counter(str(row.get("blob", "")) for row in other_rows)
    relocated_available = other_content - exact_matched
    residual: list[dict[str, Any]] = []
    for row in unmatched:
        blob = str(row.get("blob", ""))
        if relocated_available[blob] > 0:
            relocated_available[blob] -= 1
            continue
        residual.append({"path": str(row.get("path", "")), "blob": blob, "mode": str(row.get("mode", ""))})
    return residual


def _ast_examples(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    left_by_shape: dict[str, list[dict[str, Any]]] = defaultdict(list)
    right_by_shape: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in left:
        if unit.get("shape"):
            left_by_shape[str(unit["shape"])].append(unit)
    for unit in right:
        if unit.get("shape"):
            right_by_shape[str(unit["shape"])].append(unit)
    examples = []
    for shape in sorted(set(left_by_shape) & set(right_by_shape)):
        left_unit = left_by_shape[shape][0]
        right_unit = right_by_shape[shape][0]
        examples.append(
            {
                "shape": shape,
                "left": _unit_identity(left_unit),
                "right": _unit_identity(right_unit),
            }
        )
        if len(examples) == 30:
            break
    return examples


def _unit_identity(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit_id": unit.get("unit_id", ""),
        "path": unit.get("path", ""),
        "symbol": unit.get("symbol", ""),
        "line": unit.get("line", 0),
        "end_line": unit.get("end_line", 0),
    }


def _overlap_by_directory(target_units: list[dict[str, Any]], candidate_units: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    remaining = Counter(str(unit["shape"]) for unit in candidate_units if unit.get("shape"))
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"shared_instances": 0, "target_instances": 0})
    for unit in target_units:
        shape = str(unit.get("shape", ""))
        if not shape:
            continue
        directory = str(Path(str(unit.get("path", ""))).parent)
        if directory == ".":
            directory = "(root)"
        counts[directory]["target_instances"] += 1
        if remaining[shape] > 0:
            counts[directory]["shared_instances"] += 1
            remaining[shape] -= 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1]["shared_instances"], item[0])))


def _snapshot_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_id": manifest.get("work_id", ""),
        "display_name": manifest.get("display_name", ""),
        "commit": manifest.get("commit", ""),
        "source_file_count": manifest.get("source_file_count", 0),
        "structural_unit_count": manifest.get("structural_unit_count", 0),
    }


def _reachable_object_subset(repo: Path, wanted: set[str]) -> set[str]:
    if not wanted:
        return set()
    process = subprocess.Popen(
        ["git", "-C", str(repo), "rev-list", "--objects", "--all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    found: set[str] = set()
    for line in process.stdout:
        object_id = line.partition(" ")[0].strip()
        if object_id in wanted:
            found.add(object_id)
            if found == wanted:
                process.stdout.close()
                process.terminate()
                process.wait(timeout=10)
                return found
    stderr = process.stderr.read() if process.stderr is not None else ""
    return_code = process.wait(timeout=120)
    if return_code:
        raise RuntimeError(stderr.strip() or f"git rev-list --objects --all failed for {repo}")
    return found


def _clean_prefix(value: str) -> str:
    return value.replace("\\", "/").strip().strip("/")


def _under_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    clean = path.replace("\\", "/").strip("/")
    return any(clean == prefix or clean.startswith(prefix + "/") for prefix in prefixes)


def _resolve_cache_path(raw: str, anchor: Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    root = _find_project_root(anchor)
    return root / path


def _find_project_root(anchor: Path) -> Path:
    for parent in [anchor.resolve().parent, *anchor.resolve().parents]:
        if (parent / "config").is_dir() and (parent / "core").is_dir():
            return parent
    return Path.cwd()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
