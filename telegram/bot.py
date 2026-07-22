"""
Bot client initialization and event handler registration.

This is the Telegram bot entry point. It:
- Initializes the bot client
- Registers /start and callback query handlers
- Handles text input for interactive flows (session import, campaign creation)
"""

from __future__ import annotations

from telethon import TelegramClient, events

from core.config import get_settings
from core.logging import get_logger
from repositories import users_repo
from telegram import callbacks, keyboards, menus
from telegram.handlers import (
    handle_auth_phone_input,
    handle_auth_otp_input,
    handle_auth_password_input,
    handle_campaign_name_input,
    handle_duplicate_campaign_input,
    handle_account_notes_input,
    handle_autoreply_text_input,
    handle_cmp_ad_custom,
    handle_cmp_ad_forward,
    handle_cmp_int_group,
    handle_cmp_int_round,
    handle_cmp_rounds_max,
    handle_bulk_name_first,
    handle_bulk_name_last,
    handle_bulk_bio,
    handle_bulk_photo,
    handle_bulk_2fa_set,
)
from telegram.states import get_context, set_context
from utils.helpers import now_utc_naive

log = get_logger("bot")

# Module-level bot client
_bot: TelegramClient | None = None


def get_bot() -> TelegramClient:
    """Return the bot client. Raises if not initialized."""
    if _bot is None:
        raise RuntimeError("Bot not initialized. Call init_bot() first.")
    return _bot


async def init_bot() -> TelegramClient:
    """
    Initialize the Telegram bot client and register all handlers.
    """
    global _bot
    settings = get_settings()

    _bot = TelegramClient(
        "lucidads_bot",
        settings.api_id,
        settings.api_hash,
    )

    # Register handlers
    _register_handlers(_bot)

    # Connect
    await _bot.start(bot_token=settings.bot_token)  # type: ignore

    # Set bot reference in services that need it
    from services import notification_service
    notification_service.set_bot(_bot)

    me = await _bot.get_me()
    await log.ainfo("bot.started", username=me.username, id=me.id)

    return _bot


async def stop_bot() -> None:
    """Disconnect the bot client."""
    global _bot
    if _bot is not None:
        await _bot.disconnect()
        await log.ainfo("bot.stopped")
        _bot = None

async def get_missing_force_joins(event, bot) -> list[str]:
    settings = get_settings()
    if not settings.force_join_enabled:
        return []
    
    user_id = event.sender_id
    
    # Fast path: check cache
    from cache.redis_client import cache_get, cache_set
    cache_key = f"force_join:{user_id}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached.get("missing", [])

    from telethon.errors import UserNotParticipantError
    
    missing = []

    # Check channel
    if settings.force_join_channel:
        try:
            participant = await bot.get_permissions(settings.force_join_channel, user_id)
            if not participant:
                missing.append("channel")
        except Exception as e:
            if not isinstance(e, UserNotParticipantError):
                await log.aerror("force_join_channel.check_failed", error=str(e))
            missing.append("channel")

    # Check group
    if settings.force_join_group:
        try:
            participant = await bot.get_permissions(settings.force_join_group, user_id)
            if not participant:
                missing.append("group")
        except Exception as e:
            if not isinstance(e, UserNotParticipantError):
                await log.aerror("force_join_group.check_failed", error=str(e))
            missing.append("group")

    # Cache for 10 minutes (600 seconds)
    await cache_set(cache_key, {"missing": missing}, ttl=600)
    return missing

async def enforce_join(event, bot):
    settings = get_settings()
    from telethon.tl.custom import Button
    from telethon.tl.types import KeyboardButtonStyle
    buttons = []
    
    if settings.force_join_channel:
        btn1 = Button.url("Join Channel", settings.force_join_channel)
        btn1.style = KeyboardButtonStyle(bg_primary=True, icon=5447410659077661506)
        buttons.append([btn1])
    if settings.force_join_group:
        btn2 = Button.url("Join Group", settings.force_join_group)
        btn2.style = KeyboardButtonStyle(bg_primary=True, icon=5253742260054409879)
        buttons.append([btn2])
        
    btn_check = Button.inline("Joined", b"force_join_check")
    btn_check.style = KeyboardButtonStyle(bg_success=True, icon=6147460667281511517)
    buttons.append([btn_check])
    
    caption = (
        "<b><tg-emoji emoji-id=\"5420323339723881652\">🔒</tg-emoji> ACCESS DENIED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Welcome to Lucid Ads Bot!</b>\n\n"
        "<b>To unlock full access to all bot features, you must be an active member of our official community.</b>\n\n"
        "<b><tg-emoji emoji-id=\"5406745015365943482\">👇</tg-emoji> Please join the required channel and group below, then click <tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Joined to verify your account!</b>"
    )
    if settings.bot_image_url:
        await event.respond(file=settings.bot_image_url, message=caption, buttons=buttons, parse_mode="html")
    else:
        await event.respond(message=caption, buttons=buttons, parse_mode="html")


def _register_handlers(bot: TelegramClient) -> None:
    """Register all event handlers on the bot client."""

    @bot.on(events.NewMessage(pattern="/start"))
    async def on_start(event: events.NewMessage.Event) -> None:
        """Handle /start command — entry point for all users."""
        from cache.redis_client import cache_delete
        await cache_delete(f"force_join:{event.sender_id}")
        
        missing = await get_missing_force_joins(event, bot)
        if missing:
            await enforce_join(event, bot)
            return

        settings = get_settings()
        sender = await event.get_sender()
        username = getattr(sender, "username", None)

        user_id = event.sender_id

        user = await users_repo.get_or_create(
            user_id=user_id,
            username=username,
            first_name=getattr(sender, "first_name", None),
        )

        is_admin = False
        if settings.admin_user_ids and user_id in settings.admin_user_ids:
            is_admin = True
        elif settings.admin_username and username and username.lower() == settings.admin_username.lower().replace("@", ""):
            is_admin = True

        # Show Dashboard directly instead of welcome message
        from cache import dashboard_cache
        from services import dashboard_service
        
        # Try to get from cache, if not found, build it
        data = await dashboard_cache.get(user_id)
        if not data:
            data = await dashboard_service.build_dashboard(user_id)
            
        text = menus.render_dashboard(data)

        if settings.bot_image_url:
            await event.respond(
                file=settings.bot_image_url,
                message=text,
                buttons=keyboards.build_dashboard_keyboard(is_admin),
                parse_mode="html",
            )
        else:
            await event.respond(
                text,
                buttons=keyboards.build_dashboard_keyboard(is_admin),
                parse_mode="html",
            )

    @bot.on(events.NewMessage(pattern=r"(?i)^/grant"))
    async def on_grant(event: events.NewMessage.Event) -> None:
        """Handle /grant command for admin."""
        try:
            settings = get_settings()
            sender = await event.get_sender()
            is_admin = bool((event.sender_id in settings.admin_user_ids) or (getattr(sender, "username", "") and sender.username.lower() == settings.admin_username.lower().replace("@", "")))
            if not is_admin:
                return
                
            parts = event.text.split()
            if len(parts) < 3:
                await event.respond("<b>Usage:</b> <code>/grant [user_id] [weekly|monthly|yearly]</code>", parse_mode="html")
                return
                
            try:
                target_id = int(parts[1])
                plan = parts[2].upper()
            except ValueError:
                await event.respond("Invalid User ID format.")
                return
                
            days = 7 if plan == "WEEKLY" else 30 if plan == "MONTHLY" else 365 if plan == "YEARLY" else 0
            if days == 0:
                await event.respond("Invalid plan. Use weekly, monthly, or yearly.")
                return
                
            from datetime import timedelta
            ends_at = now_utc_naive() + timedelta(days=days)
            
            success = await users_repo.update(target_id, {"plan_type": plan, "subscription_ends_at": ends_at})
            if success:
                await event.respond(f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Granted {plan} plan to <code>{target_id}</code>. Expires: {ends_at.strftime('%Y-%m-%d')}", parse_mode="html")
                try:
                    price = "$10.00" if plan == "WEEKLY" else "$35.00" if plan == "MONTHLY" else "$250.00"
                    
                    caption = (
                        f"<tg-emoji emoji-id='5461151367559141950'>🎉</tg-emoji> <b>LUCID ADS PREMIUM ACTIVATED</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Your premium plan has been activated successfully.\n\n"
                        f"<b>Plan:</b> Lucid Ads Premium - {plan.capitalize()}\n"
                        f"<b>Duration:</b> {days} Days\n"
                        f"<b>Expires:</b> {ends_at.strftime('%B %d, %Y')}\n"
                        f"<b>Price:</b> {price}\n"
                        f"<b>Status:</b> <tg-emoji emoji-id='5416081784641168838'>🟢</tg-emoji> <b>PAID</b>\n\n"
                        f"<tg-emoji emoji-id='6219549292458150316'>🚀</tg-emoji> <b>Premium Features Unlocked</b>\n\n"
                        f"• Unlimited Accounts\n"
                        f"• Unlimited Campaigns\n"
                        f"• Health Monitoring & Auto Pause\n"
                        f"• Advanced Anti-Ban Delays\n"
                        f"• Auto-Join & Auto-Reply\n"
                        f"• Personal AI Assistant\n\n"
                        f"<tg-emoji emoji-id='6256032707470428424'>⚡</tg-emoji> <i>Your account is now ready to automate, scale, and optimize your Telegram marketing campaigns.</i>\n\n"
                        f"Thank you for choosing Lucid Ads Premium.\n\n"
                        f"<tg-emoji emoji-id='5424818078833715060'>🔥</tg-emoji> <b>Advertise • Grow • Succeed</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    
                    if settings.plan_image_url:
                        await event.client.send_message(target_id, message=caption, file=settings.plan_image_url, parse_mode="html")
                    else:
                        await event.client.send_message(target_id, message=caption, parse_mode="html")
                except Exception as e:
                    await event.respond(f"⚠️ Could not send notification to user: {e}")
            else:
                await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> User not found in DB.")
        except Exception as exc:
            await event.respond(f"🚨 <b>Error in /grant:</b> {exc}", parse_mode="html")

    @bot.on(events.NewMessage(pattern=r"^/revoke"))
    async def on_revoke(event: events.NewMessage.Event) -> None:
        """Handle /revoke command for admin."""
        settings = get_settings()
        sender = await event.get_sender()
        is_admin = bool((event.sender_id in settings.admin_user_ids) or (getattr(sender, "username", "") and sender.username.lower() == settings.admin_username.lower().replace("@", "")))
        if not is_admin:
            return
            
        parts = event.text.split()
        if len(parts) < 2:
            await event.respond("<b>Usage:</b> <code>/revoke [user_id]</code>", parse_mode="html")
            return
            
        try:
            target_id = int(parts[1])
        except ValueError:
            await event.respond("Invalid User ID format.")
            return
            
        success = await users_repo.update(target_id, {"plan_type": "NONE", "subscription_ends_at": None})
        if success:
            await event.respond(f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Revoked subscription for <code>{target_id}</code>.", parse_mode="html")
        else:
            await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> User not found in DB.")

    @bot.on(events.NewMessage(pattern=r"^/bd$"))
    async def on_broadcast(event: events.NewMessage.Event) -> None:
        """Handle /bd command for admin broadcasting."""
        settings = get_settings()
        sender = await event.get_sender()
        sender_username = getattr(sender, "username", "")
        
        # Check if user is admin
        is_admin = False
        if event.sender_id in settings.admin_user_ids:
            is_admin = True
        elif sender_username and f"@{sender_username.lower()}" == settings.admin_username.lower():
            is_admin = True
            
        if not is_admin:
            return
            
        if not event.is_reply:
            await event.reply("<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> Please reply to a message with /bd to broadcast it.")
            return
            
        reply_msg = await event.get_reply_message()
        if not reply_msg:
            return
            
        status_msg = await event.reply("🚀 <b>Starting broadcast...</b>", parse_mode="html")
        
        async def run_broadcast():
            active_users = await users_repo.get_all_active_user_ids()
            success_count = 0
            fail_count = 0
            import asyncio
            
            for uid in active_users:
                try:
                    await bot.send_message(uid, reply_msg)
                    success_count += 1
                except Exception:
                    fail_count += 1
                await asyncio.sleep(0.05) # Prevent global flood limit
                
            await status_msg.edit(
                f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Broadcast Complete!</b>\n\n"
                f"🎯 <b>Successfully sent to:</b> {success_count} users\n"
                f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> <b>Failed:</b> {fail_count} users", 
                parse_mode="html"
            )

        import asyncio
        asyncio.create_task(run_broadcast())

    # Per-user button spam throttle (in-memory, no Redis overhead)
    import time as _time
    _button_cooldowns: dict[int, float] = {}
    _BUTTON_COOLDOWN_SECS = 1.5

    @bot.on(events.CallbackQuery)
    async def on_callback(event: events.CallbackQuery.Event) -> None:
        """Handle all inline button presses."""
        
        # ── Anti-spam throttle ──────────────────────────────────
        now = _time.monotonic()
        last_press = _button_cooldowns.get(event.sender_id, 0.0)
        if now - last_press < _BUTTON_COOLDOWN_SECS:
            await event.answer("⏳ Please slow down! Wait a moment...", alert=False)
            return
        _button_cooldowns[event.sender_id] = now
        # ────────────────────────────────────────────────────────
        
        if event.data == b"force_join_check":
            from cache.redis_client import cache_delete
            await cache_delete(f"force_join:{event.sender_id}")
            
            missing = await get_missing_force_joins(event, bot)
            if not missing:
                await event.delete()
                # Show dashboard directly (no mock needed)
                sender = await event.get_sender()
                username = getattr(sender, "username", None)
                await users_repo.get_or_create(
                    user_id=event.sender_id,
                    username=username,
                    first_name=getattr(sender, "first_name", None),
                )
                from cache import dashboard_cache
                from services import dashboard_service
                data = await dashboard_cache.get(event.sender_id)
                if not data:
                    data = await dashboard_service.build_dashboard(event.sender_id)
                text = menus.render_dashboard(data)
                settings = get_settings()
                if settings.bot_image_url:
                    await event.respond(file=settings.bot_image_url, message=text, buttons=keyboards.main_menu_keyboard(), parse_mode="html")
                else:
                    await event.respond(text, buttons=keyboards.main_menu_keyboard(), parse_mode="html")
            else:
                if len(missing) == 2:
                    msg = "❌ You haven't joined the channel and group yet!"
                elif missing[0] == "channel":
                    msg = "❌ You haven't joined the channel yet!"
                else:
                    msg = "❌ You haven't joined the group yet!"
                await event.answer(msg, alert=True)
            return

        missing_any = await get_missing_force_joins(event, bot)
        if missing_any:
            await event.answer("🔒 You must join the required community first!", alert=True)
            await enforce_join(event, bot)
            return

        try:
            await callbacks.route_callback(event)
        except Exception as exc:
            from telethon.errors import MessageNotModifiedError
            from telethon.errors.rpcerrorlist import QueryIdInvalidError, FloodWaitError
            if isinstance(exc, (MessageNotModifiedError, QueryIdInvalidError)):
                return
            if isinstance(exc, FloodWaitError):
                try:
                    await event.answer("Too many requests! Please type /start to get a fresh menu.", alert=True)
                except Exception:
                    pass
                return
                
            await log.aerror(
                "callback.error",
                user_id=event.sender_id,
                data=event.data,
                error=str(exc),
            )
            try:
                await event.answer("An error occurred. Please try again.", alert=True)
            except Exception:
                pass

    @bot.on(events.NewMessage(func=lambda e: e.is_private))
    async def on_user_message(event: events.NewMessage.Event) -> None:
        """Central message handler for private chats."""

        if event.text and event.text.startswith("/"):
            # Command handled by other handlers
            return

        missing = await get_missing_force_joins(event, bot)
        if missing:
            await enforce_join(event, bot)
            return

        user_id = event.sender_id
        awaiting = await get_context(user_id, "awaiting_input")

        # Interactive Handlers (Phone, OTP, etc.)

        # Handle Session Upload
        if awaiting == "session_upload" and event.document:
            filename = event.document.attributes[0].file_name
            if not (filename.lower().endswith(".session") or filename.lower().endswith(".zip")):
                await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Please send a <b>.session</b> file or a <b>.zip</b> archive.", parse_mode="html")
                return

            # Download file
            file_bytes = await event.download_media(bytes)
            
            # Progress message
            progress_msg = await event.respond(
                "📂 <b>SESSIONS IMPORT</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "⏳ <b>Status: Importing Sessions</b>\n\n"
                "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Added: 0</b>\n"
                "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> <b>Failed: 0</b>\n"
                "<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Total Found: 0</b>",
                parse_mode="html"
            )

            # Define update callback
            async def update_progress(joined, failed, total, status="Importing Sessions"):
                try:
                    text = (
                        f"📂 <b>SESSIONS IMPORT</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"⏳ <b>Status: {status}</b>\n\n"
                        f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Added: {joined}</b>\n"
                        f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> <b>Failed: {failed}</b>\n"
                        f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Total Found: {total}</b>"
                    )
                    await progress_msg.edit(text, parse_mode="html")
                except Exception:
                    pass

            from services.session_importer import import_from_file
            await import_from_file(user_id, file_bytes, filename, update_progress)
            return

        if not awaiting:
            return

        if awaiting == "ai_chat" and event.text:
            from services.ai_service import chat_with_ai
            from telegram import menus, keyboards
            
            # Show typing...
            msg = await event.respond("<tg-emoji emoji-id='5291969869875522399'>⏳</tg-emoji> <i>Thinking...</i>", parse_mode="html")
            
            # Call AI
            response = await chat_with_ai(user_id, event.text)
            
            # Check if AI proposed an action
            if isinstance(response, str) and response.startswith("{") and "_action_request" in response:
                from services.ai_action_queue import enqueue_action
                action_id = await enqueue_action(user_id, response)
                if action_id:
                    action_data = __import__('json').loads(response)
                    text = menus.render_ai_action(action_data.get("description", "Unknown Action"))
                    await msg.edit(text, buttons=keyboards.ai_action_keyboard(action_id), parse_mode="html")
                else:
                    await msg.edit("<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> Failed to enqueue action.", parse_mode="html")
            else:
                # Normal chat response
                text = f"<tg-emoji emoji-id='6256032707470428424'>🤖</tg-emoji> <b>AI:</b>\n\n{response}"
                await msg.edit(text, buttons=keyboards.ai_chat_keyboard(), parse_mode="html")
                
            return

        if awaiting == "bulk_autojoin":
            from services import group_worker
            
            # Handle Folder Link
            if event.text and "t.me/addlist/" in event.text:
                slug = event.text.strip().split("t.me/addlist/")[-1].split("?")[0].strip()
                await set_context(user_id, "awaiting_input", None)
                
                msg = await event.respond("⏳ <b>Processing Folder Link...</b>", parse_mode="html")
                
                async def update_progress_folder(text: str):
                    try:
                        await msg.edit(text, parse_mode="html")
                    except: pass
                
                import asyncio
                asyncio.create_task(group_worker.bulk_join_folder(user_id, slug, update_progress_folder))
                return
            
            # Handle TXT File
            elif event.document:
                filename = event.document.attributes[0].file_name if event.document.attributes else ""
                if not filename.lower().endswith(".txt"):
                    await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Please send a <b>.txt</b> file.", parse_mode="html")
                    return
                
                file_bytes = await event.download_media(bytes)
                try:
                    content = file_bytes.decode("utf-8")
                    links = [line.strip() for line in content.split("\n") if line.strip()]
                except:
                    await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Invalid file encoding. Must be UTF-8 txt.")
                    return
                
                if not links:
                    await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> No links found in the file.")
                    return
                    
                await set_context(user_id, "awaiting_input", None)
                msg = await event.respond(f"⏳ <b>Processing {len(links)} links from file...</b>", parse_mode="html")
                
                async def update_progress_links(text: str):
                    try:
                        await msg.edit(text, parse_mode="html")
                    except: pass
                
                import asyncio
                asyncio.create_task(group_worker.bulk_join_links(user_id, links, update_progress_links))
                return
            else:
                await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Please send a <b>.txt file</b> or a <b>t.me/addlist/</b> link.", parse_mode="html")
                return

        # Interactive Handlers (Phone, OTP, etc.)
        try:
            if awaiting == "auth_phone":
                await handle_auth_phone_input(event)
            elif awaiting == "auth_otp":
                await handle_auth_otp_input(event)
            elif awaiting == "auth_password":
                await handle_auth_password_input(event)
            elif awaiting == "campaign_name":
                await handle_campaign_name_input(event)
            elif awaiting == "duplicate_campaign":
                await handle_duplicate_campaign_input(event)
            elif awaiting == "account_notes":
                await handle_account_notes_input(event)
            elif awaiting == "autoreply_text":
                await handle_autoreply_text_input(event)
            elif awaiting.startswith("cmp_ad_custom:"):
                await handle_cmp_ad_custom(event, awaiting.split(":")[1])
            elif awaiting.startswith("cmp_ad_forward:"):
                await handle_cmp_ad_forward(event, awaiting.split(":")[1])
            elif awaiting.startswith("cmp_int_group:"):
                await handle_cmp_int_group(event, awaiting.split(":")[1])
            elif awaiting.startswith("cmp_int_round:"):
                await handle_cmp_int_round(event, awaiting.split(":")[1])
            elif awaiting.startswith("cmp_rounds_max:"):
                await handle_cmp_rounds_max(event, awaiting.split(":")[1])
            elif awaiting == "bulk_name_first":
                await handle_bulk_name_first(event)
            elif awaiting == "bulk_name_last":
                await handle_bulk_name_last(event)
            elif awaiting == "bulk_bio":
                await handle_bulk_bio(event)
            elif awaiting == "bulk_photo":
                await handle_bulk_photo(event)
            elif awaiting == "bulk_2fa_set":
                await handle_bulk_2fa_set(event)
        except Exception as exc:
            await event.respond(f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Error: {str(exc)}", parse_mode="html")
            await set_context(user_id, "awaiting_input", None)


    @bot.on(events.NewMessage(pattern="/stats"))
    async def on_stats(event: events.NewMessage.Event) -> None:
        """Display internal stats (admin only)."""
        user_id = event.sender_id
        settings = get_settings()

        user = await users_repo.get(user_id)
        if not (user and user.is_admin) and user_id not in settings.admin_user_ids:
            return

        from telegram.client_pool import client_pool
        from utils.metrics import metrics
        m = await metrics.stats()
        pool = await client_pool.stats()

        lines = ["<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>System Stats</b>\n"]
        for k, v in m.items():
            lines.append(f"  {k}: <b>{v}</b>")
        lines.append("\n🔌 <b>Client Pool</b>")
        lines.append(f"  Total: <b>{pool['total_clients']}</b>/{pool['max_clients']}")
        lines.append(f"  Active: <b>{pool['active_borrows']}</b>")
        lines.append(f"  Idle: <b>{pool['idle_clients']}</b>")

        await event.respond("\n".join(lines), parse_mode="html")







