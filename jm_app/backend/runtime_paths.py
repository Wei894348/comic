from __future__ import annotations

import sys
from pathlib import Path


APP_DATA_FOLDER = "JM下载器数据"


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    path = app_base_dir() / APP_DATA_FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def downloads_dir() -> Path:
    path = app_data_dir() / "漫画下载"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = app_data_dir() / "缓存"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_dir() -> Path:
    path = app_data_dir() / "会话"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ui_cache_path() -> Path:
    return cache_dir() / "comic18_qt_cache.json"


def sqlite_cache_path() -> Path:
    return cache_dir() / "comic18.sqlite3"


def reader_cache_dir() -> Path:
    path = cache_dir() / "reader_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cookie_file_path() -> Path:
    return session_dir() / "cookies.json"
