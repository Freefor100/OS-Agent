# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OS-Agent is a plagiarism-detection system for OS kernel competition submissions. It builds deterministic code fingerprints (normalized token + AST shape), runs 1-vs-N similarity search against a corpus of ~160 kernels, and produces judge-facing HTML reports with provenance-colored kernel design trees.

Built for 全国大学生计算机系统能力大赛 (proj18).

## Commands

```bash
pip install -r requirements.txt          # Python 3.10+

# Pre-build corpus fingerprints (one-time, ~8 min)
python scripts/run.py --build

# Analyze a single submission
python scripts/run.py <repo-name>        # e.g. python scripts/run.py xv6-k210

# Single-tool invocation
python scripts/search.py <repo>          # 1-vs-N similarity search
python scripts/attribute.py <repo>       # deep compare COPIED/MODIFIED/NOVEL
python scripts/fingerprint.py <repo>     # build fingerprints only (no comparison)

# Tests — pytest is NOT installed; use unittest
python -m unittest discover -s tests
python -m unittest tests.test_agent_c_compare
```

## Architecture

### Pipeline (scripts/)

`python scripts/run.py <target>` drives four stages:

```
[A] declarations.py   extract Cargo structure, git deps, lineage refs
[B] fingerprint.py    build fingerprints (c/cpp/rust via tree-sitter + asm via tokenizer)
[C] search.py         1-vs-N similarity (token + AST dual dimension)
[D] attribute.py      COPIED / DISGUISE / MODIFIED / NOVEL deep comparison
[E] report.py         assemble HTML: contribution table + design tree + arch graph
```

| File | Role |
|---|---|
| `fingerprint.py` | Build fingerprints. `build_units(repo)` → unified unit list `{lang, file, name, fp, ast, sz}`. `fingerprint_set(repo)` → set of exact hashes. `ast_fingerprint_set(repo)` → AST shape hashes. Cached to `.fp_cache/`. |
| `provenance.py` | 5-way classification: EXTERNAL / PORTED-FRAMEWORK / PORTED-PEER / ORIGINAL / TRIVIAL. `classify_provenance(units, fw, peers, exclude_rules)`. |
| `search.py` | 1-vs-N search. `combined = max(token_min, ast_min)`. `corpus_fingerprints(build_missing=False)` returns cached fingerprints only (fast). |
| `declarations.py` | Read Cargo.toml (workspace members/exclude/path deps), .gitmodules, README references (github + gitlab.eduxiji.net). |
| `exclude.py` | Exclusion rule engine. Consumes declarations, generates include/exclude rules. No preset dictionary — LLM fills `llm_external_dirs`/`llm_student_dirs` fields. |
| `attribute.py` | Deep compare: COPIED (same fp + name) / DISGUISE (same fp, different name) / MODIFIED (same name, different fp) / NOVEL (no match). |
| `report.py` | HTML report: contribution table, 14-subsystem design tree (provenance-colored via `core/kernel_tree.py`), Mermaid arch graph, declared deps, original function list. |
| `run.py` | One-button driver: `run <target>` runs A→E. `--build` pre-builds corpus fingerprints. |

### Tool layer

| File | Role |
|---|---|
| `tools/code_atlas/minhash.py` | MinHash signatures + jaccard estimate. `signature_from_tokens(tokens)` is the fingerprint primitive — does NOT require tree-sitter. |
| `tools/code_atlas/ast_shape.py` | AST shape merkle hash — ignores variable names/literals. Same structure → same hash. |
| `tools/code_atlas/asm_tokenize.py` | Assembly tokenizer — normalizes registers→REG, labels→LBL, keeps mnemonics/offsets. Splits by label block. |
| `core/code_atlas/builder.py` | Tree-sitter code atlas: parse repo → functions, types, edges, PageRank, normalized tokens. |
| `core/kernel_tree.py` | Fixed taxonomy: 14 subsystems, 112 leaf nodes. `EXTRA_NODE_SPECS` maps function names to tree nodes. |
| `core/evidence.py` | Evidence store. `stable_id(prefix, payload)` → deterministic hash-based ID. |

### MCP & Skill

`mcp_server.py` exposes 6 compute tools: `search_candidates`, `deep_compare`, `attribution`, `node_taxonomy`, `declared_deps`, `exclude_rules`. File ops (ls/cat/grep) use Claude Code's built-in bash.

`SKILL.md` defines the Claude Code workflow: Phase 1 determine report type (incl. low-score declaration check) → Phase 2 attribution → Phase 3 sub-agent batch analysis → Phase 4 assemble three-color tree report.

### Key design constraints

- **No preset external-dependency list**: declarations drive exclusion. LLM fills gaps via `llm_external_dirs`.
- **Version-sensitive baselines**: ArceOS family must use `oscomp/arceos` (contest fork), not upstream `arceos-org`.
- **Token floor (~100)**: only suppresses PEER false-positives (Rust boilerplate). Small functions with no match → ORIGINAL.
- **Direction requires timestamps**: fingerprint similarity is undirected. Year/git history required for "who copied whom".
- **rv6 limit case**: README says "based on xv6-k210" but token=0.088/ast=0.065. SKILL Phase 1 handles this: low-score → read declarations → force comparison.

### .fp_cache

Fingerprint caches live in `.fp_cache/` (gitignored): `units_*.pkl` (full unit lists), `fpset_*.pkl` (exact hash sets), `astset_*.pkl` (AST hash sets), `exclude_*.pkl` (exclusion rules). Delete to force rebuild.

### Corpus

`repos/` (gitignored) contains ~160 submissions + teaching prototypes. `repos/_baseline_oscomp-arceos/` is the contest-fork ArceOS baseline (`git clone https://github.com/oscomp/arceos.git`).
