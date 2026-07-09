from __future__ import annotations

import re
from pathlib import Path

from .contracts import (
    REQUIRED_BASE_HEADINGS,
    REQUIRED_CHEAT_HEADINGS,
    REQUIRED_DOC_CLAIM_HEADINGS,
    REQUIRED_HISTORY_AI_HEADINGS,
    REQUIRED_MODULE_HEADINGS,
    REQUIRED_REPORT_HEADINGS,
    OPTIONAL_REPORT_HEADINGS,
    VALID_BASE_DELTA,
    VALID_CONTRADICTION_STATUS,
    VALID_FINDING_STATUS,
    VALID_MODULE_STATUS,
    VALID_ORIGINALITY,
    ValidationReport,
)
from .evidence import EvidenceCard, load_evidence
from .parser import MarkdownDocument, parse_markdown
from .taxonomy import REQUIRED_MODULES, required_module_ids, scan_deleted_features, validate_taxonomy

MACHINE_RE = re.compile(r"\bT20\d{10,}-\d+\b")
BARE_SUFFIX_RE = re.compile(r"(?<![A-Za-z0-9])\d{2,4}\s*(?:作品|队伍|仓库|报告)")
UNCERTAIN_WORDS = ("不确定", "未观察到", "待补证", "可能", "风险提示", "无法确认")
STRONG_MARKERS = (
    "实现了",
    "新增",
    "重写",
    "继承",
    "复制",
    "抄袭",
    "伪造",
    "硬编码",
    "隐匿",
    "不实",
    "原创",
    "改写",
    "支持",
    "存在",
)
GENERIC_LINES = (
    "该模块实现完整",
    "实现较为完整",
    "与 Base 基本一致",
    "功能较为完善",
    "基本实现相关功能",
    "该功能继承自 Base",
)


def validate_case_dir(case_dir: str | Path) -> ValidationReport:
    root = Path(case_dir)
    report = ValidationReport()
    evidence, evidence_report = load_evidence(root / "evidence.jsonl")
    report.extend(evidence_report)
    report.extend(validate_taxonomy())
    docs = _load_existing_docs(root)
    for doc in docs:
        report.extend(validate_document_structure(doc))
        report.extend(validate_identity_text(doc))
        report.extend(validate_evidence_refs(doc, evidence))
        report.extend(validate_strong_claims(doc, evidence))
        report.extend(validate_same_year_direction(doc, evidence))
        report.extend(validate_deleted_features(doc))
    report.extend(validate_required_modules(root, docs))
    report.extend(validate_module_quality(docs))
    report.extend(validate_contradictions(root))
    report.extend(validate_optional_sections(root))
    report.extend(validate_architecture_graph(root))
    return report


def _load_existing_docs(root: Path) -> list[MarkdownDocument]:
    paths: list[Path] = []
    for rel in ["identity.md", "base.md", "report.md", "issues/contradictions.md"]:
        path = root / rel
        if path.exists():
            paths.append(path)
    for pattern in ["modules/*.md", "findings/*.md"]:
        paths.extend(sorted(root.glob(pattern)))
    return [parse_markdown(path) for path in paths]


def validate_document_structure(doc: MarkdownDocument) -> ValidationReport:
    report = ValidationReport()
    contract = str(doc.frontmatter.get("contract", "")).strip()
    if not contract:
        report.add("structure.missing_contract", "frontmatter contract is required", doc.path)
        return report
    if contract == "base_decision":
        _require_headings(report, doc, REQUIRED_BASE_HEADINGS)
        _require_heading_order(report, doc, REQUIRED_BASE_HEADINGS)
        if doc.frontmatter.get("status") != "accepted":
            report.add("base.not_accepted", "base.md must have status: accepted before module review", doc.path)
    elif contract == "module_review":
        _require_headings(report, doc, REQUIRED_MODULE_HEADINGS)
        _require_heading_order(report, doc, REQUIRED_MODULE_HEADINGS)
        _require_enum(report, doc, "status", VALID_MODULE_STATUS)
        _require_enum(report, doc, "originality", VALID_ORIGINALITY)
        _require_enum(report, doc, "base_delta", VALID_BASE_DELTA)
        module_id = str(doc.frontmatter.get("module_id", ""))
        if module_id not in REQUIRED_MODULES:
            report.add("taxonomy.unknown_module", f"module_id is not a required taxonomy module: {module_id}", doc.path)
    elif contract == "finding_set":
        _require_enum(report, doc, "status", VALID_FINDING_STATUS)
        finding_type = str(doc.frontmatter.get("finding_type", ""))
        if finding_type == "doc_claim":
            _require_headings(report, doc, REQUIRED_DOC_CLAIM_HEADINGS)
            _require_heading_order(report, doc, REQUIRED_DOC_CLAIM_HEADINGS)
        elif finding_type == "history_ai":
            _require_headings(report, doc, REQUIRED_HISTORY_AI_HEADINGS)
            _require_heading_order(report, doc, REQUIRED_HISTORY_AI_HEADINGS)
        elif finding_type == "cheat":
            _require_headings(report, doc, REQUIRED_CHEAT_HEADINGS)
            _require_heading_order(report, doc, REQUIRED_CHEAT_HEADINGS)
    elif contract == "contradiction_set":
        _require_enum(report, doc, "status", VALID_CONTRADICTION_STATUS)
    elif contract == "assembled_report":
        _validate_assembled_report_structure(report, doc)
    elif contract == "identity":
        pass
    else:
        report.add("structure.unknown_contract", f"unknown contract: {contract}", doc.path)
    return report


def _require_headings(report: ValidationReport, doc: MarkdownDocument, headings: list[str]) -> None:
    for heading in headings:
        if not doc.has_heading(heading):
            report.add("structure.missing_heading", f"missing heading: ## {heading}", doc.path, heading)


def _require_heading_order(report: ValidationReport, doc: MarkdownDocument, headings: list[str]) -> None:
    positions = {heading.title: heading.start_line for heading in doc.headings if heading.level == 2}
    last = -1
    for heading in headings:
        current = positions.get(heading)
        if current is None:
            continue
        if current <= last:
            report.add("structure.heading_order", f"heading out of order: ## {heading}", doc.path, heading)
        last = current


def _validate_assembled_report_structure(report: ValidationReport, doc: MarkdownDocument) -> None:
    h1 = [heading for heading in doc.headings if heading.level == 1]
    if len(h1) != 1:
        report.add("structure.report_h1", "assembled report must contain exactly one H1", doc.path)
    top = [heading.title for heading in doc.headings if heading.level == 2]
    for heading in REQUIRED_REPORT_HEADINGS:
        if heading not in top:
            report.add("structure.missing_heading", f"missing heading: ## {heading}", doc.path, heading)
    required_positions = [top.index(heading) for heading in REQUIRED_REPORT_HEADINGS if heading in top]
    if required_positions != sorted(required_positions):
        report.add("structure.report_heading_order", "required report headings must follow the contract order", doc.path)
    allowed = set(REQUIRED_REPORT_HEADINGS) | set(OPTIONAL_REPORT_HEADINGS)
    for heading in top:
        if heading not in allowed:
            report.add("structure.report_unknown_h2", f"unknown report H2 heading: {heading}", doc.path, heading)
    if "内核架构图" in top and "模块实现与 Base 差异" in top:
        start = top.index("内核架构图")
        end = top.index("模块实现与 Base 差异")
        for heading in OPTIONAL_REPORT_HEADINGS:
            if heading in top and not (start < top.index(heading) < end):
                report.add("structure.optional_heading_position", f"optional section must appear before module details: {heading}", doc.path, heading)
    for heading in doc.headings:
        if heading.level > 3:
            report.add("structure.heading_depth", "report headings deeper than H3 are forbidden", doc.path, heading.title)


def _require_enum(report: ValidationReport, doc: MarkdownDocument, field: str, allowed: set[str]) -> None:
    value = str(doc.frontmatter.get(field, "")).strip()
    if value not in allowed:
        report.add("structure.invalid_enum", f"{field} must be one of {sorted(allowed)}, got {value!r}", doc.path)


def validate_identity_text(doc: MarkdownDocument) -> ValidationReport:
    report = ValidationReport()
    text = doc.body
    allowed_machine_context = doc.path.name == "identity.md" or "case_state" in doc.path.parts
    if not allowed_machine_context:
        match = MACHINE_RE.search(text)
        if match:
            report.add("identity.machine_name_leak", f"machine repo id leaks into public markdown: {match.group(0)}", doc.path)
        bare = BARE_SUFFIX_RE.search(text)
        if bare:
            report.add("identity.bare_suffix_name", f"numeric fork suffix used as prose name: {bare.group(0)}", doc.path)
    return report


def validate_evidence_refs(doc: MarkdownDocument, evidence: dict[str, EvidenceCard]) -> ValidationReport:
    report = ValidationReport()
    for ref in doc.evidence_refs:
        if ref not in evidence:
            report.add("evidence.unknown_ref", f"unknown evidence reference [@{ref}]", doc.path)
    return report


def validate_strong_claims(doc: MarkdownDocument, evidence: dict[str, EvidenceCard]) -> ValidationReport:
    report = ValidationReport()
    if doc.frontmatter.get("contract") == "identity":
        return report
    for line_no, line in enumerate(doc.body.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "---", "|")):
            continue
        if stripped.startswith("**") and stripped.endswith("**") and "[@" not in stripped:
            continue
        if any(word in stripped for word in UNCERTAIN_WORDS):
            continue
        if any(marker in stripped for marker in STRONG_MARKERS):
            refs = re.findall(r"\[@(E\d{3})\]", stripped)
            if not refs:
                report.add("evidence.strong_claim_missing_ref", f"strong claim lacks evidence chip on line {line_no}: {stripped[:120]}", doc.path)
                continue
            strong = [ref for ref in refs if evidence.get(ref) and evidence[ref].verified and evidence[ref].confidence == "strong"]
            medium = [ref for ref in refs if evidence.get(ref) and evidence[ref].verified and evidence[ref].confidence == "medium"]
            if not strong and len(medium) < 2:
                report.add("evidence.strong_claim_weak_support", f"strong claim needs one strong or two medium verified evidence refs on line {line_no}", doc.path)
    return report


def validate_same_year_direction(doc: MarkdownDocument, evidence: dict[str, EvidenceCard]) -> ValidationReport:
    report = ValidationReport()
    if doc.frontmatter.get("contract") != "base_decision":
        return report
    text = doc.section("方向判断")
    if not text or not any(term in text for term in ("同届", "同赛年", "same-year", "same year")):
        return report
    if any(word in text for word in UNCERTAIN_WORDS) and not any(word in text for word in ("判定", "确认", "抄袭自", "先提交", "后提交", "后导入")):
        return report
    if not any(word in text for word in ("抄袭", "先提交", "后提交", "后导入", "复制", "改名", "拆文件", "方向为")):
        return report
    refs = set(re.findall(r"\[@(E\d{3})\]", text))
    has_git = any(evidence.get(ref) and evidence[ref].kind == "git_history" for ref in refs)
    has_structure = any(_is_structural_similarity_evidence(evidence.get(ref)) for ref in refs)
    if not has_git or not has_structure:
        report.add(
            "same_year_direction.requires_git_and_structure",
            "same-year plagiarism direction needs both structural/AST similarity evidence and git timeline evidence",
            doc.path,
            "方向判断",
        )
    return report


def _is_structural_similarity_evidence(card: EvidenceCard | None) -> bool:
    if card is None:
        return False
    if card.kind == "base_delta_summary":
        return True
    text = f"{card.kind} {card.title} {card.excerpt} {card.canonical_path} {' '.join(card.supports)}".lower()
    return any(term in text for term in ("fingerprint", "ast", "结构指纹", "结构相似", "相似热点", "函数改名", "拆文件"))


def validate_deleted_features(doc: MarkdownDocument) -> ValidationReport:
    report = ValidationReport()
    if doc.frontmatter.get("contract") == "identity":
        return report
    for feature in scan_deleted_features(doc.body):
        report.add("taxonomy.deleted_feature_mentioned", f"deleted feature must not appear in task/report/prompt markdown: {feature}", doc.path)
    return report


def validate_required_modules(root: Path, docs: list[MarkdownDocument]) -> ValidationReport:
    report = ValidationReport()
    module_ids = {str(doc.frontmatter.get("module_id", "")) for doc in docs if doc.frontmatter.get("contract") == "module_review"}
    for module_id in required_module_ids():
        if module_id not in module_ids:
            report.add("taxonomy.required_module_missing", f"missing required module review: {module_id}", root / "modules")
    return report


def validate_module_quality(docs: list[MarkdownDocument]) -> ValidationReport:
    report = ValidationReport()
    for doc in docs:
        if doc.frontmatter.get("contract") != "module_review":
            continue
        module_id = str(doc.frontmatter.get("module_id", ""))
        status = str(doc.frontmatter.get("status", ""))
        base_delta = str(doc.frontmatter.get("base_delta", ""))
        originality = str(doc.frontmatter.get("originality", ""))
        delta_text = doc.section("相对 Base 的变化")
        if status not in {"absent", "not_applicable"} and len(doc.code_anchors) < 3:
            report.add("module_quality.too_few_anchors", f"{module_id} needs at least 3 concrete code anchors, got {len(doc.code_anchors)}", doc.path)
        if not delta_text:
            report.add("base_delta.missing_section_text", f"{module_id} lacks Base delta text", doc.path, "相对 Base 的变化")
        elif base_delta != "none" and _is_generic(delta_text):
            report.add("base_delta.generic", f"{module_id} Base delta is too generic", doc.path, "相对 Base 的变化")
        if base_delta == "none" and originality == "novel":
            report.add("contradiction.novel_without_delta", f"{module_id} cannot be novel when base_delta=none", doc.path)
        impl = doc.section("实现内容")
        if impl and delta_text and _normalize_para(impl) == _normalize_para(delta_text):
            report.add("module_quality.duplicate_sections", f"{module_id} implementation and Base delta sections are identical", doc.path)
        for generic in GENERIC_LINES:
            if generic in doc.body:
                report.add("module_quality.generic_sentence", f"generic template sentence is forbidden: {generic}", doc.path)
    return report


def _is_generic(text: str) -> bool:
    clean = _normalize_para(text)
    if len(clean) < 20:
        return True
    return any(generic in text for generic in GENERIC_LINES) and "[@E" not in text


def _normalize_para(text: str) -> str:
    return re.sub(r"\s+", "", text.strip())


def validate_contradictions(root: Path) -> ValidationReport:
    report = ValidationReport()
    path = root / "issues" / "contradictions.md"
    if path.exists():
        doc = parse_markdown(path)
        if doc.frontmatter.get("status") == "unresolved":
            report.add("contradiction.unresolved", "unresolved contradictions block report assembly", path)
    return report


def validate_optional_sections(root: Path) -> ValidationReport:
    report = ValidationReport()
    report_path = root / "report.md"
    if not report_path.exists():
        return report
    text = report_path.read_text(encoding="utf-8")
    cheat_path = root / "findings" / "cheat.md"
    if cheat_path.exists():
        cheat = parse_markdown(cheat_path)
        if cheat.frontmatter.get("status") == "no_findings":
            if re.search(r"^##\s+作弊、刷分与提示注入风险", text, flags=re.MULTILINE):
                report.add("optional_section.cheat_no_findings_visible", "cheat no_findings must omit public cheat section", report_path)
    return report


def validate_architecture_graph(root: Path) -> ValidationReport:
    report = ValidationReport()
    report_path = root / "report.md"
    if not report_path.exists():
        return report
    text = report_path.read_text(encoding="utf-8")
    if "## 内核架构图" not in text:
        report.add("architecture_graph.missing_section", "assembled report must include kernel architecture graph", report_path)
        return report
    match = re.search(r"```mermaid\n(?P<body>[\s\S]*?)\n```", text)
    if not match:
        report.add("architecture_graph.missing_mermaid", "kernel architecture graph must be a mermaid code block", report_path, "内核架构图")
        return report
    body = match.group("body")
    allowed = {module_id.replace("-", "_") for module_id in REQUIRED_MODULES}
    for module_id in allowed:
        if module_id not in body:
            report.add("architecture_graph.missing_module", f"architecture graph missing required module node: {module_id}", report_path, "内核架构图")
    nodes = set(re.findall(r"^\s*([a-z0-9_]+)\[", body, flags=re.MULTILINE))
    unknown = sorted(nodes - allowed)
    if unknown:
        report.add("architecture_graph.unknown_node", f"architecture graph contains non-taxonomy nodes: {unknown}", report_path, "内核架构图")
    if len(nodes) != len(allowed):
        report.add("architecture_graph.node_count", f"architecture graph must contain exactly {len(allowed)} taxonomy nodes, got {len(nodes)}", report_path, "内核架构图")
    edge_count = len(re.findall(r"-->|-\.", body))
    min_edges = max(1, len(allowed) - 2)
    max_edges = len(allowed) * 2
    if edge_count < min_edges:
        report.add("architecture_graph.too_few_edges", f"architecture graph needs at least {min_edges} evidence-bounded edges, got {edge_count}", report_path, "内核架构图")
    if edge_count > max_edges:
        report.add("architecture_graph.too_many_edges", f"architecture graph must stay compact; max {max_edges} edges, got {edge_count}", report_path, "内核架构图")
    return report
