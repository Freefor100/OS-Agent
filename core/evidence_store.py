from __future__ import annotations

import json
import os
import threading
from typing import Dict, Iterable, List, Optional

from core.agent_graph_state import EvidenceRecord


class EvidenceStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._by_id: Dict[str, EvidenceRecord] = {}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self.path):
            return
        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = EvidenceRecord.from_dict(json.loads(line))
                    self._by_id[rec.evidence_id] = rec
                except Exception:
                    continue

    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        with self._lock:
            self._by_id[record.evidence_id] = record
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def extend(self, records: Iterable[EvidenceRecord]) -> List[EvidenceRecord]:
        out = []
        for record in records:
            out.append(self.append(record))
        return out

    def all(self) -> List[EvidenceRecord]:
        return list(self._by_id.values())

    def by_stage(self, stage_id: str) -> List[EvidenceRecord]:
        return [r for r in self._by_id.values() if r.stage_id == stage_id]

    def by_question(self, stage_id: str, question_id: Optional[str] = None) -> List[EvidenceRecord]:
        records = self.by_stage(stage_id)
        if question_id is None:
            return records
        return [r for r in records if question_id in (r.question_ids or [])]

    def grouped_by_question(self, stage_id: str) -> Dict[str, List[EvidenceRecord]]:
        with self._lock:
            all_records = list(self._by_id.values())
        grouped: Dict[str, List[EvidenceRecord]] = {}
        for rec in all_records:
            if rec.stage_id != stage_id:
                continue
            for qid in rec.question_ids or [""]:
                grouped.setdefault(qid, []).append(rec)
        return grouped
