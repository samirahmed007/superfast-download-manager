"""Download manager: priority queue, concurrency control, and lifecycle.

Thread model: a single scheduler thread owns admission. Items marked QUEUED wait
in a priority-ordered pool; whenever an active slot frees up (bounded by
max_concurrent), the scheduler admits the highest-priority, earliest-queued item
and runs it in its own worker thread. Progress is delivered via a plain callback
(the UI marshals it onto the Qt thread).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Dict, List, Optional

from .eventlog import LOG
from .http_downloader import HttpDownloader
from .media_downloader import MediaDownloader
from .models import DownloadItem, Kind, Priority, Status, categorize, sanitize_filename
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

        # v2 engine options (set via set_engine_options from the UI).
        self.temp_dir = ""
        self.preallocate = True
        self.auto_cleanup = True
        self.http_version = "auto"
        self.proxy = ""

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
        self._logged_status: Dict[str, Status] = {}  # last-logged state per item
        self._removed: set[str] = set()            # ids removed; drop late callbacks

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
            k = kind or guess_kind(url)
            item = DownloadItem(
                url=url.strip(),
                save_dir=save_dir or self.default_dir,
                connections=connections or self.default_connections,
                kind=k,
                filename=filename,
                priority=priority,
                category=category,
            )
        # Fill in a category when none was chosen, from filename/url/kind.
        if not item.category:
            item.category = categorize(
                item.filename, item.url, is_media=(item.kind == Kind.MEDIA))
        with self._lock:
            self.items[item.id] = item
        self.store.upsert(item)
        self._emit(item)
        self.start(item.id)
        return item

    def start(self, item_id: str):
        with self._lock:
            item = self.items.get(item_id)
            # Ignore if already running, already queued, or a worker is still
            # winding down (its resume-state hasn't been written yet). The
            # scheduler re-checks admission once the old worker fully exits.
            if (not item or item.status.is_active()
                    or item_id in self._queue):
                return
            item.status = Status.QUEUED
            item.error = ""
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

    def stop(self, item_id: str):
        """Abort a download and discard any partial data + resume state.

        Unlike pause (which keeps the ``.sdmpart`` for a from-where-it-stopped
        resume), stop resets the item to a clean CANCELLED state so a later
        start re-downloads from scratch.
        """
        with self._lock:
            if item_id in self._queue:
                self._queue.remove(item_id)
            self._auto_paused.discard(item_id)
            w = self._workers.get(item_id)
            item = self.items.get(item_id)
        if not item:
            return
        if w:
            # cancel() makes the worker delete its part files on exit
            w.cancel()
        else:
            self._discard_partial(item)
            item.status = Status.CANCELLED
            item.downloaded_bytes = 0
            item.speed = 0.0
            item.eta = 0.0
            self.store.upsert(item)
            self._emit(item)

    @staticmethod
    def _discard_partial(item: DownloadItem):
        """Remove the .sdmpart sidecar files for a not-currently-running item."""
        fp = item.filepath
        if not fp:
            return
        for p in (fp + ".sdmpart", fp + ".sdmpart.json"):
            try:
                os.remove(p)
            except OSError:
                pass

    def remove(self, item_id: str):
        with self._lock:
            item = self.items.get(item_id)
            name = item.display_name if item else item_id
            # Mark removed BEFORE cancelling so the worker's terminal emit
            # (CANCELLED) is suppressed and can't resurrect the card.
            self._removed.add(item_id)
        self.cancel(item_id)
        with self._lock:
            self.items.pop(item_id, None)
            self._active.discard(item_id)
            self._logged_status.pop(item_id, None)
        if item is not None:
            self._discard_partial(item)
        self.store.delete(item_id)
        LOG.info("Removed from list", name)

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

    def _part_paths(self, item: DownloadItem) -> list[str]:
        """The .sdmpart sidecar paths for an item, honouring a custom temp dir."""
        final = item.filepath
        if not final:
            return []
        if self.temp_dir:
            base = os.path.join(self.temp_dir, os.path.basename(final) + ".sdmpart")
        else:
            base = final + ".sdmpart"
        return [base, base + ".json"]

    def rename(self, item_id: str, new_name: str) -> tuple[bool, str]:
        """Rename a download's file (and its resume sidecars) on disk + in state.

        Returns ``(ok, message)``. Blocks while the item is actively
        downloading — the worker holds the file open and derives its paths from
        the current name. Pause or stop first.
        """
        with self._lock:
            item = self.items.get(item_id)
            active = item_id in self._workers
        if not item:
            return False, "Download not found."
        if active or item.status.is_active():
            return False, "Pause or stop the download before renaming."

        new_name = sanitize_filename(new_name)
        if not new_name:
            return False, "Please enter a valid file name."
        if new_name == item.filename:
            return True, ""                       # no-op

        old_paths = self._part_paths(item)
        old_file = item.filepath
        new_file = os.path.join(item.save_dir, new_name)
        if os.path.exists(new_file):
            return False, f"“{new_name}” already exists in this folder."

        try:
            if item.status == Status.COMPLETED and old_file and os.path.exists(old_file):
                os.rename(old_file, new_file)
        except OSError as e:
            return False, f"Could not rename file: {e}"

        # Point resume state at the new name so a paused download still resumes.
        item.filename = new_name
        for old_p, new_p in zip(old_paths, self._part_paths(item)):
            if old_p != new_p and os.path.exists(old_p):
                try:
                    os.replace(old_p, new_p)
                except OSError:
                    pass

        self.store.upsert(item)
        self._emit(item)
        LOG.info("Renamed", new_name)
        return True, ""

    def set_max_concurrent(self, n: int):
        with self._lock:
            self._max_concurrent = max(1, n)
        self._wake.set()

    def set_speed_limit(self, bytes_per_sec: int):
        """Global download speed cap in bytes/sec (0 = unlimited)."""
        self._speed_limit = max(0, bytes_per_sec)

    def set_engine_options(self, *, temp_dir: str = "", preallocate: bool = True,
                           auto_cleanup: bool = True, http_version: str = "auto",
                           proxy: str = "", dns_servers: str = ""):
        """Apply file-handling + network options to future download workers.

        Takes effect for downloads started after the call; running workers keep
        their current transport until they finish or are restarted. DNS is
        applied process-wide immediately (best-effort).
        """
        from .http_downloader import configure_dns
        self.temp_dir = (temp_dir or "").strip()
        self.preallocate = bool(preallocate)
        self.auto_cleanup = bool(auto_cleanup)
        self.http_version = http_version or "auto"
        self.proxy = (proxy or "").strip()
        if self.temp_dir:
            try:
                os.makedirs(self.temp_dir, exist_ok=True)
            except OSError:
                self.temp_dir = ""
        configure_dns(dns_servers)

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
        """Highest priority (lowest rank), then earliest added. Caller holds lock.

        Skips ids whose previous worker is still winding down (still in
        ``_active`` or ``_workers``); admitting a duplicate worker before the
        old one writes its resume-state is what caused resumes to restart from
        zero. Such ids stay queued and are retried on the next wake.
        """
        best_id = None
        best_key = None
        for iid in self._queue:
            if iid in self._active or iid in self._workers:
                continue
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
                                        speed_limit=per_worker_limit,
                                        temp_dir=self.temp_dir,
                                        preallocate=self.preallocate,
                                        auto_cleanup=self.auto_cleanup,
                                        http_version=self.http_version,
                                        proxy=self.proxy)
            with self._lock:
                self._workers[item.id] = worker
            worker.run()
        finally:
            with self._lock:
                self._workers.pop(item.id, None)
                self._active.discard(item.id)
                removed = item.id in self._removed
                self._removed.discard(item.id)
            # Don't re-persist a row that remove() already deleted.
            if not removed:
                self.store.upsert(item)
            self._wake.set()

    def _per_worker_limit(self) -> int:
        if self._speed_limit <= 0:
            return 0
        with self._lock:
            n = max(1, min(self._max_concurrent, len(self._active) + 1))
        return self._speed_limit // n

    def _emit(self, item: DownloadItem):
        # Drop late callbacks from a worker whose item was already removed —
        # otherwise the progress callback would resurrect its card in the UI.
        with self._lock:
            if item.id in self._removed:
                return
        # Once the real filename is known, backfill an empty category so
        # direct-file downloads land in Software/Documents/Archives/etc.
        if not item.category and item.filename:
            item.category = categorize(
                item.filename, item.url, is_media=(item.kind == Kind.MEDIA))
        if item.status.is_terminal() or item.status == Status.PAUSED:
            self.store.upsert(item)
        self._log_transition(item)
        self._on_progress(item)

    def _log_transition(self, item: DownloadItem):
        """Emit a log entry the first time an item reaches a notable state."""
        prev = self._logged_status.get(item.id)
        if prev == item.status:
            return
        self._logged_status[item.id] = item.status
        name = item.display_name
        if item.status == Status.ERROR:
            LOG.error(item.error or "Download failed", name)
        elif item.status == Status.COMPLETED:
            if getattr(item, "checksum", "") and item.checksum_ok:
                LOG.info("Completed — checksum verified", name)
            else:
                LOG.info("Download completed", name)
        elif item.status == Status.QUEUED:
            # distinguish a resume (had prior progress) from a fresh/requeue
            if prev == Status.PAUSED and item.downloaded_bytes > 0:
                LOG.info("Resumed", name)
            elif prev is not None:
                LOG.info("Queued", name)
        elif item.status == Status.CONNECTING and prev in (None, Status.QUEUED):
            LOG.info("Connecting…", name)
        elif item.status == Status.PAUSED and prev is not None:
            LOG.info("Paused — progress kept, resumable", name)
        elif item.status == Status.CANCELLED and prev is not None:
            LOG.warn("Stopped — partial data discarded", name)
        elif item.status == Status.DOWNLOADING and prev in (None, Status.QUEUED,
                                                             Status.CONNECTING):
            LOG.info("Download started", name)

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
