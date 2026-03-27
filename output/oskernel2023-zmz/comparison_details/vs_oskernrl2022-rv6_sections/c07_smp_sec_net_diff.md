## 多核差异

### 1. 多核架构差异

| 项目 | 架构类型 | 最大核心数 | 证据 |
|------|---------|-----------|------|
| **oskernel2023-zmz** | ✅ SMP | 2 核 | `include/param.h:5`: `#define NCPU 2` |
| **oskernrl2022-rv6** | ✅ SMP | 5 核 | `src/include/param.h:4`: `#define NCPU 5` |

**共同点**：两个项目均采用 **SMP（对称多处理）** 架构，所有核心共享同一内核地址空间和全局数据结构。

**差异点**：
- oskernel2023-zmz 限制为 2 核（适用于 K210 双核开发板）
- oskernrl2022-rv6 支持最多 5 核（适用于 QEMU 多核模拟）

---

### 2. Secondary CPU 启动差异

**oskernel2023-zmz 启动流程** (`kernel/main.c:76-95`)：
- 使用 **SBI IPI 扩展** (`sbi_send_ipi`) 唤醒 AP
- BSP 通过 `started` 标志释放 AP
- AP 自旋等待 `while (started == 0);`

**oskernrl2022-rv6 启动流程** (`src/main.c:77-89`)：
- 使用 **SBI HSM 扩展** (`start_hart`) 唤醒 AP
- 通过 `booted[]` 数组标记每核启动状态
- 同样使用 `started` 标志同步

**关键代码对比**：

```c
// oskernel2023-zmz: 使用 IPI 唤醒
for (int i = 1; i < NCPU; i ++) {
    unsigned long mask = 1 << i;
    struct sbiret res = sbi_send_ipi(mask, 0);  // IPI 方式
    __debug_assert("main", SBI_SUCCESS == res.error, "sbi_send_ipi failed");
}
__sync_synchronize();
started = 1;

// oskernrl2022-rv6: 使用 HSM START 唤醒
for(int i = 1; i < NCPU; i++) {
    if(hartid!=i && booted[i]==0){
        start_hart(i, (uint64)_entry, 0);  // HSM 方式
    }
}
started=1;
```

**差异总结**：
- oskernel2023-zmz 使用 **SBI IPI 扩展** (EID=0x735049)
- oskernrl2022-rv6 使用 **SBI HSM 扩展** (EID=0x48534D) 的 `START` 功能

---

### 3. 核间中断 IPI 差异

| 项目 | IPI 接口 | 实际使用 | 状态 |
|------|---------|---------|------|
| **oskernel2023-zmz** | `sbi_send_ipi()` (`include/sbi.h:98`) | ✅ 仅用于启动 | 已实现但未用于运行时通信 |
| **oskernrl2022-rv6** | `send_ipi()` (`src/include/sbi.h:86`) | ❌ 完全未使用 | 🔸 桩函数（有接口无调用） |

**证据**：
- oskernel2023-zmz: `kernel/main.c:78-80` 调用 `sbi_send_ipi` 唤醒 AP
- oskernrl2022-rv6: `grep` 搜索 `send_ipi` 仅在头文件定义，**无任何.c 文件调用**

**结论**：两个项目均**未实现运行时 IPI 通信**（如调度器间通知、TLB 刷新）。

---

### 4. Per-CPU 变量设计差异

**结构定义对比**：

```c
// oskernel2023-zmz: include/sched/proc.h:158-165
struct cpu {
    struct proc *proc;       // 当前运行进程
    struct context context;  // 调度器上下文
    int noff;                // 中断禁用嵌套深度
    int intena;              // 保存的中断状态
};

// oskernrl2022-rv6: src/include/cpu.h:30-35
struct cpu {
  struct proc *proc;          // 当前运行进程
  struct context context;     // 调度器上下文
  int noff;                   // 中断禁用嵌套深度
  int intena;                 // 保存的中断状态
};
```

**访问方式**：
- 两者均通过 `tp` 寄存器读取 hartid (`cpuid()` → `r_tp()`)
- 两者均提供 `mycpu()` 和 `myproc()` 访问函数

**差异**：
- oskernel2023-zmz: `struct cpu cpus[NCPU]` 定义在 `kernel/sched/proc.c:92`
- oskernrl2022-rv6: `struct cpu cpus[NCPU]` 定义在 `src/cpu.c:13`

**结论**：Per-CPU 设计**高度相似**，均为基础实现，无 Per-CPU 就绪队列或分配器优化。

---

## 安全机制差异

### 1. 权限模型差异（UID/GID）

| 项目 | UID/GID 字段 | 系统调用实现 | 权限检查 | 状态 |
|------|-------------|-------------|---------|------|
| **oskernel2023-zmz** | ❌ 无 | `sys_getuid()` 硬编码返回 0 | ❌ 无检查 | 🔸 桩函数 |
| **oskernrl2022-rv6** | ✅ 有 (`struct proc::uid/gid`) | `sys_getuid()` 返回 `myproc()->uid` | ❌ 无检查 | 🔸 仅有定义未强制执行 |

**关键代码对比**：

```c
// oskernel2023-zmz: kernel/syscall/sysproc.c:267-270
uint64 sys_getuid(void) {
    return 0;  // 硬编码返回 root
}
// struct proc 中无 uid/gid 字段

// oskernrl2022-rv6: src/sysproc.c:48-94
uint64 sys_getuid(void) {
  return myproc()->uid;  // 返回实际字段
}
uint64 sys_setuid(void) {
  int uid;
  if(argint(0, &uid) < 0) return -1;
  myproc()->uid = uid;  // 直接赋值，无权限检查！
  return 0;
}
// struct proc 包含 uid/gid 字段 (src/include/proc.h:141-142)
```

**文件权限检查**：
- oskernel2023-zmz: `sys_faccessat()` 注释明确 `// assume user as root`，仅检查所有者权限位
- oskernrl2022-rv6: `sys_openat()` **未使用** UID/GID 进行权限验证

**结论**：
- oskernel2023-zmz：**仅有定义未实现**（无 uid 字段，syscall 硬编码返回 0）
- oskernrl2022-rv6：**仅有定义未强制执行**（有 uid 字段，但 setuid 无权限检查）

---

### 2. 安全沙箱差异

| 特性 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|-----------------|-----------------|
| **Seccomp** | ❌ 未实现 | ❌ 未实现 |
| **Prctl** | ❌ 未实现 | ❌ 未实现 |
| **Sandbox** | ❌ 未实现 | ❌ 未实现 |

**证据**：两个项目 grep 搜索 `seccomp|prctl|sandbox` 均**无匹配结果**。

---

### 3. 用户指针验证差异

| 项目 | 验证机制 | 实现文件 | 状态 |
|------|---------|---------|------|
| **oskernel2023-zmz** | `copyin2()` + `partofseg()` + `safememmove()` | `kernel/mm/vm.c:823-832` | ✅ 已实现 |
| **oskernrl2022-rv6** | `copyin()`/`copyout()` + `walkaddr()` | `src/vm.c:164-182` | ✅ 已实现 |

**关键代码**：

```c
// oskernel2023-zmz: kernel/mm/vm.c:823-832
int copyin2(char *dst, uint64 srcva, uint64 len) {
    struct proc *p = myproc();
    struct seg *s = partofseg(p->segment, srcva, srcva + len);
    if (s == NULL) return -1;  // 段检查
    uint64 badaddr = safememmove(dst, (char *)srcva, len);
    return badaddr == 0 ? 0 : -1;
}

// oskernrl2022-rv6: src/vm.c:164-182
uint64 walkaddr(pagetable_t pagetable, uint64 va) {
  if(va >= MAXVA) return NULL;
  pte = walk(pagetable, va, 0);
  if(pte == 0) return NULL;
  if((*pte & PTE_V) == 0) return NULL;
  if((*pte & PTE_U) == 0) return NULL;  // 用户可访问检查
  return PTE2PA(*pte);
}
```

**差异**：
- oskernel2023-zmz 使用**段机制** (`struct seg`) 进行额外验证
- oskernrl2022-rv6 仅依赖**页表权限位** (`PTE_U`)

---

## 网络差异

### 1. 协议栈差异

| 项目 | 协议栈类型 | 状态 | 证据 |
|------|-----------|------|------|
| **oskernel2023-zmz** | ❌ 未实现 | 无第三方库，无自研代码 | 搜索 `smoltcp|lwip|tcp|udp` 无结果 |
| **oskernrl2022-rv6** | ❌ 未实现 | 仅有头文件定义，无实现 | `src/include/socket.h` 仅声明无实现 |

**结论**：两个项目均**未实现任何网络协议栈**。

---

### 2. Socket 接口差异

| 系统调用 | oskernel2023-zmz | oskernrl2022-rv6 |
|---------|-----------------|-----------------|
| `SYS_socket` | ❌ 未定义 | ❌ 未实现 |
| `SYS_bind` | ❌ 未定义 | ❌ 未实现 |
| `SYS_connect` | ❌ 未定义 | ❌ 未实现 |
| `SYS_sendto` | ❌ 未定义 | ❌ 未实现 |
| `SYS_recvfrom` | ❌ 未定义 | ❌ 未实现 |

**证据**：
- oskernel2023-zmz: `include/sysnum.h` 约 90 个 syscall，**无网络相关定义**
- oskernrl2022-rv6: `src/include/socket.h` 定义 `struct socket_connection`，但 `socket_init()` 和 `add_socket()` **无实现代码**

---

### 3. 网卡驱动差异

| 项目 | VirtIO-Net | E1000 | Loopback | 状态 |
|------|-----------|-------|----------|------|
| **oskernel2023-zmz** | ❌ 未实现 | ❌ 未实现 | ❌ 未实现 | 仅实现 VirtIO 磁盘 |
| **oskernrl2022-rv6** | ❌ 未实现 | ❌ 未实现 | ❌ 未实现 | 仅实现 console/null/zero 设备 |

**证据**：
- oskernel2023-zmz: `kernel/hal/virtio_disk.c` 仅实现块设备驱动
- oskernrl2022-rv6: `src/dev.c` 仅注册 `console`、`null`、`zero` 设备

---

### 4. 协议支持差异

| 协议 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|-----------------|-----------------|
| TCP | ❌ 未实现 | ❌ 未实现 |
| UDP | ❌ 未实现 | ❌ 未实现 |
| IP | ❌ 未实现 | ❌ 未实现 |
| DHCP | ❌ 未实现 | ❌ 未实现 |
| DNS | ❌ 未实现 | ❌ 未实现 |

**结论**：两个项目均**不支持任何网络协议**。

---

## Call Graph 差异

### `main` 函数调用链对比

**Jaccard 相似度**: 0.321 (35 共同节点 / 109 全集)

**共同调用** (35 个)：
`acquire`, `allocproc`, `binit`, `cpuinit`, `disk_init`, `forkret`, `inithartid`, `initlock`, `intr_on`, `kernelvec`, `kmalloc`, `kmallocinit`, `kpminit`, `kvminit`, `kvminithart`, `memset`, `mycpu`, `printf`, `printfinit`, `proc_pagetable`, `procinit`, `r_sie`, `r_sstatus`, `release`, `safestrcpy`, `scheduler`, `set_next_timeout`, `sfence_vma`, `swtch`, `trapinithart`, `userinit`, `w_satp`, `w_sie`, `w_sstatus`, `w_stvec`

**oskernel2023-zmz 独有** (33 个)：
- **SMP 相关**: `sbi_send_ipi`, `plicinit`, `plicinithart`, `floatinithart`
- **内存管理**: `__mul_alloc_no_lock`, `__mul_free_no_lock`, `__mul_freerange`, `kvmmap`, `mappages`, `uvminit`, `protect_usr_mem`
- **硬件驱动**: `dmac_init`, `fpioa_pin_init`, `sdcard_init`, `consoleinit`
- **调试**: `__panic`, `print_logo`, `delay`

**oskernrl2022-rv6 独有** (41 个)：
- **SMP 相关**: `start_hart`, `sbi_hsm_hart_status`
- **设备管理**: `devinit`, `allocdev`, `consoleread`, `consolewrite`, `nullread`, `zerowrite`
- **文件系统**: `fs_init`, `fileinit`, `logbufinit`, `create`, `ewrite`
- **进程调度**: `readyq_pop`, `readyq_push`, `queue_init`, `waitq_pool_init`
- **调试**: `__debug_info`, `__debug_warn`, `panic`

**关键差异分析**：

1. **Secondary CPU 启动方式**：
   - oskernel2023-zmz: `sbi_send_ipi` → IPI 唤醒
   - oskernrl2022-rv6: `start_hart` → HSM START 唤醒

2. **中断控制器初始化**：
   - oskernel2023-zmz: 显式调用 `plicinit()`/`plicinithart()`
   - oskernrl2022-rv6: 未在 main 中显式调用 PLIC 初始化

3. **内存管理复杂度**：
   - oskernel2023-zmz: 使用多级分配器 (`__mul_*`, `__sin_*`)
   - oskernrl2022-rv6: 使用简单队列管理 (`queue_push`, `queue_pop`)

---

## 功能覆盖对比表

| 功能维度 | 子功能 | oskernel2023-zmz | oskernrl2022-rv6 | 差异程度 |
|---------|--------|-----------------|-----------------|---------|
| **多核架构** | SMP 支持 | ✅ 已实现 (2 核) | ✅ 已实现 (5 核) | 🔵 小 |
| | Secondary CPU 启动 | ✅ IPI 唤醒 | ✅ HSM 唤醒 | 🟡 中 |
| | IPI 运行时通信 | ❌ 未实现 | ❌ 未实现 | 🔵 小 |
| | Per-CPU 变量 | ✅ 已实现 | ✅ 已实现 | 🔵 小 |
| | 多核负载均衡 | ❌ 未实现 | ❌ 未实现 | 🔵 小 |
| **安全机制** | UID/GID 字段 | ❌ 无定义 | ✅ 已定义 | 🟡 中 |
| | UID/GID 权限检查 | ❌ 硬编码 root | ❌ 无检查 | 🟡 中 |
| | 文件权限检查 | 🔸 仅 root 位 | ❌ 未实现 | 🟡 中 |
| | Seccomp/Prctl | ❌ 未实现 | ❌ 未实现 | 🔵 小 |
| | 用户指针验证 | ✅ 段 + 页表 | ✅ 页表 | 🟡 中 |
| | Stack Canary | ❌ 未实现 | ❌ 显式禁用 | 🔵 小 |
| **网络子系统** | Socket 接口 | ❌ 未实现 | 🔸 仅头文件 | 🟡 中 |
| | TCP/IP 协议栈 | ❌ 未实现 | ❌ 未实现 | 🔵 小 |
| | 网卡驱动 | ❌ 未实现 | ❌ 未实现 | 🔵 小 |
| | Loopback 支持 | ❌ 未实现 | ❌ 未实现 | 🔵 小 |

**图例**：
- 🔵 小：两者实现状态相同（均实现或均未实现）
- 🟡 中：实现细节或完整度有差异
- 🔴 大：架构设计或核心机制有本质差异

---

## 总结

### 多核支持
两个项目均实现了**基础 SMP 架构**，但存在启动机制差异：
- oskernel2023-zmz 使用 **SBI IPI 扩展** 唤醒 AP
- oskernrl2022-rv6 使用 **SBI HSM 扩展** 唤醒 AP
- 两者均**未实现运行时 IPI 通信**和多核负载均衡

### 安全机制
- oskernel2023-zmz：**更简化**，无 UID/GID 字段，所有进程硬编码为 root
- oskernrl2022-rv6：**有字段无检查**，定义了 uid/gid 但 setuid 无权限验证
- 两者均**未实现** Seccomp、Capability、Audit 等高级安全特性

### 网络子系统
- 两个项目均**未实现任何网络功能**
- oskernrl2022-rv6 虽有 `socket.h` 头文件，但仅为桩代码
- 均不适合需要网络通信的应用场景

### 创新点
**未发现明显创新点**。两个项目均为教学性质的基础 OS 实现，功能覆盖相似，差异主要体现在：
- 硬件抽象层实现细节（IPI vs HSM）
- 内存管理复杂度（多级分配器 vs 简单队列）
- 安全模型完整度（无 UID 字段 vs 有字段无检查）