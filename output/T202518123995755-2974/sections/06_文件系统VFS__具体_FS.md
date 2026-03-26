现在我已经收集了足够的信息来编写文件系统章节的报告。让我整理所有发现并生成完整的 Markdown 报告。

基于我的分析，我现在可以生成完整的第 6 章文件系统报告。

## 第 6 章：文件系统（VFS + 具体 FS）

### VFS 架构与接口设计

NighthawkOS 实现了完整的 VFS（Virtual File System）抽象层，位于 `lib/vfs/` 目录。VFS 通过四个核心抽象来统一管理不同文件系统：

#### 1. File Trait（文件抽象）

**定义位置**: `lib/vfs/src/file.rs:50`

```rust
#[async_trait]
pub trait File: Send + Sync + DowncastSync {
    fn meta(&self) -> &FileMeta;
    async fn base_read(&self, _buf: &mut [u8], _pos: usize) -> SysResult<usize>;
    async fn base_write(&self, _buf: &[u8], _pos: usize) -> SysResult<usize>;
    fn base_load_dir(&self) -> SysResult<()>;
    fn base_readlink(&self, _buf: &mut [u8]) -> SysResult<usize>;
    fn inode(&self) -> Arc<dyn Inode>;
    fn seek(&self, ...) -> SysResult<usize>;
    // ... 更多方法
}
```

`File` trait 提供了文件操作的标准接口，包括异步读写、目录加载、符号链接读取等。每个具体文件类型（常规文件、目录、设备文件等）都需要实现此 trait。

#### 2. Inode Trait（索引节点抽象）

**定义位置**: `lib/vfs/src/inode.rs:134`

```rust
pub trait Inode: Send + Sync + DowncastSync {
    fn get_meta(&self) -> &InodeMeta;
    fn get_attr(&self) -> SysResult<Stat>;
    fn ino(&self) -> i32;
    fn inotype(&self) -> InodeType;
    fn size(&self) -> usize;
    fn check_permission(&self, euid: u32, egid: u32, groups: &[u32], access: AccessFlags) -> bool;
    // ... 更多方法
}
```

`Inode` 抽象封装了文件的元数据（权限、大小、时间戳等）和权限检查逻辑。`InodeMeta` 结构体包含：
- `ino`: 索引节点号
- `mode`: 文件类型和权限位
- `size`: 文件大小
- `nlink`: 硬链接数
- `atime/mtime/ctime`: 访问/修改/变更时间
- `uid/gid`: 所有者 ID

#### 3. Dentry Trait（目录项抽象）

**定义位置**: `lib/vfs/src/dentry.rs:59`

```rust
pub trait Dentry: Send + Sync {
    fn get_meta(&self) -> &DentryMeta;
    fn base_open(self: Arc<Self>) -> SysResult<Arc<dyn File>>;
    fn base_create(&self, dentry: &dyn Dentry, mode: InodeMode) -> SysResult<()>;
    fn base_lookup(&self, dentry: &dyn Dentry) -> SysResult<()>;
    fn base_link(&self, dentry: &dyn Dentry, old_dentry: &dyn Dentry) -> SysResult<()>;
    fn base_unlink(&self, dentry: &dyn Dentry) -> SysResult<()>;
    fn inode(&self) -> Option<Arc<dyn Inode>>;
    fn parent(&self) -> Option<Arc<dyn Dentry>>;
    // ... 更多方法
}
```

`Dentry`（Directory Entry）是路径名解析的核心数据结构，维护了目录层级关系和 inode 缓存。`DentryMeta` 包含：
- `name`: 目录项名称
- `parent`: 父目录项的弱引用
- `children`: 子目录项列表
- `inode`: 关联的 inode

#### 4. SuperBlock Trait（超级块抽象）

**定义位置**: `lib/vfs/src/superblock.rs:43`

```rust
pub trait SuperBlock: Send + Sync {
    fn meta(&self) -> &SuperBlockMeta;
    fn stat_fs(&self) -> SysResult<StatFs>;
    fn sync_fs(&self, wait: isize) -> SysResult<()>;
    fn dev_id(&self) -> u64;
}
```

`SuperBlock` 代表一个挂载的文件系统实例，`SuperBlockMeta` 包含：
- `device`: 底层块设备
- `dev_id`: 设备 ID
- `fs_type`: 文件系统类型
- `root_dentry`: 根目录项
- `inode_mapping`: inode 号到 Inode 对象的映射

### 具体文件系统支持情况（FAT32/Ext4/RamFS）

#### Ext4 文件系统实现

**实现位置**: `lib/ext4/`

Ext4 文件系统通过 `lib/ext4/src/fs.rs` 中的 `ExtFsType` 结构体实现 `FileSystemType` trait：

```rust
// lib/ext4/src/fs.rs:16-63
pub struct ExtFsType {
    meta: FileSystemTypeMeta,
}

impl FileSystemType for ExtFsType {
    fn base_mount(
        self: Arc<Self>,
        name: &str,
        parent: Option<Arc<dyn Dentry>>,
        _flags: MountFlags,
        dev: Option<Arc<dyn driver::BlockDevice>>,
    ) -> SysResult<Arc<dyn Dentry>> {
        assert!(dev.is_some());
        let meta = SuperBlockMeta::new(dev, self.clone(), 0x1);
        let superblock = ExtSuperBlock::new(meta);
        let root_dir = ExtDir::open(CString::new("/").unwrap().as_c_str())?;
        let root_inode = ExtDirInode::new(superblock.clone(), root_dir);
        root_inode.set_inotype(InodeType::Dir);
        // ... 创建根目录项并返回
    }
}
```

**架构层次**:
1. **ExtFsType** (`lib/ext4/src/fs.rs`): 实现 `FileSystemType` trait，处理挂载逻辑
2. **ExtSuperBlock** (`lib/ext4/src/superblock.rs`): 实现 `SuperBlock` trait
3. **ExtDentry** (`lib/ext4/src/dentry.rs`): 实现 `Dentry` trait
4. **ExtDirInode/ExtFileInode** (`lib/ext4/src/inode/`): 实现 `Inode` trait
5. **ExtDir/ExtFile** (`lib/ext4/src/ext/`): 底层 lwext4 库的 Rust 封装

Ext4 实现依赖于 `lwext4_rust` crate（通过 C FFI 绑定），并非纯 Rust 实现。

#### FAT32 文件系统实现

**实现位置**: `lib/fat32/`

FAT32 文件系统通过 `lib/fat32/src/fs.rs` 中的 `FatFsType` 结构体实现：

```rust
// lib/fat32/src/fs.rs:12-59
pub struct FatFsType {
    meta: FileSystemTypeMeta,
}

impl FileSystemType for FatFsType {
    fn base_mount(
        self: Arc<Self>,
        name: &str,
        parent: Option<Arc<dyn Dentry>>,
        _flags: MountFlags,
        dev: Option<Arc<dyn BlockDevice>>,
    ) -> SysResult<Arc<dyn Dentry>> {
        debug_assert!(dev.is_some());
        let sb = FatSuperBlock::new(SuperBlockMeta::new(dev, self.clone(), 0x99));
        let root_inode = FatDirInode::new(sb.clone(), sb.fs.root_dir());
        let root_dentry = FatDentry::new(name, Some(root_inode), wparent).into_dyn();
        // ... 设置根目录项并返回
    }
}
```

**架构层次**:
1. **FatFsType** (`lib/fat32/src/fs.rs`): 实现 `FileSystemType` trait
2. **FatSuperBlock** (`lib/fat32/src/superblock.rs`): 实现 `SuperBlock` trait
3. **FatDentry** (`lib/fat32/src/dentry.rs`): 实现 `Dentry` trait
4. **FatDirInode/FatFileInode** (`lib/fat32/src/inode/`): 实现 `Inode` trait
5. **FatDir/FatFile** (`lib/fat32/src/file/`): 底层 fatfs crate 的封装

FAT32 实现依赖于 `fatfs` crate。

#### RamFS/TmpFS 实现

**实现位置**: `lib/osfs/src/tmp.rs`

```rust
// lib/osfs/src/tmp.rs
pub struct TmpFsType {
    meta: FileSystemTypeMeta,
}

impl FileSystemType for TmpFsType {
    fn base_mount(...) -> SysResult<Arc<dyn Dentry>> {
        // 创建基于内存的临时文件系统
    }
}
```

TmpFS 是一个内存文件系统，使用 `lib/osfs/src/simple/` 中的简单实现：
- **SimpleFsType** (`lib/osfs/src/simple/fs.rs`): 简单的内存文件系统
- **SimpleFile** (`lib/osfs/src/simple/file.rs`): 使用 PageCache 进行数据缓存
- **SimpleDentry** (`lib/osfs/src/simple/dentry.rs`): 内存中的目录项

### 伪文件系统实现

通过 `grep_in_repo` 搜索确认，NighthawkOS 实现了多种伪文件系统：

#### 1. ProcFS（进程信息文件系统）

**实现位置**: `lib/osfs/src/proc/`

ProcFS 提供了进程和内核信息的虚拟文件系统接口：

```rust
// lib/osfs/src/proc/mod.rs:50-250
pub fn init_procfs() {
    // 创建 /proc 根目录
    // 创建 /proc/meminfo, /proc/mounts, /proc/interrupts
    // 创建 /proc/sys, /proc/kernel
    // 为每个进程创建 /proc/<pid>/status, /proc/<pid>/stat, /proc/<pid>/maps
}
```

**支持的文件**:
- `/proc/meminfo`: 内存信息
- `/proc/mounts`: 挂载点列表
- `/proc/interrupts`: 中断统计
- `/proc/<pid>/status`: 进程状态
- `/proc/<pid>/stat`: 进程统计信息
- `/proc/<pid>/maps`: 进程内存映射
- `/proc/<pid>/fd/`: 进程文件描述符
- `/proc/<pid>/exe`: 进程可执行文件链接

#### 2. DevFS（设备文件系统）

**实现位置**: `lib/osfs/src/dev/`

```rust
// lib/osfs/src/dev/mod.rs:27-69
pub struct DevFsType {
    meta: FileSystemTypeMeta,
}

impl FileSystemType for DevFsType {
    fn base_mount(...) -> SysResult<Arc<dyn Dentry>> {
        // 创建设备文件：/dev/null, /dev/zero, /dev/tty, 等
    }
}
```

**支持的设备文件**:
- `/dev/null`: 空设备
- `/dev/zero`: 零源设备
- `/dev/full`: 满设备（写入总是失败）
- `/dev/tty`: 终端设备（TTY0, TTY1, TTY2）
- `/dev/urandom`: 随机数生成器
- `/dev/rtc`: 实时时钟
- `/dev/loopX`: 回环设备

#### 3. SysFS（系统文件系统）

**实现位置**: `lib/osfs/src/sys/`

SysFS 提供了内核和硬件信息的虚拟文件系统：
- `/sys/kernel/`: 内核参数
- `/sys/fs/`: 文件系统信息
- `/sys/devices/`: 设备信息

#### 4. EtcFS 和 VarFS

- **EtcFS** (`lib/osfs/src/etc/`): `/etc` 配置文件系统
- **VarFS** (`lib/osfs/src/var/`): `/var` 变量数据文件系统

### 文件描述符与进程关联

**实现位置**: `lib/osfs/src/fd_table.rs`

文件描述符表采用 **Per-Process** 设计，每个任务（Task）拥有独立的 `FdTable`：

```rust
// lib/osfs/src/fd_table.rs:30-45
#[derive(Clone)]
pub struct FdTable {
    table: Vec<Option<FdInfo>>,
    rlimit: RLimit,
    tid: Tid,
}

pub struct FdInfo {
    file: Arc<dyn File>,
    flags: FdFlags,
}
```

**关键特性**:
- `FdTable` 是一个 `Vec<Option<FdInfo>>`，索引即为文件描述符编号
- 默认预分配 3 个文件描述符：STDIN (TTY0), STDOUT (TTY1), STDERR (TTY2)
- 最大文件描述符数量由 `config::fs::MAX_FDS` 控制
- 支持 `FD_CLOEXEC` 标志（进程 exec 时自动关闭）

**文件描述符分配流程** (`lib/osfs/src/fd_table.rs`):
```rust
pub fn alloc(&mut self, file: Arc<dyn File>, flags: OpenFlags) -> SysResult<Fd> {
    // 查找第一个空闲的 FD 槽位
    // 创建 FdInfo 并插入
    // 返回 FD 编号
}
```

### 管道 (Pipe) 与套接字 (Socket) 支持情况

#### Pipe 实现

**实现位置**: `lib/osfs/src/pipe/`

✅ **已实现** - NighthawkOS 实现了完整的匿名管道支持：

```rust
// lib/osfs/src/pipe/mod.rs
pub fn new_pipe(capacity: usize) -> (Arc<PipeRead>, Arc<PipeWrite>) {
    let pipe_inode = Arc::new(PipeInode::new(capacity));
    let read = Arc::new(PipeRead { pipe: pipe_inode.clone() });
    let write = Arc::new(PipeWrite { pipe: pipe_inode });
    (read, write)
}
```

**系统调用**: `sys_pipe2` (`kernel/src/syscall/fs.rs:1030`)

```rust
pub async fn sys_pipe2(pipefd: usize, flags: i32) -> SyscallResult {
    let task = current_task();
    let flags = OpenFlags::from_bits(flags).unwrap();
    let (pipe_read, pipe_write) = new_pipe(PIPE_BUF_LEN);
    let pipe = task.with_mut_fdtable(|table| {
        let fd_read = table.alloc(pipe_read, flags)?;
        let fd_write = table.alloc(pipe_write, flags)?;
        Ok([fd_read as u32, fd_write as u32])
    })?;
    // 将 FD 写入用户空间
}
```

**Pipe 架构**:
- **PipeInode** (`lib/osfs/src/pipe/inode.rs`): 使用环形缓冲区（RingBuffer）实现
- **PipeRead** (`lib/osfs/src/pipe/read.rs`): 实现 `File` trait 的读端
- **PipeWrite** (`lib/osfs/src/pipe/write.rs`): 实现 `File` trait 的写端
- **PIPE_BUF_LEN**: 管道缓冲区大小（通常为 4KB 或 64KB）

#### Socket 实现

**实现位置**: `kernel/src/net/` 和 `lib/net/`

✅ **已实现** - NighthawkOS 实现了完整的 Socket 支持：

```rust
// kernel/src/net/socket.rs:17-30
pub struct Socket {
    pub types: SocketType,  // STREAM, DGRAM, RAW
    pub sk: Sock,           // TcpSocket, UdpSocket, UnixSocket
    // ... 文件元数据
}

pub enum Sock {
    Tcp(TcpSocket),
    Udp(UdpSocket),
    Unix(Arc<UnixSocket>),
}
```

**支持的 Socket 类型**:
1. **TCP Socket** (`kernel/src/net/tcp/`): 面向连接的流式套接字
2. **UDP Socket** (`lib/net/udp.rs`): 无连接的数据报套接字
3. **Unix Domain Socket** (`kernel/src/net/unix.rs`): 本地进程间通信

**系统调用** (`kernel/src/syscall/net.rs`):
- `sys_socket`: 创建套接字
- `sys_bind`: 绑定地址
- `sys_connect`: 连接远程地址
- `sys_listen`: 监听连接
- `sys_accept`: 接受连接
- `sys_sendto`/`sys_recvfrom`: 发送/接收数据
- `sys_setsockopt`/`sys_getsockopt`: 套接字选项

**网络栈集成**:
- 使用 `smoltcp` crate 作为 TCP/IP 协议栈
- 支持 VirtIO 网络设备驱动 (`lib/driver/src/net/virtnet.rs`)
- 支持回环设备 (`lib/driver/src/net/loopback.rs`)

### 缓存机制（Block/Page Cache）

**实现位置**: `lib/mm/src/page_cache/`

NighthawkOS 实现了 Page Cache 机制来缓存文件数据：

```rust
// lib/mm/src/page_cache/mod.rs:12-70
pub struct PageCache {
    pages: SpinNoIrqLock<BTreeMap<usize, Arc<Page>>>,
}

impl PageCache {
    pub fn get_page(&self, offset: usize) -> Option<Arc<Page>> {
        self.pages.lock().get(&offset).cloned()
    }

    pub fn insert_page(&self, offset: usize, page: Arc<Page>) {
        self.pages.lock().insert(offset, page);
    }

    pub fn create_page(&self, offset: usize, data: &[u8], page_offset: usize) -> SysResult<Arc<Page>> {
        let page = Arc::new(Page::build()?);
        // 复制数据到页面
        self.insert_page(offset, page.clone());
    }
}
```

**Page Cache 集成到 VFS**:

在 `lib/vfs/src/file.rs` 中，`File` trait 提供了基于 Page Cache 的读写方法：

```rust
// lib/vfs/src/file.rs:294-330
async fn read_through_page_cache(&self, mut buf: &mut [u8], pos: usize) -> SysResult<usize> {
    let inode = self.inode();
    let page_cache = inode.page_cache();
    let pos = pos / PAGE_SIZE * PAGE_SIZE;
    
    if let Some(page) = page_cache.get_page(pos) {
        // 从缓存读取
    } else {
        // 从磁盘读取并缓存
        let page = self.read_page(pos).await?;
        page_cache.insert_page(pos, Arc::clone(&page));
    }
}
```

**写时复制 (CoW) 支持**:

对于 `MAP_PRIVATE` 的 mmap 映射，Page Cache 支持写时复制：
1. 首次读取时，页面映射到 Page Cache 中的页面
2. 首次写入时，触发 CoW 页故障，分配新页面并复制数据
3. 后续写入直接修改新页面，不影响 Page Cache

### 零拷贝映射验证（mmap 实现分析）

**实现位置**: `kernel/src/syscall/mm.rs` 和 `kernel/src/vm/vm_area.rs`

#### sys_mmap 系统调用

✅ **已实现** - NighthawkOS 实现了完整的 mmap 支持，包括共享映射：

```rust
// kernel/src/syscall/mm.rs:59-127
pub async fn sys_mmap(
    addr: usize,
    length: usize,
    prot: i32,
    flags: i32,
    fd: isize,
    offset: usize,
) -> SyscallResult {
    let task = current_task();
    let flags = MmapFlags::from_bits_truncate(flags);
    let prot = MmapProt::from_bits_truncate(prot);
    
    // 获取文件对象（如果不是匿名映射）
    let file = if !flags.contains(MmapFlags::MAP_ANONYMOUS) {
        let f = task.with_mut_fdtable(|table| table.get_file(fd as usize))?;
        // 检查 memfd seal 权限
        if let Some(memf) = f.clone().downcast_arc::<MemFile>().ok() {
            if memf.seals().contains(MemfdSeals::WRITE)
                && prot.contains(MmapProt::PROT_WRITE)
                && flags.contains(MmapFlags::MAP_SHARED)
            {
                return Err(SysError::EPERM);
            }
        }
        Some(f)
    } else {
        None
    };

    // 调用地址空间的 map_file 方法
    task.addr_space().map_file(
        file,
        flags,
        MappingFlags::from(prot),
        va,
        length,
        offset,
        seals,
    )
}
```

#### VmArea 的共享映射支持

**定义位置**: `kernel/src/vm/vm_area.rs:145-155`

```rust
bitflags! {
    pub struct VmaFlags: u8 {
        const SHARED = 1 << 0;    // ✅ 共享映射标志
        const PRIVATE = 1 << 1;   // 私有映射标志
    }
}
```

**FileBackedArea 结构** (`kernel/src/vm/vm_area.rs:900-910`):

```rust
pub struct FileBackedArea {
    file: Arc<dyn File>,      // 后端文件
    offset: usize,            // 页对齐的文件偏移
    len: usize,               // 映射区域长度
    seals: Option<MemfdSeals>, // memfd 密封标志
}
```

#### 共享映射的页故障处理

**关键代码** (`kernel/src/vm/vm_area.rs:958-1030`):

```rust
fn fault_handler(area: &mut VmArea, info: PageFaultInfo) -> SysResult<()> {
    let FileBackedArea { ref file, offset, .. } = area.map_type;
    let file_offset = offset + area_offset;
    
    // 从 Page Cache 读取页面
    let cached_page = block_on(async { file.read_page(file_offset).await })?;

    let page = if flags.contains(VmaFlags::PRIVATE) && access == MappingFlags::W {
        // 私有写映射：执行 CoW
        let page = Page::build()?;
        page.copy_from_page(&cached_page);
        Arc::new(page)
    } else {
        // 共享映射或只读映射：直接使用 Page Cache 中的页面
        if flags.contains(VmaFlags::PRIVATE) {
            // 私有读映射：移除写权限
            pte_flags = pte_flags.difference(PteFlags::W);
        }
        cached_page  // ✅ 共享映射直接引用 Page Cache 页面
    };
    
    page_table.map_page_to(fault_addr.page_number(), page.ppn(), pte_flags)?;
    area.pages.insert(fault_addr.page_number(), page);
    Ok(())
}
```

**零拷贝验证结论**:

✅ **已实现真正的零拷贝共享映射**：
1. `VmArea` 结构体包含 `flags: VmaFlags`，其中 `SHARED` 标志明确表示共享映射
2. `sys_mmap` 正确处理 `MAP_SHARED` 标志，并传递给 `map_file`
3. 页故障处理中，共享映射直接使用 `cached_page`（来自 Page Cache），不创建副本
4. 多个进程映射同一文件时，共享同一个 Page Cache 页面，实现零拷贝
5. 写时复制 (CoW) 仅对 `MAP_PRIVATE` 映射生效

#### 高级内存映射特性

**Memfd 支持** (`lib/osfs/src/special/memfd/`):
- ✅ 支持 `memfd_create` 系统调用创建匿名文件
- ✅ 支持 `F_ADD_SEALS`/`F_GET_SEALS` 进行写保护
- ✅ 支持 `memfd` 的共享映射和 seal 检查

**Shared Memory (shmget/shmat)** (`kernel/src/syscall/mm.rs`):
- ✅ 支持 System V 共享内存
- ✅ `SharedMemoryArea` 使用 `ShareMutex<SharedMemory>` 管理共享页面

### 关键代码验证

#### 文件打开流程追踪

通过 `lsp_get_call_graph` 分析 `sys_openat` 的调用链：

```
sys_openat (kernel/src/syscall/fs.rs:123)
├── task.walk_at(AtFd::from(dirfd), path)  // 路径解析
│   └── Path::walk_recursive()  (lib/vfs/src/path.rs:102)
│       ├── Dentry::lookup()  // 查找目录项
│       └── resolve_symlink_recursive()  // 符号链接解析
├── dentry.inode().check_permission()  // 权限检查
├── <dyn File>::open(dentry)  (lib/vfs/src/file.rs:214)
│   └── dentry.base_open()  // 调用具体文件系统的 open
└── task.with_mut_fdtable(|ft| ft.alloc(file, flags))  // 分配 FD
```

**完整流程**:
1. **路径解析**: `task.walk_at()` 调用 `Path::walk_recursive()` 解析路径名到 `Dentry`
2. **符号链接处理**: 如果是符号链接且未指定 `O_NOFOLLOW`，调用 `resolve_symlink_through()`
3. **文件创建**: 如果指定 `O_CREAT` 且文件不存在，调用 `parent.create()`
4. **权限检查**: 调用 `inode.check_permission()` 验证访问权限
5. **截断处理**: 如果指定 `O_TRUNC`，调用 `inode.set_size(0)`
6. **File 对象创建**: `<dyn File>::open(dentry)` 调用具体文件系统的 `base_open()`
7. **FD 分配**: `fd_table.alloc()` 分配文件描述符并返回

#### 四大核心数据结构协同

1. **SuperBlock**: 代表挂载的文件系统实例，通过 `dev_id` 标识设备
2. **Dentry**: 路径名解析的中间结果，维护目录树结构和 inode 缓存
3. **Inode**: 文件元数据和操作接口，通过 `ino` 唯一标识
4. **File**: 打开的文件实例，包含文件指针位置 (`pos`) 和打开标志 (`flags`)

**协同流程示例** (打开 `/home/user/test.txt`):
```
1. 从根 SuperBlock 的 root_dentry 开始
2. 查找 "home" Dentry → 获取其 Inode → 创建 File
3. 在 "home" Dentry 中查找 "user" Dentry
4. 在 "user" Dentry 中查找 "test.txt" Dentry
5. 获取 "test.txt" Inode，创建 File 对象
6. 在进程 FdTable 中分配 FD，返回给用户
```

### 功能实现状态总结

| 功能 | 状态 | 说明 |
|------|------|------|
| **VFS 抽象层** | ✅ 已实现 | File/Inode/Dentry/SuperBlock 四大 trait |
| **Ext4 文件系统** | ✅ 已实现 | 通过 lwext4_rust 封装，完整实现 VFS 接口 |
| **FAT32 文件系统** | ✅ 已实现 | 通过 fatfs crate 封装，完整实现 VFS 接口 |
| **TmpFS/RamFS** | ✅ 已实现 | `lib/osfs/src/simple/` 和 `tmp.rs` |
| **ProcFS** | ✅ 已实现 | `/proc/<pid>/status`, `/proc/meminfo` 等 |
| **DevFS** | ✅ 已实现 | `/dev/null`, `/dev/zero`, `/dev/tty` 等 |
| **SysFS** | ✅ 已实现 | `/sys/kernel/`, `/sys/fs/` 等 |
| **文件描述符表** | ✅ 已实现 | Per-Process FdTable，支持 FD_CLOEXEC |
| **Pipe 管道** | ✅ 已实现 | 匿名管道，环形缓冲区实现 |
| **Socket 套接字** | ✅ 已实现 | TCP/UDP/Unix Domain Socket |
| **mmap 映射** | ✅ 已实现 | 支持 MAP_SHARED/MAP_PRIVATE，零拷贝 |
| **Page Cache** | ✅ 已实现 | BTreeMap 缓存页面，支持 CoW |
| **poll/epoll** | ✅ 已实现 | `sys_epoll_create1/ctl/pwait` |

**文档提及但需验证的功能**:
- 无（所有核心功能均已找到代码实现）

**未实现功能**:
- ❌ `kill_sblk` 文件系统卸载：在 `FatFsType` 和 `ExtFsType` 中均为 `todo!()`
