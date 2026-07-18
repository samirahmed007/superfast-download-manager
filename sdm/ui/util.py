"""UI helpers: human-readable formatting + the dark stylesheet."""
from __future__ import annotations


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


DARK_QSS = """
* { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
QWidget { background: #16181d; color: #e6e8ec; }
QMainWindow, QDialog { background: #16181d; }

QToolBar { background: #1d2027; border: none; padding: 8px; spacing: 8px; }
QToolBar QLabel { color: #9aa0aa; }

QLineEdit, QComboBox, QSpinBox {
    background: #22262e; border: 1px solid #2f343d; border-radius: 8px;
    padding: 7px 10px; selection-background-color: #3b82f6;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #3b82f6; }

QPushButton {
    background: #2a2f38; border: 1px solid #333945; border-radius: 8px;
    padding: 7px 14px; color: #e6e8ec;
}
QPushButton:hover { background: #333945; }
QPushButton:pressed { background: #3b82f6; }
QPushButton#primary { background: #3b82f6; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #2f6fe0; }
QPushButton:disabled { color: #5b616b; background: #22262e; }

QTableWidget {
    background: #16181d; border: none; gridline-color: #23272f;
    selection-background-color: #23324a;
}
QHeaderView::section {
    background: #1d2027; color: #9aa0aa; border: none;
    border-bottom: 1px solid #2a2f38; padding: 8px; font-weight: 600;
}
QTableWidget::item { padding: 6px; border-bottom: 1px solid #1e2129; }

QProgressBar {
    background: #22262e; border: none; border-radius: 6px; height: 14px;
    text-align: center; color: #cdd2da; font-size: 11px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3b82f6, stop:1 #22c55e);
    border-radius: 6px;
}

QStatusBar { background: #1d2027; color: #9aa0aa; }
QMenu { background: #1d2027; border: 1px solid #2f343d; }
QMenu::item:selected { background: #23324a; }
QScrollBar:vertical { background: #16181d; width: 12px; }
QScrollBar::handle:vertical { background: #2f343d; border-radius: 6px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""
