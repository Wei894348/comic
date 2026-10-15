"""AI 上色服务：manga-colorization-v2 模型，后台线程逐页处理本地漫画。

模型权重位于模型目录（默认 C:\\Users\\86157\\manga_color\\mcv2\\networks，
可被设置 colorize_model_dir 覆盖）。torch 环境由 colorize_python 指定的解释器提供。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from ..backend.pdf_utils import IMAGE_SUFFIXES
from ..backend.runtime_paths import app_data_dir

DEFAULT_MODEL_DIR = r"C:\Users\86157\manga_color\mcv2"
DEFAULT_PYTHON = r"C:\Users\86157\manga_color\venv\Scripts\python.exe"

_COLORIZE_JOB_SCRIPT = r'''
import sys, os, json
os.chdir(sys.argv[1])  # model dir, so networks/ and denoising/ resolve
sys.path.insert(0, sys.argv[1])
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cv2
from colorizator import MangaColorizator

src, dst, size, denoise, sigma = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5] == "1", int(sys.argv[6])
os.makedirs(dst, exist_ok=True)
files = sorted(f for f in os.listdir(src) if os.path.splitext(f)[1].lower() in {".jpg",".jpeg",".png",".webp",".bmp"})
colorizator = None
done = 0
for name in files:
    out = os.path.join(dst, os.path.splitext(name)[0] + ".png")
    done += 1
    if os.path.exists(out) and os.path.getsize(out) > 0:
        print(json.dumps({"done": done, "total": len(files), "page": name, "skipped": True}), flush=True)
        continue
    if colorizator is None:
        colorizator = MangaColorizator("cpu")
    img = plt.imread(os.path.join(src, name))
    c = colorizator
    c.set_image(img, size=size, apply_denoise=denoise, denoise_sigma=sigma)
    out_img = c.colorize()
    out8 = (out_img * 255).astype("uint8")
    h, w = img.shape[:2]
    out8 = cv2.resize(out8, (w, h), interpolation=cv2.INTER_LANCZOS4)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(out8, cv2.COLOR_RGB2BGR))
    if not ok:
        print(json.dumps({"done": done, "total": len(files), "page": name, "error": "encode failed"}), flush=True)
        continue
    with open(out, "wb") as f:
        f.write(buf.tobytes())
    print(json.dumps({"done": done, "total": len(files), "page": name}), flush=True)
print(json.dumps({"finished": True}), flush=True)
'''


def colorize_settings_defaults() -> Dict[str, object]:
    return {
        "colorize_enabled": True,
        "colorize_size": 576,
        "colorize_denoise": False,
        "colorize_sigma": 25,
        "colorize_model_dir": DEFAULT_MODEL_DIR,
        "colorize_python": DEFAULT_PYTHON,
    }


class ColorizeJobWorker(QThread):
    """跑一个目录的上色子进程，逐页回报进度。"""

    progress = Signal(str, int, int, str)  # title, done, total, page_name
    page_failed = Signal(str, str, str)  # title, page_name, error
    finished_ok = Signal(str, str)  # title, output_dir
    failed = Signal(str, str)  # title, error

    def __init__(self, title: str, source_dir: Path, settings: Dict[str, object], parent=None):
        super().__init__(parent)
        self.title = title
        self.source_dir = Path(source_dir)
        self.settings = dict(settings)
        self.process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    def _resolved(self, key: str, default: str) -> str:
        value = str(self.settings.get(key) or default).strip()
        return value or default

    def output_dir(self) -> Path:
        return self.source_dir / "上色版"

    def stop(self) -> None:
        self._stop_requested = True
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def run(self):
        try:
            self._run()
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(self.title, str(exc))

    def _run(self):
        model_dir = self._resolved("colorize_model_dir", DEFAULT_MODEL_DIR)
        python_exe = self._resolved("colorize_python", DEFAULT_PYTHON)
        if not Path(model_dir, "networks", "generator.zip").is_file():
            raise RuntimeError(f"模型权重缺失：{model_dir}\\networks\\generator.zip")
        if not Path(python_exe).is_file():
            raise RuntimeError(f"上色 Python 解释器不存在：{python_exe}（需安装 CPU 版 torch/opencv/matplotlib）")
        if not self.source_dir.is_dir():
            raise RuntimeError(f"目录不存在：{self.source_dir}")

        dst = str(self.output_dir())
        script_path = app_data_dir() / "colorize_job.py"
        script_path.write_text(_COLORIZE_JOB_SCRIPT, encoding="utf-8")
        cmd = [
            python_exe, "-I", str(script_path),
            model_dir, str(self.source_dir), dst,
            str(int(self.settings.get("colorize_size") or 576)),
            "1" if bool(self.settings.get("colorize_denoise")) else "0",
            str(int(self.settings.get("colorize_sigma") or 25)),
        ]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=creationflags,
        )
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if self._stop_requested:
                break
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("finished"):
                break
            name = str(event.get("page") or "")
            done = int(event.get("done") or 0)
            total = int(event.get("total") or 0)
            if event.get("error"):
                self.page_failed.emit(self.title, name, str(event["error"]))
            else:
                self.progress.emit(self.title, done, total, name)
        return_code = self.process.wait()
        if self._stop_requested:
            return
        if return_code != 0:
            stderr = ""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read()[-800:]
            raise RuntimeError(f"上色进程异常退出（code {return_code}）：{stderr}")
        self.finished_ok.emit(self.title, dst)


class ColorizeManager(QObject):
    """全局单例：排队执行上色任务，同一时间只跑一个。"""

    job_started = Signal(str)
    progress = Signal(str, int, int, str)
    page_failed = Signal(str, str, str)
    job_finished = Signal(str, str)  # title, output_dir
    job_failed = Signal(str, str)  # title, error

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._queue: "queue.Queue[ColorizeJobWorker]" = queue.Queue()
        self._current: Optional[ColorizeJobWorker] = None
        self._queued_titles: set = set()

    def enqueue(self, title: str, source_dir: Path, settings: Dict[str, object]) -> bool:
        source_dir = Path(source_dir)
        if not source_dir.is_dir():
            return False
        if title in self._queued_titles or (self._current and self._current.title == title):
            return False
        worker = ColorizeJobWorker(title, source_dir, settings, self)
        if self._current is None:
            self._start(worker)
        else:
            self._queue.put(worker)
            self._queued_titles.add(title)
        return True

    def _start(self, worker: ColorizeJobWorker) -> None:
        self._current = worker
        self._queued_titles.discard(worker.title)
        worker.progress.connect(self.progress)
        worker.page_failed.connect(self.page_failed)
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_worker_thread_finished)
        self.job_started.emit(worker.title)
        worker.start()

    def _on_finished(self, title: str, output_dir: str) -> None:
        self.job_finished.emit(title, output_dir)

    def _on_failed(self, title: str, error: str) -> None:
        self.job_failed.emit(title, error)

    def _on_worker_thread_finished(self) -> None:
        worker = self.sender()
        if worker is self._current:
            self._current = None
        try:
            worker.deleteLater()
        except RuntimeError:
            pass
        if not self._queue.empty():
            self._start(self._queue.get())

    def cancel(self, title: str) -> None:
        if self._current and self._current.title == title:
            self._current.stop()

    def is_running(self, title: str = "") -> bool:
        if title:
            running = self._current is not None and self._current.title == title
            return running or title in self._queued_titles
        return self._current is not None or not self._queue.empty()


_manager: Optional[ColorizeManager] = None


def colorize_manager() -> ColorizeManager:
    global _manager
    if _manager is None:
        _manager = ColorizeManager()
    return _manager
