"""
Text, number, and date formatting helpers for Telegram message rendering.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def format_number(n: int | float) -> str:
    """Format a number with commas: 1234567 → '1,234,567'."""
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """Format a ratio as percentage: 0.875 → '87.5%'."""
    return f"{value * 100:.{decimals}f}%"


def format_time_ago(dt: datetime | None) -> str:
    """Format a datetime as relative time: '2h ago', '3d ago'."""
    if dt is None:
        return "Never"

    now = datetime.utcnow()
    delta = now - dt

    if delta.total_seconds() < 60:
        return "Just now"
    if delta.total_seconds() < 3600:
        minutes = int(delta.total_seconds() / 60)
        return f"{minutes}m ago"
    if delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        return f"{hours}h ago"
    days = delta.days
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        months = days // 30
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


def format_duration(seconds: int) -> str:
    """Format seconds as human-readable duration: 3661 → '1h 1m 1s'."""
    if seconds < 60:
        return f"{seconds}s"

    parts = []
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs:
        parts.append(f"{secs}s")
    return " ".join(parts)


def truncate(text: str, max_length: int = 50, suffix: str = "…") -> str:
    """Truncate text to max_length, adding suffix if truncated."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def progress_bar(value: float, total: float = 100, width: int = 10) -> str:
    """Render a text progress bar: ████████░░ 80%."""
    if total <= 0:
        ratio = 0.0
    else:
        ratio = min(value / total, 1.0)
    filled = int(width * ratio)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"{bar} {format_percentage(ratio, 0)}"


def format_health_score(score: int) -> str:
    """Format health score with emoji indicator."""
    if score >= 80:
        return f"🟢 {score}/100"
    if score >= 60:
        return f"🟡 {score}/100"
    if score >= 40:
        return f"🟠 {score}/100"
    if score >= 20:
        return f"🔴 {score}/100"
    return f"⛔ {score}/100"


def format_account_status(status: str) -> str:
    """Format account status with emoji."""
    status_emojis = {
        "ACTIVE": "🟢",
        "PAUSED": "⏸️",
        "QUARANTINED": "🔴",
        "BANNED": "⛔",
        "DISABLED": "⚫",
    }
    emoji = status_emojis.get(status, "❓")
    return f"{emoji} {status.title()}"


def mask_phone(phone: str) -> str:
    """Mask a phone number: +1234567890 → +12****7890."""
    if len(phone) <= 6:
        return phone
    return phone[:3] + "****" + phone[-4:]
