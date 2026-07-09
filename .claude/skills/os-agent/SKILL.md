---
name: os-agent
description: 面向 OS 功能挑战赛题的小型操作系统源码多证据分析比对规则入口。
disable-model-invocation: true
---

# OS-Agent 多证据分析比对规则入口

这个 skill 只负责评审案件入口和规则选择。Agent 只写评审片段 contract；可机器消费的数据只能由确定性 CLI 生成。

## 硬规则

- 作品身份和 canonical clone 名称由用户人工维护在 `config/works.yaml`。
- 开始评审前必须运行 `python scripts/review.py identity-check --work-id <id>`。
- Base 未 accepted 前禁止启动任何模块 subagent。
- fingerprint 属于跨作品 `fp_cache/`，单作品评审目录只保存 `case_state/fp_manifest.json` 引用。
- `evidence.jsonl` 必须先整理为 `case_state/evidence_map.json`，再生成任务文件；不得把全部 evidence 塞给每个 agent。
- 每个 subagent 只能输出对应评审片段 contract。
- 每个 subagent 下判断前必须遵守 `references/judgment-playbook.md` 的经验规则。
- 所有强结论必须引用 `[@E001]` 形式的 evidence chip。
- subagent 不写最终报告。
- `report-editor` 只组装已接受的评审片段，不允许创造事实或解决矛盾。
- 只有 `contradiction-arbiter` 可以解决冲突。
- `site/report_data.json` 只能由 `python scripts/review.py compile` 生成，agent 禁止手写。
- 同届抄袭方向必须同时引用结构指纹/AST 热点 evidence 和 git 时间线 evidence；缺任一类只能写方向不确定。
- deleted taxonomy feature 禁止出现在 task、prompt、report 或公开正文中。

## 顺序

1. 用 `identity-check` 校验人工身份表。
2. 用 `init` 初始化评审目录并锁定版本。
3. 用确定性工具生成或复核 scope、`fp_cache`、Base 候选、Base delta 事实和 evidence。
4. 产出并校验 `base.md`。
5. 用 `build-evidence-map` 生成 evidence 映射，再用 `make-task-files` 生成窄任务文件。
6. 运行模块 subagent 和 finding subagent。
7. 如存在冲突，由 `contradiction-arbiter` 处理 `issues/contradictions.md`。
8. 运行 `python scripts/review.py check-all --case-dir <dir>`。
9. 使用生成的 `report.md`、`tags.json` 和 `site/report_data.json`。

## 参考规则

按任务读取 `references/` 下的窄规则，不再使用一个大 prompt：

- `case-process.md`
- `identity.md`
- `evidence-contract.md`
- `evidence-map.md`
- `taxonomy-v3.md`
- `base-contract.md`
- `module-contract.md`
- `finding-contract.md`
- `cheat-and-injection.md`
- `contradiction-arbitration.md`
- `report-assembly.md`
- `validation.md`
- `context-quality.md`
- `judgment-playbook.md`
