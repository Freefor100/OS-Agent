from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any


SOURCE_EXTS = {".c", ".h", ".S", ".s", ".rs", ".cpp", ".cc", ".hpp", ".ld", ".lds", ".toml", ".mk", ".cmake", ".txt", ".md", ".pdf", ".docx"}
TEXT_NAMES = {"Makefile", "makefile", "justfile", ".gitignore", ".os_agent_lsp_target"}
_PERSIST_LOCKS: dict[str, Lock] = {}
_PERSIST_LOCKS_GUARD = Lock()


def stable_id(prefix: str, payload: Any, length: int = 12) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:length]}"


@dataclass
class NegativeSearchPlan:
    snapshot_commit: str
    subject: str
    queries: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=lambda: ["keyword_search", "symbol_search", "entry_call_search"])
    plan_id: str = ""

    def finalize(self) -> "NegativeSearchPlan":
        if not self.plan_id:
            self.plan_id = stable_id("negplan", {
                "commit": self.snapshot_commit, "subject": self.subject, "queries": sorted(self.queries),
                "symbols": sorted(self.symbols), "paths": sorted(self.paths), "extensions": sorted(self.extensions),
                "required_checks": sorted(self.required_checks),
            }, 16)
        return self


def execute_negative_search(repo_path: str, plan: NegativeSearchPlan, store: "EvidenceStore") -> dict[str, Any]:
    plan.finalize()
    root = Path(repo_path).resolve()
    search_roots = [(root / p).resolve() for p in (plan.paths or ["."])]
    valid_roots = [p for p in search_roots if p.exists() and (p == root or root in p.parents)]
    extensions = set(plan.extensions or [".c", ".h", ".S", ".s", ".rs", ".cpp", ".cc", ".hpp", ".ld", ".toml", ".mk"])
    patterns: list[tuple[str, str]] = []
    patterns.extend(("keyword_search", query) for query in plan.queries)
    patterns.extend(("symbol_search", symbol) for symbol in plan.symbols)
    patterns.extend(("entry_call_search", rf"\b{re.escape(symbol)}\s*\(") for symbol in plan.symbols)
    executed_checks = sorted({kind for kind, _ in patterns})
    hits: list[dict[str, Any]] = []
    scanned_files = 0
    for base in valid_roots:
        files = [base] if base.is_file() else base.rglob("*")
        for path in files:
            if not path.is_file() or (path.suffix not in extensions and path.name not in TEXT_NAMES):
                continue
            if not _is_text_file(path):
                continue
            scanned_files += 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            for check, query in patterns:
                try:
                    match = re.search(query, text, re.IGNORECASE)
                except re.error:
                    match = re.search(re.escape(query), text, re.IGNORECASE)
                if match:
                    line = text[:match.start()].count("\n") + 1
                    hits.append({"path": path.relative_to(root).as_posix(), "line": line, "query": query, "check": check})
                    if len(hits) >= 200:
                        break
            if len(hits) >= 200:
                break
    coverage_complete = bool(valid_roots and patterns and scanned_files > 0 and set(plan.required_checks).issubset(executed_checks))
    candidate = EvidenceCandidate(
        tool="negative_search", kind="negative_search", query=plan.subject, label=plan.subject, strength="strong" if coverage_complete else "weak",
        metadata={"plan_id": plan.plan_id, "snapshot_commit": plan.snapshot_commit, "searched_paths": [str(p.relative_to(root)) for p in valid_roots],
                  "executed_queries": [query for _, query in patterns], "executed_checks": executed_checks, "extensions": sorted(extensions),
                  "scanned_files": scanned_files, "matches": len(hits), "coverage_complete": coverage_complete,
                  "required_checks": plan.required_checks, "hits": hits[:50]},
    )
    evidence_id = store.add(candidate)
    return {"plan": asdict(plan), "evidence_id": evidence_id, "coverage_complete": coverage_complete, "executed_checks": executed_checks,
            "scanned_files": scanned_files, "matches": hits}


@dataclass
class EvidenceCandidate:
    tool: str
    kind: str
    path: str = ""
    line_start: int | None = None
    line_end: int | None = None
    symbol: str = ""
    label: str = ""
    strength: str = "medium"
    content: str = ""
    query: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceRecord:
    evidence_id: str
    verified: bool
    strength: str
    tool: str
    kind: str
    path: str = ""
    line_start: int | None = None
    line_end: int | None = None
    symbol: str = ""
    label: str = ""
    query: str = ""
    excerpt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    verifier_notes: list[str] = field(default_factory=list)

    def compact(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "strength": self.strength,
            "path": self.path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "symbol": self.symbol,
            "label": self.label,
            "verified": self.verified,
        }


def _safe_read_lines(repo_path: str, rel_path: str) -> list[str]:
    if not rel_path:
        return []
    root = Path(repo_path).resolve()
    path = (root / rel_path).resolve()
    if root not in path.parents and path != root:
        return []
    if not path.is_file():
        return []
    if not _is_text_file(path):
        return []
    try:
        return _clean_text(path.read_text(encoding="utf-8", errors="ignore")).splitlines()
    except OSError:
        return []


class EvidenceStore:
    """Tool-owned evidence registry.

    Agents request evidence, but only this verifier creates `evidence_id`.
    Strong conclusions should cite strong source/config/LSP/call-graph evidence.
    """

    def __init__(self, repo_path: str, persist_path: str | None = None):
        self.repo_path = repo_path
        self.records: dict[str, EvidenceRecord] = {}
        self.offsets: dict[str, int] = {}
        self.cache: OrderedDict[str, EvidenceRecord] = OrderedDict()
        self.cache_limit = max(8, int(os.environ.get("AGENT_D_EVIDENCE_CACHE_RECORDS", "128")))
        self.lock = Lock()
        self.persist_path = Path(persist_path) if persist_path else None
        if self.persist_path:
            key = str(self.persist_path.resolve())
            with _PERSIST_LOCKS_GUARD:
                self.persist_lock = _PERSIST_LOCKS.setdefault(key, Lock())
        else:
            self.persist_lock = Lock()
        if self.persist_path and self.persist_path.is_file():
            self._load_jsonl(self.persist_path)

    def add(self, cand: EvidenceCandidate) -> str:
        record = self._verify(cand)
        changed = False
        with self.lock:
            old = self.records.get(record.evidence_id)
            if old is None or _rank_strength(record.strength) > _rank_strength(old.strength):
                self.records[record.evidence_id] = _compact_record(record)
                self._cache_put(record)
                changed = True
        if changed and self.persist_path:
            with self.persist_lock:
                self._append_record(record)
        return record.evidence_id

    def add_source(self, *, kind: str, path: str, line: int, line_end: int | None = None, symbol: str = "", label: str = "", strength: str = "strong", metadata: dict[str, Any] | None = None) -> str:
        return self.add(EvidenceCandidate(
            tool="source_reader",
            kind=kind,
            path=path,
            line_start=line,
            line_end=line_end,
            symbol=symbol,
            label=label or symbol,
            strength=strength,
            metadata=metadata or {},
        ))

    def add_negative(self, *, query: str, searched_paths: list[str], label: str = "") -> str:
        return self.add(EvidenceCandidate(
            tool="negative_search",
            kind="negative_search",
            query=query,
            label=label or query,
            strength="medium",
            metadata={"searched_paths": searched_paths, "matches": 0},
        ))

    def by_id(self, evidence_id: str) -> EvidenceRecord | None:
        with self.lock:
            cached = self.cache.get(evidence_id)
            if cached is not None:
                self.cache.move_to_end(evidence_id)
                return cached
            compact = self.records.get(evidence_id)
            offset = self.offsets.get(evidence_id)
        if compact is None:
            return None
        if self.persist_path and offset is not None:
            try:
                with self.persist_path.open("rb") as handle:
                    handle.seek(offset)
                    raw = json.loads(handle.readline().decode("utf-8"))
                record = EvidenceRecord(**raw)
                with self.lock:
                    self._cache_put(record)
                return record
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
                pass
        return compact

    def compact_many(self, evidence_ids: list[str]) -> list[dict[str, Any]]:
        with self.lock:
            return [self.records[eid].compact() for eid in evidence_ids if eid in self.records]

    def write_jsonl(self, path: str) -> None:
        target = Path(path)
        if self.persist_path and target.resolve() == self.persist_path.resolve():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(self.iter_full(), key=lambda r: r.evidence_id)
        content = "".join(json.dumps(asdict(rec), ensure_ascii=False, sort_keys=True) + "\n" for rec in rows)
        last_error: OSError | None = None
        for attempt in range(6):
            tmp = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                with _file_lock(str(target)):
                    tmp.write_text(content, encoding="utf-8")
                    os.replace(tmp, target)
                return
            except OSError as exc:
                last_error = exc
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                time.sleep(0.02 * (attempt + 1))
        raise last_error or OSError(f"failed to write {target}")

    def _load_jsonl(self, path: Path) -> None:
        loaded: dict[str, EvidenceRecord] = {}
        offsets: dict[str, int] = {}
        try:
            with path.open("rb") as f:
                while True:
                    offset = f.tell()
                    raw_line = f.readline()
                    if not raw_line:
                        break
                    if not raw_line.strip():
                        continue
                    try:
                        raw = json.loads(raw_line.decode("utf-8"))
                        record = EvidenceRecord(**raw)
                    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                        continue
                    old = loaded.get(record.evidence_id)
                    if old is None or _rank_strength(record.strength) > _rank_strength(old.strength):
                        loaded[record.evidence_id] = _compact_record(record)
                        offsets[record.evidence_id] = offset
        except OSError:
            return
        self.records.update(loaded)
        self.offsets.update(offsets)

    def iter_full(self):
        with self.lock:
            evidence_ids = list(self.records)
        for evidence_id in evidence_ids:
            record = self.by_id(evidence_id)
            if record is not None:
                yield record

    def _cache_put(self, record: EvidenceRecord) -> None:
        self.cache[record.evidence_id] = record
        self.cache.move_to_end(record.evidence_id)
        while len(self.cache) > self.cache_limit:
            self.cache.popitem(last=False)

    def _append_record(self, record: EvidenceRecord) -> None:
        if not self.persist_path:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        with _file_lock(str(self.persist_path)):
            with self.persist_path.open("ab") as handle:
                offset = handle.tell()
                handle.write(payload)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        with self.lock:
            self.offsets[record.evidence_id] = offset

    def _verify(self, cand: EvidenceCandidate) -> EvidenceRecord:
        notes: list[str] = []
        verified = False
        excerpt = cand.content or ""
        line_end = cand.line_end

        if cand.kind == "negative_search":
            verified = (cand.tool == "negative_search" and cand.metadata.get("matches", 1) == 0 and bool(cand.metadata.get("coverage_complete")))
            notes.append("negative search verified by tool result" if verified else "negative search missing zero-match proof")
        elif cand.kind == "documentation":
            root = Path(self.repo_path).resolve()
            path = (root / cand.path).resolve()
            if root in path.parents or path == root:
                content = _read_doc_content(
                    path,
                    start_line=cand.line_start,
                    end_line=cand.line_end,
                    start_page=cand.metadata.get("start_page"),
                    end_page=cand.metadata.get("end_page"),
                )
                if content and not content.startswith("Error reading "):

                    excerpt = content[:5000]  # documentation gets a larger excerpt
                    verified = True
                    notes.append("documentation file verified and read")
                else:
                    notes.append("documentation file empty or could not be read")
            else:
                notes.append("documentation path outside workspace")
        elif cand.kind in {"function_definition", "type_definition", "macro_definition", "constant_definition", "config_entry", "linker_symbol", "assembly_label", "source_span", "lsp_definition", "lsp_reference"}:
            lines = _safe_read_lines(self.repo_path, cand.path)
            if lines and cand.line_start and 1 <= cand.line_start <= len(lines):
                start = max(1, cand.line_start - 2)
                end = min(len(lines), (cand.line_end or cand.line_start) + 8)
                excerpt = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
                line_end = cand.line_end or min(len(lines), cand.line_start + 3)
                verified = True
                notes.append("path and line verified by source reader")
                if cand.symbol and cand.symbol not in excerpt:
                    notes.append("symbol not found in local excerpt; evidence remains location-based")
            else:
                notes.append("path/line could not be verified")
        elif cand.kind in {"call_edge", "lsp_call_graph"}:
            verified = bool(cand.metadata.get("src") and cand.metadata.get("dst") or cand.metadata.get("root_symbol"))
            notes.append("call graph verified by structured tool metadata" if verified else "call graph metadata incomplete")
        elif cand.kind == "git_history":
            verified = bool(cand.content or cand.metadata.get("commit"))
            notes.append("git history evidence from git tool")
        elif cand.kind == "formal_search":
            verified = bool(cand.tool == "formal_search" and cand.metadata.get("score_kind") == "formal" and cand.metadata.get("target_scope_id") and cand.metadata.get("candidate_scope_id") and cand.metadata.get("candidate_commit"))
            notes.append("formal search verified by dual ScopeManifest metadata" if verified else "formal search metadata incomplete")
        elif cand.kind == "scope_manifest":
            verified = bool(cand.metadata.get("scope_id") and cand.metadata.get("snapshot_id") and cand.metadata.get("status") == "verified")
            notes.append("verified ScopeManifest metadata" if verified else "ScopeManifest metadata incomplete")
        elif cand.tool == "source_reader" and cand.path and cand.line_start:
            lines = _safe_read_lines(self.repo_path, cand.path)
            if lines and 1 <= cand.line_start <= len(lines):
                start = max(1, cand.line_start - 2); end = min(len(lines), (cand.line_end or cand.line_start) + 8)
                excerpt = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1)); line_end = cand.line_end or min(len(lines), cand.line_start + 3); verified = True
                notes.append("custom source evidence path and line verified by source reader")
                if cand.symbol and cand.symbol not in excerpt: notes.append("symbol not found in local excerpt; evidence remains location-based")
            else:
                notes.append("custom source evidence path/line could not be verified")
        else:
            verified = False
            notes.append(f"unrecognized evidence kind '{cand.kind}' — add explicit verifier logic or use a known kind")

        strength = cand.strength if verified else "weak"
        payload = {
            "tool": cand.tool,
            "kind": cand.kind,
            "path": cand.path.replace("\\", "/"),
            "line_start": cand.line_start,
            "symbol": cand.symbol,
            "query": cand.query,
            "label": cand.label,
            "meta": cand.metadata,
        }
        return EvidenceRecord(
            evidence_id=stable_id("ev", payload),
            verified=verified,
            strength=strength,
            tool=cand.tool,
            kind=cand.kind,
            path=cand.path.replace("\\", "/"),
            line_start=cand.line_start,
            line_end=line_end,
            symbol=cand.symbol,
            label=cand.label,
            query=cand.query,
            excerpt=_clean_text(excerpt)[:4000],
            metadata=cand.metadata,
            verifier_notes=notes,
        )


def _rank_strength(v: str) -> int:
    return {"weak": 1, "medium": 2, "strong": 3}.get(v, 0)


def _compact_record(record: EvidenceRecord) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=record.evidence_id,
        verified=record.verified,
        strength=record.strength,
        tool=record.tool,
        kind=record.kind,
        path=record.path,
        line_start=record.line_start,
        line_end=record.line_end,
        symbol=record.symbol,
        label=record.label,
        query=record.query,
        excerpt="",
        metadata={
            key: value
            for key, value in record.metadata.items()
            if key in {
                "root_symbol", "src", "dst", "matches", "searched_paths",
                "semantic_fn_id", "signature", "type_kind", "phase", "node_id",
                "navigation_only", "tool", "result_count", "commit", "plan_id", "snapshot_commit",
                "executed_queries", "executed_checks", "extensions", "scanned_files", "coverage_complete", "required_checks",
                "score_kind", "target_scope_id", "candidate_scope_id", "candidate_commit", "scope_id", "snapshot_id", "status",
            }
        },
        verifier_notes=record.verifier_notes,
    )


@contextmanager
def _file_lock(path: str):
    lock_path = Path(path).with_suffix(Path(path).suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        handle.close()


def read_text_head(repo_path: str, rel_path: str, limit: int = 20000) -> str:
    path = Path(repo_path) / rel_path
    if not _is_text_file(path):
        return ""
    try:
        return _clean_text(path.read_text(encoding="utf-8", errors="ignore"))[:limit]
    except OSError:
        return ""


def search_repo(repo_path: str, pattern: str, *, max_hits: int = 20, include_exts: set[str] | None = None) -> list[dict[str, Any]]:
    flags = re.IGNORECASE
    rx = re.compile(pattern, flags)
    root = Path(repo_path)
    hits: list[dict[str, Any]] = []
    exts = include_exts or SOURCE_EXTS
    for dirpath, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "dist", "node_modules", "__pycache__", ".pytest_cache"}]
        for name in files:
            path = Path(dirpath) / name
            if path.suffix not in exts and path.name not in TEXT_NAMES:
                continue
            if not _is_text_file(path):
                continue
            rel = path.relative_to(root).as_posix()
            try:
                lines = _clean_text(path.read_text(encoding="utf-8", errors="ignore")).splitlines()
            except OSError:
                continue
            for idx, line in enumerate(lines, 1):
                if rx.search(line):
                    hits.append({"path": rel, "line": idx, "text": line.strip()[:300]})
                    if len(hits) >= max_hits:
                        return hits
    return hits


def _is_text_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix not in SOURCE_EXTS and path.name not in TEXT_NAMES:
        return False
    try:
        data = path.read_bytes()[:4096]
    except OSError:
        return False
    if b"\x00" in data:
        return False
    if not data:
        return True
    control = sum(1 for b in data if b < 32 and b not in (9, 10, 13))
    return control / max(1, len(data)) < 0.02


def _clean_text(text: str) -> str:
    return "".join(_visible_char(ch) for ch in text)


def _visible_char(ch: str) -> str:
    code = ord(ch)
    if ch in "\n\r\t" or code >= 32:
        return ch
    return f"\\x{code:02x}"


def _read_doc_content(
    path: Path,
    start_line: int | None = None,
    end_line: int | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
) -> str:
    if not path.is_file():
        return ""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            total_pages = len(reader.pages)
            sp = max(1, start_page or 1)
            ep = min(total_pages, end_page or (sp + 9))
            text = f"[PDF Pages {sp}-{ep} of {total_pages}]\n"
            for i in range(sp - 1, ep):
                text += reader.pages[i].extract_text() + "\n"
            return text
        except Exception:
            return ""
    elif suffix == ".docx":
        try:
            import docx
            doc = docx.Document(path)
            all_text = [para.text for para in doc.paragraphs]
            start = max(0, (start_line or 1) - 1)
            end = end_line if end_line else len(all_text)
            return "\n".join(all_text[start:end])
        except Exception:
            return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if start_line or end_line:
            lines = text.splitlines()
            start = max(0, (start_line or 1) - 1)
            end = end_line if end_line else len(lines)
            return "\n".join(lines[start:end])
        return text
    except OSError:
        return ""


def classify_source_kind(path: str, line_text: str, symbol: str = "") -> str:
    suffix = Path(path).suffix.lower()
    text = line_text.strip()
    if suffix in {".ld", ".lds"} or "ENTRY" in text:
        return "linker_symbol"
    if suffix in {".s", ".S"}:
        return "assembly_label" if text.endswith(":") or re.match(r"^[A-Za-z_.$][\w.$]*:", text) else "source_span"
    if text.startswith("#define"):
        return "macro_definition"
    if re.match(r"^(struct|enum|typedef)\b", text) or (symbol and f"struct {symbol}" in text):
        return "type_definition"
    if "=" in text and Path(path).name.lower() in {"makefile", "cargo.toml", "rust-toolchain.toml"}:
        return "config_entry"
    return "source_span"
