from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


def load_kernel_glossary(vocab: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build the local concept glossary for kernel design tree nodes.

    Glossary entries are conceptual aids, not source evidence. Keys are both
    full claim tags (`Node.Id:tag`) and bare tags when unambiguous enough.
    """
    glossary: dict[str, dict[str, Any]] = {}
    overrides = _load_overrides()
    for node_id, node_vocab in vocab.items():
        if not isinstance(node_vocab, dict):
            continue
        for item in node_vocab.get("mechanisms", []) or []:
            if not isinstance(item, dict) or not item.get("tag"):
                continue
            tag = str(item["tag"])
            entry = _fallback_entry(node_id, item)
            if tag in overrides:
                entry = _merge_entry(entry, overrides[tag])
            full = f"{node_id}:{tag}"
            entry["node_id"] = node_id
            entry["tag"] = tag
            entry["full_tag"] = full
            glossary[full] = entry
            glossary.setdefault(tag, entry)
    return glossary


def glossary_lookup(glossary: dict[str, dict[str, Any]], tag: str, node_id: str | None = None) -> dict[str, Any]:
    raw = str(tag or "").strip()
    if not raw:
        return {"status": "not_found", "query": tag}
    candidates = []
    if node_id and ":" not in raw:
        candidates.append(f"{node_id}:{raw}")
    candidates.append(raw)
    if ":" in raw:
        candidates.append(raw.split(":", 1)[1])
    for key in candidates:
        if key in glossary:
            entry = deepcopy(glossary[key])
            entry["status"] = "ok"
            entry["evidence_warning"] = "Glossary is a concept aid only; it is not source evidence and cannot support a claim by itself."
            return entry
    return {
        "status": "not_found",
        "query": raw,
        "evidence_warning": "Glossary lookup failed; use source/LSP evidence for any claim.",
    }


def compact_glossary_for_node(glossary: dict[str, dict[str, Any]], node_id: str, tags: list[str], limit: int = 12) -> list[dict[str, Any]]:
    rows = []
    for tag in tags[:limit]:
        entry = glossary_lookup(glossary, tag, node_id)
        if entry.get("status") != "ok":
            continue
        rows.append({
            "tag": entry["tag"],
            "title_zh": entry.get("title_zh", ""),
            "title_en": entry.get("title_en", ""),
            "definition_zh": entry.get("definition_zh") or entry.get("description_zh", ""),
            "definition_en": entry.get("definition_en") or entry.get("description_en", ""),
            "compare_role": entry.get("compare_role", ""),
            "category": entry.get("category", ""),
        })
    return rows


def _load_overrides() -> dict[str, dict[str, Any]]:
    path = Path(__file__).with_name("kernel_glossary.json")
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries", data if isinstance(data, dict) else {})
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)}


def _fallback_entry(node_id: str, item: dict[str, Any]) -> dict[str, Any]:
    tag = str(item.get("tag", ""))
    title = _title_from_tag(tag)
    raw_title = tag.replace("_", " ")
    zh_title = item.get("title_zh") if item.get("title_zh") != raw_title else _zh_title_from_tag(tag)
    en_title = item.get("title_en") if item.get("title_en") != tag.replace("_", " ") else title
    description_zh = item.get("description_zh")
    description_en = item.get("description_en")
    # No boilerplate: when there is no real definition, leave it empty so the
    # judge page omits the concept line instead of echoing "属于 X 的内核设计
    # 机制" back at the reader. Real definitions come from kernel_glossary.json.
    if description_zh == raw_title:
        description_zh = ""
    if description_en == raw_title:
        description_en = ""
    return {
        "tag": tag,
        "node_id": node_id,
        "compare_role": item.get("compare_role", "primary"),
        "category": item.get("category", "mechanism"),
        "aliases": item.get("aliases", []),
        "title_zh": zh_title or title,
        "title_en": en_title or title,
        "definition_zh": description_zh or "",
        "definition_en": description_en or "",
        "recognition_cues": item.get("aliases", []),
        "include": [],
        "exclude": [],
        "confusions": [],
        "c_example": "",
        "rust_example": "",
    }


def _merge_entry(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in override.items():
        if value not in (None, "", []):
            out[key] = deepcopy(value)
    return out


def _title_from_tag(tag: str) -> str:
    acronyms = {
        "sv39": "Sv39", "x86": "x86", "x86_64": "x86_64", "pte": "PTE", "satp": "satp",
        "tlb": "TLB", "sbi": "SBI", "rustsbi": "RustSBI", "qemu": "QEMU", "uart": "UART",
        "virtio": "VirtIO", "pci": "PCI", "dma": "DMA", "fat32": "FAT32", "ext4": "ext4",
        "vfs": "VFS", "elf": "ELF", "posix": "POSIX", "vdso": "VDSO", "ipc": "IPC",
        "rcu": "RCU", "kaslr": "KASLR", "gdb": "GDB", "tcp": "TCP", "udp": "UDP",
    }
    parts = tag.split("_")
    return " ".join(acronyms.get(p.lower(), p) for p in parts)


def _zh_title_from_tag(tag: str) -> str:
    terms = {
        "three": "三级", "four": "四级", "level": "", "page": "页", "table": "表", "pagetable": "页表",
        "physical": "物理", "allocator": "分配器", "free": "空闲", "list": "链表", "buddy": "伙伴系统",
        "kernel": "内核", "heap": "堆", "object": "对象", "cache": "缓存", "walk": "遍历", "map": "映射",
        "unmap": "取消映射", "flag": "标志位", "protection": "保护", "switch": "切换", "flush": "刷新",
        "process": "进程", "task": "任务", "thread": "线程", "global": "全局", "scheduler": "调度器",
        "scheduling": "调度", "round": "轮转", "robin": "", "priority": "优先级", "fair": "公平",
        "deadline": "截止期", "fork": "Fork", "clone": "Clone", "copy": "复制", "exec": "Exec",
        "wait": "等待", "exit": "退出", "zombie": "僵尸", "signal": "信号", "pipe": "管道",
        "shared": "共享", "memory": "内存", "message": "消息", "queue": "队列", "syscall": "系统调用",
        "number": "号", "dispatch": "分发", "trap": "Trap", "vector": "向量", "timer": "定时器",
        "interrupt": "中断", "context": "上下文", "assembly": "汇编", "user": "用户", "address": "地址",
        "space": "空间", "lazy": "懒", "allocation": "分配", "fault": "缺页", "write": "写",
        "read": "读", "file": "文件", "backed": "后备", "anonymous": "匿名", "mapping": "映射",
        "copyin": "copyin", "copyout": "copyout", "validation": "校验", "pointer": "指针", "inode": "Inode",
        "dentry": "Dentry", "directory": "目录", "entry": "入口", "lookup": "查找", "path": "路径",
        "resolution": "解析", "block": "块", "buffer": "缓冲", "journal": "日志", "transaction": "事务",
        "log": "日志", "device": "设备", "driver": "驱动", "console": "控制台", "ring": "环",
        "descriptor": "描述符", "controller": "控制器", "socket": "Socket", "packet": "数据包",
        "spinlock": "自旋锁", "mutex": "互斥锁", "semaphore": "信号量", "sleep": "睡眠",
        "wakeup": "唤醒", "channel": "通道", "atomic": "原子", "refcount": "引用计数",
        "lock": "锁", "logging": "日志", "panic": "Panic", "backtrace": "回溯", "tracing": "跟踪",
        "binary": "二进制", "loader": "装载器", "shell": "Shell", "test": "测试", "programs": "程序",
        "privilege": "特权级", "isolation": "隔离", "randomization": "随机化", "stack": "栈",
        "module": "模块", "signed": "签名", "check": "校验", "work": "工作", "deferred": "延迟",
        "power": "电源", "management": "管理", "command": "命令", "line": "行", "virtual": "虚拟",
        "hypervisor": "Hypervisor", "container": "容器", "namespace": "命名空间", "cgroup": "控制组",
        "direct": "直接", "high": "高", "half": "半区", "per": "每", "frame": "页框", "bitmap": "位图",
        "simple": "简单", "bump": "碰撞式", "dynamic": "动态", "linker": "链接器", "rootfs": "根文件系统",
        "image": "镜像", "boot": "启动", "handoff": "交接", "early": "早期", "main": "主入口",
        "state": "状态", "machine": "机", "policy": "策略", "interface": "接口", "system": "系统"
    }
    acronyms = {
        "sv39": "Sv39", "x86": "x86", "x86_64": "x86_64", "pte": "PTE", "satp": "satp",
        "tlb": "TLB", "sbi": "SBI", "rustsbi": "RustSBI", "qemu": "QEMU", "uart": "UART",
        "virtio": "VirtIO", "pci": "PCI", "dma": "DMA", "fat32": "FAT32", "ext4": "ext4",
        "vfs": "VFS", "elf": "ELF", "posix": "POSIX", "vdso": "VDSO", "ipc": "IPC",
        "rcu": "RCU", "kaslr": "KASLR", "gdb": "GDB", "tcp": "TCP", "udp": "UDP",
    }
    words = [acronyms.get(p.lower(), terms.get(p.lower(), p)) for p in tag.split("_")]
    return " ".join(word for word in words if word).strip()
