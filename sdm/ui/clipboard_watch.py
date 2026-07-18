"""Clipboard watcher: detects copied download links and offers to add them.

Watches the system clipboard (via Qt's dataChanged signal). When new text that
looks like a downloadable URL appears, emits `link_found`. The main window
decides whether to add it silently or prompt, based on config.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

# A URL that plausibly points at something downloadable: a media site, or a
# direct link to a file with a known extension.
_MEDIA_HINTS = (
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv",
    "tiktok.com", "instagram.com", "facebook.com", "twitter.com", "x.com",
    "soundcloud.com", "bilibili.com",
)
_FILE_EXT = re.compile(
    r"\.(zip|rar|7z|tar|gz|tgz|exe|msi|dmg|pkg|iso|img|"
    r"mp4|mkv|webm|avi|mov|flv|m4v|mp3|flac|wav|m4a|aac|ogg|"
    r"pdf|docx?|xlsx?|pptx?|apk|deb|rpm|bin|torrent)(\?|$)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def looks_downloadable(text: str) -> bool:
    text = (text or "").strip()
    if not _URL_RE.match(text) or len(text) > 2000:
        return False
    low = text.lower()
    if any(h in low for h in _MEDIA_HINTS):
        return True
    return bool(_FILE_EXT.search(low))


class ClipboardWatcher(QObject):
    link_found = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._last = ""
        self._seen: set[str] = set()
        self._cb = QGuiApplication.clipboard()
        self._cb.dataChanged.connect(self._on_change)

    def set_enabled(self, on: bool):
        self._enabled = on
        if on:
            # seed with current contents so we don't fire on whatever's already there
            self._last = self._cb.text().strip()

    def _on_change(self):
        if not self._enabled:
            return
        text = self._cb.text().strip()
        if not text or text == self._last:
            return
        self._last = text
        if text in self._seen:
            return
        if looks_downloadable(text):
            self._seen.add(text)
            self.link_found.emit(text)
