import sys
from pathlib import Path

from PyQt5.QtGui import QIcon


def icon_path() -> Path:
    ico_path = Path.cwd() / "assets" / "app.ico"
    if ico_path.exists():
        return ico_path
    return Path.cwd() / "assets" / "iconv2_256x256.jpg"


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
