"""Main application window — sidebar + top bar + stat cards + card list.

Layout mirrors the TurboGrab web app: a fixed left Sidebar (status filters and
categories), a TopBar (search + Add), a row of StatCards, and a scrollable list
of DownloadCards. Card widgets emit intents that are wired to the manager here.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QScrollArea, QFrame, QMessageBox,
)

from ..core.config import Config, DB_PATH
from ..core.manager import DownloadManager
from ..core.models import DownloadItem, Status, Priority
from ..core.store import Store
from .util import DARK_QSS, fmt_speed, MUTED
from .sidebar import Sidebar
from .stat_cards import StatCards
from .download_card import DownloadCard
from .thumb_loader import ThumbnailLoader
from .settings_dialog import SettingsDialog
from .clipboard_watch import ClipboardWatcher
from .scheduler import Scheduler


class ProgressBridge(QObject):
    """Marshals engine progress callbacks (worker threads) onto the Qt thread."""
    progressed = Signal(object)


# Maps a sidebar filter id to a predicate over an item's status.
_FILTERS = {
    "all": lambda s: True,
    "active": lambda s: s in (Status.DOWNLOADING, Status.CONNECTING),
    "queued": lambda s: s == Status.QUEUED,
    "paused": lambda s: s == Status.PAUSED,
    "completed": lambda s: s == Status.COMPLETED,
    "failed": lambda s: s == Status.ERROR,
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = Config.load()
        self.cfg.save()
        os.makedirs(self.cfg.download_dir, exist_ok=True)

        self.store = Store(DB_PATH)
        self.manager = DownloadManager(
            self.store, self.cfg.download_dir,
            max_concurrent=self.cfg.max_concurrent,
            default_connections=self.cfg.connections_per_download,
        )

        self.bridge = ProgressBridge()
        self.bridge.progressed.connect(self._on_item_update)
        self.manager.set_progress_callback(
            lambda item: self.bridge.progressed.emit(item))

        self._cards: dict[str, DownloadCard] = {}
        self._active_filter = "all"
        self._active_category = None
        self._search = ""

        self.thumbs = ThumbnailLoader(self)
        self.thumbs.loaded.connect(self._on_thumb)

        self.setWindowTitle("Superfast Download Manager")
        self.resize(1180, 720)
        self.setStyleSheet(DARK_QSS)

        self._build_ui()

        self.manager.load_persisted()
        for item in self.manager.items.values():
            self._ensure_card(item)
        self._resort_cards()
        self._apply_filter()
        self._refresh_sidebar()

        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._update_stats)
        self._ticker.start(1000)

        # Live components
        self.manager.set_speed_limit(self.cfg.speed_limit_kb * 1024)
        self.clipboard = ClipboardWatcher(self)
        self.clipboard.link_found.connect(self._on_clipboard_link)
        self.clipboard.set_enabled(self.cfg.clipboard_watch)
        self.scheduler = Scheduler(self)
        self.scheduler.window_changed.connect(
            lambda is_open: self.manager.set_schedule_hold(not is_open))
        self.scheduler.configure(self.cfg.schedule_enabled,
                                 self.cfg.schedule_start, self.cfg.schedule_stop)

    # ---- UI construction -----------------------------------------------
    def _build_ui(self):
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        self.sidebar.filter_changed.connect(self._on_filter)
        self.sidebar.category_changed.connect(self._on_category)
        self.sidebar.open_settings.connect(self._open_settings)
        outer.addWidget(self.sidebar)

        # Right side
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        outer.addLayout(right, 1)

        right.addWidget(self._build_topbar())

        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(20, 16, 20, 16)
        body_l.setSpacing(16)

        self.stats = StatCards()
        body_l.addWidget(self.stats)

        # scrollable card list
        self.scroll = QScrollArea()
        self.scroll.setObjectName("scrollArea")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_container)
        body_l.addWidget(self.scroll, 1)

        # empty-state label
        self.empty_lbl = QLabel("No downloads yet. Paste a link and hit Add.")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setStyleSheet(f"color: {MUTED}; font-size: 14px;")
        body_l.addWidget(self.empty_lbl)

        right.addWidget(body, 1)
        self.setCentralWidget(central)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search downloads…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMaximumWidth(420)
        self.search_input.textChanged.connect(self._on_search)
        lay.addWidget(self.search_input, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {MUTED};")
        lay.addWidget(self.status_label)
        lay.addStretch(0)

        add_url = QPushButton("Paste + Add")
        add_url.clicked.connect(self._paste_and_add)
        lay.addWidget(add_url)

        add_btn = QPushButton("＋  Add")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(lambda: self._open_add_dialog())
        lay.addWidget(add_btn)
        return bar

    # ---- card management ------------------------------------------------
    def _ensure_card(self, item: DownloadItem) -> DownloadCard:
        card = self._cards.get(item.id)
        if card is not None:
            return card
        card = DownloadCard(item)
        card.resume.connect(self.manager.start)
        card.pause.connect(self.manager.pause)
        card.cancel.connect(self.manager.cancel)
        card.remove.connect(self._remove)
        card.open_file.connect(self._open_file)
        card.open_folder.connect(self._open_folder)
        card.copy_url.connect(self._copy_url)
        card.set_priority.connect(self.manager.set_priority)
        self._cards[item.id] = card
        # insert before the trailing stretch
        self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        if item.thumbnail:
            self.thumbs.request(item.thumbnail)
        return card

    def _on_item_update(self, item: DownloadItem):
        self.manager.items[item.id] = item
        card = self._ensure_card(item)
        card.update_item(item)
        self._apply_filter_to(card)
        self._refresh_sidebar()

    def _on_thumb(self, url, pixmap):
        for card in self._cards.values():
            if card.item.thumbnail == url:
                card.set_thumbnail(pixmap)

    def _resort_cards(self):
        # Order by priority then added time, matching the manager's queue.
        order = {Priority.URGENT: 0, Priority.HIGH: 1,
                 Priority.NORMAL: 2, Priority.LOW: 3}
        cards = sorted(
            self._cards.values(),
            key=lambda c: (order.get(c.item.priority, 2), c.item.added_at))
        for c in cards:
            self.list_layout.removeWidget(c)
        for i, c in enumerate(cards):
            self.list_layout.insertWidget(i, c)

    # ---- filtering ------------------------------------------------------
    def _card_visible(self, item: DownloadItem) -> bool:
        if not _FILTERS[self._active_filter](item.status):
            return False
        if self._active_category and item.category != self._active_category:
            return False
        if self._search:
            hay = f"{item.title} {item.filename} {item.url}".lower()
            if self._search not in hay:
                return False
        return True

    def _apply_filter_to(self, card: DownloadCard):
        card.setVisible(self._card_visible(card.item))

    def _apply_filter(self):
        any_visible = False
        for card in self._cards.values():
            vis = self._card_visible(card.item)
            card.setVisible(vis)
            any_visible = any_visible or vis
        self.empty_lbl.setVisible(not any_visible)

    def _on_filter(self, fid):
        self._active_filter = fid
        self._apply_filter()

    def _on_category(self, cat):
        self._active_category = cat
        self._apply_filter()

    def _on_search(self, text):
        self._search = text.strip().lower()
        self._apply_filter()

    def _refresh_sidebar(self):
        items = list(self.manager.items.values())
        counts = {fid: sum(1 for i in items if pred(i.status))
                  for fid, pred in _FILTERS.items()}
        self.sidebar.set_counts(counts)
        cats: dict[str, int] = {}
        for i in items:
            if i.category:
                cats[i.category] = cats.get(i.category, 0) + 1
        self.sidebar.set_categories(sorted(cats.items()))

    # ---- actions --------------------------------------------------------
    def _paste_and_add(self):
        text = QGuiApplication.clipboard().text().strip()
        if text.startswith("http"):
            self._open_add_dialog(text)

    def _on_clipboard_link(self, url: str):
        if self.cfg.clipboard_auto_add:
            self.manager.add(url)
            self.status_label.setText(f"Auto-added: {url[:50]}")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Download link detected")
        box.setText("A download link was copied to your clipboard:")
        box.setInformativeText(url[:120])
        add = box.addButton("Add with options…", QMessageBox.AcceptRole)
        quick = box.addButton("Quick add", QMessageBox.ActionRole)
        box.addButton("Ignore", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is add:
            self._open_add_dialog(url)
        elif clicked is quick:
            self.manager.add(url)

    def _open_add_dialog(self, initial_url: str = ""):
        from .add_dialog import AddDialog
        dlg = AddDialog(self, self.cfg.download_dir,
                        self.cfg.connections_per_download, initial_url=initial_url)
        if dlg.exec() and dlg.result_item is not None:
            self.manager.add(item=dlg.result_item)

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        dlg.changed.connect(self._apply_settings)
        dlg.exec()

    def _apply_settings(self):
        self.manager.default_dir = self.cfg.download_dir
        os.makedirs(self.cfg.download_dir, exist_ok=True)
        self.manager.default_connections = self.cfg.connections_per_download
        self.manager.set_max_concurrent(self.cfg.max_concurrent)
        self.manager.set_speed_limit(self.cfg.speed_limit_kb * 1024)
        self.clipboard.set_enabled(self.cfg.clipboard_watch)
        self.scheduler.configure(self.cfg.schedule_enabled,
                                 self.cfg.schedule_start, self.cfg.schedule_stop)
        if not self.cfg.schedule_enabled:
            self.manager.set_schedule_hold(False)

    def _remove(self, iid):
        item = self.manager.items.get(iid)
        name = (item.display_name if item else iid) or iid
        if QMessageBox.question(self, "Remove",
                                f"Remove “{name}” from the list?") != QMessageBox.Yes:
            return
        self.manager.remove(iid)
        card = self._cards.pop(iid, None)
        if card is not None:
            self.list_layout.removeWidget(card)
            card.deleteLater()
        self._apply_filter()
        self._refresh_sidebar()

    def _open_file(self, iid):
        item = self.manager.items.get(iid)
        if item and item.status == Status.COMPLETED and os.path.exists(item.filepath):
            os.startfile(item.filepath)  # noqa: S606 - Windows open

    def _open_folder(self, iid):
        item = self.manager.items.get(iid)
        if item and os.path.isdir(item.save_dir):
            os.startfile(item.save_dir)  # noqa: S606

    def _copy_url(self, iid):
        item = self.manager.items.get(iid)
        if item:
            QGuiApplication.clipboard().setText(item.url)

    # ---- stats ----------------------------------------------------------
    def _update_stats(self):
        items = list(self.manager.items.values())
        active = [i for i in items
                  if i.status in (Status.DOWNLOADING, Status.CONNECTING)]
        queued = sum(1 for i in items if i.status == Status.QUEUED)
        speed = sum(i.speed for i in active)
        downloaded = sum(i.downloaded_bytes for i in items)
        completed = sum(1 for i in items if i.status == Status.COMPLETED)
        failed = sum(1 for i in items if i.status == Status.ERROR)
        self.stats.update_stats(
            active=len(active), queued=queued, speed=speed,
            downloaded_bytes=downloaded, completed=completed,
            library=len(items), failed=failed)
        self.status_label.setText(
            f"{len(active)} active · {fmt_speed(speed)}" if active
            else f"{len(items)} in library")

    def closeEvent(self, event):
        self.manager.shutdown()
        self.store.close()
        super().closeEvent(event)
