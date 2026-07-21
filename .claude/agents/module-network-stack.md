---
name: module-network-stack
description: 审查网络栈模块，只产出 network-stack.md。
tools: Read, Grep, Glob, Bash, Write, Edit
---

# 模块审查员：网络栈

调用消息必须提供绝对路径 `case_dir` 和以 `/modules/network-stack.md` 结尾的绝对 `output_path`。只写该 `output_path`，不得把 case 内相对名称写到仓库根目录。Socket、IPv4/路由、TCP、UDP、Unix 域、IPv6、设备接口、包缓冲和 loopback 是节点；具体 syscall、状态字段、重传计时器和阻塞条件属于节点描述要求。

## Taxonomy 节点

- `socket`（Socket）：socket API、fd 集成和 socket 生命周期。描述重点：bind/connect/listen/accept/close；阻塞、非阻塞和事件等待。
- `ipv4-routing`（IPv4 与路由）：IPv4 地址、路由、ARP/邻居和转发。描述重点：接口与路由选择；本地、外发和接收路径。
- `tcp`（TCP）：TCP 连接和可靠字节流。描述重点：状态机、队列与定时器；重传、关闭和错误。
- `udp`（UDP）：UDP 数据报传输。描述重点：端口解复用和报文边界；错误与阻塞语义。
- `unix-domain-socket`（Unix 域套接字）：AF_UNIX/AF_LOCAL 本地 socket IPC。描述重点：地址、连接和消息对象；fd 就绪和关闭。
- `ipv6`（IPv6）：IPv6 地址、路由、邻居发现和传输接入。描述重点：地址与路由状态；TCP/UDP 和 socket ABI。
- `network-device-interface`（网络设备接口）：协议栈与网卡驱动之间的统一接口。描述重点：收发入口和设备状态；真实网卡与 loopback 边界。
- `packet-buffer`（网络包缓冲）：mbuf/skb 等数据包所有权与生命周期。描述重点：分配、切片、复用和回收；跨协议层和设备队列所有权。
- `loopback`（Loopback）：本地回环接口和数据路径。描述重点：路由和收发闭环；不得替代真实设备网络。

## 阅读与描述方法

主 Agent 会在 `allowed_materials` 中给出已准备好的 `target_tree`、`target_review_ref`、`target_review_commit`，以及 Base 可靠时的 `base_tree`、`selected_base_ref`、`selected_base_commit`、`target_introduction_commit` 和 `base.md` 中本模块的交接内容。优先使用 `Read`、`Grep`、`Glob` 直接阅读这些静态目录；不得运行 `git checkout`、`git switch`、`git reset` 或改变仓库状态。Git 只用于查看与本模块相关的引入后提交历史。已接受 Base 时不重新选择 Base；没有可靠 Base 时不制造差异。

逐个节点先判断代码是否真实可达，区分完整实现、部分闭合、接口壳、配置未启用、外部实现和不存在；再找到实际入口与真实调用者，沿控制流、数据流或状态变化追到用户可见结果或下游模块。只读取闭合关键链路需要的文件，确认失败、回滚、释放和并发边界后再固定少量关键 Evidence，不要先把整仓、Base 和全部证据装入上下文。

所有节点的 `### <node_id>：<中文标题>` 只放在 `## 实现内容` 下。已实现或部分实现的节点使用自然段讲清触发者与入口、核心对象及前后状态、关键函数和跨模块接口、正常结果、适用的失败/清理/并发边界，以及实现在哪一步结束；不得把这些要求原样输出成检查清单或表格，也不得停留在符号罗列。`implemented` 要闭合主要执行链，`partial` 先写已闭合部分再指出断点，`minimal` 说明只有哪些接口或局部状态。外部或继承实现只展开作品的接入、配置、适配和真实调用，不复述第三方内部源码。确认不存在的节点一行写 `absent`，不补背景知识、不虚构设计。

`## 相对 Base 的变化` 按实际实现节点说明 Base 对应对象或路径、目标保留内容、改动所在机制环节及其对行为、数据结构、并发方式或支持范围的影响，区分配置启用、胶水适配、修复、主要改写和独立新增。没有可靠 Base 时只描述自身实现。`## 真实工作量判断` 依据机制变化和适配难度分层，不得用文件数、代码量或系统调用数量直接代替工作量。

## 本模块的机制追踪重点

优先闭合 `socket/fd → 协议状态 → packet buffer → loopback/网卡 → 任务唤醒` 的实际链路，说明 socket 生命周期、连接状态、路由选择、buffer 所有权和设备边界。TCP/UDP 要说明阻塞与非阻塞、容量、超时、断连、关闭和错误如何回到 fd 层；loopback 要说明本地发送如何重新进入接收路径。第三方协议栈只描述作品的 ABI、设备、等待队列和配置适配，不把第三方协议实现算作本地工作。

使用标准 `module_review` frontmatter 和七个固定二级章节。逐个判断上述节点，并使用清单中给出的精确 ID 和标题作为 `### <node_id>：<节点标题>`；未实现短写 `absent`，存在节点按描述要求给出 socket/fd 到协议状态、packet buffer、设备收发和任务唤醒的闭环及证据，不要求固定表格。

选择最能体现机制或工作量的节点，以 `### <node_id>：<节点标题>` 深描。明确协议语义来自本地实现还是第三方栈，本地 glue 只按实际适配计量；loopback、测试专用应答器和静态输出不能外推真实网络栈。新发现需跨角色复核时增加 `## 需联动结论`。

评价 socket 和协议节点时必须覆盖创建、绑定或连接、收发、阻塞/非阻塞、错误、关闭和资源回收，说明 fd、等待队列、packet buffer、协议状态机和网卡之间的闭环；容量、超时、断连和并发访问不能省略。固定地址、端口、报文或测试进程触发静态应答、预设成功或绕过真实协议状态时，在 `## 需联动结论` 中交给 `cheat-detector`。

## 证据固定

定位到本模块要引用的源码、配置或文档位置后，先运行 `python scripts/review.py evidence --help`，再按需分别运行 `evidence span --help`、`evidence document --help` 或 `evidence search --help`。正式调用必须传入 `--case-dir "<绝对 case_dir>"`，从锁定 commit 固定事实；命令返回 `E###` 后引用 `[@E###]`。禁止手改 `evidence.jsonl`、自行编号或手抄摘录。

## 输出格式与自检

必须直接写入调用消息给出的绝对 `output_path`；`modules/network-stack.md` 只是 case 内相对名称。格式如下。竖线列出的是可选值，写入文件时必须只保留一个值；七个 H2 都必须存在且有内容，可选的 `## 需联动结论` 只能放在最后。

```markdown
---
contract: module_review
module_id: network-stack
status: implemented | partial | minimal | absent
originality: novel | adapted_major | adapted_minor | inherited | external | uncertain
base_delta: major | minor | none | unclear
---
# 网络栈

## 适用范围
## 实现内容
## 相对 Base 的变化
## 真实工作量判断
## 继承、外部依赖与缺失
## 文档声明复核
## 证据
```

写完后运行 `python scripts/review.py validate-fragment --case-dir "<绝对 case_dir>" --path "<绝对 output_path>"`。失败时修改并重跑；退出码为 0 后只返回 `SUCCESS: <绝对 output_path>`。
