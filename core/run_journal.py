from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any


class RunJournal:
    """Append-only debug artifacts with bounded in-memory counters."""

    FILES = {
        "trace": "agent_trace.jsonl",
        "llm_draft": "llm_node_drafts.jsonl",
        "verifier": "verifier_reports.jsonl",
        "blackboard": "blackboard_snapshots.jsonl",
        "llm_usage": "llm_usage.jsonl",
    }

    def __init__(self, output_dir: str | Path, *, resumed: bool):
        self.output_dir = Path(output_dir)
        self.lock = threading.Lock()
        self.counts = {name: 0 for name in self.FILES}
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not resumed:
            for filename in self.FILES.values():
                _atomic_write(self.output_dir / filename, "")

    def append(self, channel: str, row: dict[str, Any]) -> None:
        if channel not in self.FILES:
            raise KeyError(f"unknown journal channel: {channel}")
        line = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        with self.lock:
            with (self.output_dir / self.FILES[channel]).open("a", encoding="utf-8") as handle:
                handle.write(line)
            self.counts[channel] += 1
            if channel == "llm_usage":
                usage = row.get("usage") or row
                self.usage["calls"] += 1
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    self.usage[key] += int(usage.get(key) or 0)

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return {"counts": dict(self.counts), "usage": dict(self.usage)}


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
