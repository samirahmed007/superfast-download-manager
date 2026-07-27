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
from .util import fmt_speed, muted
from . import theme
from .sidebar import Sidebar
from .stat_cards import StatCards
from .download_card import DownloadCard
from .thumb_loader import ThumbnailLoader
from .settings_dialog import SettingsDialog
from .clipboard_watch import ClipboardWatcher
from .scheduler import Scheduler
from .log_panel import LogPanel


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
        self._selected_ids: set[str] = set()   # ids of selected cards
        self._anchor_id: str | None = None      # for shift-range selection

        self.thumbs = ThumbnailLoader(self)
        self.thumbs.loaded.connect(self._on_thumb)

        self.setWindowTitle("Superfast Download Manager")
        self.resize(1180, 720)
        self._set_window_icon()
        self._apply_theme(self.cfg.theme, persist=False)

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
        self._apply_engine_options()
        self.clipboard = ClipboardWatcher(self)
        self.clipboard.link_found.connect(self._on_clipboard_link)
        self.clipboard.set_enabled(self.cfg.clipboard_watch)
        self.scheduler = Scheduler(self)
        self.scheduler.window_changed.connect(
            lambda is_open: self.manager.set_schedule_hold(not is_open))
        self.scheduler.configure(self.cfg.schedule_enabled,
                                 self.cfg.schedule_start, self.cfg.schedule_stop)

        self._build_menus()
        self._build_tray()

    # ---- window chrome --------------------------------------------------
    def _set_window_icon(self):
        """Load the bundled app icon; harmless if the asset is missing."""
        import sys
        from PySide6.QtGui import QIcon
        # When frozen by PyInstaller, assets live under sys._MEIPASS; from
        # source, the project root is three levels up from this file.
        root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        for name in ("icon.ico", "icon.png"):
            path = os.path.join(root, "assets", name)
            if os.path.exists(path):
                self.setWindowIcon(QIcon(path))
                return

    # ---- menu bar -------------------------------------------------------
    def _build_menus(self):
        """Application menu bar: File / Edit / View / Help."""
        from PySide6.QtGui import QAction, QKeySequence

        bar = self.menuBar()

        def act(menu, text, slot, shortcut=None, tip=""):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setStatusTip(tip)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        file_menu = bar.addMenu("&File")
        act(file_menu, "New Download…", lambda: self._open_add_dialog(),
            "Ctrl+N", "Add a single download")
        act(file_menu, "Batch / Playlist Add…", self._open_batch_dialog,
            "Ctrl+Shift+N", "Add many URLs or expand a playlist")
        act(file_menu, "Paste URL + Add", self._paste_and_add, "Ctrl+V")
        file_menu.addSeparator()
        act(file_menu, "Settings…", self._open_settings, "Ctrl+,")
        file_menu.addSeparator()
        act(file_menu, "Exit", self.close, "Ctrl+Q")

        edit_menu = bar.addMenu("&Edit")
        act(edit_menu, "Select All", self._select_all_visible, "Ctrl+A")
        act(edit_menu, "Clear Selection", self._clear_selection, "Escape")
        edit_menu.addSeparator()
        act(edit_menu, "Resume Selected", self._resume_selected, "Ctrl+Return")
        act(edit_menu, "Pause Selected", self._pause_selected, "Ctrl+P")
        act(edit_menu, "Stop Selected", self._stop_selected, "Ctrl+S")
        act(edit_menu, "Rename…", self._rename_selected, "F2")
        act(edit_menu, "Remove Selected", self._remove_selected, "Delete")

        view_menu = bar.addMenu("&View")
        act(view_menu, "Toggle Activity Log", self.log_panel.toggle, "Ctrl+L")
        act(view_menu, "Toggle Light / Dark Theme", self._toggle_theme, "Ctrl+D")
        act(view_menu, "Focus Search", lambda: self.search_input.setFocus(),
            "Ctrl+F")

        help_menu = bar.addMenu("&Help")
        act(help_menu, "Keyboard Shortcuts", self._show_shortcuts, "F1")
        act(help_menu, "About Superfast Download Manager", self._show_about)

    def _show_shortcuts(self):
        rows = [
            ("Ctrl+N", "New download"),
            ("Ctrl+Shift+N", "Batch / playlist add"),
            ("Ctrl+V", "Paste URL and add"),
            ("Ctrl+F", "Focus search"),
            ("Ctrl+A", "Select all downloads"),
            ("Esc", "Clear selection"),
            ("Ctrl+Enter", "Resume / start selected"),
            ("Ctrl+P", "Pause selected"),
            ("Ctrl+S", "Stop selected (discard partial)"),
            ("F2", "Rename selected download"),
            ("Delete", "Remove selected from list"),
            ("Ctrl+L", "Toggle activity log"),
            ("Ctrl+D", "Toggle light / dark theme"),
            ("Ctrl+,", "Open settings"),
            ("Ctrl+Q", "Exit"),
            ("F1", "This shortcuts help"),
        ]
        body = "".join(
            f"<tr><td style='padding:2px 16px 2px 0;'>"
            f"<b>{k}</b></td><td style='padding:2px 0;'>{d}</td></tr>"
            for k, d in rows)
        html = f"<h3>Keyboard Shortcuts</h3><table>{body}</table>"
        box = QMessageBox(self)
        box.setWindowTitle("Keyboard Shortcuts")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.exec()

    def _show_about(self):
        from .. import __version__
        html = (
            "<h2>Superfast Download Manager</h2>"
            "<p>A fast, multi-connection download manager with an "
            "integrity-first work-stealing engine, media (yt-dlp) support, "
            "checksum verification, scheduling, and clipboard capture.</p>"
            f"<p><b>Version:</b> {__version__}<br>"
            "<b>Developer:</b> Samir Uddin Ahmed</p>"
            "<p style='color:gray;'>Built with Python & PySide6.</p>")
        box = QMessageBox(self)
        box.setWindowTitle("About")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.exec()

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

        # selection action bar (hidden until one or more cards are selected)
        self.sel_bar = QFrame()
        self.sel_bar.setObjectName("selBar")
        sel_l = QHBoxLayout(self.sel_bar)
        sel_l.setContentsMargins(14, 8, 14, 8)
        sel_l.setSpacing(10)
        self.sel_label = QLabel("0 selected")
        self.sel_label.setStyleSheet("font-weight: 600;")
        sel_l.addWidget(self.sel_label)
        sel_l.addStretch(1)
        for text, tip, slot in (
            ("Resume", "Resume/start selected (Ctrl+Enter)", self._resume_selected),
            ("Pause", "Pause selected (Ctrl+P)", self._pause_selected),
            ("Stop", "Stop selected, discard partial (Ctrl+S)", self._stop_selected),
            ("Remove", "Remove selected (Del)", self._remove_selected),
            ("Clear selection", "Deselect all (Esc)", self._clear_selection),
        ):
            b = QPushButton(text)
            b.setToolTip(tip)
            if text == "Remove":
                b.setObjectName("primary")
            b.clicked.connect(slot)
            sel_l.addWidget(b)
        self.sel_bar.setVisible(False)
        body_l.addWidget(self.sel_bar)

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
        self.empty_lbl.setStyleSheet(f"color: {muted()}; font-size: 14px;")
        body_l.addWidget(self.empty_lbl)

        right.addWidget(body, 1)

        # Bottom activity/error log panel (collapsed by default; auto-opens on error)
        self.log_panel = LogPanel()
        right.addWidget(self.log_panel)

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
        self.status_label.setStyleSheet(f"color: {muted()};")
        lay.addWidget(self.status_label)
        lay.addStretch(0)

        self.theme_btn = QPushButton()
        self.theme_btn.setFixedWidth(40)
        self.theme_btn.setToolTip("Toggle light / dark theme  (Ctrl+D)")
        self.theme_btn.clicked.connect(self._toggle_theme)
        self._refresh_theme_btn()
        lay.addWidget(self.theme_btn)

        add_url = QPushButton("Paste + Add")
        add_url.setToolTip("Add the URL currently on the clipboard  (Ctrl+V)")
        add_url.clicked.connect(self._paste_and_add)
        lay.addWidget(add_url)

        batch_btn = QPushButton("Batch")
        batch_btn.setToolTip("Add many URLs at once, or expand a playlist  (Ctrl+Shift+N)")
        batch_btn.clicked.connect(self._open_batch_dialog)
        lay.addWidget(batch_btn)

        add_btn = QPushButton("＋  Add")
        add_btn.setObjectName("primary")
        add_btn.setToolTip("Add a new download  (Ctrl+N)")
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
        card.stop.connect(self.manager.stop)
        card.cancel.connect(self.manager.cancel)
        card.remove.connect(self._remove)
        card.open_file.connect(self._open_file)
        card.open_folder.connect(self._open_folder)
        card.copy_url.connect(self._copy_url)
        card.rename.connect(self._rename)
        card.set_priority.connect(self.manager.set_priority)
        card.clicked.connect(self._on_card_clicked)
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

    def _quick_add(self, url: str):
        """Add a URL with configured defaults, honoring auto-start."""
        item = self.manager.add(url, priority=Priority(self.cfg.default_priority))
        if not self.cfg.auto_start:
            self.manager.pause(item.id)
        return item

    def _on_clipboard_link(self, url: str):
        if self.cfg.clipboard_auto_add:
            self._quick_add(url)
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
            self._quick_add(url)

    def _open_add_dialog(self, initial_url: str = ""):
        from .add_dialog import AddDialog
        dlg = AddDialog(self, self.cfg.download_dir,
                        self.cfg.connections_per_download,
                        initial_url=initial_url, cfg=self.cfg)
        if dlg.exec() and dlg.result_item is not None:
            self._add_item(dlg.result_item)

    def _open_batch_dialog(self):
        from .batch_dialog import BatchDialog
        dlg = BatchDialog(self, self.cfg.download_dir,
                          self.cfg.connections_per_download, cfg=self.cfg)
        if dlg.exec() and dlg.result_items:
            for item in dlg.result_items:
                self._add_item(item)
            self.status_label.setText(f"Added {len(dlg.result_items)} downloads")

    def _add_item(self, item: DownloadItem):
        """Add an item, respecting the auto-start setting (else stay paused)."""
        self.manager.add(item=item)
        if not self.cfg.auto_start:
            self.manager.pause(item.id)

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        dlg.changed.connect(self._apply_settings)
        dlg.theme_changed.connect(lambda name: self._apply_theme(name))
        dlg.exec()

    # ---- theme ----------------------------------------------------------
    def _apply_theme(self, name: str, persist: bool = True):
        app = QGuiApplication.instance()
        theme.apply_theme(app, name)
        if persist:
            self.cfg.theme = theme.current_theme()
            self.cfg.save()
        if hasattr(self, "theme_btn"):
            self._refresh_theme_btn()
        # restyle bits that use inline colors
        if hasattr(self, "empty_lbl"):
            self.empty_lbl.setStyleSheet(f"color: {muted()}; font-size: 14px;")
        if hasattr(self, "status_label"):
            self.status_label.setStyleSheet(f"color: {muted()};")
        for card in getattr(self, "_cards", {}).values():
            card.restyle()
        if hasattr(self, "log_panel"):
            self.log_panel.restyle()

    def _refresh_theme_btn(self):
        dark = theme.resolved_theme() == "dark"
        # show the icon of the theme you'd switch TO
        self.theme_btn.setText("☀" if dark else "☾")

    def _toggle_theme(self):
        # Toggle flips the resolved palette to its opposite as an explicit choice.
        self._apply_theme("light" if theme.resolved_theme() == "dark" else "dark")

    def _apply_engine_options(self):
        """Push file-handling + network settings into the download engine."""
        self.manager.set_engine_options(
            temp_dir=self.cfg.temp_dir,
            preallocate=self.cfg.preallocate,
            auto_cleanup=self.cfg.auto_cleanup,
            http_version=self.cfg.http_version,
            proxy=self.cfg.proxy,
            dns_servers=self.cfg.dns_servers,
        )

    def _apply_settings(self):
        self.manager.default_dir = self.cfg.download_dir
        os.makedirs(self.cfg.download_dir, exist_ok=True)
        self.manager.default_connections = self.cfg.connections_per_download
        self.manager.set_max_concurrent(self.cfg.max_concurrent)
        self.manager.set_speed_limit(self.cfg.speed_limit_kb * 1024)
        self._apply_engine_options()
        self.clipboard.set_enabled(self.cfg.clipboard_watch)
        self.scheduler.configure(self.cfg.schedule_enabled,
                                 self.cfg.schedule_start, self.cfg.schedule_stop)
        if not self.cfg.schedule_enabled:
            self.manager.set_schedule_hold(False)
        if hasattr(self, "tray"):
            self.tray.setVisible(
                self.cfg.minimize_to_tray or self.cfg.close_to_tray)

    # ---- selection ------------------------------------------------------
    def _on_card_clicked(self, iid, ctrl, shift):
        """Drive multi-select: plain click selects one; Ctrl toggles; Shift
        extends a contiguous range over the currently visible cards."""
        visible = [c.item.id for c in self._ordered_cards() if c.isVisible()]
        if shift and self._anchor_id in visible and iid in visible:
            a, b = visible.index(self._anchor_id), visible.index(iid)
            lo, hi = (a, b) if a <= b else (b, a)
            self._selected_ids = set(visible[lo:hi + 1])
        elif ctrl:
            self._selected_ids.symmetric_difference_update({iid})
            self._anchor_id = iid
        else:
            self._selected_ids = {iid}
            self._anchor_id = iid
        self._sync_selection()

    def _ordered_cards(self):
        cards = []
        for i in range(self.list_layout.count()):
            w = self.list_layout.itemAt(i).widget()
            if isinstance(w, DownloadCard):
                cards.append(w)
        return cards

    def _sync_selection(self):
        for iid, card in self._cards.items():
            card.set_selected(iid in self._selected_ids)
        self._update_selbar()

    def _clear_selection(self):
        self._selected_ids.clear()
        self._anchor_id = None
        self._sync_selection()

    def _select_all_visible(self):
        self._selected_ids = {c.item.id for c in self._cards.values()
                              if c.isVisible()}
        self._sync_selection()

    def _update_selbar(self):
        n = len(self._selected_ids)
        self.sel_bar.setVisible(n > 0)
        if n:
            self.sel_label.setText(f"{n} selected")

    def _select_all(self):
        self._select_all_visible()

    def _selected_or_empty(self):
        return [i for i in self._selected_ids if i in self._cards]

    def _resume_selected(self):
        for iid in self._selected_or_empty():
            self.manager.start(iid)

    def _pause_selected(self):
        for iid in self._selected_or_empty():
            self.manager.pause(iid)

    def _stop_selected(self):
        for iid in self._selected_or_empty():
            self.manager.stop(iid)

    # ---- removal --------------------------------------------------------
    def _remove(self, iid):
        item = self.manager.items.get(iid)
        name = (item.display_name if item else iid) or iid
        if self.cfg.confirm_remove and QMessageBox.question(
                self, "Remove",
                f"Remove “{name}” from the list?") != QMessageBox.Yes:
            return
        self._remove_ids([iid])

    def _remove_selected(self):
        ids = self._selected_or_empty()
        if not ids:
            return
        if self.cfg.confirm_remove and QMessageBox.question(
                self, "Remove",
                f"Remove {len(ids)} download(s) from the list?") != QMessageBox.Yes:
            return
        self._remove_ids(ids)

    def _remove_ids(self, ids):
        for iid in ids:
            self.manager.remove(iid)
            card = self._cards.pop(iid, None)
            if card is not None:
                self.list_layout.removeWidget(card)
                card.deleteLater()
            self._selected_ids.discard(iid)
        self._sync_selection()
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
            self.status_label.setText("Link copied to clipboard")

    def _rename(self, iid):
        """Prompt for a new file name and rename the download on disk + in state."""
        from PySide6.QtWidgets import QInputDialog
        item = self.manager.items.get(iid)
        if item is None:
            return
        current = item.filename or item.display_name or ""
        new_name, ok = QInputDialog.getText(
            self, "Rename download", "New file name:", text=current)
        if not ok:
            return
        ok, msg = self.manager.rename(iid, new_name.strip())
        if not ok:
            if msg:
                QMessageBox.warning(self, "Rename", msg)
            return
        card = self._cards.get(iid)
        if card is not None:
            card.update_item(item)
        self.status_label.setText(f"Renamed to {item.filename}")

    def _rename_selected(self):
        """F2 / Edit ▸ Rename: rename the single selected download."""
        ids = self._selected_or_empty()
        if len(ids) != 1:
            self.status_label.setText(
                "Select exactly one download to rename")
            return
        self._rename(ids[0])

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

    # ---- system tray ----------------------------------------------------
    def _build_tray(self):
        """A tray icon so the app can keep downloading while out of the way."""
        from PySide6.QtGui import QAction, QIcon
        from PySide6.QtWidgets import QSystemTrayIcon, QMenu

        self._force_quit = False
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.windowIcon() or QIcon())
        self.tray.setToolTip("Superfast Download Manager")

        menu = QMenu()
        show_act = QAction("Show / Hide", self)
        show_act.triggered.connect(self._toggle_window)
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self._quit_from_tray)
        menu.addAction(show_act)
        menu.addSeparator()
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setVisible(self.cfg.minimize_to_tray or self.cfg.close_to_tray)

    def _on_tray_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.Trigger:      # left-click
            self._toggle_window()

    def _toggle_window(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _quit_from_tray(self):
        self._force_quit = True
        self.close()

    def changeEvent(self, event):
        from PySide6.QtCore import QEvent
        if (event.type() == QEvent.WindowStateChange
                and self.cfg.minimize_to_tray and self.isMinimized()):
            # Defer the hide so the minimize animation doesn't fight it.
            QTimer.singleShot(0, self.hide)
            if hasattr(self, "tray"):
                self.tray.setVisible(True)
        super().changeEvent(event)

    def closeEvent(self, event):
        # Close-to-tray keeps downloads running until the user quits explicitly.
        if (getattr(self, "cfg", None) and self.cfg.close_to_tray
                and not getattr(self, "_force_quit", False)
                and hasattr(self, "tray")):
            event.ignore()
            self.hide()
            self.tray.setVisible(True)
            self.tray.showMessage(
                "Still downloading",
                "Superfast Download Manager is running in the tray.",
                msecs=3000)
            return
        self.manager.shutdown()
        self.store.close()
        if hasattr(self, "tray"):
            self.tray.hide()
        super().closeEvent(event)
