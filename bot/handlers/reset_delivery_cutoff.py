# -*- coding: utf-8 -*-
"""
Admin command:  /reset_delivery_cutoff

Cancels every pending/queued/retry/processing/creating/failed delivery_queue
row, cancels every undelivered delivery_slot, advances the reconcile
watermark to MAX(payments.id), and re-enables reconcile.

Two-step confirmation:
    /reset_delivery_cutoff           → shows summary + CONFIRM token
    /reset_delivery_cutoff CONFIRM   → performs the reset (within 5 minutes)
"""
import time
import logging

from ..bot_instance import bot
from ..helpers import is_admin
from ..config import ADMIN_IDS
from ..db import (
    get_conn,
    setting_get,
    reset_delivery_cutoff_to_max_payment_id,
)

log = logging.getLogger(__name__)

# uid → timestamp of the last unconfirmed /reset_delivery_cutoff request
_PENDING_CONFIRM: dict = {}
_CONFIRM_TTL = 300  # 5 minutes


def _is_authorized(uid: int) -> bool:
    try:
        if uid in ADMIN_IDS:
            return True
    except Exception:
        pass
    try:
        return bool(is_admin(uid))
    except Exception:
        return False


def _summary_lines() -> list:
    enabled = str(setting_get("delivery_reconcile_enabled", "1") or "1").strip()
    cutoff = str(setting_get("delivery_reconcile_after_payment_id", "0") or "0").strip()
    try:
        with get_conn() as conn:
            queue_total = conn.execute(
                "SELECT COUNT(*) AS c FROM delivery_queue "
                "WHERE status IN ('pending','retry','processing','creating','queued','failed')"
            ).fetchone()["c"]
            slot_total = conn.execute(
                "SELECT COUNT(*) AS c FROM delivery_slots WHERE status != 'delivered'"
            ).fetchone()["c"]
            max_pid_row = conn.execute(
                "SELECT COALESCE(MAX(id), 0) AS m FROM payments"
            ).fetchone()
            max_pid = int(max_pid_row[0] if max_pid_row else 0)
    except Exception as exc:
        log.error("/reset_delivery_cutoff summary failed: %s", exc)
        queue_total = slot_total = max_pid = "?"
    return [
        "⚠️ <b>ریست صف تحویل</b>",
        "",
        f"• reconcile فعال: <code>{enabled}</code>",
        f"• cutoff فعلی: <code>{cutoff}</code>",
        f"• MAX(payments.id): <code>{max_pid}</code>",
        f"• ردیف‌های صف برای کنسل: <code>{queue_total}</code>",
        f"• اسلات‌های تحویل‌نشده برای کنسل: <code>{slot_total}</code>",
    ]


@bot.message_handler(commands=["reset_delivery_cutoff"])
def cmd_reset_delivery_cutoff(message):
    uid = message.from_user.id
    if not _is_authorized(uid):
        bot.send_message(message.chat.id, "⛔ دسترسی فقط برای مالک/ادمین مجاز است.")
        return

    text_parts = (message.text or "").strip().split()
    confirmed = len(text_parts) >= 2 and text_parts[1].strip().upper() == "CONFIRM"

    if not confirmed:
        _PENDING_CONFIRM[uid] = time.time()
        lines = _summary_lines()
        lines += [
            "",
            "برای اجرای ریست، طی ۵ دقیقه این دستور را بفرستید:",
            "<code>/reset_delivery_cutoff CONFIRM</code>",
            "",
            "این عملیات قابل بازگشت نیست.",
        ]
        bot.send_message(message.chat.id, "\n".join(lines), parse_mode="HTML")
        return

    ts = _PENDING_CONFIRM.get(uid)
    if not ts or (time.time() - ts) > _CONFIRM_TTL:
        bot.send_message(
            message.chat.id,
            "⌛ تأیید منقضی شده. ابتدا دستور <code>/reset_delivery_cutoff</code> را بدون پارامتر بفرستید.",
            parse_mode="HTML",
        )
        return

    _PENDING_CONFIRM.pop(uid, None)
    try:
        result = reset_delivery_cutoff_to_max_payment_id()
    except Exception as exc:
        log.exception("/reset_delivery_cutoff failed for uid=%s", uid)
        bot.send_message(message.chat.id, f"❌ ریست انجام نشد: <code>{exc}</code>", parse_mode="HTML")
        return

    log.warning(
        "[ADMIN] reset_delivery_cutoff by uid=%s queue_cancelled=%s slots_cancelled=%s new_cutoff=%s",
        uid, result["queue_cancelled"], result["slots_cancelled"], result["new_cutoff"],
    )
    bot.send_message(
        message.chat.id,
        "\n".join([
            "✅ <b>ریست با موفقیت انجام شد</b>",
            "",
            f"• ردیف‌های صف کنسل‌شده: <code>{result['queue_cancelled']}</code>",
            f"• اسلات‌های کنسل‌شده: <code>{result['slots_cancelled']}</code>",
            f"• cutoff جدید: <code>{result['new_cutoff']}</code>",
            "• reconcile دوباره فعال شد.",
        ]),
        parse_mode="HTML",
    )
