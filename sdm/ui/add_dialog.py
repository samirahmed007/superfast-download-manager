"""Add Download dialog with metadata fetch + quality/format picker.

Mirrors the web app flow: paste a URL, click Fetch, see title/thumbnail/uploader
and a dropdown of available qualities, choose priority + category + save folder,
then add. Metadata is fetched off the UI thread.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QObject, Signal, QThread
from PySide6.QtGui import QPixmap, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QSpinBox, QFileDialog, QWidget,
    QSizePolicy, QScrollArea, QRadioButton, QButtonGroup, QFrame,
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
                 initial_url: str = "", cfg=None):
        super().__init__(parent)
        self.setWindowTitle("Add Download")
        self.setMinimumWidth(620)
        self.result_item: DownloadItem | None = None
        self._probe: ProbeResult | None = None
        self._default_conn = default_connections
        self._cfg = cfg
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

        # Output type toggle (Video / Audio) — mirrors the web app.
        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        self.video_btn = QPushButton("🎬  Video (MP4)")
        self.audio_btn = QPushButton("🎵  Audio (MP3)")
        for b in (self.video_btn, self.audio_btn):
            b.setCheckable(True)
            b.setObjectName("typeToggle")
            b.setCursor(Qt.PointingHandCursor)
            type_row.addWidget(b)
        self.video_btn.setChecked(True)
        self.video_btn.clicked.connect(lambda: self._set_audio_mode(False))
        self.audio_btn.clicked.connect(lambda: self._set_audio_mode(True))
        # hidden state flag replacing the old checkbox
        self.audio_only = QCheckBox()
        self.audio_only.setVisible(False)
        root.addLayout(type_row)

        # Available qualities — a scrollable grid of selectable rows.
        self.quality_header = QLabel("Available qualities")
        self.quality_header.setStyleSheet("color:#9aa0aa;font-size:11px;")
        root.addWidget(self.quality_header)
        self._fmt_group = QButtonGroup(self)
        self._fmt_scroll = QScrollArea()
        self._fmt_scroll.setObjectName("scrollArea")
        self._fmt_scroll.setWidgetResizable(True)
        self._fmt_scroll.setMinimumHeight(160)
        self._fmt_scroll.setMaximumHeight(260)
        self._fmt_host = QWidget()
        self._fmt_layout = QVBoxLayout(self._fmt_host)
        self._fmt_layout.setContentsMargins(2, 2, 2, 2)
        self._fmt_layout.setSpacing(6)
        self._fmt_layout.addStretch(1)
        self._fmt_scroll.setWidget(self._fmt_host)
        root.addWidget(self._fmt_scroll)
        self._fmt_buttons: list[QRadioButton] = []

        # start in audio-only mode when the configured default format is mp3
        if cfg is not None and cfg.default_ext == "mp3":
            self._set_audio_mode(True)

        # quality + options grid
        grid = QGridLayout()
        grid.addWidget(QLabel("Priority:"), 2, 0)
        self.priority = QComboBox()
        for p in Priority:
            self.priority.addItem(p.value.capitalize(), p)
        # honor the configured default priority (falls back to normal)
        default_pri = getattr(cfg, "default_priority", "normal") if cfg else "normal"
        idx = next((i for i, p in enumerate(Priority)
                    if p.value == default_pri), 2)
        self.priority.setCurrentIndex(idx)
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

        # Optional integrity checksum (direct files). "algo:hex" or bare hex.
        grid.addWidget(QLabel("Checksum:"), 3, 2)
        self.checksum_edit = QLineEdit()
        self.checksum_edit.setPlaceholderText("optional — sha256:… or md5:…")
        self.checksum_edit.setToolTip(
            "Verify the finished file against this checksum.\n"
            "Format: algo:hexdigest (e.g. sha256:ab12…) or a bare hex digest.")
        grid.addWidget(self.checksum_edit, 3, 3)
        root.addLayout(grid)

        # Per-download file handling: auto-rename instead of overwriting.
        self.auto_rename = QCheckBox("Auto-rename if a file with the same name exists")
        self.auto_rename.setChecked(
            getattr(cfg, "auto_rename", True) if cfg is not None else True)
        self.auto_rename.setToolTip(
            "When the target file already exists, save as “name (1).ext” instead "
            "of overwriting it.")
        root.addWidget(self.auto_rename)

        # save dir
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Save to:"))
        self.dir_edit = QLineEdit(default_dir)
        self.dir_edit.setPlaceholderText("Type or paste a folder path…")
        self.dir_edit.setToolTip(
            "Type or paste a folder path, or use … to browse. "
            "The folder is created if it doesn't exist.")
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
        self.add_btn.setToolTip("Add this download  (Enter)")
        # Make it the dialog's default button so Enter triggers it once focused.
        self.add_btn.setDefault(True)
        self.add_btn.setAutoDefault(True)
        self.add_btn.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(self.add_btn)
        root.addLayout(btns)

        if initial_url:
            self._fetch()
        elif cfg is not None and getattr(cfg, "clipboard_auto_paste", False):
            # Auto-paste a link sitting on the clipboard into the URL field.
            clip = QGuiApplication.clipboard().text().strip()
            if clip.startswith(("http://", "https://")) and " " not in clip:
                self.url_edit.setText(clip)
                self.url_edit.selectAll()
                self.status_lbl.setText("Pasted from clipboard — press Fetch or Add.")

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
            self.status_lbl.setText("Ready. Press Enter or click Add Download.")
            # Fetch succeeded: move focus to Add so Enter adds immediately.
            self.add_btn.setFocus()
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

    def _clear_formats(self):
        for b in self._fmt_buttons:
            b.setParent(None)
            b.deleteLater()
        self._fmt_buttons.clear()
        # remove any group-header labels / separators too (keep the stretch)
        while self._fmt_layout.count() > 1:
            it = self._fmt_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _group_by_resolution(self, formats):
        """Group formats by resolution key, sorted highest-first (web parity)."""
        groups: dict[str, list] = {}
        for f in formats:
            if not f.has_video:
                continue
            key = f.resolution or (f"{f.height}p" if f.height else "video")
            groups.setdefault(key, []).append(f)

        def sort_key(k):
            digits = "".join(ch for ch in k if ch.isdigit())
            return -(int(digits) if digits else -1)
        return [(k, groups[k]) for k in sorted(groups, key=sort_key)]

    def _pick_group_best(self, group):
        """Choose the representative format for a resolution row.

        Prefer one that already has audio (no merge needed), then larger size.
        """
        return sorted(group, key=lambda f: (0 if f.has_audio else 1,
                                            -(f.filesize or 0)))[0]

    def _populate_quality(self, result: ProbeResult):
        self._clear_formats()
        self._result_formats = result.formats

        if result.kind != Kind.MEDIA:
            # Direct file: a single row describing the file.
            f = result.best_format
            label = "Direct download"
            sub = result.suggested_name or result.url
            if result.total_bytes:
                sub = f"{sub}  ·  {fmt_bytes(result.total_bytes)}"
            self._add_format_row("direct", label, sub, recommended=True,
                                 checked=True)
            self._set_audio_mode(False, allow_audio=False)
            return

        self._set_audio_mode(self.audio_only.isChecked(), allow_audio=True)
        self._rebuild_video_rows(result)

    def _rebuild_video_rows(self, result: ProbeResult):
        self._clear_formats()
        groups = self._group_by_resolution(result.formats)
        self.quality_header.setText(f"Available qualities ({len(groups)})")
        pref = (getattr(self._cfg, "default_resolution", "best")
                if self._cfg else "best")
        pref_h = pref.rstrip("p") if pref and pref != "best" else ""

        chosen_btn = None
        # the recommended format = best combined video+audio (matches web app)
        best_id = result.best_format.format_id if result.best_format else None
        for key, group in groups:
            best = self._pick_group_best(group)
            av = "video+audio" if best.has_audio else "video only"
            recommended = (best.format_id == best_id)
            bits = [av, best.ext.upper()]
            if best.filesize:
                bits.append(fmt_bytes(best.filesize))
            if best.note:
                bits.append(best.note)
            row = self._add_format_row(
                best.format_id, key, "  ·  ".join(bits),
                recommended=recommended)
            digits = "".join(ch for ch in key if ch.isdigit())
            if pref_h and digits == pref_h:
                chosen_btn = row
            elif chosen_btn is None and recommended:
                chosen_btn = row
        if chosen_btn is None and self._fmt_buttons:
            chosen_btn = self._fmt_buttons[0]
        if chosen_btn:
            chosen_btn.setChecked(True)

    def _add_format_row(self, fmt_id, title, subtitle, recommended=False,
                        checked=False) -> QRadioButton:
        card = QFrame()
        card.setObjectName("fmtRow")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        radio = QRadioButton()
        radio.setProperty("fmt_id", fmt_id)
        self._fmt_group.addButton(radio)
        self._fmt_buttons.append(radio)
        lay.addWidget(radio, 0, Qt.AlignVCenter)
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        head = QLabel(title + ("   ★ recommended" if recommended else ""))
        head.setStyleSheet("font-weight:600;")
        sub = QLabel(subtitle)
        sub.setStyleSheet("color:#9aa0aa;font-size:11px;")
        text_col.addWidget(head)
        text_col.addWidget(sub)
        lay.addLayout(text_col, 1)
        # click anywhere on the row selects it
        card.mousePressEvent = lambda _e, r=radio: r.setChecked(True)

        def _sync(on, c=card):
            c.setProperty("selected", bool(on))
            c.style().unpolish(c)
            c.style().polish(c)
        radio.toggled.connect(_sync)
        self._fmt_layout.insertWidget(self._fmt_layout.count() - 1, card)
        if checked:
            radio.setChecked(True)
        return radio

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

    def _set_audio_mode(self, audio: bool, allow_audio: bool = True):
        """Switch between Video and Audio output. In audio mode the quality
        list collapses to a single 'best audio' row (like the web app)."""
        self.audio_only.setChecked(audio)
        self.video_btn.setChecked(not audio)
        self.audio_btn.setChecked(audio)
        self.audio_btn.setEnabled(allow_audio)
        if audio:
            ext = (getattr(self._cfg, "default_audio_ext", "mp3")
                   if self._cfg else "mp3")
            self._clear_formats()
            self.quality_header.setText("Audio output")
            self._add_format_row(
                "audio-only", f"{ext.upper()} Audio — best quality",
                "Extracts the audio track. No video.",
                recommended=True, checked=True)
        elif getattr(self, "_probe", None) and self._probe.kind == Kind.MEDIA:
            self._rebuild_video_rows(self._probe)

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
        # Normalize a typed/pasted save folder (expand ~ and env vars).
        save_dir = self.dir_edit.text().strip().strip('"')
        if save_dir:
            save_dir = os.path.normpath(
                os.path.expandvars(os.path.expanduser(save_dir)))
        p = self._probe
        from ..core.manager import guess_kind
        kind = p.kind if p else guess_kind(url)

        audio = self.audio_only.isChecked()
        # read the selected quality row
        checked = self._fmt_group.checkedButton()
        fmt_id = checked.property("fmt_id") if checked else "auto"
        if fmt_id in (None, "", "direct", "audio-only"):
            fmt_id = "auto"
        chosen = None
        if p and fmt_id != "auto":
            chosen = next((f for f in p.formats if f.format_id == fmt_id), None)
        if chosen is None and p:
            chosen = p.best_format

        cat = self.category.currentText()
        # "Auto" → derive from the file's extension / media kind.
        if cat == "Auto":
            from ..core.models import categorize
            name = ""
            if p and p.kind == Kind.HTTP and p.suggested_name:
                name = p.suggested_name
            resolved_cat = categorize(name, url, is_media=(kind == Kind.MEDIA))
        else:
            resolved_cat = cat
        item = DownloadItem(
            url=url,
            save_dir=save_dir,
            connections=self.conn.value(),
            kind=kind,
            priority=Priority(self.priority.currentData()),
            category=resolved_cat,
            format_id="" if fmt_id == "auto" else fmt_id,
            audio_only=audio,
            checksum=self.checksum_edit.text().strip(),
            auto_rename=self.auto_rename.isChecked(),
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
        audio_ext = (getattr(self._cfg, "default_audio_ext", "mp3")
                     if self._cfg else "mp3")
        if audio:
            item.ext = audio_ext
        elif chosen:
            item.ext = chosen.ext
            item.resolution = chosen.resolution
            if chosen.filesize and not item.total_bytes:
                item.total_bytes = chosen.filesize
        self.result_item = item
        self.accept()
