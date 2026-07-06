"""
Application settings loaded from environment variables / .env file.

Uses pydantic-settings v2 with SettingsConfigDict.
"""

from __future__ import annotations

from typing import Optional
from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for Lucid Ads Bot."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Telegram ────────────────────────────────────────────
    bot_token: str
    logs_bot_token: Optional[str] = None
    logs_bot_username: Optional[str] = None
    api_id: int
    api_hash: str
    admin_username: str

    # ── MongoDB ─────────────────────────────────────────────
    mongo_uri: str
    mongo_db: str

    # ── Redis ───────────────────────────────────────────────
    redis_uri: str
    redis_prefix: str

    # ── Workers ─────────────────────────────────────────────
    health_check_interval_seconds: int = 300
    cache_refresh_interval_seconds: int = 120
    analytics_refresh_interval_seconds: int = 300
    worker_heartbeat_interval_seconds: int = 30

    # ── Forwarding ──────────────────────────────────────────
    default_forward_delay_seconds: float = 2.0
    max_flood_wait_seconds: int = 300
    max_retry_attempts: int = 3

    # ── Thresholds ──────────────────────────────────────────
    health_pause_threshold: int = 40

    # ── Client Pool ─────────────────────────────────────────
    pool_max_clients: int = 15
    pool_idle_eviction_minutes: int = 15
    pool_circuit_failure_threshold: int = 5
    pool_circuit_cooldown_seconds: int = 60

    # ── Force Join ──────────────────────────────────────────
    force_join_enabled: bool = False
    force_join_channel: str = ""
    force_join_group: str = ""

    # ── Session Encryption ──────────────────────────────────
    session_encryption_key: str  # base64-encoded 32-byte AES key


    # ── AI Configuration ────────────────────────────────────
    ai_provider: str = "openai"
    ai_api_key: Optional[str] = None
    ai_base_url: Optional[str] = None

    # ── Pagination ──────────────────────────────────────────
    default_page_size: int = 20

    # ── Logging ─────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "console"

    # ── Admin ───────────────────────────────────────────────
    admin_user_ids: list[int] = Field(default_factory=list)
    admin_username: str = ""

    # Bot Branding
    bot_image_url: str = ""
    logs_bot_image_url: str = ""
    plan_image_url: str = ""
    bot_username: str = ""
