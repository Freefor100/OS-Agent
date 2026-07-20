from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .contracts import (
    OPTIONAL_REPORT_HEADINGS,
    REQUIRED_BASE_HEADINGS,
    REQUIRED_CHEAT_HEADINGS,
    REQUIRED_CONTRADICTION_HEADINGS,
    REQUIRED_DOC_CLAIM_HEADINGS,
    REQUIRED_HISTORY_AI_HEADINGS,
    REQUIRED_MODULE_HEADINGS,
    REQUIRED_REPORT_HEADINGS,
    VALID_BASE_CONFIDENCE,
    VALID_BASE_DELTA,
    VALID_CONTRADICTION_STATUS,
    VALID_FINDING_STATUS,
    VALID_MODULE_STATUS,
    VALID_ORIGINALITY,
    ValidationReport,
)
from .evidence import EvidenceCard, EvidenceError, load_evidence
from .parser import MarkdownDocument, parse_markdown
from .taxonomy import MODULES, validate_taxonomy

MACHINE_RE = re.compile(r"\bT20\d{10,}-\d+\b")
BARE_SUFFIX_RE = re.compile(r"(?<![A-Za-z0-9])\d{2,4}\s*(?:作品|队伍|仓库|报告)")
GIT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
MERMAID_RE = re.compile(r"```mermaid\s*\n(?P<body>[\s\S]*?)\n```", re.IGNORECASE)
MODULE_NODE_HEADING_RE = re.compile(r"^(?P<node_id>[a-z][a-z0-9-]*)[：:]\s*.+$")


def validate_case_dir(case_dir: str | Path) -> ValidationReport:
    root = Path(case_dir)
    report = ValidationReport()
    evidence = _load_evidence(root / "evidence.jsonl", report)
    report.extend(validate_taxonomy())
    docs = _load_docs(root, report)
    for required in (root / "identity.md", root / "base.md", root / "report.md"):
        if not required.exists():
            report.add("structure.missing_file", "required final document is missing", required)
    if not list((root / "modules").glob("*.md")):
        report.add("structure.missing_modules", "at least one module review is required", root / "modules")
    for doc in docs:
        report.extend(validate_document_structure(doc))
        report.extend(validate_output_path(doc, root))
        report.extend(validate_identity_text(doc, root))
        report.extend(validate_evidence_refs(doc, evidence))
    report.extend(validate_report_identity(docs))
    report.extend(validate_contradictions(root))
    report.extend(validate_optional_sections(root))
    report.extend(validate_architecture_graph(root))
    return report


def validate_fragment(case_dir: str | Path, path: str | Path) -> ValidationReport:
    root = Path(case_dir)
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    report = ValidationReport()
    evidence = _load_evidence(root / "evidence.jsonl", report)
    if not target.exists():
        report.add("structure.missing_file", "fragment does not exist", target)
        return report
    try:
        doc = parse_markdown(target)
    except Exception as exc:
        report.add("structure.parse_error", str(exc), target)
        return report
    report.extend(validate_document_structure(doc))
    report.extend(validate_output_path(doc, root))
    report.extend(validate_identity_text(doc, root))
    report.extend(validate_evidence_refs(doc, evidence))
    return report


def _load_docs(root: Path, report: ValidationReport) -> list[MarkdownDocument]:
    paths = [root / name for name in ("identity.md", "base.md", "report.md", "issues/contradictions.md")]
    paths.extend(sorted((root / "modules").glob("*.md")))
    paths.extend(sorted((root / "findings").glob("*.md")))
    docs: list[MarkdownDocument] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            docs.append(parse_markdown(path))
        except Exception as exc:
            report.add("structure.parse_error", str(exc), path)
    return docs


def validate_document_structure(doc: MarkdownDocument) -> ValidationReport:
    report = ValidationReport()
    contract = str(doc.frontmatter.get("contract", "")).strip()
    if not contract:
        report.add("structure.missing_contract", "frontmatter contract is required", doc.path)
        return report
    if contract == "identity":
        return report
    _require_single_h1(report, doc)
    if contract == "base_decision":
        _require_frontmatter_fields(
            report,
            doc,
            [
                "status",
                "selected_base_work_id",
                "selected_base_display_name",
                "selected_base_commit",
                "target_introduction_commit",
                "target_introduction_kind",
                "direction",
                "confidence",
            ],
        )
        _require_headings(report, doc, REQUIRED_BASE_HEADINGS)
        _require_heading_order(report, doc, REQUIRED_BASE_HEADINGS)
        _reject_unknown_h2(report, doc, set(REQUIRED_BASE_HEADINGS))
        status = str(doc.frontmatter.get("status", ""))
        if status not in {"accepted", "no_reliable_base"}:
            report.add("structure.invalid_enum", "base status must be accepted or no_reliable_base", doc.path)
        if status == "accepted":
            _validate_base_commits(report, doc)
            _require_nonempty_frontmatter(report, doc, ["selected_base_work_id", "selected_base_display_name"])
        elif status == "no_reliable_base":
            if str(doc.frontmatter.get("target_introduction_kind", "")) != "unknown":
                report.add("base.introduction_kind", "no_reliable_base requires target_introduction_kind: unknown", doc.path)
        _require_nonempty_frontmatter(report, doc, ["direction", "confidence"])
        _require_enum(report, doc, "confidence", VALID_BASE_CONFIDENCE)
        return report
    if contract == "module_review":
        _require_frontmatter_fields(report, doc, ["module_id", "status", "originality", "base_delta"])
        _require_headings(report, doc, REQUIRED_MODULE_HEADINGS)
        _require_heading_order(report, doc, REQUIRED_MODULE_HEADINGS)
        _reject_unknown_h2(report, doc, set(REQUIRED_MODULE_HEADINGS) | {"需联动结论"})
        _require_optional_h2_last(report, doc, "需联动结论")
        _require_enum(report, doc, "status", VALID_MODULE_STATUS)
        _require_enum(report, doc, "originality", VALID_ORIGINALITY)
        _require_enum(report, doc, "base_delta", VALID_BASE_DELTA)
        module_id = str(doc.frontmatter.get("module_id", ""))
        if module_id not in MODULES:
            report.add("taxonomy.unknown_module", f"unknown module_id: {module_id}", doc.path)
        else:
            _validate_module_node_ids(report, doc, module_id)
        return report
    if contract == "finding_set":
        _require_frontmatter_fields(report, doc, ["finding_type", "status", "public"])
        _require_enum(report, doc, "status", VALID_FINDING_STATUS)
        _validate_public_flag(report, doc)
        finding_type = str(doc.frontmatter.get("finding_type", ""))
        headings = {
            "doc_claim": REQUIRED_DOC_CLAIM_HEADINGS,
            "history_ai": REQUIRED_HISTORY_AI_HEADINGS,
            "cheat": REQUIRED_CHEAT_HEADINGS,
        }.get(finding_type)
        if headings is None:
            report.add("structure.unknown_finding_type", f"unknown finding_type: {finding_type}", doc.path)
        else:
            _require_headings(report, doc, headings)
            _require_heading_order(report, doc, headings)
            _reject_unknown_h2(report, doc, set(headings))
        return report
    if contract == "contradiction_set":
        _require_frontmatter_fields(report, doc, ["status"])
        _require_enum(report, doc, "status", VALID_CONTRADICTION_STATUS)
        _require_headings(report, doc, REQUIRED_CONTRADICTION_HEADINGS)
        _require_heading_order(report, doc, REQUIRED_CONTRADICTION_HEADINGS)
        _reject_unknown_h2(report, doc, set(REQUIRED_CONTRADICTION_HEADINGS))
        return report
    if contract == "final_report":
        _validate_report_structure(report, doc)
        return report
    report.add("structure.unknown_contract", f"unknown contract: {contract}", doc.path)
    return report


def _validate_module_node_ids(report: ValidationReport, doc: MarkdownDocument, module_id: str) -> None:
    allowed = {node.node_id for node in MODULES[module_id].nodes}
    for heading in doc.headings:
        if heading.level != 3:
            continue
        match = MODULE_NODE_HEADING_RE.fullmatch(heading.title)
        if match and match.group("node_id") not in allowed:
            report.add(
                "taxonomy.unknown_node",
                f"unknown node_id for {module_id}: {match.group('node_id')}",
                doc.path,
                heading.title,
            )


def validate_output_path(doc: MarkdownDocument, root: Path) -> ValidationReport:
    report = ValidationReport()
    try:
        relative = doc.path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        report.add("structure.output_outside_case", "output must be inside case_dir", doc.path)
        return report
    contract = str(doc.frontmatter.get("contract", ""))
    fixed = {
        "identity.md": "identity",
        "base.md": "base_decision",
        "report.md": "final_report",
        "issues/contradictions.md": "contradiction_set",
        "findings/doc-claims.md": "finding_set",
        "findings/history-ai.md": "finding_set",
        "findings/cheat.md": "finding_set",
    }
    expected_contract = fixed.get(relative)
    if expected_contract and contract != expected_contract:
        report.add("structure.contract_path_mismatch", f"{relative} requires contract: {expected_contract}", doc.path)
    finding_types = {
        "findings/doc-claims.md": "doc_claim",
        "findings/history-ai.md": "history_ai",
        "findings/cheat.md": "cheat",
    }
    canonical_paths = {
        "identity": {"identity.md"},
        "base_decision": {"base.md"},
        "final_report": {"report.md"},
        "contradiction_set": {"issues/contradictions.md"},
        "finding_set": set(finding_types),
    }
    if contract in canonical_paths and relative not in canonical_paths[contract]:
        report.add("structure.invalid_output_path", f"contract {contract} cannot be written to {relative}", doc.path)
    expected_finding = finding_types.get(relative)
    if expected_finding and doc.frontmatter.get("finding_type") != expected_finding:
        report.add("structure.finding_path_mismatch", f"{relative} requires finding_type: {expected_finding}", doc.path)
    module_path = Path(relative)
    if contract == "module_review" and (module_path.parent.as_posix() != "modules" or module_path.suffix != ".md"):
        report.add("structure.invalid_output_path", "module_review must be written directly under modules/", doc.path)
    if module_path.parent.as_posix() == "modules" and module_path.suffix == ".md":
        expected_module = Path(relative).stem
        if contract != "module_review":
            report.add("structure.contract_path_mismatch", "module files require contract: module_review", doc.path)
        if doc.frontmatter.get("module_id") != expected_module:
            report.add("structure.module_path_mismatch", f"filename requires module_id: {expected_module}", doc.path)
    return report


def validate_identity_text(doc: MarkdownDocument, root: Path) -> ValidationReport:
    report = ValidationReport()
    if doc.frontmatter.get("contract") == "identity":
        return report
    forbidden: set[str] = set()
    manifest = root / "case_state" / "manifest.json"
    if manifest.exists():
        try:
            work = json.loads(manifest.read_text(encoding="utf-8")).get("work", {})
            if work.get("machine_repo"):
                forbidden.add(str(work["machine_repo"]))
        except (json.JSONDecodeError, OSError):
            pass
    match = MACHINE_RE.search(doc.body)
    if match:
        report.add("identity.machine_name_leak", f"machine repo id leaks into public markdown: {match.group(0)}", doc.path)
    for value in forbidden:
        if value and value in doc.body:
            report.add("identity.machine_name_leak", f"machine repo id leaks into public markdown: {value}", doc.path)
    bare = BARE_SUFFIX_RE.search(doc.body)
    if bare:
        report.add("identity.bare_suffix_name", f"numeric fork suffix used as prose name: {bare.group(0)}", doc.path)
    return report


def validate_evidence_refs(doc: MarkdownDocument, evidence: dict[str, EvidenceCard]) -> ValidationReport:
    report = ValidationReport()
    for ref in doc.evidence_refs:
        if ref not in evidence:
            report.add("evidence.unknown_ref", f"unknown evidence reference [@{ref}]", doc.path)
    return report


def validate_report_identity(docs: list[MarkdownDocument]) -> ValidationReport:
    report = ValidationReport()
    identity = next((doc for doc in docs if doc.frontmatter.get("contract") == "identity"), None)
    final = next((doc for doc in docs if doc.frontmatter.get("contract") == "final_report"), None)
    if not identity or not final:
        return report
    display_name = str(identity.frontmatter.get("display_name", "")).strip()
    h1 = next((heading.title for heading in final.headings if heading.level == 1), "")
    if display_name and display_name not in h1:
        report.add("identity.report_title", "report H1 must use identity.md display_name", final.path)
    return report


def validate_contradictions(root: Path) -> ValidationReport:
    report = ValidationReport()
    path = root / "issues" / "contradictions.md"
    if not path.exists():
        report.add("contradiction.missing", "最终报告前必须完成 contradiction-arbiter", path)
        return report
    try:
        doc = parse_markdown(path)
    except Exception:
        return report
    if doc.frontmatter.get("status") == "unresolved":
        report.add("contradiction.unresolved", "unresolved contradictions block the final report", path)
        return report

    review_path = root / "case_state" / "contradiction-review.json"
    if not review_path.exists():
        report.add(
            "contradiction.review_missing",
            "缺少仲裁输入摘要，请运行 contradiction-check",
            review_path,
        )
        return report
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.add("contradiction.review_invalid", f"仲裁输入摘要无法读取: {exc}", review_path)
        return report
    if review.get("schema") != "review_case.contradiction_review.v1":
        report.add("contradiction.review_invalid", "仲裁输入摘要 schema 非法", review_path)
        return report
    if review.get("status") != doc.frontmatter.get("status"):
        report.add("contradiction.review_stale", "仲裁状态已变化，必须重新仲裁", review_path)
    try:
        current_files = _contradiction_material_hashes(root)
    except FileNotFoundError as exc:
        report.add("contradiction.material_missing", str(exc), root)
        return report
    recorded_files = review.get("files")
    if not isinstance(recorded_files, dict) or not recorded_files:
        report.add("contradiction.review_invalid", "仲裁输入摘要缺少 files", review_path)
        return report
    if recorded_files != current_files or review.get("digest") != _material_digest(current_files):
        report.add(
            "contradiction.review_stale",
            "Base、模块、finding、证据或仲裁文件已变化，必须重新运行 contradiction-arbiter 和 contradiction-check",
            review_path,
        )
    return report


def contradiction_check(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    path = root / "issues" / "contradictions.md"
    report = ValidationReport()
    if not path.exists():
        report.add("contradiction.missing", "缺少 issues/contradictions.md", path)
        report.raise_for_errors()
    evidence = _load_evidence(root / "evidence.jsonl", report)
    try:
        doc = parse_markdown(path)
    except Exception as exc:
        report.add("structure.parse_error", str(exc), path)
        report.raise_for_errors()
        raise AssertionError("unreachable")
    report.extend(validate_document_structure(doc))
    report.extend(validate_output_path(doc, root))
    report.extend(validate_identity_text(doc, root))
    report.extend(validate_evidence_refs(doc, evidence))
    if doc.frontmatter.get("status") == "unresolved":
        report.add("contradiction.unresolved", "仍有未解决矛盾，不能确认仲裁结果", path)
    report.raise_for_errors()

    files = _contradiction_material_hashes(root)
    payload = {
        "schema": "review_case.contradiction_review.v1",
        "status": doc.frontmatter.get("status"),
        "files": files,
        "digest": _material_digest(files),
    }
    output = root / "case_state" / "contradiction-review.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return output


def _contradiction_material_hashes(root: Path) -> dict[str, str]:
    required = [
        root / "identity.md",
        root / "base.md",
        root / "evidence.jsonl",
        root / "issues" / "contradictions.md",
    ]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(f"仲裁材料缺失: {path.relative_to(root)}")
    paths = required
    paths.extend(sorted((root / "modules").glob("*.md")))
    paths.extend(sorted((root / "findings").glob("*.md")))
    result: dict[str, str] = {}
    for path in sorted(set(paths)):
        relative = path.relative_to(root).as_posix()
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _material_digest(files: dict[str, str]) -> str:
    content = "".join(f"{path}\0{digest}\n" for path, digest in sorted(files.items()))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_evidence(path: Path, report: ValidationReport) -> dict[str, EvidenceCard]:
    try:
        return load_evidence(path)
    except EvidenceError as exc:
        report.add("evidence.invalid", str(exc), path)
        return {}


def validate_optional_sections(root: Path) -> ValidationReport:
    report = ValidationReport()
    report_path = root / "report.md"
    if not report_path.exists():
        return report
    try:
        final = parse_markdown(report_path)
    except Exception:
        return report
    present = {heading.title for heading in final.headings if heading.level == 2}
    mapping = {
        "doc-claims.md": "文档声明审查",
        "history-ai.md": "开发历史与 AI 使用",
        "cheat.md": "测评定向与结果真实性",
    }
    for filename, heading in mapping.items():
        path = root / "findings" / filename
        if not path.exists():
            if heading in present:
                report.add("optional_section.without_source", f"section has no finding source: {heading}", report_path, heading)
            continue
        try:
            finding = parse_markdown(path)
        except Exception:
            continue
        public = finding.frontmatter.get("status") == "findings" and str(finding.frontmatter.get("public", "true")).lower() != "false"
        if public and heading not in present:
            report.add("optional_section.missing_public", f"public finding section is missing: {heading}", report_path, heading)
        if not public and heading in present:
            report.add("optional_section.hidden_leak", f"non-public finding section must be omitted: {heading}", report_path, heading)
    return report


def validate_architecture_graph(root: Path) -> ValidationReport:
    report = ValidationReport()
    path = root / "report.md"
    if not path.exists():
        return report
    try:
        section = parse_markdown(path).section("内核架构图")
    except Exception:
        return report
    match = MERMAID_RE.search(section)
    if not match or not match.group("body").strip():
        report.add("architecture_graph.missing_mermaid", "内核架构图 must contain one non-empty mermaid block", path, "内核架构图")
    elif len(MERMAID_RE.findall(section)) != 1:
        report.add("architecture_graph.multiple_mermaid", "内核架构图 must contain exactly one mermaid block", path, "内核架构图")
    return report


def _require_headings(report: ValidationReport, doc: MarkdownDocument, headings: list[str]) -> None:
    for title in headings:
        if not doc.has_heading(title):
            report.add("structure.missing_heading", f"missing heading: ## {title}", doc.path, title)
        elif not _section_has_content(doc, title):
            report.add("structure.empty_heading", f"section is empty: ## {title}", doc.path, title)


def _require_single_h1(report: ValidationReport, doc: MarkdownDocument) -> None:
    h1 = [heading for heading in doc.headings if heading.level == 1]
    if len(h1) != 1:
        report.add("structure.h1", "document must contain exactly one H1", doc.path)


def _require_frontmatter_fields(report: ValidationReport, doc: MarkdownDocument, fields: list[str]) -> None:
    for field in fields:
        if field not in doc.frontmatter:
            report.add("structure.missing_frontmatter", f"missing frontmatter field: {field}", doc.path)


def _require_nonempty_frontmatter(report: ValidationReport, doc: MarkdownDocument, fields: list[str]) -> None:
    for field in fields:
        if not str(doc.frontmatter.get(field, "")).strip():
            report.add("structure.empty_frontmatter", f"frontmatter field must not be empty: {field}", doc.path)


def _reject_unknown_h2(report: ValidationReport, doc: MarkdownDocument, allowed: set[str]) -> None:
    for heading in doc.headings:
        if heading.level == 2 and heading.title not in allowed:
            report.add("structure.unknown_h2", f"unexpected H2: {heading.title}", doc.path, heading.title)


def _require_optional_h2_last(report: ValidationReport, doc: MarkdownDocument, title: str) -> None:
    top = [heading.title for heading in doc.headings if heading.level == 2]
    if title in top and top[-1] != title:
        report.add("structure.optional_heading_order", f"optional H2 must be last: {title}", doc.path, title)


def _validate_public_flag(report: ValidationReport, doc: MarkdownDocument) -> None:
    value = doc.frontmatter.get("public")
    if not isinstance(value, bool):
        report.add("structure.invalid_public", "public must be YAML boolean true or false", doc.path)
        return
    status = str(doc.frontmatter.get("status", ""))
    if status == "no_findings" and value:
        report.add("structure.invalid_public", "no_findings requires public: false", doc.path)
    if status == "findings" and not value:
        report.add("structure.invalid_public", "findings requires public: true", doc.path)


def _require_heading_order(report: ValidationReport, doc: MarkdownDocument, headings: list[str]) -> None:
    positions = {heading.title: heading.start_line for heading in doc.headings if heading.level == 2}
    existing = [positions[title] for title in headings if title in positions]
    if existing != sorted(existing):
        report.add("structure.heading_order", "required H2 sections are out of order", doc.path)


def _section_has_content(doc: MarkdownDocument, title: str) -> bool:
    for index, heading in enumerate(doc.headings):
        if heading.title != title:
            continue
        if heading.body.strip():
            return True
        for child in doc.headings[index + 1 :]:
            if child.level <= heading.level:
                break
            if child.title.strip() or child.body.strip():
                return True
        return False
    return False


def _require_enum(report: ValidationReport, doc: MarkdownDocument, field: str, allowed: set[str]) -> None:
    value = str(doc.frontmatter.get(field, "")).strip()
    if value not in allowed:
        report.add("structure.invalid_enum", f"{field} must be one of {sorted(allowed)}, got {value!r}", doc.path)


def _validate_base_commits(report: ValidationReport, doc: MarkdownDocument) -> None:
    for field in ("selected_base_commit", "target_introduction_commit"):
        value = str(doc.frontmatter.get(field, "")).strip()
        if not GIT_COMMIT_RE.fullmatch(value):
            report.add("base.commit_missing", f"{field} must be a git commit hash when Base is accepted", doc.path)
    kind = str(doc.frontmatter.get("target_introduction_kind", "")).strip()
    if kind not in {"exact", "initial_visible"}:
        report.add("base.introduction_kind", "target_introduction_kind must be exact or initial_visible", doc.path)


def _validate_report_structure(report: ValidationReport, doc: MarkdownDocument) -> None:
    h1 = [heading for heading in doc.headings if heading.level == 1]
    if len(h1) != 1:
        report.add("structure.report_h1", "report.md must contain exactly one H1", doc.path)
    top = [heading.title for heading in doc.headings if heading.level == 2]
    allowed = set(REQUIRED_REPORT_HEADINGS) | set(OPTIONAL_REPORT_HEADINGS)
    for title in REQUIRED_REPORT_HEADINGS:
        if title not in top:
            report.add("structure.missing_heading", f"missing heading: ## {title}", doc.path, title)
        elif not _section_has_content(doc, title):
            report.add("structure.empty_heading", f"section is empty: ## {title}", doc.path, title)
    for title in top:
        if title not in allowed:
            report.add("structure.report_unknown_h2", f"unknown report H2: {title}", doc.path, title)
    expected_order = [title for title in [
        "整体结论",
        "重点结论",
        "真实工作量分层",
        "Base、其他来源与同届传播关系",
        "内核架构图",
        *OPTIONAL_REPORT_HEADINGS,
        "模块实现细节及 Base 差异",
        "证据索引",
    ] if title in top]
    if top != expected_order:
        report.add("structure.report_heading_order", "report H2 sections do not follow the contract order", doc.path)
    for heading in doc.headings:
        if heading.level > 3:
            report.add("structure.heading_depth", "report headings deeper than H3 are forbidden", doc.path, heading.title)
    module_heading = next((heading for heading in doc.headings if heading.level == 2 and heading.title == "模块实现细节及 Base 差异"), None)
    evidence_heading = next((heading for heading in doc.headings if heading.level == 2 and heading.title == "证据索引"), None)
    if module_heading and evidence_heading:
        module_h3 = [heading for heading in doc.headings if heading.level == 3 and module_heading.start_line < heading.start_line < evidence_heading.start_line]
        if not module_h3:
            report.add("structure.module_h3_missing", "module details must use H3 headings", doc.path, module_heading.title)
