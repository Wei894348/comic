"""Browser-like HTTP sessions used by JM API and image CDN workers."""

from __future__ import annotations

import random
import re
from typing import Any

import requests

# JMComic-qt exposes this resolver as its first DoH service. Keeping the
# HTTP session and diagnostics tool on the same resolver avoids route drift.
DOH_URL = "https://parse.jpacg.cc/parse"
DOH_FALLBACK_URLS = (
    "https://doh.pub/dns-query",
    "https://dot.pub/dns-query",
)

try:  # Keep a functional fallback for environments not yet upgraded.
    from curl_cffi import CurlHttpVersion, CurlOpt
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - exercised by minimal installations
    curl_requests = None


def select_proxy(value: str) -> str:
    """Choose one proxy from the UI's comma/space separated proxy pool."""
    candidates = [item.strip() for item in re.split(r"[,;\s]+", str(value or "")) if item.strip()]
    return random.choice(candidates) if candidates else ""


def create_network_session(
    user_agent: str = "",
    proxy: str = "",
    doh_enabled: bool = True,
    doh_url: str = DOH_URL,
) -> Any:
    """Create an HTTP/2 session with DoH, matching JMComic-qt's request path."""
    selected_proxy = select_proxy(proxy)
    if curl_requests is not None:
        try:
            options = {}
            if doh_enabled and str(doh_url or "").strip():
                options[CurlOpt.DOH_URL] = str(doh_url).strip()
            session = curl_requests.Session(
                impersonate="chrome110",
                http_version=CurlHttpVersion.V2_0,
                curl_options=options,
            )
        except Exception:
            session = requests.Session()
    else:
        session = requests.Session()

    system_proxy = selected_proxy == "system://"
    if hasattr(session, "trust_env"):
        session.trust_env = system_proxy
    if user_agent:
        session.headers.update({"User-Agent": user_agent})
    if selected_proxy and not system_proxy:
        session.proxies.update({"http": selected_proxy, "https": selected_proxy})
    return session
