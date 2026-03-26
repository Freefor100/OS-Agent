## 多核差异

### 1. 多核架构差异

| 项目 | 架构类型 | 实现状态 | 关键证据 |
|------|---------|---------|---------|
| **oskernel2023-avx** | AMP (名义SMP) | 🔸 桩函数 | `kernel/include/param.h:5` 定义 `NCPU 2`，但从核仅轮询 UART |
| **xv6-k210** | 单核 | ❌ 未实现 | `include/param.h:5` 定义 `NCPU 2`，但无 Secondary CPU 启动代码 |

**oskernel2023-avx 详细分析**：
- ✅ 定义了 per-CPU 结构体 `struct cpu cpus[NCPU]`（`kernel/include/proc.h:44-51`）
- ✅ 通过 `r_tp()` 读取 hartid 作为 CPU 索引（`kernel/include/riscv.h:296-302`）
- ❌ **从核未进入调度器**：`kernel/main.c:85-92` 中 hart 2 初始化后进入 `while(1) UART 轮询` 死循环，**从未调用 `scheduler()`**
- ❌ 无全局任务队列或负载均衡机制

**xv6-k210 详细分析**：
- ✅ 定义了 `struct cpu cpus[NCPU]`（`kernel/sched/proc.c:94`）
- ✅ 通过 `r_tp()` 获取 CPU ID（`kernel/sched/proc.c:98-101`）
- ❌ **IPI 发送代码有 bug**：`kernel/main.c:68` 行 `sbi_send_ipi` 前一行被注释，导致 `res` 未定义但后续仍引用
- ❌ Hart 1 仅通过 `while(started==0)` 自旋等待，无独立启动序列

**【差异结论】**：两个项目都**未实现真正的 SMP**。oskernel2023-avx 的从核至少能初始化并处理 UART 中断，而 xv6-k210 的 IPI 发送代码存在编译错误。

---

### 2. Secondary CPU 启动差异

**降级分析**（`compare_call_graphs` 未找到 `smp_boot`/`start_secondary` 函数）：

| 启动阶段 | oskernel2023-avx | xv6-k210 |
|---------|-----------------|---------|
| **IPI 发送** | ✅ `sbi_hart_start(2, ...)` (`kernel/main.c:70-75`) | 🔸 `sbi_send_ipi(mask, 0)` 代码有 bug (`kernel/main.c:66-73`) |
| **从核入口** | ✅ 复用 `main()` 的 `else` 分支 | ✅ 复用 `main()` 的 `else` 分支 |
| **从核初始化** | ✅ `kvminithart()`, `trapinithart()`, `plicinithart()` | ✅ `floatinithart()`, `kvminithart()`, `trapinithart()` |
| **从核调度** | ❌ 进入 `while(1) UART 轮询` | ✅ 进入 `scheduler()`（但无独立初始化） |
| **tp 寄存器初始化** | ❌ 未发现 | ❌ 未发现 |

**关键代码对比**：

```c
// oskernel2023-avx: kernel/main.c:77-92
} else {
    // other hart
    while (started == 0)
      ;
    __sync_synchronize();
    kvminithart();
    trapinithart();
    plicinithart();
    debug_print("hart 1 init done\n");
    printf("hart 2\n");
    while (1) {  // ❌ 关键问题：从核仅处理 UART，未进入调度器
      int c = uart8250_getc();
      if (-1 != c) {
        consoleintr(c);
      }
    }
  }
  scheduler();  // 只有主核能执行到这里
```

```c
// xv6-k210: kernel/main.c:76-83
else {
    // hart 1
    while (started == 0)
        ;
    __sync_synchronize();
    floatinithart();
    kvminithart();
    trapinithart();
    printf("hart 1 init done\n");
}
// 注意：xv6-k210 的 hart 1 在初始化后继续执行到 scheduler()
```

**【差异结论】**：
- oskernel2023-avx 的从核**明确被限制在 UART 轮询**，设计意图就是单核调度
- xv6-k210 的从核在初始化后**理论上能进入 `scheduler()`**，但缺乏独立的 CPU 初始化序列（如 `procinit()`、`plicinit()`）

---

### 3. 核间中断 IPI 差异

| 功能 | oskernel2023-avx | xv6-k210 |
|------|-----------------|---------|
| **IPI 接口定义** | ✅ `kernel/include/sbi.h:82-84` | ✅ `include/sbi.h:96-103` |
| **IPI 发送调用** | 🔸 仅启动时使用，运行时未调用 | ✅ `wakeup()` 中调用 (`kernel/sched/proc.c:397-403`) |
| **IPI 处理逻辑** | ❌ 仅清除 pending 位，无业务逻辑 | ❌ 仅清除 pending 位 (`kernel/trap/trap.c:246-325`) |
| **IPI 消息队列** | ❌ 未实现 | ❌ 未实现 |

**grep 证据**：
- oskernel2023-avx：搜索 `sbi_send_ipi` 仅在 `sbi.h` 头文件和 `main.c` 启动代码中找到，**运行时未调用**
- xv6-k210：在 `kernel/sched/proc.c:397-403` 的 `wakeup()` 中有实际调用：
  ```c
  if (flag && avail) {
      sbi_send_ipi(1 << id, 0);  // 通知另一个 CPU 检查可运行进程
  }
  ```

**【差异结论】**：xv6-k210 在 `wakeup()` 中**实际使用了 IPI** 进行核间通知，而 oskernel2023-avx 的 IPI 机制**仅有接口定义，未在任何同步场景中使用**。

---

### 4. Per-CPU 变量设计差异

| 特性 | oskernel2023-avx | xv6-k210 |
|------|-----------------|---------|
| **Per-CPU 结构体** | ✅ `struct cpu` 含 `proc`, `context`, `noff`, `intena` | ✅ 相同字段 |
| **访问方式** | ✅ `mycpu()` → `cpus[cpuid()]` | ✅ 相同 |
| **中断嵌套管理** | ✅ `push_off()`/`pop_off()` (`kernel/intr.c:12-45`) | ✅ 相同实现 (`kernel/intr.c:12-40`) |
| **缓存行对齐** | ❌ 未实现 | ❌ 未实现 |
| **Per-CPU 段优化** | ❌ 未实现 | ❌ 未实现 |

**共同问题**：
- 两个项目都使用简单的全局数组 `cpus[NCPU]`，每次访问需通过 `cpuid()` 索引
- 都**未使用基于 `tp` 寄存器的偏移访问**（如 Linux 的 `__percpu` 段）
- 都**未实现缓存行对齐**，多核下可能产生伪共享（False Sharing）

**【差异结论】**：Per-CPU 设计**高度相似**，都采用 xv6 经典的简单数组模式，无高级优化。

---

## 安全机制差异

### 1. 权限模型差异

| 特性 | oskernel2023-avx | xv6-k210 |
|------|-----------------|---------|
| **UID/GID 字段定义** | ✅ `kernel/include/proc.h:66-67` | ❌ `struct proc` 中**无** uid/gid 字段 |
| **UID/GID 系统调用** | ✅ `sys_setuid`/`sys_getuid` (`kernel/sysproc.c:415-423`) | 🔸 `sys_getuid` 始终返回 0 (`kernel/syscall/sysproc.c:267-270`) |
| **文件权限检查** | ❌ 未实现（`sys_open` 无检查） | 🔸 简化检查（仅检查 owner 位，假设所有用户为 root） |
| **文件所有权存储** | ❌ 硬编码为 0 (`kernel/fat32.c:781-782`) | ❌ 硬编码为 0 (`exec.c:241-244`) |

**关键代码对比**：

```c
// oskernel2023-avx: kernel/sysproc.c:415-423
uint64 sys_setuid(void) {
  int uid;
  if (argint(0, &uid) < 0)
    return -1;
  myproc()->uid = uid;  // ❌ 任意进程可设置任意 UID，无权限验证
  return 0;
}

// oskernel2023-avx: kernel/fat32.c:781-782
void kstat(struct dirent *de, struct kstat *kst) {
  // ...
  kst->st_uid = 0;  // ❌ 硬编码为 root
  kst->st_gid = 0;
}
```

```c
// xv6-k210: kernel/syscall/sysproc.c:267-270
uint64 sys_getuid(void) {
    return 0;  // 🔸 始终返回 0（root）
}

// xv6-k210: kernel/syscall/sysfile.c:815-823
// assume user as root  ← 关键注释
int imode = (ip->mode >> 6) & 0x7;  // 仅检查 owner 权限位
if ((imode & mode) != mode)
    return -1;
return 0;
```

**grep 验证**：
- 两个项目搜索 `check_perm|inode_permission` 都**未找到独立权限检查函数**
- oskernel2023-avx 的 `sys_open` (`kernel/sysfile.c:455-462`) 直接调用 `open()`，**无任何 UID 检查**
- xv6-k210 的 `sys_faccessat` 有注释 `// assume user as root`，明确说明**所有进程被视为 root**

**【差异结论】**：
- oskernel2023-avx **有 UID/GID 字段但无强制执行**，属于"名义多用户"
- xv6-k210 **连 UID/GID 字段都未在进程结构体中定义**，更彻底的单用户设计
- 两个项目都**不适合生产环境的多用户部署**

---

### 2. 安全沙箱差异

| 特性 | oskernel2023-avx | xv6-k210 |
|------|-----------------|---------|
| **Seccomp** | ❌ 未实现（搜索无结果） | ❌ 未实现（搜索无结果） |
| **prctl** | ❌ 未实现 | ❌ 未实现 |
| **Capability** | ❌ 未实现（lwIP 中的"capability"为网络术语） | ❌ 未实现 |
| **审计日志** | 🔸 基础 syslog 缓冲区（非安全审计） | ❌ 未实现 |

**grep 证据**：
- 两个项目搜索 `seccomp|prctl|sandbox` 都**无匹配**
- oskernel2023-avx 有 `syslogbuffer` (`kernel/sysfile.c:25-29`)，但仅用于调试日志，**非安全审计**

**【差异结论】**：两个项目都**未实现任何安全沙箱机制**，符合教学操作系统的定位。

---

### 3. 用户指针验证差异

| 特性 | oskernel2023-avx | xv6-k210 |
|------|-----------------|---------|
| **用户空间访问函数** | ✅ `copyin`/`copyout`/`either_copyin`/`either_copyout` | ✅ `copyin`/`copyout`/`copyinstr` |
| **地址合法性检查** | ✅ `copyin` 检查 `PTE_U` 位 (`kernel/vm.c:133-136`) | ✅ 相同逻辑 |
| **绕过路径** | ❌ 未发现 `*_nocheck` 变体 | ⚠️ 存在 `copyin_nocheck`/`copyout_nocheck` (`include/mm/vm.h:64-75`) |
| **UserInPtr/verify_area** | ❌ 未实现 | ❌ 未实现 |

**关键代码对比**：

```c
// oskernel2023-avx: kernel/vm.c:133-136
if ((*pte & PTE_U) == 0) {
    debug_print("walkaddr: *pte & PTE_U == 0\n");
    return NULL;  // ✅ 拒绝访问非用户页
}
```

```c
// xv6-k210: include/mm/vm.h:64-75
int copyout_nocheck(uint64 dstva, char *src, uint64 len);  // ⚠️ 无检查版本
int copyin_nocheck(char *dst, uint64 srcva, uint64 len);
```

**【差异结论】**：
- 两个项目都通过 `copyin`/`copyout` 进行用户指针验证
- xv6-k210 存在 `*_nocheck` 变体函数，**可能绕过地址检查**（在 `kernel/console.c` 等位置使用）
- 都**未实现**类似 Linux 的 `access_ok()` 或 Rust 的 `UserInPtr` 类型安全封装

---

## 网络差异

### 1. 协议栈差异

| 项目 | 协议栈来源 | 运行模式 | 关键证据 |
|------|-----------|---------|---------|
| **oskernel2023-avx** | 第三方 lwIP 库 | 🔸 仅回环模式 (Loopback) | `kernel/lwip/` 完整实现，`tcpip_init_with_loopback()` |
| **xv6-k210** | ❌ 未实现 | ❌ 无网络功能 | 搜索 `lwip_|smoltcp|tcp_` 无结果 |

**oskernel2023-avx 详细分析**：
- ✅ 集成 lwIP 2.x 协议栈（`kernel/lwip/` 目录）
- ✅ 配置支持 TCP/UDP/IPv4/DNS (`kernel/lwip/lwipopts.h`)
- ❌ **仅回环模式**：`tcpip_init_with_loopback()` 初始化，文档明确说明"不经过 qemu 的网卡，直接通过本机 ring buffer 进行信息传递"
- ❌ **无真实网卡驱动**：搜索 `virtio_net|VIRTIO_ID_NET|e1000` 无结果

**xv6-k210 详细分析**：
- ❌ **完全无网络子系统**
- ❌ 无协议栈依赖（`Cargo.toml` 无 `smoltcp` 等）
- ❌ 无网络系统调用（`include/sysnum.h` 无 `SYS_socket` 等定义）
- ❌ 无网卡驱动（`kernel/hal/` 仅 SD 卡、VirtIO 磁盘驱动）

**【差异结论】**：oskernel2023-avx **有完整的 Socket API 但仅限回环测试**，xv6-k210 **完全无网络功能**。

---

### 2. Socket 接口差异

| 系统调用 | oskernel2023-avx | xv6-k210 |
|---------|-----------------|---------|
| `sys_socket` | ✅ `kernel/syssocket.c:66` | ❌ 未定义 |
| `sys_bind` | ✅ `kernel/syssocket.c:110` | ❌ 未定义 |
| `sys_connect` | ✅ `kernel/syssocket.c:161` | ❌ 未定义 |
| `sys_sendto` | ✅ `kernel/syssocket.c:254` | ❌ 未定义 |
| `sys_recvfrom` | ✅ `kernel/syssocket.c:299` | ❌ 未定义 |
| `sys_getsockname` | ❌ 未实现 | ❌ 未定义 |

**oskernel2023-avx 实现细节**：
- 所有 socket syscall 封装在 `kernel/syssocket.c`
- 底层调用 `kernel/socket_new.c` 的 `do_*` 函数
- 最终转发至 lwIP 原生 API（`lwip_socket()`、`lwip_sendto()` 等）

**xv6-k210**：
- `include/sysnum.h` 定义的系统调用涵盖进程、文件、内存、信号、时间，**无网络相关**
- `kernel/fs/file.c` 定义的文件类型包括 `FD_INODE`、`FD_DEVICE`、`FD_PIPE`，**无 `FD_SOCKET`**

**【差异结论】**：oskernel2023-avx **提供完整的 BSD Socket 接口**，xv6-k210 **无任何网络 syscall**。

---

### 3. 网卡驱动差异

| 驱动类型 | oskernel2023-avx | xv6-k210 |
|---------|-----------------|---------|
| **VirtIO-Net** | ❌ 未实现（`virtio_disk.c` 仅支持磁盘） | ❌ 未实现 |
| **E1000/82599** | ❌ 未实现 | ❌ 未实现 |
| **RTL8139** | ❌ 未实现 | ❌ 未实现 |
| **回环接口** | ✅ lwIP `loop_netif` | ❌ 无 |

**grep 证据**：
- 两个项目搜索 `virtio_net|VIRTIO_ID_NET|e1000|rtl8139` 都**无匹配**
- oskernel2023-avx 的 `kernel/virtio_disk.c` 有检查 `VIRTIO_MMIO_DEVICE_ID != 2`，**仅支持 VirtIO 磁盘**

**【差异结论】**：两个项目都**无真实网卡驱动**。oskernel2023-avx 通过 lwIP 回环接口实现本机通信，xv6-k210 完全无网络接口。

---

### 4. 协议支持差异

| 协议 | oskernel2023-avx | xv6-k210 |
|------|-----------------|---------|
| **IPv4** | ✅ `LWIP_IPV4=1` | ❌ 未实现 |
| **IPv6** | ❌ `LWIP_IPV6=0` | ❌ 未实现 |
| **TCP** | ✅ `LWIP_TCP=1` | ❌ 未实现 |
| **UDP** | ✅ `LWIP_UDP=1` | ❌ 未实现 |
| **ICMP** | ❌ `LWIP_ICMP=0` (ping 不可用) | ❌ 未实现 |
| **DHCP** | ❌ `LWIP_DHCP=0` | ❌ 未实现 |
| **DNS** | ✅ `LWIP_DNS=1` | ❌ 未实现 |
| **ARP** | ✅ `LWIP_ARP=1` (回环无需) | ❌ 未实现 |

**oskernel2023-avx 配置** (`kernel/lwip/lwipopts.h`)：
```c
#define LWIP_IPV4            1
#define LWIP_IPV6            0
#define LWIP_TCP             1
#define LWIP_UDP             1
#define LWIP_ICMP            0
#define LWIP_DHCP            0
#define LWIP_DNS             1
#define LWIP_NETIF_LOOPBACK  1
```

**【差异结论】**：oskernel2023-avx **支持 TCP/UDP/IPv4/DNS**（但仅限回环），xv6-k210 **不支持任何网络协议**。

---

## Call Graph差异

### sys_sendto 调用链对比

**oskernel2023-avx**（`compare_call_graphs` 成功）：
```
sys_sendto (kernel\syssocket.c:254)
├── argaddr
├── argfd
│   ├── argint
│   ├── debug_print
│   └── myproc
├── argint
├── copyin
├── do_sendto
│   └── lwip_sendto (lwIP 原生 API)
├── myproc
└── printf
```

**xv6-k210**：
```
[未找到函数 sys_sendto 的定义]
```

**差异分析**：
- **共同调用** (0): 无
- **oskernel2023-avx 独有** (8): `argaddr`, `argfd`, `argint`, `copyin`, `debug_print`, `do_sendto`, `myproc`, `printf`
- **xv6-k210 独有** (0): 无
- **Jaccard 相似度**: 0.000

**【降级分析补充】**：
由于 `compare_call_graphs` 对 `smp_boot`/`start_secondary` 返回"未找到函数"，已通过 `grep_in_repo` 进行文本级对比（见"多核差异"部分）。

**【结论】**：oskernel2023-avx 有**完整的 socket 发送调用链**，从系统调用到 lwIP 协议栈；xv6-k210 **完全无网络功能**。

---

## 功能覆盖对比表

| 功能维度 | 子功能 | oskernel2023-avx | xv6-k210 | 差异程度 |
|---------|--------|-----------------|---------|---------|
| **多核支持** | SMP 架构 | 🔸 AMP (从核仅 UART) | ❌ 单核 | 🔴 大 |
| | Secondary CPU 启动 | 🔸 初始化但不调度 | 🔸 代码有 bug | 🟡 中 |
| | IPI 通信 | ❌ 仅接口定义 | ✅ `wakeup()` 中使用 | 🟡 中 |
| | Per-CPU 变量 | ✅ 简单数组 | ✅ 简单数组 | 🟢 小 |
| | 多核调度 | ❌ 全局队列，无负载均衡 | ❌ 全局队列，无负载均衡 | 🟢 小 |
| **安全机制** | UID/GID 字段 | ✅ 定义但未强制 | ❌ 进程结构体无字段 | 🔴 大 |
| | 文件权限检查 | ❌ 无检查 | 🔸 简化检查 (假设 root) | 🟡 中 |
| | Seccomp/沙箱 | ❌ 未实现 | ❌ 未实现 | 🟢 小 |
| | 用户指针验证 | ✅ `copyin` 检查 `PTE_U` | ⚠️ 存在 `*_nocheck` 绕过 | 🟡 中 |
| | KPTI/SMEP/SMAP | ❌ 未实现 | ❌ 未实现 | 🟢 小 |
| **网络子系统** | 协议栈 | ✅ lwIP (回环模式) | ❌ 未实现 | 🔴 大 |
| | Socket 接口 | ✅ 完整 syscall | ❌ 未定义 | 🔴 大 |
| | 网卡驱动 | ❌ 无真实驱动 | ❌ 无真实驱动 | 🟢 小 |
| | TCP/UDP 支持 | ✅ 已实现 | ❌ 未实现 | 🔴 大 |
| | DHCP/DNS | 🔸 DNS 支持，DHCP 无 | ❌ 未实现 | 🔴 大 |

### 图例说明
- ✅ 已实现：存在完整的业务逻辑代码
- 🔸 桩函数/部分实现：函数体不完整、硬编码返回值、或功能受限
- ❌ 未实现：代码中完全不存在相关结构或函数
- ⚠️ 存在安全隐患：如绕过检查的路径

### 总体评估

| 项目 | 多核支持 | 安全机制 | 网络功能 | 适用场景 |
|------|---------|---------|---------|---------|
| **oskernel2023-avx** | 🔸 名义多核 (AMP) | 🔸 基础隔离，无权限控制 | ✅ 回环模式 Socket | 教学演示 + Socket 编程测试 |
| **xv6-k210** | ❌ 单核 | 🔸 基础隔离，更简化的权限 | ❌ 无网络 | 纯教学操作系统，K210 硬件移植 |

**核心结论**：
1. **多核支持**：两个项目都**未实现真正的 SMP**。oskernel2023-avx 的从核至少能处理 UART 中断，xv6-k210 的 IPI 代码存在 bug。
2. **安全机制**：两个项目都**仅有 UID/GID 定义但未强制执行**，所有进程实质上以 root 权限运行。
3. **网络功能**：**最大差异点**。oskernel2023-avx 集成 lwIP 提供完整 Socket API（仅限回环），xv6-k210 完全无网络功能。
4. **创新点**：未发现目标项目 (oskernel2023-avx) 有独特的创新实现，两者都基于 xv6 经典设计，oskernel2023-avx 主要优势在于集成了 lwIP 协议栈。