from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from ..backend.runtime_paths import cover_cache_dir


class CoverCacheRepository:
    _extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    _priority = {".webp": 0, ".png": 1, ".jpg": 2, ".jpeg": 3, ".gif": 4}

    def paths(self, book_id: str) -> list[Path]:
        safe_id = self._safe_id(book_id)
        return sorted(
            (path for path in cover_cache_dir().glob(f"{safe_id}.*") if path.suffix.lower() in self._extensions),
            key=lambda path: self._priority.get(path.suffix.lower(), 9),
        )

    def read(self, book_id: str) -> Optional[bytes]:
        for path in self.paths(book_id):
            try:
                data = path.read_bytes()
                if data:
                    return data
            except OSError:
                continue
        return None

    def write(self, book_id: str, data: bytes) -> Path:
        path = cover_cache_dir() / f"{self._safe_id(book_id)}{self.detect_suffix(data)}"
        path.write_bytes(data)
        for previous in self.paths(book_id):
            if previous != path:
                previous.unlink(missing_ok=True)
        return path

    @staticmethod
    def detect_suffix(data: bytes) -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return ".webp"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        return ".jpg"

    @staticmethod
    def _safe_id(book_id: str) -> str:
        return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(book_id or "unknown")).strip("._") or "unknown"
