"""Authoritative JM service domains, routes, and media URL builders.

Keep JM-facing network addresses in this module.  Other modules may retain
compatibility aliases, but should not duplicate endpoint strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


# Browser-facing web service.
WEB_BASE_URL = "https://18-comicblade.art"
WEB_DOMAINS = (
    "https://comic18j-yodo.net",
    "https://18comic.vip",
    "https://jmcomic.me",
    "https://18comic.tw",
    "https://jmcomic-zzz.org",
    "https://comic18j-robo.net",
    "https://comic18j-lodo.net",
)
WEB_LIST_PATH = "/albums/meiman"
WEB_LIST_URL = f"{WEB_BASE_URL}{WEB_LIST_PATH}"
PROFILE_WEB_BASE_URL = "https://comic18j-oomi.net"


# App API and image-CDN routing defaults.
API_DOMAINS = (
    "www.cdnhjk.net",
    "www.cdngwc.cc",
    "www.cdngwc.net",
    "www.cdngwc.club",
)
IMAGE_DOMAINS = (
    "cdn-msp.jmapiproxy1.cc",
    "cdn-msp.jmapiproxy3.cc",
    "cdn-msp.jmapinodeudzn.net",
    "cdn-msp.jmdanjonproxy.xyz",
)
API_DOMAIN_DISCOVERY_URLS = (
    "https://rup4a04-c01.tos-ap-southeast-1.bytepluses.com/newsvr-2025.txt",
)


@dataclass(frozen=True)
class JmApiPaths:
    """Paths exposed by the JM App API and chapter web fallback."""

    login: str = "/login"
    daily: str = "/daily"
    daily_check: str = "/daily_chk"
    favorite: str = "/favorite"
    favorite_folder: str = "/favorite_folder"
    watch_list: str = "/watch_list"
    forum: str = "/forum"
    comment: str = "/comment"
    search: str = "/search"
    category_filter: str = "/categories/filter"
    promote: str = "/promote"
    latest: str = "/latest"
    week: str = "/week"
    week_filter: str = "/week/filter"
    album: str = "/album"
    chapter: str = "/chapter"
    chapter_view_template: str = "/chapter_view_template"


API_PATHS = JmApiPaths()

MEDIA_ALBUMS_PATH = "/media/albums"
MEDIA_PHOTOS_PATH = "/media/photos"
MEDIA_USERS_PATH = "/media/users"


def album_cover_path(album_id: str, *, portrait: bool = True) -> str:
    suffix = "_3x4" if portrait else ""
    return f"{MEDIA_ALBUMS_PATH}/{str(album_id).strip()}{suffix}.jpg"


def photo_image_path(photo_id: str, image_name: str) -> str:
    return f"{MEDIA_PHOTOS_PATH}/{str(photo_id).strip()}/{str(image_name).lstrip('/')}"


def user_media_path(filename: str) -> str:
    name = str(filename or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    return f"{MEDIA_USERS_PATH}/{name}" if name else MEDIA_USERS_PATH


def https_url(domain: str, path: str) -> str:
    base = str(domain or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return f"{base}/{str(path or '').lstrip('/')}"


def profile_web_url(username: str = "") -> str:
    username = str(username or "").strip()
    path = f"/user/{quote(username, safe='')}" if username else API_PATHS.login
    return https_url(PROFILE_WEB_BASE_URL, path)
