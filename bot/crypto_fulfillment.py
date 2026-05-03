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
            is_payment_expired,
        )
        from .helpers import fmt_price
        from .payments import apply_gateway_bonus_if_needed
        from .bot_instance import bot

        payment = get_payment(payment_id)
        if not payment or payment["status"] != "pending":
            return
        if is_payment_expired(payment):
            print(f"[EXPIRED PAYMENT IGNORED] payment_id={payment_id}")
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
        get_tronado_token_from_payment,
    )

    _time.sleep(30)  # initial delay — let bot fully start first
    while True:
        try:
            import datetime as _dt
            _cutoff = (_dt.datetime.utcnow() - _dt.timedelta(hours=_TRONADO_MAX_AGE_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
            with get_conn() as _conn:
                rows = _conn.execute(
                    "SELECT * FROM payments"
                    " WHERE status='pending' AND payment_method='tronado'"
                    " AND (created_at IS NULL OR created_at = '' OR created_at >= ?)",
                    (_cutoff,)
                ).fetchall()

            for row in rows:
                pay_id    = row["id"]
                try:
                    token = get_tronado_token_from_payment(row)
                    print(f"[Tronado] Auto-poll: checking payment {pay_id} token={'yes' if token else 'no'}")
                    proc = process_tronado_verified_payment(pay_id, source="auto_poll", raw_payload={"auto_poll": True})
                    if proc.get("status") == "ok":
                        print(f"[Tronado] Auto-poll: payment {pay_id} PAID — fulfilled")
                    else:
                        print(f"[Tronado] Auto-poll: payment {pay_id} result={proc}")
                except Exception as _pe:
                    print(f"[Tronado] Auto-poll error for payment {pay_id}: {_pe}")

        except Exception as _le:
            print(f"[Tronado] Auto-poll loop error: {_le}")

        _time.sleep(_TRONADO_POLL_INTERVAL)


def start_tronado_poll_loop():
    """Start the Tronado auto-polling background thread. Call once from main()."""
    threading.Thread(target=_tronado_poll_loop, daemon=True, name="tronado-poll").start()
    print("✅ Tronado auto-poll loop started (interval: 2 min, max age: 1h)")


# ── CentralPay verified-payment processor ────────────────────────────────────

def process_centralpay_verified_payment(payment_id: int,
                                         source: str = "manual_verify",
                                         raw_payload: dict = None) -> dict:
    """
    Central, concurrency-safe handler for a confirmed CentralPay payment.

    CentralPay's verify endpoint returns success=true on EVERY call for paid orders,
    so an atomic lock (pending → processing) is mandatory before fulfillment.

    Returns:
        {"status": "already_processed"}                           — not pending
        {"status": "ok"}                                          — fulfilled
        {"status": "error", "msg": ...}                           — fulfillment error
        {"status": "amount_mismatch", "expected": ..., "got": ...}
    """
    import json as _json
    import traceback as _tb

    from .db import (
        get_payment, get_conn, update_balance,
        get_payment_service_names,
        get_package, get_purchase,
        lock_centralpay_payment,
        is_payment_expired,
    )
    from .helpers import fmt_price, now_str
    from .payments import apply_gateway_bonus_if_needed
    from .bot_instance import bot
    from .gateways.centralpay import verify_centralpay_order

    payment = get_payment(payment_id)
    if not payment:
        print(f"[CentralPay] process_verified: payment {payment_id} not found")
        return {"status": "already_processed"}

    if payment["payment_method"] != "centralpay":
        print(f"[CentralPay] process_verified: payment {payment_id} is not centralpay ({payment['payment_method']})")
        return {"status": "already_processed"}

    if payment["status"] not in ("pending",):
        print(f"[CentralPay] process_verified: payment {payment_id} already {payment['status']} (source={source})")
        return {"status": "already_processed"}

    if is_payment_expired(payment):
        print(f"[EXPIRED PAYMENT IGNORED] payment_id={payment_id}")
        return {"status": "expired"}

    # ── Atomic lock ───────────────────────────────────────────────────────────
    try:
        locked = lock_centralpay_payment(payment_id)
    except Exception as _le:
        print(f"[CentralPay] process_verified: lock error payment {payment_id}: {_le}")
        return {"status": "already_processed"}

    if not locked:
        print(f"[CentralPay] process_verified: payment {payment_id} lock lost (already processing/completed)")
        return {"status": "already_processed"}

    # ── Call verify API ───────────────────────────────────────────────────────
    try:
        ok_v, verify_result = verify_centralpay_order(payment_id)
    except Exception as _ve:
        _tb.print_exc()
        # Reset to pending so it can be retried
        try:
            with get_conn() as _c:
                _c.execute("UPDATE payments SET status='pending' WHERE id=? AND status='processing'", (payment_id,))
        except Exception:
            pass
        return {"status": "error", "msg": str(_ve)}

    if not ok_v:
        # Not paid — reset to pending and return
        try:
            with get_conn() as _c:
                _c.execute("UPDATE payments SET status='pending' WHERE id=? AND status='processing'", (payment_id,))
        except Exception:
            pass
        err = verify_result.get("error", "") if isinstance(verify_result, dict) else str(verify_result)
        print(f"[CentralPay] process_verified: payment {payment_id} not paid: {err}")
        return {"status": "not_paid", "msg": err}

    # ── Amount validation ─────────────────────────────────────────────────────
    def _payment_payable_amount(row) -> int:
        try:
            final_amount = row["final_amount"] if "final_amount" in row.keys() else None
            if final_amount:
                return int(final_amount)
        except Exception:
            pass
        return int(row["amount"])

    returned_amount = verify_result.get("amount", 0) if isinstance(verify_result, dict) else 0
    if returned_amount:
        expected = _payment_payable_amount(payment)
        if abs(int(returned_amount) - expected) > expected * 0.05 + 100:
            print(f"[CentralPay] process_verified: amount mismatch payment {payment_id}"
                  f" expected={expected} got={returned_amount}")
            try:
                with get_conn() as _c:
                    _c.execute("UPDATE payments SET status='pending' WHERE id=? AND status='processing'", (payment_id,))
            except Exception:
                pass
            return {"status": "amount_mismatch", "expected": expected, "got": returned_amount}

    # ── Persist audit data ────────────────────────────────────────────────────
    reference_id = verify_result.get("reference_id", "") if isinstance(verify_result, dict) else ""
    raw_str = _json.dumps(verify_result.get("raw", {}), ensure_ascii=False)[:4000] if isinstance(verify_result, dict) else ""
    try:
        with get_conn() as _c:
            _c.execute(
                "UPDATE payments SET raw_callback=?, callback_received_at=?,"
                " gateway_ref=COALESCE(NULLIF(?, ''), gateway_ref),"
                " external_txid=COALESCE(NULLIF(?, ''), external_txid)"
                " WHERE id=?",
                (raw_str, now_str(), str(payment_id), reference_id or "", payment_id)
            )
    except Exception:
        pass

        payable_amount = _payment_payable_amount(payment)
        print(f"[CentralPay] process_verified: LOCKED & VERIFIED payment {payment_id} source={source}"
            f" kind={payment['kind']} uid={payment['user_id']} amount={payment['amount']} payable={payable_amount}")

    kind   = payment["kind"]
    uid    = payment["user_id"]
    amount = payment["amount"]

    try:
        if kind == "wallet_charge":
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
                    " WHERE id=? AND status='processing'",
                    (now_str(), now_str(), payment_id)
                )
            update_balance(uid, amount)
            try:
                apply_gateway_bonus_if_needed(uid, "centralpay", amount)
            except Exception:
                pass
            try:
                bot.send_message(
                    uid,
                    f"✅ پرداخت سنترال‌پی تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(amount)} تومان",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        elif kind == "config_purchase":
            from .handlers.callbacks import _deliver_bulk_configs, _send_bulk_delivery_result
            pkg_row = get_package(payment["package_id"])
            qty = int(payment["quantity"]) if "quantity" in payment.keys() else 1
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
                    " WHERE id=? AND status='processing'",
                    (now_str(), now_str(), payment_id)
                )
            try:
                bot.send_message(uid, "✅ پرداخت سنترال‌پی تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...", parse_mode="HTML")
            except Exception:
                pass
            snames = get_payment_service_names(payment_id)
            purchase_ids, pending_ids = _deliver_bulk_configs(
                uid, uid, payment["package_id"], amount, "centralpay", qty, payment_id,
                service_names=snames,
            )
            try:
                apply_gateway_bonus_if_needed(uid, "centralpay", amount)
            except Exception:
                pass
            _send_bulk_delivery_result(uid, uid, pkg_row, purchase_ids, pending_ids, "سنترال‌پی")

        elif kind == "renewal":
            from .ui.notifications import admin_renewal_notify
            pkg_row = get_package(payment["package_id"])
            cfg_id  = payment["config_id"]
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
                    " WHERE id=? AND status='processing'",
                    (now_str(), now_str(), payment_id)
                )
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (cfg_id,)).fetchone()
            pid  = row["purchase_id"] if row else 0
            item = get_purchase(pid) if pid else None
            try:
                bot.send_message(uid,
                    "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                    "🔄 پرداخت سنترال‌پی تأیید و درخواست تمدید ثبت شد.\n"
                    "⏳ پس از انجام تمدید به شما اطلاع داده خواهد شد.",
                    parse_mode="HTML")
            except Exception:
                pass
            if item:
                admin_renewal_notify(uid, item, pkg_row, amount, "سنترال‌پی")
            try:
                apply_gateway_bonus_if_needed(uid, "centralpay", amount)
            except Exception:
                pass

        elif kind == "pnlcfg_renewal":
            from .handlers.callbacks import _execute_pnlcfg_renewal
            cfg_id = payment["config_id"]
            pkg_id = payment["package_id"]
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
                    " WHERE id=? AND status='processing'",
                    (now_str(), now_str(), payment_id)
                )
            ok_r, _ = _execute_pnlcfg_renewal(cfg_id, pkg_id, chat_id=uid, uid=uid)
            try:
                if ok_r:
                    bot.send_message(uid, "✅ پرداخت سنترال‌پی تأیید و سرویس تمدید شد.", parse_mode="HTML")
                else:
                    bot.send_message(uid,
                        "✅ پرداخت سنترال‌پی تأیید شد اما تمدید سرویس با خطا مواجه شد.\n"
                        "لطفاً با پشتیبانی ارتباط بگیرید.", parse_mode="HTML")
            except Exception:
                pass
            try:
                apply_gateway_bonus_if_needed(uid, "centralpay", amount)
            except Exception:
                pass

        else:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
                    " WHERE id=? AND status='processing'",
                    (now_str(), now_str(), payment_id)
                )

        return {"status": "ok"}

    except Exception as exc:
        _tb.print_exc()
        print(f"[CentralPay] process_verified: fulfillment error payment {payment_id}: {exc}")
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='pending' WHERE id=? AND status='processing'",
                    (payment_id,)
                )
        except Exception:
            pass
        return {"status": "error", "msg": str(exc)}


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
        is_payment_expired,
    )
    from .helpers import fmt_price, now_str
    from .payments import apply_gateway_bonus_if_needed
    from .bot_instance import bot
    from .gateways.tronado import (
        get_tronado_token_from_payment,
        get_tronado_payment_status,
        get_tronado_status_by_payment_id,
        get_tronado_status_by_prefixed_payment_id,
        normalize_tronado_status,
        extract_tronado_callback_payload,
        is_tronado_success_callback_payload,
    )
    import json as _json
    import traceback as _tb

    payment = get_payment(payment_id)
    if not payment:
        print(f"[Tronado] process_verified: payment {payment_id} not found")
        return {"status": "already_processed"}

    if payment["payment_method"] != "tronado":
        print(f"[Tronado] process_verified: payment {payment_id} is not tronado ({payment['payment_method']})")
        return {"status": "already_processed"}

    if payment["status"] not in ("pending", "rejected", "failed"):
        print(f"[Tronado] process_verified: payment {payment_id} already {payment['status']} (source={source})")
        return {"status": "already_processed"}

    if is_payment_expired(payment):
        print(f"[EXPIRED PAYMENT IGNORED] payment_id={payment_id}")
        return {"status": "expired"}

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

    # ── Verify exact Tronado order for this payment ───────────────────────────
    # IMPORTANT: token is read only from this payment row. Never scan/choose an
    # older pending payment or a latest payment.
    token = get_tronado_token_from_payment(payment)
    verify_resp = {}
    verify_key = ""
    norm = "unknown"
    try:
        flat_ipn = extract_tronado_callback_payload(raw_payload or {})
        if source == "ipn" and is_tronado_success_callback_payload(raw_payload or {}):
            cb_pid = str(flat_ipn.get("PaymentID") or flat_ipn.get("paymentId") or flat_ipn.get("payment_id") or "")
            cb_uid = str(flat_ipn.get("UserTelegramId") or flat_ipn.get("userTelegramId") or "")
            if cb_pid and cb_pid not in (str(payment_id), f"tronado-wc-{payment_id}"):
                print(f"[Tronado] process_verified: IPN payment id mismatch url={payment_id} payload={cb_pid}")
            elif cb_uid and cb_uid != str(payment["user_id"]):
                print(f"[Tronado] process_verified: IPN user mismatch payment={payment_id} db_uid={payment['user_id']} payload_uid={cb_uid}")
            else:
                verify_key = "trusted_ipn"
                verify_resp = flat_ipn
                norm = "paid"
                print(f"[Tronado] process_verified: trusted successful IPN payment={payment_id}")

        if norm != "paid" and token:
            verify_key = token
            verify_resp = get_tronado_payment_status(token)
            norm = normalize_tronado_status(verify_resp)
            print(f"[Tronado] process_verified: GetStatus by token payment={payment_id} norm={norm}")

        if norm != "paid":
            # Primary fallback: exact PaymentID used when creating GetOrderToken.
            verify_key = str(payment_id)
            fallback_resp = get_tronado_status_by_payment_id(str(payment_id))
            fallback_norm = normalize_tronado_status(fallback_resp)
            print(f"[Tronado] process_verified: GetStatus by PaymentID payment={payment_id} norm={fallback_norm}")
            if fallback_norm == "paid" or norm in ("unknown", "error"):
                verify_resp = fallback_resp
                norm = fallback_norm

        if norm != "paid":
            # Legacy fallback only. This endpoint often returns HTTP 500, so it
            # must never be the first or only lookup path.
            verify_key = f"trndorderid_{payment_id}"
            pref_resp = get_tronado_status_by_prefixed_payment_id(str(payment_id))
            pref_norm = normalize_tronado_status(pref_resp)
            print(f"[Tronado] process_verified: GetStatus prefixed fallback payment={payment_id} norm={pref_norm}")
            if pref_norm == "paid" or norm in ("unknown", "error"):
                verify_resp = pref_resp
                norm = pref_norm

    except Exception as _ve:
        _tb.print_exc()
        try:
            with get_conn() as conn:
                conn.execute("UPDATE payments SET status='pending' WHERE id=? AND status='processing'", (payment_id,))
        except Exception:
            pass
        print(f"[Tronado] process_verified: verify error payment {payment_id}: {_ve}")
        return {"status": "error", "msg": str(_ve)}

    audit_payload = {
        "source": source,
        "incoming": raw_payload or {},
        "verify_key": verify_key,
        "verify_response": verify_resp,
        "normalized_status": norm,
    }

    # ── Extract audit IDs from verified response/payload ──────────────────────
    def _deep_get(dct, *keys):
        if not isinstance(dct, dict):
            return ""
        candidates = [dct]
        data = dct.get("Data") or dct.get("data")
        if isinstance(data, dict):
            candidates.insert(0, data)
        for obj in candidates:
            for key in keys:
                val = obj.get(key)
                if val:
                    return val
        return ""

    gateway_ref = str(_deep_get(verify_resp, "UniqueCode", "uniqueCode", "OrderId", "orderId") or token or "")[:255]
    external_txid = str(_deep_get(verify_resp, "Hash", "hash", "TransactionId", "transactionId", "TxHash") or "")[:255]
    raw_payload_str = _json.dumps(audit_payload, ensure_ascii=False)[:4000]

    # ── Persist audit data ────────────────────────────────────────────────────
    try:
        save_tronado_callback_data(payment_id, raw_payload_str, gateway_ref, external_txid)
    except Exception:
        pass

    if norm == "pending" or norm == "unknown" or norm == "error":
        try:
            with get_conn() as conn:
                conn.execute("UPDATE payments SET status='pending' WHERE id=? AND status='processing'", (payment_id,))
        except Exception:
            pass
        print(f"[Tronado] process_verified: payment {payment_id} not paid yet norm={norm} resp={str(verify_resp)[:300]}")
        return {"status": "pending", "verify_status": norm, "raw_resp": verify_resp}

    if norm == "rejected":
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='rejected', rejected_at=?, reject_reason=? WHERE id=? AND status='processing'",
                    (now_str(), "Tronado rejected/failed", payment_id)
                )
        except Exception:
            try:
                with get_conn() as conn:
                    conn.execute("UPDATE payments SET status='rejected' WHERE id=? AND status='processing'", (payment_id,))
            except Exception:
                pass
        print(f"[Tronado] process_verified: payment {payment_id} rejected resp={str(verify_resp)[:300]}")
        return {"status": "rejected", "raw_resp": verify_resp}

    # ── Amount validation ──────────────────────────────────────────────────────
    for amt_key in ("Amount", "amount", "TomanAmount", "tomanAmount", "Toman", "Price"):
        ext_amount = _deep_get(verify_resp, amt_key)
        if ext_amount is not None and ext_amount != "":
            try:
                ext_amount_int = int(float(ext_amount))
                expected = payment["amount"]
                # Allow ±5% tolerance (Tronado may include slight rounding/fees)
                if abs(ext_amount_int - expected) > expected * 0.05 + 100:
                    print(f"[Tronado] process_verified: amount mismatch payment {payment_id}"
                          f" expected={expected} got={ext_amount_int}")
                    try:
                        with get_conn() as conn:
                            conn.execute("UPDATE payments SET status='pending' WHERE id=? AND status='processing'", (payment_id,))
                    except Exception:
                        pass
                    return {"status": "amount_mismatch", "expected": expected, "got": ext_amount_int}
            except Exception:
                pass
            break

    print(f"[Tronado] process_verified: LOCKED & PAID payment {payment_id} source={source}"
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

