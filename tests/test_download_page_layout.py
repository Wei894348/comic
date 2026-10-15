from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from jm_app.frontend.pages.appearance import DARK_STYLE
from jm_app.frontend.pages.download import DownloadPageMixin


class _DownloadPageHarness(DownloadPageMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.queue = []
        self.download_history = []
        self.download_workers = {}
        self.download_pending_queue = []
        self.download_card_by_id = {}
        self.theme_dark = False
        self.refreshed = 0
        self.started = 0

    def load_ui_widget(self, template_name, expected_type=None, parent=None):
        path = Path(__file__).resolve().parents[1] / "ui" / template_name
        ui_file = QFile(str(path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Unable to open download form: {path}")
        widget = QUiLoader().load(ui_file, parent)
        ui_file.close()
        return widget

    def cancel_current_task(self):
        return None

    def start_download_queue(self):
        self.started += 1

    def clear_queue(self):
        return None

    def refresh_queue_table(self):
        self.refreshed += 1

    def switch_page(self, index):
        self.switched_to = index

    def history_page_index(self):
        return 3


class DownloadPageLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.harness = _DownloadPageHarness()
        self.panel = self.harness._build_download_panel()

    def tearDown(self):
        self.panel.close()
        self.harness.close()
        self.app.processEvents()

    def test_download_page_removes_visual_log_controls(self):
        self.assertFalse(self.panel.findChildren(QPlainTextEdit))
        self.assertIsNone(self.panel.findChild(QPushButton, "clearLogButton"))
        self.assertIsNone(self.panel.findChild(QWidget, "logArea"))
        self.assertIsNone(self.harness.log_box)

    def test_download_page_only_keeps_active_download_view(self):
        stack = self.panel.findChild(QStackedWidget, "downloadQueueStack")
        self.assertEqual(stack.count(), 2)
        self.assertEqual(stack.currentIndex(), 1)
        self.assertIsNone(self.panel.findChild(QFrame, "downloadSidebar"))
        for object_name in (
            "downloadListNavButton",
            "downloadTaskNavButton",
            "downloadHistoryNavButton",
            "downloadStatsCard",
        ):
            self.assertIsNone(self.panel.findChild(QWidget, object_name))

    def test_download_queue_header_row_is_removed(self):
        self.assertIsNone(self.panel.findChild(QWidget, "downloadQueueTitle"))
        self.assertIsNone(self.panel.findChild(QWidget, "queueStatusLabel"))
        self.assertIsNone(self.panel.findChild(QHBoxLayout, "queueHeaderLayout"))

    def test_active_view_is_the_only_download_state(self):
        self.harness.update_download_empty_state()

        self.assertEqual(self.harness.download_page_title.text(), "下载任务")
        self.assertEqual(self.harness.download_empty_title.text(), "暂无进行中的任务")
        self.assertIn("未完成", self.harness.download_empty_hint.text())

    def test_unfinished_waiting_tasks_remain_visible(self):
        waiting = SimpleNamespace(album_id="waiting-1")
        self.harness.queue = [waiting]

        self.assertEqual(self.harness.visible_download_queue(), [waiting])

    def test_new_download_is_queued_and_started_automatically_once(self):
        album = SimpleNamespace(album_id="auto-1", title="自动下载")
        self.harness.queue = [album]

        self.harness.queue_automatic_download(album)
        self.harness.queue_automatic_download(album)
        self.app.processEvents()

        self.assertEqual(
            [item.album_id for item in self.harness.download_pending_queue],
            ["auto-1"],
        )
        self.assertEqual(self.harness.started, 1)
        self.assertFalse(self.harness.download_start_scheduled)

    def test_dashboard_separates_active_waiting_paused_and_failed_tasks(self):
        active = SimpleNamespace(album_id="active")
        waiting = SimpleNamespace(album_id="waiting")
        paused = SimpleNamespace(album_id="paused")
        failed = SimpleNamespace(album_id="failed")
        self.harness.queue = [active, waiting, paused, failed]
        self.harness.download_workers = {"active": object()}
        self.harness.download_speeds = {"active": 1536}
        self.harness.set_download_task_state("active", "downloading")
        self.harness.set_download_task_state("waiting", "waiting")
        self.harness.set_download_task_state("paused", "paused")
        self.harness.set_download_task_state("failed", "failed")

        self.harness.update_download_dashboard()

        self.assertEqual(self.harness.download_active_metric.text(), "下载中 1")
        self.assertEqual(
            self.harness.download_waiting_metric.text(),
            "等待 1 · 暂停 1 · 失败 1",
        )
        self.assertEqual(self.harness.download_speed_metric.text(), "1.5 KB/s")

    def test_download_toolbar_exposes_resume_pause_and_clear_waiting_actions(self):
        self.assertEqual(
            self.panel.findChild(QPushButton, "startQueueButton").text(),
            "开始 / 继续",
        )
        self.assertEqual(
            self.panel.findChild(QPushButton, "cancelDownloadsButton").text(),
            "暂停全部",
        )
        self.assertEqual(
            self.panel.findChild(QPushButton, "clearQueueButton").text(),
            "清空等待",
        )

    def test_pause_all_keeps_tasks_for_explicit_resume(self):
        album = SimpleNamespace(album_id="paused-1")
        state_updates = []
        self.harness.queue = [album]
        self.harness.download_pending_queue = [album]
        self.harness.download_controller = SimpleNamespace(
            pause=lambda _album_id: None,
            update_progress=lambda album_id, state: state_updates.append(
                (album_id, state)
            ),
        )

        self.harness.pause_all_downloads()

        self.assertEqual(self.harness.queue, [album])
        self.assertEqual(self.harness.download_pending_queue, [])
        self.assertEqual(
            self.harness.download_task_state("paused-1"), "paused"
        )
        self.assertEqual(state_updates[0][0], "paused-1")

    def test_actions_do_not_overlap_at_minimum_content_width(self):
        self.panel.resize(702, 560)
        self.panel.show()
        self.app.processEvents()

        workspace = self.panel.findChild(QFrame, "downloadWorkspace")
        buttons = [
            self.panel.findChild(QPushButton, name)
            for name in (
                "clearQueueButton",
                "cancelDownloadsButton",
                "startQueueButton",
            )
        ]
        self.assertTrue(all(buttons))
        for left, right in zip(buttons, buttons[1:]):
            self.assertLess(left.geometry().right(), right.geometry().left())
        self.assertLessEqual(buttons[-1].geometry().right(), workspace.contentsRect().right())

    def test_download_page_has_dark_theme_overrides(self):
        for selector in (
            "QFrame#downloadPanel",
            "QFrame#downloadWorkspace",
            "QProgressBar#downloadProgress",
        ):
            self.assertIn(selector, DARK_STYLE)

    def test_download_cover_uses_portrait_dimensions(self):
        from xml.etree import ElementTree

        root = ElementTree.parse(
            Path(__file__).resolve().parents[1] / "ui" / "download_card.ui"
        ).getroot()
        cover = next(
            widget
            for widget in root.iter("widget")
            if widget.attrib.get("name") == "downloadCover"
        )
        size = cover.find("./property[@name='minimumSize']/size")

        self.assertEqual(size.findtext("width"), "82")
        self.assertEqual(size.findtext("height"), "110")

    def test_priority_cover_request_moves_a_queued_cover_to_front(self):
        from jm_app.frontend.ui import MainWindow

        host = SimpleNamespace(cover_request_queue=[
            ("1", ["one"], True),
            ("2", ["two"], True),
        ])

        MainWindow.promote_queued_cover_request(host, "2")

        self.assertEqual([item[0] for item in host.cover_request_queue], ["2", "1"])

    def test_image_callbacks_are_coalesced_before_ui_and_database_update(self):
        calls = []
        self.harness.download_controller = SimpleNamespace(
            update_progress=lambda *args, **kwargs: calls.append((args, kwargs))
        )
        self.harness.download_progress_pending = set()
        self.harness.download_cancelled_ids = set()
        self.harness.download_totals = {"1": 1}
        self.harness.download_done_counts = {"1": 0}
        self.harness.download_chapter_totals = {"1": 1}
        self.harness.download_chapter_done_counts = {"1": 0}
        self.harness.download_percent_by_id = {}
        self.harness.queue_chapter_count = lambda _album: 1
        self.harness.update_download_summary = lambda: None
        self.harness.download_percent = lambda done, total: round(done * 100 / total)
        album = SimpleNamespace(album_id="1")

        self.harness.queue_download_progress_refresh(album, 1, 10)
        self.harness.queue_download_progress_refresh(album, 7, 10)

        self.assertEqual(calls, [])
        self.assertEqual(self.harness.download_ui_progress["1"][1:], (7, 10))
        self.harness.flush_queued_download_progress("1")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["done_images"], 7)


if __name__ == "__main__":
    unittest.main()
