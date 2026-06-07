"""
Inline keyboard builders — Returns Telethon Button grids.

Every function returns a list of button rows for use with event.edit().
NO database queries, NO API calls. Pure button layout functions.

UI layout matches the Lucid Ads Bot premium interface mockup.
"""

from __future__ import annotations

from typing import Any

from telethon import Button

from core.constants import CB

def _b(text: str) -> str:
    """Convert text to Unicode bold (mathematical bold)."""
    return text

# ── 1. MAIN MENU (DASHBOARD) ───────────────────────────────

from telethon.tl.types import KeyboardButtonStyle

def main_menu_keyboard() -> list[list[Button]]:
    """Main menu buttons — 2-column grid + full-width My Plan."""
    
    btn_accounts = Button.inline(_b("Accounts"), CB.ACCOUNTS)
    btn_accounts.style = KeyboardButtonStyle(bg_success=True, icon=6296218646284863141)
    
    btn_campaigns = Button.inline(_b("Campaigns"), CB.CAMPAIGNS)
    btn_campaigns.style = KeyboardButtonStyle(bg_success=True, icon=5424818078833715060)
    
    btn_analytics = Button.inline(_b("Analytics"), CB.ANALYTICS)
    btn_analytics.style = KeyboardButtonStyle(bg_primary=True, icon=5231200819986047254)
    
    btn_health = Button.inline(_b("Health"), CB.HEALTH)
    btn_health.style = KeyboardButtonStyle(bg_primary=True, icon=5289562446216835198)
    
    btn_autoreply = Button.inline(_b("Auto Reply"), CB.SETTINGS_AUTOREPLY)
    btn_autoreply.style = KeyboardButtonStyle(bg_primary=True, icon=5253742260054409879)
    
    btn_autojoin = Button.inline(_b("Auto Join"), CB.AUTO_JOIN)
    btn_autojoin.style = KeyboardButtonStyle(bg_primary=True, icon=5224607267797606837)
    
    btn_ai = Button.inline(_b("Personal AI"), CB.AI_CHAT)
    btn_ai.style = KeyboardButtonStyle(bg_success=True, icon=5877651964208091297)

    btn_profile = Button.inline(_b("My Plan"), "pay:profile")
    btn_profile.style = KeyboardButtonStyle(bg_success=True, icon=5231200819986047254)

    grid = [
        [btn_accounts, btn_campaigns],
        [btn_analytics, btn_health],
        [btn_autoreply, btn_autojoin],
        [btn_ai, btn_profile],
    ]
    
    return grid

def build_dashboard_keyboard(is_admin: bool = False) -> list[list[Button]]:
    grid = main_menu_keyboard()
    from core.config import get_settings
    from telethon.tl.types import KeyboardButtonStyle
    settings = get_settings()
    admin_url = f"https://t.me/{settings.admin_username.replace('@', '')}"
    
    if is_admin:
        btn_admin = Button.inline(_b("Admin Panel"), "admin:panel")
        btn_admin.style = KeyboardButtonStyle(bg_primary=True, icon=5231200819986047254)
        grid.append([btn_admin])
        
    btn_owner = Button.url(f"Owner / Developer: {settings.admin_username}", admin_url)
    btn_owner.style = KeyboardButtonStyle(bg_danger=True, icon=6235572922086331108)
    grid.append([btn_owner])
    return grid


# ── 2. ACCOUNTS LIST ──────────────────────────────────────

def account_list_keyboard(
    accounts: list[dict],
    pagination: dict,
    action_prefix: str = "acc:view",
    show_actions: bool = True,
    screen: str = "accounts"
) -> list[list[Button]]:
    """Account list with account buttons, pagination, and actions."""
    rows: list[list[Button]] = []

    # Account buttons — one per row with phone + health
    for acc in accounts:
        acc_id = acc.get("id", "")
        phone = acc.get("phone", "???")
        health = acc.get("health_score", 0)
        if health >= 80:
            dot_icon = 5416081784641168838
            btn_text = f"{phone}  •  Health: {health}"
        elif health >= 50:
            dot_icon = None
            btn_text = f"🟡 {phone}  •  Health: {health}"
        else:
            dot_icon = None
            btn_text = f"🔴 {phone}  •  Health: {health}"
            
        btn_style = "success" if health >= 80 else "primary" if health >= 50 else "danger"
        rows.append([
            Button.inline(
                btn_text,
                f"{action_prefix}:{acc_id}",
                style=btn_style,
                icon=dot_icon
            )
        ])

    # Pagination row
    current = pagination.get("current_page", 1)
    total = pagination.get("total_pages", 1)

    if total > 1:
        nav_row = []
        if current > 1:
            nav_row.append(Button.inline(_b("⏪ First"), f"page:next:{screen}:1", style="primary"))
            nav_row.append(Button.inline(_b("◀ Prev"), f"page:prev:{screen}:{current - 1}", style="primary"))
        nav_row.append(Button.inline(f"📄 {current}/{total}", CB.NOOP, style="primary"))
        if current < total:
            nav_row.append(Button.inline(_b("Next ▶"), f"page:next:{screen}:{current + 1}", style="primary"))
            nav_row.append(Button.inline(_b("Last ⏩"), f"page:next:{screen}:{total}", style="primary"))
        rows.append(nav_row)

    # Action row
    if show_actions:
        rows.append([
            Button.inline(_b("Bulk Account Manager"), CB.BULK_MANAGER, style="primary", icon=5210956306952758910),
        ])
        rows.append([
            Button.inline(_b("Add Account"), CB.ACCOUNT_ADD, style="success", icon=5397916757333654639),
            Button.inline(_b("Upload Sessions"), CB.ACCOUNT_UPLOAD_SESSIONS, style="success", icon=5282843764451195532),
        ])
        rows.append([
            Button.inline(_b("Remove Limited"), CB.ACCOUNT_DELETE_LIMITED, style="danger", icon=5445267414562389170),
            Button.inline(_b("Remove All"), CB.ACCOUNT_DELETE_ALL, style="danger", icon=5445267414562389170),
        ])
        rows.append([
            Button.inline(_b("Refresh"), CB.ACCOUNTS, style="primary", icon=5386367538735104399),
        ])

    # Back
    rows.append([Button.inline(_b("← Back"), CB.DASHBOARD, style="danger")])

    return rows


# ── 3. ACCOUNT DETAILS ────────────────────────────────────

def account_detail_keyboard(account_id: str, status: str, back_cb: str = CB.ACCOUNTS) -> list[list[Button]]:
    """Account detail action buttons."""
    rows = []

    # Pause/Resume based on status
    if status in ("ACTIVE", "WARNING", "HEALTHY"):
        rows.append([
            Button.inline(_b("⏸ Pause"), f"acc:pause:{account_id}", style="danger"),
            Button.inline(_b("Remove"), f"acc:del:{account_id}", style="danger", icon=5445267414562389170),
        ])
    elif status == "PAUSED":
        rows.append([
            Button.inline(_b("▶️ Resume"), f"acc:resume:{account_id}", style="success"),
            Button.inline(_b("Remove"), f"acc:del:{account_id}", style="danger", icon=5445267414562389170),
        ])
    else:
        rows.append([
            Button.inline(_b("Remove"), f"acc:del:{account_id}", style="danger", icon=5445267414562389170),
        ])

    rows.append([Button.inline(_b("← Back"), back_cb, style="danger")])

    return rows


# ── 3.5 BULK ACCOUNT MANAGER ───────────────────────────────

def bulk_manager_keyboard() -> list[list[Button]]:
    """Bulk actions for all accounts."""
    return [
        [
            Button.inline(_b("Change Name"), CB.BULK_NAME, style="primary", icon=5395444784611480792),
            Button.inline(_b("📄 Change Bio"), CB.BULK_BIO, style="primary"),
        ],
        [
            Button.inline(_b("Remove Usernames"), CB.BULK_REMOVE_USERNAME, style="danger", icon=5445267414562389170),
        ],
        [
            Button.inline(_b("🖼 Change Photo"), CB.BULK_PHOTO, style="primary"),
            Button.inline(_b("Remove Photo"), CB.BULK_REMOVE_PHOTO, style="danger", icon=5445267414562389170),
        ],
        [
            Button.inline(_b("💬 Clean DMs"), CB.BULK_CLEAN_DMS, style="danger"),
            Button.inline(_b("📦 Archive Chats"), CB.BULK_ARCHIVE, style="primary"),
        ],
        [
            Button.inline(_b("🚪 Leave Groups/Channels"), CB.BULK_LEAVE_GROUPS, style="danger"),
            Button.inline(_b("Remove All Folders"), CB.BULK_REMOVE_FOLDERS, style="danger", icon=5445267414562389170),
        ],
        [
            Button.inline(_b("🔐 2FA Manager"), CB.BULK_2FA, style="primary"),
        ],
        [Button.inline(_b("← Back"), CB.ACCOUNTS, style="danger")],
    ]


def bulk_2fa_keyboard() -> list[list[Button]]:
    """Bulk 2FA actions for all accounts."""
    return [
        [
            Button.inline(_b("🔐 Set/Change 2FA"), CB.BULK_2FA_SET, style="primary"),
        ],
        [
            Button.inline(_b("Remove 2FA"), CB.BULK_2FA_REMOVE, style="danger", icon=5445267414562389170),
        ],
        [Button.inline(_b("← Back"), CB.BULK_MANAGER, style="danger")],
    ]

def bulk_progress_keyboard() -> list[list[Button]]:
    """Keyboard shown during active bulk operations."""
    return [
        [Button.inline(_b("Cancel"), CB.BULK_CANCEL, style="danger", icon=5260293700088511294)]
    ]


# ── 4. CAMPAIGNS LIST ─────────────────────────────────────

def campaign_list_keyboard(
    campaigns: list[dict],
    pagination: dict,
) -> list[list[Button]]:
    """Campaign list with campaign buttons, pagination, and actions."""
    rows: list[list[Button]] = []

    for c in campaigns:
        cmp_id = c.get("id", "")
        name = c.get("name", "Untitled")
        status = c.get("status", "DRAFT")
        if status == "DRAFT":
            btn_text = f"{name} • {status}"
            btn_icon = 5395444784611480792
        elif status == "ACTIVE":
            btn_text = f"{name} • {status}"
            btn_icon = 5416081784641168838
        else:
            emoji = {"PAUSED": "🟡", "COMPLETED": "✅"}.get(status, "⚫")
            btn_text = f"{emoji} {name} • {status}"
            btn_icon = None
            
        btn_style = "success" if status in ("ACTIVE", "COMPLETED") else "primary" if status == "DRAFT" else "danger"

        rows.append([
            Button.inline(
                btn_text,
                f"cmp:view:{cmp_id}",
                style=btn_style,
                icon=btn_icon
            )
        ])

    # Pagination
    current = pagination.get("current_page", 1)
    total = pagination.get("total_pages", 1)

    if total > 1:
        nav_row = []
        if current > 1:
            nav_row.append(Button.inline("⏪ First", "page:next:campaigns:1", style="primary"))
            nav_row.append(Button.inline("◀ Prev", f"page:prev:campaigns:{current - 1}", style="primary"))
        nav_row.append(Button.inline(f"📄 {current}/{total}", CB.NOOP, style="primary"))
        if current < total:
            nav_row.append(Button.inline("Next ▶", f"page:next:campaigns:{current + 1}", style="primary"))
            nav_row.append(Button.inline("Last ⏩", f"page:next:campaigns:{total}", style="primary"))
        rows.append(nav_row)

    # Actions
    rows.append([
        Button.inline(_b("New Campaign"), CB.CAMPAIGN_CREATE, style="success", icon=5397916757333654639),
        Button.inline(_b("Refresh"), CB.CAMPAIGNS, style="primary", icon=5386367538735104399),
    ])

    rows.append([Button.inline(_b("← Back"), CB.DASHBOARD, style="danger")])

    return rows


# ── 5. CAMPAIGN DETAILS ───────────────────────────────────

def campaign_detail_keyboard(campaign_id: str, status: str) -> list[list[Button]]:
    """Campaign detail action buttons."""
    rows = []

    # Start/Pause
    if status in ("DRAFT", "PAUSED"):
        rows.append([
            Button.inline(_b("▶️ Start"), f"cmp:resume:{campaign_id}", style="success"),
        ])
    elif status == "ACTIVE":
        rows.append([
            Button.inline(_b("⏸ Pause"), f"cmp:pause:{campaign_id}", style="danger"),
        ])

    # Configuration
    rows.append([
        Button.inline(_b("Set Ad"), f"cmp:set_ad:{campaign_id}", style="primary", icon=5395444784611480792),
        Button.inline(_b("⏱ Set Interval"), f"cmp:set_interval:{campaign_id}", style="primary"),
    ])
    rows.append([
        Button.inline(_b("🔄 Set Rounds"), f"cmp:set_rounds:{campaign_id}", style="primary"),
        Button.inline(_b("👥 Manage Accounts"), f"cmp:manage_acc:{campaign_id}", style="primary"),
    ])



    # Delete / Duplicate
    rows.append([
        Button.inline(_b("📋 Duplicate"), f"cmp:dup:{campaign_id}", style="primary"),
        Button.inline(_b("Delete"), f"cmp:del:{campaign_id}", style="danger", icon=5445267414562389170),
    ])

    rows.append([Button.inline(_b("← Back"), CB.CAMPAIGNS, style="danger")])

    return rows

def campaign_set_ad_keyboard(campaign_id: str, current_ad_type: str = "custom") -> list[list[Button]]:
    """Menu to choose ad type."""
    c_mark = "✅ " if current_ad_type == "custom" else ""
    f_mark = "✅ " if current_ad_type == "forward" else ""
    return [
        [
            Button.inline(f"{c_mark}Custom Message", f"cmp:set_ad:custom:{campaign_id}", style="primary", icon=5395444784611480792),
            Button.inline(f"{f_mark}🔗 Forward Post", f"cmp:set_ad:forward:{campaign_id}", style="primary"),
        ],
        [Button.inline("← Back", f"cmp:view:{campaign_id}", style="danger")],
    ]


def campaign_set_interval_keyboard(campaign_id: str) -> list[list[Button]]:
    """Menu to set intervals."""
    return [
        [
            Button.inline("⏱ Group Delay", f"cmp:set_interval:group:{campaign_id}", style="primary"),
            Button.inline("⏱ Round Delay", f"cmp:set_interval:round:{campaign_id}", style="primary"),
        ],
        [Button.inline("← Back", f"cmp:view:{campaign_id}", style="danger")],
    ]


def campaign_set_rounds_keyboard(campaign_id: str, max_rounds: int = 0) -> list[list[Button]]:
    """Menu to set rounds."""
    m_mark = "✅ " if max_rounds > 0 else ""
    i_mark = "✅ " if max_rounds == 0 else ""
    return [
        [
            Button.inline(f"{m_mark}🔢 Set Max Rounds", f"cmp:set_rounds:max:{campaign_id}", style="primary"),
            Button.inline(f"{i_mark}♾️ Run 24/7", f"cmp:set_rounds:infinite:{campaign_id}", style="primary"),
        ],
        [Button.inline("← Back", f"cmp:view:{campaign_id}", style="danger")],
    ]


def campaign_manage_accounts_keyboard(
    campaign_id: str, 
    accounts: list[Any], 
    assigned_ids: list[str],
    pagination: dict
) -> list[list[Button]]:
    """Menu to select accounts for a campaign with pagination."""
    rows = []
    
    # 1. Accounts List
    for acc in accounts:
        acc_id = str(acc.get("id", ""))
        phone = acc.get("phone", "Unknown")
        is_assigned = acc_id in assigned_ids
        mark = "🟢" if is_assigned else "🔴"
        btn_style = "success" if is_assigned else "danger"
        rows.append([Button.inline(f"{mark} {phone}", f"cmp:acc_detail:{acc_id}", style=btn_style)])
        
    # 2. Quick Actions
    rows.append([
        Button.inline(_b("🔄 Refresh All Groups"), f"cmp:refresh_all_grps:{campaign_id}", style=None),
    ])
    
    total_items = pagination.get("total_items", 0)
    if total_items > 0 and len(assigned_ids) >= total_items:
        rows.append([
            Button.inline(_b("Unselect All Accounts"), f"cmp:unall_acc:{campaign_id}", style="danger", icon=5260293700088511294),
        ])
    else:
        rows.append([
            Button.inline(_b("Select All Accounts"), f"cmp:all_acc:{campaign_id}", style="success", icon=5206607081334906820),
        ])
    
    # 3. Pagination
    current = pagination.get("current_page", 1)
    total = pagination.get("total_pages", 1)
    
    if total > 1:
        nav_row = []
        if current > 1:
            nav_row.append(Button.inline(_b("⬅️ Prev"), f"page:prev:cmp_acc:{current-1}", style="primary"))
        
        nav_row.append(Button.inline(f"📄 {current}/{total}", CB.NOOP, style="primary"))
        
        if current < total:
            nav_row.append(Button.inline(_b("Next ➡️"), f"page:next:cmp_acc:{current+1}", style="primary"))
        rows.append(nav_row)

    # 4. Back
    rows.append([Button.inline(_b("← Back"), f"cmp:view:{campaign_id}", style="danger")])
    return rows


def campaign_account_detail_keyboard(campaign_id: str, account_id: str, is_assigned: bool) -> list[list[Button]]:
    """Account details within a campaign."""
    toggle_text = _b("Remove from Campaign") if is_assigned else _b("Add to Campaign")
    icon_val = 5260293700088511294 if is_assigned else 5206607081334906820
    rows = [
        [
            Button.inline(toggle_text, "cmp:toggle_acc", style="primary", icon=icon_val),
        ],
        [
            Button.inline(_b("👥 Select Groups"), "cmp:acc_groups:1", style="primary"),
        ],
        [Button.inline(_b("← Back"), f"cmp:manage_acc:{campaign_id}", style="danger")],
    ]
    return rows


def campaign_account_groups_keyboard(
    campaign_id: str, 
    account_id: str, 
    groups: list[dict], 
    assigned_group_ids: list[str],
    pagination: dict
) -> list[list[Button]]:
    """Paginated list of groups for an account."""
    rows = []
    
    # Add groups (2 per row for compactness)
    current_row = []
    for g in groups:
        group_id_str = str(g.get("_id") or g.get("id", ""))
        icon_val = 5206607081334906820 if group_id_str in assigned_group_ids else 5260293700088511294
        is_assigned = group_id_str in assigned_group_ids
        title = g.get("title", "Unknown")
        # Truncate title
        if len(title) > 15:
            title = title[:13] + ".."
            
        if is_assigned:
            btn_text = title
            btn_icon = 5416081784641168838
        else:
            btn_text = f"🔴 {title}"
            btn_icon = None
            
        page = pagination.get("page", 1)
        current_row.append(
            Button.inline(btn_text, f"cmp:grp_tg:{account_id}:{group_id_str}", style="primary" if is_assigned else "secondary", icon=btn_icon)
        )
        
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
            
    if current_row:
        rows.append(current_row)
        
    # Pagination
    page = pagination.get("page", 1)
    total_pages = pagination.get("total_pages", 1)
    
    nav_row = []
    if page > 1:
        nav_row.append(Button.inline("⬅️ Prev", f"cmp:acc_groups:{page-1}", style="primary"))
    if page < total_pages:
        nav_row.append(Button.inline("Next ➡️", f"cmp:acc_groups:{page+1}", style="primary"))
        
    if nav_row:
        rows.append(nav_row)
        
    # Select All / Deselect All
    rows.append([
        Button.inline("Select All", "cmp:grp_all", style="primary", icon=5206607081334906820),
        Button.inline("Clear All", "cmp:grp_none", style="primary", icon=5260293700088511294),
    ])
        
    rows.append([Button.inline("← Back to Account", f"cmp:acc_detail:{account_id}", style="danger")])
    return rows

# ── 6. ANALYTICS ──────────────────────────────────────────

def analytics_keyboard() -> list[list[Button]]:
    """Analytics overview buttons."""
    return [
        [Button.inline(_b("Refresh"), CB.ANALYTICS, style="primary", icon=5386367538735104399)],
        [Button.inline(_b("← Back"), CB.DASHBOARD, style="danger")],
    ]

def autoreply_view_keyboard() -> list[list[Button]]:
    """Auto Reply View Keyboard."""
    return [
        [Button.inline(_b("Delete Custom Message"), CB.SETTINGS_AUTOREPLY_CUSTOM, style="danger", icon=5445267414562389170)],
        [Button.inline(_b("← Back"), CB.SETTINGS_AUTOREPLY, style="danger")],
    ]

# ── 9. PERSONAL AI ──────────────────────────────────────────

def ai_chat_keyboard() -> list[list[Button]]:
    """Keyboard for when user is in AI chat mode."""
    return [
        [Button.inline(_b("Exit AI Chat"), CB.DASHBOARD, style="danger", icon=5260293700088511294)]
    ]

def ai_action_keyboard(action_id: str) -> list[list[Button]]:
    """Keyboard for confirming or cancelling an AI action."""
    return [
        [
            Button.inline(_b("Confirm"), CB.AI_CONFIRM.format(action_id=action_id), style="success", icon=5206607081334906820),
            Button.inline(_b("Cancel"), CB.AI_CANCEL.format(action_id=action_id), style="danger", icon=5260293700088511294),
        ]
    ]


# ── 7. HEALTH OVERVIEW ───────────────────────────────────

def health_overview_keyboard() -> list[list[Button]]:
    """Health overview buttons."""
    return [
        [
            Button.inline(_b("Refresh Now"), CB.HEALTH, style="primary", icon=5386367538735104399),
            Button.inline(_b("👁 View All"), CB.HEALTH_VIEW_ALL, style="primary"),
        ],
        [
            Button.inline(_b("Health Settings"), CB.HEALTH_SETTINGS, style="primary", icon=5341715473882955310),
        ],
        [Button.inline(_b("← Back"), CB.DASHBOARD, style="danger")],
    ]


def health_settings_keyboard(auto_pause: bool) -> list[list[Button]]:
    """Health settings menu buttons."""
    toggle_text = _b("Auto-Pause Unhealthy: ON") if auto_pause else _b("Auto-Pause Unhealthy: OFF")
    icon_val = 5206607081334906820 if auto_pause else 5260293700088511294
    toggle_btn = Button.inline(
        toggle_text,
        CB.HEALTH_SETTINGS_TOGGLE
    , style="primary", icon=icon_val)
    return [
        [toggle_btn],
        [Button.inline(_b("← Back"), CB.HEALTH, style="danger")],
    ]



def autojoin_progress_keyboard() -> list[list[Button]]:
    """Keyboard for joiner progress with cancel button."""
    return [
        [Button.inline(_b("Cancel Joining"), "groups:autojoin:cancel", style="danger", icon=5260293700088511294)],
    ]


# ── SETTINGS ─────────────────────────────────────────────

def settings_keyboard() -> list[list[Button]]:
    """Settings menu buttons."""
    return [
        [
            Button.inline("💬 Auto Reply", CB.SETTINGS_AUTOREPLY, style="primary"),
        ],
        [Button.inline("← Back", CB.DASHBOARD, style="danger")],
    ]


def autoreply_keyboard(enabled: bool, has_custom: bool) -> list[list[Button]]:
    """Auto Reply settings menu."""
    toggle_text = _b("Turn OFF") if enabled else _b("Turn ON")
    toggle_style = "danger" if enabled else "success"
    toggle_btn = Button.inline(
        toggle_text, 
        CB.SETTINGS_AUTOREPLY_TOGGLE
    , style=toggle_style)
    buttons = [[toggle_btn]]
    
    if has_custom:
        buttons.append([Button.inline(_b("View Current"), CB.SETTINGS_AUTOREPLY_VIEW, style="primary")])
        
    buttons.append([Button.inline(_b("Set Custom Reply"), CB.SETTINGS_AUTOREPLY_CUSTOM, style="primary")])
    buttons.append([Button.inline(_b("← Back"), CB.DASHBOARD, style="danger")])
    
    return buttons


# ── SHARED ───────────────────────────────────────────────

def back_keyboard(target: str = CB.DASHBOARD) -> list[list[Button]]:
    """Single back button."""
    return [[Button.inline(_b("← Back"), target, style="danger")]]


def confirm_keyboard(action: str, target_id: str) -> list[list[Button]]:
    """Yes/No confirmation buttons."""
    return [
        [
            Button.inline(_b("Yes, confirm"), f"confirm:yes:{action}:{target_id}", style="success", icon=5206607081334906820),
            Button.inline(_b("Cancel"), CB.CONFIRM_NO, style="danger", icon=5260293700088511294),
        ],
    ]

def logs_bot_activation_keyboard(bot_username: str, campaign_id: str) -> list[list[Button]]:
    """Keyboard shown when user hasn't started the logs bot."""
    return [
        [Button.url(_b("Start Logs Bot"), f"https://t.me/{bot_username}")],
        [Button.inline(_b("🔄 I have started it"), f"confirm:yes:resume_campaign:{campaign_id}", style="primary")],
        [Button.inline(_b("← Back"), f"cmp:view:{campaign_id}", style="danger")],
    ]

def profile_keyboard() -> list[list[Button]]:
    """User profile and subscription info."""
    return [
        [Button.inline(_b("Buy / Upgrade Plan"), "pay:options", style="success", icon=5438496463044752972)],
        [Button.inline(_b("← Back"), CB.DASHBOARD, style="danger")]
    ]

def paywall_keyboard(user=None) -> list[list[Button]]:
    """Subscription options linking to the admin."""
    from core.config import get_settings
    settings = get_settings()
    admin_url = f"https://t.me/{settings.admin_username.replace('@', '')}"
    
    # URL encode the base text and append user details
    import urllib.parse
    base_text = "I want to buy the {plan} Pass for ${price}.\n\nMy details:\nID: {uid}\nUsername: @{uname}"
    uid = user.user_id if user else "Unknown"
    uname = user.username if user and user.username else "NoUsername"
    
    w_text = urllib.parse.quote(base_text.format(plan="Weekly", price="5", uid=uid, uname=uname))
    m_text = urllib.parse.quote(base_text.format(plan="Monthly", price="15", uid=uid, uname=uname))
    y_text = urllib.parse.quote(base_text.format(plan="Yearly", price="120", uid=uid, uname=uname))
    
    from telethon.tl.types import KeyboardButtonStyle
    
    btn_w = Button.url(_b("Buy Weekly - $5"), f"{admin_url}?text={w_text}")
    btn_w.style = KeyboardButtonStyle(bg_success=True, icon=5409048419211682843)
    
    btn_m = Button.url(_b("Buy Monthly - $15"), f"{admin_url}?text={m_text}")
    btn_m.style = KeyboardButtonStyle(bg_primary=True, icon=5409048419211682843)
    
    btn_y = Button.url(_b("Buy Yearly - $120"), f"{admin_url}?text={y_text}")
    btn_y.style = KeyboardButtonStyle(bg_danger=True, icon=5409048419211682843)
    
    return [
        [btn_w],
        [btn_m],
        [btn_y],
        [Button.inline(_b("← Back"), "pay:profile", style="danger")]
    ]

def admin_panel_keyboard() -> list[list[Button]]:
    """Admin panel actions."""
    return [
        [Button.inline(_b("📊 View Stats"), "admin:stats", style="primary")],
        [Button.inline(_b("👥 Active Users"), "admin:users", style="primary")],
        [Button.inline(_b("← Back to Dashboard"), CB.DASHBOARD, style="danger")]
    ]

def admin_users_keyboard(page: int, total_pages: int) -> list[list[Button]]:
    """Pagination for admin active users."""
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(Button.inline(_b("◀ Prev"), f"admin:users:{page-1}", style="primary"))
        nav.append(Button.inline(f"📄 {page}/{total_pages}", CB.NOOP, style="primary"))
        if page < total_pages:
            nav.append(Button.inline(_b("Next ▶"), f"admin:users:{page+1}", style="primary"))
        rows.append(nav)
    
    rows.append([Button.inline(_b("← Back to Admin Panel"), "admin:panel", style="danger")])
    return rows
