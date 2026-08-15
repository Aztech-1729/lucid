import aiohttp
import asyncio
import re
from typing import Any, Optional
from core.logging import get_logger

log = get_logger("mailtm_client")

BASE_URL = "https://api.mail.gw"


async def get_domain() -> str:
    """Fetch an active domain."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/domains") as resp:
            data = await resp.json()
            for domain in data.get("hydra:member", []):
                if domain.get("isActive"):
                    return domain["domain"]
            raise ValueError("No active domains found on mail.gw")


async def create_account(address: str, password: str) -> dict[str, Any]:
    """Create a new account on mail.gw."""
    async with aiohttp.ClientSession() as session:
        # Throttle handling
        for _ in range(3):
            async with session.post(f"{BASE_URL}/accounts", json={"address": address, "password": password}) as resp:
                if resp.status == 201:
                    return await resp.json()
                elif resp.status == 429:
                    await asyncio.sleep(5)
                else:
                    text = await resp.text()
                    raise ValueError(f"Failed to create mail.gw account ({resp.status}): {text}")
        raise ValueError("Rate limited while creating mail.gw account.")


async def get_token(address: str, password: str) -> str:
    """Get a JWT session token."""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{BASE_URL}/token", json={"address": address, "password": password}) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["token"]
            else:
                text = await resp.text()
                raise ValueError(f"Failed to get token ({resp.status}): {text}")


async def get_messages(token: str) -> list[dict[str, Any]]:
    """List messages in the inbox."""
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/messages", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("hydra:member", [])
            return []


async def get_message(token: str, msg_id: str) -> dict[str, Any]:
    """Get full message details."""
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/messages/{msg_id}", headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            raise ValueError(f"Failed to fetch message {msg_id}")


async def wait_for_otp(token: str, timeout: int = 120) -> str:
    """Poll inbox for a verification code email and extract the OTP."""
    start = asyncio.get_event_loop().time()
    seen_ids = set()
    
    while asyncio.get_event_loop().time() - start < timeout:
        msgs = await get_messages(token)
        for msg in msgs:
            msg_id = msg["id"]
            if msg_id not in seen_ids:
                seen_ids.add(msg_id)
                # Fetch full message body
                try:
                    full_msg = await get_message(token, msg_id)
                    text = full_msg.get("text", "")
                    
                    # Look for a 5 or 6 digit code
                    # Telegram usually sends like: "code: 123456"
                    match = re.search(r'\b\d{5,6}\b', text)
                    if match:
                        return match.group(0)
                except Exception as e:
                    await log.aerror("mailtm.otp_extract_error", error=str(e))
        
        await asyncio.sleep(5)
    
    raise TimeoutError("Timed out waiting for verification code email.")
