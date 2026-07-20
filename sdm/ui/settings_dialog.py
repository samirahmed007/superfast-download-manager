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
    QComboBox, QTabWidget, QWidget,
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
    theme_changed = Signal(str)   # emitted live when the theme selection changes

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

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # ---- Downloads tab ----
        dl_tab = QWidget()
        dl_root = QVBoxLayout(dl_tab)
        dl_root.setSpacing(12)
        tabs.addTab(dl_tab, "Downloads")

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
        dl_root.addWidget(dl)

        # Defaults for new downloads
        defg = QGroupBox("Defaults for new downloads")
        defform = QFormLayout(defg)

        self.priority_combo = QComboBox()
        for label, val in (("Urgent", "urgent"), ("High", "high"),
                           ("Normal", "normal"), ("Low", "low")):
            self.priority_combo.addItem(label, val)
        pidx = self.priority_combo.findData(self.cfg.default_priority)
        self.priority_combo.setCurrentIndex(pidx if pidx >= 0 else 2)
        defform.addRow("Default priority:", self.priority_combo)

        self.ext_combo = QComboBox()
        for label, val in (("MP4 (most compatible)", "mp4"), ("WebM", "webm"),
                           ("MKV (Matroska)", "mkv"), ("MP3 (audio only)", "mp3")):
            self.ext_combo.addItem(label, val)
        eidx = self.ext_combo.findData(self.cfg.default_ext)
        self.ext_combo.setCurrentIndex(eidx if eidx >= 0 else 0)
        defform.addRow("Default video format:", self.ext_combo)

        self.audio_ext_combo = QComboBox()
        for label, val in (("MP3", "mp3"), ("M4A (AAC)", "m4a"),
                           ("Opus", "opus"), ("WAV (lossless)", "wav")):
            self.audio_ext_combo.addItem(label, val)
        aidx = self.audio_ext_combo.findData(self.cfg.default_audio_ext)
        self.audio_ext_combo.setCurrentIndex(aidx if aidx >= 0 else 0)
        defform.addRow("Audio-only format:", self.audio_ext_combo)

        self.res_combo = QComboBox()
        for label, val in (("Best available", "best"), ("2160p (4K)", "2160"),
                           ("1440p (2K)", "1440"), ("1080p", "1080"),
                           ("720p", "720"), ("480p", "480")):
            self.res_combo.addItem(label, val)
        ridx = self.res_combo.findData(self.cfg.default_resolution)
        self.res_combo.setCurrentIndex(ridx if ridx >= 0 else 0)
        defform.addRow("Default resolution:", self.res_combo)

        self.autostart_check = QCheckBox("Start downloads immediately when added")
        self.autostart_check.setChecked(self.cfg.auto_start)
        defform.addRow("", self.autostart_check)
        dl_root.addWidget(defg)
        dl_root.addStretch(1)

        # ---- Automation tab ----
        auto_tab = QWidget()
        auto_root = QVBoxLayout(auto_tab)
        auto_root.setSpacing(12)
        tabs.addTab(auto_tab, "Automation")

        # Clipboard group
        clip = QGroupBox("Clipboard")
        clip_l = QVBoxLayout(clip)
        self.clip_check = QCheckBox("Monitor clipboard for download links")
        self.clip_check.setChecked(self.cfg.clipboard_watch)
        self.clip_auto = QCheckBox("Add automatically without prompting")
        self.clip_auto.setChecked(self.cfg.clipboard_auto_add)
        clip_l.addWidget(self.clip_check)
        clip_l.addWidget(self.clip_auto)
        auto_root.addWidget(clip)

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
        auto_root.addWidget(sch)
        auto_root.addStretch(1)

        # ---- General tab ----
        gen_tab = QWidget()
        gen_root = QVBoxLayout(gen_tab)
        gen_root.setSpacing(12)
        tabs.addTab(gen_tab, "General")

        # Appearance group
        appg = QGroupBox("Appearance")
        appform = QFormLayout(appg)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Follow system", "system")
        idx = self.theme_combo.findData(self.cfg.theme)
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        # Live preview: switching the dropdown restyles the app immediately.
        self.theme_combo.currentIndexChanged.connect(
            lambda _i: self.theme_changed.emit(self.theme_combo.currentData()))
        appform.addRow("Theme:", self.theme_combo)
        gen_root.addWidget(appg)

        # Behavior group
        behg = QGroupBox("Behavior")
        beh_l = QVBoxLayout(behg)
        self.confirm_remove_check = QCheckBox(
            "Ask for confirmation before removing downloads")
        self.confirm_remove_check.setChecked(self.cfg.confirm_remove)
        beh_l.addWidget(self.confirm_remove_check)
        gen_root.addWidget(behg)
        gen_root.addStretch(1)

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
        self.cfg.default_priority = self.priority_combo.currentData()
        self.cfg.default_ext = self.ext_combo.currentData()
        self.cfg.default_audio_ext = self.audio_ext_combo.currentData()
        self.cfg.default_resolution = self.res_combo.currentData()
        self.cfg.auto_start = self.autostart_check.isChecked()
        self.cfg.confirm_remove = self.confirm_remove_check.isChecked()
        self.cfg.clipboard_watch = self.clip_check.isChecked()
        self.cfg.clipboard_auto_add = self.clip_auto.isChecked()
        self.cfg.schedule_enabled = self.sched_check.isChecked()
        self.cfg.schedule_start = self.sched_start.time().toString("HH:mm")
        self.cfg.schedule_stop = self.sched_stop.time().toString("HH:mm")
        self.cfg.theme = self.theme_combo.currentData()
        self.cfg.save()
        self.changed.emit()
        self.accept()
