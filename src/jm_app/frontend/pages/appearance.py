"""Application theme and compact navigation interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from .navigation import NAVIGATION_PANEL_WIDTH

if TYPE_CHECKING:
    from ..ui import MainWindow


COLLAPSED_NAVIGATION_WIDTH = 68

DARK_STYLE = """
QWidget, QFrame, QStackedWidget, QScrollArea, QAbstractScrollArea,
QListWidget, QListView, QTableWidget, QTabWidget::pane {
    background:#17191d; color:#e5e7eb; border-color:#343942;
}
QFrame#panel, QFrame#libraryWorkspace, QFrame#historyWorkspace,
QFrame#homeWorkspace, QFrame#navigationPanel, QFrame#settingsWorkspace,
QFrame#weeklyPanel, QFrame#localFavoritePage,
QFrame#profileTaskCard, QFrame#profileActivityCard,
QFrame#profileFavoriteCard, QFrame#profileHistoryCard,
QFrame#profileCommunityCard, QFrame#profileInboxCard {
    background:#202329; color:#e5e7eb; border-color:#363b45;
}
QWidget#navScrollContent, QScrollArea#navScroll { background:#202329; }
QLabel { color:#e5e7eb; background:transparent; }
QLabel#sectionTitle { color:#aeb6c2; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox,
QTableWidget, QListWidget, QListView {
    background:#191c21; color:#e5e7eb; border-color:#3b414c;
    selection-background-color:#8b4a18; selection-color:#ffffff;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color:#e8832f; background:#1d2026;
}
QPushButton, QToolButton {
    color:#dce1e8; background:#292d34; border:1px solid #414752;
}
QPushButton:hover, QToolButton:hover { background:#343943; border-color:#5b6370; }
QPushButton:checked { color:#ff9a4a; background:#3b2a20; border-color:#a95c24; }
QPushButton[navRole="item"] {
    color:#cbd1da; background:transparent; border:0;
    border-left:4px solid transparent;
}
QPushButton[navRole="item"]:hover { color:#ff9a4a; background:#2a2e35; }
QPushButton[navRole="item"]:checked {
    color:#ff9a4a; background:#3a2a20; border-left-color:#f07800;
}
QFrame#headerAccountMenu { background:#292d34; }
QFrame#headerAccountMenu:hover { background:#343943; }
QPushButton#profileAvatarButton {
    color:#ffffff; background:#3a414d; border:1px solid #505866;
}
QPushButton#profileAvatarButton[hasAvatar="true"] {
    background:transparent; border-color:#596270;
}
QFrame#accountLibraryCard, QFrame#albumCard, QFrame#localFavoriteCard,
QFrame#commentCard, QFrame#profileAlbumItem {
    background:#24272d; color:#e5e7eb; border-color:#3b414b;
}
QFrame#accountLibraryCard:hover, QFrame#albumCard:hover,
QFrame#localFavoriteCard:hover { background:#292d34; border-color:#d37831; }
QFrame#libraryWorkspace, QFrame#historyWorkspace,
QFrame#localFavoritePage { background:#17191d; }
QWidget#favoritesTab { background:#17191d; }
QFrame#favoriteToolbarDivider { background:#343942; }
QScrollArea#libraryCommentScroll,
QScrollArea#libraryCommentScroll > QWidget > QWidget {
    background:#191c21; border-color:#343942;
}
QComboBox#libraryFolderCombo, QComboBox#libraryFavoriteSortCombo,
QComboBox#localFavoriteFolderCombo, QComboBox#localFavoriteSortCombo,
QComboBox#localFavoriteDirectionCombo, QLineEdit#localFavoriteSearchEdit,
QSpinBox#localFavoritePageSpin {
    color:#e5e7eb; background:#191c21; border-color:#3b414c;
}
QSpinBox#localFavoritePageSpin::up-button {
    background:#24272d; border-left-color:#3b414c; border-bottom-color:#343942;
}
QSpinBox#localFavoritePageSpin::down-button {
    background:#24272d; border-left-color:#3b414c;
}
QSpinBox#localFavoritePageSpin::up-button:hover,
QSpinBox#localFavoritePageSpin::down-button:hover { background:#303640; }
QLineEdit#libraryNewFolderEdit {
    color:#e5e7eb; background:#24272d; border-color:#414752;
}
QLineEdit#libraryNewFolderEdit:hover { border-color:#586170; }
QLineEdit#libraryNewFolderEdit:focus { border-color:#5793ee; }
QPushButton#libraryAddFolderButton {
    color:#8db8ff; background:#202b3b; border-color:#416da8;
}
QPushButton#libraryAddFolderButton:hover {
    color:#ffffff; background:#3478f6; border-color:#3478f6;
}
QPushButton#libraryDeleteFolderButton {
    color:#ff9aa0; background:#382629; border-color:#713e43;
}
QPushButton#libraryDeleteFolderButton:hover {
    color:#ffffff; background:#d94349; border-color:#d94349;
}
QPushButton#libraryDeleteFolderButton:disabled {
    color:#6f7681; background:#22252a; border-color:#343942;
}
QFrame#localFavoriteBottomBar { background:#202329; border-color:#343942; }
QToolButton#localFavoriteFolderMenuButton,
QPushButton#localFavoriteImportButton,
QPushButton#localFavoriteBatchDownloadButton,
QPushButton#localFavoriteUpdateButton,
QPushButton#localFavoriteJumpButton {
    color:#8db8ff; background:#202b3b; border-color:#416da8;
}
QLabel#localFavoriteSearchLabel, QLabel#localFavoriteCountLabel,
QLabel#localFavoritePageLabel { color:#cbd1da; }
QFrame#myCommentsProfileCard, QFrame#commentCard {
    background:#24272d; border-color:#3b414b;
}
QFrame#commentCard:hover { background:#292d34; border-color:#5b6370; }
QLabel#myCommentsTitle, QLabel#myCommentsNameLabel,
QLabel[statValue="true"], QLabel#commentNameLabel,
QLabel#commentContentLabel { color:#e5e7eb; }
QLabel#myCommentsBioLabel, QLabel[statCaption="true"],
QLabel#commentIndexLabel, QLabel#commentDateLabel,
QLabel#commentIdLabel, QLabel#commentLikeLabel { color:#aeb6c2; }
QLineEdit#myCommentsSearchEdit, QComboBox#myCommentsSortCombo {
    color:#e5e7eb; background:#191c21; border-color:#3b414c;
}
QLabel#myCommentsAvatarLabel, QLabel#commentAvatarLabel,
QLabel#commentAlbumCoverLabel { background:#30343b; color:#aeb6c2; border-color:#414752; }
QPushButton#myCommentsEditProfileButton {
    color:#ff9a4a; background:#292d34; border-color:#a95c24;
}
QFrame#myCommentsDivider { background:#3b414b; }
QPushButton[commentFilter="true"] { color:#aeb6c2; background:transparent; }
QPushButton[commentFilter="true"]:checked { color:#ff9a4a; border-bottom-color:#f07800; }
QLabel#commentLevelLabel, QLabel#commentTitleLabel,
QLabel#commentReplyPreviewLabel { color:#c7d2e3; background:#30343b; }
QPushButton#commentAlbumButton, QPushButton#commentReplyButton {
    color:#cbd1da; background:transparent; border-color:transparent;
}
QFrame#downloadPanel { background:#17191d; }
QFrame#downloadWorkspace {
    background:#24272d; border-color:#3b414b;
}
QLabel#downloadPageTitle, QLabel#downloadEmptyTitle { color:#edf0f4; }
QLabel#downloadEmptyHint { color:#aeb6c2; }
QLabel#downloadHeaderIcon, QLabel#downloadEmptyIcon { background:#1d2b40; }
QProgressBar#downloadProgress {
    color:#e5e7eb; background:#191c21; border-color:#414752;
}
QProgressBar#downloadProgress::chunk { background:#3478f6; }
QPushButton#clearQueueButton, QPushButton#cancelDownloadsButton {
    color:#cbd1da; background:#292d34; border-color:#414752;
}
QPushButton#clearQueueButton:hover, QPushButton#cancelDownloadsButton:hover {
    color:#7bb0ff; background:#343943; border-color:#586170;
}
QPushButton#cancelDownloadsButton:disabled {
    color:#717784; background:#22252a; border-color:#343942;
}
QPushButton#startQueueButton {
    color:#ffffff; background:#3478f6; border-color:#3478f6;
}
QFrame#downloadDivider { background:#3b414b; }
QScrollArea#queueScroll, QWidget#queueCardsWidget,
QWidget#downloadQueuePage, QWidget#downloadEmptyPage { background:#24272d; }
QFrame#weeklyPanel { background:#17191d; }
QFrame#weeklyToolbar { background:#24272d; border-color:#3b414b; }
QLabel#weeklyPeriodIcon, QLabel#weeklyUpdateIcon { background:#3b2a20; }
QLabel#weeklyPeriodCaption { color:#f0f2f5; }
QLabel#weeklyUpdateHint { color:#c0c7d1; }
QComboBox#weeklyPeriodCombo {
    color:#f0f2f5; background:#191c21; border-color:#a95c24;
}
QComboBox#weeklyPeriodCombo:hover, QComboBox#weeklyPeriodCombo:focus {
    color:#ffffff; background:#202329; border-color:#f07800;
}
QComboBox#weeklyPeriodCombo QAbstractItemView {
    color:#e5e7eb; background:#202329; border-color:#414752;
    selection-background-color:#3b2a20; selection-color:#ff9a4a;
}
QPushButton#weeklyRefreshButton {
    color:#ffffff; background:#f07800; border-color:#f07800;
}
QPushButton#weeklyRefreshButton:hover { background:#dc6900; border-color:#dc6900; }
QTabWidget#weeklyTabs::pane { border-top-color:#343942; background:#17191d; }
QTabWidget#weeklyTabs QTabBar::tab { color:#aeb6c2; background:transparent; }
QTabWidget#weeklyTabs QTabBar::tab:hover { color:#ff9a4a; background:#292d34; }
QTabWidget#weeklyTabs QTabBar::tab:selected {
    color:#ff9a4a; background:transparent; border-bottom-color:#f07800;
}
QTabBar::tab { color:#aeb6c2; background:#202329; }
QTabBar::tab:selected { color:#ff9745; border-bottom:2px solid #f07800; }
QHeaderView::section { background:#292d34; color:#dce1e8; border-color:#414752; }
QMenu { background:#24272d; color:#e5e7eb; border:1px solid #414752; }
QMenu::item:selected { background:#3a2a20; color:#ff9a4a; }
QScrollBar:vertical { background:#202329; border:0; }
QScrollBar::handle:vertical { background:#737983; }
QScrollBar::handle:vertical:hover { background:#969ca5; }
QToolTip { color:#f3f4f6; background:#30343b; border:1px solid #555c68; }
"""


class AppearancePageMixin:
    def setup_appearance_controls(self: "MainWindow", panel: QWidget) -> None:
        self.nav_dark_mode_button = panel.findChild(QPushButton, "navDarkModeButton")
        self.nav_collapse_button = panel.findChild(QPushButton, "navCollapseButton")
        if self.nav_dark_mode_button is None or self.nav_collapse_button is None:
            raise RuntimeError("Navigation form is missing appearance controls")
        for button in (self.nav_dark_mode_button, self.nav_collapse_button):
            button.setProperty("navRole", "item")
        self.nav_dark_mode_button.clicked.connect(self.toggle_dark_mode)
        self.nav_collapse_button.clicked.connect(self.toggle_navigation_panel)
        self._navigation_panel_widget = panel
        self.bind_library_theme_controls()

    def bind_library_theme_controls(self: "MainWindow") -> None:
        if bool(getattr(self, "_library_theme_controls_bound", False)):
            return
        tabs = getattr(self, "library_tabs", None)
        if tabs is None:
            return
        tabs.currentChanged.connect(self.sync_visible_user_theme)
        self._library_theme_controls_bound = True

    def apply_saved_appearance(self: "MainWindow") -> None:
        self._themed_root_styles = {}
        self.theme_dark = False
        self.navigation_collapsed = False
        if bool(self.settings_cache.get("sidebar_collapsed", False)):
            self.set_navigation_collapsed(True, animate=False)
        if bool(self.settings_cache.get("theme_dark", False)):
            self.set_dark_mode(True, persist=False)

    def toggle_dark_mode(self: "MainWindow", checked: bool = False) -> None:
        enabled = bool(checked)
        self._pending_theme_dark = enabled
        self._sync_theme_button(enabled)
        if bool(getattr(self, "_theme_change_scheduled", False)):
            return
        self._theme_change_scheduled = True
        button = getattr(self, "nav_dark_mode_button", None)
        if button is not None:
            button.setEnabled(False)
        QTimer.singleShot(0, self._commit_pending_theme_change)

    def _commit_pending_theme_change(self: "MainWindow") -> None:
        self._theme_change_scheduled = False
        self.set_dark_mode(
            bool(getattr(self, "_pending_theme_dark", False)), persist=True
        )
        button = getattr(self, "nav_dark_mode_button", None)
        if button is not None:
            button.setEnabled(True)

    def _sync_theme_button(self: "MainWindow", enabled: bool) -> None:
        button = getattr(self, "nav_dark_mode_button", None)
        if button is None:
            return
        button.setChecked(bool(enabled))
        label = "浅色模式" if enabled else "深色模式"
        button.setProperty("expandedText", label)
        button.setText(
            "" if bool(getattr(self, "navigation_collapsed", False)) else label
        )

    def set_dark_mode(self: "MainWindow", enabled: bool, persist: bool = True) -> None:
        enabled = bool(enabled)
        self._sync_theme_button(enabled)
        if enabled == bool(getattr(self, "theme_dark", False)):
            return
        self.theme_dark = enabled
        visible_roots = self._visible_theme_roots()
        stored_roots = [
            entry[0]
            for entry in getattr(self, "_themed_root_styles", {}).values()
        ]
        update_roots = visible_roots if enabled else stored_roots
        for root in update_roots:
            try:
                root.setUpdatesEnabled(False)
            except RuntimeError:
                pass
        try:
            if enabled:
                self._set_theme_root_background(True)
                for root in visible_roots:
                    self.apply_dark_to_widget(root)
            else:
                for widget, style, palette, auto_fill in list(
                    getattr(self, "_themed_root_styles", {}).values()
                ):
                    try:
                        widget.setStyleSheet(style)
                        widget.setPalette(palette)
                        widget.setAutoFillBackground(auto_fill)
                    except RuntimeError:
                        pass
                self._themed_root_styles.clear()
                self._set_theme_root_background(False)
        finally:
            for root in update_roots:
                try:
                    root.setUpdatesEnabled(True)
                    root.update()
                except RuntimeError:
                    pass
        corner_tools = getattr(self, "home_corner_tools", None)
        if corner_tools is not None:
            corner_tools.set_dark_mode(enabled)
        self.schedule_theme_card_refresh()
        refresh_download_cards = getattr(self, "refresh_download_card_theme", None)
        if callable(refresh_download_cards):
            refresh_download_cards()
        sync_favorite_toolbar = getattr(
            self, "sync_library_favorite_toolbar_theme", None
        )
        if callable(sync_favorite_toolbar):
            sync_favorite_toolbar()
        sync_local_favorite = getattr(self, "sync_local_favorite_theme", None)
        if callable(sync_local_favorite):
            sync_local_favorite()
        sync_local_download = getattr(self, "sync_local_download_theme", None)
        if callable(sync_local_download):
            sync_local_download()
        if persist:
            self.settings_cache["theme_dark"] = enabled
            self.schedule_settings_save()

    def _visible_theme_roots(self: "MainWindow") -> list[QWidget]:
        roots = [
            getattr(self, "_navigation_panel_widget", None),
            getattr(self, "main_header", None),
        ]
        stack = getattr(self, "main_content_stack", None)
        if stack is not None:
            roots.append(stack.currentWidget())
            if stack.currentIndex() == self.library_page_index():
                tabs = getattr(self, "library_tabs", None)
                tab = tabs.currentWidget() if tabs is not None else None
                if tab is not None and tab.objectName() == "commentsTab":
                    roots.append(getattr(self, "my_comments_header", None))
                elif tab is not None and tab.objectName() == "localTab":
                    roots.append(getattr(self, "local_favorite_page", None))
        return [root for root in roots if root is not None]

    def sync_visible_user_theme(self: "MainWindow", _index: int = -1) -> None:
        if not bool(getattr(self, "theme_dark", False)):
            return
        for root in self._visible_theme_roots():
            self.apply_dark_to_widget(root)

    def schedule_theme_card_refresh(self: "MainWindow") -> None:
        """Recolor cards in short event-loop batches so theme toggles stay responsive."""
        generation = int(getattr(self, "_theme_card_generation", 0)) + 1
        self._theme_card_generation = generation
        queue = [
            ("album", album_id, card)
            for album_id, card in list(getattr(self, "card_by_id", {}).items())
        ]
        app_page = getattr(self, "app_page", None)
        if app_page is not None:
            queue.extend(
                ("library", "", card)
                for card in app_page.findChildren(QFrame, "accountLibraryCard")
            )
        self._theme_card_queue = queue
        QTimer.singleShot(0, lambda: self._refresh_theme_card_batch(generation))

    def _refresh_theme_card_batch(self: "MainWindow", generation: int) -> None:
        if generation != int(getattr(self, "_theme_card_generation", 0)):
            return
        queue = getattr(self, "_theme_card_queue", [])
        batch = queue[:20]
        del queue[: len(batch)]
        for kind, album_id, card in batch:
            if kind == "album":
                apply_card = getattr(self, "apply_album_card_theme", None)
                if callable(apply_card):
                    apply_card(album_id, card)
            else:
                apply_card = getattr(self, "apply_library_feed_card_theme", None)
                if callable(apply_card):
                    apply_card(card)
        if queue:
            QTimer.singleShot(0, lambda: self._refresh_theme_card_batch(generation))

    @staticmethod
    def _dark_palette(source: QPalette) -> QPalette:
        palette = QPalette(source)
        colors = {
            QPalette.ColorRole.Window: "#17191d",
            QPalette.ColorRole.WindowText: "#e5e7eb",
            QPalette.ColorRole.Base: "#191c21",
            QPalette.ColorRole.AlternateBase: "#202329",
            QPalette.ColorRole.Text: "#e5e7eb",
            QPalette.ColorRole.Button: "#292d34",
            QPalette.ColorRole.ButtonText: "#dce1e8",
            QPalette.ColorRole.Highlight: "#a95c24",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.ToolTipBase: "#30343b",
            QPalette.ColorRole.ToolTipText: "#f3f4f6",
        }
        for role, color in colors.items():
            palette.setColor(role, QColor(color))
        return palette

    def _set_theme_root_background(self: "MainWindow", enabled: bool) -> None:
        for widget in (
            getattr(self, "app_page", None),
            getattr(self, "dashboard_content_column", None),
        ):
            if widget is None:
                continue
            widget.setProperty("darkTheme", bool(enabled))
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def apply_dark_to_widget(self: "MainWindow", root: QWidget) -> None:
        """Apply colors to one visible subtree without touching its geometry."""
        if not bool(getattr(self, "theme_dark", False)) or root is None:
            return
        app_page = getattr(self, "app_page", None)
        ancestor = root
        belongs_to_app = False
        while ancestor is not None:
            if ancestor is app_page:
                belongs_to_app = True
                break
            ancestor = ancestor.parentWidget()
        if not belongs_to_app:
            return
        styles = getattr(self, "_themed_root_styles", None)
        if styles is None:
            self._themed_root_styles = {}
            styles = self._themed_root_styles
        key = id(root)
        if key in styles:
            return
        try:
            styles[key] = (
                root,
                root.styleSheet(),
                QPalette(root.palette()),
                root.autoFillBackground(),
            )
            root.setPalette(self._dark_palette(root.palette()))
            root.setAutoFillBackground(True)
            root.setStyleSheet(root.styleSheet() + "\n" + DARK_STYLE)
        except RuntimeError:
            return

    def toggle_navigation_panel(self: "MainWindow") -> None:
        self.set_navigation_collapsed(
            not bool(getattr(self, "navigation_collapsed", False)), animate=True
        )

    def set_navigation_collapsed(
        self: "MainWindow", collapsed: bool, animate: bool = True
    ) -> None:
        container = getattr(self, "navigation_container", None)
        panel = getattr(self, "_navigation_panel_widget", None)
        if container is None or panel is None:
            return
        collapsed = bool(collapsed)
        self.navigation_collapsed = collapsed
        target = COLLAPSED_NAVIGATION_WIDTH if collapsed else NAVIGATION_PANEL_WIDTH
        for label_name in (
            "navNavigationSectionIcon", "navNavigationSectionLabel",
            "navUserSectionIcon", "navUserSectionLabel",
            "navSupportSectionIcon", "navSupportSectionLabel",
            "headerUserLabel", "headerUserRoleLabel",
        ):
            label = panel.findChild(QLabel, label_name)
            if label is not None:
                label.setVisible(not collapsed)
        arrow = panel.findChild(QPushButton, "headerAccountArrowButton")
        if arrow is not None:
            arrow.setVisible(not collapsed)
        for button in panel.findChildren(QPushButton):
            if button.property("navRole") != "item":
                continue
            original = button.property("expandedText")
            if not original:
                original = button.text()
                button.setProperty("expandedText", original)
            button.setToolTip(str(original) if collapsed else "")
            button.setText("" if collapsed else str(original))
        panel.setProperty("collapsed", collapsed)
        panel.style().unpolish(panel)
        panel.style().polish(panel)
        old_animation = getattr(self, "navigation_toggle_animation", None)
        if old_animation is not None:
            old_animation.stop()
        if animate:
            animation = QParallelAnimationGroup(self)
            start = max(COLLAPSED_NAVIGATION_WIDTH, container.width())
            for target_widget in (container, panel):
                for name in (b"minimumWidth", b"maximumWidth"):
                    item = QPropertyAnimation(target_widget, name, animation)
                    item.setStartValue(start)
                    item.setEndValue(target)
                    item.setDuration(150)
                    item.setEasingCurve(QEasingCurve.InOutQuad)
                    animation.addAnimation(item)
            self.navigation_toggle_animation = animation
            animation.start()
        else:
            container.setMinimumWidth(target)
            container.setMaximumWidth(target)
            panel.setMinimumWidth(target)
            panel.setMaximumWidth(target)
        if hasattr(self, "settings_cache"):
            self.settings_cache["sidebar_collapsed"] = collapsed
            QTimer.singleShot(0, self.schedule_settings_save)
