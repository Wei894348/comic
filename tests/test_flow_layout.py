from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from jm_app.frontend.flow_layout import FlowLayout


class FlowLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_wraps_items_instead_of_expanding_horizontal_minimum(self):
        parent = QWidget()
        layout = FlowLayout(parent, horizontal_spacing=8, vertical_spacing=8)
        for text in ("单行本", "阿黑颜", "肛交", "巨乳", "泳装", "性勒索"):
            label = QLabel(text, parent)
            label.setFixedSize(QSize(92, 28))
            layout.addWidget(label)

        self.assertGreater(layout.heightForWidth(220), layout.heightForWidth(700))
        self.assertLessEqual(layout.minimumSize().width(), 92)


if __name__ == "__main__":
    unittest.main()
