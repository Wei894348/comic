from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication

from jm_app.backend.models import AlbumMeta
from jm_app.frontend.pages.library_feed import LibraryFeedPageMixin


class _RemoteHistoryHarness(LibraryFeedPageMixin):
    def __init__(self):
        self.library_remote_history = []
        self.library_remote_history_page = 1
        self.library_remote_history_loading = True
        self.library_remote_history_has_more = True
        self.library_remote_history_total = 0
        self.library_remote_history_reload_pending = False
        self.library_remote_history_layout = object()
        self.render_calls = []
        self.route_counts = []

    @staticmethod
    def album_from_dict(item):
        return AlbumMeta(
            album_id=str(item.get("album_id") or ""),
            title=str(item.get("title") or ""),
            url="",
        )

    def render_library_albums(self, layout, albums, empty_text, append=False):
        self.render_calls.append((list(albums), empty_text, append))

    def set_library_route_count(self, route, count, unit):
        self.route_counts.append((route, count, unit))

    def check_library_remote_history_scroll_end(self):
        return None


class RemoteHistoryContinuousFeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_pages_are_appended_without_replacing_existing_cards(self):
        page = _RemoteHistoryHarness()
        page.apply_library_remote_history_result(
            {
                "albums": [
                    {"album_id": "1", "title": "one"},
                    {"album_id": "2", "title": "two"},
                ],
                "page": 1,
                "total": 3,
            }
        )

        self.assertEqual([album.album_id for album in page.library_remote_history], ["1", "2"])
        self.assertFalse(page.render_calls[-1][2])
        self.assertTrue(page.library_remote_history_has_more)

        page.library_remote_history_loading = True
        page.apply_library_remote_history_result(
            {
                "albums": [
                    {"album_id": "2", "title": "duplicate"},
                    {"album_id": "3", "title": "three"},
                ],
                "page": 2,
                "total": 3,
            }
        )

        self.assertEqual(
            [album.album_id for album in page.library_remote_history],
            ["1", "2", "3"],
        )
        self.assertEqual([album.album_id for album in page.render_calls[-1][0]], ["3"])
        self.assertTrue(page.render_calls[-1][2])
        self.assertFalse(page.library_remote_history_has_more)
        self.assertEqual(page.route_counts[-1], ("remoteHistoryTab", 3, "本"))


if __name__ == "__main__":
    unittest.main()
