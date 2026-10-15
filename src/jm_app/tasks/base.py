from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from PySide6.QtCore import QObject, QThread, Signal


class ManagedTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, generation: int = 0, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.requestInterruption()

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set() or self.isInterruptionRequested()

    def execute(self):  # pragma: no cover - implemented by concrete tasks
        raise NotImplementedError

    def run(self) -> None:
        try:
            result = self.execute()
            if self.is_cancelled():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        except Exception as exc:
            if self.is_cancelled():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))


class TaskManager(QObject):
    """Owns UI-bound tasks and prevents late callbacks after page replacement."""

    task_started = Signal(str)
    task_finished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: Dict[str, ManagedTask] = {}
        self._retired_tasks = set()

    def start(self, key: str, task: ManagedTask, replace: bool = True) -> ManagedTask:
        if replace:
            self.cancel(key)
        self._tasks[key] = task
        task.finished.connect(lambda key=key, task=task: self._forget(key, task))
        self.task_started.emit(key)
        task.start()
        return task

    def cancel(self, key: str) -> None:
        task = self._tasks.pop(key, None)
        if task is None:
            return
        if task.isRunning():
            self._retired_tasks.add(task)
            task.cancel()

    def cancel_prefix(self, prefix: str) -> None:
        for key in [value for value in self._tasks if value.startswith(prefix)]:
            self.cancel(key)

    def cancel_all(self) -> None:
        for key in list(self._tasks):
            self.cancel(key)

    def wait_for_all(self, timeout_ms: int = 2000) -> bool:
        """Wait for cancelled QThreads without losing their Python wrappers."""
        deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
        tasks = list(self._tasks.values()) + list(self._retired_tasks)
        for task in tasks:
            if not task.isRunning():
                continue
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0 or not task.wait(remaining_ms):
                return False
        return True

    def _forget(self, key: str, task: ManagedTask) -> None:
        if self._tasks.get(key) is task:
            self._tasks.pop(key, None)
        self._retired_tasks.discard(task)
        self.task_finished.emit(key)
