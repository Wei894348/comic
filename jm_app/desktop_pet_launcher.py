from __future__ import annotations

import atexit
import ctypes
import os
import subprocess
import sys
from pathlib import Path

from .backend.runtime_paths import session_dir

_pet_process: subprocess.Popen | None = None
DESKTOP_PET_ARG = "--desktop-pet"


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _pet_dir() -> Path:
    return _project_root() / "desktop_pet"


def _session_dir() -> Path:
    path = session_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _log_path() -> Path:
    return _session_dir() / "desktop_pet.log"


def _pid_path() -> Path:
    return _session_dir() / "desktop_pet.pid"


def _pythonw_executable() -> str:
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return str(executable)
    if os.name == "nt":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(executable)


def _pet_command(entry: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [_pythonw_executable(), DESKTOP_PET_ARG]
    return [_pythonw_executable(), str(entry)]


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _read_existing_pid() -> int | None:
    try:
        return int(_pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def start_desktop_pet() -> subprocess.Popen | None:
    global _pet_process

    if _pet_process is not None and _pet_process.poll() is None:
        return _pet_process

    existing_pid = _read_existing_pid()
    if existing_pid and _is_process_running(existing_pid):
        return None

    pet_dir = _pet_dir()
    entry = pet_dir / "main.py"
    if not getattr(sys, "frozen", False) and not entry.exists():
        _log_path().write_text(
            f"Desktop pet entry not found: {entry}\n",
            encoding="utf-8",
        )
        return None

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    log_file = _log_path().open("a", encoding="utf-8")
    try:
        _pet_process = subprocess.Popen(
            _pet_command(entry),
            cwd=str(_project_root() if getattr(sys, "frozen", False) else pet_dir),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=False,
        )
        _pid_path().write_text(str(_pet_process.pid), encoding="utf-8")
        return _pet_process
    except Exception as exc:
        log_file.write(f"Failed to start desktop pet: {exc}\n")
        log_file.flush()
        _pet_process = None
        return None
    finally:
        log_file.close()


def stop_desktop_pet() -> None:
    global _pet_process

    process = _pet_process
    _pet_process = None
    if process is None or process.poll() is not None:
        _pid_path().unlink(missing_ok=True)
        return

    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    _pid_path().unlink(missing_ok=True)


atexit.register(stop_desktop_pet)
