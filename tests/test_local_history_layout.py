from __future__ import annotations

import unittest
from xml.etree import ElementTree

from jm_app.backend.runtime_paths import ui_dir


class LocalHistoryLayoutTest(unittest.TestCase):
    def test_old_download_history_header_is_removed(self):
        root = ElementTree.parse(ui_dir() / "history.ui").getroot()
        object_names = {element.get("name") for element in root.iter()}

        self.assertTrue(
            {
                "historyHeaderLayout",
                "historyTitle",
                "historyFeedStatus",
                "historySettingsButton",
            }.isdisjoint(object_names)
        )


if __name__ == "__main__":
    unittest.main()
