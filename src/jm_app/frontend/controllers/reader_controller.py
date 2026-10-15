from __future__ import annotations

from PySide6.QtCore import QObject

from ...backend.models import AlbumMeta
from ...repositories import StateRepository
from ..hd_reader import HdMangaReaderWindow


class ReaderController(QObject):
    """Persists progress without coupling the reader view to SQLite."""

    def __init__(self, state: StateRepository, parent=None):
        super().__init__(parent)
        self.state = state

    def bind(self, reader: HdMangaReaderWindow, album: AlbumMeta) -> None:
        reader.page_position_changed.connect(
            lambda page, total, source, reader=reader, album=album: self._save_position(
                reader, album, page, total, source
            )
        )

    def restore_page(self, album: AlbumMeta, chapter_id: str) -> int:
        return self.state.progress(album.album_id, chapter_id)[0]

    def _save_position(self, reader: HdMangaReaderWindow, album: AlbumMeta, page: int, total: int, source_key: str) -> None:
        chapter = getattr(reader, "chapter", None)
        if chapter is None or page <= 0:
            return
        self.state.record_reading_history(
            album.album_id,
            chapter.chapter_id,
            album.title,
            album.cover_url,
            chapter.title,
            chapter.index,
            max(
                len(album.chapters),
                int(getattr(album, "_chapter_total_hint", 0) or 0),
            ),
        )
        self.state.save_progress(album.album_id, chapter.chapter_id, page, total, source_key)
