from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import ValidationReport


@dataclass(frozen=True)
class TaxonomyModule:
    module_id: str
    title: str
    required_checks: tuple[str, ...]


REQUIRED_MODULES: dict[str, TaxonomyModule] = {
    "build-runtime": TaxonomyModule(
        "build-runtime",
        "构建与运行",
        (
            "make/cargo/qemu run target",
            "linker script",
            "platform config",
            "rootfs/image packaging",
            "board/qemu/development-board switch",
        ),
    ),
    "boot-trap-syscall": TaxonomyModule(
        "boot-trap-syscall",
        "启动、Trap 与系统调用",
        (
            "boot entry",
            "early console",
            "trap/exception dispatch",
            "syscall dispatch",
            "timer interrupt",
            "context switch",
            "user/kernel trap split",
        ),
    ),
    "process-exec": TaxonomyModule(
        "process-exec",
        "进程、调度与执行",
        (
            "task/process structure",
            "scheduler",
            "fork/clone",
            "exec",
            "wait/exit",
            "signal/kill",
            "pipe/shared IPC",
        ),
    ),
    "memory-vm": TaxonomyModule(
        "memory-vm",
        "内存、虚拟内存与页缓存",
        (
            "physical allocator",
            "kernel heap",
            "page table",
            "kernel address space",
            "user address space",
            "copy user",
            "page fault",
            "lazy allocation/COW",
            "mmap",
            "page cache",
        ),
    ),
    "fs-io": TaxonomyModule(
        "fs-io",
        "文件系统与 I/O",
        (
            "file descriptor table",
            "file/VFS abstraction",
            "path/inode/dentry",
            "pipe/proc/devfs",
            "FAT/FAT32",
            "ext4",
            "ramfs/rootfs",
            "block device",
            "block cache",
            "page-cache integration",
        ),
    ),
    "device-platform": TaxonomyModule(
        "device-platform",
        "设备与平台",
        (
            "UART",
            "interrupt controller",
            "timer device",
            "VirtIO block",
            "SD/development-board block device",
            "platform bus/device tree if present",
        ),
    ),
    "network-stack": TaxonomyModule(
        "network-stack",
        "网络栈",
        (
            "socket API",
            "TCP/UDP or supported transport",
            "network device",
            "packet buffer",
            "loopback",
            "fd integration",
        ),
    ),
    "smp-concurrency": TaxonomyModule(
        "smp-concurrency",
        "多核与并发",
        (
            "SMP bringup",
            "per-cpu state",
            "inter-processor coordination if present",
            "spinlock",
            "mutex/sleeplock",
            "wait queue",
            "semaphore",
            "atomic/refcount",
            "scheduler interaction with multicore",
        ),
    ),
    "user-abi-compat": TaxonomyModule(
        "user-abi-compat",
        "用户 ABI 与兼容层",
        (
            "ELF ABI",
            "syscall wrapper",
            "init process",
            "user tests",
            "POSIX/Linux syscall compatibility",
            "libc-test/LTP/BusyBox support",
        ),
    ),
    "test-risk-surface": TaxonomyModule(
        "test-risk-surface",
        "测试与风险面",
        (
            "contest runner",
            "test harness",
            "LTP/libc-test bridge",
            "hardcoded pass output",
            "argv/test-name special casing",
            "syscall/exec special casing",
            "prompt injection surface",
        ),
    ),
}

OPTIONAL_FEATURES = {
    "futex",
    "scheduler class",
    "priority scheduler",
    "cfs-like policy",
    "slab",
    "object cache",
    "swap",
    "journal beyond ext4 baseline",
    "PCI",
    "DMA",
    "GPU",
    "input",
    "workqueue",
    "softirq",
    "timer wheel",
    "randomness",
    "power management",
    "kernel command line",
    "W^X",
    "backtrace",
    "tracing",
}

DELETED_FEATURES = {
    "namespace",
    "cgroup",
    "RCU",
    "netfilter",
    "Unix domain socket",
    "dynamic linker",
    "VDSO",
    "module loader",
    "seccomp",
    "KASLR",
    "stack protector",
    "module signature",
    "perf counter",
    "GDB stub",
    "sanitizer",
    "virtualization",
}


def required_module_ids() -> list[str]:
    return list(REQUIRED_MODULES)


def validate_taxonomy() -> ValidationReport:
    report = ValidationReport()
    required_terms = " ".join(
        [module.module_id for module in REQUIRED_MODULES.values()]
        + [module.title for module in REQUIRED_MODULES.values()]
        + [check for module in REQUIRED_MODULES.values() for check in module.required_checks]
    ).lower()
    must_have = {
        "network": ["network-stack", "socket API"],
        "page cache": ["page cache", "page-cache integration"],
        "ext4": ["ext4"],
        "smp": ["SMP bringup", "multicore", "per-cpu state"],
    }
    for label, needles in must_have.items():
        if not any(needle.lower() in required_terms for needle in needles):
            report.add("taxonomy.required_missing", f"required taxonomy must include {label}")
    for feature in DELETED_FEATURES:
        if feature.lower() in required_terms:
            report.add("taxonomy.deleted_in_required", f"deleted feature appears in required taxonomy: {feature}")
    return report


def scan_deleted_features(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(feature for feature in DELETED_FEATURES if feature.lower() in lowered)


def make_task_files(
    work: dict,
    base: dict | None = None,
    evidence_ids: Iterable[str] = (),
    base_context_evidence_ids: Iterable[str] = (),
    module_evidence: dict[str, list[str]] | None = None,
    module_doc_claim_evidence: dict[str, list[str]] | None = None,
) -> list[dict]:
    base = base or {}
    fallback_evidence = list(evidence_ids)
    base_context = list(base_context_evidence_ids)
    module_evidence = module_evidence or {}
    module_doc_claim_evidence = module_doc_claim_evidence or {}
    packets = []
    for module in REQUIRED_MODULES.values():
        relevant = list(dict.fromkeys([*base_context, *module_evidence.get(module.module_id, fallback_evidence)]))
        packets.append(
            {
                "task_id": f"module-{module.module_id}",
                "work": {
                    "work_id": work.get("work_id", ""),
                    "display_name": work.get("display_name", ""),
                },
                "base": {
                    "work_id": base.get("work_id", ""),
                    "display_name": base.get("display_name", ""),
                    "direction": base.get("direction", ""),
                    "confidence": base.get("confidence", ""),
                },
                "module_id": module.module_id,
                "module_title": module.title,
                "required_checks": list(module.required_checks),
                "base_context_evidence_ids": base_context,
                "relevant_evidence_ids": relevant,
                "module_doc_claim_evidence_ids": module_doc_claim_evidence.get(module.module_id, []),
                "required_contract": "module_review",
                "forbidden_claims": [
                    "没有 evidence 不得声称原创、抄袭、继承或重大改写。",
                    "不得描述 deleted taxonomy features。",
                    "正文不得使用机器 repo id、裸 fork 数字或旧 clone 名。",
                    "模块 agent 不得自行决定同届抄袭方向；方向由 base-lineage-reviewer 或 contradiction-arbiter 裁决。",
                ],
                "quality_gate": {
                    "min_code_anchors": 3,
                    "requires_base_delta": True,
                    "requires_evidence_chips": True,
                    "exclude_scope_categories": ["framework_base", "third_party", "test_payload", "generated"],
                    "must_discuss_external_adaptation_when_present": True,
                },
            }
        )
    return packets
