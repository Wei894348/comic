from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from jm_app.backend.models import AlbumMeta, NetworkConfig
from jm_app.models import PageQuery
from jm_app.services.catalog_service import CatalogService


class _Client:
    def __init__(self, *_args, **_kwargs):
        self.promote_pages = []
        self.latest_pages = []

    def promote_sections(self, page):
        self.promote_pages.append(page)
        return {
            "C107推荐本本": [
                AlbumMeta(album_id="curated", title="精选", url="https://example.test/curated")
            ]
        }

    def latest(self, page):
        self.latest_pages.append(page)
        return [AlbumMeta(album_id="latest", title="最新", url="https://example.test/latest")]


class CatalogServiceTest(unittest.TestCase):
    def setUp(self):
        self.config = NetworkConfig("", "", 0, 0, 0, 0, False)
        self.query = PageQuery(mode="promote", promote_section="C107")

    def test_promote_first_page_uses_curated_section(self):
        client = _Client()
        with patch("jm_app.services.catalog_service.JmApiClient", return_value=client):
            books, sections = CatalogService().load_page(self.query, 1, self.config, threading.Event())

        self.assertEqual([book.book_id for book in books], ["curated"])
        self.assertIn("C107推荐本本", sections)
        self.assertEqual(client.promote_pages, [1])
        self.assertEqual(client.latest_pages, [])

    def test_promote_second_page_uses_pageable_latest_feed(self):
        client = _Client()
        with patch("jm_app.services.catalog_service.JmApiClient", return_value=client):
            books, sections = CatalogService().load_page(self.query, 2, self.config, threading.Event())

        self.assertEqual([book.book_id for book in books], ["latest"])
        self.assertEqual(sections, {})
        self.assertEqual(client.promote_pages, [])
        self.assertEqual(client.latest_pages, [0])
