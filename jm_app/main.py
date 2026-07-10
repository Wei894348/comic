import sys

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication

from .desktop_pet_launcher import start_desktop_pet, stop_desktop_pet
from .frontend.app_icon import APP_DISPLAY_NAME, APP_ID, app_icon, set_windows_app_id
from .frontend.startup_splash import StartupSplash


def main():
    set_windows_app_id()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("JM下载器")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())

    splash = StartupSplash()
    splash.show_centered()
    app.aboutToQuit.connect(stop_desktop_pet)

    from .frontend.ui import MainWindow

    window = MainWindow()
    splash.finish(minimum_ms=3000)
    window.show()
    QTimer.singleShot(0, start_desktop_pet)
    sys.exit(app.exec_())
