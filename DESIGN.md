# OS-Agent 可审计 Base 发现与差异报告设计

## 职责边界

宿主 Agent 负责确认作品版本、识别代码范围、选择参考作品，并为完整内核框架编写 Claim、NodeReview、ModuleReview 和 OverallAssessment。本地程序负责将 `作品@分支` 锁定为 commit、确定性指纹、双侧 Scope 搜索、双向函数匹配、Comparison 数据库、Evidence 校验、完整性校验和双报告投影。

声明、glossary、vocab 与 Node Scope 都只能帮助判断，不能单独支撑实现或抄袭结论。

## 主流程

```text
默认检出分支尖端 → 必要时分页检查其他分支尖端 → 按 commit 合并别名并锁定
→ Git blob 内存解析并生成最小指纹缓存
→ Agent 审核目标 ScopeManifest → 粗召回 Top-K
→ 审核候选 ScopeManifest → 双侧正式重排
→ BaseEvidencePacket → Agent BaseDecision → 程序准入
→ 双向函数比较 → Comparison SQLite + JSONL 审计导出
→ Agent 按 112 节点提交 Claim 与评审 → Evidence/负向搜索 → 完整性校验
→ report.json/report.html 评委主报告 + provenance.json/provenance.html 技术附录
```

粗召回结果标记为 `score_kind=rough`，禁止进入 BaseDecision 和报告排名。正式结果要求目标与候选均有 `status=verified` 的 ScopeManifest。

## 核心模块

| 模块 | 责任 |
|---|---|
| `core/snapshot.py` | 默认选择当前检出分支尖端，解析 commit/tree hash、合并 ref aliases；不复制源码树 |
| `core/git_source.py` | 从 Git commit 直接枚举 tree、批量读取 blob 和源码片段，不 checkout、不 archive、不写临时源码 |
| `core/scope.py` | 构建和验证双侧 ScopeManifest，自动识别声明的 submodule |
| `scripts/fingerprint.py` | 全归一化 token SHA-256、AST shape、调用邻居；缓存绑定 commit 和 schema |
| `core/scoped_search.py` | 双侧 Scope 的 token/AST containment 搜索，区分 rough/formal |
| `core/base_decision.py` | 声明来源提取、BaseEvidencePacket、BaseDecision 程序准入 |
| `core/comparison.py` | 双向函数匹配、确定性 ComparisonRecord 与候选 MatchEdge |
| `core/comparison_db.py` | SQLite 查询主库、JSONL 审计交接、分页聚合与 RelationshipHint |
| `core/evidence.py` | EvidenceCandidate 校验、稳定 EvidenceRecord、完整覆盖负向搜索 |
| `core/judge_report.py` | Claim、NodeReview、ModuleReview、OverallAssessment 与完整框架/Evidence 强校验 |
| `core/provenance_report.py` | 从 Comparison 数据库导出完整确定性函数溯源数据 |
| `scripts/judge_report.py` | 校验 `report.json`，整理 React 前端 view-model，注入 `web_report/dist` 并复制静态 assets |
| `web_report/` | React + Vite + TypeScript 的评委主报告前端，负责模块/节点导航、架构图交互、目录树和相关 Evidence 展示 |
| `scripts/provenance_report.py` | 独立文件树、函数列表、来源候选与源码对照技术附录 |
| `mcp_server.py` | 向宿主 Agent 暴露结构化阶段接口 |

## Claude Code 与源码工作树

Claude Code 是分析主体，可以用 bash、rg、sed、LSP 和 MCP 查询代码。BaseDecision 由 Claude Code 判断；`base_decision_submit` 只负责程序准入和审计落盘。校验通过后，Claude Code 直接用当前 decision/packet 中的 target commit 与 selected base commit 强制 checkout `repos/<target>` 和 `repos/<base>` 到 detached HEAD，再开始源码阅读。提交仓库是外部 clone，工作树残留不作为用户代码保护对象；正式分析不得继续读取 Base 仓库默认分支。

`compare_functions` 也应使用同一组 target/base commits，使函数级 Comparison、Claude Code 的源码阅读和最终报告全部绑定一致。

## 确定性函数状态

匹配顺序为：精确 token 指纹；精确 AST 与路径角色；名称、MinHash token、AST、相对路径和调用邻居联合评分；最后输出剩余项。

| 状态 | 含义 |
|---|---|
| `exact_copied` | 同名且完整归一化 token SHA-256 相同 |
| `renamed_exact` | 名称不同但完整归一化 token SHA-256 相同 |
| `modified_candidate` | 多信号形成唯一候选对，等待 Agent 解释语义变化 |
| `target_only` | 目标新增 Unit |
| `base_only` | Base 中存在、目标没有匹配 Unit |
| `ambiguous` | 存在多个近似或精确候选，等待复核 |

同名本身永远不足以产生 `modified_candidate`。`raw_status` 是工具事实，不允许被 Agent 覆盖。

## Comparison 数据库、Agent 消费与 Evidence

主 Base 确定后，程序建立完整 ComparisonRun：SQLite 保存 Units、确定性 ComparisonRecords、多对多 MatchEdges 与 RelationshipHints；JSONL 保留可审计导出。主 Base 产生完整双向状态，Agent 选择的次级来源只增加局部 MatchEdge，不改变主 Base 全局统计。

Agent 不一次读取全部函数，严格按概要、热点、目录、文件、函数候选和源码组逐层查询。程序自动生成全局/目录/文件数量、目标文件的多个来源文件、来源文件的反向拆分视图和可分页函数名列表。
`base_only` 由程序按 Base 文件单独分页展示，只证明具体 Base Unit 没有确定性目标匹配；要断言整个机制被删除，仍必须有覆盖完整的负向搜索证据。

BaseDecision 保持轻量：程序只校验所选 repo/commit 来自 formal verified 候选、引用了 Evidence，并通过候选覆盖准入；年份方向不作为硬拒条件。年份、声明来源、公开上游关系、git history、同年互抄可能性和未知年份风险由 Agent 在主报告的 `base_selection_reason` 中用中文解释。

Agent 写回的是 Claim 和框架评审，不是函数分类。每个 Claim 挂到一个语义节点，可引用多个 comparison 和 EvidenceRecord；文件、函数与 comparison 均不强制归属设计树。每个节点必须有 Claim、实现度判断、原创度判断和理由，14 个模块必须有模块总结。
宿主 Agent 通过 `evidence_formal_search`、`evidence_source` 和带项目路径的 `negative_search` 请求证据；只有 EvidenceStore 验证后生成的稳定 ID 才能进入 Claim。比较型 Claim 要求双侧证据，独立新增与未实现结论还要满足额外的正式搜索或负向搜索约束。

所有批次共享一个 `report.json` 与一个 `evidence_store.jsonl`。EvidenceStore 按持久化路径共享追加锁；JudgeReport 按报告路径共享读改写锁。节点工作者使用 `node_review_bundle_submit` 原子写入 Claims 与 NodeReview，避免并发 sub-agent 覆盖彼此结果。批次按依赖顺序串行推进，批内仅对强耦合节点组进行有限并行。

指纹预建从 Git commit blob 直接在内存中解析源码，只持久化 `units/fpset/astset/meta/scopes`。预建阶段不得仅凭目录名硬排除 Git tracked 的支持语言源码；疑似第三方、依赖或生成代码只作为 Scope 审核线索。完整 CodeAtlas 和源码 snapshots 不再是产品态缓存；`code_atlas_*` MCP 工具仅保留 deprecated 响应。Comparison 数据库负责跨作品匹配查询；关键定义、引用和调用链优先由 checkout 到锁定 commit 后的 `lsp_*`、bash/rg/sed 和 Comparison 数据确认。

作品版本面向 Agent 和评委使用 `作品@分支` 表述。默认版本是 clone 当前检出分支的尖端；只有存在明确理由时才分页检查并选择其他分支尖端。接口不遍历历史 commit，且多个分支指向同一 commit 时只返回一次。程序将选定分支解析为 commit 并在整个分析中锁定，避免 ref 移动或工作树改动污染结果。

LSP 分析前要求 Claude Code 将对应 `repos/<name>` checkout 到锁定 commit；MCP 会校验 HEAD 是否匹配。缺少编译数据库时，LSP 层会临时生成带 OS-Agent 管理标记的 `compile_flags.txt`；最后一个 clangd 客户端退出、MCP 退出或下次分析启动前必须自动删除。该辅助文件不参与指纹、Scope、Comparison 或 Evidence。

## 操作与产物约定

项目只提供一个 Claude Code Skill：`.claude/skills/os-agent/SKILL.md`。它设置 `disable-model-invocation: true`，因此开发 OS-Agent 时不会自动触发；执行作品审计时由用户显式调用 `/os-agent`。

项目级 `.mcp.json` 通过 `scripts/start_mcp.sh` 启动 MCP。启动脚本优先使用 `OS_AGENT_PYTHON`，其次寻找常见位置下的 `os_agent` Conda 环境，最后尝试 `conda run -n os_agent`。首次使用需要在 Claude Code 中批准项目 MCP；服务代码或工具签名变化后需要重新连接 MCP。

每次分析使用独立输出目录，目录内只共享一份 `report.json` 和一份 `evidence_store.jsonl`。标准产物为：

```text
report.json / report.html
provenance.json / provenance.html
evidence_store.jsonl
comparison.sqlite / comparisons.jsonl
```

`repos/`、`.fp_cache/`、`output/` 和 `.claude/settings.local.json` 都是本地状态，不进入 Git；Skill、MCP 配置、启动脚本、模型和渲染器进入 Git。测试属于本地开发行为，不作为产品交付内容。

具体指纹链路：

```text
Git commit blob reader
→ tree-sitter extractor
→ normalize_function_tokens
→ ast_shape_hash
→ scripts/fingerprint.py 生成完整归一化 token SHA-256 与 MinHash signature
→ Comparison/Search 消费 Unit 指纹
```

汇编不经过 tree-sitter，使用 `asm_tokenize.py` 归一化 label block 后生成 token 指纹。

负向搜索固定 commit、搜索计划、实际路径、查询、扩展名和扫描文件数。只有零匹配且 `coverage_complete=true` 才支持 `not_found`；否则只能是 `unknown`。

## 双报告边界

`report.html` 面向评委，使用作品名而不是内部“目标/Base”术语，完整展示框架节点的实现度、原创度、差异与 Claim。主报告按总体、模块、节点组织，并在首页用中文展示 Base 选择依据和 Scope 排除过程。语言占比和完整目录树来自快照事实，目录说明由 Agent 通过 `directory_notes` 绑定到目录项。内核架构图来自 Agent 提交的 Mermaid，前端只提供缩放、拖拽平移和重置交互。Evidence 只在相关模块/节点页面底部以彩色证据卡展示，正文只引用易读编号。
正文 Evidence 链接会标记为源码证据、文档证据、链路证据或审计证据；底部卡片进一步展示具体类型标签，如函数定义、调用链、正式检索和负向搜索。

`provenance.html` 面向技术复核，独立展示确定性函数状态、文件多来源、参考作品未匹配函数与源码对照。它不生成原创度、实现度或 Agent Claim。旧混合 `AuditProject/Finding/index.html` 流程已删除。

## 方向与报告模式

指纹相似度无方向。方向来自年份、声明、公开上游关系、git history 和 Agent 对代码关系的解释。年份是强线索但不是硬门槛；同年候选可能存在互抄、共同上游或协作传播，不能仅因同年排除，也不能仅凭同年建立方向。xlsx 缺失的开源教学项目、框架或公开上游可以作为 Base 候选，但报告必须说明年份表无法校验和替代方向依据。默认生成目标与主 Base 的差异报告；独立描述报告仅在无正式可靠 Base、声明来源已强制对比且程序准入后允许。

## 真实回归

`oskernel2023-zmz@837b6a9` 的双侧正式搜索应将 `xv6-k210@d7f3e5e` 排名第一，方向为 `2021 → 2023`。验收按 commit，不按分支字符串；隐藏 README 声明后仍须得到同一主 Base。
