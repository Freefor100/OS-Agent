from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from core.agent_d_graph import AgentDGraphRuntime, compact_existing_checkpoint, run_langgraph
from core.evidence import EvidenceStore
from core.kernel_tree import ANALYSIS_ORDER_V2
from core.node_react_agent import DeepSeekChatOpenAI, NodeDraft, run_node_react_agent
from core.node_analysis_graph import NodeAnalysisRuntime, run_node_analysis_graph
from core.run_recorder import RunRecorder


class AgentDLangGraphTests(unittest.TestCase):
    def setUp(self):
        self.old_limit = os.environ.get("AGENT_D_NODE_LIMIT")
        os.environ["AGENT_D_NODE_LIMIT"] = "3"

    def tearDown(self):
        if self.old_limit is None:
            os.environ.pop("AGENT_D_NODE_LIMIT", None)
        else:
            os.environ["AGENT_D_NODE_LIMIT"] = self.old_limit

    def runtime(self, output: Path, calls: list[str], fail_node: str = "") -> AgentDGraphRuntime:
        recorder = RunRecorder(str(output), "fake", 3, run_id="test-run")

        def analyze(node_id, snapshot):
            calls.append(node_id)
            if node_id == fail_node:
                raise RuntimeError("injected failure")
            return {
                "node_id": node_id,
                "node": {"node_id": node_id, "status": "implemented", "claim_ids": [], "evidence_ids": []},
                "claim_count": 1,
                "evidence_count": 1,
            }

        def finalize():
            index = output / "index.html"
            index.write_text("<!doctype html>", encoding="utf-8")
            return {"index_html": str(index)}

        return AgentDGraphRuntime(
            repo_name="fake",
            output_dir=output,
            recorder=recorder,
            snapshot=lambda: {"stable": True},
            analyze_node=analyze,
            merge_results=lambda results: None,
            trace_flows=lambda: None,
            build_dependencies=lambda: None,
            global_consistency=lambda: None,
            finalize=finalize,
            persist_debug=lambda: None,
        )

    def test_fanout_fanin_and_sqlite_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            calls: list[str] = []
            result = run_langgraph(self.runtime(output, calls), input_hash="hash", run_id="test-run", resumed=False)
            self.assertEqual("complete", result["run_status"])
            self.assertEqual(3, len(result["completed_node_ids"]))
            self.assertEqual(3, len(calls))
            self.assertTrue((output / "checkpoints.sqlite").is_file())
            tree = __import__("json").loads((output / "kernel_design_tree.json").read_text(encoding="utf-8"))
            self.assertEqual("in_progress", tree["run_status"])
            self.assertEqual(3, len(tree["_incremental_nodes"]))
            self.assertEqual({}, result["pending_node_results"])
            self.assertEqual({}, result["node_run_states"])
            conn = sqlite3.connect(output / "checkpoints.sqlite")
            try:
                checkpoint_bytes = conn.execute(
                    "select coalesce(sum(length(checkpoint)), 0) from checkpoints"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertLess(checkpoint_bytes, 2 * 1024 * 1024)

    def test_failed_node_is_the_only_node_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            first_calls: list[str] = []
            first = run_langgraph(
                self.runtime(output, first_calls, fail_node="BuildAndConfig.MakeTargets"),
                input_hash="hash",
                run_id="test-run",
                resumed=False,
            )
            self.assertEqual("failed", first["run_status"])
            second_calls: list[str] = []
            second = run_langgraph(self.runtime(output, second_calls), input_hash="hash", run_id="test-run", resumed=True)
            self.assertEqual("complete", second["run_status"])
            self.assertEqual(["BuildAndConfig.MakeTargets"], second_calls)

    def test_resume_from_compacted_per_node_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            first_calls: list[str] = []
            first = run_langgraph(
                self.runtime(output, first_calls, fail_node="BuildAndConfig.MakeTargets"),
                input_hash="hash",
                run_id="test-run",
                resumed=False,
            )
            self.assertEqual("failed", first["run_status"])
            compacted = compact_existing_checkpoint(output, "test-run")
            self.assertEqual("compacted", compacted["status"])
            second_calls: list[str] = []
            second = run_langgraph(self.runtime(output, second_calls), input_hash="hash", run_id="test-run", resumed=True)
            self.assertEqual("complete", second["run_status"])
            self.assertEqual(["BuildAndConfig.MakeTargets"], second_calls)

    def test_completed_result_is_reused_without_node_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            first_calls: list[str] = []
            first = run_langgraph(self.runtime(output, first_calls), input_hash="hash", run_id="test-run", resumed=False)
            self.assertEqual("complete", first["run_status"])
            second_calls: list[str] = []
            second = run_langgraph(self.runtime(output, second_calls), input_hash="hash", run_id="test-run", resumed=True)
            self.assertTrue(second["reused"])
            self.assertEqual([], second_calls)

    def test_evidence_store_recovers_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            source = repo / "x.c"
            source.write_text("void walk(void) {}\n", encoding="utf-8")
            path = Path(tmp) / "evidence.jsonl"
            first = EvidenceStore(str(repo), str(path))
            evidence_id = first.add_source(kind="function_definition", path="x.c", line=1, symbol="walk")
            second = EvidenceStore(str(repo), str(path))
            self.assertIn(evidence_id, second.records)
            self.assertEqual(evidence_id, second.add_source(kind="function_definition", path="x.c", line=1, symbol="walk"))
            self.assertEqual(1, len(second.records))

    def test_evidence_store_keeps_excerpts_on_disk_with_bounded_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            source = repo / "x.c"
            source.write_text("\n".join(f"void fn_{index}(void) {{}}" for index in range(180)), encoding="utf-8")
            store = EvidenceStore(str(repo), str(Path(tmp) / "evidence.jsonl"))
            for index in range(180):
                store.add_source(kind="function_definition", path="x.c", line=index + 1, symbol=f"fn_{index}")
            self.assertEqual(180, len(store.records))
            self.assertLessEqual(len(store.cache), store.cache_limit)
            self.assertTrue(all(not record.excerpt for record in store.records.values()))
            self.assertIn("fn_0", store.by_id(next(iter(store.records))).excerpt)

    def test_child_blackboard_does_not_copy_or_multiply_extension_history(self):
        from agent_d import Blackboard, _fork_blackboard, _merge_node_results

        with tempfile.TemporaryDirectory() as tmp:
            bb = Blackboard(
                repo_path=tmp,
                repo_name="fake",
                output_dir=tmp,
                concepts={},
                vocab={},
                glossary={},
                build={},
                atlas={},
                evidence=EvidenceStore(tmp),
                nodes={"Metadata": {"node_id": "Metadata", "status": "unknown", "claim_ids": [], "evidence_ids": []}},
                extension_requests=[{"node_id": "Metadata", "tag": "existing"}],
            )
            child = _fork_blackboard(bb, {})
            self.assertEqual([], child.extension_requests)
            duplicate = {"node_id": "Metadata", "tag": "new"}
            _merge_node_results(bb, [{
                "node_id": "Metadata",
                "node": {"node_id": "Metadata", "status": "implemented", "claim_ids": [], "evidence_ids": []},
                "claims": [],
                "dependencies": [],
                "flows": [],
                "extension_requests": [duplicate, duplicate],
            }])
            self.assertEqual(2, len(bb.extension_requests))

    def test_node_draft_schema_is_strictly_structured(self):
        draft = NodeDraft.model_validate({
            "status": "implemented",
            "claims": [{
                "canonical_tag": "sv39_three_level_page_table",
                "statement_zh": "使用 Sv39 三级页表。",
                "statement_en": "Uses an Sv39 three-level page table.",
                "evidence_ids": ["ev_1"],
            }],
        })
        self.assertEqual("implemented", draft.status)
        self.assertEqual("sv39_three_level_page_table", draft.claims[0].canonical_tag)

    def test_run_recorder_concurrent_flush_is_serialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = RunRecorder(tmp, "fake", 3, run_id="r")
            errors: list[Exception] = []

            def write(node_id):
                try:
                    for index in range(12):
                        recorder.graph_event("parallel", node_id=node_id, phase="tool", data={"active_tool": f"tool-{index}"})
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=write, args=(f"node-{index}",)) for index in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual([], errors)
            self.assertTrue((Path(tmp) / "tool_calls.jsonl").is_file())
            for index in range(520):
                recorder.event("bounded", {"index": index})
            self.assertEqual(500, len(recorder.events))
            self.assertGreaterEqual(len((Path(tmp) / "run_events.jsonl").read_text(encoding="utf-8").splitlines()), 520)
            recorder.flush()
            self.assertLessEqual(len((Path(tmp) / "run_events_tail.jsonl").read_text(encoding="utf-8").splitlines()), 500)

    def test_run_recorder_evicts_completed_node_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = RunRecorder(tmp, "fake", 3, run_id="r")
            node_id = ANALYSIS_ORDER_V2[0]
            recorder.set_node(node_id)
            recorder.graph_event("react", node_id=node_id, phase="react", data={"react_step": 2})
            self.assertIn(node_id, recorder.node_stats)

            recorder.node_done(node_id, claim_count=3, evidence_count=5)
            status = json.loads((Path(tmp) / "run_status.json").read_text(encoding="utf-8"))

            self.assertEqual("done", status["node_states"][node_id])
            self.assertNotIn(node_id, recorder.node_stats)
            self.assertNotIn(node_id, status["node_run_states"])
            self.assertIn(node_id, (Path(tmp) / "run_events.jsonl").read_text(encoding="utf-8"))

    def test_langchain_node_agent_calls_tool_then_submits_node_draft(self):
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langgraph.checkpoint.memory import InMemorySaver

        class FakeToolModel(BaseChatModel):
            calls: int = 0

            @property
            def _llm_type(self):
                return "fake-tool-model"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    message = AIMessage(content="", tool_calls=[{
                        "name": "read_symbol",
                        "args": {"symbol": "walk"},
                        "id": "tool-1",
                        "type": "tool_call",
                    }])
                else:
                    message = AIMessage(content="", tool_calls=[{
                        "name": "NodeDraft",
                        "args": {
                            "status": "implemented",
                            "claims": [{
                                "canonical_tag": "sv39_three_level_page_table",
                                "statement_zh": "使用 Sv39 三级页表。",
                                "statement_en": "Uses an Sv39 three-level page table.",
                                "evidence_ids": ["ev_1"],
                            }],
                        },
                        "id": "structured-1",
                        "type": "tool_call",
                    }])
                return ChatResult(generations=[ChatGeneration(message=message)])

        original = DeepSeekChatOpenAI.build
        requests: list[dict] = []
        saver = InMemorySaver()
        DeepSeekChatOpenAI.build = staticmethod(lambda: FakeToolModel())
        try:
            draft = run_node_react_agent(
                node_id="MemoryManagement.PageTable",
                node_context={"concept_card": {}, "candidate_vocab": {}},
                execute_request=lambda request, phase: requests.append(request) or {"added_evidence_ids": ["ev_1"]},
                checkpointer=saver,
                thread_id="test/nodes/page-table",
            )
        finally:
            DeepSeekChatOpenAI.build = original
        self.assertEqual("implemented", draft["status"])
        self.assertEqual("read_symbol", requests[0]["tool"])
        self.assertIsNone(saver.get({"configurable": {"thread_id": "test/nodes/page-table"}}))

    def test_langchain_node_agent_forces_commit_when_model_forgets_submit_tool(self):
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        class ForgetfulModel(BaseChatModel):
            calls: int = 0

            @property
            def _llm_type(self):
                return "forgetful-model"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self.calls += 1
                content = "探索结束但忘记提交。" if self.calls == 1 else '{"status":"unknown","confidence":"low","claims":[]}'
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

        model = ForgetfulModel()
        original = DeepSeekChatOpenAI.build
        DeepSeekChatOpenAI.build = staticmethod(lambda: model)
        try:
            draft = run_node_react_agent(
                node_id="FileSystem.PageCacheIntegration",
                node_context={"concept_card": {}, "candidate_vocab": {}},
                execute_request=lambda request, phase: {},
                thread_id="test/nodes/page-cache",
            )
        finally:
            DeepSeekChatOpenAI.build = original
        self.assertEqual("unknown", draft["status"])
        self.assertEqual(2, model.calls)

    def test_langchain_node_agent_forces_commit_when_react_budget_exhausts(self):
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        class EndlessExplorerModel(BaseChatModel):
            calls: int = 0

            @property
            def _llm_type(self):
                return "endless-explorer-model"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self.calls += 1
                if any("NodeCommitter" in str(getattr(message, "content", "")) for message in messages):
                    message = AIMessage(content='{"status":"unknown","confidence":"low","claims":[]}')
                else:
                    message = AIMessage(content="", tool_calls=[{
                        "name": "grep",
                        "args": {"query": "copy"},
                        "id": f"tool-{self.calls}",
                        "type": "tool_call",
                    }])
                return ChatResult(generations=[ChatGeneration(message=message)])

        model = EndlessExplorerModel()
        original_build = DeepSeekChatOpenAI.build
        old_steps = os.environ.get("AGENT_D_REACT_MAX_STEPS")
        os.environ["AGENT_D_REACT_MAX_STEPS"] = "4"
        DeepSeekChatOpenAI.build = staticmethod(lambda: model)
        try:
            draft = run_node_react_agent(
                node_id="MemoryManagement.CopyUser",
                node_context={"concept_card": {}, "candidate_vocab": {}},
                execute_request=lambda request, phase: {"tool": request["tool"], "added_evidence_ids": []},
                thread_id="test/nodes/copy-user",
            )
        finally:
            DeepSeekChatOpenAI.build = original_build
            if old_steps is None:
                os.environ.pop("AGENT_D_REACT_MAX_STEPS", None)
            else:
                os.environ["AGENT_D_REACT_MAX_STEPS"] = old_steps
        self.assertEqual("unknown", draft["status"])

    def test_node_subgraph_checkpoints_verifier_repair_and_commit(self):
        from langgraph.checkpoint.memory import InMemorySaver

        attempts: list[int] = []
        cleaned: list[int] = []
        committed: list[dict] = []

        def react(errors, attempt):
            attempts.append(attempt)
            return {"status": "implemented", "claims": [{"canonical_tag": "x"}]}

        def verify(draft, attempt):
            return {"errors": ["missing evidence"] if attempt == 1 else []}

        result = run_node_analysis_graph(
            run_id="test",
            node_id="MemoryManagement.PageTable",
            runtime=NodeAnalysisRuntime(
                react=react,
                verify=verify,
                commit=lambda draft, attempt: committed.append(draft) or {"ok": True},
                cleanup_attempt=cleaned.append,
            ),
            checkpointer=InMemorySaver(),
            max_attempts=3,
        )
        self.assertEqual("done", result["status"])
        self.assertEqual([0, 1], attempts)
        self.assertEqual([0, 1], cleaned)
        self.assertEqual(1, len(committed))


if __name__ == "__main__":
    unittest.main()
