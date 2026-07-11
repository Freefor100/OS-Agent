from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from core.evidence import stable_id
from core.git_source import read_text

DB_SCHEMA = "comparison_db_v1"
STATUSES = ("exact_copied", "renamed_exact", "modified_candidate", "target_only", "base_only", "ambiguous")

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE runs(run_id TEXT PRIMARY KEY, schema_version TEXT NOT NULL, target_snapshot_json TEXT NOT NULL, base_snapshot_json TEXT NOT NULL, target_scope_json TEXT NOT NULL, base_scope_json TEXT NOT NULL);
CREATE TABLE source_snapshots(run_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, source_role TEXT NOT NULL, repo TEXT NOT NULL, snapshot_json TEXT NOT NULL, PRIMARY KEY(run_id,snapshot_id));
CREATE TABLE units(unit_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, snapshot_id TEXT, side TEXT NOT NULL, source_role TEXT NOT NULL, repo TEXT, file TEXT NOT NULL, directory TEXT NOT NULL, symbol TEXT, line INTEGER, end_line INTEGER, lang TEXT, sz INTEGER, fp TEXT, ast TEXT, FOREIGN KEY(run_id) REFERENCES runs(run_id));
CREATE TABLE match_edges(edge_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, target_unit_id TEXT NOT NULL, source_unit_id TEXT NOT NULL, source_role TEXT NOT NULL, source_repo TEXT, pair_score REAL NOT NULL, signals_json TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id));
CREATE TABLE comparisons(comparison_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, raw_status TEXT NOT NULL, target_unit_id TEXT, selected_base_unit_id TEXT, supporting_edge_ids_json TEXT NOT NULL, signals_json TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id));
CREATE TABLE relationship_hints(hint_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, hint_type TEXT NOT NULL, confidence TEXT NOT NULL, target_unit_ids_json TEXT NOT NULL, source_unit_ids_json TEXT NOT NULL, edge_ids_json TEXT NOT NULL, metadata_json TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id));
CREATE INDEX idx_units_run_side_file ON units(run_id, side, file);
CREATE INDEX idx_units_run_dir ON units(run_id, side, directory);
CREATE INDEX idx_units_run_symbol ON units(run_id, symbol);
CREATE INDEX idx_edges_target ON match_edges(run_id, target_unit_id, source_role, pair_score DESC);
CREATE INDEX idx_edges_source ON match_edges(run_id, source_unit_id, pair_score DESC);
CREATE INDEX idx_comparisons_status ON comparisons(run_id, raw_status);
CREATE INDEX idx_comparisons_target ON comparisons(run_id, target_unit_id);
CREATE INDEX idx_comparisons_base ON comparisons(run_id, selected_base_unit_id);
CREATE INDEX idx_hints_type ON relationship_hints(run_id, hint_type);
"""


def write_comparison_database(result: dict[str, Any], database_path: str) -> dict[str, Any]:
    target_snapshot = result.get("target_snapshot") or {}; base_snapshot = result.get("base_snapshot") or {}
    target_scope = result.get("target_scope") or {}; base_scope = result.get("base_scope") or {}
    run_id = stable_id("run", {"target": target_snapshot.get("snapshot_id") or target_snapshot.get("commit"), "base": base_snapshot.get("snapshot_id") or base_snapshot.get("commit"), "target_scope": target_scope.get("scope_id"), "base_scope": base_scope.get("scope_id"), "database_schema": DB_SCHEMA, "comparison_schema": result.get("schema_version")}, 16)
    path = Path(database_path); path.parent.mkdir(parents=True, exist_ok=True); path.unlink(missing_ok=True)
    con = sqlite3.connect(path); con.executescript(SCHEMA)
    con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (run_id, DB_SCHEMA, _json(target_snapshot), _json(base_snapshot), _json(target_scope), _json(base_scope)))
    con.executemany("INSERT INTO source_snapshots VALUES(?,?,?,?,?)", [(run_id, str(target_snapshot.get("snapshot_id") or "target"), "target", str(target_snapshot.get("repo") or ""), _json(target_snapshot)), (run_id, str(base_snapshot.get("snapshot_id") or "base"), "primary_base", str(base_snapshot.get("repo") or ""), _json(base_snapshot))])
    _insert_units(con, run_id, result.get("target_units") or [], "target", "target", target_snapshot.get("repo", ""))
    _insert_units(con, run_id, result.get("base_units") or [], "primary_base", "primary_base", base_snapshot.get("repo", ""))
    edges = result.get("match_edges") or []
    con.executemany("INSERT INTO match_edges VALUES(?,?,?,?,?,?,?,?)", [(x["edge_id"], run_id, x["target_unit_id"], x["source_unit_id"], x.get("source_role", "primary_base"), x.get("source_repo") or base_snapshot.get("repo", ""), float(x.get("pair_score") or 0), _json(x.get("signals") or {})) for x in edges])
    con.executemany("INSERT INTO comparisons VALUES(?,?,?,?,?,?,?)", [(x["comparison_id"], run_id, x["raw_status"], x.get("target_unit_id") or _uid(x.get("target_unit")), x.get("selected_base_unit_id") or _uid(x.get("base_unit")), _json(x.get("supporting_edge_ids") or []), _json(x.get("signals") or {})) for x in result.get("comparisons") or []])
    hints = build_relationship_hints(edges, result.get("target_units") or [], result.get("base_units") or [])
    con.executemany("INSERT INTO relationship_hints VALUES(?,?,?,?,?,?,?,?)", [(x["hint_id"], run_id, x["hint_type"], x["confidence"], _json(x["target_unit_ids"]), _json(x["source_unit_ids"]), _json(x["edge_ids"]), _json(x.get("metadata") or {})) for x in hints])
    con.commit(); con.close()
    return {"database": str(path), "run_id": run_id, "match_edges": len(edges), "relationship_hints": len(hints)}


def add_secondary_source(database_path: str, source_snapshot: dict[str, Any], source_units: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    con = _connect(database_path); run_id = _run_id(con); repo = source_snapshot.get("repo", "")
    con.execute("INSERT OR REPLACE INTO source_snapshots VALUES(?,?,?,?,?)", (run_id, str(source_snapshot.get("snapshot_id") or source_snapshot.get("commit")), "secondary_source", repo, _json(source_snapshot)))
    _insert_units(con, run_id, source_units, "secondary_source", "secondary_source", repo)
    con.executemany("INSERT OR REPLACE INTO match_edges VALUES(?,?,?,?,?,?,?,?)", [(x["edge_id"], run_id, x["target_unit_id"], x["source_unit_id"], "secondary_source", repo, float(x.get("pair_score") or 0), _json(x.get("signals") or {})) for x in edges])
    _replace_hints(con, run_id); con.commit(); con.close()
    return {"run_id": run_id, "source_repo": repo, "units": len(source_units), "match_edges": len(edges)}


def build_relationship_hints(edges: list[dict[str, Any]], target_units: list[dict[str, Any]], source_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list); by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    files: dict[str, set[str]] = defaultdict(set); edge_ids_by_file: dict[str, list[str]] = defaultdict(list); target_ids_by_file: dict[str, list[str]] = defaultdict(list); source_ids_by_file: dict[str, list[str]] = defaultdict(list)
    source_file = {str(x.get("unit_id")): str(x.get("file") or "") for x in source_units}; target_file = {str(x.get("unit_id")): str(x.get("file") or "") for x in target_units}
    for edge in edges:
        by_target[edge["target_unit_id"]].append(edge); by_source[edge["source_unit_id"]].append(edge)
        tf = target_file.get(edge["target_unit_id"], ""); sf = source_file.get(edge["source_unit_id"], "")
        if tf and sf:
            files[tf].add(sf); edge_ids_by_file[tf].append(edge["edge_id"]); target_ids_by_file[tf].append(edge["target_unit_id"]); source_ids_by_file[tf].append(edge["source_unit_id"])
    hints=[]
    for tid, rows in by_target.items():
        strong=[x for x in rows if float(x.get("pair_score") or 0)>=0.55]
        if len(strong)>1: hints.append(_hint("many_sources_to_one_target", [tid], [x["source_unit_id"] for x in strong], [x["edge_id"] for x in strong]))
    for sid, rows in by_source.items():
        strong=[x for x in rows if float(x.get("pair_score") or 0)>=0.55]
        if len(strong)>1: hints.append(_hint("one_source_to_many_targets", [x["target_unit_id"] for x in strong], [sid], [x["edge_id"] for x in strong]))
    for tf, sfs in files.items():
        if len(sfs)>1: hints.append(_hint("multi_file_affinity", target_ids_by_file[tf], source_ids_by_file[tf], edge_ids_by_file[tf], {"target_file":tf,"source_files":sorted(sfs)}))
    return hints


def overview(database_path: str) -> dict[str, Any]:
    con=_connect(database_path); run_id=_run_id(con)
    summary={row[0]:row[1] for row in con.execute("SELECT raw_status,count(*) FROM comparisons WHERE run_id=? GROUP BY raw_status",(run_id,))}
    result={"run_id":run_id,"summary":{s:summary.get(s,0) for s in STATUSES},"target_units":_scalar(con,"SELECT count(*) FROM units WHERE run_id=? AND side='target'",run_id),"source_units":_scalar(con,"SELECT count(*) FROM units WHERE run_id=? AND side!='target'",run_id),"match_edges":_scalar(con,"SELECT count(*) FROM match_edges WHERE run_id=?",run_id),"relationship_hints":_scalar(con,"SELECT count(*) FROM relationship_hints WHERE run_id=?",run_id),"hotspots":hotspots(database_path,"modified",0,10)["rows"]}
    con.close(); return result


def hotspots(database_path: str, order_by: str="modified", offset: int=0, limit: int=20) -> dict[str, Any]:
    rows=_file_rows(database_path); key={"modified":"modified_candidate","added":"target_only","renamed":"renamed_exact","compound":"source_file_count",**{s:s for s in STATUSES}}.get(order_by,"modified_candidate")
    rows.sort(key=lambda x:(-int(x.get(key,0)), -x["total"], x["target_file"]))
    return _page(rows,offset,limit)


def directory_summary(database_path: str, path: str="", side: str="target") -> dict[str, Any]:
    if side != "target":
        selected=source_file_targets_all(database_path,path)
        return {"path":path,"side":"source","source_file_count":len(selected),"source_files":sorted(selected,key=lambda x:(-x["target_file_count"],-x["matched_units"],x["source_file"]))[:20]}
    selected=[x for x in _file_rows(database_path) if x["target_file"].startswith(path)]; summary=Counter()
    [summary.update({k:v for k,v in row.items() if k in STATUSES}) for row in selected]
    return {"path":path,"side":side,"summary":{s:summary.get(s,0) for s in STATUSES},"file_count":len(selected),"hot_files":sorted(selected,key=lambda x:(-(x.get("modified_candidate",0)+x.get("target_only",0)+x.get("renamed_exact",0)),x.get("target_file","")))[:20]}


def directory_files(database_path: str, path: str="", status: str="", offset: int=0, limit: int=50) -> dict[str, Any]:
    rows=[x for x in _file_rows(database_path) if x["target_file"].startswith(path) and (not status or x.get(status,0)>0)]
    return _page(rows,offset,limit)


def comparisons_by_status(database_path: str, status: str, path: str="", offset: int=0, limit: int=50) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid comparison status: {status}")
    con=_connect(database_path); run_id=_run_id(con)
    sql="""SELECT c.comparison_id,c.raw_status,t.unit_id,t.file,t.symbol,t.line,b.unit_id,b.repo,b.file,b.symbol,c.signals_json
           FROM comparisons c LEFT JOIN units t ON t.unit_id=c.target_unit_id LEFT JOIN units b ON b.unit_id=c.selected_base_unit_id
           WHERE c.run_id=? AND c.raw_status=? AND (coalesce(t.file,b.file) LIKE ?) ORDER BY coalesce(t.file,b.file),coalesce(t.line,b.line),coalesce(t.symbol,b.symbol)"""
    rows=[{"comparison_id":r[0],"raw_status":r[1],
           "work_unit":{"unit_id":r[2],"file":r[3],"symbol":r[4],"line":r[5]} if r[2] else None,
           "reference_unit":{"unit_id":r[6],"repo":r[7],"file":r[8],"symbol":r[9]} if r[6] else None,
           "signals":json.loads(r[10])} for r in con.execute(sql,(run_id,status,f"{path}%"))]
    con.close(); return _page(rows,offset,limit)


def search_units(database_path: str, query: str="", side: str="target", path: str="", status: str="", offset: int=0, limit: int=50) -> dict[str, Any]:
    con=_connect(database_path); run_id=_run_id(con); params: list[Any]=[run_id]
    clauses=["u.run_id=?"]
    if side:
        clauses.append("u.side=?"); params.append(side)
    if path:
        clauses.append("u.file LIKE ?"); params.append(f"{path}%")
    if query:
        clauses.append("(lower(u.symbol) LIKE ? OR lower(u.file) LIKE ?)"); needle=f"%{query.lower()}%"; params.extend([needle,needle])
    if status:
        if status not in STATUSES: con.close(); raise ValueError(f"invalid comparison status: {status}")
        clauses.append("c.raw_status=?"); params.append(status)
    sql=f"""SELECT u.unit_id,u.side,u.source_role,u.repo,u.file,u.symbol,u.line,u.end_line,u.lang,
                   c.comparison_id,c.raw_status
            FROM units u LEFT JOIN comparisons c ON c.target_unit_id=u.unit_id OR c.selected_base_unit_id=u.unit_id
            WHERE {' AND '.join(clauses)} ORDER BY u.file,u.line,u.symbol"""
    rows=[{"unit_id":r[0],"side":r[1],"source_role":r[2],"repo":r[3],"file":r[4],"symbol":r[5],"line":r[6],"end_line":r[7],
           "lang":r[8],"comparison_id":r[9],"raw_status":r[10]} for r in con.execute(sql,params)]
    con.close(); return _page(rows,offset,limit)


def directory_sources(database_path: str, path: str="", offset: int=0, limit: int=50) -> dict[str, Any]:
    con=_connect(database_path); run_id=_run_id(con)
    sql="""SELECT s.repo,s.file,e.source_role,count(DISTINCT t.file),count(DISTINCT e.target_unit_id),avg(e.pair_score)
           FROM match_edges e JOIN units t ON t.unit_id=e.target_unit_id JOIN units s ON s.unit_id=e.source_unit_id
           WHERE e.run_id=? AND t.file LIKE ? GROUP BY s.repo,s.file,e.source_role
           ORDER BY count(DISTINCT e.target_unit_id) DESC,avg(e.pair_score) DESC"""
    rows=[{"source_repo":r[0],"source_file":r[1],"source_role":r[2],"work_file_count":r[3],
           "matched_units":r[4],"average_pair_score":round(r[5],3)} for r in con.execute(sql,(run_id,f"{path}%"))]
    con.close(); return _page(rows,offset,limit)


def file_summary(database_path: str, target_file: str) -> dict[str, Any]:
    row=next((x for x in _file_rows(database_path) if x["target_file"]==target_file),None)
    return row or {"target_file":target_file,"status":"not_found"}


def file_functions(database_path: str, target_file: str, status: str="", offset: int=0, limit: int=50) -> dict[str, Any]:
    con=_connect(database_path); run_id=_run_id(con); params=[run_id,target_file]; clause="" if not status else " AND c.raw_status=?"; params += [status] if status else []
    sql="""SELECT c.comparison_id,c.raw_status,t.unit_id,t.symbol,t.line,t.end_line,b.unit_id,b.repo,b.file,b.symbol,c.signals_json FROM comparisons c JOIN units t ON t.unit_id=c.target_unit_id LEFT JOIN units b ON b.unit_id=c.selected_base_unit_id WHERE c.run_id=? AND t.file=?"""+clause+" ORDER BY t.line,t.symbol"
    rows=[{"comparison_id":r[0],"raw_status":r[1],"target":{"unit_id":r[2],"symbol":r[3],"line":r[4],"end_line":r[5]},"primary_source":{"unit_id":r[6],"repo":r[7],"file":r[8],"symbol":r[9]} if r[6] else None,"signals":json.loads(r[10])} for r in con.execute(sql,params)]
    con.close(); return _page(rows,offset,limit)


def file_sources(database_path: str, target_file: str) -> dict[str, Any]:
    con=_connect(database_path); run_id=_run_id(con)
    sql="""SELECT s.repo,s.file,e.source_role,count(DISTINCT e.target_unit_id),avg(e.pair_score) FROM match_edges e JOIN units t ON t.unit_id=e.target_unit_id JOIN units s ON s.unit_id=e.source_unit_id WHERE e.run_id=? AND t.file=? GROUP BY s.repo,s.file,e.source_role ORDER BY count(DISTINCT e.target_unit_id) DESC,avg(e.pair_score) DESC"""
    total=_scalar(con,"SELECT count(*) FROM units WHERE run_id=? AND side='target' AND file=?",run_id,target_file)
    rows=[{"source_repo":r[0],"source_file":r[1],"source_role":r[2],"matched_units":r[3],"affinity":round(r[3]/max(1,total),3),"average_pair_score":round(r[4],3)} for r in con.execute(sql,(run_id,target_file))]
    con.close(); return {"target_file":target_file,"target_units":total,"source_files":rows}


def source_file_targets(database_path: str, source_repo: str, source_file: str) -> dict[str, Any]:
    con=_connect(database_path); run_id=_run_id(con)
    sql="""SELECT t.file,count(DISTINCT e.target_unit_id),avg(e.pair_score) FROM match_edges e JOIN units t ON t.unit_id=e.target_unit_id JOIN units s ON s.unit_id=e.source_unit_id WHERE e.run_id=? AND s.repo=? AND s.file=? GROUP BY t.file ORDER BY count(DISTINCT e.target_unit_id) DESC"""
    rows=[{"target_file":r[0],"matched_units":r[1],"average_pair_score":round(r[2],3)} for r in con.execute(sql,(run_id,source_repo,source_file))]; con.close()
    return {"source_repo":source_repo,"source_file":source_file,"target_files":rows}


def base_only_files(database_path: str, offset: int=0, limit: int=100) -> dict[str, Any]:
    con=_connect(database_path); run_id=_run_id(con)
    sql="""SELECT b.file,count(*),group_concat(b.symbol, char(31) ORDER BY b.symbol) FROM comparisons c JOIN units b ON b.unit_id=c.selected_base_unit_id WHERE c.run_id=? AND c.raw_status='base_only' GROUP BY b.file ORDER BY count(*) DESC,b.file"""
    rows=[{"base_file":r[0],"base_only":r[1],"symbols":str(r[2] or "").split(chr(31))} for r in con.execute(sql,(run_id,))]
    con.close(); return _page(rows,offset,limit)


def source_file_targets_all(database_path: str, path: str="") -> list[dict[str,Any]]:
    con=_connect(database_path); run_id=_run_id(con); rows=[{"source_repo":r[0],"source_file":r[1],"target_file_count":r[2],"matched_units":r[3]} for r in con.execute("SELECT s.repo,s.file,count(DISTINCT t.file),count(DISTINCT e.target_unit_id) FROM match_edges e JOIN units t ON t.unit_id=e.target_unit_id JOIN units s ON s.unit_id=e.source_unit_id WHERE e.run_id=? AND s.file LIKE ? GROUP BY s.repo,s.file",(run_id,f"{path}%"))]; con.close(); return rows


def function_detail(database_path: str, unit_id: str) -> dict[str, Any]:
    con=_connect(database_path); unit=con.execute("SELECT unit_id,side,repo,file,symbol,line,end_line,lang FROM units WHERE unit_id=?",(unit_id,)).fetchone()
    if not unit: con.close(); return {"status":"not_found","unit_id":unit_id}
    comparisons=[{"comparison_id":r[0],"raw_status":r[1]} for r in con.execute("SELECT comparison_id,raw_status FROM comparisons WHERE target_unit_id=? OR selected_base_unit_id=?",(unit_id,unit_id))]
    con.close(); return {"unit":{"unit_id":unit[0],"side":unit[1],"repo":unit[2],"file":unit[3],"symbol":unit[4],"line":unit[5],"end_line":unit[6],"lang":unit[7]},"comparisons":comparisons}


def function_candidates(database_path: str, unit_id: str, source_role: str="", offset: int=0, limit: int=50) -> dict[str, Any]:
    con=_connect(database_path); params=[unit_id]; clause="" if not source_role else " AND e.source_role=?"; params += [source_role] if source_role else []
    sql="""SELECT e.edge_id,e.source_role,e.source_repo,e.pair_score,e.signals_json,s.unit_id,s.file,s.symbol,s.line FROM match_edges e JOIN units s ON s.unit_id=e.source_unit_id WHERE e.target_unit_id=?"""+clause+" ORDER BY e.pair_score DESC"
    rows=[{"edge_id":r[0],"source_role":r[1],"source_repo":r[2],"pair_score":r[3],"signals":json.loads(r[4]),"source_unit":{"unit_id":r[5],"file":r[6],"symbol":r[7],"line":r[8]}} for r in con.execute(sql,params)]; con.close(); return _page(rows,offset,limit)


def comparison_detail(database_path: str, comparison_id: str) -> dict[str, Any]:
    con=_connect(database_path); row=con.execute("SELECT raw_status,target_unit_id,selected_base_unit_id,supporting_edge_ids_json,signals_json FROM comparisons WHERE comparison_id=?",(comparison_id,)).fetchone(); con.close()
    return {"status":"not_found","comparison_id":comparison_id} if not row else {"comparison_id":comparison_id,"raw_status":row[0],"target_unit_id":row[1],"selected_base_unit_id":row[2],"supporting_edge_ids":json.loads(row[3]),"signals":json.loads(row[4])}


def relationship_hints(database_path: str, hint_type: str="", offset: int=0, limit: int=50) -> dict[str, Any]:
    con=_connect(database_path); run_id=_run_id(con); params=[run_id]; clause="" if not hint_type else " AND hint_type=?"; params += [hint_type] if hint_type else []
    rows=[{"hint_id":r[0],"hint_type":r[1],"confidence":r[2],"target_unit_ids":json.loads(r[3]),"source_unit_ids":json.loads(r[4]),"edge_ids":json.loads(r[5]),"metadata":json.loads(r[6])} for r in con.execute("SELECT hint_id,hint_type,confidence,target_unit_ids_json,source_unit_ids_json,edge_ids_json,metadata_json FROM relationship_hints WHERE run_id=?"+clause+" ORDER BY hint_type,hint_id",params)]; con.close(); return _page(rows,offset,limit)


def representatives(database_path: str, scope_type: str="global", scope_value: str="", limit: int=10) -> dict[str, Any]:
    rows=_file_rows(database_path)
    if scope_type=="directory": rows=[x for x in rows if x["target_file"].startswith(scope_value)]
    elif scope_type=="file": rows=[x for x in rows if x["target_file"]==scope_value]
    rows.sort(key=lambda x:(-(x.get("modified_candidate",0)*3+x.get("renamed_exact",0)*4+x.get("target_only",0)*2+x.get("source_file_count",0)),x["target_file"]))
    return {"scope_type":scope_type,"scope_value":scope_value,"files":rows[:limit]}


def source_group(database_path: str, identifier: str) -> dict[str, Any]:
    detail=comparison_detail(database_path,identifier)
    if detail.get("status")!="not_found":
        target=detail.get("target_unit_id"); candidates=function_candidates(database_path,target,limit=20) if target else {"rows":[]}
        return {"kind":"comparison","detail":detail,"target":function_detail(database_path,target) if target else None,"target_source":unit_source(database_path,target) if target else None,"candidates":candidates,"candidate_sources":[unit_source(database_path,x["source_unit"]["unit_id"]) for x in candidates["rows"]]}
    hints=relationship_hints(database_path,offset=0,limit=10000)["rows"]; hint=next((x for x in hints if x["hint_id"]==identifier),None)
    return {"status":"not_found","id":identifier} if not hint else {"kind":"relationship_hint","hint":hint,"targets":[function_detail(database_path,x) for x in hint["target_unit_ids"]],"sources":[function_detail(database_path,x) for x in hint["source_unit_ids"]],"target_sources":[unit_source(database_path,x) for x in hint["target_unit_ids"]],"source_sources":[unit_source(database_path,x) for x in hint["source_unit_ids"]]}


def _file_rows(database_path: str) -> list[dict[str, Any]]:
    con=_connect(database_path); run_id=_run_id(con)
    sql="""SELECT t.file,c.raw_status,count(*) FROM comparisons c JOIN units t ON t.unit_id=c.target_unit_id WHERE c.run_id=? GROUP BY t.file,c.raw_status"""
    rows: dict[str,dict[str,Any]]=defaultdict(lambda:{s:0 for s in STATUSES})
    for file,status,count in con.execute(sql,(run_id,)): rows[file]["target_file"]=file; rows[file][status]=count
    for row in rows.values():
        row["total"]=sum(row[s] for s in STATUSES); row["source_file_count"]=len(file_sources(database_path,row["target_file"])["source_files"])
    con.close(); return list(rows.values())


def _insert_units(con: sqlite3.Connection, run_id: str, units: Iterable[dict[str,Any]], side: str, source_role: str, repo: str) -> None:
    con.executemany("INSERT OR REPLACE INTO units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",[(str(x.get("unit_id")),run_id,str(x.get("snapshot_id") or ""),side,source_role,repo,str(x.get("file") or ""),str(Path(str(x.get("file") or "")).parent),str(x.get("name") or ""),int(x.get("line") or 0),int(x.get("end_line") or 0),str(x.get("lang") or ""),int(x.get("sz") or 0),str(x.get("fp") or ""),str(x.get("ast") or "")) for x in units])


def _replace_hints(con: sqlite3.Connection, run_id: str) -> None:
    edges=[{"edge_id":r[0],"target_unit_id":r[1],"source_unit_id":r[2],"source_role":r[3],"source_repo":r[4],"pair_score":r[5],"signals":json.loads(r[6])} for r in con.execute("SELECT edge_id,target_unit_id,source_unit_id,source_role,source_repo,pair_score,signals_json FROM match_edges WHERE run_id=?",(run_id,))]
    target=[{"unit_id":r[0],"file":r[1]} for r in con.execute("SELECT unit_id,file FROM units WHERE run_id=? AND side='target'",(run_id,))]; source=[{"unit_id":r[0],"file":r[1]} for r in con.execute("SELECT unit_id,file FROM units WHERE run_id=? AND side!='target'",(run_id,))]
    con.execute("DELETE FROM relationship_hints WHERE run_id=?",(run_id,)); hints=build_relationship_hints(edges,target,source)
    con.executemany("INSERT INTO relationship_hints VALUES(?,?,?,?,?,?,?,?)",[(x["hint_id"],run_id,x["hint_type"],x["confidence"],_json(x["target_unit_ids"]),_json(x["source_unit_ids"]),_json(x["edge_ids"]),_json(x.get("metadata") or {})) for x in hints])


def _hint(kind: str, target_ids: list[str], source_ids: list[str], edge_ids: list[str], metadata: dict[str,Any]|None=None) -> dict[str,Any]:
    payload={"type":kind,"target":sorted(set(target_ids)),"source":sorted(set(source_ids)),"edges":sorted(set(edge_ids))}
    return {"hint_id":stable_id("hint",payload,16),"hint_type":kind,"confidence":"medium","target_unit_ids":payload["target"],"source_unit_ids":payload["source"],"edge_ids":payload["edges"],"metadata":metadata or {}}


def _connect(path: str) -> sqlite3.Connection:
    con=sqlite3.connect(path); con.row_factory=sqlite3.Row; return con

def _run_id(con: sqlite3.Connection) -> str: return str(con.execute("SELECT run_id FROM runs LIMIT 1").fetchone()[0])
def _scalar(con: sqlite3.Connection, sql: str, *params: Any) -> int: return int(con.execute(sql,params).fetchone()[0])
def _json(value: Any) -> str: return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _uid(unit: dict[str,Any]|None) -> str|None: return str(unit.get("unit_id")) if unit and unit.get("unit_id") else None
def _page(rows: list[Any], offset: int, limit: int) -> dict[str,Any]: return {"total":len(rows),"offset":offset,"limit":limit,"rows":rows[offset:offset+limit]}

def resolve_database(identifier: str) -> str:
    path=Path(identifier)
    if path.is_file(): return str(path)
    for candidate in Path('output').rglob('comparison.sqlite'):
        try:
            con=sqlite3.connect(candidate); row=con.execute('SELECT run_id FROM runs LIMIT 1').fetchone(); con.close()
            if row and row[0]==identifier: return str(candidate)
        except sqlite3.Error: continue
    raise ValueError(f'comparison database/run not found: {identifier}')


def run_metadata(database_path: str) -> dict[str,Any]:
    con=_connect(database_path); row=con.execute('SELECT run_id,schema_version,target_snapshot_json,base_snapshot_json,target_scope_json,base_scope_json FROM runs LIMIT 1').fetchone(); con.close()
    return {'run_id':row[0],'schema_version':row[1],'target_snapshot':json.loads(row[2]),'base_snapshot':json.loads(row[3]),'target_scope':json.loads(row[4]),'base_scope':json.loads(row[5])}


def unit_source(database_path: str, unit_id: str, context_lines: int=5) -> dict[str,Any]:
    con=_connect(database_path); unit=con.execute('SELECT snapshot_id,side,file,line,end_line FROM units WHERE unit_id=?',(unit_id,)).fetchone()
    if not unit: con.close(); return {'status':'not_found','unit_id':unit_id}
    snap_row=con.execute('SELECT snapshot_json FROM source_snapshots WHERE snapshot_id=?',(unit[0],)).fetchone(); con.close(); snap=json.loads(snap_row[0]) if snap_row else None
    if not snap: return {'status':'source_unavailable','unit_id':unit_id,'reason':'snapshot metadata is not stored in run'}
    try:
        lines=read_text(str(snap.get('repo_path') or ''),str(snap.get('commit') or ''),unit[2]).splitlines()
    except Exception:
        return {'status':'not_found','unit_id':unit_id,'file':unit[2]}
    line=max(1,int(unit[3] or 1)); end=max(line,int(unit[4] or line)); lo=max(1,line-context_lines); hi=min(len(lines),end+context_lines)
    return {'status':'ok','unit_id':unit_id,'snapshot_commit':snap.get('commit'),'file':unit[2],'line_start':lo,'line_end':hi,'content':'\n'.join(f'{n}: {lines[n-1]}' for n in range(lo,hi+1))}

def reference_sets(database_path: str) -> dict[str,set[str]]:
    con=_connect(database_path); run_id=_run_id(con)
    out={"comparison_ids":{r[0] for r in con.execute('SELECT comparison_id FROM comparisons WHERE run_id=?',(run_id,))},
         "edge_ids":{r[0] for r in con.execute('SELECT edge_id FROM match_edges WHERE run_id=?',(run_id,))},
         "hint_ids":{r[0] for r in con.execute('SELECT hint_id FROM relationship_hints WHERE run_id=?',(run_id,))},
         "target_files":{r[0] for r in con.execute("SELECT DISTINCT file FROM units WHERE run_id=? AND side='target'",(run_id,))}}
    con.close(); return out
