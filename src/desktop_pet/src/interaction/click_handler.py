"""点击交互（从 src/core/pet_core.py 拆分）"""

from __future__ import annotations

import os
import random
import subprocess
import time
from typing import TYPE_CHECKING

import tkinter as tk

from src.constants import BEHAVIOR_MODE_QUIET

if TYPE_CHECKING:
    from src.core.pet_core import DesktopPet


class ClickHandler:
    """点击处理器（单击/双击/与拖动判定协作）"""

    def __init__(self, app: "DesktopPet") -> None:
        self.app = app
        self._click_animation_after_id = None
        # 快速点击启动相关
        self._rapid_click_times: list[float] = []
        self._rapid_click_timeout = 2000  # 2秒时间窗口

    def on_mouse_down(self, event: tk.Event) -> None:
        """鼠标按下事件 - 处理单击/双击/拖动"""
        app = self.app

        if app.click_through:
            return

        app._pending_drag = True
        app._mouse_down_x = event.x
        app._mouse_down_y = event.y
        app._drag_started = False

        current_time = int(time.time() * 1000)
        time_since_last_click = current_time - app._last_click_time

        if time_since_last_click < 300:
            app._click_count = 2
            self._handle_double_click(event)
        else:
            app._click_count = 1
            app._last_click_time = current_time
            app.root.after(300, lambda: self._handle_single_click(event))

    def on_mouse_up(self, event: tk.Event) -> None:
        """鼠标释放事件"""
        app = self.app
        if app.dragging:
            app.drag.stop_drag(event)
        app._pending_drag = False

    def on_right_click(self, event: tk.Event) -> None:
        """鼠标右键点击事件 - 显示托盘同款菜单并检测快速右键。"""
        self._check_rapid_clicks()
        tray = getattr(self.app, "tray_controller", None)
        if tray is None or not tray.show_context_menu():
            self.app.quick_menu.show()

    def _handle_single_click(self, event: tk.Event) -> None:
        """处理单击"""
        app = self.app
        if app._click_count != 1:
            return
        if app._drag_started:
            return

        # 安静模式下随机播放 idle3 或 idle4 动画
        if app.behavior_mode == BEHAVIOR_MODE_QUIET:
            # 音乐播放时禁止单击动画切换和气泡显示
            if app._music_playing:
                # 音乐播放模式下单击时显示歌名和音乐控制组件
                if app.music_panel.is_visible():
                    app.music_panel.hide()
                    app.speech_bubble.hide()
                else:
                    app.music_panel.show()
                    title = app.get_current_music_title()
                    if title:
                        app.speech_bubble.show(
                            f"🎵 {title}", duration=None, allow_during_music=True
                        )
                return

            # 取消之前的定时器
            if self._click_animation_after_id:
                app.root.after_cancel(self._click_animation_after_id)
                self._click_animation_after_id = None

            idle_gifs = getattr(app, "idle_gifs", [])
            if len(idle_gifs) >= 4:
                # 随机选择 idle3 (index 2) 或 idle4 (index 3)
                idx = random.choice([2, 3])
                frames, delays = idle_gifs[idx]
                app.current_frames = frames
                app.current_delays = delays
                app.frame_index = 0
                if frames:
                    app.label.config(image=frames[0])

                # 2000ms 后切换回普通待机动画 (idle2)
                self._click_animation_after_id = app.root.after(
                    2000, self._restore_idle_animation
                )
            # 安静模式下也触发点击反应气泡
            if not app.voice.play_random_click():
                app.speech_bubble.show_click_reaction()
            return

        # 音乐播放模式下显示歌名和音乐控制组件
        if app._music_playing:
            if app.music_panel.is_visible():
                app.music_panel.hide()
                app.speech_bubble.hide()
            else:
                app.music_panel.show()
                title = app.get_current_music_title()
                if title:
                    app.speech_bubble.show(
                        f"🎵 {title}", duration=None, allow_during_music=True
                    )
            return

        if not app.voice.play_random_click():
            app.speech_bubble.show_click_reaction()

    def _handle_double_click(self, event: tk.Event) -> None:
        """处理双击"""
        app = self.app
        app._click_count = 0
        app._pending_drag = False
        app.quick_menu.show()

    def _restore_idle_animation(self) -> None:
        """恢复普通待机动画"""
        self._click_animation_after_id = None
        app = self.app

        # 确保仍在安静模式
        if app.behavior_mode != BEHAVIOR_MODE_QUIET:
            return

        idle_gifs = getattr(app, "idle_gifs", [])
        if idle_gifs:
            # 切换回 idle2 (index 1)
            frames, delays = idle_gifs[1]
            app.current_frames = frames
            app.current_delays = delays
            app.frame_index = 0
            if frames:
                app.label.config(image=frames[0])

    def _check_rapid_clicks(self) -> None:
        """检测快速点击次数，触发快速启动"""
        from src.config import load_config

        config = load_config()
        if not config.get("quick_launch_enabled", False):
            return

        exe_path = config.get("quick_launch_exe_path", "")
        if not exe_path:
            return

        if not os.path.exists(exe_path):
            return

        click_count = config.get("quick_launch_click_count", 5)
        current_time = time.time() * 1000

        # 清理超出时间窗口的点击记录
        self._rapid_click_times = [
            t
            for t in self._rapid_click_times
            if current_time - t < self._rapid_click_timeout
        ]

        # 记录当前点击时间
        self._rapid_click_times.append(current_time)

        # 检查是否达到点击次数
        if len(self._rapid_click_times) >= click_count:
            self._rapid_click_times = []
            self._launch_exe(exe_path)

    def _launch_exe(self, exe_path: str) -> None:
        """启动指定的exe程序"""
        try:
            subprocess.Popen(
                exe_path,
                cwd=os.path.dirname(exe_path),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.app.speech_bubble.show("🚀 已启动程序", duration=2000)
        except Exception as e:
            self.app.speech_bubble.show(f"启动失败: {e}", duration=3000)
