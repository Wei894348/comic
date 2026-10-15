from __future__ import annotations

import unittest
from xml.etree import ElementTree

from jm_app.backend.runtime_paths import ui_dir


class AccountLibraryLayoutTest(unittest.TestCase):
    def setUp(self):
        self.root = ElementTree.parse(ui_dir() / "comment_card.ui").getroot()

    def _size_values(self, object_name: str, property_name: str):
        widget = self.root.find(f".//widget[@name='{object_name}']")
        self.assertIsNotNone(widget)
        size = widget.find(f"./property[@name='{property_name}']/size")
        self.assertIsNotNone(size)
        return int(size.find("width").text), int(size.find("height").text)

    def test_comment_avatar_uses_compact_conversation_size(self):
        self.assertEqual(
            self._size_values("commentAvatarLabel", "minimumSize"),
            (44, 44),
        )
        self.assertEqual(
            self._size_values("commentAvatarLabel", "maximumSize"),
            (44, 44),
        )

    def test_comment_row_does_not_restore_oversized_height(self):
        self.assertEqual(
            self._size_values("commentCard", "minimumSize"),
            (0, 112),
        )


if __name__ == "__main__":
    unittest.main()
