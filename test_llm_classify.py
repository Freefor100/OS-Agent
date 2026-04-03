#!/usr/bin/env python3
"""Test LLM batch classification accuracy for OS kernel functions."""
import json, sys, os
sys.path.insert(0, "/home/leo/OS-Agent")

from core.per_llm_stages import call_llm

DOMAINS = ["arch_platform","trap_syscall","process_sched","memory_vm",
           "fs_storage","sync_ipc","runtime_common","user_programs","unknown"]
LAYERS  = ["userspace","syscall_boundary","kernel","hardware","unknown"]

# Test cases: (fn_name, file_path, expected_domain, expected_layer)
TEST_CASES = [
    ("start_kernel",      "init/main.c",               "arch_platform",  "kernel"),
    ("sys_write",         "fs/read_write.c",            "trap_syscall",   "syscall_boundary"),
    ("do_fork",           "kernel/fork.c",              "process_sched",  "kernel"),
    ("schedule",          "kernel/sched/core.c",        "process_sched",  "kernel"),
    ("alloc_pages",       "mm/page_alloc.c",            "memory_vm",      "kernel"),
    ("handle_mm_fault",   "mm/memory.c",                "memory_vm",      "kernel"),
    ("virtio_disk_rw",    "virtio/virtio_disk.c",       "arch_platform",  "hardware"),
    ("uart_putc",         "driver/uart.c",              "arch_platform",  "hardware"),
    ("trap_handler",      "arch/riscv/trap.c",          "trap_syscall",   "kernel"),
    ("mutex_lock",        "kernel/locking/mutex.c",     "sync_ipc",       "kernel"),
    ("sys_clone",         "kernel/fork.c",              "process_sched",  "syscall_boundary"),
    ("kmalloc",           "mm/slab.c",                  "memory_vm",      "kernel"),
    ("user_main",         "user/init.c",                "user_programs",  "userspace"),
    ("uservec",           "arch/riscv/trampoline.S",    "trap_syscall",   "kernel"),
    ("copy_from_user",    "lib/usercopy.c",             "runtime_common", "kernel"),
]

nodes = [{"fn_name": fn, "file_path": fp} for fn, fp, _, _ in TEST_CASES]

prompt = f"""你是操作系统内核专家。对以下函数按 domain 和 layer 分类，只输出 JSON。

domain（选一个）: arch_platform/trap_syscall/process_sched/memory_vm/fs_storage/sync_ipc/runtime_common/user_programs/unknown
- arch_platform: 启动汇编、平台初始化、硬件驱动（uart/virtio/plic/timer等）
- trap_syscall: 中断异常向量、系统调用入口分发（不含具体sys_函数实现）
- process_sched: 进程创建/调度/上下文切换
- memory_vm: 内存分配、页表、虚拟内存、缺页处理
- fs_storage: 文件系统、磁盘I/O、inode/dentry
- sync_ipc: 锁、信号量、管道、消息、进程间通信
- runtime_common: 通用库函数（string/copy/print等）、链接器脚本无关代码
- user_programs: 用户态程序、用户态库
- unknown: 无法确定

layer（选一个）: userspace/syscall_boundary/kernel/hardware/unknown
- userspace: 运行在用户态的代码
- syscall_boundary: sys_开头的系统调用入口函数（仅入口，不含实现）
- kernel: 内核态通用逻辑
- hardware: 直接操作硬件寄存器/设备的驱动代码（uart/virtio/plic等）
- unknown: 无法确定

函数列表:
{json.dumps(nodes, ensure_ascii=False, indent=2)}

输出格式（只输出JSON，不要markdown代码块）:
{{"fn_name": {{"domain": "...", "layer": "..."}}, ...}}"""

print("Sending request to LLM...")
response = call_llm(prompt, max_tokens=1000)
print(f"\nRaw response:\n{response}\n")

# Parse JSON
try:
    # Strip possible markdown fences
    text = response.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    predictions = json.loads(text.strip())
except Exception as e:
    print(f"JSON parse error: {e}")
    sys.exit(1)

# Evaluate
domain_correct = 0
layer_correct = 0
total = len(TEST_CASES)

print(f"{'Function':<20} {'File':<30} {'D_exp':<15} {'D_pred':<15} {'L_exp':<18} {'L_pred':<18} D? L?")
print("-" * 130)
for fn, fp, exp_d, exp_l in TEST_CASES:
    pred = predictions.get(fn, {})
    pred_d = pred.get("domain", "unknown")
    pred_l = pred.get("layer", "unknown")
    d_ok = pred_d == exp_d
    l_ok = pred_l == exp_l
    if d_ok: domain_correct += 1
    if l_ok: layer_correct += 1
    print(f"{fn:<20} {fp:<30} {exp_d:<15} {pred_d:<15} {exp_l:<18} {pred_l:<18} {'✓' if d_ok else '✗'} {'✓' if l_ok else '✗'}")

print(f"\nDomain accuracy: {domain_correct}/{total} = {100*domain_correct/total:.0f}%")
print(f"Layer  accuracy: {layer_correct}/{total} = {100*layer_correct/total:.0f}%")
