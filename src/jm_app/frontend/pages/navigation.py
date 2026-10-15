"""Application navigation and retained breadcrumb routes."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    QSize,
    QTimer,
    Qt,
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProxyStyle,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyleOptionButton,
)

from ...backend.runtime_paths import resource_dir

if TYPE_CHECKING:
    from ..ui import MainWindow


# Controls the complete left column: menu, section labels and account row.
NAVIGATION_PANEL_WIDTH = 200
NAVIGATION_ICON_X = 10
NAVIGATION_ICON_SIZE = 20
NAVIGATION_TEXT_X = 42
NAVIGATION_MAX_ROW_SPACING = 24


class AlignedNavigationButtonStyle(QProxyStyle):
    """Paint every navigation icon and label on the same fixed columns."""

    def drawControl(self, element, option, painter, widget=None):
        if (
            element != QStyle.ControlElement.CE_PushButtonLabel
            or not isinstance(option, QStyleOptionButton)
            or widget is None
            or widget.property("navRole") != "item"
        ):
            return super().drawControl(element, option, painter, widget)

        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        mode = (
            QIcon.Mode.Disabled
            if not enabled
            else QIcon.Mode.Active
            if hovered
            else QIcon.Mode.Normal
        )
        state = QIcon.State.On if checked else QIcon.State.Off
        icon_x = (
            max(0, (option.rect.width() - NAVIGATION_ICON_SIZE) // 2)
            if not option.text
            else NAVIGATION_ICON_X
        )
        icon_rect = QRect(
            option.rect.left() + icon_x,
            option.rect.top()
            + max(0, (option.rect.height() - NAVIGATION_ICON_SIZE) // 2),
            NAVIGATION_ICON_SIZE,
            NAVIGATION_ICON_SIZE,
        )

        painter.save()
        option.icon.paint(painter, icon_rect, Qt.AlignCenter, mode, state)
        if option.text:
            painter.setFont(widget.font())
            painter.setPen(option.palette.buttonText().color())
            text_rect = option.rect.adjusted(NAVIGATION_TEXT_X, 0, -6, 0)
            painter.drawText(
                text_rect,
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextShowMnemonic,
                option.text,
            )
        painter.restore()


class NavigationSpacingController(QObject):
    """Distribute menu rows over the available height without overflowing."""

    def __init__(self, scroll: QScrollArea, menu_layout, parent=None):
        super().__init__(parent)
        self.scroll = scroll
        self.menu_layout = menu_layout
        self._update_pending = False
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self.update_spacing)
        scroll.viewport().installEventFilter(self)
        self.remove_bottom_stretch()
        self.menu_layout.setAlignment(Qt.AlignTop)
        self.schedule_update()

    def schedule_update(self) -> None:
        if not self._update_timer.isActive():
            self._update_timer.start(0)

    def remove_bottom_stretch(self) -> None:
        for index in range(self.menu_layout.count() - 1, -1, -1):
            item = self.menu_layout.itemAt(index)
            if item.spacerItem() is not None:
                self.menu_layout.takeAt(index)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            if not self._update_pending:
                self._update_pending = True
                self.schedule_update()
        return super().eventFilter(watched, event)

    def update_spacing(self) -> None:
        self._update_pending = False
        heights = []
        for index in range(self.menu_layout.count()):
            item = self.menu_layout.itemAt(index)
            if item.spacerItem() is not None:
                continue
            heights.append(max(item.minimumSize().height(), item.sizeHint().height()))
        if len(heights) < 2:
            return
        margins = self.menu_layout.contentsMargins()
        available = max(
            0,
            self.scroll.viewport().height() - margins.top() - margins.bottom(),
        )
        gap_count = len(heights) - 1
        free_height = max(0, available - sum(heights))
        spacing = max(
            1,
            min(NAVIGATION_MAX_ROW_SPACING, free_height // gap_count),
        )
        if self.menu_layout.spacing() != spacing:
            self.menu_layout.setSpacing(spacing)
            self.menu_layout.invalidate()


class NavigationPageMixin:
    """Owns page indexes, breadcrumb history, and side-panel navigation."""

    @staticmethod
    def navigation_icon(name: str) -> QIcon:
        icon = QIcon()
        icon_dir = resource_dir() / "nav_icons"
        normal = icon_dir / f"{name}.svg"
        active = icon_dir / f"{name}_active.svg"
        if normal.exists():
            icon.addFile(str(normal), QSize(20, 20), QIcon.Normal, QIcon.Off)
        if active.exists():
            icon.addFile(str(active), QSize(20, 20), QIcon.Normal, QIcon.On)
            icon.addFile(str(active), QSize(20, 20), QIcon.Active, QIcon.On)
        return icon

    def apply_navigation_visual_system(self: "MainWindow", panel: QFrame) -> None:
        aligned_button_style = AlignedNavigationButtonStyle()
        aligned_button_style.setParent(panel)
        self.navigation_button_style = aligned_button_style
        button_icons = {
            "navHomeButton": "line_home",
            "navCategoryRankButton": "line_category",
            "navWeeklyButton": "line_weekly",
            "navDownloadButton": "line_download",
            "navFavoriteButton": "line_favorite",
            "navCommentButton": "line_comment",
            "navRemoteHistoryButton": "line_reading",
            "navLocalFavoriteButton": "line_folder",
            "navLocalDownloadButton": "line_download",
            "navHistoryButton": "line_history",
            "navAboutButton": "line_help",
            "navSettingsButton": "line_settings",
            "navDarkModeButton": "line_moon",
            "navCollapseButton": "line_collapse",
        }
        for object_name, icon_name in button_icons.items():
            button = panel.findChild(QPushButton, object_name)
            if button is None:
                continue
            button.setIcon(self.navigation_icon(icon_name))
            button.setIconSize(QSize(20, 20))
            button.setFixedHeight(34)
            button.setStyle(aligned_button_style)
            button.setProperty("alignedNavigationColumns", True)

        section_rows = (
            (
                "navNavigationSectionLayout",
                "navNavigationSectionIcon",
                "navNavigationSectionLabel",
            ),
            (
                "navUserSectionLayout",
                "navUserSectionIcon",
                "navUserSectionLabel",
            ),
            (
                "navSupportSectionLayout",
                "navSupportSectionIcon",
                "navSupportSectionLabel",
            ),
        )
        for layout_name, icon_name, title_name in section_rows:
            layout = panel.findChild(QHBoxLayout, layout_name)
            icon_label = panel.findChild(QLabel, icon_name)
            title_label = panel.findChild(QLabel, title_name)
            if layout is None or any(
                label is None for label in (icon_label, title_label)
            ):
                continue
            layout.setContentsMargins(NAVIGATION_ICON_X, 1, 8, 1)
            layout.setSpacing(NAVIGATION_TEXT_X - NAVIGATION_ICON_X - NAVIGATION_ICON_SIZE)
            icon_label.setFixedSize(NAVIGATION_ICON_SIZE, NAVIGATION_ICON_SIZE)
            icon_label.setAlignment(Qt.AlignCenter)
            title_label.setFixedHeight(24)
            title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.setAlignment(icon_label, Qt.AlignVCenter)
            layout.setAlignment(title_label, Qt.AlignVCenter)

        icon_dir = resource_dir() / "nav_icons"
        section_icons = {
            "navNavigationSectionIcon": "section_navigation.svg",
            "navUserSectionIcon": "section_user.svg",
            "navSupportSectionIcon": "section_support.svg",
        }
        for object_name, file_name in section_icons.items():
            label = panel.findChild(QLabel, object_name)
            path = icon_dir / file_name
            if label is not None and path.exists():
                label.setPixmap(QIcon(str(path)).pixmap(20, 20))
                label.setAlignment(Qt.AlignCenter)
        nav_scroll = panel.findChild(QScrollArea, "navScroll")
        if nav_scroll is not None:
            nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            menu_layout = nav_scroll.widget().layout() if nav_scroll.widget() else None
            if menu_layout is not None:
                menu_layout.setContentsMargins(0, 0, 0, 0)
                menu_layout.setSpacing(1)
                self.navigation_spacing_controller = NavigationSpacingController(
                    nav_scroll, menu_layout, panel
                )
        navigation_layout = panel.layout()
        if navigation_layout is not None:
            navigation_layout.setContentsMargins(8, 7, 8, 7)
            navigation_layout.setSpacing(5)
        account_layout = panel.findChild(QHBoxLayout, "headerAccountMenuLayout")
        if account_layout is not None:
            account_layout.setContentsMargins(6, 7, 6, 7)
            account_layout.setSpacing(5)
        account_menu = panel.findChild(QFrame, "headerAccountMenu")
        if account_menu is not None:
            account_menu.setFixedHeight(52)
        avatar_button = panel.findChild(QPushButton, "profileAvatarButton")
        if avatar_button is not None:
            avatar_button.setFixedSize(36, 36)
        account_arrow = panel.findChild(QPushButton, "headerAccountArrowButton")
        if account_arrow is not None:
            account_arrow.setFixedSize(20, 20)

        panel.setStyleSheet(
            """
            QFrame#navigationPanel {
                background:#fbfcff; border:1px solid #e7eaf1;
                border-radius:10px;
            }
            QScrollArea#navScroll, QWidget#navScrollContent {
                background:transparent; border:0;
            }
            QScrollArea#navScroll QScrollBar:vertical {
                width:4px; margin:0; background:transparent;
            }
            QScrollArea#navScroll QScrollBar::handle:vertical {
                min-height:28px; border-radius:2px; background:#c7ceda;
            }
            QScrollArea#navScroll QScrollBar::add-line:vertical,
            QScrollArea#navScroll QScrollBar::sub-line:vertical {
                width:0; height:0; background:transparent;
            }
            QLabel#navNavigationSectionLabel,
            QLabel#navUserSectionLabel,
            QLabel#navSupportSectionLabel {
                color:#344054; background:transparent;
                font-size:14px; font-weight:800; padding:0;
            }
            QPushButton[navRole="item"] {
                min-height:34px; max-height:34px; padding:0 10px 0 10px; text-align:left;
                color:#344054; background:transparent;
                border:0; border-left:4px solid transparent;
                border-radius:7px; font-size:14px;
            }
            QPushButton[navRole="item"]:hover {
                color:#f07800; background:#f6f7fb;
            }
            QPushButton[navRole="item"]:checked {
                color:#f07800; background:#fff0e5;
                border-left-color:#f07800; font-weight:800;
            }
            QFrame#navigationPanel[collapsed="true"] QPushButton[navRole="item"] {
                padding:0; text-align:center; border-left:0;
            }
            QFrame#navDivider, QFrame#navSupportDivider {
                color:#e5e8ef; background:#e5e8ef;
                border:0; min-height:1px; max-height:1px;
                margin:3px 0;
            }
            QFrame#headerAccountMenu {
                background:#f0f2ff; border:0; border-radius:8px;
            }
            QFrame#headerAccountMenu:hover { background:#e9edff; }
            QPushButton#profileAvatarButton {
                color:#ffffff; background:#667085; border:1px solid #667085;
                border-radius:18px; font-size:13px; font-weight:800; padding:0;
            }
            QPushButton#profileAvatarButton[hasAvatar="true"] {
                background:transparent; border-color:#d9e0ea;
            }
            QPushButton#profileAvatarButton:hover { border-color:#f07800; }
            QLabel#headerUserLabel {
                color:#26344a; background:transparent;
                font-size:11px; font-weight:800;
            }
            QLabel#headerUserRoleLabel {
                color:#8a94a6; background:transparent; font-size:9px;
            }
            QPushButton#headerAccountArrowButton {
                color:#718096; background:transparent; border:0;
                border-radius:5px; font-size:20px; font-weight:500;
            }
            QPushButton#headerAccountArrowButton:hover {
                color:#f07800; background:#fff0e5;
            }
            QFrame#connectionCard { background:transparent; border:0; }
            """
        )

    def apply_dashboard_search_visual_system(
        self: "MainWindow", header: QFrame
    ) -> None:
        search_frame = header.findChild(QFrame, "navSearchFrame")
        search_edit = header.findChild(QLineEdit, "navSearchEdit")
        search_button = header.findChild(QPushButton, "navSearchButton")
        if any(widget is None for widget in (search_frame, search_edit, search_button)):
            return

        search_icon_path = resource_dir() / "nav_icons" / "line_search.svg"
        if search_icon_path.exists():
            search_edit.addAction(
                QIcon(str(search_icon_path)),
                QLineEdit.ActionPosition.LeadingPosition,
            )
        search_frame.setMinimumSize(360, 44)
        search_frame.setMaximumSize(520, 44)
        search_edit.setMinimumHeight(40)
        search_button.setMinimumSize(78, 40)
        search_button.setMaximumHeight(40)
        search_button.setCursor(Qt.PointingHandCursor)

        header.setStyleSheet(
            """
            QFrame#navSearchFrame {
                background:transparent; border:0;
            }
            QLineEdit#navSearchEdit {
                min-height:40px; color:#344054; background:#ffffff;
                border:1px solid #d6e0f0; border-radius:20px;
                padding:0 14px; font-size:14px;
                selection-background-color:#8bb5f5;
            }
            QLineEdit#navSearchEdit:hover {
                border-color:#b6cae8; background:#fdfefe;
            }
            QLineEdit#navSearchEdit:focus {
                border:2px solid #83adf2; padding:0 13px;
                background:#ffffff;
            }
            QPushButton#navSearchButton {
                min-width:78px; min-height:40px; max-height:40px;
                color:#ffffff; background:#5b8def;
                border:0; border-radius:20px;
                padding:0 18px; font-size:14px; font-weight:800;
            }
            QPushButton#navSearchButton:hover { background:#477be3; }
            QPushButton#navSearchButton:pressed { background:#356bd7; }
            """
        )

    def home_page_index(self: "MainWindow") -> int:
        return 0

    def settings_page_index(self: "MainWindow") -> int:
        return 2

    def history_page_index(self: "MainWindow") -> int:
        return 3

    def about_page_index(self: "MainWindow") -> int:
        return 4

    def profile_page_index(self: "MainWindow") -> int:
        return 5

    def detail_page_index(self: "MainWindow") -> int:
        return 6

    def library_page_index(self: "MainWindow") -> int:
        return 7

    def category_rank_page_index(self: "MainWindow") -> int:
        return 8

    def weekly_page_index(self: "MainWindow") -> int:
        return 9

    def local_download_page_index(self: "MainWindow") -> int:
        return 10

    def search_page_index(self: "MainWindow") -> int:
        return 11

    def queue_page_index(self: "MainWindow") -> int:
        return 1

    def downloading_page_index(self: "MainWindow") -> int:
        return self.queue_page_index()

    def completed_page_index(self: "MainWindow") -> int:
        return self.queue_page_index()

    def page_title_for_index(self: "MainWindow", index: int) -> str:
        return {
            self.home_page_index(): "首页",
            self.queue_page_index(): "下载",
            self.settings_page_index(): "设置",
            self.history_page_index(): "看过的漫画",
            self.about_page_index(): "关于",
            self.profile_page_index(): "账户中心",
            self.detail_page_index(): "漫画详情",
            self.library_page_index(): "收藏与记录",
            self.category_rank_page_index(): "分类",
            self.weekly_page_index(): "每周必看",
            self.local_download_page_index(): "本地下载",
            self.search_page_index(): "搜索",
        }.get(index, "首页")

    def current_breadcrumb_page_title(self: "MainWindow") -> str:
        if not hasattr(self, "main_content_stack"):
            return "首页"
        return self.page_title_for_index(self.main_content_stack.currentIndex())

    def normalize_navigation_routes(self: "MainWindow") -> None:
        """Keep one canonical route per page and a stable home-rooted path."""
        if not self.page_navigation_stack:
            return
        active_route = None
        if 0 <= self.active_navigation_position < len(self.page_navigation_stack):
            active_route = self.page_navigation_stack[self.active_navigation_position]
        normalized = []
        seen = set()
        for route_index, route_title in self.page_navigation_stack:
            if hasattr(self, "main_content_stack") and not (
                0 <= route_index < self.main_content_stack.count()
            ):
                continue
            # Account-library entries and comments intentionally use a more
            # specific route title than their shared backing page index.
            canonical_title = self.page_title_for_index(route_index)
            library_route_titles = {"评论", "漫画收藏", "漫画观看记录"}
            is_search_result = (
                route_index == self.search_page_index()
                and route_title == "搜索"
                and bool(getattr(self, "home_search_mode", False))
            )
            if (
                route_index != self.library_page_index()
                or route_title not in library_route_titles
            ) and not is_search_result:
                route_title = canonical_title
            route = (route_index, route_title)
            route_key = route_index
            if route_key in seen:
                continue
            seen.add(route_key)
            normalized.append(route)
        if not getattr(self, "home_search_mode", False):
            home_routes = [route for route in normalized if route[0] == self.home_page_index()]
            normalized = home_routes + [route for route in normalized if route[0] != self.home_page_index()]
        self.page_navigation_stack = normalized
        if active_route is not None:
            active_index = active_route[0]
            matching_positions = [
                position for position, route in enumerate(normalized)
                if route == active_route
            ]
            if not matching_positions:
                matching_positions = [
                position for position, (route_index, _title) in enumerate(normalized)
                if route_index == active_index
                ]
        else:
            matching_positions = []
        if matching_positions:
            self.active_navigation_position = matching_positions[0]
        else:
            self.active_navigation_position = max(0, len(normalized) - 1)

    def update_breadcrumb(self: "MainWindow", current_title: str = "") -> None:
        if not getattr(self, "breadcrumb_buttons", None):
            return
        self.normalize_navigation_routes()
        index = self.main_content_stack.currentIndex() if hasattr(self, "main_content_stack") else self.home_page_index()
        if index < 0:
            index = self.home_page_index()
        if not self.page_navigation_stack:
            self.page_navigation_stack = [(index, self.page_title_for_index(index))]
            self.active_navigation_position = 0
        elif not 0 <= self.active_navigation_position < len(self.page_navigation_stack):
            self.active_navigation_position = len(self.page_navigation_stack) - 1
        elif self.page_navigation_stack[self.active_navigation_position][0] != index:
            matching_positions = [
                position
                for position, (route_index, _title) in enumerate(self.page_navigation_stack)
                if route_index == index
            ]
            if matching_positions:
                self.active_navigation_position = matching_positions[-1]
            else:
                self.page_navigation_stack.append((index, self.page_title_for_index(index)))
                self.active_navigation_position = len(self.page_navigation_stack) - 1
        if current_title:
            self.page_navigation_stack[self.active_navigation_position] = (index, current_title)
        self.normalize_navigation_routes()
        menu_button = self.breadcrumb_buttons.get("menu")
        if menu_button:
            menu_button.setText("菜单")
            menu_button.setChecked(False)
        layout = getattr(self, "breadcrumb_route_layout", None)
        if layout is None:
            return
        while len(self.breadcrumb_route_buttons) < len(self.page_navigation_stack):
            separator = QLabel(">", self.main_header)
            separator.setObjectName("breadcrumbRouteSeparator")
            separator.setAlignment(Qt.AlignCenter)
            button = QPushButton(self.main_header)
            button.setObjectName("breadcrumbRouteButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, button=button: self.navigate_breadcrumb_route(
                    int(button.property("route_position") or 0)
                )
            )
            layout.addWidget(separator)
            layout.addWidget(button)
            self.breadcrumb_route_separators.append(separator)
            self.breadcrumb_route_buttons.append(button)
        for position, button in enumerate(self.breadcrumb_route_buttons):
            visible = position < len(self.page_navigation_stack)
            separator = self.breadcrumb_route_separators[position]
            button.setVisible(visible)
            separator.setVisible(visible)
            if not visible:
                continue
            _page_index, title = self.page_navigation_stack[position]
            is_current = position == self.active_navigation_position
            button.setProperty("route_position", position)
            button.setText(title)
            button.setChecked(is_current)
            button.setEnabled(not is_current)
            button.setCursor(Qt.ArrowCursor if is_current else Qt.PointingHandCursor)
            button.style().unpolish(button)
            button.style().polish(button)

    def schedule_breadcrumb_update(self: "MainWindow") -> None:
        """Coalesce route styling so a page change can paint before chrome updates."""
        if bool(getattr(self, "_breadcrumb_update_scheduled", False)):
            return
        self._breadcrumb_update_scheduled = True
        timer = getattr(self, "_breadcrumb_update_timer", None)
        if timer is None:
            timer = QTimer(self.main_content_stack)
            timer.setSingleShot(True)
            timer.timeout.connect(self.flush_scheduled_breadcrumb_update)
            self._breadcrumb_update_timer = timer
        timer.start(0)

    def flush_scheduled_breadcrumb_update(self: "MainWindow") -> None:
        self._breadcrumb_update_scheduled = False
        self.update_breadcrumb()

    def finish_page_activation(
        self: "MainWindow", generation: int, index: int
    ) -> None:
        if generation != int(getattr(self, "_page_switch_generation", 0)):
            return
        if self.main_content_stack.currentIndex() != index:
            return
        if index == self.history_page_index():
            self.refresh_history_table()

    def finish_page_theme_activation(
        self: "MainWindow", generation: int, index: int
    ) -> None:
        if generation != int(getattr(self, "_page_switch_generation", 0)):
            return
        if self.main_content_stack.currentIndex() != index:
            return
        if bool(getattr(self, "theme_dark", False)):
            self.apply_dark_to_widget(self.main_content_stack.currentWidget())

    def schedule_page_activation(
        self: "MainWindow", generation: int, index: int
    ) -> None:
        self._pending_page_activation = (generation, index)
        timer = getattr(self, "_page_activation_timer", None)
        if timer is None:
            timer = QTimer(self.main_content_stack)
            timer.setSingleShot(True)
            timer.timeout.connect(self.flush_page_activation)
            self._page_activation_timer = timer
        timer.start(16)

    def flush_page_activation(self: "MainWindow") -> None:
        pending = getattr(self, "_pending_page_activation", None)
        self._pending_page_activation = None
        if pending is not None:
            self.finish_page_activation(*pending)

    def schedule_page_theme_activation(
        self: "MainWindow", generation: int, index: int
    ) -> None:
        self._pending_page_theme_activation = (generation, index)
        timer = getattr(self, "_page_theme_activation_timer", None)
        if timer is None:
            timer = QTimer(self.main_content_stack)
            timer.setSingleShot(True)
            timer.timeout.connect(self.flush_page_theme_activation)
            self._page_theme_activation_timer = timer
        timer.start(0)

    def flush_page_theme_activation(self: "MainWindow") -> None:
        pending = getattr(self, "_pending_page_theme_activation", None)
        self._pending_page_theme_activation = None
        if pending is not None:
            self.finish_page_theme_activation(*pending)

    def navigate_breadcrumb_route(self: "MainWindow", position: int) -> None:
        if position < 0 or position >= len(self.page_navigation_stack):
            return
        index, title = self.page_navigation_stack[position]
        if index == self.home_page_index() and title == "首页":
            restore_home = getattr(self, "restore_home_before_detail_search", None)
            if callable(restore_home):
                restore_home()
        elif index == self.search_page_index() and title == "搜索":
            restore_search = getattr(self, "restore_detail_search_results", None)
            if callable(restore_search):
                restore_search()
        self.active_navigation_position = position
        self.switch_page(index, preserve_path=True, breadcrumb_title=title, route_position=position)
        if index == self.detail_page_index() and title == "漫画详情":
            restore_detail = getattr(self, "restore_current_detail_from_cache", None)
            if callable(restore_detail):
                restore_detail()

    def toggle_navigation_panel(self: "MainWindow") -> None:
        container = getattr(self, "navigation_container", None)
        if container is None:
            return
        previous_animation = getattr(self, "navigation_toggle_animation", None)
        if previous_animation is not None:
            previous_animation.stop()
        expanding = container.isHidden()
        if expanding:
            container.show()
            start_width, end_width = 0, NAVIGATION_PANEL_WIDTH
        else:
            start_width, end_width = max(0, container.width()), 0
        animation = QParallelAnimationGroup(self)
        for property_name in (b"minimumWidth", b"maximumWidth"):
            width_animation = QPropertyAnimation(container, property_name, animation)
            width_animation.setStartValue(start_width)
            width_animation.setEndValue(end_width)
            width_animation.setDuration(120)
            width_animation.setEasingCurve(QEasingCurve.InOutQuad)
            animation.addAnimation(width_animation)

        def finish_toggle() -> None:
            if expanding:
                container.setMinimumWidth(NAVIGATION_PANEL_WIDTH)
                container.setMaximumWidth(NAVIGATION_PANEL_WIDTH)
            else:
                container.hide()
                container.setMinimumWidth(0)
                container.setMaximumWidth(0)

        animation.finished.connect(finish_toggle)
        self.navigation_toggle_animation = animation
        animation.start()

    def switch_page(
        self: "MainWindow",
        index: int,
        preserve_path: bool = False,
        breadcrumb_title: str = "",
        route_position: Optional[int] = None,
    ) -> None:
        self.clear_album_selection()
        if not hasattr(self, "main_content_stack"):
            self._fade_in(self.app_page, 160)
            return
        if (
            index == self.home_page_index()
            and not preserve_path
            and bool(getattr(self, "category_rank_page_lock", False))
            and self.main_content_stack.currentIndex() == self.category_rank_page_index()
        ):
            self.schedule_breadcrumb_update()
            return
        index = max(0, min(index, self.main_content_stack.count() - 1))
        title = breadcrumb_title or self.page_title_for_index(index)
        if (
            not preserve_path
            and index == self.home_page_index()
            and not breadcrumb_title
            and any(route_index == index for route_index, _route_title in self.page_navigation_stack)
        ):
            preserve_path = True
        if preserve_path:
            if route_position is not None and 0 <= route_position < len(self.page_navigation_stack):
                self.active_navigation_position = route_position
                self.page_navigation_stack[route_position] = (index, title)
            else:
                matching_positions = [
                    position
                    for position, (route_index, route_title) in enumerate(self.page_navigation_stack)
                    if route_index == index and route_title == title
                ]
                if matching_positions:
                    self.active_navigation_position = matching_positions[-1]
                else:
                    self.page_navigation_stack.append((index, title))
                    self.active_navigation_position = len(self.page_navigation_stack) - 1
        else:
            self.page_navigation_stack = [(index, title)]
            self.active_navigation_position = 0
        if not preserve_path and index != self.detail_page_index():
            self.breadcrumb_detail_parent = ""
            self.breadcrumb_detail_parent_index = index
        page_changed = index != self.main_content_stack.currentIndex()
        self._page_switch_generation = int(
            getattr(self, "_page_switch_generation", 0)
        ) + 1
        switch_generation = self._page_switch_generation
        if page_changed:
            self.main_content_stack.setCurrentIndex(index)
        button = getattr(self, "nav_buttons", {}).get(index)
        if button:
            button.setChecked(True)
        if page_changed:
            if bool(getattr(self, "theme_dark", False)):
                self.schedule_page_theme_activation(switch_generation, index)
            self.schedule_page_activation(switch_generation, index)
        self.schedule_breadcrumb_update()

    def toggle_settings(self: "MainWindow") -> None:
        self.switch_page(self.settings_page_index())

    def open_history_dialog(self: "MainWindow") -> None:
        self.switch_page(self.history_page_index())
