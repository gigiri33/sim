# -*- coding: utf-8 -*-
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  درگاه پرداخت RialPay — ساخت فاکتور + وبهوک
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

اطلاعات تماس:
  💎 کانال اطلاع‌رسانی : @Rialpays
  💎 پشتیبانی مجموعه  : @RialSupport
  🤖 ربات               : @RialPayBot

──────────────────────────────────────────────
  تنظیمات پنل ادمین
──────────────────────────────────────────────
• rialpay_api_key          → کلید API که از پنل ریال‌پی دریافت می‌کنید
• rialpay_webhook_secret   → کلید مخفی برای اعتبارسنجی امضای وبهوک (اختیاری)
• rialpay_create_invoice_url → آدرس API ساخت فاکتور (پیش‌فرض: https://rialbotapi.shop/api/create_invoice.php)
• rialpay_callback_base_url → آدرس پایه وبهوک؛ اگر خالی باشد از server_public_url استفاده می‌شود

──────────────────────────────────────────────
  فرمت Callback URL (در پنل ریال‌پی وارد کنید)
──────────────────────────────────────────────
  https://<دامین‌شما>/rialpay/<یوزرنیم‌ربات>/{payment_id}/webhook

  مثال:
    https://bot.example.com/rialpay/MyShopBot/{payment_id}/webhook

  نکات:
  ─ به جای {payment_id} عدد واقعی سفارش قرار می‌گیرد (به‌صورت خودکار)
  ─ <یوزرنیم‌ربات> را بدون @ وارد کنید (مثلاً: MyShopBot)
  ─ در سرورهای چندربات، یوزرنیم باید دقیقاً با یوزرنیم ربات مربوطه یکسان باشد
    تا وبهوک به ربات اشتباه نرسد
──────────────────────────────────────────────
"""

import json
import hmac
import hashlib
import re
import urllib.parse
import urllib.request
import urllib.error

from ..db import setting_get


RIALPAY_DEFAULT_CREATE_URL = "https://rialbotapi.shop/api/create_invoice.php"
RIALPAY_DEFAULT_CHECK_URL = "https://rialbotapi.shop/api/invoicetest.php"


def _extract_token_from_link(link: str) -> str:
    """Extract RialPay invoice token from links like t.me/Rialpaybot?start=inv_<token>."""
    link = str(link or "").strip()
    if not link:
        return ""
    try:
        parsed = urllib.parse.urlparse(link)
        qs = urllib.parse.parse_qs(parsed.query or "")
        start = (qs.get("start") or [""])[0]
        if start:
            return start[4:] if start.startswith("inv_") else start
    except Exception:
        pass
    m = re.search(r"(?:start=|/)inv_([A-Za-z0-9_-]+)", link)
    if m:
        return m.group(1)
    m = re.search(r"inv_([A-Za-z0-9_-]+)", link)
    return m.group(1) if m else ""


def _pick_first(data: dict, keys: tuple) -> str:
    """Return the first non-empty value from a dict as string."""
    for key in keys:
        val = data.get(key)
        if val not in (None, ""):
            return str(val).strip()
    return ""


def get_rialpay_callback_base_url() -> str:
    """Return the base URL for RialPay webhook callbacks."""
    dedicated = (setting_get("rialpay_callback_base_url", "") or "").strip().rstrip("/")
    if dedicated and (dedicated.startswith("https://") or dedicated.startswith("http://")):
        return dedicated
    # fallback to server_public_url
    base = (setting_get("server_public_url", "") or "").strip().rstrip("/")
    if base and (base.startswith("https://") or base.startswith("http://")):
        return base
    return ""


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

    print(f"[RialPay] create_invoice → POST {create_url} | order_id={order_id} amount={amount_toman} callback={callback_url!r}")

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
        link = _pick_first(data, (
            "link", "payment_url", "pay_url", "url", "invoice_url", "payment_link",
        ))
        token = _pick_first(data, (
            "token", "invoice_token", "invoiceToken", "transaction_token", "hash",
        ))
        if not token:
            token = _extract_token_from_link(link)
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
            "error":  f"ریال‌پی پاسخ ناقص برگرداند (توکن یا لینک پرداخت خالی است): {raw[:300]}",
            "raw":    data,
        }

    err_msg = _extract_error(data) or raw[:300]
    print(f"[RialPay] create_invoice FAILED order_id={order_id}: status={api_status!r} raw={raw[:400]}")
    return False, {"status": "error", "error": f"ساخت فاکتور ریال‌پی ناموفق بود: {err_msg}\n\nپاسخ سرور: {raw[:200]}", "raw": data}


def check_rialpay_invoice_status(token: str) -> dict:
    """
    Query RialPay invoice status via invoicetest.php.

    POST token=<token>

    Returns one of:
      {"status": "paid",    "seller_receive": int, "invoice_id": ..., "raw": {...}}
      {"status": "pending", "raw": {...}}
      {"status": "rejected","raw": {...}}
      {"status": "error",   "error": str}
    """
    import urllib.parse as _up
    if not token:
        return {"status": "error", "error": "توکن فاکتور خالی است."}

    check_url = (setting_get("rialpay_check_invoice_url", "") or RIALPAY_DEFAULT_CHECK_URL).strip()
    form = _up.urlencode({"token": token}).encode("utf-8")
    req  = urllib.request.Request(
        check_url,
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept":       "application/json, */*",
            "User-Agent":   "ConfigFlow/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw_text, parsed = _decode_response_body(resp)
    except Exception as e:
        print(f"[RialPay] check_invoice_status error: {e}")
        return {"status": "error", "error": f"خطا در اتصال به ریال‌پی: {e}"}

    print(f"[RialPay] check_invoice_status token={token[:12]}… → {raw_text[:300]}")

    if not isinstance(parsed, dict):
        return {"status": "error", "error": f"پاسخ نامعتبر: {raw_text[:200]}"}

    api_ok = str(parsed.get("status") or "").lower() in ("ok", "true", "1", "success")
    if not api_ok:
        return {"status": "error", "error": _extract_error(parsed) or raw_text[:200]}

    invoice_status = str(parsed.get("invoice_status") or "").strip().lower()
    raw_status     = parsed.get("raw_status")
    raw_status_s   = str(raw_status).strip().lower()

    # raw_status: 0=pending, 1=paid (confirmed by support)
    if raw_status_s in ("1", "paid", "success", "completed", "successful") or invoice_status in ("paid", "success", "completed", "successful"):
        return {
            "status":         "paid",
            "seller_receive": parsed.get("seller_receive"),
            "invoice_id":     parsed.get("invoice_id"),
            "raw":            parsed,
        }
    if raw_status_s in ("-1", "2", "rejected", "failed", "cancelled", "canceled", "cancel") or invoice_status in ("rejected", "failed", "cancelled", "canceled", "cancel"):
        return {"status": "rejected", "raw": parsed}

    # default: pending
    return {"status": "pending", "raw": parsed}


def verify_rialpay_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verify RialPay webhook sign field using HMAC-SHA256.
    RialPay computes: hmac_sha256(key=secret, msg=invoice_id)
    The sign comes as a POST form field, not a header.
    This function is kept for compatibility but use verify_rialpay_sign() directly.
    """
    # Delegate to the form-field based verifier (signature here is the sign field value)
    return verify_rialpay_sign(invoice_id=None, sign=signature, raw_body=raw_body)


def verify_rialpay_sign(invoice_id, sign: str, raw_body: bytes = None) -> bool:
    """
    Verify RialPay's sign field: hmac_sha256(key=secret, msg=str(invoice_id))
    If secret is not configured, skip verification (accept all).
    """
    secret = (setting_get("rialpay_webhook_secret", "") or "").strip()
    if not secret:
        print("[RialPay] webhook sign check SKIPPED: no secret configured.")
        return True
    if not sign:
        print("[RialPay] webhook sign check SKIPPED: no sign provided.")
        return True
    if invoice_id is None:
        # Can't verify without invoice_id
        print("[RialPay] webhook sign check SKIPPED: no invoice_id.")
        return True
    expected = hmac.new(
        secret.encode("utf-8"),
        str(invoice_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    result = hmac.compare_digest(expected, str(sign).strip())
    if not result:
        print(f"[RialPay] webhook sign INVALID invoice_id={invoice_id} sign={sign!r}")
    return result


def normalize_rialpay_status(status: str) -> str:
    """
    Normalise a RialPay status string to one of:
      "paid" | "rejected" | "pending" | "unknown"
    """
    s = str(status or "").strip().lower()
    if s in ("paid", "success", "completed", "true", "1", "ok", "successful"):
        return "paid"
    if s in ("rejected", "failed", "cancel", "cancelled", "canceled", "false", "0", "error"):
        return "rejected"
    if s in ("pending", "waiting", "unpaid"):
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
                # Use gateway_ref (RialPay's actual invoice amount) if available,
                # otherwise fall back to DB amount with generous tolerance (20%)
                expected_str = (payment["gateway_ref"] or "").strip() if payment["gateway_ref"] else ""
                if expected_str:
                    try:
                        expected = int(float(expected_str))
                    except Exception:
                        expected = payment["amount"]
                else:
                    expected = payment["amount"]
                tolerance = max(int(expected * 0.20), 500)
                if abs(ext_amount_int - expected) > tolerance:
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
