"""Home page construction, category selection, and in-memory feed reuse."""

from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING

from PySide6.QtCore import QFile, QIODevice, QSize, QTimer, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QAbstractItemView,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...backend.jm_endpoints import WEB_LIST_URL as LIST_URL
from ...backend.models import AlbumMeta
from ...backend.runtime_paths import ui_dir
from ..feed_scroll_bar import (
    FEED_CARD_WIDTH,
    FEED_GRID_ROW_HEIGHT,
    FEED_MIN_GAP,
    FeedListWidget,
    FeedScrollBar,
)
from ..feed_corner_tools import FeedCornerTools

if TYPE_CHECKING:
    from ..ui import MainWindow


# Mirrors JMComic-qt's IndexView section list.  Keep request identifiers here
# with the page controller rather than at the application-window level.
HOME_CATEGORY_TABS = (
    ("latest", "最新上传", "latest", ""),
    ("serial", "连载更新 →右滑查看更多→", "promote", "连载更新"),
    ("c107", "C107推荐本本", "promote", "C107"),
    ("uncensored", "禁漫去码全彩化", "promote", "禁漫去码"),
    ("translated", "禁漫汉化组", "promote", "禁漫汉化"),
    ("hanman", "韩漫更新", "promote", "韩漫更新"),
    ("other", "其他更新", "promote", "其他更新"),
    ("library", "禁漫书库", "promote", "禁漫书库"),
    ("novels", "禁漫小说", "promote", "禁漫小说"),
)
HOME_CATEGORY_BY_KEY = {item[0]: item for item in HOME_CATEGORY_TABS}


class HomePageMixin:
    """Behavior that belongs exclusively to the home feed page."""

    def _create_home_result_list(self: "MainWindow", parent: QWidget) -> FeedListWidget:
        """Create one persistent JMComic-qt-style list for a home section."""
        result_list = FeedListWidget(parent)
        result_list.setObjectName("resultScroll")
        result_list.setViewMode(QListView.IconMode)
        result_list.setFlow(QListView.LeftToRight)
        result_list.setWrapping(True)
        result_list.setResizeMode(QListView.Adjust)
        result_list.setMovement(QListView.Static)
        result_list.setSelectionMode(QAbstractItemView.NoSelection)
        result_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        result_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        result_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        result_list.setVerticalScrollBar(FeedScrollBar(result_list))
        result_list.verticalScrollBar().setSingleStep(30)
        result_list.setFrameShape(QListWidget.NoFrame)
        result_list.setSpacing(0)
        result_list.configure_adaptive_grid(
            FEED_CARD_WIDTH,
            FEED_GRID_ROW_HEIGHT,
            min_gap=FEED_MIN_GAP,
        )
        result_list.setUniformItemSizes(True)
        result_list.verticalScrollBar().valueChanged.connect(self.on_result_scroll_value_changed)
        result_list.verticalScrollBar().movement_finished.connect(self.on_result_scroll_motion_finished)
        return result_list

    def _build_home_workspace(self: "MainWindow") -> QWidget:
        path = ui_dir() / "home.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open home form: {path}")
        try:
            page = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if page is None:
            raise RuntimeError(f"Unable to load home form: {path}")
        self.home_root_layout = page.findChild(QVBoxLayout, "homeRootLayout")
        if self.home_root_layout is None:
            raise RuntimeError("home.ui is missing homeRootLayout")

        # These fields are intentionally internal.  Scrape and cache code is
        # shared with non-home entry points, but the home form has no visible
        # duplicate filter controls.
        self.detail_check = QCheckBox()
        self.detail_check.setChecked(False)
        self.search_edit = QLineEdit()
        self.id_edit = QLineEdit()
        self.list_url_edit = QLineEdit()

        self.rank_group = QButtonGroup(self)
        self.rank_group.setExclusive(True)
        self.rank_buttons = {}
        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(True)
        self.category_buttons = {}
        self.home_category_scroll = page.findChild(QScrollArea, "homeCategoryScroll")
        self.search_result_toolbar = page.findChild(QWidget, "searchResultToolbar")
        self.search_result_query_label = page.findChild(QLabel, "searchResultQueryLabel")
        self.search_result_edit = page.findChild(QLineEdit, "searchResultEdit")
        self.search_result_button = page.findChild(QPushButton, "searchResultButton")
        self.home_category_layout = page.findChild(QHBoxLayout, "homeCategoryLayout")
        required_search_controls = (
            self.home_category_scroll,
            self.search_result_toolbar,
            self.search_result_query_label,
            self.search_result_edit,
            self.search_result_button,
            self.home_category_layout,
        )
        if any(control is None for control in required_search_controls):
            raise RuntimeError("home.ui is missing search controls")
        self.home_search_mode = False
        self.search_result_toolbar.hide()
        self.search_result_edit.returnPressed.connect(self.submit_home_search)
        self.search_result_button.clicked.connect(self.submit_home_search)
        self.home_category_group = QButtonGroup(self)
        self.home_category_group.setExclusive(True)
        self.home_category_buttons: Dict[str, QPushButton] = {}
        for key, label, _mode, _prefix in HOME_CATEGORY_TABS:
            button = QPushButton(label, page)
            button.setObjectName("homeCategoryButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, key=key: self.select_home_category(key))
            self.home_category_group.addButton(button)
            self.home_category_buttons[key] = button
            self.home_category_layout.addWidget(button)
        self.home_category_layout.addStretch()
        self.update_home_category_buttons()
        self.set_home_section_tabs_ready(False)

        self.result_stack = page.findChild(QStackedWidget, "resultStack")
        self.result_loading_page = page.findChild(QWidget, "resultLoadingPage")
        self.result_loading_text = page.findChild(QLabel, "resultLoadingText")
        self.result_loading_art = page.findChild(QLabel, "resultLoadingArt")
        old_result_scroll = page.findChild(QScrollArea, "resultScroll")
        self.result_grid_widget = page.findChild(QWidget, "resultGridWidget")
        self.result_grid = page.findChild(QGridLayout, "resultGrid")
        self.page_label = page.findChild(QLabel, "pageLabel")
        self.prev_page_btn = page.findChild(QPushButton, "prevPageButton")
        self.next_page_btn = page.findChild(QPushButton, "nextPageButton")
        required = [
            self.result_stack, self.result_loading_page, self.result_loading_text,
            old_result_scroll, self.result_grid_widget, self.result_grid,
            self.page_label, self.prev_page_btn, self.next_page_btn,
        ]
        if any(widget is None for widget in required):
            raise RuntimeError("home.ui is missing required controls")
        # Match JMComic-qt's ComicListWidget: item-view layout owns item
        # geometry, so appending a page never relays out the existing cards.
        # The .ui file keeps the old scroll area only for Designer
        # compatibility; replace it once at runtime with the actual feed.
        result_index = self.result_stack.indexOf(old_result_scroll)
        self.result_stack.removeWidget(old_result_scroll)
        self.result_scroll = self._create_home_result_list(self.result_stack)
        self.result_stack.insertWidget(max(0, result_index), self.result_scroll)
        self.home_result_stack_index = self.home_root_layout.indexOf(self.result_stack)
        old_result_scroll.deleteLater()
        self.result_list_mode = True
        self.result_grid_widget = self.result_scroll.viewport()
        self.result_grid = None
        self.home_corner_tools = FeedCornerTools(
            self.result_stack,
            self.refresh_current_home_results,
            self.scroll_home_results_to_top,
        )
        # Mirror JMComic-qt's IndexView: every section gets its own durable
        # ComicListWidget. Switching a tab must only change the active view.
        self.home_result_views = {}
        self.home_active_result_view_key = ""
        self.result_footer = page.findChild(QHBoxLayout, "resultFooter")
        if self.result_footer is not None:
            for index in range(self.result_footer.count()):
                item = self.result_footer.itemAt(index)
                widget = item.widget()
                if widget is not None:
                    widget.hide()
                spacer = item.spacerItem()
                if spacer is not None:
                    spacer.changeSize(0, 0, QSizePolicy.Minimum, QSizePolicy.Minimum)
            self.result_footer.setContentsMargins(0, 0, 0, 0)
            self.result_footer.setSpacing(0)
        self.list_url_edit.setText(LIST_URL)

        # The movie is started by reset_results when a real request begins.
        # Do not leave a hidden QMovie consuming UI time behind the list.
        if self.result_loading_art:
            self.stop_label_movie(self.result_loading_art)
        self.result_stack.setCurrentWidget(self.result_scroll)
        return page

    def activate_home_search_results(self: "MainWindow", query: str) -> None:
        """Show search results on their own retained page and list."""
        text = str(query).strip()
        self.home_search_mode = bool(text)
        # The old embedded toolbar remains hidden so returning Home always
        # shows its original section tabs and content unchanged.
        self.home_category_scroll.show()
        self.search_result_toolbar.hide()
        if self.home_search_mode:
            self.search_result_query_label.setText(text)
            self.search_result_edit.setText(text)
            self.search_page_query_label.setText(text)
            self.search_page_edit.setText(text)
            self.activate_result_surface("search")

    def deactivate_home_search_results(self: "MainWindow") -> None:
        restore_results = getattr(self, "restore_result_stack_to_home", None)
        if callable(restore_results):
            restore_results()
        self.home_search_mode = False
        self.home_category_scroll.show()
        self.search_result_toolbar.hide()

    def _build_search_workspace(self: "MainWindow") -> QWidget:
        page = self.load_ui_widget("search.ui", QWidget)
        self.search_page_query_label = page.findChild(QLabel, "searchPageQueryLabel")
        self.search_page_edit = page.findChild(QLineEdit, "searchPageEdit")
        self.search_page_button = page.findChild(QPushButton, "searchPageButton")
        search_stack = page.findChild(QStackedWidget, "searchResultStack")
        search_loading_page = page.findChild(QWidget, "searchLoadingPage")
        search_loading_text = page.findChild(QLabel, "searchLoadingText")
        search_loading_art = page.findChild(QLabel, "searchLoadingArt")
        old_search_scroll = page.findChild(QScrollArea, "searchResultScroll")
        required = (
            self.search_page_query_label,
            self.search_page_edit,
            self.search_page_button,
            search_stack,
            search_loading_page,
            search_loading_text,
            search_loading_art,
            old_search_scroll,
        )
        if any(widget is None for widget in required):
            raise RuntimeError("search.ui is missing required controls")
        result_index = search_stack.indexOf(old_search_scroll)
        search_stack.removeWidget(old_search_scroll)
        search_scroll = self._create_home_result_list(search_stack)
        search_scroll.setObjectName("searchResultList")
        search_stack.insertWidget(max(0, result_index), search_scroll)
        search_stack.setCurrentWidget(search_scroll)
        old_search_scroll.deleteLater()
        self.search_page_edit.returnPressed.connect(self.submit_search_page)
        self.search_page_button.clicked.connect(self.submit_search_page)
        self.search_corner_tools = FeedCornerTools(
            search_stack,
            self.refresh_current_home_results,
            self.scroll_home_results_to_top,
        )
        surfaces = getattr(self, "result_surfaces", None)
        if surfaces is None:
            raise RuntimeError("Search result surfaces must be initialized first")
        surfaces["search"] = {
            "stack": search_stack,
            "loading_page": search_loading_page,
            "loading_text": search_loading_text,
            "loading_art": search_loading_art,
            "scroll": search_scroll,
            "active_key": "",
        }
        return page

    def submit_search_page(self: "MainWindow") -> None:
        query = self.search_page_edit.text().strip()
        if not query:
            self.search_page_edit.setFocus(Qt.ShortcutFocusReason)
            self.show_toast("请输入搜索关键词", 1400)
            return
        self.open_search_results(query, preserve_path=True)

    def remember_home_before_detail_search(self: "MainWindow") -> None:
        """Retain the exact home feed shown before a detail metadata search."""
        if bool(getattr(self, "home_search_mode", False)):
            return
        if getattr(self, "active_result_surface", "home") != "home":
            return
        home_index = self.home_page_index()
        has_home_route = any(
            route_index == home_index and route_title == "首页"
            for route_index, route_title in self.page_navigation_stack
        )
        cache_key = str(getattr(self, "current_result_cache_key", "") or "")
        if not has_home_route or not cache_key:
            return
        self._capture_home_result_view()
        self.detail_search_home_state = {
            "cache_key": cache_key,
            "albums": list(getattr(self, "result_albums", [])),
            "home_category_key": self.home_category_key,
            "home_feed_mode": self.home_feed_mode,
            "home_category_prefix": self.home_category_prefix,
            "active_category": self.active_category,
            "pending_rank_request": self.pending_rank_request,
        }

    def restore_home_before_detail_search(self: "MainWindow") -> bool:
        """Restore Home without allowing the active search to replace it."""
        state = getattr(self, "detail_search_home_state", None)
        if not state:
            return False
        active_query = self.catalog_page_query()
        if active_query.mode == "search":
            self.home_controller.cancel(active_query)
        # Late search callbacks are ignored after this key is replaced with
        # the restored home query below.
        self._active_catalog_query_key = ""
        self.deactivate_home_search_results()
        self.search_edit.clear()
        self.search_result_edit.clear()
        self.id_edit.clear()
        self.home_category_key = str(state["home_category_key"])
        self.home_feed_mode = str(state["home_feed_mode"])
        self.home_category_prefix = str(state["home_category_prefix"])
        self.active_category = str(state["active_category"])
        self.pending_rank_request = state["pending_rank_request"]
        self.update_home_category_buttons()
        cache_key = str(state["cache_key"])
        albums = list(state["albums"])
        self.result_cache[cache_key] = albums
        if not self.restore_retained_home_result_view(cache_key, albums):
            self.prepare_home_result_view(cache_key)
            self.restore_album_list(cache_key, albums, fast_switch=True)
        self._active_catalog_query_key = self.catalog_page_query().key
        return True

    def restore_detail_search_results(self: "MainWindow") -> bool:
        """Reactivate the retained search list when its breadcrumb is used."""
        query = self.search_page_edit.text().strip()
        if not query:
            return False
        self.search_edit.setText(query)
        self.id_edit.clear()
        self.active_category = ""
        self.activate_home_search_results(query)
        self._active_catalog_query_key = self.catalog_page_query().key
        return True

    def submit_home_search(self: "MainWindow") -> None:
        query = self.search_result_edit.text().strip()
        if not query:
            self.search_result_edit.setFocus(Qt.ShortcutFocusReason)
            self.show_toast("请输入搜索关键词", 1400)
            return
        self.open_search_results(query)

    def scroll_home_results_to_top(self: "MainWindow") -> None:
        """Return to the beginning through the feed's smooth scrollbar."""
        if not hasattr(self, "result_scroll"):
            return
        scrollbar = self.result_scroll.verticalScrollBar()
        scroll_to = getattr(scrollbar, "scroll_to", None)
        if callable(scroll_to):
            scroll_to(0)
        else:
            scrollbar.setValue(0)

    def refresh_current_home_results(self: "MainWindow") -> None:
        """Force a fresh request for the currently selected feed/query."""
        worker = getattr(self, "scrape_worker", None)
        query = self.catalog_page_query()
        controller_state = getattr(self, "home_controller", None)
        state = (
            controller_state.states.get(query.key)
            if controller_state is not None
            else None
        )
        if (
            bool(getattr(self, "catalog_apply_pending", False))
            or bool(getattr(self, "append_render_pending", False))
            or bool(getattr(self, "auto_loading_next_page", False))
            or (worker is not None and worker.isRunning())
            or (state is not None and state.loading)
        ):
            self.show_toast("漫画正在加载，请稍候", 1400)
            return
        self.scroll_home_results_to_top()
        cache_key = self.result_cache_key()
        self.result_cache.pop(cache_key, None)
        # Keep HomeController's generation counter intact. Removing its state
        # lets a late callback from the previous request share the new
        # generation and incorrectly finish or replace the refresh request.
        self._force_home_catalog_refresh = True
        try:
            self.start_scrape()
        finally:
            self._force_home_catalog_refresh = False

    def update_home_category_buttons(self: "MainWindow") -> None:
        for key, button in getattr(self, "home_category_buttons", {}).items():
            button.setChecked(key == self.home_category_key)

    def set_home_section_tabs_ready(self: "MainWindow", ready: bool) -> None:
        """Mirror JMComic-qt: latest exists first; extra sections arrive later."""
        self.home_sections_ready = bool(ready)
        for key, button in getattr(self, "home_category_buttons", {}).items():
            button.setVisible(key == "latest" or self.home_sections_ready)

    def open_latest_home(self: "MainWindow") -> None:
        """Return to the canonical latest-upload page and refresh it."""
        self.category_rank_page_lock = False
        self.deactivate_home_search_results()
        self.clear_album_selection()
        self.search_edit.clear()
        self.id_edit.clear()
        self.active_category = ""
        self.home_feed_mode = "latest"
        self.home_category_key = "latest"
        self.home_category_prefix = ""
        self.update_home_category_buttons()
        self.switch_page(self.home_page_index())
        self.start_scrape()

    def select_home_category(self: "MainWindow", key: str) -> None:
        definition = HOME_CATEGORY_BY_KEY.get(key)
        if definition is None:
            return
        self.category_rank_page_lock = False
        self.deactivate_home_search_results()
        _key, _label, mode, prefix = definition
        if key == self.home_category_key and self.result_total_count:
            self.update_home_category_buttons()
            return
        self.clear_album_selection()
        self.search_edit.clear()
        self.id_edit.clear()
        self.active_category = ""
        self.home_category_key = key
        self.home_feed_mode = mode
        self.home_category_prefix = prefix
        self.update_home_category_buttons()
        cache_key = self.result_cache_key()
        cached = self.result_cache.get(cache_key)
        if cached:
            self.restore_home_category_from_memory(cache_key, cached)
            return
        self.start_scrape()

    def _capture_home_result_view(self: "MainWindow") -> None:
        key = getattr(self, "current_result_cache_key", "")
        if not key or not hasattr(self, "result_grid_widget"):
            return
        if getattr(self, "result_list_mode", False):
            self.home_result_views[key] = {
                "scroll": self.result_scroll,
                "card_by_id": self.card_by_id,
                "checkmark_by_id": self.checkmark_by_id,
                "cover_labels": self.result_cover_labels,
                "cover_requested": self.result_cover_requested,
                "render_limit": self.result_render_limit,
                "revealed": self.results_revealed,
                "scroll_value": self.result_scroll.verticalScrollBar().value(),
            }
            return
        self.home_result_views[key] = {
            "widget": self.result_grid_widget,
            "grid": self.result_grid,
            "card_by_id": self.card_by_id,
            "checkmark_by_id": self.checkmark_by_id,
            "cover_labels": self.result_cover_labels,
            "cover_requested": self.result_cover_requested,
            "render_limit": self.result_render_limit,
            "revealed": self.results_revealed,
            "scroll_value": self.result_scroll.verticalScrollBar().value(),
        }

    def prepare_home_result_view(self: "MainWindow", cache_key: str) -> bool:
        """Activate a new grid, returning True when a retained grid was found."""
        if not cache_key or not hasattr(self, "result_scroll"):
            return False
        if getattr(self, "result_list_mode", False):
            self.hide_home_append_loading()
            if cache_key == self.home_active_result_view_key:
                return cache_key in self.home_result_views
            # A queued append belongs to the list being left. It must not
            # resume later against the newly active section.
            self.append_render_pending = False
            self.append_render_generation += 1
            self.append_layout_freeze = False
            if self.home_active_result_view_key:
                self._capture_home_result_view()
            state = self.home_result_views.get(cache_key)
            if state is not None:
                self.result_scroll = state["scroll"]
                self.result_grid_widget = self.result_scroll.viewport()
                self.result_grid = None
                self.card_by_id = state["card_by_id"]
                self.checkmark_by_id = state["checkmark_by_id"]
                self.result_cover_labels = state["cover_labels"]
                self.result_cover_requested = state["cover_requested"]
                self.result_render_limit = state["render_limit"]
                self.results_revealed = state["revealed"]
                self.result_render_generation += 1
                for album_id, card in self.card_by_id.items():
                    cover = card.findChild(QLabel, "albumCover")
                    if cover is not None:
                        cover._album_id = album_id
                        cover._result_generation = self.result_render_generation
                self.result_stack.setCurrentWidget(self.result_scroll)
                self.home_active_result_view_key = cache_key
                return True

            if self.home_active_result_view_key:
                self.result_scroll = self._create_home_result_list(self.result_stack)
                self.result_stack.addWidget(self.result_scroll)
            self.result_grid_widget = self.result_scroll.viewport()
            self.result_grid = None
            self.card_by_id = {}
            self.checkmark_by_id = {}
            self.result_cover_labels = {}
            self.result_cover_requested = set()
            self.result_render_limit = 0
            self.results_revealed = False
            self.home_active_result_view_key = cache_key
            return False
        if cache_key == self.home_active_result_view_key:
            return cache_key in self.home_result_views
        self.hide_home_append_loading()
        self._capture_home_result_view()
        state = self.home_result_views.get(cache_key)
        if state is not None:
            current_widget = self.result_scroll.takeWidget()
            if current_widget is not None and current_widget is not state["widget"]:
                current_widget.setParent(None)
            self.result_grid_widget = state["widget"]
            self.result_grid = state["grid"]
            self.card_by_id = state["card_by_id"]
            self.checkmark_by_id = state["checkmark_by_id"]
            self.result_cover_labels = state["cover_labels"]
            self.result_cover_requested = state["cover_requested"]
            self.result_render_limit = state["render_limit"]
            self.results_revealed = state["revealed"]
            self.result_scroll.setWidget(self.result_grid_widget)
            self.home_active_result_view_key = cache_key
            return True

        current_widget = self.result_scroll.takeWidget()
        if current_widget is not None:
            current_widget.setParent(None)
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.result_grid_widget = widget
        self.result_grid = grid
        self.card_by_id = {}
        self.checkmark_by_id = {}
        self.result_cover_labels = {}
        self.result_cover_requested = set()
        self.result_scroll.setWidget(widget)
        self.home_active_result_view_key = cache_key
        return False

    def restore_retained_home_result_view(
        self: "MainWindow", cache_key: str, albums: List[AlbumMeta]
    ) -> bool:
        if getattr(self, "result_list_mode", False):
            if not self.prepare_home_result_view(cache_key):
                return False
            self.current_result_cache_key = cache_key
            self.result_albums = list(albums)
            self.result_total_count = len(albums)
            self.result_album_indices = {album.album_id: index for index, album in enumerate(albums)}
            self.albums = {album.album_id: album for album in albums}
            self.detail_cache.update({album.album_id: album for album in albums})
            state = self.home_result_views[cache_key]
            self.results_revealed = bool(state["revealed"])
            self.result_render_limit = state["render_limit"]
            self.loaded_source_pages = max(1, (len(albums) + 79) // 80)
            self.auto_load_has_more = True
            self.auto_loading_next_page = False
            scrollbar = self.result_scroll.verticalScrollBar()
            jump_to = getattr(scrollbar, "jump_to", None)
            if callable(jump_to):
                jump_to(state.get("scroll_value", 0))
            else:
                scrollbar.setValue(state.get("scroll_value", 0))
            self.result_stack.setCurrentWidget(self.result_scroll)
            self.update_page_controls()
            self.schedule_visible_cover_requests()
            self.set_backend_status("已切换分区", "ok")
            return True
        if not self.prepare_home_result_view(cache_key):
            return False
        self.current_result_cache_key = cache_key
        self.result_albums = list(albums)
        self.result_total_count = len(albums)
        self.result_album_indices = {album.album_id: index for index, album in enumerate(albums)}
        self.albums = {album.album_id: album for album in albums}
        self.detail_cache.update({album.album_id: album for album in albums})
        state = self.home_result_views[cache_key]
        self.results_revealed = bool(state["revealed"])
        self.result_render_limit = state["render_limit"]
        self.loaded_source_pages = max(1, (len(albums) + 79) // 80)
        self.auto_load_has_more = True
        self.auto_loading_next_page = False
        self.result_scroll.verticalScrollBar().setValue(state.get("scroll_value", 0))
        self.result_stack.setCurrentWidget(self.result_scroll)
        self.update_page_controls()
        self.schedule_visible_cover_requests()
        self.set_backend_status("已切换分区", "ok")
        return True

    def on_promote_sections_ready(
        self: "MainWindow", sections: Dict[str, List[AlbumMeta]]
    ) -> None:
        """Cache every /promote section before rendering the selected one."""
        self.home_promote_sections = {
            str(title): list(albums) for title, albums in (sections or {}).items()
        }
        for key, _label, mode, prefix in HOME_CATEGORY_TABS:
            if mode != "promote":
                continue
            normalized_prefix = "".join(str(prefix).split()).lower()
            albums = next(
                (
                    section_albums
                    for title, section_albums in self.home_promote_sections.items()
                    if "".join(title.split()).lower().startswith(normalized_prefix)
                ),
                [],
            )
            self.result_cache[f"promote:{key}:v1"] = list(albums)
        self.schedule_home_section_prewarm()

    def schedule_home_section_prewarm(self: "MainWindow") -> None:
        """Build hidden section lists ahead of the first tab switch.

        JMComic-qt creates every IndexView tab when the index response lands.
        Building one section per event-loop turn preserves that no-rebuild
        switch behavior without monopolizing this application's UI thread.
        """
        if not getattr(self, "result_list_mode", False):
            return
        pending = [
            (f"promote:{key}:v1", list(self.result_cache.get(f"promote:{key}:v1", [])))
            for key, _label, mode, _prefix in HOME_CATEGORY_TABS
            if mode == "promote" and f"promote:{key}:v1" not in self.home_result_views
        ]
        self.home_section_prewarm_queue = [item for item in pending if item[1]]
        if getattr(self, "home_section_prewarm_pending", False) or not self.home_section_prewarm_queue:
            return
        self.home_section_prewarm_pending = True
        QTimer.singleShot(30, self.prewarm_next_home_section)

    def prewarm_next_home_section(self: "MainWindow") -> None:
        if not getattr(self, "home_section_prewarm_pending", False):
            return
        if not getattr(self, "home_section_prewarm_queue", None):
            self.home_section_prewarm_pending = False
            return
        cache_key, albums = self.home_section_prewarm_queue.pop(0)
        if cache_key not in self.home_result_views and albums:
            self._prewarm_home_section_view(cache_key, albums)
        QTimer.singleShot(30, self.prewarm_next_home_section)

    def _prewarm_home_section_view(
        self: "MainWindow", cache_key: str, albums: List[AlbumMeta]
    ) -> None:
        """Create a hidden retained list without disturbing the active feed."""
        active = {
            "scroll": self.result_scroll,
            "grid_widget": self.result_grid_widget,
            "grid": self.result_grid,
            "cards": self.card_by_id,
            "checkmarks": self.checkmark_by_id,
            "cover_labels": self.result_cover_labels,
            "cover_requested": self.result_cover_requested,
            "cache_key": self.current_result_cache_key,
            "albums": self.result_albums,
            "total": self.result_total_count,
            "indices": self.result_album_indices,
            "album_map": self.albums,
            "render_limit": self.result_render_limit,
            "revealed": self.results_revealed,
            "page": self.current_result_page,
            "generation": self.result_render_generation,
        }
        try:
            self.result_scroll = self._create_home_result_list(self.result_stack)
            self.result_stack.addWidget(self.result_scroll)
            self.result_grid_widget = self.result_scroll.viewport()
            self.result_grid = None
            self.card_by_id = {}
            self.checkmark_by_id = {}
            self.result_cover_labels = {}
            self.result_cover_requested = set()
            self.current_result_cache_key = cache_key
            self.result_albums = list(albums)
            self.result_total_count = len(albums)
            self.result_album_indices = {album.album_id: index for index, album in enumerate(albums)}
            self.albums = {album.album_id: album for album in albums}
            self.result_render_limit = len(albums)
            self.results_revealed = True
            self.current_result_page = 1
            self.render_result_page(fast_switch=True)
            self._capture_home_result_view()
        finally:
            self.result_scroll = active["scroll"]
            self.result_grid_widget = active["grid_widget"]
            self.result_grid = active["grid"]
            self.card_by_id = active["cards"]
            self.checkmark_by_id = active["checkmarks"]
            self.result_cover_labels = active["cover_labels"]
            self.result_cover_requested = active["cover_requested"]
            self.current_result_cache_key = active["cache_key"]
            self.result_albums = active["albums"]
            self.result_total_count = active["total"]
            self.result_album_indices = active["indices"]
            self.albums = active["album_map"]
            self.result_render_limit = active["render_limit"]
            self.results_revealed = active["revealed"]
            self.current_result_page = active["page"]
            self.result_render_generation = active["generation"]
            self.result_stack.setCurrentWidget(self.result_scroll)
            self.update_page_controls()

    def show_home_append_loading(self: "MainWindow") -> None:
        """Show progress at the list tail without replacing already loaded cards."""
        if getattr(self, "result_list_mode", False):
            result_list = self.result_scroll
            item = getattr(result_list, "_append_loading_item", None)
            if item is not None:
                try:
                    if result_list.row(item) >= 0:
                        label = getattr(result_list, "_append_loading_label", None)
                        if label is not None:
                            self.stop_label_movie(label)
                            self.apply_detail_loading_movie(label, QSize(128, 128))
                        return
                except RuntimeError:
                    pass

            # The loading indicator is a real final list item. It therefore
            # follows the loaded comics while the user scrolls instead of
            # floating over whichever cards happen to be visible.
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(FEED_CARD_WIDTH, FEED_GRID_ROW_HEIGHT))
            container = QWidget(result_list.viewport())
            container.setObjectName("resultAppendLoadingContainer")
            container.setFixedSize(FEED_CARD_WIDTH, FEED_GRID_ROW_HEIGHT)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            label = QLabel(container)
            label.setObjectName("resultAppendLoading")
            label.setFixedSize(144, 144)
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            label.setStyleSheet("background:transparent;border:0;")
            layout.addStretch()
            layout.addWidget(label, 0, Qt.AlignHCenter)
            layout.addStretch()
            result_list.addItem(item)
            result_list.setItemWidget(item, container)
            result_list._append_loading_item = item
            result_list._append_loading_widget = container
            result_list._append_loading_label = label
            self.apply_detail_loading_movie(label, QSize(128, 128))
            self.result_append_loading_label = label
            container.show()
            return
        if not hasattr(self, "result_grid") or not hasattr(self, "result_grid_widget"):
            return
        label = getattr(self, "result_append_loading_label", None)
        if label is None:
            label = QLabel(self.result_grid_widget)
            label.setObjectName("resultAppendLoading")
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(72)
            label.setStyleSheet("color:#64748b;font-size:13px;font-weight:700;background:transparent;")
            self.result_append_loading_label = label
        label.setText("正在加载更多漫画")
        columns = max(1, self.result_columns())
        self.result_grid.removeWidget(label)
        row = (len(self.card_by_id) + columns - 1) // columns
        self.result_grid.addWidget(label, row, 0, 1, columns)
        self.apply_detail_loading_movie(label, QSize(42, 42))
        label.show()

    def position_home_append_loading(self: "MainWindow") -> None:
        """Compatibility hook; list-mode loading geometry is item-owned."""

    def hide_home_append_loading(self: "MainWindow") -> None:
        if getattr(self, "result_list_mode", False):
            result_list = self.result_scroll
            label = getattr(result_list, "_append_loading_label", None)
            if label is not None:
                try:
                    self.stop_label_movie(label)
                except RuntimeError:
                    pass
            item = getattr(result_list, "_append_loading_item", None)
            container = getattr(result_list, "_append_loading_widget", None)
            if item is not None:
                try:
                    row = result_list.row(item)
                    if row >= 0:
                        result_list.removeItemWidget(item)
                        result_list.takeItem(row)
                except RuntimeError:
                    pass
            if container is not None:
                try:
                    container.hide()
                    container.deleteLater()
                except RuntimeError:
                    pass
            result_list._append_loading_item = None
            result_list._append_loading_widget = None
            result_list._append_loading_label = None
            self.result_append_loading_label = None
            return
        label = getattr(self, "result_append_loading_label", None)
        if label is None:
            return
        self.stop_label_movie(label)
        if getattr(self, "result_grid", None) is not None:
            self.result_grid.removeWidget(label)
        label.hide()

    def show_home_initial_loading(
        self: "MainWindow", message: str = "正在加载漫画"
    ) -> None:
        """Start the detail-page movie whenever a new feed replaces the list."""
        if not hasattr(self, "result_stack"):
            return
        loading_art = getattr(self, "result_loading_art", None)
        if (
            loading_art is not None
            and getattr(loading_art, "_loading_movie", None) is None
        ):
            self.apply_detail_loading_movie(loading_art, QSize(150, 118))
        loading_text = getattr(self, "result_loading_text", None)
        if loading_text is not None:
            loading_text.setText(message)
        self.result_stack.setCurrentWidget(self.result_loading_page)

    def finish_home_initial_loading(self: "MainWindow") -> None:
        loading_art = getattr(self, "result_loading_art", None)
        if loading_art is not None:
            self.stop_label_movie(loading_art)
