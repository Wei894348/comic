from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..backend.runtime_paths import book_cache_dir


class PageCacheRepository:
    """Disk-only reader page cache: cache/book/{book}/{chapter-index}/{page}."""

    def chapter_dir(self, book_id: str, chapter_index: int) -> Path:
        return book_cache_dir(book_id, max(1, int(chapter_index)))

    def page_path(self, book_id: str, chapter_index: int, page_index: int, suffix: str) -> Path:
        extension = suffix if suffix.startswith(".") else f".{suffix}"
        return self.chapter_dir(book_id, chapter_index) / f"{max(1, int(page_index)):05d}{extension.lower()}"

    def find_page(self, book_id: str, chapter_index: int, page_index: int) -> Optional[Path]:
        stem = f"{max(1, int(page_index)):05d}"
        for path in self.chapter_dir(book_id, chapter_index).glob(f"{stem}.*"):
            if path.is_file() and path.stat().st_size > 0:
                return path
        return None
