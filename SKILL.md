# OS-Agent Skill: 内核查重与描述报告

## 任务

分析一个内核作品,产出评委可读的 HTML 报告。报告以**内核设计树**(14 子系统,112 叶子节点)为骨架,每个节点按代码出身染色,自研/修改部分附详细自然语言描述。

## MCP 工具

分析前调用这些工具获取确定性数据(全部只读):

| 工具 | 用途 | 何时调用 |
|---|---|---|
| `search_candidates(target)` | 1-vs-N 查重(token+AST 双维度),找最相似作品 | 第一步 |
| `declared_deps(target)` | 选手声明的依赖/血缘(Cargo/gitmodules/README) | 第一步 |
| `exclude_rules(target)` | 哪些代码被排除、为什么 | 第一步 |
| `node_taxonomy()` | 内核设计树骨架(14 子系统,112 叶子) | 组装报告前 |
| `attribution(target, base)` | 每个节点的函数清单+出身(COPIED/NOVEL/MODIFIED) | 核心,决定分析深度 |
| `unit_source(target, file, line)` | 读取源码片段(前后 N 行) | 写分析时按需调用 |
| `grep_repo(target, pattern)` | 正则搜索代码(找符号/证据) | 写分析时定位符号 |
| `list_dir(target, path)` | 浏览目录结构 | 探索项目结构时调用 |

## 流程

### Phase 1: 判断报告类型

```
search_candidates(target) + declared_deps(target)
    │
    ├─ combined ≥ 0.30 且有时间更早的候选
    │      → 对比报告: base = 得分最高且时间更早的候选
    │
    ├─ combined < 0.30
    │      → 读 README / 文档,检查选手是否声明了来源
    │      ├─ 声明了具体来源("基于 xv6-k210 改编" / README 里的 gitlab 引用)
    │      │      → 强制对比报告: base = 声明的来源(即使指纹分很低)
    │      │         注:低分本身是有价值的信息——"声明说基于 X,指纹却说几乎无共享"
    │      │         这正是声明核查要揭露的矛盾(rv6 案例: README 写"基于 xv6-k210")
    │      │
    │      └─ 无任何来源声明
    │             → 描述报告(原创): base = ""
    │
    └─ 无任何候选
           → 同上:读文档查声明 → 有声明则强制对比,否则描述报告
```

调用 `exclude_rules(target)`,记录排除清单,供报告核查区使用。

### Phase 2: 取得 attribution 并分类节点

```
attribution(target, base)
    → {nodes: {<node_id>: {status, functions: [{name, file, line, provenance, tokens}]}}}
```

遍历每个节点,按 provenance 归类:

| 节点内函数构成 | 分析深度 | 标注颜色 |
|---|---|---|
| 全是 EXTERNAL | 跳过(外部依赖) | ⬜ 灰色 |
| 全是 COPIED + TRIVIAL | **简要**:标注"继承自 {base},未改动" | 🟨 黄色 |
| 含 NOVEL 或 MODIFIED | **详细**:sub-agent 读源码写分析 | 🟦(NOVEL为主) / 🟥(MODIFIED为主) |
| 无函数 | **简要**:标注"未实现" | ⬜ 灰色 |

### Phase 3: Sub-agent 批量详细分析

**这是 Claude Code 的核心工作。** 对每个标记为"详细"的节点,开 sub-agent。

**对比报告模式**——sub-agent 的 prompt:
```
你是内核分析员。目标作品基于 {base}。

节点: {node_title_zh}
需要分析的函数(仅列出 NOVEL 和 MODIFIED):

MODIFIED (相对 base 做了改动):
- {name} ({file}:{line}, {tokens}tok) — 使用 unit_source 读取目标版和 base 版的源码

NOVEL (全新代码):
- {name} ({file}:{line}, {tokens}tok) — 使用 unit_source 读取源码

请逐个函数分析,用中文描述:
- MODIFIED: 相对 base 改了什么? 数据结构变了? 算法换了? 为什么这样改?
- NOVEL: 这个函数实现什么功能? 设计决策是什么? 与标准实现有何异同?

输出格式: 每个函数一段自然语言描述,附关键代码行引用。
```

**描述报告(原创)模式**——sub-agent 的 prompt:
```
你是内核描述者。目标作品无对照对象,需完整描述其设计。

节点: {node_title_zh}
该节点的自研函数:
- {name} ({file}:{line}, {tokens}tok)

请读源码,用中文描述:
- 这个节点实现了什么? 采用了什么设计策略?
- 关键函数的数据结构、算法选择
- 与典型教学内核(xv6/rCore)的差异(如果明显)

输出格式: 每个函数一段自然语言描述,附关键代码行引用。
```

**批处理策略:**
- 一次开多个 sub-agent,每个负责 3-5 个需要详细的节点
- COPIED 节点不建 sub-agent,直接从 attribution 数据生成一行描述
- 等待所有 sub-agent 完成后进入 Phase 4

### Phase 4: 组装报告

按 14 子系统树组装 HTML:

```
每个子系统 (如 进程管理):
  <h2>进程管理</h2>
  ├── 调度器 🟨 继承自 {base},round-robin 未改动
  ├── Fork/Clone 🟥 修改 - [sub-agent 产出的详细分析]
  ├── 信号 🟦 自研 - [sub-agent 产出的详细分析]
  └── Futex ⬜ 未实现
```

报告结构(自上而下):
1. **作品元信息**:名称、届号、范式(宏内核/组件化)
2. **贡献占比表**:自研 X% / 移植 Y% / 外部依赖 Z% (数据来自 attribution.summary)
3. **血缘总览**:最相似候选列表,标注是否声明
4. **声明核查**:选手声称 vs 指纹事实
5. **排除清单**:哪些代码被排除、为什么
6. **内核设计树**(主体):14 子系统 × 三色标注 + 详细/简要描述
7. **架构图**:Mermaid 三色染色
8. **创新功能区**(如有):超越标准子系统的自研模块(GUI/Wayland 等)
9. **汇编覆盖声明**:汇编文件数、分析粒度、已知局限

---

## 对比报告 vs 描述报告的差异总结

| | 对比报告 | 描述报告 |
|---|---|---|
| 触发条件 | 搜到候选 | 无候选 |
| base 参数 | 传给 attribution | 空 |
| sub-agent prompt | "相对 base 改了什么" | "这个节点实现了什么" |
| COPIED 标注 | "继承自 {base}" | "来自外部依赖" 或 "基本实现" |
| MODIFIED | 读 diff + 详细描述 | 不适用 |
| NOVEL | "相比 base 新增" + 详细描述 | "选手自研" + 详细描述 |
| 报告主叙事 | "基于 {base} 的增量工作" | "独立设计的内核" |
