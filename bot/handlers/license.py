# -*- coding: utf-8 -*-
"""
License activation & status handlers.
Handles /license_status command and the activation flow.
"""
from telebot import types

from ..bot_instance import bot
from ..helpers import state_set, state_clear, state_name, is_admin
from ..config import ADMIN_IDS
from ..db import setting_get
from ..license_manager import (
    activate_license,
    is_license_active,
    is_limited_mode,
    get_license_status_text,
    get_or_create_machine_id,
    API_KEY_PROMPT_TEXT,
    ACTIVATION_SUCCESS_TEXT,
    ACTIVATION_FAIL_TEXT,
    LIMITED_MODE_TEXT,
)

_STATE_WAITING_API_KEY = "license:waiting_api_key"


# ── /license_status command ────────────────────────────────────────────────────

@bot.message_handler(commands=["license_status"])
def cmd_license_status(message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS and not is_admin(uid):
        bot.send_message(message.chat.id, "⛔ دسترسی فقط برای مالک/ادمین مجاز است.")
        return
    text = get_license_status_text()
    kb = types.InlineKeyboardMarkup()
    if is_limited_mode():
        kb.add(types.InlineKeyboardButton("🔐 فعال‌سازی لایسنس", callback_data="license:activate"))
    kb.add(types.InlineKeyboardButton("🔄 بررسی مجدد", callback_data="license:recheck"))
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=kb)


# ── Callback: license:activate ─────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "license:activate")
def cb_license_activate(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS and not is_admin(uid):
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    state_set(uid, _STATE_WAITING_API_KEY)
    bot.send_message(call.message.chat.id, API_KEY_PROMPT_TEXT, parse_mode="HTML")


# ── Callback: license:recheck ──────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "license:recheck")
def cb_license_recheck(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS and not is_admin(uid):
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید.", show_alert=True)
        return
    bot.answer_callback_query(call.id, "⏳ در حال بررسی...")
    from ..license_manager import check_license, _invalidate_cache
    _invalidate_cache()
    check_license(force=True)
    text = get_license_status_text()
    kb = types.InlineKeyboardMarkup()
    if is_limited_mode():
        kb.add(types.InlineKeyboardButton("🔐 فعال‌سازی لایسنس", callback_data="license:activate"))
    kb.add(types.InlineKeyboardButton("🔄 بررسی مجدد", callback_data="license:recheck"))
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)


# ── Callback: license:status (alias for inline menu) ─────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "license:status")
def cb_license_status(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS and not is_admin(uid):
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    text = get_license_status_text()
    kb = types.InlineKeyboardMarkup()
    if is_limited_mode():
        kb.add(types.InlineKeyboardButton("🔐 فعال‌سازی لایسنس", callback_data="license:activate"))
    kb.add(types.InlineKeyboardButton("🔄 بررسی مجدد", callback_data="license:recheck"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:panel"))
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)


# ── Message handler: waiting for API key ──────────────────────────────────────

@bot.message_handler(func=lambda m: state_name(m.from_user.id) == _STATE_WAITING_API_KEY)
def msg_license_api_key(message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS and not is_admin(uid):
        state_clear(uid)
        return

    text = (message.text or "").strip()

    if text in ("/cancel", "لغو"):
        state_clear(uid)
        bot.send_message(message.chat.id, "❌ فعال‌سازی لغو شد.")
        return

    api_key = text
    state_clear(uid)

    # Gather automatic data
    bot_username = ""
    try:
        me = bot.get_me()
        bot_username = me.username or ""
    except Exception:
        pass

    owner_telegram_id = uid
    owner_username    = message.from_user.username or ""

    # Ensure machine_id is saved
    get_or_create_machine_id()

    bot.send_message(message.chat.id, "⏳ در حال فعال‌سازی لایسنس...", parse_mode="HTML")

    result = activate_license(
        api_key=api_key,
        bot_username=bot_username,
        owner_telegram_id=owner_telegram_id,
        owner_username=owner_username,
    )

    if result.get("ok"):
        expires = result.get("expires_at", "نامشخص")
        success_text = ACTIVATION_SUCCESS_TEXT.format(expires_at=expires)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📊 وضعیت لایسنس", callback_data="license:status"))
        bot.send_message(message.chat.id, success_text, parse_mode="HTML", reply_markup=kb)
    else:
        error_msg = result.get("message", "خطای نامشخص")
        fail_text = ACTIVATION_FAIL_TEXT.format(message=error_msg)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 تلاش مجدد", callback_data="license:activate"))
        bot.send_message(message.chat.id, fail_text, parse_mode="HTML", reply_markup=kb)


# ── Callback: limited mode info for regular users ─────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "license:limited_info")
def cb_limited_info(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "🔒 <b>ربات در حالت محدود اجرا می‌شود.</b>\n\n"
        "برای فعال‌سازی کامل ربات، با مالک تماس بگیرید.\n"
        "یا برای خرید اشتراک به @Emad_Habibnia پیام دهید.",
        parse_mode="HTML",
    )
