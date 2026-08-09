"""One-time DB reset script - reset group_health data and toxic thresholds."""
import asyncio
import sys
sys.path.insert(0, '/app')

from database.mongo import init_mongo, get_db
from core.config import get_settings

async def main():
    settings = get_settings()
    await init_mongo(settings.mongo_uri, settings.mongo_db)
    db = get_db()
    
    # 1. Reset ALL group_health data
    result = await db.group_health.update_many({}, {
        "$unset": {"restricted": "", "restricted_reason": "", "restricted_at": ""},
        "$set": {"failure_count": 0, "flood_count": 0, "success_count": 0, "total_attempts": 0}
    })
    print(f"Reset group_health: {result.modified_count} docs")
    
    # 2. Check campaign stats
    camp = await db.campaigns.find_one({"status": "ACTIVE"})
    if camp:
        stats = camp.get("stats", {})
        print(f"Campaign '{camp.get('name')}': sent={stats.get('total_sent',0)} success={stats.get('total_success',0)} failed={stats.get('total_failed',0)}")
    
    # 3. Check forwarding logs count
    import datetime
    today = datetime.datetime(2026, 8, 8, 0, 0, 0)
    total = await db.forwarding_logs.count_documents({"timestamp": {"$gte": today}})
    print(f"Forwarding logs today: {total}")
    
    print("\nDone! Group health fully reset.")

asyncio.run(main())
