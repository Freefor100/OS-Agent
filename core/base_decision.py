from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from core.evidence import stable_id
from core.snapshot import RepoSnapshot

URL_RE = re.compile(r"https?://(?:github\.com|gitlab\.eduxiji\.net)/[^\s)\]>]+", re.I)


def declared_sources(snapshot: RepoSnapshot) -> list[dict[str, Any]]:
    root = Path(snapshot.materialized_path)
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not (path.name.lower().startswith("readme") or path.suffix.lower() in {".md", ".txt"}):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in URL_RE.finditer(text):
            url = match.group(0).rstrip(".,;，。；")
            line = text[:match.start()].count("\n") + 1
            rows.setdefault(url, {"url": url, "repo_hint": url.rstrip("/").split("/")[-1].removesuffix(".git"),
                                  "path": path.relative_to(root).as_posix(), "line": line})
    return list(rows.values())


def build_base_evidence_packet(target_snapshot: RepoSnapshot, formal_candidates: Iterable[dict[str, Any]], *, target_year: int = 0,
                               include_declarations: bool = True, candidate_coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    candidates = []
    for row in formal_candidates:
        item = dict(row)
        year = int(item.get("year") or 0)
        item["year_direction"] = "older_to_target" if year and target_year and year < target_year else "same_year" if year == target_year and year else "newer_or_unknown"
        item["eligible_primary_base"] = item.get("score_kind") == "formal" and item["year_direction"] == "older_to_target"
        candidates.append(item)
    payload = {"target_snapshot": target_snapshot.to_dict(), "target_year": target_year, "formal_candidates": candidates,
               "declared_sources": declared_sources(target_snapshot) if include_declarations else [], "declarations_hidden": not include_declarations,
               "candidate_coverage": candidate_coverage or {"coverage_complete": False, "reason": "candidate coverage not supplied"}}
    payload["packet_id"] = stable_id("basepkt", payload, 16)
    return payload


def validate_base_decision(decision: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    primary = decision.get("primary_base") or {}
    if not (packet.get("candidate_coverage") or {}).get("coverage_complete"):
        errors.append("BaseDecision rejected: rough-recall Top-K candidate coverage is incomplete")
    no_base = bool(decision.get("no_reliable_base"))
    matches = [c for c in packet.get("formal_candidates", []) if c.get("repo") == primary.get("repo") and c.get("commit") == primary.get("commit")]
    if no_base:
        if primary:
            errors.append("no_reliable_base cannot coexist with primary_base")
        if any(c.get("eligible_primary_base") and float(c.get("combined") or 0) >= 0.3 for c in packet.get("formal_candidates", [])):
            errors.append("independent mode rejected: a reliable formal older candidate exists")
        if packet.get("declared_sources") and not decision.get("declared_sources_checked"):
            errors.append("independent mode rejected: declared sources were not checked")
        return errors
    if not primary:
        return ["primary_base is required unless no_reliable_base is true"]
    if not matches:
        errors.append("primary_base must reference a formal candidate by repo and commit")
    else:
        candidate = matches[0]
        if candidate.get("score_kind") != "formal" or candidate.get("scope_status") != "verified":
            errors.append("primary_base candidate is not a verified formal result")
        if candidate.get("year_direction") == "same_year":
            errors.append("same-year candidate cannot be a directional primary Base")
        rank = (decision.get("decision_factors") or {}).get("formal_rank")
        if rank is not None and rank != candidate.get("rank"):
            errors.append("decision formal_rank does not match candidate rank")
    if not decision.get("evidence_ids"):
        errors.append("BaseDecision requires evidence_ids")
    return errors
