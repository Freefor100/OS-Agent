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
  ├─ compile_flags(target)            # LSP 环境
  ├─ build_fingerprint(target)        # 建全量指纹
  ├─ 读 repo 结构 + README + 文档      # Agent 判断外部/自研
  │
  ▼
search_similar(target, exclude_prefixes=[...])
  │  token + AST 双向包含
  │  per-directory overlap 分布
  │
  ▼
Agent 选 base（搜到高分候选 or README 声明的来源）
  │
  ▼
compare_functions(target, base, exclude_prefixes=[...])
  │  summary: COPIED/DISGUISE/MODIFIED/NOVEL 计数
  │  by_file: 每个文件的函数级状态
  │
  ▼
Agent 读源码写分析 → 组装三色 HTML 报告
```

---

## 文件清单

### 确定性计算 (`scripts/`)

| 文件 | 功能 |
|---|---|
| `fingerprint.py` | 建指纹。c/cpp/rust 走 tree-sitter → token hash + AST shape hash；汇编走 tokenizer → MinHash。产出 `build_units(repo)` → 统一 unit 列表，缓存到 `.fp_cache/` |
| `search.py` | 1-vs-N 搜索。`search(target, exclude_prefixes)` → `[{combined, token_min, ast_min, overlap_by_dir, is_framework, year}]`。`overlap_by_dir` 显示相似度集中在哪些目录 |
| `attribute.py` | 函数级对比。`compare_units(target, base, exclude_prefixes)` → `{summary, by_file}`。四分类：COPIED / DISGUISE / MODIFIED / NOVEL |
| `compile_flags.py` | 为 repo 生成 `compile_flags.txt`（架构+include+宏），clangd 读取后正确解析 RISC-V/LoongArch 代码 |
| `run.py` | 预建 corpus 指纹：`python scripts/run.py --build` |

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
| `code_atlas/builder.py` | Code atlas 构建器：tree-sitter 扫描 → 函数/类型/边 → PageRank → 归一化token |
| `kernel_tree.py` | 固定骨架：14 子系统 / 112 叶子节点 |
| `evidence.py` | 证据存储 + 确定性 hash ID |

### 交付层

| 文件 | 功能 |
|---|---|
| `mcp_server.py` | MCP server：7 个工具 |
| `SKILL.md` | Agent 工作流：认识作品 → 搜索 → 对比 → 报告 |
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

## MCP 工具（7 个）

| 工具 | 输入 | 输出 |
|---|---|---|
| `search_similar` | target, exclude_prefixes?, top_k? | [{repo, combined, token_min, ast_min, is_framework, year, overlap_by_dir}] |
| `compare_functions` | target, base, exclude_prefixes? | {summary: {copied,disguise,modified,novel}, by_file} |
| `build_fingerprint` | target | {units, fingerprints, ast_fingerprints, languages} |
| `compile_flags` | target | {arch, flags} |
| `lsp_definition` | target, symbol, file? | 文件:行号 位置（含回退链信息） |
| `read_doc` | target, path, start_page?, end_page? | PDF/Docx 文本内容 |
| `node_taxonomy` | node_id? | 14 子系统 / 112 叶子节点骨架 |

---

## 内核设计树

`core/kernel_tree.py` 定义固定骨架：14 子系统 / 112 叶子节点。`EXTRA_NODE_SPECS` 提供 symbols/patterns 映射（函数名→树节点），辅助 Agent 将分析结果路由到正确节点。

## 组装依赖

requirements.txt: `mcp`, `networkx`, `numpy`, `tree-sitter-c/cpp/rust`, `pypdf`, `python-docx`。Python 3.10+。

## .fp_cache

指纹缓存（gitignored）：`units_*.pkl`（全量 unit 列表）、`fpset_*.pkl`（token hash 集合）、`astset_*.pkl`（AST hash 集合）。删 `.fp_cache/` 即强制重建。

## Corpus

`repos/`（gitignored）含 ~160 参赛内核 + 教学原型。`repos/_baseline_oscomp-arceos/` 是 ArceOS 大赛 fork。
