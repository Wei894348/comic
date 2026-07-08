import copy
import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from PyQt5.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSequentialAnimationGroup,
    QSize,
    QThread,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt5.QtGui import QDesktopServices, QFontMetrics, QImageReader, QKeySequence, QMovie, QPixmap
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QButtonGroup,
    QApplication,
    QPlainTextEdit,
    QProgressBar,
    QGraphicsOpacityEffect,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QShortcut,
)

from .app_icon import APP_DISPLAY_NAME, app_icon
from ..backend.constants import DEFAULT_USER_AGENT, LIST_URL
from ..backend.cookie_store import load_cookie_header, save_cookie_dict
from ..backend.cache_db import ComicCacheDB
from ..backend.jm_api import API_DOMAINS, APP_USER_AGENT, APP_VERSION, IMAGE_DOMAINS, get_latest_api_domains
from ..backend.jmcomic_defaults import jmcomic_default_cookie_header
from ..backend.models import AlbumMeta, ChapterMeta, DownloadConfig, NetworkConfig
from .hd_reader import HdMangaReaderWindow, collect_reader_files
from ..backend.pdf_utils import IMAGE_SUFFIXES, collect_images
from ..backend.runtime_paths import app_data_dir, downloads_dir, reader_cache_dir, ui_cache_path
from ..backend.utils import parse_cookie_header, split_ids
from ..backend.workers import ChapterWorker, DownloadWorker, IncrementalUpdateWorker, ReaderWorker, ScrapeWorker


BLUE = "#1976d2"
LIGHT_BLUE = "#e8f2ff"
TEXT = "#1f2937"
RESULT_ROWS = 2
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
LOADING_MOVIE_PATH = ASSETS_DIR / "loading_runner.gif"
APP_UI_VERSION = "1.0.1"


def elide_label_text(label: QLabel, text: str, fallback_width: int = 220) -> None:
    full_text = text or "-"
    width = max(40, label.width() or label.maximumWidth() or fallback_width)
    metrics = QFontMetrics(label.font())
    label.setText(metrics.elidedText(full_text, Qt.ElideRight, width))
    label.setToolTip(full_text)


class ReaderDialog(QDialog):
    def __init__(self, album: AlbumMeta, chapter: ChapterMeta, config: DownloadConfig, log_callback, parent=None):
        super().__init__(parent)
        self.album = album
        self.chapter = chapter
        self.log_callback = log_callback
        self.config = config
        self.worker: Optional[ReaderWorker] = None
        self.stale_workers: List[ReaderWorker] = []
        self._closing = False
        self._force_close = False
        self.page_labels: Dict[int, QLabel] = {}
        self.page_pixmaps: Dict[int, QPixmap] = {}
        self.reader_total = 0
        self.current_reader_page = 0
        self._switching_chapter = False
        self.reader_scale_mode = "fit_width"
        self.reader_mode = getattr(config, "reading_mode", "scroll") or "scroll"
        self.setWindowTitle(f"阅读 - {album.title}")
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(760, 820)
        self.setMinimumSize(520, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.chapter_combo = QComboBox()
        self.chapter_combo.setMinimumWidth(190)
        self.chapter_combo.setMaximumWidth(360)
        self.chapter_combo.setMinimumContentsLength(16)
        self.chapter_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for item in album.chapters:
            self.chapter_combo.addItem(f"{item.index}. {item.title}", item.chapter_id)
        current_index = self.chapter_index(chapter.chapter_id)
        if current_index >= 0:
            self.chapter_combo.setCurrentIndex(current_index)
        self.chapter_combo.currentIndexChanged.connect(self.on_chapter_combo_changed)
        self.title_label = QLabel(album.title)
        self.title_label.setWordWrap(False)
        self.title_label.setMinimumWidth(120)
        self.title_label.setMaximumWidth(320)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.title_label.setToolTip(album.title)
        self.title_label.setStyleSheet("font-weight:700;color:#1f2937;")
        self.page_indicator = QLabel("第 0 / 0 页")
        self.page_indicator.setMinimumWidth(92)
        self.page_indicator.setStyleSheet("color:#334155;font-weight:700;padding:0 8px;")
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("原始大小", "original")
        self.scale_combo.addItem("适应宽度", "fit_width")
        self.scale_combo.setCurrentIndex(1)
        self.scale_combo.setMaximumWidth(120)
        self.scale_combo.currentIndexChanged.connect(self.on_scale_mode_changed)
        self.prev_page_btn = QPushButton("上一页")
        self.prev_page_btn.clicked.connect(lambda: self.flip_reader_page(-1))
        self.next_page_btn = QPushButton("下一页")
        self.next_page_btn.clicked.connect(lambda: self.flip_reader_page(1))
        self.next_chapter_btn = QPushButton("下一章")
        self.next_chapter_btn.clicked.connect(self.open_next_chapter)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        header.addWidget(self.chapter_combo)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.page_indicator)
        header.addWidget(self.scale_combo)
        header.addWidget(self.prev_page_btn)
        header.addWidget(self.next_page_btn)
        header.addWidget(self.next_chapter_btn)
        header.addWidget(self.progress)
        layout.addLayout(header)
        self.update_reader_header_text()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.verticalScrollBar().valueChanged.connect(self.update_current_reader_page)
        self.page = QWidget()
        self.page_layout = QVBoxLayout(self.page)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        self.page_layout.setSpacing(0)
        self.loading_label = QLabel("正在准备章节...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("color:#64748b;padding:24px;")
        self.page_layout.addWidget(self.loading_label)
        self.page_layout.addStretch()
        self.scroll.setWidget(self.page)
        layout.addWidget(self.scroll, 1)

        self.start_reader_worker(chapter)
        self.apply_reader_mode()

    def chapter_index(self, chapter_id: str) -> int:
        for index, item in enumerate(self.album.chapters):
            if item.chapter_id == chapter_id:
                return index
        return -1

    def current_chapter_index(self) -> int:
        return self.chapter_index(self.chapter.chapter_id)

    def update_reader_header_text(self):
        elide_label_text(self.title_label, self.album.title, 260)
        index = self.current_chapter_index()
        if 0 <= index < len(self.album.chapters):
            chapter = self.album.chapters[index]
            self.chapter_combo.setToolTip(f"{chapter.index}. {chapter.title}")

    def start_reader_worker(self, chapter: ChapterMeta):
        self.chapter = chapter
        self.setWindowTitle(f"阅读 - {self.album.title} / {chapter.title}")
        self.update_reader_header_text()
        self.reset_reader_pages()
        worker = ReaderWorker(self.album, chapter, self.config, self)
        self.worker = worker
        worker.image_ready.connect(lambda index, path, worker=worker: self.add_image(index, path) if worker is self.worker else None)
        worker.progress.connect(lambda done, total, worker=worker: self.on_progress(done, total) if worker is self.worker else None)
        worker.log.connect(lambda message, worker=worker: self.log_callback(message) if worker is self.worker else None)
        worker.failed.connect(lambda message, worker=worker: self.on_failed(message) if worker is self.worker else None)
        worker.finished_ok.connect(lambda worker=worker: self.on_finished() if worker is self.worker else None)
        worker.finished.connect(lambda worker=worker: self.on_worker_finished(worker))
        self.update_current_reader_page()
        worker.start()

    def reset_reader_pages(self):
        self.page_labels.clear()
        self.page_pixmaps.clear()
        self.reader_total = 0
        self.current_reader_page = 0
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.loading_label = QLabel("正在准备章节...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("color:#64748b;padding:24px;")
        self.page_layout.addWidget(self.loading_label)
        self.page_layout.addStretch()
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        self.progress.setFormat("")
        self.scroll.verticalScrollBar().setValue(0)
        self.apply_reader_mode()
        self.update_page_indicator()

    def on_chapter_combo_changed(self, index: int):
        if self._switching_chapter or index < 0 or index >= len(self.album.chapters):
            return
        self.switch_to_chapter(index)

    def switch_to_chapter(self, index: int):
        if index < 0 or index >= len(self.album.chapters):
            return
        chapter = self.album.chapters[index]
        if chapter.chapter_id == self.chapter.chapter_id:
            return
        old_worker = self.worker
        if old_worker and old_worker.isRunning():
            old_worker.cancel()
            self.stale_workers.append(old_worker)
            old_worker.finished.connect(lambda worker=old_worker: self.forget_stale_worker(worker))
        self._switching_chapter = True
        self.chapter_combo.setCurrentIndex(index)
        self._switching_chapter = False
        self.start_reader_worker(chapter)

    def open_next_chapter(self):
        index = self.current_chapter_index()
        if index >= 0 and index + 1 < len(self.album.chapters):
            self.switch_to_chapter(index + 1)

    def on_scale_mode_changed(self):
        self.reader_scale_mode = self.scale_combo.currentData() or "original"
        self.rescale_reader_pages()

    def apply_reader_mode(self):
        page_mode = self.reader_mode == "page"
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if page_mode else Qt.ScrollBarAsNeeded)
        self.prev_page_btn.setVisible(page_mode)
        self.next_page_btn.setVisible(page_mode)
        if page_mode and self.reader_total and self.current_reader_page <= 0:
            self.current_reader_page = 1
        for index, label in list(self.page_labels.items()):
            try:
                label.setVisible(not page_mode or index == self.current_reader_page)
            except RuntimeError:
                pass
        self.update_page_indicator()

    def flip_reader_page(self, direction: int):
        if self.reader_mode != "page" or self.reader_total <= 0:
            return
        self.current_reader_page = max(1, min(self.reader_total, (self.current_reader_page or 1) + direction))
        self.apply_reader_mode()
        self.scroll.verticalScrollBar().setValue(0)

    def forget_stale_worker(self, worker: ReaderWorker):
        if worker in self.stale_workers:
            self.stale_workers.remove(worker)

    def add_image(self, index: int, image_path: str):
        if self._closing:
            return
        label = self.page_labels.get(index)
        if label is None:
            label = self.create_reader_page_label(index)
            insert_at = max(0, self.page_layout.count() - 1)
            self.page_layout.insertWidget(insert_at, label)
            self.page_labels[index] = label
        reader = QImageReader(image_path)
        reader.setAutoTransform(True)
        pixmap = QPixmap.fromImage(reader.read())
        if pixmap.isNull():
            label.setText(f"第 {index} 页加载失败")
        else:
            self.page_pixmaps[index] = pixmap
            label.setText("")
            label.setStyleSheet("background:white;border:none;padding:0;margin:0;")
            self.apply_reader_pixmap(index)
            self.apply_reader_mode()
            self.update_current_reader_page()

    def on_progress(self, done: int, total: int):
        if self._closing:
            return
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        if total and total != self.reader_total:
            self.prepare_placeholders(total)
        self.update_page_indicator()

    def prepare_placeholders(self, total: int):
        self.reader_total = total
        if self.loading_label:
            self.page_layout.removeWidget(self.loading_label)
            self.loading_label.deleteLater()
            self.loading_label = None
        for index in range(1, total + 1):
            if index in self.page_labels:
                continue
            label = self.create_reader_page_label(index)
            insert_at = max(0, self.page_layout.count() - 1)
            self.page_layout.insertWidget(insert_at, label)
            self.page_labels[index] = label
        self.apply_reader_mode()

    @staticmethod
    def create_reader_page_label(index: int) -> QLabel:
        label = QLabel(f"第 {index} 页后台下载中...")
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumHeight(120)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        label.setStyleSheet(
            "background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;color:#64748b;padding:18px;"
        )
        return label

    def apply_reader_pixmap(self, index: int):
        label = self.page_labels.get(index)
        pixmap = self.page_pixmaps.get(index)
        if label is None or pixmap is None or pixmap.isNull():
            return
        max_width = max(320, self.scroll.viewport().width() - 18)
        if self.reader_scale_mode == "original":
            display = pixmap
        else:
            target_width = min(max_width, pixmap.width())
            display = pixmap if target_width >= pixmap.width() else pixmap.scaledToWidth(target_width, Qt.SmoothTransformation)
        label.setMinimumSize(display.size())
        label.resize(display.size())
        label.setPixmap(display)
        label.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.rescale_reader_pages)
        QTimer.singleShot(0, self.update_reader_header_text)

    def rescale_reader_pages(self):
        if self._closing:
            return
        for index in list(self.page_pixmaps):
            self.apply_reader_pixmap(index)
        self.update_current_reader_page()

    def update_current_reader_page(self):
        if self._closing:
            return
        if self.reader_mode == "page":
            if self.reader_total and self.current_reader_page <= 0:
                self.current_reader_page = 1
            self.update_page_indicator()
            return
        if not self.page_labels:
            self.current_reader_page = 0
            self.update_page_indicator()
            return
        scrollbar = self.scroll.verticalScrollBar()
        center_y = scrollbar.value() + max(1, self.scroll.viewport().height() // 2)
        selected = 1
        best_distance = None
        for index, label in sorted(self.page_labels.items()):
            try:
                top = label.y()
                bottom = top + max(1, label.height())
            except RuntimeError:
                continue
            if top <= center_y <= bottom:
                selected = index
                break
            distance = min(abs(center_y - top), abs(center_y - bottom))
            if best_distance is None or distance < best_distance:
                best_distance = distance
                selected = index
        self.current_reader_page = min(max(1, selected), max(1, self.reader_total or selected))
        self.update_page_indicator()

    def update_page_indicator(self):
        total = self.reader_total
        current = self.current_reader_page if total else 0
        self.page_indicator.setText(f"第 {current} / {total} 页")
        chapter_index = self.current_chapter_index()
        has_next = chapter_index >= 0 and chapter_index + 1 < len(self.album.chapters)
        self.next_chapter_btn.setEnabled(bool(has_next and total and current >= total))
        if hasattr(self, "prev_page_btn"):
            page_mode = self.reader_mode == "page"
            self.prev_page_btn.setEnabled(bool(page_mode and total and current > 1))
            self.next_page_btn.setEnabled(bool(page_mode and total and current < total))

    def on_failed(self, message: str):
        if self._closing:
            return
        QMessageBox.warning(self, "阅读加载失败", message)

    def on_finished(self):
        self.progress.setFormat("加载完成")
        self.update_current_reader_page()

    def closeEvent(self, event):
        if self._force_close:
            super().closeEvent(event)
            return
        if self.worker and self.worker.isRunning():
            event.ignore()
            self._closing = True
            self.hide()
            self.worker.cancel()
            for worker in list(self.stale_workers):
                if worker.isRunning():
                    worker.cancel()
            return
        super().closeEvent(event)

    def on_worker_finished(self, worker=None):
        if worker is not None and worker is not self.worker and not self._closing:
            return
        if self._closing:
            self._force_close = True
            self.close()


class LocalImageReaderDialog(QDialog):
    def __init__(self, title: str, image_paths: List[Path], reading_mode: str = "scroll", parent=None):
        super().__init__(parent)
        self.image_paths = image_paths
        self.page_labels: Dict[int, QLabel] = {}
        self.page_pixmaps: Dict[int, QPixmap] = {}
        self.current_page = 0
        self.scale_mode = "fit_width"
        self.reading_mode = reading_mode or "scroll"
        self.load_index = 0
        self._closing = False
        self.setWindowTitle(f"本地阅读 - {title}")
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(860, 820)
        self.setMinimumSize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.local_title = title
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(False)
        self.title_label.setMinimumWidth(140)
        self.title_label.setMaximumWidth(420)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.title_label.setStyleSheet("font-weight:700;color:#1f2937;")
        self.page_indicator = QLabel(f"第 0 / {len(image_paths)} 页")
        self.page_indicator.setMinimumWidth(92)
        self.page_indicator.setStyleSheet("color:#334155;font-weight:700;padding:0 8px;")
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("原始大小", "original")
        self.scale_combo.addItem("适应宽度", "fit_width")
        self.scale_combo.setCurrentIndex(1)
        self.scale_combo.setMaximumWidth(120)
        self.scale_combo.currentIndexChanged.connect(self.on_scale_mode_changed)
        self.prev_page_btn = QPushButton("上一页")
        self.prev_page_btn.clicked.connect(lambda: self.flip_page(-1))
        self.next_page_btn = QPushButton("下一页")
        self.next_page_btn.clicked.connect(lambda: self.flip_page(1))
        header.addWidget(self.title_label, 1)
        header.addWidget(self.page_indicator)
        header.addWidget(self.scale_combo)
        header.addWidget(self.prev_page_btn)
        header.addWidget(self.next_page_btn)
        layout.addLayout(header)
        self.update_header_title()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if self.reading_mode == "page" else Qt.ScrollBarAsNeeded)
        self.scroll.verticalScrollBar().valueChanged.connect(self.update_current_page)
        self.page = QWidget()
        self.page_layout = QVBoxLayout(self.page)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        self.page_layout.setSpacing(0)
        for index, path in enumerate(image_paths, start=1):
            label = QLabel(f"第 {index} 页：{path.name}")
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(120)
            label.setStyleSheet(
                "background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;color:#64748b;padding:18px;"
            )
            self.page_layout.addWidget(label)
            self.page_labels[index] = label
        self.page_layout.addStretch()
        self.scroll.setWidget(self.page)
        layout.addWidget(self.scroll, 1)

        QTimer.singleShot(0, self.load_next_image)
        self.apply_reading_mode()

    def load_next_image(self):
        if self._closing:
            return
        if self.load_index >= len(self.image_paths):
            self.update_current_page()
            return
        index = self.load_index + 1
        path = self.image_paths[self.load_index]
        label = self.page_labels.get(index)
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        pixmap = QPixmap.fromImage(reader.read())
        if label is not None:
            if pixmap.isNull():
                label.setText(f"第 {index} 页加载失败")
            else:
                self.page_pixmaps[index] = pixmap
                label.setText("")
                label.setStyleSheet("background:white;border:none;padding:0;margin:0;")
                self.apply_pixmap(index)
                self.apply_reading_mode()
        self.load_index += 1
        if not self._closing:
            QTimer.singleShot(1, self.load_next_image)

    def on_scale_mode_changed(self):
        self.scale_mode = self.scale_combo.currentData() or "original"
        for index in list(self.page_pixmaps):
            self.apply_pixmap(index)
        self.update_current_page()

    def apply_reading_mode(self):
        page_mode = self.reading_mode == "page"
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if page_mode else Qt.ScrollBarAsNeeded)
        self.prev_page_btn.setVisible(page_mode)
        self.next_page_btn.setVisible(page_mode)
        if page_mode and self.image_paths and self.current_page <= 0:
            self.current_page = 1
        for index, label in list(self.page_labels.items()):
            try:
                label.setVisible(not page_mode or index == self.current_page)
            except RuntimeError:
                pass
        self.update_page_buttons()

    def flip_page(self, direction: int):
        if self.reading_mode != "page" or not self.image_paths:
            return
        self.current_page = max(1, min(len(self.image_paths), (self.current_page or 1) + direction))
        self.apply_reading_mode()
        self.scroll.verticalScrollBar().setValue(0)

    def apply_pixmap(self, index: int):
        label = self.page_labels.get(index)
        pixmap = self.page_pixmaps.get(index)
        if label is None or pixmap is None or pixmap.isNull():
            return
        if self.scale_mode == "original":
            display = pixmap
        else:
            target_width = min(max(320, self.scroll.viewport().width() - 18), pixmap.width())
            display = pixmap if target_width >= pixmap.width() else pixmap.scaledToWidth(target_width, Qt.SmoothTransformation)
        label.setMinimumSize(display.size())
        label.resize(display.size())
        label.setPixmap(display)
        label.adjustSize()

    def update_header_title(self):
        elide_label_text(self.title_label, self.local_title, 340)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.update_header_title)
        if self.scale_mode == "fit_width":
            QTimer.singleShot(0, self.on_scale_mode_changed)

    def update_current_page(self):
        if self._closing:
            return
        if self.reading_mode == "page":
            if self.image_paths and self.current_page <= 0:
                self.current_page = 1
            self.page_indicator.setText(f"第 {self.current_page} / {len(self.image_paths)} 页")
            self.update_page_buttons()
            return
        if not self.page_labels:
            self.current_page = 0
            self.page_indicator.setText(f"第 0 / {len(self.image_paths)} 页")
            return
        scrollbar = self.scroll.verticalScrollBar()
        center_y = scrollbar.value() + max(1, self.scroll.viewport().height() // 2)
        selected = 1
        best_distance = None
        for index, label in sorted(self.page_labels.items()):
            try:
                top = label.y()
                bottom = top + max(1, label.height())
            except RuntimeError:
                continue
            if top <= center_y <= bottom:
                selected = index
                break
            distance = min(abs(center_y - top), abs(center_y - bottom))
            if best_distance is None or distance < best_distance:
                best_distance = distance
                selected = index
        self.current_page = min(max(1, selected), max(1, len(self.image_paths)))
        self.page_indicator.setText(f"第 {self.current_page} / {len(self.image_paths)} 页")
        self.update_page_buttons()

    def update_page_buttons(self):
        page_mode = self.reading_mode == "page"
        total = len(self.image_paths)
        self.prev_page_btn.setEnabled(bool(page_mode and total and self.current_page > 1))
        self.next_page_btn.setEnabled(bool(page_mode and total and self.current_page < total))

    def closeEvent(self, event):
        self._closing = True
        super().closeEvent(event)


class DetailDialog(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMaximumSize(760, 920)

    def closeEvent(self, event):
        self.hide()
        self.closed.emit()
        event.ignore()


class DomainRefreshWorker(QThread):
    domains_ready = pyqtSignal(object)
    log = pyqtSignal(str)

    def run(self):
        try:
            domains = get_latest_api_domains(self.log.emit, force=True)
            self.domains_ready.emit(domains)
        except Exception as exc:
            self.log.emit(f"域名池更新失败：{exc}")


class CoverFetchWorker(QThread):
    loaded = pyqtSignal(str, object, str, object)
    failed = pyqtSignal(str, str, object)

    def __init__(self, album_id: str, urls: List[str], proxy: str = "", referer_domain: str = "", parent=None):
        super().__init__(parent)
        self.album_id = album_id
        self.urls = urls
        self.proxy = proxy.strip()
        self.referer_domain = referer_domain or API_DOMAINS[0]

    def run(self):
        headers = {
            "User-Agent": APP_USER_AGENT,
            "Referer": f"https://{self.referer_domain}/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        failed_urls = []
        last_error = ""
        session = requests.Session()
        session.trust_env = False
        for url in self.urls:
            try:
                response = session.get(url, headers=headers, proxies=proxies, timeout=(5, 12))
                response.raise_for_status()
                if not response.content:
                    raise RuntimeError("封面为空")
                self.loaded.emit(self.album_id, response.content, url, failed_urls)
                return
            except Exception as exc:
                failed_urls.append(url)
                last_error = str(exc)
        self.failed.emit(self.album_id, last_error or "封面请求失败", failed_urls)


class CacheRestoreWorker(QThread):
    loaded = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, cache_key: str, albums: List[AlbumMeta], parent=None):
        super().__init__(parent)
        self.cache_key = cache_key
        self.albums = [copy.deepcopy(album) for album in albums]

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            self.loaded.emit(self.cache_key, self.albums)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            self.failed.emit(self.cache_key, str(exc))


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
        from PyQt5.QtGui import QColor

        return QColor(15, 23, 42, alpha)


class MainWindow(QMainWindow):
    async_log = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setWindowIcon(app_icon())
        self.resize(360, 500)
        self.setMinimumSize(330, 460)
        self.albums: Dict[str, AlbumMeta] = {}
        self.row_by_id: Dict[str, int] = {}
        self.result_albums: List[Optional[AlbumMeta]] = []
        self.result_total_count = 0
        self.current_result_page = 1
        self.results_revealed = False
        self.result_render_pending = False
        self.result_page_switching = False
        self.result_render_generation = 0
        self.result_resize_pending = False
        self.loaded_source_pages = 0
        self.auto_loading_next_page = False
        self.auto_load_has_more = True
        self.append_start_index = 0
        self.current_result_cache_key = ""
        self.force_network_once = False
        self.data_root = app_data_dir()
        self.default_output_dir = downloads_dir()
        self.cache_file = ui_cache_path()
        self.comic_db = ComicCacheDB()
        self.result_cache: Dict[str, List[AlbumMeta]] = {}
        self.detail_cache: Dict[str, AlbumMeta] = {}
        self.download_history: List[Dict[str, str]] = []
        self.settings_cache: Dict[str, object] = {}
        self._applying_settings = False
        self.api_domain_pool: List[str] = list(API_DOMAINS)
        self.cover_domain_pool: List[str] = list(IMAGE_DOMAINS)
        self.cover_domain_failures: Dict[str, int] = {}
        self.card_by_id: Dict[str, QFrame] = {}
        self.checkmark_by_id: Dict[str, QLabel] = {}
        self.card_click_timers: Dict[str, QTimer] = {}
        self.selected_album_ids = set()
        self.cover_targets: Dict[str, List[QLabel]] = {}
        self.cover_pending = set()
        self.cover_fallback_urls: Dict[str, List[str]] = {}
        self.cover_workers: Dict[str, CoverFetchWorker] = {}
        self.queue: List[AlbumMeta] = []
        self.download_pending_queue: List[AlbumMeta] = []
        self.completed: List[str] = []
        self.download_card_by_id: Dict[str, QFrame] = {}
        self.download_workers: Dict[str, DownloadWorker] = {}
        self.download_totals: Dict[str, int] = {}
        self.download_done_counts: Dict[str, int] = {}
        self.download_percent_by_id: Dict[str, int] = {}
        self.last_global_download_percent = 0
        self.download_progress_pending = set()
        self.download_transfer_pending = set()
        self.download_bytes: Dict[str, int] = {}
        self.download_speeds: Dict[str, float] = {}
        self.download_cancelled_ids = set()
        self.history_card_by_index: Dict[int, QFrame] = {}
        self.selected_history_index = -1
        self.current_download_album_id = ""
        self.current_album_id = ""
        self.session_username = ""
        self.session_password = ""
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
        self.log_flush_timer = QTimer(self)
        self.log_flush_timer.setSingleShot(True)
        self.log_flush_timer.timeout.connect(self.flush_logs)
        self.pending_log_messages: List[str] = []
        self.loading_tick = 0
        self.page_animation: Optional[QPropertyAnimation] = None
        self.active_animations = []
        self.drag_position = None
        self.home_auto_loaded = False
        self.cover_cache: Dict[str, QPixmap] = {}
        self.cover_manager = QNetworkAccessManager(self)
        self.pending_rank_request = ""
        self.active_category = ""
        self.cache_restore_worker: Optional[CacheRestoreWorker] = None
        self.cache_restore_miss_keys = set()
        self.db_write_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="comic18-db")
        self.async_log.connect(self.log)
        self.load_local_cache()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.login_page = self._build_login_page()
        self.app_page = self._build_app_page()
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.app_page)
        self.stack.setCurrentWidget(self.login_page)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self._apply_style()
        self.setup_shortcuts()
        self._center_window()

    def _apply_style(self):
        self.setStyleSheet(
            f"""
            QMainWindow {{ background: #f6f8fb; }}
            QWidget#appRoot {{ background: #f6f8fb; }}
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
            QFrame#dashboardHeader {{
                background: white;
                border: 1px solid #e4eaf3;
                border-radius: 8px;
            }}
            QFrame#panel {{
                background: white;
                border: 1px solid #dfe7f2;
                border-radius: 8px;
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
            QScrollBar:vertical, QScrollBar:horizontal {{
                background:transparent;
                border:0;
                width:10px;
                height:10px;
            }}
            QScrollBar::handle {{
                background:#b7c3d4;
                border-radius:5px;
                min-height:42px;
                min-width:42px;
            }}
            QScrollBar::handle:hover {{ background:#74869e; }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                width:0;
                height:0;
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
            QPushButton#navButton {{
                border: none;
                border-radius: 8px;
                padding: 12px 8px;
                text-align: center;
                background: transparent;
                color: #5b6b82;
                font-weight: 700;
            }}
            QPushButton#navButton:hover {{
                background: #eef4fb;
                color: #1d4ed8;
            }}
            QPushButton#navButton:checked {{
                background: {BLUE};
                color: white;
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

    def _build_login_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QFrame()
        self.login_header = header
        header.installEventFilter(self)
        header.setFixedHeight(128)
        header.setStyleSheet(f"background:{BLUE};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 0, 24, 0)
        title = QLabel(APP_DISPLAY_NAME)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color:white;font-size:22px;font-weight:700;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        header_layout.addStretch()
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(26, 24, 26, 26)
        body_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        card = QFrame()
        card.setObjectName("loginCard")
        card.setMinimumWidth(300)
        card.setMaximumWidth(430)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form = QFormLayout(card)
        form.setContentsMargins(22, 24, 22, 20)
        form.setSpacing(10)

        self.login_user_edit = QLineEdit()
        self.login_user_edit.setPlaceholderText("账号")
        self.login_user_edit.setMinimumHeight(36)
        self.login_pass_edit = QLineEdit()
        self.login_pass_edit.setEchoMode(QLineEdit.Password)
        self.login_pass_edit.setPlaceholderText("密码")
        self.login_pass_edit.setMinimumHeight(36)
        self.login_cookie_edit = QTextEdit()
        self.login_cookie_edit.setFixedHeight(58)
        self.login_cookie_edit.setPlainText(load_cookie_header() or jmcomic_default_cookie_header())
        self.login_cookie_edit.setPlaceholderText("可选但推荐：粘贴浏览器 Cookie，用于通过已验证会话访问")
        self.login_cookie_edit.hide()
        self.login_ua_edit = QLineEdit(DEFAULT_USER_AGENT)
        self.login_ua_edit.hide()

        login_btn = QPushButton("登录并进入下载器")
        login_btn.setObjectName("primaryButton")
        login_btn.clicked.connect(self.login)
        open_btn = QPushButton("系统浏览器打开网站")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(LIST_URL)))
        skip_btn = QPushButton("跳过登录")
        skip_btn.setObjectName("ghostButton")
        skip_btn.clicked.connect(self.skip_login)
        btn_row = QHBoxLayout()
        btn_row.addWidget(login_btn)
        btn_row.addWidget(open_btn)

        note = QLabel("如站点需要安全验证，请进入设置页使用浏览器验证 Cookie。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b;")

        form.addRow("账号", self.login_user_edit)
        form.addRow("密码", self.login_pass_edit)
        form.addRow(btn_row)
        form.addRow(skip_btn)
        form.addRow(note)
        body_layout.addWidget(card, 0, Qt.AlignHCenter)
        body_layout.addStretch()
        layout.addWidget(body, 1)
        return page

    def load_local_cache(self):
        if not self.cache_file.exists():
            return
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self.result_cache = {
                key: [self.album_from_dict(item) for item in value]
                for key, value in (data.get("results") or {}).items()
                if isinstance(value, list)
            }
            self.detail_cache = {
                key: self.album_from_dict(value)
                for key, value in (data.get("details") or {}).items()
                if isinstance(value, dict)
            }
            self.download_history = [
                {
                    "title": str(item.get("title") or ""),
                    "file": str(item.get("file") or ""),
                    "path": str(item.get("path") or ""),
                    "pdf_path": str(item.get("pdf_path") or ""),
                    "image_dir": str(item.get("image_dir") or ""),
                    "album_id": str(item.get("album_id") or item.get("id") or ""),
                    "cover_url": str(item.get("cover_url") or ""),
                    "format": str(item.get("format") or ""),
                    "created_at": str(item.get("created_at") or ""),
                    "outputs": [
                        str(path)
                        for path in (item.get("outputs") or [])
                        if str(path).strip()
                    ],
                }
                for item in (data.get("history") or [])
                if isinstance(item, dict)
            ]
            self.settings_cache = data.get("settings") if isinstance(data.get("settings"), dict) else {}
            if int(self.settings_cache.get("settings_version", 0) or 0) < 3:
                self.settings_cache["detail_check"] = False
            self.api_domain_pool = self._dedupe_domains((data.get("api_domains") or []) + self.api_domain_pool)
            self.cover_domain_pool = self._dedupe_domains((data.get("cover_domains") or []) + self.cover_domain_pool)
            self.cover_domain_failures = {
                str(key): int(value)
                for key, value in (data.get("cover_domain_failures") or {}).items()
                if str(key).strip()
            }
        except Exception:
            self.result_cache = {}
            self.detail_cache = {}
            self.download_history = []
            self.settings_cache = {}

    def save_local_cache(self):
        try:
            payload = {
                "results": {
                    key: [self.album_to_dict(album) for album in albums]
                    for key, albums in self.result_cache.items()
                },
                "details": {
                    key: self.album_to_dict(album)
                    for key, album in self.detail_cache.items()
                },
                "history": self.download_history[-300:],
                "settings": self.current_settings_snapshot(),
                "api_domains": self.api_domain_pool,
                "cover_domains": self.cover_domain_pool,
                "cover_domain_failures": self.cover_domain_failures,
            }
            self.cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            self.log(f"缓存保存失败：{exc}") if hasattr(self, "log_box") else None

    @staticmethod
    def _dedupe_domains(domains: List[str]) -> List[str]:
        result = []
        seen = set()
        for domain in domains:
            value = str(domain or "").strip().strip("/")
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def current_settings_snapshot(self) -> Dict[str, object]:
        snapshot = dict(self.settings_cache)
        if not hasattr(self, "format_buttons"):
            return snapshot
        snapshot.update(
            {
                "output_format": self.selected_output_format(),
                "settings_version": 3,
                "make_pdf": self.make_pdf.isChecked(),
                "keep_images": self.keep_images.isChecked(),
                "cache_as_webp": self.cache_as_webp.isChecked() if hasattr(self, "cache_as_webp") else False,
                "protocol_parser": self.protocol_parser.isChecked() if hasattr(self, "protocol_parser") else True,
                "detail_check": self.detail_check.isChecked() if hasattr(self, "detail_check") else False,
                "reading_mode": self.reading_mode_combo.currentData() if hasattr(self, "reading_mode_combo") else "scroll",
                "cookie": self.cookie_edit.toPlainText().strip() if hasattr(self, "cookie_edit") else "",
                "user_agent": self.ua_edit.text().strip() if hasattr(self, "ua_edit") else DEFAULT_USER_AGENT,
                "proxy": self.proxy_edit.text().strip() if hasattr(self, "proxy_edit") else "",
                "output_dir": self.output_edit.text().strip() if hasattr(self, "output_edit") else "",
                "delay_min": self.delay_min.value() if hasattr(self, "delay_min") else 4,
                "delay_max": self.delay_max.value() if hasattr(self, "delay_max") else 9,
                "retries": self.retries.value() if hasattr(self, "retries") else 3,
                "backoff": self.backoff.value() if hasattr(self, "backoff") else 3,
                "image_threads": self.image_threads.value() if hasattr(self, "image_threads") else 4,
                "detail_threads": self.detail_threads.value() if hasattr(self, "detail_threads") else 6,
                "parallel_downloads": self.parallel_downloads.value() if hasattr(self, "parallel_downloads") else 2,
                "stop_on_block": self.stop_on_block.isChecked() if hasattr(self, "stop_on_block") else True,
            }
        )
        return snapshot

    def apply_saved_settings(self):
        if not self.settings_cache:
            self.connect_settings_autosave()
            return
        self._applying_settings = True
        try:
            output_format = str(self.settings_cache.get("output_format") or "pdf")
            if output_format in self.format_buttons:
                self.format_buttons[output_format].setChecked(True)
            self.make_pdf.setChecked(bool(self.settings_cache.get("make_pdf", False)))
            self.keep_images.setChecked(bool(self.settings_cache.get("keep_images", True)))
            if hasattr(self, "cache_as_webp"):
                self.cache_as_webp.setChecked(bool(self.settings_cache.get("cache_as_webp", False)))
            if hasattr(self, "protocol_parser"):
                self.protocol_parser.setChecked(bool(self.settings_cache.get("protocol_parser", True)))
            if hasattr(self, "detail_check"):
                self.detail_check.setChecked(bool(self.settings_cache.get("detail_check", False)))
            if hasattr(self, "reading_mode_combo"):
                reading_mode = str(self.settings_cache.get("reading_mode") or "scroll")
                index = self.reading_mode_combo.findData(reading_mode)
                self.reading_mode_combo.setCurrentIndex(index if index >= 0 else 0)

            cookie = str(self.settings_cache.get("cookie") or "")
            if cookie:
                self.cookie_edit.setPlainText(cookie)
                if hasattr(self, "login_cookie_edit"):
                    self.login_cookie_edit.setPlainText(cookie)
            self.ua_edit.setText(str(self.settings_cache.get("user_agent") or DEFAULT_USER_AGENT))
            if hasattr(self, "login_ua_edit"):
                self.login_ua_edit.setText(self.ua_edit.text())
            self.proxy_edit.setText(str(self.settings_cache.get("proxy") or ""))
            output_dir = str(self.settings_cache.get("output_dir") or "")
            if output_dir and self.should_keep_saved_output_dir(output_dir):
                self.output_edit.setText(output_dir)
            else:
                self.output_edit.setText(str(self.default_output_dir))

            self.delay_min.setValue(int(self.settings_cache.get("delay_min", 4)))
            self.delay_max.setValue(int(self.settings_cache.get("delay_max", 9)))
            self.retries.setValue(int(self.settings_cache.get("retries", 3)))
            self.backoff.setValue(int(self.settings_cache.get("backoff", 3)))
            self.image_threads.setValue(int(self.settings_cache.get("image_threads", 4)))
            self.detail_threads.setValue(int(self.settings_cache.get("detail_threads", 6)))
            if hasattr(self, "parallel_downloads"):
                self.parallel_downloads.setValue(int(self.settings_cache.get("parallel_downloads", 2)))
            self.stop_on_block.setChecked(bool(self.settings_cache.get("stop_on_block", True)))
        finally:
            self._applying_settings = False
        self.connect_settings_autosave()

    def connect_settings_autosave(self):
        if getattr(self, "_settings_autosave_connected", False):
            return
        for button in getattr(self, "format_buttons", {}).values():
            button.toggled.connect(self.schedule_settings_save)
        for checkbox in [self.make_pdf, self.keep_images, getattr(self, "cache_as_webp", None), getattr(self, "protocol_parser", None), self.stop_on_block, getattr(self, "detail_check", None)]:
            if checkbox:
                checkbox.toggled.connect(self.schedule_settings_save)
        for edit in [self.ua_edit, self.proxy_edit, self.output_edit]:
            edit.textChanged.connect(self.schedule_settings_save)
        self.cookie_edit.textChanged.connect(self.schedule_settings_save)
        if hasattr(self, "reading_mode_combo"):
            self.reading_mode_combo.currentIndexChanged.connect(self.schedule_settings_save)
        for spinbox in [self.delay_min, self.delay_max, self.retries, self.backoff, self.image_threads, self.detail_threads, getattr(self, "parallel_downloads", None)]:
            if spinbox is None:
                continue
            spinbox.valueChanged.connect(self.schedule_settings_save)
        self._settings_autosave_connected = True

    def schedule_settings_save(self, *args):
        if self._applying_settings:
            return
        self.settings_cache = self.current_settings_snapshot()
        QTimer.singleShot(250, self.save_local_cache)

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

    def show_floating_notice(self, message: str):
        notice = QLabel(message, self)
        notice.setObjectName("floatingNotice")
        notice.setAlignment(Qt.AlignCenter)
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
        self._center_window()
        self.stack.setCurrentWidget(self.app_page)
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
        self.domain_worker.start()

    def on_domain_pool_refreshed(self, domains: List[str]):
        self.api_domain_pool = self._dedupe_domains(domains + self.api_domain_pool)
        self.save_local_cache()

    def auto_load_home_page(self):
        if self.stack.currentWidget() is not self.app_page:
            return
        if self.is_loading_busy() or self.result_total_count > 0:
            return
        self.id_edit.clear()
        self.list_url_edit.setText(LIST_URL)
        self.log(f"自动加载首页漫画：{LIST_URL}")
        self.start_scrape()

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
        self.loading_label.setText(message)
        self.loading_label.show()
        if hasattr(self, "result_loading_text") and "漫画" in message:
            self.result_loading_text.setText(message)
            self.result_stack.setCurrentWidget(self.result_loading_page)
        if self.loading_timer:
            self.loading_timer.stop()
        self.loading_timer = QTimer(self)
        self.loading_timer.timeout.connect(lambda: self._tick_loading(message))
        self.loading_timer.start(360)

    def _tick_loading(self, message: str):
        self.loading_tick = (self.loading_tick + 1) % 4
        self.loading_label.setText(message + "." * self.loading_tick)
        if hasattr(self, "result_loading_text") and self.result_stack.currentWidget() is self.result_loading_page:
            self.result_loading_text.setText(message + "." * self.loading_tick)

    def stop_loading(self):
        if self.loading_timer:
            self.loading_timer.stop()
            self.loading_timer = None
        self.loading_label.setText("等待操作")
        self.loading_label.show()

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
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.update_current_results)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.quick_start_download)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.quick_start_download)
        if hasattr(self, "search_edit"):
            self.search_edit.returnPressed.connect(self.start_scrape)
        if hasattr(self, "id_edit"):
            self.id_edit.returnPressed.connect(self.start_scrape)

    def focus_search_box(self):
        self.switch_page(self.home_page_index())
        self.search_edit.setFocus(Qt.ShortcutFocusReason)
        self.search_edit.selectAll()

    def focus_id_box(self):
        self.switch_page(self.home_page_index())
        self.id_edit.setFocus(Qt.ShortcutFocusReason)
        self.id_edit.selectAll()

    def _build_app_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("appRoot")
        outer_layout = QVBoxLayout(page)
        outer_layout.setContentsMargins(6, 6, 6, 6)
        outer_layout.setSpacing(6)
        outer_layout.addWidget(self._build_dashboard_header())

        content = QWidget()
        content.setObjectName("dashboardContent")
        content.setMinimumSize(0, 0)
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._build_navigation_panel())
        self.main_content_stack = QStackedWidget()
        self.main_content_stack.addWidget(self._build_home_workspace())
        self.main_content_stack.addWidget(self._build_download_panel())
        self.main_content_stack.addWidget(self._build_settings_panel())
        self.main_content_stack.addWidget(self._build_history_panel())
        self.main_content_stack.addWidget(self._build_about_panel())
        layout.addWidget(self.main_content_stack, 1)
        outer_layout.addWidget(content, 1)
        return page

    def _build_navigation_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(92)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(8)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        items = [
            ("首页", self.home_page_index(), self.switch_page),
            ("下载", self.downloading_page_index(), self.switch_page),
            ("历史", self.history_page_index(), self.switch_page),
            ("设置", self.settings_page_index(), self.switch_page),
            ("关于", self.about_page_index(), self.switch_page),
        ]
        for text, index, callback in items:
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, index=index, callback=callback: callback(index))
            self.nav_group.addButton(button)
            self.nav_buttons[index] = button
            layout.addWidget(button)

        layout.addStretch()
        self.nav_buttons[self.home_page_index()].setChecked(True)
        return panel

    def _build_home_workspace(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._build_search_panel())
        layout.addWidget(self._build_result_panel(), 1)
        return page

    def _build_search_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMaximumHeight(150)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel("搜索与榜单")
        title.setObjectName("panelTitle")
        top.addWidget(title)
        top.addStretch()
        self.detail_check = QCheckBox("进入详情页获取章节")
        self.detail_check.setChecked(False)
        top.addWidget(self.detail_check)
        layout.addLayout(top)

        self.list_url_edit = QLineEdit(LIST_URL)
        self.list_url_edit.hide()
        self.rank_group = QButtonGroup(self)
        self.rank_group.setExclusive(True)
        self.rank_buttons = {}
        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(True)
        self.category_buttons = {}

        first_row = QHBoxLayout()
        first_row.setSpacing(6)
        for index, (text, value) in enumerate([("日榜", "day"), ("周榜", "week"), ("月榜", "month")]):
            button = QPushButton(text)
            button.setObjectName("segButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda checked=False, value=value: self.start_rank_scrape(value))
            self.rank_group.addButton(button)
            self.rank_buttons[value] = button
            first_row.addWidget(button)
        doujin_btn = QPushButton("同人")
        doujin_btn.setObjectName("segButton")
        doujin_btn.setCheckable(True)
        doujin_btn.clicked.connect(lambda: self.start_category_filter("doujin", "同人"))
        self.category_group.addButton(doujin_btn)
        self.category_buttons["doujin"] = doujin_btn
        first_row.addWidget(doujin_btn)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入关键词")
        self.search_edit.setFixedHeight(30)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet(
            "QLineEdit { background:#ffffff; border:1px solid #cfd8e5; border-radius:8px; "
            "padding:5px 10px; color:#1f2937; } "
            "QLineEdit:focus { border:1px solid #2f80ed; background:#fbfdff; }"
        )
        search_btn = QPushButton("搜索")
        search_btn.setObjectName("primaryButton")
        search_btn.clicked.connect(self.start_scrape)
        first_row.addWidget(self.search_edit, 2)
        first_row.addWidget(search_btn)
        layout.addLayout(first_row)

        second_row = QHBoxLayout()
        second_row.setSpacing(6)
        for text, category in [
            ("单本", "single"),
            ("短篇", "short"),
            ("其他类", "another"),
            ("韩漫", "hanman"),
            ("美漫", "meiman"),
            ("English", "english_site"),
        ]:
            button = QPushButton(text)
            button.setObjectName("segButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, category=category, text=text: self.start_category_filter(category, text))
            self.category_group.addButton(button)
            self.category_buttons[category] = button
            second_row.addWidget(button)

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("ID：422866, p456")
        self.id_edit.setFixedHeight(30)
        second_row.addWidget(self.id_edit, 1)
        start_btn = QPushButton("加入下载")
        start_btn.setObjectName("primaryButton")
        start_btn.clicked.connect(self.quick_start_download)
        second_row.addWidget(start_btn)
        layout.addLayout(second_row)
        return panel

    def _build_settings_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        title = QLabel("设置")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        settings = QWidget()
        form = QFormLayout(settings)
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        self.format_buttons = {}
        format_row = QHBoxLayout()
        for text, value in [("图片", "images"), ("ZIP", "zip"), ("PDF", "pdf")]:
            button = QPushButton(text)
            button.setObjectName("segButton")
            button.setCheckable(True)
            button.setChecked(value == "pdf")
            self.format_group.addButton(button)
            self.format_buttons[value] = button
            format_row.addWidget(button)

        self.make_pdf = QCheckBox("PDF 按章节导出")
        self.make_pdf.setChecked(False)
        self.keep_images = QCheckBox("保留图片目录")
        self.keep_images.setChecked(True)
        self.cache_as_webp = QCheckBox("图片缓存转 WebP")
        self.cache_as_webp.setChecked(False)
        self.protocol_parser = QCheckBox("协议解析加速")
        self.protocol_parser.setChecked(True)
        download_options = QHBoxLayout()
        download_options.addWidget(self.make_pdf)
        download_options.addWidget(self.keep_images)
        download_options.addWidget(self.cache_as_webp)
        download_options.addWidget(self.protocol_parser)
        download_options.addStretch()

        self.cookie_edit = QTextEdit()
        self.cookie_edit.setFixedHeight(76)
        self.cookie_edit.setPlainText(load_cookie_header() or jmcomic_default_cookie_header())
        self.ua_edit = QLineEdit(DEFAULT_USER_AGENT)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("可选：http://127.0.0.1:7890；多个代理用英文逗号/分号分隔")
        self.output_edit = QLineEdit(str(self.default_output_dir))
        self.delay_min = QSpinBox()
        self.delay_min.setRange(1, 120)
        self.delay_min.setValue(4)
        self.delay_max = QSpinBox()
        self.delay_max.setRange(1, 180)
        self.delay_max.setValue(9)
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(3)
        self.backoff = QSpinBox()
        self.backoff.setRange(1, 120)
        self.backoff.setValue(3)
        self.image_threads = QSpinBox()
        self.image_threads.setRange(1, 12)
        self.image_threads.setValue(4)
        self.detail_threads = QSpinBox()
        self.detail_threads.setRange(1, 12)
        self.detail_threads.setValue(6)
        self.parallel_downloads = QSpinBox()
        self.parallel_downloads.setRange(1, 4)
        self.parallel_downloads.setValue(2)
        self.stop_on_block = QCheckBox("遇到 403/429 停止")
        self.stop_on_block.setChecked(True)
        self.reading_mode_combo = QComboBox()
        self.reading_mode_combo.addItem("鼠标滚动阅读（PDF/WebP/JPG 通用）", "scroll")
        self.reading_mode_combo.addItem("左右切换页码（图片格式）", "page")
        cache_tools = QHBoxLayout()
        clear_current_cache_btn = QPushButton("清理当前结果缓存")
        clear_current_cache_btn.clicked.connect(self.clear_current_result_cache)
        clean_cache_btn = QPushButton("清理损坏缓存")
        clean_cache_btn.clicked.connect(self.clean_broken_cache)
        clear_all_cache_btn = QPushButton("清理全部缓存")
        clear_all_cache_btn.clicked.connect(self.clear_all_runtime_cache)
        export_cache_btn = QPushButton("导出缓存")
        export_cache_btn.clicked.connect(self.export_cache_bundle)
        import_cache_btn = QPushButton("导入缓存")
        import_cache_btn.clicked.connect(self.import_cache_bundle)
        cache_tools.addWidget(clear_current_cache_btn)
        cache_tools.addWidget(clean_cache_btn)
        cache_tools.addWidget(clear_all_cache_btn)
        cache_tools.addWidget(export_cache_btn)
        cache_tools.addWidget(import_cache_btn)
        cache_tools.addStretch()
        verify_btn = QPushButton("浏览器验证 Cookie")
        verify_btn.clicked.connect(self.open_cookie_verifier)

        form.addRow("下载格式", format_row)
        form.addRow("下载选项", download_options)
        form.addRow("阅读方式", self.reading_mode_combo)
        form.addRow("缓存维护", cache_tools)
        self.cache_path_label = QLabel()
        self.cache_path_label.setWordWrap(True)
        self.cache_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.cache_path_label.setStyleSheet("color:#64748b;font-size:12px;")
        form.addRow("缓存位置", self.cache_path_label)
        self.output_edit.textChanged.connect(self.update_cache_path_label)
        form.addRow(verify_btn)
        form.addRow("Cookie", self.cookie_edit)
        form.addRow("User-Agent", self.ua_edit)
        form.addRow("代理", self.proxy_edit)
        form.addRow("保存目录", self.output_edit)
        form.addRow("请求间隔", self.delay_min)
        form.addRow("重试次数", self.retries)
        form.addRow("加载线程", self.detail_threads)
        form.addRow("图片线程", self.image_threads)
        form.addRow("同时下载", self.parallel_downloads)
        form.addRow(self.stop_on_block)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(settings)
        layout.addWidget(scroll, 1)
        self.apply_saved_settings()
        self.update_cache_path_label()
        return panel

    def _build_dashboard_header(self) -> QFrame:
        header = QFrame()
        self.main_header = header
        header.setObjectName("dashboardHeader")
        header.installEventFilter(self)
        header.setFixedHeight(36)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 0, 14, 0)
        title = QLabel("JMComic 下载器")
        title.setStyleSheet("font-size:15px;font-weight:800;color:#182235;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.user_label = QLabel("")
        self.user_label.setStyleSheet("color:#64748b;")
        self.user_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.backend_label = QLabel("待加载")
        self.set_backend_status("待加载", "idle")
        logout_btn = QPushButton("退出登录")
        logout_btn.clicked.connect(self.logout)
        layout.addWidget(title)
        layout.addWidget(self.backend_label)
        layout.addStretch()
        layout.addWidget(self.user_label)
        layout.addWidget(logout_btn)
        return header

    def _build_control_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(248)
        outer_layout = QVBoxLayout(panel)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.control_stack = QStackedWidget()
        outer_layout.addWidget(self.control_stack)

        main_page = QWidget()
        layout = QVBoxLayout(main_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        search_title = QLabel("搜索")
        search_title.setObjectName("sectionTitle")
        layout.addWidget(search_title)
        tab_row = QHBoxLayout()
        for index, text in enumerate(["全站", "作品", "作者", "标签"]):
            button = QPushButton(text)
            button.setObjectName("segButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            tab_row.addWidget(button)
        layout.addLayout(tab_row)

        keyword_row = QHBoxLayout()
        self.list_url_edit = QLineEdit(LIST_URL)
        self.list_url_edit.hide()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入关键词")
        self.search_edit.setFixedHeight(30)
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self.start_scrape)
        keyword_row.addWidget(self.search_edit, 1)
        keyword_row.addWidget(search_btn)
        layout.addLayout(keyword_row)

        rank_title = QLabel("排行榜")
        rank_title.setObjectName("sectionTitle")
        layout.addWidget(rank_title)
        rank_row = QHBoxLayout()
        self.rank_group = QButtonGroup(self)
        self.rank_group.setExclusive(True)
        self.rank_buttons = {}
        for index, (text, value) in enumerate([("日榜", "day"), ("周榜", "week"), ("月榜", "month")]):
            button = QPushButton(text)
            button.setObjectName("segButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda checked=False, value=value: self.start_rank_scrape(value))
            self.rank_group.addButton(button)
            self.rank_buttons[value] = button
            rank_row.addWidget(button)
        layout.addLayout(rank_row)

        id_title = QLabel("下载 ID")
        id_title.setObjectName("sectionTitle")
        layout.addWidget(id_title)
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("422866, p456")
        self.id_edit.setFixedHeight(30)
        layout.addWidget(self.id_edit)

        format_title = QLabel("保存格式")
        format_title.setObjectName("sectionTitle")
        layout.addWidget(format_title)
        format_row = QHBoxLayout()
        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        self.format_buttons = {}
        for text, value in [("图片", "images"), ("ZIP", "zip"), ("PDF", "pdf")]:
            button = QPushButton(text)
            button.setObjectName("segButton")
            button.setCheckable(True)
            button.setChecked(value == "pdf")
            self.format_group.addButton(button)
            self.format_buttons[value] = button
            format_row.addWidget(button)
        layout.addLayout(format_row)

        pdf_title = QLabel("下载选项")
        pdf_title.setObjectName("sectionTitle")
        layout.addWidget(pdf_title)
        pdf_row = QHBoxLayout()
        self.make_pdf = QCheckBox("PDF 按章节导出")
        self.make_pdf.setChecked(False)
        self.keep_images = QCheckBox("保留图片目录")
        self.keep_images.setChecked(True)
        self.protocol_parser = QCheckBox("协议解析加速")
        self.protocol_parser.setChecked(True)
        pdf_row.addWidget(self.make_pdf)
        pdf_row.addWidget(self.keep_images)
        layout.addLayout(pdf_row)
        layout.addWidget(self.protocol_parser)

        self.detail_check = QCheckBox("进入详情页获取章节")
        self.detail_check.setChecked(False)
        layout.addWidget(self.detail_check)

        more_btn = QPushButton("更多设置")
        more_btn.clicked.connect(self.toggle_settings)
        layout.addWidget(more_btn)
        start_btn = QPushButton("开始下载")
        start_btn.setObjectName("primaryButton")
        start_btn.clicked.connect(self.quick_start_download)
        layout.addWidget(start_btn)
        layout.addStretch()

        settings_page = QWidget()
        settings_page_layout = QVBoxLayout(settings_page)
        settings_page_layout.setContentsMargins(10, 10, 10, 10)
        settings_page_layout.setSpacing(7)
        settings_header = QHBoxLayout()
        back_btn = QPushButton("返回")
        back_btn.clicked.connect(self.toggle_settings)
        settings_title = QLabel("更多设置")
        settings_title.setObjectName("panelTitle")
        settings_header.addWidget(back_btn)
        settings_header.addWidget(settings_title)
        settings_header.addStretch()
        settings_page_layout.addLayout(settings_header)
        settings = QGroupBox("后台参数")
        settings_layout = QFormLayout(settings)
        settings_layout.setContentsMargins(10, 14, 10, 10)
        settings_layout.setSpacing(6)
        settings_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)
        settings_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.cookie_edit = QTextEdit()
        self.cookie_edit.setFixedHeight(54)
        self.cookie_edit.setPlainText(load_cookie_header() or jmcomic_default_cookie_header())
        self.ua_edit = QLineEdit(DEFAULT_USER_AGENT)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("可选：http://127.0.0.1:7890")
        self.output_edit = QLineEdit(str(self.default_output_dir))
        self.output_edit.setFixedHeight(28)
        self.delay_min = QSpinBox()
        self.delay_min.setRange(1, 120)
        self.delay_min.setValue(4)
        self.delay_max = QSpinBox()
        self.delay_max.setRange(1, 180)
        self.delay_max.setValue(9)
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(3)
        self.backoff = QSpinBox()
        self.backoff.setRange(1, 120)
        self.backoff.setValue(3)
        self.image_threads = QSpinBox()
        self.image_threads.setRange(1, 12)
        self.image_threads.setValue(4)
        self.detail_threads = QSpinBox()
        self.detail_threads.setRange(1, 12)
        self.detail_threads.setValue(6)
        self.parallel_downloads = QSpinBox()
        self.parallel_downloads.setRange(1, 4)
        self.parallel_downloads.setValue(2)
        self.stop_on_block = QCheckBox("遇到 403/429 停止")
        self.stop_on_block.setChecked(True)
        verify_btn = QPushButton("浏览器验证 Cookie")
        verify_btn.clicked.connect(self.open_cookie_verifier)
        settings_layout.addRow(verify_btn)
        settings_layout.addRow("Cookie", self.cookie_edit)
        settings_layout.addRow("代理", self.proxy_edit)
        settings_layout.addRow("保存", self.output_edit)
        settings_layout.addRow("间隔", self.delay_min)
        settings_layout.addRow("重试", self.retries)
        settings_layout.addRow("加载线程", self.detail_threads)
        settings_layout.addRow("图片线程", self.image_threads)
        settings_layout.addRow("同时下载", self.parallel_downloads)
        settings_layout.addRow(self.stop_on_block)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_scroll.setWidget(settings)
        self.settings_box = settings_scroll
        settings_page_layout.addWidget(settings_scroll, 1)
        self.control_stack.addWidget(main_page)
        self.control_stack.addWidget(settings_page)
        return panel

    def _build_result_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.setObjectName("ghostButton")
        refresh_btn.clicked.connect(self.refresh_current_results)
        update_btn = QPushButton("更新")
        update_btn.setObjectName("ghostButton")
        update_btn.clicked.connect(self.update_current_results)
        self.loading_label = QLabel("等待操作")
        self.loading_label.setStyleSheet("color:#8290a7;")
        header.addWidget(refresh_btn)
        header.addWidget(update_btn)
        header.addStretch()
        header.addWidget(self.loading_label)
        layout.addLayout(header)

        self.result_stack = QStackedWidget()
        self.result_loading_page = QWidget()
        loading_layout = QVBoxLayout(self.result_loading_page)
        loading_layout.setAlignment(Qt.AlignCenter)
        self.result_loading_text = QLabel("正在加载漫画资源")
        self.result_loading_text.setAlignment(Qt.AlignCenter)
        self.result_loading_text.setStyleSheet("color:#2563eb;font-size:18px;font-weight:700;")
        self.result_loading_art = QLabel()
        self.result_loading_art.setAlignment(Qt.AlignCenter)
        self.apply_loading_movie(self.result_loading_art, QSize(150, 118))
        loading_layout.addStretch()
        loading_layout.addWidget(self.result_loading_art, 0, Qt.AlignHCenter)
        loading_layout.addWidget(self.result_loading_text)
        loading_layout.addStretch()

        self.result_scroll = QScrollArea()
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setFrameShape(QFrame.NoFrame)
        self.result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.result_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.result_grid_widget = QWidget()
        self.result_grid = QGridLayout(self.result_grid_widget)
        self.result_grid.setContentsMargins(3, 3, 3, 3)
        self.result_grid.setHorizontalSpacing(3)
        self.result_grid.setVerticalSpacing(4)
        self.result_scroll.setWidget(self.result_grid_widget)
        self.result_stack.addWidget(self.result_loading_page)
        self.result_stack.addWidget(self.result_scroll)
        self.result_stack.setCurrentWidget(self.result_scroll)
        layout.addWidget(self.result_stack, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(10, 2, 10, 6)
        self.page_label = QLabel("第 0 / 0 页，共 0 本")
        self.page_label.setStyleSheet("color:#64748b;")
        self.prev_page_btn = QPushButton("上一页")
        self.next_page_btn = QPushButton("下一页")
        self.prev_page_btn.clicked.connect(lambda: self.change_result_page(-1))
        self.next_page_btn.clicked.connect(lambda: self.change_result_page(1))
        self.prev_page_btn.setEnabled(False)
        self.next_page_btn.setEnabled(False)
        footer.addStretch()
        footer.addWidget(self.page_label)
        footer.addWidget(self.prev_page_btn)
        footer.addWidget(self.next_page_btn)
        layout.addLayout(footer)
        return panel

    def _build_detail_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        title = QLabel("漫画详情")
        title.setObjectName("panelTitle")
        title.setStyleSheet("font-size:16px;font-weight:800;color:#1f2937;")

        hero = QHBoxLayout()
        hero.setSpacing(12)
        self.cover_label = QLabel("暂无封面")
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setFixedSize(150, 198)
        self.cover_label.setStyleSheet(
            "background:#eef3f8;border:1px solid #d7e3f1;border-radius:8px;color:#8491a5;"
        )
        self.detail_card = QLabel("未选择 ID")
        self.detail_card.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.detail_card.setWordWrap(True)
        self.detail_card.setMinimumHeight(140)
        self.detail_card.setStyleSheet(
            "background:#f8fafc;border:1px solid #e0e7f2;border-radius:8px;color:#334155;padding:10px;line-height:1.35;"
        )
        hero.addWidget(self.cover_label, 0, Qt.AlignTop)
        hero.addWidget(self.detail_card, 1)

        self.tags_card = QLabel("标签：-")
        self.tags_card.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.tags_card.setWordWrap(True)
        self.tags_card.setMinimumHeight(48)
        self.tags_card.setStyleSheet(
            "background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;color:#9a3412;padding:8px;"
        )
        load_chapter_btn = QPushButton("加载章节")
        load_chapter_btn.clicked.connect(self.load_current_chapters)
        read_chapter_btn = QPushButton("阅读选中章节")
        read_chapter_btn.setObjectName("primaryButton")
        read_chapter_btn.clicked.connect(self.open_reader_for_current)
        all_chapter_btn = QPushButton("全选章节")
        all_chapter_btn.clicked.connect(lambda: self.set_all_chapters(True))
        none_chapter_btn = QPushButton("取消全选")
        none_chapter_btn.clicked.connect(lambda: self.set_all_chapters(False))
        add_current_btn = QPushButton("加入队列")
        add_current_btn.setObjectName("primaryButton")
        add_current_btn.clicked.connect(self.add_current_album_to_queue)
        layout.addWidget(title)
        layout.addLayout(hero)
        layout.addWidget(self.tags_card)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(load_chapter_btn)
        action_row.addWidget(read_chapter_btn)
        action_row.addWidget(add_current_btn)
        layout.addLayout(action_row)
        chapter_header = QHBoxLayout()
        chapter_title = QLabel("章节列表")
        chapter_title.setStyleSheet("font-weight:700;color:#334155;")
        chapter_header.addWidget(chapter_title)
        chapter_header.addStretch()
        chapter_header.addWidget(all_chapter_btn)
        chapter_header.addWidget(none_chapter_btn)
        layout.addLayout(chapter_header)
        self.chapter_table = QTableWidget(0, 4)
        self.chapter_table.verticalHeader().setDefaultSectionSize(26)
        self.chapter_table.verticalHeader().setVisible(False)
        self.chapter_table.setHorizontalHeaderLabels(["选择", "序号", "章节", "URL"])
        self.chapter_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.chapter_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.chapter_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.chapter_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.chapter_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.chapter_table.setMinimumHeight(96)
        self.chapter_table.setMaximumHeight(520)
        layout.addWidget(self.chapter_table)
        return panel

    def _build_download_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumHeight(420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        title = QLabel("下载列表")
        title.setObjectName("panelTitle")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.setRange(0, 100)
        self.progress.setFormat("0%")
        self.cancel_btn = QPushButton("取消全部下载")
        self.cancel_btn.clicked.connect(self.cancel_current_task)
        self.cancel_btn.setEnabled(False)
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.clear_log_box)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.progress)
        header.addWidget(self.cancel_btn)
        header.addWidget(clear_btn)
        layout.addLayout(header)
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(8)

        queue_area = QWidget()
        queue_layout = QVBoxLayout(queue_area)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(6)
        queue_header = QHBoxLayout()
        queue_title = QLabel("下载任务")
        queue_title.setStyleSheet("font-weight:700;color:#334155;")
        self.queue_status_label = QLabel("等待添加")
        self.queue_status_label.setStyleSheet("color:#64748b;font-size:12px;")
        queue_header.addWidget(queue_title)
        queue_header.addStretch()
        queue_header.addWidget(self.queue_status_label)
        queue_layout.addLayout(queue_header)
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setFrameShape(QFrame.NoFrame)
        self.queue_cards_widget = QWidget()
        self.queue_cards_layout = QVBoxLayout(self.queue_cards_widget)
        self.queue_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_cards_layout.setSpacing(6)
        self.queue_cards_layout.addStretch()
        self.queue_scroll.setWidget(self.queue_cards_widget)
        queue_layout.addWidget(self.queue_scroll, 1)

        self.current_download_card = None
        self.current_download_progress = None
        self.current_download_status = None
        self.current_download_title = None
        self.current_download_sub = None
        self.current_download_cover = None
        self.current_download_cancel = None

        log_area = QWidget()
        log_layout = QVBoxLayout(log_area)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(6)
        log_title = QLabel("运行日志")
        log_title.setStyleSheet("font-weight:700;color:#334155;")
        log_layout.addWidget(log_title)
        self.completed_table = QTableWidget(0, 3)
        self.completed_table.verticalHeader().setDefaultSectionSize(24)
        self.completed_table.verticalHeader().setVisible(False)
        self.completed_table.setHorizontalHeaderLabels(["漫画", "PDF 文件", "路径"])
        self.completed_table.hide()
        self.log_box = QPlainTextEdit()
        self.log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("暂无日志")
        log_layout.addWidget(self.log_box, 1)
        content.addWidget(queue_area, 3)
        content.addWidget(log_area, 2)
        layout.addLayout(content, 1)
        buttons = QHBoxLayout()
        start_btn = QPushButton("开始下载队列")
        start_btn.setObjectName("primaryButton")
        start_btn.clicked.connect(self.start_download_queue)
        clear_queue_btn = QPushButton("清空队列")
        clear_queue_btn.clicked.connect(self.clear_queue)
        buttons.addStretch()
        buttons.addWidget(clear_queue_btn)
        buttons.addWidget(start_btn)
        layout.addLayout(buttons)
        return panel

    def _build_history_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("历史下载记录")
        title.setObjectName("panelTitle")
        mode_label = QLabel("阅读格式")
        mode_label.setStyleSheet("color:#64748b;font-size:12px;font-weight:700;")
        self.history_read_mode_combo = QComboBox()
        self.history_read_mode_combo.addItems(["自动", "PDF", "原文件"])
        self.history_read_mode_combo.setFixedWidth(96)
        read_btn = QPushButton("阅读选中")
        read_btn.setObjectName("primaryButton")
        read_btn.clicked.connect(self.open_selected_history_reading)
        open_dir_btn = QPushButton("打开位置")
        open_dir_btn.clicked.connect(self.open_selected_history_location)
        delete_btn = QPushButton("删除选中")
        delete_btn.clicked.connect(self.delete_selected_history_record)
        clear_btn = QPushButton("清空历史")
        clear_btn.clicked.connect(self.clear_download_history)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(mode_label)
        header.addWidget(self.history_read_mode_combo)
        header.addWidget(open_dir_btn)
        header.addWidget(read_btn)
        header.addWidget(delete_btn)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QFrame.NoFrame)
        self.history_cards_widget = QWidget()
        self.history_cards_layout = QVBoxLayout(self.history_cards_widget)
        self.history_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.history_cards_layout.setSpacing(8)
        self.history_cards_layout.addStretch()
        self.history_scroll.setWidget(self.history_cards_widget)
        layout.addWidget(self.history_scroll, 1)
        self.refresh_history_table()
        return panel

    def refresh_history_table(self):
        if not hasattr(self, "history_cards_layout"):
            return
        self.sync_history_with_local_files()
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
        for index, record in enumerate(reversed(self.download_history)):
            source_index = len(self.download_history) - 1 - index
            card = self.create_history_card(record, source_index)
            self.history_card_by_index[source_index] = card
            self.history_cards_layout.insertWidget(max(0, self.history_cards_layout.count() - 1), card)
        if not self.download_history:
            empty = self.create_history_card({"title": "暂无历史下载记录", "file": "下载完成后会显示在这里", "path": ""}, -1)
            self.history_cards_layout.insertWidget(0, empty)

    def create_history_card(self, record: Dict[str, str], index: int) -> QFrame:
        card = QFrame()
        card.setObjectName("historyCard")
        card.setProperty("selected", index == self.selected_history_index)
        card.setMinimumHeight(116)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setStyleSheet(self.history_card_style(index == self.selected_history_index))
        outer = QHBoxLayout(card)
        outer.setContentsMargins(10, 9, 10, 9)
        outer.setSpacing(11)

        cover = QLabel()
        cover.setObjectName("historyCover")
        cover._persistent_cover = True
        cover.setFixedSize(82, 98)
        cover.setAlignment(Qt.AlignCenter)
        outer.addWidget(cover)
        self.apply_history_cover(record, cover)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(6)
        title_text = record.get("title") or Path(record.get("path", "")).stem or "未命名漫画"
        title_label = QLabel(QFontMetrics(self.font()).elidedText(title_text, Qt.ElideRight, 520))
        title_label.setObjectName("historyTitle")
        title_label.setToolTip(title_text)
        info.addWidget(title_label)

        file_text = record.get("file") or Path(record.get("path", "")).name or "-"
        meta_items = [file_text]
        fmt = record.get("format") or Path(file_text).suffix.lstrip(".").upper()
        if fmt:
            meta_items.append(fmt.upper())
        outputs = record.get("outputs") or []
        if isinstance(outputs, list) and len(outputs) > 1:
            meta_items.append(f"{len(outputs)} 个文件")
        album_id = record.get("album_id") or record.get("id") or ""
        if album_id:
            meta_items.append(f"ID {album_id}")
        meta_label = QLabel("  ·  ".join(meta_items))
        meta_label.setObjectName("historyMeta")
        meta_label.setToolTip("  ·  ".join(meta_items))
        info.addWidget(meta_label)

        path_text = record.get("path", "") or record.get("pdf_path", "") or record.get("image_dir", "")
        path_label = QLabel(QFontMetrics(self.font()).elidedText(path_text, Qt.ElideMiddle, 620))
        path_label.setObjectName("historyPath")
        path_label.setToolTip(path_text)
        info.addWidget(path_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        read = QPushButton("阅读")
        read.setObjectName("historyAction")
        read.clicked.connect(lambda checked=False, idx=index: self.select_history_record(idx, open_reader=True))
        locate = QPushButton("位置")
        locate.setObjectName("historyAction")
        locate.clicked.connect(lambda checked=False, idx=index: self.select_history_record(idx, open_location=True))
        status = QLabel("已完成" if index >= 0 else "空")
        status.setObjectName("historyBadge")
        actions.addWidget(status)
        actions.addStretch()
        actions.addWidget(locate)
        actions.addWidget(read)
        info.addLayout(actions)
        outer.addLayout(info, 1)

        if index >= 0:
            card.mousePressEvent = lambda event, idx=index: self.handle_history_card_mouse_press(event, idx)
            card.mouseDoubleClickEvent = lambda event, idx=index: self.select_history_record(idx, open_reader=True)
        return card

    def history_card_style(self, selected: bool = False) -> str:
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
        if album_id:
            album = self.detail_cache.get(album_id) or self.albums.get(album_id)
            if album:
                self.apply_loading_movie(label, QSize(72, 72))
                self.request_cover(album, label)
                return
            album = AlbumMeta(album_id=album_id, title=record.get("title", ""), url="", cover_url=cover_url)
            self.apply_loading_movie(label, QSize(72, 72))
            self.request_cover(album, label)
            return
        local_cover = self.find_history_local_cover(record)
        if local_cover:
            pixmap = QPixmap(str(local_cover))
            if not pixmap.isNull():
                self.set_cover_on_label(label, pixmap)
                return
        label.setText("本地")

    def find_history_local_cover(self, record: Dict[str, str]) -> Optional[Path]:
        path_text = record.get("image_dir", "") or record.get("path", "")
        if not path_text:
            return None
        path = Path(path_text).expanduser()
        image_dir = self.resolve_history_image_dir(path)
        if image_dir:
            images = self.collect_local_reader_images(image_dir)
            return images[0] if images else None
        if path.suffix.lower() in IMAGE_SUFFIXES and path.exists():
            return path
        return None

    def select_history_record(self, index: int, open_reader: bool = False, open_location: bool = False):
        if index < 0 or index >= len(self.download_history):
            return
        old_index = self.selected_history_index
        self.selected_history_index = index
        for idx in {old_index, index}:
            card = self.history_card_by_index.get(idx)
            if card:
                card.setStyleSheet(self.history_card_style(idx == self.selected_history_index))
        if open_reader:
            self.open_selected_history_reading()
        elif open_location:
            self.open_selected_history_location()

    def handle_history_card_mouse_press(self, event, index: int):
        if index < 0 or index >= len(self.download_history):
            return
        if event.button() == Qt.RightButton:
            self.select_history_record(index)
            self.show_history_context_menu(index, event.globalPos())
            return
        if event.button() == Qt.LeftButton:
            self.select_history_record(index)

    def show_history_context_menu(self, index: int, global_pos):
        if index < 0 or index >= len(self.download_history):
            return
        menu = QMenu(self)
        read_action = menu.addAction("阅读")
        locate_action = menu.addAction("打开位置")
        menu.addSeparator()
        delete_action = menu.addAction("删除记录")
        delete_action.setObjectName("dangerAction")
        action = menu.exec_(global_pos)
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
        local_paths = self.history_record_local_paths(record)
        if confirm:
            message = f"确定删除历史记录并删除本地漫画资源吗？\n\n{title}"
            if local_paths:
                message += "\n\n将删除：\n" + "\n".join(str(path) for path in local_paths[:6])
                if len(local_paths) > 6:
                    message += f"\n... 共 {len(local_paths)} 个路径"
            else:
                message += "\n\n没有找到对应的本地文件，只会删除历史记录。"
            answer = QMessageBox.question(self, "删除本地漫画", message)
            if answer != QMessageBox.Yes:
                return
        self.download_history.pop(index)
        deleted, failed = self.delete_history_local_paths(local_paths)
        if self.selected_history_index == index:
            self.selected_history_index = -1
        elif self.selected_history_index > index:
            self.selected_history_index -= 1
        if failed:
            self.log(f"历史记录已删除，本地资源部分删除失败：{title}，失败 {len(failed)} 个。")
            QMessageBox.warning(self, "部分删除失败", "\n".join(f"{path}: {error}" for path, error in failed[:8]))
        else:
            self.log(f"已删除历史记录和本地资源：{title}，删除 {deleted} 个路径。")
        self.refresh_history_table()
        self.save_local_cache()

    def delete_selected_history_record(self):
        if self.selected_history_index < 0 or self.selected_history_index >= len(self.download_history):
            QMessageBox.information(self, "提示", "请先选择一条历史记录。")
            return
        self.delete_history_record(self.selected_history_index)

    def clear_download_history(self):
        if not self.download_history:
            return
        answer = QMessageBox.question(
            self,
            "清空历史和本地漫画",
            f"确定清空全部 {len(self.download_history)} 条历史记录，并删除这些历史对应的本地漫画资源吗？",
        )
        if answer != QMessageBox.Yes:
            return
        all_paths = []
        for record in self.download_history:
            all_paths.extend(self.history_record_local_paths(record))
        deleted, failed = self.delete_history_local_paths(all_paths)
        self.download_history.clear()
        self.selected_history_index = -1
        self.refresh_history_table()
        self.save_local_cache()
        if failed:
            QMessageBox.warning(self, "部分删除失败", "\n".join(f"{path}: {error}" for path, error in failed[:8]))
        self.log(f"已清空历史记录并删除本地资源：删除 {deleted} 个路径，失败 {len(failed)} 个。")

    def sync_history_with_local_files(self):
        if getattr(self, "_syncing_history_files", False):
            return
        self._syncing_history_files = True
        try:
            kept = []
            removed = 0
            for record in self.download_history:
                if self.history_record_has_local_file(record):
                    kept.append(record)
                else:
                    removed += 1
            if removed:
                self.download_history = kept
                self.selected_history_index = -1
                self.save_local_cache()
                self.log(f"已同步历史记录：移除本地文件不存在的记录 {removed} 条。")
        finally:
            self._syncing_history_files = False

    def history_record_has_local_file(self, record: Dict[str, str]) -> bool:
        return any(path.exists() for path in self.history_record_local_paths(record))

    def history_record_local_paths(self, record: Dict[str, str]) -> List[Path]:
        candidates: List[Path] = []
        for key in ("path", "pdf_path", "image_dir"):
            value = record.get(key) or ""
            if value:
                candidates.append(Path(value).expanduser())
        outputs = record.get("outputs") or []
        if isinstance(outputs, list):
            candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())
        for candidate in list(candidates):
            image_dir = self.resolve_history_image_dir(candidate)
            if image_dir:
                candidates.append(image_dir)

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

    def delete_history_local_paths(self, paths: List[Path]) -> tuple[int, List[tuple[Path, str]]]:
        deleted = 0
        failed: List[tuple[Path, str]] = []
        for path in self.sorted_delete_paths(paths):
            if self.is_protected_runtime_path(path):
                continue
            if not path.exists():
                continue
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                deleted += 1
            except Exception as exc:
                failed.append((path, str(exc)))
        return deleted, failed

    def sorted_delete_paths(self, paths: List[Path]) -> List[Path]:
        unique: Dict[str, Path] = {}
        for path in paths:
            try:
                normalized = str(path.resolve(strict=False)).lower()
            except Exception:
                normalized = str(path).lower()
            unique[normalized] = path
        return sorted(unique.values(), key=lambda item: len(item.parts), reverse=True)

    def is_protected_runtime_path(self, path: Path) -> bool:
        try:
            target = path.resolve(strict=False)
            protected = {
                self.data_root.resolve(strict=False),
                self.default_output_dir.resolve(strict=False),
                self.reader_cache_root().resolve(strict=False),
                self.cache_file.parent.resolve(strict=False),
            }
            return target in protected
        except Exception:
            return False

    def selected_history_record(self) -> Optional[Dict[str, str]]:
        if not self.download_history:
            return None
        row = self.selected_history_index
        if row < 0 or row >= len(self.download_history):
            return None
        return self.download_history[row]

    def open_selected_history_reading(self):
        record = self.selected_history_record()
        if not record:
            QMessageBox.information(self, "提示", "请先选择一条历史记录。")
            return
        mode = self.selected_history_read_mode()
        path_text = record.get("path", "") or record.get("pdf_path", "") or record.get("image_dir", "")
        path = Path(path_text).expanduser() if path_text else Path()
        images, pdf_path = self.resolve_history_reader_sources_for_record(record, mode)
        if not images and pdf_path is None:
            target = str(path) if path_text else "历史记录中的本地文件"
            QMessageBox.warning(self, "文件不存在", f"找不到可阅读的本地文件：{target}")
            return

        if images or pdf_path is not None:
            title = record.get("title") or path.stem
            dialog = HdMangaReaderWindow(f"漫画阅读 - {title}")
            self.local_reader_dialogs.append(dialog)
            dialog.destroyed.connect(lambda _=None, dialog=dialog: self.forget_local_reader_dialog(dialog))
            try:
                if images:
                    dialog.start_decode_image_paths(images)
                elif pdf_path is not None:
                    fallback_images = self.resolve_history_reader_sources_for_record(record, "original")[0]
                    if not dialog.start_decode_pdf(pdf_path, fallback_images):
                        raise RuntimeError(f"PDF 解码失败：{pdf_path}")
                dialog.showMaximized()
                dialog.raise_()
                dialog.activateWindow()
                return
            except Exception as exc:
                self.forget_local_reader_dialog(dialog)
                dialog.deleteLater()
                self.log(f"本地阅读器打开失败：{exc}")
                QMessageBox.warning(self, "阅读失败", f"本地阅读器解析失败，已改用系统打开。\n{exc}")

        if path_text and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def selected_history_read_mode(self) -> str:
        combo = getattr(self, "history_read_mode_combo", None)
        text = combo.currentText() if combo else "自动"
        if text == "PDF":
            return "pdf"
        if text == "原文件":
            return "original"
        return "auto"

    def resolve_history_reader_sources_for_record(self, record: Dict[str, str], mode: str = "auto") -> tuple[List[Path], Optional[Path]]:
        pdf_path = self.resolve_history_pdf_path(record)
        image_dir = self.resolve_history_image_dir_from_record(record)
        images = self.collect_local_reader_images(image_dir) if image_dir else []
        path_text = record.get("path") or ""
        if path_text:
            direct_images, direct_pdf = collect_reader_files(Path(path_text).expanduser())
            if not images and direct_images:
                images = direct_images
            if pdf_path is None and direct_pdf is not None:
                pdf_path = direct_pdf

        if mode == "pdf":
            if pdf_path is not None:
                return [], pdf_path
            return images, None
        if mode == "original":
            if images:
                return images, None
            return [], pdf_path
        if images:
            return images, None
        return [], pdf_path

    def resolve_history_reader_sources(self, path: Path) -> tuple[List[Path], Optional[Path]]:
        images, pdf_path = collect_reader_files(path)
        image_dir = self.resolve_history_image_dir(path)
        if image_dir:
            dir_images, dir_pdf = collect_reader_files(image_dir)
            if dir_images:
                return dir_images, None
            if pdf_path is None and dir_pdf is not None:
                pdf_path = dir_pdf
        return images, pdf_path

    def resolve_history_pdf_path(self, record: Dict[str, str]) -> Optional[Path]:
        candidates: List[Path] = []
        for key in ("pdf_path", "path"):
            value = record.get(key) or ""
            if value:
                candidates.append(Path(value).expanduser())
        outputs = record.get("outputs") or []
        if isinstance(outputs, list):
            candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() == ".pdf":
                return candidate
            if candidate.is_dir():
                _, pdf_path = collect_reader_files(candidate)
                if pdf_path is not None:
                    return pdf_path
        return None

    def resolve_history_image_dir_from_record(self, record: Dict[str, str]) -> Optional[Path]:
        image_dir = record.get("image_dir") or ""
        if image_dir:
            candidate = Path(image_dir).expanduser()
            if candidate.exists() and self.collect_local_reader_images(candidate):
                return candidate
        for key in ("path", "pdf_path"):
            value = record.get(key) or ""
            if value:
                candidate = self.resolve_history_image_dir(Path(value).expanduser())
                if candidate:
                    return candidate
        outputs = record.get("outputs") or []
        if isinstance(outputs, list):
            for value in outputs:
                if str(value).strip():
                    candidate = self.resolve_history_image_dir(Path(str(value)).expanduser())
                    if candidate:
                        return candidate
        return None

    def open_selected_history_location(self):
        record = self.selected_history_record()
        if not record:
            QMessageBox.information(self, "提示", "请先选择一条历史记录。")
            return
        path_text = record.get("path", "") or record.get("pdf_path", "") or record.get("image_dir", "")
        path = Path(path_text).expanduser()
        target = path if path.is_dir() else path.parent
        if not target.exists():
            QMessageBox.warning(self, "路径不存在", f"找不到本地路径：{target}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def resolve_history_image_dir(self, path: Path) -> Optional[Path]:
        if path.is_dir():
            return path if self.collect_local_reader_images(path) else None
        if path.suffix.lower() in IMAGE_SUFFIXES:
            return path.parent
        if path.suffix.lower() == ".pdf":
            sibling = path.with_suffix("")
            if sibling.exists() and sibling.is_dir() and self.collect_local_reader_images(sibling):
                return sibling
            if " - " in path.stem:
                album_name, chapter_name = path.stem.split(" - ", 1)
                album_dir = path.parent / album_name
                chapter_dir = album_dir / chapter_name
                if chapter_dir.exists() and self.collect_local_reader_images(chapter_dir):
                    return chapter_dir
                if album_dir.exists() and self.collect_local_reader_images(album_dir):
                    return album_dir
            for candidate in sorted(path.parent.iterdir() if path.parent.exists() else []):
                if candidate.is_dir() and candidate.name.startswith(path.stem) and self.collect_local_reader_images(candidate):
                    return candidate
            album_id_match = re.search(r"(\d+)", path.stem)
            if album_id_match:
                album_id = album_id_match.group(1)
                for candidate in sorted(path.parent.iterdir() if path.parent.exists() else []):
                    if candidate.is_dir() and album_id in candidate.name and self.collect_local_reader_images(candidate):
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
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        title = QLabel("关于")
        title.setObjectName("panelTitle")
        version = QLabel(
            f"Comic18 Qt 版本：{APP_UI_VERSION}\n"
            f"JM App API 版本：{APP_VERSION}"
        )
        version.setStyleSheet("color:#334155;font-size:14px;line-height:1.5;")
        version.setTextInteractionFlags(Qt.TextSelectableByMouse)
        note = QLabel("当前版本支持榜单/搜索分页加载、封面域名池、后台阅读缓存、PDF/ZIP/图片导出。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b;")
        layout.addWidget(title)
        layout.addWidget(version)
        layout.addWidget(note)
        layout.addStretch()
        return panel

    def home_page_index(self):
        return 0

    def settings_page_index(self):
        return 2

    def history_page_index(self):
        return 3

    def about_page_index(self):
        return 4

    def queue_page_index(self):
        return 1

    def downloading_page_index(self):
        return 1

    def completed_page_index(self):
        return 1

    def login(self):
        username = self.login_user_edit.text().strip()
        password = self.login_pass_edit.text()
        cookie = self.login_cookie_edit.toPlainText().strip()
        if not username and not cookie:
            QMessageBox.information(self, "提示", "请输入账号，或粘贴已登录后的 Cookie。")
            return
        if username and not password and not cookie:
            QMessageBox.information(self, "提示", "请输入密码；如果站点要求安全验证，也请粘贴 Cookie。")
            return
        self.show_login_loading(
            "正在登录...",
            lambda: self.enter_app(username=username, password=password, cookie=cookie),
        )

    def eventFilter(self, obj, event):
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
        if hasattr(self, "result_grid") and self.result_total_count and not self.result_resize_pending:
            self.result_resize_pending = True
            QTimer.singleShot(120, self.refresh_result_layout)

    def refresh_result_layout(self):
        self.result_resize_pending = False
        total_pages = self.result_total_pages()
        if total_pages and self.current_result_page > total_pages:
            self.current_result_page = total_pages
        if hasattr(self, "result_grid"):
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
        self.settings_cache = self.current_settings_snapshot()
        self.save_local_cache()
        self.home_auto_loaded = False
        self.setMinimumSize(330, 460)
        self.resize(360, 500)
        self._center_window()
        self.stack.setCurrentWidget(self.login_page)
        self._fade_in(self.login_page, 260)

    def closeEvent(self, event):
        self.cancel_reader_chapter_workers()
        self.settings_cache = self.current_settings_snapshot()
        self.save_local_cache()
        super().closeEvent(event)

    def switch_page(self, index: int):
        self.clear_album_selection()
        if hasattr(self, "main_content_stack"):
            index = max(0, min(index, self.main_content_stack.count() - 1))
            self.main_content_stack.setCurrentIndex(index)
            button = getattr(self, "nav_buttons", {}).get(index)
            if button:
                button.setChecked(True)
            if index == self.history_page_index():
                self.refresh_history_table()
            self.animate_enter(self.main_content_stack.currentWidget(), 220, offset_y=14, scale_px=5)
            return
        self._fade_in(self.app_page, 160)

    def toggle_settings(self):
        self.switch_page(self.settings_page_index())

    def open_history_dialog(self):
        self.switch_page(self.history_page_index())

    def open_cookie_verifier(self):
        try:
            from .browser_cookie_dialog import BrowserCookieDialog
        except Exception as exc:
            QMessageBox.warning(
                self,
                "缺少组件",
                f"无法打开浏览器验证窗口：{exc}\n请安装 PyQtWebEngine。",
            )
            return

        dialog = BrowserCookieDialog(self, self.list_url_edit.text().strip() or LIST_URL)
        if dialog.exec_() != QDialog.Accepted:
            return
        header = dialog.cookie_header()
        if not header:
            QMessageBox.information(self, "提示", "没有读取到该站点 Cookie，请确认页面已完成验证。")
            return
        self.cookie_edit.setPlainText(header)
        self.login_cookie_edit.setPlainText(header)
        save_cookie_dict(parse_cookie_header(header))
        self.set_backend_status("Cookie 已更新", "ok")
        self.log("已从浏览器验证窗口同步 Cookie。")

    def reader_cache_root(self) -> Path:
        return reader_cache_dir()

    def should_keep_saved_output_dir(self, output_dir: str) -> bool:
        if not output_dir:
            return False
        try:
            saved = Path(output_dir).expanduser().resolve(strict=False)
            project_downloads = Path(__file__).resolve().parents[2] / "downloads"
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
            "页面/设置缓存：{json}\n"
            "SQLite 基础库：{db}\n"
            "阅读图片缓存：{reader}".format(
                json=self.cache_file,
                db=self.comic_db.path,
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
        self.save_local_cache()
        self.log(f"已清理当前结果缓存：{cache_key}，清理页面缓存 {removed} 组。")
        QMessageBox.information(self, "清理完成", "已清理当前分类/榜单的页面缓存。点击“更新”会重新联网加载。")

    def clear_all_runtime_cache(self):
        answer = QMessageBox.question(
            self,
            "确认清理全部缓存",
            "将清理页面结果缓存、详情缓存、封面内存缓存、SQLite 基础库和阅读图片缓存。\n设置与下载历史会保留。是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        result_count = len(self.result_cache)
        detail_count = len(self.detail_cache)
        self.result_cache.clear()
        self.detail_cache.clear()
        self.cover_cache.clear()
        self.cover_pending.clear()
        self.cover_fallback_urls.clear()
        self.cache_restore_miss_keys.clear()

        removed_paths = []
        for path in [self.comic_db.path, self.comic_db.path.with_suffix(".sqlite3-wal"), self.comic_db.path.with_suffix(".sqlite3-shm")]:
            try:
                if path.exists():
                    path.unlink()
                    removed_paths.append(str(path))
            except Exception as exc:
                self.log(f"SQLite 缓存删除失败 {path}: {exc}")
        reader_cache = self.reader_cache_root()
        try:
            if reader_cache.exists():
                shutil.rmtree(reader_cache, ignore_errors=True)
                removed_paths.append(str(reader_cache))
        except Exception as exc:
            self.log(f"阅读缓存删除失败 {reader_cache}: {exc}")

        self.comic_db = ComicCacheDB()
        self.save_local_cache()
        self.update_cache_path_label()
        self.log(f"已清理全部缓存：页面 {result_count} 组，详情 {detail_count} 本。")
        QMessageBox.information(
            self,
            "清理完成",
            "已清理全部运行缓存。\n"
            f"页面缓存：{result_count} 组\n"
            f"详情缓存：{detail_count} 本\n"
            f"已删除：{len(removed_paths)} 个缓存路径",
        )

    def clean_broken_cache(self):
        roots = [self.reader_cache_root()]
        removed_files = 0
        removed_dirs = 0
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*"), reverse=True):
                try:
                    if path.is_file():
                        broken = path.stat().st_size == 0
                        if path.suffix.lower() in IMAGE_SUFFIXES and not broken:
                            reader = QImageReader(str(path))
                            broken = not reader.canRead()
                        if broken:
                            path.unlink(missing_ok=True)
                            removed_files += 1
                    elif path.is_dir() and not any(path.iterdir()):
                        path.rmdir()
                        removed_dirs += 1
                except Exception as exc:
                    self.log(f"缓存清理跳过 {path}: {exc}")
        self.log(f"缓存清理完成：删除损坏文件 {removed_files} 个，空目录 {removed_dirs} 个。")
        QMessageBox.information(self, "缓存清理完成", f"删除损坏文件 {removed_files} 个，空目录 {removed_dirs} 个。")

    def export_cache_bundle(self):
        directory = QFileDialog.getExistingDirectory(self, "选择缓存导出目录", str(self.data_root))
        if not directory:
            return
        target = Path(directory).expanduser() / "comic18_cache"
        target.mkdir(parents=True, exist_ok=True)
        if self.comic_db.path.exists():
            shutil.copy2(self.comic_db.path, target / self.comic_db.path.name)
        reader_cache = self.reader_cache_root()
        if reader_cache.exists():
            shutil.copytree(reader_cache, target / "reader_cache", dirs_exist_ok=True)
        self.log(f"缓存已导出：{target}")
        QMessageBox.information(self, "导出完成", f"缓存已导出到：{target}")

    def import_cache_bundle(self):
        directory = QFileDialog.getExistingDirectory(self, "选择 comic18_cache 缓存目录", str(self.data_root))
        if not directory:
            return
        source = Path(directory).expanduser()
        db_source = source / self.comic_db.path.name
        reader_source = source / "reader_cache"
        imported = []
        if db_source.exists():
            self.comic_db.path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_source, self.comic_db.path)
            imported.append("SQLite 基础库")
        if reader_source.exists():
            shutil.copytree(reader_source, self.reader_cache_root(), dirs_exist_ok=True)
            imported.append("阅读图片缓存")
        if not imported:
            QMessageBox.warning(self, "导入失败", "未找到可导入的 SQLite 或 reader_cache。")
            return
        self.log(f"缓存已导入：{', '.join(imported)}")
        QMessageBox.information(self, "导入完成", f"已导入：{', '.join(imported)}")

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
        return "day"

    def result_cache_key(self) -> str:
        ids = split_ids(self.id_edit.text())
        if ids:
            return "ids:" + ",".join(ids)
        query = self.search_edit.text().strip()
        if query:
            return f"search:{query}"
        if self.active_category:
            return f"category:v2:{self.active_category}"
        return f"rank:{self.selected_rank_type()}"

    def start_rank_scrape(self, rank_type: str):
        self.clear_album_selection()
        self.search_edit.clear()
        self.id_edit.clear()
        self.active_category = ""
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
        return {"day": "日榜", "week": "周榜", "month": "月榜"}.get(rank_type, "榜单")

    def refresh_current_results(self):
        self.clear_album_selection()
        current_page = self.current_result_page
        if self.result_albums:
            self.render_result_page()
            self.result_stack.setCurrentWidget(self.result_scroll)
            self.set_backend_status("已刷新当前页", "ok")
            self.log(f"已重绘当前页：第 {self.current_result_page} 页。")
            return
        self.log("当前页面没有已加载结果，请点击更新重新联网加载。")

    def update_current_results(self):
        self.clear_album_selection()
        cache_key = self.result_cache_key()
        self.result_cache.pop(cache_key, None)
        self.cache_restore_miss_keys.discard(cache_key)
        if self.cache_restore_worker and self.cache_restore_worker.isRunning():
            self.cache_restore_worker.requestInterruption()
            self.cache_restore_worker = None
        for album in self.result_albums:
            if album is not None:
                self.detail_cache.pop(album.album_id, None)
                self.cover_cache.pop(album.album_id, None)
        self.force_network_once = True
        self.log("已清除当前结果缓存，正在重新联网更新漫画列表。")
        self.start_scrape()

    def restore_results_from_cache(self, cache_key: str) -> bool:
        cached = self.result_cache.get(cache_key)
        if not cached:
            return False
        else:
            self.log(f"已从页面缓存恢复 {len(cached)} 本漫画。")
        if not cached:
            return False
        self.restore_album_list(cache_key, cached, write_db=False)
        self.set_backend_status("已从缓存加载", "ok")
        return True

    def restore_album_list(self, cache_key: str, albums: List[AlbumMeta], write_db: bool = False):
        restored = [copy.deepcopy(album) for album in albums]
        self.reset_results()
        self.current_result_cache_key = cache_key
        self.result_total_count = len(restored)
        self.result_albums = restored
        self.albums = {album.album_id: album for album in restored}
        self.detail_cache.update({album.album_id: copy.deepcopy(album) for album in restored})
        if write_db:
            for album in restored:
                self.cache_album_async(album)
        self.results_revealed = False
        self.current_result_page = max(1, min(self.current_result_page, self.result_total_pages() or 1))
        self.reveal_results()
        loaded = len(restored)
        self.statusBar().showMessage(f"已加载 {loaded}/{self.result_total_count} 条漫画数据。")
        self.update_page_controls()

    def start_async_cache_restore(self, cache_key: str) -> bool:
        if not (cache_key.startswith("rank:") or cache_key.startswith("category:")):
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
        self.restore_album_list(cache_key, albums, write_db=False)
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
            proxy=self.proxy_edit.text().strip(),
            detail_threads=self.detail_threads.value(),
            protocol_parser=self.protocol_parser.isChecked() if hasattr(self, "protocol_parser") else True,
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
        config.detail_threads = max(1, min(2, config.detail_threads))
        config.delay_min = max(0.2, min(config.delay_min, 1.0))
        config.delay_max = max(config.delay_min, min(config.delay_max, 2.0))
        return config

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
        cache_key = self.result_cache_key()
        if self.force_network_once:
            self.force_network_once = False
        elif not append and self.restore_results_from_cache(cache_key):
            self.loaded_source_pages = max(1, (len(self.result_albums) + 79) // 80)
            return
        elif not append and self.start_async_cache_restore(cache_key):
            return
        self.set_backend_status("正在后台获取更多" if append else "正在请求", "busy")
        if not append:
            self.reset_results()
            self.loaded_source_pages = 0
            self.auto_load_has_more = True
        self.current_result_cache_key = cache_key
        worker = ScrapeWorker(
            list_url=self.list_url_edit.text().strip() or LIST_URL,
            ids=split_ids(self.id_edit.text()),
            include_detail=self.detail_check.isChecked(),
            config=self.network_config(),
            search_query=self.search_edit.text().strip(),
            rank_type=self.selected_rank_type(),
            category=self.active_category,
            list_pages=source_page,
        )
        self.scrape_worker = worker
        worker.total_known.connect(lambda total, worker=worker, source_page=source_page, append=append: self.on_scrape_total_known(total, source_page, append) if worker is self.scrape_worker else None)
        worker.album_found_at.connect(lambda index, album, worker=worker, source_page=source_page, append=append: self.on_scrape_album_found(index, album, source_page, append) if worker is self.scrape_worker else None)
        worker.log.connect(lambda message, worker=worker: self.log(message) if worker is self.scrape_worker else None)
        worker.progress.connect(lambda done, total, worker=worker: self.set_progress(done, total) if worker is self.scrape_worker else None)
        worker.finished_ok.connect(
            lambda worker=worker, source_page=source_page, append=append: self.on_scrape_finished(source_page, append) if worker is self.scrape_worker else None
        )
        worker.failed.connect(lambda message, worker=worker: self.on_scrape_failed(message) if worker is self.scrape_worker else None)
        self.switch_page(self.home_page_index())
        if not append:
            self.start_loading("正在获取漫画资源")
        self.progress.setValue(0)
        worker.start()

    def on_scrape_total_known(self, total: int, source_page: int, append: bool):
        if append:
            base = len([album for album in self.result_albums if album is not None])
            self.append_start_index = base
            self.set_result_total(base + total)
        else:
            self.set_result_total(total)

    def on_scrape_album_found(self, index: int, album: AlbumMeta, source_page: int, append: bool):
        if append:
            existing_ids = {item.album_id for item in self.result_albums if item is not None}
            if album.album_id in existing_ids:
                self.log(f"跳过重复漫画：{album.title}（{album.album_id}）")
                return
            target_index = self.append_start_index + index
            self.upsert_album_at(target_index, album)
            self.log(f"加载漫画 {target_index + 1}：{album.title}（{album.album_id}）")
            return
        self.upsert_album_at(index, album)
        self.log(f"加载漫画 {index + 1}：{album.title}（{album.album_id}）")

    def on_scrape_finished(self, source_page: int, append: bool):
        loaded_count = len([album for album in self.result_albums if album is not None])
        self.loaded_source_pages = max(self.loaded_source_pages, source_page)
        if append and loaded_count < self.result_total_count:
            self.set_result_total(loaded_count)
        self.auto_loading_next_page = False
        if loaded_count == 0 or (append and loaded_count <= (source_page - 1) * 80):
            self.auto_load_has_more = False
        self.scrape_worker = None
        self.task_done("采集完成。", self.home_page_index())

    def on_scrape_failed(self, message: str):
        self.scrape_worker = None
        self.task_failed(message)

    def cleanup_retired_scrape_worker(self, worker: ScrapeWorker):
        if worker in self.retired_scrape_workers:
            self.retired_scrape_workers.remove(worker)

    def load_current_chapters(self):
        album = self.current_album()
        if not album:
            QMessageBox.information(self, "提示", "请先选择一个漫画。")
            return
        cached = self.detail_cache.get(album.album_id)
        if cached and cached.chapters:
            self.albums[album.album_id] = copy.deepcopy(cached)
            self.show_chapters(album.album_id)
            self.set_backend_status("已从缓存加载", "ok")
            self.log(f"已从缓存加载章节：{cached.title}")
            return
        if album.chapters:
            self.detail_cache[album.album_id] = copy.deepcopy(album)
            self.show_chapters(album.album_id)
            self.set_backend_status("已从缓存加载", "ok")
            self.log(f"已从缓存加载章节：{album.title}")
            return
        if self.chapter_worker and self.chapter_worker.isRunning():
            QMessageBox.information(self, "忙碌", "已有章节加载任务正在运行。")
            return
        self.log(f"开始加载章节：{album.title}（{album.album_id}）")
        self.chapter_worker = ChapterWorker(album, self.network_config())
        self.chapter_worker.chapters_loaded.connect(self.on_chapters_loaded)
        self.chapter_worker.log.connect(self.log)
        self.chapter_worker.failed.connect(self.task_failed)
        self.set_backend_status("正在加载章节", "busy")
        self.loading_label.setText("正在加载章节")
        self.loading_label.show()
        self.chapter_worker.start()

    def on_chapters_loaded(self, album_id: str, chapters: List[ChapterMeta]):
        if album_id in self.albums:
            self.albums[album_id].chapters = chapters
            self.update_album_row(self.albums[album_id])
            self.detail_cache[album_id] = copy.deepcopy(self.albums[album_id])
            self.save_local_cache()
            self.log(f"章节加载完成：{self.albums[album_id].title}，共 {len(chapters)} 章。")
        self.switch_page(self.home_page_index())
        self.show_chapters(album_id)
        QTimer.singleShot(80, self.refresh_task_controls)

    def reset_results(self):
        self.albums.clear()
        self.row_by_id.clear()
        self.card_by_id.clear()
        self.checkmark_by_id.clear()
        self.card_click_timers.clear()
        self.selected_album_ids.clear()
        self.cover_targets.clear()
        self.cover_pending.clear()
        self.cover_fallback_urls.clear()
        for worker in list(self.cover_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
        self.cover_workers.clear()
        self.result_albums = []
        self.result_total_count = 0
        self.current_result_page = 1
        self.results_revealed = False
        self.result_render_pending = False
        self.result_page_switching = False
        self.result_render_generation += 1
        self.clear_result_grid()
        if hasattr(self, "result_stack"):
            self.result_stack.setCurrentWidget(self.result_loading_page)
        if hasattr(self, "chapter_table"):
            self.chapter_table.setRowCount(0)
        if hasattr(self, "detail_card"):
            self.detail_card.setText("未选择 ID")
        if hasattr(self, "tags_card"):
            self.tags_card.setText("标签：-")
        if hasattr(self, "cover_label"):
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText("暂无封面")
        self.update_page_controls()

    def set_result_total(self, total: int):
        new_total = max(0, total)
        old_albums = list(self.result_albums)
        self.result_total_count = new_total
        self.result_albums = [None] * self.result_total_count
        for index, album in enumerate(old_albums[: self.result_total_count]):
            self.result_albums[index] = album
        if not any(self.result_albums):
            self.current_result_page = 1
            self.results_revealed = False
            self.clear_result_grid()
            self.result_stack.setCurrentWidget(self.result_loading_page)
        if self.result_total_count == 0:
            self.reveal_results()
        self.update_page_controls()

    def upsert_album_at(self, index: int, album: AlbumMeta):
        if index < 0:
            return
        if index >= len(self.result_albums):
            self.result_albums.extend([None] * (index + 1 - len(self.result_albums)))
            self.result_total_count = len(self.result_albums)
        self.result_albums[index] = album
        self.albums[album.album_id] = album
        self.detail_cache[album.album_id] = copy.deepcopy(album)
        self.cache_album_async(album)
        start, end = self.current_page_bounds()
        if not self.results_revealed:
            if start <= index < end:
                self.reveal_results()
        elif start <= index < end:
            if self.result_stack.currentWidget() is self.result_loading_page:
                self.render_result_page()
                self.result_stack.setCurrentWidget(self.result_scroll)
                self._fade_in(self.result_scroll, 220)
            else:
                if not self.update_album_card_content(album):
                    self.append_visible_album_card(album)
        loaded = sum(1 for item in self.result_albums if item is not None)
        self.statusBar().showMessage(f"已载入 {loaded}/{self.result_total_count} 条漫画数据。")
        self.update_page_controls()

    def cache_album_async(self, album: AlbumMeta):
        snapshot = copy.deepcopy(album)

        def write_album():
            try:
                ComicCacheDB().upsert_album(snapshot)
            except Exception as exc:
                self.async_log.emit(f"SQLite 缓存写入失败：{exc}")

        self.db_write_pool.submit(write_album)

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

    def reveal_results(self):
        self.results_revealed = True
        self.render_result_page()
        self.result_stack.setCurrentWidget(self.result_scroll)
        self._fade_in(self.result_scroll, 260)

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
                title.setText(QFontMetrics(title.font()).elidedText(album.title or "-", Qt.ElideRight, card_width))
                title.setToolTip(album.title)
            meta = card.findChild(QLabel, "albumMeta")
            if meta:
                meta.setText(f"❤ {album.likes}   {album.page_count}")
            sub = card.findChild(QLabel, "albumSub")
            if sub:
                sub.setText(f"作者：{album.author}\n章节：{len(album.chapters) if album.chapters else '-'}")
            card.setStyleSheet(self.album_card_style(album.album_id in self.selected_album_ids))
            return True
        except RuntimeError:
            return False

    def append_visible_album_card(self, album: AlbumMeta):
        if album.album_id in self.card_by_id:
            self.update_album_card_content(album)
            return
        columns = self.result_columns()
        visible_index = len(self.card_by_id)
        card = self.create_album_card(album)
        row = visible_index // columns
        col = visible_index % columns
        self.result_grid.addWidget(card, row, col)
        self.card_by_id[album.album_id] = card
        self.safe_fade_in_card(card)
        self.result_grid.setRowStretch((visible_index + columns - 1) // columns, 1)
        for col_index in range(columns):
            self.result_grid.setColumnStretch(col_index, 1)
        self.update_page_controls()

    def upsert_album(self, album: AlbumMeta):
        self.albums[album.album_id] = album
        self.detail_cache[album.album_id] = copy.deepcopy(album)
        self.statusBar().showMessage(f"已载入 {len(self.albums)} 条漫画数据。")

    def update_album_row(self, album: AlbumMeta):
        self.albums[album.album_id] = album
        self.detail_cache[album.album_id] = copy.deepcopy(album)

    def render_result_page(self):
        self.clear_result_grid()
        generation = self.result_render_generation
        self.row_by_id.clear()
        self.card_by_id.clear()
        self.checkmark_by_id.clear()
        self.clear_card_click_timers()
        start, end = self.current_page_bounds()
        visible_index = 0
        columns = self.result_columns()
        for index in range(start, end):
            if index >= len(self.result_albums):
                break
            album = self.result_albums[index]
            if album is None:
                continue
            card = self.create_album_card(album)
            row = visible_index // columns
            col = visible_index % columns
            self.result_grid.addWidget(card, row, col)
            self.card_by_id[album.album_id] = card
            QTimer.singleShot(
                visible_index * 18,
                lambda card=card, generation=generation: self.safe_fade_in_card(card, generation),
            )
            visible_index += 1
        self.result_grid.setRowStretch((visible_index + columns - 1) // columns, 1)
        for col in range(columns):
            self.result_grid.setColumnStretch(col, 1)
        self.update_page_controls()

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
        except RuntimeError:
            pass

    def clear_result_grid(self):
        self.result_render_generation += 1
        self.clear_card_click_timers()
        for row in range(20):
            self.result_grid.setRowStretch(row, 0)
        for col in range(8):
            self.result_grid.setColumnStretch(col, 0)
        while self.result_grid.count():
            item = self.result_grid.takeAt(0)
            widget = item.widget()
            if widget:
                self.stop_widget_animations(widget)
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

    def create_album_card(self, album: AlbumMeta) -> QFrame:
        card = AlbumCard()
        card.setObjectName("albumCard")
        card_width = self.result_card_width()
        cover_width = max(112, min(148, card_width - 26))
        cover_height = int(cover_width * 1.32)
        card_height = cover_height + 78
        card.setFixedSize(card_width, card_height)
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet(self.album_card_style(album.album_id in self.selected_album_ids))
        card.mousePressEvent = lambda event, album_id=album.album_id: self.schedule_album_single_click(album_id)
        card.mouseDoubleClickEvent = lambda event, album_id=album.album_id: self.handle_album_double_click(album_id)
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(lambda pos, card=card, album_id=album.album_id: self.show_album_context_menu(album_id, card.mapToGlobal(pos)))

        layout = QVBoxLayout(card)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)

        top = QHBoxLayout()
        checkmark = QLabel("✓")
        checkmark.setObjectName("albumCheckmark")
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
        meta = QLabel(f"❤ {album.likes}   {album.page_count}")
        meta.setObjectName("albumMeta")
        meta.setStyleSheet("color:#475569;font-size:11px;")
        meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(checkmark)
        top.addStretch()
        top.addWidget(meta)
        layout.addLayout(top)

        cover = QLabel()
        cover.setObjectName("albumCover")
        cover.setFixedSize(cover_width, cover_height)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet("background:#eef3f8;border:1px solid #dde6f0;border-radius:6px;color:#8491a5;")
        self.apply_loading_movie(cover, QSize(min(cover_width, 120), min(cover_height, 95)))
        layout.addWidget(cover, 0, Qt.AlignHCenter)
        self.request_cover(album, cover)

        title = QLabel()
        title.setObjectName("albumTitle")
        title.setWordWrap(False)
        title.setFixedHeight(20)
        title.setToolTip(album.title)
        title.setStyleSheet("font-weight:600;color:#1f2937;")
        title_width = max(60, card_width - 10)
        title.setText(QFontMetrics(title.font()).elidedText(album.title or "-", Qt.ElideRight, title_width))
        layout.addWidget(title)

        sub = QLabel(f"作者：{album.author}\n章节：{len(album.chapters) if album.chapters else '-'}")
        sub.setObjectName("albumSub")
        sub.setWordWrap(True)
        sub.setFixedHeight(30)
        sub.setStyleSheet("color:#64748b;font-size:11px;")
        layout.addWidget(sub)
        return card

    def result_columns(self) -> int:
        if not hasattr(self, "result_scroll"):
            return 4
        width = max(1, self.result_scroll.viewport().width())
        return max(3, min(5, width // 190))

    def result_page_size(self) -> int:
        return self.result_columns() * RESULT_ROWS

    def result_card_width(self) -> int:
        columns = self.result_columns()
        viewport_width = max(360, self.result_scroll.viewport().width())
        margins = 24
        spacing = self.result_grid.horizontalSpacing() * max(0, columns - 1)
        return max(142, min(210, int((viewport_width - margins - spacing) / columns)))

    @staticmethod
    def album_card_style(selected: bool) -> str:
        border = "#2f80ed" if selected else "#dfe7f2"
        background = "#f8fbff" if selected else "#ffffff"
        return (
            f"QFrame#albumCard {{ background:{background}; border:1px solid {border}; "
            "border-radius:8px; } "
            "QFrame#albumCard[hovered=\"true\"] { background:#f8fbff; border:1px solid #9cc7ff; }"
        )

    def schedule_album_single_click(self, album_id: str):
        timer = self.card_click_timers.get(album_id)
        if timer and timer.isActive():
            timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda album_id=album_id: self.toggle_album_selection(album_id))
        self.card_click_timers[album_id] = timer
        timer.start(105)

    def handle_album_double_click(self, album_id: str):
        timer = self.card_click_timers.get(album_id)
        if timer and timer.isActive():
            timer.stop()
        self.open_album_detail(album_id)

    def show_album_context_menu(self, album_id: str, global_pos: QPoint):
        self.clear_album_selection()
        album = self.albums.get(album_id)
        if not album:
            return
        menu = QMenu(self)
        add_action = menu.addAction("加入下载")
        read_action = menu.addAction("阅读")
        detail_action = menu.addAction("查看详情")
        action = menu.exec_(global_pos)
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
        self.current_album_id = album_id
        self.ensure_detail_dialog()
        self.show_chapters(album_id)
        self.fit_detail_dialog()
        self.detail_dialog.show()
        self.animate_window_enter(self.detail_dialog)
        self.detail_dialog.raise_()
        self.detail_dialog.activateWindow()

    def ensure_detail_dialog(self):
        if getattr(self, "detail_dialog", None) is not None:
            return
        self.detail_dialog = DetailDialog()
        self.detail_dialog.setWindowTitle("漫画详情")
        self.detail_dialog.closed.connect(self.on_detail_dialog_closed)
        self.detail_dialog.setMinimumSize(460, 420)
        self.detail_dialog.setMaximumSize(760, 920)
        layout = QVBoxLayout(self.detail_dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = self._build_detail_panel()
        layout.addWidget(panel)

    def on_detail_dialog_closed(self):
        album_id = self.current_album_id
        if album_id:
            self.selected_album_ids.discard(album_id)
            self.update_card_selection(album_id, False)

    def fit_detail_dialog(self):
        dialog = getattr(self, "detail_dialog", None)
        if dialog is None:
            return
        try:
            dialog.adjustSize()
            hint = dialog.sizeHint()
            width = max(520, min(720, hint.width() + 18))
            height = max(520, min(900, hint.height() + 18))
            dialog.resize(width, height)
            screen = QApplication.primaryScreen()
            if screen:
                available = screen.availableGeometry()
                dialog.resize(min(dialog.width(), available.width() - 80), min(dialog.height(), available.height() - 80))
        except RuntimeError:
            pass

    def current_page_bounds(self):
        page_size = self.result_page_size()
        start = (self.current_result_page - 1) * page_size
        end = min(start + page_size, self.result_total_count)
        return start, end

    def result_total_pages(self) -> int:
        if self.result_total_count <= 0:
            return 0
        page_size = self.result_page_size()
        return (self.result_total_count + page_size - 1) // page_size

    def change_result_page(self, direction: int):
        self.clear_album_selection()
        if self.result_page_switching:
            return
        total_pages = self.result_total_pages()
        if total_pages <= 0:
            return
        target_page = max(1, min(total_pages, self.current_result_page + direction))
        if target_page == self.current_result_page:
            return
        self.result_page_switching = True
        self.prev_page_btn.setEnabled(False)
        self.next_page_btn.setEnabled(False)
        self.current_result_page = target_page
        start, end = self.current_page_bounds()
        if self.is_page_partially_loaded(start, end):
            self.render_result_page()
            self.result_stack.setCurrentWidget(self.result_scroll)
            self._fade_in(self.result_scroll, 180)
        else:
            self.clear_result_grid()
            self.result_loading_text.setText("正在加载当前页")
            self.result_stack.setCurrentWidget(self.result_loading_page)
        self.maybe_auto_load_next_source_page()
        QTimer.singleShot(160, self.finish_result_page_switch)

    def finish_result_page_switch(self):
        self.result_page_switching = False
        self.update_page_controls()

    def update_page_controls(self):
        total_pages = self.result_total_pages()
        current = self.current_result_page if total_pages else 0
        if hasattr(self, "page_label"):
            self.page_label.setText(f"第 {current} / {total_pages} 页，共 {self.result_total_count} 本")
            if getattr(self, "result_page_switching", False):
                self.prev_page_btn.setEnabled(False)
                self.next_page_btn.setEnabled(False)
                return
            self.prev_page_btn.setEnabled(current > 1)
            self.next_page_btn.setEnabled(total_pages > 0 and current < total_pages)

    def maybe_auto_load_next_source_page(self):
        if self.current_result_page < self.result_total_pages():
            return
        if not self.auto_load_has_more or self.auto_loading_next_page:
            return
        if split_ids(self.id_edit.text()):
            return
        if self.scrape_worker and self.scrape_worker.isRunning():
            return
        self.auto_loading_next_page = True
        next_source_page = self.loaded_source_pages + 1
        self.log(f"已到当前最后一页，后台自动获取第 {next_source_page} 页漫画。")
        self.start_scrape(source_page=next_source_page, append=True)

    def save_current_result_cache(self):
        if not self.current_result_cache_key:
            return
        albums = [copy.deepcopy(album) for album in self.result_albums if album is not None]
        if not albums:
            return
        self.result_cache[self.current_result_cache_key] = albums
        for album in albums:
            self.detail_cache[album.album_id] = copy.deepcopy(album)
        self.save_local_cache()

    def current_album(self) -> Optional[AlbumMeta]:
        if not self.current_album_id:
            return None
        return self.albums.get(self.current_album_id)

    def show_chapters(self, album_id: str):
        self.chapter_table.setRowCount(0)
        album = self.albums.get(album_id)
        if not album:
            return
        self.current_album_id = album_id
        chapter_count = len(album.chapters) if album.chapters else 0
        tags = "  ".join(f"#{tag}" for tag in album.tags[:30]) if album.tags else "-"
        self.detail_card.setText(
            f"{album.title}\n\n"
            f"ID：{album.album_id}\n"
            f"作者：{album.author}\n"
            f"点赞：{album.likes}    页数：{album.page_count}\n"
            f"章节：{chapter_count or '-'}\n"
            f"来源：{album.source}"
        )
        self.tags_card.setText(f"标签  {tags}")
        self.load_cover(album)
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
        self.adjust_chapter_table_height()
        self.fit_detail_dialog()

    def adjust_chapter_table_height(self):
        rows = self.chapter_table.rowCount()
        header = self.chapter_table.horizontalHeader().height()
        row_height = self.chapter_table.verticalHeader().defaultSectionSize()
        height = header + max(1, rows) * row_height + 8
        self.chapter_table.setFixedHeight(max(96, min(520, height)))

    def load_cover(self, album: AlbumMeta):
        self.cover_label.setPixmap(QPixmap())
        self.apply_loading_movie(self.cover_label, QSize(110, 88))
        self.request_cover(album, self.cover_label)

    def request_cover(self, album: AlbumMeta, label: QLabel):
        label._album_id = album.album_id
        if not getattr(label, "_persistent_cover", False):
            label._result_generation = self.result_render_generation
        seed_url = album.cover_url or self.default_cover_url(album.album_id)
        if not seed_url:
            self.stop_label_movie(label)
            label.setText("暂无封面")
            self.log(f"封面跳过：{album.title} 没有可用封面地址。")
            return
        if album.album_id in self.cover_cache:
            self.stop_label_movie(label)
            self.set_cover_on_label(label, self.cover_cache[album.album_id])
            self.log(f"封面命中缓存：{album.title}（{album.album_id}）")
            return

        self.cover_targets.setdefault(album.album_id, []).append(label)
        if album.album_id in self.cover_pending:
            self.log(f"封面加入等待队列：{album.title}（{album.album_id}）")
            return
        self.cover_pending.add(album.album_id)
        urls = self.cover_url_candidates(seed_url, album.album_id)
        self.cover_fallback_urls[album.album_id] = urls[1:]
        self.log(f"开始加载封面：{album.title}（{album.album_id}），候选地址 {len(urls)} 个。")
        self.start_cover_request(album.album_id, urls)

    def default_cover_url(self, album_id: str) -> str:
        match = re.search(r"(\d+)", album_id or "")
        if not match or not self.cover_domain_pool:
            return ""
        return f"https://{self.cover_domain_pool[0]}/media/albums/{match.group(1)}.jpg"

    def cover_url_candidates(self, url: str, album_id: str = "") -> List[str]:
        candidates = []
        if "_3x4.jpg" in url:
            candidates.extend([url.replace("_3x4.jpg", ".jpg"), url])
        elif url.endswith(".jpg"):
            candidates.extend([url, url[:-4] + "_3x4.jpg"])
        elif url:
            candidates.append(url)

        match = re.search(r"/media/albums/(\d+)(?:_3x4)?\.jpg", url)
        if not match:
            match = re.search(r"(\d+)", album_id or "")
        if match:
            numeric_id = match.group(1)
            original_domain = urlparse(url).netloc
            domains = self.sorted_cover_domains(original_domain)
            for domain in domains:
                candidates.append(f"https://{domain}/media/albums/{numeric_id}.jpg")
                candidates.append(f"https://{domain}/media/albums/{numeric_id}_3x4.jpg")

        deduped = []
        seen = set()
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped

    def sorted_cover_domains(self, preferred: str = "") -> List[str]:
        domains = self._dedupe_domains(([preferred] if preferred else []) + self.cover_domain_pool + list(IMAGE_DOMAINS))
        return sorted(domains, key=lambda domain: (self.cover_domain_failures.get(domain, 0), domains.index(domain)))

    def start_cover_request(self, album_id: str, urls: List[str]):
        if not urls:
            self.on_cover_failed(album_id, "没有可用封面地址", [])
            return
        referer_domain = self.api_domain_pool[0] if self.api_domain_pool else API_DOMAINS[0]
        worker = CoverFetchWorker(
            album_id,
            urls,
            proxy=self.proxy_edit.text().strip() if hasattr(self, "proxy_edit") else "",
            referer_domain=referer_domain,
            parent=self,
        )
        self.cover_workers[album_id] = worker
        worker.loaded.connect(self.on_cover_loaded)
        worker.failed.connect(self.on_cover_failed)
        worker.finished.connect(lambda album_id=album_id: self.cover_workers.pop(album_id, None))
        worker.start()

    def on_cover_loaded(self, album_id: str, data: bytes, url: str, failed_urls: List[str]):
        for failed_url in failed_urls:
            self.mark_cover_domain_failed(failed_url)
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self.mark_cover_domain_failed(url)
            self.on_cover_failed(album_id, f"封面数据无法解析：{len(data)} bytes", failed_urls + [url])
            return
        targets = self.cover_targets.pop(album_id, [])
        self.cover_pending.discard(album_id)
        self.cover_fallback_urls.pop(album_id, None)
        self.cover_cache[album_id] = pixmap
        self.mark_cover_domain_success(url)
        self.log(f"封面加载完成：{album_id}")
        for label in targets:
            if self.is_live_cover_target(album_id, label):
                self.set_cover_on_label(label, pixmap)

    def on_cover_failed(self, album_id: str, message: str, failed_urls: List[str]):
        for failed_url in failed_urls:
            self.mark_cover_domain_failed(failed_url)
        self.save_local_cache()
        targets = self.cover_targets.pop(album_id, [])
        self.cover_pending.discard(album_id)
        self.cover_fallback_urls.pop(album_id, None)
        self.log(f"封面加载失败 {album_id}：{message}")
        for label in targets:
            try:
                if not self.is_live_cover_target(album_id, label):
                    continue
                self.stop_label_movie(label)
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

    def mark_cover_domain_failed(self, url: str):
        domain = urlparse(url).netloc
        if not domain:
            return
        self.cover_domain_failures[domain] = self.cover_domain_failures.get(domain, 0) + 1
        self.cover_domain_pool = self._dedupe_domains(self.cover_domain_pool + [domain])

    def mark_cover_domain_success(self, url: str):
        domain = urlparse(url).netloc
        if not domain:
            return
        self.cover_domain_failures.pop(domain, None)
        self.cover_domain_pool = self._dedupe_domains([domain] + self.cover_domain_pool)
        self.save_local_cache()

    @staticmethod
    def set_cover_on_label(label: QLabel, pixmap: QPixmap):
        try:
            MainWindow.stop_label_movie(label)
            target = label.size()
            scaled = pixmap.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            if scaled.width() > target.width() or scaled.height() > target.height():
                x = max(0, (scaled.width() - target.width()) // 2)
                y = max(0, (scaled.height() - target.height()) // 2)
                scaled = scaled.copy(x, y, target.width(), target.height())
            label.setPixmap(scaled)
            label.setText("")
        except RuntimeError:
            pass

    def set_all_chapters(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.chapter_table.rowCount()):
            item = self.chapter_table.item(row, 0)
            if item:
                item.setCheckState(state)

    def open_reader_for_current(self):
        album = self.current_album()
        if not album:
            QMessageBox.information(self, "提示", "请先选择一个漫画。")
            return
        if not album.chapters:
            QMessageBox.information(self, "提示", "当前漫画没有章节信息。")
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
        reader.destroyed.connect(lambda _=None, dialog=reader: self.forget_reader_dialog(dialog))
        reader.start_online_chapter(album, chapter, self.download_config(), self.log)
        detail = getattr(self, "detail_dialog", None)
        if detail is not None:
            detail.hide()
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
        reader.destroyed.connect(lambda _=None, dialog=reader: self.forget_reader_dialog(dialog))
        reader.start_online_chapter(copy.deepcopy(album), copy.deepcopy(chapter), self.download_config(), self.log)
        detail = getattr(self, "detail_dialog", None)
        if detail is not None:
            detail.hide()
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

    def on_reader_chapters_loaded(self, requested_id: str, album_id: str, chapters: List[ChapterMeta]):
        if requested_id != album_id:
            return
        album = self.albums.get(album_id) or self.detail_cache.get(album_id)
        if not album:
            return
        album.chapters = chapters
        self.albums[album_id] = album
        self.detail_cache[album_id] = copy.deepcopy(album)
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
        QMessageBox.warning(self, "阅读加载失败", message)

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

    def selected_chapter_ids(self, album: AlbumMeta) -> List[str]:
        ids = []
        for row in range(self.chapter_table.rowCount()):
            item = self.chapter_table.item(row, 0)
            if item and item.checkState() == Qt.Checked and row < len(album.chapters):
                ids.append(album.chapters[row].chapter_id)
        return ids

    def add_album_to_queue(self, album_id: str, switch_page: bool = True, refresh: bool = True) -> bool:
        album = self.albums.get(album_id)
        if not album:
            return False
        if any(item.album_id == album_id for item in self.queue):
            self.log(f"下载队列已存在：{album.title}")
            return False
        queued = copy.deepcopy(album)
        if album_id == self.current_album_id and hasattr(self, "chapter_table"):
            queued.selected_chapter_ids = self.selected_chapter_ids(album)
        else:
            queued.selected_chapter_ids = [chapter.chapter_id for chapter in album.chapters]
        if not queued.selected_chapter_ids and queued.chapters:
            QMessageBox.information(self, "提示", "请至少勾选一个章节。")
            return False
        self.queue.append(queued)
        self.log(f"已加入下载队列：{queued.title}，章节 {self.queue_chapter_count(queued)} 个。")
        if refresh:
            self.refresh_queue_table()
        if switch_page:
            self.switch_page(self.queue_page_index())
        return True

    def add_current_album_to_queue(self):
        album = self.current_album()
        if not album:
            QMessageBox.information(self, "提示", "请先选择一个漫画。")
            return
        self.add_album_to_queue(album.album_id)

    def add_selected_albums_to_queue(self, switch_page: bool = True, quiet: bool = False):
        added = 0
        for album_id in list(self.selected_album_ids):
            if self.add_album_to_queue(album_id, switch_page=False, refresh=False):
                added += 1
        if not added:
            if not quiet:
                QMessageBox.information(self, "提示", "请先勾选漫画。")
            return
        self.refresh_queue_table()
        if switch_page:
            self.switch_page(self.queue_page_index())

    def create_download_card(self, album: Optional[AlbumMeta], title: str = "", status: str = "等待中", active: bool = False) -> QFrame:
        card = QFrame()
        card.setObjectName("currentDownloadCard" if active else "downloadCard")
        card.setProperty("album_id", album.album_id if album else "")
        card.setMinimumHeight(148 if active else 112)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setStyleSheet(
            """
            QFrame#downloadCard, QFrame#currentDownloadCard {
                background:#ffffff;
                border:1px solid #dfe7f2;
                border-radius:8px;
            }
            QFrame#currentDownloadCard {
                background:#f8fbff;
                border:1px solid #b8d6ff;
            }
            QLabel#downloadCover {
                background:#eef3f8;
                border:1px solid #dbe5f0;
                border-radius:6px;
                color:#8491a5;
            }
            QLabel#downloadTitle {
                font-weight:800;
                color:#1f2937;
                font-size:13px;
            }
            QLabel#downloadSub {
                color:#64748b;
                font-size:12px;
            }
            QLabel#downloadTransfer {
                color:#475569;
                font-size:12px;
                font-weight:700;
            }
            QLabel#downloadStatus {
                background:#eef4ff;
                color:#1d4ed8;
                border:1px solid #d6e6ff;
                border-radius:9px;
                padding:2px 9px;
                font-size:12px;
                font-weight:700;
            }
            QProgressBar#downloadProgress {
                border:1px solid #d9e3ef;
                border-radius:7px;
                background:#f1f5f9;
                height:14px;
                text-align:center;
                color:#334155;
                font-size:11px;
                font-weight:700;
            }
            QProgressBar#downloadProgress::chunk {
                border-radius:8px;
                background:#2f80ed;
            }
            QPushButton#downloadCancel {
                padding:5px 10px;
                border-radius:6px;
                background:#fff1f2;
                border:1px solid #fecdd3;
                color:#be123c;
                font-weight:700;
            }
            QPushButton#downloadCancel:hover {
                background:#ffe4e6;
            }
            """
        )
        outer = QHBoxLayout(card)
        outer.setContentsMargins(9, 8, 9, 8)
        outer.setSpacing(10)
        cover = QLabel()
        cover.setObjectName("downloadCover")
        cover._persistent_cover = True
        cover_size = QSize(112, 86) if active else QSize(78, 62)
        cover.setFixedSize(cover_size)
        cover.setAlignment(Qt.AlignCenter)
        if album:
            self.apply_loading_movie(cover, QSize(min(cover_size.width(), 90), min(cover_size.height(), 68)))
            self.request_cover(album, cover)
        else:
            cover.setText("无封面")
        outer.addWidget(cover)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        top = QHBoxLayout()
        name = title or (album.title if album else "-")
        title_label = QLabel(QFontMetrics(self.font()).elidedText(name, Qt.ElideRight, 520))
        title_label.setObjectName("downloadTitle")
        title_label.setToolTip(name)
        status_label = QLabel(status)
        status_label.setObjectName("downloadStatus")
        status_label.setAlignment(Qt.AlignCenter)
        top.addWidget(title_label, 1)
        top.addWidget(status_label)
        layout.addLayout(top)
        if active:
            sub_text = "当前下载任务"
        elif album:
            sub_text = f"ID：{album.album_id}    章节：{self.queue_chapter_count(album)}"
        else:
            sub_text = "队列为空，添加漫画后会显示在这里"
        sub = QLabel(sub_text)
        sub.setObjectName("downloadSub")
        sub.setToolTip(sub_text)
        layout.addWidget(sub)
        transfer_text = "已下：0 B    速度：0 B/s" if album else ""
        transfer = QLabel(transfer_text)
        transfer.setObjectName("downloadTransfer")
        transfer.setVisible(bool(album))
        transfer.setMinimumWidth(230)
        layout.addWidget(transfer)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        progress = QProgressBar()
        progress.setObjectName("downloadProgress")
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setFormat("0%" if album else "无任务")
        cancel = QPushButton("取消")
        cancel.setObjectName("downloadCancel")
        cancel.setVisible(bool(album))
        if album:
            cancel.clicked.connect(lambda checked=False, album_id=album.album_id: self.cancel_album_download(album_id))
        progress_row.addWidget(progress, 1)
        progress_row.addWidget(cancel)
        layout.addLayout(progress_row)
        outer.addLayout(layout, 1)
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
        if cancel and status_text in {"已完成", "失败", "已取消"}:
            cancel.setEnabled(False)

    def queue_chapter_count(self, album: Optional[AlbumMeta]) -> int:
        if not album:
            return 0
        return len(album.selected_chapter_ids) or len(album.chapters) or 1

    def refresh_queue_table(self):
        if not hasattr(self, "queue_cards_layout"):
            return
        if hasattr(self, "queue_status_label"):
            self.queue_status_label.setText(f"{len(self.queue)} 本等待" if self.queue else "等待添加")
        wanted_ids = [album.album_id for album in self.queue]
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
        for album in self.queue:
            card = existing_cards.get(album.album_id)
            if card is not None:
                old_index = self.queue_cards_layout.indexOf(card)
                if old_index >= 0:
                    self.queue_cards_layout.takeAt(old_index)
            else:
                card = self.create_download_card(album)
            self.download_card_by_id[album.album_id] = card
            self.queue_cards_layout.insertWidget(insert_at, card)
            insert_at += 1
        if not self.queue:
            empty = self.create_download_card(None, "暂无等待下载的漫画", "空队列")
            self.queue_cards_layout.insertWidget(0, empty)

    def clear_queue(self):
        if self.is_download_busy():
            QMessageBox.information(self, "下载中", "当前有漫画正在下载，请先取消下载后再清空队列。")
            return
        self.log("已清空下载等待队列。")
        self.queue.clear()
        self.download_pending_queue.clear()
        self.refresh_queue_table()

    def remove_finished_album_from_queue(self, album_id: str):
        before_queue = len(self.queue)
        before_pending = len(self.download_pending_queue)
        self.queue = [album for album in self.queue if album.album_id != album_id]
        self.download_pending_queue = [album for album in self.download_pending_queue if album.album_id != album_id]
        if len(self.queue) != before_queue or len(self.download_pending_queue) != before_pending:
            self.log(f"已从下载列表移除完成任务：{album_id}")
            self.refresh_queue_table()

    def start_download_queue(self):
        if not self.queue and not self.download_pending_queue:
            QMessageBox.information(self, "提示", "下载队列为空。")
            return
        if not self.download_pending_queue:
            active_ids = set(self.download_workers)
            self.download_pending_queue = [copy.deepcopy(album) for album in self.queue if album.album_id not in active_ids]
        self.log(f"开始并发下载：等待 {len(self.download_pending_queue)} 本，最多同时 {self.max_parallel_downloads()} 本。")
        self.cancel_btn.setEnabled(True)
        self.last_global_download_percent = 0
        if self.download_can_use_global_progress():
            self.set_backend_status("正在并发下载", "busy")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("总进度 0%")
        elif hasattr(self, "queue_status_label"):
            self.queue_status_label.setText(self.download_status_text())
        self.pump_download_workers()

    def max_parallel_downloads(self) -> int:
        if hasattr(self, "parallel_downloads"):
            return max(1, self.parallel_downloads.value())
        return 2

    def pump_download_workers(self):
        while self.download_pending_queue and len(self.download_workers) < self.max_parallel_downloads():
            album = self.download_pending_queue.pop(0)
            self.start_single_download(album)
        self.update_download_summary()

    def start_single_download(self, album: AlbumMeta):
        worker = DownloadWorker([copy.deepcopy(album)], self.background_download_config(), self)
        self.download_workers[album.album_id] = worker
        self.download_cancelled_ids.discard(album.album_id)
        self.download_totals[album.album_id] = max(1, self.queue_chapter_count(album))
        self.download_done_counts[album.album_id] = 0
        self.download_percent_by_id[album.album_id] = 0
        self.download_bytes[album.album_id] = 0
        self.download_speeds[album.album_id] = 0.0
        worker.log.connect(self.log)
        worker.album_started.connect(self.on_download_album_started)
        worker.album_progress.connect(self.on_download_album_progress)
        worker.album_transfer.connect(self.on_download_album_transfer)
        worker.album_done.connect(self.on_download_album_done)
        worker.item_done.connect(lambda done_album, path: None if done_album.album_id in self.download_cancelled_ids else self.add_completed_item(done_album, path))
        worker.finished_ok.connect(lambda album_id=album.album_id: self.on_single_download_finished(album_id))
        worker.failed.connect(lambda message, album_id=album.album_id: self.on_single_download_failed(album_id, message))
        worker.finished.connect(lambda album_id=album.album_id: self.forget_download_worker(album_id))
        self.log(f"并发下载启动：{album.title}")
        card = self.download_card_by_id.get(album.album_id)
        if card:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            transfer = card.findChild(QLabel, "downloadTransfer")
            if status:
                status.setText("排队启动")
            if progress:
                self.set_download_card_progress(progress, 0, max(1, self.queue_chapter_count(album)), "准备中")
        worker.start()

    def on_download_album_started(self, album: AlbumMeta, total: int):
        if album.album_id in self.download_cancelled_ids:
            return
        self.current_download_album_id = album.album_id
        self.log(f"当前下载任务：{album.title}，正在解析图片列表。")
        self.download_totals[album.album_id] = max(self.download_totals.get(album.album_id, 1), max(1, total))
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
                current_total = self.download_totals.get(album.album_id, max(1, total))
                self.set_download_card_progress(progress, current_done, current_total, f"{self.download_percent(current_done, current_total)}%")
            if sub:
                sub.setText(f"ID：{album.album_id}    图片：0 / {max(1, total)}")

    def on_download_album_progress(self, album: AlbumMeta, done: int, total: int):
        if album.album_id in self.download_cancelled_ids:
            return
        self.current_download_album_id = album.album_id
        if done == 0 or done == total or done % 10 == 0:
            self.log(f"下载进度：{album.title} {done}/{max(1, total)} 张图片。")
        prev_total = self.download_totals.get(album.album_id, 1)
        prev_done = self.download_done_counts.get(album.album_id, 0)
        total = max(prev_total, max(1, total))
        done = max(prev_done, min(done, total))
        self.download_totals[album.album_id] = total
        self.download_done_counts[album.album_id] = done
        self.flush_download_card_progress(copy.deepcopy(album), done, total)

    def flush_download_card_progress(self, album: AlbumMeta, done: int, total: int):
        self.download_progress_pending.discard(album.album_id)
        card = self.download_card_by_id.get(album.album_id)
        if card:
            status = card.findChild(QLabel, "downloadStatus")
            progress = card.findChild(QProgressBar, "downloadProgress")
            sub = card.findChild(QLabel, "downloadSub")
            if status:
                status.setText("下载中" if done < total else "处理中")
            if progress:
                percent = self.download_percent(done, total)
                self.set_download_card_progress(progress, done, total, f"{percent}%")
            if sub:
                sub.setText(f"ID：{album.album_id}    图片：{done} / {max(1, total)}")
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

    def on_download_album_done(self, album: AlbumMeta):
        if album.album_id in self.download_cancelled_ids:
            return
        self.log(f"漫画下载完成：{album.title}（{album.album_id}）")
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
        self.download_done_counts[album.album_id] = self.download_totals.get(album.album_id, 1)
        self.update_download_summary()

    def reset_current_download_card(self, status: str = "空闲"):
        self.current_download_album_id = ""
        if hasattr(self, "queue_status_label"):
            self.queue_status_label.setText(self.download_status_text())
        self.cancel_btn.setEnabled(self.is_download_busy())

    def on_single_download_finished(self, album_id: str):
        if album_id in self.download_cancelled_ids:
            self.log(f"单本下载已取消：{album_id}")
            return
        self.log(f"单本下载完成：{album_id}")
        self.remove_finished_album_from_queue(album_id)
        self.update_download_summary()

    def on_single_download_failed(self, album_id: str, message: str):
        if album_id in self.download_cancelled_ids:
            self.log(f"漫画下载已取消 {album_id}")
            return
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

    def cancel_album_download(self, album_id: str):
        worker = self.download_workers.get(album_id)
        self.download_cancelled_ids.add(album_id)
        self.queue = [album for album in self.queue if album.album_id != album_id]
        self.download_pending_queue = [album for album in self.download_pending_queue if album.album_id != album_id]
        self.cleanup_download_album_state(album_id)
        self.refresh_queue_table()
        self.update_download_summary()
        if worker and worker.isRunning():
            worker.cancel()
            self.log(f"已取消并移出下载列表：{album_id}")
        else:
            self.log(f"已移除等待下载任务：{album_id}")

    def cleanup_download_album_state(self, album_id: str):
        self.download_totals.pop(album_id, None)
        self.download_done_counts.pop(album_id, None)
        self.download_percent_by_id.pop(album_id, None)
        self.download_bytes.pop(album_id, None)
        self.download_speeds.pop(album_id, None)
        self.download_progress_pending.discard(album_id)
        self.download_transfer_pending.discard(album_id)

    def forget_download_worker(self, album_id: str):
        self.download_workers.pop(album_id, None)
        if album_id not in {album.album_id for album in self.queue}:
            self.cleanup_download_album_state(album_id)
        self.pump_download_workers()
        if not self.is_download_busy() and not self.download_pending_queue:
            self.on_all_downloads_finished()

    def on_all_downloads_finished(self):
        self.current_download_album_id = ""
        self.cancel_btn.setEnabled(False)
        self.download_cancelled_ids.clear()
        self.last_global_download_percent = 0
        self.set_backend_status("下载完成", "ok")
        self.log("全部下载任务完成。")
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
        if hasattr(self, "queue_status_label"):
            self.queue_status_label.setText(self.download_status_text())

    def add_completed_item(self, album: AlbumMeta, pdf_path: str):
        if not pdf_path:
            return
        row = self.completed_table.rowCount()
        self.completed_table.insertRow(row)
        path = Path(pdf_path).expanduser()
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
        existing_index = self.find_history_index_for_output(path)
        if existing_index >= 0:
            self.download_history.pop(existing_index)
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
            "outputs": [str(path)],
        }
        self.download_history.append(record)
        self.selected_history_index = len(self.download_history) - 1
        self.refresh_history_table()
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
                QMessageBox.information(self, "提示", "增量更新正在后台运行。")
            return
        if self.is_busy():
            if not silent:
                QMessageBox.information(self, "忙碌", "当前有任务运行，稍后再更新。")
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
            QMessageBox.information(self, "增量更新完成", f"发现 {new_count} 个新章节。下载时会自动跳过旧章节。")

    def on_incremental_failed(self, message: str, silent: bool):
        self.incremental_worker = None
        self.set_backend_status("增量更新失败", "error")
        self.log(f"增量更新失败：{message}")
        self.refresh_task_controls()
        if not silent:
            QMessageBox.warning(self, "增量更新失败", message)

    def task_done(self, message: str, page_index: Optional[int] = None):
        if "采集" in message or "加载" in message:
            self.set_backend_status("首页已加载", "ok")
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
        QMessageBox.warning(self, "任务失败", message)

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
        self.pending_log_messages.append(time.strftime("[%H:%M:%S] ") + message)
        if self.log_flush_timer.isActive():
            return
        self.log_flush_timer.start(80)

    def clear_log_box(self):
        self.pending_log_messages.clear()
        if self.log_flush_timer.isActive():
            self.log_flush_timer.stop()
        self.log_box.clear()
        self.statusBar().showMessage("日志已清空，后台任务不受影响。", 1800)

    def flush_logs(self):
        if not self.pending_log_messages:
            return
        batch = self.pending_log_messages[:80]
        del self.pending_log_messages[:80]
        self.log_box.appendPlainText("\n".join(batch))
        if self.pending_log_messages:
            self.log_flush_timer.start(80)
