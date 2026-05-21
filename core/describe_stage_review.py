"""
Describe 阶段无工具 LLM Review（仅 JSON-QA 且校验成功后）。

输入：A）题库题单 `core/describe_stage_qa/<stage_id>.json`；B）`coerce_answers_payload_by_stage_qa` **之前**
的解析后 JSON（与磁盘 `answers.json` 可能不同：后者含题库覆写）。

不包含工具摘录；不覆盖 `01_overview` / `10_history`（由调用方跳过）。

侧车：`_per_stage/<stage_id>_review.json`（含 `question_reviews`、按方案 A 的 `confidence`、`report_quality_score`、`summary_zh`、`_meta.quality`）；`DESCRIBE_STAGE_REVIEW=1` 开启。审计范围限于题面/契约/证据与答案 JSON 的报告质量。文末由 `write_review_score_json` 在输出根目录写 `review_score.json`（02~09 各章 0~100 与总分校验）。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.agent_builder import DESCRIBE_REVIEW_SYSTEM_PROMPT, build_chat_model, get_model_name
from core.utils import llm_message_total_tokens

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
        if q.get("feature_ids") or q.get("evidence_policy") or q.get("tri_state_rule"):
            feature_view = {
                "feature_ids": q.get("feature_ids"),
                "evidence_policy": q.get("evidence_policy"),
                "tri_state_rule": q.get("tri_state_rule"),
                "anti_examples": q.get("anti_examples"),
                "structured_facts": q.get("structured_facts"),
                "answer_contract": q.get("answer_contract"),
            }
            feature_view = {k: v for k, v in feature_view.items() if v is not None}
            lines.append(f"**feature_schema**: {json.dumps(feature_view, ensure_ascii=False, separators=(',', ':'))}\n\n")
        choices = q.get("choices")
        if isinstance(choices, list) and choices:
            lines.append("**choices**（前缀 A/B/C/D 仅为显示标签；答案 `value` 应使用选项原文，不必包含字母前缀）:\n")
            for i, c in enumerate(choices[:12]):
                label = chr(ord("A") + i) if i < 26 else str(i)
                lines.append(f"- {label}. {str(c).strip()}\n")
            if len(choices) > 12:
                lines.append(f"- …（共 {len(choices)} 项）\n")
            lines.append(f"\n**valid value texts**: {json.dumps([str(c).strip() for c in choices], ensure_ascii=False, separators=(',', ':'))}\n")
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


def _normalize_one_question_review(item: Any) -> Optional[Tuple[str, Any, Any, str]]:
    if not isinstance(item, dict):
        return None
    qid = str(item.get("question_id", "")).strip()
    if not qid:
        return None
    se = item.get("score_evidence")
    sc = item.get("score_consistency")
    rev = str(item.get("review", "") or item.get("review_zh", "")).strip()
    return (qid, se, sc, rev)


def coerce_review_payload(
    data: Dict[str, Any],
    *,
    stage_id: str,
    stage_title: str,
    expected_question_ids: List[str],
) -> Dict[str, Any]:
    raw_list = data.get("question_reviews")
    if not isinstance(raw_list, list):
        raw_list = data.get("per_question_reviews") or data.get("questions_review") or []

    by_id: Dict[str, Tuple[Any, Any, str, Dict[str, Any]]] = {}
    for item in raw_list:
        parsed = _normalize_one_question_review(item)
        if not parsed:
            continue
        qid, se, sc, rev = parsed
        fix_hints = item.get("fix_hints") if isinstance(item, dict) and isinstance(item.get("fix_hints"), dict) else {}
        by_id[qid] = (se, sc, rev, fix_hints)

    question_reviews: List[Dict[str, Any]] = []
    for qid in expected_question_ids:
        if qid in by_id:
            se, sc, rev, fix_hints = by_id[qid]
            question_reviews.append(
                {
                    "question_id": qid,
                    "score_evidence": se,
                    "score_consistency": sc,
                    "review": rev if rev else "（审计输出中本题为空白评审）",
                    "fix_hints": fix_hints,
                }
            )
        else:
            question_reviews.append(
                {
                    "question_id": qid,
                    "score_evidence": None,
                    "score_consistency": None,
                    "review": "（审计 JSON 未包含本题；视为输出不完整）",
                }
            )

    return {
        "schema_version": str(data.get("schema_version") or "describe_review_v1"),
        "stage_id": str(data.get("stage_id") or stage_id),
        "stage_title": str(data.get("stage_title") or stage_title),
        "confidence": data.get("confidence"),
        "question_reviews": question_reviews,
        "findings": data.get("findings") if isinstance(data.get("findings"), list) else [],
        "summary_zh": str(data.get("summary_zh") or ""),
    }


# 与 describe_stage_qa 中 02–09 题库对应；用于 review_score.json 全库汇总。
REVIEW_STAGES_02_09: tuple[str, ...] = (
    "02_boot_trap",
    "03_mem_mgmt",
    "04_process_smp",
    "05_fs_drivers",
    "06_sync_ipc",
    "07_security",
    "08_network",
    "09_debug_error",
)


def _load_stage_title_from_qa(stage_id: str) -> str:
    try:
        from core.describe_stage_qa import load_stage_qa

        d = load_stage_qa(stage_id)
        if isinstance(d, dict) and d.get("stage_title"):
            return str(d.get("stage_title"))
    except Exception:
        pass
    return stage_id


def _coerce_float_01(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        v = float(x)
        if 0.0 <= v <= 1.0:
            return v
        if 1.0 < v <= 100.0:
            return v / 100.0
        return None
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        try:
            return _coerce_float_01(float(s))
        except ValueError:
            return None
    return None


def recompute_confidence_scheme_a(
    question_reviews: list,
    *,
    fallback: Any = None,
) -> Optional[float]:
    """全阶段分：各题有数值的 mean_score 的均值，若任一题 <0.7 则不超过 0.75。无数值时回退为 fallback。"""
    confs: list[float] = []
    for item in question_reviews or []:
        if not isinstance(item, dict):
            continue
        se = _coerce_float_01(item.get("score_evidence"))
        sc = _coerce_float_01(item.get("score_consistency"))
        if se is not None and sc is not None:
            confs.append((se + sc) / 2.0)
        elif se is not None:
            confs.append(se)
        elif sc is not None:
            confs.append(sc)
    if not confs:
        return _coerce_float_01(fallback) if fallback is not None else None
    m = sum(confs) / len(confs)
    out = round(m, 2)
    if any(c < 0.7 for c in confs):
        out = min(out, 0.75)
    return out


def enrich_review_with_report_quality(
    review: Dict[str, Any],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """在 LLM 评审后写入 report_quality_score、_meta.quality，并按方案 A 覆盖全阶段 confidence。"""
    qrs = review.get("question_reviews")
    if not isinstance(qrs, list):
        qrs = []
    new_conf = recompute_confidence_scheme_a(qrs, fallback=review.get("confidence"))
    if new_conf is not None:
        review["confidence"] = new_conf

    mean_q = 0.0
    nq = 0
    for item in qrs:
        if not isinstance(item, dict):
            continue
        se = _coerce_float_01(item.get("score_evidence"))
        sc = _coerce_float_01(item.get("score_consistency"))
        if se is not None and sc is not None:
            mean_q += (se + sc) / 2.0
            nq += 1
        elif se is not None:
            mean_q += se
            nq += 1
        elif sc is not None:
            mean_q += sc
            nq += 1
    if nq:
        mean_q = mean_q / nq
    else:
        mq = _coerce_float_01(review.get("confidence"))
        mean_q = mq if mq is not None else 0.0

    # 完全以 LLM 逐题审核的 confidence（结合了题目要求、证据支撑度）为主
    rqs = mean_q
    rqs = max(0.0, min(1.0, float(rqs)))
    rqs = round(rqs, 2)
    review["report_quality_score"] = rqs

    meta: Dict[str, Any] = dict(review.get("_meta")) if isinstance(review.get("_meta"), dict) else {}
    meta["quality"] = {
        "mean_question_confidence": round(mean_q, 4),
    }
    review["_meta"] = meta
    return review


def _review_parse_max_attempts() -> int:
    v = (os.environ.get("DESCRIBE_REVIEW_MAX_ATTEMPTS") or "3").strip()
    try:
        n = int(v)
    except ValueError:
        n = 3
    return max(1, min(8, n))


def _review_max_chars() -> int:
    v = (os.environ.get("DESCRIBE_REVIEW_MAX_CHARS") or "50000").strip().lower().replace("_", "")
    mult = 1
    if v.endswith("k"):
        mult = 1000
        v = v[:-1]
    elif v.endswith("w"):
        mult = 10000
        v = v[:-1]
    try:
        n = int(float(v) * mult)
    except ValueError:
        n = 50_000
    return max(10_000, n)


def run_describe_stage_review(
    *,
    stage_id: str,
    stage_title: str,
    question_sheet: str,
    model_json_before_stage_qa_coerce: str,
    expected_question_ids: List[str],
) -> Tuple[Optional[Dict[str, Any]], str, Optional[str], int]:
    """
    无工具 invoke。材料 A=题单，B=覆写前 JSON 字符串。

    若输出无法 JSON 解析或无法 `coerce_review_payload`，会按 `DESCRIBE_REVIEW_MAX_ATTEMPTS`（默认 3）
    对同一审阅模型**追加修复轮**重试，直至成功或达到上限；失败时返回最后一次原文与错误信息。

    第四项：本阶段 review 的 LLM 调用**累计** total_tokens（与 print_step 同源；未返回则为 0）。
    """
    id_line = ", ".join(expected_question_ids) if expected_question_ids else "(无)"
    question_sheet_text = question_sheet.strip()
    model_json_text = (model_json_before_stage_qa_coerce or "").strip()
    try:
        # 去除模型输出 JSON 的多余空白和缩进以极大节省字符数
        _obj = json.loads(model_json_text)
        if isinstance(_obj, dict) and isinstance(_obj.get("answers"), list):
            for k in ["schema_version", "stage_title", "terminology_profile"]:
                _obj.pop(k, None)
            for ans in _obj["answers"]:
                if not isinstance(ans, dict):
                    continue
                ans.pop("stem", None)
                ans.pop("question_type", None)
                ans.pop("notes", None)
                if isinstance(ans.get("fact_answers"), list):
                    for fa in ans["fact_answers"]:
                        if isinstance(fa, dict):
                            fa.pop("notes", None)
                if isinstance(ans.get("evidence"), list):
                    for ev in ans["evidence"]:
                        if isinstance(ev, dict):
                            for ev_key in ["line_start", "line_end", "evidence_type", "strength", "validity", "supports_claim_types", "symbol_kind"]:
                                ev.pop(ev_key, None)
        model_json_text = json.dumps(_obj, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        pass
    max_user_chars = _review_max_chars()
    fixed_overhead = 3_000 + len(id_line)
    available_chars = max(5_000, max_user_chars - fixed_overhead)
    model_budget = min(len(model_json_text), max(1_000, int(available_chars * 0.65)))
    question_budget = min(len(question_sheet_text), max(1_000, available_chars - model_budget))
    leftover = available_chars - model_budget - question_budget
    if leftover > 0 and len(model_json_text) > model_budget:
        add = min(leftover, len(model_json_text) - model_budget)
        model_budget += add
        leftover -= add
    if leftover > 0 and len(question_sheet_text) > question_budget:
        question_budget += min(leftover, len(question_sheet_text) - question_budget)
    if len(question_sheet_text) > question_budget:
        question_sheet_text = (
            question_sheet_text[: max(0, question_budget - 500)]
            + "\n\n...[question sheet truncated; Material B is preserved]...\n"
        )
    if len(model_json_text) > model_budget:
        model_json_text = (
            model_json_text[: max(0, model_budget - 500)]
            + "\n\n...[model answer JSON truncated; caller should pass compact review payload]...\n"
        )

    user_parts = [
        "# 材料 A：题库题单（仅 describe_stage_qa JSON，不含模型输出）\n\n",
        question_sheet_text,
        "\n\n# 须逐题评审的 question_id 列表（顺序即输出 `question_reviews` 顺序，不得遗漏）\n\n",
        id_line,
        "\n\n# 材料 B：模型答案 JSON（证据仅看本 JSON 内 `answers[].evidence`。注：为精简上下文，传入的 B 已由系统剔除了 stem, notes 等重复或冗余字段，此为正常现象，请勿判定为字段缺失契约违例）\n\n",
        "```json\n",
        model_json_text,
        "\n```\n\n",
        "请根据以上两份材料：**对列表中每一题**写出 `review` 与本题 `confidence`，并给出全阶段 `confidence` 与 `summary_zh` 总评。"
        " **仅**核对题面↔答案、JSON 契约、`evidence`↔`value`；**勿**评价参赛 OS 的设计好坏；`findings` 默认 `[]`。"
        " 输出**唯一一个**符合系统说明 JSON 模式的对象（可用 ```json 围栏）。\n",
    ]
    user_text = "".join(user_parts)
    if len(user_text) > max_user_chars:
        user_text = user_text[: max_user_chars - 1000] + f"\n\n...[user bundle hard truncated at {max_user_chars} chars]...\n"

    model = os.environ.get("DESCRIBE_REVIEW_MODEL") or get_model_name()
    llm = build_chat_model(model=model, temperature=0, max_retries=0)
    max_attempts = _review_parse_max_attempts()
    messages: list = [
        SystemMessage(content=DESCRIBE_REVIEW_SYSTEM_PROMPT),
        HumanMessage(content=user_text),
    ]
    last_err: Optional[str] = None
    raw_text = ""
    review_tokens_total = 0
    for attempt in range(1, max_attempts + 1):
        try:
            from core.utils import safe_llm_invoke
            msg = safe_llm_invoke(llm, messages)
        except Exception as e:
            last_err = f"SafeLLMInvokeError: {type(e).__name__}: {e}"
            logger.warning("Describe review LLM invoke failed attempt %s/%s: %s", attempt, max_attempts, last_err)
            if attempt >= max_attempts:
                return None, "", last_err, review_tokens_total
            continue

        review_tokens_total += llm_message_total_tokens(msg)
        raw_text = (getattr(msg, "content", None) or "").strip()
        try:
            parsed = parse_review_llm_output(raw_text)
            coerced = coerce_review_payload(
                parsed,
                stage_id=stage_id,
                stage_title=stage_title,
                expected_question_ids=list(expected_question_ids),
            )
            if attempt > 1:
                logger.info("Describe review OK on attempt %s/%s", attempt, max_attempts)
            return coerced, raw_text, None, review_tokens_total
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logger.warning("Describe review parse failed attempt %s/%s: %s", attempt, max_attempts, last_err)
            if attempt >= max_attempts:
                return None, raw_text, last_err, review_tokens_total
            tail = (raw_text or "")[-6000:].replace("```", "`\u200b`")
            repair = (
                "你的上一段输出**无法**被解析为合法 JSON，或结构不符合 `describe_review_v1` 要求（必须含全部 question_id 的"
                f" `question_reviews` 等）。\n\n**错误信息**：\n{last_err}\n\n"
                f"**你上一次的完整输出**（可能含多余说明或围栏；请**仅**在本轮修正后重发 JSON）：\n```text\n{tail}\n```\n\n"
                "请**只**重新输出**一个** JSON 对象，字段名与系统说明一致，可用 ```json 围栏。不要写任何其他解释或道歉。"
            )
            messages = list(messages) + [AIMessage(content=raw_text), HumanMessage(content=repair)]
    return None, raw_text, last_err or "unknown", review_tokens_total


def _load_stage_title_from_qa(stage_id: str) -> str:
    try:
        from core.describe_stage_qa import load_stage_qa

        d = load_stage_qa(stage_id)
        if isinstance(d, dict) and d.get("stage_title"):
            return str(d.get("stage_title"))
    except Exception:
        pass
    return stage_id


def write_review_score_json(repo_output_dir: str) -> Dict[str, Any]:
    """汇总 02~09 各章 review，写 `review_score.json`；仅对已存在且可解析的侧车计分。返回与落盘内容一致。"""
    stages_out: list[dict[str, Any]] = []
    scores_100: list[int] = []
    for sid in REVIEW_STAGES_02_09:
        title = _load_stage_title_from_qa(sid)
        path = os.path.join(repo_output_dir, "_per_stage", f"{sid}_review.json")
        if not os.path.isfile(path):
            stages_out.append(
                {
                    "stage_id": sid,
                    "stage_title": title,
                    "score_0_100": None,
                    "status": "missing",
                }
            )
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("read %s: %s", path, e)
            stages_out.append(
                {
                    "stage_id": sid,
                    "stage_title": title,
                    "score_0_100": None,
                    "status": "read_error",
                }
            )
            continue
        if not isinstance(data, dict):
            stages_out.append(
                {
                    "stage_id": sid,
                    "stage_title": title,
                    "score_0_100": None,
                    "status": "invalid",
                }
            )
            continue
        rqs = data.get("report_quality_score")
        src = "report_quality_score"
        if rqs is None:
            rqs = data.get("confidence")
            src = "confidence"
        f01 = _coerce_float_01(rqs)
        if f01 is None:
            stages_out.append(
                {
                    "stage_id": sid,
                    "stage_title": title,
                    "score_0_100": None,
                    "source": src,
                    "status": "no_score",
                }
            )
            continue
        s100 = int(round(f01 * 100.0))
        scores_100.append(s100)
        stages_out.append(
            {
                "stage_id": sid,
                "stage_title": title,
                "score_0_100": s100,
                "source": src,
                "status": "ok",
            }
        )

    total: Optional[int] = None
    if scores_100:
        total = int(round(sum(scores_100) / len(scores_100)))

    out: Dict[str, Any] = {
        "schema_version": "review_score_v1",
        "stages": stages_out,
        "total_0_100": total,
        "n_scored": len(scores_100),
        "n_expected": len(REVIEW_STAGES_02_09),
    }
    out_path = os.path.join(repo_output_dir, "review_score.json")
    try:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("write review_score.json failed: %s", e)
    return out


def load_total_report_quality_0_100(repo_output_dir: str) -> Optional[int]:
    """读已写的 review_score.json 的总分，供总报告文首；无则 None。"""
    p = os.path.join(repo_output_dir, "review_score.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        t = data.get("total_0_100")
        if t is None:
            return None
        return int(t)
    except Exception:
        return None


def describe_stage_review_enabled() -> bool:
    v = (os.environ.get("DESCRIBE_STAGE_REVIEW") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def describe_stage_review_applies(stage_id: str, *, expected_question_ids: list) -> bool:
    """JSON-QA 阶段且非 01/10 概览与历史章。"""
    if stage_id in ("01_overview", "10_history"):
        return False
    return bool(expected_question_ids)
