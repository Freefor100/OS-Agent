from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from core.agent_graph_state import utcnow_iso


_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_SEMAPHORES: dict[str, tuple[int, threading.BoundedSemaphore]] = {}
_PROCESS_SEMAPHORES_GUARD = threading.Lock()
_PROCESS_RW_LOCKS: dict[str, "_ReadWriteLock"] = {}
_PROCESS_RW_LOCKS_GUARD = threading.Lock()

LSP_TOOL_CONCURRENCY = 1
RAG_TOOL_CONCURRENCY = 1


def _get_process_lock(name: str) -> threading.Lock:
    with _PROCESS_LOCKS_GUARD:
        if name not in _PROCESS_LOCKS:
            _PROCESS_LOCKS[name] = threading.Lock()
        return _PROCESS_LOCKS[name]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None and str(raw).strip() else default
    except ValueError:
        value = default
    return max(1, value)


def _get_process_semaphore(name: str, capacity: int) -> threading.BoundedSemaphore:
    capacity = max(1, int(capacity))
    with _PROCESS_SEMAPHORES_GUARD:
        existing = _PROCESS_SEMAPHORES.get(name)
        if existing is None or existing[0] != capacity:
            sem = threading.BoundedSemaphore(capacity)
            _PROCESS_SEMAPHORES[name] = (capacity, sem)
            return sem
        return existing[1]


class _ReadWriteLock:
    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False

    @contextmanager
    def read(self) -> Iterator[None]:
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextmanager
    def write(self) -> Iterator[None]:
        with self._cond:
            while self._writer or self._readers:
                self._cond.wait()
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()


def _get_process_rw_lock(name: str) -> "_ReadWriteLock":
    with _PROCESS_RW_LOCKS_GUARD:
        if name not in _PROCESS_RW_LOCKS:
            _PROCESS_RW_LOCKS[name] = _ReadWriteLock()
        return _PROCESS_RW_LOCKS[name]


class FileLock:
    def __init__(self, path: str, *, ttl_seconds: int = 3600):
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._held = False

    def acquire(self, *, timeout: float = 300.0, poll: float = 0.2) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        deadline = time.time() + timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "pid": os.getpid(),
                            "created_at": utcnow_iso(),
                            "heartbeat_at": utcnow_iso(),
                        },
                        f,
                        ensure_ascii=False,
                    )
                self._held = True
                return
            except FileExistsError:
                self._break_stale_lock_if_needed()
                if time.time() >= deadline:
                    raise TimeoutError(f"timed out waiting for lock: {self.path}")
                time.sleep(poll)

    def _break_stale_lock_if_needed(self) -> None:
        try:
            age = time.time() - os.path.getmtime(self.path)
        except OSError:
            return
        if age > self.ttl_seconds:
            try:
                os.remove(self.path)
            except OSError:
                pass

    def release(self) -> None:
        if not self._held:
            return
        try:
            os.remove(self.path)
        except OSError:
            pass
        self._held = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


@contextmanager
def named_thread_lock(name: str) -> Iterator[None]:
    lock = _get_process_lock(name)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


@contextmanager
def named_thread_semaphore(name: str, capacity: int) -> Iterator[None]:
    sem = _get_process_semaphore(name, capacity)
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


@contextmanager
def lsp_tool_guard(tool_name: str = "") -> Iterator[None]:
    """
    Limit only the actual LSP tool call instead of holding the lock for an
    entire ReAct task. Ordinary LSP queries share a read lock; target changes
    take the write lock because they restart language servers.
    """
    capacity = LSP_TOOL_CONCURRENCY
    rw = _get_process_rw_lock("lsp_target_arch")
    is_target_write = (tool_name or "").strip() == "lsp_set_target_arch"
    with named_thread_semaphore("lsp_tool", capacity):
        if is_target_write:
            with rw.write():
                yield
        else:
            with rw.read():
                yield


@contextmanager
def rag_tool_guard() -> Iterator[None]:
    """Serialize RAG embedding/search calls that share one SentenceTransformer."""
    with named_thread_semaphore("rag_tool", RAG_TOOL_CONCURRENCY):
        yield


def lock_path(state_dir: str, name: str) -> str:
    return os.path.join(state_dir, "locks", f"{name}.lock")
