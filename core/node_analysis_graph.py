from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypedDict


class NodeAnalysisState(TypedDict, total=False):
    runtime_key: str
    node_id: str
    status: str
    attempt: int
    max_attempts: int
    draft: dict[str, Any]
    verifier_errors: list[str]
    verifier_report: dict[str, Any]
    result: dict[str, Any]
    failure: str


@dataclass
class NodeAnalysisRuntime:
    react: Callable[[list[str], int], dict[str, Any]]
    verify: Callable[[dict[str, Any], int], dict[str, Any]]
    commit: Callable[[dict[str, Any], int], dict[str, Any]]
    cleanup_attempt: Callable[[int], None] | None = None
    recorder: Any = None


_RUNTIMES: dict[str, NodeAnalysisRuntime] = {}


def run_node_analysis_graph(
    *,
    run_id: str,
    node_id: str,
    runtime: NodeAnalysisRuntime,
    checkpointer: Any,
    max_attempts: int,
) -> dict[str, Any]:
    key = f"{run_id}/nodes/{node_id}"
    _RUNTIMES[key] = runtime
    graph = _build_graph(checkpointer)
    initial: NodeAnalysisState = {
        "runtime_key": key,
        "node_id": node_id,
        "status": "running",
        "attempt": 0,
        "max_attempts": max_attempts,
        "draft": {},
        "verifier_errors": [],
        "verifier_report": {},
        "result": {},
        "failure": "",
    }
    try:
        return graph.invoke(
            initial,
            config={"configurable": {"thread_id": key}, "recursion_limit": max(12, max_attempts * 5)},
        )
    finally:
        _RUNTIMES.pop(key, None)


def _build_graph(checkpointer: Any):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(NodeAnalysisState)
    builder.add_node("ReActAgent", _react)
    builder.add_node("ProgramVerifier", _verify)
    builder.add_node("CommitNodeResult", _commit)
    builder.add_node("FailedNode", _failed)
    builder.add_edge(START, "ReActAgent")
    builder.add_edge("ReActAgent", "ProgramVerifier")
    builder.add_conditional_edges(
        "ProgramVerifier",
        _after_verify,
        {"commit": "CommitNodeResult", "repair": "ReActAgent", "failed": "FailedNode"},
    )
    builder.add_edge("CommitNodeResult", END)
    builder.add_edge("FailedNode", END)
    return builder.compile(checkpointer=checkpointer)


def _runtime(state: NodeAnalysisState) -> NodeAnalysisRuntime:
    return _RUNTIMES[state["runtime_key"]]


def _react(state: NodeAnalysisState) -> dict[str, Any]:
    runtime = _runtime(state)
    attempt = int(state.get("attempt") or 0)
    if runtime.recorder:
        runtime.recorder.graph_event(
            "node_subgraph",
            node_id=state["node_id"],
            phase="react",
            data={"summary": "ReActAgent", "react_step": attempt + 1, "repair_attempt": attempt},
        )
    try:
        draft = runtime.react(list(state.get("verifier_errors") or []), attempt)
        return {"draft": draft, "attempt": attempt + 1, "failure": ""}
    except Exception as exc:
        error = f"LangChain ReAct node run failed: {type(exc).__name__}: {exc}"
        return {"draft": {}, "attempt": attempt + 1, "verifier_errors": [error], "failure": error}


def _verify(state: NodeAnalysisState) -> dict[str, Any]:
    runtime = _runtime(state)
    attempt = int(state.get("attempt") or 1)
    if state.get("draft"):
        report = runtime.verify(state["draft"], attempt)
    else:
        report = {"node_id": state["node_id"], "status": "error", "errors": list(state.get("verifier_errors") or ["missing NodeDraft"])}
    if runtime.recorder:
        runtime.recorder.graph_event(
            "node_subgraph",
            node_id=state["node_id"],
            phase="verifier",
            data={"summary": "ProgramVerifier", "repair_attempt": max(0, attempt - 1), "error": "; ".join(report.get("errors") or [])},
        )
        runtime.recorder.checkpoint(state["node_id"])
    if runtime.cleanup_attempt:
        runtime.cleanup_attempt(max(0, attempt - 1))
    return {"verifier_report": report, "verifier_errors": list(report.get("errors") or [])}


def _after_verify(state: NodeAnalysisState) -> str:
    if not (state.get("verifier_report") or {}).get("errors"):
        return "commit"
    if int(state.get("attempt") or 0) < int(state.get("max_attempts") or 1):
        return "repair"
    return "failed"


def _commit(state: NodeAnalysisState) -> dict[str, Any]:
    runtime = _runtime(state)
    result = runtime.commit(state["draft"], int(state.get("attempt") or 1))
    if runtime.recorder:
        runtime.recorder.graph_event("node_subgraph", node_id=state["node_id"], phase="commit", data={"summary": "CommitNodeResult"})
        runtime.recorder.checkpoint(state["node_id"])
    return {"status": "done", "result": result, "failure": ""}


def _failed(state: NodeAnalysisState) -> dict[str, Any]:
    errors = list((state.get("verifier_report") or {}).get("errors") or state.get("verifier_errors") or [])
    failure = f"NodeDraft failed verifier after {state.get('attempt', 0)} attempt(s): {errors}"
    return {"status": "failed", "failure": failure}
