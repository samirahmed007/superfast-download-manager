"""Left navigation sidebar: brand header, status filters, categories, settings.

Mirrors the web app's Sidebar — the filter buttons act like a radio group and
emit the selected filter id; category buttons emit the selected category name
(or None for "All").
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QButtonGroup,
    QWidget,
)

from .util import category_color, muted

NAV_ITEMS = [
    ("all", "All Downloads"),
    ("active", "Active"),
    ("queued", "Queued"),
    ("paused", "Paused"),
    ("completed", "Completed"),
    ("failed", "Failed"),
]

# Standard categories always shown in the sidebar (even at zero count), so the
# category rail reads as a stable set of "cards" rather than appearing only
# once an item happens to use one.
STANDARD_CATEGORIES = ["Software", "Media", "Documents", "Archives", "Images", "Other"]


class Sidebar(QFrame):
    filter_changed = Signal(str)
    category_changed = Signal(object)  # str or None
    open_settings = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(232)
        self._active_category = None
        self._nav_btns: dict[str, QPushButton] = {}
        self._cat_btns: list[QPushButton] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 16, 14, 14)
        root.setSpacing(14)

        # Brand
        brand = QHBoxLayout()
        logo = QLabel("⬇")
        logo.setFixedSize(38, 38)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #a874ff, stop:1 #f65fa6); border-radius:11px;"
            "color:white; font-size:18px;")
        brand.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("Superfast<span style='color:#f65fa6'>DM</span>")
        t.setObjectName("brandTitle")
        sub = QLabel("SMART DOWNLOAD MANAGER")
        sub.setObjectName("brandSub")
        titles.addWidget(t)
        titles.addWidget(sub)
        brand.addLayout(titles)
        brand.addStretch(1)
        root.addLayout(brand)

        # Library nav
        lib_lbl = QLabel("LIBRARY")
        lib_lbl.setObjectName("navGroupLabel")
        root.addWidget(lib_lbl)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for fid, label in NAV_ITEMS:
            b = QPushButton(label)
            b.setObjectName("navItem")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, f=fid: self.filter_changed.emit(f))
            self._nav_group.addButton(b)
            self._nav_btns[fid] = b
            root.addWidget(b)
        self._nav_btns["all"].setChecked(True)

        # Categories
        cat_lbl = QLabel("CATEGORIES")
        cat_lbl.setObjectName("navGroupLabel")
        root.addWidget(cat_lbl)
        self._cat_container = QVBoxLayout()
        self._cat_container.setSpacing(2)
        root.addLayout(self._cat_container)

        root.addStretch(1)

        # Settings footer
        settings_btn = QPushButton("⚙  Engine Settings")
        settings_btn.setObjectName("navItem")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.clicked.connect(self.open_settings.emit)
        root.addWidget(settings_btn)

    def set_counts(self, counts: dict[str, int]):
        for fid, label in NAV_ITEMS:
            n = counts.get(fid, 0)
            self._nav_btns[fid].setText(f"{label}    ({n})" if n else label)

    def set_categories(self, cats: list[tuple[str, int]]):
        # Preserve the current selection across rebuilds so refreshing counts
        # doesn't silently reset the active category filter.
        prev = self._active_category

        while self._cat_container.count():
            it = self._cat_container.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._cat_btns.clear()

        counts = dict(cats)
        # Always show the standard set, then any extra custom categories in use.
        names = list(STANDARD_CATEGORIES)
        for name, _ in cats:
            if name not in names:
                names.append(name)

        all_btn = self._mk_cat("All", None, muted(), sum(counts.values()))
        for name in names:
            self._mk_cat(name, name, category_color(name), counts.get(name, 0))

        # restore selection (fall back to All)
        target = None
        for b in self._cat_btns:
            if b.property("cat_value") == prev:
                target = b
                break
        (target or all_btn).setChecked(True)

    def _mk_cat(self, label, value, color, count):
        b = QPushButton(f"●  {label}" + (f"    ({count})" if count else ""))
        b.setObjectName("navItem")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"QPushButton#navItem {{ color: {color}; }}")
        b.setProperty("cat_value", value)
        b.clicked.connect(lambda _c=False, v=value: self._pick_cat(b, v))
        self._cat_container.addWidget(b)
        self._cat_btns.append(b)
        return b

    def _pick_cat(self, btn, value):
        self._active_category = value
        for b in self._cat_btns:
            b.setChecked(b is btn)
        self.category_changed.emit(value)
