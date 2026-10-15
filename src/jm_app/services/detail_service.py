from __future__ import annotations

import threading
from typing import List, Tuple

from ..backend.jm_api import JmApiClient
from ..backend.models import NetworkConfig
from ..models import BookInfo, ImageInfo


class DetailService:
    def load_book(self, book_id: str, config: NetworkConfig, cancel_event: threading.Event) -> BookInfo:
        client = JmApiClient(config, cancel_event=cancel_event)
        album = client.photo_as_album(book_id[1:]) if book_id.lower().startswith("p") else client.get_album_detail(book_id)
        return BookInfo.from_meta(album)

    def load_images(
        self, book: BookInfo, chapter_id: str, config: NetworkConfig, cancel_event: threading.Event
    ) -> Tuple[str, List[ImageInfo]]:
        client = JmApiClient(config, cancel_event=cancel_event)
        from ..backend.models import AlbumMeta

        album = AlbumMeta(album_id=book.book_id, title=book.title, url=book.url)
        photo = client.get_photo_detail(chapter_id, album, fetch_scramble=True)
        return photo.photo_id, [ImageInfo(index, name) for index, name in enumerate(photo.images, start=1)]
