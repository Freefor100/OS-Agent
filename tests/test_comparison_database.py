import tempfile
import unittest
from pathlib import Path

from core.comparison import build_match_edges, compare_unit_sets, write_comparison
from core.comparison_db import (add_secondary_source, base_only_files, comparisons_by_status, directory_sources, directory_summary,
                                file_functions, file_sources, function_candidates, overview, relationship_hints, search_units,
                                source_file_targets, source_group)
from tools.code_atlas.minhash import signature_from_tokens


def unit(uid, name, tokens, file, snapshot):
    return {"unit_id":uid,"snapshot_id":snapshot,"name":name,"file":file,"line":1,"end_line":2,"lang":"c","sz":len(tokens),
            "fp":"fp:"+" ".join(tokens),"ast":"shape:"+name,"sig":signature_from_tokens(tokens),"incoming_names":[],"outgoing_names":[]}

class ComparisonDatabaseTests(unittest.TestCase):
    def make_db(self, root):
        target=[unit("t1","a",["x"]*20,"kernel/merged.c","st"),unit("t2","b",["y"]*20,"kernel/merged.c","st")]
        base=[unit("b1","a",["x"]*20,"kernel/one.c","sb"),unit("b2","b",["y"]*20,"kernel/two.c","sb"),unit("b3","removed",["z"]*20,"kernel/deleted.c","sb")]
        result=compare_unit_sets(target,base,target_snapshot={"snapshot_id":"st","repo":"target","materialized_path":root},base_snapshot={"snapshot_id":"sb","repo":"base","materialized_path":root})
        result["target_scope"]={"scope_id":"ts"}; result["base_scope"]={"scope_id":"bs"}
        return write_comparison(result,root),target
    def test_multi_source_file_and_reverse_queries(self):
        with tempfile.TemporaryDirectory() as d:
            artifacts,_=self.make_db(d); db=artifacts["database"]
            sources=file_sources(db,"kernel/merged.c"); self.assertEqual(2,len(sources["source_files"])); self.assertEqual(0.5,sources["source_files"][0]["affinity"])
            reverse=source_file_targets(db,"base","kernel/one.c"); self.assertEqual("kernel/merged.c",reverse["target_files"][0]["target_file"])
            source_dir=directory_summary(db,"kernel/","source"); self.assertEqual(2,source_dir["source_file_count"]); self.assertIn("source_files",source_dir)
            functions=file_functions(db,"kernel/merged.c",limit=1); self.assertEqual(2,functions["total"]); self.assertEqual(1,len(functions["rows"]))
            self.assertEqual(1,search_units(db,"a")["total"])
            self.assertEqual(2,comparisons_by_status(db,"exact_copied")["total"])
            self.assertEqual(2,directory_sources(db,"kernel/")["total"])
            hints=relationship_hints(db,"multi_file_affinity"); self.assertEqual(1,hints["total"])
            hint=hints["rows"][0]; self.assertEqual({"t1","t2"},set(hint["target_unit_ids"])); self.assertEqual({"b1","b2"},set(hint["source_unit_ids"])); self.assertEqual(2,len(source_group(db,hint["hint_id"])["sources"]))
            deleted=base_only_files(db); self.assertEqual(1,deleted["total"]); self.assertEqual("kernel/deleted.c",deleted["rows"][0]["base_file"]); self.assertEqual(["removed"],deleted["rows"][0]["symbols"])
    def test_secondary_source_edges_do_not_change_primary_summary(self):
        with tempfile.TemporaryDirectory() as d:
            artifacts,target=self.make_db(d); db=artifacts["database"]; before=overview(db)["summary"]
            secondary=[unit("s1","a",["x"]*20,"secondary/a.c","ss")]; edges=build_match_edges(target,secondary,source_role="secondary_source",source_repo="secondary")
            add_secondary_source(db,{"snapshot_id":"ss","repo":"secondary","materialized_path":d},secondary,edges)
            self.assertEqual(before,overview(db)["summary"]); self.assertTrue(function_candidates(db,"t1","secondary_source")["rows"])
