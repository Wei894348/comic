"""Ameath 桌面宠物 - 主入口

飞吧，朝向春天
"""

from __future__ import annotations

import ctypes
import os
import threading
import tkinter as tk
from pathlib import Path

# 必须先启用 DPI 感知
from src.platform.system import enable_dpi_awareness

enable_dpi_awareness()

from src.config import load_config
from src.platform.hotkey import hotkey_manager
from src.core.pet_core import DesktopPet
from src.platform.tray import TrayController


def _watch_parent_process(app: DesktopPet, parent_pid: int | None) -> None:
    if not parent_pid or parent_pid <= 0:
        return

    if os.name == "nt":
        synchronize = 0x00100000
        infinite = 0xFFFFFFFF
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, parent_pid)
        if not handle:
            return
        try:
            ctypes.windll.kernel32.WaitForSingleObject(handle, infinite)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(parent_pid, 0)
        except OSError:
            return
        while True:
            try:
                os.kill(parent_pid, 0)
            except OSError:
                break
            threading.Event().wait(1)

    try:
        app.root.after(0, app.request_quit)
    except tk.TclError:
        pass


def _poll_show_signal(app: DesktopPet, signal_path: Path) -> None:
    try:
        if signal_path.exists():
            signal_path.unlink(missing_ok=True)
            app.root.deiconify()
            app.root.lift()
            app.root.attributes("-topmost", True)
    except OSError:
        pass
    try:
        app.root.after(250, lambda: _poll_show_signal(app, signal_path))
    except tk.TclError:
        pass


def main(
    parent_pid: int | None = None,
    show_signal_path: str | None = None,
):
    """主函数"""
    try:
        root = tk.Tk()
        root.withdraw()  # 先隐藏窗口，避免闪烁

        # 检查是否跳过更新检查
        config = load_config()

        # 创建宠物实例
        app = DesktopPet(root)

        if parent_pid:
            threading.Thread(
                target=_watch_parent_process,
                args=(app, parent_pid),
                name="desktop-pet-parent-watch",
                daemon=True,
            ).start()

        if show_signal_path:
            signal_path = Path(show_signal_path)
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            root.after(250, lambda: _poll_show_signal(app, signal_path))

        # 注册全局快捷键
        root.after(100, lambda: hotkey_manager.register_app(app))

        # 创建并启动托盘
        tray = TrayController(app)
        app.tray_controller = tray
        tray.run()

        # 显示窗口
        root.deiconify()

        # 启动主循环
        root.mainloop()
    except KeyboardInterrupt:
        print("\n程序已退出。如果要使用划词翻译功能，请：")
        print("1. 使用 pythonw main.py 或打包后的 exe 运行（无控制台）")
        print("2. 或在浏览器中选中文本后，切换到宠物窗口再长按Ctrl")


if __name__ == "__main__":
    main()
