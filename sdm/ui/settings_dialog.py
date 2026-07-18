"""Engine settings dialog: folder, concurrency, speed cap, clipboard, schedule.

Consolidates what used to live in the toolbar. Reads/writes the Config and
signals the main window so live components (manager, clipboard, scheduler)
can be reconfigured immediately.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, QTime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QCheckBox, QTimeEdit, QFileDialog, QGroupBox,
)

from ..core.config import Config


def _qtime(hhmm: str) -> QTime:
    try:
        h, m = hhmm.split(":")
        return QTime(int(h), int(m))
    except (ValueError, AttributeError):
        return QTime(0, 0)


class SettingsDialog(QDialog):
    changed = Signal()

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Engine Settings")
        self.setMinimumWidth(440)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        # Downloads group
        dl = QGroupBox("Downloads")
        form = QFormLayout(dl)
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(self.cfg.download_dir)
        self.dir_edit.setReadOnly(True)
        browse = QPushButton("Change…")
        browse.clicked.connect(self._choose_dir)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)
        form.addRow("Save to:", dir_row)

        self.conn_spin = QSpinBox()
        self.conn_spin.setRange(1, 32)
        self.conn_spin.setValue(self.cfg.connections_per_download)
        form.addRow("Connections / download:", self.conn_spin)

        self.par_spin = QSpinBox()
        self.par_spin.setRange(1, 10)
        self.par_spin.setValue(self.cfg.max_concurrent)
        form.addRow("Max parallel:", self.par_spin)

        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(0, 1_000_000)
        self.speed_spin.setSingleStep(128)
        self.speed_spin.setValue(self.cfg.speed_limit_kb)
        self.speed_spin.setSpecialValueText("Unlimited")
        form.addRow("Speed limit (KB/s):", self.speed_spin)
        root.addWidget(dl)

        # Clipboard group
        clip = QGroupBox("Clipboard")
        clip_l = QVBoxLayout(clip)
        self.clip_check = QCheckBox("Monitor clipboard for download links")
        self.clip_check.setChecked(self.cfg.clipboard_watch)
        self.clip_auto = QCheckBox("Add automatically without prompting")
        self.clip_auto.setChecked(self.cfg.clipboard_auto_add)
        clip_l.addWidget(self.clip_check)
        clip_l.addWidget(self.clip_auto)
        root.addWidget(clip)

        # Schedule group
        sch = QGroupBox("Schedule")
        sch_l = QVBoxLayout(sch)
        self.sched_check = QCheckBox("Only download within a time window")
        self.sched_check.setChecked(self.cfg.schedule_enabled)
        sch_l.addWidget(self.sched_check)
        win = QHBoxLayout()
        self.sched_start = QTimeEdit(_qtime(self.cfg.schedule_start))
        self.sched_start.setDisplayFormat("HH:mm")
        self.sched_stop = QTimeEdit(_qtime(self.cfg.schedule_stop))
        self.sched_stop.setDisplayFormat("HH:mm")
        win.addWidget(QLabel("From"))
        win.addWidget(self.sched_start)
        win.addWidget(QLabel("to"))
        win.addWidget(self.sched_stop)
        win.addStretch(1)
        sch_l.addLayout(win)
        root.addWidget(sch)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Apply")
        save.setObjectName("primary")
        save.clicked.connect(self._apply)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Choose download folder", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _apply(self):
        self.cfg.download_dir = self.dir_edit.text()
        self.cfg.connections_per_download = self.conn_spin.value()
        self.cfg.max_concurrent = self.par_spin.value()
        self.cfg.speed_limit_kb = self.speed_spin.value()
        self.cfg.clipboard_watch = self.clip_check.isChecked()
        self.cfg.clipboard_auto_add = self.clip_auto.isChecked()
        self.cfg.schedule_enabled = self.sched_check.isChecked()
        self.cfg.schedule_start = self.sched_start.time().toString("HH:mm")
        self.cfg.schedule_stop = self.sched_stop.time().toString("HH:mm")
        self.cfg.save()
        self.changed.emit()
        self.accept()
