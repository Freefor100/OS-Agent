from __future__ import annotations

import os
import re
from typing import Optional

from core.agent_graph_state import EvidenceRecord


_DECLARATION_HINT_RE = re.compile(r"\b(trait|typedef|struct\s+\w+\s*;|extern\s+|fn\s+\w+\s*\([^)]*\)\s*;)")


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


def verify_evidence(record: EvidenceRecord, *, repo_path: str) -> EvidenceRecord:
    score = 0.0
    path = record.path or ""
    abs_path = _repo_abs(repo_path, path) if path else ""
    path_exists = bool(path and os.path.exists(abs_path))
    if path_exists:
        score += 0.30
    if record.line_start and record.line_end and record.line_start <= record.line_end:
        score += 0.15
    if (record.excerpt or "").strip():
        score += 0.20
    if record.source_type == "source_code":
        score += 0.15
    if (record.tool_name or "").startswith("lsp_"):
        score += 0.10
    if record.tool_name == "read_code_segment" or record.metadata.get("read_confirmed"):
        score += 0.10

    text = (record.excerpt or "") + "\n" + (record.notes or "")
    negative_search = bool(
        record.evidence_type in {"search", "semantic_search"}
        and ("未找到匹配" in text or "no matches" in text.lower() or "no results" in text.lower())
        and ("已搜索" in text or "searched" in text.lower())
    )
    if negative_search:
        # A repository-wide negative search is valid evidence for "not_found"
        # claims even when there is no single source path to cite.
        score += 0.35
    if "confidence=low" in text or "Generic Fallback" in text or "ASM Fallback" in text:
        score -= 0.25
    if text.lstrip().startswith("Error:") or "无法生成调用图" in text or "未出现，无法生成" in text:
        score -= 0.35
    if record.source_type in {"documentation", "readme"} and record.metadata.get("supports_implementation_claim"):
        score -= 0.30
    if _DECLARATION_HINT_RE.search(record.excerpt or "") and record.metadata.get("supports_implementation_claim"):
        score -= 0.40
    if (not path_exists and not negative_search) or not (record.excerpt or "").strip():
        score -= 0.50

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
    record.verifier_score = round(score, 2)
    record.confidence = confidence
    record.validity = validity
    return record
