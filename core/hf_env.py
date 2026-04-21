"""
Hugging Face Hub 环境：默认国内镜像、优先本地缓存加载嵌入模型。

规则（仅此一条，易记）：
- **未设置 HF_ENDPOINT**（环境变量里为空）：默认写入国内镜像 `OS_AGENT_HF_ENDPOINT` 或 `https://hf-mirror.com`（可用 `OS_AGENT_USE_HF_MIRROR=false` 关闭默认，此时走库默认官方）。
- **已在 .env / 系统里设置了 HF_ENDPOINT**（含 `https://huggingface.co`）：**一律按该值访问**，不做改写。
- 嵌入模型先 local_files_only + 离线；失败再经当前 HF_ENDPOINT 联网补全缺失文件。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_HF_MIRROR = "https://hf-mirror.com"
_defaults_applied = False


def apply_hf_hub_env_defaults() -> None:
    """
    在进程早期调用（如 load_dotenv 之后）。幂等。

    - HF_ENDPOINT 已有值：原样使用（.env 写官方即官方、写镜像即镜像）。
    - HF_ENDPOINT 为空：默认补成国内镜像（除非关闭 OS_AGENT_USE_HF_MIRROR）。
    """
    global _defaults_applied
    mirror_on = os.environ.get("OS_AGENT_USE_HF_MIRROR", "true").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    raw = (os.environ.get("HF_ENDPOINT") or "").strip().rstrip("/")

    if raw:
        if not _defaults_applied:
            logger.info("HF_ENDPOINT 已显式指定为 %s，按该基址访问 Hub", raw)
    elif mirror_on:
        mirror_ep = (os.environ.get("OS_AGENT_HF_ENDPOINT") or DEFAULT_HF_MIRROR).strip().rstrip(
            "/"
        )
        if mirror_ep:
            os.environ["HF_ENDPOINT"] = mirror_ep
            if not _defaults_applied:
                logger.info("HF_ENDPOINT 未设置，默认使用国内镜像 %s", mirror_ep)
    elif not _defaults_applied:
        logger.info("HF_ENDPOINT 未设置且 OS_AGENT_USE_HF_MIRROR=false，将使用库默认官方 Hub")

    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "180")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")
    _defaults_applied = True

    ep_final = (os.environ.get("HF_ENDPOINT") or "").strip().rstrip("/")
    if ep_final:
        logger.info("Hugging Face Hub 基址 HF_ENDPOINT=%s", ep_final)
    else:
        logger.info("HF_ENDPOINT 未设置，Hub 将使用 huggingface_hub 库默认（官方）")


def load_sentence_transformer_for_embedding(
    model_name: str,
    *,
    trust_remote_code: bool = True,
    device: Optional[str] = None,
    model_kwargs: Optional[Dict[str, Any]] = None,
):
    """
    加载代码嵌入用 SentenceTransformer：先仅用本地缓存；失败则联网（走 HF_ENDPOINT，默认可为镜像）。
    """
    apply_hf_hub_env_defaults()
    import torch
    from sentence_transformers import SentenceTransformer

    mk = dict(model_kwargs or {})
    dev = device if device is not None else ("cuda" if torch.cuda.is_available() else "cpu")

    def _build(*, local_files_only: bool) -> Any:
        return SentenceTransformer(
            model_name,
            trust_remote_code=trust_remote_code,
            local_files_only=local_files_only,
            device=dev,
            model_kwargs=mk,
        )

    old_hf = os.environ.get("HF_HUB_OFFLINE")
    old_tf = os.environ.get("TRANSFORMERS_OFFLINE")
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        model = _build(local_files_only=True)
        logger.info("嵌入模型已从本地缓存加载: %s", model_name)
        return model
    except Exception as e:
        logger.warning(
            "嵌入模型纯本地加载失败，将经 HF_ENDPOINT=%s 联网拉取缺失文件: %s",
            os.environ.get("HF_ENDPOINT", "(默认)"),
            e,
        )
    finally:
        if old_hf is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old_hf
        if old_tf is None:
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
        else:
            os.environ["TRANSFORMERS_OFFLINE"] = old_tf

    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    model = _build(local_files_only=False)
    logger.info("嵌入模型联网加载完成: %s", model_name)
    return model
