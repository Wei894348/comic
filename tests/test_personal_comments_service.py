from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from jm_app.backend.jm_api import JmApiClient
from jm_app.backend.schemas import NetworkSettings
from jm_app.backend.services import get_comments, get_personal_comment_summary


class PersonalCommentsServiceTest(unittest.TestCase):
    @patch("jm_app.backend.services._user_client")
    def test_personal_comments_use_explicit_session_uid(self, user_client):
        client = Mock()
        client.forum_comments.return_value = ([{"CID": "1"}], 7)
        user_client.return_value = (client, "")

        result = get_comments(
            NetworkSettings(cookie_header="AVS=token"),
            page=2,
            mine=True,
            user_id="12345",
        )

        client.forum_comments.assert_called_once_with(
            album_id="",
            page=2,
            user_id="12345",
        )
        self.assertEqual(result["total"], 7)
        self.assertEqual(result["own_total"], 7)
        self.assertTrue(result["personal"])

    @patch("jm_app.backend.services._user_client")
    def test_global_comments_never_send_the_current_uid(self, user_client):
        client = Mock()
        client.forum_comments.return_value = ([{"CID": "2"}], 125)
        user_client.return_value = (client, "12345")

        result = get_comments(
            NetworkSettings(cookie_header="AVS=token"),
            page=3,
            mine=False,
            user_id="12345",
        )

        client.forum_comments.assert_called_once_with(
            album_id="",
            page=3,
            user_id="",
        )
        self.assertEqual(result["total"], 125)
        self.assertIsNone(result["own_total"])
        self.assertFalse(result["personal"])

    @patch("jm_app.backend.services._user_client")
    def test_personal_comments_never_fall_back_to_global_forum(self, user_client):
        client = Mock()
        user_client.return_value = (client, "")

        with self.assertRaisesRegex(ValueError, "UID"):
            get_comments(NetworkSettings(cookie_header="AVS=token"), mine=True)

        client.forum_comments.assert_not_called()

    def test_avatar_urls_prefer_profile_photo_and_keep_uid_fallback(self):
        client = JmApiClient.__new__(JmApiClient)
        client._image_domains = ["img-one.test", "img-two.test"]

        urls = client.user_avatar_urls("12345", "custom-avatar.webp")

        self.assertEqual(
            urls[0], "https://img-one.test/media/users/custom-avatar.webp"
        )
        self.assertIn("https://img-one.test/media/users/12345.jpg", urls)

    @patch("jm_app.backend.services._user_client")
    def test_personal_summary_aggregates_pages_and_deduplicates_comments(self, user_client):
        client = Mock()
        client.forum_comments.side_effect = [
            (
                [
                    {"CID": "1", "likes": "1,200", "replys": [{}, {}]},
                    {"CID": "2", "likes": "0", "reply_count": "3"},
                ],
                3,
            ),
            (
                [
                    {"CID": "2", "likes": "0", "reply_count": "3"},
                    {"CID": "3", "like_count": "4", "replies": "2"},
                ],
                3,
            ),
        ]
        user_client.return_value = (client, "12345")

        result = get_personal_comment_summary(NetworkSettings(), user_id="12345")

        self.assertEqual(result["published"], 3)
        self.assertEqual(result["likes"], 1204)
        self.assertEqual(result["featured"], 2)
        self.assertEqual(result["replies"], 7)
        self.assertEqual(result["user_id"], "12345")
        self.assertEqual(client.forum_comments.call_count, 2)

    @patch("jm_app.backend.services._user_client")
    def test_personal_summary_stops_when_a_page_adds_no_comments(self, user_client):
        client = Mock()
        repeated = [{"CID": "1", "likes": "2"}]
        client.forum_comments.side_effect = [(repeated, 10), (repeated, 10)]
        user_client.return_value = (client, "12345")

        result = get_personal_comment_summary(NetworkSettings())

        self.assertEqual(result["published"], 10)
        self.assertEqual(result["likes"], 2)
        self.assertEqual(client.forum_comments.call_count, 2)

    @patch("jm_app.backend.services._user_client")
    def test_personal_summary_requires_uid(self, user_client):
        client = Mock()
        user_client.return_value = (client, "")

        with self.assertRaisesRegex(ValueError, "UID"):
            get_personal_comment_summary(NetworkSettings())

        client.forum_comments.assert_not_called()


if __name__ == "__main__":
    unittest.main()
