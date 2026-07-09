#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.review_case.assembler import assemble_report
from core.review_case.compiler import compile_report
from core.review_case.contracts import ValidationReport
from core.review_case.identity import find_work, validate_work_identity
from core.review_case.site_data import build_index, build_report_html
from core.review_case.validators import validate_case_dir
from core.review_case.case_steps import build_evidence, build_evidence_map, build_fingerprint, build_fingerprint_cache, build_scope, init_by_work_id, write_task_files, search_base


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


def cmd_assemble(args: argparse.Namespace) -> int:
    report = assemble_report(args.case_dir)
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
    report = assemble_report(args.case_dir)
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


def cmd_write_task_files(args: argparse.Namespace) -> int:
    try:
        print(write_task_files(args.case_dir))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_build_index(args: argparse.Namespace) -> int:
    try:
        print(build_index(args.case_dirs, args.output))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_scope(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_scope(args.case_dir)[0])


def cmd_fingerprint(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_fingerprint(args.case_dir))


def cmd_build_fp_cache(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_fingerprint_cache(args.works, args.cache_root, args.work_id))


def cmd_search_base(args: argparse.Namespace) -> int:
    return _print_path(lambda: search_base(args.case_dir))


def cmd_build_evidence(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_evidence(args.case_dir))


def cmd_build_evidence_map(args: argparse.Namespace) -> int:
    return _print_path(lambda: build_evidence_map(args.case_dir))


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
    p = sub.add_parser("scope")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_scope)
    p = sub.add_parser("fingerprint")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_fingerprint)
    p = sub.add_parser("build-fp-cache")
    p.add_argument("--works", default="config/works.yaml")
    p.add_argument("--cache-root", default="fp_cache")
    p.add_argument("--work-id", action="append")
    p.set_defaults(func=cmd_build_fp_cache)
    p = sub.add_parser("search-base")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_search_base)
    p = sub.add_parser("build-evidence")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_build_evidence)
    p = sub.add_parser("build-evidence-map")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_build_evidence_map)
    p = sub.add_parser("make-task-files")
    p.add_argument("--case-dir", required=True)
    p.set_defaults(func=cmd_write_task_files)
    p = sub.add_parser("validate")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("assemble")
    p.add_argument("--case-dir", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_assemble)
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
