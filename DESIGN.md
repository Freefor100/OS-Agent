# OS-Agent 可审计 Base 发现与差异报告设计

## 职责边界

宿主 Agent 负责确认作品版本、识别代码范围、选择参考作品，并为完整内核框架编写 Claim、NodeReview、ModuleReview 和 OverallAssessment。本地程序负责将 `作品@分支` 锁定为 commit、确定性指纹、双侧 Scope 搜索、双向函数匹配、Comparison 数据库、Evidence 校验、完整性校验和双报告投影。

声明、glossary、vocab 与 Node Scope 都只能帮助判断，不能单独支撑实现或抄袭结论。

## 主流程

```text
用户显式指定待查重分支 → bash 校验当前检出分支和干净工作树 → rev-parse HEAD 锁定 commit
→ Git blob 内存解析并生成最小指纹缓存
→ Agent 审核目标 ScopeManifest → 粗召回 Top-K
→ 候选缺失 Scope 时使用自动轻量范围 → 双侧正式重排
→ BaseEvidencePacket → Agent BaseDecision → 程序准入
→ 双向函数比较 → Comparison SQLite + JSONL 审计导出
→ Agent 按 112 节点提交 Claim 与评审 → Evidence/负向搜索 → 完整性校验
→ report.json/report.html 评委主报告 + provenance.json/provenance.html 技术附录
```

粗召回结果标记为 `score_kind=rough`，禁止进入 BaseDecision 和报告排名。正式搜索要求目标作品有 `status=verified` 的 ScopeManifest；候选缺少 ScopeManifest 时由程序生成确定性的 `auto_candidate` 轻量范围，不要求 Agent 为 Top-K 候选逐个补 Scope 证据。

## 核心模块

| 模块 | 责任 |
|---|---|
| `core/snapshot.py` | 解析指定 commit 的 tree hash 和 ref aliases；不复制源码树 |
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

审计开始时必须先由用户显式指定待查重分支；没有分支就不启动分析。Agent 用 bash 执行 `git -C repos/<target> branch --show-current` 和 `git -C repos/<target> status --porcelain`，确认当前检出分支就是用户要审计的分支且工作树干净；只有通过后才用 `git -C repos/<target> rev-parse HEAD` 锁定 commit、创建审计目录和构建指纹。分支/工作树检查和 commit 锁定不需要新增 MCP 工具。

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

BaseDecision 保持轻量：程序只校验所选 repo/commit 来自 formal 候选，并通过返回候选覆盖准入；年份方向不作为硬拒条件，formal_search Evidence 不要求 Agent 手工注册或回填。多来源作品仍只在 BaseDecision 中选择主骨架锚点，其他来源通过 `comparison_add_secondary_source`、Evidence 和报告字段表达。年份、声明来源、公开上游关系、git history、同年互抄可能性、未知年份风险和多来源拆分由 Agent 在 `base_selection_reason`、`source_relation` 和模块评审中用中文解释。

Agent 写回的是 Claim 和框架评审，不是函数分类。每个 Claim 挂到一个语义节点，可引用多个 comparison 和 EvidenceRecord；文件、函数与 comparison 均不强制归属设计树。每个节点必须有 Claim、实现度判断、原创度判断和理由，14 个模块必须有模块总结。
宿主 Agent 通过 `evidence_source`、`evidence_structured(kind="scope_exclusion_decision")` 和带项目路径的 `negative_search` 请求证据；只有 EvidenceStore 验证后生成的稳定 ID 才能进入 Claim。Evidence 工具直接读取已 checkout 的工作树，并在入口强制校验 HEAD 等于传入 ref 且 `git status --porcelain` 干净。比较型 Claim 要求双侧证据，独立新增与未实现结论还要满足额外的正式搜索或负向搜索约束。

所有批次共享一个 `report.json` 与一个 `evidence_store.jsonl`。EvidenceStore 按持久化路径共享追加锁；JudgeReport 按报告路径共享读改写锁。节点工作者使用 `node_review_bundle_submit` 原子替换该节点的 Claims 与 NodeReview，避免并发 sub-agent 覆盖彼此结果，也避免返工残留旧结论。批次按依赖顺序串行推进，批内仅对强耦合节点组进行有限并行。

指纹预建从 Git commit blob 直接在内存中解析源码，只持久化 `units/fpset/astset/meta/scopes`。预建阶段不得仅凭目录名硬排除 Git tracked 的支持语言源码；疑似第三方、依赖或生成代码只作为 Scope 审核线索。Comparison 数据库负责跨作品匹配查询；关键定义、引用和调用链优先由 checkout 到锁定 commit 后的 `lsp_*`、bash/rg/sed 和 Comparison 数据确认。

作品版本面向 Agent 和评委使用 `作品@分支` 表述。分支必须由用户显式指定；Agent 只分析该分支当前检出的尖端 commit。程序将选定分支解析为 commit 并在整个分析中锁定，避免 ref 移动或工作树改动污染结果。

LSP 分析前要求 Claude Code 将对应 `repos/<name>` checkout 到锁定 commit；MCP 会校验 HEAD 是否匹配。关键 Evidence 注册前还要求工作树干净。缺少编译数据库时，LSP 层会临时生成带 OS-Agent 管理标记的 `compile_flags.txt`；最后一个 clangd 客户端退出、MCP 退出或下次分析启动前必须自动删除。该辅助文件不参与指纹、Scope、Comparison 或 Evidence。

## 操作与产物约定

项目只提供一个 Claude Code Skill：`.claude/skills/os-agent/SKILL.md`。它设置 `disable-model-invocation: true`，因此开发 OS-Agent 时不会自动触发；执行作品审计时由用户显式调用 `/os-agent`。

本地 `.claude/mcp.json` 由跟踪的 `.claude/mcp.json.example` 复制得到，不进入 Git；格式保持 Claude Code 生成形态：`command` 指向本机 Python 解释器，`args` 指向项目 `mcp_server.py`。这些绝对路径是个人环境配置，不进入 Git。`scripts/start_mcp.sh` 只作为环境诊断和手动启动入口，优先使用 `OS_AGENT_PYTHON`，其次寻找项目 `.venv`、常见位置下的 `os_agent` Conda/Mamba 环境，最后尝试 `conda run -n os_agent`。首次使用需要在 Claude Code 中批准本地 MCP；服务代码或工具签名变化后需要重新连接 MCP。

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

负向搜索固定 commit、搜索计划、实际路径、查询、扩展名、路径存在性、eligible 文件数、扫描文件数、读错误和逐查询命中数。只有路径存在、有 eligible 文件、无读错误、零匹配且 `coverage_complete=true` 才支持 `not_found`；否则只能是 `unknown`。

## 双报告边界

`report.html` 面向评委，使用作品名而不是内部“目标/Base”术语，完整展示框架节点的实现度、原创度、差异与 Claim。主报告按总体、模块、节点组织，并在首页用中文展示 Base 选择依据和 Scope 排除过程。语言占比和完整目录树来自锁定 commit 的源码事实，目录说明由 Agent 通过 `directory_notes` 绑定到目录项。内核架构图来自 Agent 提交的 Mermaid，前端只提供缩放、拖拽平移和重置交互。Evidence 只在相关模块/节点页面底部以彩色证据卡展示，正文只引用易读编号。
正文 Evidence 链接会标记为源码证据、文档证据、链路证据或审计证据；底部卡片进一步展示具体类型标签，如函数定义、调用链、正式检索和负向搜索。

`provenance.html` 面向技术复核，独立展示确定性函数状态、文件多来源、参考作品未匹配函数与源码对照。它不生成原创度、实现度或 Agent Claim。

## 方向与报告模式

指纹相似度无方向。方向来自年份、声明、公开上游关系、git history 和 Agent 对代码关系的解释。年份是强线索但不是硬门槛；同年候选可能存在互抄、共同上游或协作传播，不能仅因同年排除，也不能仅凭同年建立方向。对同届高相似候选，Agent 必须围绕相似文件/函数检查双方 Git 历史，包括首次引入时间、提交形态、批量导入痕迹、作者/提交信息、文档声明和共同第三方来源线索，并把结论写成概率性分类：目标更可能吸收候选、候选更可能吸收目标、双方共同参考第三方、协作/共享代码传播或证据不足。xlsx 缺失的开源教学项目、框架或公开上游可以作为 Base 候选，但报告必须说明年份表无法校验和替代方向依据。默认生成目标与主 Base 的差异报告；独立描述报告仅在无正式可靠 Base、声明来源已强制对比且程序准入后允许。

## 真实回归

`oskernel2023-zmz@837b6a9` 的双侧正式搜索应将 `xv6-k210@d7f3e5e` 排名第一，方向为 `2021 → 2023`。验收按 commit，不按分支字符串；隐藏 README 声明后仍须得到同一主 Base。
