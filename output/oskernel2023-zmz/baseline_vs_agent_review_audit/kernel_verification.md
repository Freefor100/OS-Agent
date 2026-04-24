# 内核核验（仅 `repos/oskernel2023-zmz`）

路径：`/home/leo/OS-Agent/repos/oskernel2023-zmz`。工具：`rg` + 片段阅读 `kernel/main.c`、`kernel/sched/proc.c`、`kernel/mm/vm.c`、`kernel/syscall/sysfile.c`、`kernel/sync/spinlock.c`、`include/sched/proc.h`、`include/memlayout.h`。

下列为 **实质 value 分歧**（非仅选项字母前缀差异）的裁定。


| question_id                | 事实结论                                                                       | 更优侧                                        | 依据（仓库内）                                                                                                                                       |
| -------------------------- | -------------------------------------------------------------------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **Q03_009**                | 每进程用户页表 + 调度切换 SATP                                                        | **baseline**                               | `kernel/sched/proc.c`：`w_satp(MAKE_SATP(tmp->pagetable))` / `w_satp(MAKE_SATP(kernel_pagetable))`；非「与用户共享单一页表」模型。                             |
| **Q03_016**                | 有块缓冲（buffer cache），严格「Page Cache」命名未必                                      | **tie / 略偏 baseline**                      | `kernel/fs/bio.c` 等缓冲路径存在；`stub` vs `not_found` 属术语档，不在此强行二选一。                                                                                |
| **Q03_017**                | 未见完整脏页回写子系统线索                                                              | **略偏 agent `not_found`**                   | 未在本次检索中定位典型 writeback 线程；与 `stub` 的边界题。                                                                                                       |
| **Q04_018**                | cgroup/namespace 等未见                                                       | **baseline `not_found`**                   | `rg cgroup                                                                                                                                    |
| **Q04_023**                | 未见调度器维护「等待时间」等 Stallings 指标                                                | **baseline**（选 F）                          | 题面允「未发现则选 F」；单独勾选「等待时间」缺乏「调度器追踪该指标」的实现证据。                                                                                                     |
| **Q05_010**                | `pselect`/`ppoll` 已注册并实现体                                                  | **baseline `implemented`**                 | `kernel/syscall/syscall.c`：`sys_pselect`/`sys_ppoll`；`kernel/syscall/sysfile.c`：`sys_pselect`/`sys_ppoll`。agent 判 `stub` 与代码不符。               |
| **Q05_012**                | 未见 symlink 系统调用/路径                                                         | **baseline `not_found`**                   | `rg symlink                                                                                                                                   |
| **Q05_017** vs **Q05_018** | FAT 空闲空间由 FAT 表链描述；Q05_017 若问「分配方式」链式 vs FAT 表需对照题面措辞                      | **agent Q05_017 文本更贴 FAT 机制**；Q05_018 两侧一致 | FAT 表内嵌空闲链为 FAT 经典模型；baseline 在 Q05_017 选「链式分配」易与「簇链」概念混淆，需结合教材题面再酌。                                                                          |
| **Q05_031**                | `kvmmap(UART_V, UART, …)`，存在物理 UART 与映射后 `UART_V`                          | **agent `implemented` 更合理**                | `kernel/mm/vm.c` + `include/memlayout.h`：`UART` / `UART_V`；`main.c` 中 `consoleinit` 早于 `kvminithart`，映射提供 MMU 后访问路径。baseline `not_found` 偏保守。 |
| **Q05_034**                | virtio 块设备以 **DMA 区 + 完成中断** 为典型路径                                         | **baseline「混合」更接近**                        | `kernel/hal/virtio_disk.c`：注释与 `virtio_disk_intr()` 等；纯「仅中断无 DMA」不贴切。                                                                         |
| **Q06_013**                | 自旋锁为 GCC `__sync_*` / 生成 **amoswap** 等，非 Rust `core::sync::atomic`         | **agent**                                  | `kernel/sync/spinlock.c`：`__sync_lock_test_and_set`；本仓为 C。baseline 选 Rust 原子库不成立。                                                             |
| **Q06_017**                | 存在 `wait_queue` + `sleep`/`wakeup` 式条件等待（类 Mesa 条件变量语义，非 Hoare monitor 类名） | **baseline `implemented` 略更贴**             | `include/sync/waitqueue.h` 等；严格「monitor 关键字」无，但同步原语层面有 CV 风格。                                                                                 |
| **Q07_002**                | `struct proc` **无** UID/GID；`kstat` 有 uid/gid 字段                           | **agent `stub`**                           | `include/sched/proc.h` PCB 字段列表；仅有 inode stat 字段不足以称完整凭证体系 `implemented`。                                                                     |
| **Q09_005**                | 未见内核交互监视器命令循环                                                              | **agent `not_found`**                      | `rg monitor                                                                                                                                   |
| **Q09_008**                | 未见 ftrace/perf/tracepoint 框架                                               | **agent `stub`** 或 `**not_found**`         | `rg ftrace                                                                                                                                    |


---

## 核验命令摘要（可复现）

```bash
rg -n "w_satp|MAKE_SATP" kernel --glob '*.c'
rg -n "sys_pselect|sys_ppoll" kernel/syscall --glob '*.c'
rg -n "symlink|sys_symlink" kernel/fs --glob '*.c'
rg -n "UART_V|kvmmap\\(UART" kernel/mm/vm.c include/memlayout.h
rg -n "virtio_disk_intr|DMA" kernel/hal/virtio_disk.c
rg -n "__sync_lock_test_and_set" kernel/sync/spinlock.c
rg -n "struct proc" -n include/sched/proc.h  # 人工视读字段
rg -n "ftrace|tracepoint|perf_event" kernel --glob '*.c'
```

