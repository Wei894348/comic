from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from ...backend.models import NetworkConfig
from ...models import BookInfo
from ...repositories import MemoryCatalogRepository
from ...tasks import DetailTask, TaskManager


class DetailController(QObject):
    loaded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, catalog: MemoryCatalogRepository, config_factory: Callable[[], NetworkConfig], parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.config_factory = config_factory
        self.tasks = TaskManager(self)
        self._generation = 0

    def load(self, book_id: str) -> None:
        self._generation += 1
        generation = self._generation
        task = DetailTask(book_id, self.config_factory(), generation, self)
        task.succeeded.connect(self._on_loaded)
        task.failed.connect(lambda message, book_id=book_id, generation=generation: self._on_failed(book_id, generation, message))
        self.tasks.start("detail:active", task, replace=True)

    def cancel(self) -> None:
        self.tasks.cancel("detail:active")

    def _on_loaded(self, result: dict) -> None:
        if result["generation"] != self._generation:
            return
        book: BookInfo = self.catalog.upsert_books([result["book"]])[0]
        self.loaded.emit(book)

    def _on_failed(self, book_id: str, generation: int, message: str) -> None:
        if generation == self._generation:
            self.failed.emit(book_id, message)
