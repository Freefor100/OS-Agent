## 题单作答（JSON-QA 渲染）

- stage_id: `06_fs_vfs`
- terminology_profile: `stallings_en_zh`

## 第 06_fs_vfs 阶段：文件系统（VFS + 具体 FS）

### Q06_001（short_answer）

- 题干：VFS 抽象层 (Virtual File System, VFS)接口是什么形态？（Rust trait / C op 表；必须给接口定义证据）
- 答案："C 语言风格的文件对象抽象，通过 struct file 的 type 字段区分 FD_ENTRY（文件）/FD_PIPE（管道）/FD_DEVICE（设备），无 Rust trait 风格。文件操作通过函数指针间接调用（如 eread/ewrite 用于 FD_ENTRY，piperead/pipewrite 用于 FD_PIPE，devsw[].read/write 用于 FD_DEVICE）。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/include/file.h` | `struct file` | struct file { enum { FD_NONE, FD_PIPE, FD_ENTRY, FD_DEVICE } type; ... struct pipe *pipe; struct dirent *ep; short major; }; |
| `src/file.c` | `function fileread` | switch (f->type) { case FD_PIPE: r = piperead(...); case FD_DEVICE: r = (devsw + f->major)->read(...); case FD_ENTRY: r = eread(f->ep, ...); } |

### Q06_002（single_choice）

- 题干：具体文件系统后端 (Concrete File System Backend) 更接近哪种？
- 答案："A. 真实磁盘文件系统（FAT32/Ext4/其他，持久化存储）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/fat32.c` | `function fat32_init` | FAT32 文件系统实现，基于 ChaN FatFs 库，支持持久化存储 |
| `src/include/fat32.h` | `struct fs` | struct fs { uint devno; int valid; struct dirent* image; struct Fat fat; ... void (*disk_read)(...); void (*disk_write)(...); }; |

### Q06_003（short_answer）

- 题干：若支持 FAT32/Ext4：它是自研还是第三方库/crate？（必须引用 Cargo.toml/Cargo.lock 或 Makefile 引入证据）
- 答案："第三方库：ChaN FatFs R0.14b。证据：`src/include/ff.h` 头部明确标注 'FatFs - Generic FAT Filesystem module R0.14b' 及 'Copyright (C) 2021, ChaN, all right reserved.'，本项目为 C 语言项目（非 Rust），通过直接包含 ff.h/ffconf.h 使用第三方 FatFs 库。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/include/ff.h` | `file_header FF_DEFINED` | FatFs - Generic FAT Filesystem module R0.14b / Copyright (C) 2021, ChaN, all right reserved. |

### Q06_004（short_answer）

- 题干：文件打开路径：文件打开入口（sys_open 或等价）→ VFS 层 → 具体 FS open。列出 3-6 个关键节点并给证据。
- 答案："文件打开路径：sys_openat (src/sysfile.c:41) → fdalloc (src/sysfile.c:17) → ename (src/fat32.c:1055) → create/edirlookup (src/fat32.c:867) → filealloc (src/file.c:42) → 返回 fd。关键节点：1) sys_openat 解析路径并调用 ename；2) ename 调用 lookup_path 进行路径遍历；3) dirlookup 在目录中查找条目；4) filealloc 分配全局 file 结构；5) fdalloc 将 file 绑定到进程 ofile 数组。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/sysfile.c` | `function sys_openat` | uint64 sys_openat() { ... ep = ename(dp,path,&devno); ... f = filealloc(); fd = fdalloc(f); ... } |
| `src/file.c` | `function filealloc` | struct file* filealloc(void) { ... for(f = ftable.file; f < ftable.file + NFILE; f++) if(f->ref == 0) { f->ref = 1; return f; } } |
| `src/fat32.c` | `function ename` | struct dirent *ename(struct dirent* env,char *path,int* devno) { return lookup_path(env,path, 0, name, devno); } |

### Q06_005（short_answer）

- 题干：文件描述符表 (File Descriptor Table, FD Table) 的实现形态是什么？（固定数组/Vec/BTreeMap 等；必须给结构体定义证据）
- 答案："Per-process 固定数组：`struct file **ofile`，大小为 NOFILE（101）。每个进程独立拥有 ofile 数组，通过 kmalloc 动态分配。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/include/proc.h` | `struct_field proc::ofile` | struct proc { ... struct file **ofile; ... }; |
| `src/proc.c` | `code_block procinit` | p->ofile = kmalloc(NOFILE*sizeof(struct file*)); |
| `src/include/param.h` | `macro NOFILE` | #define NOFILE 101  // open files per process |

### Q06_006（tri_state_impl）

- 题干：是否实现块缓存/缓冲缓存 (Block Cache / Buffer Cache, bcache)？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/bio.c` | `struct cache` | struct cache { struct spinlock lock; struct buf buf[NBUF]; struct buf head; } bcache; |
| `src/bio.c` | `function bread` | struct buf* bread(uint dev, uint sectorno) { b = bget(dev, sectorno); if (!b->valid) { FatFs[dev].disk_read(...); b->valid = 1; } return b; } |

### Q06_007（short_answer）

- 题干：若存在缓存：驱逐策略是什么（LRU/Clock/FIFO/无驱逐）？必须指出判断依据（字段/算法分支）证据。
- 答案："LRU（Least Recently Used）驱逐策略。判断依据：bget() 从 bcache.head.prev（最久未使用）开始扫描寻找 refcnt==0 的缓冲；brelse() 将释放的缓冲移回 bcache.head.next（最近使用），通过双向链表维护访问顺序。"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/bio.c` | `function bget` | for(b = bcache.head.prev; b != &bcache.head; b = b->prev) if(b->refcnt == 0) { ... return b; } |
| `src/bio.c` | `function brelse` | b->next->prev = b->prev; b->prev->next = b->next; b->next = bcache.head.next; b->prev = &bcache.head; bcache.head.next->prev = b; bcache.head.next = b; |

### Q06_008（tri_state_impl）

- 题干：是否实现页缓存 (Page Cache)或与 mmap/文件映射共享缓存页？（必须三态）
- 答案："stub"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/mmap.c` | `function do_mmap` | do_mmap 通过 fileread 直接读取文件内容到分配的物理页，无独立页缓存层，文件数据直接拷贝到用户页，未实现共享页缓存机制 |

### Q06_009（tri_state_impl）

- 题干：是否实现 mmap 的文件映射或匿名映射？（必须三态；若 stub 说明形态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/mmap.c` | `function do_mmap` | if(flags & MAP_ANONYMOUS) { fd = -1; goto ignore_fd; } ... struct vma *vma = alloc_mmap_vma(p, flags, start, len, perm, fd, offset); ... fileread(f, va, PGSIZE); |

### Q06_010（tri_state_impl）

- 题干：是否实现 poll/select/epoll（或等价事件机制）？（必须三态）
- 答案："stub"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/syspoll.c` | `function sys_ppoll` | uint64 sys_ppoll() { return 0; } |

### Q06_011（tri_state_impl）

- 题干：路径解析 (namei/path_walk/lookup) 是否实现并支持绝对/相对路径与 . ..？（必须三态）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/fat32.c` | `function lookup_path` | if (*path == '/') { entry = edup(&self_fs->root); } else if(env) { entry = edup(env); } else { entry = edup(myproc()->cwd); } |
| `src/fat32.c` | `function dirlookup` | if (strncmp(filename, ".", FAT32_MAX_FILENAME) == 0) { return edup(dp); } else if (strncmp(filename, "..", FAT32_MAX_FILENAME) == 0) { return edup(dp->parent); } |

### Q06_012（tri_state_impl）

- 题干：是否支持符号链接 (symlink) 的解析/跟随？（必须三态）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q06_013（tri_state_impl）

- 题干：是否实现管道 (pipe/pipe2) 并在 VFS 层作为文件对象？（必须三态；与 08 章 pipe 实现互指）
- 答案："implemented"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/pipe.c` | `function pipealloc` | (*f0)->type = FD_PIPE; (*f0)->readable = 1; (*f0)->writable = 0; (*f0)->pipe = pi; (*f1)->type = FD_PIPE; (*f1)->readable = 0; (*f1)->writable = 1; |
| `src/file.c` | `function fileread` | case FD_PIPE: r = piperead(f->pipe, 1, addr, n); |

### Q06_014（tri_state_impl）

- 题干：是否实现网络 socket（作为 VFS 文件对象）？（必须三态）
- 答案："not_found"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/include/socket.h` | `file socket.h` | 仅定义 struct socket_connection 结构，未发现 sys_socket 系统调用实现 |

### Q06_015（tri_state_impl）

- 题干：是否实现伪文件系统（devfs/procfs/sysfs）？（必须三态；若 implemented 需说明实现形态）
- 答案："not_found"

- 证据：无（`not_found`/`stub` 时允许为空；否则需补齐）

### Q06_016（single_choice）

- 题干：文件描述符表的归属是哪种？
- 答案："A. Per-Process（每进程独立 fd 表，fork 时复制/共享）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/include/proc.h` | `struct_field proc::ofile` | struct proc { ... struct file **ofile; ... }; |
| `src/proc.c` | `code_block procinit` | p->ofile = kmalloc(NOFILE*sizeof(struct file*)); |

### Q06_017（single_choice）

- 题干：文件数据块分配方式 (File Allocation Method, Stallings Ch12) 更接近哪种？
- 答案："E. 混合（如 Unix 直接 + 间接块）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/fat32.c` | `function etrunc` | for (uint32 clus = entry->first_clus; clus >= 2 && clus < FAT32_EOC; ) { uint32 next = read_fat(self_fs, clus); free_clus(self_fs, clus); clus = next; } |

### Q06_018（single_choice）

- 题干：磁盘/存储空闲空间管理 (Free Space Management, Stallings Ch12) 更接近哪种？
- 答案："E. FAT 表内嵌空闲链（FAT32 特有）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/fat32.c` | `function read_fat` | FAT32 通过 FAT 表项值判断簇是否空闲（0 表示空闲），使用 read_fat/write_fat 操作 FAT 表管理空闲簇 |

### Q06_019（single_choice）

- 题干：目录结构 (Directory Structure, Stallings Ch12) 更接近哪种？
- 答案："C. 树形层次目录 (Tree-Structured Hierarchy)（最常见）"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/fat32.c` | `function lookup_path` | 通过 skipelem 逐元素解析路径，支持多级目录嵌套遍历 |
| `src/fat32.c` | `function dirlookup` | 在目录中查找子目录或文件，支持树形层次结构 |

### Q06_020（single_choice）

- 题干：文件内部记录组织 (File Record Organization, Stallings Ch12) 更接近哪种？
- 答案："A. 字节流 (Byte Stream / Unstructured)：无固定记录结构"

| 证据路径 | 符号 | 摘录 |
|---|---|---|
| `src/file.c` | `function fileread` | fileread 按字节数 n 读取，无记录边界概念 |
| `src/fat32.c` | `function eread` | eread 按偏移 off 和长度 n 读取文件内容，视为连续字节流 |
