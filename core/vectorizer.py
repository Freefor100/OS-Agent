"""
OS-Agent C: 特征提取与本地向量化模块

从 OS-Agent D 生成的 section 报告中提取结构化特征摘要，
再通过本地 Embedding 模型转换为向量表示。
"""
import os
import re
import json
import logging
import threading
import time
from typing import Dict, List, Optional

import numpy as np
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from core.error_handling import ErrorType, RetryConfig, classify_error, calculate_backoff

load_dotenv()
logger = logging.getLogger("vectorizer")
STRUCT_FEATURE_SCHEMA_VERSION = 3

# ---------------------------------------------------------------------------
# 7 维度特征提取 Prompt
# ---------------------------------------------------------------------------
DIMENSION_MAP = {
    "D1_tech_stack": {
        "sections": ["01_"],
        "prompt": (
            "从以下项目概览报告中提取一段 100-200 字的技术特征摘要。\n\n"
            "【必须涵盖以下要素】：\n"
            "1. 编程语言及版本（Rust edition / C standard / 是否 no_std 环境）\n"
            "2. 目标架构完整列表（RISC-V / x86_64 / AArch64 / LoongArch64）\n"
            "3. 内核类型（宏内核 / 微内核 / unikernel / 混合内核）\n"
            "4. 基础框架来源（rCore / ArceOS / xv6 / 完全自研）及版本\n"
            "5. 关键第三方 crate/库依赖列表（如 smoltcp, virtio-drivers, axalloc 等）\n"
            "6. 构建系统（Makefile / Cargo / CMake）及主要构建命令\n\n"
            "【区分原则】：\n"
            "- 明确区分项目名称与底层框架名称（如'基于 ArceOS 开发的 XXX OS'）\n"
            "- 如果多个架构仅在 README 中提及但代码目录不存在，需标注'文档提及但未见架构代码'\n\n"
            "输出纯文本摘要，不要 Markdown 格式标记。"
        ),
        "weight": 0.08,
    },
    "D2_boot_arch": {
        "sections": ["02_"],
        "prompt": (
            "从以下启动流程报告中提取特征摘要（100-150 字）。\n\n"
            "【必须涵盖】：\n"
            "1. 完整启动链描述（如 SBI→U-Boot→Kernel，或 BIOS→Bootloader→Kernel）\n"
            "2. CPU 模式切换路径（如 RISC-V M-Mode→S-Mode，x86 实模式→长模式）\n"
            "3. MMU 启用方式与页表初始化时机\n"
            "4. 启动入口文件的确切路径（如 arch/riscv/entry.S 或 #[entry] 属性标注）\n"
            "5. FPU 初始化状态（是否启用浮点单元）\n"
            "6. 多平台适配情况（StarFive VisionFive2 / LoongArch 等特殊启动流程）\n\n"
            "【注意】：如果报告明确指出某些启动阶段'未发现'或'未实现'，在摘要中如实保留。\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.06,
    },
    "D3_memory": {
        "sections": ["03_"],
        "prompt": (
            "从以下内存管理报告中提取特征摘要（120-200 字）。\n\n"
            "【必须涵盖】：\n"
            "1. 物理内存分配器类型（Buddy System / Bitmap / SLAB / 外部 crate 如 buddy_system_allocator）\n"
            "2. 页表结构（SV39 / SV48 / 4 级页表）及关键结构体名（PageTable / MemorySet 等）\n"
            "3. 堆分配器实现（GlobalAlloc / TLSF / Slab 等）\n"
            "4. 高级特性逐项列出状态（已实现/桩函数/未实现）：\n"
            "   - 写时复制 CoW、懒分配 Lazy Allocation、页面置换 Swap\n"
            "   - 大页 HugePage（2M/1G）、mmap（MAP_FIXED/MAP_ANON 支持程度）\n"
            "   - 共享内存 SharedMem、反向映射 rmap\n"
            "5. 缺页异常处理链关键函数名（handle_page_fault → alloc_frame → map_page）\n"
            "6. 用户指针安全验证机制（UserInPtr/verify_area）\n\n"
            "【严格要求】：\n"
            "- 如果某特性的函数体为空/返回 unimplemented!/todo!/仅返回 Ok(0)，标注为'桩函数'\n"
            "- 区分'特质定义存在'与'impl 代码真正实现'\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.15,
    },
    "D4_process_sched": {
        "sections": ["04_"],
        "prompt": (
            "从以下进程调度报告中提取特征摘要（120-200 字）。\n\n"
            "【必须涵盖】：\n"
            "1. 执行实体模型（纯 Task / Process+Thread 分离 / 仅 Thread）\n"
            "   - 关键结构体名称（TaskInner / ProcessInner / ThreadControlBlock）\n"
            "2. 调度算法及实现方式（FIFO / Round-Robin / CFS / Stride / 优先级调度）\n"
            "   - 是否有多调度器支持（通过 feature flag 切换）\n"
            "3. 上下文切换机制（汇编实现 switch.S 保存的寄存器数量、是否支持浮点上下文）\n"
            "4. 进程间关系：是否有进程组 ProcessGroup / 会话 Session / PGID/SID 管理\n"
            "5. 信号机制（Signal）实现程度：是否支持 sigaction/kill/tgkill、用户态信号跳板 trampoline\n"
            "6. Futex 支持状态（已实现/桩函数/未实现）\n"
            "7. POSIX 资源限制 rlimit 支持情况\n\n"
            "【严格要求】：\n"
            "- 如果 schedule() 仅实现 FIFO 但文档声称支持 CFS，标注'代码仅有 FIFO'\n"
            "- 区分 fork 是否真正复制了地址空间，还是仅创建了任务控制块\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.15,
    },
    "D5_trap_syscall": {
        "sections": ["05_"],
        "prompt": (
            "从以下中断与系统调用报告中提取特征摘要（120-180 字）。\n\n"
            "【必须涵盖】：\n"
            "1. Trap 入口实现方式（汇编 trap.S / Rust #[naked] / 纯 Rust 内联汇编）\n"
            "2. TrapFrame 结构体包含的寄存器数量和总字节数\n"
            "3. 系统调用分发方式（Rust match / C switch / 函数指针表）\n"
            "4. 已实现的系统调用总数及覆盖范围（文件IO/进程管理/内存管理/网络）\n"
            "5. 接口/实现分离设计（sys_xxx 接口层 vs sys_xxx_impl 实现层）\n"
            "6. 信号处理时机（Trap 返回前检查 / 单独信号检查点）\n"
            "7. 缺页异常与 CoW/Lazy 的关联（是否在 page_fault 中触发）\n"
            "8. 用户指针安全包装（UserInPtr / UserOutPtr 类型）\n\n"
            "【严格要求】：\n"
            "- Stub 检测：检查核心 syscall（sys_clone/sys_exec/sys_mmap）是否仅返回 0 或 ENOSYS\n"
            "- 明确区分'已注册但桩实现'与'完整功能实现'的 syscall 数量\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.10,
    },
    "D6_filesystem": {
        "sections": ["06_"],
        "prompt": (
            "从以下文件系统报告中提取特征摘要（120-200 字）。\n\n"
            "【必须涵盖】：\n"
            "1. VFS 抽象层设计（Trait 定义 / 函数指针 / 无 VFS 直接访问 FS）\n"
            "   - 核心 Trait/接口名称（VfsNode / File / Inode / Dentry / SuperBlock）\n"
            "2. 具体文件系统支持列表及来源：\n"
            "   - FAT32（自研 / fatfs crate / 外部库）\n"
            "   - ext4（自研 / ext4_rs crate / 未支持）\n"
            "   - RamFS / TmpFS / DevFS / ProcFS / SysFS\n"
            "3. 文件描述符表设计（Global 还是 Per-Process，FdTable 结构位置）\n"
            "4. Pipe 管道实现（环形缓冲区 / 简单字节流 / 未实现）\n"
            "5. Socket 网络 IO 支持程度\n"
            "6. mmap 实现深度（MAP_FIXED/MAP_ANON/MAP_SHARED 支持、零拷贝能力）\n"
            "7. poll/select/epoll 支持状态\n"
            "8. 文件打开流程的 VFS 四大数据结构协同方式\n\n"
            "【严格要求】：\n"
            "- 区分'引用了外部 fatfs crate'与'自己实现了 FAT32 解析'\n"
            "- 如果 sys_mmap 只返回 Ok(0) 没有处理标志位，标注为'桩实现'\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.12,
    },
    "D7_device_driver": {
        "sections": ["07_"],
        "prompt": (
            "从以下设备驱动与硬件抽象报告中提取特征摘要（100-150 字）。\n\n"
            "【必须涵盖】：\n"
            "1. 驱动框架设计（Driver Trait / 注册机制 / 组件化选择）\n"
            "2. 设备发现方式（Device Tree 解析 / PCI 枚举 / 硬编码地址）\n"
            "3. 支持的设备列表：\n"
            "   - UART/串口（16550 / PL011 / SBI 控制台）\n"
            "   - 块设备（VirtIO-Blk / SD卡 / NVMe）\n"
            "   - 网络设备（VirtIO-Net / E1000 / ixgbe）\n"
            "   - GPU/输入设备（如有）\n"
            "4. 中断控制器驱动（PLIC / CLINT / APIC / GIC）\n"
            "5. 组件化构建配置（Cargo features / Kconfig 选择不同驱动）\n"
            "6. 目标平台/开发板支持列表\n\n"
            "【注意】：如果设备'仅在 QEMU 上测试'，需标注。\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.06,
    },
    "D8_sync_ipc": {
        "sections": ["08_"],
        "prompt": (
            "从以下同步互斥与 IPC 报告中提取特征摘要（100-150 字）。\n\n"
            "【必须涵盖】：\n"
            "1. 锁机制列表及实现方式：\n"
            "   - SpinLock（是否禁中断）、Mutex（是否有等待队列）\n"
            "   - RwLock、Semaphore\n"
            "   - 原子操作来源（core::sync::atomic / 自定义汇编 ldxr/stxr）\n"
            "2. 等待队列 WaitQueue 实现（链表/数组/条件变量）\n"
            "3. IPC 机制逐项及实现状态（已实现/桩函数/未实现）：\n"
            "   - Pipe（是否用环形缓冲区）\n"
            "   - 消息队列 MessageQueue（sys_msgget 是否有完整队列操作逻辑）\n"
            "   - 共享内存 SharedMem（SharedMemoryManager 实现）\n"
            "   - 信号量 Semaphore（sys_semget/semop）\n"
            "   - 信号 Signal 作为 IPC（sys_kill 分发机制）\n"
            "4. Futex 实现（futex_wait/futex_wake 完整调用链）\n\n"
            "【严格要求】：\n"
            "- 如果 sys_msgget 函数体为空或仅返回 Ok(0)，标注'桩函数'\n"
            "- 区分'有接口定义'与'完整的队列操作实现'\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.08,
    },
    "D9_smp_security": {
        "sections": ["09_", "10_"],
        "prompt": (
            "从以下多核支持与安全机制报告中提取特征摘要（120-180 字）。\n\n"
            "【多核部分必须涵盖】：\n"
            "1. 多核架构类型（SMP / AMP / 仅单核）\n"
            "2. Secondary CPU 启动流程（smp_boot / __cpu_up 实现）\n"
            "3. 核间中断 IPI 机制（send_ipi / ipi_handler）\n"
            "4. Per-CPU 变量设计（axns 模块 / 手动偏移 / 仅全局变量）\n"
            "5. 多核调度：负载均衡策略、CPU 亲和性\n\n"
            "【安全部分必须涵盖】：\n"
            "1. 用户态/内核态隔离（页表隔离 KPTI / SMEP/SMAP）\n"
            "2. UID/GID 权限模型：是否在 open/write/exec 等 syscall 中执行了权限检查\n"
            "   - 如果仅有 uid 字段但无 check_perm 调用，标注'仅有定义未强制执行'\n"
            "3. 安全沙箱（Seccomp/prctl）：是否为桩实现\n"
            "4. 用户指针验证（UserInPtr / verify_area / access_ok）\n"
            "5. Rust 语言级安全（所有权 / RAII / 生命周期约束）\n"
            "6. Capability / ACL 支持状态\n\n"
            "【严格要求】：如果项目不支持多核，明确写'仅支持单核'。\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.08,
    },
    "D10_net_debug": {
        "sections": ["11_", "12_"],
        "prompt": (
            "从以下网络与调试报告中综合提取特征摘要（120-180 字）。\n\n"
            "【网络部分】：\n"
            "1. 协议栈来源（smoltcp / lwip / 自研）\n"
            "2. Socket 接口支持（socket/bind/connect/sendto syscall）\n"
            "3. 支持的网卡类型（VirtIO-Net / E1000 / 仅 Loopback）\n"
            "4. 协议支持（TCP / UDP / DHCP / DNS / ICMP）\n"
            "5. 如果仅在 QEMU 或仅有回环测试，明确标注功能限制\n\n"
            "【调试部分】：\n"
            "1. 日志系统（print/log 宏实现、日志级别）\n"
            "2. Panic 处理与栈回溯（是否有真正的 Backtrace / dwarf 解析）\n"
            "3. 调试接口（交互式 Shell / GDB Stub / Monitor）\n"
            "4. 性能追踪（perf / ftrace / tracepoint）\n\n"
            "【严格要求】：\n"
            "- 如果无网络支持明确写'未实现网络功能'\n\n"
            "输出纯文本摘要。"
        ),
        "weight": 0.12,
    },
}


# ---------------------------------------------------------------------------
# Section 文件发现
# ---------------------------------------------------------------------------
def _find_section_files(sections_dir: str, prefixes: List[str]) -> List[str]:
    """根据前缀列表在 sections/ 下查找匹配的 markdown 文件。"""
    if not os.path.isdir(sections_dir):
        return []
    matched = []
    for fname in sorted(os.listdir(sections_dir)):
        if not fname.endswith(".md"):
            continue
        for prefix in prefixes:
            if fname.startswith(prefix):
                matched.append(os.path.join(sections_dir, fname))
                break
    return matched


def _save_json(path: str, payload: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_and_merge_with_stats(file_paths: List[str]):
    """读取并合并多个文件的完整内容，并返回可用于 CLI 展示的统计信息。"""
    parts = []
    file_stats = []
    for fp in file_paths:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read().strip()
            raw_len = len(raw_text)
            text = raw_text
            parts.append(text)
            file_stats.append({
                "path": fp,
                "raw_chars": raw_len,
                "sent_chars": len(text),
                "truncated": False,
            })
        except Exception as e:
            logger.warning(f"读取 {fp} 失败: {e}")
            file_stats.append({
                "path": fp,
                "raw_chars": 0,
                "sent_chars": 0,
                "truncated": False,
                "error": str(e),
            })
    merged = "\n\n---\n\n".join(parts)
    return merged, file_stats


def _get_fingerprint_stage_paths(sections_dir: str) -> Dict[str, str]:
    output_dir = os.path.dirname(sections_dir)
    stage_dir = os.path.join(output_dir, "_coarse_stage")
    return {
        "output_dir": output_dir,
        "stage_dir": stage_dir,
        "fingerprint": os.path.join(output_dir, "fingerprint.json"),
        "feature_stage": os.path.join(stage_dir, "fingerprint_features.json"),
        "struct_stage": os.path.join(stage_dir, "fingerprint_struct_features.json"),
        "embedding_stage": os.path.join(stage_dir, "fingerprint_embeddings.json"),
    }


def _is_struct_stage_cache_current(payload: Optional[dict]) -> bool:
    if not payload:
        return False
    version = payload.get("struct_features_schema_version", 1)
    return version == STRUCT_FEATURE_SCHEMA_VERSION and bool(payload.get("struct_features"))


def _is_fingerprint_cache_current(payload: Optional[dict]) -> bool:
    if not payload:
        return False
    version = payload.get("struct_features_schema_version", 1)
    return version == STRUCT_FEATURE_SCHEMA_VERSION


def _is_feature_stage_cache_complete(payload: Optional[dict], dim_ids: List[str]) -> bool:
    if not payload:
        return False
    completed_dims = payload.get("completed_dims", []) or list(
        (payload.get("features", {}) or {}).keys()
    )
    completed_dim_set = {d for d in completed_dims if d in dim_ids}
    return len(completed_dim_set) == len(dim_ids)


def _is_embedding_stage_cache_complete(payload: Optional[dict], dim_ids: List[str]) -> bool:
    if not payload:
        return False
    embeddings = payload.get("embeddings", {}) or {}
    return all(dim_id in embeddings for dim_id in dim_ids)


def _are_fingerprint_stage_caches_complete(
    feature_payload: Optional[dict],
    struct_payload: Optional[dict],
    embedding_payload: Optional[dict],
    dim_ids: List[str],
) -> bool:
    return (
        _is_feature_stage_cache_complete(feature_payload, dim_ids)
        and _is_struct_stage_cache_current(struct_payload)
        and _is_embedding_stage_cache_complete(embedding_payload, dim_ids)
    )


def get_fingerprint_stage_status(sections_dir: str, force: bool = False) -> Dict[str, object]:
    paths = _get_fingerprint_stage_paths(sections_dir)
    dim_ids = sorted(DIMENSION_MAP.keys())
    total_dims = len(dim_ids)

    if force:
        return {
            "mode": "全新构建",
            "cache_hits": [],
            "rerun_stages": [
                "维度特征摘要",
                "精确结构化特征",
                "embedding 向量",
                "最终 fingerprint.json",
            ],
        }

    fingerprint_payload = _load_json(paths["fingerprint"])
    feature_payload = _load_json(paths["feature_stage"])
    struct_payload = _load_json(paths["struct_stage"])
    embedding_payload = _load_json(paths["embedding_stage"])
    all_stage_caches_complete = _are_fingerprint_stage_caches_complete(
        feature_payload,
        struct_payload,
        embedding_payload,
        dim_ids,
    )

    if _is_fingerprint_cache_current(fingerprint_payload) and all_stage_caches_complete:
        return {
            "mode": "纯缓存加载",
            "cache_hits": [
                "维度特征摘要（已完成全部维度）",
                "精确结构化特征",
                "embedding 向量",
                "最终 fingerprint.json",
            ],
            "rerun_stages": [],
        }

    completed_dims = feature_payload.get("completed_dims", []) or list((feature_payload.get("features", {}) or {}).keys())
    completed_dim_count = len([d for d in completed_dims if d in dim_ids])
    has_struct = _is_struct_stage_cache_current(struct_payload)
    has_embedding = _is_embedding_stage_cache_complete(embedding_payload, dim_ids)

    cache_hits = []
    rerun_stages = []

    if completed_dim_count > 0:
        if completed_dim_count >= total_dims:
            cache_hits.append(f"维度特征摘要（已完成 {completed_dim_count}/{total_dims} 个维度）")
        else:
            cache_hits.append(f"维度特征摘要（已完成 {completed_dim_count}/{total_dims} 个维度）")
            rerun_stages.append(f"维度特征摘要（剩余 {total_dims - completed_dim_count}/{total_dims} 个维度）")
    else:
        rerun_stages.append("维度特征摘要")

    if has_struct:
        cache_hits.append("精确结构化特征")
    else:
        rerun_stages.append("精确结构化特征")

    if has_embedding:
        cache_hits.append("embedding 向量")
    else:
        rerun_stages.append("embedding 向量")

    if _is_fingerprint_cache_current(fingerprint_payload):
        cache_hits.append("最终 fingerprint.json（存在，但因阶段缓存缺失将重组）")
    rerun_stages.append("最终 fingerprint.json")

    mode = "断点续跑" if cache_hits else "全新构建"
    return {
        "mode": mode,
        "cache_hits": cache_hits,
        "rerun_stages": rerun_stages,
    }


# ---------------------------------------------------------------------------
# LLM 结构化特征提取
# ---------------------------------------------------------------------------
def _get_llm():
    """复用项目已有的 LLM 配置。"""
    model_name = os.environ.get("MODEL_NAME", "deepseek/deepseek-v3.2")
    return ChatOpenAI(
        model=model_name,
        temperature=0,
        request_timeout=240,
        max_retries=0,
    )


def _get_llm_model_name() -> str:
    return os.environ.get("MODEL_NAME", "deepseek/deepseek-v3.2")


def _extract_token_usage(response) -> Dict[str, int]:
    metadata = getattr(response, "response_metadata", {}) or {}
    usage = metadata.get("token_usage", {}) or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def _merge_token_usage(base: Dict[str, int], delta: Dict[str, int]) -> Dict[str, int]:
    return {
        "prompt_tokens": int(base.get("prompt_tokens", 0)) + int(delta.get("prompt_tokens", 0)),
        "completion_tokens": int(base.get("completion_tokens", 0)) + int(delta.get("completion_tokens", 0)),
        "total_tokens": int(base.get("total_tokens", 0)) + int(delta.get("total_tokens", 0)),
    }


def _get_request_timeout_seconds(llm) -> Optional[float]:
    timeout = getattr(llm, "request_timeout", None)
    if timeout is None:
        return None
    try:
        return float(timeout)
    except (TypeError, ValueError):
        return None


def _invoke_with_retry(llm, prompt: str, label: str):
    retry_count = 0
    timeout_seconds = _get_request_timeout_seconds(llm)
    while True:
        try:
            return llm.invoke(prompt)
        except Exception as e:
            error_type = classify_error(e)
            retryable = RetryConfig.RETRYABLE_ERRORS.get(error_type, False)
            if (not retryable) or retry_count >= RetryConfig.MAX_RETRIES:
                raise
            backoff = calculate_backoff(retry_count)
            retry_count += 1
            print(f"         ❌ {label}: {error_type.value} ({type(e).__name__}: {e})")
            if error_type == ErrorType.TIMEOUT_ERROR and timeout_seconds is not None:
                print(f"         - 单次请求超时: {timeout_seconds:.0f}s")
            print(f"         🔄 正在重试 ({retry_count}/{RetryConfig.MAX_RETRIES})...")
            print(f"         ⏱️  等待 {backoff}s 后重试")
            time.sleep(backoff)


def extract_features_from_report(sections_dir: str, checkpoint_path: Optional[str] = None, force: bool = False):
    """
    读取 sections/ 下的 D 报告，按 7 个维度提取结构化特征文本。

    Args:
        sections_dir: sections/ 目录路径（如 output/nonix/sections）

    Returns:
        {dim_id: feature_text} 字典
    """
    llm = _get_llm()
    model_name = _get_llm_model_name()
    cached_payload = {} if force or not checkpoint_path else _load_json(checkpoint_path)
    completed_features = dict(cached_payload.get("features", {}) or {})
    features = dict(completed_features)
    dim_items = list(DIMENSION_MAP.items())
    ok_count = 0
    fail_count = 0
    skip_count = 0
    cache_hit_count = 0
    token_usage_total = cached_payload.get(
        "token_usage_total",
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )

    print(f"   🤖 LLM：提取维度特征摘要")
    print(f"      - 模型: {model_name}")
    print(f"      - 维度数: {len(dim_items)}")
    if completed_features:
        print(f"      - 本地阶段缓存: 已完成 {len(completed_features)}/{len(dim_items)} 个维度")

    for idx, (dim_id, cfg) in enumerate(dim_items, 1):
        if dim_id in completed_features:
            print(f"      ⏭️  [{idx}/{len(dim_items)}] {dim_id}: 使用本地阶段缓存")
            cache_hit_count += 1
            continue

        files = _find_section_files(sections_dir, cfg["sections"])
        if not files:
            logger.warning(f"[{dim_id}] 未找到匹配 section 文件 (prefix={cfg['sections']})")
            features[dim_id] = f"[未找到 {dim_id} 相关的分析报告]"
            print(f"      ⏭️  [{idx}/{len(dim_items)}] {dim_id}: 未找到匹配章节 {cfg['sections']}")
            skip_count += 1
            continue

        content, file_stats = _read_and_merge_with_stats(files)
        prompt = cfg["prompt"] + "\n\n---\n以下是分析报告内容：\n\n" + content
        t0 = time.perf_counter()
        print(f"      🚀 [{idx}/{len(dim_items)}] {dim_id}: 开始提取 (sections={cfg['sections']}, files={len(files)})")
        print(f"         发送给 LLM 的本地文件:")
        for stat in file_stats:
            rel_path = os.path.relpath(stat["path"], sections_dir).replace("\\", "/")
            if stat.get("error"):
                print(f"           - {rel_path}: 读取失败 ({stat['error']})")
            else:
                trunc_note = " [已截断]" if stat["truncated"] else ""
                print(
                    f"           - {rel_path}: 原始 {stat['raw_chars']} 字符 -> "
                    f"发送 {stat['sent_chars']} 字符{trunc_note}"
                )
        print(f"         Prompt 总长度: {len(prompt)} 字符")

        try:
            response = _invoke_with_retry(llm, prompt, dim_id)
            features[dim_id] = response.content.strip()
            completed_features[dim_id] = features[dim_id]
            usage = _extract_token_usage(response)
            token_usage_total = _merge_token_usage(token_usage_total, usage)
            print(f"      ✅ [{idx}/{len(dim_items)}] {dim_id}: {len(features[dim_id])} 字符 ({time.perf_counter() - t0:.2f}s)")
            if usage["total_tokens"] > 0:
                print(
                    f"         📄 Tokens: {usage['total_tokens']:,} "
                    f"(输入:{usage['prompt_tokens']:,} + 输出:{usage['completion_tokens']:,})"
                )
            if checkpoint_path:
                _save_json(
                    checkpoint_path,
                    {
                        "stage": "feature_summaries",
                        "sections_dir": os.path.abspath(sections_dir),
                        "features": completed_features,
                        "completed_dims": list(completed_features.keys()),
                        "token_usage_total": token_usage_total,
                    },
                )
            ok_count += 1
        except Exception as e:
            features[dim_id] = f"[提取失败: {e}]"
            print(f"      ⚠️ [{idx}/{len(dim_items)}] {dim_id}: 提取失败 ({type(e).__name__}: {e})")
            print(f"         将写入失败占位文本并继续后续维度，粗筛流程不会在这里中断。")
            fail_count += 1

    print(f"      📊 维度摘要提取完成: 成功={ok_count}, 失败={fail_count}, 跳过={skip_count}, 命中缓存={cache_hit_count}")
    if token_usage_total["total_tokens"] > 0:
        print(f"      - Token使用: {token_usage_total['total_tokens']:,}")
    return features, token_usage_total


# ---------------------------------------------------------------------------
# 本地 Embedding 模型
# ---------------------------------------------------------------------------
class LocalEmbedder:
    """
    基于 sentence-transformers 的本地 Embedding 模型。
    默认统一使用 jinaai/jina-embeddings-v2-base-code（支持 8192 长度中英代码混合，768 维）。
    """

    DEFAULT_MODEL = "jinaai/jina-embeddings-v2-base-code"

    def __init__(self, model_name: str = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        
    # 类级别缓存模型和锁
    _shared_models = {} # {model_name: model_instance}
    _global_lock = threading.Lock()

    def _load_model(self):
        if self.model_name in LocalEmbedder._shared_models:
            return
            
        with LocalEmbedder._global_lock:
            if self.model_name in LocalEmbedder._shared_models:
                return
                
            try:
                import torch
                from sentence_transformers import SentenceTransformer
                # 强制离线模式
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                
                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info(f"加载 Embedding 模型: {self.model_name} (Device: {device}, Global Load) ...")
                
                # 显式指定 dtype 和 device 以避免 meta tensor 错误，且必须 trust_remote_code=True
                # 显式指定 local_files_only=True 以阻止 trust_remote_code=True 在底层发起网络检验
                model_kwargs = {
                    "dtype": torch.float32,
                    "low_cpu_mem_usage": False,
                    "trust_remote_code": True
                }
                
                # 先在 CPU 加载再移动到 CUDA
                model = SentenceTransformer(
                    self.model_name, 
                    trust_remote_code=True,
                    local_files_only=True,
                    device="cpu", 
                    model_kwargs=model_kwargs
                )
                
                if device == "cuda":
                    logger.info(f"正在将模型移动到 {device}...")
                    model = model.to(device)
                
                LocalEmbedder._shared_models[self.model_name] = model
                logger.info(f"模型加载完成，向量维度: {model.get_sentence_embedding_dimension()}")
            except ImportError:
                raise ImportError(
                    "请安装 sentence-transformers: pip install sentence-transformers torch"
                )
            except Exception as e:
                logger.error(f"加载 Embedding 模型失败: {e}")
                raise e

    @property
    def _model(self):
        self._load_model()
        return LocalEmbedder._shared_models[self.model_name]

    def encode(self, texts: List[str]) -> np.ndarray:
        """
        将文本列表编码为向量矩阵。

        Args:
            texts: 文本列表

        Returns:
            np.ndarray of shape (len(texts), embedding_dim)
        """
        self._load_model()
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return np.array(vectors, dtype=np.float32)

    @property
    def dimension(self) -> int:
        self._load_model()
        return self._model.get_sentence_embedding_dimension()


# ---------------------------------------------------------------------------
# 结构化精确特征提取
# ---------------------------------------------------------------------------
STRUCT_FEATURE_PROMPT = """从以下 OS 项目 D 报告中提取精确特征。
严格输出 JSON，不要多余文字，不要 markdown 代码块。
每个字段从括号内候选值中选取唯一一个（勿将多个候选拼接输出）：

{
  "framework":        "ArceOS" | "rCore" | "xv6-derived" | "custom" | "unknown",
  "lang":             "Rust" | "C" | "mixed",
  "kernel_type":      "monolithic" | "microkernel" | "unikernel" | "hybrid" | "unknown",
  "arch_primary":     "riscv64" | "x86_64" | "aarch64" | "loongarch64" | "multi" | "unknown",
  "boot_flow":        "sbi_to_kernel" | "bios_to_bootloader_to_kernel" | "bootloader_to_kernel" | "direct_entry" | "unknown",
  "page_table_mode":  "sv39" | "sv48" | "4-level" | "unknown",
  "pm_allocator":     "buddy" | "bitmap" | "freelist" | "slab" | "custom" | "unknown",
  "allocator_crate":  "buddy_system_allocator" | "linked_list_allocator" | "slab_allocator" | "custom" | "unknown",
  "heap_allocator":   "slab" | "buddy" | "buddy_system_allocator" | "linked_list_allocator" | "tlsf" | "custom" | "unknown",
  "task_model":       "task_only" | "proc_thread_split" | "pcb_tcb_unified" | "unknown",
  "scheduler":        "FIFO" | "RR" | "CFS" | "Stride" | "priority_queue" | "custom" | "unknown",
  "signal_support":   "full" | "partial" | "stub" | "none" | "unknown",
  "futex_support":    "full" | "partial" | "stub" | "none" | "unknown",
  "ipc_primitives":   "pipe_only" | "pipe+shared_memory" | "pipe+msgqueue+semaphore" | "rich" | "none" | "unknown",
  "msgqueue_support": "full" | "partial" | "stub" | "none" | "unknown",
  "shm_support":      "full" | "partial" | "mmap_only" | "none" | "unknown",
  "semaphore_ipc":    "full" | "partial" | "stub" | "kernel_only" | "none" | "unknown",
  "signal_ipc":       "full" | "partial" | "stub" | "none" | "unknown",
  "vfs_style":        "inode_dentry_superblock" | "trait_vfs" | "no_vfs" | "unknown",
  "fs_primary":       "fat32" | "ext4" | "ramfs" | "custom" | "none" | "unknown",
  "fs_secondary":     "fat32" | "ext4" | "procfs" | "devfs" | "tmpfs" | "ramfs" | "custom" | "none" | "unknown",
  "pipe_impl":        "ring_buffer" | "byte_stream" | "none" | "unknown",
  "mmap_support":     "full" | "partial" | "stub" | "none" | "unknown",
  "network_stack":    "smoltcp" | "lwip" | "custom" | "none" | "unknown",
  "socket_support":   "full" | "partial" | "stub" | "none" | "unknown",
  "socket_impl":      "real_stack" | "loopback_only" | "pipe_simulated" | "stub_only" | "none" | "unknown",
  "io_multiplexing":  "poll+select" | "ppoll_only" | "poll_only" | "none" | "unknown",
  "block_driver":     "virtio_blk" | "sdcard" | "virtio_blk+sdcard" | "nvme" | "none" | "unknown",
  "net_driver":       "virtio_net" | "e1000" | "ixgbe" | "none" | "custom" | "unknown",
  "device_discovery": "hardcoded" | "device_tree" | "pci_scan" | "mixed" | "unknown",
  "driver_model":     "static_mmio" | "device_tree" | "pci" | "mixed" | "unknown",
  "irq_controller":   "plic" | "apic" | "gic" | "clint+plic" | "none" | "unknown",
  "cow":              true | false | null,
  "lazy_alloc":       true | false | null,
  "swap":             true | false | null,
  "smp":              true | false | null,
  "per_cpu":          true | false | null,
  "load_balance":     true | false | null,
  "user_mem_protect": true | false | null,
  "uid_gid_model":    "real" | "stub_root" | "none" | "unknown",
  "procfs_support":   "full" | "partial" | "none" | "unknown",
  "devfs_support":    "full" | "partial" | "none" | "unknown",
  "tmpfs_support":    "full" | "partial" | "none" | "unknown",
  "procfs_devfs":     true | false | null,
  "syscall_count_real": <非负整数，仅统计有完整逻辑的 syscall，桩函数不计入，不确定填 null>,
  "trapframe_bytes":  <TrapFrame 结构体总字节数非负整数，不确定填 null>,
  "fat32_source":     "custom" | "fatfs_crate" | null,
  "vfs_trait":        "<VFS 核心 Trait/接口名称字符串>" | null
}

规则：
- null 表示报告中未明确提及或无法确定，严禁猜测
- 字段值必须是上述候选之一（字符串字段），不得输出其他任何字符串
- `none` 表示报告明确说明“未实现/不存在/不支持”，`unknown` 表示报告中无法可靠判断
- 仅当报告中有明确证据时才输出 `true` / `false`；拿不准时输出 `null`
- 优先从对应章节提取稳定结论，不要被执行摘要中的概括性修辞带偏
- 只输出 JSON，不要任何额外解释
"""


def extract_struct_features(sections_dir: str, checkpoint_path: Optional[str] = None, force: bool = False):
    """
    从 sections/ 目录读取所有 D 报告，调用 LLM 提取精确结构化特征 JSON。

    Args:
        sections_dir: sections/ 目录路径

    Returns:
        结构化特征字典，提取失败时返回 {}
    """
    cached_payload = {} if force or not checkpoint_path else _load_json(checkpoint_path)
    cached_struct_features = (
        cached_payload.get("struct_features", {}) or {}
        if _is_struct_stage_cache_current(cached_payload)
        else {}
    )
    cached_usage = cached_payload.get(
        "token_usage_total",
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )
    if cached_struct_features:
        print(f"   🤖 LLM：提取精确结构化特征")
        print(f"      ⏭️  [struct_features] 使用本地阶段缓存")
        print(f"      - 字段数: {len(cached_struct_features.keys())}")
        if cached_usage.get("total_tokens", 0) > 0:
            print(f"      - Token使用: {cached_usage['total_tokens']:,}")
        return cached_struct_features, cached_usage

    files = []
    if os.path.isdir(sections_dir):
        for fname in sorted(os.listdir(sections_dir)):
            if fname.endswith(".md"):
                files.append(os.path.join(sections_dir, fname))

    if not files:
        logger.warning(f"extract_struct_features: 未找到 section 文件 in {sections_dir}")
        return {}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # 合并所有 section 文件（完整读取，不做截断）
    parts = []
    file_stats = []
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read().strip()
            raw_len = len(raw_text)
            text = raw_text
            parts.append(text)
            file_stats.append({
                "path": fp,
                "raw_chars": raw_len,
                "sent_chars": len(text),
                "truncated": False,
            })
        except Exception as e:
            file_stats.append({
                "path": fp,
                "raw_chars": 0,
                "sent_chars": 0,
                "truncated": False,
                "error": str(e),
            })
            continue

    combined = "\n\n---\n\n".join(parts)
    prompt = STRUCT_FEATURE_PROMPT + "\n\n---\n以下是项目 D 报告内容：\n\n" + combined

    llm = _get_llm()
    model_name = _get_llm_model_name()
    t0 = time.perf_counter()
    print(f"   🤖 LLM：提取精确结构化特征")
    print(f"      - 模型: {model_name}")
    print(f"      - 文件数: {len(files)}")
    print(f"      🚀 [struct_features] 开始提取")
    print(f"         发送给 LLM 的本地文件:")
    for stat in file_stats:
        rel_path = os.path.relpath(stat["path"], sections_dir).replace("\\", "/")
        if stat.get("error"):
            print(f"           - {rel_path}: 读取失败 ({stat['error']})")
        else:
            trunc_note = " [已截断]" if stat["truncated"] else ""
            print(
                f"           - {rel_path}: 原始 {stat['raw_chars']} 字符 -> "
                f"发送 {stat['sent_chars']} 字符{trunc_note}"
            )
    print(f"         Prompt 总长度: {len(prompt)} 字符")
    try:
        response = _invoke_with_retry(llm, prompt, "struct_features")
        usage = _extract_token_usage(response)
        raw = response.content.strip()
        # 去除可能的 markdown 代码块包装
        if raw.startswith("```"):
            raw = re.sub(r'^```[a-z]*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
            raw = raw.strip()
        result = json.loads(raw)
        print(f"      ✅ [struct_features] 提取成功: {len(result.keys())} 个字段 ({time.perf_counter() - t0:.2f}s)")
        if usage["total_tokens"] > 0:
            print(
                f"         📄 Tokens: {usage['total_tokens']:,} "
                f"(输入:{usage['prompt_tokens']:,} + 输出:{usage['completion_tokens']:,})"
            )
            print(f"      - Token使用: {usage['total_tokens']:,}")
        if checkpoint_path:
            _save_json(
                checkpoint_path,
                {
                    "stage": "struct_features",
                    "sections_dir": os.path.abspath(sections_dir),
                    "struct_features_schema_version": STRUCT_FEATURE_SCHEMA_VERSION,
                    "struct_features": result,
                    "token_usage_total": usage,
                },
            )
        return result, usage
    except Exception as e:
        logger.warning(f"结构化特征提取失败 ({e})，返回空字典")
        print(f"      ⚠️ [struct_features] 提取失败 ({type(e).__name__}: {e})")
        print(f"         将返回空字典 {{}}，后续相似度计算只依赖文本特征与向量，不会因此中断。")
        return {}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


# ---------------------------------------------------------------------------
# 项目指纹 (Fingerprint)
# ---------------------------------------------------------------------------
class Fingerprint:
    """
    项目特征指纹：结构化特征文本 + 10 维向量 + 精确结构化字段。
    """

    def __init__(self, name: str, features: Dict[str, str],
                 embeddings: Dict[str, List[float]],
                 struct_features: Optional[dict] = None,
                 struct_features_schema_version: int = STRUCT_FEATURE_SCHEMA_VERSION):
        self.name = name
        self.features = features                        # {dim_id: feature_text}
        self.embeddings = embeddings                    # {dim_id: [float, ...]}
        self.struct_features = struct_features or {}    # 精确 JSON 特征
        self.struct_features_schema_version = struct_features_schema_version

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "features": self.features,
            "embeddings": {k: v for k, v in self.embeddings.items()},
            "struct_features": self.struct_features,
            "struct_features_schema_version": self.struct_features_schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Fingerprint":
        return cls(
            name=d["name"],
            features=d["features"],
            embeddings=d["embeddings"],
            struct_features=d.get("struct_features", {}),  # 向后兼容
            struct_features_schema_version=d.get("struct_features_schema_version", 1),
        )

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"指纹已保存: {path}")

    @classmethod
    def load(cls, path: str) -> "Fingerprint":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def get_concat_vector(self) -> np.ndarray:
        """将各维向量按固定顺序拼接为一个大向量。"""
        vecs = []
        for dim_id in sorted(DIMENSION_MAP.keys()):
            if dim_id in self.embeddings:
                vecs.append(np.array(self.embeddings[dim_id], dtype=np.float32))
        return np.concatenate(vecs) if vecs else np.array([], dtype=np.float32)


def build_fingerprint(
    repo_name: str,
    sections_dir: str,
    embedder: Optional[LocalEmbedder] = None,
    force: bool = False,
) -> Fingerprint:
    """
    构建项目特征指纹。

    Args:
        repo_name:    项目名称
        sections_dir: sections/ 目录路径
        embedder:     可选的 Embedder 实例（共享加载）
        force:        是否强制重建（忽略已有 fingerprint.json）

    Returns:
        Fingerprint 对象
    """
    # 检查缓存
    output_dir = os.path.dirname(sections_dir)  # output/<repo>/
    fp_path = os.path.join(output_dir, "fingerprint.json")
    stage_dir = os.path.join(output_dir, "_coarse_stage")
    feature_stage_path = os.path.join(stage_dir, "fingerprint_features.json")
    struct_stage_path = os.path.join(stage_dir, "fingerprint_struct_features.json")
    embedding_stage_path = os.path.join(stage_dir, "fingerprint_embeddings.json")
    dim_ids = sorted(DIMENSION_MAP.keys())

    if not force and os.path.exists(fp_path):
        fingerprint_payload = _load_json(fp_path)
        feature_payload = _load_json(feature_stage_path)
        struct_payload = _load_json(struct_stage_path)
        embedding_payload = _load_json(embedding_stage_path)
        if _is_fingerprint_cache_current(fingerprint_payload) and _are_fingerprint_stage_caches_complete(
            feature_payload,
            struct_payload,
            embedding_payload,
            dim_ids,
        ):
            logger.info(f"加载已有指纹: {fp_path}")
            return Fingerprint.from_dict(fingerprint_payload)
        if not _is_fingerprint_cache_current(fingerprint_payload):
            logger.info(
                f"fingerprint 结构化特征 schema 版本过旧，将重建: {fp_path}"
            )
        else:
            logger.info(
                f"fingerprint 阶段缓存不完整，将重组最终指纹: {fp_path}"
            )

    # Step 1: LLM 提取文本摘要特征
    print(f"📝 正在提取 {repo_name} 的结构化特征...")
    features, feature_usage = extract_features_from_report(
        sections_dir,
        checkpoint_path=feature_stage_path,
        force=force,
    )

    # Step 1.5: LLM 提取精确结构化特征（JSON）
    print(f"🔩 正在提取 {repo_name} 的精确结构化特征...")
    struct_features, struct_usage = extract_struct_features(
        sections_dir,
        checkpoint_path=struct_stage_path,
        force=force,
    )

    # Step 2: 本地 Embedding
    if embedder is None:
        embedder = LocalEmbedder()

    embedding_payload = {} if force else _load_json(embedding_stage_path)
    embeddings = embedding_payload.get("embeddings", {}) or {}
    if embeddings and all(dim_id in embeddings for dim_id in dim_ids):
        print(f"🧠 LLM 特征提取完成，开始本地向量化...")
        print(f"⏭️  命中本地阶段缓存：embedding 向量")
    else:
        texts = [features.get(d, "") for d in dim_ids]
        print(f"🧠 LLM 特征提取完成，开始本地向量化...")
        print(f"🔢 正在生成 {len(texts)} 个维度的向量...")
        vectors = embedder.encode(texts)

        embeddings = {}
        for i, dim_id in enumerate(dim_ids):
            embeddings[dim_id] = vectors[i].tolist()
        _save_json(
            embedding_stage_path,
            {
                "stage": "embeddings",
                "repo_name": repo_name,
                "dim_ids": dim_ids,
                "embeddings": embeddings,
            },
        )
        print(f"💾 已保存 embedding 阶段缓存: {embedding_stage_path}")

    # Step 3: 保存
    fp = Fingerprint(name=repo_name, features=features,
                     embeddings=embeddings, struct_features=struct_features,
                     struct_features_schema_version=STRUCT_FEATURE_SCHEMA_VERSION)
    fp.save(fp_path)
    llm_usage_total = _merge_token_usage(feature_usage, struct_usage)
    if llm_usage_total["total_tokens"] > 0:
        print(f"\n{'='*60}")
        print(f"📊 指纹提取总结: {repo_name}")
        print(f"   - LLM调用: 2 组（维度摘要 + 精确结构化特征）")
        print(f"   - Token使用: {llm_usage_total['total_tokens']:,}")
        print(f"{'='*60}")
    print(f"✅ 指纹已生成: {fp_path}")
    return fp


# ---------------------------------------------------------------------------
# Dimension 权重
# ---------------------------------------------------------------------------
def get_dimension_weights() -> Dict[str, float]:
    """返回各维度权重字典。"""
    return {dim_id: cfg["weight"] for dim_id, cfg in DIMENSION_MAP.items()}
