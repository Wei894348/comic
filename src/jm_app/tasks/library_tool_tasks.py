"""Qt task wrapper for offline library tools."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from PySide6.QtCore import QThread, Signal

from ..backend.library_tools import (
    copy_to_storage,
    query_doh,
    run_external_super_resolution,
    upscale_images,
    upload_webdav,
)


class LibraryToolWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, action: str, payload: Dict, parent=None):
        super().__init__(parent)
        self.action = action
        self.payload = dict(payload)

    def run(self) -> None:
        try:
            self.completed.emit(self.action, self._execute_action())
        except Exception as exc:
            self.failed.emit(self.action, str(exc))

    def _execute_action(self):
        if self.action == "doh":
            return query_doh(
                self.payload.get("domain", ""), self.payload.get("endpoint", "")
            )
        if self.action == "upscale":
            return upscale_images(
                [Path(value) for value in self.payload.get("paths", [])],
                Path(self.payload["output_dir"]),
                int(self.payload.get("scale", 2)),
            )
        if self.action == "external_sr":
            return run_external_super_resolution(
                [Path(value) for value in self.payload.get("paths", [])],
                Path(self.payload["output_dir"]),
                self.payload.get("command", ""),
            )
        if self.action == "copy_storage":
            return copy_to_storage(
                Path(self.payload["source"]), Path(self.payload["destination"])
            )
        if self.action == "webdav":
            return upload_webdav(
                Path(self.payload["source"]),
                self.payload.get("base_url", ""),
                self.payload.get("remote_path", ""),
                self.payload.get("username", ""),
                self.payload.get("password", ""),
            )
        raise ValueError(f"未知工具操作：{self.action}")
