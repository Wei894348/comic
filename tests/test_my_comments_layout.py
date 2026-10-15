from __future__ import annotations

import unittest
from xml.etree import ElementTree

from jm_app.backend.runtime_paths import ui_dir


class MyCommentsLayoutTest(unittest.TestCase):
    def setUp(self):
        self.header = ElementTree.parse(ui_dir() / "my_comments.ui").getroot()
        self.card = ElementTree.parse(ui_dir() / "comment_card.ui").getroot()

    @staticmethod
    def _widget(root, name: str):
        return root.find(f".//widget[@name='{name}']")

    @staticmethod
    def _size(widget, property_name: str):
        size = widget.find(f"./property[@name='{property_name}']/size")
        return int(size.find("width").text), int(size.find("height").text)

    def test_personal_comment_header_has_search_profile_filters_and_sort(self):
        required = (
            "myCommentsTitle",
            "myCommentsSearchEdit",
            "myCommentsProfileCard",
            "myCommentsAvatarLabel",
            "myCommentsAllButton",
            "myCommentsPublishedButton",
            "myCommentsRepliedButton",
            "myCommentsLikedButton",
            "myCommentsSortCombo",
        )
        for name in required:
            with self.subTest(name=name):
                self.assertIsNotNone(self._widget(self.header, name))

    def test_comment_card_reserves_stable_cover_geometry(self):
        cover = self._widget(self.card, "commentAlbumCoverLabel")
        self.assertIsNotNone(cover)
        self.assertEqual(self._size(cover, "minimumSize"), (58, 78))
        self.assertEqual(self._size(cover, "maximumSize"), (58, 78))

    def test_comment_card_keeps_detail_comment_identity_controls(self):
        for name in (
            "commentAvatarLabel",
            "commentIndexLabel",
            "commentNameLabel",
            "commentLevelLabel",
            "commentTitleLabel",
            "commentDateLabel",
            "commentLikeLabel",
            "commentReplyButton",
            "commentAlbumButton",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(self._widget(self.card, name))


if __name__ == "__main__":
    unittest.main()
