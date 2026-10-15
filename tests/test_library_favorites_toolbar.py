from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLineEdit, QPushButton, QTabWidget, QWidget

from jm_app.backend.runtime_paths import ui_dir
from jm_app.frontend.pages.library_feed import LibraryFeedPageMixin


class _FavoritesToolbarHarness(LibraryFeedPageMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.theme_dark = False
        ui_file = QFile(str(ui_dir() / "library.ui"))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError("Unable to open library.ui")
        self.panel = QUiLoader().load(ui_file)
        ui_file.close()

        self.library_tabs = self.panel.findChild(QTabWidget, "libraryTabs")
        self.library_folder_combo = self.panel.findChild(QComboBox, "libraryFolderCombo")
        self.library_favorite_sort_combo = self.panel.findChild(
            QComboBox, "libraryFavoriteSortCombo"
        )
        self.local_collection_combo = self.panel.findChild(QComboBox, "localCollectionCombo")
        self.library_new_folder_edit = self.panel.findChild(QLineEdit, "libraryNewFolderEdit")
        self.local_collection_name_edit = self.panel.findChild(QLineEdit, "localCollectionNameEdit")
        self.local_collection_album_edit = self.panel.findChild(QLineEdit, "localCollectionAlbumEdit")
        self.library_comment_album_edit = self.panel.findChild(QLineEdit, "libraryCommentAlbumEdit")
        self.library_comment_input = self.panel.findChild(QLineEdit, "libraryCommentInput")
        self.library_comment_reply_edit = self.panel.findChild(QLineEdit, "libraryCommentReplyEdit")
        self.apply_library_visual_system(self.panel)


class LibraryFavoritesToolbarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.harness = _FavoritesToolbarHarness()
        self.panel = self.harness.panel

    def tearDown(self):
        self.panel.close()
        self.harness.close()
        self.app.processEvents()

    def test_toolbar_controls_do_not_overlap_at_narrow_content_width(self):
        self.panel.resize(700, 560)
        self.panel.show()
        self.app.processEvents()
        controls = [
            self.harness.library_folder_combo,
            self.harness.library_favorite_sort_combo,
            self.harness.library_new_folder_edit,
            self.panel.findChild(QPushButton, "libraryAddFolderButton"),
            self.panel.findChild(QPushButton, "libraryDeleteFolderButton"),
        ]
        toolbar_rect = self.harness.library_favorite_toolbar.contentsRect()
        for index, control in enumerate(controls):
            self.assertTrue(toolbar_rect.contains(control.geometry()))
            for other in controls[index + 1 :]:
                self.assertFalse(control.geometry().intersects(other.geometry()))

    def test_toolbar_has_icons_divider_and_safe_delete_state(self):
        self.assertFalse(self.harness.library_folder_combo.itemIcon(0).isNull())
        self.assertFalse(self.harness.library_favorite_sort_combo.itemIcon(0).isNull())
        self.assertIsNotNone(self.panel.findChild(QFrame, "favoriteToolbarDivider"))
        self.assertFalse(self.harness.library_delete_folder_button.isEnabled())

        self.harness.library_folder_combo.addItem("测试收藏夹", "folder-1")
        self.harness.library_folder_combo.setCurrentIndex(1)
        self.assertTrue(self.harness.library_delete_folder_button.isEnabled())

    def test_dark_theme_updates_combo_popup(self):
        self.harness.theme_dark = True
        self.harness.sync_library_favorite_toolbar_theme()
        self.assertIn("background:#24272d", self.harness.library_folder_combo.view().styleSheet())


if __name__ == "__main__":
    unittest.main()
