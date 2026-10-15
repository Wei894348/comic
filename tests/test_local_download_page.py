from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

from jm_app.backend.runtime_paths import ui_dir
from jm_app.frontend.pages.local_download import LocalDownloadPageMixin


class _LocalDownloadHarness(LocalDownloadPageMixin):
    def __init__(self, local_path: Path):
        self.download_history = [
            {
                "title": "测试漫画",
                "album_id": "123",
                "path": str(local_path),
                "image_dir": str(local_path),
                "format": "images",
                "cover_url": "",
            }
        ]
        self.local_download_search = SimpleNamespace(
            text=lambda: ""
        )
        self.local_download_format = SimpleNamespace(
            currentData=lambda: ""
        )

    @staticmethod
    def history_record_has_local_file(record):
        return Path(record["path"]).exists()


class LocalDownloadPageTest(unittest.TestCase):
    def test_form_has_filter_and_download_feed_placeholder(self):
        names = {
            item.get("name")
            for item in ElementTree.parse(ui_dir() / "local_download.ui").getroot().iter()
        }
        self.assertTrue(
            {
                "localDownloadSearch",
                "localDownloadFormat",
                "localDownloadScroll",
                "localDownloadOpenFolder",
            }.issubset(names)
        )

    def test_completed_resource_is_selected_once(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = _LocalDownloadHarness(Path(directory))
            records = harness.local_download_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0][1]["album_id"], "123")


if __name__ == "__main__":
    unittest.main()
