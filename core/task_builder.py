from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List

from core.agent_graph_state import TaskSpec
from core.per_planner import STAGE_HINTS


def _slug(s: str, limit: int = 40) -> str:
    out = re.sub(r"[^A-Za-z0-9_]+", "_", (s or "").strip())
    out = re.sub(r"_+", "_", out).strip("_")
    return (out or "task")[:limit]


def _qid_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:8]


def _question_keywords(q: Dict[str, Any]) -> List[str]:
    hints = q.get("task_hints") if isinstance(q.get("task_hints"), dict) else {}
    kws = hints.get("keywords") if isinstance(hints.get("keywords"), list) else []
    out = [str(x).strip() for x in kws if str(x).strip()]
    stem = str(q.get("stem", ""))
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", stem):
        if token.lower() not in {"the", "and", "with", "must", "impl", "state"}:
            out.append(token)
    zh_markers = [
        "页表",
        "物理页",
        "调度",
        "上下文切换",
        "系统调用",
        "trap",
        "文件系统",
        "网络",
        "权限",
        "锁",
        "Futex",
        "fork",
        "exec",
        "wait",
    ]
    for marker in zh_markers:
        if marker in stem:
            out.append(marker)
    seen = set()
    deduped = []
    for item in out:
        low = item.lower()
        if low not in seen:
            seen.add(low)
            deduped.append(item)
    return deduped[:8]


def build_tasks_for_stage(
    *,
    stage_id: str,
    stage_title: str,
    questions: List[Dict[str, Any]],
    plan: Any,
) -> List[TaskSpec]:
    hints = STAGE_HINTS.get(stage_id, {})
    stage_seed_paths = list(getattr(plan, "seed_paths", None) or hints.get("seed_paths", []))
    stage_entry_symbols = list(getattr(plan, "entry_symbols", None) or hints.get("entry_symbols", []))
    tasks: List[TaskSpec] = []

    if not questions:
        base = _slug(stage_id)
        tasks.extend(
            [
                TaskSpec(
                    task_id=f"task_{base}_discovery",
                    stage_id=stage_id,
                    task_type="discovery",
                    query=f"{stage_title} 相关核心模块和入口",
                    seed_paths=stage_seed_paths,
                    entry_symbols=stage_entry_symbols,
                    expected_evidence_types=["search"],
                ),
                TaskSpec(
                    task_id=f"task_{base}_build_platform",
                    stage_id=stage_id,
                    task_type="build_platform",
                    query=f"{stage_title} 相关构建、平台、文档线索",
                    seed_paths=stage_seed_paths,
                    entry_symbols=stage_entry_symbols,
                    expected_evidence_types=["documentation", "build_config"],
                ),
            ]
        )
        if "10_history" in stage_id:
            tasks.append(
                TaskSpec(
                    task_id=f"task_{base}_git_history",
                    stage_id=stage_id,
                    task_type="git_history",
                    query="开发历史、作者贡献和关键文件演进",
                    expected_evidence_types=["git_history"],
                )
            )
        return tasks

    for q in questions:
        qid = str(q.get("question_id", "")).strip() or _qid_hash(str(q))
        qtype = str(q.get("question_type", "")).strip()
        stem = str(q.get("stem", "")).strip()
        task_hints = q.get("task_hints") if isinstance(q.get("task_hints"), dict) else {}
        evidence_policy = q.get("evidence_policy") if isinstance(q.get("evidence_policy"), dict) else {}
        hinted_types = task_hints.get("task_types") if isinstance(task_hints.get("task_types"), list) else []
        expected = evidence_policy.get("required_evidence_types")
        expected_types = [str(x) for x in expected] if isinstance(expected, list) else []
        seed_paths = [str(x) for x in task_hints.get("seed_paths", [])] if isinstance(task_hints.get("seed_paths"), list) else []
        entry_symbols = [str(x) for x in task_hints.get("entry_symbols", [])] if isinstance(task_hints.get("entry_symbols"), list) else []
        seed_paths = (seed_paths + stage_seed_paths)[:10]
        entry_symbols = (entry_symbols + stage_entry_symbols)[:10]
        keywords = _question_keywords(q)
        query = f"{stage_title} / {qid}: {stem}\n关键词: {', '.join(keywords)}"
        base = f"task_{stage_id}_{qid}"

        task_types = list(hinted_types)
        if not task_types:
            # Keep v1 task fanout conservative. One semantic discovery task per
            # question usually yields enough evidence for Writer/Review; add one
            # specialized task only when the question clearly needs it.
            task_types.append("discovery")
            if any(x in stem for x in ("构建", "平台", "架构", "Makefile", "Cargo", "QEMU")):
                task_types.append("build_platform")
            elif any(x.lower() in stem.lower() for x in ("调用链", "跳转链", "路径", "call graph", "flow")):
                task_types.append("flow")
            elif "definition" in expected_types or any(x in stem for x in ("结构体", "字段", "类型", "接口")):
                task_types.append("definition")
            elif qtype == "tri_state_impl" and any(x in stem for x in ("桩", "stub", "todo", "ENOSYS")):
                task_types.append("implementation_state")

        for task_type in dict.fromkeys(task_types):
            tasks.append(
                TaskSpec(
                    task_id=f"{base}_{_slug(task_type)}",
                    stage_id=stage_id,
                    question_id=qid,
                    task_type=str(task_type),
                    query=query,
                    seed_paths=seed_paths,
                    entry_symbols=entry_symbols,
                    expected_evidence_types=expected_types,
                    metadata={
                        "question_type": qtype,
                        "stem": stem,
                        "keywords": keywords,
                    },
                )
            )
    return tasks
