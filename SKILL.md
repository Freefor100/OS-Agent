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

**同届互抄检测**：
```
repo_metadata(target) → year
search_similar 返回的候选中同届 (year == target_year) 且 is_framework == false
同届高分对（combined ≥ 0.30）→ 报告单独列出，标记"⚠ 同届互抄复审重点"
```

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
# 1. 聚合数据
python scripts/report.py --data report_data.json --output output/<target>/

# 2. Agent 打开生成的 index.html，找到 <!-- AGENT_DESC: <node_id> --> 标记
#    在每个标记处填入自然语言分析

# 3. 替换 <!-- AGENT_MERMAID --> 为实际 Mermaid 架构图
```

报告结构（自上而下）：

1. **作品元信息**：名称、届号、学校、队伍、范式（宏内核/组件化）、架构
2. **贡献占比表**：自研 X% / 移植 Y% / 外部依赖 Z%
3. **血缘总览**：最相似候选列表，标注是否声明
4. **声明核查**：选手声称 vs 指纹事实
5. **内核设计树**（主体）：14 子系统 × 三色标注 + 详细/简要描述
   - 🟨 黄色 = COPIED（继承自 base，未改动）
   - 🟥 红色 = MODIFIED（相对 base 改动）
   - 🟦 蓝色 = NOVEL（自研）
   - ⬜ 灰色 = 未实现 / 外部依赖
6. **架构图**：Mermaid 三色染色
7. **创新功能区**（如有）：超越标准子系统的自研模块
8. **汇编覆盖声明**：汇编文件数、分析粒度、已知局限

---

## 标注颜色说明

| 节点内函数构成 | 分析深度 | 标注颜色 |
|---|---|---|
| 全是 COPIED | **简要**：标注"继承自 {base}，未改动" | 🟨 黄色 |
| 含 MODIFIED 或 NOVEL | **详细**：读源码写分析 | 🟥（改为主）/ 🟦（新为主） |
| 无函数 | **简要**：标注"未实现" | ⬜ 灰色 |

## 对比报告 vs 描述报告的差异

| | 对比报告 | 描述报告 |
|---|---|---|
| 触发条件 | 有相似候选或声明了来源 | 无任何候选且无声明 |
| base 参数 | 传给 compare_functions | 空 |
| COPIED 标注 | "继承自 {base}" | "来自外部依赖" 或 "基本实现" |
| MODIFIED | 读 diff + 详细描述 | 不适用 |
| NOVEL | "相比 base 新增" + 详细描述 | "选手自研" + 详细描述 |
| 报告主叙事 | "基于 {base} 的增量工作" | "独立设计的内核" |

## 机制词汇表使用指引（VOCAB_BY_NODE）

`node_taxonomy(node_id)` 返回每个节点的机制标签（来自 `core/kernel_tree.py:VOCAB_BY_NODE`）：
- **"primary" 标签** → 该节点的期望实现机制
- **"display" 标签** → 辅助识别模式
- **"weak_hint" 标签** → grep 搜索关键词
- 用作读源码分析时的 checklist，帮助 Agent 将分析结果路由到正确节点
