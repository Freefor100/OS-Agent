from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence import load_evidence
from .parser import EVIDENCE_REF_RE, parse_markdown, slugify, split_h2_sections
from .taxonomy import MODULES
from .validators import validate_case_dir


def compile_report(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    report = validate_case_dir(root)
    report.raise_for_errors()
    site_dir = root / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    identity = parse_markdown(root / "identity.md")
    base_doc = parse_markdown(root / "base.md")
    report_doc = parse_markdown(root / "report.md")
    evidence = load_evidence(root / "evidence.jsonl")
    modules = []
    module_docs = []
    module_paths = sorted((root / "modules").glob("*.md"))
    for path in module_paths:
        doc = parse_markdown(path)
        module_id = str(doc.frontmatter.get("module_id", ""))
        modules.append(
            {
                "module_id": module_id,
                "title": str(
                    doc.frontmatter.get("module_title")
                    or (MODULES[module_id].title if module_id in MODULES else module_id)
                ),
                "status": doc.frontmatter.get("status", ""),
                "originality": doc.frontmatter.get("originality", ""),
                "base_delta": doc.frontmatter.get("base_delta", ""),
                "anchors": doc.code_anchors,
                "markdown": doc.body,
                "evidence_ids": sorted(set(doc.evidence_refs)),
            }
        )
        module_docs.append((doc, modules[-1]))
    sections = [
        {**section, "evidence_ids": sorted(set(EVIDENCE_REF_RE.findall(section["markdown"])))}
        for section in split_h2_sections(report_doc.body)
    ]
    optional = _optional_sections(root)
    references = _build_references(sections, module_docs)
    public_evidence = []
    for evidence_id in sorted(references, key=lambda value: int(value[1:])):
        card = evidence[evidence_id].as_dict()
        raw_ref = card.pop("raw_ref", None)
        if raw_ref and card["kind"] in {"fingerprint_comparison", "search_result"}:
            card["source"] = {**card["source"], "path": ""}
        card["references"] = references[evidence_id]
        public_evidence.append(card)
    report_data = {
        "generated_by": "review_case_report_data_compiler",
        "schema": "report_data.v3",
        "identity": {
            "work_id": identity.frontmatter.get("work_id", ""),
            "display_name": identity.frontmatter.get("display_name", ""),
            "school": identity.frontmatter.get("school", ""),
            "team": identity.frontmatter.get("team", ""),
            "work_name": identity.frontmatter.get("work_name", ""),
        },
        "base": {
            "status": base_doc.frontmatter.get("status", ""),
            "display_name": base_doc.frontmatter.get("selected_base_display_name", ""),
            "target_review_ref": base_doc.frontmatter.get("target_review_ref", ""),
            "target_review_commit": base_doc.frontmatter.get("target_review_commit", ""),
            "target_introduction_commit": base_doc.frontmatter.get("target_introduction_commit", ""),
            "source_ref": base_doc.frontmatter.get("selected_base_ref", ""),
            "source_commit": base_doc.frontmatter.get("selected_base_commit", ""),
            "direction": base_doc.frontmatter.get("direction", ""),
            "confidence": base_doc.frontmatter.get("confidence", ""),
        },
        "sections": sections,
        "modules": modules,
        "evidence": public_evidence,
        "optional_sections": optional,
    }
    out = site_dir / "report_data.json"
    out.write_text(json.dumps(report_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (site_dir / "evidence.jsonl").write_text(
        "".join(json.dumps(card, ensure_ascii=False, sort_keys=True) + "\n" for card in public_evidence),
        encoding="utf-8",
    )
    _write_tags(root, identity, modules, optional)
    return out


def _build_references(sections: list[dict[str, Any]], module_docs: list[tuple[Any, dict]]) -> dict[str, list[dict]]:
    references: dict[str, list[dict]] = {}
    seen: dict[str, set[tuple[str, str, str]]] = {}

    def add(evidence_id: str, *, document: str, section: str, label: str, view: str, anchor: str) -> None:
        key = (document, section, anchor)
        if key in seen.setdefault(evidence_id, set()):
            return
        seen[evidence_id].add(key)
        references.setdefault(evidence_id, []).append(
            {
                "document": document,
                "section": section,
                "label": label,
                "view": view,
                "anchor": anchor,
            }
        )

    for section in sections:
        for evidence_id in section["evidence_ids"]:
            add(
                evidence_id,
                document="report.md",
                section=section["title"],
                label=section["title"],
                view=_view_for_report_section(section["title"]),
                anchor=section["id"],
            )

    for doc, module in module_docs:
        captured: set[str] = set()
        for heading in doc.headings:
            heading_refs = set(EVIDENCE_REF_RE.findall(heading.body))
            captured.update(heading_refs)
            for evidence_id in heading_refs:
                add(
                    evidence_id,
                    document=f"modules/{doc.path.name}",
                    section=heading.title,
                    label=module["title"],
                    view="modules",
                    anchor=f"module-{slugify(module['module_id'])}",
                )
        for evidence_id in set(doc.evidence_refs) - captured:
            add(
                evidence_id,
                document=f"modules/{doc.path.name}",
                section=module["title"],
                label=module["title"],
                view="modules",
                anchor=f"module-{slugify(module['module_id'])}",
            )
    return references


def _view_for_report_section(title: str) -> str:
    if title in {"整体结论", "重点结论"}:
        return "overview"
    if title in {"真实工作量分层", "Base、其他来源与同届传播关系"}:
        return "lineage"
    if title == "内核架构图":
        return "architecture"
    if title in {"文档声明审查", "开发历史与 AI 使用", "测评定向与结果真实性"}:
        return "risk"
    if title == "模块实现细节及 Base 差异":
        return "modules"
    return "evidence"


def _write_tags(root: Path, identity, modules: list[dict], optional: dict[str, bool]) -> None:
    base_path = root / "base.md"
    base = parse_markdown(base_path) if base_path.exists() else None
    summary = {"novel": 0, "adapted": 0, "inherited": 0, "external": 0, "uncertain": 0, "absent": 0}
    for module in modules:
        if module["status"] == "absent":
            summary["absent"] += 1
            continue
        originality = str(module["originality"])
        if originality.startswith("adapted"):
            summary["adapted"] += 1
        elif originality in summary:
            summary[originality] += 1
        else:
            summary["uncertain"] += 1
    risk_tags = [key for key, visible in optional.items() if visible]
    payload = {
        "work_id": identity.frontmatter.get("work_id", ""),
        "display_name": identity.frontmatter.get("display_name", ""),
        "school": identity.frontmatter.get("school", ""),
        "team": identity.frontmatter.get("team", ""),
        "work_name": identity.frontmatter.get("work_name", ""),
        "base": {
            "display_name": base.frontmatter.get("selected_base_display_name", "") if base else "",
            "ref": base.frontmatter.get("selected_base_ref", "") if base else "",
            "commit": base.frontmatter.get("selected_base_commit", "") if base else "",
            "relation": base.frontmatter.get("direction", "") if base else "",
            "confidence": base.frontmatter.get("confidence", "") if base else "",
            "status": base.frontmatter.get("status", "") if base else "",
        },
        "risk_tags": risk_tags,
        "module_summary": summary,
        "public_paths": {"markdown": "report.md", "html": "site/report.html"},
    }
    (root / "tags.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _optional_sections(root: Path) -> dict[str, bool]:
    out = {"doc_claim": False, "cheat": False, "ai": False}
    for name, key in [("doc-claims.md", "doc_claim"), ("cheat.md", "cheat"), ("history-ai.md", "ai")]:
        path = root / "findings" / name
        if path.exists():
            doc = parse_markdown(path)
            out[key] = doc.frontmatter.get("status") == "findings" and str(doc.frontmatter.get("public", "true")).lower() != "false"
    return out
