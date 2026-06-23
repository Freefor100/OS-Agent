import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.comparison import compare_unit_sets, write_comparison
from core.judge_report import (
    MODULE_IDS,
    create_judge_report,
    fork_judge_report_for_comparison,
    node_review_bundle_submit,
    validate_judge_report,
    write_judge_report,
)
from core.evidence import EvidenceCandidate, EvidenceStore
from core.kernel_tree import ANALYSIS_ORDER_V2
from core.provenance_report import export_provenance
from scripts.judge_report import render as render_judge
from scripts.provenance_report import render as render_provenance
from tools.code_atlas.minhash import signature_from_tokens


def unit(uid, name, tokens, file, snapshot):
    return {
        "unit_id": uid, "snapshot_id": snapshot, "name": name, "file": file, "line": 1, "end_line": 2,
        "lang": "c", "sz": len(tokens), "fp": "fp:" + " ".join(tokens), "ast": "shape:" + name,
        "sig": signature_from_tokens(tokens), "incoming_names": [], "outgoing_names": [],
    }


class JudgeReportTests(unittest.TestCase):
    def make_artifacts(self, root):
        Path(root, "work.c").write_text("int walk(void) {\n return 1;\n}\n", encoding="utf-8")
        target = [unit("t1", "walk", ["x"] * 20, "work.c", "st")]
        base = [unit("b1", "walk", ["x"] * 20, "work.c", "sb"), unit("b2", "removed", ["z"] * 20, "work.c", "sb")]
        result = compare_unit_sets(
            target, base,
            target_snapshot={"snapshot_id": "st", "repo": "oskernel2023-zmz", "commit": "target-commit", "materialized_path": root},
            base_snapshot={"snapshot_id": "sb", "repo": "xv6-k210", "commit": "base-commit", "materialized_path": root},
        )
        result["target_scope"] = {"scope_id": "ts"}
        result["base_scope"] = {"scope_id": "bs"}
        return write_comparison(result, root)

    def complete_report(self, root):
        artifacts = self.make_artifacts(root)
        evidence_path = Path(root, "evidence_store.jsonl")
        evidence = {
            "evidence_id": "ev_work", "verified": True, "strength": "strong", "tool": "source_reader",
            "kind": "source_span", "path": "work.c", "line_start": 1, "line_end": 2, "symbol": "walk",
            "label": "作品源码", "query": "", "excerpt": "1: int walk(void) {", "metadata": {"snapshot_commit": "target-commit"},
            "verifier_notes": ["verified"],
        }
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False) + "\n", encoding="utf-8")
        report = create_judge_report(comparison_database=artifacts["database"], evidence_store=str(evidence_path))
        for index, node_id in enumerate(ANALYSIS_ORDER_V2):
            claim_id = f"claim_{index}"
            report["claims"].append({
                "claim_id": claim_id, "node_id": node_id, "claim_type": "implementation", "verdict": "implemented",
                "statement": f"zmz 对 {node_id} 的实现已完成审阅。", "comparison_ids": [], "evidence_ids": ["ev_work"], "confidence": "medium",
            })
            report["node_reviews"].append({
                "node_id": node_id, "overview": f"zmz 中 {node_id} 的实现说明。",
                "difference_from_reference": f"已审阅 zmz 中 {node_id} 相比 xv6-k210 的实现差异。",
                "implementation_degree": {"level": "partial", "rationale": "已有源码支撑，完整性仍需结合运行结果复核。", "claim_ids": [claim_id]},
                "originality": {"level": "unknown", "rationale": "当前 Claim 不足以作更强原创度判断。", "claim_ids": [claim_id]},
                "claim_ids": [claim_id], "risks": [],
            })
        for module_id in MODULE_IDS:
            report["module_reviews"].append({
                "module_id": module_id, "overview": f"zmz 的 {module_id} 总体设计。",
                "difference_summary": "已按节点审阅与 xv6-k210 的实现差异。",
                "original_work_summary": "独立工作位置以节点 Claim 为准。",
                "implementation_summary": "模块实现情况由节点实现度综合呈现。",
                "featured_claim_ids": [],
                "key_chains": [{"title": "关键执行链", "explanation": "由节点实现共同支撑。",
                                "node_ids": [ANALYSIS_ORDER_V2[0]], "claim_ids": ["claim_0"], "evidence_ids": ["ev_work"]}],
            })
        report["overall_assessment"] = {
            "summary": "zmz 是在 xv6-k210 基础上演进的内核作品，需按模块审阅其继承、修改和独立工作。",
            "source_relation": "正式检索与双侧源码用于支撑来源关系，结论保持审慎。",
            "main_inherited": ["基础内核结构"],
            "main_modified": ["局部实现路径"],
            "main_independent": ["需由节点 Claim 逐项确认"],
            "incomplete_or_risks": ["运行行为尚需人工复核"],
            "review_focus": ["重点核对内存管理与设备驱动"],
            "architecture_edges": [{"from_module": MODULE_IDS[0], "to_module": MODULE_IDS[1], "label": "初始化与调用",
                                    "claim_ids": ["claim_0"]}],
        }
        return report, artifacts

    def test_complete_claim_driven_report_and_separate_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            report, artifacts = self.complete_report(root)
            self.assertEqual([], validate_judge_report(report, require_complete=True))
            page = render_judge(report)
            self.assertIn("总体结果与架构", page)
            self.assertIn("静态内核架构图", page)
            self.assertIn("证据 E001", page)
            self.assertIn("1: int walk", page)
            self.assertIn("函数级技术溯源附录", page)
            self.assertNotIn("Agent Claims", page)
            self.assertNotIn("Judge-facing assessment", page)
            self.assertNotIn("Scope：", page)
            for forbidden in ("target_only", "base_only", "MatchEdge", "RelationshipHint", "primary_base"):
                self.assertNotIn(forbidden, page)
            provenance_path = str(Path(root, "provenance.json"))
            export_provenance(artifacts["database"], provenance_path)
            provenance_page = render_provenance(json.loads(Path(provenance_path).read_text(encoding="utf-8")))
            self.assertIn("确定性函数对比概要", provenance_page)
            self.assertIn("xv6-k210 中存在、zmz 未找到确定性对应实现的函数", provenance_page)
            self.assertIn("walk", provenance_page)
            self.assertNotIn("Agent Claims", provenance_page)
            self.assertNotIn("RelationshipHint", provenance_page)

    def test_complete_validation_rejects_missing_node(self):
        with tempfile.TemporaryDirectory() as root:
            report, _ = self.complete_report(root)
            missing = ANALYSIS_ORDER_V2[-1]
            report["node_reviews"] = [x for x in report["node_reviews"] if x["node_id"] != missing]
            errors = validate_judge_report(report, require_complete=True)
            self.assertIn(f"missing node review {missing}", errors)

    def test_comparison_claim_requires_bilateral_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            report, _ = self.complete_report(root)
            report["claims"][0]["claim_type"] = "difference"
            report["claims"][0]["verdict"] = "inherited_modified"
            errors = validate_judge_report(report, require_complete=False)
            self.assertTrue(any("requires bilateral source evidence" in x for x in errors))

    def test_concurrent_node_bundles_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as root:
            report, _ = self.complete_report(root)
            report["claims"] = []; report["node_reviews"] = []; report["module_reviews"] = []; report["overall_assessment"] = {}
            report_path = str(Path(root, "report.json")); write_judge_report(report, report_path)
            def submit(index):
                node_id = ANALYSIS_ORDER_V2[index]; claim_id = f"parallel_{index}"
                claim = {"claim_id": claim_id, "node_id": node_id, "claim_type": "implementation", "verdict": "implemented",
                         "statement": f"{node_id} 已审阅。", "comparison_ids": [], "evidence_ids": ["ev_work"], "confidence": "medium"}
                review = {"node_id": node_id, "overview": "已有实现。", "difference_from_reference": "差异已审阅。",
                          "implementation_degree": {"level": "partial", "rationale": "有源码。", "claim_ids": [claim_id]},
                          "originality": {"level": "unknown", "rationale": "证据不足。", "claim_ids": [claim_id]},
                          "claim_ids": [claim_id], "risks": []}
                node_review_bundle_submit(report_path, node_id, [claim], review)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(submit, [0, 1]))
            saved = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertEqual(2, len(saved["claims"])); self.assertEqual(2, len(saved["node_reviews"]))

    def test_node_bundle_auto_binds_generated_claims_and_rejects_stale_generation(self):
        with tempfile.TemporaryDirectory() as root:
            report, _ = self.complete_report(root)
            report["claims"] = []; report["node_reviews"] = []; report["module_reviews"] = []; report["overall_assessment"] = {}
            report_path = str(Path(root, "report.json")); write_judge_report(report, report_path)
            node_id = ANALYSIS_ORDER_V2[0]
            claim = {"claim_type": "implementation", "verdict": "implemented", "statement": "已有源码支撑。",
                     "comparison_ids": [], "evidence_ids": ["ev_work"], "confidence": "medium"}
            review = {"overview": "已有实现。", "difference_from_reference": "差异已审阅。",
                      "implementation_degree": {"level": "partial", "rationale": "有源码。"},
                      "originality": {"level": "unknown", "rationale": "证据不足。"},
                      "claim_ids": ["missing"], "risks": []}
            with self.assertRaisesRegex(ValueError, "stale report generation"):
                node_review_bundle_submit(report_path, node_id, [claim], review, expected_generation="old")
            result = node_review_bundle_submit(report_path, node_id, [claim], review,
                                               expected_generation=report["report_generation"])
            claim_id = result["claims"][0]["claim_id"]
            self.assertEqual([claim_id], result["review"]["claim_ids"])
            self.assertEqual([claim_id], result["review"]["implementation_degree"]["claim_ids"])
            self.assertEqual([claim_id], result["review"]["originality"]["claim_ids"])

    def test_validate_reports_schema_errors_instead_of_attribute_crash(self):
        with tempfile.TemporaryDirectory() as root:
            report, _ = self.complete_report(root)
            report["claims"].append("bad")
            report["node_reviews"].append("bad")
            report["module_reviews"].append({"module_id": MODULE_IDS[0], "overview": "x", "difference_summary": "x",
                                             "original_work_summary": "x", "implementation_summary": "x",
                                             "key_chains": ["bad"]})
            report["overall_assessment"] = "bad"
            errors = validate_judge_report(report, require_complete=True)
            self.assertTrue(any("claims" in error and "object" in error for error in errors))
            self.assertTrue(any("overall_assessment must be object" in error for error in errors))

    def test_render_keeps_evidence_inside_bound_node_only(self):
        with tempfile.TemporaryDirectory() as root:
            report, _ = self.complete_report(root)
            other = {
                "evidence_id": "ev_other", "verified": True, "strength": "strong", "tool": "source_reader",
                "kind": "source_span", "path": "other.c", "line_start": 1, "line_end": 2, "symbol": "other",
                "label": "另一处源码", "query": "", "excerpt": "1: int other(void) {}", "metadata": {"snapshot_commit": "target-commit"},
                "verifier_notes": ["verified"],
            }
            with Path(report["evidence_store"]).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(other, ensure_ascii=False) + "\n")
            report["claims"][1]["evidence_ids"] = ["ev_other"]
            page = render_judge(report)
            first = page.index(f'data-panel="node:{ANALYSIS_ORDER_V2[0]}"')
            second = page.index(f'data-panel="node:{ANALYSIS_ORDER_V2[1]}"')
            first_panel = page[first:second]
            self.assertNotIn("另一处源码", first_panel)
            self.assertNotIn("Evidence 源码与审计记录", page)

    def test_forked_report_preserves_text_but_blocks_complete_render_until_rebound(self):
        with tempfile.TemporaryDirectory() as root:
            report, artifacts = self.complete_report(root)
            report_path = Path(root, "old_report.json")
            write_judge_report(report, str(report_path))
            forked = fork_judge_report_for_comparison(str(report_path), comparison_database=artifacts["database"],
                                                      evidence_store=report["evidence_store"])
            self.assertEqual(report["node_reviews"][0]["overview"], forked["node_reviews"][0]["overview"])
            self.assertEqual("needs_rebind", forked["claims"][0]["migration_status"])
            errors = validate_judge_report(forked, require_complete=True)
            self.assertTrue(any("requires evidence/comparison rebind" in error for error in errors))

    def test_evidence_jsonl_is_shared_across_snapshot_roots(self):
        with tempfile.TemporaryDirectory() as root:
            a = Path(root, "a"); b = Path(root, "b"); a.mkdir(); b.mkdir()
            Path(a, "x.c").write_text("int a(void) {}\n", encoding="utf-8")
            Path(b, "x.c").write_text("int b(void) {}\n", encoding="utf-8")
            evidence = str(Path(root, "evidence.jsonl"))
            EvidenceStore(str(a), evidence).add_source(kind="source_span", path="x.c", line=1, metadata={"snapshot_commit": "a"})
            EvidenceStore(str(b), evidence).add_source(kind="source_span", path="x.c", line=1, metadata={"snapshot_commit": "b"})
            self.assertEqual(2, len(list(EvidenceStore("", evidence).iter_full())))

    def test_invalid_document_is_not_verified(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "broken.pdf").write_text("not a pdf", encoding="utf-8")
            store = EvidenceStore(root)
            evidence_id = store.add(EvidenceCandidate(tool="documentation", kind="documentation", path="broken.pdf", label="broken"))
            self.assertFalse(store.by_id(evidence_id).verified)

    def test_docx_document_is_verified_and_excerpted(self):
        import docx
        with tempfile.TemporaryDirectory() as root:
            document = docx.Document(); document.add_paragraph("设计文档中的关键架构说明")
            document.save(Path(root, "design.docx"))
            store = EvidenceStore(root)
            evidence_id = store.add(EvidenceCandidate(tool="documentation", kind="documentation", path="design.docx", label="设计文档"))
            record = store.by_id(evidence_id)
            self.assertTrue(record.verified); self.assertIn("关键架构说明", record.excerpt)


if __name__ == "__main__":
    unittest.main()
