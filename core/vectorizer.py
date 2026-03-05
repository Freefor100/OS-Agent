"""
OS-Agent C: 特征提取与本地向量化模块

从 OS-Agent D 生成的 section 报告中提取结构化特征摘要，
再通过本地 Embedding 模型（BGE-M3）转换为向量表示。
"""
import os
import re
import json
import logging
from typing import Dict, List, Optional

import numpy as np
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
logger = logging.getLogger("vectorizer")

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
    "D10_net_debug_test": {
        "sections": ["11_", "12_", "13_"],
        "prompt": (
            "从以下网络、调试、测试报告中综合提取特征摘要（120-180 字）。\n\n"
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
            "【测试部分】：\n"
            "1. 单元测试数量（#[test] 函数精确数量）\n"
            "2. 集成测试与 LTP 测试移植情况\n"
            "3. CI/CD 配置（GitHub Actions / GitLab CI）\n"
            "4. 性能基准（Lmbench / UnixBench）\n\n"
            "【严格要求】：\n"
            "- 如果无网络支持明确写'未实现网络功能'\n"
            "- 如果无 CI 配置明确写'未发现 CI/CD 配置'\n\n"
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


def _read_and_merge(file_paths: List[str], max_chars_per_file: int = 8000) -> str:
    """读取并合并多个文件的内容（截断保护）。"""
    parts = []
    for fp in file_paths:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read().strip()
            if len(text) > max_chars_per_file:
                text = text[:max_chars_per_file] + "\n... [截断]"
            parts.append(text)
        except Exception as e:
            logger.warning(f"读取 {fp} 失败: {e}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM 结构化特征提取
# ---------------------------------------------------------------------------
def _get_llm():
    """复用项目已有的 LLM 配置。"""
    model_name = os.environ.get("MODEL_NAME", "deepseek/deepseek-v3.2")
    return ChatOpenAI(
        model=model_name,
        temperature=0,
        request_timeout=120,
        max_retries=2,
    )


def extract_features_from_report(sections_dir: str) -> Dict[str, str]:
    """
    读取 sections/ 下的 D 报告，按 7 个维度提取结构化特征文本。

    Args:
        sections_dir: sections/ 目录路径（如 output/nonix/sections）

    Returns:
        {dim_id: feature_text} 字典
    """
    llm = _get_llm()
    features = {}

    for dim_id, cfg in DIMENSION_MAP.items():
        files = _find_section_files(sections_dir, cfg["sections"])
        if not files:
            logger.warning(f"[{dim_id}] 未找到匹配 section 文件 (prefix={cfg['sections']})")
            features[dim_id] = f"[未找到 {dim_id} 相关的分析报告]"
            continue

        content = _read_and_merge(files)
        prompt = cfg["prompt"] + "\n\n---\n以下是分析报告内容：\n\n" + content

        try:
            response = llm.invoke(prompt)
            features[dim_id] = response.content.strip()
            logger.info(f"[{dim_id}] 提取特征: {len(features[dim_id])} 字符")
        except Exception as e:
            logger.error(f"[{dim_id}] LLM 提取失败: {e}")
            features[dim_id] = f"[提取失败: {e}]"

    return features


# ---------------------------------------------------------------------------
# 本地 Embedding 模型
# ---------------------------------------------------------------------------
class LocalEmbedder:
    """
    基于 sentence-transformers 的本地 Embedding 模型。
    默认使用 BAAI/bge-m3（中英文多语言，1024 维）。
    """

    DEFAULT_MODEL = "BAAI/bge-m3"

    def __init__(self, model_name: str = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _load_model(self):
        if self._model is None:
            logger.info(f"加载 Embedding 模型: {self.model_name} ...")
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                logger.info(f"模型加载完成，向量维度: {self._model.get_sentence_embedding_dimension()}")
            except ImportError:
                raise ImportError(
                    "请安装 sentence-transformers: pip install sentence-transformers torch"
                )

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
# 项目指纹 (Fingerprint)
# ---------------------------------------------------------------------------
class Fingerprint:
    """
    项目特征指纹：结构化特征文本 + 7 维向量。
    """

    def __init__(self, name: str, features: Dict[str, str],
                 embeddings: Dict[str, List[float]]):
        self.name = name
        self.features = features           # {dim_id: feature_text}
        self.embeddings = embeddings       # {dim_id: [float, ...]}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "features": self.features,
            "embeddings": {k: v for k, v in self.embeddings.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Fingerprint":
        return cls(
            name=d["name"],
            features=d["features"],
            embeddings=d["embeddings"],
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
        """将 7 维向量按固定顺序拼接为一个大向量。"""
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
    if not force and os.path.exists(fp_path):
        logger.info(f"加载已有指纹: {fp_path}")
        return Fingerprint.load(fp_path)

    # Step 1: LLM 提取结构化特征
    print(f"📝 正在提取 {repo_name} 的结构化特征...")
    features = extract_features_from_report(sections_dir)

    # Step 2: 本地 Embedding
    if embedder is None:
        embedder = LocalEmbedder()

    dim_ids = sorted(DIMENSION_MAP.keys())
    texts = [features.get(d, "") for d in dim_ids]
    print(f"🔢 正在生成 {len(texts)} 个维度的向量...")
    vectors = embedder.encode(texts)

    embeddings = {}
    for i, dim_id in enumerate(dim_ids):
        embeddings[dim_id] = vectors[i].tolist()

    # Step 3: 保存
    fp = Fingerprint(name=repo_name, features=features, embeddings=embeddings)
    fp.save(fp_path)
    print(f"✅ 指纹已生成: {fp_path}")
    return fp


# ---------------------------------------------------------------------------
# Dimension 权重
# ---------------------------------------------------------------------------
def get_dimension_weights() -> Dict[str, float]:
    """返回各维度权重字典。"""
    return {dim_id: cfg["weight"] for dim_id, cfg in DIMENSION_MAP.items()}
