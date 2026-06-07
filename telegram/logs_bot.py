"""
Logs Bot — Secondary bot client for campaign logs.
"""

from __future__ import annotations

from typing import Optional, Any

from telethon import TelegramClient, events, Button

from core.config import get_settings
from core.logging import get_logger

log = get_logger("logs_bot")

_logs_bot: Optional[TelegramClient] = None

def get_logs_bot() -> Optional[TelegramClient]:
    """Get the active Logs Bot instance, or None if disabled."""
    return _logs_bot

async def init_logs_bot() -> None:
    """Initialize and start the logs bot if token is configured."""
    global _logs_bot
    settings = get_settings()

    if not settings.logs_bot_token:
        log.info("logs_bot.disabled", reason="No LOGS_BOT_TOKEN provided")
        return

    _logs_bot = TelegramClient(
        "lucidads_logs_bot",
        settings.api_id,
        settings.api_hash,
    )

    # Register handlers
    @_logs_bot.on(events.NewMessage(pattern="/start"))
    async def on_start(event: events.NewMessage.Event) -> None:

        from repositories import users_repo
        await users_repo.update(event.sender_id, {"has_started_logs_bot": True})
        
        from telethon.tl.types import KeyboardButtonStyle
        
        buttons = []
        
        if settings.force_join_channel:
            btn_channel = Button.url("Channel", settings.force_join_channel)
            btn_channel.style = KeyboardButtonStyle(bg_primary=True, icon=5447410659077661506)
            buttons.append(btn_channel)
            
        if settings.force_join_group:
            btn_group = Button.url("Group", settings.force_join_group)
            btn_group.style = KeyboardButtonStyle(bg_primary=True, icon=5253742260054409879)
            buttons.append(btn_group)
            
        # Group channel and group horizontally
        keyboard = [buttons] if buttons else []
            
        if settings.bot_username:
            bot_link = f"https://t.me/{settings.bot_username.strip('@')}"
            btn_bot = Button.url("Main Bot", bot_link)
            btn_bot.style = KeyboardButtonStyle(bg_success=True, icon=6147460667281511517)
            keyboard.append([btn_bot])
            
        text = (
            "<b><tg-emoji emoji-id=\"5443038326535759644\">🔒</tg-emoji> LUCID LOGS SYSTEM</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Welcome to the official Lucid Ads logging network!</b>\n\n"
            "<b><tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Real-time notifications have been successfully enabled for your account. You will now receive instantaneous logs and updates right here!</b>"
        )
        
        if settings.logs_bot_image_url:
            await event.respond(file=settings.logs_bot_image_url, message=text, buttons=keyboard, parse_mode="html")
        else:
            await event.respond(message=text, buttons=keyboard, parse_mode="html")

    @_logs_bot.on(events.CallbackQuery())
    async def on_callback(event: events.CallbackQuery.Event) -> None:
        data = event.data.decode("utf-8")
        
        if data.startswith("view_batch:"):
            _, batch_id, page_str = data.split(":")
            page = int(page_str)
            
            from cache.redis_client import get_redis
            import json
            redis = get_redis()
            batch_data = await redis.get(f"lucidads:logs_batch:{batch_id}")
            
            if not batch_data:
                await event.answer("Logs expired or not found.", alert=True)
                return
                
            logs = json.loads(batch_data)
            total = len(logs)
            per_page = 10
            total_pages = (total + per_page - 1) // per_page
            
            start_idx = page * per_page
            end_idx = start_idx + per_page
            page_logs = logs[start_idx:end_idx]
            
            text = f"📄 <b>Logs Batch</b> (Page {page + 1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            
            buttons = []
            row = []
            
            for i, log_entry in enumerate(page_logs):
                idx = start_idx + i + 1
                phone = log_entry.get("account_phone", "").lstrip("+")
                group = log_entry.get("group_id")
                link = log_entry.get("message_link")
                
                text += f"{idx}. +{phone} ➔ Group {group}\n"
                
                if link:
                    row.append(Button.url(f"Msg {idx}", link))
                    if len(row) >= 2:
                        buttons.append(row)
                        row = []
                        
            if row:
                buttons.append(row)
                
            nav_row = []
            if page > 0:
                nav_row.append(Button.inline("⬅️ Prev", f"view_batch:{batch_id}:{page - 1}"))
            if page < total_pages - 1:
                nav_row.append(Button.inline("Next ➡️", f"view_batch:{batch_id}:{page + 1}"))
                
            if nav_row:
                buttons.append(nav_row)

            try:
                await event.edit(text, buttons=buttons, parse_mode="html")
            except Exception:
                await event.answer("Already on this page.")

    await _logs_bot.start(bot_token=settings.logs_bot_token) # type: ignore
    me = await _logs_bot.get_me()
    log.info("logs_bot.started", bot_username=me.username)

async def send_campaign_start_log(owner_id: int, campaign: Any) -> None:
    """Send a notification that a campaign started with details."""
    if not _logs_bot:
        return
        
    ad_type = getattr(campaign, "ad_type", "custom")
    if ad_type == "custom":
        msg = campaign.message or "None"
        msg_disp = f"{msg[:30]}..." if len(msg) > 30 else msg
        ad_disp = f"<tg-emoji emoji-id='5395444784611480792'>📝</tg-emoji> Custom ({msg_disp})"
    else:
        ad_disp = f"🔗 Forward ({campaign.forward_link})"

    text = (
        f"🚀 <b>Campaign Started</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Campaign:</b> {campaign.name}\n"
        f"<b>Ad Mode:</b> {ad_disp}\n"
        f"<b>Intervals:</b> {campaign.group_delay_seconds}s / {campaign.round_delay_seconds}s\n"
        f"<b>Rounds:</b> {'♾️ Infinite' if campaign.max_rounds == 0 else campaign.max_rounds}\n"
        f"<b>Accounts:</b> {len(campaign.account_ids)}\n"
        f"<b>Groups:</b> {len(campaign.group_ids)}"
    )
    try:
        await _logs_bot.send_message(owner_id, text, parse_mode="html")
    except Exception as e:
        log.error("logs_bot.send_error", owner_id=owner_id, error=str(e))

async def send_campaign_pause_log(owner_id: int, campaign_name: str) -> None:
    """Send a notification that a campaign was paused."""
    if not _logs_bot:
        return
        
    text = (
        f"⏸ <b>Campaign Paused</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Campaign:</b> {campaign_name}\n\n"
        f"<i>The campaign has been stopped immediately.</i>"
    )
    try:
        await _logs_bot.send_message(owner_id, text, parse_mode="html")
    except Exception as e:
        log.error("logs_bot.send_error", owner_id=owner_id, error=str(e))

async def send_ad_success_log(owner_id: int, campaign_name: str, account_phone: str, group_id: int, message_link: str) -> None:
    """Safely queue a success log instead of instant sending."""
    if not _logs_bot:
        return
        
    from services.log_queue import add_success_log
    await add_success_log(owner_id, campaign_name, account_phone, group_id, message_link)

async def send_batch_summary(owner_id: int, campaign_name: str, batch_id: str, count: int) -> None:
    """Send the batched summary message."""
    if not _logs_bot:
        return
        
    text = (
        f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Batch Success Report</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Campaign:</b> {campaign_name}\n"
        f"<b>Successful Sends:</b> {count} (last 5s)"
    )
    
    buttons = [[Button.inline("📄 View All Logs", f"view_batch:{batch_id}:0")]]
    
    try:
        await _logs_bot.send_message(owner_id, text, buttons=buttons, parse_mode="html")
    except Exception as e:
        log.error("logs_bot.send_batch_error", owner_id=owner_id, error=str(e))
