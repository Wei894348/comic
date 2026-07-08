from __future__ import annotations

import math
import threading
from io import BytesIO
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image

from PyQt5.QtCore import QByteArray, QBuffer, QIODevice, QObject, QPoint, Qt, QThread, QTimer, pyqtSignal, QRectF, QPropertyAnimation, QEasingCurve, QSize
from PyQt5.QtGui import QBrush, QColor, QImage, QImageReader, QMovie, QPainter, QPen, QPixmap, QWheelEvent
from PyQt5.QtWidgets import (
    QAction,
    QComboBox,
    QGraphicsRectItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QMessageBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QGraphicsOpacityEffect,
)

try:
    import pypdfium2 as pdfium
except Exception:  # pragma: no cover - optional runtime dependency
    pdfium = None

from ..backend.pdf_utils import IMAGE_SUFFIXES
from ..backend.workers import ReaderWorker
from ..backend.models import AlbumMeta, ChapterMeta, DownloadConfig

PDF_SUFFIXES = {".pdf"}
SUPPORTED_READER_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES
PAGE_STITCH_GAP = 0
PDFIUM_LOCK = threading.RLock()
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
READER_LOADING_MOVIE_PATH = ASSETS_DIR / "reader_magic_loader.gif"


class PixmapCache:
    def __init__(self, limit: int = 10):
        self.limit = max(2, limit)
        self.items: "OrderedDict[str, QPixmap]" = OrderedDict()

    def get(self, key: str) -> Optional[QPixmap]:
        pixmap = self.items.get(key)
        if pixmap is not None:
            self.items.move_to_end(key)
        return pixmap

    def put(self, key: str, pixmap: QPixmap) -> None:
        self.items[key] = pixmap
        self.items.move_to_end(key)
        while len(self.items) > self.limit:
            self.items.popitem(last=False)

    def clear(self) -> None:
        self.items.clear()


GLOBAL_PIXMAP_CACHE = PixmapCache(limit=18)


class BinaryImageCache:
    def __init__(self, limit: int = 96, max_bytes: int = 512 * 1024 * 1024):
        self.limit = max(8, limit)
        self.max_bytes = max(32 * 1024 * 1024, max_bytes)
        self.total_bytes = 0
        self.items: "OrderedDict[str, bytes]" = OrderedDict()

    def get(self, key: str) -> Optional[bytes]:
        data = self.items.get(key)
        if data is not None:
            self.items.move_to_end(key)
        return data

    def put(self, key: str, data: bytes) -> None:
        old = self.items.pop(key, None)
        if old is not None:
            self.total_bytes -= len(old)
        self.items[key] = data
        self.items.move_to_end(key)
        self.total_bytes += len(data)
        while len(self.items) > self.limit or self.total_bytes > self.max_bytes:
            _, removed = self.items.popitem(last=False)
            self.total_bytes -= len(removed)


GLOBAL_IMAGE_BYTES_CACHE = BinaryImageCache()


class HdImageDecoder:
    @staticmethod
    def pil_to_qimage(image: Image.Image) -> QImage:
        if image.mode == "RGBA":
            data = image.tobytes("raw", "RGBA")
            qimage = QImage(data, image.width, image.height, image.width * 4, QImage.Format_RGBA8888)
            return qimage.copy()
        rgb = image.convert("RGB") if image.mode != "RGB" else image
        data = rgb.tobytes("raw", "RGB")
        qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
        return qimage.copy()

    @staticmethod
    def decode_image(path: Path) -> QImage:
        key = str(path.resolve())
        data = GLOBAL_IMAGE_BYTES_CACHE.get(key)
        if data is None:
            data = path.read_bytes()
            GLOBAL_IMAGE_BYTES_CACHE.put(key, data)

        byte_array = QByteArray(data)
        buffer = QBuffer()
        buffer.setData(byte_array)
        buffer.open(QIODevice.ReadOnly)
        reader = QImageReader(buffer)
        reader.setAutoTransform(True)
        reader.setQuality(100)
        image = reader.read()
        buffer.close()
        if not image.isNull():
            return image.copy()

        with Image.open(BytesIO(data)) as pil_image:
            pil_image.load()
            if pil_image.mode not in {"RGB", "RGBA"}:
                pil_image = pil_image.convert("RGBA")
            return HdImageDecoder.pil_to_qimage(pil_image)

    @staticmethod
    def decode_pdf_page(path: Path, page_index: int, dpi: int = 300) -> QImage:
        if pdfium is None:
            raise RuntimeError("PDF 高清阅读需要安装 pypdfium2：pip install pypdfium2")
        with PDFIUM_LOCK:
            document = pdfium.PdfDocument(str(path))
            try:
                page = document[page_index]
                try:
                    bitmap = page.render(scale=dpi / 72.0, rotation=0)
                    try:
                        pil_image = bitmap.to_pil()
                        if pil_image.mode not in {"RGB", "RGBA"}:
                            pil_image = pil_image.convert("RGBA")
                        return HdImageDecoder.pil_to_qimage(pil_image)
                    finally:
                        close_bitmap = getattr(bitmap, "close", None)
                        if callable(close_bitmap):
                            close_bitmap()
                finally:
                    page.close()
            finally:
                document.close()

    @staticmethod
    def pdf_page_count(path: Path) -> int:
        if pdfium is None:
            raise RuntimeError("PDF 高清阅读需要安装 pypdfium2：pip install pypdfium2")
        with PDFIUM_LOCK:
            document = pdfium.PdfDocument(str(path))
            try:
                return len(document)
            finally:
                document.close()

    @staticmethod
    def pdf_page_size(path: Path, page_index: int, dpi: int = 300) -> Tuple[int, int]:
        if pdfium is None:
            raise RuntimeError("PDF 高清阅读需要安装 pypdfium2：pip install pypdfium2")
        with PDFIUM_LOCK:
            document = pdfium.PdfDocument(str(path))
            try:
                page = document[page_index]
                try:
                    width = max(1, int(float(page.get_width()) * dpi / 72.0))
                    height = max(1, int(float(page.get_height()) * dpi / 72.0))
                    return width, height
                finally:
                    page.close()
            finally:
                document.close()


class DecodeWorker(QThread):
    decoded = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, path: Path, index: int, is_pdf: bool = False, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.path = path
        self.index = index
        self.is_pdf = is_pdf

    def run(self):
        try:
            if self.is_pdf:
                image = HdImageDecoder.decode_pdf_page(self.path, self.index - 1, 300)
            else:
                image = HdImageDecoder.decode_image(self.path)
            self.decoded.emit(self.index, image)
        except Exception as exc:
            self.failed.emit(self.index, str(exc))


class MangaGraphicsView(QGraphicsView):
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._zoom = 1.0
        self._dragging = False
        self._last_pos = QPoint()
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.horizontalScrollBar().setSingleStep(28)
        self.verticalScrollBar().setSingleStep(28)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        self.setBackgroundBrush(Qt.white)

    @property
    def zoom(self) -> float:
        return self._zoom

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            self.set_zoom(self._zoom * math.pow(1.12, steps))
            event.accept()
            return
        delta = event.angleDelta().y()
        if delta:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - int(delta * 0.9))
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.pos() - self._last_pos
            self._last_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.2, min(5.0, zoom))
        factor = zoom / self._zoom
        self._zoom = zoom
        self.scale(factor, factor)
        self.zoom_changed.emit(self._zoom)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom = 1.0
        self.zoom_changed.emit(self._zoom)


class HdMangaReaderWindow(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(1100, 860)
        self.setMinimumSize(720, 520)
        self.cache = GLOBAL_PIXMAP_CACHE
        self.scene = QGraphicsScene(self)
        self.view = MangaGraphicsView(self)
        self.view.setScene(self.scene)
        self.view.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.view.zoom_changed.connect(self.update_zoom_label)
        self.items: Dict[int, QGraphicsPixmapItem] = {}
        self.page_items = {}
        self.placeholders: Dict[int, QGraphicsRectItem] = {}
        self.page_sizes: Dict[int, Tuple[int, int]] = {}
        self.last_scene_width = 0
        self.image_paths: Dict[int, Path] = {}
        self.pdf_path: Optional[Path] = None
        self.pdf_fallback_image_paths: List[Path] = []
        self.decode_pending = set()
        self.failed_pages = set()
        self.page_count = 0
        self.loaded_count = 0
        self.current_page = 0
        self.decode_workers: List[DecodeWorker] = []
        self.decode_queue: List[Tuple[Path, int, bool, str, int]] = []
        self.max_decode_workers = 3
        self.online_worker: Optional[ReaderWorker] = None
        self.preload_worker: Optional[ReaderWorker] = None
        self.album: Optional[AlbumMeta] = None
        self.chapter: Optional[ChapterMeta] = None
        self.config: Optional[DownloadConfig] = None
        self.log_callback = None
        self._chapter_generation = 0
        self._closed = False
        self._force_close = False
        self.auto_fit_width = False
        self.default_zoom = 0.4
        self._default_zoom_applied = False
        self._fit_pending = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar = QToolBar(self)
        self.toolbar.setMovable(False)
        self.toolbar.setObjectName("readerToolbar")
        chapter_label = QLabel("章节")
        chapter_label.setObjectName("readerToolbarLabel")
        self.chapter_combo = QComboBox(self)
        self.chapter_combo.setObjectName("readerChapterCombo")
        self.chapter_combo.setMinimumWidth(280)
        self.chapter_combo.setMaximumWidth(520)
        self.chapter_combo.setMaxVisibleItems(16)
        self.chapter_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.chapter_combo.currentIndexChanged.connect(self.on_chapter_combo_changed)
        self.page_label = QLabel("第 0 / 0 页")
        self.zoom_label = QLabel("40%")
        self.status_label = QLabel("准备中")
        self.zoom_in_action = QAction("放大", self)
        self.zoom_out_action = QAction("缩小", self)
        self.fit_width_action = QAction("适应宽度", self)
        self.actual_size_action = QAction("原始大小", self)
        self.zoom_in_action.triggered.connect(lambda: self.manual_zoom(self.view.zoom * 1.15))
        self.zoom_out_action.triggered.connect(lambda: self.manual_zoom(self.view.zoom / 1.15))
        self.fit_width_action.triggered.connect(self.fit_width)
        self.actual_size_action.triggered.connect(self.actual_size)
        self.toolbar.addAction(self.zoom_out_action)
        self.toolbar.addAction(self.zoom_in_action)
        self.toolbar.addAction(self.fit_width_action)
        self.toolbar.addAction(self.actual_size_action)
        spacer = QWidget(self)
        spacer.setMinimumWidth(16)
        self.toolbar.addWidget(spacer)
        self.toolbar.addWidget(chapter_label)
        self.toolbar.addWidget(self.chapter_combo)
        self.toolbar.addWidget(QLabel("   "))
        self.toolbar.addWidget(self.page_label)
        self.toolbar.addWidget(QLabel("   "))
        self.toolbar.addWidget(self.zoom_label)
        self.toolbar.addWidget(QLabel("   "))
        self.toolbar.addWidget(self.status_label)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.view, 1)
        self.loading_overlay = QLabel(self.view.viewport())
        self.loading_overlay.setAlignment(Qt.AlignCenter)
        self.loading_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.loading_overlay.setStyleSheet("background:transparent;")
        self.loading_movie: Optional[QMovie] = None
        if READER_LOADING_MOVIE_PATH.exists():
            self.loading_movie = QMovie(str(READER_LOADING_MOVIE_PATH), QByteArray(), self)
            self.loading_movie.setScaledSize(QSize(210, 190))
            self.loading_overlay.setMovie(self.loading_movie)
        self.view.verticalScrollBar().valueChanged.connect(self.update_current_page)
        self.apply_reader_style()
        self.show_loading_message("准备中")
        QTimer.singleShot(0, self.animate_reader_enter)

    def apply_reader_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background:#f6f8fb;
                color:#1f2937;
            }
            QToolBar#readerToolbar {
                background:#ffffff;
                border:0;
                border-bottom:1px solid #dfe7f2;
                padding:8px 10px;
                spacing:8px;
            }
            QToolButton {
                background:#f8fafc;
                border:1px solid #dbe5f0;
                border-radius:6px;
                padding:6px 10px;
                font-weight:700;
            }
            QToolButton:hover {
                background:#eef6ff;
                border-color:#b8d6ff;
                color:#1d4ed8;
            }
            QLabel {
                color:#334155;
                font-weight:700;
            }
            QLabel#readerToolbarLabel {
                color:#64748b;
                font-size:12px;
                padding-left:6px;
            }
            QComboBox#readerChapterCombo {
                background:#f8fafc;
                border:1px solid #d6e0ec;
                border-radius:7px;
                padding:5px 28px 5px 10px;
                min-height:26px;
                color:#1f2937;
                font-weight:700;
            }
            QComboBox#readerChapterCombo:hover {
                border-color:#9cc7ff;
                background:#ffffff;
            }
            QComboBox#readerChapterCombo:focus {
                border-color:#2f80ed;
                background:#ffffff;
            }
            QComboBox#readerChapterCombo::drop-down {
                width:24px;
                border:0;
            }
            QComboBox#readerChapterCombo QAbstractItemView {
                background:#ffffff;
                border:1px solid #dbe5f0;
                selection-background-color:#e8f2ff;
                selection-color:#1d4ed8;
                padding:4px;
                outline:0;
            }
            QGraphicsView {
                background:#f8fafc;
                border:0;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background:transparent;
                border:0;
                width:10px;
                height:10px;
            }
            QScrollBar::handle {
                background:#b7c3d4;
                border-radius:5px;
                min-height:44px;
                min-width:44px;
            }
            QScrollBar::handle:hover {
                background:#74869e;
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                width:0;
                height:0;
            }
            QScrollBar::add-page, QScrollBar::sub-page {
                background:transparent;
            }
            """
        )

    def animate_reader_enter(self) -> None:
        self.view.setGraphicsEffect(None)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_loading_overlay()
        if self.auto_fit_width:
            self.schedule_fit_width()

    def closeEvent(self, event):
        if self._force_close:
            super().closeEvent(event)
            return
        self._closed = True
        running_decoders = [worker for worker in self.decode_workers if worker.isRunning()]
        online_running = bool(
            (self.online_worker and self.online_worker.isRunning())
            or (self.preload_worker and self.preload_worker.isRunning())
        )
        if running_decoders or online_running:
            event.ignore()
            self.hide()
            self.status_label.setText("正在停止后台阅读任务")
            self.decode_queue.clear()
            if self.online_worker and self.online_worker.isRunning():
                self.online_worker.cancel()
            if self.preload_worker and self.preload_worker.isRunning():
                self.preload_worker.cancel()
            for worker in running_decoders:
                worker.requestInterruption()
            return
        super().closeEvent(event)

    def finish_deferred_close(self) -> None:
        if not self._closed:
            return
        if any(worker.isRunning() for worker in self.decode_workers):
            return
        if self.online_worker and self.online_worker.isRunning():
            return
        if self.preload_worker and self.preload_worker.isRunning():
            return
        self._force_close = True
        self.close()

    def on_online_worker_finished(self) -> None:
        worker = self.sender()
        if worker is self.online_worker:
            self.online_worker = None
        self.finish_deferred_close()

    def on_preload_worker_finished(self) -> None:
        worker = self.sender()
        if worker is self.preload_worker:
            self.preload_worker = None
        self.finish_deferred_close()

    def stop_online_worker(self) -> None:
        if self.online_worker and self.online_worker.isRunning():
            self.online_worker.cancel()
        if self.preload_worker and self.preload_worker.isRunning():
            self.preload_worker.cancel()

    def set_total_pages(self, total: int) -> None:
        old_total = self.page_count
        self.page_count = max(0, total)
        self.loaded_count = min(self.loaded_count, self.page_count)
        for index in range(old_total + 1, self.page_count + 1):
            if index not in self.page_items:
                self.create_placeholder(index, size=self.estimated_page_size())
        self.layout_pages()
        self.update_page_label()

    def add_pixmap(self, index: int, pixmap: QPixmap) -> None:
        if self._closed or pixmap.isNull():
            return
        self.hide_loading_overlay()
        placeholder = self.placeholders.pop(index, None)
        if placeholder is not None:
            self.scene.removeItem(placeholder)
        item = self.items.get(index)
        if item is None:
            item = QGraphicsPixmapItem()
            item.setTransformationMode(Qt.SmoothTransformation)
            self.scene.addItem(item)
            self.items[index] = item
            self.page_items[index] = item
        item.setPixmap(pixmap)
        self.page_sizes[index] = (pixmap.width(), pixmap.height())
        self.loaded_count = max(self.loaded_count, len(self.items))
        self.layout_pages()
        if self.auto_fit_width:
            self.schedule_fit_width()
        elif not self._default_zoom_applied:
            self.apply_default_zoom()
        self.update_current_page()
        self.status_label.setText(f"已加载 {len(self.items)} / {self.page_count or len(self.items)}")

    def layout_pages(self) -> None:
        old_vertical = self.view.verticalScrollBar().value()
        y = 0
        max_width = 0
        gap = PAGE_STITCH_GAP
        for index in range(1, self.page_count + 1):
            item = self.page_items.get(index)
            if item is None:
                continue
            width, height = self.page_sizes.get(index, (800, 1100))
            max_width = max(max_width, width)
        scene_width = max(max_width, self.last_scene_width, int(self.view.viewport().width() / max(self.view.zoom, 0.1)))
        self.last_scene_width = scene_width
        y = 0
        for index in range(1, self.page_count + 1):
            item = self.page_items.get(index)
            if item is None:
                continue
            width, height = self.page_sizes.get(index, (800, 1100))
            item.setPos(max(0, (scene_width - width) / 2), y)
            y += height + gap
        self.scene.setSceneRect(0, 0, scene_width, max(0, y - gap))
        self.view.verticalScrollBar().setValue(old_vertical)

    def fit_width(self) -> None:
        self.auto_fit_width = True
        self.apply_fit_width()

    def schedule_fit_width(self) -> None:
        if self._fit_pending:
            return
        self._fit_pending = True
        QTimer.singleShot(0, self.apply_fit_width)

    def apply_fit_width(self) -> None:
        self._fit_pending = False
        rect = self.scene.itemsBoundingRect()
        if rect.width() <= 0:
            return
        self.view.reset_zoom()
        margin = 18
        target_width = max(1, self.view.viewport().width() - margin)
        scale = max(0.15, min(1.0, target_width / rect.width()))
        self.view.set_zoom(scale)

    def apply_default_zoom(self) -> None:
        self._default_zoom_applied = True
        if self.view.zoom == self.default_zoom:
            return
        self.view.reset_zoom()
        self.view.set_zoom(self.default_zoom)

    def manual_zoom(self, zoom: float) -> None:
        self.auto_fit_width = False
        self._default_zoom_applied = True
        self.view.set_zoom(zoom)

    def actual_size(self) -> None:
        self.auto_fit_width = False
        self._default_zoom_applied = True
        self.view.reset_zoom()

    def update_zoom_label(self, zoom: float) -> None:
        self.zoom_label.setText(f"{int(zoom * 100)}%")

    def update_page_label(self) -> None:
        self.page_label.setText(f"第 {self.current_page} / {self.page_count} 页")

    def update_current_page(self) -> None:
        if not self.page_items:
            self.current_page = 0
            self.update_page_label()
            return
        center_y = self.view.mapToScene(self.view.viewport().rect().center()).y()
        selected = min(self.page_items)
        best = None
        for index, item in sorted(self.page_items.items()):
            rect = item.sceneBoundingRect()
            distance = 0 if rect.top() <= center_y <= rect.bottom() else min(abs(center_y - rect.top()), abs(center_y - rect.bottom()))
            if best is None or distance < best:
                best = distance
                selected = index
        self.current_page = selected
        self.update_page_label()
        self.schedule_decode_window(selected)

    def start_decode_image_paths(self, paths: Iterable[Path]) -> None:
        self.reset_reader_state()
        self._chapter_generation += 1
        image_paths = [path for path in paths if path.exists() and path.is_file()]
        self.pdf_path = None
        self.pdf_fallback_image_paths = []
        self.failed_pages.clear()
        self.set_total_pages(len(image_paths))
        if not image_paths:
            self.status_label.setText("没有找到可阅读图片")
            QMessageBox.warning(self, "阅读失败", "没有找到可阅读的本地图片。")
            return
        self.status_label.setText("正在准备高清阅读缓存")
        self.image_paths = {index: path for index, path in enumerate(image_paths, start=1)}
        for index, path in enumerate(image_paths, start=1):
            key = str(path.resolve())
            cached = self.cache.get(key)
            if cached is not None:
                self.add_pixmap(index, cached)
                continue
            self.create_placeholder(index, path)
        self.layout_pages()
        self.apply_default_zoom()
        self.schedule_decode_window(1, radius=3)

    def image_size(self, path: Path) -> Tuple[int, int]:
        reader = QImageReader(str(path))
        size = reader.size()
        if size.isValid():
            return max(1, size.width()), max(1, size.height())
        try:
            with Image.open(path) as image:
                return image.size
        except Exception:
            return 800, 1100

    def create_placeholder(self, index: int, path: Optional[Path] = None, size: Optional[Tuple[int, int]] = None):
        old_placeholder = self.placeholders.pop(index, None)
        if old_placeholder is not None:
            try:
                self.scene.removeItem(old_placeholder)
            except RuntimeError:
                pass
        width, height = size or ((self.image_size(path) if path is not None else (800, 1100)))
        self.page_sizes[index] = (width, height)
        placeholder = QGraphicsRectItem(0, 0, width, height)
        placeholder.setPen(QPen(Qt.NoPen))
        placeholder.setBrush(QBrush(QColor("#f8fafc")))
        self.scene.addItem(placeholder)
        self.placeholders[index] = placeholder
        self.page_items[index] = placeholder

    def estimated_page_size(self) -> Tuple[int, int]:
        if self.page_sizes:
            widths = [size[0] for size in self.page_sizes.values()]
            heights = [size[1] for size in self.page_sizes.values()]
            return max(widths), max(heights)
        return 1600, 2200

    def schedule_decode_window(self, center: int, radius: int = 2):
        if not self.image_paths and self.pdf_path is None:
            return
        for index in range(max(1, center - 1), min(self.page_count, center + radius) + 1):
            if self.pdf_path is not None:
                self.schedule_decode_pdf_page(index)
            else:
                self.schedule_decode_image(index)

    def schedule_decode_image(self, index: int):
        if self._closed or index in self.items or index in self.decode_pending or index in self.failed_pages:
            return
        path = self.image_paths.get(index)
        if path is None:
            return
        key = str(path.resolve())
        cached = self.cache.get(key)
        if cached is not None:
            self.add_pixmap(index, cached)
            return
        self.queue_decode(path, index, False, key)

    def schedule_decode_pdf_page(self, index: int):
        if self._closed or self.pdf_path is None or index in self.items or index in self.decode_pending or index in self.failed_pages:
            return
        key = f"{self.pdf_path.resolve()}:{index}:300dpi"
        cached = self.cache.get(key)
        if cached is not None:
            self.add_pixmap(index, cached)
            return
        self.queue_decode(self.pdf_path, index, True, key)

    def queue_decode(self, path: Path, index: int, is_pdf: bool, key: str) -> None:
        if self._closed or index in self.decode_pending:
            return
        self.decode_pending.add(index)
        self.decode_queue.append((path, index, is_pdf, key, self._chapter_generation))
        self.pump_decode_queue()

    def pump_decode_queue(self) -> None:
        if self._closed:
            self.decode_queue.clear()
            return
        running = sum(1 for worker in self.decode_workers if worker.isRunning())
        while self.decode_queue and running < self.max_decode_workers:
            path, index, is_pdf, key, generation = self.decode_queue.pop(0)
            worker = DecodeWorker(path, index, is_pdf, self)
            worker.decoded.connect(lambda i, image, key=key, generation=generation: self.on_decoded(key, i, image, generation))
            worker.failed.connect(lambda i, message, generation=generation: self.on_decode_failed(i, message, generation))
            worker.finished.connect(lambda worker=worker: self.forget_decode_worker(worker))
            self.decode_workers.append(worker)
            worker.start()
            running += 1

    def start_decode_pdf(self, path: Path, fallback_image_paths: Optional[Iterable[Path]] = None) -> bool:
        self.reset_reader_state()
        self._chapter_generation += 1
        fallback_paths = [path for path in (fallback_image_paths or []) if path.exists() and path.is_file()]
        try:
            total = HdImageDecoder.pdf_page_count(path)
        except Exception as exc:
            if fallback_paths:
                self.status_label.setText("PDF 解码失败，已切换原文件阅读")
                self.start_decode_image_paths(fallback_paths)
                return True
            QMessageBox.warning(self, "PDF 阅读失败", f"{exc}\n\n可以在历史记录中选择“原文件”方式阅读。")
            self.status_label.setText("PDF 阅读失败")
            return False
        if total <= 0:
            if fallback_paths:
                self.status_label.setText("PDF 无页面，已切换原文件阅读")
                self.start_decode_image_paths(fallback_paths)
                return True
            QMessageBox.warning(self, "PDF 阅读失败", "PDF 文件没有可渲染页面。")
            self.status_label.setText("PDF 无页面")
            return False
        self.pdf_path = path
        self.pdf_fallback_image_paths = fallback_paths
        self.image_paths = {}
        self.failed_pages.clear()
        self.set_total_pages(total)
        self.status_label.setText("正在按需渲染 PDF")
        default_size = (1400, 2000)
        self.apply_default_zoom()
        for index in range(1, total + 1):
            key = f"{path.resolve()}:{index}:300dpi"
            cached = self.cache.get(key)
            if cached is not None:
                self.add_pixmap(index, cached)
                continue
            self.create_placeholder(index, size=default_size)
        self.layout_pages()
        self.apply_default_zoom()
        self.schedule_decode_window(1, radius=2)
        return True

    def on_decoded(self, key: str, index: int, image: QImage, generation: Optional[int] = None) -> None:
        if generation is not None and generation != self._chapter_generation:
            return
        self.decode_pending.discard(index)
        if self._closed:
            return
        pixmap = QPixmap.fromImage(image)
        self.cache.put(key, pixmap)
        self.add_pixmap(index, pixmap)

    def on_decode_failed(self, index: int, message: str, generation: Optional[int] = None) -> None:
        if generation is not None and generation != self._chapter_generation:
            return
        self.decode_pending.discard(index)
        if self._closed:
            return
        self.failed_pages.add(index)
        if self.pdf_path is not None and self.pdf_fallback_image_paths:
            self.status_label.setText("PDF 页面解码失败，已切换原文件阅读")
            self.start_decode_image_paths(self.pdf_fallback_image_paths)
            return
        self.mark_decode_failed(index)
        self.status_label.setText(f"第 {index} 页解码失败，已跳过")

    def mark_decode_failed(self, index: int) -> None:
        placeholder = self.placeholders.get(index)
        if placeholder is None:
            width, height = self.page_sizes.get(index, (800, 1100))
            placeholder = QGraphicsRectItem(0, 0, width, height)
            self.scene.addItem(placeholder)
            self.placeholders[index] = placeholder
            self.page_items[index] = placeholder
        placeholder.setBrush(QBrush(QColor("#fff1f2")))
        placeholder.setPen(QPen(QColor("#fecdd3")))

    def show_loading_message(self, message: str) -> None:
        self.status_label.setText(message)
        self.scene.clear()
        self.scene.setSceneRect(0, 0, max(520, self.view.viewport().width()), max(320, self.view.viewport().height()))
        self.show_loading_overlay()

    def show_loading_overlay(self) -> None:
        self.position_loading_overlay()
        self.loading_overlay.show()
        self.loading_overlay.raise_()
        if self.loading_movie:
            self.loading_movie.start()
        else:
            self.loading_overlay.setText("Loading")

    def hide_loading_overlay(self) -> None:
        if self.loading_movie:
            self.loading_movie.stop()
        self.loading_overlay.hide()

    def position_loading_overlay(self) -> None:
        if not hasattr(self, "loading_overlay"):
            return
        viewport = self.view.viewport().rect()
        width, height = 260, 230
        self.loading_overlay.setGeometry(
            max(0, (viewport.width() - width) // 2),
            max(0, (viewport.height() - height) // 2),
            width,
            height,
        )

    def forget_decode_worker(self, worker: DecodeWorker) -> None:
        if worker in self.decode_workers:
            self.decode_workers.remove(worker)
        self.pump_decode_queue()
        self.finish_deferred_close()

    def start_online_chapter(self, album: AlbumMeta, chapter: ChapterMeta, config: DownloadConfig, log_callback) -> None:
        self.album = album
        self.chapter = chapter
        self.config = config
        self.log_callback = log_callback
        self.populate_chapter_combo(album, chapter)
        self.reset_reader_state()
        self._chapter_generation += 1
        generation = self._chapter_generation
        self.status_label.setText("正在后台下载章节")
        worker = ReaderWorker(album, chapter, config, self, fast_mode=True)
        self.online_worker = worker
        worker.progress.connect(lambda done, total, generation=generation: self.on_online_progress(done, total, generation))
        worker.image_ready.connect(lambda index, image_path, generation=generation: self.on_online_image_ready(index, image_path, generation))
        worker.failed.connect(lambda message, generation=generation: None if self._closed or generation != self._chapter_generation else QMessageBox.warning(self, "阅读加载失败", message))
        worker.log.connect(log_callback)
        worker.finished_ok.connect(lambda generation=generation: None if self._closed or generation != self._chapter_generation else self.status_label.setText("章节加载完成"))
        worker.finished.connect(self.on_online_worker_finished)
        worker.start()
        QTimer.singleShot(2500, lambda generation=generation: None if self._closed or generation != self._chapter_generation else self.start_next_chapter_preload(album, chapter, config, log_callback))

    def prepare_online_album(self, album: AlbumMeta, config: DownloadConfig, log_callback, message: str = "正在加载章节") -> None:
        self.album = album
        self.config = config
        self.log_callback = log_callback
        self.chapter = None
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        self.chapter_combo.addItem(message)
        self.chapter_combo.setEnabled(False)
        self.chapter_combo.blockSignals(False)
        self.show_loading_message(message)

    def start_first_available_chapter(self, album: AlbumMeta, config: Optional[DownloadConfig] = None, log_callback=None) -> None:
        config = config or self.config
        log_callback = log_callback or self.log_callback
        self.chapter_combo.setEnabled(True)
        if not album.chapters:
            self.show_loading_message("没有可阅读章节")
            return
        self.start_online_chapter(album, album.chapters[0], config, log_callback)

    def populate_chapter_combo(self, album: AlbumMeta, chapter: ChapterMeta) -> None:
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        for item in album.chapters:
            text = f"第 {item.index} 章  {item.title}"
            self.chapter_combo.addItem(text, item.chapter_id)
            self.chapter_combo.setItemData(self.chapter_combo.count() - 1, text, Qt.ToolTipRole)
        current = next((i for i, item in enumerate(album.chapters) if item.chapter_id == chapter.chapter_id), 0)
        self.chapter_combo.setCurrentIndex(max(0, current))
        self.chapter_combo.blockSignals(False)

    def on_chapter_combo_changed(self, index: int) -> None:
        if self._closed or self.album is None or self.config is None or self.log_callback is None:
            return
        if index < 0 or index >= len(self.album.chapters):
            return
        chapter = self.album.chapters[index]
        if self.chapter and chapter.chapter_id == self.chapter.chapter_id:
            return
        self.stop_online_worker()
        self.start_online_chapter(self.album, chapter, self.config, self.log_callback)

    def reset_reader_state(self) -> None:
        self.decode_queue.clear()
        self.decode_pending.clear()
        self.failed_pages.clear()
        self.items.clear()
        self.page_items.clear()
        self.placeholders.clear()
        self.page_sizes.clear()
        self.image_paths.clear()
        self.pdf_path = None
        self.pdf_fallback_image_paths = []
        self.page_count = 0
        self.loaded_count = 0
        self.current_page = 0
        self.last_scene_width = 0
        self._default_zoom_applied = False
        self.scene.clear()
        self.view.reset_zoom()
        self.view.set_zoom(self.default_zoom)
        self.view.horizontalScrollBar().setValue(0)
        self.view.verticalScrollBar().setValue(0)
        self.update_page_label()

    def start_next_chapter_preload(self, album: AlbumMeta, chapter: ChapterMeta, config: DownloadConfig, log_callback) -> None:
        if self._closed or self.preload_worker is not None:
            return
        try:
            index = next(i for i, item in enumerate(album.chapters) if item.chapter_id == chapter.chapter_id)
        except StopIteration:
            return
        if index + 1 >= len(album.chapters):
            return
        next_chapter = album.chapters[index + 1]
        self.preload_worker = ReaderWorker(album, next_chapter, config, self, fast_mode=False)
        self.preload_worker.log.connect(lambda message: log_callback(f"预加载下一章：{message}"))
        self.preload_worker.failed.connect(lambda message: log_callback(f"下一章预加载失败：{message}"))
        self.preload_worker.finished.connect(self.on_preload_worker_finished)
        self.preload_worker.start()

    def on_online_progress(self, done: int, total: int, generation: Optional[int] = None) -> None:
        if generation is not None and generation != self._chapter_generation:
            return
        if self._closed:
            return
        if total:
            self.set_total_pages(total)
        self.status_label.setText(f"后台下载 {done} / {total}")

    def on_online_image_ready(self, index: int, image_path: str, generation: Optional[int] = None) -> None:
        if generation is not None and generation != self._chapter_generation:
            return
        if self._closed or index in self.items or index in self.decode_pending:
            return
        if index > self.page_count:
            self.set_total_pages(index)
        path = Path(image_path)
        key = str(path.resolve())
        cached = self.cache.get(key)
        if cached is not None:
            self.add_pixmap(index, cached)
            return
        self.queue_decode(path, index, False, key)


def collect_reader_files(path: Path) -> Tuple[List[Path], Optional[Path]]:
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix in PDF_SUFFIXES:
            return [], path
        if suffix in IMAGE_SUFFIXES:
            return [path], None
        return [], None
    if not path.is_dir():
        return [], None
    images = sorted(child for child in path.iterdir() if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES)
    if images:
        return images, None
    pdfs = sorted(child for child in path.iterdir() if child.is_file() and child.suffix.lower() in PDF_SUFFIXES)
    return [], (pdfs[0] if pdfs else None)
