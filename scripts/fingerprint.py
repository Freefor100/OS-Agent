#!/usr/bin/env python3
"""Fingerprint building — pure computation, no judgment, no similarity.

Two fingerprint sources, unified output schema:
  - c / cpp / rust  -> code_atlas (tree-sitter) functions -> token hash + AST shape hash
  - asm (.S/.s)     -> asm_tokenize label-blocks -> minhash exact-token hash

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
import json
import pickle
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.code_atlas.builder import build_code_atlas
from core.evidence import stable_id
from core.snapshot import RepoSnapshot, resolve_snapshot
from tools.code_atlas.asm_tokenize import tokenize_asm
from tools.code_atlas.minhash import signature_from_tokens


def _semantic_fn_id(fn: dict) -> str:
    """Stable id from normalized tokens + AST shape — same inputs, same id."""
    tokens = fn.get("tokens_normalized") or fn.get("normalized_tokens") or fn.get("signature") or fn.get("name", "")
    text = " ".join(tokens) if isinstance(tokens, list) else str(tokens)
    return stable_id("sfn", {"tokens": text, "ast": fn.get("ast_shape_hash", "")}, 16)


def _fn_structure_fingerprint(fn: dict) -> dict:
    """Normalized-token fingerprint + AST shape hash for a code unit."""
    tokens = fn.get("tokens_normalized") or fn.get("normalized_tokens") or []
    token_text = " ".join(tokens) if isinstance(tokens, list) else str(tokens)
    literals = fn.get("literal_set") or []
    return {
        "semantic_fn_id": _semantic_fn_id(fn),
        "path": str(fn.get("file", "")).replace("\\", "/"),
        "symbol": fn.get("name", ""),
        "ast_shape_hash": fn.get("ast_shape_hash"),
        "normalized_token_fingerprint": stable_id("ntok", {"tokens": token_text}, 64),
        "literal_fingerprint": stable_id("lit", {"literals": sorted(map(str, literals))}, 16) if literals else "",
    }

CODE_LANGS = ("c", "cpp", "rust")
ASM_MIN_TOK = 12          # asm blocks below this are too generic (save/restore stubs)
CACHE = Path(".fp_cache")
FINGERPRINT_SCHEMA = "fingerprint_v4_sha256_full_token_commit_snapshot"


def _cache_path(prefix: str, repo_path: str, commit: str = "", tree_hash: str = "") -> Path:
    """Commit-aware cache key. Branch aliases that point to one commit share a cache."""
    name = Path(repo_path).name
    if commit:
        schema_tag = FINGERPRINT_SCHEMA.replace("fingerprint_", "fp-").replace("_", "-")
        return CACHE / f"{prefix}_{name}__{commit[:16]}__{tree_hash[:12] or 'tree-unknown'}__{schema_tag}.pkl"
    return CACHE / f"{prefix}_{name}.pkl"


def _asm_fp(tokens: list[str]) -> str:
    """Exact hash of normalized asm token stream (mirrors the code ntok hash)."""
    return "ntok_" + hashlib.sha256(" ".join(tokens).encode()).hexdigest()


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


def build_units(repo_path: str, *, branch: str = "", ref: str = "", snapshot: RepoSnapshot | None = None,
                use_cache: bool = True) -> list[dict]:
    """Build units from an immutable Git commit snapshot.

    `branch` remains a compatibility alias for `ref`. It is resolved to a commit
    before source is read, so dirty working-tree files never affect fingerprints.
    """
    snap = snapshot or resolve_snapshot(repo_path, ref or branch or "HEAD")
    cf = _cache_path("units", repo_path, snap.commit, snap.tree_hash)
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())

    units: list[dict] = []
    atlas = code_atlas(repo_path, snapshot=snap, use_cache=use_cache)
    functions = atlas.get("functions", {})
    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {}
    for edge in atlas.get("edges", []):
        src = str(edge.get("src_fn_id") or "")
        dst = str(edge.get("dst_fn_id") or "")
        callee = str(edge.get("callee_name") or "")
        if src and callee:
            outgoing.setdefault(src, set()).add(callee)
        if dst and src:
            incoming.setdefault(dst, set()).add(str(functions.get(src, {}).get("name") or src))

    for fn_id, fn in functions.items():
        lang = fn.get("lang")
        if lang not in CODE_LANGS:
            continue
        fp = _fn_structure_fingerprint(fn)
        tokens = fn.get("tokens_normalized") or []
        units.append({
            "unit_id": stable_id("unit", {"snapshot": snap.snapshot_id, "fn": fn_id}, 16),
            "lang": lang, "file": str(fn.get("file", "")).replace("\\", "/"),
            "name": fn.get("name", ""), "line": fn.get("line", 0), "end_line": fn.get("end_line", 0),
            "fp": fp["normalized_token_fingerprint"], "ast": fp.get("ast_shape_hash", ""),
            "sz": len(tokens), "sig": signature_from_tokens(tokens), "fn_id": fn_id,
            "snapshot_id": snap.snapshot_id, "commit": snap.commit,
            "outgoing_names": sorted(outgoing.get(fn_id, set())),
            "incoming_names": sorted(incoming.get(fn_id, set())),
        })

    repo = Path(snap.materialized_path)
    for rel, label, toks in _iter_asm_units(repo):
        units.append({
            "unit_id": stable_id("unit", {"snapshot": snap.snapshot_id, "file": rel, "label": label}, 16),
            "lang": "asm", "file": rel, "name": label, "line": 0, "end_line": 0,
            "fp": _asm_fp(toks), "ast": "", "sz": len(toks), "sig": signature_from_tokens(toks),
            "snapshot_id": snap.snapshot_id, "commit": snap.commit,
            "outgoing_names": [], "incoming_names": [],
        })

    CACHE.mkdir(exist_ok=True)
    cf.write_bytes(pickle.dumps(units))
    _write_cache_meta(repo_path, snap)
    return units


def code_atlas(repo_path: str, *, branch: str = "", ref: str = "", snapshot: RepoSnapshot | None = None,
               use_cache: bool = True) -> dict:
    """Build or load the immutable commit's full structural atlas for Agent navigation."""
    snap = snapshot or resolve_snapshot(repo_path, ref or branch or "HEAD")
    cf = _cache_path("atlas2", repo_path, snap.commit, snap.tree_hash)
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())
    atlas = build_code_atlas(repo_path=snap.materialized_path, repo_name=snap.repo)
    CACHE.mkdir(exist_ok=True)
    cf.write_bytes(pickle.dumps(atlas))
    _write_cache_meta(repo_path, snap)
    return atlas


def fingerprint_set(repo_path: str, *, branch: str = "", ref: str = "", snapshot: RepoSnapshot | None = None,
                    use_cache: bool = True) -> set[str]:
    snap = snapshot or resolve_snapshot(repo_path, ref or branch or "HEAD")
    cf = _cache_path("fpset", repo_path, snap.commit, snap.tree_hash)
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())
    result = {u["fp"] for u in build_units(repo_path, snapshot=snap, use_cache=use_cache)}
    CACHE.mkdir(exist_ok=True); cf.write_bytes(pickle.dumps(result))
    return result


def ast_fingerprint_set(repo_path: str, *, branch: str = "", ref: str = "", snapshot: RepoSnapshot | None = None,
                        use_cache: bool = True) -> set[str]:
    snap = snapshot or resolve_snapshot(repo_path, ref or branch or "HEAD")
    cf = _cache_path("astset", repo_path, snap.commit, snap.tree_hash)
    if use_cache and cf.exists():
        return pickle.loads(cf.read_bytes())
    units = build_units(repo_path, snapshot=snap, use_cache=use_cache)
    result = {u["ast"] for u in units if u.get("ast") and u["lang"] != "asm"}
    CACHE.mkdir(exist_ok=True); cf.write_bytes(pickle.dumps(result))
    return result


def cache_metadata(repo_path: str, ref: str = "HEAD") -> dict[str, Any]:
    snap = resolve_snapshot(repo_path, ref, materialize=False)
    path = _cache_path("meta", repo_path, snap.commit, snap.tree_hash).with_suffix(".json")
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return snap.to_dict() | {"fingerprint_schema": FINGERPRINT_SCHEMA}


def _write_cache_meta(repo_path: str, snapshot: RepoSnapshot) -> None:
    path = _cache_path("meta", repo_path, snapshot.commit, snapshot.tree_hash).with_suffix(".json")
    path.write_text(json.dumps(snapshot.to_dict() | {"fingerprint_schema": FINGERPRINT_SCHEMA},
                               ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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
    print(f"  asm units: {summ.get('asm', 0)}")
