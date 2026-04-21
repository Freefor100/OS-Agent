from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "v1"
TERMINOLOGY_PROFILE_DEFAULT = "stallings_en_zh"

JSON_SCHEMA_V1: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "stage_id", "stage_title", "terminology_profile", "answers"],
    "properties": {
        "schema_version": {"type": "string"},
        "stage_id": {"type": "string"},
        "stage_title": {"type": "string"},
        "terminology_profile": {"type": "string"},
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["question_id", "question_type", "stem", "value", "evidence"],
                "properties": {
                    "question_id": {"type": "string"},
                    "question_type": {
                        "type": "string",
                        "enum": ["fill_in", "single_choice", "multi_choice", "short_answer", "tri_state_impl"],
                    },
                    "stem": {"type": "string"},
                    "value": {},
                    "notes": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["path", "symbol_kind", "symbol_name"],
                            "properties": {
                                "path": {"type": "string"},
                                "symbol_kind": {"type": "string"},
                                "symbol_name": {"type": "string"},
                                "excerpt": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}


def build_bailian_response_format_json_schema(*, name: str = "os_agent_describe_v1") -> Dict[str, Any]:
    """Build DashScope/Bailian OpenAI-compatible response_format for json_schema.

    Docs: OpenAI-compatible Chat API supports:
    {"type":"json_schema","json_schema":{"name":..., "schema":..., "strict":true}}
    """
    return {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": name[:64],
                "schema": JSON_SCHEMA_V1,
                "strict": True,
            },
        }
    }


class JSONQASchemaError(ValueError):
    pass


_JSON_FENCE_RE = re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _is_str(x: Any) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _normalize_choice_text(x: str) -> str:
    # Keep it conservative: strip only; do not normalize punctuation to avoid false matches.
    return (x or "").strip()


def _try_decode_letter_choice(value: str) -> Optional[int]:
    v = (value or "").strip()
    if len(v) != 1:
        return None
    ch = v.upper()
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A")
    return None


def _try_decode_numeric_choice(value: str) -> Optional[int]:
    v = (value or "").strip()
    if v.isdigit():
        n = int(v)
        if n >= 1:
            return n - 1
    return None


def _coerce_single_choice_value(value: Any, choices: List[str]) -> Any:
    if not choices:
        return value
    if isinstance(value, str):
        v = _normalize_choice_text(value)
        # Already a full choice text
        if v in choices:
            return v
        # A/B/C/D style
        idx = _try_decode_letter_choice(v)
        if idx is not None and 0 <= idx < len(choices):
            return choices[idx]
        # 1/2/3 style
        idx = _try_decode_numeric_choice(v)
        if idx is not None and 0 <= idx < len(choices):
            return choices[idx]
    return value


def _coerce_multi_choice_value(value: Any, choices: List[str]) -> Any:
    if not choices:
        return value

    # If already list of full texts, keep as-is (after strip) when possible.
    if isinstance(value, list):
        out: List[Any] = []
        for it in value:
            if isinstance(it, str):
                out.append(_coerce_single_choice_value(it, choices))
            else:
                out.append(it)
        # best-effort: if after coercion it's all strings and all in choices, keep them
        return out

    if isinstance(value, str):
        v = value.strip()
        # Common patterns: "A,C", "A C", "A;C", "A|C"
        parts = [p for p in re.split(r"[,\s;|/]+", v) if p]
        if parts:
            out = []
            for p in parts:
                out.append(_coerce_single_choice_value(p, choices))
            return out
    return value


def coerce_answers_payload_by_stage_qa(payload: Dict[str, Any], *, stage_qa: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort fixups using the stage QA bank.

    - Backfill `stem` to exactly match the QA bank (prevents constraint drift).
    - Map single_choice/multi_choice value from A/B/C/D or 1/2/3 to actual choice texts.
    """
    if not isinstance(payload, dict):
        return payload
    questions = stage_qa.get("questions", []) if isinstance(stage_qa, dict) else []
    if not isinstance(questions, list) or not questions:
        return payload

    qmap: Dict[str, Dict[str, Any]] = {}
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("question_id", "")).strip()
        if qid:
            qmap[qid] = q

    answers = payload.get("answers")
    if not isinstance(answers, list):
        return payload

    out = dict(payload)
    new_answers: List[Any] = []
    for a in answers:
        if not isinstance(a, dict):
            new_answers.append(a)
            continue
        qid = str(a.get("question_id", "")).strip()
        q = qmap.get(qid)
        if not q:
            new_answers.append(a)
            continue

        qtype = str(q.get("question_type", "")).strip()
        stem = str(q.get("stem", "")).strip()
        choices_raw = q.get("choices")
        choices = [str(x).strip() for x in choices_raw] if isinstance(choices_raw, list) else []

        aa = dict(a)
        # Backfill the canonical stem (exact match to bank).
        if stem:
            aa["stem"] = stem

        # Coerce choice values
        if qtype == "single_choice":
            aa["value"] = _coerce_single_choice_value(aa.get("value"), choices)
        elif qtype == "multi_choice":
            aa["value"] = _coerce_multi_choice_value(aa.get("value"), choices)

        new_answers.append(aa)

    out["answers"] = new_answers
    return out


def _find_balanced_json_object(text: str) -> Optional[str]:
    """Find first balanced JSON object substring in text.

    This is a tolerant extractor: it does not require the message to be pure JSON.
    """
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None

    in_string = False
    escaped = False
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_text(raw_text: str) -> str:
    """Extract JSON text from an LLM message (supports ```json fences or inline JSON)."""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise JSONQASchemaError("empty_response")

    m = _JSON_FENCE_RE.search(raw_text)
    if m:
        candidate = (m.group(1) or "").strip()
        if candidate:
            return candidate

    candidate = _find_balanced_json_object(raw_text)
    if candidate:
        return candidate.strip()

    raise JSONQASchemaError("no_json_object_found")


def parse_answers_json(raw_text: str) -> Dict[str, Any]:
    """Parse JSON answers payload from raw model output."""
    json_text = extract_json_text(raw_text)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise JSONQASchemaError(f"json_decode_error: {e}") from e
    if not isinstance(payload, dict):
        raise JSONQASchemaError("payload_not_object")
    return payload


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    reason: str


def validate_answers_payload(
    payload: Dict[str, Any],
    *,
    stage_id: str,
    stage_title: str,
    expected_question_ids: Sequence[str],
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    schema_version = payload.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        issues.append(ValidationIssue("schema_version", f"must be {SCHEMA_VERSION!r}"))

    if payload.get("stage_id") != stage_id:
        issues.append(ValidationIssue("stage_id", f"must be {stage_id!r}"))
    if payload.get("stage_title") != stage_title:
        issues.append(ValidationIssue("stage_title", f"must be {stage_title!r}"))

    tp = payload.get("terminology_profile")
    if tp is None:
        # allow omitted, will be defaulted by caller
        pass
    elif not _is_str(tp):
        issues.append(ValidationIssue("terminology_profile", "must be non-empty string"))

    answers = payload.get("answers")
    if not isinstance(answers, list):
        issues.append(ValidationIssue("answers", "must be an array"))
        return issues

    seen_ids: List[str] = []
    for idx, a in enumerate(answers):
        pfx = f"answers[{idx}]"
        if not isinstance(a, dict):
            issues.append(ValidationIssue(pfx, "must be object"))
            continue

        qid = a.get("question_id")
        if not _is_str(qid):
            issues.append(ValidationIssue(f"{pfx}.question_id", "must be non-empty string"))
        else:
            seen_ids.append(qid.strip())

        qtype = a.get("question_type")
        if qtype not in {
            "fill_in",
            "single_choice",
            "multi_choice",
            "short_answer",
            "tri_state_impl",
        }:
            issues.append(ValidationIssue(f"{pfx}.question_type", "invalid question_type"))

        stem = a.get("stem")
        if not _is_str(stem):
            issues.append(ValidationIssue(f"{pfx}.stem", "must be non-empty string"))

        if "value" not in a:
            issues.append(ValidationIssue(f"{pfx}.value", "missing"))
        else:
            val = a.get("value")
            if qtype == "tri_state_impl" and val not in {"implemented", "stub", "not_found"}:
                issues.append(ValidationIssue(f"{pfx}.value", "tri_state_impl must be implemented|stub|not_found"))

        evidence = a.get("evidence", [])
        if not isinstance(evidence, list):
            issues.append(ValidationIssue(f"{pfx}.evidence", "must be an array"))
            continue

        for j, ev in enumerate(evidence):
            ep = f"{pfx}.evidence[{j}]"
            if not isinstance(ev, dict):
                issues.append(ValidationIssue(ep, "must be object"))
                continue
            if not _is_str(ev.get("path")):
                issues.append(ValidationIssue(f"{ep}.path", "must be non-empty string (repo-relative path)"))
            if not _is_str(ev.get("symbol_name")):
                issues.append(ValidationIssue(f"{ep}.symbol_name", "must be non-empty string"))
            sk = ev.get("symbol_kind")
            if sk is not None and not _is_str(sk):
                issues.append(ValidationIssue(f"{ep}.symbol_kind", "must be string if provided"))
            ex = ev.get("excerpt")
            if ex is not None and not _is_str(ex):
                issues.append(ValidationIssue(f"{ep}.excerpt", "must be non-empty string if provided"))

    expected = list(expected_question_ids)
    missing = [qid for qid in expected if qid not in seen_ids]
    extra = [qid for qid in seen_ids if qid not in expected]
    if missing:
        issues.append(ValidationIssue("answers", f"missing question_id(s): {missing[:12]}"))
    if extra:
        issues.append(ValidationIssue("answers", f"unexpected question_id(s): {extra[:12]}"))
    if len(seen_ids) != len(set(seen_ids)):
        issues.append(ValidationIssue("answers", "duplicate question_id(s)"))

    return issues


def coerce_answers_payload_defaults(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    if "terminology_profile" not in out:
        out["terminology_profile"] = TERMINOLOGY_PROFILE_DEFAULT
    return out


def _format_answer_value_for_markdown(value: Any) -> str:
    """渲染答案正文：字符串原样输出，其余类型 JSON（紧凑）。"""
    if isinstance(value, str):
        return (value or "").strip()
    return json.dumps(value, ensure_ascii=False)


def render_answers_to_markdown(payload: Dict[str, Any]) -> str:
    """将题库 JSON 答案渲染为章节内 Markdown（无 meta 头、无证据表、无「题干/答案」列表项）。"""
    answers = payload.get("answers", [])

    lines: List[str] = []
    for a in answers if isinstance(answers, list) else []:
        if not isinstance(a, dict):
            continue
        qid = str(a.get("question_id", "")).strip()
        stem = str(a.get("stem", "")).strip()
        value = a.get("value")
        notes = (a.get("notes") or "").strip() if isinstance(a.get("notes"), str) else ""

        if stem:
            lines.append(f"### {qid} {stem}")
        else:
            lines.append(f"### {qid}")
        lines.append("")
        lines.append(_format_answer_value_for_markdown(value))
        if notes:
            lines.append("")
            lines.append(notes)
        lines.append("")

    return "\n".join(lines).strip() + "\n"

