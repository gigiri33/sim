# -*- coding: utf-8 -*-
"""
Entry point for the ConfigFlow Telegram Bot.

Run with:  python main.py
"""
import threading

from bot.db import init_db
from bot.db import cleanup_stale_reservations
from bot.ui.helpers import set_bot_commands
from bot.db import setting_get
from bot.admin.backup import _backup_loop
from bot.group_manager import _group_topic_loop
import bot.handlers  # noqa: F401 — registers all handlers
from bot.bot_instance import bot  # must come after to avoid being shadowed by the package name
from bot.license_manager import (
    check_license,
    get_or_create_machine_id,
    start_license_background_check,
    is_limited_mode,
    LIMITED_MODE_TEXT,
)


def main():
    init_db()
    cleanup_stale_reservations()
    set_bot_commands()

    # ── Layer 1: Ensure machine_id exists ─────────────────────────────────────
    get_or_create_machine_id()

    # ── Layer 2: Check license at startup (non-blocking — limited mode allowed) ─
    license_ok = check_license(force=True)
    if license_ok:
        print("✅ License is active.")
    else:
        print("⚠️  License inactive or expired — running in LIMITED MODE.")
        print("   Use /license_status or the admin panel to activate.")

    # ── Layer 3: Start background license checker ─────────────────────────────
    owner_id = 0
    try:
        admin_ids_str = setting_get("license_owner_telegram_id", "")
        if admin_ids_str and admin_ids_str.isdigit():
            owner_id = int(admin_ids_str)
        else:
            # Fall back to first ADMIN_IDS entry
            from bot.config import ADMIN_IDS
            if ADMIN_IDS:
                owner_id = next(iter(ADMIN_IDS))
    except Exception:
        pass
    start_license_background_check(bot, owner_id)

    # Start backup thread
    backup_thread = threading.Thread(target=_backup_loop, daemon=True)
    backup_thread.start()

    # Start group topic maintenance loop
    group_thread = threading.Thread(target=_group_topic_loop, daemon=True)
    group_thread.start()

    # Remove any active webhook before starting long-polling (prevents 409 conflict)
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"⚠️ Could not delete webhook: {e}")

    print("✅ Bot is running...")
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30,
        allowed_updates=[
            "message",
            "callback_query",
            "chat_member",      # needed for channel-leave detection
            "my_chat_member",   # bot kicked/added to channels/groups
        ],
    )


if __name__ == "__main__":
    main()
