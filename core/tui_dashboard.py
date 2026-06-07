from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import AbstractContextManager
from typing import Any

from core.kernel_tree import ANALYSIS_BATCHES_V2, node_title_zh


class TUIDashboard(AbstractContextManager):
    """Rich live projection of Agent D events.

    The dashboard never owns workflow state. It renders snapshots supplied by
    the LangGraph event projector.
    """

    def __init__(self, projector: Any, *, enabled: bool = True):
        self.projector = projector
        self.enabled = bool(enabled and sys.stderr.isatty() and not os.environ.get("CI"))
        self.refresh_hz = max(1, int(os.environ.get("AGENT_D_TUI_REFRESH_HZ", "4")))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.live = None

    def __enter__(self):
        if self.enabled:
            self.thread = threading.Thread(target=self._run, name="agent-d-tui", daemon=True)
            self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def _run(self) -> None:
        from rich.console import Console
        from rich.live import Live

        console = Console(stderr=True)
        with Live(self._render(), console=console, refresh_per_second=self.refresh_hz, transient=False) as live:
            self.live = live
            while not self.stop_event.wait(1 / self.refresh_hz):
                live.update(self._render())

    def _render(self):
        from rich import box
        from rich.columns import Columns
        from rich.console import Group
        from rich.panel import Panel
        from rich.progress_bar import ProgressBar
        from rich.table import Table
        from rich.text import Text

        status = self.projector.snapshot()
        total = max(1, int(status.get("total_nodes") or 1))
        completed = int(status.get("completed_nodes") or 0)
        header = Text()
        header.append("Agent D  ", style="bold cyan")
        header.append(str(status.get("repo_name") or ""), style="bold")
        header.append(f"  run={status.get('run_id', '-')[:12]}  ")
        header.append("恢复运行" if status.get("resumed") else "新运行", style="yellow")
        header.append(f"  {status.get('elapsed_seconds', 0):.1f}s")
        progress = Group(header, ProgressBar(total=total, completed=completed, width=None))

        flow = Text()
        batch_index = int(status.get("current_batch_index") or 0)
        batch_meta = {int(row.get("batch_index") or 0): row for row in status.get("analysis_batches") or []}
        for index, batch in enumerate(ANALYSIS_BATCHES_V2, 1):
            batch_states = [status.get("node_states", {}).get(node, "pending") for node in batch]
            if batch_states and all(x == "done" for x in batch_states):
                marker, style = "✓", "green"
            elif any(x == "failed" for x in batch_states):
                marker, style = "×", "red"
            elif index == batch_index or any(x == "running" for x in batch_states):
                marker, style = "●", "yellow"
            else:
                marker, style = "○", "dim"
            if index > 1:
                flow.append(" → ", style="dim")
            title = str((batch_meta.get(index) or {}).get("title_zh") or f"阶段 {index}")
            parallel = "并发" if len(batch) > 1 else "串行"
            flow.append(f"{marker} {title}({parallel})", style=style)

        active = Table(box=box.SIMPLE, expand=True, show_header=True)
        active.add_column("节点 / Node", ratio=3)
        active.add_column("阶段 / Phase", ratio=2)
        active.add_column("ReAct", justify="right")
        active.add_column("当前工具 / Active tool", ratio=3)
        active.add_column("证据", justify="right")
        active.add_column("Claim", justify="right")
        rows = []
        for node_id, node in (status.get("node_run_states") or {}).items():
            if node.get("phase") not in {"pending", "done", "skipped"} or node.get("last_error"):
                rows.append((node_id, node))
        rows.sort(key=lambda item: item[1].get("updated_at", 0), reverse=True)
        limit = max(1, int(os.environ.get("AGENT_D_TUI_MAX_ACTIVE_NODES", "8")))
        for node_id, node in rows[:limit]:
            phase = str(node.get("phase") or "")
            style = "red" if node.get("last_error") else ("green" if phase == "done" else "yellow")
            active.add_row(
                f"{node_title_zh(node_id.split('.')[-1])} / {node_id}",
                Text(phase, style=style),
                str(node.get("react_step") or 0),
                str(node.get("active_tool") or ""),
                str(node.get("evidence_count") or 0),
                str(node.get("claim_count") or 0),
            )
        if not rows:
            active.add_row("等待调度", "bootstrap", "0", "", "0", "0")

        stats = Table.grid(expand=True)
        stats.add_column()
        stats.add_column()
        stats.add_column()
        stats.add_column()
        stats.add_row(
            f"LLM calls: {status.get('llm_calls', 0)}",
            f"tokens: {status.get('llm_total_tokens', 0)}",
            f"tool calls: {status.get('tool_calls', 0)}",
            f"evidence: {status.get('evidence_count', 0)}",
        )

        details = []
        selected = rows[0][1] if rows else {}
        for event in (selected.get("recent_events") or [])[-int(os.environ.get("AGENT_D_TUI_EVENT_ROWS", "8")):]:
            details.append(f"{event.get('kind', '')}: {event.get('summary', '')}")
        if selected.get("last_error"):
            details.append(f"错误: {selected['last_error']}")
        detail_text = "\n".join(details) or "节点事件会按 node_id 隔离显示。"

        return Group(
            Panel(progress, title="运行 / Run", border_style="cyan"),
            Panel(flow, title="分析流程 / Analysis Flow"),
            Panel(active, title="当前并发节点 / Active Nodes"),
            Columns([
                Panel(detail_text, title="节点详情 / Node Details", expand=True),
                Panel(stats, title="运行统计 / Statistics", expand=True),
            ], expand=True),
        )
