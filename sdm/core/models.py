"""Data models shared across the download engine and UI."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


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
    """One byte range of a segmented HTTP download."""
    index: int
    start: int
    end: int              # inclusive
    downloaded: int = 0

    @property
    def total(self) -> int:
        return self.end - self.start + 1

    @property
    def is_complete(self) -> bool:
        return self.downloaded >= self.total

    @property
    def current_pos(self) -> int:
        return self.start + self.downloaded


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

    @property
    def filepath(self) -> str:
        import os
        return os.path.join(self.save_dir, self.filename) if self.filename else ""

    @property
    def progress(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(1.0, self.downloaded_bytes / self.total_bytes)

    @property
    def display_name(self) -> str:
        return self.title or self.filename or self.url

    def to_row(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["status"] = self.status.value
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_row(cls, row: dict) -> "DownloadItem":
        row = dict(row)
        row["kind"] = Kind(row.get("kind", "http"))
        row["status"] = Status(row.get("status", "queued"))
        row["priority"] = Priority(row.get("priority", "normal"))
        # drop keys that are computed / not constructor args
        for k in ("progress", "filepath", "display_name"):
            row.pop(k, None)
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in row.items() if k in allowed})
