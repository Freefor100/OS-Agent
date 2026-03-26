## 技术栈差异

### 1. 编程语言差异

| 维度 | oskernel2023-avx (目标) | oskernrl2022-rv6 (候选) |
|------|------------------------|------------------------|
| **核心语言** | C (C99 标准) | C (C99/C11 标准) |
| **汇编语言** | RISC-V Assembly | RISC-V Assembly |
| **Rust 使用** | ❌ 未使用 (搜索 `Cargo.toml`/`.rs` 无结果) | ❌ 未使用 (搜索 `Cargo.toml`/`.rs` 无结果) |
| **no_std 环境** | ✅ 裸机内核 (`-ffreestanding -nostdlib`) | ✅ 裸机内核 (`-ffreestanding -nostdlib`) |
| **标准库依赖** | 无 (自行实现 `printf`, `memset`, `memcpy`) | 无 (自行实现 `printf`, `memset`, `memcpy`) |
| **编译选项** | `-Wall -O -fno-omit-frame-pointer -ggdb -g -mcmodel=medany` (`Makefile:129-135`) | 类似配置，使用 `riscv64-linux-gnu-gcc` |

**结论**：两个项目均采用**纯 C 语言 + RISC-V 汇编**的技术栈，无 Rust 参与，均为裸机内核环境。语言层面**高度一致**。

---

## 框架差异

### 2. 基础框架与来源

| 维度 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **框架来源** | 基于 **xv6-riscv** 教学操作系统扩展 | 基于 **xv6-riscv** 教学操作系统扩展 |
| **是否 ArceOS/rCore** | ❌ 非 ArceOS/rCore 体系 | ❌ 非 ArceOS/rCore 体系 |
| **底层固件** | SBI (Supervisor Binary Interface) | SBI (Supervisor Binary Interface) |
| **运行模式** | S-Mode (Supervisor Mode) | S-Mode (Supervisor Mode) |
| **版权声明** | `Copyright (c) 2006-2019 Frans Kaashoek, Robert Morris, Russ Cox, MIT` (`kernel/main.c:1`) | `Copyright (c) 2006-2019 Frans Kaashoek, Robert Morris, Russ Cox, MIT` (`src/main.c:1`) |

**证据**：
- 目标项目 `kernel/main.c:1-2` 和候选项目 `src/main.c:1-2` 均保留相同的 MIT 版权声明，表明两者均源自 xv6-riscv。
- 两者均使用 SBI 接口进行底层硬件抽象：
  - 目标：`kernel/include/sbi.h` 定义 `SBI_CALL` 宏和 `sbi_hart_start()` 函数
  - 候选：`src/include/sbi.h` 定义 `sbi_call()` 和 `a_sbi_ecall()` 函数

### 3. 目标架构差异

| 架构支持 | oskernel2023-avx | oskernrl2022-rv6 |
|---------|------------------|------------------|
| **RISC-V 64 (riscv64gc)** | ✅ 主要支持架构 | ✅ 唯一支持架构 |
| **x86_64** | ❌ 未发现 | ❌ 未发现 |
| **AArch64** | ❌ 未发现 | ❌ 未发现 |
| **LoongArch** | ❌ 未发现 | ❌ 未发现 |

**目标架构 Triple**：
- 目标：`riscv64gc-unknown-none-elf` (RISC-V 64 with General Purpose + Compressed + Atomic extensions)
- 候选：`riscv64gc-unknown-none-elf`

**平台支持差异**：

| 平台 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **QEMU** | ✅ `kernel/entry_qemu.S` + `linker/qemu.ld` | ✅ 支持 (`MAC?=QEMU` 配置) |
| **VisionFive 开发板** | ✅ `kernel/entry_visionfive.S` + `linker/visionfive.ld` | ❌ 未发现专用入口 |
| **SIFIVE_U** | ❌ 未发现 | ✅ `MAC?=SIFIVE_U` 配置 |

**证据**：
- 目标项目 `Makefile:1-2` 支持 `platform := visionfive` 或 `platform := qemu` 切换
- 候选项目 `Makefile:9-16` 通过 `MAC?=SIFIVE_U` 或 `MAC?=QEMU` 切换

---

## 关键依赖对比

### 4. 内核类型与架构设计

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **内核类型** | **宏内核 (Monolithic)** | **宏内核 (Monolithic)** |
| **构建产物** | 单一内核镜像 `target/kernel` | 单一内核镜像 (通过 `linker/kernel.ld` 链接) |
| **子系统耦合** | 所有子系统编译为单一镜像 | 所有子系统编译为单一镜像 |

### 5. 核心功能模块对比

#### 5.1 网络栈

| 项目 | 实现状态 | 证据 |
|------|---------|------|
| **oskernel2023-avx** | ✅ **已实现** (lwIP 协议栈) | `kernel/lwip/` 目录约 2 万行代码；`kernel/main.c:71` 调用 `tcpip_init_with_loopback()`；`kernel/socket_new.c` 包含 `#include "lwip/sockets.h"` 等 11177 处匹配 |
| **oskernrl2022-rv6** | ❌ **未实现** (仅头文件桩代码) | `src/include/socket.h` 仅定义 `struct socket_connection` 和函数声明；搜索 `socket_init\|sys_socket\|do_lwip` **无实现代码** |

**关键差异**：
- 目标项目集成完整 lwIP 协议栈（`kernel/lwip/core/`, `kernel/lwip/api/`, `kernel/lwip/netif/`）
- 候选项目仅有 Socket 头文件定义 (`src/include/socket.h:1-15`)，**无任何实现代码**，属于**桩代码状态**

#### 5.2 进程与线程管理

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **进程结构体** | `struct proc` 包含 `thread *main_thread` 和 `thread *thread_queue` (`kernel/include/proc.h:73-74`) | `struct proc` **无 thread 相关字段** (`src/include/proc.h:128-180`) |
| **线程结构体** | ✅ `struct thread` 定义于 `kernel/include/thread.h:21-45` | ❌ **未发现** `struct thread` 定义 (搜索无结果) |
| **线程创建** | ✅ `sys_clone()` 检测 `CLONE_VM` 调用 `thread_clone()` (`kernel/sysproc.c:20-48`) | 🔸 `sys_clone()` 仅调用 `clone()` (`src/sysproc.c:109-122`)，**无线程池管理** |
| **调度器** | 遍历 `thread_queue` 查找可运行线程 (`kernel/proc.c:669-753`) | 直接从 `readyq` 获取进程 (`src/proc.c:119-155`) |
| **调度算法** | 简单轮询 (Round-Robin)，**非 CFS** | 简单轮询 (Round-Robin)，**非 CFS** |

**证据**：
- 目标项目 `kernel/include/thread.h:21-45` 完整定义 `struct thread`，包含 `state`, `p`, `tid`, `trapframe`, `context`, `next_thread`, `pre_thread` 等字段
- 候选项目搜索 `struct thread` **无结果**，表明**未实现独立的线程结构体**
- 目标项目 `kernel/proc.c:703-722` 实现线程枚举和队列管理逻辑
- 候选项目 `src/proc.c:119-155` 的 `scheduler()` 直接从 `readyq_pop()` 获取进程，**无线程概念**

#### 5.3 文件系统

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **FAT32** | ✅ `kernel/fat32.c` (1184 行) | ✅ `src/fat32.c` (完整实现) |
| **ext4** | ❌ 未发现 | ❌ 未发现 |
| **ramfs** | ❌ 未发现 | ❌ 未发现 |

#### 5.4 多核 SMP 支持

| 特性 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **多核配置** | ✅ `Makefile:153` 配置 `CPUS := 2` | ✅ 代码存在但**未激活** |
| **从核启动** | ✅ `kernel/main.c:75` 调用 `sbi_hart_start(2, ...)` | ✅ `src/main.c:82-85` 调用 `start_hart()` |
| **实际运行模式** | ✅ 双核运行 (主核 hart 1, 从核 hart 2) | 🔸 文档声明"多核 SMP 支持未激活"，实际运行于单核模式 |

**证据**：
- 目标项目 `kernel/main.c:75` 明确调用 `sbi_hart_start(2, (unsigned long)_start, 0)` 启动从核
- 候选项目 `doc/内核实现--多核启动.md:51` 声明"sbi 接口使用错误，使用了另外一种唤醒方式得以解决"，但报告指出"**多核 SMP 支持未激活**"

---

## 构建系统差异

### 6. 构建配置对比

| 维度 | oskernel2023-avx | oskernrl2022-rv6 |
|------|------------------|------------------|
| **构建工具** | GNU Make (`Makefile` 353 行) | GNU Make (`Makefile` 185 行) |
| **交叉编译工具链** | `riscv64-unknown-elf-gcc` 或 `riscv64-linux-gnu-gcc` | `riscv64-linux-gnu-gcc` |
| **链接脚本** | `linker/qemu.ld` / `linker/visionfive.ld` (双平台) | `linker/kernel.ld` (单一脚本) |
| **平台切换** | `platform := visionfive` 或 `platform := qemu` (`Makefile:1-2`) | `MAC?=SIFIVE_U` 或 `MAC?=QEMU` (`Makefile:9-16`) |
| **用户程序** | `xv6-user/` 目录，通过 `usys.pl` 生成系统调用桩 | `usrinit/` 目录 |
| **SBI 固件** | 外部依赖 (未包含在仓库) | `sbi/fw_jump.elf` (约 1MB，包含在仓库) |

**关键编译选项** (目标项目 `Makefile:129-135`)：
```makefile
CFLAGS = -Wall -O -fno-omit-frame-pointer -ggdb -g
CFLAGS += -mcmodel=medany
CFLAGS += -ffreestanding -fno-common -nostdlib -mno-relax
CFLAGS += -fno-stack-protector
```

---

## 同源性评估

### 7. 框架同源性分析

**结论**：两个项目**高度同源**，均基于 **xv6-riscv** 教学操作系统进行扩展开发。

**证据**：
1. **版权声明一致**：两者 `main.c` 文件头部均保留相同的 MIT 版权声明 (`Copyright (c) 2006-2019 Frans Kaashoek, Robert Morris, Russ Cox, MIT`)
2. **核心数据结构相似**：`struct proc` 的基础字段（`state`, `parent`, `pid`, `pagetable`, `trapframe`, `context` 等）高度一致
3. **SBI 接口设计相似**：两者均使用 `ecall` 指令进行 SBI 调用，仅宏定义细节略有差异
4. **调度器框架相同**：均采用 `scheduler()` 无限循环 + `swtch()` 上下文切换的经典 xv6 模式

### 8. 定制化程度对比

| 定制维度 | oskernel2023-avx | oskernrl2022-rv6 |
|---------|------------------|------------------|
| **线程系统** | 【创新点】✅ 完整实现内核级线程池 (`struct thread`, `thread_queue`, `thread_clone()`) | ❌ 未实现独立线程结构，仅支持进程级 `clone()` |
| **网络栈** | 【创新点】✅ 集成完整 lwIP 协议栈 (约 2 万行代码) | ❌ 仅 Socket 头文件桩代码 |
| **VMA 管理** | ✅ `kernel/vma.c` (335 行) 实现 VMA 双向链表 | ✅ 有 VMA 实现 (`src/vma.c`) |
| **mmap 支持** | ✅ `kernel/mmap.c` (118 行) | ✅ 有 mmap 实现 |
| **Futex** | ✅ `kernel/futex.c` (70 行) | ✅ 有 Futex 定义但实现不完整 |
| **信号量** | ✅ `kernel/sem.c` (75 行) | ❌ 未发现独立信号量实现 |
| **双平台支持** | ✅ QEMU + VisionFive 专用入口和链接脚本 | 🔸 QEMU + SIFIVE_U 配置，但 VisionFive 支持不完整 |

### 9. 核心差异总结

| 差异等级 | 特性 | 目标项目 | 候选项目 |
|---------|------|---------|---------|
| **🔴 重大差异** | 网络栈 | ✅ lwIP 完整实现 | ❌ 仅桩代码 |
| **🔴 重大差异** | 线程系统 | ✅ 独立 `struct thread` + 线程池 | ❌ 无线程概念 |
| **🟡 中等差异** | 多核 SMP | ✅ 双核实际运行 | 🔸 代码存在但未激活 |
| **🟡 中等差异** | 平台支持 | ✅ VisionFive 完整支持 | 🔸 SIFIVE_U 支持 |
| **🟢 轻微差异** | 调度算法 | 简单轮询 | 简单轮询 |
| **🟢 轻微差异** | 文件系统 | FAT32 | FAT32 |

---

## 最终评估

### 同源性判定
两个项目**基于同一框架 (xv6-riscv)**，核心架构和数据结构高度相似，属于**同源项目的不同分支**。

### 定制化程度
- **oskernel2023-avx**：在 xv6 基础上进行了**深度扩展**，增加了内核级线程系统、完整 lwIP 网络栈、双平台支持等特性，定制化程度**高**。
- **oskernrl2022-rv6**：保持 xv6 原始架构，主要完成基础功能（进程、内存、文件系统）的实现，网络和多核功能未完整激活，定制化程度**中等**。

### 【创新点】标注
目标项目 `oskernel2023-avx` 相比候选项目的独特实现：
1. **【创新点】内核级线程系统**：独立 `struct thread` 结构体、线程池管理、`thread_queue` 调度
2. **【创新点】lwIP 网络协议栈集成**：完整 TCP/IP 实现，支持 Socket 系统调用
3. **【创新点】VisionFive 开发板原生支持**：专用入口文件 `entry_visionfive.S` 和链接脚本