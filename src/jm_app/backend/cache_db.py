import json
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

from .runtime_paths import sqlite_cache_path


def default_cache_db_path() -> Path:
    return sqlite_cache_path()


class HistoryStore:
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
                CREATE TABLE IF NOT EXISTS history_entries (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_json TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_history_entries_order
                    ON history_entries(sort_order);
                """
            )

    def replace_history(self, records: List[dict], limit: int = 300):
        snapshot = [dict(record) for record in records[-max(1, int(limit)):]]
        now = time.time()
        with self.connect() as db:
            db.execute("DELETE FROM history_entries")
            db.executemany(
                """
                INSERT INTO history_entries(record_json, sort_order, updated_at)
                VALUES(?, ?, ?)
                """,
                [
                    (json.dumps(record, ensure_ascii=False, default=str), index, now)
                    for index, record in enumerate(snapshot)
                ],
            )

    def load_history(self, limit: int = 300) -> List[dict]:
        with self.connect() as db:
            rows = list(
                db.execute(
                    """
                    SELECT record_json
                    FROM history_entries
                    ORDER BY sort_order ASC, entry_id ASC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                )
            )
        records: List[dict] = []
        for row in rows:
            try:
                record = json.loads(row[0] or "{}")
            except Exception:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records


# Kept as an import-compatible alias for third-party integrations.  It no
# longer stores online album or chapter metadata.
ComicCacheDB = HistoryStore
