from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def load_stage_qa(stage_id: str) -> Dict[str, Any]:
    """Load per-stage QA spec from core/describe_stage_qa/<stage_id>.json."""
    here = os.path.dirname(__file__)
    path = os.path.join(here, f"{stage_id}.json")
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"stage qa payload must be object: {path}")
    return payload


def list_question_ids(stage_qa: Dict[str, Any]) -> List[str]:
    questions = stage_qa.get("questions", [])
    if not isinstance(questions, list):
        return []
    out: List[str] = []
    for q in questions:
        if isinstance(q, dict) and isinstance(q.get("question_id"), str) and q["question_id"].strip():
            out.append(q["question_id"].strip())
    return out

