# -*- coding: utf-8 -*-
"""
Inline keyboard builders for main menu and admin panel.
"""
import json
from telebot import types

from ..config import ADMIN_IDS, PERM_USER_FULL
from ..db import setting_get, wallet_pay_enabled_for
from ..helpers import is_admin, admin_has_perm


def _btn(text, callback_data=None, url=None, emoji_id=None, copy_text=None):
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
    rows.append([
        _btn("خرید سرویس جدید", callback_data="buy:start",      emoji_id="5312361253610475399"),
        _btn("سرویس‌های من",     callback_data="my_configs",      emoji_id="5361741454685256344"),
    ])
    _ft_mode = setting_get("free_test_mode", "everyone")
    if _ft_mode == "everyone" or (_ft_mode == "agents_only" and _user_is_agent(user_id)):
        rows.append([_btn("تست رایگان", callback_data="test:start", emoji_id="6283073379184415506")])
    rows.append([
        _btn("حساب کاربری",  callback_data="profile",        emoji_id="5373012449597335010"),
        *([_btn("شارژ کیف پول", callback_data="wallet:charge",  emoji_id="5931368295545443065")] if wallet_pay_enabled_for(user_id) else []),
    ])
    ref_on     = setting_get("referral_enabled", "1") == "1"
    voucher_on = setting_get("vouchers_enabled", "1") == "1"
    if ref_on and voucher_on:
        rows.append([
            _btn("دعوت دوستان",    callback_data="referral:menu",   emoji_id="5453957997418004470"),
            _btn("ثبت کارت هدیه", callback_data="voucher:redeem",  emoji_id="5418010521309815154"),
        ])
    elif ref_on:
        rows.append([_btn("دعوت دوستان",    callback_data="referral:menu",  emoji_id="5453957997418004470")])
    elif voucher_on:
        rows.append([_btn("ثبت کارت هدیه", callback_data="voucher:redeem", emoji_id="5418010521309815154")])
    rows.append([_btn("ارتباط با پشتیبانی", callback_data="support", emoji_id="5467539229468793355")])
    if setting_get("agency_request_enabled", "1") == "1":
        rows.append([_btn("درخواست نمایندگی", callback_data="agency:request", emoji_id="5372957680174384345")])
    if is_admin(user_id):
        rows.append([_btn("ورود به پنل مدیریت", callback_data="admin:panel", emoji_id="5370935802844946281")])
    return _raw_markup(rows)


def kb_admin_panel(uid=None):
    rows = []
    is_owner = (uid in ADMIN_IDS) if uid else False

    # ── نوع و پکیج ────────────────────────────────────────────────────────────
    if is_owner or (uid and admin_has_perm(uid, "types_packages")):
        rows.append([_btn("مدیریت نوع و پکیج‌ها", callback_data="admin:types", emoji_id="5463224921935082813")])

    # ── کانفیگ ها ─────────────────────────────────────────────────────────────
    if is_owner or (uid and (admin_has_perm(uid, "view_configs") or
                             admin_has_perm(uid, "register_config") or
                             admin_has_perm(uid, "manage_configs"))):
        rows.append([
            _btn("کانفیگ های دستی", callback_data="admin:stock",        emoji_id="6017209397413941115"),
            _btn("کانفیگ های پنل",  callback_data="admin:panel_configs", emoji_id="5372926953978341366"),
        ])

    # ── کاربران + ادمین‌ها + نمایندگان — همه در یک ردیف ──────────────────────
    show_users  = is_owner or (uid and (admin_has_perm(uid, "view_users") or
                                        admin_has_perm(uid, "full_users") or
                                        any(admin_has_perm(uid, p) for p in PERM_USER_FULL)))
    show_admins = is_owner
    show_agents = is_owner or (uid and admin_has_perm(uid, "agency"))

    user_row = []
    if show_users:
        user_row.append(_btn("کاربران", callback_data="admin:users",  emoji_id="5258513401784573443"))
    if show_admins:
        user_row.append(_btn("ادمین‌ها", callback_data="admin:admins", emoji_id="5404568051062425670"))
    if show_agents:
        user_row.append(_btn("نمایندگان", callback_data="admin:agents", emoji_id="5908990051349434897"))
    if user_row:
        rows.append(user_row)

    # ── رسیدها + مدیریت پنل‌ها ───────────────────────────────────────────────
    show_pr     = is_owner or (uid and admin_has_perm(uid, "approve_payments"))
    show_panels = is_owner or (uid and admin_has_perm(uid, "manage_panels"))
    pr_panel_row = []
    if show_pr:
        pr_panel_row.append(_btn("رسیدهای بررسی نشده", callback_data="admin:pr",     emoji_id="5926764846518376076"))
    if show_panels:
        pr_panel_row.append(_btn("مدیریت پنل‌ها",       callback_data="admin:panels", emoji_id="5372926953978341366"))
    if pr_panel_row:
        rows.append(pr_panel_row)

    # ── تخفیف+کارت هدیه  |  فوروارد و پین ───────────────────────────────────
    show_broadcast = is_owner or (uid and (admin_has_perm(uid, "broadcast_all") or admin_has_perm(uid, "broadcast_cust")))
    disc_bc_row = []
    if is_owner:
        disc_bc_row.append(_btn("تخفیف و کارت هدیه", callback_data="admin:gifts_menu", emoji_id="5377599075237502153"))
    if show_broadcast:
        disc_bc_row.append(_btn("فوروارد و پین همگانی", callback_data="admin:broadcast", emoji_id="5416106115630918483"))
    if disc_bc_row:
        rows.append(disc_bc_row)

    # ── آمار فروش + تنظیمات ──────────────────────────────────────────────────
    show_stats    = is_owner or (uid and admin_has_perm(uid, "view_users"))
    show_settings = is_owner or (uid and admin_has_perm(uid, "settings"))
    stats_set_row = []
    if show_stats:
        stats_set_row.append(_btn("📊 آمار فروش", callback_data="admin:stats",    emoji_id="5370935802844946281"))
    if show_settings:
        stats_set_row.append(_btn("تنظیمات",      callback_data="admin:settings", emoji_id="5370935802844946281"))
    if stats_set_row:
        rows.append(stats_set_row)

    # ── لایسنس — ته منو ───────────────────────────────────────────────────────
    if is_owner:
        from ..license_manager import is_limited_mode as _is_limited
        if _is_limited():
            rows.append([_btn("🔐 فعال‌سازی لایسنس", callback_data="license:activate")])
        else:
            rows.append([_btn("🔐 مدیریت لایسنس", callback_data="license:status")])

    rows.append([_btn("بازگشت", callback_data="nav:main", emoji_id="5253997076169115797")])
    return _raw_markup(rows)
