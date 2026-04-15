# -*- coding: utf-8 -*-
"""
Admin UI renderers for Iran Panel (3x-ui) management.

Provides:
  show_iran_panels_list(call)       – main list screen
  show_iran_panel_detail(call, id)  – single panel detail
  show_iran_agent_detail(call, id)  – single agent detail
  show_iran_panel_logs(call, id)    – recent status logs
  show_create_token_result(call, token, expires)  – after token creation
"""
from __future__ import annotations

from telebot import types

from ..helpers import esc, now_str
from ..bot_instance import bot
from ..ui.helpers import send_or_edit
from ..iran_panel.db import (
    get_all_iran_panels,
    get_all_iran_agents,
    get_iran_panel,
    get_iran_agent,
    get_panel_logs,
    get_reg_tokens,
)


_STATUS_ICON = {
    "pending":      "⏳",
    "active":       "🟢",
    "failed":       "🔴",
    "disconnected": "🔌",
    "disabled":     "⛔",
    "revoked":      "🚫",
}


def _agent_icon(agent: dict) -> str:
    return _STATUS_ICON.get(agent.get("status", "pending"), "❓")


def _panel_icon(panel: dict) -> str:
    if not panel.get("is_active"):
        return "⛔"
    return _STATUS_ICON.get(panel.get("status", "pending"), "❓")


# ── Main list ──────────────────────────────────────────────────────────────────

def show_iran_panels_list(call) -> None:
    panels = get_all_iran_panels()
    tokens = get_reg_tokens(include_expired=False)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "🔑 ساخت توکن ثبت‌نام جدید",
        callback_data="adm:ip:mktoken",
    ))

    if tokens:
        kb.add(types.InlineKeyboardButton(
            f"📋 توکن‌های فعال ({len(tokens)})",
            callback_data="adm:ip:list_tokens",
        ))

    if panels:
        kb.add(types.InlineKeyboardButton("─── پنل‌های ثبت‌شده ───", callback_data="noop"))
        for p in panels:
            icon  = _panel_icon(p)
            label = f"{icon} {p['name']} | {p['host']}:{p['port']}"
            kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:ip:detail:{p['id']}"))
    else:
        pass  # shown in text

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:panel"))

    active   = sum(1 for p in panels if p.get("status") == "active")
    total    = len(panels)
    agents   = get_all_iran_agents()
    n_agents = len(agents)

    text = (
        "🖥 <b>مدیریت پنل‌های ثنایی (ایران)</b>\n\n"
        f"📡 تعداد پنل‌ها: <b>{total}</b> | فعال: <b>{active}</b>\n"
        f"🤖 تعداد Agent: <b>{n_agents}</b>\n\n"
    )
    if not panels:
        text += (
            "هیچ پنلی ثبت نشده است.\n\n"
            "برای ثبت پنل ایران:\n"
            "1. روی «ساخت توکن ثبت‌نام جدید» کلیک کنید\n"
            "2. توکن را به همراه آدرس API به سرور ایران ببرید\n"
            "3. اسکریپت install.sh را اجرا کنید"
        )
    send_or_edit(call, text, kb)


# ── Panel detail ───────────────────────────────────────────────────────────────

def show_iran_panel_detail(call, panel_id: int) -> None:
    panel = get_iran_panel(panel_id)
    if not panel:
        bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
        return

    icon       = _panel_icon(panel)
    agent_icon = _STATUS_ICON.get(panel.get("agent_status", "pending"), "❓")
    last_check = panel.get("last_check_at") or "هرگز"
    last_seen  = panel.get("last_seen_at") or "هرگز"
    agent_last = panel.get("agent_last_seen") or "هرگز"
    error_line = f"\n⚠️ خطای آخر: <code>{esc(panel['last_error'])}</code>" if panel.get("last_error") else ""

    text = (
        f"{icon} <b>{esc(panel['name'])}</b>\n\n"
        f"🌐 هاست: <code>{esc(panel['host'])}</code>:{panel['port']}\n"
        f"📄 پث: <code>/{esc(panel['panel_path'])}</code>\n"
        f"👤 کاربر: <code>{esc(panel['username'])}</code>\n"
        f"📊 وضعیت: <b>{panel['status']}</b>\n"
        f"⏰ آخرین تست: {esc(last_check)}\n"
        f"💓 آخرین heartbeat پنل: {esc(last_seen)}\n"
        f"{error_line}\n\n"
        f"{agent_icon} <b>Agent: {esc(panel['agent_name'])}</b>\n"
        f"🆔 UUID: <code>{esc(panel['agent_uuid'])}</code>\n"
        f"📡 آخرین heartbeat Agent: {esc(agent_last)}\n"
        f"وضعیت Agent: <b>{panel['agent_status']}</b>"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔄 درخواست تست مجدد", callback_data=f"adm:ip:req_test:{panel_id}"))

    toggle_lbl = "⛔ غیرفعال کردن" if panel["is_active"] else "✅ فعال کردن"
    toggle_val = 0 if panel["is_active"] else 1
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data=f"adm:ip:toggle:{panel_id}:{toggle_val}"),
        types.InlineKeyboardButton("📋 لاگ‌ها",   callback_data=f"adm:ip:logs:{panel_id}"),
    )
    kb.add(types.InlineKeyboardButton("🤖 جزئیات Agent", callback_data=f"adm:ip:agent:{panel['agent_id']}"))
    kb.add(types.InlineKeyboardButton("🗑 حذف پنل", callback_data=f"adm:ip:del_panel:{panel_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:iran_panels"))
    send_or_edit(call, text, kb)


# ── Agent detail ───────────────────────────────────────────────────────────────

def show_iran_agent_detail(call, agent_id: int) -> None:
    agent = get_iran_agent(agent_id)
    if not agent:
        bot.answer_callback_query(call.id, "Agent یافت نشد.", show_alert=True)
        return

    icon       = _STATUS_ICON.get(agent.get("status", "pending"), "❓")
    last_seen  = agent.get("last_seen_at") or "هرگز"
    reg_at     = agent.get("registered_at") or "نامشخص"
    error_line = f"\n⚠️ خطای آخر: <code>{esc(agent['last_error'])}</code>" if agent.get("last_error") else ""

    text = (
        f"{icon} <b>Agent: {esc(agent['name'])}</b>\n\n"
        f"🆔 UUID: <code>{esc(agent['agent_uuid'])}</code>\n"
        f"📊 وضعیت: <b>{agent['status']}</b>\n"
        f"📡 آخرین heartbeat: {esc(last_seen)}\n"
        f"🕐 ثبت‌نام: {esc(reg_at)}"
        f"{error_line}"
    )

    kb = types.InlineKeyboardMarkup()
    if agent["status"] != "revoked":
        kb.add(types.InlineKeyboardButton(
            "🚫 Revoke (قطع دسترسی)",
            callback_data=f"adm:ip:revoke:{agent_id}",
        ))
    kb.add(types.InlineKeyboardButton("🗑 حذف Agent", callback_data=f"adm:ip:del_agent:{agent_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:iran_panels"))
    send_or_edit(call, text, kb)


# ── Panel logs ─────────────────────────────────────────────────────────────────

def show_iran_panel_logs(call, panel_id: int) -> None:
    panel = get_iran_panel(panel_id)
    if not panel:
        bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
        return

    logs  = get_panel_logs(panel_id, limit=15)
    lines = []
    for lg in logs:
        icon = _STATUS_ICON.get(lg["status"], "❓")
        msg  = f" — {esc(lg['message'])}" if lg.get("message") else ""
        lines.append(f"{icon} <code>{esc(lg['created_at'])}</code>{msg}")

    log_text = "\n".join(lines) if lines else "هیچ لاگی ثبت نشده است."
    text     = (
        f"📋 <b>لاگ‌های پنل: {esc(panel['name'])}</b>\n\n"
        f"{log_text}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"adm:ip:detail:{panel_id}"))
    send_or_edit(call, text, kb)


# ── Token list ─────────────────────────────────────────────────────────────────

def show_iran_token_list(call) -> None:
    tokens = get_reg_tokens(include_expired=False)
    kb     = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔑 ساخت توکن جدید", callback_data="adm:ip:mktoken"))

    for t in tokens:
        label = t["label"] or "بدون عنوان"
        kb.add(types.InlineKeyboardButton(
            f"🗝 {label} | تا: {t['expires_at'][:16]}",
            callback_data="noop",
        ))
        kb.add(types.InlineKeyboardButton(
            f"🗑 حذف «{label}»",
            callback_data=f"adm:ip:del_token:{t['id']}",
        ))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:iran_panels"))
    text = (
        f"🔑 <b>توکن‌های ثبت‌نام فعال ({len(tokens)})</b>\n\n"
        "این توکن‌ها فقط یک‌بار قابل استفاده‌اند.\n"
        "پس از استفاده توسط Agent، به‌صورت خودکار منقضی می‌شوند."
    )
    send_or_edit(call, text, kb)


# ── Token creation result ──────────────────────────────────────────────────────

def show_create_token_result(call, token: str, expires_at: str, api_base_url: str) -> None:
    """Show the newly-created token with installation instructions."""
    text = (
        "✅ <b>توکن ثبت‌نام ایجاد شد</b>\n\n"
        f"🔑 توکن (یک‌بار قابل استفاده):\n<code>{esc(token)}</code>\n\n"
        f"⏰ انقضا: <code>{esc(expires_at)}</code>\n\n"
        "─────────────────────\n"
        "📋 <b>دستورالعمل نصب روی سرور ایران:</b>\n\n"
        "1. پوشه iran/ را به سرور ایران انتقال دهید\n"
        "2. دستور زیر را اجرا کنید:\n"
        "<code>cd iran &amp;&amp; bash install.sh</code>\n\n"
        "3. هنگام نصب این اطلاعات خواسته می‌شود:\n"
        f"   • API Base URL: <code>{esc(api_base_url)}</code>\n"
        f"   • Registration Token: <code>{esc(token)}</code>\n\n"
        "⚠️ این توکن را ایمن نگه دارید و فقط یک‌بار استفاده کنید."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل‌ها", callback_data="admin:iran_panels"))
    send_or_edit(call, text, kb)
