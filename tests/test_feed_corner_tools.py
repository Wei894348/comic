from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from jm_app.frontend.feed_corner_tools import FeedCornerTools


class FeedCornerToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tools_stay_in_the_bottom_right_and_dispatch_actions(self):
        calls = []
        parent = QWidget()
        parent.resize(800, 600)
        tools = FeedCornerTools(
            parent,
            lambda: calls.append("refresh"),
            lambda: calls.append("top"),
        )
        parent.show()
        self.app.processEvents()

        self.assertEqual(tools.x(), 800 - tools.width() - tools.RIGHT_MARGIN)
        self.assertEqual(tools.y(), 600 - tools.height() - tools.BOTTOM_MARGIN)
        self.assertEqual(tools.top_button.text(), "顶部")

        tools.refresh_button.click()
        tools.top_button.click()
        self.assertEqual(calls, ["refresh", "top"])

        parent.resize(960, 720)
        self.app.sendEvent(parent, QEvent(QEvent.Type.Resize))
        self.assertEqual(tools.x(), 960 - tools.width() - tools.RIGHT_MARGIN)
        self.assertEqual(tools.y(), 720 - tools.height() - tools.BOTTOM_MARGIN)

        parent.close()

    def test_tools_remain_visible_when_a_result_stack_changes_page(self):
        stack = QStackedWidget()
        stack.resize(800, 600)
        first = QWidget()
        second = QWidget()
        stack.addWidget(first)
        stack.addWidget(second)
        tools = FeedCornerTools(stack, lambda: None, lambda: None)
        stack.show()

        stack.setCurrentWidget(second)
        self.app.processEvents()

        self.assertTrue(tools.isVisible())
        self.assertIs(tools.parentWidget(), stack)
        self.assertEqual(tools.x(), 800 - tools.width() - tools.RIGHT_MARGIN)
        self.assertEqual(tools.y(), 600 - tools.height() - tools.BOTTOM_MARGIN)
        stack.close()


if __name__ == "__main__":
    unittest.main()
