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


# ---- brand + semantic color tokens (theme-independent) ---------------------
# These read well on both light and dark surfaces, so they don't change with
# the theme. Neutral surfaces (bg/card/border/text) live in theme.py.
PRIMARY = "#a874ff"        # vivid purple
PRIMARY_DIM = "#8b5cf6"
ACCENT = "#f65fa6"         # vivid pink
EMERALD = "#10b981"        # slightly deeper so it reads on light too
AMBER = "#d97706"
RED = "#ef4444"


def muted() -> str:
    """Current theme's muted text color (call at render time)."""
    from .theme import palette
    return palette()["muted"]


def status_color(status: str) -> str:
    m = muted()
    return {
        "completed": EMERALD,
        "downloading": PRIMARY,
        "connecting": PRIMARY,
        "queued": m,
        "paused": AMBER,
        "error": RED,
        "cancelled": m,
    }.get(status, m)


def priority_color(priority: str) -> str:
    return {
        "urgent": ACCENT,
        "high": PRIMARY,
        "normal": muted(),
        "low": "#71717a",
    }.get(priority, muted())


# Stable per-name category color, matching the web app's hashing approach.
_CAT_PALETTE = [
    "#a874ff", "#f65fa6", "#34d399", "#fbbf24", "#60a5fa",
    "#f87171", "#c084fc", "#2dd4bf", "#fb923c", "#4ade80",
]


def category_color(name: str) -> str:
    if not name:
        return muted()
    h = sum(ord(c) for c in name)
    return _CAT_PALETTE[h % len(_CAT_PALETTE)]
