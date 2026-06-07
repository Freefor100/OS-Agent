"""
DeepSeek Thinking Mode compatibility patch for langchain-openai.

Problem:
- DeepSeek V4 thinking mode returns `reasoning_content`.
- If a thinking turn performs tool calls, DeepSeek requires the *full* assistant
  message (including `reasoning_content`) to be passed back in subsequent requests.
- langchain-openai explicitly warns it does NOT preserve non-standard fields
  like `reasoning_content`, so multi-turn tool-call agents can hit:
  400: The `reasoning_content` in the thinking mode must be passed back to the API.

Fix:
- Monkeypatch langchain_openai.chat_models.base conversion helpers to:
  - Preserve `reasoning_content` from provider responses into AIMessage.additional_kwargs
  - Include `reasoning_content` from AIMessage.additional_kwargs back into outbound
    message dicts sent to the provider.
  - Preserve streamed `reasoning_content` deltas into message chunks.

This patch is designed to be:
- **Idempotent** (safe to call multiple times)
- **Narrow** (only touches `reasoning_content`)
"""

from __future__ import annotations

from typing import Any, Mapping


_PATCHED = False


def apply_deepseek_reasoning_content_patch() -> bool:
    """Apply monkeypatch. Returns True if patched in this call."""
    global _PATCHED
    if _PATCHED:
        return False

    try:
        from langchain_openai.chat_models import base as lc_openai_base
    except Exception:
        return False

    # Guard: only patch once per process.
    if getattr(lc_openai_base, "_OS_AGENT_DEEPSEEK_REASONING_PATCHED", False):
        _PATCHED = True
        return False

    orig_convert_dict_to_message = lc_openai_base._convert_dict_to_message
    orig_convert_message_to_dict = lc_openai_base._convert_message_to_dict
    orig_convert_delta_to_message_chunk = lc_openai_base._convert_delta_to_message_chunk

    def _convert_dict_to_message_patched(_dict: Mapping[str, Any]):
        msg = orig_convert_dict_to_message(_dict)
        # Preserve provider-specific `reasoning_content` for DeepSeek thinking mode.
        if isinstance(_dict, Mapping) and "reasoning_content" in _dict:
            rc = _dict.get("reasoning_content")
            if rc is not None:
                try:
                    msg.additional_kwargs["reasoning_content"] = rc
                except Exception:
                    # Shouldn't happen, but keep safety.
                    pass
        return msg

    def _convert_message_to_dict_patched(message, api="chat/completions"):
        d = orig_convert_message_to_dict(message, api=api)
        # If we have preserved reasoning_content, pass it back to provider.
        rc = None
        try:
            rc = (message.additional_kwargs or {}).get("reasoning_content")
        except Exception:
            rc = None
        if rc is not None and isinstance(d, dict):
            d["reasoning_content"] = rc
        return d

    def _convert_delta_to_message_chunk_patched(
        _dict: Mapping[str, Any], default_class
    ):
        chunk = orig_convert_delta_to_message_chunk(_dict, default_class)
        if isinstance(_dict, Mapping) and "reasoning_content" in _dict:
            rc = _dict.get("reasoning_content")
            if rc is not None:
                try:
                    chunk.additional_kwargs["reasoning_content"] = rc
                except Exception:
                    pass
        return chunk

    lc_openai_base._convert_dict_to_message = _convert_dict_to_message_patched
    lc_openai_base._convert_message_to_dict = _convert_message_to_dict_patched
    lc_openai_base._convert_delta_to_message_chunk = _convert_delta_to_message_chunk_patched
    lc_openai_base._OS_AGENT_DEEPSEEK_REASONING_PATCHED = True

    _PATCHED = True
    return True

