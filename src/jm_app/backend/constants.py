"""Compatibility exports for browser-facing defaults."""

from .jm_endpoints import WEB_BASE_URL, WEB_DOMAINS, WEB_LIST_URL


BASE_URL = WEB_BASE_URL
LIST_URL = WEB_LIST_URL
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
