from __future__ import annotations

import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from jm_app.services.cover_service import CoverService


class _Response:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses: dict[str, _Response]):
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs) -> _Response:
        self.urls.append(url)
        return self.responses[url]


class _Cache:
    def read(self, _book_id: str):
        return None

    def write(self, _book_id: str, _data: bytes) -> None:
        return None


class CoverServiceTest(unittest.TestCase):
    def test_tries_each_distinct_cdn_url(self):
        image = QImage(2, 3, QImage.Format_RGB32)
        image.fill(0xFF336699)
        payload = QByteArray()
        buffer = QBuffer(payload)
        self.assertTrue(buffer.open(QIODevice.WriteOnly))
        self.assertTrue(image.save(buffer, "PNG"))
        buffer.close()

        first = "https://cdn-one.example/media/albums/1_3x4.jpg"
        second = "https://cdn-two.example/media/albums/1_3x4.jpg"
        session = _Session({first: _Response(b""), second: _Response(bytes(payload))})

        @contextmanager
        def fake_session(*_args, **_kwargs):
            yield session

        with patch("jm_app.services.cover_service.create_network_session", fake_session):
            service = CoverService(cache=_Cache())
            result = service.load(
                "1", [first, first, second], "", "www.cdnhjk.net", "", threading.Event(), False
            )

        self.assertFalse(result.isNull())
        self.assertEqual(session.urls, [first, second])
        self.assertEqual(service.loaded_url, second)
        self.assertEqual(service.failed_urls, [first])
