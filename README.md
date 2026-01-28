# OS-Agent

🤖 **OS 仓库自动分析与技术报告生成工具**

基于 LLM Agent 的操作系统项目自动分析工具，能够深入分析 OS 仓库的代码结构、技术栈、内核实现，并生成专业的技术分析报告。

---

## 📋 功能特性

### 1. 自动分析 (`main.py`)

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

### 2. 报告评估 (`evaluate.py`)

使用 Agent 将自动生成的报告与仓库内人类撰写的文档进行对比评估：

- **5 维度评分**: 覆盖度、准确性、技术深度、结构、证据引用
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

创建 `.env` 文件：

```env
# API 配置
OPENAI_API_KEY=your_api_key_here
OPENAI_API_BASE=https://api.openai.com/v1

# 模型配置（可选，默认 deepseek/deepseek-v3.2）
MODEL_NAME=deepseek/deepseek-v3.2

# 仓库 URL（可选，也可在命令行指定）
REPO_URL=https://github.com/example/os-project.git
```

### 3. 运行分析

```bash
# 直接运行（使用 .env 中的 REPO_URL）
python main.py

# 或指定仓库 URL
export REPO_URL="https://github.com/example/os-project.git"
python main.py
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

## 📊 评估报告（evaluate.py）

### 功能说明

评估程序使用 Agent 模式自主探索仓库，查找人类撰写的文档（README、设计文档、docs/ 目录等），与 Agent 生成的报告进行深度对比。

**特点**：
- 🔍 Agent 自主选择要读取的文档
- 🔒 安全限制：只能访问仓库目录和 output 目录
- 📊 5 维度评分体系
- ✨ 自动发现 Agent 报告的亮点和不足

### 使用方法

```bash
# 基本用法
python evaluate.py <agent_report> <repo_path>

# 示例：评估 my-os 项目的报告
python evaluate.py output/my-os/report.md repos/my-os

# 指定输出路径
python evaluate.py output/my-os/report.md repos/my-os -o my_evaluation.md

# 使用不同的 LLM 模型
python evaluate.py output/my-os/report.md repos/my-os --model gpt-4o
```

### 命令行参数

| 参数 | 说明 |
|------|------|
| `agent_report` | Agent 生成的报告文件路径 |
| `repo_path` | 仓库本地路径 |
| `-o, --output` | 评估报告输出路径（可选，默认为同目录的 `evaluation.md`） |
| `--model` | LLM 模型名称（默认: `deepseek/deepseek-v3.2`） |

### 评估维度

| 维度 | 说明 |
|------|------|
| **coverage** | 内容覆盖度 - Agent 覆盖了人类文档多少关键技术点 |
| **accuracy** | 准确性 - Agent 描述与人类文档/代码是否一致 |
| **depth** | 技术深度 - 是否深入到代码实现层面 |
| **structure** | 结构完整性 - 报告结构是否清晰、完整 |
| **citations** | 证据引用 - 是否引用具体文件路径、代码片段 |

### 输出文件

- `evaluation.md` - 评估报告（Markdown 格式）
- `evaluation.json` - 评估数据（JSON 格式，方便程序处理）

### 示例输出

```
============================================================
🔍 OS 分析报告评估程序（Agent 模式）
============================================================

📁 仓库路径: C:\...\repos\my-os
📄 Agent 报告: C:\...\output\my-os\report.md

🤖 初始化评估 Agent (model: deepseek/deepseek-v3.2)

⏳ 正在运行评估 Agent...
----------------------------------------
   🔧 list_directory(my-os)
   🔧 find_documents(my-os)
   🔧 read_file(report.md)
   🔧 read_file(README.md)
   🔧 read_file(设计文档.md)
   📝 Agent 输出: {"overall_score": 85, ...
----------------------------------------
   完成，共 12 步

============================================================
🎯 综合评分: 85/100
============================================================

📊 分维度评分:
   coverage: 90
   accuracy: 85
   depth: 88
   structure: 82
   citations: 80

✨ Agent 亮点 (3 项):
   • Agent 提供了详细的内存管理分析，包括具体的 FrameAllocator 实现...
   • Agent 分析了 syscall 分发机制，引用了具体的代码路径...
   • Agent 生成了模块开发时间线图表，这是人类文档没有的...

⚠️  缺失内容 (2 项):
   • 人类文档提到的 USB 驱动支持未被 Agent 覆盖...
   • 设计文档中的性能测试结果未被 Agent 提及...

📄 评估报告已保存: output/my-os/evaluation.md
📄 评估数据已保存: output/my-os/evaluation.json
```

---

## 📁 项目结构

```
OS-Agent/
├── main.py              # 主分析程序
├── evaluate.py          # 报告评估程序
├── score_describe.py    # 简单相似度评分（旧版）
├── api_test.py          # API 测试工具
├── requirements.txt     # Python 依赖
├── .env                 # 环境变量配置
├── core/
│   └── agent_builder.py # Agent 构建器
├── tools/
│   ├── file_ops.py      # 文件操作工具
│   ├── git_ops.py       # Git 操作工具
│   └── describe_ops.py  # 分析描述工具
├── repos/               # 克隆的 OS 仓库
└── output/              # 输出目录（按项目名划分）
    └── <os-name>/
        ├── sections/    # 分段报告
        ├── charts/      # 图表
        ├── report.md    # 完整报告
        ├── evaluation.md    # 评估报告
        └── evaluation.json  # 评估数据
```

---

## ⚙️ 配置说明

### 支持的 LLM 模型

程序使用 OpenAI 兼容的 API，支持：
- DeepSeek: `deepseek/deepseek-v3.2`（默认）
- OpenAI: `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo`
- 其他 OpenAI 兼容的模型

### 自定义分析阶段

可以在 `main.py` 的 `STAGES` 列表中添加或修改分析阶段。每个阶段包含：
- `id`: 阶段 ID
- `title`: 阶段标题
- `prompt`: 分析提示词
- `skip_in_report`: 是否跳过写入最终报告

---

## 🔧 常见问题

### Q: 分析过程中断怎么办？

程序支持断点续传。已完成的章节会保存在 `output/<os-name>/sections/` 目录，重新运行时会自动跳过已完成的部分。

### Q: 如何评估已有的报告？

使用 `evaluate.py` 直接评估：

```bash
python evaluate.py output/my-os/report.md repos/my-os
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
