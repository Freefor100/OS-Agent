# OS-Agent

## 参赛信息

- 赛事：2026 全国大学生计算机系统能力大赛-操作系统设计赛（全国）
- 赛道：OS 功能挑战赛道
- 项目：proj18 · 面向小型操作系统的分析比对智能体系统设计
- 参赛作品信息从 `collected-data.xlsx` 中读取

---

## 这是什么

一套以 **MCP + Claude Code Skill** 形式运行的内核作品查重系统。

1. **Python 脚本**做重体力确定性计算——建指纹、搜相似度、深度对比。数据全缓存。
2. **Claude Code** 加载 MCP 工具 + SKILL.md，读确定性数据 + 源码，产出评委可读的查重报告或原创描述报告。

**不是你跑脚本就出报告**。脚本产数据，报告由 Claude Code 产。

---

## 怎么用

### 第一步：装依赖

```bash
pip install -r requirements.txt    # Python 3.10+
```

### 第二步：预建语料库指纹（一次性）

```bash
python scripts/run.py --build
```

替 `repos/` 下所有作品建代码指纹，缓存到 `.fp_cache/`。约 8 分钟。之后不用再跑。

### 第三步：为目标作品建指纹 + 搜索 + 对比

```bash
python scripts/run.py xv6-k210
```

这步跑完确定性计算：
- 编译标志 → clangd 能正确解析 RISC-V/LoongArch 代码
- 声明提取 → Cargo 结构 / git 依赖 / README 血缘引用
- 指纹 → c/cpp/rust（tree-sitter）+ 汇编（tokenizer），缓存
- 1-vs-N 搜索 → Token + AST 双维度，找到最相似的候选作品
- 深度对比 → 每个函数标 COPIED / DISGUISE / MODIFIED / NOVEL

### 第四步：用 Claude Code 产出报告

在此项目目录下打开 Claude Code。它会自动加载：
- `.mcp.json` → 连接 `mcp_server.py`（9 个 MCP 工具）
- `SKILL.md` → 完整报告生成工作流

然后说：

> 按照 SKILL.md 分析 xv6-k210，产出查重报告

Claude Code 会：
1. 调用 MCP 工具拿确定性数据（搜索候选、深度对比、声明列表…）
2. 用内置 bash 读源码
3. 按 14 子系统内核设计树逐个节点产出分析
4. 对自研/修改部分开 sub-agent 批量写详细描述
5. 拼接成 HTML 报告

**两条分支**，SKILL.md Phase 1 自动判断：
- 搜到高相似候选 → **查重对比报告**（相对 base 改了什么）
- 无候选或原创 → **描述报告**（独立分析内核设计）

---

## MCP 工具（mcp_server.py 暴露的 10 个）

| 工具 | 做什么 |
|---|---|
| `search_candidates` | 1-vs-N 搜索（Token + AST + year） |
| `build_fingerprint` | 为仓库建指纹（克隆新依赖后调用） |
| `deep_compare` | 函数级 COPIED/DISGUISE/MODIFIED/NOVEL |
| `attribution` | 每个设计树节点的函数出身 |
| `node_taxonomy` | 14 子系统 / 112 叶子节点骨架 |
| `declared_deps` | 声明的依赖和血缘 |
| `exclude_rules` | 排除规则和原因 |
| `compile_flags` | 跨架构 LSP 编译标志 |
| `lsp_definition` | LSP 跳转定义（clangd→tree-sitter→grep） |
| `read_doc` | 读 PDF/Docx |

---

## 脚本速查

| 脚本 | 做什么 |
|---|---|
| `run.py` | 一键驱动（建指纹→搜索→对比） |
| `run.py --build` | 预建全库指纹 |
| `fingerprint.py` | 单独建指纹 |
| `search.py` | 单独搜索 |
| `attribute.py` | 单独深度对比 |
| `compile_flags.py` | 单独生成 LSP 编译标志 |

---

## 项目结构

```
OS-Agent/
├── README.md                本文件
├── DESIGN.md                技术设计文档
├── SKILL.md                 Claude Code 报告生成工作流
├── mcp_server.py            MCP server（9 工具）
├── .mcp.json                MCP 配置（Claude Code 自动读取）
│
├── scripts/                 确定性流水线
├── tools/                   工具层（tree-sitter / LSP / 文件操作）
├── core/                    内核设计树 + 证据存储
├── repos/                   语料库（~160 内核，gitignored）
├── .fp_cache/               指纹缓存（gitignored）
└── output/                  报告产物（gitignored）
```
