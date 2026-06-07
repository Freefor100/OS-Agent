from __future__ import annotations

import json
import hashlib
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

WEIGHTS = {"design": 0.35, "relation": 0.25, "code_structure": 0.25, "lineage": 0.15}
COMMON_TAG_HINTS = {
    "riscv", "sv39", "spinlock", "freelist", "round_robin", "inode", "fd_table",
    "syscall_dispatch", "uart", "virtio", "qemu", "elf", "fork", "exec", "wait",
}


def run_agent_c_compare(target_dir: str, corpus_dirs: list[str], output_dir: str | None = None, progress_cb=None) -> dict[str, Any]:
    cb = progress_cb or (lambda stage, info: None)
    target_path = Path(target_dir)
    target = _load_index(target_path)
    target_tree = _load_tree(target_path)
    target_evidence = _load_evidence_summary(target_path)
    target_glossary = _load_glossary(target_path)
    refs = []
    for d in corpus_dirs:
        p = Path(d)
        if (p / "compare_index.json").is_file() and (p / "kernel_design_tree.json").is_file():
            refs.append((_load_index(p), _load_tree(p), _load_evidence_summary(p), _load_glossary(p), p))
    if not refs:
        raise FileNotFoundError("no valid _agent_d corpus dirs with compare_index.json")

    reports = []
    lineages = []
    for ref, ref_tree, ref_evidence, ref_glossary, ref_path in refs:
        cb("compare", f"{target['repo_name']} vs {ref['repo_name']}")
        scores = _score(target, ref, target_tree, ref_tree)
        lineage = _lineage(target_tree, ref_tree, target, ref, target_evidence, ref_evidence, target_glossary, ref_glossary)
        layer_scores = {
            "design_claim": scores["design_claim_score"],
            "architecture_relation": scores["architecture_relation_score"],
            "code_structure": scores["code_structure_score"],
            "base_aware_lineage": scores["lineage_prior_score"],
        }
        reports.append({
            "ref": ref["repo_name"],
            "ref_dir": str(ref_path),
            "layer_scores": layer_scores,
            **scores,
        })
        lineages.append({
            "ancestor": ref["repo_name"],
            "ancestor_dir": str(ref_path),
            "strength": scores["derivation_strength"],
            **lineage,
        })

    reports.sort(key=lambda x: x["derivation_strength"], reverse=True)
    lineages.sort(key=lambda x: x["strength"], reverse=True)
    out = Path(output_dir) if output_dir else _default_agent_c_dir(target_path)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "agent_c.compare_report.v3",
        "target": target["repo_name"],
        "compare_layers": [
            {"id": "design_claim", "title_zh": "设计 Claim", "title_en": "Design Claim", "weight": WEIGHTS["design"]},
            {"id": "architecture_relation", "title_zh": "架构关系", "title_en": "Architecture Relation", "weight": WEIGHTS["relation"]},
            {"id": "code_structure", "title_zh": "代码结构", "title_en": "Code Structure", "weight": WEIGHTS["code_structure"]},
            {"id": "base_aware_lineage", "title_zh": "Base 感知谱系", "title_en": "Base-aware Lineage", "weight": WEIGHTS["lineage"]},
        ],
        "ranking": reports,
        "best_match": reports[0] if reports else None,
        "notes_zh": "Agent C 只消费 Agent D 的 _agent_d 产物，不回读源码。",
        "notes_en": "Agent C consumes only Agent D _agent_d products and never reopens source repositories.",
    }
    lineage_doc = {
        "schema_version": "agent_c.lineage.v3",
        "target": target["repo_name"],
        "lineage": lineages,
        "best_lineage": lineages[0] if lineages else None,
    }
    view = _build_compare_view(report, lineage_doc, target, target_tree, target_evidence, target_glossary)
    _write(out / "compare_report.json", report)
    _write(out / "lineage.json", lineage_doc)
    _write(out / "judge_compare_view.json", view)
    html = _publish_compare_html(out, view)
    return {
        "compare_report": str(out / "compare_report.json"),
        "lineage": str(out / "lineage.json"),
        "judge_compare_view": str(out / "judge_compare_view.json"),
        "index_html": html,
        "ranking": reports,
        "lineage_top3": lineages[:3],
        "layer_top3": reports[:3],
    }


def _default_agent_c_dir(target_path: Path) -> Path:
    if target_path.name == "_agent_d":
        return target_path.parent / "_agent_c"
    return target_path / "_agent_c"


def _load_index(path: Path) -> dict[str, Any]:
    data = json.loads((path / "compare_index.json").read_text(encoding="utf-8"))
    data["_agent_d_dir"] = str(path.resolve())
    return data


def _load_tree(path: Path) -> dict[str, Any]:
    return json.loads((path / "kernel_design_tree.json").read_text(encoding="utf-8"))


def _load_evidence_summary(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    p = path / "evidence_store.jsonl"
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        eid = str(item.get("evidence_id") or item.get("id") or "")
        if not eid:
            continue
        rows[eid] = {
            "evidence_id": eid,
            "path": item.get("path") or "",
            "line_start": item.get("line_start") or item.get("line") or "",
            "symbol": item.get("symbol") or item.get("label") or "",
            "kind": item.get("kind") or "",
            "strength": item.get("strength") or "",
            "verified": bool(item.get("verified")),
        }
    return rows


def _load_glossary(path: Path) -> dict[str, dict[str, Any]]:
    p = path / "claim_glossary.json"
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def _score(a: dict[str, Any], b: dict[str, Any], a_tree: dict[str, Any] | None = None, b_tree: dict[str, Any] | None = None) -> dict[str, float]:
    design = _design_score(a, b, a_tree, b_tree)
    relation = _relation_score(a, b)
    code = _code_structure_score(a, b, a_tree, b_tree)
    lineage_hint = _lineage_hint_score(a, b)
    overall = round(
        design["design_claim_score"] * WEIGHTS["design"]
        + relation["architecture_relation_score"] * WEIGHTS["relation"]
        + code["code_structure_score"] * WEIGHTS["code_structure"]
        + lineage_hint * WEIGHTS["lineage"],
        4,
    )
    base_similarity = round(
        lineage_hint * 0.35
        + code["symbol_name_base_coverage"] * 0.20
        + code["fuzzy_normalized_token_base_coverage"] * 0.20
        + design["design_claim_score"] * 0.15
        + relation["architecture_relation_score"] * 0.10,
        4,
    )
    return {
        **design,
        **relation,
        **code,
        "lineage_prior_score": lineage_hint,
        "overall_similarity": overall,
        "base_similarity": base_similarity,
        "derivation_strength": base_similarity,
    }


def _design_score(a: dict[str, Any], b: dict[str, Any], a_tree: dict[str, Any] | None, b_tree: dict[str, Any] | None) -> dict[str, float]:
    la = a.get("design_layer") or a
    lb = b.get("design_layer") or b
    primary_a = la.get("primary_claim_tags") or a.get("primary_claim_tags") or la.get("mechanism_tags") or []
    primary_b = lb.get("primary_claim_tags") or b.get("primary_claim_tags") or lb.get("mechanism_tags") or []
    display_a = la.get("display_tags") or a.get("display_tags") or []
    display_b = lb.get("display_tags") or b.get("display_tags") or []
    absence_a = la.get("absence_tags") or []
    absence_b = lb.get("absence_tags") or []
    module = _j(la.get("module_presence", a.get("module_presence", [])), lb.get("module_presence", b.get("module_presence", [])))
    module_coverage = _module_base_coverage(
        la.get("module_presence", a.get("module_presence", [])),
        lb.get("module_presence", b.get("module_presence", [])),
    )
    primary = _weighted_j(primary_a, primary_b)
    primary_coverage = _semantic_tag_base_coverage(primary_a, primary_b)
    statement_coverage = _claim_statement_base_coverage(a_tree, b_tree)
    if not a_tree or not b_tree:
        statement_coverage = primary_coverage
    display = _weighted_j(display_a, display_b)
    absence = _j(absence_a, absence_b)
    return {
        "primary_claim_jaccard": primary,
        "primary_claim_base_coverage": primary_coverage,
        "claim_statement_base_coverage": statement_coverage,
        "display_tag_jaccard": display,
        "absence_tag_jaccard": absence,
        "module_jaccard": module,
        "module_base_coverage": module_coverage,
        "weak_hint_ignored": True,
        "design_claim_score": round(statement_coverage * 0.40 + primary_coverage * 0.35 + module_coverage * 0.20 + absence * 0.05, 4),
    }


def _relation_score(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    la = a.get("relation_layer") or a
    lb = b.get("relation_layer") or b
    flow = _j(la.get("flow_signatures", a.get("flow_signatures", [])), lb.get("flow_signatures", b.get("flow_signatures", [])))
    dep = _j(la.get("dependency_signatures", a.get("dependency_signatures", [])), lb.get("dependency_signatures", b.get("dependency_signatures", [])))
    flow_coverage = _text_signature_base_coverage(
        la.get("flow_signatures", a.get("flow_signatures", [])),
        lb.get("flow_signatures", b.get("flow_signatures", [])),
    )
    dep_coverage = _dependency_base_coverage(
        la.get("dependency_signatures", a.get("dependency_signatures", [])),
        lb.get("dependency_signatures", b.get("dependency_signatures", [])),
    )
    return {
        "flow_jaccard": flow,
        "dependency_jaccard": dep,
        "flow_base_coverage": flow_coverage,
        "dependency_base_coverage": dep_coverage,
        "architecture_relation_score": round(flow_coverage * 0.40 + dep_coverage * 0.60, 4),
    }


def _code_structure_score(a: dict[str, Any], b: dict[str, Any], a_tree: dict[str, Any] | None, b_tree: dict[str, Any] | None) -> dict[str, float]:
    la = a.get("code_structure_layer") or {}
    lb = b.get("code_structure_layer") or {}
    ast = _j_present(la.get("ast_shape_hashes", []), lb.get("ast_shape_hashes", []))
    token = _j_present(la.get("normalized_token_fingerprints", []), lb.get("normalized_token_fingerprints", []))
    edge = _j_present(la.get("call_edge_fingerprints", []), lb.get("call_edge_fingerprints", []))
    usage = _j_present(la.get("type_macro_usage_fingerprints", []), lb.get("type_macro_usage_fingerprints", []))
    sem = _j(la.get("semantic_fn_ids", a.get("semantic_fn_ids", [])), lb.get("semantic_fn_ids", b.get("semantic_fn_ids", [])))
    ast_coverage = _set_base_coverage(la.get("ast_shape_hashes", []), lb.get("ast_shape_hashes", []))
    token_coverage = _set_base_coverage(la.get("normalized_token_fingerprints", []), lb.get("normalized_token_fingerprints", []))
    edge_coverage = _set_base_coverage(la.get("call_edge_fingerprints", []), lb.get("call_edge_fingerprints", []))
    claim_binding_coverage = _code_bound_claim_coverage(a, b)
    code_bound_statement_coverage = _code_bound_statement_coverage(a, b, a_tree, b_tree)
    fuzzy_token_coverage = _atlas_fuzzy_code_coverage(a, b)
    symbol_name_coverage = _atlas_symbol_name_coverage(a, b)
    if not a_tree or not b_tree:
        code_bound_statement_coverage = claim_binding_coverage
    if not a.get("_agent_d_dir") or not b.get("_agent_d_dir"):
        fuzzy_token_coverage = claim_binding_coverage
    parts = [
        (fuzzy_token_coverage, 0.35),
        (symbol_name_coverage, 0.20),
        (code_bound_statement_coverage, 0.15),
        (claim_binding_coverage, 0.05),
        (ast_coverage, 0.10),
        (token_coverage, 0.05),
        (edge_coverage, 0.03),
        (usage, 0.07),
    ]
    available = [(score, weight) for score, weight in parts if score is not None]
    code_score = round(sum(score * weight for score, weight in available) / max(0.0001, sum(weight for _, weight in available)), 4) if available else 0.0
    return {
        "ast_shape_jaccard": ast if ast is not None else 0.0,
        "normalized_token_jaccard": token if token is not None else 0.0,
        "call_edge_jaccard": edge if edge is not None else 0.0,
        "type_macro_usage_jaccard": usage if usage is not None else 0.0,
        "semantic_fn_jaccard": sem,
        "ast_shape_base_coverage": ast_coverage,
        "normalized_token_base_coverage": token_coverage,
        "call_edge_base_coverage": edge_coverage,
        "code_bound_claim_base_coverage": claim_binding_coverage,
        "code_bound_statement_base_coverage": code_bound_statement_coverage,
        "fuzzy_normalized_token_base_coverage": fuzzy_token_coverage,
        "symbol_name_base_coverage": symbol_name_coverage,
        "code_structure_score": code_score,
    }


def _lineage_hint_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    la = a.get("lineage_layer") or {}
    lb = b.get("lineage_layer") or {}
    target = la.get("node_status") or {}
    base = lb.get("node_status") or {}
    relevant = [node_id for node_id, status in base.items() if status in {"implemented", "partial"}]
    if not relevant:
        return 1.0
    covered = sum(1 for node_id in relevant if target.get(node_id) in {"implemented", "partial"})
    return round(covered / len(relevant), 4)


def _j(a: list[Any], b: list[Any]) -> float:
    sa, sb = {str(x) for x in a}, {str(x) for x in b}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return round(len(sa & sb) / len(sa | sb), 4)


_GENERIC_TAG_TOKENS = {
    "extension", "policy", "internal", "mechanism", "implementation", "implemented",
    "impl", "support", "supported", "handler", "flow", "based", "system", "kernel",
    "feature", "method", "interface", "operation", "operations", "management",
}
_TOKEN_ALIASES = {
    "allocator": "alloc", "allocation": "alloc", "allocate": "alloc",
    "scheduler": "sched", "scheduling": "sched",
    "freelist": "free_list", "free": "free", "list": "list",
    "pagetable": "page_table", "page": "page", "table": "table",
    "syscalls": "syscall", "dispatcher": "dispatch", "dispatching": "dispatch",
    "interrupts": "interrupt", "locks": "lock", "locking": "lock",
    "directories": "directory", "entries": "entry", "devices": "device",
    "physical": "physical", "memory": "memory",
}


def _module_base_coverage(target_rows: list[str], base_rows: list[str]) -> float:
    target = dict(_split_presence(row) for row in target_rows if ":" in str(row))
    base = dict(_split_presence(row) for row in base_rows if ":" in str(row))
    relevant = [node_id for node_id, status in base.items() if status in {"implemented", "partial"}]
    if not relevant:
        return 1.0
    return round(sum(1 for node_id in relevant if target.get(node_id) in {"implemented", "partial"}) / len(relevant), 4)


def _split_presence(row: str) -> tuple[str, str]:
    return str(row).rsplit(":", 1)


def _semantic_tag_base_coverage(target_tags: list[str], base_tags: list[str]) -> float:
    target = [_tag_signature(tag) for tag in target_tags]
    base = [_tag_signature(tag) for tag in base_tags]
    if not base:
        return 1.0
    if not target:
        return 0.0
    scores = []
    for base_node, base_tokens in base:
        candidates = [
            _token_similarity(target_tokens, base_tokens)
            for target_node, target_tokens in target
            if target_node == base_node
        ]
        best = max(candidates, default=0.0)
        scores.append(best if best >= 0.42 else 0.0)
    return round(sum(scores) / len(scores), 4)


def _claim_statement_base_coverage(target_tree: dict[str, Any] | None, base_tree: dict[str, Any] | None, *, target_claim_ids: set[str] | None = None, base_claim_ids: set[str] | None = None) -> float:
    if not target_tree or not base_tree:
        return 0.0
    target = _claim_semantic_rows(target_tree, target_claim_ids)
    base = _claim_semantic_rows(base_tree, base_claim_ids)
    if not base:
        return 1.0
    scores = []
    for node_id, base_tokens in base:
        candidates = [
            _token_similarity(target_tokens, base_tokens)
            for target_node, target_tokens in target
            if target_node == node_id
        ]
        best = max(candidates, default=0.0)
        scores.append(best if best >= 0.18 else 0.0)
    return round(sum(scores) / len(scores), 4)


def _claim_semantic_rows(tree: dict[str, Any], claim_ids: set[str] | None) -> list[tuple[str, set[str]]]:
    rows = []
    for claim_id, claim in (tree.get("claims") or {}).items():
        if claim_ids is not None and claim_id not in claim_ids:
            continue
        if claim.get("status") not in {"implemented", "partial"}:
            continue
        text = " ".join([
            str(claim.get("canonical_tag") or ""),
            str(claim.get("statement_en") or ""),
        ])
        rows.append((str(claim.get("node_id") or ""), _tokens(text)))
    return rows


def _tag_signature(tag: str) -> tuple[str, set[str]]:
    parts = str(tag).split(":")
    node_id = parts[0]
    raw = "_".join(parts[1:])
    return node_id, _tokens(raw)


def _tokens(text: str) -> set[str]:
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(text)).lower()
    out: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", raw):
        alias = _TOKEN_ALIASES.get(token, token)
        if alias in _GENERIC_TAG_TOKENS or len(alias) <= 1:
            continue
        out.update(part for part in alias.split("_") if part and part not in _GENERIC_TAG_TOKENS)
    return out


def _token_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return (2.0 * len(a & b)) / (len(a) + len(b))


def _dependency_base_coverage(target_rows: list[str], base_rows: list[str]) -> float:
    target = {_dependency_endpoints(row) for row in target_rows}
    base = {_dependency_endpoints(row) for row in base_rows}
    return _set_base_coverage(target, base)


def _dependency_endpoints(row: str) -> str:
    return str(row).split(":", 1)[0]


def _text_signature_base_coverage(target_rows: list[str], base_rows: list[str]) -> float:
    target = [_tokens(row) for row in target_rows]
    base = [_tokens(row) for row in base_rows]
    if not base:
        return 1.0
    if not target:
        return 0.0
    scores = []
    for base_tokens in base:
        best = max((_token_similarity(target_tokens, base_tokens) for target_tokens in target), default=0.0)
        scores.append(best if best >= 0.15 else 0.0)
    return round(sum(scores) / len(scores), 4)


def _set_base_coverage(target_values: Any, base_values: Any) -> float:
    target = {str(value) for value in target_values}
    base = {str(value) for value in base_values}
    if not base:
        return 1.0
    return round(len(target & base) / len(base), 4)


def _code_bound_claim_coverage(target: dict[str, Any], base: dict[str, Any]) -> float:
    return _semantic_tag_base_coverage(_code_bound_tags(target), _code_bound_tags(base))


def _code_bound_statement_coverage(target: dict[str, Any], base: dict[str, Any], target_tree: dict[str, Any] | None, base_tree: dict[str, Any] | None) -> float:
    target_ids = _code_bound_claim_ids(target)
    base_ids = _code_bound_claim_ids(base)
    return _claim_statement_base_coverage(
        target_tree,
        base_tree,
        target_claim_ids=target_ids,
        base_claim_ids=base_ids,
    )


def _code_bound_claim_ids(index: dict[str, Any]) -> set[str]:
    bindings = (index.get("code_structure_layer") or {}).get("claim_code_bindings") or {}
    return {str(claim_id) for claim_id in bindings}


def _code_bound_tags(index: dict[str, Any]) -> list[str]:
    design = index.get("design_layer") or {}
    quality = design.get("tag_quality") or {}
    bindings = (index.get("code_structure_layer") or {}).get("claim_code_bindings") or {}
    bound_claim_ids = set(bindings)
    return [
        str(tag)
        for tag, meta in quality.items()
        if isinstance(meta, dict) and str(meta.get("claim_id") or "") in bound_claim_ids
    ]


def _atlas_fuzzy_code_coverage(target: dict[str, Any], base: dict[str, Any]) -> float:
    target_dir = str(target.get("_agent_d_dir") or "")
    base_dir = str(base.get("_agent_d_dir") or "")
    if not target_dir or not base_dir:
        return 0.0
    target_profiles = _atlas_token_profiles(target_dir)
    base_profiles = _atlas_token_profiles(base_dir)
    if not base_profiles:
        return 1.0
    if not target_profiles:
        return 0.0
    scores = []
    for base_profile in base_profiles:
        best = max((_sketch_similarity(target_profile, base_profile) for target_profile in target_profiles), default=0.0)
        scores.append(best if best >= 0.12 else 0.0)
    return round(sum(scores) / len(scores), 4)


def _atlas_symbol_name_coverage(target: dict[str, Any], base: dict[str, Any]) -> float:
    target_dir = str(target.get("_agent_d_dir") or "")
    base_dir = str(base.get("_agent_d_dir") or "")
    if not target_dir or not base_dir:
        return _code_bound_claim_coverage(target, base)
    return _set_base_coverage(_atlas_symbol_names(target_dir), _atlas_symbol_names(base_dir))


@lru_cache(maxsize=16)
def _atlas_symbol_names(agent_d_dir: str) -> tuple[str, ...]:
    path = Path(agent_d_dir) / "code_atlas.json"
    if not path.is_file():
        return ()
    try:
        atlas = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    raw = atlas.get("functions") or {}
    functions = raw.values() if isinstance(raw, dict) else raw
    return tuple(sorted({
        str(fn.get("name") or "")
        for fn in functions
        if fn.get("name") and not str(fn.get("name")).startswith("__")
    }))


@lru_cache(maxsize=16)
def _atlas_token_profiles(agent_d_dir: str) -> tuple[frozenset[int], ...]:
    path = Path(agent_d_dir) / "code_atlas.json"
    if not path.is_file():
        return ()
    try:
        atlas = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    raw = atlas.get("functions") or {}
    functions = raw.values() if isinstance(raw, dict) else raw
    profiles = []
    for fn in functions:
        tokens = [str(token) for token in (fn.get("tokens_normalized") or fn.get("normalized_tokens") or [])]
        if len(tokens) < 12:
            continue
        hashes = {
            int.from_bytes(hashlib.blake2b(" ".join(tokens[i:i + 4]).encode("utf-8"), digest_size=8).digest(), "big")
            for i in range(len(tokens) - 3)
        }
        if hashes:
            profiles.append(frozenset(sorted(hashes)[:96]))
    return tuple(profiles)


def _sketch_similarity(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _weighted_j(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    all_tags = sa | sb
    inter = sa & sb
    denom = sum(_tag_weight(t) for t in all_tags)
    numer = sum(_tag_weight(t) for t in inter)
    return round(numer / max(0.0001, denom), 4)


def _tag_weight(tag: str) -> float:
    tail = str(tag).split(":", 1)[-1].lower()
    if any(h in tail for h in COMMON_TAG_HINTS):
        return 0.55
    return 1.0


def _j_present(a: list[str], b: list[str]) -> float | None:
    if not a and not b:
        return None
    return _j(a, b)


def _lineage(
    target_tree: dict[str, Any],
    ref_tree: dict[str, Any],
    target_idx: dict[str, Any],
    ref_idx: dict[str, Any],
    target_evidence: dict[str, dict[str, Any]],
    ref_evidence: dict[str, dict[str, Any]],
    target_glossary: dict[str, dict[str, Any]],
    ref_glossary: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    tn = _nodes(target_tree["root"])
    rn = _nodes(ref_tree["root"])
    target_claims = _claims_by_node_tag(target_tree)
    ref_claims = _claims_by_node_tag(ref_tree)
    shared_mech = set(target_idx.get("mechanism_tags") or target_idx.get("primary_claim_tags") or []) & set(ref_idx.get("mechanism_tags") or ref_idx.get("primary_claim_tags") or [])
    ref_nodes = {x.split(":")[0]: x.split(":", 1)[1] for x in ref_idx.get("module_presence", []) if ":" in x}
    rows = []
    for node_id, node in sorted(tn.items()):
        if node.get("not_for_compare") or node_id == "EvolutionHistory" or node_id not in rn:
            continue
        target_status = node.get("status")
        ref_status = ref_nodes.get(node_id)
        ttags = set(node.get("compare_tags", []))
        rtags = set(rn[node_id].get("compare_tags", []))
        shared_tags = ttags & rtags
        target_unique_tags = ttags - rtags
        if shared_tags and target_unique_tags and target_status in {"implemented", "partial"} and ref_status in {"implemented", "partial"}:
            status = "base_modified"
        elif ttags & shared_mech:
            status = "base_inherited"
        elif target_status in {"implemented", "partial"} and ref_status in {"implemented", "partial"}:
            status = "base_modified"
        elif target_status in {"implemented", "partial"} and ref_status not in {"implemented", "partial"}:
            status = "target_unique"
        else:
            status = "unknown"
        target_eids = _eids_for_tags(target_claims, node_id, shared_tags | target_unique_tags)
        ref_eids = _eids_for_tags(ref_claims, node_id, shared_tags)
        rows.append({
            "node_id": node_id,
            "title_zh": node.get("title_zh", ""),
            "title_en": node.get("title_en", ""),
            "lineage_status": status,
            "target_status": target_status,
            "base_status": ref_status,
            "shared_tags": sorted(shared_tags),
            "target_unique_tags": sorted(target_unique_tags),
            "shared_claims": [_glossary_card(tag, target_glossary, ref_glossary) for tag in sorted(shared_tags)],
            "target_unique_claims": [_glossary_card(tag, target_glossary) for tag in sorted(target_unique_tags)],
            "target_evidence": [target_evidence[eid] for eid in target_eids if eid in target_evidence],
            "base_evidence": [ref_evidence[eid] for eid in ref_eids if eid in ref_evidence],
        })
    return {
        "base_inherited": [r for r in rows if r["lineage_status"] == "base_inherited"],
        "base_modified": [r for r in rows if r["lineage_status"] == "base_modified"],
        "target_unique": [r for r in rows if r["lineage_status"] == "target_unique"],
        "unknown": [r for r in rows if r["lineage_status"] == "unknown"],
    }


def _glossary_card(tag: str, *glossaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for glossary in glossaries:
        if tag in glossary:
            item = glossary[tag]
            return {
                "tag": tag,
                "title_zh": item.get("title_zh", ""),
                "title_en": item.get("title_en", ""),
                "definition_zh": item.get("definition_zh", ""),
                "definition_en": item.get("definition_en", ""),
            }
    return {"tag": tag, "title_zh": "", "title_en": "", "definition_zh": "", "definition_en": ""}


def _claims_by_node_tag(tree: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for claim in (tree.get("claims") or {}).values():
        node = str(claim.get("node_id") or "")
        tag = str(claim.get("canonical_tag") or "")
        if not node or not tag:
            continue
        out.setdefault(node, {}).setdefault(tag, [])
        out[node][tag].extend(str(eid) for eid in claim.get("evidence_ids") or [])
    return out


def _eids_for_tags(claims: dict[str, dict[str, list[str]]], node_id: str, tags: set[str]) -> list[str]:
    out: list[str] = []
    by_tag = claims.get(node_id) or {}
    for tag in sorted(tags):
        out.extend(by_tag.get(tag, []))
    return _dedupe(out)


def _nodes(root: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    def walk(n: dict[str, Any]) -> None:
        if "status" in n:
            out[n["node_id"]] = n
        for c in n.get("children", []):
            walk(c)

    walk(root)
    return out


def _build_compare_view(report: dict[str, Any], lineage_doc: dict[str, Any], target_idx: dict[str, Any], target_tree: dict[str, Any], target_evidence: dict[str, dict[str, Any]], target_glossary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "agent_c.judge_compare_view.v1",
        "target": report["target"],
        "target_summary": {
            "repo_name": target_idx.get("repo_name"),
            "implemented_nodes": len([n for n in _nodes(target_tree["root"]).values() if n.get("status") in {"implemented", "partial"}]),
            "primary_claim_tags": len(target_idx.get("primary_claim_tags") or target_idx.get("mechanism_tags") or []),
            "flows": len((target_idx.get("relation_layer") or {}).get("flow_signatures") or []),
            "dependencies": len((target_idx.get("relation_layer") or {}).get("dependency_signatures") or []),
        },
        "compare_layers": report["compare_layers"],
        "ranking": report["ranking"],
        "best_match": report["best_match"],
        "lineage": lineage_doc["lineage"],
        "best_lineage": lineage_doc["best_lineage"],
        "target_evidence": target_evidence,
        "claim_glossary": target_glossary,
        "notes_zh": report["notes_zh"],
        "notes_en": report["notes_en"],
    }


def _publish_compare_html(out: Path, view: dict[str, Any]) -> str:
    payload = json.dumps(view, ensure_ascii=False).replace("</", "<\\/")
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent C 内核查重比较</title>
  <style>
    :root {{ --bg:#f6f7f3; --panel:#fff; --ink:#20231f; --muted:#667168; --line:#d8ded6; --accent:#176b5b; --warn:#8a6415; --bad:#a33b2f; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Inter,ui-sans-serif,system-ui,"Microsoft YaHei","Segoe UI",sans-serif; font-size:14px; }}
    header {{ background:#fff; border-bottom:1px solid var(--line); padding:18px 28px; position:sticky; top:0; z-index:3; }}
    h1 {{ margin:0; font-size:24px; letter-spacing:0; }} h2 {{ margin:0 0 10px; font-size:18px; }} h3 {{ margin:0; font-size:15px; }}
    main {{ padding:18px 28px 60px; }} .muted {{ color:var(--muted); }} .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:14px 0; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 1px 2px rgba(20,32,24,.04); }}
    .metric .value {{ font-size:26px; font-weight:780; margin-top:6px; }} .metric .label {{ color:var(--muted); font-size:12px; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ text-align:left; border-bottom:1px solid #edf0ec; padding:10px; vertical-align:top; overflow-wrap:anywhere; }} th {{ color:var(--muted); font-size:12px; font-weight:650; background:#f0f3ef; }}
    tr:last-child td {{ border-bottom:0; }} .bar {{ height:8px; background:#e3e9e2; border-radius:99px; overflow:hidden; margin-top:5px; }} .bar span {{ display:block; height:100%; background:var(--accent); }}
    .pill {{ display:inline-flex; align-items:center; border:1px solid var(--line); background:#eef2ed; border-radius:999px; padding:3px 8px; margin:3px 4px 3px 0; font-size:12px; }}
    .claim-card {{ border-left:3px solid var(--accent); padding:7px 9px; margin:6px 0; background:#f7faf7; }}
    .claim-card.unique {{ border-left-color:var(--bad); background:#fff7f5; }}
    .claim-card code {{ display:inline-block; margin-top:4px; color:var(--muted); }}
    details {{ background:#fff; border:1px solid var(--line); border-radius:8px; margin:12px 0; overflow:hidden; }} summary {{ cursor:pointer; padding:12px 14px; font-weight:720; }}
    .lineage-group {{ padding:0 14px 14px; }} .row {{ border-top:1px solid #edf0ec; padding:10px 0; }} .row:first-child {{ border-top:0; }}
    code {{ background:#eef2ed; padding:2px 5px; border-radius:4px; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12px; }}
    .ev {{ color:#285248; }} .status-base_inherited {{ color:#176b5b; }} .status-base_modified {{ color:#8a6415; }} .status-target_unique {{ color:#a33b2f; }}
    @media (max-width:1000px) {{ .grid {{ grid-template-columns:1fr 1fr; }} main,header {{ padding-left:16px; padding-right:16px; }} }}
    @media (max-width:640px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<header><h1>Agent C 内核查重比较 / Kernel Similarity Compare</h1><div class="muted">四层评分：设计 Claim、架构关系、代码结构、Base 感知谱系。只消费 Agent D 产物，不回读源码。</div></header>
<main id="app"></main>
<script type="application/json" id="data">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const LAYER_ZH = {{design_claim:'设计 Claim', architecture_relation:'架构关系', code_structure:'代码结构', base_aware_lineage:'Base 感知谱系'}};
const STATUS_ZH = {{base_inherited:'继承自 base', base_modified:'基于 base 修改', target_unique:'目标独有', unknown:'未知/证据不足'}};
function esc(s) {{ return String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
function pct(x) {{ return Math.round((Number(x)||0) * 1000) / 10; }}
function bar(x) {{ return `<div class="bar"><span style="width:${{Math.max(0, Math.min(100, pct(x)))}}%"></span></div>`; }}
function tag(t) {{ return `<span class="pill">${{esc(String(t).split(':').slice(1).join(':') || t)}}</span>`; }}
function claimCard(c, cls='') {{
  if (!c) return '';
  const fallback = String(c.tag || '').split(':').slice(1).join(':') || c.tag || '';
  const title = c.title_zh || c.title_en ? `${{c.title_zh || fallback}} / ${{c.title_en || fallback}}` : fallback;
  return `<div class="claim-card ${{cls}}"><b>${{esc(title)}}</b><div class="muted">${{esc(c.definition_zh || '')}}</div><div class="muted">${{esc(c.definition_en || '')}}</div><code>${{esc(c.tag || '')}}</code></div>`;
}}
function evidence(rows) {{
  if (!rows || !rows.length) return '<span class="muted">无 evidence 摘要</span>';
  return rows.slice(0, 5).map(e => `<span class="pill ev">${{esc(e.evidence_id)}} ${{esc(e.path)}}${{e.line_start?':'+esc(e.line_start):''}} ${{esc(e.symbol)}} ${{esc(e.kind)}} ${{esc(e.strength)}}</span>`).join('');
}}
function rankingTable() {{
  const rows = (DATA.ranking || []).map((r, i) => `<tr><td>${{i+1}}</td><td><b>${{esc(r.ref)}}</b><div class="muted">${{esc(r.ref_dir)}}</div></td><td>${{pct(r.base_similarity ?? r.derivation_strength)}}%${{bar(r.base_similarity ?? r.derivation_strength)}}</td><td>${{pct(r.overall_similarity ?? r.derivation_strength)}}%</td><td>${{pct(r.layer_scores.design_claim)}}%</td><td>${{pct(r.layer_scores.architecture_relation)}}%</td><td>${{pct(r.layer_scores.code_structure)}}%</td><td>${{pct(r.layer_scores.base_aware_lineage)}}%</td></tr>`).join('');
  return `<table><thead><tr><th style="width:48px">#</th><th>候选作品 / Candidate</th><th>Base 同源度</th><th>整体相似度</th><th>Design</th><th>Relation</th><th>Code</th><th>Lineage</th></tr></thead><tbody>${{rows || '<tr><td colspan="8">无比较对象</td></tr>'}}</tbody></table>`;
}}
function lineageDetails() {{
  return (DATA.lineage || []).map(item => {{
    const groups = ['base_inherited','base_modified','target_unique','unknown'].map(key => {{
      const rows = (item[key] || []).map(r => `<div class="row"><b>${{esc(r.title_zh || r.node_id)}}</b> <span class="muted">${{esc(r.title_en || '')}}</span> <code>${{esc(r.node_id)}}</code> <span class="status-${{key}}">${{STATUS_ZH[key]}}</span><div>${{(r.shared_claims||[]).map(c => claimCard(c)).join('')}} ${{(r.target_unique_claims||[]).map(c => claimCard(c, 'unique')).join('')}}</div><div class="muted">target evidence: ${{evidence(r.target_evidence)}}</div><div class="muted">base evidence: ${{evidence(r.base_evidence)}}</div></div>`).join('');
      return `<h3>${{STATUS_ZH[key]}}</h3>${{rows || '<div class="muted row">无</div>'}}`;
    }).join('');
    return `<details open><summary>${{esc(item.ancestor)}} / strength ${{pct(item.strength)}}%</summary><div class="lineage-group">${{groups}}</div></details>`;
  }).join('');
}}
function metrics() {{
  const best = DATA.best_match || {{}};
  return `<div class="grid">
    <div class="panel metric"><div class="label">目标仓库 / Target</div><div class="value">${{esc(DATA.target)}}</div></div>
    <div class="panel metric"><div class="label">最佳匹配 / Best Match</div><div class="value">${{esc(best.ref || '无')}}</div></div>
    <div class="panel metric"><div class="label">Base 同源度 / Base Similarity</div><div class="value">${{best.base_similarity != null ? pct(best.base_similarity)+'%' : 'N/A'}}</div></div>
    <div class="panel metric"><div class="label">整体相似度 / Overall Similarity</div><div class="value">${{best.overall_similarity != null ? pct(best.overall_similarity)+'%' : 'N/A'}}</div></div>
  </div>`;
}}
document.getElementById('app').innerHTML = `${{metrics()}}<section class="panel"><h2>相似度排名 / Similarity Ranking</h2>${{rankingTable()}}</section><section style="margin-top:16px"><h2>继承、修改与独有差异 / Lineage Differences</h2>${{lineageDetails()}}</section><p class="muted">${{esc(DATA.notes_zh)}} / ${{esc(DATA.notes_en)}}</p>`;
</script>
</main>
</body>
</html>""".replace("{{", "{").replace("}}", "}").replace("__PAYLOAD__", payload)
    path = out / "index.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


def _dedupe(xs: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in xs:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    output_root = Path(args.output_root)
    target_dir = output_root / args.target / "_agent_d"
    compare_dir = output_root / args.target / "_agent_c"
    corpus_env = os.environ.get("AGENT_C_CORPUS_REPOS", "")
    corpus_names = args.corpus or [n.strip() for n in corpus_env.split(",") if n.strip()]
    if not corpus_names:
        print("错误：corpus 为空。请传命令行参数或设置 AGENT_C_CORPUS_REPOS", file=sys.stderr)
        sys.exit(2)

    if not target_dir.is_dir() or not (target_dir / "compare_index.json").is_file():
        print(f"错误：target 没有 Agent D 产物: {target_dir}\\compare_index.json", file=sys.stderr)
        sys.exit(2)

    corpus_dirs = []
    for name in corpus_names:
        d = output_root / name / "_agent_d"
        if (d / "compare_index.json").is_file():
            corpus_dirs.append(str(d))
        else:
            print(f"  跳过 {name}: 无 _agent_d/compare_index.json")
    if not corpus_dirs:
        print("错误：corpus 全无效", file=sys.stderr)
        sys.exit(2)

    print("== Agent C: KernelProject Compare ==")
    print(f"  target: {args.target}")
    print(f"  corpus: {corpus_names}")
    print("  source access: disabled; comparing Agent D products only")
    summary = run_agent_c_compare(str(target_dir), corpus_dirs, output_dir=str(compare_dir), progress_cb=lambda s, i: print(f"  [{s}] {i}"))
    print()
    print("== 完成 ==")
    for r in summary["ranking"][:3]:
        print(
            f"  {r['ref']:30s} derivation_strength={r['derivation_strength']:.4f} "
            f"design={r['design_claim_score']:.4f} relation={r['architecture_relation_score']:.4f} "
            f"code={r['code_structure_score']:.4f}"
        )
    print(f"  compare_report: {summary['compare_report']}")
    print(f"  lineage: {summary['lineage']}")
    print(f"  index_html: {summary['index_html']}")


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Agent C: compare Agent D KernelProject design products")
    parser.add_argument("target")
    parser.add_argument("corpus", nargs="*")
    parser.add_argument("--output-root", default=os.environ.get("AGENT_OUTPUT_ROOT", "output"))
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


if __name__ == "__main__":
    main()
