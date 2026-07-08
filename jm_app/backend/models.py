from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .runtime_paths import downloads_dir


@dataclass
class ChapterMeta:
    chapter_id: str
    title: str
    url: str
    index: int = 1


@dataclass
class AlbumMeta:
    album_id: str
    title: str
    url: str
    likes: str = "-"
    favorites: str = "-"
    source: str = "列表"
    cover_url: str = ""
    author: str = "-"
    page_count: str = "-"
    tags: List[str] = field(default_factory=list)
    chapters: List[ChapterMeta] = field(default_factory=list)
    selected_chapter_ids: List[str] = field(default_factory=list)


@dataclass
class NetworkConfig:
    cookie_header: str
    user_agent: str
    delay_min: float
    delay_max: float
    retries: int
    backoff_seconds: int
    stop_on_block: bool
    username: str = ""
    password: str = ""
    proxy: str = ""
    detail_threads: int = 6


@dataclass
class DownloadConfig(NetworkConfig):
    output_dir: Path = downloads_dir()
    image_threads: int = 2
    output_format: str = "pdf"
    pdf_split_chapters: bool = False
    keep_images: bool = True
    use_jmcomic: bool = True
    reading_mode: str = "scroll"
    cache_as_webp: bool = False
