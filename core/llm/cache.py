"""LLMCache：把 LLM 调用从"动态"变成"查表"。

设计（plan v7 §1）:
    cache_key = sha256(template_id | template_version | model_name |
                       stable_json(inputs))

    if cache 命中 → 直接返回历史 response
    else        → 调 LLM (temp=0, seed=42)，结果落盘缓存

    缓存目录: <cache_dir>/<key[:2]>/<key>.json
    缓存内容: { "key", "template_id", "template_version", "model",
                "inputs_hash", "response", "metadata" }

可复现性的关键不是"缓存命中率"，而是"分数 100% 算法、LLM 仅做标签和文字"。
本模块只解决 LLM 调用层的非确定性；分数层的确定性由 pipeline_config 保证。

环境变量：
    MODEL_NAME                          LLM 模型名
    AGENT_D_LLM_TEMPERATURE             默认 0
    AGENT_D_LLM_SEED                    默认 42
    AGENT_D_MAX_OUTPUT_TOKENS       默认 2048
    AGENT_D_LLM_TIMEOUT_SECONDS         默认 120
    AGENT_D_LLM_CACHE_ENABLED           默认 true；false 时纯实时（产物 lineage 会标）
    AGENT_D_LLM_CACHE_DIR               留空 = output/<repo>/_llm_cache/
    AGENT_D_LLM_CACHE_STRICT            true = miss 直接 raise，评委复现模式
    AGENT_D_VERBOSE_PROMPT_LOG          true = 把 prompt 写 _agent_state/prompt_log.jsonl
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable

from core.code_atlas.lineage import stable_json
from core.code_atlas.config import PROMPT_TEMPLATE_VERSIONS


# ─── 常量与异常 ──────────────────────────────────────────────────


class CacheStrictMissError(RuntimeError):
    """AGENT_D_LLM_CACHE_STRICT=true 时 cache miss 抛此异常。"""


class TemplateVersionMissingError(RuntimeError):
    """template_id 没在 PROMPT_TEMPLATE_VERSIONS 里登记 → 拒绝调用。"""


# ─── 环境变量读取 ────────────────────────────────────────────────


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    return int(v) if v.isdigit() else default


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


def cache_enabled() -> bool:
    return _env_bool("AGENT_D_LLM_CACHE_ENABLED", True)


def cache_strict() -> bool:
    return _env_bool("AGENT_D_LLM_CACHE_STRICT", False)


def llm_model_name() -> str:
    """Agent D 使用全局 MODEL_NAME。"""
    return _env_str("MODEL_NAME") or "gpt-4o-mini"


def llm_model_name_for_cache_key() -> str:
    """cache_key 直接使用 MODEL_NAME，避免同一模型出现两套配置来源。"""
    return llm_model_name()


def default_cache_dir(repo_output_dir: str | None = None) -> str:
    """优先级: AGENT_D_LLM_CACHE_DIR > <repo_output_dir>/_llm_cache > output/_llm_cache。"""
    explicit = _env_str("AGENT_D_LLM_CACHE_DIR").strip()
    if explicit:
        return explicit
    if repo_output_dir:
        return os.path.join(repo_output_dir, "_llm_cache")
    out_root = _env_str("AGENT_OUTPUT_ROOT", "output")
    return os.path.join(out_root, "_llm_cache")


# ─── cache_key 计算 ─────────────────────────────────────────────


def compute_cache_key(
    *,
    template_id: str,
    inputs: Any,
    model_name: str | None = None,
    template_version: str | None = None,
) -> str:
    """cache_key = sha256(template_id | version | model | stable_json(inputs))。

    template_version 必须从 PROMPT_TEMPLATE_VERSIONS 拿；不允许调用方覆盖
    （否则可以伪造缓存）。
    """
    if template_id not in PROMPT_TEMPLATE_VERSIONS:
        raise TemplateVersionMissingError(
            f"template_id={template_id!r} 未在 pipeline_config.PROMPT_TEMPLATE_VERSIONS "
            f"登记。请先在那里加版本号。"
        )
    version = template_version or PROMPT_TEMPLATE_VERSIONS[template_id]
    model = model_name or llm_model_name_for_cache_key()
    payload = "|".join([template_id, version, model, stable_json(inputs)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ─── 缓存读写（基于文件 + 进程内锁，多线程安全）───────────────


_CACHE_LOCK = Lock()


def _cache_path(cache_dir: str, key: str) -> Path:
    return Path(cache_dir) / key[:2] / f"{key}.json"


def cache_get(cache_dir: str, key: str) -> dict | None:
    path = _cache_path(cache_dir, key)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def cache_put(cache_dir: str, key: str, payload: dict) -> None:
    path = _cache_path(cache_dir, key)
    with _CACHE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


# ─── prompt 调试日志 ────────────────────────────────────────────


_PROMPT_LOG_LOCK = Lock()


def _maybe_log_prompt(repo_output_dir: str | None, payload: dict) -> None:
    if not _env_bool("AGENT_D_VERBOSE_PROMPT_LOG", False):
        return
    if not repo_output_dir:
        return
    log_path = Path(repo_output_dir) / "_agent_state" / "prompt_log.jsonl"
    with _PROMPT_LOG_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


# ─── 调用统计（给 _lineage 用）───────────────────────────────────


@dataclass
class CacheStats:
    """累计 LLM 调用统计，最终汇总到产物 _lineage.llm。

    每个 Agent 持有一个 CacheStats 实例，调用 `wrapper.invoke()` 时自动累加。
    """
    cache_keys_used: list[str] = field(default_factory=list)
    calls_total: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    model: str | None = None

    def record(self, key: str, hit: bool) -> None:
        self.cache_keys_used.append(key)
        self.calls_total += 1
        if hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

    @property
    def miss_rate(self) -> float | None:
        return self.cache_misses / self.calls_total if self.calls_total else None


# ─── 主入口：llm_call_cached ───────────────────────────────────


# 调用方必须传一个真正调 LLM 的函数；这样模块本身不依赖任何 LangChain / OpenAI SDK，
# 既方便测试（注入 mock）也方便切 backend。
LLMCallable = Callable[[str, dict], Any]
"""签名: (rendered_prompt, llm_kwargs) -> response_text_or_dict"""


def llm_call_cached(
    *,
    template_id: str,
    inputs: dict,
    render_fn: Callable[[str, dict], str],
    llm_call_fn: LLMCallable,
    cache_dir: str | None = None,
    repo_output_dir: str | None = None,
    stats: CacheStats | None = None,
    model_name: str | None = None,
    template_version: str | None = None,
    extra_metadata: dict | None = None,
) -> dict:
    """统一 LLM 调用入口。

    流程:
      1. 算 cache_key（受 template_id / version / model / inputs 决定）
      2. cache 命中 → 直接返回 (response, metadata)
      3. miss + AGENT_D_LLM_CACHE_STRICT=true → raise（评委复现模式）
      4. miss + 缓存关闭 → 直接调 LLM，不落盘
      5. miss + 缓存开启 → 调 LLM → 落盘 → 返回

    返回结构: {"response": ..., "metadata": {...}, "cache_hit": bool, "cache_key": ...}
    """
    model = model_name or llm_model_name()
    cache_model = model_name or llm_model_name_for_cache_key()
    key = compute_cache_key(
        template_id=template_id,
        inputs=inputs,
        model_name=cache_model,
        template_version=template_version,
    )
    use_cache = cache_enabled()
    cache_root = cache_dir or default_cache_dir(repo_output_dir)

    if use_cache:
        cached = cache_get(cache_root, key)
        if cached is not None:
            if stats is not None:
                stats.record(key, hit=True)
                stats.model = stats.model or cache_model
            return {
                "response": cached["response"],
                "metadata": cached.get("metadata", {}),
                "cache_hit": True,
                "cache_key": key,
            }

    if cache_strict():
        raise CacheStrictMissError(
            f"AGENT_D_LLM_CACHE_STRICT=true 但 cache miss: template={template_id} "
            f"key={key[:8]}...。评委复现模式下不允许联网调 LLM。"
        )

    rendered = render_fn(template_id, inputs)
    started = time.time()
    response = llm_call_fn(
        rendered,
        {
            "model": model,
            "temperature": _env_int("AGENT_D_LLM_TEMPERATURE", 0),
            "seed": _env_int("AGENT_D_LLM_SEED", 42),
            "max_tokens": _env_int("AGENT_D_MAX_OUTPUT_TOKENS", 4096),
            "timeout": _env_int("AGENT_D_LLM_TIMEOUT_SECONDS", 120),
        },
    )
    elapsed_ms = int((time.time() - started) * 1000)
    metadata = {
        "template_id": template_id,
        "template_version": template_version or PROMPT_TEMPLATE_VERSIONS[template_id],
        "model": model,
        "model_for_cache_key": cache_model,
        "elapsed_ms": elapsed_ms,
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **(extra_metadata or {}),
    }
    payload = {
        "key": key,
        "inputs_hash_preview": stable_json(inputs)[:512],
        "response": response,
        "metadata": metadata,
    }

    _maybe_log_prompt(repo_output_dir, {
        "template_id": template_id,
        "key": key,
        "rendered_prompt": rendered,
        "metadata": metadata,
    })

    if use_cache:
        cache_put(cache_root, key, payload)

    if stats is not None:
        stats.record(key, hit=False)
        stats.model = stats.model or cache_model

    return {
        "response": response,
        "metadata": metadata,
        "cache_hit": False,
        "cache_key": key,
    }

