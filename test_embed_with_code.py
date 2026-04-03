#!/usr/bin/env python3
"""
对比 embedding 分类效果：
  A. 只用 fn_name + file_path（上次测试结果 67%）
  B. 用 fn_name + file_path + code_snippet
"""
import sys, math
sys.path.insert(0, "/home/leo/OS-Agent")

# ---------------------------------------------------------------------------
# 测试用例：(fn_name, file_path, code_snippet, domain, layer)
# 代码片段是典型内核函数的真实风格代码
# ---------------------------------------------------------------------------
TEST_CASES = [
    (
        "start_kernel", "init/main.c",
        """void start_kernel(void) {
    set_task_stack_end_magic(&init_task);
    setup_arch(&command_line);
    trap_init();
    mm_init();
    sched_init();
    rest_init();
}""",
        "arch_platform", "kernel",
    ),
    (
        "sys_write", "kernel/syscall.c",
        """uint64 sys_write(void) {
    struct file *f;
    int fd = argfd(0, &f);
    uint64 p = argaddr(1);
    int n = argint(2);
    return filewrite(f, p, n);
}""",
        "trap_syscall", "syscall_boundary",
    ),
    (
        "do_fork", "kernel/fork.c",
        """long do_fork(unsigned long clone_flags, unsigned long stack_start,
          struct pt_regs *regs) {
    struct task_struct *p;
    p = copy_process(clone_flags, stack_start, regs);
    if (!IS_ERR(p)) {
        wake_up_new_task(p);
    }
    return task_pid_vnr(p);
}""",
        "process_sched", "kernel",
    ),
    (
        "schedule", "kernel/sched/core.c",
        """asmlinkage void schedule(void) {
    struct task_struct *prev, *next;
    prev = current;
    next = pick_next_task(rq, prev);
    if (likely(prev != next)) {
        context_switch(rq, prev, next);
    }
}""",
        "process_sched", "kernel",
    ),
    (
        "alloc_pages", "mm/page_alloc.c",
        """struct page *alloc_pages(gfp_t gfp_mask, unsigned int order) {
    struct page *page;
    page = __alloc_pages(gfp_mask, order, preferred_nid, NULL);
    return page;
}""",
        "memory_vm", "kernel",
    ),
    (
        "handle_mm_fault", "mm/memory.c",
        """vm_fault_t handle_mm_fault(struct vm_area_struct *vma,
        unsigned long address, unsigned int flags) {
    vm_fault_t ret;
    ret = __handle_mm_fault(vma, address, flags);
    return ret;
}""",
        "memory_vm", "kernel",
    ),
    (
        "virtio_disk_rw", "virtio/virtio_disk.c",
        """void virtio_disk_rw(struct buf *b, int write) {
    uint64 sector = b->blockno * (BSIZE / 512);
    disk.desc[idx[0]].addr = (uint64)&buf0;
    disk.desc[idx[0]].flags = VRING_DESC_F_NEXT;
    *R(VIRTIO_MMIO_QUEUE_NOTIFY) = 0;
    while(b->disk == 1) sleep(b, &disk.vdisk_lock);
}""",
        "arch_platform", "hardware",
    ),
    (
        "uart_putc", "driver/uart.c",
        """void uart_putc(int c) {
    while((ReadReg(LSR) & LSR_TX_IDLE) == 0)
        ;
    WriteReg(THR, c);
}""",
        "arch_platform", "hardware",
    ),
    (
        "trap_handler", "arch/riscv/trap.c",
        """void trap_handler(void) {
    uint64 cause = r_scause();
    if(cause == 8) {
        syscall();
    } else if(cause & 0x8000000000000000L) {
        devintr();
    } else {
        panic("unexpected trap");
    }
}""",
        "trap_syscall", "kernel",
    ),
    (
        "mutex_lock", "kernel/locking/mutex.c",
        """void mutex_lock(struct mutex *lock) {
    if (!__mutex_trylock_fast(lock))
        __mutex_lock_slowpath(lock);
}""",
        "sync_ipc", "kernel",
    ),
    (
        "sys_clone", "kernel/fork.c",
        """uint64 sys_clone(void) {
    uint64 stack;
    argaddr(0, &stack);
    return fork();
}""",
        "process_sched", "syscall_boundary",
    ),
    (
        "kmalloc", "mm/slab.c",
        """void *kmalloc(size_t size, gfp_t flags) {
    if (__builtin_constant_p(size)) {
        if (size > KMALLOC_MAX_CACHE_SIZE)
            return kmalloc_large(size, flags);
    }
    return __kmalloc(size, flags);
}""",
        "memory_vm", "kernel",
    ),
    (
        "user_main", "user/init.c",
        """int main(void) {
    printf("init: starting sh\\n");
    int pid = fork();
    if(pid == 0) {
        exec("sh", argv);
    }
    while(1) wait(0);
}""",
        "user_programs", "userspace",
    ),
    (
        "uservec", "arch/riscv/trampoline.S",
        """.globl uservec
uservec:
    csrw sscratch, a0
    li a0, TRAPFRAME
    sd ra, 40(a0)
    sd sp, 48(a0)
    ld sp, 8(a0)
    ld tp, 32(a0)
    jr t0""",
        "trap_syscall", "kernel",
    ),
    (
        "copy_from_user", "lib/usercopy.c",
        """int copy_from_user(void *to, const void __user *from, unsigned long n) {
    if (access_ok(from, n))
        return raw_copy_from_user(to, from, n);
    return n;
}""",
        "runtime_common", "kernel",
    ),
]

# ---------------------------------------------------------------------------
# 加载 embedding 模型
# ---------------------------------------------------------------------------
print("加载 Jina embedding 模型...")
try:
    from core.vectorizer import LocalEmbedder
    embedder = LocalEmbedder._get_model()
except Exception:
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer("jinaai/jina-embeddings-v2-base-code",
                                    trust_remote_code=True)
print("模型加载完成\n")

# ---------------------------------------------------------------------------
# Anchor embeddings
# ---------------------------------------------------------------------------
DOMAIN_ANCHORS = {
    "arch_platform":  "architecture platform boot startup entry assembly linker cpu mode switch hart smp init trampoline",
    "trap_syscall":   "trap exception interrupt syscall system call dispatch handler stvec scause sepc ecall irq",
    "process_sched":  "process thread task scheduler schedule context switch pcb tcb runnable sleep yield fork exec wait",
    "memory_vm":      "memory physical virtual page table allocator buddy mmap pagefault cow lazy alloc heap kalloc vma",
    "fs_storage":     "file system vfs inode dentry fat ext4 procfs block device buffer cache read write open mount",
    "sync_ipc":       "synchronize mutex spinlock semaphore futex pipe signal shared memory ipc lock condvar atomic",
    "runtime_common": "utility string format print log debug error panic assert runtime library common helper",
    "user_programs":  "user application shell userspace libc syscall wrapper test program binary",
}
LAYER_ANCHORS = {
    "userspace":        "user space application userland libc user program shell command",
    "syscall_boundary": "system call entry syscall number dispatch ecall svc swi boundary kernel entry",
    "kernel":           "kernel internal core subsystem kernel space ring0 privileged",
    "hardware":         "hardware device register mmio interrupt controller plic uart virtio driver",
}

print("计算 anchor embeddings...")
anchor_d = {d: embedder.encode(txt) for d, txt in DOMAIN_ANCHORS.items()}
anchor_l = {l: embedder.encode(txt) for l, txt in LAYER_ANCHORS.items()}

def cosine(a, b):
    import numpy as np
    a, b = a.astype(float), b.astype(float)
    denom = (a**2).sum()**0.5 * (b**2).sum()**0.5
    return float(a @ b / denom) if denom > 0 else 0.0

def classify_embed(text: str):
    vec = embedder.encode(text)
    domain = max(anchor_d, key=lambda d: cosine(vec, anchor_d[d]))
    layer  = max(anchor_l, key=lambda l: cosine(vec, anchor_l[l]))
    return domain, layer

# ---------------------------------------------------------------------------
# 测试 A：只用 fn_name + file_path
# ---------------------------------------------------------------------------
print("=" * 70)
print("A. 只用 fn_name + file_path")
print("=" * 70)
da_correct = la_correct = 0
for fn, fp, code, exp_d, exp_l in TEST_CASES:
    text = f"{fn} {fp}"
    pred_d, pred_l = classify_embed(text)
    d_ok = pred_d == exp_d
    l_ok = pred_l == exp_l
    if d_ok: da_correct += 1
    if l_ok: la_correct += 1
    print(f"{fn:<20} D:{'✓' if d_ok else '✗'}({pred_d:<15}) L:{'✓' if l_ok else '✗'}({pred_l})")
total = len(TEST_CASES)
print(f"\nDomain: {da_correct}/{total}={100*da_correct//total}%  Layer: {la_correct}/{total}={100*la_correct//total}%\n")

# ---------------------------------------------------------------------------
# 测试 B：fn_name + file_path + code_snippet
# ---------------------------------------------------------------------------
print("=" * 70)
print("B. fn_name + file_path + code_snippet")
print("=" * 70)
db_correct = lb_correct = 0
for fn, fp, code, exp_d, exp_l in TEST_CASES:
    text = f"{fn} {fp}\n{code}"
    pred_d, pred_l = classify_embed(text)
    d_ok = pred_d == exp_d
    l_ok = pred_l == exp_l
    if d_ok: db_correct += 1
    if l_ok: lb_correct += 1
    print(f"{fn:<20} D:{'✓' if d_ok else '✗'}({pred_d:<15}) L:{'✓' if l_ok else '✗'}({pred_l})")

print(f"\nDomain: {db_correct}/{total}={100*db_correct//total}%  Layer: {lb_correct}/{total}={100*lb_correct//total}%")
print(f"\n对比: A→B  Domain {100*da_correct//total}%→{100*db_correct//total}%  Layer {100*la_correct//total}%→{100*lb_correct//total}%")
