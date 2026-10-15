"""Reusable empty-library presentation and discovery action."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QFile, QIODevice, QSize
from PySide6.QtGui import QIcon
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from ...backend.runtime_paths import resource_dir, ui_dir


def library_empty_copy(empty_text: str) -> tuple[str, str]:
    text = str(empty_text or "").strip()
    if "收藏" in text:
        return "暂无收藏内容", "去发现喜欢的漫画并收藏起来吧"
    if "记录" in text or "阅读" in text or "观看" in text:
        return "暂无漫画记录", "去发现感兴趣的漫画，开始阅读吧"
    return "暂无漫画", "这里暂时没有漫画，去分类与排行看看吧"


def build_library_empty_state(
    parent: QWidget,
    empty_text: str,
    discover_callback: Callable[[], None],
) -> QFrame:
    path = ui_dir() / "library_empty_state.ui"
    ui_file = QFile(str(path))
    if not ui_file.open(QIODevice.ReadOnly):
        raise RuntimeError(f"Unable to open library empty state form: {path}")
    try:
        widget = QUiLoader().load(ui_file, parent)
    finally:
        ui_file.close()
    if not isinstance(widget, QFrame):
        raise RuntimeError(f"Unable to load library empty state form: {path}")

    icon = widget.findChild(QLabel, "libraryEmptyIcon")
    title = widget.findChild(QLabel, "libraryEmptyTitle")
    description = widget.findChild(QLabel, "libraryEmptyDescription")
    discover = widget.findChild(QPushButton, "libraryEmptyDiscoverButton")
    if any(control is None for control in (icon, title, description, discover)):
        raise RuntimeError("Library empty state form is missing required controls")

    title_text, description_text = library_empty_copy(empty_text)
    title.setText(title_text)
    description.setText(description_text)
    illustration = resource_dir() / "empty_discover.svg"
    if illustration.exists():
        icon.setPixmap(QIcon(str(illustration)).pixmap(QSize(148, 138)))
    discover.setIcon(
        QIcon(str(resource_dir() / "nav_icons" / "line_weekly_active.svg"))
    )
    discover.setIconSize(QSize(17, 17))
    discover.clicked.connect(discover_callback)
    widget.setStyleSheet(
        """
        QFrame#libraryEmptyState { background:transparent; border:0; }
        QLabel#libraryEmptyTitle {
            color:#253044; font-size:18px; font-weight:900;
        }
        QLabel#libraryEmptyDescription {
            color:#8a94a6; font-size:13px;
        }
        QPushButton#libraryEmptyDiscoverButton {
            color:#ffffff; background:#f07800; border:0;
            border-radius:7px; padding:0 15px;
            font-size:13px; font-weight:800;
        }
        QPushButton#libraryEmptyDiscoverButton:hover { background:#d96800; }
        QPushButton#libraryEmptyDiscoverButton:pressed { background:#bf5b00; }
        """
    )
    return widget
