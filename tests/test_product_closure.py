import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from core.audit_manifest import create_audit_manifest, load_manifest
from core.evidence import EvidenceStore
from mcp_server import base_decision_submit


def _write_evidence(root: str, evidence_path: str, index: int) -> None:
    path = Path(root) / f"x{index}.c"
    path.write_text(f"int f{index}(void) {{ return {index}; }}\n", encoding="utf-8")
    EvidenceStore(root, evidence_path).add_source(
        kind="source_span",
        path=path.name,
        line=1,
        symbol=f"f{index}",
        metadata={"snapshot_commit": f"commit-{index}"},
    )


class ProductClosureTests(unittest.TestCase):
    def test_base_decision_submit_writes_artifact_and_updates_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = create_audit_manifest({"repo": "target", "commit": "target-commit"}, root)
            output = Path(root) / "base_decision.json"
            packet = {
                "candidate_coverage": {"coverage_complete": True},
                "formal_candidates": [{
                    "repo": "base", "commit": "base-commit", "score_kind": "formal",
                    "scope_status": "verified", "rank": 1, "year_direction": "older_to_target",
                }],
            }
            decision = {
                "primary_base": {"repo": "base", "commit": "base-commit", "confidence": "high"},
                "decision_factors": {"formal_rank": 1},
                "evidence_ids": ["ev_formal"],
            }
            result = base_decision_submit(decision, packet, str(output))
            self.assertTrue(result["valid"])
            self.assertTrue(output.is_file())
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(saved["valid"])
            updated = load_manifest(manifest["artifacts"]["audit_manifest"])
            self.assertTrue(updated["stages"]["base_decision_validated"])
            self.assertEqual(str(output), updated["artifacts"]["base_decision"])

    def test_base_decision_accepts_unique_commit_prefix_and_rejects_ambiguous_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "base_decision.json"
            packet = {
                "candidate_coverage": {"coverage_complete": True},
                "formal_candidates": [
                    {"repo": "base", "commit": "abcdef123456", "score_kind": "formal", "scope_status": "verified",
                     "rank": 1, "year_direction": "older_to_target"},
                    {"repo": "base", "commit": "abcdef999999", "score_kind": "formal", "scope_status": "verified",
                     "rank": 2, "year_direction": "older_to_target"},
                ],
            }
            decision = {"primary_base": {"repo": "base", "commit": "abcdef1"}, "decision_factors": {"formal_rank": 1},
                        "evidence_ids": ["ev_formal"]}
            result = base_decision_submit(decision, packet, str(output))
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual("abcdef123456", result["selected_candidate"]["commit"])

            bad = {"primary_base": {"repo": "base", "commit": "abcdef"}, "decision_factors": {}, "evidence_ids": ["ev"]}
            result = base_decision_submit(bad, packet, str(output))
            self.assertFalse(result["valid"])
            self.assertTrue(any("ambiguous" in error or "candidates=" in error for error in result["errors"]))

    def test_evidence_jsonl_append_is_safe_across_processes(self):
        with tempfile.TemporaryDirectory() as root:
            evidence = str(Path(root) / "evidence_store.jsonl")
            processes = [multiprocessing.Process(target=_write_evidence, args=(root, evidence, i)) for i in range(4)]
            for process in processes:
                process.start()
            for process in processes:
                process.join(10)
                self.assertEqual(0, process.exitcode)
            rows = list(EvidenceStore("", evidence).iter_full())
            self.assertEqual(4, len(rows))
            self.assertTrue(all(row.verified for row in rows))

    def test_file_artifact_evidence_is_verified_without_line_number(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "sbi-k210").write_bytes(b"binary")
            store = EvidenceStore(root)
            evidence_id = store.add_source(kind="binary_artifact", path="sbi-k210")
            record = store.by_id(evidence_id)
            self.assertTrue(record.verified)
            self.assertEqual(64, len(record.metadata["sha256"]))
            self.assertEqual(6, record.metadata["file_size"])

    def test_start_mcp_script_supports_project_venv_and_clear_error(self):
        text = Path("scripts/start_mcp.sh").read_text(encoding="utf-8")
        self.assertIn('${ROOT}/.venv/bin/python', text)
        self.assertIn('${ROOT}/venv/bin/python', text)
        self.assertIn('OS_AGENT_PYTHON', text)
        self.assertIn('README.md Quick Start', text)


if __name__ == "__main__":
    unittest.main()
