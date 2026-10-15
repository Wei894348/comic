"""Main-window state persistence isolated from page construction."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Dict, List

from PySide6.QtCore import QTimer

from ..backend.atomic_write import atomic_write_json
from ..backend.cache_db import HistoryStore
from ..backend.jm_endpoints import API_DOMAINS, IMAGE_DOMAINS
from ..backend.utils import dedupe_domains

if TYPE_CHECKING:
    from .ui import MainWindow


class StatePersistenceMixin:
    def load_local_cache(self: "MainWindow") -> None:
        data = {}
        self.result_cache = {}
        self.detail_cache = {}
        try:
            if self.cache_file.exists():
                cached_data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if isinstance(cached_data, dict):
                    data = cached_data
                else:
                    self._log_local_state_warning("缓存文件不是 JSON 对象，已忽略")
        except (OSError, json.JSONDecodeError) as exc:
            self._log_local_state_warning(f"读取缓存文件失败，已忽略：{exc}")

        # Online list/detail metadata is session-only. Ignore stale legacy
        # payloads rather than repopulating cards from a previous session.
        try:
            json_history = self.normalize_history_records(data.get("history") or [])
        except Exception as exc:
            self._log_local_state_warning(f"缓存历史记录无效，已忽略：{exc}")
            json_history = []

        self.settings_cache = (
            dict(data.get("settings"))
            if isinstance(data.get("settings"), dict)
            else {}
        )
        try:
            if self.settings_file.exists():
                saved_settings = json.loads(
                    self.settings_file.read_text(encoding="utf-8")
                )
                if isinstance(saved_settings, dict):
                    self.settings_cache = saved_settings
                else:
                    self._log_local_state_warning("设置文件不是 JSON 对象，已忽略")
        except (OSError, json.JSONDecodeError) as exc:
            self._log_local_state_warning(f"读取设置文件失败，已忽略：{exc}")

        try:
            settings_version = int(
                self.settings_cache.get("settings_version", 0) or 0
            )
        except (TypeError, ValueError):
            settings_version = 0
        if settings_version < 3:
            self.settings_cache["detail_check"] = False

        # Stale routes must not outrank the current official domain pool.
        raw_api_domains = data.get("api_domains")
        raw_cover_domains = data.get("cover_domains")
        saved_api_domains = [
            domain
            for domain in (
                raw_api_domains if isinstance(raw_api_domains, (list, tuple)) else []
            )
            if domain in API_DOMAINS
        ]
        saved_cover_domains = [
            domain
            for domain in (
                raw_cover_domains if isinstance(raw_cover_domains, (list, tuple)) else []
            )
            if domain in IMAGE_DOMAINS
        ]
        self.api_domain_pool = dedupe_domains(saved_api_domains + self.api_domain_pool)
        self.cover_domain_pool = dedupe_domains(
            saved_cover_domains + self.cover_domain_pool
        )
        self.cover_domain_failures = {}
        raw_failures = data.get("cover_domain_failures")
        if isinstance(raw_failures, dict):
            for key, value in raw_failures.items():
                domain = str(key).strip()
                if not domain:
                    continue
                try:
                    self.cover_domain_failures[domain] = int(value)
                except (TypeError, ValueError):
                    self._log_local_state_warning(
                        f"封面域名失败次数无效，已忽略：{domain}"
                    )
        try:
            sqlite_history = self.normalize_history_records(
                self.history_store.load_history()
            )
            self.download_history = sqlite_history or json_history
            if json_history and not sqlite_history:
                self.history_store.replace_history(json_history)
        except Exception:
            self.download_history = json_history

    def _log_local_state_warning(self: "MainWindow", message: str) -> None:
        log = getattr(self, "log", None)
        if callable(log):
            log(message)

    def save_local_cache(self: "MainWindow") -> None:
        try:
            history_snapshot = copy.deepcopy(self.download_history[-300:])
            payload = {
                "api_domains": self.api_domain_pool,
                "cover_domains": self.cover_domain_pool,
                "cover_domain_failures": self.cover_domain_failures,
            }
            settings = self.current_settings_snapshot()
            self.settings_cache = settings
            atomic_write_json(self.cache_file, payload)
            atomic_write_json(self.settings_file, settings, indent=2)
            if not self._db_pool_closed:
                self.db_write_pool.submit(
                    self._save_history_snapshot, history_snapshot
                )
        except Exception as exc:
            self.log(f"缓存保存失败：{exc}") if hasattr(self, "log_box") else None

    def schedule_local_cache_save(
        self: "MainWindow", delay_ms: int = 450
    ) -> None:
        if self._local_cache_save_timer is None:
            self._local_cache_save_timer = QTimer(self)
            self._local_cache_save_timer.setSingleShot(True)
            self._local_cache_save_timer.timeout.connect(self.save_local_cache)
        self._local_cache_save_timer.start(delay_ms)

    def _save_history_snapshot(
        self: "MainWindow", history_snapshot: List[Dict[str, object]]
    ) -> None:
        try:
            HistoryStore().replace_history(history_snapshot)
        except Exception as exc:
            self.async_log.emit(f"SQLite 历史写入失败：{exc}")

    def shutdown_db_writer(self: "MainWindow") -> None:
        if self._db_pool_closed:
            return
        self._db_pool_closed = True
        # Waiting in the GUI thread can keep the process alive behind a locked DB.
        self.db_write_pool.shutdown(wait=self._test_mode, cancel_futures=True)

    def shutdown_cover_cache_writer(self: "MainWindow") -> None:
        if self._cover_disk_pool_closed:
            return
        self._cover_disk_pool_closed = True
        self.cover_disk_write_pool.shutdown(
            wait=self._test_mode, cancel_futures=True
        )
