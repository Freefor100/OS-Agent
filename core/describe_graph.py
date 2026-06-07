from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage

from core.agent_events import EventLogger, task_event_context
from core.agent_graph_state import DescribeGraphState, DraftAnswerRecord, EvidenceRecord, TaskResult, TaskSpec, utcnow_iso
from core.agent_locks import FileLock, lock_path
from core.describe_json_qa import (
    SCHEMA_VERSION as JSON_QA_SCHEMA_VERSION,
    coerce_answers_payload_by_stage_qa,
    coerce_answers_payload_defaults,
    ensure_structured_value_for_question,
    ensure_fact_answers_for_question,
    parse_answers_json,
    validate_answers_payload,
)
from core.describe_stage_qa import load_stage_qa, list_question_ids
from core.describe_stage_review import (
    build_stage_qa_question_sheet,
    describe_stage_review_applies,
    describe_stage_review_enabled,
    enrich_review_with_report_quality,
    run_describe_stage_review,
    write_review_score_json,
)
from core.evidence_store import EvidenceStore
from core.draft_answer_store import DraftAnswerStore
from core.evidence_verifier import verify_evidence
from core.qa_contract import (
    collect_feature_ids,
    evidence_can_support_claim,
    feature_by_question,
    features_for_stage_qa,
    negative_search_policy_for_question,
    normalize_tri_state_answer_value,
    required_evidence_types_for_question,
    strongest_evidence_strength,
)
from core.qa_prompt_guidance import answer_shape_guidance, evidence_discipline_guidance, field_guidance
from core.feature_graph import publish_feature_graph
from core.html_renderer import publish_html_report
from core.per_planner import build_repo_profile, ensure_execution_steps, plan_stage
from core.per_llm_stages import extract_json_object
from core.per_types import StageState
from core.task_agents import run_task_agent
from core.task_builder import build_tasks_for_stage, build_tasks_from_llm_plan
from core.utils import repo_name_from_url


TECH_STAGE_IDS = [
    "02_boot_trap",
    "03_mem_mgmt",
    "04_process_smp",
    "05_fs_drivers",
    "06_sync_ipc",
    "07_security",
    "08_network",
    "09_debug_error",
    "10_history",
]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int((os.environ.get(name) or "").strip() or default))
    except ValueError:
        return default


def _coerce_markdown_writer_output(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    candidates = [text]
    fenced = re.search(r"```(?:json|JSON)\s*", text)
    if fenced:
        fence_end = text.find("```", fenced.end())
        if fence_end != -1:
            candidates.insert(0, text[fenced.end():fence_end].strip())

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            for key in ("chapter", "markdown", "content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

    return text


def _atomic_save_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _slug(s: str) -> str:
    keep = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    out = "".join(keep).strip("_")
    return out[:60] if out else "section"


def _section_path(repo_output_dir: str, stage_id: str, title: str) -> str:
    prefix = stage_id.split("_", 1)[0]
    return os.path.join(repo_output_dir, "sections", f"{prefix}_{_slug(title)}.md")


def _questions_for_stage(stage_id: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    try:
        qa = load_stage_qa(stage_id)
    except Exception:
        return [], []
    questions = qa.get("questions", []) if isinstance(qa, dict) else []
    if not isinstance(questions, list):
        questions = []
    return questions, list_question_ids(qa)


def _question_digest(question: Dict[str, Any]) -> str:
    view = {
        "question_id": question.get("question_id"),
        "question_type": question.get("question_type"),
        "stem": question.get("stem"),
        "choices": question.get("choices"),
        "answer_contract": question.get("answer_contract"),
        "structured_facts": question.get("structured_facts"),
    }
    blob = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _group_evidence_records(records: List[EvidenceRecord], stage_id: str = "") -> Dict[str, List[EvidenceRecord]]:
    grouped: Dict[str, List[EvidenceRecord]] = {}
    for rec in records:
        if stage_id and rec.stage_id != stage_id:
            continue
        for qid in rec.question_ids or [""]:
            grouped.setdefault(qid, []).append(rec)
    return grouped


def _curate_grouped_evidence(grouped: Dict[str, List[EvidenceRecord]]) -> Dict[str, List[EvidenceRecord]]:
    curated: Dict[str, List[EvidenceRecord]] = {}
    rank = {"high": 3, "medium": 2, "low": 1}
    for qid, records in grouped.items():
        kept = [
            r
            for r in records
            if (r.validity != "invalid" and not _is_bad_negative_search_evidence(r))
            or _is_good_negative_search_evidence(r)
        ]
        if not kept:
            kept = list(records)
        seen = set()
        deduped: List[EvidenceRecord] = []
        for rec in sorted(
            kept,
            key=lambda r: (
                rank.get(r.confidence, 0),
                {"strong": 3, "weak": 2, "hint": 1, "invalid": 0}.get(r.strength, 0),
                float(r.verifier_score or 0.0),
                1 if r.path else 0,
            ),
            reverse=True,
        ):
            key = (rec.path, rec.evidence_type, (rec.excerpt or "")[:160])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(rec)
        curated[qid] = deduped
    return curated


def _is_bad_negative_search_evidence(record: EvidenceRecord) -> bool:
    text = (record.excerpt or "").lower()
    return any(
        bad in text
        for bad in (
            "notes|not_found",
            "notes, not_found",
            "notes not_found",
        )
    )


def _is_good_negative_search_evidence(record: EvidenceRecord) -> bool:
    text = (record.excerpt or "").lower()
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    neg = metadata.get("negative_search") if isinstance(metadata.get("negative_search"), dict) else {}
    neg_cov = metadata.get("negative_search_coverage") if isinstance(metadata.get("negative_search_coverage"), dict) else {}
    if neg.get("coverage_sufficient") is True or neg_cov.get("coverage_sufficient") is True:
        return not _is_bad_negative_search_evidence(record)
    return (
        ("未找到匹配" in text or "no matches" in text or "no results" in text)
        and ("已搜索" in text or "searched" in text)
        and not _is_bad_negative_search_evidence(record)
    )


def _json_stable(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return repr(value)


def _brief_diff(before: Any, after: Any) -> Dict[str, Any]:
    if _json_stable(before) == _json_stable(after):
        return {}
    if isinstance(before, dict) and isinstance(after, dict):
        changed: Dict[str, Any] = {}
        keys = sorted(set(before.keys()) | set(after.keys()))
        for key in keys:
            b = before.get(key)
            a = after.get(key)
            if _json_stable(b) != _json_stable(a):
                changed[key] = {"before": b, "after": a}
        return changed
    return {"before": before, "after": after}


def _answer_audit_meta(question: Dict[str, Any], phase: str, before: Any, after: Any) -> Dict[str, Any]:
    qid = str(question.get("question_id") or "").strip()
    return {
        "question_id": qid,
        "phase": phase,
        "diff": _brief_diff(before, after),
    }


def _append_programmatic_mutation(
    answer: Dict[str, Any],
    phase: str,
    before: Any,
    after: Any,
    *,
    reason: str,
) -> None:
    if not isinstance(answer, dict):
        return
    diff = _brief_diff(before, after)
    if not diff:
        return
    meta = dict(answer.get("_meta")) if isinstance(answer.get("_meta"), dict) else {}
    mutations = list(meta.get("programmatic_mutations") or []) if isinstance(meta.get("programmatic_mutations"), list) else []
    fields = sorted(diff.keys()) if isinstance(diff, dict) else []
    mutations.append(
        {
            "phase": phase,
            "source": "program",
            "reason": reason,
            "fields": fields,
            "diff": diff,
        }
    )
    meta["programmatic_mutations"] = mutations
    answer["_meta"] = meta


def _evidence_audit(records: List[EvidenceRecord]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rec in records:
        out.append(
            {
                "evidence_id": rec.evidence_id,
                "path": rec.path,
                "evidence_type": rec.evidence_type,
                "strength": rec.strength,
                "validity": rec.validity,
                "supports_claim_types": list(rec.supports_claim_types or []),
                "verifier_score": rec.verifier_score,
            }
        )
    return out


def _set_meta_path(answer: Dict[str, Any], path: List[str], value: Any) -> None:
    meta = dict(answer.get("_meta")) if isinstance(answer.get("_meta"), dict) else {}
    cursor: Dict[str, Any] = meta
    for key in path[:-1]:
        child = cursor.get(key)
        if not isinstance(child, dict):
            child = {}
        cursor[key] = child
        cursor = child
    cursor[path[-1]] = value
    answer["_meta"] = meta


def _evidence_type(record: EvidenceRecord) -> str:
    return str(record.evidence_type or "").strip()


def _is_positive_implementation_evidence(record: EvidenceRecord) -> bool:
    et = _evidence_type(record)
    if et == "negative_search" or "not_found" in (record.supports_claim_types or []):
        return False
    if "stub" in (record.supports_claim_types or []):
        return False
    if record.validity == "invalid":
        return False
    if "implemented" in (record.supports_claim_types or []):
        return True
    return record.strength == "strong" and et in {
        "definition",
        "implementation_body",
        "function_body",
        "call_site",
        "usage_flow",
        "call_graph",
        "read_code_segment",
    }


def _fact_answers_support_stub(answer: Dict[str, Any]) -> bool:
    facts = answer.get("fact_answers")
    if not isinstance(facts, list):
        return False
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if str(fact.get("value") or "").strip() == "stub_or_declaration_only":
            return True
        notes = str(fact.get("notes") or "").lower()
        if any(marker in notes for marker in ("stub", "declaration only", "桩", "声明", "固定返回", "占位")):
            return True
    return False


def _fact_answers_support_implemented(answer: Dict[str, Any]) -> bool:
    facts = answer.get("fact_answers")
    if not isinstance(facts, list):
        return False
    strong = 0
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if str(fact.get("value") or "").strip() == "yes_strong":
            strong += 1
    return strong >= 2


def _tri_state_value_allowed(value: str, evidence: List[EvidenceRecord], answer: Dict[str, Any]) -> bool:
    value = normalize_tri_state_answer_value(value)
    if value == "unknown":
        return True
    if evidence_can_support_claim(evidence, value):
        return True
    if value == "implemented":
        return any(_is_positive_implementation_evidence(rec) for rec in evidence) or (
            _fact_answers_support_implemented(answer)
            and any(_evidence_type(rec) != "negative_search" and rec.validity != "invalid" for rec in evidence)
        )
    if value == "stub":
        return any("stub" in (rec.supports_claim_types or []) for rec in evidence) or _fact_answers_support_stub(answer)
    if value == "not_found":
        return evidence_can_support_claim(evidence, "not_found")
    return False


def _stub_supported_by_drafts(drafts: List[Any]) -> bool:
    """Task Agent 草稿中是否有 medium/high confidence 的 stub 判断。"""
    for d in drafts:
        answer = d.answer if isinstance(d, DraftAnswerRecord) else (d if isinstance(d, dict) else {})
        if str(answer.get("value") or "").strip() == "stub":
            conf = str(answer.get("confidence") or "low").strip().lower()
            if conf in {"medium", "high"}:
                return True
    return False


def _stage_by_id(stages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(s.get("id")): s for s in stages}


def _list_str(value: Any, limit: int) -> List[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_str([str(x).strip() for x in value if str(x).strip()])[:limit]


def _dedupe_str(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


class MultiAgentRuntime:
    def __init__(self, *, repo_url: str, stages: List[Dict[str, Any]], output_dir: str,
                 repo_meta: Optional[Dict[str, Any]] = None):
        self.repo_url = repo_url
        self.repo_name = repo_name_from_url(repo_url)
        self.repo_path = os.path.normpath(os.path.join("./repos", self.repo_name))
        self.repo_output_dir = os.path.join(output_dir, self.repo_name)
        self.state_dir = os.path.join(self.repo_output_dir, "_agent_state")
        self.stages = stages
        self.stages_by_id = _stage_by_id(stages)
        self.repo_meta = repo_meta or {}
        self.run_id = self._load_or_create_run_id()
        self.events = EventLogger(self.run_id, self.state_dir)
        self.evidence_store = EvidenceStore(os.path.join(self.state_dir, "evidence_store.jsonl"))
        self.draft_store = DraftAnswerStore(os.path.join(self.state_dir, "draft_answer_store.jsonl"))
        self.max_parallel_stages = _env_int("OS_AGENT_MAX_PARALLEL_STAGES", 2)
        self.max_parallel_tasks = _env_int("OS_AGENT_MAX_PARALLEL_TASKS_PER_STAGE", 3)
        self.max_review_fix_rounds = 3
        self.max_task_retries = 3
        self.force_stages = {
            item.strip()
            for item in (os.environ.get("OS_AGENT_FORCE_STAGES") or "").split(",")
            if item.strip()
        }
        os.makedirs(os.path.join(self.state_dir, "stages"), exist_ok=True)
        os.makedirs(os.path.join(self.state_dir, "tasks"), exist_ok=True)
        os.makedirs(os.path.join(self.state_dir, "assembler"), exist_ok=True)
        os.makedirs(os.path.join(self.state_dir, "reviews"), exist_ok=True)
        os.makedirs(os.path.join(self.repo_output_dir, "sections"), exist_ok=True)
        os.makedirs(os.path.join(self.repo_output_dir, "_per_stage"), exist_ok=True)

    def _load_or_create_run_id(self) -> str:
        run_state_path = os.path.join(self.state_dir, "run_state.json")
        data = _load_json(run_state_path)
        if data.get("run_id"):
            return str(data["run_id"])
        return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    def save_run_state(self, status: str, extra: Optional[Dict[str, Any]] = None) -> None:
        reviewed = []
        for sid in [s.get("id") for s in self.stages]:
            if self._stage_status(str(sid)) == "reviewed":
                reviewed.append(str(sid))
        payload = {
            "run_id": self.run_id,
            "repo_name": self.repo_name,
            "repo_path": self.repo_path,
            "output_dir": self.repo_output_dir,
            "status": status,
            "completed_stages": reviewed,
            "updated_at": utcnow_iso(),
        }
        if extra:
            payload.update(extra)
        with FileLock(lock_path(self.state_dir, "output_write")):
            _atomic_save_json(os.path.join(self.state_dir, "run_state.json"), payload)

    def _stage_state_path(self, stage_id: str) -> str:
        return os.path.join(self.state_dir, "stages", f"{stage_id}_state.json")

    def _task_state_path(self, task_id: str) -> str:
        return os.path.join(self.state_dir, "tasks", f"{task_id}.json")

    def _stage_status(self, stage_id: str) -> str:
        return str(_load_json(self._stage_state_path(stage_id)).get("status") or "")

    def _stage_state(self, stage_id: str) -> Dict[str, Any]:
        return _load_json(self._stage_state_path(stage_id))

    def _group_records_by_question(self, stage_id: str, records: List[EvidenceRecord]) -> Dict[str, List[EvidenceRecord]]:
        grouped = _group_evidence_records(records, stage_id)
        return _curate_grouped_evidence(self._schema_verify_grouped_evidence(stage_id, grouped))

    def _store_evidence_by_question(self, stage_id: str) -> Dict[str, List[EvidenceRecord]]:
        grouped = self.evidence_store.grouped_by_question(stage_id)
        return _curate_grouped_evidence(self._schema_verify_grouped_evidence(stage_id, grouped))

    def _schema_verify_grouped_evidence(
        self,
        stage_id: str,
        grouped: Dict[str, List[EvidenceRecord]],
    ) -> Dict[str, List[EvidenceRecord]]:
        stage_qa = load_stage_qa(stage_id)
        qmap = {
            str(q.get("question_id") or "").strip(): q
            for q in stage_qa.get("questions", []) if isinstance(q, dict)
        }
        out: Dict[str, List[EvidenceRecord]] = {}
        for qid, records in grouped.items():
            question = qmap.get(qid, {})
            required = required_evidence_types_for_question(question) if question else []
            negative_policy = negative_search_policy_for_question(question) if question else {}
            feature_ids = collect_feature_ids(question) if question else []
            verified: List[EvidenceRecord] = []
            for rec in records:
                if feature_ids and not rec.feature_ids:
                    rec.feature_ids = feature_ids
                verified.append(
                    verify_evidence(
                        rec,
                        repo_path=self.repo_path,
                        required_evidence_types=required,
                        negative_search_policy=negative_policy,
                    )
                )
            out[qid] = verified
        return out

    def _clear_stale_locks(self) -> None:
        locks_dir = os.path.join(self.state_dir, "locks")
        if os.path.exists(locks_dir):
            for fname in os.listdir(locks_dir):
                if fname.endswith(".lock"):
                    try:
                        os.remove(os.path.join(locks_dir, fname))
                    except OSError:
                        pass

    def run(self) -> None:
        self._clear_stale_locks()
        self.events.emit("run_start", f"OS-Agent D Multi-Agent start repo={self.repo_name}")
        self.save_run_state("running")
        self._repo_prepare()
        repo_profile = build_repo_profile(repo_url=self.repo_url, repo_path=self.repo_path)
        _atomic_save_json(os.path.join(self.repo_output_dir, "repo_profile.json"), repo_profile)
        graph_state = DescribeGraphState(
            run_id=self.run_id,
            repo_name=self.repo_name,
            repo_path=self.repo_path,
            output_dir=self.repo_output_dir,
            repo_profile=repo_profile,
            stage_order=[s["id"] for s in self.stages],
            status="running",
        )
        _atomic_save_json(os.path.join(self.state_dir, "graph_state.json"), graph_state.to_dict())

        parallel_stage_ids = [sid for sid in TECH_STAGE_IDS if sid in self.stages_by_id]
        errored_stage_ids: List[str] = []
        with ThreadPoolExecutor(max_workers=self.max_parallel_stages) as pool:
            futures = {
                pool.submit(self._run_stage, sid, repo_profile): sid
                for sid in parallel_stage_ids
            }
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    errored_stage_ids.append(sid)
                    self.events.emit("stage_error", f"{type(exc).__name__}: {exc}", stage_id=sid, level="error")
        blocked_stage_ids = [
            sid for sid in parallel_stage_ids
            if self._stage_status(sid) == "blocked"
        ]
        blocked_stage_ids = _dedupe_str(blocked_stage_ids + errored_stage_ids)
        if blocked_stage_ids:
            self.events.emit(
                "overview_blocked",
                "skip 01_overview because technical stage review/precheck is blocked: "
                + ", ".join(blocked_stage_ids),
                stage_id="01_overview",
                level="error",
                metadata={"blocked_stage_ids": blocked_stage_ids},
            )
            self.save_run_state("blocked", {"blocked_stages": blocked_stage_ids})
            with FileLock(lock_path(self.state_dir, "output_write")):
                self._save_graph_snapshot_unlocked(status="blocked", current_stage=blocked_stage_ids[0])
            return
        if "01_overview" in self.stages_by_id:
            self._run_stage("01_overview", repo_profile)
        self._publish_final_report()
        self.save_run_state("done")
        with FileLock(lock_path(self.state_dir, "output_write")):
            self._save_graph_snapshot_unlocked(status="done")
        self.events.emit("run_done", f"OS-Agent D Multi-Agent done repo={self.repo_name}")

    def _repo_prepare(self) -> None:
        self.events.emit("repo_prepare", "checking local repository")
        if os.path.exists(self.repo_path) and os.path.isdir(self.repo_path) and os.listdir(self.repo_path):
            try:
                from tools.git_ops import restore_git_tracked_worktree_if_needed

                msg = restore_git_tracked_worktree_if_needed(self.repo_path)
                self.events.emit("repo_ready", msg)
            except Exception as exc:
                self.events.emit("repo_ready", f"repo exists; restore check skipped: {exc}", level="warn")
        else:
            from tools.git_ops import clone_repository

            self.events.emit("repo_clone", f"cloning {self.repo_url}")
            clone_repository.invoke({"repo_url": self.repo_url})
        try:
            from tools.lsp_ops import cleanup_os_agent_repo_ephemeral

            cleanup_os_agent_repo_ephemeral(self.repo_path)
        except Exception as exc:
            self.events.emit("cleanup_skip", f"LSP cleanup skipped: {exc}", level="warn")
        try:
            with FileLock(lock_path(self.state_dir, "vector_index")):
                from core.code_rag import CodeRAGEngine

                rag_engine = CodeRAGEngine(project_name=self.repo_name)
                rag_engine.build_index(self.repo_path, force=False)
            self.events.emit("rag_index_done", "RAG pre-index ready")
        except Exception as exc:
            self.events.emit("rag_index_skip", f"RAG pre-index skipped: {exc}", level="warn")

    def _run_stage(self, stage_id: str, repo_profile: Dict[str, Any]) -> None:
        stage = self.stages_by_id[stage_id]
        title = str(stage.get("title") or stage_id)
        answers_path = os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_answers.json")
        if os.path.isfile(answers_path) and stage_id not in self.force_stages:
            self.events.emit("stage_skip", "answers file exists, skipping", stage_id=stage_id)
            state_payload = {
                "stage_id": stage_id,
                "stage_title": title,
                "status": "reviewed",
                "block_reason": "",
                "assembler_precheck_status": "",
                "review_needs_fix": False,
                "answer_path": answers_path,
                "blocked_question_ids": [],
                "updated_at": utcnow_iso(),
            }
            with FileLock(lock_path(self.state_dir, "output_write")):
                _atomic_save_json(self._stage_state_path(stage_id), state_payload)
            return

        if self._stage_status(stage_id) == "reviewed" and stage_id not in self.force_stages:
            self.events.emit("stage_skip", "already reviewed", stage_id=stage_id)
            return
        questions, expected_question_ids = _questions_for_stage(stage_id)
        self.events.emit("stage_start", title, stage_id=stage_id, metadata={"total_questions": len(questions)})
        existing_state = self._stage_state(stage_id)
        if (
            existing_state.get("status") == "blocked"
            and existing_state.get("block_reason") in ("", None, "assembler_precheck")
            and stage_id not in self.force_stages
            and questions
        ):
            self._resume_blocked_stage(stage_id, title, stage, questions, expected_question_ids)
            return
        stage_state = StageState(
            stage_id=stage_id,
            stage_title=title,
            stage_type="describe",
            stage_prompt=str(stage.get("prompt") or ""),
        )
        stage_state.plan = ensure_execution_steps(plan_stage(stage_state, repo_profile=repo_profile, global_memory={}))
        task_plan_overlay = self._run_stage_plan_agent(stage_id, title, questions, stage_state.plan, repo_profile, force=stage_id in self.force_stages)
        if isinstance(task_plan_overlay, dict):
            stage_state.dynamic_context["llm_task_plan"] = task_plan_overlay.get("task_plan") or []
        _atomic_save_json(
            os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_plan.json"),
            {**stage_state.plan.to_dict(), "task_plan": stage_state.dynamic_context.get("llm_task_plan", [])},
        )
        tasks = build_tasks_from_llm_plan(
            stage_id=stage_id,
            stage_title=title,
            questions=questions,
            plan=stage_state.plan,
            llm_task_plan=stage_state.dynamic_context.get("llm_task_plan", []),
        )
        task_results, records, drafts = self._run_tasks(stage_id, tasks, force=stage_id in self.force_stages)
        for rec in records:
            self.evidence_store.append(rec)
        for draft in drafts:
            self.draft_store.append(draft)
        force_stage = stage_id in self.force_stages
        evidence_by_question = self._group_records_by_question(stage_id, records) if force_stage else self._store_evidence_by_question(stage_id)
        precheck: Dict[str, Any] = {}
        if questions:
            precheck = self._assembler_precheck(stage_id, title, questions, evidence_by_question)
        if questions:
            payload, _ = self._assemble_stage(stage_id, title, questions, expected_question_ids, evidence_by_question)
        else:
            payload, markdown = self._write_stage(stage_id, title, questions, expected_question_ids, evidence_by_question)
            # 01/10 章是 LLM 直写 markdown，写入 sections/ 供 index.html 使用
            section_path = _section_path(self.repo_output_dir, stage_id, title)
            if markdown and not stage.get("skip_in_report", False):
                with FileLock(lock_path(self.state_dir, "output_write")):
                    with open(section_path, "w", encoding="utf-8") as f:
                        f.write(markdown.strip() + "\n")
        review = self._review_stage(stage_id, title, expected_question_ids, payload)
        fix_round = 0
        while questions and self._review_needs_fix(review) and fix_round < self.max_review_fix_rounds:
            fix_round += 1
            self.events.emit("fix_round_start", f"round={fix_round}", stage_id=stage_id, agent_name="fix_task_builder")
            fix_tasks = self._build_fix_tasks(stage_id, title, review, questions)
            if not fix_tasks:
                break
            fix_results, fix_records, fix_drafts = self._run_tasks(stage_id, fix_tasks)
            for rec in fix_records:
                self.evidence_store.append(rec)
            for draft in fix_drafts:
                self.draft_store.append(draft)
            records.extend(fix_records)
            drafts.extend(fix_drafts)
            task_results.extend(fix_results)
            evidence_by_question = self._store_evidence_by_question(stage_id)
            if stage_id in self.force_stages:
                evidence_by_question = self._group_records_by_question(stage_id, records)
            precheck = self._assembler_precheck(stage_id, title, questions, evidence_by_question)
            payload, _ = self._assemble_stage(
                stage_id,
                title,
                questions,
                expected_question_ids,
                evidence_by_question,
                review_fix_records=fix_records,
                review_fix_round=fix_round,
            )
            review = self._review_stage(stage_id, title, expected_question_ids, payload)
        review_still_needs_fix = bool(questions and self._review_needs_fix(review))
        final_stage_status = "blocked" if precheck.get("status") == "blocked" or review_still_needs_fix else "reviewed"
        block_reason = ""
        if precheck.get("status") == "blocked":
            block_reason = "assembler_precheck"
        elif review_still_needs_fix:
            block_reason = "review_quality"
        blocked_question_ids = list(precheck.get("missing_question_ids") or []) + list(precheck.get("weak_question_ids") or [])
        if review_still_needs_fix:
            blocked_question_ids.extend(self._review_weak_question_ids(review))
        blocked_question_ids = _dedupe_str(blocked_question_ids)
        state_payload = {
            "stage_id": stage_id,
            "stage_title": title,
            "status": final_stage_status,
            "block_reason": block_reason,
            "assembler_precheck_status": precheck.get("status") if precheck else "",
            "review_needs_fix": review_still_needs_fix,
            "review_fix_rounds": fix_round,
            "blocked_question_ids": blocked_question_ids,
            "plan_path": os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_plan.json"),
            "task_ids": [t.task_id for t in tasks],
            "evidence_ids": [r.evidence_id for r in records],
            "draft_answer_ids": [d.draft_answer_id for d in drafts],
            "answer_path": os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_answers.json") if questions else "",
            "section_path": section_path,
            "review_path": os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_review.json") if review else "",
            "updated_at": utcnow_iso(),
        }
        with FileLock(lock_path(self.state_dir, "output_write")):
            _atomic_save_json(self._stage_state_path(stage_id), state_payload)
            self._save_graph_snapshot_unlocked(status="running", current_stage=stage_id)
        self.events.emit(
            "stage_done",
            f"{title} status={final_stage_status} evidence={len(records)} tasks={len(task_results)}"
            + (f" block_reason={block_reason}" if block_reason else ""),
            stage_id=stage_id,
            metadata={"review_confidence": review.get("confidence") if isinstance(review, dict) else None},
        )

    def _resume_blocked_stage(
        self,
        stage_id: str,
        title: str,
        stage: Dict[str, Any],
        questions: List[Dict[str, Any]],
        expected_question_ids: List[str],
    ) -> None:
        self.events.emit("stage_resume_blocked", "resume blocked precheck only", stage_id=stage_id)
        precheck = _load_json(os.path.join(self.state_dir, "assembler", f"{stage_id}_precheck.json"))
        records: List[EvidenceRecord] = []
        drafts: List[DraftAnswerRecord] = []
        task_results: List[TaskResult] = []
        evidence_by_question = self._store_evidence_by_question(stage_id)
        for fix_round in range(1, self.max_review_fix_rounds + 1):
            if precheck.get("status") != "blocked":
                break
            self.events.emit("assembler_fix_start", f"resume_round={fix_round}", stage_id=stage_id, agent_name="stage_assembler")
            fix_tasks = self._build_precheck_fix_tasks(stage_id, title, precheck, questions)
            if not fix_tasks:
                break
            fix_results, fix_records, fix_drafts = self._run_tasks(stage_id, fix_tasks)
            task_results.extend(fix_results)
            records.extend(fix_records)
            drafts.extend(fix_drafts)
            for rec in fix_records:
                self.evidence_store.append(rec)
            for draft in fix_drafts:
                self.draft_store.append(draft)
            evidence_by_question = self._store_evidence_by_question(stage_id)
            precheck = self._assembler_precheck(stage_id, title, questions, evidence_by_question)
        payload, markdown = self._assemble_stage(stage_id, title, questions, expected_question_ids, evidence_by_question)
        section_path = _section_path(self.repo_output_dir, stage_id, title)
        if markdown and not stage.get("skip_in_report", False):
            with FileLock(lock_path(self.state_dir, "output_write")):
                with open(section_path, "w", encoding="utf-8") as f:
                    f.write(markdown.strip() + "\n")
        review = self._review_stage(stage_id, title, expected_question_ids, payload)
        review_still_needs_fix = bool(self._review_needs_fix(review))
        final_stage_status = "blocked" if precheck.get("status") == "blocked" or review_still_needs_fix else "reviewed"
        block_reason = ""
        if precheck.get("status") == "blocked":
            block_reason = "assembler_precheck"
        elif review_still_needs_fix:
            block_reason = "review_quality"
        blocked_question_ids = list(precheck.get("missing_question_ids") or []) + list(precheck.get("weak_question_ids") or [])
        if review_still_needs_fix:
            blocked_question_ids.extend(self._review_weak_question_ids(review))
        blocked_question_ids = _dedupe_str(blocked_question_ids)
        state_payload = {
            "stage_id": stage_id,
            "stage_title": title,
            "status": final_stage_status,
            "block_reason": block_reason,
            "assembler_precheck_status": precheck.get("status") if precheck else "",
            "review_needs_fix": review_still_needs_fix,
            "review_fix_rounds": 0,
            "blocked_question_ids": blocked_question_ids,
            "task_ids": [r.task_id for r in task_results],
            "evidence_ids": [r.evidence_id for r in records],
            "draft_answer_ids": [d.draft_answer_id for d in drafts],
            "answer_path": os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_answers.json"),
            "section_path": section_path,
            "review_path": os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_review.json") if review else "",
            "updated_at": utcnow_iso(),
        }
        with FileLock(lock_path(self.state_dir, "output_write")):
            _atomic_save_json(self._stage_state_path(stage_id), state_payload)
            self._save_graph_snapshot_unlocked(status="running", current_stage=stage_id)
        self.events.emit(
            "stage_done",
            f"{title} status={final_stage_status} resume_fix_tasks={len(task_results)}"
            + (f" block_reason={block_reason}" if block_reason else ""),
            stage_id=stage_id,
            metadata={"review_confidence": review.get("confidence") if isinstance(review, dict) else None},
        )

    def _review_needs_fix(self, review: Dict[str, Any]) -> bool:
        if not isinstance(review, dict) or not review:
            return False
        try:
            conf = float(review.get("confidence"))
            if conf < 0.75:
                return True
        except Exception:
            pass
        for item in review.get("question_reviews", []) if isinstance(review.get("question_reviews"), list) else []:
            if not isinstance(item, dict):
                continue
            try:
                if float(item.get("score_evidence")) < 0.75:
                    return True
            except Exception:
                continue
        return False

    def _review_weak_question_ids(self, review: Dict[str, Any]) -> List[str]:
        if not isinstance(review, dict):
            return []
        weak: List[str] = []
        for item in review.get("question_reviews", []) if isinstance(review.get("question_reviews"), list) else []:
            if not isinstance(item, dict):
                continue
            qid = str(item.get("question_id") or "").strip()
            if not qid:
                continue
            try:
                score_evidence = float(item.get("score_evidence"))
            except Exception:
                score_evidence = 0.0
            try:
                score_consistency = float(item.get("score_consistency"))
            except Exception:
                score_consistency = 1.0
            if score_evidence < 0.75 or score_consistency < 0.75:
                weak.append(qid)
        return _dedupe_str(weak)

    def _refresh_weak_evidence(self, stage_id: str, weak_qids: List[str], max_chars: int = 2000) -> None:
        """fix round 前对低分题目的证据从源文件重读 excerpt，覆盖截断的快照。"""
        for qid in weak_qids:
            for rec in self.evidence_store.by_question(stage_id, qid):
                if not (rec.path and rec.line_start and rec.line_end):
                    continue
                full_path = os.path.join(self.repo_path, rec.path)
                if not os.path.isfile(full_path):
                    continue
                try:
                    with open(full_path, encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    chunk = "".join(lines[rec.line_start - 1 : rec.line_end])[:max_chars]
                    if chunk and chunk != rec.excerpt:
                        rec.excerpt = chunk
                        self.evidence_store.append(rec)
                except Exception:
                    continue

    def _build_fix_tasks(
        self,
        stage_id: str,
        title: str,
        review: Dict[str, Any],
        questions: List[Dict[str, Any]],
    ) -> List[TaskSpec]:
        qmap = {str(q.get("question_id")): q for q in questions if isinstance(q, dict)}
        review_by_qid: Dict[str, Dict[str, Any]] = {}
        for item in review.get("question_reviews", []) if isinstance(review.get("question_reviews"), list) else []:
            if not isinstance(item, dict):
                continue
            qid = str(item.get("question_id") or "")
            if qid:
                review_by_qid[qid] = item
        finding_messages: Dict[str, List[str]] = {}
        for finding in review.get("findings", []) if isinstance(review.get("findings"), list) else []:
            if not isinstance(finding, dict):
                continue
            
            # 健壮提取受影响的题号：支持 question_id (单数)、qid 以及 affected_question_ids (列表/字符串)
            qids: List[str] = []
            if "question_id" in finding:
                qids.append(str(finding.get("question_id") or "").strip())
            if "qid" in finding:
                qids.append(str(finding.get("qid") or "").strip())
            
            affected = finding.get("affected_question_ids") or finding.get("question_ids")
            if isinstance(affected, list):
                for x in affected:
                    qids.append(str(x or "").strip())
            elif isinstance(affected, str):
                qids.append(affected.strip())
                
            qids = _dedupe_str([q for q in qids if q])
            
            # 健壮提取缺陷描述：支持 message、description 和 text
            msg = str(finding.get("message") or finding.get("description") or finding.get("text") or "").strip()
            if msg:
                for qid in qids:
                    finding_messages.setdefault(qid, []).append(msg)

        weak_qids: List[str] = []
        for qid, item in review_by_qid.items():
            try:
                score = float(item.get("score_evidence"))
            except Exception:
                score = 0.0
            if score < 0.75:
                weak_qids.append(qid)
        for qid in finding_messages:
            if qid not in weak_qids and qid in qmap:
                weak_qids.append(qid)
        if not weak_qids:
            return []

        self._refresh_weak_evidence(stage_id, weak_qids)

        tasks: List[TaskSpec] = []
        for qid in weak_qids[:6]:
            question = qmap.get(qid)
            if not question:
                continue
            review_item = review_by_qid.get(qid, {})
            messages = finding_messages.get(qid, [])
            task = self._build_targeted_review_fix_task(
                stage_id=stage_id,
                title=title,
                question=question,
                review_item=review_item,
                finding_messages=messages,
            )
            if task is not None:
                tasks.append(task)
        return tasks

    def _build_targeted_review_fix_task(
        self,
        *,
        stage_id: str,
        title: str,
        question: Dict[str, Any],
        review_item: Dict[str, Any],
        finding_messages: List[str],
    ) -> Optional[TaskSpec]:
        qid = str(question.get("question_id") or "").strip()
        if not qid:
            return None
        fix_hints = review_item.get("fix_hints") if isinstance(review_item.get("fix_hints"), dict) else {}
        finding_type = str(fix_hints.get("finding_type") or "").strip().lower()
        try:
            score_evidence = float(review_item.get("score_evidence"))
        except Exception:
            score_evidence = 0.0
        try:
            score_consistency = float(review_item.get("score_consistency"))
        except Exception:
            score_consistency = 1.0

        # contract_only 是格式/schema 问题，Task Agent 无法修正，跳过生成任务
        if finding_type == "contract_only" and score_evidence >= 0.75:
            self.events.emit(
                "review_fix_skipped",
                f"{qid} contract_only finding with score_evidence={score_evidence:.2f}; skipping fix task",
                stage_id=stage_id,
                agent_name="stage_assembler",
            )
            return None

        review_text = str(review_item.get("review") or "")

        combined_review = "\n".join([review_text] + [m for m in finding_messages if m])
        keywords = self._targeted_fix_keywords(question, fix_hints, combined_review)
        seed_paths = self._targeted_fix_seed_paths(stage_id, question, fix_hints, combined_review)
        expected = self._targeted_fix_evidence_types(question, fix_hints, combined_review)
        task_type = self._targeted_fix_task_type(combined_review, expected)
        issue_summary = combined_review.strip()[:500] or "Review 指出该题证据支撑不足。"
        goal = str(fix_hints.get("fix_goal") or "").strip()
        if not goal:
            goal = (
                f"针对 Review 发现补证据：{issue_summary}\n"
                f"请围绕关键词 {', '.join(keywords[:12]) or '题面关键词'} 在指定路径内查找 definition/implementation/call-site。"
            )
        if any(x in combined_review for x in ("未搜索", "未找到", "未发现", "无法支撑", "not_found")):
            goal += "\n如果仍然找不到实现，必须给出针对这些关键词和路径的负向搜索证据，而不是只搜索 notes/not_found。"
        query_parts = [
            str(question.get("stem") or ""),
            " ".join(keywords),
            issue_summary,
        ]
        task = TaskSpec(
            task_id=f"task_{stage_id}_{qid}_review_fix_{uuid.uuid4().hex[:6]}",
            stage_id=stage_id,
            question_id=qid,
            question_ids=[qid],
            task_type=task_type,
            agent_type=task_type,
            task_goal=goal,
            query="\n".join(p for p in query_parts if p).strip(),
            seed_paths=seed_paths,
            entry_symbols=keywords[:20],
            expected_evidence_types=expected,
            metadata={
                "fix_reason": "review_targeted_evidence",
                "trigger_review_id": f"{stage_id}:{qid}:review_fix",
                "review_score_evidence": score_evidence,
                "review_score_consistency": score_consistency,
                "review_text": review_text,
                "finding_messages": finding_messages,
                "fix_hints": fix_hints,
                "finding_type": finding_type,
                "fix_goal": goal,
                "keywords": keywords,
            },
        )
        return task

    def _targeted_fix_keywords(self, question: Dict[str, Any], fix_hints: Dict[str, Any], review_text: str) -> List[str]:
        out: List[str] = []
        out.extend(_list_str(fix_hints.get("recommended_keywords"), 30))
        hints = question.get("task_hints") if isinstance(question.get("task_hints"), dict) else {}
        out.extend(_list_str(hints.get("keywords"), 20))
        out.extend(_list_str(hints.get("entry_symbols"), 20))
        stem = str(question.get("stem") or "")
        text = "\n".join([stem, review_text])
        protocol_keywords = [
            "Ethernet", "ARP", "IPv4", "IPv6", "ICMP", "UDP", "TCP", "DHCP", "DNS",
            "socket", "bind", "connect", "sendto", "recvfrom", "send", "recv",
            "virtio-net", "virtio_net", "e1000", "netif", "net_tx", "net_rx",
            "udp_send", "tcp_send", "ip_output", "lwip", "smoltcp",
            "zero_copy", "DMA", "descriptor",
        ]
        for kw in protocol_keywords:
            if kw.lower() in text.lower():
                out.append(kw)
        for token in re.findall(r"`([^`]{2,80})`|'([^']{2,80})'|\"([^\"]{2,80})\"|([A-Za-z_][A-Za-z0-9_\-]{2,})", text):
            raw = next((part for part in token if part), "")
            if raw:
                out.append(raw)
        banned = {
            "notes", "not_found", "implemented", "stub", "value", "score_evidence", "score_consistency",
            "evidence", "review", "question", "answer", "confidence", "warning", "warn",
            "JSON", "Agent", "Review", "Task", "not", "found", "choices", "choice",
            "未发现", "题面", "答案", "证据", "契约",
        }
        cleaned: List[str] = []
        seen = set()
        for item in out:
            item = str(item).strip().strip("，。；:：,.()[]{}")
            if not item or item in banned or item.lower() in {b.lower() for b in banned}:
                continue
            low_item = item.lower()
            if re.match(r"^Q\d+_\d+$", item) or "未发现" in item or "仅有名词" in item:
                continue
            if any(bad in low_item for bad in ("notes", "not_found", "score_", "question_", "answer_", "value=")):
                continue
            if len(item) > 40:
                continue
            key = item.lower()
            if key not in seen:
                seen.add(key)
                cleaned.append(item)
        return cleaned[:24]

    def _targeted_fix_seed_paths(self, stage_id: str, question: Dict[str, Any], fix_hints: Dict[str, Any], review_text: str) -> List[str]:
        out: List[str] = []
        out.extend(_list_str(fix_hints.get("recommended_seed_paths"), 20))
        hints = question.get("task_hints") if isinstance(question.get("task_hints"), dict) else {}
        out.extend(_list_str(hints.get("seed_paths"), 20))
        if "network" in stage_id or any(x in review_text.lower() for x in ["tcp", "udp", "socket", "protocol", "net"]):
            out.extend(["net", "network", "socket", "syscall", "src", "kernel", "drivers", "lwip", "smoltcp"])
        if any(x in review_text.lower() for x in ["virtio", "e1000", "dma", "driver", "interrupt"]):
            out.extend(["drivers", "device", "devices", "virtio", "src/sifive", "src/include"])
        if any(x in review_text.lower() for x in ["sendto", "call", "path", "调用", "路径"]):
            out.extend(["syscall", "net", "socket", "src"])
        if not out:
            out.extend(["src", "kernel"])
        seen = set()
        cleaned: List[str] = []
        for item in out:
            item = str(item).strip().strip("/\\")
            if item and item.lower() not in seen:
                seen.add(item.lower())
                cleaned.append(item)
        return cleaned[:20]

    def _targeted_fix_evidence_types(self, question: Dict[str, Any], fix_hints: Dict[str, Any], review_text: str) -> List[str]:
        out = _list_str(fix_hints.get("missing_evidence_types"), 12)
        policy = question.get("evidence_policy") if isinstance(question.get("evidence_policy"), dict) else {}
        out.extend(_list_str(policy.get("required_evidence_types"), 12))
        text = review_text.lower()
        if any(x in text for x in ["call", "调用", "路径", "sendto", "trace"]):
            out.extend(["definition", "call_site", "usage_flow"])
        if any(x in text for x in ["实现", "implementation", "body", "stub", "桩"]):
            out.extend(["definition", "implementation_body"])
        if any(x in text for x in ["未搜索", "关键词", "protocol", "协议"]):
            out.extend(["search", "definition", "implementation_body"])
        if not out:
            out = ["search", "definition", "implementation_body"]
        return _dedupe_str(out)[:12]

    def _targeted_fix_task_type(self, review_text: str, expected: List[str]) -> str:
        text = review_text.lower()
        if any(x in expected for x in ["call_site", "usage_flow"]) or any(x in text for x in ["call_graph", "调用", "路径", "trace", "sendto"]):
            return "react_lsp"
        return "react_code"

    def _run_stage_plan_agent(
        self,
        stage_id: str,
        title: str,
        questions: List[Dict[str, Any]],
        plan: Any,
        repo_profile: Dict[str, Any],
        force: bool = False,
    ) -> Dict[str, Any]:
        if not questions:
            return {"task_plan": []}
            
        plan_path = os.path.join(self.state_dir, "stages", f"{stage_id}_task_plan_raw.json")
        if not force and os.path.exists(plan_path):
            try:
                cached = _load_json(plan_path)
                if cached and "parsed" in cached and isinstance(cached["parsed"], dict):
                    self.events.emit("stage_plan_skip", "using cached task plan", stage_id=stage_id, agent_name="stage_plan_agent")
                    return cached["parsed"]
            except Exception:
                pass

        self.events.emit("stage_plan_start", "planning grouped tasks", stage_id=stage_id, agent_name="stage_plan_agent")
        prompt = self._stage_task_planner_prompt(stage_id, title, questions, plan, repo_profile)
        raw = self._invoke_llm(prompt, stage_id=stage_id, agent_name="stage_plan_agent")
        parsed = extract_json_object(raw) or {}
        task_plan = parsed.get("task_plan") if isinstance(parsed.get("task_plan"), list) else []
        if not task_plan:
            self.events.emit("stage_plan_empty", "LLM returned no task_plan", stage_id=stage_id, agent_name="stage_plan_agent", level="warn")
        self.events.emit("stage_plan_done", f"task_plan={len(task_plan)}", stage_id=stage_id, agent_name="stage_plan_agent")
        with FileLock(lock_path(self.state_dir, "output_write")):
            _atomic_save_json(
                os.path.join(self.state_dir, "stages", f"{stage_id}_task_plan_raw.json"),
                {"raw": raw, "parsed": parsed, "task_plan_count": len(task_plan)},
            )
        return parsed if isinstance(parsed, dict) else {"task_plan": []}

    def _stage_task_planner_prompt(
        self,
        stage_id: str,
        title: str,
        questions: List[Dict[str, Any]],
        plan: Any,
        repo_profile: Dict[str, Any],
    ) -> str:
        q_payload = [
            {
                "question_id": q.get("question_id"),
                "question_type": q.get("question_type"),
                "stem": q.get("stem"),
                "choices": q.get("choices"),
                "feature_ids": q.get("feature_ids"),
                "tri_state_rule": q.get("tri_state_rule"),
                "anti_examples": q.get("anti_examples"),
                "diagnostic_checks": q.get("diagnostic_checks"),
                "structured_facts": q.get("structured_facts"),
                "answer_contract": q.get("answer_contract"),
                "concept_boundary": q.get("concept_boundary"),
                "llm_answer_steps": q.get("llm_answer_steps"),
                "evidence_policy": q.get("evidence_policy"),
                "task_hints": q.get("task_hints"),
            }
            for q in questions
        ]
        return (
            "你是 OS-Agent D 的 Stage Plan Agent。你的任务是把当前 stage 的题单划分为 grouped Task，供后续 LLM ReAct Task Agent 查证据并产草稿答案。\n"
            "只输出一个 JSON 对象，不要 Markdown 围栏，不要解释。\n\n"
            "规划原则：\n"
            "- 相近题可以放入同一个 task，由你根据共享证据链、实现路径和上下文规模决定分组大小。\n"
            "- 按共享 seed_paths、entry_symbols、证据类型、同一实现链路来合并。\n"
            "- 高风险或互斥判断题不要合并过大。\n"
            "- task_goal 必须具体到要查什么证据，不要写泛泛的“分析代码”。\n"
            "- agent_type 只能是 react_code（通用，支持代码搜索/LSP/RAG/构建系统分析）或 react_history（仅限 Git 历史题）。\n"
            "- 绝大多数题用 react_code；只有 stage_id 含 '10_history' 或题目明确要求 Git 提交历史时才用 react_history。\n"
            "- expected_evidence_types 使用 definition / implementation_body / call_site / usage_flow / build_config / git_history / search。\n\n"
            "QA Contract 约束：\n"
            "- tri_state_impl 题需要按 feature 的 required_evidence_types 和 negative_search_policy 规划任务。\n"
            f"{field_guidance(['structured_facts', 'answer_contract', 'concept_boundary', 'diagnostic_checks', 'tri_state_rule', 'anti_examples', 'evidence_policy', 'llm_answer_steps', 'choices'])}"
            "- 每个 task 必须能填充相关题目的 structured_facts；task_goal/query 需要写明要完成哪些 fact_id/fact_key。\n"
            "- 对包含 diagnostic_checks 的复杂题，必须把局部判断步骤反映到 task_goal/query 中，不能只问“是否实现”。\n"
            f"{evidence_discipline_guidance()}\n"
            f"stage_id={stage_id}\nstage_title={title}\n\n"
            "## Heuristic PlanSpec\n"
            f"{json.dumps(plan.to_dict() if hasattr(plan, 'to_dict') else {}, ensure_ascii=False, indent=2)}\n\n"
            "## Repo Profile Summary\n"
            f"{json.dumps({k: repo_profile.get(k) for k in ['framework_guess', 'arch_guess', 'core_paths', 'build_files']}, ensure_ascii=False, indent=2)}\n\n"
            "## Question Sheet\n"
            f"{json.dumps(q_payload, ensure_ascii=False, indent=2)}\n\n"
            "输出格式：\n"
            "{\n"
            '  "task_plan": [\n'
            "    {\n"
            '      "task_id": "task_<stage>_<short_name>",\n'
            '      "question_ids": ["Qxx_001"],\n'
            '      "task_type": "react_code",\n'
            '      "agent_type": "react_code",\n'
            '      "task_goal": "查证某机制是否实现，并找到定义/实现体/调用点",\n'
            '      "group_reason": "这些题共享同一实现线索",\n'
            '      "query": "自然语言检索/分析目标",\n'
            '      "seed_paths": ["mm", "kernel"],\n'
            '      "entry_symbols": ["alloc_page"],\n'
            '      "expected_evidence_types": ["definition", "implementation_body"]\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )

    def _run_tasks(self, stage_id: str, tasks: List[TaskSpec], *, force: bool = False) -> Tuple[List[TaskResult], List[EvidenceRecord], List[DraftAnswerRecord]]:
        results: List[TaskResult] = []
        records: List[EvidenceRecord] = []
        drafts: List[DraftAnswerRecord] = []
        pending = list(tasks) if force else [t for t in tasks if _load_json(self._task_state_path(t.task_id)).get("status") != "done"]
        skipped = 0 if force else len(tasks) - len(pending)
        if skipped:
            self.events.emit("task_skip", f"reuse {skipped} completed task(s)", stage_id=stage_id)
        self.events.emit("task_dispatch", f"dispatch {len(pending)} task(s)", stage_id=stage_id)
        with ThreadPoolExecutor(max_workers=self.max_parallel_tasks) as pool:
            futures = {pool.submit(self._run_one_task_with_limits, t): t for t in pending}
            for future in as_completed(futures):
                task = futures[future]
                result, evs, task_drafts = future.result()
                results.append(result)
                records.extend(evs)
                drafts.extend(task_drafts)
                with FileLock(lock_path(self.state_dir, "output_write")):
                    _atomic_save_json(self._task_state_path(task.task_id), result.to_dict())
                self.events.emit(
                    "task_done" if result.status == "done" else "task_error",
                    f"{task.task_type} evidence={len(evs)} confidence={result.confidence}",
                    stage_id=task.stage_id,
                    task_id=task.task_id,
                    agent_name=f"{task.task_type}_agent",
                    level="info" if result.status == "done" else "warn",
                    metadata={"question_ids": task.question_ids or ([task.question_id] if task.question_id else [])},
                )
        return results, records, drafts

    def _run_one_task_with_limits(self, task: TaskSpec) -> Tuple[TaskResult, List[EvidenceRecord], List[DraftAnswerRecord]]:
        max_retries = int(os.environ.get("OS_AGENT_TASK_RETRIES", "1"))
        with task_event_context(
            self.events,
            stage_id=task.stage_id,
            task_id=task.task_id,
            agent_name=f"{task.task_type}_agent",
        ):
            self.events.emit(
                "task_start",
                task.task_goal or task.query or task.task_type,
                stage_id=task.stage_id,
                task_id=task.task_id,
                agent_name=f"{task.task_type}_agent",
                metadata={"question_ids": task.question_ids or ([task.question_id] if task.question_id else [])},
            )
            result: Tuple[TaskResult, List[EvidenceRecord], List[DraftAnswerRecord]] | None = None
            for attempt in range(max_retries + 1):
                result = run_task_agent(task, repo_path=self.repo_path)
                if result[0].status == "done" or attempt == max_retries:
                    break
                self.events.emit(
                    "task_retry",
                    f"attempt {attempt + 1}/{max_retries} failed ({', '.join(result[0].errors or ['unknown'])}), retrying",
                    stage_id=task.stage_id,
                    task_id=task.task_id,
                    agent_name=f"{task.task_type}_agent",
                    level="warn",
                )
                time.sleep(2 ** attempt)
            return result

    def _assembler_precheck(
        self,
        stage_id: str,
        title: str,
        questions: List[Dict[str, Any]],
        evidence_by_question: Dict[str, List[EvidenceRecord]],
    ) -> Dict[str, Any]:
        draft_by_question = self.draft_store.grouped_by_question(stage_id)
        missing: List[str] = []
        weak: List[str] = []
        for q in questions:
            qid = str(q.get("question_id", "")).strip()
            if not qid:
                continue
            evs = [
                e
                for e in evidence_by_question.get(qid, [])
                if e.validity != "invalid" or _is_good_negative_search_evidence(e)
            ]
            drafts = draft_by_question.get(qid, [])
            if not evs or not drafts:
                missing.append(qid)
            elif not self._question_has_schema_sufficient_evidence(q, evs):
                weak.append(qid)
        status = "pass" if not missing and not weak else "blocked"
        precheck = {
            "stage_id": stage_id,
            "stage_title": title,
            "status": status,
            "missing_question_ids": missing,
            "weak_question_ids": weak,
            "covered_question_ids": [
                str(q.get("question_id"))
                for q in questions
                if str(q.get("question_id")) not in set(missing + weak)
            ],
            "updated_at": utcnow_iso(),
        }
        with FileLock(lock_path(self.state_dir, "output_write")):
            _atomic_save_json(os.path.join(self.state_dir, "assembler", f"{stage_id}_precheck.json"), precheck)
        self.events.emit(
            "assembler_precheck",
            f"{status} missing={len(missing)} weak={len(weak)} missing_qids={missing} weak_qids={weak}",
            stage_id=stage_id,
            agent_name="stage_assembler",
            level="info" if status == "pass" else "warn",
        )
        return precheck

    def _question_has_schema_sufficient_evidence(self, question: Dict[str, Any], evidence: List[EvidenceRecord]) -> bool:
        qtype = str(question.get("question_type") or "").strip()
        if not evidence:
            return False
        if qtype == "tri_state_impl":
            return any(
                evidence_can_support_claim(evidence, claim)
                for claim in ("implemented", "stub", "not_found")
            )
        return any(
            e.validity != "invalid" and e.strength in {"weak", "strong"}
            for e in evidence
        )

    def _assemble_stage(
        self,
        stage_id: str,
        title: str,
        questions: List[Dict[str, Any]],
        expected_question_ids: List[str],
        evidence_by_question: Dict[str, List[EvidenceRecord]],
        review_fix_records: Optional[List[EvidenceRecord]] = None,
        review_fix_round: int = 0,
    ) -> Tuple[Dict[str, Any], str]:
        self.events.emit("assembler_start", "assembling task drafts", stage_id=stage_id, agent_name="stage_assembler")
        draft_by_question = self.draft_store.grouped_by_question(stage_id)
        answers: List[Dict[str, Any]] = []
        raw_parts: List[str] = []
        for idx, question in enumerate(questions, 1):
            qid = str(question.get("question_id", "")).strip()
            evs = evidence_by_question.get(qid, [])
            drafts = draft_by_question.get(qid, [])
            prompt = self._one_question_assembler_prompt(stage_id, title, question, evs, drafts, idx, len(questions))
            answer, raw_log = self._ask_one_question_json_with_retry(
                stage_id=stage_id,
                title=title,
                question=question,
                evidence=evs,
                prompt=prompt,
                agent_name="stage_assembler",
                drafts=drafts,
            )
            raw_parts.append(f"--- {qid} ---\n{raw_log}")
            answers.append(answer)
        payload = {
            "schema_version": JSON_QA_SCHEMA_VERSION,
            "stage_id": stage_id,
            "stage_title": title,
            "terminology_profile": "stallings_en_zh",
            "answers": answers,
        }
        self._annotate_review_fix_effect(payload, review_fix_records or [], review_fix_round)
        
        stage_qa = None
        try:
            stage_qa = load_stage_qa(stage_id)
            payload = coerce_answers_payload_by_stage_qa(payload, stage_qa=stage_qa)
            issues = validate_answers_payload(
                payload,
                stage_id=stage_id,
                stage_title=title,
                expected_question_ids=expected_question_ids,
                stage_qa=stage_qa,
            )
            if issues:
                self.events.emit("assembler_json_invalid", f"validation issues={len(issues)}; keeping fallback-safe payload", stage_id=stage_id, level="warn")
        except Exception as exc:
            self.events.emit("assembler_json_invalid", f"{type(exc).__name__}: {exc}", stage_id=stage_id, level="warn")
            
        markdown = ""  # 02-09 章不再生成 md，直接由 publish_html_report 从 answers.json 渲染
        sidecar = os.path.join(self.repo_output_dir, "_per_stage")
        with FileLock(lock_path(self.state_dir, "output_write")):
            _atomic_save_json(os.path.join(sidecar, f"{stage_id}_answers.json"), payload)
            _atomic_save_json(os.path.join(self.state_dir, "assembler", f"{stage_id}_assembled.json"), payload)
            with open(os.path.join(sidecar, f"{stage_id}_answers_raw.txt"), "w", encoding="utf-8") as f:
                f.write("\n\n".join(raw_parts).strip() + "\n")
        return payload, markdown

    def _annotate_review_fix_effect(
        self,
        payload: Dict[str, Any],
        review_fix_records: List[EvidenceRecord],
        review_fix_round: int,
    ) -> None:
        if not review_fix_records or not isinstance(payload.get("answers"), list):
            return
        by_qid: Dict[str, Dict[str, Any]] = {}
        for rec in review_fix_records:
            if "_review_fix_" not in str(rec.task_id or ""):
                continue
            for qid in rec.question_ids or []:
                item = by_qid.setdefault(
                    str(qid),
                    {
                        "round": review_fix_round,
                        "task_ids": [],
                        "new_evidence_ids": [],
                    },
                )
                if rec.task_id and rec.task_id not in item["task_ids"]:
                    item["task_ids"].append(rec.task_id)
                if rec.evidence_id and rec.evidence_id not in item["new_evidence_ids"]:
                    item["new_evidence_ids"].append(rec.evidence_id)
        if not by_qid:
            return
        for answer in payload.get("answers") or []:
            if not isinstance(answer, dict):
                continue
            qid = str(answer.get("question_id") or "")
            fix = by_qid.get(qid)
            if not fix:
                continue
            used = set(str(x) for x in answer.get("used_evidence_ids", []) if str(x))
            for fact in answer.get("fact_answers", []) if isinstance(answer.get("fact_answers"), list) else []:
                if isinstance(fact, dict) and isinstance(fact.get("used_evidence_ids"), list):
                    used.update(str(x) for x in fact.get("used_evidence_ids") if str(x))
            new_ids = set(fix.get("new_evidence_ids") or [])
            fix["affected_final_value"] = bool(used & new_ids)
            _set_meta_path(answer, ["review_fix"], dict(fix))

    def _one_question_assembler_prompt(
        self,
        stage_id: str,
        title: str,
        question: Dict[str, Any],
        evidence: List[EvidenceRecord],
        drafts: List[DraftAnswerRecord],
        idx: int,
        total: int,
    ) -> str:
        ev_payload = [
            {
                "evidence_id": r.evidence_id,
                "path": r.path,
                "symbol": r.symbol,
                "source_type": r.source_type,
                "evidence_type": r.evidence_type,
                "confidence": r.confidence,
                "strength": r.strength,
                "supports_claim_types": r.supports_claim_types,
                "validity": r.validity,
                "excerpt": (r.excerpt or "")[:1200],
            }
            for r in evidence[:10]
        ]
        draft_payload = [
            {
                "draft_answer_id": d.draft_answer_id,
                "task_id": d.task_id,
                "confidence": d.confidence,
                "used_evidence_ids": d.used_evidence_ids,
                "answer": d.answer,
                "notes": d.notes,
            }
            for d in drafts[:6]
        ]
        return (
            "你是 OS-Agent D 的 Stage Assembler Agent。现在只组装一个小题的最终 JSON answer。\n"
            "你不是源码分析执行者，不能发明新事实；只能根据 Task draft 和 Bound Evidence 统一格式、去重、修正过度表述。\n"
            "只输出一个 JSON object，字段必须是 question_id, question_type, stem, fact_answers, value, used_evidence_ids, notes。\n"
            f"{field_guidance(['structured_facts', 'answer_contract', 'concept_boundary', 'tri_state_rule', 'anti_examples', 'choices'])}"
            f"{answer_shape_guidance()}"
            "tri_state_impl 判定必须遵守 Question 中的 tri_state_rule 和 anti_examples：没有 strong implementation evidence 时不能写 implemented；负向搜索覆盖不足时不能写 not_found。\n"
            "你能看到并引用的证据列表只有下方 ## Bound Evidence；Task Drafts 里的旧 evidence/path/excerpt 不能作为最终证据，必须回到 Bound Evidence 找 ID。\n"
            "single_choice 的 value 必须等于 choices 中某一项完整原文；multi_choice 的 value 必须是数组。\n"
            "如果 draft 与 evidence 不一致，以 evidence 为准；证据不足写 unknown/待核实。\n\n"
            f"stage_id={stage_id}\nstage_title={title}\nquestion_index={idx}/{total}\n\n"
            "## Question\n"
            f"{json.dumps(question, ensure_ascii=False, indent=2)}\n\n"
            "## Task Drafts\n"
            f"{json.dumps(draft_payload, ensure_ascii=False, indent=2)}\n\n"
            "## Bound Evidence\n"
            f"{json.dumps(ev_payload, ensure_ascii=False, indent=2)}\n"
        )

    def _write_stage(
        self,
        stage_id: str,
        title: str,
        questions: List[Dict[str, Any]],
        expected_question_ids: List[str],
        evidence_by_question: Dict[str, List[EvidenceRecord]],
    ) -> Tuple[Dict[str, Any], str]:
        self.events.emit("writer_start", "writing stage output", stage_id=stage_id, agent_name="stage_writer")
        evidence_summary = self._evidence_summary_for_prompt(evidence_by_question)
        if questions:
            payload, raw = self._write_questions_json(
                stage_id,
                title,
                questions,
                expected_question_ids,
                evidence_by_question,
            )
            sidecar = os.path.join(self.repo_output_dir, "_per_stage")
            with FileLock(lock_path(self.state_dir, "output_write")):
                _atomic_save_json(os.path.join(sidecar, f"{stage_id}_answers.json"), payload)
                with open(os.path.join(sidecar, f"{stage_id}_answers_raw.txt"), "w", encoding="utf-8") as f:
                    f.write(raw.strip() + "\n")
            return payload, ""  # markdown 不再生成
        prompt = self._markdown_writer_prompt(stage_id, title, evidence_summary)
        if stage_id == "01_overview":
            prompt += "\n\n## 前置章节摘要\n" + self._load_previous_sections_text()
        markdown = self._invoke_llm(prompt, stage_id=stage_id, agent_name="stage_writer")
        return {}, _coerce_markdown_writer_output(markdown)

    def _invoke_llm(self, prompt: str, *, stage_id: str, agent_name: str) -> str:
        from core.agent_builder import build_chat_model
        from core.utils import safe_llm_invoke

        role = "planner" if agent_name == "stage_plan_agent" else "task"
        self.events.emit("llm_start", agent_name, stage_id=stage_id, agent_name=agent_name)
        llm = build_chat_model(temperature=0, role=role)
        try:
            msg = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        except Exception as e:
            self.events.emit("llm_error", f"LLM invoke failed completely: {e}", stage_id=stage_id, agent_name=agent_name)
            raise e
        usage = getattr(msg, "response_metadata", {}).get("token_usage", {}) or {}
        self.events.emit("llm_done", agent_name, stage_id=stage_id, agent_name=agent_name, token_usage=usage)
        cot = (getattr(msg, "additional_kwargs", {}) or {}).get("reasoning_content") or ""
        if cot:
            self.events.emit_debug("llm_reasoning", agent_name,
                stage_id=stage_id, agent_name=agent_name,
                metadata={"reasoning_content": cot})
        return (getattr(msg, "content", "") or "").strip()


    def _json_writer_prompt(
        self,
        stage_id: str,
        title: str,
        questions: List[Dict[str, Any]],
        evidence_summary: str,
    ) -> str:
        return (
            "你是 OS-Agent D 的 Stage Writer Agent。只根据给定 evidence 作答，不要声称 evidence 未支持的实现事实。\n"
            "最终只输出一个合法 JSON 对象，字段为 schema_version, stage_id, stage_title, terminology_profile, answers。\n"
            "answers 必须按题单顺序逐题回答，每题包含 question_id, question_type, stem, fact_answers, value, used_evidence_ids, notes。\n"
            f"{field_guidance(['structured_facts', 'answer_contract', 'concept_boundary', 'tri_state_rule', 'anti_examples', 'choices'])}"
            f"{answer_shape_guidance()}"
            "若题目含 structured_facts/answer_contract，必须逐项输出 fact_answers；自然语言只能作为 notes，不得替代事实字段。\n"
            "每个 fact_answers item 必须包含 fact_id, fact_key, value, used_evidence_ids, notes；value 只能由 fact_answers 推出。\n"
            "你能看到并引用的证据列表只有下方 ## Evidence By Question；每个 answer 只能引用本 question_id 分组下的 evidence_id。\n"
            "RAG/grep 只能作为 hint，不能单独支撑 implemented。\n\n"
            f"stage_id={stage_id}\nstage_title={title}\n\n"
            "## 题单\n"
            f"{json.dumps(questions, ensure_ascii=False, indent=2)}\n\n"
            "## Evidence By Question\n"
            f"{evidence_summary}\n\n"
            "若证据不足，value 写 unknown/待核实，并在 notes 中记录缺口。"
        )

    def _write_questions_json(
        self,
        stage_id: str,
        title: str,
        questions: List[Dict[str, Any]],
        expected_question_ids: List[str],
        evidence_by_question: Dict[str, List[EvidenceRecord]],
    ) -> Tuple[Dict[str, Any], str]:
        answers: List[Dict[str, Any]] = []
        raw_parts: List[str] = []
        for idx, question in enumerate(questions, 1):
            qid = str(question.get("question_id", "")).strip()
            evs = evidence_by_question.get(qid, [])
            prompt = self._one_question_writer_prompt(stage_id, title, question, evs, idx, len(questions))
            answer, raw_log = self._ask_one_question_json_with_retry(
                stage_id=stage_id,
                title=title,
                question=question,
                evidence=evs,
                prompt=prompt,
                agent_name="stage_writer",
            )
            raw_parts.append(f"--- {qid} ---\n{raw_log}")
            answers.append(answer)
        payload = {
            "schema_version": JSON_QA_SCHEMA_VERSION,
            "stage_id": stage_id,
            "stage_title": title,
            "terminology_profile": "stallings_en_zh",
            "answers": answers,
        }
        try:
            stage_qa = load_stage_qa(stage_id)
            payload = coerce_answers_payload_by_stage_qa(payload, stage_qa=stage_qa)
            issues = validate_answers_payload(
                payload,
                stage_id=stage_id,
                stage_title=title,
                expected_question_ids=expected_question_ids,
                stage_qa=stage_qa,
            )
            if issues:
                self.events.emit("writer_json_invalid", f"merged validation issues={len(issues)}; keeping per-question fallback-safe payload", stage_id=stage_id, level="warn")
        except Exception as exc:
            self.events.emit("writer_json_invalid", f"merged validation failed: {type(exc).__name__}: {exc}", stage_id=stage_id, level="warn")
        return payload, "\n\n".join(raw_parts)

    def _one_question_writer_prompt(
        self,
        stage_id: str,
        title: str,
        question: Dict[str, Any],
        evidence: List[EvidenceRecord],
        idx: int,
        total: int,
    ) -> str:
        ev_payload = [
            {
                "evidence_id": r.evidence_id,
                "path": r.path,
                "symbol": r.symbol,
                "source_type": r.source_type,
                "evidence_type": r.evidence_type,
                "confidence": r.confidence,
                "strength": r.strength,
                "supports_claim_types": r.supports_claim_types,
                "validity": r.validity,
                "excerpt": (r.excerpt or "")[:1200],
            }
            for r in evidence[:8]
        ]
        return (
            "你是 OS-Agent D 的 Stage Writer Agent。现在只回答一个小题。\n"
            "只能输出一个 JSON object，字段必须是 question_id, question_type, stem, fact_answers, value, used_evidence_ids, notes。\n"
            "不要输出 Markdown，不要围栏，不要解释。\n"
            f"{field_guidance(['structured_facts', 'answer_contract', 'concept_boundary', 'tri_state_rule', 'anti_examples', 'choices'])}"
            f"{answer_shape_guidance()}"
            "tri_state_impl 不能由 RAG/grep hint 直接判 implemented；证据不足写 unknown。\n"
            "你能看到并引用的证据列表只有下方 ## Bound Evidence；没有出现在该列表中的证据不可引用。\n"
            "single_choice 的 value 必须等于 choices 中某一项完整原文；multi_choice 的 value 必须是数组。\n"
            "证据不足时写 unknown/待核实，不能编造路径。\n\n"
            f"stage_id={stage_id}\nstage_title={title}\nquestion_index={idx}/{total}\n\n"
            "## Question\n"
            f"{json.dumps(question, ensure_ascii=False, indent=2)}\n\n"
            "## Bound Evidence\n"
            f"{json.dumps(ev_payload, ensure_ascii=False, indent=2)}\n"
        )

    def _parse_one_answer_or_fallback(
        self,
        stage_id: str,
        title: str,
        question: Dict[str, Any],
        raw: str,
        evidence: List[EvidenceRecord],
    ) -> Dict[str, Any]:
        answer, _issues = self._parse_one_answer_candidate(stage_id, title, question, raw, evidence)
        if answer is not None:
            return answer
        return self._fallback_answer(
            question,
            evidence,
            reason="single_answer_parse_failed",
            last_issues=_issues,
            attempts=1,
            raw_model_answer_excerpt=raw or "",
        )

    def _ask_one_question_json_with_retry(
        self,
        *,
        stage_id: str,
        title: str,
        question: Dict[str, Any],
        evidence: List[EvidenceRecord],
        prompt: str,
        agent_name: str,
        drafts: Optional[List[Any]] = None,
    ) -> Tuple[Dict[str, Any], str]:
        qid = str(question.get("question_id") or "").strip()
        max_attempts = _env_int("OS_AGENT_ANSWER_JSON_MAX_ATTEMPTS", 3)
        attempts_raw: List[str] = []
        current_prompt = prompt
        last_issues: List[str] = []
        for attempt in range(1, max_attempts + 1):
            raw = self._invoke_llm(current_prompt, stage_id=stage_id, agent_name=agent_name)
            attempts_raw.append(f"attempt={attempt}\n{raw}")
            answer, issues = self._parse_one_answer_candidate(stage_id, title, question, raw, evidence, drafts=drafts)
            if answer is not None:
                if attempt > 1:
                    self.events.emit(
                        "answer_json_retry_recovered",
                        f"{qid} accepted after attempt {attempt}",
                        stage_id=stage_id,
                        agent_name=agent_name,
                    )
                return answer, "\n\n".join(attempts_raw)

            last_issues = issues
            self.events.emit(
                "answer_json_rejected",
                f"{qid} attempt={attempt} issues={issues[:6]}",
                stage_id=stage_id,
                agent_name=agent_name,
                level="warn",
            )
            if attempt < max_attempts:
                current_prompt = self._answer_retry_prompt(
                    base_prompt=prompt,
                    raw=raw,
                    issues=issues,
                )

        fallback = self._fallback_answer(
            question,
            evidence,
            reason="answer_json_retry_exhausted",
            last_issues=last_issues,
            attempts=max_attempts,
            raw_model_answer_excerpt="\n\n".join(attempts_raw),
        )
        note = f"Answer retry exhausted after {max_attempts} attempts; last issues: {last_issues[:6]}."
        existing = fallback.get("notes")
        fallback["notes"] = f"{existing}\n{note}".strip() if isinstance(existing, str) and existing.strip() else note
        attempts_raw.append(f"fallback_used=true\n{json.dumps(fallback, ensure_ascii=False, indent=2)}")
        return fallback, "\n\n".join(attempts_raw)

    def _answer_retry_prompt(self, *, base_prompt: str, raw: str, issues: List[str]) -> str:
        return (
            f"{base_prompt}\n\n"
            "## 上一次输出被系统拒绝\n"
            "请只重新输出同一个小题的 JSON object，不要 Markdown，不要解释。\n"
            "必须修复以下问题：\n"
            f"{json.dumps(issues[:20], ensure_ascii=False, indent=2)}\n\n"
            "关键硬要求：\n"
            "- 必须包含 fact_answers。\n"
            "- fact_answers 必须覆盖 Question.structured_facts 中每个 fact_id，不能多也不能漏。\n"
            f"{answer_shape_guidance()}"
            "- 没有证据就填 []，不要编 path/line/excerpt。\n"
            "- value 只是 fact_answers 推出的汇总结论。\n\n"
            "## 上一次原始输出\n"
            f"{(raw or '')[:6000]}\n"
        )

    def _parse_one_answer_candidate(
        self,
        stage_id: str,
        title: str,
        question: Dict[str, Any],
        raw: str,
        evidence: List[EvidenceRecord],
        drafts: Optional[List[Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        try:
            text = (raw or "").strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            start = text.find("{")
            if start >= 0:
                decoder = json.JSONDecoder()
                parsed, _ = decoder.raw_decode(text[start:])
            else:
                parsed = json.loads(text)
            if isinstance(parsed, dict):
                raw_answer = copy.deepcopy(parsed)
                candidate = {
                    "schema_version": JSON_QA_SCHEMA_VERSION,
                    "stage_id": stage_id,
                    "stage_title": title,
                    "terminology_profile": "stallings_en_zh",
                    "answers": [parsed],
                }
                candidate = coerce_answers_payload_defaults(candidate)
                pre_issues = validate_answers_payload(
                    candidate,
                    stage_id=stage_id,
                    stage_title=title,
                    expected_question_ids=[str(question.get("question_id") or "").strip()],
                    stage_qa={"questions": [question]},
                )
                if pre_issues:
                    return None, [f"{issue.path}: {issue.reason}" for issue in pre_issues]
                requested_ids = self._extract_requested_evidence_ids(parsed)
                bound_ids = {rec.evidence_id for rec in evidence}
                unknown_ids = [evid for evid in requested_ids if evid not in bound_ids]
                if unknown_ids:
                    return None, [f"used_evidence_ids contains non-Bound Evidence id(s): {unknown_ids[:8]}"]
                candidate = coerce_answers_payload_by_stage_qa(candidate, stage_qa={"questions": [question]})
                coerced_answer = copy.deepcopy(candidate["answers"][0])
                if _brief_diff(raw_answer, coerced_answer):
                    _append_programmatic_mutation(
                        coerced_answer,
                        "stage_qa_coerce",
                        raw_answer,
                        coerced_answer,
                        reason="choice_normalization_or_schema_backfill",
                    )
                    self.events.emit(
                        "answer_candidate_mutated",
                        f"{question.get('question_id', '')} mutated during stage_qa_coerce",
                        stage_id=stage_id,
                        agent_name="stage_assembler",
                        metadata=_answer_audit_meta(question, "stage_qa_coerce", raw_answer, coerced_answer),
                    )
                before_resolve = copy.deepcopy(coerced_answer)
                resolved_answer = self._resolve_answer_evidence_refs(
                    coerced_answer,
                    evidence,
                    fallback_to_bound=False,
                    stage_id=stage_id,
                )
                if _brief_diff(before_resolve, resolved_answer):
                    self.events.emit(
                        "answer_candidate_mutated",
                        f"{question.get('question_id', '')} mutated during evidence_ref_resolution",
                        stage_id=stage_id,
                        agent_name="stage_assembler",
                        metadata=_answer_audit_meta(question, "evidence_ref_resolution", before_resolve, resolved_answer),
                    )
                before_schema = copy.deepcopy(resolved_answer)
                answer = self._enforce_answer_schema(question, resolved_answer, evidence, stage_id=stage_id, drafts=drafts)
                if _brief_diff(before_schema, answer):
                    self.events.emit(
                        "answer_candidate_mutated",
                        f"{question.get('question_id', '')} mutated during schema_guard",
                        stage_id=stage_id,
                        agent_name="stage_assembler",
                        level="warn",
                        metadata=_answer_audit_meta(question, "schema_guard", before_schema, answer),
                    )
                candidate["answers"] = [answer]
                post_issues = validate_answers_payload(
                    candidate,
                    stage_id=stage_id,
                    stage_title=title,
                    expected_question_ids=[str(question.get("question_id") or "").strip()],
                    stage_qa={"questions": [question]},
                )
                if post_issues:
                    return None, [f"{issue.path}: {issue.reason}" for issue in post_issues]
                return answer, []
            return None, ["answer root must be object"]
        except Exception as exc:
            return None, [f"{type(exc).__name__}: {exc}"]

    def _evidence_snapshot(self, record: EvidenceRecord) -> Dict[str, Any]:
        return {
            "evidence_id": record.evidence_id,
            "path": record.path or self.repo_path,
            "line_start": record.line_start,
            "line_end": record.line_end,
            "symbol_kind": record.evidence_type or "evidence",
            "symbol_name": record.symbol or record.tool_name or record.evidence_type or "evidence",
            "excerpt": (record.excerpt or "证据摘录为空；需结合路径继续核验。")[:4000],
            "evidence_type": record.evidence_type or "",
            "strength": record.strength or "",
            "validity": record.validity or "",
            "supports_claim_types": list(record.supports_claim_types or []),
        }

    def _extract_requested_evidence_ids(self, answer: Dict[str, Any]) -> List[str]:
        requested: List[str] = []
        used = answer.get("used_evidence_ids")
        if isinstance(used, list):
            requested.extend(str(x).strip() for x in used if str(x).strip())
        evs = answer.get("evidence")
        if isinstance(evs, list):
            for ev in evs:
                if isinstance(ev, dict):
                    evid = str(ev.get("evidence_id") or "").strip()
                    if evid:
                        requested.append(evid)
        facts = answer.get("fact_answers")
        if isinstance(facts, list):
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                used = fact.get("used_evidence_ids")
                if isinstance(used, list):
                    requested.extend(str(x).strip() for x in used if str(x).strip())
        out: List[str] = []
        seen = set()
        for evid in requested:
            if evid not in seen:
                seen.add(evid)
                out.append(evid)
        return out

    def _resolve_answer_evidence_refs(
        self,
        answer: Dict[str, Any],
        evidence: List[EvidenceRecord],
        *,
        fallback_to_bound: bool,
        stage_id: str = "",
    ) -> Dict[str, Any]:
        before = copy.deepcopy(answer)
        source = list(evidence or [])
        by_id = {r.evidence_id: r for r in source}
        requested = self._extract_requested_evidence_ids(answer)
        used_fallback = False
        if fallback_to_bound and not requested:
            requested = [r.evidence_id for r in source[:3]]
            used_fallback = bool(requested)
        valid_ids = [evid for evid in requested if evid in by_id]
        dropped_ids = [evid for evid in requested if evid not in by_id]
        answer["used_evidence_ids"] = valid_ids
        if used_fallback and valid_ids:
            self.events.emit(
                "answer_evidence_refs_fallback",
                f"{answer.get('question_id', '')} attached {len(valid_ids)} fallback evidence id(s)",
                stage_id=stage_id or str(answer.get("stage_id") or ""),
                agent_name="stage_assembler",
                metadata={
                    "question_id": answer.get("question_id"),
                    "fallback_evidence_ids": valid_ids,
                },
            )
        if dropped_ids:
            self.events.emit(
                "answer_evidence_refs_dropped",
                f"{answer.get('question_id', '')} dropped {len(dropped_ids)} non-bound evidence id(s)",
                stage_id=stage_id or str(answer.get("stage_id") or ""),
                agent_name="stage_assembler",
                level="warn",
                metadata={
                    "question_id": answer.get("question_id"),
                    "dropped_evidence_ids": dropped_ids,
                    "bound_evidence_ids": list(by_id.keys()),
                },
            )
        facts = answer.get("fact_answers")
        if isinstance(facts, list):
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                used = fact.get("used_evidence_ids")
                if isinstance(used, list):
                    fact["used_evidence_ids"] = [str(evid).strip() for evid in used if str(evid).strip() in by_id]
                else:
                    fact["used_evidence_ids"] = []
        answer["evidence"] = [self._evidence_snapshot(by_id[evid]) for evid in valid_ids]
        if dropped_ids:
            note = f"Evidence guard: 丢弃非本题 Bound Evidence 或未知 evidence_id: {dropped_ids[:8]}。"
            existing = answer.get("notes")
            answer["notes"] = f"{existing}\n{note}".strip() if isinstance(existing, str) and existing.strip() else note
        _append_programmatic_mutation(
            answer,
            "evidence_ref_resolution",
            before,
            answer,
            reason="bind_answer_to_verified_evidence_ids",
        )
        return answer

    def _enforce_answer_schema(
        self,
        question: Dict[str, Any],
        answer: Dict[str, Any],
        evidence: List[EvidenceRecord],
        *,
        stage_id: str = "",
        drafts: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        before = copy.deepcopy(answer)
        answer.setdefault("answer_status", "answered")
        answer = ensure_fact_answers_for_question(answer, question)
        answer = ensure_structured_value_for_question(answer, question)
        qtype = str(question.get("question_type") or "").strip()
        if qtype != "tri_state_impl":
            _append_programmatic_mutation(
                answer,
                "schema_enforce",
                before,
                answer,
                reason="fact_answers_or_value_shape_guard",
            )
            return answer
        value = normalize_tri_state_answer_value(answer.get("value"))
        used_ids = set(answer.get("used_evidence_ids") if isinstance(answer.get("used_evidence_ids"), list) else [])
        facts = answer.get("fact_answers")
        if isinstance(facts, list):
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                fact_used = fact.get("used_evidence_ids")
                if isinstance(fact_used, list):
                    used_ids.update(str(eid).strip() for eid in fact_used if str(eid).strip())
        scoped_evidence = [r for r in evidence if r.evidence_id in used_ids]
        if not _tri_state_value_allowed(value, scoped_evidence, answer):
            # stub 特殊救援：若 Task Agent 草稿以 medium/high confidence 判断为 stub，保留
            if value == "stub" and _stub_supported_by_drafts(drafts or []):
                note = "Schema guard: stub 由 Task Agent 草稿语义支撑（confidence=medium/high），保留。"
                existing = answer.get("notes")
                answer["notes"] = f"{existing}\n{note}".strip() if isinstance(existing, str) and existing.strip() else note
            else:
                recommended_value = "unknown"
                note = (
                    f"Schema guard: 原答案 {value!r} 缺少可支撑的强证据；"
                    f"当前引用证据最强 strength={strongest_evidence_strength(scoped_evidence)}；"
                    f"保留原 value，但建议人工审阅时视为 {recommended_value!r}。"
                )
                existing = answer.get("notes")
                answer["notes"] = f"{existing}\n{note}".strip() if isinstance(existing, str) and existing.strip() else note
                guardrail = {
                    "support_status": "unsupported",
                    "value": value,
                    "recommended_value": recommended_value,
                    "reason": "tri_state_not_supported_by_referenced_evidence",
                    "used_evidence_ids": sorted(used_ids),
                    "strongest_evidence_strength": strongest_evidence_strength(scoped_evidence),
                    "evidence_summary": _evidence_audit(scoped_evidence),
                }
                _set_meta_path(answer, ["guardrails", "tri_state"], guardrail)
                meta = dict(answer.get("_meta")) if isinstance(answer.get("_meta"), dict) else {}
                audit_items = list(meta.get("audit") or []) if isinstance(meta.get("audit"), list) else []
                audit_items.append(
                    {
                        "phase": "schema_guard",
                        "field": "value",
                        "value": value,
                        "recommended_value": recommended_value,
                        "reason": "tri_state_not_supported_by_referenced_evidence",
                        "used_evidence_ids": sorted(used_ids),
                        "evidence": _evidence_audit(scoped_evidence),
                    }
                )
                meta["audit"] = audit_items
                answer["_meta"] = meta
                self.events.emit(
                    "answer_guardrail_flagged",
                    f"{answer.get('question_id', '')} value {value!r} lacks supporting evidence; recommended {recommended_value!r}",
                    stage_id=stage_id or str(question.get("stage_id") or ""),
                    agent_name="stage_assembler",
                    level="blocker",
                    metadata={
                        "question_id": answer.get("question_id"),
                        "value": value,
                        "recommended_value": recommended_value,
                        "reason": "tri_state_not_supported_by_referenced_evidence",
                        "used_evidence_ids": sorted(used_ids),
                        "evidence": _evidence_audit(scoped_evidence),
                    },
                )
        answer["value"] = value
        _append_programmatic_mutation(
            answer,
            "schema_enforce",
            before,
            answer,
            reason="fact_answers_or_value_shape_guard",
        )
        return answer

    def _fallback_answer(
        self,
        question: Dict[str, Any],
        evidence: List[EvidenceRecord],
        *,
        reason: str = "assembler_failed_or_evidence_insufficient_fallback",
        last_issues: Optional[List[str]] = None,
        attempts: int = 0,
        raw_model_answer_excerpt: str = "",
    ) -> Dict[str, Any]:
        qid = str(question.get("question_id", "")).strip()
        qtype = str(question.get("question_type", "")).strip()
        if qtype == "tri_state_impl":
            value: Any = "unknown"
        else:
            value = "待核实：当前证据不足，需人工核验原始模型输出。"
        answer = {
            "question_id": qid,
            "question_type": qtype,
            "stem": question.get("stem", ""),
            "answer_status": "fallback_unusable",
            "fact_answers": [],
            "value": value,
            "used_evidence_ids": [],
            "evidence": [],
            "notes": "Fallback unusable: 模型输出未通过 JSON/契约校验；本答案不可视为真实结论。",
        }
        answer = ensure_fact_answers_for_question(answer, question)
        answer = ensure_structured_value_for_question(answer, question)
        _set_meta_path(
            answer,
            ["fallback"],
            {
                "reason": reason,
                "last_issues": list(last_issues or []),
                "attempts": attempts,
                "raw_model_answer_excerpt": raw_model_answer_excerpt[:4000],
            },
        )
        _append_programmatic_mutation(
            answer,
            "fallback_answer",
            {},
            answer,
            reason=reason,
        )
        return self._resolve_answer_evidence_refs(answer, evidence, fallback_to_bound=False)

    def _markdown_writer_prompt(self, stage_id: str, title: str, evidence_summary: str) -> str:
        stage_prompt = ""
        if hasattr(self, "stages_by_id") and self.stages_by_id and stage_id in self.stages_by_id:
            stage_prompt = (self.stages_by_id[stage_id].get("prompt") or "").strip()
        
        prompt = (
            "你是 OS-Agent D 的 Stage Writer Agent。根据 evidence 写 Markdown 技术章节，必须引用路径证据，证据不足写未发现。\n"
            f"stage_id={stage_id}\nstage_title={title}\n\n"
        )
        if stage_prompt:
            prompt += f"## 章节写作与格式要求\n{stage_prompt}\n\n"
        
        prompt += f"## Evidence\n{evidence_summary}\n"
        return prompt

    def _evidence_summary_for_prompt(self, grouped: Dict[str, List[EvidenceRecord]]) -> str:
        payload: Dict[str, List[Dict[str, Any]]] = {}
        for qid, records in grouped.items():
            payload[qid or "_stage"] = [
                {
                    "evidence_id": r.evidence_id,
                    "path": r.path,
                    "symbol": r.symbol,
                "source_type": r.source_type,
                "evidence_type": r.evidence_type,
                "confidence": r.confidence,
                "strength": r.strength,
                "supports_claim_types": r.supports_claim_types,
                "validity": r.validity,
                "excerpt": (r.excerpt or "")[:900],
            }
                for r in records[:8]
            ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _coerce_or_fallback_json(
        self,
        stage_id: str,
        title: str,
        questions: List[Dict[str, Any]],
        expected_question_ids: List[str],
        raw: str,
        evidence_by_question: Dict[str, List[EvidenceRecord]],
    ) -> Dict[str, Any]:
        try:
            payload = parse_answers_json(raw)
            payload = coerce_answers_payload_defaults(payload)
            stage_qa = load_stage_qa(stage_id)
            payload = coerce_answers_payload_by_stage_qa(payload, stage_qa=stage_qa)
            qmap = {str(q.get("question_id") or "").strip(): q for q in questions if isinstance(q, dict)}
            resolved_answers = []
            for answer in payload.get("answers", []) if isinstance(payload.get("answers"), list) else []:
                if not isinstance(answer, dict):
                    resolved_answers.append(answer)
                    continue
                qid = str(answer.get("question_id") or "").strip()
                evs = evidence_by_question.get(qid, [])
                q_drafts = self.draft_store.grouped_by_question(stage_id).get(qid, [])
                resolved = self._resolve_answer_evidence_refs(answer, evs, fallback_to_bound=False, stage_id=stage_id)
                resolved_answers.append(self._enforce_answer_schema(qmap.get(qid, {}), resolved, evs, stage_id=stage_id, drafts=q_drafts))
            payload["answers"] = resolved_answers
            issues = validate_answers_payload(
                payload,
                stage_id=stage_id,
                stage_title=title,
                expected_question_ids=expected_question_ids,
                stage_qa=stage_qa,
            )
            if not issues:
                return payload
            self.events.emit("writer_json_invalid", f"validation issues={len(issues)}; using fallback", stage_id=stage_id, level="warn")
        except Exception as exc:
            self.events.emit("writer_json_invalid", f"{type(exc).__name__}: {exc}; using fallback", stage_id=stage_id, level="warn")
        answers = []
        for q in questions:
            qid = str(q.get("question_id", "")).strip()
            evs = evidence_by_question.get(qid, [])
            answers.append(self._fallback_answer(
                q,
                evs,
                reason="stage_writer_json_fallback",
                last_issues=[],
                attempts=1,
                raw_model_answer_excerpt=raw or "",
            ))
        payload = {
            "schema_version": JSON_QA_SCHEMA_VERSION,
            "stage_id": stage_id,
            "stage_title": title,
            "terminology_profile": "stallings_en_zh",
            "answers": answers,
        }
        try:
            stage_qa = load_stage_qa(stage_id)
            payload = coerce_answers_payload_by_stage_qa(payload, stage_qa=stage_qa)
        except Exception:
            pass
        return payload

    def _review_stage(self, stage_id: str, title: str, expected_question_ids: List[str], payload: Dict[str, Any]) -> Dict[str, Any]:
        if not payload or not describe_stage_review_enabled() or not describe_stage_review_applies(stage_id, expected_question_ids=expected_question_ids):
            return {}
        self.events.emit("review_start", "review stage answers", stage_id=stage_id, agent_name="review_agent")
        sidecar = os.path.join(self.repo_output_dir, "_per_stage")
        reviews_dir = os.path.join(self.state_dir, "reviews")
        os.makedirs(reviews_dir, exist_ok=True)

        parsed_review: Optional[Dict[str, Any]] = None
        raw = ""
        err: Optional[str] = None
        tokens = 0
        manifest: Dict[str, Any] = {
            "stage_id": stage_id,
            "stage_title": title,
            "mode": "per_question",
            "batches": [],
            "truncated": False,
        }
        question_by_id = self._stage_question_map(stage_id)
        answer_by_id = {
            str(a.get("question_id") or "").strip(): a
            for a in payload.get("answers", []) if isinstance(a, dict)
        }
        batch_reviews: List[Dict[str, Any]] = []
        findings: List[Any] = []
        summaries: List[str] = []
        for qid in expected_question_ids:
            question = question_by_id.get(qid)
            answer = answer_by_id.get(qid)
            if not question or not answer:
                continue
            digest = _question_digest(question)
            question_sheet = self._single_question_review_sheet(stage_id, title, question, digest)
            model_json = json.dumps(
                {
                    "schema_version": payload.get("schema_version"),
                    "stage_id": stage_id,
                    "stage_title": title,
                    "answers": [answer],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            manifest["batches"].append(
                {
                    "question_ids": [qid],
                    "question_digest": digest,
                    "question_sheet_chars": len(question_sheet),
                    "answer_json_chars": len(model_json),
                    "truncated": False,
                }
            )
            one_review, one_raw, one_err, one_tokens = run_describe_stage_review(
                stage_id=stage_id,
                stage_title=title,
                question_sheet=question_sheet,
                model_json_before_stage_qa_coerce=model_json,
                expected_question_ids=[qid],
                expected_question_digests={qid: digest},
            )
            tokens += one_tokens
            raw += f"--- {qid} digest={digest} ---\n{one_raw}\n\n"
            if one_review is None:
                err = one_err or err or "unknown"
                batch_reviews.append(
                    {
                        "question_id": qid,
                        "question_digest": digest,
                        "score_evidence": None,
                        "score_consistency": None,
                        "review": f"（审计失败：{one_err or 'unknown'}）",
                    }
                )
                continue
            batch_reviews.extend(one_review.get("question_reviews") or [])
            if isinstance(one_review.get("findings"), list):
                findings.extend(one_review.get("findings") or [])
            if one_review.get("summary_zh"):
                summaries.append(str(one_review.get("summary_zh")))
        if batch_reviews:
            parsed_review = {
                "schema_version": "describe_review_v1",
                "stage_id": stage_id,
                "stage_title": title,
                "confidence": None,
                "question_reviews": batch_reviews,
                "findings": findings,
                "summary_zh": "；".join(summaries[:8]),
            }

        if parsed_review is not None:
            parsed_review = enrich_review_with_report_quality(parsed_review, payload)
            with FileLock(lock_path(self.state_dir, "output_write")):
                _atomic_save_json(os.path.join(sidecar, f"{stage_id}_review.json"), parsed_review)
                _atomic_save_json(os.path.join(self.state_dir, "reviews", f"{stage_id}_review.json"), parsed_review)
                with open(os.path.join(reviews_dir, f"{stage_id}_review_raw.txt"), "w", encoding="utf-8") as f:
                    f.write(raw.strip() + "\n")
                _atomic_save_json(os.path.join(reviews_dir, f"{stage_id}_review_input_manifest.json"), manifest)
            self.events.emit("review_done", f"confidence={parsed_review.get('confidence')}", stage_id=stage_id, agent_name="review_agent", token_usage={"total_tokens": tokens}, metadata={"score": parsed_review.get("confidence")})
            return parsed_review
        err_payload = {"error": err or "unknown", "raw_model_output_excerpt": (raw or "")[:4000]}
        with FileLock(lock_path(self.state_dir, "output_write")):
            _atomic_save_json(os.path.join(sidecar, f"{stage_id}_review_error.json"), err_payload)
        self.events.emit("review_error", err_payload["error"], stage_id=stage_id, agent_name="review_agent", level="warn")
        return {}

    def _stage_question_map(self, stage_id: str) -> Dict[str, Dict[str, Any]]:
        try:
            stage_qa = load_stage_qa(stage_id)
        except Exception:
            return {}
        questions = stage_qa.get("questions", []) if isinstance(stage_qa, dict) else []
        if not isinstance(questions, list):
            return {}
        return {
            str(q.get("question_id") or "").strip(): q
            for q in questions if isinstance(q, dict) and str(q.get("question_id") or "").strip()
        }

    def _single_question_review_sheet(self, stage_id: str, title: str, question: Dict[str, Any], digest: str) -> str:
        qid = str(question.get("question_id") or "").strip()
        lines = [
            f"## 题库文件\n`core/describe_stage_qa/{stage_id}.json`\n\n",
            f"**stage_id**: `{stage_id}`  \n**stage_title**: {title}\n\n",
            "## 题单（本批仅 1 题，禁止评价其他题）\n\n",
            f"### {qid}（{question.get('question_type', '')}）\n\n",
            f"question_digest: `{digest}`\n\n",
            f"{question.get('stem', '')}\n\n",
        ]
        feature_view = {
            "feature_ids": question.get("feature_ids"),
            "evidence_policy": question.get("evidence_policy"),
            "tri_state_rule": question.get("tri_state_rule"),
            "anti_examples": question.get("anti_examples"),
            "structured_facts": question.get("structured_facts"),
            "answer_contract": question.get("answer_contract"),
        }
        feature_view = {k: v for k, v in feature_view.items() if v is not None}
        if feature_view:
            lines.append(f"**feature_context**: {json.dumps(feature_view, ensure_ascii=False, separators=(',', ':'))}\n\n")
        choices = question.get("choices")
        if isinstance(choices, list) and choices:
            lines.append("**choices**（答案 `value` 应使用选项原文）:\n")
            for i, c in enumerate(choices[:12]):
                label = chr(ord("A") + i) if i < 26 else str(i)
                lines.append(f"- {label}. {str(c).strip()}\n")
            lines.append(f"\n**valid value texts**: {json.dumps([str(c).strip() for c in choices], ensure_ascii=False, separators=(',', ':'))}\n\n")
        lines.append("评审输出中对应 question_reviews item 必须包含相同的 question_digest。\n")
        return "".join(lines)

    def _load_previous_sections_text(self) -> str:
        parts = []
        for stage in self.stages:
            stage_id = stage.get("id")
            if stage_id == "01_overview":
                continue
            title = stage.get("title") or stage_id
            
            # 优先从 _answers.json 提炼出超高密度的纯文本大纲（不含表格、无边框、无冗余描述）
            answers_path = os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_answers.json")
            if os.path.isfile(answers_path):
                try:
                    with open(answers_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                    
                    stage_lines = [f"=== {title} ({stage_id}) ==="]
                    answers = payload.get("answers", [])
                    for a in answers:
                        if not isinstance(a, dict):
                            continue
                        qid = a.get("question_id") or ""
                        stem = (a.get("stem") or "")[:40] # 简短 stem
                        val = a.get("value") or ""
                        notes = (a.get("notes") or "").strip()
                        
                        header = f"- {qid}"
                        if stem:
                            header += f" [{stem}]"
                        if val:
                            header += f": {val}"
                        if notes:
                            notes_clean = notes.replace("\n", " ").replace("\r", " ")
                            header += f" ({notes_clean})"
                        stage_lines.append(header)
                    parts.append("\n".join(stage_lines))
                    continue
                except Exception as exc:
                    self.events.emit("stage_skip", f"Failed to compress answers for overview: {exc}", level="warn", stage_id=stage_id)
            
            # 若无 answers.json 则降级读取 Markdown 章节，但限制读取长度以保持压缩率
            sections_dir = os.path.join(self.repo_output_dir, "sections")
            if os.path.isdir(sections_dir):
                for fname in sorted(os.listdir(sections_dir)):
                    if fname.startswith(f"{stage_id}_") and fname.endswith(".md"):
                        try:
                            with open(os.path.join(sections_dir, fname), "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read(3000)
                            parts.append(f"=== {title} ({stage_id}) ===\n{text}")
                        except Exception:
                            pass
                        break
        return "\n\n".join(parts)

    def _publish_final_report(self) -> None:
        try:
            review_score_bundle = write_review_score_json(self.repo_output_dir)
        except Exception as exc:
            self.events.emit("review_score_error", str(exc), level="warn")
            review_score_bundle = {}
        total_quality = review_score_bundle.get("total_0_100") if isinstance(review_score_bundle, dict) else None
        with FileLock(lock_path(self.state_dir, "output_write")):
            index_path = publish_html_report(
                repo_output_dir=self.repo_output_dir,
                repo_name=self.repo_name,
                repo_url=self.repo_url,
                analysis_date=datetime.now().strftime('%Y年%m月%d日'),
                total_quality=total_quality,
                repo_meta=self.repo_meta or None,
            )
            try:
                graph = publish_feature_graph(
                    repo_output_dir=self.repo_output_dir,
                    evidence_records=self.evidence_store.all(),
                )
                self.events.emit("feature_graph_done", f"nodes={graph.get('stats', {}).get('nodes')} edges={graph.get('stats', {}).get('edges')}")
            except Exception as exc:
                self.events.emit("feature_graph_error", f"{type(exc).__name__}: {exc}", level="warn")
        self.events.emit("publish_done", index_path or self.repo_output_dir)

    def _save_graph_snapshot_unlocked(self, *, status: str, current_stage: str = "") -> None:
        stage_states: Dict[str, Dict[str, Any]] = {}
        for sid in [str(s.get("id")) for s in self.stages]:
            path = self._stage_state_path(sid)
            data = _load_json(path)
            if data:
                stage_states[sid] = data
        task_results: Dict[str, Dict[str, Any]] = {}
        tasks_dir = os.path.join(self.state_dir, "tasks")
        if os.path.isdir(tasks_dir):
            for name in os.listdir(tasks_dir):
                if name.endswith(".json"):
                    data = _load_json(os.path.join(tasks_dir, name))
                    tid = str(data.get("task_id") or os.path.splitext(name)[0])
                    task_results[tid] = data
        snapshot = DescribeGraphState(
            run_id=self.run_id,
            repo_name=self.repo_name,
            repo_path=self.repo_path,
            output_dir=self.repo_output_dir,
            repo_profile=_load_json(os.path.join(self.repo_output_dir, "repo_profile.json")),
            stage_order=[str(s.get("id")) for s in self.stages],
            current_stage=current_stage,
            stage_states=stage_states,
            task_results=task_results,
            evidence_store={r.evidence_id: r.to_dict() for r in self.evidence_store.all()},
            status=status,
        )
        _atomic_save_json(os.path.join(self.state_dir, "graph_state.json"), snapshot.to_dict())


def run_describe_graph(*, repo_url: str, stages: List[Dict[str, Any]], output_dir: str = "./output",
                       repo_meta: Optional[Dict[str, Any]] = None) -> None:
    runtime = MultiAgentRuntime(repo_url=repo_url, stages=stages, output_dir=output_dir, repo_meta=repo_meta)
    runtime.run()
