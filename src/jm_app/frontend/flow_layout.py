"""A small height-for-width layout used by wrapping tag collections."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0, horizontal_spacing: int = 8, vertical_spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._horizontal_spacing = max(0, int(horizontal_spacing))
        self._vertical_spacing = max(0, int(vertical_spacing))
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, max(1, width), 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        available = rect.adjusted(left, top, -right, -bottom)
        x = available.x()
        y = available.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width()
            if line_height > 0 and next_x > available.right() + 1:
                x = available.x()
                y += line_height + self._vertical_spacing
                next_x = x + hint.width()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + self._horizontal_spacing
            line_height = max(line_height, hint.height())
        return max(0, y + line_height - rect.y() + bottom)
