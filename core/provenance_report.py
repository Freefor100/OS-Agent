from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.comparison_db import (
    base_only_files,
    directory_files,
    file_functions,
    file_sources,
    function_candidates,
    overview,
    resolve_database,
    run_metadata,
    source_file_targets_all,
    source_group,
)

PROVENANCE_SCHEMA = "provenance_report_v1"


def export_provenance(comparison_database: str, output_path: str, *, work_display_name: str = "",
                      reference_display_name: str = "") -> dict[str, Any]:
    database = resolve_database(comparison_database)
    meta = run_metadata(database)
    work_name = work_display_name or _display_name(str(meta["target_snapshot"].get("repo") or "作品"))
    reference_name = reference_display_name or _display_name(str(meta["base_snapshot"].get("repo") or "参考作品"))
    files = []
    for file_row in directory_files(database, limit=1_000_000)["rows"]:
        target_file = file_row["target_file"]
        functions = []
        for row in file_functions(database, target_file, limit=1_000_000)["rows"]:
            target = row.get("target") or {}
            candidates = function_candidates(database, target.get("unit_id") or "", limit=10)["rows"]
            source_pair = source_group(database, row["comparison_id"])
            functions.append({
                **row,
                "candidates": candidates,
                "target_source": source_pair.get("target_source"),
                "candidate_sources": source_pair.get("candidate_sources") or [],
            })
        files.append({
            **file_row,
            "directory": str(Path(target_file).parent),
            "sources": file_sources(database, target_file)["source_files"],
            "functions": functions,
        })
    reverse = [x for x in source_file_targets_all(database) if x.get("target_file_count", 0) > 1]
    report = {
        "schema_version": PROVENANCE_SCHEMA,
        "comparison_run_id": meta["run_id"],
        "work": {"display_name": work_name, "snapshot": meta["target_snapshot"]},
        "reference": {"display_name": reference_name, "snapshot": meta["base_snapshot"]},
        "overview": overview(database),
        "files": files,
        "reference_unmatched_files": base_only_files(database, limit=1_000_000)["rows"],
        "source_split_summary": reverse,
    }
    _atomic_write(Path(output_path), report)
    return {"path": output_path, "files": len(files), "functions": sum(len(x["functions"]) for x in files)}


def validate_provenance(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != PROVENANCE_SCHEMA:
        errors.append(f"schema_version must be {PROVENANCE_SCHEMA}")
    if not (report.get("work") or {}).get("display_name"):
        errors.append("work display_name is required")
    if not (report.get("reference") or {}).get("display_name"):
        errors.append("reference display_name is required")
    for file_row in report.get("files") or []:
        if not file_row.get("target_file"):
            errors.append("provenance file requires target_file")
        for function in file_row.get("functions") or []:
            if not function.get("comparison_id") or not function.get("raw_status"):
                errors.append(f"function in {file_row.get('target_file')} requires comparison_id and raw_status")
    return errors


def load_provenance(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def directory_tree(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in report.get("files") or []:
        grouped[str(row.get("directory") or ".")].append(row)
    return dict(grouped)


def _display_name(repo: str) -> str:
    name = Path(repo).name
    return name.removeprefix("oskernel2023-") or name


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
