import random
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .cache_db import ComicCacheDB
from .constants import DEFAULT_USER_AGENT, LIST_URL
from .cookie_store import load_cookie_header
from .jm_api import JmApiClient, parse_jm_id
from .jmcomic_defaults import jmcomic_default_cookie_header
from .models import AlbumMeta, ChapterMeta, DownloadConfig, NetworkConfig
from .pdf_utils import collect_images, images_to_pdf
from .schemas import AlbumSchema, ChapterSchema, DownloadJobStatus, DownloadSettings, NetworkSettings
from .utils import safe_name


def chapter_to_schema(chapter: ChapterMeta) -> ChapterSchema:
    return ChapterSchema(**asdict(chapter))


def album_to_schema(album: AlbumMeta) -> AlbumSchema:
    return AlbumSchema(
        album_id=album.album_id,
        title=album.title,
        url=album.url,
        likes=album.likes,
        favorites=album.favorites,
        source=album.source,
        cover_url=album.cover_url,
        author=album.author,
        page_count=album.page_count,
        tags=list(album.tags),
        chapters=[chapter_to_schema(chapter) for chapter in album.chapters],
        selected_chapter_ids=list(album.selected_chapter_ids),
    )


def schema_to_chapter(chapter: ChapterSchema) -> ChapterMeta:
    return ChapterMeta(
        chapter_id=chapter.chapter_id,
        title=chapter.title,
        url=chapter.url,
        index=chapter.index,
    )


def schema_to_album(album: AlbumSchema) -> AlbumMeta:
    return AlbumMeta(
        album_id=album.album_id,
        title=album.title,
        url=album.url,
        likes=album.likes,
        favorites=album.favorites,
        source=album.source,
        cover_url=album.cover_url,
        author=album.author,
        page_count=album.page_count,
        tags=list(album.tags),
        chapters=[schema_to_chapter(chapter) for chapter in album.chapters],
        selected_chapter_ids=list(album.selected_chapter_ids),
    )


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
    )


def download_config(settings: Optional[DownloadSettings] = None) -> DownloadConfig:
    source = settings or DownloadSettings()
    base = network_config(source)
    return DownloadConfig(
        cookie_header=base.cookie_header,
        user_agent=base.user_agent,
        delay_min=base.delay_min,
        delay_max=base.delay_max,
        retries=base.retries,
        backoff_seconds=base.backoff_seconds,
        stop_on_block=base.stop_on_block,
        username=base.username,
        password=base.password,
        proxy=base.proxy,
        detail_threads=base.detail_threads,
        output_dir=Path(source.output_dir).expanduser(),
        image_threads=source.image_threads,
        output_format=source.output_format,
        pdf_split_chapters=source.pdf_split_chapters,
        keep_images=source.keep_images,
        use_jmcomic=source.use_jmcomic,
        reading_mode=source.reading_mode,
        cache_as_webp=source.cache_as_webp,
    )


def search_albums(
    query: str = "",
    rank_type: str = "day",
    page: int = 1,
    include_detail: bool = False,
    settings: Optional[NetworkSettings] = None,
) -> List[AlbumSchema]:
    logs: List[str] = []
    cancel_event = threading.Event()
    config = network_config(settings)
    client = JmApiClient(config, logs.append, cancel_event)
    albums = client.search(query, page=page) if query.strip() else client.ranking(rank_type, page=page)
    if include_detail and albums:
        api_domains = client._get_api_domains()
        albums = load_album_details([album.album_id for album in albums], config, api_domains, cancel_event)
    db = ComicCacheDB()
    for album in albums:
        db.upsert_album(album)
    return [album_to_schema(album) for album in albums]


def load_album_details(
    album_ids: Iterable[str],
    config: NetworkConfig,
    api_domains: Optional[List[str]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> List[AlbumMeta]:
    ids = list(album_ids)
    cancel = cancel_event or threading.Event()

    def load_one(album_id: str) -> AlbumMeta:
        client = JmApiClient(config, None, cancel)
        if api_domains:
            client._api_domains = list(api_domains)
            client._domains_initialized = True
        if album_id.lower().startswith("p"):
            return client.photo_as_album(album_id[1:])
        return client.get_album_detail(album_id)

    results: List[Optional[AlbumMeta]] = [None] * len(ids)
    max_workers = min(max(1, config.detail_threads), max(1, len(ids)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(load_one, album_id): index for index, album_id in enumerate(ids)}
        for future in as_completed(futures):
            if cancel.is_set():
                break
            results[futures[future]] = future.result()
    return [album for album in results if album is not None]


def get_album_detail(album_id: str, settings: Optional[NetworkSettings] = None) -> AlbumSchema:
    config = network_config(settings)
    client = JmApiClient(config)
    album = client.photo_as_album(album_id[1:]) if album_id.lower().startswith("p") else client.get_album_detail(album_id)
    ComicCacheDB().upsert_album(album)
    return album_to_schema(album)


def get_cached_albums(limit: int = 120) -> List[AlbumSchema]:
    return [album_to_schema(album) for album in ComicCacheDB().recent_albums(limit)]


class DownloadJob:
    def __init__(self, albums: List[AlbumMeta], config: DownloadConfig):
        self.job_id = uuid.uuid4().hex
        self.albums = albums
        self.config = config
        self.cancel_event = threading.Event()
        self.logs: List[str] = []
        self.outputs: List[str] = []
        self.status = "queued"
        self.current_album_id = ""
        self.current_title = ""
        self.done = 0
        self.total = max(1, sum(self._chapter_count(album) for album in albums))
        self.error = ""
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, name=f"comic18-download-{self.job_id}", daemon=True)

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancel_event.set()
        self.log("正在取消下载任务。")

    def log(self, message: str):
        with self.lock:
            self.logs.append(time.strftime("[%H:%M:%S] ") + message)
            self.logs = self.logs[-300:]

    def set_status(self, status: str):
        with self.lock:
            self.status = status

    def set_current_album(self, album: AlbumMeta):
        with self.lock:
            self.current_album_id = album.album_id
            self.current_title = album.title

    def increment_done(self, amount: int = 1):
        with self.lock:
            self.done = min(self.total, self.done + amount)

    def adjust_total(self, estimated_total: int, actual_total: int):
        estimated_total = max(1, estimated_total)
        actual_total = max(1, actual_total)
        if estimated_total == actual_total:
            return
        with self.lock:
            self.total = max(1, self.total + actual_total - estimated_total)
            self.done = min(self.done, self.total)

    def add_output(self, output: Path):
        with self.lock:
            self.outputs.append(str(output))

    def fail(self, exc: Exception):
        with self.lock:
            self.error = str(exc)
            self.status = "failed"

    def snapshot(self) -> DownloadJobStatus:
        with self.lock:
            return DownloadJobStatus(
                job_id=self.job_id,
                status=self.status,
                current_album_id=self.current_album_id,
                current_title=self.current_title,
                done=self.done,
                total=self.total,
                logs=list(self.logs),
                outputs=list(self.outputs),
                error=self.error,
            )

    def run(self):
        try:
            self.set_status("running")
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            for album in self.albums:
                if self.cancel_event.is_set():
                    self.set_status("cancelled")
                    return
                self.set_current_album(album)
                self.log(f"开始下载 {album.title}")
                for output in self._download_album(album):
                    self.add_output(output)
                self.log(f"完成 {album.title}")
            self.set_status("cancelled" if self.cancel_event.is_set() else "finished")
        except Exception as exc:
            self.fail(exc)
            self.log(f"下载失败：{exc}")

    def _chapter_count(self, album: AlbumMeta) -> int:
        if album.selected_chapter_ids:
            return len(album.selected_chapter_ids)
        return max(1, len(album.chapters))

    def _download_album(self, album: AlbumMeta) -> List[Path]:
        estimated_chapter_total = self._chapter_count(album)
        client = JmApiClient(self.config, self.log, self.cancel_event)
        detail = client.photo_as_album(album.album_id[1:]) if album.album_id.lower().startswith("p") else client.get_album_detail(album.album_id)
        chapters = album.chapters or detail.chapters
        cache_db = ComicCacheDB()
        detail.selected_chapter_ids = list(album.selected_chapter_ids)
        cache_db.upsert_album(detail)
        if album.selected_chapter_ids:
            wanted = set(album.selected_chapter_ids)
            chapters = [chapter for chapter in chapters if chapter.chapter_id in wanted]
        if not chapters:
            chapters = [ChapterMeta(parse_jm_id(album.album_id), "全集", album.url, 1)]
        self.adjust_total(estimated_chapter_total, len(chapters))

        album_dir = self.config.output_dir / f"JM{album.album_id}-{safe_name(album.title, album.album_id)}"
        album_dir.mkdir(parents=True, exist_ok=True)
        for chapter in chapters:
            if self.cancel_event.is_set():
                return []
            self._download_chapter(client, album, chapter, album_dir, cache_db)
            self.increment_done()
            client.sleep()

        if self.config.output_format == "images":
            outputs = [album_dir]
        elif self.config.output_format == "zip":
            outputs = [self._make_zip(album_dir)]
        elif self.config.output_format == "pdf":
            outputs = self._make_pdf_outputs(album_dir, chapters)
        else:
            raise RuntimeError(f"不支持的保存格式：{self.config.output_format}")

        if self.config.output_format in {"zip", "pdf"} and not self.config.keep_images:
            shutil.rmtree(album_dir, ignore_errors=True)
        return outputs

    def _download_chapter(self, client: JmApiClient, album: AlbumMeta, chapter: ChapterMeta, album_dir: Path, cache_db: ComicCacheDB):
        chapter_name = f"{chapter.index:03d}-{safe_name(chapter.title, chapter.chapter_id)}"
        chapter_dir = album_dir / chapter_name
        cached_path = cache_db.cached_chapter_path(chapter.chapter_id)
        if cached_path and collect_images(cached_path):
            if cached_path.resolve() != chapter_dir.resolve():
                self._mirror_cached_chapter(cached_path, chapter_dir)
            self.log(f"跳过已缓存章节：{chapter.title}")
            return

        photo = client.get_photo_detail(chapter.chapter_id, album, fetch_scramble=True)
        if not photo.images:
            self.log(f"未在章节 {chapter.title} 找到图片。")
            return
        chapter_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"下载章节 {chapter.title}：{len(photo.images)} 张图片")
        with ThreadPoolExecutor(max_workers=max(1, self.config.image_threads)) as executor:
            futures = [
                executor.submit(self._download_image_slot, client, photo, image_index, image_name, chapter_dir)
                for image_index, image_name in enumerate(photo.images, start=1)
            ]
            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    return
                future.result()
        cache_db.mark_chapter_downloaded(album.album_id, chapter, chapter_dir, len(collect_images(chapter_dir)))

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

    def _download_image_slot(self, client, photo, image_index: int, image_name: str, chapter_dir: Path):
        raw_suffix = Path(image_name).suffix.lower() or ".jpg"
        suffix = ".webp" if self.config.cache_as_webp and raw_suffix != ".gif" else raw_suffix
        filename = chapter_dir / f"{image_index:05d}{suffix}"
        if filename.exists() and filename.stat().st_size > 0:
            return
        last_error = None
        for url in client.build_image_urls(photo, image_name):
            try:
                time.sleep(random.uniform(0.2, 0.5))
                client.download_image(url, filename, photo.scramble_id)
                return
            except Exception as exc:
                last_error = exc
                if filename.exists():
                    filename.unlink(missing_ok=True)
        raise RuntimeError(f"图片下载失败：{image_name}: {last_error}")

    def _make_pdf_outputs(self, album_dir: Path, chapters: List[ChapterMeta]) -> List[Path]:
        if self.config.pdf_split_chapters and len(chapters) > 1:
            outputs = []
            for chapter_dir in self._chapter_dirs(album_dir):
                pdf_path = self._unique_path(album_dir.parent, f"{album_dir.name} - {chapter_dir.name}", ".pdf")
                images_to_pdf(collect_images(chapter_dir), pdf_path)
                outputs.append(pdf_path)
            return outputs
        image_paths = []
        for chapter_dir in self._chapter_dirs(album_dir):
            image_paths.extend(collect_images(chapter_dir))
        pdf_path = self._unique_path(album_dir.parent, album_dir.name, ".pdf")
        images_to_pdf(image_paths, pdf_path)
        return [pdf_path]

    def _make_zip(self, album_dir: Path) -> Path:
        zip_path = self._unique_path(album_dir.parent, album_dir.name, ".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(album_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(album_dir.parent))
        return zip_path

    @staticmethod
    def _chapter_dirs(album_dir: Path) -> List[Path]:
        dirs = [path for path in sorted(album_dir.iterdir()) if path.is_dir()]
        return dirs or [album_dir]

    @staticmethod
    def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
        candidate = directory / f"{stem}{suffix}"
        index = 1
        while candidate.exists():
            candidate = directory / f"{stem} ({index}){suffix}"
            index += 1
        return candidate


class DownloadJobManager:
    def __init__(self):
        self.jobs: Dict[str, DownloadJob] = {}
        self.lock = threading.Lock()

    def start(self, albums: List[AlbumMeta], config: DownloadConfig) -> DownloadJobStatus:
        job = DownloadJob(albums, config)
        with self.lock:
            self.jobs[job.job_id] = job
        job.start()
        return job.snapshot()

    def get(self, job_id: str) -> Optional[DownloadJobStatus]:
        with self.lock:
            job = self.jobs.get(job_id)
        return job.snapshot() if job else None

    def cancel(self, job_id: str) -> Optional[DownloadJobStatus]:
        with self.lock:
            job = self.jobs.get(job_id)
        if not job:
            return None
        job.cancel()
        return job.snapshot()


download_jobs = DownloadJobManager()
