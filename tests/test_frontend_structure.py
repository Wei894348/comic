from __future__ import annotations

import unittest

from jm_app.frontend.pages import SettingsPageMixin
from jm_app.frontend.lifecycle import LifecycleController
from jm_app.frontend.state_persistence import StatePersistenceMixin
from jm_app.frontend.ui import MainWindow
from jm_app.tasks import (
    CacheMaintenanceWorker,
    CacheRestoreWorker,
    CoverDecodeWorker,
    CoverFetchWorker,
    DomainRefreshWorker,
    HistoryLocalCoverWorker,
    HistoryResourceDeleteWorker,
    LibraryWorker,
    LocalHistorySyncWorker,
    LocalReaderImportWorker,
    LocalReaderPrepareWorker,
    LoginVerifyWorker,
    ProfileFetchWorker,
)
from jm_app.tasks.library_tool_tasks import LibraryToolWorker


class FrontendStructureTest(unittest.TestCase):
    def assert_mixin_owns(self, mixin, method_names):
        for method_name in method_names:
            with self.subTest(mixin=mixin.__name__, method=method_name):
                self.assertNotIn(method_name, MainWindow.__dict__)
                self.assertIs(getattr(MainWindow, method_name), getattr(mixin, method_name))

    def test_settings_page_owns_settings_persistence(self):
        self.assert_mixin_owns(
            SettingsPageMixin,
            (
                "current_settings_snapshot",
                "persist_sensitive_settings",
                "apply_saved_settings",
                "connect_settings_autosave",
                "schedule_settings_save",
            ),
        )

    def test_state_mixin_owns_local_persistence_and_writer_shutdown(self):
        self.assert_mixin_owns(
            StatePersistenceMixin,
            (
                "load_local_cache",
                "save_local_cache",
                "schedule_local_cache_save",
                "_save_history_snapshot",
                "shutdown_db_writer",
                "shutdown_cover_cache_writer",
            ),
        )

    def test_account_workers_live_in_the_task_layer(self):
        for worker_class in (
            DomainRefreshWorker,
            LoginVerifyWorker,
            ProfileFetchWorker,
            LibraryWorker,
        ):
            with self.subTest(worker=worker_class.__name__):
                self.assertEqual(worker_class.__module__, "jm_app.tasks.account_tasks")

    def test_library_tool_worker_lives_in_the_task_layer(self):
        self.assertEqual(
            LibraryToolWorker.__module__, "jm_app.tasks.library_tool_tasks"
        )

    def test_window_support_workers_live_in_domain_task_modules(self):
        expected_modules = {
            CoverFetchWorker: "jm_app.tasks.cover_workers",
            CoverDecodeWorker: "jm_app.tasks.cover_workers",
            CacheRestoreWorker: "jm_app.tasks.cache_tasks",
            CacheMaintenanceWorker: "jm_app.tasks.cache_tasks",
            LocalHistorySyncWorker: "jm_app.tasks.local_file_tasks",
            LocalReaderImportWorker: "jm_app.tasks.local_file_tasks",
            LocalReaderPrepareWorker: "jm_app.tasks.local_file_tasks",
            HistoryLocalCoverWorker: "jm_app.tasks.local_file_tasks",
            HistoryResourceDeleteWorker: "jm_app.tasks.local_file_tasks",
        }
        for worker_class, module_name in expected_modules.items():
            with self.subTest(worker=worker_class.__name__):
                self.assertEqual(worker_class.__module__, module_name)
                self.assertNotIn(worker_class.__name__, MainWindow.__dict__)

    def test_main_window_delegates_close_lifecycle(self):
        self.assertEqual(
            LifecycleController.__module__, "jm_app.frontend.lifecycle"
        )
        self.assertIn("handle_close", MainWindow.closeEvent.__code__.co_names)
        self.assertIn(
            "cancel_background_tasks_for_exit",
            MainWindow.cancel_background_tasks_for_exit.__code__.co_names,
        )


if __name__ == "__main__":
    unittest.main()
