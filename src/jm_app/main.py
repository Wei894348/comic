import os
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .backend.app_logger import AppLog
from .desktop_pet_launcher import start_desktop_pet, stop_desktop_pet
from .frontend.app_icon import APP_DISPLAY_NAME, APP_ID, app_icon, set_windows_app_id


def main():
    log_file = AppLog.init()
    AppLog.info(f"{APP_DISPLAY_NAME} 启动，日志文件：{log_file}")
    set_windows_app_id()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    available_fonts = set(QFontDatabase.families())
    for family in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "SimSun"):
        if family in available_fonts:
            app.setFont(QFont(family, 10))
            break
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("JMComic")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())

    app.aboutToQuit.connect(stop_desktop_pet)

    from .frontend.ui import MainWindow

    window = MainWindow()
    window.show()
    QTimer.singleShot(0, start_desktop_pet)
    try:
        exit_code = app.exec()
    except KeyboardInterrupt:
        exit_code = 130
    # QApplication can return while Python workers remain blocked in network
    # or file I/O.  Window shutdown persists state before this point; avoid
    # Python's unbounded wait for those workers so cmd/pwsh is released.
    stop_desktop_pet()
    os._exit(exit_code)
