"""
OS-Agent C: 精比阶段的 Agent 工具集

提供 Call Graph 差异对比、section 报告加载等 LangChain 工具，
供精比阶段的 LangGraph Agent 使用。
"""
import os
import re
import logging
from typing import Optional

from langchain.tools import tool

logger = logging.getLogger("compare_ops")

OUTPUT_DIR = "./output"


# ---------------------------------------------------------------------------
# 报告加载
# ---------------------------------------------------------------------------
@tool
def load_project_report(repo_name: str, section_id: str = "") -> str:
    """
    加载指定项目的分析报告内容。

    Args:
        repo_name:  项目名称（对应 output/<repo_name>/）
        section_id: 可选的 section 前缀过滤（如 "03_" 只加载内存管理章节）。
                    留空则加载全部 sections。

    Returns:
        报告内容文本。如果指定了 section_id，只返回匹配的 section 内容。
    """
    sections_dir = os.path.join(OUTPUT_DIR, repo_name, "sections")
    if not os.path.isdir(sections_dir):
        return f"❌ 未找到项目 {repo_name} 的分析报告目录: {sections_dir}"

    parts = []
    for fname in sorted(os.listdir(sections_dir)):
        if not fname.endswith(".md"):
            continue
        if section_id and not fname.startswith(section_id):
            continue
        fpath = os.path.join(sections_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
            # 截断保护
            if len(content) > 15000:
                content = content[:15000] + "\n... [截断，原文更长]"
            parts.append(f"--- {fname} ---\n{content}")
        except Exception as e:
            parts.append(f"--- {fname} ---\n[读取失败: {e}]")

    if not parts:
        return f"未找到匹配 section_id='{section_id}' 的报告文件"

    return "\n\n".join(parts)


@tool
def load_project_fingerprint(repo_name: str) -> str:
    """
    加载指定项目的特征指纹摘要。

    Args:
        repo_name: 项目名称

    Returns:
        各维度的结构化特征文本
    """
    import json
    fp_path = os.path.join(OUTPUT_DIR, repo_name, "fingerprint.json")
    if not os.path.exists(fp_path):
        return f"❌ 未找到项目 {repo_name} 的指纹文件: {fp_path}"

    try:
        with open(fp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        features = data.get("features", {})
        lines = [f"## {repo_name} 特征指纹\n"]
        for dim_id in sorted(features.keys()):
            lines.append(f"### {dim_id}\n{features[dim_id]}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 加载指纹失败: {e}"


# ---------------------------------------------------------------------------
# Call Graph 差异对比
# ---------------------------------------------------------------------------
# 关键入口函数列表
KEY_ENTRY_POINTS = [
    ("trap_handler",      "中断处理入口"),
    ("schedule",          "调度器入口"),
    ("handle_page_fault", "缺页异常处理"),
    ("sys_write",         "系统调用示例"),
    ("alloc_frame",       "物理内存分配"),
]


def _extract_fallback_confidence(text: str) -> str:
    """解析回退元数据中的 confidence，默认为 low。"""
    m = re.search(r"confidence=(high|medium|low)", text or "")
    if m:
        return m.group(1)
    return "low"


def _parse_call_tree_nodes(tree_text: str) -> set:
    """
    从 lsp_get_call_graph 的树形文本输出中提取函数名集合。

    输出格式示例：
        trap_handler (kernel/trap.rs:42)
        ├── handle_page_fault (kernel/mm/fault.rs:88)
        │   ├── cow_handler (kernel/mm/cow.rs:33)
        │   └── lazy_alloc (kernel/mm/lazy.rs:55)
        └── syscall_handler (kernel/syscall.rs:10)
    """
    nodes = set()
    for line in tree_text.splitlines():
        # 移除树状前缀
        cleaned = re.sub(r'^[\s│├└─]+', '', line).strip()
        if not cleaned:
            continue
        # 提取函数名（空格或括号之前的部分）
        match = re.match(r'(\w+)', cleaned)
        if match:
            nodes.add(match.group(1))
    return nodes


@tool
def compare_call_graphs(
    repo_a: str, repo_b: str, entry_function: str
) -> str:
    """
    对比两个项目中同一入口函数的 Call Graph 差异。

    内部分别调用 lsp_get_call_graph 获取两个项目的调用树，
    然后分析差异（共同调用、A 独有、B 独有）。

    Args:
        repo_a:         项目 A 名称（对应 repos/<repo_a>）
        repo_b:         项目 B 名称（对应 repos/<repo_b>）
        entry_function: 要对比的入口函数名（如 "trap_handler", "schedule"）

    Returns:
        差异对比报告文本
    """
    from tools.lsp_ops import lsp_get_call_graph
    from tools.file_ops import grep_in_repo

    def _find_entry_file(repo_name: str, symbol: str) -> Optional[str]:
        """
        优先用 ASTParser（tree-sitter）定位函数定义文件；失败再退回 grep。
        这样可以避免宏/模块同名导致“看起来像命中但其实不是函数”的误选文件。
        """
        try:
            _, rel = _find_function_chunk(repo_name, symbol)
            if rel:
                return rel.replace("\\", "/")
        except Exception:
            pass

        repo_path_local = f"repos/{repo_name}"
        try:
            grep_result = grep_in_repo.invoke({
                "repo_path": repo_path_local,
                "pattern": (
                    rf"\bfn\s+{symbol}\b|"
                    rf"\bdef\s+{symbol}\b|"
                    rf"\bfunc\s+{symbol}\s*\(|"
                    rf"\bfunc\s+\([^)]+\)\s+{symbol}\s*\(|"
                    rf"\b{symbol}\s*\([^;]*\)\s*\{{"
                ),
                "max_results": 8,
                "file_extensions": "rs,c,cc,cpp,h,hpp,go,zig,S,asm",
            })
            for line in str(grep_result).splitlines():
                if ":" in line and not line.startswith("搜索") and not line.startswith("未找到"):
                    return line.split(":")[0].strip().replace("\\", "/")
        except Exception:
            pass
        return None

    results = {}
    for repo_name in [repo_a, repo_b]:
        repo_path = f"repos/{repo_name}"
        if not os.path.isdir(repo_path):
            results[repo_name] = f"[仓库不存在: {repo_path}]"
            continue

        file_path = _find_entry_file(repo_name, entry_function)

        if not file_path:
            results[repo_name] = f"[未找到函数 {entry_function} 的定义]"
            continue

        # 调用 Call Graph：首选 LSP，失败/降级时由 lsp_get_call_graph 内部自动走分层兜底
        try:
            cg = lsp_get_call_graph.invoke({
                "repo_path": repo_path,
                "file_path": file_path,
                "symbol": entry_function,
                "direction": "outgoing",
                "max_depth": 3,
            })
            results[repo_name] = str(cg)
        except Exception as e:
            results[repo_name] = f"[Call Graph 获取失败: {e}]"

    # 解析差异
    nodes_a = _parse_call_tree_nodes(results.get(repo_a, ""))
    nodes_b = _parse_call_tree_nodes(results.get(repo_b, ""))
    common = nodes_a & nodes_b
    only_a = nodes_a - nodes_b
    only_b = nodes_b - nodes_a
    union = nodes_a | nodes_b
    jaccard_cg = len(common) / len(union) if union else 0.0

    report = [
        f"## Call Graph 对比：{entry_function}",
        f"",
        f"### {repo_a} 的调用树",
        f"```",
        results.get(repo_a, "[无数据]"),
        f"```",
        f"",
        f"### {repo_b} 的调用树",
        f"```",
        results.get(repo_b, "[无数据]"),
        f"```",
        f"",
        f"### 差异分析",
        f"- **共同调用** ({len(common)}): {', '.join(sorted(common)) or '无'}",
        f"- **{repo_a} 独有** ({len(only_a)}): {', '.join(sorted(only_a)) or '无'}",
        f"- **{repo_b} 独有** ({len(only_b)}): {', '.join(sorted(only_b)) or '无'}",
        f"- **Call Graph 节点 Jaccard**: {jaccard_cg:.3f}"
        f"  ({len(common)} 共同 / {len(union)} 全集)",
    ]
    return "\n".join(report)


@tool
def compare_feature_summary(repo_a: str, repo_b: str, dimension: str) -> str:
    """
    加载并并排显示两个项目在指定维度的特征摘要，方便 LLM 进行语义差异分析。

    Args:
        repo_a:    项目 A 名称
        repo_b:    项目 B 名称
        dimension: 维度 ID（如 "D3_memory", "D4_process_sched"）

    Returns:
        并排特征摘要文本
    """
    import json

    fp_a = os.path.join(OUTPUT_DIR, repo_a, "fingerprint.json")
    fp_b = os.path.join(OUTPUT_DIR, repo_b, "fingerprint.json")
    missing = []
    if not os.path.exists(fp_a):
        missing.append(f"- {repo_a}: {fp_a}")
    if not os.path.exists(fp_b):
        missing.append(f"- {repo_b}: {fp_b}")
    if missing:
        # 强失败：避免 LLM 把占位内容当作真实特征摘要
        return (
            "❌ compare_feature_summary 失败：缺少 fingerprint.json（无法进行维度特征对比）\n\n"
            "缺失文件：\n"
            + "\n".join(missing)
            + "\n\n"
            "请先生成指纹（粗筛阶段会自动生成）：\n"
            f"- python os_agent_c_coarse.py --target {repo_a} --library ./output --rebuild\n"
            f"- python os_agent_c_coarse.py --target {repo_b} --library ./output --rebuild\n"
        )

    summaries = {}
    for name, fp_path in [(repo_a, fp_a), (repo_b, fp_b)]:
        with open(fp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        summaries[name] = data.get("features", {}).get(dimension, "[无此维度数据]")

    return (
        f"## {dimension} 特征对比\n\n"
        f"### {repo_a}\n{summaries[repo_a]}\n\n"
        f"### {repo_b}\n{summaries[repo_b]}"
    )

# ---------------------------------------------------------------------------
# AST-based Code RAG 检索
# ---------------------------------------------------------------------------
@tool
def search_code_snippets(repo_name: str, query: str, top_k: int = 3) -> str:
    """
    在指定项目中，利用架构感知的 AST 切块与向量引擎，搜索与查询最匹配核心代码片段。
    
    用于补充基于 LSP 分析失败时，依靠静态 AST RAG （代码块）获取源码比对的细节。
    
    Args:
        repo_name: 项目名称，如 rcore-v3
        query: 检索的自然语言描述或核心函数/结构体名称 (如 "handle_page_fault implementation")
        top_k: 返回的最高匹配代码片段数量
        
    Returns:
        包含文件路径、相似度、代码块内容的文本字符串。
    """
    try:
        from core.code_rag import CodeRAGEngine
        engine = CodeRAGEngine(repo_name, output_dir=OUTPUT_DIR)
        repo_path = f"repos/{repo_name}"
        if not os.path.exists(repo_path):
            return f"❌ 无法定位仓库: {repo_path}"
            
        # 强制懒加载建立索引 (如果不存在)
        engine.build_index(repo_path, force=False)
        
        results = engine.search(query, top_k=top_k)
        if not results:
            return f"未找到与 '{query}' 高度匹配的代码片段。"
            
        out_lines = [f"### 检索 '{query}' 在 {repo_name} 的结果："]
        for i, res in enumerate(results, 1):
            score = res.get("similarity_score", 0)
            score_out = f" (相似度 {score:.2f})" if isinstance(score, float) else f" (匹配度得分:{score})"
            out_lines.append(f"\n**片段 {i}** - {res.get('file_path')} `[{res.get('node_type')}:{res.get('name')}]` {score_out}")
            out_lines.append(f"```c\n{res.get('code')}\n```")
            
        return "\n".join(out_lines)
    except Exception as e:
        logger.error(f"检索代码片段异常: {e}")
        return f"检索失败: {e}"


# ---------------------------------------------------------------------------
# Token Jaccard 函数体相似度
# ---------------------------------------------------------------------------
# 过滤掉纯语言关键字，让独有 token 更有意义
_LANG_KEYWORDS = frozenset({
    # Rust
    "fn", "pub", "let", "mut", "if", "else", "for", "while", "loop", "return",
    "match", "use", "mod", "impl", "struct", "enum", "trait", "self", "Self",
    "true", "false", "None", "Some", "Ok", "Err", "unsafe", "extern", "async",
    "await", "move", "ref", "in", "where", "type", "const", "static",
    # C/C++
    "int", "void", "char", "long", "short", "unsigned", "signed", "double",
    "float", "return", "if", "else", "for", "while", "do", "switch", "case",
    "break", "continue", "goto", "sizeof", "typedef", "struct", "enum", "union",
    "static", "extern", "const", "volatile", "inline", "NULL", "true", "false",
    # common
    "0", "1", "2", "4", "8",
})


def _find_function_chunk(repo_name: str, function_name: str):
    """
    在 repos/<repo_name> 中用 ASTParser 扫描所有 .c/.h/.rs 文件，
    返回第一个名称匹配的 (code: str, rel_path: str) 或 (None, None)。

    注意：ASTParser 只支持 C（.c/.h）和 Rust（.rs），不支持 .cpp/.cc/.hpp。
    """
    from core.code_rag import ASTParser

    repo_path = os.path.join("repos", repo_name)
    if not os.path.isdir(repo_path):
        return None, None

    parser = ASTParser()
    # 只包含 ASTParser 实际支持的扩展名，避免静默跳过
    target_exts = {".c", ".h", ".rs"}

    for root, dirs, files in os.walk(repo_path):
        # 跳过无关目录加速扫描
        dirs[:] = [d for d in dirs if d not in
                   {".git", "target", "build", "dist", "node_modules", ".os_agent_ra_target"}]
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in target_exts:
                continue
            fpath = os.path.join(root, fname)
            try:
                chunks = parser.parse_file(fpath)
            except Exception:
                continue
            for chunk in chunks:
                if chunk.name == function_name:
                    rel = os.path.relpath(fpath, repo_path)
                    return chunk.code, rel

    return None, None


def _tokenize_code(code: str) -> set:
    """去注释后提取 token 集合（过滤空字符串）。"""
    # 去行注释和块注释
    code = re.sub(r'//[^\n]*', ' ', code)
    code = re.sub(r'/\*.*?\*/', ' ', code, flags=re.DOTALL)
    tokens = re.findall(r'[a-zA-Z_]\w*|\d+|[^\w\s]', code)
    return set(t for t in tokens if t.strip())


@tool
def compare_function_tokens(repo_a: str, repo_b: str, function_name: str) -> str:
    """
    对两个仓库中同名函数的函数体做 token 级别的 Jaccard 相似度比较。
    复用 ASTParser（tree-sitter 解析，有 regex 降级），无需编译环境。
    用于在 c09_innovation 阶段提供客观代码相似度数字证据。

    Args:
        repo_a:        项目 A 名称（对应 repos/<repo_a>）
        repo_b:        项目 B 名称（对应 repos/<repo_b>）
        function_name: 目标函数名（如 "handle_page_fault", "do_fork"）

    Returns:
        Jaccard 相似度报告，含分数 + 两侧独有关键词摘要。
    """
    code_a, path_a = _find_function_chunk(repo_a, function_name)
    code_b, path_b = _find_function_chunk(repo_b, function_name)

    if code_a is None and code_b is None:
        return (f"## 函数 `{function_name}` Token 相似度\n"
                f"- {repo_a}: 未找到\n"
                f"- {repo_b}: 未找到\n"
                f"- Jaccard 相似度: N/A（函数不存在）")

    if code_a is None:
        return (f"## 函数 `{function_name}` Token 相似度\n"
                f"- {repo_a}: 未找到该函数\n"
                f"- {repo_b}: `{path_b}`\n"
                f"- Jaccard 相似度: N/A（{repo_a} 未找到函数）")

    if code_b is None:
        return (f"## 函数 `{function_name}` Token 相似度\n"
                f"- {repo_a}: `{path_a}`\n"
                f"- {repo_b}: 未找到该函数\n"
                f"- Jaccard 相似度: N/A（{repo_b} 未找到函数）")

    tokens_a = _tokenize_code(code_a)
    tokens_b = _tokenize_code(code_b)

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    jaccard = len(intersection) / len(union) if union else 0.0

    # 独有关键词（过滤语言关键字，取前 15 个）
    unique_a = sorted((tokens_a - tokens_b) - _LANG_KEYWORDS)[:15]
    unique_b = sorted((tokens_b - tokens_a) - _LANG_KEYWORDS)[:15]

    lines = [
        f"## 函数 `{function_name}` Token 相似度",
        f"- {repo_a}: `{path_a}` ({len(tokens_a)} tokens)",
        f"- {repo_b}: `{path_b}` ({len(tokens_b)} tokens)",
        f"- **Jaccard 相似度: {jaccard:.3f}**  ({len(intersection)} 共同 / {len(union)} 全集)",
        f"- {repo_a} 独有关键词: {', '.join(unique_a) or '无'}",
        f"- {repo_b} 独有关键词: {', '.join(unique_b) or '无'}",
        f"",
        f"参考标准: ≥0.60 高度相似 | 0.30-0.60 中度相似 | <0.30 差异明显",
    ]
    return "\n".join(lines)
