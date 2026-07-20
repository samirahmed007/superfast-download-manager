"""A tiny in-process event log with observer callbacks.

The engine (manager, workers) records human-readable events here — info,
warnings, and errors — and the UI subscribes to render them in a bottom log
panel (mirroring the web app's activity/error surface). Thread-safe: workers
run on background threads, so appends lock and callbacks are invoked outside
the lock.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List


class Level(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass
class Entry:
    level: Level
    message: str
    source: str = ""                 # e.g. an item's display name
    ts: float = field(default_factory=time.time)


Observer = Callable[[Entry], None]


class EventLog:
    def __init__(self, capacity: int = 500):
        self._entries: List[Entry] = []
        self._observers: List[Observer] = []
        self._lock = threading.RLock()
        self._capacity = capacity

    def subscribe(self, cb: Observer):
        with self._lock:
            self._observers.append(cb)

    def entries(self) -> List[Entry]:
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()

    def log(self, level: Level, message: str, source: str = ""):
        entry = Entry(level=level, message=message, source=source)
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._capacity:
                del self._entries[: len(self._entries) - self._capacity]
            observers = list(self._observers)
        for cb in observers:
            try:
                cb(entry)
            except Exception:  # noqa: BLE001 - never let a bad observer break logging
                pass

    def info(self, message: str, source: str = ""):
        self.log(Level.INFO, message, source)

    def warn(self, message: str, source: str = ""):
        self.log(Level.WARN, message, source)

    def error(self, message: str, source: str = ""):
        self.log(Level.ERROR, message, source)


# Process-wide shared log instance.
LOG = EventLog()
