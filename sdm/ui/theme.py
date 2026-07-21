"""Theme palettes + stylesheet builder for light/dark switching.

Brand and semantic colors (purple->pink gradient, emerald/amber/red status)
are theme-independent and live in util. Only the neutral surfaces (background,
card, sidebar, border, text) change between themes; this module holds those and
assembles the full application stylesheet from them.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

# Brand gradient stops, reused across widgets.
GRAD = "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #a874ff, stop:1 #f65fa6)"

DARK = {
    "bg": "#131118",
    "sidebar": "#181620",
    "card": "#1c1b23",
    "input": "#201e29",
    "hover": "#232030",
    "border": "#2a2833",
    "border_hi": "#2f2c3b",
    "fg": "#f4f3f7",
    "fg_soft": "#c8c5d4",
    "muted": "#9b98a8",
    "scroll": "#2f2c3b",
    "scroll_hi": "#3a3648",
    "disabled": "#5b586b",
}

LIGHT = {
    "bg": "#f6f5fa",
    "sidebar": "#ffffff",
    "card": "#ffffff",
    "input": "#f1eff7",
    "hover": "#ece9f5",
    "border": "#e3e0ee",
    "border_hi": "#d6d2e6",
    "fg": "#1c1b23",
    "fg_soft": "#4a4759",
    "muted": "#6f6b80",
    "scroll": "#d6d2e6",
    "scroll_hi": "#c2bcd8",
    "disabled": "#b4b0c2",
}

THEMES = {"dark": DARK, "light": LIGHT}

# _choice is the user's selection ("dark" / "light" / "system"); _resolved is
# the palette actually applied ("dark" or "light").
_choice = "dark"
_resolved = "dark"


def detect_system() -> str:
    """Best-effort OS color-scheme detection; defaults to dark."""
    app = QApplication.instance()
    if app is not None:
        try:
            hints = app.styleHints()
            scheme = hints.colorScheme()
            from PySide6.QtCore import Qt
            if scheme == Qt.ColorScheme.Light:
                return "light"
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
        except (AttributeError, TypeError):
            pass
    return "dark"


def resolve(name: str) -> str:
    if name == "system":
        return detect_system()
    return name if name in THEMES else "dark"


def current_theme() -> str:
    """The user's selection (may be 'system')."""
    return _choice


def resolved_theme() -> str:
    """The palette actually applied ('dark' or 'light')."""
    return _resolved


def palette(name: str | None = None) -> dict:
    return THEMES.get(resolve(name) if name else _resolved, DARK)


def build_qss(name: str) -> str:
    p = palette(name)
    return _QSS_TEMPLATE.format(g=GRAD, **p)


def apply_theme(app: QApplication, name: str):
    """Set the process-wide theme and refresh the application stylesheet.

    ``name`` may be 'dark', 'light', or 'system'. The user's choice is
    remembered as-is (so it round-trips to config), while the resolved
    light/dark palette is what gets painted.
    """
    global _choice, _resolved
    _choice = name if name in ("dark", "light", "system") else "dark"
    _resolved = resolve(_choice)
    app.setStyleSheet(build_qss(_resolved))


_QSS_TEMPLATE = """
* {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }}
QWidget {{ background: {bg}; color: {fg}; }}
QMainWindow, QDialog {{ background: {bg}; }}

/* Sidebar */
#sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
#brandTitle {{ font-size: 17px; font-weight: 800; }}
#brandSub {{ color: {muted}; font-size: 9px; letter-spacing: 1px; }}
#navGroupLabel {{ color: {muted}; font-size: 10px; font-weight: 700; }}
QPushButton#navItem {{
    background: transparent; border: none; border-radius: 9px;
    padding: 9px 12px; text-align: left; color: {fg}; font-weight: 500;
}}
QPushButton#navItem:hover {{ background: {hover}; }}
QPushButton#navItem:checked {{ background: {g}; color: white; font-weight: 700; }}

/* Top bar */
#topbar {{ background: {sidebar}; border-bottom: 1px solid {border}; }}

/* Selection action bar */
#selBar {{
    background: rgba(168, 116, 255, 0.10);
    border: 1px solid #a874ff; border-radius: 10px;
}}

QLineEdit, QComboBox, QSpinBox, QTimeEdit {{
    background: {input}; border: 1px solid {border}; border-radius: 9px;
    padding: 8px 11px; selection-background-color: #a874ff; color: {fg};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {{
    border: 1px solid #a874ff;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {card}; border: 1px solid {border};
    selection-background-color: #a874ff; selection-color: white;
}}

QPushButton {{
    background: {hover}; border: 1px solid {border_hi}; border-radius: 9px;
    padding: 8px 14px; color: {fg};
}}
QPushButton:hover {{ background: {border}; }}
QPushButton:pressed {{ background: #a874ff; color: white; }}
QPushButton#primary {{ background: {g}; border: none; font-weight: 700; color: white; }}
QPushButton#primary:hover {{ background: #b98cff; }}
QPushButton:disabled {{ color: {disabled}; background: {input}; }}

/* Stat cards */
#statCard {{ background: {card}; border: 1px solid {border}; border-radius: 14px; }}
#statTitle {{ color: {muted}; font-size: 10px; font-weight: 700; }}
#statValue {{ font-size: 22px; font-weight: 800; }}
#statSub {{ color: {muted}; font-size: 11px; }}

/* Download cards */
#downloadCard {{ background: {card}; border: 1px solid {border}; border-radius: 14px; }}
#downloadCard[running="true"] {{ border: 1px solid #a874ff; }}
#downloadCard[error="true"] {{ border: 1px solid #f87171; }}
#downloadCard[selected="true"] {{
    border: 1px solid #a874ff; background: rgba(168, 116, 255, 0.10);
}}
#cardTitle {{ font-size: 14px; font-weight: 600; }}
#thumb {{ background: {input}; border: 1px solid {border}; border-radius: 10px; }}
#badge {{
    background: {input}; border: 1px solid {border_hi}; border-radius: 6px;
    padding: 1px 6px; color: {fg_soft}; font-size: 10px;
}}
#meta {{ color: {muted}; font-size: 11px; }}

/* Add-dialog: output-type toggle + quality rows */
QPushButton#typeToggle {{
    background: {input}; border: 1px solid {border_hi}; border-radius: 10px;
    padding: 9px 14px; color: {fg_soft}; font-weight: 600;
}}
QPushButton#typeToggle:hover {{ background: {hover}; }}
QPushButton#typeToggle:checked {{
    background: rgba(168, 116, 255, 0.16); border: 1px solid #a874ff; color: {fg};
}}
#fmtRow[selected="true"] {{ border: 1px solid #a874ff; background: rgba(168, 116, 255, 0.10); }}
#fmtRow {{
    background: {card}; border: 1px solid {border}; border-radius: 10px;
}}
#fmtRow:hover {{ border: 1px solid {border_hi}; }}

QProgressBar {{
    background: {input}; border: none; border-radius: 5px; height: 8px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {g}; border-radius: 5px; }}

QStatusBar {{ background: {sidebar}; color: {muted}; }}
QMenu {{ background: {card}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: #a874ff; color: white; }}
QCheckBox {{ color: {fg_soft}; }}
QGroupBox {{
    border: 1px solid {border}; border-radius: 10px; margin-top: 10px;
    padding-top: 8px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {muted}; }}
QToolTip {{ background: {card}; color: {fg}; border: 1px solid {border}; }}
QLabel {{ background: transparent; }}

/* Tabs (settings dialog) */
QTabWidget::pane {{
    border: 1px solid {border}; border-radius: 10px; top: -1px;
    background: {card};
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: {input}; color: {muted}; border: 1px solid {border};
    border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px;
    padding: 8px 16px; margin-right: 2px;
}}
QTabBar::tab:hover {{ background: {hover}; color: {fg}; }}
QTabBar::tab:selected {{ background: {card}; color: {fg}; font-weight: 600; }}
QTabBar::tab:!selected {{ margin-top: 2px; }}

/* Log panel */
#logPanel {{ background: {sidebar}; border-top: 1px solid {border}; }}
#logHeader {{ background: {sidebar}; }}
#logHeader:hover {{ background: {hover}; }}
#logBadge {{
    background: #ef4444; color: white; border-radius: 8px;
    font-size: 10px; font-weight: 700; padding: 0 2px;
}}
#logList {{ background: {bg}; border: none; }}
#logList::item {{ border-bottom: 1px solid {border}; }}
QPushButton#logBtn {{
    background: {input}; border: 1px solid {border_hi}; border-radius: 6px;
    padding: 3px 12px; color: {fg}; font-size: 11px;
}}
QPushButton#logBtn:hover {{ background: {hover}; border: 1px solid #a874ff; }}
QPushButton#logBtn:pressed {{ background: #a874ff; color: white; }}

#scrollArea {{ border: none; background: {bg}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {scroll}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {scroll_hi}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""
