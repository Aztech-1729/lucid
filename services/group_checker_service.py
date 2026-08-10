"""
Group checker service — validates group links using dedicated checker accounts.

- TXT links: public usernames (+ private invite hashes) are validated live.
- Folder links (t.me/addlist/...): expanded and each member chat is validated.
- Multiple checker accounts run in parallel and rotate on flood waits.
- Produces a deduped, filtered list of valid links for the user.
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import timedelta
from typing import Callable, Dict, List

from telethon import TelegramClient
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    InviteHashExpiredError,
    UserAlreadyParticipantError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession
from telethon.tl import functions, types

from core.config import get_settings
from core.logging import get_logger
from repositories import checker_repo
from utils.helpers import now_utc_naive

log = get_logger("group_checker")

# Global state: one checker run per user
_active_checkers: Dict[int, asyncio.Task] = {}

# Matches t.me/<username>, t.me/+<hash>, t.me/joinchat/<hash>, t.me/addlist/<slug>
LINK_RE = re.compile(r"(t\.me/(?:joinchat/|addlist/|\+)?[A-Za-z0-9_+\-]+)", re.I)
FOLDER_RE = re.compile(r"t\.me/addlist/([A-Za-z0-9_\-]+)", re.I)
HASH_RE = re.compile(r"t\.me/(?:\+([A-Za-z0-9_\-]+)|joinchat/([A-Za-z0-9_\-]+))", re.I)
USERNAME_RE = re.compile(r"t\.me/([A-Za-z0-9_]{5,32})$", re.I)

# Adaptive pacing: start fast, back off on floods, recover gradually
CHECK_DELAY = (0.4, 0.6)  # base seconds between checks (per account, parallel)
DELAY_MULT_MAX = 8.0      # max slowdown multiplier after repeated floods
DELAY_RECOVER = 0.8       # fraction of multiplier kept per successful check
FLOOD_SLEEP_CAP = 30      # seconds — above this, the account bows out of the run


def is_checker_running(user_id: int) -> bool:
    """Check if a checker task is running for a user."""
    task = _active_checkers.get(user_id)
    return task is not None and not task.done()


async def cancel_checker(user_id: int) -> bool:
    """Cancel a running checker task."""
    task = _active_checkers.get(user_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def parse_check_links(text: str) -> List[str]:
    """Extract clean, deduped t.me links from raw text/txt content."""
    links: List[str] = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for m in LINK_RE.finditer(line):
            link = m.group(1).rstrip(".,;")
            if link not in seen:
                seen.add(link)
                links.append(link)
    return links


def _is_folder_link(link: str) -> bool:
    return bool(FOLDER_RE.search(link))


def _is_private_link(link: str) -> bool:
    return bool(HASH_RE.search(link))


async def _check_link(client: TelegramClient, link: str) -> dict:
    """
    Validate one link. Returns:
      status: valid_group | valid_channel | valid_folder | invalid | user | flood
      peers_links: expanded chat links (for folder links)
    """
    if _is_folder_link(link):
        m = FOLDER_RE.search(link)
        assert m
        slug = m.group(1)
        try:
            res = await client(functions.chatlists.CheckChatlistInviteRequest(slug=slug))
            if isinstance(res, types.chatlists.ChatlistInviteAlready):
                return {"status": "valid_folder", "peers_links": []}
            if isinstance(res, types.chatlists.ChatlistInvite):
                peers_links = []
                for peer in res.peers:
                    username = getattr(peer, "username", None)
                    if username:
                        peers_links.append(f"t.me/{username}")
                return {"status": "valid_folder", "peers_links": peers_links}
            return {"status": "invalid"}
        except (FloodWaitError, UserAlreadyParticipantError):
            raise
        except Exception as e:
            if "expired" in str(e).lower() or "revoked" in str(e).lower():
                return {"status": "invalid"}
            await log.awarning("checker.folder_error", link=link, error=str(e)[:120])
            return {"status": "invalid"}

    if _is_private_link(link):
        m = HASH_RE.search(link)
        assert m
        hash_id = m.group(1) or m.group(2)
        try:
            res = await client(
                functions.messages.CheckChatInviteRequest(hash=hash_id)
            )
            if isinstance(res, types.ChatInvite):
                return {"status": "valid_group"}
            return {"status": "valid_group"}
        except UserAlreadyParticipantError:
            return {"status": "valid_group"}
        except InviteHashExpiredError:
            return {"status": "invalid"}
        except FloodWaitError:
            raise
        except Exception as e:
            if "expired" in str(e).lower() or "revoked" in str(e).lower():
                return {"status": "invalid"}
            await log.awarning("checker.hash_error", link=link, error=str(e)[:120])
            return {"status": "invalid"}

    # Public username
    m = USERNAME_RE.search(link)
    if not m:
        return {"status": "invalid"}
    username = m.group(1)
    try:
        entity = await client.get_entity(username)
        if isinstance(entity, types.Channel):
            if getattr(entity, "broadcast", False):
                return {"status": "valid_channel"}
            return {"status": "valid_group"}
        if isinstance(entity, (types.Chat, types.ChatForbidden)):
            return {"status": "valid_group"}
        return {"status": "user"}  # resolves but is a user, not a group
    except FloodWaitError:
        raise
    except (ChannelPrivateError, ChannelInvalidError, UsernameNotOccupiedError, UsernameInvalidError):
        return {"status": "invalid"}
    except Exception as e:
        await log.awarning("checker.username_error", link=link, error=str(e)[:120])
        return {"status": "invalid"}


async def start_check(
    user_id: int,
    links: List[str],
    update_callback: Callable,
    result_callback: Callable,
) -> None:
    """Start the checker background task."""
    if is_checker_running(user_id):
        return

    task = asyncio.create_task(
        _run_checker_task(user_id, links, update_callback, result_callback)
    )
    _active_checkers[user_id] = task


async def _run_checker_task(
    user_id: int,
    links: List[str],
    update_callback: Callable,
    result_callback: Callable,
) -> None:
    """Background task that validates links across checker accounts in parallel."""
    accounts = []
    total = len(links)
    try:
        accounts = await checker_repo.get_available()
        if not accounts:
            await update_callback(
                checked=0, valid=0, invalid=0, total=total,
                status="❌ No checker accounts available. Add sessions first.",
                flood=0, skipped=0, accounts_count=0,
            )
            return

        state = {
            "valid_links": [],
            "peers_links": [],
            "checked": 0,
            "valid": 0,
            "invalid": 0,
            "flood": 0,
            "skipped": 0,
            "lock": asyncio.Lock(),
        }

        async def _safe_update(status: str = "Processing", **extra) -> None:
            async with state["lock"]:
                await update_callback(
                    checked=state["checked"],
                    valid=state["valid"],
                    invalid=state["invalid"],
                    total=total,
                    status=status,
                    flood=state["flood"],
                    skipped=state["skipped"],
                    accounts_count=len(accounts),
                )

        async def _account_worker(checker_doc: dict, idx: int) -> None:
            checker_id = str(checker_doc["_id"])
            settings = get_settings()
            client = TelegramClient(
                StringSession(checker_doc["session"]),
                settings.api_id,
                settings.api_hash,
                connection_retries=2,
                request_retries=2,
                retry_delay=2,
            )
            try:
                await client.connect()
                if not client.is_connected():
                    raise ConnectionError("connect failed")
                me = await client.get_me()
                if not me:
                    raise ConnectionError("empty session")
            except asyncio.CancelledError:
                await client.disconnect()
                raise
            except Exception as e:
                err_str = str(e).lower()
                if any(x in err_str for x in ("authkey", "auth key", "deactivated", "revoked", "not registered")):
                    await checker_repo.mark_broken(checker_id)
                    await log.awarning("checker.account_revoked", id=checker_id, error=str(e)[:120])
                else:
                    await log.awarning("checker.account_unusable", id=checker_id, error=str(e)[:120])
                async with state["lock"]:
                    state["skipped"] += len(links[idx::len(accounts)])
                try:
                    await client.disconnect()
                except Exception:
                    pass
                return

            try:
                delay_mult = 1.0
                my_links = links[idx::len(accounts)]
                for i, link in enumerate(my_links):
                    await asyncio.sleep(random.uniform(*CHECK_DELAY) * delay_mult)
                    try:
                        result = await _check_link(client, link)
                    except FloodWaitError as fl:
                        await log.awarning("checker.flood_wait", seconds=fl.seconds)
                        async with state["lock"]:
                            state["flood"] += 1
                            state["checked"] += 1
                        if fl.seconds <= FLOOD_SLEEP_CAP:
                            delay_mult = min(delay_mult * 2.0, DELAY_MULT_MAX)
                            await asyncio.sleep(fl.seconds)
                            continue
                        await checker_repo.record_use(checker_id, flood_until=now_utc_naive() + timedelta(seconds=fl.seconds))
                        async with state["lock"]:
                            state["skipped"] += len(my_links) - i
                        break
                    except Exception as e:
                        await log.awarning("checker.link_error", link=link, error=str(e)[:120])
                        async with state["lock"]:
                            state["checked"] += 1
                            state["invalid"] += 1
                        continue

                    status = result.get("status")
                    async with state["lock"]:
                        state["checked"] += 1
                        if status in ("valid_group", "valid_channel", "valid_folder"):
                            state["valid"] += 1
                            state["valid_links"].append(link)
                            for pl in result.get("peers_links", []):
                                if pl not in state["peers_links"]:
                                    state["peers_links"].append(pl)
                        else:
                            state["invalid"] += 1

                    delay_mult = max(1.0, delay_mult * DELAY_RECOVER)
                    await _safe_update()
                await checker_repo.record_use(checker_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await log.awarning("checker.worker_error", error=str(e)[:120])
            finally:
                try:
                    if client.is_connected():
                        await client.disconnect()
                except Exception:
                    pass

        await update_callback(
            checked=0, valid=0, invalid=0, total=total,
            status="🚀 Starting checker...", flood=0, skipped=0,
            accounts_count=len(accounts),
        )

        tasks = [_account_worker(acc, idx) for idx, acc in enumerate(accounts)]
        await asyncio.gather(*tasks)

        # Merge folder-expanded links into the final list
        final_links = list(dict.fromkeys(state["valid_links"] + state["peers_links"]))

        stats = {
            "checked": state["checked"],
            "valid": state["valid"],
            "invalid": state["invalid"],
            "flood": state["flood"],
            "skipped": state["skipped"],
            "total": total,
            "accounts_count": len(accounts),
        }
        await _safe_update(status="✅ Check complete!")
        await result_callback(final_links, stats)

    except asyncio.CancelledError:
        await log.ainfo("checker.cancelled", user_id=user_id)
        try:
            await update_callback(
                checked=0, valid=0, invalid=0, total=len(links),
                status="🛑 Check cancelled", flood=0, skipped=0,
                accounts_count=len(accounts),
            )
        except Exception:
            pass
    except Exception as e:
        await log.aerror("checker.fatal_error", error=str(e))
        try:
            await update_callback(
                checked=0, valid=0, invalid=0, total=len(links),
                status=f"❌ Error: {str(e)[:30]}", flood=0, skipped=0,
                accounts_count=len(accounts),
            )
        except Exception:
            pass
    finally:
        _active_checkers.pop(user_id, None)