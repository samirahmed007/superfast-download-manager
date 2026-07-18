"""yt-dlp based downloader for media sites (YouTube, Vimeo, etc.).

Runs yt-dlp in-process via its Python API, translating its progress hooks into
our DownloadItem model. Supports cancellation; pause/resume for media falls back
to yt-dlp's own .part continuation on restart.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from .models import DownloadItem, Status

ProgressCb = Callable[[DownloadItem], None]


class MediaDownloader:
    def __init__(self, item: DownloadItem, on_progress: Optional[ProgressCb] = None,
                 ytdlp_format: str = "bestvideo+bestaudio/best"):
        self.item = item
        self.on_progress = on_progress or (lambda _i: None)
        self.ytdlp_format = ytdlp_format
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def pause(self):
        # yt-dlp has no live pause; stopping keeps the .part for resume.
        self._cancel = True
        self.item.status = Status.PAUSED

    def _resolve_final_path(self, ydl, info: dict) -> str:
        """Find the file actually written after merge/postprocessing.

        yt-dlp records post-processed paths under 'requested_downloads'; fall
        back to prepare_filename and finally to the newest matching file on disk.
        """
        reqs = info.get("requested_downloads") or []
        for r in reqs:
            p = r.get("filepath") or r.get("_filename")
            if p and os.path.exists(p):
                return p
        guess = ydl.prepare_filename(info)
        if os.path.exists(guess):
            return guess
        # postprocessor changed the extension (e.g. -> .mp3): match by stem
        stem = os.path.splitext(guess)[0]
        try:
            cands = [f for f in os.listdir(self.item.save_dir)
                     if os.path.splitext(f)[0] == os.path.basename(stem)]
            if cands:
                newest = max(cands, key=lambda f: os.path.getmtime(
                    os.path.join(self.item.save_dir, f)))
                return os.path.join(self.item.save_dir, newest)
        except OSError:
            pass
        return guess

    def _build_format_selector(self) -> str:
        """Translate the user's choice into a yt-dlp format string.

        - audio_only        -> bestaudio
        - a specific format  -> that format, merged with bestaudio if video-only
        - "auto"/empty       -> best up to the chosen resolution (if any)
        """
        if self.item.audio_only:
            return "bestaudio/best"
        fid = (self.item.format_id or "").strip()
        if fid and fid.lower() not in ("auto", "best", "direct"):
            # if the picked format is video-only, add best audio for a complete file
            return f"{fid}+bestaudio/{fid}/best"
        if self.item.resolution and self.item.resolution.rstrip("p").isdigit():
            h = self.item.resolution.rstrip("p")
            return (f"bestvideo[height<={h}]+bestaudio/"
                    f"best[height<={h}]/best")
        return self.ytdlp_format

    def _hook(self, d: dict):
        if self._cancel:
            raise _Cancelled()
        st = d.get("status")
        if st == "downloading":
            self.item.status = Status.DOWNLOADING
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            self.item.total_bytes = int(total) if total else self.item.total_bytes
            self.item.downloaded_bytes = int(d.get("downloaded_bytes", 0))
            self.item.speed = float(d.get("speed") or 0.0)
            self.item.eta = float(d.get("eta") or 0.0)
            self.on_progress(self.item)
        elif st == "finished":
            # a stream finished; merging may still follow
            self.item.downloaded_bytes = self.item.total_bytes
            self.on_progress(self.item)

    def run(self):
        try:
            import yt_dlp
        except ImportError:
            self.item.status = Status.ERROR
            self.item.error = "yt-dlp is not installed"
            self.on_progress(self.item)
            return

        self.item.status = Status.CONNECTING
        self.on_progress(self.item)

        os.makedirs(self.item.save_dir, exist_ok=True)
        outtmpl = os.path.join(self.item.save_dir, "%(title)s.%(ext)s")

        opts = {
            "format": self._build_format_selector(),
            "outtmpl": outtmpl,
            "progress_hooks": [self._hook],
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "continuedl": True,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": max(1, self.item.connections),
        }
        ffmpeg = _find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        # Audio-only: extract to mp3 (requires ffmpeg; falls back to source ext).
        if self.item.audio_only:
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            # Prefer mp4 output, but let yt-dlp fall back to a compatible
            # container (e.g. mkv) when the chosen codecs can't be muxed into it.
            # Forcing a mismatched container is what causes "Conversion failed".
            opts["merge_output_format"] = "mp4/mkv/webm"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.item.url, download=True)
                if info:
                    self.item.title = info.get("title", self.item.title)
                    final = self._resolve_final_path(ydl, info)
                    self.item.filename = os.path.basename(final)
                    self.item.save_dir = os.path.dirname(final) or self.item.save_dir
            self.item.status = Status.COMPLETED
            self.item.downloaded_bytes = self.item.total_bytes or self.item.downloaded_bytes
            self.item.speed = 0.0
            import time
            self.item.completed_at = time.time()
            self.on_progress(self.item)
        except _Cancelled:
            self.item.status = (Status.PAUSED if self.item.status == Status.PAUSED
                                else Status.CANCELLED)
            self.on_progress(self.item)
        except Exception as e:  # noqa: BLE001 - surface yt-dlp errors to UI
            self.item.status = Status.ERROR
            self.item.error = str(e).strip().splitlines()[-1] if str(e) else "download failed"
            self.on_progress(self.item)


class _Cancelled(Exception):
    """Raised inside the progress hook to abort yt-dlp cleanly."""


def _find_ffmpeg() -> str:
    """Locate an ffmpeg binary: PATH, an SDM_FFMPEG env override, or None.

    yt-dlp needs ffmpeg to merge separate video+audio streams into one file.
    Without it, yt-dlp falls back to a single pre-muxed stream (lower quality
    but still works).
    """
    import shutil

    override = os.environ.get("SDM_FFMPEG")
    if override and os.path.exists(override):
        return override
    found = shutil.which("ffmpeg")
    if found:
        return os.path.dirname(found)
    return ""
