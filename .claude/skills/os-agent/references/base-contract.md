# Base Contract

`base.md` 必须使用 `contract: base_decision`，并包含：

- `## 选中 Base`
- `## 证据覆盖`
- `## 未选候选`
- `## 方向判断`
- `## Base 之后需要描述的模块`

模块 agent 启动前，Base 必须是 `status: accepted`。同届高相似必须进入方向审查，不能只按相似度排序。

方向审查必须同时看：

- 作品各自声明的 Base 和文档来源。
- scope 中的 `framework_base`、`third_party`、`test_payload`，这些不能直接算核心抄袭。
- 核心代码的相似路径、函数、类型、syscall、配置和拆分/改名痕迹。
- 双方 commit 历史：谁先提交核心实现，谁后导入、批量替换、拆文件、函数改名或清理痕迹。
- 是否对框架或外部模块做了适配修改，是否存在大规模引入代码。
- 多来源时只选主骨架 Base，其他来源进入模块 finding 或风险说明。

`base.md` 不直接替模块写实现描述，但必须列出 Base accepted 后需要启动的模块 agent。
