"""Persistent local collections for Comic18's offline library.

JMComic-qt kept a second SQLite database for local favourites and folders.
Comic18 already owns a SQLite cache, so this module keeps the same user-facing
capability without duplicating its application state or coupling it to a
network account.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

from .models import AlbumMeta
from .runtime_paths import sqlite_cache_path


class LocalCollectionStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or sqlite_cache_path()
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
                CREATE TABLE IF NOT EXISTS local_collections (
                    collection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_collection_albums (
                    collection_id INTEGER NOT NULL,
                    album_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    cover_url TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    chapter_count INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    added_at REAL NOT NULL,
                    PRIMARY KEY(collection_id, album_id),
                    FOREIGN KEY(collection_id) REFERENCES local_collections(collection_id)
                );
                CREATE INDEX IF NOT EXISTS idx_local_collection_albums_added
                    ON local_collection_albums(collection_id, added_at DESC);
                """
            )
            columns = {
                str(row[1]) for row in db.execute("PRAGMA table_info(local_collection_albums)")
            }
            migrations = {
                "author": "TEXT NOT NULL DEFAULT ''",
                "tags_json": "TEXT NOT NULL DEFAULT '[]'",
                "chapter_count": "INTEGER NOT NULL DEFAULT 0",
                "updated_at": "REAL NOT NULL DEFAULT 0",
            }
            for column, definition in migrations.items():
                if column not in columns:
                    db.execute(
                        f"ALTER TABLE local_collection_albums ADD COLUMN {column} {definition}"
                    )
            db.execute(
                "UPDATE local_collection_albums SET updated_at=added_at WHERE updated_at<=0"
            )

    def list_collections(self) -> List[tuple[int, str, int]]:
        with self.connect() as db:
            return [
                (int(row[0]), str(row[1]), int(row[2] or 0))
                for row in db.execute(
                    """
                    SELECT c.collection_id, c.name, COUNT(a.album_id)
                    FROM local_collections c
                    LEFT JOIN local_collection_albums a ON a.collection_id = c.collection_id
                    GROUP BY c.collection_id, c.name
                    ORDER BY c.name COLLATE NOCASE
                    """
                )
            ]

    def add_collection(self, name: str) -> int:
        name = str(name or "").strip()
        if not name:
            raise ValueError("收藏夹名称不能为空")
        with self.connect() as db:
            db.execute("INSERT INTO local_collections(name, created_at) VALUES(?, ?)", (name, time.time()))
            return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

    def ensure_collection(self, name: str) -> int:
        name = str(name or "").strip()
        if not name:
            raise ValueError("收藏夹名称不能为空")
        with self.connect() as db:
            row = db.execute(
                "SELECT collection_id FROM local_collections WHERE name=? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if row is not None:
                return int(row[0])
            db.execute(
                "INSERT INTO local_collections(name, created_at) VALUES(?, ?)",
                (name, time.time()),
            )
            return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

    def remove_collection(self, collection_id: int):
        with self.connect() as db:
            db.execute("DELETE FROM local_collection_albums WHERE collection_id=?", (collection_id,))
            db.execute("DELETE FROM local_collections WHERE collection_id=?", (collection_id,))

    def add_album(self, collection_id: int, album: AlbumMeta):
        if not album.album_id:
            raise ValueError("漫画 ID 不能为空")
        now = time.time()
        tags_json = json.dumps(list(album.tags or []), ensure_ascii=False)
        chapter_count = len(album.chapters or [])
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO local_collection_albums(
                    collection_id, album_id, title, cover_url, author, tags_json,
                    chapter_count, updated_at, added_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_id, album_id) DO UPDATE SET
                    title=excluded.title,
                    cover_url=excluded.cover_url,
                    author=excluded.author,
                    tags_json=excluded.tags_json,
                    chapter_count=MAX(local_collection_albums.chapter_count, excluded.chapter_count),
                    added_at=excluded.added_at
                """,
                (
                    collection_id,
                    album.album_id,
                    album.title or album.album_id,
                    album.cover_url or "",
                    album.author or "",
                    tags_json,
                    chapter_count,
                    now,
                    now,
                ),
            )

    def add_albums(self, collection_id: int, albums: List[AlbumMeta]) -> int:
        rows = []
        now = time.time()
        for album in albums:
            if not isinstance(album, AlbumMeta) or not album.album_id:
                continue
            rows.append(
                (
                    collection_id,
                    album.album_id,
                    album.title or album.album_id,
                    album.cover_url or "",
                    album.author or "",
                    json.dumps(list(album.tags or []), ensure_ascii=False),
                    len(album.chapters or []),
                    now,
                    now,
                )
            )
        if not rows:
            return 0
        with self.connect() as db:
            db.executemany(
                """
                INSERT INTO local_collection_albums(
                    collection_id, album_id, title, cover_url, author, tags_json,
                    chapter_count, updated_at, added_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_id, album_id) DO UPDATE SET
                    title=excluded.title,
                    cover_url=excluded.cover_url,
                    author=excluded.author,
                    tags_json=excluded.tags_json,
                    chapter_count=MAX(local_collection_albums.chapter_count, excluded.chapter_count),
                    added_at=excluded.added_at
                """,
                rows,
            )
        return len(rows)

    def update_album(self, album: AlbumMeta) -> bool:
        if not album.album_id:
            return False
        tags_json = json.dumps(list(album.tags or []), ensure_ascii=False)
        chapter_count = len(album.chapters or [])
        with self.connect() as db:
            previous = db.execute(
                "SELECT MAX(chapter_count) FROM local_collection_albums WHERE album_id=?",
                (str(album.album_id),),
            ).fetchone()
            if previous is None or previous[0] is None:
                return False
            changed = int(previous[0] or 0) != chapter_count
            db.execute(
                """
                UPDATE local_collection_albums
                SET title=?, cover_url=?, author=?, tags_json=?, chapter_count=?,
                    updated_at=CASE WHEN chapter_count!=? THEN ? ELSE updated_at END
                WHERE album_id=?
                """,
                (
                    album.title or album.album_id,
                    album.cover_url or "",
                    album.author or "",
                    tags_json,
                    chapter_count,
                    chapter_count,
                    time.time(),
                    str(album.album_id),
                ),
            )
            return changed

    def remove_album(self, collection_id: int, album_id: str):
        with self.connect() as db:
            db.execute(
                "DELETE FROM local_collection_albums WHERE collection_id=? AND album_id=?",
                (collection_id, str(album_id)),
            )

    def remove_album_all(self, album_id: str):
        with self.connect() as db:
            db.execute(
                "DELETE FROM local_collection_albums WHERE album_id=?",
                (str(album_id),),
            )

    def count_albums(self, collection_id: Optional[int] = None, query: str = "") -> int:
        where = []
        params = []
        if collection_id is not None and int(collection_id) >= 0:
            where.append("collection_id=?")
            params.append(int(collection_id))
        query = str(query or "").strip()
        if query:
            where.append(
                "(title LIKE ? OR album_id LIKE ? OR author LIKE ? OR tags_json LIKE ?)"
            )
            value = f"%{query}%"
            params.extend([value, value, value, value])
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as db:
            row = db.execute(
                f"SELECT COUNT(DISTINCT album_id) FROM local_collection_albums{clause}",
                params,
            ).fetchone()
        return int((row or [0])[0] or 0)

    def search_albums(
        self,
        collection_id: Optional[int] = None,
        query: str = "",
        sort_key: str = "updated_at",
        descending: bool = True,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AlbumMeta]:
        where = []
        params = []
        if collection_id is not None and int(collection_id) >= 0:
            where.append("collection_id=?")
            params.append(int(collection_id))
        query = str(query or "").strip()
        if query:
            where.append(
                "(title LIKE ? OR album_id LIKE ? OR author LIKE ? OR tags_json LIKE ?)"
            )
            value = f"%{query}%"
            params.extend([value, value, value, value])
        clause = " WHERE " + " AND ".join(where) if where else ""
        order_column = "added_at" if sort_key == "added_at" else "updated_at"
        direction = "DESC" if descending else "ASC"
        pagination = ""
        if limit is not None:
            pagination = " LIMIT ? OFFSET ?"
            params.extend([max(1, int(limit)), max(0, int(offset))])
        with self.connect() as db:
            rows = list(
                db.execute(
                    f"""
                    SELECT album_id, MAX(title), MAX(cover_url), MAX(author),
                           MAX(tags_json), MAX(chapter_count), MAX(added_at), MAX(updated_at)
                    FROM local_collection_albums
                    {clause}
                    GROUP BY album_id
                    ORDER BY MAX({order_column}) {direction}, album_id DESC
                    {pagination}
                    """,
                    params,
                )
            )
        albums = []
        for row in rows:
            try:
                tags = json.loads(str(row[4] or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                tags = []
            album = AlbumMeta(
                album_id=str(row[0]),
                title=str(row[1] or row[0]),
                url=f"jm://album/{row[0]}",
                cover_url=str(row[2] or ""),
                author=str(row[3] or "-"),
                tags=[str(tag) for tag in tags if str(tag).strip()],
                source="本地收藏",
            )
            album.local_chapter_count = int(row[5] or 0)
            album.local_added_at = float(row[6] or 0)
            album.local_updated_at = float(row[7] or 0)
            albums.append(album)
        return albums

    def albums(self, collection_id: int) -> List[AlbumMeta]:
        return self.search_albums(collection_id=collection_id, sort_key="added_at")
