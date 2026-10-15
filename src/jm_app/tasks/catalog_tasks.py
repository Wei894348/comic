from __future__ import annotations

from ..backend.models import NetworkConfig
from ..models import PageQuery
from ..services import CatalogService
from .base import ManagedTask


class CatalogPageTask(ManagedTask):
    def __init__(self, query: PageQuery, page: int, config: NetworkConfig, generation: int = 0, parent=None):
        super().__init__(generation, parent)
        self.query = query
        self.page = max(1, int(page))
        self.config = config
        self.service = CatalogService()

    def execute(self):
        books, sections = self.service.load_page(self.query, self.page, self.config, self.cancel_event)
        return {"query": self.query, "page": self.page, "books": books, "sections": sections, "generation": self.generation}
