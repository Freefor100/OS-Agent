# Taxonomy V3

必写模块：

- `build-runtime`
- `boot-trap-syscall`
- `process-exec`
- `memory-vm`
- `fs-io`
- `device-platform`
- `network-stack`
- `smp-concurrency`
- `user-abi-compat`
- `test-risk-surface`

network、page cache、ext4、SMP/multicore 都是 required，不是 optional。

彻底删除的功能：namespace、cgroup、RCU、netfilter、Unix domain socket、dynamic linker、VDSO、module loader、seccomp、KASLR、stack protector、module signature、perf counter、GDB stub、sanitizer、virtualization。
