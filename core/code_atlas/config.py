"""Code-atlas algorithm constants.

任何改动这里的常量等于改底层代码结构指纹算法，旧缓存需重建。
"""


from __future__ import annotations

PIPELINE_VERSION = "code-atlas-v1"


# ─── tree-sitter 解析器版本（写进 _lineage，cache_key 不依赖）─────────────
TREE_SITTER_VER = {
    "c":    "0.21",
    "cpp":  "0.21",
    "rust": "0.21",
    "go":   "0.21",
    "zig":  "0.20",
}


# ─── token normalize（L1 token_minhash 的输入算法）─────────────────────
NORMALIZE_VER = "v1"
NORMALIZE_RULES = {
    "strip_comments": True,
    "alpha_rename_locals": True,    # 局部变量 → V0/V1/...，全局/类型/函数名保留
    "literal_placeholder": True,    # 数字→N、字符串→S、字符→C
    "compress_whitespace": True,
    "keep_keywords": True,
}


# ─── MinHash（L1/L2/L4 都用）──────────────────────────────────────────
MINHASH_SEED = 42
MINHASH_NUM_PERM = 128            # token_minhash / function_set_minhash 用
MINHASH_NUM_PERM_SMALL = 64       # neighbor / literal / role_set 用
MINHASH_NGRAM_K = 5               # token k-gram


# ─── AST shape merkle hash（L1 ast_shape_hash 算法）────────────────────
AST_SHAPE_VER = "v1"
AST_SHAPE_RULES = {
    "leaf_uses_node_text": False,   # 关键：leaf 只用 node.type，不用文本
    "delimiter": "|",
    "child_sep": ",",
    "hash_algo": "sha256",
}


# ─── PageRank（atlas.functions.pagerank）──────────────────────────────
PAGERANK_ALPHA = 0.85
PAGERANK_TOL = 1e-8
PAGERANK_MAX_ITER = 100


# ─── role 词表版本（代码结构实验用）──────
ROLE_VOCAB_VER = "v1"


# 功能模块树由 core/review_case/taxonomy.py 唯一定义。
KERNEL_PROJECT_HINT_VER = "v3"


# ─── L3 路径剪枝（LSP 多分支图 → 5-7 步前的算法步骤）─────────────────
L3_PRUNE_VER = "v1"
L3_PATH_MAX_STEPS = 7
L3_PATH_BRANCH_FACTOR = 2          # 每层最多保留 2 分支
L3_LSP_MAX_DEPTH = 4               # .env 也可调（只影响 raw graph，不影响剪枝算法版本）


# ─── L5 架构层（domain × layer）───────────────────────────────────────
DOMAINS = [
    "arch_platform", "trap_syscall", "process_sched", "memory_vm",
    "fs_storage", "sync_ipc", "runtime_common", "user_programs", "unknown",
]
LAYERS = ["userspace", "syscall_boundary", "kernel", "hardware", "unknown"]
KERNEL_STYLE_VOCAB = ["monolithic", "microkernel", "hybrid", "unikernel", "library"]
SMP_STYLE_VOCAB    = ["single", "smp_global_lock", "smp_cpu_local", "numa"]


# ─── Prompt 模板版本（写进 cache_key）─────────────────────────────────
# template_id → 当前版本号；改 prompt 必须 bump
PROMPT_TEMPLATE_VERSIONS = {
    "function_role":         "v1",
    "l2_module_grouping":    "v1",
    "node_summary":          "v4",
    "innovation":            "v1",
    "path_refine":           "v1",
    "architecture_style":    "v1",
    "function_equivalence":  "v1",
    "lineage_explain":       "v1",
}


# ─── 谱系识别权重（plan v7 §C-2）────────────────────────────────────
LINEAGE_WEIGHTS = {
    "L5_overall_shape":           0.10,
    "L4_module_structure":        0.20,
    "L4_high_match_modules":      0.15,
    "L3_path_continuity":         0.10,
    "L1_identical_function_pct":  0.30,
    "L1_equivalent_function_pct": 0.15,
}
assert abs(sum(LINEAGE_WEIGHTS.values()) - 1.0) < 1e-9

# 高匹配阈值（plan v7 §C-2，证据计数用，不是分类阈值）
LINEAGE_L4_HIGH_MATCH = 0.7
LINEAGE_L3_PATH_MATCH = 0.85
LINEAGE_L1_EQUIVALENT_VERDICTS = ("identical", "logically_equivalent")


# ─── 启动时一致性校验 ─────────────────────────────────────────────
def assert_env_pipeline_version(env_value: str | None) -> None:
    """兼容旧调用：校验 code-atlas pipeline version。

    不一致 → raise，避免评委用旧 corpus 跑新 target（或反之）。
    """
    if env_value is None:
        raise RuntimeError(
            "CODE_ATLAS_PIPELINE_VERSION 未设置。请在 .env 里加 "
            f"CODE_ATLAS_PIPELINE_VERSION={PIPELINE_VERSION}"
        )
    if env_value != PIPELINE_VERSION:
        raise RuntimeError(
            f"CODE_ATLAS_PIPELINE_VERSION={env_value!r} 与 code_atlas.config.PIPELINE_VERSION="
            f"{PIPELINE_VERSION!r} 不一致。算法已升版，旧 corpus 与新 target 不可比，"
            f"请重建 corpus 或回退代码。"
        )


# ─── 写进每份产物 _lineage 的固定字段集合 ──────────────────────────
def algo_versions_snapshot() -> dict:
    """返回所有算法版本，给产物 _lineage.algo_versions 用。"""
    return {
        "pipeline":     PIPELINE_VERSION,
        "tree_sitter":  TREE_SITTER_VER,
        "normalize":    NORMALIZE_VER,
        "ast_shape":    AST_SHAPE_VER,
        "minhash":      {
            "seed": MINHASH_SEED,
            "num_perm": MINHASH_NUM_PERM,
            "num_perm_small": MINHASH_NUM_PERM_SMALL,
            "ngram_k": MINHASH_NGRAM_K,
        },
        "pagerank":     {"alpha": PAGERANK_ALPHA, "tol": PAGERANK_TOL},
        "role_vocab":   ROLE_VOCAB_VER,
        "kernel_project_hint": KERNEL_PROJECT_HINT_VER,
        "l3_prune":     L3_PRUNE_VER,
        "prompt_templates": dict(PROMPT_TEMPLATE_VERSIONS),
    }
