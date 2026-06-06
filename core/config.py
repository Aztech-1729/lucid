"""
Runtime configuration loader.

Provides a cached singleton accessor for the Settings instance.
"""

from __future__ import annotations

import functools

from core.settings import Settings


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated application settings (cached singleton)."""
    return Settings()  # type: ignore[call-arg]


def reload_settings() -> Settings:
    """Force-reload settings from environment / .env file."""
    get_settings.cache_clear()
    return get_settings()
