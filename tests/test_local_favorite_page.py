from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from xml.etree import ElementTree

from script.downloader import ensure_qt_plugin_path

ensure_qt_plugin_path()
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSpinBox, QStyle, QStyleOptionSpinBox

from jm_app.backend.library_store import LocalCollectionStore
from jm_app.backend.models import AlbumMeta, ChapterMeta
from jm_app.backend.runtime_paths import ui_dir


class LocalFavoritePageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_page_has_jmcomic_local_favorite_controls(self):
        root = ElementTree.parse(ui_dir() / "local_favorite.ui").getroot()
        object_names = {element.get("name") for element in root.iter()}
        self.assertTrue(
            {
                "localFavoriteFolderCombo",
                "localFavoriteSearchEdit",
                "localFavoriteFeedHost",
                "localFavoriteSortCombo",
                "localFavoriteDirectionCombo",
                "localFavoriteImportButton",
                "localFavoriteBatchDownloadButton",
                "localFavoriteUpdateButton",
                "localFavoriteCountLabel",
                "localFavoritePageSpin",
                "localFavoriteJumpButton",
            }.issubset(object_names)
        )

    def test_page_spin_buttons_are_stacked_at_the_right(self):
        spin = QSpinBox()
        spin.setObjectName("localFavoritePageSpin")
        spin.resize(74, 42)
        spin.setStyleSheet(
            """
            QSpinBox#localFavoritePageSpin { padding:0 28px 0 11px; }
            QSpinBox#localFavoritePageSpin::up-button {
                subcontrol-origin:border; subcontrol-position:top right;
                width:24px; height:20px; margin:1px 1px 0 0;
            }
            QSpinBox#localFavoritePageSpin::down-button {
                subcontrol-origin:border; subcontrol-position:bottom right;
                width:24px; height:20px; margin:0 1px 1px 0;
            }
            """
        )
        spin.ensurePolished()
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        up_rect = spin.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            QStyle.SubControl.SC_SpinBoxUp,
            spin,
        )
        down_rect = spin.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            QStyle.SubControl.SC_SpinBoxDown,
            spin,
        )
        edit_rect = spin.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            QStyle.SubControl.SC_SpinBoxEditField,
            spin,
        )

        self.assertEqual(up_rect.left(), down_rect.left())
        self.assertEqual(up_rect.width(), down_rect.width())
        self.assertLess(up_rect.top(), down_rect.top())
        self.assertGreaterEqual(up_rect.left(), edit_rect.right())
        self.assertGreater(up_rect.height(), 0)
        self.assertGreater(down_rect.height(), 0)

    def test_store_searches_all_folders_and_updates_chapter_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalCollectionStore(Path(directory) / "local.db")
            first_folder = store.ensure_collection("默认")
            self.assertEqual(store.ensure_collection("默认"), first_folder)
            second_folder = store.ensure_collection("稍后阅读")

            first = AlbumMeta(
                album_id="101",
                title="Alpha title",
                url="jm://album/101",
                author="Writer A",
                tags=["school"],
            )
            second = AlbumMeta(
                album_id="202",
                title="Beta title",
                url="jm://album/202",
                author="Writer B",
                tags=["office"],
            )
            store.add_album(first_folder, first)
            store.add_album(second_folder, first)
            store.add_album(second_folder, second)

            self.assertEqual(store.count_albums(), 2)
            self.assertEqual(store.count_albums(first_folder), 1)
            self.assertEqual(
                [album.album_id for album in store.search_albums(query="office")],
                ["202"],
            )
            self.assertEqual(
                [album.album_id for album in store.search_albums(query="Writer A")],
                ["101"],
            )

            updated = AlbumMeta(
                album_id="101",
                title="Alpha updated",
                url="jm://album/101",
                author="Writer A",
                tags=["school", "updated"],
                chapters=[
                    ChapterMeta("1", "one", "jm://chapter/1"),
                    ChapterMeta("2", "two", "jm://chapter/2"),
                ],
            )
            self.assertTrue(store.update_album(updated))
            refreshed = store.search_albums(query="updated")
            self.assertEqual(len(refreshed), 1)
            self.assertEqual(refreshed[0].title, "Alpha updated")
            self.assertEqual(refreshed[0].local_chapter_count, 2)


if __name__ == "__main__":
    unittest.main()
