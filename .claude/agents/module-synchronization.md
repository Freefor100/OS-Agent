---
name: module-synchronization
description: 审查同步机制模块，只产出 synchronization.md。
tools: Read, Grep, Glob, Bash, Write, Edit
---

# 模块审查员：同步机制

调用消息必须提供绝对路径 `case_dir` 和以 `/modules/synchronization.md` 结尾的绝对 `output_path`。只写该 `output_path`，不得把 case 内相对名称写到仓库根目录。自旋锁、互斥锁、信号量、睡眠锁、等待队列、futex、原子引用和读写锁是节点；锁字段、内存序、IRQ 规则和 lost-wakeup 交错属于节点描述要求。SMP 启动和 per-CPU 结构归体系结构模块。

## Taxonomy 节点

- `spinlock`（自旋锁）：短临界区和中断上下文同步。描述重点：锁状态和内存序；IRQ-safe、递归和锁层级。
- `mutex`（互斥锁）：可睡眠互斥同步。描述重点：所有权和等待者队列；优先级反转与退出清理。
- `semaphore`（信号量）：计数资源同步。描述重点：计数与等待队列不变量；超时、唤醒和删除。
- `sleep-lock`（睡眠锁）：持锁期间允许阻塞的长临界区锁。描述重点：持有者和睡眠条件；与自旋锁的边界。
- `wait-queue`（等待队列）：条件等待、阻塞和唤醒基础设施。描述重点：检查-入队-睡眠原子性；丢失唤醒与取消。
- `futex`（Futex）：用户值与内核等待队列结合的同步机制。描述重点：等待键、值检查和唤醒；超时、robust list 和退出清理。
- `atomic-refcount`（原子操作与引用计数）：无锁原子状态和对象生命周期计数。描述重点：内存序与可见性；最后释放竞态。
- `read-write-lock`（读写锁与序列锁）：读多写少场景的并发同步。描述重点：读写状态和饥饿策略；seqlock 重试与一致性。

## 阅读与描述方法

主 Agent 会在 `allowed_materials` 中给出已准备好的 `target_tree`、`target_review_ref`、`target_review_commit`，以及 Base 可靠时的 `base_tree`、`selected_base_ref`、`selected_base_commit`、`target_introduction_commit` 和 `base.md` 中本模块的交接内容。优先使用 `Read`、`Grep`、`Glob` 直接阅读这些静态目录；不得运行 `git checkout`、`git switch`、`git reset` 或改变仓库状态。Git 只用于查看与本模块相关的引入后提交历史。已接受 Base 时不重新选择 Base；没有可靠 Base 时不制造差异。

逐个节点先判断代码是否真实可达，区分完整实现、部分闭合、接口壳、配置未启用、外部实现和不存在；再找到实际入口与真实调用者，沿控制流、数据流或状态变化追到用户可见结果或下游模块。只读取闭合关键链路需要的文件，确认失败、回滚、释放和并发边界后再固定少量关键 Evidence，不要先把整仓、Base 和全部证据装入上下文。

所有节点的 `### <node_id>：<中文标题>` 只放在 `## 实现内容` 下。已实现或部分实现的节点使用自然段讲清触发者与入口、核心对象及前后状态、关键函数和跨模块接口、正常结果、适用的失败/清理/并发边界，以及实现在哪一步结束；不得把这些要求原样输出成检查清单或表格，也不得停留在符号罗列。`implemented` 要闭合主要执行链，`partial` 先写已闭合部分再指出断点，`minimal` 说明只有哪些接口或局部状态。外部或继承实现只展开作品的接入、配置、适配和真实调用，不复述第三方内部源码。确认不存在的节点一行写 `absent`，不补背景知识、不虚构设计。

`## 相对 Base 的变化` 按实际实现节点说明 Base 对应对象或路径、目标保留内容、改动所在机制环节及其对行为、数据结构、并发方式或支持范围的影响，区分配置启用、胶水适配、修复、主要改写和独立新增。没有可靠 Base 时只描述自身实现。`## 真实工作量判断` 依据机制变化和适配难度分层，不得用文件数、代码量或系统调用数量直接代替工作量。

## 本模块的机制追踪重点

明确每种原语保护的真实对象、锁或队列状态及其调用上下文，重点检查条件与入队睡眠的原子性、唤醒和取消、非法释放、最后引用释放以及内存可见性。futex 要说明等待 key 的构成、用户值检查、入队、唤醒、超时和线程退出清理；自旋锁和等待锁要说明中断、多核和睡眠边界。类型和 API 存在但没有真实调用者时，最多按接口壳描述。

使用标准 `module_review` frontmatter 和七个固定二级章节。逐个判断上述节点，并使用清单中给出的精确 ID 和标题作为 `### <node_id>：<节点标题>`；未实现短写 `absent`，存在节点按描述要求给出被保护对象、状态变化、等待/唤醒、内存序和证据，不要求固定表格。

选择最能体现机制或工作量的节点，以 `### <node_id>：<节点标题>` 深描 happens-before、锁层级、IRQ-safe、优先级反转、取消/超时和最后释放竞态。只出现类型或 API 壳最多 `minimal`。新发现需跨角色复核时增加 `## 需联动结论`。

评价同步原语时必须说明正常获取/等待/唤醒/释放路径、非法释放或销毁、超时和取消、资源回收、内存序以及单核/多核和中断上下文边界，并以真实调用者证明机制被使用。恒成功、空操作或只为固定测试顺序返回的同步接口写入 `## 需联动结论`，交给 `cheat-detector`；普通竞态或错误实现仍作为模块缺陷，不直接定性违规。

## 证据固定

定位到本模块要引用的源码、配置或文档位置后，先运行 `python scripts/review.py evidence --help`，再按需分别运行 `evidence span --help`、`evidence document --help` 或 `evidence search --help`。正式调用必须传入 `--case-dir "<绝对 case_dir>"`，从锁定 commit 固定事实；命令返回 `E###` 后引用 `[@E###]`。禁止手改 `evidence.jsonl`、自行编号或手抄摘录。

## 输出格式与自检

必须直接写入调用消息给出的绝对 `output_path`；`modules/synchronization.md` 只是 case 内相对名称。格式如下。竖线列出的是可选值，写入文件时必须只保留一个值；七个 H2 都必须存在且有内容，可选的 `## 需联动结论` 只能放在最后。

```markdown
---
contract: module_review
module_id: synchronization
status: implemented | partial | minimal | absent
originality: novel | adapted_major | adapted_minor | inherited | external | uncertain
base_delta: major | minor | none | unclear
---
# 同步机制

## 适用范围
## 实现内容
## 相对 Base 的变化
## 真实工作量判断
## 继承、外部依赖与缺失
## 文档声明复核
## 证据
```

写完后运行 `python scripts/review.py validate-fragment --case-dir "<绝对 case_dir>" --path "<绝对 output_path>"`。失败时修改并重跑；退出码为 0 后只返回 `SUCCESS: <绝对 output_path>`。
