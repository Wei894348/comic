"""Floating refresh and scroll-to-top controls for comic feeds."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class FeedCornerTools(QWidget):
    """Keep feed actions anchored without participating in list geometry."""

    RIGHT_MARGIN = 14
    BOTTOM_MARGIN = 14

    def __init__(
        self,
        parent: QWidget,
        refresh_callback: Callable[[], None],
        top_callback: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("feedCornerTools")
        self.setFixedSize(44, 94)
        self.setAttribute(Qt.WA_StyledBackground, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.refresh_button = QToolButton(self)
        self.refresh_button.setObjectName("feedRefreshButton")
        self.refresh_button.setFixedSize(44, 44)
        self.refresh_button.setIconSize(QSize(23, 23))
        self.refresh_button.setToolTip("刷新当前漫画")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(refresh_callback)
        layout.addWidget(self.refresh_button)

        self.top_button = QToolButton(self)
        self.top_button.setObjectName("feedTopButton")
        self.top_button.setFixedSize(44, 44)
        self.top_button.setIconSize(QSize(10, 10))
        self.top_button.setText("顶部")
        self.top_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.top_button.setToolTip("返回顶部")
        self.top_button.setCursor(Qt.PointingHandCursor)
        self.top_button.clicked.connect(top_callback)
        layout.addWidget(self.top_button)

        self.set_dark_mode(False)
        for button in (self.refresh_button, self.top_button):
            shadow = QGraphicsDropShadowEffect(button)
            shadow.setBlurRadius(14)
            shadow.setOffset(0, 2)
            shadow.setColor(QColor(0, 0, 0, 36))
            button.setGraphicsEffect(shadow)

        self.update_icons()

        parent.installEventFilter(self)
        if isinstance(parent, QStackedWidget):
            parent.currentChanged.connect(self.schedule_reposition)
        self.reposition()
        self.show()
        self.raise_()

    def schedule_reposition(self, _index: int = -1) -> None:
        QTimer.singleShot(0, self.reposition)

    def set_dark_mode(self, enabled: bool) -> None:
        if enabled:
            self.setStyleSheet(
                "QToolButton { background:#292d34; color:#dce1e8; "
                "border:1px solid #414752; border-radius:7px; padding:2px; "
                "font-size:11px; } "
                "QToolButton:hover { background:#343943; border-color:#5b6370; } "
                "QToolButton:pressed { background:#3b4049; }"
            )
        else:
            self.setStyleSheet(
                "QToolButton { background:#ffffff; color:#303238; "
                "border:1px solid #dfe3e8; border-radius:7px; padding:2px; "
                "font-size:11px; } "
                "QToolButton:hover { background:#f5f7fa; border-color:#c8cdd4; } "
                "QToolButton:pressed { background:#eceff3; }"
            )
        self.update_icons()

    @staticmethod
    def _reload_icon(color: QColor) -> QIcon:
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(color, 2.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(QRectF(5, 5, 22, 22), 38 * 16, 292 * 16)
        arrow = QPainterPath(QPointF(24.5, 4.5))
        arrow.lineTo(27.5, 11.5)
        arrow.lineTo(20.0, 10.0)
        painter.drawPath(arrow)
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _up_icon(color: QColor) -> QIcon:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(
            QPolygonF(
                [QPointF(8, 3), QPointF(14, 10), QPointF(2, 10)]
            )
        )
        painter.end()
        return QIcon(pixmap)

    def update_icons(self) -> None:
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        self.refresh_button.setIcon(self._reload_icon(color))
        self.top_button.setIcon(self._up_icon(color))

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            self.update_icons()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(
            max(0, parent.width() - self.width() - self.RIGHT_MARGIN),
            max(0, parent.height() - self.height() - self.BOTTOM_MARGIN),
        )
        self.raise_()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        }:
            self.reposition()
        return super().eventFilter(watched, event)
