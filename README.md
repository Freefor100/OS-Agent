# OS-Agent

> 面向小型操作系统的分析比对智能体系统
> 全国大学生计算机系统能力大赛 · proj18

读一个内核仓库，用代码指纹做查重：识别派生来源、外部依赖、选手自研代码，产出评委可读的报告。

---

## 快速开始

```bash
pip install -r requirements.txt     # Python 3.10+
```

### 1. 建指纹（一次性，缓存到 .fp_cache/）

```bash
# 为 repos/ 下所有作品预建指纹（首次约 8 分钟）
python scripts/run.py --build
```

### 2. 分析一个作品

```bash
python scripts/run.py <作品名>
```

例如:
```bash
python scripts/run.py xv6-k210
python scripts/run.py T202510216995249-4014
```

流程自动:
- 提取声明 (Cargo 结构 + 依赖 + 血缘引用)
- 建指纹 (c/cpp/rust + 汇编)
- 1-vs-N 搜索语料库 (token + AST 双维度)
- 组装 HTML 报告

### 3. 查看报告

打开 `output/<作品名>/_report/index.html`，包含：
- 贡献占比表 (五分类来源)
- 内核设计树 (14 子系统 × 112 叶子节点 × 三色出身标注)
- Mermaid 模块架构图 (模块级调用 + 出身染色)
- 自报依赖与血缘
- 选手自研函数清单 (带 file:line 证据)

## 环境变量 (.env)

```env
OPENAI_API_KEY=sk-...
OPENAI_API_BASE=https://api.openai.com/v1
MODEL_NAME=deepseek/deepseek-chat
```

仅旧 Agent D 流需要。新查重流水线无需 LLM。

---

## 项目结构

```
OS-Agent/
├── README.md                    本文件
├── DESIGN.md                    技术设计文档 (方法、约束、模块接口)
├── SKILL.md                     Claude Code 工作流 (MCP + Skill 报告生成)
├── mcp_server.py                MCP server (8 个工具)
├── .mcp.json                    MCP 配置
├── requirements.txt             Python 依赖
│
├── scripts/                     确定性流水线脚本
│   ├── fingerprint.py           建指纹 (c/cpp/rust via tree-sitter + 汇编 via tokenizer)
│   ├── provenance.py            五分类出身 (EXTERNAL/FRAMEWORK/PEER/ORIGINAL/TRIVIAL)
│   ├── search.py                1-vs-N 相似搜索 (token + AST 双维度)
│   ├── declarations.py          提取声明 (Cargo 结构 + 依赖 + 血缘引用)
│   ├── exclude.py               排除规则引擎 (不预设字典)
│   ├── run.py                   一键驱动
│   ├── report.py                HTML 报告组装
│   ├── attribute.py             函数级精查 (COPIED/DISGUISE/MODIFIED/NOVEL vs base)
│   ├── fp_validate.py           指纹判别力验证
│   ├── overview.py              全库总览 (辅助)
│   ├── lineage_idf.py           全库聚簇 (v1 / 辅助)
│   └── lineage_matrix.py        全库 N×N 矩阵 (已弃用)
│
├── tools/                       工具层
│   ├── code_atlas/              tree-sitter AST 解析 + MinHash 指纹
│   │   ├── minhash.py           MinHash 签名 + jaccard (指纹底层原语)
│   │   ├── normalize.py         归一化 token
│   │   ├── ast_shape.py         AST 形状哈希 (抗重构)
│   │   ├── asm_tokenize.py      汇编 tokenizer (归一化寄存器/标号)
│   │   └── extractor.py         tree-sitter 函数提取
│   ├── file_ops.py              grep / list_dir / read_code
│   ├── lsp_ops.py               LSP 符号查找
│   ├── git_ops.py               Git 历史分析
│   └── build_config_ops.py      构建配置解析
│
├── core/                        核心模块 (复用自旧 Agent D)
│   ├── code_atlas/builder.py    code_atlas 编排
│   ├── kernel_tree.py           内核设计树骨架 (14 子系统/112 叶子)
│   ├── kernel_glossary.json     334 条机制定义 (中英 + 代码示例)
│   └── evidence.py              源码证据存储
│
├── agent_d.py                   Agent D 入口 (旧分析流程,保留)
├── agent_c.py                   Agent C 入口 (旧比对流程,保留)
│
├── repos/                       语料库 (~160 参赛内核, gitignored)
├── .fp_cache/                   指纹缓存 (gitignored)
└── output/                      报告产物 (gitignored)
```

## 旧 Agent D / Agent C

以下命令仍可用，但新流水线 (`scripts/run.py`) 是当前开发方向:

```bash
# 旧 Agent D — LLM 填描述树
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv

# 旧 Agent C — 比对已分析内核
python agent_c.py xv6-k210 xv6-riscv

# 冒烟测试
AGENT_D_NODE_LIMIT=3 python agent_d.py repos/xv6-riscv --repo-name xv6-riscv
```

详见 `CLAUDE.md`。

---

## 注意事项

**LSP 支持（可选）**

安装 `clangd`（C/C++）或 `rust-analyzer`（Rust）后，Agent 可获取更精准的符号定义和调用关系。未安装时退化到 grep 搜索。

---

## 参赛信息

- 赛事：2026 全国大学生计算机系统能力大赛（操作系统赛）
- 项目：proj18 · 面向小型操作系统的分析比对智能体系统设计
- 参赛作品信息从 `collected-data.xlsx` 中读取，自动显示在结果页顶部
- 教学原型仓库（xv6、rCore、ArceOS 等）单独标注，不显示队伍信息
