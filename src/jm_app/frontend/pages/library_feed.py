"""Home-style comic grids for account and local library routes."""

from __future__ import annotations

import copy
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import QPoint, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...backend.models import AlbumMeta
from ...backend.runtime_paths import resource_dir
from .empty_state import build_library_empty_state
from ..feed_scroll_bar import (
    FEED_CARD_HEIGHT,
    FEED_CARD_WIDTH,
    FEED_GRID_ROW_HEIGHT,
    FEED_MIN_GAP,
    FeedListWidget,
    FeedScrollBar,
)

if TYPE_CHECKING:
    from ..ui import MainWindow


ACCOUNT_FEED_RENDER_BATCH = 2
ACCOUNT_FEED_RENDER_INTERVAL_MS = 6


def _tinted_library_icon(icon: QIcon, color: str, size: int = 18) -> QIcon:
    source = icon.pixmap(size, size)
    pixmap = QPixmap(source.size())
    pixmap.setDevicePixelRatio(source.devicePixelRatio())
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return QIcon(pixmap)


class FavoriteToolbarFrame(QFrame):
    """Keep favorite commands stable, wrapping only when space is constrained."""

    WIDE_MIN_WIDTH = 720

    def __init__(self, controls: list[QWidget], parent: QWidget):
        super().__init__(parent)
        self.setObjectName("favoriteToolbarSurface")
        self.controls = controls
        self._wide_layout: Optional[bool] = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(4, 6, 4, 10)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        for control in controls:
            control.setParent(self)
        self.relayout_controls()

    def relayout_controls(self) -> None:
        wide = self.width() >= self.WIDE_MIN_WIDTH
        if wide == self._wide_layout:
            return
        for control in self.controls:
            self.grid.removeWidget(control)
        for column in range(6):
            self.grid.setColumnStretch(column, 0)

        folder, sort, name_edit, add_button, delete_button = self.controls
        if wide:
            self.grid.addWidget(folder, 0, 0)
            self.grid.addWidget(sort, 0, 1)
            self.grid.setColumnStretch(2, 1)
            self.grid.addWidget(name_edit, 0, 3)
            self.grid.addWidget(add_button, 0, 4)
            self.grid.addWidget(delete_button, 0, 5)
            self.setFixedHeight(58)
        else:
            self.grid.addWidget(folder, 0, 0)
            self.grid.addWidget(sort, 0, 1)
            self.grid.setColumnStretch(2, 1)
            self.grid.addWidget(name_edit, 1, 0, 1, 3)
            self.grid.addWidget(add_button, 1, 3)
            self.grid.addWidget(delete_button, 1, 4)
            self.setFixedHeight(108)
        self._wide_layout = wide

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.relayout_controls()


class LibraryFeedPageMixin:
    """Render library data with the same geometry used by the home feed."""

    def apply_library_visual_system(self: "MainWindow", panel: QFrame) -> None:
        """Apply the shared account-library hierarchy after Designer loading."""
        panel.setObjectName("libraryWorkspace")
        root_layout = panel.layout()
        if root_layout is not None:
            root_layout.setContentsMargins(18, 14, 18, 16)
            root_layout.setSpacing(10)

        self.library_tabs.setDocumentMode(True)
        # Hidden tool tabs have very wide form rows. Ignore their aggregate
        # size hint so account routes fit the current content viewport.
        self.library_tabs.setMinimumWidth(0)
        self.library_tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        for index in range(self.library_tabs.count()):
            page = self.library_tabs.widget(index)
            page_layout = page.layout() if page is not None else None
            if page_layout is not None:
                page_layout.setContentsMargins(0, 6, 0, 0)
                page_layout.setSpacing(10)

        local_note = panel.findChild(QLabel, "localNote")
        if local_note is not None:
            local_note.hide()
        local_history_button = panel.findChild(QPushButton, "localOpenHistoryButton")
        if local_history_button is not None:
            local_history_button.hide()
        favorite_refresh_button = panel.findChild(
            QPushButton, "libraryFavoritesRefreshButton"
        )
        if favorite_refresh_button is not None:
            favorite_refresh_button.hide()
        favorites_tab = panel.findChild(QWidget, "favoritesTab")
        favorites_layout = favorites_tab.layout() if favorites_tab is not None else None
        if favorites_layout is not None and panel.findChild(QFrame, "favoriteToolbarDivider") is None:
            divider = QFrame(favorites_tab)
            divider.setObjectName("favoriteToolbarDivider")
            divider.setFixedHeight(1)
            favorites_layout.insertWidget(1, divider)
        remote_history_refresh_button = panel.findChild(
            QPushButton, "libraryRemoteHistoryRefreshButton"
        )
        if remote_history_refresh_button is not None:
            remote_history_refresh_button.hide()
        for layout_name in ("remoteHistoryToolbar", "remoteHistoryPager"):
            layout = panel.findChild(QHBoxLayout, layout_name)
            if layout is None:
                continue
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            for index in range(layout.count()):
                widget = layout.itemAt(index).widget()
                if widget is not None:
                    widget.hide()

        primary_buttons = (
            "libraryRemoteHistoryRefreshButton",
            "libraryCommentsRefreshButton",
            "localCollectionAddAlbumButton",
        )
        for name in primary_buttons:
            button = panel.findChild(QPushButton, name)
            if button is not None:
                button.setProperty("libraryRole", "primary")
                button.setMinimumHeight(34)

        compact_commands = {
            "libraryRemoteHistoryRefreshButton": ("同步", "同步云端阅读记录"),
            "libraryCommentsRefreshButton": ("刷新", "刷新我的评论"),
            "localCollectionAddAlbumButton": ("加入收藏", "将漫画加入当前本地收藏夹"),
            "localImportDirectoryButton": ("导入目录", "导入一个本地漫画目录"),
            "localImportBatchDirectoryButton": ("批量导入", "批量导入目录中的漫画"),
            "localImportArchivesButton": ("导入 ZIP/PDF", "导入漫画压缩包或 PDF"),
            "localScanButton": ("扫描本地", "扫描本地漫画库"),
        }
        for name, (text, tooltip) in compact_commands.items():
            button = panel.findChild(QPushButton, name)
            if button is not None:
                button.setText(text)
                button.setToolTip(tooltip)

        secondary_buttons = (
            "libraryAddFolderButton",
            "localCollectionAddButton",
            "localImportDirectoryButton",
            "localImportBatchDirectoryButton",
            "localImportArchivesButton",
            "localScanButton",
        )
        for name in secondary_buttons:
            button = panel.findChild(QPushButton, name)
            if button is not None:
                button.setProperty("libraryRole", "secondary")
                button.setMinimumHeight(34)

        danger_buttons = ("libraryDeleteFolderButton", "localCollectionRemoveButton")
        for name in danger_buttons:
            button = panel.findChild(QPushButton, name)
            if button is not None:
                button.setProperty("libraryRole", "danger")
                button.setMinimumHeight(34)

        refresh_icon = self.style().standardIcon(QStyle.SP_BrowserReload)
        for name in (
            "libraryRemoteHistoryRefreshButton",
            "libraryCommentsRefreshButton",
            "localScanButton",
        ):
            button = panel.findChild(QPushButton, name)
            if button is not None:
                button.setIcon(refresh_icon)

        pager_names = (
            ("libraryCommentPreviousButton", QStyle.SP_ArrowLeft, "上一页"),
            ("libraryCommentNextButton", QStyle.SP_ArrowRight, "下一页"),
        )
        for name, icon_type, tooltip in pager_names:
            button = panel.findChild(QPushButton, name)
            if button is None:
                continue
            button.setProperty("libraryRole", "pager")
            button.setIcon(self.style().standardIcon(icon_type))
            button.setText("")
            button.setToolTip(tooltip)
            button.setFixedSize(34, 32)

        for control in panel.findChildren(QPushButton):
            control.setCursor(Qt.PointingHandCursor)
        for control in (
            self.library_folder_combo,
            self.library_favorite_sort_combo,
            self.local_collection_combo,
        ):
            control.setMinimumHeight(34)
        self.library_folder_combo.setMinimumHeight(42)
        self.library_favorite_sort_combo.setMinimumHeight(42)
        for combo in (self.library_folder_combo, self.library_favorite_sort_combo):
            combo.setCursor(Qt.PointingHandCursor)
            combo.setIconSize(QSize(18, 18))
            combo.view().setSpacing(2)
        self.library_folder_combo.setMinimumWidth(154)
        self.library_folder_combo.setMaximumWidth(240)
        self.library_favorite_sort_combo.setMinimumWidth(134)
        self.library_favorite_sort_combo.setMaximumWidth(190)
        self.local_collection_combo.setMinimumWidth(150)
        self.library_new_folder_edit.setMinimumWidth(124)
        self.library_new_folder_edit.setMaximumWidth(260)
        self.library_new_folder_edit.setMinimumHeight(42)
        self.library_new_folder_edit.setClearButtonEnabled(True)
        self.local_collection_name_edit.setMaximumWidth(210)
        self.local_collection_album_edit.setMaximumWidth(300)
        self.library_comment_album_edit.setMaximumWidth(240)
        self.library_comment_album_edit.setPlaceholderText("按漫画 ID 筛选")
        self.library_comment_input.setMinimumHeight(38)
        self.library_comment_reply_edit.setMinimumHeight(38)

        icon_dir = resource_dir() / "nav_icons"
        self.library_favorite_folder_icon = _tinted_library_icon(
            QIcon(str(icon_dir / "line_folder.svg")), "#3478f6", 18
        )
        self.library_favorite_sort_icon = _tinted_library_icon(
            QIcon(str(icon_dir / "line_history.svg")), "#3478f6", 18
        )
        if not bool(self.library_new_folder_edit.property("favoriteSearchIconAdded")):
            self.library_new_folder_edit.addAction(
                _tinted_library_icon(
                    QIcon(str(icon_dir / "line_search.svg")), "#8794a7", 18
                ),
                QLineEdit.ActionPosition.LeadingPosition,
            )
            self.library_new_folder_edit.setProperty("favoriteSearchIconAdded", True)

        self.library_add_folder_button = panel.findChild(
            QPushButton, "libraryAddFolderButton"
        )
        self.library_delete_folder_button = panel.findChild(
            QPushButton, "libraryDeleteFolderButton"
        )
        if self.library_add_folder_button is not None:
            self.library_add_folder_button.setIcon(
                _tinted_library_icon(
                    QIcon(str(icon_dir / "line_folder.svg")),
                    "#3478f6",
                    18,
                )
            )
            self.library_add_folder_button.setIconSize(QSize(18, 18))
            self.library_add_folder_button.setMinimumSize(80, 42)
            self.library_add_folder_button.setToolTip("新建收藏夹")
        if self.library_delete_folder_button is not None:
            self.library_delete_folder_button.setIcon(
                _tinted_library_icon(
                    self.style().standardIcon(QStyle.SP_TrashIcon), "#e5484d", 18
                )
            )
            self.library_delete_folder_button.setIconSize(QSize(18, 18))
            self.library_delete_folder_button.setMinimumSize(110, 42)
            self.library_delete_folder_button.setToolTip("删除当前收藏夹")
        self.library_favorite_toolbar = self.install_library_favorite_toolbar(panel)
        self.library_folder_combo.currentIndexChanged.connect(
            self.sync_library_favorite_toolbar_state
        )
        self.sync_library_favorite_toolbar_icons()
        self.sync_library_favorite_toolbar_state()
        self.sync_library_favorite_toolbar_theme()

        panel.setStyleSheet(
            """
            QFrame#libraryWorkspace { background:#f7f8fa; border:0; }
            QWidget#favoritesTab { background:#f8fafc; }
            QFrame#favoriteToolbarSurface { background:transparent; border:0; }
            QFrame#favoriteToolbarDivider { background:#e6ebf2; border:0; }
            QLabel#libraryPageTitle { color:#18212f; font-size:22px; font-weight:900; }
            QLabel#libraryStatusLabel {
                color:#0f766e; background:#eaf6f3; border:1px solid #cce9e2;
                border-radius:6px; padding:3px 10px; font-size:11px; font-weight:800;
            }
            QTabWidget#libraryTabs::pane { border:0; background:transparent; }
            QTabWidget#libraryTabs > QWidget { background:transparent; }
            QListWidget#libraryFavoriteFeed, QListWidget#libraryRemoteHistoryFeed,
            QListWidget#libraryLocalFavoriteFeed {
                background:transparent; border:0; outline:0; padding:0;
            }
            QScrollArea#libraryCommentScroll { background:#ffffff; border:1px solid #e2e6ec; border-radius:6px; }
            QScrollArea#libraryCommentScroll[personalComments="true"] { background:transparent; border:0; border-radius:0; }
            QScrollArea#libraryCommentScroll > QWidget > QWidget { background:#ffffff; }
            QScrollArea#libraryCommentScroll[personalComments="true"] > QWidget > QWidget { background:transparent; }
            QLineEdit, QComboBox {
                min-height:32px; border:1px solid #d8dee7; border-radius:6px;
                background:#ffffff; color:#263244; padding:0 9px;
            }
            QLineEdit:focus, QComboBox:focus { border-color:#f28c28; }
            QComboBox#libraryFolderCombo, QComboBox#libraryFavoriteSortCombo {
                min-height:40px; color:#1f2f46; background:#ffffff;
                border:1px solid #d8e1ed; border-radius:8px;
                padding:0 34px 0 10px; font-size:13px; font-weight:700;
            }
            QComboBox#libraryFolderCombo:hover, QComboBox#libraryFavoriteSortCombo:hover {
                border-color:#9bbdff; background:#fbfdff;
            }
            QComboBox#libraryFolderCombo:focus, QComboBox#libraryFavoriteSortCombo:focus {
                border:1px solid #3478f6;
            }
            QComboBox#libraryFolderCombo::drop-down,
            QComboBox#libraryFavoriteSortCombo::drop-down {
                subcontrol-origin:padding; subcontrol-position:top right;
                width:30px; border:0; background:transparent;
            }
            QComboBox#libraryFolderCombo::drop-down:hover,
            QComboBox#libraryFavoriteSortCombo::drop-down:hover { background:#f1f5fb; }
            QLineEdit#libraryNewFolderEdit {
                min-height:40px; color:#243143; background:#ffffff;
                border:1px solid #d8e1ed; border-radius:8px;
                padding:0 10px 0 4px; font-size:13px;
            }
            QLineEdit#libraryNewFolderEdit:hover { border-color:#b8c8dd; }
            QLineEdit#libraryNewFolderEdit:focus { border:1px solid #3478f6; }
            QPushButton#libraryAddFolderButton {
                min-height:40px; color:#2468df; background:#f7faff;
                border:1px solid #a9c6ff; border-radius:8px;
                padding:0 14px; font-size:13px; font-weight:800;
            }
            QPushButton#libraryAddFolderButton:hover {
                color:#ffffff; background:#3478f6; border-color:#3478f6;
            }
            QPushButton#libraryDeleteFolderButton {
                min-height:40px; color:#dc3439; background:#fffafa;
                border:1px solid #f1c5c7; border-radius:8px;
                padding:0 14px; font-size:13px; font-weight:800;
            }
            QPushButton#libraryDeleteFolderButton:hover {
                color:#ffffff; background:#e5484d; border-color:#e5484d;
            }
            QPushButton#libraryDeleteFolderButton:disabled {
                color:#aab3c0; background:#f3f5f8; border-color:#e2e6ec;
            }
            QCheckBox { color:#526173; spacing:7px; }
            QPushButton[libraryRole="primary"] {
                color:#ffffff; background:#e87517; border:1px solid #e87517;
                border-radius:6px; padding:5px 12px; font-weight:800;
            }
            QPushButton[libraryRole="primary"]:hover { background:#cf6410; border-color:#cf6410; }
            QPushButton[libraryRole="secondary"] {
                color:#344256; background:#ffffff; border:1px solid #d5dce6;
                border-radius:6px; padding:5px 11px; font-weight:700;
            }
            QPushButton[libraryRole="secondary"]:hover { background:#f0f3f6; border-color:#bcc6d3; }
            QPushButton[libraryRole="danger"] {
                color:#b42318; background:transparent; border:1px solid transparent;
                border-radius:6px; padding:5px 9px; font-weight:700;
            }
            QPushButton[libraryRole="danger"]:hover { background:#fff0ee; border-color:#f4c7c2; }
            QPushButton[libraryRole="pager"] {
                background:#ffffff; border:1px solid #d8dee7; border-radius:6px; padding:5px;
            }
            QPushButton[libraryRole="pager"]:hover { background:#eef1f5; border-color:#bfc8d4; }
            QPushButton[libraryRole="pager"]:disabled { background:#f1f3f5; border-color:#e3e7ec; }
            QLabel#libraryCommentContextLabel { color:#526173; font-weight:700; }
            """
        )

    def install_library_favorite_toolbar(
        self: "MainWindow", panel: QFrame
    ) -> Optional[FavoriteToolbarFrame]:
        favorites_tab = panel.findChild(QWidget, "favoritesTab")
        page_layout = favorites_tab.layout() if favorites_tab is not None else None
        old_toolbar = panel.findChild(QHBoxLayout, "favoriteToolbar")
        if favorites_tab is None or page_layout is None or old_toolbar is None:
            return None

        layout_index = -1
        for index in range(page_layout.count()):
            if page_layout.itemAt(index).layout() is old_toolbar:
                layout_index = index
                break
        if layout_index < 0:
            return None

        controls = [
            self.library_folder_combo,
            self.library_favorite_sort_combo,
            self.library_new_folder_edit,
            self.library_add_folder_button,
            self.library_delete_folder_button,
        ]
        if any(control is None for control in controls):
            return None

        page_layout.takeAt(layout_index)
        while old_toolbar.count():
            item = old_toolbar.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in controls:
                widget.hide()
        toolbar = FavoriteToolbarFrame(controls, favorites_tab)
        page_layout.insertWidget(layout_index, toolbar)
        old_toolbar.deleteLater()
        return toolbar

    def sync_library_favorite_toolbar_icons(self: "MainWindow") -> None:
        folder_icon = getattr(self, "library_favorite_folder_icon", QIcon())
        sort_icon = getattr(self, "library_favorite_sort_icon", QIcon())
        for combo, icon in (
            (getattr(self, "library_folder_combo", None), folder_icon),
            (getattr(self, "library_favorite_sort_combo", None), sort_icon),
        ):
            if combo is None or icon.isNull():
                continue
            for index in range(combo.count()):
                combo.setItemIcon(index, icon)

    def sync_library_favorite_toolbar_state(self: "MainWindow", _index: int = -1) -> None:
        combo = getattr(self, "library_folder_combo", None)
        delete_button = getattr(self, "library_delete_folder_button", None)
        if combo is None or delete_button is None:
            return
        delete_button.setEnabled(str(combo.currentData() or "0") != "0")

    def sync_library_favorite_toolbar_theme(self: "MainWindow") -> None:
        dark = bool(getattr(self, "theme_dark", False))
        if dark:
            popup_style = (
                "QAbstractItemView{background:#24272d;border:1px solid #414752;"
                "border-radius:6px;padding:5px;outline:0;color:#e5e7eb;}"
                "QAbstractItemView::item{min-height:32px;padding:3px 9px;border-radius:4px;}"
                "QAbstractItemView::item:hover{background:#303640;}"
                "QAbstractItemView::item:selected{background:#1d365c;color:#8db8ff;}"
            )
        else:
            popup_style = (
                "QAbstractItemView{background:#ffffff;border:1px solid #d8e1ed;"
                "border-radius:6px;padding:5px;outline:0;color:#263244;}"
                "QAbstractItemView::item{min-height:32px;padding:3px 9px;border-radius:4px;}"
                "QAbstractItemView::item:hover{background:#f2f6fc;}"
                "QAbstractItemView::item:selected{background:#eaf2ff;color:#245fc4;}"
            )
        for combo in (
            getattr(self, "library_folder_combo", None),
            getattr(self, "library_favorite_sort_combo", None),
        ):
            if combo is not None:
                combo.view().setStyleSheet(popup_style)

    def apply_history_visual_system(self: "MainWindow", panel: QFrame) -> None:
        panel.setObjectName("historyWorkspace")
        root_layout = panel.layout()
        if root_layout is not None:
            root_layout.setContentsMargins(18, 14, 18, 16)
            root_layout.setSpacing(10)
        panel.setStyleSheet(
            """
            QFrame#historyWorkspace { background:#f7f8fa; border:0; }
            QListWidget#localHistoryFeed { background:transparent; border:0; outline:0; padding:0; }
            """
        )

    def _replace_scroll_with_library_feed(
        self: "MainWindow", old_scroll: QScrollArea, object_name: str
    ) -> FeedListWidget:
        parent = old_scroll.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        layout_index = parent_layout.indexOf(old_scroll) if parent_layout is not None else -1
        grid_position = None
        if isinstance(parent_layout, QGridLayout) and layout_index >= 0:
            grid_position = parent_layout.getItemPosition(layout_index)

        feed = FeedListWidget(parent)
        feed.setObjectName(object_name)
        feed.setViewMode(QListView.IconMode)
        feed.setFlow(QListView.LeftToRight)
        feed.setWrapping(True)
        feed.setResizeMode(QListView.Adjust)
        feed.setMovement(QListView.Static)
        feed.setSelectionMode(QAbstractItemView.NoSelection)
        feed.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        feed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        feed.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        feed.setVerticalScrollBar(FeedScrollBar(feed))
        feed.verticalScrollBar().setSingleStep(30)
        feed.setFrameShape(FeedListWidget.NoFrame)
        feed.setSpacing(0)
        feed.configure_adaptive_grid(
            FEED_CARD_WIDTH,
            FEED_GRID_ROW_HEIGHT,
            min_gap=FEED_MIN_GAP,
        )
        feed.setUniformItemSizes(True)

        if isinstance(parent_layout, QBoxLayout):
            parent_layout.removeWidget(old_scroll)
            parent_layout.insertWidget(max(0, layout_index), feed, 1)
        elif isinstance(parent_layout, QGridLayout) and grid_position is not None:
            parent_layout.removeWidget(old_scroll)
            row, column, row_span, column_span = grid_position
            parent_layout.addWidget(feed, row, column, row_span, column_span)
        old_scroll.hide()
        return feed

    def setup_library_feed_views(self: "MainWindow") -> None:
        self.library_route_counts = {}
        self.library_feed_views = {
            id(self.library_favorite_layout): self._replace_scroll_with_library_feed(
                self.library_favorite_scroll, "libraryFavoriteFeed"
            ),
            id(self.library_remote_history_layout): self._replace_scroll_with_library_feed(
                self.library_remote_history_scroll, "libraryRemoteHistoryFeed"
            ),
            id(self.local_collection_layout): self._replace_scroll_with_library_feed(
                self.local_collection_scroll, "libraryLocalFavoriteFeed"
            ),
        }
        scrollbar_style = (
            "QScrollBar:vertical{border:0;background:#f3f3f3;width:8px;"
            "margin:0;padding:0;}"
            "QScrollBar::handle:vertical{background:#878787;min-height:10px;}"
            "QScrollBar::handle:vertical:hover{background:#646464;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{"
            "border:0;background:transparent;width:0;height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{"
            "background:transparent;}"
        )
        continuous_feeds = (
            (
                self.library_feed_for_layout(self.library_favorite_layout),
                self.on_library_favorite_scroll,
                self.check_library_favorite_scroll_end,
            ),
            (
                self.library_feed_for_layout(self.library_remote_history_layout),
                self.on_library_remote_history_scroll,
                self.check_library_remote_history_scroll_end,
            ),
        )
        for feed, scroll_handler, range_handler in continuous_feeds:
            if feed is None:
                continue
            feed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            scrollbar = feed.verticalScrollBar()
            scrollbar.setStyleSheet(scrollbar_style)
            scrollbar.valueChanged.connect(scroll_handler)
            scrollbar.rangeChanged.connect(
                lambda _minimum, _maximum, handler=range_handler: QTimer.singleShot(
                    0, handler
                )
            )

    def on_library_remote_history_scroll(self: "MainWindow", _value: int) -> None:
        self.check_library_remote_history_scroll_end()

    def check_library_remote_history_scroll_end(self: "MainWindow") -> None:
        feed = self.library_feed_for_layout(self.library_remote_history_layout)
        if feed is None or not feed.isVisible():
            return
        scrollbar = feed.verticalScrollBar()
        if scrollbar.maximum() - scrollbar.value() > 320:
            return
        self.load_next_library_remote_history_page()

    def load_next_library_remote_history_page(self: "MainWindow") -> None:
        if (
            getattr(self, "library_remote_history_loading", False)
            or not getattr(self, "library_remote_history_has_more", True)
            or not getattr(self, "library_remote_history", [])
        ):
            return
        previous_page = max(1, int(getattr(self, "library_remote_history_page", 1)))
        self.library_remote_history_page = previous_page + 1
        if not self.refresh_library_remote_history():
            self.library_remote_history_page = previous_page

    def reset_library_remote_history_feed_scroll(self: "MainWindow") -> None:
        feed = self.library_feed_for_layout(self.library_remote_history_layout)
        if feed is None:
            return
        scrollbar = feed.verticalScrollBar()
        reset_thumb_size = getattr(scrollbar, "reset_thumb_size", None)
        if callable(reset_thumb_size):
            reset_thumb_size()
        jump_to = getattr(scrollbar, "jump_to", None)
        if callable(jump_to):
            jump_to(0)
        else:
            scrollbar.setValue(0)

    def apply_library_remote_history_result(self: "MainWindow", result) -> None:
        self.library_remote_history_loading = False
        if getattr(self, "library_remote_history_reload_pending", False):
            self.library_remote_history_reload_pending = False
            self.refresh_library_remote_history()
            return

        incoming = self.unique_library_albums(
            [],
            [
                self.album_from_dict(item)
                for item in (result.get("albums") or [])
                if isinstance(item, dict)
            ],
        )
        response_page = max(
            1, int(result.get("page") or self.library_remote_history_page)
        )
        self.library_remote_history_page = response_page
        self.library_remote_history_total = max(0, int(result.get("total") or 0))
        if response_page <= 1:
            self.library_remote_history = incoming
            appended = incoming
        else:
            appended = self.unique_library_albums(
                self.library_remote_history, incoming
            )
            self.library_remote_history.extend(appended)
        self.library_remote_history_has_more = bool(incoming) and bool(appended) and (
            self.library_remote_history_total <= 0
            or len(self.library_remote_history) < self.library_remote_history_total
        )
        self.render_library_albums(
            self.library_remote_history_layout,
            appended if response_page > 1 else self.library_remote_history,
            "暂无云端观看记录",
            append=response_page > 1,
        )
        self.set_library_route_count(
            "remoteHistoryTab", len(self.library_remote_history), "本"
        )
        QTimer.singleShot(0, self.check_library_remote_history_scroll_end)

    def apply_library_remote_history_failure(self: "MainWindow") -> None:
        self.library_remote_history_loading = False
        if getattr(self, "library_remote_history_reload_pending", False):
            self.library_remote_history_reload_pending = False
            self.refresh_library_remote_history()
            return
        if self.library_remote_history_page > 1:
            self.library_remote_history_page -= 1
        self.library_remote_history_has_more = True

    def set_library_status_text(self: "MainWindow", text: str) -> None:
        label = getattr(self, "library_status_label", None)
        if label is not None:
            label.setText(text)

    def on_library_favorite_scroll(self: "MainWindow", _value: int) -> None:
        self.check_library_favorite_scroll_end()

    def check_library_favorite_scroll_end(self: "MainWindow") -> None:
        feed = self.library_feed_for_layout(self.library_favorite_layout)
        if feed is None or not feed.isVisible():
            return
        scrollbar = feed.verticalScrollBar()
        if scrollbar.maximum() - scrollbar.value() > 320:
            return
        self.load_next_library_favorite_page()

    def load_next_library_favorite_page(self: "MainWindow") -> None:
        if (
            getattr(self, "library_favorite_loading", False)
            or not getattr(self, "library_favorite_has_more", True)
            or not getattr(self, "library_favorites", [])
        ):
            return
        previous_page = max(1, int(getattr(self, "library_favorite_page", 1)))
        self.library_favorite_page = previous_page + 1
        if not self.refresh_library_favorites():
            self.library_favorite_page = previous_page

    def reset_library_favorite_feed_scroll(self: "MainWindow") -> None:
        feed = self.library_feed_for_layout(self.library_favorite_layout)
        if feed is None:
            return
        scrollbar = feed.verticalScrollBar()
        reset_thumb_size = getattr(scrollbar, "reset_thumb_size", None)
        if callable(reset_thumb_size):
            reset_thumb_size()
        jump_to = getattr(scrollbar, "jump_to", None)
        if callable(jump_to):
            jump_to(0)
        else:
            scrollbar.setValue(0)

    @staticmethod
    def unique_library_albums(existing, incoming):
        """Return only new album IDs, preserving the server's display order."""
        known_ids = {str(album.album_id) for album in (existing or [])}
        unique = []
        for album in incoming or []:
            album_id = str(album.album_id)
            if album_id in known_ids:
                continue
            known_ids.add(album_id)
            unique.append(album)
        return unique

    def create_library_empty_state_widget(
        self: "MainWindow", parent, empty_text: str
    ) -> QFrame:
        return build_library_empty_state(
            parent,
            empty_text,
            self.open_library_discovery_page,
        )

    def open_library_discovery_page(self: "MainWindow") -> None:
        self.category_rank_page_lock = False
        self.switch_page(self.category_rank_page_index())
        self.show_category_rank_overview()

    def show_library_feed_empty_state(
        self: "MainWindow", feed: FeedListWidget, empty_text: str
    ) -> None:
        empty_state = self.create_library_empty_state_widget(
            feed.viewport(), empty_text
        )
        feed.set_empty_state_widget(empty_state)

    def setup_history_feed_view(self: "MainWindow") -> None:
        old_scroll = self.history_scroll
        self.history_feed_view = self._replace_scroll_with_library_feed(
            old_scroll, "localHistoryFeed"
        )
        self.history_scroll = self.history_feed_view

    def library_feed_for_layout(self: "MainWindow", layout) -> Optional[FeedListWidget]:
        return getattr(self, "library_feed_views", {}).get(id(layout))

    def set_library_route_count(
        self: "MainWindow", route: str, count: int, unit: str
    ) -> None:
        self.library_route_counts[route] = (max(0, int(count)), unit)
        current = self.library_tabs.currentWidget() if hasattr(self, "library_tabs") else None
        if current is not None and current.objectName() == route:
            self.set_library_status_text(f"{max(0, int(count))} {unit}")

    def show_library_route_status(self: "MainWindow", route: str) -> None:
        count = getattr(self, "library_route_counts", {}).get(route)
        self.set_library_status_text(
            f"{count[0]} {count[1]}" if count is not None else "准备就绪"
        )

    def render_library_feed(
        self: "MainWindow",
        feed: FeedListWidget,
        albums,
        empty_text: str,
        *,
        favorite_actions: bool = False,
        remove_callback=None,
        append: bool = False,
    ) -> None:
        albums = list(albums or [])
        entries = [(album, None, None) for album in albums]
        route_by_feed = {
            "libraryFavoriteFeed": "favoritesTab",
            "libraryRemoteHistoryFeed": "remoteHistoryTab",
            "libraryLocalFavoriteFeed": "localTab",
        }
        route = route_by_feed.get(feed.objectName())
        if route:
            count = feed.count() + len(albums) if append else len(albums)
            self.set_library_route_count(route, count, "本")
        self._render_account_feed_entries(
            feed,
            entries,
            empty_text,
            favorite_actions=favorite_actions,
            remove_callback=remove_callback,
            append=append,
        )

    def refresh_history_feed_if_ready(self: "MainWindow") -> bool:
        refresh = getattr(self, "refresh_local_reading_history", None)
        if callable(refresh):
            return bool(refresh())
        feed = getattr(self, "history_feed_view", None)
        if feed is None:
            return False
        refresh_key = self.current_history_refresh_key()
        if refresh_key == self.history_refresh_key and feed.count():
            return True
        self.history_refresh_key = refresh_key
        self.history_render_generation += 1
        visible_records = [
            (index, record)
            for index, record in enumerate(self.download_history)
            if self.history_record_matches_format_filter(record)
        ]
        self.history_visible_records = list(reversed(visible_records))
        entries = []
        for history_index, record in self.history_visible_records:
            album = self.album_from_history_record(record)
            if album is None:
                album = AlbumMeta(
                    album_id=f"local-history-{history_index}",
                    title=record.get("title") or record.get("file") or "本地漫画",
                    url="",
                    source="本地记录",
                )
            album.tags = list(album.tags or []) or [
                value
                for value in (record.get("format"), record.get("source"))
                if value
            ]
            entries.append((album, history_index, record))
        self._render_account_feed_entries(feed, entries, "暂无本地记录")
        return True

    def _render_account_feed_entries(
        self: "MainWindow",
        feed: FeedListWidget,
        entries,
        empty_text: str,
        *,
        favorite_actions: bool = False,
        remove_callback=None,
        append: bool = False,
    ) -> None:
        entries = list(entries or [])
        generation = int(getattr(feed, "_feed_generation", 0))
        if not append or generation <= 0:
            generation += 1
            feed._feed_generation = generation
        queued_entries = [
            (
                album,
                history_index,
                history_record,
                favorite_actions,
                remove_callback,
            )
            for album, history_index, history_record in entries
            if isinstance(album, AlbumMeta)
        ]
        if not append:
            feed.clear()
            feed.clear_empty_state_widget()
            feed.verticalScrollBar().jump_to(0)
            feed._feed_render_pending = queued_entries
            feed._feed_render_scheduled = False
        else:
            if queued_entries:
                feed.clear_empty_state_widget()
            pending = list(getattr(feed, "_feed_render_pending", []))
            pending.extend(queued_entries)
            feed._feed_render_pending = pending
        feed._feed_render_empty_text = empty_text
        self.schedule_account_feed_render(feed, generation)

    def schedule_account_feed_render(
        self: "MainWindow", feed: FeedListWidget, generation: int
    ) -> None:
        if bool(getattr(feed, "_feed_render_scheduled", False)):
            return
        feed._feed_render_scheduled = True
        QTimer.singleShot(
            0,
            lambda feed=feed, generation=generation:
            self.render_account_feed_batch(feed, generation),
        )

    def render_account_feed_batch(
        self: "MainWindow", feed: FeedListWidget, generation: int
    ) -> None:
        try:
            if int(getattr(feed, "_feed_generation", 0)) != generation:
                return
        except RuntimeError:
            return
        feed._feed_render_scheduled = False
        pending = list(getattr(feed, "_feed_render_pending", []))
        batch = pending[:ACCOUNT_FEED_RENDER_BATCH]
        feed._feed_render_pending = pending[len(batch):]
        pending_covers = []
        feed.setUpdatesEnabled(False)
        try:
            for (
                album,
                history_index,
                history_record,
                favorite_actions,
                remove_callback,
            ) in batch:
                if not str(album.album_id).startswith("local-history-"):
                    self.albums.setdefault(album.album_id, copy.deepcopy(album))
                    self.detail_cache.setdefault(album.album_id, copy.deepcopy(album))
                card, cover = self.create_library_feed_card(
                    album,
                    history_index=history_index,
                    history_record=history_record,
                    favorite_actions=favorite_actions,
                    remove_callback=remove_callback,
                )
                item = QListWidgetItem(feed)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                item.setSizeHint(QSize(FEED_CARD_WIDTH, FEED_GRID_ROW_HEIGHT))
                feed.setItemWidget(item, card)
                pending_covers.append((album, cover, history_record))
        finally:
            feed.setUpdatesEnabled(True)
            feed.viewport().update()

        for offset, (album, cover, history_record) in enumerate(pending_covers):
            QTimer.singleShot(
                25 + offset * 18,
                lambda album=album, cover=cover, record=history_record, feed=feed, generation=generation:
                self._load_library_feed_cover(feed, generation, album, cover, record),
            )

        if feed._feed_render_pending:
            feed._feed_render_scheduled = True
            QTimer.singleShot(
                ACCOUNT_FEED_RENDER_INTERVAL_MS,
                lambda feed=feed, generation=generation:
                self.render_account_feed_batch(feed, generation),
            )
            return
        if not feed.count():
            self.show_library_feed_empty_state(
                feed, str(getattr(feed, "_feed_render_empty_text", ""))
            )
        scrollbar = feed.verticalScrollBar()
        lock_thumb_size = getattr(scrollbar, "lock_thumb_size", None)
        if callable(lock_thumb_size):
            QTimer.singleShot(0, lock_thumb_size)

    def library_feed_card_style(self: "MainWindow") -> str:
        dark = bool(getattr(self, "theme_dark", False))
        card_background = "#24272d" if dark else "#ffffff"
        card_hover = "#292d34" if dark else "#fffdfb"
        border = "#3b414b" if dark else "#e0e5eb"
        cover_background = "#30343b" if dark else "#edf0f3"
        cover_color = "#aeb6c2" if dark else "#8995a5"
        title_color = "#e5e7eb" if dark else "#202b3a"
        return f"""
            QFrame#accountLibraryCard {{
                background:{card_background}; border:1px solid {border}; border-radius:6px;
            }}
            QFrame#accountLibraryCard:hover {{ border-color:#e99045; background:{card_hover}; }}
            QLabel#albumCover {{
                background:{cover_background}; border:0; border-bottom:1px solid {border};
                border-top-left-radius:5px; border-top-right-radius:5px; color:{cover_color};
            }}
            QLabel#albumTitle {{ color:{title_color}; background:transparent; }}
            QToolButton#accountCardMenu {{
                color:#ffffff; background:rgba(25,32,42,170); border:0;
                border-radius:5px; font-size:18px; font-weight:900; padding:0;
            }}
            QToolButton#accountCardMenu:hover {{ background:#d96d16; }}
            QProgressBar#accountReadingProgress {{
                border:0; background:rgba(255,255,255,120); min-height:4px; max-height:4px;
            }}
            QProgressBar#accountReadingProgress::chunk {{ background:#18a67e; }}
            """

    def apply_library_feed_card_theme(self: "MainWindow", card: QFrame) -> None:
        dark = bool(getattr(self, "theme_dark", False))
        title_color = "#e5e7eb" if dark else "#1f2937"
        cover_color = "#aeb6c2" if dark else "#8491a5"
        try:
            card.setStyleSheet(self.library_feed_card_style())
            title = card.findChild(QLabel, "albumTitle")
            if title is not None:
                title.setStyleSheet(
                    f"font-weight:700;color:{title_color};font-size:10px;"
                )
            cover = card.findChild(QLabel, "albumCover")
            if cover is not None:
                cover.setStyleSheet(
                    f"background:transparent;border:0;color:{cover_color};"
                )
            for badge in card.findChildren(QLabel, "tagBadge"):
                badge.setStyleSheet(
                    self.tag_badge_style(bool(badge.property("compactBadge")))
                )
        except RuntimeError:
            pass

    def refresh_library_feed_card_theme(self: "MainWindow") -> None:
        root = getattr(self, "app_page", None)
        if root is None:
            return
        for card in root.findChildren(QFrame, "accountLibraryCard"):
            self.apply_library_feed_card_theme(card)

    def create_library_feed_card(
        self: "MainWindow",
        album: AlbumMeta,
        *,
        history_index: Optional[int] = None,
        history_record=None,
        favorite_actions: bool = False,
        remove_callback=None,
    ):
        card = QFrame()
        card.setObjectName("accountLibraryCard")
        card.setFixedSize(FEED_CARD_WIDTH, FEED_CARD_HEIGHT)
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet(self.library_feed_card_style())
        is_local_download = bool(
            isinstance(history_record, dict)
            and history_record.get("_local_download")
        )

        def press(event):
            if event.button() == Qt.RightButton:
                if is_reading_history:
                    self.show_local_reading_context_menu(
                        history_record, event.globalPos()
                    )
                elif history_index is not None:
                    self.show_history_context_menu(history_index, event.globalPos())
                else:
                    self.show_library_feed_context_menu(
                        album, event.globalPos(), favorite_actions, remove_callback
                    )
                return
            if event.button() != Qt.LeftButton:
                return
            if is_local_download and history_index is not None:
                self.select_history_record(history_index, open_reader=True)
            elif str(album.album_id).startswith("local-history-") and history_index is not None:
                self.select_history_record(history_index, open_reader=True)
            else:
                self.open_album_detail(album.album_id)

        card.mousePressEvent = press
        is_reading_history = bool(
            isinstance(history_record, dict)
            and history_record.get("_reading_history")
        )

        def open_card(_event=None):
            if is_local_download and history_index is not None:
                self.select_history_record(history_index, open_reader=True)
            elif is_reading_history:
                self.continue_local_reading(history_record)
            elif history_index is not None:
                self.select_history_record(history_index, open_reader=True)
            else:
                self.read_album_from_card(album.album_id)

        card.mouseDoubleClickEvent = open_card

        layout = QVBoxLayout(card)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        cover = QLabel(card)
        cover.setObjectName("albumCover")
        cover_width = FEED_CARD_WIDTH - 4
        cover.setFixedSize(cover_width, int(cover_width * 340 / 250))
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(
            "background:transparent;border:0;"
            f"color:{'#aeb6c2' if bool(getattr(self, 'theme_dark', False)) else '#8491a5'};"
        )
        cover.setText("加载中")
        cover._persistent_cover = True
        layout.addWidget(cover)

        if history_record is not None:
            page = max(0, self._profile_int(history_record.get("last_page"), 0))
            total = max(0, self._profile_int(history_record.get("last_total"), 0))
            if page and total:
                progress = QProgressBar(cover)
                progress.setObjectName("accountReadingProgress")
                progress.setRange(0, total)
                progress.setValue(min(page, total))
                progress.setTextVisible(False)
                progress.setGeometry(0, cover.height() - 4, cover.width(), 4)
            if is_reading_history:
                read_meta = QLabel(cover)
                read_meta.setObjectName("accountReadingMeta")
                read_meta.setText(
                    f"{history_record.get('relative_time') or '刚刚'}  看过"
                )
                read_meta.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                read_meta.setGeometry(0, cover.height() - 32, cover.width(), 28)
                read_meta.setStyleSheet(
                    "background:rgba(20,25,32,190);color:#ffffff;"
                    "padding:0 9px;font-size:11px;font-weight:700;border:0;"
                )

        title = QLabel(card)
        title.setObjectName("albumTitle")
        title.setFixedHeight(34)
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        title.setStyleSheet(
            "font-weight:700;"
            f"color:{'#e5e7eb' if bool(getattr(self, 'theme_dark', False)) else '#1f2937'};"
            "font-size:10px;"
        )
        title.setText(
            self.elided_album_title(album.title or "-", title.font(), cover_width - 8, 2)
        )
        title.setToolTip(album.title)
        layout.addWidget(title)

        tags_layout = QHBoxLayout()
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(4)
        for tag in self.album_card_tags(album):
            badge = self.create_tag_badge(tag, compact=True)
            tags_layout.addWidget(badge)
        tags_layout.addStretch()
        layout.addLayout(tags_layout)

        menu_button = QToolButton(card)
        menu_button.setObjectName("accountCardMenu")
        menu_button.setText("⋮")
        menu_button.setCursor(Qt.PointingHandCursor)
        menu_button.setFixedSize(28, 28)
        menu_button.move(card.width() - 36, 8)
        def show_card_menu(_checked=False, button=menu_button):
            position = button.mapToGlobal(QPoint(0, button.height()))
            if is_reading_history:
                self.show_local_reading_context_menu(history_record, position)
            elif history_index is not None:
                self.show_history_context_menu(history_index, position)
            else:
                self.show_library_feed_context_menu(
                    album, position, favorite_actions, remove_callback
                )

        menu_button.clicked.connect(show_card_menu)
        menu_button.raise_()
        return card, cover

    def _load_library_feed_cover(
        self: "MainWindow", feed, generation: int, album, cover, history_record
    ) -> None:
        try:
            if int(getattr(feed, "_feed_generation", 0)) != generation:
                return
            if (
                isinstance(history_record, dict)
                and history_record.get("_reading_history")
            ):
                self.request_cover(album, cover)
            elif history_record is not None:
                self.apply_history_cover(history_record, cover)
            else:
                self.request_cover(album, cover)
        except RuntimeError:
            return

    def show_library_feed_context_menu(
        self: "MainWindow", album, global_pos, favorite_actions=False, remove_callback=None
    ) -> None:
        menu = QMenu(self)
        menu.addAction("查看详情", lambda: self.open_album_detail(album.album_id))
        menu.addAction("开始阅读", lambda: self.read_album_from_card(album.album_id))
        menu.addAction("加入下载", lambda: self.add_album_to_queue(album.album_id))
        if favorite_actions:
            menu.addSeparator()
            move_menu = menu.addMenu("移动到")
            for folder in self.library_folders:
                folder_id = str(folder.get("id") or "")
                folder_name = str(folder.get("name") or "")
                if folder_id and folder_name:
                    move_menu.addAction(
                        folder_name,
                        lambda folder_id=folder_id: self.start_library_action(
                            "move_favorite",
                            {"album_id": album.album_id, "folder_id": folder_id},
                        ),
                    )
            menu.addAction(
                "取消收藏",
                lambda: self.start_library_action(
                    "toggle_favorite", {"album_id": album.album_id}
                ),
            )
        if remove_callback is not None:
            menu.addSeparator()
            menu.addAction("移出本地收藏", lambda: remove_callback(album.album_id))
        menu.exec(global_pos)
