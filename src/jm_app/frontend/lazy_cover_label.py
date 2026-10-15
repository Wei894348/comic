"""Paint-triggered homepage cover placeholder.

This mirrors JMComic-qt's ``ComicItemWidget.paintEvent`` behavior: a list
item requests its cover only when Qt actually paints it for the first time.
The label never performs I/O; its owner receives the signal and starts a
background CoverTask.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel


class LazyCoverLabel(QLabel):
    load_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lazy_load_dispatched = False

    def bind_album(self, album_id: str, generation: int) -> None:
        """Reset this recycled label for its next album card."""
        self._album_id = str(album_id)
        self._result_generation = generation
        self._lazy_load_dispatched = False

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._lazy_load_dispatched or not getattr(self, "_album_id", ""):
            return
        self._lazy_load_dispatched = True
        self.load_requested.emit(self)
