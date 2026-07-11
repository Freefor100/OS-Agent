from __future__ import annotations

import json
from pathlib import Path

from .contracts import ValidationReport
from .evidence_map import write_evidence_map
from .fingerprint_search import search_fingerprint_cache
from .fingerprints import write_fingerprint_cache
from .identity import ROOT, find_work, git_text, init_case, load_works, validate_work_identity
from .parser import parse_markdown
from .taxonomy import make_task_files

SOURCE_SUFFIXES = {".c", ".h", ".S", ".s", ".rs", ".cpp", ".cc", ".hpp", ".ld", ".lds", ".toml", ".mk"}
DOC_SUFFIXES = {".md", ".pdf", ".docx", ".txt"}
GENERATED_PARTS = {"target", "build", "dist", "__pycache__", ".pytest_cache", "node_modules"}
THIRD_PARTY_PARTS = {"vendor", "thirdparty", "third_party", "dependency", "dependencies", "extern_crates", "musl", "lwip"}
TEST_PARTS = {"test", "tests", "testcases", "testcase", "ltp", "libc-test", "busybox"}


def init_by_work_id(work_id: str, works_path: str = "config/works.yaml", output_root: str = "output") -> Path:
    work = find_work(work_id, works_path)
    if not work:
        report = ValidationReport()
        report.add("identity.unknown_work", f"work_id not found in {works_path}: {work_id}")
        report.raise_for_errors()
    assert work is not None
    return init_case(work, output_root)


def write_task_files(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    manifest_path = root / "case_state" / "manifest.json"
    work = {}
    if manifest_path.exists():
        work = json.loads(manifest_path.read_text(encoding="utf-8")).get("work", {})
    base = {}
    base_path = root / "base.md"
    if base_path.exists():
        base_doc = parse_markdown(base_path)
        base = {
            "work_id": base_doc.frontmatter.get("selected_base_work_id", ""),
            "display_name": base_doc.frontmatter.get("selected_base_display_name", ""),
            "commit": base_doc.frontmatter.get("selected_base_commit", ""),
            "target_introduction_commit": base_doc.frontmatter.get("target_introduction_commit", ""),
            "target_introduction_kind": base_doc.frontmatter.get("target_introduction_kind", ""),
            "direction": base_doc.frontmatter.get("direction", ""),
            "confidence": base_doc.frontmatter.get("confidence", ""),
        }
    # Task selection must reflect the current evidence file, never a stale map.
    map_path = write_evidence_map(root)
    evidence_map = json.loads(map_path.read_text(encoding="utf-8"))
    base_context_evidence_ids = sorted(set(evidence_map.get("domains", {}).get("base_delta", [])))
    module_evidence = evidence_map.get("modules", {})
    map_by_id = evidence_map.get("map_by_id", {})
    module_doc_claim_evidence = {
        module_id: [
            evidence_id
            for evidence_id in evidence_ids
            if "doc_claim" in map_by_id.get(evidence_id, {}).get("conclusion_domains", [])
        ]
        for module_id, evidence_ids in module_evidence.items()
    }
    packets = make_task_files(
        work,
        base=base,
        base_context_evidence_ids=base_context_evidence_ids,
        module_evidence=module_evidence,
        module_doc_claim_evidence=module_doc_claim_evidence,
        node_evidence=evidence_map.get("nodes", {}),
    )
    out_dir = root / "case_state" / "task_files"
    out_dir.mkdir(parents=True, exist_ok=True)
    for packet in packets:
        (out_dir / f"{packet['task_id']}.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for packet in _role_task_files(work, evidence_map):
        (out_dir / f"{packet['task_id']}.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_dir


def build_scope(case_dir: str | Path) -> tuple[Path, Path]:
    root = Path(case_dir)
    manifest = _load_manifest(root)
    repo = Path(manifest["work"]["canonical_dir"])
    if not repo.is_absolute():
        repo = ROOT / repo
    commit = manifest["repo"]["commit"]
    files = git_text(repo, "ls-tree", "-r", "--name-only", commit).splitlines()
    buckets: dict[str, list[str]] = {
        "student_core": [],
        "framework_base": [],
        "third_party": [],
        "generated": [],
        "test_payload": [],
        "documentation": [],
        "unknown": [],
    }
    for rel in files:
        category = _classify_path(rel)
        buckets[category].append(rel)
    out_dir = root / "case_state"
    out_dir.mkdir(parents=True, exist_ok=True)
    scope_json = out_dir / "scope.json"
    scope_md = out_dir / "scope.md"
    payload = {"schema": "review_case.scope.v1", "commit": commit, "categories": buckets}
    scope_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Scope", "", f"Commit: `{commit}`", ""]
    for category, paths in buckets.items():
        lines.extend([f"## {category}", "", f"{len(paths)} paths", ""])
        lines.extend(f"- `{path}`" for path in paths[:80])
        lines.append("")
    scope_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return scope_json, scope_md


def build_fingerprint(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    manifest = _load_manifest(root)
    repo = Path(manifest["work"]["canonical_dir"])
    if not repo.is_absolute():
        repo = ROOT / repo
    commit = manifest["repo"]["commit"]
    cache_dir = write_fingerprint_cache(
        repo=repo,
        commit=commit,
        work_id=str(manifest["work"]["work_id"]),
        display_name=str(manifest["work"].get("display_name", "")),
        cache_root="fp_cache",
    )
    fp_manifest = {
        "schema": "review_case.fp_manifest.v1",
        "work_id": manifest["work"]["work_id"],
        "display_name": manifest["work"].get("display_name", ""),
        "commit": commit,
        "cache_dir": str(cache_dir.relative_to(ROOT) if cache_dir.is_relative_to(ROOT) else cache_dir),
        "blob": str((cache_dir / "target_blob.json").relative_to(ROOT) if (cache_dir / "target_blob.json").is_relative_to(ROOT) else cache_dir / "target_blob.json"),
        "structural": str((cache_dir / "target_ast.json").relative_to(ROOT) if (cache_dir / "target_ast.json").is_relative_to(ROOT) else cache_dir / "target_ast.json"),
    }
    out = root / "case_state" / "fp_manifest.json"
    out.write_text(json.dumps(fp_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def build_fingerprint_cache(works_path: str | Path = "config/works.yaml", cache_root: str | Path = "fp_cache", work_ids: list[str] | None = None) -> Path:
    selected = set(work_ids or [])
    index: list[dict[str, object]] = []
    for work in load_works(works_path):
        if selected and work.work_id not in selected:
            continue
        report = validate_work_identity(work)
        report.raise_for_errors()
        commit = git_text(work.repo_path, "rev-parse", work.review_branch)
        cache_dir = write_fingerprint_cache(work.repo_path, commit, work.work_id, work.display_name, cache_root)
        index.append(
            {
                "work_id": work.work_id,
                "display_name": work.display_name,
                "commit": commit,
                "cache_dir": str(cache_dir.relative_to(ROOT) if cache_dir.is_relative_to(ROOT) else cache_dir),
            }
        )
    cache_base = Path(cache_root)
    if not cache_base.is_absolute():
        cache_base = ROOT / cache_base
    cache_base.mkdir(parents=True, exist_ok=True)
    out = cache_base / "index.json"
    out.write_text(json.dumps({"schema": "review_case.fp_cache_index.v1", "items": index}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def search_base(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    out_dir = root / "case_state"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "base_candidates.json"
    return search_fingerprint_cache(
        out_dir / "fp_manifest.json",
        ROOT / "fp_cache" / "index.json",
        out,
    )


def build_evidence(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    manifest = _load_manifest(root)
    evidence_path = root / "evidence.jsonl"
    if evidence_path.exists():
        return evidence_path
    scope_path = root / "case_state" / "scope.json"
    fp_manifest_path = root / "case_state" / "fp_manifest.json"
    cards = []
    if scope_path.exists():
        cards.append(
            {
                "evidence_id": f"E{len(cards)+1:03d}",
                "kind": "artifact",
                "owner": "review",
                "display_owner": manifest["work"]["display_name"],
                "canonical_path": "case_state/scope.json",
                "commit": manifest["repo"]["commit"],
                "locator": "scope categories",
                "title": "Scope 分类产物",
                "excerpt": "Scope 将源码范围分为 student_core、third_party、generated、test_payload、documentation 和 unknown。",
                "supports": ["scope"],
                "confidence": "medium",
                "verified": True,
            }
        )
    if fp_manifest_path.exists():
        fp_manifest = json.loads(fp_manifest_path.read_text(encoding="utf-8"))
        cards.append(
            {
                "evidence_id": f"E{len(cards)+1:03d}",
                "kind": "artifact",
                "owner": "review",
                "display_owner": manifest["work"]["display_name"],
                "canonical_path": "case_state/fp_manifest.json",
                "commit": manifest["repo"]["commit"],
                "locator": str(fp_manifest.get("cache_dir", "")),
                "title": "目标仓库指纹缓存",
                "excerpt": "目标仓库源码 blob 指纹和结构指纹存放于 fp_cache，评审目录只记录缓存引用。",
                "supports": ["fingerprint"],
                "confidence": "medium",
                "verified": True,
            }
        )
    if not cards:
        cards.append(
            {
                "evidence_id": "E001",
                "kind": "artifact",
                "owner": "review",
                "display_owner": manifest["work"]["display_name"],
                "canonical_path": "case_state/manifest.json",
                "commit": manifest["repo"]["commit"],
                "locator": "manifest",
                "title": "评审版本锁定",
                "excerpt": "评审已锁定作品 commit 和 tree hash。",
                "supports": ["manifest"],
                "confidence": "medium",
                "verified": True,
            }
        )
    evidence_path.write_text("\n".join(json.dumps(card, ensure_ascii=False) for card in cards) + "\n", encoding="utf-8")
    digest = root / "case_state" / "evidence_digest.md"
    digest.write_text("# Evidence Digest\n\n" + "\n".join(f"- [@{card['evidence_id']}] {card['title']}: {card['excerpt']}" for card in cards) + "\n", encoding="utf-8")
    write_evidence_map(root)
    return evidence_path


def build_evidence_map(case_dir: str | Path) -> Path:
    return write_evidence_map(case_dir)


def _load_manifest(case_dir: Path) -> dict:
    path = case_dir / "case_state" / "manifest.json"
    if not path.exists():
        report = ValidationReport()
        report.add("case.manifest_missing", "run init before this stage", path)
        report.raise_for_errors()
    return json.loads(path.read_text(encoding="utf-8"))


def _role_task_files(work: dict, evidence_map: dict) -> list[dict]:
    agents = evidence_map.get("agents", {})
    return [
        {
            "task_id": "base-lineage-reviewer",
            "role": "base-lineage-reviewer",
            "work": {"work_id": work.get("work_id", ""), "display_name": work.get("display_name", "")},
            "evidence_ids": agents.get("base-lineage-reviewer", []),
            "conclusion_domains": ["base_identity", "source_lineage", "same_year_direction", "plagiarism_direction", "plagiarism_method", "external_dependency", "external_adaptation", "development_history", "scope_boundary"],
            "same_year_rule": "同届抄袭方向必须同时引用结构指纹/AST 相似热点 evidence 与 git 提交时间线 evidence；缺任一类只能写方向不确定。",
            "source_commit_rule": "主 Base、次级来源和外部模块必须定位目标作品中的最早可见引入 commit，核对 parent diff、文件/行数跳变与后续适配提交；若代码已存在于初始提交，只能报告历史上界，不得当作原创时间。",
            "context_policy": "只读 Base/来源/同届方向/时间线/外部依赖相关 evidence；不写模块实现细节。",
            "output_contract": "base_decision",
        },
        {
            "task_id": "doc-claim-reviewer",
            "role": "doc-claim-reviewer",
            "work": {"work_id": work.get("work_id", ""), "display_name": work.get("display_name", "")},
            "evidence_ids": agents.get("doc-claim-reviewer", []),
            "module_review_inputs": "modules/*.md 的 ## 文档声明复核",
            "conclusion_domains": ["doc_claim", "base_identity", "external_dependency", "module_design", "ai_usage", "development_history"],
            "context_policy": "reducer 角色，不重新全仓读代码；只汇总模块复核、doc evidence 和负向搜索 evidence。",
            "output_contract": "finding_set:doc_claim",
        },
        {
            "task_id": "history-ai-reviewer",
            "role": "history-ai-reviewer",
            "work": {"work_id": work.get("work_id", ""), "display_name": work.get("display_name", "")},
            "evidence_ids": agents.get("history-ai-reviewer", []),
            "conclusion_domains": ["development_history", "ai_usage", "work_amount", "same_year_direction", "plagiarism_direction", "plagiarism_method"],
            "context_policy": "聚焦 git 历史、AI 声明和生成痕迹；方向裁决交给 base-lineage-reviewer/contradiction-arbiter。",
            "output_contract": "finding_set:history_ai",
        },
        {
            "task_id": "cheat-detector",
            "role": "cheat-detector",
            "work": {"work_id": work.get("work_id", ""), "display_name": work.get("display_name", "")},
            "evidence_ids": agents.get("cheat-detector", []),
            "module_review_inputs": ["modules/build-config.md", "modules/process-management.md", "modules/user-abi-compat.md", "modules/kernel-services.md"],
            "conclusion_domains": ["cheat_risk", "prompt_injection"],
            "context_policy": "结合构建、进程执行、用户 ABI 和关机路径建立正常执行基线，再只读可疑 runner、测试特判和 prompt surface evidence；正常 runner/argv 不构成风险。",
            "source_commit_rule": "每个异常必须定位目标作品中的首次出现 commit，再与 Base/上游对比，区分选手新增、修改适配、未修改继承和来源不明。",
            "output_contract": "finding_set:cheat",
        },
        {
            "task_id": "report-editor",
            "role": "report-editor",
            "work": {"work_id": work.get("work_id", ""), "display_name": work.get("display_name", "")},
            "inputs": ["identity.md", "base.md", "modules/*.md", "findings/*.md", "issues/contradictions.md", "evidence.jsonl"],
            "context_policy": "只读已接受评审片段 和 evidence 索引；不读源码，不创造事实，不解决矛盾。",
            "output_contract": "assembled_report",
        },
    ]


def _classify_path(rel: str) -> str:
    parts = {part.lower() for part in Path(rel).parts}
    suffix = Path(rel).suffix
    if parts & GENERATED_PARTS:
        return "generated"
    if parts & THIRD_PARTY_PARTS:
        return "third_party"
    if parts & TEST_PARTS:
        return "test_payload"
    if suffix in DOC_SUFFIXES or "doc" in parts or "docs" in parts:
        return "documentation"
    if suffix in SOURCE_SUFFIXES or Path(rel).name in {"Makefile", "makefile", "Kconfig"}:
        return "student_core"
    return "unknown"
