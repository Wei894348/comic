from __future__ import annotations

import hashlib
import time
import unittest

from tests.qt_test_utils import close_test_window, prepare_qt_test_environment

prepare_qt_test_environment()

from PySide6.QtGui import QPalette
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from jm_app.backend.models import AlbumMeta
from jm_app.frontend.pages.navigation import NAVIGATION_ICON_X, NAVIGATION_TEXT_X
from jm_app.frontend.ui import MainWindow


def image_digest(widget: QWidget) -> str:
    image = widget.grab().toImage()
    size = image.sizeInBytes()
    return hashlib.sha256(bytes(image.bits()[:size])).hexdigest()


def palette_colors(widget: QWidget) -> tuple[str, ...]:
    palette = widget.palette()
    roles = (
        QPalette.ColorRole.Window,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Base,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.Button,
        QPalette.ColorRole.ButtonText,
    )
    return tuple(palette.color(role).name() for role in roles)


class AppearanceThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        # Prevent the persisted auto-login timer from changing control state
        # while a theme assertion is running.
        self.window.login_auto_started = True
        self.window.set_dark_mode(False, persist=False)
        self.window.resize(1180, 760)
        self.window.result_stack.setCurrentWidget(self.window.result_loading_page)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        close_test_window(self.window, self.app)

    def test_dark_mode_does_not_touch_login_page_or_main_window(self):
        self.window.stack.setCurrentWidget(self.window.login_page)
        self.window.login_page.setEnabled(True)
        self.window.set_login_controls_enabled(True)
        focus = self.app.focusWidget()
        if focus is not None:
            focus.clearFocus()
        self.app.processEvents()

        main_style = self.window.styleSheet()
        login_style = self.window.login_page.styleSheet()
        login_palette = palette_colors(self.window.login_page)
        login_enabled = self.window.login_page.isEnabled()
        controls_enabled = tuple(
            widget.isEnabled()
            for widget in (
                self.window.login_user_edit,
                self.window.login_pass_edit,
                self.window.login_cookie_edit,
                self.window.login_btn,
            )
        )
        before = image_digest(self.window.login_page)

        self.window.set_dark_mode(True, persist=False)
        self.app.processEvents()
        after = image_digest(self.window.login_page)

        self.assertEqual(self.window.styleSheet(), main_style)
        self.assertEqual(self.window.login_page.styleSheet(), login_style)
        self.assertEqual(palette_colors(self.window.login_page), login_palette)
        self.assertEqual(self.window.login_page.isEnabled(), login_enabled)
        self.assertEqual(
            tuple(
                widget.isEnabled()
                for widget in (
                    self.window.login_user_edit,
                    self.window.login_pass_edit,
                    self.window.login_cookie_edit,
                    self.window.login_btn,
                )
            ),
            controls_enabled,
        )
        self.assertEqual(after, before)

    def test_dark_mode_keeps_visible_layout_geometry_stable(self):
        self.window.stack.setCurrentWidget(self.window.app_page)
        self.app.processEvents()
        watched = (
            self.window.navigation_container,
            self.window.main_header,
            self.window.main_content_stack,
            self.window.main_content_stack.currentWidget(),
        )
        before = tuple(widget.geometry() for widget in watched)

        started = time.perf_counter()
        self.window.set_dark_mode(True, persist=False)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.app.processEvents()

        self.assertEqual(tuple(widget.geometry() for widget in watched), before)
        self.assertEqual(len(self.window._themed_root_styles), 3)
        self.assertLess(elapsed_ms, 500)

    def test_light_mode_restores_original_root_state(self):
        self.window.stack.setCurrentWidget(self.window.app_page)
        root = self.window.main_content_stack.currentWidget()
        original_style = root.styleSheet()
        original_palette = palette_colors(root)
        original_fill = root.autoFillBackground()
        backgrounds = tuple(
            (
                widget,
                palette_colors(widget),
                widget.autoFillBackground(),
            )
            for widget in (
                self.window.app_page,
                self.window.dashboard_content_column,
            )
        )

        self.window.set_dark_mode(True, persist=False)
        self.window.set_dark_mode(False, persist=False)

        self.assertEqual(root.styleSheet(), original_style)
        self.assertEqual(palette_colors(root), original_palette)
        self.assertEqual(root.autoFillBackground(), original_fill)
        for widget, colors, auto_fill in backgrounds:
            self.assertEqual(palette_colors(widget), colors)
            self.assertEqual(widget.autoFillBackground(), auto_fill)
            self.assertFalse(bool(widget.property("darkTheme")))

    def test_hidden_page_is_colored_only_when_requested(self):
        hidden = QWidget(self.window.app_page)
        hidden.setStyleSheet("QWidget { color:#123456; }")
        original_style = hidden.styleSheet()

        self.window.set_dark_mode(True, persist=False)
        self.assertEqual(hidden.styleSheet(), original_style)

        self.window.apply_dark_to_widget(hidden)
        self.assertIn("background:#17191d", hidden.styleSheet())

        self.window.set_dark_mode(False, persist=False)
        self.assertEqual(hidden.styleSheet(), original_style)

    def test_dark_mode_preserves_album_grid_and_card_geometry(self):
        self.window.stack.setCurrentWidget(self.window.app_page)
        self.window.result_stack.setCurrentWidget(self.window.result_scroll)
        self.window.clear_result_grid()
        album = AlbumMeta(
            album_id="theme-geometry",
            title="theme geometry",
            url="",
            tags=["tag one", "tag two"],
        )
        self.window.append_visible_album_card(album, animate=False)
        self.app.processEvents()
        card = self.window.card_by_id[album.album_id]
        title = card.findChild(QLabel, "albumTitle")
        item = self.window.result_scroll.item(0)
        before = (
            self.window.result_columns(),
            self.window.result_card_width(),
            self.window.result_scroll.viewport().size(),
            self.window.result_scroll.gridSize(),
            item.sizeHint(),
            card.size(),
            title.geometry(),
        )

        self.window.set_dark_mode(True, persist=False)
        self.app.processEvents()

        self.assertEqual(
            (
                self.window.result_columns(),
                self.window.result_card_width(),
                self.window.result_scroll.viewport().size(),
                self.window.result_scroll.gridSize(),
                item.sizeHint(),
                card.size(),
                title.geometry(),
            ),
            before,
        )

    def test_user_tabs_receive_dark_theme_when_selected(self):
        self.window.stack.setCurrentWidget(self.window.app_page)
        self.window.main_content_stack.setCurrentIndex(self.window.library_page_index())
        tab_indexes = {
            self.window.library_tabs.widget(index).objectName(): index
            for index in range(self.window.library_tabs.count())
        }
        self.window.library_tabs.setCurrentIndex(tab_indexes["commentsTab"])
        self.window.set_dark_mode(True, persist=False)
        self.assertIn("QFrame#myCommentsProfileCard", self.window.my_comments_header.styleSheet())

        for object_name in ("favoritesTab", "remoteHistoryTab", "localTab"):
            self.window.library_tabs.setCurrentIndex(tab_indexes[object_name])
            self.app.processEvents()
            self.assertIn(
                "background:#17191d",
                self.window.main_content_stack.currentWidget().styleSheet(),
            )
        self.assertIn("QFrame#localFavoriteBottomBar", self.window.local_favorite_page.styleSheet())

        self.window.switch_page(self.window.history_page_index())
        self.app.processEvents()
        self.assertIn(
            "background:#17191d",
            self.window.main_content_stack.currentWidget().styleSheet(),
        )

    def test_dark_mode_button_defers_heavy_refresh_to_the_event_loop(self):
        self.window.stack.setCurrentWidget(self.window.app_page)
        self.window.nav_dark_mode_button.click()
        self.assertFalse(self.window.nav_dark_mode_button.isEnabled())

        self.app.processEvents()

        self.assertTrue(self.window.theme_dark)
        self.assertTrue(self.window.nav_dark_mode_button.isEnabled())
        self.assertEqual(self.window.nav_dark_mode_button.text(), "浅色模式")

    def test_navigation_fits_without_a_vertical_scrollbar(self):
        self.window.stack.setCurrentWidget(self.window.app_page)
        self.app.processEvents()
        panel = self.window._navigation_panel_widget
        nav_scroll = panel.findChild(QScrollArea, "navScroll")
        self.assertIsNotNone(nav_scroll)
        self.assertEqual(
            nav_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        buttons = [
            button
            for button in self.window._navigation_panel_widget.findChildren(
                type(self.window.nav_dark_mode_button)
            )
            if button.property("navRole") == "item"
        ]
        self.assertTrue(buttons)
        self.assertTrue(all(button.height() == 34 for button in buttons))
        self.assertTrue(
            all(bool(button.property("alignedNavigationColumns")) for button in buttons)
        )
        button_icon_columns = {
            button.mapTo(panel, QPoint(NAVIGATION_ICON_X, 0)).x()
            for button in buttons
        }
        button_text_columns = {
            button.mapTo(panel, QPoint(NAVIGATION_TEXT_X, 0)).x()
            for button in buttons
        }
        self.assertEqual(len(button_icon_columns), 1)
        self.assertEqual(len(button_text_columns), 1)
        self.assertLessEqual(
            nav_scroll.widget().sizeHint().height(),
            nav_scroll.viewport().height(),
        )
        menu_layout = nav_scroll.widget().layout()
        self.assertGreater(menu_layout.spacing(), 1)
        self.assertFalse(
            any(
                menu_layout.itemAt(index).spacerItem() is not None
                for index in range(menu_layout.count())
            )
        )
        account = panel.findChild(QWidget, "headerAccountMenu")
        self.assertIsNotNone(account)
        self.assertTrue(account.isVisibleTo(panel))
        self.assertLessEqual(account.geometry().bottom(), panel.contentsRect().bottom())
        for name in (
            "navNavigationSectionLabel",
            "navUserSectionLabel",
            "navSupportSectionLabel",
        ):
            label = panel.findChild(QLabel, name)
            self.assertIsNotNone(label)
            self.assertGreaterEqual(label.height(), label.fontMetrics().height())
        section_icon_columns = {
            panel.findChild(QLabel, name).mapTo(panel, QPoint(0, 0)).x()
            for name in (
                "navNavigationSectionIcon",
                "navUserSectionIcon",
                "navSupportSectionIcon",
            )
        }
        section_text_columns = {
            panel.findChild(QLabel, name).mapTo(panel, QPoint(0, 0)).x()
            for name in (
                "navNavigationSectionLabel",
                "navUserSectionLabel",
                "navSupportSectionLabel",
            )
        }
        self.assertEqual(section_icon_columns, button_icon_columns)
        self.assertEqual(section_text_columns, button_text_columns)


if __name__ == "__main__":
    unittest.main()
