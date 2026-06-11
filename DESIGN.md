# OS-Agent 查重流水线 — 设计文档

> 技术实现参考。使用方法见 [README.md](README.md)。

## 核心设计原则

**Python 脚本只做确定性计算，Agent（Claude Code）做所有判断。**

- 脚本产出的数据：hash、集合交运算、per-directory overlap —— 这些都是 Agent 无法手工计算的
- Agent 的判断：哪些是外部依赖、谁是谁的 base、某个函数是否真的抄袭 —— 需要读文档+源码+理解上下文
- Agent 通过 `exclude_prefixes` 参数把判断结果传给脚本，脚本只在过滤后的数据上计算

## 流程总览

```
Agent 启动
  │
  ├─ Phase 0: git branch -a / git log / git show  # Agent bash 探索分支
  │     git checkout <selected_branch>
  │
  ├─ Phase 1: repo_metadata(target)             # xlsx 权威元数据
  │     compile_flags(target)                   # LSP 环境
  │     build_fingerprint(target, branch=...)   # 分支感知指纹
  │     读 repo 结构 + README + 文档
  │
  ▼
  search_similar(target, exclude_prefixes=[...], branch=...)
  │  token + AST 双向包含, metadata 驱动 year/is_framework
  │
  ▼
  Agent 选 base
  │
  ▼
  compare_functions(target, base, exclude_prefixes=[...], branch=..., base_branch=...)
  │  summary: COPIED/DISGUISE/MODIFIED/NOVEL
  │
  ▼
  Agent 读源码写分析 → 用 report.py 出 HTML shell → 填分析
```

---

## 文件清单

### 确定性计算 (`scripts/`)

| 文件 | 功能 |
|---|---|
| `fingerprint.py` | 建指纹。`build_units(repo, branch)` → token hash + AST shape hash + asm MinHash。分支感知缓存到 `.fp_cache/`。`run.py --all-branches` 离线预建全部 |
| `search.py` | 1-vs-N 搜索。`search(target, exclude_prefixes, branch, metadata)` → `[{repo, branch, combined, ...}]`。默认加载全部 branch cache，返回 per-branch 候选。metadata 驱动 year/is_framework |
| `attribute.py` | 函数级对比。`compare_units(target, base, exclude_prefixes, branch, base_branch)` → `{summary, by_file}` |
| `compile_flags.py` | 为 repo 生成 `compile_flags.txt`（架构+include+宏） |
| `report.py` | 报告流水线：`skeleton` 生成固定 112 节点骨架（空 color/stats/analysis 槽 + 每节点 scope），Agent 填值后 `render` 出三色 HTML（主色+构成条+⚠改名照搬标记+context 活文档） |
| `batch.py` | 批量指纹构建 |
| `run.py` | 预建 corpus 指纹：`--build --all-branches` 覆盖全部 repo×分支 |

### 工具层 (`tools/`)

| 文件 | 功能 |
|---|---|
| `code_atlas/minhash.py` | MinHash 签名 + jaccard 估计（底层指纹原语） |
| `code_atlas/ast_shape.py` | AST 形状哈希，只 hash 节点类型，不要变量名/字面量。同结构→同hash |
| `code_atlas/asm_tokenize.py` | 汇编 tokenizer：寄存器→REG，标号→LBL，保留助记符/偏移。按 label 块切分 |
| `code_atlas/extractor.py` | tree-sitter 全仓库扫描器 |
| `code_atlas/normalize.py` | token 归一化 |
| `lsp_ops.py` | LSP 客户端（clangd/rust-analyzer，含退化链） |
| `file_ops.py` | PDF/Docx 读取 |

### 核心层 (`core/`)

| 文件 | 功能 |
|---|---|
| `metadata.py` | MetadataManager：加载 xlsx，URL↔repo_name 双向索引，替代硬编码 FRAMEWORKS |
| `code_atlas/builder.py` | Code atlas 构建器：tree-sitter 扫描 → 函数/类型/边 → PageRank → 归一化token |
| `kernel_tree.py` | 固定骨架：14 子系统 / 112 叶子节点 + 每节点 `NODE_SCOPE`（工作范围边界）+ `VOCAB_BY_NODE` 命名建议词汇表 + `ANALYSIS_BATCHES_V2` 跨模块分析批次 |
| `evidence.py` | 证据存储 + 确定性 hash ID |

### 交付层

| 文件 | 功能 |
|---|---|
| `mcp_server.py` | MCP server：12 个工具（含 4 LSP + metadata） |
| `SKILL.md` | Agent 工作流：Phase 0 分支探索 → Phase 1 认识 → Phase 2 搜索 → Phase 3 对比 → Phase 4 报告 |
| `.mcp.json` | MCP 配置 |

---

## 核心方法

### 指纹维度

**Token 指纹**：tree-sitter 解析 → normalize（alpha-rename 变量，保留函数名/类型名）→ SHA256 前 16 位。汇编：保留助记符，寄存器/标号归一化，保留偏移值。

**AST 形状哈希**：`ast_shape.py` 只 hash AST 节点类型，不要变量名/字面量。同结构→同 hash。**抗重构改编**：骨架相同但目录/函数名/变量名全变也能识别。

### 双向 containment

`min(|A ∩ B| / |A|, |A ∩ B| / |B|)` —— 设计上是抑制大库偏置的（小库说"我 40% 在你里"，大库说"你只占我 2%"，取 min 自动过滤）。但在包含大量外部依赖时失效——两个都 vendored 了同一版 arceos 的作品会因为外部代码拿到虚高的 combined。

**解决方案**：Agent 通过 `exclude_prefixes` 过滤外部代码后再搜索，双向 min 在学生代码上重新生效。

### 双维度 combined

`combined = max(token_min, ast_min)` —— 任一维度有信号即采纳。AST 维度处理 token 维度的假阴性（重构/改名），token 维度处理 AST 维度的假阴性（简单函数 AST 相似但代码不同）。

### 四分类（compare_functions）

```
COPIED:    target代码 fp == base全量中某fp 且同名   → 照搬
DISGUISE:  target代码 fp == base全量中某fp 但改名    → 抄袭信号
MODIFIED:  target代码 同名 但 fp不同                → 改动了（重点分析）
NOVEL:     target代码 fp和name都不在base中           → 自研
```

---

## 关键设计约束

### 排除外部依赖：Agent 判断，脚本接受

Agent 读目标 repo 的目录结构 + Cargo.toml + README + 设计文档后，自行判断哪些是外部依赖。判断结果通过 `exclude_prefixes` 列表传给 `search_similar` 和 `compare_functions`。

### 基准库版本敏感

ArceOS 系必须用 `oscomp/arceos`（大赛 fork），非上游 `arceos-org/arceos`。

### 方向依赖时间证据

指纹本身无向。届号/git 时间用于定向（老←新）。同届高相似无法断言谁抄谁——只能标记为"同届互抄复审重点"。

### 低分 + 声明来源 → 强制对比（rv6 案例）

README 声明"基于 xv6-k210"但指纹极低（0.088），Agent 仍须强制 deep compare。因为骨架相同+实现全重写会击穿两种指纹。


---

## MCP 工具（12 个）

| 工具 | 输入 | 输出 |
|---|---|---|
| `repo_metadata` | target | {year, school, team, competition, is_framework} |
| `build_fingerprint` | target, branch?, all_branches? | {units, fingerprints, ast_fingerprints, languages} |
| `search_similar` | target, exclude_prefixes?, top_k?, branch? | [{repo, branch, combined, token_min, ast_min, is_framework, year, school, overlap_by_dir}] |
| `compare_functions` | target, base, exclude_prefixes?, branch?, base_branch? | {summary: {copied,disguise,modified,novel}, by_file} |
| `node_taxonomy` | node_id? | 14 子系统 / 112 叶子节点 + 每节点 scope + vocab 命名建议 + 跨模块分析批次 |
| `compile_flags` | target | {arch, flags} |
| `lsp_definition` | target, symbol, file? | 文件:行号 位置（含回退链信息） |
| `lsp_references` | target, symbol, file? | 全项目 file:line 引用列表 |
| `lsp_document_outline` | target, file | AST 结构大纲（函数/结构体+行号） |
| `lsp_call_graph` | target, symbol, file, direction?, max_depth? | 递归调用链树（outgoing/incoming/both） |
| `lsp_set_target_arch` | target, arch | 覆盖目标 triple + 重启 LSP |
| `read_doc` | target, path, start_page?, end_page? | PDF/Docx 文本内容 |

分支选择全部由 Agent 用 bash 完成（`git branch -a`, `git log`, `git show <branch>:README.md`）。所有分支指纹离线预计算（`run.py --all-branches`），search 返回 per-branch 候选——偏好从数据自然浮现。

---

## 新增模块

| 文件 | 功能 |
|---|---|
| `core/metadata.py` | MetadataManager：加载 `collected-data.xlsx`（168 条），构建 URL↔repo_name 双向索引。155 repos 匹配 xlsx，8 frameworks。替代 `search.py` 中硬编码 FRAMEWORKS 和脆弱的正则 `_extract_year()` |
| `scripts/report.py` | 报告流水线：`skeleton` 生成固定 112 节点骨架（空 color/stats/analysis 槽 + 每节点 scope），Agent 填值后 `render` 出三色 HTML（主色+构成条+⚠改名照搬标记+context 活文档） |
| `scripts/batch.py` | 批量指纹构建 |

## 分支处理

**所有分支预建指纹**（`python scripts/run.py --build --all-branches`）。缓存命名：
- `fpset_{name}__{branch}.pkl` — 分支名中的 `/` 替换为 `-`

Agent 用 bash 探索分支（`git branch -a`, `git log`, `git show <branch>:README.md`），无需脚本替 Agent 做选择。`search_similar` 默认加载所有分支指纹，结果自然标出每个候选匹配的具体分支。偏好从数据浮现——比如 `qemu-final` 分支高分自然反映初赛方向。

## 内核设计树

`core/kernel_tree.py` 定义固定骨架：14 子系统 / 112 叶子节点。每节点有 `NODE_SCOPE`（一句工作范围边界，Agent 到节点先读 scope 明边界，再决定哪些函数挂进来）。`VOCAB_BY_NODE`（112 条）为每个节点提供机制标签，**仅作命名建议**——帮 Agent 用统一术语表达（如"MLFQ 调度"），Agent 可动态扩充，不分级、不判工作量。`ANALYSIS_BATCHES_V2` 定义跨模块依赖分析批次（前序批次结论喂后续）。**判断靠指纹 diff，命名靠 vocab**：函数→节点归属由 Agent 判断，不要求穷举所有函数。

## 组装依赖

requirements.txt: `mcp`, `networkx`, `numpy`, `openpyxl`, `tree-sitter-c/cpp/rust`, `pypdf`, `python-docx`。Python 3.10+。

## .fp_cache

指纹缓存（gitignored）：`units_{name}__{branch}.pkl`、`fpset_{name}__{branch}.pkl`、`astset_{name}__{branch}.pkl`。分支名中的 `/` 替换为 `-`。`branch=""` 时加载所有旧格式文件（向后兼容）。删 `.fp_cache/` 即强制重建。

## Corpus

`repos/`（gitignored）含 ~160 参赛内核 + 教学原型。`collected-data.xlsx` 通过 git remote URL 桥接到本地 repo 目录。`repos/_baseline_oscomp-arceos/` 是 ArceOS 大赛 fork。
