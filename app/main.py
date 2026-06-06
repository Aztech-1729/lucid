"""
Lucid Ads Bot — Entry Point.

Initializes the async runtime, runs startup sequence,
and keeps the bot running until interrupted.
"""

from __future__ import annotations

import asyncio
import signal
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


async def main() -> None:
    """
    Main coroutine — runs startup, keeps bot alive, handles shutdown.
    """
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
