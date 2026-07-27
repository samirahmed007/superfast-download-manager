"""File properties dialog — a detailed read-out for a single download.

Mirrors a file-manager "Properties" window: name, location, size, type,
source URL, status/progress, timing, connection details, and integrity info.
Values are copyable and the source URL / file path can be opened directly.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QGroupBox,
)

from ..core.models import DownloadItem, Status
from .util import fmt_bytes, fmt_speed, fmt_duration


def _fmt_time(ts) -> str:
    if not ts:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (ValueError, OSError):
        return "—"


class PropertiesDialog(QDialog):
    def __init__(self, item: DownloadItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle("Properties")
        self.setMinimumWidth(520)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        item = self.item
        fp = item.filepath
        exists = bool(fp) and os.path.exists(fp)
        on_disk = 0
        if exists:
            try:
                on_disk = os.path.getsize(fp)
            except OSError:
                on_disk = 0

        # Header: file name + type
        name = item.filename or item.display_name or "(unnamed)"
        header = QLabel(name)
        header.setObjectName("cardTitle")
        header.setWordWrap(True)
        header.setStyleSheet("font-size:16px;font-weight:700;")
        root.addWidget(header)

        # ---- General ----
        gen = QGroupBox("General")
        gg = QGridLayout(gen)
        gg.setColumnStretch(1, 1)
        gg.setHorizontalSpacing(14)
        gg.setVerticalSpacing(6)
        self._row = 0

        ext = (os.path.splitext(name)[1].lstrip(".").upper()
               or (item.ext or "").upper() or "—")
        self._add(gg, "Type", f"{ext} file" if ext != "—" else "—")
        self._add(gg, "Location", item.save_dir or "—", copy=True)
        self._add(gg, "Full path", fp or "—", copy=True)

        total = item.total_bytes or 0
        size_str = fmt_bytes(total) if total else "unknown"
        if total:
            size_str += f"  ({total:,} bytes)"
        self._add(gg, "Size", size_str)
        if exists and on_disk != total:
            self._add(gg, "On disk", f"{fmt_bytes(on_disk)}  ({on_disk:,} bytes)")
        self._add(gg, "Exists on disk", "Yes" if exists else "No")
        root.addWidget(gen)

        # ---- Download ----
        dl = QGroupBox("Download")
        dg = QGridLayout(dl)
        dg.setColumnStretch(1, 1)
        dg.setHorizontalSpacing(14)
        dg.setVerticalSpacing(6)
        self._row = 0

        self._add(dg, "Status", item.status.value.capitalize())
        pct = item.progress * 100
        self._add(dg, "Progress",
                  f"{pct:.1f}%  ({fmt_bytes(item.downloaded_bytes)} of "
                  f"{fmt_bytes(total) if total else 'unknown'})")
        if item.status == Status.DOWNLOADING and item.speed:
            self._add(dg, "Speed", fmt_speed(item.speed))
        self._add(dg, "Kind", item.kind.value.upper())
        self._add(dg, "Category", item.category or "—")
        self._add(dg, "Priority", item.priority.value.capitalize())
        self._add(dg, "Connections", str(item.connections))
        self._add(dg, "Resumable", "Yes" if item.supports_ranges else "No")
        if item.resolution:
            self._add(dg, "Resolution", item.resolution)
        if item.error:
            self._add(dg, "Error", item.error)
        root.addWidget(dl)

        # ---- Source ----
        src = QGroupBox("Source")
        sg = QGridLayout(src)
        sg.setColumnStretch(1, 1)
        sg.setHorizontalSpacing(14)
        sg.setVerticalSpacing(6)
        self._row = 0
        self._add(sg, "URL", item.url or "—", copy=True)
        if item.extractor:
            self._add(sg, "Extractor", item.extractor)
        if item.uploader:
            self._add(sg, "Uploader", item.uploader)
        if item.duration:
            self._add(sg, "Media duration", fmt_duration(item.duration) or "—")
        root.addWidget(src)

        # ---- Timing / integrity ----
        tim = QGroupBox("Timing & integrity")
        tg = QGridLayout(tim)
        tg.setColumnStretch(1, 1)
        tg.setHorizontalSpacing(14)
        tg.setVerticalSpacing(6)
        self._row = 0
        self._add(tg, "Added", _fmt_time(item.added_at))
        self._add(tg, "Started", _fmt_time(item.started_at))
        self._add(tg, "Completed", _fmt_time(item.completed_at))
        dur = item.download_duration
        if dur:
            avg = f"  ·  avg {fmt_speed(total / dur)}" if total and dur > 0 else ""
            self._add(tg, "Duration", f"{fmt_duration(dur)}{avg}")
        if item.checksum:
            verdict = ("verified ✓" if item.checksum_ok
                       else "MISMATCH ✗" if item.checksum_ok is False
                       else "not yet verified")
            self._add(tg, "Checksum", f"{item.checksum}  ({verdict})")
        root.addWidget(tim)

        # ---- Buttons ----
        btns = QHBoxLayout()
        if item.url:
            open_url = QPushButton("Open URL")
            open_url.clicked.connect(self._open_url)
            btns.addWidget(open_url)
        if exists:
            open_folder = QPushButton("Open folder")
            open_folder.clicked.connect(self._open_folder)
            btns.addWidget(open_folder)
        btns.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        root.addLayout(btns)

    def _add(self, grid: QGridLayout, label: str, value: str, copy: bool = False):
        key = QLabel(f"{label}:")
        key.setStyleSheet("color:#9aa0aa;")
        key.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        val = QLabel(value)
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(key, self._row, 0, Qt.AlignTop)
        grid.addWidget(val, self._row, 1)
        if copy and value and value != "—":
            btn = QPushButton("Copy")
            btn.setFixedWidth(56)
            btn.clicked.connect(lambda _c=False, v=value: self._copy(v))
            grid.addWidget(btn, self._row, 2, Qt.AlignTop)
        self._row += 1

    def _copy(self, text: str):
        QGuiApplication.clipboard().setText(text)

    def _open_url(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(self.item.url))

    def _open_folder(self):
        if os.path.isdir(self.item.save_dir):
            os.startfile(self.item.save_dir)  # noqa: S606 - Windows open
