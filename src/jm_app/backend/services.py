import threading
from dataclasses import asdict
from typing import Dict, List, Optional

from .constants import DEFAULT_USER_AGENT
from .cookie_store import cookie_dict_to_header, load_cookie_header
from .jm_api import JmApiClient
from .jmcomic_defaults import jmcomic_default_cookie_header
from .models import AlbumMeta, NetworkConfig
from .schemas import NetworkSettings


def album_to_dict(album: AlbumMeta) -> Dict:
    return asdict(album)


def default_network_settings() -> NetworkSettings:
    return NetworkSettings(
        cookie_header=load_cookie_header() or jmcomic_default_cookie_header(),
        user_agent=DEFAULT_USER_AGENT,
    )


def network_config(settings: Optional[NetworkSettings] = None) -> NetworkConfig:
    source = settings or default_network_settings()
    return NetworkConfig(
        cookie_header=source.cookie_header or load_cookie_header() or jmcomic_default_cookie_header(),
        user_agent=source.user_agent or DEFAULT_USER_AGENT,
        delay_min=source.delay_min,
        delay_max=source.delay_max,
        retries=source.retries,
        backoff_seconds=source.backoff_seconds,
        stop_on_block=source.stop_on_block,
        username=source.username,
        password=source.password,
        proxy=source.proxy,
        detail_threads=source.detail_threads,
        api_route=source.api_route,
        image_route=source.image_route,
        doh_enabled=source.doh_enabled,
        doh_url=source.doh_url,
        custom_api_domain=source.custom_api_domain,
        custom_image_domain=source.custom_image_domain,
    )


def verify_login(settings: NetworkSettings) -> Dict:
    logs: List[str] = []
    cancel_event = threading.Event()
    config = network_config(settings)
    client = JmApiClient(config, logs.append, cancel_event)
    result = client.login(settings.username, settings.password)
    user = result.get("user") or {}
    uid = str(user.get("uid") or "")
    sign_result = {}
    if settings.auto_sign and uid:
        try:
            sign_result = client.auto_sign_daily(uid)
            if sign_result.get("already_signed"):
                logs.append("今日已签到。")
            else:
                logs.append("自动签到完成。")
        except Exception as exc:
            sign_result = {"ok": False, "error": str(exc)}
            logs.append(f"自动签到失败：{exc}")

    cookies = result.get("cookies") or {}
    return {
        "ok": True,
        "username": str(user.get("username") or settings.username or ""),
        "uid": uid,
        "level_name": str(user.get("level_name") or ""),
        "cookie_header": cookie_dict_to_header(cookies),
        "user": user,
        "sign": sign_result,
        "avatar_urls": client.user_avatar_urls(
            uid, str(user.get("photo") or user.get("avatar") or "")
        ),
        "logs": logs,
    }


def user_history_schemas(client: JmApiClient, uid: str, logs: List[str]) -> List[Dict]:
    if not uid:
        return []
    try:
        albums, _total = client.watch_history_albums(page=1)
        return [album_to_dict(album) for album in albums[:12]]
    except Exception as exc:
        logs.append(f"观看记录获取失败：{exc}")
        return []


def get_user_profile(settings: NetworkSettings) -> Dict:
    logs: List[str] = []
    cancel_event = threading.Event()
    config = network_config(settings)
    client = JmApiClient(config, logs.append, cancel_event)
    user: Dict = {}
    uid = ""
    if settings.username and settings.password:
        result = client.login(settings.username, settings.password)
        user = result.get("user") or {}
        uid = str(user.get("uid") or "")
    daily = {}
    if uid:
        try:
            daily = client.get_daily(uid)
        except Exception as exc:
            logs.append(f"签到状态获取失败：{exc}")
    favorites: List[AlbumMeta] = []
    if uid:
        try:
            favorites = client.favorite_albums(page=1, sort="mr")[:12]
        except Exception as exc:
            logs.append(f"收藏预览获取失败：{exc}")
    return {
        "ok": True,
        "username": str(user.get("username") or settings.username or ""),
        "uid": uid,
        "level_name": str(user.get("level_name") or ""),
        "user": user,
        "daily": daily,
        "favorites": [album_to_dict(album) for album in favorites],
        "history": user_history_schemas(client, uid, logs),
        "avatar_urls": client.user_avatar_urls(
            uid, str(user.get("photo") or user.get("avatar") or "")
        ),
        "logs": logs,
    }


def _user_client(settings: NetworkSettings) -> tuple[JmApiClient, str]:
    """Create an authenticated API client for account-only features.

    JMComic-qt reuses the active Cookie for favourite requests.  Repeating a
    login before every add/move folder request makes the UI wait for an extra
    network round trip and can be much slower than the favourite API itself.
    Only obtain a session with credentials when no Cookie is available.
    """
    config = network_config(settings)
    client = JmApiClient(config)
    uid = ""
    if not settings.cookie_header.strip() and settings.username and settings.password:
        result = client.login(settings.username, settings.password)
        uid = str((result.get("user") or {}).get("uid") or "")
    return client, uid


def get_favorite_library(settings: NetworkSettings, folder_id: str = "0", sort: str = "mr", page: int = 1) -> Dict:
    client, _uid = _user_client(settings)
    albums, total, folders = client.favorite_page(page=page, sort=sort, folder_id=folder_id)
    return {
        "albums": [album_to_dict(album) for album in albums],
        "total": total,
        "folders": folders,
        "folder_id": str(folder_id or "0"),
        "page": max(1, page),
    }


def get_all_favorite_albums(settings: NetworkSettings) -> Dict:
    client, _uid = _user_client(settings)
    albums = client.favorite_albums_all(sort="mr", folder_id="0")
    return {"albums": [album_to_dict(album) for album in albums], "total": len(albums)}


def refresh_local_favorite_albums(
    settings: NetworkSettings, album_ids: List[str]
) -> Dict:
    client, _uid = _user_client(settings)
    albums = []
    failed = []
    for album_id in dict.fromkeys(str(value or "").strip() for value in album_ids):
        if not album_id:
            continue
        try:
            albums.append(client.get_album_detail(album_id))
        except Exception:
            failed.append(album_id)
    return {
        "albums": [album_to_dict(album) for album in albums],
        "failed": failed,
        "total": len(albums) + len(failed),
    }


def update_favorite(settings: NetworkSettings, album_id: str, folder_id: str = "") -> Dict:
    client, _uid = _user_client(settings)
    result = client.toggle_favorite(album_id)
    if folder_id:
        try:
            client.move_favorite(album_id, folder_id)
        except Exception:
            # The API toggles first.  A move failure should be visible but must
            # not falsely report that the favourite action itself failed.
            result = dict(result or {})
            result["move_warning"] = "收藏状态已切换，但移动收藏夹失败"
    return {"ok": True, "result": result}


def create_favorite_folder(settings: NetworkSettings, name: str) -> Dict:
    client, _uid = _user_client(settings)
    return {"ok": True, "result": client.create_favorite_folder(name)}


def delete_favorite_folder(settings: NetworkSettings, folder_id: str) -> Dict:
    client, _uid = _user_client(settings)
    return {"ok": True, "result": client.delete_favorite_folder(folder_id)}


def move_favorite(settings: NetworkSettings, album_id: str, folder_id: str) -> Dict:
    client, _uid = _user_client(settings)
    return {"ok": True, "result": client.move_favorite(album_id, folder_id)}


def get_remote_history(settings: NetworkSettings, page: int = 1) -> Dict:
    client, _uid = _user_client(settings)
    albums, total = client.watch_history_albums(page)
    return {"albums": [album_to_dict(album) for album in albums], "total": total, "page": max(1, page)}


def get_comments(
    settings: NetworkSettings,
    album_id: str = "",
    page: int = 1,
    mine: bool = False,
    user_id: str = "",
) -> Dict:
    client, authenticated_uid = _user_client(settings)
    uid = str(user_id or authenticated_uid or "").strip()
    if mine and not uid:
        raise ValueError("无法获取当前用户 UID，请重新登录后再查看我的评论")
    comments, total = client.forum_comments(
        album_id=album_id,
        page=page,
        user_id=uid if mine else "",
    )
    return {
        "comments": comments,
        "total": total,
        "own_total": total if mine else None,
        "personal": bool(mine),
        "page": max(1, page),
    }


def _comment_number(value) -> int:
    try:
        return max(0, int(str(value or "0").replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _comment_reply_count(comment: Dict) -> int:
    replies = comment.get("replys") or comment.get("replies") or comment.get("children")
    if isinstance(replies, list):
        return len(replies)
    if replies not in (None, ""):
        parsed = _comment_number(replies)
        if parsed:
            return parsed
    for key in ("reply_count", "replies_count", "reply_num"):
        if key in comment:
            return _comment_number(comment.get(key))
    return 0


def get_personal_comment_summary(
    settings: NetworkSettings,
    user_id: str = "",
) -> Dict:
    """Aggregate the signed-in user's comment statistics across forum pages."""
    client, authenticated_uid = _user_client(settings)
    uid = str(user_id or authenticated_uid or "").strip()
    if not uid:
        raise ValueError("无法获取当前用户 UID，请重新登录后再查看我的评论")

    comments: List[Dict] = []
    seen_ids = set()
    total = 0
    page = 1
    # A broken endpoint must not leave the worker paging forever. In practice
    # forum pages contain many records, so this still covers large accounts.
    while page <= 500:
        page_comments, page_total = client.forum_comments(
            album_id="",
            page=page,
            user_id=uid,
        )
        total = max(total, _comment_number(page_total))
        if not page_comments:
            break

        added = 0
        for index, item in enumerate(page_comments):
            if not isinstance(item, dict):
                continue
            comment_id = str(
                item.get("CID") or item.get("cid") or item.get("comment_id") or item.get("id") or ""
            ).strip()
            marker = ("cid", comment_id) if comment_id else (
                "item",
                str(item.get("UID") or item.get("uid") or ""),
                str(item.get("addtime") or item.get("created_at") or item.get("time") or ""),
                str(item.get("comment") or item.get("content") or item.get("text") or ""),
                index,
            )
            if marker in seen_ids:
                continue
            seen_ids.add(marker)
            comments.append(item)
            added += 1

        if total and len(comments) >= total:
            break
        if not added:
            break
        page += 1

    likes = sum(
        _comment_number(
            item.get("likes")
            if item.get("likes") is not None
            else item.get("like", item.get("like_count", item.get("praise", 0)))
        )
        for item in comments
    )
    replies = sum(_comment_reply_count(item) for item in comments)
    featured = sum(
        1
        for item in comments
        if _comment_number(
            item.get("likes")
            if item.get("likes") is not None
            else item.get("like", item.get("like_count", item.get("praise", 0)))
        ) > 0
    )
    return {
        "published": total or len(comments),
        "likes": likes,
        "featured": featured,
        "replies": replies,
        "user_id": uid,
    }


def post_comment(settings: NetworkSettings, album_id: str, comment: str, comment_id: str = "") -> Dict:
    client, _uid = _user_client(settings)
    return {"ok": True, "result": client.post_comment(album_id, comment, comment_id)}


def get_latest_albums(settings: NetworkSettings, page: int = 0) -> Dict:
    client = JmApiClient(network_config(settings))
    albums = client.latest(page)
    return {"albums": [album_to_dict(album) for album in albums], "page": max(0, page)}


def get_week_categories(settings: NetworkSettings) -> Dict:
    client = JmApiClient(network_config(settings))
    return {"categories": client.week_categories()}


def get_week_albums(settings: NetworkSettings, category_id: str, category_type: str = "manga", page: int = 0) -> Dict:
    client = JmApiClient(network_config(settings))
    albums = client.week_filter(category_id, category_type, page)
    return {
        "albums": [album_to_dict(album) for album in albums],
        "category_id": str(category_id),
        "category_type": str(category_type),
        "page": max(0, page),
    }
