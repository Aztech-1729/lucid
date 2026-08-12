"""
Screen routing and back-stack management.

go_back pops the navigation stack and routes to the correct screen.
"""

from __future__ import annotations

import typing
from typing import Any, Callable, Coroutine, cast, Optional
from core.logging import get_logger
from telegram.states import pop_screen, get_context

log = get_logger("navigation")


async def go_back(event: Any) -> None:
    """
    Go back to the previous screen in the navigation stack.

    Pops the screen stack and routes directly to the correct callback handler.
    If the stack is empty, falls back to dashboard.
    """
    user_id = event.sender_id
    screen = await pop_screen(user_id)

    # Import here to avoid circular imports
    from telegram import callbacks

    # Route to the correct screen — the screen we are RETURNING to
    if screen == "account_detail":
        account_id = await get_context(user_id, "account_id")
        if account_id:
            await callbacks.on_account_view(event, account_id)
        else:
            await callbacks.on_accounts(event)
    elif screen == "campaign_detail":
        campaign_id = await get_context(user_id, "campaign_id")
        if campaign_id:
            await callbacks.on_campaign_view(event, campaign_id)
        else:
            await callbacks.on_campaigns(event)
    elif screen == "accounts":
        await callbacks.on_accounts(event)
    elif screen == "campaigns":
        await callbacks.on_campaigns(event)
    elif screen == "health":
        await callbacks.on_health(event)
    elif screen == "health_all":
        await callbacks.on_health_view_all(event)
    elif screen == "analytics":
        await callbacks.on_analytics(event)
    elif screen == "settings":
        # No dedicated settings screen handler; fall back to dashboard
        await callbacks.on_dashboard(event)
    else:
        # main_menu / unknown: go to dashboard
        await callbacks.on_dashboard(event)
