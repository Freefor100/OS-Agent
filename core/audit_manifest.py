from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from core.evidence import stable_id


AUDIT_MANIFEST_SCHEMA = "audit_manifest_v1"


def default_artifact_paths(output_dir: str) -> dict[str, str]:
    root = Path(output_dir)
    return {
        "audit_manifest": str(root / "audit_manifest.json"),
        "base_decision": str(root / "base_decision.json"),
        "comparison_database": str(root / "comparison.sqlite"),
        "comparisons_jsonl": str(root / "comparisons.jsonl"),
        "evidence_store": str(root / "evidence_store.jsonl"),
        "report_json": str(root / "report.json"),
        "report_html": str(root / "report.html"),
        "provenance_json": str(root / "provenance.json"),
        "provenance_html": str(root / "provenance.html"),
    }


def create_audit_manifest(target_snapshot: dict[str, Any], output_dir: str, *,
                          artifacts: dict[str, str] | None = None,
                          status: str = "initialized") -> dict[str, Any]:
    paths = default_artifact_paths(output_dir)
    paths.update({k: str(v) for k, v in (artifacts or {}).items() if v})
    manifest = {
        "schema_version": AUDIT_MANIFEST_SCHEMA,
        "audit_id": stable_id("audit", {"target": target_snapshot, "output_dir": str(Path(output_dir).resolve())}, 16),
        "created_at": _now(),
        "updated_at": _now(),
        "status": status,
        "target_snapshot": target_snapshot,
        "artifacts": paths,
        "stages": {
            "snapshot_locked": bool(target_snapshot.get("commit")),
            "target_scope_verified": False,
            "formal_search_complete": False,
            "base_decision_validated": False,
            "comparison_built": False,
            "judge_report_created": False,
            "judge_report_validated": False,
            "judge_report_rendered": False,
            "provenance_exported": False,
            "provenance_rendered": False,
        },
        "notes": [],
    }
    write_manifest(manifest, paths["audit_manifest"])
    return manifest


def load_manifest(path: str) -> dict[str, Any] | None:
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def find_manifest_for(path: str) -> tuple[dict[str, Any] | None, str]:
    p = Path(path)
    directory = p if p.suffix == "" else p.parent
    manifest_path = directory / "audit_manifest.json"
    return load_manifest(str(manifest_path)), str(manifest_path)


def update_manifest(path: str, *, artifacts: dict[str, str] | None = None,
                    stages: dict[str, bool] | None = None,
                    status: str | None = None,
                    notes: list[str] | None = None) -> dict[str, Any] | None:
    manifest = load_manifest(path)
    if manifest is None:
        return None
    manifest.setdefault("artifacts", {}).update({k: str(v) for k, v in (artifacts or {}).items() if v})
    manifest.setdefault("stages", {}).update({k: bool(v) for k, v in (stages or {}).items()})
    if status:
        manifest["status"] = status
    if notes:
        manifest.setdefault("notes", []).extend(notes)
    manifest["updated_at"] = _now()
    write_manifest(manifest, path)
    return manifest


def write_manifest(manifest: dict[str, Any], path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)
    return str(p)


def artifact_status(manifest: dict[str, Any] | None, fallback_dir: str) -> dict[str, Any]:
    artifacts = default_artifact_paths(fallback_dir)
    if manifest:
        artifacts.update(manifest.get("artifacts") or {})
    if artifacts.get("comparison_database") and not Path(artifacts["comparison_database"]).is_file():
        try:
            from core.comparison_db import resolve_database
            artifacts["comparison_database"] = resolve_database(str(artifacts["comparison_database"]))
        except Exception:
            pass
    required = ["base_decision", "comparison_database", "comparisons_jsonl", "evidence_store", "report_json",
                "report_html", "provenance_json", "provenance_html"]
    rows = {name: {"path": path, "exists": Path(path).is_file()} for name, path in artifacts.items()}
    missing = [name for name in required if not rows.get(name, {}).get("exists")]
    return {"artifacts": rows, "missing_artifacts": missing}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
