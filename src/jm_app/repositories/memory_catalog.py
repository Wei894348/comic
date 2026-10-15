from __future__ import annotations

import threading
from copy import deepcopy
from typing import Dict, Iterable, List, Optional

from ..models import BookInfo, ImageInfo


class MemoryCatalogRepository:
    """Session-scoped online metadata.  It intentionally has no disk backing."""

    def __init__(self):
        self._lock = threading.RLock()
        self._books: Dict[str, BookInfo] = {}
        self._images: Dict[str, List[ImageInfo]] = {}
        self._pages: Dict[str, List[str]] = {}

    def upsert_books(self, books: Iterable[BookInfo]) -> List[BookInfo]:
        result = []
        with self._lock:
            for book in books:
                existing = self._books.get(book.book_id)
                if existing is None:
                    self._books[book.book_id] = deepcopy(book)
                else:
                    existing.merge_meta(book_to_meta(book))
                result.append(deepcopy(self._books[book.book_id]))
        return result

    def get_book(self, book_id: str) -> Optional[BookInfo]:
        with self._lock:
            value = self._books.get(str(book_id))
            return deepcopy(value) if value else None

    def set_page_books(self, query_key: str, page: int, book_ids: Iterable[str]) -> None:
        with self._lock:
            self._pages[f"{query_key}:{page}"] = list(book_ids)

    def page_books(self, query_key: str, page: int) -> List[BookInfo]:
        with self._lock:
            return [
                deepcopy(self._books[book_id])
                for book_id in self._pages.get(f"{query_key}:{page}", [])
                if book_id in self._books
            ]

    def set_images(self, chapter_id: str, images: Iterable[ImageInfo]) -> None:
        with self._lock:
            self._images[str(chapter_id)] = [deepcopy(image) for image in images]

    def images(self, chapter_id: str) -> List[ImageInfo]:
        with self._lock:
            return deepcopy(self._images.get(str(chapter_id), []))

    def clear(self) -> None:
        with self._lock:
            self._books.clear()
            self._images.clear()
            self._pages.clear()


def book_to_meta(book: BookInfo):
    """Avoid coupling the repository to UI objects while reusing merge rules."""
    from ..backend.models import AlbumMeta, ChapterMeta

    return AlbumMeta(
        album_id=book.book_id,
        title=book.title,
        url=book.url,
        cover_url=book.cover_url,
        author=book.author,
        tags=list(book.tags),
        description=book.description,
        likes=book.likes,
        views=book.views,
        page_count=book.page_count,
        source=book.source,
        chapters=[ChapterMeta(item.chapter_id, item.title, item.url, item.index) for item in book.chapters],
    )
