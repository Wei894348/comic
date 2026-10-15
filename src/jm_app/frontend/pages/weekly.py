"""JMComic-qt-style weekly recommendation page."""

from __future__ import annotations

import copy
from typing import Dict, List, Optional, TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTabWidget,
    QVBoxLayout,
)

from ...backend.models import AlbumMeta
from ...backend.runtime_paths import resource_dir
from ...backend.schemas import NetworkSettings
from ...backend.services import get_week_albums, get_week_categories
from ..feed_scroll_bar import (
    FEED_CARD_HEIGHT,
    FEED_CARD_WIDTH,
    FEED_GRID_ROW_HEIGHT,
    FEED_MIN_GAP,
    FeedListWidget,
    FeedScrollBar,
)
from ..lazy_cover_label import LazyCoverLabel

if TYPE_CHECKING:
    from ..ui import MainWindow


WEEKLY_TYPES = ("manga", "hanman", "another")
WEEKLY_CARD_BATCH_SIZE = 8


class WeeklyWorker(QThread):
    """Run the two JM `/week` requests without blocking Qt's event loop."""

    loaded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        action: str,
        settings: NetworkSettings,
        payload: Optional[Dict] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.action = action
        self.settings = settings
        self.payload = dict(payload or {})

    def run(self) -> None:
        try:
            if self.action == "categories":
                result = get_week_categories(self.settings)
            elif self.action == "albums":
                result = get_week_albums(
                    self.settings,
                    str(self.payload.get("category_id") or ""),
                    str(self.payload.get("category_type") or "manga"),
                    page=0,
                )
            else:
                raise ValueError(f"未知每周推荐操作：{self.action}")
            self.loaded.emit(self.action, result)
        except Exception as exc:
            self.failed.emit(self.action, str(exc))


class WeeklyPageMixin:
    """Own the retained period tabs and progressively rendered weekly cards."""

    def _build_weekly_panel(self: "MainWindow") -> QFrame:
        panel = self.load_ui_widget("weekly.ui", QFrame)
        self.weekly_period_combo = panel.findChild(QComboBox, "weeklyPeriodCombo")
        self.weekly_tabs = panel.findChild(QTabWidget, "weeklyTabs")
        self.weekly_refresh_button = panel.findChild(QPushButton, "weeklyRefreshButton")
        self.weekly_period_icon = panel.findChild(QLabel, "weeklyPeriodIcon")
        self.weekly_update_icon = panel.findChild(QLabel, "weeklyUpdateIcon")
        self.weekly_loading_frame = panel.findChild(QFrame, "weeklyLoadingFrame")
        self.weekly_loading_art = panel.findChild(QLabel, "weeklyLoadingArt")
        self.weekly_loading_text = panel.findChild(QLabel, "weeklyLoadingText")
        layouts = {
            "manga": panel.findChild(QVBoxLayout, "weeklyMangaLayout"),
            "hanman": panel.findChild(QVBoxLayout, "weeklyHanmanLayout"),
            "another": panel.findChild(QVBoxLayout, "weeklyAnotherLayout"),
        }
        required = [
            self.weekly_period_combo,
            self.weekly_tabs,
            self.weekly_refresh_button,
            self.weekly_period_icon,
            self.weekly_update_icon,
            self.weekly_loading_frame,
            self.weekly_loading_art,
            self.weekly_loading_text,
            *layouts.values(),
        ]
        if any(control is None for control in required):
            raise RuntimeError("weekly.ui is missing required controls")

        icon_dir = resource_dir() / "nav_icons"
        period_icon_path = icon_dir / "line_weekly_active.svg"
        update_icon_path = icon_dir / "line_history_active.svg"
        combo_arrow_path = str(icon_dir / "chevron_down_active.svg").replace("\\", "/")
        if period_icon_path.exists():
            self.weekly_period_icon.setPixmap(
                QIcon(str(period_icon_path)).pixmap(19, 19)
            )
        if update_icon_path.exists():
            self.weekly_update_icon.setPixmap(
                QIcon(str(update_icon_path)).pixmap(19, 19)
            )
        refresh_source = self.style().standardIcon(
            QStyle.StandardPixmap.SP_BrowserReload
        ).pixmap(QSize(18, 18))
        refresh_pixmap = QPixmap(refresh_source.size())
        refresh_pixmap.setDevicePixelRatio(refresh_source.devicePixelRatio())
        refresh_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(refresh_pixmap)
        painter.drawPixmap(0, 0, refresh_source)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn
        )
        painter.fillRect(refresh_pixmap.rect(), QColor("#ffffff"))
        painter.end()
        self.weekly_refresh_button.setIcon(QIcon(refresh_pixmap))
        self.weekly_refresh_button.setIconSize(QSize(18, 18))
        self.weekly_refresh_button.setToolTip("重新获取每周推荐期数")
        self.weekly_period_combo.setMaxVisibleItems(12)
        self.weekly_period_combo.view().setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )
        self.weekly_tabs.tabBar().setExpanding(False)

        self.weekly_lists: Dict[str, FeedListWidget] = {}
        for category_type, layout in layouts.items():
            comic_list = self._create_weekly_list(panel)
            comic_list.setObjectName(f"weekly{category_type.title()}List")
            layout.addWidget(comic_list)
            self.weekly_lists[category_type] = comic_list

        self.weekly_categories_loaded = False
        self.weekly_categories_pending = False
        self.weekly_result_cache: Dict[tuple[str, str], List[AlbumMeta]] = {}
        self.weekly_rendered_keys: Dict[str, tuple[str, str]] = {}
        self.weekly_pending_keys = set()
        self.weekly_workers: List[WeeklyWorker] = []
        self.weekly_render_generation = 0
        self.weekly_period_combo.currentIndexChanged.connect(
            lambda _index=0: self.refresh_weekly_albums()
        )
        self.weekly_tabs.currentChanged.connect(self.on_weekly_tab_changed)
        self.weekly_refresh_button.clicked.connect(
            lambda _checked=False: self.refresh_weekly_categories(force=True)
        )
        panel.setStyleSheet(
            "QFrame#weeklyPanel{background:#f7f8fa;border:0;}"
            "QFrame#weeklyToolbar{background:#ffffff;border:1px solid #e5e8ee;"
            "border-radius:8px;}"
            "QLabel#weeklyPeriodIcon,QLabel#weeklyUpdateIcon{background:#fff3e8;"
            "border:0;border-radius:17px;}"
            "QLabel#weeklyPeriodCaption{color:#273142;font-size:15px;font-weight:800;}"
            "QLabel#weeklyUpdateHint{color:#4b5565;font-size:14px;font-weight:600;}"
            "QComboBox#weeklyPeriodCombo{background:#ffffff;border:1px solid #ff9a52;"
            "border-radius:7px;padding:0 0 0 12px;color:#222b38;font-size:15px;}"
            "QComboBox#weeklyPeriodCombo:hover,QComboBox#weeklyPeriodCombo:focus{"
            "border-color:#f07800;background:#fffdfb;}"
            "QComboBox#weeklyPeriodCombo::drop-down{width:24px;border:0;}"
            f"QComboBox#weeklyPeriodCombo::down-arrow{{image:url({combo_arrow_path});"
            "width:16px;height:16px;}"
            "QComboBox#weeklyPeriodCombo QAbstractItemView{background:#ffffff;"
            "color:#273142;border:1px solid #e5e8ee;selection-background-color:#fff0e5;"
            "selection-color:#e96600;outline:0;padding:5px;}"
            "QPushButton#weeklyRefreshButton{padding:0 16px;background:#f07800;"
            "color:#ffffff;border:1px solid #f07800;border-radius:7px;"
            "font-size:14px;font-weight:800;}"
            "QPushButton#weeklyRefreshButton:hover{background:#dc6900;border-color:#dc6900;}"
            "QPushButton#weeklyRefreshButton:pressed{background:#c85f00;}"
            "QPushButton#weeklyRefreshButton:disabled{background:#f3b17d;"
            "border-color:#f3b17d;color:#fff8f2;}"
            "QTabWidget#weeklyTabs::pane{border:0;border-top:1px solid #e5e8ee;"
            "background:transparent;top:-1px;}"
            "QTabWidget#weeklyTabs QTabBar::tab{min-width:92px;min-height:42px;padding:0 18px;"
            "border:0;border-bottom:3px solid transparent;background:transparent;"
            "color:#596273;font-size:14px;font-weight:800;}"
            "QTabWidget#weeklyTabs QTabBar::tab:hover{color:#f07800;background:#fff7f0;}"
            "QTabWidget#weeklyTabs QTabBar::tab:selected{color:#ff7600;border-bottom-color:#ff7600;}"
            "QFrame#weeklyLoadingFrame{background:transparent;border:0;}"
            "QLabel#weeklyLoadingText{color:#64748b;font-size:13px;}"
        )
        self.weekly_loading_frame.hide()
        return panel

    @staticmethod
    def _create_weekly_list(parent) -> FeedListWidget:
        comic_list = FeedListWidget(parent)
        comic_list.setViewMode(QListView.IconMode)
        comic_list.setFlow(QListView.LeftToRight)
        comic_list.setWrapping(True)
        comic_list.setResizeMode(QListView.Adjust)
        comic_list.setMovement(QListView.Static)
        comic_list.setSelectionMode(QAbstractItemView.NoSelection)
        comic_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        comic_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        comic_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        comic_list.setVerticalScrollBar(FeedScrollBar(comic_list))
        comic_list.verticalScrollBar().setSingleStep(30)
        comic_list.setFrameShape(QListWidget.NoFrame)
        comic_list.setSpacing(0)
        comic_list.configure_adaptive_grid(
            FEED_CARD_WIDTH,
            FEED_GRID_ROW_HEIGHT,
            min_gap=FEED_MIN_GAP,
        )
        comic_list.setUniformItemSizes(True)
        return comic_list

    def open_weekly_page(self: "MainWindow") -> None:
        self.switch_page(self.weekly_page_index())
        if not self.weekly_categories_loaded:
            self.refresh_weekly_categories()

    def weekly_type_for_index(self: "MainWindow", index: int) -> str:
        if 0 <= int(index) < len(WEEKLY_TYPES):
            return WEEKLY_TYPES[int(index)]
        return "manga"

    def current_weekly_type(self: "MainWindow") -> str:
        return self.weekly_type_for_index(self.weekly_tabs.currentIndex())

    def current_weekly_key(self: "MainWindow") -> Optional[tuple[str, str]]:
        category_id = str(self.weekly_period_combo.currentData() or "").strip()
        if not category_id:
            return None
        return category_id, self.current_weekly_type()

    def on_weekly_tab_changed(self: "MainWindow", _index: int) -> None:
        if self.weekly_categories_loaded:
            self.refresh_weekly_albums()

    def refresh_weekly_categories(self: "MainWindow", force: bool = False) -> None:
        if self.weekly_categories_pending:
            return
        if force:
            self.weekly_result_cache.clear()
            self.weekly_rendered_keys.clear()
        self.weekly_categories_pending = True
        self.weekly_refresh_button.setEnabled(False)
        self._set_weekly_loading(True, "正在加载推荐期数")
        self._start_weekly_worker("categories")

    def refresh_weekly_albums(self: "MainWindow", force: bool = False) -> None:
        key = self.current_weekly_key()
        if key is None:
            if not self.weekly_categories_loaded:
                self.refresh_weekly_categories()
            return
        category_type = key[1]
        if not force and key in self.weekly_result_cache:
            if self.weekly_rendered_keys.get(category_type) != key:
                self.render_weekly_albums(key, self.weekly_result_cache[key])
            else:
                self._set_weekly_loading(False)
            return
        if key in self.weekly_pending_keys:
            return
        self.weekly_pending_keys.add(key)
        self._set_weekly_loading(True, "正在加载本期推荐")
        self._start_weekly_worker(
            "albums",
            {"category_id": key[0], "category_type": key[1]},
        )

    def _start_weekly_worker(
        self: "MainWindow", action: str, payload: Optional[Dict] = None
    ) -> None:
        worker = WeeklyWorker(action, self._profile_settings(), payload, self)
        self.weekly_workers.append(worker)
        worker.loaded.connect(
            lambda loaded_action, result, worker=worker: self.on_weekly_loaded(
                loaded_action, result, worker
            )
        )
        worker.failed.connect(
            lambda failed_action, message, worker=worker: self.on_weekly_failed(
                failed_action, message, worker
            )
        )
        worker.finished.connect(lambda worker=worker: self.forget_weekly_worker(worker))
        worker.start()

    def forget_weekly_worker(self: "MainWindow", worker: WeeklyWorker) -> None:
        if worker in self.weekly_workers:
            self.weekly_workers.remove(worker)
        worker.deleteLater()

    def on_weekly_loaded(
        self: "MainWindow", action: str, result, worker: WeeklyWorker
    ) -> None:
        result = dict(result or {})
        if action == "categories":
            self.weekly_categories_pending = False
            self.sync_weekly_categories(result.get("categories") or [])
            return
        key = (
            str(result.get("category_id") or worker.payload.get("category_id") or ""),
            str(result.get("category_type") or worker.payload.get("category_type") or "manga"),
        )
        self.weekly_pending_keys.discard(key)
        albums = [
            self.album_from_dict(item)
            for item in (result.get("albums") or [])
            if isinstance(item, dict)
        ]
        self.weekly_result_cache[key] = albums
        if key == self.current_weekly_key():
            self.render_weekly_albums(key, albums)

    def on_weekly_failed(
        self: "MainWindow", action: str, message: str, worker: WeeklyWorker
    ) -> None:
        if action == "albums":
            key = (
                str(worker.payload.get("category_id") or ""),
                str(worker.payload.get("category_type") or "manga"),
            )
            self.weekly_pending_keys.discard(key)
        else:
            self.weekly_categories_pending = False
            self.weekly_refresh_button.setEnabled(True)
        self._set_weekly_loading(False)
        self.show_toast(f"每周必看加载失败：{message}", 2800)
        self.log(f"每周必看 {action} 失败：{message}")

    def sync_weekly_categories(self: "MainWindow", categories: List[Dict]) -> None:
        previous = self.weekly_period_combo.currentData()
        self.weekly_period_combo.blockSignals(True)
        self.weekly_period_combo.clear()
        for item in categories:
            category_id = str(item.get("id") or "").strip()
            if not category_id:
                continue
            time_text = str(item.get("time") or "").strip()
            title = str(item.get("title") or "").strip()
            label = "  ".join(value for value in (title, time_text) if value) or category_id
            self.weekly_period_combo.addItem(label, category_id)
        index = self.weekly_period_combo.findData(previous)
        self.weekly_period_combo.setCurrentIndex(
            index if index >= 0 else (0 if self.weekly_period_combo.count() else -1)
        )
        self.weekly_period_combo.blockSignals(False)
        self.weekly_categories_loaded = bool(self.weekly_period_combo.count())
        self.weekly_refresh_button.setEnabled(True)
        if self.weekly_categories_loaded:
            self.refresh_weekly_albums()
        else:
            self._set_weekly_loading(False)
            self.render_weekly_albums(("", self.current_weekly_type()), [])

    def render_weekly_albums(
        self: "MainWindow", key: tuple[str, str], albums: List[AlbumMeta]
    ) -> None:
        category_type = key[1]
        comic_list = self.weekly_lists[category_type]
        self.weekly_render_generation += 1
        generation = self.weekly_render_generation
        comic_list.clear()
        self.weekly_rendered_keys.pop(category_type, None)
        scrollbar = comic_list.verticalScrollBar()
        reset_thumb = getattr(scrollbar, "reset_thumb_size", None)
        if callable(reset_thumb):
            reset_thumb()
        jump_to = getattr(scrollbar, "jump_to", None)
        if callable(jump_to):
            jump_to(0)
        else:
            scrollbar.setValue(0)
        if not albums:
            self.weekly_rendered_keys[category_type] = key
            self._append_weekly_empty_state(comic_list, "本期没有推荐漫画")
            self._set_weekly_loading(False)
            return
        self._set_weekly_loading(True, "正在排列漫画，封面将逐步加载")
        self._append_weekly_card_batch(key, list(albums), 0, generation)

    def _append_weekly_card_batch(
        self: "MainWindow",
        key: tuple[str, str],
        albums: List[AlbumMeta],
        start: int,
        generation: int,
    ) -> None:
        if generation != self.weekly_render_generation:
            return
        category_type = key[1]
        comic_list = self.weekly_lists[category_type]
        end = min(len(albums), start + WEEKLY_CARD_BATCH_SIZE)
        comic_list.setUpdatesEnabled(False)
        try:
            for album in albums[start:end]:
                self.albums[album.album_id] = copy.deepcopy(album)
                self.detail_cache.setdefault(album.album_id, copy.deepcopy(album))
                card = self.create_weekly_album_card(album, comic_list)
                item = QListWidgetItem(comic_list)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                item.setSizeHint(QSize(FEED_CARD_WIDTH, FEED_GRID_ROW_HEIGHT))
                comic_list.setItemWidget(item, card)
        finally:
            comic_list.setUpdatesEnabled(True)
            comic_list.viewport().update()
        if end < len(albums):
            QTimer.singleShot(
                12,
                lambda: self._append_weekly_card_batch(key, albums, end, generation),
            )
            return
        scrollbar = comic_list.verticalScrollBar()
        lock_thumb = getattr(scrollbar, "lock_thumb_size", None)
        if callable(lock_thumb):
            lock_thumb()
        self.weekly_rendered_keys[category_type] = key
        self._set_weekly_loading(False)

    def create_weekly_album_card(
        self: "MainWindow", album: AlbumMeta, comic_list: FeedListWidget
    ) -> QFrame:
        card = QFrame(comic_list.viewport())
        card.setObjectName("albumCard")
        card.setFixedSize(FEED_CARD_WIDTH, FEED_CARD_HEIGHT)
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet(self.album_card_style(False))
        card._album_id = album.album_id
        card.mousePressEvent = lambda event, album_id=album.album_id: (
            self.open_album_detail(album_id) if event.button() == Qt.LeftButton else None
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        cover = LazyCoverLabel(card)
        cover.setObjectName("albumCover")
        cover_width = FEED_CARD_WIDTH - 4
        cover_height = int(cover_width * 340 / 250)
        cover.setFixedSize(cover_width, cover_height)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet("background:transparent;border:0;color:#8491a5;")
        cover.setText("加载中")
        cover._persistent_cover = True
        cover.bind_album(album.album_id, self.weekly_render_generation)
        cover.load_requested.connect(self.on_weekly_cover_painted)
        layout.addWidget(cover)

        title = QLabel(card)
        title.setObjectName("albumTitle")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        title.setFixedHeight(34)
        title.setToolTip(album.title)
        title.setStyleSheet("font-weight:700;color:#1f2937;font-size:10px;")
        title.setText(
            self.elided_album_title(album.title or "-", title.font(), cover_width - 8, 2)
        )
        layout.addWidget(title)

        tags_layout = QHBoxLayout()
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(4)
        for tag in self.album_card_tags(album):
            badge = QLabel(tag, card)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedHeight(18)
            badge.setToolTip("  ".join(album.tags))
            badge.setStyleSheet(
                "background:#fff7ed;border:1px solid #ff7a00;border-radius:9px;"
                "color:#d65f00;font-size:10px;font-weight:800;padding:0 6px;"
            )
            tags_layout.addWidget(badge)
        tags_layout.addStretch()
        layout.addLayout(tags_layout)
        return card

    def on_weekly_cover_painted(self: "MainWindow", label: LazyCoverLabel) -> None:
        album_id = str(getattr(label, "_album_id", ""))
        album = self.albums.get(album_id) or self.detail_cache.get(album_id)
        if album is not None and self.is_live_cover_target(album_id, label):
            self.request_cover(album, label)

    @staticmethod
    def _append_weekly_empty_state(comic_list: FeedListWidget, text: str) -> None:
        item = QListWidgetItem(comic_list)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        item.setSizeHint(QSize(420, 72))
        label = QLabel(text, comic_list.viewport())
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color:#64748b;font-size:14px;")
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        comic_list.setItemWidget(item, label)

    def _set_weekly_loading(self: "MainWindow", visible: bool, text: str = "") -> None:
        if text:
            self.weekly_loading_text.setText(text)
        if visible:
            self.apply_detail_loading_movie(self.weekly_loading_art, QSize(80, 64))
            self.weekly_loading_frame.show()
            return
        self.stop_label_movie(self.weekly_loading_art)
        self.weekly_loading_frame.hide()
