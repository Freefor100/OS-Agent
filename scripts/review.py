#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.review_case.compiler import compile_report
from core.review_case.contracts import ValidationReport
from core.review_case.evidence import (
    capture_commit,
    capture_comparison,
    capture_document,
    capture_search,
    capture_search_result,
    capture_span,
)
from core.review_case.identity import find_work, validate_work_identity
from core.review_case.site_data import build_index, build_report_html
from core.review_case.validators import contradiction_check, validate_case_dir, validate_fragment
from core.review_case.case_steps import (
    build_evidence,
    build_fingerprint,
    build_fingerprint_cache,
    build_inventory,
    compare_commits,
    init_by_work_id,
    search_head_candidates,
    search_history_blobs,
)


def cmd_identity_check(args: argparse.Namespace) -> int:
    work = find_work(args.work_id, args.works)
    report = ValidationReport()
    if not work:
        report.add("identity.unknown_work", f"work_id not found: {args.work_id}")
    else:
        report.extend(validate_work_identity(work))
    return _print_report(report, args.json)


def cmd_init(args: argparse.Namespace) -> int:
    try:
        case_dir = init_by_work_id(args.work_id, args.works, args.output_root)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(case_dir)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate_case_dir(args.case_dir)
    return _print_report(report, args.json)


def cmd_compile(args: argparse.Namespace) -> int:
    try:
        print(compile_report(args.case_dir))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_build_site(args: argparse.Namespace) -> int:
    try:
        print(build_report_html(args.case_dir))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_check_all(args: argparse.Namespace) -> int:
    report = validate_case_dir(args.case_dir)
    if not report.ok:
        return _print_report(report, args.json)
    try:
        compile_report(args.case_dir)
        build_report_html(args.case_dir)
    except Exception as exc:
        final = ValidationReport()
        final.add("case.check_all_failed", str(exc))
        return _print_report(final, args.json)
    final_report = validate_case_dir(args.case_dir)
    return _print_report(final_report, args.json)


def cmd_validate_fragment(args: argparse.Namespace) -> int:
    return _print_report(validate_fragment(args.case_dir, args.path), args.json)


def cmd_build_index(args: argparse.Namespace) -> int:
    try:
        print(build_index(args.case_dirs, args.output))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_inventory(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_inventory(args.case_dir)[0])


def cmd_fingerprint(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_fingerprint(args.case_dir))


def cmd_build_fp_cache(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_fingerprint_cache(args.works, args.cache_root, args.work_id))


def cmd_search_head_candidates(args: argparse.Namespace) -> int:
    return _print_path(lambda: search_head_candidates(args.case_dir, args.works, args.cache_root))


def cmd_compare_commits(args: argparse.Namespace) -> int:
    return _print_path(
        lambda: compare_commits(
            args.left_work,
            args.left_commit,
            args.right_work,
            args.right_commit,
            works_path=args.works,
            cache_root=args.cache_root,
            include_ast=args.ast,
            output_path=args.output,
        )
    )


def cmd_search_history_blobs(args: argparse.Namespace) -> int:
    return _print_path(
        lambda: search_history_blobs(
            args.target_work,
            args.target_commit,
            works_path=args.works,
            cache_root=args.cache_root,
            top_k=args.top_k,
            target_prefixes=args.target_prefix,
            output_path=args.output,
        )
    )


def cmd_build_evidence(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_evidence(args.case_dir))


def _source_kwargs(args: argparse.Namespace) -> dict:
    return {
        "work_id": getattr(args, "work_id", None),
        "repo": getattr(args, "repo", None),
        "display_name": getattr(args, "display_name", None),
        "external_id": getattr(args, "external_id", None),
        "works_path": getattr(args, "works", "config/works.yaml"),
    }


def cmd_evidence_span(args: argparse.Namespace) -> int:
    return _print_path(
        lambda: capture_span(
            Path(args.case_dir),
            title=args.title,
            commit=args.commit,
            path=args.path,
            lines=args.lines,
            **_source_kwargs(args),
        )
    )


def cmd_evidence_document(args: argparse.Namespace) -> int:
    return _print_path(
        lambda: capture_document(
            Path(args.case_dir),
            title=args.title,
            commit=args.commit,
            path=args.path,
            file_path=Path(args.file) if args.file else None,
            page=args.page,
            paragraph=args.paragraph,
            lines=args.lines,
            **_source_kwargs(args),
        )
    )


def cmd_evidence_commit(args: argparse.Namespace) -> int:
    return _print_path(
        lambda: capture_commit(
            Path(args.case_dir),
            title=args.title,
            commit=args.commit,
            paths=args.path or [],
            **_source_kwargs(args),
        )
    )


def cmd_evidence_comparison(args: argparse.Namespace) -> int:
    return _print_path(
        lambda: capture_comparison(
            Path(args.case_dir),
            title=args.title,
            fact_file=Path(args.file),
        )
    )


def cmd_evidence_search(args: argparse.Namespace) -> int:
    if args.file:
        if args.work_id or args.repo or args.commit or args.pattern or args.path:
            print("--file 不能与 Git 检索参数同时使用", file=sys.stderr)
            return 1
        return _print_path(
            lambda: capture_search_result(
                Path(args.case_dir),
                title=args.title,
                fact_file=Path(args.file),
            )
        )
    if not (args.commit and args.pattern and (args.work_id or args.repo)):
        print("直接检索必须指定来源、--commit 和 --pattern", file=sys.stderr)
        return 1
    return _print_path(
        lambda: capture_search(
            Path(args.case_dir),
            title=args.title,
            commit=args.commit,
            pattern=args.pattern,
            paths=args.path or [],
            **_source_kwargs(args),
        )
    )


def cmd_contradiction_check(args: argparse.Namespace) -> int:
    return _print_path(lambda: contradiction_check(args.case_dir))


def _print_path(fn) -> int:
    try:
        print(fn())
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _print_report(report: ValidationReport, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.format())
    return 0 if report.ok else 1


def _add_git_source(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    source = parser.add_mutually_exclusive_group(required=required)
    source.add_argument("--work-id")
    source.add_argument("--repo")
    parser.add_argument("--display-name", help="使用 --repo 时必填")
    parser.add_argument("--external-id")
    parser.add_argument("--works", default="config/works.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OS-Agent work review commands")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("identity-check")
    p.add_argument("--work-id", required=True)
    p.add_argument("--works", default="config/works.yaml")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_identity_check)
    p = sub.add_parser("init")
    p.add_argument("--work-id", required=True)
    p.add_argument("--works", default="config/works.yaml")
    p.add_argument("--output-root", default="output")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("inventory")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_inventory)
    p = sub.add_parser("fingerprint")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_fingerprint)
    p = sub.add_parser("build-fp-cache")
    p.add_argument("--works", default="config/works.yaml")
    p.add_argument("--cache-root", default="fp_cache")
    p.add_argument("--work-id", action="append")
    p.set_defaults(func=cmd_build_fp_cache)
    p = sub.add_parser("search-head-candidates")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--works", default="config/works.yaml")
    p.add_argument("--cache-root", default="fp_cache")
    p.set_defaults(func=cmd_search_head_candidates)
    p = sub.add_parser("compare-commits")
    p.add_argument("--left-work", required=True)
    p.add_argument("--left-commit", required=True)
    p.add_argument("--right-work", required=True)
    p.add_argument("--right-commit", required=True)
    p.add_argument("--works", default="config/works.yaml")
    p.add_argument("--cache-root", default="fp_cache")
    p.add_argument("--ast", action="store_true", help="build AST only for this selected commit pair")
    p.add_argument("--output")
    p.set_defaults(func=cmd_compare_commits)
    p = sub.add_parser("search-history-blobs")
    p.add_argument("--target-work", required=True)
    p.add_argument("--target-commit", required=True)
    p.add_argument("--works", default="config/works.yaml")
    p.add_argument("--cache-root", default="fp_cache")
    p.add_argument("--top-k", type=int, default=30)
    p.add_argument("--target-prefix", action="append", help="limit target blob occurrences to a core source path; repeatable")
    p.add_argument("--output")
    p.set_defaults(func=cmd_search_history_blobs)
    p = sub.add_parser("build-evidence")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_build_evidence)
    evidence = sub.add_parser("evidence", help="固定 Agent 选中的事实位置")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    p = evidence_sub.add_parser("span", help="固定 Git commit 中的源码或文本行")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--lines", required=True, help="START 或 START:END")
    _add_git_source(p)
    p.set_defaults(func=cmd_evidence_span)
    p = evidence_sub.add_parser("document", help="固定 PDF、DOCX 或文本中的文档内容")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--commit")
    p.add_argument("--path")
    p.add_argument("--file", help="不在 Git 中的本地 PDF、DOCX 或文本文件")
    p.add_argument("--page", type=int)
    p.add_argument("--paragraph", type=int)
    p.add_argument("--lines", help="PDF 页内或文本文件中的 START:END")
    _add_git_source(p)
    p.set_defaults(func=cmd_evidence_document)
    p = evidence_sub.add_parser("commit", help="固定提交元数据和路径统计")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--path", action="append", help="只统计指定路径，可重复")
    _add_git_source(p)
    p.set_defaults(func=cmd_evidence_commit)
    p = evidence_sub.add_parser("comparison", help="固定 commit 对 Blob/AST 比较摘要")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_evidence_comparison)
    p = evidence_sub.add_parser("search", help="固定 Git 检索或候选检索结果")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--file", help="search-head-candidates 或 search-history-blobs 的 JSON 结果")
    p.add_argument("--commit")
    p.add_argument("--pattern")
    p.add_argument("--path", action="append", help="限定 Git 检索路径，可重复")
    _add_git_source(p, required=False)
    p.set_defaults(func=cmd_evidence_search)
    p = sub.add_parser("contradiction-check", help="确认仲裁覆盖当前全部调查材料")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_contradiction_check)
    p = sub.add_parser("validate")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("validate-fragment")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate_fragment)
    p = sub.add_parser("compile")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_compile)
    p = sub.add_parser("build-site")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_build_site)
    p = sub.add_parser("check-all")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check_all)
    p = sub.add_parser("build-index")
    p.add_argument("--output", required=True)
    p.add_argument("case_dirs", nargs="+")
    p.set_defaults(func=cmd_build_index)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
