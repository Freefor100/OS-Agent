# OS-Agent

## 参赛信息

- 赛事：2026 全国大学生计算机系统能力大赛-操作系统设计赛（全国）
- 赛道：OS 功能挑战赛道
- 项目：proj18 · 面向小型操作系统的分析比对智能体系统设计

---

## 这是什么

一套以 **MCP + Claude Code Skill** 形式运行的内核作品查重系统。

**核心原则：Python 脚本只做确定性计算（hash、集合交运算），Agent（Claude Code）做所有判断。**

1. **Python 脚本**做重体力计算——建指纹、搜相似度、函数级匹配。数据全缓存。
2. **Claude Code** 加载 MCP 工具 + SKILL.md，读 repo 结构、判断外部依赖、选定对比对象、读源码写分析，产出评委可读的 HTML 报告。

**不是你跑脚本就出报告**。脚本产数据，判断和报告由 Agent 完成。

---

## 怎么用

### 第一步：装依赖

```bash
pip install -r requirements.txt    # Python 3.10+
```
> **提示 (提升 LSP 精度)**：本项目的 LSP 工具 (`clangd`) 默认已支持跨架构基础分析。但为了达到 **100% 的高精度分析**（消除宏污染，并正确解析 `<stdarg.h>` 等系统头文件），强烈建议在系统中安装**纯正的裸机（Bare-Metal）交叉编译器**：
> - **RISC-V**: `sudo apt-get install gcc-riscv64-unknown-elf`
> - **LoongArch**: 请从 [picolibc-ci-tools](https://github.com/picolibc/picolibc-ci-tools/releases) 下载纯净的 `loongarch64-unknown-elf`（不要用 apt 里的 `loongarch64-linux-gnu`，会导致宏污染）。
> - **ARM**: 请从 [xpack-dev-tools](https://github.com/xpack-dev-tools/aarch64-none-elf-gcc-xpack/releases) 下载 `aarch64-none-elf-gcc`。
> 将它们解压并添加到 `PATH` 后，`lsp_ops.py` 会自动探测并调用它们。

### 第二步：预建语料库指纹（一次性）

```bash
python scripts/run.py --build
```

替 `repos/` 下所有作品建代码指纹，缓存到 `.fp_cache/`。约 8 分钟。

### 第三步：用 Claude Code 产出报告

在此项目目录下打开 Claude Code，配置 `.mcp.json` 连接 `mcp_server.py`。然后说：

> 按照 SKILL.md 分析 repos/<目标作品>，产出查重报告

Claude Code 的 Agent 流程（详见 `SKILL.md`）：

1. **Phase 1 认识作品** — `compile_flags` + `build_fingerprint`，读目录结构/Cargo.toml/README，判断哪些是外部依赖
2. **Phase 2 搜索相似** — `search_similar(target, exclude_prefixes=[...])`，在学生代码上搜索，拿到 per-directory overlap
3. **Phase 3 深度对比** — `compare_functions(target, base, exclude_prefixes=[...])`，拿到 per-file 的 COPIED/DISGUISE/MODIFIED/NOVEL 清单，读源码写分析
4. **Phase 4 组装报告** — 用 `node_taxonomy()` 拿 14 子系统骨架，生成三色 HTML 报告

两条分支：
- 搜到高相似候选或有声明来源 → **对比报告**（相对 base 改了什么）
- 无候选且无声明 → **描述报告**（独立分析内核设计）

---

## MCP 工具（mcp_server.py 暴露的 7 个）

| 工具 | 做什么 |
|---|---|
| `search_similar` | 1-vs-N 搜索（Token + AST + per-directory overlap） |
| `compare_functions` | 函数级 COPIED/DISGUISE/MODIFIED/NOVEL + per-file 分组 |
| `build_fingerprint` | 为仓库建指纹（克隆新依赖后调用） |
| `compile_flags` | 跨架构 LSP 编译标志（RISC-V/LoongArch/ARM） |
| `lsp_definition` | LSP 跳转定义（clangd→tree-sitter→grep） |
| `read_doc` | 读 PDF/Docx |
| `node_taxonomy` | 14 子系统 / 112 叶子节点骨架 |

排除外部依赖不是独立工具——Agent 读目录结构后自行决定哪些目录是外部依赖，通过 `exclude_prefixes` 参数传给 `search_similar` 和 `compare_functions`。

---

## 脚本速查

| 脚本 | 做什么 |
|---|---|
| `run.py --build` | 预建全库指纹 |
| `fingerprint.py` | 单独建指纹（tree-sitter + asm tokenizer） |
| `search.py` | 1-vs-N 搜索，支持 `exclude_prefixes` 过滤 |
| `attribute.py` | 函数级 COPIED/DISGUISE/MODIFIED/NOVEL 对比 |
| `compile_flags.py` | 生成 clangd 编译标志 |

---

## 项目结构

```
OS-Agent/
├── README.md                本文件
├── SKILL.md                 Claude Code 报告生成工作流
├── mcp_server.py            MCP server（7 工具）
├── .mcp.json                MCP 配置（Claude Code 自动读取）
│
├── scripts/                 确定性计算（无判断）
│   ├── run.py               预建 corpus 指纹
│   ├── fingerprint.py       代码指纹（token hash + AST shape hash）
│   ├── search.py            1-vs-N 双向包含搜索
│   ├── attribute.py         函数级深度对比
│   └── compile_flags.py     LSP 编译标志生成
├── tools/                   工具层
│   ├── code_atlas/          MinHash / AST shape / ASM tokenizer / extractor
│   ├── lsp_ops.py           LSP 客户端
│   └── file_ops.py          PDF/Docx 读取
├── core/                    内核设计树 + code atlas builder + 证据存储
├── repos/                   语料库（~160 内核，gitignored）
├── .fp_cache/               指纹缓存（gitignored）
└── output/                  报告产物（gitignored）
```
