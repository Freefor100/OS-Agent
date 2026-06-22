import unittest
from unittest.mock import patch
from core.scope import ScopeExclusion, ScopeManifest
from core.scoped_search import search_scoped
from core.snapshot import RepoSnapshot

def snap(repo,commit): return RepoSnapshot('s_'+commit,repo,'/'+repo,commit,'tree','main',[], '/tmp/'+repo)
def scope(repo,commit,excluded=()): return ScopeManifest('scope_'+repo,'s_'+commit,repo,commit,[],[ScopeExclusion(x,'external','test') for x in excluded],[],[],'verified')
def u(file,fp): return {'file':file,'fp':fp,'ast':fp,'lang':'c'}

class ScopedSearchTests(unittest.TestCase):
    def test_candidate_own_scope_changes_formal_score_and_missing_scope_is_rough(self):
        t=snap('target','t'); c=snap('candidate','c'); units={'/target':[u('kernel/a.c','shared'),u('vendor/v.c','vendored')],'/candidate':[u('kernel/a.c','shared'),u('vendor/v.c','vendored')]}
        with patch('core.scoped_search.build_units',side_effect=lambda path,snapshot: units[path]):
            formal=search_scoped(t,scope('target','t',['vendor/']),[(c,scope('candidate','c',['vendor/']))],formal_only=True)
            self.assertEqual(1.0,formal[0]['combined']); self.assertEqual('formal',formal[0]['score_kind'])
            self.assertEqual('scope_target', formal[0]['target_scope_id'])
            self.assertEqual('scope_candidate', formal[0]['candidate_scope_id'])
            self.assertEqual('candidate', formal[0]['candidate_snapshot']['repo'])
            rough=search_scoped(t,scope('target','t',['vendor/']),[(c,None)],formal_only=False)
            self.assertEqual('rough',rough[0]['score_kind']); self.assertEqual([],search_scoped(t,scope('target','t'),[(c,None)],formal_only=True))

    def test_root_directory_naming_is_consistent(self):
        from core.scoped_search import _overlap_by_dir
        units = [{'file': 'main.c', 'fp': 'abcd1234'}, {'file': 'kernel/a.c', 'fp': 'efgh5678'}]
        result = _overlap_by_dir(units, {'abcd1234'})
        self.assertIn('(root)', result)
        self.assertNotIn('.', result)
