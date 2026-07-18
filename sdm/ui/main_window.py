"""Main application window."""
from __future__ import annotations

import os
import webbrowser

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QProgressBar, QToolBar, QLabel, QComboBox,
    QSpinBox, QFileDialog, QMessageBox, QMenu, QHeaderView, QStatusBar,
)

from ..core.config import Config, DB_PATH
from ..core.manager import DownloadManager, guess_kind
from ..core.models import DownloadItem, Status, Kind
from ..core.store import Store
from .util import fmt_bytes, fmt_speed, fmt_eta, DARK_QSS


class ProgressBridge(QObject):
    """Marshals engine progress callbacks (worker threads) onto the Qt thread."""
    progressed = Signal(object)


COLS = ["Name", "Size", "Progress", "Speed", "ETA", "Priority", "Category",
        "Conns", "Status"]


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

        self._row_by_id: dict[str, int] = {}

        self.setWindowTitle("Superfast Download Manager")
        self.resize(1040, 620)
        self.setStyleSheet(DARK_QSS)

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

        self.manager.load_persisted()
        for item in self.manager.items.values():
            self._ensure_row(item)
            self._refresh_row(item)

        # periodic status bar refresh
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._update_statusbar)
        self._ticker.start(1000)

    # ---- UI construction -----------------------------------------------
    def _build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "Paste a URL (direct file or YouTube/video link) and press Add")
        self.url_input.returnPressed.connect(self._add_from_input)
        tb.addWidget(self.url_input)

        add_btn = QPushButton("Add")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_from_input)
        tb.addWidget(add_btn)

        fetch_btn = QPushButton("Add with options…")
        fetch_btn.clicked.connect(self._open_add_dialog)
        tb.addWidget(fetch_btn)

        paste_btn = QPushButton("Paste + Add")
        paste_btn.clicked.connect(self._paste_and_add)
        tb.addWidget(paste_btn)

    def _build_body(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 6, 10, 6)

        # control row
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Save to:"))
        self.dir_label = QLineEdit(self.cfg.download_dir)
        self.dir_label.setReadOnly(True)
        controls.addWidget(self.dir_label, 1)
        browse = QPushButton("Change…")
        browse.clicked.connect(self._choose_dir)
        controls.addWidget(browse)

        controls.addSpacing(16)
        controls.addWidget(QLabel("Connections:"))
        self.conn_spin = QSpinBox()
        self.conn_spin.setRange(1, 32)
        self.conn_spin.setValue(self.cfg.connections_per_download)
        self.conn_spin.valueChanged.connect(self._on_conn_changed)
        controls.addWidget(self.conn_spin)

        controls.addWidget(QLabel("Max parallel:"))
        self.par_spin = QSpinBox()
        self.par_spin.setRange(1, 10)
        self.par_spin.setValue(self.cfg.max_concurrent)
        self.par_spin.valueChanged.connect(self._on_parallel_changed)
        controls.addWidget(self.par_spin)
        layout.addLayout(controls)

        # table
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_menu)
        self.table.doubleClicked.connect(lambda _i: self._open_selected_file())
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        # action row
        actions = QHBoxLayout()
        for label, slot in [
            ("Resume", self._resume_selected), ("Pause", self._pause_selected),
            ("Cancel", self._cancel_selected), ("Remove", self._remove_selected),
            ("Open folder", self._open_selected_folder),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.setCentralWidget(central)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel("Ready")
        sb.addWidget(self.status_label)

    # PLACEHOLDER_BUILD

    # ---- actions --------------------------------------------------------
    def _add_from_input(self):
        url = self.url_input.text().strip()
        if not url:
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.warning(self, "Invalid URL",
                                "Please enter a valid http(s) URL.")
            return
        self.manager.add(url, connections=self.conn_spin.value())
        self.url_input.clear()

    def _paste_and_add(self):
        cb = QGuiApplication.clipboard()
        text = cb.text().strip()
        if text:
            self.url_input.setText(text)
            self._add_from_input()

    def _open_add_dialog(self, initial_url: str = ""):
        from .add_dialog import AddDialog
        url = initial_url or self.url_input.text().strip()
        dlg = AddDialog(self, self.cfg.download_dir,
                        self.cfg.connections_per_download, initial_url=url)
        if dlg.exec() and dlg.result_item is not None:
            self.manager.add(item=dlg.result_item)
            self.url_input.clear()

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose download folder",
                                             self.cfg.download_dir)
        if d:
            self.cfg.download_dir = d
            self.manager.default_dir = d
            self.dir_label.setText(d)
            self.cfg.save()

    def _on_conn_changed(self, v):
        self.cfg.connections_per_download = v
        self.manager.default_connections = v
        self.cfg.save()

    def _on_parallel_changed(self, v):
        self.cfg.max_concurrent = v
        self.manager.set_max_concurrent(v)
        self.cfg.save()

    def _selected_ids(self) -> list[str]:
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), 0)
            if item:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _resume_selected(self):
        for i in self._selected_ids():
            self.manager.start(i)

    def _pause_selected(self):
        for i in self._selected_ids():
            self.manager.pause(i)

    def _cancel_selected(self):
        for i in self._selected_ids():
            self.manager.cancel(i)

    def _remove_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, "Remove",
                                f"Remove {len(ids)} download(s) from the list?") \
                != QMessageBox.Yes:
            return
        for i in ids:
            self.manager.remove(i)
            row = self._row_by_id.pop(i, None)
            if row is not None:
                self.table.removeRow(row)
                self._reindex_rows()

    def _open_selected_file(self):
        for i in self._selected_ids():
            item = self.manager.items.get(i)
            if item and item.status == Status.COMPLETED and os.path.exists(item.filepath):
                os.startfile(item.filepath)  # noqa: S606 - Windows open
            break

    def _open_selected_folder(self):
        for i in self._selected_ids():
            item = self.manager.items.get(i)
            if item and os.path.isdir(item.save_dir):
                os.startfile(item.save_dir)  # noqa: S606
            break

    def _show_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Resume", self._resume_selected)
        menu.addAction("Pause", self._pause_selected)
        menu.addAction("Cancel", self._cancel_selected)
        menu.addSeparator()
        from ..core.models import Priority
        pr_menu = menu.addMenu("Set priority")
        for p in Priority:
            pr_menu.addAction(p.value.capitalize(),
                              lambda checked=False, pr=p: self._set_priority(pr))
        menu.addSeparator()
        menu.addAction("Open file", self._open_selected_file)
        menu.addAction("Open folder", self._open_selected_folder)
        menu.addAction("Copy URL", self._copy_url)
        menu.addSeparator()
        menu.addAction("Remove", self._remove_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_url(self):
        for i in self._selected_ids():
            item = self.manager.items.get(i)
            if item:
                QGuiApplication.clipboard().setText(item.url)
            break

    def _set_priority(self, priority):
        for i in self._selected_ids():
            self.manager.set_priority(i, priority)
            item = self.manager.items.get(i)
            if item:
                self._refresh_row(item)

    # PLACEHOLDER_ACTIONS

    # ---- table rendering ------------------------------------------------
    def _ensure_row(self, item: DownloadItem) -> int:
        if item.id in self._row_by_id:
            return self._row_by_id[item.id]
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem()
        name.setData(Qt.UserRole, item.id)
        self.table.setItem(row, 0, name)
        for c in range(1, len(COLS)):
            if COLS[c] == "Progress":
                bar = QProgressBar()
                bar.setRange(0, 1000)
                self.table.setCellWidget(row, c, bar)
            else:
                self.table.setItem(row, c, QTableWidgetItem(""))
        self._row_by_id[item.id] = row
        return row

    def _on_item_update(self, item: DownloadItem):
        self.manager.items[item.id] = item
        self._ensure_row(item)
        self._refresh_row(item)

    def _refresh_row(self, item: DownloadItem):
        row = self._row_by_id.get(item.id)
        if row is None:
            return
        display = item.title or item.filename or item.url
        name_item = self.table.item(row, 0)
        name_item.setText(display)
        name_item.setToolTip(item.url)

        self.table.item(row, 1).setText(fmt_bytes(item.total_bytes))
        bar = self.table.cellWidget(row, 2)
        if bar:
            bar.setValue(int(item.progress * 1000))
            bar.setFormat(f"{item.progress * 100:.1f}%")
        self.table.item(row, 3).setText(fmt_speed(item.speed))
        self.table.item(row, 4).setText(fmt_eta(item.eta))
        from PySide6.QtGui import QColor
        pr = self.table.item(row, 5)
        pr.setText(item.priority.value.capitalize())
        pr_colors = {"urgent": "#ef4444", "high": "#f59e0b",
                     "normal": "#e6e8ec", "low": "#9aa0aa"}
        pr.setForeground(QColor(pr_colors.get(item.priority.value, "#e6e8ec")))
        self.table.item(row, 6).setText(item.category or "—")
        self.table.item(row, 7).setText(str(item.connections))
        status = self.table.item(row, 8)
        status.setText(item.status.value)
        colors = {
            Status.COMPLETED: "#22c55e", Status.ERROR: "#ef4444",
            Status.DOWNLOADING: "#3b82f6", Status.PAUSED: "#eab308",
            Status.CANCELLED: "#9aa0aa",
        }
        status.setForeground(QColor(colors.get(item.status, "#e6e8ec")))
        if item.status == Status.ERROR and item.error:
            status.setToolTip(item.error)

    def _reindex_rows(self):
        self._row_by_id.clear()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                self._row_by_id[item.data(Qt.UserRole)] = row

    def _update_statusbar(self):
        items = self.manager.items.values()
        active = [i for i in items if i.status == Status.DOWNLOADING]
        total_speed = sum(i.speed for i in active)
        done = sum(1 for i in items if i.status == Status.COMPLETED)
        self.status_label.setText(
            f"{len(active)} active · {len(list(items))} total · "
            f"{done} completed · {fmt_speed(total_speed)}")

    def closeEvent(self, event):
        self.manager.shutdown()
        self.store.close()
        super().closeEvent(event)
