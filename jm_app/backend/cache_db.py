import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable, List, Optional

from .models import AlbumMeta, ChapterMeta


def default_cache_db_path() -> Path:
    return Path.home() / ".comic18" / "comic18.sqlite3"


class ComicCacheDB:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or default_cache_db_path()
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
                CREATE TABLE IF NOT EXISTS albums (
                    album_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT,
                    likes TEXT,
                    page_count TEXT,
                    cover_url TEXT,
                    author TEXT,
                    tags_json TEXT,
                    updated_at REAL,
                    last_access_at REAL
                );
                CREATE TABLE IF NOT EXISTS chapters (
                    chapter_id TEXT PRIMARY KEY,
                    album_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    chapter_index INTEGER,
                    local_path TEXT,
                    image_count INTEGER DEFAULT 0,
                    downloaded INTEGER DEFAULT 0,
                    updated_at REAL,
                    FOREIGN KEY(album_id) REFERENCES albums(album_id)
                );
                CREATE INDEX IF NOT EXISTS idx_chapters_album ON chapters(album_id, chapter_index);
                """
            )

    def upsert_album(self, album: AlbumMeta):
        now = time.time()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO albums(album_id, title, url, likes, page_count, cover_url, author, tags_json, updated_at, last_access_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(album_id) DO UPDATE SET
                    title=excluded.title,
                    url=excluded.url,
                    likes=excluded.likes,
                    page_count=excluded.page_count,
                    cover_url=excluded.cover_url,
                    author=excluded.author,
                    tags_json=excluded.tags_json,
                    updated_at=excluded.updated_at
                """,
                (
                    album.album_id,
                    album.title,
                    album.url,
                    album.likes,
                    album.page_count,
                    album.cover_url,
                    album.author,
                    json.dumps(album.tags, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            for chapter in album.chapters:
                db.execute(
                    """
                    INSERT INTO chapters(chapter_id, album_id, title, url, chapter_index, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chapter_id) DO UPDATE SET
                        album_id=excluded.album_id,
                        title=excluded.title,
                        url=excluded.url,
                        chapter_index=excluded.chapter_index,
                        updated_at=excluded.updated_at
                    """,
                    (chapter.chapter_id, album.album_id, chapter.title, chapter.url, chapter.index, now),
                )

    def get_album(self, album_id: str) -> Optional[AlbumMeta]:
        with self.connect() as db:
            row = db.execute(
                "SELECT album_id,title,url,likes,page_count,cover_url,author,tags_json FROM albums WHERE album_id=?",
                (album_id,),
            ).fetchone()
            if not row:
                return None
            db.execute("UPDATE albums SET last_access_at=? WHERE album_id=?", (time.time(), album_id))
            chapters = [
                ChapterMeta(chapter_id=str(item[0]), title=item[1], url=item[2] or "", index=int(item[3] or 1))
                for item in db.execute(
                    "SELECT chapter_id,title,url,chapter_index FROM chapters WHERE album_id=? ORDER BY chapter_index, chapter_id",
                    (album_id,),
                )
            ]
        tags = []
        try:
            tags = json.loads(row[7] or "[]")
        except Exception:
            tags = []
        return AlbumMeta(
            album_id=str(row[0]),
            title=row[1],
            url=row[2] or "",
            likes=row[3] or "-",
            page_count=row[4] or "-",
            cover_url=row[5] or "",
            author=row[6] or "-",
            tags=tags,
            chapters=chapters,
            source="DB",
        )

    def all_album_ids(self) -> List[str]:
        with self.connect() as db:
            return [str(row[0]) for row in db.execute("SELECT album_id FROM albums ORDER BY last_access_at DESC")]

    def recent_albums(self, limit: int = 240) -> List[AlbumMeta]:
        with self.connect() as db:
            rows = list(
                db.execute(
                    "SELECT album_id FROM albums ORDER BY updated_at DESC, last_access_at DESC LIMIT ?",
                    (max(1, limit),),
                )
            )
        albums = []
        for row in rows:
            album = self.get_album(str(row[0]))
            if album is not None:
                albums.append(album)
        return albums

    def downloaded_chapter_ids(self, album_id: str) -> set:
        with self.connect() as db:
            return {
                str(row[0])
                for row in db.execute(
                    "SELECT chapter_id FROM chapters WHERE album_id=? AND downloaded=1",
                    (album_id,),
                )
            }

    def known_chapter_ids(self, album_id: str) -> set:
        with self.connect() as db:
            return {
                str(row[0])
                for row in db.execute(
                    "SELECT chapter_id FROM chapters WHERE album_id=?",
                    (album_id,),
                )
            }

    def mark_chapter_downloaded(self, album_id: str, chapter: ChapterMeta, local_path: Path, image_count: int):
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO chapters(chapter_id, album_id, title, url, chapter_index, local_path, image_count, downloaded, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?)
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
                    image_count,
                    time.time(),
                ),
            )

    def cached_chapter_path(self, chapter_id: str) -> Optional[Path]:
        with self.connect() as db:
            row = db.execute(
                "SELECT local_path FROM chapters WHERE chapter_id=? AND downloaded=1",
                (chapter_id,),
            ).fetchone()
        if not row or not row[0]:
            return None
        path = Path(row[0])
        return path if path.exists() else None
