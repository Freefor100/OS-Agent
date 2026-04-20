"""
Describe 阶段无工具 LLM Review（仅 JSON-QA 且校验成功后）。

输入：A）题库题单 `core/describe_stage_qa/<stage_id>.json`；B）`coerce_answers_payload_by_stage_qa` **之前**
的解析后 JSON（与磁盘 `answers.json` 可能不同：后者含题库覆写）。

不包含工具摘录；不覆盖 `01_overview` / `10_history`（由调用方跳过）。

侧车：`_per_stage/<stage_id>_review.json`（含 `question_reviews` 逐题 `review`+`confidence`、`confidence` 总置信度、`summary_zh`）；环境变量 `DESCRIBE_STAGE_REVIEW=1` 开启。审计范围仅限题面/契约/证据自洽，不评价参赛 OS 设计优劣。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from core.agent_builder import DESCRIBE_REVIEW_SYSTEM_PROMPT, build_chat_model, get_model_name

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE)


def build_stage_qa_question_sheet(stage_id: str, stage_title: str) -> str:
    """仅来自 describe_stage_qa 题库 JSON 的题单（不含模型答案、不含工具）。"""
    from core.describe_stage_qa import load_stage_qa

    stage_qa = load_stage_qa(stage_id)
    lines = [
        f"## 题库文件\n`core/describe_stage_qa/{stage_id}.json`\n\n",
        f"**stage_id**: `{stage_id}`  \n**stage_title**: {stage_title}\n\n",
        "## 题单（顺序与题库 `questions[]` 一致）\n\n",
    ]
    questions = stage_qa.get("questions") if isinstance(stage_qa, dict) else None
    if not isinstance(questions, list) or not questions:
        lines.append("_（本题库文件无题目）_\n")
        return "".join(lines)

    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("question_id", "")).strip()
        qtype = str(q.get("question_type", "")).strip()
        stem = str(q.get("stem", "")).strip()
        if not qid:
            continue
        lines.append(f"### {qid}（{qtype}）\n\n{stem}\n\n")
        choices = q.get("choices")
        if isinstance(choices, list) and choices:
            lines.append("**choices**:\n")
            for i, c in enumerate(choices[:12]):
                label = chr(ord("A") + i) if i < 26 else str(i)
                lines.append(f"- {label}. {str(c).strip()}\n")
            if len(choices) > 12:
                lines.append(f"- …（共 {len(choices)} 项）\n")
            lines.append("\n")
    return "".join(lines)


def parse_review_llm_output(content: str) -> Dict[str, Any]:
    raw = (content or "").strip()
    if not raw:
        raise ValueError("empty review model output")
    m = _JSON_FENCE_RE.search(raw)
    if m:
        raw = m.group(1).strip()
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        if start < 0:
            raise
        decoder = json.JSONDecoder()
        out, _end = decoder.raw_decode(raw, start)
    if not isinstance(out, dict):
        raise TypeError(f"review JSON root must be object, got {type(out).__name__}")
    return out


def _normalize_one_question_review(item: Any) -> Optional[Tuple[str, Any, str]]:
    if not isinstance(item, dict):
        return None
    qid = str(item.get("question_id", "")).strip()
    if not qid:
        return None
    conf = item.get("confidence")
    rev = str(item.get("review", "") or item.get("review_zh", "")).strip()
    return (qid, conf, rev)


def coerce_review_payload(
    data: Dict[str, Any],
    *,
    stage_id: str,
    stage_title: str,
    expected_question_ids: List[str],
) -> Dict[str, Any]:
    dims_in = data.get("dimensions") if isinstance(data.get("dimensions"), dict) else {}

    raw_list = data.get("question_reviews")
    if not isinstance(raw_list, list):
        raw_list = data.get("per_question_reviews") or data.get("questions_review") or []

    by_id: Dict[str, Tuple[Any, str]] = {}
    for item in raw_list:
        parsed = _normalize_one_question_review(item)
        if not parsed:
            continue
        qid, conf, rev = parsed
        by_id[qid] = (conf, rev)

    question_reviews: List[Dict[str, Any]] = []
    for qid in expected_question_ids:
        if qid in by_id:
            conf, rev = by_id[qid]
            question_reviews.append(
                {
                    "question_id": qid,
                    "confidence": conf,
                    "review": rev if rev else "（审计输出中本题为空白评审）",
                }
            )
        else:
            question_reviews.append(
                {
                    "question_id": qid,
                    "confidence": None,
                    "review": "（审计 JSON 未包含本题；视为输出不完整）",
                }
            )

    return {
        "schema_version": str(data.get("schema_version") or "describe_review_v1"),
        "stage_id": str(data.get("stage_id") or stage_id),
        "stage_title": str(data.get("stage_title") or stage_title),
        "confidence": data.get("confidence"),
        "question_reviews": question_reviews,
        "dimensions": {
            "evidence_supports_answers": dims_in.get("evidence_supports_answers"),
            "question_answer_consistency": dims_in.get("question_answer_consistency"),
            "requirements_fit": dims_in.get("requirements_fit"),
        },
        "findings": data.get("findings") if isinstance(data.get("findings"), list) else [],
        "summary_zh": str(data.get("summary_zh") or ""),
    }


def run_describe_stage_review(
    *,
    stage_id: str,
    stage_title: str,
    question_sheet: str,
    model_json_before_stage_qa_coerce: str,
    expected_question_ids: List[str],
) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """
    无工具单次 invoke。材料 A=题单，B=覆写前 JSON 字符串。
    """
    id_line = ", ".join(expected_question_ids) if expected_question_ids else "(无)"
    user_parts = [
        "# 材料 A：题库题单（仅 describe_stage_qa JSON，不含模型输出）\n\n",
        question_sheet.strip(),
        "\n\n# 须逐题评审的 question_id 列表（顺序即输出 `question_reviews` 顺序，不得遗漏）\n\n",
        id_line,
        "\n\n# 材料 B：模型答案 JSON（**已通过解析与 defaults 处理**，且为 **`coerce_answers_payload_by_stage_qa` 覆写题面之前** 的快照；证据仅看本 JSON 内 `answers[].evidence`）\n\n",
        "```json\n",
        (model_json_before_stage_qa_coerce or "").strip(),
        "\n```\n\n",
        "请根据以上两份材料：**对列表中每一题**写出 `review` 与本题 `confidence`，并给出全阶段 `confidence` 与 `summary_zh` 总评。"
        " **仅**核对题面↔答案、JSON 契约、`evidence`↔`value`；**勿**评价参赛 OS 的设计好坏；`findings` 默认 `[]`。"
        " 输出**唯一一个**符合系统说明 JSON 模式的对象（可用 ```json 围栏）。\n",
    ]
    user_text = "".join(user_parts)
    if len(user_text) > 200_000:
        user_text = user_text[:190_000] + "\n\n...[user bundle hard truncated at 200k chars]...\n"

    model = os.environ.get("DESCRIBE_REVIEW_MODEL") or get_model_name()
    llm = build_chat_model(model=model, temperature=0, max_retries=0)
    msg = llm.invoke(
        [
            SystemMessage(content=DESCRIBE_REVIEW_SYSTEM_PROMPT),
            HumanMessage(content=user_text),
        ]
    )
    raw_text = (getattr(msg, "content", None) or "").strip()
    try:
        parsed = parse_review_llm_output(raw_text)
        coerced = coerce_review_payload(
            parsed,
            stage_id=stage_id,
            stage_title=stage_title,
            expected_question_ids=list(expected_question_ids),
        )
        return coerced, raw_text, None
    except Exception as e:
        logger.warning("Describe review JSON parse failed: %s", e)
        return None, raw_text, f"{type(e).__name__}: {e}"


def describe_stage_review_enabled() -> bool:
    v = (os.environ.get("DESCRIBE_STAGE_REVIEW") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def describe_stage_review_applies(stage_id: str, *, expected_question_ids: list) -> bool:
    """JSON-QA 阶段且非 01/10 概览与历史章。"""
    if stage_id in ("01_overview", "10_history"):
        return False
    return bool(expected_question_ids)
