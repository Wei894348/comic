from __future__ import annotations

import atexit
import os
import tempfile
import time
from pathlib import Path

from script.downloader import ensure_qt_plugin_path


_TEST_DATA_ROOT = tempfile.TemporaryDirectory(prefix="comic18-tests-")
_TEST_DATA_DIR = Path(_TEST_DATA_ROOT.name)
atexit.register(_TEST_DATA_ROOT.cleanup)


def prepare_qt_test_environment() -> None:
    ensure_qt_plugin_path()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # UI tests must not migrate or mutate a developer's real configuration,
    # credentials, history database, or download-root settings.
    os.environ.setdefault("COMIC18_DATA_DIR", str(_TEST_DATA_DIR))
    os.environ["COMIC18_TESTING"] = "1"


prepare_qt_test_environment()

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
import shiboken6


def close_test_window(window, app) -> None:
    """Fully dispose a MainWindow instead of letting the tray hide it."""
    window._allow_final_close = True
    window._tray_quit_requested = True
    stop_tray = getattr(window, "_stop_tray_icon", None)
    if callable(stop_tray):
        stop_tray()
    cancel_tasks = getattr(window, "cancel_background_tasks_for_exit", None)
    if callable(cancel_tasks):
        cancel_tasks()
    home_controller = getattr(window, "home_controller", None)
    task_manager = getattr(home_controller, "tasks", None)
    wait_for_tasks = getattr(task_manager, "wait_for_all", None)
    if callable(wait_for_tasks):
        wait_for_tasks(2000)
    deadline = time.monotonic() + 2.0
    has_tasks = getattr(window, "has_running_background_tasks", None)
    while callable(has_tasks) and has_tasks() and time.monotonic() < deadline:
        app.processEvents()
    for timer in window.findChildren(QTimer):
        timer.stop()
    app.removeEventFilter(window)
    try:
        from jm_app.frontend.toast import ToastManager

        ToastManager._parent = None
        ToastManager._active = None
        ToastManager._queue.clear()
    except ImportError:
        pass
    window.close()
    # Flush zero-delay work while the pages are still alive.  Several feed
    # views schedule layout work from scrollbar range-change signals.
    for _ in range(2):
        app.processEvents()
    # PySide6 can crash while QStackedWidget destroys both of this window's
    # QUiLoader-built top-level pages in one native destructor. Releasing the
    # pages individually keeps ownership unambiguous and still allows the
    # window itself to follow the normal deferred-delete path.
    stack = getattr(window, "stack", None)
    if stack is not None and shiboken6.isValid(stack):
        while stack.count():
            page = stack.widget(0)
            # Removing a page changes descendant scrollbar ranges.  Blocking
            # signals prevents that teardown from queuing callbacks against
            # widgets that are about to be released.
            page.blockSignals(True)
            for child in page.findChildren(QObject):
                child.blockSignals(True)
            stack.removeWidget(page)
            page.setParent(None)
            shiboken6.delete(page)
    # The QUiLoader pages are already detached, so the remaining QMainWindow
    # shell can be released synchronously.  Leaving that shell as a deferred
    # delete lets queued theme callbacks retain it into the next test.
    shiboken6.delete(window)
    # Deleting one QUiLoader page can enqueue deferred deletion for child
    # effects and animations. Process multiple generations before returning.
    for _ in range(4):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
