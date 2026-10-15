from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from .atomic_write import atomic_write_json


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "requirements.txt").exists() and (
            (parent / "src").exists() or (parent / "jm_app").exists()
        ):
            return parent
    return current.parents[3]


def _bundle_dir() -> Path:
    """Root directory holding the frozen application's read-only data (``ui/``,
    ``res/``).

    PyInstaller places collected data files under ``sys._MEIPASS`` -- the
    extraction/contents directory (``dist/comic18/_internal`` for an onedir
    build, or a temp directory for a onefile build).  In a normal source
    checkout that attribute does not exist, so we fall back to
    :func:`app_base_dir`.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return app_base_dir()


def resource_dir() -> Path:
    base = _bundle_dir()
    preferred = base / "res" / "assets"
    return preferred if preferred.exists() else base / "assets"


def ui_dir() -> Path:
    return _bundle_dir() / "ui"


def _user_data_root() -> Path:
    override = os.environ.get("COMIC18_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "comic18"
    roaming_app_data = os.environ.get("APPDATA", "").strip()
    if roaming_app_data:
        return Path(roaming_app_data) / "comic18"
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "comic18"
    return Path.home() / ".local" / "share" / "comic18"


def _migrate_legacy_app_data(destination: Path) -> None:
    source = app_base_dir() / "data"
    if source == destination or not source.is_dir():
        return
    for item in source.iterdir():
        _move_if_missing(item, destination / item.name)


def app_data_dir() -> Path:
    """Persistent user data, outside an install or source checkout."""
    path = _user_data_root()
    path.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_app_data(path)
    return path


def state_dir() -> Path:
    path = app_data_dir() / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_config_path() -> Path:
    return app_data_dir() / "runtime_paths.json"


def settings_path() -> Path:
    return app_data_dir() / "config.json"


def _configured_download_root() -> Path | None:
    try:
        data = json.loads(runtime_config_path().read_text(encoding="utf-8"))
        value = str(data.get("download_root") or "").strip()
        if value:
            return Path(value).expanduser()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def _has_content(path: Path) -> bool:
    try:
        return path.is_dir() and next(path.iterdir(), None) is not None
    except OSError:
        return False


def _legacy_saved_download_root() -> Path | None:
    candidates = []
    for cache_file in (
        app_base_dir() / "cache" / "comic18_qt_cache.json",
        app_base_dir() / "缓存" / "comic18_qt_cache.json",
    ):
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            output_dir = str((data.get("settings") or {}).get("output_dir") or "").strip()
            if output_dir:
                candidates.append((cache_file.stat().st_mtime, Path(output_dir).expanduser()))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _default_download_root() -> Path:
    base = app_base_dir()
    saved_root = _legacy_saved_download_root()
    if saved_root is not None:
        return saved_root
    # Keep existing user downloads in place when upgrading from the old layout.
    for candidate in (
        base / "漫画下载",
        base / "commies",
        app_data_dir() / "downloads",
    ):
        if _has_content(candidate):
            return candidate
    return app_data_dir() / "downloads"


def downloads_dir() -> Path:
    path = _configured_download_root() or _default_download_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_download_root(path: Path | str) -> Path:
    root = Path(path).expanduser()
    if not str(root).strip():
        raise ValueError("下载目录不能为空")
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve(strict=False)
    config_path = runtime_config_path()
    atomic_write_json(config_path, {"download_root": str(resolved)}, indent=2)
    return resolved


def _move_if_missing(source: Path, destination: Path) -> bool:
    if not source.exists() or destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(source), str(destination))
        return True
    except OSError:
        return False


def _migrate_legacy_cache_layout(path: Path) -> None:
    legacy_reader = path / "reader_cache"
    if not legacy_reader.is_dir():
        return
    _move_if_missing(legacy_reader / "online", path / "book")
    _move_if_missing(legacy_reader / "local_zip", path / "local_zip")


def cache_dir() -> Path:
    """Cache lives below the download root, as it does in JMComic-qt."""
    path = downloads_dir() / "cache"
    if not path.exists():
        # The previous releases used a project-level cache directory.  Moving on
        # the same volume is immediate and keeps cached covers/pages intact.
        for legacy in (app_base_dir() / "cache", app_base_dir() / "缓存"):
            if _move_if_missing(legacy, path):
                break
    path.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_cache_layout(path)
    return path


def cover_cache_dir() -> Path:
    path = cache_dir() / "cover"
    path.mkdir(parents=True, exist_ok=True)
    return path


def book_cache_dir(album_id: str, chapter_index: str | int) -> Path:
    album = _safe_path_segment(album_id, "album")
    chapter = _safe_path_segment(chapter_index, "chapter")
    path = reader_cache_dir() / album / chapter
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_path_segment(value: str, fallback: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_." else "_" for char in str(value))
    return cleaned.strip("._") or fallback


def reader_cache_dir() -> Path:
    """Online reader image cache: <download root>/cache/book."""
    path = cache_dir() / "book"
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_zip_cache_dir() -> Path:
    path = cache_dir() / "local_zip"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_dir() -> Path:
    path = app_data_dir() / "session"
    legacy = app_base_dir() / "会话"
    if not path.exists():
        _move_if_missing(legacy, path)
    path.mkdir(parents=True, exist_ok=True)
    _move_if_missing(legacy / "cookies.json", path / "cookies.json")
    return path


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    _move_if_missing(app_base_dir() / "logs", path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ui_cache_path() -> Path:
    return cache_dir() / "comic18_qt_cache.json"


def history_db_path() -> Path:
    """Persistent reading/download history, separate from online list data."""
    path = app_data_dir() / "history.db"
    if not path.exists():
        for legacy in (
            cache_dir() / "comic18.sqlite3",
            app_base_dir() / "cache" / "comic18.sqlite3",
            app_base_dir() / "缓存" / "comic18.sqlite3",
        ):
            if _move_if_missing(legacy, path):
                for suffix in ("-wal", "-shm"):
                    _move_if_missing(legacy.with_name(legacy.name + suffix), path.with_name(path.name + suffix))
                break
    return path


def download_db_path() -> Path:
    """Persistent download and reader-cache state, matching JMComic's download.db."""
    path = app_data_dir() / "download.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def sqlite_cache_path() -> Path:
    """Backward-compatible name for callers that still need the history store."""
    return history_db_path()


def cookie_file_path() -> Path:
    return session_dir() / "cookies.json"
