from __future__ import annotations

from ..backend.models import NetworkConfig
from ..models import BookInfo
from ..services import DetailService
from .base import ManagedTask


class DetailTask(ManagedTask):
    def __init__(self, book_id: str, config: NetworkConfig, generation: int = 0, parent=None):
        super().__init__(generation, parent)
        self.book_id = book_id
        self.config = config
        self.service = DetailService()

    def execute(self):
        return {"book": self.service.load_book(self.book_id, self.config, self.cancel_event), "generation": self.generation}


class ImageListTask(ManagedTask):
    def __init__(self, book: BookInfo, chapter_id: str, config: NetworkConfig, generation: int = 0, parent=None):
        super().__init__(generation, parent)
        self.book = book
        self.chapter_id = chapter_id
        self.config = config
        self.service = DetailService()

    def execute(self):
        chapter_id, images = self.service.load_images(self.book, self.chapter_id, self.config, self.cancel_event)
        return {"chapter_id": chapter_id, "images": images, "generation": self.generation}
