# -*- coding: utf-8 -*-
"""
Admin Analytics Dashboard
Provides comprehensive sales & user statistics with Persian Jalali dates.
"""
from datetime import datetime, timezone, timedelta
from telebot import types

import jdatetime

from ..bot_instance import bot
from ..db import get_conn, setting_get
from ..helpers import esc, fmt_price, is_admin, admin_has_perm, _TZ_TEHRAN
from ..ui.helpers import send_or_edit

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_BACK_ICON = "5253997076169115797"


def _back_btn(cb):
    return types.InlineKeyboardButton(
        "بازگشت", callback_data=cb, icon_custom_emoji_id=_BACK_ICON
    )


def _pct(num, denom):
    if not denom:
        return "۰٪"
    p = round(num * 100 / denom, 1)
    return f"{p}٪"


def _fmt(n):
    """Format integer with thousand separators."""
    return f"{int(n):,}" if n else "۰"


# ─────────────────────────────────────────────────────────────────────────────
# Tehran / Jalali date utilities
# ─────────────────────────────────────────────────────────────────────────────

def _now_tehran() -> datetime:
    return datetime.now(_TZ_TEHRAN)


def _jdate_to_gregorian_range(jdate_str: str):
    """
    Convert a Jalali date string (YYYY-MM-DD) to a gregorian datetime
    range [start, end) in UTC stored as Jalali strings matching DB format.
    Returns (start_str, end_str) where strings look like '1404-01-01 00:00:00'.
    """
    try:
        y, m, d = (int(x) for x in jdate_str.split("-"))
        jdt_start = jdatetime.datetime(y, m, d, 0, 0, 0)
        jdt_end   = jdatetime.datetime(y, m, d, 23, 59, 59)
        return jdt_start.strftime("%Y-%m-%d %H:%M:%S"), jdt_end.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None, None


def _period_bounds(period: str, custom_start=None, custom_end=None):
    """
    Returns (start_str, end_str) in Jalali ISO format for DB queries.
    period: 'all' | 'today' | 'yesterday' | 'week' | 'month' | 'year' | 'custom'
    For 'custom': custom_start and custom_end are Jalali date strings 'YYYY-MM-DD'.
    All times are in Tehran timezone.
    Returns (None, None) for 'all'.
    """
    now = _now_tehran()
    jnow = jdatetime.datetime.fromgregorian(datetime=now)

    if period == "all":
        return None, None

    if period == "today":
        start = jdatetime.datetime(jnow.year, jnow.month, jnow.day, 0, 0, 0)
        end   = jdatetime.datetime(jnow.year, jnow.month, jnow.day, 23, 59, 59)

    elif period == "yesterday":
        yesterday = now - timedelta(days=1)
        jy = jdatetime.datetime.fromgregorian(datetime=yesterday)
        start = jdatetime.datetime(jy.year, jy.month, jy.day, 0, 0, 0)
        end   = jdatetime.datetime(jy.year, jy.month, jy.day, 23, 59, 59)

    elif period == "week":
        # Jalali week starts Saturday; use last 7 days for simplicity
        seven_ago = now - timedelta(days=6)
        js = jdatetime.datetime.fromgregorian(datetime=seven_ago)
        start = jdatetime.datetime(js.year, js.month, js.day, 0, 0, 0)
        end   = jdatetime.datetime(jnow.year, jnow.month, jnow.day, 23, 59, 59)

    elif period == "month":
        start = jdatetime.datetime(jnow.year, jnow.month, 1, 0, 0, 0)
        # last day of Jalali month
        try:
            last_day = jdatetime.JalaliDate(jnow.year, jnow.month, 1).daysinmonth
        except Exception:
            last_day = 30
        end = jdatetime.datetime(jnow.year, jnow.month, last_day, 23, 59, 59)

    elif period == "year":
        start = jdatetime.datetime(jnow.year, 1, 1, 0, 0, 0)
        end   = jdatetime.datetime(jnow.year, 12, 29, 23, 59, 59)

    elif period == "custom" and custom_start and custom_end:
        s0, _ = _jdate_to_gregorian_range(custom_start)
        _, e1 = _jdate_to_gregorian_range(custom_end)
        if s0 and e1:
            return s0, e1
        return None, None

    elif period == "custom_day" and custom_start:
        return _jdate_to_gregorian_range(custom_start)

    else:
        return None, None

    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def _period_label(period, custom_start=None, custom_end=None):
    labels = {
        "all":       "کل",
        "today":     "امروز",
        "yesterday": "دیروز",
        "week":      "این هفته",
        "month":     "این ماه",
        "year":      "امسال",
        "custom_day": f"تاریخ {custom_start or ''}",
        "custom":    f"از {custom_start or ''} تا {custom_end or ''}",
    }
    return labels.get(period, period)


# ─────────────────────────────────────────────────────────────────────────────
# DB Aggregation Queries
# ─────────────────────────────────────────────────────────────────────────────

def _date_filter(alias, start, end):
    """Return SQL fragment and params for created_at filtering."""
    if start and end:
        return f" AND {alias}.created_at >= ? AND {alias}.created_at <= ?", [start, end]
    return "", []


def _stats_global():
    """Overall bot stats (all time, no date filter)."""
    with get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

        buyers = conn.execute(
            """SELECT COUNT(DISTINCT uid) AS n FROM (
                SELECT user_id AS uid FROM purchases
                UNION
                SELECT user_id AS uid FROM panel_configs
            )"""
        ).fetchone()["n"]

        total_balance = conn.execute(
            "SELECT COALESCE(SUM(balance),0) AS n FROM users"
        ).fetchone()["n"]

        total_agents = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE is_agent=1"
        ).fetchone()["n"]

    return {
        "total_users": total_users,
        "buyers": buyers,
        "total_balance": total_balance,
        "total_agents": total_agents,
    }


def _stats_financial(start=None, end=None, agents_only=False):
    """
    Financial aggregation.
    Returns dict with: sales_count, sales_total, renewal_count, renewal_total,
                       avg_per_buyer, conversion_rate, renewal_pct
    """
    df, dp = _date_filter("p", start, end)
    agent_join = ""
    agent_where = ""
    if agents_only:
        agent_join  = " INNER JOIN users u ON u.user_id=p.user_id"
        agent_where = " AND u.is_agent=1"

    with get_conn() as conn:
        # Purchases (manual stock)
        row_pur = conn.execute(
            f"""SELECT COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS total
                FROM purchases p {agent_join}
                WHERE 1=1{df.replace('p.created_at','p.created_at')}{agent_where}""",
            dp
        ).fetchone()
        sales_count_pur  = row_pur["cnt"]
        sales_total_pur  = row_pur["total"]

        # Panel config purchases (payments with kind='config_purchase')
        row_pnl = conn.execute(
            f"""SELECT COUNT(*) AS cnt, COALESCE(SUM(p.amount),0) AS total
                FROM payments p {agent_join}
                WHERE p.kind='config_purchase' AND p.status='completed'{df}{agent_where}""",
            dp
        ).fetchone()
        sales_count_pnl = row_pnl["cnt"]
        sales_total_pnl = row_pnl["total"]

        sales_count = sales_count_pur + sales_count_pnl
        sales_total = sales_total_pur + sales_total_pnl

        # Renewals
        row_ren = conn.execute(
            f"""SELECT COUNT(*) AS cnt, COALESCE(SUM(p.amount),0) AS total
                FROM payments p {agent_join}
                WHERE p.kind IN ('renewal','pnlcfg_renewal') AND p.status='completed'{df}{agent_where}""",
            dp
        ).fetchone()
        renewal_count = row_ren["cnt"]
        renewal_total = row_ren["total"]

        # Buyers in period
        if start and end:
            buyers_in_period = conn.execute(
                f"""SELECT COUNT(DISTINCT uid) AS n FROM (
                    SELECT p.user_id AS uid FROM purchases p {agent_join}
                    WHERE 1=1{df.replace('p.created_at','p.created_at')}{agent_where}
                    UNION
                    SELECT p.user_id AS uid FROM payments p {agent_join}
                    WHERE p.kind='config_purchase' AND p.status='completed'{df}{agent_where}
                )""", dp + dp
            ).fetchone()["n"]
        else:
            if agents_only:
                buyers_in_period = conn.execute(
                    """SELECT COUNT(DISTINCT uid) AS n FROM (
                        SELECT p.user_id AS uid FROM purchases p
                        INNER JOIN users u ON u.user_id=p.user_id WHERE u.is_agent=1
                        UNION
                        SELECT p.user_id AS uid FROM panel_configs p
                        INNER JOIN users u ON u.user_id=p.user_id WHERE u.is_agent=1
                    )"""
                ).fetchone()["n"]
            else:
                buyers_in_period = conn.execute(
                    """SELECT COUNT(DISTINCT uid) AS n FROM (
                        SELECT user_id AS uid FROM purchases
                        UNION
                        SELECT user_id AS uid FROM panel_configs
                    )"""
                ).fetchone()["n"]

        total_users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] if not agents_only else \
                      conn.execute("SELECT COUNT(*) AS n FROM users WHERE is_agent=1").fetchone()["n"]

    avg_per_buyer = (sales_total + renewal_total) // buyers_in_period if buyers_in_period else 0
    conversion    = buyers_in_period / total_users if total_users else 0
    renewal_pct   = renewal_total / (sales_total + renewal_total) if (sales_total + renewal_total) else 0

    return {
        "sales_count":    sales_count,
        "sales_total":    sales_total,
        "renewal_count":  renewal_count,
        "renewal_total":  renewal_total,
        "buyers":         buyers_in_period,
        "avg_per_buyer":  avg_per_buyer,
        "conversion_pct": f"{round(conversion*100, 1)}٪",
        "renewal_pct":    f"{round(renewal_pct*100, 1)}٪",
    }


def _stats_panel_services(start=None, end=None, page=0, per_page=10, sale_type="sale"):
    """
    Return paginated panel config rows.
    sale_type: 'sale' (config_purchase payments) | 'renewal' (pnlcfg_renewal payments)
    Returns (rows, total_count)
    """
    df, dp = _date_filter("pc", start, end)
    if sale_type == "sale":
        kind_filter = "AND py.kind='config_purchase'"
    else:
        kind_filter = "AND py.kind='pnlcfg_renewal'"

    with get_conn() as conn:
        total = conn.execute(
            f"""SELECT COUNT(*) AS n FROM panel_configs pc
                LEFT JOIN payments py ON py.id=pc.payment_id
                WHERE py.status='completed' {kind_filter}{df}""",
            dp
        ).fetchone()["n"]

        rows = conn.execute(
            f"""SELECT pc.id, pc.client_name, pc.created_at, pc.user_id,
                       py.amount, py.payment_method,
                       pk.name AS pkg_name, pk.volume_gb, pk.duration_days,
                       ct.name AS type_name,
                       u.full_name, u.username
                FROM panel_configs pc
                LEFT JOIN payments py ON py.id=pc.payment_id
                LEFT JOIN packages pk ON pk.id=pc.package_id
                LEFT JOIN config_types ct ON ct.id=pk.type_id
                LEFT JOIN users u ON u.user_id=pc.user_id
                WHERE py.status='completed' {kind_filter}{df}
                ORDER BY pc.id DESC
                LIMIT ? OFFSET ?""",
            dp + [per_page, page * per_page]
        ).fetchall()

    return rows, total


def _stats_manual_services(start=None, end=None, page=0, per_page=10):
    """Return paginated manual purchase rows. Returns (rows, total_count)."""
    df, dp = _date_filter("p", start, end)
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM purchases p WHERE 1=1{df}", dp
        ).fetchone()["n"]

        rows = conn.execute(
            f"""SELECT p.id, p.created_at, p.amount, p.payment_method, p.user_id,
                       pk.name AS pkg_name, pk.volume_gb, pk.duration_days,
                       ct.name AS type_name,
                       c.service_name,
                       u.full_name, u.username
                FROM purchases p
                LEFT JOIN packages pk ON pk.id=p.package_id
                LEFT JOIN configs c ON c.id=p.config_id
                LEFT JOIN config_types ct ON ct.id=pk.type_id
                LEFT JOIN users u ON u.user_id=p.user_id
                WHERE 1=1{df}
                ORDER BY p.id DESC
                LIMIT ? OFFSET ?""",
            dp + [per_page, page * per_page]
        ).fetchall()
    return rows, total


# ─────────────────────────────────────────────────────────────────────────────
# Keyboard builders
# ─────────────────────────────────────────────────────────────────────────────

def _time_filter_kb(selected=None):
    """Time filter row keyboard."""
    kb = types.InlineKeyboardMarkup(row_width=3)
    periods = [
        ("آمار کل",         "all"),
        ("امروز",           "today"),
        ("دیروز",           "yesterday"),
        ("این هفته",        "week"),
        ("این ماه",         "month"),
        ("امسال",           "year"),
        ("📅 تاریخ خاص",    "prompt_day"),
        ("📆 بازه خاص",      "prompt_range"),
    ]
    btns = []
    for label, key in periods:
        mark = " ✅" if key == selected else ""
        btns.append(types.InlineKeyboardButton(
            f"{label}{mark}", callback_data=f"stats:period:{key}"
        ))
    # 3 per row
    for i in range(0, len(btns), 3):
        kb.row(*btns[i:i+3])
    kb.add(_back_btn("admin:panel"))
    return kb


def _report_type_kb(period, custom_start=None, custom_end=None):
    """After period selected: choose financial or services report."""
    cs = custom_start or ""
    ce = custom_end   or ""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton(
            "💰 آمار مالی",
            callback_data=f"stats:fin:{period}:{cs}:{ce}"
        ),
        types.InlineKeyboardButton(
            "📦 آمار سرویس‌ها",
            callback_data=f"stats:svc:{period}:{cs}:{ce}"
        ),
    )
    kb.add(types.InlineKeyboardButton(
        "🔄 تغییر بازه",
        callback_data="stats:period:all"
    ))
    kb.add(_back_btn("admin:panel"))
    return kb


def _service_type_kb(period, cs, ce):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton(
            "🖥 سرویس‌های پنل",
            callback_data=f"stats:svc:panel:{period}:{cs}:{ce}:sale:0"
        ),
        types.InlineKeyboardButton(
            "📁 سرویس‌های دستی",
            callback_data=f"stats:svc:manual:{period}:{cs}:{ce}:0"
        ),
    )
    kb.add(types.InlineKeyboardButton(
        "بازگشت",
        callback_data=f"stats:svc:{period}:{cs}:{ce}",
        icon_custom_emoji_id=_BACK_ICON
    ))
    return kb


def _panel_sale_type_kb(period, cs, ce):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton(
            "🛒 فروش",
            callback_data=f"stats:svc:panel:{period}:{cs}:{ce}:sale:0"
        ),
        types.InlineKeyboardButton(
            "🔄 تمدید",
            callback_data=f"stats:svc:panel:{period}:{cs}:{ce}:renewal:0"
        ),
    )
    kb.add(types.InlineKeyboardButton(
        "بازگشت",
        callback_data=f"stats:svc:{period}:{cs}:{ce}",
        icon_custom_emoji_id=_BACK_ICON
    ))
    return kb


# ─────────────────────────────────────────────────────────────────────────────
# Screen builders
# ─────────────────────────────────────────────────────────────────────────────

def show_stats_main(call):
    """Main stats overview — always all-time."""
    g  = _stats_global()
    fa = _stats_financial()          # all users
    ag = _stats_financial(agents_only=True)  # agents only

    text = (
        "📊 <b>آمار کلی ربات</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 تعداد کل کاربران: <b>{_fmt(g['total_users'])}</b> نفر\n"
        f"💳 کاربران دارای خرید: <b>{_fmt(g['buyers'])}</b> نفر\n"
        f"💰 موجودی مانده کل کاربران: <b>{fmt_price(g['total_balance'])}</b> تومان\n"
        "\n"
        f"🧾 تعداد کل فروش: <b>{_fmt(fa['sales_count'])}</b> عدد\n"
        f"💵 جمع کل فروش: <b>{fmt_price(fa['sales_total'])}</b> تومان\n"
        f"🔄 جمع کل تمدید: <b>{fmt_price(fa['renewal_total'])}</b> تومان\n"
        f"📈 نرخ تبدیل به مشتری: <b>{fa['conversion_pct']}</b>\n"
        f"💳 میانگین خرید هر مشتری: <b>{fmt_price(fa['avg_per_buyer'])}</b> تومان\n"
        f"📊 درصد تمدید از فروش: <b>{fa['renewal_pct']}</b>\n"
        "\n"
        f"👨‍💼 تعداد کل نمایندگان: <b>{_fmt(g['total_agents'])}</b> نفر\n"
        f"🧾 تعداد کل فروش نمایندگان: <b>{_fmt(ag['sales_count'])}</b> عدد\n"
        f"💵 جمع کل فروش نمایندگان: <b>{fmt_price(ag['sales_total'])}</b> تومان\n"
        f"🔄 جمع کل تمدید نمایندگان: <b>{fmt_price(ag['renewal_total'])}</b> تومان\n"
        "\n"
        "⬇️ بازه زمانی مورد نظر را انتخاب کنید:"
    )
    kb = _time_filter_kb()
    bot.answer_callback_query(call.id)
    send_or_edit(call, text, kb)


def show_stats_after_period(call, period, custom_start=None, custom_end=None):
    """Show period label and report-type buttons."""
    label = _period_label(period, custom_start, custom_end)
    text = (
        f"📊 <b>آمار — {label}</b>\n\n"
        "نوع گزارش را انتخاب کنید:"
    )
    kb = _report_type_kb(period, custom_start, custom_end)
    bot.answer_callback_query(call.id)
    send_or_edit(call, text, kb)


def show_financial_report(call, period, custom_start=None, custom_end=None):
    """Financial report for a period — all users and agents."""
    start, end = _period_bounds(period, custom_start, custom_end)
    label = _period_label(period, custom_start, custom_end)
    fa = _stats_financial(start, end)
    ag = _stats_financial(start, end, agents_only=True)

    text = (
        f"💰 <b>گزارش مالی — {label}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>🌐 همه کاربران</b>\n"
        f"🧾 تعداد کل فروش: <b>{_fmt(fa['sales_count'])}</b> عدد\n"
        f"💵 جمع کل فروش: <b>{fmt_price(fa['sales_total'])}</b> تومان\n"
        f"🔄 تعداد تمدید: <b>{_fmt(fa['renewal_count'])}</b> عدد\n"
        f"🔄 جمع کل تمدید: <b>{fmt_price(fa['renewal_total'])}</b> تومان\n"
        f"📈 نرخ تبدیل به مشتری: <b>{fa['conversion_pct']}</b>\n"
        f"💳 میانگین خرید هر مشتری: <b>{fmt_price(fa['avg_per_buyer'])}</b> تومان\n"
        f"📊 درصد تمدید از فروش: <b>{fa['renewal_pct']}</b>\n"
        "\n"
        "<b>👨‍💼 نمایندگان</b>\n"
        f"🧾 تعداد کل فروش نمایندگان: <b>{_fmt(ag['sales_count'])}</b> عدد\n"
        f"💵 جمع کل فروش نمایندگان: <b>{fmt_price(ag['sales_total'])}</b> تومان\n"
        f"🔄 تعداد تمدید نمایندگان: <b>{_fmt(ag['renewal_count'])}</b> عدد\n"
        f"🔄 جمع کل تمدید نمایندگان: <b>{fmt_price(ag['renewal_total'])}</b> تومان\n"
        f"💳 میانگین خرید هر نماینده: <b>{fmt_price(ag['avg_per_buyer'])}</b> تومان\n"
    )
    cs = custom_start or ""
    ce = custom_end   or ""
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "بازگشت",
        callback_data=f"stats:svc:{period}:{cs}:{ce}",
        icon_custom_emoji_id=_BACK_ICON
    ))
    bot.answer_callback_query(call.id)
    send_or_edit(call, text, kb)


def show_services_menu(call, period, cs, ce):
    """Choose panel or manual services."""
    label = _period_label(period, cs or None, ce or None)
    text = (
        f"📦 <b>آمار سرویس‌ها — {label}</b>\n\n"
        "نوع سرویس را انتخاب کنید:"
    )
    bot.answer_callback_query(call.id)
    send_or_edit(call, text, _service_type_kb(period, cs, ce))


def show_panel_services(call, period, cs, ce, sale_type, page):
    """Paginated list of panel service records."""
    start, end = _period_bounds(period, cs or None, ce or None)
    label = _period_label(period, cs or None, ce or None)
    per_page = 10
    rows, total = _stats_panel_services(start, end, page=page, per_page=per_page, sale_type=sale_type)

    kind_label = "فروش" if sale_type == "sale" else "تمدید"
    total_pages = max(1, (total + per_page - 1) // per_page)

    if not rows:
        text = (
            f"🖥 <b>سرویس‌های پنل ({kind_label}) — {label}</b>\n\n"
            "📭 هیچ داده‌ای در این بازه موجود نیست."
        )
    else:
        lines = [f"🖥 <b>سرویس‌های پنل ({kind_label}) — {label}</b>\n"
                 f"📄 صفحه {page+1} از {total_pages} | مجموع: {_fmt(total)}\n"
                 "━━━━━━━━━━━━━━━━━━"]
        for i, r in enumerate(rows, start=page * per_page + 1):
            cname    = r["client_name"] or "—"
            pkg_name = r["pkg_name"] or "—"
            typ_name = r["type_name"] or "—"
            amount   = fmt_price(r["amount"] or 0)
            uname    = r["username"] or ""
            fname    = r["full_name"] or ""
            user_str = f"@{uname}" if uname else fname or "—"
            lines.append(
                f"{i}. <b>{esc(cname)}</b> ({esc(typ_name)} / {esc(pkg_name)})\n"
                f"   👤 {esc(user_str)} | 💰 {amount} تومان\n"
                f"   🕐 {r['created_at'][:16]}"
            )
        text = "\n".join(lines)

    kb = types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(
            "◀️ قبلی",
            callback_data=f"stats:svc:panel:{period}:{cs}:{ce}:{sale_type}:{page-1}"
        ))
    nav.append(types.InlineKeyboardButton(
        f"📄 {page+1}/{total_pages}", callback_data="stats:noop"
    ))
    if page + 1 < total_pages:
        nav.append(types.InlineKeyboardButton(
            "▶️ بعدی",
            callback_data=f"stats:svc:panel:{period}:{cs}:{ce}:{sale_type}:{page+1}"
        ))
    if nav:
        kb.row(*nav)
    # Sale type toggle
    other_type  = "renewal" if sale_type == "sale" else "sale"
    other_label = "🔄 نمایش تمدیدها" if sale_type == "sale" else "🛒 نمایش فروش‌ها"
    kb.add(types.InlineKeyboardButton(
        other_label,
        callback_data=f"stats:svc:panel:{period}:{cs}:{ce}:{other_type}:0"
    ))
    kb.add(types.InlineKeyboardButton(
        "بازگشت",
        callback_data=f"stats:svc:{period}:{cs}:{ce}",
        icon_custom_emoji_id=_BACK_ICON
    ))
    bot.answer_callback_query(call.id)
    send_or_edit(call, text, kb)


def show_manual_services(call, period, cs, ce, page):
    """Paginated list of manual purchase records."""
    start, end = _period_bounds(period, cs or None, ce or None)
    label = _period_label(period, cs or None, ce or None)
    per_page = 10
    rows, total = _stats_manual_services(start, end, page=page, per_page=per_page)

    total_pages = max(1, (total + per_page - 1) // per_page)

    if not rows:
        text = (
            f"📁 <b>سرویس‌های دستی — {label}</b>\n\n"
            "📭 هیچ داده‌ای در این بازه موجود نیست."
        )
    else:
        lines = [f"📁 <b>سرویس‌های دستی — {label}</b>\n"
                 f"📄 صفحه {page+1} از {total_pages} | مجموع: {_fmt(total)}\n"
                 "━━━━━━━━━━━━━━━━━━"]
        for i, r in enumerate(rows, start=page * per_page + 1):
            sname    = r["service_name"] or "—"
            pkg_name = r["pkg_name"] or "—"
            typ_name = r["type_name"] or "—"
            amount   = fmt_price(r["amount"] or 0)
            uname    = r["username"] or ""
            fname    = r["full_name"] or ""
            user_str = f"@{uname}" if uname else fname or "—"
            lines.append(
                f"{i}. <b>{esc(sname)}</b> ({esc(typ_name)} / {esc(pkg_name)})\n"
                f"   👤 {esc(user_str)} | 💰 {amount} تومان\n"
                f"   🕐 {r['created_at'][:16]}"
            )
        text = "\n".join(lines)

    kb = types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(
            "◀️ قبلی",
            callback_data=f"stats:svc:manual:{period}:{cs}:{ce}:{page-1}"
        ))
    nav.append(types.InlineKeyboardButton(
        f"📄 {page+1}/{total_pages}", callback_data="stats:noop"
    ))
    if page + 1 < total_pages:
        nav.append(types.InlineKeyboardButton(
            "▶️ بعدی",
            callback_data=f"stats:svc:manual:{period}:{cs}:{ce}:{page+1}"
        ))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton(
        "بازگشت",
        callback_data=f"stats:svc:{period}:{cs}:{ce}",
        icon_custom_emoji_id=_BACK_ICON
    ))
    bot.answer_callback_query(call.id)
    send_or_edit(call, text, kb)
