from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from jm_app.frontend.pages.appearance import DARK_STYLE
from jm_app.frontend.pages.weekly import WeeklyPageMixin


class _WeeklyPageHarness(WeeklyPageMixin, QWidget):
    def load_ui_widget(self, template_name, expected_type=None, parent=None):
        path = Path(__file__).resolve().parents[1] / "ui" / template_name
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open weekly form: {path}")
        widget = QUiLoader().load(ui_file, parent)
        ui_file.close()
        return widget

    def refresh_weekly_albums(self, force=False):
        return None


class WeeklyPageLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.original_font = cls.app.font()
        available_fonts = set(QFontDatabase.families())
        for family in (
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "SimSun",
        ):
            if family in available_fonts:
                cls.app.setFont(QFont(family, 10))
                break

    @classmethod
    def tearDownClass(cls):
        cls.app.setFont(cls.original_font)

    def setUp(self):
        self.harness = _WeeklyPageHarness()
        self.panel = self.harness._build_weekly_panel()

    def tearDown(self):
        self.panel.close()
        self.harness.close()
        self.app.processEvents()

    def test_toolbar_fits_minimum_application_content_width(self):
        period_text = "2026年第249期  07.24 - 07.17"
        self.harness.weekly_period_combo.addItem(period_text, "249")
        self.panel.resize(702, 560)
        self.panel.show()
        self.app.processEvents()

        toolbar = self.panel.findChild(QFrame, "weeklyToolbar")
        controls = [
            self.panel.findChild(QWidget, name)
            for name in (
                "weeklyPeriodIcon",
                "weeklyPeriodCaption",
                "weeklyPeriodCombo",
                "weeklyUpdateIcon",
                "weeklyUpdateHint",
                "weeklyRefreshButton",
            )
        ]
        self.assertTrue(all(controls))
        self.assertEqual(toolbar.height(), 76)
        self.assertLessEqual(controls[-1].geometry().right(), toolbar.contentsRect().right())
        for left, right in zip(controls, controls[1:]):
            self.assertLess(left.geometry().right(), right.geometry().left())

        combo = self.harness.weekly_period_combo
        self.assertGreaterEqual(combo.width(), combo.minimumWidth())
        self.assertEqual(combo.minimumContentsLength(), 20)
        self.assertIn("QComboBox#weeklyPeriodCombo::down-arrow", self.panel.styleSheet())

    def test_weekly_controls_have_dark_theme_overrides(self):
        for selector in (
            "QFrame#weeklyToolbar",
            "QComboBox#weeklyPeriodCombo",
            "QPushButton#weeklyRefreshButton",
            "QTabWidget#weeklyTabs",
        ):
            self.assertIn(selector, DARK_STYLE)


if __name__ == "__main__":
    unittest.main()
