from __future__ import annotations

import sys
import platform as _stdlib_platform
from pathlib import Path


DESKTOP_PET_ARG = "--desktop-pet"
PARENT_PID_ARG = "--parent-pid"
SHOW_SIGNAL_ARG = "--show-signal"


def run_desktop_pet(
    parent_pid: int | None = None,
    show_signal_path: str | None = None,
) -> None:
    pet_dir = Path(__file__).resolve().parent / "desktop_pet"
    if str(pet_dir) not in sys.path:
        sys.path.insert(0, str(pet_dir))

    from src.main import main as pet_main

    pet_main(parent_pid=parent_pid, show_signal_path=show_signal_path)


def _parent_pid_from_args() -> int | None:
    try:
        index = sys.argv.index(PARENT_PID_ARG)
        return int(sys.argv[index + 1])
    except (IndexError, ValueError):
        return None


def _show_signal_from_args() -> str | None:
    try:
        index = sys.argv.index(SHOW_SIGNAL_ARG)
        return sys.argv[index + 1]
    except (IndexError, ValueError):
        return None


def run_downloader() -> None:
    from jm_app.main import main

    main()


if __name__ == "__main__":
    if DESKTOP_PET_ARG in sys.argv:
        parent_pid = _parent_pid_from_args()
        show_signal_path = _show_signal_from_args()
        sys.argv = [
            arg
            for index, arg in enumerate(sys.argv)
            if arg != DESKTOP_PET_ARG
            and arg != PARENT_PID_ARG
            and arg != SHOW_SIGNAL_ARG
            and not (index > 0 and sys.argv[index - 1] == PARENT_PID_ARG)
            and not (index > 0 and sys.argv[index - 1] == SHOW_SIGNAL_ARG)
        ]
        run_desktop_pet(
            parent_pid=parent_pid,
            show_signal_path=show_signal_path,
        )
    else:
        run_downloader()
