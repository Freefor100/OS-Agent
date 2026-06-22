from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core.evidence import stable_id
from core.snapshot import RepoSnapshot


SCOPE_ROOT = Path(".fp_cache") / "scopes"
SCOPE_SCHEMA = "scope_manifest_v1"


@dataclass
class ScopeExclusion:
    prefix: str
    category: str
    reason: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class ScopeManifest:
    scope_id: str
    snapshot_id: str
    repo: str
    commit: str
    included_prefixes: list[str]
    excluded: list[ScopeExclusion]
    generated_prefixes: list[str]
    documentation_prefixes: list[str]
    status: str
    schema_version: str = SCOPE_SCHEMA

    @property
    def excluded_prefixes(self) -> list[str]:
        return [row.prefix for row in self.excluded]

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["excluded_prefixes"] = self.excluded_prefixes
        return row


def build_scope_manifest(
    snapshot: RepoSnapshot,
    *,
    included_prefixes: Iterable[str] | None = None,
    excluded: Iterable[dict[str, Any] | ScopeExclusion] | None = None,
    generated_prefixes: Iterable[str] | None = None,
    documentation_prefixes: Iterable[str] | None = None,
    status: str = "verified",
) -> ScopeManifest:
    root = Path(snapshot.materialized_path)
    auto_excluded = _submodule_exclusions(root)
    supplied = [_coerce_exclusion(x) for x in (excluded or [])]
    exclusions = _dedupe_exclusions([*auto_excluded, *supplied])
    generated = _normalize_prefixes(generated_prefixes or ["target/", "build/", "dist/"])
    documentation = _normalize_prefixes(documentation_prefixes or ["doc/", "docs/"])
    included = _normalize_prefixes(included_prefixes or _default_includes(root, exclusions, generated, documentation))
    _validate_paths(root, included, exclusions)
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "included": included,
        "excluded": [asdict(x) for x in exclusions],
        "generated": generated,
        "documentation": documentation,
        "status": status,
        "schema": SCOPE_SCHEMA,
    }
    return ScopeManifest(
        scope_id=stable_id("scope", payload, 16),
        snapshot_id=snapshot.snapshot_id,
        repo=snapshot.repo,
        commit=snapshot.commit,
        included_prefixes=included,
        excluded=exclusions,
        generated_prefixes=generated,
        documentation_prefixes=documentation,
        status=status,
    )


def save_scope_manifest(manifest: ScopeManifest) -> str:
    SCOPE_ROOT.mkdir(parents=True, exist_ok=True)
    path = SCOPE_ROOT / f"{manifest.repo}__{manifest.commit[:16]}.json"
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def verified_exclusion_errors(manifest: ScopeManifest, evidence_records: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Validate Agent-selected exclusions for a verified ScopeManifest.

    Automatically detected submodules are accepted without Agent evidence because
    the `.gitmodules` declaration is verified by the scope builder itself. Any
    other verified exclusion needs at least one EvidenceRecord id; when records
    are supplied, every referenced id must exist and be verified.
    """
    if manifest.status != "verified":
        return []
    errors: list[str] = []
    records = evidence_records or {}
    for row in manifest.excluded:
        auto_submodule = row.category == "external_submodule" and row.reason == "declared git submodule"
        if auto_submodule:
            continue
        if not row.evidence_ids:
            errors.append(f"verified scope exclusion {row.prefix} requires evidence_ids")
            continue
        if evidence_records is None:
            continue
        for evidence_id in row.evidence_ids:
            record = records.get(evidence_id)
            if not record:
                errors.append(f"verified scope exclusion {row.prefix} references missing evidence {evidence_id}")
            elif not record.get("verified"):
                errors.append(f"verified scope exclusion {row.prefix} references unverified evidence {evidence_id}")
    return errors


def load_scope_manifest(repo: str, commit: str) -> ScopeManifest | None:
    path = SCOPE_ROOT / f"{repo}__{commit[:16]}.json"
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ScopeManifest(
        scope_id=raw["scope_id"],
        snapshot_id=raw["snapshot_id"],
        repo=raw["repo"],
        commit=raw["commit"],
        included_prefixes=list(raw.get("included_prefixes") or []),
        excluded=[_coerce_exclusion(x) for x in raw.get("excluded") or []],
        generated_prefixes=list(raw.get("generated_prefixes") or []),
        documentation_prefixes=list(raw.get("documentation_prefixes") or []),
        status=raw.get("status", "unverified"),
        schema_version=raw.get("schema_version", SCOPE_SCHEMA),
    )


def path_in_scope(path: str, manifest: ScopeManifest | None) -> bool:
    if manifest is None:
        return True
    rel = _normalize_prefix(path, directory=False)
    excluded = [*manifest.excluded_prefixes, *manifest.generated_prefixes, *manifest.documentation_prefixes]
    if any(_matches(rel, prefix) for prefix in excluded):
        return False
    return not manifest.included_prefixes or any(_matches(rel, prefix) for prefix in manifest.included_prefixes)


def filter_units(units: Iterable[dict[str, Any]], manifest: ScopeManifest | None) -> list[dict[str, Any]]:
    return [unit for unit in units if path_in_scope(str(unit.get("file") or ""), manifest)]


def _submodule_exclusions(root: Path) -> list[ScopeExclusion]:
    path = root / ".gitmodules"
    if not path.is_file():
        return []
    rows: list[ScopeExclusion] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == "path":
            rows.append(ScopeExclusion(
                prefix=_normalize_prefix(value.strip()),
                category="external_submodule",
                reason="declared git submodule",
            ))
    return rows


def _default_includes(
    root: Path,
    excluded: list[ScopeExclusion],
    generated: list[str],
    documentation: list[str],
) -> list[str]:
    blocked = [x.prefix for x in excluded] + generated + documentation
    rows = []
    for path in sorted(root.iterdir()):
        if path.name.startswith(".") or not path.is_dir():
            continue
        prefix = _normalize_prefix(path.name)
        if not any(_matches(prefix, x) for x in blocked):
            rows.append(prefix)
    return rows


def _validate_paths(root: Path, included: list[str], excluded: list[ScopeExclusion]) -> None:
    missing = [p for p in included if not (root / p.rstrip("/")).exists()]
    if missing:
        raise ValueError(f"scope paths do not exist in snapshot: {sorted(set(missing))}")


def _coerce_exclusion(row: dict[str, Any] | ScopeExclusion) -> ScopeExclusion:
    if isinstance(row, ScopeExclusion):
        return ScopeExclusion(_normalize_prefix(row.prefix), row.category, row.reason, list(row.evidence_ids))
    return ScopeExclusion(
        prefix=_normalize_prefix(str(row.get("prefix") or "")),
        category=str(row.get("category") or "agent_excluded"),
        reason=str(row.get("reason") or "excluded by agent"),
        evidence_ids=list(row.get("evidence_ids") or []),
    )


def _dedupe_exclusions(rows: list[ScopeExclusion]) -> list[ScopeExclusion]:
    out: dict[str, ScopeExclusion] = {}
    for row in rows:
        if not row.prefix:
            continue
        old = out.get(row.prefix)
        if old is None:
            out[row.prefix] = row
            continue
        old.evidence_ids = sorted(set(old.evidence_ids) | set(row.evidence_ids))
        if row.reason and row.reason != old.reason:
            old.reason = f"{old.reason}; {row.reason}"
        if old.category == "external_submodule" and row.category:
            old.category = row.category
    return [out[key] for key in sorted(out)]


def _normalize_prefixes(rows: Iterable[str]) -> list[str]:
    return sorted(set(_normalize_prefix(x) for x in rows if str(x).strip()))


def _normalize_prefix(value: str, *, directory: bool = True) -> str:
    value = str(value).replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    value = value.strip("/")
    return f"{value}/" if value and directory else value


def _matches(path: str, prefix: str) -> bool:
    clean = prefix.rstrip("/")
    return path == clean or path.startswith(f"{clean}/")
