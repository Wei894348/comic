from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImageReader

from ..backend.models import AlbumMeta
from ..backend.pdf_utils import IMAGE_SUFFIXES


class CacheRestoreWorker(QThread):
    loaded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, cache_key: str, albums: List[AlbumMeta], parent=None):
        super().__init__(parent)
        self.cache_key = cache_key
        self.albums = [copy.deepcopy(album) for album in albums]

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            self.loaded.emit(self.cache_key, self.albums)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            self.failed.emit(self.cache_key, str(exc))


class CacheMaintenanceWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, action: str, payload: Dict, parent=None):
        super().__init__(parent)
        self.action = action
        self.payload = dict(payload)

    def run(self):
        try:
            result = self.perform()
            if not self.isInterruptionRequested():
                self.completed.emit(self.action, result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(self.action, str(exc))

    def perform(self) -> Dict:
        if self.action == "clear_all":
            return self.clear_all_runtime_cache()
        if self.action == "clean_broken":
            return self.clean_broken_cache()
        if self.action == "export":
            return self.export_cache_bundle()
        if self.action == "import":
            return self.import_cache_bundle()
        raise ValueError(f"未知缓存维护操作：{self.action}")

    @staticmethod
    def safe_cache_delete(path: Path, allowed_root: Path) -> bool:
        if not path.exists():
            return False
        resolved_path = path.expanduser().resolve(strict=False)
        resolved_root = allowed_root.expanduser().resolve(strict=False)
        if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
            raise RuntimeError(f"拒绝删除不在缓存根目录内的路径：{resolved_path}")
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        return True

    def clear_all_runtime_cache(self) -> Dict:
        removed_paths = []
        cache_root = Path(self.payload["cache_root"])
        for key in ("reader_cache", "cover_cache", "local_zip_cache", "page_cache"):
            path = Path(self.payload[key])
            if self.safe_cache_delete(path, cache_root):
                removed_paths.append(str(path))
        return {"removed_paths": removed_paths}

    def clean_broken_cache(self) -> Dict:
        removed_files = 0
        removed_dirs = 0
        skipped = []
        for root_value in self.payload.get("roots", []):
            root = Path(root_value)
            if not root.exists():
                continue
            for path in sorted(root.rglob("*"), reverse=True):
                if self.isInterruptionRequested():
                    break
                try:
                    if path.is_file():
                        broken = path.stat().st_size == 0
                        if path.suffix.lower() in IMAGE_SUFFIXES and not broken:
                            reader = QImageReader(str(path))
                            broken = not reader.canRead()
                        if broken:
                            path.unlink(missing_ok=True)
                            removed_files += 1
                    elif path.is_dir() and not any(path.iterdir()):
                        path.rmdir()
                        removed_dirs += 1
                except Exception as exc:
                    skipped.append(f"{path}: {exc}")
        return {"removed_files": removed_files, "removed_dirs": removed_dirs, "skipped": skipped[:50]}

    def export_cache_bundle(self) -> Dict:
        target = Path(self.payload["target"]).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        exported = []
        for db_value in self.payload.get("db_paths", []):
            db_path = Path(db_value)
            if db_path.exists():
                shutil.copy2(db_path, target / db_path.name)
                exported.append(db_path.name)
        reader_cache = Path(self.payload["reader_cache"])
        if reader_cache.exists():
            shutil.copytree(reader_cache, target / "reader_cache", dirs_exist_ok=True)
            exported.append("阅读图片缓存")
        disk_cover_cache = Path(self.payload["cover_cache"])
        if disk_cover_cache.exists():
            shutil.copytree(disk_cover_cache, target / "cover_cache", dirs_exist_ok=True)
            exported.append("封面缓存")
        return {"target": str(target), "exported": exported}

    def import_cache_bundle(self) -> Dict:
        source = Path(self.payload["source"]).expanduser()
        imported = []
        for db_value in self.payload.get("db_paths", []):
            db_target = Path(db_value)
            db_source = source / db_target.name
            if db_source.exists():
                db_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(db_source, db_target)
                imported.append(db_target.name)
        reader_source = source / "reader_cache"
        if reader_source.exists():
            shutil.copytree(reader_source, Path(self.payload["reader_cache"]), dirs_exist_ok=True)
            imported.append("阅读图片缓存")
        cover_source = source / "cover_cache"
        if cover_source.exists():
            shutil.copytree(cover_source, Path(self.payload["cover_cache"]), dirs_exist_ok=True)
            imported.append("封面缓存")
        return {"source": str(source), "imported": imported}
