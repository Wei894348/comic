from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from jm_app.frontend.pages.local_history import LocalHistoryPageMixin
from jm_app.repositories.state_repository import StateRepository


class LocalReadingHistoryTest(unittest.TestCase):
    def test_repository_returns_latest_chapter_per_comic_with_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = StateRepository(Path(directory) / "state.db")
            repository.record_reading_history("7", "70", "Book", "cover", "第一话", 1, 3)
            repository.save_progress("7", "70", 8, 20, "first")
            time.sleep(0.01)
            repository.record_reading_history("7", "71", "Book", "cover", "第二话", 2, 3)
            repository.save_progress("7", "71", 4, 18, "second")

            rows = repository.reading_history()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["chapter_id"], "71")
            self.assertEqual(rows[0]["chapter_title"], "第二话")
            self.assertEqual(rows[0]["page_index"], 4)
            self.assertEqual(rows[0]["page_total"], 18)

    def test_delete_removes_history_and_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = StateRepository(Path(directory) / "state.db")
            repository.record_reading_history("9", "90", "Book", "", "Chapter", 1, 1)
            repository.save_progress("9", "90", 5, 10, "source")
            repository.delete_reading_history("9")

            self.assertEqual(repository.reading_history(), [])
            self.assertEqual(repository.progress("9", "90"), (1, 0, ""))

    def test_relative_time_matches_jmcomic_history_caption(self):
        now = time.time()
        self.assertEqual(LocalHistoryPageMixin.relative_reading_time(now - 120), "2分钟前")
        self.assertEqual(LocalHistoryPageMixin.relative_reading_time(now - 2 * 86400), "2天前")


if __name__ == "__main__":
    unittest.main()
