"""A compact per-connection activity strip for a download card.

Renders each active segment as a small cell whose fill reflects that
connection's progress — a live, at-a-glance view of the multi-connection
engine at work (like IDM's connection graph, but inline on the card).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from PySide6.QtWidgets import QWidget

from . import theme

# Gradient stops matching the brand (purple -> pink), used to fill cells.
_G0 = QColor("#a874ff")
_G1 = QColor("#f65fa6")


class SegmentBar(QWidget):
    """Draws N cells (one per connection), each filled by its progress fraction."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fracs: list[float] = []
        self.setFixedHeight(10)
        self.setToolTip("Per-connection download activity")

    def set_segments(self, fracs: list[float]):
        # Only repaint when something actually changed (avoids churn at 1 Hz).
        rounded = [round(f, 3) for f in (fracs or [])]
        if rounded != self._fracs:
            self._fracs = rounded
            self.update()

    def clear(self):
        if self._fracs:
            self._fracs = []
            self.update()

    def paintEvent(self, _event):
        n = len(self._fracs)
        if n == 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = theme.palette()
        track = QColor(pal["input"])
        w = self.width()
        h = self.height()
        gap = 2.0
        cell_w = (w - gap * (n - 1)) / n
        if cell_w <= 0:
            p.end()
            return
        radius = min(3.0, cell_w / 2, h / 2)
        for i, frac in enumerate(self._fracs):
            x = i * (cell_w + gap)
            # track
            p.setPen(Qt.NoPen)
            p.setBrush(track)
            p.drawRoundedRect(QRectF(x, 0, cell_w, h), radius, radius)
            # fill
            frac = max(0.0, min(1.0, frac))
            if frac > 0:
                grad = QLinearGradient(x, 0, x + cell_w, 0)
                grad.setColorAt(0, _G0)
                grad.setColorAt(1, _G1)
                p.setBrush(grad)
                fill_h = h
                fill_w = cell_w * frac
                p.drawRoundedRect(QRectF(x, 0, max(fill_w, radius * 2 if frac > 0 else 0),
                                         fill_h), radius, radius)
        p.end()
