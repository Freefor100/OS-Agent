# OS-Agent

> 面向小型操作系统的分析比对智能体系统
> 全国大学生计算机系统能力大赛 · proj18

读一份操作系统内核仓库，产出一棵可视化的"内核设计树"；用这棵树和其他内核做结构比对、查重和谱系分析。

> **新方向（确定性查重流水线）**：项目正从"为每个内核填描述树"转向"以代码指纹查重为主、LLM 只解读差异"。
> 完整设计、验证数据与实现状态见 [DESIGN.md](DESIGN.md)。新流水线的用法见下方[「查重流水线」](#查重流水线确定性零-llm)一节。

---

## 它解决什么问题

评审操作系统比赛作品时，每个参赛内核少则两三万行、多则十几万行代码。人工读代码判断"这个内核的内存管理用了什么策略、调度器是什么算法、和另一个内核有多少相似"既费时又难以标准化。

OS-Agent 的做法：

1. **Agent D** 逐模块读源码，把每个设计决策归结为一条有源码证据的"Claim"，最终拼成一棵固定结构的"内核设计树"，生成可在浏览器查看的静态页面。
2. **Agent C** 拿多棵设计树做横向比对——哪些机制是两个内核都有的、哪些是一个有另一个没有、哪些代码结构高度相似——输出相似度分和差异报告。

---

## 快速开始

### 环境准备

Python 3.10+，建议用 conda 或 venv 隔离环境。

```bash
pip install -r requirements.txt
```

复制配置模板，填入 API 信息：

```bash
cp .env.example .env
# 编辑 .env，至少填写：
# OPENAI_API_KEY=...
# OPENAI_API_BASE=...
# MODEL_NAME=...
```

支持任何 OpenAI 兼容接口，例如 DeepSeek、OpenRouter、本地 vLLM 等。

### 分析一个内核仓库（Agent D）

```bash
# 最简用法：分析本地仓库
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv

# 同时打开浏览器实时进度页面
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv --ui

# 直接从 Git URL 克隆并分析
python agent_d.py https://github.com/mit-pdos/xv6-riscv --repo-name xv6-riscv

# 完成后直接启动 HTTP 服务预览结果
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv --serve
```

运行结束后在浏览器打开 `output/xv6-riscv/_agent_d/index.html` 查看设计树。

### 比对两个内核（Agent C）

```bash
# 把 xv6-k210 和 xv6-riscv 做比对（两者都需要先跑过 Agent D）
python agent_c.py xv6-k210 xv6-riscv
```

Agent C 只读取 `output/<name>/_agent_d/` 下的产物，不再读源码。

---

## 输出文件说明

每次 Agent D 跑完，在 `output/<repo-name>/_agent_d/` 下生成：

| 文件 | 说明 |
|------|------|
| `index.html` | 可直接浏览器打开的内核设计树展示页 |
| `kernel_design_tree.json` | 设计树原始数据 |
| `compare_index.json` | Agent C 比对时用的多层指纹索引 |
| `evidence_store.jsonl` | 每条结论对应的源码证据（路径、行号、代码片段） |
| `judge_view.json` | 评审页面数据源 |
| `run_dashboard.html` | 运行进度实时页面（`--ui` 时自动打开） |
| `run_manifest.json` | 运行指纹、状态、断点恢复标记 |
| `llm_usage.json` | token 消耗和耗时统计 |

---

## 断点续跑

运行中途中断（网络抖动、手动 Ctrl+C）后直接重新执行同一条命令，会从上次完成的节点继续，不会重复分析已经完成的部分：

```bash
# 直接重跑，自动续
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv

# 强制从头开始（丢弃已有进度）
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv --fresh
```

判断"是否复用"的依据是源码内容 + 词表 + 模型配置的哈希，任何一项变了就视为新任务。

---

## 设计树结构

每棵内核设计树的骨架是固定的（定义在 `core/kernel_tree.py`），覆盖从启动到网络的所有主要子系统：

```
KernelProject
├── 构建与配置       (BuildAndConfig)
├── 架构与启动       (ArchitectureLayer)
├── 进程管理         (ProcessManagement)
├── 内存管理         (MemoryManagement)
├── 文件系统         (FileSystem)
├── 设备驱动         (DeviceDriver)
├── 网络             (Network)
├── 同步机制         (Synchronization)
├── 用户库与测试     (UserLibAndTests)
├── 内核服务         (KernelServices)
├── 安全与隔离       (SecurityAndIsolation)
├── 调试与可观测性   (ObservabilityAndDebug)
├── 虚拟化           (Virtualization)
└── 演进历史         (EvolutionHistory)
```

每个叶子节点分析完成后给出：

- **状态**：已实现 / 部分实现 / 未实现 / 未知
- **成熟度**：教学级 / 精简实现 / 生产级
- **Claim 列表**：每条 Claim 标注机制名、中英文描述，并链接到具体的源码证据
- **关键符号**：函数名、结构体、宏定义及其文件位置

---

## 运行参数

**Agent D：**

```
python agent_d.py <仓库路径或URL> [选项]

  --repo-name NAME     仓库显示名称（默认取目录名）
  --output-root DIR    产物根目录（默认 output/）
  --fresh              强制新运行，忽略已有进度
  --ui                 在浏览器打开实时进度页面
  --serve              完成后启动 HTTP 服务查看结果
  --no-tui             关闭终端进度界面，改用行式日志
  --quiet              只输出最终 JSON 结果，适合脚本调用
  --port PORT          HTTP 服务端口（默认 8765）
```

**Agent C：**

```
python agent_c.py <目标内核名> [参考内核名 ...]

  目标内核名和参考内核名对应 output/ 下的目录名
  例如: python agent_c.py xv6-k210 xv6-riscv arceos
```

---

## 环境变量

常用配置项（完整列表见 `.env.example`）：

```env
# 必填
OPENAI_API_KEY=sk-...
OPENAI_API_BASE=https://api.openai.com/v1
MODEL_NAME=deepseek/deepseek-chat

# 输出目录（默认 output/）
AGENT_OUTPUT_ROOT=output

# 并发控制（默认值通常够用）
AGENT_D_NODE_CONCURRENCY=1       # 同时分析几个树节点
AGENT_D_LLM_CONCURRENCY=2        # 同时发出几个模型请求
AGENT_D_REACT_MAX_STEPS=40       # 每个节点最多执行几步工具调用

# 开启模型推理过程（对推理模型效果更好）
AGENT_D_THINKING=enabled
AGENT_D_REASONING_EFFORT=high

# 显存受限时限制内存用量（默认关闭）
# AGENT_D_MEMORY_SOFT_LIMIT_GB=8
```

---

## 项目结构

```
agent_d.py              Agent D 入口
agent_c.py              Agent C 入口
core/
  agent_d_graph.py      LangGraph 全局调度图
  node_react_agent.py   每个节点的工具调用循环
  node_analysis_graph.py 节点级子图（ReAct → 校验 → 修复）
  kernel_tree.py        设计树骨架定义 + 候选机制词表
  kernel_glossary.py    机制词典加载（含 C/Rust 识别样例）
  kernel_glossary.json  334 条机制定义（中英文 + 代码示例）
  evidence.py           源码证据存储与查询
  publish.py            HTML 页面渲染
  submission_meta.py    参赛信息匹配（从 collected-data.xlsx 读取）
  code_atlas/           代码结构静态索引
  llm/                  模型调用封装
tools/
  git_ops.py            Git 历史分析（按模块聚合，避免巨型 diff）
  lsp_ops.py            LSP 符号定义/引用/调用图查询
  file_ops.py           源码读取
  build_config_ops.py   构建配置解析
  code_atlas/           AST 解析（tree-sitter）
scripts/
  run_describe.py       agent_d.py 的兼容入口
  run_compare.py        agent_c.py 的兼容入口
  build_corpus.py       批量入库脚本
  backfill_glossary.py  为已有产物补充概念定义
tests/                  单元测试
repos/                  本地源码仓库（不提交到 git）
output/                 运行产物（不提交到 git）
collected-data.xlsx     参赛作品信息表（队伍/学校/仓库地址）
```

---

## 查重流水线（确定性，零 LLM）

新方向的核心是一条确定性流水线：用归一化 token 指纹做查重，把每个函数归到「外部依赖 / 框架底座 / 移植自前代 / 自研」四类，再组装成评委可读的报告。**前四个阶段完全不用 LLM**，LLM 只在最后解读差异（设计与验证数据见 [DESIGN.md](DESIGN.md)）。

```bash
# 阶段0：为 repos/ 下所有作品建代码指纹（首次 ~8 分钟，缓存到 .fp_cache/，复跑秒级）
# 同时需要大赛 fork 的 ArceOS 作为版本正确的框架基准：
git clone https://github.com/oscomp/arceos.git repos/_baseline_oscomp-arceos

# 阶段1：全库血缘分流 → 18 个跨届家族 + 孤儿 + 同届互抄候选
python scripts/lineage_idf.py            # 产出 output/lineage_clusters.json

# 阶段2-4：单个作品的出身分类 + 报告（自动判范式、自动选框架基准、自动取同簇 peers）
python scripts/run.py <作品目录名>        # 例: python scripts/run.py T202510216995249-4014

# 全库批量：为每个作品生成报告，并产出全库总览
python scripts/run.py --all              # 产出 output/_overview/index.html

# 全库查重总览（家族谱系 / 孤儿榜 / 同届复审重点）
python scripts/overview.py
```

产物：
- `output/<作品>/_report/index.html` — 单作品报告：贡献占比、三色架构图、声明核查、自研函数清单。
- `output/_overview/index.html` — 全库总览：18 个家族谱系、原创候选、同届互抄复审重点。

辅助验证脚本：`scripts/fp_validate.py`（指纹判别力）、`scripts/attribute.py`（函数级溯源 + LLM work-list）、`scripts/provenance.py`（四分类，可单独跑）。

---

## 注意事项

**LSP 支持（可选）**

安装 `clangd`（C/C++ 项目）或 `rust-analyzer`（Rust 项目）后，Agent D 会自动调用 LSP 获取更精准的符号定义和调用关系。没有 LSP 时退化到静态搜索，结果仍然可用。

**深度 clone vs 浅层 clone**

`--depth=1` clone 的仓库缺少完整 git 历史，`EvolutionHistory` 节点的演进分析会退化。如果需要演进历史，clone 时去掉 `--depth` 参数。

**token 消耗**

分析一个中等规模内核（约 2 万行）全量跑完大约消耗 200k–800k tokens，取决于模型和内核复杂度。建议先用 `AGENT_D_NODE_LIMIT=3` 跑 3 个节点验证配置，确认无误再全量跑。

```bash
AGENT_D_NODE_LIMIT=3 python agent_d.py repos/xv6-riscv --repo-name xv6-riscv
```

---

## 参赛信息

- 赛事：2026 全国大学生计算机系统能力大赛（操作系统赛）
- 项目：proj18 · 面向小型操作系统的分析比对智能体系统设计
- 参赛作品信息从 `collected-data.xlsx` 中读取，自动显示在结果页顶部
- 教学原型仓库（xv6、rCore、ArceOS 等）单独标注，不显示队伍信息
