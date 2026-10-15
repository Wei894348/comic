from __future__ import annotations

import unittest
from pathlib import Path
from xml.etree import ElementTree

from jm_app.backend.runtime_paths import resource_dir, ui_dir


class NavigationPanelTest(unittest.TestCase):
    def test_navigation_panel_has_three_sections_and_account_subtitle(self):
        root = ElementTree.parse(ui_dir() / "navigation.ui").getroot()
        object_names = {element.get("name") for element in root.iter()}

        self.assertTrue(
            {
                "navNavigationSectionLayout",
                "navUserSectionLayout",
                "navSupportSectionLayout",
                "headerAccountMenu",
                "headerUserRoleLabel",
                "navDarkModeButton",
                "navCollapseButton",
            }.issubset(object_names)
        )

    def test_dashboard_header_has_styled_search_controls(self):
        root = ElementTree.parse(ui_dir() / "dashboard_header.ui").getroot()
        object_names = {element.get("name") for element in root.iter()}

        self.assertTrue(
            {"navSearchFrame", "navSearchEdit", "navSearchButton"}.issubset(
                object_names
            )
        )
        search_icon = resource_dir() / "nav_icons" / "line_search.svg"
        self.assertTrue(search_icon.exists())
        ElementTree.parse(search_icon)
        self.assertTrue(
            {
                "navNavigationSectionArrow",
                "navUserSectionArrow",
                "navSupportSectionArrow",
            }.isdisjoint(object_names)
        )

    def test_every_navigation_item_has_normal_and_active_line_icons(self):
        icon_dir = resource_dir() / "nav_icons"
        names = {
            "line_home",
            "line_category",
            "line_weekly",
            "line_download",
            "line_favorite",
            "line_comment",
            "line_reading",
            "line_folder",
            "line_history",
            "line_help",
            "line_settings",
            "line_moon",
            "line_collapse",
        }
        paths = [icon_dir / f"{name}{suffix}.svg" for name in names for suffix in ("", "_active")]

        self.assertTrue(all(path.exists() for path in paths))
        for path in paths:
            ElementTree.parse(Path(path))

    def test_navigation_icons_use_one_neutral_and_one_active_color(self):
        icon_dir = resource_dir() / "nav_icons"
        normal_paths = list(icon_dir.glob("line_*.svg"))
        normal_paths = [path for path in normal_paths if not path.stem.endswith("_active")]
        normal_paths.extend(icon_dir.glob("section_*.svg"))
        active_paths = list(icon_dir.glob("line_*_active.svg"))

        self.assertTrue(normal_paths)
        self.assertTrue(active_paths)
        self.assertEqual(
            {ElementTree.parse(path).getroot().get("stroke") for path in normal_paths},
            {"#718096"},
        )
        self.assertEqual(
            {ElementTree.parse(path).getroot().get("stroke") for path in active_paths},
            {"#f07800"},
        )

    def test_navigation_scrollbar_is_disabled_and_menu_spacing_is_compact(self):
        root = ElementTree.parse(ui_dir() / "navigation.ui").getroot()
        scroll = root.find(".//widget[@name='navScroll']")
        menu = root.find(".//layout[@name='navMenuLayout']")

        self.assertEqual(
            scroll.find("./property[@name='verticalScrollBarPolicy']/enum").text,
            "Qt::ScrollBarPolicy::ScrollBarAlwaysOff",
        )
        self.assertEqual(
            menu.find("./property[@name='spacing']/number").text,
            "1",
        )

    def test_section_labels_remove_global_vertical_padding(self):
        source = (
            ui_dir().parent
            / "src"
            / "jm_app"
            / "frontend"
            / "pages"
            / "navigation.py"
        ).read_text(encoding="utf-8")
        self.assertIn("font-size:14px; font-weight:800; padding:0;", source)


if __name__ == "__main__":
    unittest.main()
