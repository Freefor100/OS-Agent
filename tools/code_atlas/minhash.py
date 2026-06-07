"""固定 seed 的 MinHash + Jaccard 估计。

不依赖 datasketch（额外依赖且不固定 seed），自实现简洁版本。
正确性参考: Indyk, Motwani et al.，每个 hash 函数 h_i(x) = (a_i * x + b_i) mod p

关键性质（pipeline_config 锁死）:
  MINHASH_SEED = 42
  MINHASH_NUM_PERM = 128 / 64
  MINHASH_NGRAM_K = 5

可复现: 同输入同 seed → 同签名 → 同 jaccard estimate（bit-level）。

接口:
  signature_from_tokens(tokens, k=5, num_perm=128) -> list[int]
  signature_from_set(items, num_perm=128) -> list[int]      # 不 k-gram，直接对元素
  jaccard_estimate(sig_a, sig_b) -> float
"""

from __future__ import annotations

import hashlib
import struct
from typing import Iterable

from core.code_atlas.config import (
    MINHASH_NGRAM_K,
    MINHASH_NUM_PERM,
    MINHASH_NUM_PERM_SMALL,
    MINHASH_SEED,
)


# 大于 2^32 的素数，给线性 hash family 用
_MERSENNE_PRIME = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1


def _hash_token(tok: str) -> int:
    """sha1 → 32 bit；无随机性。"""
    digest = hashlib.sha1(tok.encode("utf-8")).digest()
    return struct.unpack("<I", digest[:4])[0]


def _build_permutations(num_perm: int, seed: int) -> tuple[list[int], list[int]]:
    """生成 (a_i, b_i)，i ∈ [0, num_perm)。固定 seed → 固定 permutation。"""
    import random
    rng = random.Random(seed)
    a_list = [rng.randint(1, _MERSENNE_PRIME - 1) for _ in range(num_perm)]
    b_list = [rng.randint(0, _MERSENNE_PRIME - 1) for _ in range(num_perm)]
    return a_list, b_list


# 缓存 permutation（同 seed 同 num_perm 复用）
_PERM_CACHE: dict[tuple[int, int], tuple[list[int], list[int]]] = {}


def _get_permutations(num_perm: int) -> tuple[list[int], list[int]]:
    key = (MINHASH_SEED, num_perm)
    cached = _PERM_CACHE.get(key)
    if cached is None:
        cached = _build_permutations(num_perm, MINHASH_SEED)
        _PERM_CACHE[key] = cached
    return cached


# ─── 主接口 ────────────────────────────────────────────────


def signature_from_set(items: Iterable, *, num_perm: int = MINHASH_NUM_PERM) -> list[int]:
    """对一个 set 算 minhash 签名。

    items: 任意可 str() 的元素。重复无影响（最小 hash 一样）。
    返回 num_perm 个 32-bit minhash 值。
    """
    a_list, b_list = _get_permutations(num_perm)
    sig = [_MAX_HASH] * num_perm

    seen = False
    for item in items:
        seen = True
        h = _hash_token(str(item))
        for i in range(num_perm):
            ph = (a_list[i] * h + b_list[i]) % _MERSENNE_PRIME
            ph &= _MAX_HASH
            if ph < sig[i]:
                sig[i] = ph

    if not seen:
        # 空 set：保持全 _MAX_HASH（与"任何非空 set"jaccard=0）
        return sig
    return sig


def signature_from_tokens(
    tokens: list[str],
    *,
    k: int = MINHASH_NGRAM_K,
    num_perm: int = MINHASH_NUM_PERM,
) -> list[int]:
    """token 列表 → k-gram → minhash。

    k-gram 用空格 join，避免 ['ab','cd'] 与 ['a','bcd'] 撞。
    """
    if len(tokens) == 0:
        return [_MAX_HASH] * num_perm
    if len(tokens) < k:
        # 太短，整段当一个 gram
        return signature_from_set([" ".join(tokens)], num_perm=num_perm)
    grams = [
        " ".join(tokens[i : i + k])
        for i in range(len(tokens) - k + 1)
    ]
    return signature_from_set(grams, num_perm=num_perm)


def jaccard_estimate(sig_a: list[int], sig_b: list[int]) -> float:
    """两个 minhash 签名的 jaccard 估计 = 相同位数 / num_perm。

    要求两签名 num_perm 相同。
    """
    if len(sig_a) != len(sig_b):
        raise ValueError(
            f"jaccard_estimate: 签名长度不一致 {len(sig_a)} vs {len(sig_b)}"
        )
    if not sig_a:
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return matches / len(sig_a)


def small_perm() -> int:
    """方便调用方拿到 small 维度（neighbor / literal / role_set 用）。"""
    return MINHASH_NUM_PERM_SMALL
