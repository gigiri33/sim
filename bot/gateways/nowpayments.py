# -*- coding: utf-8 -*-
"""
NowPayments crypto payment gateway.
API docs: https://documenter.getpostman.com/view/7907941/S1a32n38

Auth: ``x-api-key`` header.
IPN signature: HMAC-SHA512 over JSON body with keys sorted alphabetically.
"""
import hashlib
import hmac
import json
import os

import requests

from ..db import setting_get
from .crypto import fetch_crypto_prices

NOWPAYMENTS_BASE_URL = "https://api.nowpayments.io/v1"

# Cached auto-detected public IP (per-process)
_CACHED_PUBLIC_IP: str | None = None


def normalize_bot_username(bot_username: str) -> str:
    """Strip leading @ from bot username."""
    return bot_username.lstrip("@")


def detect_public_ip() -> str:
    """
    Auto-detect this server's public IPv4 address.
    Tries multiple providers for robustness. Result is cached per-process.
    Returns empty string on failure.
    """
    global _CACHED_PUBLIC_IP
    if _CACHED_PUBLIC_IP:
        return _CACHED_PUBLIC_IP
    for url in (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://api.my-ip.io/ip",
        "https://ipv4.icanhazip.com",
    ):
        try:
            r = requests.get(url, timeout=5)
            ip = (r.text or "").strip()
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                _CACHED_PUBLIC_IP = ip
                return ip
        except Exception:
            continue
    return ""


def get_nowpayments_webhook_port() -> str:
    """Resolve webhook port: env var (NOWPAYMENTS_WEBHOOK_PORT) > DB setting > shared with Plisio (5050)."""
    p = (os.getenv("NOWPAYMENTS_WEBHOOK_PORT", "") or "").strip()
    if not p:
        p = (setting_get("nowpayments_webhook_port", "") or "").strip()
    if not p or not p.isdigit():
        # Default: same port as Plisio so a single Flask app can serve both.
        p = (os.getenv("PLISIO_WEBHOOK_PORT", "") or "").strip()
        if not p:
            p = (setting_get("plisio_webhook_port", "") or "").strip()
        if not p or not p.isdigit():
            p = "5050"
    return p


def get_effective_public_base_url() -> str:
    """
    Return the base URL to use for NowPayments callbacks.
    Priority:
      1. ``server_public_url`` setting (shared with Plisio, if admin set one)
      2. Auto-detected ``http://<public_ip>:<webhook_port>``
    Returns empty string if neither is available.
    """
    base = (setting_get("server_public_url", "") or "").strip().rstrip("/")
    if base:
        return base
    ip = detect_public_ip()
    if not ip:
        return ""
    port = get_nowpayments_webhook_port()
    return f"http://{ip}:{port}"


def get_nowpayments_callback_urls(bot_username: str) -> dict:
    """Build callback URLs for a NowPayments invoice."""
    base = get_effective_public_base_url()
    if not base:
        return {}
    slug = normalize_bot_username(bot_username)
    return {
        "ipn_callback_url": f"{base}/nowpayments/{slug}/callback",
        "success_url":      f"{base}/nowpayments/{slug}/success",
        "cancel_url":       f"{base}/nowpayments/{slug}/cancel",
    }


def _api_headers() -> dict:
    api_key = (setting_get("nowpayments_api_key", "") or "").strip()
    return {"x-api-key": api_key, "Content-Type": "application/json"}


def get_nowpayments_min_usdt() -> float:
    """Query NowPayments live minimum amount for USD→USDT-TRC20. Falls back to 5.0."""
    api_key = (setting_get("nowpayments_api_key", "") or "").strip()
    if not api_key:
        return 5.0
    try:
        resp = requests.get(
            f"{NOWPAYMENTS_BASE_URL}/min-amount",
            params={"currency_from": "usd", "currency_to": "usdttrc20"},
            headers={"x-api-key": api_key},
            timeout=10,
        )
        data = resp.json()
        # API returns {"currency_from":"usd","currency_to":"usdttrc20","min_amount":X}
        amt = float(data.get("min_amount") or 0)
        if amt > 0:
            return amt
    except Exception:
        pass
    return 5.0


def create_nowpayments_invoice(amount_toman: int, payment_id, user_id, bot_username: str, description: str):
    """
    Create a new NowPayments invoice.

    Converts *amount_toman* to USD using the live USDT/IRT rate (USDT≈USD),
    then POSTs to ``/v1/invoice``.

    Returns:
        ``(True,  {"invoice_id": ..., "invoice_url": ..., "amount_usdt": ..., "usdt_rate": ...})``  on success
        ``(False, {"error": ...})``                                                                 on failure
    """
    api_key = (setting_get("nowpayments_api_key", "") or "").strip()
    if not api_key:
        return False, {"error": "کلید API NowPayments ثبت نشده است."}

    prices = fetch_crypto_prices()
    usdt_irt = prices.get("USDT", 0)
    if not usdt_irt or usdt_irt <= 0:
        return False, {"error": "دریافت نرخ USDT ناموفق بود. لطفاً مجدداً تلاش کنید."}

    amount_usdt = round(amount_toman / usdt_irt, 4)

    # Enforce NowPayments minimum (queried live, fallback 5 USDT)
    min_usdt = get_nowpayments_min_usdt()
    if amount_usdt < min_usdt:
        min_toman = int(min_usdt * usdt_irt)
        from ..helpers import fmt_price
        return False, {"error": (
            f"حداقل مبلغ پرداخت از طریق NowPayments برابر {min_usdt:.2f} USDT "
            f"(معادل {fmt_price(min_toman)} تومان) است.\n"
            "لطفاً درگاه دیگری انتخاب کنید یا مبلغ را افزایش دهید."
        )}

    pay_currency = ((setting_get("nowpayments_pay_currency", "") or "") or "usdttrc20").strip().lower()

    body = {
        "price_amount":      amount_usdt,
        "price_currency":    "usd",
        "pay_currency":      pay_currency,
        "order_id":          str(payment_id),
        "order_description": (description or "")[:200],
        "is_fee_paid_by_user": False,
    }
    urls = get_nowpayments_callback_urls(bot_username)
    if urls:
        body["ipn_callback_url"] = urls["ipn_callback_url"]
        body["success_url"]      = urls["success_url"]
        body["cancel_url"]       = urls["cancel_url"]

    try:
        resp = requests.post(
            f"{NOWPAYMENTS_BASE_URL}/invoice",
            headers=_api_headers(),
            data=json.dumps(body),
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        return False, {"error": str(exc)}

    invoice_id  = str(data.get("id") or "")
    invoice_url = data.get("invoice_url") or ""
    if not invoice_id or not invoice_url:
        msg = data.get("message") or data.get("error") or str(data)
        return False, {"error": msg[:400]}

    return True, {
        "invoice_id":  invoice_id,
        "invoice_url": invoice_url,
        "amount_usdt": amount_usdt,
        "usdt_rate":   usdt_irt,
    }


def check_nowpayments_invoice(invoice_id: str):
    """
    Look up the latest payment status associated with a NowPayments invoice.

    NowPayments doesn't expose a direct invoice-status endpoint; instead we
    list payments filtered by ``invoiceId``.

    Returns:
        ``(True,  status_str)``  — status from the most recent associated payment,
                                    or ``""`` if no payment yet (still waiting).
        ``(False, None)``        — API/network error.
    """
    api_key = (setting_get("nowpayments_api_key", "") or "").strip()
    if not api_key or not invoice_id:
        return False, None
    try:
        resp = requests.get(
            f"{NOWPAYMENTS_BASE_URL}/payment/",
            params={"limit": 10, "invoiceId": invoice_id},
            headers={"x-api-key": api_key},
            timeout=10,
        )
        data = resp.json()
    except Exception as exc:
        print(f"[NowPayments check_invoice] request error: {exc}")
        return False, None

    items = data.get("data") if isinstance(data, dict) else None
    if not items:
        # No payment created yet → user hasn't paid; treat as waiting.
        return True, ""

    # Pick the most "advanced" status (paid > pending > failed) so a partial
    # confirmation isn't masked by an earlier failed attempt.
    rank = {
        "finished":       100,
        "confirmed":       90,
        "sending":         80,
        "partially_paid":  70,
        "confirming":      60,
        "waiting":         50,
        "expired":         20,
        "failed":          10,
        "refunded":         5,
    }
    best_status = ""
    best_rank   = -1
    for it in items:
        st = (it.get("payment_status") or "").lower()
        r  = rank.get(st, 0)
        if r > best_rank:
            best_rank   = r
            best_status = st
    return True, best_status


def verify_nowpayments_signature(raw_body: bytes, header_signature: str) -> bool:
    """
    Verify NowPayments IPN signature.

    Per NowPayments docs, the signature is computed as:
        HMAC-SHA512(IPN_SECRET, json_encode(ksort(decoded_body)))

    Python equivalent: ``json.dumps(data, sort_keys=True, separators=(',', ':'))``
    (sort_keys recursively sorts nested dicts too).

    Returns ``True`` if signature is valid.
    """
    ipn_secret = (setting_get("nowpayments_ipn_secret", "") or "").strip()
    if not ipn_secret or not header_signature:
        return False
    try:
        data = json.loads(raw_body.decode("utf-8") if isinstance(raw_body, (bytes, bytearray)) else raw_body)
    except Exception:
        return False
    sorted_msg = json.dumps(data, sort_keys=True, separators=(",", ":"))
    expected   = hmac.new(ipn_secret.encode(), sorted_msg.encode("utf-8"), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, header_signature.strip())


def is_nowpayments_paid(status: str) -> bool:
    """Return True when the payment is effectively credited.

    ``finished`` — fully credited to merchant.
    ``confirmed`` / ``sending`` — confirmed on chain; safe to fulfill.
    """
    return status in ("finished", "confirmed", "sending")


def is_nowpayments_pending(status: str) -> bool:
    """Return True when the payment is still being processed."""
    return status in ("waiting", "confirming", "partially_paid", "")


def is_nowpayments_failed(status: str) -> bool:
    """Return True when the payment failed/expired/was refunded."""
    return status in ("failed", "expired", "refunded")
