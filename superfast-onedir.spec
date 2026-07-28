# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Superfast Download Manager — ONEDIR build.

Build:  pyinstaller superfast-onedir.spec --clean --noconfirm
Output: dist/onedir/SuperfastDownloadManager/  (folder with the .exe + deps)

This onedir folder is what the Inno Setup script packages into an installer.
It starts faster than the onefile build (no self-extraction step).
"""

import PyInstaller.config
PyInstaller.config.CONF['distpath'] = 'dist/onedir'

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/icon.ico', 'assets'), ('assets/icon.png', 'assets')],
    hiddenimports=['yt_dlp'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PySide6.QtWebEngineCore'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SuperfastDownloadManager',
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
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SuperfastDownloadManager',
)
