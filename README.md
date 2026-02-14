# OS-Agent

🤖 **OS 仓库自动分析与技术报告生成工具**

基于 LLM Agent 的操作系统项目自动分析工具，能够深入分析 OS 仓库的代码结构、技术栈、内核实现，并生成专业的技术分析报告。

---

## 📋 功能特性

### 1. 自动分析 (`os_agent_d.py`)

对 OS 仓库进行 **16 阶段**的深度技术分析：

| 阶段 | 内容 |
|------|------|
| 00 | 仓库准备（克隆） |
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

### 2. 报告评估 (`evaluate.py`) ✨ **增强版**

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
  - 捏造加重扣分（12→18 分/处）
  - PDF 大文档分页阅读指令
  - 输出前自检清单

- **📄 报告增强**
  - 各章节维度评分汇总表格
  - 自动生成改进建议
  - 标记最需改进的章节

#### 核心特性

- **5 维度评分**: 覆盖度、准确性、技术深度、引用规范、亮点发现
- **源码验证**: 冲突时以源码为准，使用工具验证技术声明
- **开发历史集成**: 集成了 Git 历史验证工具（*注：第 14 章历史验证默认跳过*）
- **亮点分析**: 发现 Agent 比人类文档更详细的地方
- **缺失分析**: 发现 Agent 遗漏的重要内容
- **安全限制**: Agent 只能访问指定的仓库和输出目录

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

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

### 3. 运行分析

```bash
# 直接运行（使用 .env 中的配置）
python os_agent_d.py
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

## 📊 评估报告（evaluate.py）✨ **增强版 v2.0**

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
python evaluate.py

# 指定仓库 URL
python evaluate.py --repo-url https://gitlab.educg.net/xxx/os-project.git

# 指定仓库路径和输出目录
python evaluate.py --repo-path repos/my-os --output-dir output/my-os

# 使用不同的 LLM 模型
python evaluate.py --model gpt-4o
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
   章节总数: 15
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
      - 总章节数: 15
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
├── os_agent_d.py          # OS描述/分析程序 (OS-Agent-D)
├── evaluate.py            # 报告评估程序 (v2.1)
├── requirements.txt       # Python 依赖
├── .env                   # 环境变量配置（需自行创建）
├── .env.example           # 环境变量配置模板
├── core/
│   └── agent_builder.py   # Agent 构建器（含 grep_in_repo 工具）
├── docs/                  # 文档目录
│   └── markdown_format_guide.md # Markdown 格式指南
├── tools/
│   ├── file_ops.py        # 文件操作工具（read_code_segment, grep_in_repo）
│   ├── git_ops.py         # Git 操作与图表生成
│   ├── describe_ops.py    # 仓库分析工具（描述模块专用）
│   └── eval_ops.py        # 评估专用工具（人类文档搜索、声明验证）
├── repos/                 # 克隆的 OS 仓库
├── output/                # 描述模块输出（按项目名划分）
│   └── <os-name>/
│       ├── sections/      # 分段报告
│       ├── charts/        # 图表
│       └── report.md      # 完整报告
└── evaluation/            # 评估模块输出（按项目名划分）
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

可以在 `os_agent_d.py` 的 `STAGES` 列表中添加或修改分析阶段。每个阶段包含：
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
| `analyze_code_architecture` | 最多 20 个文件 | 每文件最多显示 10 个结构体/函数 |
| `get_dev_history_by_module` | 最多 200 条提交 | 每模块最多显示 20 条 |

**截断提示**：所有工具在输出被截断时会明确告知 LLM，例如：
```
📊 统计: 分析了 20 个文件，共 45 个结构体，128 个函数
⚠️ [文件数限制] 只分析了前 20/35 个文件
⚠️ [显示限制] 还有 12 个结构体和 56 个函数未显示
```

## 🔧 常见问题

### Q: 分析过程中断怎么办？

程序支持断点续传。已完成的章节会保存在 `output/<os-name>/sections/` 目录，重新运行时会自动跳过已完成的部分。

### Q: 如何评估已有的报告？

使用 `evaluate.py` 直接评估：

```bash
# 使用 .env 中的 REPO_URL
python evaluate.py

# 或指定仓库 URL
python evaluate.py --repo-url https://gitlab.educg.net/xxx/os-project.git
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
