# OS-Agent

OS-Agent 是 2026 年全国大学生计算机系统能力大赛操作系统设计赛（全国）OS 功能挑战赛道 proj18“面向小型操作系统的分析比对智能体系统设计”的参赛项目。

项目帮助内核赛道评委回答四类相互牵连的问题：作品从哪里发展而来、选手完成了哪些真实增量、内核模块实际上如何工作，以及文档、开发历史、AI 使用和测评定向代码是否存在需要复核的风险。系统不把相似度分数直接写成抄袭或原创结论，而是由多个 Claude Code sub-agent 结合源码、设计文档、Git 历史、blob 和 AST 事实共同判断。

## 评审准则的使用边界

OS-Agent 参加的是 Proj18 功能挑战赛道；仓库中的《操作系统设计赛内核实现赛道评审准则进一步说明》描述的是本系统所分析的内核作品的评价背景。最新准则用于审查当前目标作品，历届作品只作为 Base、外部来源和演进参照，不追溯判定其当年是否违规。

静态分析将风险结论分为三类：未运行真实测试却打印预录结果或合成通过数，称为“测试结果造假”；代码证据完整命中测例特征识别、输入/环境硬编码、通用机制或系统调用语义绕过时，称为“符合评审准则列明的违规模式”；成功存根、假 fd、硬编码平台信息或证据链不完整时，只写“需评委复核”。判断按上述顺序取证据能够支撑的最高等级；已经证明结果与真实执行脱钩时归入造假，只有触发、影响或来源尚未查清时才进入复核。源码不能替代平台日志、判分脚本、实际得分和现场答辩。


## 准备

1. 在 `config/works.yaml` 中人工维护参赛作品和开源参考仓库。参赛作品维护学校、队伍、作品名、可读展示名、仓库目录和评审分支；系统不猜作品名，也不自动重命名仓库。
2. 将作品 clone 到配置中的 `canonical_dir`。公开报告只能使用 `display_name`，不能使用平台仓库编号或 fork 数字后缀。
3. 首次分析前建立 HEAD 指纹库。
4. 在 Claude Code 中手动启动 `/os-agent`，并给出要分析的 `work_id`。
5. 人工复核“不确定”或“需评委复核”的结论，尤其是同届传播方向、成功存根对平台成绩的实际影响和 AI 使用判断。

身份配置示例见 `config/works.yaml.example`。

`repository_type: competition` 表示参赛作品；`repository_type: reference` 表示开源参考。参考仓库再用 `reference_kind: kernel | framework | component` 区分完整内核、底层框架和单模块实现。只有 component 填写 `module_ids`，值直接使用 Taxonomy 模块 ID，例如 Ext4 实现使用 `[file-system]`。这些字段只传给 Agent 说明候选身份和阅读范围，不参与相似度计算：完整内核和框架可以成为主 Base，component 只能作为次级来源交给对应模块 Agent，最终仍须以源码边界、引入提交和适配历史为准。

## 项目结构

```text
config/                       人工维护的作品身份
repos/                        人工规范化命名的本地 Git 仓库
fp_cache/<work-id>/<commit>/  按作品和 commit 保存的 blob/AST 指纹
fp_cache/history_searches/    历史 blob 召回事实
fp_cache/comparisons/         明确 commit 对的比较事实
.claude/skills/os-agent/      Claude Code 主 Agent 调度规则
.claude/agents/               Base、模块、历史、风险、仲裁和报告角色
core/review_case/             Git/指纹事实、Markdown 解析、轻量校验和编译
scripts/review.py             主 Agent 使用的事实脚本入口
review_viewer/                Vite React 报告与作品索引前端
doc/                          面向评委的 LaTeX/PDF 设计书
output/<work-id>/             单件作品的分析产物
```

项目不再使用旧 `report.json`、旧 view model、程序生成的 Agent task、MCP 流程状态机或 Python 拼接的报告前端。

## 安装运行环境

推荐使用 Ubuntu 或 WSL。Linux 环境能直接使用 Git、Python 和作品原有目录结构，也不会因 Windows 保留文件名导致部分 Rust 仓库无法完整 clone。

### Claude Code

按 [Claude Code 官方安装文档](https://code.claude.com/docs/en/setup) 使用原生安装器，并检查安装状态：

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude --version
claude doctor
```

OS-Agent 不要求安装语言服务器、裸机交叉编译器或作品指定的 Rust nightly。主 Agent 通过锁定版本的源码、构建文件、Git 历史、Blob/AST 指纹和精确检索完成调查，不执行作品即可产出主要结论。

### Python 依赖

```bash
which python
python -m pip install -r requirements.txt
```

仓库已跟踪 `review_viewer/dist/`，正常运行分析和发布报告不需要安装 Node.js 或重新 build。只有修改前端源码时才执行：

```bash
cd review_viewer
npm install
npm run build
cd ..
```

本机 Claude Code 使用 `PATH` 中的默认 `python`；当前开发机应显示 `/home/leo/miniconda3/bin/python`。安装依赖和后续运行必须使用同一个 `python`，这样无需额外激活环境，也不会出现“依赖装进一个解释器、事实脚本却由另一个解释器执行”的情况。

`requirements.txt` 只包含当前分析链路使用的 Python 包：YAML/Markdown frontmatter、PDF/DOCX 文本提取，以及 C、C++、Rust 的 AST 指纹。Git 和 `rg` 是 Claude Code 调查源码与历史时使用的系统命令；Node.js、npm 及 `review_viewer/package.json` 中的包只用于构建 React 阅读器，不属于 Python 运行时。

项目在 `.claude/settings.json` 中将 Claude Code 默认权限模式设为 `auto`。Auto mode 需要 Claude Code 2.1.83 或更高版本，并要求账号、模型和服务商满足 Claude Code 的支持条件；当前开发机使用 2.1.210。主 Agent 进入 Auto mode 后，sub-agent 继承相同模式，由安全分类器检查文件写入和命令执行。若当前账号不支持 Auto mode，可用 `claude --permission-mode acceptEdits` 启动，但后台并行角色需要使用的 evidence、校验和 Git 命令必须提前在 `/permissions` 中授权，否则需要改为前台运行。

## 建立和使用指纹库

首次使用或 `works.yaml` 中有一批作品尚未建库时，运行全量命令：

```bash
python scripts/review.py build-fp-cache
```

该命令读取每件作品的 `review_branch`，为该分支当前 HEAD 同时生成 Blob 和 AST 指纹。缓存不使用 `index.json`，目录中的 commit 就是快照身份：

缓存直接按以下结构保存：

```text
fp_cache/
  <work-id>/<commit>/
    manifest.json
    blob.json
    ast.json
  history_searches/
  comparisons/
```

`blob.json` 保留每个 `(完整路径, blob, mode)` 实例，不 strip 路径，也不把相同内容折叠成集合。`ast.json` 保存函数和汇编块的结构指纹。批量 HEAD 检索时，程序读取 `works.yaml`，解析每件作品 `review_branch` 的当前 commit，再直接打开对应指纹目录；历史 commit 虽然存放在同一目录中，但不会混入 HEAD 候选。

某件作品的 `review_branch` 向前推进后，只更新该作品即可；`--work-id` 可以重复指定，并且不会改动其他作品缓存：

```bash
python scripts/review.py build-fp-cache --work-id <work-id>
python scripts/review.py build-fp-cache --work-id <work-id-1> --work-id <work-id-2>
```

开始一个作品的分析后，将锁定版本绑定到 case，再从全库召回 HEAD 候选：

```bash
python scripts/review.py init --work-id <work-id>
python scripts/review.py fingerprint --case-dir output/<work-id>
python scripts/review.py search-head-candidates --case-dir output/<work-id>
```

`fingerprint` 会把目标锁定版本及其缓存位置写入 `case_state/facts/fingerprint.json`；完整缓存已经存在时直接复用，不重复构建 AST。`search-head-candidates` 要求 `works.yaml` 中所有作品当前 `review_branch@HEAD` 都已有完整缓存，输出只用于候选召回，不直接决定 Base。

HEAD blob/AST 只负责从大量作品中召回线索。Base 必须继续追到“目标作品引入 commit 与来源作品历史 commit”的明确 commit 对；历史 commit 默认只建立 blob，只有筛出的少量 commit 对才运行 AST。

目标引入提交确定后，可以先用 Blob 扫描所有仓库的全部 refs，寻找历史来源候选：

```bash
python scripts/review.py search-history-blobs \
  --target-work <目标work-id> --target-commit <目标引入commit> \
  [--target-prefix <目标核心目录>]
```

Base 角色先在目标评审分支的祖先中定位代码首次大规模出现的位置，再核对来源仓库的声明分支、tag 和其他 refs。明确 commit 对时必须同时传入两侧 ref；路径范围由 Base 角色根据已确认的主骨架和外部模块边界指定，脚本不自动判断 vendor 或学生代码：

```bash
python scripts/review.py compare-commits \
  --left-work <目标work-id> --left-ref <目标评审分支> --left-commit <目标引入commit> \
  --right-work <Base work-id> --right-ref <Base分支或tag> --right-commit <Base历史commit> \
  --left-include-prefix <目标核心目录> --right-include-prefix <Base核心目录> \
  [--left-exclude-prefix <目标排除目录>] [--right-exclude-prefix <Base排除目录>] [--ast]
```

脚本会检查 commit 是否能从给定 ref 到达。比较结果同时保存双方显示名、ref tip、实际 commit、过滤范围、同路径 Blob、跨路径 Blob 和包含率。`--ast` 只用于已经筛出的少量 commit 对，不用于全历史扫描。

## Claude Code 如何分析

`/os-agent` 启动的会话是主 Agent。主 Agent 直接使用 Claude Code 的 Agent 能力调用 `.claude/agents/` 中的命名角色，不通过 Python 创建任务文件。每次调用固定传入以下字段，以减少长上下文造成的注意力衰减：

```text
case_dir: <绝对路径>
output_path: <case_dir 内的绝对路径>
question: <本次问题>
allowed_materials: <允许读取的仓库、commit、文件和 evidence>
related_evidence: <E### 列表>
```

sub-agent 从仓库根目录启动，不会自动进入 `case_dir`。它只能写入调用消息给出的绝对 `output_path`；角色 prompt 中的 `base.md`、`modules/*.md` 等短路径只表示 case 内产物类型，不能直接作为相对当前工作目录的写入路径。角色完成后使用同一绝对 `case_dir` 和 `output_path` 自检，并返回 `SUCCESS: <绝对 output_path>`。

```text
准备事实
  └─ identity-check / init / inventory / fingerprint / HEAD 候选
       ↓
来源待定
  └─ base-lineage-reviewer
       ├─ 直接运行历史 Blob 召回与 commit 对比较
       └─ base.md = accepted | no_reliable_base
       ↓
源码版本准备
  └─ 主 Agent 固定目标评审 commit 与已接受的 Base 历史 commit
       ├─ 独立且干净的仓库 → 各自一次检出后冻结
       └─ 同仓双版本、脏工作区或版本冲突 → case_state/read/ 下 detached worktree
       ↓
模块与开发过程
  ├─ 主 Agent 将两个只读源码目录和 Base 模块交接内容传给 module-*
  └─ history-ai-reviewer 只分析引入后的持续演进与 AI 使用，不重新选择 Base
       ↓
联动复核
  ├─ 模块发现影响来源/历史/风险的新事实 → 重调对应角色
  ├─ doc-claim-reviewer 汇总模块中的声明复核
  └─ cheat-detector 在执行基线、来源归属和历史材料具备后检查测评定向与结果真实性
       ↓
冲突与成稿
  ├─ contradiction-arbiter 必须检查全部当前结论
  ├─ contradiction-check 固定本次仲裁覆盖的材料版本
  └─ report-editor 只消费有效仲裁结果，重写唯一 report.md
       ↓
轻量校验 / React 发布
```

状态由现有产物表达，不维护另一套程序状态机：

| 当前产物 | 主 Agent 下一步 |
|---|---|
| 尚无 `base.md` | 调用 `base-lineage-reviewer` |
| sub-agent 写完片段 | 由该角色运行 prompt 中的 `validate-fragment`；通过后返回 `SUCCESS: <path>` |
| Base 为 `accepted` | 准备目标最终版本和 Base 历史版本的冻结源码目录，再调用模块与历史角色 |
| Base 为 `no_reliable_base` | 准备目标最终版本的冻结源码目录，模块只描述自身实现 |
| 模块出现 `## 需联动结论` | 按语义重调 Base、历史、文档或风险角色 |
| Base、模块和 findings 已稳定 | 无论是否已发现冲突，都调用 `contradiction-arbiter` |
| `contradictions.md` 为 `unresolved` | 禁止调用 `report-editor` |
| 仲裁通过 | 仲裁角色运行 `contradiction-check`，记录本次覆盖的材料哈希 |
| Base、模块、finding、evidence 或仲裁文件改变 | 原仲裁结果过期；重新仲裁后再调用 `report-editor` |
| `report.md` 稳定 | `check-all` 校验并发布 |

每个角色 prompt 都直接给出自己的完整 frontmatter、标题顺序、可选值、输出路径和校验命令，sub-agent 不需要从主 Skill 猜测格式。程序只检查 Markdown 契约能否解析、必需章节是否存在、evidence ID 是否有效、作品名称是否规范以及是否仍有未解决冲突；不根据标题、摘录、路径或关键词推断结论领域和负责角色。抄袭方向、原创度、工作量、架构图真实性和测评影响仍由 Agent 与评委判断。

## Agent 角色与产物

| 角色 | 任务 | 唯一产物 |
|---|---|---|
| 主 Agent | 调用事实脚本、控制上下文、调度、发现联动和返工 | 不写分析结论 |
| `base-lineage-reviewer` | Base 历史版本、引入 commit、共同 Base、同届残差方向 | `base.md` |
| `module-*` | 单个内核模块的机制、Base 差异、工作量和功能声明复核 | `modules/<module>.md` |
| `history-ai-reviewer` | 读取已接受的 Base 边界，分析引入后的持续开发、模块演进、批量导入、贡献记录、AI 使用披露及人工验证；不重新选择 Base | `findings/history-ai.md` |
| `doc-claim-reviewer` | 汇总开发计划、模块声明、来源依赖、AI 披露和复现说明 | `findings/doc-claims.md` |
| `cheat-detector` | 测试结果造假、测例定向、非通用实现、成功存根和硬编码伪装 | `findings/cheat.md` |
| `contradiction-arbiter` | 必经的全局结论复核；对相反判断裁决或要求补证 | `issues/contradictions.md`、内部材料摘要 |
| `report-editor` | 统一名称、删除空章节、重写唯一正式报告和 Mermaid 架构图 | `report.md` |

文档和历史角色只要有可靠材料，就可以公开正面、中性或负面评价；完全无可评材料时才隐藏。`cheat-detector` 没有风险 finding 时始终不生成公开章节。风险结论必须保持“测试结果造假、符合评审准则列明的违规模式、需评委复核”三级边界。

Base 可靠时，模块角色必须解释相对 Base 的继承、适配、新增和缺失；没有可靠 Base 时只描述作品自身实现，不伪造差异。不存在的节点简短写 `absent`，不扩写占位内容。高级功能按源码实际发现加入，不要求架构图覆盖固定清单。

`base.md` 是来源结论和后续角色之间唯一的公开交接文件。它同时记录目标 `review ref@最终 commit`、目标引入 commit、Base `ref@历史 commit`，并按模块列出目标路径、Base 对应路径、相关适配提交和 Evidence ID。主 Agent 调用模块角色时，再通过 `allowed_materials` 传入 `target_tree`、`base_tree` 和该模块的交接段落。sub-agent 只用 `Read/Grep/Glob` 阅读这些冻结目录，不运行 `checkout`、`switch` 或 `reset`。

同届高相似作品必须分别追溯到共同历史 Base 的具体版本。双方均一次性引入同一上届作品时，交集首先归为共同来源；只有扣除共同 Base、第三方、测试代码和生成物后的核心残差仍有完整的双方引入链路，才允许讨论传播方向。“上传项目快照”一类根提交只能提供最早可见上界。

## Agent 如何固定证据

sub-agent 负责选择事实位置，脚本负责从锁定对象中提取内容、去重并分配编号。Agent 不得手写 `evidence.jsonl`、摘录、编号、可信度或支撑关系。相同事实位置重复添加会返回已有 Evidence ID。

```bash
# 指定 commit 中的源码或文本行
python scripts/review.py evidence span --case-dir output/<work-id> \
  --work-id <work-id> --commit <commit> --path <path> --lines 120:168 --title "页表映射实现"

# PDF 页、DOCX 段落或 Git 中的文本行
python scripts/review.py evidence document --case-dir output/<work-id> \
  --work-id <work-id> --commit <commit> --path docs/design.pdf --page 8 --title "内存设计声明"

# 仓库外的本地文档使用文件 SHA256 固定
python scripts/review.py evidence document --case-dir output/<work-id> \
  --work-id <work-id> --file collected/design.docx --paragraph 12 --title "开发过程声明"

# commit 元数据、父提交、时间和 numstat
python scripts/review.py evidence commit --case-dir output/<work-id> \
  --work-id <work-id> --commit <commit> --path kernel --title "内核批量引入提交"

# 已生成的 commit 对 Blob/AST 比较
python scripts/review.py evidence comparison --case-dir output/<work-id> \
  --file fp_cache/comparisons/<result>.json --title "引入版本与 Base 历史版本比较"

# 固定 Git 检索命中或零命中；--file 也可固定候选检索 JSON
python scripts/review.py evidence search --case-dir output/<work-id> \
  --work-id <work-id> --commit <commit> --pattern 'TPASS|Pass!' --path kernel --title "测试结果字符串检索"
```

每条命令成功后只打印 `E###`。Git 内容始终从指定 commit 读取并记录 object hash，工作区改动不会改变已经固定的摘录。`comparison` 会记录原始结果文件 SHA256，但公开站点只发布可读摘要。一个 Evidence ID 可以被多处结论引用，compiler 会反向列出它在报告和模块中的引用位置。

## 单件作品产物

```text
output/<work-id>/
  identity.md
  base.md
  evidence.jsonl
  modules/*.md
  findings/*.md
  issues/contradictions.md
  report.md
  tags.json
  case_state/
    manifest.json
    repo_snapshot.json
    works.snapshot.yaml
    contradiction-review.json
    facts/*
    read/*                    仅在同仓双版本、脏工作区或版本冲突时保存 detached worktree
  site/
    report_data.json
    evidence.jsonl
    report.html
    assets/*
```

`report.md` 是唯一正式文案。根目录 `evidence.jsonl` 保留调查过程中固定的全部事实卡；`site/evidence.jsonl` 和 `report_data.json` 只包含报告或公开模块实际引用的卡片。`report_data.v3` 不是文件名或第三份报告，而是 `site/report_data.json` 内部当前唯一接受的 schema 标识；该文件由 compiler 从 Markdown、模块 frontmatter 和 evidence 引用确定性生成，只供 React 前端读取，不能由 Agent 编写。它包含目标评审 ref、目标引入 commit、Base ref 和 Base 历史 commit，用于展示准确的来源版本关系；前端不会兼容或迁移其他 schema。

## 构建前端与发布

```bash
npm --prefix review_viewer run build

python scripts/review.py check-all --case-dir output/<work-id>
python scripts/review.py build-index --output output/site output/<work-id> [...]
```

React 阅读器提供作品搜索和筛选、从“来源基线—引入与适配—被评版本—分析结果”的来源轨迹、工作量账本、动态报告视图、真正渲染的 Mermaid 内核架构图，以及可从 `[@E###]` 打开的证据抽屉。来源节点显示中文作品名与 `ref@commit`；比较证据显示两侧分支、commit 和过滤范围。Python 只编译 `report_data.json` 并复制已构建的前端资源，不生成界面或维护另一套摘要。

`scripts/review.py` 主要由主 Agent 调用。对人最重要的是 `build-fp-cache`、`check-all` 和 `build-index`；其余命令提供版本锁定、HEAD 候选召回、历史 blob 搜索和明确 commit 对比较等事实，不负责做语义结论。

## 开发历程以及遇到的困难

详见 [doc/os-agent-design.pdf](doc/os-agent-design.pdf)


## AI Usage情况

本项目在开发过程中使用 Claude Code、Codex、Cursor、Antigravity 的 AI 编程工具（模型GPT5.5/5.6、DeepSeek V4、Sonnet 4.6、Gemini 3.5 Flash）辅助完成大部分代码实现、重复性工作、文档整理和流程设计讨论。AI 工具主要用于提升实现效率、生成候选方案和辅助检查，Agent的流程设计、skill的内容由我起草设计，LLM进行结构整理，边界条件的确认。最终的Agent职责边界、工作流设计、脚本功能的取舍以及职责设计、报告校验的粒度、查重边界与结论确认仍由项目维护者定义。


## 参赛信息

- 赛事：2026 全国大学生计算机系统能力大赛-操作系统设计赛
- 赛道：OS 功能挑战赛道
- 项目：proj18 · 面向小型操作系统的分析比对智能体系统设计
- 队伍名称：OS照妖镜
- 队员：刘建博、李佳峻
- 学校：华中科技大学


## 选手常常引用的外部 GitHub 库，这里列出以供参考


### 基础内核框架 / OS 框架

| 仓库 | 说明 | 本地 |
|---|---|:---:|
| [rcore-os/rCore](https://github.com/rcore-os/rCore) | rCore 内核参考实现 | |
| [rcore-os/zCore](https://github.com/rcore-os/zCore) | Zircon 兼容的 Rust OS | ✓ |
| [arceos-org/arceos](https://github.com/arceos-org/arceos) | ArceOS 模块化 unikernel | ✓ |
| [arceos-org/starry-next](https://github.com/arceos-org/starry-next) | Starry Next（官方版） | ✓ |
| [Starry-OS/StarryOS](https://github.com/Starry-OS/StarryOS) | 基于ArceOS的 | ✓ |
| [Starry-OS/arceos](https://github.com/Starry-OS/arceos) | StarryOS 使用的 arceos fork | ✓ |
| [asterinas/asterinas](https://github.com/asterinas/asterinas) | Asterinas 安全 OS 框架（framekernel） | ✓ |
| [Byte-OS/ByteOS](https://github.com/Byte-OS/ByteOS) | ByteOS 模块化 Rust OS | ✓ |
| [sandyyyz/Re-XVapor](https://github.com/sandyyyz/Re-XVapor) | xv6 衍生内核-25年作品github版 | |
| [aether-os-studio/naos](https://github.com/aether-os-studio/naos) | NaOS 操作系统 | ✓ |
| [managarm/managarm](https://github.com/managarm/managarm) | 异步微内核 OS | ✓ |
| [seL4/seL4](https://github.com/seL4/seL4) | seL4 形式化验证微内核 | ✓ |
| [unikraft/unikraft](https://github.com/unikraft/unikraft) | Unikraft unikernel 框架 | ✓ |
| [RT-Thread/rt-thread](https://github.com/RT-Thread/rt-thread) | RT-Thread RTOS | ✓ |
| [mit-pdos/xv6-riscv](https://github.com/mit-pdos/xv6-riscv) | xv6 RISC-V 版（MIT 教学） | ✓ |
| [mit-pdos/xv6-public](https://github.com/mit-pdos/xv6-public) | xv6 x86 版（MIT 教学） | ✓ |
| [HUSTOS/xv6-k210](https://github.com/HUST-OS/xv6-k210)| 2021一等奖作品github版（gitlab版不可访问） |
| [rcore-os/rCore-Tutorial-v3](https://github.com/rcore-os/rCore-Tutorial-v3) | rCore Tutorial v3 教学 OS | ✓ |
| [chyyuu/ucore_os_lab](https://github.com/chyyuu/ucore_os_lab) | uCore OS 教学实验 | ✓ |
| [hawkw/mycelium](https://github.com/hawkw/mycelium) | Rust 异步 OS 内核 | |
| [cbiffle/lilos](https://github.com/cbiffle/lilos) | 最小化 async Rust RTOS | |
| [equation314/nimbos](https://github.com/equation314/nimbos) | 教学用 OS（类 rCore） | |
| [torvalds/linux](https://github.com/torvalds/linux) | Linux 内核（参考/ABI 兼容） | |
| [ChenRuiwei/Phoenix](https://github.com/ChenRuiwei/Phoenix) | 2024年OS竞赛一等奖作品(纯Rust，ArceOS系，被多个2026队伍作为设计参考) | ✓ |
| [Tencent/TencentOS-tiny](https://github.com/Tencent/TencentOS-tiny) | 腾讯物联网 OS | |

### 内存分配器

| 仓库 | 说明 |
|---|---|
| [rcore-os/buddy_system_allocator](https://github.com/rcore-os/buddy_system_allocator) | Buddy 伙伴系统分配器（Rust） |
| [jasonwhite/buddy_system_allocator](https://github.com/jasonwhite/buddy_system_allocator) | 同上（原版） |
| [rcore-os/bitmap-allocator](https://github.com/rcore-os/bitmap-allocator) | 位图帧分配器（Rust） |
| [arceos-org/allocator](https://github.com/arceos-org/allocator) | ArceOS 通用分配器 crate |
| [arceos-org/slab_allocator](https://github.com/arceos-org/slab_allocator) | Slab 分配器 |
| [cloudwu/buddy](https://github.com/cloudwu/buddy) | C 语言 Buddy 分配器 |
| [mattconte/tlsf](https://github.com/mattconte/tlsf) | TLSF 两级分离适应分配器 |
| [OlegHahm/tlsf](https://github.com/OlegHahm/tlsf) | TLSF 另一实现 |
| [blanham/liballoc](https://github.com/blanham/liballoc) | 轻量级 liballoc 分配器 |

### 文件系统库

| 仓库 | 说明 |
|---|---|
| [gkostka/lwext4](https://github.com/gkostka/lwext4) | C 语言轻量级 ext4 库 |
| [elliott10/lwext4_rust](https://github.com/elliott10/lwext4_rust) | lwext4 的 Rust 绑定 |
| [rafalh/rust-fatfs](https://github.com/rafalh/rust-fatfs) | Rust FAT 文件系统库 |
| [rafalh/rust-fscommon](https://github.com/rafalh/rust-fscommon) | rust-fatfs 配套工具库 |
| [yuoo655/ext4_rs](https://github.com/yuoo655/ext4_rs) | 纯 Rust ext4 实现 |
| [Starry-OS/rsext4](https://github.com/Starry-OS/rsext4) | Starry 的 Rust ext4 库 |
| [webdesus/fs_extra](https://github.com/webdesus/fs_extra) | Rust FS 扩展工具 |
| [undefined-os/vfs](https://github.com/undefined-os/vfs) | VFS 虚拟文件系统抽象层 |

### 网络协议栈

| 仓库 | 说明 |
|---|---|
| [smoltcp-rs/smoltcp](https://github.com/smoltcp-rs/smoltcp) | 纯 Rust TCP/IP 协议栈 |
| [rcore-os/smoltcp](https://github.com/rcore-os/smoltcp) | rCore 修改版 smoltcp |
| [asterinas/smoltcp](https://github.com/asterinas/smoltcp) | Asterinas fork |

### 硬件驱动 / HAL

| 仓库 | 说明 |
|---|---|
| [rcore-os/virtio-drivers](https://github.com/rcore-os/virtio-drivers) | VirtIO 设备驱动（Rust） |
| [arceos-org/axdriver_crates](https://github.com/arceos-org/axdriver_crates) | ArceOS 驱动 crates 集合 |
| [arceos-org/axplat_crates](https://github.com/arceos-org/axplat_crates) | ArceOS 平台支持 crates |
| [rcore-os/device_tree-rs](https://github.com/rcore-os/device_tree-rs) | 设备树（DTB）解析库 |
| [repnop/fdt](https://github.com/repnop/fdt) | FDT/DTB 解析库 |
| [rust-embedded/riscv](https://github.com/rust-embedded/riscv) | RISC-V 寄存器访问 crate |
| [rcore-os/riscv](https://github.com/rcore-os/riscv) | rCore 修改版 riscv crate |
| [wyfcyx/k210-hal](https://github.com/wyfcyx/k210-hal) | K210 HAL |
| [wyfcyx/k210-pac](https://github.com/wyfcyx/k210-pac) | K210 PAC |
| [wyfcyx/k210-soc](https://github.com/wyfcyx/k210-soc) | K210 SoC 支持 |
| [riscv-rust/fu740-hal](https://github.com/riscv-rust/fu740-hal) | FU740 HAL |
| [riscv-rust/fu740-pac](https://github.com/riscv-rust/fu740-pac) | FU740 PAC |
| [T-head-Semi/openc906](https://github.com/T-head-Semi/openc906) | T-Head C906 开源实现 |
| [QIUZHILEI/dw_sd](https://github.com/QIUZHILEI/dw_sd) | DesignWare SD 控制器驱动 |

### SBI / 引导 / 固件

| 仓库 | 说明 |
|---|---|
| [rustsbi/rustsbi](https://github.com/rustsbi/rustsbi) | RISC-V SBI 实现（Rust） |
| [rustsbi/rustsbi-d1](https://github.com/rustsbi/rustsbi-d1) | D1 专用 RustSBI |
| [luojia65/rustsbi](https://github.com/luojia65/rustsbi) | 早期 RustSBI |
| [riscv-software-src/opensbi](https://github.com/riscv-software-src/opensbi) | OpenSBI 开源实现 |
| [elliott10/opensbi](https://github.com/elliott10/opensbi) | 修改版 OpenSBI |
| [sifive/freedom-u-sdk](https://github.com/sifive/freedom-u-sdk) | SiFive U 系列 SDK |

### ELF / 二进制解析

| 仓库 | 说明 |
|---|---|
| [nrc/xmas-elf](https://github.com/nrc/xmas-elf) | Rust ELF 解析库 |
| [zlc-dev/xmas-elf](https://github.com/zlc-dev/xmas-elf) | xmas-elf 修改版 |
| [m4b/goblin](https://github.com/m4b/goblin) | 多格式二进制解析（ELF/PE/Mach-O） |
| [arceos-org/kernel-elf-parser](https://github.com/arceos-org/kernel-elf-parser) | 内核 ELF 加载解析器 |

### 并发 / 数据结构 / 页表

| 仓库 | 说明 |
|---|---|
| [Amanieu/intrusive-rs](https://github.com/Amanieu/intrusive-rs) | 侵入式数据结构（Rust） |
| [greatbridf/intrusive-rs](https://github.com/greatbridf/intrusive-rs) | fork 版本 |
| [arceos-org/linked_list](https://github.com/arceos-org/linked_list) | 侵入式链表 |
| [arceos-org/scheduler](https://github.com/arceos-org/scheduler) | 调度器 crate（CFS/FIFO/Round-Robin） |
| [arceos-org/page_table_multiarch](https://github.com/arceos-org/page_table_multiarch) | 多架构页表实现 |
| [rcore-os/page_table_multiarch](https://github.com/rcore-os/page_table_multiarch) | rCore 版本多架构页表 |
| [tokio-rs/tracing](https://github.com/tokio-rs/tracing) | Rust 结构化日志/追踪框架 |
| [asterinas/inherit-methods-macro](https://github.com/asterinas/inherit-methods-macro) | 方法继承过程宏 |
| [asterinas/inventory](https://github.com/asterinas/inventory) | 编译期静态注册表 |
| [theseus-os/irq_safety](https://github.com/theseus-os/irq_safety) | 中断安全 Mutex 封装 |
| [alacritty/vte](https://github.com/alacritty/vte) | VT100 终端转义序列解析（Rust） |

### C/C++ 系统库

| 仓库 | 说明 |
|---|---|
| [electronicarts/EASTL](https://github.com/electronicarts/EASTL) | EA STL C++ 标准库 |
| [mendsley/tinystl](https://github.com/mendsley/tinystl) | 最小化 STL 实现 |
| [martinmoene/expected-lite](https://github.com/martinmoene/expected-lite) | C++ `expected<T,E>` 实现 |
| [bbqsrc/core2](https://github.com/bbqsrc/core2) | Rust no_std IO 封装 |
| [jethrogb/rust-core_io](https://github.com/jethrogb/rust-core_io) | Rust `core::io` 扩展 |
| [jasonwhite/syscalls](https://github.com/jasonwhite/syscalls) | Rust syscall 封装 crate |
| [bminor/glibc](https://github.com/bminor/glibc) | GNU C 库（参考） |
| [richfelker/musl-cross-make](https://github.com/richfelker/musl-cross-make) | musl 交叉编译工具链构建 |
| [managarm/frigg](https://github.com/managarm/frigg) | 轻量级 C++ 工具库 |
| [managarm/libasync](https://github.com/managarm/libasync) | C++ 协程/异步库 |
| [managarm/bragi](https://github.com/managarm/bragi) | IDL 消息传递框架 |

### 开发工具 / 构建

| 仓库 | 说明 |
|---|---|
| [rust-embedded/cargo-binutils](https://github.com/rust-embedded/cargo-binutils) | Cargo LLVM 工具链封装 |
| [matklad/cargo-xtask](https://github.com/matklad/cargo-xtask) | Cargo 任务扩展模式 |
| [ninja-build/ninja](https://github.com/ninja-build/ninja) | Ninja 构建系统 |
| [cyrus-and/gdb-dashboard](https://github.com/cyrus-and/gdb-dashboard) | GDB 调试增强界面 |
| [rust-lang/mdbook](https://github.com/rust-lang/mdbook) | mdBook 文档工具 |
| [managarm/xbstrap](https://github.com/managarm/xbstrap) | 交叉编译 bootstrap 工具 |

### 规范文档 / 参考资料

| 仓库 | 说明 |
|---|---|
| [riscv/riscv-isa-manual](https://github.com/riscv/riscv-isa-manual) | RISC-V ISA 官方手册 |
| [riscv-non-isa/riscv-sbi-doc](https://github.com/riscv-non-isa/riscv-sbi-doc) | RISC-V SBI 规范 |
| [riscv-non-isa/riscv-asm-manual](https://github.com/riscv-non-isa/riscv-asm-manual) | RISC-V 汇编手册 |
| [riscv-non-isa/riscv-elf-psabi-doc](https://github.com/riscv-non-isa/riscv-elf-psabi-doc) | RISC-V ELF psABI 规范 |
| [devicetree-org/devicetree-specification](https://github.com/devicetree-org/devicetree-specification) | 设备树规范 |
| [loongson/LoongArch-Documentation](https://github.com/loongson/LoongArch-Documentation) | LoongArch 架构文档 |
| [seL4/l4v](https://github.com/seL4/l4v) | seL4 形式化验证证明 |



## Risk/Todo:
### 如果一个作品自己未声明跨语言重写（大概率使用Agent/AI/LLM）
### 声明Base未在repo内（github开源作品）?-> fallback commit可解决？
### 如何减小模型能力对描述的影响？待测评不同模型的描述效果。
