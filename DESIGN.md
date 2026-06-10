# OS-Agent 设计文档：内核作品查重系统

> 状态：**流程重新设计（v2）**。本文档是实现依据。
> 适用：全国大学生计算机系统能力大赛（操作系统赛）proj18 —— 面向小型操作系统的分析比对智能体系统
> 重要：本版根据实践教训修正了 v1 的流程顺序与范围。v1 的实现存在方向性错误（见 §6），需按 §7 改造。

---

## 1. 任务

读一个**待查内核作品**，判定它的真实工作：哪些是外部依赖、哪些移植自前代作品（原型/往届/同届）、哪些是选手自研，并展示其内核架构。不管选手是否声明，都要能识别真实血缘。

核心服务对象是**单个待查作品 vs 语料库**，不是对所有作品做两两普查。

---

## 2. v1 的五个流程错误（实践教训）

v1 把流程做反了，具体错误与正确做法：

| # | v1 的错误做法 | 正确做法 |
|---|---|---|
| 1 | 先全库建指纹+查重，最后才用 `declarations.py` 读声明做"事后核查" | **先让 Agent 读目录结构 + Cargo/Makefile/文档**，理解依赖与结构，**据此排除**，再查重。声明理解是前置过滤器，不是事后补丁 |
| 2 | 只处理 c/cpp/rust，**汇编 `.S/.s` 被静默忽略**（全库 1699 个汇编文件，含 boot/entry/swtch 等内核核心） | 汇编的取舍必须是**显式决策**并说明；内核启动/上下文切换的抄袭常在汇编 |
| 3 | 建指纹与查相似度**耦合**在一条流水线里 | **分离**：建指纹（纯确定性）→ Agent 看结构/声明**排除**外部依赖/vendor/汇编/无关 → 再对剩余代码查相似度 |
| 4 | 做 **N×N 全库 all-pairs**（162×162），既贵又大部分无意义 | **1-vs-N**：一个待查作品 against 语料库 |
| 5 | 全部作品都做细粒度计算，无漏斗 | **两级漏斗**：指纹粗筛出高相似候选 → 仅对候选做源码级细对比 |

教训总结：**理解在前、排除在中、查重在后；指纹与比对分离；1-vs-N 粗筛→精查漏斗。**

---

## 3. 重新设计的流程（v2）

```
待查作品 R
 │
 ├─[A 理解]  Agent 读 R 的目录结构 + Cargo.toml/Makefile/.gitmodules/README/文档
 │           产出：声明的依赖清单、范式判定、自报血缘、目录角色标注
 │
 ├─[B 排除]  据 A 的理解，标注并排除：
 │           · 外部依赖 (vendor/、cargo 依赖、GNU bash/busybox/musl…)
 │           · vendored 框架底座 (ArceOS/rCore 整包)
 │           · 汇编（显式决策：默认单独标注而非静默丢弃）
 │           · 构建产物/测试样例等无关代码
 │           产出：R 的"选手相关代码"子集
 │
 ├─[C 建指纹] 仅对 R 的选手相关代码建归一化 token 指纹（确定性，可缓存）
 │           语料库成员的指纹离线预建一次
 │
 ├─[D 粗筛]  R 的指纹 vs 语料库（1-vs-N），双向 containment
 │           产出：高相似候选作品列表（按相似度排序）
 │
 ├─[E 精查]  仅对 top-K 候选做源码级细对比：
 │           · 函数级精确哈希 → 原样照搬/换皮/改动/新增
 │           · 声明 vs 事实交叉核查（A 的声明 × D/E 的指纹事实）
 │
 └─[F 报告]  贡献占比 + 三色架构图 + 血缘 + 声明核查 + 创新工作区
```

A/B 是 Agent（LLM）主导的"理解与排除"；C/D 是确定性指纹层；E 在候选上做细对比 + LLM 解读；F 组装。**LLM 不再只做事后核查，而是在最前面做理解与过滤。**

---

## 4. 确定性查重方法（已验证，跨重设计保留）

这些是 v1 实测验证过的结论，方法本身正确，重设计只改它们的**调用时机与范围**（从全库 all-pairs 改为 1-vs-N 漏斗），方法内核不变。

| 用途 | 方法 | 判据 | 验证 |
|---|---|---|---|
| 仓库/簇级相似 | 双向 containment 取 min | min ≥ 0.30 候选；0.7+ 强同源 | xv6-k210=1.00、rCore↔ucore=0.85 |
| 函数级取证 | 归一化 token 精确哈希 | 无关内核误撞 1% | ✅ |
| 换皮检测 | 哈希相等但函数名不同 + 常量集 | 零误报 | ✅ |
| 抗重构改编 | AST 形状哈希（`ast_shape_hash`），只算节点类型不含文本 | combined=max(tok,ast)；avx token 0.041→AST 0.075（保留结构骨架） | ✅ 已有数据，现成（code_atlas 里算了但从未用于查重） |
| 方向判定 | 届号 / git 时间戳 | 老 ← 新 | 指纹本身无向，必须叠加 |

**已废弃 / 修正：**
- **逐函数 jaccard 量化改动量**：被重构（extract/inline）击穿。验证：xv6 `kvminit` 代码未改，但逻辑被抽到 `kvmmake`，函数名对不齐，jaccard=0.00。改动量只在模块级用 containment 给粗粒度。
- **IDF 加权**：对 6566 文件的巨库假枢纽无效（实测 46→48 没降）。大库假枢纽靠**双向 containment 取 min** 解决（小库说"我 40% 在你里"，大库说"你只占我 2%"，取 min 自动过滤）。
- **函数级 token 下限 ~100**：仅用于**抑制 PEER 误判**（Rust new()/get()/drop() 等样板假撞），**不是给自研打折**：无任何匹配的小函数仍是 ORIGINAL。

---

## 5. 出身分类与范式

### 5.1 出身四分类（+ TRIVIAL）
每个函数归入：
- **EXTERNAL**：外部依赖（crates.io 包、GNU bash/busybox、vendor/ 目录）
- **PORTED-FRAMEWORK**：vendored 的框架底座（ArceOS/rCore 整包）
- **PORTED-PEER**：移植/抄袭前代作品（原型/往届/同届）
- **ORIGINAL**：选手自研
- **TRIVIAL**：低于 token 下限且仅匹配 peer 的样板（不诬告抄袭）

判定靠**指纹 + 声明交叉**，不靠预设字典、不靠文件夹名：
- 外部依赖"**是什么**" → Agent 读 Cargo/Makefile/.gitmodules/README（答案在声明里）
- 声明"**是否属实**" → 指纹核查（防瞒报）
- 最有价值的结论来自两者打架：**声称自研却指纹命中他人**

### 5.2 范式识别（决定展示骨架）
报告须先识别范式，按范式选骨架与贡献算法：
- **宏内核**（xv6/rCore/npucore 系）：贡献=自写/改的子系统代码；骨架=固定 14 子系统树。
- **组件化**（ArceOS 系）：贡献=选/改/新增了哪些组件 + 集成；骨架=组件依赖图。
- ArceOS 的"出身×角色"二维：出身（指纹判：官方未改/改过/原创）× 角色（声明判：外部 crate/vendor 改过/自研）。"基于 ArceOS 搭建"是架构选择，不等同于"调用 GNU bash"。

### 5.3 基准库版本敏感（硬约束）
ArceOS 系必须用大赛 fork `oscomp/arceos`（`repos/_baseline_oscomp-arceos`），非上游 `arceos-org/arceos`。验证：用错基准时 vendored 框架 containment 仅 0.43，用对则 0.92 —— 否则 ~40 个百分点的版本差被误报为"选手魔改"。同理 xv6-k210 fork 自早期 xv6。

### 5.4 汇编处理（显式决策，v1 全程缺席）
全库有 1699 个汇编文件（`.S/.s`），v1 的 code_atlas 扩展名映射不含汇编，**被静默忽略**——汇编从未参与过任何相似度计算（boot/entry/swtch/trap 等内核核心、抄袭高发区，v1 的"全库验证"对它一无所知）。

**关键事实**：指纹底层 `tools/code_atlas/minhash.py::signature_from_tokens(tokens)` 只吃一个 token 列表，**不依赖 tree-sitter / AST**。tree-sitter 仅是 code_atlas 用来"切函数 + 抽归一化 token"的手段。所以给汇编建指纹不必等 tree-sitter 支持，决策：
- **轻量汇编 tokenizer（首选，改造必做项）**：按行拆，保留助记符（`mv/ld/csrw/sd…`），把寄存器名、立即数、标号归一化成占位符，得到 token 流，直接复用现成的 `signature_from_tokens`。换皮（改标号/改注释/改寄存器分配）照样可抓。**让汇编进入与 C/Rust 同一套相似度比对。**
- 粒度：按 `.S` 内的 label 块或整文件做单元（汇编无"函数"概念，label 块是自然边界）。
- 备选（更重，不优先）：社区 `tree-sitter-asm`，但 RISC-V/LoongArch 方言多、质量参差。
- 禁止：像 v1 那样静默丢弃而不说明。

---

## 6. 当前实现状态

### 6.1 确定性层（已完成）

| 脚本 | 功能 | 说明 |
|---|---|---|
| `scripts/fingerprint.py` | 统一建指纹（c/cpp/rust via atlas + 汇编 via tokenizer）| build_units / fingerprint_set / ast_fingerprint_set / lang_summary。含 `fn_id` 供边匹配，含 `ast` 字段（AST 形状哈希）。缓存到 `.fp_cache/` |
| `scripts/provenance.py` | 五分类出身（EXTERNAL/FRAMEWORK/PEER/ORIGINAL/TRIVIAL）| classify_provenance（token 下限 100）、functions_and_edges（架构图用）。从 fingerprint.py 取数据。无内置硬编码列表 |
| `scripts/search.py` | 1-vs-N 搜索（token + AST 双维度）| combined = max(token_min, ast_min)；默认缓存模式，`--build` 预建全库 |
| `scripts/declarations.py` | 提取 Cargo 结构 + 依赖声明 | workspace_members / vendored_frameworks / git_deps / submodules / readme_refs。含 gitlab.eduxiji.net |
| `scripts/exclude.py` | 排除规则引擎 | 消费声明数据，不预设字典。llm_external_dirs / llm_student_dirs 字段供 LLM 补写 |
| `scripts/run.py` | 一键驱动 | `run <target>`：声明→指纹→搜索→报告；`--build` 预建全库指纹 |
| `scripts/report.py` | 单作品报告 | 贡献表 + 内核设计树（14 子系统 × 112 叶子 × 三色） + 架构图 + 声明区 + 自研清单 |
| `tools/code_atlas/asm_tokenize.py` | 汇编 tokenizer | 归一化寄存器/标号，保留助记符/偏移。按 label 块切分。复用 minhash.signature_from_tokens |

### 6.2 交付层（已完成）

| 文件 | 功能 |
|---|---|
| `mcp_server.py` | 8 个 MCP 工具：search_candidates / attribution / unit_source / grep_repo / list_dir / node_taxonomy / declared_deps / exclude_rules |
| `SKILL.md` | Claude Code 工作流：Phase 1 判类型（含低分读声明强制对比）→ Phase 2 attribution → Phase 3 sub-agent 批量详细分析 → Phase 4 三色树报告。含两套分析模板（对比/描述） |
| `DESIGN.md` | 本文档 |

### 6.3 已验证

- **指纹判别力**：xv6-k210=os2022test8 1.000（同一代码）、zmz=0.732（直接 fork）、无关噪声 1%
- **AST 增幅**：avx token 0.041→AST 0.075（保留结构骨架）、zmz 0.732→0.752（稳定）
- **rv6 极限案例**：README"基于 xv6-k210 改编"但指纹 token 0.088/ast 0.065——骨架相同+实现重写的改编穿不透指纹。启示：低分时 Agent 必须读声明强制对比（SKILL Phase 1）
- **汇编纳入**：swtch=1.00（同源）、改名换皮被命中（exaros kernelTrap = xv6 kernelvec 逐字照搬）
- **ArceOS 排除**：api/src 保留为 ORIGINAL、arceos/vendor 排除为 EXTERNAL

### 6.4 待做

- **阶段 4 精查**：attribute.py 的函数级 COPIED/DISGUISE/MODIFIED/NOVEL 对比未接入 1-vs-N 搜索
- **创新工作区**：指纹全库 NOVEL 簇（GUI/Wayland 等超出标准子系统的自研模块）
- **产品化验证**：Claude Code + MCP + Skill 真实运行（需要 Claude Code 环境加载 MCP）
- **汇编说明**：报告里显式声明汇编覆盖范围
- **overview.py**：v1 全库 all-pairs 产物，未适配 1-vs-N

---

## 7. 后续计划

| 序号 | 做什么 | 说明 |
|---|---|---|
| 1 | 阶段 4 精查 | attribute.py 接搜索结果 + 声明核查 |
| 2 | 创新工作区 | 全库 NOVEL 簇识别、GUI/Wayland 等展示 |
| 3 | 产品化验证 | Claude Code 加载 MCP+Skill 真实跑一次 |
| 4 | 报告收尾 | 汇编覆盖声明、排除清单、创新区 |
| 5 | overview 适配 | 降级为语料库维护工具 |

---

## 附：环境

依赖：networkx、tree-sitter-c/cpp/rust、numpy（均在 requirements.txt）。指纹缓存 `.fp_cache/`（gitignored）。框架基准 `repos/_baseline_oscomp-arceos`（大赛 fork，见 §5.3）。语料库 `repos/` 约 160 个作品（C-dominant 87 / Rust-dominant 74）。汇编文件 1699 个（§5.4）。
