"""
MongoDB collection name constants.

Single source of truth for all collection names used in the application.
"""

from __future__ import annotations

import typing
from typing import Any, Callable, Coroutine, cast, Optional
USERS = "users"
ACCOUNTS = "accounts"
CAMPAIGNS = "campaigns"
HEALTH_RECORDS = "health_records"
FORWARDING_LOGS = "forwarding_logs"
ANALYTICS_DAILY = "analytics_daily"
WORKER_RECORDS = "worker_records"
CHECKER_ACCOUNTS = "checker_accounts"
