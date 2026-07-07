#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.judge_report import MODULE_IDS, validate_judge_report
from core.git_source import blob_sizes, list_tree
from core.kernel_tree import ANALYSIS_ORDER_V2, ROOT_NODES_V2, node_scope, node_title_zh

try:
    from core.metadata import MetadataManager
except Exception:
    MetadataManager = None


IMPLEMENTATION_LABELS = {
    "full": "完整",
    "partial": "部分",
    "minimal": "最低限度",
    "absent": "未发现实现",
    "not_applicable": "不适用",
    "unknown": "待确认",
}
ORIGINALITY_LABELS = {
    "novel": "独立实现",
    "adapted_major": "实质重写",
    "adapted_minor": "增量修改",
    "inherited": "主体继承",
    "external_dep": "外部依赖",
    "not_applicable": "不适用",
    "unknown": "待确认",
}
CLAIM_LABELS = {
    "lineage": "来源关系",
    "difference": "实现差异",
    "independent_work": "独立工作",
    "implementation": "实现判断",
    "absence": "缺失判断",
    "risk": "复核风险",
}
EVIDENCE_KIND_LABELS = {
    "source": "源码证据",
    "documentation": "文档说明",
    "function_definition": "函数定义",
    "type_definition": "数据结构",
    "macro_definition": "宏定义",
    "constant_definition": "常量定义",
    "config_entry": "配置项",
    "linker_symbol": "链接脚本",
    "assembly_label": "汇编入口",
    "source_span": "源码片段",
    "lsp_definition": "定义定位",
    "lsp_reference": "引用关系",
    "call_edge": "调用关系",
    "lsp_call_graph": "调用链",
    "git_history": "Git 历史",
    "formal_search": "正式检索",
    "scope_manifest": "代码范围",
    "negative_search": "负向搜索",
    "binary_artifact": "二进制文件",
    "file_artifact": "文件证据",
}


def render(report: dict[str, Any], base_decision: dict[str, Any] | None = None) -> str:
    errors = validate_judge_report(report, require_complete=False)
    if errors:
        import sys
        print(f"Warning: render validation issues ({len(errors)}), proceeding anyway", file=sys.stderr)
    data = _build_view_model(report, base_decision or {})
    return _dist_index().replace("__REPORT_DATA__", _json_for_script(data))


def render_to_file(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(report, _read_base_decision(output.parent)), encoding="utf-8")
    _copy_dist_assets(output.parent)


def _read_base_decision(report_dir: Path) -> dict[str, Any]:
    path = report_dir / "base_decision.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _build_view_model(report: dict[str, Any], base_decision: dict[str, Any]) -> dict[str, Any]:
    evidence = _read_evidence(report.get("evidence_store") or report.get("evidence_store",""))
    claims = report.get("claims") or []
    module_reviews = report.get("module_reviews") or []
    used_evidence_ids = _used_evidence_ids(claims, module_reviews)
    evidence_labels = {eid: f"E{index:03d}" for index, eid in enumerate(used_evidence_ids, 1)}
    evidence_rows = {
        eid: _evidence_view(evidence[eid], evidence_labels[eid], report)
        for eid in used_evidence_ids
        if eid in evidence
    }
    return {
        "report": report,
        "taxonomy": _taxonomy_view(),
        "labels": {
            "implementation": IMPLEMENTATION_LABELS,
            "originality": ORIGINALITY_LABELS,
            "claim": CLAIM_LABELS,
            "evidenceKind": EVIDENCE_KIND_LABELS,
        },
        "projectMeta": _project_meta(report, base_decision),
        "projectProfile": _project_profile(report),
        "evidenceLabels": evidence_labels,
        "evidence": evidence_rows,
    }


def _taxonomy_view() -> dict[str, Any]:
    nodes = {}
    for node_id in ANALYSIS_ORDER_V2:
        nodes[node_id] = {"id": node_id, "title": node_title_zh(node_id), "scope": node_scope(node_id)}
    modules = []
    for module_id in MODULE_IDS:
        children = ROOT_NODES_V2[module_id]
        node_ids = [module_id] if not children else [f"{module_id}.{child}" for child in children]
        modules.append({
            "id": module_id,
            "title": node_title_zh(module_id),
            "nodeIds": node_ids,
            "scope": node_scope(module_id),
        })
    return {"modules": modules, "nodes": nodes}


def _used_evidence_ids(claims: list[dict[str, Any]], module_reviews: list[dict[str, Any]]) -> list[str]:
    used: list[str] = []
    for claim in claims:
        for evidence_id in claim.get("evidence_ids") or []:
            if evidence_id not in used:
                used.append(evidence_id)
    for review in module_reviews:
        for chain in review.get("key_chains") or []:
            if isinstance(chain, dict):
                for evidence_id in chain.get("evidence_ids") or []:
                    if evidence_id not in used:
                        used.append(evidence_id)
    return used


def _evidence_view(row: dict[str, Any], label: str, report: dict[str, Any]) -> dict[str, Any]:
    work_obj = report.get("work") or {}; ref_obj = report.get("reference") or {}
    if not isinstance(work_obj, dict): work_obj = {}
    if not isinstance(ref_obj, dict): ref_obj = {}
    target_commit = (work_obj.get("snapshot") or {}).get("commit")
    reference_commit = (ref_obj.get("snapshot") or {}).get("commit")
    commit = (row.get("metadata") or {}).get("snapshot_commit")
    if commit == target_commit:
        owner = work_obj.get("display_name","作品")
    elif commit == reference_commit:
        owner = ref_obj.get("display_name","参考作品")
    else:
        owner = "检索与审计流程"
    return {
        "id": row.get("evidence_id"),
        "label": label,
        "category": _evidence_category(row),
        "kindLabel": EVIDENCE_KIND_LABELS.get(row.get("kind"), row.get("kind")),
        "owner": owner,
        "commit": commit,
        "path": row.get("path"),
        "lineStart": row.get("line_start"),
        "lineEnd": row.get("line_end"),
        "title": row.get("label") or row.get("path") or row.get("query") or "结构化证据",
        "excerpt": row.get("excerpt") or _evidence_summary(row),
        "verified": bool(row.get("verified")),
    }


def _evidence_summary(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") or {}
    if row.get("kind") == "negative_search":
        return f"完整覆盖：{metadata.get('coverage_complete')}；扫描文件：{metadata.get('scanned_files')}；匹配数：{metadata.get('matches')}"
    if row.get("kind") == "formal_search":
        return f"正式检索排名：{metadata.get('rank')}；候选：{metadata.get('candidate_repo')}@{metadata.get('candidate_commit')}"
    return str(row.get("query") or row.get("label") or "已验证结构化证据")


def _evidence_category(row: dict[str, Any]) -> str:
    kind = row.get("kind")
    if kind == "documentation":
        return "文档证据"
    if kind in {"formal_search", "negative_search", "scope_manifest", "git_history"}:
        return "审计证据"
    if kind in {"call_edge", "lsp_call_graph", "lsp_reference"}:
        return "链路证据"
    return "源码证据"


def _read_evidence(path: object) -> dict[str, dict[str, Any]]:
    out = {}
    if not isinstance(path, str) or not path or len(path) > 500:
        return out
    try:
        evidence_path = Path(path)
    except (OSError, ValueError):
        return out
    if not evidence_path.is_file():
        return out
    for line in evidence_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
            out[row["evidence_id"]] = row
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return out


def _project_meta(report: dict[str, Any], base_decision: dict[str, Any]) -> list[dict[str, str]]:
    work = report.get("work") or {}
    reference = report.get("reference") or {}
    if not isinstance(work, dict): work = {}
    if not isinstance(reference, dict): reference = {}
    work_snapshot = work.get("snapshot") or {}
    reference_snapshot = reference.get("snapshot") or {}
    work_meta = _repo_metadata(str(work_snapshot.get("repo") or ""))
    ref_meta = _repo_metadata(str(reference_snapshot.get("repo") or ""))
    base = f"{reference_snapshot.get('repo') or '无'}@{_display_ref(reference_snapshot)}" if reference_snapshot else "无可靠 Base"
    base_year = _base_year(report, base_decision, ref_meta)
    rows = [
        {"label": "作品队伍", "value": _team_label(work_meta, work.get("display_name") or work_snapshot.get("repo") or "")},
        {"label": "年份", "value": str(work_meta.get("year") or _year_from_display(work.get("display_name") or ""))},
        {"label": "分析分支", "value": _display_ref(work_snapshot)},
        {"label": "推测 Base", "value": base},
        {"label": "Base 年份", "value": base_year},
    ]
    if ref_meta:
        rows.append({"label": "Base 队伍", "value": _team_label(ref_meta, reference.get("display_name") or reference_snapshot.get("repo") or "")})
    return rows


def _base_year(report: dict[str, Any], base_decision: dict[str, Any], ref_meta: dict[str, Any]) -> str:
    if ref_meta.get("year"):
        return str(ref_meta["year"])

    decision = base_decision.get("decision") if isinstance(base_decision.get("decision"), dict) else {}
    candidates = [
        decision.get("base_year"),
        (decision.get("decision_factors") or {}).get("base_year") if isinstance(decision.get("decision_factors"), dict) else None,
        (decision.get("primary_base") or {}).get("year") if isinstance(decision.get("primary_base"), dict) else None,
        (decision.get("selected_formal_candidate") or {}).get("year") if isinstance(decision.get("selected_formal_candidate"), dict) else None,
        (decision.get("evidence") or {}).get("original_year") if isinstance(decision.get("evidence"), dict) else None,
    ]
    for value in candidates:
        year = _coerce_year(value)
        if year:
            return year

    text_fields = [
        decision.get("base_selection_reason"),
        decision.get("year_direction_note"),
        decision.get("year_relation"),
        (decision.get("decision_factors") or {}).get("reason") if isinstance(decision.get("decision_factors"), dict) else None,
        (report.get("overall_assessment") or {}).get("base_selection_reason") if isinstance(report.get("overall_assessment"), dict) else None,
        (report.get("overall_assessment") or {}).get("source_relation") if isinstance(report.get("overall_assessment"), dict) else None,
    ]
    for value in text_fields:
        year = _year_from_base_text(str(value or ""))
        if year:
            return year

    reference = report.get("reference") or {}
    if not isinstance(reference, dict): reference = {}
    reference_snapshot = reference.get("snapshot") or {}
    for value in (reference_snapshot.get("repo"), reference.get("display_name")):
        year = _coerce_year(value)
        if year:
            return year
    return "未知"


def _coerce_year(value: Any) -> str:
    if isinstance(value, int) and 2000 <= value <= 2099:
        return str(value)
    return _year_from_display(str(value or ""))


def _year_from_base_text(text: str) -> str:
    if not text:
        return ""
    explicit = re.search(r"(?:Base|base|基准|参考|来源|上游|原始|选择)[^。；;，,\n]{0,40}?(20\d{2})", text)
    if explicit:
        return explicit.group(1)
    relation = re.search(r"(20\d{2})\s*(?:_to_|至|到|->|→)\s*20\d{2}", text)
    if relation:
        return relation.group(1)
    years = re.findall(r"20\d{2}", text)
    unique = []
    for year in years:
        if year not in unique:
            unique.append(year)
    if len(unique) == 1:
        return unique[0]
    return ""


def _repo_metadata(repo: str) -> dict[str, Any]:
    if not repo or MetadataManager is None:
        return {}
    try:
        return MetadataManager().lookup_by_repo_name(repo) or {}
    except Exception:
        return {}


def _team_label(meta: dict[str, Any], fallback: str) -> str:
    team = meta.get("team") or ""
    school = meta.get("school") or ""
    if team and school:
        return f"{team}（{school}）"
    return team or fallback


def _display_ref(snapshot: dict[str, Any]) -> str:
    aliases = [str(x) for x in snapshot.get("ref_aliases") or [] if x and x != "origin/HEAD"]
    local = [x for x in aliases if "/" not in x]
    if local:
        return local[0]
    if aliases:
        return aliases[0].removeprefix("origin/")
    return str(snapshot.get("canonical_branch") or snapshot.get("display_ref") or snapshot.get("commit") or "")[:12]


def _year_from_display(value: str) -> str:
    import re
    match = re.search(r"(20\d{2})", value)
    return match.group(1) if match else ""


def _project_profile(report: dict[str, Any]) -> dict[str, Any]:
    work_obj = report.get("work") or {}
    if not isinstance(work_obj, dict): work_obj = {}
    snapshot = work_obj.get("snapshot") or {}
    repo_path = str(snapshot.get("repo_path") or "")
    commit = str(snapshot.get("commit") or "")
    if not repo_path or not commit:
        return {"languages": [], "directories": [], "totalFiles": 0, "totalBytes": 0}
    language_stats: dict[str, dict[str, int]] = {}
    directory_stats: dict[str, dict[str, int]] = {}
    directory_tree: dict[str, Any] = {"name": ".", "path": ".", "files": 0, "bytes": 0, "children": {}}
    total_bytes = 0
    try:
        entries = list_tree(repo_path, commit)
    except Exception:
        return {"languages": [], "directories": [], "totalFiles": 0, "totalBytes": 0}
    sizes = blob_sizes(repo_path, [entry for entry in entries if entry.kind == "blob"])
    for entry in entries:
        if entry.kind != "blob":
            continue
        rel = entry.path
        size = sizes.get(entry.object_id, 0)
        total_bytes += size
        lang = _language_for(Path(rel).name)
        language_stats.setdefault(lang, {"files": 0, "bytes": 0})
        language_stats[lang]["files"] += 1
        language_stats[lang]["bytes"] += size
        top = rel.split("/", 1)[0] if "/" in rel else "根目录文件"
        directory_stats.setdefault(top, {"files": 0, "bytes": 0})
        directory_stats[top]["files"] += 1
        directory_stats[top]["bytes"] += size
        _add_tree_file(directory_tree, rel, size)
    total_files = sum(row["files"] for row in language_stats.values())
    languages = sorted(
        [{"name": name, **stats, "percent": stats["files"] / total_files * 100 if total_files else 0}
         for name, stats in language_stats.items()],
        key=lambda row: (-row["files"], -row["bytes"]),
    )
    directories = sorted(
        [{"path": path, **stats, "percent": stats["bytes"] / total_bytes * 100 if total_bytes else 0}
         for path, stats in directory_stats.items()],
        key=lambda row: -row["bytes"],
    )
    return {
        "languages": languages[:8],
        "directories": directories[:12],
        "directoryTree": _finalize_tree(directory_tree),
        "totalFiles": total_files,
        "totalBytes": total_bytes,
    }


def _add_tree_file(root: dict[str, Any], rel: str, size: int) -> None:
    parts = rel.split("/")
    node = root
    node["files"] += 1
    node["bytes"] += size
    current = []
    for part in parts[:-1]:
        current.append(part)
        children = node.setdefault("children", {})
        child = children.setdefault(part, {
            "name": part,
            "path": "/".join(current),
            "files": 0,
            "bytes": 0,
            "children": {},
        })
        child["files"] += 1
        child["bytes"] += size
        node = child


def _finalize_tree(node: dict[str, Any]) -> dict[str, Any]:
    children = [_finalize_tree(child) for child in (node.get("children") or {}).values()]
    children.sort(key=lambda row: (-int(row.get("bytes") or 0), str(row.get("name") or "")))
    return {
        "name": node.get("name"),
        "path": node.get("path"),
        "files": node.get("files") or 0,
        "bytes": node.get("bytes") or 0,
        "children": children,
    }


def _language_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".c", ".h"}:
        return "C/C 头文件"
    if suffix in {".s", ".asm"}:
        return "汇编"
    if suffix == ".ld":
        return "链接脚本"
    if suffix == ".mk" or filename == "Makefile":
        return "Makefile"
    if suffix == ".rs":
        return "Rust"
    if suffix == ".py":
        return "Python"
    if suffix in {".md", ".txt"}:
        return "文档"
    if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".bin", ".elf", ".img", ".o", ".a"}:
        return "工件/资源"
    if suffix in {".json", ".toml", ".yaml", ".yml"}:
        return "配置"
    return "其他"


def _dist_index() -> str:
    index = ROOT / "web_report" / "dist" / "index.html"
    if not index.is_file():
        raise FileNotFoundError(
            "web_report/dist/index.html not found. Run `cd web_report && npm install && npm run build` first."
        )
    return index.read_text(encoding="utf-8")


def _copy_dist_assets(output_dir: Path) -> None:
    src = ROOT / "web_report" / "dist" / "assets"
    if not src.is_dir():
        return
    dst = output_dir / "assets"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: judge_report.py <report.json> <report.html>")
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    output = Path(sys.argv[2])
    render_to_file(report, output)


if __name__ == "__main__":
    main()
