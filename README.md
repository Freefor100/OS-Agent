# 2026年操作系统设计赛（全国赛 ）-OS功能挑战赛

# proj18-面向小型操作系统的分析比对智能体系统设计


# OS-Agent: KernelProject Agents

本仓库当前主线是两个公开入口：

```powershell
python agent_d.py --repo repos\xv6-riscv --repo-name xv6-riscv --ui
python agent_c.py xv6-k210 xv6-riscv
```

`agent_d.py` 生成单个内核仓库的 KernelProject 抽象设计树。`agent_c.py` 只消费 Agent D 的 `_agent_d` 产物做查重/谱系比较，不回读源码。

## Agent D 目标

Agent D 不是自然语言报告生成器，也不是靠文件名/函数名规则贴标签。目标是让 LLM 以 ReAct 方式读源码证据，产出可展示、可比较、可追溯的固定 KernelProject 设计树。

输出目录：

```text
output/<repo>/_agent_d/
├── kernel_design_tree.json     # 主产物：KernelProject 设计树
├── evidence_store.jsonl        # 工具生成的 verified evidence
├── compare_index.json          # Agent C 查重索引
├── claim_glossary.json         # Claim 中英文解释、概念边界与通用 C/Rust 识别样例
├── judge_view.json             # 评委页面数据
├── index.html                  # 最终静态展示页
├── checkpoints.sqlite          # LangGraph 全局图与节点 ReAct checkpoint
├── run_manifest.json           # 输入指纹、run_id、恢复与完成状态
├── run_dashboard.html          # 与 TUI 同源的运行进度页面
├── run_status.json             # 当前状态快照
├── run_events.jsonl            # 运行事件流
├── tool_calls.jsonl            # 工具调用记录
├── llm_node_drafts.jsonl       # LLM 结构化回答，不含 CoT
├── verifier_reports.jsonl      # claim-evidence 校验记录
├── blackboard_snapshots.jsonl  # 全局黑板压缩快照
└── llm_usage.json              # 模型、thinking、token、耗时
```

## Agent D 流程

Agent D 由 LangGraph 控制全局状态，LangChain `create_agent` 控制每个叶子节点的自主 ReAct。Rich TUI、网页和 JSON 都只投影同一份图事件，不自行控制流程。

全局图固定为：

```text
BootstrapContext -> InitializeTree -> SelectBatch
  -> AnalyzeNode fan-out -> MergeBatch fan-in -> SelectBatch
  -> FlowTracer -> DependencyBuilder -> GlobalConsistency
  -> Finalizer -> Complete
```

每个 `AnalyzeNode` 内部还有一张可 checkpoint 的节点子图：

```text
LangChain ReAct Agent -> Program Verifier
  -> pass: CommitNodeResult
  -> fail: ReAct Agent repair
  -> repair 超限: FailedNode
```

ReAct Agent 读取节点概念卡、候选词、概念辨析、稳定黑板快照与已有 evidence，自主调用 `glossary_lookup`、CodeAtlas 导航、源码读取、LSP definition/reference/call graph 和 negative search，最后通过 `ToolStrategy(NodeDraft)` 提交严格结构化结果。程序 Verifier 校验 claim tag、evidence_id、强证据和负向证据；失败反馈会回到同一节点线程修复。

相同源码、词表、Prompt、模型和 thinking 配置生成相同输入指纹。未完成运行自动从 `checkpoints.sqlite` 恢复；完成运行直接复用；失败运行只重试失败节点。`--fresh` 强制新运行，`--run-id` 指定恢复运行。

`AGENT_D_NODE_CONCURRENCY` 限制同时活跃的完整节点 ReAct 工作流；`AGENT_D_LLM_CONCURRENCY` 限制这些节点合计同时发出的模型请求。两者设成相同值时，LLM 限流通常不会进一步约束节点，因此默认使用 `4/4`。完成节点会立即清除完整 ReAct 消息 checkpoint，只保留磁盘上的结构化节点结果；`AGENT_D_MEMORY_SOFT_LIMIT_GB` 默认关闭，仅可作为额外的应急保护。

Agent D 使用“磁盘完整、内存有界”的状态模型。每个节点通过 Verifier 后立即原子更新 `kernel_design_tree.json`，并写入 `_state/node_results/<node>.json`；中断不会丢掉已完成节点。完整 tool/LLM/verifier/trace 行为追加写入 JSONL，TUI 和 Web Dashboard 只保留最近 500 条事件窗口。EvidenceStore 只在内存保留紧凑索引和最近 128 条完整 evidence；源码 excerpt 按 evidence_id 从磁盘读取。LangChain ReAct 消息不进入持久 checkpoint，未完成节点恢复时从节点边界重跑并复用幂等 evidence。

默认交互终端显示 Rich TUI；`--ui` 在保留 TUI 的同时启动网页 Dashboard；`--no-tui` 使用行式日志，`--quiet` 只输出最终 JSON。

树结构定义在 `core/kernel_tree.py::ROOT_NODES_V2`，是 `KernelProject -> 一级模块 -> 叶子设计节点`。`ANALYSIS_BATCHES_V2` 不是树层级，只是执行调度：批次之间串行，同批次内可并发。`run_dashboard.html` 显示的是调度流程状态，最终 `index.html` 展示的是树状内核设计。

## LLM 强制要求

Agent D deep-read 模式必须使用 LLM：

```env
OPENAI_API_KEY=...
OPENAI_API_BASE=...
MODEL_NAME=...
AGENT_D_THINKING=enabled
AGENT_D_REASONING_EFFORT=high
```

Agent D 默认把源码 evidence pack 作为 LLM 输入；LLM API 不可用或 LLM draft 无法通过 verifier 时会失败。页面和产物不展示 CoT，只展示结构化结论和 evidence 绑定。

## Agent C 比较层

Agent C 只读取两个或多个 `_agent_d` 目录：

1. Design Claim：比较 `claim_tag`、模块存在性、机制/策略/结构/接口标签。
2. Architecture Relation：比较 flow signature 和 dependency signature。
3. Code Structure：比较 AST/CPG-lite 指纹，包括 AST shape、normalized tokens、call edge、type/macro usage、claim-code bindings。
4. Base-aware Lineage：根据共同 base 把 claim 标为 `base_inherited/base_modified/target_unique/unknown`。

`EvolutionHistory` 只用于展示，不进入主查重分数。

## 目录结构

```text
agent_d.py              # Agent D 正式入口
agent_c.py              # Agent C 正式入口
scripts/                # 兼容入口和批量辅助脚本
core/                   # Agent D 支撑模块：LangGraph、LangChain ReAct、证据、树、页面、TUI
core/code_atlas/        # 静态代码结构索引基础设施
core/llm/               # OpenAI-compatible LLM runtime
tools/                  # LSP、构建配置、文件和 tree-sitter 工具
repos/                  # 本地源码仓库，不提交
output/                 # 运行产物，不提交
```

旧多层图流水线已从当前主线移除；现在统一产物是 `_agent_d` 和 `_agent_c`。



