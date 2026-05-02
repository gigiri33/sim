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
        gateway:    "plisio", "nowpayments", or "pazzlenet"
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
            "pazzlenet":   "PazzleNet",
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


# ── Tronado auto-polling loop ─────────────────────────────────────────────────
_TRONADO_POLL_INTERVAL = 60    # seconds between each sweep
_TRONADO_MAX_AGE_HOURS = 2     # ignore payments older than this (likely abandoned)

def _tronado_poll_loop():
    """
    Background thread: every 2 minutes scan all pending Tronado payments and
    auto-confirm any that are paid, so users don't need to press the verify button.
    Only payments created in the last hour are checked (older ones are considered
    abandoned and skipped to avoid unnecessary API calls).
    """
    import time as _time
    from .db import get_conn
    from .gateways.tronado import (
        get_tronado_payment_status,
        get_tronado_status_by_payment_id,
        is_tronado_response_paid,
    )

    _time.sleep(30)  # initial delay — let bot fully start first
    while True:
        try:
            import datetime as _dt
            _cutoff = (_dt.datetime.utcnow() - _dt.timedelta(hours=_TRONADO_MAX_AGE_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
            with get_conn() as _conn:
                rows = _conn.execute(
                    "SELECT id, receipt_text FROM payments"
                    " WHERE status='pending' AND payment_method='tronado'"
                    " AND (created_at IS NULL OR created_at = '' OR created_at >= ?)",
                    (_cutoff,)
                ).fetchall()

            for row in rows:
                pay_id    = row["id"]
                token     = row["receipt_text"] or ""
                try:
                    resp = {}
                    # Try by token first (most specific)
                    if token:
                        resp = get_tronado_payment_status(token)
                    # Always also try by our payment_id prefix (more reliable after confirmation)
                    if not is_tronado_response_paid(resp):
                        resp2 = get_tronado_status_by_payment_id(str(pay_id))
                        if resp2 and not resp2.get("__http_error"):
                            resp = resp2
                    if is_tronado_response_paid(resp):
                        print(f"[Tronado] Auto-poll: payment {pay_id} PAID — fulfilling")
                        process_tronado_verified_payment(pay_id, source="auto_poll", raw_payload=resp)
                    else:
                        print(f"[Tronado] Auto-poll: payment {pay_id} not paid yet resp={str(resp)[:120]}")
                except Exception as _pe:
                    print(f"[Tronado] Auto-poll error for payment {pay_id}: {_pe}")

        except Exception as _le:
            print(f"[Tronado] Auto-poll loop error: {_le}")

        _time.sleep(_TRONADO_POLL_INTERVAL)


def start_tronado_poll_loop():
    """Start the Tronado auto-polling background thread. Call once from main()."""
    threading.Thread(target=_tronado_poll_loop, daemon=True, name="tronado-poll").start()
    print("✅ Tronado auto-poll loop started (interval: 2 min, max age: 1h)")


# ── Shared Tronado verified-payment processor ─────────────────────────────────

def process_tronado_verified_payment(payment_id: int,
                                      source: str = "manual_verify",
                                      raw_payload: dict = None) -> dict:
    """
    Central, concurrency-safe handler for a confirmed Tronado payment.

    Steps:
    1. Load payment row; validate it belongs to tronado.
    2. If already completed/processing → return already_processed.
    3. Atomically lock (pending → processing) via BEGIN IMMEDIATE.
    4. If lock failed → already_processed (another thread/IPN won the race).
    5. Persist raw_payload + audit fields.
    6. Amount-check: if Tronado returned an amount, verify it matches ±5%.
    7. Run fulfillment (wallet_charge or config/renewal).
    8. On success: mark completed + fulfilled_at.
    9. If fulfillment raised, reset to pending so it can be retried.

    Returns:
        {"status": "already_processed"} — payment was not pending
        {"status": "ok"}               — fulfilled successfully
        {"status": "error", "msg": ...} — fulfillment failed
        {"status": "amount_mismatch", "expected": ..., "got": ...} — security check failed
    """
    from .db import (
        get_payment, get_conn, update_balance,
        get_payment_service_names, save_tronado_callback_data,
        get_package, get_purchase,
    )
    from .helpers import fmt_price, now_str
    from .payments import apply_gateway_bonus_if_needed
    from .bot_instance import bot
    import json as _json
    import traceback as _tb

    payment = get_payment(payment_id)
    if not payment:
        print(f"[Tronado] process_verified: payment {payment_id} not found")
        return {"status": "already_processed"}

    if payment["payment_method"] != "tronado":
        print(f"[Tronado] process_verified: payment {payment_id} is not tronado ({payment['payment_method']})")
        return {"status": "already_processed"}

    if payment["status"] not in ("pending",):
        print(f"[Tronado] process_verified: payment {payment_id} already {payment['status']} (source={source})")
        return {"status": "already_processed"}

    # ── Amount validation ──────────────────────────────────────────────────────
    if raw_payload and isinstance(raw_payload, dict):
        for amt_key in ("Amount", "amount", "TomanAmount", "tomanAmount"):
            ext_amount = raw_payload.get(amt_key)
            if ext_amount is not None:
                try:
                    ext_amount_int = int(float(ext_amount))
                    expected = payment["amount"]
                    # Allow ±5% tolerance (Tronado may include slight rounding)
                    if abs(ext_amount_int - expected) > expected * 0.05 + 100:
                        print(f"[Tronado] process_verified: amount mismatch payment {payment_id}"
                              f" expected={expected} got={ext_amount_int}")
                        return {"status": "amount_mismatch", "expected": expected, "got": ext_amount_int}
                except Exception:
                    pass
                break

    # ── Extract audit IDs from payload ────────────────────────────────────────
    gateway_ref = ""
    external_txid = ""
    if raw_payload and isinstance(raw_payload, dict):
        gateway_ref = str(
            raw_payload.get("UniqueCode") or raw_payload.get("uniqueCode") or
            raw_payload.get("OrderId")    or raw_payload.get("orderId") or ""
        )[:255]
        external_txid = str(
            raw_payload.get("Hash")          or raw_payload.get("hash") or
            raw_payload.get("TransactionId") or raw_payload.get("transactionId") or
            raw_payload.get("TxHash")        or ""
        )[:255]
    raw_payload_str = _json.dumps(raw_payload, ensure_ascii=False)[:4000] if raw_payload else ""

    # ── Atomically lock the payment (BEGIN IMMEDIATE) ─────────────────────────
    try:
        from .db import lock_tronado_payment
        locked = lock_tronado_payment(payment_id)
    except Exception as _le:
        print(f"[Tronado] process_verified: lock error payment {payment_id}: {_le}")
        # If lock_tronado_payment used BEGIN IMMEDIATE and the table is locked,
        # treat it as "someone else is processing".
        return {"status": "already_processed"}

    if not locked:
        print(f"[Tronado] process_verified: payment {payment_id} lock lost (already processing/completed)")
        return {"status": "already_processed"}

    # ── Persist audit data ────────────────────────────────────────────────────
    try:
        save_tronado_callback_data(payment_id, raw_payload_str, gateway_ref, external_txid)
    except Exception:
        pass

    print(f"[Tronado] process_verified: LOCKED payment {payment_id} source={source}"
          f" kind={payment['kind']} uid={payment['user_id']} amount={payment['amount']}")

    kind   = payment["kind"]
    uid    = payment["user_id"]
    amount = payment["amount"]

    try:
        if kind == "wallet_charge":
            # Mark completed first (atomic — lock already held above)
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
                    " WHERE id=? AND status='processing'",
                    (now_str(), now_str(), payment_id)
                )
            update_balance(uid, amount)
            try:
                apply_gateway_bonus_if_needed(uid, "tronado", amount)
            except Exception:
                pass
            try:
                bot.send_message(
                    uid,
                    f"✅ پرداخت ترونادو تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(amount)} تومان",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        else:
            # config_purchase / renewal / pnlcfg_renewal — delegate to run_crypto_fulfillment
            # but override the 'pending' check since we already set to 'processing'.
            # We directly call the fulfillment body with status='processing'.
            _fulfill_tronado_non_wallet(payment_id, kind, uid, amount, payment)

        return {"status": "ok"}

    except Exception as exc:
        _tb.print_exc()
        print(f"[Tronado] process_verified: fulfillment error payment {payment_id}: {exc}")
        # Reset to pending so auto-poll or next verify can retry
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='pending' WHERE id=? AND status='processing'",
                    (payment_id,)
                )
        except Exception:
            pass
        return {"status": "error", "msg": str(exc)}


def _fulfill_tronado_non_wallet(payment_id: int, kind: str, uid: int, amount: int, payment):
    """
    Fulfils a locked (status=processing) non-wallet Tronado payment.
    Marks completed on success; caller is responsible for resetting on exception.
    """
    from .db import (
        complete_payment, get_package, get_purchase, get_conn,
        get_payment_service_names,
    )
    from .helpers import now_str
    from .payments import apply_gateway_bonus_if_needed
    from .bot_instance import bot

    # Mark completed now (we hold the processing lock)
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
            " WHERE id=? AND status='processing'",
            (now_str(), now_str(), payment_id)
        )

    if kind == "config_purchase":
        from .handlers.callbacks import _deliver_bulk_configs, _send_bulk_delivery_result
        pkg_row = get_package(payment["package_id"])
        qty = int(payment["quantity"]) if "quantity" in payment.keys() else 1
        try:
            bot.send_message(
                uid,
                "✅ پرداخت ترونادو تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                parse_mode="HTML",
            )
        except Exception:
            pass
        snames = get_payment_service_names(payment_id)
        purchase_ids, pending_ids = _deliver_bulk_configs(
            uid, uid, payment["package_id"], amount, "tronado", qty, payment_id,
            service_names=snames,
        )
        try:
            apply_gateway_bonus_if_needed(uid, "tronado", amount)
        except Exception:
            pass
        _send_bulk_delivery_result(uid, uid, pkg_row, purchase_ids, pending_ids, "ترونادو")

    elif kind == "renewal":
        from .ui.notifications import admin_renewal_notify
        pkg_row = get_package(payment["package_id"])
        cfg_id  = payment["config_id"]
        with get_conn() as conn:
            row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (cfg_id,)).fetchone()
        pid  = row["purchase_id"] if row else 0
        item = get_purchase(pid) if pid else None
        try:
            bot.send_message(
                uid,
                "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                "🔄 پرداخت ترونادو تأیید و درخواست تمدید ثبت شد.\n"
                "⏳ پس از انجام تمدید به شما اطلاع داده خواهد شد.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        if item:
            admin_renewal_notify(uid, item, pkg_row, amount, "ترونادو")
        try:
            apply_gateway_bonus_if_needed(uid, "tronado", amount)
        except Exception:
            pass

    elif kind == "pnlcfg_renewal":
        from .handlers.callbacks import _execute_pnlcfg_renewal
        cfg_id = payment["config_id"]
        pkg_id = payment["package_id"]
        ok_r, _ = _execute_pnlcfg_renewal(cfg_id, pkg_id, chat_id=uid, uid=uid)
        if ok_r:
            try:
                bot.send_message(uid, "✅ پرداخت ترونادو تأیید و سرویس تمدید شد.", parse_mode="HTML")
            except Exception:
                pass
        else:
            try:
                bot.send_message(uid,
                    "✅ پرداخت ترونادو تأیید شد اما تمدید سرویس با خطا مواجه شد.\n"
                    "لطفاً با پشتیبانی ارتباط بگیرید.",
                    parse_mode="HTML")
            except Exception:
                pass
        try:
            apply_gateway_bonus_if_needed(uid, "tronado", amount)
        except Exception:
            pass

