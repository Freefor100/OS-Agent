## 驱动框架差异

### 1.1 驱动框架设计对比

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **框架类型** | 双层架构（SBI Rust + 内核 C） | 单层架构（纯 C 内核 + SBI 调用） |
| **驱动抽象** | ✅ Trait 抽象（`UartHandler`） | 🔸 静态设备表（`struct devsw`） |
| **注册机制** | 条件编译集中初始化 | 运行时静态注册（`allocdev()`） |
| **设备发现** | ❌ 硬编码地址 | ❌ 硬编码地址 |

**oskernel2023-zmz 驱动框架特征**：
- **SBI 层**（Rust）：`sbi/psicasbi/src/hal/uart/mod.rs` 定义 `UartHandler` Trait
- **内核层**（C）：`kernel/hal/disk.c` 通过条件编译选择驱动
- **初始化入口**：`kernel/main.c:66` 调用 `disk_init()`

```c
// oskernel2023-zmz: kernel/hal/disk.c:22-32
void disk_init(void) {
    __debug_info("disk_init", "enter\n");
    #ifdef QEMU
    virtio_disk_init();
    #else 
    sdcard_init();
    #endif
    __debug_info("disk_init", "leave\n");
}
```

**oskernrl2022-rv6 驱动框架特征**：
- **静态设备表**：`src/include/dev.h` 定义 `struct devsw` 最多支持 4 种设备
- **设备注册**：`src/dev.c:24-45` 的 `devinit()` 调用 `allocdev()` 静态注册
- **SBI 抽象**：所有 UART 操作通过 `sbi_console_getchar/putchar` 调用

```c
// oskernrl2022-rv6: src/dev.c:42-45
int devinit() {
    memset(devsw, 0, NDEV*sizeof(struct devsw));
    allocdev("console", consoleread, consolewrite);
    allocdev("null", nullread, nullwrite);
    allocdev("zero", zeroread, zerowrite);
    return 0;
}
```

### 1.2 设备发现机制

**两个项目均未实现设备树解析**：

| 项目 | 设备发现方式 | 证据文件 |
|------|-------------|---------|
| oskernel2023-zmz | 硬编码地址（`include/memlayout.h`） | `include/memlayout.h:36-50` |
| oskernrl2022-rv6 | 硬编码地址（`src/include/memlayout.h`） | `src/include/memlayout.h:1-2` |

```c
// oskernel2023-zmz: include/memlayout.h:36-50
#define VIRT_OFFSET             0x3F00000000L
#ifdef QEMU
#define UART                    0x10000000L
#define VIRTIO0                 0x10001000
#else
#define UART                    0x38000000L  // K210
#endif
```

**结论**：❌ 两个项目都**未实现**动态设备发现（DTS/PCI 枚举），采用编译期硬编码。

---

## 设备支持 Call Graph 差异

### 2.1 驱动初始化 Call Graph 对比

由于两个项目均无 `init_drivers` 函数，使用 `disk_init` 作为驱动初始化入口进行对比：

#### `disk_init` 调用链对比

| 项目 | 调用链深度 | 关键子调用 |
|------|-----------|-----------|
| **oskernel2023-zmz** | 2 层 | `disk_init` → `sdcard_init` / `virtio_disk_init` |
| **oskernrl2022-rv6** | 1 层 | `disk_init` → `ramdisk_init` / `disk_initialize`（LSP 未追踪到） |

**Call Graph 工具输出**：
```
### oskernel2023-zmz 的调用树
[Call Graph] 根节点: disk_init  ← kernel\hal\disk.c:22
》出吐调用 (Outgoing Calls):
    ├── sdcard_init  [sdcard_init]  ← include\hal\sdcard.h:6

### oskernrl2022-rv6 的调用树
[Call Graph] 根节点: disk_init  ← src\disk.c:16
》出吐调用 (Outgoing Calls):  (空)
```

**降级分析**：通过 `grep_in_repo` 验证 `oskernrl2022-rv6` 的实际调用：
```c
// oskernrl2022-rv6: src/disk.c:16-23
void disk_init(void) {
    if(disk_init_flag) return;
    else disk_init_flag = 1;
    #ifdef RAM
    ramdisk_init();
    #else
    disk_initialize(0);  // FatFs 磁盘初始化
    #endif
}
```

**差异总结**：
- **oskernel2023-zmz**：明确区分 QEMU（VirtIO）和 K210（SD 卡）路径
- **oskernrl2022-rv6**：区分 RAM 磁盘和 SD 卡后端，但 Call Graph 工具未能完整追踪

### 2.2 VirtIO 驱动支持对比

| 功能 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **VirtIO-Blk** | ✅ 已实现 | ❌ 未实现 |
| **初始化函数** | `virtio_disk_init()` (kernel/hal/virtio_disk.c:95) | 仅头文件声明，无实现 |
| **Call Graph 节点** | 6 个（`__panic`, `cpuid`, `initlock`, `memset`, `printf`, `wait_queue_init`） | 未找到函数定义 |

**oskernel2023-zmz VirtIO 初始化调用链**：
```
virtio_disk_init  ← kernel\hal\virtio_disk.c:95
├── __panic
├── cpuid
├── initlock
├── memset
├── printf
└── wait_queue_init
```

**oskernrl2022-rv6 状态**：
```c
// src/include/virtio.h:56-61 - 仅定义结构体
struct VRingDesc {
  uint64 addr;
  uint32 len;
  uint16 flags;
  uint16 next;
};
// 声明但未实现
void virtio_disk_init(void);  // ❌ 无实现体
```

### 2.3 设备驱动 Call Graph 对比：`devinit`

| 项目 | `devinit` 存在性 | 调用链节点数 |
|------|-----------------|-------------|
| oskernel2023-zmz | ❌ 未实现 | N/A |
| oskernrl2022-rv6 | ✅ 已实现 | 21 个节点 |

**oskernrl2022-rv6 `devinit` 调用链**（21 个子调用）：
```
devinit  ← src\dev.c:24
├── __debug_info, allocdev, consoleread, consolewrite
├── consputc, create, either_copyin, either_copyout
├── eput, eunlock, ewrite, initlock, memset
├── nullread, nullwrite, sbi_console_getchar
├── strncpy, zero_out, zeroread, zerowrite
└── allocdev → [initlock, strncpy, __debug_warn]
```

**结论**：`oskernrl2022-rv6` 有完整的设备表初始化框架，而 `oskernel2023-zmz` 采用条件编译直接调用驱动初始化函数，无统一设备注册机制。

---

## IPC 机制差异表

### 3.1 锁机制对比

| 锁类型 | oskernel2023-zmz | oskernrl2022-rv6 | 实现差异 |
|--------|------------------|------------------|---------|
| **SpinLock** | ✅ 已实现 | ✅ 已实现 | 两者均使用 `amoswap.w.aq` 原子指令 |
| **SleepLock** | ✅ 已实现 | ✅ 已实现 | 两者均内嵌 SpinLock + WaitQueue |
| **RwLock** | ❌ 未实现 | ❌ 未实现 | 均未发现读写锁实现 |
| **Semaphore** | ❌ 未实现 | ❌ 未实现 | System V 信号量未实现 |

**SpinLock 实现对比**：
```c
// oskernel2023-zmz: kernel/sync/spinlock.c:23-45
void acquire(struct spinlock *lk) {
    push_off();
    if(holding(lk)) panic("acquire");
    while(__sync_lock_test_and_set(&lk->locked, 1) != 0) ;
    __sync_synchronize();  // memory fence
    lk->cpu = mycpu();
}

// oskernrl2022-rv6: src/spinlock.c:24-46 (几乎相同)
void acquire(struct spinlock *lk) {
    push_off();
    if(holding(lk)) panic("acquire");
    while(__sync_lock_test_and_set(&lk->locked, 1) != 0) ;
    __sync_synchronize();
    lk->cpu = mycpu();
}
```

**结论**：两个项目的 SpinLock 实现**代码高度相似**，均基于 RISC-V `amoswap` 原子指令。

### 3.2 IPC 机制逐项对比

| IPC 机制 | oskernel2023-zmz | oskernrl2022-rv6 | 状态说明 |
|----------|------------------|------------------|---------|
| **Pipe** | ✅ 已实现 | ✅ 已实现 | 两者均实现环形缓冲区 |
| **MessageQueue** | ❌ 未实现 | ❌ 未实现 | 仅文档提及，无代码 |
| **SharedMem (System V)** | ❌ 未实现 | ❌ 未实现 | `shmget/shmat/shmdt` 未实现 |
| **SharedMem (POSIX mmap)** | ✅ 已实现 | ❌ 未实现 | `oskernel2023-zmz` 支持 `MAP_SHARED` |
| **Semaphore (System V)** | ❌ 未实现 | ❌ 未实现 | `semget/semop` 未实现 |
| **Futex** | ❌ 未实现 | 🔸 桩函数 | `oskernrl2022-rv6` 仅有声明 |
| **Signal** | ✅ 已实现 | ✅ 已实现 | 两者均完整实现 |
| **Poll/Select** | ✅ 已实现 | ❌ 未实现 | `oskernel2023-zmz` 独有 |

### 3.3 桩代码检测结果

| 函数名 | oskernel2023-zmz | oskernrl2022-rv6 | 检测依据 |
|--------|------------------|------------------|---------|
| `sys_msgget` | ❌ 未实现 | ❌ 未实现 | grep 搜索无结果 |
| `sys_semget` | ❌ 未实现 | ❌ 未实现 | grep 搜索无结果 |
| `sys_shmget` | ❌ 未实现 | ❌ 未实现 | grep 搜索无结果 |
| `sys_futex` | ❌ 未实现 | 🔸 桩函数 | `oskernrl2022-rv6` 仅在 `src/include/proc.h:199` 有声明 |
| `do_futex` | ❌ 未实现 | 🔸 桩函数 | 仅头文件声明，无实现体 |

**桩函数证据**（oskernrl2022-rv6）：
```c
// src/include/proc.h:199 - 仅声明
int do_futex(int* uaddr, int futex_op, int val, ktime_t *timeout, 
             int *addr2, int val2, int val3);

// 搜索 src/*.c 无 do_futex 函数体实现
```

**文档规划但未实现**（oskernrl2022-rv6）：
```markdown
// doc/内核实现--Futex.md:20-36
| FUTEX_WAIT | 在某锁变量满足条件时，在某锁变量上挂起等待 |
| FUTEX_WAKE | 唤醒若干个在某锁变量上挂起的等待进程 |
// 但源代码中无实现
```

---

## Call Graph 差异

### 4.1 Pipe 写操作 Call Graph 对比

使用 `compare_call_graphs` 对比 `pipewrite` 函数：

| 指标 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **共同调用** | \multicolumn{2}{c|}{7 个：`acquire`, `myproc`, `printf`, `release`, `sched`, `sleep`, `wakeup`} |
| **独有调用** | 18 个 | 16 个 |
| **Jaccard 相似度** | \multicolumn{2}{c|}{0.171 (7 共同 / 41 全集)} |

**oskernel2023-zmz 独有调用**（18 个）：
```
__panic, __proc_list_insert_no_lock, __proc_list_remove_no_lock,
__wakeup_no_lock, copyin_nocheck, cpuid, permit_usr_mem,
pipelock, pipeunlock, pipewakeup, pipewritable, protect_usr_mem,
safememmove, wait_queue_add, wait_queue_del, wait_queue_empty,
wait_queue_is_first, wait_queue_next
```

**oskernrl2022-rv6 独有调用**（16 个）：
```
__debug_error, allocwaitq, delwaitq, either_copyin, findwaitq,
holding, intr_get, mycpu, panic, queue_init, queue_pop,
queue_push, readyq_push, swtch, waitq_pop, waitq_push
```

**关键差异分析**：

1. **等待队列实现不同**：
   - `oskernel2023-zmz`：使用 `wait_queue_*` 系列函数（`wait_queue_add`, `wait_queue_del`）
   - `oskernrl2022-rv6`：使用 `waitq_*` 和 `queue_*` 系列函数（`waitq_push`, `queue_pop`）

2. **Pipe 锁机制不同**：
   - `oskernel2023-zmz`：有专门的 `pipelock()` / `pipeunlock()` 实现 FIFO 排队
   - `oskernrl2022-rv6`：直接使用 `acquire(&pi->lock)` 简单自旋锁

3. **内存拷贝不同**：
   - `oskernel2023-zmz`：使用 `copyin_nocheck()` + `safememmove()`
   - `oskernrl2022-rv6`：使用 `either_copyin()`

**oskernel2023-zmz Pipe 写操作核心调用链**：
```
pipewrite  ← kernel\fs\pipe.c:214
├── pipelock → [acquire, sleep, wait_queue_add]
├── pipewritable → [acquire, sleep, pipewakeup]
├── copyin_nocheck → [safememmove, permit_usr_mem]
├── pipewakeup → [wakeup, wait_queue_next]
└── pipeunlock → [wakeup, wait_queue_del]
```

**oskernrl2022-rv6 Pipe 写操作核心调用链**：
```
pipewrite  ← src\pipe.c:70
├── sleep → [allocwaitq, findwaitq, waitq_push, sched]
├── either_copyin
├── wakeup → [waitq_pop, readyq_push, delwaitq]
└── release
```

### 4.2 Futex 调用链对比（降级分析）

由于两个项目均未实现完整的 `sys_futex`，`compare_call_graphs` 无法获取有效调用图。

**grep 搜索结果**：
- `oskernel2023-zmz`：未找到任何 `futex` 相关代码
- `oskernrl2022-rv6`：仅在头文件和文档中找到声明

**降级分析结论**：
- **oskernel2023-zmz**：❌ **未实现** Futex 机制
- **oskernrl2022-rv6**：🔸 **桩函数** - 仅有 `do_futex` 声明（`src/include/proc.h:199`），无实现体

---

## 桩代码/真实实现区分

### 5.1 设备驱动部分

| 功能模块 | oskernel2023-zmz | oskernrl2022-rv6 | 状态 |
|----------|------------------|------------------|------|
| **UART 驱动** | ✅ 真实实现 | ✅ 真实实现（通过 SBI） | 两者均完整 |
| **VirtIO-Blk** | ✅ 真实实现 | ❌ 未实现 | `oskernrl2022-rv6` 仅头文件 |
| **SD 卡驱动** | ✅ 真实实现 | ✅ 真实实现 | 两者均完整 |
| **RAM 磁盘** | ❌ 未实现 | ✅ 真实实现 | `oskernel2023-zmz` 无此功能 |
| **PLIC 驱动** | ✅ 真实实现 | 🔸 桩函数 | `oskernrl2022-rv6` 中断号硬编码为 0 |
| **CLINT 定时器** | ✅ 真实实现（SBI 调用） | ✅ 真实实现（SBI 调用） | 两者均完整 |
| **网络驱动** | ❌ 未实现 | ❌ 未实现 | 两者均无 |
| **设备树解析** | ❌ 未实现 | ❌ 未实现 | 两者均硬编码 |

**PLIC 桩函数证据**（oskernrl2022-rv6）：
```c
// src/trap.c:220-235
int devintr(void) {
  if ((0x8000000000000000L & scause) && 9 == (scause & 0xff)) {
    int irq = 0;  // ⚠️ 硬编码为 0，未从 PLIC 读取
    // plic_claim();  // 被注释
    if (UART0_IRQ == irq) {
      // consoleintr(c);  // 被注释
    }
    // plic_complete(irq);  // 被注释
    return 1;
  }
}
```

### 5.2 IPC 部分

| IPC 机制 | oskernel2023-zmz | oskernrl2022-rv6 | 状态 |
|----------|------------------|------------------|------|
| **SpinLock** | ✅ 真实实现 | ✅ 真实实现 | 两者均完整 |
| **SleepLock** | ✅ 真实实现 | ✅ 真实实现 | 两者均完整 |
| **WaitQueue** | ✅ 真实实现 | ✅ 真实实现 | 实现方式不同 |
| **Pipe** | ✅ 真实实现 | ✅ 真实实现 | 两者均完整 |
| **Signal** | ✅ 真实实现 | ✅ 真实实现 | 两者均完整 |
| **Poll/Select** | ✅ 真实实现 | ❌ 未实现 | `oskernel2023-zmz` 独有 |
| **Futex** | ❌ 未实现 | 🔸 桩函数 | `oskernrl2022-rv6` 仅声明 |
| **MessageQueue** | ❌ 未实现 | ❌ 未实现 | 两者均无 |
| **Semaphore** | ❌ 未实现 | ❌ 未实现 | 两者均无 |
| **SharedMem (System V)** | ❌ 未实现 | ❌ 未实现 | 两者均无 |
| **SharedMem (POSIX mmap)** | ✅ 真实实现 | ❌ 未实现 | `oskernel2023-zmz` 独有 |

### 5.3 【创新点】发现

| 创新功能 | 所属项目 | 说明 |
|----------|---------|------|
| **Poll/Select 机制** | oskernel2023-zmz | 完整实现 `poll_wait()` 和 `pselect()`，支持管道轮询 |
| **POSIX 共享内存** | oskernel2023-zmz | 通过 `mmap(MAP_SHARED)` 实现文件共享映射 |
| **FPIOA 驱动** | oskernel2023-zmz | K210 可编程 IO 矩阵配置（`kernel/hal/fpioa.c` 83.7KB） |
| **DMAC 驱动** | oskernel2023-zmz | K210 DMA 控制器完整实现（`kernel/hal/dmac.c`） |
| **VirtIO-Blk 完整驱动** | oskernel2023-zmz | 包含初始化、读写、中断处理完整流程 |
| **双层驱动架构** | oskernel2023-zmz | SBI(Rust) + 内核(C) 分离设计 |

---

## 总结

### 驱动部分核心差异

1. **架构设计**：`oskernel2023-zmz` 采用双层架构（SBI Rust + 内核 C），`oskernrl2022-rv6` 为纯 C 内核 + SBI 调用
2. **VirtIO 支持**：`oskernel2023-zmz` 完整实现 VirtIO-Blk，`oskernrl2022-rv6` 仅头文件声明
3. **设备发现**：两者均采用硬编码地址，无设备树解析
4. **平台支持**：`oskernel2023-zmz` 支持 QEMU + K210，`oskernrl2022-rv6` 支持 QEMU + SiFive_U

### IPC 部分核心差异

1. **Pipe 实现**：两者均实现但设计不同（`oskernel2023-zmz` 有 FIFO 排队机制）
2. **Futex**：`oskernrl2022-rv6` 仅有文档规划和接口声明，无实际实现
3. **System V IPC**：两者均未实现消息队列、信号量、共享内存
4. **创新功能**：`oskernel2023-zmz` 独有 Poll/Select 和 POSIX 共享内存

### 代码相似度评估

- **SpinLock/SleepLock**：代码高度相似（基于 xv6 传统实现）
- **Pipe**：设计思路相似但实现细节不同（Jaccard 0.171）
- **WaitQueue**：数据结构不同（双向链表 vs 队列池）