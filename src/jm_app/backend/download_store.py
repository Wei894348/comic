from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from .models import ChapterMeta
from .runtime_paths import download_db_path


class DownloadStore:
    """Only persists download state; online album metadata stays in memory."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or download_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _init_schema(self):
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS download_chapters (
                    chapter_id TEXT PRIMARY KEY,
                    album_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    chapter_index INTEGER,
                    local_path TEXT NOT NULL,
                    image_count INTEGER NOT NULL DEFAULT 0,
                    downloaded INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_download_chapters_album
                    ON download_chapters(album_id, chapter_index);
                CREATE TABLE IF NOT EXISTS download_tasks (
                    album_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    save_path TEXT,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def downloaded_chapter_ids(self, album_id: str) -> set[str]:
        with self.connect() as db:
            return {
                str(row[0])
                for row in db.execute(
                    "SELECT chapter_id FROM download_chapters WHERE album_id=? AND downloaded=1",
                    (album_id,),
                )
            }

    def cached_chapter_path(self, chapter_id: str) -> Optional[Path]:
        with self.connect() as db:
            row = db.execute(
                "SELECT local_path FROM download_chapters WHERE chapter_id=? AND downloaded=1",
                (chapter_id,),
            ).fetchone()
        if not row or not row[0]:
            return None
        path = Path(row[0])
        return path if path.exists() else None

    def mark_chapter_downloaded(
        self, album_id: str, chapter: ChapterMeta, local_path: Path, image_count: int
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO download_chapters(
                    chapter_id, album_id, title, url, chapter_index, local_path,
                    image_count, downloaded, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(chapter_id) DO UPDATE SET
                    album_id=excluded.album_id,
                    title=excluded.title,
                    url=excluded.url,
                    chapter_index=excluded.chapter_index,
                    local_path=excluded.local_path,
                    image_count=excluded.image_count,
                    downloaded=1,
                    updated_at=excluded.updated_at
                """,
                (
                    chapter.chapter_id,
                    album_id,
                    chapter.title,
                    chapter.url,
                    chapter.index,
                    str(local_path),
                    max(0, int(image_count)),
                    time.time(),
                ),
            )

    def update_task(self, album_id: str, title: str, save_path: Path, status: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO download_tasks(album_id, title, save_path, status, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(album_id) DO UPDATE SET
                    title=excluded.title,
                    save_path=excluded.save_path,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (album_id, title, str(save_path), status, time.time()),
            )
