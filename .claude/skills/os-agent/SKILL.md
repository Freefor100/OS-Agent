---
name: os-agent
description: Analyze an OS competition submission for lineage, implementation completeness, originality, and differences using the os-agent MCP. Use when asked to analyze, compare, audit, check duplication, or generate a judge report for a repository under repos/.
disable-model-invocation: true
---

# OS-Agent Skill：可审计 Base 发现与差异报告

## 原则

宿主 Agent 负责判断；本地工具只做不可变快照、范围校验、确定性搜索/比较、Evidence 校验和报告投影。正式结论必须引用 commit、ScopeManifest、comparison 和 EvidenceRecord。

- 开始分析前确认用户指定了独立输出目录；该目录固定保存本次分析唯一的 `report.json`、`evidence_store.jsonl`、Comparison 数据库和双报告。
- 不扫描工作树，只分析 Git commit 快照。
- 分支只是入口；多个别名指向同一 commit 时只分析一次。
- `search_similar` 是内部粗召回，禁止用于报告排名或 BaseDecision。
- 正式搜索必须使用目标和候选各自的 verified ScopeManifest。
- 声明是强线索，不自动成为 Base；声明来源必须正式对比。
- 同届候选只进入复审区，不能作为有方向性的主 Base。
- Node Scope 是语义边界和导航提示，不是函数路由规则。
- Agent 可解释 `modified_candidate`，但不得覆盖 `raw_status`。

## 结构化阶段

### 1. 发现目标不可变快照

1. 调 `repo_snapshots(target)`。默认作品版本是 clone 当前检出分支的尖端，面向用户表述为 `作品@分支`；程序同时记录其 commit 作为整个流程的审计锁。默认响应不返回其他分支，避免占用上下文。
2. 仅当 README、分支命名或内容表明默认分支可能不是最终作品时，才使用 `include_other_branches=true` 分页检查其他唯一分支尖端并改变选择。该接口不遍历历史 commit，并按 commit 合并等价分支别名。
3. 后续 MCP 调用传入选定分支解析出的固定 commit，防止长流程中 ref 移动；报告正文使用 `作品@分支`，commit 仅放入版本与证据详情。
4. 调 `build_fingerprint(target, ref=<固定 commit>)`。缓存绑定 commit 与指纹 schema，脏工作树不参与。

### 2. 确认目标 ScopeManifest

1. 阅读 `.gitmodules`、Cargo workspace、Makefile、README 和目录结构。
2. 判断学生代码、外部依赖、生成物和文档范围。
3. 调 `create_scope_manifest(target, ref=<commit>, ...)`；程序验证路径与 submodule 声明。
4. Scope 的排除理由应引用 EvidenceRecord。不得用预置外部依赖名单代替判断。

### 3. 粗召回、候选审核、正式重排

1. `search_similar(...)` 或 `search_formal(..., formal_only=false)` 仅用于粗召回。
2. 审核 Top-20 中缺少 ScopeManifest 的候选，并逐个调用 `create_scope_manifest`。
3. 调 `search_formal(..., formal_only=true)` 正式重排。
4. 报告只展示 `score_kind=formal` 且双方 scope verified 的结果。

### 4. Base 决策

1. 调 `base_evidence_packet(target, ref, formal_candidates, target_year, include_declarations=true)`。
2. Agent 综合正式排名、年份方向、声明验证、核心目录覆盖和差异解释能力选择候选，并调 `evidence_formal_search` 将正式搜索结果写入本项目 EvidenceStore。
3. 提交引用该 evidence ID 的 BaseDecision，再调 `validate_base_decision(decision, packet)`。主 Base 必须按 repo+commit 引用正式候选。
4. 对去声明回归，再以 `include_declarations=false` 组包并验证同一决定。
5. 仅当无可靠正式 Base、声明来源均已强制对比且程序准入时，才允许独立报告。

### 5. Comparison 数据库与按需消费

1. 调 `compare_functions(..., output_dir=...)` 建立主 Base 的完整 ComparisonRun；SQLite 是查询主库，JSONL 是审计导出。
2. Agent 不一次加载全部函数。先调 `comparison_overview` 和 `comparison_hotspots` 获取概要与热点。
3. 用 `comparison_search_units` 按符号/路径定位节点入口，用 `comparison_by_status` 按确定性状态分页抽样。
4. 按需调用 `comparison_directory_summary`、`comparison_directory_sources`、`comparison_file_summary`、`comparison_file_functions` 和 `comparison_base_only_files`。所有列表必须分页；文件可对应多个来源文件。
5. 对关键函数调用 `comparison_function_candidates`、`comparison_detail`、`comparison_call_context` 和 `comparison_source_group`，读取候选来源、调用邻居差异与不可变源码。
6. `MatchEdge` 和 `RelationshipHint` 只是候选关系，不等于整合、拆分、挪用或抄袭结论。
7. 主 Base 的 `raw_status` 只能由程序生成；次级来源通过 `comparison_add_secondary_source` 增加局部候选边，不改变主 Base 统计。

### 6. Claim 驱动的完整框架评审

1. 调 `judge_report_create` 创建 `report.json` 骨架；它引用 ComparisonRun 和 EvidenceStore，但不内嵌全部函数对比。
2. 整个项目只使用一个全局 `evidence_store.jsonl` 和一个全局 `report.json`。不得给不同批次创建私有 EvidenceStore。
3. 严格按 `ANALYSIS_BATCHES_V2` 的先后顺序处理全部 112 个节点。跨批次存在依赖，不并行启动所有批次。
4. 一个批次内按“关键链路/强耦合节点组”分配 1–3 个 sub-agent；不要把整个批次塞给一个上下文，也不要机械地为每个节点创建一个 sub-agent。每个 sub-agent 必须覆盖获分配组内全部节点，并返回结构化草稿。
5. 每个节点先调 `node_analysis_packet`，再用 Comparison 与 `code_atlas_search` 定位候选文件、符号和入口。关键调用链优先使用带目标 `ref` 的 `lsp_call_graph`、`lsp_definition` 和 `lsp_references` 做语义确认；检查返回中的 fallback/confidence 信息。`code_atlas_call_neighbors` 用于全仓库低成本导航、分页、交叉检查或 LSP 不可用时的补充。`code_atlas_overview` 默认只返回少量中心函数，只用于首次架构初探，不得在每个节点重复调用，也不得单独支撑调用链 Claim。sub-agent 可以注册 Evidence，但不得直接写共享 `report.json`。
6. Agent 读完源码后，调用 `evidence_list` 复用已有证据；缺少时用 `evidence_source_batch` 注册源码范围，调用链/历史/Scope 等结构化事实用 `evidence_structured` 注册。工具返回的 `evidence_id` 才能写入 Claim。
7. 宿主 Agent 汇总并检查批内 sub-agent 草稿后，为每个节点调用一次 `node_review_bundle_submit` 原子提交 Claims 与 NodeReview。单条修订才使用 `claim_update` 或 `node_review_submit`。
8. 每个 NodeReview 必须说明实际实现、与参考作品差异、实现度、原创度、风险和技术附录定位。函数、文件和 comparison 不要求归属节点。
9. 完成一个模块后，由宿主 Agent综合节点结果提交 `ModuleReview`，其中必须包含模块总结和有 Claim/Evidence 支撑的 `key_chains`。
10. 14 个模块完成后，宿主 Agent 提交 `OverallAssessment` 和由实际分析得到的 `architecture_edges`，用于生成总体总结与静态架构图。
11. 比较型 Claim 必须具有作品与参考作品双侧证据；独立新增必须同时有作品源码、正式候选覆盖和完整负向搜索证据。

### 7. Evidence 注册与共享

1. EvidenceStore 固定为当前报告目录下的 `evidence_store.jsonl`。它是所有批次、sub-agent、Claim、关键链路和总评共享的证据注册表。
2. Agent 用内置读文件、LSP 或 Comparison 源码组理解代码；“读过代码”本身不会产生 Evidence。必须显式调用 Evidence MCP 注册。
3. 源码证据使用 `evidence_source` 或 `evidence_source_batch`，参数必须包含作品、不可变 ref、路径和准确行号范围。
4. `evidence_source` 返回稳定 `evidence_id`；相同 commit、位置、类型和元数据重复注册会得到相同 ID。
5. 调用链、Git 历史和 ScopeManifest 使用 `evidence_structured`；PDF/DOCX/Markdown 文档使用 `evidence_document`；机制未实现使用 `negative_search`。
6. Claim 只引用 `evidence_id`，不得内嵌源码或自行编造 ID。写 Claim 前可用 `evidence_get/evidence_list` 检查与复用。

### 8. 负向搜索

1. 根据 glossary、Base 符号、目标命名风格和已发现入口构造查询。
2. 调 `negative_search(..., evidence_store=<本项目路径>)` 固定 commit、搜索计划、路径、扩展名、实际查询和扫描文件数。
3. 只有 `coverage_complete=true` 且零匹配才能支撑 `not_found`；否则结论为 `unknown`。

### 9. 校验与渲染

1. 每完成一个批次都调 `judge_report_status`；检查 `missing_by_batch`，当前批次未清零不得进入下一批。
2. 最终再次调用 `judge_report_status`，确认 112 个 NodeReview、112 个节点均有 Claim、14 个 ModuleReview、各模块关键链路、OverallAssessment、架构边和 Evidence 约束全部完成。
3. 只有 `judge_report_validate` 通过后才调用 `judge_report_render`，生成评委主报告 `report.html`。
4. 调 `provenance_export` 生成确定性函数溯源数据 `provenance.json`，再调 `provenance_render` 生成独立技术附录 `provenance.html`。
5. `report.html` 只展示完整框架评审、Claim 和底部 Evidence，不展示函数状态内部术语或完整函数列表。
6. `provenance.html` 只展示程序计算的函数匹配、来源候选与源码对照，不生成原创度、实现度或 Agent Claim。
7. 旧混合 `AuditProject/Finding/index.html` 流程已废弃，不得生成或复用。

标准产物目录必须包含：

```text
report.json / report.html
provenance.json / provenance.html
evidence_store.jsonl
comparison.sqlite / comparisons.jsonl
```

## 真实回归

目标 `oskernel2023-zmz` 应选择 commit `837b6a9...`，并合并 `recover/k210/display/remote HEAD` 等价别名；正式双侧 Scope 搜索应将 `xv6-k210` commit `d7f3e5e...` 排名第一，方向为 `2021 → 2023`。验收按 commit，不按分支字符串。正常模式和隐藏 README 声明模式都必须通过，禁止仓库名硬编码。
