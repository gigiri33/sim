# -*- coding: utf-8 -*-
"""
Shared fulfillment logic for crypto gateways (Plisio / NowPayments).

Called from:
  - main.py  (webhook handler — when IPN arrives immediately)
  - bot/handlers/callbacks.py  (admin force-check panel)
  - auto-verify polling threads (fallback via complete_payment guard)
"""
import threading


def run_crypto_fulfillment(gateway: str, payment_id: int):
    """
    Complete and deliver a non-wallet-charge crypto payment.

    Safe to call from multiple threads — ``complete_payment`` is atomic and
    only the first caller proceeds; subsequent calls are no-ops.

    Args:
        gateway:    "plisio" or "nowpayments"
        payment_id: DB row ID of the payment
    """
    try:
        from .db import (
            get_payment, complete_payment, update_balance,
            get_package, get_purchase, get_conn,
            get_payment_service_names,
        )
        from .helpers import fmt_price
        from .payments import apply_gateway_bonus_if_needed
        from .bot_instance import bot

        payment = get_payment(payment_id)
        if not payment or payment["status"] != "pending":
            return
        if not complete_payment(payment_id):
            return  # already handled by another path

        kind     = payment["kind"]
        uid      = payment["user_id"]
        amount   = payment["amount"]
        gw_label = {
            "plisio":      "Plisio",
            "nowpayments": "NowPayments",
        }.get(gateway, gateway.capitalize())

        if kind == "wallet_charge":
            update_balance(uid, amount)
            try:
                apply_gateway_bonus_if_needed(uid, gateway, amount)
            except Exception:
                pass
            try:
                bot.send_message(
                    uid,
                    f"✅ پرداخت {gw_label} شما تأیید شد و کیف پول شارژ شد.\n\n"
                    f"💰 مبلغ: {fmt_price(amount)} تومان",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        elif kind == "config_purchase":
            from .handlers.callbacks import _deliver_bulk_configs, _send_bulk_delivery_result
            pkg_row = get_package(payment["package_id"])
            qty = int(payment["quantity"]) if "quantity" in payment.keys() else 1
            try:
                bot.send_message(
                    uid,
                    f"✅ پرداخت {gw_label} شما تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            snames = get_payment_service_names(payment_id)
            purchase_ids, pending_ids = _deliver_bulk_configs(
                uid, uid, payment["package_id"], amount, gateway, qty, payment_id,
                service_names=snames,
            )
            try:
                apply_gateway_bonus_if_needed(uid, gateway, amount)
            except Exception:
                pass
            _send_bulk_delivery_result(uid, uid, pkg_row, purchase_ids, pending_ids, gw_label)

        elif kind == "renewal":
            from .ui.notifications import admin_renewal_notify
            pkg_row = get_package(payment["package_id"])
            cfg_id  = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT purchase_id FROM configs WHERE id=?", (cfg_id,)
                ).fetchone()
            pid  = row["purchase_id"] if row else 0
            item = get_purchase(pid) if pid else None
            try:
                bot.send_message(
                    uid,
                    "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                    "🔄 پرداخت تأیید و درخواست تمدید ثبت شد.\n"
                    "⏳ پس از انجام تمدید به شما اطلاع داده خواهد شد.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            if item:
                admin_renewal_notify(uid, item, pkg_row, amount, gw_label)
            try:
                apply_gateway_bonus_if_needed(uid, gateway, amount)
            except Exception:
                pass

        elif kind == "pnlcfg_renewal":
            from .handlers.callbacks import _execute_pnlcfg_renewal
            cfg_id = payment["config_id"]
            pkg_id = payment["package_id"]
            ok_r, _ = _execute_pnlcfg_renewal(cfg_id, pkg_id, chat_id=uid, uid=uid)
            if ok_r:
                try:
                    bot.send_message(
                        uid,
                        f"✅ پرداخت {gw_label} تأیید و سرویس تمدید شد.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            else:
                try:
                    bot.send_message(
                        uid,
                        "✅ پرداخت تأیید شد اما تمدید سرویس با خطا مواجه شد.\n"
                        "لطفاً با پشتیبانی ارتباط بگیرید.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            try:
                apply_gateway_bonus_if_needed(uid, gateway, amount)
            except Exception:
                pass

    except Exception as exc:
        print(f"CRYPTO_FULFILLMENT_ERROR [{gateway} #{payment_id}]: {exc}")


def run_crypto_fulfillment_async(gateway: str, payment_id: int):
    """Start fulfillment in a daemon thread (fire-and-forget)."""
    threading.Thread(
        target=run_crypto_fulfillment,
        args=(gateway, payment_id),
        daemon=True,
    ).start()
