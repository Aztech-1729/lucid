"""
Lucid Ads Bot — Entry Point.

Initializes the async runtime, runs startup sequence,
and keeps the bot running until interrupted.
"""

from __future__ import annotations

import asyncio
import sys


def _install_uvloop() -> None:
    """Install uvloop as the event loop policy if available (non-Windows)."""
    if sys.platform == "win32":
        # uvloop does not support Windows
        return

    try:
        import uvloop
        uvloop.install()
        print("[boot] uvloop installed ✓")
    except ImportError:
        print("[boot] uvloop not available, using default asyncio loop")


def _suppress_telethon_crashes(loop, context):
    """Catch Telethon internal task crashes (send loop, wrong session ID) to prevent process death."""
    exc = context.get("exception")
    if exc:
        msg = str(exc).lower()
        if any(x in msg for x in ["tcptransport closed", "wrong session", "security error", "send loop"]):
            return
    loop.default_exception_handler(context)


async def main() -> None:
    """
    Main coroutine — runs startup, keeps bot alive, handles shutdown.
    """
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_suppress_telethon_crashes)

    from app.startup import startup
    from app.shutdown import shutdown
    from telegram.bot import get_bot

    try:
        # Run ordered startup
        await startup()

        # Keep the bot running until explicitly stopped, catching network drops
        bot = get_bot()
        print("\n" + "=" * 50)
        print("  LUCID ADS BOT — RUNNING 🚀")
        print("  Press Ctrl+C to stop")
        print("=" * 50 + "\n")

        while True:
            try:
                await bot.run_until_disconnected()
                break  # Clean disconnect
            except KeyboardInterrupt:
                raise
            except Exception as e:
                err_str = str(e).lower()
                if "connection" in err_str or "timeout" in err_str or "closed" in err_str:
                    print(f"\n[main] Network drop detected: {e}. Reconnecting in 5s...")
                    await asyncio.sleep(5)
                else:
                    raise
        print("\n[main] Keyboard interrupt received")
    except Exception as exc:
        print(f"\n[main] Fatal error: {exc}")
        raise
    finally:
        # Always run shutdown
        await shutdown()


def _suppress_telethon_crashes(loop, context):
    """Catch Telethon internal task crashes (send loop, wrong session ID) to prevent process death."""
    exc = context.get("exception")
    if exc:
        msg = str(exc).lower()
        if any(x in msg for x in ["tcptransport closed", "wrong session", "security error"]):
            return  # Suppress — these are handled by the pool's circuit breaker
    loop.default_exception_handler(context)


def run() -> None:
    """Entry point — configures the event loop and runs main()."""
    _install_uvloop()

    if sys.platform == "win32":
        # Windows requires ProactorEventLoop for subprocess support
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[boot] Shutdown complete")


if __name__ == "__main__":
    run()
