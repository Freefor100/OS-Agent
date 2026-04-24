#!/usr/bin/env python3
"""Export diff questions (baseline vs agent) to blind-review md + json per repo.

扫描 `baseline_output/<repo>/_per_stage` 与 `output/<repo>/_per_stage`，对题库
`core/describe_stage_qa` 中 REVIEW_STAGES_02_09 各章若两侧均有 `*_answers.json` 则参与对比。

MD 不披露方法 A/B 与管线对应关系。维护者约定：表列与 JSON 中 **method_a** = Agent 侧、
**method_b** = Baseline 侧（与 md 列顺序一致）。

用法：
  python export_diffs_with_evidence.py              # 处理所有成对仓库
  python export_diffs_with_evidence.py oskernel2023-zmz   # 仅指定仓库
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path("/home/leo/OS-Agent")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.describe_stage_review import REVIEW_STAGES_02_09

QA_DIR = ROOT / "core/describe_stage_qa"
BASELINE_ROOT = ROOT / "baseline_output"
OUTPUT_ROOT = ROOT / "output"

STAGES: tuple[str, ...] = REVIEW_STAGES_02_09

_CHOICE_PREFIX = re.compile(r"^[A-Z]\.\s*")


def norm_val(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v).strip()


def values_differ(qtype: str, bv: str, ov: str) -> bool:
    if bv == ov:
        return False
    if qtype == "single_choice":
        b2 = _CHOICE_PREFIX.sub("", bv.strip(), count=1).strip()
        o2 = _CHOICE_PREFIX.sub("", ov.strip(), count=1).strip()
        if b2 == o2:
            return False
    return True


def cell_text(s: str, max_len: int = 12000) -> str:
    if not s:
        return "—"
    s = str(s).replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("|", "\\|")
    s = s.replace("\n", "<br>")
    if len(s) > max_len:
        s = s[: max_len - 20] + "<br>…（截断）"
    return s


def stem_for_atx_heading(stem: str) -> str:
    if not stem.strip():
        return "（无题干）"
    s = re.sub(r"\s+", " ", stem.strip())
    s = re.sub(r"^#+\s*", "", s)
    return s


def fmt_evidence_table(ev: object, per_excerpt: int = 500, max_items: int = 20) -> str:
    if not isinstance(ev, list) or not ev:
        return "—"
    parts: list[str] = []
    for i, item in enumerate(ev[:max_items], 1):
        if not isinstance(item, dict):
            parts.append(f"[{i}] （非对象）")
            continue
        path = str(item.get("path", "") or "")
        sym = str(item.get("symbol_name", item.get("symbol_kind", "")) or "")
        ex = str(item.get("excerpt", "") or "").replace("\r", "")
        ex = re.sub(r"\s+", " ", ex).strip()
        if len(ex) > per_excerpt:
            ex = ex[: per_excerpt - 1] + "…"
        parts.append(f"[{i}] `{path}` · {sym}<br><code>{ex}</code>")
    if len(ev) > max_items:
        parts.append(f"… 共 {len(ev)} 条 evidence，仅列前 {max_items} 条")
    return "<br>".join(parts)


def discover_repo_slugs() -> list[str]:
    if not BASELINE_ROOT.is_dir():
        return []
    out: list[str] = []
    for d in sorted(BASELINE_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        name = d.name
        if (OUTPUT_ROOT / name / "_per_stage").is_dir():
            out.append(name)
    return out


def export_repo(repo_slug: str) -> tuple[int, Path]:
    base_dir = BASELINE_ROOT / repo_slug / "_per_stage"
    agent_dir = OUTPUT_ROOT / repo_slug / "_per_stage"
    out_dir = OUTPUT_ROOT / repo_slug / "baseline_vs_agent_review_audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [f"# {repo_slug}", ""]
    all_records: list[dict] = []
    total_diff = 0

    for sid in STAGES:
        qa_path = QA_DIR / f"{sid}.json"
        ba_path = base_dir / f"{sid}_answers.json"
        oa_path = agent_dir / f"{sid}_answers.json"
        if not qa_path.is_file() or not ba_path.is_file() or not oa_path.is_file():
            continue

        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        stem_by_id: dict[str, str] = {}
        type_by_id: dict[str, str] = {}
        for q in qa.get("questions", []):
            if isinstance(q, dict) and q.get("question_id"):
                stem_by_id[str(q["question_id"])] = str(q.get("stem", "")).strip()
                type_by_id[str(q["question_id"])] = str(q.get("question_type", "")).strip()

        ba = json.loads(ba_path.read_text(encoding="utf-8"))
        oa = json.loads(oa_path.read_text(encoding="utf-8"))
        bm = {a["question_id"]: a for a in ba.get("answers", [])}
        om = {a["question_id"]: a for a in oa.get("answers", [])}

        stage_title = ba.get("stage_title", sid)
        section_lines: list[str] = []
        n = 0
        for qid in sorted(set(bm) & set(om), key=lambda x: x):
            b, o = bm[qid], om[qid]
            qtype = type_by_id.get(qid, b.get("question_type", ""))
            bv = norm_val(b.get("value"))
            ov = norm_val(o.get("value"))
            if not values_differ(qtype, bv, ov):
                continue
            n += 1
            total_diff += 1
            stem = stem_by_id.get(qid, "")
            ev_b = fmt_evidence_table(b.get("evidence"))
            ev_a = fmt_evidence_table(o.get("evidence"))

            all_records.append(
                {
                    "stage_id": sid,
                    "question_id": qid,
                    "question_type": qtype,
                    "stem": stem,
                    "method_a": {"value": o.get("value"), "evidence": o.get("evidence", [])},
                    "method_b": {"value": b.get("value"), "evidence": b.get("evidence", [])},
                }
            )

            section_lines.append(f"### `{qid}` · `{qtype}`")
            section_lines.append("")
            section_lines.append("### " + stem_for_atx_heading(stem))
            section_lines.append("")
            section_lines.append("| 项目 | 方法A | 方法B |")
            section_lines.append("| --- | --- | --- |")
            section_lines.append("| **答案** | " + cell_text(ov, 12000) + " | " + cell_text(bv, 12000) + " |")
            section_lines.append("| **证据** | " + cell_text(ev_a, 16000) + " | " + cell_text(ev_b, 16000) + " |")
            section_lines.append("")

        if n > 0:
            lines.append(f"## {sid} — {stage_title}")
            lines.append("")
            lines.extend(section_lines)

    md_path = out_dir / "diffs_with_evidence.md"
    json_path = out_dir / "diffs_with_evidence.json"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "schema_version": "diff_evidence_v4_blind",
                "os_repo": repo_slug,
                "total_diff_questions": total_diff,
                "items": all_records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return total_diff, md_path


def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    if argv:
        slugs = argv
        for s in slugs:
            if not (BASELINE_ROOT / s / "_per_stage").is_dir():
                print(f"跳过（无 baseline）: {s}", file=sys.stderr)
                continue
            if not (OUTPUT_ROOT / s / "_per_stage").is_dir():
                print(f"跳过（无 output）: {s}", file=sys.stderr)
                continue
            n, p = export_repo(s)
            print(f"{s}: {n} 条差异 -> {p}")
    else:
        for slug in discover_repo_slugs():
            n, p = export_repo(slug)
            print(f"{slug}: {n} 条差异 -> {p}")


if __name__ == "__main__":
    main()
