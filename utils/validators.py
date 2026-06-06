"""
Input validation and sanitization utilities.
"""

from __future__ import annotations

import re
from typing import Optional


def validate_session_string(session: str) -> bool:
    """
    Validate a Telethon StringSession format.

    A valid session string is a non-empty base64-like string,
    typically 300+ characters long.
    """
    if not session or not isinstance(session, str):
        return False

    session = session.strip()

    # Must be at least 100 chars (typical sessions are 300+)
    if len(session) < 100:
        return False

    # Should be alphanumeric + base64 chars
    if not re.match(r'^[A-Za-z0-9+/=]+$', session):
        return False

    return True


def normalize_phone(phone: str) -> str:
    """
    Normalize a phone number.

    Strips whitespace, dashes, and ensures + prefix.
    """
    phone = re.sub(r'[\s\-\(\)]', '', phone.strip())
    if not phone.startswith('+'):
        phone = '+' + phone
    return phone


def validate_phone(phone: str) -> bool:
    """Check if a phone number is plausibly valid."""
    normalized = normalize_phone(phone)
    # Must be + followed by 7-15 digits
    return bool(re.match(r'^\+\d{7,15}$', normalized))


def sanitize_campaign_name(name: str) -> str:
    """Sanitize a campaign name for display."""
    # Strip control characters, excessive whitespace
    name = re.sub(r'[\x00-\x1f\x7f]', '', name.strip())
    name = re.sub(r'\s+', ' ', name)
    # Truncate to 100 chars
    return name[:100]


def validate_campaign_name(name: str) -> tuple[bool, Optional[str]]:
    """
    Validate a campaign name.

    Returns (is_valid, error_message).
    """
    if not name or not name.strip():
        return False, "Campaign name cannot be empty"
    if len(name) > 100:
        return False, "Campaign name must be 100 characters or less"
    if len(name) < 2:
        return False, "Campaign name must be at least 2 characters"
    return True, None


def validate_delay(delay: float) -> tuple[bool, Optional[str]]:
    """
    Validate a forwarding delay value.

    Returns (is_valid, error_message).
    """
    if delay < 0:
        return False, "Delay cannot be negative"
    if delay > 3600:
        return False, "Delay cannot exceed 1 hour"
    return True, None


def parse_callback_data(data: str | bytes) -> tuple[str, list[str]]:
    """
    Parse callback data into action and parameters.

    Example: "acc:view:abc123" → ("acc:view", ["abc123"])
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")

    parts = data.split(":")
    if len(parts) <= 2:
        return data, []

    # First two parts are the action prefix, rest are params
    action = ":".join(parts[:2])
    params = parts[2:]
    return action, params
