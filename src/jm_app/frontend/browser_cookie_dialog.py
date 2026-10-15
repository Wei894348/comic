from typing import Dict, Tuple
from urllib.parse import urlparse

from PySide6.QtCore import QFile, QIODevice, QUrl
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QDialog,
    QPushButton,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..backend.cookie_store import cookie_dict_to_header
from ..backend.jm_endpoints import WEB_LIST_URL as LIST_URL
from ..backend.runtime_paths import ui_dir


class BrowserCookieDialog(QDialog):
    def __init__(self, parent=None, url: str = LIST_URL):
        super().__init__(parent)
        self.setWindowTitle("浏览器验证 Cookie")
        self.resize(980, 720)
        self.cookies: Dict[Tuple[str, str, str], str] = {}
        self.target_domain = urlparse(url).netloc

        web_host, refresh_btn, sync_btn, cancel_btn = self.load_form()

        self.profile = QWebEngineProfile.defaultProfile()
        self.profile.cookieStore().cookieAdded.connect(self.on_cookie_added)
        self.profile.cookieStore().loadAllCookies()

        self.web = QWebEngineView()
        self.web.setUrl(QUrl(url))
        web_host.layout().addWidget(self.web)
        refresh_btn.clicked.connect(self.web.reload)
        sync_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    def load_form(self) -> tuple[QWidget, QPushButton, QPushButton, QPushButton]:
        path = ui_dir() / "browser_cookie_dialog.ui"
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open browser cookie form: {path}")
        try:
            form = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if form is None:
            raise RuntimeError(f"Unable to load browser cookie form: {path}")
        form.setParent(self)
        form.setGeometry(self.rect())
        self.form = form
        web_host = form.findChild(QWidget, "webHost")
        refresh_btn = form.findChild(QPushButton, "refreshButton")
        sync_btn = form.findChild(QPushButton, "syncButton")
        cancel_btn = form.findChild(QPushButton, "cancelButton")
        if not (web_host and web_host.layout() and refresh_btn and sync_btn and cancel_btn):
            raise RuntimeError("browser_cookie_dialog.ui is missing required controls")
        return web_host, refresh_btn, sync_btn, cancel_btn

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "form"):
            self.form.setGeometry(self.rect())

    def on_cookie_added(self, cookie):
        name = bytes(cookie.name()).decode("utf-8", "ignore")
        value = bytes(cookie.value()).decode("utf-8", "ignore")
        domain = cookie.domain().lstrip(".")
        path = cookie.path() or "/"
        if name:
            self.cookies[(domain, path, name)] = value

    def cookie_dict(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for (domain, _path, name), value in self.cookies.items():
            if not domain or self.target_domain.endswith(domain) or domain.endswith(self.target_domain):
                result[name] = value
        return result

    def cookie_header(self) -> str:
        return cookie_dict_to_header(self.cookie_dict())
