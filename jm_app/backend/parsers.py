import re
from typing import Dict, List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import AlbumMeta, ChapterMeta
from .utils import parse_album_id, safe_name


def normalize_count(value: str) -> str:
    value = value.strip().replace(",", "")
    return value or "-"


def find_count(text: str, keywords: List[str]) -> str:
    text = re.sub(r"\s+", " ", text)
    number = r"([\d,.]+(?:\.\d+)?\s*(?:万|億|亿|k|K|m|M)?)"
    for keyword in keywords:
        patterns = [
            rf"{re.escape(keyword)}\s*[:：]?\s*{number}",
            rf"{re.escape(keyword)}[^\d]{{0,20}}{number}",
            rf"{number}\s*(?:个|次)?\s*{re.escape(keyword)}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = [group for group in match.groups() if group]
                if groups:
                    return normalize_count(groups[-1])
    return "-"


def extract_stats_from_text(text: str) -> Tuple[str, str]:
    likes = find_count(text, ["点赞", "喜歡", "喜欢", "Likes", "Like"])
    favorites = find_count(
        text,
        ["收藏数", "收藏", "Favorites", "Favorite", "Bookmarks", "Bookmark"],
    )
    return likes, favorites


def extract_stats_from_soup(soup: BeautifulSoup) -> Tuple[str, str]:
    like_candidates = []
    favorite_candidates = []
    for node in soup.find_all(True):
        names = " ".join(
            str(node.get(attr, "")) for attr in ["class", "id", "aria-label", "title"]
        )
        node_text = node.get_text(" ", strip=True)
        if re.search(r"like|点赞|喜欢|喜歡", names, re.I):
            like_candidates.append(names + " " + node_text)
        if re.search(r"favorite|fav|bookmark|收藏", names, re.I):
            favorite_candidates.append(names + " " + node_text)

    page_likes, page_favorites = extract_stats_from_text(soup.get_text(" ", strip=True))
    likes = find_count(
        " ".join(like_candidates),
        ["count", "num", "点赞", "喜欢", "喜歡", "Likes", "Like"],
    )
    favorites = find_count(
        " ".join(favorite_candidates),
        ["count", "num", "收藏数", "收藏", "Favorites", "Favorite", "Bookmarks", "Bookmark"],
    )
    return (
        likes if likes != "-" else page_likes,
        favorites if favorites != "-" else page_favorites,
    )


def cover_from_node(link) -> str:
    image = link.find("img")
    if not image:
        return ""
    src = (
        image.get("data-original")
        or image.get("data-src")
        or image.get("data-lazy-src")
        or image.get("src")
        or ""
    )
    return src


def title_from_album_node(link, parent) -> str:
    image = link.find("img")
    values = [
        link.get("title"),
        link.get("aria-label"),
        image.get("alt") if image else "",
        image.get("title") if image else "",
        link.get_text(" ", strip=True),
    ]
    for selector in [".title", ".video-title", ".album-title", "h3", "h4"]:
        node = parent.select_one(selector) if parent else None
        if node:
            values.append(node.get_text(" ", strip=True))
    for value in values:
        if value and value.strip():
            return safe_name(value.strip(), "未命名")
    return "未命名"


def parse_album_list(html: str, page_url: str) -> List[AlbumMeta]:
    soup = BeautifulSoup(html, "lxml")
    albums: Dict[str, AlbumMeta] = {}

    for link in soup.find_all("a", href=True):
        href = urljoin(page_url, link.get("href", ""))
        match = re.search(r"/(?:album|albums)/(\d+)(?:[/?#]|$)", urlparse(href).path)
        if not match:
            continue

        album_id = match.group(1)
        parent = link.find_parent(["article", "li", "div"])
        text = parent.get_text(" ", strip=True) if parent else link.get_text(" ", strip=True)
        likes, favorites = extract_stats_from_text(text)
        cover_url = urljoin(page_url, cover_from_node(link))
        albums.setdefault(
            album_id,
            AlbumMeta(
                album_id=album_id,
                title=title_from_album_node(link, parent),
                url=href,
                likes=likes,
                favorites=favorites,
                cover_url=cover_url,
            ),
        )

    return list(albums.values())


def parse_album_detail(html: str, page_url: str, fallback_id: str) -> AlbumMeta:
    soup = BeautifulSoup(html, "lxml")
    canonical = soup.select_one("link[rel='canonical'][href], meta[property='og:url'][content]")
    canonical_url = ""
    if canonical:
        canonical_url = canonical.get("href") or canonical.get("content") or ""
        canonical_url = urljoin(page_url, canonical_url)
    album_id = parse_album_id(canonical_url) or parse_album_id(page_url) or fallback_id
    title = ""
    cover_url = ""
    for selector in ["h1", ".book-name", ".album-title", ".title", "title"]:
        node = soup.select_one(selector)
        if node:
            title = node.get_text(" ", strip=True)
            break
    image = soup.select_one(".cover img, .album-cover img, .book-cover img, img")
    if image:
        cover_url = image.get("data-original") or image.get("data-src") or image.get("src") or ""
        cover_url = urljoin(page_url, cover_url)
    title = re.sub(r"\s*-\s*禁漫.*$", "", title).strip()
    likes, favorites = extract_stats_from_soup(soup)
    return AlbumMeta(
        album_id=album_id,
        title=safe_name(title, f"JM{album_id}"),
        url=page_url,
        likes=likes,
        favorites=favorites,
        source="详情",
        cover_url=cover_url,
        chapters=parse_chapters(html, page_url),
    )


def parse_chapters(html: str, page_url: str) -> List[ChapterMeta]:
    soup = BeautifulSoup(html, "lxml")
    links: Dict[str, ChapterMeta] = {}
    for link in soup.find_all("a", href=True):
        href = urljoin(page_url, link["href"])
        match = re.search(r"/photo/(\d+)(?:[/?#]|$)", urlparse(href).path)
        if not match:
            continue
        chapter_id = match.group(1)
        title = link.get("title") or link.get_text(" ", strip=True) or f"第 {len(links) + 1} 集"
        links.setdefault(
            chapter_id,
            ChapterMeta(
                chapter_id=chapter_id,
                title=safe_name(title, f"第 {len(links) + 1} 集"),
                url=href,
                index=len(links) + 1,
            ),
        )

    chapters = list(links.values())
    if not chapters:
        album_id = parse_album_id(page_url) or "album"
        chapters.append(
            ChapterMeta(
                chapter_id=album_id,
                title="全集",
                url=page_url,
                index=1,
            )
        )
    return chapters


def parse_image_links(html: str, page_url: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    images: List[str] = []
    for image in soup.find_all("img"):
        src = (
            image.get("data-original")
            or image.get("data-src")
            or image.get("data-lazy-src")
            or image.get("src")
        )
        if not src:
            continue
        full_url = urljoin(page_url, src)
        if re.search(r"\.(?:jpg|jpeg|png|webp|gif)(?:[?#]|$)", full_url, re.I):
            images.append(full_url)
    return list(dict.fromkeys(images))
