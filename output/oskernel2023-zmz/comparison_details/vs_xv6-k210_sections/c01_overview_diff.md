## 技术栈差异

### 1. 编程语言差异

| 维度 | oskernel2023-zmz | xv6-k210 |
|------|------------------|----------|
| **内核主体语言** | C 语言（91 个文件） | C 语言 |
| **Bootloader 语言** | Rust（22 个文件，`sbi/psicasbi/`） | Rust（`bootloader/SBI/rustsbi-k210/`） |
| **Rust Edition** | `edition = "2018"`（`sbi/psicasbi/Cargo.toml:4`） | `edition = "2018"`（`rustsbi-k210/Cargo.toml:5`） |
| **no_std 环境** | ✅ `#![no_std]` + `#![no_main]`（`sbi/psicasbi/src/main.rs:1-2`） | ✅ `#![no_std]` + `#![no_main]`（`rustsbi-k210/src/main.rs:2-3`） |
| **汇编语言** | RISC-V 汇编（`.S` 文件，如 `kernel/entry.S`） | RISC-V 汇编（`.S` 文件，如 `kernel/entry_k210.S`） |
| **C 编译器标志** | `-mcmodel=medany -ffreestanding -nostdlib -mno-relax`（`Makefile:25-27`） | `-march=rv64imafdc -mcmodel=medany -ffreestanding -nostdlib -mno-relax`（`Makefile:24-27`） |

**关键差异**：
- **xv6-k210** 显式指定 `-march=rv64imafdc`（支持整数/乘除/原子/浮点/压缩指令集）
- **oskernel2023-zmz** 未在 Makefile 中显式指定 `-march` 标志，依赖工具链默认配置

---

## 框架差异

### 2. 框架归属分析

| 项目 | 是否基于框架 | 框架名称 | 框架版本 | 自研程度 |
|------|-------------|---------|---------|---------|
| **oskernel2023-zmz** | ❌ 否 | 无 | N/A | **完全自研**（基于 MIT xv6-riscv 移植） |
| **xv6-k210** | ❌ 否 | 无 | N/A | **完全自研**（基于 MIT xv6-riscv 移植） |

**证据**：
- `grep` 搜索 `rCore|ArceOS|rcore|arceos` 在 **oskernel2023-zmz** 中**未找到任何匹配**（已搜索 193 个文件）
- 两个项目均采用 **C 语言宏内核** 架构，非 Rust 内核框架（如 rCore/ArceOS）
- 两个项目的 Bootloader 均使用 **RustSBI** 变种：
  - oskernel2023-zmz: 自研 `psicasbi`（`sbi/psicasbi/`）
  - xv6-k210: 基于官方 RustSBI 修改（`bootloader/SBI/rustsbi-k210/`，引用 `https://github.com/luojia65/rustsbi`）

**结论**：两个项目**均不基于同一框架**，都是基于 MIT xv6-riscv 的独立移植项目，但 Bootloader 实现不同。

---

## 关键依赖对比

### 3. Bootloader 依赖对比

#### oskernel2023-zmz (`sbi/psicasbi/Cargo.toml`)
```toml
[dependencies]
lazy_static = { version = "1", features = ["spin_no_std"] }
spin = "0.9.0"
riscv = "0.6.0"
buddy_system_allocator = "0.8"      # 堆内存分配器
k210-pac = "0.2.0"                  # K210 外设访问库
r0 = "1.0.0"                        # BSS 清零
```

#### xv6-k210 (`bootloader/SBI/rustsbi-k210/Cargo.toml`)
```toml
[dependencies]
rustsbi = "0.1.1"                   # ✅ 使用官方 RustSBI 框架
riscv = { git = "https://github.com/rust-embedded/riscv", features = ["inline-asm"] }
linked_list_allocator = "0.8"       # 与 oskernel2023-zmz 不同
k210-hal = { git = "https://github.com/riscv-rust/k210-hal" }  # ✅ 使用 k210-hal
embedded-hal = "1.0.0-alpha.1"
lazy_static = {version = "1.1.0", features = ["spin_no_std"]}
spin = "0.7.1"                      # 版本低于 oskernel2023-zmz
r0 = "1.0"
```

**关键差异**：
| 依赖项 | oskernel2023-zmz | xv6-k210 | 差异说明 |
|--------|------------------|----------|---------|
| **SBI 框架** | ❌ 自研 `psicasbi` | ✅ `rustsbi = "0.1.1"` | xv6-k210 复用官方 RustSBI |
| **内存分配器** | `buddy_system_allocator = "0.8"` | `linked_list_allocator = "0.8"` | 算法不同（伙伴系统 vs 链表） |
| **K210 HAL** | `k210-pac = "0.2.0"`（外设访问） | `k210-hal`（完整 HAL） | xv6-k210 使用更高级抽象 |
| **spin 锁** | `spin = "0.9.0"` | `spin = "0.7.1"` | oskernel2023-zmz 版本更新 |

### 4. 内核依赖对比

| 项目 | 外部依赖 | 说明 |
|------|---------|------|
| **oskernel2023-zmz** | ❌ 无 | 纯 C 实现，无外部库 |
| **xv6-k210** | ❌ 无 | 纯 C 实现，无外部库 |

**共同点**：两个项目的内核主体均**无第三方依赖**，所有子系统（进程管理、内存管理、文件系统、设备驱动）均为自包含实现。

---

## 同源性评估

### 5. 同源性判断

**结论**：两个项目**非同源**，但**设计思路高度相似**。

**证据链**：

1. **框架独立性**：
   - 两个项目均**不基于 rCore/ArceOS** 等现代 Rust 内核框架
   - 两个项目均采用 **C 语言宏内核 + Rust Bootloader** 的混合架构
   - Bootloader 实现不同：oskernel2023-zmz 使用自研 `psicasbi`，xv6-k210 使用官方 `RustSBI`

2. **代码结构相似性**（源自 MIT xv6-riscv）：
   - 目录结构高度一致：`kernel/mm/`、`kernel/sched/`、`kernel/fs/`、`kernel/trap/`
   - 核心文件名相同：`vm.c`、`proc.c`、`trap.c`、`syscall.c`
   - 系统调用接口相似：`SYS_fork`、`SYS_exec`、`SYS_mmap` 等

3. **关键差异点**：
   | 维度 | oskernel2023-zmz | xv6-k210 |
   |------|------------------|----------|
   | **Bootloader** | 自研 `psicasbi`（v0.4.0） | 基于 `RustSBI`（v0.1.1） |
   | **内存分配器（SBI）** | 伙伴系统（`buddy_system_allocator`） | 链表分配（`linked_list_allocator`） |
   | **K210 HAL** | 直接使用 PAC（`k210-pac`） | 使用高级 HAL（`k210-hal`） |
   | **编译标志** | 未显式指定 `-march` | 显式指定 `-march=rv64imafdc` |
   | **工具链前缀** | `riscv64-linux-gnu-`（`Makefile:12`） | `riscv64-unknown-elf-`（`Makefile:12`） |

4. **定制化程度评估**：
   - **oskernel2023-zmz**：Bootloader 完全自研，未复用 RustSBI 框架，定制化程度**更高**
   - **xv6-k210**：Bootloader 基于官方 RustSBI 修改，复用成熟框架，定制化程度**较低**

**最终判定**：
- 两个项目均源自 **MIT xv6-riscv** 教学操作系统
- 但**Bootloader 实现独立**，无代码复用关系
- **内核主体代码**可能存在部分同源（均基于 xv6-riscv），但需进一步通过 `compare_function_tokens` 验证具体函数的代码相似度
- 两个项目属于**同一设计思路下的独立实现**，而非同一框架的不同分支

---

## 总结

| 维度 | 差异程度 | 关键发现 |
|------|---------|---------|
| **编程语言** | 🔸 小 | 均为 C+Rust 混合，Rust Edition 相同（2018） |
| **框架归属** | ✅ 大 | 均不基于 rCore/ArceOS，Bootloader 实现不同 |
| **目标架构** | 🔸 小 | 均支持 RISC-V 64 位（K210+QEMU 双平台） |
| **内核类型** | ❌ 无 | 均为宏内核 |
| **关键依赖** | ✅ 大 | SBI 框架、内存分配器、K210 HAL 均不同 |
| **构建系统** | 🔸 中 | 工具链前缀、编译标志有差异 |

**创新点标注**：
- 【oskernel2023-zmz】自研 `psicasbi` Bootloader，采用伙伴系统内存分配器（`buddy_system_allocator`），未复用官方 RustSBI
- 【xv6-k210】复用官方 `RustSBI` 框架，采用 `k210-hal` 高级硬件抽象层