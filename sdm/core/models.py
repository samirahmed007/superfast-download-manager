"""Data models shared across the download engine and UI."""
from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

# Characters illegal in filenames on Windows (and best avoided elsewhere).
_ILLEGAL_FN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, fallback: str = "download") -> str:
    """Reduce an arbitrary string to a safe, single-segment filename.

    Servers sometimes send Content-Disposition values containing full paths
    (e.g. "/some/dir/file.rar"); joining such a value with the save directory
    would silently escape it. We strip directory components and illegal
    characters so the file always lands inside the chosen folder.
    """
    if not name:
        return fallback
    # take the last path segment regardless of separator style
    name = name.replace("\\", "/").split("/")[-1]
    name = _ILLEGAL_FN.sub("_", name).strip(" .")
    # collapse whitespace runs; guard against reserved/empty results
    name = re.sub(r"\s+", " ", name)
    return name or fallback


# Extension → category map for auto-categorizing direct file downloads.
_CATEGORY_BY_EXT = {
    # Software / installers
    "exe": "Software", "msi": "Software", "dmg": "Software", "pkg": "Software",
    "deb": "Software", "rpm": "Software", "apk": "Software", "appimage": "Software",
    "bin": "Software", "run": "Software",
    # Archives
    "zip": "Archives", "rar": "Archives", "7z": "Archives", "tar": "Archives",
    "gz": "Archives", "tgz": "Archives", "bz2": "Archives", "xz": "Archives",
    "iso": "Archives", "img": "Archives", "cab": "Archives",
    # Documents
    "pdf": "Documents", "doc": "Documents", "docx": "Documents", "xls": "Documents",
    "xlsx": "Documents", "ppt": "Documents", "pptx": "Documents", "txt": "Documents",
    "rtf": "Documents", "odt": "Documents", "epub": "Documents", "mobi": "Documents",
    "csv": "Documents",
    # Media — video
    "mp4": "Media", "mkv": "Media", "webm": "Media", "avi": "Media", "mov": "Media",
    "flv": "Media", "m4v": "Media", "wmv": "Media", "mpg": "Media", "mpeg": "Media",
    # Media — audio
    "mp3": "Media", "flac": "Media", "wav": "Media", "m4a": "Media", "aac": "Media",
    "ogg": "Media", "opus": "Media", "wma": "Media",
    # Images
    "jpg": "Images", "jpeg": "Images", "png": "Images", "gif": "Images",
    "webp": "Images", "svg": "Images", "bmp": "Images", "tiff": "Images",
}


def categorize(filename: str = "", url: str = "", is_media: bool = False) -> str:
    """Best-effort category from a filename/URL extension.

    Media-site downloads (yt-dlp) are always "Media". For direct files we key
    off the extension; unknown extensions fall back to "Other".
    """
    if is_media:
        return "Media"
    src = filename or url or ""
    # strip query/fragment, then take the extension of the last path segment
    src = src.split("?")[0].split("#")[0].replace("\\", "/").split("/")[-1]
    ext = src.rsplit(".", 1)[-1].lower() if "." in src else ""
    if not ext:
        return "Other"
    return _CATEGORY_BY_EXT.get(ext, "Other")


class Status(str, Enum):
    QUEUED = "queued"
    CONNECTING = "connecting"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"

    def is_active(self) -> bool:
        return self in (Status.CONNECTING, Status.DOWNLOADING)

    def is_terminal(self) -> bool:
        return self in (Status.COMPLETED, Status.ERROR, Status.CANCELLED)


class Kind(str, Enum):
    HTTP = "http"      # direct file, segmented accelerator
    MEDIA = "media"    # yt-dlp handled (YouTube, etc.)


class Priority(str, Enum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"urgent": 0, "high": 1, "normal": 2, "low": 3}[self.value]


@dataclass
class Format:
    """One selectable quality/format option from yt-dlp (or a direct file)."""
    format_id: str
    ext: str = "mp4"
    resolution: str = ""          # "1080p", "audio", ...
    height: Optional[int] = None
    width: Optional[int] = None
    fps: Optional[int] = None
    note: str = ""                # "1.5MB", "128kbps", codec info
    filesize: int = 0             # bytes, 0 if unknown
    has_video: bool = True
    has_audio: bool = True
    is_best: bool = False
    vcodec: str = ""
    acodec: str = ""

    @property
    def label(self) -> str:
        """Human-friendly one-line description for the picker."""
        if self.has_video and self.height:
            kind = f"{self.resolution or str(self.height) + 'p'}"
            if self.fps and self.fps >= 50:
                kind += f"{self.fps}"
            av = "video+audio" if self.has_audio else "video only"
        elif self.has_audio and not self.has_video:
            kind = "audio"
            av = self.note or "audio only"
        else:
            kind = self.resolution or "file"
            av = ""
        size = ""
        if self.filesize:
            size = f" · {self.filesize / 1_048_576:.1f} MB"
        codec = f" · {self.vcodec}" if (self.has_video and self.vcodec and self.vcodec != "none") else ""
        parts = f"{kind}  [{self.ext}]"
        if av:
            parts += f" · {av}"
        return parts + codec + size


@dataclass
class Segment:
    """One byte range of a segmented HTTP download.

    Ranges are dynamic: an idle worker may shrink a busy segment's ``end`` and
    take over its tail (work-stealing), so ``end`` and ``total`` can change
    while a download is in flight.
    """
    index: int
    start: int
    end: int              # inclusive
    downloaded: int = 0
    active: bool = False   # a worker currently owns this segment (not persisted)

    @property
    def total(self) -> int:
        return self.end - self.start + 1

    @property
    def is_complete(self) -> bool:
        return self.downloaded >= self.total

    @property
    def current_pos(self) -> int:
        return self.start + self.downloaded

    @property
    def remaining(self) -> int:
        """Bytes still to fetch before this segment reaches its current end."""
        return max(0, self.end - self.current_pos + 1)


@dataclass
class DownloadItem:
    url: str
    filename: str = ""
    save_dir: str = ""
    kind: Kind = Kind.HTTP
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    status: Status = Status.QUEUED
    total_bytes: int = 0
    downloaded_bytes: int = 0
    speed: float = 0.0            # bytes/sec (smoothed)
    connections: int = 8
    supports_ranges: bool = False

    error: str = ""
    eta: float = 0.0              # seconds
    added_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # queue management
    priority: Priority = Priority.NORMAL
    category: str = ""            # "Media", "Software", "Documents", ...

    # media (yt-dlp) extras + rich metadata (mirrors the web app)
    format_id: str = ""           # selected yt-dlp format ("" / "auto" = best)
    ext: str = "mp4"
    resolution: str = ""
    title: str = ""
    uploader: str = ""
    extractor: str = ""
    duration: int = 0             # seconds
    thumbnail: str = ""
    audio_only: bool = False      # extract audio (mp3) instead of video

    # integrity
    checksum: str = ""            # "algo:hexdigest" to verify against (optional)
    checksum_ok: Optional[bool] = None  # None=unverified, True/False after check
    validator: str = ""           # server ETag / Last-Modified for If-Range resume safety

    # per-task options
    auto_rename: bool = True      # rename instead of overwriting an existing file

    # live, non-persisted: per-connection progress fractions for the segment
    # activity view. Refreshed by the downloader; not written to the store.
    seg_progress: list = field(default_factory=list)

    @property
    def filepath(self) -> str:
        if not self.filename:
            return ""
        # Defense in depth: never let a filename escape the save directory,
        # even if a caller stored a path-like value.
        safe = sanitize_filename(self.filename)
        return os.path.join(self.save_dir, safe)

    @property
    def progress(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(1.0, self.downloaded_bytes / self.total_bytes)

    @property
    def display_name(self) -> str:
        return self.title or self.filename or self.url

    @property
    def download_duration(self) -> float:
        """Wall-clock seconds spent downloading (start → completion), 0 if unknown."""
        if self.started_at and self.completed_at and self.completed_at >= self.started_at:
            return self.completed_at - self.started_at
        return 0.0

    def to_row(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["status"] = self.status.value
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_row(cls, row: dict) -> "DownloadItem":
        row = dict(row)

        def _enum(enum_cls, value, default):
            # Tolerate NULL/blank/unknown values from older or partial rows.
            try:
                return enum_cls(value) if value else default
            except ValueError:
                return default

        row["kind"] = _enum(Kind, row.get("kind"), Kind.HTTP)
        row["status"] = _enum(Status, row.get("status"), Status.QUEUED)
        row["priority"] = _enum(Priority, row.get("priority"), Priority.NORMAL)
        # drop keys that are computed / not constructor args
        for k in ("progress", "filepath", "display_name"):
            row.pop(k, None)
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in row.items() if k in allowed})
