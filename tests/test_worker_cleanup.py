from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from jm_app.frontend.pages.profile import ProfilePageMixin
from jm_app.frontend.ui import MainWindow


class WorkerCleanupTest(unittest.TestCase):
    def test_domain_cleanup_keeps_newer_worker_and_deletes_finished_one(self):
        active_worker = object()
        finished_worker = SimpleNamespace(deleteLater=Mock())
        window = SimpleNamespace(domain_worker=active_worker)

        MainWindow.cleanup_domain_worker(window, finished_worker)

        self.assertIs(window.domain_worker, active_worker)
        finished_worker.deleteLater.assert_called_once()

    def test_login_cleanup_deletes_finished_worker(self):
        worker = SimpleNamespace(deleteLater=Mock())
        window = SimpleNamespace(login_worker=worker, set_login_controls_enabled=Mock())

        MainWindow.cleanup_login_worker(window, worker)

        self.assertIsNone(window.login_worker)
        window.set_login_controls_enabled.assert_called_once_with(True)
        worker.deleteLater.assert_called_once()

    def test_profile_cleanup_keeps_newer_worker_and_deletes_finished_one(self):
        active_worker = object()
        finished_worker = SimpleNamespace(deleteLater=Mock())
        window = SimpleNamespace(profile_worker=active_worker)

        ProfilePageMixin.cleanup_profile_worker(window, finished_worker)

        self.assertIs(window.profile_worker, active_worker)
        finished_worker.deleteLater.assert_called_once()

    def test_daily_sign_cleanup_deletes_finished_worker(self):
        worker = SimpleNamespace(deleteLater=Mock())
        window = SimpleNamespace(daily_sign_worker=worker)

        ProfilePageMixin.cleanup_daily_sign_worker(window, worker)

        self.assertIsNone(window.daily_sign_worker)
        worker.deleteLater.assert_called_once()


if __name__ == "__main__":
    unittest.main()
