from typing import Dict, Tuple
from urllib.parse import urlparse

from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)
from PyQt5.QtWebEngineWidgets import QWebEngineProfile, QWebEngineView

from ..backend.constants import LIST_URL
from ..backend.cookie_store import cookie_dict_to_header


class BrowserCookieDialog(QDialog):
    def __init__(self, parent=None, url: str = LIST_URL):
        super().__init__(parent)
        self.setWindowTitle("浏览器验证 Cookie")
        self.resize(980, 720)
        self.cookies: Dict[Tuple[str, str, str], str] = {}
        self.target_domain = urlparse(url).netloc

        layout = QVBoxLayout(self)
        tip = QLabel("请在此浏览器窗口中完成网站验证/登录，然后点击“同步 Cookie”。")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.profile = QWebEngineProfile.defaultProfile()
        self.profile.cookieStore().cookieAdded.connect(self.on_cookie_added)
        self.profile.cookieStore().loadAllCookies()

        self.web = QWebEngineView()
        self.web.setUrl(QUrl(url))
        layout.addWidget(self.web, 1)

        row = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.web.reload)
        sync_btn = QPushButton("同步 Cookie")
        sync_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(refresh_btn)
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(sync_btn)
        layout.addLayout(row)

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
