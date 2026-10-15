import copy
import hashlib
import os
import threading
import shutil
import zipfile
import random
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Signal

from .download_store import DownloadStore
from .jm_api import JmApiClient, PhotoDetail, parse_jm_id
from .models import AlbumMeta, ChapterMeta, DownloadConfig, NetworkConfig
from .pdf_utils import collect_images, collect_images_recursive, images_to_pdf
from .runtime_paths import book_cache_dir
from .utils import safe_name

PDF_AUTO_SPLIT_IMAGE_COUNT = 700
PDF_MAX_IMAGES_PER_FILE = 280
# Keep compatibility with Windows installations where long paths are not
# enabled. Directories need enough remaining room for image/PDF filenames.
DOWNLOAD_ALBUM_PATH_LIMIT = 190
DOWNLOAD_DIRECTORY_PATH_LIMIT = 240
DOWNLOAD_FILE_PATH_LIMIT = 250
MIN_BOUNDED_NAME_UNITS = 12


def _windows_path_length(path: Path) -> int:
    absolute = os.path.abspath(str(path))
    return len(absolute.encode("utf-16-le")) // 2


def _windows_text_units(value: str) -> int:
    return len(str(value).encode("utf-16-le")) // 2


def _truncate_windows_units(value: str, max_units: int) -> str:
    if max_units <= 0:
        return ""
    result = []
    used = 0
    for character in value:
        units = len(character.encode("utf-16-le")) // 2
        if used + units > max_units:
            break
        result.append(character)
        used += units
    return "".join(result)


def _bounded_safe_name(text: str, fallback: str, max_units: int) -> str:
    cleaned = safe_name(text, fallback)
    if _windows_text_units(cleaned) <= max_units:
        return cleaned
    digest = hashlib.sha256(str(text or fallback).encode("utf-8")).hexdigest()[:8]
    suffix = f"-{digest}"
    head = _truncate_windows_units(cleaned, max_units - len(suffix)).rstrip(" .")
    if head:
        return f"{head}{suffix}"
    compact_fallback = _truncate_windows_units(safe_name(fallback, "item"), max_units)
    if compact_fallback:
        return compact_fallback
    raise OSError("下载目录过长，无法生成安全的文件名；请缩短下载保存路径")


def _child_component_budget(parent: Path, path_limit: int, reserved_units: int = 0) -> int:
    return path_limit - _windows_path_length(parent) - 1 - max(0, reserved_units)


def ensure_album_id(expected_id: str, actual_id: str, requested_url: str, actual_url: str):
    if expected_id and actual_id and expected_id != actual_id:
        raise RuntimeError(
            "Requested album ID "
            f"{expected_id}, but the site returned album ID {actual_id}. "
            f"Requested URL: {requested_url}; final URL: {actual_url or requested_url}. "
            "Check that the input is an album ID/link, not a photo/chapter ID."
        )


class ScrapeWorker(QThread):
    album_found = Signal(object)
    album_found_at = Signal(int, object)
    promote_sections_ready = Signal(object)
    total_known = Signal(int)
    log = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(
        self,
        list_url: str,
        ids: List[str],
        include_detail: bool,
        config: NetworkConfig,
        search_query: str = "",
        rank_type: str = "day",
        category: str = "",
        promote: bool = False,
        latest: bool = False,
        promote_section: str = "",
        list_pages: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self.list_url = list_url
        self.ids = ids
        self.include_detail = include_detail
        self.config = config
        self.search_query = search_query
        self.rank_type = rank_type
        self.category = category
        self.promote = bool(promote)
        self.latest = bool(latest)
        self.promote_section = str(promote_section or "").strip()
        self.start_page = max(1, list_pages)
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            client = JmApiClient(self.config, self.log.emit, self.cancel_event)
            api_domains = client._get_api_domains()
            if self.ids:
                self.log.emit(f"准备按 ID 获取 {len(self.ids)} 个漫画详情。")
                self.total_known.emit(len(self.ids))
                self._emit_parallel_details(self.ids, api_domains)
                self.finished_ok.emit()
                return
            elif self.search_query.strip():
                self.log.emit(f"正在通过 App API 搜索：{self.search_query}，第 {self.start_page} 页")
                albums = self._emit_album_pages(client, api_domains, search_query=self.search_query.strip())
            elif self.promote:
                self.log.emit(f"正在通过 App API 获取首页推荐，第 {self.start_page} 页。")
                albums = self._emit_album_pages(client, api_domains, promote=True, promote_section=self.promote_section)
            elif self.latest:
                self.log.emit(f"正在通过 App API 获取最新上传，第 {self.start_page} 页。")
                albums = self._emit_album_pages(client, api_domains, latest=True)
            else:
                if self.category:
                    self.log.emit(f"正在通过 App API 获取分类 {self.category}，第 {self.start_page} 页。")
                else:
                    self.log.emit(f"正在通过 App API 获取排行榜，第 {self.start_page} 页。")
                albums = self._emit_album_pages(client, api_domains, rank_type=self.rank_type, category=self.category)
            found_count = len(albums)
            self.log.emit(f"获取到 {found_count} 个漫画，结果区将连续追加显示。")
            self.total_known.emit(found_count)

            total = len(albums)
            self.progress.emit(0, total)
            # Listing endpoints already contain everything needed to render a
            # card.  Treating protocol_parser as a request to load every album
            # detail made the home screen wait for hundreds of /album requests
            # before it could become visible.
            detail_prefetch = self.include_detail
            if detail_prefetch:
                self.log.emit(f"正在并发加载详情，线程数：{self._detail_threads(total)}")
                seed_albums = {album.album_id: album for album in albums}
                self._emit_parallel_details([album.album_id for album in albums], api_domains, seed_albums)

            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _emit_album_pages(
        self,
        client: JmApiClient,
        api_domains: List[str],
        search_query: str = "",
        rank_type: str = "day",
        category: str = "",
        promote: bool = False,
        latest: bool = False,
        promote_section: str = "",
    ) -> List[AlbumMeta]:
        albums: List[AlbumMeta] = []
        seen = set()
        page = self.start_page
        while page <= self.start_page:
            if self.cancel_event.is_set():
                break
            client._api_domains = list(api_domains)
            client._domains_initialized = True
            if search_query:
                page_albums = client.search(search_query, page=page)
            elif promote:
                # /promote returns every home section in one payload.  Expose
                # that payload to the UI so switching tabs never repeats the
                # same request just to select a different section.
                sections = client.promote_sections(page=page)
                if page == 1:
                    self.promote_sections_ready.emit(sections)
                if promote_section:
                    normalized_prefix = "".join(promote_section.split()).lower()
                    page_albums = next(
                        (
                            section_albums
                            for title, section_albums in sections.items()
                            if "".join(title.split()).lower().startswith(normalized_prefix)
                        ),
                        [],
                    )
                else:
                    page_albums = [album for section_albums in sections.values() for album in section_albums]
            elif latest:
                page_albums = client.latest(page=max(0, page - 1))
            elif category:
                page_albums = client.category(category, page=page)
            else:
                page_albums = client.ranking(rank_type, page=page)
            self.log.emit(f"第 {page} 页获取到 {len(page_albums)} 本漫画。")
            if not page_albums:
                break
            self.total_known.emit(len(page_albums))
            for album in page_albums:
                if album.album_id in seen:
                    continue
                seen.add(album.album_id)
                albums.append(album)
                index = len(albums) - 1
                self.album_found.emit(album)
                self.album_found_at.emit(index, album)
                self.progress.emit(len(albums), len(page_albums))
            self.total_known.emit(len(albums))
            page += 1
        return albums

    def _emit_parallel_details(
        self,
        item_ids: List[str],
        api_domains: List[str],
        seed_albums: Optional[Dict[str, AlbumMeta]] = None,
    ):
        total = len(item_ids)
        self.progress.emit(0, total)
        if total == 0:
            return

        done = 0
        with ThreadPoolExecutor(max_workers=self._detail_threads(total)) as executor:
            futures = {
                executor.submit(
                    self._load_one_detail,
                    item_id,
                    api_domains,
                    seed_albums.get(item_id) if seed_albums else None,
                ): index
                for index, item_id in enumerate(item_ids)
            }
            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    self.log.emit("采集已取消。")
                    break
                index = futures[future]
                item_id = item_ids[index]
                try:
                    album = future.result()
                except Exception as exc:
                    self.log.emit(f"详情加载失败，保留列表信息 {item_id}：{exc}")
                    album = seed_albums.get(item_id) if seed_albums else None
                if album is None:
                    done += 1
                    self.progress.emit(done, total)
                    continue
                self.album_found.emit(album)
                self.album_found_at.emit(index, album)
                done += 1
                self.progress.emit(done, total)

    def _load_one_detail(
        self,
        item_id: str,
        api_domains: List[str],
        seed_album: Optional[AlbumMeta] = None,
    ) -> AlbumMeta:
        client = JmApiClient(self.config, self.log.emit, self.cancel_event)
        client._api_domains = list(api_domains)
        client._domains_initialized = True
        if item_id.lower().startswith("p"):
            detail = client.photo_as_album(item_id[1:])
        else:
            detail = client.get_album_detail(item_id)
        if seed_album and seed_album.cover_url and not detail.cover_url:
            detail.cover_url = seed_album.cover_url
        return detail

    def _detail_threads(self, total: int) -> int:
        return min(max(1, self.config.detail_threads), max(1, total))


class ChapterWorker(QThread):
    chapters_loaded = Signal(str, object)
    log = Signal(str)
    failed = Signal(str)

    def __init__(self, album: AlbumMeta, config: NetworkConfig, parent=None):
        super().__init__(parent)
        self.album = album
        self.config = config
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            client = JmApiClient(self.config, self.log.emit, self.cancel_event)
            if self.album.album_id.lower().startswith("p"):
                detail = client.photo_as_album(self.album.album_id[1:])
            else:
                detail = client.get_album_detail(self.album.album_id)
            chapters = detail.chapters
            if self.album.cover_url and not detail.cover_url:
                detail.cover_url = self.album.cover_url
            self.chapters_loaded.emit(self.album.album_id, detail)
            self.log.emit(f"已加载 {self.album.title} 的 {len(chapters)} 个章节。")
        except Exception as exc:
            self.failed.emit(str(exc))


class IncrementalUpdateWorker(QThread):
    progress = Signal(int, int)
    log = Signal(str)
    finished_ok = Signal(int)
    failed = Signal(str)

    def __init__(self, config: NetworkConfig, limit: int = 120, parent=None):
        super().__init__(parent)
        self.config = config
        self.limit = max(1, limit)
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        # Online lists intentionally are not persisted.  Update checks are
        # therefore limited to explicit collection/download workflows.
        if not self.cancel_event.is_set():
            self.finished_ok.emit(0)


class DownloadWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    album_started = Signal(object, int)
    album_progress = Signal(object, int, int)
    chapter_done = Signal(object, int, int)
    album_transfer = Signal(object, int, float)
    album_done = Signal(object)
    item_done = Signal(object, str)
    state_changed = Signal(object, str, object)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, albums: List[AlbumMeta], config: DownloadConfig, parent=None):
        super().__init__(parent)
        self.albums = albums
        self.config = config
        self.cancel_event = threading.Event()
        self._transfer_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._album_bytes: Dict[str, int] = {}
        self._album_last_bytes: Dict[str, int] = {}
        self._album_last_time: Dict[str, float] = {}
        self._album_speeds: Dict[str, float] = {}
        self._album_image_done: Dict[str, int] = {}
        self._album_image_total: Dict[str, int] = {}
        self._global_chapters_done = 0
        self._global_chapters_total = 1

    def cancel(self):
        self.cancel_event.set()

    def _emit_state(self, album: AlbumMeta, state: str, **detail) -> None:
        self.state_changed.emit(album, state, detail)

    def run(self):
        try:
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            total = max(1, sum(self._chapter_count(album) for album in self.albums))
            self._global_chapters_done = 0
            self._global_chapters_total = total
            self.progress.emit(0, total)

            for album in self.albums:
                if self.cancel_event.is_set():
                    self._emit_state(album, "cancelled")
                    self.log.emit("下载已取消。")
                    return
                album_total = self._chapter_count(album)
                self.album_started.emit(album, album_total)
                chapter_paths = self._download_album(album)
                if self.cancel_event.is_set():
                    self._emit_state(album, "cancelled")
                    self.log.emit("下载已取消，未写入完成记录。")
                    return
                if not chapter_paths:
                    raise RuntimeError(f"下载未生成有效输出：{album.title}")
                self.album_done.emit(album)
                for pdf_path in chapter_paths:
                    self.item_done.emit(album, str(pdf_path))

            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _chapter_count(self, album: AlbumMeta) -> int:
        if album.selected_chapter_ids:
            return len(album.selected_chapter_ids)
        return max(1, len(album.chapters))

    def _album_directory(self, album: AlbumMeta) -> Path:
        prefix = f"JM{album.album_id}-"
        component_budget = _child_component_budget(
            self.config.output_dir, DOWNLOAD_ALBUM_PATH_LIMIT
        )
        title_budget = component_budget - _windows_text_units(prefix)
        if title_budget < MIN_BOUNDED_NAME_UNITS:
            raise OSError("下载保存路径过长，请选择更短的下载目录")
        title = _bounded_safe_name(album.title, album.album_id, title_budget)
        return self.config.output_dir / f"{prefix}{title}"

    @staticmethod
    def _attempt_directory_prefix(album: AlbumMeta) -> str:
        return f".JM{album.album_id}.partial-"

    @staticmethod
    def _chapter_directory_name(chapter: ChapterMeta, *parents: Path) -> str:
        prefix = f"{chapter.index:03d}-"
        component_budget = min(
            _child_component_budget(parent, DOWNLOAD_DIRECTORY_PATH_LIMIT)
            for parent in parents
        )
        title_budget = component_budget - _windows_text_units(prefix)
        if title_budget < MIN_BOUNDED_NAME_UNITS:
            raise OSError("下载保存路径过长，无法创建章节目录；请缩短下载保存路径")
        title = _bounded_safe_name(chapter.title, chapter.chapter_id, title_budget)
        return f"{prefix}{title}"

    def _download_album(self, album: AlbumMeta) -> List[Path]:
        estimated_chapter_total = self._chapter_count(album)
        download_store = DownloadStore()
        self._emit_state(album, "fetch_book")
        detail = self._cached_album_detail(album)
        client: Optional[JmApiClient] = None
        if detail is None:
            client = JmApiClient(self.config, self.log.emit, self.cancel_event)
            if album.album_id.lower().startswith("p"):
                detail = client.photo_as_album(album.album_id[1:])
            else:
                detail = client.get_album_detail(album.album_id)
        else:
            self.log.emit(f"下载元数据命中本地缓存：{detail.title}（{detail.album_id}）")
        self._emit_state(album, "fetch_chapters")
        chapters = detail.chapters
        detail.selected_chapter_ids = list(album.selected_chapter_ids)
        if album.selected_chapter_ids:
            wanted = set(album.selected_chapter_ids)
            chapters = [chapter for chapter in chapters if chapter.chapter_id in wanted]
        if not chapters:
            chapters = [ChapterMeta(parse_jm_id(album.album_id), "全集", album.url, 1)]
        self._adjust_global_chapter_total(estimated_chapter_total, len(chapters))

        self.log.emit(f"开始下载 {album.title}，章节数：{len(chapters)}")
        album_dir = self._album_directory(album)
        album_dir.mkdir(parents=True, exist_ok=True)
        attempt_dir = Path(
            tempfile.mkdtemp(
                prefix=self._attempt_directory_prefix(album),
                dir=str(self.config.output_dir),
            )
        )
        output_paths: List[Path] = []
        try:
            download_store.update_task(album.album_id, detail.title, album_dir, "downloading")
            self._start_album_transfer(album, album_dir)
            pending_chapters = [chapter for chapter in chapters if not self._chapter_cached(download_store, chapter)]
            if pending_chapters and client is None:
                client = JmApiClient(self.config, self.log.emit, self.cancel_event)
            self._emit_state(album, "fetch_images")
            protocol_photos = self._prefetch_protocol_photos(client, album, chapters, download_store) if client is not None else {}

            chapter_done = 0
            chapter_total = max(1, len(chapters))
            image_workers = max(1, min(12, self.config.image_threads))
            image_client_local = threading.local()
            image_domains = list(client._image_domains) if client is not None else []

            def init_image_client():
                worker_client = JmApiClient(self.config, None, self.cancel_event)
                if image_domains:
                    worker_client._image_domains = list(image_domains)
                image_client_local.client = worker_client

            def download_slot(album_meta, photo_meta, image_index, image_name, chapter_dir):
                worker_client = getattr(image_client_local, "client", client)
                return self._download_image_slot(
                    worker_client,
                    album_meta,
                    photo_meta,
                    image_index,
                    image_name,
                    chapter_dir,
                )

            self.log.emit(f"图片下载线程：{image_workers}")
            image_executor = ThreadPoolExecutor(
                max_workers=image_workers,
                initializer=init_image_client,
            )
            deferred_attempt_cleanup = False
            try:
                for chapter in chapters:
                    if self.cancel_event.is_set():
                        raise RuntimeError("下载已取消")
                    self._emit_state(album, "downloading", current_chapter_id=chapter.chapter_id)
                    self._download_chapter(
                        client,
                        album,
                        chapter,
                        album_dir,
                        download_store,
                        protocol_photos.get(chapter.chapter_id),
                        image_executor=image_executor,
                        download_slot=download_slot,
                        chapter_staging_root=attempt_dir,
                    )
                    if self.cancel_event.is_set():
                        raise RuntimeError("下载已取消")
                    chapter_done += 1
                    self._emit_global_chapter_done(album, chapter_done, chapter_total)
            finally:
                if self.cancel_event.is_set():
                    image_executor.shutdown(wait=False, cancel_futures=True)
                    self._cleanup_attempt_after_executor(image_executor, attempt_dir)
                    deferred_attempt_cleanup = True
                else:
                    image_executor.shutdown(wait=True, cancel_futures=True)

            self._emit_state(album, "finalizing")
            output_paths.extend(
                self._finalize_validated_album_outputs(album, album_dir, chapters)
            )
            try:
                download_store.update_task(
                    album.album_id, detail.title, album_dir, "completed"
                )
            except Exception as state_error:
                self.log.emit(f"记录下载完成状态时出错：{state_error}")
            if not deferred_attempt_cleanup:
                self._cleanup_download_attempt(attempt_dir)
            return output_paths
        except Exception:
            self._emit_state(album, "cancelled" if self.cancel_event.is_set() else "failed")
            try:
                download_store.update_task(album.album_id, detail.title, album_dir, "failed")
            except Exception as state_error:
                self.log.emit(f"记录下载失败状态时出错：{state_error}")
            cleanup_attempt = None if locals().get("deferred_attempt_cleanup", False) else attempt_dir
            self._cleanup_incomplete_album(album_dir, output_paths, cleanup_attempt)
            raise

    def _cached_album_detail(self, album: AlbumMeta) -> Optional[AlbumMeta]:
        if album.chapters:
            return copy.deepcopy(album)
        return None

    def _emit_global_chapter_done(self, album: AlbumMeta, album_done: int, album_total: int):
        self._global_chapters_done = min(self._global_chapters_total, self._global_chapters_done + 1)
        self.progress.emit(self._global_chapters_done, self._global_chapters_total)
        self.chapter_done.emit(album, album_done, album_total)

    def _adjust_global_chapter_total(self, estimated_total: int, actual_total: int):
        estimated_total = max(1, estimated_total)
        actual_total = max(1, actual_total)
        if estimated_total == actual_total:
            return
        self._global_chapters_total = max(1, self._global_chapters_total + actual_total - estimated_total)
        self.progress.emit(self._global_chapters_done, self._global_chapters_total)

    def _prefetch_protocol_photos(
        self,
        client: Optional[JmApiClient],
        album: AlbumMeta,
        chapters: List[ChapterMeta],
        download_store: DownloadStore,
    ) -> Dict[str, PhotoDetail]:
        if not self.config.protocol_parser or len(chapters) <= 1:
            return {}
        pending = [chapter for chapter in chapters if not self._chapter_cached(download_store, chapter)]
        if len(pending) <= 1:
            return {}
        api_domains = client._get_api_domains()
        max_workers = min(max(1, self.config.detail_threads), len(pending))
        self.log.emit(f"Protocol parser prefetch: {len(pending)} chapters, workers={max_workers}")

        def load_one(chapter: ChapterMeta):
            worker_client = JmApiClient(self.config, self.log.emit, self.cancel_event)
            worker_client._api_domains = list(api_domains)
            worker_client._domains_initialized = True
            return chapter.chapter_id, worker_client.get_photo_detail(chapter.chapter_id, album, fetch_scramble=True)

        photos: Dict[str, PhotoDetail] = {}
        executor = ThreadPoolExecutor(max_workers=max_workers)
        futures = {executor.submit(load_one, chapter): chapter for chapter in pending}
        try:
            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    break
                chapter_id, photo = future.result()
                photos[chapter_id] = photo
        finally:
            executor.shutdown(
                wait=not self.cancel_event.is_set(),
                cancel_futures=True,
            )
        return photos

    @staticmethod
    def _chapter_cached(download_store: DownloadStore, chapter: ChapterMeta) -> bool:
        cached_path = download_store.cached_chapter_path(chapter.chapter_id)
        return bool(cached_path and collect_images(cached_path))

    def _download_chapter(
        self,
        client: JmApiClient,
        album: AlbumMeta,
        chapter: ChapterMeta,
        album_dir: Path,
        download_store: DownloadStore,
        photo: Optional[PhotoDetail] = None,
        image_executor: Optional[ThreadPoolExecutor] = None,
        download_slot=None,
        chapter_staging_root: Optional[Path] = None,
    ):
        chapter_parents = [album_dir]
        if chapter_staging_root is not None:
            chapter_parents.append(chapter_staging_root)
        chapter_name = self._chapter_directory_name(chapter, *chapter_parents)
        chapter_dir = album_dir / chapter_name
        cached_path = download_store.cached_chapter_path(chapter.chapter_id)
        cached_images = collect_images(cached_path) if cached_path else []
        if cached_images:
            self._add_album_image_total(album, len(cached_images))
            if cached_path.resolve() != chapter_dir.resolve():
                self._mirror_cached_chapter(cached_path, chapter_dir)
                self._record_album_transfer(album, self._dir_size(chapter_dir))
            self._mark_album_images_done(album, len(cached_images))
            self.log.emit(f"跳过已缓存章节：{chapter.title}")
            return

        if photo is None:
            if client is None:
                raise RuntimeError(f"章节 {chapter.title} 缺少本地缓存，且没有可用的网络客户端。")
            photo = client.get_photo_detail(chapter.chapter_id, album, fetch_scramble=True)
        if not photo.images:
            raise RuntimeError(f"未在章节 {chapter.title} 找到图片。")

        download_dir = (
            chapter_staging_root / chapter_name
            if chapter_staging_root is not None
            else chapter_dir
        )
        download_dir.mkdir(parents=True, exist_ok=True)
        self._add_album_image_total(album, len(photo.images))

        self.log.emit(f"下载章节 {chapter.title}：{len(photo.images)} 张图片")
        owns_executor = image_executor is None
        executor = image_executor or ThreadPoolExecutor(
            max_workers=max(1, min(12, self.config.image_threads))
        )
        slot = download_slot or self._download_image_slot
        pending_futures = set()
        images = iter(enumerate(photo.images, start=1))
        submit_limit = max(1, min(12, self.config.image_threads)) * 2

        def submit_next() -> bool:
            if self.cancel_event.is_set():
                return False
            try:
                image_index, image_name = next(images)
            except StopIteration:
                return False
            if download_slot is not None:
                future = executor.submit(
                    slot, album, photo, image_index, image_name, download_dir
                )
            else:
                future = executor.submit(
                    slot, client, album, photo, image_index, image_name, download_dir
                )
            pending_futures.add(future)
            return True

        try:
            for _ in range(min(submit_limit, len(photo.images))):
                if not submit_next():
                    break
            while pending_futures:
                if self.cancel_event.is_set():
                    raise RuntimeError("下载已取消")
                completed, _ = wait(
                    pending_futures,
                    timeout=0.05,
                    return_when=FIRST_COMPLETED,
                )
                if not completed:
                    continue
                for future in completed:
                    pending_futures.remove(future)
                    if self.cancel_event.is_set():
                        raise RuntimeError("下载已取消")
                    future.result()
                    self._mark_album_images_done(album, 1)
                    submit_next()
        finally:
            for future in pending_futures:
                future.cancel()
            if owns_executor:
                executor.shutdown(
                    wait=not self.cancel_event.is_set(),
                    cancel_futures=True,
                )
        downloaded_images = collect_images(download_dir)
        if len(downloaded_images) < len(photo.images):
            raise RuntimeError(f"章节下载不完整：{chapter.title}，{len(downloaded_images)}/{len(photo.images)}")
        if download_dir != chapter_dir:
            self._commit_staged_chapter(download_dir, chapter_dir)
            downloaded_images = collect_images(chapter_dir)
        download_store.mark_chapter_downloaded(album.album_id, chapter, chapter_dir, len(downloaded_images))

    @staticmethod
    def _commit_staged_chapter(staged_dir: Path, chapter_dir: Path) -> None:
        """Atomically publish a complete chapter while preserving the old one on failure."""
        chapter_dir.parent.mkdir(parents=True, exist_ok=True)
        backup_token = hashlib.sha256(
            f"{chapter_dir.name}|{staged_dir.parent.name}".encode("utf-8")
        ).hexdigest()[:12]
        backup_dir = chapter_dir.parent / f".previous-{backup_token}"
        moved_previous = False
        if chapter_dir.exists():
            chapter_dir.replace(backup_dir)
            moved_previous = True
        try:
            staged_dir.replace(chapter_dir)
        except Exception:
            if moved_previous and backup_dir.exists() and not chapter_dir.exists():
                backup_dir.replace(chapter_dir)
            raise
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

    def _mirror_cached_chapter(self, cached_path: Path, chapter_dir: Path):
        chapter_dir.mkdir(parents=True, exist_ok=True)
        for image_path in collect_images(cached_path):
            target = chapter_dir / image_path.name
            if target.exists() and target.stat().st_size > 0:
                continue
            try:
                target.hardlink_to(image_path)
            except Exception:
                shutil.copy2(image_path, target)

    def _download_image_slot(self, client: JmApiClient, album: AlbumMeta, photo, image_index: int, image_name: str, chapter_dir: Path):
        if self.cancel_event.is_set():
            raise RuntimeError("下载已取消")
        raw_suffix = Path(image_name).suffix.lower() or ".jpg"
        suffix = ".webp" if self.config.cache_as_webp and raw_suffix != ".gif" else raw_suffix
        filename = chapter_dir / f"{image_index:05d}{suffix}"
        if filename.exists() and filename.stat().st_size > 0:
            return

        last_error = None
        for url in client.build_image_urls(photo, image_name):
            try:
                if self.cancel_event.is_set():
                    raise RuntimeError("下载已取消")
                client.download_image(
                    url,
                    filename,
                    photo.scramble_id,
                    progress_callback=lambda size, album=album: self._record_album_transfer(album, int(size)),
                )
                return
            except Exception as exc:
                last_error = exc
                if filename.exists():
                    filename.unlink(missing_ok=True)
                if self.cancel_event.is_set():
                    raise RuntimeError("下载已取消") from exc
        raise RuntimeError(f"图片下载失败：{image_name}: {last_error}")

    def _finalize_album_outputs(
        self, album_dir: Path, chapters: List[ChapterMeta]
    ) -> List[Path]:
        if self.config.output_format == "images":
            return [album_dir]
        if self.config.output_format in {"zip", "cbz"}:
            suffix = ".cbz" if self.config.output_format == "cbz" else ".zip"
            try:
                return [self._make_zip(album_dir, suffix=suffix)]
            except Exception as exc:
                if collect_images_recursive(album_dir):
                    self.log.emit(
                        f"{self.config.output_format.upper()} 生成失败，"
                        f"已保留完整图片目录作为下载结果：{exc}"
                    )
                    return [album_dir]
                raise
        if self.config.output_format != "pdf":
            raise RuntimeError(f"不支持的保存格式：{self.config.output_format}")
        try:
            return self._make_pdf_outputs(album_dir, chapters)
        except Exception as exc:
            if collect_images_recursive(album_dir):
                self.log.emit(f"PDF 生成失败，已保留完整图片目录作为下载结果：{exc}")
                return [album_dir]
            raise

    def _finalize_validated_album_outputs(
        self,
        album: AlbumMeta,
        album_dir: Path,
        chapters: List[ChapterMeta],
    ) -> List[Path]:
        outputs = self._finalize_album_outputs(album_dir, chapters)
        self._validate_album_outputs(album, outputs)
        self._discard_source_images_after_success(album_dir, outputs)
        return outputs

    def _discard_source_images_after_success(
        self, album_dir: Path, output_paths: List[Path]
    ) -> None:
        if self.config.keep_images or self.config.output_format == "images":
            return
        # A directory output means archive/PDF conversion failed and the
        # complete images are the recovery result; never remove that fallback.
        if any(path.is_dir() for path in output_paths):
            return
        try:
            if self.config.output_format in {"zip", "cbz"}:
                shutil.rmtree(album_dir)
                self.log.emit(f"已按设置移除图片目录：{album_dir}")
                return
            for image_path in collect_images_recursive(album_dir):
                image_path.unlink(missing_ok=True)
            for directory in sorted(
                (path for path in album_dir.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            self.log.emit(f"已按设置移除 PDF 源图片：{album_dir}")
        except OSError as exc:
            self.log.emit(f"移除源图片失败，已保留目录：{album_dir}，{exc}")

    def _start_album_transfer(self, album: AlbumMeta, album_dir: Path):
        existing_bytes = self._dir_size(album_dir)
        now = time.monotonic()
        with self._transfer_lock:
            self._album_bytes[album.album_id] = existing_bytes
            self._album_last_bytes[album.album_id] = existing_bytes
            self._album_last_time[album.album_id] = now
            self._album_speeds[album.album_id] = 0.0
        with self._progress_lock:
            self._album_image_done[album.album_id] = 0
            self._album_image_total[album.album_id] = 0
        self.album_transfer.emit(album, existing_bytes, 0.0)
        self.album_progress.emit(album, 0, 1)

    def _add_album_image_total(self, album: AlbumMeta, count: int):
        count = max(0, int(count))
        if count <= 0:
            return
        with self._progress_lock:
            done = self._album_image_done.get(album.album_id, 0)
            current_total = self._album_image_total.get(album.album_id, 0)
            total = max(done + count, current_total + count, 1)
            self._album_image_total[album.album_id] = total
        self.album_progress.emit(album, done, total)

    def _mark_album_images_done(self, album: AlbumMeta, count: int = 1):
        count = max(0, int(count))
        if count <= 0:
            return
        with self._progress_lock:
            total = max(1, self._album_image_total.get(album.album_id, 1))
            done = min(total, self._album_image_done.get(album.album_id, 0) + count)
            self._album_image_done[album.album_id] = done
        self.album_progress.emit(album, done, total)

    def _record_album_transfer(self, album: AlbumMeta, delta_bytes: int):
        if delta_bytes <= 0:
            return
        now = time.monotonic()
        with self._transfer_lock:
            current = self._album_bytes.get(album.album_id, 0) + int(delta_bytes)
            last_bytes = self._album_last_bytes.get(album.album_id, current)
            last_time = self._album_last_time.get(album.album_id, now)
            elapsed = max(0.001, now - last_time)
            speed = self._album_speeds.get(album.album_id, 0.0)
            if elapsed >= 0.15:
                speed = max(0.0, (current - last_bytes) / elapsed)
                self._album_last_bytes[album.album_id] = current
                self._album_last_time[album.album_id] = now
                self._album_speeds[album.album_id] = speed
            self._album_bytes[album.album_id] = current
        self.album_transfer.emit(album, current, speed)

    def _dir_size(self, directory: Path) -> int:
        if not directory.exists():
            return 0
        total = 0
        for path in directory.rglob("*"):
            if self.cancel_event.is_set():
                break
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    def _validate_album_outputs(self, album: AlbumMeta, output_paths: List[Path]):
        if self.cancel_event.is_set():
            raise RuntimeError("下载已取消")
        if not output_paths:
            raise RuntimeError(f"下载未生成有效输出：{album.title}")
        for path in output_paths:
            if not path.exists():
                raise RuntimeError(f"下载输出不存在：{path}")
            if path.is_dir():
                if not collect_images_recursive(path):
                    raise RuntimeError(f"下载目录没有可用图片：{path}")
            elif path.stat().st_size <= 0:
                raise RuntimeError(f"下载输出文件为空：{path}")

    def _cleanup_incomplete_album(
        self,
        album_dir: Path,
        output_paths: List[Path],
        attempt_dir: Optional[Path] = None,
    ):
        """Remove only artifacts created by this attempt; never delete album_dir."""
        targets: List[Path] = list(output_paths)
        if attempt_dir is not None:
            targets.append(attempt_dir)
        seen = set()
        for path in targets:
            try:
                key = str(path.resolve(strict=False)).lower()
            except Exception:
                key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            if not path.exists():
                continue
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                self.log.emit(f"已清理未完成下载：{path}")
            except Exception as exc:
                self.log.emit(f"清理未完成下载失败：{path}，{exc}")

    def _cleanup_download_attempt(self, attempt_dir: Path) -> None:
        if not attempt_dir.exists():
            return
        try:
            shutil.rmtree(attempt_dir)
        except OSError as exc:
            self.log.emit(f"清理下载临时目录失败：{attempt_dir}，{exc}")

    def _cleanup_attempt_after_executor(
        self, executor: ThreadPoolExecutor, attempt_dir: Path
    ) -> None:
        def cleanup() -> None:
            executor.shutdown(wait=True, cancel_futures=True)
            self._cleanup_download_attempt(attempt_dir)

        threading.Thread(
            target=cleanup,
            name="comic18-download-cancel-cleanup",
            daemon=True,
        ).start()

    def _make_pdf_outputs(self, album_dir: Path, chapters: List[ChapterMeta]) -> List[Path]:
        outputs: List[Path] = []
        chapter_dirs = self._chapter_dirs(album_dir)
        total_images = sum(len(collect_images(chapter_dir)) for chapter_dir in chapter_dirs)
        if self.config.pdf_split_chapters and len(chapters) > 1:
            for chapter_dir in chapter_dirs:
                pdf_path = self._unique_path(album_dir, chapter_dir.name, ".pdf")
                images_to_pdf(collect_images(chapter_dir), pdf_path)
                outputs.append(pdf_path)
                self.log.emit(f"已生成 PDF：{pdf_path}")
            return outputs
        if total_images > PDF_AUTO_SPLIT_IMAGE_COUNT:
            if len(chapter_dirs) > 1:
                self.log.emit(f"图片数量 {total_images} 较多，自动按章节拆分 PDF，避免后处理失败。")
                for chapter_dir in chapter_dirs:
                    images = collect_images(chapter_dir)
                    if not images:
                        continue
                    pdf_path = self._unique_path(album_dir, chapter_dir.name, ".pdf")
                    images_to_pdf(images, pdf_path)
                    outputs.append(pdf_path)
                    self.log.emit(f"已生成 PDF：{pdf_path}")
                return outputs
            self.log.emit(f"图片数量 {total_images} 较多，自动分卷生成 PDF，避免后处理失败。")
            images = collect_images(album_dir)
            for start in range(0, len(images), PDF_MAX_IMAGES_PER_FILE):
                part = start // PDF_MAX_IMAGES_PER_FILE + 1
                pdf_path = self._unique_path(album_dir, f"{album_dir.name} - part{part:02d}", ".pdf")
                images_to_pdf(images[start:start + PDF_MAX_IMAGES_PER_FILE], pdf_path)
                outputs.append(pdf_path)
                self.log.emit(f"已生成 PDF：{pdf_path}")
            return outputs

        image_paths = []
        for chapter_dir in chapter_dirs:
            image_paths.extend(collect_images(chapter_dir))
        pdf_path = self._unique_path(album_dir, album_dir.name, ".pdf")
        images_to_pdf(image_paths, pdf_path)
        outputs.append(pdf_path)
        self.log.emit(f"已生成 PDF：{pdf_path}")
        return outputs

    def _make_zip(self, album_dir: Path, suffix: str = ".zip") -> Path:
        zip_path = self._unique_path(album_dir.parent, album_dir.name, suffix)
        # Comic images are already compressed; storing them avoids expensive,
        # ineffective recompression and matches JMComic-qt's fast local output.
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for path in sorted(album_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(album_dir.parent))
        self.log.emit(f"已生成 ZIP：{zip_path}")
        return zip_path

    @staticmethod
    def _chapter_dirs(album_dir: Path) -> List[Path]:
        dirs = [path for path in sorted(album_dir.iterdir()) if path.is_dir()]
        return dirs or [album_dir]

    @staticmethod
    def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
        stem_budget = _child_component_budget(
            directory,
            DOWNLOAD_FILE_PATH_LIMIT,
            reserved_units=_windows_text_units(suffix) + 12,
        )
        if stem_budget < MIN_BOUNDED_NAME_UNITS:
            raise OSError("下载保存路径过长，无法创建输出文件；请缩短下载保存路径")
        bounded_stem = _bounded_safe_name(stem, "output", stem_budget)
        candidate = directory / f"{bounded_stem}{suffix}"
        index = 1
        while candidate.exists():
            candidate = directory / f"{bounded_stem} ({index}){suffix}"
            index += 1
        return candidate


class ReaderWorker(QThread):
    image_ready = Signal(int, str)
    progress = Signal(int, int)
    log = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, album: AlbumMeta, chapter: ChapterMeta, config: DownloadConfig, parent=None, fast_mode: bool = False):
        super().__init__(parent)
        self.album = album
        self.chapter = chapter
        self.config = config
        self.fast_mode = fast_mode
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            download_store = DownloadStore()
            cached_path = download_store.cached_chapter_path(self.chapter.chapter_id)
            if cached_path:
                cached_images = collect_images(cached_path)
                if cached_images:
                    total = len(cached_images)
                    self.log.emit(f"阅读优先使用本地缓存：{cached_path}")
                    self.progress.emit(0, total)
                    for index, image_path in enumerate(cached_images, start=1):
                        if self.cancel_event.is_set():
                            return
                        self.image_ready.emit(index, str(image_path))
                        self.progress.emit(index, total)
                    self.finished_ok.emit()
                    return

            client = JmApiClient(self.config, self.log.emit, self.cancel_event)
            photo = client.get_photo_detail(self.chapter.chapter_id, self.album, fetch_scramble=True)
            total = len(photo.images)
            self.progress.emit(0, total)
            if total == 0:
                raise RuntimeError("该章节没有可阅读图片")

            cache_dir = book_cache_dir(self.album.album_id, max(1, int(self.chapter.index or 1)))

            done = 0
            max_workers = max(6, self.config.image_threads * 2) if self.fast_mode else max(4, self.config.image_threads)
            max_workers = min(12, max_workers)
            self.log.emit(f"阅读后台下载启动：{total} 张图片，线程数 {max_workers}")
            first_name = photo.images[0]
            first_suffix = Path(first_name).suffix.lower()
            first_path = cache_dir / f"{1:05d}{'.gif' if first_suffix == '.gif' else ('.webp' if self.config.cache_as_webp else '.png')}"
            first_index, first_image_path = self._prepare_image(client, photo, 1, first_name, first_path)
            done = 1
            self.image_ready.emit(first_index, str(first_image_path))
            self.progress.emit(done, total)

            next_index = 2
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}

                def submit_next():
                    nonlocal next_index
                    if next_index > total:
                        return
                    image_name = photo.images[next_index - 1]
                    raw_suffix = Path(image_name).suffix.lower()
                    suffix = ".gif" if raw_suffix == ".gif" else (".webp" if self.config.cache_as_webp else ".png")
                    image_path = cache_dir / f"{next_index:05d}{suffix}"
                    future = executor.submit(self._prepare_image, client, photo, next_index, image_name, image_path)
                    futures[future] = next_index
                    next_index += 1

                for _ in range(min(max_workers, total)):
                    submit_next()

                while futures:
                    if self.cancel_event.is_set():
                        return
                    for future in as_completed(list(futures)):
                        futures.pop(future, None)
                        index, image_path = future.result()
                        done += 1
                        self.image_ready.emit(index, str(image_path))
                        self.progress.emit(done, total)
                        submit_next()
                        break

            self.finished_ok.emit()
            download_store.mark_chapter_downloaded(self.album.album_id, self.chapter, cache_dir, len(collect_images(cache_dir)))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _prepare_image(self, client: JmApiClient, photo, index: int, image_name: str, image_path: Path):
        if self.cancel_event.is_set():
            raise RuntimeError("任务已取消")
        if not image_path.exists() or image_path.stat().st_size == 0:
            self._download_image(client, photo, image_name, image_path)
        return index, image_path

    def _download_image(self, client: JmApiClient, photo, image_name: str, image_path: Path):
        last_error = None
        for url in client.build_image_urls(photo, image_name):
            try:
                if not self.fast_mode:
                    time.sleep(random.uniform(0.2, 0.5))
                client.download_image(url, image_path, photo.scramble_id)
                return
            except Exception as exc:
                last_error = exc
                if image_path.exists():
                    image_path.unlink(missing_ok=True)
        raise RuntimeError(f"阅读图片加载失败：{image_name}: {last_error}")
