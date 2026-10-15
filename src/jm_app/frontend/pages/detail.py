"""Comic detail-page actions: favorites, comments, and local collection."""

from __future__ import annotations

import copy
from typing import Dict, List, TYPE_CHECKING

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ...backend.runtime_paths import resource_dir

if TYPE_CHECKING:
    from ..ui import MainWindow


DETAIL_ICON_DIR = resource_dir() / "detail_icons"


class DetailPageMixin:
    """Methods for the album detail page and its dependent library actions."""

    def restore_current_detail_from_cache(self):
        album_id = str(getattr(self, "current_album_id", "") or "")
        if not album_id:
            return False
        if album_id not in self.albums and album_id not in self.detail_cache:
            return False
        # Search is a separate page, so the existing detail widgets remain
        # intact. Returning through the breadcrumb must only reveal them.
        return True

    def toggle_current_album_favorite(self):
        album = self.current_album()
        if not album:
            self.show_toast("请先选择漫画")
            return
        if not self._library_has_session():
            self.show_toast("请先登录账号或在设置中填写有效 Cookie", 2400)
            return
        if self.detail_favorite_target_id:
            return
        self.detail_favorite_target_id = album.album_id
        self.detail_favorite_previous_state = self.detail_favorite_state(album.album_id)
        self.detail_favorite_toggle_confirmed = False
        self.detail_favorite_folders_loaded = False
        self.detail_favorite_folder_cache = []
        # Keep the click responsive.  The request runs in LibraryWorker and
        # failure restores this state below.
        self.set_detail_favorite_state(album.album_id, not self.detail_favorite_previous_state)
        self.update_detail_favorite_button(enabled=False)
        self.start_library_action("detail_toggle_favorite", {"album_id": album.album_id})
        if not self.detail_favorite_previous_state:
            self.start_library_action("detail_favorite_folders", requires_session=True)

    def detail_favorite_state(self, album_id: str = "") -> bool:
        target_id = str(album_id or self.current_album_id or "")
        if not target_id:
            return False
        if target_id in self.detail_favorite_states:
            return self.detail_favorite_states[target_id]
        album = self.albums.get(target_id)
        return bool(album and album.is_favorite)

    def update_detail_favorite_button(self, enabled: bool = True) -> None:
        button = getattr(self, "detail_favorite_button", None)
        if button is None:
            return
        is_favorite = self.detail_favorite_state()
        icon_name = "icon_like_on.png" if is_favorite else "icon_like_off.png"
        button.setIcon(QIcon(str(DETAIL_ICON_DIR / icon_name)))
        button.setToolTip("取消收藏" if is_favorite else "收藏到云端")
        button.setEnabled(enabled)

    def set_detail_favorite_state(self, album_id: str, is_favorite: bool) -> None:
        album_id = str(album_id or "")
        if not album_id:
            return
        value = bool(is_favorite)
        self.detail_favorite_states[album_id] = value
        for source in (self.albums, self.detail_cache):
            album = source.get(album_id)
            if album is not None:
                album.is_favorite = value
        self.update_detail_favorite_button()
        self.schedule_local_cache_save()

    def open_detail_favorite_dialog(self, folders: List[Dict], selected_name: str = "") -> None:
        existing = self.detail_favorite_dialog
        if existing is not None and existing.isVisible():
            category_box = existing.category_box
            previous_name = selected_name or category_box.currentText()
            category_box.blockSignals(True)
            category_box.clear()
            category_box.addItem("所有收藏", "0")
            seen = {"0"}
            for folder in folders:
                folder_id = str(folder.get("id") or "").strip()
                name = str(folder.get("name") or "").strip()
                if folder_id and name and folder_id not in seen:
                    category_box.addItem(name, folder_id)
                    seen.add(folder_id)
            selected_index = category_box.findText(previous_name)
            category_box.setCurrentIndex(selected_index if selected_index >= 0 else 0)
            category_box.blockSignals(False)
            existing.new_folder_edit.clear()
            existing.add_folder_button.setEnabled(True)
            existing.save_button.setEnabled(True)
            existing.status_label.setText("请选择分类后保存")
            existing.raise_()
            existing.activateWindow()
            return

        dialog = QDialog(self)
        dialog.setObjectName("detailFavoriteDialog")
        dialog.setWindowTitle("收藏分类")
        dialog.setModal(True)
        dialog.setMinimumWidth(408)
        dialog.setStyleSheet(
            "QDialog#detailFavoriteDialog {background:#ffffff;}"
            "QLabel#favoriteDialogTitle {color:#1f2937;font-size:18px;font-weight:900;}"
            "QLabel#favoriteDialogHint {color:#64748b;font-size:13px;}"
            "QComboBox, QLineEdit {min-height:38px;border:1px solid #dbe3ed;border-radius:6px;"
            "padding:0 10px;background:#ffffff;color:#334155;font-size:14px;}"
            "QComboBox:focus, QLineEdit:focus {border-color:#f97316;}"
            "QPushButton {min-height:38px;border:1px solid #dbe3ed;border-radius:6px;"
            "padding:0 14px;background:#ffffff;color:#475569;font-weight:800;}"
            "QPushButton:hover {background:#fff7ed;color:#c2410c;border-color:#fb923c;}"
            "QPushButton#favoriteDialogSave {background:#f97316;border-color:#f97316;color:#ffffff;}"
            "QPushButton#favoriteDialogSave:hover {background:#ea580c;}"
        )
        root = QVBoxLayout(dialog)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)
        title = QLabel("收藏分类", dialog)
        title.setObjectName("favoriteDialogTitle")
        hint = QLabel("选择要保存这本漫画的分类，也可以新建一个分类。", dialog)
        hint.setObjectName("favoriteDialogHint")
        category_box = QComboBox(dialog)
        category_box.addItem("所有收藏", "0")
        seen = {"0"}
        for folder in folders:
            folder_id = str(folder.get("id") or "").strip()
            name = str(folder.get("name") or "").strip()
            if folder_id and name and folder_id not in seen:
                category_box.addItem(name, folder_id)
                seen.add(folder_id)
        selected_index = category_box.findText(selected_name) if selected_name else 0
        category_box.setCurrentIndex(selected_index if selected_index >= 0 else 0)

        new_folder_row = QHBoxLayout()
        new_folder_edit = QLineEdit(dialog)
        new_folder_edit.setPlaceholderText("新建分类名称")
        add_folder_button = QPushButton("添加", dialog)
        new_folder_row.addWidget(new_folder_edit, 1)
        new_folder_row.addWidget(add_folder_button)
        status = QLabel("", dialog)
        status.setObjectName("favoriteDialogHint")
        footer = QHBoxLayout()
        footer.addStretch()
        cancel_button = QPushButton("取消", dialog)
        save_button = QPushButton("保存", dialog)
        save_button.setObjectName("favoriteDialogSave")
        footer.addWidget(cancel_button)
        footer.addWidget(save_button)
        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(category_box)
        root.addLayout(new_folder_row)
        root.addWidget(status)
        root.addLayout(footer)

        dialog.category_box = category_box
        dialog.new_folder_edit = new_folder_edit
        dialog.add_folder_button = add_folder_button
        dialog.save_button = save_button
        dialog.status_label = status
        add_folder_button.clicked.connect(self.add_detail_favorite_folder)
        new_folder_edit.returnPressed.connect(self.add_detail_favorite_folder)
        cancel_button.clicked.connect(dialog.reject)
        save_button.clicked.connect(self.save_detail_favorite_folder)
        dialog.finished.connect(self.close_detail_favorite_dialog)
        self.detail_favorite_dialog = dialog
        dialog.open()

    def close_detail_favorite_dialog(self, _result: int = 0) -> None:
        self.detail_favorite_dialog = None
        self.detail_favorite_target_id = ""
        self.detail_favorite_toggle_confirmed = False
        self.detail_favorite_folders_loaded = False
        self.detail_favorite_folder_cache = []
        self.detail_favorite_pending_folder_name = ""
        self.update_detail_favorite_button(enabled=True)

    def add_detail_favorite_folder(self) -> None:
        dialog = self.detail_favorite_dialog
        if dialog is None:
            return
        name = dialog.new_folder_edit.text().strip()
        if not name:
            dialog.status_label.setText("请输入新分类名称")
            dialog.new_folder_edit.setFocus()
            return
        self.detail_favorite_pending_folder_name = name
        dialog.status_label.setText("正在添加分类...")
        dialog.add_folder_button.setEnabled(False)
        self.start_library_action("detail_add_favorite_folder", {"name": name})

    def save_detail_favorite_folder(self) -> None:
        dialog = self.detail_favorite_dialog
        album_id = self.detail_favorite_target_id or self.current_album_id
        if dialog is None or not album_id:
            return
        folder_id = str(dialog.category_box.currentData() or "0")
        dialog.status_label.setText("正在保存分类...")
        dialog.save_button.setEnabled(False)
        dialog.add_folder_button.setEnabled(False)
        self.start_library_action(
            "detail_move_favorite",
            {"album_id": album_id, "folder_id": folder_id, "folder_name": dialog.category_box.currentText()},
        )

    def open_current_album_comments(self):
        album = self.current_album()
        if not album:
            self.show_toast("请先选择漫画")
            return
        self.set_library_comment_context(album)
        self.open_library(
            tab=2,
            refresh=False,
            preserve_path=True,
            breadcrumb_title="评论",
            preserve_comment_context=True,
        )
        self.library_comment_album_edit.setText(album.album_id)
        self.library_comment_reply_edit.clear()
        self.library_comment_page = 1
        self.refresh_library_comments()

    def add_current_album_to_local_favorites(self):
        album = self.current_album()
        if not album:
            self.show_toast("\u8bf7\u5148\u9009\u62e9\u6f2b\u753b")
            return

        default_collection_name = "\u9ed8\u8ba4\u6536\u85cf"
        collection_id = next(
            (
                stored_id
                for stored_id, name, _count in self.local_collection_store.list_collections()
                if name == default_collection_name
            ),
            None,
        )
        if collection_id is None:
            try:
                collection_id = self.local_collection_store.add_collection(default_collection_name)
            except Exception as exc:
                self.show_toast(str(exc))
                return

        self.local_collection_store.add_album(collection_id, copy.deepcopy(album))
        self.refresh_local_collection_combo(collection_id)
        self.show_toast("\u5df2\u52a0\u5165\u672c\u5730\u6536\u85cf")
