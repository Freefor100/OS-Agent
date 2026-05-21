from core.agent_graph_state import EvidenceRecord, TaskSpec
from core.evidence_verifier import verify_evidence
from core.feature_schema_bank import evidence_can_support_claim
from core.task_agents import _records_from_react_output


NEG_POLICY = {
    "keywords": ["socket", "bind", "connect", "sendto", "recvfrom"],
    "seed_paths": ["kernel", "include", "Makefile"],
    "minimum_keyword_coverage": 0.7,
    "minimum_directory_coverage": 0.6,
}


def test_structured_negative_search_supports_not_found(tmp_path):
    rec = EvidenceRecord(
        evidence_id="ev_test",
        stage_id="08_network",
        question_ids=["Q08_001"],
        evidence_type="negative_search",
        source_type="search",
        excerpt="搜索 socket/bind/connect/sendto/recvfrom 后未发现实现入口",
        metadata={
            "negative_search": {
                "searched_keywords": ["socket", "bind", "connect", "sendto", "recvfrom"],
                "searched_directories": ["kernel", "include", "Makefile"],
                "match_count": 0,
                "coverage_sufficient": True,
            }
        },
    )

    verified = verify_evidence(
        rec,
        repo_path=str(tmp_path),
        required_evidence_types=["negative_search"],
        negative_search_policy=NEG_POLICY,
    )

    assert verified.strength == "strong"
    assert verified.validity == "valid"
    assert evidence_can_support_claim([verified], "not_found")


def test_structured_fact_results_synthesize_negative_search_record(tmp_path):
    task = TaskSpec(
        task_id="task_08_network_overview",
        stage_id="08_network",
        question_id="Q08_001",
        question_ids=["Q08_001"],
        expected_evidence_types=["definition", "negative_search"],
        metadata={"negative_search_policy": NEG_POLICY},
    )
    parsed = {
        "structured_fact_results": [
            {
                "fact_id": "Q08_001_06",
                "status_or_value": {
                    "searched_keywords": ["socket", "bind", "connect", "sendto", "recvfrom"],
                    "searched_directories": ["kernel", "include", "Makefile"],
                    "match_count": 0,
                    "coverage_sufficient": True,
                },
                "evidence_candidate_indexes": [],
                "notes": "负向搜索覆盖充分",
            }
        ],
        "evidence_candidates": [],
    }

    records = _records_from_react_output(task, str(tmp_path), parsed)

    assert len(records) == 1
    assert records[0].question_ids == ["Q08_001"]
    assert records[0].evidence_type == "negative_search"
    assert evidence_can_support_claim(records, "not_found")
