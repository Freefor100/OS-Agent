from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

from core.agent_graph_state import EvidenceRecord
from core.qa_contract import HINT_EVIDENCE_TYPES, STRONG_EVIDENCE_TYPES


_DECLARATION_HINT_RE = re.compile(r"\b(trait|typedef|struct\s+\w+\s*;|extern\s+|fn\s+\w+\s*\([^)]*\)\s*;)")
_STUB_HINT_RE = re.compile(
    r"\b(todo!|unimplemented!|panic!\s*\(|ENOSYS|ENOTSUP|unsupported|return\s+0\s*;|return\s+-1\s*;|Ok\s*\(\s*0\s*\))",
    re.IGNORECASE,
)


def _repo_abs(repo_path: str, evidence_path: str) -> str:
    if os.path.isabs(evidence_path):
        return evidence_path
    norm_repo = os.path.normpath(repo_path)
    norm_ev = os.path.normpath(evidence_path)
    repo_name = os.path.basename(norm_repo)
    parts = norm_ev.split(os.sep)
    if len(parts) >= 2 and parts[0] == "repos" and parts[1] == repo_name:
        return norm_ev
    if norm_ev == repo_name or norm_ev.startswith(repo_name + os.sep):
        return os.path.join(os.path.dirname(norm_repo), norm_ev)
    return os.path.join(norm_repo, norm_ev)


def _read_lines(abs_path: str, line_start: Optional[int], line_end: Optional[int]) -> str:
    if not line_start or not line_end or line_start <= 0 or line_end < line_start:
        return ""
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return ""
    if line_start > len(lines):
        return ""
    return "".join(lines[line_start - 1 : min(line_end, len(lines))])


def _excerpt_matches_file(record: EvidenceRecord, abs_path: str) -> bool:
    excerpt = (record.excerpt or "").strip()
    if not excerpt or not os.path.isfile(abs_path):
        return False
    window = _read_lines(abs_path, record.line_start, record.line_end)
    if not window:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                window = f.read(200000)
        except Exception:
            return False
    compact_excerpt = re.sub(r"\s+", " ", excerpt[:500]).strip()
    compact_window = re.sub(r"\s+", " ", window).strip()
    if compact_excerpt and compact_excerpt in compact_window:
        return True
    # Short snippets often include tool decorations; accept a dense 80-char core match.
    core = compact_excerpt[:160]
    return bool(len(core) >= 40 and core in compact_window)


def _looks_like_negative_search(text: str) -> bool:
    low = (text or "").lower()
    return (
        (
            "未找到匹配" in text
            or "未发现" in text
            or "无匹配" in text
            or "无结果" in text
            or "no matches" in low
            or "no results" in low
            or "not found" in low
        )
        and ("已搜索" in text or "搜索" in text or "searched" in low)
    )


def _parse_negative_search_metadata(record: EvidenceRecord) -> Dict[str, Any]:
    metadata = dict(record.metadata or {})
    neg = metadata.get("negative_search") if isinstance(metadata.get("negative_search"), dict) else {}
    text = (record.excerpt or "") + "\n" + (record.notes or "")
    if not neg and isinstance(metadata.get("negative_search_coverage"), dict):
        neg = metadata.get("negative_search_coverage") or {}
    if not neg and metadata.get("negative_search_structured"):
        neg = {
            "keywords": metadata.get("keywords") or metadata.get("searched_keywords") or [],
            "searched_directories": metadata.get("seed_paths") or metadata.get("searched_directories") or [],
            "coverage_sufficient": bool(metadata.get("coverage_sufficient", True)),
            "match_count": metadata.get("match_count", 0),
            "file_count": metadata.get("file_count"),
        }
    if not neg and _looks_like_negative_search(text):
        neg = {
            "keywords": metadata.get("keywords") or metadata.get("query_keywords") or [],
            "searched_directories": metadata.get("seed_paths") or metadata.get("searched_directories") or [],
            "coverage_scope": "repository" if ("全仓" in text or "repository" in text.lower()) else "unknown",
            "match_count": 0,
            "file_count": metadata.get("file_count"),
        }
    return neg if isinstance(neg, dict) else {}


def _coverage_ratio(observed: Iterable[Any], required: Iterable[Any]) -> float:
    req = {str(x).strip().lower() for x in required if str(x).strip()}
    if not req:
        return 1.0
    obs = {str(x).strip().lower() for x in observed if str(x).strip()}
    if not obs:
        return 0.0
    covered = sum(1 for item in req if item in obs or any(item in x or x in item for x in obs))
    return covered / max(1, len(req))


def _negative_search_covers_policy(record: EvidenceRecord, policy: Optional[Dict[str, Any]]) -> bool:
    neg = _parse_negative_search_metadata(record)
    if not neg:
        return False
    if neg.get("coverage_sufficient") is True:
        return True
    policy = policy or {}
    required_keywords = policy.get("keywords") if isinstance(policy.get("keywords"), list) else []
    required_dirs = policy.get("seed_paths") if isinstance(policy.get("seed_paths"), list) else []
    min_kw = float(policy.get("minimum_keyword_coverage", 0.0) or 0.0)
    min_dir = float(policy.get("minimum_directory_coverage", 0.0) or 0.0)
    observed_keywords = neg.get("keywords") if isinstance(neg.get("keywords"), list) else []
    if not observed_keywords and isinstance(neg.get("searched_keywords"), list):
        observed_keywords = neg.get("searched_keywords") or []
    observed_dirs = neg.get("searched_directories") if isinstance(neg.get("searched_directories"), list) else []
    return _coverage_ratio(observed_keywords, required_keywords) >= min_kw and _coverage_ratio(observed_dirs, required_dirs) >= min_dir


def verify_evidence(
    record: EvidenceRecord,
    *,
    repo_path: str,
    required_evidence_types: Optional[List[str]] = None,
    negative_search_policy: Optional[Dict[str, Any]] = None,
) -> EvidenceRecord:
    score = 0.0
    path = record.path or ""
    abs_path = _repo_abs(repo_path, path) if path else ""
    path_exists = bool(path and os.path.exists(abs_path))
    line_readable = bool(path_exists and _read_lines(abs_path, record.line_start, record.line_end))
    excerpt_nonempty = bool((record.excerpt or "").strip())
    excerpt_matches = bool(path_exists and excerpt_nonempty and _excerpt_matches_file(record, abs_path))

    evidence_type = (record.evidence_type or "search").strip()
    tool_name = (record.tool_name or "").strip()
    required_evidence_types = required_evidence_types or []
    parsed_negative_search = _parse_negative_search_metadata(record)
    synthetic_negative_search = bool(parsed_negative_search.get("synthetic") or record.metadata.get("synthesized_from_structured_fact_results"))
    negative_search = bool(parsed_negative_search) or _looks_like_negative_search((record.excerpt or "") + "\n" + (record.notes or ""))
    negative_search_structured = negative_search and not synthetic_negative_search and _negative_search_covers_policy(record, negative_search_policy)

    if path_exists:
        score += 0.25
    if line_readable:
        score += 0.15
    if excerpt_nonempty:
        score += 0.15
    if excerpt_matches:
        score += 0.20
    if record.source_type == "source_code":
        score += 0.10
    if tool_name.startswith("lsp_"):
        score += 0.10
    if tool_name == "read_code_segment" or record.metadata.get("read_confirmed"):
        score += 0.15
    if evidence_type in STRONG_EVIDENCE_TYPES:
        score += 0.10
    if evidence_type in HINT_EVIDENCE_TYPES or tool_name in {"rag_search_code", "grep_in_repo"}:
        score -= 0.10
    if required_evidence_types and evidence_type not in set(required_evidence_types):
        if not (negative_search_structured and "negative_search" in set(required_evidence_types)):
            score -= 0.20
    if negative_search:
        score += 0.15
    if negative_search_structured:
        score += 0.30

    text = (record.excerpt or "") + "\n" + (record.notes or "")
    if "confidence=low" in text or "Generic Fallback" in text or "ASM Fallback" in text:
        score -= 0.25
    if text.lstrip().startswith("Error:") or "无法生成调用图" in text or "未出现，无法生成" in text:
        score -= 0.35
    if record.source_type in {"documentation", "readme"} and record.metadata.get("supports_implementation_claim"):
        score -= 0.30
    declaration_only = bool(_DECLARATION_HINT_RE.search(record.excerpt or ""))
    stub_like = bool(_STUB_HINT_RE.search(record.excerpt or ""))
    if declaration_only and record.metadata.get("supports_implementation_claim"):
        score -= 0.40
    if (not path_exists and not negative_search) or not excerpt_nonempty:
        score -= 0.50
    if path_exists and record.line_start and record.line_end and not line_readable:
        score -= 0.35
    if path_exists and excerpt_nonempty and not excerpt_matches and not negative_search:
        score -= 0.35

    score = max(0.0, min(1.0, score))
    if score >= 0.80:
        confidence = "high"
        validity = "valid"
    elif score >= 0.50:
        confidence = "medium"
        validity = "valid"
    elif score >= 0.20:
        confidence = "low"
        validity = "weak"
    else:
        confidence = "low"
        validity = "invalid"

    strength = "invalid"
    supports: List[str] = []
    if validity != "invalid":
        if negative_search_structured:
            strength = "strong"
            supports.append("not_found")
        elif negative_search:
            strength = "weak"
        elif evidence_type in HINT_EVIDENCE_TYPES or tool_name in {"rag_search_code", "grep_in_repo"}:
            strength = "hint"
        elif (evidence_type in STRONG_EVIDENCE_TYPES or tool_name.startswith("lsp_") or tool_name == "read_code_segment") and (
            excerpt_matches or record.metadata.get("read_confirmed") or tool_name.startswith("lsp_")
        ):
            strength = "strong"
            supports.append("stub" if stub_like or declaration_only else "implemented")
        else:
            strength = "weak"
    if stub_like or declaration_only:
        if "implemented" in supports:
            supports.remove("implemented")
        if validity != "invalid" and "stub" not in supports:
            supports.append("stub")

    record.verifier_score = round(score, 2)
    record.confidence = confidence
    record.validity = validity
    record.strength = strength
    record.supports_claim_types = supports
    record.metadata = dict(record.metadata or {})
    record.metadata.update(
        {
            "path_exists": path_exists,
            "line_readable": line_readable,
            "excerpt_matches_file": excerpt_matches,
            "negative_search": parsed_negative_search if negative_search else {},
            "negative_search_synthetic": synthetic_negative_search,
            "negative_search_structured": negative_search_structured,
            "can_support_implemented": "implemented" in supports,
        }
    )
    return record
