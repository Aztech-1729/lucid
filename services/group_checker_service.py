"""
Group checker service — validates group links using dedicated checker accounts.

- TXT links: public usernames (+ private invite hashes) are validated live.
- Folder links (t.me/addlist/...): expanded and each member chat is validated.
- Multiple checker accounts run in parallel and rotate on flood waits.
- Produces a deduped, filtered list of valid links for the user.
"""

from __future__ import annotations

import asyncio
import httpx
import random
import re
from collections import deque
from datetime import timedelta
from typing import Callable, Dict, List, Awaitable, Optional, Tuple

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

# Web preview checking (t.me HTML) — no MTProto, no flood limits, no accounts needed
WEB_CONCURRENCY = 24      # burst parallelism: 24 keeps ~half the pages intact
WEB_TIMEOUT = 10.0        # seconds per request (stale long-polls must fail fast)
WEB_RETRIES = 2           # retries on 429/403/network errors
WEB_CONN_REQS_CAP = 600   # rotate to a fresh h2 connection after N requests
WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
WEB_PROGRESS_EVERY = 50   # update progress message every N web checks

# t.me throttles per-IP after a burst of requests: pages start coming back as
# bare "Telegram: Contact @" shells identical to real user pages. Speed
# strategy: the first pass blasts through as fast as possible, accepting
# degraded renders, and recovery happens in the slow recheck passes (cheap
# and fully accurate). The guard below is only a pathological safety net
# (e.g. long-lived rate-limit): it fires on a shared timer so pauses never
# stack, and only when the unknown share is far above the natural rate from
# genuine user pages (~15%).
WEB_RATE_GUARD_HIGH = 0.70   # pause only if unknown share in window >= this
WEB_GUARD_LOOKBACK = 60      # sliding window size (last N results)
WEB_GUARD_PAUSE = 8.0        # seconds to cool down per pause

# Ambiguous renders are re-fetched afterwards in slow, jittered passes that
# start only after a full cool-down; genuine user pages stay "Contact"
# forever while throttled chats recover to full previews.
WEB_RECHECK_PASSES = 2         # extra slow passes for ambiguous renders
WEB_RECHECK_CONCURRENCY = 16   # much lower parallelism for rechecks
WEB_RECHECK_COOLDOWN = 10.0    # wait before rechecking (let t.me recover)


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
    """Extract clean, deduped t.me links from raw text/txt content.

    Parses the WHOLE text with one regex pass, so empty lines, BOMs, and
    arbitrary line structure can never cut off detection mid-file.
    """
    text = text.lstrip("\ufeff")
    links: List[str] = []
    seen = set()
    for m in LINK_RE.finditer(text):
        link = m.group(1).rstrip(".,;:!?")
        if link not in seen:
            seen.add(link)
            links.append(link)
    return links


def _is_folder_link(link: str) -> bool:
    return bool(FOLDER_RE.search(link))


def _is_private_link(link: str) -> bool:
    return bool(HASH_RE.search(link))


def _web_url(link: str) -> str:
    """Map a parsed t.me link to its public web preview URL."""
    body = link.split("t.me/", 1)[1]
    return f"https://t.me/{body}"


def _classify_web(link: str, html: str) -> str:
    """Classify a t.me preview page: valid | invalid | unknown.

    Real chats (groups/channels) render a title block plus a
    "tgme_page_extra" line containing member/subscriber counts. Under
    parallel load t.me sometimes serves a degraded "Contact @" shell that is
    indistinguishable from a real user page — those return "unknown" so the
    caller re-fetches them in a slow recheck pass. Dead/expired/user pages
    have stable shapes and are confident "invalid".
    """
    if not html:
        return "unknown"
    low = html.lower()
    if any(x in low for x in ("expired", "no longer accessible", "was deleted", "doesn")):
        return "invalid"
    if "tgme_page_title" in html:
        if _is_folder_link(link):
            return "valid"
        extra = re.search(r'class="tgme_page_extra"[^>]*>([^<]*)<', html)
        extra_text = extra.group(1).strip() if extra else ""
        if "member" in extra_text.lower() or "subscriber" in extra_text.lower():
            return "valid"
        return "invalid"
    title = re.search(r"<title>([^<]*)</title>", html, re.IGNORECASE)
    title_text = title.group(1).strip() if title else ""
    if not title_text or title_text.lower().startswith("telegram: contact"):
        return "unknown"
    return "invalid"


async def _check_links_web(links: List[str], on_result: Callable[[str, str], Awaitable[None]]) -> None:
    """Validate links via the public t.me preview pages (no MTProto, no flood).

    Each HTTP/2 connection carries a bounded number of requests: t.me
    terminates long-lived sessions after a couple thousand streams, which
    then replay against the dying connection (orders-of-magnitude slowdown,
    retries on top of retries). The client is therefore rotated to a fresh
    connection every WEB_CONN_REQS_CAP requests. A first burst pass runs
    fast; anything "unknown" (degraded "Contact @" renders are
    indistinguishable from real user pages mid-throttle) is re-fetched in
    slow, jittered recheck passes. Every link is delivered exactly once via
    on_result(link, status): valid | invalid | unknown.
    """
    fetch_lock = asyncio.Lock()
    cur: List[httpx.AsyncClient] = []
    retired: List[httpx.AsyncClient] = []
    reqs = [0]

    async def _make_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=WEB_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": WEB_UA, "Accept-Language": "en"},
            http2=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )

    async def _client() -> httpx.AsyncClient:
        async with fetch_lock:
            if reqs[0] >= WEB_CONN_REQS_CAP:
                retired.append(cur[0])
                cur[0] = await _make_client()
                reqs[0] = 0
            reqs[0] += 1
            return cur[0]

    async def _fetch(link: str) -> str:
        client = await _client()
        for attempt in range(WEB_RETRIES + 1):
            try:
                resp = await client.get(_web_url(link))
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in (429, 403) and attempt < WEB_RETRIES:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                return ""
            except Exception:
                if attempt < WEB_RETRIES:
                    await asyncio.sleep(0.5 * (attempt + 1))
                continue
        return ""

    async def _run_pass(pass_links: List[str], concurrency: int, jitter: Optional[Tuple[float, float]], adaptive: bool) -> Dict[str, str]:
        out: Dict[str, str] = {}
        window: deque = deque(maxlen=WEB_GUARD_LOOKBACK)
        pos = [0]
        pop_lock = asyncio.Lock()
        throttle_until = [0.0]

        async def worker() -> None:
            while True:
                if adaptive:
                    now = asyncio.get_event_loop().time()
                    if throttle_until[0] > now:
                        await asyncio.sleep(throttle_until[0] - now)
                        continue
                    if len(window) >= 30:
                        unknown_share = sum(1 for s in window if s == "unknown") / len(window)
                        if unknown_share >= WEB_RATE_GUARD_HIGH:
                            throttle_until[0] = now + WEB_GUARD_PAUSE
                            window.clear()
                            continue
                async with pop_lock:
                    if pos[0] >= len(pass_links):
                        return
                    link = pass_links[pos[0]]
                    pos[0] += 1
                if jitter:
                    await asyncio.sleep(random.uniform(*jitter))
                status = _classify_web(link, await _fetch(link))
                out[link] = status
                window.append(status)

        await asyncio.gather(*[worker() for _ in range(concurrency)])
        return out

    cur.append(await _make_client())
    try:
        pending = list(links)
        for round_i in range(WEB_RECHECK_PASSES + 1):
            if round_i > 0:
                await asyncio.sleep(WEB_RECHECK_COOLDOWN)
            concurrency = WEB_CONCURRENCY if round_i == 0 else WEB_RECHECK_CONCURRENCY
            jitter = None if round_i == 0 else (0.3, 0.6)
            results = await _run_pass(pending, concurrency, jitter, round_i == 0)
            still_unknown: List[str] = []
            for link in pending:
                status = results.get(link, "unknown")
                if status == "unknown" and round_i < WEB_RECHECK_PASSES:
                    still_unknown.append(link)
                else:
                    await on_result(link, status)
            pending = still_unknown
            if not pending:
                break
    finally:
        for c in retired + cur:
            try:
                await c.aclose()
            except Exception:
                pass


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
    """Two-phase checker pipeline:

    Phase 1 — folder links (t.me/addlist/...) via MTProto checker accounts
              (needs member-list expansion; rare: one request per folder).
    Phase 2 — everything else (public usernames, private hashes, expanded
              folder members) via public t.me web previews: no accounts,
              no FloodWait, ~20 parallel HTTP requests.
    """
    total = len(links)
    folder_links = [link for link in links if _is_folder_link(link)]
    web_links = [link for link in links if not _is_folder_link(link)]

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

    accounts = []
    try:
        accounts = await checker_repo.get_available()
    except Exception as e:
        await log.awarning("checker.accounts_query_error", error=str(e)[:120])

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

    try:
        await update_callback(
            checked=0, valid=0, invalid=0, total=total,
            status="🚀 Starting checker...", flood=0, skipped=0,
            accounts_count=len(accounts),
        )

        async def _account_worker(checker_doc: dict, idx: int, worker_links: List[str]) -> None:
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
                await client.disconnect()  # type: ignore[misc]
                raise
            except Exception as e:
                err_str = str(e).lower()
                if any(x in err_str for x in ("authkey", "auth key", "deactivated", "revoked", "not registered")):
                    await checker_repo.mark_broken(checker_id)
                    await log.awarning("checker.account_revoked", id=checker_id, error=str(e)[:120])
                else:
                    await log.awarning("checker.account_unusable", id=checker_id, error=str(e)[:120])
                async with state["lock"]:
                    state["skipped"] += len(worker_links[idx::len(accounts)])
                try:
                    await client.disconnect()  # type: ignore[misc]
                except Exception:
                    pass
                return

            try:
                delay_mult = 1.0
                my_links = worker_links[idx::len(accounts)]
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
                        await client.disconnect()  # type: ignore[misc]
                except Exception:
                    pass

        # Phase 1: folder expansion via MTProto accounts (rare, small batches)
        if folder_links and not accounts:
            web_links = web_links + folder_links
        if folder_links and accounts:
            folder_tasks = [_account_worker(acc, idx, folder_links) for idx, acc in enumerate(accounts)]
            await asyncio.gather(*folder_tasks)

        # Phase 2a: verify expanded folder members through the web preview
        if state["peers_links"]:
            members = list(dict.fromkeys(state["peers_links"]))
            state["peers_links"] = []
            verified_members = []
            await _safe_update(status="🌐 Verifying folder members via web preview...")

            async def member_result(link: str, status: str) -> None:
                if status == "valid":
                    verified_members.append(link)

            await _check_links_web(members, member_result)
            state["peers_links"] = verified_members

        # Phase 2b: bulk web preview checking (public + private + folder fallback)
        if web_links:
            await _safe_update(status="🌐 Checking via web preview...")
            web_done = 0

            async def web_result(link: str, status: str) -> None:
                nonlocal web_done
                async with state["lock"]:
                    state["checked"] += 1
                    web_done += 1
                    if status == "valid":
                        state["valid"] += 1
                        state["valid_links"].append(link)
                    elif status == "unknown":
                        state["skipped"] += 1
                    else:
                        state["invalid"] += 1
                if web_done % WEB_PROGRESS_EVERY == 0:
                    await _safe_update()

            await _check_links_web(web_links, web_result)
            await _safe_update(status="✅ Web preview complete")

        # Final merge: original valid links + web-verified folder members
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
        # Send a partial result with everything checked so far
        partial_links = list(dict.fromkeys(state["valid_links"] + state["peers_links"]))
        partial_stats = {
            "checked": state["checked"],
            "valid": len(state["valid_links"]),
            "invalid": state["invalid"],
            "flood": state["flood"],
            "skipped": state["skipped"],
            "total": total,
            "accounts_count": len(accounts),
            "cancelled": True,
        }
        try:
            await update_callback(
                checked=state["checked"], valid=len(state["valid_links"]),
                invalid=state["invalid"], total=total,
                status="🛑 Check stopped — sending partial result...",
                flood=state["flood"], skipped=state["skipped"],
                accounts_count=len(accounts),
            )
            await result_callback(partial_links, partial_stats)
        except Exception:
            pass
    except Exception as e:
        await log.aerror("checker.fatal_error", error=str(e))
        try:
            await update_callback(
                checked=0, valid=0, invalid=0, total=total,
                status=f"❌ Error: {str(e)[:30]}", flood=0, skipped=0,
                accounts_count=len(accounts),
            )
        except Exception:
            pass
    finally:
        _active_checkers.pop(user_id, None)
