from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any, Dict, Optional

from core.agent_graph_state import AgentEvent, utcnow_iso


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


class EventLogger:
    def __init__(self, run_id: str, state_dir: str):
        self.run_id = run_id
        self.state_dir = state_dir
        self.events_path = os.path.join(state_dir, "events.jsonl")
        self.mode = (os.environ.get("OS_AGENT_TERMINAL_MODE") or "compact").strip().lower()
        self.preview_chars = _env_int("OS_AGENT_EVENT_PREVIEW_CHARS", 180)
        self._lock = threading.Lock()
        os.makedirs(state_dir, exist_ok=True)

    def emit(
        self,
        event_type: str,
        message: str,
        *,
        stage_id: str = "",
        task_id: str = "",
        agent_name: str = "",
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
        token_usage: Optional[Dict[str, int]] = None,
    ) -> AgentEvent:
        event = AgentEvent(
            event_id=str(uuid.uuid4()),
            timestamp=utcnow_iso(),
            run_id=self.run_id,
            stage_id=stage_id,
            task_id=task_id,
            agent_name=agent_name,
            event_type=event_type,
            level=level,
            message=message,
            metadata=metadata or {},
            token_usage=token_usage or {},
        )
        with self._lock:
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self._render(event)
        return event

    def _render(self, event: AgentEvent) -> None:
        if self.mode == "silent" and event.event_type not in {
            "run_start",
            "run_resume",
            "run_done",
            "stage_start",
            "stage_done",
            "stage_error",
            "task_error",
        }:
            return
        if self.mode == "compact" and event.event_type in {"llm_start", "llm_done"}:
            return
        msg = (event.message or "").replace("\n", " ")
        if len(msg) > self.preview_chars:
            msg = msg[: self.preview_chars - 3] + "..."
        prefix_parts = []
        if event.stage_id:
            prefix_parts.append(event.stage_id.split("_", 1)[0])
        if event.task_id and self.mode == "verbose":
            prefix_parts.append(event.task_id)
        if event.agent_name:
            prefix_parts.append(event.agent_name)
        prefix = "[" + "][".join(prefix_parts) + "]" if prefix_parts else "[run]"
        if self.mode == "verbose" and event.metadata:
            meta = json.dumps(event.metadata, ensure_ascii=False)
            if len(meta) > self.preview_chars:
                meta = meta[: self.preview_chars - 3] + "..."
            print(f"{prefix} {event.event_type}: {msg} {meta}", flush=True)
        else:
            print(f"{prefix} {event.event_type}: {msg}", flush=True)
