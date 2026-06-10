#!/usr/bin/env python3
"""Stage-1 fingerprint building — pure, deterministic, no similarity, no LLM.

This module ONLY builds fingerprints for one repo. It does NOT compare anything.
Similarity/classification lives in provenance.py (which now consumes this).

Two fingerprint sources, unified output schema:
  - c / cpp / rust  -> code_atlas (tree-sitter) functions -> _fn_structure_fingerprint
  - asm (.S/.s)     -> asm_tokenize label-blocks -> minhash exact-token hash
                       (code_atlas can't parse asm; was v1's blind spot, DESIGN 5.4)

Unit schema (one dict per code unit, function or asm label-block):
  {
    "lang":  "c"|"cpp"|"rust"|"asm",
    "file":  "rel/path",
    "name":  symbol / label,
    "line":  int,
    "fp":    exact normalized-token hash (str)    # cross-repo identity key
    "sz":    token count (int)                     # for the PEER floor
    "sig":   minhash signature (list[int]) | None  # graded similarity (asm uses it)
  }

Caching: per-repo unit list -> .fp_cache/units_<name>.pkl; fingerprint-only set
-> .fp_cache/fpset_<name>.pkl (for 1-vs-N peer reuse).
"""
from __future__ import annotations

import hashlib
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.code_atlas.builder import build_code_atlas
from core.evidence import stable_id
from tools.code_atlas.asm_tokenize import tokenize_asm
from tools.code_atlas.minhash import signature_from_tokens


def _semantic_fn_id(fn: dict) -> str:
    """Stable id from normalized tokens + AST shape — same inputs, same id."""
    tokens = fn.get("tokens_normalized") or fn.get("normalized_tokens") or fn.get("signature") or fn.get("name", "")
    text = " ".join(tokens[:200]) if isinstance(tokens, list) else str(tokens)[:1000]
    return stable_id("sfn", {"tokens": text, "ast": fn.get("ast_shape_hash", "")}, 16)


def _fn_structure_fingerprint(fn: dict) -> dict:
    """Extracted from agent_d.py. Returns {normalized_token_fingerprint, ast_shape_hash, ...}."""
    tokens = fn.get("tokens_normalized") or fn.get("normalized_tokens") or []
    token_text = " ".join(tokens[:400]) if isinstance(tokens, list) else str(tokens)[:2000]
    literals = fn.get("literal_set") or []
    return {
        "semantic_fn_id": _semantic_fn_id(fn),
        "path": str(fn.get("file", "")).replace("\\", "/"),
        "symbol": fn.get("name", ""),
        "ast_shape_hash": fn.get("ast_shape_hash"),
        "normalized_token_fingerprint": stable_id("ntok", {"tokens": token_text}, 16),
        "literal_fingerprint": stable_id("lit", {"literals": sorted(map(str, literals))}, 16) if literals else "",
    }

CODE_LANGS = ("c", "cpp", "rust")
ASM_MIN_TOK = 12          # asm blocks below this are too generic (save/restore stubs)
CACHE = Path(".fp_cache")


def _asm_fp(tokens: list[str]) -> str:
    """Exact hash of normalized asm token stream (mirrors the code ntok hash)."""
    return "ntok_" + hashlib.sha256(" ".join(tokens).encode()).hexdigest()[:16]


def _iter_asm_units(repo: Path):
    """Yield (rel_path, label, tokens) for every asm label-block >= ASM_MIN_TOK."""
    for f in list(repo.rglob("*.S")) + list(repo.rglob("*.s")):
        if "/.git/" in str(f):
            continue
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        rel = str(f.relative_to(repo)).replace("\\", "/")
        for label, toks in tokenize_asm(txt):
            if len(toks) >= ASM_MIN_TOK:
                yield rel, label, toks


def build_units(repo_path: str, *, use_cache: bool = True) -> list[dict]:
    """Build the unified unit list for one repo (code + asm). Cached."""
    name = Path(repo_path).name
    cf = CACHE / f"units_{name}.pkl"
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())

    units: list[dict] = []

    atlas = build_code_atlas(repo_path=repo_path, repo_name=name)
    for fn_id, fn in atlas.get("functions", {}).items():
        lang = fn.get("lang")
        if lang not in CODE_LANGS:
            continue
        fp = _fn_structure_fingerprint(fn)
        units.append({
            "lang": lang,
            "file": str(fn.get("file", "")).replace("\\", "/"),
            "name": fn.get("name", ""),
            "line": fn.get("line", 0),
            "fp": fp["normalized_token_fingerprint"],
            "ast": fp.get("ast_shape_hash", ""),  # AST structure hash (ignores names/literals)
            "sz": len(fn.get("tokens_normalized") or []),
            "sig": None,
            "fn_id": fn_id,
        })

    repo = Path(repo_path)
    for rel, label, toks in _iter_asm_units(repo):
        units.append({
            "lang": "asm",
            "file": rel,
            "name": label,
            "line": 0,
            "fp": _asm_fp(toks),
            "sz": len(toks),
            "sig": signature_from_tokens(toks),
        })

    CACHE.mkdir(exist_ok=True)
    cf.write_bytes(pickle.dumps(units))
    return units


def fingerprint_set(repo_path: str, *, use_cache: bool = True) -> set[str]:
    """Just the set of exact fingerprints (1-vs-N peer membership). Cached."""
    name = Path(repo_path).name
    cf = CACHE / f"fpset_{name}.pkl"
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())
    s = {u["fp"] for u in build_units(repo_path, use_cache=use_cache)}
    CACHE.mkdir(exist_ok=True)
    cf.write_bytes(pickle.dumps(s))
    return s


def ast_fingerprint_set(repo_path: str, *, use_cache: bool = True) -> set[str]:
    """AST shape hash set for a repo (code-only; asm has no tree-sitter AST).

    Always reads from units but caches the final set. If the units cache is
    stale (from before ast was added), rebuilds once.
    """
    name = Path(repo_path).name
    cf = CACHE / f"astset_{name}.pkl"
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())
    units = build_units(repo_path, use_cache=use_cache)
    s = {u["ast"] for u in units if u.get("ast") and u["lang"] != "asm"}
    if s:
        CACHE.mkdir(exist_ok=True)
        cf.write_bytes(pickle.dumps(s))
    return s


def lang_summary(units: list[dict]) -> dict[str, int]:
    """Unit count per language — for the report's explicit coverage statement."""
    out: dict[str, int] = {}
    for u in units:
        out[u["lang"]] = out.get(u["lang"], 0) + 1
    return out


if __name__ == "__main__":  # build only; proves no similarity is computed
    repo = sys.argv[1]
    units = build_units(f"repos/{repo}" if "/" not in repo else repo)
    summ = lang_summary(units)
    print(f"{repo}: {len(units)} units  {summ}")
    print(f"  asm units: {summ.get('asm', 0)}  (v1 dropped all of these)")
