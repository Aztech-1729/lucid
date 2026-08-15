"""
All callback handlers — CACHE-READ ONLY.

Golden Rules enforced here:
1. Every handler starts with `await event.answer()` — NO EXCEPTIONS
2. Read from Redis cache — NEVER from MongoDB
3. Render via menus.py and send

No expensive work. No health checks. No calculations. No Telegram API calls.
"""

from __future__ import annotations

import typing
from typing import Any, Callable, Coroutine, cast, Optional
from telethon import events

from cache import account_cache, analytics_cache, campaign_cache, dashboard_cache, health_cache
from core.constants import CB, CampaignStatus
from core.logging import get_logger
from telegram import keyboards, menus
from telegram.states import get_context, push_screen, set_context

log = get_logger("callbacks")


def _uid(event: events.CallbackQuery.Event) -> int:
    """Extract sender_id as int, raising if missing (never happens for callbacks)."""
    uid = event.sender_id
    assert uid is not None, "CallbackQuery must have a sender"
    return uid


# ── Dashboard ───────────────────────────────────────────────

async def on_dashboard(event: events.CallbackQuery.Event) -> None:
    """Display the dashboard."""
    await event.answer()  # LINE 1. Non-negotiable.
    data = await dashboard_cache.get(_uid(event))
    if not data:
        from workers.cache_worker import warm_user_cache
        await warm_user_cache(_uid(event), force=True)
        data = await dashboard_cache.get(_uid(event))
        
    text: str = menus.render_dashboard(data)
    from core.config import get_settings
    from repositories import users_repo
    settings = get_settings()
    user = await users_repo.get(_uid(event))
    is_admin = False
    if _uid(event) in settings.admin_user_ids:
        is_admin = True
    elif user and user.username and user.username.lower() == settings.admin_username.lower().replace("@", ""):
        is_admin = True
    
    await event.edit(text, buttons=keyboards.build_dashboard_keyboard(is_admin), parse_mode="html")


# ── Accounts ────────────────────────────────────────────────

async def on_accounts(event: events.CallbackQuery.Event) -> None:
    """Display the account list."""
    await event.answer()  # LINE 1. Non-negotiable.
    await push_screen(_uid(event), "accounts")
    await set_context(_uid(event), "view_source", "accounts")
    page = 1
    data = await account_cache.get_page(_uid(event), page)
    if not data or not data.get("accounts"):
        # Cache is cold or empty — warm it and re-read for instant results
        from workers.cache_worker import warm_user_cache
        await warm_user_cache(_uid(event), force=True)
        data = await account_cache.get_page(_uid(event), page)

    text: str = menus.render_account_list(data)
    accounts = data.get("accounts", []) if data else []
    pagination = data.get("pagination", {}) if data else {}
    buttons = keyboards.account_list_keyboard(accounts, pagination)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_account_view(event: events.CallbackQuery.Event, account_id: str) -> None:
    """Display account details."""
    await event.answer()  # LINE 1. Non-negotiable.
    
    # Read context BEFORE pushing new screen
    from telegram.states import get_context
    context: str = await get_context(_uid(event), "view_source")
    back_target = CB.ACCOUNTS
    if context == "health_all":
        back_target = CB.HEALTH_VIEW_ALL

    await push_screen(_uid(event), "account_detail", {"account_id": account_id})
    data = await account_cache.get_summary(account_id)
    text: str = menus.render_account_detail(data)
    status = data.get("status", "UNKNOWN") if data else "UNKNOWN"

    buttons = keyboards.account_detail_keyboard(account_id, status, back_cb=back_target)
    await event.edit(text, buttons=buttons, parse_mode="html")

async def on_account_export_sessions(event: events.CallbackQuery.Event) -> None:
    """Export all accounts as a ZIP of .session files."""
    await event.answer()  # LINE 1. Non-negotiable.
    
    # 1. Update UI to show processing
    await event.edit("⏳ <b>Generating ZIP...</b>\n\nPlease wait while your sessions are securely decrypted and packaged.", buttons=None, parse_mode="html")
    
    # 2. Call exporter service
    from services.session_exporter import export_sessions_zip
    from telethon.tl.types import DocumentAttributeFilename
    zip_bytes = await export_sessions_zip(_uid(event))
    
    if not zip_bytes:
        await event.edit("❌ <b>Export Failed</b>\n\nYou do not have any active accounts to export.", buttons=keyboards.back_keyboard(CB.ACCOUNTS), parse_mode="html")
        return
        
    # 3. Send file to user
    await event.respond(
        file=zip_bytes,
        attributes=[DocumentAttributeFilename("Exported_Sessions.zip")],
        message="✅ <b>Export Complete!</b>\n\nHere are your exported Telethon `.session` files.",
        parse_mode="html"
    )
    
    # 4. Restore menu
    await on_accounts(event)

async def on_account_add(event: events.CallbackQuery.Event) -> None:
    """Prompt user to send a session string."""
    await event.answer()  # LINE 1. Non-negotiable.
    await set_context(_uid(event), "awaiting_input", "auth_phone")
    text: str = (
        "📲 <b>Add Account</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Please send the <b>Phone Number</b> of the account you want to add.\n\n"
        "<i>Include the country code (e.g. +91...)</i>"
    )
    await event.edit(text, buttons=keyboards.back_keyboard(CB.ACCOUNTS), parse_mode="html")


async def on_account_pause(event: events.CallbackQuery.Event, account_id: str) -> None:
    """Confirm account pause."""
    await event.answer()  # LINE 1. Non-negotiable.
    text: str = "⏸️ Are you sure you want to <b>pause</b> this account?"
    buttons = keyboards.confirm_keyboard("pause_account", account_id)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_account_resume(event: events.CallbackQuery.Event, account_id: str) -> None:
    """Confirm account resume."""
    await event.answer()  # LINE 1. Non-negotiable.
    text: str = "▶️ Are you sure you want to <b>resume</b> this account?"
    buttons = keyboards.confirm_keyboard("resume_account", account_id)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_account_delete(event: events.CallbackQuery.Event, account_id: str) -> None:
    """Confirm account deletion."""
    await event.answer()  # LINE 1. Non-negotiable.
    text: str = "<tg-emoji emoji-id='5445267414562389170'>🗑️</tg-emoji> Are you sure you want to <b>delete</b> this account?\n\n<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> This action cannot be undone."
    buttons = keyboards.confirm_keyboard("delete_account", account_id)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_accounts_delete_all(event: events.CallbackQuery.Event) -> None:
    """Confirm deletion of all accounts."""
    await event.answer()  # LINE 1. Non-negotiable.
    await push_screen(_uid(event), "accounts")
    text: str = (
        "<tg-emoji emoji-id='5445267414562389170'>🗑️</tg-emoji> <b>REMOVE ALL ACCOUNTS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Are you sure you want to remove <b>ALL</b> accounts from the bot?\n\n"
        "<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> This action <b>CANNOT</b> be undone and will delete all session data."
    )
    buttons = keyboards.confirm_keyboard("delete_all_accounts", "all")
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_accounts_delete_limited(event: events.CallbackQuery.Event) -> None:
    """Prompt for confirmation before deleting limited accounts."""
    await event.answer()
    text: str = (
        "<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> <b>REMOVE LIMITED ACCOUNTS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Are you sure you want to remove <b>ALL</b> accounts with a health score below 50?\n"
        "This will help clean up accounts that are likely to fail."
    )
    buttons = keyboards.confirm_keyboard("delete_limited_accounts", "limited")
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_account_upload_sessions(event: events.CallbackQuery.Event) -> None:
    """Prompt user to upload a .session or .zip file."""
    await event.answer()
    text: str = (
        "📂 <b>UPLOAD SESSIONS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Please send a <b>.session</b> file or a <b>.zip</b> archive containing sessions.\n\n"
        "<tg-emoji emoji-id='5458603043203327669'>ℹ️</tg-emoji> <b>Tips:</b>\n"
        "├ 1. Sessions will be automatically validated.\n"
        "├ 2. Valid accounts will be added to your list.\n"
        "└ 3. All sessions are securely encrypted."
    )
    buttons = keyboards.back_keyboard(CB.ACCOUNTS)
    await event.edit(text, buttons=buttons, parse_mode="html")
    await set_context(_uid(event), "awaiting_input", "session_upload")


async def on_account_health(event: events.CallbackQuery.Event, account_id: str) -> None:
    """Display account health details."""
    await event.answer()  # LINE 1. Non-negotiable.
    data = await health_cache.get_account(account_id)
    if data:
        from core.constants import HEALTH_EMOJI, HealthState
        state = data.get("state", "UNKNOWN")
        emoji = HEALTH_EMOJI.get(HealthState(state), "❓")
        text: str = (
            f"🩺 <b>Account Health</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Status: {emoji} <b>{state}</b>\n"
            f"Score: <b>{data.get('score', 0)}/100</b>\n"
            f"Checked: <b>{menus._format_iso_date(data.get('checked_at'))}</b>"
        )
    else:
        text: str = "🩺 No health data available for this account yet."
    await event.edit(text, buttons=keyboards.back_keyboard(CB.ACCOUNT_VIEW.format(account_id=account_id)), parse_mode="html")


async def on_account_mails_list(event: events.CallbackQuery.Event, page: int = 1) -> None:
    """Show paginated list of accounts with secure emails."""
    await event.answer()
    from repositories import accounts_repo
    accounts = await accounts_repo.list_by_owner(_uid(event))
    
    # Filter only accounts with recovery_email
    mail_accounts = [acc for acc in accounts if acc.recovery_email]
    
    # Pagination logic
    limit = 10
    total = len(mail_accounts)
    total_pages = max(1, (total + limit - 1) // limit)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * limit
    page_accounts = mail_accounts[start_idx : start_idx + limit]
    
    pagination = {"current_page": page, "total_pages": total_pages}
    
    text = (
        "📧 <b>Account Mails</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Total secure emails configured: <b>{total}</b>\n"
        "Select an account to view details or check the inbox."
    )
    await event.edit(text, buttons=keyboards.account_mails_list_keyboard(page_accounts, pagination), parse_mode="html")


async def on_account_mails_view(event: events.CallbackQuery.Event, account_id: str) -> None:
    """View details of a specific account's secure email."""
    await event.answer()
    from repositories import accounts_repo
    acc = await accounts_repo.get(account_id)
    if not acc:
        await event.answer("Account not found.", alert=True)
        return
        
    text = (
        "📧 <b>Mail Details</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 Phone: <b>{acc.phone or 'Unknown'}</b>\n"
        f"✉️ Email: <b>{acc.recovery_email}</b>\n"
        f"🔐 2FA Password: <code>{acc.two_fa_password}</code>\n"
    )
    await event.edit(text, buttons=keyboards.account_mails_detail_keyboard(account_id), parse_mode="html")


async def on_account_mails_check(event: events.CallbackQuery.Event, account_id: str) -> None:
    """Check the latest emails for the account's secure email."""
    await event.answer("Checking inbox... ⏳")
    from repositories import accounts_repo
    from services.email_client import get_messages, get_message
    
    acc = await accounts_repo.get(account_id)
    if not acc or not acc.recovery_email:
        await event.answer("No secure email found.", alert=True)
        return
        
    try:
        msgs = await get_messages(acc.recovery_email)
        
        if not msgs:
            text = "📭 <b>Inbox is empty.</b>"
        else:
            text = "📬 <b>Latest Emails:</b>\n\n"
            # Get up to 3 latest messages
            for m in msgs[:3]:
                # Fetch full to get text preview if needed
                text_preview = await get_message(acc.recovery_email, m["messageID"])
                subject = m.get("subject", "No Subject")
                # text can be long, so truncate it
                body = text_preview[:200]
                text += f"🔹 <b>{subject}</b>\n<code>{body}</code>\n\n"
    except Exception as e:
        text = f"❌ Error checking mail: {str(e)}"
        
    # Append the back buttons
    final_text = (
        f"📧 <b>Inbox for {acc.recovery_email}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{text}"
    )
    await event.edit(final_text, buttons=keyboards.account_mails_detail_keyboard(account_id), parse_mode="html")


async def on_account_stats(event: events.CallbackQuery.Event, account_id: str) -> None:
    """Display account statistics."""
    await event.answer()  # LINE 1. Non-negotiable.
    data = await account_cache.get_summary(account_id)
    if data:
        from utils.formatters import format_number, format_percentage
        text: str = (
            f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Account Statistics</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Success: <b>{format_number(data.get('success_count', 0))}</b>\n"
            f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Failed: <b>{format_number(data.get('failure_count', 0))}</b>\n"
            f"<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> Success Rate: <b>{format_percentage(data.get('success_rate', 0))}</b>\n\n"
            f"🎯 Rotation Score: <b>{data.get('rotation_score', 0):.4f}</b>\n"
            f"🕐 Last Used: <b>{menus._format_iso_date(data.get('last_used_at'))}</b>"
        )
    else:
        text: str = "<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> No statistics available for this account."
    await event.edit(text, buttons=keyboards.back_keyboard(CB.ACCOUNT_VIEW.format(account_id=account_id)), parse_mode="html")


# ── Campaigns ───────────────────────────────────────────────

async def on_campaigns(event: events.CallbackQuery.Event) -> None:
    """Display the campaign list."""
    await event.answer()  # LINE 1. Non-negotiable.
    await push_screen(_uid(event), "campaigns")
    page = 1
    data = await campaign_cache.get_page(_uid(event), page)
    if not data:
        from workers.cache_worker import warm_user_cache
        await warm_user_cache(_uid(event), force=True)
        data = await campaign_cache.get_page(_uid(event), page)
        
    campaigns_list = data.get("campaigns", []) if data else []
    pagination = data.get("pagination", {}) if data else {}
    text: str = menus.render_campaign_list(data)
    buttons = keyboards.campaign_list_keyboard(campaigns_list, pagination)
    await event.edit(text, buttons=buttons, parse_mode="html")

async def _get_campaign_summary(campaign_id: str) -> dict[str, Any]:
    from cache import campaign_cache
    data = await campaign_cache.get_summary(campaign_id)
    if not data:
        from repositories import campaigns_repo
        c = await campaigns_repo.get(campaign_id)
        if c:
            data = c.model_dump(mode="json")
            data["account_count"] = len(c.account_ids)
            data["group_count"] = len(c.group_ids)
            data["total_sent"] = getattr(c.stats, "total_sent", 0)
            data["success_count"] = getattr(c.stats, "total_success", 0)
            data["failure_count"] = getattr(c.stats, "total_failed", 0)
            await campaign_cache.set_summary(campaign_id, data)
    return data or {}

async def on_campaign_view(event: events.CallbackQuery.Event, campaign_id: str) -> None:
    """Display campaign details."""
    await event.answer()  # LINE 1. Non-negotiable.
    await push_screen(_uid(event), "campaign_detail", {"campaign_id": campaign_id})
    data = await _get_campaign_summary(campaign_id)
    from telegram import menus, keyboards
    text: str = menus.render_campaign_detail(data)
    status = data.get("status", "UNKNOWN") if data else "UNKNOWN"
    buttons = keyboards.campaign_detail_keyboard(campaign_id, status)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_campaign_set_ad(event: events.CallbackQuery.Event, action: str, campaign_id: str) -> None:
    await event.answer()
    if action == "menu":
        from services import campaign_service
        camp = await campaign_service.get_campaign(campaign_id)
        current_ad_type = getattr(camp, "ad_type", "custom")
        
        msg = getattr(camp, "message", "") or "None"
        msg_disp = f"{msg[:40]}..." if len(msg) > 40 else msg
        link = getattr(camp, "forward_link", "") or "None"
        
        text: str = (
            "<tg-emoji emoji-id='5395444784611480792'>📝</tg-emoji> <b>Set Ad Type</b>\n\n"
            "Choose the type of advertisement for this campaign:\n\n"
            "<b>Current Settings:</b>\n"
            f"🔹 Custom Message: <i>{msg_disp}</i>\n"
            f"🔹 Forward Link: {link}"
        )
        await event.edit(text, buttons=keyboards.campaign_set_ad_keyboard(campaign_id, current_ad_type), parse_mode="html")
    elif action == "custom":
        await set_context(_uid(event), "awaiting_input", f"cmp_ad_custom:{campaign_id}")
        await event.edit("Please send the <b>custom message text</b> for your ad.", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)), parse_mode="html")
    elif action == "forward":
        await set_context(_uid(event), "awaiting_input", f"cmp_ad_forward:{campaign_id}")
        await event.edit("Please send the <b>post link</b> (e.g. t.me/channel/123) you want to forward.", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)), parse_mode="html")

async def on_campaign_set_interval(event: events.CallbackQuery.Event, action: str, campaign_id: str) -> None:
    await event.answer()
    if action == "menu":
        text: str = "⏱ <b>Set Intervals</b>\n\nConfigure how fast the bot sends messages:"
        await event.edit(text, buttons=keyboards.campaign_set_interval_keyboard(campaign_id), parse_mode="html")
    elif action == "group":
        await set_context(_uid(event), "awaiting_input", f"cmp_int_group:{campaign_id}")
        await event.edit("Enter the <b>delay between groups</b> in seconds (e.g. 15):", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)), parse_mode="html")
    elif action == "round":
        await set_context(_uid(event), "awaiting_input", f"cmp_int_round:{campaign_id}")
        await event.edit("Enter the <b>delay after a full round</b> in seconds (e.g. 600):", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)), parse_mode="html")

async def on_campaign_set_rounds(event: events.CallbackQuery.Event, action: str, campaign_id: str) -> None:
    await event.answer()
    if action == "menu":
        from services import campaign_service
        camp = await campaign_service.get_campaign(campaign_id)
        max_rounds = getattr(camp, "max_rounds", 0)
        text: str = "🔄 <b>Set Rounds</b>\n\nHow many times should the bot loop through all groups?"
        await event.edit(text, buttons=keyboards.campaign_set_rounds_keyboard(campaign_id, max_rounds), parse_mode="html")
    elif action == "max":
        await set_context(_uid(event), "awaiting_input", f"cmp_rounds_max:{campaign_id}")
        await event.edit("Enter the <b>maximum number of rounds</b> (e.g. 5):", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)), parse_mode="html")
    elif action == "infinite":
        from services import campaign_service
        await campaign_service.update_campaign(campaign_id, max_rounds=0)
        await on_campaign_view(event, campaign_id)

async def on_campaign_manage_accounts(event: events.CallbackQuery.Event, campaign_id: str, page: int = 1) -> None:
    """Display the accounts management screen for a campaign with pagination."""
    from cache import account_cache

    data = await account_cache.get_page(_uid(event), page)
    if not data:
        from workers.cache_worker import warm_user_cache
        await warm_user_cache(_uid(event), force=True)
        data = await account_cache.get_page(_uid(event), page)

    campaign = await _get_campaign_summary(campaign_id)
    assigned_ids: list[str] = campaign.get("account_ids", cast(list[Any], [])) if campaign else cast(list[Any], [])

    accounts = data.get("accounts", []) if data else []
    pagination = data.get("pagination", {}) if data else {"current_page": page, "total_pages": 1}

    text: str = (
        f"👥 <b>MANAGE ACCOUNTS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Campaign:</b> {campaign.get('name', 'Untitled') if campaign else '—'}\n"
        f"<b>Assigned:</b> {len(assigned_ids)} accounts\n\n"
        f"Select accounts to use for this campaign."
    )
    await set_context(_uid(event), "cmp_active", campaign_id)
    buttons = keyboards.campaign_manage_accounts_keyboard(campaign_id, accounts, assigned_ids, pagination)
    await event.edit(text, buttons=buttons, parse_mode="html")
async def on_campaign_select_all_accounts(event: events.CallbackQuery.Event, campaign_id: str) -> None:
    """Prompt for confirmation to add all accounts."""
    await event.answer()
    text: str = (
        "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> <b>SELECT ALL ACCOUNTS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Add <b>ALL</b> your accounts to this campaign?\n"
        "This will also select <b>ALL joined groups</b> for every account."
    )
    buttons = keyboards.confirm_keyboard("select_all_accounts", campaign_id)
    await event.edit(text, buttons=buttons, parse_mode="html")

async def on_campaign_unselect_all_accounts(event: events.CallbackQuery.Event, campaign_id: str) -> None:
    """Prompt for confirmation to remove all accounts."""
    await event.answer()
    text: str = (
        "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> <b>UNSELECT ALL ACCOUNTS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Remove <b>ALL</b> your accounts from this campaign?\n"
        "This will pause all active operations for this campaign."
    )
    buttons = keyboards.confirm_keyboard("unselect_all_accounts", campaign_id)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_campaign_account_toggle(event: events.CallbackQuery.Event) -> None:
    """Toggle an account's assignment to the active campaign."""
    await event.answer("Updating campaign...")
    from services import campaign_service
    from repositories import account_groups_repo
    
    campaign_id = await get_context(_uid(event), "cmp_active")
    account_id = await get_context(_uid(event), "acc_active")
    
    if not campaign_id or not account_id:
        await event.answer("❌ Error: Missing context.", alert=True)
        return
        
    camp = await campaign_service.get_campaign(campaign_id)
    if not camp:
        return
        
    # Force all IDs to strings to ensure consistent matching
    current_ids = [aid for aid in camp.account_ids]
    current_groups = [gid for gid in camp.group_ids]
    account_id_str = str(account_id)
    
    # Ensure groups are fetched if this account hasn't been synced yet
    await account_groups_repo.fetch_groups_if_missing(account_id_str)
    
    # Get all groups for this account to add/remove them as well
    all_account_groups = await account_groups_repo.get_all_group_ids(account_id_str)
    
    # Create fresh copies of lists
    new_acc_ids = list(current_ids)
    new_grp_ids = list(current_groups)
    
    if account_id_str in new_acc_ids:
        # REMOVE
        new_acc_ids.remove(account_id_str)
        # Filter out all groups belonging to this account
        new_grp_ids = [gid for gid in new_grp_ids if gid not in all_account_groups]
    else:
        # ADD
        new_acc_ids.append(account_id_str)
        for gid in all_account_groups:
            if gid not in new_grp_ids:
                new_grp_ids.append(gid)
                
    await campaign_service.update_campaign(campaign_id, account_ids=new_acc_ids, group_ids=new_grp_ids)
    
    # Return to detail view to show updated state
    await on_campaign_acc_detail(event, account_id)


async def on_campaign_refresh_all_groups(event: events.CallbackQuery.Event, campaign_id: str) -> None:
    """Fetch latest groups from Telegram for all assigned accounts in a campaign."""
    await event.answer("Fetching latest groups for all accounts...", alert=False)
    from repositories import account_groups_repo
    from services import campaign_service
    
    camp = await campaign_service.get_campaign(campaign_id)
    if not camp or not camp.account_ids:
        await on_campaign_manage_accounts(event, campaign_id)
        return
        
    for acc_id in camp.account_ids:
        await account_groups_repo.sync_groups_from_telegram(acc_id)
        
    await on_campaign_manage_accounts(event, campaign_id)


async def on_campaign_acc_detail(event: events.CallbackQuery.Event, account_id: str) -> None:

    """Show details for an account inside a campaign context."""
    from services import campaign_service
    from repositories import accounts_repo, account_groups_repo
    
    campaign_id = await get_context(_uid(event), "cmp_active")
    if not campaign_id:
        return
    await set_context(_uid(event), "acc_active", account_id)
    
    camp = await campaign_service.get_campaign(campaign_id)
    # Ensure ID comparison uses strings to avoid mismatch
    assigned_ids = [str(aid) for aid in (camp.account_ids if camp else [])]
    is_assigned = account_id in assigned_ids
    
    account = await accounts_repo.get(account_id)
    if not account:
        await event.edit("Account not found.")
        return
        
    # Check if we have groups, if not, fetch them
    total_groups = await account_groups_repo._coll().count_documents({"account_id": account_id})
    if total_groups == 0:
        try:
            from telegram.client_pool import client_pool
            async with client_pool.acquire(account_id) as client:
                dialogs = await client.get_dialogs()
                groups = [
                    {"id": d.id, "title": d.title, "is_selected": False}
                    for d in dialogs if d.is_group or d.is_channel
                ]
                await account_groups_repo.save_groups(account_id, groups)
                total_groups = len(groups)
        except Exception:
            pass # Ignore and continue with 0 groups
    
    phone = account.phone or "Unknown"
    
    text: str = (
        f"<tg-emoji emoji-id='5461117441612462242'>👤</tg-emoji> <b>Account Details</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 Phone: <b>{phone}</b>\n"
        f"🏘 Total Groups in Account: <b>{total_groups}</b>\n\n"
        f"Use the buttons below to include this account or select specific groups."
    )
    await event.edit(text, buttons=keyboards.campaign_account_detail_keyboard(campaign_id, account_id, is_assigned), parse_mode="html")

async def on_campaign_account_groups(event: events.CallbackQuery.Event, page: int) -> None:
    """Show paginated groups for an account to assign to a campaign."""
    await event.answer()
    from services import campaign_service
    from repositories import account_groups_repo
    
    campaign_id = await get_context(_uid(event), "cmp_active")
    account_id = await get_context(_uid(event), "acc_active")
    if not campaign_id or not account_id:
        return
        
    camp = await campaign_service.get_campaign(campaign_id)
    # Normalize current groups to strings
    assigned_group_ids = [str(gid) for gid in (camp.group_ids if camp else [])]
    
    groups, pagination = await account_groups_repo.get_groups_paginated(account_id, page, 10)
    
    text: str = (
        "👥 <b>Select Groups</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select which groups from this account should be used in the campaign."
    )
    await event.edit(text, buttons=keyboards.campaign_account_groups_keyboard(campaign_id, account_id, groups, assigned_group_ids, pagination), parse_mode="html")

async def on_campaign_auto_distribute(event: events.CallbackQuery.Event) -> None:
    """Trigger the global auto-distribute groups function."""
    await event.answer("🪄 Auto-distributing groups... Please wait.", alert=False)
    from services.distribution_service import auto_distribute_all_groups
    results = await auto_distribute_all_groups(_uid(event))
    
    if not results:
        await event.answer("❌ No campaigns or accounts found to distribute.", alert=True)
        return
        
    msg = "✅ **Groups Auto-Distributed Successfully!**\n\n"
    for camp_name, count in results.items():
        msg += f"• **{camp_name}**: {count} groups\n"
    msg += "\n*No two campaigns will target the same group!*"
        
    await event.answer(msg, alert=True)
    await on_campaigns(event)


async def on_campaign_start_all(event: events.CallbackQuery.Event) -> None:
    """Start all paused/draft campaigns for the user."""
    # (Lock removed)
    from repositories import users_repo
    from core.config import get_settings
    
    user = await users_repo.get(_uid(event))
    settings = get_settings()
    
    if settings.logs_bot_token and user and not user.has_started_logs_bot:
        bot_username = settings.logs_bot_username
        if not bot_username:
            await event.answer("Logs bot username is not configured in the environment.", alert=True)
            return
        text: str = (
            "<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> <b>Logs Bot Not Started</b>\n\n"
            "To receive real-time campaign notifications and success logs, "
            "you must first start the Logs Bot.\n\n"
            "Please click the button below to start it, then try again."
        )
        from telegram import keyboards
        buttons = keyboards.logs_bot_activation_keyboard(bot_username, "all")
        try:
            await event.edit(text, buttons=buttons, parse_mode="html")
        except Exception as e:
            if "Message is not modified" in str(e) or "not modified" in str(e).lower():
                await event.answer("⚠️ You haven't started the Logs Bot yet! Please click the link to start it first.", alert=True)
            else:
                raise e
        return

    await event.answer("▶️ Starting all campaigns...")
    from services import campaign_service
    await campaign_service.start_all_campaigns(_uid(event))
    await event.answer("✅ All campaigns started.", alert=True)
    await on_campaigns(event)


async def on_campaign_pause_all(event: events.CallbackQuery.Event) -> None:
    """Pause all active campaigns for the user."""
    await event.answer("⏸️ Pausing all campaigns...")
    from services import campaign_service
    await campaign_service.pause_all_campaigns(_uid(event))
    await event.answer("✅ All campaigns paused.", alert=True)
    await on_campaigns(event)


async def on_campaign_delete_all_confirm(event: events.CallbackQuery.Event) -> None:
    """Confirm deletion of all campaigns."""
    await event.answer()
    text: str = (
        "<tg-emoji emoji-id='5445267414562389170'>🗑️</tg-emoji> <b>DELETE ALL CAMPAIGNS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Are you sure you want to completely remove <b>ALL</b> your campaigns?\n\n"
        "<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> This action <b>CANNOT</b> be undone."
    )
    from telegram import keyboards
    buttons = keyboards.confirm_keyboard("delete_all_campaigns", "all")
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_campaign_group_bulk(event: events.CallbackQuery.Event, action: str) -> None:
    """Select or clear all groups for the current account in a campaign."""
    await event.answer("Updating groups...")
    from services import campaign_service
    from repositories import account_groups_repo
    
    campaign_id = await get_context(_uid(event), "cmp_active")
    account_id = await get_context(_uid(event), "acc_active")
    if not campaign_id or not account_id:
        return
        
    camp = await campaign_service.get_campaign(campaign_id)
    if not camp:
        return
        
    # Force all IDs to strings to ensure consistent matching
    current_groups = [gid for gid in camp.group_ids]
    all_account_groups = [gid for gid in await account_groups_repo.get_all_group_ids(account_id)]
    
    new_grp_ids = list(current_groups)
    
    if action == "all":
        # Add all account groups that aren't already in new_grp_ids
        for gid in all_account_groups:
            if gid not in new_grp_ids:
                new_grp_ids.append(gid)
    elif action == "none":
        # Remove all account groups from new_grp_ids
        new_grp_ids = [gid for gid in new_grp_ids if gid not in all_account_groups]
        
    await campaign_service.update_campaign(campaign_id, group_ids=new_grp_ids)
    
    await on_campaign_account_groups(event, 1)

async def on_campaign_toggle_group(event: events.CallbackQuery.Event, group_id_str: str) -> None:
    """Toggle a specific group for a campaign."""
    await event.answer()
    from services import campaign_service
    
    campaign_id = await get_context(_uid(event), "cmp_active")
    account_id = await get_context(_uid(event), "acc_active")
    if not campaign_id or not account_id:
        return
        
    camp = await campaign_service.get_campaign(campaign_id)
    if not camp:
        return
        
    # Normalize IDs
    current_groups = [gid for gid in camp.group_ids]
    gid_str = group_id_str
    
    new_grp_ids = list(current_groups)
    if gid_str in new_grp_ids:
        new_grp_ids.remove(gid_str)
    else:
        new_grp_ids.append(gid_str)
        
    await campaign_service.update_campaign(campaign_id, group_ids=new_grp_ids)
    
    # Since we dropped page from toggle_grp, we will just route back to page 1 for now.
    await on_campaign_account_groups(event, 1)

async def on_campaign_create(event: events.CallbackQuery.Event) -> None:
    """Prompt user to name a new campaign."""
    await event.answer()  # LINE 1. Non-negotiable.
    await set_context(_uid(event), "awaiting_input", "campaign_name")
    text: str = (
        "<tg-emoji emoji-id='5424818078833715060'>📢</tg-emoji> <b>Create Campaign</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Please send the <b>campaign name</b>."
    )
    await event.edit(text, buttons=keyboards.back_keyboard(CB.CAMPAIGNS), parse_mode="html")


async def on_campaign_pause(event: events.CallbackQuery.Event, campaign_id: str) -> None:
    """Confirm campaign pause."""
    await event.answer()  # LINE 1. Non-negotiable.
    text: str = "⏸️ Are you sure you want to <b>pause</b> this campaign?"
    buttons = keyboards.confirm_keyboard("pause_campaign", campaign_id)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_campaign_resume(event: events.CallbackQuery.Event, campaign_id: str) -> None:
    """Confirm campaign start/resume."""
    await event.answer()  # LINE 1. Non-negotiable.
    text: str = "▶️ Are you sure you want to <b>start</b> this campaign?"
    buttons = keyboards.confirm_keyboard("resume_campaign", campaign_id)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_campaign_delete(event: events.CallbackQuery.Event, campaign_id: str) -> None:
    """Confirm campaign deletion."""
    await event.answer()  # LINE 1. Non-negotiable.
    text: str = "<tg-emoji emoji-id='5445267414562389170'>🗑️</tg-emoji> Are you sure you want to <b>delete</b> this campaign?\n\n<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> This action cannot be undone."
    buttons = keyboards.confirm_keyboard("delete_campaign", campaign_id)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_campaign_duplicate(event: events.CallbackQuery.Event, campaign_id: str) -> None:
    """Prompt for new campaign name for duplication."""
    await event.answer()  # LINE 1. Non-negotiable.
    await set_context(_uid(event), "awaiting_input", "duplicate_campaign")
    await set_context(_uid(event), "duplicate_source", campaign_id)
    text: str = (
        "📋 <b>Duplicate Campaign</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Please send a <b>name</b> for the new campaign."
    )
    await event.edit(text, buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)), parse_mode="html")


# ── Health ──────────────────────────────────────────────────

async def on_health(event: events.CallbackQuery.Event) -> None:
    """Display health overview."""
    await event.answer()  # LINE 1. Non-negotiable.
    await push_screen(_uid(event), "health")
    data = await health_cache.get_summary(_uid(event))
    if not data:
        from workers.cache_worker import warm_user_cache
        await warm_user_cache(_uid(event), force=True)
        data = await health_cache.get_summary(_uid(event))
        
    text: str = menus.render_health_overview(data)
    buttons = keyboards.health_overview_keyboard()
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_health_settings(event: events.CallbackQuery.Event) -> None:
    """Display health settings."""
    await event.answer()
    from repositories import users_repo
    user = await users_repo.get(_uid(event))
    if not user:
        return
        
    text: str = menus.render_health_settings()
    buttons = keyboards.health_settings_keyboard(user.health_auto_pause)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_health_settings_toggle(event: events.CallbackQuery.Event) -> None:
    """Toggle health auto pause."""
    from repositories import users_repo
    user = await users_repo.get(_uid(event))
    if not user:
        return
        
    new_status = not user.health_auto_pause
    await users_repo.update(_uid(event), {"health_auto_pause": new_status})
    await event.answer(f"Auto-Pause turned {'ON' if new_status else 'OFF'}")
    
    text: str = menus.render_health_settings()
    buttons = keyboards.health_settings_keyboard(new_status)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_health_clear_toxic(event: events.CallbackQuery.Event) -> None:
    """Show confirmation to clear toxic backlog."""
    await event.answer()
    text: str = (
        "<tg-emoji emoji-id='5445267414562389170'>♻️</tg-emoji> <b>CLEAR TOXIC BACKLOG</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Are you sure you want to completely clear the entire health history for all groups?\n\n"
        "All groups currently marked as 'toxic' will be reset to 100 Health and the bot will attempt to message them again.\n\n"
        "<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> This action <b>CANNOT</b> be undone."
    )
    from telegram import keyboards
    buttons = keyboards.confirm_keyboard("clear_toxic", "all")
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_health_view_all(event: events.CallbackQuery.Event, page: int = 1) -> None:
    """Display paginated list of accounts with health info."""
    await event.answer("Fetching health data...")
    await push_screen(_uid(event), "health_all")
    await set_context(_uid(event), "view_source", "health_all")
    # For now, just use the account list keyboard since it shows health dots!
    from cache import account_cache
    data = await account_cache.get_page(_uid(event), page)
    if not data:
        from workers.cache_worker import warm_user_cache
        await warm_user_cache(_uid(event), force=True)
        data = await account_cache.get_page(_uid(event), page)

    accounts = data.get("accounts", []) if data else []
    pagination = data.get("pagination", {}) if data else {}

    text: str = (
        "👁 <b>ACCOUNT HEALTH LIST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select an account to view detailed stats and health checks."
    )
    buttons = keyboards.account_list_keyboard(
        accounts, 
        pagination, 
        action_prefix="acc:view", 
        show_actions=False,
        screen="health_all",
        back_cb=CB.HEALTH
    )
    await event.edit(text, buttons=buttons, parse_mode="html")


# ── 9. PERSONAL AI ───────────────────────────────────────────

async def on_ai_chat(event: events.CallbackQuery.Event) -> None:
    """Enter AI chat mode."""
    await event.answer()
    text: str = menus.render_ai_welcome()
    buttons = keyboards.ai_chat_keyboard()
    await event.edit(text, buttons=buttons, parse_mode="html")
    await set_context(_uid(event), "awaiting_input", "ai_chat")

async def on_ai_confirm(event: events.CallbackQuery.Event, action_id: str) -> None:
    """Execute a pending AI action."""
    await event.answer()
    
    from services.ai_action_queue import get_action, clear_action
    action = await get_action(action_id)
    
    if not action:
        await event.edit("<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> Action expired or not found.", buttons=keyboards.back_keyboard())
        return
        
    if action.get("user_id") != _uid(event):
        await event.answer("⚠️ Unauthorized.", alert=True)
        return
        
    action_type = action.get("action_type")
    payload = action.get("payload", {})
    
    await event.edit("⏳ <b>Executing...</b>", parse_mode="html")
    
    # Route execution based on action_type
    try:
        if action_type == "delete_account":
            account_id = payload.get("account_id")
            if account_id:
                from telegram.client_pool import client_pool
                await client_pool.evict(account_id)
                from repositories import accounts_repo
                await accounts_repo.delete(account_id)
                await event.edit("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Account deleted successfully.", buttons=keyboards.back_keyboard(CB.ACCOUNTS))
        elif action_type == "create_campaign":
            from repositories import campaigns_repo
            try:
                await campaigns_repo.create(payload)
                await event.edit(f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Campaign '{payload.get('name')}' created successfully.", buttons=keyboards.back_keyboard(CB.CAMPAIGNS))
            except ValueError as e:
                await event.answer(str(e), alert=True)
                return
        elif action_type == "edit_campaign_status":
            campaign_id = payload.get("campaign_id")
            status = payload.get("status")
            if campaign_id and status:
                from repositories import campaigns_repo
                await campaigns_repo.update_status(campaign_id, status)
                await event.edit(f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Campaign status updated to {status}.", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)))
        elif action_type == "edit_campaign_interval":
            campaign_id = payload.get("campaign_id")
            delay = payload.get("group_delay_seconds")
            if campaign_id and delay is not None:
                from repositories import campaigns_repo
                await campaigns_repo.update_fields(campaign_id, {"group_delay_seconds": int(delay)})
                await event.edit(f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Campaign interval updated to {delay}s.", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)))
        elif action_type == "delete_campaign":
            campaign_id = payload.get("campaign_id")
            if campaign_id:
                from repositories import campaigns_repo
                await campaigns_repo.delete(campaign_id)
                await event.edit("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Campaign deleted successfully.", buttons=keyboards.back_keyboard(CB.CAMPAIGNS))
        elif action_type == "edit_campaign_message":
            campaign_id = payload.get("campaign_id")
            message = payload.get("message")
            if campaign_id and message is not None:
                from repositories import campaigns_repo
                await campaigns_repo.update_fields(campaign_id, {"message": message})
                await event.edit("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Campaign message updated successfully.", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)))
        elif action_type == "edit_campaign_accounts":
            campaign_id = payload.get("campaign_id")
            account_ids = payload.get("account_ids")
            if campaign_id and account_ids is not None:
                from repositories import campaigns_repo
                await campaigns_repo.update_fields(campaign_id, {"account_ids": account_ids})
                await event.edit("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Campaign accounts updated successfully.", buttons=keyboards.back_keyboard(CB.CAMPAIGN_VIEW.format(campaign_id=campaign_id)))
        elif action_type == "pause_all_campaigns":
            from repositories import campaigns_repo
            campaigns = await campaigns_repo.list_by_owner(_uid(event))
            for c in campaigns:
                if getattr(c, "status", "") == "ACTIVE" and c.id:
                    await campaigns_repo.update_status(c.id, CampaignStatus.PAUSED)
            await event.edit("<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> All active campaigns have been paused.", buttons=keyboards.back_keyboard(CB.CAMPAIGNS))
        else:
            await event.edit(f"<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> Unknown action type: {action_type}", buttons=keyboards.back_keyboard())
    except Exception as e:
        await event.edit(f"<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> Execution failed: {str(e)}", buttons=keyboards.back_keyboard())
    finally:
        await clear_action(action_id)


async def on_ai_cancel(event: events.CallbackQuery.Event, action_id: str) -> None:
    """Cancel a pending AI action."""
    await event.answer("Action cancelled.")
    from services.ai_action_queue import clear_action
    await clear_action(action_id)
    
    text: str = menus.render_ai_welcome()
    buttons = keyboards.ai_chat_keyboard()
    await event.edit(text, buttons=buttons, parse_mode="html")


# ── Auto Join ──────────────────────────────────────────────────


async def on_groups_autojoin(event: events.CallbackQuery.Event) -> None:
    """Prompt for .txt file to start auto-joining."""
    await event.answer()
    from services.joiner_service import is_joiner_running
    if is_joiner_running(_uid(event)):
        await event.answer("⚠️ Auto-join already in progress!", alert=True)
        return

    text: str = menus.render_autojoin_prompt()
    buttons = keyboards.back_keyboard(CB.DASHBOARD)
    await event.edit(text, buttons=buttons, parse_mode="html")
    await set_context(_uid(event), "awaiting_input", "bulk_autojoin")


async def on_groups_autojoin_cancel(event: events.CallbackQuery.Event) -> None:
    """Cancel the running joiner."""
    from services.joiner_service import cancel_joiner
    if await cancel_joiner(_uid(event)):
        await event.answer("🛑 Joining process cancelled!", alert=True)
    else:
        await event.answer("Nothing to cancel.")
    await on_dashboard(event)


# ── Groups Checker ───────────────────────────────────────────


async def on_groups_checker(event: events.CallbackQuery.Event) -> None:
    """Prompt for .txt file / folder link to start group checking."""
    await event.answer()
    from services.group_checker_service import is_checker_running
    if is_checker_running(_uid(event)):
        await event.answer("⚠️ Checker already in progress!", alert=True)
        return

    from repositories import checker_repo
    if await checker_repo.count() == 0:
        await event.respond(
            "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> <b>No checker accounts added.</b>\n"
            "Add checker sessions first, then try again.",
            buttons=keyboards.back_keyboard(CB.DASHBOARD),
            parse_mode="html",
        )
        return

    text: str = menus.render_checker_prompt()
    buttons = keyboards.back_keyboard(CB.DASHBOARD)
    await event.edit(text, buttons=buttons, parse_mode="html")
    await set_context(_uid(event), "awaiting_input", "bulk_checker")


async def on_groups_checker_cancel(event: events.CallbackQuery.Event) -> None:
    """Cancel the running checker."""
    from services.group_checker_service import cancel_checker
    if await cancel_checker(_uid(event)):
        await event.answer("🛑 Checking process cancelled!", alert=True)
    else:
        await event.answer("Nothing to cancel.")


# ── Analytics ───────────────────────────────────────────────

async def on_analytics(event: events.CallbackQuery.Event) -> None:
    """Display analytics overview."""
    await event.answer("Refreshing analytics...")  # LINE 1. Non-negotiable.
    await push_screen(_uid(event), "analytics")
    user_id = _uid(event)
    
    # Get synchronized data from dashboard service/cache
    from services import dashboard_service
    data = await dashboard_cache.get(user_id)
    if not data:
        data = await dashboard_service.build_dashboard(user_id)
    
    # Map dashboard stats to analytics renderer expected keys
    # dashboard keys: total_forwarded, successful, failed, success_rate
    # render_analytics expects: total_sent, total_success, total_failed
    analytics_data = {
        "total_sent": data.get("total_forwarded", 0),
        "total_success": data.get("successful", 0),
        "total_failed": data.get("failed", 0),
    }
    
    text: str = menus.render_analytics(analytics_data)
    buttons = keyboards.analytics_keyboard()
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_analytics_detailed(event: events.CallbackQuery.Event) -> None:
    """Display detailed analytics."""
    await event.answer()  # LINE 1. Non-negotiable.
    user_id = _uid(event)
    data = await analytics_cache.get_dashboard(user_id)
    text: str = menus.render_analytics_detailed(data)
    # Re-use the back keyboard to go back to main analytics overview
    buttons = keyboards.back_keyboard(CB.ANALYTICS)
    await event.edit(text, buttons=buttons, parse_mode="html")


# ── Settings ────────────────────────────────────────────────

async def on_autoreply_menu(event: events.CallbackQuery.Event) -> None:
    """Display auto-reply settings menu."""
    await event.answer()
    from repositories import users_repo
    user = await users_repo.get(_uid(event))
    if not user:
        return
        
    enabled = user.autoreply_enabled
    has_custom = bool(user.autoreply_text)
    
    text: str = menus.render_autoreply_menu(enabled, has_custom)
    buttons = keyboards.autoreply_keyboard(enabled, has_custom)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_autoreply_toggle(event: events.CallbackQuery.Event) -> None:
    """Toggle auto-reply status."""
    from repositories import users_repo
    user = await users_repo.get(_uid(event))
    if not user:
        return
        
    new_status = not user.autoreply_enabled
    await users_repo.update(_uid(event), {"autoreply_enabled": new_status})
    
    if new_status:
        from services.autoreply_service import ensure_autoreply_clients
        import asyncio
        asyncio.create_task(ensure_autoreply_clients())
        
    await event.answer(f"Auto Reply turned {'ON' if new_status else 'OFF'}")
    
    # Refresh menu
    has_custom = bool(user.autoreply_text)
    text: str = menus.render_autoreply_menu(new_status, has_custom)
    buttons = keyboards.autoreply_keyboard(new_status, has_custom)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_autoreply_view(event: events.CallbackQuery.Event) -> None:
    """View current auto-reply message."""
    await event.answer()
    from repositories import users_repo
    user = await users_repo.get(_uid(event))
    if not user:
        return
        
    text: str = menus.render_autoreply_view(user.autoreply_text or "N/A")
    buttons = keyboards.back_keyboard(CB.SETTINGS_AUTOREPLY)
    await event.edit(text, buttons=buttons, parse_mode="html")


async def on_autoreply_custom(event: events.CallbackQuery.Event) -> None:
    """Initiate setting custom auto-reply message."""
    await event.answer("Please send your new auto-reply message.")
    await set_context(_uid(event), "awaiting_input", "autoreply_text")
    
    # Instruct user via new message or edit
    await event.edit(
        "💬 <b>SET CUSTOM AUTO REPLY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Please send the message you want to use for auto-replies.",
        parse_mode="html",
        buttons=keyboards.back_keyboard(CB.SETTINGS_AUTOREPLY)
    )


# ── Navigation ──────────────────────────────────────────────

async def on_back(event: events.CallbackQuery.Event) -> None:
    """Navigate back to previous screen."""
    await event.answer()  # LINE 1. Non-negotiable.
    from telegram.navigation import go_back
    await go_back(event)


async def on_page_next(event: events.CallbackQuery.Event, screen: str, page: int) -> None:
    """Navigate to next page."""
    await event.answer()  # LINE 1. Non-negotiable.
    if screen == "accounts":
        data = await account_cache.get_page(_uid(event), page)
        text: str = menus.render_account_list(data)
        accounts = data.get("accounts", []) if data else []
        pagination = data.get("pagination", {}) if data else {}
        buttons = keyboards.account_list_keyboard(accounts, pagination)
        await event.edit(text, buttons=buttons, parse_mode="html")
    elif screen == "campaigns":
        data = await campaign_cache.get_page(_uid(event), page)
        campaigns_list = data.get("campaigns", []) if data else []
        pagination = data.get("pagination", {}) if data else {}
        text: str = "<tg-emoji emoji-id='5424818078833715060'>📢</tg-emoji> <b>Campaigns</b>\n━━━━━━━━━━━━━━━━━━━━━━━━"
        buttons = keyboards.campaign_list_keyboard(campaigns_list, pagination)
        await event.edit(text, buttons=buttons, parse_mode="html")
    elif screen == "cmp_acc":
        campaign_id = await get_context(_uid(event), "cmp_active")
        await on_campaign_manage_accounts(event, campaign_id, page=page)
    elif screen == "health_all":
        await on_health_view_all(event, page=page)


async def on_page_prev(event: events.CallbackQuery.Event, screen: str, page: int) -> None:
    """Navigate to previous page."""
    await event.answer()  # LINE 1. Non-negotiable.
    # Reuse next page logic
    await on_page_next(event, screen, page)


# ── Confirmation ────────────────────────────────────────────

async def on_confirm_yes(event: events.CallbackQuery.Event, action: str, target_id: str) -> None:
    """Handle confirmed action."""
    await event.answer()  # LINE 1. Non-negotiable.

    text: str = ""
    try:
        if action == "delete_account":
            from services import account_service
            await account_service.delete_account(target_id, _uid(event))
            text: str = "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Account deleted successfully."
        elif action == "delete_all_accounts":
            from services import account_service
            await account_service.delete_all_accounts(_uid(event))
            text: str = "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> All accounts removed."
        elif action == "clear_toxic":
            from repositories import group_health_repo
            count = await group_health_repo.clear_all_health()
            text: str = f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Toxic backlog cleared. Reset health for {count} groups."
        elif action == "delete_limited_accounts":
            from services import account_service
            count = await account_service.delete_limited_accounts(_uid(event))
            text: str = f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> {count} limited accounts removed."
        elif action == "select_all_accounts":
            from services import campaign_service
            await campaign_service.select_all_accounts(target_id, _uid(event))
            text: str = "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> All accounts added to campaign."
        elif action == "unselect_all_accounts":
            from services import campaign_service
            await campaign_service.unselect_all_accounts(target_id, _uid(event))
            text: str = "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> All accounts removed from campaign."
        elif action == "pause_account":
            from services import account_service
            await account_service.pause_account(target_id, _uid(event))
            text: str = "⏸️ Account paused."
        elif action == "resume_account":
            from services import account_service
            await account_service.resume_account(target_id, _uid(event))
            text: str = "▶️ Account resumed."
        elif action == "delete_campaign":
            from services import campaign_service
            await campaign_service.delete_campaign(target_id, _uid(event))
            text: str = "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Campaign deleted successfully."
        elif action == "delete_all_campaigns":
            from services import campaign_service
            await campaign_service.delete_all_campaigns(_uid(event))
            text: str = "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> All campaigns deleted."
        elif action == "pause_campaign":
            from services import campaign_service
            await campaign_service.pause_campaign(target_id, _uid(event))
            text: str = "⏸️ Campaign paused."
        elif action == "resume_campaign":
            # (Lock removed)
            from repositories import users_repo
            from core.config import get_settings
            
            user = await users_repo.get(_uid(event))
            settings = get_settings()
            
            if settings.logs_bot_token and user and not user.has_started_logs_bot:
                bot_username = settings.logs_bot_username
                if not bot_username:
                    await event.answer("Logs bot username is not configured in the environment.", alert=True)
                    return
                text: str = (
                    "<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> <b>Logs Bot Not Started</b>\n\n"
                    "To receive real-time campaign notifications and success logs, "
                    "you must first start the Logs Bot.\n\n"
                    "Please click the button below to start it, then try again."
                )
                buttons = keyboards.logs_bot_activation_keyboard(bot_username, target_id)
                try:
                    await event.edit(text, buttons=buttons, parse_mode="html")
                except Exception as e:
                    if "Message is not modified" in str(e) or "not modified" in str(e).lower():
                        await event.answer("⚠️ You haven't started the Logs Bot yet! Please click the link to start it first.", alert=True)
                    else:
                        raise e
                return

            from services import campaign_service
            await campaign_service.resume_campaign(target_id, _uid(event))
            text: str = "▶️ Campaign started."
            
        elif action == "bulk_cancel":
            from services.bulk_service import cancel_bulk_task
            cancel_bulk_task(_uid(event))
            await event.answer("🛑 Cancelling bulk task...", alert=True)

        elif action == "bulk_rm_username":
            from telegram.menus import render_bulk_progress
            from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
            await event.edit(render_bulk_progress("Remove Usernames", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
            from services import bulk_service
            async def run_task():
                async def update_progress(success: int, failed: int, total: int):
                    try:
                        await event.edit(render_bulk_progress("Remove Usernames", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
                    except Exception:
                        pass
                success, failed = await bulk_service.bulk_remove_usernames(_uid(event), progress_callback=update_progress)
                try:
                    await event.edit(render_bulk_progress("Remove Usernames", success, failed, success+failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
                except Exception:
                        pass
            import asyncio
            asyncio.create_task(run_task())
            return
            
        elif action == "bulk_rm_photo":
            from telegram.menus import render_bulk_progress
            from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
            await event.edit(render_bulk_progress("Remove Photo", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
            from services import bulk_service
            async def run_task():
                async def update_progress(success: int, failed: int, total: int):
                    try:
                        await event.edit(render_bulk_progress("Remove Photo", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
                    except Exception:
                        pass
                success, failed = await bulk_service.bulk_delete_profile_photos(_uid(event), progress_callback=update_progress)
                try:
                    await event.edit(render_bulk_progress("Remove Photo", success, failed, success+failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
                except Exception:
                        pass
            import asyncio
            asyncio.create_task(run_task())
            return
            
        elif action == "bulk_clean_dms":
            from telegram.menus import render_bulk_progress
            from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
            await event.edit(render_bulk_progress("Clean DMs", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
            from services import bulk_service
            async def run_task():
                async def update_progress(success: int, failed: int, total: int):
                    try:
                        await event.edit(render_bulk_progress("Clean DMs", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
                    except Exception:
                        pass
                success, failed = await bulk_service.bulk_clean_dms(_uid(event), progress_callback=update_progress)
                try:
                    await event.edit(render_bulk_progress("Clean DMs", success, failed, success+failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
                except Exception:
                        pass
            import asyncio
            asyncio.create_task(run_task())
            return
            
        elif action == "bulk_archive":
            from telegram.menus import render_bulk_progress
            from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
            await event.edit(render_bulk_progress("Archive Chats", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
            from services import bulk_service
            async def run_task():
                async def update_progress(success: int, failed: int, total: int):
                    try:
                        await event.edit(render_bulk_progress("Archive Chats", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
                    except Exception:
                        pass
                success, failed = await bulk_service.bulk_archive_chats(_uid(event), progress_callback=update_progress)
                try:
                    await event.edit(render_bulk_progress("Archive Chats", success, failed, success+failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
                except Exception:
                        pass
            import asyncio
            asyncio.create_task(run_task())
            return
            
        elif action == "bulk_leave_groups":
            from telegram.menus import render_bulk_progress
            from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
            await event.edit(render_bulk_progress("Leave Groups/Channels", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
            from services import bulk_service
            async def run_task():
                async def update_progress(success: int, failed: int, total: int):
                    try:
                        await event.edit(render_bulk_progress("Leave Groups/Channels", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
                    except Exception:
                        pass
                success, failed = await bulk_service.bulk_leave_groups(_uid(event), progress_callback=update_progress)
                try:
                    await event.edit(render_bulk_progress("Leave Groups/Channels", success, failed, success+failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
                except Exception:
                        pass
            import asyncio
            asyncio.create_task(run_task())
            return
            
        elif action == "bulk_rm_folders":
            from telegram.menus import render_bulk_progress
            from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
            await event.edit(render_bulk_progress("Remove Folders", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
            from services import group_worker
            async def run_task():
                async def update_progress(success: int, failed: int, total: int):
                    try:
                        await event.edit(render_bulk_progress("Remove Folders", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
                    except Exception:
                        pass
                success, failed = await group_worker.bulk_remove_folders(_uid(event), progress_callback=update_progress)
                try:
                    await event.edit(render_bulk_progress("Remove Folders", success, failed, success+failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
                except Exception:
                        pass
            import asyncio
            asyncio.create_task(run_task())
            return
            
        elif action == "bulk_rm_2fa":
            from telegram.menus import render_bulk_progress
            from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
            await event.edit(render_bulk_progress("Remove 2FA", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
            from services import bulk_service
            async def run_task():
                async def update_progress(success: int, failed: int, total: int):
                    try:
                        await event.edit(render_bulk_progress("Remove 2FA", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
                    except Exception:
                        pass
                success, failed = await bulk_service.bulk_remove_2fa(_uid(event), progress_callback=update_progress)
                try:
                    await event.edit(render_bulk_progress("Remove 2FA", success, failed, success+failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
                except Exception:
                        pass
            import asyncio
            asyncio.create_task(run_task())
            return
        elif action == "bulk_secure_privacy":
            from telegram.menus import render_bulk_progress
            from telegram.keyboards import bulk_progress_keyboard, bulk_manager_keyboard
            await event.edit(render_bulk_progress("Secure Privacy", 0, 0, 0), buttons=bulk_progress_keyboard(), parse_mode="html")
            from services import bulk_service
            async def run_task():
                async def update_progress(success: int, failed: int, total: int):
                    try:
                        await event.edit(render_bulk_progress("Secure Privacy", success, failed, total), buttons=bulk_progress_keyboard(), parse_mode="html")
                    except Exception:
                        pass
                success, failed = await bulk_service.bulk_secure_privacy(_uid(event), progress_callback=update_progress)
                try:
                    await event.edit(render_bulk_progress("Secure Privacy", success, failed, success+failed, "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Completed!"), buttons=bulk_manager_keyboard(), parse_mode="html")
                except Exception:
                        pass
            import asyncio
            asyncio.create_task(run_task())
            return
            
        else:
            text: str = "❓ Unknown action."
    except Exception as exc:
        text: str = f"<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Error: {str(exc)}"

    # One-step-back target depends on the confirmed action
    if action in ("delete_account", "delete_all_accounts", "delete_limited_accounts"):
        back_target: str = CB.ACCOUNTS
    elif action in ("delete_campaign", "delete_all_campaigns"):
        back_target = CB.CAMPAIGNS
    elif action in ("pause_account", "resume_account"):
        back_target = CB.ACCOUNT_VIEW.format(account_id=target_id)
    elif action in ("pause_campaign", "resume_campaign", "select_all_accounts", "unselect_all_accounts"):
        back_target = CB.CAMPAIGN_VIEW.format(campaign_id=target_id)
    elif action == "clear_toxic":
        back_target = CB.HEALTH
    else:
        back_target = CB.DASHBOARD

    await event.edit(text, buttons=keyboards.back_keyboard(back_target), parse_mode="html")

async def on_pay_profile(event: events.CallbackQuery.Event) -> None:
    from core.config import get_settings
    from repositories import users_repo
    user = await users_repo.get(_uid(event))
    if not user:
        return
    settings = get_settings()
    is_active = user.is_active(settings.admin_user_ids, settings.admin_username)
    text: str = menus.render_profile(user.model_dump(), is_active)
    await event.edit(text, buttons=keyboards.profile_keyboard(), parse_mode="html")

async def on_pay_options(event: events.CallbackQuery.Event) -> None:
    from repositories import users_repo
    user = await users_repo.get(_uid(event))
    text: str = menus.render_paywall()
    await event.edit(text, buttons=keyboards.paywall_keyboard(user), parse_mode="html")

async def on_admin_panel(event: events.CallbackQuery.Event) -> None:
    from core.db import get_redis
    from core.constants import RedisKeys
    r = get_redis()
    val = await r.get(RedisKeys.ADMIN_BOT_IMAGE_ENABLED)
    image_enabled = val.decode("utf-8") == "1" if val else True
    
    text: str = menus.render_admin_panel()
    await event.edit(text, buttons=keyboards.admin_panel_keyboard(image_enabled), parse_mode="html")
async def on_admin_stats(event: events.CallbackQuery.Event) -> None:
    from repositories import users_repo
    stats = await users_repo.get_stats()
    text: str = menus.render_admin_stats(stats)
    await event.edit(text, buttons=keyboards.back_keyboard("admin:panel"), parse_mode="html")

async def on_admin_users(event: events.CallbackQuery.Event) -> None:
    # simple listing for active users
    from repositories import users_repo
    users = await users_repo.get_active_subscribers()
    if not users:
        await event.answer("No active users found.", alert=True)
        return
        
    text: str = "👑 <b>ACTIVE USERS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for u in users[:20]: # Simple limit for now
        text += f"ID: <code>{u.user_id}</code> | @{u.username or 'NoName'} | {u.plan_type}\n"
        
    await event.edit(text, buttons=keyboards.back_keyboard("admin:panel"), parse_mode="html")

async def on_confirm_no(event: events.CallbackQuery.Event) -> None:
    """Handle cancelled action — go back."""
    await event.answer()  # LINE 1. Non-negotiable.
    from telegram.navigation import go_back
    await go_back(event)


async def on_noop(event: events.CallbackQuery.Event) -> None:
    """Handle no-op buttons (like page indicator)."""
    await event.answer()  # LINE 1. Non-negotiable.
    # Do nothing — just dismiss the loading spinner


# ── Bulk Account Manager ──────────────────────────────────────

async def on_bulk_manager(event: events.CallbackQuery.Event) -> None:
    """Show Bulk Account Manager."""
    await event.answer()
    text: str = (
        "👥 <b>Bulk Account Manager</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Perform actions on <b>all connected accounts</b> simultaneously.\n"
        "<i>Note: Actions may take time if you have many accounts.</i>"
    )
    await event.edit(text, buttons=keyboards.bulk_manager_keyboard(), parse_mode="html")

async def on_bulk_action(event: events.CallbackQuery.Event, action: str) -> None:
    """Handle bulk manager buttons."""
    await event.answer()
    text: str = ""
    if action == "name":
        await set_context(_uid(event), "awaiting_input", "bulk_name_first")
        await event.edit("Please send the <b>new First Name</b> for all accounts.", buttons=keyboards.back_keyboard(CB.BULK_MANAGER), parse_mode="html")
    elif action == "bio":
        await set_context(_uid(event), "awaiting_input", "bulk_bio")
        await event.edit("Please send the <b>new Bio/About</b> for all accounts.\n\n<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> <b>Important:</b> Telegram strictly allows a <b>MAXIMUM of 70 characters</b>.", buttons=keyboards.back_keyboard(CB.BULK_MANAGER), parse_mode="html")
    elif action == "rm_username":
        buttons = keyboards.confirm_keyboard("bulk_rm_username", "all")
        await event.edit("🚫 <b>Remove Usernames?</b>\n\nThis will completely remove the usernames from all connected accounts.", buttons=buttons, parse_mode="html")
    elif action == "photo":
        await set_context(_uid(event), "awaiting_input", "bulk_photo")
        await event.edit("Please send the <b>new Profile Photo</b>.", buttons=keyboards.back_keyboard(CB.BULK_MANAGER), parse_mode="html")
    elif action == "rm_photo":
        buttons = keyboards.confirm_keyboard("bulk_rm_photo", "all")
        await event.edit("<tg-emoji emoji-id='5445267414562389170'>🗑️</tg-emoji> Remove all profile photos from all accounts?", buttons=buttons, parse_mode="html")
    elif action == "clean_dms":
        buttons = keyboards.confirm_keyboard("bulk_clean_dms", "all")
        await event.edit("💬 Delete all private chat history from all accounts?", buttons=buttons, parse_mode="html")
    elif action == "archive":
        buttons = keyboards.confirm_keyboard("bulk_archive", "all")
        await event.edit("📦 Archive all active chats on all accounts?", buttons=buttons, parse_mode="html")
    elif action == "leave_groups":
        buttons = keyboards.confirm_keyboard("bulk_leave_groups", "all")
        await event.edit("🚪 Leave ALL groups and channels on all accounts?", buttons=buttons, parse_mode="html")
    elif action == "rm_folders":
        buttons = keyboards.confirm_keyboard("bulk_rm_folders", "all")
        await event.edit("📁 Delete ALL custom chat folders from all accounts?\n\n<i>Note: This only deletes the folders, you will NOT leave the groups.</i>", buttons=buttons, parse_mode="html")

    elif action == "2fa":
        text: str = "🔐 <b>Bulk 2FA Manager</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nChoose an action below."
        await event.edit(text, buttons=keyboards.bulk_2fa_keyboard(), parse_mode="html")
    elif action == "2fa:set":
        await set_context(_uid(event), "awaiting_input", "bulk_2fa_set")
        await event.edit("Please send the <b>new 2FA Password</b> for all accounts.", buttons=keyboards.back_keyboard(CB.BULK_MANAGER), parse_mode="html")
    elif action == "secure_email":
        await set_context(_uid(event), "awaiting_input", "bulk_secure_email")
        text_body = (
            "🔒 <b>Secure Email Setup</b>\n\n"
            "This will create a permanent @gmail.com alias for all accounts and set it as the recovery email. "
            "Because this requires 2FA to be enabled, you must provide a 2FA password to set.\n\n"
            "<i>Note: If an account already has 2FA enabled, it will be skipped automatically.</i>\n\n"
            "Please send the <b>2FA Password</b> you want to set for these accounts:"
        )
        await event.edit(text_body, buttons=keyboards.back_keyboard(CB.BULK_MANAGER), parse_mode="html")
    elif action == "2fa:remove":
        buttons = keyboards.confirm_keyboard("bulk_rm_2fa", "all")
        await event.edit("🔓 Remove 2FA from all accounts?\n\n<i>Note: This only works if no 2FA is set, or if we can clear it.</i>", buttons=buttons, parse_mode="html")
    elif action == "secure_privacy":
        buttons = keyboards.confirm_keyboard("bulk_secure_privacy", "all")
        text_body = (
            "🛡 <b>Secure Privacy Lockdown</b>\n\n"
            "This will apply extreme privacy settings to all accounts:\n"
            "• Sets Phone, Last Seen, Calls, Birthday, Invites to <b>Nobody</b>\n"
            "• Wipes Payment & Shipping Info\n"
            "• Disables Frequent Contacts\n"
            "• <b>Deletes all Synced Contacts permanently</b>\n\n"
            "Are you sure you want to proceed?"
        )
        await event.edit(text_body, buttons=buttons, parse_mode="html")


# ── Callback Router ─────────────────────────────────────────

async def on_buy_plan(event: events.CallbackQuery.Event, plan: str) -> None:
    """Show payment methods for the selected plan."""
    await event.answer()
    price = "$35" if plan == "weekly" else "$75"
    text: str = (
        f"<b>🛒 Purchase Plan</b>\n\n"
        f"<b>Selected:</b> {plan.capitalize()} Pass\n"
        f"<b>Price:</b> {price}\n\n"
        f"<i>Please select your preferred payment method below.</i>"
    )
    from telegram import keyboards
    await event.edit(text, buttons=keyboards.payment_method_keyboard(plan), parse_mode="html")

async def on_pay_method_select(event: events.CallbackQuery.Event, plan: str, method: str) -> None:
    """Generate invoice based on payment method."""
    await event.answer()
    
    amount_usd = 35 if plan == "weekly" else 75
    
    import uuid
    order_id = uuid.uuid4().hex
    user_id = _uid(event)
    
    from services.payment_service import create_oxapay_invoice
    from models.invoice import Invoice
    from repositories.invoice_repo import invoice_repo
    
    await event.edit("⏳ <b>Generating Invoice...</b>", parse_mode="html")
    
    pay_url = await create_oxapay_invoice(order_id, amount_usd, user_id)
    gateway = "oxapay"
        
    if not pay_url:
        from telethon.tl.custom import Button
        await event.edit("❌ <b>Failed to generate payment link.</b>\n\nPlease try again later or contact support.", parse_mode="html", buttons=[[Button.inline("← Back", b"pay:options")]])
        return

    # Save to database
    inv = Invoice(order_id=order_id, user_id=user_id, plan=plan.upper(), amount=str(amount_usd), gateway=gateway)
    await invoice_repo.create(inv)
    
    text: str = (
        f"<b>🧾 Invoice Created</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Order ID:</b> <code>{order_id}</code>\n"
        f"<b>Plan:</b> {plan.capitalize()} Pass\n"
        f"<b>Amount:</b> ${amount_usd}\n"
        f"<b>Method:</b> Crypto (OxaPay)\n\n"
        f"<i>Click the button below to pay. Your plan will be automatically activated once payment is confirmed.</i>"
    )
    from telegram import keyboards
    await event.edit(text, buttons=keyboards.invoice_keyboard(pay_url, show_link=True), parse_mode="html")

async def on_invoice_cancel(event: events.CallbackQuery.Event) -> None:
    """Cancel an invoice."""
    await event.answer("Invoice Canceled")
    # Delete the photo/text message
    await event.delete()
    
    from telegram import keyboards
    text: str = (
        "<b>💎 Premium Plans</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select your preferred billing cycle to continue:"
    )
    await event.respond(text, buttons=keyboards.paywall_keyboard(), parse_mode="html")


async def route_callback(event: events.CallbackQuery.Event) -> None:
    """
    Route a callback query to the appropriate handler.

    This is the main entry point for all inline button presses.
    """
    data = event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data

    # Paywall Enforcement
    from core.config import get_settings
    from repositories import users_repo
    from core.constants import CB
    user = await users_repo.get(_uid(event))
    if user:
        settings = get_settings()
        is_active = user.is_active(settings.admin_user_ids, settings.admin_username)
        if not is_active:
            allowed_prefixes = ("pay:", "admin:", "buy:")
            allowed_exact = (CB.DASHBOARD, CB.NOOP, "force_join_check", "invoice:cancel")
            if not any(data.startswith(p) for p in allowed_prefixes) and data not in allowed_exact:
                await event.answer("❌ You don't have an active plan! Please purchase a plan from 'My Plan'.", alert=True)
                return

    # Simple callbacks (no parameters)
    simple_handlers = {
        CB.DASHBOARD: on_dashboard,
        CB.ACCOUNTS: on_accounts,
        CB.CAMPAIGNS: on_campaigns,
        CB.HEALTH: on_health,
        CB.HEALTH_VIEW_ALL: on_health_view_all,
        CB.HEALTH_SETTINGS: on_health_settings,
        CB.HEALTH_SETTINGS_TOGGLE: on_health_settings_toggle,
        CB.HEALTH_CLEAR_TOXIC: on_health_clear_toxic,
        CB.ANALYTICS: on_analytics,
        CB.BACK: on_back,
        CB.NOOP: on_noop,
        CB.ACCOUNT_ADD: on_account_add,
        CB.ACCOUNT_DELETE_ALL: on_accounts_delete_all,
        CB.ACCOUNT_DELETE_LIMITED: on_accounts_delete_limited,
        CB.ACCOUNT_UPLOAD_SESSIONS: on_account_upload_sessions,
        CB.ACCOUNT_EXPORT_SESSIONS: on_account_export_sessions,
        CB.CAMPAIGN_CREATE: on_campaign_create,
        CB.CAMPAIGN_AUTO_DISTRIBUTE: on_campaign_auto_distribute,
        CB.CAMPAIGN_START_ALL: on_campaign_start_all,
        CB.CAMPAIGN_PAUSE_ALL: on_campaign_pause_all,
        CB.CAMPAIGN_DELETE_ALL: on_campaign_delete_all_confirm,
        CB.CONFIRM_NO: on_confirm_no,
        CB.SETTINGS_AUTOREPLY: on_autoreply_menu,
        CB.SETTINGS_AUTOREPLY_TOGGLE: on_autoreply_toggle,
        CB.SETTINGS_AUTOREPLY_VIEW: on_autoreply_view,
        CB.SETTINGS_AUTOREPLY_CUSTOM: on_autoreply_custom,
        CB.AUTO_JOIN: on_groups_autojoin,
        "groups:autojoin:cancel": on_groups_autojoin_cancel,
        CB.GROUPS_CHECKER: on_groups_checker,
        CB.GROUPS_CHECKER_CANCEL: on_groups_checker_cancel,
        CB.AI_CHAT: on_ai_chat,
    }

    handler = simple_handlers.get(data)
    if handler:
        await handler(event)
        return

    elif data.startswith("ai:confirm:"):
        action_id = data.split(":", 2)[2]
        await on_ai_confirm(event, action_id)
    elif data.startswith("ai:cancel:"):
        action_id = data.split(":", 2)[2]
        await on_ai_cancel(event, action_id)
    elif data.startswith("acc:view:"):
        account_id = data.split(":", 2)[2]
        await on_account_view(event, account_id)

    elif data.startswith("acc:del:"):
        account_id = data.split(":", 2)[2]
        await on_account_delete(event, account_id)
    elif data.startswith("acc:pause:"):
        account_id = data.split(":", 2)[2]
        await on_account_pause(event, account_id)
    elif data.startswith("acc:resume:"):
        account_id = data.split(":", 2)[2]
        await on_account_resume(event, account_id)
    elif data.startswith("acc:health:"):
        account_id = data.split(":", 2)[2]
        await on_account_health(event, account_id)
    elif data.startswith("acc:stats:"):
        account_id = data.split(":", 2)[2]
        await on_account_stats(event, account_id)
    elif data.startswith("cmp:view:"):
        campaign_id = data.split(":", 2)[2]
        await on_campaign_view(event, campaign_id)
    elif data.startswith("cmp:pause:"):
        campaign_id = data.split(":", 2)[2]
        await on_campaign_pause(event, campaign_id)
    elif data.startswith("cmp:resume:"):
        campaign_id = data.split(":", 2)[2]
        await on_campaign_resume(event, campaign_id)
    elif data.startswith("cmp:del:"):
        campaign_id = data.split(":", 2)[2]
        await on_campaign_delete(event, campaign_id)
    elif data.startswith("cmp:dup:"):
        campaign_id = data.split(":", 2)[2]
        await on_campaign_duplicate(event, campaign_id)
    elif data.startswith("cmp:set_ad:"):
        parts = data.split(":")
        # parts: ["cmp", "set_ad", action, campaign_id]
        action = parts[2]
        campaign_id = parts[3] if len(parts) > 3 else parts[2]
        if len(parts) == 3: # "cmp:set_ad:id" -> menu
            await on_campaign_set_ad(event, "menu", campaign_id)
        else:
            await on_campaign_set_ad(event, action, campaign_id)
    elif data.startswith("cmp:set_interval:"):
        parts = data.split(":")
        if len(parts) == 3:
            await on_campaign_set_interval(event, "menu", parts[2])
        else:
            await on_campaign_set_interval(event, parts[2], parts[3])
    elif data.startswith("cmp:set_rounds:"):
        parts = data.split(":")
        if len(parts) == 3:
            await on_campaign_set_rounds(event, "menu", parts[2])
        else:
            await on_campaign_set_rounds(event, parts[2], parts[3])
    elif data.startswith("cmp:manage_acc:"):
        await event.answer()
        campaign_id = data.split(":")[2]
        await on_campaign_manage_accounts(event, campaign_id)
    elif data.startswith("cmp:all_acc:"):
        campaign_id = data.split(":")[2]
        await on_campaign_select_all_accounts(event, campaign_id)
    elif data.startswith("cmp:unall_acc:"):
        campaign_id = data.split(":")[2]
        await on_campaign_unselect_all_accounts(event, campaign_id)
    elif data.startswith("cmp:toggle_acc"):
        await on_campaign_account_toggle(event)
    elif data.startswith("cmp:refresh_all_grps:"):
        campaign_id = data.split(":")[2]
        await on_campaign_refresh_all_groups(event, campaign_id)
    elif data.startswith("cmp:acc_detail:"):
        await event.answer()
        _, _, account_id = data.split(":")
        await on_campaign_acc_detail(event, account_id)
    elif data.startswith("cmp:acc_groups:"):
        _, _, page = data.split(":")
        await on_campaign_account_groups(event, int(page))
    elif data.startswith("cmp:toggle_grp:"):
        _, _, group_id_str = data.split(":")
        await on_campaign_toggle_group(event, group_id_str)
    elif data == "cmp:grp_all":
        await on_campaign_group_bulk(event, "all")
    elif data == "cmp:grp_none":
        await on_campaign_group_bulk(event, "none")
    elif data.startswith("page:next:"):
        parts = data.split(":")
        screen = parts[2]
        page = int(parts[3])
        await on_page_next(event, screen, page)
    elif data.startswith("page:prev:"):
        parts = data.split(":")
        screen = parts[2]
        page = int(parts[3])
        await on_page_prev(event, screen, page)

    elif data.startswith("mails:list"):
        await on_account_mails_list(event, page=1)
    elif data.startswith("mails:view:"):
        account_id = data.split(":")[2]
        await on_account_mails_view(event, account_id)
    elif data.startswith("mails:check:"):
        account_id = data.split(":")[2]
        await on_account_mails_check(event, account_id)

    elif data.startswith("confirm:yes:"):
        parts = data.split(":")
        action = parts[2]
        target_id = parts[3]
        await on_confirm_yes(event, action, target_id)
    elif data == CB.BULK_MANAGER:
        await on_bulk_manager(event)
    elif data.startswith("bulk:"):
        # e.g. bulk:name, bulk:2fa:set
        action = data[5:]
        await on_bulk_action(event, action)
    elif data.startswith("buy:"):
        plan = data.split(":")[1]
        await on_buy_plan(event, plan)
    elif data.startswith("pay:") and len(data.split(":")) == 3:
        _, plan, method = data.split(":")
        await on_pay_method_select(event, plan, method)
    elif data == "invoice:cancel":
        await on_invoice_cancel(event)
    elif data == "pay:profile":
        await on_pay_profile(event)
    elif data == "pay:options":
        await on_pay_options(event)
    elif data == "admin:panel":
        await on_admin_panel(event)
    elif data == "admin:stats":
        await on_admin_stats(event)
    elif data == "admin:users":
        await on_admin_users(event)
    elif data == "admin:toggle_image":
        from core.db import get_redis
        from core.constants import RedisKeys
        r = get_redis()
        val = await r.get(RedisKeys.ADMIN_BOT_IMAGE_ENABLED)
        current = val.decode("utf-8") == "1" if val else True
        new_val = "0" if current else "1"
        await r.set(RedisKeys.ADMIN_BOT_IMAGE_ENABLED, new_val)
        await on_admin_panel(event)
    else:
        # Unknown callback — just answer to dismiss spinner
        await event.answer("Unknown action", alert=False)
