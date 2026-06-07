from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "v1"
TERMINOLOGY_PROFILE_DEFAULT = "stallings_en_zh"

# tri_state_impl 的 JSON 取值（校验用英文）；渲染 Markdown 时改为中文表述
_TRI_STATE_IMPL_MARKDOWN_ZH: Dict[str, str] = {
    "implemented": "已实现",
    "stub": "桩实现",
    "not_found": "未发现",
    "unknown": "证据不足/未知",
}

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
                "required": ["question_id", "question_type", "stem", "fact_answers", "value"],
                "properties": {
                    "question_id": {"type": "string"},
                    "question_type": {
                        "type": "string",
                        "enum": ["fill_in", "single_choice", "multi_choice", "short_answer", "tri_state_impl"],
                    },
                    "stem": {"type": "string"},
                    "fact_answers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["fact_id", "value", "used_evidence_ids"],
                            "properties": {
                                "fact_id": {"type": "string"},
                                "fact_key": {"type": "string"},
                                "value": {},
                                "used_evidence_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "notes": {"type": "string"},
                            },
                        },
                    },
                    "value": {},
                    "notes": {"type": "string"},
                    "used_evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["evidence_id", "path", "symbol_kind", "symbol_name"],
                            "properties": {
                                "evidence_id": {"type": "string"},
                                "path": {"type": "string"},
                                "symbol_kind": {"type": "string"},
                                "symbol_name": {"type": "string"},
                                "excerpt": {"type": "string"},
                                "line_start": {"type": ["integer", "null"]},
                                "line_end": {"type": ["integer", "null"]},
                                "evidence_type": {"type": "string"},
                                "strength": {"type": "string"},
                                "validity": {"type": "string"},
                                "supports_claim_types": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
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

        aa = ensure_fact_answers_for_question(aa, q)
        aa = ensure_structured_value_for_question(aa, q)

        # Coerce fact_answers[*].value by allowed_values if defined
        facts_by_id = {
            str(f.get("fact_id") or "").strip(): f
            for f in (q.get("structured_facts") or [])
            if isinstance(f, dict)
        }
        if facts_by_id and isinstance(aa.get("fact_answers"), list):
            for fa in aa["fact_answers"]:
                if not isinstance(fa, dict):
                    continue
                fid = str(fa.get("fact_id") or "").strip()
                fact_spec = facts_by_id.get(fid, {})
                fa_choices_raw = fact_spec.get("allowed_values")
                if isinstance(fa_choices_raw, list) and fa_choices_raw:
                    fa_choices = [str(x).strip() for x in fa_choices_raw]
                    fa["value"] = _coerce_single_choice_value(fa.get("value"), fa_choices)

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


def _question_map(stage_qa: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    questions = stage_qa.get("questions", []) if isinstance(stage_qa, dict) else []
    if not isinstance(questions, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("question_id") or "").strip()
        if qid:
            out[qid] = q
    return out


def _fact_specs(question: Dict[str, Any]) -> List[Dict[str, Any]]:
    facts = question.get("structured_facts")
    return [f for f in facts if isinstance(f, dict) and _is_str(f.get("fact_id"))] if isinstance(facts, list) else []


def _fact_field_keys(question: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for fact in _fact_specs(question):
        key = str(fact.get("fact_key") or "").strip() or str(fact.get("fact_id") or "").strip()
        if key and key not in out:
            out.append(key)
    return out


def _value_shape_fields(question: Dict[str, Any]) -> List[str]:
    contract = question.get("answer_contract") if isinstance(question.get("answer_contract"), dict) else {}
    shape = contract.get("value_shape")
    if not isinstance(shape, dict) or not shape:
        return []
    return [str(k).strip() for k in shape.keys() if str(k).strip()]


def question_requires_fixed_value_shape(question: Dict[str, Any]) -> bool:
    """Whether `value` must be an object with explicit answer_contract.value_shape keys."""
    qtype = str(question.get("question_type") or "").strip()
    if qtype not in {"short_answer", "fill_in"}:
        return False
    return bool(_value_shape_fields(question))


def default_structured_value_for_question(question: Dict[str, Any]) -> Dict[str, Any]:
    keys = _value_shape_fields(question) or _fact_field_keys(question)
    return {key: "unknown" for key in keys}


def _default_fact_value(fact: Dict[str, Any]) -> Any:
    allowed = fact.get("allowed_values")
    if isinstance(allowed, list):
        values = [str(x).strip() for x in allowed if str(x).strip()]
        if "unknown" in values:
            return "unknown"
        if values:
            return values[-1]
    return "unknown"


def ensure_fact_answers_for_question(answer: Dict[str, Any], question: Dict[str, Any]) -> Dict[str, Any]:
    """Return an answer object with one fact_answers item for every structured fact.

    This is a compatibility guard for fallback paths and older model outputs. Prompted
    model outputs are still expected to provide fact_answers explicitly; validation can
    then check that every required fact was paid for with a local evidence-id list.
    """
    if not isinstance(answer, dict):
        return answer
    facts = _fact_specs(question)
    if not facts:
        answer.setdefault("fact_answers", [])
        return answer

    existing_items = answer.get("fact_answers")
    if not isinstance(existing_items, list):
        existing_items = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in existing_items:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("fact_id") or "").strip()
        if fid:
            by_id[fid] = item

    used_top = answer.get("used_evidence_ids")
    inherited_used = [str(x).strip() for x in used_top if _is_str(x)] if isinstance(used_top, list) else []
    out: List[Dict[str, Any]] = []
    for fact in facts:
        fid = str(fact.get("fact_id") or "").strip()
        item = dict(by_id.get(fid) or {})
        item["fact_id"] = fid
        fact_key = str(fact.get("fact_key") or "").strip()
        if fact_key:
            item.setdefault("fact_key", fact_key)
        if "value" not in item:
            item["value"] = _default_fact_value(fact)
        used = item.get("used_evidence_ids")
        if isinstance(used, list):
            item["used_evidence_ids"] = [str(x).strip() for x in used if _is_str(x)]
        else:
            item["used_evidence_ids"] = list(inherited_used)
        if "notes" in item and not isinstance(item.get("notes"), str):
            item["notes"] = str(item.get("notes") or "")
        out.append(item)
    answer["fact_answers"] = out
    return answer


def ensure_structured_value_for_question(answer: Dict[str, Any], question: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill fixed-field value objects only when answer_contract declares value_shape."""
    if not isinstance(answer, dict):
        return answer
    if not question_requires_fixed_value_shape(question):
        return answer
    expected = _value_shape_fields(question)
    if not expected:
        return answer
    value = answer.get("value")
    if not isinstance(value, dict):
        answer["value"] = default_structured_value_for_question(question)
        return answer
    answer["value"] = {key: value.get(key, "unknown") for key in expected}
    return answer


def coerce_fact_answers_by_stage_qa(payload: Dict[str, Any], *, stage_qa: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill canonical fact_answers shape from the QA bank for safe fallbacks."""
    if not isinstance(payload, dict):
        return payload
    answers = payload.get("answers")
    if not isinstance(answers, list):
        return payload
    qmap = _question_map(stage_qa)
    out = dict(payload)
    new_answers: List[Any] = []
    for a in answers:
        if not isinstance(a, dict):
            new_answers.append(a)
            continue
        qid = str(a.get("question_id") or "").strip()
        q = qmap.get(qid)
        aa = dict(a)
        if q:
            aa = ensure_fact_answers_for_question(aa, q)
            aa = ensure_structured_value_for_question(aa, q)
        else:
            aa.setdefault("fact_answers", [])
        new_answers.append(aa)
    out["answers"] = new_answers
    return out


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
    stage_qa: Optional[Dict[str, Any]] = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    qmap = _question_map(stage_qa)

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

        answer_status = a.get("answer_status")
        if answer_status is not None and answer_status not in {"answered", "fallback_unusable"}:
            issues.append(ValidationIssue(f"{pfx}.answer_status", "must be answered|fallback_unusable if provided"))

        stem = a.get("stem")
        if not _is_str(stem):
            issues.append(ValidationIssue(f"{pfx}.stem", "must be non-empty string"))

        if "value" not in a:
            issues.append(ValidationIssue(f"{pfx}.value", "missing"))
        else:
            val = a.get("value")
            if qtype == "tri_state_impl" and val not in {"implemented", "stub", "not_found", "unknown"}:
                issues.append(ValidationIssue(f"{pfx}.value", "tri_state_impl must be implemented|stub|not_found|unknown"))

        fact_answers = a.get("fact_answers")
        if not isinstance(fact_answers, list):
            issues.append(ValidationIssue(f"{pfx}.fact_answers", "must be an array"))
            fact_answers = []
        fact_ids_seen: List[str] = []
        for j, fa in enumerate(fact_answers):
            fp = f"{pfx}.fact_answers[{j}]"
            if not isinstance(fa, dict):
                issues.append(ValidationIssue(fp, "must be object"))
                continue
            fid = fa.get("fact_id")
            if not _is_str(fid):
                issues.append(ValidationIssue(f"{fp}.fact_id", "must be non-empty string"))
            else:
                fact_ids_seen.append(str(fid).strip())
            if "value" not in fa:
                issues.append(ValidationIssue(f"{fp}.value", "missing"))
            f_used = fa.get("used_evidence_ids")
            if not isinstance(f_used, list):
                issues.append(ValidationIssue(f"{fp}.used_evidence_ids", "must be an array"))
            elif any(not _is_str(x) for x in f_used):
                issues.append(ValidationIssue(f"{fp}.used_evidence_ids", "must contain non-empty strings"))
            if "fact_key" in fa and not isinstance(fa.get("fact_key"), str):
                issues.append(ValidationIssue(f"{fp}.fact_key", "must be string if provided"))
            if "notes" in fa and not isinstance(fa.get("notes"), str):
                issues.append(ValidationIssue(f"{fp}.notes", "must be string if provided"))

        if _is_str(qid) and qid.strip() in qmap:
            q = qmap[qid.strip()]
            fact_specs = _fact_specs(q)
            expected_fact_ids = [str(f.get("fact_id") or "").strip() for f in fact_specs if _is_str(f.get("fact_id"))]
            missing_facts = [fid for fid in expected_fact_ids if fid not in fact_ids_seen]
            extra_facts = [fid for fid in fact_ids_seen if fid not in expected_fact_ids]
            if missing_facts:
                issues.append(ValidationIssue(f"{pfx}.fact_answers", f"missing fact_id(s): {missing_facts[:12]}"))
            if extra_facts:
                issues.append(ValidationIssue(f"{pfx}.fact_answers", f"unexpected fact_id(s): {extra_facts[:12]}"))
            if len(fact_ids_seen) != len(set(fact_ids_seen)):
                issues.append(ValidationIssue(f"{pfx}.fact_answers", "duplicate fact_id(s)"))
            if question_requires_fixed_value_shape(q):
                expected_fields = _value_shape_fields(q)
                if expected_fields:
                    value = a.get("value")
                    if not isinstance(value, dict):
                        issues.append(ValidationIssue(f"{pfx}.value", "short_answer/fill_in value must be object keyed by answer_contract.value_shape"))
                    else:
                        got_fields = [str(k).strip() for k in value.keys()]
                        missing_fields = [key for key in expected_fields if key not in got_fields]
                        extra_fields = [key for key in got_fields if key not in expected_fields]
                        if missing_fields:
                            issues.append(ValidationIssue(f"{pfx}.value", f"missing fixed field(s): {missing_fields[:12]}"))
                        if extra_fields:
                            issues.append(ValidationIssue(f"{pfx}.value", f"unexpected fixed field(s): {extra_fields[:12]}"))
            by_fact = {str(f.get("fact_id") or "").strip(): f for f in fact_specs}
            for j, fa in enumerate(fact_answers):
                if not isinstance(fa, dict):
                    continue
                fid = str(fa.get("fact_id") or "").strip()
                spec = by_fact.get(fid)
                if not spec:
                    continue
                allowed = spec.get("allowed_values")
                if isinstance(allowed, list) and allowed:
                    allowed_values = {str(x).strip() for x in allowed if str(x).strip()}
                    if allowed_values and str(fa.get("value") or "").strip() not in allowed_values:
                        issues.append(
                            ValidationIssue(
                                f"{pfx}.fact_answers[{j}].value",
                                f"must be one of question structured_facts allowed_values for {fid}",
                            )
                        )

        evidence = a.get("evidence", [])
        if not isinstance(evidence, list):
            issues.append(ValidationIssue(f"{pfx}.evidence", "must be an array"))
            continue

        used = a.get("used_evidence_ids", [])
        if used is not None and not isinstance(used, list):
            issues.append(ValidationIssue(f"{pfx}.used_evidence_ids", "must be an array if provided"))
        elif isinstance(used, list) and any(not _is_str(x) for x in used):
            issues.append(ValidationIssue(f"{pfx}.used_evidence_ids", "must contain non-empty strings"))

        for j, ev in enumerate(evidence):
            ep = f"{pfx}.evidence[{j}]"
            if not isinstance(ev, dict):
                issues.append(ValidationIssue(ep, "must be object"))
                continue
            if not _is_str(ev.get("evidence_id")):
                issues.append(ValidationIssue(f"{ep}.evidence_id", "must be non-empty string"))
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


def _format_answer_value_for_markdown(value: Any, *, question_type: Optional[str] = None) -> str:
    """渲染答案正文：字符串原样输出，其余类型 JSON（紧凑）。

    ``tri_state_impl`` 的枚举值在 md 中译为中文，与 JSON 内英文取值并存（校验仍以英文为准）。
    """
    if isinstance(value, str):
        s = (value or "").strip()
        if (question_type or "").strip() == "tri_state_impl" and s in _TRI_STATE_IMPL_MARKDOWN_ZH:
            return _TRI_STATE_IMPL_MARKDOWN_ZH[s]
        return s
    return json.dumps(value, ensure_ascii=False)


def _format_fact_answers_for_markdown(
    fact_answers: Any,
    evidence_list: Optional[List[Dict[str, Any]]] = None,
    desc_map: Optional[Dict[str, str]] = None
) -> List[str]:
    if not isinstance(fact_answers, list) or not fact_answers:
        return []

    desc_map = desc_map or {}

    lines = ["", "| 子问题 (fact_key) | 考核项描述 | 结论 (value) | 备注说明 |", "|---|---|---|---|"]
    for item in fact_answers:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("fact_id") or "").strip()
        fkey = str(item.get("fact_key") or "").strip()
        name = fkey if fkey else fid
        
        desc = desc_map.get(fid, "-")
        
        value = item.get("value")
        value_text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        
        value_zh = {
            "yes_strong": "✅ 强支撑 (yes_strong)",
            "yes_weak": "⚠️ 弱支撑 (yes_weak)",
            "no": "❌ 无/未实现 (no)",
            "unknown": "❓ 未知 (unknown)",
            "implemented": "✅ 已实现 (implemented)",
            "stub": "⚠️ 存根/空函数 (stub)",
            "not_found": "❌ 未发现 (not_found)",
        }.get(value_text, value_text)
        
        notes = str(item.get("notes") or "").strip()
        for ch in ("\n", "\r"):
            value_zh = value_zh.replace(ch, " ")
            notes = notes.replace(ch, " ")
            desc = desc.replace(ch, " ")
        notes = notes.replace("|", "\\|")
        desc = desc.replace("|", "\\|")
            
        lines.append(f"| **{name}** | {desc} | {value_zh} | {notes} |")
    return lines if len(lines) > 2 else []


def render_answers_to_markdown(payload: Dict[str, Any], stage_qa: Optional[Dict[str, Any]] = None) -> str:
    """将题库 JSON 答案渲染为章节内 Markdown（无 meta 头、无证据表、无「题干/答案」列表项）。"""
    answers = payload.get("answers", [])
    
    fact_desc_map: Dict[str, Dict[str, str]] = {}
    if stage_qa and isinstance(stage_qa.get("questions"), list):
        for q in stage_qa["questions"]:
            if not isinstance(q, dict): continue
            qid = str(q.get("question_id") or "").strip()
            fact_desc_map[qid] = {}
            for sf in q.get("structured_facts", []) if isinstance(q.get("structured_facts"), list) else []:
                if not isinstance(sf, dict): continue
                fid = str(sf.get("fact_id") or "").strip()
                fdesc = str(sf.get("question") or "").strip()
                if fid and fdesc:
                    fact_desc_map[qid][fid] = fdesc

    lines: List[str] = []
    for a in answers if isinstance(answers, list) else []:
        if not isinstance(a, dict):
            continue
        qid = str(a.get("question_id", "")).strip()
        stem = str(a.get("stem", "")).strip()
        qtype = str(a.get("question_type", "")).strip()
        value = a.get("value")
        notes = (a.get("notes") or "").strip() if isinstance(a.get("notes"), str) else ""

        if stem:
            lines.append(f"### {qid} {stem}")
        else:
            lines.append(f"### {qid}")
        lines.append("")
        lines.extend(_format_fact_answers_for_markdown(
            a.get("fact_answers"),
            evidence_list=a.get("evidence"),
            desc_map=fact_desc_map.get(qid, {})
        ))

        if isinstance(a.get("fact_answers"), list) and a.get("fact_answers"):
            lines.append("")
            lines.append("汇总结论：")
            lines.append("")
        lines.append(_format_answer_value_for_markdown(value, question_type=qtype))
        if notes:
            lines.append("")
            lines.append(notes)
        lines.append("")


    return "\n".join(lines).strip() + "\n"
