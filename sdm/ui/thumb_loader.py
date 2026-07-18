"""Fetches remote thumbnails off the UI thread and hands back QPixmaps.

Downloads are cheap and cached in-process by URL. Results are delivered via a
Qt signal so the card can be updated on the main thread.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QPixmap


class _FetchWorker(QThread):
    done = Signal(str, bytes)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            import urllib.request
            req = urllib.request.Request(self.url, headers={"User-Agent": "sdm"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            self.done.emit(self.url, data)
        except Exception:  # noqa: BLE001 - thumbnails are best-effort
            self.done.emit(self.url, b"")


class ThumbnailLoader(QObject):
    loaded = Signal(str, QPixmap)  # (url, pixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: dict[str, QPixmap] = {}
        self._workers: dict[str, _FetchWorker] = {}

    def request(self, url: str):
        if not url:
            return
        if url in self._cache:
            self.loaded.emit(url, self._cache[url])
            return
        if url in self._workers:
            return
        w = _FetchWorker(url)
        w.done.connect(self._on_done)
        self._workers[url] = w
        w.start()

    def _on_done(self, url: str, data: bytes):
        self._workers.pop(url, None)
        if not data:
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            self._cache[url] = pix
            self.loaded.emit(url, pix)
