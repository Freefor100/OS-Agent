from __future__ import annotations

import unittest

from agent_c import _score


def _index(*, tags, modules, flows, deps, ast, claim_prefix):
    quality = {}
    bindings = {}
    for index, tag in enumerate(tags):
        claim_id = f"{claim_prefix}_{index}"
        quality[tag] = {"claim_id": claim_id}
        bindings[claim_id] = [{"ast_shape_hash": ast[index % len(ast)]}]
    return {
        "design_layer": {
            "primary_claim_tags": tags,
            "display_tags": [],
            "absence_tags": [],
            "module_presence": modules,
            "tag_quality": quality,
        },
        "relation_layer": {
            "flow_signatures": flows,
            "dependency_signatures": deps,
        },
        "code_structure_layer": {
            "ast_shape_hashes": ast,
            "normalized_token_fingerprints": ast,
            "call_edge_fingerprints": ast,
            "type_macro_usage_fingerprints": [],
            "semantic_fn_ids": ast,
            "claim_code_bindings": bindings,
        },
        "lineage_layer": {
            "node_status": {row.rsplit(":", 1)[0]: row.rsplit(":", 1)[1] for row in modules},
        },
    }


class AgentCCompareTests(unittest.TestCase):
    def test_base_coverage_survives_extension_tag_renames_and_target_additions(self):
        base = _index(
            tags=[
                "MemoryManagement.PhysicalAllocator:extension:free_list_implemented",
                "MemoryManagement.PageTable:sv39_three_level_page_table",
                "ProcessManagement.Scheduler:round_robin_scheduler_impl",
            ],
            modules=[
                "MemoryManagement.PhysicalAllocator:implemented",
                "MemoryManagement.PageTable:implemented",
                "ProcessManagement.Scheduler:implemented",
            ],
            flows=["scheduler>swtch>yield", "walk>mappages>satp"],
            deps=[
                "MemoryManagement.PageTable->MemoryManagement.PhysicalAllocator:allocates_pages",
                "ProcessManagement.Scheduler->Synchronization.SpinLock:protects_proc",
            ],
            ast=["a", "b", "c"],
            claim_prefix="base",
        )
        target = _index(
            tags=[
                "MemoryManagement.PhysicalAllocator:free_list_physical_allocator",
                "MemoryManagement.PageTable:sv39_three_level_page_table",
                "ProcessManagement.Scheduler:round_robin_scheduler",
                "FileSystem.ConcreteFS.FAT32:fat32_cluster_chain",
            ],
            modules=[
                "MemoryManagement.PhysicalAllocator:implemented",
                "MemoryManagement.PageTable:implemented",
                "ProcessManagement.Scheduler:implemented",
                "FileSystem.ConcreteFS.FAT32:implemented",
            ],
            flows=["scheduler loop>swtch>yield process", "walk page table>mappages>satp switch"],
            deps=[
                "MemoryManagement.PageTable->MemoryManagement.PhysicalAllocator:uses_allocator",
                "ProcessManagement.Scheduler->Synchronization.SpinLock:uses_lock",
            ],
            ast=["a", "b", "x"],
            claim_prefix="target",
        )
        score = _score(target, base)
        self.assertGreater(score["design_claim_score"], 0.75)
        self.assertGreater(score["architecture_relation_score"], 0.75)
        self.assertGreater(score["code_structure_score"], 0.55)
        self.assertEqual(1.0, score["lineage_prior_score"])
        self.assertGreater(score["derivation_strength"], 0.75)


if __name__ == "__main__":
    unittest.main()
