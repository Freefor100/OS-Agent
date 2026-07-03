from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from core.evidence import stable_id
from core.git_source import read_text
from tools.code_atlas.minhash import jaccard_estimate, signature_from_set

COMPARISON_SCHEMA = "function_comparison_v4_joint_match"
EDGE_THRESHOLD = 0.45
STATUSES = ("exact_copied", "renamed_exact", "modified_candidate", "target_only", "base_only", "ambiguous")
WEAK_CANDIDATE_BUCKET_LIMIT = 96


def compare_unit_sets(target_units: list[dict[str, Any]], base_units: list[dict[str, Any]], *, target_snapshot: dict | None = None,
                      base_snapshot: dict | None = None) -> dict[str, Any]:
    _NEIGHBOR_SIG_CACHE.clear()
    _PAIR_SIGNALS_CACHE.clear()
    _PAIR_SCORE_CACHE.clear()
    match_edges = build_match_edges(target_units, base_units, source_role="primary_base", source_repo=str((base_snapshot or {}).get("repo") or ""))
    edge_by_pair = {(row["target_unit_id"], row["source_unit_id"]): row["edge_id"] for row in match_edges}
    by_fp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in base_units:
        if unit.get("fp"):
            by_fp[str(unit["fp"])].append(unit)

    used_base: set[str] = set()
    ambiguous_base: set[str] = set()
    comparisons: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for target in target_units:
        matches = [x for x in by_fp.get(str(target.get("fp") or ""), []) if x.get("unit_id") not in used_base]
        same = [x for x in matches if _name(x) == _name(target)]
        if same:
            chosen = _closest_path(target, same)
            comparisons.append(_record("exact_copied", target, chosen, _signals(target, chosen), edge_by_pair))
            used_base.add(str(chosen["unit_id"]))
        elif len(matches) == 1:
            chosen = matches[0]
            comparisons.append(_record("renamed_exact", target, chosen, _signals(target, chosen), edge_by_pair))
            used_base.add(str(chosen["unit_id"]))
        elif len(matches) > 1:
            ambiguous_base.update(str(x["unit_id"]) for x in matches)
            comparisons.append(_record("ambiguous", target, None, {"candidate_base_unit_ids": [x["unit_id"] for x in matches], "reason": "multiple exact fingerprint matches"}, edge_by_pair))
        else:
            unresolved.append(target)

    remaining_by_id = {str(x.get("unit_id")): x for x in base_units if str(x.get("unit_id")) not in used_base}

    # Build a candidate index from existing match edges so the scoring loop
    # only evaluates plausible pairs instead of O(n*m) on the full set.
    # build_match_edges already found edges for units sharing FP/AST/name/leaf.
    _candidates_by_target: dict[str, set[str]] = defaultdict(set)
    for edge in match_edges:
        tid = str(edge.get("target_unit_id") or "")
        sid = str(edge.get("source_unit_id") or "")
        if tid and sid:
            _candidates_by_target[tid].add(sid)

    for target in unresolved:
        tid = str(target.get("unit_id") or "")
        candidate_ids = _candidates_by_target.get(tid, set())
        if not candidate_ids:
            comparisons.append(_record("target_only", target, None, {"reason": "no deterministic base match"}, edge_by_pair))
            continue
        candidates = [remaining_by_id[bid] for bid in candidate_ids if bid in remaining_by_id]

        ranked = sorted(((_pair_score(target, base), base) for base in candidates), key=lambda x: x[0], reverse=True)
        viable = [(score, base) for score, base in ranked if _is_modified_candidate(target, base, score)]
        if not viable:
            comparisons.append(_record("target_only", target, None, {"reason": "no deterministic base match"}, edge_by_pair))
            continue
        if len(viable) > 1 and viable[0][0] - viable[1][0] < 0.06:
            ambiguous_base.update(str(base["unit_id"]) for _, base in viable[:5])
            comparisons.append(_record("ambiguous", target, None, {
                "reason": "multiple near-equal structural matches",
                "candidate_base_unit_ids": [base["unit_id"] for _, base in viable[:5]],
                "candidate_scores": [round(score, 3) for score, _ in viable[:5]],
            }, edge_by_pair))
            continue
        score, chosen = viable[0]
        comparisons.append(_record("modified_candidate", target, chosen, _signals(target, chosen) | {"pair_score": round(score, 3)}, edge_by_pair))
        used_base.add(str(chosen["unit_id"]))
        remaining_by_id.pop(str(chosen.get("unit_id")), None)

    for base in base_units:
        if str(base.get("unit_id")) not in used_base and str(base.get("unit_id")) not in ambiguous_base:
            comparisons.append(_record("base_only", None, base, {"reason": "no target match"}, edge_by_pair))

    summary = Counter(row["raw_status"] for row in comparisons)
    return {
        "schema_version": COMPARISON_SCHEMA,
        "target_snapshot": target_snapshot or {},
        "base_snapshot": base_snapshot or {},
        "summary": {status: summary.get(status, 0) for status in STATUSES},
        "target_units": target_units, "base_units": base_units, "match_edges": match_edges,
        "comparisons": comparisons,
    }


def write_comparison(result: dict[str, Any], output_dir: str) -> dict[str, str]:
    from core.comparison_db import write_comparison_database
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    rows_path = out / "comparisons.jsonl"
    rows_path.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in result.get("comparisons", [])), encoding="utf-8")
    index = _build_index(result.get("comparisons", []))
    metadata_path = out / "comparison_metadata.json"
    metadata_path.write_text(json.dumps({"schema_version": COMPARISON_SCHEMA, "target_snapshot": result.get("target_snapshot", {}), "base_snapshot": result.get("base_snapshot", {}), "target_scope": result.get("target_scope", {}), "base_scope": result.get("base_scope", {})}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    index_path = out / "comparison_index.json"
    index_path.write_text(json.dumps({"schema_version": COMPARISON_SCHEMA, "summary": result.get("summary", {}), **index}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    database = write_comparison_database(result, str(out / "comparison.sqlite"))
    return {"comparisons": str(rows_path), "index": str(index_path), "metadata": str(metadata_path), **database}


def query_comparisons(path: str, *, status: str = "", directory: str = "", symbol: str = "", comparison_id: str = "",
                      offset: int = 0, limit: int = 50) -> dict[str, Any]:
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if comparison_id and row.get("comparison_id") != comparison_id: continue
            if status and row.get("raw_status") != status: continue
            units = [row.get("target_unit") or {}, row.get("base_unit") or {}]
            if directory and not any(str(x.get("file") or "").startswith(directory) for x in units): continue
            if symbol and not any(symbol.lower() in str(x.get("name") or "").lower() for x in units): continue
            rows.append(row)
    return {"total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset + limit]}


def read_source_pair(comparisons_path: str, comparison_id: str, context_lines: int = 8) -> dict[str, Any]:
    """Read both source spans from immutable snapshots recorded beside comparisons.jsonl."""
    rows = query_comparisons(comparisons_path, comparison_id=comparison_id, limit=1)["rows"]
    if not rows:
        return {"status": "not_found", "comparison_id": comparison_id}
    rec = rows[0]; out: dict[str, Any] = {"comparison_id": comparison_id, "comparison": rec}
    metadata_path = Path(comparisons_path).parent / "comparison_metadata.json"
    if not metadata_path.is_file():
        return out | {"status": "metadata_missing"}
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    for side in ("target", "base"):
        unit = rec.get(f"{side}_unit"); snapshot = metadata.get(f"{side}_snapshot") or {}
        if not unit:
            continue
        try:
            lines = read_text(str(snapshot.get("repo_path") or ""), str(snapshot.get("commit") or ""), str(unit.get("file") or "")).splitlines()
        except Exception:
            out[f"{side}_source"] = {"status": "not_found", "file": unit.get("file")}; continue
        line = max(1, int(unit.get("line") or 1)); end_line = max(line, int(unit.get("end_line") or line))
        lo = max(1, line-context_lines); hi = min(len(lines), end_line+context_lines)
        out[f"{side}_source"] = {"snapshot_commit": snapshot.get("commit"), "file": unit.get("file"), "line_start": lo, "line_end": hi,
                                  "content": "\n".join(f"{n}: {lines[n-1]}" for n in range(lo, hi+1))}
    out["status"] = "ok"
    return out


def build_match_edges(target_units: list[dict[str, Any]], source_units: list[dict[str, Any]], *, source_role: str = "primary_base", source_repo: str = "") -> list[dict[str, Any]]:
    """Build candidate relations without asserting merge or split semantics."""
    by_fp: dict[str, list[dict[str, Any]]] = defaultdict(list); by_ast: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list); by_leaf: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in source_units:
        if unit.get("fp"): by_fp[str(unit["fp"])].append(unit)
        if unit.get("ast"): by_ast[str(unit["ast"])].append(unit)
        if _name(unit): by_name[_name(unit)].append(unit)
        by_leaf[Path(str(unit.get("file") or "")).name.lower()].append(unit)
    edges=[]; seen=set()
    for target in target_units:
        candidates={}
        candidate_buckets = (
            by_fp.get(str(target.get("fp") or ""), []),
            by_ast.get(str(target.get("ast") or ""), []),
            _bounded_bucket(by_name.get(_name(target), [])),
            _bounded_bucket(by_leaf.get(Path(str(target.get("file") or "")).name.lower(), [])),
        )
        for rows in candidate_buckets:
            for source in rows: candidates[str(source.get("unit_id"))]=source
        for source in candidates.values():
            key=(str(target.get("unit_id")),str(source.get("unit_id")))
            if key in seen: continue
            seen.add(key)
            if str(target.get("fp") or "") and str(target.get("fp")) == str(source.get("fp")):
                # Exact fp match — skip expensive _signals / _pair_score
                signals = {
                    "same_name": _name(target) == _name(source),
                    "exact_token_fp": True,
                    "exact_ast_shape": bool(target.get("ast") and target.get("ast") == source.get("ast")),
                    "token_similarity": 1.0,
                    "path_role_similarity": _path_role_similarity(target, source),
                    "call_neighbor_similarity": 0.0,
                }
                _PAIR_SIGNALS_CACHE[_pair_key(target, source)] = signals
                _PAIR_SCORE_CACHE[_pair_key(target, source)] = 1.0
                score = 1.0
            else:
                signals = _signals(target, source)
                score = _pair_score(target, source)
            if score < EDGE_THRESHOLD: continue
            edges.append({"edge_id":stable_id("edge",{"target":key[0],"source":key[1],"role":source_role},16),"target_unit_id":key[0],"source_unit_id":key[1],"source_role":source_role,"source_repo":source_repo,"pair_score":round(score,3),"signals":signals})
    return sorted(edges,key=lambda row:(row["target_unit_id"],-row["pair_score"],row["source_unit_id"]))


def _record(status: str, target: dict | None, base: dict | None, signals: dict[str, Any], edge_by_pair: dict[tuple[str,str],str]) -> dict[str, Any]:
    payload = {"status": status, "target": (target or {}).get("unit_id"), "base": (base or {}).get("unit_id")}
    target_id=str((target or {}).get("unit_id") or ""); base_id=str((base or {}).get("unit_id") or "")
    supporting=[edge_by_pair[(target_id,base_id)]] if (target_id,base_id) in edge_by_pair else []
    return {"comparison_id": stable_id("cmp", payload, 16), "raw_status": status, "target_unit_id":target_id or None,
            "selected_base_unit_id":base_id or None,"supporting_edge_ids":supporting,"target_unit": _compact(target), "base_unit": _compact(base), "signals": signals}


def _compact(unit: dict | None) -> dict | None:
    if unit is None: return None
    return {key: unit.get(key) for key in ("unit_id", "file", "line", "end_line", "name", "lang", "sz", "fp", "ast", "commit")}


def _bounded_bucket(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return rows if len(rows) <= WEAK_CANDIDATE_BUCKET_LIMIT else []


def _signals(target: dict, base: dict) -> dict[str, Any]:
    key = _pair_key(target, base)
    cached = _PAIR_SIGNALS_CACHE.get(key)
    if cached is not None:
        return cached
    token = jaccard_estimate(target.get("sig") or [], base.get("sig") or []) if target.get("sig") and base.get("sig") else 0.0
    neighbors = _neighbor_similarity(target, base)
    signals = {"same_name": _name(target) == _name(base), "exact_token_fp": bool(target.get("fp") and target.get("fp") == base.get("fp")),
               "exact_ast_shape": bool(target.get("ast") and target.get("ast") == base.get("ast")), "token_similarity": round(token, 3),
               "path_role_similarity": round(_path_role_similarity(target, base), 3), "call_neighbor_similarity": round(neighbors, 3)}
    _PAIR_SIGNALS_CACHE[key] = signals
    return signals


def _is_modified_candidate(target: dict, base: dict, score: float) -> bool:
    if score >= 0.55:
        return True
    signals = _signals(target, base)
    return bool(score >= 0.50 and signals["same_name"] and signals["path_role_similarity"] >= 0.9 and signals["call_neighbor_similarity"] >= 0.65)


def _pair_score(target: dict, base: dict) -> float:
    key = _pair_key(target, base)
    cached = _PAIR_SCORE_CACHE.get(key)
    if cached is not None:
        return cached
    sig = _signals(target, base)
    name = 1.0 if sig["same_name"] else 0.0
    ast = 1.0 if sig["exact_ast_shape"] else 0.0
    score = 0.25 * name + 0.30 * sig["token_similarity"] + 0.20 * ast + 0.15 * sig["path_role_similarity"] + 0.10 * sig["call_neighbor_similarity"]
    # Same-name alone is deliberately insufficient.
    if name and not ast and sig["token_similarity"] < 0.25 and sig["path_role_similarity"] < 0.5:
        score = 0.0
    _PAIR_SCORE_CACHE[key] = score
    return score


_NEIGHBOR_SIG_CACHE: dict[str, list[int]] = {}
_PAIR_SIGNALS_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_PAIR_SCORE_CACHE: dict[tuple[str, str], float] = {}


def _pair_key(target: dict, base: dict) -> tuple[str, str]:
    return str(target.get("unit_id") or ""), str(base.get("unit_id") or "")

def _neighbor_sig(unit: dict) -> list[int]:
    uid = str(unit.get("unit_id") or "")
    cached = _NEIGHBOR_SIG_CACHE.get(uid)
    if cached is not None:
        return cached
    names = set(unit.get("outgoing_names") or []) | set(unit.get("incoming_names") or [])
    sig = signature_from_set(names) if names else []
    _NEIGHBOR_SIG_CACHE[uid] = sig
    return sig

def _neighbor_similarity(a: dict, b: dict) -> float:
    left = _neighbor_sig(a)
    right = _neighbor_sig(b)
    if not left or not right: return 0.0
    return jaccard_estimate(left, right)


def _path_role_similarity(a: dict, b: dict) -> float:
    pa = str(a.get("file") or "").lower().split("/")
    pb = str(b.get("file") or "").lower().split("/")
    if not pa or not pb: return 0.0
    sa, sb = set(pa[-3:]), set(pb[-3:])
    return len(sa & sb) / max(1, len(sa | sb))


def _closest_path(target: dict, rows: list[dict]) -> dict:
    return max(rows, key=lambda x: _path_role_similarity(target, x))


def _name(unit: dict) -> str:
    return str(unit.get("name") or "").lower()


def _build_index(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, list[str]] = defaultdict(list); by_directory: dict[str, list[str]] = defaultdict(list); by_symbol: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        cid = row["comparison_id"]; by_status[row["raw_status"]].append(cid)
        for unit in (row.get("target_unit"), row.get("base_unit")):
            if not unit: continue
            by_directory[str(Path(str(unit.get("file") or "")).parent)].append(cid)
            by_symbol[str(unit.get("name") or "").lower()].append(cid)
    return {"by_status": dict(by_status), "by_directory": dict(by_directory), "by_symbol": dict(by_symbol)}
