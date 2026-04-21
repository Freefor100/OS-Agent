## 技术栈差异

### 1. 编程语言差异

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **核心语言** | **C + Rust 混合** | **纯 C 语言** |
| **C 语言用途** | 内核主体（91 个 C 文件） | 全部内核代码（66 个 C/C++ 文件） |
| **Rust 用途** | SBI 固件 `sbi/psicasbi/`（22 个 Rust 文件） | ❌ 未使用 Rust |
| **汇编语言** | RISC-V 汇编（`.S` 文件，10+ 个） | RISC-V 汇编（`entry.S`, `swtch.S`, `trampoline.S` 等） |
| **标准库** | `-ffreestanding -nostdlib`（裸机环境） | `-ffreestanding -nostdlib`（裸机环境，自行实现 `printf`/`memset`） |
| **Rust Edition** | `edition = "2018"`（`sbi/psicasbi/Cargo.toml:4`） | N/A |

**证据引用**：
- oskernel2023-zmz Rust 配置：`repos/oskernel2023-zmz/sbi/psicasbi/Cargo.toml:4` → `edition = "2018"`
- oskernel2023-zmz C 编译标志：`repos/oskernel2023-zmz/Makefile:15-17` → `CFLAGS += -ffreestanding -fno-common -nostdlib`
- oskernrl2022-rv6 纯 C 架构：报告明确指出"无 Rust 特性"，"纯 C 语言实现"

---

### 2. 框架差异

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **基础框架** | **MIT xv6-riscv 移植版**（xv6-k210） | **类 xv6 独立实现**（单人主导开发） |
| **是否基于 ArceOS/rCore** | ❌ 否 | ❌ 否 |
| **框架来源** | MIT xv6-riscv 移植到 Kendryte K210 | 自研（21 天完成全栈实现） |
| **SBI 固件** | 自研 Rust SBI `psicasbi` | 依赖外部 SBI 固件（`sbi/fw_jump.elf`，OpenSBI/RustSBI） |
| **内核类型** | **宏内核**（Monolithic） | **宏内核**（Monolithic） |
| **运行模式** | RISC-V S-Mode（Supervisor Mode） | RISC-V S-Mode（Supervisor Mode） |

**证据引用**：
- oskernel2023-zmz 框架身份：报告明确指出"本项目 `xv6-k210` 是基于 MIT xv6-riscv 移植到 Kendryte K210 RISC-V SoC 的教学操作系统"
- oskernrl2022-rv6 框架身份：报告指出"非 ArceOS/rCore：本项目为独立实现的 C 语言内核"
- SBI 差异：oskernel2023-zmz 使用自研 Rust SBI（`sbi/psicasbi/`），oskernrl2022-rv6 依赖外部 `fw_jump.elf`

---

### 3. 目标架构差异

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **ISA 架构** | **RISC-V 64 位（rv64g）** | **RISC-V 64 位（riscv64gc）** |
| **指令集扩展** | `rv64g`（G=General） | `riscv64gc`（G+C=Compressed） |
| **支持平台** | **双平台**：K210 开发板 + QEMU 仿真 | **单平台**：SIFIVE_U / QEMU（通过 `MAC` 宏切换） |
| **链接脚本入口地址** | `0x80020000`（`linker/linker64.ld:4`） | `0x80200000`（`linker/kernel.ld:4`） |
| **跨架构支持** | ❌ 仅 RISC-V | ❌ 仅 RISC-V |

**证据引用**：
- oskernel2023-zmz 架构标志：`Makefile` 中 `-march=rv64g`
- oskernrl2022-rv6 架构：链接脚本 `OUTPUT_ARCH(riscv)`，报告指出"仅支持 RISC-V 64"
- 入口地址差异：
  - oskernel2023-zmz：`repos/oskernel2023-zmz/linker/linker64.ld:4` → `BASE_ADDRESS = 0x80020000`
  - oskernrl2022-rv6：`repos/oskernrl2022-rv6/linker/kernel.ld:4` → `BASE_ADDRESS = 0x80200000`

---

## 框架差异

### 4. 内核类型差异

两个项目均为**宏内核（Monolithic Kernel）**架构，核心子系统（进程管理、内存管理、文件系统、设备驱动）均编译为单一内核镜像。

| 特性 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **内核类型** | 宏内核 | 宏内核 |
| **运行特权级** | S-Mode（Supervisor Mode） | S-Mode（Supervisor Mode） |
| **多核支持** | 代码存在多核启动逻辑（SBI 固件支持） | ❌ 多核 SMP 支持未激活（报告明确指出"代码存在但逻辑未连通"） |
| **启动流程** | Rust SBI → C 内核 `main()` | 外部 SBI → 汇编 `_entry` → C `main()` |

**证据引用**：
- oskernel2023-zmz 多核：报告提及"使用 Rust 编写的 SBI 固件 `psicasbi` 作为 Boot ROM，负责多核启动"
- oskernrl2022-rv6 单核限制：报告明确指出"多核 SMP 支持未激活，系统实际运行于单核模式"

---

## 关键依赖对比

### 5. 第三方库依赖

#### oskernel2023-zmz（SBI 固件依赖）

**文件路径**：`repos/oskernel2023-zmz/sbi/psicasbi/Cargo.toml`

```toml
[dependencies]
lazy_static = { version = "1", features = ["spin_no_std"] }
spin = "0.9.0"
riscv = "0.6.0"
buddy_system_allocator = "0.8"
k210-pac = "0.2.0"    # K210 外设访问库（目标项目独有）
r0 = "1.0.0"
```

**外部工具链**：
- RISC-V GNU Toolchain（`riscv64-linux-gnu-`）
- QEMU System RISC-V
- kflash.py（K210 烧录工具）

#### oskernrl2022-rv6

**依赖情况**：
- ❌ **无第三方库依赖**（纯 C 实现，无 Cargo.toml）
- 集成 **FatFs**（FAT32）嵌入式文件系统库（代码集成在 `src/fat32.c`）
- 依赖外部 SBI 固件（`sbi/fw_jump.elf`）

**外部工具链**：
- RISC-V GNU Toolchain（`riscv64-linux-gnu-`）
- QEMU System RISC-V

**关键差异**：
| 依赖项 | oskernel2023-zmz | oskernrl2022-rv6 |
|--------|------------------|------------------|
| **Rust crate** | 6 个（`spin`, `riscv`, `buddy_system_allocator`, `k210-pac` 等） | 0 个 |
| **硬件抽象库** | `k210-pac`（K210 专用） | 无（直接操作寄存器） |
| **文件系统** | 自研 FAT32（`kernel/fs/fat32/`） | 集成 FatFs（`src/fat32.c`） |
| **SBI 固件** | 自研 Rust SBI | 外部预编译固件 |

---

### 6. 构建系统差异

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **构建工具** | GNU Make + Cargo（Rust） | GNU Make |
| **平台切换** | `platform := k210\|qemu`（Makefile 第 1-2 行） | `MAC?=SIFIVE_U\|QEMU`（Makefile 第 7 行） |
| **模式切换** | `mode := debug\|release` | 固定 Debug 模式（`-DDEBUG`） |
| **内核入口** | `_entry`（`linker/linker64.ld:2`） | `_entry`（`linker/kernel.ld:2`） |
| **构建流程** | 1. 编译 Rust SBI → 2. 编译 C 内核 → 3. 编译用户程序 → 4. 合并（K210 模式） | 1. 编译 C 内核 → 2. 编译用户程序 → 3. 链接外部 SBI |
| **Feature Flags** | Rust features: `k210`, `qemu`, `soft-extern`, `old-spec` | C 宏：`-D$(FS)`, `-D$(MAC)` |

**证据引用**：
- oskernel2023-zmz Makefile：`repos/oskernel2023-zmz/Makefile:1-2` → `platform := k210` / `mode := debug`
- oskernrl2022-rv6 Makefile：`repos/oskernrl2022-rv6/Makefile:7` → `MAC?=SIFIVE_U`
- oskernel2023-zmz Rust features：`repos/oskernel2023-zmz/sbi/psicasbi/Cargo.toml:17-20`

---

## 同源性评估

### 框架同源性分析

**结论**：两个项目**无直接同源性**，但均受 **xv6 设计哲学影响**。

| 评估维度 | 分析结果 |
|----------|----------|
| **是否基于同一框架** | ❌ 否。oskernel2023-zmz 基于 MIT xv6-riscv 移植；oskernrl2022-rv6 为独立实现 |
| **代码相似度** | 🔸 **设计思路相似**：均采用类 xv6 的进程结构体、页表管理、FAT32 文件系统设计，但**代码实现不同**（一个 C+Rust 混合，一个纯 C） |
| **定制化程度** | oskernel2023-zmz：在 xv6 基础上增加了 K210 硬件支持、Rust SBI 固件、COW Fork 机制<br>oskernrl2022-rv6：完全自研，21 天内完成全栈实现 |
| **独特实现** | **oskernel2023-zmz 创新点**：<br>1. Rust SBI 固件 `psicasbi`（候选项目无）<br>2. K210 专用驱动（`k210-pac` 依赖）<br>3. 双平台构建系统（K210/QEMU）<br><br>**oskernrl2022-rv6 特点**：<br>1. 纯 C 实现，无 Rust 依赖<br>2. 集成 FatFs 文件系统库<br>3. 信号处理机制（`signal.c`） |

### 核心差异总结

| 差异类型 | 具体表现 |
|----------|----------|
| **语言栈** | oskernel2023-zmz 采用 C+Rust 混合架构，oskernrl2022-rv6 为纯 C |
| **SBI 策略** | oskernel2023-zmz 自研 Rust SBI，oskernrl2022-rv6 依赖外部固件 |
| **硬件支持** | oskernel2023-zmz 支持 K210 真实硬件 + QEMU，oskernrl2022-rv6 主要面向 QEMU/SIFIVE_U |
| **多核能力** | oskernel2023-zmz SBI 支持多核启动，oskernrl2022-rv6 多核逻辑未激活 |
| **网络功能** | ❌ 两者均未实现网络栈 |

**最终判定**：两个项目为**独立开发**的 RISC-V 教学操作系统，共享类 xv6 的设计理念，但无代码层面的直接继承关系。oskernel2023-zmz 在 Rust+SBI 固件、K210 硬件适配方面具有独特创新；oskernrl2022-rv6 则体现了纯 C 实现的极简主义风格。