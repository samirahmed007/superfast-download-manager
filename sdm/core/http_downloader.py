"""Multi-connection segmented HTTP downloader.

The performance core: a file is split into N byte ranges downloaded in parallel
threads, each writing to its own region of a preallocated file. Supports live
progress, pause (cooperative stop), resume (via a .sdmpart sidecar), and clean
cancellation.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional
from urllib.parse import urlparse, unquote

import requests

from .models import DownloadItem, Segment, Status

CHUNK = 1024 * 256          # 256 KiB socket reads
MIN_SEG = 1024 * 1024       # don't split below 1 MiB/segment
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SDM/1.0"
)

ProgressCb = Callable[[DownloadItem], None]


class HttpDownloader:
    """Drives a single DownloadItem to completion. One instance per download."""

    def __init__(self, item: DownloadItem, on_progress: Optional[ProgressCb] = None,
                 timeout: int = 30, max_retries: int = 5, speed_limit: int = 0):
        self.item = item
        self.on_progress = on_progress or (lambda _i: None)
        self.timeout = timeout
        self.max_retries = max_retries
        self.speed_limit = max(0, speed_limit)   # bytes/sec for this worker (0=off)

        self._stop = threading.Event()       # cooperative pause/cancel
        self._cancelled = False
        self._segments: list[Segment] = []
        self._lock = threading.Lock()
        self._throttle_t0 = time.time()
        self._throttle_bytes = 0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    # ---- public control -------------------------------------------------
    def pause(self):
        self.item.status = Status.PAUSED
        self._stop.set()

    def cancel(self):
        self._cancelled = True
        self._stop.set()

    # ---- helpers --------------------------------------------------------
    @property
    def _part_path(self) -> str:
        return self.item.filepath + ".sdmpart"

    def _emit(self):
        self.on_progress(self.item)

    def _probe(self):
        """HEAD/GET probe: total size, range support, resolved filename."""
        r = self._session.head(self.item.url, allow_redirects=True, timeout=self.timeout)
        if r.status_code >= 400 or "content-length" not in {k.lower() for k in r.headers}:
            # Some servers reject HEAD; fall back to a ranged GET of 1 byte.
            r = self._session.get(self.item.url, headers={"Range": "bytes=0-0"},
                                  stream=True, allow_redirects=True, timeout=self.timeout)
            r.close()

        headers = {k.lower(): v for k, v in r.headers.items()}
        accepts = headers.get("accept-ranges", "").lower() == "bytes"
        # content-range on a partial response also proves range support
        if "content-range" in headers:
            accepts = True
            try:
                self.item.total_bytes = int(headers["content-range"].split("/")[-1])
            except (ValueError, IndexError):
                pass
        if not self.item.total_bytes:
            try:
                self.item.total_bytes = int(headers.get("content-length", 0))
            except ValueError:
                self.item.total_bytes = 0

        self.item.supports_ranges = accepts and self.item.total_bytes > 0

        if not self.item.filename:
            self.item.filename = self._resolve_name(r, headers)

    def _resolve_name(self, resp, headers: dict) -> str:
        cd = headers.get("content-disposition", "")
        if "filename=" in cd:
            name = cd.split("filename=")[-1].strip().strip('"; ')
            if name:
                return unquote(name)
        path = urlparse(resp.url).path
        name = unquote(os.path.basename(path)) or "download"
        return name

    def _plan_segments(self) -> list[Segment]:
        n = max(1, self.item.connections)
        total = self.item.total_bytes
        if not self.item.supports_ranges or total <= 0:
            return [Segment(0, 0, max(0, total - 1))]
        n = min(n, max(1, total // MIN_SEG))
        base = total // n
        segs = []
        pos = 0
        for i in range(n):
            end = total - 1 if i == n - 1 else pos + base - 1
            segs.append(Segment(i, pos, end))
            pos = end + 1
        return segs

    # ---- resume state ---------------------------------------------------
    def _load_state(self) -> bool:
        try:
            with open(self._part_path + ".json", "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("url") != self.item.url or data.get("total") != self.item.total_bytes:
                return False
            self._segments = [Segment(**s) for s in data["segments"]]
            self.item.downloaded_bytes = sum(s.downloaded for s in self._segments)
            return True
        except (OSError, ValueError, KeyError):
            return False

    def _save_state(self):
        try:
            with open(self._part_path + ".json", "w", encoding="utf-8") as f:
                json.dump({
                    "url": self.item.url,
                    "total": self.item.total_bytes,
                    "segments": [vars(s) for s in self._segments],
                }, f)
        except OSError:
            pass

    def _clear_state(self):
        for p in (self._part_path + ".json",):
            try:
                os.remove(p)
            except OSError:
                pass

    # ---- worker ---------------------------------------------------------
    def _download_segment(self, seg: Segment, fh_path: str):
        attempt = 0
        while not seg.is_complete and not self._stop.is_set():
            try:
                pos = seg.current_pos
                headers = {}
                if self.item.supports_ranges:
                    headers["Range"] = f"bytes={pos}-{seg.end}"
                with self._session.get(self.item.url, headers=headers, stream=True,
                                       timeout=self.timeout) as r:
                    r.raise_for_status()
                    with open(fh_path, "r+b") as fh:
                        fh.seek(pos)
                        for chunk in r.iter_content(CHUNK):
                            if self._stop.is_set():
                                return
                            if not chunk:
                                continue
                            fh.write(chunk)
                            with self._lock:
                                seg.downloaded += len(chunk)
                                self.item.downloaded_bytes += len(chunk)
                            self._maybe_throttle(len(chunk))
                return
            except (requests.RequestException, OSError) as e:
                attempt += 1
                if attempt > self.max_retries or self._stop.is_set():
                    raise RuntimeError(f"segment {seg.index} failed: {e}") from e
                time.sleep(min(2 ** attempt, 15))

    def _maybe_throttle(self, n: int):
        """Token-bucket-ish sleep to keep this worker under speed_limit."""
        if self.speed_limit <= 0:
            return
        with self._lock:
            self._throttle_bytes += n
            elapsed = time.time() - self._throttle_t0
            allowed = self.speed_limit * elapsed
            if self._throttle_bytes > allowed:
                sleep_for = (self._throttle_bytes - allowed) / self.speed_limit
            else:
                sleep_for = 0
            if elapsed > 2:   # reset window periodically
                self._throttle_t0 = time.time()
                self._throttle_bytes = 0
        if sleep_for > 0:
            time.sleep(min(sleep_for, 1.0))

    def _preallocate(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.exists(path):
            return
        with open(path, "wb") as f:
            if self.item.total_bytes > 0:
                f.truncate(self.item.total_bytes)

    # ---- main -----------------------------------------------------------
    def run(self):
        try:
            self.item.status = Status.CONNECTING
            self._emit()
            self._probe()

            part = self._part_path
            resumed = self._load_state()
            if not resumed:
                self._segments = self._plan_segments()
                self.item.downloaded_bytes = 0
            self.item.connections = len(self._segments)
            self._preallocate(part)

            self.item.status = Status.DOWNLOADING
            self._stop.clear()
            self._emit()

            monitor = threading.Thread(target=self._monitor, daemon=True)
            monitor.start()

            errors = []
            with ThreadPoolExecutor(max_workers=len(self._segments)) as pool:
                futures = [pool.submit(self._download_segment, s, part)
                           for s in self._segments if not s.is_complete]
                for fut in futures:
                    try:
                        fut.result()
                    except Exception as e:  # noqa: BLE001 - aggregate worker errors
                        errors.append(str(e))

            self._stop.set()
            monitor.join(timeout=2)

            if self._cancelled:
                self.item.status = Status.CANCELLED
                self._cleanup_files(part)
                self._emit()
                return

            if any(not s.is_complete for s in self._segments):
                if errors:
                    raise RuntimeError("; ".join(errors[:3]))
                # paused
                self._save_state()
                self.item.status = Status.PAUSED
                self._emit()
                return

            # success: finalize
            os.replace(part, self.item.filepath)
            self._clear_state()
            self.item.downloaded_bytes = self.item.total_bytes or self.item.downloaded_bytes
            self.item.status = Status.COMPLETED
            self.item.completed_at = time.time()
            self.item.speed = 0.0
            self._emit()
        except Exception as e:  # noqa: BLE001 - surface any failure to UI
            if self._cancelled:
                self.item.status = Status.CANCELLED
            else:
                self.item.status = Status.ERROR
                self.item.error = str(e)
            self._save_state()
            self._emit()

    def _monitor(self):
        """Compute smoothed speed + ETA and periodically checkpoint state."""
        last_bytes = self.item.downloaded_bytes
        last_t = time.time()
        ema = 0.0
        tick = 0
        while not self._stop.is_set():
            time.sleep(0.5)
            now = time.time()
            dt = now - last_t
            if dt <= 0:
                continue
            delta = self.item.downloaded_bytes - last_bytes
            inst = delta / dt
            ema = inst if ema == 0 else ema * 0.7 + inst * 0.3
            self.item.speed = max(0.0, ema)
            remaining = (self.item.total_bytes - self.item.downloaded_bytes)
            self.item.eta = remaining / ema if ema > 1 else 0.0
            last_bytes = self.item.downloaded_bytes
            last_t = now
            self._emit()
            tick += 1
            if tick % 6 == 0:      # checkpoint every ~3s
                self._save_state()

    def _cleanup_files(self, part: str):
        for p in (part, part + ".json"):
            try:
                os.remove(p)
            except OSError:
                pass
