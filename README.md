# OS-Agent

## 参赛信息

- 赛事：2026 全国大学生计算机系统能力大赛-操作系统设计赛
- 赛道：OS 功能挑战赛道
- 项目：proj18 · 面向小型操作系统的分析比对智能体系统设计
- 队伍名称：OS照妖镜
- 队员：刘建博（kkkboxbili@qq.com）、李佳峻
- 学校：华中科技大学

## 这是什么

OS-Agent 是一套以 **Claude Code Skill + MCP** 形式运行的内核作品查重和差异评审系统。

- 本地程序负责 Git 版本锁定、代码范围校验、Git blob 与 AST shape 指纹、1-vs-N 搜索、函数匹配、关键证据锚定、完整性校验和 HTML 渲染。
- Claude Code 负责阅读源码和文档，判断外部依赖、参考作品、实现度、原创度与关键差异。

它不是“运行一个 Python 脚本就自动得到评委结论”。脚本提供可复现的事实底座；Agent 完成完整框架评审后，程序才允许渲染最终报告。

最终生成两份职责独立的报告：

```text
report.json      → report.html       面向评委的中文完整框架评审
provenance.json  → provenance.html   面向技术复核的函数溯源附录
```

## 快速开始

下面以分析 `oskernel2023-zmz` 为例。所有命令都在 OS-Agent 项目根目录执行。

### 0. 安装 Claude Code / 配置 DeepSeek API

OS-Agent 通过 Claude Code 调用项目 Skill 和 MCP。推荐在 Linux 或 WSL 中运行；不建议使用原生 Windows 环境，路径、shell、Git 和本地 MCP 进程管理更容易出现兼容性问题。若本机还没有 Claude Code，在 Linux/WSL 中执行：

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

也可以使用 npm 安装方式：

```bash
npm install -g @anthropic-ai/claude-code
```

安装后确认命令可用：

```bash
claude --version
```

OS-Agent 的一次完整评审可能消耗 `60M+` tokens，建议使用 DeepSeek API 作为 Claude Code 后端；在长流程、多 Agent、重复读取证据的场景下，缓存命中率通常可达 `97%`-`98%`。先到 [DeepSeek Platform](https://platform.deepseek.com/) 创建 API Key，再把环境变量写入当前 shell 的启动文件。bash 用户写入 `~/.bashrc`，zsh 用户写入 `~/.zshrc`：

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_API_KEY=<你的 DeepSeek API Key>
```

写入后重新打开终端，或执行 `source ~/.bashrc` / `source ~/.zshrc` 让配置立即生效。`<你的 DeepSeek API Key>` 是占位符，替换为实际 key，不要把尖括号原样输入，也不要提交到 Git。DeepSeek 的 Anthropic 兼容接口 base URL 是 `https://api.deepseek.com/anthropic`；以上配置来自 DeepSeek 的 Claude Code 接入说明。配置完成后进入项目目录启动：

```bash
cd /path/to/OS-Agent
claude
```

### 1. 安装 Python 依赖

推荐使用名为 `os_agent` 的 Conda 环境，项目 `environment.yml` 包含完整 Python 及 LSP 依赖：

```bash
conda env create -f environment.yml
conda activate os_agent
```

如果是已有环境的增量更新：

```bash
conda env update -f environment.yml
```

也可以手动创建：

```bash
conda create -n os_agent python=3.11
conda activate os_agent
pip install -r requirements.txt
```

环境创建完成后，先激活环境，再把当前解释器写入 `OS_AGENT_PYTHON`。后续命令和本地 MCP 配置都优先使用这个变量：

```bash
export OS_AGENT_PYTHON="$(command -v python)"
```

Claude Code 通过 MCP 使用 OS-Agent 时不依赖系统存在 `python` 命令；手动运行 CLI 命令前需要激活对应环境，或显式使用该环境中的 Python。

`.claude/mcp.json` 是每个人的本地 Claude Code MCP 配置，不进入 Git。仓库提供 [.claude/mcp.json.example](.claude/mcp.json.example)，首次使用时复制为 `.claude/mcp.json`：

```bash
cp .claude/mcp.json.example .claude/mcp.json
```

这个 example 保持 Claude Code 生成的直接启动格式：`command` 是 Python 解释器，`args` 第一个参数是项目里的 `mcp_server.py`。复制后把 `<python-executable>` 替换为 `OS_AGENT_PYTHON` 指向的解释器；把 `<project-root>` 替换为当前 OS-Agent 目录的绝对路径。可以用 `printf '%s\n' "$OS_AGENT_PYTHON"` 和 `pwd` 查看这两个值。个人本地路径不要提交到 Git。

跨机器迁移时，不要复用别人填好的绝对路径；先用 `environment.yml` 创建同名环境，再用 `printf '%s\n' "$OS_AGENT_PYTHON"` 和 `pwd` 得到本机路径，填入 `.claude/mcp.json`。`scripts/start_mcp.sh` 仍保留为手动诊断入口；如果你想让本地配置自动找环境，也可以只在自己的 `.claude/mcp.json` 中把 `command` 改成 `bash`、`args` 改成 `["scripts/start_mcp.sh"]`，但仓库 example 默认保持 Claude Code 生成的直接启动格式。

`scripts/start_mcp.sh` 不是 MCP 服务本体；真正的服务入口是 `mcp_server.py`。启动脚本只负责按顺序寻找可用 Python：`OS_AGENT_PYTHON`、项目 `.venv/` 或 `venv/`、常见 Conda/Mamba `os_agent` 环境，以及 PATH 中可用的 Conda/Mamba/Micromamba 环境管理器，找到后再启动 `mcp_server.py`。因此它适合排查环境或作为个人本地替代配置，但不要把它和 `mcp_server.py` 混为一谈。

### 2. 准备作品和候选语料库

将每个 Git 仓库分别 clone 到 `repos/`，并保留 `.git`：

```text
repos/
├── oskernel2023-zmz/   本次待分析作品
├── xv6-k210/           候选参考作品
├── ...
└── 其他竞赛作品/
```

首次使用或语料库发生变化后，预建候选 AST 指纹：

```bash
"$OS_AGENT_PYTHON" scripts/run.py --build
```

也可以只预建指定作品和指定分支：

```bash
"$OS_AGENT_PYTHON" scripts/run.py --build oskernel2023-zmz@main
```

预建阶段直接读取 Git commit blob，在内存中解析源码，只把 `units/fpset/meta/scopes` 等审计缓存写入 `.fp_cache/`。其中 `fpset` 是函数 AST shape hash 集合。
默认构建每个仓库的所有唯一分支尖端 commit，供后续粗召回和正式 Scope 搜索消费；多个分支指向同一 commit 时只构建一次。该流程不会遍历历史 commit。只想快速预建当前检出版本时使用 `--current-only`。

当前查重底座是 **Git blob + AST shape**：

- Git blob hash 来自 `git ls-tree -r HEAD`，用于识别逐字节完全一致的文件、框架 fork、路径搬移和同届共享文件。
- AST shape hash 由 tree-sitter 提取函数语法结构后生成，是 `search_formal` 和函数 Comparison 的核心函数级指标，可穿透函数/变量改名、注释和格式修改、拆文件与合文件。
- 报告使用 blob 与 AST 的差距解释混淆、搬移和真实工作量。

### 3. 启动 Claude Code 和 MCP

在 OS-Agent 项目根目录启动 Claude Code。本地 `.claude/mcp.json` 会用配置中的 Python 解释器启动 `mcp_server.py`。

首次进入项目时：

1. 批准本地 `.claude/mcp.json` MCP 配置。
2. 在 Claude Code 中执行 `/mcp`，确认 `os-agent` 已连接。
3. 如果修改过 `mcp_server.py`、`.claude/mcp.json` 或启动脚本，重新连接 MCP 或重启 Claude Code。

找不到环境时可单独检查启动脚本；这只验证环境发现和 `mcp_server.py` 能否启动，不代表默认 example 必须使用该脚本：

```bash
timeout 3 scripts/start_mcp.sh
```

正常情况下服务会持续运行并被 `timeout` 结束；若立即退出，会打印缺少环境或依赖的原因。

### 4. 发起一次完整分析

Claude Code 自动发现的唯一项目 Skill 是 [.claude/skills/os-agent/SKILL.md](.claude/skills/os-agent/SKILL.md)。它不会自动触发，必须显式执行 `/os-agent`。

推荐入口只有一个：

```text
/os-agent oskernel2023-zmz recover
```

Agent 会自动完成：

1. 检查 `repos/oskernel2023-zmz` 当前检出分支就是 `recover`，且工作树干净，然后锁定该分支尖端 commit。
2. 创建 `output/oskernel2023-zmz/`。
3. 校验作品代码范围，排除外部依赖和生成物。
4. 执行正式 1-vs-N 搜索并选择参考作品。
5. 建立函数 Comparison 数据库。
6. 按模块阅读代码，形成 112 节点中文评审。
7. 生成 `report.html` 和 `provenance.html`。

需要固定目录名时再显式指定：

```text
/os-agent oskernel2023-zmz recover 输出到 output/oskernel2023-zmz-custom/
```

Agent 会先将指定分支解析并锁定为固定 commit。例如评委看到的是：

```text
oskernel2023-zmz@recover
```

程序内部锁定：

```text
recover → 837b6a9...
```

这样长时间分析期间分支移动或工作树变化不会污染结果。没有用户显式指定分支时，Skill 不会继续工作。

### 5. 查看结果

一次完整分析目录包含：

```text
output/oskernel2023-zmz/
├── audit_manifest.json      本次审计的锁定版本、产物路径和阶段状态
├── base_decision.json       程序校验通过的参考作品判断
├── report.json              Agent Claim、节点/模块评审和总体结论
├── report.html              面向评委的主报告
├── provenance.json          确定性函数溯源导出
├── provenance.html          面向技术复核的函数溯源附录
├── evidence_store.jsonl     全局共享、可验证的证据记录
├── comparison.sqlite        函数 Comparison 查询数据库
└── comparisons.jsonl        Comparison 审计导出
```

- 首先打开 `report.html`：查看中文总体结论、Base 选择依据、Scope 排除过程、Agent 阅读代码后给出的架构说明、14 个模块、112 个节点、完整度、原创度与关键 Claim。
- 需要核对函数匹配和源码对照时，再打开 `provenance.html`。
- `report.html` 由 `web_report/` 的 React + Vite + TypeScript 静态前端投影 `report.json` 生成。Python 负责校验、整理 view-model、注入数据，并复制 `web_report/dist/assets/`。
- `report.html` 以中文呈现，必要机制名可用括号补充解释，例如“写时复制（copy-on-write）”。Evidence 只作为关键锚点展示在相关模块/节点页面底部，不要求普通节点堆砌证据。
- 内核架构图来自 Agent 提交的 Mermaid 图；页面只提供放大、缩小、拖拽平移和重置交互，不自动生成或改写图内容。

只有 `judge_report_validate` 验证全部节点、模块、关键 Claim、中文架构说明和产物链后，程序才允许生成最终主报告。

### 报告生成与预览

`report.html` 依赖仓库中已有的 `web_report/dist/` Vite 构建产物。正常 `/os-agent` 审计流程中，Claude Code 会在最终阶段调用 MCP `judge_report_render`，把 `report.json` 渲染成 `report.html`；用户不需要手动执行渲染脚本。

只有首次使用时本地缺少 `web_report/dist/index.html`，或你修改了 `web_report/` 前端源码后，才需要重新构建前端：

```bash
cd web_report
npm install
npm run build
```

`scripts/judge_report.py` 只是 `judge_report_render` 背后的手动离线入口；只有不通过 MCP、需要手工把某个 `report.json` 重渲染成 `report.html` 时才直接调用：

```bash
python3 scripts/judge_report.py output/oskernel2023-zmz/report.json output/oskernel2023-zmz/report.html
```

这里的 `output/oskernel2023-zmz/` 要替换为本次实际审计目录；如果看到文档或报错中的 `<report.json>`、`<report.html>`，尖括号表示占位符，不要原样输入，例如应写成 `output/某作品/report.json` 和 `output/某作品/report.html`。

渲染脚本会把 `web_report/dist/index.html` 注入当前报告数据，并把 `web_report/dist/assets/` 复制到报告输出目录。若审计目录中已经存在 `report.html`，仅查看报告时不需要重新构建前端，也不需要重新运行 `scripts/judge_report.py`。

本地预览请通过 HTTP 打开报告目录，不要直接用 `file://` 打开 Vite 产物：

```bash
cd output/<repo>
python3 -m http.server 8765 --bind 127.0.0.1
```

然后访问 `http://127.0.0.1:8765/report.html`。如果你的环境没有 `python3` 命令，可换成当前虚拟环境或 conda 环境里的 Python 解释器路径。

## 版本与分析范围

### 必须指定哪个分支

查重必须显式指定待查重分支；没有分支名时 `/os-agent` 不应继续工作。开始审计前，Agent 会用 bash 检查 `repos/<作品>/` 当前检出分支就是用户指定的分支，且 `git status --porcelain` 为空：

```text
作品@指定分支 → 固定 commit
```

确认分支和干净工作树使用普通 `git -C repos/<作品> branch --show-current` 与 `git -C repos/<作品> status --porcelain`，不需要 MCP 工具。通过后，Agent 用 `git -C repos/<作品> rev-parse HEAD` 得到固定 commit，并把这个 commit 传给后续 MCP 工具。

OS-Agent 不分析未提交工作树。指纹、搜索和 Comparison 绑定选定 commit 的预建缓存；LSP、bash 阅读和关键证据注册前，Claude Code 必须把对应 `repos/<作品>/` checkout 到锁定 commit，并保持 `git status --porcelain` 干净。Evidence 工具直接读取当前工作树，MCP 会强制校验 HEAD 等于传入 ref 且工作树干净。

### 外部依赖和范围如何排除

程序不维护预设外部依赖名单，也不只凭目录名排除 Git tracked 源码。`vendor/`、`third_party/`、`target/`、`build/`、`out/`、`dist/`、`node_modules/` 只能作为审核线索；Agent 需要阅读 `.gitmodules`、Cargo workspace、Makefile/CMake、README、源码引用关系和必要的 git history，判断这些代码是否实际参与项目、是否有声明来源、是否有学生修改痕迹，然后提交 `ScopeManifest`；程序验证路径和 submodule 声明。

正式 1-vs-N 搜索必须使用目标作品验证过的 ScopeManifest；候选缺少 ScopeManifest 时，程序使用确定性的 `auto_candidate` 轻量范围参与重排，避免要求 Agent 为 Top-K 每个候选提交 Scope 证据。排除范围确定前的 `search_similar` 只能用于内部粗召回，不能进入参考作品判断或报告排名。
除自动识别的 `.gitmodules` 子模块外，verified ScopeManifest 中的排除项必须引用已注册并验证的 EvidenceRecord；没有证据的范围建议只能作为 draft。排除依据优先引用源码/配置/文档证据；没有单一源码位置时使用 `evidence_structured(kind="scope_exclusion_decision", metadata={prefix, category, reason, basis})`。`scope_manifest` 证据只记录已创建的 Scope 清单，不作为创建前的排除依据。

## Agent 实际执行流程

Claude Code 的完整约束见 [.claude/skills/os-agent/SKILL.md](.claude/skills/os-agent/SKILL.md)：

主流程按下面顺序执行，用户不需要手动调用这些工具：

1. **启动审计**：确认用户显式指定待查重分支；用 bash 检查 `repos/<作品>/` 当前检出分支就是该分支且工作树干净，锁定作品 commit，创建独立输出目录和 `audit_manifest.json`。默认输出目录是 `output/<repo>/`，所有产物平铺在该目录下。
2. **确认范围**：Agent 判断学生代码、外部依赖、生成物和文档边界，MCP 验证 ScopeManifest。
3. **参考发现**：用目标 verified scope 和候选自动轻量 scope 做正式 1-vs-N 搜索，粗召回只作为内部候选发现。
4. **Base 固化**：Agent 选择参考来源，MCP 校验 `repo + commit + formal score` 后写入 `base_decision.json`。
5. **切换源码工作树**：`base_decision_submit` 校验通过后，Claude Code 直接使用刚刚判断出的 `target_commit` 和 `selected_base_commit`，把 `repos/<target>` 和 `repos/<base>` 强制 checkout 到对应 detached commits。`base_decision.json` 是审计记录，不是下一步重新读取的控制输入。
6. **函数事实**：用同一组 target/base commits 建立 `comparison.sqlite`，Agent 只按模块需要分页查询概要、热点、目录、文件和关键函数。
7. **模块评审**：Agent 以模块为阅读单位，覆盖 112 个节点，写中文 Claim、完整度、原创度、模块关键链路和总体结论。
8. **双报告生成**：先生成 `provenance` 技术附录，再在完整性校验通过后渲染中文 `report.html`。

声明是强线索但不会自动成为参考作品；年份方向只是强线索，不是硬门槛。同年高相似候选仍可能存在互抄、共同上游或协作传播，不能仅因同年排除。Agent 需要抽取高相似文件/函数，用 `git log --follow`、`git blame`、`git show`、`git diff` 检查双方相似片段的首次引入时间、提交形态、批量导入痕迹、文档声明和共同第三方来源线索，并在主报告中用中文说明当前更像互抄、共同外部来源、协作共享还是方向不明。如果选择同年、未知年份或不在 xlsx 的开源教学项目作为 Base，主报告必须说明方向不确定性、替代方向依据和未选其他候选的原因。
`judge_report_create` 默认不覆盖已有报告；切换 Base/Comparison 时使用 `judge_report_fork_for_comparison` 生成待重绑草稿。

报告中的中文说明字段支持两种形态：连续解释用字符串，并列机制、分阶段结论、第一/第二/第三类判断用字符串数组。渲染器只按 Agent 显式提交的数组分条展示，不会按标点、序号或句长自动拆句。建议 `module_reviews[].overview`、`implementation_summary`、`difference_summary`、`original_work_summary`、`overall_assessment.summary`、`source_relation`、`base_selection_reason`、`scope_exclusion_process`、`directory_overview` 和 `architecture_overview` 在包含多个并列点时提交数组。多来源作品不要把所有来源塞进 `BaseDecision`；`BaseDecision` 只固定主骨架参考，`source_relation` 和模块 `difference_summary/original_work_summary` 用中文数组逐条说明来源名称、关系类型、影响范围、确认程度和不确定点。`base_selection_reason` 面向评委说明为什么选中或未选中 Base；`scope_exclusion_process` 说明排除路径、证据来源、疑似第三方/生成代码是否检查过修改和实际引用。

`overall_assessment.directory_overview` 承载 Agent 对完整目录树的整体解释，`overall_assessment.directory_notes` 可按目录相对路径提供逐项说明，前端把说明紧跟在对应目录项后面，不替 Agent 编写目录解释。`overall_assessment.architecture_overview` 承载中文内核架构补充说明，展示在架构图下方。`overall_assessment.architecture_diagram` 若存在，必须是纯 Mermaid 内核架构图源码，不得混入说明段落；校验失败时 Agent 需要修改 JSON 后重新提交。页面对该图提供缩放、拖拽平移和重置交互，但不自动生成或修复图内容。`overall_assessment.architecture_edges` 用来索引 Agent 阅读代码后总结出的真实架构关系，不是固定模块摆盘图。每条边至少需要中文 `label` 和非空 `claim_ids`；端点可以用 `source/target` 或 `from/to` 写自由文字，也可以用 `from_module/to_module`、`module_ids`、`from_node/to_node`、`node_ids` 绑定结构化模块或节点。结构化引用会校验 ID，普通端点文字不会被当成模块强校验，MCP 不会替 Agent 自动绘图或拆句。

## LSP 与文档支持 (这点实际Agent不会优先采用LSP Tool来查调用链)

关键调用链优先使用 LSP 语义确认。未安装对应语言服务器时，工具会降级到 tree-sitter、语言感知搜索或汇编解析，并在结果中标记 fallback/confidence：

- C/C++：`clangd`
- Rust：`rust-analyzer`
- Go：`gopls`
- Zig：`zls`

跨架构 C/C++ 项目建议安装对应裸机交叉编译器，例如 `riscv64-unknown-elf-gcc`。LSP 使用已 checkout 到锁定 commit 的作品工作树；clangd 结束、MCP 退出或下次启动前会自动清除受管理的临时配置。

PDF 和 DOCX 文档证据分别通过 `pypdf` 与 `python-docx` 从已 checkout 的工作树读取。Evidence 主要用于 BaseDecision、Scope 排除、负向搜索、关键继承/独立结论、架构边支撑和模块置顶 Claim；普通实现说明可直接写中文分析，不必为每个节点反复注册 Evidence。

## Claude Code 开发态与产品态

- **开发 OS-Agent 本身**：正常向 Claude Code 提出代码修改或评审请求。`/os-agent` 不会自动触发；项目 MCP 即使连接，也只是可选工具。
- **使用 OS-Agent 分析作品**：显式执行 `/os-agent <作品名> <待查重分支>`，可选指定输出目录；Skill 会要求执行完整 MCP 审计流程。
- **临时不启动 MCP**：可在本机 `/mcp` 中禁用 `os-agent`，或使用被 Git 忽略的 `.claude/settings.local.json`。此时不能做 MCP 集成验证或作品审计。
- **首次克隆 OS-Agent**：先 `cp .claude/mcp.json.example .claude/mcp.json`，Claude Code 会要求批准本地 `.claude/mcp.json`，批准后才会启动 stdio MCP。

Git 跟踪边界：

- 跟踪：`.claude/skills/os-agent/SKILL.md`、`.claude/mcp.json.example`、`scripts/start_mcp.sh`、MCP/模型/渲染代码。
- 不跟踪：`.claude/mcp.json`、`.claude/settings.local.json`、`repos/`、`output/`、`.fp_cache/`、`tmp/` 和个人权限配置。

Agent 临时脚本和一次性中间文件默认不要创建；当 Claude Code 写大段 JSON 容易触发 Write tool error，或需要本地批量校验/整理草稿时，可以统一放在项目根 `tmp/`。`tmp/` 只用于生成、修复、格式化或校验待提交 JSON 草稿；最终写入仍必须通过 MCP 正式接口完成。临时脚本不得批量生成节点/模块正文，不得用模板套话填充评审内容。不要写入 `scripts/`、`core/`、`repos/`、`output/` 或系统 `/tmp`。`tmp/` 不作为 Evidence、Scope、BaseDecision、Comparison 或报告产物来源。

## 常见问题

### 为什么运行 `scripts/run.py <作品>` 没有直接生成最终报告？

它只准备确定性数据和候选搜索输入。最终报告需要 Agent 阅读源码、提交中文 Claim，并通过完整性与关键 Evidence 校验。

### 为什么报告展示分支名，内部又保存 commit？

`作品@分支` 方便人理解；commit 用来保证一次长流程始终分析同一版本。分支移动不会改变已经锁定的结果。

### 为什么看不到未提交修改？

这是审计约束。正式分析只读取 Git commit，避免本地修改、生成文件或工具临时文件污染结果。需要分析新状态时，请先在作品仓库提交它。

### MCP 无法连接怎么办？

1. 确认 `.claude/mcp.json` 的 `command` 指向的解释器已安装 `requirements.txt`，或项目 `.venv/`、conda 环境 `os_agent` 可用。
2. 执行 `"$OS_AGENT_PYTHON" -c "import mcp, tree_sitter, pypdf, docx"` 检查依赖。
3. 执行 `timeout 3 scripts/start_mcp.sh` 检查启动脚本。
4. 在 Claude Code 中执行 `/mcp`，重新连接或重新批准 `os-agent`。
5. 修改 MCP 服务代码后重启 Claude Code，避免既有进程继续提供过期工具定义。

### MCP 与子 Agent 的性能限制

OS-Agent 的 MCP 工具通过 stdio JSON-RPC 与 Claude Code 通信。这不是高性能 IPC，每次调用都要走完整的序列化/反序列化往返。以下场景性能问题尤其明显：

- **`compare_functions`**：O(N×M) 函数匹配，数万到数十万次 `_pair_score` 比对，在 MCP 中无法并行，只能单线程跑，大仓库可能需要 60 分钟以上。
- **`build_fingerprint`**：C 代码的 tree-sitter AST 解析可能因文件深度触发 Python 递归栈限制。
- **并发瓶颈**：MCP 工具在 Claude Code 主会话中运行，多个子 Agent 并行争用同一 MCP 连接会排队甚至卡死。正常 `/os-agent` 流程由主会话直接调用 MCP tool；子 Agent 应用 bash、rg、sed、git 等普通命令读代码并产出草稿，由主会话串行写入报告和证据。`scripts/run_mcp_tool.py` 只作为调试/应急的命令行单工具入口。
- **MCP 卡死**：如果 `.claude/mcp.json` 中 `command` 写的是裸 `python3`，PATH 可能解析到其他环境（如 `.venv/`），依赖不完整则 MCP 服务启动失败或超时。

**对策**：

1. `.claude/mcp.json` 默认从 `.claude/mcp.json.example` 复制，按 Claude Code 生成格式填写 Python 解释器绝对路径和 `mcp_server.py` 绝对路径，不要把个人绝对路径提交到 Git。
2. 需要检查环境自动发现时，可手动运行 `scripts/start_mcp.sh`；它会读取 `OS_AGENT_PYTHON` 并搜索 `.venv`、Conda/Mamba 环境。
3. `compare_functions`、`build_fingerprint` 这类计算密集步骤由主会话按阶段启动，避免多个 MCP 调用同时抢占同一服务进程。
4. 确需在 MCP 连接外调用单个工具时，使用 `scripts/run_mcp_tool.py <tool> '<json_args>'`。该脚本会按 `OS_AGENT_PYTHON`、项目 `.venv`、常见 Conda/Mamba `os_agent` 环境和 PATH 中的环境管理器自动寻找可用 Python，然后导入 `mcp_server.py` 并调用同名 Python 函数；它不经过 MCP/JSON-RPC，也不要把它作为常规并发方案。
5. 批量查重场景可以用多个独立 Claude Code 会话分别处理不同作品；同一审计内的子 Agent 只做阅读和草稿，不直接调用 MCP。
6. 注意清理已被 kill 的 Agent 残留子进程，避免 CPU 被孤儿 `compare_functions` 占满。

## MCP 工具推荐路径

完整分析时，Claude Code 应优先使用下面主路径工具。其他工具保留给补查、定位和故障恢复。

### 主路径工具

| 阶段 | 工具 | 做什么 |
|---|---|---|
| 启动审计 | bash `git` 检查、`audit_manifest_create`、`build_fingerprint` | 确认指定分支和干净工作树、锁定 commit、创建审计目录、准备 AST 指纹 |
| 确认范围 | `create_scope_manifest` | 固定正式搜索范围 |
| 参考发现 | `search_formal` | 执行正式 1-vs-N 搜索 |
| Base 固化 | `base_evidence_packet`、`base_decision_submit` | 组包、选择 formal 候选、写入 BaseDecision |
| 函数事实 | `compare_functions`、`comparison_overview`、`comparison_hotspots`、`comparison_*` | 建库并按需查询函数匹配事实 |
| 模块阅读 | `judge_report_create`、`module_analysis_packet` | 创建报告骨架，以模块获取节点功能范围和候选摘要 |
| 报告写入 | `node_review_bundle_submit`、`module_review_submit`、`overall_assessment_submit` | 原子写入中文节点、模块和总体评审 |
| 完成产物 | `judge_report_status`、`provenance_export`、`provenance_render`、`judge_report_validate`、`judge_report_render` | 校验完整性并生成双报告 |

### 补查与恢复工具

| 工具 | 使用边界 |
|---|---|
| `node_analysis_packet` | 只在单节点返工或模块包信息不足时使用 |
| `node_review_draft_batch` | 只生成草稿，不正式写入报告 |
| `claim_contract` | 不确定 Claim 枚举或证据要求时查看 |
| `lsp_definition` / `lsp_references` / `lsp_call_graph` | 确认关键符号、引用和调用链 |
| `evidence_*` / `negative_search` | 注册关键锚点；普通节点说明不需要反复注册 Evidence |
| `search_similar` | 临时粗召回，不能进入 BaseDecision 或报告排名 |
| `judge_report_fork_for_comparison` | 切换 Base/Comparison 时使用，避免覆盖已有报告 |

## 项目结构

```text
OS-Agent/
├── README.md
├── DESIGN.md
├── mcp_server.py
├── .claude/mcp.json.example
├── .claude/skills/os-agent/
│   └── SKILL.md             唯一的 Claude Code 审计工作流
├── scripts/                 确定性计算与报告渲染
├── web_report/              report.html 的 React 静态前端模板、样式和交互
├── tools/                   tree-sitter、LSP 和文档读取工具
├── core/                    Git commit、Scope、Comparison、Evidence 和报告模型
├── repos/                   作品与候选语料库，Git 忽略
├── .fp_cache/               AST 指纹、Scope 与审计缓存，Git 忽略
└── output/                  分析产物，Git 忽略
```

更详细的数据模型和职责边界见 [DESIGN.md](DESIGN.md)。

## AI 辅助说明

本项目在开发过程中使用 Claude Code、Codex、Cursor、Antigravity 的 AI 编程工具（模型GPT5.5、DeepSeek V4 pro、Sonnet 4.6、Gemini 3.5 Flash）辅助完成大部分代码实现、重复性工作、文档整理和流程设计讨论。AI 工具主要用于提升实现效率、生成候选方案和辅助检查，Skill的流程、经验由我起草，LLM进行结构整理，边界条件的确认。最终的职责边界、工作流设计、功能取舍、查重边界与结论确认仍由项目维护者定义。
