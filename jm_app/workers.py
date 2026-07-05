import threading
import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

from PyQt5.QtCore import QThread, pyqtSignal

from .jm_api import JmApiClient, parse_jm_id
from .models import AlbumMeta, ChapterMeta, DownloadConfig, NetworkConfig
from .pdf_utils import collect_images, images_to_pdf
from .utils import safe_name


def ensure_album_id(expected_id: str, actual_id: str, requested_url: str, actual_url: str):
    if expected_id and actual_id and expected_id != actual_id:
        raise RuntimeError(
            "Requested album ID "
            f"{expected_id}, but the site returned album ID {actual_id}. "
            f"Requested URL: {requested_url}; final URL: {actual_url or requested_url}. "
            "Check that the input is an album ID/link, not a photo/chapter ID."
        )


class ScrapeWorker(QThread):
    album_found = pyqtSignal(object)
    album_found_at = pyqtSignal(int, object)
    total_known = pyqtSignal(int)
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        list_url: str,
        ids: List[str],
        include_detail: bool,
        config: NetworkConfig,
        search_query: str = "",
        rank_type: str = "day",
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
            else:
                self.log.emit(f"正在通过 App API 获取排行榜，第 {self.start_page} 页。")
                albums = self._emit_album_pages(client, api_domains, rank_type=self.rank_type)
            found_count = len(albums)
            self.log.emit(f"获取到 {found_count} 个漫画，结果区将按窗口宽度分页显示。")
            self.total_known.emit(found_count)

            total = len(albums)
            self.progress.emit(0, total)
            if self.include_detail:
                self.log.emit(f"正在并发加载详情，线程数：{self._detail_threads(total)}")
                self._emit_parallel_details([album.album_id for album in albums], api_domains)
            else:
                for index, album in enumerate(albums, start=1):
                    if self.cancel_event.is_set():
                        self.log.emit("采集已取消。")
                        break
                    self.album_found.emit(album)
                    self.album_found_at.emit(index - 1, album)
                    self.progress.emit(index, total)

            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _emit_album_pages(
        self,
        client: JmApiClient,
        api_domains: List[str],
        search_query: str = "",
        rank_type: str = "day",
    ) -> List[AlbumMeta]:
        albums: List[AlbumMeta] = []
        seen = set()
        page = self.start_page
        while page <= self.start_page:
            if self.cancel_event.is_set():
                break
            client._api_domains = list(api_domains)
            client._domains_initialized = True
            page_albums = client.search(search_query, page=page) if search_query else client.ranking(rank_type, page=page)
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

    def _emit_parallel_details(self, item_ids: List[str], api_domains: List[str]):
        total = len(item_ids)
        self.progress.emit(0, total)
        if total == 0:
            return

        done = 0
        with ThreadPoolExecutor(max_workers=self._detail_threads(total)) as executor:
            futures = {
                executor.submit(self._load_one_detail, item_id, api_domains): index
                for index, item_id in enumerate(item_ids)
            }
            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    self.log.emit("采集已取消。")
                    break
                index = futures[future]
                album = future.result()
                self.album_found.emit(album)
                self.album_found_at.emit(index, album)
                done += 1
                self.progress.emit(done, total)

    def _load_one_detail(self, item_id: str, api_domains: List[str]) -> AlbumMeta:
        client = JmApiClient(self.config, self.log.emit, self.cancel_event)
        client._api_domains = list(api_domains)
        client._domains_initialized = True
        if item_id.lower().startswith("p"):
            return client.photo_as_album(item_id[1:])
        return client.get_album_detail(item_id)

    def _detail_threads(self, total: int) -> int:
        return min(max(1, self.config.detail_threads), max(1, total))


class ChapterWorker(QThread):
    chapters_loaded = pyqtSignal(str, object)
    log = pyqtSignal(str)
    failed = pyqtSignal(str)

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
            self.chapters_loaded.emit(self.album.album_id, chapters)
            self.log.emit(f"已加载 {self.album.title} 的 {len(chapters)} 个章节。")
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    item_done = pyqtSignal(object, str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, albums: List[AlbumMeta], config: DownloadConfig, parent=None):
        super().__init__(parent)
        self.albums = albums
        self.config = config
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            total = max(1, sum(self._chapter_count(album) for album in self.albums))
            done = 0
            self.progress.emit(0, total)

            for album in self.albums:
                if self.cancel_event.is_set():
                    self.log.emit("下载已取消。")
                    break
                chapter_paths = self._download_album(album)
                for pdf_path in chapter_paths:
                    self.item_done.emit(album, str(pdf_path))
                    done += 1
                    self.progress.emit(done, total)

            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _chapter_count(self, album: AlbumMeta) -> int:
        if album.selected_chapter_ids:
            return len(album.selected_chapter_ids)
        return max(1, len(album.chapters))

    def _download_album(self, album: AlbumMeta) -> List[Path]:
        client = JmApiClient(self.config, self.log.emit, self.cancel_event)
        if album.album_id.lower().startswith("p"):
            detail = client.photo_as_album(album.album_id[1:])
        else:
            detail = client.get_album_detail(album.album_id)
        chapters = album.chapters or detail.chapters
        if album.selected_chapter_ids:
            wanted = set(album.selected_chapter_ids)
            chapters = [chapter for chapter in chapters if chapter.chapter_id in wanted]
        if not chapters:
            chapters = [ChapterMeta(parse_jm_id(album.album_id), "全集", album.url, 1)]

        self.log.emit(f"开始下载 {album.title}，章节数：{len(chapters)}")
        album_dir = self.config.output_dir / f"JM{album.album_id}-{safe_name(album.title, album.album_id)}"
        album_dir.mkdir(parents=True, exist_ok=True)

        output_paths: List[Path] = []
        for chapter in chapters:
            if self.cancel_event.is_set():
                return output_paths
            self._download_chapter(client, album, chapter, album_dir)
            client.sleep()

        if self.config.output_format == "images":
            output_paths.append(album_dir)
        elif self.config.output_format == "zip":
            output_paths.append(self._make_zip(album_dir))
        elif self.config.output_format == "pdf":
            output_paths.extend(self._make_pdf_outputs(album_dir, chapters))
        else:
            raise RuntimeError(f"不支持的保存格式：{self.config.output_format}")

        if self.config.output_format in {"zip", "pdf"} and not self.config.keep_images:
            shutil.rmtree(album_dir, ignore_errors=True)
            self.log.emit(f"已删除图片目录：{album_dir}")
        return output_paths

    def _download_chapter(
        self,
        client: JmApiClient,
        album: AlbumMeta,
        chapter: ChapterMeta,
        album_dir: Path,
    ):
        photo = client.get_photo_detail(chapter.chapter_id, album, fetch_scramble=True)
        if not photo.images:
            self.log.emit(f"未在章节 {chapter.title} 找到图片。")
            return

        chapter_name = f"{chapter.index:03d}-{safe_name(chapter.title, chapter.chapter_id)}"
        chapter_dir = album_dir / chapter_name
        chapter_dir.mkdir(parents=True, exist_ok=True)

        self.log.emit(f"下载章节 {chapter.title}：{len(photo.images)} 张图片")
        with ThreadPoolExecutor(max_workers=max(1, self.config.image_threads)) as executor:
            futures = [
                executor.submit(self._download_image_slot, client, photo, image_index, image_name, chapter_dir)
                for image_index, image_name in enumerate(photo.images, start=1)
            ]
            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    return
                future.result()

    def _download_image_slot(self, client: JmApiClient, photo, image_index: int, image_name: str, chapter_dir: Path):
        if self.cancel_event.is_set():
            return
        suffix = Path(image_name).suffix or ".jpg"
        filename = chapter_dir / f"{image_index:05d}{suffix}"
        if filename.exists() and filename.stat().st_size > 0:
            return

        last_error = None
        for url in client.build_image_urls(photo, image_name):
            try:
                client.download_image(url, filename, photo.scramble_id)
                return
            except Exception as exc:
                last_error = exc
                if filename.exists():
                    filename.unlink(missing_ok=True)
        raise RuntimeError(f"图片下载失败：{image_name}: {last_error}")

    def _make_pdf_outputs(self, album_dir: Path, chapters: List[ChapterMeta]) -> List[Path]:
        outputs: List[Path] = []
        if self.config.pdf_split_chapters and len(chapters) > 1:
            for chapter_dir in self._chapter_dirs(album_dir):
                pdf_path = self._unique_path(album_dir.parent, f"{album_dir.name} - {chapter_dir.name}", ".pdf")
                images_to_pdf(collect_images(chapter_dir), pdf_path)
                outputs.append(pdf_path)
                self.log.emit(f"已生成 PDF：{pdf_path}")
            return outputs

        image_paths = []
        for chapter_dir in self._chapter_dirs(album_dir):
            image_paths.extend(collect_images(chapter_dir))
        pdf_path = self._unique_path(album_dir.parent, album_dir.name, ".pdf")
        images_to_pdf(image_paths, pdf_path)
        outputs.append(pdf_path)
        self.log.emit(f"已生成 PDF：{pdf_path}")
        return outputs

    def _make_zip(self, album_dir: Path) -> Path:
        zip_path = self._unique_path(album_dir.parent, album_dir.name, ".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
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
        candidate = directory / f"{stem}{suffix}"
        index = 1
        while candidate.exists():
            candidate = directory / f"{stem} ({index}){suffix}"
            index += 1
        return candidate


class ReaderWorker(QThread):
    image_ready = pyqtSignal(int, str)
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, album: AlbumMeta, chapter: ChapterMeta, config: DownloadConfig, parent=None):
        super().__init__(parent)
        self.album = album
        self.chapter = chapter
        self.config = config
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            client = JmApiClient(self.config, self.log.emit, self.cancel_event)
            photo = client.get_photo_detail(self.chapter.chapter_id, self.album, fetch_scramble=True)
            total = len(photo.images)
            self.progress.emit(0, total)
            if total == 0:
                raise RuntimeError("该章节没有可阅读图片")

            cache_dir = (
                Path(tempfile.gettempdir())
                / "jm_qt_reader"
                / safe_name(self.album.album_id, "album")
                / safe_name(self.chapter.chapter_id, "chapter")
            )
            cache_dir.mkdir(parents=True, exist_ok=True)

            done = 0
            max_workers = max(4, self.config.image_threads)
            self.log.emit(f"阅读后台下载启动：{total} 张图片，线程数 {max_workers}")
            next_index = 1
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}

                def submit_next():
                    nonlocal next_index
                    if next_index > total:
                        return
                    image_name = photo.images[next_index - 1]
                    suffix = ".gif" if Path(image_name).suffix.lower() == ".gif" else ".png"
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
                client.download_image(url, image_path, photo.scramble_id)
                return
            except Exception as exc:
                last_error = exc
                if image_path.exists():
                    image_path.unlink(missing_ok=True)
        raise RuntimeError(f"阅读图片加载失败：{image_name}: {last_error}")
