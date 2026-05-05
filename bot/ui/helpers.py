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
from .premium_emoji import ce

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
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # Resolve chat_id and thread_id for fallback sends
    if hasattr(call_or_msg, "message"):
        _chat_id   = call_or_msg.message.chat.id
        _thread_id = getattr(call_or_msg.message, "message_thread_id", None)
    else:
        _chat_id   = call_or_msg.chat.id
        _thread_id = getattr(call_or_msg, "message_thread_id", None)

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
                disable_web_page_preview=disable_preview,
                message_thread_id=_thread_id,
            )
    except Exception as _e1:
        _e1_str = str(_e1)
        # Silence known harmless edit errors — fallback to send_message handles them.
        _silent_edit_errors = ("no text in the message", "message is not modified")
        if not any(s in _e1_str.lower() for s in _silent_edit_errors):
            _log.warning("send_or_edit primary failed: %s", _e1)
        try:
            bot.send_message(_chat_id, text,
                             parse_mode="HTML",
                             reply_markup=reply_markup,
                             disable_web_page_preview=disable_preview,
                             message_thread_id=_thread_id)
        except Exception as _e2:
            _log.warning("send_or_edit fallback-HTML failed: %s", _e2)
            # Last-resort: send without HTML parse mode (strip HTML tags)
            try:
                import re as _re
                plain = _re.sub(r"<[^>]+>", "", text)
                plain = plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')
                bot.send_message(_chat_id, plain,
                                 parse_mode="",
                                 reply_markup=reply_markup,
                                 disable_web_page_preview=disable_preview,
                                 message_thread_id=_thread_id)
            except Exception as _e3:
                _log.error("send_or_edit last-resort plain failed: %s", _e3)


def _get_all_locked_channels() -> list:
    """Return the deduplicated list of locked channels from the DB table.
    The legacy channel_id setting is migrated to the table on startup (main.py).
    This fallback still reads it so the bot works before the first restart."""
    seen = set()
    channels = []

    def _add(ch):
        key = ch.lower().lstrip("@")
        if key and key not in seen:
            seen.add(key)
            channels.append(ch)

    try:
        rows = get_locked_channels()
        for row in rows:
            _add(str(row["channel_id"]).strip())
    except Exception:
        pass
    # Legacy fallback — cleared by main.py on startup after migration
    legacy = setting_get("channel_id", "").strip()
    if legacy:
        _add(legacy)
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
    all_checked = True  # True only if every channel was successfully queried
    for channel_id in channels:
        try:
            member = bot.get_chat_member(channel_id, user_id)
            if member.status not in ("member", "administrator", "creator"):
                # Telegram explicitly says user is not a member → block
                is_member = False
                break
        except Exception as e:
            # Two cases:
            # 1. Bot is not an admin/member of this channel → can't verify → skip (fail-open)
            # 2. Other API error
            # Either way we cannot confirm the user IS a member, so mark result as uncertain
            # and do NOT cache a positive result.
            err = str(e).lower()
            # If Telegram explicitly reports user is not a participant → block
            if "user_not_participant" in err or "participant" in err:
                is_member = False
                break
            # Otherwise (bot lacks permissions, network error, etc.) → skip this channel
            all_checked = False

    # Only cache when every channel could be checked; uncertain results are not cached
    # so the next request triggers a fresh check.
    if all_checked or not is_member:
        with _CHANNEL_CACHE_LOCK:
            _CHANNEL_CACHE[user_id] = (is_member, now)
    return is_member


def channel_lock_message(target):
    channels = _get_all_locked_channels()
    kb = types.InlineKeyboardMarkup()
    _bot_username = ""
    try:
        _bot_username = bot.get_me().username or ""
    except Exception:
        pass
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
            kb.add(types.InlineKeyboardButton(
                f"📢 {label}",
                url=url,
                icon_custom_emoji_id="5348125643852758491",
            ))
    else:
        kb.add(types.InlineKeyboardButton(
            "📢 عضویت در کانال",
            url="https://t.me/",
            icon_custom_emoji_id="5348125643852758491",
        ))
    kb.add(types.InlineKeyboardButton(
        "✅ عضو شدم",
        callback_data="check_channel",
        icon_custom_emoji_id="5350659885010797372",
    ))
    _bot_mention = f"@{_bot_username}" if _bot_username else "ربات"
    send_or_edit(
        target,
        f"{ce('🔒', '5990125934940787455')} برای استفاده از {_bot_mention}، ابتدا باید در کانال‌های ما عضو شوید.\n\n"
        f"{ce('✅', '5990309862620271638')} پس از عضویت در همه کانال‌ها، روی «عضو شدم» بزنید.",
        kb
    )
