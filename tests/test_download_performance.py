from __future__ import annotations

import tempfile
import threading
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree

from jm_app.backend.jm_api import PhotoDetail
from jm_app.backend.models import AlbumMeta, ChapterMeta, DownloadConfig
from jm_app.backend.workers import (
    DOWNLOAD_ALBUM_PATH_LIMIT,
    DOWNLOAD_DIRECTORY_PATH_LIMIT,
    DOWNLOAD_FILE_PATH_LIMIT,
    DownloadWorker,
    _windows_path_length,
)
from jm_app.backend.runtime_paths import ui_dir


def download_config(output_dir: Path, **values) -> DownloadConfig:
    defaults = {
        "cookie_header": "",
        "user_agent": "test",
        "delay_min": 0,
        "delay_max": 0,
        "retries": 0,
        "backoff_seconds": 0,
        "stop_on_block": False,
        "output_dir": output_dir,
        "output_format": "images",
    }
    defaults.update(values)
    return DownloadConfig(**defaults)


class _DownloadStoreStub:
    @staticmethod
    def cached_chapter_path(_chapter_id):
        return None

    @staticmethod
    def mark_chapter_downloaded(*_args):
        return None


class _ImageClientStub:
    @staticmethod
    def build_image_urls(_photo, image_name):
        return [f"https://images.invalid/{image_name}"]

    @staticmethod
    def download_image(_url, path, _scramble_id, progress_callback=None):
        time.sleep(0.04)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        if progress_callback is not None:
            progress_callback(5)
        return 5


class DownloadPerformanceTest(unittest.TestCase):
    def test_default_picture_threads_match_jmcomic_qt(self):
        with tempfile.TemporaryDirectory() as directory:
            config = download_config(Path(directory))
        self.assertEqual(config.image_threads, 5)

        root = ElementTree.parse(ui_dir() / "settings.ui").getroot()
        spinbox = root.find(".//widget[@name='imageThreadsSpin']")
        value = spinbox.find("./property[@name='value']/number")
        self.assertEqual(value.text, "5")

    def test_picture_downloads_have_no_artificial_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = DownloadWorker([], download_config(Path(directory)))
            album = AlbumMeta("1", "test", "")
            photo = PhotoDetail("1", "1", "test", 1, "0", "images.invalid", ["1.jpg"])
            with patch(
                "jm_app.backend.workers.random.uniform",
                side_effect=AssertionError("per-image delay must not be used"),
            ):
                worker._download_image_slot(
                    _ImageClientStub(), album, photo, 1, "1.jpg", Path(directory)
                )
            self.assertTrue((Path(directory) / "00001.jpg").exists())

    def test_five_picture_workers_run_concurrently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = DownloadWorker([], download_config(root, image_threads=5))
            album = AlbumMeta("1", "test", "")
            chapter = ChapterMeta("1", "chapter", "", 1)
            photo = PhotoDetail(
                "1",
                "1",
                "test",
                1,
                "0",
                "images.invalid",
                [f"{index}.jpg" for index in range(10)],
            )
            lock = threading.Lock()
            release = threading.Event()
            five_started = threading.Event()
            active = 0
            peak_active = 0

            class ConcurrentImageClient(_ImageClientStub):
                @staticmethod
                def download_image(_url, path, _scramble_id, progress_callback=None):
                    nonlocal active, peak_active
                    with lock:
                        active += 1
                        peak_active = max(peak_active, active)
                        if active == 5:
                            five_started.set()
                    try:
                        release.wait()
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b"image")
                        if progress_callback is not None:
                            progress_callback(5)
                        return 5
                    finally:
                        with lock:
                            active -= 1

            with ThreadPoolExecutor(max_workers=1) as invocation_executor:
                future = invocation_executor.submit(
                    worker._download_chapter,
                    ConcurrentImageClient(),
                    album,
                    chapter,
                    root,
                    _DownloadStoreStub(),
                    photo,
                )
                try:
                    reached_expected_concurrency = five_started.wait(timeout=2)
                finally:
                    release.set()
                future.result(timeout=5)

            self.assertTrue(reached_expected_concurrency)
            self.assertGreaterEqual(peak_active, 5)
            self.assertEqual(len(list(root.rglob("*.jpg"))), 10)

    def test_non_pdf_outputs_do_not_generate_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = DownloadWorker([], download_config(root, output_format="images"))
            worker._make_pdf_outputs = Mock(side_effect=AssertionError("unexpected PDF"))
            self.assertEqual(worker._finalize_album_outputs(root, []), [root])
            worker._make_pdf_outputs.assert_not_called()

    def test_zip_uses_fast_store_for_compressed_comic_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "album"
            root.mkdir()
            (root / "00001.jpg").write_bytes(b"already-compressed-image")
            worker = DownloadWorker(
                [], download_config(Path(directory), output_format="zip")
            )
            zip_path = worker._make_zip(root)
            with zipfile.ZipFile(zip_path) as archive:
                self.assertTrue(archive.infolist())
                self.assertTrue(
                    all(item.compress_type == zipfile.ZIP_STORED for item in archive.infolist())
                )

    def test_failed_attempt_never_deletes_existing_album_chapters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            album_dir = root / "JM1-existing"
            existing_chapter = album_dir / "001-existing"
            existing_chapter.mkdir(parents=True)
            existing_image = existing_chapter / "00001.jpg"
            existing_image.write_bytes(b"existing-complete-image")

            attempt_dir = root / ".JM1-existing.partial-test"
            failed_chapter = attempt_dir / "002-new"
            failed_chapter.mkdir(parents=True)
            (failed_chapter / "00001.jpg").write_bytes(b"partial")
            failed_output = root / "JM1-existing.partial.zip"
            failed_output.write_bytes(b"partial archive")

            worker = DownloadWorker([], download_config(root))
            worker._cleanup_incomplete_album(
                album_dir,
                [failed_output],
                attempt_dir,
            )

            self.assertTrue(existing_image.exists())
            self.assertEqual(existing_image.read_bytes(), b"existing-complete-image")
            self.assertFalse(attempt_dir.exists())
            self.assertFalse(failed_output.exists())

    def test_complete_staged_chapter_is_published_after_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chapter_dir = root / "album" / "002-new"
            staged_dir = root / "attempt" / "002-new"
            staged_dir.mkdir(parents=True)
            staged_image = staged_dir / "00001.jpg"
            staged_image.write_bytes(b"complete")

            DownloadWorker._commit_staged_chapter(staged_dir, chapter_dir)

            self.assertFalse(staged_dir.exists())
            self.assertEqual((chapter_dir / "00001.jpg").read_bytes(), b"complete")

    def test_long_album_and_chapter_titles_stay_within_windows_path_limits(self):
        title = (
            "让我来教你吧♥〜巨乳美人大姐姐和落榜生的我〇〇〇的故事〜 [白杨汉化组] "
            "(C105) [パイレーツキャット] 教えてアゲル♥〜巨乳美人お姉さんと浪人生の僕の"
            "○○なお话・前编〜 [中国翻译] [DL版]"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = DownloadWorker([], download_config(root, image_threads=1))
            album = AlbumMeta("1060422", title, "")
            chapter = ChapterMeta("1060422", title, "", 1)
            album_dir = worker._album_directory(album)
            album_dir.mkdir(parents=True)
            attempt_dir = root / f"{worker._attempt_directory_prefix(album)}u40niljt"
            attempt_dir.mkdir()
            photo = PhotoDetail(
                "1060422",
                "1060422",
                title,
                1,
                "0",
                "images.invalid",
                ["1.jpg"],
            )

            worker._download_chapter(
                _ImageClientStub(),
                album,
                chapter,
                album_dir,
                _DownloadStoreStub(),
                photo,
                chapter_staging_root=attempt_dir,
            )

            images = list(album_dir.rglob("*.jpg"))
            self.assertEqual(len(images), 1)
            self.assertLessEqual(_windows_path_length(album_dir), DOWNLOAD_ALBUM_PATH_LIMIT)
            self.assertLessEqual(
                _windows_path_length(images[0].parent), DOWNLOAD_DIRECTORY_PATH_LIMIT
            )
            self.assertLessEqual(_windows_path_length(images[0]), DOWNLOAD_FILE_PATH_LIMIT)
            self.assertNotIn(title, worker._attempt_directory_prefix(album))

    def test_long_chapter_retry_uses_short_backup_name_and_preserves_new_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            album_dir = root / ("JM1-" + "a" * 120)
            album_dir.mkdir()
            chapter = ChapterMeta("99", "b" * 120, "", 1)
            attempt_one = root / ".JM1.partial-first"
            attempt_two = root / ".JM1.partial-second"
            attempt_one.mkdir()
            attempt_two.mkdir()
            chapter_name = DownloadWorker._chapter_directory_name(
                chapter, album_dir, attempt_one, attempt_two
            )
            chapter_dir = album_dir / chapter_name
            staged_one = attempt_one / chapter_name
            staged_one.mkdir()
            (staged_one / "00001.jpg").write_bytes(b"old")
            DownloadWorker._commit_staged_chapter(staged_one, chapter_dir)
            staged_two = attempt_two / chapter_name
            staged_two.mkdir()
            (staged_two / "00001.jpg").write_bytes(b"new")

            DownloadWorker._commit_staged_chapter(staged_two, chapter_dir)

            self.assertEqual((chapter_dir / "00001.jpg").read_bytes(), b"new")
            self.assertFalse(list(album_dir.glob(".previous-*")))

    def test_cancel_stops_submitting_images_and_returns_without_draining_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = DownloadWorker([], download_config(root, image_threads=2))
            album = AlbumMeta("1", "test", "")
            chapter = ChapterMeta("1", "chapter", "", 1)
            photo = PhotoDetail(
                "1",
                "1",
                "test",
                1,
                "0",
                "images.invalid",
                [f"{index}.jpg" for index in range(30)],
            )
            started = []
            two_started = threading.Event()
            finished = threading.Event()
            errors = []

            def blocking_slot(_album, _photo, image_index, _name, _download_dir):
                started.append(image_index)
                if len(started) >= 2:
                    two_started.set()
                worker.cancel_event.wait()
                raise RuntimeError("cancelled slot")

            def run_chapter():
                try:
                    worker._download_chapter(
                        _ImageClientStub(),
                        album,
                        chapter,
                        root,
                        _DownloadStoreStub(),
                        photo,
                        download_slot=blocking_slot,
                    )
                except Exception as exc:
                    errors.append(exc)
                finally:
                    finished.set()

            thread = threading.Thread(target=run_chapter)
            thread.start()
            self.assertTrue(two_started.wait(1), "image workers did not start")
            worker.cancel()
            self.assertTrue(finished.wait(1), "cancel waited for the full image queue")
            thread.join(1)

            self.assertFalse(thread.is_alive())
            self.assertTrue(errors)
            self.assertIn("取消", str(errors[0]))
            self.assertLessEqual(len(started), 4)

    def test_images_output_always_keeps_image_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            album_dir = Path(directory) / "album"
            album_dir.mkdir()
            (album_dir / "00001.jpg").write_bytes(b"image")
            worker = DownloadWorker(
                [], download_config(Path(directory), output_format="images", keep_images=False)
            )

            outputs = worker._finalize_validated_album_outputs(
                AlbumMeta("1", "test", ""), album_dir, []
            )

            self.assertEqual(outputs, [album_dir])
            self.assertTrue((album_dir / "00001.jpg").exists())

    def test_zip_and_cbz_remove_images_only_after_valid_archive(self):
        for output_format, suffix in (("zip", ".zip"), ("cbz", ".cbz")):
            with self.subTest(output_format=output_format), tempfile.TemporaryDirectory() as directory:
                album_dir = Path(directory) / "album"
                album_dir.mkdir()
                (album_dir / "00001.jpg").write_bytes(b"image")
                worker = DownloadWorker(
                    [],
                    download_config(
                        Path(directory),
                        output_format=output_format,
                        keep_images=False,
                    ),
                )

                outputs = worker._finalize_validated_album_outputs(
                    AlbumMeta("1", "test", ""), album_dir, []
                )

                self.assertEqual(outputs[0].suffix, suffix)
                self.assertTrue(outputs[0].exists())
                self.assertFalse(album_dir.exists())

    def test_pdf_removes_source_images_but_keeps_generated_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            album_dir = Path(directory) / "album"
            chapter_dir = album_dir / "001-chapter"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "00001.jpg").write_bytes(b"image")
            worker = DownloadWorker(
                [], download_config(Path(directory), output_format="pdf", keep_images=False)
            )

            def make_pdf(_album_dir, _chapters):
                path = album_dir / "album.pdf"
                path.write_bytes(b"pdf")
                return [path]

            worker._make_pdf_outputs = make_pdf
            outputs = worker._finalize_validated_album_outputs(
                AlbumMeta("1", "test", ""), album_dir, []
            )

            self.assertTrue(outputs[0].exists())
            self.assertFalse(list(album_dir.rglob("*.jpg")))

    def test_conversion_failure_keeps_images_as_successful_fallback(self):
        for output_format, method_name in (("zip", "_make_zip"), ("cbz", "_make_zip"), ("pdf", "_make_pdf_outputs")):
            with self.subTest(output_format=output_format), tempfile.TemporaryDirectory() as directory:
                album_dir = Path(directory) / "album"
                album_dir.mkdir()
                image_path = album_dir / "00001.jpg"
                image_path.write_bytes(b"image")
                worker = DownloadWorker(
                    [],
                    download_config(
                        Path(directory),
                        output_format=output_format,
                        keep_images=False,
                    ),
                )
                setattr(worker, method_name, Mock(side_effect=RuntimeError("convert failed")))

                outputs = worker._finalize_validated_album_outputs(
                    AlbumMeta("1", "test", ""), album_dir, []
                )

                self.assertEqual(outputs, [album_dir])
                self.assertTrue(image_path.exists())


if __name__ == "__main__":
    unittest.main()
