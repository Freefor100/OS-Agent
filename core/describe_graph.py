from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage

from core.agent_events import EventLogger
from core.agent_graph_state import DescribeGraphState, EvidenceRecord, TaskResult, TaskSpec, utcnow_iso
from core.agent_locks import FileLock, lock_path, named_thread_lock
from core.describe_json_qa import (
    SCHEMA_VERSION as JSON_QA_SCHEMA_VERSION,
    coerce_answers_payload_by_stage_qa,
    coerce_answers_payload_defaults,
    parse_answers_json,
    render_answers_to_markdown,
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
from core.handoff_to_c import emit_handoff_to_c
from core.per_planner import build_repo_profile, ensure_execution_steps, plan_stage
from core.per_types import StageState
from core.task_agents import run_task_agent
from core.task_builder import build_tasks_for_stage
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


def _stage_by_id(stages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(s.get("id")): s for s in stages}


class MultiAgentRuntime:
    def __init__(self, *, repo_url: str, stages: List[Dict[str, Any]], output_dir: str):
        self.repo_url = repo_url
        self.repo_name = repo_name_from_url(repo_url)
        self.repo_path = os.path.normpath(os.path.join("./repos", self.repo_name))
        self.repo_output_dir = os.path.join(output_dir, self.repo_name)
        self.state_dir = os.path.join(self.repo_output_dir, "_agent_state")
        self.stages = stages
        self.stages_by_id = _stage_by_id(stages)
        self.run_id = self._load_or_create_run_id()
        self.events = EventLogger(self.run_id, self.state_dir)
        self.evidence_store = EvidenceStore(os.path.join(self.state_dir, "evidence_store.jsonl"))
        self.max_parallel_stages = _env_int("OS_AGENT_MAX_PARALLEL_STAGES", 2)
        self.max_parallel_tasks = _env_int("OS_AGENT_MAX_PARALLEL_TASKS_PER_STAGE", 3)
        self.llm_semaphore = threading.BoundedSemaphore(_env_int("OS_AGENT_MAX_PARALLEL_LLM_CALLS", 2))
        self.lsp_semaphore = threading.BoundedSemaphore(_env_int("OS_AGENT_MAX_PARALLEL_LSP_TASKS", 1))
        self.rag_semaphore = threading.BoundedSemaphore(_env_int("OS_AGENT_MAX_PARALLEL_RAG_TASKS", 3))
        self.max_review_fix_rounds = _env_int("OS_AGENT_MAX_REVIEW_FIX_ROUNDS", 2)
        self.max_task_retries = _env_int("OS_AGENT_MAX_TASK_RETRIES", 2)
        self.force_stages = {
            item.strip()
            for item in (os.environ.get("OS_AGENT_FORCE_STAGES") or "").split(",")
            if item.strip()
        }
        os.makedirs(os.path.join(self.state_dir, "stages"), exist_ok=True)
        os.makedirs(os.path.join(self.state_dir, "tasks"), exist_ok=True)
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

    def run(self) -> None:
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
        with ThreadPoolExecutor(max_workers=self.max_parallel_stages) as pool:
            futures = {
                pool.submit(self._run_stage, sid, repo_profile): sid
                for sid in parallel_stage_ids
                if self._stage_status(sid) != "reviewed" or sid in self.force_stages
            }
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    self.events.emit("stage_error", f"{type(exc).__name__}: {exc}", stage_id=sid, level="error")
        if "01_overview" in self.stages_by_id:
            self._run_stage("01_overview", repo_profile)
        self._publish_final_report()
        handoff = emit_handoff_to_c(self.repo_name, self.repo_output_dir)
        self.events.emit("handoff_done", "handoff_to_c.json generated", metadata={"evidence_count": handoff.get("evidence_summary", {}).get("count", 0)})
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
        if self._stage_status(stage_id) == "reviewed" and stage_id not in self.force_stages:
            self.events.emit("stage_skip", "already reviewed", stage_id=stage_id)
            return
        self.events.emit("stage_start", title, stage_id=stage_id)
        questions, expected_question_ids = _questions_for_stage(stage_id)
        stage_state = StageState(
            stage_id=stage_id,
            stage_title=title,
            stage_type="describe",
            stage_prompt=str(stage.get("prompt") or ""),
        )
        stage_state.plan = ensure_execution_steps(plan_stage(stage_state, repo_profile=repo_profile, global_memory={}))
        _atomic_save_json(
            os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_plan.json"),
            stage_state.plan.to_dict(),
        )
        tasks = build_tasks_for_stage(stage_id=stage_id, stage_title=title, questions=questions, plan=stage_state.plan)
        task_results, records = self._run_tasks(stage_id, tasks, force=stage_id in self.force_stages)
        for rec in records:
            self.evidence_store.append(rec)
        evidence_by_question = self.evidence_store.grouped_by_question(stage_id)
        payload, markdown = self._write_stage(stage_id, title, questions, expected_question_ids, evidence_by_question)
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
            fix_results, fix_records = self._run_tasks(stage_id, fix_tasks)
            for rec in fix_records:
                self.evidence_store.append(rec)
            records.extend(fix_records)
            task_results.extend(fix_results)
            evidence_by_question = self.evidence_store.grouped_by_question(stage_id)
            payload, markdown = self._write_stage(stage_id, title, questions, expected_question_ids, evidence_by_question)
            if markdown and not stage.get("skip_in_report", False):
                with FileLock(lock_path(self.state_dir, "output_write")):
                    with open(section_path, "w", encoding="utf-8") as f:
                        f.write(markdown.strip() + "\n")
            review = self._review_stage(stage_id, title, expected_question_ids, payload)
        state_payload = {
            "stage_id": stage_id,
            "stage_title": title,
            "status": "reviewed",
            "plan_path": os.path.join(self.repo_output_dir, "_per_stage", f"{stage_id}_plan.json"),
            "task_ids": [t.task_id for t in tasks],
            "evidence_ids": [r.evidence_id for r in records],
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
            f"{title} evidence={len(records)} tasks={len(task_results)}",
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

    def _build_fix_tasks(
        self,
        stage_id: str,
        title: str,
        review: Dict[str, Any],
        questions: List[Dict[str, Any]],
    ) -> List[TaskSpec]:
        qmap = {str(q.get("question_id")): q for q in questions if isinstance(q, dict)}
        weak_qids: List[str] = []
        for item in review.get("question_reviews", []) if isinstance(review.get("question_reviews"), list) else []:
            if not isinstance(item, dict):
                continue
            qid = str(item.get("question_id") or "")
            try:
                score = float(item.get("score_evidence"))
            except Exception:
                score = 0.0
            if qid and score < 0.75:
                weak_qids.append(qid)
        if not weak_qids and qmap:
            weak_qids = list(qmap.keys())[:2]
        fix_questions = [qmap[qid] for qid in weak_qids[:4] if qid in qmap]
        tasks = build_tasks_for_stage(
            stage_id=stage_id,
            stage_title=title,
            questions=fix_questions,
            plan=StageState(stage_id=stage_id, stage_title=title, stage_type="describe", stage_prompt="").plan,
        )
        for task in tasks:
            task.task_id = f"{task.task_id}_fix_{uuid.uuid4().hex[:6]}"
            task.metadata["fix_reason"] = "review_low_evidence"
        return tasks

    def _run_tasks(self, stage_id: str, tasks: List[TaskSpec], *, force: bool = False) -> Tuple[List[TaskResult], List[EvidenceRecord]]:
        results: List[TaskResult] = []
        records: List[EvidenceRecord] = []
        pending = list(tasks) if force else [t for t in tasks if _load_json(self._task_state_path(t.task_id)).get("status") != "done"]
        skipped = 0 if force else len(tasks) - len(pending)
        if skipped:
            self.events.emit("task_skip", f"reuse {skipped} completed task(s)", stage_id=stage_id)
        self.events.emit("task_dispatch", f"dispatch {len(pending)} task(s)", stage_id=stage_id)
        with ThreadPoolExecutor(max_workers=self.max_parallel_tasks) as pool:
            futures = {pool.submit(self._run_one_task_with_limits, t): t for t in pending}
            for future in as_completed(futures):
                task = futures[future]
                result, evs = future.result()
                results.append(result)
                records.extend(evs)
                with FileLock(lock_path(self.state_dir, "output_write")):
                    _atomic_save_json(self._task_state_path(task.task_id), result.to_dict())
                self.events.emit(
                    "task_done" if result.status == "done" else "task_error",
                    f"{task.task_type} evidence={len(evs)} confidence={result.confidence}",
                    stage_id=task.stage_id,
                    task_id=task.task_id,
                    agent_name=f"{task.task_type}_agent",
                    level="info" if result.status == "done" else "warn",
                )
        return results, records

    def _run_one_task_with_limits(self, task: TaskSpec) -> Tuple[TaskResult, List[EvidenceRecord]]:
        sem = None
        lock_cm = None
        if task.task_type in {"definition", "flow"}:
            sem = self.lsp_semaphore
            lock_cm = named_thread_lock("lsp_task")
        elif task.task_type in {"discovery", "implementation_state"}:
            sem = self.rag_semaphore
        if sem:
            sem.acquire()
        try:
            if lock_cm:
                with lock_cm:
                    return run_task_agent(task, repo_path=self.repo_path)
            return run_task_agent(task, repo_path=self.repo_path)
        finally:
            if sem:
                sem.release()

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
            markdown = render_answers_to_markdown(payload).strip()
            sidecar = os.path.join(self.repo_output_dir, "_per_stage")
            with FileLock(lock_path(self.state_dir, "output_write")):
                _atomic_save_json(os.path.join(sidecar, f"{stage_id}_answers.json"), payload)
                with open(os.path.join(sidecar, f"{stage_id}_answers_raw.txt"), "w", encoding="utf-8") as f:
                    f.write(raw.strip() + "\n")
            return payload, markdown
        prompt = self._markdown_writer_prompt(stage_id, title, evidence_summary)
        if stage_id == "01_overview":
            prompt += "\n\n## 前置章节摘要\n" + self._load_previous_sections_text()
        markdown = self._invoke_llm(prompt, stage_id=stage_id, agent_name="stage_writer")
        return {}, markdown

    def _invoke_llm(self, prompt: str, *, stage_id: str, agent_name: str) -> str:
        from core.agent_builder import build_chat_model

        self.llm_semaphore.acquire()
        self.events.emit("llm_start", agent_name, stage_id=stage_id, agent_name=agent_name)
        try:
            llm = build_chat_model(temperature=0)
            msg = llm.invoke([HumanMessage(content=prompt)])
            usage = getattr(msg, "response_metadata", {}).get("token_usage", {}) or {}
            self.events.emit("llm_done", agent_name, stage_id=stage_id, agent_name=agent_name, token_usage=usage)
            return (getattr(msg, "content", "") or "").strip()
        finally:
            self.llm_semaphore.release()

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
            "answers 必须按题单顺序逐题回答，每题包含 question_id, question_type, stem, value, evidence。\n"
            "tri_state_impl 的 value 只能是 implemented / stub / not_found。\n\n"
            f"stage_id={stage_id}\nstage_title={title}\n\n"
            "## 题单\n"
            f"{json.dumps(questions, ensure_ascii=False, indent=2)}\n\n"
            "## Evidence By Question\n"
            f"{evidence_summary}\n\n"
            "若证据不足，value 写 not_found/待核实，并在 evidence 中记录搜索范围。"
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
            raw = self._invoke_llm(prompt, stage_id=stage_id, agent_name="stage_writer")
            raw_parts.append(f"--- {qid} ---\n{raw}")
            answer = self._parse_one_answer_or_fallback(stage_id, title, question, raw, evs)
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
                "validity": r.validity,
                "excerpt": (r.excerpt or "")[:1200],
            }
            for r in evidence[:8]
        ]
        return (
            "你是 OS-Agent D 的 Stage Writer Agent。现在只回答一个小题。\n"
            "只能输出一个 JSON object，字段必须是 question_id, question_type, stem, value, evidence。\n"
            "不要输出 Markdown，不要围栏，不要解释。\n"
            "tri_state_impl 的 value 只能是 implemented / stub / not_found。\n"
            "single_choice 的 value 必须等于 choices 中某一项完整原文；multi_choice 的 value 必须是数组。\n"
            "证据不足时写 not_found/待核实，不能编造路径。\n\n"
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
                candidate = {
                    "schema_version": JSON_QA_SCHEMA_VERSION,
                    "stage_id": stage_id,
                    "stage_title": title,
                    "terminology_profile": "stallings_en_zh",
                    "answers": [parsed],
                }
                candidate = coerce_answers_payload_defaults(candidate)
                candidate = coerce_answers_payload_by_stage_qa(candidate, stage_qa={"questions": [question]})
                answer = candidate["answers"][0]
                # Ensure evidence has the exact minimal schema accepted by renderer.
                if not isinstance(answer.get("evidence"), list):
                    answer["evidence"] = []
                return answer
        except Exception:
            pass
        return self._fallback_answer(question, evidence)

    def _fallback_answer(self, question: Dict[str, Any], evidence: List[EvidenceRecord]) -> Dict[str, Any]:
        qid = str(question.get("question_id", "")).strip()
        qtype = str(question.get("question_type", "")).strip()
        ev_payload = [
            {
                "path": r.path or self.repo_path,
                "symbol_kind": r.evidence_type or "search",
                "symbol_name": r.symbol or r.tool_name or "evidence",
                "excerpt": (r.excerpt or "")[:500],
            }
            for r in evidence[:3]
        ]
        if not ev_payload:
            ev_payload = [{"path": self.repo_path, "symbol_kind": "search", "symbol_name": "no_valid_evidence", "excerpt": "未找到可验证证据。"}]
        if qtype == "tri_state_impl":
            value: Any = "not_found"
        elif qtype == "multi_choice":
            choices = question.get("choices") if isinstance(question.get("choices"), list) else []
            value = [choices[-1]] if choices else []
        elif qtype == "single_choice":
            choices = question.get("choices") if isinstance(question.get("choices"), list) else []
            value = choices[-1] if choices else "待核实"
        else:
            value = "待核实：当前证据不足，需结合 evidence 继续确认。"
        return {
            "question_id": qid,
            "question_type": qtype,
            "stem": question.get("stem", ""),
            "value": value,
            "evidence": ev_payload,
        }

    def _markdown_writer_prompt(self, stage_id: str, title: str, evidence_summary: str) -> str:
        return (
            "你是 OS-Agent D 的 Stage Writer Agent。根据 evidence 写 Markdown 技术章节，必须引用路径证据，证据不足写未发现。\n"
            f"stage_id={stage_id}\nstage_title={title}\n\n"
            f"## Evidence\n{evidence_summary}\n"
        )

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
            issues = validate_answers_payload(payload, stage_id=stage_id, stage_title=title, expected_question_ids=expected_question_ids)
            if not issues:
                return payload
            self.events.emit("writer_json_invalid", f"validation issues={len(issues)}; using fallback", stage_id=stage_id, level="warn")
        except Exception as exc:
            self.events.emit("writer_json_invalid", f"{type(exc).__name__}: {exc}; using fallback", stage_id=stage_id, level="warn")
        answers = []
        for q in questions:
            qid = str(q.get("question_id", "")).strip()
            qtype = str(q.get("question_type", "")).strip()
            evs = evidence_by_question.get(qid, [])
            evidence = [
                {
                    "path": r.path or self.repo_path,
                    "symbol_kind": r.evidence_type or "search",
                    "symbol_name": r.symbol or r.tool_name or "evidence",
                    "excerpt": (r.excerpt or "")[:500],
                }
                for r in evs[:3]
            ]
            if not evidence:
                evidence = [{"path": self.repo_path, "symbol_kind": "search", "symbol_name": "no_valid_evidence", "excerpt": "未找到可验证证据。"}]
            if qtype == "tri_state_impl":
                value: Any = "not_found"
            elif qtype == "multi_choice":
                choices = q.get("choices") if isinstance(q.get("choices"), list) else []
                value = [choices[-1]] if choices else []
            elif qtype == "single_choice":
                choices = q.get("choices") if isinstance(q.get("choices"), list) else []
                value = choices[-1] if choices else "待核实"
            else:
                value = "待核实：当前 Multi-Agent 证据不足，需结合 evidence 继续确认。"
            answers.append(
                {
                    "question_id": qid,
                    "question_type": qtype,
                    "stem": q.get("stem", ""),
                    "value": value,
                    "evidence": evidence,
                }
            )
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
        question_sheet = build_stage_qa_question_sheet(stage_id, title)
        model_json = json.dumps(payload, ensure_ascii=False, indent=2)
        self.llm_semaphore.acquire()
        try:
            parsed_review, raw, err, tokens = run_describe_stage_review(
                stage_id=stage_id,
                stage_title=title,
                question_sheet=question_sheet,
                model_json_before_stage_qa_coerce=model_json,
                expected_question_ids=expected_question_ids,
            )
        finally:
            self.llm_semaphore.release()
        sidecar = os.path.join(self.repo_output_dir, "_per_stage")
        if parsed_review is not None:
            parsed_review = enrich_review_with_report_quality(parsed_review, payload)
            with FileLock(lock_path(self.state_dir, "output_write")):
                _atomic_save_json(os.path.join(sidecar, f"{stage_id}_review.json"), parsed_review)
                _atomic_save_json(os.path.join(self.state_dir, "reviews", f"{stage_id}_review.json"), parsed_review)
            self.events.emit("review_done", f"confidence={parsed_review.get('confidence')}", stage_id=stage_id, agent_name="review_agent", token_usage={"total_tokens": tokens})
            return parsed_review
        err_payload = {"error": err or "unknown", "raw_model_output_excerpt": (raw or "")[:4000]}
        with FileLock(lock_path(self.state_dir, "output_write")):
            _atomic_save_json(os.path.join(sidecar, f"{stage_id}_review_error.json"), err_payload)
        self.events.emit("review_error", err_payload["error"], stage_id=stage_id, agent_name="review_agent", level="warn")
        return {}

    def _load_previous_sections_text(self) -> str:
        sections_dir = os.path.join(self.repo_output_dir, "sections")
        parts = []
        for fname in sorted(os.listdir(sections_dir)) if os.path.isdir(sections_dir) else []:
            if fname.startswith("01_") or not fname.endswith(".md"):
                continue
            try:
                with open(os.path.join(sections_dir, fname), "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read(8000)
                parts.append(f"--- {fname} ---\n{text}")
            except Exception:
                pass
        return "\n\n".join(parts)

    def _publish_final_report(self) -> None:
        try:
            review_score_bundle = write_review_score_json(self.repo_output_dir)
        except Exception as exc:
            self.events.emit("review_score_error", str(exc), level="warn")
            review_score_bundle = {}
        total_quality = review_score_bundle.get("total_0_100") if isinstance(review_score_bundle, dict) else None
        final_report_path = os.path.join(self.repo_output_dir, f"OS技术分析报告_{self.repo_name}.md")
        sections_dir = os.path.join(self.repo_output_dir, "sections")
        section_paths = [
            os.path.join(sections_dir, f)
            for f in sorted(os.listdir(sections_dir)) if f.endswith(".md")
        ] if os.path.isdir(sections_dir) else []
        overview = [p for p in section_paths if os.path.basename(p).startswith("01_")]
        others = [p for p in section_paths if p not in overview]
        content_sections = overview + others
        with FileLock(lock_path(self.state_dir, "output_write")):
            with open(final_report_path, "w", encoding="utf-8") as out:
                out.write(f"# {self.repo_name} 操作系统技术分析报告\n\n")
                out.write(f"> **仓库地址**: {self.repo_url}\n\n")
                out.write(f"> **分析日期**: {datetime.now().strftime('%Y年%m月%d日')}\n\n")
                out.write("> **分析工具**: OS-Agent-D Multi-Agent\n\n")
                if total_quality is not None:
                    out.write(f"> **报告质量打分**: {total_quality}/100\n\n")
                out.write("---\n\n## 目录\n\n")
                for idx, path in enumerate(content_sections, 1):
                    title = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
                    out.write(f"{idx}. {title}\n")
                out.write("\n---\n\n")
                for path in content_sections:
                    heading = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
                    out.write(f"# {heading}\n\n")
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        out.write(f.read().strip() + "\n\n---\n\n")
                out.write(f"*本报告由 OS-Agent-D Multi-Agent 自动生成*  \n")
                out.write(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*  \n")
        self.events.emit("publish_done", final_report_path)

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


def run_describe_graph(*, repo_url: str, stages: List[Dict[str, Any]], output_dir: str = "./output") -> None:
    runtime = MultiAgentRuntime(repo_url=repo_url, stages=stages, output_dir=output_dir)
    runtime.run()
