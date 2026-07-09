from __future__ import annotations

import json
from pathlib import Path

from .evidence import load_evidence
from .evidence_map import write_evidence_map
from .parser import EVIDENCE_REF_RE, parse_markdown, split_h2_sections
from .taxonomy import REQUIRED_MODULES
from .validators import validate_case_dir


def compile_report(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    report = validate_case_dir(root)
    report.raise_for_errors()
    site_dir = root / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    identity = parse_markdown(root / "identity.md")
    report_doc = parse_markdown(root / "report.md")
    evidence, _ = load_evidence(root / "evidence.jsonl")
    modules = []
    for path in sorted((root / "modules").glob("*.md")):
        doc = parse_markdown(path)
        module_id = str(doc.frontmatter.get("module_id", ""))
        modules.append(
            {
                "module_id": module_id,
                "title": REQUIRED_MODULES[module_id].title if module_id in REQUIRED_MODULES else str(doc.frontmatter.get("module_title", module_id)),
                "status": doc.frontmatter.get("status", ""),
                "originality": doc.frontmatter.get("originality", ""),
                "base_delta": doc.frontmatter.get("base_delta", ""),
                "anchors": doc.code_anchors,
                "markdown": doc.body,
                "evidence_ids": sorted(set(doc.evidence_refs)),
            }
        )
    sections = [
        {**section, "evidence_ids": sorted(set(EVIDENCE_REF_RE.findall(section["markdown"])))} for section in split_h2_sections(report_doc.body)
    ]
    evidence_map = _load_evidence_map(root)
    optional = _optional_sections(root)
    report_data = {
        "generated_by": "review_case_report_data_compiler",
        "schema": "report_data.v1",
        "identity": {
            "work_id": identity.frontmatter.get("work_id", ""),
            "display_name": identity.frontmatter.get("display_name", ""),
            "school": identity.frontmatter.get("school", ""),
            "team": identity.frontmatter.get("team", ""),
            "work_name": identity.frontmatter.get("work_name", ""),
        },
        "sections": sections,
        "modules": modules,
        "evidence": [card.as_dict() for card in evidence.values()],
        "evidence_graph": {
            "markdown_claims": _markdown_claims(sections, modules),
            "evidence_map": evidence_map,
        },
        "optional_sections": optional,
    }
    out = site_dir / "report_data.json"
    out.write_text(json.dumps(report_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _optional_sections(root: Path) -> dict[str, bool]:
    out = {"cheat": False, "ai": False, "prompt_injection": False}
    for name, key in [("cheat.md", "cheat"), ("history-ai.md", "ai")]:
        path = root / "findings" / name
        if path.exists():
            doc = parse_markdown(path)
            out[key] = doc.frontmatter.get("status") == "findings" and str(doc.frontmatter.get("public", "true")).lower() != "false"
    if out["cheat"]:
        cheat = parse_markdown(root / "findings" / "cheat.md")
        out["prompt_injection"] = "Prompt Injection" in cheat.body
    return out


def _markdown_claims(sections: list[dict], modules: list[dict]) -> dict[str, object]:
    claims = []
    for section in sections:
        claims.append(
            {
                "claim_id": f"section:{section['id']}",
                "kind": "section",
                "title": section["title"],
                "evidence_ids": section.get("evidence_ids", []),
            }
        )
    for module in modules:
        claims.append(
            {
                "claim_id": f"module:{module['module_id']}",
                "kind": "module",
                "title": module["title"],
                "evidence_ids": module.get("evidence_ids", []),
            }
        )
    evidence_to_claims: dict[str, list[str]] = {}
    for claim in claims:
        for evidence_id in claim["evidence_ids"]:
            evidence_to_claims.setdefault(evidence_id, []).append(claim["claim_id"])
    return {"claims": claims, "evidence_to_claims": evidence_to_claims}


def _load_evidence_map(root: Path) -> dict:
    path = root / "case_state" / "evidence_map.json"
    if not path.exists():
        write_evidence_map(root)
    return json.loads(path.read_text(encoding="utf-8"))
