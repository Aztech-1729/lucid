"""
TelegramClient pool — The ONLY way to acquire Telegram clients.

Features:
- Client reuse via in-memory pool keyed by account_id
- Configurable max clients cap
- Idle eviction for unused clients
- Per-account asyncio.Lock for exclusive access
- Circuit breaker pattern (CLOSED → OPEN → HALF_OPEN)
- Transparent reconnection on disconnect
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from telethon import TelegramClient
from telethon.sessions import StringSession

from cache.redis_client import get_redis, make_key
from core.config import get_settings
from core.constants import CircuitState, RedisKeys
from core.exceptions import CircuitOpenError
from core.logging import get_logger

log = get_logger("client_pool")


@dataclass
class PoolSlot:
    """An entry in the client pool."""

    account_id: str
    client: TelegramClient
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)
    error_count: int = 0
    is_borrowed: bool = False


class ClientPool:
    """
    Managed pool of TelegramClient instances.

    All Telethon clients must be acquired exclusively through this pool.
    Never instantiate TelegramClient directly in any service or worker.
    """

    def __init__(self) -> None:
        self._slots: dict[str, PoolSlot] = {}
        self._global_lock = asyncio.Lock()
        self._eviction_task: Optional[asyncio.Task] = None
        self._running = False
        self.keep_alive_accounts: set[str] = set()

    async def start(self) -> None:
        """Start the pool and idle eviction loop."""
        self._running = True
        self._eviction_task = asyncio.create_task(self._eviction_loop())
        await log.ainfo("pool.started")

    async def stop(self) -> None:
        """Stop the pool and disconnect all clients."""
        self._running = False
        if self._eviction_task:
            self._eviction_task.cancel()
            try:
                await self._eviction_task
            except asyncio.CancelledError:
                pass

        # Disconnect all clients concurrently
        disconnect_tasks = []
        for slot in list(self._slots.values()):
            disconnect_tasks.append(slot.client.disconnect())
            
        if disconnect_tasks:
            await asyncio.gather(*disconnect_tasks, return_exceptions=True)
            # Give Telethon's internal send/recv loops time to finalize
            await asyncio.sleep(0.25)
            
        self._slots.clear()
        await log.ainfo("pool.stopped")

    @asynccontextmanager
    async def acquire(self, account_id: str) -> AsyncIterator[TelegramClient]:
        """
        Borrow a connected client for an account.

        Usage:
            async with client_pool.acquire(account_id) as client:
                await client.send_message(target, message)
        """
        account_id = str(account_id)
        
        while True:
            # Check circuit breaker
            await self._check_circuit(account_id)
    
            slot = await self._get_or_create_slot(account_id)
    
            async with slot.lock:
                # STATE DRIFT FIX: Verify slot wasn't evicted while waiting for the lock
                if self._slots.get(account_id) is not slot:
                    # Slot was evicted. Retry acquisition from the beginning.
                    continue
                    
                try:
                    # Reconnect if disconnected
                    if not slot.client.is_connected():
                        await asyncio.wait_for(slot.client.connect(), timeout=15.0)
    
                    slot.is_borrowed = True
                    slot.last_used = time.monotonic()
    
                    yield slot.client
    
                    # Success — reset error count
                    slot.error_count = 0
                    await self._update_circuit(account_id, success=True)
    
                except Exception as exc:
                    slot.error_count += 1
                    await self._update_circuit(account_id, success=False)
                    
                    # Force disconnect or auto-delete on fatal connection/session errors
                    err_str = str(exc).lower()
                    if any(x in err_str for x in ["authkey", "deactivated", "authorization key"]):
                        # Only auto-delete after 3 consecutive auth failures to avoid
                        # false positives from Telegram rate-limiting during bulk operations
                        if slot.error_count >= 3:
                            try:
                                from services import account_service
                                asyncio.create_task(account_service.handle_unauthorized_account(account_id))
                                await log.aerror("pool.account_revoked", account_id=account_id, error=str(exc))
                            except Exception:
                                pass
                        else:
                            await log.awarning("pool.auth_error_transient", account_id=account_id, attempt=slot.error_count, error=str(exc))
                            try:
                                await slot.client.disconnect()
                            except Exception:
                                pass
                    elif "wrong session id" in err_str or "connection" in err_str or "closed" in err_str or "unpacking" in err_str:
                        try:
                            await slot.client.disconnect()
                        except Exception:
                            pass
                            
                    raise
    
                finally:
                    slot.is_borrowed = False
                    slot.last_used = time.monotonic()
    
                    # Update last-used in Redis
                    r = get_redis()
                    key = make_key(RedisKeys.POOL_LAST_USED, account_id=account_id)
                    await r.set(key, str(time.time()))
                    
            # Break the retry loop on successful yield/finally completion
            break

    async def evict(self, account_id: str) -> None:
        """Force-disconnect and remove a client (on ban/quarantine)."""
        account_id = str(account_id)
        async with self._global_lock:
            slot = self._slots.pop(account_id, None)
            if slot:
                try:
                    await slot.client.disconnect()
                    # Give Telethon's internal send/recv loops time to finalize
                    await asyncio.sleep(0.25)
                except Exception:
                    pass
                await log.ainfo("pool.evicted", account_id=account_id)

    async def register(self, account_id: str, session: StringSession) -> None:
        """Register a new session in the pool without connecting."""
        account_id = str(account_id)
        settings = get_settings()
        client = TelegramClient(session, settings.api_id, settings.api_hash, connection_retries=3, request_retries=3, retry_delay=2)
        async with self._global_lock:
            # STATE DRIFT FIX: Cleanly disconnect any existing client in this slot before replacing
            if account_id in self._slots:
                try:
                    await self._slots[account_id].client.disconnect()
                except Exception:
                    pass
                    
            self._slots[account_id] = PoolSlot(
                account_id=account_id,
                client=client,
            )

    async def stats(self) -> dict:
        """Return pool statistics."""
        # ASYNC FIX: Use a list snapshot to prevent dictionary size mutation errors
        slots_snapshot = list(self._slots.values())
        total = len(slots_snapshot)
        borrowed = sum(1 for s in slots_snapshot if s.is_borrowed)
        idle = total - borrowed

        # Get circuit states
        r = get_redis()
        circuits: dict[str, str] = {}
        for account_id in self._slots:
            key = make_key(RedisKeys.POOL_CIRCUIT, account_id=account_id)
            state = await r.get(key)
            if state:
                circuits[account_id] = state

        return {
            "total_clients": total,
            "active_borrows": borrowed,
            "idle_clients": idle,
            "max_clients": get_settings().pool_max_clients,
            "circuits": circuits,
        }

    # ── Internal methods ────────────────────────────────────

    async def _get_or_create_slot(self, account_id: str) -> PoolSlot:
        """Get existing slot or create a new one."""
        if account_id in self._slots:
            return self._slots[account_id]

        async with self._global_lock:
            # Double-check
            if account_id in self._slots:
                return self._slots[account_id]

            # Enforce max clients
            settings = get_settings()
            if len(self._slots) >= settings.pool_max_clients:
                # Evict least-recently-used idle client
                await self._evict_lru()

            # Create new client from stored session
            from services.session_manager import get_session_string
            raw_session = await get_session_string(account_id)
            session = StringSession(raw_session)
            client = TelegramClient(session, settings.api_id, settings.api_hash, connection_retries=3, request_retries=3, retry_delay=2)
            
            # Attach account ID and Auto Reply handler
            client.account_id = account_id
            from telethon import events
            from services.autoreply_service import handle_incoming_message
            client.add_event_handler(handle_incoming_message, events.NewMessage(incoming=True))
            
            slot = PoolSlot(account_id=account_id, client=client)
            self._slots[account_id] = slot

            await log.ainfo(
                "pool.client_created",
                account_id=account_id,
                pool_size=len(self._slots),
            )
            return slot

    async def _evict_lru(self) -> None:
        """Evict the least-recently-used idle client."""
        idle_slots = [
            (aid, s) for aid, s in self._slots.items()
            if not s.is_borrowed
        ]
        if not idle_slots:
            await log.awarning("pool.no_idle_to_evict")
            return

        # Sort by last_used ascending
        idle_slots.sort(key=lambda x: x[1].last_used)
        lru_id, lru_slot = idle_slots[0]

        try:
            await lru_slot.client.disconnect()
            await asyncio.sleep(0.25)
        except Exception:
            pass

        del self._slots[lru_id]
        await log.ainfo("pool.lru_evicted", account_id=lru_id)

    async def _eviction_loop(self) -> None:
        """Background loop that evicts idle clients."""
        settings = get_settings()
        eviction_seconds = settings.pool_idle_eviction_minutes * 60

        while self._running:
            try:
                await asyncio.sleep(60)  # Check every minute

                now = time.monotonic()
                to_evict = []

                # ASYNC FIX: Use a list snapshot to prevent dictionary size mutation errors
                for account_id, slot in list(self._slots.items()):
                    if account_id in self.keep_alive_accounts:
                        continue
                    if not slot.is_borrowed and (now - slot.last_used) > eviction_seconds:
                        to_evict.append(account_id)

                for account_id in to_evict:
                    await self.evict(account_id)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                await log.awarning("pool.eviction_error", error=str(exc))

    async def _check_circuit(self, account_id: str) -> None:
        """Check if the circuit breaker allows borrowing."""
        r = get_redis()
        key = make_key(RedisKeys.POOL_CIRCUIT, account_id=account_id)
        state = await r.get(key)

        if state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit breaker OPEN for account {account_id}. "
                f"Wait for cooldown before retrying."
            )

    async def _update_circuit(self, account_id: str, success: bool) -> None:
        """Update circuit breaker state after a borrow attempt."""
        settings = get_settings()
        r = get_redis()
        circuit_key = make_key(RedisKeys.POOL_CIRCUIT, account_id=account_id)
        errors_key = make_key(RedisKeys.POOL_ERRORS, account_id=account_id)

        if success:
            # Reset on success
            current = await r.get(circuit_key)
            if current == CircuitState.HALF_OPEN:
                await r.set(circuit_key, CircuitState.CLOSED)
                await r.delete(errors_key)
            return

        # Increment error count
        count = await r.incr(errors_key)
        await r.expire(errors_key, 300)  # 5-minute sliding window

        if count >= settings.pool_circuit_failure_threshold:
            await r.setex(
                circuit_key,
                settings.pool_circuit_cooldown_seconds,
                CircuitState.OPEN,
            )
            await log.awarning(
                "pool.circuit_opened",
                account_id=account_id,
                error_count=count,
            )


# ── Global singleton ────────────────────────────────────────

client_pool = ClientPool()
