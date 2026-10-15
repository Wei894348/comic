from __future__ import annotations

import unittest

from tests.qt_test_utils import close_test_window, prepare_qt_test_environment

prepare_qt_test_environment()

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from jm_app.backend.models import AlbumMeta, ChapterMeta
from jm_app.frontend.ui import MainWindow


class DetailMetadataSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.resize(1180, 760)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        close_test_window(self.window, self.app)

    def detail_badge(self, text: str) -> QLabel:
        matches = [
            label
            for label in self.window.detail_tags_flow_widget.findChildren(QLabel)
            if label.text() == text
        ]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_author_and_tags_open_search_without_changing_styles(self):
        album = AlbumMeta(
            album_id="detail-search",
            title="可搜索详情",
            url="",
            author="测试作者",
            tags=["冒险", "剧情"],
        )
        self.window.albums[album.album_id] = album
        author_style = self.window.detail_author_label.styleSheet()
        opened = []
        self.window.open_search_results = (
            lambda query, **options: opened.append((query, options))
        )

        self.window.show_chapters(album.album_id)
        self.app.processEvents()

        adventure = self.detail_badge("冒险")
        self.assertEqual(self.window.detail_author_label.styleSheet(), author_style)
        self.assertEqual(adventure.styleSheet(), self.window.tag_badge_style(False))
        self.assertEqual(
            self.window.detail_author_label.cursor().shape(), Qt.PointingHandCursor
        )
        self.assertEqual(adventure.cursor().shape(), Qt.PointingHandCursor)

        QTest.mouseClick(self.window.detail_author_label, Qt.LeftButton)
        QTest.mouseClick(adventure, Qt.LeftButton)

        self.assertEqual(
            opened,
            [
                ("测试作者", {"preserve_path": True}),
                ("冒险", {"preserve_path": True}),
            ],
        )

    def test_placeholder_metadata_is_not_searchable(self):
        album = AlbumMeta(
            album_id="detail-placeholder",
            title="无元数据详情",
            url="",
            author="-",
            tags=[],
        )
        self.window.albums[album.album_id] = album
        opened = []
        self.window.open_search_results = (
            lambda query, **options: opened.append((query, options))
        )

        self.window.show_chapters(album.album_id)
        self.app.processEvents()

        placeholder = self.detail_badge("-")
        self.assertEqual(self.window.detail_author_label.cursor().shape(), Qt.ArrowCursor)
        self.assertEqual(placeholder.cursor().shape(), Qt.ArrowCursor)

        QTest.mouseClick(self.window.detail_author_label, Qt.LeftButton)
        QTest.mouseClick(placeholder, Qt.LeftButton)

        self.assertEqual(opened, [])

    def test_detail_search_appends_to_the_existing_breadcrumb_route(self):
        home_index = self.window.home_page_index()
        detail_index = self.window.detail_page_index()
        search_index = self.window.search_page_index()
        self.window.main_content_stack.setCurrentIndex(detail_index)
        self.window.page_navigation_stack = [
            (home_index, "首页"),
            (detail_index, "漫画详情"),
        ]
        self.window.active_navigation_position = 1
        searches = []
        self.window.start_category_search = searches.append

        self.window.open_detail_metadata_search("冒险")
        self.app.processEvents()

        self.assertEqual(
            self.window.page_navigation_stack,
            [
                (home_index, "首页"),
                (detail_index, "漫画详情"),
                (search_index, "搜索"),
            ],
        )
        self.assertEqual(self.window.active_navigation_position, 2)
        self.assertEqual(self.window.main_content_stack.currentIndex(), search_index)
        self.assertEqual(searches, ["冒险"])
        visible_routes = [
            button
            for button in self.window.breadcrumb_route_buttons
            if not button.isHidden()
        ]
        self.assertEqual(
            [button.text() for button in visible_routes],
            ["首页", "漫画详情", "搜索"],
        )
        self.assertEqual(
            [button.isChecked() for button in visible_routes],
            [False, False, True],
        )

    def test_home_breadcrumb_restores_content_shown_before_search(self):
        home_album = AlbumMeta("home-album", "首页漫画", "")
        search_album = AlbumMeta("search-album", "搜索漫画", "")
        home_key = "latest:v1"
        self.window.current_result_cache_key = home_key
        self.window.home_active_result_view_key = home_key
        self.window.result_cache[home_key] = [home_album]
        self.window.restore_album_list(home_key, [home_album], fast_switch=True)
        self.window._capture_home_result_view()
        home_scroll = self.window.result_scroll

        home_index = self.window.home_page_index()
        detail_index = self.window.detail_page_index()
        search_index = self.window.search_page_index()
        self.window.main_content_stack.setCurrentIndex(detail_index)
        self.window.page_navigation_stack = [
            (home_index, "首页"),
            (detail_index, "漫画详情"),
        ]
        self.window.active_navigation_position = 1

        def show_search_results(query: str) -> None:
            self.window.search_edit.setText(query)
            search_key = self.window.result_cache_key()
            self.window.prepare_home_result_view(search_key)
            self.window.restore_album_list(search_key, [search_album], fast_switch=True)
            self.window.result_cache[search_key] = [search_album]

        self.window.start_category_search = show_search_results
        self.window.open_detail_metadata_search("冒险")
        self.app.processEvents()
        self.assertEqual(self.window.main_content_stack.currentIndex(), search_index)
        self.assertIsNot(self.window.result_scroll, home_scroll)
        self.assertEqual(
            [album.album_id for album in self.window.result_albums],
            ["search-album"],
        )

        self.window.navigate_breadcrumb_route(0)
        self.app.processEvents()

        self.assertFalse(self.window.home_search_mode)
        self.assertEqual(self.window.current_result_cache_key, home_key)
        self.assertIs(self.window.result_scroll, home_scroll)
        self.assertEqual(
            [album.album_id for album in self.window.result_albums],
            ["home-album"],
        )
        self.assertIn("home-album", self.window.card_by_id)
        self.assertNotIn("search-album", self.window.card_by_id)

        self.window.navigate_breadcrumb_route(2)
        self.app.processEvents()

        self.assertTrue(self.window.home_search_mode)
        self.assertEqual(self.window.main_content_stack.currentIndex(), search_index)
        self.assertEqual(getattr(self.window, "active_result_surface", ""), "search")
        self.assertIsNot(self.window.result_scroll, home_scroll)
        self.assertEqual(
            [album.album_id for album in self.window.result_albums],
            ["search-album"],
        )
        self.assertIn("search-album", self.window.card_by_id)
        self.assertNotIn("home-album", self.window.card_by_id)

    def test_search_completion_stays_on_search_page(self):
        search_index = self.window.search_page_index()
        self.window.activate_home_search_results("冒险")
        self.window.main_content_stack.setCurrentIndex(search_index)
        self.window.page_navigation_stack = [(search_index, "搜索")]
        self.window.active_navigation_position = 0
        self.window.result_albums = [AlbumMeta("search-finished", "搜索结果", "")]
        self.window.result_total_count = 1
        self.window.result_render_limit = 1
        self.window.results_revealed = True
        self.window.auto_load_has_more = False
        self.window.maybe_auto_load_if_result_viewport_not_full = lambda: None

        self.window.on_scrape_finished(1, False)
        self.app.processEvents()

        self.assertEqual(self.window.main_content_stack.currentIndex(), search_index)
        self.assertEqual(self.window.page_navigation_stack, [(search_index, "搜索")])
        self.assertEqual(self.window.backend_label.text(), "搜索结果已加载")

    def test_late_search_completion_does_not_leave_open_detail_page(self):
        home_index = self.window.home_page_index()
        detail_index = self.window.detail_page_index()
        search_index = self.window.search_page_index()
        self.window.activate_home_search_results("冒险")
        self.window.main_content_stack.setCurrentIndex(detail_index)
        self.window.page_navigation_stack = [
            (home_index, "首页"),
            (search_index, "搜索"),
            (detail_index, "漫画详情"),
        ]
        self.window.active_navigation_position = 2
        self.window.result_albums = [AlbumMeta("late-search", "搜索结果", "")]
        self.window.result_total_count = 1
        self.window.result_render_limit = 1
        self.window.results_revealed = True
        self.window.auto_load_has_more = False
        self.window.maybe_auto_load_if_result_viewport_not_full = lambda: None

        self.window.on_scrape_finished(1, False)
        self.app.processEvents()

        self.assertEqual(self.window.main_content_stack.currentIndex(), detail_index)
        self.assertEqual(self.window.active_navigation_position, 2)
        self.assertEqual(
            self.window.page_navigation_stack,
            [
                (home_index, "首页"),
                (search_index, "搜索"),
                (detail_index, "漫画详情"),
            ],
        )

    def test_detail_result_survives_search_reset_and_breadcrumb_return(self):
        album = AlbumMeta(
            "detail-survives",
            "详情保留漫画",
            "",
            author="作者",
            tags=["剧情"],
        )
        self.window.albums[album.album_id] = album
        self.window.detail_cache[album.album_id] = album
        self.window.current_album_id = album.album_id
        home_index = self.window.home_page_index()
        detail_index = self.window.detail_page_index()
        search_index = self.window.search_page_index()
        self.window.main_content_stack.setCurrentIndex(search_index)
        self.window.page_navigation_stack = [
            (home_index, "首页"),
            (detail_index, "漫画详情"),
            (search_index, "搜索"),
        ]
        self.window.active_navigation_position = 2
        self.window.reset_results()
        self.assertNotIn(album.album_id, self.window.albums)

        loaded = AlbumMeta(
            album.album_id,
            album.title,
            "",
            author="作者",
            tags=["剧情"],
            description="搜索后仍然存在的详情",
            chapters=[ChapterMeta("chapter-1", "第一章", "", 1)],
        )
        self.window.on_chapters_loaded(album.album_id, loaded)
        self.window.navigate_breadcrumb_route(1)
        self.app.processEvents()

        self.assertEqual(self.window.main_content_stack.currentIndex(), detail_index)
        self.assertEqual(self.window.detail_title_label.text(), album.title)
        self.assertEqual(
            self.window.detail_description_label.text(),
            "搜索后仍然存在的详情",
        )
        self.assertEqual(self.window.chapter_table.rowCount(), 1)
        self.assertIsNotNone(self.window.current_album())

    def test_tag_search_breadcrumb_return_keeps_existing_detail_without_request(self):
        album = AlbumMeta(
            "detail-tag-return",
            "标签返回详情",
            "",
            author="详情作者",
            tags=["剧情"],
            description="返回时应保持的详情内容",
            chapters=[ChapterMeta("detail-chapter", "第一章", "", 1)],
        )
        self.window.albums[album.album_id] = album
        self.window.detail_cache[album.album_id] = album
        home_index = self.window.home_page_index()
        detail_index = self.window.detail_page_index()
        search_index = self.window.search_page_index()
        self.window.main_content_stack.setCurrentIndex(detail_index)
        self.window.page_navigation_stack = [
            (home_index, "首页"),
            (detail_index, "漫画详情"),
        ]
        self.window.active_navigation_position = 1
        self.window.show_chapters(album.album_id)
        title_before = self.window.detail_title_label.text()
        description_before = self.window.detail_description_label.text()
        chapter_rows_before = self.window.chapter_table.rowCount()
        detail_requests = []
        cover_loads = []
        self.window.detail_controller.load = detail_requests.append
        self.window.load_cover = lambda current: cover_loads.append(current.album_id)
        self.window.start_category_search = lambda _query: self.window.reset_results()

        QTest.mouseClick(self.detail_badge("剧情"), Qt.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.window.main_content_stack.currentIndex(), search_index)

        self.window.navigate_breadcrumb_route(1)
        self.app.processEvents()

        self.assertEqual(self.window.main_content_stack.currentIndex(), detail_index)
        self.assertEqual(detail_requests, [])
        self.assertEqual(cover_loads, [])
        self.assertEqual(self.window.detail_title_label.text(), title_before)
        self.assertEqual(
            self.window.detail_description_label.text(), description_before
        )
        self.assertEqual(self.window.chapter_table.rowCount(), chapter_rows_before)


if __name__ == "__main__":
    unittest.main()
