from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict

from PySide6.QtCore import QObject, Signal

from ...backend.models import NetworkConfig
from ...models import BookInfo, PageQuery
from ...repositories import MemoryCatalogRepository
from ...tasks import CatalogPageTask, TaskManager


@dataclass
class PageState:
    next_page: int = 1
    loading: bool = False
    has_more: bool = True
    generation: int = 0


class HomeController(QObject):
    page_loaded = Signal(object, int, object, object)
    page_failed = Signal(object, str)
    sections_prefetched = Signal(object, object)
    sections_prefetch_failed = Signal(object, str)
    loading_changed = Signal(bool)

    def __init__(self, config_factory: Callable[[], NetworkConfig], parent=None):
        super().__init__(parent)
        self.config_factory = config_factory
        self.catalog = MemoryCatalogRepository()
        self.tasks = TaskManager(self)
        self.states: Dict[str, PageState] = {}

    def refresh(self, query: PageQuery) -> None:
        state = self.states.setdefault(query.key, PageState())
        state.generation += 1
        state.next_page = 1
        state.has_more = True
        # A new page/query supersedes every pending catalogue request.  The
        # generation check still protects against a late signal, but actively
        # cancelling prevents stale category requests from occupying workers.
        self.tasks.cancel_prefix("catalog:")
        self._load(query, state, append=False)

    def load_next(self, query: PageQuery) -> None:
        state = self.states.setdefault(query.key, PageState())
        if state.loading or not state.has_more:
            return
        self._load(query, state, append=True)

    def seed_loaded_pages(self, query: PageQuery, page_count: int) -> None:
        """Record pages rendered from an in-memory home-section cache.

        Promote sections are prefetched before a user opens their tab, so the
        controller has no per-section state for that first rendered page.
        Without this seed, the first append request starts at page 1 again.
        Never move an existing state backwards: it may already know that a
        later page was loaded or that the feed has ended.
        """
        state = self.states.setdefault(query.key, PageState())
        loaded_pages = max(1, int(page_count))
        if state.next_page <= 1:
            state.next_page = loaded_pages + 1

    def prefetch_sections(self, query: PageQuery) -> None:
        """Fetch non-active home sections without replacing the visible feed."""
        state = self.states.setdefault(query.key, PageState())
        if state.loading:
            return
        state.loading = True
        page = 1
        generation = state.generation
        task = CatalogPageTask(query, page, self.config_factory(), generation, self)
        task.succeeded.connect(self._on_sections_prefetched)
        task.failed.connect(
            lambda message, query=query, generation=generation: self._on_prefetch_failed(
                query, generation, message
            )
        )
        task.cancelled.connect(
            lambda query=query, generation=generation: self._finish_prefetch(query, generation)
        )
        self.tasks.start(f"catalog-prefetch:{query.key}:{generation}", task, replace=True)

    def restore(self, query: PageQuery) -> bool:
        """Restore this session's already-loaded pages without a network call."""
        state = self.states.get(query.key)
        if not state or state.loading or state.next_page <= 1:
            return False
        books: list[BookInfo] = []
        for page in range(1, state.next_page):
            books.extend(self.catalog.page_books(query.key, page))
        if not books:
            return False
        self.page_loaded.emit(query, state.next_page - 1, books, {"append": False, "cached": True, "sections": {}})
        return True

    def cancel(self, query: PageQuery) -> None:
        self.tasks.cancel_prefix(f"catalog:{query.key}:")
        state = self.states.get(query.key)
        if state:
            state.loading = False

    def _load(self, query: PageQuery, state: PageState, append: bool) -> None:
        state.loading = True
        self.loading_changed.emit(True)
        page = state.next_page
        generation = state.generation
        task = CatalogPageTask(query, page, self.config_factory(), generation, self)
        task.succeeded.connect(lambda result, append=append: self._on_loaded(result, append))
        task.failed.connect(lambda message, query=query, generation=generation: self._on_failed(query, generation, message))
        task.cancelled.connect(lambda query=query, generation=generation: self._finish_cancelled(query, generation))
        self.tasks.start(f"catalog:{query.key}:{generation}", task, replace=True)

    def _on_loaded(self, result: dict, append: bool) -> None:
        query: PageQuery = result["query"]
        state = self.states.get(query.key)
        if not state or result["generation"] != state.generation:
            return
        books: list[BookInfo] = self.catalog.upsert_books(result["books"])
        self.catalog.set_page_books(query.key, result["page"], [book.book_id for book in books])
        state.loading = False
        state.has_more = bool(books)
        if books:
            state.next_page = result["page"] + 1
        self.loading_changed.emit(False)
        self.page_loaded.emit(query, result["page"], books, {"append": append, "sections": result["sections"]})

    def _on_sections_prefetched(self, result: dict) -> None:
        query: PageQuery = result["query"]
        state = self.states.get(query.key)
        if not state or result["generation"] != state.generation:
            return
        books: list[BookInfo] = self.catalog.upsert_books(result["books"])
        self.catalog.set_page_books(query.key, result["page"], [book.book_id for book in books])
        state.loading = False
        state.has_more = bool(books)
        if books:
            state.next_page = result["page"] + 1
        self.sections_prefetched.emit(query, result["sections"])

    def _finish_prefetch(self, query: PageQuery, generation: int) -> None:
        state = self.states.get(query.key)
        if state and state.generation == generation:
            state.loading = False

    def _on_prefetch_failed(self, query: PageQuery, generation: int, message: str) -> None:
        state = self.states.get(query.key)
        if not state or state.generation != generation:
            return
        state.loading = False
        self.sections_prefetch_failed.emit(query, message)

    def _on_failed(self, query: PageQuery, generation: int, message: str) -> None:
        state = self.states.get(query.key)
        if state and state.generation == generation:
            state.loading = False
            self.loading_changed.emit(False)
            self.page_failed.emit(query, message)

    def _finish_cancelled(self, query: PageQuery, generation: int) -> None:
        state = self.states.get(query.key)
        if state and state.generation == generation:
            state.loading = False
            self.loading_changed.emit(False)
