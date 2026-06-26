---
name: os-agent
description: 使用 os-agent MCP 分析 repos/ 下操作系统竞赛作品的来源关系、实现完整度、原创度和实现差异，并生成中文评审报告。
disable-model-invocation: true
---

# OS-Agent Skill：可审计 Base 发现与差异报告

## 触发方式

用户显式执行 `/os-agent <作品名>` 时启动本 Skill。若用户只说“分析某作品”但没有给输出目录，自动使用：

```text
output/<repo-name>/audit-YYYYMMDD-HHMMSS/
```

开始时只向用户确认三件事：目标作品、锁定版本、输出目录。不要要求用户理解 BaseDecision、Comparison、EvidenceStore、report_generation 等内部概念。

## 原则

宿主 Agent 负责判断；本地工具只做不可变快照、范围校验、确定性搜索/比较、关键证据锚定和报告投影。最终 `report.html` 必须是中文报告；必要机制名可在中文后用括号补充解释，例如“多级反馈队列（MLFQ）”“写时复制（copy-on-write）”。

- 开始分析前确定独立输出目录；若用户未指定，自动使用 `output/<repo-name>/audit-YYYYMMDD-HHMMSS/`，并在开始时告知用户。随后调用 `audit_manifest_create` 创建本次分析唯一的 `audit_manifest.json`，该目录固定保存 `base_decision.json`、`report.json`、`evidence_store.jsonl`、Comparison 数据库和双报告。
- 不扫描工作树，只分析 Git commit 快照。
- 预建指纹阶段不得仅凭目录名硬排除 Git tracked 的支持语言源码；看起来像依赖、生成物或外部代码的路径只能作为 Scope 审核线索，不能替代证据裁决。
- 分支只是入口；多个别名指向同一 commit 时只分析一次。
- `search_similar` 是内部粗召回，禁止用于报告排名或 BaseDecision。
- 正式搜索必须使用目标和候选各自的 verified ScopeManifest。
- 声明是强线索，不自动成为 Base；声明来源必须正式对比。
- 同届候选只进入复审区，不能作为有方向性的主 Base。
- 参赛年份、学校、队伍和是否在参赛表内，统一通过 MCP `repo_metadata`、`search_formal`、`base_evidence_packet` 等工具返回的元数据消费；不要直接读取或解析 `collected-data.xlsx`。xlsx 的地址列和表头是 MCP 内部索引实现细节，Agent 只使用工具返回的行级队伍信息。
- Node Scope 是语义边界，不是函数路由规则，也不能单独作为查重证据。旧机制标签和词表已从产品态工具输出移除，不参与导航、证据或报告内容。
- Agent 可解释 `modified_candidate`，但不得覆盖 `raw_status`。
- 阅读内核实现时必须主动留意面向平台评测或公开测例的硬编码、旁路和刷分式实现，例如按固定路径、固定参数、固定测试程序名或固定设备名特判返回结果。发现后应在对应节点/模块中用中文说明其适用范围、对真实内核机制完整度的影响和评审风险；不得把这类过测旁路等同于完整通用机制。
- 报告优先面向评委阅读，避免堆砌工具术语；所有概述、模块总结、节点说明和架构边标签必须使用中文。

## MCP 主路径工具

默认只沿下面主路径调用工具。其他 MCP 工具只能用于补查、定位或故障恢复，不作为主流程入口。

| 阶段 | 主路径工具 | 目的 |
|---|---|---|
| 启动审计 | `repo_snapshots`、`audit_manifest_create`、`build_fingerprint` | 锁定作品 commit、创建独立审计目录、准备指纹 |
| 确认范围 | `create_scope_manifest` | 固定学生代码范围和外部依赖排除 |
| 参考发现 | `search_formal` | 完成双侧 verified scope 的正式 1-vs-N 搜索 |
| Base 固化 | `base_evidence_packet`、`evidence_formal_search`、`base_decision_submit` | 让 Agent 判断参考来源，并由程序校验写入 `base_decision.json` |
| 函数事实 | `compare_functions`、`comparison_overview`、`comparison_hotspots`、`comparison_*` | 建立并按需查询 Comparison 数据库 |
| 模块阅读 | `judge_report_create`、`module_analysis_packet` | 以模块为单位读代码，获取节点功能范围和候选函数摘要 |
| 报告写入 | `node_review_bundle_submit`、`module_review_submit`、`overall_assessment_submit` | 宿主 Agent 统一写入中文节点、模块和总体评审 |
| 完成产物 | `judge_report_status`、`provenance_export`、`provenance_render`、`judge_report_validate`、`judge_report_render` | 校验完整性并生成主报告和技术附录 |

补查工具使用边界：

- `node_analysis_packet`：只在模块包信息不足或单节点返工时使用。
- `node_review_draft_batch`：只生成草稿，不写报告；必须由宿主 Agent 审核后再用 `node_review_bundle_submit` 写入。
- `lsp_*`、bash/rg/sed 和 Comparison 查询：用于确认关键符号、调用链和入口定位；`code_atlas_*` 已废弃。
- `evidence_*`、`negative_search`：只注册关键锚点，不为普通 Claim 反复注册。
- `search_similar`：只作临时粗召回，禁止进入 BaseDecision 或报告排名。
- `judge_report_fork_for_comparison`：只在切换 Base/Comparison 时使用，不得用 `judge_report_create` 覆盖旧报告。

## 结构化阶段

### 1. 发现目标不可变快照

1. 调 `repo_snapshots(target)`。默认作品版本是 clone 当前检出分支的尖端，面向用户表述为 `作品@分支`；程序同时记录其 commit 作为整个流程的审计锁。默认响应不返回其他分支，避免占用上下文。
2. 仅当 README、分支命名或内容表明默认分支可能不是最终作品时，才使用 `include_other_branches=true` 分页检查其他唯一分支尖端并改变选择。该接口不遍历历史 commit，并按 commit 合并等价分支别名。
3. 后续 MCP 调用传入选定分支解析出的固定 commit，防止长流程中 ref 移动；报告正文使用 `作品@分支`，commit 仅放入版本与证据详情。
4. 调 `audit_manifest_create(target, ref=<固定 commit>, output_dir=<独立输出目录>)`，固定本次审计的标准产物路径和阶段状态；若用户没有提供目录，使用 `output/<repo-name>/audit-YYYYMMDD-HHMMSS/`。
5. 调 `build_fingerprint(target, ref=<固定 commit>)`。缓存绑定 commit 与指纹 schema，脏工作树不参与；该工具返回的 Scope 只作为 draft suggestion，不是正式 ScopeManifest。

### 2. 确认目标 ScopeManifest

1. 阅读 `.gitmodules`、Cargo workspace、Makefile、README 和目录结构。
2. 判断学生代码、外部依赖、生成物和文档范围；不得只因路径名是 `vendor/`、`third_party/`、`target/`、`build/`、`out/`、`dist/`、`node_modules/` 就排除源码。
3. 对看起来像第三方、依赖或生成代码的目录，必须检查它是否被项目实际引用、是否有依赖声明或生成声明、是否存在学生修改痕迹；可使用 `git log`、`git blame`、`git diff`、`.gitmodules`、Cargo/CMake/Makefile/包管理配置和源码引用关系辅助判断。
4. 先为排除理由注册 EvidenceRecord：源码/配置用 `evidence_source`，文档用 `evidence_document`，结构化范围说明用 `evidence_structured(kind="scope_manifest", ...)`。
5. 调 `create_scope_manifest(target, ref=<commit>, evidence_store=<本项目 evidence_store.jsonl>, ...)`；程序验证路径、submodule 声明和 Agent 排除项引用的 Evidence。
6. 除自动 `.gitmodules` 子模块外，verified ScopeManifest 的排除项必须引用已验证 EvidenceRecord。没有证据的范围只能保存为 draft，不得进入正式搜索。

### 3. 粗召回、候选审核、正式重排

1. `search_similar(...)` 或 `search_formal(..., formal_only=false)` 仅用于粗召回。
2. 审核 Top-20 中缺少 ScopeManifest 的候选，并逐个调用 `create_scope_manifest`。
3. 调 `search_formal(..., formal_only=true)` 正式重排。
4. 报告只展示 `score_kind=formal` 且双方 scope verified 的结果。

### 4. Base 决策

1. 调 `base_evidence_packet(target, ref, formal_candidates, target_year, include_declarations=true)`。
2. Agent 综合正式排名、年份方向、声明验证、核心目录覆盖和差异解释能力选择候选，并调 `evidence_formal_search` 将正式搜索结果写入本项目 EvidenceStore。
3. 提交引用该 evidence ID 的 BaseDecision，调用 `base_decision_submit(decision, packet, output_path=<输出目录>/base_decision.json)`。主 Base 必须按 repo+commit 引用正式候选；校验通过后程序固化 `base_decision.json`。
4. BaseDecision 保持简洁：必须能指向 formal verified 候选并引用正式搜索 Evidence；可写 `selection_reason` 作为 Agent 备注，但主报告中的选择依据仍以后续 `overall_assessment.base_selection_reason` 的中文说明为准。
5. 年份方向是强线索，不是程序硬门槛。xlsx 中有明确更早年份的候选方向性最强；同年候选仍可能存在互抄、共同上游或协作传播，不能仅因同年排除，但必须在主报告中说明方向不确定或给出额外方向依据。对不在 xlsx 的开源教学项目、框架或公开上游，若有声明、公开来源、git 历史或项目关系证据，也可以选择为 Base，但必须在主报告中说明年份表无法校验及替代方向依据。明确更晚年份的候选若被选作主要参考，也必须说明为什么时间表不能直接否定该关系。
6. 对去声明回归，再以 `include_declarations=false` 组包并验证同一决定。
7. 仅当无可靠正式 Base、声明来源均已强制对比且程序准入时，才允许独立报告。

### 5. Comparison 数据库与按需消费

0. `base_decision_submit` 返回 valid 后，Claude Code 立即使用当前上下文里的 `packet.target_snapshot.commit`、`decision.primary_base.repo` 和 `decision.primary_base.commit` 切换源码工作树；`base_decision.json` 只是审计落盘，不是让 Agent 再读一遍的流程输入。执行 `git -C repos/<target> checkout --detach -f <target_commit>` 和 `git -C repos/<base> checkout --detach -f <selected_base_commit>`，必要时清理 clone 中未跟踪垃圾文件后再开始 bash/rg 读代码。不得继续读取未切换的 `repos/<base>` 默认分支。
1. 调 `compare_functions(target=<target>, base=<selected_repo>, ref=<target_commit>, base_ref=<selected_base_commit>, output_dir=...)` 建立主 Base 的完整 ComparisonRun；SQLite 是查询主库，JSONL 是审计导出。
2. Agent 不一次加载全部函数。先调 `comparison_overview` 和 `comparison_hotspots` 获取概要与热点。
3. 用 `comparison_search_units` 按符号/路径定位节点入口，用 `comparison_by_status` 按确定性状态分页抽样。
4. 按需调用 `comparison_directory_summary`、`comparison_directory_sources`、`comparison_file_summary`、`comparison_file_functions` 和 `comparison_base_only_files`。所有列表必须分页；文件可对应多个来源文件。
5. 对关键函数调用 `comparison_function_candidates`、`comparison_detail`、`comparison_call_context` 和 `comparison_source_group`，读取候选来源、调用邻居差异与不可变源码。
6. `MatchEdge` 和 `RelationshipHint` 只是候选关系，不等于整合、拆分、挪用或抄袭结论。
7. 主 Base 的 `raw_status` 只能由程序生成；次级来源通过 `comparison_add_secondary_source` 增加局部候选边，不改变主 Base 统计。

### 6. 按模块形成中文抽象评审

1. 调 `judge_report_create` 创建 `report.json` 骨架；它引用 ComparisonRun 和 EvidenceStore，但不内嵌全部函数对比。该工具默认不覆盖已有报告；切换 Base/Comparison 时使用 `judge_report_fork_for_comparison` 新建待重绑草稿，不在原报告上清空。
2. 整个项目只使用一个全局 `evidence_store.jsonl` 和一个全局 `report.json`。不得给不同批次创建私有 EvidenceStore。
3. `ANALYSIS_BATCHES_V2` 只作为依赖调度参考；实际产物按模块组织。优先调用 `module_analysis_packet(report_path, module_id)`，一次获取模块内全部节点的标题、功能范围、scope、候选函数、已有写入和 `report_generation`。
4. 按模块或强相关模块组开少量 sub-agent。每个 sub-agent 负责读代码、理解功能范围、形成中文草稿；不得直接写共享 `report.json`。
5. 分析任何节点前必须先读 scope。scope 是功能边界，不是证据；它告诉 Agent 该节点应该解释哪类内核功能。
6. 关键调用链优先用带目标 `ref` 的 LSP、Comparison 工具或 bash/rg/sed/cat 确认；直接读源码前必须确认 `repos/<target>` 和 `repos/<base>` 已处于 BaseDecision 刚判断出的 detached commit。普通源码定位可以写入 Claim 文本、文件路径或函数名；只有关键锚点才注册 Evidence。
7. 宿主 Agent 汇总草稿后，为每个节点调用一次 `node_review_bundle_submit(..., expected_generation=<module_analysis_packet 返回值>)` 原子提交 Claims 与 NodeReview。该工具会生成 claim_id 并回填到 review/degree。
8. 每个 NodeReview 必须用中文说明“代码如何实现该功能范围”、与参考作品差异、完整度、原创度和风险。函数、文件和 comparison 不要求机械归属节点。
9. 若节点或模块中发现过测旁路、平台评测特判、公开测例特判或其他硬编码刷分行为，必须在 NodeReview 或 ModuleReview 的风险/差异/完整度说明中明确指出，并尽量锚定到具体文件、函数、条件判断或字符串常量；只有关键结论才注册 Evidence。
10. 完成一个模块后，宿主 Agent 提交 `ModuleReview`。模块页是核心阅读单位，必须把节点事实抽象成模块能力、关键机制链路和实现差异。`overview`、`implementation_summary`、`difference_summary`、`original_work_summary` 可以是中文字符串，也可以是中文字符串数组；当内容包含多个并列机制、多个阶段、第一/第二/第三类结论时，必须提交数组，不要把所有机制堆成一个长段落。
11. 14 个模块完成后，宿主 Agent 提交 `OverallAssessment`。总体摘要、来源关系、Base 选择依据、Scope 排除过程、目录结构解释和架构说明同样遵守上一条：并列条目用数组表达，长解释才用段落字符串。渲染器只按显式数组分条显示，不会根据“第一、第二”、标点或句长自动拆分。
    - `base_selection_reason` 必须用评委能读懂的中文说明为什么选中当前 Base 或为什么没有可靠 Base；应覆盖正式排名/相似度、核心目录覆盖、声明来源、年份或替代方向依据、同年/未知年份候选的方向不确定性、未选择主要候选的原因。不要求写复杂结构。
    - `scope_exclusion_process` 必须用中文概述 Scope 审核和排除过程；应说明排除了哪些主要路径、证据来源、是否检查疑似第三方/生成代码是否被修改或实际引用，以及仍不确定的范围风险。不要求列出全部函数或全部 Evidence。
12. `directory_overview` 必须解释该作品真实目录组织；`directory_notes` 应按目录相对路径写中文说明，例如 `{"kernel": "内核主体，包含调度、内存、文件系统和驱动实现", "xv6-user": "用户态程序与系统调用测试"}`。前端会把说明紧跟在对应目录项后面，不会替 Agent 解释目录含义。
13. 架构部分必须体现该作品的内核独特设计：用中文填写 `architecture_overview`。如提交 `architecture_diagram`，该字段必须是纯 Mermaid 内核架构图源码，不得混入中文解释、段落说明或列表；解释文字必须放回 `architecture_overview` 并在图下方展示。`judge_report_validate/render` 会校验 Mermaid 行级语法，失败时 Agent 必须修改 `overall_assessment` 后重新提交。`architecture_edges` 只作为结构化索引，不是自动绘图输入。每条边至少包含中文 `label` 和非空 `claim_ids`；可选填写 `type`、`source/target` 或 `from/to` 作为自由端点文字，也可选填写 `from_module/to_module`、`module_ids`、`from_node/to_node`、`node_ids` 作为结构化引用。结构化模块必须是 14 个模块 ID，结构化节点必须是 112 个节点 ID。MCP 不会替 Agent 自动绘制、拆句或修复架构图。

### 7. 关键 Evidence 锚定

1. EvidenceStore 固定为当前报告目录下的 `evidence_store.jsonl`，但 Evidence 只作为关键审计锚点，不再要求普通节点每个 Claim 都注册。
2. 必须注册 Evidence 的场景：BaseDecision、Scope 排除、负向搜索、关键继承/独立结论、架构边支撑、模块置顶 Claim。
3. 普通实现说明、普通差异说明和风险提示可以直接写中文 Claim，并附文件/函数/源码位置文字；不要为了填表反复调用 Evidence 工具。
4. 需要注册时优先批量：源码用 `evidence_source_batch`，文件工件用 `binary_artifact/file_artifact`，文档用 `evidence_document`，负向结论用 `negative_search`。
5. Claim 不得编造 evidence_id；只有 MCP 返回的 `evidence_id` 才能作为关键证据锚点。

### 8. 负向搜索

1. 根据节点 scope、MCP 返回的导航提示、Base 符号、目标命名风格和已发现入口构造查询。
2. 调 `negative_search(..., evidence_store=<本项目路径>)` 固定 commit、搜索计划、路径、扩展名、实际查询和扫描文件数。
3. 只有 `coverage_complete=true` 且零匹配才能支撑 `absent`；否则结论为 `uncertain`。

### 9. 校验与渲染

1. 每完成一个模块都调 `judge_report_status`；检查缺失模块、缺失节点、缺失关键 Evidence、缺失中文总评和缺失真实架构说明。
2. 最终再次调用 `judge_report_status`，确认 112 个 NodeReview、112 个节点均有 Claim、14 个 ModuleReview、各模块关键链路、OverallAssessment、架构边、BaseDecision 和产物约束全部完成。
3. 调 `provenance_export` 生成确定性函数溯源数据 `provenance.json`，再调 `provenance_render` 生成独立技术附录 `provenance.html`。
4. 只有 `judge_report_validate` 通过且 `base_decision.json`、Comparison、EvidenceStore、provenance 双产物存在后，才调用 `judge_report_render` 生成评委主报告 `report.html`。
5. `report.html` 由 `web_report/` 的 React + Vite + TypeScript 静态前端投影 `report.json` 生成，不由 Python 拼接业务页面。渲染前必须已存在 `web_report/dist/index.html`；本机首次使用或修改前端后执行 `cd web_report && npm install && npm run build`。页面只展示中文总概述、模块概述、关键链路、完整度/原创度矩阵、节点细节、语言占比、完整目录树和少量关键证据锚点；不展示函数状态内部术语、完整函数列表或全局 Evidence 池。架构图在页面中支持按钮缩放、拖拽平移和重置，但图内容必须仍由 Agent 提交的 Mermaid 内核架构图决定。
6. Evidence 在主报告中放在相关模块/节点页面底部，以彩色证据卡展示。Claim 上的证据按钮只跳转到本页对应证据卡；正文不得平铺全局 Evidence 池。节点没有关键证据时必须由 Agent 在 Claim/Review 中明确说明原因，渲染器不会替 Agent 补证据。
7. `provenance.html` 只展示程序计算的函数匹配、来源候选与源码对照，不生成原创度、实现度或 Agent Claim。
8. 旧混合 `AuditProject/Finding/index.html` 流程已废弃，不得生成或复用。

标准产物目录必须包含：

```text
report.json / report.html
provenance.json / provenance.html
evidence_store.jsonl
audit_manifest.json / base_decision.json
comparison.sqlite / comparisons.jsonl
```

## 真实回归

目标 `oskernel2023-zmz` 应选择 commit `837b6a9...`，并合并 `recover/k210/display/remote HEAD` 等价别名；正式双侧 Scope 搜索应将 `xv6-k210` commit `d7f3e5e...` 排名第一，方向为 `2021 → 2023`。验收按 commit，不按分支字符串。正常模式和隐藏 README 声明模式都必须通过，禁止仓库名硬编码。
