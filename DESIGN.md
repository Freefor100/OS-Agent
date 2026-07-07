# OS-Agent 可审计内核评审系统设计

## 设计定位

OS-Agent 是一套面向操作系统竞赛作品的可审计智能评审基础设施。它不是单次运行的查重脚本，而是把代码指纹、版本锁定、来源发现、函数溯源、证据校验、人工语义判断和中文报告生成组织成一条可复现的审计流水线。

这份设计面向评委展示的不是“我们做了一个相似度工具”，而是“为什么内核赛道真实工作量必须用一套证据化系统来还原”。内核作品天然包含教学框架、硬件抽象、第三方库、往届代码、测试适配和大量样板接口。如果只看仓库规模、通过测试数量或整体相似度，既可能低估真正完成复杂机制的队伍，也可能高估只做包装、移植、改名或刷分的作品。

单纯的 `1-vs-N` 历史作品查重、代码行数统计、仓库元数据扫描和自动风险打分，都可以由比赛平台统一完成。OS-Agent 的设计重点不在重复这些通用能力，而在把平台级底层信号继续向前推进一步：回答选手在既有内核框架之上到底做了哪些增量创新、哪些机制被实质改写、哪些只是继承/适配/包装，以及这些判断能否被逐文件、逐函数、逐证据复核。

系统的核心目标是解决三个传统评审难题：

1. **来源关系难判定**：参赛作品可能同时继承教学内核、开源框架、往届作品、第三方库、论文方案和 AI 生成片段，不能只用一个相似度数字下结论。
2. **混淆手法难穿透**：改函数名、改变量名、拆文件、合文件、批量替换标识符、加虚假注释和格式化都会让普通文件相似度失效。
3. **报告结论难复核**：评委需要中文可读结论，技术复核者需要函数级证据链，两者不能混在同一份不可追溯的自然语言报告里。

因此 OS-Agent 采用“确定性工具给事实，宿主 Agent 做判断，报告系统做准入”的分工。工具负责 Git commit、blob、AST、Scope、Comparison、Evidence 和 schema 校验；Claude Code 负责阅读源码、文档、历史和上下文，形成 BaseDecision、Claim、NodeReview、ModuleReview 与 OverallAssessment。

换句话说，系统用算法做证据发现，用逻辑推理完成裁判解释。暴力检索只能把可疑点摆出来，OS-Agent 要进一步说明可疑点为什么成立、为什么不成立、是否影响真实工作量，以及评委应当如何复核。

## 评委视角的问题

内核赛道评审真正要回答的问题不是“两个仓库像不像”，而是：

1. 选手实际完成了哪些内核机制？
2. 哪些代码来自框架、教材、往届作品、第三方库或生成工具？
3. 哪些改动只是适配、重命名、搬文件、补接口或刷测试？
4. 哪些功能在文档中宣称存在，但代码里只是 stub、空实现或硬编码输出？
5. 如果存在高度相似代码，方向是什么，是合理继承、共同上游、协作传播，还是未声明复制？
6. 在参考 Base 之上，哪些模块体现了结构性改写、机制增强、性能/兼容性改进或新的设计取舍？
7. 最终结论能否被评委和技术复核者按 commit、文件、函数和证据重新验证？

OS-Agent 的设计围绕“真实工作量归因”展开：先剥离公共基座和外部依赖，再识别代码级继承、修改和新增，最后结合文档、Git 历史、测试路径和功能节点给出可审计的实现度与原创度判断。

## 真实工作量的干扰项

内核作品的评审难点在于干扰项非常多，而且很多干扰项看起来像工作量。OS-Agent 将这些干扰项显式建模，避免评委被表面规模、测试输出或文本声明误导。

| 干扰项 | 表面现象 | 对真实工作量的影响 | OS-Agent 的处理 |
|---|---|---|---|
| 教学框架继承 | 仓库有完整进程、内存、文件系统、驱动目录 | 大量代码是公共基座，不应计为选手原创 | Base 发现、Scope、blob/AST 对齐，区分框架继承和学生增量 |
| 第三方库和移植层 | musl、virtio、lwIP、FAT/ext4、测试库等代码量大 | 代码规模膨胀，但主要是集成工作 | ScopeManifest 标注外部依赖，模块评审只评价集成质量 |
| 模板接口和 syscall 桩 | syscall 编号齐全，接口文件很多 | 看起来功能覆盖广，实际可能只是 return 0/ENOSYS | 节点级实现度检查，stub 归为 minimal 或 absent |
| 测试适配和刷分逻辑 | 测试通过数高，输出格式漂亮 | 可能绕过真实执行，不能代表内核能力 | 检查 runner、exec、argv 特判和伪造 TPASS 输出 |
| 路径重组和重命名 | 文件结构和符号名与来源不同 | 人眼难以发现继承关系 | AST shape 穿透改名、拆文件、合文件和格式修改 |
| 文档包装 | 设计文档宣称完整机制、原创设计或未使用 AI | 文档可能夸大、遗漏或与代码不一致 | 先读文档，再逐项核对代码和 Git 证据 |
| AI 批量生成 | 首次提交出现大量成型模块，注释和 commit 风格统一 | 产物质量可能高，但人类设计和调试工作量不明 | AI 参与结构化判断，比较声明和仓库事实 |
| 风格化代码误读 | 低水平实现、模板注释、批量 syscall 适配和统一格式看起来“像生成” | 容易把能力不足、赶工补接口或团队规范误判成来源问题 | 回到提交历史、代码演化和具体机制实现，而不是凭风格下结论 |
| 多来源拼装 | 不同模块来自不同项目或公开上游 | 单一 Base 无法解释全部来源 | 主 Base 负责骨架，次级来源和模块来源单独记录 |
| 同届传播 | 两个参赛作品高度相似且年份相同 | 相似度不能直接给方向 | Git 时间线、首次出现时间、提交形态和共同上游复审 |
| 生成物和构建产物 | target/build/generated 目录含大量代码 | 容易污染相似度和代码量统计 | Scope 审核排除，但不能只凭目录名硬排 |

因此，OS-Agent 的每个设计点都服务于一个评审目标：把“仓库里有什么”进一步拆成“学生真正设计、实现、调试并可解释的是什么”。

## 总体架构

```text
用户显式指定 作品@分支
→ bash 校验目标仓库当前分支和干净工作树
→ audit_manifest_create 锁定 commit 与产物目录
→ build_fingerprint 构建 Git blob / AST shape / 汇编块指纹
→ create_scope_manifest 固化学生代码范围与排除证据
→ search_formal 执行正式 1-vs-N 双侧 Scope 搜索
→ base_evidence_packet 汇总声明、年份、排名和覆盖事实
→ Agent 提交 BaseDecision，base_decision_submit 程序准入
→ compare_functions 建立双向函数级 Comparison 数据库
→ Agent 分模块阅读源码、文档、Git 历史和 Evidence
→ node_review_bundle_submit / module_review_submit / overall_assessment_submit
→ judge_report_validate 完整性、证据、中文质量和 schema 校验
→ report.html 面向评委，provenance.html 面向技术复核
```

这条链路中，所有关键判断都绑定到不可变 commit。分支只是入口，系统在开始审计时解析为具体 commit，并在后续 Evidence、Comparison、LSP 和报告渲染中持续校验。这样可以避免长时间分析期间分支移动、工作树改动或默认分支漂移污染结果。

## 职责边界

| 层级 | 责任 | 不负责 |
|---|---|---|
| Git / 指纹层 | 锁定 commit、枚举 tree、读取 blob、生成 AST shape hash 和汇编 block hash | 判断原创度和实现度 |
| Scope 层 | 固化学生代码范围、外部依赖、生成物和文档目录 | 用目录名直接替代证据 |
| 搜索层 | 1-vs-N formal 检索、候选覆盖状态、粗召回隔离 | 把 rough 结果写入报告排名 |
| BaseDecision 层 | 程序准入所选 Base 必须来自 formal 候选 | 替 Agent 决定来源方向 |
| Comparison 层 | 双向函数匹配、状态枚举、多来源 MatchEdge、SQLite 查询 | 覆盖 Agent 对语义差异的解释 |
| Evidence 层 | 验证源码、文档、链路、负向搜索和审计证据 | 接受未经校验的自然语言引用 |
| Report 层 | 112 节点、14 模块、总体评估、中文报告和技术附录 | 允许模板化灌水或字段漂移 |
| Claude Code Skill | 固化操作流程、质量红线和实战判断方法论 | 自动替代宿主 Agent 判断 |

声明、glossary、vocab、Node Scope 和相似度都只是判断材料，不能单独支撑实现度、原创度、作弊或抄袭结论。

## 核心设计：从代码规模到贡献归因

OS-Agent 的核心设计不是追求更高的相似度分数，而是把内核作品拆成可归因的工作量单元。每个技术选择都对应一种评审干扰：blob 解决逐字节来源，AST 解决改名混淆，Scope 解决外部依赖污染，Comparison 解决函数级继承和新增，Evidence 解决结论可复核，报告 taxonomy 解决完整框架下的实现度判断。

| 平台可统一完成的底层能力 | OS-Agent 进一步完成的评审能力 |
|---|---|
| 全库 `1-vs-N` 相似度排序 | 解释相似度来自公共基座、外部依赖、同届传播还是学生增量 |
| 黑箱风险打分或标签 | 转化为可复核审查问题，用提交、文件、函数、文档和演化历史解释风险来源 |
| 代码行数、文件数、语言占比 | 剥离框架和生成物后，统计并解释学生实际改动区域 |
| 仓库元数据和提交列表 | 分析首次导入、渐进开发、返工修正、测试适配和证据销毁风险 |
| 单点文件相似或 hash 命中 | 建立函数级 Comparison，说明继承、改名、重写、删除和新增机制 |
| 单点风险标签 | 形成 14 模块、112 节点的实现度、原创度和增量创新评审 |

因此，OS-Agent 的产出不是“发现某作品像某作品”或“某段代码风险分很高”，而是给评委一份可复核的增量贡献说明：该队继承了什么，真正改了什么，新增了什么，哪些机制只是表面支持，哪些地方体现了实质设计和工程投入。

### 1. 三层比对的反混淆体系

OS-Agent 将查重拆成三层事实，而不是依赖单一相似度：

| 层级 | 指标 | 作用 |
|---|---|---|
| 文件级 blob | Git tree 中的 blob SHA-1 | 识别逐字节复制、fork、路径搬移和框架继承 |
| 函数级 AST shape | tree-sitter 提取函数语法结构并哈希 | 穿透函数名、变量名、注释、格式和文件重组 |
| 语义上下文 | 路径角色、调用邻居、同名关系、Git 时间线、文档声明 | 解释方向、来源类型、真实工作量和混淆动机 |

blob 是高置信铁证，但容易被改名和重排规避；AST shape 对结构高度敏感，对命名和排版不敏感，能识别“换皮式”重命名和拆文件；语义上下文负责回答“为什么像、谁更可能来自谁、哪些是共同上游、哪些是学生增量”。

当出现 `blob` 显著低于 `AST` 的情况，例如 blob 60% 但 AST 83%，系统将其视为系统性混淆信号，而不是简单降低风险。Agent 必须在报告中解释 blob 和 AST 的差距来自改名、拆分、合并、批量替换、虚假注释还是格式修改。

这个设计直接服务于真实工作量判断：如果函数结构没有变化，只是换名、搬路径或重排文件，就不能把这些操作当作新的内核机制实现；如果 AST 发生真实结构变化，才进入后续语义评审，判断它是功能增强、适配修改还是局部修补。

### 2. Base 发现与差异评审解耦

Base 是解释主要公共骨架的参考锚点，不等于作品全部来源。多来源作品可能以某个教学内核为框架，同时吸收往届模块、开源驱动、Linux ABI、论文方案或 AI 生成代码。

设计上分两步处理：

1. **BaseDecision** 只选择主骨架锚点，用于建立稳定的全局 Comparison。
2. **模块评审** 继续记录次级来源、外部依赖、设计参考、AI 参与、刷分风险和独立新增工作。

这样避免把一个复杂作品粗暴压缩成“基于 A”或“抄 B”，也避免在没有主参考系的情况下生成不可比较的主观报告。

对评委来说，这意味着报告不会把公共框架误算成原创，也不会因为作品存在基座就否定全部增量。系统先建立公平参照系，再逐模块说明选手在哪些机制上有实质改动、哪些只是继承或适配。

### 3. 函数级溯源数据库

主 Base 固化后，系统建立完整 ComparisonRun。SQLite 保存 Units、ComparisonRecords、MatchEdges、RelationshipHints 和分页聚合视图，JSONL 保留审计导出。

函数状态由程序生成，Agent 只能解释，不能覆盖：

| 状态 | 含义 |
|---|---|
| `exact_copied` | 同名且 AST shape 完全一致 |
| `renamed_exact` | 名称不同但 AST shape 完全一致 |
| `modified_candidate` | 多信号唯一候选，等待语义解释 |
| `target_only` | 目标新增 Unit |
| `base_only` | Base 中存在、目标没有确定性匹配 |
| `ambiguous` | 多个近似或精确候选，需要复核 |

同名本身不足以产生 `modified_candidate`。`raw_status` 是工具事实，报告中的原创度和实现度必须围绕这些事实展开。

函数级数据库让“工作量”不再停留在文件数量和总代码行数。评委可以看到某个模块到底是大量 `exact_copied`、少量 `modified_candidate`，还是存在真正的 `target_only` 机制；技术复核者也可以反向检查 Base 中哪些能力被删除、保留或重写。

### 4. Evidence 驱动的报告准入

OS-Agent 不允许把“我看过代码觉得如此”直接渲染成最终结论。重要 Claim 必须绑定 EvidenceRecord，EvidenceStore 会校验：

- 源码证据是否来自锁定 commit。
- 工作树 HEAD 是否等于审计 commit 且干净。
- 文档证据、正式搜索证据、负向搜索证据和 scope 排除证据是否结构化。
- `not_found` 是否满足路径存在、eligible 文件非空、无读错误、零匹配和 `coverage_complete=true`。
- 比较型 Claim 是否有双侧证据。
- 独立新增或未实现结论是否有正式搜索或完整负向搜索支撑。

所有批次共享一个 `evidence_store.jsonl` 和一个 `report.json`。节点工作者通过 `node_review_bundle_submit` 原子替换单节点 Claims 与 NodeReview，避免并发写入互相覆盖和旧结论残留。

这套准入机制保证最终展示给评委的不是无法复查的主观印象，而是“结论 + 代码位置 + 函数关系 + 负向搜索 + 文档核验”的组合证据。它尤其适合处理内核赛道常见的争议场景：功能是否真的实现、是否只是测试特判、是否为外部库、是否继承自共同上游。

## 实战方法论沉淀

Skill 是 OS-Agent 的经验层，它把实际评审中反复踩坑的判断规则固化为操作规范。设计文档将这些经验上升为系统能力。

### 共同基座识别

不能直接拿候选排行榜第一名当 Base。Agent 必须综合：

- README、PDF、设计文档中的基座声明。
- Git 首次提交、submodule、fork 痕迹和引入时间。
- blob 级三方对比：目标 vs 基座、候选 vs 基座、目标 vs 候选。
- AST 级函数重合和路径重组情况。
- 领域知识中的典型框架文件、模块布局和版本演进。

关键判断是：若目标和同届候选互比明显高于各自对共同基座的相似度，超出的部分往往是基座之外的共享增量，需要进入传播方向复审。

### 时间线定方向

相似度没有方向。方向来自年份、声明、公开上游关系、Git 历史和具体片段的首次出现时间。

对同届高相似候选，Agent 必须检查：

- 首次 commit 是否批量导入大量非框架源码。
- 文件数曲线是渐进开发还是单次跳跃。
- 高相似文件在双方历史中的首次出现时间。
- commit message、作者、提交形态和 Revert 链。
- 文档声明、删改记录和第三方公开来源。

报告只给概率性分类：目标更可能吸收候选、候选更可能吸收目标、双方共同参考第三方、协作/共享代码传播，或证据不足。不能仅凭同年排除，也不能仅凭同年建立方向。

### AI 参与识别

AI 参与不是靠作者声明单点判断，而是“文档声明”和“仓库事实”的一致性问题。

系统要求 Agent 同时读取 README、PDF、设计文档、AI usage 文件、`.claude/`、`.cursor/`、`AGENTS.md`、`CLAUDE.md`、`CODEBUDDY.md` 和 prompt 目录，并结合 Git 历史判断：

- 文档是否声明 AI 使用。
- 声明范围是否与 commit 证据一致。
- 是否存在 Co-Authored-By、emoji conventional commit、英文批量提交、AI agent 配置或对话残留。
- 首次提交是否一次性出现大量非框架原创代码。
- 是否存在真实调试、返工、修正和渐进理解痕迹。

`ai_participation` 必须是结构化对象，包含声明来源、commit 证据、代码模式、综合 assessment 和置信度。未声明 AI 或声明程度低于事实，按隐匿 AI 风险记录。

OS-Agent 将 AI 参与证据按可追溯性和解释力分级，而不是把所有“像 AI”的现象混成一个概率。分级只表示证据强度，不表示惩罚等级；最终仍要结合竞赛规则、作者披露情况和真实工作量判断。

| 证据强度 | 证据类型 | 说明 |
|---|---|---|
| 100% 确定性证据 | `Co-authored-by` / `Generated-by` / commit 正文明确写明 Claude、Opus、Sonnet、Copilot、Codex、DeepSeek、GLM、Kimi 等模型或工具参与 | 这是直接来源证据，可精确追溯到 commit、作者、时间和具体变更 |
| 100% 确定性证据 | 仓库存在 `AGENTS.md`、`CLAUDE.md`、`CODEX.md`、`.claude/`、`.cursor/`、prompt、handoff、AI 操作日志等，并且内容是给 AI agent 的约束、任务分工或执行记录 | 这是工具使用环境证据，说明仓库开发流程中配置了 AI agent |
| 100% 确定性证据 | README、设计文档、AI usage 文档、答辩材料或提交说明中自述 AI 参与 | 这是作者披露证据；重点是核对披露范围是否与仓库事实一致 |
| 99% 强证据 | commit message 大量 emoji + conventional commit，且风格高度一致 | 例如连续出现 `✨ feat:`、`🐛 fix:`、`📚 docs:` 等。这是 Claude/Copilot/Codex 常见输出风格，但仍需排除团队人为统一规范 |
| 80% 强风险证据 | commit message 长期保持 `feat:` / `fix:` / `docs:` / `refactor:` + 英文祈使句 + 多条 bullet 说明，粒度稳定、句式高度一致 | 这是典型 Claude Code / Codex 代理式提交形态。若伴随短时间大规模模块落地、缺少调试返工，风险显著升高 |
| 80% 强风险证据 | 首次或早期 commit 一次性导入完整非框架项目骨架，包含 Cargo/Makefile/CI/多模块内核代码和详细注释 | 若不是导入公开基座，而是原创模块一次成型，通常说明 AI 或外部生成流程高度参与 |
| 50% 弱风险证据 | 注释呈现统一解释性语气、分条 `1/2/3/4`、中英双语规整、每个函数都有“教科书式说明” | 这类风格可能来自 AI，也可能来自低水平学生照模板写，必须降权使用 |
| 50% 弱风险证据 | 代码结构过度整齐、错误处理模板化、接口批量补齐、缺少真实调试痕迹 | 只能说明生成式/模板化风险，不能单独证明 AI 参与 |

这套分级的优势是可解释：每个结论都能指向具体 commit、文件、文档、配置或代码片段。相比“黑箱概率很高”，评委可以复核证据本身：是谁提交的、什么时候提交的、文件里写了什么、声明和事实是否一致。

同时，弱证据必须避免过度解读。学生水平低、照教程写、赶工补 syscall、统一使用模板注释，也会产生“像 AI”的风格。OS-Agent 只把这些现象作为风险提示；只有当弱风格证据与确定性证据、提交历史、AI 配置、文档披露不一致等多项证据汇合时，才提高 `ai_participation` 置信度。

### 为什么以逻辑推理替代暴力判别

内核赛道的评审对象不是孤立代码片段，而是一个长期演化的工程系统。简单暴力算法擅长发现“相似”“异常”“高概率”这类线索，但它们不会回答评委真正关心的问题：相似来自共同基座还是未声明复制，异常来自真实创新还是临时刷分，高概率风格来自 AI 参与还是低水平模板化实现。

OS-Agent 的设计把算法输出限制在“事实发现”层，把裁判级结论放在“证据推理”层。平台可以先给出候选、分数、命中片段和风险标签；系统随后按照固定推理链继续追问：

1. **来源链**：这段代码最早出现在哪里，是否属于公开基座、第三方库、往届作品或同届传播？
2. **变化链**：相似函数是逐字节复制、改名、局部修补、结构重写，还是目标仓库独立新增？
3. **时间链**：相关文件是在首次提交一次性导入，还是伴随调试、返工、测试失败和修复逐步演化？
4. **声明链**：README、设计文档、AI usage、commit message 和实际仓库事实是否一致？
5. **功能链**：文档宣称的机制是否真的落到调度、内存、文件系统、驱动、syscall、兼容层等代码路径中？
6. **贡献链**：剥离公共框架和依赖后，学生真正完成的增量设计、接口适配、机制改造和工程修复是什么？

这种推理式设计更适合面向评委展示工作量。它不是把作品压缩成一个分数，而是把争议点拆成可复核问题：证据在哪里，方向如何判断，哪些结论确定，哪些结论只是不足以采信的风险提示。最终报告呈现的是“判断过程”，不是“黑箱标签”。

因此，OS-Agent 的价值不在于替代平台跑更多暴力检索，而在于把自动化线索组织成评委能理解、能质询、能复核的审计逻辑。对优秀作品，它能说明增量创新具体发生在哪些机制；对包装型作品，它能说明表面规模为何不能等同真实工作量；对争议作品，它能给出证据链而不是只给一个不可解释的概率。

### 刷分与造假检测

OS-Agent 把“实现功能”和“伪造测试输出”区分为独立风险。Agent 必须读取测试运行器、init、contest runner、LTP 桥接层和 syscall 分发路径，检查：

- 不执行测试而直接打印 `TPASS` / `Pass!`。
- 针对测试名硬编码成功输出。
- synthetic lib、bridge case、compat test 等虚假执行路径。
- syscall 或 exec 路径按 argv 特判测试程序。
- 截止日前引入或删除作弊代码、日志和设计文档。

发现造假时，`source_relation` 必须新增 `type="fabricated_output"` 条目，并在总体风险中明确区分全系统级测试造假、单点刷分和普通输出重格式化。

## 主要模块

| 模块 | 责任 |
|---|---|
| `core/snapshot.py` | 解析指定 commit、tree hash 和 ref aliases，避免依赖移动分支 |
| `core/git_source.py` | 从 Git commit 直接枚举 tree、批量读取 blob 和源码片段，不 checkout、不复制源码树 |
| `core/scope.py` | 构建、验证和持久化 ScopeManifest，记录 included、excluded、generated 和 documentation 范围 |
| `scripts/fingerprint.py` | 从 Git blob 构建 Unit、blob set、AST shape set、汇编 label-block exact hash 和语言统计 |
| `tools/code_atlas/` | tree-sitter 加载、AST shape 提取、汇编 token 化和 MinHash 支撑 |
| `core/scoped_search.py` | 双侧 Scope 搜索，区分 rough 和 formal，支持候选 `auto_candidate` 范围 |
| `core/base_decision.py` | 生成 BaseEvidencePacket，校验 BaseDecision 来自 formal 候选 |
| `core/comparison.py` | 双向函数匹配、候选边构建、状态分类和多来源扩展 |
| `core/comparison_db.py` | SQLite 查询层，提供 overview、hotspots、目录、文件、函数、来源反查和分页 |
| `core/evidence.py` | EvidenceCandidate 校验、稳定 ID、工作树校验和负向搜索约束 |
| `core/kernel_tree.py` | 14 模块、112 节点的评审分类体系和分析批次 |
| `core/judge_report.py` | Claim、NodeReview、ModuleReview、OverallAssessment、并发锁和完整性校验 |
| `core/provenance_report.py` | 导出技术复核用函数溯源 JSON 和 HTML 数据 |
| `scripts/judge_report.py` | 校验 report.json，整理前端 view-model，注入 React 静态资源 |
| `scripts/provenance_report.py` | 生成独立的函数级溯源附录 |
| `tools/lsp_ops.py` | 在锁定 worktree 上提供定义、引用、调用链和编译上下文辅助 |
| `mcp_server.py` | 向 Claude Code 暴露结构化阶段接口，是 Agent 与确定性工具的边界 |
| `web_report/` | React + Vite + TypeScript 主报告前端，展示模块、节点、证据卡、目录树和 Mermaid 架构图 |

## 数据与产物

每次审计使用独立输出目录，默认 `output/<repo>/`。标准产物平铺放置：

```text
audit_manifest.json      本次审计的锁定版本、产物路径和阶段状态
base_decision.json       程序校验通过的 BaseDecision 与证据包
comparison.sqlite        函数 Comparison 主查询库
comparisons.jsonl        Comparison 审计导出
evidence_store.jsonl     全局共享的稳定证据记录
report.json              Agent Claim、节点、模块和总体评审
report.html              面向评委的中文主报告
provenance.json          技术复核数据
provenance.html          面向技术复核的函数溯源附录
assets/                  前端静态资源
```

`repos/`、`.fp_cache/`、`output/`、`tmp/` 和 `.claude/settings.local.json` 是本地状态，不进入 Git。`.claude/mcp.json` 是个人本地配置，由 `.claude/mcp.json.example` 复制，不提交绝对路径。项目只提供一个 Claude Code Skill：`.claude/skills/os-agent/SKILL.md`，设置 `disable-model-invocation: true`，执行审计时必须由用户显式调用 `/os-agent`。

## 报告体系

### 评委主报告

`report.html` 面向评委，以作品名和参考作品名表达，不把内部工具术语暴露为主叙事。它的核心价值是展示“真实工作量账本”：哪些能力是公共基座，哪些是外部依赖，哪些是选手做了实质设计和实现，哪些只是接口、适配、包装、改名或测试规避。风险标签只用于帮助定位问题，主报告的重心始终是选手在 Base 之上的增量创新、机制改写和工程投入。

它展示：

- Base 选择依据和 Scope 排除过程。
- 中文总体结论、AI 参与判断、来源关系和风险项。
- 14 个模块、112 个节点的实现度、原创度和关键差异。
- 参考 Base 之上的新增机制、重写路径、关键设计取舍和未完成边界。
- 目录树、语言占比、架构 Mermaid 图和关键 Evidence 卡片。
- 作弊、刷分、隐匿 AI、声明不实、功能夸大等高风险结论。

报告正文必须来自实际阅读，不允许模板化灌水。每个节点至少锚定真实文件、函数、结构体、syscall、设备、配置项、缺失事实或 Comparison/Evidence 关系。`not_applicable` 节点保持短说明，避免为不存在的功能写长篇解释。

评委阅读路径按“先结论、再来源、再模块、最后证据”组织：先看总体工作量和风险，再看 Base 与干扰项排除，再进入模块级实现度和原创度，最后用 Evidence 卡片和技术附录复核争议点。

### 技术溯源附录

`provenance.html` 面向技术复核，独立展示：

- 确定性函数状态。
- 目标文件的多个来源文件。
- Base 未匹配函数。
- 函数候选、源码对照和来源反向拆分视图。

它不生成原创度、实现度或自然语言 Claim，只提供可复核的函数级事实。

## 关键不变量

1. **用户必须显式指定待查重分支**。没有分支就不启动分析。
2. **分析开始前必须确认目标仓库当前检出分支正确且工作树干净**。
3. **所有阶段绑定同一个 target commit 和 selected base commit**。
4. **rough 搜索只用于导航，禁止进入 BaseDecision 和报告排名**。
5. **正式搜索要求目标 ScopeManifest 为 `verified`**，候选缺失 Scope 时只使用确定性 `auto_candidate`。
6. **BaseDecision 必须来自 formal 候选并通过程序准入**。
7. **Comparison 的 `raw_status` 只能由程序生成，Agent 不得覆盖**。
8. **Evidence 必须由 EvidenceStore 验证后才能进入 Claim**。
9. **负向搜索只有覆盖完整且零匹配时才能支持 `not_found`**。
10. **所有节点、模块和总体评估写入同一个 report.json**。
11. **报告渲染前必须通过 `judge_report_validate`**。
12. **测试和临时脚本只属于本地开发行为，不构成交付产物或证据来源**。

## 工程运行模式

Claude Code 是分析主体，可以使用 bash、rg、sed、Git、LSP 和 MCP 查询代码。正式分析前，Agent 用 bash 执行：

```bash
git -C repos/<target> branch --show-current
git -C repos/<target> status --porcelain
git -C repos/<target> rev-parse HEAD
```

确认通过后再创建审计目录和构建指纹。BaseDecision 校验通过后，Agent 将目标和 Base worktree checkout 到对应 detached HEAD，用同一组 commit 阅读源码、注册 Evidence 和构建 Comparison。Evidence 注册入口会再次校验 HEAD 与工作树状态。

缺少编译数据库时，LSP 层可以临时生成带 OS-Agent 管理标记的 `compile_flags.txt`。该文件只服务于交互式代码理解，不参与指纹、Scope、Comparison、Evidence 或报告产物，并在 clangd 客户端退出、MCP 退出或下次分析启动前清理。

## 质量门禁

OS-Agent 的质量门禁同时约束事实、结构和表达：

- schema 必须是 `judge_report_v1`。
- 顶层必须包含 work、reference、taxonomy、claims、node_reviews、module_reviews、overall_assessment、evidence_store 和 provenance_href。
- 112 个节点、14 个模块必须完整。
- `implementation_degree` 和 `originality` 必须使用枚举值，不能写自然语言或浮点分。
- `ai_participation` 必须是结构化对象，不能是字符串占位。
- `source_relation` 必须是结构化对象数组，作弊造假使用 `fabricated_output`。
- 模块和节点正文必须有具体代码事实，不能复用套话。
- Mermaid 架构图必须体现真实模块、文件、函数和调用关系。
- 最终 HTML 必须通过命令行渲染验证。

这些门禁的目标不是让报告更复杂，而是让每个结论都能回答：依据是什么、来自哪个 commit、由谁判断、工具校验了什么、评委如何复核。

## 典型回归

`oskernel2023-zmz@837b6a9` 的双侧正式搜索应将 `xv6-k210@d7f3e5e` 排名第一，方向为 `2021 → 2023`。验收按 commit，不按分支字符串。即使隐藏 README 声明，系统仍应依靠 blob、AST、Scope 和正式搜索得到同一主 Base。

这个回归体现 OS-Agent 的底线：声明可以帮助判断，但不能替代代码事实；相似度可以提供线索，但必须落到可审计的版本、范围、函数和证据链上。
