"""Account/profile page request scheduling and navigation actions."""

from __future__ import annotations

from typing import Dict, TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QPushButton

from ...backend.jm_endpoints import profile_web_url
from ...tasks import LoginVerifyWorker, ProfileFetchWorker

if TYPE_CHECKING:
    from ..ui import MainWindow


class ProfilePageMixin:
    """Interactive account-page behavior kept separate from widget assembly."""

    def bind_profile_page_actions(self, page):
        actions = {
            "profileFavoriteMoreButton": self.open_profile_favorites,
            "profileHistoryMoreButton": self.open_profile_history,
            "profileLogoutButton": self.logout,
            "profileWebButton": self.open_profile_web_page,
            "profileInboxWebButton": self.open_profile_web_page,
        }
        for object_name, callback in actions.items():
            button = page.findChild(QPushButton, object_name)
            if button is not None:
                button.clicked.connect(callback)

    def open_profile_page(self):
        if hasattr(self, "main_content_stack"):
            self.switch_page(self.profile_page_index())
            self.show_profile_section(0)
            self.update_profile_page()
        if self.session_username and self.session_password:
            self.refresh_user_profile()

    def show_profile_section(self, section: int = 0):
        stack = getattr(self, "profile_content_stack", None)
        buttons = getattr(self, "profile_nav_buttons", [])
        if stack is None:
            return
        section = max(0, min(int(section), stack.count() - 1))
        stack.setCurrentIndex(section)
        if section < len(buttons) and buttons[section] is not None:
            buttons[section].setChecked(True)
        render_preview = getattr(self, "render_profile_section_preview", None)
        if render_preview is not None:
            render_preview(section)

    def open_profile_web_page(self):
        username = self._profile_text(self.profile_data.get("username") or self.session_username, "")
        QDesktopServices.openUrl(QUrl(profile_web_url(username)))

    def open_profile_favorites(self):
        self.show_profile_section(2)

    def open_profile_history(self):
        self.show_profile_section(3)

    def refresh_user_profile(self):
        if not self.session_username or not self.session_password:
            self.update_profile_page()
            self.show_toast("请先登录账号")
            return
        if self.profile_worker and self.profile_worker.isRunning():
            return
        if self.profile_status_label:
            self.profile_status_label.setText("\u6b63\u5728\u901a\u8fc7 App API \u83b7\u53d6\u8d26\u6237\u4fe1\u606f...")
        self.profile_worker = ProfileFetchWorker(self._profile_settings(), self)
        self.profile_worker.loaded.connect(self.on_profile_loaded)
        self.profile_worker.failed.connect(self.on_profile_failed)
        self.profile_worker.finished.connect(
            lambda worker=self.profile_worker: self.cleanup_profile_worker(worker)
        )
        self.profile_worker.start()

    def on_profile_loaded(self, result: Dict):
        self.profile_data = dict(result or {})
        self.profile_avatar_pixmap = None
        if hasattr(self, "avatar_button"):
            self.reset_navigation_avatar()
        user = self.profile_data.get("user") or {}
        self.session_uid = str(self.profile_data.get("uid") or user.get("uid") or self.session_uid or "")
        for message in self.profile_data.get("logs") or []:
            self.log(message)
        self.update_profile_page()
        self.update_navigation_profile_card()
        self.sync_comment_profile_header()
        self.start_avatar_fetch()

    def apply_navigation_avatar_pixmap(self, pixmap: QPixmap) -> None:
        button = getattr(self, "avatar_button", None)
        if button is None or pixmap.isNull():
            return
        diameter = max(24, min(button.width(), button.height()) - 2)
        scaled = pixmap.scaled(
            diameter,
            diameter,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = max(0, (scaled.width() - diameter) // 2)
        top = max(0, (scaled.height() - diameter) // 2)
        cropped = scaled.copy(left, top, diameter, diameter)
        rounded = QPixmap(diameter, diameter)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        clip = QPainterPath()
        clip.addEllipse(0, 0, diameter, diameter)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        button.setProperty("hasAvatar", True)
        button.setIcon(QIcon(rounded))
        button.setIconSize(QSize(diameter, diameter))
        button.setText("")
        button.style().unpolish(button)
        button.style().polish(button)

    def reset_navigation_avatar(self, initial: str = "U") -> None:
        button = getattr(self, "avatar_button", None)
        if button is None:
            return
        button.setProperty("hasAvatar", False)
        button.setIcon(QIcon())
        button.setText((str(initial or "U")[:1] or "U").upper())
        button.style().unpolish(button)
        button.style().polish(button)

    def on_profile_failed(self, message: str):
        if self.profile_status_label:
            self.profile_status_label.setText(f"\u8d26\u6237\u4fe1\u606f\u83b7\u53d6\u5931\u8d25\uff1a{message}")
        self.show_toast(message or "\u8d26\u6237\u4fe1\u606f\u83b7\u53d6\u5931\u8d25", 2200)

    def cleanup_profile_worker(self, worker: ProfileFetchWorker):
        if worker is self.profile_worker:
            self.profile_worker = None
        worker.deleteLater()

    def update_header_profile(self):
        username = self._profile_text(self.profile_data.get("username") or self.session_username, "\u6e38\u5ba2")
        if hasattr(self, "user_label"):
            metrics = self.user_label.fontMetrics()
            label_width = min(100, max(20, metrics.horizontalAdvance(username) + 2))
            self.user_label.setText(metrics.elidedText(username, Qt.ElideRight, label_width))
            self.user_label.setToolTip(username)
        if hasattr(self, "user_role_label"):
            user = self.profile_data.get("user") or {}
            role = self._profile_text(
                self.profile_data.get("level_name")
                or user.get("level_name")
                or user.get("title"),
                "普通用户" if self.session_username else "游客账户",
            )
            role_metrics = self.user_role_label.fontMetrics()
            self.user_role_label.setText(
                role_metrics.elidedText(role, Qt.ElideRight, 100)
            )
            self.user_role_label.setToolTip(role)
        if hasattr(self, "avatar_button"):
            if self.profile_avatar_pixmap is not None or not self.avatar_button.icon().isNull():
                self.avatar_button.setText("")
            else:
                initial = username[0].upper() if username and username != "\u6e38\u5ba2" else "U"
                self.reset_navigation_avatar(initial)
            self.avatar_button.setToolTip("账户菜单")
        self.update_navigation_profile_card()

    def update_navigation_profile_card(self):
        username = self._profile_text(self.profile_data.get("username") or self.session_username, "游客模式")
        user = self.profile_data.get("user") or {}
        favorites = self._profile_text(user.get("album_favorites") or user.get("favorites"), "0")
        favorites_max = self._profile_text(user.get("album_favorites_max") or user.get("canFavorites"), "-")
        coin = self._profile_text(user.get("coin"), "-")
        level = self._profile_text(user.get("level"), "-")
        level_name = self._profile_text(self.profile_data.get("level_name") or user.get("level_name") or user.get("title"), "登录后显示账户信息")
        signed = self._daily_signed_text(self.profile_data.get("daily") or self.profile_data.get("sign"))
        if hasattr(self, "nav_profile_name_label"):
            self.nav_profile_name_label.setText(username)
        if hasattr(self, "nav_profile_title_label"):
            self.nav_profile_title_label.setText(level_name)
        if hasattr(self, "nav_coin_value_label"):
            self.nav_coin_value_label.setText(coin)
        if hasattr(self, "nav_level_value_label"):
            self.nav_level_value_label.setText(f"LV{level}" if level != "-" else "LV -")
        if hasattr(self, "nav_favorite_value_label"):
            self.nav_favorite_value_label.setText(f"{favorites}/{favorites_max}")
        if hasattr(self, "nav_profile_avatar_label"):
            if self.profile_avatar_pixmap is not None:
                self.set_cover_on_label(self.nav_profile_avatar_label, self.profile_avatar_pixmap)
            else:
                self.nav_profile_avatar_label.setText((username[:1] or "U").upper())

    def open_login_or_profile(self):
        if self.session_username and self.session_password:
            self.open_profile_page()
            return
        self.stack.setCurrentWidget(self.login_page)
        self.login_user_edit.setFocus(Qt.OtherFocusReason)

    def set_api_route(self, route: int):
        self.api_route = max(0, int(route))
        self.settings_cache = self.current_settings_snapshot()
        self.settings_cache["api_route"] = self.api_route
        self.save_local_cache()
        self.show_toast(f"已切换至分流 {self.api_route + 1}，下次请求生效")

    def sign_in_from_navigation(self):
        if not self.session_username or not self.session_password:
            self.show_toast("请先登录账号")
            return
        if self._daily_signed_text(self.profile_data.get("daily") or self.profile_data.get("sign")) == "已签到":
            self.show_toast("今日已打卡")
            return
        if self.daily_sign_worker and self.daily_sign_worker.isRunning():
            return
        settings = self._profile_settings()
        settings.auto_sign = True
        worker = LoginVerifyWorker(settings, self)
        self.daily_sign_worker = worker
        worker.verified.connect(self.on_navigation_sign_verified)
        worker.failed.connect(lambda message: self.show_toast(message or "打卡失败", 2400))
        worker.finished.connect(
            lambda worker=worker: self.cleanup_daily_sign_worker(worker)
        )
        self.show_toast("正在打卡...", 900)
        worker.start()

    def on_navigation_sign_verified(self, result: Dict):
        if not isinstance(result, dict):
            return
        self.profile_data.update(result)
        sign = result.get("sign") or {}
        if isinstance(sign, dict):
            self.profile_data["daily"] = sign
        user = self.profile_data.get("user") or {}
        self.session_uid = str(result.get("uid") or user.get("uid") or self.session_uid)
        self.update_profile_page()
        self.update_navigation_profile_card()
        self.show_toast("今日已打卡" if sign.get("already_signed") else "打卡成功")
        self.refresh_user_profile()

    def cleanup_daily_sign_worker(self, worker: LoginVerifyWorker):
        if worker is self.daily_sign_worker:
            self.daily_sign_worker = None
        worker.deleteLater()
