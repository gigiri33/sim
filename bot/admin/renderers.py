# -*- coding: utf-8 -*-
"""
Admin panel renderer helpers — reusable screen-building functions
for types, stock, users, admins, panels.
"""
from telebot import types

from ..config import ADMIN_PERMS, PERM_EMOJI_IDS
from ..db import (
    get_all_types, get_packages, get_registered_packages_stock,
    get_all_admin_users, get_user, get_user_detail, get_phone_number,
    count_users_stats,
)
from ..helpers import esc, fmt_price, display_username, back_button
from ..ui.keyboards import _btn, _raw_markup
from ..bot_instance import bot
from ..ui.helpers import send_or_edit


# ── Types & packages ───────────────────────────────────────────────────────────
def _show_admin_types(call):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ افزودن نوع جدید", callback_data="admin:type:add"))
    all_types = get_all_types()
    for item in all_types:
        is_type_active = item["is_active"] if "is_active" in item.keys() else 1
        type_status_icon = "✅" if is_type_active else "❌"
        kb.add(types.InlineKeyboardButton(f"{type_status_icon} 🧩 {item['name']}", callback_data="noop"))
        kb.row(
            types.InlineKeyboardButton("✏️ ویرایش", callback_data=f"admin:type:edit:{item['id']}"),
            types.InlineKeyboardButton("🗑 حذف",    callback_data=f"admin:type:del:{item['id']}"),
        )
        kb.add(types.InlineKeyboardButton(
            f"➕ افزودن پکیج برای {item['name']}",
            callback_data=f"admin:pkg:add:t:{item['id']}"
        ))
        packs = get_packages(type_id=item['id'], include_inactive=True)
        for p in packs:
            pkg_active = p["active"] if "active" in p.keys() else 1
            pkg_status_icon = "✅" if pkg_active else "❌"
            kb.row(
                types.InlineKeyboardButton(
                    f"{pkg_status_icon} 📦 {p['name']} | {p['volume_gb']}GB | {fmt_price(p['price'])}ت",
                    callback_data="noop"
                ),
                types.InlineKeyboardButton("✏️", callback_data=f"admin:pkg:edit:{p['id']}"),
                types.InlineKeyboardButton("🗑",  callback_data=f"admin:pkg:del:{p['id']}"),
            )
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, "🧩 <b>مدیریت نوع و پکیج‌ها</b>", kb)


# ── Stock ──────────────────────────────────────────────────────────────────────
def _show_admin_stock(call):
    rows = get_registered_packages_stock()
    kb   = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📝 ثبت کانفیگ",   callback_data="admin:add_config"))
    kb.add(types.InlineKeyboardButton("🔍 جستجو",          callback_data="adm:stk:search"))
    total_avail   = sum(r["stock"] for r in rows)
    total_sold    = sum(r["sold_count"] for r in rows)
    total_expired = sum(r["expired_count"] for r in rows)
    kb.row(
        types.InlineKeyboardButton(f"🟢 کل موجود ({total_avail})",  callback_data="adm:stk:all:av:0"),
        types.InlineKeyboardButton(f"🔴 کل فروخته ({total_sold})", callback_data="adm:stk:all:sl:0"),
        types.InlineKeyboardButton(f"❌ کل منقضی ({total_expired})", callback_data="adm:stk:all:ex:0"),
    )
    for row in rows:
        pending_c     = row['pending_count'] if row['pending_count'] else 0
        pending_label = f" ⏳{pending_c}" if pending_c > 0 else ""
        kb.add(types.InlineKeyboardButton(
            f"📦 {row['type_name']} - {row['name']} | 🟢{row['stock']} 🔴{row['sold_count']} ❌{row['expired_count']}{pending_label}",
            callback_data=f"adm:stk:pk:{row['id']}"
        ))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, "📁 <b>کانفیگ‌ها</b>", kb)


# ── Admins management ──────────────────────────────────────────────────────────
def _show_admin_admins_panel(call):
    admins = get_all_admin_users()
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ افزودن ادمین جدید", callback_data="adm:mgr:add"))
    for row in admins:
        user_row = get_user(row["user_id"])
        name = user_row["full_name"] if user_row else f"کاربر {row['user_id']}"
        kb.add(types.InlineKeyboardButton(
            f"👮 {name} | {row['user_id']}",
            callback_data=f"adm:mgr:v:{row['user_id']}"
        ))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
    count = len(admins)
    text = (
        f"👮 <b>مدیریت ادمین‌ها</b>\n\n"
        f"تعداد ادمین‌های ثبت‌شده: <b>{count}</b>\n\n"
        "برای مشاهده یا ویرایش دسترسی هر ادمین روی نام آن کلیک کنید."
    )
    send_or_edit(call, text, kb)


def _show_perm_selection(call, uid, target_id, perms, edit_mode=False):
    user_row = get_user(target_id)
    name = user_row["full_name"] if user_row else f"کاربر {target_id}"
    text = (
        f"🔑 <b>انتخاب سطح دسترسی</b>\n\n"
        f"👤 کاربر: {esc(name)} (<code>{target_id}</code>)\n\n"
        "سطح دسترسی‌های مورد نظر را انتخاب کنید:\n"
        "(هر گزینه را بزنید تا فعال/غیرفعال شود)"
    )
    rows = []
    for perm_key, perm_label in ADMIN_PERMS:
        checked = bool(perms.get(perm_key))
        icon    = "✅" if checked else "⬜️"
        eid     = PERM_EMOJI_IDS.get(perm_key)
        rows.append([_btn(
            f"{icon} {perm_label}",
            callback_data=f"adm:mgr:pt:{perm_key}",
            emoji_id=eid,
        )])
    action_label = "💾 ذخیره تغییرات" if edit_mode else "➕ افزودن ادمین"
    rows.append([_btn(action_label, callback_data="adm:mgr:confirm")])
    rows.append([_btn("بازگشت", callback_data="admin:admins", emoji_id="5352759161945867747")])
    send_or_edit(call, text, _raw_markup(rows))


# ── Users list & detail ────────────────────────────────────────────────────────
def _show_admin_users_list(call, page=0, filter_mode="all"):
    from ..db import get_users, count_all_users
    PER_PAGE = 12
    # Map filter_mode to has_purchase arg and status filter
    hp = None
    status_filter = None
    if filter_mode == "buyers":
        hp = True
    elif filter_mode == "new":
        hp = False
    elif filter_mode in ("safe", "unsafe", "restricted"):
        status_filter = filter_mode

    # DB-level pagination — no Python re-sort, newest users first
    # We need total for this filter to build pages
    all_count_q_rows = get_users(has_purchase=hp, status=status_filter)
    total_filtered   = len(all_count_q_rows)
    total_pages      = max(1, (total_filtered + PER_PAGE - 1) // PER_PAGE)
    page             = max(0, min(page, total_pages - 1))
    page_rows        = get_users(has_purchase=hp, status=status_filter, limit=PER_PAGE, offset=page * PER_PAGE)

    total, buyers, new_today = count_users_stats()

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="adm:usr:search"))

    # Filter bar — row 1: general
    all_icon    = "▶️ " if filter_mode == "all"    else ""
    buyers_icon = "▶️ " if filter_mode == "buyers" else ""
    new_icon    = "▶️ " if filter_mode == "new"    else ""
    kb.row(
        types.InlineKeyboardButton(f"{all_icon}همه ({total})",          callback_data="adm:usr:fl:all:0"),
        types.InlineKeyboardButton(f"{buyers_icon}خریداران ({buyers})", callback_data="adm:usr:fl:buyers:0"),
        types.InlineKeyboardButton(f"{new_icon}بدون خرید",              callback_data="adm:usr:fl:new:0"),
    )

    # Filter bar — row 2: security status
    safe_icon       = "▶️ " if filter_mode == "safe"       else ""
    unsafe_icon     = "▶️ " if filter_mode == "unsafe"     else ""
    restricted_icon = "▶️ " if filter_mode == "restricted" else ""
    kb.row(
        types.InlineKeyboardButton(f"{safe_icon}🔘 امن",         callback_data="adm:usr:fl:safe:0"),
        types.InlineKeyboardButton(f"{unsafe_icon}⚠️ ناامن",     callback_data="adm:usr:fl:unsafe:0"),
        types.InlineKeyboardButton(f"{restricted_icon}🚫 محدود", callback_data="adm:usr:fl:restricted:0"),
    )

    for row in page_rows:
        if row["status"] == "safe":
            status_icon = "🔘"
        elif row["status"] == "restricted":
            status_icon = "🚫"
        else:
            status_icon = "⚠️"
        agent_icon  = "🤝" if row["is_agent"] else ""
        buy_icon    = f" 🛍{row['purchase_count']}" if row["purchase_count"] else ""
        name_part   = row["full_name"] or f"بدون نام ({row['user_id']})"
        uname_part  = f" | @{row['username']}" if row["username"] else ""
        label       = f"{status_icon}{agent_icon} {name_part}{uname_part}{buy_icon}"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:usr:v:{row['user_id']}"))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"adm:usr:fl:{filter_mode}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton("➡️ بعدی", callback_data=f"adm:usr:fl:{filter_mode}:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))

    text = (
        f"👥 <b>مدیریت کاربران</b>\n\n"
        f"👤 کل کاربران: <b>{total}</b>\n"
        f"🛍 خریداران: <b>{buyers}</b>\n"
        f"📭 بدون خرید: <b>{total - buyers}</b>\n"
        f"🆕 امروز: <b>{new_today}</b>\n\n"
        f"📄 صفحه {page + 1} از {total_pages} | نمایش: {total_filtered} نفر"
    )
    send_or_edit(call, text, kb)


def _user_status_label(status):
    if status == "safe":
        return "🔘 امن"
    elif status == "restricted":
        return "🚫 محدود"
    else:
        return "⚠️ ناامن"


def _show_admin_user_detail(call, user_id):
    row = get_user_detail(user_id)
    if not row:
        send_or_edit(call, "کاربر یافت نشد.", back_button("admin:users"))
        return
    status_label = _user_status_label(row["status"])
    agent_label  = "🤝 نمایندگی فعال" if row["is_agent"] else "❌ نمایندگی غیرفعال"
    phone = get_phone_number(row["user_id"])
    phone_line = f"📞 شماره تلفن: <code>{esc(phone)}</code>\n" if phone else "📞 شماره تلفن: ثبت نشده\n"
    text = (
        "👤 <b>اطلاعات کاربر</b>\n\n"
        f"📱 نام: {esc(row['full_name'])}\n"
        f"🆔 نام کاربری: {esc(display_username(row['username']))}\n"
        f"🔢 آیدی: <code>{row['user_id']}</code>\n"
        f"{phone_line}"
        f"💰 موجودی: <b>{fmt_price(row['balance'])}</b> تومان\n"
        f"🛍 تعداد خرید: <b>{row['purchase_count']}</b>\n"
        f"💵 مجموع خرید: <b>{fmt_price(row['total_spent'])}</b> تومان\n"
        f"🕒 عضویت: {esc(row['joined_at'])}\n"
        f"وضعیت: {status_label}\n"
        f"نمایندگی: {agent_label}"
    )
    uid_t = row["user_id"]
    kb    = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(f"🔄 {status_label}", callback_data=f"adm:usr:sts:{uid_t}"),
        types.InlineKeyboardButton(f"🤝 نمایندگی",       callback_data=f"adm:usr:ag:{uid_t}"),
    )
    kb.add(types.InlineKeyboardButton("💰 موجودی",           callback_data=f"adm:usr:bal:{uid_t}"))
    kb.add(types.InlineKeyboardButton("📦 کانفیگ‌ها",         callback_data=f"adm:usr:cfgs:{uid_t}"))
    kb.add(types.InlineKeyboardButton("💰 قیمت نمایندگی کاربر", callback_data=f"adm:agcfg:{uid_t}"))
    kb.add(types.InlineKeyboardButton("✉️ پیام خصوصی به کاربر", callback_data=f"adm:usr:dm:{uid_t}"))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:users", icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)


def _show_admin_user_detail_msg(chat_id, user_id):
    """Send user detail as a new message (for use from message handlers)."""
    row = get_user_detail(user_id)
    if not row:
        bot.send_message(chat_id, "کاربر یافت نشد.", reply_markup=back_button("admin:users"))
        return
    status_label = _user_status_label(row["status"])
    agent_label  = "🤝 نمایندگی فعال" if row["is_agent"] else "❌ نمایندگی غیرفعال"
    phone = get_phone_number(row["user_id"])
    phone_line = f"📞 شماره تلفن: <code>{esc(phone)}</code>\n" if phone else "📞 شماره تلفن: ثبت نشده\n"
    text = (
        "👤 <b>اطلاعات کاربر</b>\n\n"
        f"📱 نام: {esc(row['full_name'])}\n"
        f"🆔 نام کاربری: {esc(display_username(row['username']))}\n"
        f"🔢 آیدی: <code>{row['user_id']}</code>\n"
        f"{phone_line}"
        f"💰 موجودی: <b>{fmt_price(row['balance'])}</b> تومان\n"
        f"🛍 تعداد خرید: <b>{row['purchase_count']}</b>\n"
        f"💵 مجموع خرید: <b>{fmt_price(row['total_spent'])}</b> تومان\n"
        f"🕒 عضویت: {esc(row['joined_at'])}\n"
        f"وضعیت: {status_label}\n"
        f"نمایندگی: {agent_label}"
    )
    uid_t = row["user_id"]
    kb    = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(f"🔄 {status_label}", callback_data=f"adm:usr:sts:{uid_t}"),
        types.InlineKeyboardButton(f"🤝 نمایندگی",       callback_data=f"adm:usr:ag:{uid_t}"),
    )
    kb.add(types.InlineKeyboardButton("💰 موجودی",           callback_data=f"adm:usr:bal:{uid_t}"))
    kb.add(types.InlineKeyboardButton("📦 کانفیگ‌ها",         callback_data=f"adm:usr:cfgs:{uid_t}"))
    kb.add(types.InlineKeyboardButton("💰 قیمت نمایندگی کاربر", callback_data=f"adm:agcfg:{uid_t}"))
    kb.add(types.InlineKeyboardButton("✉️ پیام خصوصی به کاربر", callback_data=f"adm:usr:dm:{uid_t}"))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:users", icon_custom_emoji_id="5253997076169115797"))
    bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")


def _show_admin_assign_config_type(call, target_id):
    items = get_all_types()
    kb    = types.InlineKeyboardMarkup()
    for item in items:
        kb.add(types.InlineKeyboardButton(
            f"🧩 {item['name']}",
            callback_data=f"adm:acfg:t:{target_id}:{item['id']}"
        ))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, "📝 نوع کانفیگ را انتخاب کنید:", kb)


def _fake_call(call, new_data):
    """Re-dispatch a callback with different data (for re-rendering pages)."""
    from ..handlers.callbacks import _dispatch_callback

    class _FakeCall:
        def __init__(self, original, data):
            self.from_user = original.from_user
            self.message   = original.message
            self.data      = data
            self.id        = original.id

    _dispatch_callback(_FakeCall(call, new_data), call.from_user.id, new_data)

