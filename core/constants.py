"""
Enums, limits, Redis key templates, timeouts, and other constants.

This is the single source of truth for all magic values in the system.
"""

from __future__ import annotations

from enum import StrEnum


# ── Account Status ──────────────────────────────────────────

class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    QUARANTINED = "QUARANTINED"
    BANNED = "BANNED"
    DISABLED = "DISABLED"


# ── Health State ────────────────────────────────────────────

class HealthState(StrEnum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    LIMITED = "LIMITED"
    QUARANTINED = "QUARANTINED"
    BANNED = "BANNED"
    UNKNOWN = "UNKNOWN"


HEALTH_EMOJI: dict[HealthState, str] = {
    HealthState.HEALTHY: "🟢",
    HealthState.WARNING: "🟡",
    HealthState.LIMITED: "🟠",
    HealthState.QUARANTINED: "🔴",
    HealthState.BANNED: "⛔",
    HealthState.UNKNOWN: "⚫",
}


# ── Campaign Status ─────────────────────────────────────────

class CampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


# ── Worker Status ───────────────────────────────────────────

class WorkerStatus(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    CRASHED = "CRASHED"


# ── Circuit Breaker State ───────────────────────────────────

class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


# ── Redis Key Templates ────────────────────────────────────
# All templates expect .format() with the appropriate IDs.

class RedisKeys:
    """Centralized Redis key templates. Prefix is prepended at runtime."""

    # Dashboard
    DASHBOARD = "dashboard:{user_id}"

    # Accounts
    ACCOUNT_SUMMARY = "account:summary:{account_id}"
    ACCOUNT_LIST = "account:list:{user_id}"
    ACCOUNT_LIST_PAGE = "account:list:{user_id}:page:{page}"
    ACCOUNT_ROTATION_WEIGHTS = "account:rotation_weights"

    # Health
    HEALTH_SUMMARY = "health:summary:{user_id}"
    HEALTH_ACCOUNT = "health:account:{account_id}"
    HEALTH_ALERTS = "health:alerts:{user_id}"

    # Campaigns
    CAMPAIGN_SUMMARY = "campaign:summary:{campaign_id}"
    CAMPAIGN_LIST = "campaign:list:{user_id}"
    CAMPAIGN_LIST_PAGE = "campaign:list:{user_id}:page:{page}"

    # Analytics
    ANALYTICS_DASHBOARD = "analytics:dashboard:{user_id}"
    ANALYTICS_DAILY = "analytics:daily:{date}"
    ANALYTICS_WEEKLY = "analytics:weekly:{week}"
    ANALYTICS_ACCOUNT = "analytics:account:{account_id}"
    ANALYTICS_CAMPAIGN = "analytics:campaign:{campaign_id}"
    ANALYTICS_TOP_ACCOUNTS = "analytics:top_accounts"
    ANALYTICS_TOP_CAMPAIGNS = "analytics:top_campaigns"

    # User State
    USER_STATE = "state:{user_id}"
    USER_SESSION = "session:{user_id}"
    
    # AI State
    AI_CHAT_HISTORY = "ai:history:{user_id}"
    AI_ACTION_QUEUE = "ai:queue:{action_id}"

    # Runtime
    FLOOD_LOCK = "flood:{account_id}"
    WORKER_HEARTBEAT = "worker:heartbeat:{worker_id}"

    # Client Pool
    POOL_CIRCUIT = "pool:circuit:{account_id}"
    POOL_ERRORS = "pool:errors:{account_id}"
    POOL_LAST_USED = "pool:last_used:{account_id}"


    # Plans
    PLAN = "plan:{user_id}"


# ── Timeouts & Limits ──────────────────────────────────────

DEFAULT_PAGE_SIZE: int = 10
MAX_PAGE_SIZE: int = 20
CRASH_RECOVERY_DELAY: float = 5.0
HEARTBEAT_MISS_THRESHOLD: int = 3  # missed heartbeats before restart

# ── Health Score Weights ────────────────────────────────────

HEALTH_WEIGHT_SPAMBOT: float = 0.40
HEALTH_WEIGHT_FLOOD: float = 0.20
HEALTH_WEIGHT_SUCCESS_RATIO: float = 0.20
HEALTH_WEIGHT_AGE: float = 0.10
HEALTH_WEIGHT_RESTRICTIONS: float = 0.10

# ── Rotation Score Weights ──────────────────────────────────

ROTATION_WEIGHT_HEALTH: float = 0.50
ROTATION_WEIGHT_SUCCESS: float = 0.30
ROTATION_WEIGHT_FLOOD: float = 0.20

# ── Cache TTLs (seconds) ───────────────────────────────────

TTL_DASHBOARD: int = 180
TTL_ACCOUNT_SUMMARY: int = 300
TTL_HEALTH_SUMMARY: int = 300
TTL_ANALYTICS: int = 600
TTL_CAMPAIGN_SUMMARY: int = 300
TTL_USER_STATE: int = 86400  # 24 hours

# ── Callback Data Prefixes ─────────────────────────────────

class CB:
    """Callback data constants for inline keyboard buttons."""

    # Main menu
    DASHBOARD = "dashboard"
    ACCOUNTS = "accounts"
    CAMPAIGNS = "campaigns"
    HEALTH = "health"
    HEALTH_VIEW_ALL = "health:all"
    HEALTH_SETTINGS = "health:settings"
    HEALTH_SETTINGS_TOGGLE = "health:settings:toggle"
    ANALYTICS = "analytics"
    SETTINGS = "settings"
    GROUPS = "groups"
    # Groups
    GROUPS_VIEW = "groups:view:{account_id}:{page}"
    GROUPS_TOGGLE = "groups:toggle:{account_id}:{group_id}:{page}"
    GROUPS_SELECT_ALL = "groups:all:{account_id}:{page}"
    AUTO_JOIN = "groups:autojoin"

    # AI
    AI_CHAT = "ai:chat"
    AI_CONFIRM = "ai:confirm:{action_id}"
    AI_CANCEL = "ai:cancel:{action_id}"

    # Navigation
    BACK = "back"
    NOOP = "noop"

    # Accounts
    ACCOUNT_VIEW = "acc:view:{account_id}"
    ACCOUNT_ADD = "acc:add"
    ACCOUNT_DELETE = "acc:del:{account_id}"
    ACCOUNT_DELETE_ALL = "acc:delall"
    ACCOUNT_DELETE_LIMITED = "acc:dellimited"
    ACCOUNT_UPLOAD_SESSIONS = "acc:upload"
    ACCOUNT_PAUSE = "acc:pause:{account_id}"
    ACCOUNT_RESUME = "acc:resume:{account_id}"
    ACCOUNT_HEALTH = "acc:health:{account_id}"
    ACCOUNT_STATS = "acc:stats:{account_id}"
    ACCOUNT_NOTES = "acc:notes:{account_id}"
    
    # Bulk Account Manager
    BULK_MANAGER = "bulk:manager"
    BULK_NAME = "bulk:name"
    BULK_BIO = "bulk:bio"
    BULK_REMOVE_USERNAME = "bulk:rm_username"
    BULK_PHOTO = "bulk:photo"
    BULK_REMOVE_PHOTO = "bulk:rm_photo"
    BULK_CLEAN_DMS = "bulk:clean_dms"
    BULK_ARCHIVE = "bulk:archive"
    BULK_LEAVE_GROUPS = "bulk:leave_groups"
    BULK_REMOVE_FOLDERS = "bulk:rm_folders"
    BULK_AUTOJOIN = "bulk:autojoin"
    BULK_2FA = "bulk:2fa"
    BULK_2FA_SET = "bulk:2fa:set"
    BULK_2FA_REMOVE = "bulk:2fa:remove"
    BULK_CANCEL = "bulk:cancel"

    # Campaigns
    CAMPAIGN_VIEW = "cmp:view:{campaign_id}"
    CAMPAIGN_CREATE = "cmp:create"
    CAMPAIGN_PAUSE = "cmp:pause:{campaign_id}"
    CAMPAIGN_RESUME = "cmp:resume:{campaign_id}"
    CAMPAIGN_DELETE = "cmp:del:{campaign_id}"
    CAMPAIGN_DUPLICATE = "cmp:dup:{campaign_id}"

    # Health
    HEALTH_DETAIL = "health:detail:{account_id}"

    # Pagination
    PAGE_NEXT = "page:next:{screen}:{page}"
    PAGE_PREV = "page:prev:{screen}:{page}"

    # Confirmation
    CONFIRM_YES = "confirm:yes:{action}:{target_id}"
    CONFIRM_NO = "confirm:no"

    # Settings
    SETTINGS_AUTOREPLY = "settings:autoreply"
    SETTINGS_AUTOREPLY_TOGGLE = "settings:autoreply:toggle"
    SETTINGS_AUTOREPLY_VIEW = "settings:autoreply:view"
    SETTINGS_AUTOREPLY_CUSTOM = "settings:autoreply:custom"
