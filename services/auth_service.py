"""
Authentication service for adding accounts via Phone Number & OTP.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

from core.config import get_settings
from core.logging import get_logger

log = get_logger("auth_service")

# In-memory store for active login sessions. Key: user_id
_auth_sessions: dict[int, dict[str, Any]] = {}

OTP_TIMEOUT_SECONDS = 300


async def start_auth(user_id: int, phone: str) -> bool:
    """
    Start the authentication process for a phone number.
    Returns True if OTP was successfully requested.
    """
    await cleanup_auth(user_id)
    
    settings = get_settings()
    
    # Create temporary client
    client = TelegramClient(StringSession(), settings.api_id, settings.api_hash)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(phone)
        _auth_sessions[user_id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent_code.phone_code_hash,
            "timestamp": time.time(),
        }
        return True
    except Exception as exc:
        await log.aerror("auth.send_code_failed", user_id=user_id, error=str(exc))
        await client.disconnect()
        raise


async def submit_otp(user_id: int, otp: str) -> str:
    """
    Submit the OTP for a user's active auth session.
    Returns: 'success', 'needs_password', or raises an Exception.
    """
    session_data = _auth_sessions.get(user_id)
    if not session_data:
        raise ValueError("No active authentication session. Please start over.")
        
    if time.time() - session_data["timestamp"] > OTP_TIMEOUT_SECONDS:
        await cleanup_auth(user_id)
        raise ValueError("OTP expired (5 minutes passed). Please start over.")
        
    client: TelegramClient = session_data["client"]
    phone = session_data["phone"]
    phone_code_hash = session_data["phone_code_hash"]
    
    try:
        await client.sign_in(phone=phone, code=otp, phone_code_hash=phone_code_hash)
        return "success"
    except SessionPasswordNeededError:
        return "needs_password"
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as exc:
        raise ValueError("Invalid or expired OTP.") from exc
    except Exception as exc:
        await log.aerror("auth.submit_otp_failed", user_id=user_id, error=str(exc))
        raise


async def submit_password(user_id: int, password: str) -> str:
    """
    Submit the 2FA password.
    Returns: 'success', or raises an Exception.
    """
    session_data = _auth_sessions.get(user_id)
    if not session_data:
        raise ValueError("No active authentication session. Please start over.")
        
    if time.time() - session_data["timestamp"] > OTP_TIMEOUT_SECONDS:
        await cleanup_auth(user_id)
        raise ValueError("Session expired (5 minutes passed). Please start over.")
        
    client: TelegramClient = session_data["client"]
    
    try:
        await client.sign_in(password=password)
        return "success"
    except Exception as exc:
        await log.aerror("auth.submit_password_failed", user_id=user_id, error=str(exc))
        raise ValueError("Invalid password or error signing in.")


async def finalize_auth(user_id: int) -> dict:
    """
    Finalize the authentication, fetch user profile and stats, export session string.
    Returns a dictionary with the summary and the raw session string.
    """
    session_data = _auth_sessions.get(user_id)
    if not session_data:
        raise ValueError("No active authentication session.")
        
    client: TelegramClient = session_data["client"]
    
    try:
        me = await client.get_me()
        dialogs = await client.get_dialogs()
        
        # Count groups/channels and parse them
        groups = []
        for d in dialogs:
            if d.is_group or d.is_channel:
                groups.append({
                    "id": d.id,
                    "title": d.title or "Unknown Group",
                    "is_channel": d.is_channel,
                    "is_selected": True
                })
        
        raw_session = client.session.save()
        
        # Determine Bio (Telethon get_me doesn't include bio, need full user)
        # Using GetFullUserRequest to get bio
        from telethon.tl.functions.users import GetFullUserRequest
        full_user = await client(GetFullUserRequest(me.id))
        bio = full_user.full_user.about or "No Bio"
        
        summary = {
            "name": f"{me.first_name or ''} {me.last_name or ''}".strip(),
            "username": f"@{me.username}" if me.username else "No Username",
            "bio": bio,
            "groups_count": len(groups),
            "groups": groups,
            "raw_session": raw_session
        }
        
        return summary
    finally:
        # We DO NOT disconnect the client here because if we export the session string, 
        # and then disconnect, Telethon might invalidate something or we can just let it 
        # disconnect safely. Actually, disconnecting is fine since it's an in-memory string session.
        await cleanup_auth(user_id)


async def cleanup_auth(user_id: int) -> None:
    """Disconnect and clean up any active auth session for the user."""
    session_data = _auth_sessions.pop(user_id, None)
    if session_data:
        client: TelegramClient = session_data["client"]
        try:
            await client.disconnect()
        except Exception:
            pass
