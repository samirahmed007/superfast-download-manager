"""Superfast Download Manager — entry point.

A fast, free desktop download manager:
  * multi-connection segmented HTTP downloads (IDM-style acceleration)
  * yt-dlp integration for YouTube and other media sites
  * pause / resume, queue, and persistent history

Run:  python main.py
"""
from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from sdm.ui.main_window import MainWindow


def _resource_path(rel: str) -> str:
    """Resolve a bundled resource path for both source and PyInstaller runs."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main():
    # On Windows, set an explicit AppUserModelID so the taskbar shows our icon
    # (not the generic Python one) when running as a bundled exe.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SamirUddinAhmed.SuperfastDownloadManager.1")
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Superfast Download Manager")
    app.setOrganizationName("Samir Uddin Ahmed")

    icon_path = _resource_path(os.path.join("assets", "icon.ico"))
    if not os.path.exists(icon_path):
        icon_path = _resource_path(os.path.join("assets", "icon.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
