import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from .app_icon import app_icon, set_windows_app_id
from .ui import MainWindow


def main():
    set_windows_app_id()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
