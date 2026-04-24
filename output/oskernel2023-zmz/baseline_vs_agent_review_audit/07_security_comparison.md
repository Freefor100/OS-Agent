# 07_security — Baseline vs Agent

- 题库题数: 14
- baseline `report_quality_score`: 0.96
- agent `report_quality_score`: 0.98

| question_id | type | agreement | better_side(初值) | baseline_se | baseline_sc | agent_se | agent_sc | baseline_value | agent_value |
|---|---|:---|:---|---:|---:|---:|---:|---|---|
| Q07_001 | single_choice | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | A. 有用户态/内核态隔离（user mode/kernel mode） | 有用户态/内核态隔离（user mode/kernel mode） |
| Q07_002 | tri_state_impl | 结论冲突 | 待核验 | 0.90 | 1.00 | 0.95 | 1.00 | implemented | stub |
| Q07_003 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | stub | stub |
| Q07_004 | short_answer | 表述差异 | 待酌 | 0.85 | 0.95 | 0.95 | 0.95 | 未发现完整的权限检查链路。sys_openat -> namei -> lookup_path -> dirlookup 路径中仅有文件存在性检查，无基于 UID/GID 的访问控制检查。faccessat 系统调用存在但仅检查文件模式位，未与进程凭证关联。 | 权限检查链路（简化版，假设 root）：sys_faccessat → nameifrom → ip->mode >> 6 检查所有者权限。证据：`kernel/syscall/sysfile.c:1057-1072` sys_faccessat 中'assume user as root'注释后直接检查 (imode & mode) != mode；`kernel/syscall/sysfile.c:466-530` sys_o... |
| Q07_005 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | implemented | implemented |
| Q07_006 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 0.90 | 1.00 | not_found | not_found |
| Q07_007 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 1.00 | 1.00 | stub | stub |
| Q07_008 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 0.90 | 1.00 | not_found | not_found |
| Q07_009 | short_answer | 表述差异 | 待酌 | 0.95 | 1.00 | 1.00 | 0.95 | 仅支持 riscv64 架构。证据：1) Makefile 中 TOOLPREFIX := riscv64-linux-gnu- 2) include/hal/riscv.h 中定义 RISC-V 特有 CSR 操作 3) sbi/psicasbi/Cargo.toml 中 target = riscv64imac-unknown-none-elf。安全相关初始化：PMP 配置在 sbi/psicasbi/src/main.rs ... | 仅支持 RISC-V 64（riscv64）。证据：`include/hal/riscv.h` 定义 SSTATUS_SPP/SSTATUS_PUM/SSTATUS_SUM 等 RISC-V 特有寄存器位；`sbi/psicasbi/src/main.rs:161-187` 有 PMP 初始化代码但配置为允许所有访问（pmpaddr = -1, pmpcfg = R\|W\|X）；未发现 aarch64/x86_64/loonga... |
| Q07_010 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | not_found | not_found |
| Q07_011 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | not_found | not_found |
| Q07_012 | short_answer | 表述差异 | 待酌 | 0.90 | 1.00 | 1.00 | 0.95 | 字段存在但无检查链。kstat 结构体中有 uid/gid 字段，sys_getuid 等系统调用返回硬编码的 0，faccessat 仅检查文件模式位 (imode & mode)，未与进程 UID/GID 进行比较。openat/execve/write 等关键系统调用路径中未见基于凭证的权限验证逻辑。 | 字段存在但无检查链。struct kstat 包含 uid/gid 字段（`include/fs/stat.h:54-55`），但 struct proc 无 uid/gid 字段；sys_faccessat 中注释'assume user as root'后直接检查 mode 位（`kernel/syscall/sysfile.c:1065-1070`），无 UID/GID 比较逻辑；sys_getuid 硬编码返回 0（`ke... |
| Q07_013 | single_choice | 一致 | tie | 0.90 | 1.00 | 1.00 | 1.00 | D. 仅有特权级隔离（ring0/ring3），无细粒度访问控制 | 仅有特权级隔离（ring0/ring3），无细粒度访问控制 |
| Q07_014 | tri_state_impl | 一致 | tie | 0.95 | 1.00 | 0.90 | 1.00 | not_found | not_found |

统计: 一致=10, 表述差异=3, 结论冲突=1
