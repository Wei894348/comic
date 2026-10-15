from __future__ import annotations

import unittest
from xml.etree import ElementTree

from jm_app.backend.runtime_paths import resource_dir, ui_dir
from jm_app.frontend.pages.empty_state import library_empty_copy
from jm_app.frontend.pages.library_feed import LibraryFeedPageMixin


class _DiscoveryHarness(LibraryFeedPageMixin):
    def __init__(self):
        self.category_rank_page_lock = True
        self.switched_to = None
        self.overview_shown = False

    def category_rank_page_index(self):
        return 8

    def switch_page(self, index):
        self.switched_to = index

    def show_category_rank_overview(self):
        self.overview_shown = True


class LibraryEmptyStateTest(unittest.TestCase):
    def test_empty_state_ui_contains_discovery_controls(self):
        root = ElementTree.parse(ui_dir() / "library_empty_state.ui").getroot()
        object_names = {element.get("name") for element in root.iter()}

        self.assertTrue(
            {
                "libraryEmptyState",
                "libraryEmptyIcon",
                "libraryEmptyTitle",
                "libraryEmptyDescription",
                "libraryEmptyDiscoverButton",
            }.issubset(object_names)
        )
        ElementTree.parse(resource_dir() / "empty_discover.svg")

        layout = root.find(".//layout[@name='libraryEmptyStateLayout']")
        widget_items = [
            item.find("widget")
            for item in layout.findall("item")
            if item.find("widget") is not None
        ]
        names = [widget.get("name") for widget in widget_items]
        self.assertLess(names.index("libraryEmptyTitle"), names.index("libraryEmptyIcon"))
        icon_item = next(
            item
            for item in layout.findall("item")
            if item.find("widget") is not None
            and item.find("widget").get("name") == "libraryEmptyIcon"
        )
        self.assertIn("AlignHCenter", icon_item.get("alignment", ""))

    def test_empty_copy_matches_collection_and_reading_contexts(self):
        self.assertEqual(
            library_empty_copy("暂无云端收藏"),
            ("暂无收藏内容", "去发现喜欢的漫画并收藏起来吧"),
        )
        self.assertEqual(
            library_empty_copy("暂无云端观看记录"),
            ("暂无漫画记录", "去发现感兴趣的漫画，开始阅读吧"),
        )
        self.assertEqual(
            library_empty_copy("本期没有推荐漫画"),
            ("暂无漫画", "这里暂时没有漫画，去分类与排行看看吧"),
        )

    def test_discovery_action_opens_category_rank_overview(self):
        page = _DiscoveryHarness()
        page.open_library_discovery_page()

        self.assertFalse(page.category_rank_page_lock)
        self.assertEqual(page.switched_to, 8)
        self.assertTrue(page.overview_shown)


if __name__ == "__main__":
    unittest.main()
