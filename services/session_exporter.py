import io
import os
import zipfile
import tempfile

from telethon.sessions import StringSession, SQLiteSession

from core.logging import get_logger
from repositories import accounts_repo
from services import session_manager

log = get_logger("session_exporter")

async def export_sessions_zip(owner_id: int) -> bytes:
    """
    Exports all active accounts for a user into a ZIP file containing
    standard Telethon .session (SQLite) files.
    """
    accounts = await accounts_repo.list_by_owner(owner_id)
    if not accounts:
        return b""
        
    mem_zip = io.BytesIO()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for acc in accounts:
                try:
                    # 1. Decrypt raw string
                    raw_str = session_manager.decrypt_session(acc.session)
                    string_sess = StringSession(raw_str)
                    
                    # 2. Re-create SQLite .session file
                    session_path = os.path.join(tmpdir, f"{acc.phone}.session")
                    sql_sess = SQLiteSession(session_path)
                    
                    # Populate the core details
                    sql_sess.set_dc(string_sess.dc_id, string_sess.server_address, string_sess.port)
                    sql_sess.auth_key = string_sess.auth_key
                    sql_sess.save()
                    sql_sess.close()
                    
                    # 3. Add to ZIP archive
                    zf.write(session_path, arcname=f"{acc.phone}.session")
                    
                    # 4. Generate metadata JSON file
                    import json
                    from core.config import get_settings
                    settings = get_settings()
                    
                    meta = {
                        "session_file": acc.phone,
                        "phone": acc.phone,
                        "register_time": int(acc.created_at.timestamp()) if hasattr(acc, "created_at") else 0,
                        "app_id": settings.api_id,
                        "app_hash": settings.api_hash,
                        "sdk": "Windows 10",
                        "app_version": "1.0",
                        "device": "PC",
                        "last_check_time": int(acc.updated_at.timestamp()) if hasattr(acc, "updated_at") else 0,
                        "avatar": "",
                        "first_name": acc.name,
                        "last_name": "",
                        "username": "",
                        "sex": 0,
                        "lang_pack": "en",
                        "system_lang_pack": "en",
                        "twoFA": acc.two_fa_password or "no_pass"
                    }
                    
                    json_path = os.path.join(tmpdir, f"{acc.phone}.json")
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=4)
                        
                    zf.write(json_path, arcname=f"{acc.phone}.json")
                    
                except Exception as e:
                    await log.aerror("export.failed", phone=acc.phone, error=str(e))
                    
    return mem_zip.getvalue()
