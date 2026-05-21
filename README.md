# OS-Agent

🤖 **OS 仓库自动分析与技术报告生成工具**

基于 LLM Agent 的操作系统项目自动分析工具，能够深入分析 OS 仓库的代码结构、技术栈、内核实现，并生成专业的技术分析报告。

---

## 📋 功能特性

### 1. OS-Agent D：自动源码描述 (`os_agent_d_describe.py`) ✨ **增强版**

对 OS 仓库进行 **阶段化**深度技术分析（`STAGES`：**02→09 技术章 → `10_history` → `01_overview` 置底**；另含 **00** 仓库准备、**0.5** RAG 预索引）。Describe 当前默认使用 **Multi-Agent 图模式**：程序化 Supervisor 负责调度、并行、锁、断点和发布，Task ReAct Agents 负责查证据并产出结构化草稿，Stage Assembler 与 Review Agent 负责逐题组装和证据支撑审查。

| 阶段 | 内容 |
|------|------|
| 00 | 仓库准备（本地直连克隆，无 LLM 开销） |
| 0.5 | RAG 预索引（代码向量化，支持后续语义搜索，已有索引自动跳过） |
| 02 | 启动/架构与 Trap/系统调用 |
| 03 | 内存管理（物理/虚拟/分配器） |
| 04 | 进程/线程/调度与多核 |
| 05 | 文件系统与设备 I/O |
| 06 | 同步互斥与进程间通信 |
| 07 | 安全机制与权限模型 |
| 08 | 网络子系统与协议栈 |
| 09 | 调试机制与错误处理 |
| 10 | 开发历史与里程碑（Git 语义化分析） |
| 01 | 项目概览与技术栈（**最后执行**，依赖 02–10 各章） |

**无工具 Baseline 对照（`baseline_test.py`）**

- 对 **02–09 题单**各做一次「整仓源码 + 题单」的**单次** LLM 回答（不跑 Plan、不调工具、**不做** JSON 修复重试），再跑与主链路相同的 **Review**，结果落在 **`baseline_output/<repo名>/`**（仅 `_per_stage/*` 与 `review_score.json`，不生成合并 md）。
- 环境变量与主程序一致：需 `.env` 中的 `REPO_URL` 等；可选 `BASELINE_MAX_USER_CHARS` 控制单轮用户消息总长度（默认 2,400,000 字符，过大时会截断平铺源码）。
- 每阶段在终端输出 **Execute / Review 的 total_tokens 与累计**（与主链路 `response_metadata.token_usage` 一致），并落盘 **`baseline_output/<repo名>/token_usage.json`**；若某次为 0，多为 API 未返回用量。

**核心分析机制（三级联动）：**

1. 🔍 **RAG 语义搜索（首选）**：`rag_search_code` 对整个仓库代码建立本地向量索引（Jina Embedding），支持语义级模糊搜索（如"查找页表映射实现"），穿透复杂目录结构直接定位相关代码块，大幅减少无效的目录遍历。
2. 🌳 **LSP 拓扑展开**：通过 `lsp_get_call_graph`（多层递归调用树，包含变量到引用的智能降级）、`lsp_get_definition`（跨文件跳转）、`lsp_get_references` 构建精确的 AST 调用拓扑图。
3. 🛠️ **分层降级兜底**：当 LSP 失败时，系统**首选 Tree-sitter AST 解析**（C/C++/Rust/Go/Zig），再退到语言感知正则、通用 Grep；仅在汇编或前述路径都失败时才使用 ASM 词法兜底。系统具备“智能分层切换”：LSP -> Tree-sitter -> Language-aware Static -> Grep -> ASM(最终兜底)。

**OS-Agent D Multi-Agent 图模式**

直接运行 describe 即进入 Multi-Agent 图模式；`--multi-agent` 仍可传入，但只是兼容旧脚本的 no-op：

```bash
conda run -n os_agent python os_agent_d_describe.py --multi-agent
```

不带参数运行效果相同：

```bash
conda run -n os_agent python os_agent_d_describe.py
```

Multi-Agent 模式采用 **程序化 Supervisor + LLM ReAct Task Agents + 结构化证据黑板**：

- **结构化题单本体**：`core/describe_stage_qa/02-09*.json` 已直接写入 `feature_id`、结构化事实、证据要求、负向搜索策略、三态规则和反例；运行时只读题单本体，不做自动补齐或生成。
- **Supervisor / Repo Profile / Task Builder / Evidence Verifier / Publisher**：程序节点，负责调度、状态、断点、证据校验、schema guard、图谱和产物写入。
- **Stage Plan Agent**：基于结构化题单、`PlanSpec` 和 repo profile 生成 grouped `task_plan[]`；相近题可以合并到一个 task。
- **Task Builder**：程序校验 Plan Agent 的任务，注入题单本体中的 evidence policy / structured facts，修正非法 `question_ids` 并去重；任务怎么合并由 LLM Plan Agent 决定，规则不再替代规划。
- **Task ReAct Agents**：每个 task 都是受限工具集的小 ReAct Agent，主动调用 RAG/LSP/read/build/git 工具查证据；最终输出 evidence candidates 和草稿，系统再生成 `EvidenceRecord`。
- **Evidence Verifier**：校验 path、line、excerpt、证据类型和负向搜索覆盖，输出 `strength` 与 `supports_claim_types`；RAG/grep 默认只是 hint，不能单独支撑 `implemented`。
- **Stage Assembler Agent**：不从零查源码，只消费 task 草稿与绑定证据，逐题统一格式、去重、修正过度表述；三态证据不足会降级为 `unknown`。
- **Review Agent**：默认无源码工具，只读审计题单、最终答案 JSON 与 evidence 摘要；重点检查回答 claim 是否被证据支撑，低分时生成 fix task，再交回 Task Agent 补证据。

并行调度策略：

- `02_boot_trap` 到 `09_debug_error` 以及 `10_history` 可并行执行。
- `01_overview` 必须等待 02–10 全部完成后串行执行。
- 用户只控制 stage 并发与 stage 内 task 并发。LLM 调用由这两个池自然限制；LSP 与 RAG 属于底层共享资源，代码内部固定串行保护。

`.env` 中 OS-Agent D 只保留常用运行项：

```env
OS_AGENT_MAX_PARALLEL_STAGES=2
OS_AGENT_MAX_PARALLEL_TASKS_PER_STAGE=3
OS_AGENT_TASK_AGENT_BUDGET=30
# OS_AGENT_FORCE_STAGES=
OS_AGENT_TERMINAL_MODE=dashboard
```

`OS_AGENT_MAX_PARALLEL_STAGES` 控制 02-09 与 `10_history` 同时跑几个 stage；`01_overview` 始终等前面完成后串行执行。`OS_AGENT_MAX_PARALLEL_TASKS_PER_STAGE` 控制单个 stage 内同时跑几个 Task Agent。默认 `2 × 3`，也就是最多约 6 个 Task ReAct Agents 活跃。

不再暴露单独的 LLM 并发变量，也不再读取旧的并发档位配置。Plan Agent 固定使用 LLM，Task Agent 固定使用 LLM ReAct；规则程序只做 schema 校验、证据审查、证据整理和安全兜底。

`OS_AGENT_TASK_AGENT_BUDGET` 是单个 Task Agent 的唯一循环预算。它直接同时限制 ReAct 图递归次数和工具调用次数；超过后会产生 `tool_blocked` 或由 LangGraph 停止本 task，不再维护额外的内部派生阈值。LLM 抽风导致的固定动作循环属于内置熔断，不需要配置：系统会自动拦截 `AAA`、`ABABAB`、`ABCABCABC` 这类重复工具动作模式。

断点与事件产物写入 `output/<repo>/_agent_state/`：

```text
_agent_state/
├── run_state.json
├── graph_state.json
├── evidence_store.jsonl
├── draft_answer_store.jsonl
├── events.jsonl
├── assembler/
├── stages/
├── tasks/
├── reviews/
└── locks/
```

Multi-Agent 终端输出支持 `dashboard` / `compact` / `verbose` / `silent`。默认 `dashboard` 会优先使用 `rich` 彩色表格和动态刷新；缺少 `rich` 时自动回退到无依赖 ANSI 仪表盘。Dashboard 会显示 active stages、active tasks/tools、LLM/tool/review 计数和最近事件。并行节点不会直接 `print()`，而是写入 `events.jsonl` 并由 renderer 统一显示，避免并发输出交错。

完整排查日志会同时写入：

```text
output/<repo>/_agent_state/events.jsonl
output/<repo>/_agent_state/debug_events.jsonl
```

其中 `debug_events.jsonl` 保留完整 `metadata`、工具参数、工具结果 excerpt、token usage 和 warning/error 信息，不受终端预览长度影响，方便复盘某个 task agent 的循环、卡顿或证据查找问题。

**v4.0 受限外部背景补充**

- 新增 `web_search` 工具，但**默认关闭**。
- 该工具只允许查询“全国大学生操作系统比赛”背景、赛道定位、目标要求、功能要求和公开技术背景。
- `web_search` 结果只能用于**技术概览 / 概述总结**，**绝不能**作为仓库实现事实、查重判断或源码证据。

**报告拼装（各阶段结束后）：Call Graph 概览块** (`tools/callgraph_overview.py`) ✨ **新增**

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

### 2. 本地工具安全与沙盒限制

为防止 Token 溢出与确保本地系统安全，工具仅能访问白名单目录（如 `repos/`、`output/`），具体额度与行为见下文「工具限制说明」。

### 3. 本地代码 RAG 语义搜索引擎

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
- **多架构 Cross Compiler 检测**：自动扫描 RISC-V、ARM、LoongArch 交叉编译器，并识别常见别名/fallback（如 `riscv-none-elf-gcc`、`riscv64-unknown-elf-gcc`、`riscv64-linux-gnu-gcc`、`loongarch64-linux-gnu-gcc`、`aarch64-linux-gnu-gcc`）
- **路径自动修复**：通过 `_resolve_lsp_binary` 探测 `~/go/bin/`、`~/.cargo/bin/`、WinGet 等非标准安装目录，无需手动配置 PATH

### 2. 安装 Language Servers（LSP 工具依赖）

> LSP 工具（`lsp_get_definition`、`lsp_get_references`、`lsp_get_document_outline`）需要本地安装对应语言的 Language Server。未安装或超时时会**首选 Tree-sitter AST 解析**（C/C++/Rust/Go/Zig），再走语言感知正则、通用 Grep；仅在汇编或最终兜底场景才使用 ASM 正则。

LSP 目标架构推断会优先读取仓库内显式标记 `.os_agent_lsp_target`，也会从 `rust-toolchain.toml`、`.cargo/config(.toml)`、`Cargo.toml`、`Makefile`、`CMakeLists.txt`、`build.zig`、`linker/*.ld(s)` 等构建配置中识别 target triple / 工具链前缀 / QEMU 与 linker `OUTPUT_ARCH` 线索。对 OS 内核场景，`riscv64-linux-gnu`、`loongarch64-linux-gnu`、`aarch64-linux-gnu` 这类 hosted 工具链会在非用户态上下文中映射为更适合 clangd 裸机解析的 target（如 `riscv64-unknown-elf`、`loongarch64-unknown-elf`、`aarch64-unknown-none-elf`）。手动调用 `lsp_set_target_arch(repo_path, target)` 后，会强制重启受 target 影响的 `rust-analyzer` 与 `clangd` 客户端，避免 Rust/C/C++ 混合仓库继续使用旧架构索引。

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
    ├── features/               # 每阶段 Feature Schema Bank 展开结果
    ├── feature_graph.json      # Feature/Question/Evidence/File/Symbol/Claim 图谱
    ├── feature_graph.cypher    # Neo4j 导入用 Cypher
    ├── feature_graph.graphml   # 通用图工具导入格式
    ├── OS技术分析报告_<os-name>.md
    └── describe_error_report.json
```

---

## 📜 核心演进史 (Key Version History)

> 从最早期的基础描述模块，本作在各个子版本的演进中不断填补了 LLM 的认知短板，并建立起牢不可破的沙盒机制。

#### 🆕 **v4.0 / v4.1 Describe Multi-Agent 图模式**（2026-03-27；后续迭代）
- **Describe 默认 Multi-Agent**：`os_agent_d_describe.py` 直接进入 `core.describe_graph.MultiAgentRuntime`；旧串行 Describe Plan→Execute→Review 链路已移除，`--multi-agent` 仅作为兼容旧脚本的 no-op。
- **结构化题单定稿**：02-09 题单 JSON 本体已直接 materialize 为可人工评审的结构化题单，运行时不再自动扩展或补齐；`tri_state_impl` 的 `implemented / stub / not_found / unknown` 判定边界、证据要求和反例都写在题单文件里。
- **程序化图调度**：Supervisor 负责仓库准备、RAG 预索引、并行 stage/task 调度、锁、断点续传与发布；`Stage Plan Agent` 只生成 grouped task plan，`Task Builder` 会程序化校验并限流。
- **结构化证据黑板**：Task ReAct Agents 产出候选证据与 `DraftAnswerRecord`，系统生成并校验 `EvidenceRecord`；Evidence Verifier 会区分 hint/weak/strong/invalid，并输出可支撑的 claim 类型。
- **Feature Graph 输出**：最终发布 `feature_graph.json`、`feature_graph.cypher`、`feature_graph.graphml`，以 Feature/Question/Evidence/File/Symbol/Claim 节点展示 OS 机制 DAG 与证据追溯。
- **旧 JSON-QA Repair 删除**：Describe 不再运行整章 JSON 修复循环，也不再写旧 repair 侧车。Review Agent 自身的 JSON 解析重试仍保留在 `core.describe_stage_review` 内。
- **LSP target 与工具链推断增强**：`tools/compile_context.py` 现在从 Cargo/Make/CMake/Zig/linker script/QEMU 线索推断 target triple，并区分裸机内核与 hosted userland；`tools/lsp_ops.py` 优先使用裸机 RISC-V 工具链（`riscv-none-elf-gcc` / `riscv64-unknown-elf-gcc`），同时保留发行版常见 `riscv64-linux-gnu-gcc` fallback。`lsp_set_target_arch` 写入 `.os_agent_lsp_target` 后会重启 Rust 与 C/C++ LSP 客户端，避免混合语言仓库的 clangd 继续沿用旧 target。
- **模型输出上限兼容**：`DESCRIBE_MAX_OUTPUT_TOKENS` 继续用于降低长 JSON-QA 截断风险；对 DeepSeek 兼容接口，`max_tokens` 会通过 `extra_body` 透传，避免 langchain-openai 将其改写成 DeepSeek 不接受的参数名。
- **受限 `web_search`**：新增 `tools/web_search.py`，默认关闭，只允许用于“全国大学生操作系统比赛”背景、赛道定位、目标要求和技术概览；禁止作为源码实现证据或查重依据。
- **细粒度并发保护而非降并发**：保留多 tool call / 多阶段并行能力，只对共享状态热点加最小粒度保护。当前已覆盖同仓库 LSP polyfill/目标架构切换、同项目 RAG 向量索引落盘、同仓库 clone，以及同目标文件写入/导出 PDF，避免把正常的只读检索也串行化。
- **中断后不留“锁死”状态**：并发保护统一采用进程内锁，不落磁盘锁文件；`LSP` 的 `run_coroutine_threadsafe(...).result(timeout=...)` 在超时、异常或手动中断时会主动取消后台 future，避免同一进程里下一次运行被残留协程继续占锁。
#### 🆕 **v3.2 终局合成与抗幻觉架构重构**（2026-03-19）
- **报告生成逆向思维法**：颠覆了流程式生成的刻板印象，将 `01_overview` 移至分析大循环的最后一环执行。Agent 现在会携带前置技术章与历史章（02–10）的全量上下文，以前所未有的上帝视角凝练出最终的项目概览与完成度评价，并通过首字母编排算法自动归位至报告首发位置。
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

#### 🆕 **v2.7/v2.6 全链路监控防断连优化**（2026-03-01）
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
├── os_agent_d_describe.py          # Agent D：OS 源码深度描述（10 个 LLM 阶段 + 仓库准备/RAG 预索引）
├── check_env.py                    # 环境检查脚本（含依赖预检与 LSP 自动安装）
├── test_api.py                     # LLM API 连通性快速测试
├── force_download_jina.py          # Jina 嵌入模型强制下载脚本
├── verify_jina.py                  # Jina 嵌入模型验证脚本
├── requirements.txt                # Python 依赖
├── CHANGELOG.md                    # 变更日志
├── .env                            # 环境变量配置（需自行创建）
├── .env.example                    # 环境变量配置模板
├── core/
│   ├── agent_builder.py            # LLM、Review Prompt、Task ReAct Agent 构建器
│   ├── code_rag.py                 # 代码 RAG 引擎（AST 解析 + 向量索引）
│   ├── utils.py                    # 公共工具函数（格式化、仓库名解析）
│   ├── error_handling.py           # 错误处理模块（分类、重试、追踪）
│   ├── per_types.py                # v4.0：StageState / PlanSpec 等核心数据结构
│   ├── per_planner.py              # v4.0：plan 阶段、repo_profile、dynamic_context
│   ├── per_llm_stages.py           # v4.0：LLM 规划 Agent（Plan JSON 解析与合并）
│   └── hf_env.py                   # Hugging Face 默认镜像、嵌入模型加载
├── tools/
│   ├── lsp_ops.py                  # LSP 封装（callHierarchy、定义、引用、大纲）
│   ├── file_ops.py                 # 文件操作（read_code_segment、grep_in_repo）
│   ├── git_ops.py                  # Git 操作（历史分析、作者贡献、Diff 透视）
│   ├── describe_ops.py             # 描述模块专用工具
│   └── web_search.py               # v4.0：受限外部背景搜索（默认关闭）
├── repos/                          # 克隆的 OS 仓库（运行时自动克隆，.gitignore 忽略）
├── output/                         # 描述模块输出（按项目名划分）
│   └── <os-name>/
│       ├── sections/               # 各章节分段报告
│       ├── _per_stage/             # v4.0：侧车（repo_profile、各阶段 *_plan.json）
│       ├── OS技术分析报告_<os-name>.md
│       └── describe_error_report.json  # 错误报告（如有）
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

`evidence_index` 仅在内存中用于任务执行与证据整理，**不**写入 `_per_stage`。

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
| `read_code_segment` | 最大 100,000 字符 | 只能访问 `repos/`、`output/` 目录 |
| `grep_in_repo` | 最多 20 条匹配 | 在源码中搜索关键词/正则，验证技术声明 |
| `list_repo_structure` | 默认 4 层深度 | 可通过 `max_depth` 调整 |
| `lsp_get_definition` / `lsp_get_references` | 本地化跨文件追踪 | 不受文件切片截断影响，提供 AST 真实函数映射与依赖拓扑 |
| `lsp_get_document_outline` | 文件大纲提取 | 快速获取文件中所有函数/结构体/枚举的名称与行号 |
| `analyze_git_history` | 每页最多 50-100 条 | 支持 `skip` 分页检索和 `path_filter` 目录定点钻取，提供文件级改动详情以供 LLM 判定边界 |
| `trace_file_evolution` | 单一文件演进链 | 利用底层的 `git log --follow` 抽离核心文件的所有重构记录，无视历史变迁和重命名 |
| `analyze_authors_contribution` | 最大遍历 2000 个提交 | 洞察 Repo 开发模式（单人闭门造车还是社区分包机制），并统计作者的核心贡献目录 |
| `get_commit_diff_summary` | 硬截断 20000 字符 | 透视极度模糊的 Commit 留言，去除干扰注释和空行，向 LLM 呈现最原生核心的功能大修逻辑 |
| **阶段隔离限制** | 严格白名单 | LLM 将只能在对应 Stage 获取特定工具（如 14 阶段才给 Git 工具） |

### 并发与共享状态策略

系统只让用户调 stage/task 两级并发。只有在工具存在共享状态或共享输出路径时，才做固定的底层保护：

- **LSP tool 级固定串行**：`react_lsp` task 不再整段占用 LSP 锁；只有实际调用 `lsp_get_definition`、`lsp_get_references`、`lsp_get_document_outline`、`lsp_get_call_graph`、`lsp_set_target_arch` 时才进入 `lsp_tool_guard()`。LSP tool concurrency 固定为 `1`，因为底层共享 `_lsp_loop`、`_gateway`、`LSPClient`、`opened_uris`、`pending_requests`、polyfill 文件和 `.os_agent_lsp_target`；`lsp_set_target_arch` 还会重启语言服务器。
- **仓库级 LSP 配置保护**：保护 `compile_flags.txt`、`Cargo.toml`、`src/lib.rs`、`.os_agent_lsp_target` 的生成与切换，避免同仓库并行 polyfill 或切架构时互相覆盖。
- **RAG 查询与 embedding 固定串行**：`rag_search_code` 进入 `rag_tool_guard()`，RAG query / embedding concurrency 固定为 `1`，避免多个 Task Agent 同时打同一个本地 `SentenceTransformer.encode()`。
- **项目级 RAG 索引锁**：保护 `output/<proj>/_vector_db/chunks.json` 与 `vectors.npy` 的构建和落盘，避免同项目被重复建索引或写坏索引文件。
- **仓库级 clone 锁**：只串行同一个 `repos/<name>` 目录的克隆，其他仓库仍可并行。
- **目标路径写锁**：`write_file()` 与 `convert_md_to_pdf()` 仅在写入同一路径时串行，避免覆盖。
- **普通只读工具不受影响**：源码读取、grep、受限 `web_search` 等不因上述保护被整体串行化。

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

**v4.1** 可结合 `_agent_state/`、`_per_stage/*_plan.json`、`evidence_store.jsonl`、`draft_answer_store.jsonl`、`features/*.json`、`feature_graph.json` 与 `repo_profile.json` 对照各章任务、证据、feature 和 review/fix 过程；章节正文以 `sections/*.md` 为准。

**Describe JSON-QA 生成**：02~09 题单阶段由 Task Agents 收集候选证据，系统生成并校验 `EvidenceRecord`，Stage Assembler 逐题生成 `_per_stage/<stage_id>_answers.json` 并渲染章节 Markdown。`tri_state_impl` 只能输出 `implemented / stub / not_found / unknown`；RAG/grep 不能单独支撑 `implemented`，负向搜索覆盖不足会降级为 `unknown` 或触发补证据 task。旧串行链路的整章 JSON repair 侧车已删除。

**Describe 无工具 Review（可选）**：`DESCRIBE_STAGE_REVIEW=1` 时，仅对 **JSON-QA 且校验成功** 的阶段在落盘前送审：材料为 **`core/describe_stage_qa` 题单 + feature schema** + **`coerce_answers_payload_by_stage_qa` 覆写题面前的答案 JSON**（证据以答案 JSON 内 `evidence` 为准）。`01_overview`、`10_history` 不审。结果 `_per_stage/<stage_id>_review.json`：细粒度规则见系统提示**详细分档（0.95+ 为优秀，<0.80 为证据单薄，<0.50 为严重问题）**；后处理会写入 **`report_quality_score`（0~1，完全由 LLM 逐题置信度与维度分合成，摒弃纯代码统计）**、**`_meta.quality`**，并按**方案 A** 重算全阶段 **`confidence`（与各题 `confidence` 一致）**；另含逐题 `question_reviews[]`、`summary_zh` 等。默认可选 `DESCRIBE_REVIEW_MODEL`。合并总报告时，会在 **`output/<os-name>/review_score.json`** 汇总 **02~09 题库各章**（8 个 `stage_id`）的 0~100 分与 **总分校验（有分章的算术平均）**，并在最终报告文首写引用行；若各章无可用 review 则写“未统计”类占位。

审阅侧车若 **JSON 解析或结构不合规**（如缺题、乱序），会按 **`DESCRIBE_REVIEW_MAX_ATTEMPTS`**（默认 `3`，最大 `8`）对同一审阅模型追加「修复重发」轮次；仍失败则写入 `*_review_error.json`。

若某章质量不符预期，优先检查 `output/<os-name>/_per_stage/` 下对应 `*_plan.json` 与 `os_agent_d_describe.py` 中该阶段 `prompt` / 执行契约。

并发保护相关的运行时保证：
- 当前锁都是**进程内锁**，不会在磁盘上遗留 `.lock` 一类文件，因此程序被终止后，下次启动不会因为旧锁残留而无法运行。
- `react_lsp` 的 LSP 并发保护是**工具级**而不是 task 级：LLM 思考、RAG、grep、read 代码不会占用 LSP 槽位，只有具体 LSP 工具调用会进入固定串行队列。
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
