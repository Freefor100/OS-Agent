# OS-Agent

## 项目信息

- 赛事：2026 全国大学生计算机系统能力大赛-操作系统设计赛
- 赛道：OS 功能挑战赛道
- 项目：proj18 · 面向小型操作系统的分析比对智能体系统设计

## 这是什么

OS-Agent 是一套以 **Claude Code Skill + MCP** 形式运行的内核作品查重和差异评审系统。

- 本地程序负责 Git 版本锁定、代码范围校验、指纹、1-vs-N 搜索、函数匹配、Evidence 校验、完整性校验和 HTML 渲染。
- Claude Code 负责阅读源码和文档，判断外部依赖、参考作品、实现度、原创度与关键差异。

它不是“运行一个 Python 脚本就自动得到评委结论”。脚本提供可复现的事实底座；Agent 完成完整框架评审后，程序才允许渲染最终报告。

最终生成两份职责独立的报告：

```text
report.json      → report.html       面向评委的完整框架评审
provenance.json  → provenance.html   面向技术复核的函数溯源附录
```

## 快速开始

下面以分析 `oskernel2023-zmz` 为例。所有命令都在 OS-Agent 项目根目录执行。

### 1. 安装 Python 依赖

推荐使用名为 `os_agent` 的 Conda 环境，项目 MCP 启动脚本会自动寻找它：

```bash
conda create -n os_agent python=3.11
conda activate os_agent
pip install -r requirements.txt
```

也可以使用其他环境，但需要在启动 Claude Code 前指定解释器：

```bash
export OS_AGENT_PYTHON=/absolute/path/to/python
```

如果项目根目录存在 `.venv/` 或 `venv/`，MCP 启动脚本也会优先使用其中的 Python。Claude Code 通过 MCP 使用 OS-Agent 时不依赖系统存在 `python` 命令；手动运行 CLI 命令前需要激活对应环境，或显式使用该环境中的 Python。

### 2. 准备作品和候选语料库

将每个 Git 仓库分别 clone 到 `repos/`，并保留 `.git`：

```text
repos/
├── oskernel2023-zmz/   本次待分析作品
├── xv6-k210/           候选参考作品
├── ...
└── 其他竞赛作品/
```

首次使用或语料库发生变化后，预建候选指纹：

```bash
conda run -n os_agent python scripts/run.py --build
```

指纹和内部 Git 源码快照写入 `.fp_cache/`，不会修改 `repos/` 中的作品仓库。
默认只构建每个仓库当前检出分支；确实需要预建其他分支尖端时使用 `--all-branches`。该选项不会遍历历史 commit。

### 3. 启动 Claude Code 和 MCP

在 OS-Agent 项目根目录启动 Claude Code。项目级 [.mcp.json](.mcp.json) 会通过 [scripts/start_mcp.sh](scripts/start_mcp.sh) 启动 `os-agent` MCP。

首次进入项目时：

1. 批准项目级 MCP 配置。
2. 在 Claude Code 中执行 `/mcp`，确认 `os-agent` 已连接。
3. 如果修改过 `mcp_server.py`、`.mcp.json` 或启动脚本，重新连接 MCP 或重启 Claude Code。

找不到环境时可单独检查启动脚本：

```bash
timeout 3 scripts/start_mcp.sh
```

正常情况下服务会持续运行并被 `timeout` 结束；若立即退出，会打印缺少环境或依赖的原因。

### 4. 发起一次完整分析

Claude Code 自动发现的唯一项目 Skill 是 [.claude/skills/os-agent/SKILL.md](.claude/skills/os-agent/SKILL.md)。它不会自动触发，必须显式执行 `/os-agent`。

推荐同时指定作品和输出目录：

```text
/os-agent

完整分析 repos/oskernel2023-zmz。
默认使用当前检出分支作为作品版本；如有明确证据表明其他分支才是最终作品，再分页检查其他分支尖端。
所有新产物写入 output/oskernel2023-zmz/audit-001/。
完成正式 1-vs-N 搜索、参考作品判断、112 节点完整评审、Evidence 校验，并渲染两份报告。
```

Agent 会先将当前分支解析并锁定为固定 commit。例如评委看到的是：

```text
oskernel2023-zmz@recover
```

程序内部锁定：

```text
recover → 837b6a9...
```

这样长时间分析期间分支移动或工作树变化不会污染结果。只有存在明确理由时，Agent 才分页检查其他分支尖端；不会遍历整个 Git 历史。

### 5. 查看结果

一次完整分析目录包含：

```text
output/oskernel2023-zmz/audit-001/
├── audit_manifest.json      本次审计的快照、产物路径和阶段状态
├── base_decision.json       程序校验通过的参考作品判断
├── report.json              Agent Claim、节点/模块评审和总体结论
├── report.html              面向评委的主报告
├── provenance.json          确定性函数溯源导出
├── provenance.html          面向技术复核的函数溯源附录
├── evidence_store.jsonl     全局共享、可验证的证据记录
├── comparison.sqlite        函数 Comparison 查询数据库
└── comparisons.jsonl        Comparison 审计导出
```

- 首先打开 `report.html`：查看总体结论、架构图、14 个模块、112 个节点、实现度、原创度与 Claim。
- 需要核对函数匹配和源码对照时，再打开 `provenance.html`。
- `report.html` 中的 Evidence 编号会跳转到底部证据卡片。Evidence 是 MCP 校验后注册的记录，不是 Agent 自行填写的源码文本。

只有 `judge_report_validate` 验证全部节点、模块、Claim 和 Evidence 后，程序才允许生成最终主报告。

## 版本与分析范围

### 默认分析哪个版本

默认版本是仓库当前检出分支的尖端提交，也就是 clone 后通常看到的作品最新状态：

```text
作品@当前分支 → 固定 commit
```

`repo_snapshots` 默认只返回这个版本，避免将大量分支信息塞入 Agent 上下文。需要检查其他分支时，Agent 分页读取其他唯一分支尖端。多个分支名指向同一 commit 时只分析一次。

OS-Agent 不分析未提交工作树。即使 `repos/<作品>/` 中存在本地修改，指纹、搜索、LSP、Comparison 和 Evidence 都读取选定 commit 的内部源码快照。

### 外部依赖如何排除

程序不维护预设外部依赖名单。Agent 阅读 `.gitmodules`、Cargo workspace、Makefile、README 和目录结构后提交 `ScopeManifest`；程序验证路径和 submodule 声明。

正式 1-vs-N 搜索必须同时使用作品与候选各自验证过的 ScopeManifest。排除范围确定前的搜索只能用于内部粗召回，不能进入参考作品判断或报告排名。
除自动识别的 `.gitmodules` 子模块外，verified ScopeManifest 中的排除项必须引用已注册并验证的 EvidenceRecord；没有证据的范围建议只能作为 draft。

## Agent 实际执行流程

Claude Code 的完整约束见 [.claude/skills/os-agent/SKILL.md](.claude/skills/os-agent/SKILL.md)：

1. **选择作品版本并锁定**：默认使用 clone 当前检出分支尖端；报告展示 `作品@分支`，程序锁定 commit。
2. **创建审计清单**：`audit_manifest.json` 固定输出目录、证据库、Comparison、双报告和 BaseDecision 路径。
3. **审核代码范围**：Agent 识别学生代码、外部依赖、生成物和文档；程序验证 ScopeManifest。
4. **粗召回与正式重排**：粗搜索只发现候选；审核 Top-K 候选范围后，执行双侧排除的正式 1-vs-N 排名。
5. **选择参考作品**：Agent 综合声明、年份、正式排名和差异解释能力判断；程序执行准入校验并写入 `base_decision.json`。
6. **建立 Comparison 数据库**：程序完整保存函数匹配事实；Agent 从概要、热点、目录、文件到函数逐层查询，不一次加载全部函数。
7. **完整框架评审**：Agent 按依赖顺序覆盖 112 个节点，编写 Claim、实现度、原创度、模块关键链路和总体结论。
8. **校验并生成双报告**：先导出/渲染 `provenance` 技术附录，再在完整性校验通过后渲染 `report.html`。

声明是强线索但不会自动成为参考作品；同届高相似候选进入人工复审区，不能作为有方向性的继承来源。

## LSP 与文档支持

关键调用链优先使用 LSP 语义确认。未安装对应语言服务器时，工具会降级到 tree-sitter、语言感知搜索或汇编解析，并在结果中标记 fallback/confidence：

- C/C++：`clangd`
- Rust：`rust-analyzer`
- Go：`gopls`
- Zig：`zls`

跨架构 C/C++ 项目建议安装对应裸机交叉编译器，例如 `riscv64-unknown-elf-gcc`。LSP 在内部 commit 源码快照中临时生成受管理的 `compile_flags.txt`，clangd 结束、MCP 退出或下次启动前会自动清除，不写入作品工作树。

PDF 和 DOCX 文档证据分别通过 `pypdf` 与 `python-docx` 读取。Agent 必须调用 `evidence_document` 注册后才能在 Claim 中引用；单纯读过文档不等于形成 Evidence。

## Claude Code 开发态与产品态

- **开发 OS-Agent 本身**：正常向 Claude Code 提出代码修改、测试或评审请求。`/os-agent` 不会自动触发；项目 MCP 即使连接，也只是可选工具。
- **使用 OS-Agent 分析作品**：显式执行 `/os-agent` 并指定作品和输出目录，Skill 会要求执行完整 MCP 审计流程。
- **临时不启动 MCP**：可在本机 `/mcp` 中禁用 `os-agent`，或使用被 Git 忽略的 `.claude/settings.local.json`。此时不能做 MCP 集成测试或作品审计。
- **首次克隆 OS-Agent**：Claude Code 会要求批准项目级 `.mcp.json`，批准后才会启动本地 stdio MCP。

Git 跟踪边界：

- 跟踪：`.claude/skills/os-agent/SKILL.md`、`.mcp.json`、`scripts/start_mcp.sh`、MCP/模型/渲染代码和测试。
- 不跟踪：`.claude/settings.local.json`、`repos/`、`output/`、`.fp_cache/` 和个人权限配置。

## 常见问题

### 为什么运行 `scripts/run.py <作品>` 没有直接生成最终报告？

它只准备确定性数据和候选搜索输入。最终报告需要 Agent 阅读源码、提交 Claim，并通过完整性与 Evidence 校验。

### 为什么报告展示分支名，内部又保存 commit？

`作品@分支` 方便人理解；commit 用来保证一次长流程始终分析同一版本。分支移动不会改变已经锁定的结果。

### 为什么看不到未提交修改？

这是审计约束。正式分析只读取 Git commit，避免本地修改、生成文件或工具临时文件污染结果。需要分析新状态时，请先在作品仓库提交它。

### MCP 无法连接怎么办？

1. 确认 `OS_AGENT_PYTHON` 指向的解释器、项目 `.venv/`，或 conda 环境 `os_agent` 中已经安装 `requirements.txt`。
2. 执行 `conda run -n os_agent python -c "import mcp, tree_sitter, pypdf, docx"` 或使用你的实际解释器检查依赖。
3. 执行 `timeout 3 scripts/start_mcp.sh` 检查启动脚本。
4. 在 Claude Code 中执行 `/mcp`，重新连接或重新批准 `os-agent`。
5. 修改 MCP 服务代码后重启 Claude Code，避免旧进程继续提供旧工具定义。

## 关键 MCP 工具

| 工具 | 做什么 |
|---|---|
| `repo_snapshots` | 返回默认检出分支尖端；需要时分页返回其他唯一分支尖端，并按 commit 合并别名 |
| `audit_manifest_create` | 固定本次审计的标准产物路径和阶段状态 |
| `build_fingerprint` | 从锁定 commit 构建 token、AST 与调用邻居指纹 |
| `create_scope_manifest` / `search_formal` | 校验双侧代码范围并执行正式搜索 |
| `base_evidence_packet` / `base_decision_submit` | 组装参考作品判断证据、执行程序准入并固化 BaseDecision |
| `compare_functions` / `comparison_*` | 建立并分层查询函数 Comparison 数据库 |
| `code_atlas_overview` / `code_atlas_search` | 少量全局结构候选与入口定位；不直接作为调用链证据 |
| `lsp_definition` / `lsp_references` / `lsp_call_graph` | 对锁定 commit 做关键符号和调用链语义确认 |
| `evidence_*` / `negative_search` | 注册源码、文档、调用链、正式搜索与负向搜索证据 |
| `node_analysis_packet` / `node_review_bundle_submit` | 获取节点分析包并原子写回 Claim 与 NodeReview |
| `judge_report_status` / `judge_report_validate` / `judge_report_render` | 检查完整框架覆盖并生成评委主报告 |
| `provenance_export` / `provenance_render` | 生成独立函数级技术溯源附录 |

## 项目结构

```text
OS-Agent/
├── README.md
├── DESIGN.md
├── mcp_server.py
├── .mcp.json
├── .claude/skills/os-agent/
│   └── SKILL.md             唯一的 Claude Code 审计工作流
├── scripts/                 确定性计算与报告渲染
├── tools/                   CodeAtlas、LSP 和文档读取工具
├── core/                    快照、Scope、Comparison、Evidence 和报告模型
├── repos/                   作品与候选语料库，Git 忽略
├── .fp_cache/               指纹与内部源码快照，Git 忽略
└── output/                  分析产物，Git 忽略
```

更详细的数据模型和职责边界见 [DESIGN.md](DESIGN.md)。
