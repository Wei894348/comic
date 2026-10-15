from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider

from jm_app.frontend.feed_scroll_bar import (
    FEED_CARD_WIDTH,
    FEED_MIN_GAP,
    FeedListWidget,
    FeedScrollBar,
)


class FeedScrollBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_wheel_target_is_clamped_to_the_scroll_range(self):
        bar = FeedScrollBar()
        bar.setOrientation(Qt.Vertical)
        bar.setRange(0, 1000)
        bar.jump_to(200)
        bar.scroll_by(900)
        self.assertEqual(bar._target_value, 1000)
        bar.scroll_by(-1500)
        self.assertEqual(bar._target_value, 0)

    def test_target_is_clamped_when_loading_footer_changes_the_range(self):
        bar = FeedScrollBar()
        bar.setOrientation(Qt.Vertical)
        bar.setRange(0, 1000)
        bar._target_value = 900

        bar.setRange(0, 600)

        self.assertEqual(bar._target_value, 600)

    def test_thumb_size_stays_fixed_when_the_feed_range_grows(self):
        bar = FeedScrollBar()
        bar.setOrientation(Qt.Vertical)
        bar.resize(8, 500)
        bar.setRange(0, 1000)
        bar.setPageStep(200)
        bar.lock_thumb_size()

        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        initial_height = bar.style().subControlRect(
            QStyle.CC_ScrollBar, option, QStyle.SC_ScrollBarSlider, bar
        ).height()

        bar.setRange(0, 8000)
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        expanded_height = bar.style().subControlRect(
            QStyle.CC_ScrollBar, option, QStyle.SC_ScrollBarSlider, bar
        ).height()

        self.assertEqual(expanded_height, initial_height)

    def test_fixed_page_step_keeps_the_same_pixel_length_across_ranges(self):
        track_length = 500
        thumb_length = FeedScrollBar.FIXED_THUMB_LENGTH
        lengths = []
        for scroll_range in (100, 1000, 8000):
            page_step = FeedScrollBar.fixed_page_step(
                scroll_range, track_length, thumb_length
            )
            lengths.append(
                round(track_length * page_step / (scroll_range + page_step))
            )

        self.assertLessEqual(max(lengths) - min(lengths), 1)
        self.assertTrue(all(abs(length - thumb_length) <= 1 for length in lengths))

    def test_reset_does_not_disable_fixed_thumb_sizing(self):
        bar = FeedScrollBar()
        bar.reset_thumb_size()

        self.assertEqual(bar.FIXED_THUMB_LENGTH, 46)


class FeedListWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_adaptive_grid_distributes_spare_width_across_columns(self):
        cell_width = FeedListWidget.adaptive_cell_width(
            1216,
            FEED_CARD_WIDTH,
            FEED_MIN_GAP,
        )

        self.assertEqual(cell_width, 304)
        self.assertEqual(1216 // cell_width, 4)

    def test_adaptive_grid_never_makes_a_cell_smaller_than_its_card(self):
        self.assertEqual(
            FeedListWidget.adaptive_cell_width(
                180,
                FEED_CARD_WIDTH,
                FEED_MIN_GAP,
            ),
            FEED_CARD_WIDTH + FEED_MIN_GAP,
        )
