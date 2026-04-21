from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def load_stage_qa(stage_id: str) -> Dict[str, Any]:
    """Load per-stage QA spec from core/describe_stage_qa/<stage_id>.json.

    若文件不存在，按空题单处理（与 questions: [] 等价），供无小题单阶段使用。
    """
    here = os.path.dirname(__file__)
    path = os.path.join(here, f"{stage_id}.json")
    if not os.path.isfile(path):
        logger.debug("No describe_stage_qa JSON at %s; using empty questions.", path)
        return {"stage_id": stage_id, "stage_title": "", "questions": []}
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

