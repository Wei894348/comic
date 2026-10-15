"""JMComic-qt-style network, DNS, routing and speed-test settings."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Dict

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...backend.constants import DEFAULT_USER_AGENT
from ...backend.cookie_store import (
    clear_cookie_store,
    load_cookie_header,
    save_cookie_dict,
)
from ...backend.credential_store import (
    delete_secret,
    get_secret,
    migrate_legacy_base64_secret,
    set_secret,
)
from ...backend.jm_endpoints import API_DOMAINS, IMAGE_DOMAINS
from ...backend.network_session import DOH_URL, create_network_session
from ...backend.utils import dedupe_domains, parse_cookie_header

if TYPE_CHECKING:
    from ..ui import MainWindow


class RouteSpeedWorker(QThread):
    measured = Signal(str, str, str)
    completed = Signal()

    def __init__(self, routes, proxy: str, doh_enabled: bool, doh_url: str, parent=None):
        super().__init__(parent)
        self.routes = list(routes)
        self.proxy = proxy
        self.doh_enabled = doh_enabled
        self.doh_url = doh_url
        self._session = None

    def cancel(self) -> None:
        self.requestInterruption()
        session = self._session
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def run(self) -> None:
        try:
            with create_network_session(
                proxy=self.proxy,
                doh_enabled=self.doh_enabled,
                doh_url=self.doh_url,
            ) as session:
                self._session = session
                for route_type, domain in self.routes:
                    if self.isInterruptionRequested():
                        break
                    started = time.perf_counter()
                    try:
                        response = session.get(
                            f"https://{domain}/",
                            timeout=(3, 5),
                            allow_redirects=False,
                            stream=True,
                        )
                        elapsed = round((time.perf_counter() - started) * 1000)
                        status = f"{elapsed} ms · HTTP {response.status_code}"
                        response.close()
                    except Exception as exc:
                        status = f"不可用 · {str(exc)[:46]}"
                    if not self.isInterruptionRequested():
                        self.measured.emit(route_type, domain, status)
        finally:
            self._session = None
            self.completed.emit()


class SettingsPageMixin:
    def setup_network_settings_panel(self: "MainWindow", panel: QFrame) -> None:
        form = panel.findChild(QFormLayout, "settingsForm")
        if form is None:
            raise RuntimeError("Settings form is missing settingsForm")
        group = QGroupBox("网络、DNS 与分流", panel)
        group.setObjectName("networkRouteGroup")
        root = QVBoxLayout(group)
        root.setContentsMargins(16, 18, 16, 16)
        root.setSpacing(12)

        network_form = QFormLayout()
        network_form.setHorizontalSpacing(18)
        network_form.setVerticalSpacing(10)
        network_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.proxy_mode_combo = QComboBox(group)
        for text, value in (
            ("不使用代理", "none"),
            ("HTTP 代理", "http"),
            ("SOCKS5 代理", "socks5"),
            ("使用系统代理", "system"),
        ):
            self.proxy_mode_combo.addItem(text, value)
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:7890")
        self.socks_proxy_edit = QLineEdit(group)
        self.socks_proxy_edit.setPlaceholderText("socks5://127.0.0.1:1080")
        network_form.addRow("代理方式", self.proxy_mode_combo)
        network_form.addRow("HTTP 代理", self.proxy_edit)
        network_form.addRow("SOCKS5 代理", self.socks_proxy_edit)

        doh_row = QHBoxLayout()
        self.doh_enabled_box = QCheckBox("启用 DoH", group)
        self.doh_enabled_box.setChecked(True)
        self.doh_url_edit = QLineEdit(group)
        self.doh_url_edit.setPlaceholderText(DOH_URL)
        self.doh_url_edit.setText(DOH_URL)
        doh_row.addWidget(self.doh_enabled_box)
        doh_row.addWidget(self.doh_url_edit, 1)
        network_form.addRow("DNS", doh_row)

        self.api_route_combo = QComboBox(group)
        self.image_route_combo = QComboBox(group)
        self.api_route_combo.addItem("自动选择可用线路", 0)
        self.image_route_combo.addItem("自动选择可用线路", 0)
        for index, domain in enumerate(API_DOMAINS, start=1):
            self.api_route_combo.addItem(f"分流 {index} · {domain}", index)
        for index, domain in enumerate(IMAGE_DOMAINS, start=1):
            self.image_route_combo.addItem(f"分流 {index} · {domain}", index)
        network_form.addRow("API 分流", self.api_route_combo)
        network_form.addRow("图片分流", self.image_route_combo)

        self.custom_api_domain_edit = QLineEdit(group)
        self.custom_api_domain_edit.setPlaceholderText("可选：自定义 API 域名")
        self.custom_image_domain_edit = QLineEdit(group)
        self.custom_image_domain_edit.setPlaceholderText("可选：自定义图片域名")
        network_form.addRow("自定义 API", self.custom_api_domain_edit)
        network_form.addRow("自定义图片", self.custom_image_domain_edit)
        root.addLayout(network_form)

        commands = QHBoxLayout()
        self.route_speed_button = QPushButton("开始测速", group)
        self.route_speed_button.setObjectName("primaryButton")
        self.route_speed_status = QLabel("选择分流后会用于后续新请求", group)
        self.route_speed_status.setObjectName("routeSpeedStatus")
        commands.addWidget(self.route_speed_button)
        commands.addWidget(self.route_speed_status)
        commands.addStretch(1)
        root.addLayout(commands)

        self.route_speed_table = QTableWidget(0, 3, group)
        self.route_speed_table.setHorizontalHeaderLabels(("类型", "线路", "测速结果"))
        self.route_speed_table.horizontalHeader().setStretchLastSection(True)
        self.route_speed_table.verticalHeader().hide()
        self.route_speed_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.route_speed_table.setSelectionMode(QTableWidget.NoSelection)
        self.route_speed_table.setMinimumHeight(190)
        root.addWidget(self.route_speed_table)
        form.insertRow(0, group)

        legacy_proxy_label = panel.findChild(QLabel, "proxyLabel")
        if legacy_proxy_label is not None:
            legacy_proxy_label.hide()
        self.route_speed_button.clicked.connect(self.start_route_speed_test)
        self.proxy_mode_combo.currentIndexChanged.connect(self.update_proxy_field_state)
        self.update_proxy_field_state()

        panel.setObjectName("settingsWorkspace")
        panel.setStyleSheet(
            "QFrame#settingsWorkspace{background:#f7f8fa;border:0;}"
            "QGroupBox#networkRouteGroup{background:#fff;border:1px solid #dfe5ec;"
            "border-radius:7px;margin-top:12px;font-weight:800;}"
            "QGroupBox#networkRouteGroup::title{subcontrol-origin:margin;left:12px;padding:0 5px;}"
            "QLabel#routeSpeedStatus{color:#667085;}"
            "QTableWidget{background:#fff;border:1px solid #e0e5eb;border-radius:6px;gridline-color:#edf0f3;}"
        )

    def effective_proxy(self: "MainWindow") -> str:
        mode = self.proxy_mode_combo.currentData() if hasattr(self, "proxy_mode_combo") else "http"
        if mode == "system":
            return "system://"
        if mode == "http":
            return self.proxy_edit.text().strip()
        if mode == "socks5":
            return self.socks_proxy_edit.text().strip()
        return ""

    def update_proxy_field_state(self: "MainWindow", *_args) -> None:
        mode = self.proxy_mode_combo.currentData()
        self.proxy_edit.setEnabled(mode == "http")
        self.socks_proxy_edit.setEnabled(mode == "socks5")

    def apply_network_route_selection(self: "MainWindow") -> None:
        self.api_route = int(self.api_route_combo.currentData() or 0)
        image_route = int(self.image_route_combo.currentData() or 0)
        api_domains = list(API_DOMAINS)
        custom_api = self.custom_api_domain_edit.text().strip()
        custom_api = custom_api.replace("https://", "").replace("http://", "").strip("/")
        if custom_api and self.api_route == 0:
            api_domains.insert(0, custom_api)
        if api_domains and self.api_route:
            api_offset = (self.api_route - 1) % len(api_domains)
            api_domains = api_domains[api_offset:] + api_domains[:api_offset]
        self.api_domain_pool = dedupe_domains(api_domains)
        domains = list(IMAGE_DOMAINS)
        custom = self.custom_image_domain_edit.text().strip()
        custom = custom.replace("https://", "").replace("http://", "").strip("/")
        if custom and image_route == 0:
            domains.insert(0, custom)
        if domains and image_route:
            offset = (image_route - 1) % len(domains)
            domains = domains[offset:] + domains[:offset]
        self.cover_domain_pool = dedupe_domains(domains)

    def start_route_speed_test(self: "MainWindow") -> None:
        worker = getattr(self, "route_speed_worker", None)
        if worker is not None and worker.isRunning():
            return
        api_domains = list(API_DOMAINS)
        image_domains = list(IMAGE_DOMAINS)
        custom_api = self.custom_api_domain_edit.text().strip()
        custom_image = self.custom_image_domain_edit.text().strip()
        for value, target in ((custom_api, api_domains), (custom_image, image_domains)):
            domain = value.replace("https://", "").replace("http://", "").strip("/")
            if domain and domain not in target:
                target.insert(0, domain)
        routes = [("API", domain) for domain in api_domains]
        routes += [("图片", domain) for domain in image_domains]
        self.route_speed_table.setRowCount(0)
        self.route_speed_button.setEnabled(False)
        self.route_speed_status.setText("正在测试各条线路...")
        worker = RouteSpeedWorker(
            routes,
            self.effective_proxy(),
            self.doh_enabled_box.isChecked(),
            self.doh_url_edit.text().strip() or DOH_URL,
            self,
        )
        self.route_speed_worker = worker
        worker.measured.connect(self.append_route_speed_result)
        worker.completed.connect(self.finish_route_speed_test)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def append_route_speed_result(
        self: "MainWindow", route_type: str, domain: str, result: str
    ) -> None:
        row = self.route_speed_table.rowCount()
        self.route_speed_table.insertRow(row)
        for column, text in enumerate((route_type, domain, result)):
            item = QTableWidgetItem(text)
            if column == 2:
                item.setTextAlignment(Qt.AlignCenter)
            self.route_speed_table.setItem(row, column, item)

    def finish_route_speed_test(self: "MainWindow") -> None:
        self.route_speed_button.setEnabled(True)
        self.route_speed_status.setText("测速完成，可选择响应更快的分流")
        self.route_speed_worker = None

    def current_settings_snapshot(self: "MainWindow") -> Dict[str, object]:
        snapshot = dict(self.settings_cache)
        if hasattr(self, "login_user_edit"):
            save_password = (
                self.save_password_box.isChecked()
                if hasattr(self, "save_password_box")
                else False
            )
            if getattr(self, "_password_secret_write_failed", False):
                save_password = False
            snapshot.pop("login_password", None)
            snapshot.update(
                {
                    "login_username": self.login_user_edit.text().strip(),
                    "save_password": save_password,
                    "auto_login": (
                        self.auto_login_box.isChecked()
                        if hasattr(self, "auto_login_box")
                        else False
                    ),
                    "auto_sign": (
                        self.auto_sign_box.isChecked()
                        if hasattr(self, "auto_sign_box")
                        else False
                    ),
                }
            )
        snapshot["api_route"] = getattr(self, "api_route", 0)
        snapshot["theme_dark"] = bool(getattr(self, "theme_dark", False))
        snapshot["sidebar_collapsed"] = bool(
            getattr(self, "navigation_collapsed", False)
        )
        if not hasattr(self, "format_buttons"):
            return snapshot
        snapshot.pop("cookie", None)
        snapshot.update(
            {
                "output_format": self.selected_output_format(),
                "settings_version": 3,
                "make_pdf": self.make_pdf.isChecked(),
                "keep_images": self.keep_images.isChecked(),
                "cache_as_webp": (
                    self.cache_as_webp.isChecked()
                    if hasattr(self, "cache_as_webp")
                    else False
                ),
                "protocol_parser": (
                    self.protocol_parser.isChecked()
                    if hasattr(self, "protocol_parser")
                    else True
                ),
                "detail_check": (
                    self.detail_check.isChecked()
                    if hasattr(self, "detail_check")
                    else False
                ),
                "reading_mode": (
                    self.reading_mode_combo.currentData()
                    if hasattr(self, "reading_mode_combo")
                    else "scroll"
                ),
                "user_agent": (
                    self.ua_edit.text().strip()
                    if hasattr(self, "ua_edit")
                    else DEFAULT_USER_AGENT
                ),
                "proxy": (
                    self.proxy_edit.text().strip()
                    if hasattr(self, "proxy_edit")
                    else ""
                ),
                "proxy_mode": (
                    self.proxy_mode_combo.currentData()
                    if hasattr(self, "proxy_mode_combo")
                    else "none"
                ),
                "http_proxy": (
                    self.proxy_edit.text().strip()
                    if hasattr(self, "proxy_edit")
                    else ""
                ),
                "socks_proxy": (
                    self.socks_proxy_edit.text().strip()
                    if hasattr(self, "socks_proxy_edit")
                    else ""
                ),
                "doh_enabled": (
                    self.doh_enabled_box.isChecked()
                    if hasattr(self, "doh_enabled_box")
                    else True
                ),
                "doh_url": (
                    self.doh_url_edit.text().strip()
                    if hasattr(self, "doh_url_edit")
                    else ""
                ),
                "image_route": (
                    int(self.image_route_combo.currentData() or 0)
                    if hasattr(self, "image_route_combo")
                    else 0
                ),
                "custom_api_domain": (
                    self.custom_api_domain_edit.text().strip()
                    if hasattr(self, "custom_api_domain_edit")
                    else ""
                ),
                "custom_image_domain": (
                    self.custom_image_domain_edit.text().strip()
                    if hasattr(self, "custom_image_domain_edit")
                    else ""
                ),
                "output_dir": (
                    self.output_edit.text().strip()
                    if hasattr(self, "output_edit")
                    else ""
                ),
                "delay_min": self.delay_min.value() if hasattr(self, "delay_min") else 4,
                "delay_max": self.delay_max.value() if hasattr(self, "delay_max") else 9,
                "retries": self.retries.value() if hasattr(self, "retries") else 3,
                "backoff": self.backoff.value() if hasattr(self, "backoff") else 3,
                "image_threads": (
                    self.image_threads.value()
                    if hasattr(self, "image_threads")
                    else 5
                ),
                "download_tuning_version": 1,
                "detail_threads": (
                    self.detail_threads.value()
                    if hasattr(self, "detail_threads")
                    else 6
                ),
                "parallel_downloads": (
                    self.parallel_downloads.value()
                    if hasattr(self, "parallel_downloads")
                    else 2
                ),
                "stop_on_block": (
                    self.stop_on_block.isChecked()
                    if hasattr(self, "stop_on_block")
                    else True
                ),
            }
        )
        return snapshot

    def persist_sensitive_settings(self: "MainWindow") -> None:
        """Persist credentials separately so building a settings snapshot is pure."""
        if hasattr(self, "login_user_edit"):
            save_password = (
                self.save_password_box.isChecked()
                if hasattr(self, "save_password_box")
                else False
            )
            password = (
                self.login_pass_edit.text()
                if save_password and hasattr(self, "login_pass_edit")
                else ""
            )
            try:
                if password:
                    set_secret("login_password", password)
                else:
                    delete_secret("login_password")
                    save_password = False
            except (OSError, RuntimeError):
                self._password_secret_write_failed = True
            else:
                self._password_secret_write_failed = False

        if hasattr(self, "cookie_edit"):
            cookie_header = self.cookie_edit.toPlainText().strip()
            try:
                if cookie_header:
                    save_cookie_dict(parse_cookie_header(cookie_header))
                else:
                    clear_cookie_store()
            except (OSError, RuntimeError):
                pass

    def apply_saved_settings(self: "MainWindow") -> None:
        if not self.settings_cache:
            self.connect_settings_autosave()
            return
        migrated_legacy_credentials = False
        self._applying_settings = True
        try:
            if hasattr(self, "login_user_edit"):
                self.login_user_edit.setText(
                    str(self.settings_cache.get("login_username") or "")
                )
            if hasattr(self, "save_password_box"):
                self.save_password_box.setChecked(
                    bool(self.settings_cache.get("save_password", False))
                )
            if hasattr(self, "auto_login_box"):
                self.auto_login_box.setChecked(
                    bool(self.settings_cache.get("auto_login", False))
                )
            if hasattr(self, "auto_sign_box"):
                self.auto_sign_box.setChecked(
                    bool(self.settings_cache.get("auto_sign", False))
                )
            if hasattr(self, "login_pass_edit") and bool(
                self.settings_cache.get("save_password", False)
            ):
                encoded_password = str(
                    self.settings_cache.pop("login_password", "") or ""
                )
                password = get_secret("login_password")
                if not password and encoded_password:
                    password = migrate_legacy_base64_secret(
                        "login_password", encoded_password
                    )
                    migrated_legacy_credentials = True
                self.login_pass_edit.setText(password)
            output_format = str(self.settings_cache.get("output_format") or "pdf")
            if output_format in self.format_buttons:
                self.format_buttons[output_format].setChecked(True)
            self.make_pdf.setChecked(bool(self.settings_cache.get("make_pdf", False)))
            self.keep_images.setChecked(
                bool(self.settings_cache.get("keep_images", True))
            )
            if hasattr(self, "cache_as_webp"):
                self.cache_as_webp.setChecked(
                    bool(self.settings_cache.get("cache_as_webp", False))
                )
            if hasattr(self, "protocol_parser"):
                self.protocol_parser.setChecked(
                    bool(self.settings_cache.get("protocol_parser", True))
                )
            if hasattr(self, "detail_check"):
                self.detail_check.setChecked(
                    bool(self.settings_cache.get("detail_check", False))
                )
            if hasattr(self, "reading_mode_combo"):
                reading_mode = str(
                    self.settings_cache.get("reading_mode") or "scroll"
                )
                index = self.reading_mode_combo.findData(reading_mode)
                self.reading_mode_combo.setCurrentIndex(index if index >= 0 else 0)

            legacy_cookie = str(self.settings_cache.pop("cookie", "") or "").strip()
            if legacy_cookie:
                try:
                    save_cookie_dict(parse_cookie_header(legacy_cookie))
                except OSError:
                    pass
                migrated_legacy_credentials = True
            cookie = load_cookie_header()
            if cookie:
                self.cookie_edit.setPlainText(cookie)
                if hasattr(self, "login_cookie_edit"):
                    self.login_cookie_edit.setPlainText(cookie)
            self.ua_edit.setText(
                str(self.settings_cache.get("user_agent") or DEFAULT_USER_AGENT)
            )
            if hasattr(self, "login_ua_edit"):
                self.login_ua_edit.setText(self.ua_edit.text())
            self.proxy_edit.setText(str(self.settings_cache.get("proxy") or ""))
            if hasattr(self, "proxy_mode_combo"):
                proxy_mode = str(
                    self.settings_cache.get("proxy_mode")
                    or ("http" if self.settings_cache.get("proxy") else "none")
                )
                proxy_index = self.proxy_mode_combo.findData(proxy_mode)
                self.proxy_mode_combo.setCurrentIndex(max(0, proxy_index))
                self.proxy_edit.setText(
                    str(
                        self.settings_cache.get("http_proxy")
                        or self.settings_cache.get("proxy")
                        or ""
                    )
                )
                self.socks_proxy_edit.setText(
                    str(self.settings_cache.get("socks_proxy") or "")
                )
                self.doh_enabled_box.setChecked(
                    bool(self.settings_cache.get("doh_enabled", True))
                )
                self.doh_url_edit.setText(
                    str(self.settings_cache.get("doh_url") or DOH_URL)
                )
                api_index = self.api_route_combo.findData(
                    int(self.settings_cache.get("api_route", 0) or 0)
                )
                image_index = self.image_route_combo.findData(
                    int(self.settings_cache.get("image_route", 0) or 0)
                )
                self.api_route_combo.setCurrentIndex(max(0, api_index))
                self.image_route_combo.setCurrentIndex(max(0, image_index))
                self.custom_api_domain_edit.setText(
                    str(self.settings_cache.get("custom_api_domain") or "")
                )
                self.custom_image_domain_edit.setText(
                    str(self.settings_cache.get("custom_image_domain") or "")
                )
                self.update_proxy_field_state()
                self.apply_network_route_selection()
            output_dir = str(self.settings_cache.get("output_dir") or "")
            if output_dir and self.should_keep_saved_output_dir(output_dir):
                self.output_edit.setText(output_dir)
            else:
                self.output_edit.setText(str(self.default_output_dir))

            self.delay_min.setValue(int(self.settings_cache.get("delay_min", 4)))
            self.delay_max.setValue(int(self.settings_cache.get("delay_max", 9)))
            self.retries.setValue(int(self.settings_cache.get("retries", 3)))
            self.backoff.setValue(int(self.settings_cache.get("backoff", 3)))
            saved_image_threads = int(self.settings_cache.get("image_threads", 5))
            if int(self.settings_cache.get("download_tuning_version", 0)) < 1:
                saved_image_threads = max(5, saved_image_threads)
                self.settings_cache["image_threads"] = saved_image_threads
                self.settings_cache["download_tuning_version"] = 1
            self.image_threads.setValue(saved_image_threads)
            self.detail_threads.setValue(
                int(self.settings_cache.get("detail_threads", 6))
            )
            if hasattr(self, "parallel_downloads"):
                self.parallel_downloads.setValue(
                    int(self.settings_cache.get("parallel_downloads", 2))
                )
            self.stop_on_block.setChecked(
                bool(self.settings_cache.get("stop_on_block", True))
            )
        finally:
            self._applying_settings = False
        self.persist_download_root()
        self.connect_settings_autosave()
        if migrated_legacy_credentials:
            self.save_local_cache()

    def connect_settings_autosave(self: "MainWindow") -> None:
        if getattr(self, "_settings_autosave_connected", False):
            return
        for button in getattr(self, "format_buttons", {}).values():
            button.toggled.connect(self.schedule_settings_save)
        checkboxes = [
            self.make_pdf,
            self.keep_images,
            getattr(self, "cache_as_webp", None),
            getattr(self, "protocol_parser", None),
            self.stop_on_block,
            getattr(self, "detail_check", None),
        ]
        for checkbox in checkboxes:
            if checkbox:
                checkbox.toggled.connect(self.schedule_settings_save)
        edits = [
            self.ua_edit,
            self.proxy_edit,
            self.output_edit,
            getattr(self, "socks_proxy_edit", None),
            getattr(self, "doh_url_edit", None),
            getattr(self, "custom_api_domain_edit", None),
            getattr(self, "custom_image_domain_edit", None),
        ]
        for edit in edits:
            if edit is not None:
                edit.textChanged.connect(self.schedule_settings_save)
        self.cookie_edit.textChanged.connect(self.schedule_settings_save)
        for edit in (
            getattr(self, "login_user_edit", None),
            getattr(self, "login_pass_edit", None),
        ):
            if edit:
                edit.textChanged.connect(self.schedule_settings_save)
        for checkbox in (
            getattr(self, "save_password_box", None),
            getattr(self, "auto_login_box", None),
            getattr(self, "auto_sign_box", None),
        ):
            if checkbox:
                checkbox.toggled.connect(self.schedule_settings_save)
        if hasattr(self, "reading_mode_combo"):
            self.reading_mode_combo.currentIndexChanged.connect(
                self.schedule_settings_save
            )
        for combo in (
            getattr(self, "proxy_mode_combo", None),
            getattr(self, "api_route_combo", None),
            getattr(self, "image_route_combo", None),
        ):
            if combo is None:
                continue
            combo.currentIndexChanged.connect(self.schedule_settings_save)
            combo.currentIndexChanged.connect(self.apply_network_route_selection)
        if hasattr(self, "doh_enabled_box"):
            self.doh_enabled_box.toggled.connect(self.schedule_settings_save)
        for edit in (
            getattr(self, "custom_api_domain_edit", None),
            getattr(self, "custom_image_domain_edit", None),
        ):
            if edit is not None:
                edit.textChanged.connect(self.apply_network_route_selection)
        spinboxes = [
            self.delay_min,
            self.delay_max,
            self.retries,
            self.backoff,
            self.image_threads,
            self.detail_threads,
            getattr(self, "parallel_downloads", None),
        ]
        for spinbox in spinboxes:
            if spinbox is not None:
                spinbox.valueChanged.connect(self.schedule_settings_save)
        self._settings_autosave_connected = True

    def schedule_settings_save(self: "MainWindow", *_args) -> None:
        if self._applying_settings:
            return
        self.persist_sensitive_settings()
        self.settings_cache = self.current_settings_snapshot()
        self.schedule_local_cache_save(250)
