"""Download manager: priority queue, concurrency control, and lifecycle.

Thread model: a single scheduler thread owns admission. Items marked QUEUED wait
in a priority-ordered pool; whenever an active slot frees up (bounded by
max_concurrent), the scheduler admits the highest-priority, earliest-queued item
and runs it in its own worker thread. Progress is delivered via a plain callback
(the UI marshals it onto the Qt thread).
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

from .http_downloader import HttpDownloader
from .media_downloader import MediaDownloader
from .models import DownloadItem, Kind, Priority, Status
from .store import Store

ProgressCb = Callable[[DownloadItem], None]

MEDIA_HINTS = (
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv",
    "tiktok.com", "instagram.com", "facebook.com", "twitter.com", "x.com",
    "soundcloud.com", "bilibili.com",
)


def guess_kind(url: str) -> Kind:
    u = url.lower()
    return Kind.MEDIA if any(h in u for h in MEDIA_HINTS) else Kind.HTTP


class DownloadManager:
    def __init__(self, store: Store, default_dir: str,
                 max_concurrent: int = 3, default_connections: int = 8):
        self.store = store
        self.default_dir = default_dir
        self.default_connections = default_connections
        self._max_concurrent = max(1, max_concurrent)

        self.items: Dict[str, DownloadItem] = {}
        self._workers: Dict[str, object] = {}     # id -> downloader instance
        self._queue: List[str] = []               # ids waiting to run
        self._active: set[str] = set()            # ids currently running
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._on_progress: ProgressCb = lambda _i: None
        self._speed_limit = 0                     # global bytes/sec cap (0 = off)
        self._schedule_hold = False               # scheduler gate
        self._auto_paused: set[str] = set()       # ids paused by the scheduler

        self._running = True
        self._scheduler = threading.Thread(target=self._schedule_loop, daemon=True)
        self._scheduler.start()

    # ---- wiring ---------------------------------------------------------
    def set_progress_callback(self, cb: ProgressCb):
        self._on_progress = cb

    def load_persisted(self):
        for item in self.store.all():
            # anything left mid-flight becomes resumable/paused on load
            if item.status.is_active() or item.status == Status.QUEUED:
                item.status = Status.PAUSED
            self.items[item.id] = item

    # ---- queue ops ------------------------------------------------------
    def add(self, url: str = "", save_dir: Optional[str] = None,
            connections: Optional[int] = None, kind: Optional[Kind] = None,
            filename: str = "", priority: Priority = Priority.NORMAL,
            category: str = "", item: Optional[DownloadItem] = None) -> DownloadItem:
        if item is None:
            item = DownloadItem(
                url=url.strip(),
                save_dir=save_dir or self.default_dir,
                connections=connections or self.default_connections,
                kind=kind or guess_kind(url),
                filename=filename,
                priority=priority,
                category=category,
            )
        with self._lock:
            self.items[item.id] = item
        self.store.upsert(item)
        self._emit(item)
        self.start(item.id)
        return item

    def start(self, item_id: str):
        with self._lock:
            item = self.items.get(item_id)
            if not item or item.status.is_active() or item_id in self._queue:
                return
            item.status = Status.QUEUED
            item.error = ""
            if item_id not in self._queue:
                self._queue.append(item_id)
        self._emit(item)
        self._wake.set()

    def pause(self, item_id: str):
        with self._lock:
            if item_id in self._queue:
                self._queue.remove(item_id)
            w = self._workers.get(item_id)
            item = self.items.get(item_id)
        if w:
            w.pause()
        elif item and item.status in (Status.QUEUED,):
            item.status = Status.PAUSED
            self._emit(item)

    def cancel(self, item_id: str):
        with self._lock:
            if item_id in self._queue:
                self._queue.remove(item_id)
            w = self._workers.get(item_id)
            item = self.items.get(item_id)
        if w:
            w.cancel()
        elif item:
            item.status = Status.CANCELLED
            self._emit(item)

    def remove(self, item_id: str):
        self.cancel(item_id)
        with self._lock:
            self.items.pop(item_id, None)
            self._active.discard(item_id)
        self.store.delete(item_id)

    def set_priority(self, item_id: str, priority: Priority):
        with self._lock:
            item = self.items.get(item_id)
            if item:
                item.priority = priority
                self.store.upsert(item)
        if item:
            self._emit(item)
            self._wake.set()

    def set_category(self, item_id: str, category: str):
        with self._lock:
            item = self.items.get(item_id)
            if item:
                item.category = category
                self.store.upsert(item)
        if item:
            self._emit(item)

    def set_max_concurrent(self, n: int):
        with self._lock:
            self._max_concurrent = max(1, n)
        self._wake.set()

    def set_speed_limit(self, bytes_per_sec: int):
        """Global download speed cap in bytes/sec (0 = unlimited)."""
        self._speed_limit = max(0, bytes_per_sec)

    def set_schedule_hold(self, hold: bool):
        """Scheduler gate: when held, pause active downloads and stop admitting.

        Items paused by the hold are remembered so they auto-resume when the
        window reopens — without disturbing downloads the user paused manually.
        """
        with self._lock:
            self._schedule_hold = hold
        if hold:
            with self._lock:
                to_pause = [iid for iid, w in self._workers.items()]
                self._auto_paused = set(to_pause) | {
                    iid for iid in self._queue}
                workers = [(iid, self._workers.get(iid)) for iid in to_pause]
            for iid, w in workers:
                if w:
                    w.pause()
        else:
            with self._lock:
                resume = list(self._auto_paused)
                self._auto_paused.clear()
            for iid in resume:
                self.start(iid)
            self._wake.set()

    # ---- scheduler ------------------------------------------------------
    def _schedule_loop(self):
        while self._running:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            while True:
                with self._lock:
                    if self._schedule_hold:
                        break
                    if len(self._active) >= self._max_concurrent:
                        break
                    nxt = self._pick_next_locked()
                    if nxt is None:
                        break
                    self._queue.remove(nxt)
                    self._active.add(nxt)
                    item = self.items[nxt]
                t = threading.Thread(target=self._run, args=(item,), daemon=True)
                t.start()

    def _pick_next_locked(self) -> Optional[str]:
        """Highest priority (lowest rank), then earliest added. Caller holds lock."""
        best_id = None
        best_key = None
        for iid in self._queue:
            it = self.items.get(iid)
            if not it:
                continue
            key = (it.priority.rank, it.added_at)
            if best_key is None or key < best_key:
                best_key = key
                best_id = iid
        return best_id

    # ---- worker ---------------------------------------------------------
    def _run(self, item: DownloadItem):
        try:
            if item.status == Status.CANCELLED:
                return
            item.started_at = item.started_at or time.time()
            per_worker_limit = self._per_worker_limit()
            if item.kind == Kind.MEDIA:
                worker = MediaDownloader(item, on_progress=self._emit)
            else:
                worker = HttpDownloader(item, on_progress=self._emit,
                                        speed_limit=per_worker_limit)
            with self._lock:
                self._workers[item.id] = worker
            worker.run()
        finally:
            with self._lock:
                self._workers.pop(item.id, None)
                self._active.discard(item.id)
            self.store.upsert(item)
            self._wake.set()

    def _per_worker_limit(self) -> int:
        if self._speed_limit <= 0:
            return 0
        with self._lock:
            n = max(1, min(self._max_concurrent, len(self._active) + 1))
        return self._speed_limit // n

    def _emit(self, item: DownloadItem):
        if item.status.is_terminal() or item.status == Status.PAUSED:
            self.store.upsert(item)
        self._on_progress(item)

    def shutdown(self):
        self._running = False
        self._wake.set()
        for w in list(self._workers.values()):
            try:
                w.pause()
            except Exception:  # noqa: BLE001
                pass
        for item in self.items.values():
            self.store.upsert(item)
