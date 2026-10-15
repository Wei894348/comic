import copy
import hashlib
from html import unescape
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from PySide6.QtCore import (
    QFile,
    QIODevice,
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSequentialAnimationGroup,
    QSignalBlocker,
    QSize,
    QThread,
    QTimer,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QIcon, QImage, QImageReader, QKeySequence, QMovie, QPainter, QPainterPath, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QButtonGroup,
    QBoxLayout,
    QApplication,
    QPlainTextEdit,
    QProgressBar,
    QGraphicsOpacityEffect,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from .app_icon import APP_DISPLAY_NAME, app_icon
from .feed_scroll_bar import (
    FEED_CARD_HEIGHT,
    FEED_CARD_WIDTH,
    FEED_MIN_GAP,
    PROFILE_CARD_HEIGHT,
    PROFILE_CARD_WIDTH,
    PROFILE_GRID_ROW_HEIGHT,
    FeedListWidget,
    FeedScrollBar,
)
from .lazy_cover_label import LazyCoverLabel
from .lifecycle import LifecycleController
from .state_persistence import StatePersistenceMixin
from .pages import (
    AppearancePageMixin,
    CommentsPageMixin,
    DetailPageMixin,
    DownloadPageMixin,
    HomePageMixin,
    LibraryFeedPageMixin,
    LocalDownloadPageMixin,
    LocalFavoritePageMixin,
    LocalHistoryPageMixin,
    NAVIGATION_PANEL_WIDTH,
    NavigationPageMixin,
    ProfilePageMixin,
    SettingsPageMixin,
    WeeklyPageMixin,
)
from .pages.home import HOME_CATEGORY_BY_KEY, HOME_CATEGORY_TABS
from .controllers import DetailController, DownloadController, HomeController, ReaderController
from ..desktop_pet_launcher import show_desktop_pet, stop_desktop_pet
from ..backend.constants import DEFAULT_USER_AGENT
from ..backend.cookie_store import clear_cookie_store, load_cookie_header, save_cookie_dict
from ..backend.app_logger import AppLog
from ..backend.cache_db import HistoryStore
from ..backend.download_store import DownloadStore
from ..backend.library_store import LocalCollectionStore
from ..backend.library_tools import DEFAULT_DOH_ENDPOINT
from ..backend.storage_store import StorageStore
from ..backend.jm_api import APP_USER_AGENT, APP_VERSION
from ..backend.jm_endpoints import (
    API_DOMAINS,
    IMAGE_DOMAINS,
    MEDIA_ALBUMS_PATH,
    WEB_LIST_URL as LIST_URL,
    album_cover_path,
    https_url,
    user_media_path,
)
from ..backend.jmcomic_defaults import jmcomic_default_cookie_header
from ..backend.models import AlbumMeta, ChapterMeta, DownloadConfig, NetworkConfig
from ..backend.network_session import DOH_URL
from ..models import BookInfo, DownloadState, PageQuery
from ..repositories import StateRepository
from ..tasks import (
    CacheMaintenanceWorker,
    CacheRestoreWorker,
    CoverDecodeWorker,
    CoverFetchWorker,
    CoverTask,
    DomainRefreshWorker,
    HistoryLocalCoverWorker,
    HistoryResourceDeleteWorker,
    LibraryToolWorker,
    LibraryWorker,
    LocalHistorySyncWorker,
    LocalReaderImportWorker,
    LocalReaderPrepareWorker,
    LoginVerifyWorker,
    ProfileFetchWorker,
    find_history_local_cover_path,
    history_cover_cache_key_from_record,
)
from ..backend.schemas import NetworkSettings
from .hd_reader import HdMangaReaderWindow
from .flow_layout import FlowLayout
from .toast import ToastManager
from ..backend.pdf_utils import IMAGE_SUFFIXES, collect_images
from ..backend.runtime_paths import (
    app_base_dir,
    app_data_dir,
    cache_dir,
    cover_cache_dir,
    downloads_dir,
    local_zip_cache_dir,
    log_dir,
    reader_cache_dir,
    resource_dir,
    set_download_root,
    settings_path,
    ui_cache_path,
    ui_dir,
)
from ..backend.utils import dedupe_domains, parse_cookie_header, split_ids
from ..backend.workers import ChapterWorker, DownloadWorker, IncrementalUpdateWorker, ScrapeWorker


BLUE = "#1976d2"
LIGHT_BLUE = "#e8f2ff"
TEXT = "#1f2937"
RESULT_PAGE_SIZE = 80
RESULT_INITIAL_RENDER_COUNT = 12
RESULT_RENDER_BATCH_SIZE = 12
APPEND_RENDER_BATCH_SIZE = 4
APPEND_RENDER_INTERVAL_MS = 0
CATALOG_APPLY_BATCH_SIZE = 4
# JMComic-qt starts five independent picture downloads and replenishes a slot
# as soon as one finishes.  Keeping this bounded still avoids flooding a CDN.
COVER_REQUEST_CONCURRENCY = 2
RESULT_COVER_REQUEST_INTERVAL_MS = 120
ASSETS_DIR = resource_dir()
LOADING_MOVIE_PATH = ASSETS_DIR / "loading_runner.gif"
DETAIL_LOADING_MOVIE_PATH = ASSETS_DIR / "jmcomic_loading.gif"
DETAIL_ICON_DIR = ASSETS_DIR / "detail_icons"
APP_UI_VERSION = "1.0.1"


def elide_label_text(label: QLabel, text: str, fallback_width: int = 220) -> None:
    full_text = text or "-"
    width = max(40, label.width() or label.maximumWidth() or fallback_width)
    metrics = QFontMetrics(label.font())
    label.setText(metrics.elidedText(full_text, Qt.ElideRight, width))
    label.setToolTip(full_text)


class AlbumCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_pos = QPoint()
        self._hover_pos_animation: Optional[QPropertyAnimation] = None
        self._hover_shadow_animation: Optional[QPropertyAnimation] = None
        self.shadow: Optional[QGraphicsDropShadowEffect] = None

    def enterEvent(self, event):
        self._base_pos = self.pos()
        self.setProperty("hovered", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hovered", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().leaveEvent(event)

    def _animate_hover(self, target_pos: QPoint, alpha: int):
        self.move(target_pos)

    def _ensure_shadow(self) -> QGraphicsDropShadowEffect:
        if self.shadow is None:
            self.shadow = QGraphicsDropShadowEffect(self)
        return self.shadow

    @staticmethod
    def _shadow_color(alpha: int):
        from PySide6.QtGui import QColor

        return QColor(15, 23, 42, alpha)


class MainWindow(
    AppearancePageMixin,
    StatePersistenceMixin,
    SettingsPageMixin,
    DownloadPageMixin,
    HomePageMixin,
    DetailPageMixin,
    ProfilePageMixin,
    LibraryFeedPageMixin,
    LocalDownloadPageMixin,
    LocalHistoryPageMixin,
    LocalFavoritePageMixin,
    CommentsPageMixin,
    WeeklyPageMixin,
    NavigationPageMixin,
    QMainWindow,
):
    async_log = Signal(str)

    def __init__(self):
        super().__init__()
        self._test_mode = os.environ.get("COMIC18_TESTING") == "1"
        self.setWindowTitle(APP_DISPLAY_NAME)
        icon = app_icon()
        self.setWindowIcon(icon)
        QApplication.instance().setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            if not self._test_mode:
                app.setQuitOnLastWindowClosed(False)
                app.installEventFilter(self)
        ToastManager.init(self)
        self.resize(360, 500)
        self.setMinimumSize(330, 460)
        self.albums: Dict[str, AlbumMeta] = {}
        self.row_by_id: Dict[str, int] = {}
        self.result_albums: List[Optional[AlbumMeta]] = []
        self.result_album_indices: Dict[str, int] = {}
        self.result_total_count = 0
        self.current_result_page = 1
        self.results_revealed = False
        self.result_render_pending = False
        self.result_page_switching = False
        self.pending_result_page = 0
        self.result_render_generation = 0
        self.result_render_limit = RESULT_INITIAL_RENDER_COUNT
        self.result_resize_pending = False
        self.loaded_source_pages = 0
        self.auto_loading_next_page = False
        self.auto_load_has_more = True
        self.append_start_index = 0
        self.append_next_index = 0
        self.append_render_pending = False
        self.append_render_next_index = 0
        self.append_render_end_index = 0
        self.append_render_generation = 0
        self.append_render_scroll_value = 0
        self.append_layout_freeze = False
        self.catalog_apply_pending = False
        self.catalog_apply_context = None
        self.current_result_cache_key = ""
        self.data_root = app_data_dir()
        self.default_output_dir = downloads_dir()
        self.cache_file = ui_cache_path()
        self.settings_file = settings_path()
        self.history_store = HistoryStore()
        self.download_store = DownloadStore()
        self.state_repository = StateRepository()
        self.local_collection_store = LocalCollectionStore()
        self.storage_store = StorageStore()
        self.result_cache: Dict[str, List[AlbumMeta]] = {}
        self.home_promote_sections: Dict[str, List[AlbumMeta]] = {}
        self.detail_cache: Dict[str, AlbumMeta] = {}
        self.download_history: List[Dict[str, str]] = []
        self.settings_cache: Dict[str, object] = {}
        self._applying_settings = False
        self.api_domain_pool: List[str] = list(API_DOMAINS)
        self.cover_domain_pool: List[str] = list(IMAGE_DOMAINS)
        self.cover_domain_failures: Dict[str, int] = {}
        self.card_by_id: Dict[str, QFrame] = {}
        self.album_card_pool: List[QFrame] = []
        self.checkmark_by_id: Dict[str, QLabel] = {}
        self.card_click_timers: Dict[str, QTimer] = {}
        self.result_cover_labels: Dict[str, QLabel] = {}
        self.result_cover_requested = set()
        self.result_cover_lazy_timer: Optional[QTimer] = None
        self.selected_album_ids = set()
        self.cover_targets: Dict[str, List[QLabel]] = {}
        self.cover_pending = set()
        self.cover_fallback_urls: Dict[str, List[str]] = {}
        self.cover_workers: Dict[str, CoverFetchWorker] = {}
        self.cover_decode_workers: Dict[str, CoverDecodeWorker] = {}
        self.cover_request_queue: List[tuple[str, List[str], bool]] = []
        self.cover_disk_write_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="comic18-cover-cache")
        self._cover_disk_pool_closed = False
        self.queue: List[AlbumMeta] = []
        self.download_pending_queue: List[AlbumMeta] = []
        self.completed: List[str] = []
        self.download_card_by_id: Dict[str, QFrame] = {}
        self.download_workers: Dict[str, DownloadWorker] = {}
        self.download_task_ids: Dict[str, str] = {}
        self.download_controller = DownloadController(self.background_download_config, self.state_repository, self)
        self.download_controller.worker_created.connect(self.on_download_worker_created)
        self.download_controller.log.connect(self.log)
        self.download_workers = self.download_controller.workers
        self.download_task_ids = self.download_controller.task_ids
        self.download_totals: Dict[str, int] = {}
        self.download_done_counts: Dict[str, int] = {}
        self.download_chapter_totals: Dict[str, int] = {}
        self.download_chapter_done_counts: Dict[str, int] = {}
        self.download_percent_by_id: Dict[str, int] = {}
        self.last_global_download_percent = 0
        self.download_progress_pending = set()
        self.download_transfer_pending = set()
        self.download_bytes: Dict[str, int] = {}
        self.download_speeds: Dict[str, float] = {}
        self.download_cancelled_ids = set()
        self.download_retry_ids = set()
        self.history_card_by_index: Dict[int, QFrame] = {}
        self.selected_history_index = -1
        self.history_visible_records: List[tuple[int, Dict[str, str]]] = []
        self.history_render_limit = 24
        self.history_render_batch = 24
        self.history_view_mode = "list"
        self.history_local_cover_cache: Dict[str, str] = {}
        self.history_drag_index = -1
        self.history_drag_record: Optional[Dict[str, str]] = None
        self.history_drag_start_pos = None
        self.history_dragging = False
        self.history_drag_card: Optional[QWidget] = None
        self.history_drag_ghost: Optional[QLabel] = None
        self.history_drag_opacity: Optional[QGraphicsOpacityEffect] = None
        self.history_drop_placeholder: Optional[QFrame] = None
        self.history_drop_index = -1
        self.history_drag_last_move_at = 0.0
        self.history_drag_last_autoscroll_at = 0.0
        self.history_drag_target_centers: List[tuple[int, int]] = []
        self.history_render_generation = 0
        self.history_cover_queue: List[tuple[int, Dict[str, str], QLabel]] = []
        self.history_local_cover_workers: Dict[str, HistoryLocalCoverWorker] = {}
        self.history_local_cover_labels: Dict[str, List[QLabel]] = {}
        self.history_cover_timer = QTimer(self)
        self.history_cover_timer.setSingleShot(True)
        self.history_cover_timer.timeout.connect(self.flush_history_cover_queue)
        self.history_refresh_key = None
        self.current_download_album_id = ""
        self.current_album_id = ""
        self.session_username = ""
        self.session_password = ""
        self.session_uid = ""
        self.profile_data: Dict[str, object] = {}
        self.breadcrumb_detail_parent = ""
        self.breadcrumb_detail_parent_index = 0
        self.breadcrumb_buttons: Dict[str, QPushButton] = {}
        self.page_navigation_stack: List[tuple[int, str]] = []
        self.active_navigation_position = 0
        self.breadcrumb_route_buttons: List[QPushButton] = []
        self.breadcrumb_route_separators: List[QLabel] = []
        self.login_worker: Optional[LoginVerifyWorker] = None
        self.daily_sign_worker: Optional[LoginVerifyWorker] = None
        self.profile_worker: Optional[ProfileFetchWorker] = None
        self.library_workers: List[LibraryWorker] = []
        self.library_tool_workers: List[LibraryToolWorker] = []
        self.history_delete_workers: List[HistoryResourceDeleteWorker] = []
        self.library_folders: List[Dict[str, str]] = []
        self.library_favorites: List[AlbumMeta] = []
        self.library_remote_history: List[AlbumMeta] = []
        self.library_favorite_page = 1
        self.library_favorite_loading = False
        self.library_favorite_has_more = True
        self.library_favorite_total = 0
        self.library_favorite_reload_pending = False
        self.library_remote_history_page = 1
        self.library_remote_history_loading = False
        self.library_remote_history_has_more = True
        self.library_remote_history_total = 0
        self.library_remote_history_reload_pending = False
        self.library_comment_page = 1
        self.comment_context_album_id = ""
        self.comment_context_title = ""
        # JM's forum payload contains a relative user-photo path.  Keep these
        # requests separate from album covers so cards can render immediately
        # and avatars arrive progressively without blocking the GUI thread.
        self.comment_avatar_cache: Dict[str, QPixmap] = {}
        self.comment_avatar_targets: Dict[str, List[QLabel]] = {}
        self.comment_avatar_workers: Dict[str, CoverFetchWorker] = {}
        self.comment_avatar_queue: List[tuple[str, List[str]]] = []
        self.comment_avatar_queued = set()
        self.library_latest_page = 0
        self.avatar_worker: Optional[CoverFetchWorker] = None
        self.profile_avatar_pixmap: Optional[QPixmap] = None
        self.local_history_sync_worker: Optional[LocalHistorySyncWorker] = None
        self.local_reader_import_worker: Optional[LocalReaderImportWorker] = None
        self.local_reader_prepare_workers: List[LocalReaderPrepareWorker] = []
        self.login_auto_started = False
        self.scrape_worker: Optional[ScrapeWorker] = None
        self.retired_scrape_workers: List[ScrapeWorker] = []
        self.chapter_worker: Optional[ChapterWorker] = None
        self.reader_chapter_workers: Dict[str, ChapterWorker] = {}
        self.incremental_worker: Optional[IncrementalUpdateWorker] = None
        self.domain_worker: Optional[DomainRefreshWorker] = None
        self.reader_dialogs: List[QWidget] = []
        self.local_reader_dialogs: List[QWidget] = []
        self.pending_reader_by_album_id: Dict[str, HdMangaReaderWindow] = {}
        self.cancelled_reader_album_ids = set()
        self.loading_timer: Optional[QTimer] = None
        self.incremental_timer: Optional[QTimer] = None
        self.history_save_timer = QTimer(self)
        self.history_save_timer.setSingleShot(True)
        self.history_save_timer.timeout.connect(self.save_local_cache)
        self.loading_tick = 0
        self.page_animation: Optional[QPropertyAnimation] = None
        self.active_animations = []
        self.corner_notices = []
        self.drag_position = None
        self.home_auto_loaded = False
        self.home_sections_ready = False
        self.home_sections_prefetch_started = False
        self.cover_cache: Dict[str, QPixmap] = {}
        self.cover_cache_refresh_attempted = set()
        self.home_feed_mode = "latest"
        self.home_category_key = "latest"
        self.home_category_prefix = ""
        self.pending_rank_request = ""
        self.active_category = ""
        self.cache_restore_worker: Optional[CacheRestoreWorker] = None
        self.cache_maintenance_worker: Optional[CacheMaintenanceWorker] = None
        self.cache_restore_miss_keys = set()
        self._closing_app = False
        self._allow_final_close = self._test_mode
        self._tray_quit_requested = False
        # A tray "Quit" is an explicit process-exit request.  main.py uses
        # this after QApplication.exec() returns to prevent a stranded worker
        # thread from keeping the console process alive.
        self._force_process_exit = False
        self._tray_notice_shown = False
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._close_wait_ticks = 0
        self.lifecycle = LifecycleController(self)
        self.db_write_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="comic18-db")
        self._db_pool_closed = False
        self._local_cache_save_timer: Optional[QTimer] = None
        self.async_log.connect(self.log)
        self.load_local_cache()
        self.api_route = min(1, max(0, int(self.settings_cache.get("api_route", 0) or 0)))

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.login_page = self._build_login_page()
        self.app_page = self._build_app_page()
        self.home_controller = HomeController(self.network_config, self)
        self.home_controller.page_loaded.connect(self.on_catalog_page_loaded)
        self.home_controller.page_failed.connect(self.on_catalog_page_failed)
        self.home_controller.sections_prefetched.connect(self.on_catalog_sections_prefetched)
        self.home_controller.sections_prefetch_failed.connect(self.on_catalog_sections_prefetch_failed)
        self.detail_controller = DetailController(self.home_controller.catalog, self.network_config, self)
        self.detail_controller.loaded.connect(self.on_catalog_detail_loaded)
        self.detail_controller.failed.connect(self.on_catalog_detail_failed)
        self.reader_controller = ReaderController(self.state_repository, self)
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.app_page)
        self.stack.setCurrentWidget(self.login_page)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setup_tray_icon(icon)
        self._apply_style()
        self.apply_saved_appearance()
        self.setup_shortcuts()
        self._center_window()
        if not self._test_mode:
            QTimer.singleShot(250, self.try_auto_login)

    def setup_tray_icon(self, _icon: QIcon) -> None:
        if self._test_mode or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        menu = QMenu(self)
        show_action = QAction("显示", menu)
        pet_action = QAction("显示桌宠", menu)
        quit_action = QAction("退出", menu)
        show_action.triggered.connect(self.show_from_tray)
        pet_action.triggered.connect(self.show_desktop_pet_from_tray)
        quit_action.triggered.connect(self.quit_from_tray)
        menu.addAction(show_action)
        menu.addAction(pet_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        tray = QSystemTrayIcon(_icon, self)
        tray.setToolTip(APP_DISPLAY_NAME)
        tray.setContextMenu(menu)
        tray.activated.connect(self.on_tray_activated)
        self.tray_icon = tray
        tray.show()

    def on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_from_tray()


    def show_desktop_pet_from_tray(self) -> None:
        if not show_desktop_pet():
            self.show_corner_floating_notice("桌宠启动失败，请检查运行日志", 2400)

    def _stop_tray_icon(self) -> None:
        tray = self.tray_icon
        self.tray_icon = None
        if tray is not None:
            try:
                tray.hide()
                tray.setContextMenu(None)
                tray.deleteLater()
            except Exception:
                pass

    def show_from_tray(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_from_tray(self) -> None:
        self._tray_quit_requested = True
        self._force_process_exit = True
        self._stop_tray_icon()
        stop_desktop_pet()
        self.settings_cache = self.current_settings_snapshot()
        self.save_local_cache()
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(True)
        # Network QThreads can keep Qt alive after the window and tray icon
        # are gone.  This daemon timer is independent of the Qt event loop.
        exit_timer = threading.Timer(2.0, self.force_exit_after_tray_quit)
        exit_timer.daemon = True
        exit_timer.start()
        QTimer.singleShot(0, self.close)

    def force_exit_after_tray_quit(self) -> None:
        if self._tray_quit_requested:
            os._exit(0)

    def _apply_style(self):
        self.setStyleSheet(
            f"""
            QMainWindow {{ background: #f4f4f4; }}
            QWidget#appRoot {{ background: #f4f4f4; }}
            QWidget#appRoot[darkTheme="true"],
            QWidget#dashboardContentColumn[darkTheme="true"] {{ background:#17191d; }}
            QLabel {{ color: {TEXT}; }}
            QLineEdit, QTextEdit, QSpinBox {{
                border: 1px solid #d5dce8;
                border-radius: 7px;
                padding: 6px 8px;
                background: white;
            }}
            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{
                border-color: #2f80ed;
                background: #fbfdff;
            }}
            QGroupBox {{
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                margin-top: 12px;
                background: white;
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }}
            QPushButton {{
                border: 1px solid #cfd8e3;
                border-radius: 7px;
                padding: 6px 10px;
                background: white;
            }}
            QPushButton:hover {{ background: #f1f5f9; border-color:#b8c7d9; }}
            QPushButton:pressed {{ background: #e8eef7; }}
            QPushButton#primaryButton {{
                background: {BLUE};
                color: white;
                border-color: {BLUE};
                font-weight: 600;
                border-radius: 14px;
                padding: 7px 12px;
            }}
            QPushButton#ghostButton {{
                color: {BLUE};
                border: none;
                background: transparent;
                padding: 8px 10px;
                font-weight: 600;
            }}
            QPushButton#ghostButton:hover {{
                background: #eef6ff;
                border-radius: 16px;
            }}
            QPushButton#profileAvatarButton {{
                background: #0f766e;
                color: #ffffff;
                border: 0;
                border-radius: 15px;
                font-weight: 900;
                padding: 0;
            }}
            QPushButton#profileAvatarButton:hover {{
                background: #0d9488;
            }}
            QFrame#headerAccountMenu {{
                background: #f1f5f9;
                border: 0;
                border-radius: 12px;
            }}
            QFrame#headerAccountMenu:hover {{
                background: #e2e8f0;
            }}
            QLabel#headerUserLabel {{
                color: #1e293b;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#headerAccountArrowButton {{
                color: #94a3b8;
                font-size: 18px;
                border: 0;
                background: transparent;
                padding: 0;
            }}
            QPushButton#headerAccountArrowButton:hover {{
                color: #475569;
            }}
            QFrame#profileNavFrame {{
                background: #ffffff;
                border: 0;
                border-bottom: 1px solid #e5e7eb;
            }}
            QPushButton#profileNavButton {{
                min-height: 54px;
                border: 0;
                border-radius: 0;
                border-bottom: 3px solid transparent;
                background: transparent;
                color: #64748b;
                font-size: 14px;
                font-weight: 800;
                padding: 0 14px;
            }}
            QPushButton#profileNavButton:hover {{
                color: #f97316;
                background: #fffaf5;
            }}
            QPushButton#profileNavButton:checked {{
                color: #f97316;
                border-bottom-color: #f97316;
                background: transparent;
            }}
            QPushButton#profileLogoutButton {{
                border: 0;
                background: transparent;
                color: #64748b;
                font-weight: 700;
            }}
            QPushButton#profileLogoutButton:hover {{
                color: #f97316;
                background: #fff7ed;
            }}
            QStackedWidget#profileContentStack {{
                background: #f3f4f6;
                border: 0;
            }}
            QFrame#profileTaskCard, QFrame#profileActivityCard,
            QFrame#profileFavoriteCard, QFrame#profileHistoryCard,
            QFrame#profileCommunityCard, QFrame#profileInboxCard {{
                background: #ffffff;
                border: 1px solid #dfe5ec;
                border-radius: 6px;
            }}
            QProgressBar#profileLoginTaskBar,
            QProgressBar#profileDailyTaskBar,
            QProgressBar#profileFavoriteTaskBar,
            QProgressBar#profileExpBar {{
                min-height: 7px;
                max-height: 7px;
                border: 0;
                border-radius: 3px;
                background: #e5e7eb;
            }}
            QProgressBar#profileLoginTaskBar::chunk,
            QProgressBar#profileDailyTaskBar::chunk,
            QProgressBar#profileFavoriteTaskBar::chunk,
            QProgressBar#profileExpBar::chunk {{
                border-radius: 3px;
                background: #f97316;
            }}
            QFrame#profileAlbumItem {{
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
            }}
            QFrame#profileAlbumItem:hover {{
                border-color: #ff9f43;
                background: #fffaf4;
            }}
            QListWidget#profileAlbumList {{
                background: transparent;
                border: 0;
                outline: 0;
            }}
            QFrame#profileFeedAlbumCard {{
                background: transparent;
                border: 0;
                border-radius: 0;
            }}
            QFrame#profileFeedAlbumCard:hover {{
                background: #f8fbff;
            }}
            QPushButton#profileFavoriteMoreButton,
            QPushButton#profileHistoryMoreButton {{
                border: 0;
                background: transparent;
                color: #ff7a00;
                font-weight: 800;
                padding: 4px 6px;
            }}
            QPushButton#profileFavoriteMoreButton:hover,
            QPushButton#profileHistoryMoreButton:hover {{
                background: #fff3e8;
                border-radius: 6px;
            }}
            QScrollArea#profileFavoriteScroll,
            QScrollArea#profileHistoryScroll,
            QScrollArea#profileFavoritePageScroll,
            QScrollArea#profileHistoryPageScroll {{
                background: transparent;
                border: 0;
            }}
            QLabel#profileAvatarLabel {{
                background: #111827;
                color: #ffffff;
                border-radius: 29px;
                font-size: 24px;
                font-weight: 900;
            }}
            QLabel#profileNameLabel {{
                color: #ff7a00;
                font-size: 15px;
                font-weight: 900;
            }}
            QLabel#profileUserLabel, QLabel#profileUidLabel,
            QLabel#profileStatusLabel, QLabel#profileFavoriteCountLabel,
            QLabel#profileFavoriteSummaryLabel, QLabel#profileActivityText,
            QLabel#profileInboxMessage {{
                color: #64748b;
                font-size: 12px;
            }}
            QLabel#profileTitleLabel, QLabel#profileLevelLabel,
            QLabel#profileFavoriteLabel, QLabel#profileCoinLabel {{
                color: #1f2937;
                font-size: 18px;
                font-weight: 900;
            }}
            QLabel#profileTaskTitle, QLabel#profileFavoriteTitle,
            QLabel#profileHistoryTitle, QLabel#profileActivityTitle,
            QLabel#profileCommunityTitle, QLabel#profileInboxTitle,
            QLabel#profileFavoritePageTitle, QLabel#profileHistoryPageTitle {{
                color: #1f2937;
                font-size: 14px;
                font-weight: 900;
            }}
            QLabel#profileInboxIcon {{
                color: #f97316;
                font-size: 42px;
            }}
            QLabel#profileTitleCaption, QLabel#profileLevelCaption,
            QLabel#profileFavoriteCaption, QLabel#profileCoinCaption,
            QLabel#profileExpLabel, QLabel#profileSignLabel,
            QLabel#profileTaskList {{
                color: #64748b;
                font-size: 13px;
            }}
            QFrame#dashboardHeader {{
                background: transparent;
                border: 0;
                border-radius: 0;
            }}
            QPushButton#breadcrumbMenuButton,
            QPushButton#breadcrumbSectionButton,
            QPushButton#breadcrumbCurrentButton,
            QPushButton#breadcrumbRouteButton {{
                border: 0;
                background: transparent;
                color: #475569;
                font-size: 14px;
                font-weight: 800;
                padding: 7px 10px;
                border-radius: 0;
                text-align: left;
            }}
            QPushButton#breadcrumbMenuButton:hover,
            QPushButton#breadcrumbSectionButton:hover,
            QPushButton#breadcrumbRouteButton:hover {{
                background: #f3f6fa;
                color: #1f2937;
            }}
            QPushButton#breadcrumbMenuButton:checked,
            QPushButton#breadcrumbSectionButton:checked,
            QPushButton#breadcrumbCurrentButton:checked,
            QPushButton#breadcrumbRouteButton:checked {{
                color: #ff7a00;
                background: #fff3e8;
                border-left: 3px solid #ff7a00;
                padding-left: 7px;
            }}
            QLabel#breadcrumbSep1,
            QLabel#breadcrumbSep2,
            QLabel#breadcrumbRouteSeparator {{
                color: #94a3b8;
                font-weight: 800;
            }}
            QFrame#panel {{
                background: white;
                border: 1px solid #e4eaf3;
                border-radius: 12px;
            }}
            QLabel#panelTitle {{
                font-size: 14px;
                font-weight: 800;
                padding: 6px;
            }}
            QLabel#sectionTitle {{
                color: #667894;
                font-size: 11px;
                font-weight: 800;
            }}
            QPushButton#segButton {{
                background: #f0f4fa;
                border: 1px solid #e1e8f2;
                border-radius: 6px;
                padding: 5px 8px;
            }}
            QPushButton#segButton:hover {{
                background:#eaf2ff;
                border-color:#c7dbff;
            }}
            QPushButton#segButton:checked {{
                color: #2563eb;
                background: #eaf2ff;
                font-weight: 800;
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:horizontal {{
                border:0;
                background:#f3f3f3;
                height:8px;
            }}
            QScrollBar:vertical {{
                border:0;
                background:#f3f3f3;
                width:8px;
                padding-top:12px;
                padding-bottom:12px;
            }}
            QScrollBar::handle:horizontal {{
                background:#878787;
                min-width:20px;
            }}
            QScrollBar::handle:vertical {{
                background:#878787;
                min-height:10px;
            }}
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
                background:#646464;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                border:0;
                background:transparent;
                width:0px;
                height:0px;
            }}
            QScrollBar::add-page, QScrollBar::sub-page {{
                background:transparent;
            }}
            QProgressBar {{
                border:1px solid #d9e3ef;
                border-radius:7px;
                background:#f1f5f9;
                text-align:center;
                color:#334155;
                font-weight:700;
            }}
            QProgressBar::chunk {{
                border-radius:7px;
                background:#2f80ed;
                margin:1px;
            }}
            QMenu {{
                background:#ffffff;
                border:1px solid #dbe5f0;
                border-radius:8px;
                padding:6px;
            }}
            QMenu::item {{
                padding:7px 22px;
                border-radius:6px;
            }}
            QMenu::item:selected {{
                background:#eaf2ff;
                color:#1d4ed8;
            }}
            QLabel#loadingLabel {{
                color: {BLUE};
                font-size: 18px;
                font-weight: 700;
            }}
            QFrame#loginCard {{
                background: rgba(255,255,255,0.98);
                border: 1px solid #e6edf6;
                border-radius: 18px;
            }}
            QFrame#loginCard QLineEdit {{
                border-radius: 16px;
                padding: 8px 12px;
            }}
            QFrame#loginCard QTextEdit {{
                border-radius: 12px;
                padding: 8px 10px;
            }}
            QPushButton#sideButton {{
                border: none;
                border-radius: 0;
                padding: 14px 18px;
                text-align: left;
                background: white;
                font-size: 15px;
            }}
            QPushButton#sideButton:checked {{
                background: {BLUE};
                color: white;
                font-weight: 600;
            }}
            QScrollArea#homeCategoryScroll {{
                background: #f4f4f4;
                border: 0;
                border-bottom: 1px solid #dddddd;
            }}
            QPushButton#homeCategoryButton {{
                border: 0;
                border-bottom: 3px solid transparent;
                border-radius: 0;
                min-height: 46px;
                padding: 0 13px;
                background: transparent;
                color: #4b5563;
                font-size: 15px;
                font-weight: 800;
            }}
            QPushButton#homeCategoryButton:hover {{ color: #ff7600; background: #f7f7f7; }}
            QPushButton#homeCategoryButton:checked {{ color: #ff7600; border-bottom-color: #ff7600; }}
            QFrame#searchResultToolbar {{
                background: #f7f7f7;
                border: 0;
                border-bottom: 2px solid #ff7600;
            }}
            QLabel#searchResultCaption {{
                color: #374151;
                font-size: 15px;
            }}
            QLabel#searchResultQueryLabel {{
                color: #ff7600;
                font-size: 15px;
                font-weight: 800;
            }}
            QLineEdit#searchResultEdit {{
                min-height: 38px;
                color: #374151;
                background: #ffffff;
                border: 1px solid #d5dce8;
                border-radius: 5px;
                padding: 0 10px;
            }}
            QLineEdit#searchResultEdit:focus {{
                border-color: #ff7600;
            }}
            QPushButton#searchResultButton {{
                color: #ff7600;
                background: #ffffff;
                border: 2px solid #ff7600;
                border-radius: 5px;
                font-size: 15px;
                font-weight: 800;
            }}
            QPushButton#searchResultButton:hover {{
                color: #ffffff;
                background: #ff7600;
            }}
            QFrame#navigationPanel {{
                background: #f4f4f4;
                border: 0;
                border-radius: 0;
            }}
            QFrame#categoryRankPanel {{
                background: #f7f7f7;
                border: 0;
                border-radius: 0;
            }}
            QScrollArea#categoryRankNavScroll {{
                background: #f7f7f7;
                border: 0;
                border-bottom: 1px solid #e2e2e2;
            }}
            QPushButton[categoryRankNavOption="true"] {{
                min-height: 48px;
                padding: 0 14px;
                color: #4b5563;
                background: transparent;
                border: 0;
                border-bottom: 3px solid transparent;
                font-size: 15px;
                font-weight: 800;
            }}
            QPushButton[categoryRankNavOption="true"]:hover {{
                color: #ff7600;
                background: #f1f1f1;
            }}
            QPushButton[categoryRankNavOption="true"]:checked {{
                color: #ff7600;
                border-bottom-color: #ff7600;
            }}
            QLabel[categoryRankSectionTitle="true"] {{
                color: #475569;
                font-size: 15px;
                font-weight: 500;
                padding-top: 4px;
            }}
            QPushButton#categoryRankTagOption {{
                min-height: 42px;
                padding: 5px 10px;
                color: #ff7600;
                background: transparent;
                border: 2px solid #ff7600;
                border-radius: 5px;
                font-size: 14px;
                font-weight: 800;
            }}
            QPushButton#categoryRankTagOption:hover {{
                color: #ffffff;
                background: #ff7600;
            }}
            QLabel#navUserSectionLabel, QLabel#navNavigationSectionLabel, QLabel#navSupportSectionLabel {{
                color:#374151; font-size:15px; font-weight:800; padding:11px 0 5px 2px;
            }}
            QFrame#connectionCard {{
                background: #eeeeee;
                border: 0;
                border-radius: 0;
            }}
            QLabel#connectionTitle {{
                color: #1f2937;
                font-size: 14px;
                font-weight: 800;
            }}
            QLabel#connectionSub {{
                color: #64748b;
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#connectionDot {{
                font-size: 18px;
                font-weight: 900;
            }}
            QTableWidget {{
                background: white;
                border: 1px solid #e2e8f0;
                gridline-color: #edf2f7;
                selection-background-color: transparent;
                selection-color: #1f2937;
                font-size: 12px;
            }}
            QTableWidget::item:selected {{
                background: transparent;
                color: #1f2937;
            }}
            QTableWidget::item:focus {{
                outline: none;
            }}
            QHeaderView::section {{
                background: #f8fafc;
                border: none;
                border-bottom: 1px solid #e2e8f0;
                padding: 4px 6px;
                font-weight: 600;
                font-size: 12px;
            }}
            """
        )

    def show_toast(self, message: str, duration_ms: int = 1700, parent: Optional[QWidget] = None) -> None:
        ToastManager.show(message, duration_ms, parent)

    def _load_login_page_from_ui(self) -> QWidget:
        path = ui_dir() / "login.ui"
        if not path.exists():
            raise RuntimeError(f"login.ui not found: {path}")
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open login.ui: {path}")
        try:
            page = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if page is None:
            raise RuntimeError(f"Unable to load login.ui: {path}")

        self.login_header = page.findChild(QFrame, "loginHeader")
        if self.login_header:
            self.login_header.installEventFilter(self)
        title = page.findChild(QLabel, "titleLabel")
        if title:
            title.setText(APP_DISPLAY_NAME)

        self.login_user_edit = page.findChild(QLineEdit, "loginUserEdit")
        self.login_pass_edit = page.findChild(QLineEdit, "loginPassEdit")
        self.login_cookie_edit = page.findChild(QTextEdit, "loginCookieEdit")
        self.login_ua_edit = page.findChild(QLineEdit, "loginUaEdit")
        self.save_password_box = page.findChild(QCheckBox, "savePasswordBox")
        self.auto_login_box = page.findChild(QCheckBox, "autoLoginBox")
        self.auto_sign_box = page.findChild(QCheckBox, "autoSignBox")
        self.login_btn = page.findChild(QPushButton, "loginButton")
        self.skip_login_btn = page.findChild(QPushButton, "closeButton")

        required = [
            self.login_user_edit,
            self.login_pass_edit,
            self.login_cookie_edit,
            self.login_ua_edit,
            self.save_password_box,
            self.auto_login_box,
            self.auto_sign_box,
            self.login_btn,
            self.skip_login_btn,
        ]
        if any(widget is None for widget in required):
            raise RuntimeError("login.ui is missing required controls")

        self.login_pass_edit.setEchoMode(QLineEdit.Password)
        self.login_user_edit.setPlaceholderText("账号")
        self.login_pass_edit.setPlaceholderText("密码")
        label_texts = {
            "accountLabel": "账号",
            "passwordLabel": "密码",
        }
        for object_name, text in label_texts.items():
            label = page.findChild(QLabel, object_name)
            if label:
                label.setText(text)
        self.save_password_box.setText("保存密码")
        self.auto_login_box.setText("自动登录")
        self.auto_sign_box.setText("自动签到")
        self.login_btn.setText("登录")
        self.skip_login_btn.setText("游客进入")
        self.login_cookie_edit.setPlainText(load_cookie_header() or jmcomic_default_cookie_header())
        self.login_cookie_edit.hide()
        self.login_ua_edit.setText(DEFAULT_USER_AGENT)
        self.login_ua_edit.hide()
        self.login_btn.clicked.connect(self.login)
        self.skip_login_btn.clicked.connect(self.skip_login)
        return page

    def _build_login_page(self) -> QWidget:
        return self._load_login_page_from_ui()

    @staticmethod
    def normalize_history_records(items) -> List[Dict[str, object]]:
        records: List[Dict[str, object]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            record = dict(item)
            for key in (
                "title",
                "file",
                "path",
                "pdf_path",
                "image_dir",
                "album_id",
                "cover_url",
                "format",
                "created_at",
                "last_page",
                "last_total",
                "last_source",
                "last_read_at",
                "managed",
                "sort_order",
            ):
                fallback = item.get("id") if key == "album_id" else ""
                record[key] = str(item.get(key) or fallback or "")
            record["outputs"] = [
                str(path)
                for path in (item.get("outputs") or [])
                if str(path).strip()
            ]
            records.append(record)
        return records

    @staticmethod
    def album_to_dict(album: AlbumMeta) -> Dict:
        return {
            "album_id": album.album_id,
            "title": album.title,
            "url": album.url,
            "likes": album.likes,
            "favorites": album.favorites,
            "source": album.source,
            "cover_url": album.cover_url,
            "author": album.author,
            "page_count": album.page_count,
            "description": album.description,
            "views": album.views,
            "comment_count": album.comment_count,
            "is_favorite": album.is_favorite,
            "tags": list(album.tags),
            "selected_chapter_ids": list(album.selected_chapter_ids),
            "chapters": [
                {
                    "chapter_id": chapter.chapter_id,
                    "title": chapter.title,
                    "url": chapter.url,
                    "index": chapter.index,
                }
                for chapter in album.chapters
            ],
        }

    @staticmethod
    def album_from_dict(data: Dict) -> AlbumMeta:
        favorite_value = data.get("is_favorite")
        is_favorite = (
            favorite_value.strip().lower() in {"1", "true", "yes", "on"}
            if isinstance(favorite_value, str)
            else bool(favorite_value)
        )
        return AlbumMeta(
            album_id=str(data.get("album_id") or ""),
            title=str(data.get("title") or ""),
            url=str(data.get("url") or ""),
            likes=str(data.get("likes") or "-"),
            favorites=str(data.get("favorites") or "-"),
            source=str(data.get("source") or "缓存"),
            cover_url=str(data.get("cover_url") or ""),
            author=str(data.get("author") or "-"),
            page_count=str(data.get("page_count") or "-"),
            description=str(data.get("description") or ""),
            views=str(data.get("views") or "-"),
            comment_count=str(data.get("comment_count") or "0"),
            is_favorite=is_favorite,
            tags=list(data.get("tags") or []),
            selected_chapter_ids=list(data.get("selected_chapter_ids") or []),
            chapters=[
                ChapterMeta(
                    chapter_id=str(item.get("chapter_id") or ""),
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    index=int(item.get("index") or 1),
                )
                for item in (data.get("chapters") or [])
                if isinstance(item, dict)
            ],
        )

    def _center_window(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geometry = self.frameGeometry()
        geometry.moveCenter(screen.availableGeometry().center())
        self.move(geometry.topLeft())

    def _resize_to_available(self, desired_width: int, desired_height: int):
        screen = QApplication.primaryScreen()
        if not screen:
            self.resize(desired_width, desired_height)
            return
        available = screen.availableGeometry()
        width = min(desired_width, max(760, available.width() - 80))
        height = min(desired_height, max(520, available.height() - 80))
        self.resize(width, height)

    def _fade_in(self, widget: QWidget, duration: int = 240):
        self.animate_enter(widget, duration)

    def animate_enter(self, widget: QWidget, duration: int = 260, offset_y: int = 18, scale_px: int = 8):
        if not widget:
            return
        try:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            end_pos = widget.pos()
        except RuntimeError:
            return
        start_pos = end_pos + QPoint(0, offset_y)
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(duration)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        slide = QPropertyAnimation(widget, b"pos", self)
        slide.setDuration(duration)
        slide.setStartValue(start_pos)
        slide.setEndValue(end_pos)
        slide.setEasingCurve(QEasingCurve.OutCubic)

        first = QParallelAnimationGroup(self)
        first.addAnimation(fade)
        first.addAnimation(slide)

        end_geo = widget.geometry()
        start_geo = QRect(
            end_geo.x() + scale_px,
            end_geo.y() + scale_px,
            max(1, end_geo.width() - scale_px * 2),
            max(1, end_geo.height() - scale_px * 2),
        )
        pop = QPropertyAnimation(widget, b"geometry", self)
        pop.setDuration(150)
        pop.setStartValue(start_geo)
        pop.setEndValue(end_geo)
        pop.setEasingCurve(QEasingCurve.OutBack)

        sequence = QSequentialAnimationGroup(self)
        sequence.addAnimation(first)
        sequence.addAnimation(pop)
        sequence.finished.connect(lambda widget=widget: self.finish_widget_animation(widget))
        sequence.finished.connect(lambda: self.active_animations.remove(sequence) if sequence in self.active_animations else None)
        self.active_animations.append(sequence)
        self.page_animation = sequence
        sequence.start()

    @staticmethod
    def finish_widget_animation(widget: QWidget):
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass

    def animate_window_enter(self, window: QWidget, duration: int = 260):
        if not window:
            return
        end_geo = window.geometry()
        start_geo = QRect(
            end_geo.x(),
            end_geo.y() + 22,
            max(1, end_geo.width() - 14),
            max(1, end_geo.height() - 14),
        )
        start_geo.moveCenter(end_geo.center() + QPoint(0, 10))
        window.setWindowOpacity(0.0)
        window.setGeometry(start_geo)

        fade = QPropertyAnimation(window, b"windowOpacity", self)
        fade.setDuration(duration)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        move = QPropertyAnimation(window, b"geometry", self)
        move.setDuration(duration)
        move.setStartValue(start_geo)
        move.setEndValue(end_geo)
        move.setEasingCurve(QEasingCurve.OutBack)

        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(move)
        group.finished.connect(lambda: self.active_animations.remove(group) if group in self.active_animations else None)
        self.active_animations.append(group)
        group.start()

    def load_ui_widget(self, template_name: str, expected_type=None, parent: Optional[QWidget] = None):
        path = ui_dir() / template_name
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open {template_name}: {path}")
        try:
            widget = QUiLoader().load(ui_file, parent if parent is not None else self)
        finally:
            ui_file.close()
        if widget is None:
            raise RuntimeError(f"Unable to load {template_name}: {path}")
        if expected_type is not None and not isinstance(widget, expected_type):
            raise RuntimeError(f"{template_name} root widget type mismatch")
        return widget

    def create_empty_state_label(self, text: str, padding: int = 16) -> QLabel:
        label = self.load_ui_widget("empty_state.ui", QLabel)
        label.setText(text)
        label.setStyleSheet(f"color:#64748b;padding:{padding}px 4px;")
        return label

    def create_tag_badge(self, text: str, compact: bool = True) -> QLabel:
        badge = self.load_ui_widget("tag_badge.ui", QLabel)
        badge.setText(text)
        badge.setAlignment(Qt.AlignCenter)
        badge.setProperty("compactBadge", bool(compact))
        badge.setFixedHeight(18 if compact else 28)
        badge.setStyleSheet(self.tag_badge_style(compact))
        return badge

    def tag_badge_style(self, compact: bool = True) -> str:
        dark = bool(getattr(self, "theme_dark", False))
        return (
            f"background:{'#3b2a20' if dark else ('#fff7ed' if compact else '#fff4e8')};"
            f"border:1px solid {'#a95c24' if dark else '#ff7a00'};"
            f"border-radius:{9 if compact else 14}px;"
            f"color:{'#ff9a4a' if dark else '#d65f00'};"
            f"font-size:{10 if compact else 12}px;font-weight:800;"
            f"padding:0 {6 if compact else 12}px;"
        )

    def create_notice_label(self, message: str, parent: Optional[QWidget] = None) -> QLabel:
        notice = self.load_ui_widget("notice_label.ui", QLabel, parent)
        notice.setText(message)
        notice.setAlignment(Qt.AlignCenter)
        return notice

    def show_floating_notice(self, message: str):
        notice = self.create_notice_label(message, self)
        notice.setObjectName("floatingNotice")
        notice.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        notice.setStyleSheet(
            """
            QLabel#floatingNotice {
                background:rgba(15, 23, 42, 230);
                color:#ffffff;
                border-radius:14px;
                padding:10px 18px;
                font-size:13px;
                font-weight:700;
            }
            """
        )
        max_width = max(260, min(520, self.width() - 48))
        notice.setWordWrap(True)
        notice.setFixedWidth(max_width)
        notice.adjustSize()
        notice.setFixedHeight(max(44, notice.sizeHint().height() + 12))

        end_pos = QPoint(
            max(24, (self.width() - notice.width()) // 2),
            max(24, self.height() - notice.height() - 42),
        )
        start_pos = end_pos + QPoint(0, 18)
        notice.move(start_pos)
        notice.show()
        notice.raise_()

        effect = QGraphicsOpacityEffect(notice)
        notice.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        fade_in = QPropertyAnimation(effect, b"opacity", self)
        fade_in.setDuration(180)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)

        move_in = QPropertyAnimation(notice, b"pos", self)
        move_in.setDuration(220)
        move_in.setStartValue(start_pos)
        move_in.setEndValue(end_pos)
        move_in.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(fade_in)
        group.addAnimation(move_in)
        group.finished.connect(lambda: self.active_animations.remove(group) if group in self.active_animations else None)
        self.active_animations.append(group)
        group.start()

        def close_notice():
            try:
                if notice.parent() is None:
                    return
                fade_out = QPropertyAnimation(effect, b"opacity", self)
                fade_out.setDuration(180)
                fade_out.setStartValue(effect.opacity())
                fade_out.setEndValue(0.0)
                fade_out.setEasingCurve(QEasingCurve.InCubic)
                fade_out.finished.connect(lambda: notice.deleteLater())
                fade_out.finished.connect(lambda: self.active_animations.remove(fade_out) if fade_out in self.active_animations else None)
                self.active_animations.append(fade_out)
                fade_out.start()
            except RuntimeError:
                pass

        QTimer.singleShot(1800, close_notice)

    def hide_to_lower_left(self):
        if not self.isVisible():
            return
        self.hide()

    def show_corner_floating_notice(self, message: str, duration_ms: int = 2400):
        notice = self.create_notice_label(message, None)
        notice.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        notice.setAttribute(Qt.WA_TranslucentBackground, True)
        notice.setStyleSheet(
            """
            QLabel {
                background:rgba(15, 23, 42, 232);
                color:#ffffff;
                border-radius:12px;
                padding:10px 16px;
                font-size:13px;
                font-weight:800;
            }
            """
        )
        notice.adjustSize()
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect(0, 0, 1024, 768)
        width = min(max(notice.sizeHint().width(), 260), 460)
        height = max(44, notice.sizeHint().height())
        notice.setFixedSize(width, height)
        notice.move(available.left() + 18, available.bottom() - height - 18)
        notice.show()
        self.corner_notices.append(notice)
        QTimer.singleShot(duration_ms, lambda n=notice: self.close_corner_notice(n))

    def close_corner_notice(self, notice: QLabel):
        if notice in self.corner_notices:
            self.corner_notices.remove(notice)
        notice.hide()
        notice.deleteLater()

    def enter_app(self, username: str = "", password: str = "", cookie: str = ""):
        self.session_username = username
        self.session_password = password
        if cookie:
            self.cookie_edit.setPlainText(cookie)
        if self.login_ua_edit.text().strip():
            self.ua_edit.setText(self.login_ua_edit.text().strip())
        self.user_label.setText(f"当前用户：{username or '游客模式'}")
        self.settings_cache = self.current_settings_snapshot()
        self.save_local_cache()
        self.setMinimumSize(920, 640)
        self._resize_to_available(1180, 760)
        self.update_header_profile()
        self.stack.setCurrentWidget(self.app_page)
        self.showMaximized()
        self._fade_in(self.app_page, 320)
        self.set_backend_status("准备加载首页", "busy")
        QTimer.singleShot(100, self.refresh_domain_pool)
        self.start_incremental_timer()
        if not self.home_auto_loaded:
            self.home_auto_loaded = True
            QTimer.singleShot(650, self.auto_load_home_page)

    def start_incremental_timer(self):
        if self.incremental_timer is not None:
            return
        self.incremental_timer = QTimer(self)
        self.incremental_timer.setInterval(30 * 60 * 1000)
        self.incremental_timer.timeout.connect(self.run_silent_incremental_update)
        self.incremental_timer.start()

    def run_silent_incremental_update(self):
        if self.is_busy() or (self.incremental_worker and self.incremental_worker.isRunning()):
            return
        self.start_incremental_update(silent=True)

    def refresh_domain_pool(self):
        if self.domain_worker and self.domain_worker.isRunning():
            return
        self.domain_worker = DomainRefreshWorker(self)
        self.domain_worker.log.connect(self.log)
        self.domain_worker.domains_ready.connect(self.on_domain_pool_refreshed)
        self.domain_worker.finished.connect(
            lambda worker=self.domain_worker: self.cleanup_domain_worker(worker)
        )
        self.domain_worker.start()

    def cleanup_domain_worker(self, worker: DomainRefreshWorker):
        if worker is self.domain_worker:
            self.domain_worker = None
        worker.deleteLater()

    def on_domain_pool_refreshed(self, domains: List[str]):
        self.api_domain_pool = dedupe_domains(domains + self.api_domain_pool)
        self.save_local_cache()

    def auto_load_home_page(self):
        if self.stack.currentWidget() is not self.app_page:
            return
        if self.is_loading_busy() or self.result_total_count > 0:
            return
        self.id_edit.clear()
        self.search_edit.clear()
        self.active_category = ""
        self.home_feed_mode = "latest"
        self.home_category_key = "latest"
        self.home_category_prefix = ""
        self.update_home_category_buttons()
        if hasattr(self, "rank_group"):
            checked = self.rank_group.checkedButton()
            if checked:
                self.rank_group.setExclusive(False)
                checked.setChecked(False)
                self.rank_group.setExclusive(True)
        self.list_url_edit.setText(LIST_URL)
        self.log("自动进入首页最新上传：App API /latest")
        self.open_latest_home()

    def set_backend_status(self, text: str, state: str = "idle"):
        if not hasattr(self, "backend_label"):
            return
        styles = {
            "ok": "color:#16a34a;background:#e9fbe9;",
            "busy": "color:#2563eb;background:#eaf2ff;",
            "warn": "color:#b45309;background:#fff7ed;",
            "error": "color:#dc2626;background:#fef2f2;",
            "idle": "color:#64748b;background:#f1f5f9;",
        }
        self.backend_label.setText(text)
        self.backend_label.setStyleSheet(
            styles.get(state, styles["idle"]) + "border-radius:12px;padding:4px 10px;"
        )

    def show_login_loading(self, message: str, callback):
        self.login_user_edit.setEnabled(False)
        self.login_pass_edit.setEnabled(False)
        self.login_cookie_edit.setEnabled(False)
        self.login_ua_edit.setEnabled(False)
        self.statusBar().showMessage(message)
        QTimer.singleShot(420, lambda: self._finish_login_loading(callback))

    def _finish_login_loading(self, callback):
        self.login_user_edit.setEnabled(True)
        self.login_pass_edit.setEnabled(True)
        self.login_cookie_edit.setEnabled(True)
        self.login_ua_edit.setEnabled(True)
        callback()

    def start_loading(self, message: str):
        self.loading_tick = 0
        if hasattr(self, "result_loading_text") and "漫画" in message:
            self.show_home_initial_loading(message)
        if self.loading_timer:
            self.loading_timer.stop()
        self.loading_timer = QTimer(self)
        self.loading_timer.timeout.connect(lambda: self._tick_loading(message))
        self.loading_timer.start(360)

    def _tick_loading(self, message: str):
        self.loading_tick = (self.loading_tick + 1) % 4
        if hasattr(self, "result_loading_text") and self.result_stack.currentWidget() is self.result_loading_page:
            self.result_loading_text.setText(message + "." * self.loading_tick)

    def stop_loading(self):
        if self.loading_timer:
            self.loading_timer.stop()
            self.loading_timer = None

    def apply_loading_movie(self, label: QLabel, size: QSize):
        if LOADING_MOVIE_PATH.exists():
            movie = QMovie(str(LOADING_MOVIE_PATH))
            movie.setScaledSize(size)
            label.setMovie(movie)
            label._loading_movie = movie
            movie.start()
            return
        label.setText("加载中")
    @staticmethod
    def stop_label_movie(label: QLabel):
        try:
            movie = getattr(label, "_loading_movie", None)
            if movie:
                movie.stop()
                label._loading_movie = None
        except RuntimeError:
            pass

    def setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search_box)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.focus_id_box)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.quick_start_download)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.quick_start_download)
        if hasattr(self, "search_edit"):
            self.search_edit.returnPressed.connect(self.start_scrape)
        if hasattr(self, "id_edit"):
            self.id_edit.returnPressed.connect(self.start_scrape)

    def focus_search_box(self):
        self.category_rank_page_lock = False
        self.switch_page(self.home_page_index())
        self.search_edit.setFocus(Qt.ShortcutFocusReason)
        self.search_edit.selectAll()

    def focus_id_box(self):
        self.category_rank_page_lock = False
        self.switch_page(self.home_page_index())
        self.id_edit.setFocus(Qt.ShortcutFocusReason)
        self.id_edit.selectAll()

    def _build_app_page(self) -> QWidget:
        path = ui_dir() / "app.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open app form: {path}")
        try:
            page = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if page is None:
            raise RuntimeError(f"Unable to load app form: {path}")
        header_layout = page.findChild(QVBoxLayout, "dashboardHeaderContainerLayout")
        navigation_layout = page.findChild(QVBoxLayout, "navigationContainerLayout")
        navigation_container = page.findChild(QWidget, "navigationContainer")
        header_container = page.findChild(QWidget, "dashboardHeaderContainer")
        content_layout = page.findChild(QHBoxLayout, "dashboardContentLayout")
        self.main_content_stack = page.findChild(QStackedWidget, "mainContentStack")
        if not all((header_layout, navigation_layout, header_container, content_layout, self.main_content_stack)):
            raise RuntimeError("App form is missing dashboard containers")
        # The header belongs to the content column.  This lets the sidebar
        # start at the top while the menu breadcrumb begins beside it.
        root_layout = page.findChild(QVBoxLayout, "appRootLayout")
        if root_layout is not None:
            root_layout.removeWidget(header_container)
        content_layout.removeWidget(self.main_content_stack)
        content_column = QWidget(page)
        content_column.setObjectName("dashboardContentColumn")
        self.dashboard_content_column = content_column
        content_column.setMinimumWidth(0)
        content_column.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        content_column_layout = QVBoxLayout(content_column)
        content_column_layout.setContentsMargins(0, 0, 0, 0)
        content_column_layout.setSpacing(6)
        content_column_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        header_container.setParent(content_column)
        header_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.main_content_stack.setParent(content_column)
        content_column_layout.addWidget(header_container)
        content_column_layout.addWidget(self.main_content_stack, 1)
        content_layout.insertWidget(1, content_column, 1)
        if navigation_container is not None:
            self.navigation_container = navigation_container
            self.navigation_toggle_animation = None
            navigation_container.setMinimumWidth(NAVIGATION_PANEL_WIDTH)
            navigation_container.setMaximumWidth(NAVIGATION_PANEL_WIDTH)
            navigation_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        content_layout.setStretch(0, 0)
        content_layout.setStretch(1, 1)
        content_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.main_content_stack.setMinimumWidth(0)
        self.main_content_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        header_layout.addWidget(self._build_dashboard_header())
        navigation_layout.addWidget(self._build_navigation_panel())
        self.main_content_stack.addWidget(self._build_home_workspace())
        self.main_content_stack.addWidget(self._build_download_panel())
        self.main_content_stack.addWidget(self._build_settings_panel())
        self.main_content_stack.addWidget(self._build_history_panel())
        self.main_content_stack.addWidget(self._build_about_panel())
        self.main_content_stack.addWidget(self._build_profile_panel())
        self.main_content_stack.addWidget(self._build_detail_panel())
        self.main_content_stack.addWidget(self._build_library_panel())
        self.main_content_stack.addWidget(self._build_category_rank_panel())
        self.main_content_stack.addWidget(self._build_weekly_panel())
        self.main_content_stack.addWidget(self._build_local_download_panel())
        self.main_content_stack.addWidget(self._build_search_workspace())
        self.main_content_stack.currentChanged.connect(
            lambda _index: self.schedule_breadcrumb_update()
        )
        self.schedule_breadcrumb_update()
        return page

    def _build_navigation_panel(self) -> QFrame:
        path = ui_dir() / "navigation.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open navigation form: {path}")
        panel = QUiLoader().load(ui_file, self)
        ui_file.close()
        if panel is None:
            raise RuntimeError(f"Unable to load navigation form: {path}")
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        self.user_label = panel.findChild(QLabel, "headerUserLabel")
        self.user_role_label = panel.findChild(QLabel, "headerUserRoleLabel")
        self.avatar_button = panel.findChild(QPushButton, "profileAvatarButton")
        self.header_account_menu = panel.findChild(QFrame, "headerAccountMenu")
        self.header_account_arrow_button = panel.findChild(QPushButton, "headerAccountArrowButton")
        self.nav_category_rank_button = panel.findChild(QPushButton, "navCategoryRankButton")
        self.nav_weekly_button = panel.findChild(QPushButton, "navWeeklyButton")
        page_items = [
            ("navHomeButton", "首页", self.home_page_index(), "home"),
            ("navDownloadButton", "下载管理", self.downloading_page_index(), "download"),
            ("navHistoryButton", "本地记录", self.history_page_index(), "history"),
            ("navLocalDownloadButton", "本地下载", self.local_download_page_index(), "download"),
            ("navSettingsButton", "设置", self.settings_page_index(), "settings"),
            ("navAboutButton", "帮助", self.about_page_index(), "about"),
        ]
        library_items = [
            ("navFavoriteButton", "我的收藏", "favoritesTab", "history"),
            ("navLocalFavoriteButton", "本地收藏", "localTab", "history"),
            ("navRemoteHistoryButton", "我的阅读", "remoteHistoryTab", "history"),
            ("navCommentButton", "我的评论", "commentsTab", "history"),
        ]

        def find_nav_button(object_name: str, text: str) -> Optional[QPushButton]:
            button = panel.findChild(QPushButton, object_name)
            if button is not None:
                return button
            return next((item for item in panel.findChildren(QPushButton) if item.text() == text), None)

        for object_name, text, index, icon_name in page_items:
            button = find_nav_button(object_name, text)
            if button is None:
                raise RuntimeError(f"Navigation form is missing {object_name}")
            button.setProperty("navRole", "item")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, index=index: (
                    self.open_latest_home()
                    if index == self.home_page_index()
                    else self.open_local_download_page()
                    if index == self.local_download_page_index()
                    else self.switch_page(index)
                )
            )
            self.nav_group.addButton(button)
            self.nav_buttons[index] = button
        for object_name, text, tab_name, icon_name in library_items:
            button = find_nav_button(object_name, text)
            if button is None:
                raise RuntimeError(f"Navigation form is missing {object_name}")
            button.setProperty("navRole", "item")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, tab_name=tab_name, button=button: self.open_library_tab(tab_name, button))
            self.nav_group.addButton(button)
        if self.nav_category_rank_button is None:
            raise RuntimeError("Navigation form is missing category and rank control")
        self.nav_category_rank_button.setProperty("navRole", "item")
        self.nav_category_rank_button.setCursor(Qt.PointingHandCursor)
        self.nav_category_rank_button.setCheckable(True)
        self.nav_category_rank_button.clicked.connect(self.open_category_rank_page)
        self.nav_group.addButton(self.nav_category_rank_button)
        self.nav_buttons[self.category_rank_page_index()] = self.nav_category_rank_button
        if self.nav_weekly_button is None:
            raise RuntimeError("Navigation form is missing weekly control")
        self.nav_weekly_button.setProperty("navRole", "item")
        self.nav_weekly_button.setCursor(Qt.PointingHandCursor)
        self.nav_weekly_button.setCheckable(True)
        self.nav_weekly_button.clicked.connect(self.open_weekly_page)
        self.nav_group.addButton(self.nav_weekly_button)
        self.nav_buttons[self.weekly_page_index()] = self.nav_weekly_button
        account_controls = (
            self.user_label,
            self.user_role_label,
            self.avatar_button,
            self.header_account_menu,
            self.header_account_arrow_button,
        )
        if any(control is None for control in account_controls):
            raise RuntimeError("Navigation form is missing account controls")
        self.user_label.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.user_label.setMinimumWidth(0)
        self.user_label.setMaximumWidth(100)
        self.user_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.user_label.setCursor(Qt.PointingHandCursor)
        self.user_label.setToolTip("账户菜单")
        self.user_label.installEventFilter(self)
        self.user_role_label.setMaximumWidth(100)
        self.avatar_button.setObjectName("profileAvatarButton")
        self.avatar_button.setFixedSize(36, 36)
        self.avatar_button.setCursor(Qt.PointingHandCursor)
        self.avatar_button.clicked.connect(self.open_profile_page)
        self.header_account_arrow_button.clicked.connect(self.show_header_account_menu)
        connection_card = panel.findChild(QFrame, "connectionCard")
        if connection_card is not None:
            connection_card.hide()
        self.apply_navigation_visual_system(panel)
        self.setup_appearance_controls(panel)
        self.nav_buttons[self.home_page_index()].setChecked(True)
        return panel

    def search_from_navigation(self):
        query = self.nav_search_edit.text().strip() if hasattr(self, "nav_search_edit") else ""
        if not query:
            if hasattr(self, "nav_search_edit"):
                self.nav_search_edit.setFocus(Qt.ShortcutFocusReason)
            self.show_toast("请输入搜索关键词", 1400)
            return
        self.open_search_results(query)

    def open_category_rank_page(self):
        self.switch_page(self.category_rank_page_index())
        if (
            hasattr(self, "category_rank_stack")
            and self.category_rank_stack.currentWidget() is getattr(self, "category_rank_results_page", None)
        ):
            self.activate_result_surface("category")

    def open_navigation_category(self, category: str, label: str):
        self.category_rank_page_lock = False
        self.deactivate_home_search_results()
        self.switch_page(self.home_page_index())
        home_button = getattr(self, "nav_buttons", {}).get(self.home_page_index())
        if home_button is not None:
            home_button.setChecked(True)
        self.start_category_filter(category, label)

    def open_navigation_rank(self, rank_type: str):
        self.category_rank_page_lock = False
        self.deactivate_home_search_results()
        self.switch_page(self.home_page_index())
        home_button = getattr(self, "nav_buttons", {}).get(self.home_page_index())
        if home_button is not None:
            home_button.setChecked(True)
        self.start_rank_scrape(rank_type)

    def open_search_results(self, query: str, *, preserve_path: bool = False):
        query = str(query).strip()
        if not query:
            return
        if (
            preserve_path
            and self.main_content_stack.currentIndex() == self.detail_page_index()
        ):
            current_detail = self.current_album()
            if current_detail is not None:
                self.detail_cache[current_detail.album_id] = copy.deepcopy(current_detail)
            self.remember_home_before_detail_search()
        self.category_rank_page_lock = False
        opened_from_category = (
            self.main_content_stack.currentIndex() == self.category_rank_page_index()
        )
        self.activate_home_search_results(query)
        self.switch_page(
            self.search_page_index(),
            preserve_path=preserve_path or opened_from_category,
            breadcrumb_title="搜索",
        )
        home_button = getattr(self, "nav_buttons", {}).get(self.home_page_index())
        if home_button is not None:
            home_button.setChecked(True)
        self.start_category_search(query)

    def _build_category_rank_panel(self) -> QFrame:
        panel = self.load_ui_widget("category_rank.ui", QFrame)
        self.category_rank_stack = panel.findChild(QStackedWidget, "categoryRankContentStack")
        tag_page = panel.findChild(QWidget, "categoryRankTagPage")
        self.category_rank_results_page = panel.findChild(QWidget, "categoryRankResultsPage")
        self.category_rank_results_layout = panel.findChild(QVBoxLayout, "categoryRankResultsLayout")
        if (
            self.category_rank_stack is None
            or tag_page is None
            or self.category_rank_results_page is None
            or self.category_rank_results_layout is None
        ):
            raise RuntimeError("category_rank.ui is missing page controls")
        for label_name in (
            "categoryRankThemeTitle",
            "categoryRankRoleTitle",
            "categoryRankPlayTitle",
            "categoryRankOtherTitle",
        ):
            label = panel.findChild(QLabel, label_name)
            if label is None:
                raise RuntimeError(f"category_rank.ui is missing {label_name}")
            label.setProperty("categoryRankSectionTitle", True)

        overview_button = panel.findChild(QPushButton, "categoryRankOverviewButton")
        if overview_button is None:
            raise RuntimeError("category_rank.ui is missing overview controls")
        self.category_rank_view_group = QButtonGroup(panel)
        self.category_rank_view_group.setExclusive(True)
        overview_button.setProperty("categoryRankNavOption", True)
        overview_button.setCheckable(True)
        overview_button.setCursor(Qt.PointingHandCursor)
        overview_button.clicked.connect(self.show_category_rank_overview)
        self.category_rank_view_group.addButton(overview_button)
        overview_button.setChecked(True)

        category_buttons = {
            "categoryRankAllButton": ("0", "最新A漫"),
            "categoryRankDoujinButton": ("doujin", "同人"),
            "categoryRankSingleButton": ("single", "单本"),
            "categoryRankShortButton": ("short", "短篇"),
            "categoryRankOtherButton": ("another", "其他类"),
            "categoryRankHanmanButton": ("hanman", "韩漫"),
            "categoryRankEnglishButton": ("english_site", "ENGLISH MANGA"),
            "categoryRankGeneralHanmanButton": ("hanman_general", "一般向韩漫"),
            "categoryRank3dButton": ("3D", "3D"),
            "categoryRankCosplayButton": ("doujin_cosplay", "Cosplay"),
            "categoryRankTranslatedButton": ("translated", "禁漫汉化组"),
        }
        for object_name, (category, label) in category_buttons.items():
            button = panel.findChild(QPushButton, object_name)
            if button is None:
                raise RuntimeError(f"category_rank.ui is missing {object_name}")
            button.setProperty("categoryRankNavOption", True)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, category=category, label=label: self.show_category_rank_results(category, label)
            )
            self.category_rank_view_group.addButton(button)

        tag_sections = {
            "categoryRankThemeGrid": ("剧情向", "校园", "纯爱", "人妻", "师生", "近亲", "百合", "YAOI", "性转", "NTR", "伪娘", "痴女", "全彩", "女性向"),
            "categoryRankRoleGrid": ("萝莉", "御姐", "熟女", "正太", "巨乳", "贫乳", "女王", "教师", "女仆", "护士", "泳装", "眼镜", "连裤袜", "其他制服", "兔女郎"),
            "categoryRankPlayGrid": ("群交", "足交", "SM", "肛交", "阿黑颜", "药物", "扶他", "调教", "野外露出", "催眠", "自慰", "触手", "兽交"),
            "categoryRankTagOtherGrid": ("CG集", "重口", "猎奇", "非H", "血腥暴力"),
        }
        for layout_name, tags in tag_sections.items():
            layout = panel.findChild(QGridLayout, layout_name)
            if layout is None:
                raise RuntimeError(f"category_rank.ui is missing {layout_name}")
            self._add_category_rank_tags(layout, tags)

        category_result_stack = QStackedWidget(self.category_rank_results_page)
        category_result_stack.setObjectName("categoryResultStack")
        category_loading_page = QWidget(category_result_stack)
        category_loading_page.setObjectName("categoryResultLoadingPage")
        category_loading_layout = QVBoxLayout(category_loading_page)
        category_loading_layout.addStretch(1)
        category_loading_art = QLabel(category_loading_page)
        category_loading_art.setObjectName("categoryResultLoadingArt")
        category_loading_art.setFixedSize(150, 118)
        category_loading_art.setAlignment(Qt.AlignCenter)
        category_loading_layout.addWidget(category_loading_art, 0, Qt.AlignHCenter)
        category_loading_text = QLabel("正在加载漫画资源", category_loading_page)
        category_loading_text.setObjectName("categoryResultLoadingText")
        category_loading_text.setAlignment(Qt.AlignCenter)
        category_loading_layout.addWidget(category_loading_text, 0, Qt.AlignHCenter)
        category_loading_layout.addStretch(1)
        category_result_scroll = self._create_home_result_list(category_result_stack)
        category_result_stack.addWidget(category_loading_page)
        category_result_stack.addWidget(category_result_scroll)
        category_result_stack.setCurrentWidget(category_result_scroll)
        self.category_rank_results_layout.addWidget(category_result_stack)
        self.apply_detail_loading_movie(category_loading_art, QSize(150, 118))

        self.result_surfaces = {
            "home": {
                "stack": self.result_stack,
                "loading_page": self.result_loading_page,
                "loading_text": self.result_loading_text,
                "loading_art": self.result_loading_art,
                "scroll": self.result_scroll,
                "active_key": self.home_active_result_view_key,
            },
            "category": {
                "stack": category_result_stack,
                "loading_page": category_loading_page,
                "loading_text": category_loading_text,
                "loading_art": category_loading_art,
                "scroll": category_result_scroll,
                "active_key": "",
            },
        }
        self.active_result_surface = "home"

        return panel

    def move_result_stack_to_category_page(self) -> None:
        self.activate_result_surface("category")

    def restore_result_stack_to_home(self) -> None:
        self.activate_result_surface("home")

    def activate_result_surface(self, surface_name: str) -> None:
        surfaces = getattr(self, "result_surfaces", {})
        target = surfaces.get(surface_name)
        if target is None or getattr(self, "active_result_surface", "home") == surface_name:
            return

        current = surfaces.get(self.active_result_surface)
        if current is not None:
            if self.home_active_result_view_key:
                self._capture_home_result_view()
            current["scroll"] = self.result_scroll
            current["active_key"] = self.home_active_result_view_key

        self.result_stack = target["stack"]
        self.result_loading_page = target["loading_page"]
        self.result_loading_text = target["loading_text"]
        self.result_loading_art = target["loading_art"]
        self.result_scroll = target["scroll"]
        self.result_grid_widget = self.result_scroll.viewport()
        self.result_grid = None
        self.home_active_result_view_key = str(target.get("active_key") or "")
        state = self.home_result_views.get(self.home_active_result_view_key)
        if state is not None and state.get("scroll") is not None:
            self.result_scroll = state["scroll"]
            target["scroll"] = self.result_scroll
            self.result_grid_widget = self.result_scroll.viewport()
            self.card_by_id = state["card_by_id"]
            self.checkmark_by_id = state["checkmark_by_id"]
            self.result_cover_labels = state["cover_labels"]
            self.result_cover_requested = state["cover_requested"]
            self.result_render_limit = state["render_limit"]
            self.results_revealed = state["revealed"]
            cached_albums = list(self.result_cache.get(self.home_active_result_view_key, []))
            self.result_albums = cached_albums
            self.result_total_count = len(cached_albums)
            self.result_album_indices = {
                album.album_id: index for index, album in enumerate(cached_albums)
            }
            self.albums = {album.album_id: album for album in cached_albums}
        else:
            self.card_by_id = {}
            self.checkmark_by_id = {}
            self.result_cover_labels = {}
            self.result_cover_requested = set()
            self.result_render_limit = 0
            self.results_revealed = False
            self.result_albums = []
            self.result_total_count = 0
            self.result_album_indices = {}
            self.albums = {}
        self.result_stack.setCurrentWidget(self.result_scroll)
        self.active_result_surface = surface_name

    def show_category_rank_overview(self) -> None:
        self.category_rank_stack.setCurrentIndex(0)

    def show_category_rank_results(self, category: str, label: str) -> None:
        self.category_rank_page_lock = True
        self.home_search_mode = False
        self.search_result_toolbar.hide()
        self.move_result_stack_to_category_page()
        self.category_rank_stack.setCurrentWidget(self.category_rank_results_page)
        self.start_category_filter(category, label)

    def keeps_category_rank_results_visible(self) -> bool:
        return (
            hasattr(self, "main_content_stack")
            and self.main_content_stack.currentIndex() == self.category_rank_page_index()
            and getattr(self, "category_rank_stack", None) is not None
            and self.category_rank_stack.currentWidget() is getattr(self, "category_rank_results_page", None)
            and getattr(self, "active_result_surface", "home") == "category"
        )

    def _add_category_rank_tags(self, layout: QGridLayout, tags) -> None:
        for index, tag in enumerate(tags):
            button = QPushButton(tag)
            button.setObjectName("categoryRankTagOption")
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _=False, tag=tag: self.open_search_results(tag))
            layout.addWidget(button, index // 6, index % 6)
        for column in range(6):
            layout.setColumnStretch(column, 1)

    def _build_profile_panel(self) -> QWidget:
        path = ui_dir() / "profile.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open profile.ui: {path}")
        try:
            page = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if page is None:
            raise RuntimeError(f"Unable to load profile.ui: {path}")

        self.profile_page = page
        self.profile_content_stack = page.findChild(QStackedWidget, "profileContentStack")
        self.profile_avatar_label = page.findChild(QLabel, "profileAvatarLabel")
        self.profile_name_label = page.findChild(QLabel, "profileNameLabel")
        self.profile_user_label = page.findChild(QLabel, "profileUserLabel")
        self.profile_title_label = page.findChild(QLabel, "profileTitleLabel")
        self.profile_level_label = page.findChild(QLabel, "profileLevelLabel")
        self.profile_favorite_label = page.findChild(QLabel, "profileFavoriteLabel")
        self.profile_favorite_count_label = page.findChild(QLabel, "profileFavoriteCountLabel")
        self.profile_favorite_summary_label = page.findChild(QLabel, "profileFavoriteSummaryLabel")
        self.profile_coin_label = page.findChild(QLabel, "profileCoinLabel")
        self.profile_exp_bar = page.findChild(QProgressBar, "profileExpBar")
        self.profile_exp_label = page.findChild(QLabel, "profileExpLabel")
        self.profile_sign_label = page.findChild(QLabel, "profileSignLabel")
        self.profile_uid_label = page.findChild(QLabel, "profileUidLabel")
        self.profile_status_label = page.findChild(QLabel, "profileStatusLabel")
        self.profile_task_list = page.findChild(QLabel, "profileTaskList")
        self.profile_favorite_layout = page.findChild(QHBoxLayout, "profileFavoriteStrip")
        self.profile_history_layout = page.findChild(QHBoxLayout, "profileHistoryStrip")
        profile_favorite_page_scroll = page.findChild(QScrollArea, "profileFavoritePageScroll")
        profile_history_page_scroll = page.findChild(QScrollArea, "profileHistoryPageScroll")
        self.profile_login_task_bar = page.findChild(QProgressBar, "profileLoginTaskBar")
        self.profile_login_task_value = page.findChild(QLabel, "profileLoginTaskValue")
        self.profile_daily_task_bar = page.findChild(QProgressBar, "profileDailyTaskBar")
        self.profile_daily_task_value = page.findChild(QLabel, "profileDailyTaskValue")
        self.profile_favorite_task_bar = page.findChild(QProgressBar, "profileFavoriteTaskBar")
        self.profile_favorite_task_value = page.findChild(QLabel, "profileFavoriteTaskValue")
        self.profile_nav_buttons = [
            page.findChild(QPushButton, "profileInfoNavButton"),
            page.findChild(QPushButton, "profileInboxNavButton"),
            page.findChild(QPushButton, "profileFavoriteNavButton"),
            page.findChild(QPushButton, "profileHistoryNavButton"),
        ]
        required = [
            self.profile_avatar_label,
            self.profile_name_label,
            self.profile_user_label,
            self.profile_content_stack,
            self.profile_favorite_layout,
            self.profile_history_layout,
            profile_favorite_page_scroll,
            profile_history_page_scroll,
        ]
        if any(widget is None for widget in required) or any(button is None for button in self.profile_nav_buttons):
            raise RuntimeError("profile.ui is missing required controls")

        self.profile_nav_group = QButtonGroup(page)
        self.profile_nav_group.setExclusive(True)
        for index, button in enumerate(self.profile_nav_buttons):
            button.setObjectName("profileNavButton")
            self.profile_nav_group.addButton(button, index)
            button.clicked.connect(lambda _checked=False, section=index: self.show_profile_section(section))

        self.bind_profile_page_actions(page)
        self.profile_favorite_page_view = self.create_profile_album_list(profile_favorite_page_scroll)
        self.profile_history_page_view = self.create_profile_album_list(profile_history_page_scroll)
        self.profile_section_albums = {2: [], 3: []}
        self.profile_section_render_keys = {2: None, 3: None}
        self.show_profile_section(0)
        self.update_profile_page()
        return page

    @staticmethod
    def _profile_text(value, fallback: str = "-") -> str:
        text = str(value if value is not None else "").strip()
        return text or fallback

    def _profile_settings(self) -> NetworkSettings:
        return NetworkSettings(
            cookie_header=self.login_cookie_edit.toPlainText().strip() if hasattr(self, "login_cookie_edit") else "",
            user_agent=self.login_ua_edit.text().strip() if hasattr(self, "login_ua_edit") else DEFAULT_USER_AGENT,
            delay_min=float(self.delay_min.value()) if hasattr(self, "delay_min") else 1.0,
            delay_max=float(self.delay_max.value()) if hasattr(self, "delay_max") else 3.0,
            retries=self.retries.value() if hasattr(self, "retries") else 3,
            backoff_seconds=self.backoff.value() if hasattr(self, "backoff") else 3,
            stop_on_block=self.stop_on_block.isChecked() if hasattr(self, "stop_on_block") else True,
            username=self.session_username or (self.login_user_edit.text().strip() if hasattr(self, "login_user_edit") else ""),
            password=self.session_password or (self.login_pass_edit.text() if hasattr(self, "login_pass_edit") else ""),
            proxy=self.effective_proxy() if hasattr(self, "proxy_mode_combo") else "",
            detail_threads=self.detail_threads.value() if hasattr(self, "detail_threads") else 6,
            auto_sign=self.auto_sign_box.isChecked() if hasattr(self, "auto_sign_box") else False,
            api_route=getattr(self, "api_route", 0),
            image_route=int(self.image_route_combo.currentData() or 0),
            doh_enabled=self.doh_enabled_box.isChecked(),
            doh_url=self.doh_url_edit.text().strip() or DOH_URL,
            custom_api_domain=self.custom_api_domain_edit.text().strip(),
            custom_image_domain=self.custom_image_domain_edit.text().strip(),
        )

    def update_profile_page(self):
        self.update_header_profile()
        if not hasattr(self, "profile_page"):
            return
        data = self.profile_data or {}
        user = data.get("user") or {}
        username = self._profile_text(data.get("username") or user.get("username") or self.session_username, "未登录")
        uid = self._profile_text(data.get("uid") or user.get("uid") or self.session_uid)
        level = self._profile_text(user.get("level"))
        level_name = self._profile_text(data.get("level_name") or user.get("level_name") or user.get("title"))
        coin = self._profile_text(user.get("coin"))
        favorites = self._profile_text(user.get("album_favorites") or user.get("favorites"))
        favorites_max = self._profile_text(user.get("album_favorites_max") or user.get("canFavorites"))
        exp = self._profile_int(user.get("exp"), 0)
        next_exp = self._profile_int(user.get("nextLevelExp") or user.get("nex_exp"), 0)
        signed = self._daily_signed_text(data.get("daily") or data.get("sign"))

        self._set_label(self.profile_name_label, username)
        self._set_label(self.profile_user_label, f"@{username}" if username != "未登录" else "@guest")
        self._set_label(self.profile_title_label, level_name)
        self._set_label(self.profile_level_label, f"LV {level}" if level != "-" else "LV -")
        self._set_label(self.profile_favorite_label, f"{favorites}/{favorites_max}")
        self._set_label(self.profile_favorite_count_label, f"\u6536\u85cf\u989d\u5ea6\uff1a{favorites}/{favorites_max}")
        self._set_label(self.profile_favorite_summary_label, f"可收藏数量：{favorites}/{favorites_max}")
        self._set_label(self.profile_coin_label, coin)
        self._set_label(self.profile_exp_label, f"经验 {exp}/{next_exp or '-'}")
        self._set_label(self.profile_sign_label, f"\u7b7e\u5230\u72b6\u6001\uff1a{signed}")
        self._set_label(self.profile_uid_label, f"UID {uid}")
        self._set_label(self.profile_status_label, "")
        if self.profile_avatar_label:
            if self.profile_avatar_pixmap is not None:
                self.set_cover_on_label(self.profile_avatar_label, self.profile_avatar_pixmap)
            else:
                self.profile_avatar_label.setText((username[0].upper() if username and username != "未登录" else "U"))
        if self.profile_exp_bar:
            self.profile_exp_bar.setValue(0 if next_exp <= 0 else max(0, min(100, int(exp * 100 / next_exp))))
        logged_in = bool(self.session_username or self.session_uid)
        signed_done = signed == "已签到"
        if self.profile_login_task_bar:
            self.profile_login_task_bar.setValue(1 if logged_in else 0)
        self._set_label(self.profile_login_task_value, "1/1" if logged_in else "0/1")
        if self.profile_daily_task_bar:
            self.profile_daily_task_bar.setValue(1 if signed_done else 0)
        self._set_label(self.profile_daily_task_value, "1/1" if signed_done else "0/1")
        favorite_count = self._profile_int(favorites, 0)
        favorite_limit = max(1, self._profile_int(favorites_max, 1))
        if self.profile_favorite_task_bar:
            self.profile_favorite_task_bar.setMaximum(favorite_limit)
            self.profile_favorite_task_bar.setValue(min(favorite_count, favorite_limit))
        self._set_label(self.profile_favorite_task_value, f"{favorites}/{favorites_max}")
        if self.profile_task_list:
            sign_progress = "1/1" if signed != "-" else "0/1"
            self.profile_task_list.setText(
                f"Daily login  1/1\nSign  {sign_progress}\nFavorites  {favorites}/{favorites_max}"
            )
        favorite_albums = [self.album_from_dict(item) for item in (data.get("favorites") or []) if isinstance(item, dict)]
        self.render_profile_album_strip(
            self.profile_favorite_layout,
            favorite_albums,
            "\u6682\u65e0\u6536\u85cf\u6f2b\u753b",
            "\u6536\u85cf\u6f2b\u753b",
            limit=6,
        )
        self.profile_section_albums[2] = favorite_albums
        history_albums = [self.album_from_dict(item) for item in (data.get("history") or []) if isinstance(item, dict)]
        if history_albums:
            self.render_profile_album_strip(self.profile_history_layout, history_albums, "暂无观看记录", "观看记录", limit=6)
            self.profile_section_albums[3] = history_albums
        else:
            local_history = self.profile_local_history_items()
            self.render_profile_album_strip(
                self.profile_history_layout,
                local_history,
                "暂无观看记录",
                "观看记录",
                limit=6,
            )
            self.profile_section_albums[3] = local_history
        current_section = self.profile_content_stack.currentIndex() if self.profile_content_stack else 0
        if current_section in (2, 3):
            self.render_profile_section_preview(current_section)

    def render_profile_section_preview(self, section: int):
        if section not in (2, 3):
            return
        albums = self.profile_section_albums.get(section, [])
        album_ids = []
        for entry in albums[:12]:
            album = entry[0] if isinstance(entry, tuple) else entry
            album_ids.append(getattr(album, "album_id", ""))
        render_key = tuple(album_ids)
        if self.profile_section_render_keys.get(section) == render_key:
            return
        self.profile_section_render_keys[section] = render_key
        if section == 2:
            self.render_profile_album_grid(
                self.profile_favorite_page_view,
                albums,
                "暂无收藏漫画",
                "收藏漫画",
                limit=12,
            )
        else:
            self.render_profile_album_grid(
                self.profile_history_page_view,
                albums,
                "暂无观看记录",
                "观看记录",
                limit=12,
            )

    def create_profile_album_list(self, old_scroll: QScrollArea) -> FeedListWidget:
        parent = old_scroll.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        layout_index = parent_layout.indexOf(old_scroll) if parent_layout is not None else -1
        album_list = FeedListWidget(parent)
        album_list.setObjectName("profileAlbumList")
        album_list.setViewMode(QListView.IconMode)
        album_list.setFlow(QListView.LeftToRight)
        album_list.setWrapping(True)
        album_list.setResizeMode(QListView.Adjust)
        album_list.setMovement(QListView.Static)
        album_list.setSelectionMode(QAbstractItemView.NoSelection)
        album_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        album_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        album_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        album_list.setVerticalScrollBar(FeedScrollBar(album_list))
        album_list.verticalScrollBar().setSingleStep(30)
        album_list.setFrameShape(QListWidget.NoFrame)
        album_list.setSpacing(0)
        album_list.configure_adaptive_grid(
            PROFILE_CARD_WIDTH,
            PROFILE_GRID_ROW_HEIGHT,
            min_gap=FEED_MIN_GAP,
        )
        album_list.setUniformItemSizes(True)
        album_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if isinstance(parent_layout, QBoxLayout):
            parent_layout.removeWidget(old_scroll)
            parent_layout.insertWidget(max(0, layout_index), album_list, 1)
        old_scroll.hide()
        old_scroll.deleteLater()
        return album_list

    def render_profile_album_grid(
        self,
        album_list: Optional[QListWidget],
        albums,
        empty_text: str,
        parent_title: str,
        limit: Optional[int] = None,
    ):
        if album_list is None:
            return
        album_list.setUpdatesEnabled(False)
        pending_covers = []
        try:
            album_list.clear()
            clear_empty_state = getattr(album_list, "clear_empty_state_widget", None)
            if callable(clear_empty_state):
                clear_empty_state()
            entries = list(albums or [])
            if limit is not None:
                entries = entries[: max(0, limit)]
            for entry in entries:
                history_index = None
                album = entry
                if isinstance(entry, tuple):
                    album, history_index = entry
                if not isinstance(album, AlbumMeta) or not album.album_id:
                    continue
                card, cover = self.create_profile_feed_album_card(
                    album,
                    parent_title,
                    history_index,
                )
                item = QListWidgetItem(album_list)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                item.setSizeHint(QSize(PROFILE_CARD_WIDTH, PROFILE_GRID_ROW_HEIGHT))
                album_list.setItemWidget(item, card)
                pending_covers.append((album, cover))
            if album_list.count() == 0:
                if isinstance(album_list, FeedListWidget):
                    self.show_library_feed_empty_state(album_list, empty_text)
                else:
                    empty_item = QListWidgetItem(empty_text, album_list)
                    empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
                    empty_item.setTextAlignment(Qt.AlignCenter)
                    empty_item.setSizeHint(QSize(PROFILE_CARD_WIDTH, 120))
            album_list.verticalScrollBar().setValue(0)
        finally:
            album_list.setUpdatesEnabled(True)
            album_list.viewport().update()
        if pending_covers:
            QTimer.singleShot(
                30,
                lambda covers=tuple(pending_covers): self.request_profile_album_covers(covers),
            )

    def create_profile_feed_album_card(
        self,
        album: AlbumMeta,
        parent_title: str,
        history_index: Optional[int] = None,
    ) -> tuple[QFrame, QLabel]:
        self.albums.setdefault(album.album_id, copy.deepcopy(album))
        card = QFrame()
        card.setObjectName("profileFeedAlbumCard")
        card.setFixedSize(PROFILE_CARD_WIDTH, PROFILE_CARD_HEIGHT)
        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = (
            lambda event, album_id=album.album_id, title=parent_title:
            self.open_profile_album_detail(album_id, title)
        )
        card.mouseDoubleClickEvent = (
            lambda event, album_id=album.album_id, index=history_index:
            self.open_profile_album_reader(album_id, index)
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        cover = QLabel(card)
        cover.setObjectName("profileFeedAlbumCover")
        cover_width = PROFILE_CARD_WIDTH - 4
        cover_height = int(cover_width * 340 / 250)
        cover.setFixedSize(cover_width, cover_height)
        cover.setAlignment(Qt.AlignCenter)
        cover.setScaledContents(False)
        cover.setText("加载中")
        cover.setStyleSheet("background:transparent;border:0;color:#8491a5;")
        cover._persistent_cover = True
        layout.addWidget(cover, 0, Qt.AlignHCenter)

        title = QLabel(card)
        title.setObjectName("profileFeedAlbumTitle")
        title.setFixedHeight(34)
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        title.setStyleSheet("font-weight:700;color:#1f2937;font-size:10px;")
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
            badge.setToolTip("  ".join(album.tags))
            tags_layout.addWidget(badge)
        tags_layout.addStretch()
        layout.addLayout(tags_layout)
        return card, cover

    def request_profile_album_covers(self, covers):
        for album, cover in covers:
            try:
                self.request_cover(album, cover)
            except RuntimeError:
                continue

    @staticmethod
    def _profile_int(value, fallback: int = 0) -> int:
        try:
            return int(str(value))
        except Exception:
            return fallback

    @staticmethod
    def _set_label(label: Optional[QLabel], text: str):
        if label:
            label.setText(text)

    def _daily_signed_text(self, daily) -> str:
        if not isinstance(daily, dict):
            return "-"
        if isinstance(daily.get("daily"), dict):
            nested = dict(daily.get("daily") or {})
            nested["already_signed"] = daily.get("already_signed", nested.get("already_signed"))
            if daily.get("sign"):
                nested["sign"] = daily.get("sign")
            daily = nested
        if daily.get("already_signed"):
            return "已签到"
        if daily.get("sign"):
            return "\u4eca\u65e5\u5df2\u7b7e\u5230"
        today = time.localtime().tm_mday
        for week in daily.get("record") or []:
            if not isinstance(week, list):
                continue
            for item in week:
                if not isinstance(item, dict):
                    continue
                if self._profile_int(item.get("date"), -1) == today:
                    return "已签到" if item.get("signed") else "未签到"
        return "-"

    def clear_profile_layout(self, layout: Optional[QHBoxLayout]):
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def profile_local_history_items(self) -> List[tuple[AlbumMeta, int]]:
        items: List[tuple[AlbumMeta, int]] = []
        for index, record in reversed(list(enumerate(self.download_history))):
            if not isinstance(record, dict):
                continue
            album = self.album_from_history_record(record)
            if album:
                items.append((album, index))
        return items

    def render_profile_album_strip(
        self,
        layout: Optional[QHBoxLayout],
        albums,
        empty_text: str,
        parent_title: str,
        limit: Optional[int] = None,
    ):
        if layout is None:
            return
        self.clear_profile_layout(layout)
        if not albums:
            label = self.create_empty_state_label(empty_text, 16)
            layout.addWidget(label)
            layout.addStretch()
            return
        entries = list(albums)
        if limit is not None:
            entries = entries[: max(0, limit)]
        for entry in entries:
            history_index = None
            album = entry
            if isinstance(entry, tuple):
                album, history_index = entry
            if not isinstance(album, AlbumMeta) or not album.album_id:
                continue
            layout.addWidget(self.create_profile_album_item(album, parent_title, history_index))
        layout.addStretch()

    def create_profile_album_item(self, album: AlbumMeta, parent_title: str, history_index: Optional[int] = None) -> QFrame:
        self.albums.setdefault(album.album_id, copy.deepcopy(album))
        path = ui_dir() / "profile_album_item.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open profile_album_item.ui: {path}")
        try:
            item = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if item is None:
            raise RuntimeError(f"Unable to load profile_album_item.ui: {path}")
        item.setObjectName("profileAlbumItem")
        item.setCursor(Qt.PointingHandCursor)
        item.setFixedSize(136, 214)
        item.mousePressEvent = lambda event, album_id=album.album_id, parent_title=parent_title: self.open_profile_album_detail(album_id, parent_title)
        item.mouseDoubleClickEvent = (
            lambda event, album_id=album.album_id, history_index=history_index: self.open_profile_album_reader(album_id, history_index)
        )
        cover = item.findChild(QLabel, "profileAlbumCover")
        title = item.findChild(QLabel, "profileAlbumTitle")
        if cover is None or title is None:
            raise RuntimeError("profile_album_item.ui is missing required controls")
        cover._persistent_cover = True
        cover.setFixedSize(118, 158)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet("background:#f8fafc;border:1px solid #e2e8f0;color:#94a3b8;")
        self.apply_loading_movie(cover, QSize(86, 66))
        title.setText(self.elided_album_title(album.title or "-", cover.font(), 118, 2))
        title.setFixedSize(118, 34)
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        title.setStyleSheet("color:#1f2937;font-size:12px;font-weight:700;")
        title.setToolTip(album.title)
        self.request_cover(album, cover)
        return item

    def open_profile_album_detail(self, album_id: str, parent_title: str):
        self.breadcrumb_detail_parent = parent_title or self.current_breadcrumb_page_title()
        self.breadcrumb_detail_parent_index = self.profile_page_index()
        self.open_album_detail(album_id)

    def open_profile_album_reader(self, album_id: str, history_index: Optional[int] = None):
        if history_index is not None and 0 <= history_index < len(self.download_history):
            self.select_history_record(history_index, open_reader=True)
            return
        self.read_album_from_card(album_id)

    def start_avatar_fetch(self):
        urls = list(self.profile_data.get("avatar_urls") or [])
        if not urls or not hasattr(self, "avatar_button"):
            return
        if self.avatar_worker and self.avatar_worker.isRunning():
            return
        self.avatar_worker = CoverFetchWorker(
            "__profile_avatar__",
            urls,
            self.effective_proxy(),
            doh_enabled=self.doh_enabled_box.isChecked(),
            doh_url=self.doh_url_edit.text().strip() or DOH_URL,
            parent=self,
        )
        self.avatar_worker.loaded.connect(self.on_avatar_loaded)
        self.avatar_worker.failed.connect(lambda *_: None)
        self.avatar_worker.finished.connect(lambda: setattr(self, "avatar_worker", None))
        self.avatar_worker.start()

    def on_avatar_loaded(self, _album_id: str, data: bytes, _url: str, _failed_urls):
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            return
        self.profile_avatar_pixmap = pixmap
        self.apply_navigation_avatar_pixmap(pixmap)
        if self.profile_avatar_label:
            self.set_cover_on_label(self.profile_avatar_label, pixmap)
        self.update_navigation_profile_card()
        self.sync_comment_profile_header()

    def _build_settings_panel(self) -> QFrame:
        path = ui_dir() / "settings.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open settings form: {path}")
        try:
            panel = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if panel is None:
            raise RuntimeError(f"Unable to load settings form: {path}")

        def require(widget_type, object_name, text: str = ""):
            widget = panel.findChild(widget_type, object_name)
            if widget is None and text and issubclass(widget_type, QPushButton):
                widget = next((item for item in panel.findChildren(QPushButton) if item.text() == text), None)
            if widget is None:
                raise RuntimeError(f"Missing settings control: {object_name}")
            return widget

        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        self.format_buttons = {
            "images": require(QPushButton, "formatImagesButton", "图片"),
            "zip": require(QPushButton, "formatZipButton", "ZIP"),
            "pdf": require(QPushButton, "formatPdfButton", "PDF"),
        }
        for button in self.format_buttons.values():
            button.setObjectName("segButton")
            self.format_group.addButton(button)
        self.make_pdf = require(QCheckBox, "makePdfCheck")
        self.keep_images = require(QCheckBox, "keepImagesCheck")
        self.cache_as_webp = require(QCheckBox, "cacheWebpCheck")
        self.protocol_parser = require(QCheckBox, "protocolParserCheck")
        self.stop_on_block = require(QCheckBox, "stopOnBlockCheck")
        self.cookie_edit = require(QTextEdit, "cookieEdit")
        self.ua_edit = require(QLineEdit, "uaEdit")
        self.proxy_edit = require(QLineEdit, "proxyEdit")
        self.output_edit = require(QLineEdit, "outputEdit")
        self.cache_path_label = require(QLabel, "cachePathLabel")
        self.delay_min = require(QSpinBox, "delayMinSpin")
        self.delay_max = require(QSpinBox, "delayMaxSpin")
        self.retries = require(QSpinBox, "retriesSpin")
        self.backoff = require(QSpinBox, "backoffSpin")
        self.image_threads = require(QSpinBox, "imageThreadsSpin")
        self.detail_threads = require(QSpinBox, "detailThreadsSpin")
        self.parallel_downloads = require(QSpinBox, "parallelDownloadsSpin")
        self.reading_mode_combo = require(QComboBox, "readingModeCombo")
        self.cookie_edit.setPlainText(load_cookie_header() or jmcomic_default_cookie_header())
        self.ua_edit.setText(DEFAULT_USER_AGENT)
        self.output_edit.setText(str(self.default_output_dir))
        self.output_edit.textChanged.connect(self.update_cache_path_label)
        self.output_edit.editingFinished.connect(self.persist_download_root)
        require(QPushButton, "clearCurrentCacheButton").clicked.connect(self.clear_current_result_cache)
        require(QPushButton, "cleanCacheButton").clicked.connect(self.clean_broken_cache)
        require(QPushButton, "clearAllCacheButton").clicked.connect(self.clear_all_runtime_cache)
        require(QPushButton, "exportCacheButton").clicked.connect(self.export_cache_bundle)
        require(QPushButton, "importCacheButton").clicked.connect(self.import_cache_bundle)
        require(QPushButton, "browserVerifyButton").clicked.connect(self.open_cookie_verifier)
        self.setup_network_settings_panel(panel)
        self.apply_saved_settings()
        self.update_cache_path_label()
        return panel

    def _build_dashboard_header(self) -> QFrame:
        path = ui_dir() / "dashboard_header.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open dashboard_header.ui: {path}")
        try:
            header = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if header is None:
            raise RuntimeError(f"Unable to load dashboard_header.ui: {path}")
        self.breadcrumb_menu_button = header.findChild(QPushButton, "breadcrumbMenuButton")
        self.breadcrumb_section_button = header.findChild(QPushButton, "breadcrumbSectionButton")
        self.breadcrumb_current_button = header.findChild(QPushButton, "breadcrumbCurrentButton")
        self.breadcrumb_sep1 = header.findChild(QLabel, "breadcrumbSep1")
        self.breadcrumb_sep2 = header.findChild(QLabel, "breadcrumbSep2")
        self.backend_label = header.findChild(QLabel, "backendStatusLabel")
        self.nav_search_edit = header.findChild(QLineEdit, "navSearchEdit")
        self.nav_search_button = header.findChild(QPushButton, "navSearchButton")
        required = [
            self.breadcrumb_menu_button,
            self.breadcrumb_section_button,
            self.breadcrumb_current_button,
            self.breadcrumb_sep1,
            self.breadcrumb_sep2,
            self.backend_label,
            self.nav_search_edit,
            self.nav_search_button,
        ]
        if any(widget is None for widget in required):
            raise RuntimeError("dashboard_header.ui is missing required controls")
        self.main_header = header
        header.setObjectName("dashboardHeader")
        header.installEventFilter(self)
        header.setFixedHeight(52)
        self.apply_dashboard_search_visual_system(header)
        self.nav_search_edit.returnPressed.connect(self.search_from_navigation)
        self.nav_search_button.clicked.connect(self.search_from_navigation)
        self.breadcrumb_buttons = {
            "menu": self.breadcrumb_menu_button,
            "section": self.breadcrumb_section_button,
            "current": self.breadcrumb_current_button,
        }
        self.breadcrumb_route_layout = header.findChild(QHBoxLayout, "breadcrumbLayout")
        # Keep the menu button from the designer form and render a variable
        # page path after it, matching JMComic-qt's retained tab path.
        for widget in (
            self.breadcrumb_sep1,
            self.breadcrumb_section_button,
            self.breadcrumb_sep2,
            self.breadcrumb_current_button,
        ):
            widget.hide()
        if self.breadcrumb_menu_button:
            self.breadcrumb_menu_button.setCheckable(False)
            self.breadcrumb_menu_button.clicked.connect(self.toggle_navigation_panel)
        self.breadcrumb_section_index = self.home_page_index()
        self.set_backend_status("待加载", "idle")
        self.backend_label.setVisible(False)
        self.update_breadcrumb()
        return header

    def is_header_account_logged_in(self) -> bool:
        data = self.profile_data or {}
        user = data.get("user") or {}
        return bool(self.session_username or self.session_uid or data.get("username") or user.get("username"))

    def create_header_account_menu(self) -> QMenu:
        menu = QMenu(self)
        if self.is_header_account_logged_in():
            profile_action = menu.addAction("个人资料")
            profile_action.triggered.connect(self.open_profile_page)
            menu.addSeparator()
            logout_action = menu.addAction("退出登录")
            logout_action.triggered.connect(self.logout)
        else:
            login_action = menu.addAction("登录")
            login_action.triggered.connect(self.open_login_or_profile)
        return menu

    def show_header_account_menu(self):
        if not hasattr(self, "header_account_menu"):
            return
        menu = self.create_header_account_menu()
        anchor = self.header_account_menu.mapToGlobal(QPoint(0, -4))
        menu.exec(QPoint(anchor.x(), anchor.y() - menu.sizeHint().height()))

    def _build_detail_panel(self) -> QFrame:
        path = ui_dir() / "detail.ui"
        self.detail_title_label = None
        self.detail_id_label = None
        self.detail_author_label = None
        self.detail_description_label = None
        self.detail_likes_label = None
        self.detail_views_label = None
        self.detail_page_count_label = None
        self.detail_tags_layout = None
        self.detail_offline_chapters: List[ChapterMeta] = []
        self.detail_favorite_button: Optional[QToolButton] = None
        self.detail_favorite_states: Dict[str, bool] = {}
        self.detail_favorite_target_id = ""
        self.detail_favorite_previous_state = False
        self.detail_favorite_toggle_confirmed = False
        self.detail_favorite_folders_loaded = False
        self.detail_favorite_folder_cache: List[Dict] = []
        self.detail_favorite_pending_folder_name = ""
        self.detail_favorite_dialog: Optional[QDialog] = None
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open detail.ui: {path}")
        try:
            panel = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if panel is None:
            raise RuntimeError(f"Unable to load detail.ui: {path}")

        self.detail_panel = panel
        self.detail_scroll_area = panel.findChild(QScrollArea, "detailScrollArea")
        self.detail_scroll_viewport = None
        self.detail_content = panel.findChild(QWidget, "detailContent")
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.detail_loading_overlay = QLabel(panel)
        self.detail_loading_overlay.setObjectName("detailLoadingOverlay")
        self.detail_loading_overlay.setFixedSize(256, 256)
        self.detail_loading_overlay.setAlignment(Qt.AlignCenter)
        self.detail_loading_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.detail_loading_overlay.hide()
        self.cover_label = panel.findChild(QLabel, "detailCoverLabel")
        self.detail_title_label = panel.findChild(QLabel, "detailTitleLabel")
        self.detail_id_label = panel.findChild(QLabel, "detailIdLabel")
        self.detail_author_label = panel.findChild(QLabel, "detailAuthorLabel")
        self.detail_description_label = panel.findChild(QLabel, "detailDescriptionLabel")
        self.detail_likes_label = panel.findChild(QLabel, "detailLikesLabel")
        self.detail_views_label = panel.findChild(QLabel, "detailViewsLabel")
        self.detail_page_count_label = panel.findChild(QLabel, "detailPageCountLabel")
        detail_info_layout = panel.findChild(QVBoxLayout, "detailInfoLayout")
        detail_grid_layout = panel.findChild(QGridLayout, "detailGridLayout")
        detail_hero_layout = panel.findChild(QHBoxLayout, "detailHeroLayout")
        self.detail_hero_layout = detail_hero_layout
        if detail_info_layout and detail_grid_layout:
            detail_info_layout.setAlignment(Qt.AlignTop)
            detail_info_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
            detail_grid_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
            detail_grid_layout.setColumnStretch(1, 1)
            detail_grid_layout.setColumnMinimumWidth(1, 0)
            detail_grid_layout.setVerticalSpacing(8)
        if detail_hero_layout:
            detail_hero_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
            detail_hero_layout.setStretch(0, 0)
            detail_hero_layout.setStretch(1, 1)
        if self.detail_scroll_area:
            self.detail_scroll_area.setMinimumWidth(0)
            self.detail_scroll_area.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
            self.detail_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.detail_scroll_viewport = self.detail_scroll_area.viewport()
            self.detail_scroll_viewport.installEventFilter(self)
        if self.detail_content:
            self.detail_content.setMinimumWidth(0)
            self.detail_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            if self.detail_content.layout():
                self.detail_content.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.cover_label.setScaledContents(False)
        self.cover_label.setContentsMargins(0, 0, 0, 0)
        tags_widget = panel.findChild(QWidget, "detailTagsWidget")
        self.detail_tags_flow_widget = None
        self.detail_tags_layout = None
        if tags_widget and tags_widget.layout():
            tags_widget.setMinimumWidth(0)
            tags_policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            tags_policy.setHeightForWidth(True)
            tags_widget.setSizePolicy(tags_policy)
            self.detail_tags_flow_widget = QWidget(tags_widget)
            self.detail_tags_flow_widget.setObjectName("detailTagsFlowWidget")
            self.detail_tags_flow_widget.setMinimumWidth(0)
            flow_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            flow_policy.setHeightForWidth(True)
            self.detail_tags_flow_widget.setSizePolicy(flow_policy)
            self.detail_tags_layout = FlowLayout(
                self.detail_tags_flow_widget,
                margin=0,
                horizontal_spacing=8,
                vertical_spacing=8,
            )
            tags_widget.layout().addWidget(self.detail_tags_flow_widget)
        self.detail_chapter_buttons = panel.findChild(QWidget, "detailChapterButtons")
        self.detail_chapter_button_layout = panel.findChild(QGridLayout, "detailChapterButtonGrid")
        self.tags_card = panel.findChild(QLabel, "detailTagsFallbackLabel")
        self.chapter_table = panel.findChild(QTableWidget, "detailChapterTable")
        self.offline_chapter_table = panel.findChild(QTableWidget, "detailOfflineChapterTable")
        self.detail_tab_widget = panel.findChild(QTabWidget, "detailTabWidget")
        self.detail_offline_hint_label = panel.findChild(QLabel, "detailOfflineHintLabel")
        required = [
            self.cover_label,
            self.detail_title_label,
            self.detail_description_label,
            self.detail_likes_label,
            self.detail_views_label,
            self.tags_card,
            self.detail_chapter_buttons,
            self.detail_chapter_button_layout,
            self.chapter_table,
            self.offline_chapter_table,
            self.detail_tab_widget,
        ]
        if any(widget is None for widget in required):
            raise RuntimeError("detail.ui is missing required controls")

        def detail_button(object_name: str):
            return panel.findChild(QToolButton, object_name) or panel.findChild(QPushButton, object_name)

        read_chapter_btn = panel.findChild(QPushButton, "detailReadButton")
        self.detail_read_button = read_chapter_btn
        queue_btn = detail_button("detailQueueButton")
        favorite_btn = detail_button("detailFavoriteButton")
        self.detail_favorite_button = favorite_btn
        local_favorite_btn = detail_button("detailLocalFavoriteButton")
        comment_btn = detail_button("detailCommentButton")
        self.detail_comment_button = comment_btn
        clear_cache_btn = detail_button("detailClearCacheButton")
        offline_read_btn = panel.findChild(QPushButton, "detailOfflineReadButton")
        if read_chapter_btn:
            read_chapter_btn.setObjectName("primaryButton")
            read_chapter_btn.clicked.connect(self.open_reader_for_current)
        if queue_btn:
            queue_btn.setObjectName("primaryButton")
            queue_btn.clicked.connect(self.add_current_album_to_queue)
        if favorite_btn:
            favorite_btn.clicked.connect(self.toggle_current_album_favorite)
        if local_favorite_btn:
            local_favorite_btn.clicked.connect(self.add_current_album_to_local_favorites)
        if comment_btn:
            comment_btn.clicked.connect(self.open_current_album_comments)
        if clear_cache_btn:
            clear_cache_btn.clicked.connect(self.clear_current_cover_cache)
        if offline_read_btn:
            offline_read_btn.setObjectName("primaryButton")
            offline_read_btn.clicked.connect(self.open_first_offline_chapter)

        action_icons = (
            (favorite_btn, "icon_like_off.png"),
            (local_favorite_btn, "icon_like_off.png"),
            (comment_btn, "icon_comment.png"),
            (queue_btn, "ic_get_app_black_36dp.png"),
            (clear_cache_btn, "clear_off.png"),
        )
        for button, icon_name in action_icons:
            if button:
                button.setIcon(QIcon(str(DETAIL_ICON_DIR / icon_name)))
                button.setIconSize(QSize(38, 38))
                button.setMinimumHeight(52)
                button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.update_detail_favorite_button()

        if self.cover_label:
            self.cover_label._persistent_cover = True
            self.cover_label.setStyleSheet(
                "background:transparent;border:0;color:#94a3b8;"
            )
        if self.detail_tab_widget:
            self.detail_tab_widget.setMinimumWidth(0)
            self.detail_tab_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
            self.detail_tab_widget.tabBar().setExpanding(False)
            self.detail_tab_widget.setStyleSheet(
                "QTabWidget::pane {border:0;background:transparent;top:-1px;}"
                "QTabBar::tab {border:0;background:transparent;color:#64748b;"
                "min-width:94px;padding:9px 16px 8px;font-size:15px;font-weight:800;}"
                "QTabBar::tab:hover {color:#d65f00;background:#fff7ed;border-radius:6px;}"
                "QTabBar::tab:selected {color:#d65f00;border-bottom:3px solid #f97316;}"
            )
        if getattr(self, "detail_title_label", None):
            self.detail_title_label.setStyleSheet("font-size:18px;font-weight:900;color:#334155;")
        if getattr(self, "detail_author_label", None):
            self.detail_author_label.setStyleSheet("color:#ff7a00;font-size:15px;font-weight:800;")
            self.detail_author_label.setProperty("detailSearchKind", "author")
            self.detail_author_label.installEventFilter(self)
        for label_name in (
            "detail_id_label",
            "detail_description_label",
            "detail_likes_label",
            "detail_views_label",
            "detail_page_count_label",
        ):
            label = getattr(self, label_name, None)
            if label:
                label.setStyleSheet("color:#334155;font-size:14px;")
        for label in (
            self.detail_title_label,
            self.detail_author_label,
            self.detail_description_label,
        ):
            if label:
                label.setMinimumWidth(0)
                policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                policy.setHeightForWidth(True)
                label.setSizePolicy(policy)
        if self.chapter_table:
            self.chapter_table.verticalHeader().setDefaultSectionSize(28)
            self.chapter_table.verticalHeader().setVisible(False)
            self.chapter_table.setHorizontalHeaderLabels(["选择", "序号", "章节", "URL"])
            self.chapter_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.chapter_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.chapter_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.chapter_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            self.chapter_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        if self.detail_chapter_buttons:
            self.detail_chapter_buttons.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            self.detail_chapter_button_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            read_tab_layout = panel.findChild(QVBoxLayout, "detailReadTabLayout")
            if read_tab_layout:
                read_tab_layout.setAlignment(Qt.AlignTop)
        if self.offline_chapter_table:
            self.offline_chapter_table.verticalHeader().setDefaultSectionSize(28)
            self.offline_chapter_table.verticalHeader().setVisible(False)
            self.offline_chapter_table.setHorizontalHeaderLabels(["序号", "章节", "本地缓存"])
            self.offline_chapter_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.offline_chapter_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self.offline_chapter_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self.offline_chapter_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.offline_chapter_table.setMinimumHeight(150)
            self.offline_chapter_table.cellDoubleClicked.connect(self.open_offline_chapter_row)
        if self.detail_offline_hint_label:
            self.detail_offline_hint_label.setStyleSheet(
                "color:#475569;font-size:14px;font-weight:700;padding:6px 2px;"
            )
        for table in (self.chapter_table, self.offline_chapter_table):
            if table:
                table.setAlternatingRowColors(True)
                table.setShowGrid(False)
                table.setStyleSheet(
                    "QTableWidget {background:#ffffff;color:#334155;border:1px solid #e2e8f0;"
                    "border-radius:7px;alternate-background-color:#f8fafc;selection-background-color:#ffedd5;"
                    "selection-color:#9a3412;outline:0;}"
                    "QHeaderView::section {background:#f8fafc;color:#64748b;border:0;"
                    "border-bottom:1px solid #e2e8f0;padding:7px 9px;font-weight:800;}"
                    "QTableWidget::item {border:0;padding:4px 8px;}"
                )
        for tool_button in panel.findChildren(QToolButton):
            tool_button.setCursor(Qt.PointingHandCursor)
            tool_button.setStyleSheet(
                "QToolButton{border:0;background:transparent;color:#475569;font-weight:700;padding:6px 8px;}"
                "QToolButton:hover{background:#fff3e8;color:#d65f00;border-radius:6px;}"
                "QToolButton:pressed{background:#ffe7d0;}"
            )
        return panel

    def _build_history_panel(self) -> QFrame:
        path = ui_dir() / "history.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open history form: {path}")
        try:
            panel = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if panel is None:
            raise RuntimeError(f"Unable to load history form: {path}")

        def require(widget_type, object_name):
            widget = panel.findChild(widget_type, object_name)
            if widget is None:
                raise RuntimeError(f"Missing history control: {object_name}")
            return widget

        self.history_read_mode_combo = require(QComboBox, "historyReadModeCombo")
        self.history_format_filter_combo = require(QComboBox, "historyFormatFilterCombo")
        self.history_format_filter_combo.currentIndexChanged.connect(self.refresh_history_table)
        self.history_view_combo = require(QComboBox, "historyViewCombo")
        self.history_view_combo.currentIndexChanged.connect(self.change_history_view_mode)
        self.history_scroll = require(QScrollArea, "historyScroll")
        self.history_scroll.verticalScrollBar().valueChanged.connect(self.on_history_scroll_value_changed)
        self.history_cards_widget = require(QWidget, "historyCardsWidget")
        self.history_cards_layout = require(QVBoxLayout, "historyCardsLayout")
        self.setup_history_feed_view()
        self.apply_history_visual_system(panel)
        self.refresh_history_table()
        return panel

    def _build_library_panel(self) -> QFrame:
        path = ui_dir() / "library.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open library form: {path}")
        try:
            panel = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if panel is None:
            raise RuntimeError(f"Unable to load library form: {path}")

        text_fallbacks = {
            "libraryCommentPostButton": "发布",
            "enhanceRunButton": "开始增强",
            "libraryWeekLoadButton": "查看推荐",
            "libraryLatestRefreshButton": "加载最新更新",
        }

        def require(widget_type, object_name):
            widget = panel.findChild(widget_type, object_name)
            text = text_fallbacks.get(object_name, "")
            if widget is None and text and issubclass(widget_type, QPushButton):
                widget = next((item for item in panel.findChildren(QPushButton) if item.text() == text), None)
            if widget is None:
                raise RuntimeError(f"Missing library control: {object_name}")
            if object_name in text_fallbacks and issubclass(widget_type, QPushButton):
                widget.setObjectName("primaryButton")
            return widget

        self.library_title_label = None
        self.library_status_label = None
        self.library_tabs = require(QTabWidget, "libraryTabs")
        # These sections are routed from the left navigation. Keep the
        # QTabWidget as the retained page container without duplicating its
        # navigation controls across every account/library page.
        self.library_tabs.tabBar().hide()
        library_tab_titles = {
            "favoritesTab": "我的收藏",
            "remoteHistoryTab": "我的阅读",
            "commentsTab": "我的评论",
            "localTab": "本地收藏",
        }
        for tab_index in range(self.library_tabs.count()):
            tab = self.library_tabs.widget(tab_index)
            if tab is not None and tab.objectName() in library_tab_titles:
                self.library_tabs.setTabText(tab_index, library_tab_titles[tab.objectName()])
        self.library_folder_combo = require(QComboBox, "libraryFolderCombo")
        self.library_favorite_sort_combo = require(QComboBox, "libraryFavoriteSortCombo")
        self.library_new_folder_edit = require(QLineEdit, "libraryNewFolderEdit")
        self.library_favorite_previous_btn = None
        self.library_favorite_page_label = None
        self.library_favorite_next_btn = None
        self.library_favorite_scroll = require(QScrollArea, "libraryFavoriteScroll")
        self.library_favorite_layout = require(QVBoxLayout, "libraryFavoriteLayout")
        self.library_remote_history_previous_btn = require(QPushButton, "libraryRemoteHistoryPreviousButton")
        self.library_remote_history_page_label = require(QLabel, "libraryRemoteHistoryPageLabel")
        self.library_remote_history_next_btn = require(QPushButton, "libraryRemoteHistoryNextButton")
        self.library_remote_history_scroll = require(QScrollArea, "libraryRemoteHistoryScroll")
        self.library_remote_history_layout = require(QVBoxLayout, "libraryRemoteHistoryLayout")
        self.library_comment_album_edit = require(QLineEdit, "libraryCommentAlbumEdit")
        self.library_comment_mine = require(QCheckBox, "libraryCommentMineCheck")
        self.library_comment_previous_btn = require(QPushButton, "libraryCommentPreviousButton")
        self.library_comment_page_label = require(QLabel, "libraryCommentPageLabel")
        self.library_comment_next_btn = require(QPushButton, "libraryCommentNextButton")
        self.library_comment_scroll = require(QScrollArea, "libraryCommentScroll")
        self.library_comment_layout = require(QVBoxLayout, "libraryCommentLayout")
        self.library_comment_input = require(QLineEdit, "libraryCommentInput")
        self.library_comment_reply_edit = require(QLineEdit, "libraryCommentReplyEdit")
        self.library_comment_refresh_btn = require(QPushButton, "libraryCommentsRefreshButton")
        comments_toolbar = panel.findChild(QHBoxLayout, "commentsToolbar")
        self.library_comment_context_label = QLabel()
        self.library_comment_context_label.setObjectName("libraryCommentContextLabel")
        self.library_comment_context_label.setStyleSheet("color:#64748b;")
        self.library_comment_context_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.library_comment_context_label.setVisible(False)
        if comments_toolbar is not None:
            comments_toolbar.insertWidget(0, self.library_comment_context_label)
        self.setup_comments_page(panel)
        self.local_collection_combo = require(QComboBox, "localCollectionCombo")
        self.local_collection_name_edit = require(QLineEdit, "localCollectionNameEdit")
        self.local_collection_album_edit = require(QLineEdit, "localCollectionAlbumEdit")
        self.local_collection_scroll = require(QScrollArea, "localCollectionScroll")
        self.local_collection_layout = require(QVBoxLayout, "localCollectionLayout")
        self.doh_domain_edit = require(QLineEdit, "dohDomainEdit")
        self.doh_endpoint_edit = require(QLineEdit, "dohEndpointEdit")
        if self.doh_endpoint_edit.text().strip() == "https://cloudflare-dns.com/dns-query":
            self.doh_endpoint_edit.setText(DEFAULT_DOH_ENDPOINT)
        self.enhance_paths = []
        self.enhance_source_label = require(QLabel, "enhanceSourceLabel")
        self.enhance_scale = require(QSpinBox, "enhanceScaleSpin")
        self.enhance_output_edit = require(QLineEdit, "enhanceOutputEdit")
        self.enhance_output_edit.setText(str(self.default_output_dir / "enhanced"))
        self.external_sr_command_edit = require(QLineEdit, "externalSrCommandEdit")
        self.storage_profile_combo = require(QComboBox, "storageProfileCombo")
        self.storage_profile_name_edit = require(QLineEdit, "storageProfileNameEdit")
        self.storage_transport_combo = require(QComboBox, "storageTransportCombo")
        self.storage_source_edit = require(QLineEdit, "storageSourceEdit")
        self.storage_destination_edit = require(QLineEdit, "storageDestinationEdit")
        self.webdav_url_edit = require(QLineEdit, "webdavUrlEdit")
        self.webdav_path_edit = require(QLineEdit, "webdavPathEdit")
        self.webdav_user_edit = require(QLineEdit, "webdavUserEdit")
        self.webdav_password_edit = require(QLineEdit, "webdavPasswordEdit")
        self.storage_task_history_output = require(QPlainTextEdit, "storageTaskHistoryOutput")
        self.library_tool_output = require(QPlainTextEdit, "libraryToolOutput")
        self.library_week_combo = require(QComboBox, "libraryWeekCombo")
        self.library_week_type_combo = require(QComboBox, "libraryWeekTypeCombo")
        self.library_week_scroll = require(QScrollArea, "libraryWeekScroll")
        self.library_week_layout = require(QVBoxLayout, "libraryWeekLayout")
        self.library_latest_scroll = require(QScrollArea, "libraryLatestScroll")
        self.library_latest_layout = require(QVBoxLayout, "libraryLatestLayout")
        self.library_latest_previous_btn = require(QPushButton, "libraryLatestPreviousButton")
        self.library_latest_page_label = require(QLabel, "libraryLatestPageLabel")
        self.library_latest_next_btn = require(QPushButton, "libraryLatestNextButton")

        self.library_folder_combo.currentIndexChanged.connect(self.reset_library_favorite_page)
        self.library_favorite_sort_combo.currentIndexChanged.connect(self.reset_library_favorite_page)
        self.local_collection_combo.currentIndexChanged.connect(lambda _=0: self.refresh_local_collection_albums())
        self.storage_profile_combo.currentIndexChanged.connect(self.load_storage_profile)
        require(QPushButton, "libraryFavoritesRefreshButton").clicked.connect(self.refresh_library_favorites)
        require(QPushButton, "libraryAddFolderButton").clicked.connect(self.add_library_folder)
        require(QPushButton, "libraryDeleteFolderButton").clicked.connect(self.delete_library_folder)
        require(QPushButton, "libraryRemoteHistoryRefreshButton").clicked.connect(self.reset_library_remote_history_page)
        self.library_comment_refresh_btn.clicked.connect(self.reset_library_comment_page)
        self.library_comment_previous_btn.clicked.connect(lambda: self.change_library_page("comments", -1))
        self.library_comment_next_btn.clicked.connect(lambda: self.change_library_page("comments", 1))
        require(QPushButton, "libraryCommentPostButton").clicked.connect(self.post_library_comment)
        require(QPushButton, "localCollectionAddButton").clicked.connect(self.add_local_collection)
        require(QPushButton, "localCollectionRemoveButton").clicked.connect(self.remove_local_collection)
        require(QPushButton, "localCollectionAddAlbumButton").clicked.connect(self.add_to_local_collection)
        require(QPushButton, "localImportDirectoryButton").clicked.connect(self.import_local_reader_directory)
        require(QPushButton, "localImportBatchDirectoryButton").clicked.connect(self.import_local_reader_directory_batch)
        require(QPushButton, "localImportArchivesButton").clicked.connect(self.import_local_reader_files)
        require(QPushButton, "localScanButton").clicked.connect(self.sync_local_history_from_button)
        require(QPushButton, "localOpenHistoryButton").clicked.connect(lambda: self.switch_page(self.history_page_index()))
        require(QPushButton, "dohQueryButton").clicked.connect(self.run_doh_query)
        require(QPushButton, "enhanceSelectImagesButton").clicked.connect(self.choose_enhance_images)
        require(QPushButton, "enhanceRunButton").clicked.connect(self.run_image_enhance)
        require(QPushButton, "externalSrRunButton").clicked.connect(self.run_external_sr)
        require(QPushButton, "storageSaveProfileButton").clicked.connect(self.save_storage_profile)
        require(QPushButton, "storageDeleteProfileButton").clicked.connect(self.delete_storage_profile)
        require(QPushButton, "storageSourceBrowseButton").clicked.connect(lambda: self.choose_tool_path(self.storage_source_edit, directory=True))
        require(QPushButton, "storageDestinationBrowseButton").clicked.connect(lambda: self.choose_tool_path(self.storage_destination_edit, directory=True))
        require(QPushButton, "storageCopyButton").clicked.connect(self.run_storage_copy)
        require(QPushButton, "webdavUploadButton").clicked.connect(self.run_webdav_upload)
        require(QPushButton, "libraryWeekReloadButton").clicked.connect(self.refresh_week_categories)
        require(QPushButton, "libraryWeekLoadButton").clicked.connect(self.refresh_week_albums)
        require(QPushButton, "libraryLatestRefreshButton").clicked.connect(self.reset_library_latest_page)
        self.library_latest_previous_btn.clicked.connect(lambda: self.change_library_latest_page(-1))
        self.library_latest_next_btn.clicked.connect(lambda: self.change_library_latest_page(1))
        self.library_latest_previous_btn.setEnabled(False)
        self.setup_library_feed_views()
        self.apply_library_visual_system(panel)
        self.setup_local_favorite_page(panel)
        self.refresh_local_collection_combo()
        self.refresh_storage_profiles()
        self.refresh_storage_transfer_history()
        self.set_library_comment_context(None)
        self.bind_library_theme_controls()
        return panel

    def open_library_tab(self, tab_object_name: str, nav_button: Optional[QPushButton] = None):
        self.set_library_comment_context(None)
        route_titles = {
            "favoritesTab": "我的收藏",
            "commentsTab": "我的评论",
            "remoteHistoryTab": "我的阅读",
            "localTab": "本地收藏",
        }
        route_title = route_titles.get(tab_object_name, "收藏与记录")
        self.switch_page(self.library_page_index(), breadcrumb_title=route_title)
        if self.library_title_label is not None:
            self.library_title_label.setText(route_title)
        if hasattr(self, "library_tabs"):
            for index in range(self.library_tabs.count()):
                tab = self.library_tabs.widget(index)
                if tab and tab.objectName() == tab_object_name:
                    self.library_tabs.setCurrentIndex(index)
                    break
        self.show_library_route_status(tab_object_name)
        if nav_button is not None:
            nav_button.setChecked(True)
        if tab_object_name == "commentsTab":
            self.library_comment_mine.setChecked(True)
            self.library_comment_mine.hide()
        if tab_object_name == "favoritesTab" and not getattr(self, "library_favorites", []):
            self.refresh_library_favorites()
        elif tab_object_name == "remoteHistoryTab" and not getattr(self, "library_remote_history", []):
            self.reset_library_remote_history_page()
        elif tab_object_name == "commentsTab":
            self.refresh_library_comments()
        elif tab_object_name == "localTab":
            self.refresh_local_collection_albums()
        elif tab_object_name == "weekTab":
            if hasattr(self, "library_week_combo") and self.library_week_combo.count():
                self.refresh_week_albums()
            else:
                self.refresh_week_categories()
        elif tab_object_name == "latestTab":
            self.refresh_latest_albums()

    def set_library_comment_context(self, album: Optional[AlbumMeta]):
        """Switch the shared comments tab between public and album-specific modes."""
        is_album_context = album is not None
        self.comment_context_album_id = album.album_id if album else ""
        self.comment_context_title = album.title if album else ""
        if not hasattr(self, "library_tabs"):
            return
        self.library_tabs.tabBar().hide()
        if self.library_title_label is not None:
            self.library_title_label.setText("漫画评论" if is_album_context else "收藏与记录")
        self.library_comment_context_label.setVisible(is_album_context)
        self.library_comment_album_edit.setVisible(not is_album_context)
        self.library_comment_mine.setVisible(not is_album_context)
        self.library_comment_refresh_btn.setText("刷新")
        self.library_comment_input.setPlaceholderText(
            "写下你的评论" if is_album_context else "输入评论；需填写漫画 ID 并登录"
        )
        self.set_comments_page_mode(not is_album_context)
        if is_album_context:
            context_text = f"《{album.title}》 · JM{album.album_id}"
            self.library_comment_context_label.setText(context_text)
            self.library_comment_context_label.setToolTip(context_text)
        else:
            self.library_comment_context_label.clear()

    def open_home_shortcut(self, nav_button: Optional[QPushButton] = None):
        self.switch_page(self.home_page_index())
        if nav_button is not None:
            nav_button.setChecked(True)
        if hasattr(self, "search_edit"):
            self.search_edit.setFocus()

    def refresh_local_collection_combo(self, selected_id: Optional[int] = None):
        self.sync_local_favorite_folders(selected_id)

    def add_local_collection(self):
        self.create_local_favorite_folder()

    def remove_local_collection(self):
        self.delete_local_favorite_folder()

    def local_collection_album_from_input(self) -> Optional[AlbumMeta]:
        value = self.local_collection_album_edit.text().strip()
        if value:
            ids = split_ids(value)
            if not ids:
                self.show_toast("无法识别漫画 ID")
                return None
            album_id = ids[0]
            return copy.deepcopy(self.albums.get(album_id) or self.detail_cache.get(album_id) or AlbumMeta(
                album_id=album_id,
                title=f"JM{album_id}",
                url=f"jm://album/{album_id}",
                source="本地收藏",
            ))
        album = self.current_album()
        if album:
            return copy.deepcopy(album)
        self.show_toast("请输入漫画 ID，或先打开一本漫画详情")
        return None

    def add_to_local_collection(self):
        collection_id = self.local_collection_combo.currentData()
        if collection_id is None:
            self.show_toast("请先新建或选择本地收藏夹")
            return
        album = self.local_collection_album_from_input()
        if not album:
            return
        self.local_collection_store.add_album(int(collection_id), album)
        self.local_collection_album_edit.clear()
        self.refresh_local_collection_combo(int(collection_id))
        self.show_toast("已加入本地收藏")

    def refresh_local_collection_albums(self):
        self.refresh_local_favorite_page()

    def render_local_collection_albums(self, albums: List[AlbumMeta]):
        self.local_favorite_visible_albums = list(albums or [])
        self.render_local_favorite_cards(self.local_favorite_visible_albums)

    def remove_local_collection_album(self, collection_id, album_id: str):
        self.remove_local_favorite_album(collection_id, album_id)

    def import_local_reader_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "\u9009\u62e9\u6f2b\u753b\u76ee\u5f55", str(self.default_output_dir))
        if directory:
            self.start_local_reader_import([directory], batch=False)

    def import_local_reader_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "\u9009\u62e9\u672c\u5730\u9605\u8bfb\u6587\u4ef6",
            str(self.default_output_dir),
            "Comic files (*.zip *.pdf *.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if paths:
            self.start_local_reader_import(paths, batch=False)

    def import_local_reader_directory_batch(self):
        directory = QFileDialog.getExistingDirectory(self, "\u9009\u62e9\u6279\u91cf\u5bfc\u5165\u76ee\u5f55", str(self.default_output_dir))
        if not directory:
            return
        self.start_local_reader_import([directory], batch=True)

    def start_local_reader_import(self, paths: List[str], batch: bool = False):
        if self.local_reader_import_worker and self.local_reader_import_worker.isRunning():
            self.show_toast("本地导入任务正在运行", 1800)
            return
        album_cache = {
            album_id: self.album_to_dict(album)
            for album_id, album in {**self.detail_cache, **self.albums}.items()
            if album_id and isinstance(album, AlbumMeta)
        }
        worker = LocalReaderImportWorker(self.download_history, paths, album_cache, batch=batch, parent=self)
        self.local_reader_import_worker = worker
        worker.imported.connect(self.on_local_reader_imported)
        worker.failed.connect(self.on_local_reader_import_failed)
        worker.finished.connect(lambda worker=worker: self.cleanup_local_reader_import_worker(worker))
        self.show_toast("正在后台导入本地阅读项", 1600)
        self.log("开始后台导入本地阅读项。")
        worker.start()

    def on_local_reader_imported(self, history: List[Dict[str, str]], added: int, selected_index: int):
        self.download_history = history
        if selected_index >= 0:
            self.selected_history_index = min(selected_index, len(self.download_history) - 1)
        elif self.download_history:
            self.selected_history_index = min(max(self.selected_history_index, -1), len(self.download_history) - 1)
        else:
            self.selected_history_index = -1
        self.refresh_history_table()
        self.save_local_cache()
        if added:
            self.show_toast(f"本地导入完成：{added} 项")
            self.log(f"本地阅读项后台导入完成：新增/更新 {added} 项。")
        else:
            self.show_toast("未找到新的本地阅读项", 1800)
            self.log("本地阅读项后台导入完成：没有新增记录。")

    def on_local_reader_import_failed(self, message: str):
        self.show_toast(f"本地导入失败：{message}", 2400)
        self.log(f"本地阅读项后台导入失败：{message}")

    def cleanup_local_reader_import_worker(self, worker: LocalReaderImportWorker):
        if worker is self.local_reader_import_worker:
            self.local_reader_import_worker = None
        worker.deleteLater()

    def import_local_reader_resource(self, path: Path, refresh: bool = True) -> int:
        path = Path(path).expanduser()
        album_id = self.album_id_from_local_output(path)
        record = self.history_record_from_local_output(path, album_id, managed=False)
        if record is None:
            self.show_toast("\u672a\u627e\u5230\u53ef\u9605\u8bfb\u7684\u56fe\u7247\u3001ZIP \u6216 PDF")
            return 0
        existing_index = self.find_history_index_for_album(album_id) if album_id else -1
        if existing_index < 0:
            existing_index = self.find_history_index_for_output(path)
        if existing_index >= 0:
            changed = self.merge_history_record_local_output(existing_index, record)
            self.download_history[existing_index]["managed"] = "0"
            self.selected_history_index = existing_index
            added = 1 if changed else 0
        else:
            self.download_history.append(record)
            self.selected_history_index = len(self.download_history) - 1
            added = 1
        if refresh:
            self.refresh_history_table()
            self.save_local_cache()
            self.show_toast("\u5df2\u5bfc\u5165\u672c\u5730\u9605\u8bfb\u9879")
        return added

    def refresh_storage_profiles(self, selected_id: Optional[int] = None):
        if not hasattr(self, "storage_profile_combo"):
            return
        combo = self.storage_profile_combo
        current = selected_id if selected_id is not None else combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("\u9009\u62e9\u5df2\u4fdd\u5b58\u7684\u914d\u7f6e", None)
        for profile in self.storage_store.list_profiles():
            combo.addItem(f"{profile.name} ({profile.transport})", profile.profile_id)
        combo.blockSignals(False)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def load_storage_profile(self, _index: int = 0):
        profile_id = self.storage_profile_combo.currentData()
        if profile_id is None:
            return
        profile = next(
            (item for item in self.storage_store.list_profiles() if item.profile_id == int(profile_id)),
            None,
        )
        if profile is None:
            return
        self.storage_profile_name_edit.setText(profile.name)
        self.storage_transport_combo.setCurrentIndex(
            max(0, self.storage_transport_combo.findData(profile.transport))
        )
        self.storage_destination_edit.setText(profile.destination)
        self.webdav_url_edit.setText(profile.webdav_url)
        self.webdav_path_edit.setText(profile.webdav_path)
        self.webdav_user_edit.setText(profile.username)
        self.webdav_password_edit.clear()

    def save_storage_profile(self):
        name = self.storage_profile_name_edit.text().strip()
        try:
            profile_id = self.storage_store.save_profile(
                name=name,
                transport=str(self.storage_transport_combo.currentData() or "local_smb"),
                destination=self.storage_destination_edit.text(),
                webdav_url=self.webdav_url_edit.text(),
                webdav_path=self.webdav_path_edit.text(),
                username=self.webdav_user_edit.text(),
            )
        except Exception as exc:
            self.show_toast(str(exc))
            return
        self.refresh_storage_profiles(profile_id)
        self.show_toast("\u5b58\u50a8\u914d\u7f6e\u5df2\u4fdd\u5b58")

    def delete_storage_profile(self):
        profile_id = self.storage_profile_combo.currentData()
        if profile_id is None:
            self.show_toast("\u8bf7\u5148\u9009\u62e9\u8981\u5220\u9664\u7684\u914d\u7f6e")
            return
        self.storage_store.remove_profile(int(profile_id))
        self.storage_profile_name_edit.clear()
        self.refresh_storage_profiles()
        self.show_toast("\u5b58\u50a8\u914d\u7f6e\u5df2\u5220\u9664")

    def refresh_storage_transfer_history(self):
        if not hasattr(self, "storage_task_history_output"):
            return
        rows = []
        for task in self.storage_store.list_transfers(limit=12):
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(task.created_at))
            detail = f" - {task.detail}" if task.detail else ""
            rows.append(f"#{task.transfer_id}  {stamp}  {task.status}  {task.transport}: {task.source} -> {task.destination}{detail}")
        self.storage_task_history_output.setPlainText("\n".join(rows) or "\u6682\u65e0\u4f20\u8f93\u4efb\u52a1")

    def _record_storage_transfer(self, transport: str, source: str, destination: str) -> int:
        transfer_id = self.storage_store.add_transfer(transport, source, destination)
        self.refresh_storage_transfer_history()
        return transfer_id

    def choose_tool_path(self, edit: QLineEdit, directory: bool = False):
        if directory:
            value = QFileDialog.getExistingDirectory(self, "选择目录", edit.text().strip() or str(self.default_output_dir))
        else:
            value, _ = QFileDialog.getOpenFileName(self, "选择文件", edit.text().strip() or str(self.default_output_dir))
        if value:
            edit.setText(value)

    def choose_enhance_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要增强的图片",
            str(self.default_output_dir),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if files:
            self.enhance_paths = files
            self.enhance_source_label.setText(f"已选择 {len(files)} 张图片")

    def start_library_tool(self, action: str, payload: Dict):
        worker = LibraryToolWorker(action, payload, self)
        self.library_tool_workers.append(worker)
        worker.completed.connect(
            lambda completed_action, result, worker=worker: self.on_library_tool_completed(completed_action, result, worker)
        )
        worker.failed.connect(
            lambda failed_action, message, worker=worker: self.on_library_tool_failed(failed_action, message, worker)
        )
        worker.finished.connect(lambda worker=worker: self.forget_library_tool_worker(worker))
        self.library_tool_output.setPlainText("正在执行...")
        worker.start()

    def forget_library_tool_worker(self, worker: LibraryToolWorker):
        if worker in self.library_tool_workers:
            self.library_tool_workers.remove(worker)
        worker.deleteLater()

    def run_doh_query(self):
        self.start_library_tool("doh", {"domain": self.doh_domain_edit.text(), "endpoint": self.doh_endpoint_edit.text()})

    def run_image_enhance(self):
        if not self.enhance_paths:
            self.show_toast("请先选择图片")
            return
        self.start_library_tool(
            "upscale",
            {"paths": self.enhance_paths, "output_dir": self.enhance_output_edit.text(), "scale": self.enhance_scale.value()},
        )

    def run_external_sr(self):
        if not self.enhance_paths:
            self.show_toast("请先选择图片")
            return
        command = self.external_sr_command_edit.text().strip()
        if not command:
            self.show_toast("请填写外部超分命令")
            return
        self.start_library_tool(
            "external_sr",
            {"paths": self.enhance_paths, "output_dir": self.enhance_output_edit.text(), "command": command},
        )

    def run_storage_copy(self):
        source = self.storage_source_edit.text().strip()
        destination = self.storage_destination_edit.text().strip()
        if not source or not destination:
            self.show_toast("请选择源文件和目标目录")
            return
        transfer_id = self._record_storage_transfer("local_smb", source, destination)
        self.start_library_tool(
            "copy_storage",
            {"source": source, "destination": destination, "storage_transfer_id": transfer_id},
        )

    def run_webdav_upload(self):
        source = self.storage_source_edit.text().strip()
        url = self.webdav_url_edit.text().strip()
        if not source or not url:
            self.show_toast("请选择源文件并填写 WebDAV 地址")
            return
        remote_path = self.webdav_path_edit.text()
        transfer_id = self._record_storage_transfer("webdav", source, f"{url.rstrip('/')}/{remote_path.strip('/')}")
        self.start_library_tool(
            "webdav",
            {
                "source": source,
                "base_url": url,
                "remote_path": remote_path,
                "username": self.webdav_user_edit.text(),
                "password": self.webdav_password_edit.text(),
                "storage_transfer_id": transfer_id,
            },
        )

    def on_library_tool_completed(self, action: str, result, worker: Optional[LibraryToolWorker] = None):
        transfer_id = worker.payload.get("storage_transfer_id") if worker else None
        if transfer_id is not None:
            count = len(result) if isinstance(result, list) else int(result)
            self.storage_store.finish_transfer(int(transfer_id), "completed", f"{count} files transferred")
            self.refresh_storage_transfer_history()
        if action == "doh":
            text = "\n".join(f"{item['name']}  type={item['type']}  ttl={item['ttl']}  {item['data']}" for item in result)
            self.library_tool_output.setPlainText(text or "未返回 A 记录")
        elif action in {"upscale", "external_sr"}:
            self.library_tool_output.setPlainText("已生成：\n" + "\n".join(str(path) for path in result))
        elif action == "copy_storage":
            self.library_tool_output.setPlainText(f"上传完成，共 {len(result)} 个文件：\n" + "\n".join(str(path) for path in result[:40]))
        else:
            self.library_tool_output.setPlainText(f"WebDAV 上传完成，共 {result} 个文件")

    def on_library_tool_failed(self, action: str, message: str, worker: Optional[LibraryToolWorker] = None):
        transfer_id = worker.payload.get("storage_transfer_id") if worker else None
        if transfer_id is not None:
            self.storage_store.finish_transfer(int(transfer_id), "failed", message)
            self.refresh_storage_transfer_history()
        self.library_tool_output.setPlainText(f"{action} 失败：{message}")
        self.log(f"工具 {action} 失败：{message}")

    @staticmethod
    def _clear_library_layout(layout: QVBoxLayout):
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _library_has_session(self) -> bool:
        return bool(
            (self.session_username and self.session_password)
            or (hasattr(self, "cookie_edit") and self.cookie_edit.toPlainText().strip())
        )

    def open_library(
        self,
        tab: int = 0,
        refresh: bool = True,
        preserve_path: bool = False,
        breadcrumb_title: str = "",
        preserve_comment_context: bool = False,
    ):
        if not preserve_comment_context:
            self.set_library_comment_context(None)
        self.switch_page(
            self.library_page_index(),
            preserve_path=preserve_path,
            breadcrumb_title=breadcrumb_title,
        )
        if hasattr(self, "library_tabs"):
            self.library_tabs.setCurrentIndex(max(0, min(tab, self.library_tabs.count() - 1)))
        if not refresh:
            return
        if tab == 0:
            self.refresh_library_favorites()
        elif tab == 1:
            self.refresh_library_remote_history()
        elif tab == 2:
            self.refresh_library_comments()
        elif tab == 5:
            self.refresh_week_categories()
        elif tab == 6:
            self.refresh_latest_albums()

    def start_library_action(self, action: str, payload: Optional[Dict] = None, requires_session: bool = True):
        if requires_session and not self._library_has_session():
            self.show_toast("请先登录账号或在设置中填写有效 Cookie", 2400)
            return False
        worker = LibraryWorker(action, self._profile_settings(), payload, self)
        self.library_workers.append(worker)
        worker.loaded.connect(self.on_library_loaded)
        worker.failed.connect(self.on_library_failed)
        worker.finished.connect(lambda worker=worker: self.forget_library_worker(worker))
        if action in {"comments", "post_comment"} and self.comment_context_album_id:
            self.set_library_status_text("漫画评论加载中...")
        else:
            self.set_library_status_text("正在同步收藏与记录...")
        worker.start()
        return True

    def forget_library_worker(self, worker: LibraryWorker):
        if worker in self.library_workers:
            self.library_workers.remove(worker)
        worker.deleteLater()

    def refresh_library_favorites(self):
        if not hasattr(self, "library_folder_combo"):
            return False
        if self.library_favorite_loading:
            if self.library_favorite_page == 1:
                self.library_favorite_reload_pending = True
            return False
        self.library_favorite_loading = True
        started = self.start_library_action(
            "favorites",
            {
                "folder_id": self.library_folder_combo.currentData() or "0",
                "sort": self.library_favorite_sort_combo.currentData() or "mr",
                "page": self.library_favorite_page,
            },
        )
        if not started:
            self.library_favorite_loading = False
        return bool(started)

    def refresh_library_remote_history(self):
        if self.library_remote_history_loading:
            if self.library_remote_history_page == 1:
                self.library_remote_history_reload_pending = True
            return False
        self.library_remote_history_loading = True
        started = self.start_library_action(
            "remote_history", {"page": self.library_remote_history_page}
        )
        if not started:
            self.library_remote_history_loading = False
        return bool(started)

    def refresh_library_comments(self):
        album_id = self.comment_context_album_id or (
            self.library_comment_album_edit.text().strip() if hasattr(self, "library_comment_album_edit") else ""
        )
        personal_page = not bool(self.comment_context_album_id)
        comment_filter = (
            str(getattr(self, "comment_filter_mode", "all") or "all")
            if personal_page
            else "album"
        )
        mine = personal_page and comment_filter != "all"
        if personal_page:
            self.refresh_personal_comment_statistics()
        request_serial = int(getattr(self, "library_comment_request_serial", 0)) + 1
        self.library_comment_request_serial = request_serial
        return self.start_library_action(
            "comments",
            {
                "album_id": album_id,
                "mine": mine,
                "user_id": self.session_uid if mine else "",
                "page": self.library_comment_page,
                "comment_filter": comment_filter,
                "request_serial": request_serial,
            },
            requires_session=mine,
        )

    def refresh_personal_comment_statistics(self, force: bool = False):
        uid = str(getattr(self, "session_uid", "") or "").strip()
        if not uid:
            self.personal_comment_statistics = None
            self.personal_comment_statistics_uid = ""
            self.personal_comment_statistics_loading = False
            if hasattr(self, "my_comments_stat_labels"):
                self.update_comment_statistics([], 0)
            return False
        if (
            not force
            and getattr(self, "personal_comment_statistics_uid", "") == uid
            and (
                getattr(self, "personal_comment_statistics", None) is not None
                or getattr(self, "personal_comment_statistics_loading", False)
            )
        ):
            return False
        self.personal_comment_statistics = None
        self.personal_comment_statistics_uid = uid
        self.personal_comment_statistics_loading = True
        serial = int(getattr(self, "personal_comment_statistics_serial", 0)) + 1
        self.personal_comment_statistics_serial = serial
        if hasattr(self, "my_comments_stat_labels"):
            self.update_comment_statistics([], 0)
        started = self.start_library_action(
            "comment_stats",
            {"user_id": uid, "request_serial": serial},
            requires_session=True,
        )
        if not started:
            self.personal_comment_statistics_loading = False
        return bool(started)

    def reset_library_favorite_page(self, _index: int = 0):
        self.library_favorite_page = 1
        self.library_favorite_total = 0
        self.library_favorite_has_more = True
        self.reset_library_favorite_feed_scroll()
        if self.library_favorite_loading:
            self.library_favorite_reload_pending = True
            return
        self.refresh_library_favorites()

    def reset_library_remote_history_page(self):
        self.library_remote_history_page = 1
        self.library_remote_history_total = 0
        self.library_remote_history_has_more = True
        self.reset_library_remote_history_feed_scroll()
        if self.library_remote_history_loading:
            self.library_remote_history_reload_pending = True
            return
        self.refresh_library_remote_history()

    def reset_library_comment_page(self, _index: int = 0):
        self.library_comment_page = 1
        self.refresh_library_comments()

    def change_library_page(self, scope: str, delta: int):
        attributes = {
            "comments": "library_comment_page",
        }
        attribute = attributes.get(scope)
        if not attribute:
            return
        page = max(1, int(getattr(self, attribute, 1)) + int(delta))
        if page == getattr(self, attribute, 1):
            return
        setattr(self, attribute, page)
        self.refresh_library_comments()

    def update_library_pager(self, scope: str, page: int, total: int, page_count: int):
        prefix = {
            "comments": "library_comment",
        }.get(scope)
        if not prefix:
            return
        label = getattr(self, f"{prefix}_page_label", None)
        previous = getattr(self, f"{prefix}_previous_btn", None)
        next_button = getattr(self, f"{prefix}_next_btn", None)
        if label:
            pages = max(1, (max(0, total) + max(1, page_count) - 1) // max(1, page_count))
            label.setText(f"\u7b2c {page} / {pages} \u9875 \u00b7 \u5171 {total} \u6761")
        if previous:
            previous.setEnabled(page > 1)
        if next_button:
            next_button.setEnabled(bool(page_count) and (page * max(1, page_count) < total))

    def refresh_week_categories(self):
        self.start_library_action("week_categories", requires_session=False)

    def refresh_latest_albums(self):
        self.start_library_action(
            "latest",
            {"page": self.library_latest_page},
            requires_session=False,
        )

    def reset_library_latest_page(self):
        self.library_latest_page = 0
        self.refresh_latest_albums()

    def change_library_latest_page(self, delta: int):
        page = max(0, int(self.library_latest_page) + int(delta))
        if page == self.library_latest_page:
            return
        self.library_latest_page = page
        self.refresh_latest_albums()

    def refresh_week_albums(self):
        category_id = self.library_week_combo.currentData() if hasattr(self, "library_week_combo") else ""
        if not category_id:
            self.refresh_week_categories()
            self.show_toast("正在加载周推荐期数，请稍后选择")
            return
        self.start_library_action(
            "week_albums",
            {"category_id": str(category_id), "category_type": self.library_week_type_combo.currentData() or "manga"},
            requires_session=False,
        )

    def add_library_folder(self):
        name = self.library_new_folder_edit.text().strip()
        if not name:
            self.show_toast("请输入收藏夹名称")
            return
        self.start_library_action("add_folder", {"name": name})

    def delete_library_folder(self):
        folder_id = str(self.library_folder_combo.currentData() or "0")
        if folder_id == "0":
            self.show_toast("请选择要删除的收藏夹")
            return
        self.start_library_action("delete_folder", {"folder_id": folder_id})

    def post_library_comment(self):
        album_id = self.comment_context_album_id or self.library_comment_album_edit.text().strip()
        comment = self.library_comment_input.text().strip()
        comment_id = self.library_comment_reply_edit.text().strip()
        if not album_id:
            self.show_toast("发布评论前请填写漫画 ID")
            return
        if not comment:
            self.show_toast("请输入评论内容")
            return
        self.start_library_action(
            "post_comment",
            {"album_id": album_id, "comment": comment, "comment_id": comment_id},
        )

    def on_library_loaded(self, action: str, result: Dict):
        result = dict(result or {})
        if action == "comment_stats":
            response_serial = int(result.get("request_serial") or 0)
            response_uid = str(result.get("user_id") or "").strip()
            if (
                response_serial != int(getattr(self, "personal_comment_statistics_serial", 0))
                or response_uid != str(getattr(self, "session_uid", "") or "").strip()
            ):
                return
            self.personal_comment_statistics_loading = False
            self.personal_comment_statistics_uid = response_uid
            self.personal_comment_statistics = {
                key: max(0, int(result.get(key) or 0))
                for key in ("published", "likes", "featured", "replies")
            }
            self.update_comment_statistics([], 0)
            return
        if action == "comments":
            response_serial = int(result.get("request_serial") or 0)
            if response_serial and response_serial != int(
                getattr(self, "library_comment_request_serial", 0)
            ):
                return
        self.set_library_status_text(
            "\u6f2b\u753b\u8bc4\u8bba\u5df2\u540c\u6b65"
            if self.comment_context_album_id and action in {"comments", "post_comment"}
            else "\u6536\u85cf\u4e0e\u8bb0\u5f55\u5df2\u540c\u6b65"
        )
        if action == "detail_toggle_favorite":
            album_id = self.detail_favorite_target_id
            is_favorite = self.detail_favorite_state(album_id)
            self.detail_favorite_toggle_confirmed = True
            self.update_detail_favorite_button(enabled=not is_favorite)
            if not is_favorite:
                self.detail_favorite_target_id = ""
                self.show_toast("已取消收藏")
                return
            if self.detail_favorite_folders_loaded:
                self.open_detail_favorite_dialog(self.detail_favorite_folder_cache)
            else:
                self.show_toast("已收藏，正在准备分类...", 1200)
            return
        if action == "detail_favorite_folders":
            self.detail_favorite_folder_cache = [
                dict(item) for item in (result.get("folders") or []) if isinstance(item, dict)
            ]
            self.detail_favorite_folders_loaded = True
            if self.detail_favorite_toggle_confirmed and self.detail_favorite_state(self.detail_favorite_target_id):
                self.open_detail_favorite_dialog(
                    self.detail_favorite_folder_cache,
                    self.detail_favorite_pending_folder_name,
                )
            self.detail_favorite_pending_folder_name = ""
            return
        if action == "detail_add_favorite_folder":
            dialog = self.detail_favorite_dialog
            if dialog is not None:
                dialog.status_label.setText("分类已添加，正在刷新列表...")
            self.detail_favorite_folders_loaded = False
            self.start_library_action("detail_favorite_folders", requires_session=True)
            return
        if action == "detail_move_favorite":
            dialog = self.detail_favorite_dialog
            folder_name = ""
            if dialog is not None:
                folder_name = dialog.category_box.currentText()
                dialog.accept()
            self.detail_favorite_target_id = ""
            self.show_toast(f"已收藏到{folder_name or '所选分类'}")
            return
        if action == "local_favorite_import":
            self.apply_local_favorite_import_result(result)
            return
        if action == "local_favorite_update":
            self.apply_local_favorite_update_result(result)
            return
        if action == "favorites":
            self.library_favorite_loading = False
            if self.library_favorite_reload_pending:
                self.library_favorite_reload_pending = False
                self.refresh_library_favorites()
                return
            self.library_folders = [dict(item) for item in (result.get("folders") or []) if isinstance(item, dict)]
            incoming = self.unique_library_albums(
                [],
                [
                    self.album_from_dict(item)
                    for item in (result.get("albums") or [])
                    if isinstance(item, dict)
                ],
            )
            response_page = max(1, int(result.get("page") or self.library_favorite_page))
            self.library_favorite_page = response_page
            self.library_favorite_total = max(0, int(result.get("total") or 0))
            self.sync_library_folder_combo(str(result.get("folder_id") or "0"))
            if response_page <= 1:
                self.library_favorites = incoming
                appended = incoming
            else:
                appended = self.unique_library_albums(
                    self.library_favorites, incoming
                )
                self.library_favorites.extend(appended)
            self.library_favorite_has_more = bool(incoming) and bool(appended) and (
                self.library_favorite_total <= 0
                or len(self.library_favorites) < self.library_favorite_total
            )
            self.render_library_albums(
                self.library_favorite_layout,
                appended if response_page > 1 else self.library_favorites,
                "暂无云端收藏",
                favorite_actions=True,
                append=response_page > 1,
            )
            self.set_library_route_count(
                "favoritesTab", len(self.library_favorites), "本"
            )
            QTimer.singleShot(0, self.check_library_favorite_scroll_end)
            return
        if action == "remote_history":
            self.apply_library_remote_history_result(result)
            return
        if action == "comments":
            comments = result.get("comments") or []
            self.library_comment_page = max(1, int(result.get("page") or self.library_comment_page))
            total_value = (
                result.get("own_total")
                if bool(result.get("personal")) and result.get("own_total") is not None
                else result.get("total")
            )
            comment_total = max(0, int(total_value or 0))
            self.render_library_comments(comments, comment_total)
            self.update_library_pager(
                "comments",
                self.library_comment_page,
                comment_total,
                len(comments),
            )
            return
        if action == "week_categories":
            self.sync_week_categories(result.get("categories") or [])
            return
        if action == "latest":
            albums = [self.album_from_dict(item) for item in (result.get("albums") or []) if isinstance(item, dict)]
            self.library_latest_page = max(0, int(result.get("page") or self.library_latest_page))
            self.render_library_albums(self.library_latest_layout, albums, "暂无最新更新")
            self.library_latest_page_label.setText(f"第 {self.library_latest_page + 1} 页")
            self.library_latest_previous_btn.setEnabled(self.library_latest_page > 0)
            self.library_latest_next_btn.setEnabled(bool(albums))
            self.library_latest_scroll.verticalScrollBar().setValue(0)
            return
        if action == "week_albums":
            albums = [self.album_from_dict(item) for item in (result.get("albums") or []) if isinstance(item, dict)]
            self.render_library_albums(self.library_week_layout, albums, "本期没有推荐漫画")
            return
        if action in {"add_folder", "delete_folder", "move_favorite", "toggle_favorite"}:
            if hasattr(self, "library_new_folder_edit"):
                self.library_new_folder_edit.clear()
            self.show_toast("操作完成")
            self.reset_library_favorite_page()
            return
        if action == "post_comment":
            self.library_comment_input.clear()
            self.library_comment_reply_edit.clear()
            self.library_comment_page = 1
            self.show_toast("评论已提交")
            self.refresh_personal_comment_statistics(force=True)
            self.refresh_library_comments()

    def on_library_failed(self, action: str, message: str):
        if action == "comment_stats":
            self.personal_comment_statistics_loading = False
            if hasattr(self, "my_comments_stat_labels"):
                self.update_comment_statistics([], 0)
            self.log(f"个人评论统计加载失败：{message}")
            return
        if action.startswith("detail_"):
            if action == "detail_favorite_folders":
                self.detail_favorite_folders_loaded = True
                self.detail_favorite_folder_cache = []
                if self.detail_favorite_toggle_confirmed and self.detail_favorite_target_id:
                    self.open_detail_favorite_dialog([])
                    self.show_toast("收藏成功，分类列表加载失败，可稍后在云端收藏中调整", 2800)
                return
            dialog = self.detail_favorite_dialog
            if dialog is not None:
                dialog.status_label.setText(f"操作失败：{message}")
                dialog.add_folder_button.setEnabled(True)
                dialog.save_button.setEnabled(True)
            if action == "detail_toggle_favorite":
                self.set_detail_favorite_state(
                    self.detail_favorite_target_id,
                    self.detail_favorite_previous_state,
                )
                self.detail_favorite_target_id = ""
                self.update_detail_favorite_button(enabled=True)
            self.log(f"详情收藏 {action} 失败：{message}")
            self.show_toast(f"收藏操作失败：{message}", 2600)
            return
        if action == "favorites":
            self.library_favorite_loading = False
            if self.library_favorite_reload_pending:
                self.library_favorite_reload_pending = False
                self.refresh_library_favorites()
                return
            if self.library_favorite_page > 1:
                self.library_favorite_page -= 1
            self.library_favorite_has_more = True
        elif action == "remote_history":
            self.apply_library_remote_history_failure()
        elif action in {"local_favorite_import", "local_favorite_update"}:
            self.apply_local_favorite_failure(message)
        scope = "\u6f2b\u753b\u8bc4\u8bba" if self.comment_context_album_id and action in {"comments", "post_comment"} else "\u6536\u85cf\u4e0e\u8bb0\u5f55"
        self.set_library_status_text(f"{scope}\u64cd\u4f5c\u5931\u8d25\uff1a{message}")
        self.log(f"{scope} {action} \u5931\u8d25\uff1a{message}")
        self.show_toast(f"操作失败：{message}", 2600)

    def sync_library_folder_combo(self, selected_id: str = "0"):
        if not hasattr(self, "library_folder_combo"):
            return
        combo = self.library_folder_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("全部收藏", "0")
        seen = {"0"}
        for item in self.library_folders:
            folder_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if folder_id and name and folder_id not in seen:
                combo.addItem(name, folder_id)
                seen.add(folder_id)
        index = combo.findData(selected_id)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self.sync_library_favorite_toolbar_icons()
        self.sync_library_favorite_toolbar_state()

    def sync_week_categories(self, categories: List[Dict]):
        if not hasattr(self, "library_week_combo"):
            return
        combo = self.library_week_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for item in categories:
            category_id = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            time_text = str(item.get("time") or "").strip()
            if category_id:
                combo.addItem(" - ".join(part for part in [time_text, title] if part) or category_id, category_id)
        index = combo.findData(previous)
        combo.setCurrentIndex(index if index >= 0 else (0 if combo.count() else -1))
        combo.blockSignals(False)
        if combo.count():
            self.refresh_week_albums()

    def render_library_albums(
        self,
        layout: QVBoxLayout,
        albums: List[AlbumMeta],
        empty_text: str,
        favorite_actions: bool = False,
        append: bool = False,
    ):
        feed = self.library_feed_for_layout(layout)
        if feed is not None:
            self.render_library_feed(
                feed,
                albums,
                empty_text,
                favorite_actions=favorite_actions,
                append=append,
            )
            return
        if append:
            for album in albums:
                self.albums[album.album_id] = copy.deepcopy(album)
                self.detail_cache.setdefault(album.album_id, copy.deepcopy(album))
                row = self.create_library_album_card(album, favorite_actions=favorite_actions)
                layout.insertWidget(max(0, layout.count() - 1), row)
            return
        self._clear_library_layout(layout)
        if not albums:
            empty_state = self.create_library_empty_state_widget(
                layout.parentWidget(), empty_text
            )
            empty_state.setMinimumHeight(360)
            layout.insertWidget(0, empty_state, 1)
            return
        for album in albums:
            self.albums[album.album_id] = copy.deepcopy(album)
            self.detail_cache.setdefault(album.album_id, copy.deepcopy(album))
            row = self.create_library_album_card(album, favorite_actions=favorite_actions)
            layout.insertWidget(max(0, layout.count() - 1), row)

    def create_library_album_card(self, album: AlbumMeta, favorite_actions: bool = False, remove_callback=None) -> QFrame:
        path = ui_dir() / "library_album_card.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open library_album_card.ui: {path}")
        try:
            row = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if row is None:
            raise RuntimeError(f"Unable to load library_album_card.ui: {path}")
        row.setObjectName("libraryAlbumCard")
        row.setCursor(Qt.PointingHandCursor)
        row.mousePressEvent = lambda event, album_id=album.album_id: self.open_album_detail(album_id)
        row.mouseDoubleClickEvent = lambda event, album_id=album.album_id: self.read_album_from_card(album_id)

        cover = row.findChild(QLabel, "libraryAlbumCover")
        title = row.findChild(QLabel, "libraryAlbumTitle")
        meta = row.findChild(QLabel, "libraryAlbumMeta")
        tags = row.findChild(QLabel, "libraryAlbumTags")
        detail = row.findChild(QPushButton, "libraryAlbumDetailButton")
        read = row.findChild(QPushButton, "libraryAlbumReadButton")
        queue = row.findChild(QPushButton, "libraryAlbumQueueButton")
        move = row.findChild(QComboBox, "libraryAlbumMoveCombo")
        toggle = row.findChild(QPushButton, "libraryAlbumToggleButton")
        remove = row.findChild(QPushButton, "libraryAlbumRemoveButton")
        required = [cover, title, meta, tags, detail, read, queue, move, toggle, remove]
        if any(widget is None for widget in required):
            raise RuntimeError("library_album_card.ui is missing required controls")

        cover._persistent_cover = True
        cover.setFixedSize(86, 116)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet("background:#f8fafc;border:1px solid #e2e8f0;color:#94a3b8;")
        self.apply_loading_movie(cover, QSize(72, 72))
        self.request_cover(album, cover)

        title.setText(album.title or album.album_id)
        title.setStyleSheet("font-weight:800;color:#1f2937;")
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        meta.setText(f"JM{album.album_id}  |  {album.author or '-'}  |  {album.page_count or '-'}")
        meta.setStyleSheet("color:#64748b;")
        meta.setMinimumWidth(0)
        meta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tags.setText("  ".join((album.tags or [])[:6]))
        tags.setStyleSheet("color:#d65f00;")
        tags.setMinimumWidth(0)
        tags.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        detail.clicked.connect(lambda _=False, album_id=album.album_id: self.open_album_detail(album_id))
        read.clicked.connect(lambda _=False, album_id=album.album_id: self.read_album_from_card(album_id))
        queue.clicked.connect(lambda _=False, album_id=album.album_id: self.add_album_to_queue(album_id))

        move.setVisible(favorite_actions)
        toggle.setVisible(favorite_actions)
        if favorite_actions:
            move.addItem("移动到...", "")
            for folder in self.library_folders:
                if folder.get("id") and folder.get("name"):
                    move.addItem(str(folder["name"]), str(folder["id"]))
            move.currentIndexChanged.connect(
                lambda _=0, box=move, album_id=album.album_id: self.move_library_favorite(album_id, box)
            )
            toggle.clicked.connect(lambda _=False, album_id=album.album_id: self.start_library_action("toggle_favorite", {"album_id": album_id}))

        remove.setVisible(remove_callback is not None)
        if remove_callback is not None:
            remove.clicked.connect(lambda _=False, album_id=album.album_id: remove_callback(album_id))
        return row

    def move_library_favorite(self, album_id: str, box: QComboBox):
        folder_id = str(box.currentData() or "")
        if folder_id:
            self.start_library_action("move_favorite", {"album_id": album_id, "folder_id": folder_id})

    @staticmethod
    def _comment_field(item: Dict, keys: List[str], default: str = "") -> str:
        candidates = [item]
        for nested_key in ("user", "member", "profile", "author", "expinfo"):
            nested = item.get(nested_key)
            if isinstance(nested, dict):
                candidates.append(nested)
        for candidate in candidates:
            for key in keys:
                value = candidate.get(key)
                if value not in (None, ""):
                    return str(value).strip()
        return default

    def comment_avatar_urls(self, photo: str, user_id: str = "") -> List[str]:
        """Return mirror candidates for JM's /media/users/<photo> payload."""
        photo = str(photo or "").strip()
        user_id = str(user_id or "").strip()
        paths = []
        urls = []
        preferred = ""
        if photo:
            parsed = urlparse(photo)
            if parsed.scheme and parsed.netloc:
                paths.append(parsed.path)
                urls.append(photo)
                preferred = parsed.netloc
            else:
                paths.append(photo)
        # App forum responses occasionally omit ``photo``.  Its conventional
        # UID portrait remains a useful fallback, while nopic-*.gif is kept so
        # JM's own default avatar is rendered instead of an initial letter.
        if user_id:
            paths.append(user_media_path(f"{user_id}.jpg"))
        normalized_paths = []
        for path in paths:
            path = str(path or "").strip()
            if not path:
                continue
            normalized_paths.append(user_media_path(path))
        for domain in self.sorted_cover_domains(preferred):
            urls.extend(https_url(domain, path) for path in normalized_paths)
        return self._dedupe_comment_urls(urls)

    @staticmethod
    def _dedupe_comment_urls(urls: List[str]) -> List[str]:
        seen = set()
        result = []
        for url in urls:
            value = str(url or "").strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _comment_avatar_placeholder(self, label: QLabel, _username: str = ""):
        label.setPixmap(QPixmap())
        label.setText("")
        icon_path = resource_dir() / "nav_icons" / "section_user.svg"
        if icon_path.exists():
            icon_size = max(20, min(label.width(), label.height()) - 20)
            label.setPixmap(QIcon(str(icon_path)).pixmap(icon_size, icon_size))
        label.setAlignment(Qt.AlignCenter)

    @staticmethod
    def set_comment_avatar_on_label(label: QLabel, pixmap: QPixmap):
        """Crop avatar artwork into the fixed rounded-square JM comment slot."""
        try:
            if pixmap.isNull():
                return
            size = label.contentsRect().size()
            if size.isEmpty():
                return
            source = pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            left = max(0, (source.width() - size.width()) // 2)
            top = max(0, (source.height() - size.height()) // 2)
            source = source.copy(left, top, size.width(), size.height())
            rounded = QPixmap(size)
            rounded.fill(Qt.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.Antialiasing)
            clip = QPainterPath()
            clip.addRoundedRect(0.0, 0.0, float(size.width()), float(size.height()), 12.0, 12.0)
            painter.setClipPath(clip)
            painter.drawPixmap(0, 0, source)
            painter.end()
            label.setText("")
            label.setPixmap(rounded)
        except RuntimeError:
            pass

    def request_comment_avatar(self, photo: str, user_id: str, label: QLabel, username: str):
        self._comment_avatar_placeholder(label, username)
        if self._test_mode:
            return
        urls = self.comment_avatar_urls(photo, user_id)
        if not urls:
            return
        avatar_key = hashlib.sha1(urls[0].encode("utf-8")).hexdigest()
        cached = self.comment_avatar_cache.get(avatar_key)
        if cached is not None:
            self.set_comment_avatar_on_label(label, cached)
            return
        self.comment_avatar_targets.setdefault(avatar_key, []).append(label)
        if avatar_key in self.comment_avatar_workers or avatar_key in self.comment_avatar_queued:
            return
        self.comment_avatar_queue.append((avatar_key, urls))
        self.comment_avatar_queued.add(avatar_key)
        self.drain_comment_avatar_queue()

    def drain_comment_avatar_queue(self):
        while self.comment_avatar_queue and len(self.comment_avatar_workers) < min(4, COVER_REQUEST_CONCURRENCY):
            avatar_key, urls = self.comment_avatar_queue.pop(0)
            self.comment_avatar_queued.discard(avatar_key)
            if avatar_key not in self.comment_avatar_targets:
                continue
            self.start_comment_avatar_request(avatar_key, urls)

    def start_comment_avatar_request(self, avatar_key: str, urls: List[str]):
        worker = CoverFetchWorker(
            avatar_key,
            urls,
            self.effective_proxy(),
            self.api_domain_pool[0] if self.api_domain_pool else API_DOMAINS[0],
            doh_enabled=self.doh_enabled_box.isChecked(),
            doh_url=self.doh_url_edit.text().strip() or DOH_URL,
            parent=self,
        )
        self.comment_avatar_workers[avatar_key] = worker
        worker.loaded.connect(self.on_comment_avatar_loaded)
        worker.failed.connect(self.on_comment_avatar_failed)
        worker.finished.connect(lambda worker=worker: worker.deleteLater())
        worker.start()

    def on_comment_avatar_loaded(self, avatar_key: str, data: bytes, _url: str, _failed_urls):
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            self.on_comment_avatar_failed(avatar_key, "头像数据无法转换为 Pixmap", [])
            return
        self.comment_avatar_cache[avatar_key] = pixmap
        labels = self.comment_avatar_targets.pop(avatar_key, [])
        self.comment_avatar_workers.pop(avatar_key, None)
        for label in labels:
            self.set_comment_avatar_on_label(label, pixmap)
        self.drain_comment_avatar_queue()

    def on_comment_avatar_failed(self, avatar_key: str, _message: str, _failed_urls):
        self.comment_avatar_targets.pop(avatar_key, None)
        self.comment_avatar_workers.pop(avatar_key, None)
        self.drain_comment_avatar_queue()

    @staticmethod
    def clean_comment_content(content: str) -> str:
        """Forum comments are HTML fragments; render their text, never markup."""
        text = str(content or "")
        text = re.sub(r"(?is)<(?:script|style)[^>]*>.*?</(?:script|style)>", "", text)
        text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
        text = re.sub(r"(?i)</\s*(?:div|p|li|tr|h[1-6])\s*>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", "", text)
        text = unescape(text).replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[\t\f\v ]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def create_comment_card(self, item: Dict, index: int) -> QFrame:
        return self.build_comment_card(item, index)

    def prepare_comment_reply(self, comment_id: str):
        self.library_comment_reply_edit.setText(str(comment_id))
        self.library_comment_input.setFocus(Qt.ShortcutFocusReason)

    def open_comment_replies(self, replies: List[Dict], parent_comment_id: str):
        """Match JMComic-qt's reply action: inspect children, then reply to the parent."""
        dialog = QDialog(self)
        dialog.setWindowTitle("评论回复")
        dialog.resize(680, 540)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addStretch(1)
        for index, reply in enumerate(replies, start=1):
            if isinstance(reply, dict):
                content_layout.insertWidget(max(0, content_layout.count() - 1), self.create_comment_card(reply, index))
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        reply_button = QPushButton("回复此评论", dialog)
        reply_button.setObjectName("primaryButton")
        reply_button.clicked.connect(
            lambda _=False, comment_id=parent_comment_id: (self.prepare_comment_reply(comment_id), dialog.accept())
        )
        close_button = QPushButton("关闭", dialog)
        close_button.clicked.connect(dialog.reject)
        actions.addWidget(reply_button)
        actions.addWidget(close_button)
        root.addLayout(actions)
        dialog.exec()

    def render_library_comments(self, comments: List[Dict], total: int):
        self.set_library_route_count("commentsTab", total, "条")
        self.render_comment_center(comments, total)

    def build_history_settings_menu(self) -> QMenu:
        menu = QMenu(self)
        self.history_format_actions = {}
        self.history_view_actions = {}
        self.history_read_mode_actions = {}

        format_menu = menu.addMenu("显示格式")
        for text in ["全部", "图片", "PDF", "ZIP"]:
            action = format_menu.addAction(text)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, value=text: self.set_history_combo_text(self.history_format_filter_combo, value))
            self.history_format_actions[text] = action

        view_menu = menu.addMenu("视图")
        for text in ["竖列", "九宫格"]:
            action = view_menu.addAction(text)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, value=text: self.set_history_combo_text(self.history_view_combo, value))
            self.history_view_actions[text] = action

        read_menu = menu.addMenu("阅读格式")
        for text in ["自动", "PDF", "原文件"]:
            action = read_menu.addAction(text)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, value=text: self.set_history_combo_text(self.history_read_mode_combo, value))
            self.history_read_mode_actions[text] = action

        menu.addSeparator()
        menu.addAction("扫描本地", self.sync_local_history_from_button)
        menu.addSeparator()
        menu.addAction("清空历史", self.clear_download_history)
        menu.aboutToShow.connect(self.sync_history_settings_menu_state)
        return menu

    @staticmethod
    def set_history_combo_text(combo: QComboBox, text: str):
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def sync_history_settings_menu_state(self):
        for text, action in getattr(self, "history_format_actions", {}).items():
            action.setChecked(self.history_format_filter_combo.currentText() == text)
        for text, action in getattr(self, "history_view_actions", {}).items():
            action.setChecked(self.history_view_combo.currentText() == text)
        for text, action in getattr(self, "history_read_mode_actions", {}).items():
            action.setChecked(self.history_read_mode_combo.currentText() == text)

    def refresh_history_table(self):
        if self.refresh_history_feed_if_ready():
            return
        if not hasattr(self, "history_cards_layout"):
            return
        self.cleanup_history_drag_artifacts()
        refresh_key = self.current_history_refresh_key()
        if refresh_key == self.history_refresh_key and self.history_cards_layout.count() > 1:
            return
        self.history_refresh_key = refresh_key
        self.history_render_generation += 1
        self.history_cover_queue.clear()
        self.history_local_cover_labels.clear()
        self.history_cover_timer.stop()
        self.history_card_by_index.clear()
        while self.history_cards_layout.count() > 1:
            item = self.history_cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.selected_history_index = -1 if not self.download_history else min(
            max(self.selected_history_index, -1),
            len(self.download_history) - 1,
        )
        visible_records = [
            (source_index, record)
            for source_index, record in enumerate(self.download_history)
            if self.history_record_matches_format_filter(record)
        ]
        visible_indexes = {source_index for source_index, _ in visible_records}
        if self.selected_history_index not in visible_indexes:
            self.selected_history_index = -1
        self.history_visible_records = list(reversed(visible_records))
        self.history_render_limit = min(self.history_render_batch, len(self.history_visible_records) or self.history_render_batch)
        self.render_history_cards(reset_scroll=True)
        if not self.history_visible_records:
            empty = self.create_history_card({"title": "No history", "file": "Downloaded comics will appear here", "path": ""}, -1)
            self.history_cards_layout.insertWidget(0, empty)

    def current_history_refresh_key(self):
        combo = getattr(self, "history_format_filter_combo", None)
        selected = combo.currentText() if combo else "全部"
        view_mode = self.current_history_view_mode()
        records_key = tuple(
            (
                record.get("album_id") or record.get("id") or "",
                record.get("path") or "",
                record.get("pdf_path") or "",
                record.get("image_dir") or "",
                record.get("format") or "",
                record.get("last_page") or "",
                record.get("last_total") or "",
            )
            for record in self.download_history
        )
        return selected, view_mode, records_key

    def current_history_view_mode(self) -> str:
        combo = getattr(self, "history_view_combo", None)
        text = combo.currentText() if combo else ""
        return "grid" if text == "九宫格" else "list"

    def change_history_view_mode(self, *_):
        self.history_view_mode = self.current_history_view_mode()
        self.history_refresh_key = None
        self.history_render_limit = min(self.history_render_batch, len(getattr(self, "history_visible_records", [])) or self.history_render_batch)
        self.refresh_history_table()

    def render_history_cards(self, reset_scroll: bool = False):
        if not hasattr(self, "history_cards_layout"):
            return
        self.cleanup_history_drag_artifacts()
        self.history_render_generation += 1
        self.history_cover_queue.clear()
        self.history_local_cover_labels.clear()
        self.history_cover_timer.stop()
        self.history_card_by_index.clear()
        while self.history_cards_layout.count() > 1:
            item = self.history_cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.append_history_cards(0, self.history_render_limit)
        if reset_scroll:
            QTimer.singleShot(0, lambda: self.history_scroll.verticalScrollBar().setValue(0))

    def append_history_cards(self, start: int, end: int):
        if not hasattr(self, "history_cards_layout"):
            return
        if self.current_history_view_mode() == "grid":
            self.append_history_grid_cards(start, end)
            return
        insert_at = max(0, self.history_cards_layout.count() - 1)
        for source_index, record in self.history_visible_records[start:end]:
            if source_index in self.history_card_by_index:
                continue
            card = self.create_history_card(record, source_index)
            self.history_card_by_index[source_index] = card
            self.history_cards_layout.insertWidget(insert_at, card)
            insert_at += 1

    def append_history_grid_cards(self, start: int, end: int):
        columns = self.history_grid_column_count()
        insert_at = max(0, self.history_cards_layout.count() - 1)
        batch = self.history_visible_records[start:end]
        for row_start in range(0, len(batch), columns):
            row_widget = self.load_ui_widget("history_grid_row.ui", QWidget)
            row_layout = row_widget.findChild(QHBoxLayout, "historyGridRowLayout")
            if row_layout is None:
                raise RuntimeError("history_grid_row.ui is missing layout")
            for source_index, record in batch[row_start:row_start + columns]:
                if source_index in self.history_card_by_index:
                    continue
                card = self.create_history_card(record, source_index)
                self.history_card_by_index[source_index] = card
                row_layout.addWidget(card)
            row_layout.addStretch()
            self.history_cards_layout.insertWidget(insert_at, row_widget)
            insert_at += 1

    def history_grid_column_count(self) -> int:
        viewport_width = self.history_scroll.viewport().width() if hasattr(self, "history_scroll") else self.width()
        return max(2, min(6, viewport_width // 168))

    def on_history_scroll_value_changed(self, value: int):
        if not getattr(self, "history_visible_records", None):
            return
        bar = self.history_scroll.verticalScrollBar()
        if value < bar.maximum() - 36:
            return
        if self.history_render_limit >= len(self.history_visible_records):
            return
        old_limit = self.history_render_limit
        self.history_render_limit = min(len(self.history_visible_records), self.history_render_limit + self.history_render_batch)
        self.append_history_cards(old_limit, self.history_render_limit)

    def history_record_matches_format_filter(self, record: Dict[str, str]) -> bool:
        combo = getattr(self, "history_format_filter_combo", None)
        selected = combo.currentText() if combo else "全部"
        if selected == "全部":
            return True
        fmt = (record.get("format") or "").lower()
        path_texts = [record.get("path") or "", record.get("pdf_path") or "", record.get("image_dir") or ""]
        outputs = record.get("outputs") or []
        if isinstance(outputs, list):
            path_texts.extend(str(value) for value in outputs)
        suffixes = {Path(text).suffix.lower().lstrip(".") for text in path_texts if str(text).strip()}
        if selected == "PDF":
            return fmt == "pdf" or "pdf" in suffixes
        if selected == "ZIP":
            return fmt == "zip" or "zip" in suffixes
        if selected == "图片":
            return fmt in {"images", "image"} or bool(record.get("image_dir")) or any(suffix in {item.lstrip(".") for item in IMAGE_SUFFIXES} for suffix in suffixes)
        return True

    def create_history_card(self, record: Dict[str, str], index: int) -> QFrame:
        if self.current_history_view_mode() == "grid":
            return self.create_history_grid_card(record, index)
        card = self.load_history_list_card()
        card.setObjectName("historyCard")
        card.setProperty("selected", index == self.selected_history_index)
        card.setProperty("history_index", index)
        card.setMinimumHeight(148)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setStyleSheet(self.history_card_style(index == self.selected_history_index))

        cover = self.require_history_card_child(card, QLabel, "historyCover")
        cover._persistent_cover = True
        cover.setFixedSize(96, 128)
        cover.setAlignment(Qt.AlignCenter)
        cover.setText("封面")
        self.queue_history_cover(record, cover)

        title_text = record.get("title") or Path(record.get("path", "")).stem or "Untitled comic"
        title_label = self.require_history_card_child(card, QLabel, "historyTitle")
        title_label.setText(QFontMetrics(self.font()).elidedText(title_text, Qt.ElideRight, 440))
        title_label.setToolTip(title_text)
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        file_text = record.get("file") or Path(record.get("path", "")).name or "-"
        meta_items = [file_text]
        fmt = record.get("format") or Path(file_text).suffix.lstrip(".").upper()
        if fmt:
            meta_items.append(fmt.upper())
        outputs = record.get("outputs") or []
        if isinstance(outputs, list) and len(outputs) > 1:
            meta_items.append(f"{len(outputs)} 个文件")
        album_id = record.get("album_id") or record.get("id") or ""
        last_page = self.history_record_last_page(record)
        if last_page:
            meta_items.append(f"看到第 {last_page} 页")
        meta_text = "  ·  ".join(meta_items)
        meta_label = self.require_history_card_child(card, QLabel, "historyMeta")
        meta_label.setText(QFontMetrics(self.font()).elidedText(meta_text, Qt.ElideRight, 520))
        meta_label.setToolTip(meta_text)
        meta_label.setMinimumWidth(0)
        meta_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        fixed_items = []
        if album_id:
            fixed_items.append(f"ID {album_id}")
        if last_page:
            fixed_items.append(f"看到第 {last_page} 页")
        fixed_label = self.require_history_card_child(card, QLabel, "historyFixedMeta")
        if fixed_items:
            fixed_text = "  ·  ".join(fixed_items)
            fixed_label.setText(fixed_text)
            fixed_label.setToolTip(fixed_text)
            fixed_label.setMinimumWidth(0)
            fixed_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            fixed_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            fixed_label.setVisible(True)
        else:
            fixed_label.clear()
            fixed_label.setVisible(False)

        path_text = record.get("path", "") or record.get("pdf_path", "") or record.get("image_dir", "")
        path_label = self.require_history_card_child(card, QLabel, "historyPath")
        path_label.setText(QFontMetrics(self.font()).elidedText(path_text, Qt.ElideMiddle, 520))
        path_label.setToolTip(path_text)
        path_label.setMinimumWidth(0)
        path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        read = self.require_history_card_child(card, QPushButton, "historyReadButton")
        read.setObjectName("historyAction")
        read.clicked.connect(lambda checked=False, idx=index: self.select_history_record(idx, open_reader=True))
        locate = self.require_history_card_child(card, QPushButton, "historyLocateButton")
        locate.setObjectName("historyAction")
        locate.clicked.connect(lambda checked=False, idx=index: self.select_history_record(idx, open_location=True))
        status = self.require_history_card_child(card, QLabel, "historyBadge")
        status.setText("Done" if index >= 0 else "-")
        status.setAlignment(Qt.AlignCenter)

        if index >= 0:
            card.setCursor(Qt.PointingHandCursor)
            card.mousePressEvent = lambda event, idx=index, widget=card: self.handle_history_card_mouse_press(event, idx, widget)
            card.mouseMoveEvent = lambda event, idx=index, widget=card: self.handle_history_card_mouse_move(event, idx, widget)
            card.mouseReleaseEvent = lambda event, idx=index, widget=card: self.handle_history_card_mouse_release(event, idx, widget)
            card.mouseDoubleClickEvent = lambda event, idx=index: self.select_history_record(idx, open_reader=True)
        return card

    def load_history_list_card(self) -> QFrame:
        path = ui_dir() / "history_list_card.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open history_list_card.ui: {path}")
        try:
            card = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if card is None:
            raise RuntimeError(f"Unable to load history_list_card.ui: {path}")
        return card

    @staticmethod
    def require_history_card_child(card: QFrame, widget_type, object_name: str):
        widget = card.findChild(widget_type, object_name)
        if widget is None:
            raise RuntimeError(f"history_list_card.ui is missing required control: {object_name}")
        return widget

    def create_history_grid_card(self, record: Dict[str, str], index: int) -> QFrame:
        path = ui_dir() / "history_grid_card.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open history_grid_card.ui: {path}")
        try:
            card = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if card is None:
            raise RuntimeError(f"Unable to load history_grid_card.ui: {path}")
        card.setObjectName("historyGridCard")
        card.setProperty("selected", index == self.selected_history_index)
        card.setProperty("history_index", index)
        card.setFixedWidth(146)
        card.setMinimumHeight(238)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        card.setStyleSheet(self.history_card_style(index == self.selected_history_index, grid=True))

        cover_box = card.findChild(QFrame, "historyGridCoverBox")
        cover = card.findChild(QLabel, "historyGridCover")
        progress = card.findChild(QLabel, "historyGridProgress")
        badge = card.findChild(QLabel, "historyGridReadBadge")
        title = card.findChild(QLabel, "historyGridTitle")
        required = [cover_box, cover, progress, badge, title]
        if any(widget is None for widget in required):
            raise RuntimeError("history_grid_card.ui is missing required controls")
        cover._persistent_cover = True
        cover.setAlignment(Qt.AlignCenter)
        self.queue_history_cover(record, cover)

        title_text = record.get("title") or Path(record.get("path", "")).stem or "Untitled comic"
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        title.setToolTip(title_text)
        title.setFixedHeight(48)
        title.setText(title_text)
        progress.setText(self.history_read_progress_text(record))
        progress.adjustSize()
        badge.adjustSize()

        if index >= 0:
            card.setCursor(Qt.PointingHandCursor)
            card.mousePressEvent = lambda event, idx=index, widget=card: self.handle_history_card_mouse_press(event, idx, widget)
            card.mouseMoveEvent = lambda event, idx=index, widget=card: self.handle_history_card_mouse_move(event, idx, widget)
            card.mouseReleaseEvent = lambda event, idx=index, widget=card: self.handle_history_card_mouse_release(event, idx, widget)
            card.mouseDoubleClickEvent = lambda event, idx=index: self.select_history_record(idx, open_reader=True)
        return card

    def history_read_progress_text(self, record: Dict[str, str]) -> str:
        page = self.history_record_last_page(record)
        total = self.history_record_last_total(record)
        if page > 0 and total > 0:
            if page >= total:
                return "已读完"
            return f"{max(0, min(100, int(page * 100 / total)))}%"
        if page > 0:
            return f"第{page}页"
        return "0%"

    def queue_history_cover(self, record: Dict[str, str], label: QLabel):
        generation = self.history_render_generation
        label._history_generation = generation
        album_id = record.get("album_id") or record.get("id") or ""
        if album_id:
            label._album_id = album_id
        self.history_cover_queue.append((generation, record, label))
        if not self.history_cover_timer.isActive():
            self.history_cover_timer.start(20)

    def flush_history_cover_queue(self):
        generation = self.history_render_generation
        processed = 0
        while self.history_cover_queue and processed < 2:
            item_generation, record, label = self.history_cover_queue.pop(0)
            if item_generation != generation or getattr(label, "_history_generation", None) != generation:
                continue
            try:
                self.apply_history_cover(record, label)
            except RuntimeError:
                pass
            processed += 1
        if self.history_cover_queue:
            self.history_cover_timer.start(35)

    def history_card_style(self, selected: bool = False, grid: bool = False) -> str:
        if grid:
            border = "#f3c768" if selected else "transparent"
            background = "#fff7df" if selected else "transparent"
            glow = "rgba(245, 158, 11, 80)" if selected else "rgba(15, 23, 42, 36)"
            return f"""
                QFrame#historyGridCard {{
                    background:{background};
                    border:2px solid {border};
                    border-radius:10px;
                }}
                QFrame#historyGridCoverBox {{
                    background:#eef0f4;
                    border-radius:11px;
                    border:1px solid rgba(148,163,184,120);
                }}
                QLabel#historyGridCover {{
                    background:#eef0f4;
                    border-radius:11px;
                    color:#8b95a5;
                }}
                QLabel#historyGridTitle {{
                    color:#111827;
                    font-size:16px;
                    font-weight:800;
                    background:transparent;
                }}
                QLabel#historyGridProgress {{
                    color:#ffffff;
                    background:rgba(15,23,42,120);
                    border-radius:8px;
                    padding:1px 5px;
                    font-size:14px;
                    font-weight:900;
                }}
                QLabel#historyGridReadBadge {{
                    color:#111827;
                    background:#ffffff;
                    border:3px solid #111827;
                    border-radius:16px;
                    font-size:13px;
                    font-weight:900;
                }}
                QFrame#historyGridCard[selected="true"] QFrame#historyGridCoverBox {{
                    border:2px solid #f59e0b;
                    background:{glow};
                }}
            """
        border = "#2f80ed" if selected else "#dfe7f2"
        background = "#f8fbff" if selected else "#ffffff"
        return f"""
            QFrame#historyCard {{
                background:{background};
                border:1px solid {border};
                border-radius:8px;
            }}
            QLabel#historyCover {{
                background:#eef3f8;
                border:1px solid #dbe5f0;
                border-radius:6px;
                color:#8491a5;
            }}
            QLabel#historyTitle {{
                font-weight:800;
                color:#1f2937;
                font-size:13px;
            }}
            QLabel#historyMeta, QLabel#historyPath {{
                color:#64748b;
                font-size:12px;
            }}
            QLabel#historyFixedMeta {{
                color:#1d4ed8;
                font-size:12px;
                font-weight:800;
            }}
            QLabel#historyBadge {{
                background:#eaf7ef;
                color:#16794c;
                border:1px solid #ccebd8;
                border-radius:10px;
                padding:2px 8px;
                font-size:12px;
                font-weight:700;
            }}
            QPushButton#historyAction {{
                padding:4px 10px;
                border-radius:6px;
            }}
        """

    def apply_history_cover(self, record: Dict[str, str], label: QLabel):
        album_id = record.get("album_id") or record.get("id") or ""
        cover_url = record.get("cover_url") or ""
        label._history_record = copy.deepcopy(record)
        cache_key = self.history_cover_cache_key(record)
        label._history_local_cover_key = cache_key
        if self.set_history_cached_local_cover(record, label):
            return
        if album_id and album_id in self.cover_cache:
            self.set_cover_on_label(label, self.cover_cache[album_id])
            self.schedule_history_local_cover(record, label)
            return
        if album_id:
            album = self.detail_cache.get(album_id) or self.albums.get(album_id)
            if album:
                self.apply_loading_movie(label, QSize(72, 72))
                self.request_cover(album, label)
                self.schedule_history_local_cover(record, label)
                return
            album = AlbumMeta(album_id=album_id, title=record.get("title", ""), url="", cover_url=cover_url)
            self.apply_loading_movie(label, QSize(72, 72))
            self.request_cover(album, label)
            self.schedule_history_local_cover(record, label)
            return
        label.setText("本地")
        self.schedule_history_local_cover(record, label)

    def set_history_cached_local_cover(self, record: Dict[str, str], label: QLabel) -> bool:
        cache_key = self.history_cover_cache_key(record)
        cached = self.history_local_cover_cache.get(cache_key)
        if not cached:
            return False
        cached_path = Path(cached)
        if not cached_path.exists():
            self.history_local_cover_cache.pop(cache_key, None)
            return False
        pixmap = self.load_local_cover_pixmap(cached_path)
        if pixmap.isNull():
            return False
        album_id = record.get("album_id") or record.get("id") or ""
        if album_id:
            self.cover_cache[album_id] = pixmap
        self.stop_label_movie(label)
        self.set_cover_on_label(label, pixmap)
        return True

    def schedule_history_local_cover(self, record: Dict[str, str], label: QLabel):
        cache_key = self.history_cover_cache_key(record)
        if not cache_key:
            return
        labels = self.history_local_cover_labels.setdefault(cache_key, [])
        if label not in labels:
            labels.append(label)
        if cache_key in self.history_local_cover_workers:
            return
        worker = HistoryLocalCoverWorker(cache_key, record, self)
        self.history_local_cover_workers[cache_key] = worker
        worker.resolved.connect(self.on_history_local_cover_resolved)
        worker.failed.connect(lambda key, message: self.log(f"本地历史封面查找失败：{message}") if key in self.history_local_cover_workers else None)
        worker.finished.connect(lambda cache_key=cache_key: self.cleanup_history_local_cover_worker(cache_key))
        worker.start()

    def on_history_local_cover_resolved(self, cache_key: str, path_text: str):
        if not path_text:
            return
        path = Path(path_text)
        if not path.exists():
            return
        self.history_local_cover_cache[cache_key] = str(path)
        pixmap = self.load_local_cover_pixmap(path)
        if pixmap.isNull():
            return
        for label in list(self.history_local_cover_labels.get(cache_key, [])):
            if getattr(label, "_history_local_cover_key", "") != cache_key:
                continue
            try:
                self.stop_label_movie(label)
                self.set_cover_on_label(label, pixmap)
            except RuntimeError:
                continue

    def cleanup_history_local_cover_worker(self, cache_key: str):
        worker = self.history_local_cover_workers.pop(cache_key, None)
        if worker is not None:
            worker.deleteLater()
    def set_history_local_cover(self, record: Dict[str, str], label: QLabel) -> bool:
        local_cover = self.find_history_local_cover(record)
        if not local_cover:
            return False
        pixmap = self.load_local_cover_pixmap(local_cover)
        if pixmap.isNull():
            return False
        album_id = record.get("album_id") or record.get("id") or ""
        if album_id:
            self.cover_cache[album_id] = pixmap
        self.stop_label_movie(label)
        self.set_cover_on_label(label, pixmap)
        return True

    @staticmethod
    def load_local_cover_pixmap(path: Path) -> QPixmap:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if not image.isNull():
            return QPixmap.fromImage(image)
        return QPixmap(str(path))

    def find_history_local_cover(self, record: Dict[str, str]) -> Optional[Path]:
        cache_key = self.history_cover_cache_key(record)
        cached = self.history_local_cover_cache.get(cache_key)
        if cached:
            cached_path = Path(cached)
            if cached_path.exists():
                return cached_path
            self.history_local_cover_cache.pop(cache_key, None)
        local_cover = find_history_local_cover_path(record)
        if local_cover:
            self.history_local_cover_cache[cache_key] = str(local_cover)
        return local_cover

    @staticmethod
    def history_cover_cache_key(record: Dict[str, str]) -> str:
        return history_cover_cache_key_from_record(record)

    def select_history_record(self, index: int, open_reader: bool = False, open_location: bool = False):
        if index < 0 or index >= len(self.download_history):
            return
        old_index = self.selected_history_index
        self.selected_history_index = index
        for idx in {old_index, index}:
            card = self.history_card_by_index.get(idx)
            if card:
                self.set_history_card_selected(card, idx == self.selected_history_index)
        if open_reader:
            self.open_selected_history_reading()
        elif open_location:
            self.open_selected_history_location()

    def set_history_card_selected(self, card: QWidget, selected: bool):
        card.setProperty("selected", selected)
        card.setStyleSheet(self.history_card_style(selected, grid=card.objectName() == "historyGridCard"))

    def handle_history_card_mouse_press(self, event, index: int, card: Optional[QWidget] = None):
        if index < 0 or index >= len(self.download_history):
            return
        if event.button() == Qt.RightButton:
            self.select_history_record(index)
            self.show_history_context_menu(index, event.globalPos())
            return
        if event.button() == Qt.LeftButton:
            self.select_history_record(index)
            self.history_drag_index = index
            self.history_drag_record = self.download_history[index]
            self.history_drag_start_pos = event.globalPos()
            self.history_drag_card = card
            self.history_dragging = False

    def handle_history_card_mouse_move(self, event, index: int, card: Optional[QWidget] = None):
        if self.history_drag_index < 0 or self.history_drag_record is None or self.history_drag_start_pos is None:
            return
        if self.current_history_view_mode() == "grid":
            return
        combo = getattr(self, "history_format_filter_combo", None)
        if combo and combo.currentText() != "全部":
            return
        if not self.history_dragging:
            delta = event.globalPos() - self.history_drag_start_pos
            if delta.manhattanLength() < 10:
                return
            self.start_history_drag(card)
        self.update_history_drag_ghost(event.globalPos())
        self.autoscroll_history_drag(event.globalPos())

    def handle_history_card_mouse_release(self, event, index: int, card: Optional[QWidget] = None):
        self.complete_history_drag(commit=True)
        return
        if self.history_dragging:
            new_display_order = self.history_display_order_from_placeholder()
            current_display_order = [idx for idx, _ in self.history_visible_records]
            self.finish_history_drag()
            if new_display_order and new_display_order != current_display_order:
                self.apply_history_display_order(new_display_order)
                self.save_local_cache()
                self.show_toast("历史顺序已保存")
        self.history_drag_index = -1
        self.history_drag_record = None
        self.history_drag_start_pos = None
        self.history_dragging = False
        self.history_drag_card = None

    def start_history_drag(self, card: Optional[QWidget]):
        if card is None:
            return
        self.cleanup_history_drag_artifacts()
        self.history_dragging = True
        self.history_drag_card = card
        self.history_drag_last_move_at = 0.0
        placeholder = self.create_history_drop_placeholder(card.height())
        insert_at = self.history_layout_index_of(card)
        self.history_cards_layout.insertWidget(max(0, insert_at), placeholder)
        effect = QGraphicsOpacityEffect(card)
        effect.setOpacity(0.34)
        card.setGraphicsEffect(effect)
        self.history_drag_opacity = effect
        self.history_drop_placeholder = placeholder
        self.history_drop_index = max(0, insert_at)
        self.refresh_history_drag_targets()

        viewport = self.history_scroll.viewport() if hasattr(self, "history_scroll") else self
        ghost = self.load_ui_widget("history_drag_ghost.ui", QLabel, viewport)
        ghost.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        ghost_width = min(card.width(), max(260, viewport.width() - 18))
        ghost_height = card.height()
        title = ""
        if isinstance(self.history_drag_record, dict):
            title = self.history_drag_record.get("title") or self.history_drag_record.get("file") or ""
        ghost.setText(QFontMetrics(self.font()).elidedText(title or "移动历史记录", Qt.ElideRight, max(120, ghost_width - 28)))
        ghost.setAlignment(Qt.AlignCenter)
        ghost.setFixedSize(ghost_width, ghost_height)
        ghost.setStyleSheet("color:#0f172a;border:1px solid #93c5fd;border-radius:14px;background:rgba(255,255,255,232);font-size:13px;font-weight:800;")
        ghost.show()
        ghost.raise_()
        self.history_drag_ghost = ghost

    def create_history_drop_placeholder(self, height: int) -> QFrame:
        placeholder = self.load_ui_widget("history_drop_placeholder.ui", QFrame)
        marker_height = max(10, min(16, height // 8 if height else 12))
        placeholder.setFixedHeight(marker_height)
        placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        placeholder.setStyleSheet(
            """
            QFrame#historyDropPlaceholder {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(59,130,246,60), stop:0.5 rgba(37,99,235,210), stop:1 rgba(59,130,246,60));
                border:1px solid rgba(37,99,235,120);
                border-radius:6px;
            }
            """
        )
        effect = QGraphicsOpacityEffect(placeholder)
        effect.setOpacity(0.86)
        placeholder.setGraphicsEffect(effect)
        return placeholder

    def update_history_drag_ghost(self, global_pos):
        ghost = self.history_drag_ghost
        if ghost is None:
            return
        now = time.monotonic()
        if now - self.history_drag_last_move_at < 0.035:
            return
        self.history_drag_last_move_at = now
        viewport = self.history_scroll.viewport() if hasattr(self, "history_scroll") else self
        local_pos = viewport.mapFromGlobal(global_pos)
        if (
            local_pos.x() < -90
            or local_pos.x() > viewport.width() + 90
            or local_pos.y() < -140
            or local_pos.y() > viewport.height() + 140
        ):
            self.complete_history_drag(commit=False)
            return
        x = local_pos.x() - ghost.width() // 2
        y = local_pos.y() - ghost.height() // 2
        x = max(6, min(x, max(6, viewport.width() - ghost.width() - 6)))
        y = max(6, min(y, max(6, viewport.height() - ghost.height() - 6)))
        ghost.move(x, y)
        ghost.raise_()
        self.move_history_drop_placeholder(global_pos.y())

    def autoscroll_history_drag(self, global_pos):
        if not hasattr(self, "history_scroll"):
            return
        now = time.monotonic()
        if now - self.history_drag_last_autoscroll_at < 0.055:
            return
        self.history_drag_last_autoscroll_at = now
        viewport = self.history_scroll.viewport()
        local = viewport.mapFromGlobal(global_pos)
        bar = self.history_scroll.verticalScrollBar()
        margin = 42
        if local.y() < margin:
            old_value = bar.value()
            bar.setValue(max(bar.minimum(), old_value - 12))
            if bar.value() != old_value:
                self.refresh_history_drag_targets()
        elif local.y() > viewport.height() - margin:
            old_value = bar.value()
            bar.setValue(min(bar.maximum(), old_value + 12))
            if bar.value() != old_value:
                self.refresh_history_drag_targets()

    def finish_history_drag(self):
        if self.history_drop_placeholder is not None:
            self.history_cards_layout.removeWidget(self.history_drop_placeholder)
            self.history_drop_placeholder.deleteLater()
        if self.history_drag_card is not None:
            self.history_drag_card.setGraphicsEffect(None)
            self.history_drag_card.show()
        if self.history_drag_ghost is not None:
            self.history_drag_ghost.hide()
            self.history_drag_ghost.deleteLater()
        self.history_drag_ghost = None
        self.history_drag_opacity = None
        self.history_drop_placeholder = None
        self.history_drop_index = -1

    def complete_history_drag(self, commit: bool = True):
        if not self.history_dragging:
            self.reset_history_drag_state()
            return
        new_display_order = self.history_display_order_from_placeholder() if commit else []
        current_display_order = [idx for idx, _ in self.history_visible_records]
        self.finish_history_drag()
        if commit and new_display_order and new_display_order != current_display_order:
            self.apply_history_display_order(new_display_order)
            self.save_local_cache()
            self.show_toast("\u5386\u53f2\u987a\u5e8f\u5df2\u4fdd\u5b58")
        self.reset_history_drag_state()
        self.cleanup_history_drag_artifacts()

    def reset_history_drag_state(self):
        self.history_drag_index = -1
        self.history_drag_record = None
        self.history_drag_start_pos = None
        self.history_dragging = False
        self.history_drag_card = None
        self.history_drag_last_move_at = 0.0
        self.history_drag_last_autoscroll_at = 0.0
        self.history_drag_target_centers = []

    def cleanup_history_drag_artifacts(self):
        if self.history_drag_card is not None:
            self.history_drag_card.setGraphicsEffect(None)
            self.history_drag_card.show()
        if self.history_drag_ghost is not None:
            self.history_drag_ghost.hide()
            self.history_drag_ghost.deleteLater()
            self.history_drag_ghost = None
        if hasattr(self, "history_scroll"):
            for ghost in self.history_scroll.viewport().findChildren(QLabel, "historyDragGhost"):
                ghost.hide()
                ghost.deleteLater()
        if hasattr(self, "history_cards_layout"):
            for layout_index in range(self.history_cards_layout.count() - 1, -1, -1):
                item = self.history_cards_layout.itemAt(layout_index)
                widget = item.widget() if item else None
                if widget is not None and widget.objectName() == "historyDropPlaceholder":
                    self.history_cards_layout.removeWidget(widget)
                    widget.deleteLater()
        self.history_drop_placeholder = None
        self.history_drop_index = -1
        self.history_drag_target_centers = []

    def history_layout_index_of(self, widget: QWidget) -> int:
        for index in range(self.history_cards_layout.count()):
            item = self.history_cards_layout.itemAt(index)
            if item and item.widget() is widget:
                return index
        return max(0, self.history_cards_layout.count() - 1)

    def refresh_history_drag_targets(self):
        if not hasattr(self, "history_cards_layout"):
            self.history_drag_target_centers = []
            return
        targets: List[tuple[int, int]] = []
        for layout_index in range(self.history_cards_layout.count()):
            item = self.history_cards_layout.itemAt(layout_index)
            widget = item.widget() if item else None
            if widget is None or widget is self.history_drop_placeholder or widget is self.history_drag_card:
                continue
            if widget.objectName() == "historyDropPlaceholder":
                continue
            targets.append((layout_index, widget.mapToGlobal(widget.rect().center()).y()))
        self.history_drag_target_centers = targets

    def move_history_drop_placeholder(self, global_y: int):
        placeholder = self.history_drop_placeholder
        if placeholder is None:
            return
        if not self.history_drag_target_centers:
            self.refresh_history_drag_targets()
        target_index = max(0, self.history_cards_layout.count() - 1)
        for layout_index, center_y in self.history_drag_target_centers:
            if global_y <= center_y:
                target_index = layout_index
                break
        current_index = self.history_drop_index if self.history_drop_index >= 0 else self.history_layout_index_of(placeholder)
        if target_index > current_index:
            target_index -= 1
        target_index = max(0, min(target_index, max(0, self.history_cards_layout.count() - 2)))
        if target_index == current_index or target_index == self.history_drop_index:
            return
        self.history_cards_layout.removeWidget(placeholder)
        self.history_cards_layout.insertWidget(max(0, target_index), placeholder)
        self.history_drop_index = target_index
        self.refresh_history_drag_targets()

    def history_display_order_from_placeholder(self) -> List[int]:
        source_index = self.history_drag_index
        if source_index < 0 or self.history_drop_placeholder is None:
            return []
        display_without_source = [idx for idx, _ in self.history_visible_records if idx != source_index]
        before_count = 0
        marker_seen = False
        for layout_index in range(self.history_cards_layout.count()):
            item = self.history_cards_layout.itemAt(layout_index)
            widget = item.widget() if item else None
            if widget is None:
                continue
            if widget is self.history_drop_placeholder:
                marker_seen = True
                break
            if widget is self.history_drag_card:
                continue
            idx = widget.property("history_index")
            if isinstance(idx, int) and idx in display_without_source:
                before_count += 1
        if not marker_seen:
            before_count = len([idx for idx in display_without_source if idx in [item[0] for item in self.history_visible_records[: self.history_render_limit]]])
        before_count = max(0, min(before_count, len(display_without_source)))
        display_without_source.insert(before_count, source_index)
        return display_without_source

    def apply_history_display_order(self, display_indexes: List[int]):
        if not display_indexes:
            return
        old_records = self.download_history
        if set(display_indexes) != set(range(len(old_records))):
            remaining = [idx for idx, _ in self.history_visible_records if idx not in display_indexes]
            display_indexes = display_indexes + remaining
        self.download_history = [old_records[idx] for idx in reversed(display_indexes)]
        for order, record in enumerate(self.download_history):
            record["sort_order"] = str(order)
        if self.history_drag_record in self.download_history:
            self.history_drag_index = self.download_history.index(self.history_drag_record)
            self.selected_history_index = self.history_drag_index
        current_scroll = self.history_scroll.verticalScrollBar().value() if hasattr(self, "history_scroll") else 0
        self.history_visible_records = list(reversed(list(enumerate(self.download_history))))
        self.render_history_cards(reset_scroll=False)
        QTimer.singleShot(0, lambda value=current_scroll: self.history_scroll.verticalScrollBar().setValue(value))

    def history_drop_target_index(self, global_y: int) -> int:
        rendered_indexes = [source_index for source_index, _ in self.history_visible_records[: self.history_render_limit]]
        if not rendered_indexes:
            return -1
        target_index = rendered_indexes[-1]
        for source_index in rendered_indexes:
            card = self.history_card_by_index.get(source_index)
            if card is None:
                continue
            center_y = card.mapToGlobal(card.rect().center()).y()
            if global_y <= center_y:
                target_index = source_index
                break
        return target_index

    def reorder_history_by_display_target(self, source_index: int, target_index: int):
        if source_index < 0 or target_index < 0 or source_index >= len(self.download_history) or target_index >= len(self.download_history):
            return
        display_indexes = [idx for idx, _ in self.history_visible_records]
        if source_index not in display_indexes or target_index not in display_indexes:
            return
        source_pos = display_indexes.index(source_index)
        target_pos = display_indexes.index(target_index)
        if source_pos == target_pos:
            return
        moved_index = display_indexes.pop(source_pos)
        display_indexes.insert(target_pos, moved_index)
        old_records = self.download_history
        self.download_history = [old_records[idx] for idx in reversed(display_indexes)]
        for order, record in enumerate(self.download_history):
            record["sort_order"] = str(order)
        if self.history_drag_record in self.download_history:
            self.history_drag_index = self.download_history.index(self.history_drag_record)
            self.selected_history_index = self.history_drag_index
        current_scroll = self.history_scroll.verticalScrollBar().value() if hasattr(self, "history_scroll") else 0
        self.history_visible_records = list(reversed(list(enumerate(self.download_history))))
        self.render_history_cards(reset_scroll=False)
        QTimer.singleShot(0, lambda value=current_scroll: self.history_scroll.verticalScrollBar().setValue(value))

    def show_history_context_menu(self, index: int, global_pos):
        if index < 0 or index >= len(self.download_history):
            return
        menu = QMenu(self)
        read_action = menu.addAction("阅读")
        locate_action = menu.addAction("打开位置")
        menu.addSeparator()
        delete_action = menu.addAction("删除记录")
        delete_action.setObjectName("dangerAction")
        action = menu.exec(global_pos)
        if action == read_action:
            self.select_history_record(index, open_reader=True)
        elif action == locate_action:
            self.select_history_record(index, open_location=True)
        elif action == delete_action:
            self.delete_history_record(index)

    def delete_history_record(self, index: int, confirm: bool = True):
        if index < 0 or index >= len(self.download_history):
            return
        record = self.download_history[index]
        title = record.get("title") or record.get("file") or record.get("path") or "历史记录"
        local_paths = self.history_record_local_paths(record) if self.history_record_is_managed(record) else []
        self.download_history.pop(index)
        if self.selected_history_index == index:
            self.selected_history_index = -1
        elif self.selected_history_index > index:
            self.selected_history_index -= 1
        if hasattr(self, "download_total_value"):
            self.update_download_page_stats()
        self.refresh_history_table()
        self.refresh_local_downloads_if_visible()
        self.save_local_cache()
        if local_paths:
            self.start_history_resource_delete(title, local_paths)
            self.log(f"已删除历史记录：{title}，本地资源正在后台删除。")
            self.show_toast("历史记录已删除，本地资源后台删除中", 1800)
        else:
            self.log(f"已删除历史记录：{title}。")
            self.show_toast("历史记录已删除")

    def delete_selected_history_record(self):
        if self.selected_history_index < 0 or self.selected_history_index >= len(self.download_history):
            self.show_toast("请先选择一条历史记录")
            return
        self.delete_history_record(self.selected_history_index)

    def clear_download_history(self):
        if not self.download_history:
            return
        all_paths = []
        for record in self.download_history:
            if self.history_record_is_managed(record):
                all_paths.extend(self.history_record_local_paths(record))
        self.download_history.clear()
        self.selected_history_index = -1
        if hasattr(self, "download_total_value"):
            self.update_download_page_stats()
        self.refresh_history_table()
        self.refresh_local_downloads_if_visible()
        self.save_local_cache()
        if all_paths:
            self.start_history_resource_delete("全部历史记录", all_paths)
            self.show_toast("历史记录已清空，本地资源后台删除中", 2000)
            self.log(f"已清空历史记录，本地资源正在后台删除：{len(all_paths)} 个候选路径。")
        else:
            self.show_toast("历史记录已清空")
            self.log("历史记录已清空。")

    def start_history_resource_delete(self, title: str, paths: List[Path]):
        protected = [
            str(self.data_root),
            str(self.default_output_dir),
            str(self.reader_cache_root()),
            str(self.cache_file.parent),
        ]
        worker = HistoryResourceDeleteWorker(title, [str(path) for path in paths], protected, self)
        self.history_delete_workers.append(worker)
        worker.completed.connect(self.on_history_resource_delete_completed)
        worker.finished.connect(lambda worker=worker: self.cleanup_history_delete_worker(worker))
        worker.start()

    def on_history_resource_delete_completed(self, title: str, deleted: int, failed: List[tuple[str, str]]):
        if failed:
            for path, message in failed[:20]:
                self.log(f"本地资源删除失败 {path}: {message}")
            self.log(f"历史记录本地资源后台删除完成：{title}，删除 {deleted} 个路径，失败 {len(failed)} 个。")
            self.show_toast(f"本地资源部分删除失败：{len(failed)} 个", 2200)
            return
        self.log(f"历史记录本地资源后台删除完成：{title}，删除 {deleted} 个路径。")

    def cleanup_history_delete_worker(self, worker: HistoryResourceDeleteWorker):
        if worker in self.history_delete_workers:
            self.history_delete_workers.remove(worker)
        worker.deleteLater()

    def sync_local_history_from_button(self):
        if self.local_history_sync_worker and self.local_history_sync_worker.isRunning():
            self.show_toast("正在后台扫描本地记录", 1600)
            return
        roots = [
            str(Path(self.output_edit.text()).expanduser() if hasattr(self, "output_edit") else self.default_output_dir),
            str(self.default_output_dir),
        ]
        album_cache = {
            album_id: self.album_to_dict(album)
            for album_id, album in {**self.detail_cache, **self.albums}.items()
            if album_id and isinstance(album, AlbumMeta)
        }
        worker = LocalHistorySyncWorker(self.download_history, roots, album_cache, self)
        self.local_history_sync_worker = worker
        worker.synced.connect(self.on_local_history_synced)
        worker.failed.connect(self.on_local_history_sync_failed)
        worker.finished.connect(lambda worker=worker: self.cleanup_local_history_sync_worker(worker))
        self.show_toast("正在后台扫描本地记录", 1400)
        self.log("开始后台同步本地观看记录。")
        worker.start()

    def on_local_history_synced(self, history: List[Dict[str, str]], removed: int, added: int):
        self.download_history = history
        if self.download_history:
            self.selected_history_index = min(max(self.selected_history_index, -1), len(self.download_history) - 1)
        else:
            self.selected_history_index = -1
        self.save_local_cache()
        self.refresh_history_table()
        if removed or added:
            self.show_toast(f"本地扫描完成：导入 {added} 条，移除失效 {removed} 条", 2200)
            self.log(f"本地观看记录后台同步完成：新增/更新 {added} 条，移除失效 {removed} 条。")
        else:
            self.show_toast("本地扫描完成：没有发现新的漫画", 1800)
            self.log("本地观看记录后台同步完成：没有新增记录。")

    def on_local_history_sync_failed(self, message: str):
        self.show_toast(f"本地扫描失败：{message}", 2400)
        self.log(f"本地观看记录后台同步失败：{message}")

    def cleanup_local_history_sync_worker(self, worker: LocalHistorySyncWorker):
        if worker is self.local_history_sync_worker:
            self.local_history_sync_worker = None
        worker.deleteLater()

    def merge_history_record_local_output(self, index: int, incoming: Dict[str, str]) -> bool:
        if index < 0 or index >= len(self.download_history):
            return False
        record = self.download_history[index]
        changed = False

        for key in ("title", "file", "album_id", "cover_url"):
            if not record.get(key) and incoming.get(key):
                record[key] = incoming.get(key, "")
                changed = True
        for key in ("path", "pdf_path", "image_dir"):
            incoming_value = incoming.get(key) or ""
            if not incoming_value:
                continue
            current_value = record.get(key) or ""
            if not current_value or not self.is_completed_local_resource(Path(current_value).expanduser()):
                record[key] = incoming_value
                changed = True

        outputs = []
        for value in [record.get("path") or "", record.get("pdf_path") or "", record.get("image_dir") or ""]:
            if str(value).strip():
                outputs.append(str(value))
        old_outputs = record.get("outputs") or []
        if isinstance(old_outputs, list):
            outputs.extend(str(value) for value in old_outputs if str(value).strip())
        new_outputs = incoming.get("outputs") or []
        if isinstance(new_outputs, list):
            outputs.extend(str(value) for value in new_outputs if str(value).strip())

        unique_outputs = []
        seen_outputs = set()
        for value in outputs:
            path = Path(value).expanduser()
            if not self.is_completed_local_resource(path):
                continue
            key = self.normalized_history_path(path)
            if key in seen_outputs:
                continue
            seen_outputs.add(key)
            unique_outputs.append(str(path))
        if unique_outputs != (record.get("outputs") or []):
            record["outputs"] = unique_outputs
            changed = True

        if incoming.get("image_dir") and record.get("format") not in {"images", "image"}:
            record["format"] = "images"
            changed = True
        return changed

    def iter_completed_local_outputs(self, root: Path) -> List[Path]:
        if not root.exists() or not root.is_dir():
            return []
        outputs: List[Path] = []
        seen = set()

        def add_output(path: Path):
            normalized = self.normalized_history_path(path)
            if normalized in seen:
                return
            seen.add(normalized)
            outputs.append(path)

        def walk(directory: Path, is_root: bool = False):
            children = []
            try:
                iterator = directory.iterdir()
            except OSError:
                return
            for child in iterator:
                try:
                    children.append((child.stat().st_mtime, child))
                except OSError:
                    continue
            for _, child in sorted(children, key=lambda item: item[0], reverse=True):
                if child.name.startswith("."):
                    continue
                if child.is_file():
                    if child.suffix.lower() in {".pdf", ".zip"} and self.is_completed_local_resource(child):
                        add_output(child)
                    continue
                if not child.is_dir():
                    continue
                if self.is_local_album_output_dir(child):
                    add_output(child)
                    continue
                walk(child)

        walk(root, is_root=True)
        return outputs

    def is_local_album_output_dir(self, directory: Path) -> bool:
        try:
            if collect_images(directory):
                return True
            direct_files = [
                child
                for child in directory.iterdir()
                if child.is_file() and child.suffix.lower() in {".pdf", ".zip"} and child.stat().st_size > 0
            ]
            has_reader_images = bool(self.collect_local_reader_images(directory))
            if has_reader_images and direct_files:
                return True
            child_image_dirs = [
                child
                for child in directory.iterdir()
                if child.is_dir() and not child.name.startswith(".") and collect_images(child)
            ]
            if child_image_dirs and (
                self.album_id_from_local_output(directory)
                or len(child_image_dirs) == 1
                or any(re.search(r"(^\d+|第.+[话話章]|chapter|chap|ch)", child.name, re.IGNORECASE) for child in child_image_dirs)
            ):
                return True
            return False
        except OSError:
            return False

    def direct_local_output_files(self, directory: Path) -> List[Path]:
        if not directory.exists() or not directory.is_dir():
            return []
        try:
            return sorted(
                (
                    child
                    for child in directory.iterdir()
                    if child.is_file() and child.suffix.lower() in {".pdf", ".zip"} and child.stat().st_size > 0
                ),
                key=lambda path: self.local_chapter_sort_key(path.name),
            )
        except OSError:
            return []


    @staticmethod
    def album_id_from_local_output(path: Path) -> str:
        match = re.search(r"(?:JM)?(\d{4,})", path.stem if path.is_file() else path.name, re.IGNORECASE)
        return match.group(1) if match else ""

    def history_record_from_local_output(
        self,
        path: Path,
        album_id: str = "",
        managed: bool = True,
    ) -> Optional[Dict[str, str]]:
        if not self.is_completed_local_resource(path):
            return None
        title = path.stem if path.is_file() else path.name
        if album_id:
            title = re.sub(rf"^JM?{re.escape(album_id)}[-_\s]*", "", title, flags=re.IGNORECASE) or title
        image_dir = self.resolve_history_image_dir(path)
        output_paths = [path]
        if path.is_dir():
            output_paths.extend(self.direct_local_output_files(path))
        pdf_candidates = [item for item in output_paths if item.is_file() and item.suffix.lower() == ".pdf"]
        pdf_path = str(pdf_candidates[0]) if pdf_candidates else ""
        album = self.albums.get(album_id) or self.detail_cache.get(album_id) if album_id else None
        return {
            "title": album.title if album else title,
            "file": path.name,
            "path": str(path),
            "pdf_path": pdf_path,
            "image_dir": str(image_dir) if image_dir else (str(path) if path.is_dir() else ""),
            "album_id": album_id,
            "cover_url": album.cover_url if album else "",
            "format": path.suffix.lstrip(".") if path.is_file() else "images",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sort_order": str(len(self.download_history)),
            "managed": "1" if managed else "0",
            "outputs": [str(item) for item in output_paths],
        }

    @staticmethod
    def history_record_is_managed(record: Dict[str, str]) -> bool:
        return str(record.get("managed") or "1") != "0"

    def history_record_has_local_file(self, record: Dict[str, str]) -> bool:
        return any(self.is_completed_local_resource(path) for path in self.history_record_local_paths(record))

    def is_completed_local_resource(self, path: Path) -> bool:
        try:
            path = path.expanduser()
            if path.is_dir():
                return bool(self.collect_local_reader_images(path) or self.direct_local_output_files(path))
            if not path.is_file() or path.stat().st_size <= 0:
                return False
            return path.suffix.lower() in {".pdf", ".zip"} | IMAGE_SUFFIXES
        except Exception:
            return False

    def history_record_local_paths(self, record: Dict[str, str]) -> List[Path]:
        candidates: List[Path] = []
        for key in ("path", "pdf_path", "image_dir"):
            value = record.get(key) or ""
            if value:
                candidates.append(Path(value).expanduser())
        outputs = record.get("outputs") or []
        if isinstance(outputs, list):
            candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())

        unique: List[Path] = []
        seen = set()
        for path in candidates:
            try:
                normalized = str(path.resolve(strict=False)).lower()
            except Exception:
                normalized = str(path).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(path)
        return unique

    def selected_history_record(self) -> Optional[Dict[str, str]]:
        if not self.download_history:
            return None
        row = self.selected_history_index
        if row < 0 or row >= len(self.download_history):
            return None
        return self.download_history[row]

    @staticmethod
    def history_record_last_page(record: Dict[str, str]) -> int:
        try:
            return max(0, int(record.get("last_page") or 0))
        except (TypeError, ValueError):
            return 0

    def schedule_history_save(self):
        self.history_save_timer.start(500)

    def bind_reader_download_action(self, reader: HdMangaReaderWindow, album: Optional[AlbumMeta] = None):
        if album is not None:
            reader.album = copy.deepcopy(album)
        reader.download_requested.connect(lambda album, source_reader=reader: self.on_reader_download_requested(album, source_reader))
        if album is not None:
            self.reader_controller.bind(reader, copy.deepcopy(album))

    def on_reader_download_requested(self, album: AlbumMeta, reader: Optional[HdMangaReaderWindow] = None):
        if not album or not album.album_id:
            self.show_toast("\u5f53\u524d\u6f2b\u753b\u7f3a\u5c11 ID\uff0c\u65e0\u6cd5\u52a0\u5165\u4e0b\u8f7d", parent=reader)
            return
        if not album or not album.album_id:
            self.show_toast("当前漫画缺少 ID，无法加入下载")
            return
        if album.album_id not in self.albums:
            self.albums[album.album_id] = copy.deepcopy(album)
        if album.album_id not in self.detail_cache:
            self.detail_cache[album.album_id] = copy.deepcopy(album)
        if any(item.album_id == album.album_id for item in self.queue):
            self.show_toast("\u6f2b\u753b\u5df2\u5b58\u5728\uff0c\u65e0\u9700\u91cd\u590d\u4e0b\u8f7d", parent=reader)
            return
        if any(item.album_id == album.album_id for item in self.download_pending_queue) or album.album_id in self.download_workers:
            self.show_toast("\u6f2b\u753b\u5df2\u5728\u4e0b\u8f7d\u4e2d\uff0c\u65e0\u9700\u91cd\u590d\u4e0b\u8f7d", parent=reader)
            return
        if self.album_has_completed_local_resource(album):
            self.show_toast("\u6f2b\u753b\u5df2\u5b58\u5728\uff0c\u65e0\u9700\u91cd\u590d\u4e0b\u8f7d", parent=reader)
            return
        if not album.chapters:
            self.show_toast("\u5f53\u524d\u6f2b\u753b\u8fd8\u6ca1\u6709\u53ef\u4e0b\u8f7d\u7ae0\u8282", parent=reader)
            return
        reader_added_to_queue = self.add_album_to_queue(album.album_id, switch_page=False, toast_parent=reader)
        if reader_added_to_queue:
            self.show_toast("\u5df2\u52a0\u5165\u4e0b\u8f7d\u961f\u5217", parent=reader)
        if reader_added_to_queue:
            self.log(f"已从阅读器加入下载：{album.title}")

    def on_history_reader_position_changed(self, history_index: int, page: int, total: int, source_key: str):
        if history_index < 0 or history_index >= len(self.download_history) or page <= 0:
            return
        record = self.download_history[history_index]
        if self.history_record_last_page(record) == page and self.history_record_last_total(record) == max(0, total):
            return
        record["last_page"] = str(page)
        record["last_total"] = str(max(0, total))
        record["last_source"] = source_key or ""
        record["last_read_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.update_history_card_progress(history_index)
        self.schedule_history_save()

    def update_history_card_progress(self, history_index: int):
        card = self.history_card_by_index.get(history_index)
        if not card or history_index < 0 or history_index >= len(self.download_history):
            return
        record = self.download_history[history_index]
        fixed_label = card.findChild(QLabel, "historyFixedMeta")
        if fixed_label is not None:
            text = self.history_fixed_meta_text(record)
            fixed_label.setText(text)
            fixed_label.setToolTip(text)
        grid_progress = card.findChild(QLabel, "historyGridProgress")
        if grid_progress is not None:
            grid_progress.setText(self.history_read_progress_text(record))

    def history_fixed_meta_text(self, record: Dict[str, str]) -> str:
        items = []
        album_id = record.get("album_id") or record.get("id") or ""
        if album_id:
            items.append(f"ID {album_id}")
        last_page = self.history_record_last_page(record)
        if last_page:
            items.append(f"看到第 {last_page} 页")
        return "  ·  ".join(items)

    @staticmethod
    def history_record_last_total(record: Dict[str, str]) -> int:
        try:
            return max(0, int(record.get("last_total") or 0))
        except (TypeError, ValueError):
            return 0

    def album_from_history_record(self, record: Dict[str, str]) -> Optional[AlbumMeta]:
        album_id = str(record.get("album_id") or record.get("id") or "").strip()
        if not album_id:
            return None
        album = self.albums.get(album_id) or self.detail_cache.get(album_id)
        if album:
            return copy.deepcopy(album)
        return AlbumMeta(
            album_id=album_id,
            title=record.get("title") or record.get("file") or album_id,
            url="",
            cover_url=record.get("cover_url") or "",
            source="历史",
        )

    def open_selected_history_reading(self):
        record = self.selected_history_record()
        if not record:
            self.show_toast("请先选择一条历史记录")
            return
        mode = self.selected_history_read_mode()
        history_index = self.selected_history_index
        output_dir = Path(self.output_edit.text()).expanduser() if hasattr(self, "output_edit") else self.default_output_dir
        worker = LocalReaderPrepareWorker(history_index, record, mode, output_dir, self.default_output_dir, self)
        self.local_reader_prepare_workers.append(worker)
        worker.prepared.connect(self.on_local_reader_prepared)
        worker.failed.connect(self.on_local_reader_prepare_failed)
        worker.finished.connect(lambda worker=worker: self.cleanup_local_reader_prepare_worker(worker))
        self.show_toast("正在后台准备本地阅读", 1500)
        self.log(f"开始后台准备本地阅读：{record.get('title') or record.get('path') or record.get('file') or history_index}")
        worker.start()

    def on_local_reader_prepared(self, result: Dict[str, object]):
        kind = str(result.get("kind") or "")
        if kind == "missing":
            self.show_toast(str(result.get("message") or "找不到可阅读的本地文件"), 2200)
            return
        if kind == "system":
            system_path = result.get("system_path")
            if system_path:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(system_path)))
            return

        record = result.get("record") if isinstance(result.get("record"), dict) else {}
        history_index = int(result.get("history_index") if result.get("history_index") is not None else -1)
        title = str(result.get("title") or record.get("title") or "本地阅读")
        dialog = HdMangaReaderWindow(f"漫画阅读 - {title}")
        self.bind_reader_download_action(dialog, self.album_from_history_record(record))
        dialog.mark_downloaded_action()
        dialog.set_restore_page(self.history_record_last_page(record))
        dialog.page_position_changed.connect(
            lambda page, total, source, idx=history_index: self.on_history_reader_position_changed(idx, page, total, source)
        )
        self.local_reader_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _=None, dialog=dialog: self.forget_local_reader_dialog(dialog))
        try:
            if kind == "chapter_dirs":
                dialog.start_local_chapter_dirs(result.get("chapter_dirs") or [], str(result.get("restore_source") or ""))
            elif kind == "images":
                dialog.start_decode_image_paths(result.get("images") or [])
            elif kind == "pdf_groups":
                dialog.start_local_pdf_chapters(result.get("pdf_groups") or [], str(result.get("restore_source") or ""))
            elif kind == "pdf":
                pdf_path = result.get("pdf_path")
                if not pdf_path or not dialog.start_decode_pdf(Path(pdf_path), []):
                    raise RuntimeError(f"PDF 解码失败：{pdf_path}")
            else:
                raise RuntimeError(f"未知本地阅读类型：{kind}")
            dialog.showMaximized()
            dialog.raise_()
            dialog.activateWindow()
            self.log(f"本地阅读器已打开：{title}")
        except Exception as exc:
            self.forget_local_reader_dialog(dialog)
            dialog.deleteLater()
            self.log(f"本地阅读器打开失败：{exc}")
            self.show_toast(f"本地阅读器解析失败：{exc}", 2400)

    def on_local_reader_prepare_failed(self, message: str, context):
        record = context.get("record") if isinstance(context, dict) else {}
        self.log(f"本地阅读后台准备失败：{message}")
        self.show_toast(f"本地阅读器解析失败，已改用系统打开：{message}", 2400)
        path_text = ""
        if isinstance(record, dict):
            path_text = record.get("path", "") or record.get("pdf_path", "") or record.get("image_dir", "")
        if path_text:
            path = Path(path_text).expanduser()
            if path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def cleanup_local_reader_prepare_worker(self, worker: LocalReaderPrepareWorker):
        if worker in self.local_reader_prepare_workers:
            self.local_reader_prepare_workers.remove(worker)
        worker.deleteLater()

    def local_reader_pdf_chapter_groups(self, record: Dict[str, str]) -> List[tuple[str, Path, str]]:
        candidates: List[Path] = []
        for key in ("pdf_path", "path"):
            value = record.get(key) or ""
            if value:
                candidates.append(Path(value).expanduser())
        outputs = record.get("outputs") or []
        if isinstance(outputs, list):
            candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())

        pdfs: List[Path] = []
        seen = set()
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() == ".pdf" and candidate.stat().st_size > 0:
                paths = [candidate]
            elif candidate.is_dir():
                paths = sorted(
                    path
                    for path in candidate.iterdir()
                    if path.is_file() and path.suffix.lower() == ".pdf" and path.stat().st_size > 0
                )
            else:
                paths = []
            for path in paths:
                key = self.normalized_history_path(path)
                if key in seen:
                    continue
                seen.add(key)
                pdfs.append(path)

        pdfs.sort(key=lambda path: self.local_chapter_sort_key(path.stem))
        return [(path.stem, path, str(path)) for path in pdfs]

    @staticmethod
    def local_chapter_sort_key(text: str):
        parts = re.split(r"(\d+)", text or "")
        return [int(part) if part.isdigit() else part.lower() for part in parts]

    def local_reader_chapter_dir_groups(self, image_dir: Optional[Path]) -> List[tuple[str, Path, str]]:
        if image_dir is None or not image_dir.exists() or not image_dir.is_dir():
            return []
        if collect_images(image_dir):
            return [(image_dir.name, image_dir, str(image_dir))]
        child_dirs = [
            child
            for child in sorted(image_dir.iterdir(), key=lambda path: self.local_chapter_sort_key(path.name))
            if child.is_dir() and not child.name.startswith(".")
        ]
        groups = [
            (child.name, child, str(child))
            for child in child_dirs
            if self.directory_may_contain_reader_images(child)
        ]
        return groups or [(image_dir.name, image_dir, str(image_dir))]

    @staticmethod
    def directory_may_contain_reader_images(directory: Path) -> bool:
        try:
            for child in directory.iterdir():
                if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES:
                    return True
            for child in directory.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue
                for item in child.iterdir():
                    if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES:
                        return True
        except OSError:
            return False
        return False

    def selected_history_read_mode(self) -> str:
        combo = getattr(self, "history_read_mode_combo", None)
        text = combo.currentText() if combo else "自动"
        if text == "PDF":
            return "pdf"
        if text == "原文件":
            return "original"
        return "auto"

    def album_has_completed_local_resource(self, album: AlbumMeta) -> bool:
        history_index = self.find_history_index_for_album(album.album_id)
        if history_index >= 0 and self.history_record_has_local_file(self.download_history[history_index]):
            return True
        return self.find_completed_album_output(album) is not None

    def find_completed_album_output(self, album: AlbumMeta) -> Optional[Path]:
        expected_prefix = f"JM{album.album_id}-".lower()
        roots = [
            Path(self.output_edit.text()).expanduser() if hasattr(self, "output_edit") else self.default_output_dir,
            self.default_output_dir,
        ]
        for root in self.unique_existing_dirs(roots):
            for candidate in sorted(root.iterdir()):
                name = candidate.name.lower()
                if not (name.startswith(expected_prefix) or album.album_id in name):
                    continue
                if self.is_completed_local_resource(candidate):
                    return candidate
        return None

    @staticmethod
    def unique_existing_dirs(paths: List[Path]) -> List[Path]:
        unique: List[Path] = []
        seen = set()
        for path in paths:
            if not path:
                continue
            try:
                resolved = path.expanduser().resolve(strict=False)
            except Exception:
                resolved = path.expanduser()
            key = str(resolved).lower()
            if key in seen or not resolved.exists() or not resolved.is_dir():
                continue
            seen.add(key)
            unique.append(resolved)
        return unique

    def open_selected_history_location(self):
        record = self.selected_history_record()
        if not record:
            self.show_toast("请先选择一条历史记录")
            return
        candidates: List[Path] = []
        for key in ("image_dir", "pdf_path", "path"):
            value = record.get(key) or ""
            if value:
                candidates.append(Path(value).expanduser())
        outputs = record.get("outputs") or []
        if isinstance(outputs, list):
            candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())
        target = None
        for path in candidates:
            if path.exists():
                target = path if path.is_dir() else path.parent
                break
        if target is None or not target.exists():
            fallback = candidates[0] if candidates else Path("历史记录中的本地文件")
            self.show_toast(f"找不到本地路径：{fallback}", 2200)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def resolve_history_image_dir(self, path: Path) -> Optional[Path]:
        if path.is_dir():
            return path if self.directory_may_contain_reader_images(path) else None
        if path.suffix.lower() in IMAGE_SUFFIXES:
            return path.parent
        if path.suffix.lower() == ".pdf":
            sibling = path.with_suffix("")
            if sibling.exists() and sibling.is_dir() and self.directory_may_contain_reader_images(sibling):
                return sibling
            if " - " in path.stem:
                album_name, chapter_name = path.stem.split(" - ", 1)
                album_dir = path.parent / album_name
                chapter_dir = album_dir / chapter_name
                if chapter_dir.exists() and self.directory_may_contain_reader_images(chapter_dir):
                    return chapter_dir
                if album_dir.exists() and self.directory_may_contain_reader_images(album_dir):
                    return album_dir
            for candidate in sorted(path.parent.iterdir() if path.parent.exists() else []):
                if candidate.is_dir() and candidate.name.startswith(path.stem) and self.directory_may_contain_reader_images(candidate):
                    return candidate
            album_id_match = re.search(r"(\d+)", path.stem)
            if album_id_match:
                album_id = album_id_match.group(1)
                for candidate in sorted(path.parent.iterdir() if path.parent.exists() else []):
                    if candidate.is_dir() and album_id in candidate.name and self.directory_may_contain_reader_images(candidate):
                        return candidate
        return None

    @staticmethod
    def collect_local_reader_images(directory: Path) -> List[Path]:
        if not directory.exists() or not directory.is_dir():
            return []
        direct = collect_images(directory)
        if direct:
            return direct
        return sorted(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )

    def _build_about_panel(self) -> QFrame:
        path = ui_dir() / "about.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open about form: {path}")
        panel = QUiLoader().load(ui_file, self)
        ui_file.close()
        if panel is None:
            raise RuntimeError(f"Unable to load about form: {path}")
        version = panel.findChild(QLabel, "aboutVersionLabel")
        note = panel.findChild(QLabel, "aboutNoteLabel")
        show_log = panel.findChild(QPushButton, "showLogButton")
        open_data = panel.findChild(QPushButton, "openDataButton")
        if not all((version, note, show_log, open_data)):
            raise RuntimeError("About form is missing required controls")
        version.setText(
            f"{APP_DISPLAY_NAME} Qt \u7248\u672c\uff1a{APP_UI_VERSION}\n"
            f"JM App API \u7248\u672c\uff1a{APP_VERSION}"
        )
        version.setStyleSheet("color:#334155;font-size:14px;line-height:1.5;")
        note.setStyleSheet("color:#64748b;")
        show_log.clicked.connect(self.open_log_directory)
        open_data.clicked.connect(self.open_application_data_directory)
        return panel

    def open_log_directory(self):
        path = log_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_application_data_directory(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_root)))

    def login(self):
        username = self.login_user_edit.text().strip()
        password = self.login_pass_edit.text()
        cookie = self.login_cookie_edit.toPlainText().strip()
        if not username:
            self.show_toast("\u8bf7\u8f93\u5165\u8d26\u53f7")
            return
        if not password:
            self.show_toast("\u8bf7\u8f93\u5165\u5bc6\u7801")
            return
        if self.login_worker and self.login_worker.isRunning():
            return

        settings = NetworkSettings(
            cookie_header=cookie,
            user_agent=self.login_ua_edit.text().strip() or DEFAULT_USER_AGENT,
            delay_min=float(self.delay_min.value()),
            delay_max=float(self.delay_max.value()),
            retries=self.retries.value(),
            backoff_seconds=self.backoff.value(),
            stop_on_block=self.stop_on_block.isChecked(),
            username=username,
            password=password,
            proxy=self.effective_proxy(),
            detail_threads=self.detail_threads.value(),
            save_password=self.save_password_box.isChecked(),
            auto_login=self.auto_login_box.isChecked(),
            auto_sign=self.auto_sign_box.isChecked(),
            api_route=getattr(self, "api_route", 0),
            image_route=int(self.image_route_combo.currentData() or 0),
            doh_enabled=self.doh_enabled_box.isChecked(),
            doh_url=self.doh_url_edit.text().strip() or DOH_URL,
            custom_api_domain=self.custom_api_domain_edit.text().strip(),
            custom_image_domain=self.custom_image_domain_edit.text().strip(),
        )
        self.persist_sensitive_settings()
        self.settings_cache = self.current_settings_snapshot()
        self.save_local_cache()
        self.set_login_controls_enabled(False)
        self.statusBar().showMessage("正在验证账号密码...")
        self.login_worker = LoginVerifyWorker(settings, self)
        self.login_worker.verified.connect(lambda result, worker=self.login_worker: self.on_login_verified(result, worker))
        self.login_worker.failed.connect(lambda message, worker=self.login_worker: self.on_login_failed(message, worker))
        self.login_worker.finished.connect(lambda worker=self.login_worker: self.cleanup_login_worker(worker))
        self.login_worker.start()

    def set_login_controls_enabled(self, enabled: bool):
        self.login_user_edit.setEnabled(enabled)
        self.login_pass_edit.setEnabled(enabled)
        self.login_cookie_edit.setEnabled(enabled)
        self.login_ua_edit.setEnabled(enabled)
        for widget_name in ("save_password_box", "auto_login_box", "auto_sign_box", "login_btn", "skip_login_btn"):
            widget = getattr(self, widget_name, None)
            if widget:
                widget.setEnabled(enabled)

    def on_login_verified(self, result: Dict, worker: LoginVerifyWorker):
        if worker is not self.login_worker:
            return
        username = str(result.get("username") or self.login_user_edit.text().strip())
        cookie = str(result.get("cookie_header") or self.login_cookie_edit.toPlainText().strip())
        if cookie:
            self.login_cookie_edit.setPlainText(cookie)
        self.profile_data = dict(result or {})
        self.invalidate_personal_comment_statistics()
        self.profile_avatar_pixmap = None
        if hasattr(self, "avatar_button"):
            self.reset_navigation_avatar()
        user = self.profile_data.get("user") or {}
        self.session_uid = str(self.profile_data.get("uid") or user.get("uid") or "")
        for message in result.get("logs") or []:
            self.log(message)
        self.statusBar().showMessage("账号密码验证成功", 1800)
        self.settings_cache = self.current_settings_snapshot()
        self.save_local_cache()
        self.update_profile_page()
        self.start_avatar_fetch()
        self.enter_app(username=username, password=self.login_pass_edit.text(), cookie=cookie)

    def on_login_failed(self, message: str, worker: LoginVerifyWorker):
        if worker is not self.login_worker:
            return
        self.set_login_controls_enabled(True)
        self.statusBar().showMessage("账号密码验证失败", 2600)
        self.show_toast(message or "\u767b\u5f55\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8d26\u53f7\u5bc6\u7801", 2600)
        self.log(f"\u767b\u5f55\u5931\u8d25\uff1a{message}")

    def cleanup_login_worker(self, worker: LoginVerifyWorker):
        if worker is self.login_worker:
            self.set_login_controls_enabled(True)
            self.login_worker = None
        worker.deleteLater()

    def try_auto_login(self):
        if self.login_auto_started:
            return
        self.login_auto_started = True
        if not hasattr(self, "auto_login_box") or not self.auto_login_box.isChecked():
            return
        if not hasattr(self, "save_password_box") or not self.save_password_box.isChecked():
            return
        if not self.login_user_edit.text().strip() or not self.login_pass_edit.text():
            return
        self.login()

    def sync_detail_content_width(self):
        scroll_area = getattr(self, "detail_scroll_area", None)
        content = getattr(self, "detail_content", None)
        if scroll_area is None or content is None:
            return
        viewport = scroll_area.viewport()
        viewport_width = viewport.width()
        viewport_left = viewport.mapTo(self, QPoint(0, 0)).x()
        visible_width = min(viewport_width, max(1, self.width() - viewport_left - 8))
        if visible_width <= 0:
            return
        content.setMinimumWidth(0)
        content.setMaximumWidth(visible_width)
        hero_layout = getattr(self, "detail_hero_layout", None)
        if hero_layout is not None:
            compact = visible_width < 760
            direction = (
                QBoxLayout.Direction.TopToBottom
                if compact
                else QBoxLayout.Direction.LeftToRight
            )
            if hero_layout.direction() != direction:
                hero_layout.setDirection(direction)
            cover = getattr(self, "cover_label", None)
            if cover is not None:
                hero_layout.setAlignment(
                    cover,
                    (Qt.AlignHCenter | Qt.AlignTop) if compact else Qt.AlignTop,
                )
            hero_layout.invalidate()
        content.updateGeometry()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            detail_search_kind = obj.property("detailSearchKind")
            if detail_search_kind == "author":
                self.open_current_detail_author_search()
                return True
            if detail_search_kind == "tag":
                self.open_detail_metadata_search(obj.property("detailSearchValue"))
                return True

        if (
            obj is getattr(self, "user_label", None)
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
        ):
            self.show_header_account_menu()
            return True

        # Do not call detail_scroll_area.viewport() from the application-wide
        # event filter. Qt continues to dispatch child events while a scroll
        # area is being destroyed, when that call can access a half-destroyed
        # native object.
        detail_viewport = getattr(self, "detail_scroll_viewport", None)
        if obj is detail_viewport and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self.sync_detail_content_width)
            return False

        if getattr(self, "history_dragging", False):
            if event.type() == QEvent.MouseMove and hasattr(event, "globalPos"):
                self.update_history_drag_ghost(event.globalPos())
                self.autoscroll_history_drag(event.globalPos())
                return False
            if event.type() == QEvent.MouseButtonRelease:
                self.complete_history_drag(commit=True)
                return True
            if event.type() == QEvent.KeyPress and hasattr(event, "key") and event.key() == Qt.Key_Escape:
                self.complete_history_drag(commit=False)
                return True

        if getattr(obj, "objectName", lambda: "")() == "albumCard" and event.type() in {QEvent.Enter, QEvent.Leave}:
            obj.setProperty("hovered", event.type() == QEvent.Enter)
            obj.style().unpolish(obj)
            obj.style().polish(obj)
            return False

        if obj not in {getattr(self, "login_header", None), getattr(self, "main_header", None)}:
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            return True

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            return True

        if event.type() == QEvent.MouseMove and event.buttons() & Qt.LeftButton:
            if self.drag_position is not None and not self.isMaximized():
                self.move(event.globalPos() - self.drag_position)
            return True

        if event.type() == QEvent.MouseButtonRelease:
            self.drag_position = None
            return True

        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_detail_content_width()
        overlay = getattr(self, "detail_loading_overlay", None)
        panel = getattr(self, "detail_panel", None)
        if overlay is not None and panel is not None and overlay.isVisible():
            overlay.move(max(0, (panel.width() - overlay.width()) // 2), max(0, (panel.height() - overlay.height()) // 2))
        self.position_home_append_loading()
        if (
            not getattr(self, "result_list_mode", False)
            and getattr(self, "result_grid", None) is not None
            and self.result_total_count
            and not self.result_resize_pending
        ):
            self.result_resize_pending = True
            QTimer.singleShot(120, self.refresh_result_layout)

    def refresh_result_layout(self):
        self.result_resize_pending = False
        if getattr(self, "result_list_mode", False):
            return
        # An appended page is already being placed incrementally. Rebuilding
        # every existing card here causes a visible flash and restarts cover
        # work, so drop deferred layout refreshes until the append commits.
        if self.append_layout_freeze:
            return
        total_pages = self.result_total_pages()
        if total_pages and self.current_result_page > total_pages:
            self.current_result_page = total_pages
        if getattr(self, "result_grid", None) is not None:
            self.render_result_page()

    def skip_login(self):
        self.show_login_loading(
            "正在进入游客模式...",
            lambda: self.enter_app(
                username="",
                password="",
                cookie=self.login_cookie_edit.toPlainText().strip(),
            ),
        )

    def logout(self):
        if self.avatar_worker and self.avatar_worker.isRunning():
            self.avatar_worker.cancel()
        self.session_username = ""
        self.session_password = ""
        self.session_uid = ""
        self.profile_data = {}
        self.invalidate_personal_comment_statistics()
        self.profile_avatar_pixmap = None
        for edit_name in ("login_user_edit", "login_pass_edit"):
            edit = getattr(self, edit_name, None)
            if edit is not None:
                edit.clear()
        for edit_name in ("login_cookie_edit", "cookie_edit"):
            edit = getattr(self, edit_name, None)
            if edit is not None:
                edit.clear()
        clear_cookie_store()
        self.settings_cache = self.current_settings_snapshot()
        self.save_local_cache()
        if hasattr(self, "avatar_button"):
            self.reset_navigation_avatar()
        self.update_profile_page()
        self.update_navigation_profile_card()
        self.home_auto_loaded = False
        if self.isMaximized():
            self.showNormal()
        self.setMinimumSize(330, 460)
        self.resize(360, 500)
        self._center_window()
        self.stack.setCurrentWidget(self.login_page)
        self._fade_in(self.login_page, 260)



    @staticmethod




    def closeEvent(self, event):
        self.lifecycle.handle_close(event)

    def _accept_close_event(self, event):
        super().closeEvent(event)

    def stop_shutdown_timers(self) -> None:
        self.lifecycle.stop_shutdown_timers()

    @staticmethod
    def stop_worker_for_exit(worker) -> None:
        LifecycleController.stop_worker_for_exit(worker)

    def cancel_background_tasks_for_exit(self) -> None:
        self.lifecycle.cancel_background_tasks_for_exit()

    def finish_close_when_idle(self) -> None:
        self.lifecycle.finish_close_when_idle()

    def has_running_background_tasks(self) -> bool:
        return self.lifecycle.has_running_background_tasks()

    def open_cookie_verifier(self):
        try:
            from .browser_cookie_dialog import BrowserCookieDialog
        except Exception as exc:
            self.show_toast(f"无法打开浏览器验证窗口：{exc}；请安装 PySide6 QtWebEngine", 2400)
            return

        dialog = BrowserCookieDialog(self, self.list_url_edit.text().strip() or LIST_URL)
        if dialog.exec() != QDialog.Accepted:
            return
        header = dialog.cookie_header()
        if not header:
            self.show_toast("没有读取到该站点 Cookie，请确认页面已完成验证")
            return
        self.cookie_edit.setPlainText(header)
        self.login_cookie_edit.setPlainText(header)
        save_cookie_dict(parse_cookie_header(header))
        self.set_backend_status("Cookie updated", "ok")
        self.log("已从浏览器验证窗口同步 Cookie。")
    def reader_cache_root(self) -> Path:
        return reader_cache_dir()

    def persist_download_root(self):
        output_dir = self.output_edit.text().strip() if hasattr(self, "output_edit") else ""
        if not output_dir:
            return
        try:
            self.default_output_dir = set_download_root(output_dir)
        except (OSError, ValueError) as exc:
            self.log(f"下载目录保存失败：{exc}")
            return
        self.update_cache_path_label()

    def should_keep_saved_output_dir(self, output_dir: str) -> bool:
        if not output_dir:
            return False
        try:
            saved = Path(output_dir).expanduser().resolve(strict=False)
            project_downloads = app_base_dir() / "downloads"
            old_default = project_downloads.resolve(strict=False)
            cwd_default = (Path.cwd() / "downloads").resolve(strict=False)
            new_default = self.default_output_dir.resolve(strict=False)
        except Exception:
            return True
        if saved in {old_default, cwd_default}:
            return False
        if saved == new_default:
            return True
        return True

    def update_cache_path_label(self):
        if not hasattr(self, "cache_path_label"):
            return
        self.cache_path_label.setText(
            "\u9875\u9762\u7f13\u5b58\uff1a{json}\n"
            "\u8bbe\u7f6e\uff1a{settings}\n"
            "\u5386\u53f2\u5e93\uff1a{history_db}\n"
            "\u4e0b\u8f7d\u72b6\u6001\u5e93\uff1a{download_db}\n"
            "\u9605\u8bfb\u56fe\u7247\u7f13\u5b58\uff1a{reader}".format(
                json=self.cache_file,
                settings=self.settings_file,
                history_db=self.history_store.path,
                download_db=self.download_store.path,
                reader=self.reader_cache_root(),
            )
        )

    def clear_current_result_cache(self):
        cache_key = self.result_cache_key()
        removed = 0
        if self.result_cache.pop(cache_key, None) is not None:
            removed += 1
        self.cache_restore_miss_keys.discard(cache_key)
        for album in self.result_albums:
            if album is not None:
                self.detail_cache.pop(album.album_id, None)
                self.cover_cache.pop(album.album_id, None)
                self.cover_cache_refresh_attempted.discard(album.album_id)
        self.save_local_cache()
        self.log(f"已清理当前结果缓存：{cache_key}，清理页面缓存 {removed} 组。")
        self.show_toast("已清理当前页面缓存")
    def clear_all_runtime_cache(self):
        result_count = len(self.result_cache)
        detail_count = len(self.detail_cache)
        self.result_cache.clear()
        self.detail_cache.clear()
        self.cover_cache.clear()
        self.cover_cache_refresh_attempted.clear()
        self.cover_pending.clear()
        self.cover_fallback_urls.clear()
        self.cover_request_queue.clear()
        self.cache_restore_miss_keys.clear()
        self.save_local_cache()
        self.log(f"已清理全部缓存：页面 {result_count} 组，详情 {detail_count} 本。")
        self.start_cache_maintenance(
            "clear_all",
            {
                "cache_root": str(cache_dir()),
                "reader_cache": str(self.reader_cache_root()),
                "cover_cache": str(cover_cache_dir()),
                "local_zip_cache": str(local_zip_cache_dir()),
                "page_cache": str(self.cache_file),
                "result_count": result_count,
                "detail_count": detail_count,
            },
            "正在后台清理全部运行缓存",
        )

    def clean_broken_cache(self):
        self.start_cache_maintenance(
            "clean_broken",
            {"roots": [str(self.reader_cache_root())]},
            "正在后台清理损坏缓存",
        )

    def export_cache_bundle(self):
        directory = QFileDialog.getExistingDirectory(self, "选择缓存导出目录", str(self.data_root))
        if not directory:
            return
        target = Path(directory).expanduser() / "comic18_cache"
        self.start_cache_maintenance(
            "export",
            {
                "target": str(target),
                "db_paths": [str(self.history_store.path), str(self.download_store.path)],
                "reader_cache": str(self.reader_cache_root()),
                "cover_cache": str(cover_cache_dir()),
            },
            "正在后台导出缓存",
        )

    def import_cache_bundle(self):
        directory = QFileDialog.getExistingDirectory(self, "选择 comic18_cache 缓存目录", str(self.data_root))
        if not directory:
            return
        self.start_cache_maintenance(
            "import",
            {
                "source": str(Path(directory).expanduser()),
                "db_paths": [str(self.history_store.path), str(self.download_store.path)],
                "reader_cache": str(self.reader_cache_root()),
                "cover_cache": str(cover_cache_dir()),
            },
            "正在后台导入缓存",
        )

    def start_cache_maintenance(self, action: str, payload: Dict, message: str):
        if self.cache_maintenance_worker and self.cache_maintenance_worker.isRunning():
            self.show_toast("缓存维护任务正在运行", 1800)
            return
        worker = CacheMaintenanceWorker(action, payload, self)
        self.cache_maintenance_worker = worker
        worker.completed.connect(self.on_cache_maintenance_completed)
        worker.failed.connect(self.on_cache_maintenance_failed)
        worker.finished.connect(lambda worker=worker: self.cleanup_cache_maintenance_worker(worker))
        self.show_toast(message, 1600)
        self.log(message)
        worker.start()

    def on_cache_maintenance_completed(self, action: str, result: Dict):
        if action == "clear_all":
            removed_paths = result.get("removed_paths") or []
            self.history_store = HistoryStore()
            self.download_store = DownloadStore()
            self.update_cache_path_label()
            self.show_toast(f"已清理全部运行缓存，删除 {len(removed_paths)} 个缓存路径", 2200)
            self.log(f"全部运行缓存后台清理完成：删除 {len(removed_paths)} 个缓存路径。")
            return
        if action == "clean_broken":
            removed_files = int(result.get("removed_files") or 0)
            removed_dirs = int(result.get("removed_dirs") or 0)
            for skipped in result.get("skipped") or []:
                self.log(f"缓存清理跳过 {skipped}")
            self.log(f"缓存清理完成：删除损坏文件 {removed_files} 个，空目录 {removed_dirs} 个。")
            self.show_toast(f"删除损坏文件 {removed_files} 个，空目录 {removed_dirs} 个")
            return
        if action == "export":
            target = result.get("target") or ""
            exported = result.get("exported") or []
            self.log(f"缓存已导出：{target}（{', '.join(exported) or '无可导出项目'}）")
            self.show_toast(f"缓存已导出到：{target}", 2200)
            return
        if action == "import":
            imported = result.get("imported") or []
            if not imported:
                self.show_toast("未找到可导入的 SQLite、reader_cache 或 cover_cache")
                return
            self.history_store = HistoryStore()
            self.download_store = DownloadStore()
            self.cover_cache.clear()
            self.cover_cache_refresh_attempted.clear()
            self.update_cache_path_label()
            self.log(f"缓存已导入：{', '.join(imported)}")
            self.show_toast(f"已导入：{', '.join(imported)}")

    def on_cache_maintenance_failed(self, action: str, message: str):
        self.log(f"缓存维护失败（{action}）：{message}")
        self.show_toast(f"缓存维护失败：{message}", 2600)

    def cleanup_cache_maintenance_worker(self, worker: CacheMaintenanceWorker):
        if worker is self.cache_maintenance_worker:
            self.cache_maintenance_worker = None
        worker.deleteLater()

    def quick_start_download(self):
        if self.result_total_count == 0 and self.id_edit.text().strip():
            self.start_scrape()
            return
        selected_before = len(self.queue)
        self.add_selected_albums_to_queue(switch_page=False, quiet=True)
        if len(self.queue) > selected_before:
            self.log(f"已加入下载队列，当前共 {len(self.queue)} 本。")
            self.show_floating_notice(f"已加入 {len(self.queue) - selected_before} 本漫画，后台开始下载")
            self.start_download_queue()
        self.clear_album_selection()

    def start_category_search(self, query: str):
        if not self.keeps_category_rank_results_visible():
            self.activate_home_search_results(query)
        self.id_edit.clear()
        self.search_edit.setText(query)
        self.active_category = ""
        self.start_scrape()

    def start_category_filter(self, category: str, label: str):
        self.clear_album_selection()
        self.id_edit.clear()
        self.search_edit.clear()
        self.active_category = str(category)
        if hasattr(self, "rank_group"):
            checked = self.rank_group.checkedButton()
            if checked:
                self.rank_group.setExclusive(False)
                checked.setChecked(False)
                self.rank_group.setExclusive(True)
        button = getattr(self, "category_buttons", {}).get(self.active_category)
        if button:
            button.setChecked(True)
        cache_key = self.result_cache_key()
        if (
            getattr(self, "active_result_surface", "home") == "category"
            and self.current_result_cache_key == cache_key
            and self.results_revealed
            and self.result_scroll.count() > 0
        ):
            self.result_stack.setCurrentWidget(self.result_scroll)
            self.set_backend_status(f"已显示{label}", "ok")
            self.schedule_visible_cover_requests()
            return
        self.set_backend_status(f"切换{label}", "busy")
        if hasattr(self, "result_loading_text"):
            self.result_loading_text.setText(f"正在加载{label}")
            self.result_stack.setCurrentWidget(self.result_loading_page)
        QTimer.singleShot(0, self.start_scrape)

    def selected_output_format(self) -> str:
        for value, button in self.format_buttons.items():
            if button.isChecked():
                return value
        return "pdf"

    def selected_rank_type(self) -> str:
        for value, button in self.rank_buttons.items():
            if button.isChecked():
                return value
        return self.pending_rank_request or "day"

    def result_cache_key(self) -> str:
        ids = split_ids(self.id_edit.text())
        if ids:
            return "ids:" + ",".join(ids)
        query = self.search_edit.text().strip()
        if query:
            surface = getattr(self, "active_result_surface", "home")
            return f"{surface}:search:{query}"
        if self.active_category:
            surface = getattr(self, "active_result_surface", "home")
            return f"{surface}:category:v2:{self.active_category}"
        if self.home_feed_mode == "latest":
            return "latest:v1"
        if self.home_feed_mode == "promote":
            return f"promote:{self.home_category_key or 'home'}:v1"
        return f"rank:{self.selected_rank_type()}"

    def start_rank_scrape(self, rank_type: str):
        self.clear_album_selection()
        self.search_edit.clear()
        self.id_edit.clear()
        self.active_category = ""
        self.home_feed_mode = "ranking"
        if hasattr(self, "category_group"):
            checked = self.category_group.checkedButton()
            if checked:
                self.category_group.setExclusive(False)
                checked.setChecked(False)
                self.category_group.setExclusive(True)
        button = self.rank_buttons.get(rank_type)
        if button:
            button.setChecked(True)
        self.pending_rank_request = rank_type
        if self.scrape_worker and self.scrape_worker.isRunning():
            old_worker = self.scrape_worker
            old_worker.cancel()
            self.retired_scrape_workers.append(old_worker)
            old_worker.finished.connect(lambda worker=old_worker: self.cleanup_retired_scrape_worker(worker))
            self.scrape_worker = None
        if self.cache_restore_worker and self.cache_restore_worker.isRunning():
            self.cache_restore_worker.requestInterruption()
        self.set_backend_status(f"切换{self.rank_label(rank_type)}", "busy")
        if hasattr(self, "result_loading_text"):
            self.result_loading_text.setText(f"正在加载{self.rank_label(rank_type)}")
            self.result_stack.setCurrentWidget(self.result_loading_page)
        QTimer.singleShot(0, self.start_scrape)

    @staticmethod
    def rank_label(rank_type: str) -> str:
        return {"day": "\u65e5\u699c", "week": "\u5468\u699c", "month": "\u6708\u699c"}.get(rank_type, "\u699c\u5355")
    def restore_results_from_cache(self, cache_key: str) -> bool:
        cached = self.result_cache.get(cache_key)
        if not cached:
            return False
        else:
            self.log(f"已从页面缓存恢复 {len(cached)} 本漫画。")
        if not cached:
            return False
        self.restore_album_list(cache_key, cached)
        self.set_backend_status("已从缓存加载", "ok")
        return True

    def restore_home_category_from_memory(self, cache_key: str, albums: List[AlbumMeta]):
        self._active_catalog_query_key = self.catalog_page_query().key
        self.catalog_apply_pending = False
        self.catalog_apply_context = None
        if self.scrape_worker and self.scrape_worker.isRunning():
            worker = self.scrape_worker
            worker.cancel()
            self.retired_scrape_workers.append(worker)
            worker.finished.connect(lambda worker=worker: self.cleanup_retired_scrape_worker(worker))
            self.scrape_worker = None
        if self.cache_restore_worker and self.cache_restore_worker.isRunning():
            self.cache_restore_worker.requestInterruption()
        # A promoted section in result_cache is its already-rendered first
        # source page. The controller tracks pagination separately from the
        # UI cache, so seed it before a bottom-scroll asks for more results.
        self.home_controller.seed_loaded_pages(self.catalog_page_query(), 1)
        if self.restore_retained_home_result_view(cache_key, albums):
            return
        self.prepare_home_result_view(cache_key)
        self.restore_album_list(cache_key, albums, fast_switch=True)
        self.loaded_source_pages = max(1, (len(albums) + 79) // 80)
        self.set_backend_status("已切换分区", "ok")

    def restore_album_list(
        self,
        cache_key: str,
        albums: List[AlbumMeta],
        fast_switch: bool = False,
    ):
        restored = list(albums) if fast_switch else [copy.deepcopy(album) for album in albums]
        self.reset_results(preserve_cover_requests=fast_switch)
        self.append_start_index = 0
        self.append_next_index = len(restored)
        self.auto_load_has_more = True
        self.auto_loading_next_page = False
        self.current_result_cache_key = cache_key
        self.result_total_count = len(restored)
        self.result_albums = restored
        self.result_album_indices = {album.album_id: index for index, album in enumerate(restored)}
        self.albums = {album.album_id: album for album in restored}
        self.detail_cache.update(
            {
                album.album_id: album if fast_switch else copy.deepcopy(album)
                for album in restored
            }
        )
        self.results_revealed = False
        self.current_result_page = max(1, min(self.current_result_page, self.result_total_pages() or 1))
        self.reveal_results(fast_switch=fast_switch)
        if fast_switch:
            self.result_scroll.verticalScrollBar().setValue(0)
        self.update_page_controls()

    def start_async_cache_restore(self, cache_key: str) -> bool:
        if not (
            cache_key.startswith("rank:")
            or cache_key.startswith("category:")
            or cache_key.startswith("promote:")
            or cache_key.startswith("latest:")
        ):
            return False
        cached = self.result_cache.get(cache_key)
        if not cached:
            return False
        if cache_key in self.cache_restore_miss_keys:
            return False
        if self.cache_restore_worker and self.cache_restore_worker.isRunning():
            self.cache_restore_worker.requestInterruption()
        worker = CacheRestoreWorker(cache_key, cached, self)
        self.cache_restore_worker = worker
        worker.loaded.connect(lambda key, albums, worker=worker: self.on_async_cache_loaded(key, albums, worker))
        worker.failed.connect(lambda key, message, worker=worker: self.on_async_cache_failed(key, message, worker))
        worker.start()
        return True

    def on_async_cache_loaded(self, cache_key: str, albums: List[AlbumMeta], worker: CacheRestoreWorker):
        if worker is not self.cache_restore_worker:
            return
        if cache_key != self.result_cache_key() or (self.scrape_worker and self.scrape_worker.isRunning()):
            return
        self.cache_restore_worker = None
        if not albums:
            self.cache_restore_miss_keys.add(cache_key)
            self.start_scrape()
            return
        self.log(f"已后台读取本地缓存 {len(albums)} 本，正在显示当前榜单。")
        self.result_cache[cache_key] = [copy.deepcopy(album) for album in albums]
        self.restore_album_list(cache_key, albums)
        self.loaded_source_pages = max(1, (len(self.result_albums) + 79) // 80)
        self.set_backend_status("已从缓存加载", "ok")

    def on_async_cache_failed(self, cache_key: str, message: str, worker: CacheRestoreWorker):
        if worker is not self.cache_restore_worker:
            return
        if cache_key == self.result_cache_key():
            self.cache_restore_worker = None
            self.cache_restore_miss_keys.add(cache_key)
            self.log(f"本地缓存读取失败，改为联网加载：{message}")
            self.start_scrape()

    def network_config(self) -> NetworkConfig:
        return NetworkConfig(
            cookie_header=self.cookie_edit.toPlainText().strip(),
            user_agent=self.ua_edit.text().strip() or DEFAULT_USER_AGENT,
            delay_min=float(self.delay_min.value()),
            delay_max=float(self.delay_max.value()),
            retries=self.retries.value(),
            backoff_seconds=self.backoff.value(),
            stop_on_block=self.stop_on_block.isChecked(),
            username=self.session_username,
            password=self.session_password,
            proxy=self.effective_proxy(),
            detail_threads=self.detail_threads.value(),
            protocol_parser=self.protocol_parser.isChecked() if hasattr(self, "protocol_parser") else True,
            api_route=getattr(self, "api_route", 0),
            image_route=int(self.image_route_combo.currentData() or 0) if hasattr(self, "image_route_combo") else 0,
            doh_enabled=self.doh_enabled_box.isChecked() if hasattr(self, "doh_enabled_box") else True,
            doh_url=self.doh_url_edit.text().strip() if hasattr(self, "doh_url_edit") else DOH_URL,
            custom_api_domain=self.custom_api_domain_edit.text().strip() if hasattr(self, "custom_api_domain_edit") else "",
            custom_image_domain=self.custom_image_domain_edit.text().strip() if hasattr(self, "custom_image_domain_edit") else "",
        )

    def download_config(self) -> DownloadConfig:
        base = self.network_config()
        return DownloadConfig(
            cookie_header=base.cookie_header,
            user_agent=base.user_agent,
            delay_min=base.delay_min,
            delay_max=base.delay_max,
            retries=base.retries,
            backoff_seconds=base.backoff_seconds,
            stop_on_block=base.stop_on_block,
            username=base.username,
            password=base.password,
            proxy=base.proxy,
            detail_threads=base.detail_threads,
            api_route=base.api_route,
            image_route=base.image_route,
            doh_enabled=base.doh_enabled,
            doh_url=base.doh_url,
            custom_api_domain=base.custom_api_domain,
            custom_image_domain=base.custom_image_domain,
            output_dir=Path(self.output_edit.text()).expanduser(),
            image_threads=self.image_threads.value(),
            output_format=self.selected_output_format(),
            pdf_split_chapters=self.make_pdf.isChecked(),
            keep_images=self.keep_images.isChecked(),
            reading_mode=self.reading_mode_combo.currentData() if hasattr(self, "reading_mode_combo") else "scroll",
            cache_as_webp=self.cache_as_webp.isChecked() if hasattr(self, "cache_as_webp") else False,
            protocol_parser=self.protocol_parser.isChecked() if hasattr(self, "protocol_parser") else True,
        )

    def background_download_config(self) -> DownloadConfig:
        config = copy.deepcopy(self.download_config())
        config.image_threads = max(1, min(12, config.image_threads))
        config.detail_threads = max(1, min(6, config.detail_threads))
        config.delay_min = max(0.2, min(config.delay_min, 1.0))
        config.delay_max = max(config.delay_min, min(config.delay_max, 2.0))
        return config

    def catalog_page_query(self) -> PageQuery:
        search = self.search_edit.text().strip()
        if search:
            return PageQuery(mode="search", search=search)
        if self.active_category:
            return PageQuery(mode="category", category=self.active_category)
        if self.home_feed_mode == "latest":
            return PageQuery(mode="latest")
        if self.home_feed_mode == "promote":
            return PageQuery(mode="promote", promote_section=self.home_category_prefix)
        return PageQuery(mode="ranking", rank_type=self.selected_rank_type())

    @staticmethod
    def album_from_book_info(book: BookInfo) -> AlbumMeta:
        return AlbumMeta(
            album_id=book.book_id,
            title=book.title,
            url=book.url,
            cover_url=book.cover_url,
            author=book.author,
            tags=list(book.tags),
            description=book.description,
            likes=book.likes,
            views=book.views,
            page_count=book.page_count,
            source=book.source or "API",
            chapters=[ChapterMeta(item.chapter_id, item.title, item.url, item.index) for item in book.chapters],
        )

    def start_catalog_page(self, append: bool) -> None:
        query = self.catalog_page_query()
        force_refresh = bool(getattr(self, "_force_home_catalog_refresh", False))
        self._active_catalog_query_key = query.key
        cache_key = self.result_cache_key()
        self.set_backend_status("正在后台获取更多" if append else "正在请求", "busy")
        if not append:
            cached = self.result_cache.get(cache_key)
            if (
                getattr(self, "active_result_surface", "home") == "category"
                and cached
                and self.restore_retained_home_result_view(cache_key, cached)
            ):
                self.current_result_cache_key = cache_key
                self.loaded_source_pages = max(1, (len(cached) + 79) // 80)
                self.auto_load_has_more = True
                self.set_backend_status("已切换分区", "ok")
                self.update_page_controls()
                self.schedule_visible_cover_requests()
                return
            self.prepare_home_result_view(cache_key)
            self.reset_results()
            self.loaded_source_pages = 0
            self.auto_load_has_more = True
            self.current_result_cache_key = cache_key
            if not self.keeps_category_rank_results_visible():
                on_search_page = getattr(self, "active_result_surface", "home") == "search"
                self.switch_page(
                    self.search_page_index() if on_search_page else self.home_page_index(),
                    preserve_path=on_search_page,
                    breadcrumb_title="搜索" if on_search_page else "",
                )
            self.start_loading("正在获取漫画资源")
            self.progress.setValue(0)
            if (
                not force_refresh
                and self.home_feed_mode != "latest"
                and self.home_controller.restore(query)
            ):
                return
            self.home_controller.refresh(query)
            return
        self.append_start_index = len([album for album in self.result_albums if album is not None])
        self.append_next_index = self.append_start_index
        self.current_result_cache_key = cache_key
        self.home_controller.load_next(query)

    def on_catalog_page_loaded(self, query: PageQuery, source_page: int, books: List[BookInfo], metadata: Dict):
        if query.key != getattr(self, "_active_catalog_query_key", ""):
            return
        append = bool(metadata.get("append"))
        if metadata.get("sections"):
            self.on_promote_sections_ready(
                {
                    title: [self.album_from_book_info(book) for book in section_books]
                    for title, section_books in metadata["sections"].items()
                }
            )
        if (
            getattr(self, "result_list_mode", False)
            and getattr(self, "active_result_surface", "home") != "category"
        ):
            self.apply_catalog_page_directly(query, source_page, books, append)
            if query.mode == "latest" and source_page == 1 and not append:
                self.prefetch_home_sections()
            return
        self.on_scrape_total_known(len(books), source_page, append)
        self.catalog_apply_pending = True
        self.catalog_apply_context = {
            "query": query,
            "source_page": source_page,
            "books": list(books),
            "append": append,
            "next_index": 0,
        }
        QTimer.singleShot(0, self.flush_catalog_page_items)

    def apply_catalog_page_directly(
        self, query: PageQuery, source_page: int, books: List[BookInfo], append: bool
    ) -> None:
        """Apply a returned page in short UI turns while the feed stays usable."""
        self.on_scrape_total_known(len(books), source_page, append)
        self.result_render_limit = max(self.result_render_limit, self.result_total_count)
        self.catalog_apply_pending = True
        self.catalog_apply_context = {
            "query": query,
            "source_page": source_page,
            "books": list(books),
            "append": append,
            "next_index": 0,
            "direct_list": True,
        }
        QTimer.singleShot(0, self.flush_catalog_page_items)

    def flush_catalog_page_items(self):
        """Apply a fetched page without monopolizing the GUI thread."""
        context = self.catalog_apply_context
        if not self.catalog_apply_pending or not context:
            return
        query = context["query"]
        if query.key != getattr(self, "_active_catalog_query_key", ""):
            self.catalog_apply_pending = False
            self.catalog_apply_context = None
            return

        books = context["books"]
        start = context["next_index"]
        batch_size = 4 if getattr(self, "active_result_surface", "home") == "category" else CATALOG_APPLY_BATCH_SIZE
        end = min(len(books), start + batch_size)
        self.catalog_batch_insert = True
        direct_list = bool(context.get("direct_list"))
        self.catalog_direct_list_insert = direct_list
        try:
            for index in range(start, end):
                self.on_scrape_album_found(
                    index,
                    self.album_from_book_info(books[index]),
                    context["source_page"],
                    context["append"],
                )
        finally:
            self.catalog_batch_insert = False
            if end < len(books):
                self.catalog_direct_list_insert = False
        self.update_page_controls()
        context["next_index"] = end
        if end < len(books):
            QTimer.singleShot(APPEND_RENDER_INTERVAL_MS, self.flush_catalog_page_items)
            return

        self.catalog_apply_pending = False
        self.catalog_apply_context = None
        try:
            self.on_scrape_finished(context["source_page"], context["append"])
        finally:
            self.catalog_direct_list_insert = False
        if query.mode == "latest" and context["source_page"] == 1 and not context["append"]:
            self.prefetch_home_sections()

    def prefetch_home_sections(self):
        if self.home_sections_prefetch_started:
            return
        self.home_sections_prefetch_started = True
        self.home_controller.prefetch_sections(PageQuery(mode="promote"))

    def on_catalog_sections_prefetched(self, _query: PageQuery, sections: Dict[str, List[BookInfo]]):
        if not sections:
            return
        self.on_promote_sections_ready(
            {
                title: [self.album_from_book_info(book) for book in section_books]
                for title, section_books in sections.items()
            }
        )
        self.set_home_section_tabs_ready(True)
        section_count = sum(len(items) for items in sections.values())
        self.log(f"首页其它分区已预取：{len(sections)} 个分区，{section_count} 本漫画。")

    def on_catalog_sections_prefetch_failed(self, _query: PageQuery, message: str):
        self.home_sections_prefetch_started = False
        # A failed prefetch must not lock the other categories out; selecting
        # one will fall back to its own request.
        self.set_home_section_tabs_ready(True)
        self.log(f"首页其它分区预取失败：{message}")

    def on_catalog_page_failed(self, query: PageQuery, message: str):
        if query.key == getattr(self, "_active_catalog_query_key", ""):
            self.on_scrape_failed(message)

    def on_catalog_detail_loaded(self, book: BookInfo):
        self.on_chapters_loaded(book.book_id, self.album_from_book_info(book))

    def on_catalog_detail_failed(self, book_id: str, message: str):
        self.log(f"详情加载失败 {book_id}：{message}")
        if self.current_album_id != book_id:
            return
        self.hide_detail_loading_overlay()
        if book_id in self.albums:
            self.show_chapters(book_id)
        self.set_backend_status("详情加载失败", "warn")
        self.show_toast("漫画详情加载失败", 1800)

    def start_scrape(self, source_page: int = 1, append: bool = False):
        if not append:
            self.clear_album_selection()
        if self.scrape_worker and self.scrape_worker.isRunning():
            if append:
                return
            old_worker = self.scrape_worker
            old_worker.cancel()
            self.retired_scrape_workers.append(old_worker)
            old_worker.finished.connect(lambda worker=old_worker: self.cleanup_retired_scrape_worker(worker))
            self.scrape_worker = None
        if not split_ids(self.id_edit.text()):
            self.start_catalog_page(append)
            return
        cache_key = self.result_cache_key()
        if not append and self.restore_results_from_cache(cache_key):
            self.loaded_source_pages = max(1, (len(self.result_albums) + 79) // 80)
            return
        self.set_backend_status("正在后台获取更多" if append else "\u6b63\u5728\u8bf7\u6c42", "busy")
        if not append:
            self.prepare_home_result_view(cache_key)
            self.reset_results()
            self.loaded_source_pages = 0
            self.auto_load_has_more = True
        else:
            self.append_start_index = len([album for album in self.result_albums if album is not None])
            self.append_next_index = self.append_start_index
        self.current_result_cache_key = cache_key
        worker = ScrapeWorker(
            list_url=self.list_url_edit.text().strip() or LIST_URL,
            ids=split_ids(self.id_edit.text()),
            include_detail=self.detail_check.isChecked(),
            config=self.network_config(),
            search_query=self.search_edit.text().strip(),
            rank_type=self.selected_rank_type(),
            category=self.active_category,
            promote=bool(
                self.home_feed_mode == "promote"
                and not self.active_category
                and not self.search_edit.text().strip()
                and not split_ids(self.id_edit.text())
            ),
            latest=bool(
                self.home_feed_mode == "latest"
                and not self.active_category
                and not self.search_edit.text().strip()
                and not split_ids(self.id_edit.text())
            ),
            promote_section=self.home_category_prefix if self.home_feed_mode == "promote" else "",
            list_pages=source_page,
        )
        self.scrape_worker = worker
        worker.total_known.connect(lambda total, worker=worker, source_page=source_page, append=append: self.on_scrape_total_known(total, source_page, append) if worker is self.scrape_worker else None)
        worker.promote_sections_ready.connect(
            lambda sections, worker=worker: self.on_promote_sections_ready(sections) if worker is self.scrape_worker else None
        )
        worker.album_found_at.connect(lambda index, album, worker=worker, source_page=source_page, append=append: self.on_scrape_album_found(index, album, source_page, append) if worker is self.scrape_worker else None)
        worker.log.connect(lambda message, worker=worker: self.log(message) if worker is self.scrape_worker else None)
        worker.progress.connect(lambda done, total, worker=worker: self.set_progress(done, total) if worker is self.scrape_worker else None)
        worker.finished_ok.connect(
            lambda worker=worker, source_page=source_page, append=append: self.on_scrape_finished(source_page, append) if worker is self.scrape_worker else None
        )
        worker.failed.connect(lambda message, worker=worker: self.on_scrape_failed(message) if worker is self.scrape_worker else None)
        if not self.keeps_category_rank_results_visible():
            on_search_page = getattr(self, "active_result_surface", "home") == "search"
            self.switch_page(
                self.search_page_index() if on_search_page else self.home_page_index(),
                preserve_path=on_search_page,
                breadcrumb_title="搜索" if on_search_page else "",
            )
        if not append:
            self.start_loading("正在获取漫画资源")
        self.progress.setValue(0)
        worker.start()

    def on_scrape_total_known(self, total: int, source_page: int, append: bool):
        if append:
            self.set_result_total(self.append_start_index + total)
        else:
            self.set_result_total(total)

    def on_scrape_album_found(self, index: int, album: AlbumMeta, source_page: int, append: bool):
        if append:
            existing_index = self.result_album_indices.get(album.album_id)
            if existing_index is not None:
                # A detail-prefetch update or an overlapping source page should
                # refresh the existing card, never reserve a second slot.
                self.upsert_album_at(existing_index, album)
                return
            target_index = self.append_next_index
            self.append_next_index += 1
            self.upsert_album_at(target_index, album)
            if self.results_revealed:
                self.result_render_limit = max(self.result_render_limit, target_index + 1)
                if (
                    getattr(self, "catalog_direct_list_insert", False)
                    and album.album_id not in self.card_by_id
                ):
                    self.append_visible_album_card(
                        album,
                        animate=False,
                        update_controls=False,
                        defer_cover=True,
                    )
            return
        self.upsert_album_at(index, album)
        if not getattr(self, "catalog_direct_list_insert", False):
            self.log(f"加载漫画 {index + 1}：{album.title}（{album.album_id}）")
        # The list request has already supplied a usable card.  Reveal the
        # page immediately instead of waiting for optional detail prefetch.
        if not self.results_revealed:
            self.reveal_results()

    def on_scrape_finished(self, source_page: int, append: bool):
        loaded_count = len([album for album in self.result_albums if album is not None])
        appended_count = max(0, self.append_next_index - self.append_start_index) if append else loaded_count
        self.loaded_source_pages = max(self.loaded_source_pages, source_page)
        if append and loaded_count < self.result_total_count:
            self.set_result_total(loaded_count)
        self.auto_loading_next_page = False
        if append:
            # Card signals can arrive before the grid is ready or while the
            # append indicator owns the next row. Reconcile only the new
            # range once the page has completed without rebuilding the feed.
            if self.results_revealed and appended_count:
                self.result_render_limit = max(self.result_render_limit, loaded_count)
                if getattr(self, "catalog_direct_list_insert", False):
                    self.schedule_visible_cover_requests()
                    self.log(f"第 {source_page} 页已直接插入 {appended_count} 本漫画。")
                else:
                    self.queue_appended_result_cards(self.append_start_index, loaded_count)
                    self.log(f"第 {source_page} 页已获取 {appended_count} 本，正在逐步显示。")
            if getattr(self, "catalog_direct_list_insert", False) or not self.append_render_pending:
                self.hide_home_append_loading()
        if loaded_count == 0 or (append and appended_count == 0):
            self.auto_load_has_more = False
        self.scrape_worker = None
        self.current_result_page = 1
        self.pending_result_page = 0
        if not self.results_revealed:
            self.reveal_results()
            self.result_scroll.verticalScrollBar().setValue(0)
        if loaded_count == 0 and not append:
            self.show_library_feed_empty_state(self.result_scroll, "暂无漫画")
        if not append:
            lock_thumb_size = getattr(self.result_scroll.verticalScrollBar(), "lock_thumb_size", None)
            if callable(lock_thumb_size):
                lock_thumb_size()
        self.result_page_switching = False
        self.update_page_controls()
        active_surface = getattr(self, "active_result_surface", "home")
        completion_page = (
            self.home_page_index() if active_surface == "home" else None
        )
        self.task_done("采集完成。", completion_page)
        QTimer.singleShot(0, self.maybe_auto_load_if_result_viewport_not_full)
    def on_scrape_failed(self, message: str):
        self.scrape_worker = None
        self.auto_loading_next_page = False
        self.hide_home_append_loading()
        self.finish_home_initial_loading()
        self.pending_result_page = 0
        self.result_page_switching = False
        self.update_page_controls()
        if self.result_total_count:
            self.result_stack.setCurrentWidget(self.result_scroll)
        elif hasattr(self, "result_stack"):
            self.results_revealed = True
            self.result_stack.setCurrentWidget(self.result_scroll)
            self.show_library_feed_empty_state(self.result_scroll, "漫画加载失败")
        self.task_failed(message)

    def cleanup_retired_scrape_worker(self, worker: ScrapeWorker):
        if worker in self.retired_scrape_workers:
            self.retired_scrape_workers.remove(worker)

    def load_current_chapters(self, force_refresh: bool = True):
        album = self.current_album()
        if not album:
            self.show_toast("请先选择一个漫画")
            return
        cached = self.detail_cache.get(album.album_id)
        if not force_refresh and cached and cached.chapters and self.album_has_detail_metadata(cached):
            self.albums[album.album_id] = copy.deepcopy(cached)
            self.show_chapters(album.album_id)
            self.set_backend_status("已从缓存加载", "ok")
            self.log(f"已从缓存加载章节：{cached.title}")
            return
        if not force_refresh and album.chapters and self.album_has_detail_metadata(album):
            self.detail_cache[album.album_id] = copy.deepcopy(album)
            self.show_chapters(album.album_id)
            self.set_backend_status("已从缓存加载", "ok")
            self.log(f"已从缓存加载章节：{album.title}")
            return
        if self.chapter_worker and self.chapter_worker.isRunning():
            if self.chapter_worker.album.album_id == album.album_id:
                return
            self.chapter_worker.cancel()
        self.log(f"请求漫画详情：{album.title}（{album.album_id}）")
        self.start_detail_loading(album)
        self.detail_controller.load(album.album_id)
        self.set_backend_status("正在加载章节", "busy")

    def clear_chapter_worker(self, worker: ChapterWorker):
        if worker is self.chapter_worker:
            self.chapter_worker = None

    def start_detail_loading(self, album: AlbumMeta):
        if self.current_album_id != album.album_id:
            return
        if getattr(self, "detail_description_label", None):
            self.detail_description_label.setText("正在加载漫画详情...")
        if getattr(self, "chapter_table", None):
            self.chapter_table.setRowCount(0)
        if getattr(self, "cover_label", None):
            self.cover_label.setPixmap(QPixmap())
            self.apply_detail_loading_movie(self.cover_label)
        self.show_detail_loading_overlay()

    def show_detail_loading_overlay(self):
        overlay = getattr(self, "detail_loading_overlay", None)
        panel = getattr(self, "detail_panel", None)
        if overlay is None or panel is None:
            return
        self.stop_label_movie(overlay)
        if DETAIL_LOADING_MOVIE_PATH.exists():
            movie = QMovie(str(DETAIL_LOADING_MOVIE_PATH))
            movie.setScaledSize(QSize(256, 256))
            overlay.setMovie(movie)
            overlay._loading_movie = movie
            movie.start()
        else:
            overlay.setText("正在加载详情")
        overlay.move(max(0, (panel.width() - overlay.width()) // 2), max(0, (panel.height() - overlay.height()) // 2))
        overlay.raise_()
        overlay.show()

    def hide_detail_loading_overlay(self):
        overlay = getattr(self, "detail_loading_overlay", None)
        if overlay is None:
            return
        self.stop_label_movie(overlay)
        overlay.hide()

    def apply_detail_loading_movie(self, label: QLabel, size: Optional[QSize] = None):
        self.stop_label_movie(label)
        if DETAIL_LOADING_MOVIE_PATH.exists():
            movie = QMovie(str(DETAIL_LOADING_MOVIE_PATH))
            movie.setScaledSize(size or QSize(126, 126))
            label.setMovie(movie)
            label._loading_movie = movie
            movie.start()
            return
        label.setText("正在加载")

    def on_album_detail_failed(self, album_id: str, message: str, worker: ChapterWorker):
        if worker is self.chapter_worker:
            self.chapter_worker = None
        self.log(f"详情加载失败 {album_id}：{message}")
        if self.current_album_id != album_id:
            return
        self.hide_detail_loading_overlay()
        album = self.albums.get(album_id) or self.detail_cache.get(album_id)
        if album:
            self.show_chapters(album_id)
        if getattr(self, "detail_description_label", None):
            self.detail_description_label.setText("详情加载失败，已显示列表信息。")
        self.set_backend_status("详情加载失败", "warn")
        self.show_toast("漫画详情加载失败", 1800)

    def on_chapters_loaded(self, album_id: str, detail_or_chapters):
        existing = self.albums.get(album_id) or self.detail_cache.get(album_id)
        resolved = None
        if isinstance(detail_or_chapters, AlbumMeta):
            resolved = detail_or_chapters
            if existing and existing.cover_url and not resolved.cover_url:
                resolved.cover_url = existing.cover_url
        elif existing is not None:
            resolved = copy.deepcopy(existing)
            resolved.chapters = detail_or_chapters
        if resolved is not None:
            self.detail_cache[album_id] = copy.deepcopy(resolved)
            if album_id in self.albums:
                self.albums[album_id] = resolved
                self.update_album_row(resolved)
                self.update_album_card_content(resolved)
            self.schedule_local_cache_save()
            self.log(f"详情加载完成：{resolved.title}，{len(resolved.chapters)} 个章节")
        if (
            self.current_album_id == album_id
            and hasattr(self, "main_content_stack")
            and self.main_content_stack.currentIndex() == self.detail_page_index()
        ):
            self.update_breadcrumb("漫画详情")
        self.show_chapters(album_id)
        if self.current_album_id == album_id:
            self.hide_detail_loading_overlay()
            self.set_backend_status("详情加载完成", "ok")
        QTimer.singleShot(80, self.refresh_task_controls)

    def reset_results(self, preserve_cover_requests: bool = False):
        self.hide_home_append_loading()
        scrollbar = getattr(self, "result_scroll", None)
        if scrollbar is not None:
            reset_target = getattr(scrollbar.verticalScrollBar(), "reset_target", None)
            if callable(reset_target):
                reset_target()
            reset_thumb_size = getattr(scrollbar.verticalScrollBar(), "reset_thumb_size", None)
            if callable(reset_thumb_size):
                reset_thumb_size()
        self.albums.clear()
        self.row_by_id.clear()
        self.card_by_id.clear()
        self.checkmark_by_id.clear()
        self.result_cover_labels.clear()
        self.result_cover_requested.clear()
        self.card_click_timers.clear()
        self.selected_album_ids.clear()
        self.cover_targets.clear()
        if not preserve_cover_requests:
            self.cover_pending.clear()
            self.cover_fallback_urls.clear()
            self.cover_request_queue.clear()
            self.cover_cache_refresh_attempted.clear()
            for worker in list(self.cover_workers.values()):
                if worker.isRunning():
                    cancel = getattr(worker, "cancel", None)
                    if callable(cancel):
                        cancel()
                    else:
                        worker.requestInterruption()
            self.cover_workers.clear()
            for worker in list(self.cover_decode_workers.values()):
                if worker.isRunning():
                    worker.requestInterruption()
            self.cover_decode_workers.clear()
        self.result_albums = []
        self.result_album_indices.clear()
        self.result_total_count = 0
        self.current_result_page = 1
        self.result_render_limit = RESULT_INITIAL_RENDER_COUNT
        self.results_revealed = False
        self.result_render_pending = False
        self.result_page_switching = False
        self.pending_result_page = 0
        self.append_start_index = 0
        self.append_next_index = 0
        self.append_render_pending = False
        self.append_render_next_index = 0
        self.append_render_end_index = 0
        self.append_render_generation = 0
        self.append_render_scroll_value = 0
        self.append_layout_freeze = False
        self.catalog_apply_pending = False
        self.catalog_apply_context = None
        self.result_render_generation += 1
        self.clear_result_grid()
        if hasattr(self, "result_stack"):
            self.show_home_initial_loading("正在加载漫画")
        self.update_page_controls()
        self.schedule_visible_cover_requests()

    def set_result_total(self, total: int):
        new_total = max(0, total)
        old_albums = list(self.result_albums)
        self.result_total_count = new_total
        self.result_albums = [None] * self.result_total_count
        for index, album in enumerate(old_albums[: self.result_total_count]):
            self.result_albums[index] = album
        self.result_album_indices = {
            album.album_id: index
            for index, album in enumerate(self.result_albums)
            if album is not None
        }
        if not any(self.result_albums):
            self.current_result_page = 1
            self.results_revealed = False
            self.clear_result_grid()
            self.result_stack.setCurrentWidget(self.result_loading_page)
        if self.result_total_count == 0:
            self.reveal_results()
        self.update_page_controls()
        self.schedule_visible_cover_requests()

    def upsert_album_at(self, index: int, album: AlbumMeta):
        if index < 0:
            return
        if index >= len(self.result_albums):
            self.result_albums.extend([None] * (index + 1 - len(self.result_albums)))
            self.result_total_count = len(self.result_albums)
        previous = self.result_albums[index]
        if previous is not None and previous.album_id != album.album_id:
            if self.result_album_indices.get(previous.album_id) == index:
                self.result_album_indices.pop(previous.album_id, None)
        self.result_albums[index] = album
        self.result_album_indices[album.album_id] = index
        self.albums[album.album_id] = album
        self.detail_cache[album.album_id] = copy.deepcopy(album)
        start, end = self.current_page_bounds()
        if self.results_revealed and start <= index < end:
            if self.result_stack.currentWidget() is self.result_loading_page:
                self.render_result_page()
                self.result_stack.setCurrentWidget(self.result_scroll)
                self.schedule_result_layout_after_show()
            elif index - start < self.result_render_limit:
                if not self.update_album_card_content(album):
                    batched = bool(getattr(self, "catalog_batch_insert", False))
                    self.append_visible_album_card(
                        album,
                        animate=not batched,
                        update_controls=not batched,
                        defer_cover=batched,
                    )

    def is_page_loaded(self, start: int, end: int) -> bool:
        if self.result_total_count == 0:
            return True
        if end <= start:
            return False
        return all(index < len(self.result_albums) and self.result_albums[index] is not None for index in range(start, end))

    def is_page_partially_loaded(self, start: int, end: int) -> bool:
        if self.result_total_count == 0:
            return True
        if end <= start:
            return False
        return any(index < len(self.result_albums) and self.result_albums[index] is not None for index in range(start, end))

    def reveal_results(self, fast_switch: bool = False):
        self.results_revealed = True
        self.render_result_page(fast_switch=fast_switch)
        self.result_stack.setCurrentWidget(self.result_scroll)
        self.finish_home_initial_loading()
        self.schedule_result_layout_after_show()

    def schedule_result_layout_after_show(self):
        if getattr(self, "result_list_mode", False):
            return
        if self.result_resize_pending:
            return
        self.result_resize_pending = True
        QTimer.singleShot(40, self.refresh_result_layout)

    def fade_in_result_scroll(self, duration: int = 220):
        # The footer shares the result panel with this scroll area. Do not animate
        # its geometry, otherwise it can overlap the fixed pagination controls.
        self.animate_enter(self.result_scroll, duration, offset_y=0, scale_px=0)

    def schedule_result_render(self):
        if self.result_render_pending:
            return
        self.result_render_pending = True
        QTimer.singleShot(80, self.flush_result_render)

    def flush_result_render(self):
        self.result_render_pending = False
        if hasattr(self, "result_stack") and self.result_stack.currentWidget() is self.result_scroll:
            self.render_result_page()

    def update_album_card_content(self, album: AlbumMeta) -> bool:
        card = self.card_by_id.get(album.album_id)
        if not card:
            return False
        try:
            card_width = max(60, card.width() - 10)
            title = card.findChild(QLabel, "albumTitle")
            if title:
                title.setText(self.elided_album_title(album.title or "-", title.font(), max(60, card_width - 20), 2))
                title.setToolTip(album.title)
            meta = card.findChild(QLabel, "albumMeta")
            if meta:
                meta.setText(f"\u2764 {album.likes}   {album.page_count}")
            card.setStyleSheet(self.album_card_style(album.album_id in self.selected_album_ids))
            return True
        except RuntimeError:
            return False

    def append_visible_album_card(
        self,
        album: AlbumMeta,
        animate: bool = True,
        update_controls: bool = True,
        defer_cover: bool = False,
    ):
        if album.album_id in self.card_by_id:
            self.update_album_card_content(album)
            return
        # Like JMComic-qt's ComicItemWidget.paintEvent, every home-list card
        # gets its fixed text/layout first. Its cover stays a placeholder until
        # the card is actually painted in the visible viewport.
        card = self.create_album_card(
            album,
            defer_cover=defer_cover or getattr(self, "result_list_mode", False),
        )
        if getattr(self, "result_list_mode", False):
            # Keep the insertion sequence identical to JMComic-qt's
            # ComicListWidget.AddBookItem: create the item in the view, give
            # it a fixed geometry, then attach the already-built card widget.
            # This produces one model insertion per comic and avoids the
            # selection repaint caused by QListWidget's default item flags.
            item = QListWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setSizeHint(card.size())
            loading_item = getattr(self.result_scroll, "_append_loading_item", None)
            loading_row = -1
            if loading_item is not None:
                try:
                    loading_row = self.result_scroll.row(loading_item)
                except RuntimeError:
                    loading_row = -1
            if loading_row >= 0:
                self.result_scroll.insertItem(loading_row, item)
            else:
                self.result_scroll.addItem(item)
            self.result_scroll.setItemWidget(item, card)
            card._list_item = item
            self.card_by_id[album.album_id] = card
            card.show()
            if update_controls:
                self.update_page_controls()
            return
        columns = self.result_columns()
        visible_index = len(self.card_by_id)
        row = visible_index // columns
        col = visible_index % columns
        self.result_grid.addWidget(card, row, col)
        self.card_by_id[album.album_id] = card
        if animate:
            self.safe_fade_in_card(card)
        else:
            card.show()
        for col_index in range(columns):
            self.result_grid.setColumnStretch(col_index, 1)
        if update_controls:
            self.update_page_controls()

    def append_loaded_result_cards(self, start_index: int, end_index: int):
        """Render only new cards that missed their incremental append signal."""
        if not self.results_revealed:
            return
        start_index = max(0, start_index)
        end_index = min(max(start_index, end_index), len(self.result_albums))
        for index in range(start_index, end_index):
            album = self.result_albums[index]
            if album is not None and album.album_id not in self.card_by_id:
                self.append_visible_album_card(album)
        self.schedule_result_layout_after_show()
        self.schedule_visible_cover_requests()

    def queue_appended_result_cards(self, start_index: int, end_index: int):
        """Render an appended source page over several event-loop turns."""
        if not self.results_revealed:
            return
        start_index = max(0, start_index)
        end_index = min(max(start_index, end_index), len(self.result_albums))
        if start_index >= end_index:
            return
        if self.append_render_pending:
            self.append_render_end_index = max(self.append_render_end_index, end_index)
            return
        self.append_render_pending = True
        self.append_render_next_index = start_index
        self.append_render_end_index = end_index
        self.append_render_generation = self.result_render_generation
        self.append_layout_freeze = False
        QTimer.singleShot(0, self.flush_appended_result_cards)

    def flush_appended_result_cards(self):
        if not self.append_render_pending:
            return
        if (
            self.append_render_generation != self.result_render_generation
            or not self.results_revealed
        ):
            self.append_render_pending = False
            self.append_layout_freeze = False
            self.hide_home_append_loading()
            return

        processed = 0
        while (
            self.append_render_next_index < self.append_render_end_index
            and processed < APPEND_RENDER_BATCH_SIZE
        ):
            index = self.append_render_next_index
            self.append_render_next_index += 1
            processed += 1
            album = self.result_albums[index]
            if album is None or album.album_id in self.card_by_id:
                continue
            self.append_visible_album_card(
                album,
                animate=False,
                update_controls=False,
                defer_cover=True,
            )

        if self.append_render_next_index < self.append_render_end_index:
            QTimer.singleShot(APPEND_RENDER_INTERVAL_MS, self.flush_appended_result_cards)
            return

        self.append_render_pending = False
        self.append_layout_freeze = False
        self.hide_home_append_loading()
        self.update_page_controls()
        if not getattr(self, "result_list_mode", False):
            self.result_grid.invalidate()
            self.result_grid.activate()
            self.result_grid_widget.updateGeometry()
        self.schedule_visible_cover_requests()
        QTimer.singleShot(0, self.maybe_auto_load_if_result_viewport_not_full)

    def release_append_layout_freeze(self):
        self.append_layout_freeze = False

    def upsert_album(self, album: AlbumMeta):
        self.albums[album.album_id] = album
        self.detail_cache[album.album_id] = copy.deepcopy(album)

    def update_album_row(self, album: AlbumMeta):
        self.albums[album.album_id] = album
        self.detail_cache[album.album_id] = copy.deepcopy(album)
        index = self.result_album_indices.get(album.album_id)
        if index is not None and index < len(self.result_albums):
            self.result_albums[index] = album

    def render_result_page(self, fast_switch: bool = False):
        self.clear_result_grid()
        generation = self.result_render_generation
        self.row_by_id.clear()
        self.card_by_id.clear()
        self.checkmark_by_id.clear()
        self.result_cover_labels.clear()
        self.result_cover_requested.clear()
        self.clear_card_click_timers()
        start, end = self.current_page_bounds()
        end = min(end, start + self.result_render_limit)
        if getattr(self, "result_list_mode", False):
            for index in range(start, end):
                if index >= len(self.result_albums):
                    break
                album = self.result_albums[index]
                if album is not None:
                    self.append_visible_album_card(album, animate=False, update_controls=False)
            self.update_page_controls()
            if fast_switch:
                self.schedule_visible_cover_requests()
            return
        visible_index = 0
        columns = self.result_columns()
        for index in range(start, end):
            if index >= len(self.result_albums):
                break
            album = self.result_albums[index]
            if album is None:
                continue
            card = self.create_album_card(album, show_loading=False)
            row = visible_index // columns
            col = visible_index % columns
            self.result_grid.addWidget(card, row, col)
            self.card_by_id[album.album_id] = card
            if fast_switch:
                card.show()
            else:
                QTimer.singleShot(
                    visible_index * 18,
                    lambda card=card, generation=generation: self.safe_fade_in_card(card, generation),
                )
            visible_index += 1
        for col in range(columns):
            self.result_grid.setColumnStretch(col, 1)
        self.update_page_controls()
        if fast_switch:
            self.schedule_visible_cover_requests()

    def safe_animate_enter(self, widget: QWidget, duration: int = 260, offset_y: int = 18, scale_px: int = 8):
        try:
            self.animate_enter(widget, duration, offset_y, scale_px)
        except RuntimeError:
            pass

    def safe_fade_in_card(self, card: QWidget, generation: Optional[int] = None):
        try:
            if generation is not None and generation != self.result_render_generation:
                return
            if not card or card.parent() is None:
                return
            card.setGraphicsEffect(None)
            card.show()
            self.schedule_visible_cover_requests()
        except RuntimeError:
            pass

    def on_album_cover_painted(self, label: LazyCoverLabel):
        """Start one background task when an album card is first painted."""
        try:
            album_id = str(getattr(label, "_album_id", ""))
            if not album_id or not self.is_live_cover_target(album_id, label):
                return
            # A recycled card can receive a queued paint event from its old
            # page. Only the label belonging to the currently active card is
            # allowed to start a network request.
            if self.current_result_cover_target(album_id) is not label:
                return
            album = self.albums.get(album_id) or self.detail_cache.get(album_id)
            if album is None:
                return
            if getattr(label, "_defer_cover_request", False):
                # Appended cards reserve their final geometry first. Deferring
                # their cover work lets Qt finish the scroll/layout pass before
                # the bounded cover queue is replenished.
                self.result_cover_labels[album_id] = label
                if not self.append_render_pending:
                    self.schedule_visible_cover_requests()
                return
            self.result_cover_requested.add(album_id)
            self.request_cover(album, label)
        except RuntimeError:
            pass

    def schedule_visible_cover_requests(self):
        # Kept as a compatibility hook for restored views. New album cards use
        # LazyCoverLabel.paintEvent, matching JMComic-qt exactly.
        if not hasattr(self, "result_scroll") or not getattr(self, "result_cover_labels", None):
            return
        if self.result_cover_lazy_timer and self.result_cover_lazy_timer.isActive():
            return
        self.result_cover_lazy_timer = QTimer(self)
        self.result_cover_lazy_timer.setSingleShot(True)
        self.result_cover_lazy_timer.timeout.connect(self.request_visible_result_covers)
        self.result_cover_lazy_timer.start(RESULT_COVER_REQUEST_INTERVAL_MS)

    def request_visible_result_covers(self):
        if not hasattr(self, "result_scroll"):
            return
        scrollbar = self.result_scroll.verticalScrollBar()
        is_smooth_scrolling = getattr(scrollbar, "is_smooth_scrolling", None)
        if callable(is_smooth_scrolling) and is_smooth_scrolling():
            # Do not begin image work while the smooth scrollbar is moving.
            # ``movement_finished`` schedules the next visible cover pass.
            return
        if len(self.cover_workers) >= COVER_REQUEST_CONCURRENCY:
            return
        viewport = self.result_scroll.viewport()
        viewport_rect = viewport.rect()
        expanded_top = viewport_rect.top()
        expanded_bottom = viewport_rect.bottom()
        for album_id, label in list(self.result_cover_labels.items()):
            if album_id in self.result_cover_requested:
                continue
            album = self.albums.get(album_id) or self.detail_cache.get(album_id)
            if album is None:
                continue
            try:
                if label is None or label.parent() is None:
                    self.result_cover_labels.pop(album_id, None)
                    continue
                top_left = label.mapTo(viewport, QPoint(0, 0))
                bottom = top_left.y() + label.height()
                if bottom < expanded_top or top_left.y() > expanded_bottom:
                    continue
            except RuntimeError:
                self.result_cover_labels.pop(album_id, None)
                continue
            self.result_cover_requested.add(album_id)
            self.request_cover(album, label)
            self.result_cover_labels.pop(album_id, None)
            # One request per turn keeps cover decode and widget repaint from
            # competing with wheel input. The next pass is queued below.
            self.schedule_visible_cover_requests()
            break

    def on_result_scroll_value_changed(self, value: int):
        if not hasattr(self, "result_scroll"):
            return
        bar = self.result_scroll.verticalScrollBar()
        source = self.sender()
        if source is not None and source is not bar:
            return
        self.schedule_visible_cover_requests()
        if hasattr(bar, "movement_finished"):
            return
        if value >= max(0, bar.maximum() - max(96, self.result_scroll.viewport().height() // 5)):
            start, end = self.current_page_bounds()
            if self.result_render_limit < end - start:
                self.load_next_result_card_batch()
                return
            self.maybe_auto_load_next_source_page()

    def on_result_scroll_motion_finished(self):
        """JMComic-qt loads another page after smooth motion reaches the end."""
        if not hasattr(self, "result_scroll"):
            return
        bar = self.result_scroll.verticalScrollBar()
        source = self.sender()
        if source is not None and source is not bar:
            return
        self.schedule_visible_cover_requests()
        if bar.sliderPosition() < bar.maximum():
            return
        start, end = self.current_page_bounds()
        if self.result_render_limit < end - start:
            self.load_next_result_card_batch()
            return
        self.maybe_auto_load_next_source_page()

    def maybe_auto_load_if_result_viewport_not_full(self):
        if not hasattr(self, "result_scroll") or not self.results_revealed:
            return
        bar = self.result_scroll.verticalScrollBar()
        if bar.maximum() <= 0:
            self.maybe_auto_load_next_source_page()

    def load_next_result_card_batch(self):
        start, end = self.current_page_bounds()
        previous_limit = self.result_render_limit
        self.result_render_limit = min(end - start, previous_limit + RESULT_RENDER_BATCH_SIZE)
        if self.result_render_limit <= previous_limit:
            return
        if getattr(self, "result_list_mode", False):
            for index in range(start + previous_limit, start + self.result_render_limit):
                if index >= len(self.result_albums):
                    break
                album = self.result_albums[index]
                if album is not None and album.album_id not in self.card_by_id:
                    self.append_visible_album_card(album, animate=False, update_controls=False)
            self.update_page_controls()
            self.schedule_visible_cover_requests()
            return
        columns = self.result_columns()
        visible_index = len(self.card_by_id)
        for index in range(start + previous_limit, start + self.result_render_limit):
            if index >= len(self.result_albums):
                break
            album = self.result_albums[index]
            if album is None or album.album_id in self.card_by_id:
                continue
            card = self.create_album_card(album)
            self.result_grid.addWidget(card, visible_index // columns, visible_index % columns)
            self.card_by_id[album.album_id] = card
            card.show()
            visible_index += 1
        for col in range(columns):
            self.result_grid.setColumnStretch(col, 1)
        self.schedule_visible_cover_requests()

    def clear_result_grid(self):
        self.result_render_generation += 1
        self.clear_card_click_timers()
        self.card_by_id.clear()
        self.checkmark_by_id.clear()
        self.result_cover_labels.clear()
        self.result_cover_requested.clear()
        if getattr(self, "result_list_mode", False):
            clear_empty_state = getattr(
                self.result_scroll, "clear_empty_state_widget", None
            )
            if callable(clear_empty_state):
                clear_empty_state()
            for index in range(self.result_scroll.count()):
                item = self.result_scroll.item(index)
                widget = self.result_scroll.itemWidget(item)
                if widget is not None:
                    self.stop_widget_animations(widget)
                    for label in widget.findChildren(QLabel):
                        self.stop_label_movie(label)
            self.result_scroll.clear()
            self.album_card_pool.clear()
            return
        # A stretched trailing row expands to a large blank area in the
        # scroll view. Reset every existing row before releasing the cards.
        for row in range(self.result_grid.rowCount()):
            self.result_grid.setRowStretch(row, 0)
        for col in range(8):
            self.result_grid.setColumnStretch(col, 0)
        while self.result_grid.count():
            item = self.result_grid.takeAt(0)
            widget = item.widget()
            if widget:
                self.stop_widget_animations(widget)
                if widget.objectName() == "albumCard":
                    for label in widget.findChildren(QLabel):
                        self.stop_label_movie(label)
                    widget.hide()
                    self.album_card_pool.append(widget)
                else:
                    widget.deleteLater()

    def clear_card_click_timers(self):
        for timer in list(self.card_click_timers.values()):
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass
        self.card_click_timers.clear()

    def stop_widget_animations(self, widget: QWidget):
        for attr in ("_fade_animation", "_selection_animation", "_hover_pos_animation", "_hover_shadow_animation"):
            animation = getattr(widget, attr, None)
            try:
                if animation:
                    animation.stop()
            except RuntimeError:
                pass
        for child in widget.findChildren(QWidget):
            for attr in ("_fade_animation", "_selection_animation"):
                animation = getattr(child, attr, None)
                try:
                    if animation:
                        animation.stop()
                except RuntimeError:
                    pass

    def create_empty_album_card(self) -> QFrame:
        """Create a reusable card once instead of parsing album_card.ui per item."""
        card = QFrame(self.result_scroll.viewport() if getattr(self, "result_list_mode", False) else self.result_grid_widget)
        card.setObjectName("albumCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        cover = LazyCoverLabel(card)
        cover.setObjectName("albumCover")
        cover.load_requested.connect(self.on_album_cover_painted)
        layout.addWidget(cover)
        title = QLabel(card)
        title.setObjectName("albumTitle")
        layout.addWidget(title)
        tags_layout = QHBoxLayout()
        tags_layout.setObjectName("albumTagsLayout")
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(4)
        layout.addLayout(tags_layout)

        checkmark = QLabel("✓", card)
        checkmark.setObjectName("albumCheckmark")
        meta = QLabel(card)
        meta.setObjectName("albumMeta")
        return card

    def create_album_card(
        self,
        album: AlbumMeta,
        show_loading: bool = False,
        defer_cover: bool = False,
    ) -> QFrame:
        card = (
            self.create_empty_album_card()
            if getattr(self, "result_list_mode", False)
            else (self.album_card_pool.pop() if self.album_card_pool else self.create_empty_album_card())
        )
        card.setObjectName("albumCard")
        card.setParent(self.result_scroll.viewport() if getattr(self, "result_list_mode", False) else self.result_grid_widget)
        card_width = self.result_card_width()
        list_mode = getattr(self, "result_list_mode", False)
        cover_width = (
            max(150, card_width - 4)
            if list_mode
            else min(250, max(150, card_width - 4))
        )
        # Fill the retained list card like the weekly view. Keeping the old
        # 250 px cap left a blank strip at the bottom of every home-feed row.
        cover_height = int(cover_width * 340 / 250)
        card_height = FEED_CARD_HEIGHT if list_mode else cover_height + 60
        card.setFixedSize(card_width, card_height)
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet(self.album_card_style(album.album_id in self.selected_album_ids))
        card._album_id = album.album_id
        if not getattr(card, "_album_handlers_connected", False):
            card.installEventFilter(self)
            card.mousePressEvent = lambda event, card=card: self.handle_album_card_mouse_press(
                event,
                getattr(card, "_album_id", ""),
            )
            card.mouseDoubleClickEvent = lambda event: event.accept()
            card.setContextMenuPolicy(Qt.NoContextMenu)
            card._album_handlers_connected = True

        checkmark = card.findChild(QLabel, "albumCheckmark")
        meta = card.findChild(QLabel, "albumMeta")
        cover = card.findChild(QLabel, "albumCover")
        title = card.findChild(QLabel, "albumTitle")
        tags_layout = card.findChild(QHBoxLayout, "albumTagsLayout")
        required = [checkmark, meta, cover, title, tags_layout]
        if any(widget is None for widget in required):
            raise RuntimeError("album_card.ui is missing required controls")

        checkmark.setAlignment(Qt.AlignCenter)
        checkmark.setFixedSize(24, 24)
        checkmark.setMinimumSize(24, 24)
        checkmark.setMaximumSize(24, 24)
        checkmark.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        checkmark.setStyleSheet(
            "background:#1976d2;color:white;border-radius:12px;font-weight:900;font-size:16px;"
        )
        checkmark.setVisible(album.album_id in self.selected_album_ids)
        self.checkmark_by_id[album.album_id] = checkmark
        meta.setText(f"❤ {album.likes}   {album.page_count}")
        meta.setStyleSheet(
            f"color:{'#aeb6c2' if bool(getattr(self, 'theme_dark', False)) else '#475569'};"
            "font-size:11px;"
        )
        meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        meta.hide()
        checkmark.move(12, 12)

        cover.setFixedSize(cover_width, cover_height)
        cover.setAlignment(Qt.AlignCenter)
        cover.setScaledContents(False)
        cover.setContentsMargins(0, 0, 0, 0)
        cover.setStyleSheet(
            "background:transparent;border:0;"
            f"color:{'#aeb6c2' if bool(getattr(self, 'theme_dark', False)) else '#8491a5'};"
        )
        cover.setPixmap(QPixmap())
        cover._defer_cover_request = defer_cover
        # The card can be rebuilt while its lazy cover task is still running.
        # Keep the identity on the new label so the completion handler can
        # update the visible replacement instead of only the retired label.
        cover.bind_album(album.album_id, self.result_render_generation)
        if show_loading:
            self.apply_loading_movie(cover, QSize(min(cover_width, 120), min(cover_height, 95)))
        else:
            cover.setText("加载中")
        checkmark.raise_()

        title.setWordWrap(True)
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        title.setFixedHeight(34)
        title.setToolTip(album.title)
        title.setStyleSheet(
            "font-weight:700;"
            f"color:{'#e5e7eb' if bool(getattr(self, 'theme_dark', False)) else '#1f2937'};"
            "font-size:10px;"
        )
        title_width = max(60, cover_width - 8)
        title.setText(self.elided_album_title(album.title or "-", title.font(), title_width, 2))

        while tags_layout.count():
            item = tags_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for tag in self.album_card_tags(album):
            badge = self.create_tag_badge(tag, compact=True)
            badge.setToolTip("  ".join(album.tags))
            tags_layout.addWidget(badge)
        tags_layout.addStretch()
        return card

    @staticmethod
    def album_card_tags(album: AlbumMeta) -> List[str]:
        values = []
        seen = set()
        for tag in album.tags or []:
            value = str(tag).strip()
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        return values[:3]

    @staticmethod
    def elided_album_title(text: str, font, width: int, lines: int = 2) -> str:
        metrics = QFontMetrics(font)
        source = str(text or "-")
        if lines <= 1:
            return metrics.elidedText(source, Qt.ElideRight, width)
        result = []
        start = 0
        for line in range(lines):
            remaining = source[start:]
            if not remaining:
                break
            if line == lines - 1:
                result.append(metrics.elidedText(remaining, Qt.ElideRight, width))
                break
            end = start + 1
            last_fit = end
            while end <= len(source) and metrics.horizontalAdvance(source[start:end]) <= width:
                last_fit = end
                end += 1
            if last_fit <= start:
                last_fit = start + 1
            result.append(source[start:last_fit])
            start = last_fit
        return "\n".join(result)

    def result_columns(self) -> int:
        if getattr(self, "result_list_mode", False):
            viewport_width = max(self.result_scroll.viewport().width(), self.result_scroll.width())
            return max(1, viewport_width // 250)
        if not hasattr(self, "result_scroll") or getattr(self, "result_grid", None) is None:
            return 1
        viewport_width = max(self.result_scroll.viewport().width(), self.result_scroll.width())
        if viewport_width <= 0:
            return 1
        margins = self.result_grid.contentsMargins()
        spacing = max(0, self.result_grid.horizontalSpacing())
        usable_width = max(1, viewport_width - margins.left() - margins.right())
        target_card_width = 250
        return max(1, (usable_width + spacing) // (target_card_width + spacing))

    def result_page_size(self) -> int:
        return RESULT_PAGE_SIZE

    def result_card_width(self) -> int:
        if getattr(self, "result_list_mode", False):
            return FEED_CARD_WIDTH
        columns = self.result_columns()
        viewport_width = max(360, self.result_scroll.viewport().width(), self.result_scroll.width())
        margins = 12
        spacing = self.result_grid.horizontalSpacing() * max(0, columns - 1)
        return max(180, min(250, int((viewport_width - margins - spacing) / columns)))

    def album_card_style(self, selected: bool) -> str:
        dark = bool(getattr(self, "theme_dark", False))
        background = ("#3b2a20" if dark else "#f8fbff") if selected else "transparent"
        hover = "#292d34" if dark else "#f8fbff"
        return (
            f"QFrame#albumCard {{ background:{background}; border:0; border-radius:0; }} "
            f"QFrame#albumCard[hovered=\"true\"] {{ background:{hover}; border:0; }}"
        )

    def apply_album_card_theme(self, album_id: str, card: QFrame) -> None:
        """Recolor one live feed card without touching its geometry."""
        dark = bool(getattr(self, "theme_dark", False))
        try:
            card.setStyleSheet(
                self.album_card_style(album_id in self.selected_album_ids)
            )
            title = card.findChild(QLabel, "albumTitle")
            if title is not None:
                title.setStyleSheet(
                    "font-weight:700;"
                    f"color:{'#e5e7eb' if dark else '#1f2937'};font-size:10px;"
                )
            cover = card.findChild(QLabel, "albumCover")
            if cover is not None:
                cover.setStyleSheet(
                    "background:transparent;border:0;"
                    f"color:{'#aeb6c2' if dark else '#8491a5'};"
                )
            for badge in card.findChildren(QLabel, "tagBadge"):
                compact = bool(badge.property("compactBadge"))
                badge.setStyleSheet(self.tag_badge_style(compact))
        except RuntimeError:
            pass

    def refresh_album_card_theme(self) -> None:
        """Recolor live feed cards; callers may batch through the single-card API."""
        for album_id, card in list(getattr(self, "card_by_id", {}).items()):
            self.apply_album_card_theme(album_id, card)

    def handle_album_card_mouse_press(self, event, album_id: str):
        if event.button() == Qt.LeftButton:
            self.open_album_detail(album_id)
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self.show_album_context_menu(album_id, event.globalPos())
            event.accept()

    def schedule_album_single_click(self, album_id: str):
        timer = self.card_click_timers.get(album_id)
        if timer and timer.isActive():
            timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda album_id=album_id: self.open_album_detail(album_id))
        self.card_click_timers[album_id] = timer
        timer.start(120)

    def handle_album_double_click(self, album_id: str):
        timer = self.card_click_timers.get(album_id)
        if timer and timer.isActive():
            timer.stop()
        self.read_album_from_card(album_id)

    def show_album_context_menu(self, album_id: str, global_pos: QPoint):
        self.clear_album_selection()
        album = self.albums.get(album_id)
        if not album:
            return
        menu = QMenu(self)
        add_action = menu.addAction("加入下载")
        read_action = menu.addAction("阅读")
        detail_action = menu.addAction("查看详情")
        action = menu.exec(global_pos)
        if action == add_action:
            selected_before = len(self.queue)
            if self.add_album_to_queue(album_id, switch_page=False):
                self.show_floating_notice("已加入下载队列，后台开始下载")
                if len(self.queue) > selected_before:
                    self.start_download_queue()
        elif action == read_action:
            self.read_album_from_card(album_id)
        elif action == detail_action:
            self.open_album_detail(album_id)

    def read_album_from_card(self, album_id: str):
        album = self.albums.get(album_id)
        if album and album.chapters:
            self.open_reader_for_album(album)
            return
        self.load_chapters_then_read(album_id)

    def toggle_album_selection(self, album_id: str):
        checked = album_id not in self.selected_album_ids
        if checked:
            self.selected_album_ids.add(album_id)
        else:
            self.selected_album_ids.discard(album_id)
        self.update_card_selection(album_id, checked)

    def update_card_selection(self, album_id: str, checked: bool):
        card = self.card_by_id.get(album_id)
        if card:
            card.setStyleSheet(self.album_card_style(checked))
        checkmark = self.checkmark_by_id.get(album_id)
        if not checkmark:
            return
        animation = getattr(checkmark, "_selection_animation", None)
        try:
            if animation:
                animation.stop()
            checkmark.setGraphicsEffect(None)
            checkmark.setFixedSize(24, 24)
        except RuntimeError:
            return
        if checked:
            checkmark.setVisible(True)
        else:
            checkmark.setVisible(False)

    def clear_album_selection(self):
        if not self.selected_album_ids:
            return
        selected = list(self.selected_album_ids)
        self.selected_album_ids.clear()
        for album_id in selected:
            self.update_card_selection(album_id, False)

    def fade_widget(self, widget: QWidget, start: float, end: float, duration: int) -> QPropertyAnimation:
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.start()
        widget._selection_animation = animation
        return animation

    def open_album_detail(self, album_id: str):
        self.clear_album_selection()
        cached = self.detail_cache.get(album_id)
        if cached:
            self.albums[album_id] = copy.deepcopy(cached)
        if album_id not in self.albums:
            return
        if not self.breadcrumb_detail_parent:
            self.breadcrumb_detail_parent = self.current_breadcrumb_page_title()
            self.breadcrumb_detail_parent_index = (
                self.main_content_stack.currentIndex() if hasattr(self, "main_content_stack") else self.home_page_index()
            )
        self.current_album_id = album_id
        self.switch_page(self.detail_page_index(), preserve_path=True, breadcrumb_title="漫画详情")
        self.show_chapters(album_id)
        self.load_current_chapters(force_refresh=True)

    def current_page_bounds(self):
        # Home results are one append-only stream, like JMComic-qt's list.
        return 0, self.result_total_count

    def result_total_pages(self) -> int:
        return 1 if self.result_total_count > 0 else 0

    def change_result_page(self, direction: int):
        if direction > 0:
            self.maybe_auto_load_next_source_page()

    def request_next_result_source_page(self):
        self.maybe_auto_load_next_source_page()

    def finish_result_page_switch(self):
        self.result_page_switching = False
        self.update_page_controls()

    def update_page_controls(self):
        if hasattr(self, "page_label"):
            self.page_label.setText(f"\u5df2\u52a0\u8f7d {self.result_total_count} \u672c")
        if hasattr(self, "prev_page_btn"):
            self.prev_page_btn.setEnabled(False)
        if hasattr(self, "next_page_btn"):
            self.next_page_btn.setEnabled(False)

    def maybe_auto_load_next_source_page(self):
        if (
            not self.auto_load_has_more
            or self.auto_loading_next_page
            or self.append_render_pending
        ):
            return
        if split_ids(self.id_edit.text()):
            return
        if self.scrape_worker and self.scrape_worker.isRunning():
            return
        self.pending_result_page = 1
        self.auto_loading_next_page = True
        next_source_page = self.loaded_source_pages + 1
        self.log(f"已到当前最后一页，后台自动获取第 {next_source_page} 页漫画。")
        self.show_home_append_loading()
        self.start_scrape(source_page=next_source_page, append=True)

    def save_current_result_cache(self):
        if not self.current_result_cache_key:
            return
        # Result objects are owned by this window and already mirrored to
        # detail_cache as they arrive. Retaining their references avoids a
        # full-page deepcopy on every infinite-scroll completion.
        albums = [album for album in self.result_albums if album is not None]
        if not albums:
            return
        self.result_cache[self.current_result_cache_key] = albums

    def current_album(self) -> Optional[AlbumMeta]:
        if not self.current_album_id:
            return None
        return self.albums.get(self.current_album_id) or self.detail_cache.get(
            self.current_album_id
        )

    def open_detail_metadata_search(self, value: str):
        query = str(value or "").strip()
        if query and query != "-":
            self.open_search_results(query, preserve_path=True)

    def open_current_detail_author_search(self):
        album = self.current_album()
        if album is not None:
            self.open_detail_metadata_search(album.author)

    @staticmethod
    def album_has_detail_metadata(album: AlbumMeta) -> bool:
        return bool(
            album.tags
            or (album.author and album.author != "-")
            or (album.page_count and album.page_count != "-")
        )

    def show_chapters(self, album_id: str):
        album = self.albums.get(album_id) or self.detail_cache.get(album_id)
        if not album:
            return
        self.current_album_id = album_id
        if self.chapter_table:
            self.chapter_table.setRowCount(0)
        tags = "  ".join(f"#{tag}" for tag in album.tags[:30]) if album.tags else "-"
        self._set_label(self.detail_title_label, album.title or "-")
        self._set_label(self.detail_id_label, album.album_id)
        self._set_label(self.detail_author_label, album.author or "-")
        author = str(album.author or "").strip()
        if self.detail_author_label is not None:
            self.detail_author_label.setCursor(
                Qt.PointingHandCursor if author and author != "-" else Qt.ArrowCursor
            )
        self._set_label(self.detail_description_label, album.description or "暂无描述")
        self._set_label(self.detail_likes_label, str(album.likes or "-"))
        self._set_label(self.detail_views_label, str(album.views or "-"))
        self._set_label(self.detail_page_count_label, str(album.page_count or "-"))
        self.update_detail_favorite_button()
        self.render_detail_tags(album.tags)
        if getattr(self, "detail_read_button", None):
            self.detail_read_button.setText("观看第1章" if album.chapters else "加载中...")
            self.detail_read_button.setEnabled(bool(album.chapters))
        if getattr(self, "detail_comment_button", None):
            self.detail_comment_button.setText(f"评论 ({album.comment_count or '0'})")
        if self.tags_card:
            self.tags_card.setText(f"标签  {tags}")
        self.load_cover(album)
        if self.chapter_table:
            for chapter in album.chapters:
                row = self.chapter_table.rowCount()
                self.chapter_table.insertRow(row)
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                check_item.setCheckState(Qt.Checked)
                self.chapter_table.setItem(row, 0, check_item)
                for col, value in enumerate([chapter.index, chapter.title, chapter.url], start=1):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    self.chapter_table.setItem(row, col, item)
        self.render_detail_chapter_buttons(album)
        self.render_offline_chapters(album)
        if (
            hasattr(self, "main_content_stack")
            and self.main_content_stack.currentIndex() == self.detail_page_index()
        ):
            self.update_breadcrumb("漫画详情")

    def render_detail_tags(self, tags: List[str]):
        layout = getattr(self, "detail_tags_layout", None)
        if layout is None:
            return
        self.clear_profile_layout(layout)
        values = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        if not values:
            values = ["-"]
        for tag in values[:24]:
            badge = self.create_tag_badge(tag, compact=False)
            if tag != "-":
                badge.setCursor(Qt.PointingHandCursor)
                badge.setProperty("detailSearchKind", "tag")
                badge.setProperty("detailSearchValue", tag)
                badge.installEventFilter(self)
            layout.addWidget(badge)
        layout.invalidate()
        flow_widget = getattr(self, "detail_tags_flow_widget", None)
        if flow_widget is not None:
            flow_widget.updateGeometry()
            QTimer.singleShot(0, flow_widget.updateGeometry)
        tags_widget = flow_widget.parentWidget() if flow_widget is not None else None
        if tags_widget is not None:
            QTimer.singleShot(0, tags_widget.updateGeometry)
        QTimer.singleShot(0, self.sync_detail_content_width)

    def render_detail_chapter_buttons(self, album: AlbumMeta):
        layout = getattr(self, "detail_chapter_button_layout", None)
        container = getattr(self, "detail_chapter_buttons", None)
        if layout is None or container is None:
            return
        self.clear_profile_layout(layout)
        columns = max(1, min(7, max(1, container.width() // 118)))
        for index, chapter in enumerate(album.chapters):
            label = f"第{chapter.index}话"
            button = QPushButton(label, container)
            button.setFixedSize(110, 40)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(chapter.title)
            button.setStyleSheet(
                "QPushButton {background:#ffffff;color:#475569;border:1px solid #dbe3ed;"
                "border-radius:7px;padding:0 10px;font-size:14px;font-weight:800;}"
                "QPushButton:hover {background:#fff7ed;color:#c2410c;border-color:#fb923c;}"
                "QPushButton:pressed {background:#ffedd5;color:#9a3412;border-color:#f97316;}"
            )
            button.clicked.connect(lambda _=False, chapter=chapter, album=album: self.open_reader_for_album(album, chapter))
            layout.addWidget(button, index // columns, index % columns, Qt.AlignLeft | Qt.AlignTop)
        if not album.chapters:
            label = QLabel("正在加载章节...", container)
            label.setStyleSheet("color:#94a3b8;font-size:14px;")
            layout.addWidget(label, 0, 0)

    def render_offline_chapters(self, album: AlbumMeta):
        if not getattr(self, "offline_chapter_table", None):
            return
        self.detail_offline_chapters = []
        self.offline_chapter_table.setRowCount(0)
        for chapter in album.chapters:
            local_path = self.download_store.cached_chapter_path(chapter.chapter_id)
            if not local_path:
                continue
            try:
                image_count = len(collect_images(local_path))
            except OSError:
                image_count = 0
            if image_count <= 0:
                continue
            row = self.offline_chapter_table.rowCount()
            self.offline_chapter_table.insertRow(row)
            values = [chapter.index, chapter.title, f"{image_count} 页"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.offline_chapter_table.setItem(row, column, item)
            self.detail_offline_chapters.append(chapter)
        if self.detail_offline_hint_label:
            if self.detail_offline_chapters:
                self.detail_offline_hint_label.setText(
                    f"可离线阅读已下载的章节：{len(self.detail_offline_chapters)} 个"
                )
            else:
                self.detail_offline_hint_label.setText("可离线阅读已下载的章节：暂无本地缓存")
        self.adjust_offline_chapter_table_height()

    def adjust_offline_chapter_table_height(self):
        if not getattr(self, "offline_chapter_table", None):
            return
        rows = self.offline_chapter_table.rowCount()
        header = self.offline_chapter_table.horizontalHeader().height()
        row_height = self.offline_chapter_table.verticalHeader().defaultSectionSize()
        height = header + max(1, rows) * row_height + 8
        self.offline_chapter_table.setFixedHeight(max(96, min(520, height)))

    def clear_current_cover_cache(self):
        album = self.current_album()
        if not album:
            self.show_toast("请先选择一个漫画")
            return
        answer = QMessageBox.question(
            self,
            "清理缓存",
            f"确定清除《{album.title}》的封面缓存吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.cover_cache.pop(album.album_id, None)
        self.cover_cache_refresh_attempted.discard(album.album_id)
        try:
            for cache_path in self.cover_cache_paths(album.album_id):
                cache_path.unlink(missing_ok=True)
        except OSError as exc:
            self.show_toast(f"封面缓存清理失败：{exc}")
            return
        self.show_toast("已清除封面缓存")
        self.load_cover(album)

    def load_cover(self, album: AlbumMeta):
        self.cover_label.setPixmap(QPixmap())
        self.apply_detail_loading_movie(self.cover_label)
        self.request_cover(album, self.cover_label)

    def request_cover(
        self, album: AlbumMeta, label: QLabel, *, priority: bool = False
    ):
        label._album_id = album.album_id
        if not getattr(label, "_persistent_cover", False):
            label._result_generation = self.result_render_generation
        if self._test_mode:
            self.stop_label_movie(label)
            label.setText("封面")
            return
        seed_url = album.cover_url or self.default_cover_url(album.album_id)
        if not seed_url:
            self.stop_label_movie(label)
            label.setText("暂无封面")
            self.log(f"封面跳过：{album.title} 没有可用封面地址。")
            return
        if album.album_id in self.cover_cache:
            cached_pixmap = self.cover_cache[album.album_id]
            if not self.cover_pixmap_needs_refresh(album.album_id, cached_pixmap, label):
                self.stop_label_movie(label)
                self.set_cover_on_label(label, cached_pixmap)
                self.log(f"封面命中缓存：{album.title}（{album.album_id}）")
                return
            label._fallback_cover_pixmap = QPixmap(cached_pixmap)
            self.log(f"封面缓存尺寸偏小，尝试刷新高清封面：{album.title}（{album.album_id}）")
        self.cover_targets.setdefault(album.album_id, []).append(label)
        if album.album_id in self.cover_pending:
            if priority:
                self.promote_queued_cover_request(album.album_id)
            self.log(f"封面加入等待队列：{album.title}（{album.album_id}）")
            return
        self.cover_pending.add(album.album_id)
        urls = self.cover_url_candidates(seed_url, album.album_id)
        self.cover_fallback_urls[album.album_id] = urls
        self.log(f"开始加载封面：{album.title}（{album.album_id}），候选地址 {len(urls)} 个。")
        # A cached landscape/square image is the legacy cropped album cover.
        # Bypass the disk cache so the canonical 3:4 image can replace it.
        self.start_cover_request(
            album.album_id,
            urls,
            use_disk_cache=album.album_id not in self.cover_cache_refresh_attempted,
            priority=priority,
        )

    def promote_queued_cover_request(self, album_id: str) -> None:
        """Move a visible high-priority cover ahead of background feed covers."""
        for index, request in enumerate(self.cover_request_queue):
            if request[0] != album_id:
                continue
            if index:
                self.cover_request_queue.insert(0, self.cover_request_queue.pop(index))
            return

    def cover_cache_paths(self, album_id: str) -> List[Path]:
        safe_id = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(album_id or "unknown")).strip("._") or "unknown"
        root = cover_cache_dir()
        candidates = [
            path for path in root.glob(f"{safe_id}.*")
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        ]
        preference = {".webp": 0, ".png": 1, ".jpg": 2, ".jpeg": 3, ".gif": 4}
        return sorted(candidates, key=lambda path: preference.get(path.suffix.lower(), 9))

    def cover_cache_path(self, album_id: str, suffix: str = ".jpg") -> Path:
        safe_id = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(album_id or "unknown")).strip("._") or "unknown"
        extension = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
        return cover_cache_dir() / f"{safe_id}{extension}"

    def cover_pixmap_needs_refresh(self, album_id: str, pixmap: QPixmap, label: QLabel) -> bool:
        if album_id in self.cover_cache_refresh_attempted:
            return False
        if pixmap.isNull():
            return True
        # Album covers are served by JM as portrait 3:4 images.  Older cache
        # entries may contain the cropped plain .jpg variant instead.
        if pixmap.height() / max(1, pixmap.width()) < 1.2:
            self.cover_cache_refresh_attempted.add(album_id)
            return True
        target = label.size()
        if target.isEmpty():
            return False
        ratio = max(1.0, label.devicePixelRatioF())
        min_width = int(target.width() * ratio * 0.9)
        min_height = int(target.height() * ratio * 0.9)
        if pixmap.width() >= min_width and pixmap.height() >= min_height:
            return False
        self.cover_cache_refresh_attempted.add(album_id)
        return True

    @staticmethod
    def cover_cache_suffix(data: bytes) -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return ".webp"
        if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
            return ".gif"
        return ".jpg"

    def write_cover_disk_cache(self, album_id: str, data: bytes):
        path = self.cover_cache_path(album_id, self.cover_cache_suffix(data))
        payload = bytes(data)

        def write_cache():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                for previous_path in self.cover_cache_paths(album_id):
                    if previous_path != path:
                        previous_path.unlink(missing_ok=True)
            except Exception as exc:
                self.async_log.emit(f"封面文件缓存写入失败 {album_id}: {exc}")

        if not self._cover_disk_pool_closed:
            self.cover_disk_write_pool.submit(write_cache)

    def default_cover_url(self, album_id: str) -> str:
        match = re.search(r"(\d+)", album_id or "")
        if not match or not self.cover_domain_pool:
            return ""
        return https_url(self.cover_domain_pool[0], album_cover_path(match.group(1)))

    def cover_url_candidates(self, url: str, album_id: str = "") -> List[str]:
        match = re.search(rf"{re.escape(MEDIA_ALBUMS_PATH)}/(\d+)(?:_3x4)?\.jpg", url)
        if not match:
            match = re.search(r"(\d+)", album_id or "")
        candidates = []
        if match:
            numeric_id = match.group(1)
            original_domain = urlparse(url).netloc
            domains = self.sorted_cover_domains(original_domain)
            # The 3:4 endpoint is the actual album artwork.  Keeping every
            # domain's portrait URL before a legacy .jpg fallback avoids
            # spending two network timeouts on the same slow CDN.  This makes
            # each CoverTask behave like JMComic-qt's single image task while
            # retaining a small, fast failover path.
            for domain in domains:
                candidates.append(https_url(domain, album_cover_path(numeric_id)))
            for domain in domains:
                candidates.append(https_url(domain, album_cover_path(numeric_id, portrait=False)))
        elif url:
            candidates.append(url)

        deduped = []
        seen = set()
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped

    def sorted_cover_domains(self, preferred: str = "") -> List[str]:
        domains = dedupe_domains(([preferred] if preferred else []) + self.cover_domain_pool + list(IMAGE_DOMAINS))
        return sorted(domains, key=lambda domain: (self.cover_domain_failures.get(domain, 0), domains.index(domain)))

    def start_cover_request(
        self,
        album_id: str,
        urls: List[str],
        use_disk_cache: bool = True,
        *,
        priority: bool = False,
    ):
        if not urls:
            self.on_cover_failed(album_id, "没有可用封面地址", [])
            return
        request = (album_id, list(urls), use_disk_cache)
        if priority:
            self.cover_request_queue.insert(0, request)
        else:
            self.cover_request_queue.append(request)
        self.drain_cover_request_queue()

    def drain_cover_request_queue(self):
        while self.cover_request_queue and len(self.cover_workers) < COVER_REQUEST_CONCURRENCY:
            album_id, urls, use_disk_cache = self.cover_request_queue.pop(0)
            if album_id not in self.cover_pending:
                continue
            self.start_cover_request_now(album_id, urls, use_disk_cache)

    def start_cover_request_now(self, album_id: str, urls: List[str], use_disk_cache: bool):
        referer_domain = self.api_domain_pool[0] if self.api_domain_pool else API_DOMAINS[0]
        worker = CoverTask(
            album_id,
            urls,
            proxy=self.effective_proxy(),
            referer_domain=referer_domain,
            user_agent=self.network_config().user_agent,
            use_disk_cache=use_disk_cache,
            generation=self.result_render_generation,
            doh_enabled=self.doh_enabled_box.isChecked(),
            doh_url=self.doh_url_edit.text().strip() or DOH_URL,
            parent=self,
        )
        self.cover_workers[album_id] = worker
        worker.succeeded.connect(self.on_cover_task_loaded)
        worker.failed_with_context.connect(self.on_cover_task_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def on_cover_task_loaded(self, result: Dict):
        album_id = str(result.get("book_id") or "")
        if not album_id:
            return
        for failed_url in result.get("failed_urls") or []:
            self.mark_cover_domain_failed(str(failed_url))
        pixmap = QPixmap.fromImage(result.get("image"))
        if pixmap.isNull():
            self.on_cover_failed(album_id, "封面数据无法转换为 Pixmap", [])
            self.release_cover_worker(album_id)
            return
        targets = self.cover_targets.pop(album_id, [])
        current_target = self.current_result_cover_target(album_id)
        if current_target is not None and current_target not in targets:
            targets.append(current_target)
        self.cover_pending.discard(album_id)
        self.cover_fallback_urls.pop(album_id, None)
        self.cover_cache[album_id] = pixmap
        self.mark_cover_domain_success(str(result.get("source_url") or ""))
        self.log(f"封面加载完成：{album_id}")
        for label in targets:
            if self.is_live_cover_target(album_id, label):
                self.set_cover_on_label(label, pixmap)

        # ``succeeded`` is delivered to this MainWindow on the GUI thread.
        # Releasing here, rather than through a finished->lambda connection,
        # ensures that the next child QThread is also constructed on the GUI
        # thread. Without this, exactly COVER_REQUEST_CONCURRENCY covers load
        # and the remainder of the queue stalls.
        self.release_cover_worker(album_id)

    def on_cover_task_failed(self, result: Dict):
        album_id = str(result.get("book_id") or "")
        if not album_id:
            return
        self.on_cover_failed(
            album_id,
            str(result.get("message") or "封面请求失败"),
            list(result.get("failed_urls") or []),
        )
        self.release_cover_worker(album_id)

    def release_cover_worker(self, album_id: str):
        self.cover_workers.pop(str(album_id or ""), None)
        self.drain_cover_request_queue()
        if getattr(self, "result_list_mode", False):
            self.schedule_visible_cover_requests()

    def on_cover_loaded(self, album_id: str, data: bytes, url: str, failed_urls: List[str]):
        for failed_url in failed_urls:
            self.mark_cover_domain_failed(failed_url)
        worker = CoverDecodeWorker(album_id, data, url, failed_urls, self)
        self.cover_decode_workers[album_id] = worker
        worker.decoded.connect(self.on_cover_decoded)
        worker.failed.connect(self.on_cover_decode_failed)
        worker.finished.connect(lambda album_id=album_id: self.cover_decode_workers.pop(album_id, None))
        worker.start()

    def on_cover_decoded(self, album_id: str, image: QImage, data: bytes, url: str, failed_urls: List[str]):
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self.on_cover_decode_failed(album_id, f"封面数据无法转换为 Pixmap：{len(data)} bytes", url, failed_urls)
            return
        if (
            url.startswith("cache://")
            and album_id not in self.cover_cache_refresh_attempted
            and pixmap.height() / max(1, pixmap.width()) < 1.2
        ):
            # Do not briefly render a legacy cropped disk cache on startup.
            # Keep it only as a failure fallback while the portrait artwork is
            # fetched and then overwrite this cache after a successful fetch.
            self.cover_cache_refresh_attempted.add(album_id)
            self.cover_cache[album_id] = pixmap
            for label in self.cover_targets.get(album_id, []):
                label._fallback_cover_pixmap = QPixmap(pixmap)
            urls = self.cover_fallback_urls.get(album_id, [])
            if urls:
                self.log(f"本地封面缓存为裁剪版，刷新完整封面：{album_id}")
                self.start_cover_request(album_id, urls, use_disk_cache=False)
                return
        targets = self.cover_targets.pop(album_id, [])
        self.cover_pending.discard(album_id)
        self.cover_fallback_urls.pop(album_id, None)
        self.cover_cache[album_id] = pixmap
        if not url.startswith("cache://"):
            self.write_cover_disk_cache(album_id, data)
            self.mark_cover_domain_success(url)
        self.log(f"封面加载完成：{album_id}")
        for label in targets:
            if self.is_live_cover_target(album_id, label):
                self.set_cover_on_label(label, pixmap)

    def on_cover_decode_failed(self, album_id: str, message: str, url: str, failed_urls: List[str]):
        if url.startswith("cache://"):
            self.log(f"本地封面缓存已失效，改为远程获取：{album_id}")
            urls = self.cover_fallback_urls.get(album_id, [])
            if urls:
                self.start_cover_request(album_id, urls, use_disk_cache=False)
                return
        self.mark_cover_domain_failed(url)
        self.on_cover_failed(album_id, message, failed_urls + [url])

    def on_cover_failed(self, album_id: str, message: str, failed_urls: List[str]):
        for failed_url in failed_urls:
            self.mark_cover_domain_failed(failed_url)
        self.schedule_local_cache_save()
        targets = self.cover_targets.pop(album_id, [])
        current_target = self.current_result_cover_target(album_id)
        if current_target is not None and current_target not in targets:
            targets.append(current_target)
        self.cover_pending.discard(album_id)
        self.cover_fallback_urls.pop(album_id, None)
        self.log(f"封面加载失败 {album_id}：{message}")
        for label in targets:
            try:
                if not self.is_live_cover_target(album_id, label):
                    continue
                history_record = getattr(label, "_history_record", None)
                if isinstance(history_record, dict) and self.set_history_local_cover(history_record, label):
                    continue
                fallback_pixmap = getattr(label, "_fallback_cover_pixmap", None)
                if isinstance(fallback_pixmap, QPixmap) and not fallback_pixmap.isNull():
                    self.stop_label_movie(label)
                    self.set_cover_on_label(label, fallback_pixmap)
                    continue
                self.stop_label_movie(label)
                retry_count = int(getattr(label, "_cover_retry_count", 0))
                album = self.albums.get(album_id)
                if album is not None and retry_count < 1:
                    label._cover_retry_count = retry_count + 1
                    label.setText("正在重试封面")
                    QTimer.singleShot(
                        700,
                        lambda album=album, label=label, album_id=album_id: (
                            self.request_cover(album, label)
                            if self.is_live_cover_target(album_id, label)
                            else None
                        ),
                    )
                    continue
                label.setText("封面加载失败")
            except RuntimeError:
                pass

    def is_live_cover_target(self, album_id: str, label: QLabel) -> bool:
        try:
            if label is None or label.parent() is None:
                return False
            if getattr(label, "_album_id", "") != album_id:
                return False
            if getattr(label, "_persistent_cover", False):
                return True
            generation = getattr(label, "_result_generation", self.result_render_generation)
            if generation != self.result_render_generation and label is not getattr(self, "cover_label", None):
                return False
            return True
        except RuntimeError:
            return False

    def current_result_cover_target(self, album_id: str) -> Optional[QLabel]:
        """Return the cover label belonging to the card currently on screen.

        Homepage cards are deliberately recycled when a page is appended or a
        section is changed. A background task may therefore complete after the
        label captured at request time has been retired. Looking up the card by
        id at completion time prevents a successful fetch from being discarded.
        """
        try:
            card = self.card_by_id.get(album_id)
            if card is None or card.parent() is None:
                return None
            label = card.findChild(QLabel, "albumCover")
            if label is None or label.parent() is None:
                return None
            if getattr(card, "_album_id", "") != album_id:
                return None
            label._album_id = album_id
            label._result_generation = self.result_render_generation
            return label
        except RuntimeError:
            return None

    def mark_cover_domain_failed(self, url: str):
        domain = urlparse(url).netloc
        if not domain:
            return
        self.cover_domain_failures[domain] = self.cover_domain_failures.get(domain, 0) + 1
        self.cover_domain_pool = dedupe_domains(self.cover_domain_pool + [domain])

    def mark_cover_domain_success(self, url: str):
        domain = urlparse(url).netloc
        if not domain:
            return
        self.cover_domain_failures.pop(domain, None)
        self.cover_domain_pool = dedupe_domains([domain] + self.cover_domain_pool)
        self.schedule_local_cache_save()

    @staticmethod
    def set_cover_on_label(label: QLabel, pixmap: QPixmap):
        try:
            MainWindow.stop_label_movie(label)
            target = label.contentsRect().size()
            if target.isEmpty() or pixmap.isNull():
                return
            label.setScaledContents(False)
            # QLabel dimensions are logical pixels.  Scaling to them directly
            # makes Qt enlarge the already-downscaled image on high-DPI Windows
            # displays.  Match JMComic-qt by preparing a device-pixel pixmap.
            pixel_ratio = max(1.0, label.devicePixelRatioF())
            pixel_target = QSize(
                max(1, round(target.width() * pixel_ratio)),
                max(1, round(target.height() * pixel_ratio)),
            )
            scaled = pixmap.scaled(
                pixel_target,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(pixel_ratio)
            label.setAlignment(Qt.AlignCenter)
            label.setPixmap(scaled)
            label.setText("")
        except RuntimeError:
            pass

    def open_reader_for_current(self):
        album = self.current_album()
        if not album:
            self.show_toast("请先选择一个漫画")
            return
        if not album.chapters or not self.chapter_table:
            self.show_toast("当前漫画没有章节信息")
            return

        chapter = None
        for row in range(self.chapter_table.rowCount()):
            item = self.chapter_table.item(row, 0)
            if item and item.checkState() == Qt.Checked and row < len(album.chapters):
                chapter = album.chapters[row]
                break
        if chapter is None:
            chapter = album.chapters[0]

        reader = HdMangaReaderWindow(f"漫画阅读 - {album.title}")
        self.reader_dialogs.append(reader)
        self.bind_reader_download_action(reader, album)
        reader.destroyed.connect(lambda _=None, dialog=reader: self.forget_reader_dialog(dialog))
        reader.set_restore_page(self.reader_controller.restore_page(album, chapter.chapter_id))
        reader.start_online_chapter(album, chapter, self.download_config(), self.log)
        reader.showMaximized()
        reader.raise_()
        reader.activateWindow()

    def open_first_offline_chapter(self):
        self.open_offline_chapter_row(0)

    def open_offline_chapter_row(self, row: int, _column: int = 0):
        if row < 0 or row >= len(getattr(self, "detail_offline_chapters", [])):
            self.show_toast("当前漫画没有可离线阅读的章节")
            return
        album = self.current_album()
        chapter = self.detail_offline_chapters[row]
        if not album:
            return
        local_path = self.download_store.cached_chapter_path(chapter.chapter_id)
        images = collect_images(local_path) if local_path else []
        if not images:
            self.render_offline_chapters(album)
            self.show_toast("该章节的本地缓存已失效")
            return
        reader = HdMangaReaderWindow(f"离线阅读 - {album.title}")
        self.local_reader_dialogs.append(reader)
        reader.destroyed.connect(lambda _=None, dialog=reader: self.forget_local_reader_dialog(dialog))
        reader.mark_downloaded_action()
        reader.start_decode_image_paths(images)
        reader.showMaximized()
        reader.raise_()
        reader.activateWindow()

    def open_reader_for_album(self, album: AlbumMeta, chapter: Optional[ChapterMeta] = None):
        if not album.chapters:
            self.load_chapters_then_read(album.album_id)
            return
        chapter = chapter or album.chapters[0]
        reader = HdMangaReaderWindow(f"漫画阅读 - {album.title}")
        self.reader_dialogs.append(reader)
        self.bind_reader_download_action(reader, album)
        reader.destroyed.connect(lambda _=None, dialog=reader: self.forget_reader_dialog(dialog))
        reader.set_restore_page(self.reader_controller.restore_page(album, chapter.chapter_id))
        reader.start_online_chapter(copy.deepcopy(album), copy.deepcopy(chapter), self.download_config(), self.log)
        self.clear_album_selection()
        reader.showMaximized()
        reader.raise_()
        reader.activateWindow()

    def load_chapters_then_read(self, album_id: str):
        album = self.albums.get(album_id) or self.detail_cache.get(album_id)
        if not album:
            return
        reader = self.pending_reader_by_album_id.get(album_id)
        if reader is None:
            reader = HdMangaReaderWindow(f"漫画阅读 - {album.title}")
            self.reader_dialogs.append(reader)
            self.pending_reader_by_album_id[album_id] = reader
            self.cancelled_reader_album_ids.discard(album_id)
            self.bind_reader_download_action(reader, album)
            reader.destroyed.connect(lambda _=None, album_id=album_id: self.forget_pending_reader(album_id))
            reader.prepare_online_album(copy.deepcopy(album), self.download_config(), self.log, "正在加载章节，准备阅读")
            self.clear_album_selection()
            reader.showMaximized()
            reader.raise_()
            reader.activateWindow()
        cached = self.detail_cache.get(album_id)
        if cached and cached.chapters:
            self.albums[album_id] = copy.deepcopy(cached)
            reader.start_first_available_chapter(copy.deepcopy(self.albums[album_id]), self.download_config(), self.log)
            return
        if album.chapters:
            self.detail_cache[album_id] = copy.deepcopy(album)
            reader.start_first_available_chapter(copy.deepcopy(album), self.download_config(), self.log)
            return
        worker = self.reader_chapter_workers.get(album_id)
        if worker and worker.isRunning():
            self.log(f"章节正在加载，稍后自动进入阅读：{album.title}")
            return
        self.log(f"右键阅读：正在加载章节 {album.title}（{album.album_id}）")
        worker = ChapterWorker(copy.deepcopy(album), self.network_config(), self)
        self.reader_chapter_workers[album_id] = worker
        worker.chapters_loaded.connect(lambda loaded_id, chapters, album_id=album_id: self.on_reader_chapters_loaded(album_id, loaded_id, chapters))
        worker.log.connect(self.log)
        worker.failed.connect(lambda message, album_id=album_id: self.on_reader_chapters_failed(album_id, message))
        worker.finished.connect(lambda album_id=album_id: self.reader_chapter_workers.pop(album_id, None))
        worker.start()

    def on_reader_chapters_loaded(self, requested_id: str, album_id: str, detail_or_chapters):
        if requested_id != album_id:
            return
        album = self.albums.get(album_id) or self.detail_cache.get(album_id)
        if not album:
            return
        if isinstance(detail_or_chapters, AlbumMeta):
            detail = detail_or_chapters
            if album.cover_url and not detail.cover_url:
                detail.cover_url = album.cover_url
            album = detail
        else:
            album.chapters = detail_or_chapters
        self.albums[album_id] = album
        self.detail_cache[album_id] = copy.deepcopy(album)
        self.update_album_card_content(album)
        self.save_local_cache()
        if album_id in self.cancelled_reader_album_ids:
            return
        reader = self.pending_reader_by_album_id.get(album_id)
        if reader is not None:
            if getattr(reader, "_closed", False):
                self.pending_reader_by_album_id.pop(album_id, None)
                self.cancelled_reader_album_ids.add(album_id)
                return
            try:
                reader.start_first_available_chapter(copy.deepcopy(album), self.download_config(), self.log)
            except RuntimeError:
                self.pending_reader_by_album_id.pop(album_id, None)
                self.cancelled_reader_album_ids.add(album_id)
        else:
            self.open_reader_for_album(album)

    def on_reader_chapters_failed(self, album_id: str, message: str):
        self.pending_reader_by_album_id.pop(album_id, None)
        self.cancelled_reader_album_ids.discard(album_id)
        self.log(f"阅读章节加载失败 {album_id}：{message}")
        self.show_toast(f"阅读加载失败：{message}", 2200)

    def forget_pending_reader(self, album_id: str):
        self.pending_reader_by_album_id.pop(album_id, None)
        self.cancelled_reader_album_ids.add(album_id)
        worker = self.reader_chapter_workers.get(album_id)
        if worker and worker.isRunning():
            worker.cancel()

    def cancel_reader_chapter_workers(self):
        for album_id, worker in list(self.reader_chapter_workers.items()):
            if worker and worker.isRunning():
                worker.cancel()
            self.cancelled_reader_album_ids.add(album_id)

    def forget_reader_dialog(self, dialog: QWidget, album_id: str = ""):
        try:
            if dialog in self.reader_dialogs:
                self.reader_dialogs.remove(dialog)
        except RuntimeError:
            self.reader_dialogs = [item for item in self.reader_dialogs if item is not dialog]
        if album_id:
            self.pending_reader_by_album_id.pop(album_id, None)
        else:
            for key, value in list(self.pending_reader_by_album_id.items()):
                if value is dialog:
                    self.pending_reader_by_album_id.pop(key, None)

    def forget_local_reader_dialog(self, dialog: QWidget):
        if dialog in self.local_reader_dialogs:
            self.local_reader_dialogs.remove(dialog)
        if hasattr(self, "history_save_timer") and self.history_save_timer.isActive():
            self.history_save_timer.stop()
            self.save_local_cache()

    def selected_chapter_ids(self, album: AlbumMeta) -> List[str]:
        ids = []
        for row in range(self.chapter_table.rowCount()):
            item = self.chapter_table.item(row, 0)
            if item and item.checkState() == Qt.Checked and row < len(album.chapters):
                ids.append(album.chapters[row].chapter_id)
        return ids

    def add_album_to_queue(self, album_id: str, switch_page: bool = True, refresh: bool = True, toast_parent: Optional[QWidget] = None) -> bool:
        album = self.albums.get(album_id)
        if not album:
            return False
        if any(item.album_id == album_id for item in self.queue):
            self.log(f"下载队列已存在：{album.title}")
            self.show_toast("漫画已存在，无需重复下载")
            return False
        if any(item.album_id == album_id for item in self.download_pending_queue) or album_id in self.download_workers:
            self.log(f"漫画正在下载中，已跳过重复任务：{album.title}")
            self.show_toast("漫画已在下载中，无需重复下载")
            return False
        if self.album_has_completed_local_resource(album):
            self.log(f"本地已存在完整漫画，已跳过重复下载：{album.title}")
            self.show_toast("漫画已存在，无需重复下载")
            return False
        queued = copy.deepcopy(album)
        if album_id == self.current_album_id and hasattr(self, "chapter_table"):
            queued.selected_chapter_ids = self.selected_chapter_ids(album)
        else:
            queued.selected_chapter_ids = [chapter.chapter_id for chapter in album.chapters]
        if not queued.selected_chapter_ids and queued.chapters:
            self.show_toast("请至少勾选一个章节")
            return False
        self.queue.append(queued)
        self.queue_automatic_download(queued)
        self.log(f"已加入下载队列：{queued.title}，章节 {self.queue_chapter_count(queued)} 个。")
        if refresh:
            self.refresh_queue_table()
        if switch_page:
            self.switch_page(self.queue_page_index())
        return True

    def add_current_album_to_queue(self):
        album = self.current_album()
        if not album:
            self.show_toast("请先选择一个漫画")
            return
        self.add_album_to_queue(album.album_id)

    def add_selected_albums_to_queue(self, switch_page: bool = True, quiet: bool = False):
        added = 0
        for album_id in list(self.selected_album_ids):
            if self.add_album_to_queue(album_id, switch_page=False, refresh=False):
                added += 1
        if not added:
            if not quiet:
                self.show_toast("请先勾选漫画")
            return
        self.refresh_queue_table()
        if switch_page:
            self.switch_page(self.queue_page_index())

    def create_download_card(self, album: Optional[AlbumMeta], title: str = "", status: str = "等待中", active: bool = False) -> QFrame:
        path = ui_dir() / "download_card.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open download_card.ui: {path}")
        try:
            card = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if card is None:
            raise RuntimeError(f"Unable to load download_card.ui: {path}")
        card.setObjectName("currentDownloadCard" if active else "downloadCard")
        card.setProperty("album_id", album.album_id if album else "")
        card.setMinimumHeight(148 if active else 132)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setStyleSheet(self.download_card_style())
        cover = card.findChild(QLabel, "downloadCover")
        title_label = card.findChild(QLabel, "downloadTitle")
        status_label = card.findChild(QLabel, "downloadStatus")
        sub = card.findChild(QLabel, "downloadSub")
        transfer = card.findChild(QLabel, "downloadTransfer")
        progress = card.findChild(QProgressBar, "downloadProgress")
        retry = card.findChild(QPushButton, "downloadRetry")
        cancel = card.findChild(QPushButton, "downloadCancel")
        required = [cover, title_label, status_label, sub, transfer, progress, retry, cancel]
        if any(widget is None for widget in required):
            raise RuntimeError("download_card.ui is missing required controls")
        cover._persistent_cover = True
        cover_size = QSize(90, 120) if active else QSize(82, 110)
        cover.setFixedSize(cover_size)
        cover.setAlignment(Qt.AlignCenter)
        if album:
            self.apply_loading_movie(
                cover,
                QSize(min(cover_size.width() - 10, 72), min(cover_size.height() - 14, 82)),
            )
            self.request_cover(album, cover, priority=True)
        else:
            cover.setText("无封面")
        name = title or (album.title if album else "-")
        title_width = 300 if album else 280
        title_label.setText(QFontMetrics(self.font()).elidedText(name, Qt.ElideRight, title_width))
        title_label.setToolTip(name)
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_label.setText(status)
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setMinimumWidth(64)
        status_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        if active:
            sub_text = "当前下载任务"
        elif album:
            sub_text = f"ID：{album.album_id}    章节：{self.queue_chapter_count(album)}"
        else:
            sub_text = "队列为空，添加漫画后会显示在这里"
        sub.setToolTip(sub_text)
        sub.setText(sub_text)
        transfer_text = "已下：0 B    速度：0 B/s" if album else ""
        transfer.setVisible(bool(album))
        transfer.setText(transfer_text)
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setFormat("0%" if album else "无任务")
        retry.setFixedWidth(64)
        retry.setVisible(bool(album))
        retry.setEnabled(bool(album))
        cancel.setFixedWidth(64)
        cancel.setVisible(bool(album))
        if album:
            retry.clicked.connect(lambda checked=False, album_id=album.album_id: self.retry_album_download(album_id))
            cancel.clicked.connect(lambda checked=False, album_id=album.album_id: self.request_download_card_cancel(album_id))
            self.sync_download_card_actions(album.album_id, card)
        return card

    def update_download_card_state(self, album_id: str, status_text: str, done: Optional[int] = None, total: Optional[int] = None, sub_text: Optional[str] = None):
        card = self.download_card_by_id.get(album_id)
        if not card:
            return
        status = card.findChild(QLabel, "downloadStatus")
        progress = card.findChild(QProgressBar, "downloadProgress")
        sub = card.findChild(QLabel, "downloadSub")
        cancel = card.findChild(QPushButton, "downloadCancel")
        if status:
            status.setText(status_text)
        if progress and done is not None and total is not None:
            percent = self.download_percent(done, total)
            self.set_download_card_progress(progress, done, total, f"{percent}%")
        if sub_text and sub:
            sub.setText(sub_text)
            sub.setToolTip(sub_text)
        if cancel and status_text in {"Done", "Failed", "Cancelled"}:
            cancel.setEnabled(False)

    def queue_chapter_count(self, album: Optional[AlbumMeta]) -> int:
        if not album:
            return 0
        return len(album.selected_chapter_ids) or len(album.chapters) or 1

    def refresh_queue_table(self):
        if not hasattr(self, "queue_cards_layout"):
            return
        visible_queue = self.visible_download_queue()
        self.update_download_empty_state()
        self.download_queue_stack.setCurrentIndex(0 if visible_queue else 1)
        self.update_download_page_stats()
        if getattr(self, "queue_status_label", None) is not None:
            self.queue_status_label.setText(self.download_status_text())
        wanted_ids = [album.album_id for album in visible_queue]
        wanted_set = set(wanted_ids)
        existing_cards: Dict[str, QFrame] = {}
        for index in range(self.queue_cards_layout.count() - 1, -1, -1):
            item = self.queue_cards_layout.itemAt(index)
            widget = item.widget() if item else None
            if not widget:
                continue
            album_id = widget.property("album_id") or ""
            if album_id and album_id in wanted_set:
                existing_cards[str(album_id)] = widget
            else:
                self.queue_cards_layout.takeAt(index)
                widget.deleteLater()
        self.download_card_by_id.clear()

        insert_at = 0
        for album in visible_queue:
            card = existing_cards.get(album.album_id)
            if card is not None:
                old_index = self.queue_cards_layout.indexOf(card)
                if old_index >= 0:
                    self.queue_cards_layout.takeAt(old_index)
            else:
                card = self.create_download_card(album)
            self.download_card_by_id[album.album_id] = card
            self.sync_download_card_actions(album.album_id, card)
            self.queue_cards_layout.insertWidget(insert_at, card)
            insert_at += 1
        self.update_download_dashboard()

    def clear_queue(self):
        if self.is_download_busy():
            self.show_toast("当前有漫画正在下载，请先取消下载后再清空队列")
            return
        self.log("已清空下载等待队列。")
        for album in list(self.queue) + list(self.download_pending_queue):
            self.clear_download_task_state(album.album_id)
        self.queue.clear()
        self.download_pending_queue.clear()
        self.download_paused_ids.clear()
        self.refresh_queue_table()

    def remove_finished_album_from_queue(self, album_id: str):
        before_queue = len(self.queue)
        before_pending = len(self.download_pending_queue)
        self.queue = [album for album in self.queue if album.album_id != album_id]
        self.download_pending_queue = [album for album in self.download_pending_queue if album.album_id != album_id]
        if len(self.queue) != before_queue or len(self.download_pending_queue) != before_pending:
            self.clear_download_task_state(album_id)
            self.log(f"已从下载列表移除完成任务：{album_id}")
            self.refresh_queue_table()

    def start_download_queue(self):
        if not self.queue and not self.download_pending_queue:
            self.show_toast("下载队列为空")
            return
        if not self.download_pending_queue:
            active_ids = set(self.download_workers)
            runnable_states = {"waiting", "paused"}
            self.download_pending_queue = [
                copy.deepcopy(album)
                for album in self.queue
                if album.album_id not in active_ids
                and self.download_task_state(album.album_id) in runnable_states
            ]
        if not self.download_pending_queue and not self.download_workers:
            self.show_toast("没有可继续的任务，失败任务请手动重试")
            self.update_download_dashboard()
            return
        for album in self.download_pending_queue:
            self.set_download_task_state(album.album_id, "waiting")
            self.download_paused_ids.discard(album.album_id)
        self.refresh_queue_table()
        self.log(f"开始并发下载：等待 {len(self.download_pending_queue)} 本，最多同时 {self.max_parallel_downloads()} 本。")
        self.cancel_btn.setEnabled(True)
        self.last_global_download_percent = 0
        if self.download_can_use_global_progress():
            self.set_backend_status("正在并发下载", "busy")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("总进度 0%")
        elif getattr(self, "queue_status_label", None) is not None:
            self.queue_status_label.setText(self.download_status_text())
        self.start_download_scheduler()
        self.pump_download_workers()

    def max_parallel_downloads(self) -> int:
        if hasattr(self, "parallel_downloads"):
            return max(1, self.parallel_downloads.value())
        return 2

    def pump_download_workers(self):
        while self.download_pending_queue and len(self.download_workers) < self.max_parallel_downloads():
            album = self.download_pending_queue.pop(0)
            if self.download_task_state(album.album_id) != "waiting":
                continue
            self.start_single_download(album)
        self.update_download_summary()

    def start_single_download(self, album: AlbumMeta):
        self.download_cancelled_ids.discard(album.album_id)
        self.download_paused_ids.discard(album.album_id)
        self.set_download_task_state(album.album_id, "starting")
        chapter_total = max(1, self.queue_chapter_count(album))
        self.download_chapter_totals[album.album_id] = chapter_total
        self.download_chapter_done_counts[album.album_id] = 0
        self.download_totals[album.album_id] = chapter_total
        self.download_done_counts[album.album_id] = 0
        self.download_percent_by_id[album.album_id] = 0
        self.download_bytes[album.album_id] = 0
        self.download_speeds[album.album_id] = 0.0
        worker = self.download_controller.start(copy.deepcopy(album))
        if worker is None:
            self.set_download_task_state(album.album_id, "waiting")
            return
        self.log(f"并发下载启动：{album.title}")
        card = self.download_card_by_id.get(album.album_id)
        if card:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            if status:
                status.setText("排队启动")
            if progress:
                self.set_download_card_progress(progress, 0, max(1, self.queue_chapter_count(album)), "准备中")
        self.sync_download_card_actions(album.album_id)
        self.update_download_dashboard()

    def on_download_worker_created(self, album: AlbumMeta, worker: DownloadWorker):
        worker.album_started.connect(self.on_download_album_started)
        worker.album_progress.connect(self.on_download_album_progress)
        worker.chapter_done.connect(self.on_download_chapter_done)
        worker.album_transfer.connect(self.on_download_album_transfer)
        worker.album_done.connect(self.on_download_album_done)
        worker.item_done.connect(
            lambda done_album, path: None
            if done_album.album_id in self.download_cancelled_ids
            or done_album.album_id in self.download_paused_ids
            else self.add_completed_item(done_album, path)
        )
        worker.finished_ok.connect(lambda album_id=album.album_id: self.on_single_download_finished(album_id))
        worker.failed.connect(lambda message, album_id=album.album_id: self.on_single_download_failed(album_id, message))
        worker.finished.connect(lambda album_id=album.album_id: self.forget_download_worker(album_id))

    def on_download_album_started(self, album: AlbumMeta, total: int):
        if album.album_id in self.download_cancelled_ids:
            return
        self.current_download_album_id = album.album_id
        self.set_download_task_state(album.album_id, "downloading")
        self.download_controller.update_progress(album.album_id, DownloadState.FETCH_IMAGES, total_images=total)
        self.log(f"当前下载任务：{album.title}，正在解析图片列表。")
        chapter_total = max(1, total)
        self.download_chapter_totals[album.album_id] = chapter_total
        self.download_chapter_done_counts.setdefault(album.album_id, 0)
        self.download_totals[album.album_id] = chapter_total
        self.download_done_counts.setdefault(album.album_id, 0)
        card = self.download_card_by_id.get(album.album_id)
        if card:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            sub = card.findChild(QLabel, "downloadSub")
            if status:
                status.setText("下载中")
            if progress:
                current_done = self.download_done_counts.get(album.album_id, 0)
                current_total = self.download_totals.get(album.album_id, chapter_total)
                text = f"章节 {current_done}/{current_total}" if chapter_total > 1 else "解析图片"
                self.set_download_card_progress(progress, current_done, current_total, text)
            if sub:
                sub_text = f"ID：{album.album_id}    章节：0 / {chapter_total}" if chapter_total > 1 else f"ID：{album.album_id}    正在解析图片"
                sub.setText(sub_text)
                sub.setToolTip(sub_text)
        self.sync_download_card_actions(album.album_id)
        self.update_download_dashboard()

    def on_download_album_progress(self, album: AlbumMeta, done: int, total: int):
        if album.album_id in self.download_cancelled_ids:
            return
        self.current_download_album_id = album.album_id
        if done == 0 or done == total or done % 10 == 0:
            self.log(f"下载进度：{album.title} {done}/{max(1, total)} 张图片。")
        self.queue_download_progress_refresh(album, done, total)

    def on_download_chapter_done(self, album: AlbumMeta, done: int, total: int):
        if album.album_id in self.download_cancelled_ids:
            return
        total = max(1, total)
        done = max(self.download_chapter_done_counts.get(album.album_id, 0), min(done, total))
        self.download_chapter_totals[album.album_id] = total
        self.download_chapter_done_counts[album.album_id] = done
        if total > 1:
            self.download_totals[album.album_id] = total
            self.download_done_counts[album.album_id] = done
        latest = self.download_image_progress_by_id.get(album.album_id, (0, 1))
        image_done, image_total = latest
        self.queue_download_progress_refresh(
            album, image_done, image_total, immediate=True
        )

    def flush_download_card_progress(self, album: AlbumMeta, done: int, total: int):
        self.download_progress_pending.discard(album.album_id)
        card = self.download_card_by_id.get(album.album_id)
        if card:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            sub = card.findChild(QLabel, "downloadSub")
            if status:
                status.setText("Downloading" if done < total else "Processing")
            if progress:
                percent = self.download_percent(done, total)
                chapter_total = self.download_chapter_totals.get(album.album_id, 1)
                text = f"章节 {done}/{total}" if chapter_total > 1 else f"{percent}%"
                self.set_download_card_progress(progress, done, total, text)
            if sub:
                chapter_total = self.download_chapter_totals.get(album.album_id, 1)
                if chapter_total > 1:
                    sub_text = f"ID：{album.album_id}    章节：{done} / {max(1, total)}"
                else:
                    sub_text = f"ID：{album.album_id}    图片：{done} / {max(1, total)}"
                sub.setText(sub_text)
                sub.setToolTip(sub_text)
        self.update_download_summary()

    def on_download_album_transfer(self, album: AlbumMeta, bytes_done: int, speed: float):
        if album.album_id in self.download_cancelled_ids:
            return
        self.download_bytes[album.album_id] = max(0, int(bytes_done))
        self.download_speeds[album.album_id] = max(0.0, float(speed))
        if album.album_id in self.download_transfer_pending:
            return
        self.download_transfer_pending.add(album.album_id)
        QTimer.singleShot(180, lambda album_id=album.album_id: self.flush_download_card_transfer(album_id))

    def flush_download_card_transfer(self, album_id: str):
        self.download_transfer_pending.discard(album_id)
        card = self.download_card_by_id.get(album_id)
        if not card:
            return
        transfer = card.findChild(QLabel, "downloadTransfer")
        if not transfer:
            return
        size_text = self.format_bytes(self.download_bytes.get(album_id, 0))
        speed_text = self.format_speed(self.download_speeds.get(album_id, 0.0))
        transfer.setText(f"已下：{size_text}    速度：{speed_text}")
        self.update_download_dashboard()

    def on_download_album_done(self, album: AlbumMeta):
        if album.album_id in self.download_cancelled_ids or album.album_id in self.download_paused_ids:
            return
        self.flush_queued_download_progress(album.album_id)
        self.set_download_task_state(album.album_id, "finalizing")
        self.log(f"漫画下载完成：{album.title}（{album.album_id}）")
        self.download_controller.update_progress(album.album_id, DownloadState.FINALIZING)
        card = self.download_card_by_id.get(album.album_id)
        if card:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            transfer = card.findChild(QLabel, "downloadTransfer")
            if status:
                status.setText("已完成")
            if progress:
                self.set_download_card_progress(progress, 1, 1, "100%")
            if transfer:
                transfer.setText(f"已下：{self.format_bytes(self.download_bytes.get(album.album_id, 0))}    速度：已完成")
        chapter_total = max(1, self.download_chapter_totals.get(album.album_id, self.download_totals.get(album.album_id, 1)))
        self.download_chapter_done_counts[album.album_id] = chapter_total
        self.download_done_counts[album.album_id] = self.download_totals.get(album.album_id, 1)
        self.sync_download_card_actions(album.album_id)
        self.update_download_summary()

    def reset_current_download_card(self, status: str = "空闲"):
        self.current_download_album_id = ""
        if getattr(self, "queue_status_label", None) is not None:
            self.queue_status_label.setText(self.download_status_text())
        self.cancel_btn.setEnabled(self.is_download_busy())

    def on_single_download_finished(self, album_id: str):
        if album_id in self.download_cancelled_ids:
            self.log(f"单本下载已取消：{album_id}")
            return
        if album_id in self.download_paused_ids:
            self.set_download_task_state(album_id, "paused")
            self.sync_download_card_actions(album_id)
            self.update_download_dashboard()
            return
        self.set_download_task_state(album_id, "completed")
        self.log(f"单本下载完成：{album_id}")
        self.remove_finished_album_from_queue(album_id)
        self.update_download_summary()

    def on_single_download_failed(self, album_id: str, message: str):
        if album_id in self.download_cancelled_ids:
            self.log(f"漫画下载已取消 {album_id}")
            return
        if album_id in self.download_paused_ids:
            self.set_download_task_state(album_id, "paused")
            self.download_controller.update_progress(album_id, DownloadState.PAUSED)
            card = self.download_card_by_id.get(album_id)
            if card:
                status = card.findChild(QLabel, "downloadStatus")
                progress = card.findChild(QProgressBar, "downloadProgress")
                transfer = card.findChild(QLabel, "downloadTransfer")
                if status:
                    status.setText("已暂停")
                if progress:
                    progress.setFormat("已暂停")
                if transfer:
                    transfer.setText(f"已下：{self.format_bytes(self.download_bytes.get(album_id, 0))}    速度：已暂停")
            self.sync_download_card_actions(album_id)
            self.update_download_summary()
            return
        self.set_download_task_state(album_id, "failed")
        self.log(f"漫画下载失败 {album_id}：{message}")
        card = self.download_card_by_id.get(album_id)
        if card:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            transfer = card.findChild(QLabel, "downloadTransfer")
            if status:
                status.setText("失败")
            if progress:
                progress.setFormat("失败")
            if transfer:
                transfer.setText(f"已下：{self.format_bytes(self.download_bytes.get(album_id, 0))}    速度：已停止")
        self.download_pending_queue = [album for album in self.download_pending_queue if album.album_id != album_id]
        self.download_totals.pop(album_id, None)
        self.download_done_counts.pop(album_id, None)
        self.download_chapter_totals.pop(album_id, None)
        self.download_chapter_done_counts.pop(album_id, None)
        self.download_percent_by_id.pop(album_id, None)
        self.download_speeds[album_id] = 0.0
        self.sync_download_card_actions(album_id)
        self.update_download_summary()

    def retry_album_download(self, album_id: str):
        album = self.find_album_for_download_retry(album_id)
        if not album:
            self.show_toast("找不到可重试的漫画信息")
            return
        worker = self.download_workers.get(album_id)
        if worker and worker.isRunning():
            self.download_retry_ids.add(album_id)
            self.download_cancelled_ids.add(album_id)
            worker.cancel()
            self.log(f"正在停止卡住的下载，稍后自动重试：{album.title}")
        self.download_pending_queue = [item for item in self.download_pending_queue if item.album_id != album_id]
        self.download_pending_queue.insert(0, copy.deepcopy(album))
        self.set_download_task_state(album_id, "waiting")
        self.download_paused_ids.discard(album_id)
        if not any(item.album_id == album_id for item in self.queue):
            self.queue.append(copy.deepcopy(album))
        card = self.download_card_by_id.get(album_id)
        if card:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            transfer = card.findChild(QLabel, "downloadTransfer")
            if status:
                status.setText("等待重试")
            if progress:
                self.set_download_card_progress(progress, 0, 1, "等待重试")
            if transfer:
                transfer.setText("正在重新排队")
        self.cleanup_download_album_state(album_id)
        self.set_download_task_state(album_id, "waiting")
        self.start_download_scheduler()
        if not (worker and worker.isRunning()):
            self.pump_download_workers()

    def find_album_for_download_retry(self, album_id: str) -> Optional[AlbumMeta]:
        for source in (self.queue, self.download_pending_queue):
            for album in source:
                if album.album_id == album_id:
                    return copy.deepcopy(album)
        return copy.deepcopy(self.albums.get(album_id) or self.detail_cache.get(album_id)) if album_id in self.albums or album_id in self.detail_cache else None

    def cancel_album_download(self, album_id: str):
        worker = self.download_workers.get(album_id)
        self.download_controller.cancel(album_id)
        self.download_cancelled_ids.add(album_id)
        self.download_retry_ids.discard(album_id)
        self.download_paused_ids.discard(album_id)
        self.queue = [album for album in self.queue if album.album_id != album_id]
        self.download_pending_queue = [album for album in self.download_pending_queue if album.album_id != album_id]
        self.cleanup_download_album_state(album_id)
        self.clear_download_task_state(album_id)
        self.refresh_queue_table()
        self.update_download_summary()
        if worker and worker.isRunning():
            self.log(f"已取消并移出下载列表：{album_id}")
        else:
            self.log(f"已移除等待下载任务：{album_id}")

    def cleanup_download_album_state(self, album_id: str):
        self.download_totals.pop(album_id, None)
        self.download_done_counts.pop(album_id, None)
        self.download_chapter_totals.pop(album_id, None)
        self.download_chapter_done_counts.pop(album_id, None)
        self.download_percent_by_id.pop(album_id, None)
        self.download_bytes.pop(album_id, None)
        self.download_speeds.pop(album_id, None)
        self.download_progress_pending.discard(album_id)
        self.download_transfer_pending.discard(album_id)
        self.download_ui_progress.pop(album_id, None)
        self.download_image_progress_by_id.pop(album_id, None)

    def forget_download_worker(self, album_id: str):
        self.download_workers.pop(album_id, None)
        self.download_cancelled_ids.discard(album_id)
        if album_id in self.download_paused_ids:
            self.set_download_task_state(album_id, "paused")
        elif album_id not in {album.album_id for album in self.queue}:
            self.cleanup_download_album_state(album_id)
            self.clear_download_task_state(album_id)
        self.pump_download_workers()
        if not self.is_download_busy() and not self.download_pending_queue:
            self.on_all_downloads_finished()

    def on_all_downloads_finished(self):
        self.current_download_album_id = ""
        self.cancel_btn.setEnabled(False)
        self.download_cancelled_ids.clear()
        self.last_global_download_percent = 0
        paused = any(
            self.download_task_state(album.album_id) == "paused"
            for album in self.queue
        )
        failed = any(
            self.download_task_state(album.album_id) == "failed"
            for album in self.queue
        )
        if paused:
            self.set_backend_status("下载已暂停", "idle")
            self.log("下载任务已暂停，点击“开始 / 继续”可恢复。")
        elif failed:
            self.set_backend_status("下载等待重试", "warn")
            self.log("存在失败任务，点击任务上的“重试”继续下载。")
        else:
            self.set_backend_status("下载完成", "ok")
            self.log("全部下载任务完成。")
        self.stop_download_scheduler()
        self.update_download_summary()
        QTimer.singleShot(80, self.refresh_task_controls)

    def download_status_text(self) -> str:
        active = len(self.download_workers)
        pending = len(self.download_pending_queue)
        if active or pending:
            return f"{active} 本下载中，{pending} 本等待"
        return f"{len(self.queue)} 本等待" if self.queue else "等待添加"

    @staticmethod
    def download_percent(done: int, total: int) -> int:
        total = max(1, total)
        return max(0, min(100, round(done * 100 / total)))

    @staticmethod
    def format_bytes(value: int) -> str:
        size = max(0.0, float(value or 0))
        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        return f"{size:.1f} {units[unit_index]}"

    @classmethod
    def format_speed(cls, value: float) -> str:
        return f"{cls.format_bytes(int(value or 0))}/s"

    def download_can_use_global_progress(self) -> bool:
        return not self.is_loading_busy() and not (self.incremental_worker and self.incremental_worker.isRunning())

    def set_download_card_progress(self, progress: QProgressBar, done: int, total: int, text: Optional[str] = None):
        album_id = ""
        parent = progress.parent()
        while parent is not None:
            album_id = str(parent.property("album_id") or "")
            if album_id:
                break
            parent = parent.parent()
        percent = self.download_percent(done, total)
        if album_id:
            percent = max(self.download_percent_by_id.get(album_id, 0), percent)
            self.download_percent_by_id[album_id] = percent
        progress.setRange(0, 100)
        if progress.value() != percent:
            progress.setValue(percent)
        next_format = text or f"{percent}%"
        if progress.format() != next_format:
            progress.setFormat(next_format)

    def update_download_summary(self):
        total = sum(self.download_totals.values())
        done = sum(min(self.download_done_counts.get(album_id, 0), total_count) for album_id, total_count in self.download_totals.items())
        percent = self.download_percent(done, total)
        if self.download_can_use_global_progress():
            if self.download_workers or self.download_pending_queue:
                percent = max(self.last_global_download_percent, percent)
                self.last_global_download_percent = percent
            self.progress.setRange(0, 100)
            if self.progress.value() != percent:
                self.progress.setValue(percent)
            self.progress.setFormat(f"总进度 {percent}%")
        if getattr(self, "queue_status_label", None) is not None:
            self.queue_status_label.setText(self.download_status_text())
        if hasattr(self, "download_total_value"):
            self.update_download_page_stats()
        self.update_download_dashboard()

    def add_completed_item(self, album: AlbumMeta, pdf_path: str):
        if not pdf_path:
            return
        path = Path(pdf_path).expanduser()
        if not self.is_completed_local_resource(path):
            self.log(f"跳过未完成下载记录：{album.title}，{path}")
            return
        if self.completed_table is not None:
            row = self.completed_table.rowCount()
            self.completed_table.insertRow(row)
            for col, value in enumerate([album.title, path.name, str(path)]):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.completed_table.setItem(row, col, item)
        normalized_path = self.normalized_history_path(path)
        completed_paths = {self.normalized_history_path(Path(value).expanduser()) for value in self.completed}
        if normalized_path not in completed_paths:
            self.completed.append(str(path))

        image_dir = self.resolve_completed_image_dir(album, path)
        pdf_record_path = str(path) if path.suffix.lower() == ".pdf" else ""
        existing_index = self.find_history_index_for_album(album.album_id)
        if existing_index < 0:
            existing_index = self.find_history_index_for_output(path)
        outputs = [str(path)]
        if existing_index >= 0:
            old_record = self.download_history.pop(existing_index)
            old_outputs = old_record.get("outputs") or []
            if isinstance(old_outputs, list):
                outputs.extend(str(value) for value in old_outputs if str(value).strip())
            for key in ("path", "pdf_path", "image_dir"):
                value = old_record.get(key) or ""
                if value:
                    outputs.append(str(value))
        unique_outputs = []
        seen_outputs = set()
        for value in outputs:
            output = Path(value).expanduser()
            key = self.normalized_history_path(output)
            if key in seen_outputs or not self.is_completed_local_resource(output):
                continue
            seen_outputs.add(key)
            unique_outputs.append(str(output))
        record = {
            "title": album.title,
            "file": path.name,
            "path": str(path),
            "pdf_path": pdf_record_path,
            "image_dir": str(image_dir) if image_dir else "",
            "album_id": album.album_id,
            "cover_url": album.cover_url,
            "format": path.suffix.lstrip(".") or self.selected_output_format(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sort_order": str(len(self.download_history)),
            "outputs": unique_outputs or [str(path)],
        }
        self.download_history.append(record)
        self.selected_history_index = len(self.download_history) - 1
        self.update_download_page_stats()
        self.refresh_history_table()
        self.refresh_local_downloads_if_visible()
        self.save_local_cache()

    @staticmethod
    def normalized_history_path(path: Path) -> str:
        try:
            return str(path.expanduser().resolve(strict=False)).lower()
        except Exception:
            return str(path).lower()

    def find_history_index_for_album(self, album_id: str) -> int:
        if not album_id:
            return -1
        for index, record in enumerate(self.download_history):
            if str(record.get("album_id") or record.get("id") or "") == str(album_id):
                return index
        return -1

    def find_history_index_for_output(self, output_path: Path) -> int:
        target = self.normalized_history_path(output_path)
        for index, record in enumerate(self.download_history):
            paths = [record.get("path") or "", record.get("pdf_path") or "", record.get("image_dir") or ""]
            outputs = record.get("outputs") or []
            if isinstance(outputs, list):
                paths.extend(str(value) for value in outputs)
            for value in paths:
                if value and self.normalized_history_path(Path(value).expanduser()) == target:
                    return index
        return -1

    def resolve_completed_image_dir(self, album: AlbumMeta, output_path: Path) -> Optional[Path]:
        if output_path.is_dir() and self.collect_local_reader_images(output_path):
            return output_path
        candidates: List[Path] = []
        if output_path.suffix.lower() in {".pdf", ".zip"}:
            candidates.append(output_path.with_suffix(""))
        parent = output_path.parent
        if parent.exists():
            expected_prefix = f"JM{album.album_id}-"
            candidates.extend(
                child
                for child in sorted(parent.iterdir())
                if child.is_dir() and (child.name.startswith(expected_prefix) or album.album_id in child.name)
            )
        for candidate in candidates:
            if candidate.exists() and self.collect_local_reader_images(candidate):
                return candidate
        return None

    def set_progress(self, done: int, total: int):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.progress.setFormat(f"{self.download_percent(done, total)}%")

    def start_incremental_update(self, silent: bool = False):
        if self.incremental_worker and self.incremental_worker.isRunning():
            if not silent:
                self.show_toast("增量更新正在后台运行")
            return
        if self.is_busy():
            if not silent:
                self.show_toast("当前有任务运行，稍后再更新")
            return
        worker = IncrementalUpdateWorker(self.network_config(), parent=self)
        self.incremental_worker = worker
        worker.log.connect(self.log)
        worker.progress.connect(self.set_progress)
        worker.finished_ok.connect(lambda new_count, silent=silent: self.on_incremental_finished(new_count, silent))
        worker.failed.connect(lambda message, silent=silent: self.on_incremental_failed(message, silent))
        if not silent:
            self.set_backend_status("正在增量更新", "busy")
            self.start_loading("正在检查本地漫画更新")
        else:
            self.set_backend_status("后台静默更新", "busy")
        worker.start()

    def on_incremental_finished(self, new_count: int, silent: bool):
        self.incremental_worker = None
        self.set_backend_status("增量更新完成", "ok")
        self.log(f"增量更新完成，发现 {new_count} 个新章节。")
        self.refresh_task_controls()
        if not silent:
            self.show_toast(f"发现 {new_count} 个新章节，下载时会自动跳过旧章节", 2200)

    def on_incremental_failed(self, message: str, silent: bool):
        self.incremental_worker = None
        self.set_backend_status("增量更新失败", "error")
        self.log(f"增量更新失败：{message}")
        self.refresh_task_controls()
        if not silent:
            self.show_toast(f"增量更新失败：{message}", 2200)

    def task_done(self, message: str, page_index: Optional[int] = None):
        if "采集" in message or "加载" in message:
            status_text = (
                "搜索结果已加载"
                if getattr(self, "active_result_surface", "home") == "search"
                else "首页已加载"
            )
            self.set_backend_status(status_text, "ok")
            if "采集" in message:
                self.save_current_result_cache()
        elif "下载" in message:
            self.set_backend_status("下载完成", "ok")
        else:
            self.set_backend_status("空闲", "idle")
        self.log(message)
        if page_index is not None:
            self.switch_page(page_index)
        QTimer.singleShot(80, self.refresh_task_controls)

    def task_failed(self, message: str):
        if any(token in message for token in ["安全验证", "403", "429"]):
            self.set_backend_status("需验证/限流", "warn")
        else:
            self.set_backend_status("请求失败", "error")
        self.log(f"任务失败：{message}")
        QTimer.singleShot(80, self.refresh_task_controls)
        self.show_toast(f"任务失败：{message}", 2200)

    def cancel_current_task(self):
        if self.download_workers:
            active_ids = list(self.download_workers.keys())
            for worker in list(self.download_workers.values()):
                if worker.isRunning():
                    worker.cancel()
            self.download_cancelled_ids.update(active_ids)
            self.queue.clear()
            self.download_pending_queue.clear()
            for album_id in active_ids:
                self.cleanup_download_album_state(album_id)
            self.refresh_queue_table()
            self.update_download_summary()
            self.cancel_btn.setEnabled(False)
            self.log("已取消全部下载任务并清空下载列表。")
            return
        self.log("当前没有正在下载的任务。")
    def is_loading_busy(self) -> bool:
        return bool(
            (self.scrape_worker and self.scrape_worker.isRunning())
            or (self.chapter_worker and self.chapter_worker.isRunning())
        )

    def is_download_busy(self) -> bool:
        return any(worker.isRunning() for worker in self.download_workers.values())

    def is_busy(self) -> bool:
        return bool(
            self.is_loading_busy()
            or self.is_download_busy()
            or (self.incremental_worker and self.incremental_worker.isRunning())
        )

    def refresh_task_controls(self):
        self.cancel_btn.setEnabled(self.is_download_busy())
        if not self.is_loading_busy() and not (self.incremental_worker and self.incremental_worker.isRunning()):
            self.stop_loading()

    def choose_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_edit.text())
        if directory:
            self.output_edit.setText(directory)

    def open_output_dir(self):
        path = Path(self.output_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_site(self):
        QDesktopServices.openUrl(QUrl(self.list_url_edit.text().strip() or LIST_URL))

    def log(self, message: str):
        AppLog.info(str(message))
