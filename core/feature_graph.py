from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List, Tuple

from core.agent_graph_state import EvidenceRecord
from core.describe_stage_qa import load_stage_qa
from core.feature_schema_bank import TECH_STAGE_IDS, features_for_stage_qa


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_:.\\/-]+", "_", str(value or "").strip())[:180]


def _node(node_id: str, labels: List[str], **props: Any) -> Dict[str, Any]:
    out = {"id": _safe_id(node_id), "labels": labels, "properties": {}}
    for k, v in props.items():
        if v is not None:
            out["properties"][k] = v
    return out


def _edge(src: str, dst: str, edge_type: str, **props: Any) -> Dict[str, Any]:
    out = {"source": _safe_id(src), "target": _safe_id(dst), "type": edge_type, "properties": {}}
    for k, v in props.items():
        if v is not None:
            out["properties"][k] = v
    return out


def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _dedupe_nodes_edges(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    node_map: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        node_id = n.get("id")
        if not node_id:
            continue
        if node_id in node_map:
            node_map[node_id]["labels"] = sorted(set(node_map[node_id].get("labels", [])) | set(n.get("labels", [])))
            node_map[node_id].setdefault("properties", {}).update(n.get("properties", {}))
        else:
            node_map[node_id] = n
    edge_seen = set()
    deduped_edges: List[Dict[str, Any]] = []
    for e in edges:
        key = (e.get("source"), e.get("target"), e.get("type"), json.dumps(e.get("properties", {}), ensure_ascii=False, sort_keys=True))
        if key in edge_seen:
            continue
        edge_seen.add(key)
        deduped_edges.append(e)
    return list(node_map.values()), deduped_edges


def _cypher_literal(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _write_cypher(path: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    lines: List[str] = []
    for n in nodes:
        labels = ":".join(_safe_id(x) for x in n.get("labels", []) if x)
        props = dict(n.get("properties", {}))
        props["id"] = n["id"]
        props_txt = ", ".join(f"{_safe_id(k)}: {_cypher_literal(v)}" for k, v in props.items())
        lines.append(f"MERGE (n:{labels} {{id: {json.dumps(n['id'], ensure_ascii=False)}}}) SET n += {{{props_txt}}};")
    for e in edges:
        etype = _safe_id(e.get("type") or "RELATED_TO").upper()
        props = dict(e.get("properties", {}))
        props_txt = " {" + ", ".join(f"{_safe_id(k)}: {_cypher_literal(v)}" for k, v in props.items()) + "}" if props else ""
        lines.append(
            f"MATCH (a {{id: {json.dumps(e['source'], ensure_ascii=False)}}}), "
            f"(b {{id: {json.dumps(e['target'], ensure_ascii=False)}}}) "
            f"MERGE (a)-[:{etype}{props_txt}]->(b);"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _xml_escape(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _write_graphml(path: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="type" for="edge" attr.name="type" attr.type="string"/>',
        '  <graph edgedefault="directed">',
    ]
    for n in nodes:
        label = ",".join(n.get("labels", []))
        lines.append(f'    <node id="{_xml_escape(n["id"])}"><data key="label">{_xml_escape(label)}</data></node>')
    for idx, e in enumerate(edges):
        lines.append(
            f'    <edge id="e{idx}" source="{_xml_escape(e["source"])}" target="{_xml_escape(e["target"])}">'
            f'<data key="type">{_xml_escape(e["type"])}</data></edge>'
        )
    lines.extend(["  </graph>", "</graphml>"])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def publish_feature_graph(
    *,
    repo_output_dir: str,
    evidence_records: Iterable[EvidenceRecord],
    stage_ids: Iterable[str] = TECH_STAGE_IDS,
) -> Dict[str, Any]:
    features_dir = os.path.join(repo_output_dir, "features")
    os.makedirs(features_dir, exist_ok=True)
    per_stage_dir = os.path.join(repo_output_dir, "_per_stage")
    evidence_by_id = {rec.evidence_id: rec for rec in evidence_records}
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    for stage_id in stage_ids:
        stage_qa = load_stage_qa(stage_id)
        features = features_for_stage_qa(stage_qa)
        if not features:
            continue
        with open(os.path.join(features_dir, f"{stage_id}_features.json"), "w", encoding="utf-8") as f:
            json.dump({"stage_id": stage_id, "features": features}, f, ensure_ascii=False, indent=2)

        subsystem_id = f"subsystem:{stage_id}"
        stage_title = stage_qa.get("stage_title") or stage_id
        nodes.append(_node(subsystem_id, ["Subsystem"], stage_id=stage_id, title=stage_title))
        for feature in features:
            fid = str(feature.get("feature_id") or "")
            if not fid:
                continue
            nodes.append(_node(fid, ["Feature"], **{k: feature.get(k) for k in ["stage_id", "domain", "feature_name", "description", "graph_tags"]}))
            edges.append(_edge(fid, subsystem_id, "IMPLEMENTS"))
            for dep in feature.get("dependencies", []) if isinstance(feature.get("dependencies"), list) else []:
                edges.append(_edge(fid, f"subsystem:{dep}", "DEPENDS_ON"))
            for qid in feature.get("question_ids", []) if isinstance(feature.get("question_ids"), list) else []:
                qnode = f"question:{qid}"
                nodes.append(_node(qnode, ["Question"], question_id=qid, stage_id=stage_id))
                edges.append(_edge(qnode, fid, "ASKED_BY"))

        answers_payload = _load_json(os.path.join(per_stage_dir, f"{stage_id}_answers.json"))
        for answer in answers_payload.get("answers", []) if isinstance(answers_payload.get("answers"), list) else []:
            if not isinstance(answer, dict):
                continue
            qid = str(answer.get("question_id") or "")
            claim_id = f"claim:{stage_id}:{qid}"
            nodes.append(
                _node(
                    claim_id,
                    ["Claim"],
                    stage_id=stage_id,
                    question_id=qid,
                    question_type=answer.get("question_type"),
                    value=answer.get("value"),
                )
            )
            edges.append(_edge(f"question:{qid}", claim_id, "EVIDENCED_BY"))
            fact_nodes_by_key: Dict[str, str] = {}
            for fact in answer.get("fact_answers", []) if isinstance(answer.get("fact_answers"), list) else []:
                if not isinstance(fact, dict):
                    continue
                fact_id = str(fact.get("fact_id") or "").strip()
                if not fact_id:
                    continue
                fact_node = f"fact_answer:{stage_id}:{qid}:{fact_id}"
                nodes.append(
                    _node(
                        fact_node,
                        ["FactAnswer"],
                        stage_id=stage_id,
                        question_id=qid,
                        fact_id=fact_id,
                        fact_key=fact.get("fact_key"),
                        value=fact.get("value"),
                        notes=fact.get("notes"),
                    )
                )
                edges.append(_edge(claim_id, fact_node, "DERIVED_FROM"))
                fact_key = str(fact.get("fact_key") or "").strip()
                if fact_key:
                    fact_nodes_by_key[fact_key] = fact_node
                for evid in fact.get("used_evidence_ids", []) if isinstance(fact.get("used_evidence_ids"), list) else []:
                    evid = str(evid or "").strip()
                    if evid:
                        edges.append(_edge(fact_node, f"evidence:{evid}", "EVIDENCED_BY"))
            value = answer.get("value")
            if isinstance(value, dict):
                for field_key, field_value in value.items():
                    field_key = str(field_key or "").strip()
                    if not field_key:
                        continue
                    field_node = f"answer_field:{stage_id}:{qid}:{field_key}"
                    nodes.append(
                        _node(
                            field_node,
                            ["AnswerField"],
                            stage_id=stage_id,
                            question_id=qid,
                            field_key=field_key,
                            value=field_value,
                        )
                    )
                    edges.append(_edge(claim_id, field_node, "HAS_FIELD"))
                    fact_node = fact_nodes_by_key.get(field_key)
                    if fact_node:
                        edges.append(_edge(field_node, fact_node, "DERIVED_FROM"))
            for ev in answer.get("evidence", []) if isinstance(answer.get("evidence"), list) else []:
                if not isinstance(ev, dict):
                    continue
                evid = str(ev.get("evidence_id") or "").strip()
                if not evid:
                    continue
                rec = evidence_by_id.get(evid)
                ev_node = f"evidence:{evid}"
                nodes.append(
                    _node(
                        ev_node,
                        ["Evidence"],
                        evidence_id=evid,
                        evidence_type=getattr(rec, "evidence_type", None),
                        strength=getattr(rec, "strength", None),
                        validity=getattr(rec, "validity", None),
                        supports_claim_types=getattr(rec, "supports_claim_types", None),
                    )
                )
                edges.append(_edge(claim_id, ev_node, "EVIDENCED_BY"))
                path = getattr(rec, "path", "") if rec else str(ev.get("path") or "")
                if path:
                    file_node = f"file:{path}"
                    nodes.append(_node(file_node, ["File"], path=path))
                    edges.append(_edge(ev_node, file_node, "LOCATED_IN"))
                symbol = getattr(rec, "symbol", None) if rec else ev.get("symbol_name")
                if symbol:
                    sym_node = f"symbol:{path}:{symbol}"
                    nodes.append(_node(sym_node, ["Symbol"], symbol=symbol, path=path))
                    edges.append(_edge(ev_node, sym_node, "LOCATED_IN"))

    nodes, edges = _dedupe_nodes_edges(nodes, edges)
    graph = {
        "schema_version": "feature_graph_v1",
        "nodes": nodes,
        "edges": edges,
        "stats": {"nodes": len(nodes), "edges": len(edges)},
    }
    json_path = os.path.join(repo_output_dir, "feature_graph.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    _write_cypher(os.path.join(repo_output_dir, "feature_graph.cypher"), nodes, edges)
    _write_graphml(os.path.join(repo_output_dir, "feature_graph.graphml"), nodes, edges)
    return graph
