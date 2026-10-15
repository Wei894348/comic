from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..backend.models import AlbumMeta, ChapterMeta


@dataclass
class ChapterInfo:
    chapter_id: str
    title: str
    url: str
    index: int

    @classmethod
    def from_meta(cls, value: ChapterMeta) -> "ChapterInfo":
        return cls(value.chapter_id, value.title, value.url, value.index)


@dataclass
class ImageInfo:
    image_index: int
    image_name: str
    remote_url: str = ""
    local_path: str = ""


@dataclass
class BookInfo:
    book_id: str
    title: str
    url: str
    cover_url: str = ""
    author: str = "-"
    tags: List[str] = field(default_factory=list)
    description: str = ""
    likes: str = "-"
    views: str = "-"
    page_count: str = "-"
    source: str = ""
    chapters: List[ChapterInfo] = field(default_factory=list)

    @classmethod
    def from_meta(cls, value: AlbumMeta) -> "BookInfo":
        return cls(
            book_id=value.album_id,
            title=value.title,
            url=value.url,
            cover_url=value.cover_url,
            author=value.author,
            tags=list(value.tags),
            description=value.description,
            likes=value.likes,
            views=value.views,
            page_count=value.page_count,
            source=value.source,
            chapters=[ChapterInfo.from_meta(chapter) for chapter in value.chapters],
        )

    def merge_meta(self, value: AlbumMeta) -> None:
        replacement = self.from_meta(value)
        for field_name in self.__dataclass_fields__:
            candidate = getattr(replacement, field_name)
            if candidate not in ("", "-", [], None):
                setattr(self, field_name, candidate)


@dataclass(frozen=True)
class PageQuery:
    """A stable key for a home/search/category page request."""

    mode: str = "ranking"
    rank_type: str = "day"
    category: str = ""
    search: str = ""
    promote_section: str = ""

    @property
    def key(self) -> str:
        return "|".join((self.mode, self.rank_type, self.category, self.search, self.promote_section))
