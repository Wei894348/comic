import sys
from pathlib import Path

from PyQt5.QtGui import QIcon


def resource_path(*parts: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).joinpath(*parts)
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def icon_path() -> Path:
    ico_path = resource_path("assets", "app.ico")
    if ico_path.exists():
        return ico_path
    jpg_path = resource_path("assets", "iconv2_256x256.jpg")
    if jpg_path.exists():
        return jpg_path
    return ico_path


def app_icon() -> QIcon:
    return QIcon(str(icon_path()))


def set_windows_app_id():
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "jm.comic.downloader"
        )
    except Exception:
        pass
