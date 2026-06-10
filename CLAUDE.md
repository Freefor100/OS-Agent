# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OS-Agent reads an operating-system kernel source repo and produces a fixed-shape "kernel design tree" with source-backed claims, then compares trees across kernels for similarity / lineage analysis. Built for the 全国大学生计算机系统能力大赛 (proj18). Two agents:

- **Agent D** (`agent_d.py`): reads source, fills a fixed kernel-design-tree taxonomy, emits static HTML + JSON artifacts.
- **Agent C** (`agent_c.py`): compares already-analyzed kernels. Reads only `output/<name>/_agent_d/` artifacts, never source.

## Commands

```bash
pip install -r requirements.txt          # Python 3.10+

# Analyze a kernel (clone URL or local path both work)
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv
python agent_d.py https://github.com/mit-pdos/xv6-riscv --repo-name xv6-riscv
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv --ui     # live browser dashboard
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv --serve  # serve result after run
python agent_d.py repos/xv6-riscv --repo-name xv6-riscv --fresh  # ignore checkpoint, restart

# Smoke-test config cheaply before a full run (3 nodes only)
AGENT_D_NODE_LIMIT=3 python agent_d.py repos/xv6-riscv --repo-name xv6-riscv

# Compare kernels (each must have been run through Agent D first)
python agent_c.py xv6-k210 xv6-riscv [more-kernels...]

# Tests — pytest is NOT installed; use unittest
python -m unittest discover -s tests
python -m unittest tests.test_agent_d_langgraph              # single module
python -m unittest tests.test_agent_d_langgraph.AgentDLangGraphTests.test_fanout_fanin_and_sqlite_checkpoint
```

Config lives in `.env` (copy from `.env.example`). Required: `OPENAI_API_KEY`, `OPENAI_API_BASE`, `MODEL_NAME` (any OpenAI-compatible endpoint — DeepSeek, OpenRouter, local vLLM). Output goes to `output/<repo-name>/_agent_d/`; the human-facing result is `index.html` there.

## Architecture

The two CLI entry points are thin. The orchestration lives in `core/`, executed as **two nested LangGraph state machines**:

1. **Global graph** (`core/agent_d_graph.py`, `AgentDGraphState`): drives the run batch-by-batch over the taxonomy. Nodes are analyzed in dependency batches defined by `ANALYSIS_BATCHES_V2` in `core/kernel_tree.py`. After all node batches: `trace_flows` → `build_dependencies` → `global_consistency` → `generate_architecture` → `finalize`. State is checkpointed to SQLite (langgraph-checkpoint-sqlite) so runs resume.

2. **Per-node subgraph** (`core/node_analysis_graph.py`, `NodeAnalysisState`): for each taxonomy node, runs **ReAct → verify → commit** with repair retries (`AGENT_D_REPAIR_ROUNDS`). The ReAct loop is `core/node_react_agent.py`, which forces a strict `NodeDraft` Pydantic schema as final output.

The "runtime" objects (`AgentDGraphRuntime`, `NodeAnalysisRuntime`) are dataclasses of callbacks. The graph modules are pure plumbing; the actual analysis logic (snapshotting, node analysis, merging, flow tracing, finalize) is implemented as closures **inside `agent_d.py`** and injected via these runtimes. To understand what a graph step does, find the matching callback in `agent_d.py`, not in `core/`.

### Key concepts

- **Taxonomy / design tree** (`core/kernel_tree.py`): the tree skeleton is fixed (`ROOT_NODES_V2`, 14 subsystems from BuildAndConfig to EvolutionHistory). Every kernel fills the same structure. `ANALYSIS_ORDER_V2` flattens the batches into linear order.
- **Blackboard** (`agent_d.py`): shared run state passed to node analysis. Forked per node (`_fork_blackboard`) and merged back (`_merge_node_results`); the fork deliberately does NOT copy extension history (see test `test_child_blackboard_does_not_copy...`).
- **Glossary** (`core/kernel_glossary.py` + `kernel_glossary.json`): ~334 mechanism definitions (bilingual + C/Rust code samples) that seed candidate mechanisms per node.
- **Evidence** (`core/evidence.py`): every claim links to source evidence (path, line, excerpt). Excerpts stored on disk (`evidence_store.jsonl`) with a bounded in-memory cache; recovery is idempotent.
- **Code Atlas** (`tools/code_atlas/`, `core/code_atlas/`): tree-sitter AST index (C/C++/Rust/Go/Zig) producing functions/types/edges, PageRank, and MinHash fingerprints. Used both by Agent D's `atlas_search` tool and by Agent C for fuzzy code-structure similarity.
- **ReAct tools** exposed to the node agent: `atlas_search`, `grep`, `lsp_definition`, `lsp_references`, `list_dir`, `read_doc`, `negative_search`, `git_history`. LSP (`tools/lsp_ops.py`) needs `clangd` or `rust-analyzer` installed — degrades to static search if absent.

### Agent C scoring

`agent_c.py` is a single large scoring module (no LLM at compare time). It loads `compare_index.json` + `kernel_design_tree.json` per kernel and combines several signals: `_design_score`, `_relation_score`, `_code_structure_score` (atlas MinHash/symbol-name overlap), and `_lineage_hint_score`. "Base coverage" functions handle teaching-prototype lineage: a fork should still match its base even after tag renames / additions (see `test_agent_c_compare.py`).

## Conventions and gotchas

- **Checkpoint reuse keys on a content hash** (`compute_input_hash`): source content + taxonomy + model config. Change any of those and it treats it as a new run. Use `--fresh` to force.
- **`scripts/run_describe.py` and `scripts/run_compare.py`** are compatibility shims for `agent_d.py` / `agent_c.py` — prefer the top-level entry points.
- **Shallow clones** (`--depth=1`) lack git history, so the `EvolutionHistory` node degrades. Clone with full history if evolution analysis matters.
- **Token cost** is significant (~200k–800k tokens for a ~20k-LOC kernel). Always validate config with `AGENT_D_NODE_LIMIT=3` first.
- **Concurrency** is env-tuned: `AGENT_D_NODE_CONCURRENCY` (tree nodes in parallel), `AGENT_D_LLM_CONCURRENCY` (in-flight model calls), `AGENT_D_REACT_MAX_STEPS`, `AGENT_D_CONTEXT_BUDGET_TOKENS`. Memory ceiling via `AGENT_D_MEMORY_SOFT_LIMIT_GB`.
- `repos/` (source) and `output/` (artifacts) are gitignored; `collected-data.xlsx` holds team/school metadata matched onto result pages via `core/submission_meta.py`.
