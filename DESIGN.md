# OS-Agent 设计文档：从「描述树」到「确定性查重 + LLM 差异解读」

> 状态：方案验证完成，待实现。本文档是实现依据。
> 日期：2026-06-10
> 适用：全国大学生计算机系统能力大赛（操作系统赛）proj18 —— 面向小型操作系统的分析比对智能体系统

---

## 0. 这份文档要解决什么

OS-Agent 的真实任务**不是**「给每个内核画一棵描述树」，而是**查重 + 展示本届选手的真实工作**：

> 不管选手是否声明，都要识别出真实血缘（移植自原型 / fork 往届 / 同届互抄 / 真原创），
> 并向评委清晰展示：哪些是外部依赖、哪些移植自前代作品、哪些是选手自己写的、哪些是创新功能。

本文档记录：为什么推翻旧的「描述树为主」路线、新流程是什么、每个判断背后的验证数据、以及实现约束。

---

## 1. 为什么推翻旧路线（有数据支撑）

### 1.1 描述树对同谱系作品「文字塌缩」

固定的内核设计树让 LLM 为每个子系统产出描述性 claim（如「使用 round-robin 调度器 / status=implemented / maturity=teaching」）。**对同源作品，这些描述几乎逐字相同，零区分度。**

验证（npucore 2023→2024 真实对子，`scripts/attribute.py`）：
- base 和 target 的 `sbrk` 函数若用描述树，都会被填成「实现了 sbrk 堆调整 / implemented」——完全一样。
- 而实际差异是：base 调用通用 `mmap()`，target 改为专用 `expand_heap/shrink_heap` + `wrapping_add` 防溢出 + 统一越界日志。**这是真实的设计改进，描述树完全埋没了它。**

### 1.2 区分度不在 LLM 的散文里，在确定性信号里

两个真正能区分同源作品的信号，都与 LLM 无关：
1. **归一化 token 的精确指纹**（抹掉标识符名后的代码结构哈希）。
2. **每个函数锚定的精确源码位置**（file:line + 片段）。

### 1.3 保留什么 / 推翻什么

| 旧 agent_d 的东西 | 处置 |
|---|---|
| 「为每个 repo 独立填描述树」作为主任务 | **推翻** |
| `node_react_agent` / `agent_d_graph` / `node_analysis_graph` 自研 ReAct+编排+checkpoint | **推翻**（LLM 现在只处理极少数差异函数，不需要重型编排） |
| `tui_dashboard` / `run_recorder` / `run_journal` | **删** |
| `core/code_atlas/*`、`tools/code_atlas/*`（AST/指纹） | **保留为地基** |
| `core/evidence.py`（确定性 evidence_id） | **保留**（取证） |
| `core/kernel_tree.py` taxonomy + `NODE_SPECS` | **保留为陈列骨架 + 归类导航**（仅宏内核范式） |
| `kernel_glossary.json` | **保留**（阶段3 LLM 资源） |
| 架构图生成（Mermaid，commit f68f9ff） | **保留并重用**（阶段4，按出身三色染色 + 画创新模块） |
| `agent_c.py` 打分 | **重写**为双向 containment（阶段1） |

**一句话**：主干换成确定性查重流水线，旧系统的确定性零件全部复用，LLM 编排那套丢掉。

---

## 2. 非 LLM 查重方法（已定稿，全程验证）

| 用途 | 方法 | 判据 | 验证状态 |
|---|---|---|---|
| 仓库/簇级血缘 | 双向 containment 取 min + 并查集聚簇 | min ≥ 0.30 入簇；0.7+ 直系 | ✅ 命中 xv6-k210=1.00、rCore↔ucore=0.85 |
| 方向（谁抄谁） | 届号 / git 时间戳 | 老 ← 新 | 必须叠加，指纹本身无向 |
| 函数级取证 | 归一化 token 精确哈希 | 无关内核误撞率 1% | ✅ |
| 换皮检测 | 哈希相等但函数名不同 + 常量集指纹 | 零误报 | ✅ |
| 抗深度混淆 | AST 形状哈希 + 调用图指纹 | 兜底二次确认 | 有数据，未深测 |

**已弃用**：逐函数 jaccard 量化「改了多少」——被重构（extract/inline）系统性击穿。验证：xv6 的 `kvminit` 代码未改，但因逻辑被抽到 `kvmmake`，函数名对不齐，jaccard=0.00。改动量只在模块级用 containment 给粗粒度，不做函数级百分比。

**关键发现**：
- **大库假枢纽**靠双向 containment 取 min 解决，**不靠 IDF**（实测 IDF 对 6566 文件的巨库 `T...106` 无效，46→48 没降）。原理：小库说「我 40% 在你里面」，大库说「你只占我 2%」，取 min 自动过滤。
- IDF 加权可保留（无害），但不是关键。

---

## 3. 核心概念：出身（provenance）四分类

每个函数的「来源」不是二元属性，而是四类。**判定靠指纹 + 声明交叉，不靠预设字典、不靠文件夹名。**

| 类别 | 含义 | 主要判据 |
|---|---|---|
| **EXTERNAL** | 外部依赖：crates.io 包、GNU bash、busybox、OpenSBI 等 | LLM 读 Cargo.toml/Makefile/.gitmodules 声明 + `vendor/` 机器复制目录 |
| **PORTED-FRAMEWORK** | vendored 的框架底座：ArceOS / rCore 等组件化框架 | 指纹命中对应版本框架基准 + 声明 |
| **PORTED-PEER** | 移植/抄袭前代作品：教学原型、往届、同届 | 指纹 all-pairs 命中更早语料成员（阶段1结果） |
| **ORIGINAL** | 选手自己写的 | 指纹在全语料库 + 框架基准里都无匹配 |

**为什么不能预设外部库指纹清单**（你点破的循环论证）：
- 预设永远不全，漏一个就高估选手。
- 更致命：「先用文件夹名 `bash-5.1.16/` 圈出外部库，再算指纹，然后号称用指纹识别外部库」——指纹是用文件夹名喂进去的，自我实现的预言，逻辑是空的。

**正确分工**：
- **外部依赖「是什么」** → LLM 读声明文件（答案在 Cargo.toml/Makefile/submodule/README 里，需读懂自然语言和构建逻辑）。
- **声明「是否属实 / 有无瞒报」** → 指纹 all-pairs（确定性，防撒谎）。
- **最有价值的查重结论来自两者打架**：声明说自研、指纹说抄袭。

---

## 4. 内核范式：一把尺子量不了所有作品

不同架构范式的「贡献」衡量方式根本不同，**报告必须先识别范式，再选展示骨架和贡献算法**。

| 范式 | 特征 | 贡献 = | 展示骨架 |
|---|---|---|---|
| **宏内核**（xv6/rCore/npucore 系） | 单体 `os/src/`，直接系统调用 | 自己写/改了多少子系统代码 | 固定 14 子系统树 |
| **组件化**（ArceOS 系） | 大量 `ax*` crate 依赖，workspace | 选了/改了/新增了哪些组件 + 怎么集成 | 组件依赖图（按 crate） |
| **unikernel** | `no_std`，单地址空间 | 类似组件化 | 组件/特性图 |

范式识别由 LLM 读 `Cargo.toml` 依赖结构 + 目录布局完成（实测可行，见 §5.3）。

### 4.1 ArceOS：「算不算外部依赖」需要二维标注

「ArceOS 部分算不算外部依赖」不能用单一标签回答——组件化范式破坏了简单的三分法。正确做法是拆成两个正交维度：

- **维度 A：出身（provenance）** —— 指纹说了算（来自 ArceOS 官方未改 / 改过 / 选手原创）。
- **维度 B：角色（integration）** —— 声明说了算（外部 crate 原样拉取 / vendor 进来改过 / 自研 crate）。

ArceOS 组件落在矩阵里，而非一个标签：

| | 选手未改源码 | 选手改了源码 |
|---|---|---|
| **来自 ArceOS 官方** | 🔲 框架依赖（像用标准库） | 🟨 魔改框架（选手工作！） |
| **选手自己写的 ax-crate** | — | 🟦 自研组件 |

**判断原则**：「基于 ArceOS 搭建」本身是一种架构选择和集成工作，**不应等同于「调用 GNU bash」**。否则 ArceOS 系选手永远显得「没干活」，不公平。

---

## 5. 三种范式的验证数据

所有验证脚本在 `scripts/`，零 LLM，指纹缓存在 `.fp_cache/`（复跑秒级）。

### 5.1 宏内核同一代码（对照组）
`xv6-k210 ↔ os2022test8` containment = **1.00**（同一份代码换名提交）。
`rCore-Tutorial-v3 ↔ ucore_os_lab` = 0.85（已知教学传承）。

### 5.2 宏内核跨届（npucore 2023→2024，`scripts/attribute.py`）
排除 vendor 后：**88% 继承（COPIED）/ 12% 真实工作（MODIFIED+NOVEL）**。
- LLM 攻击面从 12512 个函数压到 147 个（98.8% 被确定性层消化）。
- NOVEL `sys_linkat` 里有选手硬编码的 `println!("111111111111")` 调试残留 —— 真人手写的铁证。
- **教训**：不排除 vendored 第三方（GNU bash/busybox），选手真实工作量从 12% 被稀释到 2%，严重低估选手。

### 5.3 组件化（ArceOS 系，作品 T202510216995249-4014）
- 选手自研代码（`api/core/src`）在官方 arceos 里 containment = **0.05** —— 几乎全自研，铁证。
- 指纹干净分离了「选手 starry-core/api」与「vendored 框架」，**组件化范式下出身判定同样成立**。
- `Cargo.toml` 明文写出范式（workspace members）、外部依赖（12 处 `oscomp/arceos.git`、Starry-OS crates、crates.io）、自研边界（path 依赖 `./core ./api`），还自报血缘（`repository = Starry-OS/starry-next`）。**LLM 读声明完全可行。**

### 5.4 ⚠️ 版本漂移：最重要的约束
```
vendored arceos  在「我的 baseline」(arceos-org 上游) 里 : 仅 0.43
两个参赛作品的 vendored arceos 互相                      : 0.82
```
两个作品用同一个大赛 fork（`oscomp/arceos`）所以彼此 0.82，但和我的上游 baseline 都只有 0.43。**这不是选手改了一半，是我比错了版本。** 用错基准会把 ~40 个百分点的「版本差」误报成「选手魔改」。

**已验证修复**：clone 大赛 fork `repos/_baseline_oscomp-arceos`（`git clone https://github.com/oscomp/arceos.git`）后重测：
```
作品 A vendored arceos:  上游 baseline 0.43  →  oscomp baseline 0.92
作品 B vendored arceos:  上游 baseline 0.39  →  oscomp baseline 0.75
```
换对基准，框架 containment 从 0.43 跳到 0.92 —— 之前的「差异」绝大部分是版本差，不是选手魔改。基准对了，剩余的 8%（A）/ 25%（B）才是可信的「选手动过框架」信号；A、B 差异本身也变得可解释（B vendored 文件更多，可能 fork 自不同时间点）。

### 5.5 四分类端到端（`scripts/provenance.py`，作品 A + oscomp 基准 + 5 个同簇 peer）
首次把 §3 的四分类作为整体跑通。按 token 加权：
```
PORTED-FRAMEWORK  61%   (vendored oscomp/arceos)
PORTED-PEER       21%   (Starry 生态同簇共享)
ORIGINAL          17%   (选手自研)
```
**按目录的出身分布精确对上项目结构**（指纹层不知道目录含义，纯靠代码）：
```
arceos/  82% FRAMEWORK   src/ 97% ORIGINAL   core/ 65% ORIGINAL
api/     60% ORIGINAL    apps/ 77% PEER
```
ORIGINAL 样本全是真实内核工作：`handle_syscall`(3091tok)、`sys_clone`、`sys_mmap`、`sys_futex`、`sys_execve`、`do_exit`、`sys_shmat`…… 即「选手在 ArceOS 上自研的 Linux 兼容系统调用层」，每条带 file:line。
- 少量 ORIGINAL 落在 `arceos/` 目录（如 `axfs/.../lwext4_rust.rs::write_at`）= 选手确实魔改了框架的一部分，符合预期，非误判。
- 该作品真相被准确刻画为「框架 61% + 生态共享 21% + 自研 17%」，而非用错基准时失真的「90% 外部依赖」。§4.1 的二维矩阵在真实数据上成立。

### 5.6 声明-事实交叉核查（阶段3，由 Claude 扮演 LLM 实跑）
读作品 README，逐条对账：

| 选手声明 | 指纹事实 | 判定 |
|---|---|---|
| 「基于 ArceOS 组件生态构建」 | arceos/ 82% FRAMEWORK，匹配 oscomp/arceos 0.92 | ✅ 属实 |
| 「参考 starry-next 编写 starry core/api」 | core/api 大量 BROAD（多 peer 共有，共同祖先 starry-next） | ✅ 属实且诚实 |
| 「Unikernel 风格宏内核」 | 范式特征吻合 | ✅ 属实 |

声明诚实的作品：自报 ArceOS + starry-next 血缘，指纹全部印证，无「声称自研却命中他人」的矛盾。

### 5.7 ⚠️ 函数级判定必须设 token 下限（关键规则）
核查 PEER 共享模式时发现：选手 core/api 中「恰好 1 个 peer 共有」的 narrow 信号，MIN_TOK=0 时有 117 个，但样本全是 `from`/`new`/`get`/`drop` 等 Rust 样板小函数——归一化后结构天然相同，不是抄袭。
```
MIN_TOK=0:   NARROW=117  (from/new/get/drop 噪声)
MIN_TOK=50:  NARROW=59
MIN_TOK=100: NARROW=24   (read_from_user/check_null_terminated/check_signals 等真函数)
```
**规则**：函数级抄袭判定必须设 token 下限（~100），低于它的函数因无判别力而排除。与仓库级「小函数/通用代码无判别力」同源（仓库级靠双向 min 压制，函数级靠 token 下限）。攻击面从 117 噪声压到 24 真信号。

**已落地**（`scripts/provenance.py`，PEER_TOKEN_FLOOR=100，新增 TRIVIAL 桶）：
```
            加下限前        加下限后
PORTED-PEER  21%（含噪声）  →  13%（真共享）
ORIGINAL     17%           →  14%（样本不变，仍是 handle_syscall/sys_mmap/sys_futex…）
TRIVIAL      —             →  12%（无判别力小函数，不诬告抄袭、不虚增自研）
```
TRIVIAL 单列：**仅匹配 peer 且低于下限**的小函数（Rust new()/get()/drop()）不报 PORTED-PEER（不诬告抄袭）。

**重要修正（批量抽查发现）**：token 下限**只用于抑制 PEER 误判，不是给自研打折**。早先实现把「低于下限且无匹配」也划进 TRIVIAL，导致小函数多的精简内核被严重低估——作品 `T202410488992741-2142`（token 中位数仅 61）的自研工作被压到 65%（token 加权），修正后回到 84%。正确规则：
```
peer 匹配 + ≥下限 → PORTED-PEER（抄袭判据）
peer 匹配 + <下限 → TRIVIAL（样板假撞，不算抄袭）
无任何匹配          → ORIGINAL（选手代码，不论大小）
```
FRAMEWORK/vendor 判定有目录/基准佐证，不受下限影响。

### 5.8 阶段4 报告组装端到端（`scripts/report.py`）
把确定性出身分类组装成评委可读的自包含 HTML（`output/<target>/_report/index.html`，12KB，无 JS 依赖）。五个区块：
1. **贡献占比表**：五类来源的函数数/token 占比 + 色条（🟩自研 🟨框架 🟥同源 ⬜外部 ▫️样板）。
2. **各目录来源构成**：每目录的堆叠色条 —— 即「结构指纹」（src/ 97%自研、arceos/ 82%框架）。
3. **声明-事实交叉核查**：从 stage-3 注入的 `xcheck_<target>.json`（§5.6 的三条判定全 ✅）。
4. **选手自研函数清单**：ORIGINAL 按规模 top40，每条带 file:line（handle_syscall/sys_mmap/sys_futex…）。
5. 真实工作量估算（自研+同源 token，扣除框架/外部）。

`classify_provenance` 抽成 `provenance.py` 的共享函数，阶段2 CLI 与阶段4 报告共用同一分类逻辑。

### 5.9 双范式端到端 + 流水线自动化（最终集成）
报告生成器对**两种范式**都跑通，共用同一套 `classify_provenance`：

| 作品 | 范式 | 框架基准 | 结果（token 倾向） |
|---|---|---|---|
| T202510216995249-4014 | 组件化(ArceOS) | `_baseline_oscomp-arceos` | 框架 61% + 同源 13% + 自研 14% |
| T202410214992509-3687 | 宏内核(npucore) | `none`（无框架，更早同族作 base） | EXTERNAL 11315(GNU bash/dependency) + PEER 223 + 自研 31 |

集成中修掉的三个真实缺口：
1. **框架基准可选**：宏内核传 `none`，PORTED-FRAMEWORK 为空，更早同族成员经 PORTED-PEER 充当 base（DESIGN §4「按范式选骨架」落地）。
2. **peers 自动解析**：阶段1 持久化 `output/lineage_clusters.json`（families / peers / older_peers / year），阶段2/4 自动读取，不再手敲 CLI 参数；框架基准自身从 peers 中剔除（避免框架代码误判为 PEER）。
3. **vendored 识别下沉到共享层**：`is_vendor`（正则匹配 `bash-*/dependency/busybox/...` 等顶层第三方目录）移入 `provenance.py`，`classify_provenance`、`attribute.py`、`report.py` 共用。否则 npucore 的 GNU bash(345k tok)、dependency(248k tok)会淹没选手真实工作。验证 §9.2「不能只靠 `vendor/` 目录名」。

**注意**：宏内核作品里 `rustsbi-k210/` 仍出现在目录表中——它是 RustSBI 的 vendored 副本，当前 `VENDOR_RE` 未覆盖 `rustsbi*`。这类「框架/SBI 的 vendored 副本」最终应由阶段3 LLM 读 Cargo/Makefile 声明确认，而非靠扩充正则（否则又回到预设清单的老路）。

### 5.10 全库查重总览（`scripts/overview.py`）
阶段1 的集群数据汇成评委用的俯视图（`output/_overview/index.html`，17KB），纯读 `lineage_clusters.json`、零计算：
1. **⚠ 同届复审重点**：同年 + 双向 containment ≥ 0.80 的边（9 个）。同届无先后可循，是最该人工核查的互抄候选（如 2024 同届 `T...605-85 ↔ T...009-1211` = 0.945）。
2. **跨届派生关系**：老 ← 新 有向边 top30。
3. **血缘家族**：18 个家族按规模列出谱系链（按届号排序）。
4. **孤儿榜**：best-containment < 0.20 标「★ 强原创候选」（zCore 0.08 等 25 个）。

`lineage_idf.py` 的导出扩展为含 `edges`（有向 + 同届标记）、`orphans`。

### 5.11 三色架构图（`scripts/report.py` 的 `mermaid_arch`）
单作品报告接入 Mermaid 模块级调用图，节点按主导出身染色，双范式验证通过：
- **ArceOS 作品**：`arceos` 模块🟨框架底座、`api/imp`🟩自研、`apps`🟥同源共享 —— 一眼看出「框架底座 + 自研系统调用层」的结构。
- **宏内核 npucore**：`os/fs`、`os/mm`、`os/syscall` 等真实内核模块，vendored 的 bash/dependency 已排除。

机制：`functions_and_edges` 一次 atlas 构建同时返回函数 meta（含 `fn_id`）与内部调用边；按模块（路径前两段）聚合函数 token，模块取主导 provenance 染色；模块间调用边来自 atlas 调用图，取 top14 模块 + top40 边保证可读。色板与贡献表一致（🟩自研 🟨框架 🟥同源 ⬜外部 ▫️样板）。

### 5.12 全库跑通发现：语料库覆盖缺口的自诊断
155 个作品全量跑完后，最高分同届对 `T202410213992605-85 ↔ T202410487993009-1211`（均 2024 届，双向 containment 0.96/0.97）揭示一个系统特性：
- 两者对每个**库内**祖先候选（xv6-k210、git_push…）的 containment **完全相同**（0.42/0.42、0.56/0.56），说明同源。
- 但它们**互相** 0.96，**远高于**对任何库内祖先的 0.56 —— 意味着约 40 个百分点的共享代码不在任何已收录祖先里。
- README 自报：A 基于 `xv6-loongson`、B 是华科 2023 获奖作 AVX 的 LoongArch 移植 —— 它们共享一个**语料库未收录**的 LoongArch 底座。

**结论（系统能力，非缺陷）**：当一组作品互相 containment 远高于它们对任何库内成员的 containment 时，信号本身在说「它们共享一个你没收录的祖先」。全库分析因此能**自诊断语料库覆盖缺口**，提示应补收哪些上游（此处：xv6-loongson / AVX-2023-LoongArch）。方向仍无法判定（同届无时序 + 真底座不在库，命中 §9.4 两条限制的交汇）。

### 5.13 声明-事实核查端到端（Claude 扮演 stage-3b，作品 605-85）
首个真实的「声明 vs 事实」闭环（非手敲），验证整套系统的核心价值主张：
- **声明提取 bug 修复**：`declarations.py` 原只认 `github.com`，漏了大赛实际托管的 `gitlab.eduxiji.net` —— 几乎所有参赛作品的血缘引用都在后者。修复后 605-85 的 `readme_refs` 抓到 `T202410487993009/AVX-LoongArch64`。
- **闭环**：指纹标记 605-85 与同届 `T202410487993009-1211`（AVX-LA）containment **0.91**（同簇唯一高相似 peer）→ 确定性提取从 README 抓到它声明了这个 gitlab 引用 → 判定**声明属实、诚实借用，非瞒报抄袭**。
- **散文血缘需 LLM 补读**：「基于 xv6-loongson」无 URL，确定性提取抓不到，由 Claude 读 README 补上。
- 报告 `xcheck` 区产出 4 行真实判定（3 ✅ + 1 ⚠「同届高度同源、方向无法判定、建议人工复核借用边界」）。

**这证明了系统设计的分工**：确定性层标记「谁和谁像、像多少、自报了什么结构化引用」，LLM 只补读散文血缘 + 给出「属实/瞒报」的语义判定。最有价值的输出正是两者交汇处——此例是「诚实借用」，反例（声称自研却指纹命中他人）会在同一机制下显形。

---

## 11. 当前实现状态（截至本轮）

五阶段全部有可运行实现，两种范式（宏内核 / 组件化）端到端验证：

| 阶段 | 脚本 | 状态 |
|---|---|---|
| 0 索引 | `code_atlas`（复用）+ `.fp_cache/` | ✅ 160 repo 缓存 |
| 1 血缘分流 | `lineage_idf.py` → `lineage_clusters.json` | ✅ 18 家族/孤儿/边 |
| 2 出身分类 | `provenance.py`（`classify_provenance` 共享） | ✅ 五分类 + token 下限 + vendor 检测 |
| 3a 声明提取 | `declarations.py`（Cargo/.gitmodules/README） | ✅ 确定性，已接入报告 |
| 3b LLM 核查 | （Claude 扮演验证，薄 MCP+Skill 待建） | ◐ 机制验证，未产品化 |
| 4 报告组装 | `report.py`（单作品 + 三色架构图 + 声明区）+ `overview.py`（全库） | ✅ 双范式 HTML |

**确定性层（0/1/2/3a/4）已完整可跑**，含三色架构图与自报依赖提取。剩下属 LLM/展示，机制均已验证：
- **3a 的能力边界（实测）**：确定性提取能抓结构化引用（Cargo git 依赖、.gitmodules、README 的 github URL），但抓不到散文血缘声明——如作品 605-85 的 README 写「基于 xv6-loongson」却无 URL，`readme_refs` 为空。**这正是 LLM 不可替代的部分**：读懂自然语言里的来源声明，再与指纹事实交叉核查。
- **3b LLM 核查**：读散文血缘 + 四类标注 + 创新识别，产出 `xcheck.json`（现手工注入，待自动化）。
- **创新工作区**：指纹全库 NOVEL 簇 + LLM 解读，单列于报告（§7）。

**下一步建议**：① 阶段3b 薄 MCP（`function_attribution`/`read_function`/`validate_draft`）+ Skill（范式判定 + 四分类规范 + 报告格式 + 散文血缘核查），消费 `declarations.py` 的结构化输出、补读散文、产出 `xcheck.json` 与创新区；② headless 全库驱动已具备（`run.py --all`）。

---

## 6. 完整流程（最终版）

```
阶段0   语料索引     参赛 repo + 框架基准建 atlas+指纹                        [确定性]
                    框架基准包括:oscomp/arceos(及历史版本)、rCore、xv6 等
阶段1   血缘分流     双向 containment 取 min + 届号定向 + 并查集              [确定性]
                    → 范式家族(xv6系/npucore系/ArceOS系) + 孤儿
                    containment 高低本身区分范式:宏内核 fork=0.95+, ArceOS系=0.4-0.7
阶段2   指纹分类     每函数在「对应版本基准」里找匹配 → 出身候选              [确定性]
                    COPIED / DISGUISE / MODIFIED / NOVEL
                    产出:模块级出身占比 + LLM work-list(仅 MODIFIED+NOVEL)
阶段3   LLM 解读     ① 读 Cargo/Makefile/submodule/README → 范式 + 依赖清单 + 自报血缘  [LLM,最小]
                    ② 交叉验证:声明 vs 指纹事实 → 四类标注 + 瞒报检测
                    ③ 读 ORIGINAL 簇 → 识别并描述创新功能
阶段4   报告组装     按范式选骨架(宏内核→14子系统树; ArceOS系→组件依赖图)    [组装]
                    + 创新工作区 + 三色架构图 + 贡献占比表 + 声明核查
```

**与旧流程的根本差别**：前三阶段零 LLM，LLM 只在阶段3 处理那 ~1% 的差异/新增函数。区分度、溯源、四分类全由确定性指纹层完成，LLM 只做不可替代的「语义解释 + 声明解读」。

---

## 7. 创新功能怎么展示（GUI / Wayland 等）

固定 14 子系统树**没有**「Wayland 支持」「GUI」这种节点，会埋没创新。分两类处理：

- **(a) 能映射到现有子系统**：挂最近节点（Wayland→IPC/Network，GUI 帧缓冲→`DeviceDriver.GPUDisplay`），但标记为 ORIGINAL + 创新。
- **(b) 现有树容不下**：指纹在全语料库零匹配且聚成新模块（如一个 `wayland/` 目录的互调函数组）= 最强创新信号 → 单列「**超出标准内核范畴的创新工作**」区，由 LLM 读这些 NOVEL 函数 + 选手文档总结。

**动态架构图（重用 commit f68f9ff）在此价值巨大**：固定树负责标准子系统三色染色，动态架构图负责画出固定树容不下的创新模块。固定 taxonomy 保证可跨作品对齐，动态图保证创新不被埋没——两者都要。

---

## 8. 最终报告形态

```
报告
├── 贡献占比表:外部依赖 X% / 移植自前代 Y% / 自研 Z%
│     └─ 声明 vs 事实 一致性核查(有无瞒报抄袭)
├── 主视图(按范式):
│     · 宏内核 → 标准 14 子系统树,每节点三色 🟦自研 🟨移植(标来源) ⬜外部(标库名+版本)
│     · ArceOS 系 → 组件依赖图,每 crate:⬜官方原样 / 🟨fork改过 / 🟦自研
├── ★创新工作区(动态):指纹全库 NOVEL + LLM 解读(Wayland/GUI 等)
└── 架构图(Mermaid,三色染色,含创新模块)
```

---

## 9. 实现约束（验证逼出来的硬规则）

1. **基准库必须版本敏感**。ArceOS 系必须用大赛 fork `oscomp/arceos`（出自 `https://github.com/oscomp/arceos.git`，oscomp = 大赛官方组织）而非上游 `arceos-org/arceos`，且收录对应时间点版本。否则版本漂移污染出身判定（实测误差 ~40 个百分点）。同理 xv6-k210 fork 自早期 xv6。
2. **vendored 代码识别不能只靠目录名**。`vendor/`（`cargo vendor` 生成的 crates.io 依赖）和单独 vendor 的框架（如 `arceos/` 目录）都是「非自研但 vendored」，但意义不同（包依赖 vs 框架底座），要分开标注。判定靠指纹 + 声明，不靠目录名。
3. **逐函数 jaccard 不可用于量化改动量**（重构击穿）。
4. **方向判定依赖时间证据**。无 git 时间/届号时，只能标「同源，方向待定」，不能断言谁抄谁。
5. **外部依赖参考库不预设**。LLM 现场读每个项目的声明文件提取。

---

## 10. MCP / Skill 的定位（下游决策，先别迁）

- **阶段 0-2、4 是批处理流水线，不该做成 MCP**（在 Claude 介入前跑完，产物落盘）。这是项目主体和 80% 价值。
- **只有阶段 3（交互式读差异/声明、产报告）适合 Claude Code + 薄 MCP + Skill**：
  - 薄 MCP 暴露：`lineage_lookup` / `function_attribution` / `read_function` / `diff` / `validate_node_draft`（保留证据存在性校验，反幻觉）。
  - Skill 编码：范式判定规则 + 四分类标注规范 + 报告格式 + 内核树 taxonomy。
- 验证中我（Claude）已扮演 stage-3 成功产出真实 diff，证明「Claude 当大脑读 work-list」可行。
- **现在别迁**：先把确定性流水线和报告跑通，再决定阶段3 走 Claude Code 还是留自研 agent。确定性流水线不关心 LLM 由谁托管。

---

## 附：验证脚本清单

| 脚本 | 作用 | 状态 |
|---|---|---|
| `scripts/fp_validate.py` | 函数指纹验证（噪声 1%、换皮零误报、揭示重构击穿） | ✅ |
| `scripts/lineage_matrix.py` | 全库 all-pairs 裸 containment 矩阵 | ✅ |
| `scripts/lineage_idf.py` | IDF 加权 + 届号定向 + 并查集聚簇（18 家族/孤儿榜） | ✅ |
| `scripts/attribute.py` | 函数级溯源 + vendor 排除 + 生成 LLM work-list | ✅ |
| `scripts/provenance.py` | 四分类出身（EXTERNAL/FRAMEWORK/PEER/ORIGINAL/TRIVIAL）+ 共享分类函数 | ✅ |
| `scripts/report.py` | 阶段4 报告组装 → 自包含 HTML（贡献表/目录构成/声明核查/自研清单） | ✅ |
| `repos/_baseline_oscomp-arceos/` | 大赛 fork ArceOS 框架基准（版本敏感） | ✅ |
| `.fp_cache/` | 160 个 repo 指纹缓存，复跑秒级 | ✅ |

依赖（均在 requirements.txt）：networkx、tree-sitter-c/cpp/rust、numpy。
未改动任何现有生产代码（agent_d.py / agent_c.py 原样）。
