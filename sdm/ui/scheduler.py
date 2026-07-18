"""Download scheduler: run downloads only within a configured time window.

Checks the wall clock once a minute. When the current time enters the active
window it resumes queued/paused downloads; when it leaves, it pauses active
ones. Handles windows that cross midnight (e.g. 23:00 -> 06:00).
"""
from __future__ import annotations

from datetime import datetime, time as dtime

from PySide6.QtCore import QObject, QTimer, Signal


def _parse(hhmm: str) -> dtime:
    try:
        h, m = hhmm.split(":")
        return dtime(int(h) % 24, int(m) % 60)
    except (ValueError, AttributeError):
        return dtime(0, 0)


def in_window(now: dtime, start: dtime, stop: dtime) -> bool:
    if start == stop:
        return True  # 24h window
    if start < stop:
        return start <= now < stop
    # crosses midnight
    return now >= start or now < stop


class Scheduler(QObject):
    """Emits window_open(bool) whenever the active state changes."""
    window_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._start = dtime(1, 0)
        self._stop = dtime(7, 0)
        self._active: bool | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)  # check twice a minute
        self._timer.timeout.connect(self._tick)

    def configure(self, enabled: bool, start: str, stop: str):
        self._enabled = enabled
        self._start = _parse(start)
        self._stop = _parse(stop)
        if enabled:
            self._active = None  # force a re-evaluation + emit
            self._timer.start()
            self._tick()
        else:
            self._timer.stop()
            self._active = None

    def is_open(self) -> bool:
        if not self._enabled:
            return True
        return in_window(datetime.now().time(), self._start, self._stop)

    def _tick(self):
        if not self._enabled:
            return
        now_open = self.is_open()
        if now_open != self._active:
            self._active = now_open
            self.window_changed.emit(now_open)
