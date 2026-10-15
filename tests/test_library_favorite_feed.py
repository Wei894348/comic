from __future__ import annotations

import unittest
from xml.etree import ElementTree

from jm_app.backend.models import AlbumMeta
from jm_app.backend.runtime_paths import ui_dir
from jm_app.frontend.pages.library_feed import LibraryFeedPageMixin


def album(album_id: str) -> AlbumMeta:
    return AlbumMeta(album_id=album_id, title=f"Album {album_id}", url="")


class _PagingHarness(LibraryFeedPageMixin):
    def __init__(self):
        self.library_favorite_loading = False
        self.library_favorite_has_more = True
        self.library_favorite_page = 1
        self.library_favorites = [album("1")]
        self.refresh_calls = 0
        self.refresh_result = True

    def refresh_library_favorites(self):
        self.refresh_calls += 1
        return self.refresh_result


class LibraryFavoriteFeedTest(unittest.TestCase):
    def test_library_ui_removes_title_count_and_favorite_pager(self):
        root = ElementTree.parse(ui_dir() / "library.ui").getroot()
        object_names = {element.get("name") for element in root.iter()}

        self.assertTrue(
            {
                "libraryHeaderLayout",
                "libraryTitle",
                "libraryStatusLabel",
                "favoritePager",
                "libraryFavoritePreviousButton",
                "libraryFavoritePageLabel",
                "libraryFavoriteNextButton",
            }.isdisjoint(object_names)
        )

    def test_next_page_is_requested_once_and_page_rolls_back_on_rejection(self):
        page = _PagingHarness()
        page.load_next_library_favorite_page()

        self.assertEqual(page.library_favorite_page, 2)
        self.assertEqual(page.refresh_calls, 1)

        page = _PagingHarness()
        page.refresh_result = False
        page.load_next_library_favorite_page()

        self.assertEqual(page.library_favorite_page, 1)
        self.assertEqual(page.refresh_calls, 1)

    def test_loading_or_completed_feed_does_not_request_another_page(self):
        for loading, has_more in ((True, True), (False, False)):
            page = _PagingHarness()
            page.library_favorite_loading = loading
            page.library_favorite_has_more = has_more
            page.load_next_library_favorite_page()
            self.assertEqual(page.refresh_calls, 0)
            self.assertEqual(page.library_favorite_page, 1)

    def test_cross_page_and_same_page_duplicates_are_removed(self):
        unique = LibraryFeedPageMixin.unique_library_albums(
            [album("1")], [album("1"), album("2"), album("2"), album("3")]
        )
        self.assertEqual([item.album_id for item in unique], ["2", "3"])

if __name__ == "__main__":
    unittest.main()
