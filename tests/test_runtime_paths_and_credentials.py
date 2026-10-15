from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jm_app.backend import credential_store, runtime_paths
from jm_app.frontend.ui import MainWindow


class RuntimePathsTest(unittest.TestCase):
    def test_legacy_data_and_logs_move_to_user_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_root = root / "legacy-project"
            legacy_data = legacy_root / "data"
            legacy_data.mkdir(parents=True)
            (legacy_data / "config.json").write_text('{"theme_dark": true}', encoding="utf-8")
            legacy_logs = legacy_root / "logs"
            legacy_logs.mkdir()
            (legacy_logs / "comic18.log").write_text("old log", encoding="utf-8")
            user_data = root / "user-data"

            with patch.dict(os.environ, {"COMIC18_DATA_DIR": str(user_data)}), patch.object(
                runtime_paths, "app_base_dir", return_value=legacy_root
            ):
                self.assertEqual(runtime_paths.app_data_dir(), user_data)
                self.assertTrue((user_data / "config.json").exists())
                self.assertEqual(runtime_paths.log_dir(), user_data / "logs")
                self.assertEqual(
                    (user_data / "logs" / "comic18.log").read_text(encoding="utf-8"),
                    "old log",
                )

    def test_existing_download_root_is_not_moved_during_data_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_root = root / "legacy-project"
            legacy_downloads = legacy_root / "commies"
            legacy_downloads.mkdir(parents=True)
            marker = legacy_downloads / "completed.cbz"
            marker.write_bytes(b"archive")
            user_data = root / "user-data"

            with patch.dict(os.environ, {"COMIC18_DATA_DIR": str(user_data)}), patch.object(
                runtime_paths, "app_base_dir", return_value=legacy_root
            ):
                self.assertEqual(runtime_paths.downloads_dir(), legacy_downloads)
                self.assertTrue(marker.exists())


class CredentialStoreTest(unittest.TestCase):
    def setUp(self):
        if os.name != "nt":
            self.skipTest("requires Windows DPAPI support")

    def test_migrated_password_is_dpapi_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            user_data = Path(directory) / "user-data"
            legacy_value = "c2VjdXJlLXBhc3N3b3Jk"
            with patch.dict(os.environ, {"COMIC18_DATA_DIR": str(user_data)}):
                password = credential_store.migrate_legacy_base64_secret(
                    "login_password", legacy_value
                )
                self.assertEqual(password, "secure-password")
                self.assertEqual(
                    credential_store.get_secret("login_password"), "secure-password"
                )
                stored = json.loads((user_data / "credentials.json").read_text(encoding="utf-8"))
                self.assertNotIn("secure-password", json.dumps(stored))
                self.assertNotEqual(stored["login_password"], legacy_value)

    def test_settings_snapshot_excludes_cookie_without_storing_it(self):
        class Field:
            def isChecked(self):
                return False

            def text(self):
                return ""

            def toPlainText(self):
                return "AVS=protected-cookie"

            def currentData(self):
                return None

            def value(self):
                return 0

        field = Field()
        window = SimpleNamespace(
            settings_cache={"cookie": "legacy-cookie"},
            api_route=0,
            theme_dark=False,
            navigation_collapsed=False,
            format_buttons={},
            selected_output_format=lambda: "images",
            cookie_edit=field,
            make_pdf=field,
            keep_images=field,
            ua_edit=field,
            proxy_edit=field,
            proxy_mode_combo=field,
            socks_proxy_edit=field,
            doh_enabled_box=field,
            doh_url_edit=field,
            image_route_combo=field,
            custom_api_domain_edit=field,
            custom_image_domain_edit=field,
            output_edit=field,
            delay_min=field,
            delay_max=field,
            retries=field,
            backoff=field,
            image_threads=field,
            detail_threads=field,
            parallel_downloads=field,
            stop_on_block=field,
        )

        with patch("jm_app.frontend.pages.settings.save_cookie_dict") as save_cookie:
            snapshot = MainWindow.current_settings_snapshot(window)

        self.assertNotIn("cookie", snapshot)
        save_cookie.assert_not_called()

    def test_sensitive_settings_are_stored_outside_snapshot_generation(self):
        class Field:
            def toPlainText(self):
                return "AVS=protected-cookie"

        window = SimpleNamespace(cookie_edit=Field())
        with patch("jm_app.frontend.pages.settings.save_cookie_dict") as save_cookie:
            MainWindow.persist_sensitive_settings(window)

        save_cookie.assert_called_once()

    def test_settings_autosave_uses_owned_debounce_timer(self):
        snapshot = {"theme_dark": True}
        window = SimpleNamespace(
            _applying_settings=False,
            persist_sensitive_settings=Mock(),
            current_settings_snapshot=Mock(return_value=snapshot),
            schedule_local_cache_save=Mock(),
        )

        MainWindow.schedule_settings_save(window)

        window.persist_sensitive_settings.assert_called_once()
        self.assertEqual(window.settings_cache, snapshot)
        window.schedule_local_cache_save.assert_called_once_with(250)

if __name__ == "__main__":
    unittest.main()
