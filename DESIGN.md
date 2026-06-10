# OS-Agent 查重流水线 — 设计文档

> 技术实现参考。使用方法见 [README.md](README.md)。

## 流程总览

```
python scripts/run.py <作品名>
    │
    ├─ [A] declarations       读 Cargo.toml /.gitmodules / README
    ├─ [B] fingerprint        建指纹 (c/cpp/rust + 汇编, 缓存)
    ├─ [C] search             1-vs-N 搜索 (token + AST 双维度)
    └─ [D] report             组装 HTML: 贡献表 + 设计树 + 架构图
```

## 文件清单

### 确定性层 (`scripts/`)

| 文件 | 功能 | 公开接口 |
|---|---|---|
| `fingerprint.py` | 统一建指纹: c/cpp/rust 走 code_atlas (tree-sitter), 汇编 `.S/.s` 走轻量 tokenizer。输出统一 unit 格式 `{lang, file, name, fp, ast, sz, sig, fn_id}`。缓存到 `.fp_cache/` | `build_units(repo)` `fingerprint_set(repo)` `ast_fingerprint_set(repo)` `lang_summary(units)` |
| `provenance.py` | 五分类出身: EXTERNAL / PORTED-FRAMEWORK / PORTED-PEER / ORIGINAL / TRIVIAL。从 fingerprint.py 取数据,消费 exclude.py 排除规则。无内置硬编码列表 | `classify_provenance(units, fw, peers, exclude_rules)` `functions_and_edges(repo)` |
| `search.py` | 1-vs-N 相似搜索。双向 containment (token 维度 + AST 维度),`combined = max(tok_min, ast_min)` | `search(target, corpus, top_k)` `corpus_fingerprints(build_missing)` |
| `declarations.py` | 提取项目声明: Cargo workspace (members/exclude/path deps)、git 依赖、submodule、README 的 GitHub/gitlab 引用 | `extract(repo)` `parse_cargo_structure(repo)` |
| `exclude.py` | 排除规则引擎。消费声明数据,生成 include/exclude 规则集。不预设字典——LLM 通过 `llm_external_dirs`/`llm_student_dirs` 字段补写 | `load_rules(target)` `default_exclude_rules(repo, declarations)` `apply_exclude(rules, file)` |
| `run.py` | 一键驱动。`python scripts/run.py <target>` 跑完整 A→B→C→D；`--build` 预建全库指纹 | |
| `report.py` | HTML 报告组装: 贡献占比表 + 内核设计树(14子系统×112叶子×三色) + Mermaid 架构图 + 声明区 + 自研清单 | |
| `overview.py` | 全库总览 (v1 遗留的辅助工具) | |

**辅助脚本:**
| `attribute.py` | 函数级精查: COPIED/DISGUISE/MODIFIED/NOVEL vs 单一 base |
| `fp_validate.py` | 指纹判别力验证 (噪声/换皮/梯度) |
| `lineage_idf.py` | v1 IDF 加权聚簇 (IDF 已证无效,保留聚簇逻辑参考) |
| `lineage_matrix.py` | v1 全库 N×N 矩阵 (已弃用) |

### 工具层 (`tools/`)

| 文件 | 功能 |
|---|---|
| `code_atlas/asm_tokenize.py` | 汇编 tokenizer: 寄存器→REG, 标号→LBL, 保留助记符/偏移。按 label 块切分。复用 `minhash.signature_from_tokens` |
| `code_atlas/minhash.py` | MinHash 签名生成 + jaccard 估计 (底层指纹原语,不依赖 tree-sitter) |
| `code_atlas/ast_shape.py` | AST 形状哈希: 只 hash 节点类型,不要变量名/字面量。同结构=同hash。抗重构改编 |

### 交付层

| 文件 | 功能 |
|---|---|
| `mcp_server.py` | 8 个 MCP 工具 (FastMCP): search_candidates / attribution / unit_source / grep_repo / list_dir / node_taxonomy / declared_deps / exclude_rules |
| `SKILL.md` | Claude Code 工作流: 判类型 (含低分读声明强制对比) → attribution → sub-agent 批量详细分析 → 三色树报告 |
| `.mcp.json` | MCP 配置,指向 `mcp_server.py` |

### 语料库

| 路径 | 说明 |
|---|---|
| `repos/` | 约 160 个参赛内核 + 原型 (gitignored) |
| `repos/_baseline_oscomp-arceos/` | ArceOS 大赛 fork (`oscomp/arceos`), 作为组件化范式基准 |
| `.fp_cache/` | 指纹缓存 (units_/fpset_/astset_/exclude_ *.pkl, gitignored) |
| `output/` | 报告产物 (gitignored) |

---

## 核心方法

### Token 指纹 (归一化 token 精确哈希)

tree-sitter 解析 → `normalize.py` 归一化 (抹掉标识符名) → SHA256 前 16 位。

汇编 tokenizer 模拟相同流程: 保留助记符 (`sd/ld/csrw`), 将寄存器→`REG`、标号→`LBL`, 保留偏移值 (8/16/24)。

### AST 形状哈希

`ast_shape.py`: 只 hash AST 节点类型, 不要变量名/字面量。同结构→同hash。**抗重构改编**: 骨架相同、目录/函数名/变量名全变的"改编"。

`search.py` 的 `combined = max(tok_min, ast_min)` 策略: 任一维度有信号即采纳。

### 双向 containment

`min(A 的指纹∩B, B 的指纹∩A)` —— 抑制大库偏置 (小库说"我 40% 在你里", 大库说"你只占我 2%", 取 min 自动过滤)。

### 出身五分类

每函数判定优先级:
1. EXTERNAL — 排除规则命中 (Cargo vendor/exclude, gitmodule, 声明的外部目录)
2. PORTED-FRAMEWORK — 指纹命中框架基准 (oscomp/arceos)
3. PORTED-PEER — 指纹命中语料库更早成员
4. ORIGINAL — 无任何匹配
5. TRIVIAL — 低于 token 下限(~100) 且仅匹配 peer 的样板 (Rust new()/get()/drop())

token 下限**仅抑制 PEER 误判**, 不给自研打折——无任何匹配的小函数仍是 ORIGINAL。

---

## 关键设计约束

### 不预设外部依赖清单

外部依赖"是什么"由 Agent 读 Cargo/Makefile/README 判断。`exclude.py` 只消费声明数据, `llm_external_dirs`/`llm_student_dirs` 字段供 LLM 补写。唯一确定性排除是 `vendor/` 目录 (cargo-vendor 工具约定) 和 `.gitmodules` 路径。

### 基准库版本敏感

ArceOS 系必须用 `oscomp/arceos` (大赛 fork), 非上游 `arceos-org/arceos`。用错基准导致 ~40 个百分点版本差被误报为"选手魔改"。

### 方向依赖时间证据

指纹本身无向。届号/git 时间用于定向 (老←新)。同时代高相似无法断言谁抄谁。

### 函数级 token 下限

~100 token。低于此限的函数因无判别力排除 PEER 匹配 (不报假抄袭)。无匹配的小函数仍归 ORIGINAL。

### 已废弃方法

- **逐函数 jaccard 量化改动量**: 被 extract/inline 重构击穿 (kvminit 案例: 代码未改但逻辑被抽走, jaccard=0.00)
- **IDF 加权**: 对大库假枢纽无效; 双向 min 已消化该问题
- **全库 N×N all-pairs**: 改用 1-vs-N

### 已知极限 (rv6 案例)

README 声明"基于 xv6-k210 改编"但 fingerprint token=0.088/ast=0.065 —— 骨架相同+实现重写的改编穿不透两种指纹。SKILL Phase 1 要求: 低分时 Agent 必须读声明强制对比。

---

## MCP 工具

| 工具 (mcp_server.py 的 `@mcp.tool()`) | 输入 | 输出 |
|---|---|---|
| `search_candidates` | target, top_k | [{repo, token_min, ast_min, combined, is_framework}] |
| `attribution` | target, base | {nodes: {node_id: {status, functions: [{name, file, line, provenance}]}}} |
| `unit_source` | target, file, line | 源码片段 (前后各 20 行) |
| `grep_repo` | target, pattern | file:line 匹配结果 |
| `list_dir` | target, path | 目录内容 |
| `node_taxonomy` | node_id (可选) | 14 子系统 112 叶子节点 |
| `declared_deps` | target | {git_deps, workspace_members, vendored_frameworks, readme_refs, ...} |
| `exclude_rules` | target | [{rule, pattern, reason}] |

---

## 内核设计树

`core/kernel_tree.py` 定义固定骨架: 15 根子系统/112 叶子节点 (Metadata、BuildAndConfig~EvolutionHistory)。所有内核填同一套槽位。

`report.py` 按 `EXTRA_NODE_SPECS` 的 symbols 表 (函数名→树节点) 将 provenance 数据映射到节点。非 xv6 系内核匹配可能不全。

## 组装依赖

requirements.txt: `mcp`, `networkx`, `tree-sitter-c/cpp/rust`, `numpy`, `gitpython`, `langgraph` (旧 Agent D 依赖) 等。

Python 3.10+。
