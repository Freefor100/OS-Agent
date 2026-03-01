# 更新日志 (Changelog)

## [2.7.0] - 2026-03-01

### ✨ 新增功能

#### 评估模块自动克隆

- `os_agent_d_evaluate.py` 新增自动克隆逻辑：检测到 `repos/<repo_name>` 不存在或为空时，自动从 `REPO_URL` 克隆 OS 仓库
- 无需先运行 describe 即可直接评估已有报告

#### output/ 和 evaluation/ 纳入 Git 跟踪

- `.gitignore` 不再忽略 `output/` 和 `evaluation/` 目录
- 他人 clone 仓库后可直接查看分析报告和评估结果
- `repos/` 保持忽略（运行时自动克隆，不占仓库体积）
- 添加 `.gitkeep` 确保空目录也被跟踪

### 🐛 Bug 修复

- 修正评估模块错误提示中的脚本名称（`os_agent_d.py` → `os_agent_d_describe.py`）

---

## [2.5.0] - 2026-02-21

### ✨ 新增功能

#### 评估驱动的 Stage Prompt 精修

基于 13 章评估结果归纳的 6 类共性问题，针对性修改了 6 个 stage prompt：

- **内存管理** (`02_mem_mgmt`)：新增 brk/sbrk 惰性机制、用户指针安全验证、进程级映射管理（VmAreaStruct/rmap）
- **中断与系统调用** (`04_trap_syscall`)：要求精确统计 TrapFrame 字节数，新增接口/实现分离模式（`_impl` 后缀）、UserInPtr 语义化包装
- **文件系统** (`05_fs_vfs`)：新增具体 FS 抽象层結构分析（FatFilesystemInner 等）、文件打开完整调用链、路径精确性约束
- **同步 IPC** (`07_sync_ipc`)：新增信号作为 IPC 机制、Futex 跨文件调用链追踪
- **安全机制** (`09_security`)：强制多架构覆盖要求
- **测试框架** (`12_test_ci`)：要求精确计数测试用例，与 grep 结果一致

#### 评估程序术语规范

- 评估 prompt 新增"术语约定"段落，明确区分【人类文档】与【生成报告】
- `accuracy.errors.desc` 中必须标明问题归属

#### 新增 `lsp_get_document_outline` 工具

- 基于 `textDocument/documentSymbol` 协议，快速提取文件中所有函数、结构体、枚举的名称与行号
- 已注册到 `build_agent` 的 `base_tools` 和评估程序的 `EVAL_TOOLS`
- 描述和评估的 format 函数已支持该工具的输出格式化

### 🔧 环境配置

#### Language Server 安装

- 安装 clangd v21.1.8（通过 LLVM winget）
- 安装 rust-analyzer v0.3.2795-standalone（直接下载，修复了与 rustup shim 的 PATH 冲突）
- 安装 gopls v0.21.1（通过 `go install`）
- README 新增 Language Server 安装指南

### 🐛 Bug 修复

- 修复 `lsp_ops.py` 中 `builtins.open` 未导入的引用错误（改为直接使用内置 `open`）

### 📝 文档更新

- README 新增 v2.5 版本说明
- README 快速开始新增"安装 Language Servers"步骤（含安装命令与验证方法）
- README 工具限制表新增 `lsp_get_document_outline`
- CHANGELOG 新增 v2.5.0 条目

---

## [2.4.0] - 2026-02-20

### ✨ 新增功能

#### 语言服务器原生整合 (LSP Integration)

**原生 AST 智能解析体系**
- **LSP 多路复用**：引入 `clangd` / `rust-analyzer` / `gopls` 等原生语言服务器，彻底告别正则文本扫描带来的信息残缺（幻觉断层）。
- **自动 Polyfill**：当环境缺乏 `compile_commands.json` 或 `Cargo.toml` 时，支持基于编译头文件特征的动态挂载，自动补全底层 AST 依赖库环境。
- **汇编自动降级**：对 `.s`, `.asm` 的汇编代码以及发生超时的 LSP 查询默认实施正则解析（ASMLexicalParser）降级保护机制。

**全链路替换分析网关**
- 全面下线 `analyze_code_architecture` 工具，重构了 `describe_ops` 和 `evaluate` 模块底层的调用分析提示词。
- 强制大模型在验证高级特性（如 CoW、零拷贝）以及调用链时，使用 `lsp_get_definition` 和 `lsp_get_references` 获取精准结构实体，防止产生捏造的调用链逻辑。

---

## [2.3.0] - 2026-02-20

### ✨ 新增功能

#### 描述模块增强 (os_agent_d_describe.py v2.3)

**严格审查与反幻觉机制**
- 强化多阶段 prompt，强制进行未实现接口的检测（`unimplemented!()`、`todo!()`、`ENOSYS` 等桩代码）。
- 在引用文件路径前强制验证该路径在仓库中的真实性。
- 新增针对 FPU 初始化、CPU 模式切换环节真实性验证要求（避免由于配置文件存在而被误认为已实现）。

**深度实现追踪机制**
- 要求通过追踪 `sys_mmap`、IPC 等特性的核心代码逻辑（例如验证是否有队列结构、环形缓冲、共享标识处理）判断功能的真实性。

**执行流程优化**
- 优化了项目概览阶段（`00_repo_prep`），在本地目标仓库已存在的场景下直接跳过克隆与代码摘要处理，从而大幅度降低消耗与等待时间。

---

## [2.0.0] - 2025-02-14

### ✨ 新增功能

#### 评估程序增强版 (os_agent_d_evaluate.py v2.0)

**智能重试机制**
- 实现指数退避策略（2s → 4s → 8s，最大 60s）
- 自动错误分类（网络、API、超时、解析、验证、工具、未知 7 种类型）
- 针对性重试策略：可重试的错误类型自动重试，不可重试的跳过
- 最大重试次数可配置（默认 3 次）

**完整错误追溯**
- 新增 `ErrorTracker` 类，统一管理错误记录
- 生成 `error_report.json` 包含：
  - 错误详情（时间戳、类型、异常、堆栈）
  - 错误分类统计
  - 失败时的完整上下文（步骤数、模型、参数等）
- 日志级别提升至 DEBUG，记录完整堆栈跟踪
- Markdown 报告集成错误摘要

**鲁棒性提升**
- 输入验证：章节文件、仓库目录存在性检查
- 超时控制：可配置请求超时（默认 300 秒）
- 优雅降级：单章节失败不影响整体评估流程
- 追问机制：JSON 解析失败时自动追问 Agent 重新生成
- 资源清理：异常时自动保存中间结果
- 用户中断（Ctrl+C）优雅退出

**统计增强**
- 成功/失败/跳过章节统计
- 成功率计算和显示
- 错误类型分布统计
- 评估耗时记录

### 🔧 改进

**日志系统**
- 日志同时输出到文件和控制台（可配置）
- 格式优化，包含日志级别、模块名、时间戳
- 关键操作点详细记录

**错误处理**
- 将简单的 `try-except` 升级为智能重试循环
- 添加错误上下文保存
- 区分用户中断和系统异常

**输出文件**
- `summary.json` 新增 `evaluation_stats` 字段（总数、成功、失败、跳过、成功率）
- `evaluation_report.md` 末尾自动添加错误统计章节
- 新增 `error_report.json` 记录所有错误详情

### 📝 文档更新

- 更新 `README.md`：
  - 添加评估程序增强功能说明
  - 新增故障排查章节
  - 更新示例输出
  - 添加配置说明
- 更新 `.env.example`：
  - 添加评估增强配置选项
  - 添加重试参数说明
  - 添加日志级别配置
- 更新 `requirements.txt`：
  - 添加版本说明和注释
  - 明确标注评估增强功能依赖

### 🐛 Bug 修复

- 修复评估失败时程序崩溃的问题（现在会优雅降级）
- 修复 JSON 解析失败导致的数据丢失（新增追问机制）
- 修复重试时 token 浪费的问题（虽然仍从头开始，但有退避机制）

### ⚡ 性能优化

- 优化重试策略，避免无效重试（解析错误不重试）
- 添加超时控制，避免长时间等待

---

## [1.0.0] - 2025-02-13

### ✨ 初始版本

- OS 仓库自动分析功能 (os_agent_d_describe.py)
- 16 阶段技术分析
- Git 历史分析和图表生成
- 基础评估功能 (os_agent_d_evaluate.py)
- 5 维度评分体系
- Markdown 报告生成

---

## 版本规范

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范：

- **MAJOR**（主版本号）：不兼容的 API 修改
- **MINOR**（次版本号）：向下兼容的功能性新增
- **PATCH**（修订号）：向下兼容的问题修正

---

*最后更新: 2026-03-01*
