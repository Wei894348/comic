import sys
from pathlib import Path

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

APP_DISPLAY_NAME = "JM下载器"
APP_ID = "jm.downloader.desktop"


def resource_path(*parts: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).joinpath(*parts)
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def asset_candidates(*parts: str) -> list[Path]:
    relative = Path(*parts)
    roots = [
        Path(getattr(sys, "_MEIPASS")) if hasattr(sys, "_MEIPASS") else None,
        Path(__file__).resolve().parents[2],
        Path.cwd(),
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None,
    ]
    candidates: list[Path] = []
    seen = set()
    for root in roots:
        if root is None:
            continue
        candidate = root / relative
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)
    return candidates


def icon_paths() -> list[Path]:
    candidates: list[Path] = []
    for name in ("app.ico", "iconv2_256x256.jpg", "ChatGPT Image 2026年7月5日 23_19_08.png"):
        candidates.extend(asset_candidates("assets", name))
    return [path for path in candidates if path.exists()]


def icon_path() -> Path:
    paths = icon_paths()
    return paths[0] if paths else resource_path("assets", "app.ico")


def app_icon() -> QIcon:
    icon = QIcon()
    for path in icon_paths():
        loaded = QIcon(str(path))
        if not loaded.isNull():
            icon.addFile(str(path), QSize(), QIcon.Normal, QIcon.Off)
    if not icon.isNull():
        return icon

    pixmap = QPixmap(256, 256)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#1976d2"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(16, 16, 224, 224, 42, 42)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Microsoft YaHei UI", 72, QFont.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "JM")
    painter.end()
    return QIcon(pixmap)


def set_windows_app_id():
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_ID
        )
    except Exception:
        pass
