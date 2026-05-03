# -*- coding: utf-8 -*-
"""
RialPay payment gateway — create invoices and handle webhook callbacks.
Webhook authentication via HMAC-SHA256 (X-Signature header).
"""

import json
import hmac
import hashlib
import urllib.request
import urllib.error

from ..db import setting_get


RIALPAY_DEFAULT_CREATE_URL = "https://rialbotapi.shop/api/create_invoice.php"


def _decode_response_body(resp) -> tuple:
    raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return "", {}
    try:
        return raw, json.loads(raw)
    except Exception:
        return raw, raw


def _extract_error(data) -> str:
    if isinstance(data, dict):
        for key in ("message", "Message", "error", "Error", "msg", "detail"):
            if data.get(key):
                return str(data[key])[:500]
        return json.dumps(data, ensure_ascii=False)[:500]
    return str(data)[:500]


def create_rialpay_invoice(amount_toman: int, user_id, order_id, callback_url: str) -> tuple:
    """
    Create a RialPay invoice.

    Returns:
        (True, {"status": "created", "amount": ..., "token": ..., "payment_url": ..., "raw": ...})
        (False, {"status": "error", "error": ..., "raw": ...})
    """
    api_key = (setting_get("rialpay_api_key", "") or "").strip()
    if not api_key:
        return False, {"status": "error", "error": "کلید API ریال‌پی تنظیم نشده است.", "raw": {}}

    create_url = (setting_get("rialpay_create_invoice_url", "") or RIALPAY_DEFAULT_CREATE_URL).strip()

    # Try form-encoded first (most PHP APIs expect this), fallback to JSON
    import urllib.parse as _urlparse
    form_data = _urlparse.urlencode({
        "api_key":  api_key,
        "amount":   int(amount_toman),
        "callback": callback_url,
        "order_id": str(order_id),
    }).encode("utf-8")

    print(f"[RialPay] create_invoice → POST {create_url} | order_id={order_id} amount={amount_toman}")

    req = urllib.request.Request(
        create_url,
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept":       "application/json, text/plain, */*",
            "User-Agent":   "ConfigFlow/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw, parsed = _decode_response_body(resp)
    except urllib.error.HTTPError as e:
        raw_body = ""
        try:
            raw_body = e.read().decode("utf-8", errors="replace").strip()
        except Exception:
            pass
        print(f"[RialPay] create_invoice HTTP error {e.code}: {raw_body[:400]}")
        try:
            parsed = json.loads(raw_body) if raw_body else {}
        except Exception:
            parsed = raw_body
        err = _extract_error(parsed) or f"HTTP {e.code}"
        return False, {"status": "error", "error": f"خطای RialPay: {err}", "raw": parsed}
    except Exception as e:
        return False, {"status": "error", "error": f"خطا در اتصال به ریال‌پی: {e}", "raw": {}}

    print(f"[RialPay] create_invoice order_id={order_id} response: {raw[:600]}")

    data = parsed if isinstance(parsed, dict) else {}
    api_status = data.get("status")

    if api_status is True or str(api_status).lower() in ("true", "1", "ok", "success"):
        token = str(data.get("token") or "").strip()
        link  = str(data.get("link")  or data.get("payment_url") or "").strip()
        if token and link:
            return True, {
                "status":      "created",
                "amount":      data.get("amount", amount_toman),
                "token":       token,
                "payment_url": link,
                "raw":         data,
            }
        return False, {
            "status": "error",
            "error":  f"ریال‌پی پاسخ ناقص برگرداند (token یا link خالی است): {raw[:300]}",
            "raw":    data,
        }

    err_msg = _extract_error(data) or raw[:300]
    print(f"[RialPay] create_invoice FAILED order_id={order_id}: status={api_status!r} raw={raw[:400]}")
    return False, {"status": "error", "error": f"ساخت فاکتور ریال‌پی ناموفق بود: {err_msg}\n\nپاسخ سرور: {raw[:200]}", "raw": data}


def verify_rialpay_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verify X-Signature header from RialPay webhook using HMAC-SHA256.

    If rialpay_webhook_secret is not set, returns False (reject all).
    """
    secret = (setting_get("rialpay_webhook_secret", "") or "").strip()
    if not secret:
        print("[RialPay] webhook signature check FAILED: Webhook Secret ریال‌پی تنظیم نشده است.")
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip())


def normalize_rialpay_status(status: str) -> str:
    """
    Normalise a RialPay status string to one of:
      "paid" | "rejected" | "pending" | "unknown"
    """
    s = str(status or "").strip().lower()
    if s == "paid":
        return "paid"
    if s == "rejected":
        return "rejected"
    if s == "pending":
        return "pending"
    return "unknown"


def process_rialpay_verified_payment(payment_id: int,
                                      source: str = "webhook",
                                      raw_payload: dict = None) -> dict:
    """
    Central, concurrency-safe handler for a confirmed RialPay payment.

    Returns:
        {"status": "already_processed"}
        {"status": "ok"}
        {"status": "error", "msg": ...}
        {"status": "amount_mismatch", "expected": ..., "got": ...}
    """
    import traceback as _tb
    import json as _json
    from ..db import (
        get_payment, get_conn, update_balance,
        get_payment_service_names, now_str,
        get_package, get_purchase,
    )
    from ..helpers import fmt_price
    from ..payments import apply_gateway_bonus_if_needed
    from ..bot_instance import bot

    payment = get_payment(payment_id)
    if not payment:
        print(f"[RialPay] process_verified: payment {payment_id} not found")
        return {"status": "already_processed"}

    if payment["payment_method"] != "rialpay":
        print(f"[RialPay] process_verified: payment {payment_id} wrong method {payment['payment_method']}")
        return {"status": "already_processed"}

    if payment["status"] not in ("pending",):
        print(f"[RialPay] process_verified: payment {payment_id} already {payment['status']} (source={source})")
        return {"status": "already_processed"}

    # ── Amount validation ──────────────────────────────────────────────────────
    if raw_payload and isinstance(raw_payload, dict):
        ext_amount = raw_payload.get("amount")
        if ext_amount is not None:
            try:
                ext_amount_int = int(float(ext_amount))
                expected = payment["amount"]
                if abs(ext_amount_int - expected) > expected * 0.05 + 100:
                    print(f"[RialPay] process_verified: amount mismatch payment={payment_id}"
                          f" expected={expected} got={ext_amount_int}")
                    return {"status": "amount_mismatch", "expected": expected, "got": ext_amount_int}
            except Exception:
                pass

    # ── Extract audit fields ───────────────────────────────────────────────────
    gateway_ref   = ""
    external_txid = ""
    if raw_payload and isinstance(raw_payload, dict):
        gateway_ref   = str(raw_payload.get("token")      or raw_payload.get("order_id") or "")[:255]
        external_txid = str(raw_payload.get("invoice_id") or "")[:255]
    raw_payload_str = _json.dumps(raw_payload, ensure_ascii=False)[:4000] if raw_payload else ""

    # ── Atomic lock: pending → processing ─────────────────────────────────────
    try:
        with get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE payments SET status='processing'"
                " WHERE id=? AND payment_method='rialpay' AND status='pending'",
                (payment_id,)
            )
            changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
            conn.execute("COMMIT")
        if changed == 0:
            print(f"[RialPay] process_verified: payment {payment_id} lock lost (already processing/completed)")
            return {"status": "already_processed"}
    except Exception as _le:
        print(f"[RialPay] process_verified: lock error payment {payment_id}: {_le}")
        return {"status": "already_processed"}

    # ── Persist audit data ────────────────────────────────────────────────────
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE payments SET raw_callback=?, callback_received_at=?,"
                " gateway_ref=COALESCE(NULLIF(?, ''), gateway_ref),"
                " external_txid=COALESCE(NULLIF(?, ''), external_txid)"
                " WHERE id=?",
                (raw_payload_str, now_str(), gateway_ref or "", external_txid or "", payment_id),
            )
    except Exception:
        pass

    print(f"[RialPay] process_verified: LOCKED payment {payment_id} source={source}"
          f" kind={payment['kind']} uid={payment['user_id']} amount={payment['amount']}")

    kind   = payment["kind"]
    uid    = payment["user_id"]
    amount = payment["amount"]

    try:
        if kind == "wallet_charge":
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
                    " WHERE id=? AND status='processing'",
                    (now_str(), now_str(), payment_id),
                )
            update_balance(uid, amount)
            try:
                apply_gateway_bonus_if_needed(uid, "rialpay", amount)
            except Exception:
                pass
            try:
                bot.send_message(
                    uid,
                    f"✅ پرداخت ریال‌پی تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(amount)} تومان",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        else:
            # config_purchase / renewal / pnlcfg_renewal
            _fulfill_rialpay_non_wallet(payment_id, kind, uid, amount, payment)

        return {"status": "ok"}

    except Exception as exc:
        _tb.print_exc()
        print(f"[RialPay] process_verified: fulfillment error payment {payment_id}: {exc}")
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE payments SET status='pending' WHERE id=? AND status='processing'",
                    (payment_id,),
                )
        except Exception:
            pass
        return {"status": "error", "msg": str(exc)}


def _fulfill_rialpay_non_wallet(payment_id: int, kind: str, uid: int, amount: int, payment):
    """Fulfil a locked (status=processing) non-wallet RialPay payment."""
    from ..db import (
        complete_payment, get_package, get_purchase, get_conn,
        get_payment_service_names, now_str,
    )
    from ..helpers import now_str as _now_str
    from ..payments import apply_gateway_bonus_if_needed
    from ..bot_instance import bot

    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=?"
            " WHERE id=? AND status='processing'",
            (now_str(), now_str(), payment_id),
        )

    if kind == "config_purchase":
        from ..handlers.callbacks import _deliver_bulk_configs, _send_bulk_delivery_result
        pkg_row = get_package(payment["package_id"])
        qty = int(payment["quantity"]) if "quantity" in payment.keys() else 1
        try:
            bot.send_message(
                uid,
                "✅ پرداخت ریال‌پی تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                parse_mode="HTML",
            )
        except Exception:
            pass
        snames = get_payment_service_names(payment_id)
        purchase_ids, pending_ids = _deliver_bulk_configs(
            uid, uid, payment["package_id"], amount, "rialpay", qty, payment_id,
            service_names=snames,
        )
        try:
            apply_gateway_bonus_if_needed(uid, "rialpay", amount)
        except Exception:
            pass
        _send_bulk_delivery_result(uid, uid, pkg_row, purchase_ids, pending_ids, "ریال‌پی")

    elif kind == "renewal":
        from ..db import get_conn as _gc
        from ..ui.notifications import admin_renewal_notify
        pkg_row   = get_package(payment["package_id"])
        config_id = payment["config_id"]
        with _gc() as conn:
            row = conn.execute(
                "SELECT purchase_id FROM configs WHERE id=?", (config_id,)
            ).fetchone()
        purchase_id = row["purchase_id"] if row else 0
        item = get_purchase(purchase_id) if purchase_id else None
        try:
            bot.send_message(
                uid,
                "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                "🔄 درخواست تمدید سرویس شما با موفقیت ثبت و برای پشتیبانی ارسال شد.\n"
                "⏳ لطفاً کمی صبر کنید، پس از انجام تمدید به شما اطلاع داده خواهد شد.\n\n"
                "🙏 از صبر و شکیبایی شما متشکریم.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        if item and pkg_row:
            admin_renewal_notify(uid, item, pkg_row, amount, "ریال‌پی")
        try:
            apply_gateway_bonus_if_needed(uid, "rialpay", amount)
        except Exception:
            pass

    elif kind == "pnlcfg_renewal":
        from ..handlers.callbacks import _execute_pnlcfg_renewal
        config_id  = payment["config_id"]
        package_id = payment["package_id"]
        ok_r, err_r = _execute_pnlcfg_renewal(config_id, package_id, uid=uid)
        if ok_r:
            try:
                bot.send_message(
                    uid,
                    "✅ <b>تمدید سرویس انجام شد!</b>\n\n"
                    "🔄 پرداخت شما تأیید و سرویس با موفقیت تمدید شد.\n\n"
                    "🙏 از اعتماد شما سپاسگزاریم.",
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
            apply_gateway_bonus_if_needed(uid, "rialpay", amount)
        except Exception:
            pass
