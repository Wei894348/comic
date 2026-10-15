from __future__ import annotations

import unittest
from xml.etree import ElementTree

from jm_app.backend.runtime_paths import ui_dir
from jm_app.frontend.pages.profile import ProfilePageMixin
from jm_app.frontend.pages.navigation import NavigationPageMixin


class _Stack:
    def __init__(self, count: int):
        self._count = count
        self.current_index = 0

    def count(self) -> int:
        return self._count

    def setCurrentIndex(self, index: int):
        self.current_index = index


class _Button:
    def __init__(self):
        self.checked = False

    def setChecked(self, checked: bool):
        self.checked = checked


class _ProfileHarness(ProfilePageMixin):
    def __init__(self):
        self.profile_content_stack = _Stack(4)
        self.profile_nav_buttons = [_Button() for _ in range(4)]


class _NavigationHarness(NavigationPageMixin):
    def __init__(self, title: str):
        self.main_content_stack = _Stack(10)
        self.main_content_stack.current_index = 7
        self.page_navigation_stack = [(4, "账户中心"), (7, title)]
        self.active_navigation_position = 1
        self.home_search_mode = False

    def home_page_index(self):
        return 0

    def library_page_index(self):
        return 7

    def page_title_for_index(self, index: int):
        return "收藏与记录" if index == 7 else "账户中心"


class ProfilePageTest(unittest.TestCase):
    def setUp(self):
        self.page = _ProfileHarness()

    def test_switches_all_account_sections_in_place(self):
        for section in range(4):
            self.page.show_profile_section(section)
            self.assertEqual(self.page.profile_content_stack.current_index, section)
            self.assertTrue(self.page.profile_nav_buttons[section].checked)

    def test_favorite_more_switches_to_profile_favorite_section(self):
        self.page.open_profile_favorites()

        self.assertEqual(self.page.profile_content_stack.current_index, 2)
        self.assertTrue(self.page.profile_nav_buttons[2].checked)

    def test_history_more_switches_to_profile_history_section(self):
        self.page.open_profile_history()

        self.assertEqual(self.page.profile_content_stack.current_index, 3)
        self.assertTrue(self.page.profile_nav_buttons[3].checked)

    def test_account_library_breadcrumb_titles_remain_specific(self):
        for title in ("漫画收藏", "漫画观看记录"):
            page = _NavigationHarness(title)
            page.normalize_navigation_routes()
            self.assertEqual(page.page_navigation_stack[-1], (7, title))

    def test_profile_ui_omits_legacy_management_controls(self):
        root = ElementTree.parse(ui_dir() / "profile.ui").getroot()
        object_names = {element.get("name") for element in root.iter()}

        self.assertTrue(
            {
                "profileFavoriteManageButton",
                "profileHistoryManageButton",
                "profileRefreshButton",
                "profileFavoritePageHint",
                "profileHistoryPageHint",
            }.isdisjoint(object_names)
        )


if __name__ == "__main__":
    unittest.main()
