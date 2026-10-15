"""Persistent storage profiles and transfer history for the library tools."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .runtime_paths import sqlite_cache_path


@dataclass(frozen=True)
class StorageProfile:
    profile_id: int
    name: str
    transport: str
    destination: str
    webdav_url: str
    webdav_path: str
    username: str


@dataclass(frozen=True)
class StorageTransfer:
    transfer_id: int
    transport: str
    source: str
    destination: str
    status: str
    detail: str
    created_at: float
    finished_at: Optional[float]


class StorageStore:
    """Keeps non-secret NAS configuration and an audit trail of transfers."""

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
                CREATE TABLE IF NOT EXISTS storage_profiles (
                    profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    transport TEXT NOT NULL,
                    destination TEXT NOT NULL DEFAULT '',
                    webdav_url TEXT NOT NULL DEFAULT '',
                    webdav_path TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS storage_transfers (
                    transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transport TEXT NOT NULL,
                    source TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    finished_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_storage_transfers_created
                    ON storage_transfers(created_at DESC);
                """
            )

    def list_profiles(self) -> List[StorageProfile]:
        with self.connect() as db:
            rows = list(
                db.execute(
                    """
                    SELECT profile_id, name, transport, destination, webdav_url, webdav_path, username
                    FROM storage_profiles
                    ORDER BY name COLLATE NOCASE
                    """
                )
            )
        return [StorageProfile(*row) for row in rows]

    def save_profile(
        self,
        name: str,
        transport: str,
        destination: str = "",
        webdav_url: str = "",
        webdav_path: str = "",
        username: str = "",
    ) -> int:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Profile name cannot be empty")
        transport = str(transport or "").strip()
        if transport not in {"local_smb", "webdav"}:
            raise ValueError("Unsupported storage transport")
        values = (transport, str(destination or "").strip(), str(webdav_url or "").strip(), str(webdav_path or "").strip(), str(username or "").strip(), time.time(), name)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO storage_profiles(name, transport, destination, webdav_url, webdav_path, username, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    transport=excluded.transport,
                    destination=excluded.destination,
                    webdav_url=excluded.webdav_url,
                    webdav_path=excluded.webdav_path,
                    username=excluded.username,
                    updated_at=excluded.updated_at
                """,
                (name, *values[:-1]),
            )
            row = db.execute("SELECT profile_id FROM storage_profiles WHERE name=?", (name,)).fetchone()
        return int(row[0])

    def remove_profile(self, profile_id: int):
        with self.connect() as db:
            db.execute("DELETE FROM storage_profiles WHERE profile_id=?", (int(profile_id),))

    def add_transfer(self, transport: str, source: str, destination: str) -> int:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO storage_transfers(transport, source, destination, status, created_at)
                VALUES(?, ?, ?, 'running', ?)
                """,
                (str(transport), str(source), str(destination), time.time()),
            )
            return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

    def finish_transfer(self, transfer_id: int, status: str, detail: str = ""):
        if status not in {"completed", "failed"}:
            raise ValueError("Transfer status must be completed or failed")
        with self.connect() as db:
            db.execute(
                """
                UPDATE storage_transfers
                SET status=?, detail=?, finished_at=?
                WHERE transfer_id=?
                """,
                (status, str(detail or "")[-4000:], time.time(), int(transfer_id)),
            )

    def list_transfers(self, limit: int = 20) -> List[StorageTransfer]:
        with self.connect() as db:
            rows = list(
                db.execute(
                    """
                    SELECT transfer_id, transport, source, destination, status, detail, created_at, finished_at
                    FROM storage_transfers
                    ORDER BY transfer_id DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                )
            )
        return [StorageTransfer(*row) for row in rows]
