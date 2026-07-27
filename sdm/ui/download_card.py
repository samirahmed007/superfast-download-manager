"""A single download rendered as a rich card (mirrors the web app's DownloadCard).

Shows thumbnail, title, source/quality/category badges, a gradient progress
bar, live stats, and contextual action buttons. Emits high-level intents;
the main window wires them to the manager.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QColor, QAction
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QProgressBar,
    QSizePolicy, QToolButton, QMenu,
)

from ..core.models import DownloadItem, Status, Priority
from .util import (
    fmt_bytes, fmt_speed, fmt_eta, fmt_duration, fmt_relative,
    status_color, priority_color, category_color, muted,
)
from .segment_bar import SegmentBar
from . import theme


class DownloadCard(QFrame):
    resume = Signal(str)
    pause = Signal(str)
    stop = Signal(str)
    cancel = Signal(str)
    remove = Signal(str)
    open_file = Signal(str)
    open_folder = Signal(str)
    copy_url = Signal(str)
    rename = Signal(str)
    set_priority = Signal(str, object)  # (id, Priority)
    # Emitted on a body click so the window can drive multi-select.
    # Args: (id, ctrl_held, shift_held)
    clicked = Signal(str, bool, bool)

    def __init__(self, item: DownloadItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("downloadCard")
        self._thumb_loaded = False
        self._selected = False
        self._build()
        self.update_item(item)

    # ---- selection ------------------------------------------------------
    def set_selected(self, on: bool):
        if on == self._selected:
            return
        self._selected = on
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def is_selected(self) -> bool:
        return self._selected

    def mousePressEvent(self, event):
        from PySide6.QtCore import Qt as _Qt
        mods = event.modifiers()
        self.clicked.emit(
            self.item.id,
            bool(mods & _Qt.ControlModifier),
            bool(mods & _Qt.ShiftModifier),
        )
        super().mousePressEvent(event)

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
        # Priority: a compact dropdown button, click to change (like the web app).
        self.priority_btn = QToolButton()
        self.priority_btn.setObjectName("priorityBtn")
        self.priority_btn.setCursor(Qt.PointingHandCursor)
        self.priority_btn.setPopupMode(QToolButton.InstantPopup)
        self.priority_btn.setToolTip("Change priority")
        self._priority_menu = QMenu(self.priority_btn)
        for p in Priority:
            act = QAction(p.value.capitalize(), self._priority_menu)
            act.setData(p)
            act.triggered.connect(lambda _c=False, pr=p: self._pick_priority(pr))
            self._priority_menu.addAction(act)
        self.priority_btn.setMenu(self._priority_menu)
        title_row.addWidget(self.priority_btn, 0, Qt.AlignRight)
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

        # Live per-connection activity strip (visible only while downloading)
        self.seg_bar = SegmentBar()
        self.seg_bar.setVisible(False)
        col.addWidget(self.seg_bar)

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

    def _mk_btn(self, key: str, label: str, slot, primary=False, tooltip=""):
        b = QPushButton(label)
        if primary:
            b.setObjectName("primary")
        b.setCursor(Qt.PointingHandCursor)
        if tooltip:
            b.setToolTip(tooltip)
        b.clicked.connect(slot)
        return b

    def _pick_priority(self, p: Priority):
        if p != self.item.priority:
            self.set_priority.emit(self.item.id, p)

    # ---- context menu ---------------------------------------------------
    def contextMenuEvent(self, event):
        """Right-click menu: copy link, change priority, and quick actions."""
        item = self.item
        iid = item.id
        st = item.status
        menu = QMenu(self)

        copy = menu.addAction("Copy link")
        copy.triggered.connect(lambda: self.copy_url.emit(iid))

        rename = menu.addAction("Rename…")
        rename.setShortcut("F2")
        rename.triggered.connect(lambda: self.rename.emit(iid))
        # Renaming needs the file closed; disabled only while actively downloading.
        rename.setEnabled(st not in (Status.DOWNLOADING, Status.CONNECTING))

        pr_menu = menu.addMenu("Set priority")
        for p in Priority:
            act = pr_menu.addAction(
                ("● " if p == item.priority else "   ") + p.value.capitalize())
            act.triggered.connect(lambda _c=False, pr=p: self._pick_priority(pr))

        menu.addSeparator()
        if st in (Status.DOWNLOADING, Status.CONNECTING, Status.QUEUED):
            menu.addAction("Pause").triggered.connect(lambda: self.pause.emit(iid))
            menu.addAction("Stop").triggered.connect(lambda: self.stop.emit(iid))
        if st in (Status.PAUSED, Status.ERROR, Status.CANCELLED):
            label = "Restart" if st == Status.CANCELLED else "Resume"
            menu.addAction(label).triggered.connect(lambda: self.resume.emit(iid))
        if st == Status.COMPLETED:
            menu.addAction("Open file").triggered.connect(
                lambda: self.open_file.emit(iid))
        menu.addAction("Open folder").triggered.connect(
            lambda: self.open_folder.emit(iid))
        menu.addSeparator()
        menu.addAction("Remove").triggered.connect(lambda: self.remove.emit(iid))
        menu.exec(event.globalPos())

    # ---- updates --------------------------------------------------------
    def update_item(self, item: DownloadItem):
        self.item = item
        self.setProperty("running", item.status == Status.DOWNLOADING)
        self.setProperty("error", item.status == Status.ERROR)
        self.style().unpolish(self)
        self.style().polish(self)

        self.title.setText(item.display_name or item.filename or item.url)
        self.title.setToolTip(item.title or item.url)

        # priority dropdown
        pc = priority_color(item.priority.value)
        self.priority_btn.setText(f"{item.priority.value.upper()}  ▾")
        self.priority_btn.setStyleSheet(
            f"QToolButton#priorityBtn {{ color: {pc}; border: 1px solid {pc}55;"
            f" border-radius: 6px; padding: 1px 6px; font-size: 10px;"
            f" font-weight: 700; background: transparent; }}"
            f"QToolButton#priorityBtn::menu-indicator {{ width: 0; }}"
            f"QToolButton#priorityBtn:hover {{ background: {pc}22; }}")
        # mark the active choice in the menu
        for act in self._priority_menu.actions():
            p = act.data()
            pval = p.value if isinstance(p, Priority) else str(p)
            act.setText((("● " if pval == item.priority.value else "   ")
                         + pval.capitalize()))

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
        self.thumb.setStyleSheet(f"color: {muted()}; font-size: 26px;")

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

        # Live per-connection strip: only while actively downloading with >1 seg.
        segs = item.seg_progress if item.status == Status.DOWNLOADING else []
        if len(segs) > 1:
            self.seg_bar.set_segments(segs)
            self.seg_bar.setVisible(True)
        else:
            self.seg_bar.clear()
            self.seg_bar.setVisible(False)

        color = status_color(item.status.value)
        track = theme.palette()["input"]
        # active downloads use the brand gradient; other states use a solid
        # status color so paused/error/completed read at a glance.
        if item.status in (Status.DOWNLOADING, Status.CONNECTING):
            chunk = theme.GRAD
        else:
            chunk = color
        self.bar.setStyleSheet(
            f"QProgressBar {{ background:{track}; border:none; border-radius:5px; }}"
            f"QProgressBar::chunk {{ background:{chunk}; border-radius:5px; }}")

        # stats line
        parts = []
        if item.status == Status.ERROR:
            parts.append(f"<span style='color:{color}'>{item.error or 'failed'}</span>")
        elif item.status == Status.COMPLETED:
            parts.append(f"{fmt_bytes(item.total_bytes or item.downloaded_bytes)} total")
            dur = item.download_duration
            if dur:
                parts.append(f"took {fmt_duration(dur)}")
                if item.total_bytes and dur > 0:
                    parts.append(f"avg {fmt_speed(item.total_bytes / dur)}")
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
                n = len(item.seg_progress)
                if n > 1:
                    parts.append(f"{n} connections")
        # A verified checksum earns a small badge on completed items.
        if item.status == Status.COMPLETED and item.checksum_ok:
            parts.append(f"<span style='color:{status_color('completed')}'>✓ verified</span>")
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
        active = st in (Status.DOWNLOADING, Status.CONNECTING, Status.QUEUED)
        if active:
            # Pause: keep partial data, resume from where it stopped.
            btns.append(self._mk_btn("pause", "Pause",
                                     lambda: self.pause.emit(iid),
                                     tooltip="Pause — keep progress"))
            # Stop: abort and discard partial data (clean restart later).
            btns.append(self._mk_btn("stop", "Stop",
                                     lambda: self.stop.emit(iid),
                                     tooltip="Stop — discard partial data"))
        if st in (Status.PAUSED, Status.ERROR, Status.CANCELLED):
            label = "Restart" if st == Status.CANCELLED else "Resume"
            btns.append(self._mk_btn("resume", label,
                                     lambda: self.resume.emit(iid), primary=True,
                                     tooltip=f"{label} download"))
        if st == Status.COMPLETED:
            btns.append(self._mk_btn("open", "Open",
                                     lambda: self.open_file.emit(iid), primary=True,
                                     tooltip="Open file"))
        btns.append(self._mk_btn("folder", "Folder",
                                 lambda: self.open_folder.emit(iid),
                                 tooltip="Open containing folder"))
        btns.append(self._mk_btn("remove", "Remove",
                                 lambda: self.remove.emit(iid),
                                 tooltip="Remove from list (Del)"))
        for b in btns:
            self.actions.addWidget(b)

    def restyle(self):
        """Re-apply theme-dependent inline styles after a theme switch."""
        if not self._thumb_loaded:
            self.thumb.setStyleSheet(f"color: {muted()}; font-size: 26px;")
        self._update_progress(self.item)
        self.seg_bar.update()
