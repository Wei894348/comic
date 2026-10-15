from __future__ import annotations

import threading
from io import BytesIO

from PySide6.QtGui import QImage
from PIL import Image

from ..backend.constants import DEFAULT_USER_AGENT
from ..backend.network_session import create_network_session
from ..repositories import CoverCacheRepository


class CoverService:
    # JMComic-qt retries the same image request against every configured
    # image host.  A cover URL is only a route seed; it must not become a
    # single point of failure when that CDN is unavailable.
    REQUEST_TIMEOUT = (2.5, 6)

    def __init__(self, cache: CoverCacheRepository | None = None):
        self.cache = cache or CoverCacheRepository()
        self.failed_urls: list[str] = []
        self.loaded_url = ""

    @staticmethod
    def decode_image(data: bytes) -> QImage:
        """Decode JPEG/WebP even when the deployed Qt image plugins are absent."""
        image = QImage.fromData(data)
        if not image.isNull():
            return image
        try:
            with Image.open(BytesIO(data)) as source:
                rgba = source.convert("RGBA")
                qt_image = QImage(
                    rgba.tobytes(),
                    rgba.width,
                    rgba.height,
                    QImage.Format_RGBA8888,
                )
                return qt_image.copy()
        except Exception:
            return QImage()

    def load(
        self, book_id: str, urls: list[str], proxy: str, referer_domain: str,
        user_agent: str,
        cancel_event: threading.Event, use_disk_cache: bool = True,
        doh_enabled: bool = True, doh_url: str = "",
    ) -> QImage:
        self.failed_urls = []
        self.loaded_url = ""
        data = self.cache.read(book_id) if use_disk_cache else None
        if data:
            image = self.decode_image(data)
            if not image.isNull():
                return image
        headers = {
            "User-Agent": user_agent.strip() or DEFAULT_USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "X-Requested-With": "com.JMComic3.app",
            "Referer": f"https://{referer_domain}/",
        }
        last_error = "封面请求失败"
        with create_network_session(
            headers["User-Agent"], proxy, doh_enabled, doh_url
        ) as session:
            for url in self._unique_urls(urls):
                if cancel_event.is_set():
                    raise RuntimeError("任务已取消")
                try:
                    response = session.get(
                        url,
                        headers=headers,
                        timeout=self.REQUEST_TIMEOUT,
                    )
                    response.raise_for_status()
                    if not response.content:
                        raise RuntimeError("封面为空")
                    image = self.decode_image(response.content)
                    if image.isNull():
                        raise RuntimeError(f"封面数据无法解析：{len(response.content)} bytes")
                    self.cache.write(book_id, response.content)
                    self.loaded_url = url
                    return image
                except Exception as exc:
                    self.failed_urls.append(url)
                    last_error = str(exc)
        raise RuntimeError(last_error)

    @staticmethod
    def _unique_urls(urls: list[str]):
        """Preserve CDN failover order while avoiding duplicate requests."""
        seen = set()
        for value in urls:
            url = str(value or "").strip()
            if url and url not in seen:
                seen.add(url)
                yield url
