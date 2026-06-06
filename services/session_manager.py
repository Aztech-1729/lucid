"""
Session manager — All session import/export/reconnect/revoke operations.

This is the ONLY module that reads, writes, or decrypts session strings.
Uses Fernet symmetric encryption (compatible with existing accounts).
"""

from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet
from telethon import TelegramClient
from telethon.sessions import StringSession

from core.config import get_settings
from core.exceptions import SessionDecryptionError, SessionInvalidError
from core.logging import get_logger
from models.account import Account
from repositories import accounts_repo

log = get_logger("session_manager")


def _get_fernet() -> Fernet:
    """Get the Fernet instance from the configured key."""
    key = get_settings().session_encryption_key
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt_session(raw_session: str) -> str:
    """Encrypt a raw session string using Fernet."""
    f = _get_fernet()
    return f.encrypt(raw_session.encode("utf-8")).decode("utf-8")


def decrypt_session(encrypted: str) -> str:
    """Decrypt an encrypted session string using Fernet."""
    f = _get_fernet()
    try:
        return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise SessionDecryptionError(
            "Failed to decrypt session string",
            detail=str(exc),
        ) from exc


async def import_session(owner_id: int, raw_string: str) -> Account:
    """
    Validate, encrypt, and persist a Telethon StringSession.

    This is the ONLY place where direct TelegramClient instantiation
    is permitted — for initial session validation.
    """
    raw_string = raw_string.strip()
    settings = get_settings()

    # 1. Parse StringSession — raises if malformed
    try:
        session = StringSession(raw_string)
    except Exception as exc:
        raise SessionInvalidError(
            "Invalid session string format",
            detail=str(exc),
        ) from exc

    # 2. Connect and validate with a lightweight API call
    try:
        client = TelegramClient(session, settings.api_id, settings.api_hash)
        await client.connect()
        me = await client.get_me()
        if me is None:
            raise SessionInvalidError("Session returned no user info")
        await client.disconnect()
    except SessionInvalidError:
        raise
    except Exception as exc:
        raise SessionInvalidError(
            "Session failed live validation",
            detail=str(exc),
        ) from exc

    # 3. Check for duplicates using Telegram User ID
    telegram_id = me.id
    phone = me.phone or "unknown"
    
    # We must check by telegram_id to prevent duplicates even if phone is hidden
    existing = await accounts_repo.get_by_telegram_id(owner_id, telegram_id)
    if existing:
        raise SessionInvalidError(f"This Telegram account is already added as '{existing.name}'!")

    # 4. Encrypt and persist
    encrypted = encrypt_session(raw_string)
    account = await accounts_repo.create(
        owner_id=owner_id,
        phone=phone,
        session=encrypted,
        name=me.first_name or me.username or phone,
        telegram_id=telegram_id,
    )

    await log.ainfo(
        "session.imported",
        account_id=account.id,
        owner_id=owner_id,
        username=me.username,
    )

    return account


async def export_session(account_id: str, owner_id: int) -> str:
    """Decrypt and return the session string for an authorized user."""
    account = await accounts_repo.get(account_id)
    if account is None:
        raise SessionInvalidError("Account not found")
    if account.owner_id != owner_id:
        raise SessionInvalidError("Not authorized to export this session")

    return decrypt_session(account.session)


async def get_session_string(account_id: str) -> str:
    """Internal helper: get decrypted session string for pool usage."""
    account = await accounts_repo.get(account_id)
    if account is None:
        raise SessionInvalidError("Account not found")
    return decrypt_session(account.session)


async def validate(account_id: str) -> bool:
    """Attempt a lightweight API call to confirm a session is alive."""
    settings = get_settings()
    try:
        raw = await get_session_string(account_id)
        session = StringSession(raw)
        client = TelegramClient(session, settings.api_id, settings.api_hash)
        await client.connect()
        me = await client.get_me()
        await client.disconnect()
        return me is not None
    except Exception:
        return False


async def revoke(account_id: str) -> None:
    """Wipe session from DB and evict from pool."""
    await accounts_repo.delete(account_id)
    await log.ainfo("session.revoked", account_id=account_id)
