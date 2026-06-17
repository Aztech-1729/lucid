"""
Menu renderers — Pure text-building functions.

Every render function takes a cache dict and returns an HTML string.
NO database queries, NO Telegram API calls. Display-only.

UI design matches the Lucid Ads Bot premium dark-mode interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo


def _bar(value: float, total: float, length: int = 12) -> str:
    """Create a progress bar using Unicode block characters."""
    if total <= 0:
        return "░" * length
    ratio = min(value / total, 1.0)
    filled = int(ratio * length)
    return "█" * filled + "░" * (length - filled)


def _format_number(n: int | float) -> str:
    """Format a number with comma separators."""
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def _format_pct(value: float) -> str:
    """Format a percentage."""
    return f"{value:.2f}%"


def _format_iso_date(iso_str: str | None) -> str:
    """Format an ISO date string to readable format."""
    if not iso_str:
        return "N/A"
    try:
        # Pydantic JSON mode usually outputs '2026-05-29T21:00:00.000000'
        if not iso_str.endswith("Z") and "+" not in iso_str:
            iso_str += "Z"
        # Parse Z as UTC
        iso_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt = dt.astimezone(ZoneInfo("UTC"))
        return dt.strftime("%d %b %Y, %I:%M %p UTC")
    except (ValueError, TypeError):
        return str(iso_str)


def _time_ago(iso_str: str | None) -> str:
    """Convert ISO string to '5m ago' format."""
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str)
        diff = datetime.utcnow() - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        elif seconds < 3600:
            return f"{seconds // 60}m ago"
        elif seconds < 86400:
            return f"{seconds // 3600}h ago"
        else:
            return f"{seconds // 86400}d ago"
    except (ValueError, TypeError):
        return "N/A"


def _status_dot(status: str) -> str:
    """Get colored dot for account status."""
    dots = {
        "ACTIVE": "<tg-emoji emoji-id='5416081784641168838'>🟢</tg-emoji>",
        "HEALTHY": "<tg-emoji emoji-id='5416081784641168838'>🟢</tg-emoji>",
        "WARNING": "🟡",
        "PAUSED": "🟡",
        "LIMITED": "🟠",
        "BANNED": "⚫",
        "DISABLED": "⚫",
        "UNKNOWN": "⚫",
    }
    return dots.get(str(status).upper(), "⚫")


def _health_label(score: int) -> str:
    """Get health label from score."""
    if score >= 90:
        return "Free As Bird"
    elif score >= 70:
        return "Healthy"
    elif score >= 50:
        return "Low Trust"
    elif score >= 30:
        return "Limited"
    if score >= 10:
        return "Critical"


def _flood_risk(score: int) -> str:
    """Get flood risk label."""
    if score >= 80:
        return "Low"
    elif score >= 50:
        return "Medium"
    else:
        return "High"


# ── 1. MAIN MENU (DASHBOARD) ───────────────────────────────

def render_main_menu(user_name: str | None = None) -> str:
    """Render the welcome/main menu screen (before dashboard data loads)."""
    name = user_name or "User"
    return (
        f"🏠 <b>LUCID ADS BOT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Welcome back, <b>{name}</b>! 👋\n\n"
        f"Select an option from the menu below."
    )


def render_dashboard(data: dict | None) -> str:
    """Render the full dashboard with stats in tree style."""
    if not data:
        return (
            "<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>DASHBOARD</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏳ Loading dashboard data...\n"
            "Data will be available shortly."
        )

    username = data.get("username", "User")
    total_accs = data.get("total_accounts", 0)
    active_accs = data.get("active_accounts", 0)
    active_camps = data.get("active_campaigns", 0)
    total_fwd = data.get("total_forwarded", 0)
    successful = data.get("successful", 0)
    failed = data.get("failed", 0)
    success_rate = data.get("success_rate", 0)
    uptime = data.get("uptime", 99.9)

    healthy = data.get("healthy_accounts", 0)
    warning = data.get("warning_accounts", 0)
    limited = data.get("limited_accounts", 0)
    overall_health = data.get("overall_health", 0)
    health_total = max(healthy + limited, 1)

    return (
        f"<b><tg-emoji emoji-id=\"5447410659077661506\">🏠</tg-emoji> DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b><tg-emoji emoji-id=\"5461117441612462242\">👤</tg-emoji> User: @{username}</b>\n\n"
        f"<b><tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> OVERVIEW:</b>\n"
        f"├ <b>Total Accounts: {total_accs}</b>\n"
        f"├ <b>Active Accounts: {active_accs}</b>\n"
        f"├ <b>Active Campaigns: {active_camps}</b>\n"
        f"├ <b>Total Forwarded: {total_fwd}</b>\n"
        f"├ <b>Successful: {successful}</b>\n"
        f"├ <b>Failed: {failed}</b>\n"
        f"└ <b>Success Rate: {success_rate:.2f}%</b>\n\n"
        f"<b><tg-emoji emoji-id=\"5289562446216835198\">🛡️</tg-emoji> HEALTH:</b>\n"
        f"├ <b><tg-emoji emoji-id=\"5416081784641168838\">🟢</tg-emoji> Healthy: {healthy} ({healthy/health_total*100:.1f}%)</b>\n"
        f"├ <b><tg-emoji emoji-id=\"5411225014148014586\">🟠</tg-emoji> Limited: {limited} ({limited/health_total*100:.1f}%)</b>\n"
        f"└ <b><tg-emoji emoji-id=\"5438496463044752972\">⭐</tg-emoji> Overall Score: {overall_health}%</b>"
    )


# ── 2. ACCOUNTS LIST ───────────────────────────────────────

def render_account_list(data: dict | None) -> str:
    """Render the accounts list total count only."""
    if not data:
        return (
            "📱 <b>ACCOUNTS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No accounts found.\n"
            "Press ➕ <b>Add Account</b> to get started."
        )

    total_items = data.get("total_items", 0)
    return f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> Total: <b>{total_items}</b> accounts"


# ── 3. ACCOUNT DETAILS ─────────────────────────────────────

def render_account_detail(data: dict | None) -> str:
    """Render account detail view in tree style."""
    if not data:
        return (
            "📱 <b>ACCOUNT DETAILS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Account data not available."
        )

    phone = data.get("phone", "Unknown")
    health = data.get("health_score", 0)
    status_disp = data.get("health_display")
    if not status_disp:
        # Fallback for old cache entries
        status_disp = _health_label(health)
        
    flood_risk = _flood_risk(health)
    success_count = data.get("success_count", 0)
    failure_count = data.get("failure_count", 0)
    total = success_count + failure_count
    rate = (success_count / total * 100) if total > 0 else 0

    return (
        f"📱 <b>ACCOUNT DETAILS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📞 <b>{phone}</b>  <b>{status_disp}</b>\n\n"
        f"<tg-emoji emoji-id='5458603043203327669'>ℹ️</tg-emoji> <b>INFO:</b>\n"
        f"├ <b>Health Score: {health}/100</b>\n"
        f"├ <b>Status: {status_disp}</b>\n"
        f"├ <b>Flood Risk: {flood_risk}</b>\n"
        f"├ <b>SpamBot Check: {_time_ago(data.get('last_checked_at'))}</b>\n"
        f"├ <b>Last Active: {_time_ago(data.get('last_used_at'))}</b>\n"
        f"└ <b>Added On: {_format_iso_date(data.get('created_at'))}</b>\n\n"
        f"<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> <b>STATS:</b>\n"
        f"├ <b>Total Forwarded: {total}</b>\n"
        f"├ <b>Successful: {success_count} ({rate:.2f}%)</b>\n"
        f"├ <b>Failed: {failure_count} ({100-rate:.2f}%)</b>\n"
        f"├ <b>Flood Waits: {len(data.get('flood_wait_history', []))}</b>\n"
        f"└ <b>Session: Valid</b>"
    )


# ── 4. CAMPAIGNS LIST ──────────────────────────────────────

def render_campaign_list(data: dict | None) -> str:
    """Render the campaign list page."""
    if not data:
        return (
            "<tg-emoji emoji-id='5424818078833715060'>📢</tg-emoji> <b>CAMPAIGNS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No campaigns found.\n"
            "Press ➕ <b>New Campaign</b> to create one."
        )

    pagination = data.get("pagination", {})
    page = pagination.get("current_page", 1)
    total_pages = pagination.get("total_pages", 1)
    campaigns = data.get("campaigns", [])

    lines = [
        f"<tg-emoji emoji-id='5424818078833715060'>📢</tg-emoji> <b>CAMPAIGNS</b> (Page {page}/{total_pages})",
        "━━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    for c in campaigns:
        name = c.get("name", "Untitled")
        status = c.get("status", "DRAFT")
        status_emoji = {"ACTIVE": "<tg-emoji emoji-id='5416081784641168838'>🟢</tg-emoji>", "PAUSED": "🟡", "DRAFT": "<tg-emoji emoji-id='5395444784611480792'>📝</tg-emoji>", "COMPLETED": "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji>"}.get(status, "⚫")
        status_label = f"<code>{status}</code>"
        accounts = c.get("account_count", 0)
        groups = c.get("group_count", 0)

        lines.append(
            f"{status_emoji} <b>{name}</b>  {status_label}\n"
            f"      Accounts: {accounts} | Groups: {groups}"
        )

    return "\n".join(lines)


# ── 5. CAMPAIGN DETAILS ────────────────────────────────────

def render_campaign_detail(data: dict | None) -> str:
    """Render campaign detail view in tree style."""
    if not data:
        return (
            "<tg-emoji emoji-id='5424818078833715060'>📢</tg-emoji> <b>CAMPAIGN DETAILS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Campaign data not available."
        )

    name = data.get("name", "Untitled")
    status = data.get("status", "DRAFT")
    campaign_id = data.get("id", "—")
    accounts = data.get("account_count", 0)
    groups = data.get("group_count", 0)
    created = data.get("created_at", None)
    stats = data.get("stats", {})
    total_sent = data.get("total_sent") or stats.get("total_sent", 0)
    success = data.get("success_count") or stats.get("total_success", 0)
    failed = data.get("failure_count") or stats.get("total_failed", 0)
    
    rate = (success / total_sent * 100) if total_sent > 0 else 0
    fail_rate = (failed / total_sent * 100) if total_sent > 0 else 0

    status_badge = {"ACTIVE": "<tg-emoji emoji-id='5416081784641168838'>🟢</tg-emoji> Active", "PAUSED": "🟡 Paused", "DRAFT": "<tg-emoji emoji-id='5395444784611480792'>📝</tg-emoji> Draft", "COMPLETED": "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Done"}.get(status, status)

    ad_type = data.get("ad_type", "custom")
    if ad_type == "custom":
        msg = data.get("message", "") or "None"
        msg_disp = f"{msg[:30]}..." if len(msg) > 30 else msg
        ad_disp = f"<b>Custom ({msg_disp})</b>"
    else:
        link = data.get("forward_link", "") or "None"
        ad_disp = f"<b>Forward ({link})</b>"

    return (
        f"<tg-emoji emoji-id='5424818078833715060'>📢</tg-emoji> <b>CAMPAIGN DETAILS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<tg-emoji emoji-id='5424818078833715060'>📢</tg-emoji> <b>{name}</b>  {status_badge}\n\n"
        f"<tg-emoji emoji-id='5458603043203327669'>ℹ️</tg-emoji> <b>INFO:</b>\n"
        f"├ <b>ID: {campaign_id[:12]}</b>\n"
        f"├ <b>Accounts: {accounts}</b>\n"
        f"├ <b>Groups: {groups}</b>\n"
        f"└ <b>Created: {_format_iso_date(created)}</b>\n\n"
        f"<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> <b>STATS:</b>\n"
        f"├ <b>Total Forwarded: {total_sent}</b>\n"
        f"├ <b>Successful: {success} ({rate:.2f}%)</b>\n"
        f"└ <b>Failed: {failed} ({fail_rate:.2f}%)</b>\n\n"
        f"<tg-emoji emoji-id='5341715473882955310'>⚙️</tg-emoji> <b>SETTINGS:</b>\n"
        f"├ <b>Ad Type: {ad_disp}</b>\n"
        f"├ <b>Interval: {data.get('group_delay_seconds', 15)}s / {data.get('round_delay_seconds', 600)}s</b>\n"
        f"└ <b>Max Rounds: {'24/7' if data.get('max_rounds', 0) == 0 else data.get('max_rounds')}</b>"
    )


# ── 6. ANALYTICS OVERVIEW ──────────────────────────────────

def render_analytics(data: dict | None) -> str:
    """Render analytics overview with all-time stats in tree style."""
    if not data:
        return (
            "<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>ANALYTICS OVERVIEW</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📅 Period: All Time\n\n"
            "No analytics data yet.\n"
            "Start a campaign to see stats here."
        )

    total_sent = data.get("total_sent", 0)
    successful = data.get("total_success", 0)
    failed = data.get("total_failed", 0)
    rate = (successful / total_sent * 100) if total_sent > 0 else 0
    uptime = 99.9

    return (
        f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>ANALYTICS OVERVIEW</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Period: <b>All Time</b>\n\n"
        f"<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> <b>PERFORMANCE:</b>\n"
        f"├ <b>Total Messages: {total_sent}</b>\n"
        f"├ <b>Successful: {successful}</b>\n"
        f"├ <b>Failed: {failed}</b>\n"
        f"└ <b>Success Rate: {rate:.2f}%</b>"
    )


# ── 7. HEALTH OVERVIEW ─────────────────────────────────────


def render_analytics_detailed(data: dict | None) -> str:
    """Render detailed analytics view."""
    if not data:
        return (
            "<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> <b>DETAILED ANALYTICS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No detailed data available yet."
        )

    return (
        "<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> <b>DETAILED ANALYTICS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Detailed metrics and graphs will be displayed here.\n\n"
        f"<i>Coming soon in the next update!</i>"
    )


# ── 7. HEALTH OVERVIEW ─────────────────────────────────────

def render_health_overview(data: dict | None) -> str:
    """Render health overview in tree style."""
    if not data:
        return (
            "🩺 <b>ACCOUNTS HEALTH</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No health data available yet.\n"
            "Health checks will run automatically."
        )

    counts = data.get("counts", {})
    healthy = counts.get("HEALTHY", 0)
    warning = counts.get("WARNING", 0)
    limited = counts.get("LIMITED", 0)
    banned = counts.get("BANNED", 0)
    total = data.get("total_accounts", 0) or 1
    overall = data.get("overall_health_pct", 0)

    return (
        f"<b><tg-emoji emoji-id=\"5289562446216835198\">🛡️</tg-emoji> ACCOUNTS HEALTH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b><tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> STATUS:</b>\n"
        f"├ <b><tg-emoji emoji-id=\"5416081784641168838\">🟢</tg-emoji> Healthy: {healthy} ({healthy/total*100:.1f}%)</b>\n"
        f"└ <b><tg-emoji emoji-id=\"5411225014148014586\">🟠</tg-emoji> Limited: {limited} ({limited/total*100:.1f}%)</b>\n\n"
        f"<b><tg-emoji emoji-id=\"5438496463044752972\">⭐</tg-emoji> Overall Health Score: {overall}%</b>"
    )


def render_health_settings() -> str:
    """Render health settings."""
    return (
        "<tg-emoji emoji-id='5341715473882955310'>⚙️</tg-emoji> <b>HEALTH SETTINGS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Configure how the bot handles account health.\n\n"
        "<b>Auto-Pause Unhealthy:</b> If ON, the bot will automatically pause ad forwarding for accounts that drop into the WARNING state, protecting them from bans."
    )


def render_session_import_progress(
    filename: str, total_count: int, success: int, failed: int
) -> str:
    """Renders live progress of a session import."""
    text = (
        f"📦 <b>Session Import:</b> <code>{filename}</code>\n"
        f"├ <b>Total Detected:</b> {total_count}\n"
        f"├ <b>Success:</b> {success} <tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji>\n"
        f"└ <b>Failed:</b> {failed} <tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji>\n\n"
        f"<i>Please wait, importing accounts... ⏳</i>"
    )
    return text


def render_bulk_progress(
    action_name: str, success: int, failed: int, total: int, status: str = "Processing... ⏳"
) -> str:
    """Renders live progress of a bulk account action."""
    processed = success + failed
    text = (
        f"👥 <b>Bulk Action:</b> <i>{action_name}</i>\n"
        f"├ <b>Total Accounts:</b> {total}\n"
        f"├ <b>Processed:</b> {processed} / {total}\n"
        f"├ <b>Success:</b> {success} <tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji>\n"
        f"└ <b>Failed:</b> {failed} <tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji>\n\n"
        f"<i>{status}</i>"
    )
    return text


def render_groups_list(phone: str, selected_count: int, total_count: int) -> str:
    """Render the groups list for a specific account."""
    return (
        f"👥 <b>GROUPS MANAGEMENT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Account:</b> {phone}\n"
        f"<b>Selected Groups:</b> {selected_count} / {total_count}\n\n"
        f"Select the groups you want this account to forward ads to."
    )


def render_autojoin_prompt() -> str:
    """Render the auto-join instructions."""
    return (
        "<b><tg-emoji emoji-id='6256032707470428424'>🤖</tg-emoji> AUTO JOIN GROUPS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>👇 No buttons needed! Just do ONE of the following right here in the chat:</b>\n\n"
        "<b>📁 Option 1: Paste your <code>t.me/addlist/...</code> folder link (Instant Join)</b>\n\n"
        "<b>📄 Option 2: Upload a <code>.txt</code> file containing group links (Slower Join)</b>"
    )


def render_autojoin_progress(joined: int, failed: int, total: int, status: str = "Processing", groups_count: int = 0, accounts_count: int = 0) -> str:
    """Render the real-time joining progress."""
    progress = (joined + failed)
    pct = (progress / total * 100) if total > 0 else 0
    
    return (
        f"<tg-emoji emoji-id='6256032707470428424'>🤖</tg-emoji> <b>AUTO JOIN PROGRESS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏳ <b>Status: {status}</b>\n\n"
        f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>STATS:</b>\n"
        f"├ <b>Groups: {groups_count}</b>\n"
        f"├ <b>Accounts: {accounts_count}</b>\n"
        f"├ <b>Joined: {joined}</b>\n"
        f"├ <b>Failed: {failed}</b>\n"
        f"└ <b>Target Joins: {total}</b>\n\n"
        f"<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> <b>Progress: {progress}/{total} ({pct:.1f}%)</b>\n"
        f"{_bar(progress, total, 16)}"
    )


# ── SETTINGS ────────────────────────────────────────────────

def render_autoreply_menu(enabled: bool, has_custom: bool) -> str:
    """Render Auto Reply settings in tree style."""
    status = "<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Enabled" if enabled else "<tg-emoji emoji-id='5260293700088511294'>❌</tg-emoji> Disabled"
    msg_status = "Custom (Set)" if has_custom else "Default"
    
    return (
        f"💬 <b>AUTO REPLY SETTINGS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Automatically reply to direct messages sent to your accounts.\n\n"
        f"<tg-emoji emoji-id='5458603043203327669'>ℹ️</tg-emoji> <b>CONFIG:</b>\n"
        f"├ <b>Status: {status}</b>\n"
        f"└ <b>Message: {msg_status}</b>\n\n"
        f"Use the buttons below to configure."
    )


def render_autoreply_view(text: str) -> str:
    """Render current custom auto reply text."""
    return (
        f"💬 <b>CURRENT AUTO REPLY</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<code>{text}</code>"
    )

# ── 9. PERSONAL AI ──────────────────────────────────────────

def render_ai_welcome() -> str:
    """Render the AI welcome screen."""
    return (
        "<tg-emoji emoji-id='6256032707470428424'>🤖</tg-emoji> <b>PERSONAL AI ASSISTANT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Hello! I am your intelligent agent.\n\n"
        "I can fetch live statistics, diagnose campaign issues, or securely perform actions for you.\n\n"
        "What would you like me to do?\n"
        "(Just type your message below)"
    )

def render_ai_action(description: str) -> str:
    """Render the AI Action confirmation prompt."""
    return (
        "<tg-emoji emoji-id='5420323339723881652'>⚠️</tg-emoji> <b>AI ACTION PROPOSED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "The AI has proposed the following action:\n\n"
        f"👉 <b>{description}</b>\n\n"
        "<i>Do you want to authorize this action?</i>"
    )


def render_profile(user_data: dict, is_active: bool) -> str:
    """Render the user profile and subscription status."""
    plan = user_data.get("plan_type", "NONE")
    ends_at = user_data.get("subscription_ends_at")
    
    status = "<tg-emoji emoji-id='5416081784641168838'>🟢</tg-emoji> ACTIVE" if is_active else "🔴 EXPIRED"
        
    expiry_str = "Expired"
    if is_active and ends_at:
        expiry_str = ends_at.strftime("%Y-%m-%d %H:%M UTC")

    return (
        f"<tg-emoji emoji-id='5461117441612462242'>👤</tg-emoji> <b>USER PROFILE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>User ID:</b> <code>{user_data.get('user_id')}</code>\n"
        f"<b>Status:</b> {status}\n\n"
        f"<tg-emoji emoji-id='5438496463044752972'>💳</tg-emoji> <b>CURRENT PLAN</b>\n"
        f"├ <b>Tier:</b> {plan}\n"
        f"└ <b>Expires:</b> {expiry_str}\n\n"
        f"<i>Tap the button below to purchase or upgrade your plan.</i>"
    )

def render_paywall() -> str:
    """Render the paywall message."""
    return (
        f"<tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> <b>LUCID ADS PREMIUM</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Unlock the full power of Lucid Ads Bot to automate your campaigns.\n\n"
        f"<tg-emoji emoji-id=\"5461151367559141950\">✨</tg-emoji> <b>Features Included:</b>\n"
        f"• Unlimited Accounts\n"
        f"• Unlimited Campaigns\n"
        f"• Health Monitoring & Auto Pause\n"
        f"• Advanced Anti-Ban Delays\n"
        f"• Auto-Join & Auto-Reply\n"
        f"• Personal AI Assistant\n\n"
        f"<i>Select a plan below to contact the admin for instant activation.</i>"
    )

def render_admin_panel(stats: dict = None) -> str:
    """Render the main admin dashboard."""
    return (
        f"👑 <b>ADMIN PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Manage users and subscriptions directly from Telegram.\n\n"
        f"🛠 <b>COMMANDS:</b>\n"
        f"<code>/grant [user_id] [weekly|monthly|yearly]</code>\n"
        f"<i>Instantly activates a plan for a user.</i>\n\n"
        f"<code>/revoke [user_id]</code>\n"
        f"<i>Instantly cancels a user's subscription.</i>\n\n"
        f"Select an option below to view statistics or active users."
    )

def render_admin_stats(stats: dict) -> str:
    """Render admin stats."""
    return (
        f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>SYSTEM STATISTICS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 <b>Total Users:</b> {stats.get('total_users', 0)}\n"
        f"💎 <b>Active Subscriptions:</b> {stats.get('active_subscriptions', 0)}\n\n"
        f"<i>Statistics are updated in real-time.</i>"
    )
