from __future__ import annotations

import json
import os
import threading
from typing import Dict, Iterable, List, Optional

from core.agent_graph_state import DraftAnswerRecord


class DraftAnswerStore:
    """Append-only JSONL store for question-bound Task Agent answer drafts."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._by_id: Dict[str, DraftAnswerRecord] = {}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = DraftAnswerRecord.from_dict(json.loads(line))
                    self._by_id[rec.draft_answer_id] = rec
                except Exception:
                    continue

    def append(self, record: DraftAnswerRecord) -> DraftAnswerRecord:
        with self._lock:
            if record.draft_answer_id in self._by_id:
                return self._by_id[record.draft_answer_id]
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
            self._by_id[record.draft_answer_id] = record
            return record

    def extend(self, records: Iterable[DraftAnswerRecord]) -> List[DraftAnswerRecord]:
        return [self.append(r) for r in records]

    def all(self) -> List[DraftAnswerRecord]:
        return list(self._by_id.values())

    def by_stage(self, stage_id: str) -> List[DraftAnswerRecord]:
        return [r for r in self._by_id.values() if r.stage_id == stage_id]

    def by_question(self, stage_id: str, question_id: Optional[str] = None) -> List[DraftAnswerRecord]:
        records = [r for r in self._by_id.values() if r.stage_id == stage_id]
        if question_id:
            records = [r for r in records if r.question_id == question_id]
        return records

    def grouped_by_question(self, stage_id: str) -> Dict[str, List[DraftAnswerRecord]]:
        grouped: Dict[str, List[DraftAnswerRecord]] = {}
        for rec in self.by_stage(stage_id):
            grouped.setdefault(rec.question_id, []).append(rec)
        return grouped
