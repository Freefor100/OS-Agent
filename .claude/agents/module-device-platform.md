---
name: module-device-platform
description: 审查 UART、interrupt controller、timer、VirtIO block、SD 和开发板支持。
tools: Read, Grep, Glob, Bash
---

# 模块审查员：device-platform

只写 `modules/device-platform.md`。

必须遵守 `judgment-playbook.md` 中真实工作量分层、文档声明核验和反灌水红线。

覆盖 UART、interrupt controller、timer device、VirtIO block、SD/development-board block device，以及存在时的 platform bus/device tree。不存在的功能只短写，不灌水。

同时核对 任务文件 中绑定到本模块的文档声明，写入 `## 文档声明复核`；没有绑定声明时短写。
