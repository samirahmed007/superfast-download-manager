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
