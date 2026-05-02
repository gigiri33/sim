# -*- coding: utf-8 -*-
"""
/start message handler.
"""
from ..db import ensure_user, notify_first_start_if_needed, get_user, setting_get, add_referral, get_referral_by_referee, get_phone_number, get_locked_channels
from ..helpers import state_clear, state_set, is_admin, parse_int, normalize_iranian_phone
from ..ui.helpers import check_channel_membership, channel_lock_message, _invalidate_channel_cache
from ..ui.menus import show_main_menu
from ..bot_instance import bot


def _phone_required_for_user(uid: int) -> bool:
    """Return True if this user still needs to provide a phone number."""
    phone_mode = setting_get("phone_mode", "disabled")
    if phone_mode == "disabled":
        return False
    if get_phone_number(uid):
        return False  # already collected
    if phone_mode == "everyone":
        return True
    user = get_user(uid)
    if not user:
        return False
    if phone_mode == "agents_only":
        return bool(user["is_agent"])
    if phone_mode == "trusted_only":
        return user["status"] in ("safe",)
    # card_only and other modes: not required at start
    return False


def _send_phone_request(chat_id: int, uid: int):
    """Send the phone-collection message with a contact keyboard."""
    from telebot import types as _t
    kb = _t.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(_t.KeyboardButton("📱 ارسال شماره تلفن", request_contact=True))
    bot.send_message(
        chat_id,
        "📱 <b>ثبت شماره تلفن</b>\n\n"
        "برای استفاده از ربات، لطفاً شماره تلفن خود را با دکمه زیر ارسال کنید.",
        parse_mode="HTML",
        reply_markup=kb,
    )
    state_set(uid, "waiting_for_phone")


@bot.message_handler(commands=["start"])
def start_handler(message):
    is_new = ensure_user(message.from_user)
    notify_first_start_if_needed(message.from_user)
    uid = message.from_user.id
    # Cancel any active panel connection thread before clearing state
    try:
        from .callbacks import _pnl_connect_events
        ev = _pnl_connect_events.pop(uid, None)
        if ev:
            ev.set()
    except Exception:
        pass
    state_clear(uid)

    # Handle referral link: /start ref_12345
    if is_new and message.text:
        parts = message.text.split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            try:
                referrer_id = int(parts[1][4:])
                if referrer_id != uid and setting_get("referral_enabled", "1") == "1":
                    add_referral(referrer_id, uid)
                    from ..ui.notifications import (
                        check_and_give_referral_start_reward,
                        try_give_referral_start_reward_for_channel_join,
                        notify_referral_join,
                        _channel_reward_required,
                        send_captcha_prompt,
                    )
                    try:
                        notify_referral_join(referrer_id, uid)
                    except Exception:
                        pass

                    if _channel_reward_required():
                        # Channel condition is active.
                        # If the user is ALREADY a channel member right now,
                        # treat the join as immediate (e.g. they joined before starting).
                        _invalidate_channel_cache(uid)
                        if check_channel_membership(uid):
                            # Mark channel_joined and potentially give reward / show captcha
                            try_give_referral_start_reward_for_channel_join(uid)
                        # else: reward deferred until user confirms channel membership
                    else:
                        # start_only mode — give reward immediately (or show captcha first)
                        captcha_enabled = setting_get("referral_captcha_enabled", "1") == "1"
                        if captcha_enabled:
                            send_captcha_prompt(uid)
                        else:
                            check_and_give_referral_start_reward(referrer_id)
            except (ValueError, Exception):
                pass

    # Bot status check (before everything else for non-admins)
    if not is_admin(uid):
        from ..license_manager import is_limited_mode as _is_limited
        if _is_limited():
            bot.send_message(message.chat.id, "🚫 ربات در حال حاضر غیرفعال است.")
            return
        bot_status = setting_get("bot_status", "on")
        if bot_status == "off":
            return
        if bot_status == "update":
            bot.send_message(
                message.chat.id,
                "🔄 <b>ربات در حال بروزرسانی است</b>\n\n"
                "فعلاً ربات در حال بروزرسانی می‌باشد، لطفاً بعداً اقدام نمایید. 🙏\n\n"
                "در صورتی که کار فوری دارید، می‌توانید با پشتیبانی در ارتباط باشید.",
                parse_mode="HTML"
            )
            return

    user = get_user(uid)
    if user and user["status"] == "restricted":
        bot.send_message(
            message.chat.id,
            "🚫 <b>دسترسی محدود شده</b>\n\n"
            "شما از ربات محدود شده‌اید و نمی‌توانید از آن استفاده کنید.\n"
            "در صورت نیاز با پشتیبانی تماس بگیرید.",
            parse_mode="HTML"
        )
        return
    if not check_channel_membership(uid):
        channel_lock_message(message)
        return

    # User has passed channel check — if they were a referee waiting for channel
    # confirmation, process their reward now (handles the case where they join
    # the channel externally and then hit /start again instead of the button).
    _invalidate_channel_cache(uid)
    try:
        from ..ui.notifications import try_give_referral_start_reward_for_channel_join
        try_give_referral_start_reward_for_channel_join(uid)
    except Exception:
        pass

    # Phone gate — must come after channel check
    if not is_admin(uid) and _phone_required_for_user(uid):
        _send_phone_request(message.chat.id, uid)
        return

    show_main_menu(message)


# ── Channel member-status watcher ─────────────────────────────────────────────
# Fires when any user's membership status changes inside ANY chat the bot can see.
# We only care about our configured mandatory channel: if a user leaves/gets kicked,
# we immediately drop their membership cache so the very next callback or message
# they send will be blocked without waiting for the TTL to expire.

@bot.chat_member_handler(func=lambda u: True)
def on_chat_member_updated(update):
    """Invalidate channel-membership cache when a user leaves any locked channel."""
    # Build full list of locked channels (DB table + legacy setting)
    all_channels = []
    try:
        for row in get_locked_channels():
            ch = str(row["channel_id"]).strip()
            if ch and ch not in all_channels:
                all_channels.append(ch)
    except Exception:
        pass
    legacy = setting_get("channel_id", "").strip()
    if legacy and legacy not in all_channels:
        all_channels.append(legacy)

    if not all_channels:
        return

    # Check whether the update's chat matches any of our locked channels
    chat = update.chat
    matched_channel = None
    for channel_id in all_channels:
        chat_matches = (
            str(chat.id) == channel_id
            or (chat.username and f"@{chat.username}" == channel_id)
            or str(chat.id) == channel_id.lstrip("-")
        )
        if chat_matches:
            matched_channel = channel_id
            break

    if matched_channel is None:
        return

    new_status = update.new_chat_member.status
    user_id    = update.new_chat_member.user.id

    if new_status in ("left", "kicked", "restricted", "banned"):
        _invalidate_channel_cache(user_id)

        # Determine a human-readable channel label
        if matched_channel.startswith("@"):
            channel_url   = f"https://t.me/{matched_channel.lstrip('@')}"
            channel_label = matched_channel
        elif matched_channel.startswith("-100"):
            channel_url   = f"https://t.me/c/{matched_channel[4:]}"
            # Try to get username from the chat object
            channel_label = f"@{chat.username}" if chat.username else matched_channel
        else:
            channel_url   = f"https://t.me/{matched_channel}"
            channel_label = f"@{chat.username}" if chat.username else matched_channel

        from telebot import types as _t
        kb = _t.InlineKeyboardMarkup()
        kb.add(_t.InlineKeyboardButton(f"📢 عضویت مجدد در کانال", url=channel_url))
        try:
            bot.send_message(
                user_id,
                f"❌ <b>شما از کانال {channel_label} خارج شدید</b>\n\n"
                "از این پس از اخبار، آپدیت‌ها و اطلاعیه‌های مهم با خبر نمی‌شوید.\n\n"
                "بهتر است مجدداً عضو کانال شوید تا دسترسی به ربات حفظ شود. 🙏",
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:
            pass
