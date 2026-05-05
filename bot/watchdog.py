# -*- coding: utf-8 -*-
"""
Bot Watchdog — monitors Telegram API connectivity every N minutes.

If `bot.get_me()` fails MAX_FAILURES times in a row the process is killed
with os._exit(1) so systemd (Restart=always) can restart it cleanly.
"""

import threading
import time
import os
import sys

_consecutive_failures = 0
_MAX_FAILURES         = 2       # failures in a row before hard-exit
_CHECK_INTERVAL       = 300     # seconds between checks (5 minutes)


def _do_check(token: str) -> bool:
    """
    Use a plain requests call (separate from the bot's internal session)
    with a tight timeout so we don't get stuck inside a broken TCP connection.
    Returns True if bot is healthy, False otherwise.
    """
    global _consecutive_failures
    try:
        import requests
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            if _consecutive_failures > 0:
                print(f"[Watchdog] ✅ Recovered after {_consecutive_failures} failure(s).")
            _consecutive_failures = 0
            return True
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:120]}")
    except Exception as exc:
        _consecutive_failures += 1
        print(
            f"[Watchdog] ⚠️  Check failed "
            f"({_consecutive_failures}/{_MAX_FAILURES}): {exc}",
            flush=True,
        )
        if _consecutive_failures >= _MAX_FAILURES:
            print(
                "[Watchdog] 🔴 Bot is unresponsive — triggering systemd restart via os._exit(1)",
                flush=True,
            )
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)          # hard-kill; systemd will restart within RestartSec
        return False


def start_watchdog(bot, interval: int = _CHECK_INTERVAL) -> None:
    """
    Start the watchdog background thread.
    Call this once from main() after the bot is fully initialised.

    Args:
        bot:      The pyTeleBot bot instance (needs .token attribute).
        interval: Seconds between health checks (default 300 = 5 min).
    """

    token = bot.token

    def _loop():
        # Wait one full interval first so we don't check during startup
        time.sleep(interval)
        while True:
            _do_check(token)
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="sim-watchdog")
    t.start()
    print(
        f"[Watchdog] ✅ Started — getMe check every {interval // 60} min, "
        f"exit after {_MAX_FAILURES} consecutive failures.",
        flush=True,
    )
