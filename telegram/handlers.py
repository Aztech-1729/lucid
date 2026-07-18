"""
Text input handlers for interactive bot flows.

Extracted from bot.py to keep module sizes under 800 lines.
Handles: phone auth OTP, campaign creation, bulk actions, session uploads.
"""

from __future__ import annotations

from telethon import events
from telethon.events import NewMessage

from core.constants import CB
from core.logging import get_logger
from telegram.states import get_context, set_context

log = get_logger("handlers")


async def handle_auth_phone_input(event: events.NewMessage.Event) -> None:
    """Handle phone number input for auth."""
    phone = event.text.strip()
    if not phone.startswith("+") or len(phone) < 8:
        await event.respond(
            "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Invalid phone number. "
            "It must start with '+' and include the country code.")
        await set_context(event.sender_id, "awaiting_input", None)
        return

    msg = await event.respond("⏳ Requesting OTP from Telegram... Please wait.")

    from services import auth_service
    try:
        await auth_service.start_auth(event.sender_id, phone)
        await set_context(event.sender_id, "awaiting_input", "auth_otp")
        await msg.edit(
            f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> OTP requested for <b>{phone}</b>.\n\n"
            f"Please send the <b>5-digit code</b> you received in the Telegram app.\n"
            f"<i>You have 5 minutes to enter it.</i>",
            parse_mode="html")
    except Exception as exc:
        await set_context(event.sender_id, "awaiting_input", None)
        await msg.edit(
            f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Failed to request code: {str(exc)}",
            parse_mode="html")


async def handle_auth_otp_input(event: events.NewMessage.Event) -> None:
    """Handle OTP input for auth."""
    otp = event.text.strip()
    otp = ''.join(c for c in otp if c.isdigit())

    msg = await event.respond("⏳ Verifying OTP...")
    from services import auth_service

    try:
        status = await auth_service.submit_otp(event.sender_id, otp)
        if status == "needs_password":
            await set_context(event.sender_id, "awaiting_input", "auth_password")
            await msg.edit(
                "🔐 <b>2FA Enabled</b>\n\nPlease send your Two-Step Verification password.",
                parse_mode="html")
            return

        summary = await auth_service.finalize_auth(event.sender_id)
        from services import account_service
        account = await account_service.add_account(event.sender_id, summary["raw_session"])

        from repositories import account_groups_repo
        await account_groups_repo.save_groups(str(account.id), summary["groups"])

        await set_context(event.sender_id, "awaiting_input", None)
        await msg.edit(
            f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Account Added Successfully!</b>\n\n"
            f"<tg-emoji emoji-id='5461117441612462242'>👤</tg-emoji> Name: <b>{summary['name']}</b>\n"
            f"🔗 Username: <b>{summary['username']}</b>\n"
            f"<tg-emoji emoji-id='5395444784611480792'>📝</tg-emoji> Bio: <i>{summary['bio']}</i>\n"
            f"👥 Total Groups: <b>{summary['groups_count']}</b>",
            parse_mode="html")
    except Exception as exc:
        await set_context(event.sender_id, "awaiting_input", None)
        await msg.edit(
            f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> OTP verification failed: {str(exc)}",
            parse_mode="html")

    try:
        await event.delete()
    except Exception:
        pass


async def handle_auth_password_input(event: events.NewMessage.Event) -> None:
    """Handle 2FA password input for auth."""
    password = event.text.strip()
    msg = await event.respond("⏳ Verifying Password...")
    from services import auth_service

    try:
        await auth_service.submit_password(event.sender_id, password)
        summary = await auth_service.finalize_auth(event.sender_id)
        from services import account_service
        account = await account_service.add_account(event.sender_id, summary["raw_session"])

        from repositories import account_groups_repo
        await account_groups_repo.save_groups(str(account.id), summary["groups"])

        await set_context(event.sender_id, "awaiting_input", None)
        await msg.edit(
            f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Account Added Successfully!</b>\n\n"
            f"<tg-emoji emoji-id='5461117441612462242'>👤</tg-emoji> Name: <b>{summary['name']}</b>\n"
            f"🔗 Username: <b>{summary['username']}</b>\n"
            f"<tg-emoji emoji-id='5395444784611480792'>📝</tg-emoji> Bio: <i>{summary['bio']}</i>\n"
            f"👥 Total Groups: <b>{summary['groups_count']}</b>",
            parse_mode="html")
    except Exception as exc:
        await set_context(event.sender_id, "awaiting_input", None)
        await msg.edit(
            f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Password verification failed: {str(exc)}",
            parse_mode="html")

    try:
        await event.delete()
    except Exception:
        pass


async def handle_campaign_name_input(event: events.NewMessage.Event) -> None:
    """Handle campaign name input."""
    name = event.text.strip()

    from services import campaign_service
    try:
        campaign = await campaign_service.create_campaign(
            owner_id=event.sender_id,
            name=name,
            message="",
        )
        await set_context(event.sender_id, "awaiting_input", None)

        from cache import campaign_cache
        from telegram.menus import render_campaign_detail
        from telegram.keyboards import campaign_detail_keyboard
        from core.config import get_settings

        data = campaign.model_dump(mode="json")
        data["account_count"] = len(campaign.account_ids)
        data["group_count"] = len(campaign.group_ids)
        data["success_count"] = 0
        data["failure_count"] = 0

        await campaign_cache.set_summary(str(campaign.id), data)

        text = render_campaign_detail(data)
        buttons = campaign_detail_keyboard(str(campaign.id), campaign.status)

        settings = get_settings()
        if settings.bot_image_url:
            await event.respond(file=settings.bot_image_url, message=text, buttons=buttons, parse_mode="html")
        else:
            await event.respond(text, buttons=buttons, parse_mode="html")

    except Exception as exc:
        await event.respond(
            f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> {str(exc)}",
            parse_mode="html")


async def handle_duplicate_campaign_input(event: events.NewMessage.Event) -> None:
    """Handle campaign duplication name input."""
    from services import campaign_service

    new_name = event.text.strip()
    source_id = await get_context(event.sender_id, "duplicate_source")

    if not source_id:
        await event.respond(
            "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Source campaign not found. Please try again.")
        return

    try:
        new_campaign = await campaign_service.duplicate_campaign(
            campaign_id=source_id,
            owner_id=event.sender_id,
            new_name=new_name,
        )
        await set_context(event.sender_id, "awaiting_input", None)
        await event.respond(
            f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Campaign duplicated as <b>{new_campaign.name}</b>!",
            parse_mode="html")
    except Exception as exc:
        await event.respond(
            f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Error: {str(exc)}",
            parse_mode="html")


async def handle_account_notes_input(event: events.NewMessage.Event) -> None:
    """Handle account notes input."""
    from services import account_service

    notes = event.text.strip()
    account_id = await get_context(event.sender_id, "notes_account_id")

    if not account_id:
        await event.respond(
            "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Account not found. Please try again.")
        return

    try:
        await account_service.update_notes(account_id, event.sender_id, notes)
        await set_context(event.sender_id, "awaiting_input", None)
        await event.respond(
            "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Notes updated!",
            parse_mode="html")
    except Exception as exc:
        await event.respond(
            f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Error: {str(exc)}",
            parse_mode="html")


async def handle_autoreply_text_input(event: events.NewMessage.Event) -> None:
    """Handle custom auto-reply message input."""
    text = event.text.strip()

    try:
        from repositories import users_repo
        await users_repo.update(event.sender_id, {"autoreply_text": text})
        await set_context(event.sender_id, "awaiting_input", None)

        from telegram import keyboards
        await event.respond(
            f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Custom auto-reply message saved!</b>\n\n"
            f"<code>{text}</code>",
            parse_mode="html",
            buttons=keyboards.back_keyboard(CB.SETTINGS_AUTOREPLY))
    except Exception as exc:
        await event.respond(
            f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Error saving message: {str(exc)}",
            parse_mode="html")


async def handle_cmp_ad_custom(event, campaign_id: str):
    from services import campaign_service
    from telegram.menus import render_campaign_detail
    from telegram.keyboards import campaign_detail_keyboard
    from cache import campaign_cache

    await campaign_service.update_campaign(campaign_id, ad_type="custom", message=event.text.strip(), forward_link=None)
    await set_context(event.sender_id, "awaiting_input", None)

    await event.respond("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Custom message saved!</b>", parse_mode="html")

    from workers.cache_worker import warm_user_cache
    await warm_user_cache(event.sender_id)
    data = await campaign_cache.get_summary(campaign_id)
    text = render_campaign_detail(data)
    buttons = campaign_detail_keyboard(campaign_id, data.get("status", "UNKNOWN") if data else "UNKNOWN")
    await event.respond(text, buttons=buttons, parse_mode="html")


async def handle_cmp_ad_forward(event, campaign_id: str):
    from services import campaign_service
    from telegram.menus import render_campaign_detail
    from telegram.keyboards import campaign_detail_keyboard
    from cache import campaign_cache

    await campaign_service.update_campaign(campaign_id, ad_type="forward", forward_link=event.text.strip())
    await set_context(event.sender_id, "awaiting_input", None)

    await event.respond("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Forward link saved!</b>", parse_mode="html")

    from workers.cache_worker import warm_user_cache
    await warm_user_cache(event.sender_id)
    data = await campaign_cache.get_summary(campaign_id)
    text = render_campaign_detail(data)
    buttons = campaign_detail_keyboard(campaign_id, data.get("status", "UNKNOWN") if data else "UNKNOWN")
    await event.respond(text, buttons=buttons, parse_mode="html")


async def handle_cmp_int_group(event, campaign_id: str):
    from services import campaign_service
    from telegram.menus import render_campaign_detail
    from telegram.keyboards import campaign_detail_keyboard
    from cache import campaign_cache
    try:
        val = int(event.text.strip())
        await campaign_service.update_campaign(campaign_id, group_delay_seconds=val)
        await set_context(event.sender_id, "awaiting_input", None)
        await event.respond("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Group delay saved!</b>", parse_mode="html")

        from workers.cache_worker import warm_user_cache
        await warm_user_cache(event.sender_id)
        data = await campaign_cache.get_summary(campaign_id)
        text = render_campaign_detail(data)
        buttons = campaign_detail_keyboard(campaign_id, data.get("status", "UNKNOWN") if data else "UNKNOWN")
        await event.respond(text, buttons=buttons, parse_mode="html")
    except ValueError:
        await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Invalid number. Try again.")


async def handle_cmp_int_round(event, campaign_id: str):
    from services import campaign_service
    from telegram.menus import render_campaign_detail
    from telegram.keyboards import campaign_detail_keyboard
    from cache import campaign_cache
    try:
        val = int(event.text.strip())
        await campaign_service.update_campaign(campaign_id, round_delay_seconds=val)
        await set_context(event.sender_id, "awaiting_input", None)
        await event.respond("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Round delay saved!</b>", parse_mode="html")

        from workers.cache_worker import warm_user_cache
        await warm_user_cache(event.sender_id)
        data = await campaign_cache.get_summary(campaign_id)
        text = render_campaign_detail(data)
        buttons = campaign_detail_keyboard(campaign_id, data.get("status", "UNKNOWN") if data else "UNKNOWN")
        await event.respond(text, buttons=buttons, parse_mode="html")
    except ValueError:
        await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Invalid number. Try again.")


async def handle_cmp_rounds_max(event, campaign_id: str):
    from services import campaign_service
    from telegram.menus import render_campaign_detail
    from telegram.keyboards import campaign_detail_keyboard
    from cache import campaign_cache
    try:
        val = int(event.text.strip())
        await campaign_service.update_campaign(campaign_id, max_rounds=val)
        await set_context(event.sender_id, "awaiting_input", None)
        await event.respond("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>Max rounds saved!</b>", parse_mode="html")

        from workers.cache_worker import warm_user_cache
        await warm_user_cache(event.sender_id)
        data = await campaign_cache.get_summary(campaign_id)
        text = render_campaign_detail(data)
        buttons = campaign_detail_keyboard(campaign_id, data.get("status", "UNKNOWN") if data else "UNKNOWN")
        await event.respond(text, buttons=buttons, parse_mode="html")
    except ValueError:
        await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Invalid number. Try again.")


async def handle_bulk_name_first(event: events.NewMessage.Event) -> None:
    text = event.text.strip()
    await set_context(event.sender_id, "bulk_first_name", text)
    await set_context(event.sender_id, "awaiting_input", "bulk_name_last")
    from telegram.keyboards import back_keyboard
    await event.respond(
        f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> First name set to: <b>{text}</b>\n\n"
        f"Now, please send the <b>new Last Name</b> for all accounts.\n"
        f"<i>(Send a dot `.` or space to leave it blank)</i>",
        buttons=back_keyboard(CB.BULK_MANAGER), parse_mode="html")


async def handle_bulk_name_last(event: events.NewMessage.Event) -> None:
    last_name = event.text.strip()
    if last_name == "." or not last_name:
        last_name = ""

    first_name = await get_context(event.sender_id, "bulk_first_name")

    from telegram.menus import render_bulk_progress
    from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
    msg = await event.respond(render_bulk_progress("Change Name", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
    from services import bulk_service

    async def run_task():
        async def update_progress(success, failed, total):
            try:
                await msg.edit(render_bulk_progress("Change Name", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
            except Exception:
                pass
        success, failed = await bulk_service.bulk_update_profile(event.sender_id, first_name=first_name, last_name=last_name, progress_callback=update_progress)
        try:
            await msg.edit(render_bulk_progress("Change Name", success, failed, success + failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
        except Exception:
            pass

    import asyncio
    asyncio.create_task(run_task())
    await set_context(event.sender_id, "awaiting_input", None)


async def handle_bulk_bio(event: events.NewMessage.Event) -> None:
    text = event.text.strip()
    if len(text) > 70:
        await event.respond(
            "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> <b>Bio too long!</b>\n"
            "Telegram only allows a maximum of 70 characters.\n\nPlease send a shorter one.",
            parse_mode="html")
        return

    from telegram.menus import render_bulk_progress
    from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
    msg = await event.respond(render_bulk_progress("Change Bio", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
    from services import bulk_service

    async def run_task():
        async def update_progress(success, failed, total):
            try:
                await msg.edit(render_bulk_progress("Change Bio", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
            except Exception:
                pass
        success, failed = await bulk_service.bulk_update_profile(event.sender_id, about=text, progress_callback=update_progress)
        try:
            await msg.edit(render_bulk_progress("Change Bio", success, failed, success + failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
        except Exception:
            pass

    import asyncio
    asyncio.create_task(run_task())
    await set_context(event.sender_id, "awaiting_input", None)


async def handle_bulk_photo(event: events.NewMessage.Event) -> None:
    if not event.photo:
        await event.respond("<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Please send a photo.")
        return

    msg = await event.respond("Downloading photo... ⏳")
    import os
    import uuid
    filename = f"temp_photo_{uuid.uuid4().hex}.jpg"
    await event.download_media(file=filename)

    from telegram.menus import render_bulk_progress
    from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
    await msg.edit(render_bulk_progress("Change Photo", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
    from services import bulk_service

    async def run_task():
        async def update_progress(success, failed, total):
            try:
                await msg.edit(render_bulk_progress("Change Photo", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
            except Exception:
                pass
        success, failed = await bulk_service.bulk_upload_profile_photo(event.sender_id, filename, progress_callback=update_progress)
        if os.path.exists(filename):
            os.remove(filename)
        try:
            await msg.edit(render_bulk_progress("Change Photo", success, failed, success + failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
        except Exception:
            pass

    import asyncio
    asyncio.create_task(run_task())
    await set_context(event.sender_id, "awaiting_input", None)


async def handle_bulk_2fa_set(event: events.NewMessage.Event) -> None:
    text = event.text.strip()
    from telegram.menus import render_bulk_progress
    from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
    msg = await event.respond(render_bulk_progress("Set 2FA", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
    from services import bulk_service

    async def run_task():
        async def update_progress(success, failed, total):
            try:
                await msg.edit(render_bulk_progress("Set 2FA", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
            except Exception:
                pass
        success, failed = await bulk_service.bulk_manage_2fa(event.sender_id, text, progress_callback=update_progress)
        try:
            await msg.edit(render_bulk_progress("Set 2FA", success, failed, success + failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
        except Exception:
            pass

    import asyncio
    asyncio.create_task(run_task())
    await set_context(event.sender_id, "awaiting_input", None)
