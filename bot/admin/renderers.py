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
    get_panel_configs, get_panel_configs_count, get_panel_config_full,
    get_panel_client_packages, get_panel_client_package,
    get_panel,
    setting_get,
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
    kb.add(types.InlineKeyboardButton("⚡️ عملیات گروهی روی تمامی کاربران", callback_data="adm:usr:bulk"))

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
    panel_renew = row["panel_renew_count"] if "panel_renew_count" in row.keys() else 0
    credit_enabled = row["purchase_credit_enabled"] if "purchase_credit_enabled" in row.keys() else 0
    credit_limit   = row["purchase_credit_limit"]   if "purchase_credit_limit"   in row.keys() else 0
    admin_adj      = row["total_admin_adjusted"]     if "total_admin_adjusted"    in row.keys() else 0
    if credit_enabled:
        balance = row['balance']
        used_credit = max(0, -balance) if balance < 0 else 0
        credit_remaining = credit_limit - used_credit
        credit_line = f"💳 اعتبار خرید: ✅ سقف: <b>{fmt_price(credit_limit)}</b> | مانده: <b>{fmt_price(credit_remaining)}</b> تومان\n"
    else:
        credit_line = "💳 اعتبار خرید: ❌ غیرفعال\n"
    total_paid = row['total_direct_payments'] + max(0, admin_adj)
    text = (
        "👤 <b>اطلاعات کاربر</b>\n\n"
        f"📱 نام: {esc(row['full_name'])}\n"
        f"🆔 نام کاربری: {esc(display_username(row['username']))}\n"
        f"🔢 آیدی: <code>{row['user_id']}</code>\n"
        f"{phone_line}"
        f"💰 موجودی: <b>{fmt_price(row['balance'])}</b> تومان\n"
        f"{credit_line}"
        f"🛍 تعداد خرید: <b>{row['purchase_count']}</b>\n"
        f"♻️ تعداد تمدیدها: <b>{row['renewal_count'] + panel_renew}</b>\n"
        f"💵 مجموع خرید: <b>{fmt_price(row['total_spent'])}</b> تومان\n"
        f"💳 مجموع تمدیدها: <b>{fmt_price(row['total_renewals'])}</b> تومان\n"
        f"💰 مجموع خرید‌ها: <b>{fmt_price(row['total_spent'] + row['total_renewals'])}</b> تومان\n"
        f"💳 مجموع پرداخت: <b>{fmt_price(total_paid)}</b> تومان\n"
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
    kb.add(types.InlineKeyboardButton("💳 اعتبار خرید",       callback_data=f"adm:credit:{uid_t}"))
    kb.add(types.InlineKeyboardButton("📦 کانفیگ‌ها",         callback_data=f"adm:usr:cfgs:{uid_t}"))
    kb.add(types.InlineKeyboardButton("👥 زیرمجموعه‌ها",      callback_data=f"adm:usr:refs:{uid_t}:0"))
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
    panel_renew = row["panel_renew_count"] if "panel_renew_count" in row.keys() else 0
    credit_enabled = row["purchase_credit_enabled"] if "purchase_credit_enabled" in row.keys() else 0
    credit_limit   = row["purchase_credit_limit"]   if "purchase_credit_limit"   in row.keys() else 0
    admin_adj      = row["total_admin_adjusted"]     if "total_admin_adjusted"    in row.keys() else 0
    if credit_enabled:
        balance = row['balance']
        used_credit = max(0, -balance) if balance < 0 else 0
        credit_remaining = credit_limit - used_credit
        credit_line = f"💳 اعتبار خرید: ✅ سقف: <b>{fmt_price(credit_limit)}</b> | مانده: <b>{fmt_price(credit_remaining)}</b> تومان\n"
    else:
        credit_line = "💳 اعتبار خرید: ❌ غیرفعال\n"
    total_paid = row['total_direct_payments'] + max(0, admin_adj)
    text = (
        "👤 <b>اطلاعات کاربر</b>\n\n"
        f"📱 نام: {esc(row['full_name'])}\n"
        f"🆔 نام کاربری: {esc(display_username(row['username']))}\n"
        f"🔢 آیدی: <code>{row['user_id']}</code>\n"
        f"{phone_line}"
        f"💰 موجودی: <b>{fmt_price(row['balance'])}</b> تومان\n"
        f"{credit_line}"
        f"🛍 تعداد خرید: <b>{row['purchase_count']}</b>\n"
        f"♻️ تعداد تمدیدها: <b>{row['renewal_count'] + panel_renew}</b>\n"
        f"💵 مجموع خرید: <b>{fmt_price(row['total_spent'])}</b> تومان\n"
        f"💳 مجموع تمدیدها: <b>{fmt_price(row['total_renewals'])}</b> تومان\n"
        f"💰 مجموع خرید‌ها: <b>{fmt_price(row['total_spent'] + row['total_renewals'])}</b> تومان\n"
        f"💳 مجموع پرداخت: <b>{fmt_price(total_paid)}</b> تومان\n"
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
    kb.add(types.InlineKeyboardButton("💳 اعتبار خرید",       callback_data=f"adm:credit:{uid_t}"))
    kb.add(types.InlineKeyboardButton("📦 کانفیگ‌ها",         callback_data=f"adm:usr:cfgs:{uid_t}"))
    kb.add(types.InlineKeyboardButton("👥 زیرمجموعه‌ها",      callback_data=f"adm:usr:refs:{uid_t}:0"))
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


# ── Panels ─────────────────────────────────────────────────────────────────────

def _panel_status_icon(panel) -> str:
    if not panel["is_active"]:
        return "⏸"
    s = panel["connection_status"]
    if s == "connected":
        return "🟢"
    if s == "disconnected":
        return "🔴"
    return "❓"


def _show_admin_panels(call):
    from ..db import get_all_panels
    panels = get_all_panels()

    text = "🖥 <b>مدیریت پنل‌ها</b>"

    rows = []
    for p in panels:
        icon = _panel_status_icon(p)
        try:
            panel_type = p["panel_type"] or "sanaei"
        except (IndexError, KeyError):
            panel_type = "sanaei"
        type_label = "صنایی" if panel_type == "sanaei" else panel_type
        rows.append([_btn(f"{icon}  {p['name']} ({type_label})", callback_data=f"adm:pnl:detail:{p['id']}")])

    rows.append([_btn("➕ افزودن پنل", callback_data="adm:pnl:add")])
    rows.append([_btn("بازگشت", callback_data="admin:panel",
                       emoji_id="5253997076169115797")])

    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup()
    for row in rows:
        kb.row(*[InlineKeyboardButton(**b) for b in row])
    send_or_edit(call, text, kb)


def _show_panel_detail(call, panel_id):
    from ..db import get_panel
    p = get_panel(panel_id)
    if not p:
        send_or_edit(call, "⚠️ پنل یافت نشد.", None)
        return

    icon = _panel_status_icon(p)
    status_label = {
        "connected":    "🟢 متصل",
        "disconnected": "🔴 قطع",
        "unknown":      "❓ بررسی نشده",
    }.get(p["connection_status"], p["connection_status"])

    path_disp = p["path"] or "<i>(ندارد)</i>"
    checked   = p["last_checked_at"] or "—"
    err_line  = f"\n⚠️ خطا: <code>{esc(p['last_error'])}</code>" if p["last_error"] else ""

    uname_disp  = p['username'] if p['username'] else '—'
    passwd_disp = p['password'] if p['password'] else '—'
    try:
        sub_url_base_disp = p['sub_url_base'] or "<i>(ندارد — از آدرس پنل استفاده می‌شود)</i>"
    except (IndexError, KeyError):
        sub_url_base_disp = "<i>(ندارد)</i>"
    try:
        updated = p['updated_at'] or '—'
    except (IndexError, KeyError):
        updated = '—'

    text = (
        f"{icon} <b>{esc(p['name'])}</b>\n\n"
        f"🔗 آدرس:  <code>{p['protocol']}://{esc(p['host'])}:{p['port']}{esc(p['path'] or '')}</code>\n"
        f"📡 ساب:   {sub_url_base_disp}\n"
        f"👤 نام کاربری: <code>{uname_disp}</code>\n"
        f"🔑 رمز عبور:   <code>{passwd_disp}</code>\n"
        f"📡 وضعیت: {status_label}\n"
        f"🕐 آخرین بررسی: {checked}"
        f"{err_line}\n\n"
        f"📅 افزوده‌شده: {p['created_at']}\n"
        f"✏️ ویرایش شده: {updated}"
    )

    is_active = int(p["is_active"])
    toggle_label    = "⏸ غیرفعال کردن" if is_active else "▶️ فعال کردن"
    toggle_callback = f"adm:pnl:toggle:{panel_id}:{0 if is_active else 1}"

    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📦 کلاینت پکیج‌ها", callback_data=f"adm:pnl:cpkgs:{panel_id}"),
    )
    kb.row(
        InlineKeyboardButton("🔄 بررسی الان",  callback_data=f"adm:pnl:recheck:{panel_id}"),
        InlineKeyboardButton(toggle_label,      callback_data=toggle_callback),
    )
    kb.row(
        InlineKeyboardButton("✏️ ویرایش پنل",  callback_data=f"adm:pnl:editpanel:{panel_id}"),
        InlineKeyboardButton("🗑 حذف پنل",     callback_data=f"adm:pnl:del:{panel_id}"),
    )
    kb.add(InlineKeyboardButton("بازگشت", callback_data="admin:panels",
                                icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)


def _show_panel_edit_menu(call, panel_id):
    """Panel edit sub-menu with all field edit buttons."""
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✏️ نام",        callback_data=f"adm:pnl:ef:name:{panel_id}"),
        InlineKeyboardButton("🌐 پروتکل",     callback_data=f"adm:pnl:ef:protocol:{panel_id}"),
    )
    kb.row(
        InlineKeyboardButton("🖥 هاست",       callback_data=f"adm:pnl:ef:host:{panel_id}"),
        InlineKeyboardButton("🔌 پورت",       callback_data=f"adm:pnl:ef:port:{panel_id}"),
    )
    kb.row(
        InlineKeyboardButton("📂 مسیر مخفی",  callback_data=f"adm:pnl:ef:path:{panel_id}"),
        InlineKeyboardButton("👤 نام کاربری", callback_data=f"adm:pnl:ef:username:{panel_id}"),
    )
    kb.add(
        InlineKeyboardButton("🔑 رمز عبور",   callback_data=f"adm:pnl:ef:password:{panel_id}"),
    )
    kb.add(InlineKeyboardButton("بازگشت", callback_data=f"adm:pnl:detail:{panel_id}",
                                icon_custom_emoji_id="5253997076169115797"))
    from ..db import get_panel as _gp
    p = _gp(panel_id)
    send_or_edit(call,
        f"✏️ <b>ویرایش پنل: {esc(p['name']) if p else panel_id}</b>\n\nفیلد مورد نظر را انتخاب کنید:",
        kb)


# ── Panel Client Packages ──────────────────────────────────────────────────────
def _show_panel_client_packages(call, panel_id):
    """List all client packages (templates) for a panel."""
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    p = get_panel(panel_id)
    if not p:
        send_or_edit(call, "⚠️ پنل یافت نشد.", None)
        return

    cpkgs = get_panel_client_packages(panel_id)
    _DM = {"config_only": "📄 فقط کانفیگ", "sub_only": "🔗 فقط ساب", "both": "📄+🔗 هر دو"}

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        "➕  افزودن کلاینت پکیج",
        callback_data=f"adm:pnl:cpkg:add:{panel_id}",
    ))
    if cpkgs:
        for cp in cpkgs:
            label = (cp["name"] or f"اینباند #{cp['inbound_id']}")[:20]
            kb.row(
                InlineKeyboardButton(f"📦 {label}",  callback_data="noop"),
                InlineKeyboardButton("✏️ ویرایش",   callback_data=f"adm:pnl:cpkg:edit:{cp['id']}"),
                InlineKeyboardButton("🗑 حذف",      callback_data=f"adm:pnl:cpkg:del:{cp['id']}"),
            )

    kb.add(InlineKeyboardButton("بازگشت", callback_data=f"adm:pnl:detail:{panel_id}",
                                icon_custom_emoji_id="5253997076169115797"))
    count_line = f"\n\n{len(cpkgs)} کلاینت پکیج ثبت‌شده" if cpkgs else "\n\nهنوز کلاینت پکیجی ثبت نشده."
    send_or_edit(
        call,
        f"📦 <b>کلاینت پکیج‌های پنل:</b> {esc(p['name'])}{count_line}",
        kb,
    )


def _show_cpkg_edit_menu(call, cpkg_id):
    """Show edit sub-menu for a client package."""
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    cp = get_panel_client_package(cpkg_id)
    if not cp:
        send_or_edit(call, "⚠️ کلاینت پکیج یافت نشد.", None)
        return
    _DM = {"config_only": "📄 فقط کانفیگ", "sub_only": "🔗 فقط ساب", "both": "📄+🔗 هر دو"}
    # sample_client_name may not exist in older rows
    try:
        scn = cp["sample_client_name"] or ""
    except (KeyError, IndexError):
        scn = ""
    text = (
        f"✏️ <b>ویرایش کلاینت پکیج #{cpkg_id}</b>\n\n"
        f"🔌 اینباند ID: <code>{cp['inbound_id']}</code>\n"
        f"📤 تحویل: {_DM.get(cp['delivery_mode'], cp['delivery_mode'])}\n"
        f"📄 کانفیگ نمونه: <code>{esc(cp['sample_config'][:60]) if cp['sample_config'] else '—'}</code>\n"
        f"🔗 ساب نمونه: <code>{esc(cp['sample_sub_url'][:60]) if cp['sample_sub_url'] else '—'}</code>\n"
        f"🏷 نام نمونه در فرگمنت: <code>{esc(scn) if scn else '— (تنظیم نشده)'}</code>\n\n"
        "فیلد مورد نظر را برای ویرایش انتخاب کنید:"
    )
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"🔢 ویرایش ID اینباند (فعلی: {cp['inbound_id']})",
        callback_data=f"adm:pnl:cpkg:ef:inbound_id:{cpkg_id}"
    ))
    kb.add(InlineKeyboardButton(
        "📄 ویرایش کانفیگ نمونه",
        callback_data=f"adm:pnl:cpkg:ef:sample_config:{cpkg_id}"
    ))
    kb.add(InlineKeyboardButton(
        "🔗 ویرایش لینک ساب نمونه",
        callback_data=f"adm:pnl:cpkg:ef:sample_sub_url:{cpkg_id}"
    ))
    kb.add(InlineKeyboardButton(
        "🏷 ویرایش نام نمونه در فرگمنت",
        callback_data=f"adm:pnl:cpkg:ef:sample_client_name:{cpkg_id}"
    ))
    kb.add(InlineKeyboardButton("بازگشت", callback_data=f"adm:pnl:cpkgs:{cp['panel_id']}",
                                icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)


def _show_panel_client_package_preview(call, cpkg_id):
    """Show sample config/sub of a client package to admin."""
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    cp = get_panel_client_package(cpkg_id)
    if not cp:
        send_or_edit(call, "⚠️ کلاینت پکیج یافت نشد.", None)
        return
    _DM = {"config_only": "📄 فقط کانفیگ", "sub_only": "🔗 فقط ساب", "both": "📄+🔗 هر دو"}
    dm_label = _DM.get(cp["delivery_mode"], cp["delivery_mode"])
    parts = [
        f"📦 <b>کلاینت پکیج #{cp['id']}</b>",
        f"🔹 نام: <b>{esc(cp['name'] or '—')}</b>",
        f"🔌 اینباند ID: <code>{cp['inbound_id']}</code>",
        f"📤 تحویل: {dm_label}",
    ]
    if cp["sample_config"]:
        parts.append(f"\n📄 <b>نمونه کانفیگ:</b>\n<code>{esc(cp['sample_config'])}</code>")
    if cp["sample_sub_url"]:
        parts.append(f"\n🔗 <b>نمونه ساب:</b>\n<code>{esc(cp['sample_sub_url'])}</code>")
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("بازگشت", callback_data=f"adm:pnl:cpkgs:{cp['panel_id']}",
                                icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, "\n".join(parts), kb)





# ── Panel Configs (purchased, auto-created) ────────────────────────────────────

def _is_expiring_time(item):
    """Return True if the config is close to expiry (time-based, < 20% remaining)."""
    from datetime import datetime
    if not item["expire_at"] or not item["duration_days"]:
        return False
    try:
        expire_dt = datetime.strptime(str(item["expire_at"])[:19], "%Y-%m-%d %H:%M:%S")
        remaining = (expire_dt - datetime.utcnow()).total_seconds()
        if remaining <= 0:
            return True
        total = (item["duration_days"] or 0) * 86400
        if total <= 0:
            return False
        return (remaining / total) < 0.2
    except Exception:
        return False


def _show_panel_configs(call, page=0, search=None, only_expired=False,
                        filter_type=None, package_id=None):
    """
    Main panel-configs landing menu: search + 3 filter buttons with counts
    + package list.  When filter_type/search is provided, delegates to list.
    """
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

    # Delegate to list view when an explicit filter is requested
    if filter_type or search or only_expired:
        ft = filter_type or ("expired" if only_expired else "all")
        _show_panel_config_list(call, filter_type=ft, package_id=package_id,
                                page=page, search=search)
        return

    cnt_all      = get_panel_configs_count(filter_type="all")
    cnt_expiring = get_panel_configs_count(filter_type="expiring")
    cnt_expired  = get_panel_configs_count(filter_type="expired")

    text = "🔌 <b>کانفیگ های پنل</b>"

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("جستجو 🔎", callback_data="admin:pcfg:search"))
    kb.row(
        InlineKeyboardButton(f"📋 همه ({cnt_all})",           callback_data="admin:pcfg:fl:all:0"),
        InlineKeyboardButton(f"⚠️ رو به پایان ({cnt_expiring})", callback_data="admin:pcfg:fl:expiring:0"),
        InlineKeyboardButton(f"❌ منقضی ({cnt_expired})",       callback_data="admin:pcfg:fl:expired:0"),
    )

    # Package list (only packages that have at least one panel config)
    all_pkgs = get_packages(include_inactive=True) or []
    pkgs_used = [p for p in all_pkgs
                 if get_panel_configs_count(filter_type="all", package_id=p["id"]) > 0]
    if pkgs_used:
        kb.add(InlineKeyboardButton("─── پکیج ها ───", callback_data="admin:pcfg:noop"))
        for p in pkgs_used:
            pc_cnt = get_panel_configs_count(filter_type="all", package_id=p["id"])
            kb.add(InlineKeyboardButton(
                f"📦 {esc(p['name'])} ({pc_cnt})",
                callback_data=f"admin:pcfg:pkg:{p['id']}"
            ))

    kb.add(InlineKeyboardButton("بازگشت", callback_data="admin:panel",
                                icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)


def _show_panel_config_list(call, filter_type="all", package_id=None,
                            page=0, search=None):
    """
    Paginated list of panel configs for the given filter / package.
    Each item is a clickable button opening the config detail.
    """
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

    PER_PAGE = 10
    items = get_panel_configs(
        search=search, filter_type=filter_type,
        package_id=package_id, page=page, per_page=PER_PAGE
    )
    total = get_panel_configs_count(
        search=search, filter_type=filter_type, package_id=package_id
    )
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    _FILTER_LABELS = {
        "all":      "تمامی کانفیگ ها",
        "expiring": "کانفیگ های رو به پایان",
        "expired":  "کانفیگ های به اتمام رسیده",
    }

    lines = [f"🔌 <b>{_FILTER_LABELS.get(filter_type, filter_type)}</b>"]
    if search:
        lines.append(f"🔍 {esc(search)}")
    lines.append(f"تعداد: <b>{total}</b>")
    if not items:
        lines.append("\n<i>موردی یافت نشد.</i>")

    text = "\n".join(lines)

    back_cb = f"admin:pcfg:pkg:{package_id}" if package_id else "admin:panel_configs"

    def _pg_cb(p):
        if package_id:
            return f"admin:pcfg:fl:{filter_type}:{p}:{package_id}"
        return f"admin:pcfg:fl:{filter_type}:{p}"

    kb = InlineKeyboardMarkup()
    for item in items:
        if item["is_expired"]:
            marker = "⌛"
        elif _is_expiring_time(item):
            marker = "🟡"
        else:
            marker = "🟢"
        pkg_name    = (item["package_name"] or f"#{item['package_id']}")[:20]
        client_name = (item["client_name"] or "—")[:30]
        btn_text    = f"{marker} {client_name} | {pkg_name}"
        kb.add(InlineKeyboardButton(btn_text, callback_data=f"admin:pcfg:d:{item['id']}"))

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("صفحه قبل", callback_data=_pg_cb(page - 1)))
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="admin:pcfg:noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("صفحه بعد", callback_data=_pg_cb(page + 1)))
        kb.row(*nav)

    kb.add(InlineKeyboardButton("بازگشت", callback_data=back_cb,
                                icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)


def _show_panel_config_pkg(call, package_id):
    """Package submenu: 3 filter buttons scoped to one package."""
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    from ..db import get_package as _gp

    p = _gp(package_id)
    pkg_name = esc(p["name"]) if p else f"#{package_id}"

    cnt_all      = get_panel_configs_count(filter_type="all",      package_id=package_id)
    cnt_expiring = get_panel_configs_count(filter_type="expiring", package_id=package_id)
    cnt_expired  = get_panel_configs_count(filter_type="expired",  package_id=package_id)

    text = f"🔌 <b>کانفیگ های پنل</b>\n📦 پکیج: {pkg_name}"

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"تمامی کانفیگ ها ({cnt_all})",
        callback_data=f"admin:pcfg:fl:all:0:{package_id}"
    ))
    kb.add(InlineKeyboardButton(
        f"کانفیگ های رو به پایان ({cnt_expiring})",
        callback_data=f"admin:pcfg:fl:expiring:0:{package_id}"
    ))
    kb.add(InlineKeyboardButton(
        f"کانفیگ های به اتمام رسیده ({cnt_expired})",
        callback_data=f"admin:pcfg:fl:expired:0:{package_id}"
    ))
    kb.add(InlineKeyboardButton("بازگشت", callback_data="admin:panel_configs",
                                icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)


def _show_panel_config_detail(call, config_id, back_data="admin:panel_configs",
                              is_user_view=False):
    """
    Full detail view for one panel config.
    Shows static DB data + best-effort live traffic from panel API.
    """
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    from datetime import datetime
    from ..ui.premium_emoji import ce

    cfg = get_panel_config_full(config_id)
    if not cfg:
        try:
            bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True)
        except Exception:
            pass
        return
    cfg = dict(cfg)

    # ── Remaining time from DB expire_at ─────────────────────────────────────
    remaining_time_str = "نامحدود"
    if cfg.get("expire_at"):
        try:
            expire_dt = datetime.strptime(str(cfg["expire_at"])[:19], "%Y-%m-%d %H:%M:%S")
            rem = (expire_dt - datetime.utcnow()).total_seconds()
            if rem <= 0:
                remaining_time_str = "منقضی شده ⌛"
            else:
                d = int(rem // 86400)
                h = int((rem % 86400) // 3600)
                remaining_time_str = f"{d} روز و {h} ساعت مانده"
        except Exception:
            remaining_time_str = str(cfg["expire_at"])[:10]

    # ── Try live traffic from panel API ──────────────────────────────────────
    remaining_vol_str   = "—"
    client_enabled_live = None
    try:
        panel = get_panel(cfg["panel_id"])
        if panel:
            from ..panels.client import PanelClient
            pc_api = PanelClient(
                protocol=panel["protocol"], host=panel["host"], port=panel["port"],
                path=panel["path"] or "", username=panel["username"], password=panel["password"]
            )
            ok, td = pc_api.get_client_traffics(cfg.get("client_name") or "")
            if ok and td:
                total_b = td.get("total", 0) or 0
                used_b  = (td.get("up", 0) or 0) + (td.get("down", 0) or 0)
                client_enabled_live = td.get("enable", True)
                if total_b == 0:
                    remaining_vol_str = "نامحدود"
                else:
                    rem_gb = max(0, total_b - used_b) / (1024 ** 3)
                    remaining_vol_str = f"{rem_gb:.2f} GB مانده"
                exp_ms = td.get("expiryTime", 0) or 0
                if exp_ms > 0 and remaining_time_str == "نامحدود":
                    import time as _time
                    rem_s = exp_ms / 1000 - _time.time()
                    if rem_s <= 0:
                        remaining_time_str = "منقضی شده ⌛"
                    else:
                        d = int(rem_s // 86400)
                        h = int((rem_s % 86400) // 3600)
                        remaining_time_str = f"{d} روز و {h} ساعت مانده"
    except Exception:
        pass

    # ── Static package info ───────────────────────────────────────────────────
    vol_text = "نامحدود" if not cfg.get("volume_gb")    else f"{cfg['volume_gb']} گیگ"
    dur_text = "نامحدود" if not cfg.get("duration_days") else f"{cfg['duration_days']} روز"

    cpkg_delivery = "—"
    if cfg.get("cpkg_id"):
        cp = get_panel_client_package(cfg["cpkg_id"])
        if cp:
            dm = dict(cp).get("delivery_mode", "both")
            mode_map = {"config_only": "کانفیگ", "sub_only": "ساب", "both": "کانفیگ + ساب"}
            cpkg_delivery = mode_map.get(dm, dm)

    purchase_time = str(cfg.get("created_at") or "—")[:19]
    auto_renew    = int(cfg.get("auto_renew")  or 0)
    is_disabled   = int(cfg.get("is_disabled") or 0)
    is_active     = (not is_disabled) if client_enabled_live is None else bool(client_enabled_live)

    has_config = bool(cfg.get("client_config_text"))
    has_sub    = bool(cfg.get("client_sub_url"))

    # ── Build config/sub lines ────────────────────────────────────────────────
    config_line = ""
    if has_config:
        cfg_txt = str(cfg["client_config_text"])[:800]
        config_line += f"\n\n{ce('💝', '5900197669178970457')} <b>Config:</b>\n<code>{esc(cfg_txt)}</code>"
    if has_sub:
        config_line += f"\n\n{ce('🔗', '5271604874419647061')} <b>لینک ساب:</b>\n{esc(cfg['client_sub_url'])}"

    # ── Usage stats block ─────────────────────────────────────────────────────
    usage_block = (
        f"\n\n━━━━━━━━━━━━━\n"
        f"📊 <b>وضعیت مصرف:</b>\n"
        f"حجم مانده: {remaining_vol_str}\n"
        f"زمان مانده: {remaining_time_str}"
    )

    if is_user_view:
        text = (
            f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(cfg.get('client_name') or '—')}</b>\n"
            f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(cfg.get('type_name') or '—')}</b>\n"
            f"{ce('🔋', '5924538142198600679')} حجم: <b>{vol_text}</b>\n"
            f"{ce('⏰', '5343724178547691280')} مدت: <b>{dur_text}</b>\n"
            f"{ce('👥', '5372926953978341366')} تعداد کاربر: <b>نامحدود</b>"
            f"{config_line}"
            f"{usage_block}"
        )
    else:
        user_block = ""
        buyer_name     = esc(str(cfg.get("full_name") or "—"))
        buyer_username = esc(str(cfg.get("username")  or "—"))
        buyer_id       = cfg.get("user_id", "—")
        user_block = (
            f"\n\n🛒 <b>خریدار:</b>\n"
            f"نام: {buyer_name}\n"
            f"نام کاربری: @{buyer_username}\n"
            f"آیدی: <code>{buyer_id}</code>\n"
            f"زمان خرید: <code>{purchase_time}</code>"
        )
        text = (
            f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(cfg.get('client_name') or '—')}</b>\n"
            f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(cfg.get('type_name') or '—')}</b>\n"
            f"{ce('🔋', '5924538142198600679')} حجم: <b>{vol_text}</b>\n"
            f"{ce('⏰', '5343724178547691280')} مدت: <b>{dur_text}</b>"
            f"{config_line}"
            f"{user_block}"
            f"{usage_block}"
        )

    kb = InlineKeyboardMarkup()

    if not is_user_view:
        kb.row(
            InlineKeyboardButton("🔄 بازسازی لینک ساب",  callback_data=f"admin:pcfg:rsub:{config_id}"),
            InlineKeyboardButton("🔄 بازسازی کانفیگ",     callback_data=f"admin:pcfg:ruuid:{config_id}"),
        )
        ar_label = "♻️ تمدید خودکار: ✅" if auto_renew else "♻️ تمدید خودکار: ❌"
        kb.row(
            InlineKeyboardButton(ar_label,              callback_data=f"admin:pcfg:autorenew:{config_id}"),
            InlineKeyboardButton("⚡ تمدید فوری",        callback_data=f"admin:pcfg:renew:{config_id}"),
        )
        toggle_label = "✅ فعال‌سازی کانفیگ" if not is_active else "⛔ غیرفعال موقت"
        kb.row(
            InlineKeyboardButton(toggle_label,           callback_data=f"admin:pcfg:toggle:{config_id}"),
            InlineKeyboardButton("🗑 حذف کانفیگ",        callback_data=f"admin:pcfg:del:{config_id}"),
        )
        kb.add(InlineKeyboardButton("بازگشت", callback_data=back_data,
                                    icon_custom_emoji_id="5253997076169115797"))
        # Send with QR photo attached
        qr_source = cfg.get("client_config_text") or ""
        if not qr_source and has_sub:
            qr_source = cfg.get("client_sub_url") or ""
        if qr_source:
            try:
                import qrcode as _qr
                import io as _io
                bio = _io.BytesIO()
                _qr.make(qr_source).save(bio, format="PNG")
                bio.seek(0)
                bio.name = "qr.png"
                chat_id = call.message.chat.id if hasattr(call, "message") else call.chat.id
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
                except Exception:
                    pass
                bot.send_photo(chat_id, bio, caption=text, parse_mode="HTML", reply_markup=kb)
                return
            except Exception:
                pass
        send_or_edit(call, text, kb)
    else:
        # User view: send QR inline if possible, then show buttons
        ar_label = "♻️ تمدید خودکار: ✅" if auto_renew else "♻️ تمدید خودکار: ❌"
        kb.row(
            InlineKeyboardButton("⚡ تمدید فوری",  callback_data=f"mypnlcfg:renewwarn:{config_id}"),
            InlineKeyboardButton(ar_label,          callback_data=f"mypnlcfg:autorenew:{config_id}"),
        )
        # ── Add-on purchase buttons (only for panel-created configs) ──────
        _vol_en  = setting_get("addon_volume_enabled", "1") == "1"
        _time_en = setting_get("addon_time_enabled",   "1") == "1"
        _addon_row = []
        if _vol_en:
            _addon_row.append(InlineKeyboardButton("📦 خرید حجم",  callback_data=f"addon:vol:{config_id}"))
        if _time_en:
            _addon_row.append(InlineKeyboardButton("⏰ خرید زمان", callback_data=f"addon:time:{config_id}"))
        if _addon_row:
            kb.row(*_addon_row)
        kb.add(InlineKeyboardButton("بازگشت", callback_data=back_data,
                                    icon_custom_emoji_id="5253997076169115797"))

        # Determine QR source
        qr_source = cfg.get("client_config_text") or cfg.get("client_sub_url") or ""
        if has_sub and not has_config:
            qr_source = cfg["client_sub_url"]

        if qr_source:
            try:
                import qrcode as _qr
                import io as _io
                bio = _io.BytesIO()
                _qr.make(qr_source).save(bio, format="PNG")
                bio.seek(0)
                bio.name = "qr.png"
                chat_id = call.message.chat.id if hasattr(call, "message") else call.chat.id
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
                except Exception:
                    pass
                bot.send_photo(chat_id, bio, caption=text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                send_or_edit(call, text, kb)
        else:
            send_or_edit(call, text, kb)

