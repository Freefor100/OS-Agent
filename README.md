# OS-Agent

OS-Agent 是面向小型操作系统竞赛作品的多角色、多证据分析比对系统。它结合源码结构指纹、Git 提交历史、作者文档和模块实现证据，用于分析 Base 来源、技术演进、真实工作量、同届代码传播、文档可信度、AI 使用与测评异常。

## 设计边界

- 人工维护 `config/works.yaml` 和规范化 clone 目录；系统只校验。
- `scripts/review.py` 是唯一主 CLI，确定性实现在 `core/review_case/`。
- `.claude/skills/os-agent/SKILL.md` 只负责主 Agent 调度和阶段门禁。
- `.claude/agents/` 中的 sub-agent 每个只写一种评审片段。
- 指纹缓存放在 `fp_cache/`，作品评审目录只保存引用。
- 指纹候选只是 Base 和来源判断的输入，不直接产生抄袭、原创或传播方向结论。
- 不使用 MCP 服务承载主流程，sub-agent 不争用共享工具连接。

## 环境

```bash
conda env create -f environment.yml
conda activate os_agent
pip install -r requirements.txt
```

tree-sitter 及 C/C++/Rust grammar 是 AST 指纹的必需依赖。如果缺少 parser，指纹 manifest 会记录 warning，不得将仅含汇编块的结果当成完整指纹。

## 作品身份

`config/works.yaml` 由人工维护：

```yaml
- work_id: 2026-example-team-work
  year: 2026
  school: 示例学校
  team: 示例队伍
  work_name: 示例内核
  display_name: 示例学校 示例队伍《示例内核》
  machine_repo: T2026-example
  canonical_dir: repos/2026-示例学校-示例队伍-示例内核
  review_branch: main
  urls: {}
```

## 主命令

```bash
python3 scripts/review.py identity-check --work-id <work-id>
python3 scripts/review.py build-fp-cache
python3 scripts/review.py init --work-id <work-id>

python3 scripts/review.py scope --case-dir output/<work-id>
python3 scripts/review.py fingerprint --case-dir output/<work-id>
python3 scripts/review.py search-base --case-dir output/<work-id>
python3 scripts/review.py build-evidence --case-dir output/<work-id>
python3 scripts/review.py build-evidence-map --case-dir output/<work-id>
python3 scripts/review.py make-task-files --case-dir output/<work-id>

python3 scripts/review.py validate --case-dir output/<work-id>
python3 scripts/review.py assemble --case-dir output/<work-id>
python3 scripts/review.py compile --case-dir output/<work-id>
python3 scripts/review.py build-site --case-dir output/<work-id>
python3 scripts/review.py check-all --case-dir output/<work-id>
```

Base 接受后必须重新运行 `build-evidence-map` 和 `make-task-files`，使模块任务引用锁定 Base commit 和目标作品中的引入 commit。

## 目录

```text
config/works.yaml             人工作品身份
repos/                        规范化作品 clone
fp_cache/                     跨作品 blob/AST 指纹缓存
core/review_case/             确定性逻辑
scripts/review.py             主 CLI
scripts/compile_flags.py       可选 LSP 辅助
.claude/skills/os-agent/      主 Agent 调度规则
.claude/agents/               sub-agent 角色规则
output/<work-id>/             单作品评审产物
review_viewer/                报告阅读器
doc/                          参赛设计书
```

## 验证

```bash
python3 -m py_compile scripts/review.py core/review_case/*.py
python3 scripts/review.py --help
```
