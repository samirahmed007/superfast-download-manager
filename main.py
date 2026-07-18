"""Superfast Download Manager — entry point.

A fast, free desktop download manager:
  * multi-connection segmented HTTP downloads (IDM-style acceleration)
  * yt-dlp integration for YouTube and other media sites
  * pause / resume, queue, and persistent history

Run:  python main.py
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from sdm.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Superfast Download Manager")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
