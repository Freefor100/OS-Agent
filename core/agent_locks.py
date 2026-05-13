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


def _get_process_lock(name: str) -> threading.Lock:
    with _PROCESS_LOCKS_GUARD:
        if name not in _PROCESS_LOCKS:
            _PROCESS_LOCKS[name] = threading.Lock()
        return _PROCESS_LOCKS[name]


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


def lock_path(state_dir: str, name: str) -> str:
    return os.path.join(state_dir, "locks", f"{name}.lock")
