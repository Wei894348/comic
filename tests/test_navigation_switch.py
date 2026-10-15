from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from jm_app.frontend.app_icon import icon_path, icon_paths
from jm_app.frontend.pages.navigation import NavigationPageMixin


class _NavigationHarness(NavigationPageMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.main_content_stack = QStackedWidget(self)
        for _index in range(4):
            self.main_content_stack.addWidget(QWidget())
        self.main_content_stack.currentChanged.connect(
            lambda _index: self.schedule_breadcrumb_update()
        )
        self.page_navigation_stack = [(0, "首页")]
        self.active_navigation_position = 0
        self.nav_buttons = {}
        self.category_rank_page_lock = False
        self.breadcrumb_detail_parent = ""
        self.breadcrumb_detail_parent_index = 0
        self.breadcrumb_updates = 0
        self.history_refreshes = 0
        self.theme_dark = False

    def clear_album_selection(self):
        return None

    def page_title_for_index(self, index: int) -> str:
        return f"页面 {index}"

    def home_page_index(self) -> int:
        return 0

    def detail_page_index(self) -> int:
        return 2

    def history_page_index(self) -> int:
        return 3

    def category_rank_page_index(self) -> int:
        return 1

    def update_breadcrumb(self, current_title: str = ""):
        self.breadcrumb_updates += 1

    def refresh_history_table(self):
        self.history_refreshes += 1

    def apply_dark_to_widget(self, _widget):
        return None


class NavigationSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.harness = _NavigationHarness()

    def tearDown(self):
        self.harness.close()
        self.app.processEvents()

    def test_page_switch_coalesces_breadcrumb_updates(self):
        self.harness.switch_page(1)
        self.assertEqual(self.harness.breadcrumb_updates, 0)

        self.app.processEvents()

        self.assertEqual(self.harness.breadcrumb_updates, 1)

    def test_history_render_is_deferred_until_after_first_frame(self):
        self.harness.switch_page(3)

        self.assertEqual(self.harness.main_content_stack.currentIndex(), 3)
        self.assertEqual(self.harness.history_refreshes, 0)
        QTest.qWait(40)
        self.app.processEvents()

        self.assertEqual(self.harness.history_refreshes, 1)

    def test_jmcomic_round_logo_is_the_primary_application_icon(self):
        self.assertEqual(icon_path().name, "jmcomic_logo_round.png")
        self.assertEqual(icon_paths()[0].name, "jmcomic_logo_round.png")
        self.assertTrue(icon_path().exists())
        self.assertTrue(icon_path().with_name("app.ico").exists())


if __name__ == "__main__":
    unittest.main()
