"""AI 上色入口：本地下载右键、阅读器工具栏、进度提示。

UI 侧只负责收集目录与设置、转发到 ColorizeManager；模型与子进程在
backend.colorize_service 里。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from PySide6.QtWidgets import QMenu

from ..backend.colorize_service import colorize_manager, colorize_settings_defaults
from ..backend.pdf_utils import IMAGE_SUFFIXES
from .hd_reader import HdMangaReaderWindow, collect_reader_images

if TYPE_CHECKING:
    from .ui import MainWindow

def colorize_effective_settings(main: "MainWindow") -> Dict[str, object]:
    """合并默认值与设置页当前值。"""
    settings = colorize_settings_defaults()
    cached = getattr(main, "settings_cache", None)
    legacy = {
        r"C:\Users\86157\manga_color\mcv2",
        r"C:\Users\86157\manga_color\venv\Scripts\python.exe",
    }
    if isinstance(cached, dict):
        for key in settings:
            if key in cached:
                value = cached[key]
                # 旧版默认路径已迁移到项目内置位置，忽略缓存里的旧值
                if isinstance(value, str) and value.strip() in legacy:
                    continue
                settings[key] = value
    if hasattr(main, "colorize_size_combo"):
        settings["colorize_size"] = int(main.colorize_size_combo.currentData() or 576)
        settings["colorize_denoise"] = bool(main.colorize_denoise_box.isChecked())
        model_dir = main.colorize_model_edit.text().strip()
        python_exe = main.colorize_python_edit.text().strip()
        if model_dir:
            settings["colorize_model_dir"] = model_dir
        if python_exe:
            settings["colorize_python"] = python_exe
    return settings


def first_local_image_dir(record: Dict[str, str]) -> Optional[Path]:
    """从历史记录里找出可上色的图片目录（目录内含图片，或 zip 解包目录）。"""
    candidates: List[Path] = []
    for key in ("image_dir", "path"):
        value = str(record.get(key) or "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    outputs = record.get("outputs") or []
    if isinstance(outputs, list):
        candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())
    for path in candidates:
        if path.is_dir():
            try:
                if any(item.suffix.lower() in IMAGE_SUFFIXES for item in path.iterdir()):
                    return path
            except OSError:
                continue
    return None


class ColorizeUIMixin:
    """MainWindow mixin：右键上色、进度显示、完成后询问打开。"""

    def setup_colorize(self: "MainWindow") -> None:
        if getattr(self, "_colorize_connected", False):
            return
        manager = colorize_manager()
        manager.job_started.connect(self.on_colorize_started)
        manager.progress.connect(self.on_colorize_progress)
        manager.page_failed.connect(self.on_colorize_page_failed)
        manager.job_finished.connect(self.on_colorize_finished)
        manager.job_failed.connect(self.on_colorize_failed)
        self._colorize_connected = True

    def bind_reader_colorize(self: "MainWindow", reader) -> None:
        """把阅读器的上色请求接到全局管理器，完成后回填到这个阅读器。"""
        manager = colorize_manager()

        def on_requested(title: str, source_dir) -> None:
            if self.log:
                self.log(f"上色请求到达：{title} <- {source_dir}")
            settings = colorize_effective_settings(self)
            enqueued = manager.enqueue(title, Path(source_dir), settings)
            if enqueued:
                reader.colorize_source_dir = Path(source_dir)
                if self.log:
                    self.log(f"上色任务已入队：{title}（模型={settings.get('colorize_model_dir')}，python={settings.get('colorize_python')}）")
            else:
                reader.colorize_action.setEnabled(True)
                reader.status_label.setText("")
                self.show_toast("上色任务已在队列中，请等待完成", 2200, parent=reader)

        def on_finished(out_title: str, _output_dir: str) -> None:
            source = getattr(reader, "colorize_source_dir", None)
            if source is not None and out_title == getattr(reader, "_colorize_title", ""):
                reader.open_colorized_result(Path(source))

        def on_failed(out_title: str, error: str) -> None:
            if out_title == getattr(reader, "_colorize_title", ""):
                reader.colorize_action.setEnabled(True)
                reader.status_label.setText("上色失败")
                self.show_toast(f"上色失败：{error}", 2800, parent=reader)

        def capture_title(title: str, _source_dir) -> None:
            reader._colorize_title = title

        reader.colorize_requested.connect(capture_title)
        reader.colorize_requested.connect(on_requested)
        manager.job_finished.connect(on_finished)
        manager.job_failed.connect(on_failed)

    def request_colorize_history_index(self: "MainWindow", index: int, open_when_done: bool = False) -> None:
        record = self.download_history[index] if 0 <= index < len(self.download_history) else {}
        if not record:
            return
        title = str(record.get("title") or record.get("file") or f"本地漫画 {index + 1}")
        source_dir = first_local_image_dir(record)
        if source_dir is None:
            self.show_toast("该记录没有可直接上色的图片目录（PDF/ZIP 请先用图片方式下载）", 2600)
            return
        self.setup_colorize()
        settings = colorize_effective_settings(self)
        enqueued = colorize_manager().enqueue(title, source_dir, settings)
        if not enqueued:
            self.show_floating_notice(f"上色任务已在队列中：{title}")
            return
        if open_when_done:
            pending = getattr(self, "_colorize_open_when_done", {})
            pending[title] = source_dir
            self._colorize_open_when_done = pending

    def open_colorized_history(self: "MainWindow", title: str, source_dir) -> None:
        """上色完成后自动打开上色版阅读。"""
        colorized = Path(source_dir) / "上色版"
        record = {"title": title, "path": str(colorized), "image_dir": str(colorized)}
        dialog = HdMangaReaderWindow(f"漫画阅读（上色版） - {title}")
        self.local_reader_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _=None, dialog=dialog: self.forget_local_reader_dialog(dialog))
        try:
            dialog.start_decode_image_paths(collect_reader_images(colorized))
            dialog.showMaximized()
            dialog.raise_()
            dialog.activateWindow()
            self.log(f"上色版阅读器已打开：{title}")
        except Exception as exc:
            self.forget_local_reader_dialog(dialog)
            dialog.deleteLater()
            self.show_toast(f"上色版打开失败：{exc}", 2400)

    def append_history_context_colorize_action(self: "MainWindow", menu: QMenu, index: int) -> None:
        record = self.download_history[index] if 0 <= index < len(self.download_history) else {}
        source_dir = first_local_image_dir(record)
        action = menu.addAction("AI 上色")
        if source_dir is None:
            action.setEnabled(False)
            action.setToolTip("没有可上色的图片目录")
        action.triggered.connect(lambda _=False, idx=index: self.request_colorize_history_index(idx))
        read_action = menu.addAction("上色阅读")
        if source_dir is None:
            read_action.setEnabled(False)
        read_action.triggered.connect(
            lambda _=False, idx=index: self.request_colorize_history_index(idx, open_when_done=True)
        )

    # ---- 进度显示 ----

    def on_colorize_started(self: "MainWindow", title: str) -> None:
        self.show_floating_notice(f"开始上色：{title}")

    def on_colorize_progress(self: "MainWindow", title: str, done: int, total: int, page: str) -> None:
        if total > 0:
            self.show_floating_notice(f"上色中 {title}：{done}/{total} 页")

    def on_colorize_page_failed(self: "MainWindow", title: str, page: str, error: str) -> None:
        self.log(f"上色单页失败：{title} {page}: {error}")

    def on_colorize_finished(self: "MainWindow", title: str, output_dir: str) -> None:
        self.log(f"上色完成：{title} → {output_dir}")
        self.refresh_local_downloads_if_visible()
        pending = getattr(self, "_colorize_open_when_done", {})
        source_dir = pending.pop(title, None)
        if source_dir is not None:
            self.open_colorized_history(title, source_dir)
        else:
            self.show_floating_notice(f"上色完成：{title}")

    def on_colorize_failed(self: "MainWindow", title: str, error: str) -> None:
        self.log(f"上色失败：{title}: {error}")
        self.show_toast(f"上色失败：{error}", 3000)
