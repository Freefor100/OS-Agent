import unittest
from pathlib import Path

from core.base_decision import build_base_evidence_packet, validate_base_decision
from core.scope import build_scope_manifest
from core.scoped_search import search_scoped
from core.snapshot import resolve_snapshot

ROOT=Path(__file__).resolve().parents[1]
HAS_REPOS=(ROOT/'repos/oskernel2023-zmz/.git').exists() and (ROOT/'repos/xv6-k210/.git').exists()

@unittest.skipUnless(HAS_REPOS,'real corpus repos not available')
class RealBaseDiscoveryRegression(unittest.TestCase):
    def test_expected_commits_and_declaration_blind_decision(self):
        target=resolve_snapshot(str(ROOT/'repos/oskernel2023-zmz'),'recover'); base=resolve_snapshot(str(ROOT/'repos/xv6-k210'),'scene')
        self.assertTrue(target.commit.startswith('837b6a9')); self.assertTrue(base.commit.startswith('d7f3e5e'))
        self.assertIn('origin/k210',target.ref_aliases); self.assertIn('origin/display',target.ref_aliases)
        ts=build_scope_manifest(target); bs=build_scope_manifest(base)
        self.assertIn('sbi/psicasbi/',ts.excluded_prefixes); self.assertIn('sbi/psicasbi/',bs.excluded_prefixes)
        rows=search_scoped(target,ts,[(base,bs)],formal_only=True); self.assertEqual(base.commit,rows[0]['commit']); self.assertEqual('formal',rows[0]['score_kind'])
        rows[0]['year']=2021
        decision={'primary_base':{'repo':base.repo,'commit':base.commit,'confidence':'high'},'decision_factors':{'formal_rank':1},'evidence_ids':['ev_formal']}
        normal=build_base_evidence_packet(target,rows,target_year=2023,include_declarations=True,candidate_coverage={"coverage_complete":True})
        blind=build_base_evidence_packet(target,rows,target_year=2023,include_declarations=False,candidate_coverage={"coverage_complete":True})
        self.assertFalse(validate_base_decision(decision,normal)); self.assertFalse(validate_base_decision(decision,blind)); self.assertFalse(blind['declared_sources'])
