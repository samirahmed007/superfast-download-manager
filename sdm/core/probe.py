"""URL metadata + format probing (mirrors the web app's /api/fetch-info).

For media URLs, uses yt-dlp to extract title, uploader, thumbnail, duration and
the full list of selectable qualities/formats — without downloading. For direct
file URLs, does a lightweight HTTP HEAD to get size/filename.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse, unquote

import requests

from .models import Format, Kind
from .manager import guess_kind

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class ProbeResult:
    url: str
    kind: Kind
    title: str = ""
    uploader: str = ""
    extractor: str = ""
    duration: int = 0
    thumbnail: str = ""
    is_live: bool = False
    total_bytes: int = 0
    suggested_name: str = ""
    formats: List[Format] = field(default_factory=list)
    best_format: Optional[Format] = None
    error: str = ""


def _find_ffmpeg() -> str:
    import shutil
    override = os.environ.get("SDM_FFMPEG")
    if override and os.path.exists(override):
        return override
    found = shutil.which("ffmpeg")
    return os.path.dirname(found) if found else ""


def probe(url: str) -> ProbeResult:
    url = url.strip()
    kind = guess_kind(url)
    if kind == Kind.MEDIA:
        return _probe_media(url)
    # HTTP direct file: try media probe as a fallback only if it looks like a page
    result = _probe_http(url)
    return result


def _probe_http(url: str) -> ProbeResult:
    res = ProbeResult(url=url, kind=Kind.HTTP)
    try:
        r = requests.head(url, headers={"User-Agent": USER_AGENT},
                          allow_redirects=True, timeout=20)
        headers = {k.lower(): v for k, v in r.headers.items()}
        try:
            res.total_bytes = int(headers.get("content-length", 0))
        except ValueError:
            res.total_bytes = 0
        cd = headers.get("content-disposition", "")
        if "filename=" in cd:
            res.suggested_name = unquote(cd.split("filename=")[-1].strip().strip('"; '))
        if not res.suggested_name:
            res.suggested_name = unquote(os.path.basename(urlparse(r.url).path)) or "download"
        res.title = res.suggested_name
        ext = os.path.splitext(res.suggested_name)[1].lstrip(".").lower() or "bin"
        res.formats = [Format(
            format_id="direct", ext=ext, resolution="file",
            note=headers.get("content-type", ""), filesize=res.total_bytes,
            has_video=False, has_audio=False, is_best=True,
        )]
        res.best_format = res.formats[0]
    except requests.RequestException as e:
        res.error = str(e)
    return res


def _probe_media(url: str) -> ProbeResult:
    res = ProbeResult(url=url, kind=Kind.MEDIA)
    try:
        import yt_dlp
    except ImportError:
        res.error = "yt-dlp is not installed"
        return res

    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True,
    }
    ff = _find_ffmpeg()
    if ff:
        opts["ffmpeg_location"] = ff
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        res.error = str(e).strip().splitlines()[-1] if str(e) else "probe failed"
        return res

    if info is None:
        res.error = "no metadata returned"
        return res
    # a playlist entry — take the first entry
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next((e for e in info["entries"] if e), info)

    res.title = info.get("title") or info.get("fulltitle") or url
    res.uploader = info.get("uploader") or info.get("channel") or ""
    res.extractor = info.get("extractor_key") or info.get("extractor") or ""
    res.duration = int(info.get("duration") or 0)
    res.is_live = bool(info.get("is_live"))
    thumbs = info.get("thumbnails") or []
    res.thumbnail = info.get("thumbnail") or (thumbs[-1]["url"] if thumbs else "")

    res.formats = _build_formats(info.get("formats") or [])
    res.best_format = next(
        (f for f in res.formats if f.has_video and f.has_audio and f.height), None)
    if res.best_format:
        res.best_format.is_best = True
    return res


def _build_formats(raw: list) -> List[Format]:
    formats: List[Format] = []
    for f in raw:
        vcodec = f.get("vcodec") or "none"
        acodec = f.get("acodec") or "none"
        has_v = vcodec != "none"
        has_a = acodec != "none"
        if not has_v and not has_a:
            continue
        height = f.get("height")
        size = int(f.get("filesize") or f.get("filesize_approx") or 0)
        tbr = f.get("tbr")
        note = f.get("format_note") or (f"{round(tbr)}kbps" if tbr else "")
        formats.append(Format(
            format_id=str(f.get("format_id")),
            ext=(f.get("ext") or "mp4").lower(),
            resolution=f.get("resolution") or (f"{height}p" if height else "audio"),
            height=height, width=f.get("width"),
            fps=int(f["fps"]) if f.get("fps") else None,
            note=note, filesize=size,
            has_video=has_v, has_audio=has_a,
            vcodec=vcodec if has_v else "", acodec=acodec if has_a else "",
        ))
    # sort: video by height desc, then audio; keep combined near top
    def key(fm: Format):
        return (0 if fm.has_video else 1, -(fm.height or 0), -(fm.filesize or 0))
    formats.sort(key=key)
    return formats
