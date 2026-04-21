## 多核差异

### 1. 多核架构差异

**oskernel2023-zmz**: ✅ **基础 SMP 架构（双核）**
- 定义 `NCPU=2` (`include/param.h:5`)
- 实现 `struct cpu cpus[NCPU]` Per-CPU 数组 (`kernel/sched/proc.c:92`)
- 通过 `tp` 寄存器读取 hartid (`include/sched/proc.h:165-168`)
- **证据文件**: `kernel/main.c:42-105`, `include/sched/proc.h:158-165`

**xv6-k210**: 🔸 **SMP 框架存在但有缺陷**
- 同样定义 `NCPU=2` (`include/param.h:5`)
- 同样实现 `struct cpu cpus[NCPU]` (`kernel/sched/proc.c:94`)
- **关键缺陷**: IPI 发送代码有 bug — `res` 变量未定义但被引用 (`kernel/main.c:68-70`)
- **证据文件**: `kernel/main.c:66-73` (注释掉的代码导致编译错误)

**差异结论**: 两个项目代码高度相似（几乎相同），但 xv6-k210 存在明显的代码错误（`res` 未定义），导致多核启动可能失败。

---

### 2. Secondary CPU 启动差异

**oskernel2023-zmz**: ✅ **已实现（通过 IPI + 自旋等待）**
- BSP (hart 0) 初始化共享资源后发送 IPI
- AP (hart 1) 通过 `while (started == 0);` 自旋等待
- 收到 IPI 后初始化本核资源（页表、中断向量）
- **证据代码** (`kernel/main.c:76-95`):
```c
// BSP 发送 IPI
for (int i = 1; i < NCPU; i ++) {
    unsigned long mask = 1 << i;
    struct sbiret res = sbi_send_ipi(mask, 0);  // ✅ 正确定义 res
    __debug_assert("main", SBI_SUCCESS == res.error, "sbi_send_ipi failed");
}
__sync_synchronize();
started = 1;

// AP 自旋等待
else {
    while (started == 0)
        ;
    __sync_synchronize();
    floatinithart();
    kvminithart();
    trapinithart();
    plicinithart();
}
```

**xv6-k210**: 🔸 **桩函数/有缺陷实现**
- 代码结构与 oskernel2023-zmz 几乎相同
- **关键 bug**: `res` 变量未定义
- **证据代码** (`kernel/main.c:66-73`):
```c
for (int i = 1; i < NCPU; i ++) {
    unsigned long mask = 1 << i;
    // struct sbiret res = sbi_send_ipi(mask, 0);  // ❌ 被注释！
    sbi_send_ipi(mask, 0);
    __debug_assert("main", SBI_SUCCESS == res.error, "sbi_send_ipi failed");  // ❌ res 未定义
}
```
- Hart 1 缺少 `plicinithart()` 调用（被注释掉）

**差异结论**: oskernel2023-zmz 的 Secondary CPU 启动代码完整可运行；xv6-k210 存在编译错误和初始化不完整问题。

---

### 3. 核间中断 IPI 差异

**oskernel2023-zmz**: ✅ **已实现（SBI 接口 + 底层硬件适配）**
- SBI IPI 扩展接口 (`include/sbi.h:96-103`)
- 底层通过 CLINT 实现 (`sbi/psicasbi/src/hal/clint/mod.rs`)
- 支持 QEMU 和 K210 双平台
- **运行时 IPI 使用**: `wakeup()` 函数中向其他 CPU 发送 IPI (`kernel/sched/proc.c:397-403`)
- **证据代码**:
```c
// kernel/sched/proc.c:397-403
void wakeup(void *chan) {
    int id = 0 == cpuid() ? 1 : 0;
    int avail = NULL == cpus[id].proc;
    if (flag && avail) {
        sbi_send_ipi(1 << id, 0);  // 通知空闲 CPU
    }
}
```

**xv6-k210**: 🔸 **接口存在但使用受限**
- 同样实现 SBI IPI 接口
- **关键限制**: IPI 处理仅清除 pending 位，无实际业务逻辑
- **证据** (`kernel/trap/trap.c:246-250`):
```c
else if (INTR_SOFTWARE == scause) {
    sbi_clear_ipi();
    return 0;  // ❌ 无实际处理逻辑
}
```
- 注释明确说明："on k210 software interrupts may be used for IPI, but as it is not yet supported, handle this as an unsupported one"

**差异结论**: oskernel2023-zmz 在 `wakeup()` 中实际使用 IPI 进行核间通信；xv6-k210 的 IPI 处理仅为桩函数。

---

### 4. Per-CPU 变量设计差异

**oskernel2023-zmz**: ✅ **完整实现**
- `struct cpu` 包含：`proc`、`context`、`noff`、`intena` (`include/sched/proc.h:158-165`)
- `mycpu()` 通过 `tp` 寄存器访问 (`kernel/sched/proc.c:96-99`)
- `push_off()`/`pop_off()` 实现中断嵌套保护 (`kernel/intr.c:12-40`)
- **证据**: 代码完整，无缺失

**xv6-k210**: ✅ **同样实现（代码几乎相同）**
- 结构体定义和访问方式与 oskernel2023-zmz 完全一致
- **未发现差异**

**差异结论**: 两个项目在 Per-CPU 变量设计上**代码相同**，无显著差异。

---

### 5. Call Graph 对比：`main` 函数

**对比结果**:
- **oskernel2023-zmz**: 55 个出向调用（完整初始化链）
  - 关键调用：`sbi_send_ipi`、`scheduler`、`userinit`、`plicinithart`
- **xv6-k210**: 降级分析（Tree-sitter 静态提取），仅找到 7 个调用
  - **原因**: LSP 不可用，降级到静态分析
  - 提取的调用均为 Rust bootloader 代码，非内核 `main()`

**Jaccard 相似度**: 0.000（无共同节点，因 xv6-k210 分析降级）

**降级分析说明**: xv6-k210 的 `main` 函数 Call Graph 获取失败（LSP 不可用），但通过代码阅读确认两个项目的 `main()` 函数体**几乎完全相同**，差异仅在于：
1. oskernel2023-zmz 有 `delay(100000000)` 调用
2. xv6-k210 的 IPI 发送代码有 bug
3. xv6-k210 的 hart 1 缺少 `plicinithart()` 调用

---

## 安全机制差异

### 1. 权限模型差异（UID/GID）

**oskernel2023-zmz**: 🔸 **仅有定义未强制执行**
- `sys_getuid()` 硬编码返回 0 (`kernel/syscall/sysproc.c:267-270`)
- `sys_faccessat()` 注释明确标注 `// assume user as root`
- 仅检查 owner 权限位（右移 6 位），无真实 UID/GID 匹配
- **证据代码** (`kernel/syscall/sysfile.c:896-903`):
```c
// assume user as root
int imode = (ip->mode >> 6) & 0x7;  // 仅检查所有者权限
if ((imode & mode) != mode)
    return -1;
```
- `struct proc` 中**无** `uid`/`gid` 字段

**xv6-k210**: 🔸 **完全相同（桩函数）**
- 代码与 oskernel2023-zmz 完全一致
- 同样硬编码返回 0，同样假设所有用户为 root

**差异结论**: 两个项目**代码相同**，均未实现真实的多用户权限模型。

---

### 2. 安全沙箱差异（Seccomp/prctl）

**oskernel2023-zmz**: ❌ **未实现**
- grep 搜索 `seccomp|prctl|capability` 返回 0 结果
- 无系统调用过滤机制

**xv6-k210**: ❌ **未实现**
- 同样无相关代码

**差异结论**: 两个项目均**未实现**安全沙箱机制。

---

### 3. 用户指针验证差异

**oskernel2023-zmz**: ✅ **已实现基础验证**
- 通过 `copyin2()` + `partofseg()` 进行段合法性检查 (`kernel/mm/vm.c:823-832`)
- 存在 `copyin_nocheck()` 等绕过路径
- **未发现** `UserInPtr`、`verify_area` 等高级封装

**xv6-k210**: ✅ **同样实现**
- 代码结构相同

**差异结论**: 两个项目**代码相同**，均提供基础用户指针验证，但存在绕过路径。

---

### 4. 其他安全机制对比

| 安全特性 | oskernel2023-zmz | xv6-k210 | 差异 |
|---------|------------------|----------|------|
| SSTATUS_PUM/SUM | ✅ 已实现 | ✅ 已实现 | 相同 |
| KPTI | ❌ 未实现 | ❌ 未实现 | 相同 |
| Stack Canary | ❌ 未实现 | ❌ 未实现 | 相同 |
| 资源限制 (prlimit) | 🔸 桩函数 | 🔸 桩函数 | 相同 |
| Audit 审计 | ❌ 未实现 | ❌ 未实现 | 相同 |
| 安全启动 | ❌ 未实现 | ❌ 未实现 | 相同 |

**总体结论**: 两个项目在安全机制上**代码高度相似**，均为基础教学级实现，无显著差异。

---

## 网络差异

### 1. 协议栈差异

**oskernel2023-zmz**: ❌ **未实现**
- grep 搜索 `smoltcp|lwip|tcp_|udp_|struct iphdr` 返回 0 结果
- 无第三方网络库依赖
- 无自研协议栈代码

**xv6-k210**: ❌ **未实现**
- 同样无网络协议栈

**差异结论**: 两个项目均**未实现**网络协议栈。

---

### 2. Socket 接口差异

**oskernel2023-zmz**: ❌ **未实现**
- `include/sysnum.h` 中无 `SYS_socket`、`SYS_bind`、`SYS_sendto` 等定义
- grep 搜索 `sys_sendto|sys_socket|sys_bind|sys_connect` 返回 0 结果

**xv6-k210**: ❌ **未实现**
- 同样无网络系统调用

**差异结论**: 两个项目均**未实现**Socket 接口。

---

### 3. 网卡驱动差异

**oskernel2023-zmz**: ❌ **未实现**
- `kernel/hal/` 目录下仅有 `virtio_disk.c`（块设备）、`sdcard.c`
- grep 搜索 `virtio_net|e1000|net_driver|ethernet` 返回 0 结果
- `include/hal/virtio.h:21` 注释提到 "1 is net, 2 is disk"，但**仅实现了磁盘驱动**

**xv6-k210**: ❌ **未实现**
- 同样仅实现 VirtIO 磁盘驱动

**差异结论**: 两个项目均**未实现**网卡驱动。

---

### 4. 协议支持差异

| 协议 | oskernel2023-zmz | xv6-k210 |
|------|------------------|----------|
| TCP | ❌ 未实现 | ❌ 未实现 |
| UDP | ❌ 未实现 | ❌ 未实现 |
| IP | ❌ 未实现 | ❌ 未实现 |
| DHCP | ❌ 未实现 | ❌ 未实现 |
| DNS | ❌ 未实现 | ❌ 未实现 |
| Loopback | ❌ 未实现 | ❌ 未实现 |

---

### 5. Call Graph 对比：网络 syscall

**跳过说明**: 两个项目均**未实现** `sys_sendto`、`sys_socket` 等网络系统调用，无法进行 Call Graph 对比。

**降级分析**: 通过 grep 验证：
- oskernel2023-zmz: `grep "sys_sendto|sys_socket"` → 0 结果
- xv6-k210: 同样 0 结果

---

## Call Graph差异

### 多核启动 Call Graph 对比（`main` 函数）

| 项目 | 分析模式 | 节点数 | 关键差异 |
|------|---------|--------|----------|
| oskernel2023-zmz | LSP | 55 | 完整调用链，包含 `sbi_send_ipi`、`plicinithart` |
| xv6-k210 | Tree-sitter (降级) | 7 | LSP 不可用，仅提取到 bootloader 代码 |

**Jaccard 相似度**: 0.000（因分析模式不同导致）

**代码级对比**（通过阅读源码）:
1. **oskernel2023-zmz** 有 `delay(100000000)` 调用（xv6-k210 无）
2. **xv6-k210** 的 IPI 发送代码有 bug（`res` 未定义）
3. **xv6-k210** 的 hart 1 缺少 `plicinithart()` 调用

---

## 功能覆盖对比表

| 功能维度 | 子功能 | oskernel2023-zmz | xv6-k210 | 差异程度 |
|---------|--------|------------------|----------|----------|
| **多核支持** | SMP 架构 | ✅ 已实现（双核） | 🔸 框架存在（有 bug） | 🔴 大 |
| | Secondary CPU 启动 | ✅ 已实现 | 🔸 桩函数（代码错误） | 🔴 大 |
| | IPI 发送 | ✅ 已实现 | ✅ 已实现 | 🟢 小 |
| | IPI 处理 | 🔸 部分实现（wakeup 使用） | 🔸 桩函数 | 🟡 中 |
| | Per-CPU 变量 | ✅ 已实现 | ✅ 已实现 | 🟢 小 |
| | 多核调度 | ❌ 全局队列（无负载均衡） | ❌ 全局队列 | 🟢 小 |
| | SpinLock | ✅ 已实现 | ✅ 已实现 | 🟢 小 |
| **安全机制** | UID/GID 管理 | 🔸 桩函数（返回 0） | 🔸 桩函数 | 🟢 小 |
| | 文件权限检查 | 🔸 假设 root | 🔸 假设 root | 🟢 小 |
| | Seccomp/Prctl | ❌ 未实现 | ❌ 未实现 | 🟢 小 |
| | 用户指针验证 | ✅ 基础实现 | ✅ 基础实现 | 🟢 小 |
| | KPTI/SMEP | ❌ 未实现 | ❌ 未实现 | 🟢 小 |
| | Stack Canary | ❌ 未实现 | ❌ 未实现 | 🟢 小 |
| **网络子系统** | 协议栈 | ❌ 未实现 | ❌ 未实现 | 🟢 小 |
| | Socket syscall | ❌ 未实现 | ❌ 未实现 | 🟢 小 |
| | 网卡驱动 | ❌ 未实现 | ❌ 未实现 | 🟢 小 |
| | TCP/UDP/IP | ❌ 未实现 | ❌ 未实现 | 🟢 小 |

---

## 总结

### 核心发现

1. **代码同源性极高**: 两个项目在多核、安全、网络三个维度的代码**几乎完全相同**，表明它们可能源自同一代码库（xv6-riscv 变种）。

2. **关键差异点**:
   - **oskernel2023-zmz** 的多核启动代码更完整（无编译错误）
   - **xv6-k210** 存在明显的代码缺陷（`res` 变量未定义、`plicinithart()` 被注释）
   - **oskernel2023-zmz** 在 `wakeup()` 中实际使用 IPI，而 xv6-k210 的 IPI 处理仅为桩函数

3. **共同缺失**:
   - 两个项目均**未实现**网络子系统
   - 两个项目均**未实现**真实的多用户权限模型（所有进程为 root）
   - 两个项目均**未实现**高级安全特性（Seccomp、KPTI、Stack Canary）

### 创新点标注

**未发现显著创新点**: 两个项目均为教学级操作系统，功能实现较为保守，未发现目标项目 (oskernel2023-zmz) 有而候选项目 (xv6-k210) 没有的独特实现。相反，oskernel2023-zmz 的代码质量略高于 xv6-k210（无编译错误）。

### 建议

如需进一步验证差异，建议：
1. 修复 xv6-k210 的 `res` 变量 bug 后重新编译测试
2. 在 QEMU 多核环境下验证两个项目的 SMP 启动成功率
3. 检查是否有未提交的补丁或分支包含网络功能实现