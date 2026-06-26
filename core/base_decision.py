from __future__ import annotations

import re
from typing import Any, Iterable

from core.evidence import stable_id
from core.git_source import list_tree, read_text
from core.snapshot import RepoSnapshot

URL_RE = re.compile(r"https?://(?:github\.com|gitlab\.eduxiji\.net)/[^\s)\]>]+", re.I)


def declared_sources(snapshot: RepoSnapshot) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for entry in list_tree(snapshot.repo_path, snapshot.commit):
        name = entry.path.rsplit("/", 1)[-1]
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if entry.kind != "blob" or not (name.lower().startswith("readme") or suffix in {".md", ".txt"}):
            continue
        try:
            text = read_text(snapshot.repo_path, snapshot.commit, entry.path)
        except Exception:
            continue
        for match in URL_RE.finditer(text):
            url = match.group(0).rstrip(".,;，。；")
            line = text[:match.start()].count("\n") + 1
            rows.setdefault(url, {"url": url, "repo_hint": url.rstrip("/").split("/")[-1].removesuffix(".git"),
                                  "path": entry.path, "line": line})
    return list(rows.values())


def build_base_evidence_packet(target_snapshot: RepoSnapshot, formal_candidates: Iterable[dict[str, Any]], *, target_year: int = 0,
                               include_declarations: bool = True, candidate_coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    candidates = []
    for row in formal_candidates:
        item = dict(row)
        year = int(item.get("year") or 0)
        if year and target_year:
            if year < target_year:
                direction = "older_to_target"
            elif year == target_year:
                direction = "same_year"
            else:
                direction = "newer_to_target"
        elif item.get("is_framework"):
            direction = "external_reference_unknown_year"
        else:
            direction = "unknown_year"
        item["year_direction"] = direction
        item["eligible_primary_base"] = item.get("score_kind") == "formal" and item["year_direction"] == "older_to_target"
        candidates.append(item)
    coverage = candidate_coverage or _infer_candidate_coverage(candidates)
    payload = {"target_snapshot": target_snapshot.to_dict(), "target_year": target_year, "formal_candidates": candidates,
               "declared_sources": declared_sources(target_snapshot) if include_declarations else [], "declarations_hidden": not include_declarations,
               "candidate_coverage": coverage}
    payload["packet_id"] = stable_id("basepkt", payload, 16)
    return payload


def validate_base_decision(decision: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    primary = decision.get("primary_base") or {}
    if not (packet.get("candidate_coverage") or {}).get("coverage_complete"):
        errors.append("BaseDecision rejected: rough-recall Top-K candidate coverage is incomplete")
    no_base = bool(decision.get("no_reliable_base"))
    matches, match_errors = _candidate_matches(primary, packet.get("formal_candidates", []))
    errors.extend(match_errors)
    if no_base:
        if primary:
            errors.append("no_reliable_base cannot coexist with primary_base")
        if any(c.get("eligible_primary_base") and _score_value(c.get("combined")) >= 0.3 for c in packet.get("formal_candidates", [])):
            errors.append("independent mode rejected: a reliable formal older candidate exists")
        if packet.get("declared_sources") and not decision.get("declared_sources_checked"):
            errors.append("independent mode rejected: declared sources were not checked")
        return errors
    if not primary:
        return ["primary_base is required unless no_reliable_base is true"]
    if not matches:
        errors.append("primary_base must reference a formal candidate by repo and commit; candidates=" + _candidate_summary(packet.get("formal_candidates", [])))
    else:
        candidate = matches[0]
        if candidate.get("score_kind") != "formal" or candidate.get("scope_status") != "verified":
            errors.append(
                "primary_base candidate is not a verified formal result; "
                f"required score_kind=formal scope_status=verified; selected rank={candidate.get('rank')} "
                f"repo={candidate.get('repo')} commit={candidate.get('commit')} "
                f"score_kind={candidate.get('score_kind')} scope_status={candidate.get('scope_status')}"
            )
        rank = (decision.get("decision_factors") or {}).get("formal_rank")
        if rank is not None and rank != candidate.get("rank"):
            errors.append("decision formal_rank does not match candidate rank")
    if not decision.get("evidence_ids"):
        errors.append("BaseDecision requires evidence_ids")
    return errors


def resolve_primary_candidate(decision: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any] | None:
    """Return the formal candidate selected by primary_base after prefix matching."""
    primary = decision.get("primary_base") or {}
    matches, errors = _candidate_matches(primary, packet.get("formal_candidates", []))
    return None if errors or not matches else matches[0]


def _candidate_matches(primary: dict[str, Any], candidates: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    repo = str(primary.get("repo") or "")
    commit = str(primary.get("commit") or "")
    if not repo or not commit:
        return [], []
    rows = [c for c in candidates if str(c.get("repo") or "") == repo]
    matches = [c for c in rows if _commit_matches(commit, str(c.get("commit") or ""))]
    if len(matches) > 1:
        return [], [f"primary_base commit prefix is ambiguous for repo {repo}: {', '.join(str(c.get('commit')) for c in matches)}"]
    return matches, []


def _infer_candidate_coverage(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    verified_formal = [c for c in candidates if c.get("score_kind") == "formal" and c.get("scope_status") == "verified"]
    return {
        "coverage_complete": bool(candidates) and len(verified_formal) == len(candidates),
        "source": "formal_candidates",
        "reason": "inferred from supplied formal_candidates",
        "returned_candidate_count": len(candidates),
        "verified_formal_count": len(verified_formal),
    }


def _score_value(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("score") if "score" in value else value.get("combined")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _commit_matches(requested: str, candidate: str) -> bool:
    if not requested or not candidate:
        return False
    return candidate == requested or candidate.startswith(requested) or requested.startswith(candidate)


def _candidate_summary(candidates: Iterable[dict[str, Any]]) -> str:
    parts = []
    for row in candidates:
        parts.append(
            f"rank={row.get('rank')} repo={row.get('repo')} commit={row.get('commit')} "
            f"score_kind={row.get('score_kind')} scope_status={row.get('scope_status')}"
        )
    return "[" + "; ".join(parts[:20]) + (f"; ... total={len(parts)}" if len(parts) > 20 else "") + "]"
