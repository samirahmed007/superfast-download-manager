"""Multi-connection segmented HTTP downloader.

The performance core: a file is split into N byte ranges downloaded in parallel
threads, each writing to its own region of a preallocated file. Supports live
progress, pause (cooperative stop), resume (via a .sdmpart sidecar), and clean
cancellation.

Integrity is treated as non-negotiable. Every parallel connection is verified to
be an honest ``206 Partial Content`` response whose ``Content-Range`` matches the
byte offset we asked for; writes are clamped to the requested range so a
misbehaving server can never bleed into a neighbouring segment; an ``If-Range``
validator guards resume against a file that changed on the server; and the
finished file is fsync'd and size-checked before it is put in place. If a server
or CDN ignores our ``Range`` header and streams the whole file (a ``200``), the
engine degrades to a single verified stream rather than scattering full-file
bytes across the segments — the classic cause of "right size, corrupt content".
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional
from urllib.parse import urlparse, unquote

import requests

try:                                # optional: enables HTTP/2
    import httpx
except ImportError:                 # pragma: no cover - httpx is optional
    httpx = None

from .models import DownloadItem, Segment, Status, sanitize_filename

CHUNK = 1024 * 256          # 256 KiB socket reads
MIN_SEG = 1024 * 1024       # don't split below 1 MiB/segment
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SDM/2.0"
)

ProgressCb = Callable[[DownloadItem], None]


_ORIG_GETADDRINFO = None


def configure_dns(servers: str):
    """Best-effort custom DNS for all downloads (needs ``dnspython`` installed).

    Overrides hostname→IP resolution process-wide while leaving TLS/SNI keyed to
    the original hostname, so certificate validation is unaffected. A no-op when
    dnspython is missing or no servers are given; falls back to system DNS per
    lookup on any resolver error.
    """
    global _ORIG_GETADDRINFO
    import socket
    if _ORIG_GETADDRINFO is None:
        _ORIG_GETADDRINFO = socket.getaddrinfo
    orig = _ORIG_GETADDRINFO

    names = [s.strip() for s in (servers or "").split(",") if s.strip()]
    if not names:
        socket.getaddrinfo = orig          # restore system DNS
        return
    try:
        import dns.resolver
    except ImportError:
        return                             # dnspython unavailable: keep system DNS

    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = names
    cache: dict[str, str] = {}

    def patched(host, *args, **kwargs):
        try:
            ip = cache.get(host)
            if ip is None:
                ip = str(resolver.resolve(host, "A")[0])
                cache[host] = ip
            return orig(ip, *args, **kwargs)
        except Exception:  # noqa: BLE001 - fall back to the system resolver
            return orig(host, *args, **kwargs)

    socket.getaddrinfo = patched



class _RangeNotHonored(Exception):
    """The server answered a ranged request with a full-body ``200``.

    Signals that parallel byte-range downloading is unsafe for this URL and the
    engine must fall back to a single verified stream.
    """


class _Resp:
    """A streaming HTTP response normalized across ``requests`` and ``httpx``."""

    __slots__ = ("status_code", "headers", "url", "_raise", "_iter")

    def __init__(self, status_code, headers, url, raise_for_status, iterator):
        self.status_code = status_code
        self.headers = headers          # case-insensitive in both libraries
        self.url = url
        self._raise = raise_for_status
        self._iter = iterator

    def raise_for_status(self):
        self._raise()

    def iter(self):
        return self._iter()


class HttpDownloader:
    """Drives a single DownloadItem to completion. One instance per download."""

    def __init__(self, item: DownloadItem, on_progress: Optional[ProgressCb] = None,
                 timeout: int = 30, max_retries: int = 5, speed_limit: int = 0,
                 temp_dir: str = "", preallocate: bool = True,
                 auto_cleanup: bool = True, http_version: str = "auto",
                 proxy: str = ""):
        self.item = item
        self.on_progress = on_progress or (lambda _i: None)
        self.timeout = timeout
        self.max_retries = max_retries
        self.speed_limit = max(0, speed_limit)   # bytes/sec for this worker (0=off)
        self.temp_dir = temp_dir or ""
        self.preallocate = preallocate
        self.auto_cleanup = auto_cleanup
        self.proxy = proxy or ""

        self._stop = threading.Event()       # cooperative pause/cancel
        self._cancelled = False
        self._range_broken = False           # server ignored Range → single-stream
        self._segments: list[Segment] = []
        self._lock = threading.Lock()
        self._throttle_t0 = time.time()
        self._throttle_bytes = 0

        # Pick the transport. httpx unlocks HTTP/2; requests stays the default.
        pool = max(10, item.connections * 2 + 4)
        want_h2 = http_version in ("2", "3") and httpx is not None
        self._mode = "httpx" if want_h2 else "requests"
        self._session = None
        self._client = None
        if self._mode == "httpx":
            self._client = self._build_httpx(pool)
        else:
            self._session = self._build_requests(pool)

    # ---- transport ------------------------------------------------------
    def _build_requests(self, pool: int) -> "requests.Session":
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        if self.proxy:
            s.proxies = {"http": self.proxy, "https": self.proxy}
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=pool, pool_maxsize=pool, max_retries=0)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        return s

    def _build_httpx(self, pool: int):
        limits = httpx.Limits(max_connections=pool, max_keepalive_connections=pool)
        kwargs = dict(http2=True, headers={"User-Agent": USER_AGENT},
                      limits=limits, follow_redirects=True,
                      timeout=self.timeout, verify=True)
        if self.proxy:
            # httpx renamed proxies→proxy across versions; try both.
            try:
                return httpx.Client(proxy=self.proxy, **kwargs)
            except TypeError:
                return httpx.Client(proxies=self.proxy, **kwargs)
        return httpx.Client(**kwargs)

    def _close_transport(self):
        try:
            if self._client is not None:
                self._client.close()
            if self._session is not None:
                self._session.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    @contextmanager
    def _stream(self, headers: dict):
        """Yield a normalized streaming response for a GET of the item URL."""
        if self._mode == "httpx":
            with self._client.stream("GET", self.item.url, headers=headers) as r:
                yield _Resp(r.status_code, r.headers, str(r.url),
                            r.raise_for_status, lambda: r.iter_bytes(CHUNK))
        else:
            with self._session.get(self.item.url, headers=headers, stream=True,
                                   allow_redirects=True, timeout=self.timeout) as r:
                yield _Resp(r.status_code, r.headers, r.url,
                            r.raise_for_status, lambda: r.iter_content(CHUNK))

    def _head(self):
        if self._mode == "httpx":
            return self._client.head(self.item.url)
        return self._session.head(self.item.url, allow_redirects=True,
                                  timeout=self.timeout)

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
        """Where the in-progress file lives (honours a custom temp directory)."""
        final = self.item.filepath
        if self.temp_dir:
            return os.path.join(self.temp_dir, os.path.basename(final) + ".sdmpart")
        return final + ".sdmpart"

    def _emit(self):
        self.on_progress(self.item)

    def _probe(self):
        """HEAD/GET probe: total size, range support, filename, validator."""
        try:
            r = self._head()
            headers = {k.lower(): v for k, v in r.headers.items()}
            status = r.status_code
        except Exception:  # noqa: BLE001 - some servers refuse HEAD outright
            headers, status = {}, 400

        if status >= 400 or "content-length" not in headers:
            # HEAD unusable; probe with a 1-byte ranged GET instead.
            with self._stream({"Range": "bytes=0-0"}) as g:
                headers = {k.lower(): v for k, v in g.headers.items()}
                status = g.status_code

        accepts = headers.get("accept-ranges", "").lower() == "bytes"
        if "content-range" in headers:     # a partial response proves ranges work
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
        # Capture a validator so resume/If-Range can detect a changed file.
        self.item.validator = (headers.get("etag")
                               or headers.get("last-modified") or "")

        if not self.item.filename:
            self.item.filename = self._resolve_name(headers, self.item.url)

    def _resolve_name(self, headers: dict, url: str) -> str:
        cd = headers.get("content-disposition", "")
        if "filename=" in cd:
            name = cd.split("filename=")[-1].strip().strip('"; ')
            if name:
                return sanitize_filename(unquote(name))
        path = urlparse(url).path
        name = unquote(os.path.basename(path))
        return sanitize_filename(name)

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
            if (data.get("url") != self.item.url
                    or data.get("total") != self.item.total_bytes):
                return False
            # A changed validator means the server file differs from our partial
            # data — resuming would splice two versions. Start clean instead.
            saved_val = data.get("validator", "")
            if saved_val and self.item.validator and saved_val != self.item.validator:
                return False
            segs = []
            for s in data["segments"]:
                s.pop("active", None)   # transient; never resume as "owned"
                segs.append(Segment(**s))
            self._segments = segs
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
                    "validator": self.item.validator,
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

    # ---- work-stealing scheduler ----------------------------------------
    def _next_work(self) -> Optional[Segment]:
        """Hand a worker its next segment. Caller must NOT hold the lock.

        Priority: (1) any not-yet-started, incomplete segment; (2) otherwise
        split the tail off the segment with the most bytes left to fetch, so a
        freed connection accelerates the slowest one instead of going idle.
        """
        with self._lock:
            for s in self._segments:
                if not s.active and not s.is_complete:
                    s.active = True
                    return s
            if not self.item.supports_ranges:
                return None
            victim = max((s for s in self._segments if s.active),
                         key=lambda s: s.remaining, default=None)
            if victim is None or victim.remaining < 2 * MIN_SEG:
                return None
            split = victim.current_pos + victim.remaining // 2
            tail = Segment(index=len(self._segments), start=split,
                           end=victim.end, active=True)
            victim.end = split - 1        # victim now stops early; it will notice
            self._segments.append(tail)
            return tail

    def _worker_loop(self, fh_path: str, errors: list):
        """Pull segments until the file is done, stolen tails and all."""
        while not self._stop.is_set():
            seg = self._next_work()
            if seg is None:
                return
            try:
                self._download_segment(seg, fh_path)
            except _RangeNotHonored:
                # Fatal for parallel mode: stop everyone, run() will retry as one
                # verified stream. Not an error the user needs to see.
                self._range_broken = True
                self._stop.set()
                return
            except Exception as e:  # noqa: BLE001 - collect, let siblings finish
                errors.append(str(e))
                return
            finally:
                with self._lock:
                    seg.active = False

    # ---- worker ---------------------------------------------------------
    def _download_segment(self, seg: Segment, fh_path: str):
        ranges = self.item.supports_ranges
        attempt = 0
        while not seg.is_complete and not self._stop.is_set():
            pos = seg.current_pos
            req_end = seg.end
            want = req_end - pos + 1              # exactly what we asked for
            headers = {}
            if ranges:
                headers["Range"] = f"bytes={pos}-{req_end}"
                if self.item.validator:
                    headers["If-Range"] = self.item.validator
            try:
                with self._stream(headers) as r:
                    self._validate_response(r, pos, ranges)
                    with open(fh_path, "r+b") as fh:
                        fh.seek(pos)
                        written = 0
                        for chunk in r.iter():
                            if self._stop.is_set():
                                return
                            if not chunk:
                                continue
                            # Clamp: never write past the range we requested, so a
                            # server that over-sends can't corrupt the next segment.
                            if ranges and written + len(chunk) > want:
                                chunk = chunk[:want - written]
                            if not chunk:
                                break
                            fh.write(chunk)
                            written += len(chunk)
                            with self._lock:
                                seg.downloaded += len(chunk)
                            # Our tail was stolen: stop, let the thief finish it.
                            if seg.current_pos > seg.end:
                                return
                            self._maybe_throttle(len(chunk))
                            if ranges and written >= want:
                                break
                return
            except _RangeNotHonored:
                raise
            except (requests.RequestException, OSError) as e:
                attempt += 1
                if attempt > self.max_retries or self._stop.is_set():
                    raise RuntimeError(f"segment {seg.index} failed: {e}") from e
                time.sleep(min(2 ** attempt, 15))
            except Exception as e:  # noqa: BLE001 - httpx errors, etc.
                if httpx is not None and isinstance(e, httpx.HTTPError):
                    attempt += 1
                    if attempt > self.max_retries or self._stop.is_set():
                        raise RuntimeError(f"segment {seg.index} failed: {e}") from e
                    time.sleep(min(2 ** attempt, 15))
                    continue
                raise

    def _validate_response(self, r: _Resp, pos: int, ranges: bool):
        """Reject any response that isn't a truthful answer to our request."""
        if not ranges:
            r.raise_for_status()
            return
        if r.status_code == 200:
            # Range ignored (or If-Range validator changed): full file incoming.
            raise _RangeNotHonored()
        if r.status_code != 206:
            r.raise_for_status()
            raise _RangeNotHonored()
        cr = r.headers.get("content-range", "")
        if not self._content_range_ok(cr, pos):
            raise RuntimeError(f"bad Content-Range {cr!r} (wanted offset {pos})")

    @staticmethod
    def _content_range_ok(cr: str, pos: int) -> bool:
        """Confirm a ``Content-Range`` header starts at the offset we asked for."""
        if not cr:
            # 206 without a Content-Range: only trustworthy for a from-zero read.
            return pos == 0
        try:
            span = cr.split()[1].split("/")[0]     # "bytes 200-1023/1024" → "200-1023"
            start = int(span.split("-")[0])
            return start == pos
        except (IndexError, ValueError):
            return False

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
            # Reserving the full size up front lets every worker seek+write its
            # own region safely. When disabled we create an empty file and rely
            # on seek-write auto-extension (still correct, just more fragmented).
            if self.item.total_bytes > 0 and self.preallocate:
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

            errors = self._download_all(part)

            # A server that ignored our Range header: discard the scattered
            # partial data and retry once as a single, fully verified stream.
            if self._range_broken and not self._cancelled:
                errors = self._retry_single_stream(part)

            self._aggregate_progress()

            if self._cancelled:
                self.item.status = Status.CANCELLED
                self._cleanup_files(part)
                self.item.downloaded_bytes = 0
                self.item.speed = 0.0
                self.item.eta = 0.0
                self._emit()
                return

            if any(not s.is_complete for s in self._segments):
                if errors:
                    raise RuntimeError("; ".join(errors[:3]))
                self._save_state()               # paused
                self.item.status = Status.PAUSED
                self._emit()
                return

            self._finalize(part)
        except Exception as e:  # noqa: BLE001 - surface any failure to UI
            if self._cancelled:
                self.item.status = Status.CANCELLED
            else:
                self.item.status = Status.ERROR
                self.item.error = str(e)
            self._save_state()
            self._emit()
        finally:
            self._close_transport()

    def _download_all(self, part: str) -> list:
        """Spin up one worker per segment and run to pause/finish/error."""
        from concurrent.futures import ThreadPoolExecutor
        errors: list = []
        monitor = threading.Thread(target=self._monitor, daemon=True)
        monitor.start()
        n_workers = max(1, len(self._segments))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(self._worker_loop, part, errors)
                       for _ in range(n_workers)]
            for fut in futures:
                try:
                    fut.result()
                except Exception as e:  # noqa: BLE001 - aggregate worker errors
                    errors.append(str(e))
        self._stop.set()
        monitor.join(timeout=2)
        return errors

    def _retry_single_stream(self, part: str) -> list:
        """Re-download as one verified stream after a Range-ignoring server."""
        self.item.supports_ranges = False
        self._range_broken = False
        self._stop.clear()
        total = self.item.total_bytes
        self._segments = [Segment(0, 0, max(0, total - 1))]
        self.item.downloaded_bytes = 0
        self.item.connections = 1
        # Start the part file over so no stray parallel bytes survive.
        try:
            os.remove(part)
        except OSError:
            pass
        self._preallocate(part)
        self.item.status = Status.DOWNLOADING
        self._emit()
        return self._download_all(part)

    def _finalize(self, part: str):
        """Flush to disk, verify size + checksum, then put the file in place."""
        self._fsync(part)

        # Size assertion: the file on disk must be exactly what we expected.
        if self.item.total_bytes > 0:
            try:
                actual = os.path.getsize(part)
            except OSError:
                actual = -1
            if actual != self.item.total_bytes:
                raise RuntimeError(
                    f"size mismatch: got {actual} bytes, expected "
                    f"{self.item.total_bytes} — download incomplete")

        target = self._resolve_target()
        self._move_into_place(part, target)
        self.item.filename = os.path.basename(target)
        self._clear_state()

        self.item.downloaded_bytes = self.item.total_bytes or self.item.downloaded_bytes
        self.item.speed = 0.0
        self.item.seg_progress = []

        if self.item.checksum:
            self.item.status = Status.CONNECTING   # transient "verifying" state
            self._emit()
            ok = self._verify_checksum(target, self.item.checksum)
            self.item.checksum_ok = ok
            if not ok:
                self.item.status = Status.ERROR
                self.item.error = "Checksum mismatch — file may be corrupt"
                self._emit()
                return
        self.item.status = Status.COMPLETED
        self.item.completed_at = time.time()
        self._emit()

    def _resolve_target(self) -> str:
        """Final destination path, auto-renamed to avoid clobbering a file."""
        target = self.item.filepath
        if not self.item.auto_rename or not os.path.exists(target):
            return target
        base, ext = os.path.splitext(target)
        i = 1
        while os.path.exists(f"{base} ({i}){ext}"):
            i += 1
        return f"{base} ({i}){ext}"

    @staticmethod
    def _fsync(path: str):
        """Force buffered writes to physical disk before we rename the file."""
        try:
            with open(path, "rb+") as f:
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass

    @staticmethod
    def _move_into_place(part: str, target: str):
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        try:
            os.replace(part, target)          # atomic on the same volume
        except OSError:
            # temp dir on a different drive: fall back to a copy+remove move.
            shutil.move(part, target)

    def _aggregate_progress(self):
        """Recompute total bytes + per-segment fractions from segment state."""
        with self._lock:
            total = 0
            fracs = []
            for s in self._segments:
                total += s.downloaded
                fracs.append(min(1.0, s.downloaded / s.total) if s.total > 0 else 1.0)
        self.item.downloaded_bytes = total
        self.item.seg_progress = fracs

    def _monitor(self):
        """Compute smoothed speed + ETA and periodically checkpoint state."""
        self._aggregate_progress()
        last_bytes = self.item.downloaded_bytes
        last_t = time.time()
        ema = 0.0
        tick = 0
        while not self._stop.is_set():
            time.sleep(0.5)
            self._aggregate_progress()
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

    @staticmethod
    def _verify_checksum(path: str, spec: str) -> bool:
        """Verify ``path`` against a checksum spec.

        ``spec`` is "algo:hexdigest" (e.g. "sha256:ab12...") or a bare hex
        digest, in which case the algorithm is inferred from its length
        (32=md5, 40=sha1, 64=sha256, 128=sha512).
        """
        spec = (spec or "").strip().lower()
        if not spec:
            return True
        if ":" in spec:
            algo, _, expected = spec.partition(":")
        else:
            expected = spec
            algo = {32: "md5", 40: "sha1", 64: "sha256",
                    128: "sha512"}.get(len(expected), "")
        expected = expected.strip()
        if algo not in hashlib.algorithms_available or not expected:
            return True  # unknown spec: don't fail a good download over it
        try:
            h = hashlib.new(algo)
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(block)
            return h.hexdigest().lower() == expected
        except OSError:
            return False

    def _cleanup_files(self, part: str):
        if not self.auto_cleanup:
            return
        for p in (part, part + ".json"):
            try:
                os.remove(p)
            except OSError:
                pass
