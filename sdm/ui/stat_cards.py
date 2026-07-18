"""The four summary stat cards shown above the download list."""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel

from .util import fmt_bytes, fmt_speed, PRIMARY, EMERALD, ACCENT


class _Card(QFrame):
    def __init__(self, title: str, tone: str):
        super().__init__()
        self.setObjectName("statCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        self._title = QLabel(title)
        self._title.setObjectName("statTitle")
        top.addWidget(self._title)
        top.addStretch(1)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {tone}; font-size: 15px;")
        top.addWidget(dot)
        lay.addLayout(top)
        self._value = QLabel("0")
        self._value.setObjectName("statValue")
        lay.addWidget(self._value)
        self._sub = QLabel("")
        self._sub.setObjectName("statSub")
        lay.addWidget(self._sub)

    def set(self, value: str, sub: str):
        self._value.setText(value)
        self._sub.setText(sub)


class StatCards(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.active = _Card("ACTIVE", PRIMARY)
        self.speed = _Card("TOTAL SPEED", EMERALD)
        self.downloaded = _Card("DOWNLOADED", ACCENT)
        self.library = _Card("IN LIBRARY", PRIMARY)
        for c in (self.active, self.speed, self.downloaded, self.library):
            lay.addWidget(c, 1)

    def update_stats(self, *, active, queued, speed, downloaded_bytes,
                     completed, library, failed):
        self.active.set(str(active), f"{queued} queued")
        self.speed.set(fmt_speed(speed) if speed else "—", "combined throughput")
        self.downloaded.set(fmt_bytes(downloaded_bytes), f"{completed} completed")
        self.library.set(str(library), f"{failed} failed")
