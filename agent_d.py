from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import copy
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock, Semaphore
from typing import Any

from dotenv import load_dotenv

from tools.build_config_ops import parse_build_config_structured
from core.code_atlas.builder import build_code_atlas

from core.evidence import EvidenceStore, read_text_head, search_repo, stable_id
from core.kernel_glossary import compact_glossary_for_node, glossary_lookup, load_kernel_glossary
from core.kernel_tree import ANALYSIS_BATCHES_V2, ANALYSIS_ORDER_V2, ROOT_NODES_V2, apply_kernel_taxonomy, node_title_en, node_title_zh
from core.publish import publish_agent_d
from core.run_recorder import RunRecorder
from core.run_journal import RunJournal

load_dotenv(override=True)


ROOT_NODES: dict[str, list[str]] = ROOT_NODES_V2
ANALYSIS_ORDER = ANALYSIS_ORDER_V2
_LLM_SEMAPHORE: Semaphore | None = None
_LLM_SEMAPHORE_LOCK = Lock()
_LSP_SEMAPHORE: Semaphore | None = None
_LSP_SEMAPHORE_LOCK = Lock()


@dataclass
class Claim:
    claim_id: str
    node_id: str
    status: str
    claim_type: str
    canonical_tag: str
    statement_zh: str
    statement_en: str
    evidence_ids: list[str]
    confidence: str = "high"
    maturity: str = "simplified"


@dataclass
class Flow:
    flow_id: str
    title_zh: str
    title_en: str
    role_sequence: list[str]
    steps: list[dict[str, Any]]
    evidence_ids: list[str]


@dataclass
class Dependency:
    dependency_id: str
    src: str
    dst: str
    relation: str
    reason_zh: str
    evidence_ids: list[str]


@dataclass
class Blackboard:
    repo_path: str
    repo_name: str
    output_dir: str
    concepts: dict[str, Any]
    vocab: dict[str, Any]
    glossary: dict[str, dict[str, Any]]
    build: dict[str, Any]
    atlas: dict[str, Any]
    evidence: EvidenceStore
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    flows: dict[str, Flow] = field(default_factory=dict)
    dependencies: dict[str, Dependency] = field(default_factory=dict)
    extension_requests: list[dict[str, Any]] = field(default_factory=list)
    current_batch_snapshot: dict[str, Any] | None = None
    recorder: RunRecorder | None = None
    journal: RunJournal | None = None
    checkpointer: Any = None
    run_id: str = ""

    def claim(self, node_id: str, status: str, tag: str, zh: str, en: str, evidence_ids: list[str], claim_type: str = "mechanism", confidence: str = "high", maturity: str = "simplified") -> str:
        cid = stable_id("claim", {"node": node_id, "tag": tag, "evidence": sorted(evidence_ids)})
        self.claims[cid] = Claim(cid, node_id, status, claim_type, tag, zh, en, evidence_ids, confidence, maturity)
        return cid


def run_agent_d(
    repo_path: str,
    output_dir: str,
    repo_name: str | None = None,
    progress_cb=None,
    *,
    fresh: bool = False,
    run_id: str = "",
    tui: bool = False,
) -> dict[str, Any]:
    from core.agent_d_graph import AgentDGraphRuntime, choose_run_id, compute_input_hash, run_langgraph
    from core.tui_dashboard import TUIDashboard

    started = time.time()
    repo_path = str(Path(repo_path).resolve())
    repo_name = repo_name or Path(repo_path).name
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if fresh:
        _clear_resumable_state(out)
    _strict_llm_prelight()
    recorder_total = int(os.environ.get("AGENT_D_NODE_LIMIT", "0") or "0") or len(ANALYSIS_ORDER)
    root = Path(__file__).parent / "core"
    input_hash = compute_input_hash(
        repo_path,
        taxonomy_paths=[
            str(root / "kernel_concepts.json"),
            str(root / "kernel_mechanism_vocab.json"),
            str(root / "kernel_glossary.json"),
            str(root / "kernel_tree.py"),
            str(root / "node_react_agent.py"),
            str(root / "node_analysis_graph.py"),
            str(Path(__file__).resolve()),
        ],
        model_name=os.environ.get("MODEL_NAME", ""),
        thinking=f"{os.environ.get('AGENT_D_THINKING', 'enabled')}:{os.environ.get('AGENT_D_REASONING_EFFORT', 'high')}",
    )
    selected_run_id, resumed = choose_run_id(out, input_hash, explicit_run_id=run_id, fresh=fresh)
    recorder = RunRecorder(str(out), repo_name, min(recorder_total, len(ANALYSIS_ORDER)), run_id=selected_run_id, resumed=resumed)
    journal = RunJournal(out, resumed=resumed)
    concepts = json.loads((root / "kernel_concepts.json").read_text(encoding="utf-8"))
    vocab = json.loads((root / "kernel_mechanism_vocab.json").read_text(encoding="utf-8"))
    concepts, vocab, node_specs = apply_kernel_taxonomy(concepts, vocab, NODE_SPECS)
    NODE_SPECS.clear()
    NODE_SPECS.update(node_specs)
    cb = progress_cb or (lambda stage, info: None)

    cb("context", "parse build config and code atlas")
    recorder.event("context_start", {"stage": "parse build config and code atlas"})
    build = parse_build_config_structured(repo_path)
    lsp_target_result = _try_set_lsp_target(repo_path, build.get("target_arch"))
    atlas = _build_atlas(repo_path, repo_name, out)
    glossary = load_kernel_glossary(vocab)
    bb = Blackboard(repo_path, repo_name, str(out), concepts, vocab, glossary, build, atlas, EvidenceStore(repo_path, str(out / "evidence_store.jsonl")))
    bb.recorder = recorder
    bb.journal = journal
    bb.run_id = selected_run_id
    _journal(bb, "trace", {"stage": "context", "lsp_target": lsp_target_result})

    _seed_build_evidence(bb)
    _seed_symbol_evidence(bb)
    _init_tree(bb)

    def analyze_node(node_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        cb("node", node_id)
        child = _fork_blackboard(bb, snapshot)
        child.checkpointer = runtime.checkpointer
        _fill_node_deep(child, node_id)
        return _node_result(child, node_id)

    def merge_results(results: list[dict[str, Any]]) -> None:
        _merge_node_results(bb, results)
        bb.current_batch_snapshot = None
        _journal(bb, "blackboard", _blackboard_summary(bb))
        _evict_completed_node_details(bb, [str(result["node_id"]) for result in results])

    def finalize() -> dict[str, str]:
        _hydrate_nodes_from_disk(bb, out)
        _attach_refs(bb)
        tree = _finalize_tree(bb, started)
        compare_index = _build_compare_index(bb, tree)
        judge_view = _build_judge_view(bb, tree, compare_index)
        _write_json(out / "kernel_design_tree.json", tree)
        bb.evidence.write_jsonl(str(out / "evidence_store.jsonl"))
        _write_json(out / "compare_index.json", compare_index)
        _write_json(out / "judge_view.json", judge_view)
        _write_json(out / "claim_glossary.json", {k: v for k, v in bb.glossary.items() if ":" in k})
        html = publish_agent_d(str(out))
        _write_debug_artifacts(out, bb)
        return {
            "kernel_design_tree": str(out / "kernel_design_tree.json"),
            "evidence_store": str(out / "evidence_store.jsonl"),
            "compare_index": str(out / "compare_index.json"),
            "judge_view": str(out / "judge_view.json"),
            "claim_glossary": str(out / "claim_glossary.json"),
            "index_html": html,
        }

    runtime = AgentDGraphRuntime(
        repo_name=repo_name,
        output_dir=out,
        recorder=recorder,
        snapshot=lambda: _blackboard_summary(bb),
        analyze_node=analyze_node,
        merge_results=merge_results,
        trace_flows=lambda: _trace_flows_deep(bb),
        build_dependencies=lambda: _build_dependencies_deep(bb),
        global_consistency=lambda: (_attach_refs(bb), _global_consistency_pass(bb)),
        finalize=finalize,
        persist_debug=lambda: _write_debug_artifacts(out, bb),
    )
    auto_resume = os.environ.get("AGENT_D_AUTO_RESUME", "true").lower() in {"1", "true", "yes", "on"}
    try:
        with TUIDashboard(recorder, enabled=tui):
            graph_result = run_langgraph(runtime, input_hash=input_hash, run_id=selected_run_id, resumed=resumed, auto_resume=auto_resume)
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        _write_debug_artifacts(out, bb, failure=failure)
        recorder.finish({}, failure=failure)
        raise
    artifacts = graph_result.get("artifact_paths") or {}
    if graph_result.get("run_status") != "complete":
        raise RuntimeError(graph_result.get("failure") or "Agent D LangGraph run did not complete")
    return {
        **artifacts,
        "run_id": selected_run_id,
        "resumed": resumed,
        "reused": bool(graph_result.get("reused")),
        "node_count": len(bb.nodes),
        "claim_count": len(bb.claims),
        "evidence_count": len(bb.evidence.records),
        "elapsed_seconds": round(time.time() - started, 2),
    }


def _fork_blackboard(bb: Blackboard, snapshot: dict[str, Any]) -> Blackboard:
    child = Blackboard(
        bb.repo_path,
        bb.repo_name,
        bb.output_dir,
        bb.concepts,
        bb.vocab,
        bb.glossary,
        bb.build,
        bb.atlas,
        bb.evidence,
        nodes=copy.deepcopy(bb.nodes),
        claims=copy.deepcopy(bb.claims),
        flows=copy.deepcopy(bb.flows),
        dependencies=copy.deepcopy(bb.dependencies),
        extension_requests=[],
        current_batch_snapshot=copy.deepcopy(snapshot),
        recorder=bb.recorder,
        journal=bb.journal,
        checkpointer=bb.checkpointer,
        run_id=bb.run_id,
    )
    return child


def _node_result(child: Blackboard, node_id: str) -> dict[str, Any]:
    claim_ids = child.nodes[node_id].get("claim_ids", [])
    return {
        "node_id": node_id,
        "node": copy.deepcopy(child.nodes[node_id]),
        "claims": [asdict(child.claims[cid]) for cid in claim_ids if cid in child.claims],
        "dependencies": [asdict(dep) for dep in child.dependencies.values() if dep.src == node_id],
        "flows": [asdict(flow) for flow in child.flows.values() if any(step.get("evidence_id") in child.nodes[node_id].get("evidence_ids", []) for step in flow.steps)],
        "extension_requests": copy.deepcopy(child.extension_requests),
        "claim_count": len(claim_ids),
        "evidence_count": len(child.nodes[node_id].get("evidence_ids", [])),
    }


def _merge_node_results(bb: Blackboard, results: list[dict[str, Any]]) -> None:
    for result in sorted(results, key=lambda row: ANALYSIS_ORDER.index(row["node_id"])):
        node_id = result["node_id"]
        bb.nodes[node_id] = result["node"]
        for raw in result.get("claims", []):
            claim = Claim(**raw)
            bb.claims[claim.claim_id] = claim
        for raw in result.get("dependencies", []):
            dep = Dependency(**raw)
            bb.dependencies[dep.dependency_id] = dep
        for raw in result.get("flows", []):
            flow = Flow(**raw)
            bb.flows[flow.flow_id] = flow
        known_extensions = {
            (str(item.get("node_id") or ""), str(item.get("tag") or ""))
            for item in bb.extension_requests
            if isinstance(item, dict)
        }
        for item in result.get("extension_requests", []):
            if not isinstance(item, dict):
                continue
            key = (str(item.get("node_id") or node_id), str(item.get("tag") or ""))
            if key in known_extensions:
                continue
            bb.extension_requests.append(item)
            known_extensions.add(key)
        _journal(bb, "trace", {"node_id": node_id, "filled_claims": bb.nodes[node_id].get("claim_ids", []), "mode": "langchain_react"})


def _evict_completed_node_details(bb: Blackboard, node_ids: list[str]) -> None:
    """Keep only the compact cross-node memory needed by later analysis."""
    keep = {
        "node_id", "status", "confidence", "title_zh", "title_en",
        "summary_zh", "summary_en", "mechanisms", "key_symbols",
        "claim_ids", "flow_ids", "dependency_ids", "evidence_ids",
        "compare_tags", "not_for_compare", "concept_scope",
    }
    for node_id in node_ids:
        node = bb.nodes.get(node_id)
        if not node:
            continue
        compact = {key: value for key, value in node.items() if key in keep}
        compact["summary_zh"] = str(compact.get("summary_zh") or "")[:240]
        compact["summary_en"] = str(compact.get("summary_en") or "")[:240]
        compact["mechanisms"] = list(compact.get("mechanisms") or [])[:8]
        compact["key_symbols"] = list(compact.get("key_symbols") or [])[:12]
        compact["claim_ids"] = list(compact.get("claim_ids") or [])[:12]
        compact["evidence_ids"] = list(compact.get("evidence_ids") or [])[:16]
        bb.nodes[node_id] = compact


def _hydrate_nodes_from_disk(bb: Blackboard, output_dir: Path) -> None:
    root = output_dir / "_state" / "node_results"
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.json")):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if result.get("status") != "done" or not isinstance(result.get("node"), dict):
            continue
        bb.nodes[str(result["node_id"])] = result["node"]


def _build_atlas(repo_path: str, repo_name: str, output_dir: Path) -> dict[str, Any]:
    atlas = build_code_atlas(repo_path=repo_path, repo_name=repo_name)
    _write_json(output_dir / "code_atlas.json", atlas)
    return _compact_atlas(atlas)


def _clear_resumable_state(output_dir: Path) -> None:
    state_dir = (output_dir / "_state").resolve()
    output_root = output_dir.resolve()
    if state_dir.parent != output_root:
        raise RuntimeError(f"refusing to clear state outside output directory: {state_dir}")
    if state_dir.exists():
        shutil.rmtree(state_dir)
    for path in output_dir.glob("checkpoints.sqlite*"):
        if path.is_file():
            path.unlink()
    for name in ("run_manifest.json", "kernel_design_tree.json"):
        path = output_dir / name
        if path.is_file():
            path.unlink()


def _compact_atlas(atlas: dict[str, Any]) -> dict[str, Any]:
    compact = {key: value for key, value in atlas.items() if key not in {"functions", "types", "edges"}}
    functions = atlas.get("functions", {})
    items = functions.items() if isinstance(functions, dict) else enumerate(functions or [])
    compact_functions: dict[str, dict[str, Any]] = {}
    for fn_id, fn in items:
        row = dict(fn)
        row.setdefault("fn_id", str(fn_id))
        row["body_text"] = str(row.get("body_text") or "")[:1200]
        tokens = row.get("tokens_normalized") or row.get("normalized_tokens") or []
        if isinstance(tokens, list):
            row["tokens_normalized"] = tokens[:400]
            row.pop("normalized_tokens", None)
        compact_functions[str(fn_id)] = row
    compact["functions"] = compact_functions
    types = atlas.get("types", {})
    type_items = types.items() if isinstance(types, dict) else enumerate(types or [])
    compact["types"] = {
        str(type_id): {
            key: value
            for key, value in dict(item).items()
            if key in {"name", "file", "path", "line", "kind", "signature"}
        }
        for type_id, item in type_items
    }
    compact["edges"] = list(atlas.get("edges") or [])[:10000]
    return compact


def _try_set_lsp_target(repo_path: str, target_arch: Any) -> dict[str, Any]:
    if not target_arch or str(target_arch) == "unknown":
        return {"status": "skipped", "reason": "unknown target_arch"}
    try:
        from tools.lsp_ops import lsp_set_target_arch

        result = _invoke_tool(lsp_set_target_arch, repo_path=repo_path, target=str(target_arch))
        return {"status": "ok", "target_arch": str(target_arch), "result": str(result)[:500]}
    except Exception as exc:
        return {"status": "failed", "target_arch": str(target_arch), "error": f"{type(exc).__name__}: {exc}"}


def _init_tree(bb: Blackboard) -> None:
    for root, leaves in ROOT_NODES.items():
        if not leaves:
            _new_node(bb, root)
        for leaf in leaves:
            _new_node(bb, f"{root}.{leaf}")


def _new_node(bb: Blackboard, node_id: str) -> None:
    c = bb.concepts.get(node_id, {})
    bb.nodes[node_id] = {
        "node_id": node_id,
        "status": "unknown",
        "confidence": "low",
        "title_zh": c.get("title_zh") or node_title_zh(node_id),
        "title_en": c.get("title_en") or node_title_en(node_id),
        "concept_definition": c.get("definition", ""),
        "summary_zh": "",
        "summary_en": "",
        "responsibilities": [],
        "mechanisms": [],
        "policies": [],
        "data_structures": [],
        "interfaces": [],
        "negative_features": [],
        "design_choices": [],
        "key_symbols": [],
        "claim_ids": [],
        "flow_ids": [],
        "dependency_ids": [],
        "evidence_ids": [],
        "compare_tags": [],
        "not_for_compare": node_id == "EvolutionHistory",
        "concept_scope": c,
    }


def _strict_llm_prelight() -> None:
    os.environ.setdefault("AGENT_D_THINKING", "enabled")
    os.environ.setdefault("AGENT_D_REASONING_EFFORT", "high")
    os.environ.setdefault("AGENT_D_STRICT_THINKING", "true")
    os.environ.setdefault("AGENT_D_MAX_OUTPUT_TOKENS", "32768")
    os.environ.setdefault("AGENT_D_CONTEXT_BUDGET_TOKENS", "120000")
    os.environ.setdefault("AGENT_D_NODE_CONCURRENCY", "4")
    os.environ.setdefault("AGENT_D_LLM_CONCURRENCY", "4")
    os.environ.setdefault("AGENT_D_LSP_CONCURRENCY", "2")
    os.environ.setdefault("AGENT_D_EVIDENCE_CONCURRENCY", "8")
    os.environ.setdefault("AGENT_D_MEMORY_WAIT_SECONDS", "20")
    os.environ.setdefault("AGENT_D_REPAIR_ROUNDS", "2")
    if not _llm_enabled():
        raise RuntimeError("Agent D requires a valid OPENAI_API_KEY / OPENAI_API_BASE / MODEL_NAME configuration.")


def _fill_node_deep(bb: Blackboard, node_id: str) -> None:
    from core.node_analysis_graph import NodeAnalysisRuntime, run_node_analysis_graph
    from core.node_react_agent import run_node_react_agent

    pack = _build_evidence_pack(bb, node_id)
    max_attempts = max(1, int(os.environ.get("AGENT_D_REPAIR_ROUNDS", "2")) + 1)

    def execute_request(request: dict[str, Any], phase: str) -> dict[str, Any]:
        added = _run_evidence_requests(bb, node_id, [request], pack, phase=phase)
        evidence_ids = [eid for eid in added if eid in bb.evidence.records]
        return {
            "tool": request.get("tool"),
            "added_evidence_ids": evidence_ids,
            "concept_results": [item for item in added if str(item).startswith("glossary:")],
            "evidence": _evidence_for_llm(bb, evidence_ids),
        }

    def react(repair_errors: list[str], attempt: int) -> dict[str, Any]:
        return run_node_react_agent(
            node_id=node_id,
            node_context={
                "node_identity": pack["node_identity"],
                "concept_card": pack["concept"],
                # candidate_vocab carries only tag+role; human-readable definitions
                # are served once via glossary_context to avoid sending the same
                # tags' titles/descriptions twice.
                "candidate_vocab": _compact_vocab_for_llm(pack["vocab"]),
                "glossary_context": pack["glossary_context"],
                "navigation_hints": pack["navigation_hints"],
                "blackboard_compact": pack["blackboard"],
                "verified_evidence": pack["evidence"],
            },
            execute_request=execute_request,
            checkpointer=bb.checkpointer,
            thread_id=f"{bb.run_id or bb.repo_name}/nodes/{node_id}/react/{attempt}",
            verifier_feedback=repair_errors,
            recorder=bb.recorder,
        )

    def verify(draft: dict[str, Any], attempt: int) -> dict[str, Any]:
        _normalize_extension_tags(bb, node_id, draft)
        _normalize_absence_evidence(bb, node_id, draft, pack)
        report = _verify_node_draft(bb, node_id, draft)
        if report["errors"] and attempt >= max_attempts:
            rejected = _prune_unverified_claims(bb, node_id, draft)
            if rejected:
                report = _verify_node_draft(bb, node_id, draft)
                report["rejected_claims"] = rejected
        report["repair_attempt"] = max(0, attempt - 1)
        _journal(bb, "verifier", report)
        if bb.recorder:
            bb.recorder.verifier(report)
        _journal(bb, "llm_draft", {"node_id": node_id, "attempt": attempt, "draft": draft, "verified": not report["errors"], "errors": report["errors"]})
        return report

    def commit(draft: dict[str, Any], attempt: int) -> dict[str, Any]:
        _apply_node_draft(bb, node_id, draft, pack)
        return {"node_id": node_id, "attempt": attempt, "claim_ids": list(bb.nodes[node_id].get("claim_ids", []))}

    def cleanup_attempt(attempt: int) -> None:
        if bb.checkpointer is None:
            return
        try:
            bb.checkpointer.delete_thread(f"{bb.run_id or bb.repo_name}/nodes/{node_id}/react/{attempt}")
        except Exception:
            pass

    result = run_node_analysis_graph(
        run_id=bb.run_id or bb.repo_name,
        node_id=node_id,
        runtime=NodeAnalysisRuntime(
            react=react,
            verify=verify,
            commit=commit,
            cleanup_attempt=cleanup_attempt,
            recorder=bb.recorder,
        ),
        checkpointer=bb.checkpointer,
        max_attempts=max_attempts,
    )
    if result.get("status") != "done":
        raise RuntimeError(result.get("failure") or f"Node analysis failed for {node_id}")


def _prune_unverified_claims(bb: Blackboard, node_id: str, draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject unsupported LLM claims after repair is exhausted.

    The verifier may discard claims, but it never invents or strengthens them.
    """
    claims = list(draft.get("claims") or [])
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for claim in claims:
        probe = dict(draft)
        probe["claims"] = [claim]
        errors = _verify_node_draft(bb, node_id, probe)["errors"]
        claim_errors = [error for error in errors if error.startswith("claim[")]
        if claim_errors:
            rejected.append({"canonical_tag": claim.get("canonical_tag", ""), "errors": claim_errors})
        else:
            kept.append(claim)
    draft["claims"] = kept
    valid_tags = {str(claim.get("canonical_tag") or "") for claim in kept}
    draft["mechanisms"] = [tag for tag in draft.get("mechanisms", []) if tag in valid_tags]
    return rejected


def _compact_vocab_for_llm(vocab: dict[str, Any]) -> dict[str, Any]:
    """Strip vocab down to tag + compare_role for the prompt.

    Full titles/definitions for these tags are sent once via glossary_context,
    so re-sending them inside candidate_vocab is pure token duplication.
    """
    mechanisms = []
    for item in vocab.get("mechanisms", []) or []:
        if not isinstance(item, dict) or not item.get("tag"):
            continue
        row = {"tag": item["tag"], "compare_role": item.get("compare_role", "primary")}
        if item.get("category") and item["category"] != "mechanism":
            row["category"] = item["category"]
        mechanisms.append(row)
    out = {"mechanisms": mechanisms}
    if vocab.get("navigation_hints"):
        out["navigation_hints"] = vocab["navigation_hints"]
    return out


def _build_evidence_pack(bb: Blackboard, node_id: str) -> dict[str, Any]:
    specs = NODE_SPECS.get(node_id, {})
    evidence_ids: list[str] = []
    key_symbols: list[dict[str, Any]] = []

    if node_id == "Metadata":
        evidence_ids.extend(h["evidence_id"] for h in bb.build.get("_evidence", []))
        key_symbols.extend({"name": h["path"], "path": h["path"], "line": 1, "kind": "config_entry", "evidence_id": h["evidence_id"]} for h in bb.build.get("_evidence", [])[:12])

    evidence_ids = _dedupe(evidence_ids)
    key_symbols = _dedupe(key_symbols)
    vocab = bb.vocab.get(node_id, {})
    vocab_tags = [str(item.get("tag")) for item in vocab.get("mechanisms", []) if isinstance(item, dict) and item.get("tag")]
    return {
        "node_id": node_id,
        "node_identity": {
            "node_id": node_id,
            "tree_path": ["KernelProject", *node_id.split(".")],
            "title_zh": bb.nodes.get(node_id, {}).get("title_zh") or node_title_zh(node_id),
            "title_en": bb.nodes.get(node_id, {}).get("title_en") or node_title_en(node_id),
        },
        "concept": bb.concepts.get(node_id, {}),
        "vocab": vocab,
        "glossary_context": compact_glossary_for_node(bb.glossary, node_id, vocab_tags),
        "navigation_hints": vocab.get("navigation_hints") or {
            "warning": "这些只是导航提示，不是证据；claim 必须引用工具生成的 evidence_id。",
            "possible_terms": specs.get("patterns", []),
            "possible_entry_symbols": specs.get("symbols", []),
        },
        "evidence_ids": evidence_ids,
        "key_symbols": key_symbols[:18],
        "evidence": _evidence_for_llm(bb, evidence_ids),
        "blackboard": bb.current_batch_snapshot or _blackboard_summary(bb),
    }


def _ranked_atlas_hints(bb: Blackboard, node_id: str, specs: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    funcs_raw = bb.atlas.get("functions", {})
    funcs = list(funcs_raw.values()) if isinstance(funcs_raw, dict) else list(funcs_raw)
    terms = [node_id.split(".")[-1], *specs.get("symbols", []), *specs.get("patterns", []), *specs.get("mechanisms", [])]
    scored = []
    for fn in funcs:
        hay = " ".join([fn.get("name", ""), fn.get("file", ""), fn.get("signature", ""), (fn.get("body_text") or "")[:2000]]).lower()
        score = 0
        for raw in terms:
            term = str(raw).lower().replace("\\b", "").replace("\\s", "").replace("_", "")
            if not term:
                continue
            compact_hay = hay.replace("_", "")
            if term in compact_hay:
                score += 3 if term == fn.get("name", "").lower().replace("_", "") else 1
        if score:
            scored.append((score + float(fn.get("pagerank", 0.0)), fn))
    scored.sort(key=lambda x: (-x[0], x[1].get("file", ""), x[1].get("line", 0)))
    out = []
    for _, fn in scored[:limit]:
        out.append({
            "name": fn.get("name", ""),
            "path": fn.get("file", ""),
            "line": fn.get("line", 1),
            "semantic_fn_id": _semantic_fn_id(fn),
        })
    return out


def _add_lsp_context(bb: Blackboard, symbols: list[dict[str, Any]]) -> list[str]:
    evs = []
    try:
        from core.evidence import EvidenceCandidate
        from tools.lsp_ops import lsp_get_call_graph, lsp_get_definition, lsp_get_references
    except Exception:
        return evs
    for meta in symbols:
        if meta.get("kind") not in {"function", "function_definition", "source_span"}:
            continue
        path = meta.get("path", "")
        symbol = meta.get("name", "")
        if not path or not symbol:
            continue
        for tool_name, fn, kind in (
            ("lsp_get_definition", lsp_get_definition, "lsp_definition"),
            ("lsp_get_references", lsp_get_references, "lsp_reference"),
            ("lsp_get_call_graph", lambda **kw: lsp_get_call_graph(direction="outgoing", max_depth=2, **kw), "lsp_call_graph"),
        ):
            try:
                text = _invoke_tool(fn, repo_path=bb.repo_path, file_path=path, symbol=symbol)
            except Exception as exc:
                text = f"{tool_name} failed: {type(exc).__name__}: {exc}"
            evs.append(bb.evidence.add(EvidenceCandidate(
                tool=tool_name,
                kind=kind,
                path=path,
                line_start=int(meta.get("line") or 1),
                symbol=symbol,
                label=f"{tool_name}:{symbol}",
                strength="strong" if "Error:" not in str(text) and "failed:" not in str(text) else "weak",
                content=str(text)[:4000],
                metadata={"root_symbol": symbol, "file_path": path, "src": symbol, "dst": "", "mode": "deep_read_lsp"},
            )))
    return evs


def _invoke_tool(tool_obj: Any, **kwargs) -> Any:
    if hasattr(tool_obj, "invoke"):
        return tool_obj.invoke(kwargs)
    return tool_obj(**kwargs)


def _evidence_for_llm(bb: Blackboard, evidence_ids: list[str]) -> list[dict[str, Any]]:
    out = []
    for eid in evidence_ids:
        rec = bb.evidence.by_id(eid)
        if not rec:
            continue
        out.append({
            "evidence_id": eid,
            "verified": rec.verified,
            "strength": rec.strength,
            "tool": rec.tool,
            "kind": rec.kind,
            "path": rec.path,
            "line_start": rec.line_start,
            "line_end": rec.line_end,
            "symbol": rec.symbol or rec.label,
            "excerpt": rec.excerpt[:2200],
            "verifier_notes": rec.verifier_notes,
        })
    return out


def _run_evidence_requests(bb: Blackboard, node_id: str, requests: Any, pack: dict[str, Any], phase: str) -> list[str]:
    if not isinstance(requests, list):
        return []
    valid_requests = [req for req in requests[:4] if isinstance(req, dict)]
    if not valid_requests:
        return []
    added: list[str] = []
    max_workers = max(1, int(os.environ.get("AGENT_D_EVIDENCE_CONCURRENCY", "8")))
    with ThreadPoolExecutor(max_workers=min(max_workers, len(valid_requests))) as pool:
        futures = [pool.submit(_execute_evidence_request, bb, node_id, req, phase) for req in valid_requests]
        for fut in as_completed(futures):
            result = fut.result()
            request_added = result["added"]
            for ev, meta in request_added:
                _append_pack_evidence(bb, pack, ev, meta, added)
            glossary_rows = result.get("glossary") or []
            if glossary_rows:
                pack["glossary_context"] = _dedupe([*pack.get("glossary_context", []), *glossary_rows])[-24:]
                added.extend(f"glossary:{row.get('tag', '')}" for row in glossary_rows if row.get("tag"))
            if bb.recorder:
                bb.recorder.tool_call(
                    node_id=node_id,
                    phase=phase,
                    tool=result["tool"],
                    args=result["args"],
                    started_at=result["started"],
                    status=result["status"],
                    added_evidence_ids=[ev for ev, _ in request_added],
                    error=result["error"],
                )
    if added:
        pack["evidence_ids"] = _dedupe(pack["evidence_ids"])
        pack["key_symbols"] = _dedupe(pack["key_symbols"])
        pack["evidence"] = _evidence_for_llm(bb, pack["evidence_ids"])
        _journal(bb, "verifier", {"node_id": node_id, "status": f"evidence_request:{phase}", "errors": [], "added_evidence_ids": added})
    return added


def _execute_evidence_request(bb: Blackboard, node_id: str, req: dict[str, Any], phase: str) -> dict[str, Any]:
    started = time.time()
    error = ""
    status = "ok"
    tool = str(req.get("tool") or req.get("kind") or "grep").strip()
    query = str(req.get("query") or req.get("symbol") or "").strip()
    symbol = str(req.get("symbol") or query).strip()
    path = str(req.get("path") or "").strip().replace("\\", "/")
    line = int(req.get("line") or 1)
    added: list[tuple[str, dict[str, Any]]] = []
    glossary_rows: list[dict[str, Any]] = []
    try:
        if tool == "glossary_lookup":
            result = glossary_lookup(bb.glossary, query or symbol, node_id)
            if result.get("status") == "ok":
                glossary_rows.append(result)
            else:
                status = "not_found"
                error = f"glossary entry not found: {query or symbol}"
        elif tool in {"atlas_search", "atlas_symbol", "atlas_neighbors", "atlas_fingerprint"}:
            added.extend(_run_atlas_tool(bb, tool, query=query, symbol=symbol, limit=int(req.get("limit") or 12)))
        elif tool == "read_symbol" and symbol:
            added.extend(_find_symbol(bb, symbol, max_hits=4))
        elif tool == "read_path" and path:
            ev = bb.evidence.add_source(kind=_kind_for_path(path), path=path, line=line, symbol=symbol, label=symbol or path, strength="strong", metadata={"phase": phase, "node_id": node_id})
            added.append((ev, {"name": symbol or Path(path).name, "path": path, "line": line, "kind": _kind_for_path(path), "evidence_id": ev}))
        elif tool in {"lsp_definition", "lsp_references", "call_graph"} and path and symbol:
            lsp_ids = _add_specific_lsp_context(bb, path, symbol, line, tool)
            added.extend((ev, {"name": symbol, "path": path, "line": line, "kind": "function", "evidence_id": ev}) for ev in lsp_ids)
        elif tool == "git_history":
            from core.evidence import EvidenceCandidate
            from tools.git_ops import analyze_git_history, git_history_summary

            # Churn-aggregated summary (Top-3 modules per commit, 8000-char cap)
            # instead of a bare `git log --oneline`. A path_filter drill-down is
            # available when the agent passes query=<subsystem path>.
            summary = git_history_summary(bb.repo_path, max_commits=200)
            detail = analyze_git_history(bb.repo_path, max_commits=40, path_filter=query) if query else ""
            content = summary if not detail else f"{summary}\n\n=== drill-down: {query} ===\n{detail}"
            mod_hist = _module_history(bb.repo_path)
            ev = bb.evidence.add(EvidenceCandidate(
                tool="git_ops",
                kind="git_history",
                label=f"git history summary (churn by module){' / '+query if query else ''}",
                strength="strong",
                content=content,
                metadata={"module_history": mod_hist, "path_filter": query},
            ))
            added.append((ev, {"name": "git_history", "path": ".git", "line": 1, "kind": "git_history", "evidence_id": ev}))
        elif tool in {"trace_file_evolution", "symbol_first_commit", "commit_diff"}:
            from core.evidence import EvidenceCandidate
            from tools.git_ops import commit_diff_summary, find_symbol_first_commit, trace_file_evolution

            if tool == "trace_file_evolution":
                content = trace_file_evolution(bb.repo_path, path or query)
                label = f"file evolution: {path or query}"
            elif tool == "symbol_first_commit":
                content = find_symbol_first_commit(bb.repo_path, [query or symbol])
                label = f"symbol first commit: {query or symbol}"
            else:
                content = commit_diff_summary(bb.repo_path, query or symbol)
                label = f"commit diff: {query or symbol}"
            ev = bb.evidence.add(EvidenceCandidate(
                tool="git_ops", kind="git_history", label=label, strength="strong", content=content,
                metadata={"git_subtool": tool},
            ))
            added.append((ev, {"name": tool, "path": ".git", "line": 1, "kind": "git_history", "evidence_id": ev}))
        elif tool == "negative_search":
            if not query:
                query = node_id
            pattern = re.escape(query)
            matches = search_repo(bb.repo_path, pattern, max_hits=8)
            if matches:
                status = "found"
                error = f"negative_search found {len(matches)} match(es); absence is not proven"
                added.extend(_find_pattern(bb, pattern, max_hits=4))
            else:
                ev = bb.evidence.add_negative(query=query, searched_paths=["repo"], label=f"{node_id} negative search: {query}")
                added.append((ev, {"name": query, "path": "", "line": 1, "kind": "negative_search", "evidence_id": ev}))
        elif query:
            pattern = re.escape(query)
            added.extend(_find_pattern(bb, pattern, max_hits=4))
        else:
            status = "skipped"
            error = "missing query/symbol/path"
    except Exception as exc:
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
    return {
        "tool": tool,
        "args": {"query": query, "symbol": symbol, "path": path, "line": line, "reason_zh": req.get("reason_zh") or req.get("reason")},
        "started": started,
        "status": status,
        "error": error,
        "added": added,
        "glossary": glossary_rows,
    }


def _run_atlas_tool(bb: Blackboard, tool: str, *, query: str, symbol: str, limit: int) -> list[tuple[str, dict[str, Any]]]:
    from core.evidence import EvidenceCandidate

    rows: list[dict[str, Any]]
    if tool == "atlas_search":
        rows = _atlas_search(bb, query or symbol, limit=limit)
    elif tool == "atlas_symbol":
        rows = _atlas_symbol(bb, symbol or query, limit=limit)
    elif tool == "atlas_neighbors":
        rows = _atlas_neighbors(bb, symbol or query, limit=limit)
    else:
        rows = _atlas_fingerprint(bb, symbol or query, limit=limit)
    label = f"{tool}:{query or symbol}"
    ev = bb.evidence.add(EvidenceCandidate(
        tool="code_atlas",
        kind=tool,
        label=label,
        strength="weak",
        content=json.dumps(rows, ensure_ascii=False, indent=2)[:4000],
        query=query or symbol,
        metadata={"navigation_only": True, "tool": tool, "result_count": len(rows)},
    ))
    meta = {"name": query or symbol or tool, "path": "", "line": 1, "kind": tool, "evidence_id": ev}
    return [(ev, meta)]


def _atlas_search(bb: Blackboard, query: str, limit: int = 12) -> list[dict[str, Any]]:
    terms = [t.lower() for t in re.split(r"[^A-Za-z0-9_]+", query or "") if t]
    rows = []
    funcs_raw = bb.atlas.get("functions", {})
    funcs = list(funcs_raw.values()) if isinstance(funcs_raw, dict) else list(funcs_raw or [])
    for fn in funcs:
        hay = " ".join(str(fn.get(k, "")) for k in ("name", "file", "signature")).lower()
        body = str(fn.get("body_text") or "")[:1200].lower()
        score = sum(3 if t in hay else 1 if t in body else 0 for t in terms)
        if score:
            rows.append((score + float(fn.get("pagerank", 0.0)), {
                "kind": "function",
                "symbol": fn.get("name", ""),
                "path": fn.get("file", ""),
                "line": fn.get("line", 1),
                "signature": fn.get("signature", ""),
                "semantic_fn_id": _semantic_fn_id(fn),
            }))
    rows.sort(key=lambda x: (-x[0], str(x[1].get("path", "")), int(x[1].get("line") or 1)))
    return [row for _, row in rows[:max(1, min(limit, 40))]]


def _atlas_symbol(bb: Blackboard, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
    rows = []
    q = (symbol or "").lower()
    funcs_raw = bb.atlas.get("functions", {})
    funcs = list(funcs_raw.values()) if isinstance(funcs_raw, dict) else list(funcs_raw or [])
    for fn in funcs:
        name = str(fn.get("name", ""))
        if q and q not in name.lower():
            continue
        rows.append({
            "kind": "function",
            "symbol": name,
            "path": fn.get("file", ""),
            "line": fn.get("line", 1),
            "signature": fn.get("signature", ""),
            "semantic_fn_id": _semantic_fn_id(fn),
            "note": "CodeAtlas summary only; use read_symbol/read_path/LSP for strong evidence before claiming.",
        })
        if len(rows) >= limit:
            break
    for key, kind in (("types", "type"), ("macros", "macro")):
        raw = bb.atlas.get(key, {})
        items = list(raw.values()) if isinstance(raw, dict) else list(raw or [])
        for item in items:
            name = str(item.get("name", ""))
            if q and q not in name.lower():
                continue
            rows.append({
                "kind": kind,
                "symbol": name,
                "path": item.get("file", item.get("path", "")),
                "line": item.get("line", 1),
                "note": "CodeAtlas summary only; use read_symbol/read_path/LSP for strong evidence before claiming.",
            })
            if len(rows) >= limit:
                return rows
    return rows


def _atlas_neighbors(bb: Blackboard, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
    funcs_raw = bb.atlas.get("functions", {})
    funcs = list(funcs_raw.values()) if isinstance(funcs_raw, dict) else list(funcs_raw or [])
    name_to_ids = {str(fn.get("name", "")).lower(): str(fn.get("fn_id") or _semantic_fn_id(fn)) for fn in funcs}
    target = name_to_ids.get((symbol or "").lower(), "")
    rows = []
    for edge in bb.atlas.get("edges", [])[:8000]:
        if target and str(edge.get("src_fn_id", "")) != target and str(edge.get("dst_fn_id", "")) != target:
            continue
        if not target and symbol.lower() not in str(edge).lower():
            continue
        rows.append({
            "src_fn_id": edge.get("src_fn_id", ""),
            "dst_fn_id": edge.get("dst_fn_id", ""),
            "callee_name": edge.get("callee_name", ""),
            "note": "Rough AST edge only; verify with LSP call_graph/read evidence.",
        })
        if len(rows) >= limit:
            break
    return rows


def _atlas_fingerprint(bb: Blackboard, symbol: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = []
    funcs_raw = bb.atlas.get("functions", {})
    funcs = list(funcs_raw.values()) if isinstance(funcs_raw, dict) else list(funcs_raw or [])
    for fn in funcs:
        if symbol and symbol.lower() not in str(fn.get("name", "")).lower():
            continue
        rows.append(_fn_structure_fingerprint(fn))
        if len(rows) >= limit:
            break
    return rows


def _append_pack_evidence(bb: Blackboard, pack: dict[str, Any], ev: str, meta: dict[str, Any], added: list[str]) -> None:
    if ev not in pack["evidence_ids"] and bb.evidence.by_id(ev):
        pack["evidence_ids"].append(ev)
        pack["key_symbols"].append(meta)
        added.append(ev)


def _kind_for_path(path: str) -> str:
    p = path.lower()
    name = Path(path).name.lower()
    if p.endswith((".ld", ".lds")):
        return "linker_symbol"
    if p.endswith((".s", ".S".lower())):
        return "assembly_label"
    if name in {"makefile", "cargo.toml", "rust-toolchain.toml"} or p.endswith((".mk", ".toml")):
        return "config_entry"
    return "source_span"


def _add_specific_lsp_context(bb: Blackboard, path: str, symbol: str, line: int, tool: str) -> list[str]:
    try:
        from core.evidence import EvidenceCandidate
        from tools.lsp_ops import lsp_get_call_graph, lsp_get_definition, lsp_get_references
    except Exception:
        return []
    if tool == "lsp_definition":
        calls = [("lsp_get_definition", lsp_get_definition, "lsp_definition")]
    elif tool == "lsp_references":
        calls = [("lsp_get_references", lsp_get_references, "lsp_reference")]
    else:
        calls = [("lsp_get_call_graph", lambda **kw: lsp_get_call_graph(direction="outgoing", max_depth=2, **kw), "lsp_call_graph")]
    evs = []
    for tool_name, fn, kind in calls:
        try:
            with _lsp_semaphore():
                text = _invoke_tool(fn, repo_path=bb.repo_path, file_path=path, symbol=symbol)
        except Exception as exc:
            text = f"{tool_name} failed: {type(exc).__name__}: {exc}"
        evs.append(bb.evidence.add(EvidenceCandidate(
            tool=tool_name,
            kind=kind,
            path=path,
            line_start=line,
            symbol=symbol,
            label=f"{tool_name}:{symbol}",
            strength="strong" if "failed:" not in str(text) and "Error:" not in str(text) else "weak",
            content=str(text)[:4000],
            metadata={"root_symbol": symbol, "file_path": path, "src": symbol, "dst": "", "mode": "react_tool"},
        )))
    return evs


def _vocab_items(bb: Blackboard, node_id: str) -> list[dict[str, Any]]:
    items = (bb.vocab.get(node_id) or {}).get("mechanisms", [])
    out = []
    for item in items:
        if isinstance(item, dict) and item.get("tag"):
            out.append(item)
        elif isinstance(item, str):
            out.append({"tag": item, "compare_role": "primary", "category": "mechanism"})
    return out


def _vocab_tags(bb: Blackboard, node_id: str, *, include_weak: bool = True) -> set[str]:
    tags = set()
    for item in _vocab_items(bb, node_id):
        if include_weak or item.get("compare_role") != "weak_hint":
            tags.add(str(item.get("tag", "")).strip())
    return {t for t in tags if t}


def _tag_meta(bb: Blackboard, node_id: str, tag: str) -> dict[str, Any]:
    raw = tag.replace("extension:", "")
    for item in _vocab_items(bb, node_id):
        if item.get("tag") == raw or item.get("tag") == tag:
            return item
    if tag.startswith("data:"):
        return {"tag": tag, "compare_role": "display", "category": "data_structure"}
    if tag.startswith("policy:"):
        return {"tag": tag, "compare_role": "display", "category": "policy"}
    if tag.startswith("interface:"):
        return {"tag": tag, "compare_role": "display", "category": "interface"}
    if tag.startswith("extension:"):
        return {"tag": tag, "compare_role": "primary", "category": "mechanism"}
    if tag in {"metadata_profile", "not_found", "display_only_history"}:
        return {"tag": tag, "compare_role": "display", "category": "metadata"}
    return {"tag": tag, "compare_role": "primary", "category": "mechanism"}


def _verify_node_draft(bb: Blackboard, node_id: str, draft: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    status = draft.get("status")
    if status not in {"implemented", "partial", "not_found", "unknown"}:
        errors.append("status must be implemented|partial|not_found|unknown")
    evidence_pool = set(bb.evidence.records)
    claims = draft.get("claims")
    if not isinstance(claims, list):
        errors.append("claims must be a list")
        claims = []
    if status in {"implemented", "partial"} and not claims:
        errors.append("implemented/partial node must contain at least one claim")
    if status == "not_found" and not claims:
        errors.append("not_found node must contain an absence claim with negative_search evidence")
    allowed = _vocab_tags(bb, node_id)
    for idx, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claim[{idx}] must be an object")
            continue
        tag = str(claim.get("canonical_tag", "")).strip()
        if not tag:
            errors.append(f"claim[{idx}] missing canonical_tag")
        if _is_placeholder_tag(tag):
            errors.append(f"claim[{idx}] tag {tag!r} is a placeholder/example, not a comparable claim tag")
        if tag and tag not in allowed and not tag.startswith(("extension:", "data:", "policy:", "interface:", "metadata_profile", "not_found", "display_only_history")):
            errors.append(f"claim[{idx}] tag {tag!r} is outside vocab; use extension:<tag> with extension_requests")
        ev_ids = claim.get("evidence_ids") or []
        if not ev_ids:
            errors.append(f"claim[{idx}] missing evidence_ids")
            continue
        missing = [eid for eid in ev_ids if eid not in evidence_pool]
        if missing:
            errors.append(f"claim[{idx}] references unknown evidence_id(s): {missing}")
            continue
        records = [bb.evidence.by_id(eid) for eid in ev_ids]
        meta = _tag_meta(bb, node_id, tag)
        if meta.get("compare_role") == "weak_hint" and status in {"implemented", "partial"}:
            errors.append(f"claim[{idx}] uses weak_hint tag {tag!r}; weak_hint is navigation only")
        if any(r and r.kind.startswith("atlas_") for r in records) and not any(r and r.verified and r.strength == "strong" for r in records):
            errors.append(f"claim[{idx}] cannot be supported only by CodeAtlas/navigation evidence")
        if status in {"implemented", "partial"} and meta.get("compare_role") in {"primary", "display"} and not any(r and r.verified and r.strength == "strong" for r in records):
            errors.append(f"claim[{idx}] needs at least one verified strong evidence")
        if status == "not_found" and not any(r and r.kind == "negative_search" and r.verified for r in records):
            errors.append(f"claim[{idx}] not_found needs verified negative_search evidence")
    return {"node_id": node_id, "status": "ok" if not errors else "error", "errors": errors, "claim_count": len(claims)}


def _is_placeholder_tag(tag: str) -> bool:
    raw = tag.lower().replace("extension:", "").replace("data:", "").replace("policy:", "").replace("interface:", "")
    return any(marker in raw for marker in ("mechanism_or_feature_tag", "example", "placeholder", "specific_evidence_backed_tag", "choose_allowed_vocab"))


def _normalize_extension_tags(bb: Blackboard, node_id: str, draft: dict[str, Any]) -> None:
    allowed = _vocab_tags(bb, node_id)
    special = {"metadata_profile", "not_found", "display_only_history"}
    extension_requests = draft.setdefault("extension_requests", [])
    for claim in draft.get("claims", []) or []:
        if not isinstance(claim, dict):
            continue
        tag = str(claim.get("canonical_tag", "")).strip()
        tag = _normalize_claim_tag_prefix(tag, allowed)
        claim["canonical_tag"] = tag
        if not tag or tag in allowed or tag in special or tag.startswith(("extension:", "data:", "policy:", "interface:")):
            continue
        ctype = str(claim.get("claim_type", "")).strip()
        if ctype in {"data_structure", "policy", "interface"}:
            prefix = {"data_structure": "data", "policy": "policy", "interface": "interface"}[ctype]
            claim["canonical_tag"] = f"{prefix}:{tag}"
        else:
            claim["canonical_tag"] = f"extension:{tag}"
            extension_requests.append({"tag": tag, "reason": f"LLM identified {tag} with verified evidence but it is not in the fixed vocab for {node_id}."})
    mechanisms = []
    for tag in draft.get("mechanisms", []) or []:
        s = str(tag).strip()
        s = _normalize_claim_tag_prefix(s, allowed)
        if not s:
            continue
        if s in allowed or s.startswith("extension:"):
            mechanisms.append(s)
        else:
            mechanisms.append(f"extension:{s}")
            extension_requests.append({"tag": s, "reason": f"LLM mechanism {s} is outside fixed vocab for {node_id}."})
    if mechanisms:
        draft["mechanisms"] = _dedupe(mechanisms)


def _normalize_claim_tag_prefix(tag: str, allowed: set[str]) -> str:
    tag = tag.strip()
    for prefix in ("mechanism:", "feature:"):
        if tag.startswith(prefix):
            raw = tag.split(":", 1)[1]
            return raw if raw in allowed else f"extension:{raw}"
    if tag.startswith("extension:mechanism:"):
        raw = tag.split("extension:mechanism:", 1)[1]
        return raw if raw in allowed else f"extension:{raw}"
    if tag.startswith("extension:feature:"):
        raw = tag.split("extension:feature:", 1)[1]
        return raw if raw in allowed else f"extension:{raw}"
    return tag


def _normalize_absence_evidence(bb: Blackboard, node_id: str, draft: dict[str, Any], pack: dict[str, Any]) -> None:
    if draft.get("status") != "not_found":
        return
    neg_ids = []
    for eid in pack.get("evidence_ids", []):
        rec = bb.evidence.by_id(eid)
        if rec and rec.kind == "negative_search" and rec.verified:
            neg_ids.append(eid)
    if not neg_ids:
        return
    claims = draft.setdefault("claims", [])
    if not claims:
        claims.append({
            "canonical_tag": "not_found",
            "claim_type": "absence",
            "confidence": draft.get("confidence", "medium"),
            "statement_zh": f"{node_id} 未找到实现证据。",
            "statement_en": f"{node_id} implementation evidence was not found.",
            "evidence_ids": neg_ids[:2],
        })
        return
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        records = [bb.evidence.by_id(eid) for eid in claim.get("evidence_ids", [])]
        if not any(r and r.kind == "negative_search" and r.verified for r in records):
            claim["evidence_ids"] = _dedupe(list(claim.get("evidence_ids", [])) + neg_ids[:2])


def _apply_node_draft(bb: Blackboard, node_id: str, draft: dict[str, Any], pack: dict[str, Any]) -> None:
    node = bb.nodes[node_id]
    claims = draft.get("claims") or []
    evidence_ids = _dedupe([eid for claim in claims for eid in claim.get("evidence_ids", [])])
    mechanisms = _dedupe([str(x) for x in draft.get("mechanisms", []) if x])
    claim_tags = _dedupe([str(claim.get("canonical_tag", "")).strip() for claim in claims if isinstance(claim, dict) and str(claim.get("canonical_tag", "")).strip()])
    for req in draft.get("extension_requests", []) or []:
        if isinstance(req, dict):
            bb.extension_requests.append({"node_id": node_id, **req})
    node.update({
        "status": draft.get("status", "unknown"),
        "confidence": draft.get("confidence", "medium"),
        "summary_zh": draft.get("summary_zh", ""),
        "summary_en": draft.get("summary_en", ""),
        "responsibilities": _string_list(draft.get("responsibilities", [])),
        "mechanisms": mechanisms,
        "policies": _string_list(draft.get("policies", [])),
        "data_structures": _string_list(draft.get("data_structures", [])),
        "interfaces": _string_list(draft.get("interfaces", [])),
        "negative_features": _string_list(draft.get("negative_features", [])),
        "design_choices": _string_list(draft.get("design_choices", [])),
        "key_symbols": _symbols_used_by_claims(pack.get("key_symbols", []), evidence_ids),
        "evidence_ids": evidence_ids,
        "compare_tags": [f"{node_id}:{m}" for m in claim_tags if _tag_meta(bb, node_id, m).get("compare_role") == "primary"] if node_id != "EvolutionHistory" else [],
        "not_for_compare": node_id == "EvolutionHistory",
    })
    for claim in claims:
        cid = bb.claim(
            node_id,
            draft.get("status", "unknown"),
            str(claim.get("canonical_tag", "")),
            str(claim.get("statement_zh", "")),
            str(claim.get("statement_en", "")),
            list(claim.get("evidence_ids", [])),
            str(claim.get("claim_type", "mechanism")),
            str(claim.get("confidence", draft.get("confidence", "medium"))),
            str(claim.get("maturity", "simplified")),
        )
        node["claim_ids"].append(cid)
    _apply_draft_dependencies(bb, node_id, draft)
    _apply_draft_flows(bb, node_id, draft)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            parts = []
            for key in ("name", "type", "description", "description_zh", "statement_zh", "reason_zh", "choice"):
                if item.get(key):
                    parts.append(str(item[key]))
            out.append(" / ".join(parts) if parts else json.dumps(item, ensure_ascii=False, sort_keys=True))
        else:
            out.append(str(item))
    return out


def _symbols_used_by_claims(symbols: list[dict[str, Any]], evidence_ids: list[str]) -> list[dict[str, Any]]:
    used = set(evidence_ids)
    selected = [s for s in symbols if s.get("evidence_id") in used]
    return (selected or symbols)[:12]


def _apply_draft_dependencies(bb: Blackboard, node_id: str, draft: dict[str, Any]) -> None:
    for item in draft.get("dependencies", []) or []:
        if not isinstance(item, dict):
            continue
        dst = str(item.get("dst", "")).strip()
        if dst not in bb.nodes:
            _journal(bb, "verifier", {"node_id": node_id, "status": "warning", "errors": [f"dependency dst not found: {dst}"]})
            continue
        evs = [eid for eid in item.get("evidence_ids", []) if eid in bb.evidence.records]
        if not evs:
            continue
        rel = str(item.get("relation", "depends_on")).strip() or "depends_on"
        dep = Dependency(
            stable_id("dep", {"src": node_id, "dst": dst, "rel": rel, "ev": evs}),
            node_id,
            dst,
            rel,
            str(item.get("reason_zh", f"{node_id} depends on {dst}")),
            evs,
        )
        bb.dependencies[dep.dependency_id] = dep


def _apply_draft_flows(bb: Blackboard, node_id: str, draft: dict[str, Any]) -> None:
    for item in draft.get("flows", []) or []:
        if not isinstance(item, dict):
            continue
        steps = []
        evs = []
        for step in item.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            eid = step.get("evidence_id")
            if eid not in bb.evidence.records:
                continue
            rec = bb.evidence.by_id(eid)
            evs.append(eid)
            steps.append({
                "role": str(step.get("role", "")),
                "symbol": str(step.get("symbol") or (rec.symbol if rec else "")),
                "path": rec.path if rec else "",
                "line": rec.line_start if rec else None,
                "evidence_id": eid,
            })
        if len(steps) < 2:
            continue
        title_zh = str(item.get("title_zh", f"{node_id} 关键链路"))
        title_en = str(item.get("title_en", f"{node_id} flow"))
        roles = item.get("role_sequence") or [s["role"] for s in steps]
        flow = Flow(stable_id("flow", {"node": node_id, "title": title_zh, "ev": evs}), title_zh, title_en, list(roles), steps, _dedupe(evs))
        bb.flows[flow.flow_id] = flow


def _call_agent_d_llm(bb: Blackboard, template_id: str, payload: dict[str, Any], max_tokens: int = 4096) -> tuple[Any, dict[str, Any]]:
    from core.llm.backend import call_chat_model, parse_llm_json

    model = os.environ.get("MODEL_NAME") or "gpt-4o-mini"
    payload = _fit_payload_to_budget(payload)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    started = time.time()
    sem = _llm_semaphore()
    with sem:
        response = call_chat_model(
            rendered,
            {
                "model": model,
                "temperature": float(os.environ.get("AGENT_D_LLM_TEMPERATURE", "0")),
                "max_tokens": int(os.environ.get("AGENT_D_MAX_OUTPUT_TOKENS", str(max_tokens))),
                "timeout": float(os.environ.get("AGENT_D_LLM_TIMEOUT_SECONDS", "180")),
            },
        )
    meta = {
        "template_id": template_id,
        "model": model,
        "elapsed_seconds": round(time.time() - started, 3),
        "usage": response.get("usage", {}),
        "reasoning_effort": os.environ.get("AGENT_D_REASONING_EFFORT", "high"),
        "thinking": os.environ.get("AGENT_D_THINKING", "enabled"),
        "llm_concurrency": int(os.environ.get("AGENT_D_LLM_CONCURRENCY", "2")),
    }
    _journal(bb, "llm_usage", meta)
    if bb.recorder:
        bb.recorder.llm_call(meta)
    return parse_llm_json(response.get("content", "")), meta


def _llm_semaphore() -> Semaphore:
    global _LLM_SEMAPHORE
    with _LLM_SEMAPHORE_LOCK:
        if _LLM_SEMAPHORE is None:
            _LLM_SEMAPHORE = Semaphore(max(1, int(os.environ.get("AGENT_D_LLM_CONCURRENCY", "2"))))
        return _LLM_SEMAPHORE


def _lsp_semaphore() -> Semaphore:
    global _LSP_SEMAPHORE
    with _LSP_SEMAPHORE_LOCK:
        if _LSP_SEMAPHORE is None:
            _LSP_SEMAPHORE = Semaphore(max(1, int(os.environ.get("AGENT_D_LSP_CONCURRENCY", "4"))))
        return _LSP_SEMAPHORE


def _fit_payload_to_budget(payload: dict[str, Any]) -> dict[str, Any]:
    budget_tokens = max(8000, int(os.environ.get("AGENT_D_CONTEXT_BUDGET_TOKENS", "120000")))
    budget_chars = budget_tokens * 3
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(rendered) <= budget_chars:
        return payload
    compact = json.loads(json.dumps(payload, ensure_ascii=False))
    for ev in compact.get("verified_evidence", []) or []:
        if isinstance(ev, dict) and isinstance(ev.get("excerpt"), str):
            ev["excerpt"] = ev["excerpt"][:700] + "\n...<truncated by AGENT_D_CONTEXT_BUDGET_TOKENS>..."
    bb = compact.get("blackboard")
    if isinstance(bb, dict):
        bb["filled_nodes"] = bb.get("filled_nodes", [])[-10:]
        bb["confirmed_claims"] = bb.get("confirmed_claims", [])[-18:]
        bb["known_dependencies"] = bb.get("known_dependencies", [])[-8:]
        bb["known_flows"] = bb.get("known_flows", [])[-6:]
    return compact


def _blackboard_summary(bb: Blackboard) -> dict[str, Any]:
    filled = []
    for node_id in ANALYSIS_ORDER:
        n = bb.nodes.get(node_id)
        if not n or n.get("status") == "unknown":
            continue
        filled.append({
            "node_id": node_id,
            "status": n.get("status"),
            "mechanisms": n.get("mechanisms", [])[:8],
            "summary_zh": n.get("summary_zh", "")[:220],
            "claim_ids": n.get("claim_ids", [])[:8],
            "evidence_ids": n.get("evidence_ids", [])[:8],
        })
    return {
        "repo_name": bb.repo_name,
        "filled_nodes": filled[-18:],
        "confirmed_claims": [
            {
                "claim_id": c.claim_id,
                "node_id": c.node_id,
                "tag": c.canonical_tag,
                "evidence_ids": c.evidence_ids[:4],
            }
            for c in list(bb.claims.values())[-32:]
        ],
        "known_dependencies": [asdict(d) for d in list(bb.dependencies.values())[-16:]],
        "known_flows": [asdict(f) for f in list(bb.flows.values())[-10:]],
    }


def _module_history(repo_path: str) -> dict[str, list[dict[str, str]]]:
    """Churn-ranked per-module commit index via the ported git_ops tool.

    Replaces the old keyword-bucketing (which had no churn data and a fixed
    13-module table) with repo-agnostic top-level-directory aggregation.
    """
    try:
        from tools.git_ops import module_history

        return module_history(repo_path, max_commits=200)
    except Exception:
        return {}


def _seed_build_evidence(bb: Blackboard) -> None:
    evs = []
    for hit in bb.build.get("config_hits", [])[:30]:
        path = hit["path"]
        first_marker = (hit.get("markers") or ["config"])[0]
        line = _line_for_pattern(bb.repo_path, path, re.escape(first_marker)) or 1
        ev = bb.evidence.add_source(kind="config_entry", path=path, line=line, symbol=first_marker, label=f"{path}:{first_marker}", strength="strong", metadata={"markers": hit.get("markers", [])})
        evs.append({"path": path, "evidence_id": ev})
    bb.build["_evidence"] = evs


def _seed_symbol_evidence(bb: Blackboard) -> None:
    funcs_raw = bb.atlas.get("functions", {})
    types_raw = bb.atlas.get("types", {})
    funcs = list(funcs_raw.values()) if isinstance(funcs_raw, dict) else list(funcs_raw)
    types = list(types_raw.values()) if isinstance(types_raw, dict) else list(types_raw)
    bb.atlas["_fn_by_name"] = {}
    for fn in funcs:
        name = fn.get("name", "")
        bb.atlas["_fn_by_name"].setdefault(name.lower(), []).append(fn)
    bb.atlas["_type_by_name"] = {}
    for ty in types:
        name = ty.get("name", "")
        bb.atlas["_type_by_name"].setdefault(name.lower(), []).append(ty)


def _find_symbol(bb: Blackboard, symbol: str, max_hits: int = 3) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for fn in bb.atlas.get("_fn_by_name", {}).get(symbol.lower(), [])[:max_hits]:
        ev = bb.evidence.add_source(kind="function_definition", path=fn["file"], line=int(fn["line"]), symbol=fn["name"], label=f"{fn['name']}()", metadata={"semantic_fn_id": _semantic_fn_id(fn), "signature": fn.get("signature", "")})
        out.append((ev, {"name": fn["name"], "path": fn["file"], "line": fn["line"], "kind": "function", "evidence_id": ev, "semantic_fn_id": _semantic_fn_id(fn)}))
    for ty in bb.atlas.get("_type_by_name", {}).get(symbol.lower(), [])[:max_hits]:
        ev = bb.evidence.add_source(kind="type_definition", path=ty["file"], line=int(ty["line"]), symbol=ty["name"], label=f"{ty.get('kind', 'type')} {ty['name']}", metadata={"type_kind": ty.get("kind")})
        out.append((ev, {"name": ty["name"], "path": ty["file"], "line": ty["line"], "kind": "type", "evidence_id": ev}))
    if out:
        return out
    return _find_pattern(bb, rf"\b{re.escape(symbol)}\b", max_hits=max_hits)


def _find_pattern(bb: Blackboard, pattern: str, max_hits: int = 3) -> list[tuple[str, dict[str, Any]]]:
    hits = search_repo(bb.repo_path, pattern, max_hits=max_hits)
    out = []
    for hit in hits:
        kind = _kind_for_hit(hit["path"], hit["text"])
        sym = _symbol_from_line(hit["text"]) or pattern
        ev = bb.evidence.add_source(kind=kind, path=hit["path"], line=hit["line"], symbol=sym, label=sym, metadata={"pattern": pattern, "line_text": hit["text"]})
        out.append((ev, {"name": sym, "path": hit["path"], "line": hit["line"], "kind": kind, "evidence_id": ev}))
    return out


def _line_for_pattern(repo_path: str, rel_path: str, pattern: str) -> int | None:
    text = read_text_head(repo_path, rel_path, 50000)
    rx = re.compile(pattern, re.I)
    for i, line in enumerate(text.splitlines(), 1):
        if rx.search(line):
            return i
    return None


def _kind_for_hit(path: str, line: str) -> str:
    name = Path(path).name.lower()
    if path.lower().endswith((".ld", ".lds")):
        return "linker_symbol"
    if path.lower().endswith((".s", ".S".lower())):
        return "assembly_label"
    if name in {"makefile", "cargo.toml", "rust-toolchain.toml"} or path.endswith((".mk", ".toml")):
        return "config_entry"
    if line.lstrip().startswith("#define"):
        return "macro_definition"
    if re.search(r"\b(struct|enum|typedef)\b", line):
        return "type_definition"
    return "source_span"


def _symbol_from_line(line: str) -> str:
    m = re.match(r"\s*(?:void|int|uint64|uint|char|struct\s+\w+\s*\*?|\w+\s*\*?)\s+([A-Za-z_]\w*)\s*\(", line)
    if m:
        return m.group(1)
    m = re.match(r"\s*#define\s+([A-Za-z_]\w*)", line)
    if m:
        return m.group(1)
    m = re.match(r"\s*(?:struct|enum|typedef).*?\b([A-Za-z_]\w*)\s*[;{]", line)
    if m:
        return m.group(1)
    m = re.match(r"\s*([A-Za-z_.$][\w.$]*):", line)
    if m:
        return m.group(1)
    return line.strip()[:60]


def _semantic_fn_id(fn: dict[str, Any]) -> str:
    tokens = fn.get("tokens_normalized") or fn.get("normalized_tokens") or fn.get("signature") or fn.get("name", "")
    if isinstance(tokens, list):
        text = " ".join(tokens[:200])
    else:
        text = str(tokens)[:1000]
    return stable_id("sfn", {"tokens": text, "ast": fn.get("ast_shape_hash", "")}, 16)


def _trace_flows_deep(bb: Blackboard) -> None:
    payload = {
        "role": "LLMFlowTracer",
        "instruction": (
            "基于已经验证的 KernelProject 黑板和 evidence，提出关键内核链路。"
            "不要输出内部思维链，只输出 JSON。每个 step 必须引用已有 evidence_id。"
        ),
        "required_flows": ["boot", "trap/syscall", "scheduler/context switch", "fork/exec/wait", "read/write", "block I/O"],
        "blackboard": _blackboard_summary(bb),
        "claims": {cid: asdict(c) for cid, c in bb.claims.items()},
        "output_schema": {
            "flows": [{
                "title_zh": "链路中文名",
                "title_en": "English title",
                "role_sequence": ["role"],
                "steps": [{"role": "role", "symbol": "symbol", "evidence_id": "ev_xxx"}],
            }]
        },
    }
    parsed, meta = _call_agent_d_llm(bb, "agent_d_flow_tracer", payload, max_tokens=3000)
    _journal(bb, "llm_draft", {"node_id": "__flows__", "draft": parsed, "llm_meta": meta})
    if not isinstance(parsed, dict) or not isinstance(parsed.get("flows"), list):
        raise RuntimeError("LLMFlowTracer did not return {'flows': [...]}")
    draft = {"flows": parsed["flows"]}
    before = len(bb.flows)
    _apply_draft_flows(bb, "__global__", draft)
    if len(bb.flows) == before:
        raise RuntimeError("LLMFlowTracer produced no verifiable flows")


def _build_dependencies_deep(bb: Blackboard) -> None:
    payload = {
        "role": "LLMDependencyBuilder",
        "instruction": (
            "基于已确认 claim、节点和 evidence，提出模块依赖边。"
            "依赖必须有源码/LSP/call graph evidence_id 支撑。不要输出内部思维链，只输出 JSON。"
        ),
        "valid_nodes": list(bb.nodes.keys()),
        "blackboard": _blackboard_summary(bb),
        "claims": {cid: asdict(c) for cid, c in bb.claims.items()},
        "output_schema": {
            "dependencies": [{
                "src": "KernelProject node_id",
                "dst": "KernelProject node_id",
                "relation": "semantic_relation",
                "reason_zh": "中文原因",
                "evidence_ids": ["ev_xxx"],
            }]
        },
    }
    parsed, meta = _call_agent_d_llm(bb, "agent_d_dependency_builder", payload, max_tokens=3000)
    _journal(bb, "llm_draft", {"node_id": "__dependencies__", "draft": parsed, "llm_meta": meta})
    if not isinstance(parsed, dict) or not isinstance(parsed.get("dependencies"), list):
        raise RuntimeError("LLMDependencyBuilder did not return {'dependencies': [...]}")
    before = len(bb.dependencies)
    for item in parsed["dependencies"]:
        if not isinstance(item, dict):
            continue
        src = item.get("src")
        if src not in bb.nodes:
            continue
        _apply_draft_dependencies(bb, src, {"dependencies": [item]})
    if len(bb.dependencies) == before:
        raise RuntimeError("LLMDependencyBuilder produced no verifiable dependencies")


def _global_consistency_pass(bb: Blackboard) -> None:
    payload = {
        "role": "LLMGlobalConsistencyReviewer",
        "instruction": (
            "审查完整 KernelProject 黑板，找出概念混淆、claim 缺证据、模块错放。"
            "不要输出内部思维链，只输出 JSON。若无需修改，返回 empty corrections。"
        ),
        "focus_confusions": [
            "PageTable vs AddressSpace",
            "TrapException vs SyscallEntry",
            "ContextSwitch vs Scheduler",
            "PhysicalAllocator vs KernelHeap",
            "VFS vs ConcreteFS",
        ],
        "blackboard": _blackboard_summary(bb),
        "nodes": {node_id: {k: n.get(k) for k in ("status", "summary_zh", "mechanisms", "claim_ids", "evidence_ids")} for node_id, n in bb.nodes.items()},
        "claims": {cid: asdict(c) for cid, c in bb.claims.items()},
        "output_schema": {
            "review_summary_zh": "全局审查摘要",
            "corrections": [{"node_id": "node", "field": "summary_zh|summary_en", "value": "new value", "reason_zh": "原因"}],
            "warnings": ["无法自动修改但需要注意的问题"],
        },
    }
    parsed, meta = _call_agent_d_llm(bb, "agent_d_global_consistency", payload, max_tokens=2500)
    _journal(bb, "llm_draft", {"node_id": "__global_consistency__", "draft": parsed, "llm_meta": meta})
    if not isinstance(parsed, dict):
        raise RuntimeError("LLMGlobalConsistencyReviewer did not return a JSON object")
    for corr in parsed.get("corrections", []) or []:
        if not isinstance(corr, dict):
            continue
        node_id = corr.get("node_id")
        field_name = corr.get("field")
        if node_id in bb.nodes and field_name in {"summary_zh", "summary_en"}:
            bb.nodes[node_id][field_name] = str(corr.get("value", ""))
    _journal(bb, "verifier", {"node_id": "__global_consistency__", "status": "ok", "errors": [], "review": parsed})





def _attach_refs(bb: Blackboard) -> None:
    for flow in bb.flows.values():
        for step in flow.steps:
            for node_id in _nodes_for_symbol(step.get("symbol", "")):
                if node_id in bb.nodes:
                    bb.nodes[node_id]["flow_ids"].append(flow.flow_id)
    for dep in bb.dependencies.values():
        for node_id in (dep.src, dep.dst):
            bb.nodes[node_id]["dependency_ids"].append(dep.dependency_id)
    for node in bb.nodes.values():
        for key in ("flow_ids", "dependency_ids", "claim_ids", "evidence_ids", "compare_tags"):
            node[key] = _dedupe(node.get(key, []))


def _nodes_for_symbol(symbol: str) -> list[str]:
    s = symbol.lower()
    out = []
    for node, specs in NODE_SPECS.items():
        if s in [x.lower() for x in specs.get("symbols", [])]:
            out.append(node)
    return out


def _finalize_tree(bb: Blackboard, started: float) -> dict[str, Any]:
    children = []
    for root, leaves in ROOT_NODES.items():
        if not leaves:
            children.append(bb.nodes[root])
        else:
            children.append({"node_id": root, "title_zh": node_title_zh(root), "title_en": node_title_en(root), "children": [bb.nodes[f"{root}.{leaf}"] for leaf in leaves]})
    return {
        "schema_version": "agent_d.kernel_project.v2",
        "repo_name": bb.repo_name,
        "repo_path": bb.repo_path,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_goal": "从源码和工具证据生成可展示、可查重的 KernelProject 抽象设计树。",
        "analysis_order": ANALYSIS_ORDER,
        "analysis_batches": ANALYSIS_BATCHES_V2,
        "root": {"node_id": "KernelProject", "title_zh": "内核项目设计树", "title_en": "KernelProject", "children": children},
        "claims": {k: asdict(v) for k, v in bb.claims.items()},
        "flows": {k: asdict(v) for k, v in bb.flows.items()},
        "dependencies": {k: asdict(v) for k, v in bb.dependencies.items()},
        "extension_requests": bb.extension_requests,
        "lineage": {"elapsed_seconds": round(time.time() - started, 2), "evidence_count": len(bb.evidence.records), "claim_count": len(bb.claims)},
    }


def _build_compare_index(bb: Blackboard, tree: dict[str, Any]) -> dict[str, Any]:
    nodes = [n for n in bb.nodes.values() if not n.get("not_for_compare")]
    compare_claims = [c for c in bb.claims.values() if c.node_id != "EvolutionHistory"]
    tag_quality: dict[str, dict[str, Any]] = {}
    primary_tags: set[str] = set()
    display_tags: set[str] = set()
    weak_hint_tags: set[str] = set()
    absence_tags: set[str] = set()
    for c in compare_claims:
        key = f"{c.node_id}:{c.canonical_tag}"
        meta = _tag_meta(bb, c.node_id, c.canonical_tag)
        records = [bb.evidence.by_id(eid) for eid in c.evidence_ids]
        strengths = [r.strength for r in records if r]
        roles = meta.get("compare_role", "primary")
        tag_quality[key] = {
            "claim_id": c.claim_id,
            "node_id": c.node_id,
            "tag": c.canonical_tag,
            "compare_role": roles,
            "category": meta.get("category", c.claim_type),
            "evidence_strengths": strengths,
            "has_strong_evidence": any(s == "strong" for s in strengths),
        }
        if c.claim_type == "absence" or c.status == "not_found":
            absence_tags.add(key)
        elif roles == "primary" and c.status in {"implemented", "partial"}:
            primary_tags.add(key)
        elif roles == "display":
            display_tags.add(key)
        else:
            weak_hint_tags.add(key)
    semantic_ids = []
    for n in nodes:
        for s in n.get("key_symbols", []):
            if s.get("semantic_fn_id"):
                semantic_ids.append(s["semantic_fn_id"])
    code_layer = _build_code_structure_layer(bb, compare_claims)
    design_layer = {
        "claim_tags": sorted({f"{c.node_id}:{c.canonical_tag}" for c in compare_claims}),
        "primary_claim_tags": sorted(primary_tags),
        "mechanism_tags": sorted(primary_tags),
        "display_tags": sorted(display_tags),
        "weak_hint_tags": sorted(weak_hint_tags),
        "absence_tags": sorted(absence_tags),
        "module_presence": sorted(f"{n['node_id']}:{n['status']}" for n in nodes),
        "policy_tags": sorted({f"{n['node_id']}:{p}" for n in nodes for p in n.get("policies", [])}),
        "data_structure_tags": sorted({f"{n['node_id']}:{d}" for n in nodes for d in n.get("data_structures", [])}),
        "interface_tags": sorted({f"{n['node_id']}:{i}" for n in nodes for i in n.get("interfaces", [])}),
        "tag_quality": tag_quality,
    }
    relation_layer = {
        "flow_signatures": sorted({">".join(f.role_sequence) for f in bb.flows.values()}),
        "dependency_signatures": sorted({f"{d.src}->{d.dst}:{d.relation}" for d in bb.dependencies.values()}),
    }
    lineage_layer = {
        "excluded_nodes": ["EvolutionHistory"],
        "claim_to_evidence": {c.claim_id: c.evidence_ids for c in compare_claims},
        "node_status": {n["node_id"]: n.get("status", "unknown") for n in nodes},
    }
    return {
        "schema_version": "agent_d.compare_index.v3",
        "repo_name": bb.repo_name,
        "design_layer": design_layer,
        "relation_layer": relation_layer,
        "code_structure_layer": code_layer,
        "lineage_layer": lineage_layer,
        "excluded_nodes": lineage_layer["excluded_nodes"],
        "module_presence": design_layer["module_presence"],
        "primary_claim_tags": design_layer["primary_claim_tags"],
        "mechanism_tags": design_layer["mechanism_tags"],
        "display_tags": design_layer["display_tags"],
        "weak_hint_tags": design_layer["weak_hint_tags"],
        "absence_tags": design_layer["absence_tags"],
        "policy_tags": design_layer["policy_tags"],
        "data_structure_tags": design_layer["data_structure_tags"],
        "interface_tags": design_layer["interface_tags"],
        "flow_signatures": relation_layer["flow_signatures"],
        "dependency_signatures": relation_layer["dependency_signatures"],
        "semantic_fn_ids": sorted(set(semantic_ids)),
        "claim_tags": design_layer["claim_tags"],
        "weights": {"design": 0.35, "relation": 0.25, "code_structure": 0.25, "lineage": 0.15},
    }


def _build_code_structure_layer(bb: Blackboard, compare_claims: list[Claim]) -> dict[str, Any]:
    funcs_raw = bb.atlas.get("functions", {})
    if isinstance(funcs_raw, dict):
        funcs = []
        for fn_id, fn in funcs_raw.items():
            row = dict(fn)
            row.setdefault("fn_id", fn_id)
            funcs.append(row)
    else:
        funcs = list(funcs_raw)
    by_file_symbol: dict[tuple[str, str], dict[str, Any]] = {}
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    by_fn_id: dict[str, dict[str, Any]] = {}
    for fn in funcs:
        file_key = str(fn.get("file", "")).replace("\\", "/")
        name = str(fn.get("name", ""))
        fn_id = str(fn.get("fn_id") or _semantic_fn_id(fn))
        by_file_symbol[(file_key, name)] = fn
        by_symbol.setdefault(name, []).append(fn)
        by_fn_id[fn_id] = fn
    selected: dict[str, dict[str, Any]] = {}
    claim_bindings: dict[str, list[dict[str, Any]]] = {}
    for claim in compare_claims:
        bindings = []
        for eid in claim.evidence_ids:
            rec = bb.evidence.by_id(eid)
            if not rec:
                continue
            symbol = rec.symbol or rec.label
            path = rec.path.replace("\\", "/")
            matches = []
            if (path, symbol) in by_file_symbol:
                matches = [by_file_symbol[(path, symbol)]]
            elif symbol in by_symbol:
                matches = by_symbol[symbol][:3]
            for fn in matches:
                fp = _fn_structure_fingerprint(fn)
                selected[fp["semantic_fn_id"]] = fp
                bindings.append({
                    "claim_id": claim.claim_id,
                    "evidence_id": eid,
                    "semantic_fn_id": fp["semantic_fn_id"],
                    "ast_shape_hash": fp.get("ast_shape_hash"),
                    "normalized_token_fingerprint": fp.get("normalized_token_fingerprint"),
                })
        if bindings:
            claim_bindings[claim.claim_id] = bindings
    if not selected:
        ranked = sorted(funcs, key=lambda fn: float(fn.get("pagerank", 0.0)), reverse=True)[:80]
        for fn in ranked:
            fp = _fn_structure_fingerprint(fn)
            selected[fp["semantic_fn_id"]] = fp
    edge_fps = []
    for edge in bb.atlas.get("edges", [])[:5000]:
        src = by_fn_id.get(str(edge.get("src_fn_id", "")))
        dst = by_fn_id.get(str(edge.get("dst_fn_id", "")))
        if not src:
            continue
        src_id = _semantic_fn_id(src)
        dst_id = _semantic_fn_id(dst) if dst else str(edge.get("callee_name", ""))
        if src_id in selected or dst_id in selected:
            edge_fps.append(stable_id("cedge", {"src": src_id, "dst": dst_id, "callee": edge.get("callee_name")}, 16))
    type_macro_usage = []
    for fp in selected.values():
        if fp.get("literal_fingerprint"):
            type_macro_usage.append(fp["literal_fingerprint"])
    return {
        "schema_version": "agent_d.code_structure.v1",
        "ast_shape_hashes": sorted({fp["ast_shape_hash"] for fp in selected.values() if fp.get("ast_shape_hash")}),
        "normalized_token_fingerprints": sorted({fp["normalized_token_fingerprint"] for fp in selected.values() if fp.get("normalized_token_fingerprint")}),
        "call_edge_fingerprints": sorted(set(edge_fps)),
        "type_macro_usage_fingerprints": sorted(set(type_macro_usage)),
        "semantic_fn_ids": sorted(selected),
        "claim_code_bindings": claim_bindings,
    }


def _fn_structure_fingerprint(fn: dict[str, Any]) -> dict[str, Any]:
    tokens = fn.get("tokens_normalized") or fn.get("normalized_tokens") or []
    token_text = " ".join(tokens[:400]) if isinstance(tokens, list) else str(tokens)[:2000]
    literals = fn.get("literal_set") or []
    return {
        "semantic_fn_id": _semantic_fn_id(fn),
        "path": str(fn.get("file", "")).replace("\\", "/"),
        "symbol": fn.get("name", ""),
        "ast_shape_hash": fn.get("ast_shape_hash"),
        "normalized_token_fingerprint": stable_id("ntok", {"tokens": token_text}, 16),
        "literal_fingerprint": stable_id("lit", {"literals": sorted(map(str, literals))}, 16) if literals else "",
    }


def _resolve_submission_meta(bb: Blackboard) -> dict[str, Any]:
    """Look up contest/team identity (or teaching-prototype label) for the banner."""
    try:
        from core.submission_meta import match_submission

        xlsx = Path(__file__).parent / "collected-data.xlsx"
        return match_submission(bb.repo_name, bb.repo_path, xlsx)
    except Exception as exc:
        return {"repo_name": bb.repo_name, "is_base_os": False, "error": f"{type(exc).__name__}: {exc}"}


def _build_judge_view(bb: Blackboard, tree: dict[str, Any], compare_index: dict[str, Any]) -> dict[str, Any]:
    claim_rows = {}
    used_glossary = {}
    for claim_id, claim in bb.claims.items():
        glossary = glossary_lookup(bb.glossary, claim.canonical_tag, claim.node_id)
        claim_rows[claim_id] = asdict(claim) | {"glossary": glossary}
        if glossary.get("status") == "ok":
            used_glossary[glossary["full_tag"]] = glossary
    return {
        "repo_name": bb.repo_name,
        "schema_version": "agent_d.judge_view.v2",
        "submission_meta": _resolve_submission_meta(bb),
        "tree": tree["root"],
        "claims": claim_rows,
        "claim_glossary": used_glossary,
        "flows": {k: asdict(v) for k, v in bb.flows.items()},
        "dependencies": {k: asdict(v) for k, v in bb.dependencies.items()},
        "evidence": {
            rec.evidence_id: rec.compact() | {"excerpt": rec.excerpt, "verifier_notes": rec.verifier_notes}
            for rec in bb.evidence.iter_full()
        },
        "compare_summary": {
            "implemented_nodes": sum(1 for n in bb.nodes.values() if n.get("status") == "implemented" and not n.get("not_for_compare")),
            "partial_nodes": sum(1 for n in bb.nodes.values() if n.get("status") == "partial"),
            "mechanism_count": len(compare_index["mechanism_tags"]),
            "flow_count": len(compare_index["flow_signatures"]),
            "dependency_count": len(compare_index["dependency_signatures"]),
        },
        "agent_runtime": _llm_trace(),
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_debug_artifacts(out: Path, bb: Blackboard, failure: str | None = None) -> None:
    journal = bb.journal.summary() if bb.journal else {"counts": {}, "usage": {}}
    _write_json(out / "agent_trace.json", {
        "analysis_order": ANALYSIS_ORDER,
        "llm": _llm_trace(),
        "journal": journal,
        "failure": failure,
    })
    _write_json(out / "llm_usage.json", {
        "schema_version": "agent_d.llm_usage.v2",
        "summary": journal.get("usage", {}),
        "calls_jsonl": "llm_usage.jsonl",
        "thinking": os.environ.get("AGENT_D_THINKING", "enabled"),
        "reasoning_effort": os.environ.get("AGENT_D_REASONING_EFFORT", "high"),
        "node_concurrency": os.environ.get("AGENT_D_NODE_CONCURRENCY", "1"),
        "llm_concurrency": os.environ.get("AGENT_D_LLM_CONCURRENCY", "2"),
        "context_budget_tokens": os.environ.get("AGENT_D_CONTEXT_BUDGET_TOKENS", "120000"),
        "failure": failure,
    })


def _journal(bb: Blackboard, channel: str, row: dict[str, Any]) -> None:
    if bb.journal:
        bb.journal.append(channel, row)


def _dedupe(xs: list[Any]) -> list[Any]:
    out = []
    seen = set()
    for x in xs:
        if not x:
            continue
        key = json.dumps(x, ensure_ascii=False, sort_keys=True) if isinstance(x, (dict, list)) else str(x)
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def _llm_trace() -> dict[str, Any]:
    return {
        "role": "DeepReadOrchestrator",
        "enabled": _llm_enabled(),
        "reasoning_effort": os.environ.get("AGENT_D_REASONING_EFFORT", "high"),
        "thinking": os.environ.get("AGENT_D_THINKING", "enabled"),
        "node_concurrency": os.environ.get("AGENT_D_NODE_CONCURRENCY", "1"),
        "llm_concurrency": os.environ.get("AGENT_D_LLM_CONCURRENCY", "2"),
        "note": "LLM reads verified source/LSP evidence packs and emits structured drafts. Tools mint evidence_id and verify claim bindings. Internal chain-of-thought is not emitted.",
    }


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _llm_enabled() -> bool:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    valid_key = bool(key and len(key) > 8 and key.lower() not in {"true", "false", "none", "null"} and "your" not in key.lower() and "placeholder" not in key.lower())
    return valid_key


NODE_SPECS: dict[str, dict[str, Any]] = {}


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    repo_arg = args.repo or args.clone or args.repo_path or os.environ.get("AGENT_D_TARGET_REPO") or os.environ.get("REPO_URL", "")
    if not repo_arg:
        print("错误：请通过 --repo、本地路径参数、AGENT_D_TARGET_REPO 或 REPO_URL 指定仓库", file=sys.stderr)
        sys.exit(2)

    repo_path, repo_name = _resolve_repo(repo_arg, args.repo_name)
    output_dir = Path(args.output_root) / repo_name / "_agent_d"
    interactive = sys.stderr.isatty() and not os.environ.get("CI")
    use_tui = interactive and not args.no_tui and not args.quiet and os.environ.get("AGENT_D_TUI", "true").lower() in {"1", "true", "yes", "on"}
    line_progress = not use_tui and not args.quiet

    ui_server = None
    if args.ui:
        ui_server = _serve_background(output_dir, args.port)
        if not args.quiet:
            print(f"  progress_ui: http://localhost:{ui_server.server_address[1]}/run_dashboard.html", file=sys.stderr)

    if line_progress:
        print("== Agent D: LangGraph KernelProject Reader ==", file=sys.stderr)
        print(f"  repo_path: {repo_path}", file=sys.stderr)
        print(f"  repo_name: {repo_name}", file=sys.stderr)
        print(f"  output_dir: {output_dir}", file=sys.stderr)
        print("  flow: LangGraph batches -> LangChain ReAct nodes -> verifier -> flow/dependency/consistency -> finalizer", file=sys.stderr)
    started = time.time()
    try:
        summary = run_agent_d(
            repo_path=str(repo_path),
            output_dir=str(output_dir),
            repo_name=repo_name,
            progress_cb=(lambda stage, info: print(f"  [{stage}] {info}", file=sys.stderr)) if line_progress else None,
            fresh=args.fresh,
            run_id=args.run_id,
            tui=use_tui,
        )
    except KeyboardInterrupt:
        print(json.dumps({"status": "paused", "message": "checkpoint 已保存；再次运行会自动恢复。"}, ensure_ascii=False))
        return
    print(json.dumps({
        "status": "complete",
        "run_id": summary.get("run_id"),
        "resumed": summary.get("resumed"),
        "reused": summary.get("reused"),
        "elapsed_seconds": round(time.time() - started, 1),
        "kernel_design_tree": summary.get("kernel_design_tree"),
        "compare_index": summary.get("compare_index"),
        "index_html": summary.get("index_html"),
    }, ensure_ascii=False))

    if args.serve and not args.ui:
        _serve(output_dir, args.port)


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Agent D: read one kernel repository and generate KernelProject design tree")
    parser.add_argument("repo_path", nargs="?", default="")
    parser.add_argument("--repo", default=None, help="Local repo path or Git URL")
    parser.add_argument("--clone", default=None, help="Legacy alias of --repo for Git URL")
    parser.add_argument("--repo-name", default=None)
    parser.add_argument("--output-root", default=os.environ.get("AGENT_OUTPUT_ROOT", "output"))
    parser.add_argument("--force", action="store_true", help="Accepted for compatibility")
    parser.add_argument("--serve", action="store_true", help="Serve output directory after generation")
    parser.add_argument("--ui", action="store_true", help="Open live Agent D dashboard while running")
    parser.add_argument("--fresh", action="store_true", help="Start a new run even when a compatible checkpoint exists")
    parser.add_argument("--run-id", default="", help="Resume or inspect a specific run id")
    parser.add_argument("--no-tui", action="store_true", help="Disable the default Rich live TUI")
    parser.add_argument("--quiet", action="store_true", help="Only print the final machine-readable result")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _resolve_repo(repo_arg: str, repo_name: str | None) -> tuple[Path, str]:
    if _looks_like_git_url(repo_arg):
        url = repo_arg.rstrip("/")
        inferred = Path(url).name.removesuffix(".git")
        name = repo_name or inferred
        local = Path("repos") / name
        local.parent.mkdir(parents=True, exist_ok=True)
        if local.is_dir():
            print(f"  已存在 {local}，跳过 clone")
        else:
            print(f"  git clone {url} -> {local}")
            subprocess.check_call(["git", "clone", url, str(local)])
        return local.resolve(), name
    p = Path(repo_arg)
    if not p.is_dir():
        print(f"错误：仓库路径不存在: {repo_arg}", file=sys.stderr)
        sys.exit(2)
    return p.resolve(), repo_name or p.resolve().name


def _looks_like_git_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "git@")) or s.endswith(".git")


def _serve(output_dir: Path, port: int) -> None:
    import http.server
    import socketserver
    import webbrowser

    os.chdir(output_dir)
    url = f"http://localhost:{port}"
    print(f"  启动 HTTP 服务 {url}  (Ctrl+C 停止)")
    webbrowser.open(url)
    with socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  已停止")


def _serve_background(output_dir: Path, port: int):
    import functools
    import http.server
    import socketserver
    import webbrowser

    output_dir.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(output_dir.resolve()))
    try:
        httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    except OSError:
        httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        webbrowser.open(f"http://localhost:{httpd.server_address[1]}/run_dashboard.html")
    except Exception:
        pass
    return httpd


if __name__ == "__main__":
    main()

