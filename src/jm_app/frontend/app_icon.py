import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from ..backend.runtime_paths import app_base_dir, resource_dir

APP_DISPLAY_NAME = "JMComic"
APP_ID = "comic18.jmcomic.desktop"


def resource_path(*parts: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).joinpath(*parts)
    if parts and parts[0] == "assets":
        return resource_dir().joinpath(*parts[1:])
    return app_base_dir().joinpath(*parts)


def asset_candidates(*parts: str) -> list[Path]:
    relative = Path(*parts)
    roots = [
        Path(getattr(sys, "_MEIPASS")) if hasattr(sys, "_MEIPASS") else None,
        app_base_dir(),
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
    for name in (
        "jmcomic_logo_round.png",
        "app.ico",
        "iconv2_256x256.jpg",
        "ChatGPT Image 2026年7月5日 23_19_08.png",
    ):
        candidates.append(resource_dir() / name)
        candidates.extend(asset_candidates("assets", name))
    paths: list[Path] = []
    seen = set()
    for path in candidates:
        key = str(path).lower()
        if path.exists() and key not in seen:
            seen.add(key)
            paths.append(path)
    return paths


def icon_path() -> Path:
    paths = icon_paths()
    return paths[0] if paths else resource_path("assets", "jmcomic_logo_round.png")


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
