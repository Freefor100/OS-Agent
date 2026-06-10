"""`_lineage` metadata field builder for code atlas records.
  → 同输入产同 hash，评委可以拿这个 hash 比对
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Iterable

from core.code_atlas.config import (
    PIPELINE_VERSION,
    algo_versions_snapshot,
)


def stable_json(obj: Any) -> str:
    """规范化 JSON 序列化：sort_keys + 紧凑分隔，让 sha256 跨机器一致。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _safe_git_head(repo_path: str) -> str | None:
    """读 .git/HEAD 解析当前 commit；非 git 仓库返回 None。"""
    head_file = os.path.join(repo_path, ".git", "HEAD")
    if not os.path.isfile(head_file):
        return None
    try:
        with open(head_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content.startswith("ref:"):
            ref_path = os.path.join(repo_path, ".git", content[4:].strip())
            if os.path.isfile(ref_path):
                with open(ref_path, "r", encoding="utf-8") as rf:
                    return rf.read().strip()
        return content or None
    except OSError:
        return None


def compute_input_hash(
    *,
    repo_path: str,
    extra_inputs: dict | None = None,
) -> str:
    """计算 input_hash = sha256(repo_commit + pipeline_versions + extra)。

    extra_inputs 的约定：语料库所有 commit hash 也要参与。
    """
    payload = {
        "pipeline_version": PIPELINE_VERSION,
        "algo_versions": algo_versions_snapshot(),
        "repo_commit": _safe_git_head(repo_path),
        "extra": extra_inputs or {},
    }
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def make_lineage(
    *,
    repo_path: str,
    extra_inputs: dict | None = None,
    llm_model: str | None = None,
    llm_cache_keys: Iterable[str] = (),
    llm_calls_total: int = 0,
    llm_miss_rate: float | None = None,
    llm_cache_enabled: bool = True,
    llm_cache_strict: bool = False,
    extra_meta: dict | None = None,
) -> dict:
    """给一份产物构造 `_lineage` 字段。

    调用方负责累计 LLM 调用统计。算法侧字段全自动来自 pipeline_config。
    """
    keys = sorted(set(llm_cache_keys))
    return {
        "pipeline_version": PIPELINE_VERSION,
        "input_hash": compute_input_hash(
            repo_path=repo_path, extra_inputs=extra_inputs
        ),
        "algo_versions": algo_versions_snapshot(),
        "llm": {
            "model": llm_model,
            "cache_enabled": llm_cache_enabled,
            "cache_strict": llm_cache_strict,
            "cache_keys_used": keys,
            "calls_total": llm_calls_total,
            "miss_rate": llm_miss_rate,
        },
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "extra_meta": extra_meta or {},
    }


def attach_lineage(payload: dict, lineage: dict) -> dict:
    """把 _lineage 挂到产物末尾。原地修改并返回原对象（方便链式）。"""
    payload["_lineage"] = lineage
    return payload
