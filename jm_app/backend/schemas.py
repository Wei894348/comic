from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from .runtime_paths import downloads_dir


class ChapterSchema(BaseModel):
    chapter_id: str
    title: str
    url: str = ""
    index: int = 1


class AlbumSchema(BaseModel):
    album_id: str
    title: str
    url: str = ""
    likes: str = "-"
    favorites: str = "-"
    source: str = "API"
    cover_url: str = ""
    author: str = "-"
    page_count: str = "-"
    tags: List[str] = Field(default_factory=list)
    chapters: List[ChapterSchema] = Field(default_factory=list)
    selected_chapter_ids: List[str] = Field(default_factory=list)


class NetworkSettings(BaseModel):
    cookie_header: str = ""
    user_agent: str = ""
    delay_min: float = 1.0
    delay_max: float = 3.0
    retries: int = 3
    backoff_seconds: int = 3
    stop_on_block: bool = True
    username: str = ""
    password: str = ""
    proxy: str = ""
    detail_threads: int = 6


class DownloadSettings(NetworkSettings):
    output_dir: Path = downloads_dir()
    image_threads: int = 4
    output_format: str = "pdf"
    pdf_split_chapters: bool = False
    keep_images: bool = True
    use_jmcomic: bool = True
    reading_mode: str = "scroll"
    cache_as_webp: bool = False


class SearchResponse(BaseModel):
    albums: List[AlbumSchema]
    count: int


class DownloadRequest(BaseModel):
    albums: List[AlbumSchema]
    settings: Optional[DownloadSettings] = None


class DownloadJobStatus(BaseModel):
    job_id: str
    status: str
    current_album_id: str = ""
    current_title: str = ""
    done: int = 0
    total: int = 0
    logs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    error: str = ""
