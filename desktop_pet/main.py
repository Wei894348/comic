"""Ameath 桌面宠物 - 启动入口"""

from __future__ import annotations

import sys
import platform as _stdlib_platform
from pathlib import Path


def _parent_pid_from_args() -> int | None:
    try:
        index = sys.argv.index("--parent-pid")
        return int(sys.argv[index + 1])
    except (IndexError, ValueError):
        return None


def _show_signal_from_args() -> str | None:
    try:
        index = sys.argv.index("--show-signal")
        return sys.argv[index + 1]
    except (IndexError, ValueError):
        return None


def _bootstrap() -> None:
    base_dir = Path(__file__).resolve().parent
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    from src.main import main as app_main

    app_main(
        parent_pid=_parent_pid_from_args(),
        show_signal_path=_show_signal_from_args(),
    )


if __name__ == "__main__":
    _bootstrap()
