from __future__ import annotations

import unittest
from unittest.mock import patch

from jm_app.tasks import account_tasks
from jm_app.tasks.account_tasks import LibraryWorker


class AccountTasksTest(unittest.TestCase):
    def test_comment_action_maps_payload_to_service_arguments(self):
        settings = object()
        worker = LibraryWorker(
            "comments",
            settings,
            {
                "album_id": "42",
                "page": 3,
                "mine": True,
                "user_id": "7",
            },
        )
        with patch.object(
            account_tasks, "get_comments", return_value={"comments": []}
        ) as get_comments:
            result = worker._execute_action()

        self.assertEqual(result, {"comments": []})
        get_comments.assert_called_once_with(
            settings,
            album_id="42",
            page=3,
            mine=True,
            user_id="7",
        )

    def test_run_preserves_request_scope_metadata(self):
        worker = LibraryWorker(
            "comments",
            object(),
            {"request_serial": 9, "comment_filter": "mine"},
        )
        emitted = []
        worker.loaded.connect(lambda action, result: emitted.append((action, result)))
        with patch.object(worker, "_execute_action", return_value={"comments": []}):
            worker.run()

        self.assertEqual(
            emitted,
            [
                (
                    "comments",
                    {
                        "comments": [],
                        "request_serial": 9,
                        "comment_filter": "mine",
                    },
                )
            ],
        )

    def test_unknown_action_is_rejected(self):
        worker = LibraryWorker("unknown", object())
        with self.assertRaisesRegex(ValueError, "未知收藏与记录操作"):
            worker._execute_action()


if __name__ == "__main__":
    unittest.main()
