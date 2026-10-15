"""Local downloaded comics page, separate from the active download queue."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QLineEdit, QPushButton, QScrollArea

from ...backend.models import AlbumMeta

if TYPE_CHECKING:
    from ..ui import MainWindow


LOCAL_DOWNLOAD_LIGHT_STYLE = """
QFrame#localDownloadPanel { background:#f7f8fa; border:0; }
QFrame#localDownloadToolbar { background:#ffffff; border:1px solid #e1e7ef; border-radius:7px; }
QLabel#localDownloadTitle { color:#1f2937; font-size:16px; font-weight:800; }
QLabel#localDownloadCount { color:#718096; font-size:12px; font-weight:700; }
QLineEdit#localDownloadSearch, QComboBox#localDownloadFormat {
    min-height:38px; max-height:38px; color:#263244; background:#ffffff;
    border:1px solid #d8e1ed; border-radius:6px; padding:0 11px;
}
QLineEdit#localDownloadSearch:focus, QComboBox#localDownloadFormat:focus { border-color:#5793ee; }
QPushButton#localDownloadOpenFolder {
    min-height:38px; max-height:38px; padding:0 14px; color:#2563eb;
    background:#eef5ff; border:1px solid #c8dcfb; border-radius:6px; font-weight:700;
}
QPushButton#localDownloadOpenFolder:hover { background:#dfeeff; }
QListWidget#localDownloadFeed { background:transparent; border:0; outline:0; }
"""


LOCAL_DOWNLOAD_DARK_STYLE = """
QFrame#localDownloadPanel { background:#17191d; border:0; }
QFrame#localDownloadToolbar { background:#24272d; border:1px solid #3b414b; border-radius:7px; }
QLabel#localDownloadTitle { color:#edf0f4; font-size:16px; font-weight:800; }
QLabel#localDownloadCount { color:#aeb6c2; font-size:12px; font-weight:700; }
QLineEdit#localDownloadSearch, QComboBox#localDownloadFormat {
    min-height:38px; max-height:38px; color:#e5e7eb; background:#191c21;
    border:1px solid #414752; border-radius:6px; padding:0 11px;
}
QPushButton#localDownloadOpenFolder {
    min-height:38px; max-height:38px; padding:0 14px; color:#8db8ff;
    background:#202b3b; border:1px solid #416da8; border-radius:6px; font-weight:700;
}
QPushButton#localDownloadOpenFolder:hover { background:#283b55; }
QListWidget#localDownloadFeed { background:transparent; border:0; outline:0; }
"""


class LocalDownloadPageMixin:
    """Display completed local resources using the shared home-style grid."""

    def _build_local_download_panel(self: "MainWindow") -> QFrame:
        panel = self.load_ui_widget("local_download.ui", QFrame)

        def require(widget_type, object_name):
            widget = panel.findChild(widget_type, object_name)
            if widget is None:
                raise RuntimeError(f"local_download.ui is missing {object_name}")
            return widget

        self.local_download_panel = panel
        self.local_download_search = require(QLineEdit, "localDownloadSearch")
        self.local_download_format = require(QComboBox, "localDownloadFormat")
        self.local_download_count = require(QLabel, "localDownloadCount")
        self.local_download_open_folder = require(QPushButton, "localDownloadOpenFolder")
        placeholder = require(QScrollArea, "localDownloadScroll")
        self.local_download_feed = self._replace_scroll_with_library_feed(
            placeholder, "localDownloadFeed"
        )
        self.local_download_feed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.local_download_search_timer = QTimer(self)
        self.local_download_search_timer.setSingleShot(True)
        self.local_download_search_timer.setInterval(160)
        self.local_download_search_timer.timeout.connect(self.refresh_local_downloads)
        self.local_download_refresh_timer = QTimer(self)
        self.local_download_refresh_timer.setSingleShot(True)
        self.local_download_refresh_timer.setInterval(140)
        self.local_download_refresh_timer.timeout.connect(self.refresh_local_downloads)
        self.local_download_search.textChanged.connect(
            lambda _text: self.local_download_search_timer.start()
        )
        self.local_download_format.currentIndexChanged.connect(self.refresh_local_downloads)
        self.local_download_open_folder.clicked.connect(self.open_output_dir)
        self.sync_local_download_theme()
        self.local_download_dirty = True
        return panel

    def open_local_download_page(self: "MainWindow") -> None:
        self.switch_page(self.local_download_page_index())
        self.local_download_dirty = True
        self.local_download_refresh_timer.start(16)

    def refresh_local_downloads_if_visible(self: "MainWindow") -> None:
        panel = getattr(self, "local_download_panel", None)
        if panel is None or not panel.isVisible():
            self.local_download_dirty = True
            return
        self.local_download_dirty = True
        self.local_download_refresh_timer.start()

    def sync_local_download_theme(self: "MainWindow") -> None:
        panel = getattr(self, "local_download_panel", None)
        if panel is None:
            return
        panel.setStyleSheet(
            LOCAL_DOWNLOAD_DARK_STYLE
            if bool(getattr(self, "theme_dark", False))
            else LOCAL_DOWNLOAD_LIGHT_STYLE
        )

    def local_download_records(self: "MainWindow"):
        query = self.local_download_search.text().strip().casefold()
        selected_format = str(self.local_download_format.currentData() or "")
        records = []
        for history_index, record in reversed(
            list(enumerate(getattr(self, "download_history", [])))
        ):
            if not isinstance(record, dict) or not self.history_record_has_local_file(record):
                continue
            record_format = str(record.get("format") or "").lower()
            if selected_format and record_format != selected_format:
                continue
            searchable = " ".join(
                str(record.get(key) or "")
                for key in ("title", "album_id", "file", "path")
            ).casefold()
            if query and query not in searchable:
                continue
            records.append((history_index, record))
        return records

    def refresh_local_downloads(self: "MainWindow", *_args) -> None:
        feed = getattr(self, "local_download_feed", None)
        if feed is None:
            return
        entries = []
        for history_index, record in self.local_download_records():
            album = self.album_from_history_record(record)
            if album is None:
                album = AlbumMeta(
                    album_id=str(record.get("album_id") or f"local-{history_index}"),
                    title=str(record.get("title") or record.get("file") or "本地漫画"),
                    url="",
                    cover_url=str(record.get("cover_url") or ""),
                    source="本地下载",
                )
            album.tags = [str(record.get("format") or "图片").upper(), "已下载"]
            view_record = copy.deepcopy(record)
            view_record["_local_download"] = True
            entries.append((album, history_index, view_record))
        self.local_download_count.setText(f"{len(entries)} 本")
        self.local_download_dirty = False
        self._render_account_feed_entries(
            feed, entries, "暂无本地下载，去分类页发现漫画"
        )
