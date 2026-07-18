"""UI helpers: human-readable formatting, color tokens, and the app theme.

The palette mirrors the TurboGrab web app: a dark neutral base with a
purple->pink brand gradient, emerald for success, amber/red for warnings.
"""
from __future__ import annotations

import time as _time


def fmt_bytes(n: float) -> str:
    if n is None or n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    n = float(n)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.1f} {units[i]}" if i else f"{int(n)} {units[i]}"


def fmt_speed(bps: float) -> str:
    if not bps or bps <= 0:
        return "—"
    return fmt_bytes(bps) + "/s"


def fmt_eta(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def fmt_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_relative(ts: float) -> str:
    if not ts:
        return ""
    delta = _time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


# ---- color tokens (hex approximations of the web app's oklch palette) ------
PRIMARY = "#a874ff"        # vivid purple
PRIMARY_DIM = "#8b5cf6"
ACCENT = "#f65fa6"         # vivid pink
EMERALD = "#34d399"
AMBER = "#fbbf24"
RED = "#f87171"
FG = "#f4f3f7"
MUTED = "#9b98a8"
CARD = "#1c1b23"
BG = "#131118"
SIDEBAR = "#181620"
BORDER = "#2a2833"


def status_color(status: str) -> str:
    return {
        "completed": EMERALD,
        "downloading": PRIMARY,
        "connecting": PRIMARY,
        "queued": MUTED,
        "paused": AMBER,
        "error": RED,
        "cancelled": MUTED,
    }.get(status, MUTED)


def priority_color(priority: str) -> str:
    return {
        "urgent": ACCENT,
        "high": PRIMARY,
        "normal": MUTED,
        "low": "#71717a",
    }.get(priority, MUTED)


# Stable per-name category color, matching the web app's hashing approach.
_CAT_PALETTE = [
    "#a874ff", "#f65fa6", "#34d399", "#fbbf24", "#60a5fa",
    "#f87171", "#c084fc", "#2dd4bf", "#fb923c", "#4ade80",
]


def category_color(name: str) -> str:
    if not name:
        return MUTED
    h = sum(ord(c) for c in name)
    return _CAT_PALETTE[h % len(_CAT_PALETTE)]


DARK_QSS = """
* { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
QWidget { background: #131118; color: #f4f3f7; }
QMainWindow, QDialog { background: #131118; }

/* Sidebar */
#sidebar { background: #181620; border-right: 1px solid #2a2833; }
#brandTitle { font-size: 17px; font-weight: 800; }
#brandSub { color: #9b98a8; font-size: 9px; letter-spacing: 1px; }
#navGroupLabel { color: #9b98a8; font-size: 10px; font-weight: 700; }
QPushButton#navItem {
    background: transparent; border: none; border-radius: 9px;
    padding: 9px 12px; text-align: left; color: #c8c5d4;
}
QPushButton#navItem:hover { background: #232030; }
QPushButton#navItem:checked {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #a874ff, stop:1 #f65fa6);
    color: white; font-weight: 600;
}

/* Top bar */
#topbar { background: #181620; border-bottom: 1px solid #2a2833; }

QLineEdit, QComboBox, QSpinBox, QTimeEdit {
    background: #201e29; border: 1px solid #2a2833; border-radius: 9px;
    padding: 8px 11px; selection-background-color: #a874ff;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {
    border: 1px solid #a874ff;
}
QComboBox::drop-down { border: none; width: 22px; }

QPushButton {
    background: #232030; border: 1px solid #2f2c3b; border-radius: 9px;
    padding: 8px 14px; color: #f4f3f7;
}
QPushButton:hover { background: #2c2939; }
QPushButton:pressed { background: #a874ff; }
QPushButton#primary {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #a874ff, stop:1 #f65fa6);
    border: none; font-weight: 700; color: white;
}
QPushButton#primary:hover { background: #b98cff; }
QPushButton:disabled { color: #5b586b; background: #201e29; }

/* Stat cards */
#statCard { background: #1c1b23; border: 1px solid #2a2833; border-radius: 14px; }
#statTitle { color: #9b98a8; font-size: 10px; font-weight: 700; }
#statValue { font-size: 22px; font-weight: 800; }
#statSub { color: #9b98a8; font-size: 11px; }

/* Download cards */
#downloadCard { background: #1c1b23; border: 1px solid #2a2833; border-radius: 14px; }
#downloadCard[running="true"] { border: 1px solid #a874ff; }
#downloadCard[error="true"] { border: 1px solid #f87171; }
#cardTitle { font-size: 14px; font-weight: 600; }
#thumb { background: #232030; border: 1px solid #2a2833; border-radius: 10px; }
#badge {
    background: #232030; border: 1px solid #2f2c3b; border-radius: 6px;
    padding: 1px 6px; color: #c8c5d4; font-size: 10px;
}
#meta { color: #9b98a8; font-size: 11px; }

QProgressBar {
    background: #201e29; border: none; border-radius: 5px; height: 8px;
    text-align: center; color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #a874ff, stop:1 #f65fa6);
    border-radius: 5px;
}

QStatusBar { background: #181620; color: #9b98a8; }
QMenu { background: #1c1b23; border: 1px solid #2a2833; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: #a874ff; color: white; }
QCheckBox { color: #c8c5d4; }
QToolTip { background: #1c1b23; color: #f4f3f7; border: 1px solid #2a2833; }

#scrollArea { border: none; background: #131118; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2f2c3b; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3a3648; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""
