from __future__ import annotations

from typing import Callable, Dict, Set

from PySide6.QtCore import QObject, Signal

from ...backend.models import AlbumMeta, DownloadConfig
from ...backend.workers import DownloadWorker
from ...models import DownloadState, DownloadTaskInfo
from ...repositories import StateRepository


class DownloadController(QObject):
    """Owns download Worker lifecycle and durable state transitions."""

    worker_created = Signal(object, object)
    log = Signal(str)
    task_finished = Signal(str)
    task_failed = Signal(str, str)

    def __init__(self, config_factory: Callable[[], DownloadConfig], state: StateRepository, parent=None):
        super().__init__(parent)
        self.config_factory = config_factory
        self.state = state
        self.workers: Dict[str, DownloadWorker] = {}
        self.task_ids: Dict[str, str] = {}
        self.paused_ids: Set[str] = set()

    def start(self, album: AlbumMeta) -> DownloadWorker | None:
        if not album.album_id or album.album_id in self.workers:
            return None
        worker = DownloadWorker([album], self.config_factory(), self)
        task_id = f"download:{album.album_id}"
        self.workers[album.album_id] = worker
        self.task_ids[album.album_id] = task_id
        self.state.save_download_task(
            DownloadTaskInfo(task_id, album.album_id, album.title, DownloadState.QUEUED)
        )
        worker.log.connect(self.log)
        worker.state_changed.connect(self._on_state_changed)
        worker.finished_ok.connect(lambda album_id=album.album_id: self._on_finished(album_id))
        worker.failed.connect(lambda message, album_id=album.album_id: self._on_failed(album_id, message))
        worker.finished.connect(lambda album_id=album.album_id, worker=worker: self._forget(album_id, worker))
        self.worker_created.emit(album, worker)
        worker.start()
        return worker

    def cancel(self, book_id: str) -> None:
        worker = self.workers.get(book_id)
        self.paused_ids.discard(book_id)
        self.state.update_download_state(self.task_ids.get(book_id, f"download:{book_id}"), DownloadState.CANCELLED)
        if worker and worker.isRunning():
            worker.cancel()

    def pause(self, book_id: str) -> None:
        """Stop the worker while retaining a resumable task state."""
        worker = self.workers.get(book_id)
        self.paused_ids.add(book_id)
        self.state.update_download_state(
            self.task_ids.get(book_id, f"download:{book_id}"), DownloadState.PAUSED
        )
        if worker and worker.isRunning():
            worker.cancel()

    def cancel_all(self) -> None:
        for book_id in list(self.workers):
            self.cancel(book_id)

    def update_progress(self, book_id: str, state: DownloadState, total_images: int = 0, done_images: int = 0) -> None:
        self.state.update_download_state(
            self.task_ids.get(book_id, f"download:{book_id}"),
            state,
            total_images=max(0, int(total_images)),
            done_images=max(0, int(done_images)),
        )

    def _on_state_changed(self, album: AlbumMeta, state_name: str, detail: dict) -> None:
        try:
            state = DownloadState(state_name)
        except ValueError:
            return
        values = {}
        if detail.get("current_chapter_id"):
            values["current_chapter_id"] = str(detail["current_chapter_id"])
        self.state.update_download_state(self.task_ids.get(album.album_id, f"download:{album.album_id}"), state, **values)

    def _on_finished(self, book_id: str) -> None:
        self.paused_ids.discard(book_id)
        self.state.update_download_state(self.task_ids.get(book_id, f"download:{book_id}"), DownloadState.COMPLETED)
        self.task_finished.emit(book_id)

    def _on_failed(self, book_id: str, message: str) -> None:
        worker = self.workers.get(book_id)
        if worker is not None and worker.cancel_event.is_set():
            state = DownloadState.PAUSED if book_id in self.paused_ids else DownloadState.CANCELLED
            self.state.update_download_state(
                self.task_ids.get(book_id, f"download:{book_id}"), state
            )
            return
        self.state.update_download_state(
            self.task_ids.get(book_id, f"download:{book_id}"), DownloadState.FAILED, error_message=message
        )
        self.task_failed.emit(book_id, message)

    def _forget(self, book_id: str, worker: DownloadWorker) -> None:
        if self.workers.get(book_id) is worker:
            self.workers.pop(book_id, None)
        self.paused_ids.discard(book_id)
