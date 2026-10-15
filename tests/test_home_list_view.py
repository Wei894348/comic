from __future__ import annotations

import unittest

from tests.qt_test_utils import close_test_window, prepare_qt_test_environment

prepare_qt_test_environment()

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget

from jm_app.backend.models import AlbumMeta
from jm_app.frontend.ui import MainWindow
from jm_app.models import BookInfo, PageQuery


class HomeListViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.auto_load_has_more = False
        self.window.result_stack.setCurrentWidget(self.window.result_scroll)
        self.window.results_revealed = True
        self.window.show()
        self.app.processEvents()
        self.window.clear_result_grid()
        self.window.result_albums = []
        self.window.result_album_indices.clear()
        self.window.result_total_count = 0

    def tearDown(self):
        close_test_window(self.window, self.app)

    @staticmethod
    def album(index: int) -> AlbumMeta:
        return AlbumMeta(
            album_id=str(810000 + index),
            title=f"album {index}",
            url="",
            cover_url="",
            tags=[],
        )

    def test_appends_list_items_without_rebuilding_existing_cards(self):
        self.assertIsInstance(self.window.result_scroll, QListWidget)

        for index in range(8):
            album = self.album(index)
            self.window.result_albums.append(album)
            self.window.upsert_album_at(index, album)
        self.window.result_total_count = 8
        self.window.result_render_limit = 8
        self.window.render_result_page(fast_switch=True)
        self.app.processEvents()

        first_card = self.window.card_by_id[self.album(0).album_id]
        self.assertEqual(self.window.result_scroll.count(), 8)
        bar = self.window.result_scroll.verticalScrollBar()
        bar.setValue(max(0, bar.maximum() // 2))
        scroll_value_before_append = bar.value()

        for index in range(8, 16):
            album = self.album(index)
            self.window.result_albums.append(album)
            self.window.upsert_album_at(index, album)
        self.window.result_total_count = 16
        self.window.queue_appended_result_cards(8, 16)
        for _ in range(40):
            self.app.processEvents()

        self.assertEqual(self.window.result_scroll.count(), 16)
        self.assertIs(self.window.card_by_id[self.album(0).album_id], first_card)
        self.assertIn(self.album(15).album_id, self.window.card_by_id)
        self.assertEqual(bar.value(), scroll_value_before_append)

    def test_switching_back_to_a_section_reuses_its_list_and_cards(self):
        latest_key = "latest:latest:v1"
        promote_key = "promote:c107:v1"
        self.window.home_result_views.clear()
        self.window.home_active_result_view_key = latest_key
        self.window.current_result_cache_key = latest_key

        for index in range(4):
            album = self.album(index)
            self.window.result_albums.append(album)
            self.window.upsert_album_at(index, album)
        self.window.result_total_count = 4
        self.window.result_render_limit = 4
        self.window.render_result_page(fast_switch=True)
        self.app.processEvents()

        latest_list = self.window.result_scroll
        latest_card = self.window.card_by_id[self.album(0).album_id]
        self.window._capture_home_result_view()

        self.assertFalse(self.window.prepare_home_result_view(promote_key))
        promote_list = self.window.result_scroll
        self.assertIsNot(promote_list, latest_list)
        self.window.current_result_cache_key = promote_key

        self.assertTrue(self.window.prepare_home_result_view(latest_key))
        self.assertIs(self.window.result_scroll, latest_list)
        self.assertIs(self.window.card_by_id[self.album(0).album_id], latest_card)
        self.assertEqual(self.window.result_scroll.count(), 4)

    def test_prewarmed_section_is_ready_before_its_first_switch(self):
        latest_key = "latest:latest:v1"
        promote_key = "promote:c107:v1"
        self.window.home_result_views.clear()
        self.window.home_active_result_view_key = latest_key
        self.window.current_result_cache_key = latest_key
        active_list = self.window.result_scroll

        prewarmed_album = self.album(20)
        self.window._prewarm_home_section_view(promote_key, [prewarmed_album])

        state = self.window.home_result_views[promote_key]
        prewarmed_list = state["scroll"]
        prewarmed_card = state["card_by_id"][prewarmed_album.album_id]
        self.assertIs(self.window.result_scroll, active_list)
        self.assertEqual(prewarmed_list.count(), 1)

        self.assertTrue(self.window.prepare_home_result_view(promote_key))
        self.assertIs(self.window.result_scroll, prewarmed_list)
        self.assertIs(self.window.card_by_id[prewarmed_album.album_id], prewarmed_card)

    def test_catalog_page_inserts_all_list_items_in_short_timer_batches(self):
        query = PageQuery(mode="latest")
        self.window.home_result_views.clear()
        self.window.home_active_result_view_key = "latest:latest:v1"
        self.window.current_result_cache_key = "latest:latest:v1"
        self.window._active_catalog_query_key = query.key
        self.window.results_revealed = False
        books = [
            BookInfo(
                book_id=str(820000 + index),
                title=f"direct {index}",
                url="",
                cover_url="",
            )
            for index in range(16)
        ]

        self.window.on_catalog_page_loaded(query, 1, books, {"append": False})
        for _ in range(20):
            self.app.processEvents()

        self.assertEqual(self.window.result_scroll.count(), 16)
        self.assertEqual(len(self.window.card_by_id), 16)
        self.assertFalse(self.window.catalog_apply_pending)
        self.assertFalse(getattr(self.window, "catalog_direct_list_insert", False))

    def test_next_page_animation_is_the_final_list_item(self):
        list_widget = self.window.result_scroll
        self.window.result_stack.setCurrentWidget(list_widget)
        count_before = list_widget.count()

        self.window.show_home_append_loading()
        self.app.processEvents()

        loading_item = getattr(list_widget, "_append_loading_item", None)
        loading_label = getattr(list_widget, "_append_loading_label", None)
        self.assertIsNotNone(loading_item)
        self.assertIsNotNone(loading_label)
        self.assertEqual(list_widget.row(loading_item), list_widget.count() - 1)
        self.assertEqual(list_widget.count(), count_before + 1)
        self.assertFalse(loading_label.isHidden())
        self.assertTrue(loading_label.testAttribute(Qt.WA_TransparentForMouseEvents))

        album = self.album(60)
        self.window.append_visible_album_card(album, animate=False)
        self.assertEqual(list_widget.row(loading_item), list_widget.count() - 1)

        self.window.hide_home_append_loading()
        self.assertIsNone(getattr(list_widget, "_append_loading_item", None))
        self.assertEqual(list_widget.count(), count_before + 1)

    def test_initial_loading_restarts_and_reveal_stops_detail_movie(self):
        self.window.reset_results()

        self.assertIs(
            self.window.result_stack.currentWidget(),
            self.window.result_loading_page,
        )
        self.assertIsNotNone(
            getattr(self.window.result_loading_art, "_loading_movie", None)
        )

        self.window.reveal_results()

        self.assertIs(self.window.result_stack.currentWidget(), self.window.result_scroll)
        self.assertIsNone(getattr(self.window.result_loading_art, "_loading_movie", None))

    def test_list_card_defers_its_cover_until_it_is_painted(self):
        album = self.album(50)
        self.window.append_visible_album_card(album, animate=False)

        card = self.window.card_by_id[album.album_id]
        cover = card.findChild(QLabel, "albumCover")

        self.assertTrue(getattr(cover, "_defer_cover_request", False))
