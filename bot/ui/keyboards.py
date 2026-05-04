# -*- coding: utf-8 -*-
"""
Inline keyboard builders for main menu and admin panel.
"""
import json
from telebot import types

from ..config import ADMIN_IDS, PERM_USER_FULL
from ..db import setting_get
from ..helpers import is_admin, admin_has_perm
from .start_menu import build_main_menu_rows


def _btn(text, callback_data=None, url=None, emoji_id=None, copy_text=None, style=None):
    """Build an InlineKeyboardButton dict with optional icon_custom_emoji_id."""
    d = {"text": text}
    if callback_data is not None:
        d["callback_data"] = callback_data
    if url is not None:
        d["url"] = url
    if emoji_id is not None:
        d["icon_custom_emoji_id"] = str(emoji_id)
    if copy_text is not None:
        d["copy_text"] = {"text": str(copy_text)}
    if style is not None:
        d["style"] = style
    return d


def _raw_markup(rows):
    """Serialize an inline_keyboard rows list to a JSON string for reply_markup."""
    return json.dumps({"inline_keyboard": rows})


def _user_is_agent(user_id) -> bool:
    try:
        from ..db import get_user
        u = get_user(user_id)
        return bool(u and u["is_agent"])
    except Exception:
        return False


def kb_main(user_id):
    rows = []
    for row in build_main_menu_rows(user_id):
        rows.append([
            _btn(
                item["text"],
                callback_data=item["callback_data"],
                emoji_id=item.get("emoji_id"),
                style=item.get("style"),
            )
            for item in row
        ])
    return _raw_markup(rows)


def kb_admin_panel(uid=None):
    rows = []
    is_owner = (uid in ADMIN_IDS) if uid else False

    if is_owner or (uid and admin_has_perm(uid, "types_packages")):
        rows.append([_btn("مدیریت نوع و پکیج‌ها", callback_data="admin:types", emoji_id="5463224921935082813")])

    if is_owner or (uid and (admin_has_perm(uid, "view_configs") or
                             admin_has_perm(uid, "register_config") or
                             admin_has_perm(uid, "manage_configs"))):
        rows.append([
            _btn("کانفیگ های دستی", callback_data="admin:stock",        emoji_id="6017209397413941115"),
            _btn("کانفیگ های پنل",  callback_data="admin:panel_configs", emoji_id="5372926953978341366"),
        ])

    show_users  = is_owner or (uid and (admin_has_perm(uid, "view_users") or
                                        admin_has_perm(uid, "full_users") or
                                        any(admin_has_perm(uid, p) for p in PERM_USER_FULL)))
    show_agents = is_owner or (uid and admin_has_perm(uid, "agency"))

    # Row: مدیریت کاربران | مدیریت ادمین‌ها | مدیریت نمایندگان
    row_mgmt = []
    if show_users:
        row_mgmt.append(_btn("مدیریت کاربران", callback_data="admin:users", emoji_id="5258513401784573442"))
    if is_owner:
        row_mgmt.append(_btn("مدیریت ادمین‌ها", callback_data="admin:admins", emoji_id="5404568051062425670"))
    if show_agents:
        row_mgmt.append(_btn("مدیریت نمایندگان", callback_data="admin:agents", emoji_id="5908990051349434897"))
    if row_mgmt:
        rows.append(row_mgmt)

    # Row: آمار فروش | تنظیمات
    row_stats_settings = []
    if is_owner or (uid and admin_has_perm(uid, "view_users")):
        row_stats_settings.append(_btn("📊 آمار فروش", callback_data="admin:stats"))
    if is_owner or (uid and admin_has_perm(uid, "settings")):
        row_stats_settings.append(_btn("تنظیمات", callback_data="admin:settings", emoji_id="5370935802844946281"))
    if row_stats_settings:
        rows.append(row_stats_settings)

    # Row: فوروارد و پین | کارت هدیه / کد تخفیف
    show_broadcast = is_owner or (uid and (admin_has_perm(uid, "broadcast_all") or admin_has_perm(uid, "broadcast_cust")))
    if is_owner:
        row_tools = []
        if show_broadcast:
            row_tools.append(_btn("فوروارد و پین همگانی", callback_data="admin:broadcast", emoji_id="5416106115630918483"))
        row_tools.append(_btn("🎁 کارت هدیه / کد تخفیف", callback_data="admin:gifts"))
        rows.append(row_tools)
    elif show_broadcast:
        rows.append([_btn("فوروارد و پین همگانی", callback_data="admin:broadcast", emoji_id="5416106115630918483")])

    # Row: رسیدهای بررسی نشده | مدیریت پنل‌ها
    row_ops = []
    show_pr = is_owner or (uid and admin_has_perm(uid, "approve_payments"))
    if show_pr:
        row_ops.append(_btn("رسیدهای بررسی نشده", callback_data="admin:pr", emoji_id="5926764846518376076"))
    if is_owner or (uid and admin_has_perm(uid, "manage_panels")):
        row_ops.append(_btn("مدیریت پنل‌ها", callback_data="admin:panels", emoji_id="5372926953978341366"))
    if row_ops:
        rows.append(row_ops)

    # Row: مدیریت لایسنس (پایین‌ترین)
    if is_owner:
        from ..license_manager import is_limited_mode as _is_limited
        if _is_limited():
            rows.append([_btn("🔐 فعال‌سازی لایسنس", callback_data="license:activate")])
        else:
            rows.append([_btn("🔐 مدیریت لایسنس", callback_data="license:status")])

    rows.append([_btn("بازگشت", callback_data="nav:main", emoji_id="5253997076169115797")])
    return _raw_markup(rows)
