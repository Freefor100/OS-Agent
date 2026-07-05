---
name: os-agent
description: 使用 os-agent MCP 分析 repos/ 下操作系统竞赛作品的来源关系、实现完整度、原创度和实现差异，并生成中文评审报告。
disable-model-invocation: true
---

# OS-Agent Skill：可审计 Base 发现与差异报告

## 触发方式

用户显式执行 `/os-agent <作品名> <待查重分支>` 时启动本 Skill。分支必须显式给出；若用户没有给待查重分支，停止并询问分支，不得默认使用当前分支。若用户只说"分析某作品"但没有给输出目录，自动使用 `output/<repo-name>/`。

开始时只向用户确认三件事：目标作品、待查重分支、输出目录。不要要求用户理解 BaseDecision、Comparison、EvidenceStore、report_generation 等内部概念。

## 原则

宿主 Agent 负责判断；本地工具只做版本锁定、范围校验、确定性搜索/比较、关键证据锚定和报告投影。最终 `report.html` 必须是中文报告；必要机制名可在中文后用括号补充解释，例如"多级反馈队列（MLFQ）""写时复制（copy-on-write）"。

- 开始分析前确定独立输出目录；若用户未指定，自动使用 `output/<repo-name>/`，并在开始时告知用户。随后先用 bash 确认 `repos/<target>` 当前检出分支就是待查重分支且工作树干净，再调用 `audit_manifest_create` 创建本次分析唯一的 `audit_manifest.json`，该目录固定保存 `base_decision.json`、`report.json`、`report.html`、`provenance.json`、`provenance.html`、`evidence_store.jsonl`、Comparison 数据库和 `assets/`。所有产出物统一放置在同一个平层目录下。
- 预建指纹阶段不得仅凭目录名硬排除 Git tracked 的支持语言源码；看起来像依赖、生成物或外部代码的路径只能作为 Scope 审核线索，不能替代证据裁决。
- 分支只是入口；多个别名指向同一 commit 时只分析一次。
- `search_similar` 是内部粗召回，禁止用于报告排名或 BaseDecision。
- 正式搜索必须使用目标作品 verified ScopeManifest；候选缺少 ScopeManifest 时由程序生成确定性的 `auto_candidate` 轻量范围，不要求 Agent 为 Top-K 候选逐个补 Scope 证据。
- 声明是强线索，不自动成为 Base；声明来源必须正式对比。
- Base 是解释主要公共骨架的参考锚点，不等于作品全部来源。参赛作品可能是在某个系统上演进，也可能同时参考多个开源内核、往届作品、Linux ABI/man-pages、Zircon/Fuchsia object model、论文方案、测试脚本或 AI 生成片段；Agent 必须在阅读文档和代码时判断多来源组成、各模块参考关系和真实工作量。
- 同届候选只进入复审区，不能仅凭年份作为有方向性的主 Base；若同届候选与目标存在高相似核心代码，Agent 必须结合相似片段的 Git 历史、文档声明和第三方来源线索，推测互抄、共同外部参考、协作传播或方向不明的可能性。
- 参赛年份、学校、队伍和是否在参赛表内，统一通过 MCP 工具返回的元数据消费；不要直接读取或解析 `collected-data.xlsx`。
- Agent 临时脚本和一次性中间文件默认不要创建；当 Claude Code 写大段 JSON 容易触发 Write tool error，或需要本地批量校验/整理草稿时，可以在项目根 `tmp/` 放临时脚本。临时脚本只用于生成、修复、格式化或校验待提交 JSON 草稿；最终写入仍必须通过 MCP 的 `node_review_bundle_submit`、`module_review_submit`、`overall_assessment_submit` 等正式接口完成。不要写入 `scripts/`、`core/`、`repos/`、`output/` 或系统 `/tmp`。`tmp/` 内容不得作为 Evidence、Scope、BaseDecision、Comparison 或报告产物来源。
- Node Scope 是语义边界，不是函数路由规则，也不能单独作为查重证据。
- Agent 可解释 `modified_candidate`，但不得覆盖 `raw_status`。
- 报告优先面向评委阅读，避免堆砌工具术语，使用行业常见专业用语；所有概述、模块总结、节点说明和架构边标签必须使用中文。

## 查重方法论

### 三层比对体系（按优先级）

1. **blob hash（文件级，最快）**: `git ls-tree -r HEAD` 取每个源文件的 SHA-1 哈希。两 repo 同一文件的 blob 相同 = 逐字节完全一致。不依赖任何 parser/normalizer，跨 repo 天然稳定。适合判断"是否来自同一个代码库"。

2. **AST shape hash（函数级，核心指标）**: tree-sitter 解析每个函数的语法树结构后 SHA-256。只比函数签名、分支结构、子调用关系，不关心变量名和文件路径，是 `search_formal` 的 `combined` 主要指标。

3. **blob + AST 联合判断**：
   - blob 覆盖 >90% → 同一代码库 fork
   - AST combined pairwise ≈ AST(作品, 基座) → 框架共享，非互抄
   - AST combined pairwise >> AST(作品, 基座) → 可能存在同届增量共享 → 需 git timeline 验证

4. **文件路径重组不等于原创**：如果两件作品的同一函数体文件路径不同但 blob hash 相同——代码是被搬移而非重写。报告应如实说明"路径重组非原创"。

5. **AST 可穿透改名/拆文件混淆**：掩盖抄袭的常见手法（改函数名、改变量名、拆大文件为小文件、合并小文件、标识符批量替换如 pulse_core → oskernel_core、加虚假注释、改空格格式），blob hash 会因这些变更而不同，但 **AST shape hash 只比结构不比名字**，能穿透改名和拆分。具体场景：
   - **改名不改结构**：函数体完全一样但改了函数名/变量名 → blob不同但AST相同 → 抄袭铁证
   - **拆文件**：同一逻辑单元被拆成N个小文件 → blob全是新的，但 AST 函数指纹在两边匹配 → 代码是从源头被物理拆分的
   - **合文件**：多个函数合并到一个文件 → 同样判断
   - **标识符批量替换**：纯字符串替换（如 pulse_core → oskernel_core），AST 结构不变 → blob 不同但 AST 精确匹配
   - **虚假注释/格式修改**：加注释/改空格/改行尾 → blob 不同但 AST 相同
   
   实际案例（T2026104869910069-16 振兴三连队抄袭 PulseOS）：384 对标识符重命名 + 文件拆分重组 + 虚假 REFERENCE 注释 + 包重命名，三层掩盖全部被 AST 揭穿——blob 60% vs AST 82.8%。12 个关键函数全部 NOT FOUND。

6. **blob+AST 联合反混淆**：当 blob pairwise 明显低于抄袭阈值（如 40-70%），但 AST 相似度远高于 blob（如 blob 60% vs AST 83%），说明存在改名/拆分/格式化等混淆。若 AST > blob + 20%，必存在系统性掩盖手段。每多一层混淆，blob-AST 差距就扩大一级。

### 同届高相似度的判断流程

1. 排除框架代码和外部依赖的相同 blob
2. 看剩余的相同文件：是学生原创代码吗？
3. 如果是学生原创代码且高度相同 → 抄袭
4. 如果剩余文件完全不同 → 各自独立开发，只是用了同一框架

### 代码分层（三层分解）

读代码时的固定分析框架：

1. **blob 对比找相同文件**：这些是框架代码还是学生原创？与上游框架对比验证
2. **blob 对比找不同文件**：不同文件 = 真正的学生工作量差异
3. **git log 看变动**：哪些文件被修改？修改了什么？commit 历史是否显示迭代开发？
4. **结合文档声明**：学生说自己做了什么？与代码实际匹配吗？

分三层写入 `source_relation`：
- **第一层 框架/基座**：与上游框架 blob 匹配的文件。两个作品都基于同一框架时，这层高度重叠是正常的，不代表抄袭
- **第二层 外部依赖**：第三方库（musl、virtio-drivers、ext4 parser等）。多个作品独立引入同一依赖也会产生相同 blob，不代表抄袭
- **第三层 学生原创**：独有文件 + 修改过的文件。这是真正的学生工作量，**重点分析这层**

## AI 参与判断

### AI 参与的独立证据（无需作者声明也可判定）

- **commit message 模式**：大量使用 emoji + 英文 conventional-commit（`📃 docs:` / `✨ feat:` / `🐛 fix:`）是 Claude/Copilot 的标准输出，中文团队手动提交不会采用此格式
- **代码注释风格**：中英双语混排注释、双语言空格纠错、`REFERENCE:` 超链接注释——均为 AI 生成特征。单一文件内注释语言风格跳跃为 Vibe Coding 指标
- **单体文件批量导入**：首次或早期 commit 含完整项目骨架（Cargo.toml + CI + 多模块代码同时导入），而非渐进式添加
- **遗漏的 AI 对话日志**：仓库中残留 `object.txt` / `start.md` / `codex-handoff-mistakes.md` 等文件含 AI 自述语句
- **`AGENTS.md` / `CLAUDE.md` / `.claude/` / `.cursor/`** 文件直接证明 AI agent 参与

### 隐匿AI的判断

隐匿AI ≠ 没声明AI。隐匿AI = **文档声明与commit证据不一致**。

判断流程：
1. 先读所有文档（PDF + README + 设计文档），提取 AI 声明内容
2. 再查 git log（Co-Authored-By、commit message 模式、首次提交规模）
3. 再查 repo 文件（CLAUDE.md、AGENTS.md、.claude/、.cursor/）
4. **对比**：文档说的 vs commit 证据 → 一致还是矛盾？
5. 如果矛盾 → 隐匿AI，在 assessment 中明确指出矛盾点

具体场景：
- PDF/README 说"纯人工开发"但 commit 中有 Co-Authored-By: Claude 行
- 文档声称"仅用AI做代码审查"但 commit 显示 AI 生成了大量初始代码
- 完全没有提及AI使用，但 repo 中存在 CLAUDE.md / AGENTS.md / .claude/ 配置目录
- AGENTS.md 有详细的 attribution 规则和模型配置，但所有公开文档避而不谈
- **首次 commit 包含大量非框架的原创代码文件**：整个项目骨架一次性提交，不是迭代开发，不是框架导入。关键区别：导入 xv6/RT-Thread 等框架的批量文件是正常的框架初始化；但自己写的内核代码（非框架）第一次就提交完整项目结构 → AI 批量生成的特征

`ai_participation.declared` 定义：
- **true**: 文档中明确声明了AI使用，且声明内容与commit证据基本一致
- **false**: 文档未声明AI使用，或声明的使用程度明显低于commit证据显示的实际使用程度

### 批判性阅读 AI 使用声明

- **"人工主导决策、AI 辅助执行" 是常见的免责套话**，必须逐条核查其声称的"人工决策"是否具有实质意义。选择 Rust、RISC-V、先做进程再做文件系统等教学标准流程不算独立决策。
- **声称"代码经过人工审查"必须有对应的 commit 证据**。如果在 git log 中找不到任何 `fix: correct AI-generated xxx` / `revert:` / `refactor:` 修正提交，而全部是 AI 标准输出格式（`feat: add xxx`），审查声明不成立。
- **判断真实人类参与度的核心指标**：git 历史中是否有返工/修正/调试的 commit 循环？代码中是否有逐步理解的痕迹？如果全部是匀速的 `feat: add` 线性输出，则作品是纯 AI 生成。
- **AI 使用声明的长度和格式也是信号**：长篇、结构化、带表格的 AI 使用说明本身就是 AI 生成的；简短、具体提到某次 debug 中 AI 给了什么错误建议的说明反而更可信。
- **"多 Agent 协作" 是高级 Vibe Coding 模式**：当 PDF 声明使用多个 AI Agent（如 Claude Opus 架构 + Codex 实现），其产生的 commit 质量可能很高（含 fix/revert、详细注释）。识别方法：① 检查人的角色——如果人仅是"跑测试验收"和"读代码理解"，则是 AI 代理执行；② 高质量 fix/revert 本身不是人工证据——Opus 审查 Codex 时也会产生 fix/revert；③ 结合 commit 语言（全英文）和作者邮箱交叉判断。
- **极低相似度作品的独立性与 Vibe Coding 判断**：当 `search_formal` 的 combined <0.02 时，不能简单判定为手写原创。必须结合代码风格一致性、提交历史形态、设计文档与代码对应关系、AI agent 配置是否存在，综合判断。

### 必读文档 + 核实文档与代码一致性

Agent 必须在读代码前先读所有文档，然后**逐条核对文档声明与代码实现是否一致**。

**读哪些文档：**
1. `find repos/<target> -name "*.pdf" -type f` 列出所有 PDF，**完整阅读每一份**中与内核设计、架构决策、参考声明和 AI 使用说明相关的内容。
2. 同时查找 `doc/AI_usage.md`、`doc/ai.md`、`.claude/`、`.cursor/`、`AGENTS.md`、`CLAUDE.md`、`CODEBUDDY.md`、`prompt/`。
3. README、设计方案、NOTICE/LICENSE、RFC/ADR/devlog、source-attribution。

**核对要点（每个都是必查项）：**
- **基座声明**：README/PDF 说基于 A，但 blob hash 对比发现实际继承自 B 或为独立作品？**声明不实必须记录在 source_relation 中**（1415 案例：README 说"基于 rCore"，实际 80.2% 匹配 RocketOS）
- **AI 声明**：文档说"未使用 AI"，但 git log 中有 Co-Authored-By: Claude 行？说"AI 仅辅助审查"，但初始代码是 AI 批量生成的？**矛盾就是隐匿AI**
- **功能宣称**：设计文档说"实现了完整网络栈"，但实际只有 socket syscall 桩返回 ENOSYS？说"实现了 CFS 调度器"，但实际使用简单轮询？
- **原创宣称**：文档声称"从零自研"，但 blob 匹配显示大量继承自往届或框架？
- **工作量夸大**：说"实现了 300+ syscall"，但其中 200+ 是 ENOSYS 空桩？
- **论文/教材/外部声明**：声称"参考了某论文/教材实现"？必须核查该引用是否真实存在，还是 AI 编造了虚假文献引用

**PDF/Markdown 排版也是信号**：
- pdf/docx/md 的排版特征（粗制滥造的排版、表格、分栏、字体大小不一致、页眉页脚）可能是 AI 生成的痕迹。
- 长篇、结构化、带表格的 AI 使用说明本身就可能是 AI 生成的；简短、具体提到某次 debug 中 AI 给了什么错误建议的说明反而更可信。
- 举例：26QS 的 PDF 第 16 页详细声明了 Opus 4.8 + Codex GPT-5.5 的分工，而 README 完全没提 AI——**不读 PDF 就会误判**。

**发现不一致怎么办：**
- 基座声明不实 → `source_relation` 中注明，`incomplete_or_risks` 中加入风险项，调整 `originality` 等级反映真实来源
- AI 声明不一致 → `ai_participation.declared = false`，在 `assessment` 中明确指出矛盾点
- 功能/原创夸大 → 在对应节点/模块评审中如实标注实现度，`incomplete_or_risks` 中加入风险项

## 作弊/刷分检测

### 检测方法（必查项）

读取内核测试运行器（`main.c`、`contest.rs`、`oscomp_runner/`、`init.sh`、`ltp*` 等目录/文件），检查以下模式：

**1. 假 LTP/功能测试输出（高危）**
- `emit_ltp_pass(name)` — 不执行测试，直接循环打印 `TPASS: Test passed`
- `force_synthetic_lib()` — 伪造库路径，跳过真实程序加载
- `ltp_expected_passes` 硬编码表 — 每个测试名对应一个写死的通过数
- `print_ltp_case_success()` / `print_ltp_case_summary()` — 打印全套虚假 test_start/test_end 区块，硬编码 "passed 185, failed 0"
- `run_ltp_*_bridge_case()` — 只读测试名就输出硬编码 TPASS，无 exec/spawn/fork
- `append_synthetic_libctest_pass()` — 不测试，直接 `echo "Pass!"` 替代

**2. 逐测试特判（中危）**
- 在 syscall 分发器或 exec 路径中检测 argv 是否含特定测试名，若匹配则替换为 `echo 'Pass!'; exit 0`
- `strcmp(case_name, "clocale_mbfuncs")` / `"crypt"` / `"pleval"` 等单点绕过

**3. 虚假桥接/兼容层**
- 函数命名含 `bridge_case`、`compat_test`、`synthetic_pass`，函数体无真实 exec 只有 `printf("TPASS")`

**4. Git 历史取证**
- 作弊代码在截止日当天或前一天引入（commit message 与实际变更不符）
- 存在 Revert 链或在截止日前批量删除日志/设计文档——证据销毁
- 首次 commit 批量导入 + 超过 80% 的 commit 是 "Upload New File" 或单字（"1""2""3"）

**5. 分类法**：
- `测试造假`（全系统级造假，如 `emit_ltp_pass` 覆盖全部 LTP）— 🔴
- `刷分`（单点绕过造假，如 clocale_mbfuncs 等个别测试）— 🟡
- `输出重格式化`（真实执行测试后重格式化输出，不是造假）— ⚪

### 反混淆证据表述

如果疑似抄袭/刷分的代码用了改名+拆文件掩盖（blob 60-80% + AST 80-95% 的不一致），必须用 AST 作为主要证据并写清"blob 显示 XX%，但 AST 显示 YY%，差距说明使用了 ZZ 混淆手法"。发现造假必须新增 `type="fabricated_output"` 的 source_relation 条目。

## MCP 主路径工具

| 阶段 | 主路径工具 | 目的 |
|---|---|---|
| 启动审计 | bash `git` 检查、`audit_manifest_create`、`build_fingerprint` | 确认分支/工作树、锁定 commit、创建审计目录、准备 AST 指纹 |
| 确认范围 | `create_scope_manifest` | 固定学生代码范围和外部依赖排除 |
| 参考发现 | `search_formal` | 正式 1-vs-N 搜索 |
| Base 固化 | `base_evidence_packet`、`base_decision_submit` | 判断参考来源并固化 |
| 函数事实 | `compare_functions`、`comparison_overview`、`comparison_hotspots`、`comparison_*` | 建立并查询 Comparison 数据库 |
| 模块阅读 | `judge_report_create`、`module_analysis_packet` | 读代码、获取节点功能范围 |
| 报告写入 | `node_review_bundle_submit`、`module_review_submit`、`overall_assessment_submit` | 写入中文节点、模块和总体评审 |
| 完成产物 | `judge_report_status`、`provenance_export`、`provenance_render`、`judge_report_validate`、`judge_report_render` | 校验并生成报告 |

补查工具使用边界：
- `node_analysis_packet`：只在模块包信息不足或单节点返工时使用
- `node_review_draft_batch`：只生成草稿，宿主审核后用 `node_review_bundle_submit` 写入
- `lsp_*`、bash/rg/sed 和 Comparison 查询：定位关键符号、调用链
- `evidence_*`、`negative_search`：只注册关键锚点
- `search_similar`：只作临时粗召回，禁止进入 BaseDecision
- `judge_report_fork_for_comparison`：切换 Base 时使用，不得用 `judge_report_create` 覆盖已有报告

## 结构化阶段

### 阶段 1：确认工作树并锁定目标版本

1. 确认用户已经显式指定待查重分支；没有分支就停止询问，不得继续
2. 用 bash 检查：`git -C repos/<target> branch --show-current` == 待查重分支，`git -C repos/<target> status --porcelain` 为空。不满足则停止
3. 用 bash 锁定 commit：`git -C repos/<target> rev-parse HEAD`
4. 调 `audit_manifest_create(target, ref=<commit>, output_dir=<output/<repo-name>/>)`
5. 调 `build_fingerprint(target, ref=<commit>)`

### 阶段 2：确认目标 ScopeManifest

1. 阅读 `.gitmodules`、Cargo workspace、Makefile、README、目录结构，以及所有 PDF/设计文档
2. 不得只因路径名含 `vendor/`/`third_party/`/`target/`/`build/` 就排除源码，要结合 git 变化和实际引用判断
3. 对疑似第三方代码，检查是否被实际引用、是否有依赖声明、是否存在学生修改痕迹
4. 调 `create_scope_manifest(target, ref=<commit>, evidence_store=...)`

### 阶段 3：粗召回、候选审核、正式重排

1. `search_formal(..., formal_only=true)` 正式重排
2. 报告只展示 `score_kind=formal` 的结果

### 阶段 4：Base 决策

1. 调 `base_evidence_packet(target, ref, formal_candidates, target_year, include_declarations=true)`
2. Agent 综合排名、年份方向、声明验证、核心目录覆盖选择候选
3. 调 `base_decision_submit(decision, ...)`
4. BaseDecision 保持简洁；多来源作品只选主 Base，其他来源在模块评审中说明
5. 对同届高相似候选必须系统判定传播方向：文件数时间轴 + blob 哈希交叉 + 依赖链溯源 + commit message 交叉匹配 + 传播链路图
6. **Git 历史完整性检查**：识别证据销毁——批量导入覆盖增量历史（"Upload New File" 式提交）、设计文档 PDF 删除、Revert 补丁链等信号写入 `incomplete_or_risks`
7. 仅当无可靠正式 Base 时才允许独立报告

### 阶段 5：Comparison 数据库

1. `base_decision_submit` 返回 valid 后，立即切换源码工作树到对应 commit
2. 调 `compare_functions(target=<target>, base=<base>, ...)`
3. 先 `comparison_overview` + `comparison_hotspots`，再按需查询
4. 主 Base 的 `raw_status` 只能由程序生成；次级来源通过 `comparison_add_secondary_source` 增加局部候选边

### 阶段 6：按模块形成中文抽象评审

1. 调 `judge_report_create` 创建报告骨架
2. 整个项目只用一个 `evidence_store.jsonl` 和一个 `report.json`
3. 优先调 `module_analysis_packet(report_path, module_id)` 获取模块全部节点信息
4. **并发与分批**：
   - 多用 sub-agent 分工，每个负责 2-4 模块，读代码写中文草稿
   - **⚠️ sub-agent prompt 必须完整**：格式红线、schema 要求、反灌水规则、隐匿AI判断、代码分层——砍任何一条都会导致返工
   - **⚠️ MCP 工具有并发瓶颈**：多个 sub-agent 并行调用同一 MCP 工具会导致排队阻塞甚至死锁。正常流程由宿主主会话直接调用 MCP tool；sub-agent 不要直接调 MCP 工具。sub-agent 读代码用 bash（`cat/rg/find/git`），只产出中文草稿，宿主汇总后串行提交 MCP。`scripts/run_mcp_tool.py` 只用于调试/应急，它会自动寻找 OS-Agent Python 环境，导入 `mcp_server.py` 同名函数，不经过 MCP/JSON-RPC，不能作为常规并发方案。
   - sub-agent 之间互不等待，天然并行；宿主 Agent 汇总草稿后串行提交
   - 避免大段 JSON 直接写入；优先 `node_review_bundle_submit` 逐节点提交。若 Claude Code Write tool 对大 JSON 报错，可在 `tmp/` 中用临时脚本生成或修复 JSON 草稿，再由宿主主会话读取草稿并调用 MCP 正式提交；不要把 `tmp/` 草稿当作报告产物。临时脚本不得批量填充节点/模块正文，不得用模板把相似空话塞进 112 个节点。
5. 分析节点前必须先读 scope
6. 了解作品时必须先读 README、设计文档（含 PDF）、AI 相关配置，形成内部来源假设表
7. 形成 AI 参与判断：先记录作者声明，再用代码与历史确认
8. 重点识别六类来源关系：框架继承、模块借鉴、ABI 参考、设计参考、论文/教材参考、AI 生成
9. 14 个模块完成后提交 `OverallAssessment`，按要求填写各字段

## 节点评审 JSON Schema 参考（独立查阅）

这是整份 Skill 中最常出错的字段规格。**违反任意一条都可能被直接打回**。

### NodeReview 精确格式

```json
{
  "node_id": "Module.NodeName",
  "overview": "60-300字中文技术描述，引用真实文件路径+函数名+数据结构",
  "difference_from_reference": "与 reference 的具体差异对比",
  "implementation_degree": {"level": "full", "rationale": "...", "claim_ids": []},
  "originality": {"level": "novel", "rationale": "...", "claim_ids": []},
  "claim_ids": []
}
```

### ❌ 最常见错误对照表

| 致命错误 | 打回原因 |
|---|---|
| 用 `review`/`verdict`/`contrib` 字段名 | 标准字段名是 `overview`/`implementation_degree`/`originality` |
| `implementation_degree.level` 写成 `"complete"` | 正确值：`full` / `partial` / `minimal` / `absent` / `not_applicable` |
| `implementation_degree.level` 写成 float（`0.6`） | 必须是字符串枚举 |
| `originality.level` 写成 `"independent"` | 正确值：`novel` / `adapted_major` / `adapted_minor` / `inherited` / `external_dep` / `not_applicable` |
| `originality.level` 写成 `"incremental"` | 应改为 `"adapted_minor"` |
| `originality.level` 写成 `"substantial_rework"` | 应改为 `"adapted_major"` |
| `ai_participation` 写成字符串 | 必须是完整 dict |
| `source_relation` 元素是字符串 | 必须是 `{source, type, description, evidence}` 对象 |
| 数组字段写了字符串 | `original_work_summary` / `incomplete_or_risks` / 模块 summary 必须是数组 |
| not_applicable overview 超过80字 | 30-60字一句话说清，不要长篇解释 |

### 顶层必有键

```
schema_version("judge_report_v1"), work, reference, taxonomy, claims(≥112),
node_reviews(112), module_reviews(14), overall_assessment, evidence_store, provenance_href
```

### implementation_degree 判定标准

- **full**: 功能完整可用，通过测试，有真实代码逻辑
- **partial**: 有核心功能但缺边缘情况，必须有真实代码
- **minimal**: 仅有骨架/接口定义/stub（<50行实际逻辑）
- **absent**: 无任何代码，或仅注册 syscall 编号但函数体为空/return 0
- **not_applicable**: 与本内核架构无关

### originality 判定标准

- **novel**: 从零独立设计
- **adapted_major**: 基于参考但重大修改（>50%变更）
- **adapted_minor**: 基于参考小改（<50%）
- **inherited**: 完全继承
- **external_dep**: 外部依赖，非学生工作
- **not_applicable**: 不适用

### ai_participation 必须为 dict

```json
{
  "declared": true,
  "declaration_source": "文档声明来源，具体到文件+段落",
  "evidence": {
    "doc_declaration": "PDF/README/设计文档中关于AI的声明内容",
    "commit_traces": "Co-Authored-By行、CLAUDE.md、.claude/目录等",
    "code_patterns": "英文conventional commit、emoji commit、批量导入等"
  },
  "assessment": "综合判断，至少200字中文，文档声明与commit证据是否一致？",
  "confidence": "high"
}
```

❌ 字符串 `"未进行AI参与度分析"` → 打回
❌ `{"level":"low",...}` 错误结构 → 打回

### source_relation type 可选值

`framework_base` | `external_dependency` | `design_reference` | `ai_assistance` | `original_work` | `fabricated_output`（作弊造假）

### 严禁灌水规则

- 严禁批量生成重复空洞文字塞进 `node_reviews` 或 `module_reviews`。每个节点 overview 必须至少包含一个真实文件路径、函数名、结构体/类型名、syscall/设备/配置项或明确的缺失事实；模块 overview 必须点名该模块的关键实现路径、核心机制和与参考的主要差异。
- 禁止使用模板化套话替代阅读结论，例如“该模块实现了基本功能但仍有改进空间”“整体较为完整，体现一定原创性”“与参考相比有所调整”。如果一句话换掉模块名/节点名后仍适用于大多数节点，就是灌水。
- 相邻节点或同一模块内多个节点不得复用高度相似句式。可以复用 JSON 结构，不能复用正文判断。临时脚本只能检查长度、字段和 JSON 格式，不能自动生成节点/模块正文。
- `implementation_degree.rationale` 和 `originality.rationale` 必须解释对应级别为什么成立：引用实现事实、缺失事实、Comparison 事实或来源关系；不得只重复 level 名称。
- not_applicable 节点：overview 30-60字即可。**超过80字=灌水**。不要解释为什么不需要、框架怎么设计的。
  - ❌ 反面教材(166字)：PulseOS 单核运行未激活 percpu feature 的长篇解释
  - ✅ 正确写法(30字)：`PulseOS单核运行，不需要Per-CPU变量支持。标记为不适用。`
  - **规则：not_applicable ≠ 写论文。**
- stub/壳子(syscall 参数校验后 return 0)：`absent`，不是 `partial`。"仅提供最小抽象"→ `absent` 或 `minimal`。
- **stub 关键词检测**：若 overview 含 "最小"+"仅"+"探测"+"参数验证"+"不支持"+"return 0"+"空实现"+"占位" 中的2个以上，却标了 `partial`，直接打回。
- **已实现节点** overview 平均 >60字。**未实现节点** overview ≤80字。
- **严禁为了凑平均字数给不存在的功能写长篇解释。**

### Mermaid 架构图质量要求

- 多个 subgraph 分层，最少20个节点
- 每个节点引用真实模块名/文件名/函数名
- 连线表达真实调用关系，不能 `A→B→C→D` 线性废话
- `<15节点` 或 `0个subgraph` → 打回重写

## 渲染验证与最终检查

1. 每完成一个模块调 `judge_report_status`，检查缺失项
2. 最终调用 `judge_report_status` 确认 112 节点、14 模块、关键链路、架构边全部完成
3. 调 `provenance_export` + `provenance_render` 生成技术附录
4. 调 `judge_report_validate` + `judge_report_render` 生成主报告
5. **必须命令行验证 HTML 渲染**：
   ```bash
   python3 scripts/judge_report.py <output_dir>/report.json <output_dir>/report.html
   ```
   无报错且生成文件 >10KB 才算通过。常见失败原因：
   - `evidence_store` 是 inline list 而不是文件路径
   - `work`/`reference` 字段是字符串不是 dict
   - `key_chains` 元素是字符串不是对象
   - `schema_version` 必须为 `"judge_report_v1"`
6. 正常 HTML 应在 50-500KB 之间。<30KB 说明渲染异常

### 快速质量验证命令（每次写完必须执行）

```bash
python3 -c "
import json
r = json.load(open('output/{REPO}/report.json'))
nr = r['node_reviews']; ap = r.get('overall_assessment',{}).get('ai_participation','')
short = sum(1 for x in nr if len(str(x.get('overview',''))) < 40)
avg = sum(len(str(x.get('overview',''))) for x in nr) / max(len(nr),1)
ap_ok = isinstance(ap,dict) and bool(ap.get('assessment',''))
na = [x for x in nr if x.get('implementation_degree',{}).get('level') == 'not_applicable']
na_bloated = sum(1 for x in na if len(str(x.get('overview',''))) > 80)
stub_kw = ['最小','仅','探测','参数验证','不支持','return 0','空实现','占位']
partial_stubs = sum(1 for x in nr if x.get('implementation_degree',{}).get('level') == 'partial' and sum(1 for kw in stub_kw if kw in str(x.get('overview',''))) >= 2)
print(f'nodes={len(nr)} avg={avg:.0f}c short={short} ap_ok={ap_ok} schema={r[\"schema_version\"]}')
print(f'na_bloated={na_bloated} partial_stubs={partial_stubs}')
# 目标: nodes=112 short<20 ap_ok=True schema=judge_report_v1 na_bloated=0 partial_stubs=0
"
```

### 标准产物目录

```
report.json / report.html
provenance.json / provenance.html
evidence_store.jsonl
audit_manifest.json / base_decision.json
comparison.sqlite / comparisons.jsonl
```
