# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, copy_metadata
import os
import sys


desktop_pet_path = os.path.join(SPECPATH, 'desktop_pet')
sys.path.insert(0, desktop_pet_path)

hiddenimports = [
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.font',
    'PIL.ImageTk',
    'pystray',
    'pygame',
    'yaml',
] + collect_submodules('dashscope') + collect_submodules('websocket') + collect_submodules('src')

package_metadata = copy_metadata('dashscope') + copy_metadata('websocket-client')


a = Analysis(
    ['downloader.py'],
    pathex=[desktop_pet_path],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('desktop_pet/assets', 'desktop_pet/assets'),
        ('desktop_pet/config', 'desktop_pet/config'),
    ] + package_metadata,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'jm_app.frontend.browser_cookie_dialog',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebChannel',
        'PyQt5.QtQuick',
        'PyQt5.QtQuickWidgets',
        'PyQt5.QtQml',
        'PyQt5.QtPositioning',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JM下载器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JM下载器',
)
