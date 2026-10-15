from __future__ import annotations

from dataclasses import asdict
import unittest

from jm_app.backend.constants import BASE_URL, WEB_DOMAINS
from jm_app.backend.jm_api import (
    API_DOMAINS as COMPAT_API_DOMAINS,
    API_DOMAIN_SERVER_URLS,
    IMAGE_DOMAINS as COMPAT_IMAGE_DOMAINS,
)
from jm_app.backend.jm_endpoints import (
    API_DOMAIN_DISCOVERY_URLS,
    API_DOMAINS,
    API_PATHS,
    IMAGE_DOMAINS,
    WEB_LIST_URL,
    album_cover_path,
    photo_image_path,
    profile_web_url,
    user_media_path,
)
from jm_app.backend.library_tools import DEFAULT_DOH_ENDPOINT
from jm_app.backend.network_session import DOH_FALLBACK_URLS, DOH_URL


class JmcomicQtServiceDefaultsTest(unittest.TestCase):
    def test_defaults_match_jmcomic_qt_global_config(self):
        self.assertEqual(BASE_URL, "https://18-comicblade.art")
        self.assertEqual(
            WEB_DOMAINS,
            (
                "https://comic18j-yodo.net",
                "https://18comic.vip",
                "https://jmcomic.me",
                "https://18comic.tw",
                "https://jmcomic-zzz.org",
                "https://comic18j-robo.net",
                "https://comic18j-lodo.net",
            ),
        )
        self.assertEqual(
            API_DOMAINS,
            ("www.cdnhjk.net", "www.cdngwc.cc", "www.cdngwc.net", "www.cdngwc.club"),
        )
        self.assertEqual(
            IMAGE_DOMAINS,
            (
                "cdn-msp.jmapiproxy1.cc",
                "cdn-msp.jmapiproxy3.cc",
                "cdn-msp.jmapinodeudzn.net",
                "cdn-msp.jmdanjonproxy.xyz",
            ),
        )
        self.assertEqual(
            API_DOMAIN_DISCOVERY_URLS,
            ("https://rup4a04-c01.tos-ap-southeast-1.bytepluses.com/newsvr-2025.txt",),
        )
        self.assertEqual(WEB_LIST_URL, "https://18-comicblade.art/albums/meiman")
        self.assertEqual(DOH_URL, "https://parse.jpacg.cc/parse")
        self.assertEqual(DEFAULT_DOH_ENDPOINT, DOH_URL)
        self.assertEqual(DOH_FALLBACK_URLS, ("https://doh.pub/dns-query", "https://dot.pub/dns-query"))

    def test_api_route_registry_is_complete(self):
        self.assertEqual(
            asdict(API_PATHS),
            {
                "login": "/login",
                "daily": "/daily",
                "daily_check": "/daily_chk",
                "favorite": "/favorite",
                "favorite_folder": "/favorite_folder",
                "watch_list": "/watch_list",
                "forum": "/forum",
                "comment": "/comment",
                "search": "/search",
                "category_filter": "/categories/filter",
                "promote": "/promote",
                "latest": "/latest",
                "week": "/week",
                "week_filter": "/week/filter",
                "album": "/album",
                "chapter": "/chapter",
                "chapter_view_template": "/chapter_view_template",
            },
        )

    def test_media_and_profile_routes_are_built_centrally(self):
        self.assertEqual(album_cover_path("123"), "/media/albums/123_3x4.jpg")
        self.assertEqual(album_cover_path("123", portrait=False), "/media/albums/123.jpg")
        self.assertEqual(photo_image_path("456", "001.webp"), "/media/photos/456/001.webp")
        self.assertEqual(user_media_path("/legacy/avatar.jpg"), "/media/users/avatar.jpg")
        self.assertEqual(profile_web_url("name with space"), "https://comic18j-oomi.net/user/name%20with%20space")

    def test_legacy_exports_follow_the_endpoint_registry(self):
        self.assertEqual(COMPAT_API_DOMAINS, list(API_DOMAINS))
        self.assertEqual(COMPAT_IMAGE_DOMAINS, list(IMAGE_DOMAINS))
        self.assertEqual(API_DOMAIN_SERVER_URLS, list(API_DOMAIN_DISCOVERY_URLS))
