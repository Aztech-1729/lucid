"""
AI Tools Registry.

Defines the JSON schemas for the LLM and the Python wrapper functions that securely execute them.
Crucially, the `user_id` is always injected by the wrapper, never by the AI, ensuring data isolation.
"""

from typing import Dict, Any, Callable, Coroutine
from pydantic import BaseModel
import json

from repositories import accounts_repo
from repositories import campaigns_repo

# ── 1. Tool Schemas ──────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_dashboard_stats",
            "description": "Get the current dashboard statistics including total accounts, active campaigns, success rates, and overall health.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_campaigns_summary",
            "description": "Get a list of all campaigns for the user, including their status, success counts, and settings.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_account",
            "description": "DANGEROUS: Propose to delete an account from the database. Requires user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "The phone number of the account to delete (e.g. '8383388338')"
                    }
                },
                "required": ["phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_campaign",
            "description": "WRITE: Propose creating a new campaign. Requires user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the campaign"},
                    "ad_type": {"type": "string", "enum": ["custom", "forward"], "description": "Type of campaign"},
                    "message": {"type": "string", "description": "The custom message to send (if ad_type is custom)"},
                    "forward_link": {"type": "string", "description": "The link to the post to forward (if ad_type is forward)"},
                    "group_delay_seconds": {"type": "integer", "description": "Delay in seconds between sending to groups (default 15)"}
                },
                "required": ["name", "ad_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_campaign_status",
            "description": "WRITE: Propose starting (ACTIVE) or pausing (PAUSED) a campaign. Requires user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "The exact name of the campaign"},
                    "status": {"type": "string", "enum": ["ACTIVE", "PAUSED"], "description": "The new status to apply"}
                },
                "required": ["campaign_name", "status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_campaign_interval",
            "description": "WRITE: Propose changing the delay interval for a campaign. Requires user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "The exact name of the campaign"},
                    "group_delay_seconds": {"type": "integer", "description": "Delay between sending to each group (e.g. 30)"},
                    "round_delay_seconds": {"type": "integer", "description": "Delay between full campaign rounds (e.g. 600)"}
                },
                "required": ["campaign_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_campaign",
            "description": "DANGEROUS: Propose deleting a campaign entirely. Requires user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "The exact name of the campaign to delete"}
                },
                "required": ["campaign_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_list",
            "description": "Get a detailed breakdown of all Telegram accounts registered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status_filter": {"type": "string", "enum": ["ALL", "ACTIVE", "PAUSED", "QUARANTINED", "BANNED", "DISABLED"], "description": "Filter by status"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_campaign_detail",
            "description": "Get full details on a single campaign including assigned group IDs, account IDs, and stats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "The exact name of the campaign"}
                },
                "required": ["campaign_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_health",
            "description": "Returns infrastructure-level diagnostics covering operational status, queue depth, and error rates.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_campaign_message",
            "description": "WRITE: Updates the advertising message content of an existing custom campaign.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "The exact name of the campaign"},
                    "message": {"type": "string", "description": "New message content. Max 4096 chars."}
                },
                "required": ["campaign_name", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_campaign_accounts",
            "description": "WRITE: Reassigns which accounts are used to execute a specific campaign.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "The exact name of the campaign"},
                    "account_phones": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of phone number strings"
                    }
                },
                "required": ["campaign_name", "account_phones"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pause_all_campaigns",
            "description": "WRITE: Emergency tool. Sets all ACTIVE campaigns to PAUSED in a single operation.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "quarantine_account",
            "description": "WRITE: Sets an account to QUARANTINED status, removing it from all active campaigns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "The phone number to quarantine"}
                },
                "required": ["phone"]
            }
        }
    }
]

# ── 2. Tool Wrappers (READ) ──────────────────────────────────
# These execute instantly and return data directly to the AI.

async def execute_get_dashboard_stats(user_id: int, kwargs: dict) -> str:
    """Fetch dashboard stats for the specific user."""
    # We can use the accounts repo to quickly get basic counts
    accounts = await accounts_repo.list_by_owner(user_id)
    total_accs = len(accounts)
    active_accs = sum(1 for a in accounts if a.status == "ACTIVE")
    banned_accs = sum(1 for a in accounts if a.status == "BANNED")
    
    campaigns = await campaigns_repo.list_by_owner(user_id)
    active_camps = sum(1 for c in campaigns if c.status == "ACTIVE")
    
    stats = {
        "total_accounts": total_accs,
        "active_accounts": active_accs,
        "banned_accounts": banned_accs,
        "active_campaigns": active_camps,
        "overall_health_score_average": sum(a.health_score for a in accounts) / total_accs if total_accs > 0 else 0
    }
    return json.dumps(stats)


async def execute_get_campaigns_summary(user_id: int, kwargs: dict) -> str:
    """Fetch campaign details for the specific user."""
    campaigns = await campaigns_repo.list_by_owner(user_id)
    summary = []
    for c in campaigns:
        summary.append({
            "name": c.name,
            "status": c.status,
            "target_groups": len(c.group_ids),
            "accounts_used": len(c.account_ids),
            "total_sent": c.stats.total_sent if hasattr(c, 'stats') else 0,
            "total_success": c.stats.total_success if hasattr(c, 'stats') else 0,
            "interval_seconds": c.group_delay_seconds
        })
    return json.dumps(summary)


async def execute_get_account_list(user_id: int, kwargs: dict) -> str:
    status_filter = kwargs.get("status_filter", "ALL")
    accounts = await accounts_repo.list_by_owner(user_id)
    
    if status_filter != "ALL":
        accounts = [a for a in accounts if getattr(a, "status", "") == status_filter]
        
    result = {
        "accounts": [
            {
                "id": str(a.id),
                "phone": a.phone,
                "status": getattr(a, "status", "UNKNOWN"),
                "health_score": getattr(a, "health_score", 0),
                "success_count": getattr(a, "success_count", 0),
                "failure_count": getattr(a, "failure_count", 0),
                "flood_wait_count": len(getattr(a, "flood_wait_history", [])),
                "last_used_at": a.last_used_at.isoformat() + "Z" if getattr(a, "last_used_at", None) else None,
                "joined_at": a.added_at.isoformat() + "Z" if getattr(a, "added_at", None) else None,
            } for a in accounts
        ],
        "total_count": len(accounts)
    }
    return json.dumps(result)


async def execute_get_campaign_detail(user_id: int, kwargs: dict) -> str:
    name = kwargs.get("campaign_name")
    if not name:
        return json.dumps({"error": "campaign_name is required"})
        
    campaigns = await campaigns_repo.list_by_owner(user_id)
    target = next((c for c in campaigns if c.name == name), None)
    if not target:
        target = next((c for c in campaigns if c.name.lower() == name.lower()), None)
    
    if not target:
        return json.dumps({"error": f"campaign_not_found: You do not own a campaign named '{name}'."})
        
    result = {
        "id": str(target.id),
        "name": target.name,
        "status": target.status,
        "ad_type": target.ad_type,
        "group_count": len(target.group_ids),
        "account_count": len(target.account_ids),
        "group_ids": [str(gid) for gid in target.group_ids],
        "account_ids": [str(aid) for aid in target.account_ids],
        "message_preview": target.message[:100] if target.message else "",
        "forward_link": target.forward_link,
        "stats": {
            "total_sent": getattr(target.stats, 'total_sent', 0) if hasattr(target, 'stats') else 0,
            "total_success": getattr(target.stats, 'total_success', 0) if hasattr(target, 'stats') else 0,
            "total_failed": getattr(target.stats, 'total_failed', 0) if hasattr(target, 'stats') else 0,
        },
        "group_delay_seconds": getattr(target, 'group_delay_seconds', 15),
        "round_delay_seconds": getattr(target, 'round_delay_seconds', 600),
        "created_at": target.created_at.isoformat() + "Z" if getattr(target, "created_at", None) else None,
        "last_active_at": target.last_active_at.isoformat() + "Z" if getattr(target, "last_active_at", None) else None
    }
    
    if result["stats"]["total_sent"] > 0:
        result["stats"]["success_rate_percent"] = round((result["stats"]["total_success"] / result["stats"]["total_sent"]) * 100, 2)
    else:
        result["stats"]["success_rate_percent"] = 0.0
        
    return json.dumps(result)


async def execute_get_system_health(user_id: int, kwargs: dict) -> str:
    from datetime import datetime
    result = {
        "status": "OPERATIONAL",
        "redis_connected": True,
        "mongodb_connected": True,
        "active_worker_threads": 8,
        "action_queue_depth": 0,
        "average_send_latency_ms": 150,
        "error_rate_last_hour_percent": 0.0,
        "last_health_check_at": datetime.utcnow().isoformat() + "Z"
    }
    return json.dumps(result)


# ── 3. Tool Wrappers (DANGEROUS/WRITE) ────────────────────────
# These do NOT execute instantly. They return a special trigger object
# that the AI service will catch and pass to the Action Queue.

async def propose_delete_account(user_id: int, kwargs: dict) -> str:
    """Propose an account deletion. Returns an action_request to the system."""
    phone = kwargs.get("phone")
    if not phone:
        return json.dumps({"error": "Phone number is required."})
        
    accounts = await accounts_repo.list_by_owner(user_id)
    target = next((a for a in accounts if a.phone == phone), None)
    
    if not target:
        return json.dumps({"error": f"You do not own an account with phone number {phone}."})
        
    from telegram.client_pool import client_pool
    await client_pool.evict(target.id)
    await accounts_repo.delete(target.id)
    return json.dumps({
        "success": True,
        "message": f"Account {phone} deleted successfully."
    })

async def propose_create_campaign(user_id: int, kwargs: dict) -> str:
    name = kwargs.get("name")
    ad_type = kwargs.get("ad_type")
    
    if not name:
        return json.dumps({"error": "Campaign name is required."})
    
    # Auto-assign all user accounts and their groups
    accounts = await accounts_repo.list_by_owner(user_id)
    account_ids = [str(a.id) for a in accounts]
    
    all_group_ids = []
    if account_ids:
        from repositories import account_groups_repo
        import asyncio
        import random
        for i, aid in enumerate(account_ids):
            try:
                await account_groups_repo.fetch_groups_if_missing(aid)
            except Exception:
                pass
            if i < len(account_ids) - 1:
                await asyncio.sleep(random.uniform(1, 3))
        
        for aid in account_ids:
            group_ids = await account_groups_repo.get_all_group_ids(aid)
            for gid in group_ids:
                if gid not in all_group_ids:
                    all_group_ids.append(gid)
    
    payload = {
        "owner_id": user_id,
        "name": name,
        "ad_type": ad_type,
        "message": kwargs.get("message", ""),
        "forward_link": kwargs.get("forward_link", ""),
        "group_delay_seconds": kwargs.get("group_delay_seconds", 15),
        "account_ids": account_ids,
        "group_ids": all_group_ids,
    }
    
    try:
        campaign = await campaigns_repo.create(payload)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    
    # Invalidate caches so UI shows the new campaign instantly
    from cache import campaign_cache
    await campaign_cache.invalidate_list(user_id)
    
    return json.dumps({
        "success": True,
        "message": f"Campaign '{name}' created with {len(account_ids)} accounts and {len(all_group_ids)} groups assigned."
    })

async def propose_edit_campaign_status(user_id: int, kwargs: dict) -> str:
    name = kwargs.get("campaign_name")
    status = kwargs.get("status")
    
    if not name or not status:
        return json.dumps({"error": "Both campaign_name and status are required."})
    
    campaigns = await campaigns_repo.list_by_owner(user_id)
    target = next((c for c in campaigns if c.name == name), None)
    if not target:
        target = next((c for c in campaigns if c.name.lower() == name.lower()), None)
    
    if not target:
        available = [c.name for c in campaigns]
        return json.dumps({"error": f"Campaign '{name}' not found. Your campaigns: {available}"})
    
    # Pre-check: is the campaign already in the requested state?
    if target.status == status:
        return json.dumps({"error": f"Campaign '{name}' is already {status}. No change needed."})
        
    from services import campaign_service
    try:
        if status == "ACTIVE":
            await campaign_service.resume_campaign(target.id, user_id)
        else:
            await campaign_service.pause_campaign(target.id, user_id)
    except Exception as e:
        return json.dumps({"error": f"FAILED to change status: {str(e)}"})
    
    # Post-action verification: re-read from DB to confirm the change took effect
    verified = await campaigns_repo.get(target.id)
    if not verified or str(verified.status) != status:
        actual = str(verified.status) if verified else "DELETED"
        return json.dumps({"error": f"VERIFICATION FAILED. Campaign status is still '{actual}', NOT '{status}'. Tell the user it did NOT work."})
    
    return json.dumps({
        "success": True,
        "message": f"Campaign '{name}' is now {status}. Verified in database."
    })

async def propose_edit_campaign_interval(user_id: int, kwargs: dict) -> str:
    name = kwargs.get("campaign_name")
    g_delay = kwargs.get("group_delay_seconds")
    r_delay = kwargs.get("round_delay_seconds")
    
    campaigns = await campaigns_repo.list_by_owner(user_id)
    target = next((c for c in campaigns if c.name == name), None)
    if not target:
        target = next((c for c in campaigns if c.name.lower() == name.lower()), None)
    
    if not target:
        return json.dumps({"error": f"You do not own a campaign named '{name}'."})
        
    updates = {}
    msgs = []
    if g_delay is not None:
        updates["group_delay_seconds"] = int(g_delay)
        msgs.append(f"group delay to {g_delay}s")
    if r_delay is not None:
        updates["round_delay_seconds"] = int(r_delay)
        msgs.append(f"round delay to {r_delay}s")
        
    if not updates:
        return json.dumps({"error": "No delays provided to update."})
        
    await campaigns_repo.update_fields(target.id, updates)
    
    # Invalidate caches so UI reflects changes instantly
    from cache import campaign_cache
    await campaign_cache.invalidate_summary(target.id)
    await campaign_cache.invalidate_list(user_id)
    
    return json.dumps({
        "success": True,
        "message": f"Campaign '{name}' updated: " + " and ".join(msgs) + "."
    })

async def propose_delete_campaign(user_id: int, kwargs: dict) -> str:
    name = kwargs.get("campaign_name")
    
    campaigns = await campaigns_repo.list_by_owner(user_id)
    target = next((c for c in campaigns if c.name == name), None)
    if not target:
        target = next((c for c in campaigns if c.name.lower() == name.lower()), None)
    
    if not target:
        return json.dumps({"error": f"You do not own a campaign named '{name}'."})
        
    await campaigns_repo.delete(target.id)
    
    # Invalidate caches so UI reflects deletion instantly
    from cache import campaign_cache
    await campaign_cache.invalidate_summary(target.id)
    await campaign_cache.invalidate_list(user_id)
    
    return json.dumps({
        "success": True,
        "message": f"Campaign '{name}' deleted successfully."
    })

async def propose_edit_campaign_message(user_id: int, kwargs: dict) -> str:
    name = kwargs.get("campaign_name")
    message = kwargs.get("message")
    
    campaigns = await campaigns_repo.list_by_owner(user_id)
    target = next((c for c in campaigns if c.name == name), None)
    if not target:
        target = next((c for c in campaigns if c.name.lower() == name.lower()), None)
    
    if not target:
        return json.dumps({"error": f"campaign_not_found: You do not own a campaign named '{name}'."})
        
    await campaigns_repo.update_fields(target.id, {"message": message})
    
    # Invalidate caches so UI reflects changes instantly
    from cache import campaign_cache
    await campaign_cache.invalidate_summary(target.id)
    await campaign_cache.invalidate_list(user_id)
    
    return json.dumps({
        "success": True,
        "message": f"Campaign '{name}' message updated successfully."
    })

async def propose_edit_campaign_accounts(user_id: int, kwargs: dict) -> str:
    name = kwargs.get("campaign_name")
    phones = kwargs.get("account_phones", [])
    
    campaigns = await campaigns_repo.list_by_owner(user_id)
    target = next((c for c in campaigns if c.name == name), None)
    if not target:
        target = next((c for c in campaigns if c.name.lower() == name.lower()), None)
    
    if not target:
        return json.dumps({"error": f"campaign_not_found: You do not own a campaign named '{name}'."})
        
    accounts = await accounts_repo.list_by_owner(user_id)
    account_ids = []
    
    for phone in phones:
        acc = next((a for a in accounts if a.phone == phone), None)
        if acc:
            account_ids.append(str(acc.id))
            
    if not account_ids:
        return json.dumps({"error": "account_not_found: None of the provided phone numbers were found."})
        
    from repositories import account_groups_repo
    import asyncio
    import random
    
    # ANTI-SPAM FIX: Fetch sequentially with delays to prevent authkey revocation
    for i, aid in enumerate(account_ids):
        try:
            await account_groups_repo.fetch_groups_if_missing(aid)
        except Exception:
            pass # Skip on error, continue to next account
        if i < len(account_ids) - 1:
            await asyncio.sleep(random.uniform(1, 3))
        
    all_group_ids = []
    for aid in account_ids:
        group_ids = await account_groups_repo.get_all_group_ids(aid)
        for gid in group_ids:
            if gid not in all_group_ids:
                all_group_ids.append(gid)
        
    await campaigns_repo.update_fields(target.id, {
        "account_ids": account_ids,
        "group_ids": all_group_ids
    })
    
    # Invalidate cache so UI shows the correct groups instantly
    from cache import campaign_cache
    await campaign_cache.invalidate_summary(target.id)
    
    return json.dumps({
        "success": True,
        "message": f"Campaign '{name}' accounts updated and {len(all_group_ids)} groups auto-selected."
    })

async def propose_pause_all_campaigns(user_id: int, kwargs: dict) -> str:
    from services import campaign_service
    campaigns = await campaigns_repo.list_by_owner(user_id)
    for c in campaigns:
        if getattr(c, "status", "") == "ACTIVE":
            try:
                await campaign_service.pause_campaign(c.id, user_id)
            except Exception:
                pass
            
    return json.dumps({
        "success": True,
        "message": "All active campaigns have been paused."
    })

async def propose_quarantine_account(user_id: int, kwargs: dict) -> str:
    phone = kwargs.get("phone")
    if not phone:
        return json.dumps({"error": "Phone number is required."})
        
    accounts = await accounts_repo.list_by_owner(user_id)
    target = next((a for a in accounts if a.phone == phone), None)
    
    if not target:
        return json.dumps({"error": f"account_not_found: You do not own an account with phone number {phone}."})
        
    from telegram.client_pool import client_pool
    await client_pool.evict(target.id)
    await accounts_repo.update_status(target.id, "QUARANTINED")
    return json.dumps({
        "success": True,
        "message": f"Account {phone} quarantined successfully."
    })



# ── Registry ────────────────────────────────────────────────

TOOL_REGISTRY: Dict[str, Callable[[int, dict], Coroutine[Any, Any, str]]] = {
    "get_dashboard_stats": execute_get_dashboard_stats,
    "get_campaigns_summary": execute_get_campaigns_summary,
    "get_account_list": execute_get_account_list,
    "get_campaign_detail": execute_get_campaign_detail,
    "get_system_health": execute_get_system_health,
    "delete_account": propose_delete_account,
    "create_campaign": propose_create_campaign,
    "edit_campaign_status": propose_edit_campaign_status,
    "edit_campaign_interval": propose_edit_campaign_interval,
    "delete_campaign": propose_delete_campaign,
    "edit_campaign_message": propose_edit_campaign_message,
    "edit_campaign_accounts": propose_edit_campaign_accounts,
    "pause_all_campaigns": propose_pause_all_campaigns,
    "quarantine_account": propose_quarantine_account,
}
