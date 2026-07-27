<div align="center">

# ⚡ Superfast Download Manager

**A fast, free, premium-grade desktop download manager — built with Python + PySide6 (Qt).**

Multi-connection acceleration, 1000+ video sites, pause/resume, scheduling, and a clean light/dark UI. No ads. No sign-up. No nonsense.

![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Qt](https://img.shields.io/badge/UI-PySide6%20(Qt)-41CD52?logo=qt&logoColor=white)
![Version](https://img.shields.io/badge/version-2.0.0-8A2BE2)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

</div>

---

## Why you'll like it

Most download managers are either bloated, ad-riddled, or locked behind a paywall. This one is none of those. It borrows the best ideas from IDM and aria2 — parallel byte-range downloading with work-stealing — wraps them in a modern Qt interface, and adds full yt-dlp media support so you can grab videos from 1000+ sites with a quality picker. It's a single portable `.exe` or a proper installer. That's it.

## 🆕 What's new in 2.0 — integrity-first engine

Version 2.0 rebuilds the download core around one rule: **byte-perfect output, always — even at maximum speed.** Earlier versions could occasionally produce a file with the correct *size* but scrambled *content* (a large video that plays for a while, then skips or hangs). The cause was trusting the server to honour parallel `Range` requests. It no longer does:

- **Every connection is verified.** A parallel worker only writes data from a genuine `206 Partial Content` response whose `Content-Range` matches the exact byte offset it asked for. Anything else is rejected.
- **Writes are clamped to their segment.** A server that over-sends can never bleed bytes into a neighbouring segment.
- **Graceful single-stream fallback.** If a CDN ignores `Range` and streams the whole file (a `200`), the engine discards the scattered data and re-downloads as one verified stream instead of corrupting the output.
- **`If-Range` change detection.** Resuming a file that changed on the server no longer splices two versions together — it restarts cleanly.
- **Durable finish.** The file is `fsync`'d and its size asserted against the expected total *before* it's moved into place.

The result: integrity on par with — or better than — IDM, with the work-stealing speed fully intact.

## ✨ Features

- **⚡ Work-stealing multi-connection engine** — splits each file into up to 32 parallel byte-range connections. When one connection finishes early, it *steals the tail* of the slowest remaining segment, so a single slow mirror never bottlenecks the whole download.
- **🛡️ Verified integrity** — per-connection `206`/`Content-Range` validation, range-clamped writes, `If-Range` change detection, `fsync` + final size check, and optional checksum — byte-perfect files at full speed.
- **🌐 HTTP/2 (and HTTP/3 best-effort)** — enable in Settings ▸ Network (via the optional `httpx` package); falls back to HTTP/1.1 automatically.
- **🧦 Proxy, VPN & DNS** — route through an HTTP/SOCKS proxy, works transparently with system VPNs, and set custom DNS servers (via optional `dnspython`).
- **🎬 Video / media downloads** — YouTube, Vimeo, TikTok, and 1000+ sites via yt-dlp, with a quality/format picker grouped by resolution.
- **📋 Batch & playlist add** — paste many URLs at once, or expand a playlist / channel URL into individual downloads.
- **⏸️ Pause, resume & stop** — segmented downloads resume from exactly where they stopped (a `.sdmpart` sidecar tracks per-segment progress). *Pause* keeps partial data; *Stop* discards it for a clean restart.
- **🔍 File properties** — right-click any download for a full Properties panel: file type, location, size, source URL, status/progress, timing, average speed, and checksum verdict. All fields are selectable and copyable.
- **✏️ Rename downloads** — right-click ▸ Rename… or press `F2` to rename a file directly from the list. Works for completed, paused, and queued items; updates resume state so paused downloads still resume correctly.
- **🗂️ Advanced file handling** — configurable temp folder, file pre-allocation, automatic cleanup of part files, and **auto-rename** so a new download never overwrites an existing file.
- **🔐 Checksum verification** — optionally verify a finished file against an expected `sha256:` / `md5:` (or bare hex) digest; mismatches are flagged, not silently kept.
- **🗂️ Auto-categorization** — direct files are sorted into Software, Media, Documents, Archives, Images, or Other by extension; media links become Media.
- **🚦 Queue with priorities** — Urgent / High / Normal / Low, changeable per download from a dropdown or the right-click menu.
- **📎 Clipboard capture & auto-paste** — auto-detect copied download links, and auto-fill the Add dialog from the clipboard.
- **🔗 Per-task actions** — copy download link, change priority, and see the **total download duration** and average speed on finished items.
- **🕒 Scheduler** — restrict downloads to a time window (handles midnight crossing); global speed limit in KB/s.
- **🔻 Minimize / close to system tray** — keep downloading quietly in the background.
- **✅ Multi-select** — Ctrl/Shift-click rows (or `Ctrl+A`), then resume / pause / remove them in bulk.
- **📰 Activity & error log** — a collapsible bottom panel shows real-time status transitions, auto-opens on errors, and entries are copyable.
- **🌗 Light / dark themes** — live-switchable, plus "follow system".
- **💾 Persistent history** — the list survives restarts (SQLite).
- **⌨️ Full menu bar & keyboard shortcuts** — see below.

## 📥 Download & install (for users)

Grab the latest **`SuperfastDownloadManager-Setup-x.x.x.exe`** from the [Releases page](https://github.com/samirahmed007/superfast-download-manager/releases) and run it. The installer is per-user (no admin rights required), adds a Start Menu shortcut, and includes a clean uninstaller.

Prefer no install? A single portable **`SuperfastDownloadManager.exe`** is also attached to each release — just download and double-click.

> ffmpeg is optional. It's only needed to merge the highest-quality video+audio streams from media sites. Without it, the app downloads a single pre-muxed stream. Put `ffmpeg.exe` on your PATH or set the `SDM_FFMPEG` environment variable to its folder.

## ⌨️ Keyboard shortcuts

| Shortcut       | Action                          |
|----------------|---------------------------------|
| `Ctrl+N`       | New download                    |
| `Ctrl+Shift+N` | Batch / playlist add            |
| `Ctrl+V`       | Paste URL and add               |
| `Ctrl+F`       | Focus search                    |
| `Ctrl+A`       | Select all downloads            |
| `Esc`          | Clear selection                 |
| `Ctrl+Enter`   | Resume / start selected         |
| `Ctrl+P`       | Pause selected                  |
| `Ctrl+S`       | Stop selected (discard partial) |
| `F2`           | Rename selected download        |
| `Alt+Enter`    | Properties (right-click menu)    |
| `Delete`       | Remove selected from list       |
| `Ctrl+L`       | Toggle activity log             |
| `Ctrl+D`       | Toggle light / dark theme       |
| `Ctrl+,`       | Open settings                   |
| `Ctrl+Q`       | Exit                            |
| `F1`           | Keyboard shortcuts help         |

## 🚀 Run from source

```bash
git clone https://github.com/samirahmed007/superfast-download-manager.git
cd superfast-download-manager
pip install -r requirements.txt
python main.py
```

**Requirements:** Python 3.9+, Windows (tested on Windows 10). The core is cross-platform; the "open file/folder" actions use Windows-specific `os.startfile`.

## 🛠️ Build it yourself

Full instructions live in [`command.txt`](command.txt). Quick version:

```bash
pip install pyinstaller

# One portable .exe  ->  dist/onefile/SuperfastDownloadManager.exe
pyinstaller superfast.spec --clean --noconfirm

# App folder (installer input)  ->  dist/onedir/SuperfastDownloadManager/
pyinstaller superfast-onedir.spec --clean --noconfirm

# Windows installer (needs Inno Setup 6)  ->  installer_output/*-Setup-x.x.x.exe
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

## 💡 Usage

1. Press **Add** (or `Ctrl+N`) and paste a URL, or use **Paste + Add** to grab the clipboard. Use **Batch** for many URLs / playlists.
2. Direct file links download with parallel connections; video-site links are handled by yt-dlp automatically. After a fetch, just press **Enter** to add.
3. Select rows (Ctrl/Shift-click) to pause, resume, stop, or remove in bulk. Right-click for the same actions plus **Rename** (F2), **Properties** (Alt+Enter), Open file / folder, and Copy URL.
4. Tune folder, connections, parallelism, speed limit, defaults, clipboard, schedule, **temp folder, HTTP version, proxy/DNS, tray, and auto-rename** from **Settings** (`Ctrl+,`). The Save-to and Temp folder fields accept typed or pasted paths — no need to use the file browser.

## 📂 Where things live

- Config: `~/.superfast-dm/config.json`
- Download history DB: `~/.superfast-dm/downloads.sqlite`
- Default download folder: `~/Downloads/SuperfastDM`

## 📝 Notes

- Range support is per-server. Many CDNs ignore `Range` and return the whole file — the app detects this, discards the partial parallel data, and re-downloads as a single **verified** connection so the output is never corrupted. This is expected.
- HTTP/2 needs the optional `httpx[http2]` package and custom DNS needs `dnspython`; both are listed in `requirements.txt`. Without them the app still runs on HTTP/1.1 + system DNS.
- Respect the terms of service of the sites you download from and applicable copyright law.

## 🧩 Architecture

```
main.py                     entry point (icon, app id)
assets/icon.ico|png         application icon
superfast.spec              PyInstaller one-file build spec
superfast-onedir.spec       PyInstaller one-dir build spec (installer input)
installer.iss               Inno Setup installer script
command.txt                 build instructions
sdm/core/
  models.py                 DownloadItem, Segment, Status, Kind, categorize()
  http_downloader.py        segmented work-stealing HTTP engine + checksum
  media_downloader.py       yt-dlp wrapper
  manager.py                queue, concurrency, routing, lifecycle, event log
  store.py                  SQLite persistence
  probe.py                  metadata / format / playlist probing
  eventlog.py               in-process activity/error log
  config.py                 settings + paths
sdm/ui/
  main_window.py            Qt main window, menus, shortcuts, selection
  sidebar.py                filters + category cards
  download_card.py          per-item card with live segment view
  segment_bar.py            live per-connection activity strip
  add_dialog.py             single add with quality picker
  batch_dialog.py           batch / playlist add
  settings_dialog.py        tabbed settings
  log_panel.py              collapsible activity/error panel
  theme.py                  light/dark palettes + stylesheet
  util.py                   formatting helpers + color tokens
```

## 📄 License

Released under the [MIT License](LICENSE).

---

<div align="center">

Built with Python & PySide6 by **[Samir Uddin Ahmed](https://github.com/samirahmed007)**.

If this saved you time, consider giving it a ⭐ — it helps others find it.

</div>

