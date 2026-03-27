from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from core.per_types import PlanSpec, StageState


NOISE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "target",
    "build",
    "dist",
    "node_modules",
    ".cursor",
    "output",
}


STAGE_HINTS: Dict[str, Dict[str, List[str]]] = {
    "01_overview": {
        "seed_paths": ["README.md", "Cargo.toml", "Makefile", ".cargo", "arch", "platform", "kernel", "os"],
        "entry_symbols": ["main", "kernel_main", "rust_main", "_start"],
        "evidence_targets": ["语言与框架来源", "支持架构", "入口函数", "关键目录"],
    },
    "02_boot_arch": {
        "seed_paths": ["arch", "boot", "platform", "entry.S", "start.S", "linker.ld"],
        "entry_symbols": ["_start", "start", "rust_main", "kernel_main", "trap_handler"],
        "evidence_targets": ["启动入口", "模式切换", "页表/MMU", "trap 向量"],
    },
    "02": {
        "seed_paths": ["arch", "boot", "platform", "entry.S", "start.S", "linker.ld"],
        "entry_symbols": ["_start", "start", "rust_main", "kernel_main", "trap_handler"],
        "evidence_targets": ["启动入口", "模式切换", "页表/MMU", "trap 向量"],
    },
    "03_mem_mgmt": {
        "seed_paths": ["mm", "memory", "vm", "kernel/mm", "os/src/mm"],
        "entry_symbols": ["handle_page_fault", "alloc_frame", "map_page", "PageTable", "FrameAllocator"],
        "evidence_targets": ["物理页分配", "页表映射", "页故障处理", "堆分配器"],
    },
    "03": {
        "seed_paths": ["mm", "memory", "vm", "kernel/mm", "os/src/mm"],
        "entry_symbols": ["handle_page_fault", "alloc_frame", "map_page", "PageTable", "FrameAllocator"],
        "evidence_targets": ["物理页分配", "页表映射", "页故障处理", "堆分配器"],
    },
    "04": {
        "seed_paths": ["task", "proc", "process", "sched", "kernel/task", "kernel/proc"],
        "entry_symbols": ["schedule", "sys_fork", "spawn", "switch_to", "Task"],
        "evidence_targets": ["任务模型", "调度器", "上下文切换", "信号/Futex"],
    },
    "05": {
        "seed_paths": ["trap", "syscall", "interrupt", "exception", "kernel/trap"],
        "entry_symbols": ["trap_handler", "syscall", "syscall_dispatch", "TrapFrame"],
        "evidence_targets": ["trap 入口", "syscall 分发", "TrapFrame", "用户指针校验"],
    },
    "06": {
        "seed_paths": ["fs", "vfs", "file", "inode", "kernel/fs"],
        "entry_symbols": ["sys_open", "vfs_open", "openat", "File", "Inode"],
        "evidence_targets": ["VFS 设计", "具体文件系统", "fd table", "pipe/mmap"],
    },
    "07": {
        "seed_paths": ["driver", "device", "net", "pci", "virtio", "uart"],
        "entry_symbols": ["probe", "init_driver", "uart_init", "virtio", "interrupt"],
        "evidence_targets": ["驱动框架", "中断注册", "块设备/网卡", "平台适配"],
    },
    "08": {
        "seed_paths": ["sync", "lock", "ipc", "futex", "pipe", "signal"],
        "entry_symbols": ["Mutex", "SpinLock", "futex_wait", "pipe_write", "signal"],
        "evidence_targets": ["锁与同步原语", "IPC", "Futex", "管道/信号"],
    },
    "09": {
        "seed_paths": ["smp", "cpu", "hart", "scheduler", "interrupt"],
        "entry_symbols": ["start_secondary", "boot_secondary", "cpu_init", "ipi"],
        "evidence_targets": ["多核启动", "CPU 本地状态", "IPI", "并发保护"],
    },
    "10": {
        "seed_paths": ["security", "capability", "uid", "perm", "auth"],
        "entry_symbols": ["sys_getuid", "cap", "permission", "check_perm"],
        "evidence_targets": ["权限模型", "用户身份", "隔离边界", "安全机制"],
    },
    "11": {
        "seed_paths": ["net", "tcp", "udp", "socket", "lwip", "smoltcp"],
        "entry_symbols": ["sys_socket", "tcp", "udp", "poll", "epoll"],
        "evidence_targets": ["协议栈", "socket API", "poll/epoll", "驱动接入"],
    },
    "12": {
        "seed_paths": ["debug", "log", "panic", "assert", "backtrace"],
        "entry_symbols": ["panic_handler", "backtrace", "log", "assert"],
        "evidence_targets": ["panic/debug", "日志系统", "回溯", "错误处理"],
    },
    "13_history": {
        "seed_paths": ["git", "history", "README.md"],
        "entry_symbols": ["git"],
        "evidence_targets": ["作者贡献", "重大提交", "模块演进", "当前缺口"],
    },
}


def _read_head(path: str, max_chars: int = 3000) -> str:
    if not os.path.exists(path) or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_chars)
    except OSError:
        return ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _list_root_entries(repo_path: str) -> List[str]:
    try:
        return sorted(os.listdir(repo_path))
    except OSError:
        return []


def _walk_core_paths(repo_path: str, max_depth: int = 2) -> List[str]:
    core_paths: List[str] = []
    repo_path = os.path.abspath(repo_path)
    for root, dirs, files in os.walk(repo_path):
        rel_root = os.path.relpath(root, repo_path)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        dirs[:] = [d for d in dirs if d not in NOISE_DIRS]
        if depth > max_depth:
            dirs[:] = []
            continue
        if rel_root != ".":
            core_paths.append(rel_root.replace("\\", "/"))
        for name in files:
            if name in {"Cargo.toml", "Makefile", "Kconfig", "linker.ld", "rust-toolchain.toml"}:
                joined = os.path.join(rel_root, name) if rel_root != "." else name
                core_paths.append(joined.replace("\\", "/"))
    return _dedupe_keep_order(core_paths[:80])


def _guess_framework(readme_text: str, root_entries: List[str]) -> List[str]:
    text = (readme_text + "\n" + "\n".join(root_entries)).lower()
    guesses = []
    for keyword, label in (
        ("arceos", "ArceOS"),
        ("rcore", "rCore"),
        ("xv6", "xv6"),
        ("ucore", "uCore"),
        ("unikraft", "Unikraft"),
    ):
        if keyword in text:
            guesses.append(label)
    return _dedupe_keep_order(guesses)


def _guess_architecture(readme_text: str, root_entries: List[str]) -> List[str]:
    text = (readme_text + "\n" + "\n".join(root_entries)).lower()
    guesses = []
    for keyword, label in (
        ("riscv64", "riscv64"),
        ("risc-v", "riscv64"),
        ("riscv", "riscv64"),
        ("aarch64", "aarch64"),
        ("arm64", "aarch64"),
        ("x86_64", "x86_64"),
        ("loongarch64", "loongarch64"),
        ("loongarch", "loongarch64"),
    ):
        if keyword in text:
            guesses.append(label)
    return _dedupe_keep_order(guesses)


def _guess_language_mix(readme_text: str, root_entries: List[str]) -> List[str]:
    text = (readme_text + "\n" + "\n".join(root_entries)).lower()
    guesses = []
    if any(x in text for x in ("cargo.toml", "rust", ".rs")):
        guesses.append("Rust")
    if any(x in text for x in ("makefile", ".c", ".h", "clang")):
        guesses.append("C/C++")
    if ".go" in text:
        guesses.append("Go")
    if ".zig" in text:
        guesses.append("Zig")
    return _dedupe_keep_order(guesses)


def _find_repo_docs(repo_path: str) -> List[str]:
    docs = []
    for name in ("README.md", "README.MD", "readme.md", "docs", "doc", "design", "report"):
        target = os.path.join(repo_path, name)
        if os.path.exists(target):
            docs.append(name)
    return docs


def build_repo_profile(repo_url: str, repo_path: str) -> Dict[str, Any]:
    root_entries = _list_root_entries(repo_path)
    readme_text = ""
    for readme_name in ("README.md", "README.MD", "readme.md"):
        readme_path = os.path.join(repo_path, readme_name)
        if os.path.exists(readme_path):
            readme_text = _read_head(readme_path)
            break

    config_text = "\n".join(
        _read_head(os.path.join(repo_path, name), max_chars=1500)
        for name in ("Cargo.toml", "Makefile", "rust-toolchain.toml")
        if os.path.exists(os.path.join(repo_path, name))
    )
    arch_guesses = _guess_architecture(readme_text + "\n" + config_text, root_entries)
    framework_guesses = _guess_framework(readme_text + "\n" + config_text, root_entries)
    core_paths = _walk_core_paths(repo_path, max_depth=2)
    entry_candidates = _dedupe_keep_order([
        symbol for symbol in ("_start", "start", "rust_main", "kernel_main", "main", "trap_handler")
        if symbol in (readme_text + "\n" + config_text)
    ])

    return {
        "repo_url": repo_url,
        "repo_path": repo_path,
        "framework_guess": framework_guesses,
        "arch_guess": arch_guesses,
        "board_guess": _dedupe_keep_order([
            board
            for board in ("k210", "visionfive", "jh7110", "qemu", "virt")
            if board in (readme_text + "\n" + config_text).lower()
        ]),
        "language_mix": _guess_language_mix(readme_text + "\n" + config_text, root_entries),
        "core_paths": core_paths,
        "entry_candidates": entry_candidates,
        "doc_paths": _find_repo_docs(repo_path),
        "history_available": os.path.isdir(os.path.join(repo_path, ".git")),
        "root_entries": root_entries[:80],
        "readme_summary": _norm(readme_text[:800]),
    }


def extract_stage_questions(prompt: str) -> List[str]:
    questions: List[str] = []
    for raw in prompt.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- "):
            candidate = re.sub(r"^\-\s*", "", line).strip()
            if len(candidate) >= 4:
                questions.append(candidate)
    return _dedupe_keep_order(questions[:12])


def _match_stage_hints(stage_id: str) -> Dict[str, List[str]]:
    if stage_id in STAGE_HINTS:
        return STAGE_HINTS[stage_id]
    for prefix, hints in STAGE_HINTS.items():
        if prefix in stage_id:
            return hints
    return {
        "seed_paths": ["kernel", "os", "arch", "platform", "README.md"],
        "entry_symbols": ["main", "kernel_main", "rust_main"],
        "evidence_targets": [],
    }


def infer_seed_paths(stage_id: str, repo_profile: Dict[str, Any], global_memory: Dict[str, Any]) -> List[str]:
    hints = _match_stage_hints(stage_id)
    seeds = list(hints.get("seed_paths", []))
    for path in repo_profile.get("core_paths", []):
        lower = path.lower()
        if any(token in lower for token in ("arch", "mm", "trap", "task", "fs", "driver", "net", "sync")):
            seeds.append(path)
    for path in global_memory.get("mentioned_paths", []):
        seeds.append(path)
    return _dedupe_keep_order(seeds[:12])


def infer_entry_symbols(stage_id: str, repo_profile: Dict[str, Any]) -> List[str]:
    hints = _match_stage_hints(stage_id)
    return _dedupe_keep_order(list(hints.get("entry_symbols", [])) + repo_profile.get("entry_candidates", []))[:10]


def build_review_checklist(stage_type: str, must_cover: List[str]) -> List[str]:
    checklist = [
        "关键问题是否回答",
        "重要结论是否给出源码路径",
        "是否避免将 README 当成实现证据",
        "是否标出未实现/桩函数",
    ]
    if stage_type == "fine_compare":
        checklist.extend([
            "是否区分代码相似与设计相似",
            "是否给出量化或结构化对比证据",
        ])
    if must_cover:
        checklist.append(f"must_cover_count={len(must_cover)}")
    return checklist


def estimate_context_budget(stage_id: str) -> Dict[str, int]:
    base = {
        "max_prev_section_chars": 6000,
        "max_seed_paths": 8,
        "max_evidence_items": 12,
        "max_memory_items": 8,
    }
    if "01_overview" in stage_id:
        base["max_prev_section_chars"] = 12000
        base["max_evidence_items"] = 18
    if "13_history" in stage_id:
        base["max_prev_section_chars"] = 4000
    return base


def plan_stage(state: StageState, repo_profile: Dict[str, Any], global_memory: Dict[str, Any]) -> PlanSpec:
    must_cover = extract_stage_questions(state.stage_prompt)
    hints = _match_stage_hints(state.stage_id)
    goal_line = next((line.strip() for line in state.stage_prompt.splitlines() if line.strip()), state.stage_title)
    return PlanSpec(
        stage_id=state.stage_id,
        goal=_norm(goal_line)[:120],
        must_cover=must_cover,
        evidence_targets=hints.get("evidence_targets", []),
        seed_paths=infer_seed_paths(state.stage_id, repo_profile, global_memory),
        framework_guess=repo_profile.get("framework_guess", []),
        arch_guess=repo_profile.get("arch_guess", []),
        entry_symbols=infer_entry_symbols(state.stage_id, repo_profile),
        repo_hotspots=repo_profile.get("core_paths", [])[:10],
        preferred_tools=["rag_search_code", "lsp_get_call_graph", "lsp_get_definition", "read_code_segment"],
        avoid_tools=["blind_read_large_files", "full_repo_scan_with_read_code_segment"],
        review_checklist=build_review_checklist(state.stage_type, must_cover),
        context_budget=estimate_context_budget(state.stage_id),
    )


def _shorten(text: str, limit: int = 400) -> str:
    text = _norm(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def build_dynamic_context(
    state: StageState,
    repo_profile: Dict[str, Any],
    global_memory: Dict[str, Any],
) -> Dict[str, Any]:
    related_sections = global_memory.get("section_summaries", {}) or {}
    max_sections = state.plan.context_budget.get("max_memory_items", 8) if state.plan else 8
    recent_sections = [
        {"stage_id": sid, "summary": _shorten(summary, 280)}
        for sid, summary in list(related_sections.items())[-max_sections:]
    ]
    return {
        "repo_profile": {
            "framework_guess": repo_profile.get("framework_guess", []),
            "arch_guess": repo_profile.get("arch_guess", []),
            "language_mix": repo_profile.get("language_mix", []),
            "core_paths": repo_profile.get("core_paths", [])[:10],
            "board_guess": repo_profile.get("board_guess", []),
        },
        "plan_summary": state.plan.to_dict() if state.plan else {},
        "recent_sections": recent_sections,
        "repair_context": state.metadata.get("repair_context", []),
        "evidence_cache": [item.to_dict() for item in state.evidence_index[: state.plan.context_budget.get("max_evidence_items", 12)]],
        "external_background": global_memory.get("external_background", {}),
    }


def render_plan_context(state: StageState) -> str:
    plan = state.plan
    dynamic_context = state.dynamic_context or {}
    if not plan:
        return ""
    lines = [
        "## 阶段执行计划（请先按此计划收集证据，再写报告）",
        f"- stage_id: {plan.stage_id}",
        f"- goal: {plan.goal}",
        f"- must_cover: {', '.join(plan.must_cover[:8]) or '无'}",
        f"- evidence_targets: {', '.join(plan.evidence_targets[:8]) or '无'}",
        f"- seed_paths: {', '.join(plan.seed_paths[:8]) or '无'}",
        f"- framework_guess: {', '.join(plan.framework_guess[:6]) or '未知'}",
        f"- arch_guess: {', '.join(plan.arch_guess[:6]) or '未知'}",
        f"- entry_symbols: {', '.join(plan.entry_symbols[:8]) or '无'}",
        f"- preferred_tools: {' -> '.join(plan.preferred_tools)}",
        f"- avoid_tools: {', '.join(plan.avoid_tools)}",
        "",
        "## 动态上下文摘要",
        f"- recent_sections: {len(dynamic_context.get('recent_sections', []))}",
        f"- repair_actions: {len(dynamic_context.get('repair_context', []))}",
        f"- cached_evidence: {len(dynamic_context.get('evidence_cache', []))}",
    ]
    recent_sections = dynamic_context.get("recent_sections", [])
    if recent_sections:
        lines.append("")
        lines.append("### 最近章节摘要")
        for item in recent_sections:
            lines.append(f"- {item['stage_id']}: {item['summary']}")
    repair_context = dynamic_context.get("repair_context", [])
    if repair_context:
        lines.append("")
        lines.append("### 本轮修补要求")
        for action in repair_context[:6]:
            lines.append(f"- {action}")
    return "\n".join(lines).strip()


def build_coarse_preplan(target_name: str, target_sections_dir: str) -> Dict[str, Any]:
    section_files = []
    if os.path.isdir(target_sections_dir):
        for name in sorted(os.listdir(target_sections_dir)):
            if name.endswith(".md"):
                section_files.append(name)
    overview_text = ""
    for name in section_files:
        if name.startswith("01_"):
            overview_text = _read_head(os.path.join(target_sections_dir, name), 2500)
            break
    lowered = overview_text.lower()
    framework_guess = _guess_framework(overview_text, section_files)
    arch_guess = _guess_architecture(overview_text, section_files)
    critical_dims = []
    if any(x in lowered for x in ("arceos", "rcore", "xv6")):
        critical_dims.append("framework")
    if any(x in lowered for x in ("buddy", "bitmap", "allocator")):
        critical_dims.append("allocator")
    if any(x in lowered for x in ("trapframe", "syscall")):
        critical_dims.append("trapframe/syscall")
    if not critical_dims:
        critical_dims = ["framework", "allocator", "syscall_count_real"]
    return {
        "target": target_name,
        "framework_guess": framework_guess,
        "arch_guess": arch_guess,
        "critical_dims": _dedupe_keep_order(critical_dims),
        "available_sections": section_files,
    }
