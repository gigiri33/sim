# -*- coding: utf-8 -*-
"""
Core Telegram UI helpers: message editing/sending, bot commands,
channel lock enforcement.
"""
import time
import threading
from telebot import types

from ..db import setting_get, get_locked_channels
from ..bot_instance import bot

# ── Channel membership cache (TTL = 60 s) ─────────────────────────────────────
# Each bot.get_chat_member() call is an HTTP round-trip to Telegram (~100-300ms).
# Caching the result per-user for 60 s cuts the vast majority of these calls.
_CHANNEL_CACHE: dict[int, tuple[bool, float]] = {}
_CHANNEL_CACHE_LOCK = threading.Lock()
_CHANNEL_CACHE_TTL  = 30.0   # seconds — short TTL so leaving the channel is detected quickly


def _invalidate_channel_cache(user_id: int | None = None) -> None:
    """Invalidate one user or the whole cache (pass None)."""
    with _CHANNEL_CACHE_LOCK:
        if user_id is None:
            _CHANNEL_CACHE.clear()
        else:
            _CHANNEL_CACHE.pop(user_id, None)


# ── Bot commands ───────────────────────────────────────────────────────────────
def set_bot_commands():
    try:
        bot.set_my_commands([types.BotCommand("start", "شروع ربات")])
    except Exception:
        pass


# ── Message send/edit ──────────────────────────────────────────────────────────
def send_or_edit(call_or_msg, text, reply_markup=None, disable_preview=True):
    """Edit an existing message (from a callback) or send a new one."""
    try:
        if hasattr(call_or_msg, "message"):
            bot.edit_message_text(
                text,
                call_or_msg.message.chat.id,
                call_or_msg.message.message_id,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=disable_preview,
            )
        else:
            bot.send_message(
                call_or_msg.chat.id, text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=disable_preview
            )
    except Exception:
        try:
            chat_id = (
                call_or_msg.message.chat.id
                if hasattr(call_or_msg, "message")
                else call_or_msg.chat.id
            )
            bot.send_message(chat_id, text,
                             parse_mode="HTML",
                             reply_markup=reply_markup,
                             disable_web_page_preview=disable_preview)
        except Exception:
            pass


def _get_all_locked_channels() -> list:
    """Return the merged list of channels from DB table + legacy channel_id setting."""
    channels = []
    try:
        rows = get_locked_channels()
        for row in rows:
            ch = str(row["channel_id"]).strip()
            if ch and ch not in channels:
                channels.append(ch)
    except Exception:
        pass
    legacy = setting_get("channel_id", "").strip()
    if legacy and legacy not in channels:
        channels.append(legacy)
    return channels


def _channel_url(channel_id):
    if channel_id.startswith("@"):
        return "https://t.me/{}".format(channel_id.lstrip("@"))
    if channel_id.startswith("-100"):
        return "https://t.me/c/{}".format(channel_id[4:])
    return "https://t.me/{}".format(channel_id)


# ── Channel lock ───────────────────────────────────────────────────────────────
def check_channel_membership(user_id):
    channels = _get_all_locked_channels()
    if not channels:
        return True

    now = time.monotonic()
    with _CHANNEL_CACHE_LOCK:
        cached = _CHANNEL_CACHE.get(user_id)
        if cached is not None:
            result, ts = cached
            if (now - ts) < _CHANNEL_CACHE_TTL:
                return result

    # Cache miss or stale — user must be in ALL channels
    is_member = True
    for channel_id in channels:
        try:
            member = bot.get_chat_member(channel_id, user_id)
            if member.status not in ("member", "administrator", "creator"):
                is_member = False
                break
        except Exception:
            pass  # fail-open

    with _CHANNEL_CACHE_LOCK:
        _CHANNEL_CACHE[user_id] = (is_member, now)
    return is_member


def channel_lock_message(target):
    channels = _get_all_locked_channels()
    kb = types.InlineKeyboardMarkup()
    if channels:
        for channel_id in channels:
            url = _channel_url(channel_id)
            if channel_id.startswith("@"):
                label = channel_id  # e.g. @MyChannel
            else:
                # Numeric ID — try to resolve username from Telegram
                try:
                    chat = bot.get_chat(channel_id)
                    label = f"@{chat.username}" if chat.username else channel_id
                except Exception:
                    label = channel_id
            kb.add(types.InlineKeyboardButton("📢 {}".format(label), url=url))
    else:
        kb.add(types.InlineKeyboardButton("📢 عضویت در کانال", url="https://t.me/"))
    kb.add(types.InlineKeyboardButton("✅ عضو شدم", callback_data="check_channel"))
    send_or_edit(
        target,
        "🔒 برای استفاده از ربات، ابتدا باید در کانال‌های ما عضو شوید.\n\nپس از عضویت در همه کانال‌ها، روی «عضو شدم» بزنید.",
        kb
    )
