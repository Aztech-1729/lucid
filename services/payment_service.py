import typing
from typing import Any, Callable, Coroutine, cast, Optional
import aiohttp
from core.config import get_settings
from core.logging import get_logger

log = get_logger("payment_service")

async def create_oxapay_invoice(order_id: str, amount_usd: int, user_id: int) -> str:
    """Create an OxaPay crypto payment link."""
    settings = get_settings()
    if not settings.oxapay_key:
        await log.awarning("payment_service.oxapay_missing_key")
        return "https://oxapay.com/setup-missing"

    webhook_url = settings.oxapay_webhook_url or (f"{settings.webhook_base_url}/webhook/oxapay" if settings.webhook_base_url else "")


    payload = {
        "merchant": settings.oxapay_key,
        "amount": amount_usd,
        "currency": "USD",
        "orderId": order_id,
        "description": f"Lucid Ads | UID:{user_id}",
        "lifeTime": 60,  # 60 mins
    }
    if webhook_url:
        payload["callbackUrl"] = webhook_url

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.oxapay.com/merchants/request", json=payload) as resp:
                data = await resp.json()
                if data.get("result") == 100:
                    return data.get("payLink")
                else:
                    await log.aerror("payment_service.oxapay_failed", resp=data)
                    return ""
    except Exception as e:
        await log.aerror("payment_service.oxapay_error", error=str(e))
        return ""
