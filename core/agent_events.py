from __future__ import annotations

import json
import os
import threading
import uuid
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional

from core.agent_graph_state import AgentEvent, utcnow_iso

try:
    from rich import box
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live
    from rich.spinner import Spinner
except Exception:  # pragma: no cover - rich is optional at runtime
    box = None
    Console = None
    Group = None
    Panel = None
    Table = None
    Text = None
    Live = None
    Spinner = None


class EventLogger:
    def __init__(self, run_id: str, state_dir: str):
        self.run_id = run_id
        self.state_dir = state_dir
        self.events_path = os.path.join(state_dir, "events.jsonl")
        self.debug_events_path = os.path.join(state_dir, "debug_events.jsonl")
        self.mode = (os.environ.get("OS_AGENT_TERMINAL_MODE") or "compact").strip().lower()
        self.preview_chars = 180
        self._lock = threading.Lock()
        self._dashboard = _DashboardState(run_id)
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
            with open(self.debug_events_path, "a", encoding="utf-8") as f:
                debug_payload = event.to_dict()
                debug_payload["_debug"] = {
                    "terminal_mode": self.mode,
                    "state_dir": self.state_dir,
                }
                f.write(json.dumps(debug_payload, ensure_ascii=False) + "\n")
            self._render(event)
        return event

    def _render(self, event: AgentEvent) -> None:
        if self.mode == "dashboard":
            self._dashboard.update(event)
            self._dashboard.render(preview_chars=self.preview_chars)
            return
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
        if event.task_id and (self.mode == "verbose" or event.event_type.startswith("tool_")):
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


class _DashboardState:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._frame = 0
        self._console = Console() if Console is not None else None
        self._live = Live(console=self._console, auto_refresh=True, refresh_per_second=60) if Live is not None and self._console else None
        if self._live:
            self._live.start()
        self.active_stages: Dict[str, Dict[str, Any]] = {}
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        self.recent_events: deque[AgentEvent] = deque(maxlen=12)
        self.counters: Dict[str, int] = {
            "stages_done": 0,
            "stages_error": 0,
            "tasks_done": 0,
            "tasks_error": 0,
            "tools_done": 0,
            "tools_blocked": 0,
            "llm_calls": 0,
            "reviews_done": 0,
        }
        self.last_errors: deque[str] = deque(maxlen=5)

    def update(self, event: AgentEvent) -> None:
        self.recent_events.append(event)
        et = event.event_type
        if event.level in {"warn", "error"} or et.endswith("_error"):
            self.last_errors.append(self._event_line(event, 160))

        if et == "stage_start" and event.stage_id:
            self.active_stages[event.stage_id] = {
                "stage_id": event.stage_id,
                "message": event.message,
                "status": "running",
                "phase": "starting",
            }
        elif et in {"stage_done", "stage_skip", "stage_error"} and event.stage_id:
            self.active_stages.pop(event.stage_id, None)
            if et == "stage_done":
                self.counters["stages_done"] += 1
            elif et == "stage_error":
                self.counters["stages_error"] += 1
        elif event.stage_id and event.stage_id in self.active_stages:
            if "plan" in et:
                self.active_stages[event.stage_id]["phase"] = "planning"
            elif et.startswith("task_") or et.startswith("tool_"):
                self.active_stages[event.stage_id]["phase"] = "executing"
            elif et == "review_done":
                self.active_stages[event.stage_id]["phase"] = "reviewed"
            elif "review" in et:
                self.active_stages[event.stage_id]["phase"] = "reviewing"

        if et in {"task_start", "tool_start", "task_dispatch"} and event.task_id:
            self.active_tasks[event.task_id] = {
                "stage_id": event.stage_id,
                "task_id": event.task_id,
                "agent_name": event.agent_name,
                "action": event.message,
                "event_type": et,
            }
        elif et == "tool_done" and event.task_id:
            self.counters["tools_done"] += 1
            self.active_tasks[event.task_id] = {
                "stage_id": event.stage_id,
                "task_id": event.task_id,
                "agent_name": event.agent_name,
                "action": event.message,
                "event_type": et,
            }
        elif et == "tool_blocked" and event.task_id:
            self.counters["tools_blocked"] += 1
            self.active_tasks[event.task_id] = {
                "stage_id": event.stage_id,
                "task_id": event.task_id,
                "agent_name": event.agent_name,
                "action": event.message,
                "event_type": et,
            }
        elif et == "task_done" and event.task_id:
            self.active_tasks.pop(event.task_id, None)
            self.counters["tasks_done"] += 1
        elif et == "task_error" and event.task_id:
            self.active_tasks.pop(event.task_id, None)
            self.counters["tasks_error"] += 1

        if et == "llm_done":
            self.counters["llm_calls"] += 1
        if et == "review_done":
            self.counters["reviews_done"] += 1

    def render(self, *, preview_chars: int) -> None:
        self._frame += 1
        if self._console is not None:
            self._render_rich(preview_chars=preview_chars)
            return
        self._render_plain(preview_chars=preview_chars)

    def _render_rich(self, *, preview_chars: int) -> None:
        assert self._console is not None

        summary = Table.grid(expand=True)
        summary.add_column(ratio=1)
        summary.add_column(ratio=1)
        summary.add_column(ratio=1)
        summary.add_column(ratio=1)
        summary.add_row(
            self._metric("Stages", f"{self.counters['stages_done']} done / {self.counters['stages_error']} err", "green"),
            self._metric("Tasks", f"{self.counters['tasks_done']} done / {self.counters['tasks_error']} err", "cyan"),
            self._metric("Tools", f"{self.counters['tools_done']} done / {self.counters['tools_blocked']} blocked", "yellow"),
            self._metric("LLM/Review", f"{self.counters['llm_calls']} / {self.counters['reviews_done']}", "magenta"),
        )

        stages = Table(box=box.SIMPLE_HEAVY, expand=True)
        stages.add_column("Stage", style="bold cyan", no_wrap=True)
        stages.add_column("Phase", style="yellow", no_wrap=True)
        stages.add_column("Status", style="green", no_wrap=True)
        stages.add_column("Message", overflow="fold")
        if self.active_stages:
            for sid, item in sorted(self.active_stages.items()):
                stages.add_row(
                    sid,
                    str(item.get("phase") or "running"),
                    str(item.get("status") or "running"),
                    self._truncate(str(item.get("message") or ""), preview_chars)
                )
        else:
            stages.add_row("-", "-", "idle", "none")

        tasks = Table(box=box.SIMPLE_HEAVY, expand=True)
        tasks.add_column("Stage", style="cyan", no_wrap=True)
        tasks.add_column("Task", style="bold white", no_wrap=True)
        tasks.add_column("Agent", style="magenta", no_wrap=True)
        tasks.add_column("Event", style="yellow", no_wrap=True)
        tasks.add_column("Action", overflow="fold")
        if self.active_tasks:
            for tid, item in sorted(self.active_tasks.items()):
                event_type = str(item.get("event_type") or "")
                style = self._event_style(event_type)
                tasks.add_row(
                    str(item.get("stage_id") or ""),
                    tid,
                    str(item.get("agent_name") or ""),
                    Text(event_type, style=style),
                    self._truncate(str(item.get("action") or ""), preview_chars),
                )
        else:
            tasks.add_row("-", "-", "-", "idle", "none")

        recent = Table(box=box.SIMPLE, expand=True)
        recent.add_column("Level", no_wrap=True)
        recent.add_column("Scope", style="cyan", no_wrap=True)
        recent.add_column("Event", no_wrap=True)
        recent.add_column("Message", overflow="fold")
        for event in list(self.recent_events)[-10:]:
            scope = "/".join([x for x in [event.stage_id, event.task_id, event.agent_name] if x]) or "run"
            recent.add_row(
                Text(event.level, style=self._level_style(event.level)),
                scope,
                Text(event.event_type, style=self._event_style(event.event_type)),
                self._truncate((event.message or "").replace("\n", " "), preview_chars),
            )

        header = Table.grid(padding=(0, 1))
        header.add_row(Spinner("dots", style="bright_white"), Text("OS-Agent D Dashboard", style="bold bright_white"))

        panels = [
            Panel(
                Group(
                    header,
                    Text(f"run_id={self.run_id}", style="dim"),
                    summary,
                ),
                border_style="bright_blue",
            ),
            Panel(stages, title="Active Stages", border_style="cyan"),
            Panel(tasks, title="Active Tasks / Tools", border_style="magenta"),
            Panel(recent, title="Recent Events", border_style="green"),
        ]
        if self.last_errors:
            error_text = "\n".join(self._truncate(err, preview_chars) for err in self.last_errors)
            panels.append(Panel(error_text, title="Last 5 Warnings/Errors", border_style="red"))

        group = Group(*panels)
        if getattr(self, "_live", None) and self._live:
            self._live.update(group, refresh=False)
        else:
            self._console.clear()
            self._console.print(group)

    def _render_plain(self, *, preview_chars: int) -> None:
        width = 110
        lines = [
            "OS-Agent D Dashboard".ljust(width, "="),
            f"run_id={self.run_id}",
            (
                f"stages done/error={self.counters['stages_done']}/{self.counters['stages_error']}  "
                f"tasks done/error={self.counters['tasks_done']}/{self.counters['tasks_error']}  "
                f"tools done/blocked={self.counters['tools_done']}/{self.counters['tools_blocked']}  "
                f"llm={self.counters['llm_calls']}  review={self.counters['reviews_done']}"
            ),
            "",
            "Active Stages",
            *self._active_stage_lines(preview_chars),
            "",
            "Active Tasks / Tools",
            *self._active_task_lines(preview_chars),
            "",
            "Recent Events",
            *[self._event_line(e, preview_chars) for e in list(self.recent_events)[-12:]],
        ]
        if self.last_error:
            lines.extend(["", "Last Warning/Error", self._truncate(self.last_error, preview_chars)])
        lines.append("=" * width)
        print("\033[2J\033[H" + "\n".join(lines), flush=True)

    @staticmethod
    def _metric(name: str, value: str, color: str):
        if Text is None:
            return f"{name}: {value}"
        return Text.assemble((name + "\n", f"bold {color}"), (value, "bright_white"))

    @staticmethod
    def _level_style(level: str) -> str:
        return {
            "error": "bold red",
            "warn": "yellow",
            "warning": "yellow",
            "info": "green",
        }.get((level or "").lower(), "white")

    @staticmethod
    def _event_style(event_type: str) -> str:
        et = event_type or ""
        if et.endswith("_error") or et == "tool_blocked":
            return "bold red"
        if et.endswith("_start") or et == "tool_start":
            return "bright_cyan"
        if et.endswith("_done") or et == "tool_done":
            return "green"
        if "review" in et:
            return "magenta"
        return "white"

    def _active_stage_lines(self, preview_chars: int) -> list[str]:
        if not self.active_stages:
            return ["  none"]
        return [
            f"  {sid} [{item.get('phase', 'running')}]: {self._truncate(str(item.get('message') or ''), preview_chars)}"
            for sid, item in sorted(self.active_stages.items())
        ]

    def _active_task_lines(self, preview_chars: int) -> list[str]:
        if not self.active_tasks:
            return ["  none"]
        rows = []
        for tid, item in sorted(self.active_tasks.items()):
            stage = str(item.get("stage_id") or "")
            agent = str(item.get("agent_name") or "")
            et = str(item.get("event_type") or "")
            action = self._truncate(str(item.get("action") or ""), preview_chars)
            rows.append(f"  {stage} {tid} {agent} {et}: {action}")
        return rows

    def _event_line(self, event: AgentEvent, preview_chars: int) -> str:
        parts = []
        if event.stage_id:
            parts.append(event.stage_id)
        if event.task_id:
            parts.append(event.task_id)
        if event.agent_name:
            parts.append(event.agent_name)
        prefix = "][".join(parts) if parts else "run"
        msg = self._truncate((event.message or "").replace("\n", " "), preview_chars)
        return f"  [{event.level}] [{prefix}] {event.event_type}: {msg}"

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."


_CURRENT_EVENT_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "os_agent_current_event_context",
    default=None,
)


@contextmanager
def task_event_context(
    logger: EventLogger,
    *,
    stage_id: str,
    task_id: str,
    agent_name: str,
):
    token = _CURRENT_EVENT_CONTEXT.set(
        {
            "logger": logger,
            "stage_id": stage_id,
            "task_id": task_id,
            "agent_name": agent_name,
            "tool_call_count": 0,
            "tool_signature_counts": {},
        }
    )
    try:
        yield
    finally:
        _CURRENT_EVENT_CONTEXT.reset(token)


def current_task_event_context() -> Optional[Dict[str, Any]]:
    return _CURRENT_EVENT_CONTEXT.get()


def emit_task_tool_event(
    event_type: str,
    message: str,
    *,
    level: str = "info",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    ctx = current_task_event_context()
    if not ctx:
        return
    logger = ctx.get("logger")
    if not isinstance(logger, EventLogger):
        return
    logger.emit(
        event_type,
        message,
        stage_id=str(ctx.get("stage_id") or ""),
        task_id=str(ctx.get("task_id") or ""),
        agent_name=str(ctx.get("agent_name") or ""),
        level=level,
        metadata=metadata or {},
    )
