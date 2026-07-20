"""Batch / playlist add dialog.

Two ways to queue many downloads at once:
  * paste a list of URLs (one per line), or
  * paste a single playlist/channel URL and expand it into its entries.

Shared options (priority, category, connections, save folder, output type)
apply to every item. Metadata for each item is probed lazily by the engine
when it starts, so this dialog stays responsive for large lists.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QObject, Signal, QThread
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QPlainTextEdit, QSpinBox, QFileDialog, QCheckBox,
)

from ..core.models import DownloadItem, Priority
from ..core.manager import guess_kind
from ..core.probe import probe_playlist

CATEGORIES = ["Auto", "Media", "Video", "Audio", "Software", "Documents",
              "Archives", "Images", "Other"]


class _PlaylistWorker(QObject):
    done = Signal(object, str)  # (entries, error)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            entries, err = probe_playlist(self.url)
        except Exception as e:  # noqa: BLE001
            entries, err = [], str(e)
        self.done.emit(entries, err)


class BatchDialog(QDialog):
    def __init__(self, parent, default_dir: str, default_connections: int, cfg=None):
        super().__init__(parent)
        self.setWindowTitle("Batch / Playlist Add")
        self.setMinimumWidth(620)
        self.result_items: list[DownloadItem] = []
        self._cfg = cfg
        self._thread: QThread | None = None

        root = QVBoxLayout(self)

        root.addWidget(QLabel(
            "Paste one URL per line, or a playlist URL and click Expand."))

        # URL list
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(
            "https://example.com/file1.zip\n"
            "https://example.com/file2.zip\n"
            "https://youtube.com/playlist?list=…")
        self.text.setMinimumHeight(180)
        root.addWidget(self.text, 1)

        # expand row
        exp_row = QHBoxLayout()
        self.expand_btn = QPushButton("Expand playlist")
        self.expand_btn.setToolTip(
            "Replace the first line's playlist/channel URL with its entries.")
        self.expand_btn.clicked.connect(self._expand)
        exp_row.addWidget(self.expand_btn)
        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet("color:#9aa0aa;")
        exp_row.addWidget(self.count_lbl)
        exp_row.addStretch(1)
        root.addLayout(exp_row)

        self.text.textChanged.connect(self._update_count)

        # shared options
        grid = QGridLayout()
        grid.addWidget(QLabel("Priority:"), 0, 0)
        self.priority = QComboBox()
        for p in Priority:
            self.priority.addItem(p.value.capitalize(), p)
        default_pri = getattr(cfg, "default_priority", "normal") if cfg else "normal"
        idx = next((i for i, p in enumerate(Priority) if p.value == default_pri), 2)
        self.priority.setCurrentIndex(idx)
        grid.addWidget(self.priority, 0, 1)

        grid.addWidget(QLabel("Category:"), 0, 2)
        self.category = QComboBox()
        self.category.addItems(CATEGORIES)
        grid.addWidget(self.category, 0, 3)

        grid.addWidget(QLabel("Connections:"), 1, 0)
        self.conn = QSpinBox()
        self.conn.setRange(1, 32)
        self.conn.setValue(default_connections)
        grid.addWidget(self.conn, 1, 1)

        self.audio_only = QCheckBox("Audio only (extract to audio file)")
        grid.addWidget(self.audio_only, 1, 2, 1, 2)
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
        self.add_btn = QPushButton("Add All")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(self.add_btn)
        root.addLayout(btns)

        self._update_count()

    # ---- helpers --------------------------------------------------------
    def _urls(self) -> list[str]:
        seen, out = set(), []
        for line in self.text.toPlainText().splitlines():
            u = line.strip()
            if u.startswith("http") and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _update_count(self):
        n = len(self._urls())
        self.count_lbl.setText(f"{n} URL{'s' if n != 1 else ''}")
        self.add_btn.setEnabled(n > 0)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose folder",
                                             self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    # ---- expand ---------------------------------------------------------
    def _expand(self):
        urls = self._urls()
        if not urls:
            return
        self.expand_btn.setEnabled(False)
        self.status_lbl.setText("Expanding playlist…")
        self._thread = QThread()
        self._worker = _PlaylistWorker(urls[0])
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_expanded)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_expanded(self, entries, error):
        self.expand_btn.setEnabled(True)
        if error:
            self.status_lbl.setText(f"⚠ {error[:90]}")
            return
        if not entries:
            self.status_lbl.setText("No entries found.")
            return
        # keep any lines the user added after the first, append expanded entries
        existing = self._urls()[1:]
        lines = [e.url for e in entries] + existing
        self.text.setPlainText("\n".join(lines))
        self.status_lbl.setText(f"Expanded to {len(entries)} item(s).")

    # ---- accept ---------------------------------------------------------
    def _accept(self):
        urls = self._urls()
        if not urls:
            return
        cat = self.category.currentText()
        audio = self.audio_only.isChecked()
        audio_ext = getattr(self._cfg, "default_audio_ext", "mp3") if self._cfg else "mp3"
        items = []
        for u in urls:
            item = DownloadItem(
                url=u,
                save_dir=self.dir_edit.text().strip(),
                connections=self.conn.value(),
                kind=guess_kind(u),
                priority=Priority(self.priority.currentData()),
                category="" if cat == "Auto" else cat,
                audio_only=audio,
            )
            if audio:
                item.ext = audio_ext
            items.append(item)
        self.result_items = items
        self.accept()
