"""Add Download dialog with metadata fetch + quality/format picker.

Mirrors the web app flow: paste a URL, click Fetch, see title/thumbnail/uploader
and a dropdown of available qualities, choose priority + category + save folder,
then add. Metadata is fetched off the UI thread.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QObject, Signal, QThread
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QSpinBox, QFileDialog, QWidget,
    QSizePolicy,
)

import requests

from ..core.models import DownloadItem, Priority, Kind
from ..core.probe import probe, ProbeResult
from .util import fmt_bytes, fmt_eta


CATEGORIES = ["Auto", "Media", "Video", "Audio", "Software", "Documents",
              "Archives", "Images", "Other"]


class _ProbeWorker(QObject):
    done = Signal(object)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            self.done.emit(probe(self.url))
        except Exception as e:  # noqa: BLE001
            r = ProbeResult(url=self.url, kind=Kind.HTTP)
            r.error = str(e)
            self.done.emit(r)


class AddDialog(QDialog):
    def __init__(self, parent, default_dir: str, default_connections: int,
                 initial_url: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add Download")
        self.setMinimumWidth(620)
        self.result_item: DownloadItem | None = None
        self._probe: ProbeResult | None = None
        self._default_conn = default_connections
        self._thread: QThread | None = None

        root = QVBoxLayout(self)

        # URL row
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit(initial_url)
        self.url_edit.setPlaceholderText("Paste a video page or direct file URL")
        self.url_edit.returnPressed.connect(self._fetch)
        self.fetch_btn = QPushButton("Fetch")
        self.fetch_btn.setObjectName("primary")
        self.fetch_btn.clicked.connect(self._fetch)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.fetch_btn)
        root.addLayout(url_row)

        # metadata preview (thumbnail + title/uploader/duration)
        meta = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(160, 90)
        self.thumb.setStyleSheet("background:#22262e;border-radius:8px;")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setText("no preview")
        meta.addWidget(self.thumb)

        info_col = QVBoxLayout()
        self.title_lbl = QLabel("—")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setStyleSheet("font-size:15px;font-weight:600;")
        self.sub_lbl = QLabel("")
        self.sub_lbl.setStyleSheet("color:#9aa0aa;")
        info_col.addWidget(self.title_lbl)
        info_col.addWidget(self.sub_lbl)
        info_col.addStretch(1)
        meta.addLayout(info_col, 1)
        root.addLayout(meta)

        # quality + options grid
        grid = QGridLayout()
        grid.addWidget(QLabel("Quality:"), 0, 0)
        self.quality = QComboBox()
        self.quality.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid.addWidget(self.quality, 0, 1, 1, 3)

        self.audio_only = QCheckBox("Audio only (MP3)")
        self.audio_only.stateChanged.connect(self._on_audio_toggled)
        grid.addWidget(self.audio_only, 1, 1)

        grid.addWidget(QLabel("Priority:"), 2, 0)
        self.priority = QComboBox()
        for p in Priority:
            self.priority.addItem(p.value.capitalize(), p)
        self.priority.setCurrentIndex(2)  # normal
        grid.addWidget(self.priority, 2, 1)

        grid.addWidget(QLabel("Category:"), 2, 2)
        self.category = QComboBox()
        self.category.addItems(CATEGORIES)
        grid.addWidget(self.category, 2, 3)

        grid.addWidget(QLabel("Connections:"), 3, 0)
        self.conn = QSpinBox()
        self.conn.setRange(1, 32)
        self.conn.setValue(default_connections)
        grid.addWidget(self.conn, 3, 1)
        root.addLayout(grid)

        # save dir
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Save to:"))
        self.dir_edit = QLineEdit(default_dir)
        dir_row.addWidget(self.dir_edit, 1)
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse)
        dir_row.addWidget(browse)
        root.addLayout(dir_row)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#9aa0aa;")
        root.addWidget(self.status_lbl)

        # buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.add_btn = QPushButton("Add Download")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(self.add_btn)
        root.addLayout(btns)

        if initial_url:
            self._fetch()

    # ---- fetch ----------------------------------------------------------
    def _fetch(self):
        url = self.url_edit.text().strip()
        if not url:
            return
        self.fetch_btn.setEnabled(False)
        self.status_lbl.setText("Fetching metadata…")
        self._thread = QThread()
        self._worker = _ProbeWorker(url)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_probe)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_probe(self, result: ProbeResult):
        self._probe = result
        self.fetch_btn.setEnabled(True)
        if result.error:
            self.status_lbl.setText(f"⚠ {result.error[:90]}")
        else:
            self.status_lbl.setText("Ready. Pick a quality and add.")
        self.title_lbl.setText(result.title or result.suggested_name or result.url)
        subs = []
        if result.uploader:
            subs.append(result.uploader)
        if result.duration:
            subs.append(fmt_eta(result.duration))
        if result.extractor:
            subs.append(result.extractor)
        if result.total_bytes:
            subs.append(fmt_bytes(result.total_bytes))
        self.sub_lbl.setText("  ·  ".join(subs))

        self._populate_quality(result)
        self._load_thumb(result.thumbnail)
        if result.kind == Kind.MEDIA:
            self.category.setCurrentText("Media")

    def _populate_quality(self, result: ProbeResult):
        self.quality.clear()
        if result.best_format:
            self.quality.addItem(f"Best available ({result.best_format.label})", "auto")
        for f in result.formats:
            self.quality.addItem(f.label, f.format_id)
        if self.quality.count() == 0:
            self.quality.addItem("Default", "auto")

    def _load_thumb(self, url: str):
        if not url:
            self.thumb.setText("no preview")
            return
        try:
            data = requests.get(url, timeout=10).content
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                self.thumb.setPixmap(pix.scaled(
                    self.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        except requests.RequestException:
            pass
        self.thumb.setText("no preview")

    def _on_audio_toggled(self, state):
        self.quality.setEnabled(not self.audio_only.isChecked())

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose folder", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    # ---- accept ---------------------------------------------------------
    def _accept(self):
        url = self.url_edit.text().strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            self.status_lbl.setText("⚠ Enter a valid http(s) URL")
            return
        p = self._probe
        from ..core.manager import guess_kind
        kind = p.kind if p else guess_kind(url)
        fmt_id = self.quality.currentData() or "auto"
        chosen = None
        if p:
            chosen = next((f for f in p.formats if f.format_id == fmt_id), p.best_format)

        cat = self.category.currentText()
        item = DownloadItem(
            url=url,
            save_dir=self.dir_edit.text().strip(),
            connections=self.conn.value(),
            kind=kind,
            priority=Priority(self.priority.currentData()),
            category="" if cat == "Auto" else cat,
            format_id="" if fmt_id == "auto" else fmt_id,
            audio_only=self.audio_only.isChecked(),
        )
        if p:
            item.title = p.title
            item.uploader = p.uploader
            item.extractor = p.extractor
            item.duration = p.duration
            item.thumbnail = p.thumbnail
            if p.kind == Kind.HTTP and p.suggested_name:
                item.filename = p.suggested_name
            if p.total_bytes:
                item.total_bytes = p.total_bytes
        if chosen:
            item.ext = "mp3" if self.audio_only.isChecked() else chosen.ext
            item.resolution = chosen.resolution
            if chosen.filesize and not item.total_bytes:
                item.total_bytes = chosen.filesize
        self.result_item = item
        self.accept()
