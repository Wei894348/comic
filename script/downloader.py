from __future__ import annotations

import sys
import os
from pathlib import Path


DESKTOP_PET_ARG = "--desktop-pet"
PARENT_PID_ARG = "--parent-pid"
SHOW_SIGNAL_ARG = "--show-signal"
_QT_DLL_DIRECTORY_HANDLES = []


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_src_path() -> Path:
    src_dir = project_root() / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    return src_dir


def ensure_qt_plugin_path() -> None:
    """Bind Qt to the PySide6 distribution used by this interpreter.

    Windows machines commonly have PyQt5, Anaconda and more than one PySide6
    installation on PATH.  A stale Qt plugin environment variable makes Qt try
    to load a qwindows.dll built for a different Qt runtime, which produces the
    generic "no Qt platform plugin could be initialized" dialog before our UI
    can start.
    """
    try:
        import PySide6
        from PySide6.QtCore import QCoreApplication, QLibraryInfo
    except ImportError:
        return

    pyside_dir = Path(PySide6.__file__).resolve().parent
    plugin_candidates = [pyside_dir / "plugins"]
    try:
        plugin_candidates.append(
            Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
        )
    except Exception:
        pass
    plugin_candidates.append(pyside_dir.parent / "plugins")

    plugin_dir = next(
        (
            candidate
            for candidate in plugin_candidates
            if candidate.joinpath("platforms", "qwindows.dll").is_file()
        ),
        None,
    )
    if plugin_dir is None:
        return
    platform_dir = plugin_dir / "platforms"

    if hasattr(os, "add_dll_directory"):
        for directory in (pyside_dir, pyside_dir / "Qt" / "bin"):
            if directory.is_dir():
                _QT_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(directory)))
    os.environ["QT_PLUGIN_PATH"] = str(plugin_dir)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platform_dir)
    # Environment variables alone are not sufficient if another Qt binding
    # has already supplied library paths in this Python process. Restrict Qt
    # to this matching PySide6 plugin directory before QApplication exists.
    QCoreApplication.setLibraryPaths([str(plugin_dir)])
    # This is a Windows desktop client. Do not inherit a stale ``offscreen``,
    # ``minimal`` or third-party platform selection from pwsh/Anaconda.
    os.environ["QT_QPA_PLATFORM"] = "windows"


def run_desktop_pet(
    parent_pid: int | None = None,
    show_signal_path: str | None = None,
) -> None:
    ensure_src_path()
    ensure_qt_plugin_path()
    pet_dir = project_root() / "src" / "desktop_pet"
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
    ensure_src_path()
    ensure_qt_plugin_path()
    from jm_app.main import main

    main()


def main() -> None:
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


if __name__ == "__main__":
    main()
