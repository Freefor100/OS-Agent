# OS-Agent Skill: 内核查重与描述报告

## 任务

分析一个内核作品，产出评委可读的 HTML 报告。报告以**内核设计树**（14 子系统，112 叶子节点）为骨架，每个节点按代码出身染色，自研/修改部分附详细自然语言描述。

## MCP 工具

以下 7 个工具通过 MCP 暴露。文件操作（读源码/grep/列目录）直接用 Claude Code 内置的 bash。

| 工具 | 用途 | 何时调用 |
|---|---|---|
| `search_similar(target, exclude_prefixes, top_k)` | 1-vs-N 查重（token+AST, 支持路径过滤） | Agent 识别外部依赖后 |
| `compare_functions(target, base, exclude_prefixes)` | 函数级 COPIED/DISGUISE/MODIFIED/NOVEL | 选定 base 后 |
| `build_fingerprint(target)` | 为仓库建指纹（克隆新依赖后调用） | 依赖不在本地时 |
| `compile_flags(target)` | 生成 clangd 编译标志（架构+include+宏） | 第一步（自动） |
| `lsp_definition(target, symbol, file)` | LSP 跳转定义 | 读源码分析时 |
| `read_doc(target, path)` | 读 PDF/Docx 文档 | 读选手报告/设计文档 |
| `node_taxonomy()` | 内核设计树骨架（14 子系统，112 叶子） | 组装报告前 |

## 流程

### Phase 1: 认识作品

```
compile_flags(target)                   # 准备 LSP 环境
build_fingerprint(target)               # 建全量指纹（代码+汇编）
ls repos/<target>/                      # 看目录结构
cat repos/<target>/Cargo.toml           # 项目结构（如有）
cat repos/<target>/README*              # 声明
read_doc(target, "设计文档.pdf")         # 如有设计文档
```

Agent 自己判断：

- **哪些目录是外部依赖**：`vendor/`（cargo vendored crates）、`.gitmodules` 里的 submodule 路径、README 中声明的参考项目源码目录、明显的外部项目目录（如 `bash-*`、`musl-*`、`lwip-*`）
- **哪些是学生代码**：Cargo workspace member 目录、源码目录（`os/`、`kernel/`、`src/`、`api/`、`user/`）
- **READMe 声明的来源**：如"基于 xv6-k210"、"移植了 arceos 的文件系统"

形成 `exclude_prefixes = ["vendor/", "dependency/", "bash-5.1.16/", ...]`

### Phase 2: 搜索相似作品 + 选择 base

```
search_similar(target, exclude_prefixes=[...])
```

返回每个候选的 `combined` 分 + `overlap_by_dir`（哪个目录命中最多）。Agent 据此判断：

- **高相似度 + 集中在核心目录** → 可能抄了 → 选为 base
- **高相似度 + 集中在配置文件/脚本** → 可能只是巧合模板
- **低相似度** → 检查 README 声明的来源（"基于 xxx 改编"）→ 强制对比

如有 README 声明的参考仓库不在本地：

```
git clone <url> repos/<name>
build_fingerprint(<name>)
```

同届互抄检测：

```
search_similar 返回的候选的 year + is_framework 字段
同届 = year == target_year AND is_framework == false
同届高分对（combined ≥ 0.30）→ 报告单独列出，标记"⚠ 同届互抄复审重点"
```

### Phase 3: 深度对比

```
compare_functions(target, base, exclude_prefixes=[...])
```

返回：

- `summary`：COPIED / DISGUISE / MODIFIED / NOVEL 计数
- `by_file`：每个文件的函数清单，每个函数有 `name, status, tokens, line`

Agent 利用这些数据：

- **COPIED 函数**：快速确认（读几行关键代码），标注"继承自 {base}，未改动"
- **DISGUISE 函数**：这是抄袭信号 → 读源码确认是否真的是改名拷贝
- **MODIFIED 函数**：**这是重点** → 读目标版和 base 版源码，描述改了什么
- **NOVEL 函数**：读源码，描述实现的是什么，设计决策是什么
- **没有的函数**：标注"未实现"

对于需要详细分析的函数，用 `lsp_definition` 跳转到定义，用 `bash` 的 `cat`/`grep` 读源码。

### Phase 4: 组装报告

用 `node_taxonomy()` 拿 14 子系统 112 叶子骨架，按 Phase 3 的分析结果填内容。

报告结构（自上而下）：

1. **作品元信息**：名称、届号、范式（宏内核/组件化）、架构（RISC-V/LoongArch/ARM/x86）
2. **贡献占比表**：自研 X% / 移植 Y% / 外部依赖 Z%（数据来自 compare_functions.summary）
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
