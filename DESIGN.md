# OS-Agent 可审计 Base 发现与差异报告设计

## 职责边界

宿主 Agent 负责确认作品版本、识别代码范围、选择参考作品，并为完整内核框架编写 Claim、NodeReview、ModuleReview 和 OverallAssessment。本地程序负责将 `作品@分支` 锁定为 commit、确定性指纹、双侧 Scope 搜索、双向函数匹配、Comparison 数据库、Evidence 校验、完整性校验和双报告投影。

声明、glossary、vocab 与 Node Scope 都只能帮助判断，不能单独支撑实现或抄袭结论。

## 主流程

```text
默认检出分支尖端 → 必要时分页检查其他分支尖端 → 按 commit 合并别名并锁定
→ Git archive 内部源码快照
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
| `core/snapshot.py` | 默认选择当前检出分支尖端，解析 commit/tree hash、合并 ref aliases，并用 `git archive` 生成内部源码快照 |
| `core/scope.py` | 构建和验证双侧 ScopeManifest，自动识别声明的 submodule |
| `scripts/fingerprint.py` | 全归一化 token SHA-256、AST shape、调用邻居；缓存绑定 commit 和 schema |
| `core/scoped_search.py` | 双侧 Scope 的 token/AST containment 搜索，区分 rough/formal |
| `core/base_decision.py` | 声明来源提取、BaseEvidencePacket、BaseDecision 程序准入 |
| `core/comparison.py` | 双向函数匹配、确定性 ComparisonRecord 与候选 MatchEdge |
| `core/comparison_db.py` | SQLite 查询主库、JSONL 审计交接、分页聚合与 RelationshipHint |
| `core/evidence.py` | EvidenceCandidate 校验、稳定 EvidenceRecord、完整覆盖负向搜索 |
| `core/judge_report.py` | Claim、NodeReview、ModuleReview、OverallAssessment 与完整框架/Evidence 强校验 |
| `core/provenance_report.py` | 从 Comparison 数据库导出完整确定性函数溯源数据 |
| `scripts/judge_report.py` | 固定左侧框架目录、节点详情、静态架构图与集中 Evidence 的评委主报告 |
| `scripts/provenance_report.py` | 独立文件树、函数列表、来源候选与源码对照技术附录 |
| `mcp_server.py` | 向宿主 Agent 暴露结构化阶段接口 |

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

Agent 写回的是 Claim 和框架评审，不是函数分类。每个 Claim 挂到一个语义节点，可引用多个 comparison 和 EvidenceRecord；文件、函数与 comparison 均不强制归属设计树。每个节点必须有 Claim、实现度判断、原创度判断和理由，14 个模块必须有模块总结。
宿主 Agent 通过 `evidence_formal_search`、`evidence_source` 和带项目路径的 `negative_search` 请求证据；只有 EvidenceStore 验证后生成的稳定 ID 才能进入 Claim。比较型 Claim 要求双侧证据，独立新增与未实现结论还要满足额外的正式搜索或负向搜索约束。

所有批次共享一个 `report.json` 与一个 `evidence_store.jsonl`。EvidenceStore 按持久化路径共享追加锁；JudgeReport 按报告路径共享读改写锁。节点工作者使用 `node_review_bundle_submit` 原子写入 Claims 与 NodeReview，避免并发 sub-agent 覆盖彼此结果。批次按依赖顺序串行推进，批内仅对强耦合节点组进行有限并行。

CodeAtlas 仍是指纹、AST shape、调用邻居和结构中心度的来源，不是废弃模块。Comparison 数据库负责跨作品匹配查询；`code_atlas_overview/search` 负责不可变单作品的全局结构导航和入口候选发现；关键定义、引用和调用链优先由针对指定不可变 commit 执行的 `lsp_*` 语义确认。`code_atlas_call_neighbors` 用于低成本导航、分页、交叉检查或 LSP 不可用时补充，不得单独支撑关键调用链 Claim。

作品版本面向 Agent 和评委使用 `作品@分支` 表述。默认版本是 clone 当前检出分支的尖端；只有存在明确理由时才分页检查并选择其他分支尖端。接口不遍历历史 commit，且多个分支指向同一 commit 时只返回一次。程序将选定分支解析为 commit 并在整个分析中锁定，避免 ref 移动或工作树改动污染结果。内部 materialized snapshot 路径仅是缓存实现细节，不进入报告。

LSP 同样分析锁定 commit 的内部源码快照。缺少编译数据库时，LSP 层会临时生成带 OS-Agent 管理标记的 `compile_flags.txt`；最后一个 clangd 客户端退出、MCP 退出或下次分析启动前必须自动删除。该辅助文件不参与指纹、Scope、Comparison 或 Evidence，也不得写入 `repos/` 中的作品工作树。

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
CodeAtlas tree-sitter extractor
→ normalize_function_tokens
→ ast_shape_hash
→ scripts/fingerprint.py 生成完整归一化 token SHA-256 与 MinHash signature
→ Comparison/Search 消费 Unit 指纹
```

汇编不经过 tree-sitter，使用 `asm_tokenize.py` 归一化 label block 后生成 token 指纹。

负向搜索固定 commit、搜索计划、实际路径、查询、扩展名和扫描文件数。只有零匹配且 `coverage_complete=true` 才支持 `not_found`；否则只能是 `unknown`。

## 双报告边界

`report.html` 面向评委，使用作品名而不是内部“目标/Base”术语，完整展示框架节点的实现度、原创度、差异与 Claim。Evidence 在页面底部集中折叠展示，正文只引用易读编号。
正文 Evidence 链接会标记为源码证据、文档证据、链路证据或审计证据；底部卡片进一步展示具体类型标签，如函数定义、调用链、正式检索和负向搜索。

`provenance.html` 面向技术复核，独立展示确定性函数状态、文件多来源、参考作品未匹配函数与源码对照。它不生成原创度、实现度或 Agent Claim。旧混合 `AuditProject/Finding/index.html` 流程已删除。

## 方向与报告模式

指纹相似度无方向。方向来自年份、声明和 Git 证据。同届候选进入人工复审区，不能作为有方向性的主 Base。默认生成目标与主 Base 的差异报告；独立描述报告仅在无正式可靠 Base、声明来源已强制对比且程序准入后允许。

## 真实回归

`oskernel2023-zmz@837b6a9` 的双侧正式搜索应将 `xv6-k210@d7f3e5e` 排名第一，方向为 `2021 → 2023`。验收按 commit，不按分支字符串；隐藏 README 声明后仍须得到同一主 Base。
