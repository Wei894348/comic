# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for comic18 (onedir build).

Layout notes:
  * PyInstaller 6.x onedir collects all bundled files (``ui/``, ``res/``,
    ``desktop_pet/`` and the binaries) into a ``_internal`` subdirectory of
    ``dist/comic18/``.  At runtime PyInstaller exposes that directory as
    ``sys._MEIPASS``, which is exactly where these resources live.
  * Resource resolution therefore uses ``sys._MEIPASS``:
      - main app  -> ``src/jm_app/backend/runtime_paths.py`` (``_bundle_dir``)
      - desktop pet -> ``src/desktop_pet/src/utils.py`` (``desktop_pet_base``)
  * ``app_base_dir()`` intentionally keeps returning ``sys.executable.parent``
    (``dist/comic18/``) for legacy/user-data migration (cache, logs, data),
    which must stay in the writable install folder, not inside ``_internal``.

Onefile is not usable: its extraction temp dir differs from
``sys.executable.parent``, breaking both resolution strategies.

Build:
    pyinstaller comic18.spec            # validation build (console=on)
    set COMIC18_CONSOLE=0 && pyinstaller comic18.spec   # final GUI build
"""
import os
from pathlib import Path

try:
    SPECPATH = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SPECPATH = os.getcwd()
ROOT = Path(SPECPATH)


def gather_modules(base, pkg_root):
    """Collect every ``*.py`` under *base* as a dotted module name, relative to
    *pkg_root* (so the package prefix is correct)."""
    mods = set()
    base = Path(base)
    pkg_root = Path(pkg_root)
    if not base.exists():
        return mods
    for p in base.rglob("*.py"):
        rel = p.relative_to(pkg_root).with_suffix("")
        parts = list(rel.parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        name = ".".join(parts)
        if name:
            mods.add(name)
    return mods


hiddenimports = set()
# Main application package (imported as top-level ``jm_app``).
hiddenimports |= gather_modules(ROOT / "src" / "jm_app", ROOT / "src")
# Desktop pet package: imported as top-level ``src`` (namespace merge of
# src/desktop_pet/src). Critical because it is only imported lazily at runtime.
hiddenimports |= gather_modules(ROOT / "src" / "desktop_pet" / "src", ROOT / "src" / "desktop_pet")
# Launch orchestration (imported by run.py).
hiddenimports |= gather_modules(ROOT / "script", ROOT)

# PySide6 submodules that may only be reached through lazy / string-based imports.
hiddenimports |= {
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtUiTools",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtXml",
}

# jmcomic and several libraries are only imported lazily at runtime (inside
# functions / the desktop pet). Ensure PyInstaller bundles the whole packages,
# including their plugins / submodules.
hiddenimports |= {
    "jmcomic",
    "dashscope",
    "curl_cffi",
    "requests",
    "bs4",
    "lxml",
    "PIL",
    "pystray",
    "pygame",
    "pypdfium2",
    "pydantic",
    "Crypto",
    "pyperclip",
    "yaml",
}

# Runtime data that the frozen code expects next to / inside the bundle.
datas = [
    (str(ROOT / "res"), "res"),
    (str(ROOT / "ui"), "ui"),
    (str(ROOT / "src" / "desktop_pet" / "assets"), "desktop_pet/assets"),
    (str(ROOT / "src" / "desktop_pet" / "config"), "desktop_pet/config"),
]

# Console on for the validation build so import / missing-module errors are visible.
CONSOLE = os.environ.get("COMIC18_CONSOLE", "1") == "1"

a = Analysis(
    [str(ROOT / "run.py")],
    # `src/desktop_pet` is on the path so PyInstaller can resolve the desktop
    # pet's ``src`` namespace package (its modules live under
    # src/desktop_pet/src/, imported at runtime as ``src.*``).
    pathex=[str(ROOT), str(ROOT / "src"), str(ROOT / "src" / "desktop_pet")],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "wx"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Onedir layout: the executable lives in dist/comic18/ together with the
# bundled data (res/, ui/, desktop_pet/). This matches the app's runtime path
# resolution (app_base_dir() == sys.executable.parent; desktop_pet_base() uses
# sys._MEIPASS, which PyInstaller points at the same folder in onedir mode).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="comic18.exe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "res" / "assets" / "app.ico"),
    version=str(ROOT / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="comic18",
)
