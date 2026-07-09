from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ValidationReport

ALLOWED_EVIDENCE_KINDS = {
    "source_span",
    "doc_claim",
    "base_delta_summary",
    "git_history",
    "negative_search",
    "artifact",
    "risk_signal",
}
ALLOWED_CONFIDENCE = {"strong", "medium", "weak"}
EVIDENCE_ID_RE = re.compile(r"^E\d{3}$")


@dataclass(frozen=True)
class EvidenceCard:
    evidence_id: str
    kind: str
    owner: str
    display_owner: str
    canonical_path: str
    commit: str
    locator: str
    title: str
    excerpt: str
    supports: list[str]
    confidence: str
    verified: bool

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvidenceCard":
        return cls(
            evidence_id=str(raw.get("evidence_id", "")).strip(),
            kind=str(raw.get("kind", "")).strip(),
            owner=str(raw.get("owner", "")).strip(),
            display_owner=str(raw.get("display_owner", "")).strip(),
            canonical_path=str(raw.get("canonical_path", "")).strip(),
            commit=str(raw.get("commit", "")).strip(),
            locator=str(raw.get("locator", "")).strip(),
            title=str(raw.get("title", "")).strip(),
            excerpt=str(raw.get("excerpt", "")).strip(),
            supports=[str(x) for x in raw.get("supports", [])] if isinstance(raw.get("supports", []), list) else [],
            confidence=str(raw.get("confidence", "")).strip(),
            verified=bool(raw.get("verified", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "owner": self.owner,
            "display_owner": self.display_owner,
            "canonical_path": self.canonical_path,
            "commit": self.commit,
            "locator": self.locator,
            "title": self.title,
            "excerpt": self.excerpt,
            "supports": self.supports,
            "confidence": self.confidence,
            "verified": self.verified,
        }


def load_evidence(path: str | Path) -> tuple[dict[str, EvidenceCard], ValidationReport]:
    evidence_path = Path(path)
    report = ValidationReport()
    cards: dict[str, EvidenceCard] = {}
    if not evidence_path.exists():
        report.add("evidence.missing_file", "evidence.jsonl is missing", evidence_path)
        return cards, report
    for line_no, line in enumerate(evidence_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            report.add("evidence.invalid_json", f"line {line_no}: {exc}", evidence_path)
            continue
        card = EvidenceCard.from_dict(raw)
        line_path = f"{evidence_path}:{line_no}"
        if not EVIDENCE_ID_RE.match(card.evidence_id):
            report.add("evidence.invalid_id", "evidence_id must use E001 format", line_path)
        if card.evidence_id in cards:
            report.add("evidence.duplicate_id", f"duplicate evidence id {card.evidence_id}", line_path)
        if card.kind not in ALLOWED_EVIDENCE_KINDS:
            report.add("evidence.invalid_kind", f"invalid evidence kind {card.kind}", line_path)
        if card.confidence not in ALLOWED_CONFIDENCE:
            report.add("evidence.invalid_confidence", f"invalid confidence {card.confidence}", line_path)
        for field in ("owner", "display_owner", "title", "excerpt"):
            if not getattr(card, field):
                report.add("evidence.missing_field", f"{card.evidence_id} missing {field}", line_path)
        cards[card.evidence_id] = card
    expected = [f"E{i:03d}" for i in range(1, len(cards) + 1)]
    actual = sorted(cards)
    if actual and actual != expected:
        report.add("evidence.non_sequential", f"evidence ids must be sequential from E001; got {actual[:8]}", evidence_path)
    return cards, report
