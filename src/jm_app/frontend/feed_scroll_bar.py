"""JMComic-qt-style smooth scrollbar and comic-list interaction."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Signal, Qt
from PySide6.QtWidgets import QListWidget, QScrollBar, QWidget


FEED_CARD_WIDTH = 276
FEED_CARD_HEIGHT = 438
FEED_GRID_ROW_HEIGHT = FEED_CARD_HEIGHT
FEED_MIN_GAP = 12

PROFILE_CARD_WIDTH = 250
PROFILE_CARD_HEIGHT = 410
PROFILE_GRID_ROW_HEIGHT = PROFILE_CARD_HEIGHT


class FeedScrollBar(QScrollBar):
    """JMComic-qt motion with a stable visual thumb for infinite feeds."""

    movement_finished = Signal()
    FIXED_THUMB_LENGTH = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_value = self.value()
        self._animation = QPropertyAnimation(self, b"value", self)
        self._animation.setEasingCurve(QEasingCurve.OutQuint)
        self._animation.setDuration(500)
        self._animation.finished.connect(self.movement_finished)
        self.rangeChanged.connect(self._clamp_target_to_range)

    def _clamp_target_to_range(self, minimum: int, maximum: int) -> None:
        """Keep wheel input continuous when loading changes the list range."""
        self._target_value = max(int(minimum), min(int(maximum), self._target_value))

    def setValue(self, value: int) -> None:
        value = max(self.minimum(), min(self.maximum(), int(value)))
        if value == self.value():
            return
        self._animation.stop()
        self._target_value = value
        self.movement_finished.emit()
        self._animation.setStartValue(self.value())
        self._animation.setEndValue(value)
        self._animation.start()

    def scroll_by(self, delta: int) -> None:
        self._target_value = max(self.minimum(), min(self.maximum(), self._target_value + int(delta)))
        self.setValue(self._target_value)

    def scroll_to(self, value: int) -> None:
        self._target_value = max(self.minimum(), min(self.maximum(), int(value)))
        self.setValue(self._target_value)

    def jump_to(self, value: int) -> None:
        self._animation.stop()
        self._target_value = max(self.minimum(), min(self.maximum(), int(value)))
        QScrollBar.setValue(self, self._target_value)

    def reset_target(self, value: int = 0) -> None:
        self._animation.stop()
        self._target_value = max(self.minimum(), min(self.maximum(), int(value)))

    def is_smooth_scrolling(self) -> bool:
        return self._animation.state() == QPropertyAnimation.State.Running

    def lock_thumb_size(self) -> None:
        # Retained for callers shared with older feeds. The thumb is fixed from
        # construction, so loading another page never needs to lock it again.
        self.update()

    def reset_thumb_size(self) -> None:
        # Query changes reset the logical position only; visual size is fixed.
        self.update()

    @staticmethod
    def fixed_page_step(
        scroll_range: int,
        track_length: int,
        thumb_length: int,
    ) -> int:
        logical_range = max(1, int(scroll_range))
        track = max(2, int(track_length))
        thumb = max(1, min(int(thumb_length), track - 1))
        return max(1, round(logical_range * thumb / (track - thumb)))

    def initStyleOption(self, option) -> None:
        super().initStyleOption(option)
        scroll_range = option.maximum - option.minimum
        track_length = self.height() if option.orientation == Qt.Vertical else self.width()
        visual_range = max(1, scroll_range)
        if scroll_range <= 0:
            # Keep the empty/loading-state thumb compact instead of painting a
            # full-track handle that shrinks as soon as the first page arrives.
            visual_range = 10_000
            option.maximum = option.minimum + visual_range
        option.pageStep = self.fixed_page_step(
            visual_range,
            track_length,
            self.FIXED_THUMB_LENGTH,
        )

    def mousePressEvent(self, event) -> None:
        self._animation.stop()
        super().mousePressEvent(event)
        self._target_value = self.value()

    def mouseReleaseEvent(self, event) -> None:
        self._animation.stop()
        super().mouseReleaseEvent(event)
        self._target_value = self.value()
        self.movement_finished.emit()

    def mouseMoveEvent(self, event) -> None:
        self._animation.stop()
        super().mouseMoveEvent(event)
        self._target_value = self.value()


class FeedListWidget(QListWidget):
    """QListWidget wheel path used by JMComic-qt's ``BaseListWidget``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._adaptive_card_width = 0
        self._adaptive_row_height = 0
        self._adaptive_min_gap = 0
        self._empty_state_widget: QWidget | None = None

    def set_empty_state_widget(self, widget: QWidget) -> None:
        self.clear_empty_state_widget()
        self._empty_state_widget = widget
        widget.setParent(self.viewport())
        widget.setGeometry(self.viewport().rect())
        widget.show()
        widget.raise_()

    def clear_empty_state_widget(self) -> None:
        widget = self._empty_state_widget
        self._empty_state_widget = None
        if widget is not None:
            widget.hide()
            widget.deleteLater()

    def configure_adaptive_grid(
        self,
        card_width: int,
        row_height: int,
        min_gap: int = 8,
    ) -> None:
        """Distribute spare viewport width between fixed-size comic cards."""
        self._adaptive_card_width = max(1, int(card_width))
        self._adaptive_row_height = max(1, int(row_height))
        self._adaptive_min_gap = max(0, int(min_gap))
        self._update_adaptive_grid()

    @staticmethod
    def adaptive_cell_width(viewport_width: int, card_width: int, min_gap: int) -> int:
        minimum_cell_width = max(1, int(card_width) + max(0, int(min_gap)))
        columns = max(1, int(viewport_width) // minimum_cell_width)
        return max(minimum_cell_width, int(viewport_width) // columns)

    def _update_adaptive_grid(self) -> None:
        if self._adaptive_card_width <= 0 or self._adaptive_row_height <= 0:
            return
        viewport_width = max(1, self.viewport().width())
        cell_width = self.adaptive_cell_width(
            viewport_width,
            self._adaptive_card_width,
            self._adaptive_min_gap,
        )
        grid_size = QSize(cell_width, self._adaptive_row_height)
        if self.gridSize() != grid_size:
            self.setGridSize(grid_size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_adaptive_grid()
        if self._empty_state_widget is not None:
            self._empty_state_widget.setGeometry(self.viewport().rect())

    def wheelEvent(self, event) -> None:
        scrollbar = self.verticalScrollBar()
        if isinstance(scrollbar, FeedScrollBar):
            delta = event.pixelDelta().y() or event.angleDelta().y()
            if delta:
                scrollbar.scroll_by(-delta)
                event.accept()
                return
        super().wheelEvent(event)
