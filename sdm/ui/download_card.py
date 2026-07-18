"""A single download rendered as a rich card (mirrors the web app's DownloadCard).

Shows thumbnail, title, source/quality/category badges, a gradient progress
bar, live stats, and contextual action buttons. Emits high-level intents;
the main window wires them to the manager.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QProgressBar,
    QSizePolicy,
)

from ..core.models import DownloadItem, Status, Priority
from .util import (
    fmt_bytes, fmt_speed, fmt_eta, fmt_duration, fmt_relative,
    status_color, priority_color, category_color, MUTED,
)


class DownloadCard(QFrame):
    resume = Signal(str)
    pause = Signal(str)
    cancel = Signal(str)
    remove = Signal(str)
    open_file = Signal(str)
    open_folder = Signal(str)
    copy_url = Signal(str)
    set_priority = Signal(str, object)  # (id, Priority)

    def __init__(self, item: DownloadItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("downloadCard")
        self._thumb_loaded = False
        self._build()
        self.update_item(item)

    # ---- construction ---------------------------------------------------
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        # Thumbnail
        self.thumb = QLabel()
        self.thumb.setObjectName("thumb")
        self.thumb.setFixedSize(QSize(84, 84))
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setScaledContents(False)
        root.addWidget(self.thumb, 0, Qt.AlignTop)

        # Main column
        col = QVBoxLayout()
        col.setSpacing(6)
        root.addLayout(col, 1)

        # Title row
        title_row = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(False)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_row.addWidget(self.title, 1)
        self.priority_lbl = QLabel()
        self.priority_lbl.setObjectName("badge")
        title_row.addWidget(self.priority_lbl, 0, Qt.AlignRight)
        col.addLayout(title_row)

        # Badges / meta row
        self.meta_row = QHBoxLayout()
        self.meta_row.setSpacing(6)
        self.meta_row.addStretch(1)
        col.addLayout(self.meta_row)

        # Progress bar
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        col.addWidget(self.bar)

        # Stats line
        self.stats = QLabel()
        self.stats.setObjectName("meta")
        col.addWidget(self.stats)

        # Action buttons
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        self.actions.addStretch(1)
        col.addLayout(self.actions)
        self._buttons: dict[str, QPushButton] = {}

    def _mk_btn(self, key: str, label: str, slot, primary=False):
        b = QPushButton(label)
        if primary:
            b.setObjectName("primary")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    # ---- updates --------------------------------------------------------
    def update_item(self, item: DownloadItem):
        self.item = item
        self.setProperty("running", item.status == Status.DOWNLOADING)
        self.setProperty("error", item.status == Status.ERROR)
        self.style().unpolish(self)
        self.style().polish(self)

        self.title.setText(item.display_name or item.filename or item.url)
        self.title.setToolTip(item.title or item.url)

        # priority badge
        self.priority_lbl.setText(item.priority.value.upper())
        self.priority_lbl.setStyleSheet(
            f"color: {priority_color(item.priority.value)};")

        self._rebuild_badges(item)
        self._update_thumb(item)
        self._update_progress(item)
        self._rebuild_actions(item)

    def _clear_layout(self, layout, keep_stretch=True):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        if keep_stretch:
            layout.addStretch(1)

    def _rebuild_badges(self, item: DownloadItem):
        # remove all then re-add (order: source, resolution, ext, category, age)
        while self.meta_row.count():
            it = self.meta_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        def add_badge(text, color=None):
            lbl = QLabel(text)
            lbl.setObjectName("badge")
            if color:
                lbl.setStyleSheet(f"color: {color}; border-color: {color}55;")
            self.meta_row.addWidget(lbl)

        if item.extractor:
            add_badge(item.extractor.upper())
        if item.resolution:
            add_badge(item.resolution)
        if item.ext:
            add_badge(item.ext.upper())
        if item.category:
            add_badge(item.category, category_color(item.category))
        age = fmt_relative(item.added_at)
        if age:
            lbl = QLabel(age)
            lbl.setObjectName("meta")
            self.meta_row.addWidget(lbl)
        self.meta_row.addStretch(1)

    def _update_thumb(self, item: DownloadItem):
        if self._thumb_loaded:
            return
        is_audio = item.audio_only or item.ext == "mp3"
        # placeholder glyph
        self.thumb.setText("♪" if is_audio else "▶")
        self.thumb.setStyleSheet(f"color: {MUTED}; font-size: 26px;")

    def set_thumbnail(self, pixmap: QPixmap):
        if pixmap and not pixmap.isNull():
            self.thumb.setText("")
            self.thumb.setPixmap(pixmap.scaled(
                84, 84, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            self._thumb_loaded = True

    def _update_progress(self, item: DownloadItem):
        pct = item.progress
        show_bar = item.status in (
            Status.DOWNLOADING, Status.PAUSED, Status.COMPLETED,
            Status.ERROR, Status.CONNECTING)
        self.bar.setVisible(show_bar)
        if item.status == Status.COMPLETED:
            self.bar.setValue(1000)
        else:
            self.bar.setValue(int(pct * 10))

        color = status_color(item.status.value)
        self.bar.setStyleSheet(
            "QProgressBar { background:#201e29; border:none; border-radius:5px; }"
            f"QProgressBar::chunk {{ background:{color}; border-radius:5px; }}")

        # stats line
        parts = []
        if item.status == Status.ERROR:
            parts.append(f"<span style='color:{color}'>{item.error or 'failed'}</span>")
        elif item.status == Status.COMPLETED:
            parts.append(f"{fmt_bytes(item.total_bytes or item.downloaded_bytes)} total")
        else:
            dl = fmt_bytes(item.downloaded_bytes)
            if item.total_bytes:
                parts.append(f"{dl} / {fmt_bytes(item.total_bytes)} ({pct:.0f}%)")
            else:
                parts.append(dl)
            if item.status == Status.DOWNLOADING and item.speed:
                parts.append(fmt_speed(item.speed))
                eta = ((item.total_bytes - item.downloaded_bytes) / item.speed
                       if item.total_bytes and item.speed else 0)
                if eta:
                    parts.append(f"ETA {fmt_eta(eta)}")
        parts.append(f"<b style='color:{color}'>{item.status.value}</b>")
        self.stats.setText("  ·  ".join(parts))

    def _rebuild_actions(self, item: DownloadItem):
        while self.actions.count():
            it = self.actions.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.actions.addStretch(1)

        st = item.status
        iid = item.id
        btns = []
        if st in (Status.DOWNLOADING, Status.CONNECTING, Status.QUEUED):
            btns.append(self._mk_btn("pause", "Pause",
                                     lambda: self.pause.emit(iid)))
        if st in (Status.PAUSED, Status.ERROR):
            btns.append(self._mk_btn("resume", "Resume",
                                     lambda: self.resume.emit(iid), primary=True))
        if st == Status.COMPLETED:
            btns.append(self._mk_btn("open", "Open",
                                     lambda: self.open_file.emit(iid), primary=True))
        btns.append(self._mk_btn("folder", "Folder",
                                 lambda: self.open_folder.emit(iid)))
        if st not in (Status.COMPLETED, Status.CANCELLED):
            btns.append(self._mk_btn("cancel", "Cancel",
                                     lambda: self.cancel.emit(iid)))
        btns.append(self._mk_btn("remove", "Remove",
                                 lambda: self.remove.emit(iid)))
        for b in btns:
            self.actions.addWidget(b)
