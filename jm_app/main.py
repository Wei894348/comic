import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from .frontend.app_icon import APP_DISPLAY_NAME, APP_ID, app_icon, set_windows_app_id
from .frontend.ui import MainWindow


def main():
    set_windows_app_id()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("JM下载器")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec_())
