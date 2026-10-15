from __future__ import annotations

import unittest
from types import SimpleNamespace

from tests.qt_test_utils import close_test_window, prepare_qt_test_environment

prepare_qt_test_environment()

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from jm_app.frontend.ui import MainWindow
from jm_app.frontend.pages.comments import CommentsPageMixin


class CommentAlbumNavigationTest(unittest.TestCase):
    def test_comment_album_link_seeds_an_unloaded_album(self):
        opened = []
        host = SimpleNamespace(
            albums={},
            detail_cache={},
            default_cover_url=lambda album_id: f"https://img/{album_id}_3x4.jpg",
            open_album_detail=lambda album_id: opened.append(album_id),
            show_toast=lambda _message: None,
        )

        CommentsPageMixin.open_comment_album_detail(host, "99999999", "漫画标题")

        self.assertEqual(opened, ["99999999"])
        self.assertEqual(host.albums["99999999"].title, "漫画标题")
        self.assertIn("99999999_3x4.jpg", host.albums["99999999"].cover_url)


class CommentCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        close_test_window(self.window, self.app)

    def test_parses_jmcomic_forum_comment_fields(self):
        opened = []
        self.window.open_comment_album_detail = (
            lambda album_id, album_name="": opened.append((album_id, album_name))
        )
        card = self.window.create_comment_card(
            {
                "CID": "98",
                "UID": "1234",
                "username": "wintergazer",
                "expinfo": {"level": "8", "level_name": "猛兽的太阳"},
                "photo": "",
                "content": "好重的人工智能味，硬不起来",
                "likes": "12",
                "addtime": "Jul 23, 2026",
                "AID": "1444544",
                "name": "漫画标题",
                "replys": [{"CID": "99"}, {"CID": "100"}],
            },
            7,
        )

        self.assertEqual(card.findChild(QLabel, "commentIndexLabel").text(), "#7")
        self.assertEqual(card.findChild(QLabel, "commentNameLabel").text(), "wintergazer")
        self.assertEqual(card.findChild(QLabel, "commentLevelLabel").text(), "LV 8")
        self.assertEqual(card.findChild(QLabel, "commentTitleLabel").text(), "猛兽的太阳")
        self.assertEqual(card.findChild(QLabel, "commentDateLabel").text(), "Jul 23, 2026")
        self.assertEqual(card.findChild(QLabel, "commentLikeLabel").text(), "♡ 12")
        self.assertEqual(card.findChild(QPushButton, "commentReplyButton").text(), "回复 (2)")
        self.assertEqual(card.findChild(QPushButton, "commentAlbumButton").text(), "漫画标题")
        card.findChild(QPushButton, "commentAlbumButton").click()

        self.assertEqual(opened, [("1444544", "漫画标题")])

    def test_builds_mirror_urls_for_jm_relative_avatar_path(self):
        urls = self.window.comment_avatar_urls("avatar.jpg")

        self.assertTrue(urls)
        self.assertTrue(all("/media/users/avatar.jpg" in url for url in urls))
        self.assertTrue(self.window.comment_avatar_urls("nopic-Female.gif"))
        self.assertTrue(self.window.comment_avatar_urls("", "1234"))

    def test_removes_forum_html_from_comment_content(self):
        text = self.window.clean_comment_content('<div style="flex-direction:row;">校园催眠后宫<br>第二行</div>')

        self.assertEqual(text, "校园催眠后宫\n第二行")

    def test_header_account_menu_exposes_profile_and_logout(self):
        self.window.session_username = "admin"
        self.window.update_header_profile()
        menu = self.window.create_header_account_menu()

        self.assertEqual(self.window.user_label.text(), "admin")
        self.assertEqual(self.window.avatar_button.size().width(), 36)
        self.assertTrue(self.window.header_account_arrow_button.isEnabled())
        self.assertEqual([action.text() for action in menu.actions() if not action.isSeparator()], ["个人资料", "退出登录"])

    def test_navigation_avatar_is_center_cropped_to_one_round_layer(self):
        source = QPixmap(80, 48)
        source.fill(QColor("#ef8faf"))

        self.window.apply_navigation_avatar_pixmap(source)

        self.assertTrue(bool(self.window.avatar_button.property("hasAvatar")))
        self.assertEqual(self.window.avatar_button.iconSize().width(), 34)
        rendered = self.window.avatar_button.icon().pixmap(34, 34).toImage()
        self.assertEqual(rendered.pixelColor(0, 0).alpha(), 0)

    def test_navigation_search_reuses_home_search(self):
        calls = []
        self.window.start_scrape = lambda: calls.append("search")
        self.window.nav_search_edit.setText("测试关键词")

        self.window.search_from_navigation()

        self.assertEqual(self.window.search_edit.text(), "测试关键词")
        self.assertEqual(calls, ["search"])

    def test_category_tag_opens_search_result_surface(self):
        calls = []
        self.window.start_scrape = lambda: calls.append("search")
        self.window.open_category_rank_page()

        self.window.open_search_results("剧情向")

        self.assertTrue(self.window.home_search_mode)
        self.assertEqual(self.window.main_content_stack.currentIndex(), self.window.search_page_index())
        self.assertFalse(self.window.category_rank_page_lock)
        self.assertEqual(self.window.search_result_query_label.text(), "剧情向")
        self.assertEqual(self.window.search_edit.text(), "剧情向")
        self.assertEqual(calls, ["search"])

    def test_navigation_category_and_rank_reuse_home_actions(self):
        calls = []
        self.window.start_category_filter = lambda category, label: calls.append(("category", category, label))
        self.window.start_rank_scrape = lambda rank_type: calls.append(("rank", rank_type))

        self.window.open_navigation_category("doujin", "同人")
        self.window.open_navigation_rank("week")

        self.assertEqual(calls, [("category", "doujin", "同人"), ("rank", "week")])

    def test_category_rank_navigation_opens_its_own_page(self):
        self.window.open_category_rank_page()

        self.assertEqual(self.window.main_content_stack.currentIndex(), self.window.category_rank_page_index())
        self.assertEqual(self.window.category_rank_stack.count(), 2)
        self.assertTrue(self.window.findChild(QPushButton, "categoryRankOverviewButton").isChecked())
        self.assertEqual(len(self.window.findChildren(QPushButton, "categoryRankTagOption")), 47)
        self.assertIsNone(self.window.findChild(QPushButton, "categoryRankRankingButton"))

    def test_weekly_navigation_opens_retained_weekly_page(self):
        self.window.weekly_categories_loaded = True

        self.window.nav_weekly_button.click()

        self.assertEqual(self.window.main_content_stack.currentIndex(), self.window.weekly_page_index())
        self.assertEqual(self.window.current_breadcrumb_page_title(), "每周必看")
        self.assertTrue(self.window.nav_weekly_button.isChecked())

    def test_weekly_tabs_use_jmcomic_category_type_mapping(self):
        self.assertEqual(
            [self.window.weekly_type_for_index(index) for index in range(3)],
            ["manga", "hanman", "another"],
        )
        self.assertIsNot(self.window.weekly_lists["manga"], self.window.result_scroll)
        self.assertIsNot(self.window.weekly_lists["hanman"], self.window.weekly_lists["manga"])
        self.assertIsNot(self.window.weekly_lists["another"], self.window.weekly_lists["manga"])

    def test_weekly_periods_preserve_api_order_and_trigger_current_period(self):
        requested = []
        self.window.refresh_weekly_albums = lambda force=False: requested.append(
            self.window.current_weekly_key()
        )

        self.window.sync_weekly_categories(
            [
                {"id": "249", "time": "07.24 - 07.17", "title": "2026年第249期"},
                {"id": "248", "time": "07.17 - 07.10", "title": "2026年第248期"},
            ]
        )

        self.assertEqual(self.window.weekly_period_combo.count(), 2)
        self.assertEqual(self.window.weekly_period_combo.currentData(), "249")
        self.assertEqual(requested, [("249", "manga")])
        self.window.weekly_period_combo.setCurrentIndex(1)
        self.assertEqual(requested[-1], ("248", "manga"))

    def test_category_top_tab_keeps_results_on_category_page(self):
        calls = []
        self.window.start_category_filter = lambda category, label: calls.append((category, label))
        self.window.open_category_rank_page()

        self.window.show_category_rank_results("doujin", "同人")

        self.assertEqual(self.window.main_content_stack.currentIndex(), self.window.category_rank_page_index())
        self.assertIs(self.window.category_rank_stack.currentWidget(), self.window.category_rank_results_page)
        self.assertTrue(self.window.keeps_category_rank_results_visible())
        self.assertEqual(calls, [("doujin", "同人")])

    def test_latest_category_tab_stays_on_category_page(self):
        calls = []
        self.window.start_category_filter = lambda category, label: calls.append((category, label))
        self.window.open_category_rank_page()

        self.window.findChild(QPushButton, "categoryRankAllButton").click()

        self.assertEqual(self.window.main_content_stack.currentIndex(), self.window.category_rank_page_index())
        self.assertTrue(self.window.keeps_category_rank_results_visible())
        self.assertEqual(calls, [("0", "最新A漫")])

    def test_category_loading_rejects_automatic_home_redirect(self):
        self.window.start_category_filter = lambda _category, _label: None
        self.window.open_category_rank_page()
        self.window.show_category_rank_results("0", "最新A漫")

        self.window.switch_page(self.window.home_page_index())

        self.assertEqual(self.window.main_content_stack.currentIndex(), self.window.category_rank_page_index())
        self.window.category_rank_page_lock = False
        self.window.switch_page(self.window.home_page_index())
        self.assertEqual(self.window.main_content_stack.currentIndex(), self.window.home_page_index())

    def test_category_completion_does_not_request_home_page(self):
        pages = []
        self.window.start_category_filter = lambda _category, _label: None
        self.window.open_category_rank_page()
        self.window.show_category_rank_results("0", "最新A漫")
        self.window.task_done = lambda _message, page_index=None: pages.append(page_index)
        self.window.result_albums = []
        self.window.result_total_count = 0

        self.window.on_scrape_finished(1, False)

        self.assertEqual(pages, [None])

    def test_loaded_category_does_not_reload_same_list(self):
        calls = []
        self.window.open_category_rank_page()
        self.window.move_result_stack_to_category_page()
        self.window.category_rank_stack.setCurrentWidget(self.window.category_rank_results_page)
        self.window.active_category = "doujin"
        self.window.current_result_cache_key = "category:category:v2:doujin"
        self.window.results_revealed = True
        self.window.result_scroll.addItem("loaded")
        self.window.start_scrape = lambda: calls.append("reload")

        self.window.start_category_filter("doujin", "同人")

        self.assertEqual(calls, [])

    def test_restored_result_stack_follows_home_headers(self):
        self.window.start_category_filter = lambda _category, _label: None
        self.window.show_category_rank_results("doujin", "同人")

        self.window.restore_result_stack_to_home()

        expected_index = max(
            self.window.home_root_layout.indexOf(self.window.home_category_scroll),
            self.window.home_root_layout.indexOf(self.window.search_result_toolbar),
        ) + 1
        self.assertEqual(self.window.home_root_layout.indexOf(self.window.result_stack), expected_index)
