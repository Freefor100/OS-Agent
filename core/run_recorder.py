from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from core.kernel_tree import ANALYSIS_BATCHES_V2, ANALYSIS_ORDER_V2, node_title_zh


@dataclass
class ToolCallRecord:
    call_id: str
    node_id: str
    phase: str
    tool: str
    args: dict[str, Any]
    status: str
    started_at: float
    ended_at: float
    latency_ms: int
    added_evidence_ids: list[str] = field(default_factory=list)
    error: str = ""


class RunRecorder:
    """Event projector for LangGraph, TUI, JSON status, and the web dashboard."""

    def __init__(self, output_dir: str, repo_name: str, total_nodes: int, *, run_id: str = "", resumed: bool = False):
        self.output_dir = Path(output_dir)
        self.repo_name = repo_name
        self.total_nodes = total_nodes
        self.started_at = time.time()
        self.run_id = run_id
        self.resumed = resumed
        self.lock = Lock()
        self.io_lock = Lock()
        self.log_lock = Lock()
        self.events: deque[dict[str, Any]] = deque(maxlen=500)
        self.tool_calls: deque[ToolCallRecord] = deque(maxlen=500)
        self.tool_call_count = 0
        self.active_nodes = set(ANALYSIS_ORDER_V2[:total_nodes])
        self.node_states = {
            node_id: ("pending" if node_id in self.active_nodes else "skipped")
            for node_id in ANALYSIS_ORDER_V2
        }
        # Detailed node state exists only while a node is active or failed.
        # Completed-node details live in append-only logs and node result files.
        self.node_stats: dict[str, dict[str, Any]] = {}
        self.status: dict[str, Any] = {
            "schema_version": "agent_d.run_status.v3",
            "repo_name": repo_name,
            "run_id": run_id,
            "resumed": resumed,
            "state": "running",
            "current_batch_index": 0,
            "current_batch": "",
            "current_node": "",
            "total_nodes": total_nodes,
            "completed_nodes": 0,
            "failed_node": "",
            "last_error": "",
            "llm_calls": 0,
            "llm_total_tokens": 0,
            "llm_reasoning_tokens": 0,
            "tool_calls": 0,
            "evidence_count": 0,
            "claim_count": 0,
            "verifier_errors": [],
            "artifacts": {},
            "analysis_batches": _analysis_batches_for_status(),
            "node_states": self.node_states,
            "node_stats": self.node_stats,
            "node_run_states": self.node_stats,
            "node_concurrency": _env_int("AGENT_D_NODE_CONCURRENCY", 1),
            "llm_concurrency": _env_int("AGENT_D_LLM_CONCURRENCY", 2),
            "evidence_concurrency": _env_int("AGENT_D_EVIDENCE_CONCURRENCY", 8),
            "thinking": {
                "enabled": str(_env("AGENT_D_THINKING", "enabled")),
                "reasoning_effort": str(_env("AGENT_D_REASONING_EFFORT", "high")),
            },
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not resumed:
            _atomic_write_text(self.output_dir / "run_events.jsonl", "")
            _atomic_write_text(self.output_dir / "tool_calls.jsonl", "")
        self.event("run_start", {"repo_name": repo_name, "total_nodes": total_nodes})
        self.flush()

    def event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        node_id = str(data.get("node_id") or "")
        summary = str(data.get("summary") or data.get("phase") or data.get("tool") or data.get("label") or "")[:220]
        with self.lock:
            now = time.time()
            row = {"ts": now, "kind": kind, "node_id": node_id, "data": data}
            self.events.append(row)
            if node_id and self.node_states.get(node_id) not in {"done", "skipped"}:
                state = self.node_stats.setdefault(node_id, _empty_node_state(node_id))
                state["updated_at"] = now
                recent = list(state.get("recent_events") or [])
                recent.append({"ts": now, "kind": kind, "summary": summary})
                state["recent_events"] = recent[-20:]
        self._append_log("run_events.jsonl", row)

    def set_batch(self, label: str, batch_index: int | None = None) -> None:
        with self.lock:
            self.status["current_batch"] = label
            if batch_index is not None:
                self.status["current_batch_index"] = batch_index
        self.event("batch", {"label": label, "batch_index": batch_index or 0})
        self.flush()

    def set_node(self, node_id: str) -> None:
        now = time.time()
        with self.lock:
            self.status["current_node"] = node_id
            if self.node_states.get(node_id) != "done":
                self.node_states[node_id] = "running"
                self.node_stats.setdefault(node_id, _empty_node_state(node_id))
                self.node_stats[node_id]["phase"] = "react"
                self.node_stats[node_id]["started_at"] = self.node_stats[node_id].get("started_at") or now
                self.node_stats[node_id]["last_error"] = ""
                self.node_stats[node_id]["updated_at"] = now
            self.status["node_states"] = self.node_states
            self.status["node_stats"] = self.node_stats
        self.event("node_start", {"node_id": node_id})
        self.flush()

    def node_done(self, node_id: str, claim_count: int, evidence_count: int) -> None:
        now = time.time()
        with self.lock:
            if self.node_states.get(node_id) != "done":
                self.status["completed_nodes"] = int(self.status.get("completed_nodes", 0)) + 1
            self.node_states[node_id] = "done"
            self.node_stats.pop(node_id, None)
            self.status["claim_count"] = claim_count
            self.status["evidence_count"] = evidence_count
            self.status["node_states"] = self.node_states
            self.status["node_stats"] = self.node_stats
        self.event("node_done", {"node_id": node_id, "claim_count": claim_count, "evidence_count": evidence_count})
        self.flush()

    def llm_call(self, meta: dict[str, Any]) -> None:
        usage = meta.get("usage") or {}
        node_id = _node_from_template(str(meta.get("template_id") or ""))
        with self.lock:
            self.status["llm_calls"] = int(self.status.get("llm_calls", 0)) + 1
            self.status["llm_total_tokens"] = int(self.status.get("llm_total_tokens", 0)) + int(usage.get("total_tokens") or 0)
            self.status["llm_reasoning_tokens"] = int(self.status.get("llm_reasoning_tokens", 0)) + int(usage.get("reasoning_tokens") or 0)
            if node_id in self.node_stats and self.node_states.get(node_id) != "done":
                self.node_stats[node_id]["llm_calls"] = int(self.node_stats[node_id].get("llm_calls") or 0) + 1
                self.node_stats[node_id]["updated_at"] = time.time()
                self.status["node_stats"] = self.node_stats
        self.event("llm_call", meta)
        self.flush()

    def tool_call(self, *, node_id: str, phase: str, tool: str, args: dict[str, Any], started_at: float, status: str, added_evidence_ids: list[str] | None = None, error: str = "") -> None:
        ended = time.time()
        with self.lock:
            self.tool_call_count += 1
            call_id = f"tool_{self.tool_call_count:05d}"
        rec = ToolCallRecord(
            call_id=call_id,
            node_id=node_id,
            phase=phase,
            tool=tool,
            args=_compact(args),
            status=status,
            started_at=started_at,
            ended_at=ended,
            latency_ms=int((ended - started_at) * 1000),
            added_evidence_ids=added_evidence_ids or [],
            error=error,
        )
        with self.lock:
            self.tool_calls.append(rec)
            self.status["tool_calls"] = self.tool_call_count
            if self.node_states.get(node_id) not in {"done", "skipped"}:
                self.node_stats.setdefault(node_id, _empty_node_state(node_id))
                self.node_stats[node_id]["phase"] = "tool"
                self.node_stats[node_id]["active_tool"] = tool
                self.node_stats[node_id]["tool_calls"] = int(self.node_stats[node_id].get("tool_calls") or 0) + 1
                recent = list(self.node_stats[node_id].get("recent_tool_calls") or [])
                recent.append({"tool": tool, "status": status, "latency_ms": rec.latency_ms})
                self.node_stats[node_id]["recent_tool_calls"] = recent[-12:]
                if added_evidence_ids:
                    self.node_stats[node_id]["evidence_count"] = int(self.node_stats[node_id].get("evidence_count") or 0) + len(added_evidence_ids)
                if error:
                    self.node_stats[node_id]["last_error"] = error
                self.node_stats[node_id]["updated_at"] = ended
            self.status["node_stats"] = self.node_stats
        self._append_log("tool_calls.jsonl", asdict(rec))
        self.event("tool_call", asdict(rec))
        self.flush()

    def verifier(self, report: dict[str, Any]) -> None:
        errors = report.get("errors") or []
        if errors:
            node_id = str(report.get("node_id") or "")
            with self.lock:
                rows = list(self.status.get("verifier_errors") or [])
                rows.append({"node_id": node_id, "errors": errors[-4:]})
                self.status["verifier_errors"] = rows[-12:]
                if node_id in self.node_stats:
                    self.node_stats[node_id]["phase"] = "repair" if errors else "verifier"
                    self.node_stats[node_id]["last_error"] = "; ".join(str(x) for x in errors[-2:])
                    self.node_stats[node_id]["repair_attempt"] = int(report.get("repair_attempt") or self.node_stats[node_id].get("repair_attempt") or 0)
                    self.node_stats[node_id]["updated_at"] = time.time()
                    self.status["node_stats"] = self.node_stats
        self.event("verifier", report)
        self.flush()

    def graph_event(self, kind: str, *, node_id: str = "", phase: str = "", data: dict[str, Any] | None = None) -> None:
        payload = dict(data or {})
        if node_id:
            payload["node_id"] = node_id
        if phase:
            payload["phase"] = phase
        with self.lock:
            if node_id and self.node_states.get(node_id) not in {"done", "skipped"}:
                state = self.node_stats.setdefault(node_id, _empty_node_state(node_id))
                if phase:
                    state["phase"] = phase
                if "react_step" in payload:
                    state["react_step"] = int(payload["react_step"])
                if "repair_attempt" in payload:
                    state["repair_attempt"] = int(payload["repair_attempt"])
                if "active_tool" in payload:
                    state["active_tool"] = str(payload["active_tool"])
                if "last_checkpoint_at" in payload:
                    state["last_checkpoint_at"] = payload["last_checkpoint_at"]
                if payload.get("error"):
                    state["last_error"] = str(payload["error"])
                state["updated_at"] = time.time()
        self.event(kind, payload)
        self.flush()

    def project_graph_state(self, state: dict[str, Any]) -> None:
        with self.lock:
            self.status["run_id"] = state.get("run_id") or self.run_id
            self.status["state"] = state.get("run_status") or self.status.get("state", "running")
            self.status["current_batch_index"] = min(
                len(ANALYSIS_BATCHES_V2),
                int(state.get("current_batch_index") or 0) + 1,
            )
            completed = set(state.get("completed_node_ids") or [])
            failed = set(state.get("failed_node_ids") or [])
            self.status["completed_nodes"] = len(completed)
            for node_id in completed:
                self.node_states[node_id] = "done"
                self.node_stats.pop(node_id, None)
            for node_id in failed:
                self.node_states[node_id] = "failed"
                self.node_stats.setdefault(node_id, _empty_node_state(node_id))["phase"] = "failed"
            for node_id, projected in (state.get("node_run_states") or {}).items():
                if node_id == "__clear__":
                    for completed_node_id in projected or []:
                        self.node_stats.pop(str(completed_node_id), None)
                    continue
                if node_id in completed:
                    continue
                if not isinstance(projected, dict):
                    continue
                node_state = self.node_stats.setdefault(node_id, _empty_node_state(node_id))
                for key in ("phase", "last_error", "last_checkpoint_at"):
                    if projected.get(key) not in {None, ""}:
                        node_state[key] = projected[key]
            self.status["node_states"] = self.node_states
            self.status["node_stats"] = self.node_stats
            self.status["node_run_states"] = self.node_stats
        self.flush()

    def checkpoint(self, node_id: str = "") -> None:
        now = time.time()
        if node_id and self.node_states.get(node_id) not in {"done", "skipped"}:
            with self.lock:
                self.node_stats.setdefault(node_id, _empty_node_state(node_id))["last_checkpoint_at"] = now
        self.event("checkpoint", {"node_id": node_id, "last_checkpoint_at": now})
        self.flush()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            snap = json.loads(json.dumps(self.status, ensure_ascii=False, default=str))
            snap["node_run_states"] = json.loads(json.dumps(self.node_stats, ensure_ascii=False, default=str))
            snap["elapsed_seconds"] = round(time.time() - self.started_at, 1)
            return snap

    def finish(self, artifacts: dict[str, str], failure: str | None = None) -> None:
        with self.lock:
            self.status["state"] = "failed" if failure else "complete"
            self.status["last_error"] = failure or ""
            self.status["artifacts"] = artifacts
            self.status["elapsed_seconds"] = round(time.time() - self.started_at, 2)
            if failure:
                failed_node = str(self.status.get("current_node") or "")
                self.status["failed_node"] = failed_node
                if failed_node in self.node_states:
                    self.node_states[failed_node] = "failed"
                    self.node_stats.setdefault(failed_node, _empty_node_state(failed_node))
                    self.node_stats[failed_node]["phase"] = "failed"
                    self.node_stats[failed_node]["last_error"] = failure
                    self.status["node_states"] = self.node_states
                    self.status["node_stats"] = self.node_stats
        self.event("run_finish", {"failure": failure, "artifacts": artifacts})
        self.flush()

    def flush(self) -> None:
        with self.lock:
            status = dict(self.status)
            status["node_states"] = dict(self.node_states)
            status["node_stats"] = json.loads(json.dumps(self.node_stats, ensure_ascii=False, default=str))
            status["node_run_states"] = status["node_stats"]
            events = list(self.events)
            tool_calls = [asdict(x) for x in self.tool_calls]
        with self.io_lock:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(self.output_dir / "run_status.json", json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
            _write_jsonl(self.output_dir / "run_events_tail.jsonl", events)
            _write_jsonl(self.output_dir / "tool_calls_tail.jsonl", tool_calls)
            _atomic_write_text(self.output_dir / "run_dashboard.html", _dashboard_html(status, events, tool_calls))

    def _append_log(self, filename: str, row: dict[str, Any]) -> None:
        line = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        with self.log_lock:
            with (self.output_dir / filename).open("a", encoding="utf-8") as handle:
                handle.write(line)


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _compact(v) for k, v in value.items() if k not in {"content", "excerpt"}}
    if isinstance(value, list):
        return [_compact(v) for v in value[:8]]
    text = str(value)
    return text if len(text) <= 240 else text[:237] + "..."


def _empty_node_state(node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "phase": "pending",
        "react_step": 0,
        "repair_attempt": 0,
        "active_tool": "",
        "recent_tool_calls": [],
        "recent_events": [],
        "llm_calls": 0,
        "tool_calls": 0,
        "evidence_count": 0,
        "claim_count": 0,
        "last_error": "",
        "last_checkpoint_at": None,
        "updated_at": time.time(),
        "started_at": None,
        "ended_at": None,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def _atomic_write_text(path: Path, content: str) -> bool:
    for attempt in range(6):
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, path)
            return True
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.02 * (attempt + 1))
    # RunRecorder is an event projection, not workflow state. A later event
    # will retry the snapshot; projection I/O must never abort Agent D.
    return False


def _env(name: str, default: Any) -> Any:
    return __import__("os").environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(_env(name, default)))
    except ValueError:
        return default


def _node_from_template(template_id: str) -> str:
    for prefix in ("agent_d_node_explorer:", "agent_d_node_reader:"):
        if template_id.startswith(prefix):
            return template_id[len(prefix):]
    if template_id == "agent_d_evolution_history":
        return "EvolutionHistory"
    if template_id.startswith("langchain_node:"):
        return template_id[len("langchain_node:"):]
    return "__global__"


def _analysis_batches_for_status() -> list[dict[str, Any]]:
    return [
        {
            "batch_index": index,
            "title_zh": _batch_title(index),
            "description_zh": _batch_description(index),
            "parallel": len(nodes) > 1,
            "nodes": [{"node_id": node_id, "title_zh": _node_title_zh(node_id)} for node_id in nodes],
        }
        for index, nodes in enumerate(ANALYSIS_BATCHES_V2, start=1)
    ]


def _batch_title(index: int) -> str:
    return {
        1: "项目元数据与构建配置",
        2: "启动入口与早期控制台",
        3: "内存基础：物理页、页表、地址空间",
        4: "陷入、系统调用与时钟",
        5: "任务结构、上下文切换与调度基础",
        6: "进程生命周期与 IPC",
        7: "高级内存机制",
        8: "同步原语汇总",
        9: "文件抽象与命名空间",
        10: "块缓存、日志与块设备",
        11: "具体文件系统",
        12: "设备驱动扩展",
        13: "网络栈",
        14: "安全与隔离",
        15: "内核服务",
        16: "多核、线程与资源控制扩展",
        17: "观测与调试",
        18: "用户态支持",
        19: "虚拟化",
        20: "演进历史",
    }.get(index, f"分析阶段 {index}")


def _batch_description(index: int) -> str:
    return {
        1: "先确认语言、架构、平台、链接脚本、编译目标和工具链。",
        2: "从机器启动到内核入口，并确认最早可用的串口/控制台输出。",
        3: "建立内存管理的地基，后续进程、陷入和文件 I/O 都会依赖它。",
        4: "确认异常入口、系统调用分发和时钟中断，这是用户态进入内核的主通道。",
        5: "读任务结构、上下文保存和调度循环，形成运行实体模型。",
        6: "读 fork/exec/wait、信号和 IPC，确认进程生命周期。",
        7: "补充 mmap、缺页、页缓存、swap、TLB 等现代内存机制。",
        8: "把锁、等待队列和引用计数机制统一归纳，避免和调度/文件层混淆。",
        9: "读文件描述符、VFS 或 inode/dentry，把用户文件接口和内核对象连起来。",
        10: "确认块缓存、日志和底层块设备之间的依赖。",
        11: "识别 FAT32、ext4、ramfs、devfs 等具体文件系统。",
        12: "读总线、DMA、显示、输入、时钟等平台驱动扩展。",
        13: "识别 socket、TCP/UDP、网卡和包缓冲。",
        14: "确认特权级、用户/内核隔离、安全策略和硬化机制。",
        15: "识别工作队列、软中断、定时器、模块、随机数和电源管理。",
        16: "补充 SMP、每 CPU 状态、线程、调度类、futex、namespace、cgroup。",
        17: "读日志、panic、回溯、trace、性能计数和 GDB 支持。",
        18: "读用户库、shell、init、测试程序和 ELF ABI。",
        19: "识别 hypervisor、virtio guest 和容器相关原语。",
        20: "LLM 读取 git/history 证据，给评委展示演进脉络，不参与主查重分。",
    }.get(index, "")


def _node_title_zh(node_id: str) -> str:
    if node_id in {"Metadata", "EvolutionHistory"}:
        return node_title_zh(node_id)
    parts = node_id.split(".")
    return " / ".join(node_title_zh(part) for part in parts[-2:] if part != "ConcreteFS") if len(parts) > 2 else node_title_zh(parts[-1])


def _zh(name: str) -> str:
    return {
        "Metadata": "项目元数据",
        "BuildAndConfig": "构建与配置",
        "ArchitectureLayer": "架构层",
        "MemoryManagement": "内存管理",
        "ProcessManagement": "进程管理",
        "Synchronization": "同步机制",
        "FileSystem": "文件系统",
        "DeviceDriver": "设备驱动",
        "Network": "网络",
        "SecurityAndIsolation": "安全与隔离",
        "KernelServices": "内核服务",
        "ObservabilityAndDebug": "观测与调试",
        "UserLibAndTests": "用户库与测试",
        "Virtualization": "虚拟化",
        "EvolutionHistory": "演进历史",
        "MakeTargets": "Make 目标",
        "LinkerScript": "链接脚本",
        "Toolchain": "工具链",
        "KernelConfig": "内核配置",
        "CargoFeatures": "Cargo Features",
        "Boot": "启动入口",
        "EarlyConsole": "早期控制台",
        "TrapException": "陷入与异常",
        "SyscallEntry": "系统调用入口",
        "InterruptTimer": "时钟中断",
        "ContextSwitch": "上下文切换",
        "SMPBringup": "多核启动",
        "PerCpuState": "每 CPU 状态",
        "PhysicalAllocator": "物理页分配",
        "KernelHeap": "内核堆",
        "SlabObjectCache": "对象缓存/Slab",
        "PageTable": "页表",
        "KernelAddressSpace": "内核地址空间",
        "UserAddressSpace": "用户地址空间",
        "Mmap": "mmap",
        "PageFault": "缺页处理",
        "CopyUser": "用户态拷贝",
        "PageCache": "页缓存",
        "Swap": "交换区",
        "TLBManagement": "TLB 管理",
        "TaskStruct": "任务结构",
        "ThreadModel": "线程模型",
        "Scheduler": "调度器",
        "SchedulerClass": "调度类",
        "ForkClone": "Fork/Clone",
        "Exec": "Exec 装载",
        "WaitExit": "Wait/Exit",
        "Signal": "信号",
        "IPC": "进程间通信",
        "Futex": "Futex",
        "Namespace": "命名空间",
        "Cgroup": "Cgroup",
        "SpinLock": "自旋锁",
        "Mutex": "互斥锁",
        "Semaphore": "信号量",
        "SleepLock": "睡眠锁",
        "WaitQueue": "等待队列",
        "RCU": "RCU",
        "AtomicRefCount": "原子引用计数",
        "FileDescriptorTable": "文件描述符表",
        "VFS": "VFS/文件抽象",
        "InodeDentry": "Inode/Dentry",
        "FAT32": "FAT32",
        "ext4": "ext4",
        "ramfs": "ramfs/rootfs",
        "devfs": "devfs",
        "PipeOrProcFS": "Pipe/ProcFS",
        "BlockCache": "块缓存",
        "JournalOrLog": "日志/Journaling",
        "BlockDevice": "块设备",
        "PageCacheIntegration": "页缓存集成",
        "DriverModel": "驱动模型",
        "InterruptController": "中断控制器",
        "ConsoleUART": "Console/UART",
        "VirtIO": "VirtIO",
        "PCI": "PCI 总线",
        "PlatformBus": "平台总线/FDT",
        "DMA": "DMA",
        "GPUDisplay": "图形显示",
        "InputDevice": "输入设备",
        "ClockTimerDevice": "时钟设备",
        "Socket": "Socket",
        "TCPUDP": "TCP/UDP",
        "NetDevice": "网络设备",
        "PacketBuffer": "包缓冲",
        "Netfilter": "网络过滤",
        "UnixDomainSocket": "Unix 域 Socket",
        "PrivilegeMode": "特权级",
        "UserKernelIsolation": "用户/内核隔离",
        "CapabilityOrACL": "权限/ACL",
        "SeccompSandbox": "Seccomp/沙箱",
        "KASLR": "KASLR",
        "WriteXorExecute": "W^X/NX",
        "WorkQueue": "工作队列",
        "SoftIRQ": "软中断",
        "TimerWheel": "定时器队列",
        "ModuleLoader": "模块加载",
        "Randomness": "随机数",
        "PowerManagement": "电源管理",
        "Logging": "日志输出",
        "Panic": "Panic",
        "Backtrace": "回溯",
        "Tracing": "跟踪",
        "PerfCounter": "性能计数器",
        "GDBStub": "GDB Stub",
        "LibcOrSyscallWrapper": "用户库/系统调用封装",
        "Shell": "Shell",
        "InitProc": "Init 进程",
        "TestPrograms": "测试程序",
        "ELFABI": "ELF ABI",
        "HypervisorMode": "Hypervisor 模式",
        "VirtioGuest": "VirtIO Guest",
        "ContainerPrimitives": "容器原语",
    }.get(name, name)


def _dashboard_html(status: dict[str, Any], events: list[dict[str, Any]], tool_calls: list[dict[str, Any]]) -> str:
    payload = json.dumps({"status": status, "events": events, "tool_calls": tool_calls}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent D 内核分析进度</title>
  <style>
    :root {{
      --bg:#f5f6f2; --panel:#ffffff; --ink:#1d241f; --muted:#647069; --line:#d9dfd7;
      --pending:#a3aaa4; --running:#2368b3; --done:#168267; --failed:#b13a2f; --skipped:#c4c9c2;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, "Microsoft YaHei", "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }}
    header {{ padding:18px 28px; background:#fff; border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }}
    h1 {{ margin:0; font-size:24px; letter-spacing:0; }} h2 {{ margin:0 0 12px; font-size:18px; }} h3 {{ margin:0; font-size:15px; }}
    main {{ padding:18px 28px 56px; }} .muted {{ color:var(--muted); }} .hint {{ margin-top:6px; font-size:13px; color:var(--muted); }}
    .summary {{ display:grid; grid-template-columns: minmax(280px,2fr) repeat(4,minmax(130px,1fr)); gap:12px; align-items:stretch; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 1px 2px rgba(20,32,24,.04); }}
    .metric .value {{ font-size:25px; font-weight:750; margin-top:5px; }} .metric .label {{ font-size:13px; color:var(--muted); }}
    progress {{ width:100%; height:15px; accent-color:var(--done); }}
    .state-pill {{ display:inline-flex; align-items:center; gap:7px; border:1px solid var(--line); border-radius:999px; padding:4px 10px; font-size:13px; background:#fff; }}
    .dot {{ width:9px; height:9px; border-radius:50%; background:var(--pending); display:inline-block; }}
    .dot.running {{ background:var(--running); box-shadow:0 0 0 4px rgba(35,104,179,.12); }}
    .dot.done {{ background:var(--done); }} .dot.failed {{ background:var(--failed); }} .dot.skipped {{ background:var(--skipped); }}
    .flow {{ display:flex; gap:16px; overflow-x:auto; padding:4px 2px 16px; scroll-snap-type:x proximity; }}
    .batch {{ flex:0 0 360px; min-height:230px; scroll-snap-align:start; position:relative; }}
    .batch::after {{ content:"→"; position:absolute; right:-14px; top:27px; color:#8a948d; font-weight:700; }}
    .batch:last-child::after {{ content:""; }}
    .batch-head {{ display:flex; gap:10px; align-items:flex-start; margin-bottom:10px; }}
    .badge {{ flex:0 0 auto; width:30px; height:30px; border-radius:50%; display:grid; place-items:center; font-weight:800; color:#fff; background:#6e7970; }}
    .batch.running .badge {{ background:var(--running); }} .batch.done .badge {{ background:var(--done); }} .batch.failed .badge {{ background:var(--failed); }}
    .batch-title {{ font-weight:760; line-height:1.25; }} .batch-desc {{ margin-top:5px; font-size:12px; line-height:1.45; color:var(--muted); }}
    .parallel-note {{ font-size:12px; color:#536158; margin:4px 0 9px; }}
    .nodes {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
    .node {{ border:1px solid #e4e8e2; border-left:4px solid var(--pending); border-radius:7px; padding:8px 9px; min-height:66px; background:#fbfcfa; }}
    .node.running {{ border-left-color:var(--running); background:#f4f8fd; }} .node.done {{ border-left-color:var(--done); background:#f4fbf8; }}
    .node.failed {{ border-left-color:var(--failed); background:#fff6f5; }} .node.skipped {{ border-left-color:var(--skipped); color:#7b837d; background:#f3f5f2; }}
    .node-name {{ font-size:13px; font-weight:720; line-height:1.25; }} .node-meta {{ margin-top:6px; font-size:11px; color:var(--muted); line-height:1.35; }}
    .details-grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-top:14px; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; }} th,td {{ text-align:left; border-bottom:1px solid #edf0ec; padding:8px; vertical-align:top; overflow-wrap:anywhere; font-size:13px; }}
    code {{ background:#eef2ed; padding:2px 5px; border-radius:4px; }} .bad {{ color:var(--failed); }} .ok {{ color:var(--done); }}
    @media (max-width:1100px) {{ .summary {{ grid-template-columns:1fr 1fr; }} .details-grid {{ grid-template-columns:1fr; }} .batch {{ flex-basis:330px; }} }}
    @media (max-width:640px) {{ main,header {{ padding-left:14px; padding-right:14px; }} .summary {{ grid-template-columns:1fr; }} .nodes {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<header>
  <h1>Agent D 内核分析进度</h1>
  <div class="hint">按“写/启动内核”的依赖顺序推进；每个阶段从左到右串行，阶段内部的多个分析节点可以并发执行。</div>
</header>
<main id="app"></main>
<script type="application/json" id="snapshot">{payload}</script>
<script>
let DATA = JSON.parse(document.getElementById('snapshot').textContent);
const STATE_TEXT = {{pending:'等待', running:'运行中', done:'完成', failed:'失败', skipped:'未纳入本次'}};
const TOOL_TEXT = {{
  read_symbol:'读符号', read_path:'读源码位置', grep:'搜索', lsp_definition:'LSP 定义',
  lsp_references:'LSP 引用', call_graph:'调用图', negative_search:'负向搜索', git_history:'Git 历史',
  atlas_search:'结构索引搜索', atlas_symbol:'结构索引符号', atlas_neighbors:'结构邻居', atlas_fingerprint:'结构指纹',
  glossary_lookup:'概念词典查询'
}};
async function refresh() {{
  if (location.protocol.startsWith('http')) {{
    try {{
      DATA.status = await (await fetch('run_status.json?ts=' + Date.now())).json();
      const evText = await (await fetch('run_events_tail.jsonl?ts=' + Date.now())).text();
      DATA.events = evText.trim().split('\\n').filter(Boolean).map(JSON.parse);
      const tcText = await (await fetch('tool_calls_tail.jsonl?ts=' + Date.now())).text();
      DATA.tool_calls = tcText.trim().split('\\n').filter(Boolean).map(JSON.parse);
    }} catch (e) {{}}
  }}
  render();
  if (DATA.status.state !== 'complete' && DATA.status.state !== 'failed') setTimeout(refresh, 1500);
}}
function esc(s) {{ return String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
function pct(s) {{ return Math.round((s.completed_nodes || 0) * 100 / Math.max(1, s.total_nodes || 1)); }}
function batchState(batch, states) {{
  const active = batch.nodes.filter(n => states[n.node_id] !== 'skipped');
  if (!active.length) return 'skipped';
  if (active.some(n => states[n.node_id] === 'failed')) return 'failed';
  if (active.some(n => states[n.node_id] === 'running')) return 'running';
  if (active.every(n => states[n.node_id] === 'done')) return 'done';
  return 'pending';
}}
function nodeTitle(nodeId, s) {{
  for (const batch of (s.analysis_batches || [])) {{
    const hit = (batch.nodes || []).find(n => n.node_id === nodeId);
    if (hit) return hit.title_zh || nodeId;
  }}
  return nodeId || '等待开始';
}}
function currentBatchTitle(s) {{
  const raw = String(s.current_batch || '');
  const m = raw.match(/^(\\d+)\\//);
  if (m) {{
    const hit = (s.analysis_batches || []).find(b => String(b.batch_index) === m[1]);
    if (hit) return `${{hit.batch_index}}/20：${{hit.title_zh}}`;
  }}
  return raw || '准备中';
}}
function nodeCard(n, states, stats) {{
  const state = states[n.node_id] || 'pending';
  const st = stats[n.node_id] || {{}};
  return `<div class="node ${{state}}" title="${{esc(n.node_id)}}">
    <div class="node-name"><span class="dot ${{state}}"></span> ${{esc(n.title_zh || n.node_id)}}</div>
    <div class="node-meta">${{STATE_TEXT[state] || state}} · LLM ${{st.llm_calls || 0}} · 工具 ${{st.tool_calls || 0}} · 证据 ${{st.evidence_count || 0}}</div>
    ${{st.last_error ? `<div class="node-meta bad">${{esc(st.last_error).slice(0,140)}}</div>` : ''}}
  </div>`;
}}
function renderFlow(s) {{
  const states = s.node_states || {{}}, stats = s.node_stats || {{}};
  return (s.analysis_batches || []).map(batch => {{
    const state = batchState(batch, states);
    return `<section class="panel batch ${{state}}">
      <div class="batch-head">
        <div class="badge">${{batch.batch_index}}</div>
        <div>
          <div class="batch-title">${{esc(batch.title_zh)}}</div>
          <div class="batch-desc">${{esc(batch.description_zh || '')}}</div>
        </div>
      </div>
      <div class="parallel-note">${{batch.parallel ? '本阶段可并发分析' : '本阶段单节点收束'}} · <span class="state-pill"><span class="dot ${{state}}"></span>${{STATE_TEXT[state]}}</span></div>
      <div class="nodes">${{batch.nodes.map(n => nodeCard(n, states, stats)).join('')}}</div>
    </section>`;
  }}).join('');
}}
function artifactLinks(arts) {{
  const entries = Object.entries(arts || {{}});
  if (!entries.length) return '<p class="muted">运行完成后这里会出现最终设计树、查重索引和展示页链接。</p>';
  return entries.map(([k,v]) => `<p><b>${{esc(k)}}</b>: <a href="${{esc(String(v).split(/[\\\\/]/).pop())}}">${{esc(v)}}</a></p>`).join('');
}}
function renderToolCalls(rows) {{
  return rows.slice(-24).reverse().map(t => `<tr>
    <td>${{esc(t.node_id)}}</td>
    <td>${{esc(t.phase)}} / <b>${{esc(TOOL_TEXT[t.tool] || t.tool)}}</b><br><span class="muted">${{t.latency_ms || 0}} ms</span></td>
    <td>${{esc(t.status)}}</td>
    <td>${{esc((t.added_evidence_ids || []).join(', ') || t.error || '')}}</td>
  </tr>`).join('');
}}
function render() {{
  const s = DATA.status, p = pct(s);
  document.getElementById('app').innerHTML = `
    <div class="summary">
      <section class="panel">
        <div class="state-pill"><span class="dot ${{s.state === 'failed' ? 'failed' : s.state === 'complete' ? 'done' : 'running'}}"></span>${{s.state === 'complete' ? '已完成' : s.state === 'failed' ? '失败' : '运行中'}}</div>
        <h2 style="margin-top:10px">${{esc(s.repo_name)}} · ${{p}}%</h2>
        <progress value="${{s.completed_nodes||0}}" max="${{s.total_nodes||1}}"></progress>
        <div class="hint">当前阶段：${{esc(currentBatchTitle(s))}}<br>当前分析：${{esc((s.node_states && s.current_node) ? nodeTitle(s.current_node, s) : '等待开始')}}</div>
      </section>
      ${{metric('完成节点', `${{s.completed_nodes||0}}/${{s.total_nodes||0}}`)}}
      ${{metric('LLM 调用', s.llm_calls || 0)}}
      ${{metric('工具调用', s.tool_calls || 0)}}
      ${{metric('证据 / Claim', `${{s.evidence_count||0}} / ${{s.claim_count||0}}`)}}
    </div>
    <section class="panel" style="margin-top:14px">
      <h2>内核分析流程图</h2>
      <div class="hint">横向顺序表示依赖先后；卡片内的小节点表示同阶段可并发或可独立验证的分析任务。</div>
      <div class="flow">${{renderFlow(s)}}</div>
    </section>
    <div class="details-grid">
      <section class="panel"><h2>最终产物</h2>${{artifactLinks(s.artifacts)}}</section>
      <section class="panel"><h2>运行配置</h2>
        <p>节点并发：<b>${{s.node_concurrency || 1}}</b> · LLM 并发：<b>${{s.llm_concurrency || 1}}</b> · Evidence 并发：<b>${{s.evidence_concurrency || 1}}</b></p>
        <p>Thinking：<b>${{esc((s.thinking || {{}}).enabled || '')}}</b> · Reasoning effort：<b>${{esc((s.thinking || {{}}).reasoning_effort || '')}}</b></p>
        ${{s.last_error ? `<p class="bad">${{esc(s.last_error)}}</p>` : '<p class="ok">暂无失败</p>'}}
      </section>
    </div>
    <section class="panel"><h2>最近工具调用</h2><table><thead><tr><th>分析节点</th><th>阶段/工具</th><th>状态</th><th>新增证据或错误</th></tr></thead><tbody>${{renderToolCalls(DATA.tool_calls || [])}}</tbody></table></section>
    <section class="panel"><h2>Verifier 错误</h2>${{(s.verifier_errors||[]).map(x=>`<p class="bad"><code>${{esc(x.node_id)}}</code> ${{esc((x.errors||[]).join('; '))}}</p>`).join('') || '<p class="ok">暂无</p>'}}</section>
  `;
}}
function metric(k,v) {{ return `<section class="panel metric"><div class="label">${{k}}</div><div class="value">${{v}}</div></section>`; }}
refresh();
</script>
</body>
</html>"""

