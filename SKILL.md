# OS-Agent Skill: 内核查重与描述报告

## 任务

分析一个内核作品，产出评委可读的 HTML 报告。报告以**内核设计树**（14 子系统，112 叶子节点）为骨架，每个节点按代码出身染色，自研/修改部分附详细自然语言描述。

## MCP 工具

以下 12 个工具通过 MCP 暴露。文件操作（读源码/grep/列目录/git clone/checkout/branch/log/diff/show）直接用 Claude Code 内置的 bash。

| 工具 | 用途 | 何时调用 |
|---|---|---|
| `repo_metadata(target)` | xlsx 元数据（年份/学校/队伍） | Phase 1 第一步 |
| `build_fingerprint(target, branch, all_branches)` | 建指纹（分支感知） | Phase 0/1 |
| `search_similar(target, exclude_prefixes, top_k, branch)` | 1-vs-N 查重 | Phase 2 |
| `compare_functions(target, base, exclude_prefixes, branch, base_branch)` | 函数级四分类 | Phase 3 |
| `node_taxonomy(node_id?)` | 内核设计树骨架 + 机制词汇表 | 组装报告前 |
| `compile_flags(target)` | clangd 编译标志 | Phase 1 |
| `lsp_definition(target, symbol, file)` | LSP 跳转定义 | 读源码分析时 |
| `lsp_references(target, symbol, file)` | LSP 查全项目引用 | Phase 3 深度分析 |
| `lsp_document_outline(target, file)` | LSP 文件结构大纲 | 读大文件前 |
| `lsp_call_graph(target, symbol, file, direction, max_depth)` | LSP 调用链图 | Phase 3 关键路径分析 |
| `lsp_set_target_arch(target, arch)` | 覆盖 LSP 目标架构 | cfg 代码灰化时 |
| `read_doc(target, path)` | 读 PDF/Docx 文档 | 读选手报告/设计文档 |

## 环境要求

在执行任何 Python 脚本（如 `scripts/report.py`）之前，**Agent 必须确保当前处于正确的 Python 运行环境**（通常是已执行 `conda activate os_agent` 或已激活 `.venv` 的 bash 会话）。

## 流程

### Phase 0: 探索分支

参赛作品通常有多个分支（初赛 QEMU 版、决赛开发板版、重构版等）。Agent 用 bash 探索：

```bash
git -C repos/<target> branch -a                         # 列所有分支
git -C repos/<target> log --oneline -10 <branch>        # 看提交历史
git -C repos/<target> log --format="%aI" -10 <branch>   # 看提交时间
git -C repos/<target> show <branch>:README.md | head -30 # 读分支内 README
```

**快速判断**：
- 只有一个分支 → 直接用
- 分支名含 `final`/`finals`/`submit`/`deployed` → 优先看
- 分支名含 `board`/`vf2`/`k210`/`la64` → 硬件适配分支
- 提交集中在 3-6 月 → 初赛周期；集中在 7-8 月 → 决赛周期

**如果只有一条线性链**（所有 feat 分支都合并到了 main）→ 直接选 main：
```bash
git -C repos/<target> checkout main
```

**如果有分叉**（如 `qemu-final` vs `vf2-board` vs `la64-board`），先全部分支建指纹，让搜索来揭示相似度：
```bash
git -C repos/<target> checkout qemu-final
build_fingerprint(target, all_branches=True)
```
然后对当前主要关心的分支建指纹、单独搜：
```bash
build_fingerprint(target, branch="qemu-final")     # 只建当前分支（已有则跳过）
search_similar(target, branch="qemu-final", exclude_prefixes=[...])
# 返回结果自然显示各候选的哪个分支最相似
```

**如果分叉差异大**，分别分析：
```bash
git -C repos/<target> diff qemu-final...vf2-board --stat   # 看差异
# 差异 >30% 文件 → 两个分支各跑一次 Phase 2-4
```

### Phase 1: 认识作品

```
repo_metadata(target)                               # xlsx 权威元数据
compile_flags(target)                               # LSP 环境

# 确保有指纹（离线已预计算所有分支，这里不用等）：
build_fingerprint(target, branch=...)               # 当前分支，已有则秒返

ls repos/<target>/                                  # 目录结构
cat repos/<target>/Cargo.toml                       # 项目结构
cat repos/<target>/README*                          # 声明
read_doc(target, "设计文档.pdf")                     # 设计文档
```

Agent 自己判断：

- **哪些目录是外部依赖**：`vendor/`、`.gitmodules` 里的 submodule、README 声明的参考项目源码目录、明显外部项目目录（`bash-*`、`musl-*`、`lwip-*`）
- **哪些是学生代码**：Cargo workspace member、源码目录（`os/`、`kernel/`、`src/`、`api/`、`user/`）
- **README 声明的来源**："基于 xv6-k210"、"移植了 arceos 的文件系统"

形成 `exclude_prefixes = ["vendor/", "dependency/", "bash-5.1.16/", ...]`

### Phase 2: 搜索相似作品 + 选择 base

```
search_similar(target, exclude_prefixes=[...], branch=...)
```
当 corpus 包含所有分支的指纹时（`corpus_fingerprints()` 默认加载全部 `fpset_*__*.pkl`），返回的每个候选都标明了匹配的具体分支：

```
candidates: [
  {repo: "xv6-k210", branch: "scene", combined: 0.852, year: 2022, ...},
  {repo: "xv6-k210", branch: "main",  combined: 0.721, ...},
  {repo: "oskernel2023-zmz", branch: "final", combined: 0.634, ...},
]
```

偏好从数据中自然浮现——不需要脚本判断优先级。Agent 根据结果判断：
- **同一个 repo 的多个分支都高分** → 选最高的那个分支做 base
- **哪个分支最像** → 本身就反映了比赛阶段：`qemu-final` 高分暗示初赛方向，`vf2-board` 高分暗示决赛方向
- **高相似度 + 集中在核心目录** → 可能抄了 → 选为 base
- **低相似度** → 检查 README 声明的来源 → 强制对比

**base 选择规则（关键）**：

base = 指纹搜索里**最相似的已存在作品**，即选手的**真实起点**（通常是近一两届的参赛作品）。

> ⚠ **不要选谱系根**（如 MIT xv6-riscv）。同谱系内核一届届迭代：2024 的作品基于 2023 某作品做增量，2023 又基于 2022。跟谱系根比，得到的 delta 里混着历届所有人的共同继承，量出来的"工作"根本不是这队做的。对**最相似的近届作品**做 compare，delta 才是这队的真实增量。

**方向判定（用 xlsx 年份，不用 git 时间线）**：

```
repo_metadata(target) → target_year
对每个高分候选看 xlsx year：
  候选 year < target_year   → base 是往届 → delta = 本队真增量（合法/跨届抄袭）
  候选 year == target_year  → 同届高分对（combined ≥ 0.30）→ 互抄
                              → 报告单独列出，标"⚠ 同届互抄复审重点"（年份无法定向，交人工）
  跟谁都不像 + 无 README 声明 → 独立设计（描述报告模式）
```

> 现在只分析最新一届作品，现实场景就两类：**同届互抄** 和 **抄前几届**。

如有 README 声明的参考仓库不在本地：

```bash
git clone <url> repos/<name>
```
然后 `build_fingerprint(<name>)`。

### Phase 3: 深度对比

```
compare_functions(target, base, exclude_prefixes=[...], branch=..., base_branch=...)
```

返回：

- `summary`：COPIED / DISGUISE / MODIFIED / NOVEL 计数
- `by_file`：每个文件的函数清单，每个函数有 `name, status, tokens, line`

Agent 利用这些数据 + LSP 新工具：

- **COPIED 函数**：快速确认（读几行关键代码），标注"继承自 {base}，未改动"
- **DISGUISE 函数**：抄袭信号 → 用 `lsp_references` 查调用方是否也相似
- **MODIFIED 函数**：**重点** → 读目标版和 base 版源码，用 `lsp_call_graph` 追踪调用链变化
- **NOVEL 函数**：用 `lsp_document_outline` 获取文件结构，读源码，描述实现和设计决策
- **没有的函数**：标注"未实现"

对于需要详细分析的函数：
- `lsp_definition` 跳转到定义
- `lsp_references` 查所有引用点
- `lsp_call_graph(target, symbol, file, direction="both")` 追踪完整调用链
- `lsp_document_outline(target, file)` 获取大文件的结构地图

### Phase 4: 组装报告

```
# 1. 生成固定 112 节点的骨架 JSON（color/stats/analysis 留空槽，每节点带 scope）
python scripts/report.py skeleton <target> output/<target>/report_data.json [branch]

# 2. Agent 按批次顺序探索，将分析填入 report_data.json：
#    - 每节点填 color (copied/modified/novel/external)、disguise (true/false)、
#      stats ({copied,disguise,modified,novel})、size_tokens、analysis
#    - 每完成一批回写 context（base_verdict / inherited_subsystems / findings），
#      后续批次读回参考

# 3. 渲染填好的 JSON → index.html
python scripts/report.py render output/<target>/report_data.json output/<target>/
```

报告结构（自上而下）：

1. **作品元信息**：名称、届号、学校、队伍、范式（宏内核/组件化）、架构
2. **分析上下文**（context 活文档）：base 判定、已继承子系统、跨批次关键发现
3. **贡献占比表**：COPIED / DISGUISE / MODIFIED / NOVEL 计数与占比
4. **血缘总览**：Top-10 最相似候选列表，标注是否声明
5. **内核设计树**（主体）：14 子系统 × 112 叶子节点，三色标注 + 构成条 + 自然语言分析
   - 🟦 蓝色 = 独创实现 (NOVEL)
   - 🟥 红色 = 实现但修改 (MODIFIED)
   - 🟨 黄色 = 实现照搬 (COPIED)
   - 🟨 + ⚠ = 改名照搬 (DISGUISE)，突出作弊意图
   - ⬜ 灰色 = 未实现 / 外部依赖
   - 每节点下方**构成条**显示各状态真实占比（不会因单一主色掩盖"部分实现"）
6. **架构图**：Mermaid 三色染色
7. **创新功能区**（如有）：超越标准子系统的自研模块
8. **汇编覆盖声明**：汇编文件数、分析粒度、已知局限

---

## 探索顺序：按批次走，前序喂后续

Agent 调用 `node_taxonomy()`（无参）获取 `batches`（`ANALYSIS_BATCHES_V2`），**按批次顺序**探索——不是按模块，也不是拍平的 112 节点。

批次是**跨模块依赖分组**（如 batch 5 = TaskStruct + ContextSwitch + Scheduler + SpinLock + WaitQueue，因调度依赖上下文切换和锁）。**每批完成 → 回写 context.findings → 后续批次读回参考。**

每批开始时：
1. 对批内每个节点调用 `node_taxonomy(node_id)` 拿 `scope`（工作范围边界）
2. 结合 `compare_functions` 结果，读源码判断哪些函数属于该节点（这是 Agent 的判断，框架不强行路由）
3. 根据指纹 diff 判颜色 + 写分析
4. 本批完成后回写 `report_data.json` 的 context.findings

## 标注颜色说明

| 节点内函数构成 | 分析深度 | 标注颜色 | 构成条体现 |
|---|---|---|---|
| 全 NOVEL | **详细**：描述实现和设计决策 | 🟦 蓝色 | 全蓝 |
| 含 MODIFIED 或 NOVEL | **详细**：读源码 + LSP 追踪变化 | 🟥/🟦 按占比 | 红蓝 mix |
| 全 COPIED | **简要**：标注"继承自 {base}，未改动" | 🟨 黄色 | 全黄 |
| 含 DISGUISE | **重点**：改名照搬 = 作弊信号 → 用 lsp_references 查调用链 | 🟨 黄 + ⚠ 标记 | 黄底斜纹 |
| 混合（部分实现） | **按占比定主色**，构成条显示真实比例 | 占比最多者 | 多色堆叠 |
| 无函数 | **简要**：标注"未实现" | ⬜ 灰色 | 空 |

## 对比报告 vs 描述报告的差异

| | 对比报告 | 描述报告 |
|---|---|---|
| 触发条件 | 有相似候选或声明了来源 | 无任何候选且无声明 |
| base 参数 | 传给 compare_functions | 空 |
| COPIED 标注 | "继承自 {base}" | "来自外部依赖" 或 "基本实现" |
| MODIFIED | 读 diff + 详细描述 | 不适用 |
| NOVEL | "相比 base 新增" + 详细描述 | "选手自研" + 详细描述 |
| 报告主叙事 | "基于 {base} 的增量工作" | "独立设计的内核" |

## 机制词汇表使用指引（VOCAB）

`node_taxonomy(node_id)` 返回每个节点的 `vocab` 标签列表，来自 `core/kernel_tree.py:VOCAB_BY_NODE`：

- **仅作命名建议**：帮 Agent 用统一术语表达机制（如"这是 MLFQ 多级反馈队列"而非自由发挥）。
- **不分级，不判工作量**：tag 的存在性不代表选手做了工作。同谱系作品当然都有 sv39 页表、walk()、fork——但 walk() 可能 token 级逐字照搬（判 COPIED），调度器可能重写（判 NOVEL）。**真正的区分在指纹 diff + 规模，不在 tag 命中。**
- **Agent 可动态扩充**：遇词汇表没有的机制，Agent 自行命名写入分析，框架不阻拦。

> 反例：xv6-k210 与 oskernrl2022-rv6（同谱系，rv6 自述"基于 xv6-k210 改编"）——两个作品的 `walk()` 函数 token 级逐字相同（判 COPIED），"sv39 都有"这个 tag 命中毫无区分力。但 xv6-k210 用优先级多队列调度（`proc_runnable[priority]`）、rv6 用单就绪队列 `readyq_pop()`，指纹 diff 能区分出"调度器是 MODIFIED/NOVEL"。**judge by fingerprint diff, name by vocab。**
