# OS-Agent

OS-Agent 是面向“全国大学生计算机系统能力大赛-操作系统设计赛(全国)-OS功能挑战赛道”的小型操作系统源码分析比对智能体系统。它的目标不是输出一个相似度分数，而是还原参赛作品的真实工作量、Base 与来源关系、模块实现质量、文档声明可信度、开发历史与 AI 使用、作弊/刷分/prompt injection 风险。

当前主线是 `review_case`。确定性脚本负责版本锁定、指纹缓存、证据整理、格式校验和前端数据；Agent 只写窄任务的评审片段。

## 人工前置

作品身份和 clone 目录由人工维护，不自动挖作品名，不自动 rename clone。

```text
config/works.yaml
repos/2026-<学校>-<队名>-<作品名>/
```

`config/works.yaml` 是作品身份唯一来源：

```yaml
- work_id: 2026-pku-shulijichu-workslug
  year: 2026
  school: 北京大学
  team: 数理基础队
  work_name: 手工挖出的作品名
  display_name: 北京大学 数理基础队《手工挖出的作品名》
  machine_repo: T2026100019911468-282
  canonical_dir: repos/2026-北京大学-数理基础队-手工挖出的作品名
  review_branch: main
  urls:
    prelim: https://...
    final: ""
    source: ""
```

公开正文只能使用 `display_name`。机器 repo id、数字 fork 后缀、历史 clone 目录名进入公开正文会校验失败。

## 分工顺序

`scope` 是源码归属划分：学生核心、共同框架、第三方库、生成物、测试包、文档和未知。它不是最终结论，只是防止共同框架、外部模块和测试代码污染 Base 选择、同届方向判断和模块工作量描述。

```text
works.yaml + canonical clone
-> identity-check
-> init 锁定版本
-> scope 划分评审边界
-> fp_cache 批量指纹缓存
-> search-base 生成候选
-> base.md 确认 Base
-> evidence.jsonl
-> evidence_map.json 证据映射
-> task_files/*.json 窄任务文件
-> subagents 写评审片段 contracts
-> contradictions 仲裁
-> assemble 生成 report.md/tags.json
-> compile 生成 site/report_data.json
-> build-site/build-index 发布前端
```

## CLI

```bash
python scripts/review.py identity-check --work-id <work_id>
python scripts/review.py init --work-id <work_id>
python scripts/review.py scope --case-dir output/<work_id>
python scripts/review.py build-fp-cache --works config/works.yaml --cache-root fp_cache
python scripts/review.py fingerprint --case-dir output/<work_id>
python scripts/review.py search-base --case-dir output/<work_id>
python scripts/review.py build-evidence --case-dir output/<work_id>
python scripts/review.py build-evidence-map --case-dir output/<work_id>
python scripts/review.py make-task-files --case-dir output/<work_id>
python scripts/review.py validate --case-dir output/<work_id>
python scripts/review.py assemble --case-dir output/<work_id>
python scripts/review.py compile --case-dir output/<work_id>
python scripts/review.py build-site --case-dir output/<work_id>
python scripts/review.py check-all --case-dir output/<work_id>
python scripts/review.py build-index --output output/site output/<work_id> ...
```

## 产物

```text
fp_cache/
  index.json
  <work_id>/<commit>/
    fingerprint_manifest.json
    target_blob.json
    target_ast.json

output/<work_id>/
  identity.md
  base.md
  evidence.jsonl
  modules/*.md
  findings/doc-claims.md
  findings/history-ai.md
  findings/cheat.md
  issues/contradictions.md
  report.md
  tags.json
  site/
    report_data.json
    report.html
  case_state/
    manifest.json
    works.snapshot.yaml
    repo_snapshot.json
    scope.json
    scope.md
    fp_manifest.json
    base_candidates.json
    evidence_map.json
    evidence_digest.md
    task_files/*.json
```

`case_state/` 是内部评审元数据命名空间，用来隔离机器产物和公开报告。批量发布不复制 `case_state/`。

公开阅读入口：

```text
report.md
site/report.html
tags.json
site/report_data.json
evidence.jsonl
```

`site/report_data.json` 不是报告正文，它是前端阅读器数据：章节、模块账本、evidence cards、Markdown 引用图和 evidence 证据映射图。

## 同届抄袭方向

同届抄袭方向不是相似度排序。必须同时看：

- 结构指纹/AST 热点：改名、拆文件、合文件、路径搬移后仍相似的核心函数和类型。
- git 时间线：核心代码首次出现时间、批量导入、后提交方的改写痕迹、提交说明和文件拆分轨迹。
- Base 声明与 scope：先排除共同框架、第三方库、测试包和公开引入模块，再判断学生核心代码。
- 外部模块适配：大规模引入代码不直接算原创，只有接口、平台、页表、调度、I/O 等适配工作单独计入。

没有“结构指纹证据 + git 时间线证据”的同向支撑，只能写方向不确定，不能写谁抄谁。

## Agent 角色

- `base-lineage-reviewer`：Base、来源关系、同届抄袭方向、commit 先后、掩盖手法、外部模块引入/适配。
- `module-*`：对应模块实现、真实工作量、相对 Base 差异、本模块文档声明复核。
- `doc-claim-reviewer`：reducer，只汇总模块文档复核与 doc evidence，不全仓重读代码。
- `history-ai-reviewer`：提交时间线、AI 使用声明、批量导入与生成痕迹。
- `cheat-detector`：测试造假、runner 绕过、prompt injection。
- `contradiction-arbiter`：唯一能解决冲突的角色。
- `report-editor`：只组装已接受评审片段，不创造事实、不读源码、不解决矛盾。

## 报告结构

```text
# <display_name> 评审报告
## 整体结论
## 重点结论
## Base 与来源关系
## 真实工作量账本
## 内核架构图
## 文档声明审查
## 开发历史与 AI 使用
## 作弊、刷分与提示注入风险
## 模块实现与 Base 差异
### <模块>
## 证据索引
```

文档、历史、作弊风险章节只在存在公开 finding 时出现。没有 finding 时完全省略，不写“未发现”占位。

## 前端

新前端在 `review_viewer/`，输入是 `site/report_data.json`、`evidence.jsonl` 和 `tags.json`。它是评审阅读器，不复用旧报告组件。

```bash
cd review_viewer
npm install
npm run typecheck
npm run build
```

## 校验

```bash
python -m unittest tests.test_pipeline
```

当前 acceptance tests 覆盖 identity、evidence、Base delta、机器名泄漏、未解决矛盾、deleted taxonomy、required taxonomy、fp_cache、report_data、evidence map、架构图和前端类型/build。
