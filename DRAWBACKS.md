# OS-Agent 架构缺陷与改进方案

这份文档记录 OS-Agent 在审计约 140 份报告后暴露出的架构缺陷，以及下一步改进方向。核心结论很明确：当前问题不是单点 bug，而是 **JSON schema 脆弱性、Agent 执行不可靠、MCP/Claude Code 基础设施限制** 三层互相放大。

老实说，自研 Multi-Agent 不是好选择。这个项目是竞赛作品，不是商业化 Agent 平台；自研通用 Agent 的工程量和维护成本会远远超过收益。Claude Code / MCP 体系虽然粗糙，但它免费、有上下文窗口、能读代码、能调用本地工具。换 OpenCode 或其他框架，解决不了“Agent 写报告敷衍、灌水、模板化”的本质问题。

改进方向不是“再造一个 Agent”，而是：

1. 用固定模板和阶段化流程沉淀方法论，减少 prompt 缩水和流程跳步。
2. 用确定性证据工厂预计算事实，减少 Agent 自己乱找证据。
3. 用 Markdown 替代复杂 JSON 报告，让 Agent 输出回到 LLM 原生擅长的格式。
4. 用轻量工作流强制阶段顺序和质量门禁，而不是让 Agent 自主决定做什么。

## 一、当前架构全貌

```text
输入: repos/<作品>.git + 2026_entries.json
  ↓
MCP Server (stdio JSON-RPC, 单进程)
  ├── build_fingerprint (tree-sitter AST)
  ├── search_formal (1-vs-N 搜索)
  ├── compare_functions (O(N×M) 函数匹配)
  ├── node_review_bundle_submit (原子写入)
  └── judge_report_render (渲染)
  ↓
Claude Code (主 Agent, 对话控制)
  ├── 手动部署 sub-agent (非强制, 经常不开)
  ├── prompt 手动编写 (每次都缩水)
  └── 自主决定流程顺序 (容易跳步)
  ↓
产物 (多文件、多层嵌套、schema 脆弱、互相牵连)
  ├── report.json           (15+ 顶层键, 嵌套 5 层, 200-300KB, enum 敏感)
  ├── base_decision.json    (与 report 重复)
  ├── evidence_store.jsonl  (被 claim 引用但单独存)
  ├── provenance.json       (评委基本不看)
  └── comparison.sqlite     (函数 match 查询库)
  ↓
validator (6 处以上容错补丁, enum 白名单, 迭代加入)
  ├── require_complete=True → False
  ├── IMPLEMENTATION_LEVELS: complete → full
  ├── ORIGINALITY_LEVELS: independent → novel
  ├── work/reference 字符串容错
  ├── key_chains 字符串容错
  └── evidence_store 超长路径跳过
  ↓
renderer (三层映射)
  ├── Python: json → view_model
  ├── Python: view_model → inject into dist/index.html
  └── React: view_model → 像素
  ↓
frontend (React)
  └── 一个 level 值不认就可能显示空白
```

核心矛盾：

| 层 | 问题 | 结果 |
|---|---|---|
| 数据层 | JSON + enum + 深层嵌套 | Agent 被诱导填空，字段一错就连锁失败 |
| 校验层 | 字段拼错整个报告渲染失败 | 修一个错误往往要加一个容错补丁 |
| 渲染层 | json → view_model → HTML → React 映射复杂 | 前端不认新字段或新枚举就显示空白 |
| Agent 层 | 主 Agent 自主决策开不开 sub-agent | 同样方法论，不同 Agent 执行质量天差地别 |
| MCP 层 | sub-agent 不能共用 MCP，并发排队 | 读不了 comparison 数据，只能读源文件或写临时 Python |
| 流程层 | 没有强制工作流 | Agent 可能先写结论、后补证据，甚至漏验证 |

## 二、问题分层

### 1. JSON Schema 脆弱性（技术层）

| 问题 | 表现 | 后果 |
|---|---|---|
| enum 脆弱 | `complete` / `full`、`independent` / `novel` 这种枚举写错 | 一个 enum 写错，全报告渲染失败或局部显示空白 |
| 顶层字段过多 | `report.json` 有 15+ 顶层键，核心内容和技术字段混在一起 | Agent 不知道哪些字段该认真写，哪些只是技术元数据 |
| 数据分散 | report / evidence / base_decision / provenance 四类文件互相引用 | 判断链被拆散，排错时要跨文件追踪 |
| 字段冗余 | report 写 reference，base_decision 又写一遍 | 同一事实多处维护，容易不一致 |
| 增加标签成本高 | 加一个 tag 要改 validator + renderer + frontend 三处 | 小需求变成三层联动修改 |
| 长文本不适配 | summary 5000 字塞进一个 JSON 字符串 | HTML 一个 `<p>` 展示，阅读体验差 |
| 对象误渲染 | source_relation 是对象数组，前端处理不完整时显示 `[object Object]` | 技术结构泄漏到评委界面 |

JSON 本身不是错，问题是让 LLM 直接生产 200-300KB、15+ 顶层键、深层嵌套、强 enum 约束的报告。它像考试填表，字段名本身会诱导 Agent 偷懒：

```json
{
  "overview": "该节点实现完整",
  "difference_from_reference": "与基座一致",
  "implementation_degree": {"level": "complete", "rationale": "实现完整"}
}
```

字段名已经暗示了“这里写概述”“这里写差异”“这里写理由”，Agent 很容易机械填空。最后 112 个节点变成“该功能继承自 XXX”“该节点未实现”这类模板句。

### 2. Agent 不可靠性（执行层）

| 问题 | 表现 | 根因 |
|---|---|---|
| 子 Agent 不听话 | 让它开 14 个 sub-agent 分析模块，实际只开 2-3 个，剩下自己硬写 | Claude Code 的 sub-agent 是建议性的，不是强制的 |
| 注意力衰减 | 前 3 个模块写得详细，后面全部模板化 | LLM 处理长任务的自然衰减 |
| prompt 缩水 | 第一次 prompt 有完整模板，第三次只剩几行 | 靠人手动复制，没有固化机制 |
| 对话和报告不一致 | 跟人对话时头头是道，写出来的 report 灌水、模板、乱编 | 对话分析和结构化写入是两种任务 |
| 同方法不同结果 | 同样的方法论，不同 Agent 执行质量天差地别 | 缺少强制流程和中间门禁 |
| sub-agent 读不了 comparison | sub-agent 没有 MCP，只能读源文件，或者用 Python 写 JSON | Claude Code/MCP 工具边界限制 |
| MCP 并发卡死 | 多个 sub-agent 抢 MCP，排队甚至死锁 | stdio JSON-RPC 单连接不适合高并发 |

最典型的问题是：Agent 在聊天里可以分析得很像样，但写入 `report.json` 时会回到“字段填空”。这不是某一次 prompt 没写好，而是 JSON 报告结构、长任务注意力衰减、无强制工作流共同导致的。

### 3. MCP / Claude Code 基础设施限制

| 问题 | 表现 | 影响 |
|---|---|---|
| MCP 并发瓶颈 | 多个 sub-agent 同时调用同一 MCP，排队或卡死 | 不能把 14 模块评审真正并行化 |
| sub-agent 无 MCP | sub-agent 读不了 comparison.sqlite 的 MCP 查询结果 | 只能靠源文件阅读，缺少函数级溯源事实 |
| 校验在末尾 | 写完报告 → 渲染 → 发现错误 → 返工 | 一次失败可能返工 4-5 轮 |
| 阶段不可追溯 | 不知道 Agent 哪一步用了什么证据得出什么结论 | 复盘困难，也难以定位灌水从哪里开始 |

MCP 适合做确定性工具入口，不适合作为多个子 Agent 高频争用的并发总线。正常流程应该是主会话串行调用 MCP，子 Agent 只读预计算证据和源码片段，输出 Markdown 草稿。

## 三、两层恶性循环

当前架构的问题会自我放大：

```text
JSON 太复杂
  → Agent 更容易写错
  → 增加校验逻辑和容错分支
  → JSON schema 更复杂
  → Agent 更不敢自由组织内容，只能模板填空
```

```text
渲染难看
  → 加前端组件和 view_model 映射
  → 映射逻辑更多
  → 新字段、新枚举、新对象更容易丢失或显示空白
  → 再加 validator / renderer 补丁
```

这就是 JSON、validator、renderer、frontend 的恶性循环。它不断把问题从“报告内容质量”转移成“字段和映射修补”，但真正的根因没有解决：Agent 被复杂 schema 诱导成填表机器。

## 四、Markdown 替代 JSON 的理由

LLM 天生擅长 Markdown。Markdown 是它们主要训练格式之一，而 JSON 是它们被逼着学的严格结构化格式。Claude/GPT 写 Markdown 流畅自然，写大型 JSON 像考试，越复杂越容易错。

### JSON vs Markdown

| 问题 | JSON | Markdown |
|---|---|---|
| Agent 灌水 | 有框架，字段名暗示内容，容易偷懒填空 | 无固定深层框架，需要自己组织内容，更容易写真实分析 |
| 格式错误 | enum 拼错可能全报告报错 | 拼错就是一个字，不影响整体渲染 |
| 渲染 | 需要 validator + renderer + frontend 复杂映射 | `markdown-it` 一行即可渲染主体内容 |
| 评委阅读 | 通常必须开 HTML 或专用前端 | VSCode / GitHub / GitLab 可直接预览 |
| 增加字段 | 改 validator + renderer + frontend | 加个标题或段落即可 |
| Mermaid 图 | 单独字段，容易丢失或被转义 | ```mermaid 代码块自然嵌入 |
| 版本控制 | 140KB JSON diff 基本读不了 | Markdown diff 一目了然 |
| 长文本 | 一个字符串，HTML 不换行 | 自然段落、列表、标题 |

### 输出形态对比

JSON 模式：

```json
{
  "node_id": "ArchitectureLayer.Boot",
  "overview": "该节点实现完整",
  "difference_from_reference": "与基座一致",
  "implementation_degree": {"level": "complete", "rationale": "实现完整"}
}
```

Agent 被逼着填空，但字段名本身已经告诉它“这里要写概述”“这里要写差异”。最后经常得到 112 个节点的模板套话。

Markdown 模式：

```markdown
### ArchitectureLayer.Boot

实现度: 完整
原创度: 主体继承，局部适配

启动流程由 `entry.S` 汇编入口开始，经过 `start.c` 完成硬件初始化。
目标作品保留了 xv6-riscv 的 `mepc` 设置逻辑，但在中断入口和页表切换处增加了
LoongArch CSR 适配。新增部分主要集中在 `arch/loongarch/trap.rs` 和
`mm/address.rs`，属于面向目标平台的适配工作，不应计为全新启动子系统。
```

Markdown 强迫 Agent 组织自然段、引用文件和解释判断。它更接近“写评审意见”，而不是“填 schema 表格”。

评委看 Markdown 也比看生成 HTML 更直接。VSCode、GitHub、GitLab 原生支持 Markdown 预览，目录树可以自动生成，Mermaid 图可以直接嵌入 ` ```mermaid` 代码块，Git diff 也能追踪每次报告修改。

## 五、目标架构

### 核心设计原则

1. **确定性工作流**：不让 Agent 自己决定做什么、怎么做、做多少。
2. **LLM 原生输出格式**：使用 Markdown，不让 Agent 直接维护大型 JSON。
3. **证据预计算**：Agent 只负责根据证据写判断，不负责从零找证据。
4. **自适应粒度**：报告篇幅和模块深度与项目复杂度匹配。
5. **单文件主报告**：减少 report / evidence / base_decision / provenance 的分裂。
6. **阶段质量门禁**：每个阶段先验收，再进入下一阶段。

### 目标架构图

```text
输入: repos/<作品>.git + 2026_entries.json
                       ↓
  ┌──────────────────────────────┐
  │  证据工厂 (确定性计算)         │
  │  - blob hash 三方对比         │
  │  - AST fingerprint 函数匹配   │
  │  - git timeline + commit 分析 │
  │  - 基座声明提取 + 交叉验证     │
  │  - AI agent 配置扫描          │
  │  - 作弊/刷分模式检测           │
  └──────────────────────────────┘
                       ↓ (证据文件, 100-200 行, 纯数据)
  ┌──────────────────────────────┐
  │  工作流固化层                  │
  │                              │
  │  Stage 1: 基座检测            │ ← prompt: base_detect.tmpl
  │  Stage 2: AI + 作弊分析       │ ← prompt: ai_detect.tmpl
  │  Stage 3: 模块评审            │ ← prompt: module.tmpl × N
  │  Stage 4: 摘要 + 架构 + 关系   │ ← prompt: summary.tmpl
  │  Stage 5: 质量验证             │ ← 不合格打回
  │                              │
  │  特性:                        │
  │  - prompt 从模板文件读取       │
  │  - 每阶段必须完成才能推进       │
  │  - 子任务只读证据和源码片段     │
  │  - MCP 调用由主会话串行执行     │
  └──────────────────────────────┘
                       ↓ (每阶段输出 Markdown 片段)
  ┌──────────────────────────────┐
  │  组装 + 发布                   │
  │  - report.md (单文件, 5-50KB) │
  │  - tags.yaml (一行 = 一个作品) │
  │  - index.html (读 tags, 搜索)  │
  └──────────────────────────────┘
```

## 六、阶段设计

### Stage 1: 基座检测

```text
输入: blob 对比结果 + AST 对比结果 + 选手自述提取
输出: base_detection.md (50-100 行)
内容: 基座是谁、声明是否一致、框架继承比例、是否存在同届异常相似
```

### Stage 2: AI + 作弊分析

```text
输入: git log + commit 分析 + AI 配置文件扫描 + 测试代码扫描
输出: ai_and_cheat.md (30-60 行)
内容: AI 参与度判断、隐匿 AI 证据、作弊/刷分检测、工作量判断
```

### Stage 3: 模块评审

```text
输入: 分模块源文件列表 + 对应 comparison 数据摘要
执行: N 个 claude --print 任务，每个负责 2-3 个模块
输出: module_*.md 片段
关键: N 由 evidence 工厂动态决定，不固定 14。极简内核可能只有 5 个片段
```

子任务不要直接抢 MCP。它们读取预计算证据、源码片段和 comparison 摘要；主会话负责串行调用 MCP 写入或校验。

### Stage 4: 摘要 + 架构 + 关系

```text
输入: Stage 1-3 的所有输出 + 原始证据
输出: summary.md (100-200 行)
内容: 作品整体评价、架构图 (Mermaid)、工作量分层、风险、source_relation
```

### Stage 5: 质量验证

检查项：

- 每个模块片段是否有足够信息量，过短视为灌水。
- 是否引用具体文件名、函数名、结构体、syscall 或配置项。
- 是否有具体代码规模、修改范围或 comparison 事实。
- originality 是否区分 framework / external_dep / adapted / novel。
- 是否出现大面积“该功能继承自 XXX”“该节点未实现”模板文字。
- 是否存在文档宣称和代码证据不一致却未说明。
- 是否遗漏 Base、Scope、AI、作弊、同届传播、外部依赖等核心风险。

不通过就打回对应 Stage，而不是等最终 HTML 渲染时才发现问题。

## 七、输出格式简化

### 主报告

```text
report.md
```

单文件承载评委真正要看的内容：基座、真实工作量、来源关系、模块评审、AI/作弊风险、架构图、关键证据。

### 标签索引

```yaml
# tags.yaml - 每作品一行，结构化但极简
T2026104869910787-1379:
  school: 武汉大学
  team: 缺页队
  tags: [同届抄袭, 声明不实]
  base: T202610213999887-1415 (哈工大菜鸟队)
  blob_match: 99.2%
  ai: Gemini CLI(隐匿)
  cheat: 无
  summary: 从同届菜鸟队复制代码, 首 commit 99.2% 匹配, 15 天时间差
```

旧 index.html 读取 `report.json`，再提取 team/school/tags。新 index.html 只读 `tags.yaml`，负责搜索和过滤，不再理解完整报告结构。

## 八、原创工作判定标准

| 修改类型 | 例子 | 是否算原创 |
|---|---|---|
| 路径/配置/版本适配 | `Cargo.toml` 改路径、链接脚本改地址 | 不算 |
| bugfix/兼容补丁 | 加 `CONSOLE_LOCK` 13 行、修类型转换 | 不算，标注为 adapted |
| 重命名/拆文件 | `pulse_core` → `oskernel_core`、拆大文件 | 不算，属于混淆或重组 |
| vendored crate 修改 | 改依赖路径、改 feature 开关 | 通常不算，只评价集成质量 |
| 新增子系统 | `special.rs` 400 行、futex 重构 191 行 | 才算主要原创工作 |
| 功能性扩展 | `splice`、`preadv2` 等新 syscall | 算增量实现 |
| 机制级重写 | 调度、内存、文件系统、驱动路径出现结构性改造 | 算高价值增量 |

这个标准服务于评委最关心的问题：剥离框架、依赖、适配和包装后，学生真正完成的机制创新和工程投入是什么。

## 九、实施路径

### Phase 1: 证据工厂 + 单报告 Markdown 验证

- 写 `tools/evidence_factory.py`：输入 repo 名，输出 `_evidence/` 下所有预计算数据。
- 手动跑一次完整流程：证据 → Markdown 报告 → 对比旧 JSON 效果。
- 对比典型作品的 JSON vs Markdown 可读性。

### Phase 2: 工作流固化 + 模板化

- 写 `workflow/engine.py`：5 个 Stage，每个 Stage 读模板文件和证据文件，只做顺序控制和质量门禁，不做自研 Agent 推理。
- 写 `workflow/prompts/` 下的模板文件，防止 prompt 每轮缩水。
- 验证子任务并行能力，但 MCP 调用仍由主会话串行执行。

### Phase 3: 全面切换到 Markdown

- 所有作品输出 `report.md`。
- `index.html` 改为读 `tags.yaml`。
- 删除或弱化 `evidence_store` / `provenance` / `base_decision` 独立报告入口，只保留必要技术中间产物。
- 前端简化到搜索、过滤、打开报告，不再承载复杂报告渲染逻辑。

### Phase 4: 自适应粒度

- evidence 工厂扫描项目规模，动态决定模块数。
- 极简内核不展开 112 节点。
- `not_applicable` 自动折叠，不为不存在的功能写长篇说明。
- 大型复杂作品保留更细模块，但只展开有真实代码证据的部分。
