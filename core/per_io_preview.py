"""终端长预览与 LLM 调用日志（Plan / Verify / Patch / Repair 共用）。"""
from __future__ import annotations

from typing import Any, List, Optional


def print_agent_long_preview(
    title_line: str,
    body: str,
    *,
    max_chars: int = 6000,
    max_lines: int = 120,
    indent: str = "   ",
) -> None:
    """
    多行块预览，风格接近 Execute 里「Agent:」长回复。
    """
    print(f"\n{title_line}")
    if not (body or "").strip():
        print(f"{indent}（空）")
        return
    excerpt = body[:max_chars]
    lines = excerpt.splitlines()
    truncated_lines = len(lines) > max_lines
    if truncated_lines:
        lines = lines[:max_lines]
    for ln in lines:
        print(indent + ln)
    if truncated_lines:
        print(f"{indent}…（预览最多 {max_lines} 行）")
    if len(body) > max_chars:
        print(f"{indent}…（预览最多 {max_chars:,} 字符，全文 {len(body):,} 字符）")
    else:
        print(f"{indent}📄 全文 {len(body):,} 字符")


def log_llm_text_call_out(
    phase: str,
    prompt: str,
    *,
    mode: str = "单次 llm.invoke（无 ReAct / 无工具循环）",
    extras: Optional[List[str]] = None,
) -> None:
    print(f"   📤 {phase} 已发送: 文本提示 ≈{len(prompt):,} 字符")
    print(f"      · {mode}")
    for line in extras or []:
        print(f"      · {line}")


def log_llm_response_tokens(phase: str, resp: Any) -> None:
    meta = getattr(resp, "response_metadata", None) or {}
    usage = meta.get("token_usage") if isinstance(meta, dict) else None
    if isinstance(usage, dict) and usage:
        total = usage.get("total_tokens", 0) or 0
        inp = usage.get("prompt_tokens", 0) or 0
        out = usage.get("completion_tokens", 0) or 0
        print(f"   📄 {phase} Tokens: {total:,} (输入:{inp:,} + 输出:{out:,})")
    else:
        print(f"   📄 {phase} Tokens: （本响应未携带 token_usage，以计费面板为准）")
