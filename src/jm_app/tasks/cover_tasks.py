from __future__ import annotations

from PySide6.QtCore import Signal

from ..services import CoverService
from .base import ManagedTask


class CoverTask(ManagedTask):
    failed_with_context = Signal(object)

    def __init__(
        self, book_id: str, urls: list[str], proxy: str, referer_domain: str,
        user_agent: str = "", use_disk_cache: bool = True, generation: int = 0,
        doh_enabled: bool = True, doh_url: str = "", parent=None
    ):
        super().__init__(generation, parent)
        self.book_id = book_id
        self.urls = list(urls)
        self.proxy = proxy
        self.referer_domain = referer_domain
        self.user_agent = user_agent
        self.use_disk_cache = use_disk_cache
        self.doh_enabled = doh_enabled
        self.doh_url = doh_url
        self.failed_urls: list[str] = []
        self.service = CoverService()

    def execute(self):
        try:
            image = self.service.load(
                self.book_id,
                self.urls,
                self.proxy,
                self.referer_domain,
                self.user_agent,
                self.cancel_event,
                self.use_disk_cache,
                self.doh_enabled,
                self.doh_url,
            )
            return {
                "book_id": self.book_id,
                "image": image,
                "generation": self.generation,
                "failed_urls": list(self.service.failed_urls),
                "source_url": self.service.loaded_url,
            }
        finally:
            self.failed_urls = list(self.service.failed_urls)

    def run(self) -> None:
        """Return failures to the GUI thread with the queue key attached."""
        try:
            result = self.execute()
            if self.is_cancelled():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        except Exception as exc:
            if self.is_cancelled():
                self.cancelled.emit()
            else:
                self.failed_with_context.emit(
                    {
                        "book_id": self.book_id,
                        "message": str(exc),
                        "failed_urls": list(self.failed_urls),
                    }
                )
