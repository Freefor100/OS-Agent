from __future__ import annotations

import os
import re
import uuid
import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List, Tuple

from core.agent_graph_state import EvidenceRecord, TaskResult, TaskSpec
from core.evidence_verifier import verify_evidence


def _invoke_tool(tool: Any, args: Dict[str, Any]) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        if hasattr(tool, "invoke"):
            result = str(tool.invoke(args))
        else:
            result = str(tool(**args))
    captured = (stdout.getvalue() + stderr.getvalue()).strip()
    if captured:
        return result + "\n\n[tool_output]\n" + captured
    return result


def _safe_rel_path(repo_path: str, path: str) -> str:
    if not path:
        return ""
    norm_repo = os.path.normpath(repo_path)
    repo_name = os.path.basename(norm_repo)
    norm_path = os.path.normpath(path)
    parts = norm_path.split(os.sep)
    if len(parts) >= 2 and parts[0] == "repos" and parts[1] == repo_name:
        try:
            return os.path.relpath(norm_path, norm_repo).replace("\\", "/")
        except ValueError:
            return norm_path.replace("\\", "/")
    if os.path.isabs(path):
        try:
            return os.path.relpath(path, repo_path).replace("\\", "/")
        except ValueError:
            return path.replace("\\", "/")
    return path.replace("\\", "/")


def _extract_paths(text: str, repo_path: str, limit: int = 5) -> List[str]:
    paths: List[str] = []
    for match in re.finditer(r"([A-Za-z]:)?[^\s`'\"]+\.(?:rs|c|h|cpp|hpp|go|zig|S|s|toml|ld|lds|md|py)(?::\d+(?:-\d+)?)?", text or ""):
        raw = match.group(0).strip("`'\".,;)")
        if not raw or raw.startswith("http"):
            continue
        if ":" in raw[2:]:
            raw = raw.rsplit(":", 1)[0]
        rel = _safe_rel_path(repo_path, raw)
        if rel not in paths:
            paths.append(rel)
        if len(paths) >= limit:
            break
    return paths


def _first_existing_source_file(repo_path: str, seeds: List[str]) -> str:
    exts = (".rs", ".c", ".h", ".cpp", ".hpp", ".go", ".zig", ".S", ".s")
    for seed in seeds:
        candidate = os.path.join(repo_path, seed)
        if os.path.isfile(candidate) and candidate.endswith(exts):
            return _safe_rel_path(repo_path, candidate)
        if os.path.isdir(candidate):
            for root, dirs, files in os.walk(candidate):
                dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "dist", "node_modules", ".os_agent_ra_target"}]
                for name in files:
                    if name.endswith(exts):
                        return _safe_rel_path(repo_path, os.path.join(root, name))
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "dist", "node_modules", ".os_agent_ra_target"}]
        for name in files:
            if name.endswith(exts):
                return _safe_rel_path(repo_path, os.path.join(root, name))
    return ""


def _make_evidence(
    *,
    task: TaskSpec,
    repo_path: str,
    tool_name: str,
    evidence_type: str,
    output: str,
    path: str = "",
    source_type: str = "source_code",
) -> EvidenceRecord:
    excerpt = (output or "").strip()
    if len(excerpt) > 1800:
        excerpt = excerpt[:1800] + "\n... [truncated]"
    rec = EvidenceRecord(
        evidence_id=f"ev_{task.task_id}_{uuid.uuid4().hex[:8]}",
        stage_id=task.stage_id,
        question_ids=[task.question_id] if task.question_id else [],
        task_id=task.task_id,
        path=path,
        source_type=source_type,
        evidence_type=evidence_type,
        tool_name=tool_name,
        excerpt=excerpt,
        metadata={"query": task.query},
    )
    return verify_evidence(rec, repo_path=repo_path)


def run_task_agent(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    try:
        if task.task_type in {"discovery", "implementation_state"}:
            return _run_rag_task(task, repo_path=repo_path)
        if task.task_type in {"definition", "flow"}:
            return _run_lsp_task(task, repo_path=repo_path)
        if task.task_type == "build_platform":
            return _run_build_platform_task(task, repo_path=repo_path)
        if task.task_type == "git_history":
            return _run_git_history_task(task, repo_path=repo_path)
        return _run_code_evidence_task(task, repo_path=repo_path)
    except Exception as exc:
        return (
            TaskResult(
                task_id=task.task_id,
                stage_id=task.stage_id,
                question_id=task.question_id,
                status="failed",
                errors=[f"{type(exc).__name__}: {exc}"],
                confidence="low",
            ),
            [],
        )


def _run_rag_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.file_ops import grep_in_repo, rag_search_code

    records: List[EvidenceRecord] = []
    query = task.query[:1000]
    out = _invoke_tool(rag_search_code, {"repo_path": repo_path, "query": query, "top_k": 5})
    paths = _extract_paths(out, repo_path)
    records.append(
        _make_evidence(
            task=task,
            repo_path=repo_path,
            tool_name="rag_search_code",
            evidence_type="semantic_search",
            output=out,
            path=paths[0] if paths else "",
        )
    )
    if not paths and task.metadata.get("keywords"):
        pattern = "|".join(re.escape(k) for k in task.metadata["keywords"][:4])
        grep_out = _invoke_tool(grep_in_repo, {"repo_path": repo_path, "pattern": pattern, "max_results": 20})
        grep_paths = _extract_paths(grep_out, repo_path)
        records.append(
            _make_evidence(
                task=task,
                repo_path=repo_path,
                tool_name="grep_in_repo",
                evidence_type="search",
                output=grep_out,
                path=grep_paths[0] if grep_paths else "",
            )
        )
    return _result_from_records(task, records), records


def _run_lsp_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.file_ops import grep_in_repo
    from tools.lsp_ops import lsp_get_call_graph, lsp_get_definition, lsp_get_document_outline

    records: List[EvidenceRecord] = []
    default_file_path = _first_existing_source_file(repo_path, task.seed_paths)
    symbols = [s for s in task.entry_symbols if s][:3]
    if not symbols:
        symbols = [k for k in task.metadata.get("keywords", []) if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k)][:3]
    for sym in symbols[:2]:
        grep_out = _invoke_tool(grep_in_repo, {"repo_path": repo_path, "pattern": re.escape(sym), "max_results": 5})
        grep_paths = _extract_paths(grep_out, repo_path)
        file_path = grep_paths[0] if grep_paths else default_file_path
        if task.task_type == "flow":
            out = _invoke_tool(lsp_get_call_graph, {"repo_path": repo_path, "file_path": file_path, "symbol": sym, "max_depth": 3})
            tool_name = "lsp_get_call_graph"
            evidence_type = "call_graph"
        else:
            out = _invoke_tool(lsp_get_definition, {"repo_path": repo_path, "file_path": file_path, "symbol": sym})
            tool_name = "lsp_get_definition"
            evidence_type = "definition"
        paths = _extract_paths(out, repo_path)
        records.append(
            _make_evidence(
                task=task,
                repo_path=repo_path,
                tool_name=tool_name,
                evidence_type=evidence_type,
                output=out,
                path=paths[0] if paths else "",
            )
        )
    if not records and task.seed_paths:
        candidate = default_file_path or task.seed_paths[0]
        out = _invoke_tool(lsp_get_document_outline, {"repo_path": repo_path, "file_path": candidate})
        records.append(
            _make_evidence(
                task=task,
                repo_path=repo_path,
                tool_name="lsp_get_document_outline",
                evidence_type="outline",
                output=out,
                path=_safe_rel_path(repo_path, candidate),
            )
        )
    return _result_from_records(task, records), records


def _run_code_evidence_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.file_ops import grep_in_repo

    pattern = "|".join(re.escape(k) for k in task.metadata.get("keywords", [])[:4]) or re.escape(task.question_id or task.stage_id)
    out = _invoke_tool(grep_in_repo, {"repo_path": repo_path, "pattern": pattern, "max_results": 20})
    paths = _extract_paths(out, repo_path)
    records = [
        _make_evidence(
            task=task,
            repo_path=repo_path,
            tool_name="grep_in_repo",
            evidence_type="search",
            output=out,
            path=paths[0] if paths else "",
        )
    ]
    return _result_from_records(task, records), records


def _run_build_platform_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.build_config_ops import parse_build_config

    out = _invoke_tool(parse_build_config, {"repo_path": repo_path})
    paths = _extract_paths(out, repo_path)
    records = [
        _make_evidence(
            task=task,
            repo_path=repo_path,
            tool_name="parse_build_config",
            evidence_type="build_config",
            output=out,
            path=paths[0] if paths else "README.md",
            source_type="documentation",
        )
    ]
    return _result_from_records(task, records), records


def _run_git_history_task(task: TaskSpec, *, repo_path: str) -> Tuple[TaskResult, List[EvidenceRecord]]:
    from tools.git_ops import get_git_history_summary

    out = _invoke_tool(get_git_history_summary, {"repo_path": repo_path, "max_commits": 30})
    records = [
        _make_evidence(
            task=task,
            repo_path=repo_path,
            tool_name="get_git_history_summary",
            evidence_type="git_history",
            output=out,
            path=".git",
            source_type="git_history",
        )
    ]
    return _result_from_records(task, records), records


def _result_from_records(task: TaskSpec, records: List[EvidenceRecord]) -> TaskResult:
    valid = [r for r in records if r.validity != "invalid"]
    if any(r.confidence == "high" for r in valid):
        confidence = "high"
    elif any(r.confidence == "medium" for r in valid):
        confidence = "medium"
    else:
        confidence = "low"
    return TaskResult(
        task_id=task.task_id,
        stage_id=task.stage_id,
        question_id=task.question_id,
        status="done" if valid else "failed",
        evidence_ids=[r.evidence_id for r in records],
        confidence=confidence,
        errors=[] if valid else ["no valid evidence"],
        metadata={"evidence_count": len(records)},
    )
