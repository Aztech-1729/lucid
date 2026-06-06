"""
Custom exception hierarchy for Lucid Ads Bot.

All domain exceptions inherit from LucidAdsBaseError so callers can
catch the entire family with a single except clause.
"""

from __future__ import annotations


class LucidAdsBaseError(Exception):
    """Base exception for all Lucid Ads domain errors."""

    def __init__(self, message: str = "", *, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(message)


# ── Account Errors ──────────────────────────────────────────

class AccountNotFoundError(LucidAdsBaseError):
    """Raised when an account lookup returns no result."""


class AccountBannedError(LucidAdsBaseError):
    """Raised when attempting to use a banned account."""


class AccountQuarantinedError(LucidAdsBaseError):
    """Raised when attempting to use a quarantined account."""


# ── Campaign Errors ─────────────────────────────────────────

class CampaignNotFoundError(LucidAdsBaseError):
    """Raised when a campaign lookup returns no result."""


class CampaignInactiveError(LucidAdsBaseError):
    """Raised when attempting an operation on a non-active campaign."""


# ── Health Errors ───────────────────────────────────────────

class HealthCheckFailedError(LucidAdsBaseError):
    """Raised when a SpamBot health check fails."""


# ── Infrastructure Errors ───────────────────────────────────

class CacheUnavailableError(LucidAdsBaseError):
    """Raised when Redis is unreachable or returns an error."""


class CircuitOpenError(LucidAdsBaseError):
    """Raised when the circuit breaker for an account is OPEN."""


# ── Session Errors ──────────────────────────────────────────

class SessionInvalidError(LucidAdsBaseError):
    """Raised when a Telethon session string fails validation."""


class SessionDecryptionError(LucidAdsBaseError):
    """Raised when session decryption fails (bad key or corrupted data)."""


# ── Plan Errors ─────────────────────────────────────────────

class PlanLimitError(LucidAdsBaseError):
    """Raised when a user has exceeded their plan quota."""


class PlanNotFoundError(LucidAdsBaseError):
    """Raised when a user has no plan record."""


# ── Force Join Errors ───────────────────────────────────────

class ForceJoinRequiredError(LucidAdsBaseError):
    """Raised when a user has not joined the required channels."""


# ── Group Errors ────────────────────────────────────────────

class GroupNotFoundError(LucidAdsBaseError):
    """Raised when a group lookup returns no result."""
