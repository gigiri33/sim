# -*- coding: utf-8 -*-
"""
SwapWallet Crypto payment gateway — temporary-wallet invoice via v2 API.
POST /v2/payment/{username}/invoices/temporary-wallet
"""
import json
import urllib.request
import urllib.parse
import urllib.error

from ..config import SWAPWALLET_BASE_URL
from ..db import setting_get
from ..helpers import fmt_price, esc
from ..bot_instance import bot
from telebot import types

# شبکه‌های پشتیبانی‌شده و توکن پیش‌فرض آن‌ها
SWAPWALLET_CRYPTO_NETWORKS = [
    ("TRON", "USDT"),
    ("TON",  "TON"),
    ("BSC",  "USDT"),
]

NETWORK_LABELS = {
    "TRON": "🔵 ترون (USDT-TRC20)",
    "TON":  "💎 تون (TON)",
    "BSC":  "🟡 بایننس (USDT-BEP20)",
}


def _get_credentials():
    api_key  = setting_get("swapwallet_crypto_api_key", "").strip()
    username = setting_get("swapwallet_crypto_username", "").strip()
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    if username.startswith("@"):
        username = username[1:].strip()
    return api_key, username


def create_swapwallet_crypto_invoice(amount_toman, order_id, network, description="پرداخت"):
    """ایجاد فاکتور کریپتو با کیف پول موقت.
    Returns (True, result_dict) or (False, {"error": "..."})
    """
    api_key, username = _get_credentials()
    if not username:
        return False, {"error": "نام کاربری فروشگاه SwapWallet (کریپتو) تنظیم نشده است."}
    if not api_key:
        return False, {"error": "کلید API SwapWallet (کریپتو) تنظیم نشده است."}

    # توکن مجاز بر اساس شبکه
    allowed_token = "TON" if network == "TON" else "USDT"

    payload = json.dumps({
        "amount":      {"number": str(int(amount_toman)), "unit": "IRT"},
        "network":     network,
        "allowedToken": allowed_token,
        "ttl":         3600,
        "orderId":     str(order_id),
        "description": str(description),
    }, ensure_ascii=False).encode("utf-8")

    safe_user = urllib.parse.quote(username, safe="")
    url = f"{SWAPWALLET_BASE_URL}/v2/payment/{safe_user}/invoices/temporary-wallet"
    headers = {
        "Content-Type":  "application/json; charset=utf-8",
        "Authorization": f"Bearer {api_key}",
        "User-Agent":    "ConfigFlow/1.0",
        "Accept":        "application/json",
    }
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "OK" and data.get("result", {}).get("id"):
            return True, data["result"]
        return False, {"error": str(data)}
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            msg = err_data.get("message") or err_data.get("error") or str(err_data)[:200]
        except Exception:
            msg = f"HTTP {e.code}: {e.reason}"
        return False, {"error": msg}
    except Exception as e:
        return False, {"error": str(e)}


def check_swapwallet_crypto_invoice(invoice_id):
    """بررسی وضعیت فاکتور کریپتو.
    Returns (True, result_dict) or (False, {"error": "..."})
    """
    api_key, username = _get_credentials()
    if not username:
        return False, {"error": "نام کاربری فروشگاه SwapWallet (کریپتو) تنظیم نشده است."}
    safe_user = urllib.parse.quote(username, safe="")
    safe_inv  = urllib.parse.quote(str(invoice_id), safe="")
    url = f"{SWAPWALLET_BASE_URL}/v2/payment/{safe_user}/invoices/{safe_inv}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent":    "ConfigFlow/1.0",
        "Accept":        "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "OK":
            return True, data.get("result", data)
        return False, {"error": str(data)}
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            msg = err_data.get("message") or err_data.get("error") or str(err_data)[:200]
        except Exception:
            msg = f"HTTP {e.code}: {e.reason}"
        return False, {"error": msg}
    except Exception as e:
        return False, {"error": str(e)}


def show_swapwallet_crypto_page(call, *, amount_toman, invoice_id, result, payment_id, verify_cb):
    """نمایش صفحه پرداخت کریپتو SwapWallet."""
    from ..ui.helpers import send_or_edit

    wallet_address = result.get("walletAddress", "")
    links          = result.get("links", [])
    amount_obj     = result.get("amount", {})
    usd_val        = amount_obj.get("usdValue", {})
    user_currency  = amount_obj.get("userCurrencyValue", {})
    expired_at     = result.get("expiredAt", "")

    # مبلغ معادل ارزی
    usd_text = ""
    if usd_val.get("number"):
        usd_text = f"\n💱 معادل: <b>{usd_val['number']} {usd_val.get('unit','')}</b>"

    short_id = invoice_id.replace("-", "")[:10] if invoice_id else "---"

    text = (
        "💎 <b>پرداخت کریپتو (SwapWallet)</b>\n\n"
        f"🛒 کد پیگیری: <code>{short_id}</code>\n"
        f"💰 مبلغ: <b>{fmt_price(amount_toman)}</b> تومان"
        f"{usd_text}\n\n"
    )
    if wallet_address:
        text += f"📋 آدرس کیف پول:\n<code>{esc(wallet_address)}</code>\n\n"
    text += (
        "ℹ️ <i>در صورت موجود بودن آن ارز در کیف پول سواپ ولت شما، مبلغ از کیف پول کسر می‌شود؛ در غیر این صورت پرداخت به‌صورت ریالی انجام خواهد شد.</i>\n\n"
        "❌ این فاکتور <b>۱ ساعت</b> اعتبار دارد\n"
        "پس از واریز، دکمه «✅ بررسی پرداخت» را بزنید."
    )

    kb = types.InlineKeyboardMarkup()
    for link in links:
        name    = link.get("name", "")
        url     = link.get("url", "")
        if not url:
            continue
        if name == "SWAP_WALLET":
            kb.add(types.InlineKeyboardButton("💳 پرداخت در SwapWallet", url=url))
        elif name == "TRUST_WALLET":
            kb.add(types.InlineKeyboardButton("🔒 Trust Wallet", url=url))
        else:
            kb.add(types.InlineKeyboardButton(f"🔗 {name}", url=url))
    kb.add(types.InlineKeyboardButton("✅ بررسی پرداخت", callback_data=verify_cb))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="nav:main"))

    send_or_edit(call, text, kb)
