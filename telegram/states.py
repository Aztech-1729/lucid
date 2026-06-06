"""
User state machine — Stored in Redis.

Tracks current screen, navigation stack, and pending input context
for each user interacting with the bot.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from cache.redis_client import get_redis, make_key
from core.constants import RedisKeys, TTL_USER_STATE


class UserState:
    """Represents the current UI state for a user."""

    def __init__(
        self,
        user_id: int,
        screen: str = "main_menu",
        nav_stack: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.user_id = user_id
        self.screen = screen
        self.nav_stack = nav_stack or []
        self.context = context or {}

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "screen": self.screen,
            "nav_stack": self.nav_stack,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserState":
        return cls(
            user_id=data["user_id"],
            screen=data.get("screen", "main_menu"),
            nav_stack=data.get("nav_stack", []),
            context=data.get("context", {}),
        )


async def get_state(user_id: int) -> UserState:
    """Get the current state for a user. Returns default if none exists."""
    r = get_redis()
    key = make_key(RedisKeys.USER_STATE, user_id=user_id)
    raw = await r.get(key)

    if raw:
        try:
            data = json.loads(raw)
            return UserState.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            pass

    return UserState(user_id=user_id)


async def set_state(state: UserState) -> None:
    """Save user state to Redis."""
    r = get_redis()
    key = make_key(RedisKeys.USER_STATE, user_id=state.user_id)
    await r.setex(key, TTL_USER_STATE, json.dumps(state.to_dict()))


async def push_screen(user_id: int, screen: str, context: dict | None = None) -> None:
    """Navigate to a new screen, pushing current to back stack."""
    state = await get_state(user_id)
    state.nav_stack.append(state.screen)
    state.screen = screen
    if context:
        # Merge context instead of overwriting
        state.context.update(context)
    await set_state(state)


async def pop_screen(user_id: int) -> str:
    """Go back to the previous screen. Returns the screen navigated to."""
    state = await get_state(user_id)
    if state.nav_stack:
        state.screen = state.nav_stack.pop()
    else:
        state.screen = "main_menu"
    # Do NOT clear context here as it may contain long-lived flags like view_source
    await set_state(state)
    return state.screen


async def set_context(user_id: int, key: str, value: Any) -> None:
    """Set a context variable for the current screen."""
    state = await get_state(user_id)
    state.context[key] = value
    await set_state(state)


async def get_context(user_id: int, key: str, default: Any = None) -> Any:
    """Get a context variable."""
    state = await get_state(user_id)
    return state.context.get(key, default)


async def clear_state(user_id: int) -> None:
    """Reset user state to main menu."""
    r = get_redis()
    key = make_key(RedisKeys.USER_STATE, user_id=user_id)
    await r.delete(key)
