from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from core.per_types import EvidenceItem, ParagraphRecord, ReviewResult, StageState


PATH_CITATION_RE = re.compile(
    r"`[^`\n]*/[^`\n]+\.(?:rs|c|h|cpp|cc|go|zig|S|s|toml|ld|md|py)(?::\d+(?:-\d+)?)?`"
)


def _has_path_citation(text: str) -> bool:
    return bool(PATH_CITATION_RE.search(text or ""))


def _contains_readme_reference(text: str) -> bool:
    lowered = (text or "").lower()
    return "readme" in lowered or "文档提及" in lowered


def _important_paragraph(paragraph: ParagraphRecord) -> bool:
    text = paragraph.text.strip()
    if text.startswith("#"):
        return False
    if len(text) < 30:
        return False
    keywords = (
        "实现", "支持", "采用", "入口", "调度", "页表", "trap", "syscall", "fork",
        "driver", "network", "buddy", "bitmap", "已实现", "未实现", "桩函数", "框架",
        "文件系统", "多核", "安全", "调用链", "history", "evolution"
    )
    return any(keyword.lower() in text.lower() for keyword in keywords)


def _keywords_for_question(question: str) -> List[str]:
    tokens = re.split(r"[：:，,。；;（）()、/\s]+", question)
    out = []
    for token in tokens:
        token = token.strip("-* ")
        if not token:
            continue
        if len(token) >= 2:
            out.append(token.lower())
    return out[:6]


def _find_evidence(evidence_index: Sequence[EvidenceItem], evidence_ids: Sequence[str]) -> List[EvidenceItem]:
    wanted = set(evidence_ids)
    return [item for item in evidence_index if item.evidence_id in wanted]


def _score_from_issues(hard_fail_count: int, soft_fail_count: int, format_issue_count: int) -> float:
    score = 1.0
    score -= hard_fail_count * 0.25
    score -= soft_fail_count * 0.07
    score -= format_issue_count * 0.02
    return max(0.0, round(score, 2))


def _dedupe_actions(actions: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for action in actions:
        key = tuple(sorted(action.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


def _review_paragraphs(state: StageState, target_paragraph_ids: Optional[Sequence[str]] = None) -> ReviewResult:
    draft_document = state.draft_document
    evidence_index = state.evidence_index
    if not draft_document:
        return ReviewResult(
            passed=False,
            score=0.0,
            severity="critical",
            failed_rules=["empty_draft"],
            missing_evidence=[{"reason": "草稿为空"}],
            repair_actions=[{"action_type": "replan_stage", "hint": "草稿为空，需重新规划并执行"}],
        )

    hard_failures: List[str] = []
    missing_evidence: List[Dict[str, str]] = []
    weak_claims: List[Dict[str, str]] = []
    format_issues: List[Dict[str, str]] = []
    repair_actions: List[Dict[str, str]] = []
    missed_modules: List[str] = []

    target_ids = set(target_paragraph_ids or [])
    paragraphs = [
        p for p in draft_document.paragraphs
        if (not target_ids or p.paragraph_id in target_ids) and not p.text.startswith("#")
    ]

    for paragraph in paragraphs:
        linked_evidence = _find_evidence(evidence_index, paragraph.evidence_ids)
        code_evidence = [ev for ev in linked_evidence if ev.source_type in {"source_code", "lsp_call_graph", "git_history", "rag_hit"}]
        strong_evidence = [ev for ev in code_evidence if ev.confidence != "low"]

        if _important_paragraph(paragraph) and not _has_path_citation(paragraph.text):
            hard_failures.append("missing_path_citation")
            missing_evidence.append({
                "paragraph_id": paragraph.paragraph_id,
                "claim_id": paragraph.claim_ids[0] if paragraph.claim_ids else "",
                "reason": "重要结论缺少源码路径引用",
            })
            repair_actions.append({
                "action_type": "add_evidence",
                "target_paragraph_id": paragraph.paragraph_id,
                "target_claim_id": paragraph.claim_ids[0] if paragraph.claim_ids else "",
                "hint": "补充源码路径或符号定义后重写本段",
            })
            repair_actions.append({
                "action_type": "rewrite_paragraph",
                "target_paragraph_id": paragraph.paragraph_id,
                "target_claim_id": paragraph.claim_ids[0] if paragraph.claim_ids else "",
                "hint": "保留原意，仅补充缺失的源码证据与路径引用",
            })

        if _contains_readme_reference(paragraph.text) and not strong_evidence:
            hard_failures.append("readme_over_source")
            missing_evidence.append({
                "paragraph_id": paragraph.paragraph_id,
                "claim_id": paragraph.claim_ids[0] if paragraph.claim_ids else "",
                "reason": "本段结论主要依赖 README/文档，缺少源码证据",
            })
            repair_actions.append({
                "action_type": "add_evidence",
                "target_paragraph_id": paragraph.paragraph_id,
                "target_claim_id": paragraph.claim_ids[0] if paragraph.claim_ids else "",
                "hint": "仅补充源码证据；若确无实现，则降级为文档提及但未见代码",
            })
            repair_actions.append({
                "action_type": "rewrite_paragraph",
                "target_paragraph_id": paragraph.paragraph_id,
                "target_claim_id": paragraph.claim_ids[0] if paragraph.claim_ids else "",
                "hint": "补充源码证据后重写；若仍无实现，则显式降级该结论",
            })

        if any(ev.confidence == "low" for ev in linked_evidence) and not strong_evidence:
            weak_claims.append({
                "paragraph_id": paragraph.paragraph_id,
                "claim_id": paragraph.claim_ids[0] if paragraph.claim_ids else "",
                "reason": "当前段落主要依赖低置信度或降级分析证据",
            })

        if "分页表" in paragraph.text:
            format_issues.append({
                "paragraph_id": paragraph.paragraph_id,
                "reason": "建议将术语“分页表”统一为“页表”",
            })
            repair_actions.append({
                "action_type": "normalize_terminology",
                "target_paragraph_id": paragraph.paragraph_id,
                "hint": "统一专业术语，不改变结论",
            })

    full_text = draft_document.to_markdown().lower()
    if not target_ids:
        for question in state.plan.must_cover[:10] if state.plan else []:
            keywords = _keywords_for_question(question)
            if keywords and not any(keyword in full_text for keyword in keywords):
                hard_failures.append("key_question_unanswered")
                missing_evidence.append({
                    "claim_id": "",
                    "reason": f"阶段关键问题未回答: {question}",
                })
                repair_actions.append({
                    "action_type": "append_missing_module",
                    "hint": f"补充回答该问题并给出源码证据: {question}",
                })

        for seed_path in (state.plan.seed_paths[:6] if state.plan else []):
            normalized = seed_path.lower()
            if "/" in normalized and normalized not in full_text:
                if not any(ev.path and normalized in ev.path.lower() for ev in evidence_index):
                    missed_modules.append(seed_path)

    hard_failures = list(dict.fromkeys(hard_failures))
    missed_modules = list(dict.fromkeys(missed_modules))[:6]
    if missed_modules:
        weak_claims.append({
            "reason": f"计划中的关键路径尚未覆盖: {', '.join(missed_modules[:4])}",
        })
        repair_actions.append({
            "action_type": "append_missing_module",
            "hint": f"优先检查以下关键路径: {', '.join(missed_modules[:4])}",
        })

    hard_fail_count = len(hard_failures)
    soft_fail_count = len(weak_claims)
    format_issue_count = len(format_issues)
    score = _score_from_issues(hard_fail_count, soft_fail_count, format_issue_count)

    severity = "minor"
    if hard_fail_count >= 4:
        severity = "critical"
    elif hard_fail_count >= 2:
        severity = "major"
    elif hard_fail_count == 1:
        severity = "major"
    elif soft_fail_count > 2:
        severity = "minor"

    return ReviewResult(
        passed=hard_fail_count == 0,
        score=score,
        severity=severity,
        failed_rules=hard_failures,
        missing_evidence=missing_evidence,
        weak_claims=weak_claims,
        format_issues=format_issues,
        missed_modules=missed_modules,
        repair_actions=_dedupe_actions(repair_actions),
    )


def review_stage(
    state: StageState,
    llm: Any = None,
    *,
    llm_primary: bool = False,
    on_llm_stream_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> ReviewResult:
    rule_result = _review_paragraphs(state)
    if llm_primary and llm is not None:
        from core.per_llm_stages import run_llm_review

        llm_result = run_llm_review(
            state,
            llm,
            on_stream_step=on_llm_stream_step,
            stage_id=state.stage_id,
        )
        result = llm_result if llm_result is not None else rule_result
    else:
        print(
            "   📤 ③ Verify: 仅规则审阅（无 LLM；内置检查路径引用、README 证据、must_cover 关键词等）"
        )
        print(
            f"   📥 ③ Verify 结果: passed={rule_result.passed}, score={rule_result.score}, "
            f"repair_actions={len(rule_result.repair_actions)} 条"
        )
        result = rule_result
    state.review_result = result
    state.status = "done" if result.passed else "review_failed"
    return result


def re_review_stage(state: StageState, target_paragraph_ids: Sequence[str]) -> ReviewResult:
    result = _review_paragraphs(state, target_paragraph_ids=target_paragraph_ids)
    state.review_result = result
    if result.passed:
        state.status = "patched"
    return result
