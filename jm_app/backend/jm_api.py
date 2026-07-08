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

import requests
from Crypto.Cipher import AES
from PIL import Image

from .models import AlbumMeta, ChapterMeta, NetworkConfig
from .utils import safe_name


API_DOMAINS = [
    "www.cdnhjk.net",
    "www.cdngwc.cc",
    "www.cdngwc.net",
    "www.cdngwc.club",
    "www.cdnhjk.cc",
    "www.cdnutc.me",
]

IMAGE_DOMAINS = [
    "cdn-msp.jmapiproxy1.cc",
    "cdn-msp.jmapiproxy2.cc",
    "cdn-msp2.jmapiproxy2.cc",
    "cdn-msp3.jmapiproxy2.cc",
    "cdn-msp.jmapinodeudzn.net",
    "cdn-msp3.jmapinodeudzn.net",
]

API_DOMAIN_SERVER_URLS = [
    "https://rup4a04-c01.tos-ap-southeast-1.bytepluses.com/newsvr-2025.txt",
    "https://rup4a04-c02.tos-cn-hongkong.bytepluses.com/newsvr-2025.txt",
]

APP_VERSION = "2.0.21"
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


def _dedupe_domains(domains: Iterable[str]) -> List[str]:
    result = []
    seen = set()
    for domain in domains:
        value = str(domain or "").strip().strip("/")
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def get_latest_api_domains(log_callback=None, session: Optional[requests.Session] = None, force: bool = False) -> List[str]:
    global _LATEST_API_DOMAINS, _LATEST_API_DOMAINS_TS
    now = time.time()
    if not force and _LATEST_API_DOMAINS and now - _LATEST_API_DOMAINS_TS < 1800:
        return list(_LATEST_API_DOMAINS)

    requester = session or requests.Session()
    for url in API_DOMAIN_SERVER_URLS:
        try:
            response = requester.get(url, timeout=(6, 12))
            response.raise_for_status()
            text = _trim_leading_non_ascii(response.text)
            decoded = decode_response_data(text, "", API_DOMAIN_SERVER_SECRET)
            payload = json.loads(decoded)
            domains = _dedupe_domains((payload.get("Server") or []) + (payload.get("Setting") or []))
            if domains:
                merged = _dedupe_domains(domains + API_DOMAINS)
                _LATEST_API_DOMAINS = merged
                _LATEST_API_DOMAINS_TS = now
                if log_callback:
                    log_callback(f"已更新 API 域名池：{', '.join(domains[:5])}")
                return merged
        except Exception as exc:
            if log_callback:
                log_callback(f"最新域名获取失败：{url}，{exc}")
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
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return re.split(r"[\s,]+", text) if text else []


def _int(value, fallback: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return fallback


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
        save_kwargs = {"quality": 96, "subsampling": 0, "optimize": True}
    elif suffix == ".webp":
        save_kwargs = {"quality": 96, "method": 6}
    image.save(save_path, **save_kwargs)
    image.close()


class JmApiClient:
    def __init__(self, config: NetworkConfig, log_callback=None, cancel_event=None):
        self.config = config
        self.log_callback = log_callback
        self.cancel_event = cancel_event or threading.Event()
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": APP_USER_AGENT})
        if config.proxy.strip():
            proxies = [item.strip() for item in re.split(r"[,;\s]+", config.proxy.strip()) if item.strip()]
            proxy = random.choice(proxies)
            self.session.proxies.update({"http": proxy, "https": proxy})
            self.log(f"已启用代理：{proxy}" + (f"（代理池 {len(proxies)} 个）" if len(proxies) > 1 else ""))
        self._api_domains = list(API_DOMAINS)
        self._image_domains = list(IMAGE_DOMAINS)
        self._domains_initialized = False
        self._scramble_cache: Dict[str, str] = {}

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def search(self, query: str, page: int = 1, main_tag: int = 0) -> List[AlbumMeta]:
        data = self._api_get(
            "/search",
            {
                "main_tag": str(main_tag),
                "search_query": query,
                "page": str(max(1, page)),
                "o": "mr",
                "t": "a",
            },
        )
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
        data = self._api_get("/categories/filter", params)
        albums = self._parse_album_items(data.get("content"), ranked=True)
        if not albums and fallback_params:
            data = self._api_get("/categories/filter", fallback_params)
            albums = self._parse_album_items(data.get("content"), ranked=True)
        return albums

    def category(self, category: str, page: int = 1, order_by: str = "mr") -> List[AlbumMeta]:
        params = {
            "page": str(max(1, page)),
            "order": "",
            "c": self.normalize_category(category),
            "o": order_by or "mr",
        }
        data = self._api_get("/categories/filter", params)
        return self._parse_album_items(data.get("content"), ranked=False)

    @staticmethod
    def normalize_category(category: str) -> str:
        key = str(category or "").strip()
        return CATEGORY_ALIASES.get(key, key or "0")

    def get_album_detail(self, album_id: str) -> AlbumMeta:
        album_id = parse_jm_id(album_id)
        data = self._api_get("/album", {"id": album_id})
        title = str(data.get("name") or "").strip()
        if not title:
            raise RuntimeError(f"未找到本子详情: {album_id}")
        chapters = self._parse_chapters(data.get("series"), album_id, title)
        page_count = len(data.get("images") or [])
        if page_count == 0:
            page_count = self._count_album_pages(chapters)
        author = next(iter(_string_list(data.get("author"))), "-")
        tags = _string_list(data.get("tags"))
        likes = str(data.get("likes") or "0")
        return AlbumMeta(
            album_id=str(data.get("id") or album_id),
            title=safe_name(title, f"JM{album_id}"),
            url=f"jm://album/{album_id}",
            likes=likes,
            favorites="-",
            source="API",
            cover_url=self.cover_url(album_id),
            author=author,
            page_count=f"{page_count} 页" if page_count else "-",
            tags=tags,
            chapters=chapters,
        )

    def _count_album_pages(self, chapters: List[ChapterMeta]) -> int:
        total = 0
        for chapter in chapters:
            if self.cancel_event.is_set():
                break
            try:
                data = self._api_get("/chapter", {"id": parse_jm_id(chapter.chapter_id)})
                total += len(data.get("images") or [])
            except Exception as exc:
                self.log(f"页数获取失败 {chapter.chapter_id}：{exc}")
        return total

    def get_photo_detail(
        self,
        photo_id: str,
        album: Optional[AlbumMeta] = None,
        fetch_scramble: bool = True,
    ) -> PhotoDetail:
        photo_id = parse_jm_id(photo_id)
        data = self._api_get("/chapter", {"id": photo_id})
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
        return f"https://{self._image_domains[0]}/media/albums/{parse_jm_id(album_id)}.jpg"

    def build_image_urls(self, photo: PhotoDetail, image_name: str) -> Iterable[str]:
        yield f"https://{photo.image_domain}/media/photos/{photo.photo_id}/{image_name}"
        for domain in self._image_domains:
            if domain != photo.image_domain:
                yield f"https://{domain}/media/photos/{photo.photo_id}/{image_name}"

    def download_image(self, url: str, save_path: Path, scramble_id: str, progress_callback=None):
        response = self._request(
            "GET",
            url,
            headers=self._image_headers(),
            stream=True,
            timeout=(10, 60),
            retry_wait_cap=10,
        )
        chunks = []
        for chunk in response.iter_content(chunk_size=64 * 1024):
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

        match = re.search(r"/media/photos/(\d+)/", url_path)
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
            "app_img_shunt": "1",
            "express": "off",
            "v": str(self._timestamp()),
        }
        path = self._append_query("/chapter_view_template", params)
        ts = str(self._timestamp())
        token, token_param = token_and_param(ts, APP_TOKEN_SECRET_CONTENT)
        last_error: Optional[Exception] = None
        for domain in self._get_api_domains():
            try:
                response = self._request(
                    "GET",
                    "https://" + domain + path,
                    headers=self._api_headers(token, token_param),
                    timeout=(6, 16),
                    retries=0,
                )
                match = SCRAMBLE_RE.search(response.text)
                scramble_id = match.group(1) if match else "220980"
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
                    timeout=(6, 16),
                    retries=0,
                )
                payload = self._parse_json_object(response.text)
                if _int(payload.get("code")) != 200:
                    raise RuntimeError(f"JM API 返回错误: {response.text}")
                encoded = str(payload.get("data") or "")
                if not encoded:
                    raise RuntimeError("JM API 返回空 data")
                return json.loads(decode_response_data(encoded, ts))
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"JM API 请求失败: {path}: {last_error}")

    def _get_api_domains(self) -> List[str]:
        if self._domains_initialized:
            return self._api_domains
        self._api_domains = get_latest_api_domains(self.log, self.session)
        self._domains_initialized = True
        return self._api_domains

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
            album_id = str(item.get("id") or "").strip()
            if not album_id:
                continue
            title = str(item.get("name") or album_id)
            result.append(
                AlbumMeta(
                    album_id=album_id,
                    title=safe_name(title, album_id),
                    url=f"jm://album/{album_id}",
                    likes=f"#{index}" if ranked else "-",
                    favorites="-",
                    source="API",
                    cover_url=self.cover_url(album_id),
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
