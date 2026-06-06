"""
Session Importer service — Handles bulk import of .session and .zip files.
"""

from __future__ import annotations

import asyncio
import io
import os
import zipfile
import sqlite3
from typing import List, Dict, Any, Optional

from telethon import TelegramClient
from telethon.sessions import StringSession

from core.config import get_settings
from core.logging import get_logger
from services import session_manager

log = get_logger("session_importer")

async def import_from_file(owner_id: int, file_bytes: bytes, filename: str, update_callback) -> None:
    """Import sessions from a .session file or a .zip archive."""
    if filename.lower().endswith(".session"):
        await _process_session_file(owner_id, file_bytes, filename, update_callback)
    elif filename.lower().endswith(".zip"):
        await _process_zip_file(owner_id, file_bytes, update_callback)
    else:
        await update_callback(0, 0, 0, "❌ Unsupported file type. Send .session or .zip")
        return

    # Invalidate cache so newly imported accounts show up instantly
    from cache import account_cache, dashboard_cache
    await account_cache.invalidate_list(owner_id)
    await dashboard_cache.invalidate(owner_id)

async def _process_session_file(owner_id: int, file_bytes: bytes, filename: str, update_callback) -> None:
    """Process a single Telethon/Pyrogram .session file."""
    await update_callback(0, 0, 1, "Processing session file...")
    
    try:
        # We need to save it temporarily as a file for SQLite
        temp_path = f"temp_{filename}"
        with open(temp_path, "wb") as f:
            f.write(file_bytes)
            
        success = await _import_single_session_file(owner_id, temp_path)
        
        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        if success:
            await update_callback(1, 0, 1, "✅ Session added successfully!")
        else:
            await update_callback(0, 1, 1, "❌ Failed to add session.")
            
    except Exception as e:
        await update_callback(0, 1, 1, f"❌ Error: {str(e)[:20]}")

async def _process_zip_file(owner_id: int, file_bytes: bytes, update_callback) -> None:
    """Extract and process all .session files from a ZIP archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            session_files = [f for f in z.namelist() if f.lower().endswith(".session")]
            total = len(session_files)
            
            if total == 0:
                await update_callback(0, 0, 0, "❌ No .session files found in ZIP.")
                return
                
            joined = 0
            failed = 0
            
            await update_callback(0, 0, total, f"Found {total} sessions. Starting import...")
            
            for i, filename in enumerate(session_files):
                try:
                    # Extract single file to a temp path
                    temp_path = f"temp_{os.path.basename(filename)}"
                    with open(temp_path, "wb") as f:
                        f.write(z.read(filename))
                        
                    if await _import_single_session_file(owner_id, temp_path):
                        joined += 1
                    else:
                        failed += 1
                        
                    # Cleanup
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                        
                except Exception as e:
                    log.error("session_importer.file_error", file=filename, error=str(e))
                    failed += 1

                # Update progress outside the try/except to avoid double-counting
                try:
                    await update_callback(joined, failed, total)
                except Exception:
                    pass
                    
                # Small sleep to avoid hitting API too hard during connect/get_me
                await asyncio.sleep(1)

            await update_callback(joined, failed, total, "✅ Import Complete")
            
    except zipfile.BadZipFile:
        await update_callback(0, 0, 0, "❌ Invalid ZIP file.")
    except Exception as e:
        await update_callback(0, 0, 0, f"❌ Fatal Error: {str(e)[:20]}")

async def _import_single_session_file(owner_id: int, file_path: str) -> bool:
    """Convert a physical .session file (Telethon or Pyrogram) to a StringSession and import it."""
    client = None
    try:
        import base64
        import struct

        # 1. Detect Schema
        is_pyrogram = False
        is_telethon = False
        dc_id = None
        server_address = None
        port = None
        auth_key = None
        
        conn = sqlite3.connect(file_path)
        try:
            c = conn.cursor()
            # Pyrogram check
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session'")
            if c.fetchone():
                is_pyrogram = True
                c.execute("SELECT dc_id, auth_key FROM session LIMIT 1")
                row = c.fetchone()
                if row:
                    dc_id, auth_key = row
            else:
                # Telethon check
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
                if not c.fetchone():
                    log.warning("session_importer.unknown_schema", file=file_path)
                    return False
                else:
                    try:
                        c.execute("SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1")
                        row = c.fetchone()
                        if row:
                            dc_id, server_address, port, auth_key = row
                            is_telethon = True
                    except sqlite3.OperationalError:
                        log.warning("session_importer.invalid_telethon_schema", file=file_path)
                        return False
        finally:
            conn.close()

        settings = get_settings()
        
        # 2. Handle Conversion
        if is_pyrogram and dc_id and auth_key:
            # Convert Pyrogram auth_key to Telethon StringSession
            # Telethon StringSession (v1): 
            # [1 byte: version] + [1 byte: dc_id] + [ip length + ip] + [2 bytes: port] + [256 bytes: auth_key]
            # Pyrogram stores raw auth_key (256 bytes)
            
            # Default IPs for Telegram DCs (Production)
            dc_ips = {
                1: "149.154.175.53",
                2: "149.154.167.51",
                3: "149.154.175.100",
                4: "149.154.167.91",
                5: "91.108.56.130"
            }
            ip = dc_ips.get(dc_id, "149.154.167.50") # Default to DC2
            
            # Construct Telethon v1 String
            import socket
            ip_bytes = socket.inet_aton(ip)
            
            # Version(1) + DC(1) + IP_LEN(1) + IP(...) + PORT(2) + KEY(256)
            data = struct.pack(">BB", 1, dc_id)
            data += struct.pack(">B", len(ip_bytes)) + ip_bytes
            data += struct.pack(">H", 443) # Default port
            data += auth_key
            
            raw_string = base64.urlsafe_b64encode(data).decode('ascii')
            
        elif is_telethon and dc_id and server_address and port and auth_key:
            import socket
            import ipaddress
            ip_bytes = ipaddress.ip_address(server_address).packed
            
            data = struct.pack(f">B{len(ip_bytes)}sH256s", dc_id, ip_bytes, port, auth_key)
            raw_string = '1' + base64.urlsafe_b64encode(data).decode('ascii')
            
        else:
            log.warning("session_importer.missing_data", file=file_path)
            return False

        # 3. Import using existing manager
        # 3. Import using existing manager
        await session_manager.import_session(owner_id, raw_string)
        return True
            
    except Exception as e:
        log.error("session_importer.import_failed", error=str(e))
        if client and client.is_connected():
            await client.disconnect()
        return False
