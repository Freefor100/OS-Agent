## 内存管理实现对比报告：oskernel2023-zmz vs oskernrl2022-rv6

---

## 分配器差异

### 物理内存分配器

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **算法类型** | 链表式空闲列表（Free List） | 链表式空闲列表（Free List） |
| **实现位置** | `kernel/mm/pm.c` | `src/pm.c` |
| **数据结构** | 双分配器设计：`struct pm_allocator`（multiple + single 双池） | 单分配器设计：`struct { spinlock; run* freelist; } kmem` |
| **分配策略** | 优先从 single 池（高地址 400 页预留池）分配，失败后回退到 multiple 池 | 直接从单一空闲链表分配 |
| **外部 crate** | ❌ 无，内部实现 | ❌ 无，内部实现 |

**oskernel2023-zmz 双池设计代码证据**（`kernel/mm/pm.c:31-38`）：
```c
struct pm_allocator {
    struct spinlock lock;
    struct run *freelist;
    uint64 npage;
};
struct pm_allocator multiple;  // 多页分配器
struct pm_allocator single;    // 单页分配器
#define SINGLE_PAGE_NUM 400
```

**oskernrl2022-rv6 单池设计代码证据**（`src/pm.c:31-35`）：
```c
struct {
  struct spinlock lock;
  struct run *freelist;
  uint64 npage;
} kmem;
```

**【创新点】** oskernel2023-zmz 采用**双池优化设计**，通过分离单页预留池减少锁竞争，这是 oskernrl2022-rv6 未实现的优化策略。

---

### 内核堆分配器（kmalloc）

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **算法类型** | 类 Slab 分配器 | 类 Slab 分配器 |
| **实现位置** | `kernel/mm/kmalloc.c` | `src/kmalloc.c` |
| **分配范围** | 32B - 4048B | 32B - 4048B |
| **对齐方式** | 16 字节对齐 | 16 字节对齐 |
| **哈希表大小** | 17 桶 (`KMEM_TABLE_SIZE = 17`) | 17 桶 |
| **核心结构** | `struct kmem_node` + `struct kmem_allocator` | `struct kmem_node` + `struct kmem_allocator` |

**代码相似度分析**：两个项目的 kmalloc 实现**高度相似**，数据结构字段名几乎一致：

```c
// oskernel2023-zmz: kernel/mm/kmalloc.c:37-52
struct kmem_node {
    struct kmem_node *next;
    struct { uint64 obj_size; uint64 obj_addr; } config;
    uint8 avail; uint8 cnt; uint8 table[KMEM_OBJ_MAX_COUNT];
};

// oskernrl2022-rv6: src/kmalloc.c:17-40
struct kmem_node {
  struct kmem_node *next;
  struct { uint64 obj_size; uint64 obj_addr; } config;
  uint8 avail; uint8 cnt; uint8 table[KMEM_OBJ_MAX_COUNT];
};
```

**结论**：两个项目的内核堆分配器**设计思路相同且代码高度相似**，可能源自同一代码基线。

---

## 页表差异

### 页表架构对比

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **页表级别** | Sv39 三级页表 | Sv39 三级页表 |
| **页大小** | 4096 字节 (4KB) | 4096 字节 (4KB) |
| **pagetable_t 定义** | `typedef uint64 *pagetable_t` | `typedef uint64 *pagetable_t` |
| **PTE 标志位** | PTE_V/R/W/X/U + **PTE_RSW1/PTE_RSW2** | PTE_V/R/W/X/U/G/A/D + PTE_RSW1/PTE_RSW2 |
| **特殊标志** | **PTE_COW = PTE_RSW1**（用于写时复制） | 无 COW 标志 |
| **页表操作函数** | `walk()`, `mappages()`, `vmunmap()` | `walk()`, `mappages()`, `vmunmap()` |

**oskernel2023-zmz PTE 定义**（`include/hal/riscv.h:384-399`）：
```c
#define PTE_V (1L << 0)
#define PTE_R (1L << 1)
#define PTE_W (1L << 2)
#define PTE_X (1L << 3)
#define PTE_U (1L << 4)
#define PTE_RSW1 (1L << 8)  // reserved for supervisor software 1
#define PTE_COW PTE_RSW1    // 用于 CoW 标记 (kernel/mm/vm.c:22)
```

**oskernrl2022-rv6 PTE 定义**（`src/include/riscv.h:345-360`）：
```c
#define PTE_V (1L << 0)
#define PTE_R (1L << 1)
#define PTE_W (1L << 2)
#define PTE_X (1L << 3)
#define PTE_U (1L << 4)
#define PTE_G (1L << 5)   // Global
#define PTE_A (1L << 6)   // Accessed
#define PTE_D (1L << 7)   // Dirty
```

**关键差异**：
1. oskernel2023-zmz 使用 `PTE_RSW1` 作为 **COW 标记位**
2. oskernrl2022-rv6 定义了 `PTE_G/A/D` 标志，但未在核心逻辑中使用

---

### 关键结构体对比

#### MemorySet / VmArea 管理结构

| 结构体 | oskernel2023-zmz | oskernrl2022-rv6 |
|--------|------------------|------------------|
| **名称** | `struct seg` | `struct vma` |
| **定义位置** | `include/mm/usrmm.h:10-18` | `src/include/vma.h:14-24` |
| **字段** | `type, flag, addr, sz, next, mmap, f_off, f_sz` | `type, perm, addr, sz, end, flags, fd, f_off, prev, next` |
| **链表类型** | 单向链表 (`next` 指针) | **双向链表** (`prev` + `next` 指针) |
| **MMAP 元数据** | `uint64 mmap`（存储映射元数据指针） | `int fd` + `uint64 f_off`（直接存储文件描述符） |

**oskernel2023-zmz struct seg**（`include/mm/usrmm.h:10-18`）：
```c
struct seg{
    enum segtype type;
    int flag;
    uint64 addr;
    uint64 sz;
    struct seg *next;      // 单向链表
    uint64 mmap;           // MMAP 元数据指针
    uint64 f_off;
    uint64 f_sz;
};
```

**oskernrl2022-rv6 struct vma**（`src/include/vma.h:14-24`）：
```c
struct vma {
    enum segtype type;
    int perm;
    uint64 addr;
    uint64 sz;
    uint64 end;            // 额外字段：结束地址
    int flags;
    int fd;                // 文件描述符
    uint64 f_off;
    struct vma *prev;      // 双向链表
    struct vma *next;
};
```

**差异分析**：
- oskernrl2022-rv6 的 `struct vma` 多了一个 `end` 字段，便于快速判断区间边界
- oskernrl2022-rv6 采用双向链表，删除操作更高效
- oskernel2023-zmz 使用 `mmap` 指针间接管理 MMAP 元数据，支持更复杂的共享映射场景

---

## Call Graph 差异

### handle_page_fault 调用链对比

**对比命令**：`compare_call_graphs(oskernel2023-zmz, oskernrl2022-rv6, "handle_page_fault")`

| 项目 | handle_page_fault 实现状态 | 调用子函数 |
|------|---------------------------|-----------|
| **oskernel2023-zmz** | ✅ 已实现 (`kernel/mm/vm.c:1025`) | `handle_page_fault_lazy`, `handle_page_fault_loadelf`, `handle_page_fault_mmap`, `handle_store_page_fault_cow`, `walk`, `locateseg` |
| **oskernrl2022-rv6** | ❌ **未实现**（仅头文件声明） | 无 |

**oskernel2023-zmz 完整调用链**：
```
handle_page_fault (kernel/mm/vm.c:1025)
├── locateseg()                    # 查找 segment
├── walk()                         # 获取 PTE
├── handle_store_page_fault_cow()  # CoW 处理
│   ├── monopolizepage()           # 检查引用计数
│   ├── allocpage() + memmove()    # 复制页面
│   └── sfence_vma()
├── handle_page_fault_lazy()       # 懒分配
│   └── uvmalloc() → allocpage()
├── handle_page_fault_loadelf()    # ELF 懒加载
│   └── loadseg()
└── handle_page_fault_mmap()       # MMAP 按需映射
    ├── handle_anonymous_shared()
    └── handle_file_mmap()
```

**oskernrl2022-rv6 状态**：
- 头文件 `src/include/vm.h:42-43` 声明了 `handle_page_fault()` 和 `kernel_handle_page_fault()`
- **但在 `.c` 文件中未找到实现**
- `src/trap.c:102` 中缺页异常处理被注释掉：
  ```c
  /* else if(handle_excp(cause) == 0) { } */
  ```
- 未知异常直接导致进程 `SIGTERM` 退出

**Call Graph Jaccard 相似度**: 0.000（0 共同节点 / 30 全集节点）

**结论**：oskernel2023-zmz 实现了**完整的缺页异常处理链路**，支持 CoW、Lazy Allocation、ELF 懒加载、MMAP 按需分页；而 oskernrl2022-rv6 **完全未实现缺页异常处理**，所有用户页面必须预先分配。

---

## 高级特性对比表

| 特性 | oskernel2023-zmz | oskernrl2022-rv6 | 差异说明 |
|------|------------------|------------------|----------|
| **写时复制（CoW）** | ✅ 已实现 | ❌ 未实现 | oskernel2023-zmz 在 `fork()` 时标记 COW 页，缺页时复制；oskernrl2022-rv6 直接深拷贝 |
| **懒分配（Lazy Allocation）** | ✅ 已实现 | ❌ 未实现 | oskernel2023-zmz 的 `sbrk/brk` 仅调整边界，物理页在缺页时分配；oskernrl2022-rv6 的 `uvmalloc()` 立即分配 |
| **Swap 页面置换** | ❌ 未实现 | ❌ 未实现 | 两者均无 swap_out/swap_in 实现；oskernel2023-zmz 的 `__page_file_swap` 仅用于文件映射换出 |
| **HugePage 大页** | ❌ 未实现 | ❌ 未实现 | 两者均仅支持 4KB 页，无 2M/1G 大页支持 |
| **mmap 文件映射** | ✅ 已实现 | ✅ 已实现 | 两者均支持 `MAP_FIXED/MAP_ANON/MAP_SHARED/MAP_PRIVATE` |
| **SharedMem 共享内存** | ❌ 未实现 | ❌ 未实现 | 两者均无 `shmget/shmdt` 系统调用；但 mmap 支持 `MAP_SHARED` |
| **rmap 反向映射** | ❌ 未实现 | ❌ 未实现 | 两者均无 `rmap/page_to_vma` 数据结构 |
| **mmap 桩代码检测** | ✅ 完整实现 | ✅ 完整实现 | 两者的 `sys_mmap` 均调用 `do_mmap()` 完整逻辑，**非桩实现** |

### CoW 实现细节对比

**oskernel2023-zmz CoW 代码证据**（`kernel/mm/vm.c:564-565`）：
```c
if (cow && (*pte & PTE_W)) {
    *pte = (*pte|PTE_COW) & ~PTE_W;  // 标记 COW，移除写权限
}
```

**CoW 缺页处理**（`kernel/mm/vm.c:961-986`）：
```c
static int handle_store_page_fault_cow(pte_t *ptep) {
    pte_t pte = *ptep;
    uint64 pa = PTE2PA(pte);
    
    if (monopolizepage(pa)) {    // 唯一引用，直接添加写权限
        pte |= PTE_W;
    } else {
        char *copy = (char *)allocpage();  // 分配新页
        memmove(copy, (char *)pa, PGSIZE); // 复制内容
        pte = PA2PTE(copy) | PTE_FLAGS(pte) | PTE_W;
    }
    pte &= ~PTE_COW;
    *ptep = pte;
    sfence_vma();
    return 0;
}
```

**oskernrl2022-rv6 搜索结果**：
```
grep 'cow|COW|copy_on_write' → 未找到匹配
```
**结论**：❌ **CoW 未实现**，`uvmcopy()` 直接复制物理页（深拷贝）

---

### Lazy Allocation 实现细节对比

**oskernel2023-zmz 懒分配代码证据**：
- `sys_sbrk()` 仅调整 `p->pbrk` 边界（`kernel/syscall/sysmem.c:20-52`）
- 实际物理页在缺页时通过 `handle_page_fault_lazy()` 分配

**handle_page_fault_lazy**（`kernel/mm/vm.c:988-1002`）：
```c
static int handle_page_fault_lazy(uint64 badaddr, struct seg *s) {
    struct proc *p = myproc();
    uint64 pa = PGROUNDDOWN(badaddr);
    if (uvmalloc(p->pagetable, pa, pa + PGSIZE, s->flag) == 0)
        return -1;
    sfence_vma();
    return 0;
}
```

**oskernrl2022-rv6 搜索结果**：
```
grep 'lazy|Lazy|populate' → 未找到匹配
```
**uvmalloc() 行为**（`src/vm.c:243-268`）：
```c
uint64 uvmalloc(pagetable_t pagetable, uint64 start, uint64 end, int perm) {
    for(a = start; a < end; a += PGSIZE){
        mem = allocpage();  // 立即分配物理页
        memset(mem, 0, PGSIZE);
        mappages(pagetable, a, PGSIZE, (uint64)mem, perm);
    }
    return 0;
}
```
**结论**：❌ **Lazy Allocation 未实现**

---

### mmap 实现对比

**两者均完整实现 mmap**，非桩代码：

**oskernel2023-zmz sys_mmap**（`kernel/syscall/sysmem.c:79-113`）：
```c
uint64 sys_mmap(void) {
    // 参数解析与验证
    if (off % PGSIZE || len == 0) return -EINVAL;
    if ((fd < 0 || f == NULL) && !(flags & MAP_ANONYMOUS)) return -EBADF;
    if (!(flags & (MAP_SHARED|MAP_PRIVATE))) return -EINVAL;
    
    return do_mmap(start, len, prot, flags, f, off);  // 调用完整实现
}
```

**oskernrl2022-rv6 sys_mmap**（`src/sysfile.c:895-918`）：
```c
uint64 sys_mmap(void) {
    // 参数解析
    if(argaddr(0, &start) < 0) return -1;
    // ...
    uint64 ret = do_mmap(start, len, prot, flags, fd, off);
    return ret;  // 返回实际映射地址，非桩返回值
}
```

**✅ 结论**：两者的 `sys_mmap` 均调用 `do_mmap()` 完整实现，**非桩函数**。

---

## 总结

### 核心差异概览

| 维度 | oskernel2023-zmz | oskernrl2022-rv6 |
|------|------------------|------------------|
| **物理分配器** | 双池优化（single + multiple） | 单池设计 |
| **页表** | Sv39 + COW 标志位 | Sv39（无 COW） |
| **VMA 管理** | 单向链表 `struct seg` | 双向链表 `struct vma` |
| **缺页异常** | ✅ 完整实现 | ❌ 未实现 |
| **CoW** | ✅ 已实现 | ❌ 未实现 |
| **Lazy Allocation** | ✅ 已实现 | ❌ 未实现 |
| **mmap** | ✅ 完整实现 | ✅ 完整实现 |
| **Swap/HugePage/rmap/shm** | ❌ 均未实现 | ❌ 均未实现 |

### 【创新点】标注

1. **双池物理分配器**（oskernel2023-zmz 独有）：通过分离单页预留池减少锁竞争
2. **完整缺页异常处理链路**（oskernel2023-zmz 独有）：支持 CoW、Lazy、ELF 懒加载、MMAP 按需分页
3. **COW 写时复制机制**（oskernel2023-zmz 独有）：使用 `PTE_RSW1` 作为 COW 标志位
4. **Lazy Allocation 懒分配**（oskernel2023-zmz 独有）：`sbrk/brk` 仅调整边界，物理页按需分配

### 代码相似度分析

- **物理分配器**：设计思路相似（链表式），但 oskernel2023-zmz 有双池优化
- **内核堆分配器**：代码高度相似，可能源自同一基线
- **页表操作**：`walk()`/`mappages()` 代码结构几乎一致
- **mmap 实现**：设计思路相似，但 oskernel2023-zmz 支持更完整的按需分页

**总体评价**：oskernel2023-zmz 在内存管理高级特性（CoW、Lazy、缺页异常）上显著领先于 oskernrl2022-rv6，体现了更成熟的虚拟内存管理能力。