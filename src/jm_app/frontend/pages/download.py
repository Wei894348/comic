"""Download page presentation for unfinished queue tasks."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ...backend.runtime_paths import resource_dir

if TYPE_CHECKING:
    from ..ui import MainWindow


DOWNLOAD_PAGE_STYLE = """
QFrame#downloadPanel { background:#f6f8fb; border:0; }
QFrame#downloadWorkspace {
    background:#ffffff; border:1px solid #e3e8f0; border-radius:8px;
}
QLabel#downloadPageTitle {
    color:#172033; font-size:16px; font-weight:800;
}
QLabel#downloadActiveMetric, QLabel#downloadWaitingMetric, QLabel#downloadSpeedMetric {
    min-height:26px; padding:0 9px; border-radius:6px;
    font-size:11px; font-weight:800;
}
QLabel#downloadActiveMetric { color:#1d4ed8; background:#eaf2ff; }
QLabel#downloadWaitingMetric { color:#58677a; background:#f0f3f7; }
QLabel#downloadSpeedMetric { color:#087f5b; background:#e6f7f0; }
QLabel#downloadHeaderIcon {
    background:#edf4ff; border:0; border-radius:17px;
}
QProgressBar#downloadProgress {
    min-height:20px; max-height:20px; border:0; border-radius:10px;
    background:#f0f2f6; color:#243046; text-align:center;
    font-size:11px; font-weight:800;
}
QProgressBar#downloadProgress::chunk { background:#3478f6; border-radius:10px; }
QPushButton#clearQueueButton, QPushButton#cancelDownloadsButton {
    min-height:38px; padding:0 14px; color:#526176; background:#ffffff;
    border:1px solid #dfe5ee; border-radius:7px; font-weight:700;
}
QPushButton#clearQueueButton:hover, QPushButton#cancelDownloadsButton:hover {
    color:#2563eb; background:#f7f9fc; border-color:#b9c7db;
}
QPushButton#cancelDownloadsButton:disabled {
    color:#aeb6c2; background:#f7f8fa; border-color:#e8ebf0;
}
QPushButton#startQueueButton {
    min-height:38px; padding:0 16px; color:#ffffff; background:#3478f6;
    border:1px solid #3478f6; border-radius:7px; font-weight:800;
}
QPushButton#startQueueButton:hover { background:#2468df; border-color:#2468df; }
QFrame#downloadDivider { background:#e8ecf2; border:0; }
QScrollArea#queueScroll, QWidget#queueCardsWidget, QWidget#downloadQueuePage,
QWidget#downloadEmptyPage { background:transparent; border:0; }
QLabel#downloadEmptyIcon {
    background:#edf4ff; border:0; border-radius:32px;
}
QLabel#downloadEmptyTitle { color:#243046; font-size:17px; font-weight:800; }
QLabel#downloadEmptyHint { color:#7a8699; font-size:13px; }
"""


DOWNLOAD_CARD_LIGHT_STYLE = """
QFrame#downloadCard, QFrame#currentDownloadCard {
    background:#ffffff; border:1px solid #dfe7f2; border-radius:8px;
}
QFrame#currentDownloadCard { background:#f8fbff; border-color:#9fc7ff; }
QLabel#downloadCover {
    background:#eef3f8; border:1px solid #dbe5f0; border-radius:6px; color:#8491a5;
}
QLabel#downloadTitle { color:#1f2937; font-size:13px; font-weight:800; }
QLabel#downloadSub { color:#64748b; font-size:12px; }
QLabel#downloadTransfer { color:#475569; font-size:12px; font-weight:700; }
QLabel#downloadStatus {
    background:#eef4ff; color:#1d4ed8; border:1px solid #d6e6ff;
    border-radius:9px; padding:2px 9px; font-size:12px; font-weight:700;
}
QProgressBar#downloadProgress {
    min-height:16px; max-height:16px; color:#334155; background:#eef3f8;
    border:1px solid #cbd8e6; border-radius:8px; text-align:center;
    font-size:11px; font-weight:700;
}
QProgressBar#downloadProgress::chunk { background:#3478f6; border-radius:7px; }
QPushButton#downloadCancel {
    min-width:58px; max-width:58px; padding:5px 8px; color:#be123c;
    background:#fff1f2; border:1px solid #fecdd3; border-radius:6px; font-weight:700;
}
QPushButton#downloadCancel:hover { background:#ffe4e6; }
QPushButton#downloadRetry {
    min-width:58px; max-width:58px; padding:5px 8px; color:#1d4ed8;
    background:#eff6ff; border:1px solid #bfdbfe; border-radius:6px; font-weight:700;
}
QPushButton#downloadRetry:hover { background:#dbeafe; }
"""


DOWNLOAD_CARD_DARK_STYLE = """
QFrame#downloadCard, QFrame#currentDownloadCard {
    background:#24272d; border:1px solid #3b414b; border-radius:8px;
}
QFrame#currentDownloadCard { background:#252b34; border-color:#4e7dbd; }
QLabel#downloadCover { background:#30343b; border:1px solid #414752; border-radius:6px; color:#aeb6c2; }
QLabel#downloadTitle { color:#edf0f4; font-size:13px; font-weight:800; }
QLabel#downloadSub { color:#aeb6c2; font-size:12px; }
QLabel#downloadTransfer { color:#c7ced8; font-size:12px; font-weight:700; }
QLabel#downloadStatus {
    background:#1d2b40; color:#7bb0ff; border:1px solid #365780;
    border-radius:9px; padding:2px 9px; font-size:12px; font-weight:700;
}
QProgressBar#downloadProgress {
    min-height:16px; max-height:16px; color:#e5e7eb; background:#191c21;
    border:1px solid #414752; border-radius:8px; text-align:center;
    font-size:11px; font-weight:700;
}
QProgressBar#downloadProgress::chunk { background:#3478f6; border-radius:7px; }
QPushButton#downloadCancel { color:#ff9aa7; background:#38262a; border:1px solid #6d3b44; border-radius:6px; }
QPushButton#downloadRetry { color:#7bb0ff; background:#1d2b40; border:1px solid #365780; border-radius:6px; }
"""


DOWNLOAD_DASHBOARD_DARK_STYLE = {
    "downloadActiveMetric": "color:#8db8ff; background:#1d2b40;",
    "downloadWaitingMetric": "color:#c7ced8; background:#30343b;",
    "downloadSpeedMetric": "color:#77d7b9; background:#17362f;",
}

DOWNLOAD_DASHBOARD_LIGHT_STYLE = {
    "downloadActiveMetric": "color:#1d4ed8; background:#eaf2ff;",
    "downloadWaitingMetric": "color:#58677a; background:#f0f3f7;",
    "downloadSpeedMetric": "color:#087f5b; background:#e6f7f0;",
}

DOWNLOAD_STATE_WAITING = "waiting"
DOWNLOAD_STATE_STARTING = "starting"
DOWNLOAD_STATE_DOWNLOADING = "downloading"
DOWNLOAD_STATE_PAUSED = "paused"
DOWNLOAD_STATE_FAILED = "failed"
DOWNLOAD_STATE_FINALIZING = "finalizing"


def _tinted_icon(source: QIcon, color: str, size: int) -> QIcon:
    source_pixmap = source.pixmap(size, size)
    pixmap = QPixmap(source_pixmap.size())
    pixmap.setDevicePixelRatio(source_pixmap.devicePixelRatio())
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.drawPixmap(0, 0, source_pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return QIcon(pixmap)


class DownloadPageMixin:
    def _build_download_panel(self: "MainWindow") -> QFrame:
        panel = self.load_ui_widget("download.ui", QFrame)

        def require(widget_type, object_name):
            widget = panel.findChild(widget_type, object_name)
            if widget is None:
                raise RuntimeError(f"Missing download control: {object_name}")
            return widget

        self.progress = require(QProgressBar, "downloadProgress")
        self.cancel_btn = require(QPushButton, "cancelDownloadsButton")
        self.queue_status_label = None
        self.queue_scroll = require(QScrollArea, "queueScroll")
        self.queue_cards_widget = require(QWidget, "queueCardsWidget")
        self.queue_cards_layout = require(QVBoxLayout, "queueCardsLayout")
        self.download_queue_stack = require(QStackedWidget, "downloadQueueStack")
        self.download_empty_title = require(QLabel, "downloadEmptyTitle")
        self.download_empty_hint = require(QLabel, "downloadEmptyHint")
        self.download_page_title = require(QLabel, "downloadPageTitle")
        self.download_page_title.setText("下载任务")
        self.completed_table = None
        self.log_box = None

        start_button = require(QPushButton, "startQueueButton")
        clear_button = require(QPushButton, "clearQueueButton")
        start_button.setText("开始 / 继续")
        clear_button.setText("清空等待")
        self.cancel_btn.setText("暂停全部")
        self.cancel_btn.clicked.connect(self.pause_all_downloads)
        start_button.clicked.connect(self.start_download_queue)
        clear_button.clicked.connect(self.clear_queue)
        for button, standard_icon, color in (
            (start_button, QStyle.StandardPixmap.SP_MediaPlay, "#ffffff"),
            (clear_button, QStyle.StandardPixmap.SP_TrashIcon, "#64748b"),
            (self.cancel_btn, QStyle.StandardPixmap.SP_BrowserStop, "#8a94a3"),
        ):
            button.setIcon(
                _tinted_icon(self.style().standardIcon(standard_icon), color, 16)
            )
            button.setIconSize(QSize(16, 16))

        header_layout = panel.findChild(QHBoxLayout, "downloadHeaderLayout")
        if header_layout is None:
            raise RuntimeError("download.ui is missing downloadHeaderLayout")
        self.download_active_metric = QLabel("下载中 0", panel)
        self.download_active_metric.setObjectName("downloadActiveMetric")
        self.download_waiting_metric = QLabel("等待 0", panel)
        self.download_waiting_metric.setObjectName("downloadWaitingMetric")
        self.download_speed_metric = QLabel("0 B/s", panel)
        self.download_speed_metric.setObjectName("downloadSpeedMetric")
        for metric in (
            self.download_active_metric,
            self.download_waiting_metric,
            self.download_speed_metric,
        ):
            metric.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_layout.addWidget(metric)

        icon_dir = resource_dir() / "nav_icons"

        for label_name, icon_name, size in (
            ("downloadHeaderIcon", "line_reading.svg", 19),
            ("downloadEmptyIcon", "line_reading.svg", 30),
        ):
            label = require(QLabel, label_name)
            label.setPixmap(
                _tinted_icon(QIcon(str(icon_dir / icon_name)), "#3478f6", size).pixmap(
                    size, size
                )
            )

        self.current_download_card = None
        self.current_download_progress = None
        self.current_download_status = None
        self.current_download_title = None
        self.current_download_sub = None
        self.current_download_cover = None
        self.current_download_cancel = None
        self.download_ui_progress = {}
        self.download_image_progress_by_id = {}
        self.download_start_scheduled = False
        self.download_task_state_by_id = {}
        self.download_paused_ids = set()
        self.download_scheduler_timer = QTimer(self)
        self.download_scheduler_timer.setInterval(350)
        self.download_scheduler_timer.timeout.connect(self.run_download_scheduler_tick)
        panel.setStyleSheet(DOWNLOAD_PAGE_STYLE)
        self.update_download_dashboard()
        self.update_download_page_stats()
        self.update_download_empty_state()
        return panel

    def visible_download_queue(self: "MainWindow"):
        # The queue only contains unfinished work; completed entries are
        # removed by ``remove_finished_album_from_queue``.
        return list(self.queue)

    def update_download_empty_state(self: "MainWindow") -> None:
        self.download_empty_title.setText("暂无进行中的任务")
        self.download_empty_hint.setText("添加漫画后，未完成的下载任务会显示在这里")

    def update_download_page_stats(self: "MainWindow") -> None:
        return None

    def download_task_state(self: "MainWindow", album_id: str) -> str:
        states = getattr(self, "download_task_state_by_id", {})
        return str(states.get(str(album_id), DOWNLOAD_STATE_WAITING))

    def set_download_task_state(self: "MainWindow", album_id: str, state: str) -> None:
        if not album_id:
            return
        states = getattr(self, "download_task_state_by_id", None)
        if states is None:
            states = {}
            self.download_task_state_by_id = states
        states[str(album_id)] = str(state)

    def clear_download_task_state(self: "MainWindow", album_id: str) -> None:
        states = getattr(self, "download_task_state_by_id", None)
        if isinstance(states, dict):
            states.pop(str(album_id), None)
        getattr(self, "download_paused_ids", set()).discard(str(album_id))

    @staticmethod
    def dashboard_speed_text(value: float) -> str:
        size = max(0.0, float(value or 0))
        units = ("B", "KB", "MB", "GB", "TB")
        unit_index = 0
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}/s"
        return f"{size:.1f} {units[unit_index]}/s"

    def update_download_dashboard(self: "MainWindow") -> None:
        """Refresh compact queue metrics without rebuilding task cards."""
        active = len(getattr(self, "download_workers", {}))
        queue = list(getattr(self, "queue", []))
        pending = list(getattr(self, "download_pending_queue", []))
        queued_ids = {str(getattr(album, "album_id", "")) for album in queue}
        queued_ids.update(str(getattr(album, "album_id", "")) for album in pending)
        queued_ids.discard("")
        states = getattr(self, "download_task_state_by_id", {})
        waiting = sum(
            1
            for album_id in queued_ids
            if str(states.get(album_id, DOWNLOAD_STATE_WAITING))
            == DOWNLOAD_STATE_WAITING
        )
        paused = sum(
            1
            for album_id in queued_ids
            if str(states.get(album_id, "")) == DOWNLOAD_STATE_PAUSED
        )
        failed = sum(
            1
            for album_id in queued_ids
            if str(states.get(album_id, "")) == DOWNLOAD_STATE_FAILED
        )
        speed = sum(float(value or 0) for value in getattr(self, "download_speeds", {}).values())
        active_label = getattr(self, "download_active_metric", None)
        waiting_label = getattr(self, "download_waiting_metric", None)
        speed_label = getattr(self, "download_speed_metric", None)
        if active_label is not None:
            active_label.setText(f"下载中 {active}")
        if waiting_label is not None:
            suffix = f" · 暂停 {paused}" if paused else ""
            suffix += f" · 失败 {failed}" if failed else ""
            waiting_label.setText(f"等待 {waiting}{suffix}")
        if speed_label is not None:
            speed_label.setText(self.dashboard_speed_text(speed))
        palette = (
            DOWNLOAD_DASHBOARD_DARK_STYLE
            if bool(getattr(self, "theme_dark", False))
            else DOWNLOAD_DASHBOARD_LIGHT_STYLE
        )
        for label in (active_label, waiting_label, speed_label):
            if label is not None:
                color = palette.get(label.objectName(), "")
                label.setStyleSheet(f"{color} border-radius:6px; padding:0 9px;")

    def start_download_scheduler(self: "MainWindow") -> None:
        timer = getattr(self, "download_scheduler_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()

    def stop_download_scheduler(self: "MainWindow") -> None:
        timer = getattr(self, "download_scheduler_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def run_download_scheduler_tick(self: "MainWindow") -> None:
        """JMComic-qt style slot replenishment, isolated from expensive UI work."""
        pending = getattr(self, "download_pending_queue", [])
        workers = getattr(self, "download_workers", {})
        if pending or workers:
            pump = getattr(self, "pump_download_workers", None)
            if callable(pump):
                pump()
        else:
            self.stop_download_scheduler()
        self.update_download_dashboard()

    def pause_all_downloads(self: "MainWindow") -> None:
        queue = list(getattr(self, "queue", []))
        pending = list(getattr(self, "download_pending_queue", []))
        workers = dict(getattr(self, "download_workers", {}))
        targets = {
            str(getattr(album, "album_id", ""))
            for album in queue + pending
            if str(getattr(album, "album_id", ""))
        }
        targets.update(str(album_id) for album_id in workers)
        if not targets:
            show_toast = getattr(self, "show_toast", None)
            if callable(show_toast):
                show_toast("当前没有可暂停的下载任务")
            return
        self.download_pending_queue = []
        paused_ids = getattr(self, "download_paused_ids", set())
        self.download_paused_ids = paused_ids
        controller = getattr(self, "download_controller", None)
        for album_id in targets:
            self.set_download_task_state(album_id, DOWNLOAD_STATE_PAUSED)
            paused_ids.add(album_id)
            worker = workers.get(album_id)
            if worker is not None and worker.isRunning() and controller is not None:
                controller.pause(album_id)
            if controller is not None:
                try:
                    from ...models import DownloadState

                    controller.update_progress(album_id, DownloadState.PAUSED)
                except Exception:
                    pass
            self.sync_download_card_actions(album_id)
        self.stop_download_scheduler()
        cancel_button = getattr(self, "cancel_btn", None)
        if cancel_button is not None:
            cancel_button.setEnabled(False)
        refresh = getattr(self, "refresh_queue_table", None)
        if callable(refresh):
            refresh()
        summary = getattr(self, "update_download_summary", None)
        if callable(summary):
            summary()
        self.update_download_dashboard()

    def pause_download_album(self: "MainWindow", album_id: str) -> None:
        workers = getattr(self, "download_workers", {})
        worker = workers.get(album_id)
        if worker is None or not worker.isRunning():
            return
        self.download_pending_queue = [
            album for album in getattr(self, "download_pending_queue", [])
            if str(getattr(album, "album_id", "")) != str(album_id)
        ]
        self.set_download_task_state(album_id, DOWNLOAD_STATE_PAUSED)
        self.download_paused_ids.add(str(album_id))
        controller = getattr(self, "download_controller", None)
        if controller is not None:
            controller.pause(album_id)
        self.sync_download_card_actions(album_id)
        self.update_download_dashboard()

    def request_download_card_cancel(self: "MainWindow", album_id: str) -> None:
        state = self.download_task_state(album_id)
        if state in {
            DOWNLOAD_STATE_STARTING,
            DOWNLOAD_STATE_DOWNLOADING,
            DOWNLOAD_STATE_FINALIZING,
        }:
            self.pause_download_album(album_id)
            return
        cancel = getattr(self, "cancel_album_download", None)
        if callable(cancel):
            cancel(album_id)

    def sync_download_card_actions(
        self: "MainWindow", album_id: str, card: Optional[QFrame] = None
    ) -> None:
        card = card or getattr(self, "download_card_by_id", {}).get(album_id)
        if card is None:
            return
        state = self.download_task_state(album_id)
        active = state in {
            DOWNLOAD_STATE_STARTING,
            DOWNLOAD_STATE_DOWNLOADING,
            DOWNLOAD_STATE_FINALIZING,
        }
        card.setObjectName("currentDownloadCard" if active else "downloadCard")
        card.setStyleSheet(self.download_card_style())
        retry = card.findChild(QPushButton, "downloadRetry")
        cancel = card.findChild(QPushButton, "downloadCancel")
        if retry is not None:
            retry.setText("继续" if state == DOWNLOAD_STATE_PAUSED else "重试")
            retry.setEnabled(state in {DOWNLOAD_STATE_PAUSED, DOWNLOAD_STATE_FAILED})
        if cancel is not None:
            cancel.setText("暂停" if active else "移除")
            cancel.setEnabled(state not in {DOWNLOAD_STATE_FINALIZING})

    def queue_automatic_download(self: "MainWindow", album) -> None:
        """Put a newly added album into the worker queue and coalesce startup."""
        album_id = str(album.album_id)
        active_ids = set(getattr(self, "download_workers", {}))
        pending_ids = {
            str(item.album_id) for item in getattr(self, "download_pending_queue", [])
        }
        if album_id not in active_ids and album_id not in pending_ids:
            self.download_pending_queue.append(copy.deepcopy(album))
            self.set_download_task_state(album_id, DOWNLOAD_STATE_WAITING)
            self.download_paused_ids.discard(album_id)
        self.start_download_scheduler()
        self.update_download_dashboard()
        if getattr(self, "download_start_scheduled", False):
            return
        self.download_start_scheduled = True
        QTimer.singleShot(0, self.start_scheduled_download_queue)

    def start_scheduled_download_queue(self: "MainWindow") -> None:
        self.download_start_scheduled = False
        if self.download_pending_queue or self.queue:
            self.start_download_queue()

    def queue_download_progress_refresh(
        self: "MainWindow", album, done: int, total: int, *, immediate: bool = False
    ) -> None:
        """Coalesce per-image callbacks into a stable UI refresh cadence."""
        album_id = str(album.album_id)
        self.download_ui_progress[album_id] = (
            album,
            max(0, int(done)),
            max(1, int(total)),
        )
        self.download_image_progress_by_id[album_id] = (
            max(0, int(done)),
            max(1, int(total)),
        )
        if immediate:
            self.flush_queued_download_progress(album_id)
            return
        if album_id in self.download_progress_pending:
            return
        self.download_progress_pending.add(album_id)
        QTimer.singleShot(
            250,
            lambda album_id=album_id: self.flush_queued_download_progress(album_id),
        )

    def flush_queued_download_progress(self: "MainWindow", album_id: str) -> None:
        self.download_progress_pending.discard(album_id)
        payload = self.download_ui_progress.pop(album_id, None)
        if payload is None or album_id in self.download_cancelled_ids:
            return
        album, image_done, image_total = payload
        image_done = min(image_done, image_total)
        self.download_controller.update_progress(
            album_id,
            self.download_state_downloading(),
            total_images=image_total,
            done_images=image_done,
        )

        chapter_total = max(
            1,
            self.download_chapter_totals.get(
                album_id, self.queue_chapter_count(album)
            ),
        )
        chapter_done = min(
            chapter_total, self.download_chapter_done_counts.get(album_id, 0)
        )
        if chapter_total > 1:
            progress_done, progress_total = chapter_done, chapter_total
            progress_text = (
                f"章节 {chapter_done}/{chapter_total} · "
                f"{self.download_percent(chapter_done, chapter_total)}%"
            )
            sub_text = f"ID：{album_id}    当前图片：{image_done} / {image_total}"
        else:
            previous_total = self.download_totals.get(album_id, 1)
            previous_done = self.download_done_counts.get(album_id, 0)
            progress_total = max(previous_total, image_total)
            progress_done = max(previous_done, min(image_done, progress_total))
            self.download_totals[album_id] = progress_total
            self.download_done_counts[album_id] = progress_done
            progress_text = (
                f"图片 {progress_done}/{progress_total} · "
                f"{self.download_percent(progress_done, progress_total)}%"
            )
            sub_text = f"ID：{album_id}    单章节下载"

        card = self.download_card_by_id.get(album_id)
        if card is not None:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            sub = card.findChild(QLabel, "downloadSub")
            if status is not None:
                status.setText("下载中")
            if progress is not None:
                self.set_download_card_progress(
                    progress, progress_done, progress_total, progress_text
                )
            if sub is not None:
                sub.setText(sub_text)
                sub.setToolTip(sub_text)
        self.update_download_summary()

    @staticmethod
    def download_state_downloading():
        from ...models import DownloadState

        return DownloadState.DOWNLOADING

    def download_card_style(self: "MainWindow") -> str:
        return DOWNLOAD_CARD_DARK_STYLE if bool(getattr(self, "theme_dark", False)) else DOWNLOAD_CARD_LIGHT_STYLE

    def refresh_download_card_theme(self: "MainWindow") -> None:
        style = self.download_card_style()
        for card in list(getattr(self, "download_card_by_id", {}).values()):
            try:
                card.setStyleSheet(style)
            except RuntimeError:
                pass
        self.update_download_dashboard()
