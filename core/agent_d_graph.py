from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict

from core.kernel_tree import ANALYSIS_BATCHES_V2, ANALYSIS_ORDER_V2, ROOT_NODES_V2, node_title_en, node_title_zh


_INCREMENTAL_TREE_LOCK = threading.Lock()


def _merge_dicts(current: dict[str, Any] | None, update: dict[str, Any] | None) -> dict[str, Any]:
    return {**(current or {}), **(update or {})}


def _merge_pending_results(current: dict[str, Any] | None, update: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(current or {})
    incoming = dict(update or {})
    for node_id in incoming.pop("__clear__", []) or []:
        merged.pop(str(node_id), None)
    merged.update(incoming)
    return merged


def _merge_active_node_states(current: dict[str, Any] | None, update: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only active/failed node details in the checkpointed graph state."""
    return _merge_pending_results(current, update)


class AgentDGraphState(TypedDict, total=False):
    run_id: str
    input_hash: str
    run_status: str
    current_batch_index: int
    completed_node_ids: list[str]
    failed_node_ids: list[str]
    blackboard: dict[str, Any]
    batch_snapshot: dict[str, Any]
    batch_node_ids: list[str]
    pending_node_results: Annotated[dict[str, dict[str, Any]], _merge_pending_results]
    node_run_states: Annotated[dict[str, dict[str, Any]], _merge_active_node_states]
    verifier_reports: list[dict[str, Any]]
    artifact_paths: dict[str, str]
    failure: str


@dataclass
class AgentDGraphRuntime:
    repo_name: str
    output_dir: Path
    recorder: Any
    snapshot: Callable[[], dict[str, Any]]
    analyze_node: Callable[[str, dict[str, Any]], dict[str, Any]]
    merge_results: Callable[[list[dict[str, Any]]], None]
    trace_flows: Callable[[], None]
    build_dependencies: Callable[[], None]
    global_consistency: Callable[[], None]
    generate_architecture: Callable[[], None]
    finalize: Callable[[], dict[str, str]]
    persist_debug: Callable[[], None]
    checkpointer: Any = None



_RUNTIMES: dict[str, AgentDGraphRuntime] = {}


def compute_input_hash(repo_path: str, *, taxonomy_paths: list[str], model_name: str, thinking: str, prompt_version: str = "agent-d-langgraph-v1") -> str:
    root = Path(repo_path).resolve()
    h = hashlib.sha256()
    h.update(str(root).encode())
    try:
        import subprocess

        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL)
        diff = subprocess.check_output(["git", "-C", str(root), "diff", "--binary", "HEAD"], stderr=subprocess.DEVNULL)
        h.update(head.encode())
        h.update(dirty.encode())
        h.update(diff)
        for rel in subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines():
            path = root / rel
            if path.is_file():
                h.update(rel.encode())
                h.update(path.read_bytes())
    except Exception:
        for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts):
            stat = path.stat()
            h.update(str(path.relative_to(root)).encode())
            h.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
    for raw in taxonomy_paths:
        path = Path(raw)
        if path.is_file():
            h.update(path.read_bytes())
    h.update(model_name.encode())
    h.update(thinking.encode())
    h.update(prompt_version.encode())
    return h.hexdigest()


def choose_run_id(output_dir: Path, input_hash: str, *, explicit_run_id: str = "", fresh: bool = False) -> tuple[str, bool]:
    manifest_path = output_dir / "run_manifest.json"
    previous: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    if explicit_run_id:
        return explicit_run_id, bool(previous.get("run_id") == explicit_run_id)
    if not fresh and previous.get("input_hash") == input_hash and previous.get("run_id"):
        return str(previous["run_id"]), True
    return f"run_{input_hash[:12]}_{uuid.uuid4().hex[:8]}", False


def run_langgraph(
    runtime: AgentDGraphRuntime,
    *,
    input_hash: str,
    run_id: str,
    resumed: bool,
    auto_resume: bool = True,
) -> dict[str, Any]:
    from langgraph.checkpoint.memory import InMemorySaver

    runtime.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime.output_dir / "run_manifest.json"
    previous = _read_json(manifest_path)
    if resumed and previous.get("state") == "complete" and previous.get("input_hash") == input_hash:
        artifacts = previous.get("artifact_paths") or {}
        if artifacts and all(Path(path).exists() for path in artifacts.values() if path):
            runtime.recorder.graph_event("run_reused", data={"run_id": run_id})
            return {"run_id": run_id, "run_status": "complete", "artifact_paths": artifacts, "reused": True}

    stack = ExitStack()
    checkpointer = _open_sqlite_checkpointer(runtime.output_dir / "checkpoints.sqlite", stack)
    if checkpointer is None:
        checkpointer = InMemorySaver()
        runtime.recorder.graph_event("checkpoint_warning", data={
            "summary": "langgraph-checkpoint-sqlite is not installed; this run uses in-memory checkpoints.",
        })
    runtime.checkpointer = checkpointer
    _RUNTIMES[run_id] = runtime
    graph = _build_graph(checkpointer)
    initial: AgentDGraphState = {
        "run_id": run_id,
        "input_hash": input_hash,
        "run_status": "running",
        "current_batch_index": 0,
        "completed_node_ids": [],
        "failed_node_ids": [],
        "blackboard": runtime.snapshot(),
        "batch_snapshot": {},
        "batch_node_ids": [],
        "pending_node_results": {},
        "node_run_states": {},
        "verifier_reports": [],
        "artifact_paths": {},
        "failure": "",
    }
    config = {
        "configurable": {"thread_id": run_id},
        "recursion_limit": int(os.environ.get("AGENT_D_GRAPH_RECURSION_LIMIT", "120")),
        "max_concurrency": max(1, int(os.environ.get("AGENT_D_NODE_CONCURRENCY", "1"))),
    }
    _write_manifest(manifest_path, run_id, input_hash, "running", {}, resumed)
    try:
        invoke_input: dict[str, Any] | None = initial
        if resumed and auto_resume and _has_checkpoint(graph, config):
            checkpoint_state = dict(graph.get_state(config).values or {})
            completed = set(checkpoint_state.get("completed_node_ids") or [])
            completed_results = _load_node_results(runtime.output_dir, completed)
            legacy_results = [
                result for node_id, result in (checkpoint_state.get("pending_node_results") or {}).items()
                if node_id in completed and result.get("status") == "done"
            ]
            known = {str(result.get("node_id") or "") for result in completed_results}
            completed_results.extend(result for result in legacy_results if str(result.get("node_id") or "") not in known)
            if completed_results:
                runtime.merge_results(completed_results)
                _persist_node_results(runtime.output_dir, completed_results)
            restart_index = int(checkpoint_state.get("current_batch_index") or 0)
            if checkpoint_state.get("run_status") == "failed":
                failed = list(checkpoint_state.get("failed_node_ids") or [])
                restart_index = min((_batch_index(node_id) for node_id in failed), default=int(checkpoint_state.get("current_batch_index") or 0))
            # A LangGraph checkpoint is a recovery boundary, not an audit log.
            # Re-seed from compact per-node results and discard the old global
            # history so repeated fan-out states cannot grow quadratically.
            _delete_thread(checkpointer, run_id)
            _cleanup_all_node_threads(checkpointer, run_id)
            invoke_input = {
                **initial,
                "current_batch_index": restart_index,
                "completed_node_ids": list(completed),
                "pending_node_results": {},
            }
            runtime.recorder.graph_event("run_resumed", data={"run_id": run_id, "completed_nodes": len(completed)})
        elif resumed and auto_resume:
            completed_results = _load_all_node_results(runtime.output_dir)
            if completed_results:
                runtime.merge_results(completed_results)
                completed = {str(result["node_id"]) for result in completed_results}
                invoke_input = {
                    **initial,
                    "current_batch_index": _first_incomplete_batch(completed),
                    "completed_node_ids": sorted(completed),
                    "pending_node_results": {},
                }
                runtime.recorder.graph_event("run_resumed", data={"run_id": run_id, "completed_nodes": len(completed)})
        result = graph.invoke(invoke_input, config=config)
        runtime.recorder.project_graph_state(result)
        _write_manifest(manifest_path, run_id, input_hash, str(result.get("run_status") or "failed"), result.get("artifact_paths") or {}, resumed)
        return result
    finally:
        _RUNTIMES.pop(run_id, None)
        stack.close()


def _build_graph(checkpointer: Any):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(AgentDGraphState)
    builder.add_node("BootstrapContext", _bootstrap)
    builder.add_node("InitializeTree", _initialize)
    builder.add_node("SelectBatch", _select_batch)
    builder.add_node("AnalyzeNode", _analyze_node)
    builder.add_node("MergeBatch", _merge_batch)
    builder.add_node("FlowTracer", _flow_tracer)
    builder.add_node("DependencyBuilder", _dependency_builder)
    builder.add_node("GlobalConsistency", _global_consistency)
    builder.add_node("ArchitectureGenerator", _architecture_generator)
    builder.add_node("Finalizer", _finalizer)
    builder.add_node("Complete", _complete)
    builder.add_edge(START, "BootstrapContext")
    builder.add_edge("BootstrapContext", "InitializeTree")
    builder.add_edge("InitializeTree", "SelectBatch")
    builder.add_conditional_edges("SelectBatch", _dispatch_batch, ["AnalyzeNode", "FlowTracer"])
    builder.add_edge("AnalyzeNode", "MergeBatch")
    builder.add_conditional_edges("MergeBatch", _after_merge, {"continue": "SelectBatch", "failed": "Complete"})
    builder.add_edge("FlowTracer", "DependencyBuilder")
    builder.add_edge("DependencyBuilder", "GlobalConsistency")
    builder.add_edge("GlobalConsistency", "ArchitectureGenerator")
    builder.add_edge("ArchitectureGenerator", "Finalizer")
    builder.add_edge("Finalizer", "Complete")
    builder.add_edge("Complete", END)
    return builder.compile(checkpointer=checkpointer)


def _runtime(state: AgentDGraphState) -> AgentDGraphRuntime:
    return _RUNTIMES[str(state["run_id"])]


def _bootstrap(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    rt.recorder.graph_event("graph_node", phase="bootstrap", data={"summary": "BootstrapContext"})
    rt.recorder.project_graph_state(state)
    return {"run_status": "running"}


def _initialize(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    rt.recorder.graph_event("graph_node", phase="initialize", data={"summary": "InitializeTree"})
    rt.persist_debug()
    return {}


def _select_batch(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    index = int(state.get("current_batch_index") or 0)
    if index >= len(ANALYSIS_BATCHES_V2):
        return {"batch_node_ids": [], "batch_snapshot": rt.snapshot()}
    limit = max(0, int(os.environ.get("AGENT_D_NODE_LIMIT", "0") or 0))
    completed = set(state.get("completed_node_ids") or [])
    if limit and len(completed) >= limit:
        return {"current_batch_index": len(ANALYSIS_BATCHES_V2), "batch_node_ids": [], "batch_snapshot": rt.snapshot()}
    batch = [node for node in ANALYSIS_BATCHES_V2[index] if node not in completed]
    if limit:
        batch = batch[: max(0, limit - len(completed))]
    rt.recorder.set_batch(f"{index + 1}/{len(ANALYSIS_BATCHES_V2)}: {', '.join(batch)}", index + 1)
    rt.recorder.graph_event("select_batch", data={"batch_index": index + 1, "nodes": batch})
    return {"batch_node_ids": batch, "batch_snapshot": rt.snapshot()}


def _dispatch_batch(state: AgentDGraphState):
    from langgraph.types import Send

    if int(state.get("current_batch_index") or 0) >= len(ANALYSIS_BATCHES_V2) or not state.get("batch_node_ids"):
        return "FlowTracer"
    return [
        Send("AnalyzeNode", {
            "run_id": state["run_id"],
            "batch_snapshot": state.get("batch_snapshot", {}),
            "batch_node_ids": [node_id],
            "pending_node_results": {},
        })
        for node_id in state.get("batch_node_ids") or []
    ]


def _analyze_node(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    node_id = state["batch_node_ids"][0]
    rt.recorder.set_node(node_id)
    rt.recorder.graph_event("graph_node", node_id=node_id, phase="react", data={"summary": "AnalyzeNode"})
    try:
        result = rt.analyze_node(node_id, state.get("batch_snapshot") or {})
        result.setdefault("node_id", node_id)
        result["status"] = "done"
        _persist_node_results(rt.output_dir, [result])
        _persist_incremental_tree_node(rt.output_dir, rt.repo_name, result)
    except Exception as exc:
        result = {"node_id": node_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        rt.recorder.graph_event("node_failed", node_id=node_id, phase="failed", data={"error": result["error"]})
    rt.recorder.checkpoint(node_id)
    return {
        "pending_node_results": {node_id: result},
        "node_run_states": {node_id: {
            "node_id": node_id,
            "phase": result["status"],
            "last_error": result.get("error", ""),
            "last_checkpoint_at": time.time(),
        }},
    }


def _merge_batch(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    batch_nodes = set(state.get("batch_node_ids") or [])
    results = [result for node_id, result in (state.get("pending_node_results") or {}).items() if node_id in batch_nodes]
    failed = [str(result["node_id"]) for result in results if result.get("status") == "failed"]
    successful = [result for result in results if result.get("status") == "done"]
    if successful:
        rt.merge_results(successful)
        _persist_node_results(rt.output_dir, successful)
        for result in successful:
            rt.recorder.node_done(str(result["node_id"]), int(result.get("claim_count") or 0), int(result.get("evidence_count") or 0))
            _cleanup_completed_node_threads(rt.checkpointer, str(state["run_id"]), {str(result["node_id"])})
    completed = list(dict.fromkeys([*(state.get("completed_node_ids") or []), *(str(result["node_id"]) for result in successful)]))
    rt.persist_debug()
    update = {
        "completed_node_ids": completed,
        "failed_node_ids": failed,
        "current_batch_index": int(state.get("current_batch_index") or 0) + (0 if failed else 1),
        "blackboard": rt.snapshot(),
        "verifier_reports": [
            report
            for result in successful
            for report in result.get("verifier_reports", [])
        ][-100:],
        "run_status": "failed" if failed else "running",
        "failure": "; ".join(str((state.get("pending_node_results") or {}).get(node, {}).get("error") or node) for node in failed),
        "pending_node_results": {"__clear__": list(batch_nodes)},
        "node_run_states": {"__clear__": [str(result["node_id"]) for result in successful]},
    }
    rt.recorder.project_graph_state({**state, **update})
    rt.recorder.checkpoint()
    return update


def _after_merge(state: AgentDGraphState) -> str:
    return "failed" if state.get("failed_node_ids") else "continue"


def _flow_tracer(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    if int(os.environ.get("AGENT_D_NODE_LIMIT", "0") or 0):
        return {}
    rt.recorder.graph_event("graph_node", phase="flow", data={"summary": "FlowTracer"})
    rt.trace_flows()
    return {}


def _dependency_builder(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    if int(os.environ.get("AGENT_D_NODE_LIMIT", "0") or 0):
        return {}
    rt.recorder.graph_event("graph_node", phase="dependency", data={"summary": "DependencyBuilder"})
    rt.build_dependencies()
    return {}


def _global_consistency(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    if int(os.environ.get("AGENT_D_NODE_LIMIT", "0") or 0):
        return {}
    rt.recorder.graph_event("graph_node", phase="consistency", data={"summary": "GlobalConsistency"})
    rt.global_consistency()
    return {}


def _architecture_generator(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    if int(os.environ.get("AGENT_D_NODE_LIMIT", "0") or 0):
        return {}
    rt.recorder.graph_event("graph_node", phase="architecture", data={"summary": "ArchitectureGenerator"})
    rt.generate_architecture()
    return {}


def _finalizer(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    rt.recorder.graph_event("graph_node", phase="finalize", data={"summary": "Finalizer"})
    artifacts = rt.finalize()
    return {"artifact_paths": artifacts, "run_status": "complete"}


def _complete(state: AgentDGraphState) -> dict[str, Any]:
    rt = _runtime(state)
    failure = state.get("failure") if state.get("run_status") == "failed" else None
    rt.recorder.finish(state.get("artifact_paths") or {}, failure=failure)
    return {}


def _open_sqlite_checkpointer(path: Path, stack: ExitStack):
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    return stack.enter_context(SqliteSaver.from_conn_string(str(path)))


def _has_checkpoint(graph: Any, config: dict[str, Any]) -> bool:
    try:
        snapshot = graph.get_state(config)
        return bool(snapshot and snapshot.values)
    except Exception:
        return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_manifest(path: Path, run_id: str, input_hash: str, state: str, artifacts: dict[str, str], resumed: bool) -> None:
    path.write_text(json.dumps({
        "schema_version": "agent_d.run_manifest.v1",
        "run_id": run_id,
        "input_hash": input_hash,
        "state": state,
        "artifact_paths": artifacts,
        "resumed": resumed,
        "updated_at": time.time(),
    }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _batch_index(node_id: str) -> int:
    for index, batch in enumerate(ANALYSIS_BATCHES_V2):
        if node_id in batch:
            return index
    return 0


def _node_result_dir(output_dir: Path) -> Path:
    return output_dir / "_state" / "node_results"


def _node_result_path(output_dir: Path, node_id: str) -> Path:
    safe = node_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    return _node_result_dir(output_dir) / f"{safe}.json"


def _persist_node_results(output_dir: Path, results: list[dict[str, Any]]) -> None:
    root = _node_result_dir(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    for result in results:
        node_id = str(result.get("node_id") or "")
        if not node_id or result.get("status") != "done":
            continue
        path = _node_result_path(output_dir, node_id)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)


def _persist_incremental_tree_node(output_dir: Path, repo_name: str, result: dict[str, Any]) -> None:
    path = output_dir / "kernel_design_tree.json"
    with _INCREMENTAL_TREE_LOCK:
        current = _read_json(path)
        nodes = dict(current.get("_incremental_nodes") or {})
        claims = dict(current.get("claims") or {})
        node_id = str(result.get("node_id") or "")
        if node_id and isinstance(result.get("node"), dict):
            nodes[node_id] = result["node"]
        for claim in result.get("claims") or []:
            if isinstance(claim, dict) and claim.get("claim_id"):
                claims[str(claim["claim_id"])] = claim
        children: list[dict[str, Any]] = []
        for root, leaves in ROOT_NODES_V2.items():
            if not leaves:
                children.append(nodes.get(root) or _pending_node(root))
                continue
            children.append({
                "node_id": root,
                "title_zh": node_title_zh(root),
                "title_en": node_title_en(root),
                "children": [nodes.get(f"{root}.{leaf}") or _pending_node(f"{root}.{leaf}") for leaf in leaves],
            })
        payload = {
            "schema_version": "agent_d.kernel_project.v2",
            "run_status": "in_progress",
            "repo_name": repo_name,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "root": {
                "node_id": "KernelProject",
                "title_zh": "内核项目设计树",
                "title_en": "KernelProject",
                "children": children,
            },
            "claims": claims,
            "_incremental_nodes": nodes,
        }
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)


def _pending_node(node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "status": "pending",
        "title_zh": node_title_zh(node_id),
        "title_en": node_title_en(node_id),
        "claim_ids": [],
        "evidence_ids": [],
    }


def _load_node_results(output_dir: Path, completed: set[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node_id in sorted(completed):
        raw = _read_json(_node_result_path(output_dir, node_id))
        if raw.get("status") == "done":
            results.append(raw)
    return results


def _load_all_node_results(output_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    root = _node_result_dir(output_dir)
    if not root.is_dir():
        return results
    for path in sorted(root.glob("*.json")):
        raw = _read_json(path)
        if raw.get("status") == "done" and raw.get("node_id"):
            results.append(raw)
    return results


def _delete_thread(checkpointer: Any, thread_id: str) -> None:
    try:
        checkpointer.delete_thread(thread_id)
    except Exception:
        pass


def _cleanup_completed_node_threads(checkpointer: Any, run_id: str, node_ids: set[str]) -> None:
    max_attempts = max(1, int(os.environ.get("AGENT_D_REPAIR_ROUNDS", "2")) + 1)
    for node_id in node_ids:
        _delete_thread(checkpointer, f"{run_id}/nodes/{node_id}")
        for attempt in range(max_attempts):
            _delete_thread(checkpointer, f"{run_id}/nodes/{node_id}/react/{attempt}")


def _cleanup_all_node_threads(checkpointer: Any, run_id: str) -> None:
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return
    try:
        rows = conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE ?",
            (f"{run_id}/nodes/%",),
        ).fetchall()
    except Exception:
        return
    for (thread_id,) in rows:
        _delete_thread(checkpointer, str(thread_id))


def compact_existing_checkpoint(output_dir: str | Path, run_id: str) -> dict[str, Any]:
    """Migrate a legacy unbounded checkpoint into compact per-node results."""
    from contextlib import ExitStack

    output = Path(output_dir)
    db_path = output / "checkpoints.sqlite"
    if not db_path.is_file():
        return {"status": "skipped", "reason": "checkpoint database not found"}
    with ExitStack() as stack:
        checkpointer = _open_sqlite_checkpointer(db_path, stack)
        if checkpointer is None:
            return {"status": "skipped", "reason": "SQLite checkpointer unavailable"}
        checkpoint = checkpointer.get({"configurable": {"thread_id": run_id}}) or {}
        values = dict(checkpoint.get("channel_values") or {})
        completed = set(values.get("completed_node_ids") or [])
        results = [
            result
            for node_id, result in (values.get("pending_node_results") or {}).items()
            if node_id in completed and isinstance(result, dict) and result.get("status") == "done"
        ]
        _persist_node_results(output, results)
        _delete_thread(checkpointer, run_id)
        _cleanup_all_node_threads(checkpointer, run_id)
    try:
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
    except Exception:
        pass
    return {
        "status": "compacted",
        "completed_nodes": len(completed),
        "persisted_results": len(results),
        "database_bytes": db_path.stat().st_size,
    }


def _first_incomplete_batch(completed: set[str]) -> int:
    for index, batch in enumerate(ANALYSIS_BATCHES_V2):
        if any(node_id not in completed for node_id in batch):
            return index
    return len(ANALYSIS_BATCHES_V2)
