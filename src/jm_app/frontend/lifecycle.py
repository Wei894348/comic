"""Main-window shutdown coordination and background-task cancellation."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from ..desktop_pet_launcher import stop_desktop_pet


class LifecycleController(QObject):
    """Own the asynchronous close state machine for the main window."""

    RETRY_INTERVAL_MS = 150
    MAX_WAIT_TICKS = 6

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self.finish_close_when_idle)

    def handle_close(self, event) -> None:
        window = self.window
        if (
            not window._tray_quit_requested
            and not window._allow_final_close
            and window.tray_icon is not None
            and window.tray_icon.isVisible()
        ):
            event.ignore()
            window.persist_sensitive_settings()
            window.settings_cache = window.current_settings_snapshot()
            window.schedule_local_cache_save(260)
            window.hide_to_lower_left()
            if not window._tray_notice_shown:
                window.show_corner_floating_notice(
                    "程序已隐藏到左下角，双击托盘图标可恢复窗口"
                )
                window._tray_notice_shown = True
            return

        if window._allow_final_close or not self.has_running_background_tasks():
            self.finalize_close(event)
            return

        event.ignore()
        if window._closing_app:
            return
        window._closing_app = True
        window._close_wait_ticks = 0
        window.set_backend_status("正在停止后台任务", "warn")
        self.stop_shutdown_timers()
        self.cancel_background_tasks_for_exit()
        window.cancel_reader_chapter_workers()
        for worker in list(window.download_workers.values()):
            try:
                worker.cancel()
            except RuntimeError:
                pass
        for dialog in list(window.reader_dialogs) + list(window.local_reader_dialogs):
            try:
                if hasattr(dialog, "stop_online_worker"):
                    dialog.stop_online_worker()
                dialog.close()
            except RuntimeError:
                pass
        self.retry_timer.start(self.RETRY_INTERVAL_MS)

    def finalize_close(self, event) -> None:
        window = self.window
        window._stop_tray_icon()
        stop_desktop_pet()
        self.stop_shutdown_timers()
        window.persist_sensitive_settings()
        window.settings_cache = window.current_settings_snapshot()
        window.save_local_cache()
        window.shutdown_db_writer()
        window.shutdown_cover_cache_writer()
        window._accept_close_event(event)
        app = QApplication.instance()
        if app is not None and not window._test_mode:
            QTimer.singleShot(0, app.quit)

    def stop_shutdown_timers(self) -> None:
        """Prevent pending UI work from creating more jobs while closing."""
        self.retry_timer.stop()
        for timer_name in (
            "history_cover_timer",
            "history_save_timer",
            "loading_timer",
            "incremental_timer",
            "result_cover_lazy_timer",
            "_local_cache_save_timer",
            "_breadcrumb_update_timer",
            "_page_activation_timer",
            "_page_theme_activation_timer",
        ):
            timer = getattr(self.window, timer_name, None)
            if timer is not None:
                timer.stop()

    @staticmethod
    def stop_worker_for_exit(worker) -> None:
        if worker is None:
            return
        try:
            cancel = getattr(worker, "cancel", None)
            if callable(cancel):
                cancel()
        except RuntimeError:
            return
        try:
            worker.requestInterruption()
        except (AttributeError, RuntimeError):
            pass

    def _background_workers(self):
        window = self.window
        workers = []
        workers.extend(window.download_workers.values())
        workers.extend(window.reader_chapter_workers.values())
        workers.extend(window.library_workers)
        workers.extend(window.library_tool_workers)
        workers.extend(window.history_delete_workers)
        workers.extend(window.local_reader_prepare_workers)
        workers.extend(window.history_local_cover_workers.values())
        workers.extend(window.cover_workers.values())
        workers.extend(window.cover_decode_workers.values())
        workers.extend(window.comment_avatar_workers.values())
        workers.extend(getattr(window, "weekly_workers", []))
        for worker in (
            window.scrape_worker,
            window.chapter_worker,
            window.incremental_worker,
            window.domain_worker,
            window.cache_restore_worker,
            window.profile_worker,
            window.daily_sign_worker,
            window.avatar_worker,
            window.local_history_sync_worker,
            window.local_reader_import_worker,
            window.cache_maintenance_worker,
            getattr(window, "route_speed_worker", None),
        ):
            if worker is not None:
                workers.append(worker)
        return workers

    def cancel_background_tasks_for_exit(self) -> None:
        window = self.window
        if hasattr(window, "home_controller"):
            window.home_controller.tasks.cancel_all()
        if hasattr(window, "detail_controller"):
            window.detail_controller.cancel()
        if hasattr(window, "download_controller"):
            window.download_controller.cancel_all()
        window.cover_request_queue.clear()
        window.cover_pending.clear()
        window.cover_targets.clear()
        window.cover_fallback_urls.clear()
        window.comment_avatar_queue.clear()
        window.comment_avatar_queued.clear()
        for worker in self._background_workers():
            self.stop_worker_for_exit(worker)

    def finish_close_when_idle(self) -> None:
        window = self.window
        if (
            not self.has_running_background_tasks()
            or window._close_wait_ticks >= self.MAX_WAIT_TICKS
        ):
            window._allow_final_close = True
            window.close()
            return
        window._close_wait_ticks += 1
        self.retry_timer.start(self.RETRY_INTERVAL_MS)

    def has_running_background_tasks(self) -> bool:
        for worker in self._background_workers():
            try:
                if worker.isRunning():
                    return True
            except RuntimeError:
                continue
        return False
