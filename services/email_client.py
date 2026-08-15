import asyncio
import re
from typing import Any, Optional
from core.logging import get_logger

log = get_logger("email_client")

def _create_email_sync() -> str:
    """Synchronously create a new gmail alias using temp-gmail."""
    from temp_gmail import GMail
    g = GMail()
    return g.create_email()

async def create_account() -> str:
    """Create a new @gmail.com alias. Returns the email address."""
    return await asyncio.to_thread(_create_email_sync)

def _get_messages_sync(address: str) -> list[dict[str, Any]]:
    """Synchronously get messages for an address."""
    from temp_gmail import GMail
    g = GMail()
    g.email = address
    data = g.load_list()
    return data.get("messageData", [])

async def get_messages(address: str) -> list[dict[str, Any]]:
    """List messages in the inbox."""
    return await asyncio.to_thread(_get_messages_sync, address)

def _get_message_sync(address: str, msg_id: str) -> str:
    """Synchronously get full message body."""
    from temp_gmail import GMail
    g = GMail()
    g.email = address
    return g.load_item(msg_id)

async def get_message(address: str, msg_id: str) -> str:
    """Get full message details (HTML/Text body)."""
    return await asyncio.to_thread(_get_message_sync, address, msg_id)

async def wait_for_otp(address: str, timeout: int = 120) -> str:
    """Poll inbox for a verification code email and extract the OTP."""
    start = asyncio.get_event_loop().time()
    seen_ids = set()
    
    while asyncio.get_event_loop().time() - start < timeout:
        try:
            msgs = await get_messages(address)
            for msg in msgs:
                msg_id = msg["messageID"]
                if msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    # Fetch full message body
                    try:
                        text = await get_message(address, msg_id)
                        
                        # Look for a 5 or 6 digit code
                        match = re.search(r'\b\d{5,6}\b', text)
                        if match:
                            return match.group(0)
                    except Exception as e:
                        await log.aerror("email_client.otp_extract_error", error=str(e))
        except Exception as e:
            await log.awarning("email_client.fetch_error", error=str(e))
            
        await asyncio.sleep(5)
    
    raise TimeoutError("Timed out waiting for verification code email.")
