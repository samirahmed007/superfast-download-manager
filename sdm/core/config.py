"""App configuration + paths, persisted as JSON in the user's home."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict


APP_DIR = os.path.join(os.path.expanduser("~"), ".superfast-dm")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
DB_PATH = os.path.join(APP_DIR, "downloads.sqlite")


def _default_download_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), "Downloads", "SuperfastDM")
    return d


@dataclass
class Config:
    download_dir: str = ""
    max_concurrent: int = 3
    connections_per_download: int = 8
    theme: str = "dark"

    # Phase 2: enhancements
    clipboard_watch: bool = False          # auto-detect copied download links
    clipboard_auto_add: bool = False       # add silently vs. prompt
    speed_limit_kb: int = 0                # global cap in KB/s (0 = unlimited)
    schedule_enabled: bool = False
    schedule_start: str = "01:00"          # HH:MM — start queue at this time
    schedule_stop: str = "07:00"           # HH:MM — pause queue at this time

    # Defaults for new downloads (mirrors the web app's settings panel)
    default_priority: str = "normal"       # urgent | high | normal | low
    default_ext: str = "mp4"               # mp4 | webm | mkv | mp3 (mp3 = audio)
    default_audio_ext: str = "mp3"         # mp3 | m4a | opus | wav (audio-only)
    default_resolution: str = "best"       # best | 2160 | 1440 | 1080 | 720 | 480
    auto_start: bool = True                # start on add, or stay paused/queued
    confirm_remove: bool = True            # ask before removing from the list

    # v2: file handling
    temp_dir: str = ""                     # where .sdmpart lives (blank = beside file)
    preallocate: bool = True               # reserve the full size up front
    auto_cleanup: bool = True              # delete part/temp files on cancel/error
    auto_rename: bool = True               # rename instead of overwriting an existing file

    # v2: clipboard / window behaviour
    clipboard_auto_paste: bool = True      # prefill Add dialog from the clipboard
    minimize_to_tray: bool = False         # minimize hides to the system tray
    close_to_tray: bool = False            # closing hides to tray instead of quitting

    # v2: network
    http_version: str = "auto"             # auto | 1.1 | 2 | 3
    proxy: str = ""                        # http(s)/socks proxy URL (blank = system)
    dns_servers: str = ""                  # comma-separated custom DNS servers (best-effort)

    def __post_init__(self):
        if not self.download_dir:
            self.download_dir = _default_download_dir()

    @classmethod
    def load(cls) -> "Config":
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items()
                          if k in cls.__dataclass_fields__})
        except (OSError, ValueError):
            return cls()

    def save(self):
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
