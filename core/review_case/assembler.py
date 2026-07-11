from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import ReviewCaseValidationError, ValidationReport
from .evidence import EvidenceCard, load_evidence
from .parser import parse_markdown
from .taxonomy import NODE_INDEX, REQUIRED_MODULES
from .validators import validate_case_dir


def assemble_report(case_dir: str | Path) -> ValidationReport:
    root = Path(case_dir)
    pre_report = validate_case_dir(root)
    # Allow report.md to be absent during pre-assembly.
    pre_report.issues = [issue for issue in pre_report.issues if not (issue.code.startswith("optional_section") or str(issue.path).endswith("report.md"))]
    if not pre_report.ok:
        return pre_report
    report = ValidationReport()
    identity = parse_markdown(root / "identity.md")
    base = parse_markdown(root / "base.md")
    evidence, evidence_report = load_evidence(root / "evidence.jsonl")
    report.extend(evidence_report)
    display_name = str(identity.frontmatter.get("display_name", "")).strip() or str(identity.frontmatter.get("work_id", "")).strip()
    modules = [parse_markdown(path) for path in (root / "modules").glob("*.md")]
    module_order = {module_id: index for index, module_id in enumerate(REQUIRED_MODULES)}
    modules.sort(key=lambda doc: module_order.get(str(doc.frontmatter.get("module_id", "")), len(module_order)))
    findings = {path.stem: parse_markdown(path) for path in sorted((root / "findings").glob("*.md"))}
    lines: list[str] = [
        "---",
        "contract: assembled_report",
        f"work_id: {identity.frontmatter.get('work_id', '')}",
        "---",
        "",
        f"# {display_name} 评审报告",
        "",
        "## 整体结论",
        "",
        _one_line_summary(base, modules, findings),
        "",
        "## 重点结论",
        "",
        _key_findings_summary(base, modules, findings),
        "",
        "## Base 与来源关系",
        "",
        _without_h1(base.body),
        "",
        "## 真实工作量账本",
        "",
        _module_ledger(modules),
        "",
        "## 内核架构图",
        "",
        _architecture_mermaid(modules),
        "",
    ]
    if _finding_public(findings.get("doc-claims")):
        lines.extend(["## 文档声明审查", "", _without_h1(findings["doc-claims"].body), ""])
    if _finding_public(findings.get("history-ai")):
        lines.extend(["## 开发历史与 AI 使用", "", _without_h1(findings["history-ai"].body), ""])
    cheat = findings.get("cheat")
    if _finding_public(cheat):
        lines.extend(["## 作弊、刷分与提示注入风险", "", _without_h1(cheat.body), ""])
    lines.extend(["## 模块实现与 Base 差异", ""])
    for module in modules:
        title = str(module.frontmatter.get("module_title") or REQUIRED_MODULES.get(str(module.frontmatter.get("module_id", "")), None).title if module.frontmatter.get("module_id") in REQUIRED_MODULES else module.headings[0].title)
        lines.extend([f"### {title}", "", _without_h1(module.body), ""])
    lines.extend(["## 证据索引", "", _evidence_index(evidence), ""])
    report_md = "\n".join(lines).rstrip() + "\n"
    (root / "report.md").write_text(report_md, encoding="utf-8")
    (root / "tags.json").write_text(json.dumps(_tags(identity, base, modules, findings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    post_report = validate_case_dir(root)
    if not post_report.ok:
        return post_report
    return report


def _without_h1(markdown: str) -> str:
    lines = markdown.splitlines()
    out = []
    for line in lines:
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            out.append(f"**{line[3:].strip()}**")
            continue
        if line.startswith("### "):
            out.append(f"**{line[4:].strip()}**")
            continue
        out.append(line)
    return "\n".join(out).strip()


def _finding_public(doc) -> bool:
    if doc is None:
        return False
    if doc.frontmatter.get("status") != "findings":
        return False
    if str(doc.frontmatter.get("public", "true")).lower() == "false":
        return False
    return True


def _one_line_summary(base, modules, findings: dict[str, Any]) -> str:
    implemented = sum(1 for module in modules if module.frontmatter.get("status") in {"implemented", "partial"})
    novel = sum(1 for module in modules if str(module.frontmatter.get("originality", "")).startswith("novel"))
    risk_bits = []
    if _finding_public(findings.get("doc-claims")):
        risk_bits.append("文档声明存在需复核项")
    if _finding_public(findings.get("history-ai")):
        risk_bits.append("开发历史或 AI 使用存在需复核项")
    if _finding_public(findings.get("cheat")):
        risk_bits.append("测试/提示注入风险存在需复核项")
    risk = "；".join(risk_bits) if risk_bits else "未进入公开风险章节"
    refs = sorted(set(base.evidence_refs))
    chip = f" [@{refs[0]}]" if refs else ""
    return f"Base 方向为 `{base.frontmatter.get('direction', 'uncertain')}`，{implemented} 个核心模块有实现或部分实现，{novel} 个模块标为主要原创；{risk}。{chip}"


def _key_findings_summary(base, modules, findings: dict[str, Any]) -> str:
    refs = sorted(set(base.evidence_refs))
    chip = f" [@{refs[0]}]" if refs else ""
    implemented = sum(1 for module in modules if module.frontmatter.get("status") in {"implemented", "partial"})
    absent = sum(1 for module in modules if module.frontmatter.get("status") == "absent")
    adapted = sum(1 for module in modules if str(module.frontmatter.get("originality", "")).startswith("adapted"))
    inherited = sum(1 for module in modules if module.frontmatter.get("originality") == "inherited")
    risk_lines = []
    risk_lines.append(f"- Base 与来源：`{base.frontmatter.get('direction', 'uncertain')}`，置信度 `{base.frontmatter.get('confidence', 'low')}`。{chip}")
    risk_lines.append(f"- 真实工作量分层：{implemented} 个功能模块进入实现或部分实现，{adapted} 个模块为适配型增量，{inherited} 个模块以继承为主，{absent} 个模块缺失。{chip}")
    if _finding_public(findings.get("doc-claims")):
        risk_lines.append(f"- 文档声明：存在公开 finding，详见“文档声明审查”。{_doc_chip(findings.get('doc-claims'))}")
    else:
        risk_lines.append("- 文档声明：无公开结论。")
    if _finding_public(findings.get("history-ai")):
        risk_lines.append(f"- 开发历史与 AI 使用：存在公开 finding，详见“开发历史与 AI 使用”。{_doc_chip(findings.get('history-ai'))}")
    else:
        risk_lines.append("- 开发历史与 AI 使用：无公开结论。")
    if _finding_public(findings.get("cheat")):
        risk_lines.append(f"- 作弊、刷分与提示注入：存在公开 finding，详见风险章节。{_doc_chip(findings.get('cheat'))}")
    else:
        risk_lines.append("- 作弊、刷分与提示注入：无公开结论。")
    return "\n".join(risk_lines)


def _doc_chip(doc) -> str:
    if doc is None:
        return ""
    refs = sorted(set(doc.evidence_refs))
    return f" [@{refs[0]}]" if refs else ""


def _module_ledger(modules) -> str:
    lines = ["| 模块 | 实现状态 | 原创性 | Base 差异 |", "|---|---|---|---|"]
    for module in modules:
        module_id = str(module.frontmatter.get("module_id", ""))
        title = REQUIRED_MODULES[module_id].title if module_id in REQUIRED_MODULES else module_id
        lines.append(f"| {title} | `{module.frontmatter.get('status', '')}` | `{module.frontmatter.get('originality', '')}` | `{module.frontmatter.get('base_delta', '')}` |")
    return "\n".join(lines)


def _architecture_mermaid(modules) -> str:
    status_by_id = {str(module.frontmatter.get("module_id", "")): str(module.frontmatter.get("status", "")) for module in modules}

    def label(module_id: str, short: str) -> str:
        status = status_by_id.get(module_id, "unknown")
        return f'{module_id.replace("-", "_")}["{short}<br/>{status}"]'

    lines = [
        "```mermaid",
        "graph LR",
        f"  {label('build-config', '构建与配置')}",
        f"  {label('architecture-boot', '体系结构与启动')}",
        f"  {label('process-management', '进程/线程/调度')}",
        f"  {label('memory-management', '内存管理')}",
        f"  {label('file-system', '文件系统与 I/O')}",
        f"  {label('device-driver', '设备与平台驱动')}",
        f"  {label('network-stack', '网络栈')}",
        f"  {label('synchronization', '同步机制')}",
        f"  {label('user-abi-compat', '用户 ABI 与兼容')}",
        f"  {label('kernel-services', '内核服务')}",
        f"  {label('security-isolation', '安全与隔离')}",
        f"  {label('observability-debug', '调试与可观测性')}",
        "  build_config --> architecture_boot",
        "  architecture_boot --> process_management",
        "  architecture_boot --> memory_management",
        "  architecture_boot --> device_driver",
        "  process_management --> synchronization",
        "  process_management --> user_abi_compat",
        "  memory_management --> process_management",
        "  memory_management --> file_system",
        "  memory_management --> security_isolation",
        "  file_system --> device_driver",
        "  network_stack --> device_driver",
        "  network_stack --> synchronization",
        "  kernel_services --> synchronization",
        "  kernel_services --> architecture_boot",
        "  observability_debug -.观测.-> architecture_boot",
        "  observability_debug -.观测.-> process_management",
    ]
    for module in modules:
        module_id = str(module.frontmatter.get("module_id", ""))
        module_node = module_id.replace("-", "_")
        selected = 0
        for heading in module.headings:
            if heading.level != 3:
                continue
            node_id = heading.title.split("：", 1)[0].strip().strip("`")
            node_item = NODE_INDEX.get(node_id)
            if not node_item or node_item[0] != module_id:
                continue
            detail_node = "n_" + node_id.replace("-", "_")
            node_title = node_item[1].title.replace('"', "'")
            lines.append(f'  {detail_node}["{node_title}"]')
            lines.append(f"  {module_node} --> {detail_node}")
            selected += 1
            if selected == 2:
                break
    lines.append("```")
    return "\n".join(lines)


def _evidence_index(evidence: dict[str, EvidenceCard]) -> str:
    lines = ["| ID | 类型 | 标题 | 位置 | 置信度 |", "|---|---|---|---|---|"]
    for card in evidence.values():
        loc = f"{card.canonical_path} {card.locator}".strip()
        lines.append(f"| [@{card.evidence_id}] | {card.kind} | {card.title} | {loc} | {card.confidence} |")
    return "\n".join(lines)


def _tags(identity, base, modules, findings: dict[str, Any]) -> dict[str, Any]:
    risk_tags: list[str] = []
    if _finding_public(findings.get("doc-claims")):
        risk_tags.append("doc_claim_mismatch")
    if _finding_public(findings.get("history-ai")):
        risk_tags.append("history_ai_signal")
    if _finding_public(findings.get("cheat")):
        risk_tags.append("cheat_or_prompt_injection_signal")
    summary = {"novel": 0, "adapted": 0, "inherited": 0, "absent": 0}
    for module in modules:
        originality = str(module.frontmatter.get("originality", ""))
        status = str(module.frontmatter.get("status", ""))
        if status == "absent":
            summary["absent"] += 1
        elif originality == "novel":
            summary["novel"] += 1
        elif originality.startswith("adapted"):
            summary["adapted"] += 1
        elif originality == "inherited":
            summary["inherited"] += 1
    return {
        "work_id": identity.frontmatter.get("work_id", ""),
        "display_name": identity.frontmatter.get("display_name", ""),
        "school": identity.frontmatter.get("school", ""),
        "team": identity.frontmatter.get("team", ""),
        "work_name": identity.frontmatter.get("work_name", ""),
        "base": {
            "display_name": base.frontmatter.get("selected_base_display_name", ""),
            "relation": base.frontmatter.get("direction", "uncertain"),
            "confidence": base.frontmatter.get("confidence", "low"),
        },
        "risk_tags": risk_tags,
        "module_summary": summary,
        "public_paths": {"markdown": "report.md", "html": "site/report.html", "data": "site/report_data.json"},
    }


def assemble_or_raise(case_dir: str | Path) -> None:
    report = assemble_report(case_dir)
    if not report.ok:
        raise ReviewCaseValidationError(report)
