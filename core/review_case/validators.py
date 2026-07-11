from __future__ import annotations

import json
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
from .parser import MarkdownDocument, extract_code_anchors, parse_markdown
from .taxonomy import (
    REQUIRED_MODULES,
    NODE_INDEX,
    VALID_DELTA_CLASS,
    VALID_EFFORT_LEVEL,
    VALID_POINT_STATUS,
    required_module_ids,
    scan_deleted_features,
    validate_taxonomy,
)

MACHINE_RE = re.compile(r"\bT20\d{10,}-\d+\b")
GIT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
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
MODULE_COVERAGE_COLUMNS = ["功能节点", "目标状态", "Base 状态", "差异归类", "计入工作量", "实现入口", "核心状态/不变量", "关键路径/失败边界", "证据"]
FORBIDDEN_PLATFORM_RESULT_PATTERNS = (
    re.compile(r"(?:平台|官方)?(?:测例|测试|测评)(?:全部)?通过"),
    re.compile(r"全部通过"),
    re.compile(r"通过率\s*[:：]?\s*\d"),
    re.compile(r"(?:评测)?得分\s*[:：]?\s*\d"),
    re.compile(r"排名\s*(?:第\s*)?\d|排名第一"),
    re.compile(r"吞吐[^\n。；;]*\d+(?:\.\d+)?\s*(?:MB/s|GB/s)", re.IGNORECASE),
    re.compile(r"延迟[^\n。；;]*\d+(?:\.\d+)?\s*(?:us|ms|μs)", re.IGNORECASE),
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
    report.extend(validate_module_quality(docs, evidence))
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
        _validate_base_commits(report, doc)
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


def _validate_base_commits(report: ValidationReport, doc: MarkdownDocument) -> None:
    for field in ("selected_base_commit", "target_introduction_commit"):
        value = str(doc.frontmatter.get(field, "")).strip()
        if not GIT_COMMIT_RE.fullmatch(value):
            report.add("base.commit_missing", f"{field} must be a 7-40 character git commit hash", doc.path)
    kind = str(doc.frontmatter.get("target_introduction_kind", "")).strip()
    if kind not in {"exact", "initial_visible"}:
        report.add(
            "base.introduction_kind",
            "target_introduction_kind must be exact or initial_visible",
            doc.path,
        )


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


def validate_module_quality(docs: list[MarkdownDocument], evidence: dict[str, EvidenceCard] | None = None) -> ValidationReport:
    evidence = evidence or {}
    report = ValidationReport()
    for doc in docs:
        if doc.frontmatter.get("contract") != "module_review":
            continue
        module_id = str(doc.frontmatter.get("module_id", ""))
        status = str(doc.frontmatter.get("status", ""))
        base_delta = str(doc.frontmatter.get("base_delta", ""))
        originality = str(doc.frontmatter.get("originality", ""))
        module = REQUIRED_MODULES.get(module_id)
        if module is not None:
            report.extend(_validate_module_coverage_table(doc, module, evidence))
        delta_text = doc.section("相对 Base 的变化")
        if status != "absent" and len(doc.code_anchors) < 3:
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
        result_claim_text = "\n".join(
            [doc.section("实现内容"), doc.section("相对 Base 的变化"), doc.section("真实工作量判断")]
        )
        for pattern in FORBIDDEN_PLATFORM_RESULT_PATTERNS:
            match = pattern.search(result_claim_text)
            if match:
                report.add(
                    "module_quality.unavailable_platform_result",
                    f"module agent cannot claim unavailable platform result: {match.group(0)}",
                    doc.path,
                )
                break
    return report


def _validate_module_coverage_table(doc: MarkdownDocument, module, evidence: dict[str, EvidenceCard]) -> ValidationReport:
    report = ValidationReport()
    section = doc.section("实现内容")
    header, rows = _parse_markdown_table(section)
    if header != MODULE_COVERAGE_COLUMNS:
        report.add(
            "module_quality.coverage_table_header",
            "实现内容 must begin with coverage table columns: " + " | ".join(MODULE_COVERAGE_COLUMNS),
            doc.path,
            "实现内容",
        )
        return report

    by_id: dict[str, list[str]] = {}
    for row in rows:
        node_id = row[0].strip().strip("`")
        if node_id in by_id:
            report.add("module_quality.duplicate_check_row", f"duplicate coverage row: {node_id}", doc.path, "实现内容")
            continue
        by_id[node_id] = row

    expected_ids, task_report = _expected_module_nodes(doc, module)
    report.extend(task_report)
    expected = {node.node_id: node for node in module.nodes if node.node_id in expected_ids}
    for node_id in expected:
        if node_id not in by_id:
            report.add("module_quality.missing_node_row", f"missing module node row: {node_id}", doc.path, "实现内容")

    allowed_ids = expected_ids
    for node_id, row in by_id.items():
        if node_id not in allowed_ids:
            report.add("module_quality.unknown_node_row", f"unknown node for {module.module_id}: {node_id}", doc.path, "实现内容")
            continue
        status = row[1].strip().strip("`")
        base_status = row[2].strip().strip("`")
        delta_class = row[3].strip().strip("`")
        effort = row[4].strip().strip("`")
        if status not in VALID_POINT_STATUS:
            report.add("module_quality.invalid_point_status", f"{node_id}: invalid target status {status!r}", doc.path, "实现内容")
            continue
        if base_status not in VALID_POINT_STATUS:
            report.add("module_quality.invalid_base_status", f"{node_id}: invalid Base status {base_status!r}", doc.path, "实现内容")
        if delta_class not in VALID_DELTA_CLASS:
            report.add("module_quality.invalid_delta_class", f"{node_id}: invalid delta class {delta_class!r}", doc.path, "实现内容")
        if effort not in VALID_EFFORT_LEVEL:
            report.add("module_quality.invalid_effort_level", f"{node_id}: invalid effort level {effort!r}", doc.path, "实现内容")
        if delta_class in {"inherited", "external", "none"} and effort != "none":
            report.add("module_quality.effort_contradicts_delta", f"{node_id}: {delta_class} must not count upstream implementation as student effort", doc.path, "实现内容")
        if base_status == "unclear" and delta_class != "unclear":
            report.add("module_quality.delta_without_base", f"{node_id}: Base status is unclear, so delta class must also be unclear", doc.path, "实现内容")
        if delta_class == "unclear" and effort not in {"uncertain", "none"}:
            report.add("module_quality.effort_without_delta", f"{node_id}: unclear delta cannot support a definite student effort level", doc.path, "实现内容")
        if status == "absent" and delta_class == "novel":
            report.add("module_quality.absent_node_marked_novel", f"{node_id}: absent target capability cannot be novel", doc.path, "实现内容")
        evidence_cell = row[8]
        refs = re.findall(r"\[@(E\d{3})\]", evidence_cell)
        if not refs:
            report.add("module_quality.node_missing_evidence", f"{node_id}: coverage row needs evidence chip", doc.path, "实现内容")
        else:
            unrelated = [
                ref
                for ref in refs
                if ref in evidence
                and f"module:{module.module_id}" not in evidence[ref].supports
                and f"node:{node_id}" not in evidence[ref].supports
            ]
            if len(unrelated) == len(refs):
                report.add("module_quality.node_unrelated_evidence", f"{node_id}: evidence does not support this module or node", doc.path, "实现内容")
        if delta_class != "unclear":
            delta_refs = [
                ref
                for ref in refs
                if evidence.get(ref)
                and evidence[ref].kind == "base_delta_summary"
                and f"node:{node_id}" in evidence[ref].supports
                and evidence[ref].verified
            ]
            if not delta_refs:
                report.add(
                    "module_quality.node_delta_missing_evidence",
                    f"{node_id}: Base status and delta class need node-specific base_delta_summary evidence",
                    doc.path,
                    "实现内容",
                )
        if status in {"implemented", "partial", "minimal"}:
            labels = [(5, "实现入口"), (6, "核心状态/不变量"), (7, "关键路径/失败边界")]
            for index, label in labels:
                value = row[index].strip()
                if not value or value in {"-", "无", "不适用"}:
                    report.add("module_quality.node_missing_dimension", f"{node_id}: {label} is required for {status}", doc.path, "实现内容")
            anchors = " ".join(row[5:8])
            if len(extract_code_anchors(anchors)) < 2:
                report.add("module_quality.node_too_few_anchors", f"{node_id}: present node needs at least two concrete anchors across entry/state/path", doc.path, "实现内容")
            implementation_refs = [
                ref
                for ref in refs
                if evidence.get(ref)
                and evidence[ref].kind == "source_span"
                and f"node:{node_id}" in evidence[ref].supports
            ]
            strong = [ref for ref in implementation_refs if evidence[ref].verified and evidence[ref].confidence == "strong"]
            medium = [ref for ref in implementation_refs if evidence[ref].verified and evidence[ref].confidence == "medium"]
            if not strong and len(set(medium)) < 2:
                report.add(
                    "module_quality.node_weak_evidence",
                    f"{node_id}: present node needs node-specific source evidence: one strong or two medium verified refs",
                    doc.path,
                    "实现内容",
                )
    present_rows = [
        node_id
        for node_id, row in by_id.items()
        if node_id in allowed_ids and row[1].strip().strip("`") in {"implemented", "partial", "minimal"}
    ]
    if str(doc.frontmatter.get("status", "")) == "absent" and present_rows:
        report.add(
            "module_quality.absent_module_has_implementation",
            f"absent module contains implemented checks: {present_rows}",
            doc.path,
            "实现内容",
        )
    return report


def _expected_module_nodes(doc: MarkdownDocument, module) -> tuple[set[str], ValidationReport]:
    report = ValidationReport()
    default = {node.node_id for node in module.nodes}
    case_root = doc.path.parent.parent
    task_path = case_root / "case_state" / "task_files" / f"module-{module.module_id}.json"
    if not task_path.exists():
        return default, report
    try:
        payload = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.add("module_quality.task_file_invalid", f"cannot read module task file: {exc}", task_path)
        return default, report
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        report.add("module_quality.task_nodes_missing", "module task file must contain nodes", task_path)
        return default, report
    task_ids = {str(item.get("node_id", "")) for item in nodes if isinstance(item, dict)}
    known = {node.node_id for node in module.nodes}
    unknown = sorted(task_ids - known)
    if unknown:
        report.add("module_quality.task_unknown_nodes", f"task file contains unknown nodes: {unknown}", task_path)
    return (task_ids & known) | default, report


def _parse_markdown_table(section: str) -> tuple[list[str], list[list[str]]]:
    table_lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|") and line.strip().endswith("|")]
    if len(table_lines) < 2:
        return [], []

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    header = cells(table_lines[0])
    separator = cells(table_lines[1])
    if len(separator) != len(header) or not all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in separator):
        return [], []
    rows = [cells(line) for line in table_lines[2:]]
    rows = [row for row in rows if len(row) == len(header)]
    return header, rows


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
    module_nodes = {module_id.replace("-", "_") for module_id in REQUIRED_MODULES}
    detail_nodes = {"n_" + node_id.replace("-", "_") for node_id in NODE_INDEX}
    allowed = module_nodes | detail_nodes
    for module_id in module_nodes:
        if module_id not in body:
            report.add("architecture_graph.missing_module", f"architecture graph missing required module node: {module_id}", report_path, "内核架构图")
    nodes = set(re.findall(r"^\s*([a-z0-9_]+)\[", body, flags=re.MULTILINE))
    unknown = sorted(nodes - allowed)
    if unknown:
        report.add("architecture_graph.unknown_node", f"architecture graph contains non-taxonomy nodes: {unknown}", report_path, "内核架构图")
    selected_nodes = nodes & detail_nodes
    if len(nodes) < len(module_nodes):
        report.add("architecture_graph.node_count", f"architecture graph must contain all {len(module_nodes)} module nodes", report_path, "内核架构图")
    if len(selected_nodes) > 24:
        report.add("architecture_graph.too_many_detail_nodes", f"architecture graph allows at most 24 evidence-backed detail nodes, got {len(selected_nodes)}", report_path, "内核架构图")
    edge_count = len(re.findall(r"-->|-\.", body))
    min_edges = max(1, len(module_nodes) - 2)
    max_edges = (len(module_nodes) + len(selected_nodes)) * 2
    if edge_count < min_edges:
        report.add("architecture_graph.too_few_edges", f"architecture graph needs at least {min_edges} evidence-bounded edges, got {edge_count}", report_path, "内核架构图")
    if edge_count > max_edges:
        report.add("architecture_graph.too_many_edges", f"architecture graph must stay compact; max {max_edges} edges, got {edge_count}", report_path, "内核架构图")
    return report
