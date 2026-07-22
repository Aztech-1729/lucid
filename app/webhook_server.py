from aiohttp import web
from core.logging import get_logger
from repositories.invoice_repo import invoice_repo
from repositories import users_repo
from utils.helpers import now_utc_naive
from datetime import timedelta

log = get_logger("webhook_server")

async def handle_zapupi_webhook(request: web.Request) -> web.Response:
    """Handle ZapUPI payment callbacks."""
    try:
        data = await request.json()
        order_id = data.get("order_id")
        status = data.get("status")
        
        await log.ainfo("webhook.zapupi.received", order_id=order_id, status=status)
        
        if status == "Success":
            await process_successful_payment(order_id)
            
        return web.json_response({"status": "ok"})
    except Exception as e:
        await log.aerror("webhook.zapupi.error", error=str(e))
        return web.Response(status=500)

async def handle_oxapay_webhook(request: web.Request) -> web.Response:
    """Handle OxaPay payment callbacks."""
    try:
        data = await request.json()
        order_id = data.get("orderId")
        status = data.get("status")
        
        await log.ainfo("webhook.oxapay.received", order_id=order_id, status=status)
        
        if status == "Paid":
            await process_successful_payment(order_id)
            
        return web.json_response({"status": "ok"})
    except Exception as e:
        await log.aerror("webhook.oxapay.error", error=str(e))
        return web.Response(status=500)


async def process_successful_payment(order_id: str) -> None:
    """Update invoice and user plan after payment is confirmed."""
    inv = await invoice_repo.get_by_order_id(order_id)
    if not inv:
        await log.awarning("payment.invoice_not_found", order_id=order_id)
        return
        
    if inv.status == "paid":
        return  # already processed

    await invoice_repo.update_status(order_id, "paid")
    
    # Upgrade User Plan
    days = 7 if inv.plan == "WEEKLY" else 30
    ends_at = now_utc_naive() + timedelta(days=days)
    
    success = await users_repo.update(inv.user_id, {"plan_type": inv.plan, "subscription_ends_at": ends_at})
    if success:
        await log.ainfo("payment.user_upgraded", user_id=inv.user_id, plan=inv.plan)
        # Notify the user
        from telegram.bot import get_bot
        try:
            bot = get_bot()
            text = (
                f"🎉 <b>PAYMENT SUCCESSFUL</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ Your <b>{inv.plan.capitalize()} Pass</b> has been activated!\n"
                f"It is valid until {ends_at.strftime('%Y-%m-%d')}."
            )
            await bot.send_message(inv.user_id, text, parse_mode="html")
        except Exception as e:
            await log.aerror("payment.notify_failed", error=str(e))
    else:
        await log.aerror("payment.user_update_failed", user_id=inv.user_id)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post('/webhook/zapupi', handle_zapupi_webhook)
    app.router.add_post('/webhook/oxapay', handle_oxapay_webhook)
    return app

async def start_webhook_server(host: str = "0.0.0.0", port: int = 8080) -> web.AppRunner:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    await log.ainfo("webhook.server_started", host=host, port=port)
    return runner
