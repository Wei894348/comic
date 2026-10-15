from __future__ import annotations

import unittest

from jm_app.frontend.ui import MainWindow


class _Edit:
    def text(self) -> str:
        return ""


class _CommentHost:
    def __init__(self, filter_mode: str = "all"):
        self.comment_context_album_id = ""
        self.library_comment_album_edit = _Edit()
        self.comment_filter_mode = filter_mode
        self.session_uid = "12345"
        self.library_comment_page = 1
        self.library_comment_request_serial = 0
        self.personal_comment_statistics = None
        self.personal_comment_statistics_uid = ""
        self.personal_comment_statistics_loading = False
        self.personal_comment_statistics_serial = 0
        self.started = []
        self.rendered = []
        self.pagers = []
        self.statistics = []

    def start_library_action(self, action, payload, requires_session=True):
        self.started.append((action, payload, requires_session))
        return True

    def set_library_status_text(self, _text):
        pass

    def render_library_comments(self, comments, total):
        self.rendered.append((comments, total))

    def update_library_pager(self, scope, page, total, page_count):
        self.pagers.append((scope, page, total, page_count))

    def refresh_personal_comment_statistics(self, force=False):
        return MainWindow.refresh_personal_comment_statistics(self, force)

    def update_comment_statistics(self, _comments, _total):
        self.statistics.append(self.personal_comment_statistics)

    def log(self, _message):
        pass


class CommentRequestScopeTest(unittest.TestCase):
    def test_all_filter_requests_global_comments(self):
        host = _CommentHost("all")

        MainWindow.refresh_library_comments(host)

        action, payload, requires_session = host.started[-1]
        self.assertEqual(action, "comments")
        self.assertFalse(payload["mine"])
        self.assertEqual(payload["user_id"], "")
        self.assertFalse(requires_session)
        self.assertEqual(host.started[0][0], "comment_stats")
        self.assertEqual(host.started[0][1]["user_id"], "12345")

    def test_personal_filters_request_comments_for_current_uid(self):
        for filter_mode in ("published", "replied", "liked"):
            with self.subTest(filter_mode=filter_mode):
                host = _CommentHost(filter_mode)
                MainWindow.refresh_library_comments(host)
                _action, payload, requires_session = host.started[-1]
                self.assertTrue(payload["mine"])
                self.assertEqual(payload["user_id"], "12345")
                self.assertTrue(requires_session)

    def test_stale_comment_response_cannot_replace_new_filter(self):
        host = _CommentHost("published")
        host.library_comment_request_serial = 2

        MainWindow.on_library_loaded(
            host,
            "comments",
            {
                "comments": [{"CID": "old"}],
                "total": 999,
                "personal": False,
                "request_serial": 1,
                "page": 1,
            },
        )

        self.assertEqual(host.rendered, [])

    def test_global_and_personal_responses_use_their_own_totals(self):
        host = _CommentHost("all")
        host.library_comment_request_serial = 1
        MainWindow.on_library_loaded(
            host,
            "comments",
            {
                "comments": [{"CID": "global"}],
                "total": 125,
                "own_total": None,
                "personal": False,
                "request_serial": 1,
                "page": 1,
            },
        )
        self.assertEqual(host.rendered[-1][1], 125)

        host.library_comment_request_serial = 2
        MainWindow.on_library_loaded(
            host,
            "comments",
            {
                "comments": [{"CID": "mine"}],
                "total": 7,
                "own_total": 7,
                "personal": True,
                "request_serial": 2,
                "page": 1,
            },
        )
        self.assertEqual(host.rendered[-1][1], 7)

    def test_personal_statistics_response_updates_independent_values(self):
        host = _CommentHost("all")
        host.personal_comment_statistics_serial = 3

        MainWindow.on_library_loaded(
            host,
            "comment_stats",
            {
                "published": 8,
                "likes": 14,
                "featured": 3,
                "replies": 5,
                "user_id": "12345",
                "request_serial": 3,
            },
        )

        self.assertEqual(
            host.personal_comment_statistics,
            {"published": 8, "likes": 14, "featured": 3, "replies": 5},
        )
        self.assertEqual(host.statistics[-1], host.personal_comment_statistics)

    def test_stale_or_other_user_statistics_cannot_replace_current_values(self):
        host = _CommentHost("all")
        host.personal_comment_statistics_serial = 4
        host.personal_comment_statistics = {"published": 2}

        MainWindow.on_library_loaded(
            host,
            "comment_stats",
            {
                "published": 99,
                "user_id": "54321",
                "request_serial": 4,
            },
        )
        MainWindow.on_library_loaded(
            host,
            "comment_stats",
            {
                "published": 88,
                "user_id": "12345",
                "request_serial": 3,
            },
        )

        self.assertEqual(host.personal_comment_statistics, {"published": 2})


if __name__ == "__main__":
    unittest.main()
