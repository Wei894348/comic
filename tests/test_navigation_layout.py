from __future__ import annotations

import unittest
from xml.etree import ElementTree

from jm_app.backend.runtime_paths import ui_dir
from jm_app.frontend.pages.navigation import NAVIGATION_PANEL_WIDTH


class NavigationLayoutTest(unittest.TestCase):
    def test_designer_panel_width_matches_navigation_logic(self):
        root = ElementTree.parse(ui_dir() / "navigation.ui").getroot()
        panel = root.find(".//widget[@name='navigationPanel']")

        self.assertIsNotNone(panel)
        widths = [
            int(width.text)
            for width in panel.findall("./property/size/width")
        ]
        self.assertEqual(widths, [NAVIGATION_PANEL_WIDTH, NAVIGATION_PANEL_WIDTH])

    def test_user_routes_have_explicit_labels(self):
        root = ElementTree.parse(ui_dir() / "navigation.ui").getroot()
        expected = {
            "navFavoriteButton": "我的收藏",
            "navCommentButton": "我的评论",
            "navRemoteHistoryButton": "我的阅读",
            "navLocalFavoriteButton": "本地收藏",
            "navLocalDownloadButton": "本地下载",
            "navHistoryButton": "本地记录",
        }
        for object_name, label in expected.items():
            widget = root.find(f".//widget[@name='{object_name}']")
            self.assertIsNotNone(widget)
            self.assertEqual(widget.find("./property[@name='text']/string").text, label)


if __name__ == "__main__":
    unittest.main()
