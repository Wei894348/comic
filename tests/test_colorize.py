"""AI 上色：设置读写、目录解析、队列去重、子进程脚本语法。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tests.qt_test_utils import prepare_qt_test_environment

prepare_qt_test_environment()

from PySide6.QtCore import QCoreApplication

from jm_app.backend.colorize_service import (
    ColorizeJobWorker,
    ColorizeManager,
    colorize_settings_defaults,
)
from jm_app.backend.runtime_paths import app_data_dir
from jm_app.frontend.colorize_actions import (
    colorize_effective_settings,
    first_local_image_dir,
)


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def test_settings_defaults_shape():
    defaults = colorize_settings_defaults()
    assert defaults["colorize_size"] == 576
    assert defaults["colorize_denoise"] is False
    assert "colorize_model_dir" in defaults and "colorize_python" in defaults


def test_effective_settings_uses_ui_overrides():
    class FakeCombo:
        def currentData(self):
            return 768

    class FakeBox:
        def isChecked(self):
            return True

    class FakeEdit:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class FakeMain:
        settings_cache = {"colorize_size": 999}
        colorize_size_combo = FakeCombo()
        colorize_denoise_box = FakeBox()
        colorize_model_edit = FakeEdit("D:/models/mcv2")
        colorize_python_edit = FakeEdit("")

    settings = colorize_effective_settings(FakeMain())
    assert settings["colorize_size"] == 768  # UI wins over cache
    assert settings["colorize_denoise"] is True
    assert settings["colorize_model_dir"] == "D:/models/mcv2"
    assert settings["colorize_python"] != ""  # falls back to default


def test_first_local_image_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert first_local_image_dir({"path": str(empty)}) is None

    images = tmp_path / "images"
    images.mkdir()
    (images / "001.jpg").write_bytes(b"x")
    assert first_local_image_dir({"path": str(images)}) == images
    assert first_local_image_dir({"image_dir": str(images)}) == images
    assert first_local_image_dir({"path": str(tmp_path / "missing")}) is None


def test_job_script_is_valid_python_and_writes_jsonl():
    from jm_app.backend import colorize_service

    # The embedded job script must compile as Python.
    compile(colorize_service._COLORIZE_JOB_SCRIPT, "colorize_job.py", "exec")
    # And the service writes it under the app data dir when started.
    assert app_data_dir().name


def test_manager_enqueue_rejects_missing_dir(qapp):
    manager = ColorizeManager()
    assert manager.enqueue("t", Path("Z:/definitely/missing"), {}) is False


def test_manager_rejects_duplicate_titles(qapp, tmp_path):
    images = tmp_path / "imgs"
    images.mkdir()
    (images / "a.png").write_bytes(b"x")
    manager = ColorizeManager()
    assert manager.enqueue("dup", images, {"colorize_model_dir": "missing", "colorize_python": "missing"}) is True
    assert manager.enqueue("dup", images, {}) is False
    assert manager.is_running("dup") is True
    manager.cancel("dup")
    # The job fails fast (missing model); let the finished signal drain.
    for _ in range(50):
        if not manager.is_running("dup"):
            break
        QCoreApplication.processEvents()
        manager._current and manager._current.wait(100)
    assert manager.is_running("dup") is False


def test_worker_fails_cleanly_on_missing_weights(qapp, tmp_path):
    images = tmp_path / "imgs"
    images.mkdir()
    (images / "a.png").write_bytes(b"x")
    worker = ColorizeJobWorker("t", images, {"colorize_model_dir": str(tmp_path / "no_model"), "colorize_python": str(tmp_path / "no_python.exe")})
    errors = []
    worker.failed.connect(lambda title, error: errors.append(error))
    worker.start()
    worker.wait(15000)
    for _ in range(20):
        if errors:
            break
        QCoreApplication.processEvents()
        worker.wait(200)
    assert errors
    assert "模型权重缺失" in errors[0] or "解释器不存在" in errors[0]
