#!/usr/bin/env python3
"""
OS-Agent C 粗筛模块：基于向量相似度的历史 OS 库快速检索

功能：
  1. 对指定目标 OS 和历史 OS 库中的每个项目生成特征指纹（LLM 提取 + 本地 Embedding）
  2. 计算多维度加权余弦相似度，选出 Top-5 最相似项目
  3. 将向量和相似度结果保存到 output/ 对应目录

向量存储位置：
  output/<repo>/fingerprint.json          — 每个项目的特征指纹（结构化特征 + 7 维向量）
  output/<target>/coarse_screening.json   — 粗筛结果（Top-K + 各维度得分）

用法：
  # 基本用法：指定目标和历史库
  python os_agent_c_coarse.py --target nonix --library output

  # 通过 REPO_URL 推断目标，指定自定义历史库路径
  python os_agent_c_coarse.py --library /path/to/history_library

  # 指定 Top-K 数量、强制重建指纹
  python os_agent_c_coarse.py --target nonix --library output --top-k 3 --rebuild

  # 指定输出目录
  python os_agent_c_coarse.py --target nonix --library output --output-dir ./output

环境变量（通过 .env 配置）：
  REPO_URL     - 目标 OS 仓库 URL（当未指定 --target 时使用）
  MODEL_NAME   - LLM 模型名称（特征提取用）
"""
import os
import sys
import json
import logging
import argparse
import time
from datetime import datetime
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from core.utils import repo_name_from_url, parse_env_repo_list
from core.vectorizer import (
    build_fingerprint,
    get_fingerprint_stage_status,
    is_fingerprint_disk_cache_ok,
    LocalEmbedder,
    get_dimension_weights,
    DIMENSION_MAP,
    Fingerprint,
)
from core.vector_store import VectorStore
from core.per_planner import build_coarse_preplan
from core.error_handling import RetryConfig

load_dotenv()
from core.hf_env import apply_hf_hub_env_defaults

apply_hf_hub_env_defaults()

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s | %(levelname)s | %(message)s",
)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("os_agent_c_coarse")

DEFAULT_OUTPUT_DIR = "./output"


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt_seconds(sec: float) -> str:
    if sec < 1:
        return f"{sec * 1000:.0f}ms"
    return f"{sec:.2f}s"


def _verbosity_rank(v: str) -> int:
    v = (v or "").strip().lower()
    if v == "debug":
        return 2
    if v == "verbose":
        return 1
    return 0  # normal


def _sf_pick(struct_features: Dict[str, Any]) -> Dict[str, Any]:
    """挑选 coarse 输出里最关键的 struct 字段（避免整坨 JSON 刷屏）。"""
    keys = [
        "framework",
        "allocator_crate",
        "network_stack",
        "fat32_source",
        "trapframe_bytes",
        "syscall_count_real",
    ]
    out = {}
    for k in keys:
        if k in struct_features:
            out[k] = struct_features.get(k)
    return out


def _fmt_kv(d: Dict[str, Any]) -> str:
    parts = []
    for k, v in d.items():
        if v is None or v == "":
            parts.append(f"{k}=null")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts) if parts else "-"


def _print_header(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def discover_projects(library_dir: str, filter_list: list = None) -> list:
    """
    扫描历史 OS 库目录，发现所有包含 D 报告（sections/）的项目。

    Args:
        library_dir: 历史 OS 库根目录（每个子目录是一个项目）
        filter_list: 如果提供，只选出该列表中的项目名称

    Returns:
        [(project_name, sections_dir), ...]
    """
    projects = []
    if not os.path.isdir(library_dir):
        logger.error(f"历史库目录不存在: {library_dir}")
        return projects

    for entry in sorted(os.listdir(library_dir)):
        entry_path = os.path.join(library_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        if entry.startswith("_"):  # 跳过 _vector_index 等内部目录
            continue
            
        if filter_list is not None and entry not in filter_list:
            continue
            
        sections_path = os.path.join(entry_path, "sections")
        if os.path.isdir(sections_path):
            projects.append((entry, sections_path))

    return projects


def run_coarse_screening(
    target_name: str,
    library_dir: str,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    top_k: int = 5,
    rebuild: bool = False,
    filter_list: list = None,
    verbosity: str = "verbose",
) -> dict:
    """
    执行粗筛流程。

    Args:
        target_name:  目标项目名称
        library_dir:  历史 OS 库根目录
        output_dir:   输出根目录
        top_k:        返回 Top-K 候选数
        rebuild:      是否强制重建所有指纹

    Returns:
        粗筛结果字典（同时保存为 JSON 文件）
    """
    v_rank = _verbosity_rank(verbosity)
    t0_total = time.perf_counter()

    _print_header("🔍 OS-Agent C 粗筛：向量相似度检索")
    print(f"   目标项目:   {target_name}")
    print(f"   历史库:     {os.path.abspath(library_dir)}")
    print(f"   输出目录:   {os.path.abspath(output_dir)}")
    print(f"   Top-K:      {top_k}")
    print(f"   rebuild:    {rebuild}")
    print(f"   verbosity:  {verbosity}")
    if filter_list:
        print(f"   filter_list: {filter_list}")
    print(f"   重试配置:   最大{RetryConfig.MAX_RETRIES}次, 退避{RetryConfig.INITIAL_BACKOFF}-{RetryConfig.MAX_BACKOFF}秒")
    print(f"   ⏰ 开始:     {_now_ts()}")
    print("=" * 80)

    # ── Step 1: 加载本地 Embedding 模型 ──
    t0 = time.perf_counter()
    print("\n📦 Step 1/4: 加载本地 Embedding 模型...")
    embedder = LocalEmbedder()
    print(f"   ✅ Embedder 就绪 ({_fmt_seconds(time.perf_counter() - t0)})")

    # ── Step 2: 生成目标项目指纹 ──
    t0 = time.perf_counter()
    print(f"\n📝 Step 2/4: 生成目标项目 [{target_name}] 的特征指纹...")
    target_sections = os.path.join(library_dir, target_name, "sections")
    if not os.path.isdir(target_sections):
        # 也尝试在 output_dir 下查找
        target_sections_alt = os.path.join(output_dir, target_name, "sections")
        if os.path.isdir(target_sections_alt):
            target_sections = target_sections_alt
        else:
            print(f"❌ 未找到目标项目的 D 报告:")
            print(f"   已检查: {target_sections}")
            print(f"   已检查: {target_sections_alt}")
            print(f"   请先运行 OS-Agent D 生成报告")
            return {}

    # 指纹保存在 output_dir 下
    target_output = os.path.join(output_dir, target_name)
    os.makedirs(target_output, exist_ok=True)
    print("   - 子步骤: 读取 01_ 概览并生成 coarse pre-plan")
    print("   - 子步骤: 调用 LLM 提取维度特征摘要")
    print("   - 子步骤: 调用 LLM 提取精确结构化特征")
    print("   - 子步骤: 使用本地 embedding 模型生成向量并保存 fingerprint.json")
    stage_status = get_fingerprint_stage_status(target_sections, force=rebuild)
    print(f"   - 构建模式: {stage_status['mode']}")
    print(f"   - 已命中缓存: {', '.join(stage_status['cache_hits']) if stage_status['cache_hits'] else '无'}")
    print(f"   - 将重跑阶段: {', '.join(stage_status['rerun_stages']) if stage_status['rerun_stages'] else '无'}")
    coarse_preplan = build_coarse_preplan(target_name=target_name, target_sections_dir=target_sections)
    preplan_path = os.path.join(target_output, "coarse_preplan.json")
    try:
        with open(preplan_path, "w", encoding="utf-8") as f:
            json.dump(coarse_preplan, f, ensure_ascii=False, indent=2)
        print(f"   🧭 pre-plan: framework={coarse_preplan.get('framework_guess', [])} arch={coarse_preplan.get('arch_guess', [])}")
    except Exception as e:
        print(f"   ⚠️ 保存 coarse_preplan 失败: {e}")

    target_fp_path = os.path.join(os.path.dirname(target_sections), "fingerprint.json")
    target_disk_ok = (not rebuild) and is_fingerprint_disk_cache_ok(target_sections)
    target_action = "LOAD" if target_disk_ok else "BUILD"
    target_reason = None
    if rebuild:
        target_reason = "--rebuild"
    elif not os.path.exists(target_fp_path):
        target_reason = "fingerprint_missing"
    elif not target_disk_ok:
        target_reason = "fingerprint_stale_or_incomplete"

    target_fp = build_fingerprint(
        repo_name=target_name,
        sections_dir=target_sections,
        embedder=embedder,
        force=rebuild,
    )
    print(f"   ✅ 目标指纹: {target_fp_path}")
    print(f"   动作:       {target_action}" + (f" (reason={target_reason})" if target_reason else ""))
    print(f"   sections:    {os.path.abspath(target_sections)}")
    print(f"   向量维度数: {len(target_fp.embeddings)} 个维度")
    for dim_id, vec in sorted(target_fp.embeddings.items()):
        print(f"      {dim_id}: {len(vec)} 维向量")
    if v_rank >= 1:
        sf = getattr(target_fp, "struct_features", {}) or {}
        print(f"   struct_features: {_fmt_kv(_sf_pick(sf))}")
    print(f"   ✅ Step 2 完成 ({_fmt_seconds(time.perf_counter() - t0)})")

    # ── Step 3: 为历史库中所有项目生成指纹 ──
    t0 = time.perf_counter()
    print(f"\n📂 Step 3/4: 扫描历史库并生成指纹...")
    all_projects = discover_projects(library_dir, filter_list=filter_list)
    print(f"   发现 {len(all_projects)} 个历史项目")

    store = VectorStore(output_dir=output_dir)

    n_load = 0
    n_build = 0
    n_fail = 0

    for idx, (proj_name, proj_sections) in enumerate(all_projects, 1):
        # fingerprint.json 保存在 sections/ 的父目录（即 output/仓库名/）
        proj_fp_path = os.path.join(os.path.dirname(proj_sections), "fingerprint.json")
        proj_t0 = time.perf_counter()

        try:
            action = "BUILD"
            reason = None
            proj_disk_ok = (not rebuild) and is_fingerprint_disk_cache_ok(proj_sections)
            if proj_disk_ok and os.path.exists(proj_fp_path):
                action = "LOAD"
                fp = Fingerprint.load(proj_fp_path)
                n_load += 1
            else:
                if rebuild:
                    reason = "--rebuild"
                elif not os.path.exists(proj_fp_path):
                    reason = "fingerprint_missing"
                elif not proj_disk_ok:
                    reason = "fingerprint_stale_or_incomplete"
                fp = build_fingerprint(
                    repo_name=proj_name,
                    sections_dir=proj_sections,
                    embedder=embedder,
                    force=rebuild,
                )
                n_build += 1

            sf = getattr(fp, "struct_features", {}) or {}
            sf_short = _sf_pick(sf) if v_rank >= 1 else {}
            suffix = f" | {action}"
            if reason:
                suffix += f"(reason={reason})"
            suffix += f" | fp={proj_fp_path}"
            if v_rank >= 1:
                suffix += f" | {_fmt_kv(sf_short)}"
            suffix += f" | {_fmt_seconds(time.perf_counter() - proj_t0)}"
            print(f"   [{idx:>3}/{len(all_projects):<3}] {proj_name}{suffix}")

            store.add_project(proj_name, fp)
        except Exception as e:
            n_fail += 1
            print(f"   [{idx:>3}/{len(all_projects):<3}] {proj_name} | FAIL | {type(e).__name__}: {e}")

    # 也确保目标项目在 store 中
    if not store.has_project(target_name):
        store.add_project(target_name, target_fp)

    print(f"\n   📊 索引总项目数: {store.size}")
    print(f"   统计: LOAD={n_load}, BUILD={n_build}, FAIL={n_fail}")
    print(f"   ✅ Step 3 完成 ({_fmt_seconds(time.perf_counter() - t0)})")

    # ── Step 4: 向量检索 ──
    t0 = time.perf_counter()
    print(f"\n🔎 Step 4/4: 执行向量相似度检索...")
    if v_rank >= 1:
        dim_ids = sorted(DIMENSION_MAP.keys())
        weights = get_dimension_weights()
        fw_shared = ", ".join(sorted(VectorStore.FRAMEWORK_SHARED_DIMS))
        core_dims = ", ".join(sorted(VectorStore.CUSTOM_CORE_DIMS))
        print("   相似度配置: 多维度加权余弦 + struct_features 精确字段加分（最终分归一化到 0~1 / 0~100%）")
        print(f"   维度: {', '.join(dim_ids)}")
        print(f"   权重: {_fmt_kv({d: round(weights.get(d, 0.0), 4) for d in dim_ids})}")
        print(f"   同框架重权重: shared_half=[{fw_shared}], core_x1.4=[{core_dims}]")

    results = store.search_similar(target_fp, top_k=top_k, exclude_self=True)
    print(f"   ✅ Step 4 完成 ({_fmt_seconds(time.perf_counter() - t0)})")

    # ── 输出结果 ──
    weights = get_dimension_weights()
    dim_ids = sorted(DIMENSION_MAP.keys())

    print("\n" + "=" * 80)
    print(f"📋 粗筛结果：{target_name} vs 历史库 (Top-{top_k})")
    print("=" * 80)

    # 表头
    dim_short = [d.split("_", 1)[1][:8] for d in dim_ids]
    header = f"{'#':>2}  {'项目':<20}  {'总分':>6}  {'百分比':>8}"
    for s in dim_short:
        header += f"  {s:>8}"
    print(header)
    print("-" * len(header))

    for rank, r in enumerate(results, 1):
        fw_tag = " [同框架]" if r.get("same_framework") else ""
        line = (f"{rank:>2}  {r['name']:<20}  {r['total_score']:>6.4f}"
                f"  {r.get('similarity_percent', r['total_score'] * 100):>7.2f}%"
                f"  (raw={r.get('raw_total_score', r['total_score']):.4f}"
                f", cos={r.get('cosine_score', r['total_score']):.4f}"
                f", sf={r.get('struct_score', 0):.4f}){fw_tag}")
        for d in dim_ids:
            line += f"  {r['dim_scores'].get(d, 0):>8.4f}"
        print(line)

    print(f"\n权重: ", end="")
    for d in dim_ids:
        short = d.split("_", 1)[1][:8]
        print(f"{short}={weights[d]:.2f} ", end="")
    print()

    # ── 保存粗筛结果 ──
    coarse_result = {
        "target": target_name,
        "library_dir": os.path.abspath(library_dir),
        "timestamp": datetime.now().isoformat(),
        "top_k": top_k,
        "coarse_preplan_path": preplan_path,
        "coarse_preplan": coarse_preplan,
        "dimension_weights": weights,
        "target_fingerprint_path": target_fp_path,
        "target_vectors": {
            dim_id: {
                "feature_text": target_fp.features.get(dim_id, ""),
                "vector_length": len(target_fp.embeddings.get(dim_id, [])),
            }
            for dim_id in dim_ids
        },
        "results": results,
    }
    coarse_result["validation"] = validate_coarse_output(coarse_result)

    coarse_path = os.path.join(target_output, "coarse_screening.json")
    with open(coarse_path, "w", encoding="utf-8") as f:
        json.dump(coarse_result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 粗筛结果已保存: {coarse_path}")

    # 同时保存人类可读的 markdown 版本
    md_path = os.path.join(target_output, "coarse_screening.md")
    _save_coarse_markdown(md_path, target_name, results, dim_ids, weights)
    print(f"📄 可读报告已保存: {md_path}")

    print("\n" + "-" * 80)
    print("📦 输出产物汇总")
    print("-" * 80)
    print(f"   target_sections: {os.path.abspath(target_sections)}")
    print(f"   target_fingerprint: {target_fp_path}")
    print(f"   coarse_json: {coarse_path}")
    print(f"   coarse_md:   {md_path}")
    print("-" * 80)
    print(f"⏰ 完成: {_now_ts()} | 总耗时: {_fmt_seconds(time.perf_counter() - t0_total)}")
    return coarse_result


def _save_coarse_markdown(
    path: str, target: str, results: list, dim_ids: list, weights: dict
):
    """保存粗筛结果的 Markdown 可读版本。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {target} 向量粗筛报告\n\n")
        f.write(f"> **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **分析工具**: OS-Agent-C (粗筛模块)\n\n")
        f.write("---\n\n")

        f.write("## 相似度排名\n\n")
        f.write(
            "| 排名 | 项目 | 总相似度(0~1) | 百分比 | "
            "raw(cos+sf) | cos | sf |"
        )
        for d in dim_ids:
            short = d.split("_", 1)[1]
            f.write(f" {short} |")
        f.write("\n")
        f.write("|------|------|---------------|--------|-------------|-----|-----|")
        for _ in dim_ids:
            f.write("--------|")
        f.write("\n")

        for rank, r in enumerate(results, 1):
            raw_v = r.get("raw_total_score", r["total_score"])
            cos_v = r.get("cosine_score", 0.0)
            sf_v = r.get("struct_score", 0.0)
            f.write(
                f"| {rank} | {r['name']} | {r['total_score']:.4f} | "
                f"{r.get('similarity_percent', r['total_score'] * 100):.2f}% | "
                f"{raw_v:.4f} | {cos_v:.4f} | {sf_v:.4f} |"
            )
            for d in dim_ids:
                f.write(f" {r['dim_scores'].get(d, 0):.4f} |")
            f.write("\n")

        cap = VectorStore.TOTAL_SCORE_CAP
        f.write(
            f"\n> **说明**：`raw = cosine_score + struct_score`（未除以 {cap:.2f} 的原始合成）；"
            f"`总相似度 = raw / {cap:.2f}` 后钳在 0~1，与 `coarse_screening.json` 字段一致。\n"
        )

        f.write(f"\n## 维度权重\n\n")
        for d in dim_ids:
            name = d.split("_", 1)[1]
            f.write(f"- **{name}**: {weights[d]:.2f}\n")

        f.write(f"\n---\n*本报告由 OS-Agent-C 粗筛模块自动生成*\n")


def validate_coarse_output(coarse_result: dict) -> dict:
    issues = []
    if not coarse_result.get("results"):
        issues.append("empty_results")
    preplan = coarse_result.get("coarse_preplan", {}) or {}
    if not preplan.get("available_sections"):
        issues.append("missing_sections")
    if not preplan.get("framework_guess"):
        issues.append("framework_unknown")
    return {
        "passed": len([x for x in issues if x not in {"framework_unknown"}]) == 0,
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="OS-Agent C 粗筛：向量相似度快速检索",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python os_agent_c_coarse.py --target nonix --library ./output
  python os_agent_c_coarse.py --target nonix --library ./output --top-k 3
  python os_agent_c_coarse.py --target nonix --library ./output --rebuild
  python os_agent_c_coarse.py --target nonix --library ./output --verbosity verbose
        """,
    )
    parser.add_argument(
        "--target", type=str, default=None,
        help="目标项目名称（对应 library/ 下的子目录名）。未指定则从 REPO_URL 推断。",
    )
    parser.add_argument(
        "--library", type=str, default=DEFAULT_OUTPUT_DIR,
        help="历史 OS 库根目录（默认 ./output）。每个子目录应包含 sections/ 子目录。",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="输出目录（默认与 --library 相同）。指纹和粗筛结果保存在此。",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="返回 Top-K 个最相似项目（默认 5）",
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="强制重建所有项目的特征指纹（忽略已有缓存）",
    )
    parser.add_argument(
        "--verbosity",
        type=str,
        default="verbose",
        choices=["normal", "verbose", "debug"],
        help="终端输出详细级别（默认 verbose）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="静默模式：等同于 --verbosity normal（兼容用）",
    )
    args = parser.parse_args()

    # 确定目标项目名
    target_name = args.target
    if not target_name:
        repo_url = os.environ.get("REPO_URL", "").strip()
        if repo_url:
            target_name = repo_name_from_url(repo_url)
        else:
            print("❌ 请通过 --target 指定目标项目名，或在 .env 中设置 REPO_URL")
            sys.exit(1)

    output_dir = args.output_dir or args.library
    verbosity = "normal" if args.quiet else args.verbosity

    # 解析 .env 中的 HISTORY_PROJECTS（支持单行/多行列表）
    filter_list = None
    try:
        parsed_history_projects = parse_env_repo_list("HISTORY_PROJECTS")
        if parsed_history_projects:
            filter_list = parsed_history_projects
    except Exception as e:
        print(f"⚠️ 解析 HISTORY_PROJECTS 环境变量失败: {e}，将扫描库目录下所有项目")

    if filter_list:
        filter_list = [repo_name_from_url(x) if x.startswith("http") or x.startswith("git@") else x for x in filter_list]

    run_coarse_screening(
        target_name=target_name,
        library_dir=args.library,
        output_dir=output_dir,
        top_k=args.top_k,
        rebuild=args.rebuild,
        filter_list=filter_list,
        verbosity=verbosity,
    )


if __name__ == "__main__":
    main()
