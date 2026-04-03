#!/usr/bin/env python3
"""测试 LLM 分类：名字+路径+代码片段"""
import sys, json
sys.path.insert(0, "/home/leo/OS-Agent")

from core.agent_builder import build_chat_model
from langchain_core.messages import HumanMessage

TEST_CASES = [
    ("start_kernel", "init/main.c",
     """void start_kernel(void) {
    set_task_stack_end_magic(&init_task);
    setup_arch(&command_line);
    trap_init(); mm_init(); sched_init(); rest_init();
}""", "arch_platform", "kernel"),
    ("sys_write", "kernel/syscall.c",
     """uint64 sys_write(void) {
    struct file *f; int fd = argfd(0, &f);
    uint64 p = argaddr(1); int n = argint(2);
    return filewrite(f, p, n);
}""", "trap_syscall", "syscall_boundary"),
    ("do_fork", "kernel/fork.c",
     """long do_fork(unsigned long clone_flags, unsigned long stack_start) {
    struct task_struct *p = copy_process(clone_flags, stack_start);
    if (!IS_ERR(p)) wake_up_new_task(p);
    return task_pid_vnr(p);
}""", "process_sched", "kernel"),
    ("schedule", "kernel/sched/core.c",
     """asmlinkage void schedule(void) {
    struct task_struct *prev = current, *next;
    next = pick_next_task(rq, prev);
    if (likely(prev != next)) context_switch(rq, prev, next);
}""", "process_sched", "kernel"),
    ("alloc_pages", "mm/page_alloc.c",
     """struct page *alloc_pages(gfp_t gfp_mask, unsigned int order) {
    return __alloc_pages(gfp_mask, order, preferred_nid, NULL);
}""", "memory_vm", "kernel"),
    ("handle_mm_fault", "mm/memory.c",
     """vm_fault_t handle_mm_fault(struct vm_area_struct *vma,
        unsigned long address, unsigned int flags) {
    return __handle_mm_fault(vma, address, flags);
}""", "memory_vm", "kernel"),
    ("virtio_disk_rw", "virtio/virtio_disk.c",
     """void virtio_disk_rw(struct buf *b, int write) {
    uint64 sector = b->blockno * (BSIZE/512);
    disk.desc[idx[0]].addr = (uint64)&buf0;
    *R(VIRTIO_MMIO_QUEUE_NOTIFY) = 0;
    while(b->disk == 1) sleep(b, &disk.vdisk_lock);
}""", "arch_platform", "hardware"),
    ("uart_putc", "driver/uart.c",
     """void uart_putc(int c) {
    while((ReadReg(LSR) & LSR_TX_IDLE) == 0);
    WriteReg(THR, c);
}""", "arch_platform", "hardware"),
    ("trap_handler", "arch/riscv/trap.c",
     """void trap_handler(void) {
    uint64 cause = r_scause();
    if(cause == 8) syscall();
    else if(cause & 0x8000000000000000L) devintr();
    else panic("unexpected trap");
}""", "trap_syscall", "kernel"),
    ("mutex_lock", "kernel/locking/mutex.c",
     """void mutex_lock(struct mutex *lock) {
    if (!__mutex_trylock_fast(lock)) __mutex_lock_slowpath(lock);
}""", "sync_ipc", "kernel"),
    ("sys_clone", "kernel/fork.c",
     """uint64 sys_clone(void) {
    uint64 stack; argaddr(0, &stack);
    return fork();
}""", "process_sched", "syscall_boundary"),
    ("kmalloc", "mm/slab.c",
     """void *kmalloc(size_t size, gfp_t flags) {
    if (size > KMALLOC_MAX_CACHE_SIZE) return kmalloc_large(size, flags);
    return __kmalloc(size, flags);
}""", "memory_vm", "kernel"),
    ("user_main", "user/init.c",
     """int main(void) {
    int pid = fork();
    if(pid == 0) exec("sh", argv);
    while(1) wait(0);
}""", "user_programs", "userspace"),
    ("uservec", "arch/riscv/trampoline.S",
     """.globl uservec
uservec:
    csrw sscratch, a0
    li a0, TRAPFRAME
    sd ra, 40(a0); sd sp, 48(a0)
    ld sp, 8(a0); jr t0""", "trap_syscall", "kernel"),
    ("copy_from_user", "lib/usercopy.c",
     """int copy_from_user(void *to, const void __user *from, unsigned long n) {
    if (access_ok(from, n)) return raw_copy_from_user(to, from, n);
    return n;
}""", "runtime_common", "kernel"),
]

domain_desc = """arch_platform: 启动汇编、平台初始化、硬件驱动（uart/virtio/plic/timer等）
trap_syscall: 中断异常向量、系统调用入口分发（trap_handler/uservec等，不含具体sys_实现）
process_sched: 进程创建/调度/上下文切换（fork/exec/schedule等）
memory_vm: 内存分配、页表、虚拟内存、缺页处理
fs_storage: 文件系统、磁盘I/O、inode/dentry
sync_ipc: 锁、信号量、管道、消息、进程间通信
runtime_common: 通用库函数（string/copy/print等）
user_programs: 用户态程序、用户态库
unknown: 无法确定"""

layer_desc = """userspace: 运行在用户态的代码
syscall_boundary: sys_开头的系统调用入口函数
kernel: 内核态通用逻辑
hardware: 直接操作硬件寄存器/设备的驱动代码
unknown: 无法确定"""

nodes_text = ""
for fn, fp, code, _, _ in TEST_CASES:
    nodes_text += f"\n### {fn}\n文件: {fp}\n```c\n{code}\n```\n"

prompt = (
    "你是操作系统内核专家。根据函数名、文件路径和代码片段，对每个函数按 domain 和 layer 分类，只输出 JSON。\n\n"
    f"domain（选一个）:\n{domain_desc}\n\n"
    f"layer（选一个）:\n{layer_desc}\n\n"
    f"函数列表:{nodes_text}\n"
    '输出格式（只输出JSON，不要markdown代码块）:\n'
    '{"fn_name": {"domain": "...", "layer": "..."}, ...}'
)

print("发送请求...")
llm = build_chat_model(temperature=0)
resp = llm.invoke([HumanMessage(content=prompt)])
text = resp.content.strip()
if text.startswith("```"):
    parts = text.split("```")
    text = parts[1] if len(parts) > 1 else text
    if text.startswith("json"): text = text[4:]
predictions = json.loads(text.strip())

print(f"\n{'函数':<20} {'D_期望':<15} {'D_预测':<15} {'L_期望':<18} {'L_预测':<18} D? L?")
print("-" * 100)
dc = lc = 0
total = len(TEST_CASES)
for fn, fp, code, exp_d, exp_l in TEST_CASES:
    pred = predictions.get(fn, {})
    pd, pl = pred.get("domain","unknown"), pred.get("layer","unknown")
    d_ok, l_ok = pd == exp_d, pl == exp_l
    if d_ok: dc += 1
    if l_ok: lc += 1
    print(f"{fn:<20} {exp_d:<15} {pd:<15} {exp_l:<18} {pl:<18} {'✓' if d_ok else '✗'} {'✓' if l_ok else '✗'}")

print(f"\nDomain: {dc}/{total}={100*dc//total}%  Layer: {lc}/{total}={100*lc//total}%")
print(f"\n汇总对比:")
print(f"  embedding 名字+路径      : Domain 66%  Layer 46%")
print(f"  embedding 名字+路径+代码 : Domain 66%  Layer 60%")
print(f"  LLM       名字+路径      : Domain 80%  Layer 87%")
print(f"  LLM       名字+路径+代码 : Domain {100*dc//total}%  Layer {100*lc//total}%")
