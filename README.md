# OS-Agent

🤖 **OS 仓库自动分析与技术报告生成工具**

基于 LLM Agent 的操作系统项目自动分析工具，能够深入分析 OS 仓库的代码结构、技术栈、内核实现，并生成专业的技术分析报告。

---

## 📋 功能特性

### 1. OS-Agent D：自动源码描述 (`os_agent_d_describe.py`) ✨ **增强版**

对 OS 仓库进行 **13 阶段**的深度技术分析，现已升级为**阶段级 Plan-Execute (PE)** 架构，内置本地 RAG 语义搜索、LSP 调用图分析、智能重试；Execute 阶段受锁定 **`execution_steps`** 与执行契约约束。各阶段计划在 `_per_stage/*_plan.json` 落盘便于对照与复跑。

| 阶段 | 内容 |
|------|------|
| 00 | 仓库准备（本地直连克隆，无 LLM 开销） |
| 0.5 | RAG 预索引（代码向量化，支持后续语义搜索，已有索引自动跳过） |
| 01 | 项目概览与技术栈 |
| 02 | 启动流程与架构初始化 |
| 03 | 内存管理（物理/虚拟/分配器） |
| 04 | 进程/线程与调度机制 |
| 05 | 中断、异常与系统调用 |
| 06 | 文件系统（VFS + 具体 FS） |
| 07 | 设备驱动与硬件抽象 |
| 08 | 同步互斥与进程间通信 |
| 09 | 多核支持与并行机制 |
| 10 | 安全机制与权限模型 |
| 11 | 网络子系统与协议栈 |
| 12 | 调试机制与错误处理 |
| 13 | 开发历史与里程碑（Git 语义化分析） |

**核心分析机制（三级联动）：**

1. 🔍 **RAG 语义搜索（首选）**：`rag_search_code` 对整个仓库代码建立本地向量索引（Jina Embedding），支持语义级模糊搜索（如"查找页表映射实现"），穿透复杂目录结构直接定位相关代码块，大幅减少无效的目录遍历。
2. 🌳 **LSP 拓扑展开**：通过 `lsp_get_call_graph`（多层递归调用树，包含变量到引用的智能降级）、`lsp_get_definition`（跨文件跳转）、`lsp_get_references` 构建精确的 AST 调用拓扑图。
3. 🛠️ **分层降级兜底**：当 LSP 失败时，系统**首选 Tree-sitter AST 解析**（C/C++/Rust/Go/Zig），再退到语言感知正则、通用 Grep；仅在汇编或前述路径都失败时才使用 ASM 词法兜底。系统具备“智能分层切换”：LSP -> Tree-sitter -> Language-aware Static -> Grep -> ASM(最终兜底)。

**v4.0 新增：阶段级 Plan-Execute 闭环**

1. 🧭 **Plan**：每章生成结构化 `PlanSpec`（`seed_paths`、`must_cover`、`entry_symbols` 等），并锁定 **`execution_steps`**（4～8 条短句）；Execute **须按该顺序**调工具与收束正文（见 `render_plan_context` + `STAGE_EXECUTION_CONTRACT`）。
2. 🧠 **Execute**：ReAct Agent 做证据搜集与章节 Markdown；可抽取 `evidence_index` / `claim_map` 供内存侧逻辑参考；章节正文写入 `sections/*.md`，计划写入 `_per_stage/{stage_id}_plan.json`。

**v4.0 受限外部背景补充**

- 新增 `web_search` 工具，但**默认关闭**。
- 该工具只允许查询“全国大学生操作系统比赛”背景、赛道定位、目标要求、功能要求和公开技术背景。
- `web_search` 结果只能用于**技术概览 / 概述总结**，**绝不能**作为仓库实现事实、查重判断或源码证据。

**报告拼装（13阶段结束后）：Call Graph 概览块** (`tools/callgraph_overview.py`) ✨ **新增**

所有分析阶段完成后，在报告 TOC 之后、各章节正文之前，自动插入 **Call Graph 概览块**，让评委一眼看懂 OS 的架构枢纽与调用关系。

| 步骤 | 内容 |
|------|------|
| 1. Tree-sitter 全库解析 | 遍历配置的源码扩展名（含 `.c/.h/.rs/.go/.zig` 等），提取函数/宏/typedef（节点）与单文件调用（边），构建 NetworkX `DiGraph` |
| 2. Clang 语义过滤（C/C++） | 用 **libclang** 按 `compile_flags.txt` / `compile_commands.json` 解析 TU，收集**预处理后可进入 AST 的函数定义**；从图中剔除条件编译裁掉的符号，使 PageRank 更接近真实构建。**环境**：`pip install clang`（Python 绑定）+ 系统安装 **LLVM**（含 `libclang.dll`；Windows 下代码会尝试 `C:\\Program Files\\LLVM\\bin\\libclang.dll`）。也可设 `LIBCLANG_PATH` 指向该文件。不可用时跳过并打日志。 |
| 3. PageRank Top-k | `nx.pagerank(alpha=0.85)` 选出枢纽（默认 k=30，可改） |
| 4. LSP 精化（可选） | 对前 30 个枢纽调用 `lsp_get_call_graph(..., max_depth=4 或参数 lsp_max_depth)`，补充跨文件边；若 LSP 返回降级/空则跳过 |
| 5. LLM 批量分类 | 对 Top-k 做 domain×layer **单次** LLM 分类；返回的 token 计入 `describe` 总用量（见阶段结束与收尾汇总） |
| 6. SVG 渲染 | `domain`（列）× `layer`（行）二维网格，Bezier 连线 |
| 7. 表格与缓存 | 文件级表、枢纽表；落盘 `callgraph_overview.{svg,md,meta.json}`；**缓存**由 `input_fingerprint`（compile 配置、git HEAD、管线版本、`top_k`/`lsp_max_depth`、libclang 可用性）自动失效，**无需**设置 Call Graph 相关环境变量 |

**代码参数（非环境变量）**：在 `os_agent_d_describe.py` 中调用 `generate_callgraph_section(top_k=30, lsp_refine=True, lsp_max_depth=None, force_regenerate=False)`；返回 **`(markdown, llm_total_tokens)`**，第二项为步骤 5 的 LLM token，**已并入** `describe` 末尾「总Token使用」。`lsp_max_depth` 为 `None` 时用默认 `4`；`force_regenerate=True` 仅用于强制忽略缓存。

**LSP 精化**：建议目标仓库有与真实编译一致的 `compile_flags.txt` 或 `compile_commands.json`（Bear/CMake），减轻条件编译符号上的 `DEGRADED`。

若终端显示 **「LSP 成功精化节点数: 0」**：表示对 Top 枢纽的每次 `lsp_get_call_graph` 均得到**空结果**或含 **`DEGRADED`**（clangd/rust-analyzer 无法可靠索引），常见原因是 **C/C++ 工程根目录缺少 `compile_commands.json`**。可在仓库内用 Bear/CMake 等生成该文件后重跑；未精化时调用图仍以 **Tree-sitter + 语义过滤后的边**为主。

结果落盘（`output/<repo>/`，指纹未变时命中缓存）：

- `callgraph_overview.svg`：矢量图，可单独打开、做 diff  
- `callgraph_overview.md`：章节正文，用**相对路径**引用同目录 SVG（体积小、可读）  
- `callgraph_overview_meta.json`：统计、k、Top-k、`classified`、`input_fingerprint` 等  

---

### 2. OS-Agent D：自动报告评估 (`os_agent_d_evaluate.py`) ✨ **增强版**

使用 Agent 将自动生成的报告与仓库内人类撰写的文档进行对比评估。

### 3. OS-Agent C：智能查重与比对 (`os_agent_c_coarse.py` / `os_agent_c_fine.py`)

面向小型操作系统的分析比对，系统分为两阶段架构，快速在新旧作品间进行查重与创新点分析：

- **粗筛模块 (`os_agent_c_coarse.py`)**：采用 **`pre-plan + deterministic pipeline`**，不引入完整 reviewer 闭环。先通过轻量 `coarse_preplan` 判断框架生态、关键 section 和粗筛锚点，再进入多维度加权余弦相似度检索。内置三项量化增强：
  - **结构化精确特征（扩展版）**：LLM 会额外从 D 报告中提取更宽的 JSON 精确字段集，不再只覆盖少量校正项，而是同时覆盖框架/架构/内核类型、页表模式、物理页与堆分配器、任务模型、调度器、信号/Futex/IPC、VFS/主次文件系统、`mmap`/共享内存、socket 真实实现形态、`poll/select`、块设备/网卡/设备发现、`procfs/devfs/tmpfs`、安全权限模型，以及 `syscall_count_real`、`trapframe_bytes` 等数值字段。
  - **精确字段加分规则（更新版）**：粗筛会先计算原始分 `raw_total = cosine_score + struct_score`，其中 `struct_score` 会按字段精确匹配叠加加分，覆盖内存管理、任务/IPC、文件系统、网络/驱动、安全与 SMP 等稳定事实字段，最高原始加分为 **+0.30**。最终再将总分**严格归一化到 `0~1`**（同时输出 `0~100%`），保证“完全相似 = `1.0` = `100%`”，避免查重场景中出现 `>1` 的误导。
  - **框架感知权重**：自动识别两个项目是否基于同一框架（ArceOS/rCore/xv6 等），同框架时将框架贡献维度（D1/D2/D7）权重减半，自研核心维度（D3~D8）权重上调 ×1.4，防止因共享框架导致虚高相似度。
  - **阶段缓存与断点续跑**：粗筛的指纹构建已支持分阶段落盘。`features`、`struct_features`、`embeddings` 会保存在 `output/<repo>/_coarse_stage/` 下，重跑时自动检查本地阶段缓存并跳过已完成阶段，避免因单次超时或中断整轮白跑。现在**最终 `fingerprint.json` 也依赖阶段缓存完整性**：只要某个阶段缓存缺失，即使 `fingerprint.json` 仍在，也会自动判定为需要重组最终指纹，而不是直接命中旧总缓存。

- **精比模块 (`os_agent_c_fine.py`)**：**阶段级 Plan → Execute**（与 Describe 同为两阶段管线）。对粗筛出的 Top-K 候选逐阶段生成对比草稿，在源码级深度比对的基础上，增加“代码相似 vs 设计相似”区分。并保留两大量化相似度维度：
  - **Token Jaccard 相似度**（`compare_function_tokens`）：对同名函数体 token 化后计算 Jaccard 指数，去除语言关键字后输出独有符号摘要，提供函数实现层面的客观数字证据。
  - **Call Graph Jaccard 相似度**（`compare_call_graphs`）：对比两项目调用图的节点集合，输出节点 Jaccard = |交集| / |并集|，量化调用拓扑结构的相似程度。
  - **综合评分锚定**：Agent 被强制要求对 5 个核心函数分别获取 Token Jaccard 与 CG Jaccard，以 `综合相似度 = Token Jaccard 均值 × 0.5 + CG Jaccard 均值 × 0.5` 为锚，结合 4 档评级区间（高度相似 / 改进版 / 受启发 / 独立）输出 0-100 最终评分，确保结论有量化依据可追溯。

### 4. 本地工具安全与沙盒限制

为防止 Token 溢出与确保本地系统安全，各底座工具有严格的使用边界：

- **5 维度客观评分**: 覆盖度、准确性、技术深度、引用规范、亮点发现
- **独立源码验真**: 冲突时永远以源码为准，利用工具确保证据链闭环
- **重构脉络提取**: 完全自主翻阅并提取大型架构的历史合并节点
- **创新亮点锚定**: 发现比人类原生文档更详细的地方，以及遗漏的关键缺陷
- **沙盒安全边界**: 大模型仅能访问指定的仓库源内文件以及受限的外部沙盒输出目录

### 5. 本地代码 RAG 语义搜索引擎

OS-Agent 内置了一套专为操作系统内核代码优化的**本地 RAG（Retrieval-Augmented Generation）引擎**，在分析每个 OS 仓库前自动完成代码向量化，使 LLM Agent 可以用自然语言"查找功能实现"而非死记函数名。

#### 完整工作链路

```
OS 仓库源码 (.c / .h / .rs)
       │
       ▼  ① tree-sitter AST 解析（精确切块）
  CodeChunk：函数定义 / impl 块 / struct
  含：文件路径、起止行号、代码体、符号名
       │
       ▼  ② Jina Embedding 向量化
  模型：jinaai/jina-embeddings-v2-base-code
  输入：Name + Path + Type + Code(≤2000字符)
  输出：768 维 float32 稠密向量，L2 归一化
       │
       ▼  ③ 持久化向量索引
  output/<proj>/_vector_db/
  ├── chunks.json   ← 代码块元数据
  └── vectors.npy   ← 向量矩阵 (NumPy float32)
       │
       ▼  ④ 余弦相似度最近邻检索（纯 NumPy）
  scores = vectors @ encode(query)
  top_k = argsort(scores)[-k:]
  返回：相似度分数 + 文件:行号 + 代码片段
```

#### 阶段 0.5：自动预索引

克隆仓库后，系统在正式分析前立即执行 RAG 预索引：

```
🚀 阶段 0.5：RAG 预索引 (代码向量化)...
✅ RAG 预索引完成，后续语义搜索将秒开。
```

- **增量感知**：`_vector_db/` 已存在时直接加载，避免重复向量化
- **自动剪枝**：跳过 `.git/`、`target/`、`build/` 等无关目录
- **双重降级保护**：tree-sitter 未安装 → 正则切块；Embedding 模型失败 → 关键词词频匹配

#### `rag_search_code` 工具接口

```
rag_search_code(repo_path, query, top_k=3)
```

| 参数 | 说明 |
|------|------|
| `repo_path` | 仓库路径（受沙盒限制，只能访问 `repos/` 目录） |
| `query` | **自然语言**描述，如 `"物理页面分配与回收"` / `"page fault handler"` |
| `top_k` | 返回最相关代码块数（默认 3） |

**返回格式：**
```
[1] 相似度: 0.8821 | 文件: kernel/vm.c:120-165 | 类型: function_definition | 符号名: mappages
```c
void mappages(pagetable_t pagetable, uint64 va, ...) { ... }
```


每个结果含相似度分数、文件路径与起止行号、节点类型、代码体（≤800字符，超出提示使用 `read_code_segment` 读完整内容）。

#### 三级联动分析策略

| 优先级 | 工具 | 适用场景 |
|--------|------|---------|
| 🥇 **首选** | `rag_search_code` | 不知道函数名，只知道功能描述 |
| 🥈 **次选** | `lsp_get_call_graph` | 已找到符号，展开调用拓扑（自动处理函数与变量的差异） |
| 🥉 **兜底** | `grep_in_repo` | 精确关键词/正则，或前两者均无结果 |

#### 模型与存储配置

| 配置项 | 默认值 |
|--------|--------|
| 嵌入模型 | `jinaai/jina-embeddings-v2-base-code`（`.env` 中 `CODE_EMBEDDING_MODEL` 可覆盖） |
| 向量维度 | 768 维，float32 |
| 索引位置 | `output/<proj>/_vector_db/`（与分析报告同级） |
| 建索引时代码截断 | ≤ 2000 字符/块 |
| 搜索结果截断 | ≤ 800 字符/块（防 Token 溢出） |

#### Hugging Face Hub（嵌入模型拉取）

逻辑在 **`core/hf_env.py`** 的 `apply_hf_hub_env_defaults()`（各入口在 `load_dotenv` 之后会调用）：

| 情况 | 行为 |
|------|------|
| **`HF_ENDPOINT` 未设置** | 默认写入国内镜像 **`https://hf-mirror.com`**（可用 `OS_AGENT_HF_ENDPOINT` 改默认基址；`OS_AGENT_USE_HF_MIRROR=false` 则不改写，走库默认官方）。 |
| **`.env` / 环境已设置 `HF_ENDPOINT`** | **原样使用**（写官方即官方，写镜像即镜像）。 |

`os_agent_d_describe.py` 使用 **`load_dotenv(override=True)`**，避免系统里误带的 `HF_ENDPOINT` 盖住仓库 `.env`。详见仓库根目录 **`.env.example`** 中 Hugging Face 小节。

---

## 🚀 快速开始

### 1. 自动环境配置（推荐）

推荐使用 Conda 隔离 Python 环境：

```bash
conda create -n os_agent python=3.10
conda activate os_agent
pip install -r requirements.txt
```

然后运行环境检查脚本，它会自动检测缺失依赖、尝试安装 LSP 工具，并自动识别 Cross Compiler 和 Go 工具链路径：

```bash
python check_env.py
```

`check_env.py` 特性：
- **智能预检**：先运行 `pip --dry-run` 判断依赖是否已满足，已满足则跳过安装，秒速完成检查
- **自动安装 LSP**：缺失 `clangd`、`gopls`、`rust-analyzer` 时自动安装
- **多架构 Cross Compiler 检测**：自动扫描 RISC-V、ARM、LoongArch 交叉编译器
- **路径自动修复**：通过 `_resolve_lsp_binary` 探测 `~/go/bin/`、`~/.cargo/bin/`、WinGet 等非标准安装目录，无需手动配置 PATH

### 2. 安装 Language Servers（LSP 工具依赖）

> LSP 工具（`lsp_get_definition`、`lsp_get_references`、`lsp_get_document_outline`）需要本地安装对应语言的 Language Server。未安装或超时时会**首选 Tree-sitter AST 解析**（C/C++/Rust/Go/Zig），再走语言感知正则、通用 Grep；仅在汇编或最终兜底场景才使用 ASM 正则。

### 2.1 降级结果元数据

当查询进入降级路径时，返回文本会追加结构化标记：

`[Fallback Metadata] fallback_path=...; confidence=high|medium|low; reason=...`

- `fallback_path`: 实际回退链路（如 `lsp->treesitter`、`lsp->lang_static->grep`）
- `confidence`: 结果置信度（`high/medium/low`）
- `reason`: 触发原因（如 `lsp_timeout`、`process_dead`）

建议在自动报告中显式引用该标记，避免将低置信度结果当作 AST 级证据。

### 2.2 回归验收建议（跨语言）

- Rust/C/Go 各选 3 个符号，分别验证 `lsp_get_definition` 与 `lsp_get_references` 在 LSP 正常与降级场景下的一致性。
- 统计降级后误命中率与空结果率，并与旧版“直接 ASM 降级”进行对照。
- 记录平均耗时与 P95 耗时，确认分层降级未显著拉高整体分析时延。

**按需安装**（只需安装你要分析的 OS 使用的语言）：

| 语言 | Language Server | Windows | Linux | macOS |
|------|----------------|---------|-------|-------|
| **Rust** | rust-analyzer | `rustup component add rust-analyzer` | 同左，或 `apt install rust-analyzer` | `brew install rust-analyzer` |
| **C/C++** | clangd | `winget install LLVM.LLVM` | `apt install clangd` / `pacman -S clang` | `brew install llvm` |
| **Go** | gopls | `go install golang.org/x/tools/gopls@latest` | 同左 | 同左 |
| **Zig** | zls | 从 [Releases](https://github.com/zigtools/zls/releases) 下载 | 同左 | 同左 |

安装后验证（推荐一键检查）：
```bash
python check_env.py
```

手动验证：
```bash
rust-analyzer --version   # 例如: rust-analyzer 0.3.2795-standalone
clangd --version          # 例如: clangd version 21.1.8
```

> **❗ Conda / venv 用户注意**：虚拟环境的 PATH 可能不包含系统工具目录。程序已内置 `_resolve_lsp_binary` 路径探测：
>
> | 平台 | 自动搜索路径 |
> |------|-------------|
> | Windows | `~/.cargo/bin/`, `~/go/bin/`, `~/AppData/Local/{name}/`, `~/scoop/shims/`, WinGet 包目录 |
> | macOS | `~/.cargo/bin/`, `~/go/bin/`, `/opt/homebrew/bin/`, `/usr/local/bin/` |
> | Linux | `~/.cargo/bin/`, `~/go/bin/`, `/usr/bin/`, `~/.local/bin/`, `/snap/bin/` |
>
> 如果仍然报错，请将 Language Server 安装目录手动加入系统 PATH。

### 3. 配置环境变量

创建 `.env` 文件（可复制 `.env.example`）：

```env
# API 配置（必需）
OPENAI_API_KEY=your_api_key_here
OPENAI_API_BASE=https://api.openai.com/v1

# 模型配置（可选）
MODEL_NAME=deepseek/deepseek-v3.2

# 要分析的 OS 仓库地址（必需）
REPO_URL=https://github.com/example/os-project.git

# 可选：启用 web_search（仅用于比赛背景/赛道目标/技术概览）
ENABLE_WEB_SEARCH=false
# TAVILY_API_KEY=
# SERPER_API_KEY=
# 嵌入模型与 HF 镜像（默认国内镜像）：见 .env.example「Hugging Face」一节
```

#### 配置项说明

| 配置项 | 必需 | 说明 |
|--------|------|------|
| `OPENAI_API_KEY` | ✅ | OpenAI 兼容 API 的密钥 |
| `OPENAI_API_BASE` | ✅ | API 地址（支持 OpenRouter、DeepSeek 等） |
| `MODEL_NAME` | ❌ | LLM 模型名称，默认 `deepseek/deepseek-v3.2` |
| `REPO_URL` | ✅ | 要分析的 OS 仓库 Git 地址 |
| `ENABLE_WEB_SEARCH` | ❌ | 是否启用 `web_search`（默认关闭，仅用于比赛背景与技术概览） |
| `TAVILY_API_KEY` / `SERPER_API_KEY` | ❌ | `web_search` 的 provider 密钥，至少配置一种 |
| `HF_ENDPOINT` 等 | ❌ | 代码嵌入拉取：见上文「Hugging Face Hub」与 `.env.example` |

### 4. 运行分析

```bash
# 直接运行（使用 .env 中的配置）
python os_agent_d_describe.py
```

输出目录结构：
```
output/
└── <os-name>/
    ├── sections/               # 各章节分段报告
    │   ├── 01_项目概览与技术栈.md
    │   ├── 02_启动流程与架构初始化.md
    │   └── ...
    ├── _per_stage/             # 阶段侧车（repo_profile + 各章 plan.json）
    │   ├── repo_profile.json
    │   ├── 03_mem_mgmt_plan.json
    │   └── ...
    ├── _coarse_stage/          # 粗筛阶段缓存（按项目）
    │   ├── fingerprint_features.json
    │   ├── fingerprint_struct_features.json
    │   └── fingerprint_embeddings.json
    ├── coarse_preplan.json     # 粗筛 pre-plan 结果
    ├── fingerprint.json        # 粗筛最终指纹（features + struct_features + embeddings）
    ├── coarse_screening.json   # 粗筛 Top-K 结果
    ├── coarse_screening.md     # 粗筛可读报告
    ├── OS技术分析报告_<os-name>.md
    └── describe_error_report.json
```

---

## 📊 评估报告（os_agent_d_evaluate.py）✨ **增强版 v2.5**

> **v2.0 更新**（2025-02-14）：新增智能重试、完整错误追溯、鲁棒性大幅提升！评估过程更稳定，失败可追溯。

### 功能说明

评估程序使用独立 Agent 对每个章节进行评估，自主探索仓库，查找人类撰写的文档（README、设计文档、PDF 等），与 Agent 生成的报告进行深度对比。**冲突时以源码为准**。

**核心特点**：
- 🔍 Agent 自主选择要读取的文档
- 🔒 安全限制：只能访问仓库目录和 output 目录
- 📊 5 维度评分体系（覆盖度、准确性、深度、引用、亮点）
- ✨ 自动发现 Agent 报告的亮点和不足
- 🔄 智能重试机制（指数退避、错误分类）
- 📋 完整错误追溯（日志、报告、堆栈）
- 🛡️ 高鲁棒性（输入验证、超时控制、优雅降级）

### 使用方法

```bash
# 基本用法（使用 .env 中的 REPO_URL）
python os_agent_d_evaluate.py

# 指定仓库 URL
python os_agent_d_evaluate.py --repo-url https://gitlab.educg.net/xxx/os-project.git

# 指定仓库路径和输出目录
python os_agent_d_evaluate.py --repo-path repos/my-os --output-dir output/my-os

# 使用不同的 LLM 模型
python os_agent_d_evaluate.py --model gpt-4o
```

### 命令行参数

| 参数 | 说明 |
|------|------|
| `--repo-url` | OS 仓库 URL（覆盖 .env 中的 REPO_URL） |
| `--repo-path` | 仓库本地路径（默认从 REPO_URL 解析） |
| `--output-dir` | 生成报告目录（默认 output/<repo_name>） |
| `--model` | LLM 模型名称（覆盖 .env 中的 EVAL_MODEL_NAME） |

### 评估维度

| 维度 | 权重 | 说明 |
|------|------|------|
| **coverage** | 25% | 内容覆盖度 - Agent 覆盖了人类文档多少关键技术点 |
| **accuracy** | 35% | 准确性 - Agent 描述与人类文档/代码是否一致，捏造严重扣分 |
| **depth** | 20% | 技术深度 - 是否深入到代码实现层面 |
| **citations** | 10% | 证据引用 - 是否引用具体文件路径、代码片段 |
| **highlights** | 10% | 亮点发现 - Agent 超越人类文档的源码级洞察 |

### 输出文件（增强版）

评估完成后，在 `evaluation/<repo_name>/` 目录下生成：

```
evaluation/
└── <repo_name>/
    ├── evaluation.log          # 📋 详细日志（DEBUG 级别，包含完整堆栈）
    ├── error_report.json        # 🆕 错误报告（错误分类、统计、堆栈）
    ├── summary.json            # 📊 汇总结果（包含成功率、统计信息）
    ├── evaluation_report.md    # 📄 Markdown 报告（包含错误摘要）
    └── sections/               # 📂 各章节评估结果
        ├── 01_项目概览与技术栈.json
        ├── 02_内存管理.json
        └── ...
```

### 示例输出

```
============================================================
🚀 OS-Agent D 评估开始（增强版）
   仓库: my-os
   repo_path: C:\...\repos\my-os
   output_dir: C:\...\output\my-os
   评估输出: C:\...\evaluation\my-os
   模型: deepseek/deepseek-v3.2
   章节总数: 13
   日志文件: C:\...\evaluation\my-os\evaluation.log
   重试配置: 最大3次, 退避2-60秒
============================================================

📌 评估章节: 01_项目概览与技术栈.md

【步骤 1/500】🔧 调用工具:
   find_human_docs(my-os/ "os kernel design")
   ✅ find_human_docs: 找到 3 个文档

【步骤 2/500】🔧 调用工具:
   read_human_doc(README.md)
   ✅ read_human_doc: 返回 150 行 (5000 字符)

【步骤 3/500】🔧 调用工具:
   verify_claim_in_source(repo_path, "使用 Buddy System", "buddy|BuddyAllocator")
   ✅ verify_claim_in_source: ✓ 源码有匹配

   ...

   ✅ 01_项目概览与技术栈.md: 85.3 分 - 覆盖较好，准确性高...
   📄 已保存: C:\...\evaluation\my-os\sections\01_项目概览与技术栈.json

📌 评估章节: 02_内存管理.md
   ❌ 网络错误: ConnectionError: Connection refused
   🔄 正在重试 (1/3)...
   ⏱️  等待 2 秒后重试（网络错误）...

【步骤 15/500】🔧 调用工具:
   find_human_docs(my-os/ "mm memory paging")
   ✅ find_human_docs: 找到 2 个文档

   ...

   ✅ 02_内存管理.md: 78.1 分 - 深度分析到位，但缺少 Slab 分配器...

============================================================
✅ 评估任务完成
   📊 统计:
      - 总章节数: 13
      - 成功: 12
      - 失败: 1
      - 跳过: 2
   🎯 综合评分: 82.5 / 100
   ⏱️  耗时: 256.3 秒 (4.3 分钟)
   📋 日志: C:\...\evaluation\my-os\evaluation.log
   ⚠️  错误数: 2 (详见错误报告)
============================================================
```

---

## 📜 核心演进史 (Key Version History)

> 从最早期的基础描述模块，本作在各个子版本的演进中不断填补了 LLM 的认知短板，并建立起牢不可破的沙盒机制。

#### 🆕 **v3.3 OS-Agent C 客观量化查重增强 & 并发安全修复**（2026-03-20）
- **结构化精确特征提取**：粗筛阶段新增 LLM JSON 精确字段提取，并在后续版本中从最初 13 项少量校正字段扩展为覆盖更广的精确特征集（框架/架构/内核类型、页表模式、分配器、任务模型、IPC、VFS/FS、socket 形态、I/O 多路复用、驱动/设备发现、`procfs/devfs/tmpfs`、安全权限模型及关键数值字段），显著减少单靠嵌入向量造成的误判。
- **框架感知权重调整**：同框架项目间自动降低框架贡献维度（D1/D2/D7）权重、上调自研核心维度（D3~D8）权重，防止共享框架导致的虚高相似度评分。
- **精确字段加分升级**：`struct_score` 由原先少数字段的最高 **+0.15**，升级为覆盖多类稳定实现事实字段的最高 **+0.30**；同时粗筛最终分改为**严格归一化到 `0~1 / 0~100%`**，确保“完全相似 = 100%”语义稳定，更适合查重排序与阈值判断。
- **Token Jaccard 工具**：新增 `compare_function_tokens`，对两仓库中同名函数体进行 token 化并计算 Jaccard 相似度，输出独有关键词摘要，提供代码实现层面的客观数字证据。
- **Call Graph Jaccard 输出**：增强 `compare_call_graphs`，在输出末尾追加节点集合 Jaccard = |交集| / |并集|，量化调用拓扑结构相似度。
- **c09_innovation 双维量化锚定**：强制 Agent 对 5 个核心函数分别获取 Token Jaccard 与 CG Jaccard，以加权均值确定最终 0-100 评分区间，结论有量化证据可追溯。
- **`lsp_set_target_arch` 竞争修复**：补加 `async with _lsp_global_lock`，确保 LSP 重启操作等待所有飞行中请求完成后才执行，消除并发调用时的竞态窗口。
- **`compare_function_tokens` 类型安全**：`syscall_count_real` 和 `trapframe_bytes` 的精确加分逻辑增加 `int()` 类型规范化，防止 LLM 以字符串输出数字时导致的 `TypeError`。

#### 🆕 **v4.0 阶段级 Plan-Execute 与执行契约**（2026-03-27；后续迭代）
- **阶段级 Plan-Execute**：`os_agent_d_describe.py` 与 `os_agent_c_fine.py` 使用 `StageState` / `PlanSpec`；Describe 在 Plan 中锁定 **`execution_steps`**，Execute 提示词注入 **`STAGE_EXECUTION_CONTRACT`**（证据路径、文风与粒度等）。
- **动态上下文**：`repo_profile`、`evidence_cache`、`external_background` 等经 `render_plan_context` 注入 Execute。
- **证据账本 (`evidence_index`)**：可从工具轨迹抽取，供 Execute 与内存侧逻辑参考；**不**写入 `_per_stage`。
- **粗筛链路保持轻量**：`os_agent_c_coarse.py` 没有硬套完整 PE，而是新增 `coarse_preplan` 与 `validate_coarse_output()`，继续保持“预侦察 + 指纹构建 + 向量检索”的确定性流水线。
- **受限 `web_search`**：新增 `tools/web_search.py`，默认关闭，只允许用于“全国大学生操作系统比赛”背景、赛道定位、目标要求和技术概览；禁止作为源码实现证据或查重依据。
- **细粒度并发保护而非降并发**：保留多 tool call / 多阶段并行能力，只对共享状态热点加最小粒度保护。当前已覆盖同仓库 LSP polyfill/目标架构切换、同项目 RAG 向量索引落盘、同仓库 clone，以及同目标文件写入/导出 PDF，避免把正常的只读检索也串行化。
- **中断后不留“锁死”状态**：并发保护统一采用进程内锁，不落磁盘锁文件；`LSP` 的 `run_coroutine_threadsafe(...).result(timeout=...)` 在超时、异常或手动中断时会主动取消后台 future，避免同一进程里下一次运行被残留协程继续占锁。
- **粗筛最终缓存语义收紧**：`fingerprint.json` 不再单独视为充分缓存命中条件；只有当 `features`、`struct_features`、`embeddings` 三个阶段缓存也完整且 schema 版本匹配时才会直接加载。只要任一阶段缓存缺失，即使最终指纹仍在，也会自动进入重组流程。

#### 🆕 **v3.2 终局合成与抗幻觉架构重构**（2026-03-19）
- **报告生成逆向思维法**：颠覆了流程式生成的刻板印象，将 `01_overview` 移至分析大循环的最后一环执行。Agent 现在会携带前置 12 章的几万字上下文全集，以前所未有的上帝视角凝练出最终的项目概览与完成度评价，并通过首字母编排算法自动归位至报告首发位置。
- **封杀数字虚构幻觉**：删除冗余旧阶段，并以硬性“防打分负向 Prompt”取代，有效抑制了大模型在评价完成度时随意虚构 `7.5/10` 一类不严谨的数字评分体系。
- **自动选手画像注入**：集成纯 Python (`openpyxl`) 的解析桥梁，智能从 `collected-data.xlsx` 回读开发者的学校、年份、赛事及队伍画像，直接雕刻于最终报告顶部。

#### 🆕 **v3.1 LSP 智能降级与 Windows 兼容性加固**（2026-03-15）
- **Cross Compilers提示更新**：`check_env.py` 中优化了 Cross Compilers 检查，并提供了详细的安装提示。
- **jina embedding 优化**： 离线模式，减少报错。
- **智能变量 fallback**：`lsp_get_call_graph` 在遇到变量/静态引用时不再单纯报错，而是自动切换至 `textDocument/references` 模式并向 Agent 解释原因，确保数据流分析不中断。
- **符号位置打分驱动**：修正了 LSP 锚点可能落在 doc-comments 导致的解析失败，新增位置权重算法优先锁定实际代码定义行。
- **Windows 稳定性全量补丁**：深度解决 CRLF 换行符导致的偏移 panic、驱动器盘符大小写不一致导致的 VFS 分叉，以及 `nightly-2024-02-03` 遗留的 line-index bug（通过强制注入 `stable` toolchain）。
- **依赖树补全**：正式引入 `tree-sitter-c` 与 `tree-sitter-rust` 原生绑定，大幅提升 RAG 切块精度；新增 `optimum-onnx` 支持，加速本地向量化过程。

#### 🆕 **v3.0 LSP 深度修复与报告质量优化**（2026-03-11）
- **LSP Call Graph 修复**：`callHierarchy/prepare` 现在遍历所有符号位置并优先选取函数定义行，解决了 `exec`/`exit` 等与标准库同名函数无法建立调用层次的问题。
- **裸金属编译环境注入**：自动向 clangd 的 `compile_flags.txt` 注入 `-ffreestanding -fno-builtin`，确保 OS 代码在无标准库环境下被正确解析。
- **报告前缀清洗 (`_strip_llm_preamble`)**：LLM 在正式报告前输出的过渡性口语文字（如"现在我已经收集了足够的信息…"）在写入章节文件前自动剥除，不再污染报告格式。
- **`check_env.py` 改进**：新增 `pip --dry-run` 预检（避免每次重装）、修复 Cross Compiler 检查时 `use_resolve` 未定义的 `UnboundLocalError`、新增多架构交叉编译器自动检测。
- **`requirements.txt` 依赖宽松化**：`transformers` 从 `==4.34.0` 改为 `>=4.36.0,<4.58.0`，解决与 `optimum-onnx` 的版本冲突和无谓降级。
- **路径探测补全**：`_resolve_lsp_binary` 新增 `~/go/bin/` 搜索路径，修复 `gopls` 安装后被误判为未找到的问题。

#### 🆕 **v2.9 高阶 Git 历史语意化钻取探针**（2026-03-07）
- 细粒度深钻机制 (`path_filter`) 规避全局分析引发的 Token 爆炸。
- 新增三大神级代码编年史探针：文件进化史 (`trace_file_evolution`)、大盘协作图谱 (`analyze_authors_contribution`)、核心 Commit 源码提词透视镜 (`get_commit_diff_summary`)。

#### 🆕 **v2.8 Git 语义化沉浸分析与工具生命周期隔离**（2026-03-04）
- 纯 LLM 语义化历史推演，全面弃用传统统计 Python 图表。
- 严格限定大模型的工具生命周期（Stage-Based Tool Provisioning），彻底切断环境外溢与污染，在特定领域精准限制探索边界。

#### 🆕 **v2.7/v2.6 评估全链路监控防断连优化**（2026-03-01）
- 新增 **`ErrorTracker`** 与指数退避阻断：网络/API/超时自动断点重试。
- 本地克隆增强（防 Windows NTFS 截断），并在 Conda 环境下深度解决底层 Rust 与 Clang 语言服务器安装检测与修复。

#### 🆕 **v2.4 - v2.5 代码深度检测：从正则破茧至原生 AST 语义分析**
- 引入 `clangd` / `rust-analyzer` 等原生语言服务器多路复用，自动 Polyfill 编译环境以生成正确的宏与函数依赖链拓扑图。
- 强化 Stage Prompts 深度防骗约束（检测 `todo!()`、桩代码），使用严格的验证探针阻隔其信口开河的能力。

#### 🆕 **v2.0 - v2.2 D 系列框架立项与多重反幻觉评估重构**
- 立项评判机器人，引入“证据为王”原则（强制源码验真）。基于代码而非仅仅“大纲设计书”来输出终极比对结论。

---

## 📁 核心项目结构

```
OS-Agent/
├── os_agent_d_describe.py          # Agent D：OS 源码深度描述（13 个分析阶段 + 仓库准备/RAG 预索引）
├── os_agent_d_evaluate.py          # Agent D：报告自动评估
├── os_agent_c_coarse.py            # Agent C：粗筛（pre-plan + 向量相似度检索）
├── os_agent_c_fine.py              # Agent C：精比（阶段级 Plan→Execute）
├── check_env.py                    # 环境检查脚本（含依赖预检与 LSP 自动安装）
├── test_api.py                     # LLM API 连通性快速测试
├── force_download_jina.py          # Jina 嵌入模型强制下载脚本
├── verify_jina.py                  # Jina 嵌入模型验证脚本
├── requirements.txt                # Python 依赖
├── CHANGELOG.md                    # 变更日志
├── .env                            # 环境变量配置（需自行创建）
├── .env.example                    # 环境变量配置模板
├── core/
│   ├── agent_builder.py            # Agent 构建器（planner/executor/sub-agent）
│   ├── code_rag.py                 # 代码 RAG 引擎（AST 解析 + 向量索引）
│   ├── vectorizer.py               # 本地 Embedding 向量化（Jina 模型）+ 结构化精确特征提取
│   ├── vector_store.py             # 向量数据库存取（含框架感知权重 + 精确字段加分）
│   ├── utils.py                    # 公共工具函数（格式化、仓库名解析）
│   ├── error_handling.py           # 错误处理模块（分类、重试、追踪）
│   ├── per_types.py                # v4.0：StageState / PlanSpec 等核心数据结构
│   ├── per_planner.py              # v4.0：plan 阶段、repo_profile、dynamic_context
│   ├── per_executor.py             # v4.0：草稿与 evidence_index 抽取
│   ├── per_llm_stages.py           # v4.0：LLM 规划 Agent（Plan JSON 解析与合并）
│   └── hf_env.py                   # Hugging Face 默认镜像、嵌入模型加载
├── tools/
│   ├── lsp_ops.py                  # LSP 封装（callHierarchy、定义、引用、大纲）
│   ├── file_ops.py                 # 文件操作（read_code_segment、grep_in_repo）
│   ├── git_ops.py                  # Git 操作（历史分析、作者贡献、Diff 透视）
│   ├── compare_ops.py              # 项目比对工具（Agent C 精比辅助，含 Token/CG Jaccard）
│   ├── describe_ops.py             # 描述模块专用工具
│   ├── eval_ops.py                 # 评估专用工具（人类文档搜索、声明验证）
│   └── web_search.py               # v4.0：受限外部背景搜索（默认关闭）
├── repos/                          # 克隆的 OS 仓库（运行时自动克隆，.gitignore 忽略）
├── output/                         # 描述模块输出（按项目名划分）
│   └── <os-name>/
│       ├── sections/               # 各章节分段报告
│       ├── _per_stage/             # v4.0：侧车（repo_profile、各阶段 *_plan.json）
│       ├── OS技术分析报告_<os-name>.md
│       └── describe_error_report.json  # 错误报告（如有）
└── evaluation/                     # 评估模块输出（按项目名划分）
    └── <os-name>/
        ├── evaluation.log          # 详细日志
        ├── error_report.json       # 错误报告
        ├── summary.json            # 汇总评分
        ├── evaluation_report.md    # Markdown 评估报告
        └── sections/               # 各章节评估 JSON
```


---

## ⚙️ 配置说明

### 支持的 LLM 模型

程序使用 OpenAI 兼容的 API，支持：
- DeepSeek: `deepseek/deepseek-v3.2`（默认）
- OpenAI: `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo`
- 其他 OpenAI 兼容的模型

### 自定义分析阶段

可以在 `os_agent_d_describe.py` 的 `STAGES` 列表中添加或修改分析阶段。每个阶段包含：
- `id`: 阶段 ID
- `title`: 阶段标题
- `prompt`: 分析提示词
- `skip_in_report`: 是否跳过写入最终报告

### v4.0：侧车计划产物

`describe` 在每章 **Plan** 合并后、**Execute** 写完章节时，将结构化计划落盘，便于对照提示词与执行契约、排查断点续跑问题：

- `repo_profile.json`：仓库级先验（框架猜测、架构、关键目录、语言混合）
- `*_plan.json`：阶段 `PlanSpec`（含 **`execution_steps`**、`must_cover`、`seed_paths` 等）

`evidence_index` 仅在内存中用于 Execute / 工具侧逻辑，**不**写入 `_per_stage`。`fine compare` 仅在 `vs_<候选>_per/` 下保留 `*_plan.json`。

### 支持的 CPU 架构

`find_os_core_modules` 工具支持自动识别以下架构相关代码：

| 类型 | 架构 |
|------|------|
| **国际架构** | x86, x86_64, ARM, ARM64, RISC-V, MIPS |
| **国产架构** | 龙芯 (LoongArch)、申威 (Sunway)、飞腾 (Phytium)、鲲鹏 (Kunpeng)、海光 (Hygon)、兆芯 (Zhaoxin)、玄铁 (XuanTie) |

### 工具限制说明

为防止 Token 溢出和确保安全，各工具有以下限制：

| 工具 | 限制 | 说明 |
|------|------|------|
| `read_code_segment` | 最大 100,000 字符 | 只能访问 `repos/`、`output/`、`evaluation/` 目录 |
| `grep_in_repo` | 最多 20 条匹配 | 在源码中搜索关键词/正则，验证技术声明 |
| `read_file` (评估) | 最大 50,000 字符 | 只能访问仓库和 output 目录 |
| `list_repo_structure` | 默认 4 层深度 | 可通过 `max_depth` 调整 |
| `lsp_get_definition` / `lsp_get_references` | 本地化跨文件追踪 | 不受文件切片截断影响，提供 AST 真实函数映射与依赖拓扑 |
| `lsp_get_document_outline` | 文件大纲提取 | 快速获取文件中所有函数/结构体/枚举的名称与行号 |
| `analyze_git_history` | 每页最多 50-100 条 | 支持 `skip` 分页检索和 `path_filter` 目录定点钻取，提供文件级改动详情以供 LLM 判定边界 |
| `trace_file_evolution` | 单一文件演进链 | 利用底层的 `git log --follow` 抽离核心文件的所有重构记录，无视历史变迁和重命名 |
| `analyze_authors_contribution` | 最大遍历 2000 个提交 | 洞察 Repo 开发模式（单人闭门造车还是社区分包机制），并统计作者的核心贡献目录 |
| `get_commit_diff_summary` | 硬截断 20000 字符 | 透视极度模糊的 Commit 留言，去除干扰注释和空行，向 LLM 呈现最原生核心的功能大修逻辑 |
| **阶段隔离限制** | 严格白名单 | LLM 将只能在对应 Stage 获取特定工具（如 14 阶段才给 Git 工具） |

### 并发与共享状态策略

系统默认**不主动降低并发度**。只有在工具存在共享状态或共享输出路径时，才做细粒度保护：

- **仓库级 LSP 配置锁**：保护 `compile_flags.txt`、`Cargo.toml`、`src/lib.rs`、`.os_agent_lsp_target` 的生成与切换，避免同仓库并行 polyfill 或切架构时互相覆盖。
- **项目级 RAG 索引锁**：保护 `output/<proj>/_vector_db/chunks.json` 与 `vectors.npy` 的构建和落盘，避免同项目被重复建索引或写坏索引文件。
- **仓库级 clone 锁**：只串行同一个 `repos/<name>` 目录的克隆，其他仓库仍可并行。
- **目标路径写锁**：`write_file()` 与 `convert_md_to_pdf()` 仅在写入同一路径时串行，避免覆盖。
- **只读工具不受影响**：源码读取、grep/RAG 查询、评估文档读取、受限 `web_search` 等不因上述保护被整体串行化。

**截断提示**：所有工具在输出被截断时会明确告知 LLM，例如：
```
📊 统计: 分析了 20 个文件，共 45 个结构体，128 个函数
⚠️ [文件数限制] 只分析了前 20/35 个文件
⚠️ [显示限制] 还有 12 个结构体和 56 个函数未显示
```

## 🔧 常见问题

### Q: 分析过程中断或出错怎么办？

程序支持断点续传。已完成的章节会保存在 `output/<os-name>/sections/` 目录，重新运行时会自动跳过已完成的部分。

**v2.6** 新增智能重试机制：
- 网络/API/超时错误自动重试（最多 3 次，指数退避）
- 单阶段失败不影响后续阶段执行
- 运行结束时输出错误摘要，并生成 `output/<os-name>/describe_error_report.json`

**v4.0** 可结合 `_per_stage/*_plan.json` 与 `repo_profile.json` 对照各章锁定步骤与 must_cover；章节正文以 `sections/*.md` 为准。

若某章质量不符预期，优先检查 `output/<os-name>/_per_stage/` 下对应 `*_plan.json` 与 `os_agent_d_describe.py` 中该阶段 `prompt` / 执行契约。

并发保护相关的运行时保证：
- 当前锁都是**进程内锁**，不会在磁盘上遗留 `.lock` 一类文件，因此程序被终止后，下次启动不会因为旧锁残留而无法运行。
- 对 `LSP` 后台协程，若出现超时、异常或手动中断，系统会主动取消对应 future，避免“本次虽然停了，但后台还在继续跑并占着仓库级锁”的情况。
- 共享状态保护只影响**同一仓库 / 同一项目 / 同一路径**的竞争写入；不会把其他仓库、其他输出路径、或只读查询一起拖成串行。

### Q: web_search 什么时候该开？

只建议在以下场景开启：
- 写项目概述时补充“全国大学生操作系统比赛”背景
- 解释赛道定位、目标要求、功能要求
- 补充 OS 架构常识或比赛生态背景

**不要**用它做：
- 仓库实现事实判断
- 查重结论判断
- 替代源码证据

如果不配置 `ENABLE_WEB_SEARCH=true` 和 provider 密钥，系统会自动保持关闭。

### Q: 如何评估已有的报告？

使用 `os_agent_d_evaluate.py` 直接评估：

```bash
# 使用 .env 中的 REPO_URL
python os_agent_d_evaluate.py

# 或指定仓库 URL
python os_agent_d_evaluate.py --repo-url https://gitlab.educg.net/xxx/os-project.git
```

### Q: 评估失败怎么办？

**v2.0 增强版**提供了完整的错误追溯：

1. **查看日志**：`evaluation/<repo_name>/evaluation.log`
   - 包含详细的错误信息和堆栈跟踪

2. **查看错误报告**：`evaluation/<repo_name>/error_report.json`
   - 错误分类统计
   - 每个错误的完整上下文

3. **常见问题**：
   - **网络错误**：检查网络连接，程序会自动重试 3 次
   - **API 错误**：检查 API 密钥和配额，增加退避时间
   - **超时错误**：在 `.env` 中增加 `EVAL_REQUEST_TIMEOUT=600`
   - **解析错误**：程序会自动追问 Agent 重新生成 JSON

4. **配置重试**：
   ```bash
   # 在 .env 中配置（未来版本支持）
   EVAL_MAX_RETRIES=5
   EVAL_INITIAL_BACKOFF=3
   EVAL_MAX_BACKOFF=120
   ```

### Q: 如何获取更详细的调试信息？

在 `.env` 中设置：

```bash
# 提升日志级别到 DEBUG
LOG_LEVEL=DEBUG

# 启用详细日志（同时输出到控制台）
VERBOSE_LOGGING=true
```

### Q: 支持哪些 OS 项目？

理论上支持任何 OS 仓库，包括：
- Rust 实现的 OS（如 rCore, ArceOS）
- C 实现的 OS（如 xv6, Linux）
- 混合实现的 OS

### Q: 终端里大量 `LSP [...] STDERR: I[...]` 是什么？

本地 **clangd / rust-analyzer** 等会把运行日志写到 **stderr**，属于**正常索引/编译数据库加载信息**，一般**不是**分析失败。若需降噪，可自行调低对应 Language Server 的日志级别或重定向 stderr。

### Q: 嵌入模型仍连 `huggingface.co`？

先确认进程内实际基址：日志里应有 `HF_ENDPOINT=...`（`apply_hf_hub_env_defaults` 打出）。若 `.env` 已写官方地址则会**按官方**访问；若未写 `HF_ENDPOINT` 仍走官方，检查是否设置了 **`OS_AGENT_USE_HF_MIRROR=false`**，或系统环境变量是否抢先于 `.env`（Describe 已 `load_dotenv(override=True)`）。

---

## 🛑 局限性与已知困难 (Known Limitations)

在深度分析多个复杂 OS 仓库的过程中，我们识别并记录了以下核心技术瓶颈：

1. **环境兼容性敏感**：Windows 宿主机下的 LSP (clangd) 对路径格式极其敏感，UNC 路径或不规范的 `file:///` 前缀会导致 VFS 崩溃。
2. **工作区破碎化**：部分 Rust 项目缺乏根目录 `Cargo.toml` 或采用非标准嵌套布局，导致原生 LSP 无法建立全局索引，产生“语义盲区”。
3. **架构语义“灰化”**：由于 OS 代码中包含大量 `#[cfg(target_arch = "...")]`，当本地解析架构与目标架构不匹配时，关键代码块会被 LSP 标记为不激活，导致调用图缺失。
4. **依赖库生命周期风险**：若 `Cargo.toml` 中的 Git 依赖仓库被第三方原作者删除（404），传统的 `cargo fetch` 会导致分析进程永久阻塞。
5. **LLM 幻觉风险**：在缺乏直接代码证据时，大模型在压力下可能产生“拟合性幻觉”，将设计文档中的描述误认为已实现的源码。

---

## 🛡️ 应对策略与鲁棒性机制 (Robustness Mechanisms)

针对上述困难，OS-Agent 已在工具层内置了以下原生自愈与加固机制：

1. **自愈式工作区生成 (Virtual Manifest Polyfill)**：
   - 自动递归探测仓库内所有嵌套的 `Cargo.toml`。
   - 动态生成合成工作区清单 (`[workspace]`)，无需修改源码即可让 LSP 获得全局视角。
   - **Windows 级自愈**：自动转换物理路径换行符风格，并同步 VFS 驱动器标识符。

2. **离线安全沙箱 (LSP Offline Sandbox)**：
   - 强制启用 `CARGO_NET_OFFLINE="true"` 及初始化参数 `--offline`。
   - 物理阻断任何形式的网络悬挂风险，确保即便上游依赖库 404，本地分析链依然能够正常启动。
   - 使用独立的 `CARGO_TARGET_DIR` 并禁用构建脚本执行，防止主机污染与构建死循环。

3. **双模混合动力引擎 (Hybrid Fallback Engine)**：
   - 系统实时监控语义分析器的返回质量。
   - 当 LSP 语义分析因为复杂架构或类型推导失败导致返回空结果时，系统自动切换至 **Grep 静态分析引擎**。
   - 确保在“语义图谱”不完整的极端情况下，依然能提供可靠的文本级调用关系。

4. **架构自动注入与跨平台 Polyfill**：
   - 自动探测 `os/src/arch` 路径并猜解目标 CPU 架构。
   - 在 LSP 初始化时注入 `cargo.target`，破解代码“灰化”难题，实现跨架构的代码可见性。

5. **三态反幻觉验证 (Three-State Detection)**：
   - 强制 Prompt 遵循原则：未发现代码证据时必须标记 `❌ 未实现`，禁止凭空捏造。
   - 明确区分 `✅ 已实现` 与 `🔸 桩函数`，确保技术报告的诚实性。

6. **全链路执行韧性 (Execution Resilience)**：
   - **智能重试与退避 (Intelligent Retry)**：针对 API 超时、网络波动或工具执行异常，内置 7 种错误分类及指数退避重试机制。
   - **递归深度熔断 (Recursion Limit)**：为 Agent 执行链设置硬性熔断阈值（默认 500 步），防止复杂逻辑导致的 Token 无限消耗。
   - **自愈式摘要驱动 (Forced Summary)**：当 Agent 在某阶段陷入“分析死循环”且即将触达步数限制时，系统自动发送“追问消息”强制 LLM 脱离工具调用，立即生成基于已有信息的最佳报告。
   - **断点续传 (Breakpoint Resume)**：实时保存各阶段中间产物，支持在发生不可控中断后从断点无感恢复，无需重新运行。

7. **Git 与 Token 效率优化 (Optimization)**：
   - **递进式下钻分析 (Path-Filter Drill-down)**：针对包含数千个文件的巨型提交（如合入整个第三方模块），支持指定 `path_filter` 进行定点下钻，避免输出撑爆上下文。
   - **智能历史浓缩 (History Distillation)**：内置 `get_git_history_summary` 工具，采用“头部+尾部”双端保留算法，在确保分析跨度的同时将 200 个 commit 的上下文压缩并在 8000 字符内。
   - **Windows NTFS 兼容补丁**：针对 Linux OS 项目中可能存在的“非法 Windows 文件名”（如冒号 `:` 等），在克隆阶段自动检测并注入 `protectNTFS=false` 补丁，确保跨平台分析链的完整性。

---

## 📄 许可证

MIT License

---

## 🙏 致谢

- [LangChain](https://langchain.com/) - LLM 应用框架
- [LangGraph](https://langchain-ai.github.io/langgraph/) - Agent 编排框架
