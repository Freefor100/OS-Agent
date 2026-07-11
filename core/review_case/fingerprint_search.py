from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def search_fingerprint_cache(
    target_manifest_path: Path,
    index_path: Path,
    output_path: Path,
    *,
    top_k: int = 30,
) -> Path:
    target_manifest = _load(target_manifest_path)
    target_work_id = str(target_manifest["work_id"])
    target_cache = _resolve_cache_path(str(target_manifest["cache_dir"]), target_manifest_path)
    target_blob, target_units = _fingerprints(target_cache)
    rows: list[dict[str, Any]] = []

    for item in _load(index_path).get("items", []):
        if str(item.get("work_id", "")) == target_work_id:
            continue
        candidate_cache = _resolve_cache_path(str(item.get("cache_dir", "")), index_path)
        if not candidate_cache.is_dir():
            continue
        candidate_blob, candidate_units = _fingerprints(candidate_cache)
        blob = _containment(target_blob, candidate_blob)
        target_ast = {str(unit.get("shape", "")) for unit in target_units if unit.get("shape")}
        candidate_ast = {str(unit.get("shape", "")) for unit in candidate_units if unit.get("shape")}
        ast = _containment(target_ast, candidate_ast)
        rows.append(
            {
                "work_id": item.get("work_id", ""),
                "display_name": item.get("display_name", ""),
                "commit": item.get("commit", ""),
                "blob_containment": blob,
                "ast_containment": ast,
                "combined": round(max(blob["balanced"], ast["balanced"]), 6),
                "overlap_by_target_directory": _overlap_by_directory(target_units, candidate_ast),
            }
        )

    rows.sort(key=lambda row: (-float(row["combined"]), str(row["display_name"]), str(row["commit"])))
    payload = {
        "schema": "review_case.search_candidates.v2",
        "target_work_id": target_work_id,
        "target_commit": target_manifest.get("commit", ""),
        "score_notice": "Candidate retrieval only. Scores do not decide Base, originality, plagiarism, or direction.",
        "candidates": rows[:top_k],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _fingerprints(cache_dir: Path) -> tuple[set[str], list[dict[str, Any]]]:
    blob_doc = _load(cache_dir / "target_blob.json")
    ast_doc = _load(cache_dir / "target_ast.json")
    blobs = {str(row.get("blob", "")) for row in blob_doc.get("files", []) if row.get("blob")}
    return blobs, list(ast_doc.get("units", []))


def _containment(left: set[str], right: set[str]) -> dict[str, Any]:
    shared = len(left & right)
    left_ratio = shared / len(left) if left else 0.0
    right_ratio = shared / len(right) if right else 0.0
    return {
        "shared": shared,
        "target_total": len(left),
        "candidate_total": len(right),
        "target_containment": round(left_ratio, 6),
        "candidate_containment": round(right_ratio, 6),
        "balanced": round(min(left_ratio, right_ratio), 6),
    }


def _overlap_by_directory(target_units: list[dict[str, Any]], candidate_shapes: set[str]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"shared": 0, "target": 0})
    for unit in target_units:
        shape = str(unit.get("shape", ""))
        if not shape:
            continue
        directory = str(Path(str(unit.get("path", ""))).parent)
        if directory == ".":
            directory = "(root)"
        counts[directory]["target"] += 1
        if shape in candidate_shapes:
            counts[directory]["shared"] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1]["shared"], item[0])))


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
