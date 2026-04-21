from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PlanSpec:
    stage_id: str
    goal: str
    must_cover: List[str] = field(default_factory=list)
    evidence_targets: List[str] = field(default_factory=list)
    seed_paths: List[str] = field(default_factory=list)
    framework_guess: List[str] = field(default_factory=list)
    arch_guess: List[str] = field(default_factory=list)
    entry_symbols: List[str] = field(default_factory=list)
    repo_hotspots: List[str] = field(default_factory=list)
    preferred_tools: List[str] = field(default_factory=list)
    avoid_tools: List[str] = field(default_factory=list)
    context_budget: Dict[str, int] = field(default_factory=dict)
    # 须按序完成的执行步骤（Plan 阶段锁定，Execute 严格遵守，类似 Cursor 的 scoped plan）
    execution_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceItem:
    evidence_id: str
    claim_ids: List[str] = field(default_factory=list)
    path: str = ""
    symbol: Optional[str] = None
    lines: Optional[str] = None
    source_type: str = "source_code"
    confidence: str = "medium"
    excerpt: str = ""
    used_in_paragraphs: List[str] = field(default_factory=list)
    tool_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParagraphRecord:
    paragraph_id: str
    heading_path: List[str] = field(default_factory=list)
    text: str = ""
    claim_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DraftDocument:
    paragraphs: List[ParagraphRecord] = field(default_factory=list)
    claim_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "claim_map": self.claim_map,
        }

    def to_markdown(self) -> str:
        return "\n\n".join(p.text.strip() for p in self.paragraphs if p.text.strip()).strip()


@dataclass
class StageState:
    stage_id: str
    stage_title: str
    stage_type: str
    stage_prompt: str
    plan: Optional[PlanSpec] = None
    dynamic_context: Dict[str, Any] = field(default_factory=dict)
    draft_markdown: str = ""
    draft_document: Optional[DraftDocument] = None
    evidence_index: List[EvidenceItem] = field(default_factory=list)
    status: str = "init"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "stage_title": self.stage_title,
            "stage_type": self.stage_type,
            "stage_prompt": self.stage_prompt,
            "plan": self.plan.to_dict() if self.plan else None,
            "dynamic_context": self.dynamic_context,
            "draft_markdown": self.draft_markdown,
            "draft_document": self.draft_document.to_dict() if self.draft_document else None,
            "evidence_index": [e.to_dict() for e in self.evidence_index],
            "status": self.status,
            "metadata": self.metadata,
        }
