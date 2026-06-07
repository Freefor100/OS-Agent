"""LLM 调用后端。

直接使用 openai 包（项目用 DeepSeek / 任意 OpenAI-compatible 接口），
不依赖 langchain。读取 .env 的 OPENAI_API_KEY / OPENAI_API_BASE。

llm_call_cached() 期望的 llm_call_fn 形态：
    call_chat_model(rendered_prompt: str, kwargs: dict) -> dict
"""

from __future__ import annotations

import json
import logging
import os
import time
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_CLIENT_LOCK = Lock()
_CLIENT = None


def _get_client():
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            from openai import OpenAI
            _CLIENT = OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY", ""),
                base_url=os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
            )
        return _CLIENT


def call_chat_model(rendered_prompt: str, kwargs: dict) -> dict:
    """LLMCache 期望的 llm_call_fn。

    返回 dict 形如 {"content": "...", "usage": {...}}。
    """
    model_name = kwargs["model"]
    temperature = float(kwargs.get("temperature", 0))
    max_tokens = int(kwargs.get("max_tokens", 2048))
    timeout = float(kwargs.get("timeout", os.environ.get("AGENT_D_LLM_TIMEOUT_SECONDS", 120)))

    retry_max = int(os.environ.get("AGENT_D_LLM_RETRY_MAX", "3"))
    last_exc: Exception | None = None
    delay = 1.5

    client = _get_client()

    for attempt in range(1, retry_max + 1):
        try:
            t0 = time.time()
            request = {
                "model": model_name,
                "messages": [{"role": "user", "content": rendered_prompt}],
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
            thinking = os.environ.get("AGENT_D_THINKING", "enabled").strip().lower()
            reasoning_effort = os.environ.get("AGENT_D_REASONING_EFFORT", "").strip()
            strict_thinking = os.environ.get("AGENT_D_STRICT_THINKING", "true").strip().lower() in {"1", "true", "yes", "on"}
            if thinking in {"enabled", "on", "true", "1", "max"}:
                if reasoning_effort:
                    request["reasoning_effort"] = reasoning_effort
                request["extra_body"] = {"thinking": {"type": "enabled"}}
                if reasoning_effort:
                    request["extra_body"]["reasoning_effort"] = reasoning_effort
            else:
                request["temperature"] = temperature
                if thinking in {"disabled", "off", "false", "0"}:
                    request["extra_body"] = {"thinking": {"type": "disabled"}}
            try:
                response = client.chat.completions.create(**request)
            except Exception as exc:
                if (reasoning_effort or thinking) and _looks_like_reasoning_param_rejection(exc) and not strict_thinking:
                    logger.warning(
                        "[AgentD-LLM] model/provider rejected reasoning/thinking config (%s); retrying without it because AGENT_D_STRICT_THINKING=false.",
                        reasoning_effort,
                    )
                    request.pop("extra_body", None)
                    request.pop("reasoning_effort", None)
                    request.setdefault("temperature", temperature)
                    response = client.chat.completions.create(**request)
                else:
                    raise
            elapsed = time.time() - t0
            choice = response.choices[0]
            if getattr(choice, "finish_reason", None) == "length":
                raise RuntimeError("LLM output was truncated (finish_reason=length)")
            content = choice.message.content or ""
            if not content.strip():
                raise RuntimeError("LLM returned empty content")
            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens":     response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens":      response.usage.total_tokens,
                }
                reasoning_tokens = getattr(getattr(response.usage, "completion_tokens_details", None), "reasoning_tokens", None)
                if reasoning_tokens is not None:
                    usage["reasoning_tokens"] = reasoning_tokens
            return {
                "content": content,
                "usage": usage,
                "elapsed_seconds": round(elapsed, 3),
                "attempt": attempt,
                "thinking": thinking,
                "reasoning_effort": reasoning_effort,
            }
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "[AgentD-LLM] invoke 第 %d/%d 次失败 (%s): %s。%.1fs 后重试。",
                attempt, retry_max, type(exc).__name__, exc, delay,
            )
            if attempt < retry_max:
                time.sleep(delay)
                delay *= 2

    raise RuntimeError(f"LLM 调用 {retry_max} 次全失败: {last_exc}") from last_exc


def _looks_like_reasoning_param_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "reasoning",
            "reasoning_effort",
            "extra_body",
            "unknown parameter",
            "unsupported parameter",
            "unrecognized request argument",
        )
    )


# ─── JSON 解析辅助 ────────────────────────────────────────────


def parse_llm_json(content: str) -> Any:
    """从 LLM 输出抽 JSON。容忍 ```json ... ``` 代码块、前后噪声文本。"""
    if not content:
        raise ValueError("LLM content 为空")
    text = content.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl > 0:
            text = text[first_nl + 1:]
        end = text.rfind("```")
        if end > 0:
            text = text[:end]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [text.find(c) for c in "{[" if text.find(c) >= 0]
    if not starts:
        raise ValueError(f"无法找到 JSON 起始，content head: {content[:200]!r}")
    start = min(starts)
    for end in range(len(text), start, -1):
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
    raise ValueError(f"无法解析 JSON, content head: {content[:200]!r}")

