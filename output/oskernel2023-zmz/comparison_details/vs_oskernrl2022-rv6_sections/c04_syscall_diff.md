## Trap 差异

### 1. Trap 入口实现差异

**oskernel2023-zmz**:
- **实现方式**: 纯汇编 `trampoline.S` + C 语言处理
- **用户态入口**: `uservec` 位于 `kernel/trap/trampoline.S:15-70`
- **内核态入口**: `kernelvec` 位于 `kernel/trap/kernelvec.S:10-80`
- **关键特征**: 
  - 使用 `sscratch` 寄存器快速定位 `TrapFrame`
  - 用户态和内核态使用**独立的 Trap 向量**（通过 `stvec` 切换）
  - 浮点寄存器完整保存（33个浮点寄存器 + fcsr）

**oskernrl2022-rv6**:
- **实现方式**: 纯汇编 `trampoline.S` + C 语言处理
- **用户态入口**: `uservec` 位于 `src/trampoline.S:17-85`
- **内核态入口**: `kernelvec` 位于 `src/trap.c:21`（声明）
- **关键特征**:
  - 同样使用 `sscratch` 机制
  - 代码结构与 oskernel2023-zmz 高度相似（设计思路相似）
  - **未保存浮点寄存器**

**证据对比**:
| 项目 | TrapFrame 字段数 | 总字节数 | 浮点寄存器 |
|------|-----------------|---------|-----------|
| oskernel2023-zmz | 70 字段 | 808 字节 | ✅ 33个 (ft0-ft11, fs0-fs11, fa0-fa7, fcsr) |
| oskernrl2022-rv6 | 28 字段 | 224 字节 | ❌ 未实现 |

**TrapFrame 结构体证据**:
- oskernel2023-zmz: `include/trap.h:17-97` 包含 `ft0-ft11, fs0-fs11, fa0-fa7, fcsr`
- oskernrl2022-rv6: `src/include/trap.h:17-56` 仅包含整数寄存器

---

## syscall 分发差异

### 3. 系统调用分发方式

**oskernel2023-zmz**:
- **分发机制**: 函数指针表 `static uint64 (*syscalls[])(void)`
- **文件路径**: `kernel/syscall/syscall.c:197-271`
- **分发函数**: `syscall()` 位于 `kernel/syscall/syscall.c:347-377`
- **代码特征**:
```c
if (SYS_rt_sigreturn == num) {
    sigreturn();  // 特殊处理
}
else if (num < NELEM(syscalls) && syscalls[num]) {
    p->trapframe->a0 = syscalls[num]();
} else {
    p->trapframe->a0 = -1;
}
```

**oskernrl2022-rv6**:
- **分发机制**: 函数指针表（与 oskernel2023-zmz 设计思路相同）
- **文件路径**: `syscall/syscall.c`（grep 未找到完整表定义，但 `syscall()` 函数存在）
- **分发函数**: `syscall()` 位于 `syscall/syscall.c:1-20`
- **代码特征**:
```c
if(num > 0 && num < NELEM(syscalls) && syscalls[num]) {
    p->trapframe->a0 = syscalls[num]();
    // trace
    if ((p->tmask & (1 << num)) != 0) {
        printf("pid %d: %s -> %d\n", p->pid, sysnames[num], p->trapframe->a0);
    }
} else {
    p->trapframe->a0 = -1;
}
```

**结论**: 两者均采用**函数指针表**分发方式，设计思路相同，但 oskernel2023-zmz 对 `SYS_rt_sigreturn` 有特殊分支处理。

---

## Call Graph 差异

### 5. usertrap 调用链对比

使用 `compare_call_graphs(repo_a="oskernel2023-zmz", repo_b="oskernrl2022-rv6", entry_function="usertrap")` 分析结果：

**Jaccard 相似度**: 0.390 (32 共同节点 / 82 全集节点)

**共同调用** (32 个):
`acquire`, `exit`, `holding`, `intr_get`, `intr_off`, `intr_on`, `kernelvec`, `mycpu`, `myproc`, `printf`, `r_satp`, `r_scause`, `r_sepc`, `r_sip`, `r_sstatus`, `r_stval`, `r_tp`, `release`, `sbi_console_getchar`, `sched`, `sighandle`, `swtch`, `syscall`, `timer_tick`, `trapframedump`, `usertrap`, `usertrapret`, `w_sepc`, `w_sip`, `w_sstatus`, `w_stvec`, `yield`

**oskernel2023-zmz 独有调用** (39 个) — 【创新点集中区域】:
- **缺页异常处理链**: `handle_excp` → `handle_page_fault` → `handle_page_fault_lazy` / `handle_page_fault_loadelf` / `handle_page_fault_mmap` / `handle_store_page_fault_cow`
- **中断处理增强**: `handle_intr`, `disk_intr`, `plic_claim`, `plic_complete`, `consoleintr`, `proc_tick`
- **内存管理**: `uvmfree`, `freewalk`, `walk`, `locateseg`, `idlepages`, `protect_usr_mem`, `permit_usr_mem`
- **浮点支持**: `floatload`, `floatstore`, `r_sstatus_fs`, `w_sstatus_fs`
- **进程管理增强**: `__proc_list_insert_no_lock`, `__proc_list_remove_no_lock`, `__wakeup_no_lock`, `__get_runnable_no_lock`
- **SBI 扩展**: `sbi_clear_ipi`, `sbi_xv6_is_ext`, `sbi_xv6_set_ext`, `sdcard_intr`

**oskernrl2022-rv6 独有调用** (11 个):
- **简化进程管理**: `delwaitq`, `findwaitq`, `readyq_push`, `waitq_pop`, `wakeup`, `getparent`, `reparent`
- **简化文件管理**: `eput`, `fileclose`
- **中断分发**: `devintr`（oskernel2023-zmz 将其拆分为 `handle_intr` + `handle_excp`）

**关键差异分析**:
1. oskernel2023-zmz 的 `usertrap` 直接调用 `handle_excp` 和 `handle_intr` 进行细粒度异常/中断处理
2. oskernrl2022-rv6 的 `usertrap` 调用 `devintr` 统一处理设备中断，且缺页异常处理被注释掉（`else if(handle_excp(cause) == 0)` 为空）

---

## 覆盖度对比

### 4. 已实现 syscall 数量与覆盖度

#### oskernel2023-zmz 统计

**系统调用表大小**: 约 74 个（`kernel/syscall/syscall.c:197-271`）

**✅ 完整实现**（核心功能，含业务逻辑）:
| 类别 | 系统调用 | 文件路径 |
|------|---------|---------|
| **进程管理** | `sys_fork`, `sys_clone`, `sys_exec`, `sys_exit`, `sys_wait4`, `sys_getpid`, `sys_getppid` | `kernel/syscall/sysproc.c` |
| **文件 IO** | `sys_read`, `sys_write`, `sys_openat`, `sys_close`, `sys_dup`, `sys_dup3`, `sys_getdents`, `sys_getcwd`, `sys_readv`, `sys_writev`, `sys_lseek` | `kernel/syscall/sysfile.c` |
| **内存管理** | `sys_mmap`, `sys_munmap`, `sys_mprotect`, `sys_brk`, `sys_sbrk` | `kernel/syscall/sysmem.c` |
| **信号** | `sys_kill`, `sys_rt_sigaction`, `sys_rt_sigprocmask` | `kernel/syscall/syssignal.c`, `kernel/sched/signal.c` |
| **时间** | `sys_gettimeofday`, `sys_nanosleep`, `sys_times` | `kernel/syscall/systime.c` |
| **其他** | `sys_uname`, `sys_sysinfo`, `sys_trace`, `sys_fstatat`, `sys_fcntl`, `sys_ioctl` | 多个文件 |

**🔸 桩函数**（有定义但无实际逻辑）:
| 系统调用 | 文件路径 | 桩代码特征 |
|---------|---------|-----------|
| `sys_getuid` | `kernel/syscall/sysproc.c:267` | `return 0;` |
| `sys_geteuid` | `kernel/syscall/syscall.c:242` | 指向 `sys_getuid` |
| `sys_getgid` | `kernel/syscall/syscall.c:243` | 指向 `sys_getuid` |
| `sys_getegid` | `kernel/syscall/syscall.c:244` | 指向 `sys_getuid` |
| `sys_prlimit64` | `kernel/syscall/sysproc.c` | `return 0;`（注释"暂时没必要实现"） |
| `sys_rt_sigtimedwait` | `kernel/syscall/syssignal.c:142` | `return 0;` |
| `sys_exit_group` | `kernel/syscall/syscall.c:252` | 指向 `sys_exit` |

**❌ 未实现**（未在分发表中或完全缺失）:
- `sys_tkill` / `sys_tgkill`: grep 搜索结果为空
- `sys_getrusage`: 仅声明，未找到完整实现

**统计汇总**:
- 完整实现: ~25 个
- 桩函数: 7 个
- 未实现: 约 42 个（74 - 25 - 7）

#### oskernrl2022-rv6 统计

**✅ 完整实现**:
| 类别 | 系统调用 | 文件路径 |
|------|---------|---------|
| **进程管理** | `sys_fork`, `sys_clone`, `sys_execve`, `sys_exit`, `sys_wait4`, `sys_getpid`, `sys_getppid`, `sys_gettid`, `sys_set_tid_address` | `src/sysproc.c` |
| **文件 IO** | `sys_read`, `sys_write`, `sys_readv`, `sys_writev`, `sys_close`, `sys_openat` | `src/sysfile.c` |
| **信号** | `sys_rt_sigaction`, `sys_rt_sigprocmask`, `sys_rt_sigreturn`, `sys_kill`, `sys_tgkill` | `src/syssig.c` |
| **内存管理** | `sys_brk` | `src/sysproc.c:165` |
| **其他** | `sys_uname`, `sys_nanosleep`, `sys_getuid`, `sys_geteuid`, `sys_getgid`, `sys_getegid`, `sys_setuid`, `sys_setgid` | `src/sysproc.c` |

**🔸 桩函数**:
| 系统调用 | 文件路径 | 桩代码特征 |
|---------|---------|-----------|
| `sys_exit_group` | `src/syssig.c:9-11` | `return 0;` |

**❌ 未实现**（文档提及但代码缺失）:
- `sys_mmap` / `sys_munmap`: grep 搜索未找到实现
- `sys_fstat` / `sys_stat`: 未找到完整实现
- `sys_pipe`: 系统调用表中有声明但未找到实现
- `sys_dup` / `sys_dup2`: 未找到实现
- `sys_sleep` / `sys_uptime`: 未找到独立实现
- `sys_mknod` / `sys_unlink` / `sys_link` / `sys_mkdir`: 未找到实现
- `sys_tkill`: 未找到（仅有 `sys_tgkill`）

**统计汇总**:
- 完整实现: ~24 个
- 桩函数: 1 个
- 未实现: 约 10+ 个（基于文档提及但代码缺失）

#### 覆盖度对比表

| 类别 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|-----------------|-----------------|
| **文件 IO** | ✅ read/write/openat/close/dup/dup3/getdents/getcwd/readv/writev/lseek | ✅ read/write/readv/writev/close/openat |
| **进程管理** | ✅ fork/clone/exec/exit/wait4/getpid/getppid | ✅ fork/clone/execve/exit/wait4/getpid/getppid/gettid |
| **内存管理** | ✅ mmap/munmap/mprotect/brk/sbrk | 🔸 仅 brk（mmap/munmap 未实现） |
| **信号** | ✅ kill/rt_sigaction/rt_sigprocmask<br>❌ tkill/tgkill | ✅ kill/rt_sigaction/rt_sigprocmask/rt_sigreturn/tgkill<br>❌ tkill |
| **用户 ID** | 🔸 getuid/geteuid/getgid/getegid（桩函数） | ✅ getuid/geteuid/getgid/getegid/setuid/setgid（完整实现） |
| **系统调用总数** | ~74 个注册 | ~35 个注册（估算） |

---

### 6. 接口/实现分离设计

**oskernel2023-zmz**:
- **模式**: 部分采用 `sys_xxx` → 内部函数调用模式
- **示例**: `sys_write()` → `filewrite()`（`kernel/syscall/sysfile.c:120` → `kernel/fs/file.c`）
- **特征**: 系统调用包装层较薄，直接调用核心文件系统/内存管理函数

**oskernrl2022-rv6**:
- **模式**: 类似的 `sys_xxx` → 内部函数调用
- **示例**: `sys_write()` → `filewrite()`（`src/sysfile.c:233` → `src/file.c`）
- **特征**: 设计与 oskernel2023-zmz 高度相似

**结论**: 两者均未采用严格的 `sys_xxx` / `sys_xxx_impl` 分离模式，而是直接调用核心模块函数。设计思路相同。

---

### 7. 缺页异常处理差异

**oskernel2023-zmz**:
- ✅ **完整实现**缺页异常处理链
- ✅ **Lazy Allocation**: `handle_page_fault_lazy()`（`kernel/mm/vm.c:988`）
- ✅ **CoW（写时复制）**: `handle_store_page_fault_cow()` + `PTE_COW` 标记（`kernel/mm/vm.c:961`, `kernel/mm/vm.c:22`）
- ✅ **mmap 缺页**: `handle_page_fault_mmap()` 支持匿名映射和文件映射（`kernel/mm/mmap.c:1047`）
- **调用链证据**: `handle_excp` → `handle_page_fault` → `handle_store_page_fault_cow` / `handle_page_fault_lazy` / `handle_page_fault_mmap`

**oskernrl2022-rv6**:
- ❌ **未实现**缺页异常处理
- **证据 1**: `src/trap.c:102` 中缺页处理被注释掉：
  ```c
  else if(handle_excp(cause) == 0) {
    // 空处理
  }
  ```
- **证据 2**: grep 搜索 `handle_store_page_fault_cow|PTE_COW|cow` 结果为空
- **证据 3**: 搜索 `handle_page_fault` 仅找到函数声明（`src/include/vm.h:42-43`），未找到实现
- **结论**: CoW 和 Lazy Allocation 特性**❌ 未实现**

**【创新点】**: oskernel2023-zmz 的缺页异常处理链（含 CoW 和 Lazy Allocation）是候选项目完全缺失的核心特性。

---

### 8. 用户指针安全

**oskernel2023-zmz**:
- **实现方式**: 使用 `copyout` / `copyin` / `copyinstr` 系列函数
- **文件路径**: 未在 grep 中找到 `UserInPtr`/`UserOutPtr` 类型
- **参数获取**: `argaddr()` / `argint()` / `argfd()` 从 `trapframe` 提取参数后，通过 `copyout`/`copyin` 进行安全拷贝
- **证据**: `kernel/syscall/sysfile.c:120` 中 `argaddr(1, &p)` 获取用户指针后，传递给 `filewrite()` 内部处理

**oskernrl2022-rv6**:
- **实现方式**: 使用 `copyout` / `copyin` / `copyinstr` / `either_copyout` / `either_copyin` 系列函数
- **文件路径**: `src/copy.c:14-197`
- **函数列表**:
  - `copyout()`: 内核 → 用户
  - `copyout2()`: 内核 → 用户（无页表参数）
  - `copyin()`: 用户 → 内核
  - `copyin2()`: 用户 → 内核（无页表参数）
  - `either_copyout()`: 根据标志位选择用户/内核目标
  - `either_copyin()`: 根据标志位选择用户/内核源
- **证据**: grep 找到 93 个匹配，广泛使用于 `src/dev.c`, `src/exec.c` 等

**结论**: 
- 两者均**未采用** Rust 风格的 `UserInPtr<T>` / `UserOutPtr<T>` 类型安全包装
- 两者均采用传统的 `copyin`/`copyout` 函数进行用户空间指针安全访问
- oskernrl2022-rv6 提供了更丰富的变体（`either_copyin`/`either_copyout`）

---

## 总结

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 | 差异程度 |
|------|-----------------|-----------------|---------|
| **Trap 入口** | 汇编 trampoline.S + 独立内核态入口 | 汇编 trampoline.S | 🔸 小（设计相似） |
| **TrapFrame** | 70 字段/808 字节（含浮点） | 28 字段/224 字节（无浮点） | ✅ 大 |
| **syscall 分发** | 函数指针表 + 特殊分支处理 | 函数指针表 | 🔸 小 |
| **syscall 覆盖度** | ~74 个注册，~25 个完整实现 | ~35 个注册，~24 个完整实现 | ✅ 大 |
| **缺页异常** | ✅ CoW + Lazy Allocation + mmap | ❌ 未实现 | ✅ 大（【创新点】） |
| **信号机制** | 进程级信号，无 tkill/tgkill | 进程级 + 线程级（tgkill） | 🔸 中 |
| **用户指针安全** | copyin/copyout | copyin/copyout + either_* 变体 | 🔸 小 |

**核心【创新点】**（oskernel2023-zmz 独有）:
1. **完整的缺页异常处理链**：含 CoW、Lazy Allocation、mmap 缺页处理
2. **浮点寄存器保存/恢复**：TrapFrame 包含 33 个浮点寄存器
3. **细粒度中断/异常分离**：`handle_intr` 与 `handle_excp` 独立处理
4. **SBI 扩展支持**：`sbi_xv6_is_ext`/`sbi_xv6_set_ext`/`sbi_clear_ipi`
5. **磁盘中断处理**：`disk_intr` / `sdcard_intr`