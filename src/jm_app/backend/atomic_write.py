"""Small atomic-write helpers for per-user JSON state."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_LOCK_STATE = threading.local()


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _thread_lock(key: str) -> threading.RLock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def exclusive_path_lock(path: Path, *, timeout: float = 15.0) -> Iterator[None]:
    """Serialize a read-modify-write sequence across threads and processes."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    key = _path_key(destination)
    lock_path = destination.with_name(f".{destination.name}.lock")
    with _thread_lock(key):
        held_paths = getattr(_LOCK_STATE, "held_paths", set())
        _LOCK_STATE.held_paths = held_paths
        if key in held_paths:
            yield
            return
        with open(lock_path, "a+b") as stream:
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            if os.name == "nt":
                import msvcrt

                deadline = time.monotonic() + max(0.0, timeout)
                while True:
                    stream.seek(0)
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"timed out locking {destination}") from exc
                        time.sleep(0.05)
                held_paths.add(key)
                try:
                    yield
                finally:
                    held_paths.remove(key)
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                held_paths.add(key)
                try:
                    yield
                finally:
                    held_paths.remove(key)
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Replace *path* from a unique temporary file in the same directory."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_path_lock(destination):
        descriptor = -1
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=str(destination.parent),
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding=encoding) as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any, *, indent: int | None = None) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=indent),
    )
