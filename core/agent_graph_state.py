from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class TaskSpec:
    task_id: str
    stage_id: str
    question_id: str = ""
    question_ids: List[str] = field(default_factory=list)
    task_type: str = "discovery"
    agent_type: str = ""
    task_goal: str = ""
    query: str = ""
    seed_paths: List[str] = field(default_factory=list)
    entry_symbols: List[str] = field(default_factory=list)
    tool_policy: Dict[str, Any] = field(default_factory=dict)
    expected_evidence_types: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    status: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not data.get("question_ids") and self.question_id:
            data["question_ids"] = [self.question_id]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSpec":
        payload = {k: data.get(k) for k in cls.__dataclass_fields__.keys() if k in data}
        if not payload.get("question_ids") and payload.get("question_id"):
            payload["question_ids"] = [payload["question_id"]]
        if not payload.get("question_id") and payload.get("question_ids"):
            payload["question_id"] = str(payload["question_ids"][0])
        return cls(**payload)


@dataclass
class TaskResult:
    task_id: str
    stage_id: str
    question_id: str = ""
    question_ids: List[str] = field(default_factory=list)
    status: str = "pending"
    evidence_ids: List[str] = field(default_factory=list)
    draft_answer_ids: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    confidence: str = "low"
    errors: List[str] = field(default_factory=list)
    token_usage: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not data.get("question_ids") and self.question_id:
            data["question_ids"] = [self.question_id]
        return data


@dataclass
class DraftAnswerRecord:
    draft_answer_id: str
    task_id: str
    stage_id: str
    question_id: str
    answer: Dict[str, Any] = field(default_factory=dict)
    used_evidence_ids: List[str] = field(default_factory=list)
    confidence: str = "low"
    status: str = "draft"
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DraftAnswerRecord":
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__.keys() if k in data})


@dataclass
class EvidenceRecord:
    evidence_id: str
    stage_id: str
    question_ids: List[str] = field(default_factory=list)
    task_id: str = ""
    path: str = ""
    symbol: Optional[str] = None
    lines: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    source_type: str = "source_code"
    evidence_type: str = "search"
    tool_name: Optional[str] = None
    confidence: str = "low"
    verifier_score: float = 0.0
    validity: str = "unverified"
    excerpt: str = ""
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceRecord":
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__.keys() if k in data})


@dataclass
class AgentEvent:
    event_id: str
    timestamp: str
    run_id: str
    stage_id: str = ""
    task_id: str = ""
    agent_name: str = ""
    event_type: str = "info"
    level: str = "info"
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    token_usage: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CDescribeHandoff:
    repo_name: str
    sections_dir: str
    fingerprint_ready: bool = False
    stage_quality: Dict[str, Any] = field(default_factory=dict)
    normalized_facts: Dict[str, Any] = field(default_factory=dict)
    evidence_summary: Dict[str, Any] = field(default_factory=dict)
    risk_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DescribeGraphState:
    run_id: str
    repo_name: str
    repo_path: str
    output_dir: str
    repo_profile: Dict[str, Any] = field(default_factory=dict)
    stage_order: List[str] = field(default_factory=list)
    current_stage: str = ""
    stage_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    task_queue: List[Dict[str, Any]] = field(default_factory=list)
    task_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    evidence_store: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    review_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    token_usage_total: Dict[str, int] = field(default_factory=dict)
    locks: Dict[str, Any] = field(default_factory=dict)
    status: str = "init"
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["updated_at"] = utcnow_iso()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DescribeGraphState":
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__.keys() if k in data})
