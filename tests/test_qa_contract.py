from __future__ import annotations

import importlib

from core.describe_stage_qa import load_stage_qa
from core.qa_contract import (
    collect_feature_ids,
    feature_by_question,
    feature_context_for_question,
    features_for_stage_qa,
    negative_search_policy_for_question,
    required_evidence_types_for_question,
)


STAGE_IDS = [
    "02_boot_trap",
    "03_mem_mgmt",
    "04_process_smp",
    "05_fs_drivers",
    "06_sync_ipc",
    "07_security",
    "08_network",
    "09_debug_error",
]


def test_retired_schema_module_is_removed() -> None:
    try:
        importlib.import_module("core." + "feature_" + "schema_" + "bank")
    except ModuleNotFoundError:
        return
    raise AssertionError("retired schema helper module must not be importable")


def test_qa_contract_reads_only_authored_question_fields() -> None:
    question = {
        "question_id": "Q99_001",
        "stem": "authored stem",
        "feature_ids": ["feat_a", "feat_a", "feat_b"],
        "concept_boundary": "authored boundary",
        "structured_facts": [{"fact_id": "F1", "fact_key": "fact"}],
        "evidence_policy": {
            "required_evidence_types": ["definition", "definition", "negative_search"],
            "negative_search_policy": {"keywords": ["needle"]},
        },
    }

    assert collect_feature_ids(question) == ["feat_a", "feat_b"]
    assert required_evidence_types_for_question(question) == ["definition", "negative_search"]
    assert negative_search_policy_for_question(question) == {"keywords": ["needle"]}
    assert feature_context_for_question(question)["structured_facts"] == question["structured_facts"]

    empty_question = {"question_id": "Q99_002", "stem": "missing authored metadata"}
    assert collect_feature_ids(empty_question) == []
    assert required_evidence_types_for_question(empty_question) == []
    assert negative_search_policy_for_question(empty_question) == {}
    assert feature_context_for_question(empty_question)["structured_facts"] == []


def test_stage_qa_contracts_are_consistent() -> None:
    seen_question_ids: set[str] = set()
    total = 0
    for stage_id in STAGE_IDS:
        stage_qa = load_stage_qa(stage_id)
        features = features_for_stage_qa(stage_qa)
        assert isinstance(features, list)
        features_by_question = feature_by_question(stage_qa)

        for question in stage_qa.get("questions", []):
            total += 1
            qid = question["question_id"]
            assert qid not in seen_question_ids
            seen_question_ids.add(qid)
            assert qid in features_by_question

            if question.get("question_type") == "tri_state_impl":
                allowed = question.get("tri_state_rule", {}).get("allowed_values")
                assert allowed == ["implemented", "stub", "not_found", "unknown"]
                assert question.get("answer_contract", {}).get("final_type") == "enum"
                assert question.get("answer_contract", {}).get("allowed_final_values") == [
                    "implemented",
                    "stub",
                    "not_found",
                    "unknown",
                ]
            if question.get("question_type") == "short_answer":
                assert question.get("answer_contract", {}).get("final_type") != "enum"

            fact_ids = [
                fact.get("fact_id")
                for fact in question.get("structured_facts", [])
                if isinstance(fact, dict) and fact.get("fact_id")
            ]
            for fact in question.get("structured_facts", []):
                if isinstance(fact, dict) and fact.get("answer_type") == "enum":
                    assert isinstance(fact.get("allowed_values"), list)

            required_fact_ids = question.get("answer_contract", {}).get("required_fact_ids", [])
            if required_fact_ids:
                assert required_fact_ids == fact_ids

            feature_matches = features_by_question[qid]
            assert len(feature_matches) == 1
            feature = feature_matches[0]
            assert feature.get("description") == question.get("stem")
            assert feature.get("concept_boundary") == question.get("concept_boundary")
            assert feature.get("answer_contract", {}).get("required_fact_ids", []) == fact_ids
            assert feature.get("structured_facts") == question.get("structured_facts")

            fact_text = " ".join(
                str(fact.get("question", ""))
                for fact in question.get("structured_facts", [])
                if isinstance(fact, dict)
            )
            task_hint_fact_text = " ".join(
                str(fact.get("question", ""))
                for fact in question.get("task_hints", {}).get("structured_facts", [])
                if isinstance(fact, dict)
            )
            assert "围绕 " not in fact_text
            assert "收集可复现证据" not in fact_text
            assert "围绕 " not in task_hint_fact_text
            assert "收集可复现证据" not in task_hint_fact_text

    assert total == 201


def test_multi_status_questions_are_not_single_tri_state() -> None:
    multi_status_question_ids = {
        "Q04_014",
        "Q06_008",
        "Q06_019",
        "Q07_008",
        "Q07_011",
        "Q08_007",
    }
    by_id = {}
    for stage_id in STAGE_IDS:
        for question in load_stage_qa(stage_id).get("questions", []):
            by_id[question["question_id"]] = question

    for qid in multi_status_question_ids:
        question = by_id[qid]
        assert question["question_type"] == "short_answer"
        assert question["answer_contract"]["final_type"] == "structured_text"
        assert "allowed_final_values" not in question["answer_contract"]


def test_audit_table_covers_every_question() -> None:
    audit_path = "core/describe_stage_qa/AUDIT_02_09.md"
    with open(audit_path, encoding="utf-8") as audit_file:
        audit_text = audit_file.read()

    question_ids = []
    for stage_id in STAGE_IDS:
        for question in load_stage_qa(stage_id).get("questions", []):
            question_ids.append(question["question_id"])

    for qid in question_ids:
        assert f"| {qid} |" in audit_text
    assert "- Total questions: 201" in audit_text
    assert "- rewritten: 201" in audit_text
    assert "- remaining_generic_facts: 0" in audit_text
