# Module Contract

每个模块输出都使用 `contract: module_review`，并包含：

- `## 适用范围`
- `## 实现内容`
- `## 相对 Base 的变化`
- `## 真实工作量判断`
- `## 继承、外部依赖与缺失`
- `## 文档声明复核`
- `## 证据`

这些 H2 必须按顺序出现，不允许改名、合并或调换顺序。

非 absent 模块至少需要三个具体锚点：路径、函数、类型、syscall、配置或测试名。每个强结论都必须引用 evidence。

如果 Base 选择结论是无可靠 Base，则 `base_delta: unclear`，`## 相对 Base 的变化` 只说明“未选出可靠 Base，本文不做相对 Base 差异判断”，后续重点放在实现内容和真实工作量。

模块 agent 负责核对 任务文件 中绑定到本模块的文档声明。没有绑定声明时短写，不扩展上下文。发现声明夸大、不实或缺证时，在本节引用文档 evidence 和代码/负向搜索 evidence，供 `doc-claim-reviewer` 汇总。

不存在或未观察到的模块：

- 使用 `status: absent` 或 `minimal`，不要为了填充报告而扩写。
- `## 实现内容` 写未观察到的范围和负向搜索 evidence。
- `## 相对 Base 的变化` 写 `base_delta: none` 或 `unclear` 的原因。
- `## 真实工作量判断` 只能写“不计入该模块真实工作量”或“待补证”，不能写成完整实现。
- 不需要三个代码锚点，但必须引用支撑 absent/minimal 的 evidence。
