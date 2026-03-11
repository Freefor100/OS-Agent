# OS-Agent

🤖 **OS 仓库自动分析与技术报告生成工具**

基于 LLM Agent 的操作系统项目自动分析工具，能够深入分析 OS 仓库的代码结构、技术栈、内核实现，并生成专业的技术分析报告。

---

## 📋 功能特性

### 1. OS-Agent D：自动源码描述 (`os_agent_d_describe.py`) ✨ **增强版**

对 OS 仓库进行 **14 阶段**的深度技术分析，内置本地 RAG 语义搜索、LSP 调用图分析、智能重试与错误追踪机制：

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
| 14 | 执行摘要与报告整合 |

**核心分析机制（三级联动）：**

1. 🔍 **RAG 语义搜索（首选）**：`rag_search_code` 对整个仓库代码建立本地向量索引（Jina Embedding），支持语义级模糊搜索（如"查找页表映射实现"），穿透复杂目录结构直接定位相关代码块，大幅减少无效的目录遍历。
2. 🌳 **LSP 拓扑展开**：通过 `lsp_get_call_graph`（多层递归调用树）、`lsp_get_definition`（跨文件跳转）、`lsp_get_references` 构建精确的 AST 调用拓扑图。
3. 🛠️ **Grep 降级兜底**：仅当 RAG 和 LSP 均无结果时，才触发 `grep_in_repo` 静态文本搜索。

### 2. OS-Agent D：自动报告评估 (`os_agent_d_evaluate.py`) ✨ **增强版**

使用 Agent 将自动生成的报告与仓库内人类撰写的文档进行对比评估。

### 3. OS-Agent C：智能查重与比对 (`os_agent_c_coarse.py` / `os_agent_c_fine.py`)

面向小型操作系统的分析比对，系统分为两阶段架构，快速在新旧作品间进行查重与创新点分析：

- **粗筛模块 (`os_agent_c_coarse.py`)**：基于特征指纹（LLM 提取）与本地 Embedding（7维架构特征向量），计算目标仓库与历史库中所有作品的加权余弦相似度，极速锁定 Top-5 最相似候选项目。
- **精比模块 (`os_agent_c_fine.py`)**：基于 LLM Agent 对粗筛出的 Top-5 候选进行源码级深度比对。包含技术栈与架构差异、Call Graph 对比、创新点挖掘及代码重合度详尽分析，最终输出完整的 Markdown 比对报告。

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
```

每个结果含相似度分数、文件路径与起止行号、节点类型、代码体（≤800字符，超出提示使用 `read_code_segment` 读完整内容）。

#### 三级联动分析策略

| 优先级 | 工具 | 适用场景 |
|--------|------|---------|
| 🥇 **首选** | `rag_search_code` | 不知道函数名，只知道功能描述 |
| 🥈 **次选** | `lsp_get_call_graph` / `lsp_get_definition` | 已找到符号，展开调用拓扑 |
| 🥉 **兜底** | `grep_in_repo` | 精确关键词/正则，或前两者均无结果 |

#### 模型与存储配置

| 配置项 | 默认值 |
|--------|--------|
| 嵌入模型 | `jinaai/jina-embeddings-v2-base-code`（`.env` 中 `CODE_EMBEDDING_MODEL` 可覆盖） |
| 向量维度 | 768 维，float32 |
| 索引位置 | `output/<proj>/_vector_db/`（与分析报告同级） |
| 建索引时代码截断 | ≤ 2000 字符/块 |
| 搜索结果截断 | ≤ 800 字符/块（防 Token 溢出） |

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

> LSP 工具（`lsp_get_definition`、`lsp_get_references`、`lsp_get_document_outline`）需要本地安装对应语言的 Language Server。未安装时会自动降级为正则解析，但**精度大幅下降**。

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
```

#### 配置项说明

| 配置项 | 必需 | 说明 |
|--------|------|------|
| `OPENAI_API_KEY` | ✅ | OpenAI 兼容 API 的密钥 |
| `OPENAI_API_BASE` | ✅ | API 地址（支持 OpenRouter、DeepSeek 等） |
| `MODEL_NAME` | ❌ | LLM 模型名称，默认 `deepseek/deepseek-v3.2` |
| `REPO_URL` | ✅ | 要分析的 OS 仓库 Git 地址 |

### 4. 运行分析

```bash
# 直接运行（使用 .env 中的配置）
python os_agent_d_describe.py
```

输出目录结构：
```
output/
└── <os-name>/
    ├── sections/          # 各章节分段报告
    │   ├── 01_项目概览与技术栈.md
    │   ├── 02_启动流程与架构初始化.md
    │   └── ...
    └── report.md          # 最终完整报告
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
├── os_agent_d_describe.py          # Agent D：OS 源码深度描述（16 阶段）
├── os_agent_d_evaluate.py          # Agent D：报告自动评估
├── os_agent_c_coarse.py            # Agent C：粗筛（本地 Embedding 相似度比对）
├── os_agent_c_fine.py              # Agent C：精比（LLM 深度源码逐项比对）
├── check_env.py                    # 环境检查脚本（含依赖预检与 LSP 自动安装）
├── test_api.py                     # LLM API 连通性快速测试
├── force_download_jina.py          # Jina 嵌入模型强制下载脚本
├── verify_jina.py                  # Jina 嵌入模型验证脚本
├── requirements.txt                # Python 依赖
├── CHANGELOG.md                    # 变更日志
├── .env                            # 环境变量配置（需自行创建）
├── .env.example                    # 环境变量配置模板
├── core/
│   ├── agent_builder.py            # Agent 构建器（工具绑定、LSP、grep 等）
│   ├── code_rag.py                 # 代码 RAG 引擎（AST 解析 + 向量索引）
│   ├── vectorizer.py               # 本地 Embedding 向量化（Jina 模型）
│   ├── vector_store.py             # 向量数据库存取
│   ├── utils.py                    # 公共工具函数（格式化、仓库名解析）
│   └── error_handling.py           # 错误处理模块（分类、重试、追踪）
├── tools/
│   ├── lsp_ops.py                  # LSP 封装（callHierarchy、定义、引用、大纲）
│   ├── file_ops.py                 # 文件操作（read_code_segment、grep_in_repo）
│   ├── git_ops.py                  # Git 操作（历史分析、作者贡献、Diff 透视）
│   ├── callgraph_ops.py            # 调用图分析（跨文件调用关系）
│   ├── compare_ops.py              # 项目比对工具（Agent C 精比辅助）
│   ├── describe_ops.py             # 描述模块专用工具
│   └── eval_ops.py                 # 评估专用工具（人类文档搜索、声明验证）
├── repos/                          # 克隆的 OS 仓库（运行时自动克隆，.gitignore 忽略）
├── output/                         # 描述模块输出（按项目名划分）
│   └── <os-name>/
│       ├── sections/               # 各章节分段报告
│       ├── report.md               # 最终完整报告
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

---

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
