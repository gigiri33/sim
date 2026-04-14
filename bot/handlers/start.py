# -*- coding: utf-8 -*-
"""
/start message handler.
"""
from ..db import ensure_user, notify_first_start_if_needed, get_user, setting_get, add_referral, get_referral_by_referee, get_phone_number
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
    state_clear(message.from_user.id)
    uid = message.from_user.id

    # Handle referral link: /start ref_12345
    if is_new and message.text:
        parts = message.text.split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            try:
                referrer_id = int(parts[1][4:])
                if referrer_id != uid:
                    add_referral(referrer_id, uid)
                    from ..ui.notifications import (
                        check_and_give_referral_start_reward,
                        try_give_referral_start_reward_for_channel_join,
                        notify_referral_join,
                        _channel_reward_required,
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
                            # Mark channel_joined and potentially give reward now
                            try_give_referral_start_reward_for_channel_join(uid)
                        # else: reward deferred until user confirms channel membership
                    else:
                        # start_only mode — give reward immediately
                        check_and_give_referral_start_reward(referrer_id)
            except (ValueError, Exception):
                pass

    # Bot status check (before everything else for non-admins)
    if not is_admin(uid):
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
