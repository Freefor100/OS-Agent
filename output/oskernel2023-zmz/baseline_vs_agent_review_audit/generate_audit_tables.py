#!/usr/bin/env python3
"""
Generate per-stage comparison tables: baseline vs agent answers + review scores.
Kernel arbitration is done separately (see kernel_verify.py) — this file only joins JSON.
Output: per-stage Markdown under this directory.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("/home/leo/OS-Agent")
QA_DIR = ROOT / "core/describe_stage_qa"
BASE = ROOT / "baseline_output/oskernel2023-zmz/_per_stage"
AGENT = ROOT / "output/oskernel2023-zmz/_per_stage"
OUT = ROOT / "output/oskernel2023-zmz/baseline_vs_agent_review_audit"

STAGES = [
    "02_boot_trap",
    "03_mem_mgmt",
    "04_process_smp",
    "05_fs_drivers",
    "06_sync_ipc",
    "07_security",
    "08_network",
    "09_debug_error",
]


def norm_val(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v).strip()


def load_json(p: Path):
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def review_by_qid(rev: dict | None) -> dict[str, tuple[float | None, float | None, str]]:
    out: dict[str, tuple[float | None, float | None, str]] = {}
    if not rev or not isinstance(rev.get("question_reviews"), list):
        return out
    for item in rev["question_reviews"]:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id", "")).strip()
        if not qid:
            continue
        se = item.get("score_evidence")
        sc = item.get("score_consistency")
        try:
            sef = float(se) if se is not None else None
        except (TypeError, ValueError):
            sef = None
        try:
            scf = float(sc) if sc is not None else None
        except (TypeError, ValueError):
            scf = None
        txt = str(item.get("review", "") or "").replace("\n", " ").strip()[:200]
        out[qid] = (sef, scf, txt)
    return out


_CHOICE_PREFIX = re.compile(r"^[A-Z]\.\s*")


def _norm_choice_text(s: str) -> str:
    """Strip leading 'A. ' style prefix for single_choice comparison."""
    s = s.strip()
    return _CHOICE_PREFIX.sub("", s, count=1).strip()


def agreement_type(qtype: str, bv: str, ov: str) -> str:
    if bv == ov:
        return "一致"
    if qtype == "single_choice":
        if _norm_choice_text(bv) == _norm_choice_text(ov):
            return "一致"
    if qtype in ("tri_state_impl", "single_choice", "multi_choice"):
        return "结论冲突"
    # short_answer / fill_in: heuristic — long text diff
    if len(bv) > 80 or len(ov) > 80:
        return "表述差异"
    return "表述差异"


def esc_cell(s: str, max_len: int = 180) -> str:
    s = s.replace("|", "\\|").replace("\n", "<br>")
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index_lines = [
        "# Baseline vs Agent — 逐题对比表索引",
        "",
        "生成自 `baseline_output/oskernel2023-zmz/_per_stage` 与 `output/oskernel2023-zmz/_per_stage`。",
        "`agreement` 为字面规范化后的初分：`一致` / `表述差异` / `结论冲突`（结构化题型 value 不同）。",
        "`better_side` 初值为 `待核验`（结构化冲突）或 `待酌`（长文本差异）；**以 `kernel_verification.md` 与 `synthesis.md` 为准**。",
        "",
    ]

    for sid in STAGES:
        qa_path = QA_DIR / f"{sid}.json"
        qa = load_json(qa_path)
        questions = qa.get("questions", []) if isinstance(qa, dict) else []
        expected_ids = [str(q.get("question_id")) for q in questions if isinstance(q, dict) and q.get("question_id")]

        ba = load_json(BASE / f"{sid}_answers.json")
        oa = load_json(AGENT / f"{sid}_answers.json")
        br = load_json(BASE / f"{sid}_review.json")
        orv = load_json(AGENT / f"{sid}_review.json")

        bm = {a["question_id"]: a for a in (ba or {}).get("answers", [])}
        om = {a["question_id"]: a for a in (oa or {}).get("answers", [])}
        rb = review_by_qid(br)
        ro = review_by_qid(orv)

        lines = [
            f"# {sid} — Baseline vs Agent",
            "",
            f"- 题库题数: {len(expected_ids)}",
            f"- baseline `report_quality_score`: {(br or {}).get('report_quality_score')}",
            f"- agent `report_quality_score`: {(orv or {}).get('report_quality_score')}",
            "",
            "| question_id | type | agreement | better_side(初值) | baseline_se | baseline_sc | agent_se | agent_sc | baseline_value | agent_value |",
            "|---|---|:---|:---|---:|---:|---:|---:|---|---|",
        ]

        n_same = n_diff = n_conflict = 0
        for q in questions:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id", ""))
            qtype = str(q.get("question_type", ""))
            b = bm.get(qid)
            o = om.get(qid)
            if not b or not o:
                lines.append(
                    f"| {qid} | {qtype} | 缺答案 | — | — | — | — | — | "
                    f"{'缺baseline' if not b else ''} {'缺agent' if not o else ''} |"
                )
                continue
            bv = norm_val(b.get("value"))
            ov = norm_val(o.get("value"))
            agr = agreement_type(qtype, bv, ov)
            if agr == "一致":
                n_same += 1
                better = "tie"
            elif agr == "结论冲突":
                n_conflict += 1
                better = "待核验"
            else:
                n_diff += 1
                better = "待酌"

            se_b, sc_b, _ = rb.get(qid, (None, None, ""))
            se_o, sc_o, _ = ro.get(qid, (None, None, ""))
            se_bs = f"{se_b:.2f}" if se_b is not None else "—"
            sc_bs = f"{sc_b:.2f}" if sc_b is not None else "—"
            se_os = f"{se_o:.2f}" if se_o is not None else "—"
            sc_os = f"{sc_o:.2f}" if sc_o is not None else "—"

            lines.append(
                f"| {qid} | {qtype} | {agr} | {better} | {se_bs} | {sc_bs} | {se_os} | {sc_os} | "
                f"{esc_cell(bv, 220)} | {esc_cell(ov, 220)} |"
            )

        lines.append("")
        lines.append(f"统计: 一致={n_same}, 表述差异={n_diff}, 结论冲突={n_conflict}")
        out_md = OUT / f"{sid}_comparison.md"
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        index_lines.append(f"- [{sid}]({sid}_comparison.md) — 一致 {n_same} / 表述差异 {n_diff} / 结论冲突 {n_conflict}")

    (OUT / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
