from __future__ import annotations

import json
from pathlib import Path

from .evidence import EvidenceCard, load_evidence
from .taxonomy import REQUIRED_MODULES

CONCLUSION_DOMAINS = {
    "base_identity",
    "source_lineage",
    "same_year_direction",
    "plagiarism_direction",
    "plagiarism_method",
    "work_amount",
    "module_implementation",
    "base_delta",
    "external_dependency",
    "external_adaptation",
    "doc_claim",
    "module_design",
    "ai_usage",
    "development_history",
    "cheat_risk",
    "prompt_injection",
    "architecture",
    "scope_boundary",
}

BASE_DOMAINS = {
    "base_identity",
    "source_lineage",
    "same_year_direction",
    "plagiarism_direction",
    "plagiarism_method",
    "base_delta",
    "external_dependency",
    "external_adaptation",
    "development_history",
    "scope_boundary",
}


def write_evidence_map(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    evidence, report = load_evidence(root / "evidence.jsonl")
    report.raise_for_errors()
    payload = map_evidence(evidence)
    out_dir = root / "case_state"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "evidence_map.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def map_evidence(evidence: dict[str, EvidenceCard]) -> dict:
    entries = []
    by_domain: dict[str, list[str]] = {domain: [] for domain in sorted(CONCLUSION_DOMAINS)}
    by_agent: dict[str, list[str]] = {}
    by_module: dict[str, list[str]] = {module_id: [] for module_id in REQUIRED_MODULES}
    map_by_id: dict[str, dict] = {}
    for card in evidence.values():
        domains = sorted(_infer_domains(card))
        modules = sorted(_infer_modules(card))
        agents = sorted(_infer_agents(card, set(domains), set(modules)))
        entry = {
            "evidence_id": card.evidence_id,
            "kind": card.kind,
            "supports": card.supports,
            "conclusion_domains": domains,
            "agents": agents,
            "modules": modules,
            "reason": _map_reason(card, domains, modules),
        }
        entries.append(entry)
        map_by_id[card.evidence_id] = entry
        for domain in domains:
            by_domain.setdefault(domain, []).append(card.evidence_id)
        for agent in agents:
            by_agent.setdefault(agent, []).append(card.evidence_id)
        for module_id in modules:
            by_module.setdefault(module_id, []).append(card.evidence_id)
    return {
        "schema": "review_case.evidence_map.v1",
        "evidence_map": entries,
        "domains": {key: value for key, value in by_domain.items() if value},
        "agents": by_agent,
        "modules": {key: value for key, value in by_module.items() if value},
        "map_by_id": map_by_id,
    }


def _infer_domains(card: EvidenceCard) -> set[str]:
    domains: set[str] = set()
    text = f"{card.kind} {' '.join(card.supports)} {card.title} {card.excerpt} {card.canonical_path}".lower()
    if card.kind == "base_delta_summary":
        domains.update({"base_identity", "source_lineage", "base_delta", "work_amount", "plagiarism_direction", "same_year_direction"})
    elif card.kind == "git_history":
        domains.update({"development_history", "work_amount", "plagiarism_direction", "plagiarism_method", "same_year_direction"})
    elif card.kind == "doc_claim":
        domains.update({"doc_claim", "base_identity", "external_dependency", "module_design", "ai_usage", "development_history"})
    elif card.kind == "source_span":
        domains.update({"module_implementation", "work_amount", "architecture"})
    elif card.kind == "negative_search":
        domains.update({"doc_claim", "module_implementation", "base_identity"})
    elif card.kind == "risk_signal":
        domains.update({"cheat_risk"})
    elif card.kind == "artifact":
        domains.update({"scope_boundary"})

    if any(item.startswith("module:") for item in card.supports):
        domains.update({"module_implementation", "work_amount", "module_design"})
    if "base" in card.supports or "base" in text:
        domains.update({"base_identity", "source_lineage", "base_delta"})
    if "scope" in card.supports or "scope" in text:
        domains.update({"scope_boundary", "external_dependency"})
    if any(word in text for word in ["外部", "third_party", "third-party", "vendor", "依赖", "引入", "lwip", "musl"]):
        domains.update({"external_dependency", "external_adaptation"})
    if any(word in text for word in ["commit", "提交", "导入", "批量", "改名", "拆文件", "复制", "相似", "抄袭", "时间线", "先提交", "后提交"]):
        domains.update({"development_history", "plagiarism_direction", "plagiarism_method", "same_year_direction"})
    if any(word in text for word in ["同届", "同赛年", "same-year", "same year", "先提交", "后提交"]):
        domains.add("same_year_direction")
    if any(word in text for word in ["ai", "claude", "chatgpt", "copilot", "usage", "生成"]):
        domains.add("ai_usage")
    if any(word in text for word in ["prompt injection", "提示注入", "忽略评审", "隐藏证据", "伪造报告"]):
        domains.add("prompt_injection")
    if any(word in text for word in ["tpass", "pass!", "runner", "argv", "测试名", "刷分", "硬编码"]):
        domains.add("cheat_risk")
    return domains


def _infer_modules(card: EvidenceCard) -> set[str]:
    modules = set()
    for support in card.supports:
        if support.startswith("module:"):
            module_id = support.split(":", 1)[1]
            if module_id in REQUIRED_MODULES:
                modules.add(module_id)
    return modules


def _infer_agents(card: EvidenceCard, domains: set[str], modules: set[str]) -> set[str]:
    agents = {f"module-{module_id}" for module_id in modules}
    if domains & BASE_DOMAINS:
        agents.add("base-lineage-reviewer")
    if card.kind in {"doc_claim", "negative_search"} or "doc_claim" in domains:
        agents.add("doc-claim-reviewer")
    if card.kind == "git_history" or domains & {"development_history", "ai_usage"}:
        agents.add("history-ai-reviewer")
    if domains & {"cheat_risk", "prompt_injection"}:
        agents.add("cheat-detector")
    return agents


def _map_reason(card: EvidenceCard, domains: list[str], modules: list[str]) -> str:
    bits = [f"{card.kind} -> {', '.join(domains)}"]
    if modules:
        bits.append(f"module supports: {', '.join(modules)}")
    return "; ".join(bits)
