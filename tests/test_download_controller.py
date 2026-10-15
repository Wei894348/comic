from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from jm_app.frontend.controllers.download_controller import DownloadController
from jm_app.models import DownloadState


class _StateRecorder:
    def __init__(self):
        self.updates = []

    def update_download_state(self, task_id, state, **values):
        self.updates.append((task_id, state, values))

    def save_download_task(self, _task):
        return None


class DownloadControllerTest(unittest.TestCase):
    def test_pause_survives_a_cancelled_worker_failure_callback(self):
        state = _StateRecorder()
        controller = DownloadController(lambda: None, state)
        task_id = "download:42"
        cancelled = threading.Event()
        cancelled.set()
        controller.workers["42"] = SimpleNamespace(
            cancel_event=cancelled,
            isRunning=lambda: False,
        )
        controller.task_ids["42"] = task_id

        controller.pause("42")
        controller._on_failed("42", "cancelled for pause")

        self.assertEqual(state.updates[-1][0], task_id)
        self.assertEqual(state.updates[-1][1], DownloadState.PAUSED)


if __name__ == "__main__":
    unittest.main()
