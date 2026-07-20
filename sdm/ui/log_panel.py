"""Collapsible activity/error log panel docked at the bottom of the window.

Subscribes to the engine's shared EventLog and renders entries in a compact,
color-coded list. Auto-opens when an error arrives (like the web app's error
surface) and shows an unread-error badge on its header. Users can filter to
errors only, clear the log, or collapse the panel.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QCheckBox,
)

from ..core.eventlog import LOG, Entry, Level
from .util import muted, EMERALD, AMBER, RED
from . import theme


_LEVEL_COLOR = {Level.INFO: None, Level.WARN: AMBER, Level.ERROR: RED}
_LEVEL_ICON = {Level.INFO: "·", Level.WARN: "▲", Level.ERROR: "✕"}


class _LogBridge(QObject):
    """Marshals log callbacks (worker threads) onto the Qt thread."""
    arrived = Signal(object)


class LogPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logPanel")
        self._collapsed = True
        self._errors_only = False
        self._unread_errors = 0

        self._bridge = _LogBridge()
        self._bridge.arrived.connect(self._on_entry)
        LOG.subscribe(lambda e: self._bridge.arrived.emit(e))

        self._build()
        self._render_existing()
        self._apply_collapsed()

    # ---- construction ---------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header bar (always visible; click to toggle)
        self.header = QFrame()
        self.header.setObjectName("logHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.mousePressEvent = lambda _e: self.toggle()
        h = QHBoxLayout(self.header)
        h.setContentsMargins(14, 7, 10, 7)
        h.setSpacing(8)

        self.chevron = QLabel("▸")
        self.chevron.setObjectName("meta")
        h.addWidget(self.chevron)

        self.title = QLabel("Activity Log")
        self.title.setStyleSheet("font-weight: 600;")
        h.addWidget(self.title)

        self.badge = QLabel("")
        self.badge.setObjectName("logBadge")
        self.badge.setVisible(False)
        h.addWidget(self.badge)

        h.addStretch(1)

        self.errors_chk = QCheckBox("Errors only")
        self.errors_chk.toggled.connect(self._toggle_errors_only)
        # don't let clicks on the checkbox collapse the panel
        self.errors_chk.setAttribute(Qt.WA_NoMousePropagation, True)
        h.addWidget(self.errors_chk)

        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("logBtn")
        self.copy_btn.setFixedHeight(24)
        self.copy_btn.setToolTip("Copy all log entries to the clipboard")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.setAttribute(Qt.WA_NoMousePropagation, True)
        h.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("logBtn")
        self.clear_btn.setFixedHeight(24)
        self.clear_btn.setToolTip("Remove all log entries")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear)
        self.clear_btn.setAttribute(Qt.WA_NoMousePropagation, True)
        h.addWidget(self.clear_btn)

        root.addWidget(self.header)

        # scrollable entry list
        self.list = QListWidget()
        self.list.setObjectName("logList")
        self.list.setFixedHeight(160)
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        root.addWidget(self.list)

    # ---- state ----------------------------------------------------------
    def toggle(self):
        self._collapsed = not self._collapsed
        if not self._collapsed:
            self._unread_errors = 0
            self._refresh_badge()
        self._apply_collapsed()

    def open(self):
        if self._collapsed:
            self.toggle()

    def _apply_collapsed(self):
        self.list.setVisible(not self._collapsed)
        self.errors_chk.setVisible(not self._collapsed)
        self.copy_btn.setVisible(not self._collapsed)
        self.clear_btn.setVisible(not self._collapsed)
        self.chevron.setText("▸" if self._collapsed else "▾")

    def _toggle_errors_only(self, on: bool):
        self._errors_only = on
        self.list.clear()
        self._render_existing()

    def _clear(self):
        LOG.clear()
        self.list.clear()
        self._unread_errors = 0
        self._refresh_badge()

    def _copy(self):
        """Copy all (or errors-only, matching the current filter) log entries
        to the clipboard as plain text."""
        from PySide6.QtGui import QGuiApplication
        lines = []
        for e in LOG.entries():
            if self._errors_only and e.level != Level.ERROR:
                continue
            ts = time.strftime("%H:%M:%S", time.localtime(e.ts))
            src = f" [{e.source}]" if e.source else ""
            lines.append(f"{ts} {e.level.value.upper()}{src} {e.message}")
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.copy_btn.setText("Copied ✓")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("Copy"))

    # ---- rendering ------------------------------------------------------
    def _render_existing(self):
        for entry in LOG.entries():
            self._append(entry, scroll=False)
        self.list.scrollToBottom()

    def _on_entry(self, entry: Entry):
        self._append(entry)
        if entry.level == Level.ERROR:
            # surface errors: auto-open and, if still collapsed, count unread
            if self._collapsed:
                self._unread_errors += 1
                self._refresh_badge()
                self.open()

    def _append(self, entry: Entry, scroll: bool = True):
        if self._errors_only and entry.level != Level.ERROR:
            return
        color = _LEVEL_COLOR.get(entry.level) or muted()
        icon = _LEVEL_ICON.get(entry.level, "·")
        ts = time.strftime("%H:%M:%S", time.localtime(entry.ts))
        src = f"  <b>{entry.source}</b>" if entry.source else ""
        text = (f"<span style='color:{muted()}'>{ts}</span>  "
                f"<span style='color:{color}'>{icon}</span>{src}  "
                f"<span style='color:{color}'>{entry.message}</span>")
        lbl = QLabel(text)
        lbl.setTextFormat(Qt.RichText)
        lbl.setContentsMargins(10, 2, 10, 2)
        it = QListWidgetItem()
        it.setSizeHint(lbl.sizeHint())
        self.list.addItem(it)
        self.list.setItemWidget(it, lbl)
        if scroll:
            self.list.scrollToBottom()

    def _refresh_badge(self):
        if self._unread_errors > 0:
            self.badge.setText(f" {self._unread_errors} ")
            self.badge.setVisible(True)
        else:
            self.badge.setVisible(False)

    def restyle(self):
        # re-render entries so inline theme colors update
        self.list.clear()
        self._render_existing()
