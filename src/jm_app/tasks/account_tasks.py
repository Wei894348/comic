"""Qt tasks for account, profile, favorite, history, and comment requests."""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QThread, Signal

from ..backend.jm_api import get_latest_api_domains
from ..backend.schemas import NetworkSettings
from ..backend.services import (
    create_favorite_folder,
    delete_favorite_folder,
    get_all_favorite_albums,
    get_comments,
    get_favorite_library,
    get_latest_albums,
    get_personal_comment_summary,
    get_remote_history,
    get_user_profile,
    get_week_albums,
    get_week_categories,
    move_favorite,
    post_comment,
    refresh_local_favorite_albums,
    update_favorite,
    verify_login,
)


class DomainRefreshWorker(QThread):
    domains_ready = Signal(object)
    log = Signal(str)

    def run(self) -> None:
        try:
            domains = get_latest_api_domains(self.log.emit, force=True)
            self.domains_ready.emit(domains)
        except Exception as exc:
            self.log.emit(f"域名池更新失败：{exc}")


class LoginVerifyWorker(QThread):
    verified = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: NetworkSettings, parent=None):
        super().__init__(parent)
        self.settings = settings

    def run(self) -> None:
        try:
            self.verified.emit(verify_login(self.settings))
        except Exception as exc:
            self.failed.emit(str(exc))


class ProfileFetchWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: NetworkSettings, parent=None):
        super().__init__(parent)
        self.settings = settings

    def run(self) -> None:
        try:
            self.loaded.emit(get_user_profile(self.settings))
        except Exception as exc:
            self.failed.emit(str(exc))


class LibraryWorker(QThread):
    """Run account library actions without blocking the Qt event loop."""

    loaded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        action: str,
        settings: NetworkSettings,
        payload: Optional[Dict] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.action = action
        self.settings = settings
        self.payload = dict(payload or {})

    def run(self) -> None:
        try:
            result = self._execute_action()
            if isinstance(result, dict):
                result = dict(result)
                if "request_serial" in self.payload:
                    result["request_serial"] = self.payload["request_serial"]
                if "comment_filter" in self.payload:
                    result["comment_filter"] = self.payload["comment_filter"]
            self.loaded.emit(self.action, result)
        except Exception as exc:
            self.failed.emit(self.action, str(exc))

    def _execute_action(self):
        if self.action == "favorites":
            return get_favorite_library(
                self.settings,
                folder_id=str(self.payload.get("folder_id") or "0"),
                sort=str(self.payload.get("sort") or "mr"),
                page=int(self.payload.get("page") or 1),
            )
        if self.action == "local_favorite_import":
            return get_all_favorite_albums(self.settings)
        if self.action == "local_favorite_update":
            return refresh_local_favorite_albums(
                self.settings,
                [str(value) for value in (self.payload.get("album_ids") or [])],
            )
        if self.action == "remote_history":
            return get_remote_history(
                self.settings, page=int(self.payload.get("page") or 1)
            )
        if self.action == "comments":
            return get_comments(
                self.settings,
                album_id=str(self.payload.get("album_id") or ""),
                page=int(self.payload.get("page") or 1),
                mine=bool(self.payload.get("mine")),
                user_id=str(self.payload.get("user_id") or ""),
            )
        if self.action == "comment_stats":
            return get_personal_comment_summary(
                self.settings,
                user_id=str(self.payload.get("user_id") or ""),
            )
        if self.action == "toggle_favorite":
            return update_favorite(
                self.settings,
                str(self.payload.get("album_id") or ""),
                folder_id=str(self.payload.get("folder_id") or ""),
            )
        if self.action == "detail_toggle_favorite":
            return update_favorite(
                self.settings, str(self.payload.get("album_id") or "")
            )
        if self.action == "detail_favorite_folders":
            return get_favorite_library(self.settings, page=1)
        if self.action in {"detail_add_favorite_folder", "add_folder"}:
            return create_favorite_folder(
                self.settings, str(self.payload.get("name") or "")
            )
        if self.action == "detail_move_favorite":
            return move_favorite(
                self.settings,
                str(self.payload.get("album_id") or ""),
                str(self.payload.get("folder_id") or "0"),
            )
        if self.action == "delete_folder":
            return delete_favorite_folder(
                self.settings, str(self.payload.get("folder_id") or "")
            )
        if self.action == "move_favorite":
            return move_favorite(
                self.settings,
                str(self.payload.get("album_id") or ""),
                str(self.payload.get("folder_id") or "0"),
            )
        if self.action == "post_comment":
            return post_comment(
                self.settings,
                str(self.payload.get("album_id") or ""),
                str(self.payload.get("comment") or ""),
                str(self.payload.get("comment_id") or ""),
            )
        if self.action == "week_categories":
            return get_week_categories(self.settings)
        if self.action == "latest":
            return get_latest_albums(
                self.settings,
                page=int(self.payload.get("page") or 0),
            )
        if self.action == "week_albums":
            return get_week_albums(
                self.settings,
                str(self.payload.get("category_id") or ""),
                str(self.payload.get("category_type") or "manga"),
            )
        raise ValueError(f"未知收藏与记录操作：{self.action}")
