# -*- coding: utf-8 -*-
"""
Payment logic: pricing, gateway selection UI, payment-to-admins dispatch,
card payment approval and rejection.
"""
from telebot import types
import json

import threading as _threading

from .config import ADMIN_IDS, CRYPTO_COINS, CRYPTO_API_SYMBOLS, CRYPTO_EMOJI_IDS
from .db import (
    get_user, get_payment, get_package, get_agency_price,
    get_agency_price_config, get_agency_type_discount,
    approve_payment, reject_payment, complete_payment,
    update_balance, reserve_first_config, release_reserved_config,
    assign_config_to_user, get_conn, create_pending_order, get_purchase,
    get_all_admin_users,
    save_payment_admin_message, get_payment_admin_messages, delete_payment_admin_messages,
    get_per_gb_price, get_payment_service_names,
)
from .helpers import esc, fmt_price, display_username, back_button, now_str
import time
import random
import string

# ── In-memory idempotency guard ────────────────────────────────────────────────
# Prevents concurrent or duplicate processing of the same payment_id when
# the admin has a weak network and Telegram retries the callback, or two
# admins tap approve simultaneously.
_pay_lock   = _threading.Lock()
_pay_in_fly: set = set()   # payment IDs currently being processed
from .gateways.base import is_gateway_available, is_card_info_complete, get_gateway_range_text, is_gateway_in_range, build_gateway_range_guide
from .gateways.base import get_gateway_bonus_amount as _gw_bonus_amt
from .gateways.crypto import fetch_crypto_prices
from .bot_instance import bot
from .ui.helpers import send_or_edit
from .ui.keyboards import _btn, _raw_markup
from .ui.premium_emoji import ce
from .group_manager import send_to_topic, send_photo_to_topic, get_group_id

# ── Gateway label display for bonus text ──────────────────────────────────────
_GW_DISPLAY_NAMES = {
    "card":              "کارت به کارت",
    "crypto":            "ارز دیجیتال",
    "tetrapay":          "TetraPay",
    "swapwallet_crypto": "SwapWallet",
    "tronpays_rial":     "TronPays",
    "tronado":           "ترونادو",
    "centralpay":        "درگاه کارت به کارت (CentralPay)",
    "rialpay":           "درگاه کارت به کارت (Rialpays)",
}


def apply_gateway_bonus_if_needed(user_id: int, gw_name: str, payment_amount: int) -> int:
    """Credit wallet bonus and notify user if this gateway has a bonus configured.

    Returns the bonus amount credited (0 if none).
    This function is intentionally side-effect-free when bonus is not enabled.
    """
    from .db import get_gateway_bonus_amount, update_balance
    bonus = get_gateway_bonus_amount(gw_name, payment_amount)
    if bonus <= 0:
        return 0
    update_balance(user_id, bonus)
    gw_display = _GW_DISPLAY_NAMES.get(gw_name, gw_name)
    try:
        bot.send_message(
            user_id,
            f"🎁 <b>هدیه پرداخت</b>\n\n"
            f"به دلیل پرداخت از طریق درگاه <b>{gw_display}</b>، "
            f"مبلغ <b>{fmt_price(bonus)} تومان</b> به عنوان هدیه به کیف پول شما اضافه شد. 🎉",
            parse_mode="HTML",
        )
    except Exception:
        pass
    return bonus

# ── Price cache (60 s TTL) — both selection and payment info share the same data
_PRICES_CACHE: dict = {}
_PRICES_CACHE_TS: float = 0.0


def _get_prices() -> dict:
    global _PRICES_CACHE, _PRICES_CACHE_TS
    if time.time() - _PRICES_CACHE_TS < 60 and _PRICES_CACHE:
        return _PRICES_CACHE
    data = fetch_crypto_prices()
    if data:
        _PRICES_CACHE    = data
        _PRICES_CACHE_TS = time.time()
    return _PRICES_CACHE


# ── Pricing ────────────────────────────────────────────────────────────────────
def calculate_effective_order_price(user_id, package_row, quantity=1):
    """
    Returns a dict with:
      original_unit_price  – package base price
      unit_price           – effective price per unit after reseller discount
      quantity             – quantity requested
      subtotal             – unit_price * quantity
      discount_amount      – total discount vs original (0 for regular users)
      final_amount         – same as subtotal (kept as alias)
      pricing_mode         – 'normal'|'global_pct'|'global_fixed'|'type_pct'|'type_fixed'|'package'|'per_gb'
    """
    base = package_row["price"]
    user = get_user(user_id)
    if not user or not user["is_agent"]:
        subtotal = base * quantity
        return {
            "original_unit_price": base,
            "unit_price": base,
            "quantity": quantity,
            "subtotal": subtotal,
            "discount_amount": 0,
            "final_amount": subtotal,
            "pricing_mode": "normal",
        }

    cfg  = get_agency_price_config(user_id)
    mode = cfg["price_mode"]

    if mode == "global":
        g_type = cfg["global_type"]
        g_val  = cfg["global_val"]
        if g_type == "pct":
            unit_price = max(0, base - round(base * g_val / 100))
            pricing_mode = "global_pct"
        else:
            unit_price = max(0, base - g_val)
            pricing_mode = "global_fixed"
    elif mode == "type":
        type_id = package_row["type_id"]
        td = get_agency_type_discount(user_id, type_id)
        if td:
            if td["discount_type"] == "pct":
                unit_price = max(0, base - round(base * td["discount_value"] / 100))
                pricing_mode = "type_pct"
            else:
                unit_price = max(0, base - td["discount_value"])
                pricing_mode = "type_fixed"
        else:
            unit_price = base
            pricing_mode = "type_fixed"
    elif mode == "per_gb":
        type_id = package_row["type_id"]
        pgb = get_per_gb_price(user_id, type_id)
        if pgb is not None:
            volume_gb = (package_row["volume_gb"] or 0)
            unit_price = max(0, int(pgb * volume_gb))
            pricing_mode = "per_gb"
        else:
            unit_price = base
            pricing_mode = "normal"
    else:  # package (default)
        ap = get_agency_price(user_id, package_row["id"])
        unit_price = ap if ap is not None else base
        pricing_mode = "package"

    subtotal = unit_price * quantity
    discount_amount = (base - unit_price) * quantity
    return {
        "original_unit_price": base,
        "unit_price": unit_price,
        "quantity": quantity,
        "subtotal": subtotal,
        "discount_amount": max(0, discount_amount),
        "final_amount": subtotal,
        "pricing_mode": pricing_mode,
    }


def get_effective_price(user_id, package_row):
    """Return discounted price for agents, else regular price."""
    return calculate_effective_order_price(user_id, package_row)["unit_price"]


# ── Payment method selection ───────────────────────────────────────────────────
def show_payment_method_selection(target, uid, context_data):
    """
    context_data must contain:
      'kind': 'wallet_charge' or 'config_purchase'
      'amount': int
    """
    amount = context_data["amount"]

    _gw_labels = []
    rows = []
    from .db import setting_get as _sg

    # Gateway emoji mapping: gateway_key -> (default_label, emoji_id)
    _GW_DEFAULTS = {
        "card":              ("کارت به کارت",                                "5796315849241403403"),
        "crypto":            ("ارز دیجیتال",                                 "5794002949222964817"),
        "tetrapay":          ("درگاه کارت به کارت (TetraPay)",              "5796315849241403403"),
        "swapwallet_crypto": ("درگاه کارت به کارت و ارز دیجیتال (SwapWallet)", "5796315849241403403"),
        "tronpays_rial":     ("درگاه کارت به کارت (TronPay)",               "5796315849241403403"),
        "tronado":           ("درگاه ترونادو",                              "5796315849241403403"),
        "rialpay":           ("درگاه کارت به کارت (Rialpays)",                               "5796315849241403403"),
    }

    def _add_gw(key, cb, extra_check=True):
        if not (is_gateway_available(key, uid) and extra_check):
            return
        default_lbl, eid = _GW_DEFAULTS[key]
        custom_lbl = _sg(f"gw_{key}_display_name", "").strip()
        lbl = custom_lbl or default_lbl
        # Show bonus hint if this gateway has a bonus configured
        bonus = _gw_bonus_amt(key, amount)
        if bonus > 0:
            lbl += f" ({fmt_price(bonus)} هدیه 🎁)"
        rows.append([_btn(lbl, callback_data=cb, emoji_id=eid)])
        _gw_labels.append((key, lbl))

    _add_gw("card", "pm:card", is_card_info_complete())
    _add_gw("crypto", "pm:crypto")
    _add_gw("tetrapay", "pm:tetrapay")
    _add_gw("swapwallet_crypto", "pm:swapwallet_crypto")
    _add_gw("tronpays_rial", "pm:tronpays_rial")
    _add_gw("tronado", "pm:tronado")
    _add_gw("rialpay", "pm:rialpay")

    rows.append([_btn("بازگشت", callback_data="wallet:menu", emoji_id="5352759161945867747")])
    kb = _raw_markup(rows)

    user       = get_user(uid)
    agent_note = f"\n\n{ce('🤝', '5415963453997214172')} <i>این قیمت‌ها مخصوص همکاری شماست</i>" if user and user["is_agent"] else ""
    _range_guide = build_gateway_range_guide(_gw_labels)
    send_or_edit(
        target,
        f"{ce('💳', '5406865085471663921')} <b>انتخاب روش پرداخت</b>\n\n"
        f"{ce('💰', '5318912792428814144')} مبلغ: <b>{fmt_price(amount)}</b> تومان{agent_note}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "روش پرداخت را انتخاب کنید:",
        kb
    )


# ── Crypto UI ──────────────────────────────────────────────────────────────────
def show_crypto_selection(target, amount=None, back_cb="pm:back"):
    from .db import setting_get
    rows   = []
    prices = _get_prices() if amount else {}
    has_any = False
    for coin_key, coin_label in CRYPTO_COINS:
        addr = setting_get(f"crypto_{coin_key}", "")
        if addr:
            has_any = True
            symbol     = CRYPTO_API_SYMBOLS.get(coin_key, "")
            price_note = ""
            if amount and symbol and symbol in prices and prices[symbol] > 0:
                coin_amount = amount / prices[symbol]
                price_note  = f" | ≈ {coin_amount:.4f} {symbol}"
            eid = CRYPTO_EMOJI_IDS.get(coin_key)
            rows.append([_btn(f"{coin_label}{price_note}", callback_data=f"pm:crypto:{coin_key}", emoji_id=eid)])
    if not has_any:
        send_or_edit(target, "⚠️ هیچ آدرس ارز دیجیتالی توسط ادمین ثبت نشده است.", back_button("main"))
        return
    rows.append([_btn("بازگشت", callback_data=back_cb, emoji_id="5352759161945867747")])
    send_or_edit(target, f"{ce('💎', '5454409660473827001')} <b>ارز دیجیتال</b>\n\nنوع ارز مورد نظر را انتخاب کنید:", _raw_markup(rows))


def show_crypto_payment_info(target, uid, coin_key, amount, payment_id=None):
    """Render the crypto payment instruction page.

    Returns True on success, False when rendering was aborted (missing address).
    Callers MUST only transition the user into an ``await_*_receipt`` state
    after this function returns True.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    _chat = target.message.chat.id if hasattr(target, "message") else target.chat.id
    try:
        from .db import setting_get
        addr   = setting_get(f"crypto_{coin_key}", "")
        label  = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
        symbol = CRYPTO_API_SYMBOLS.get(coin_key, "")
        if not addr:
            send_or_edit(target, "⚠️ آدرس این ارز هنوز توسط ادمین ثبت نشده است.", back_button("main"))
            return False

        comment_on = setting_get(f"crypto_{coin_key}_comment", "0") == "1"
        randamt_on = setting_get(f"crypto_{coin_key}_rand_amount", "0") == "1"

        coin_amount_str = ""
        if amount:
            prices = _get_prices()
            if symbol and symbol in prices and prices[symbol] > 0:
                coin_amount = float(amount) / prices[symbol]
                if randamt_on:
                    base  = f"{coin_amount:.2f}"
                    extra = "".join(str(random.randint(0, 9)) for _ in range(random.randint(3, 5)))
                    coin_amount_str = base + extra
                else:
                    coin_amount_str = f"{coin_amount:.6f}"

        equiv_line = (
            f"\n{ce('💱', '5987693802335245516')} <b>معادل ارزی:</b> <code>{coin_amount_str}</code> {esc(symbol)}\n"
            if coin_amount_str else ""
        )

        comment_code = None
        comment_section = ""
        if comment_on:
            chars = string.ascii_uppercase + string.digits
            comment_code = "".join(random.choices(chars, k=8))
            comment_section = (
                f"\n\n{ce('🔑', '5454386656628991407')} <b>کامنت:</b> <code>{comment_code}</code>\n\n"
                f"{ce('⚠️', '5987718004475958316')} <b>هنگام پرداخت حتماً مقدار کامنت را دقیقاً وارد کنید، در غیر این صورت رسید شما تأیید نخواهد شد.</b>"
            )
            # Save the comment code to the DB so admins can see it
            if payment_id:
                try:
                    from .db import update_payment_crypto_comment
                    update_payment_crypto_comment(payment_id, comment_code)
                except Exception:
                    pass

        # Save the coin amount to the DB so admin notification always shows it
        if payment_id and coin_amount_str and symbol:
            try:
                from .db import update_payment_crypto_amount
                update_payment_crypto_amount(payment_id, f"{coin_amount_str} {symbol}")
            except Exception:
                pass

        text = (
            f"{ce('💎', '5454409660473827001')} <b>پرداخت با {esc(label)}</b>\n\n"
            f"{ce('💰', '5987758377168540855')} مبلغ: <b>{fmt_price(amount)}</b> تومان"
            f"{equiv_line}\n"
            f"{ce('👛', '5987881105859024173')} <b>آدرس ولت:</b>\n<code>{esc(addr)}</code>"
            f"{comment_section}\n\n"
            f"{ce('⬇️', '5987671584469422871')} پس از واریز، تصویر تراکنش یا هش آن را ارسال کنید.\n\n"
            f"{ce('⚠️', '5989790729923203577')} <i>تمامی کارمزد انتقال ارز دیجیتال به عهده واریزکننده می‌باشد</i>"
        )

        # ── Crypto copy buttons use CopyTextButton (Bot API 7.0) ─────────────
        # No callback handlers needed — buttons copy directly to clipboard.
        kb = types.InlineKeyboardMarkup()
        _copy_row = [
            types.InlineKeyboardButton(
                "آدرس کیف‌پول",
                copy_text=types.CopyTextButton(text=addr),
            ),
        ]
        if coin_amount_str:
            _copy_row.append(
                types.InlineKeyboardButton(
                    "مبلغ ارز",
                    copy_text=types.CopyTextButton(text=coin_amount_str),
                )
            )
        if comment_on and comment_code:
            _copy_row.append(
                types.InlineKeyboardButton(
                    "کد کامنت",
                    copy_text=types.CopyTextButton(text=comment_code),
                )
            )
        kb.row(*_copy_row)
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="pm:back"))
        send_or_edit(target, text, kb)
        return True

    except Exception as _ex:
        _log.exception("show_crypto_payment_info error coin=%s uid=%s: %s", coin_key, uid, _ex)
        try:
            from .db import setting_get as _sg
            _addr  = _sg(f"crypto_{coin_key}", "")
            _label = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
            _kb = types.InlineKeyboardMarkup()
            _kb.add(types.InlineKeyboardButton("بازگشت", callback_data="pm:back"))
            bot.send_message(
                _chat,
                f"{ce('💎', '5454409660473827001')} <b>پرداخت با {_label}</b>\n\n"
                f"{ce('💰', '5987758377168540855')} مبلغ: <b>{fmt_price(amount)}</b> تومان\n"
                f"{ce('👛', '5987881105859024173')} آدرس ولت:\n<code>{esc(_addr)}</code>\n\n"
                f"{ce('⬇️', '5987671584469422871')} پس از واریز، تصویر تراکنش یا هش آن را ارسال کنید.",
                parse_mode="HTML",
                reply_markup=_kb,
            )
            return True
        except Exception:
            return False


# ── Send payment receipt to admins ─────────────────────────────────────────────
def send_payment_to_admins(payment_id):
    payment     = get_payment(payment_id)
    user        = get_user(payment["user_id"])
    package_row = get_package(payment["package_id"]) if payment["package_id"] else None
    _pk = payment["kind"]
    if _pk == "wallet_charge":
        kind_label = "شارژ کیف پول"
    elif _pk in ("renewal", "pnlcfg_renewal"):
        kind_label = "تمدید سرویس" + (" (پنل)" if _pk == "pnlcfg_renewal" else "")
    else:
        kind_label = "خرید کانفیگ"
    method_label = payment["payment_method"]
    coin_key = payment["crypto_coin"]
    if coin_key:
        method_label += f" ({coin_key})"
    package_text = ""
    if package_row:
        try:
            qty = int(payment["quantity"]) if "quantity" in payment.keys() else 1
        except Exception:
            qty = 1
        qty_line = f"\n🔢 تعداد کانفیگ: <b>{qty} عدد</b>" if qty > 1 else ""
        package_text = (
            f"\n🧩 نوع: {esc(package_row['type_name'])}"
            f"\n📦 پکیج: {esc(package_row['name'])}"
            f"{qty_line}"
            f"\n🔋 حجم: {package_row['volume_gb']} گیگ"
            f"\n⏰ مدت: {package_row['duration_days']} روز"
            f"\n👥 تعداد کاربر: {'نامحدود' if not (package_row['max_users'] if 'max_users' in package_row.keys() else 0) else str(package_row['max_users']) + ' کاربره'}"
        )
    # Crypto equivalent line (shown only for crypto payments)
    # Prefer the value stored in DB at payment time; fall back to live price
    crypto_line = ""
    if coin_key:
        _pay_dict = dict(payment)
        _stored_amt = _pay_dict.get("crypto_amount")
        if _stored_amt:
            crypto_line = f"\n💱 معادل ارزی: <code>{esc(_stored_amt)}</code>"
        else:
            symbol = CRYPTO_API_SYMBOLS.get(coin_key, "")
            if symbol:
                prices = _get_prices()
                if symbol in prices and prices[symbol] > 0:
                    coin_amount = payment["amount"] / prices[symbol]
                    crypto_line = f"\n💱 معادل ارزی: <code>{coin_amount:.6f} {symbol}</code>"

    # Crypto comment code shown to admin (for verification)
    ton_fraud_line = ""
    if coin_key:
        _pay_dict = dict(payment)
        _comment = _pay_dict.get("crypto_comment")
        _tx_hash = _pay_dict.get("crypto_tx_hash")
        if _comment:
            ton_fraud_line += f"\n🔑 کد کامنت: <code>{esc(_comment)}</code>"
        if _tx_hash:
            ton_fraud_line += f"\n🔗 هش تراکنش: <code>{esc(_tx_hash)}</code>"
    text = (
        f"📥 <b>درخواست جدید برای بررسی</b>\n\n"
        f"🧾 نوع: {kind_label} | {method_label}\n"
        f"👤 کاربر: {esc(user['full_name'])}\n"
        f"🆔 نام کاربری: {esc(display_username(user['username']))}\n"
        f"🔢 آیدی: <code>{user['user_id']}</code>\n"
        f"💰 مبلغ: <b>{fmt_price(payment['amount'])}</b> تومان"
        + (f"\n🎲 مبلغ نهایی (رندوم): <b>{fmt_price(payment['final_amount'])}</b> تومان"
           if payment['final_amount'] and payment['final_amount'] != payment['amount'] else "")
        + f"{crypto_line}"
        + f"{ton_fraud_line}"
        f"{package_text}\n\n"
        f"📝 توضیح کاربر:\n{esc(payment['receipt_text'] or '-')}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ تأیید", callback_data=f"adm:pay:apc:{payment_id}"),
        types.InlineKeyboardButton("❌ رد",    callback_data=f"adm:pay:rjc:plain:{payment_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("✅💬 تأیید با توضیح", callback_data=f"adm:pay:ap:{payment_id}"),
        types.InlineKeyboardButton("❌💬 رد با توضیح",    callback_data=f"adm:pay:rj:{payment_id}"),
    )

    file_id = payment["receipt_file_id"]

    def _send_to_one(target_id):
        """Send payment notification to a single admin/sub-admin.

        Sends ONE unified message:
        - If there is a receipt photo/document: send_photo/send_document with the
          full info text as caption (max 1024 chars). All approve/reject buttons
          are attached to that single message so admin can act without scrolling.
        - If no media: send text+buttons as a single message.

        Returns the tracked Message (the one that holds the approve/reject buttons).
        """
        try:
            if file_id:
                # Telegram caption max is 1024 chars
                caption = text if len(text) <= 1024 else text[:1021] + "..."
                try:
                    tracked_msg = bot.send_photo(
                        target_id, file_id,
                        caption=caption, reply_markup=kb, parse_mode="HTML",
                    )
                except Exception:
                    try:
                        tracked_msg = bot.send_document(
                            target_id, file_id,
                            caption=caption, reply_markup=kb, parse_mode="HTML",
                        )
                    except Exception:
                        # Media send failed — fall back to text-only message
                        tracked_msg = bot.send_message(
                            target_id, text, reply_markup=kb, parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
            else:
                tracked_msg = bot.send_message(
                    target_id, text, reply_markup=kb, parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            return tracked_msg
        except Exception as e:
            print(f"[send_payment_to_admins] FAILED target={target_id} payment={payment_id} error={e}")
            return None

    for admin_id in ADMIN_IDS:
        msg = _send_to_one(admin_id)
        if msg:
            save_payment_admin_message(payment_id, admin_id, msg.message_id)

    # Also notify sub-admins with approve_payments permission
    for row in get_all_admin_users():
        sub_id = row["user_id"]
        if sub_id in ADMIN_IDS:
            continue
        perms = json.loads(row["permissions"] or "{}")
        if not (perms.get("full") or perms.get("approve_payments")):
            continue
        msg = _send_to_one(sub_id)
        if msg:
            save_payment_admin_message(payment_id, sub_id, msg.message_id)

    # Group topic: unified message (photo+caption+buttons or text+buttons)
    # Track the message so its buttons are removed when the payment is reviewed.
    _group_id = get_group_id()
    if file_id:
        caption = text if len(text) <= 1024 else text[:1021] + "..."
        _topic_msg = send_photo_to_topic("payment_approval", file_id, caption=caption, reply_markup=kb)
    else:
        _topic_msg = send_to_topic("payment_approval", text, reply_markup=kb)
    if _topic_msg and _group_id:
        save_payment_admin_message(payment_id, _group_id, _topic_msg.message_id)


# ── Card payment approval / rejection ─────────────────────────────────────────
def _clear_payment_admin_buttons(payment_id, status_text, file_id=None):
    """Remove approve/reject buttons from all admin notification messages."""
    msgs = get_payment_admin_messages(payment_id)
    for row in msgs:
        _chat_id = row["admin_id"]
        # Remove the inline keyboard from the notification message
        try:
            bot.edit_message_reply_markup(_chat_id, row["message_id"], reply_markup=None)
        except Exception:
            pass
        # Send status follow-up only to individual admin DMs (positive IDs).
        # Group/channel chats (negative IDs) already had their buttons removed;
        # sending an extra message there would pollute the group.
        if _chat_id <= 0:
            continue
        try:
            if file_id:
                # Send photo with full status text as caption (max 1024 chars)
                caption = status_text[:1024]
                sent = False
                try:
                    bot.send_photo(_chat_id, file_id, caption=caption, parse_mode="HTML")
                    sent = True
                except Exception:
                    try:
                        bot.send_document(_chat_id, file_id, caption=caption, parse_mode="HTML")
                        sent = True
                    except Exception:
                        pass
                # If media failed or text was truncated, also send as plain text
                if not sent or len(status_text) > 1024:
                    bot.send_message(_chat_id, status_text, parse_mode="HTML")
            else:
                bot.send_message(_chat_id, status_text, parse_mode="HTML")
        except Exception:
            pass
    delete_payment_admin_messages(payment_id)


def finish_card_payment_approval(payment_id, admin_note, approved):
    result, user_notified = _finish_card_payment_approval_inner(payment_id, admin_note, approved)
    if result:
        header = f"{ce('✅', '5900157489759916320')} <b>تراکنش تأیید شد.</b>" if approved else f"{ce('❌', '5215539470849288572')} <b>تراکنش رد شد.</b>"
        not_notified_note = (
            "\n\n⚠️ <i>ارسال پیام به کاربر امکان‌پذیر نبود (احتمالاً حساب حذف یا ربات را بلاک کرده است).</i>"
            if not user_notified else ""
        )
        file_id = None
        try:
            payment = get_payment(payment_id)
            user = get_user(payment["user_id"]) if payment else None
            package_row = get_package(payment["package_id"]) if payment and payment["package_id"] else None
            if payment and user:
                _k = payment["kind"]
                if _k == "wallet_charge":
                    kind_label = "شارژ کیف پول"
                elif _k in ("renewal", "pnlcfg_renewal"):
                    kind_label = "تمدید سرویس"
                else:
                    kind_label = "خرید کانفیگ"
                method_label = payment["payment_method"]
                coin_key = payment["crypto_coin"]
                if coin_key:
                    method_label += f" ({coin_key})"
                package_text = ""
                if package_row:
                    package_text = (
                        f"\n🧩 نوع: {esc(package_row['type_name'])}"
                        f"\n📦 پکیج: {esc(package_row['name'])}"
                        f"\n🔋 حجم: {package_row['volume_gb']} گیگ"
                        f"\n⏰ مدت: {package_row['duration_days']} روز"
                        f"\n👥 تعداد کاربر: {'نامحدود' if not (package_row['max_users'] if 'max_users' in package_row.keys() else 0) else str(package_row['max_users']) + ' کاربره'}"
                    )
                status_text = (
                    f"{header}\n\n"
                    f"🧾 نوع: {kind_label} | {method_label}\n"
                    f"{ce('👤', '5373012449597335010')} کاربر: {esc(user['full_name'])}\n"
                    f"🆔 نام کاربری: {esc(display_username(user['username']))}\n"
                    f"🔢 آیدی: <code>{user['user_id']}</code>\n"
                    f"{ce('💰', '5794002949222964817')} مبلغ: <b>{fmt_price(payment['amount'])}</b> تومان"
                    f"{package_text}\n\n"
                    f"📝 توضیح کاربر:\n{esc(payment['receipt_text'] or '-')}"
                    f"{not_notified_note}"
                )
                file_id = payment["receipt_file_id"]
            else:
                status_text = header + not_notified_note
        except Exception:
            status_text = header
        try:
            _clear_payment_admin_buttons(payment_id, status_text, file_id)
        except Exception:
            pass
    return result


def _finish_card_payment_approval_inner(payment_id, admin_note, approved):
    from .ui.notifications import (
        deliver_purchase_message, admin_purchase_notify,
        admin_renewal_notify, notify_pending_order_to_admins,
    )
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # ── In-memory guard: reject duplicate/concurrent approval of same payment ─
    with _pay_lock:
        if payment_id in _pay_in_fly:
            _log.warning("payment #%s already being processed — duplicate call ignored", payment_id)
            return False, True
        _pay_in_fly.add(payment_id)

    try:
        return _finish_card_payment_approval_core(payment_id, admin_note, approved)
    finally:
        with _pay_lock:
            _pay_in_fly.discard(payment_id)


def _finish_card_payment_approval_core(payment_id, admin_note, approved):
    from .ui.notifications import (
        deliver_purchase_message, admin_purchase_notify,
        admin_renewal_notify, notify_pending_order_to_admins,
    )
    import logging as _logging
    _log = _logging.getLogger(__name__)

    payment = get_payment(payment_id)
    if not payment or payment["status"] != "pending":
        return False, True  # (result, user_notified)
    user_id = payment["user_id"]

    def _safe_send(user_id, *args, **kwargs):
        """Send a message to user; returns True on success, False on 403/deactivated."""
        try:
            bot.send_message(user_id, *args, **kwargs)
            return True
        except Exception as e:
            _log.warning("payment_notify: cannot send to user %s: %s", user_id, e)
            return False

    if approved:
        approve_payment(payment_id, admin_note)
        if payment["kind"] == "wallet_charge":
            if not complete_payment(payment_id, force=True):
                return False, True  # already processed
            update_balance(user_id, payment["amount"])
            notified = _safe_send(user_id,
                f"{ce('✅', '5987885383646451415')} واریزی شما تأیید شد."
                + (f"\n\n{esc(admin_note)}" if admin_note else ""),
                parse_mode="HTML")
            # Apply gateway bonus if configured
            try:
                apply_gateway_bonus_if_needed(user_id, payment["payment_method"] or "card", payment["amount"])
            except Exception:
                pass
            user_row = get_user(user_id)
            receipt_note = payment["receipt_text"] if payment["receipt_text"] else ""
            pay_method   = payment["payment_method"] if payment["payment_method"] else "—"
            pay_id_txt   = f"#{payment_id}"
            send_to_topic("wallet_log",
                f"{ce('💳', '5931368295545443065')} <b>شارژ کیف‌پول تأیید شد</b>\n\n"
                f"{ce('👤', '5373012449597335010')} {esc(user_row['full_name'] if user_row else str(user_id))}\n"
                f"🆔 <code>{user_id}</code>\n"
                f"{ce('💰', '5794002949222964817')} مبلغ: <b>{fmt_price(payment['amount'])}</b> تومان\n"
                f"💳 روش پرداخت: {esc(pay_method)}\n"
                f"🧾 شناسه تراکنش: <code>{pay_id_txt}</code>\n"
                + (f"📝 توضیحات: {esc(receipt_note)}\n" if receipt_note else "")
                + f"🕐 زمان: {now_str()[:16]}"
            )
            return True, notified

        elif payment["kind"] == "config_purchase":
            config_id   = payment["config_id"]
            package_id  = payment["package_id"]
            package_row = get_package(package_id)
            from .handlers.callbacks import _deliver_bulk_configs, _send_bulk_delivery_result
            _qty_card = int(payment["quantity"]) if "quantity" in payment.keys() else 1
            if not complete_payment(payment_id, force=True):
                return False, True  # already processed
            notified = _safe_send(user_id,
                f"{ce('✅', '5987885383646451415')} واریزی شما تأیید شد."
                + (f"\n\n{esc(admin_note)}" if admin_note else "")
                + f"\n\n{ce('⏳', '5258079378159453410')} کانفیگ شما در حال ارسال است ...",
                parse_mode="HTML")
            # Apply gateway bonus if configured
            try:
                apply_gateway_bonus_if_needed(user_id, payment["payment_method"] or "card", payment["amount"])
            except Exception:
                pass
            # Run delivery in a background thread so the approval callback returns
            # immediately and Telegram does not retry the callback due to timeout.
            _svc_names = get_payment_service_names(payment_id)
            _pay_method = payment["payment_method"]
            def _do_deliver():
                try:
                    purchase_ids, pending_ids = _deliver_bulk_configs(
                        user_id, user_id, package_id,
                        payment["amount"], _pay_method, _qty_card, payment_id,
                        service_names=_svc_names,
                    )
                    _send_bulk_delivery_result(user_id, user_id, package_row,
                                               purchase_ids, pending_ids,
                                               _pay_method, payment_id=payment_id)
                except Exception as _de:
                    _log.error("background delivery failed for payment %s: %s", payment_id, _de)
            _threading.Thread(target=_do_deliver, daemon=True).start()
            return True, notified

        elif payment["kind"] == "renewal":
            package_id  = payment["package_id"]
            package_row = get_package(package_id)
            config_id   = payment["config_id"]
            if not complete_payment(payment_id, force=True):
                return True, True  # already processed by another path
            notified = _safe_send(
                user_id,
                "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                "🔄 درخواست تمدید سرویس شما با موفقیت ثبت و برای پشتیبانی ارسال شد.\n"
                "⏳ لطفاً کمی صبر کنید، پس از انجام تمدید به شما اطلاع داده خواهد شد.\n\n"
                "🙏 از صبر و شکیبایی شما متشکریم.",
                parse_mode="HTML",
            )
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT purchase_id FROM configs WHERE id=?", (config_id,)
                ).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item        = get_purchase(purchase_id) if purchase_id else None
            if item and package_row:
                admin_renewal_notify(user_id, item, package_row, payment["amount"], payment["payment_method"])
            return True, notified

        elif payment["kind"] == "pnlcfg_renewal":
            # Panel config renewal — execute automatically after payment approval
            from .handlers.callbacks import _execute_pnlcfg_renewal as _exec_pnlr
            panel_config_id = payment["config_id"]
            package_id      = payment["package_id"]
            if not complete_payment(payment_id, force=True):
                return True, True  # already processed
            ok_r, err_r = _exec_pnlr(panel_config_id, package_id, uid=user_id)
            if ok_r:
                notified = _safe_send(
                    user_id,
                    "✅ <b>تمدید سرویس انجام شد!</b>\n\n"
                    "🔄 پرداخت شما تأیید و سرویس با موفقیت تمدید شد.\n\n"
                    "🙏 از اعتماد شما سپاسگزاریم.",
                    parse_mode="HTML",
                )
            else:
                notified = _safe_send(
                    user_id,
                    "✅ پرداخت تأیید شد اما تمدید سرویس با خطا مواجه شد.\n"
                    "لطفاً با پشتیبانی ارتباط بگیرید.",
                    parse_mode="HTML",
                )
            return True, notified

        return True, True
    else:
        reject_payment(payment_id, admin_note)
        if payment["config_id"] and payment["kind"] != "pnlcfg_renewal":
            release_reserved_config(payment["config_id"])
        _reject_text = (
            "کاربر گرامی\n\n"
            f"{ce('❌', '5987718004475958316')} رسید شما توسط ادمین رد شد."
        )
        if admin_note:
            _reject_text += f"\n\n📝 دلیل: {esc(admin_note)}"
        notified = _safe_send(user_id, _reject_text)
        return True, notified
