"""
Screen routing and back-stack management.

go_back pops the navigation stack and routes to the correct screen.
"""

from __future__ import annotations

from core.logging import get_logger
from telegram.states import pop_screen

log = get_logger("navigation")


async def go_back(event) -> None:
    """
    Go back to the previous screen in the navigation stack.

    Pops the screen stack and routes directly to the correct callback handler.
    If the stack is empty, falls back to dashboard.
    """
    user_id = event.sender_id
    screen = await pop_screen(user_id)

    # Import here to avoid circular imports
    from telegram import callbacks

    # Route to the correct screen
    if screen == "account_detail":
        await callbacks.on_accounts(event)
    elif screen == "campaign_detail":
        await callbacks.on_campaigns(event)
    elif screen == "accounts":
        await callbacks.on_dashboard(event)
    elif screen == "campaigns":
        await callbacks.on_dashboard(event)
    elif screen == "health":
        await callbacks.on_dashboard(event)
    elif screen == "analytics":
        await callbacks.on_dashboard(event)
    elif screen == "settings":
        await callbacks.on_dashboard(event)
    else:
        # Default: go to dashboard
        await callbacks.on_dashboard(event)
