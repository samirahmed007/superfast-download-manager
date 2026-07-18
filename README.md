# Superfast Download Manager

A fast, free desktop download manager for Windows, built with Python + PySide6 (Qt).

## Features

- **Multi-connection acceleration** — splits each file into up to 32 parallel
  byte-range connections (IDM/aria2 style) for maximum speed on servers that
  support HTTP ranges. Falls back cleanly to a single stream when they don't.
- **Video / media downloads** — YouTube, Vimeo, TikTok, and 1000+ sites via
  yt-dlp. Links are auto-detected and routed to the media engine.
- **Pause & resume** — segmented downloads resume from exactly where they
  stopped (a `.sdmpart` sidecar tracks per-segment progress). Media downloads
  continue via yt-dlp's own partial files.
- **Queue with concurrency control** — cap how many downloads run at once and
  how many connections each uses.
- **Persistent history** — the list survives restarts (SQLite).
- **Live progress** — per-item speed, ETA, progress bar, and a global speed
  readout in the status bar.
- **Dark premium UI** — clean Qt interface, context menus, drag-free workflow.

## Requirements

- Python 3.9+
- Windows (tested on Windows 10). The core is cross-platform; `os.startfile`
  for "open file/folder" is Windows-specific.
- Optional: **ffmpeg** on your PATH (or set the `SDM_FFMPEG` env var to a folder
  containing `ffmpeg.exe`). Needed only to merge high-quality video+audio from
  media sites. Without it, media still downloads at a slightly lower muxed
  quality.

## Install & run

```bash
pip install -r requirements.txt
python main.py
```

## Usage

1. Paste a URL into the top bar and press **Add** (or **Paste + Add** to grab
   the clipboard).
2. Direct file links download with parallel connections. Video-site links are
   handled by yt-dlp automatically.
3. Select rows to **Pause**, **Resume**, **Cancel**, or **Remove**. Right-click
   for the same actions plus **Open file / folder** and **Copy URL**.
4. Set the save folder, connections-per-download, and max parallel downloads
   from the controls row. Settings persist.

## Where things live

- Config: `~/.superfast-dm/config.json`
- Download history DB: `~/.superfast-dm/downloads.sqlite`
- Default download folder: `~/Downloads/SuperfastDM`

## Notes

- Range support is per-server. Many CDNs (e.g. some Cloudflare endpoints)
  ignore `Range` and return the whole file — the app detects this and uses a
  single connection. This is expected, not a bug.
- Respect the terms of service of the sites you download from and applicable
  copyright law.

## Architecture

```
main.py                     entry point
sdm/core/
  models.py                 DownloadItem, Segment, Status, Kind
  http_downloader.py        segmented parallel HTTP engine
  media_downloader.py       yt-dlp wrapper
  manager.py                queue, concurrency, routing, lifecycle
  store.py                  SQLite persistence
  config.py                 settings + paths
sdm/ui/
  main_window.py            Qt main window
  util.py                   formatting + dark stylesheet
```
