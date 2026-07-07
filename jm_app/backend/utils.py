import re
from typing import Dict, List, Optional


def safe_name(text: str, fallback: str = "untitled") -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:120] or fallback


def parse_album_id(value: str) -> Optional[str]:
    value = value.strip()
    if value.isdigit():
        return value
    prefixed = re.fullmatch(r"[pP](\d+)", value)
    if prefixed:
        return prefixed.group(1)
    match = re.search(r"/(?:album|albums|photo)/(\d+)", value)
    return match.group(1) if match else None


def split_ids(text: str) -> List[str]:
    ids: List[str] = []
    for part in re.split(r"[\s,，;；]+", text.strip()):
        prefixed = re.fullmatch(r"[pP](\d+)", part.strip())
        if prefixed:
            value = "p" + prefixed.group(1)
            if value not in ids:
                ids.append(value)
            continue
        album_id = parse_album_id(part)
        if album_id and album_id not in ids:
            ids.append(album_id)
    return ids


def parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def looks_like_security_page(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "performing security verification",
        "verifies you are not a bot",
        "just a moment",
        "checking your browser",
        "security service",
        "cloudflare",
    ]
    return any(marker in lowered for marker in markers)
