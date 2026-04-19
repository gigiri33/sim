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
    get_panel_configs, get_panel_configs_count,
    get_panel_client_packages, get_panel_client_package,
    get_panel,
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
    text = (
        "👤 <b>اطلاعات کاربر</b>\n\n"
        f"📱 نام: {esc(row['full_name'])}\n"
        f"🆔 نام کاربری: {esc(display_username(row['username']))}\n"
        f"🔢 آیدی: <code>{row['user_id']}</code>\n"
        f"{phone_line}"
        f"💰 موجودی: <b>{fmt_price(row['balance'])}</b> تومان\n"
        f"🛍 تعداد خرید: <b>{row['purchase_count']}</b>\n"
        f"� تعداد تمدیدها: <b>{row['renewal_count']}</b>\n"
        f"💵 مجموع خرید: <b>{fmt_price(row['total_spent'])}</b> تومان\n"
        f"💳 مجموع تمدیدها: <b>{fmt_price(row['total_renewals'])}</b> تومان\n"
        f"💰 مجموع تمامی پرداخت‌ها: <b>{fmt_price(row['total_spent'] + row['total_renewals'])}</b> تومان\n"
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
        f"� تعداد تمدیدها: <b>{row['renewal_count']}</b>\n"
        f"💵 مجموع خرید: <b>{fmt_price(row['total_spent'])}</b> تومان\n"
        f"💳 مجموع تمدیدها: <b>{fmt_price(row['total_renewals'])}</b> تومان\n"
        f"💰 مجموع تمامی پرداخت‌ها: <b>{fmt_price(row['total_spent'] + row['total_renewals'])}</b> تومان\n"
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

    uname_censored = p['username'][:2] + '***' if p['username'] else '—'
    passwd_censored = '••••••••'
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
        f"👤 نام کاربری: <code>{uname_censored}</code>\n"
        f"🔑 رمز عبور:   <code>{passwd_censored}</code>\n"
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
    text = (
        f"✏️ <b>ویرایش کلاینت پکیج #{cpkg_id}</b>\n\n"
        f"🔌 اینباند ID: <code>{cp['inbound_id']}</code>\n"
        f"📤 تحویل: {_DM.get(cp['delivery_mode'], cp['delivery_mode'])}\n"
        f"📄 کانفیگ نمونه: <code>{esc(cp['sample_config'][:60]) if cp['sample_config'] else '—'}</code>\n"
        f"🔗 ساب نمونه: <code>{esc(cp['sample_sub_url'][:60]) if cp['sample_sub_url'] else '—'}</code>\n\n"
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
def _show_panel_configs(call, page=0, search=None, only_expired=False):
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

    PER_PAGE    = 10
    items       = get_panel_configs(search=search, only_expired=only_expired, page=page, per_page=PER_PAGE)
    total_count = get_panel_configs_count(search=search, only_expired=only_expired)
    total_pages = max(1, (total_count + PER_PAGE - 1) // PER_PAGE)
    filter_str  = "expired" if only_expired else "all"

    lines = ["🔌 <b>کانفیگ های پنل</b>"]
    if search:
        lines.append(f"🔍 جستجو: <code>{esc(search)}</code>")
    lines.append(f"تعداد: <b>{total_count}</b>\n")

    if items:
        for item in items:
            expired_mark = " ⌛" if item["is_expired"] else " 🟢"
            pkg_name     = item["package_name"] or f"پکیج #{item['package_id']}"
            client_name  = item["client_name"] or "—"
            expire_line  = f"  انقضا: {item['expire_at'][:10]}" if item["expire_at"] else ""
            lines.append(
                f"👤 <code>{item['user_id']}</code> | 📦 {esc(pkg_name)}\n"
                f"  🔤 {esc(client_name)}{expire_line}{expired_mark}"
            )
    else:
        lines.append("<i>موردی یافت نشد.</i>")

    text = "\n".join(lines)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔍 جستجو", callback_data="admin:pcfg:search"))
    kb.row(
        InlineKeyboardButton(
            "✅ تمامی کانفیگ ها" if not only_expired else "همه کانفیگ ها",
            callback_data=f"admin:pcfg:f:all:0"),
        InlineKeyboardButton(
            "✅ کانفیگ های منقضی شده" if only_expired else "کانفیگ های منقضی شده",
            callback_data=f"admin:pcfg:f:expired:0"),
    )

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"admin:pcfg:pg:{page - 1}:{filter_str}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="admin:pcfg:noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"admin:pcfg:pg:{page + 1}:{filter_str}"))
        kb.row(*nav)

    kb.add(InlineKeyboardButton("بازگشت", callback_data="admin:panel",
                                icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)

