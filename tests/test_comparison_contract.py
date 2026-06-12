import unittest
from core.comparison import compare_unit_sets
from tools.code_atlas.minhash import signature_from_tokens


def unit(uid, name, tokens, path="kernel/x.c", ast=""):
    return {"unit_id":uid,"name":name,"file":path,"line":1,"end_line":2,"lang":"c","sz":len(tokens),"fp":"fp:"+" ".join(tokens),"ast":ast,"sig":signature_from_tokens(tokens),"incoming_names":[],"outgoing_names":[]}

class ComparisonContractTests(unittest.TestCase):
    def test_exact_rename_added_removed(self):
        target=[unit("t1","same",["a","b"]),unit("t2","newname",["x","y"]),unit("t3","added",["n","e","w"])]
        base=[unit("b1","same",["a","b"]),unit("b2","oldname",["x","y"]),unit("b3","removed",["o","l","d"])]
        s=compare_unit_sets(target,base)["summary"]
        self.assertEqual(1,s["exact_copied"]); self.assertEqual(1,s["renamed_exact"]); self.assertEqual(1,s["target_only"]); self.assertEqual(1,s["base_only"])
    def test_modified_candidate_and_ambiguous(self):
        modified=compare_unit_sets([unit("t","walk",["a"]*20,"kernel/mm.c","shape")],[unit("b","walk",["b"]*20,"kernel/mm.c","shape")])["summary"]
        self.assertEqual(1,modified["modified_candidate"])
        target=unit("t","new",["a"]*20,"kernel/mm.c","shape")
        b1=unit("b1","old1",["b"]*20,"kernel/mm.c","shape"); b2=unit("b2","old2",["c"]*20,"kernel/mm.c","shape")
        b1["sig"]=target["sig"]; b2["sig"]=target["sig"]
        ambiguous=compare_unit_sets([target],[b1,b2])["summary"]
        self.assertEqual(1,ambiguous["ambiguous"])

    def test_same_name_unrelated_is_not_modified(self):
        rows=compare_unit_sets([unit("t","walk",["alpha"]*20,"a/x.c")],[unit("b","walk",["omega"]*20,"z/y.c")])["comparisons"]
        self.assertNotIn("modified_candidate", {x["raw_status"] for x in rows})


    def test_same_name_same_path_high_call_context_can_be_modified(self):
        target=unit("t","pipewrite",["alpha"]*20,"kernel/fs/pipe.c"); base=unit("b","pipewrite",["omega"]*20,"kernel/fs/pipe.c")
        target["outgoing_names"]=["sleep","wakeup","copyin"]; base["outgoing_names"]=["sleep","wakeup","copyin"]
        rows=compare_unit_sets([target],[base])["comparisons"]
        self.assertEqual("modified_candidate",rows[0]["raw_status"])
