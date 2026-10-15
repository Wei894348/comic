import base64
import hashlib
import json
import random
import re
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

import requests
from Crypto.Cipher import AES
from PIL import Image

from .cookie_store import save_cookie_dict
from .jm_endpoints import (
    API_DOMAIN_DISCOVERY_URLS,
    API_DOMAINS as DEFAULT_API_DOMAINS,
    API_PATHS,
    IMAGE_DOMAINS as DEFAULT_IMAGE_DOMAINS,
    MEDIA_PHOTOS_PATH,
    album_cover_path,
    https_url,
    photo_image_path,
    user_media_path,
)
from .models import AlbumMeta, ChapterMeta, NetworkConfig
from .network_session import create_network_session, select_proxy
from .utils import dedupe_domains, parse_cookie_header, safe_name


# Mutable lists remain as compatibility exports for existing callers.  Their
# values are owned by jm_endpoints.py.
API_DOMAINS = list(DEFAULT_API_DOMAINS)
IMAGE_DOMAINS = list(DEFAULT_IMAGE_DOMAINS)
API_DOMAIN_SERVER_URLS = list(API_DOMAIN_DISCOVERY_URLS)

APP_VERSION = "2.0.26"
APP_TOKEN_SECRET = "18comicAPP"
APP_TOKEN_SECRET_CONTENT = "18comicAPPContent"
APP_DATA_SECRET = "185Hcomic3PAPP7R"
API_DOMAIN_SERVER_SECRET = "diosfjckwpqpdfjkvnqQjsik"

APP_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 9; V1938CT Build/PQ3A.190705.11211812; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/91.0.4472.114 Safari/537.36"
)

CATEGORY_ALIASES = {
    "0": "single",
    "1": "short",
    "2": "doujin",
    "3": "another",
    "4": "hanman",
    "5": "english_site",
    "6": "hanman",
    "all": "0",
    "doujin": "doujin",
    "single": "single",
    "short": "short",
    "another": "another",
    "hanman": "hanman",
    "meiman": "meiman",
    "english": "english_site",
    "english_site": "english_site",
    "cosplay": "doujin_cosplay",
    "doujin_cosplay": "doujin_cosplay",
    "3d": "3D",
    "3D": "3D",
}

SCRAMBLE_RE = re.compile(r"var\s+scramble_id\s*=\s*(\d+)")
_LATEST_API_DOMAINS: List[str] = []
_LATEST_API_DOMAINS_TS = 0.0


@dataclass
class PhotoDetail:
    photo_id: str
    album_id: str
    title: str
    sort: int
    scramble_id: str
    image_domain: str
    images: List[str]


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def token_and_param(ts: str, secret: str = APP_TOKEN_SECRET):
    return md5_hex(ts + secret), f"{ts},{APP_VERSION}"


def decode_response_data(data: str, ts: str, secret: str = APP_DATA_SECRET) -> str:
    encrypted = base64.b64decode(data)
    key = md5_hex(ts + secret).encode("utf-8")
    decrypted = AES.new(key, AES.MODE_ECB).decrypt(encrypted)
    if not decrypted:
        return ""
    padding = decrypted[-1]
    if padding < 1 or padding > 16 or padding > len(decrypted):
        raise RuntimeError(f"无效的 PKCS7 padding: {padding}")
    return decrypted[:-padding].decode("utf-8")


def get_latest_api_domains(log_callback=None, session: Optional[requests.Session] = None, force: bool = False) -> List[str]:
    global _LATEST_API_DOMAINS, _LATEST_API_DOMAINS_TS
    now = time.time()
    if not force and _LATEST_API_DOMAINS and now - _LATEST_API_DOMAINS_TS < 1800:
        return list(_LATEST_API_DOMAINS)

    owns_session = session is None
    requester = session or create_network_session(APP_USER_AGENT)
    try:
        for url in API_DOMAIN_SERVER_URLS:
            try:
                response = requester.get(url, timeout=(4, 8))
                response.raise_for_status()
                text = _trim_leading_non_ascii(response.text)
                decoded = decode_response_data(text, "", API_DOMAIN_SERVER_SECRET)
                payload = json.loads(decoded)
                domains = dedupe_domains((payload.get("Server") or []) + (payload.get("Setting") or []))
                if domains:
                    merged = dedupe_domains(domains + API_DOMAINS)
                    _LATEST_API_DOMAINS = merged
                    _LATEST_API_DOMAINS_TS = now
                    if log_callback:
                        log_callback(f"已更新 API 域名池：{', '.join(domains[:5])}")
                    return merged
            except Exception as exc:
                if log_callback:
                    log_callback(f"最新域名获取失败：{url}，{exc}")
    finally:
        if owns_session:
            requester.close()
    return list(_LATEST_API_DOMAINS or API_DOMAINS)


def parse_jm_id(value: str) -> str:
    text = (value or "").strip()
    if text.lower().startswith("jm"):
        text = text[2:]
    match = re.search(r"(?:photos?|albums?)/(\d+)|id=(\d+)|(\d+)", text)
    if not match:
        raise ValueError(f"无法解析 JM ID: {value}")
    for group in match.groups():
        if group:
            return group
    raise ValueError(f"无法解析 JM ID: {value}")


def _string_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        for key in ("title", "name", "tag", "text", "label", "category"):
            if value.get(key) not in (None, ""):
                return _string_list(value[key])
        return []
    if isinstance(value, (list, tuple, set)):
        result: List[str] = []
        for item in value:
            result.extend(_string_list(item))
        return result
    text = str(value).strip()
    return [item.strip() for item in re.split(r"[,，\r\n]+", text) if item.strip()] if text else []


def _int(value, fallback: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return fallback


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _trim_leading_non_ascii(text: str) -> str:
    index = 0
    while index < len(text) and ord(text[index]) > 127:
        index += 1
    return text[index:]


def image_segment_count(scramble_id: str, aid: str, file_stem: str) -> int:
    try:
        scramble = int(scramble_id)
        photo_id = int(aid)
    except Exception:
        return 0
    if photo_id < scramble:
        return 0
    if photo_id < 268850:
        return 10
    x = 10 if photo_id < 421926 else 8
    value = ord(md5_hex(str(photo_id) + file_stem)[-1]) % x
    return value * 2 + 2


def decode_image_bytes(image_bytes: bytes, segments: int, save_path: Path):
    with Image.open(BytesIO(image_bytes)) as source:
        image = source.copy()

    if segments > 0:
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")
        width, height = image.size
        decoded = Image.new(image.mode, image.size)
        base = height // segments
        over = height % segments
        for index in range(segments):
            move = base
            source_y = height - (base * (index + 1)) - over
            dest_y = base * index
            if index == 0:
                move += over
            else:
                dest_y += over
            box = (0, source_y, width, source_y + move)
            decoded.paste(image.crop(box), (0, dest_y))
        image.close()
        image = decoded

    suffix = save_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"} and image.mode != "RGB":
        image = image.convert("RGB")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_kwargs = {}
    if suffix in {".jpg", ".jpeg"}:
        # Scrambled pages must be re-encoded after strip restoration. Avoid
        # Pillow's expensive optimize pass; it saves little on comic artwork
        # and otherwise becomes the bottleneck once downloads are parallel.
        save_kwargs = {"quality": 96, "subsampling": 0}
    elif suffix == ".webp":
        save_kwargs = {"quality": 96, "method": 4}
    image.save(save_path, **save_kwargs)
    image.close()


class JmApiClient:
    def __init__(self, config: NetworkConfig, log_callback=None, cancel_event=None):
        self.config = config
        self.log_callback = log_callback
        self.cancel_event = cancel_event or threading.Event()
        self.proxy = select_proxy(config.proxy)
        self.session = create_network_session(
            APP_USER_AGENT,
            self.proxy,
            config.doh_enabled,
            config.doh_url,
        )
        # Cookie 登录是 Comic18 的默认登录方式。旧版 JMComic-qt 会在每个
        # 请求会话中恢复 Cookie；不恢复的话收藏、评论和观看记录会变成匿名请求。
        if config.cookie_header.strip():
            self.session.cookies.update(parse_cookie_header(config.cookie_header))
        if self.proxy:
            proxies = [item.strip() for item in re.split(r"[,;\s]+", config.proxy.strip()) if item.strip()]
            self.log(f"已启用代理：{self.proxy}" + (f"（代理池 {len(proxies)} 个）" if len(proxies) > 1 else ""))
        custom_image = str(config.custom_image_domain or "").strip().replace("https://", "").replace("http://", "").strip("/")
        self._api_domains = dedupe_domains(list(API_DOMAINS))
        self._image_domains = dedupe_domains(list(IMAGE_DOMAINS))
        image_route = max(0, int(getattr(config, "image_route", 0) or 0))
        if custom_image and image_route == 0:
            self._image_domains.insert(0, custom_image)
        elif self._image_domains and image_route:
            offset = (image_route - 1) % len(self._image_domains)
            self._image_domains = self._image_domains[offset:] + self._image_domains[:offset]
        self._domains_initialized = False
        self._scramble_cache: Dict[str, str] = {}

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def login(self, username: str, password: str) -> Dict:
        username = (username or "").strip()
        if not username:
            raise ValueError("请输入账号")
        if not password:
            raise ValueError("请输入密码")

        result = self._api_post(API_PATHS.login, {"username": username, "password": password})
        cookies = self.session.cookies.get_dict()
        if cookies:
            save_cookie_dict(cookies)
        return {"user": result, "cookies": cookies}

    def get_daily(self, user_id: str) -> Dict:
        user_id = str(user_id or "").strip()
        if not user_id:
            raise ValueError("缺少用户 ID，无法查询签到状态")
        return self._api_get(API_PATHS.daily, {"user_id": user_id})

    def sign_daily(self, user_id: str, daily_id) -> Dict:
        user_id = str(user_id or "").strip()
        daily_id = str(daily_id or "").strip()
        if not user_id or not daily_id:
            raise ValueError("缺少签到参数")
        return self._api_post(API_PATHS.daily_check, {"user_id": user_id, "daily_id": daily_id})

    def auto_sign_daily(self, user_id: str) -> Dict:
        daily = self.get_daily(user_id)
        today = time.localtime().tm_mday
        signed_today = False
        for week in daily.get("record") or []:
            if not isinstance(week, list):
                continue
            for item in week:
                if not isinstance(item, dict):
                    continue
                try:
                    day = int(item.get("date"))
                except Exception:
                    continue
                if day == today:
                    signed_today = bool(item.get("signed"))
                    break
            if signed_today:
                break
        if signed_today:
            return {"ok": True, "already_signed": True, "daily": daily}
        sign_result = self.sign_daily(user_id, daily.get("daily_id"))
        return {"ok": True, "already_signed": False, "daily": daily, "sign": sign_result}

    def favorite_page(self, page: int = 1, sort: str = "mr", folder_id: str = "0") -> tuple[List[AlbumMeta], int, List[Dict[str, str]]]:
        data = self._api_get(
            API_PATHS.favorite,
            {
                "page": str(max(1, page)),
                "folder_id": str(folder_id or "0"),
                "o": sort or "mr",
            },
        )
        folders = []
        for item in data.get("folder_list") or []:
            if not isinstance(item, dict):
                continue
            folder_id_value = str(item.get("FID") or item.get("id") or item.get("folder_id") or "").strip()
            name = str(item.get("name") or item.get("folder_name") or "").strip()
            if folder_id_value and name:
                folders.append({"id": folder_id_value, "name": name})
        albums = self._parse_album_items(data.get("content") or data.get("list"), ranked=False)
        return albums, _int(data.get("total"), len(albums)), folders

    def favorite_albums(self, page: int = 1, sort: str = "mr", folder_id: str = "0") -> List[AlbumMeta]:
        albums, _total, _folders = self.favorite_page(page=page, sort=sort, folder_id=folder_id)
        return albums

    def favorite_albums_all(self, sort: str = "mr", folder_id: str = "0", max_pages: int = 100) -> List[AlbumMeta]:
        result: List[AlbumMeta] = []
        seen = set()
        for page in range(1, max(1, max_pages) + 1):
            albums = self.favorite_albums(page=page, sort=sort, folder_id=folder_id)
            if not albums:
                break
            added = False
            for album in albums:
                if album.album_id in seen:
                    continue
                seen.add(album.album_id)
                result.append(album)
                added = True
            if not added:
                break
        return result

    def toggle_favorite(self, album_id: str) -> Dict:
        return self._api_post(API_PATHS.favorite, {"aid": parse_jm_id(album_id)})

    def create_favorite_folder(self, name: str) -> Dict:
        name = str(name or "").strip()
        if not name:
            raise ValueError("收藏夹名称不能为空")
        return self._api_post(API_PATHS.favorite_folder, {"folder_name": name, "type": "add"})

    def delete_favorite_folder(self, folder_id: str) -> Dict:
        folder_id = str(folder_id or "").strip()
        if not folder_id or folder_id == "0":
            raise ValueError("请选择要删除的收藏夹")
        return self._api_post(API_PATHS.favorite_folder, {"folder_id": folder_id, "type": "del"})

    def move_favorite(self, album_id: str, folder_id: str) -> Dict:
        return self._api_post(
            API_PATHS.favorite_folder,
            {"folder_id": str(folder_id or "0"), "type": "move", "aid": parse_jm_id(album_id)},
        )

    def watch_history_albums(self, page: int = 1) -> tuple[List[AlbumMeta], int]:
        data = self._api_get(API_PATHS.watch_list, {"page": str(max(1, page))})
        albums = self._parse_album_items(data.get("list") or data.get("content"), ranked=False)
        return albums, _int(data.get("total"), len(albums))

    def watch_history_all(self, max_pages: int = 100) -> List[AlbumMeta]:
        result: List[AlbumMeta] = []
        seen = set()
        total = 0
        for page in range(1, max(1, max_pages) + 1):
            albums, total = self.watch_history_albums(page)
            if not albums:
                break
            for album in albums:
                if album.album_id in seen:
                    continue
                seen.add(album.album_id)
                result.append(album)
            if total and len(result) >= total:
                break
        return result

    def forum_comments(self, album_id: str = "", page: int = 1, user_id: str = "") -> tuple[List[Dict], int]:
        params = {"mode": "undefined" if user_id else "manhua", "page": str(max(1, page))}
        if album_id:
            params["aid"] = parse_jm_id(album_id)
        if user_id:
            params["uid"] = str(user_id)
        data = self._api_get(API_PATHS.forum, params)
        comments = data.get("list") or data.get("content") or data.get("comments") or []
        return [dict(item) for item in comments if isinstance(item, dict)], _int(data.get("total"), len(comments))

    def post_comment(self, album_id: str, comment: str, comment_id: str = "") -> Dict:
        comment = str(comment or "").strip()
        if not comment:
            raise ValueError("评论内容不能为空")
        data = {"aid": parse_jm_id(album_id), "comment": comment}
        if comment_id:
            data["comment_id"] = str(comment_id)
        return self._api_post(API_PATHS.comment, data)

    def user_avatar_urls(self, user_id: str, photo: str = "") -> List[str]:
        user_id = str(user_id or "").strip()
        photo = str(photo or "").strip()
        if not user_id and not photo:
            return []
        direct_urls: List[str] = []
        paths: List[str] = []
        if photo:
            parsed = urlparse(photo)
            if parsed.scheme and parsed.netloc:
                direct_urls.append(photo)
                photo = parsed.path
            if photo:
                photo_name = photo.rsplit("/", 1)[-1]
                if photo_name:
                    paths.append(user_media_path(photo_name))
        if user_id:
            paths.append(user_media_path(f"{user_id}.jpg"))
        urls = direct_urls + [
            https_url(domain, path)
            for path in dict.fromkeys(paths)
            for domain in self._image_domains
        ]
        return list(dict.fromkeys(urls))

    def search(self, query: str, page: int = 1, main_tag: int = 0) -> List[AlbumMeta]:
        # Keep the App API shape used by JMComic-qt.  The older web-only
        # main_tag/t fields cause some current mirrors to return an empty list.
        params = {"search_query": query, "o": "mr"}
        if page > 1:
            params["page"] = str(page)
        data = self._api_get(API_PATHS.search, params)
        redirect_id = str(data.get("redirect_aid") or "").strip()
        if redirect_id:
            return [self.get_album_detail(redirect_id)]
        return self._parse_album_items(data.get("content"), ranked=False)

    def ranking(self, rank_type: str = "day", page: int = 1, category: str = "") -> List[AlbumMeta]:
        if rank_type == "week":
            params = {"page": str(max(1, page)), "order": "", "c": "0", "o": "mv_w"}
            fallback_params = {"page": str(max(1, page)), "order": "mv_w", "c": "0", "o": ""}
        elif rank_type == "month":
            params = {"page": str(max(1, page)), "order": "", "c": "0", "o": "mv_m"}
            fallback_params = None
        else:
            params = {"page": str(max(1, page)), "order": "", "c": "0", "o": "mv_t"}
            fallback_params = {"page": str(max(1, page)), "order": "mv_t", "c": "0", "o": ""}
        if category:
            params["c"] = self.normalize_category(category)
            if fallback_params:
                fallback_params["c"] = params["c"]
        data = self._api_get(API_PATHS.category_filter, params)
        albums = self._parse_album_items(data.get("content"), ranked=True)
        if not albums and fallback_params:
            data = self._api_get(API_PATHS.category_filter, fallback_params)
            albums = self._parse_album_items(data.get("content"), ranked=True)
        return albums

    def category(self, category: str, page: int = 1, order_by: str = "mr") -> List[AlbumMeta]:
        params = {
            "c": self.normalize_category(category),
            "o": order_by or "mr",
        }
        if page > 1:
            params["page"] = str(page)
        data = self._api_get(API_PATHS.category_filter, params)
        return self._parse_album_items(data.get("content"), ranked=False)

    def promote(self, page: int = 1) -> List[AlbumMeta]:
        albums: List[AlbumMeta] = []
        for section_albums in self.promote_sections(page).values():
            albums.extend(section_albums)
        return albums

    def promote_sections(self, page: int = 1) -> Dict[str, List[AlbumMeta]]:
        data = self._api_get(API_PATHS.promote, {"page": str(max(0, page - 1))})
        sections = data if isinstance(data, list) else (data.get("content") or data.get("list") or [])
        result: Dict[str, List[AlbumMeta]] = {}
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_title = str(section.get("title") or section.get("name") or "首页推荐")
            items = section.get("content") or section.get("list") or section.get("albums") or []
            albums: List[AlbumMeta] = []
            seen = set()
            for album in self._parse_album_items(items, ranked=False):
                if album.album_id in seen:
                    continue
                seen.add(album.album_id)
                album.source = section_title
                albums.append(album)
            if albums:
                result[section_title] = albums
        return result

    def promote_section(self, section_prefix: str, page: int = 1) -> List[AlbumMeta]:
        prefix = str(section_prefix or "").strip()
        sections = self.promote_sections(page)
        if not prefix:
            return [album for albums in sections.values() for album in albums]
        normalized_prefix = re.sub(r"\s+", "", prefix).lower()
        for title, albums in sections.items():
            normalized_title = re.sub(r"\s+", "", title).lower()
            if normalized_title.startswith(normalized_prefix):
                return albums
        return []

    def latest(self, page: int = 0) -> List[AlbumMeta]:
        data = self._api_get(API_PATHS.latest, {"page": str(max(0, page))})
        content = data if isinstance(data, list) else (data.get("content") or data.get("list") or [])
        return self._parse_album_items(content, ranked=False)

    def week_categories(self) -> List[Dict]:
        data = self._api_get(API_PATHS.week, {"page": "0"})
        return [dict(item) for item in (data.get("categories") or []) if isinstance(item, dict)]

    def week_filter(self, category_id: str, category_type: str = "manga", page: int = 0) -> List[AlbumMeta]:
        data = self._api_get(
            API_PATHS.week_filter,
            {"id": str(category_id), "type": str(category_type or "manga"), "page": str(max(0, page))},
        )
        return self._parse_album_items(data.get("list") or data.get("content"), ranked=False)

    @staticmethod
    def normalize_category(category: str) -> str:
        key = str(category or "").strip()
        return CATEGORY_ALIASES.get(key, key or "0")

    def get_album_detail(self, album_id: str) -> AlbumMeta:
        album_id = parse_jm_id(album_id)
        data = self._api_get(API_PATHS.album, {"comicName": "", "id": album_id})
        title = str(data.get("name") or "").strip()
        if not title:
            raise RuntimeError(f"未找到本子详情: {album_id}")
        chapters = self._parse_chapters(data.get("series"), album_id, title)
        page_count = len(data.get("images") or [])
        author = ", ".join(_string_list(data.get("author"))) or "-"
        tags = _string_list(data.get("tags"))
        likes = str(data.get("likes") or "0")
        description = str(data.get("description") or "").strip()
        views = str(data.get("total_views") or "-")
        comment_count = str(data.get("comment_total") or "0")
        return AlbumMeta(
            album_id=str(data.get("id") or album_id),
            title=safe_name(title, f"JM{album_id}"),
            url=f"jm://album/{album_id}",
            likes=likes,
            favorites="-",
            source="API",
            cover_url=self.cover_url(str(data.get("id") or album_id)),
            author=author,
            page_count=f"{page_count} 页" if page_count else "-",
            description=description,
            views=views,
            comment_count=comment_count,
            is_favorite=_bool(data.get("is_favorite") if "is_favorite" in data else data.get("isFavorite")),
            tags=tags,
            chapters=chapters,
        )

    def get_photo_detail(
        self,
        photo_id: str,
        album: Optional[AlbumMeta] = None,
        fetch_scramble: bool = True,
    ) -> PhotoDetail:
        photo_id = parse_jm_id(photo_id)
        data = self._api_get(API_PATHS.chapter, {"comicName": "", "skip": "", "id": photo_id})
        album_id = str(data.get("series_id") or "").strip()
        if not album_id or album_id == "0":
            album_id = photo_id
        title = str(data.get("name") or photo_id)
        sort = self._photo_sort(data.get("series"), photo_id)
        scramble_id = self.get_scramble_id(photo_id, album_id) if fetch_scramble else ""
        if not scramble_id and album is not None:
            scramble_id = "220980"
        return PhotoDetail(
            photo_id=photo_id,
            album_id=album_id,
            title=safe_name(title, photo_id),
            sort=sort,
            scramble_id=scramble_id,
            image_domain=random.choice(self._image_domains),
            images=_string_list(data.get("images")),
        )

    def photo_as_album(self, photo_id: str) -> AlbumMeta:
        photo = self.get_photo_detail(photo_id)
        chapter = ChapterMeta(
            chapter_id=photo.photo_id,
            title=photo.title,
            url=f"jm://photo/{photo.photo_id}",
            index=1,
        )
        return AlbumMeta(
            album_id="p" + photo.photo_id,
            title=photo.title,
            url=f"jm://photo/{photo.photo_id}",
            likes="-",
            favorites="-",
            source="API",
            page_count=f"{len(photo.images)} 页",
            chapters=[chapter],
        )

    def cover_url(self, album_id: str) -> str:
        # Spread the initially visible homepage cards across the available
        # image CDNs.  Pointing every card at index 0 makes a single slow
        # route stall the complete first screen.  The cover UI still promotes
        # a successful route for later requests, while this deterministic
        # selection gives the initial lazy queue the same independent-task
        # behavior as JMComic-qt's ComicItemWidget downloader.
        numeric_id = parse_jm_id(album_id)
        try:
            domain = self._image_domains[int(numeric_id) % len(self._image_domains)]
        except (ValueError, ZeroDivisionError):
            domain = self._image_domains[0]
        return https_url(domain, album_cover_path(numeric_id))

    def build_image_urls(self, photo: PhotoDetail, image_name: str) -> Iterable[str]:
        path = photo_image_path(photo.photo_id, image_name)
        yield https_url(photo.image_domain, path)
        for domain in self._image_domains:
            if domain != photo.image_domain:
                yield https_url(domain, path)

    def download_image(self, url: str, save_path: Path, scramble_id: str, progress_callback=None):
        response = self._request(
            "GET",
            url,
            headers=self._image_headers(),
            stream=True,
            timeout=(8, 25),
            retry_wait_cap=5,
        )
        chunks = []
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if self.cancel_event.is_set():
                raise RuntimeError("下载已取消")
            if not chunk:
                continue
            chunks.append(chunk)
            if progress_callback:
                progress_callback(len(chunk))
        image_bytes = b"".join(chunks)
        if not image_bytes:
            raise RuntimeError(f"图片为空: {url}")

        url_path = url.split("?", 1)[0]
        if url_path.lower().endswith(".gif"):
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(image_bytes)
            return save_path.stat().st_size

        match = re.search(rf"{re.escape(MEDIA_PHOTOS_PATH)}/(\d+)/", url_path)
        aid = match.group(1) if match else "0"
        stem = Path(url_path).stem
        segments = image_segment_count(scramble_id, aid, stem)
        if segments == 0 and save_path.suffix.lower() == Path(url_path).suffix.lower():
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(image_bytes)
            return save_path.stat().st_size
        decode_image_bytes(image_bytes, segments, save_path)
        return save_path.stat().st_size if save_path.exists() else 0

    def sleep(self):
        low = min(self.config.delay_min, self.config.delay_max)
        high = max(self.config.delay_min, self.config.delay_max)
        self.cancel_event.wait(random.uniform(low, high))

    def get_scramble_id(self, photo_id: str, album_id: Optional[str]) -> str:
        if album_id and album_id in self._scramble_cache:
            return self._scramble_cache[album_id]
        if photo_id in self._scramble_cache:
            return self._scramble_cache[photo_id]

        params = {
            "id": parse_jm_id(photo_id),
            "mode": "vertical",
            "page": "0",
            "app_img_shunt": "NaN",
        }
        path = self._append_query(API_PATHS.chapter_view_template, params)
        ts = str(self._timestamp())
        token, token_param = token_and_param(ts, APP_TOKEN_SECRET_CONTENT)
        last_error: Optional[Exception] = None
        for domain in self._get_api_domains():
            try:
                response = self._request(
                    "GET",
                    "https://" + domain + path,
                    headers=self._api_headers(token, token_param),
                    timeout=(4, 8),
                    retries=0,
                )
                match = SCRAMBLE_RE.search(response.text)
                scramble_id = match.group(1) if match else "220980"
                self._promote_api_domain(domain)
                self._scramble_cache[photo_id] = scramble_id
                if album_id:
                    self._scramble_cache[album_id] = scramble_id
                return scramble_id
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"获取 scramble_id 失败: {photo_id}: {last_error}")

    def _api_get(self, path: str, params: Dict[str, str]) -> Dict:
        query_path = self._append_query(path, params)
        ts = str(self._timestamp())
        token, token_param = token_and_param(ts)
        last_error: Optional[Exception] = None
        for domain in self._get_api_domains():
            try:
                response = self._request(
                    "GET",
                    "https://" + domain + query_path,
                    headers=self._api_headers(token, token_param),
                    timeout=(4, 8),
                    retries=0,
                )
                payload = self._parse_json_object(response.text)
                if _int(payload.get("code")) != 200:
                    raise RuntimeError(f"JM API 返回错误: {response.text}")
                encoded = str(payload.get("data") or "")
                if not encoded:
                    raise RuntimeError("JM API 返回空 data")
                self._promote_api_domain(domain)
                return json.loads(decode_response_data(encoded, ts))
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"JM API 请求失败: {path}: {last_error}")

    def _api_post(self, path: str, data: Dict[str, str]) -> Dict:
        ts = str(self._timestamp())
        token, token_param = token_and_param(ts)
        headers = self._api_headers(token, token_param)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        last_error: Optional[Exception] = None
        for domain in self._get_api_domains():
            try:
                response = self._request(
                    "POST",
                    "https://" + domain + path,
                    headers=headers,
                    data=data,
                    timeout=(4, 8),
                    retries=0,
                )
                payload = self._parse_json_object(response.text)
                if _int(payload.get("code")) != 200:
                    message = payload.get("errorMsg") or payload.get("message") or response.text
                    raise RuntimeError(str(message or "JM API returned an error"))
                encoded = str(payload.get("data") or "")
                if not encoded:
                    raise RuntimeError("JM API returned empty data")
                self._promote_api_domain(domain)
                return json.loads(decode_response_data(encoded, ts))
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"JM API request failed: {path}: {last_error}")

    def _get_api_domains(self) -> List[str]:
        if self._domains_initialized:
            return self._api_domains
        custom = str(getattr(self.config, "custom_api_domain", "") or "").strip()
        custom = custom.replace("https://", "").replace("http://", "").strip("/")
        self._api_domains = dedupe_domains(get_latest_api_domains(self.log, self.session))
        route = max(0, int(getattr(self.config, "api_route", 0) or 0))
        if custom and route == 0:
            self._api_domains.insert(0, custom)
        elif self._api_domains and route:
            offset = (route - 1) % len(self._api_domains)
            self._api_domains = self._api_domains[offset:] + self._api_domains[:offset]
        self._domains_initialized = True
        return self._api_domains

    def _promote_api_domain(self, domain: str) -> None:
        """Reuse the last responsive API host for subsequent page requests."""
        if domain in self._api_domains:
            self._api_domains = [domain] + [item for item in self._api_domains if item != domain]

    def _request(self, method: str, url: str, **kwargs):
        timeout = kwargs.pop("timeout", (8, 30))
        retries = kwargs.pop("retries", self.config.retries)
        retry_wait_cap = kwargs.pop("retry_wait_cap", 8)
        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 2):
            if self.cancel_event.is_set():
                raise RuntimeError("任务已取消")
            try:
                response = self.session.request(method, url, timeout=timeout, **kwargs)
                if response.status_code in {403, 429} and self.config.stop_on_block:
                    raise RuntimeError(f"HTTP {response.status_code}: {url}")
                response.raise_for_status()
                return response
            except Exception as exc:
                last_error = exc
                if attempt > retries:
                    break
                wait = min(self.config.backoff_seconds * attempt + random.uniform(0.5, 2.5), retry_wait_cap)
                self.log(f"请求失败，{wait:.1f}s 后重试：{exc}")
                self.cancel_event.wait(wait)
        raise RuntimeError(str(last_error))

    @staticmethod
    def _parse_json_object(text: str) -> Dict:
        trimmed = text.strip()
        if not trimmed.startswith("{"):
            start = trimmed.find("{")
            end = trimmed.rfind("}")
            if start >= 0 and end > start:
                trimmed = trimmed[start : end + 1]
        return json.loads(trimmed)

    def _parse_album_items(self, content, ranked: bool) -> List[AlbumMeta]:
        result: List[AlbumMeta] = []
        if not isinstance(content, list):
            return result
        for index, item in enumerate(content, start=1):
            if not isinstance(item, dict):
                continue
            album_id = str(item.get("id") or item.get("album_id") or item.get("aid") or "").strip()
            if not album_id:
                continue
            title = str(item.get("name") or item.get("title") or album_id)
            # JMComic-qt intentionally ignores feed-provided cover paths and
            # always requests this canonical portrait album artwork.
            cover_url = self.cover_url(album_id)
            category_tags = []
            seen_tags = set()
            # Different home/category feeds use tags, a tag list, or one/two
            # category fields.  Preserve the API order and remove duplicates.
            for key in ("tags", "tag_list", "tagList", "category", "category_sub"):
                for tag in _string_list(item.get(key)):
                    normalized_tag = tag.strip()
                    if normalized_tag and normalized_tag not in seen_tags:
                        seen_tags.add(normalized_tag)
                        category_tags.append(normalized_tag)
            result.append(
                AlbumMeta(
                    album_id=album_id,
                    title=safe_name(title, album_id),
                    url=f"jm://album/{album_id}",
                    likes=f"#{index}" if ranked else "-",
                    favorites="-",
                    source="API",
                    cover_url=cover_url,
                    author=", ".join(_string_list(item.get("author"))) or "-",
                    page_count=str(item.get("page_count") or item.get("pages") or "-"),
                    is_favorite=_bool(item.get("is_favorite") if "is_favorite" in item else item.get("isFavorite")),
                    tags=category_tags,
                )
            )
        return result

    @staticmethod
    def _parse_chapters(series, album_id: str, album_title: str) -> List[ChapterMeta]:
        chapters: List[ChapterMeta] = []
        if isinstance(series, list):
            for item in series:
                if not isinstance(item, dict):
                    continue
                chapter_id = str(item.get("id") or "").strip()
                if not chapter_id:
                    continue
                chapters.append(
                    ChapterMeta(
                        chapter_id=chapter_id,
                        title=safe_name(str(item.get("name") or album_title), chapter_id),
                        url=f"jm://photo/{chapter_id}",
                        index=_int(item.get("sort"), 1),
                    )
                )
        if not chapters:
            chapters.append(
                ChapterMeta(
                    chapter_id=album_id,
                    title=safe_name(album_title, album_id),
                    url=f"jm://photo/{album_id}",
                    index=1,
                )
            )
        by_sort: Dict[int, ChapterMeta] = {}
        for chapter in chapters:
            by_sort.setdefault(chapter.index, chapter)
        return [by_sort[key] for key in sorted(by_sort)]

    @staticmethod
    def _photo_sort(series, photo_id: str) -> int:
        if isinstance(series, list):
            for item in series:
                if isinstance(item, dict) and str(item.get("id")) == photo_id:
                    return _int(item.get("sort"), 1)
        return 1

    @staticmethod
    def _append_query(path: str, params: Dict[str, str]) -> str:
        from urllib.parse import urlencode

        return path + "?" + urlencode(params)

    @staticmethod
    def _timestamp() -> int:
        return int(time.time())

    @staticmethod
    def _api_headers(token: str, token_param: str) -> Dict[str, str]:
        return {
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": APP_USER_AGENT,
            "token": token,
            "tokenparam": token_param,
            "version": "v1.3.3",
        }

    @staticmethod
    def _image_headers() -> Dict[str, str]:
        return {
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": APP_USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "X-Requested-With": "com.JMComic3.app",
            "Referer": "https://" + API_DOMAINS[0],
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }
