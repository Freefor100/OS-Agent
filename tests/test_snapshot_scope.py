import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.scope import build_scope_manifest, path_in_scope, verified_exclusion_errors
from core.snapshot import branch_tip_snapshots, default_snapshot, discover_commit_snapshots, resolve_snapshot


class SnapshotScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = os.getcwd(); os.chdir(self.tmp.name)
        self.repo = Path("sample"); self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "T"], check=True)
        (self.repo / "kernel").mkdir(); (self.repo / "kernel/a.c").write_text("int a(){return 1;}\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True); subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "one"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "branch", "alias-one"], check=True)
    def tearDown(self): os.chdir(self.old); self.tmp.cleanup()
    def test_aliases_merge_and_dirty_tree_ignored(self):
        snaps = discover_commit_snapshots(str(self.repo)); self.assertEqual(1, len(snaps)); self.assertIn("alias-one", snaps[0].ref_aliases)
        snap = resolve_snapshot(str(self.repo)); (self.repo / "kernel/a.c").write_text("DIRTY\n")
        self.assertIn("return 1", (Path(snap.materialized_path) / "kernel/a.c").read_text())
        self.assertEqual(f"sample@{snap.canonical_branch}", snap.to_dict()["display_name"])
        self.assertNotIn("materialized_path", snap.to_public_dict())
        self.assertNotIn("repo_path", snap.to_public_dict())
    def test_default_is_checked_out_tip_and_branch_tips_exclude_history(self):
        first = default_snapshot(str(self.repo), materialize=False)
        (self.repo / "kernel/a.c").write_text("int a(){return 2;}\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "two"], check=True)
        current = default_snapshot(str(self.repo), materialize=False)
        subprocess.run(["git", "-C", str(self.repo), "branch", "-f", "alias-one", current.commit], check=True)
        tips = branch_tip_snapshots(str(self.repo), materialize=False)
        self.assertNotEqual(first.commit, current.commit)
        self.assertEqual(current.commit, tips[0]["commit"])
        self.assertTrue(tips[0]["is_default"])
        self.assertNotIn(first.commit, [row["commit"] for row in tips])
    def test_scope_filters_excluded_path(self):
        snap = resolve_snapshot(str(self.repo)); scope = build_scope_manifest(snap, included_prefixes=["kernel/"], excluded=[{"prefix":"kernel/generated/","category":"generated","reason":"test"}])
        self.assertTrue(path_in_scope("kernel/a.c", scope)); self.assertFalse(path_in_scope("kernel/generated/x.c", scope))
    def test_supplied_submodule_evidence_is_merged(self):
        (self.repo / ".gitmodules").write_text('[submodule "vendor"]\n  path = vendor\n  url = https://example.invalid/vendor\n'); (self.repo / "vendor").mkdir()
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True); subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "submodule declaration"], check=True)
        snap=resolve_snapshot(str(self.repo)); scope=build_scope_manifest(snap,excluded=[{"prefix":"vendor/","category":"external_submodule","reason":"Agent verified","evidence_ids":["ev_1"]}])
        self.assertEqual(["ev_1"],next(x for x in scope.excluded if x.prefix=="vendor/").evidence_ids)
    def test_verified_scope_requires_evidence_for_agent_exclusions_and_draft_allows(self):
        snap = resolve_snapshot(str(self.repo))
        verified = build_scope_manifest(snap, excluded=[{"prefix":"kernel/","category":"agent_excluded","reason":"reviewed"}])
        self.assertIn("requires evidence_ids", "; ".join(verified_exclusion_errors(verified)))
        draft = build_scope_manifest(snap, excluded=[{"prefix":"kernel/","category":"agent_excluded","reason":"reviewed"}], status="draft")
        self.assertEqual([], verified_exclusion_errors(draft))
        with_evidence = build_scope_manifest(snap, excluded=[{"prefix":"kernel/","category":"agent_excluded","reason":"reviewed","evidence_ids":["ev_ok"]}])
        self.assertEqual([], verified_exclusion_errors(with_evidence, {"ev_ok": {"verified": True}}))
        self.assertIn("unverified", "; ".join(verified_exclusion_errors(with_evidence, {"ev_ok": {"verified": False}})))
