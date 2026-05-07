# -*- coding: utf-8 -*-
"""
License command handler — only /license_status command.
All callback routing is handled in _dispatch_callback (callbacks.py).
The message state (license:waiting_api_key) is handled in universal_handler (messages.py).
"""
from telebot import types

from ..bot_instance import bot
from ..helpers import is_admin
from ..config import ADMIN_IDS
from ..license_manager import (
    is_limited_mode,
    get_license_status_text,
)


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
