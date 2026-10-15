"""Local reading history backed by :class:`StateRepository`."""

from __future__ import annotations

import copy
import time
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMenu, QMessageBox

from ...backend.models import AlbumMeta, ChapterMeta

if TYPE_CHECKING:
    from ..ui import MainWindow


class LocalHistoryPageMixin:
    """Present one latest reading position per comic, like JMComic-qt."""

    @staticmethod
    def relative_reading_time(timestamp: float) -> str:
        elapsed = max(0, int(time.time() - float(timestamp or 0)))
        if elapsed < 60:
            return "刚刚"
        if elapsed < 3600:
            return f"{elapsed // 60}分钟前"
        if elapsed < 86400:
            return f"{elapsed // 3600}小时前"
        if elapsed < 86400 * 30:
            return f"{elapsed // 86400}天前"
        if elapsed < 86400 * 365:
            return f"{elapsed // (86400 * 30)}个月前"
        return f"{elapsed // (86400 * 365)}年前"

    def refresh_local_reading_history(self: "MainWindow") -> bool:
        feed = getattr(self, "history_feed_view", None)
        if feed is None:
            return False
        records = self.state_repository.reading_history()
        self.local_reading_records = records

        entries = []
        for record in records:
            chapter_index = max(0, int(record.get("chapter_index") or 0))
            chapter_title = str(record.get("chapter_title") or "").strip()
            page = max(1, int(record.get("page_index") or 1))
            total = max(0, int(record.get("page_total") or 0))
            progress_text = f"第 {page} / {total} 页" if total else f"第 {page} 页"
            chapter_text = chapter_title or (
                f"第 {chapter_index} 话"
                if chapter_index
                else f"章节 {record.get('chapter_id') or '-'}"
            )
            album = AlbumMeta(
                album_id=str(record.get("book_id") or ""),
                title=str(record.get("title") or "未命名漫画"),
                url=f"jm://album/{record.get('book_id') or ''}",
                cover_url=str(record.get("cover_url") or ""),
                source="本地阅读记录",
                tags=[chapter_text, progress_text],
                chapters=[
                    ChapterMeta(
                        chapter_id=str(record.get("chapter_id") or ""),
                        title=chapter_title or chapter_text,
                        url=f"jm://chapter/{record.get('chapter_id') or ''}",
                        index=chapter_index or 1,
                    )
                ],
            )
            view_record = dict(record)
            view_record.update(
                {
                    "_reading_history": True,
                    "album_id": str(record.get("book_id") or ""),
                    "last_page": page,
                    "last_total": total,
                    "relative_time": self.relative_reading_time(
                        float(record.get("last_opened_at") or 0)
                    ),
                }
            )
            entries.append((album, None, view_record))
        self._render_account_feed_entries(feed, entries, "还没有看过的漫画")
        return True

    def continue_local_reading(self: "MainWindow", record: dict) -> None:
        book_id = str(record.get("book_id") or "")
        chapter_id = str(record.get("chapter_id") or "")
        if not book_id or not chapter_id:
            self.show_toast("阅读记录不完整，无法继续阅读")
            return
        cached = self.detail_cache.get(book_id) or self.albums.get(book_id)
        album = copy.deepcopy(cached) if cached is not None else AlbumMeta(
            album_id=book_id,
            title=str(record.get("title") or f"JM{book_id}"),
            url=f"jm://album/{book_id}",
            cover_url=str(record.get("cover_url") or ""),
        )
        chapter = next(
            (item for item in album.chapters if str(item.chapter_id) == chapter_id),
            None,
        )
        if chapter is None:
            chapter = ChapterMeta(
                chapter_id=chapter_id,
                title=str(record.get("chapter_title") or "上次阅读章节"),
                url=f"jm://chapter/{chapter_id}",
                index=max(1, int(record.get("chapter_index") or 1)),
            )
            album.chapters = [chapter]
        album._chapter_total_hint = max(
            len(album.chapters), int(record.get("chapter_total") or 0)
        )
        self.albums[book_id] = copy.deepcopy(album)
        self.detail_cache.setdefault(book_id, copy.deepcopy(album))
        self.open_reader_for_album(album, chapter)

    def show_local_reading_context_menu(
        self: "MainWindow", record: dict, global_pos
    ) -> None:
        menu = QMenu(self)
        menu.addAction("继续阅读", lambda: self.continue_local_reading(record))
        menu.addAction(
            "查看详情",
            lambda: self.open_album_detail(str(record.get("book_id") or "")),
        )
        menu.addSeparator()
        menu.addAction("删除记录", lambda: self.delete_local_reading_record(record))
        menu.exec(global_pos)

    def delete_local_reading_record(self: "MainWindow", record: dict) -> None:
        book_id = str(record.get("book_id") or "")
        if not book_id:
            return
        self.state_repository.delete_reading_history(book_id)
        self.refresh_local_reading_history()

    def clear_local_reading_history(self: "MainWindow") -> None:
        answer = QMessageBox.question(
            self,
            "清空阅读记录",
            "确定清空全部本地阅读记录和阅读进度吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.state_repository.clear_reading_history()
        self.refresh_local_reading_history()

    def build_local_history_settings_menu(self: "MainWindow") -> QMenu:
        menu = QMenu(self)
        menu.addAction("刷新", self.refresh_local_reading_history)
        menu.addSeparator()
        menu.addAction("清空阅读记录", self.clear_local_reading_history)
        return menu
