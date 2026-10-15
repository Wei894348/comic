"""JMComic-qt style local favourites page and actions."""

from __future__ import annotations

import copy
import math
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...backend.models import AlbumMeta
from ...backend.runtime_paths import resource_dir
from .library_feed import _tinted_library_icon

if TYPE_CHECKING:
    from ..ui import MainWindow


LOCAL_FAVORITE_PAGE_SIZE = 20
ALL_LOCAL_FAVORITES = -1


class LocalFavoritePageMixin:
    """Own the local favourites UI without adding more page code to ui.py."""

    def setup_local_favorite_page(self: "MainWindow", panel: QFrame) -> None:
        local_tab = next(
            (
                self.library_tabs.widget(index)
                for index in range(self.library_tabs.count())
                if self.library_tabs.widget(index).objectName() == "localTab"
            ),
            None,
        )
        if local_tab is None or not isinstance(local_tab.layout(), QVBoxLayout):
            raise RuntimeError("library.ui is missing localTab")

        self.local_favorite_page = self.load_ui_widget(
            "local_favorite.ui", QFrame, local_tab
        )

        def require(widget_type, name):
            widget = self.local_favorite_page.findChild(widget_type, name)
            if widget is None:
                raise RuntimeError(f"local_favorite.ui is missing {name}")
            return widget

        self.local_favorite_folder_combo = require(
            QComboBox, "localFavoriteFolderCombo"
        )
        self.local_favorite_search_label = require(
            QLabel, "localFavoriteSearchLabel"
        )
        self.local_favorite_search_edit = require(
            QLineEdit, "localFavoriteSearchEdit"
        )
        self.local_favorite_folder_menu_button = require(
            QToolButton, "localFavoriteFolderMenuButton"
        )
        self.local_favorite_sort_combo = require(
            QComboBox, "localFavoriteSortCombo"
        )
        self.local_favorite_direction_combo = require(
            QComboBox, "localFavoriteDirectionCombo"
        )
        self.local_favorite_import_button = require(
            QPushButton, "localFavoriteImportButton"
        )
        self.local_favorite_batch_button = require(
            QPushButton, "localFavoriteBatchDownloadButton"
        )
        self.local_favorite_update_button = require(
            QPushButton, "localFavoriteUpdateButton"
        )
        self.local_favorite_task_label = require(
            QLabel, "localFavoriteTaskLabel"
        )
        self.local_favorite_count_label = require(
            QLabel, "localFavoriteCountLabel"
        )
        self.local_favorite_page_label = require(
            QLabel, "localFavoritePageLabel"
        )
        self.local_favorite_page_spin = require(
            QSpinBox, "localFavoritePageSpin"
        )
        self.local_favorite_jump_button = require(
            QPushButton, "localFavoriteJumpButton"
        )

        feed = self.library_feed_for_layout(self.local_collection_layout)
        host_layout = self.local_favorite_page.findChild(
            QVBoxLayout, "localFavoriteFeedHostLayout"
        )
        if feed is None or host_layout is None:
            raise RuntimeError("Local favorite feed was not initialized")
        feed.setParent(self.local_favorite_page)
        host_layout.addWidget(feed, 1)
        feed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        old_controls = (
            "localNote",
            "localCollectionCombo",
            "localCollectionNameEdit",
            "localCollectionAddButton",
            "localCollectionRemoveButton",
            "localCollectionAlbumEdit",
            "localCollectionAddAlbumButton",
            "localImportDirectoryButton",
            "localImportBatchDirectoryButton",
            "localImportArchivesButton",
            "localScanButton",
            "localOpenHistoryButton",
        )
        for name in old_controls:
            widget = panel.findChild(QWidget, name)
            if widget is not None and hasattr(widget, "hide"):
                widget.hide()
        local_tab.layout().insertWidget(0, self.local_favorite_page, 1)

        self.local_favorite_current_page = 1
        self.local_favorite_total = 0
        self.local_favorite_visible_albums: List[AlbumMeta] = []
        self.local_favorite_busy = False
        self.local_favorite_search_timer = QTimer(self)
        self.local_favorite_search_timer.setSingleShot(True)
        self.local_favorite_search_timer.setInterval(180)
        self.local_favorite_search_timer.timeout.connect(
            self.reset_local_favorite_page
        )

        self.local_favorite_folder_combo.currentIndexChanged.connect(
            self.reset_local_favorite_page
        )
        self.local_favorite_search_edit.textChanged.connect(
            lambda _text: self.local_favorite_search_timer.start()
        )
        self.local_favorite_sort_combo.currentIndexChanged.connect(
            self.reset_local_favorite_page
        )
        self.local_favorite_direction_combo.currentIndexChanged.connect(
            self.reset_local_favorite_page
        )
        self.local_favorite_folder_menu_button.clicked.connect(
            self.open_local_favorite_folder_menu
        )
        self.local_favorite_import_button.clicked.connect(
            self.import_account_favorites_to_local
        )
        self.local_favorite_batch_button.clicked.connect(
            self.batch_download_local_favorites
        )
        self.local_favorite_update_button.clicked.connect(
            self.update_local_favorite_chapters
        )
        self.local_favorite_jump_button.clicked.connect(
            self.jump_local_favorite_page
        )

        self.local_favorite_search_label.setText("搜索范围")
        icon_dir = resource_dir() / "nav_icons"
        search_icon = _tinted_library_icon(
            QIcon(str(icon_dir / "line_search.svg")), "#7d8ca1", 18
        )
        self.local_favorite_search_edit.addAction(
            search_icon, QLineEdit.ActionPosition.LeadingPosition
        )
        self.local_favorite_folder_menu_button.setIcon(
            _tinted_library_icon(
                QIcon(str(icon_dir / "line_folder.svg")), "#3478f6", 19
            )
        )
        self.local_favorite_folder_menu_button.setIconSize(QSize(19, 19))
        self.local_favorite_folder_menu_button.setText("")
        self.local_favorite_folder_icon = _tinted_library_icon(
            QIcon(str(icon_dir / "line_favorite.svg")), "#3478f6", 18
        )
        self.local_favorite_sort_icon = _tinted_library_icon(
            QIcon(str(icon_dir / "line_calendar.svg")), "#3478f6", 17
        )
        for index in range(self.local_favorite_sort_combo.count()):
            self.local_favorite_sort_combo.setItemIcon(
                index, self.local_favorite_sort_icon
            )
        direction_icons = (
            _tinted_library_icon(
                QIcon(str(icon_dir / "line_sort_desc.svg")), "#3478f6", 17
            ),
            _tinted_library_icon(
                QIcon(str(icon_dir / "line_sort_asc.svg")), "#3478f6", 17
            ),
        )
        for index, icon in enumerate(direction_icons):
            if index < self.local_favorite_direction_combo.count():
                self.local_favorite_direction_combo.setItemIcon(index, icon)
        command_icons = (
            (self.local_favorite_import_button, "line_cloud_import.svg"),
            (self.local_favorite_batch_button, "line_download.svg"),
            (self.local_favorite_update_button, "line_refresh.svg"),
            (self.local_favorite_jump_button, "line_arrow_right.svg"),
        )
        for button, filename in command_icons:
            button.setIcon(
                _tinted_library_icon(QIcon(str(icon_dir / filename)), "#3478f6", 18)
            )
            button.setIconSize(QSize(18, 18))
        for control in (
            self.local_favorite_folder_combo,
            self.local_favorite_search_edit,
            self.local_favorite_sort_combo,
            self.local_favorite_direction_combo,
        ):
            control.setMinimumHeight(42)
        self.local_favorite_folder_menu_button.setFixedSize(42, 42)
        self.local_favorite_folder_combo.setIconSize(QSize(18, 18))
        self.local_favorite_sort_combo.setIconSize(QSize(17, 17))
        self.apply_local_favorite_style()
        self.sync_local_favorite_theme()

    def apply_local_favorite_style(self: "MainWindow") -> None:
        icon_dir = resource_dir() / "nav_icons"
        spin_up_icon = (icon_dir / "spin_up.svg").as_posix()
        spin_down_icon = (icon_dir / "spin_down.svg").as_posix()
        style = (
            """
            QFrame#localFavoritePage { background:#f8fafc; border:0; }
            QLabel#localFavoriteSearchLabel { color:#334155; font-size:13px; font-weight:800; }
            QFrame#localFavoriteAccentLine { background:#e3eaf4; border:0; }
            QComboBox#localFavoriteFolderCombo, QLineEdit#localFavoriteSearchEdit,
            QComboBox#localFavoriteSortCombo, QComboBox#localFavoriteDirectionCombo,
            QSpinBox#localFavoritePageSpin {
                color:#243143; background:#ffffff; border:1px solid #d8e1ed;
                border-radius:8px; padding:0 10px; font-size:13px;
            }
            QSpinBox#localFavoritePageSpin { padding:0 28px 0 11px; }
            QSpinBox#localFavoritePageSpin::up-button {
                subcontrol-origin:border; subcontrol-position:top right;
                width:24px; height:20px; margin:1px 1px 0 0;
                background:#f8fafc; border:0; border-left:1px solid #d8e1ed;
                border-bottom:1px solid #e7ecf3; border-top-right-radius:7px;
            }
            QSpinBox#localFavoritePageSpin::down-button {
                subcontrol-origin:border; subcontrol-position:bottom right;
                width:24px; height:20px; margin:0 1px 1px 0;
                background:#f8fafc; border:0; border-left:1px solid #d8e1ed;
                border-bottom-right-radius:7px;
            }
            QSpinBox#localFavoritePageSpin::up-button:hover,
            QSpinBox#localFavoritePageSpin::down-button:hover { background:#eaf2ff; }
            QSpinBox#localFavoritePageSpin::up-arrow {
                image:url("__SPIN_UP_ICON__"); width:8px; height:8px;
            }
            QSpinBox#localFavoritePageSpin::down-arrow {
                image:url("__SPIN_DOWN_ICON__"); width:8px; height:8px;
            }
            QComboBox:hover, QLineEdit:hover, QSpinBox:hover { border-color:#9bbdff; }
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus { border:1px solid #3478f6; }
            QToolButton#localFavoriteFolderMenuButton {
                background:#ffffff; border:1px solid #d8e1ed; border-radius:8px;
            }
            QToolButton#localFavoriteFolderMenuButton:hover { background:#edf4ff; border-color:#3478f6; }
            QFrame#localFavoriteBottomBar { background:#ffffff; border:1px solid #e3e9f1; border-radius:8px; }
            QPushButton#localFavoriteImportButton, QPushButton#localFavoriteBatchDownloadButton,
            QPushButton#localFavoriteUpdateButton, QPushButton#localFavoriteJumpButton {
                color:#2468df; background:#f8fbff; border:1px solid #a9c6ff;
                border-radius:7px; padding:5px 10px; font-weight:800;
            }
            QPushButton:hover { color:#ffffff; background:#3478f6; border-color:#3478f6; }
            QPushButton:disabled { color:#9aa3af; border-color:#d8dde5; background:#f4f5f7; }
            QLabel#localFavoriteTaskLabel { color:#2563eb; font-size:11px; }
            QLabel#localFavoriteCountLabel, QLabel#localFavoritePageLabel { color:#4b5563; font-weight:700; }
            QListWidget#libraryLocalFavoriteFeed {
                background:transparent; border:0; outline:0; padding:0;
            }
            QScrollBar:vertical { border:0; background:#f3f3f3; width:8px; margin:0; }
            QScrollBar::handle:vertical { background:#878787; min-height:10px; }
            QScrollBar::handle:vertical:hover { background:#646464; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; border:0; }
            """
        )
        self.local_favorite_page.setStyleSheet(
            style.replace("__SPIN_UP_ICON__", spin_up_icon).replace(
                "__SPIN_DOWN_ICON__", spin_down_icon
            )
        )
        for combo in (
            self.local_favorite_folder_combo,
            self.local_favorite_sort_combo,
            self.local_favorite_direction_combo,
        ):
            combo.view().setSpacing(2)

    def sync_local_favorite_theme(self: "MainWindow") -> None:
        dark = bool(getattr(self, "theme_dark", False))
        if dark:
            popup_style = (
                "QAbstractItemView{background:#24272d;border:1px solid #414752;"
                "border-radius:6px;padding:5px;outline:0;color:#e5e7eb;}"
                "QAbstractItemView::item{min-height:31px;padding:3px 8px;border-radius:4px;}"
                "QAbstractItemView::item:hover{background:#303640;}"
                "QAbstractItemView::item:selected{background:#1d365c;color:#8db8ff;}"
            )
        else:
            popup_style = (
                "QAbstractItemView{background:#ffffff;border:1px solid #d8e1ed;"
                "border-radius:6px;padding:5px;outline:0;color:#263244;}"
                "QAbstractItemView::item{min-height:31px;padding:3px 8px;border-radius:4px;}"
                "QAbstractItemView::item:hover{background:#f2f6fc;}"
                "QAbstractItemView::item:selected{background:#eaf2ff;color:#245fc4;}"
            )
        for combo in (
            getattr(self, "local_favorite_folder_combo", None),
            getattr(self, "local_favorite_sort_combo", None),
            getattr(self, "local_favorite_direction_combo", None),
        ):
            if combo is not None:
                combo.view().setStyleSheet(popup_style)

    def sync_local_favorite_folders(
        self: "MainWindow", selected_id: Optional[int] = None
    ) -> None:
        if not hasattr(self, "local_favorite_folder_combo"):
            return
        combo = self.local_favorite_folder_combo
        current = selected_id if selected_id is not None else combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        total = self.local_collection_store.count_albums()
        combo.addItem(f"所有 ({total})", ALL_LOCAL_FAVORITES)
        for collection_id, name, count in self.local_collection_store.list_collections():
                combo.addItem(f"{name} ({count})", collection_id)
        icon = getattr(self, "local_favorite_folder_icon", QIcon())
        if not icon.isNull():
            for item_index in range(combo.count()):
                combo.setItemIcon(item_index, icon)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self.reset_local_favorite_page()

    def reset_local_favorite_page(self: "MainWindow", *_args) -> None:
        self.local_favorite_current_page = 1
        self.refresh_local_favorite_page()

    def selected_local_favorite_collection(self: "MainWindow") -> Optional[int]:
        value = self.local_favorite_folder_combo.currentData()
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return None if value == ALL_LOCAL_FAVORITES else value

    def local_favorite_query(self: "MainWindow") -> str:
        return self.local_favorite_search_edit.text().strip()

    def local_favorite_sort(self: "MainWindow") -> tuple[str, bool]:
        sort_key = str(self.local_favorite_sort_combo.currentData() or "updated_at")
        descending = bool(self.local_favorite_direction_combo.currentData())
        return sort_key, descending

    def refresh_local_favorite_page(self: "MainWindow") -> None:
        if not hasattr(self, "local_favorite_page"):
            return
        collection_id = self.selected_local_favorite_collection()
        query = self.local_favorite_query()
        sort_key, descending = self.local_favorite_sort()
        total = self.local_collection_store.count_albums(collection_id, query)
        page_count = max(1, math.ceil(total / LOCAL_FAVORITE_PAGE_SIZE))
        self.local_favorite_current_page = min(
            max(1, int(self.local_favorite_current_page)), page_count
        )
        albums = self.local_collection_store.search_albums(
            collection_id=collection_id,
            query=query,
            sort_key=sort_key,
            descending=descending,
            limit=LOCAL_FAVORITE_PAGE_SIZE,
            offset=(self.local_favorite_current_page - 1) * LOCAL_FAVORITE_PAGE_SIZE,
        )
        self.local_favorite_total = total
        self.local_favorite_visible_albums = list(albums)
        self.render_local_favorite_cards(albums)
        self.local_favorite_count_label.setText(f"收藏数：{total}")
        self.local_favorite_page_label.setText(
            f"{self.local_favorite_current_page} / {page_count} 页"
        )
        self.local_favorite_page_spin.blockSignals(True)
        self.local_favorite_page_spin.setMaximum(page_count)
        self.local_favorite_page_spin.setValue(self.local_favorite_current_page)
        self.local_favorite_page_spin.blockSignals(False)
        enabled = bool(albums) and not self.local_favorite_busy
        self.local_favorite_batch_button.setEnabled(enabled)
        self.local_favorite_update_button.setEnabled(enabled)
        self.set_library_route_count("localTab", total, "本")

    def jump_local_favorite_page(self: "MainWindow") -> None:
        page = int(self.local_favorite_page_spin.value())
        if page == self.local_favorite_current_page:
            return
        self.local_favorite_current_page = page
        self.refresh_local_favorite_page()

    def render_local_favorite_cards(
        self: "MainWindow", albums: List[AlbumMeta]
    ) -> None:
        feed = self.library_feed_for_layout(self.local_collection_layout)
        if feed is None:
            return
        collection_id = self.selected_local_favorite_collection()
        self.render_library_feed(
            feed,
            albums,
            "暂无本地收藏",
            remove_callback=lambda album_id, collection_id=collection_id:
            self.remove_local_favorite_album(collection_id, album_id),
        )
        history_by_id = {
            str(record.get("album_id") or record.get("id") or ""): record
            for record in reversed(self.download_history)
            if str(record.get("album_id") or record.get("id") or "")
        }
        for row in range(feed.count()):
            card = feed.itemWidget(feed.item(row))
            if card is None or row >= len(albums):
                continue
            album = albums[row]
            card.setProperty("album_id", album.album_id)
            record = history_by_id.get(str(album.album_id), {})
            page = self._profile_int(record.get("last_page"), 0)
            total = self._profile_int(record.get("last_total"), 0)
            if page <= 0:
                continue
            cover = card.findChild(QLabel, "albumCover")
            if cover is None:
                continue
            progress = QLabel(cover)
            progress.setObjectName("localFavoriteReadingProgress")
            suffix = f"/{total}页" if total > 0 else ""
            progress.setText(f"上次看到第{page}页{suffix}")
            progress.setAlignment(Qt.AlignCenter)
            progress.setStyleSheet(
                "color:#ffffff;background:rgba(24,31,42,185);"
                "font-size:11px;font-weight:700;border:0;padding:3px;"
            )
            progress.setGeometry(0, cover.height() - 28, cover.width(), 28)
            progress.show()
            progress.raise_()

    def all_filtered_local_favorite_albums(self: "MainWindow") -> List[AlbumMeta]:
        sort_key, descending = self.local_favorite_sort()
        return self.local_collection_store.search_albums(
            collection_id=self.selected_local_favorite_collection(),
            query=self.local_favorite_query(),
            sort_key=sort_key,
            descending=descending,
        )

    def open_local_favorite_folder_menu(self: "MainWindow") -> None:
        menu = self.build_local_favorite_folder_menu()
        menu.exec(
            self.local_favorite_folder_menu_button.mapToGlobal(
                self.local_favorite_folder_menu_button.rect().bottomLeft()
            )
        )

    def build_local_favorite_folder_menu(self: "MainWindow"):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("新建收藏夹", self.create_local_favorite_folder)
        delete_action = menu.addAction(
            "删除当前收藏夹", self.delete_local_favorite_folder
        )
        delete_action.setEnabled(
            self.selected_local_favorite_collection() is not None
        )
        return menu

    def create_local_favorite_folder(self: "MainWindow") -> None:
        name, accepted = QInputDialog.getText(self, "新建收藏夹", "收藏夹名称")
        if not accepted or not name.strip():
            return
        try:
            collection_id = self.local_collection_store.ensure_collection(name)
        except Exception as exc:
            self.show_toast(str(exc))
            return
        self.sync_local_favorite_folders(collection_id)
        self.show_toast("本地收藏夹已创建")

    def delete_local_favorite_folder(self: "MainWindow") -> None:
        collection_id = self.selected_local_favorite_collection()
        if collection_id is None:
            self.show_toast("“所有”不是收藏夹")
            return
        answer = QMessageBox.question(
            self,
            "删除收藏夹",
            f"确定删除“{self.local_favorite_folder_combo.currentText()}”及其收藏吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.local_collection_store.remove_collection(collection_id)
        self.sync_local_favorite_folders()
        self.show_toast("本地收藏夹已删除")

    def remove_local_favorite_album(
        self: "MainWindow", collection_id: Optional[int], album_id: str
    ) -> None:
        if collection_id is None:
            self.local_collection_store.remove_album_all(album_id)
        else:
            self.local_collection_store.remove_album(collection_id, album_id)
        self.sync_local_favorite_folders(collection_id)

    def import_account_favorites_to_local(self: "MainWindow") -> None:
        if self.local_favorite_busy:
            return
        self.set_local_favorite_busy(True, "正在导入账号收藏...")
        if not self.start_library_action("local_favorite_import"):
            self.set_local_favorite_busy(False, "")

    def apply_local_favorite_import_result(
        self: "MainWindow", result
    ) -> None:
        albums = [
            self.album_from_dict(item)
            for item in (result.get("albums") or [])
            if isinstance(item, dict)
        ]
        collection_id = self.selected_local_favorite_collection()
        if collection_id is None:
            collection_id = self.local_collection_store.ensure_collection("账号收藏")
        imported = self.local_collection_store.add_albums(collection_id, albums)
        self.set_local_favorite_busy(False, f"已导入 {imported} 本")
        self.sync_local_favorite_folders(collection_id)
        self.show_toast(f"账号收藏导入完成：{imported} 本")

    def batch_download_local_favorites(self: "MainWindow") -> None:
        albums = self.all_filtered_local_favorite_albums()
        if not albums:
            self.show_toast("当前筛选没有可下载的漫画")
            return
        added = 0
        queued_ids = {
            album.album_id
            for album in list(self.queue) + list(self.download_pending_queue)
        }
        queued_ids.update(self.download_workers)
        for album in albums:
            if (
                album.album_id in queued_ids
                or self.album_has_completed_local_resource(album)
            ):
                continue
            self.albums[album.album_id] = copy.deepcopy(album)
            self.detail_cache.setdefault(album.album_id, copy.deepcopy(album))
            if self.add_album_to_queue(
                album.album_id, switch_page=False, refresh=False
            ):
                added += 1
                queued_ids.add(album.album_id)
        if not added:
            self.show_toast("筛选结果已在下载队列或本地库中")
            return
        self.refresh_queue_table()
        self.switch_page(self.queue_page_index())
        self.show_toast(f"已将 {added} 本漫画加入下载队列")

    def update_local_favorite_chapters(self: "MainWindow") -> None:
        if self.local_favorite_busy:
            return
        albums = self.all_filtered_local_favorite_albums()
        if not albums:
            self.show_toast("当前筛选没有漫画")
            return
        self.set_local_favorite_busy(True, f"正在更新 0 / {len(albums)}...")
        started = self.start_library_action(
            "local_favorite_update",
            {"album_ids": [album.album_id for album in albums]},
            requires_session=False,
        )
        if not started:
            self.set_local_favorite_busy(False, "")

    def apply_local_favorite_update_result(
        self: "MainWindow", result
    ) -> None:
        changed = 0
        albums = [
            self.album_from_dict(item)
            for item in (result.get("albums") or [])
            if isinstance(item, dict)
        ]
        for album in albums:
            changed += int(self.local_collection_store.update_album(album))
            self.albums[album.album_id] = copy.deepcopy(album)
            self.detail_cache[album.album_id] = copy.deepcopy(album)
        failed = len(result.get("failed") or [])
        text = f"更新完成：{changed} 本有新章节"
        if failed:
            text += f"，{failed} 本失败"
        self.set_local_favorite_busy(False, text)
        self.refresh_local_favorite_page()
        self.show_toast(text)

    def set_local_favorite_busy(
        self: "MainWindow", busy: bool, text: str
    ) -> None:
        self.local_favorite_busy = bool(busy)
        self.local_favorite_task_label.setText(text)
        for button in (
            self.local_favorite_import_button,
            self.local_favorite_batch_button,
            self.local_favorite_update_button,
        ):
            button.setEnabled(not busy)

    def apply_local_favorite_failure(
        self: "MainWindow", message: str
    ) -> None:
        self.set_local_favorite_busy(False, f"操作失败：{message}")
