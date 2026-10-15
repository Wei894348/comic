from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DownloadState(str, Enum):
    QUEUED = "queued"
    FETCH_BOOK = "fetch_book"
    FETCH_CHAPTERS = "fetch_chapters"
    FETCH_IMAGES = "fetch_images"
    DOWNLOADING = "downloading"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class DownloadTaskInfo:
    task_id: str
    book_id: str
    title: str
    state: DownloadState
    output_dir: str = ""
    current_chapter_id: str = ""
    total_images: int = 0
    done_images: int = 0
    error_message: str = ""
