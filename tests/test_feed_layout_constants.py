from __future__ import annotations

import unittest

from jm_app.frontend.feed_scroll_bar import (
    FEED_CARD_HEIGHT,
    FEED_GRID_ROW_HEIGHT,
    PROFILE_CARD_HEIGHT,
    PROFILE_GRID_ROW_HEIGHT,
)


class FeedLayoutConstantsTest(unittest.TestCase):
    def test_card_heights_stay_at_the_full_design_size(self):
        self.assertEqual(FEED_CARD_HEIGHT, 438)
        self.assertEqual(PROFILE_CARD_HEIGHT, 410)

    def test_feed_rows_do_not_add_vertical_space_after_cards(self):
        self.assertEqual(FEED_GRID_ROW_HEIGHT, FEED_CARD_HEIGHT)

    def test_profile_rows_do_not_add_vertical_space_after_cards(self):
        self.assertEqual(PROFILE_GRID_ROW_HEIGHT, PROFILE_CARD_HEIGHT)


if __name__ == "__main__":
    unittest.main()
