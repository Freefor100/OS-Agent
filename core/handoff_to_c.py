from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from core.agent_graph_state import CDescribeHandoff


def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def emit_handoff_to_c(repo_name: str, repo_output_dir: str) -> Dict[str, Any]:
    sections_dir = os.path.join(repo_output_dir, "sections")
    review_score = _load_json(os.path.join(repo_output_dir, "review_score.json"))
    fingerprint_ready = os.path.isfile(os.path.join(repo_output_dir, "fingerprint.json"))
    evidence_summary: Dict[str, Any] = {"count": 0, "by_stage": {}}
    ev_path = os.path.join(repo_output_dir, "_agent_state", "evidence_store.jsonl")
    if os.path.isfile(ev_path):
        with open(ev_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                stage_id = item.get("stage_id") or "unknown"
                evidence_summary["count"] += 1
                evidence_summary["by_stage"][stage_id] = evidence_summary["by_stage"].get(stage_id, 0) + 1
    normalized_facts: Dict[str, Any] = {}
    for fname in sorted(os.listdir(sections_dir)) if os.path.isdir(sections_dir) else []:
        if fname.endswith(".md"):
            normalized_facts.setdefault("sections", []).append(fname)
    handoff = CDescribeHandoff(
        repo_name=repo_name,
        sections_dir=os.path.abspath(sections_dir),
        fingerprint_ready=fingerprint_ready,
        stage_quality=review_score,
        normalized_facts=normalized_facts,
        evidence_summary=evidence_summary,
        risk_flags=[],
    ).to_dict()
    out_path = os.path.join(repo_output_dir, "handoff_to_c.json")
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(handoff, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)
    return handoff
