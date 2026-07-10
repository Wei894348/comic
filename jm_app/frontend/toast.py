from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QRect, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget


class ToastWidget(QFrame):
    closed = pyqtSignal()

    def __init__(self, text: str, duration_ms: int = 1700, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.duration_ms = max(800, int(duration_ms or 1700))
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(
            """
            QFrame {
                background: rgba(51, 51, 51, 204);
                border-radius: 10px;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                padding: 10px 16px;
            }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)

        self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.fade_in.setDuration(160)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.setEasingCurve(QEasingCurve.OutQuad)

        self.fade_out = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.fade_out.setDuration(260)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QEasingCurve.OutQuad)
        self.fade_out.finished.connect(self.finish)

    def start(self) -> None:
        self.show()
        self.raise_()
        self.fade_in.start()
        QTimer.singleShot(self.duration_ms, self.fade_out.start)

    def finish(self) -> None:
        self.hide()
        self.closed.emit()
        self.deleteLater()


class ToastManager:
    _parent: Optional[QWidget] = None
    _active: Optional[ToastWidget] = None
    _queue: List[Tuple[str, int, Optional[QWidget]]] = []

    @classmethod
    def init(cls, parent: QWidget) -> None:
        cls._parent = parent

    @classmethod
    def show(cls, text: str, duration_ms: int = 1700, parent: Optional[QWidget] = None) -> None:
        message = str(text or "").strip()
        if not message:
            return
        cls._queue.append((message, duration_ms, parent))
        cls._show_next()

    @classmethod
    def show_on(cls, parent: QWidget, text: str, duration_ms: int = 1700) -> None:
        cls.show(text, duration_ms, parent)

    @classmethod
    def _show_next(cls) -> None:
        if cls._active is not None or not cls._queue:
            return
        text, duration_ms, parent = cls._queue.pop(0)
        target_parent = parent or cls._parent
        if target_parent is None:
            return
        toast = ToastWidget(text, duration_ms, target_parent)
        cls._active = toast
        toast.adjustSize()
        parent_rect = target_parent.rect()
        width = min(max(toast.sizeHint().width(), 220), max(240, parent_rect.width() - 56))
        height = toast.sizeHint().height()
        x = max(14, (parent_rect.width() - width) // 2)
        y = max(14, parent_rect.bottom() - height - 32)
        toast.setGeometry(QRect(x, y, width, height))
        toast.closed.connect(cls._on_closed)
        toast.start()

    @classmethod
    def _on_closed(cls) -> None:
        cls._active = None
        QTimer.singleShot(70, cls._show_next)
