from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..models import DownloadState, DownloadTaskInfo
from ..backend.runtime_paths import app_data_dir


class StateRepository:
    """Durable user state only; online catalogue metadata is never stored here."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or app_data_dir() / "state.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _init_schema(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS download_tasks (
                    task_id TEXT PRIMARY KEY,
                    book_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    state TEXT NOT NULL,
                    output_dir TEXT NOT NULL DEFAULT '',
                    current_chapter_id TEXT NOT NULL DEFAULT '',
                    total_images INTEGER NOT NULL DEFAULT 0,
                    done_images INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_download_tasks_state ON download_tasks(state, updated_at DESC);
                CREATE TABLE IF NOT EXISTS reading_progress (
                    book_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    page_index INTEGER NOT NULL DEFAULT 1,
                    page_total INTEGER NOT NULL DEFAULT 0,
                    source_key TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(book_id, chapter_id)
                );
                CREATE TABLE IF NOT EXISTS reading_history (
                    book_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    cover_url TEXT NOT NULL DEFAULT '',
                    chapter_title TEXT NOT NULL DEFAULT '',
                    chapter_index INTEGER NOT NULL DEFAULT 0,
                    chapter_total INTEGER NOT NULL DEFAULT 0,
                    last_opened_at REAL NOT NULL,
                    PRIMARY KEY(book_id, chapter_id)
                );
                """
            )
            columns = {
                str(row[1]) for row in db.execute("PRAGMA table_info(reading_history)")
            }
            for name, definition in (
                ("chapter_title", "TEXT NOT NULL DEFAULT ''"),
                ("chapter_index", "INTEGER NOT NULL DEFAULT 0"),
                ("chapter_total", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE reading_history ADD COLUMN {name} {definition}"
                    )

    def save_download_task(self, task: DownloadTaskInfo) -> None:
        now = time.time()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO download_tasks(
                    task_id, book_id, title, state, output_dir, current_chapter_id,
                    total_images, done_images, error_message, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state=excluded.state, output_dir=excluded.output_dir,
                    current_chapter_id=excluded.current_chapter_id,
                    total_images=excluded.total_images, done_images=excluded.done_images,
                    error_message=excluded.error_message, updated_at=excluded.updated_at
                """,
                (
                    task.task_id, task.book_id, task.title, task.state.value,
                    task.output_dir, task.current_chapter_id, task.total_images,
                    task.done_images, task.error_message, now, now,
                ),
            )

    def update_download_state(self, task_id: str, state: DownloadState, **values) -> None:
        allowed = {"current_chapter_id", "total_images", "done_images", "error_message", "output_dir"}
        assignments = ["state=?", "updated_at=?"]
        params = [state.value, time.time()]
        for key, value in values.items():
            if key in allowed:
                assignments.append(f"{key}=?")
                params.append(value)
        params.append(task_id)
        with self.connect() as db:
            db.execute(f"UPDATE download_tasks SET {', '.join(assignments)} WHERE task_id=?", params)

    def save_progress(self, book_id: str, chapter_id: str, page_index: int, page_total: int, source_key: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO reading_progress(book_id, chapter_id, page_index, page_total, source_key, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id, chapter_id) DO UPDATE SET
                    page_index=excluded.page_index, page_total=excluded.page_total,
                    source_key=excluded.source_key, updated_at=excluded.updated_at
                """,
                (book_id, chapter_id, max(1, page_index), max(0, page_total), source_key, time.time()),
            )

    def progress(self, book_id: str, chapter_id: str) -> tuple[int, int, str]:
        with self.connect() as db:
            row = db.execute(
                "SELECT page_index, page_total, source_key FROM reading_progress WHERE book_id=? AND chapter_id=?",
                (book_id, chapter_id),
            ).fetchone()
        return (int(row[0]), int(row[1]), str(row[2])) if row else (1, 0, "")

    def record_reading_history(
        self,
        book_id: str,
        chapter_id: str,
        title: str,
        cover_url: str,
        chapter_title: str = "",
        chapter_index: int = 0,
        chapter_total: int = 0,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO reading_history(
                    book_id, chapter_id, title, cover_url, chapter_title,
                    chapter_index, chapter_total, last_opened_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id, chapter_id) DO UPDATE SET
                    title=excluded.title, cover_url=excluded.cover_url,
                    chapter_title=excluded.chapter_title,
                    chapter_index=excluded.chapter_index,
                    chapter_total=excluded.chapter_total,
                    last_opened_at=excluded.last_opened_at
                """,
                (
                    book_id,
                    chapter_id,
                    title,
                    cover_url,
                    chapter_title,
                    max(0, int(chapter_index)),
                    max(0, int(chapter_total)),
                    time.time(),
                ),
            )

    def reading_history(self, limit: int = 0, offset: int = 0) -> List[Dict]:
        """Return one most-recent reading position for each comic."""
        sql = """
            SELECT h.book_id, h.chapter_id, h.title, h.cover_url,
                   h.chapter_title, h.chapter_index, h.chapter_total,
                   h.last_opened_at, COALESCE(p.page_index, 1),
                   COALESCE(p.page_total, 0), COALESCE(p.source_key, '')
            FROM reading_history AS h
            LEFT JOIN reading_progress AS p
              ON p.book_id=h.book_id AND p.chapter_id=h.chapter_id
            WHERE h.rowid = (
                SELECT h2.rowid FROM reading_history AS h2
                WHERE h2.book_id=h.book_id
                ORDER BY h2.last_opened_at DESC, h2.rowid DESC LIMIT 1
            )
            ORDER BY h.last_opened_at DESC
        """
        params: List[int] = []
        if int(limit) > 0:
            sql += " LIMIT ? OFFSET ?"
            params.extend((int(limit), max(0, int(offset))))
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        keys = (
            "book_id",
            "chapter_id",
            "title",
            "cover_url",
            "chapter_title",
            "chapter_index",
            "chapter_total",
            "last_opened_at",
            "page_index",
            "page_total",
            "source_key",
        )
        return [dict(zip(keys, row)) for row in rows]

    def delete_reading_history(self, book_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM reading_history WHERE book_id=?", (book_id,))
            db.execute("DELETE FROM reading_progress WHERE book_id=?", (book_id,))

    def clear_reading_history(self) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM reading_history")
            db.execute("DELETE FROM reading_progress")
