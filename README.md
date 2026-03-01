# OS-Agent

🤖 **OS 仓库自动分析与技术报告生成工具**

基于 LLM Agent 的操作系统项目自动分析工具，能够深入分析 OS 仓库的代码结构、技术栈、内核实现，并生成专业的技术分析报告。

---

## 📋 功能特性

### 1. 自动分析 (`os_agent_d_describe.py`) ✨ **增强版**

对 OS 仓库进行 **16 阶段**的深度技术分析，内置智能重试与错误追踪机制：

| 阶段 | 内容 |
|------|------|
| 00 | 仓库准备（本地直连克隆，无 LLM 开销） |
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
| 13 | 测试框架与验证机制 |
| 14 | 开发历史与里程碑（含图表） |
| 15 | 执行摘要与报告整合 |

### 2. 报告评估 (`os_agent_d_evaluate.py`) ✨ **增强版**

使用 Agent 将自动生成的报告与仓库内人类撰写的文档进行对比评估。

#### 🆕 **v2.0 增强功能**（2025-02-14）

- **🔄 智能重试机制**
  - 指数退避策略（2s → 4s → 8s，最大 60s）
  - 自动错误分类（网络、API、超时、解析等 7 种类型）
  - 针对性重试策略（解析错误不重试，网络错误重试）
  - 最大重试次数可配置（默认 3 次）

- **📊 完整错误追溯**
  - 详细日志记录（DEBUG 级别，包含完整堆栈）
  - 错误报告生成（`error_report.json`）
  - 失败上下文保存（步骤数、模型、参数等）
  - Markdown 错误摘要（集成到评估报告）

- **🛡️ 鲁棒性提升**
  - 输入验证（章节文件、仓库目录存在性检查）
  - 超时控制（可配置，默认 300 秒）
  - 优雅降级（单章节失败不影响整体评估）
  - 追问机制（JSON 解析失败时自动追问 Agent）
  - 资源清理（异常时自动保存中间结果）

- **📈 统计增强**
  - 成功/失败/跳过章节统计
  - 成功率计算
  - 错误类型分布统计
  - 评估耗时记录

#### 🆕 **v2.1 评估精度提升**（2025-02-14）

- **🔍 描述模块增强**
  - 新增 `grep_in_repo` 源码搜索工具，减少捏造
  - 系统 prompt 增加反捏造要求和覆盖度检查
  - 低分章节（安全、网络、测试、文件系统）prompt 增加针对性搜索指引

- **📊 评估 prompt 强化**
  - 强制验证：所有声明必须标注验证状态
  - 捏造加重扣分（幻觉 -20 分/处，细节捏造 -25 分/处）
  - PDF 大文档分页阅读指令
  - 输出前自检清单

- **📄 报告增强**
  - 各章节维度评分汇总表格
  - 自动生成改进建议
  - 标记最需改进的章节
  
#### 🆕 **v2.2 深度与真实性增强**（2025-02-15）

- **🛡️ 严格反幻觉机制**
  - **证据为王**：所有技术结论必须基于代码实现，严禁根据文档“画饼”进行推断。
  - **强制验证**：对关键特性（如 CoW、零拷贝）必须使用 `grep` 或 `verify_claim_in_source` 验证代码存在性。
  - **调用链追踪**：要求 Agent 对核心机制（如 `fork`, `page fault`）进行完整的函数调用链分析，而非仅列出函数名。

- **📉 科学评分体系**
  - **覆盖率 (Coverage)**：区分“文档提及”与“代码实现”。
  - **准确性 (Accuracy)**：对“幻觉”（即源码中不存在的功能）实施重罚（-20分/处）。
  - **深度 (Depth)**：奖励对代码调用链的完整追踪分析。

#### 🆕 **v2.3 评估提示词增强与流程优化**（2026-02-20）

- **🛡️ 严格审查与桩代码检测**
  - **预防幻觉**：要求 Agent 严格检查 `unimplemented!()`, `todo!()`, `ENOSYS` 等桩代码，并标注为“桩函数”或“未实现”。
  - **深度真实性验证**：强制代码验证 FPU 初始化、模式切换、完整系统调用及 IPC（真实队列/缓冲区）逻辑。
  - **路径合法性验证**：在引用文件路径前，**必须**确保该文件真实存在。

- **🚀 本地执行缓存与直连克隆优化**
  - **加速分析流程**：重构了 `00_repo_prep` 仓库准备逻辑，现在通过底层 Python 原生 Git 模块直接完成直连克隆，**完全剥离 LLM 参与**。当环境本地已存在目标分析仓库时直接跳过克隆，彻底消除了每次运行初期的无效几十亿参数大模型请求开销和时延。

#### 🆕 **v2.4 语言服务器原生整合**（2026-02-20）

- **🧠 原生 AST 智能解析体系**
  - **LSP 多路复用**：引入 `clangd` / `rust-analyzer` / `gopls` 等原生语言服务器，彻底告别正则文本扫描带来的信息残缺（幻觉断层）。
  - **自动 Polyfill**：当环境缺乏 `compile_commands.json` 或 `Cargo.toml` 时，支持基于编译头文件特征的动态挂载，自动补全底层 AST 依赖库环境。
  - **汇编自动降级**：对 `.s`, `.asm` 的汇编代码以及发生超时的 LSP 查询默认实施正则解析（ASMLexicalParser）降级保护机制。
  - **全链路替换分析网关**：全面下线 `analyze_code_architecture` 工具，重构其底层的调用分析体系，彻底释放由于其低匹配精确性造成的评测分偏低问题。

#### 🆕 **v2.5 评估驱动的提示词精修 + 环境完善**（2026-02-21）

- **🔬 Round 1: 评估反馈驱动的 Stage Prompt 修正**
  - 基于 13 章评估结果的 6 类共性问题，针对性修改了 6 个 stage prompt
  - 内存管理新增 brk/sbrk、用户指针安全、进程级映射管理
  - 中断系统调用要求精确统计 TrapFrame 字节数，新增接口/实现分离模式
  - 文件系统新增具体 FS 抽象层、文件打开调用链、路径精确性约束
  - 同步 IPC 新增信号作为 IPC、Futex 跨文件调用链
  - 安全机制强制多架构覆盖；测试框架要求精确计数

- **🔬 Round 2: 评分 86.8 后的定向优化**（基于完整评估跑分结果）
  - §01 概览：强制搜索 arceos 子模块（解决漏检 Lazy Allocation/CFS 问题）
  - §02 启动：新增 SBI→U-Boot→OS 固件级启动链 + MMU 前后串口地址切换
  - §03 内存：新增 B树 shm 优化 + rmap 反向映射表检查
  - §04 进程：新增 PGID/SID 层次 ID 规则 + 16 种 POSIX 资源限制
  - §05 中断：新增 CoW/Lazy↔缺页关联 + 信号三粒度 + SIGSEGV + 跳板代码
  - §07 驱动：新增 MMU 前后串口地址切换
  - §08 同步：新增信号处理时机（Trap 返回前）
  - §09 多核：新增跨章节交叉引用（解决 18%→94.7% 的覆盖率问题）
  - §11 网络：新增功能限制声明要求
  - §13 测试：强化 CI/CD 检测（.github/workflows 解决方案）
  - SYSTEM_PROMPT：新增子模块探索规则（Rule 11）
  - 评估 prompt：新增章节边界评分规则

- **📝 评估术语规范**
  - 评估 prompt 新增术语约定，明确区分【人类文档】与【生成报告】
  - `accuracy.errors.desc` 必须标明问题归属

- **🧰 新增 `lsp_get_document_outline` 工具**
  - 基于 `textDocument/documentSymbol`，快速获取文件内所有函数/结构体/枚举的名称与行号
  - 已注册到描述 Agent 和评估 Agent

- **🔧 LSP 环境配置**
  - 安装 clangd v21.1.8、rust-analyzer v0.3.2795、gopls v0.21.1
  - 修复 `lsp_ops.py` 中 `builtins.open` 引用错误
  - **新增 `_resolve_lsp_binary` 路径探测**：Conda 环境下自动搜索 `~/.cargo/bin/`、`~/AppData/Local/` 等常见安装位置

#### 🆕 **v2.6 代码架构重构 + 描述模块鲁棒性增强**（2026-03-01）

- **♻️ 公共模块抽取**
  - **新增 `core/utils.py`**：从 `os_agent_d_describe.py` 和 `os_agent_d_evaluate.py` 提取重复的工具格式化函数（`format_tool_call_summary`、`format_tool_result_summary`、`repo_name_from_url`），合并为超集版本
  - **新增 `core/error_handling.py`**：从 `os_agent_d_evaluate.py` 提取错误处理体系（`ErrorType`、`RetryConfig`、`classify_error`、`calculate_backoff`、`ErrorTracker`），供两个模块共享
  - 净减少约 87 行重复代码，确保错误处理和格式化逻辑的单一来源

- **🔄 描述模块（`os_agent_d_describe.py`）智能重试**
  - 新增 **指数退避重试机制**（与评估模块一致）：每阶段最多重试 3 次，退避时间 2s→4s→8s
  - 新增 **`ErrorTracker` 错误追踪**：记录所有阶段执行中的错误，运行结束生成 `describe_error_report.json`
  - 错误自动分类（网络/API/超时/解析/工具/未知），解析错误不做无意义重试
  - 用户中断（Ctrl+C）时自动保存已记录的错误报告
  - 运行结束输出错误摘要统计

- **🛡️ Git 克隆鲁棒性增强**
  - `clone_repository` 新增 Windows NTFS 非法字符（如冒号 `:`）容错
  - 克隆失败时自动设置 `core.protectNTFS=false` 并强制 checkout
  - 空目录检测：避免对空目录误判为已存在仓库

- **🧠 LSP 稳定性大幅提升**
  - `rust-analyzer` **自动安装**：当 `rustup component` 缺少时自动执行 `rustup component add rust-analyzer`
  - `Cargo.toml` 自动修复：当 manifest 缺少 target 文件（`src/lib.rs`、`src/main.rs`）时自动创建空占位文件
  - 新增 `disable_build_scripts` 选项：通过环境变量禁用 build scripts，减少 `FetchWorkspaceError`
  - stderr 读取循环独立管理，防止 LSP 进程死锁
  - `_resolve_lsp_binary` 支持 `cwd` 参数，优先在项目 toolchain 中查找

- **🔧 其他修复**
  - `agent_builder.py`：修复历史阶段工具匹配条件（`13_history` → `_history`），确保阶段 ID 变化后仍能正确加载 Git 历史工具

#### 核心特性

- **5 维度评分**: 覆盖度、准确性、技术深度、引用规范、亮点发现
- **源码验证**: 冲突时以源码为准，使用工具验证技术声明
- **开发历史集成**: 集成了 Git 历史验证工具（*注：第 14 章历史验证默认跳过*）
- **亮点分析**: 发现 Agent 比人类文档更详细的地方
- **缺失分析**: 发现 Agent 遗漏的重要内容
- **安全限制**: Agent 只能访问指定的仓库和输出目录

---

## 🚀 快速开始

### 1. 自动环境配置（推荐）

本项目依赖多种底层分析工具（如 `rust-analyzer`, `clangd` 等）。我们提供了全自动的依赖安装脚本：

**Windows (PowerShell):**
```powershell
.\setup_env.ps1
```

**Linux / macOS:**
```bash
chmod +x setup_env.sh
./setup_env.sh
```

*(如果脚本因网络原因失败，可参考脚本内容手动安装所需依赖。我们推荐使用 Conda 隔离 Python 环境：`conda create -n os_agent python=3.10`)*

如果不使用 conda，也可以直接安装：

```bash
pip install -r requirements.txt
```

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
> | Windows | `~/.cargo/bin/`, `~/AppData/Local/{name}/`, `~/scoop/shims/` |
> | macOS | `~/.cargo/bin/`, `/opt/homebrew/bin/`, `/usr/local/bin/` |
> | Linux | `~/.cargo/bin/`, `/usr/bin/`, `~/.local/bin/`, `/snap/bin/` |
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
    ├── charts/            # 生成的图表
    │   ├── commits_monthly.png
    │   ├── modules_activity.png
    │   └── modules_timeline.png
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

## 📁 项目结构

```
OS-Agent/
├── os_agent_d_describe.py          # OS描述/分析程序（含智能重试与错误追踪）
├── os_agent_d_evaluate.py          # 报告评估程序 (v2.6)
├── requirements.txt                # Python 依赖
├── .env                            # 环境变量配置（需自行创建）
├── .env.example                    # 环境变量配置模板
├── core/
│   ├── agent_builder.py            # Agent 构建器（含 LSP 工具、grep_in_repo 等）
│   ├── utils.py                    # 🆕 公共工具函数（格式化、仓库名解析）
│   └── error_handling.py           # 🆕 错误处理模块（分类、重试、追踪）
├── docs/                           # 文档目录
│   └── markdown_format_guide.md    # Markdown 格式指南
├── tools/
│   ├── file_ops.py                 # 文件操作工具（read_code_segment, grep_in_repo）
│   ├── git_ops.py                  # Git 操作与图表生成
│   ├── lsp_ops.py                  # 语言服务器协议(LSP)封装，AST解析
│   ├── describe_ops.py             # 仓库分析工具（描述模块专用）
│   └── eval_ops.py                 # 评估专用工具（人类文档搜索、声明验证）
├── repos/                          # 克隆的 OS 仓库
├── output/                         # 描述模块输出（按项目名划分）
│   └── <os-name>/
│       ├── sections/               # 分段报告
│       ├── charts/                 # 图表
│       ├── report.md               # 完整报告
│       └── describe_error_report.json  # 🆕 错误报告（如有错误）
└── evaluation/                     # 评估模块输出（按项目名划分）
    └── <os-name>/
        ├── evaluation.log          # 详细日志
        ├── error_report.json       # 错误报告
        ├── summary.json            # 汇总结果
        ├── evaluation_report.md    # Markdown 报告（含维度表格与改进建议）
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
| `get_dev_history_by_module` | 最多 200 条提交 | 每模块最多显示 20 条 |

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

## 📄 许可证

MIT License

---

## 🙏 致谢

- [LangChain](https://langchain.com/) - LLM 应用框架
- [LangGraph](https://langchain-ai.github.io/langgraph/) - Agent 编排框架
