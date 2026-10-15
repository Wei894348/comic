from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ..backend.jm_api import APP_USER_AGENT
from ..backend.jm_endpoints import API_DOMAINS
from ..backend.network_session import DOH_URL, create_network_session


class CoverFetchWorker(QThread):
    loaded = Signal(str, object, str, object)
    failed = Signal(str, str, object)

    def __init__(
        self,
        album_id: str,
        urls: List[str],
        proxy: str = "",
        referer_domain: str = "",
        cache_paths: Optional[List[Path]] = None,
        doh_enabled: bool = True,
        doh_url: str = DOH_URL,
        parent=None,
    ):
        super().__init__(parent)
        self.album_id = album_id
        self.urls = urls
        self.proxy = proxy.strip()
        self.referer_domain = referer_domain or API_DOMAINS[0]
        self.cache_paths = list(cache_paths or [])
        self.doh_enabled = doh_enabled
        self.doh_url = doh_url
        self.cancel_event = threading.Event()
        self._session: Optional[requests.Session] = None

    def cancel(self):
        self.cancel_event.set()
        self.requestInterruption()
        if self._session is not None:
            self._session.close()

    def run(self):
        if self.cancel_event.is_set():
            return
        for cache_path in self.cache_paths:
            try:
                if cache_path.exists() and cache_path.stat().st_size > 0:
                    data = cache_path.read_bytes()
                    if data and not self.cancel_event.is_set():
                        self.loaded.emit(self.album_id, data, f"cache://{self.album_id}", [])
                        return
            except OSError:
                continue
        headers = {
            "User-Agent": APP_USER_AGENT,
            "Referer": f"https://{self.referer_domain}/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        failed_urls = []
        last_error = ""
        session = create_network_session(
            APP_USER_AGENT, self.proxy, self.doh_enabled, self.doh_url
        )
        self._session = session
        for url in self.urls:
            if self.cancel_event.is_set():
                return
            try:
                response = session.get(url, headers=headers, timeout=(5, 12))
                if self.cancel_event.is_set():
                    return
                response.raise_for_status()
                if not response.content:
                    raise RuntimeError("封面为空")
                self.loaded.emit(self.album_id, response.content, url, failed_urls)
                return
            except Exception as exc:
                failed_urls.append(url)
                last_error = str(exc)
        if not self.cancel_event.is_set():
            self.failed.emit(self.album_id, last_error or "封面请求失败", failed_urls)


class CoverDecodeWorker(QThread):
    decoded = Signal(str, object, object, str, object)
    failed = Signal(str, str, str, object)

    def __init__(self, album_id: str, data: bytes, url: str, failed_urls: List[str], parent=None):
        super().__init__(parent)
        self.album_id = album_id
        self.data = bytes(data or b"")
        self.url = str(url or "")
        self.failed_urls = list(failed_urls or [])

    def run(self):
        try:
            image = QImage.fromData(self.data)
            if image.isNull():
                raise RuntimeError(f"封面数据无法解析：{len(self.data)} bytes")
            if not self.isInterruptionRequested():
                self.decoded.emit(self.album_id, image, self.data, self.url, self.failed_urls)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(self.album_id, str(exc), self.url, self.failed_urls)
