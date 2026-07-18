"""SQLite persistence for the download list (survives app restarts)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import List

from .models import DownloadItem

_FIELDS = [
    "id", "url", "filename", "save_dir", "kind", "status", "total_bytes",
    "downloaded_bytes", "connections", "supports_ranges", "error", "added_at",
    "started_at", "completed_at", "priority", "category", "format_id", "ext",
    "resolution", "title", "uploader", "extractor", "duration", "thumbnail",
    "audio_only",
]


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cols = ", ".join(f"{f} TEXT" for f in _FIELDS if f != "id")
        with self._lock:
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS downloads (id TEXT PRIMARY KEY, {cols})"
            )
            # Migrate older DBs: add any columns introduced after the table
            # was first created (ALTER TABLE ADD COLUMN is a no-op-safe way to
            # bring an existing schema up to date without dropping data).
            existing = {
                r["name"] for r in self._conn.execute(
                    "PRAGMA table_info(downloads)").fetchall()
            }
            for f in _FIELDS:
                if f not in existing:
                    self._conn.execute(f"ALTER TABLE downloads ADD COLUMN {f} TEXT")
            self._conn.commit()

    def upsert(self, item: DownloadItem):
        row = item.to_row()
        vals = {}
        for f in _FIELDS:
            v = row.get(f)
            vals[f] = json.dumps(v) if isinstance(v, bool) else v
        placeholders = ", ".join(f":{f}" for f in _FIELDS)
        updates = ", ".join(f"{f}=:{f}" for f in _FIELDS if f != "id")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO downloads ({', '.join(_FIELDS)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                vals,
            )
            self._conn.commit()

    def delete(self, item_id: str):
        with self._lock:
            self._conn.execute("DELETE FROM downloads WHERE id=?", (item_id,))
            self._conn.commit()

    def all(self) -> List[DownloadItem]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM downloads ORDER BY added_at ASC"
            ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["total_bytes"] = int(d.get("total_bytes") or 0)
            d["downloaded_bytes"] = int(d.get("downloaded_bytes") or 0)
            d["connections"] = int(d.get("connections") or 8)
            d["duration"] = int(d.get("duration") or 0)
            d["added_at"] = float(d.get("added_at") or 0)
            for tf in ("started_at", "completed_at"):
                d[tf] = float(d[tf]) if d.get(tf) not in (None, "", "None") else None

            def _truthy(v):
                return v in ("true", "1", "True", True)
            d["supports_ranges"] = _truthy(d.get("supports_ranges"))
            d["audio_only"] = _truthy(d.get("audio_only"))
            items.append(DownloadItem.from_row(d))
        return items

    def close(self):
        with self._lock:
            self._conn.close()
