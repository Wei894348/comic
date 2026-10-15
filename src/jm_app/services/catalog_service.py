from __future__ import annotations

import threading
from typing import Dict, List, Tuple

from ..backend.jm_api import JmApiClient
from ..backend.models import NetworkConfig
from ..models import BookInfo, PageQuery


class CatalogService:
    def load_page(
        self, query: PageQuery, page: int, config: NetworkConfig, cancel_event: threading.Event
    ) -> Tuple[List[BookInfo], Dict[str, List[BookInfo]]]:
        client = JmApiClient(config, cancel_event=cancel_event)
        page = max(1, int(page))
        sections: Dict[str, List[BookInfo]] = {}
        if query.mode == "search":
            albums = client.search(query.search, page=page)
        elif query.mode == "latest":
            albums = client.latest(page=page - 1)
        elif query.mode == "promote":
            if page == 1:
                raw_sections = client.promote_sections(page=page)
                sections = {
                    title: [BookInfo.from_meta(album) for album in values]
                    for title, values in raw_sections.items()
                }
                if query.promote_section:
                    prefix = "".join(query.promote_section.split()).lower()
                    books = next(
                        (
                            values
                            for title, values in sections.items()
                            if "".join(title.split()).lower().startswith(prefix)
                        ),
                        [],
                    )
                else:
                    books = [book for values in sections.values() for book in values]
                return books, sections

            # The App API's /promote endpoint is a static home payload: it
            # returns the same section cards for every page value. Continue
            # from JMComic-qt's pageable /latest feed after that curated
            # first page so a bottom-scroll can add real, non-duplicate work.
            albums = client.latest(page=page - 2)
        elif query.mode == "category":
            albums = client.category(query.category, page=page)
        else:
            albums = client.ranking(query.rank_type, page=page, category=query.category)
        return [BookInfo.from_meta(album) for album in albums], sections
