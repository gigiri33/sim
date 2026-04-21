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
    set_payment_crypto_comment,
)
from .helpers import esc, fmt_price, display_username, back_button, now_str
import time

# ── In-memory idempotency guard ────────────────────────────────────────────────
# Prevents concurrent or duplicate processing of the same payment_id when
# the admin has a weak network and Telegram retries the callback, or two
# admins tap approve simultaneously.
_pay_lock   = _threading.Lock()
_pay_in_fly: set = set()   # payment IDs currently being processed
from .gateways.base import is_gateway_available, is_card_info_complete, get_gateway_range_text, is_gateway_in_range, build_gateway_range_guide
from .gateways.crypto import fetch_crypto_prices
from .bot_instance import bot
from .ui.helpers import send_or_edit
from .ui.keyboards import _btn, _raw_markup
from .ui.premium_emoji import ce
from .group_manager import send_to_topic, send_photo_to_topic

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
def get_effective_price(user_id, package_row):
    """Return discounted price for agents, else regular price."""
    user = get_user(user_id)
    if not user or not user["is_agent"]:
        return package_row["price"]
    base  = package_row["price"]
    cfg   = get_agency_price_config(user_id)
    mode  = cfg["price_mode"]
    if mode == "global":
        g_type = cfg["global_type"]
        g_val  = cfg["global_val"]
        if g_type == "pct":
            return max(0, base - round(base * g_val / 100))
        else:
            return max(0, base - g_val)
    elif mode == "type":
        type_id = package_row["type_id"]
        td = get_agency_type_discount(user_id, type_id)
        if td:
            if td["discount_type"] == "pct":
                return max(0, base - round(base * td["discount_value"] / 100))
            else:
                return max(0, base - td["discount_value"])
        return base
    else:  # package (default)
        ap = get_agency_price(user_id, package_row["id"])
        return ap if ap is not None else base


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
    }

    def _add_gw(key, cb, extra_check=True):
        if not (is_gateway_available(key, uid) and extra_check):
            return
        default_lbl, eid = _GW_DEFAULTS[key]
        custom_lbl = _sg(f"gw_{key}_display_name", "").strip()
        lbl = custom_lbl or default_lbl
        rows.append([_btn(lbl, callback_data=cb, emoji_id=eid)])
        _gw_labels.append((key, lbl))

    _add_gw("card", "pm:card", is_card_info_complete())
    _add_gw("crypto", "pm:crypto")
    _add_gw("tetrapay", "pm:tetrapay")
    _add_gw("swapwallet_crypto", "pm:swapwallet_crypto")
    _add_gw("tronpays_rial", "pm:tronpays_rial")

    rows.append([_btn("بازگشت", callback_data="nav:main", emoji_id="5352759161945867747")])
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
def show_crypto_selection(target, amount=None):
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
    rows.append([_btn("بازگشت", callback_data="pm:back", emoji_id="5352759161945867747")])
    send_or_edit(target, f"{ce('💎', '5794002949222964817')} <b>ارز دیجیتال</b>\n\nنوع ارز مورد نظر را انتخاب کنید:", _raw_markup(rows))


def show_crypto_payment_info(target, uid, coin_key, amount, payment_id=None):
    """Render the crypto payment instruction page (wallet + amount + memo for TON).

    Returns True when the full info page was successfully rendered to the user,
    False when rendering was aborted (e.g. missing admin-configured address).
    Callers MUST only transition the user into an ``await_*_receipt`` state
    after this function returns True, otherwise the next arbitrary message
    would incorrectly be treated as a payment receipt.
    """
    from .db import setting_get
    addr   = setting_get(f"crypto_{coin_key}", "")
    label  = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
    symbol = CRYPTO_API_SYMBOLS.get(coin_key, "")
    if not addr:
        send_or_edit(target, "⚠️ آدرس این ارز هنوز توسط ادمین ثبت نشده است.", back_button("main"))
        return False

    coin_amount_str = ""
    prices = _get_prices()
    if symbol and symbol in prices and prices[symbol] > 0:
        coin_amount = amount / prices[symbol]
        coin_amount_str = f"{coin_amount:.6f}"

    equiv_line = (
        f"\n{ce('💱', '5402186569006210455')} <b>معادل ارزی:</b> <code>{coin_amount_str}</code> {symbol}\n"
        if coin_amount_str else ""
    )

    # TON-specific: generate a unique comment/memo code
    comment_section = ""
    comment_code = None
    if coin_key == "ton" and payment_id:
        comment_code = f"SIM{payment_id:06d}"
        try:
            set_payment_crypto_comment(payment_id, comment_code)
        except Exception:
            pass
        comment_section = (
            f"\n\n{ce('🔑', '5316979637987594548')} <b>کد یکتای واریز (الزامی):</b>\n"
            f"<code>{comment_code}</code>\n"
            f"{ce('⚠️', '5314302076317081739')} <b>این کد را حتماً در فیلد <i>Comment</i> تراکنش TON وارد کنید.</b>\n"
            f"{ce('⚠️', '5314302076317081739')} <i>واریز بدون این کد قابل شناسایی نیست و تأیید نخواهد شد.</i>"
        )

    text = (
        f"{ce('💎', '5794002949222964817')} <b>پرداخت با {label}</b>\n\n"
        f"{ce('💰', '5318912792428814144')} مبلغ: <b>{fmt_price(amount)}</b> تومان"
        f"{equiv_line}\n"
        f"{ce('👛', '5796280694934085416')} <b>آدرس ولت:</b>\n<code>{esc(addr)}</code>"
        f"{comment_section}\n\n"
        f"{ce('⬇️', '5314453632828055816')} پس از واریز، تصویر تراکنش یا هش آن را ارسال کنید.\n\n"
        f"{ce('⚠️', '5314302076317081739')} <i>تمامی کارمزد انتقال ارز دیجیتال به عهده واریزکننده می‌باشد</i>"
    )

    rows = []
    if coin_key == "ton" and comment_code:
        rows.append([_btn("کپی کد واریز", copy_text=comment_code, emoji_id="5316979637987594548")])
    if coin_amount_str:
        rows.append([
            _btn("کپی آدرس ولت", copy_text=addr, emoji_id="5796280694934085416"),
            _btn("کپی مبلغ دقیق", copy_text=coin_amount_str, emoji_id="5794002949222964817"),
        ])
    else:
        rows.append([_btn("کپی آدرس ولت", copy_text=addr, emoji_id="5796280694934085416")])
    rows.append([_btn("بازگشت", callback_data="nav:main", emoji_id="5352759161945867747")])
    kb = _raw_markup(rows)

    # Fallback keyboard without copy_text buttons (standard InlineKeyboardMarkup)
    # used if Telegram rejects the copy_text button type
    kb_fallback = types.InlineKeyboardMarkup()
    kb_fallback.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main"))

    def _send(chat_id, msg_text):
        """Try sending with copy_text keyboard; fall back to plain keyboard."""
        try:
            bot.send_message(chat_id, msg_text, reply_markup=kb,
                             parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            bot.send_message(chat_id, msg_text, reply_markup=kb_fallback,
                             parse_mode="HTML", disable_web_page_preview=True)

    if hasattr(target, "message"):
        chat_id = target.message.chat.id
        msg_id  = target.message.message_id
        try:
            bot.edit_message_text(
                text, chat_id, msg_id,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception:
            pass
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            try:
                bot.edit_message_reply_markup(
                    chat_id, msg_id,
                    reply_markup=types.InlineKeyboardMarkup()
                )
            except Exception:
                pass
        _send(chat_id, text)
        return True
    elif hasattr(target, "chat"):
        _send(target.chat.id, text)
        return True
    else:
        try:
            send_or_edit(target, text, kb)
        except Exception:
            send_or_edit(target, text, kb_fallback)
        return True


# ── Send payment receipt to admins ─────────────────────────────────────────────
def send_payment_to_admins(payment_id):
    payment     = get_payment(payment_id)
    user        = get_user(payment["user_id"])
    package_row = get_package(payment["package_id"]) if payment["package_id"] else None
    kind_label  = "شارژ کیف پول" if payment["kind"] == "wallet_charge" else "خرید کانفیگ"
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
    crypto_line = ""
    if coin_key:
        symbol = CRYPTO_API_SYMBOLS.get(coin_key, "")
        if symbol:
            prices = _get_prices()
            if symbol in prices and prices[symbol] > 0:
                coin_amount = payment["amount"] / prices[symbol]
                crypto_line = f"\n💱 معادل ارزی: <code>{coin_amount:.6f} {symbol}</code>"

    # TON anti-fraud info for admin
    ton_fraud_line = ""
    if coin_key == "ton":
        _pay_dict = dict(payment)
        _comment = _pay_dict.get("crypto_comment")
        _tx_hash = _pay_dict.get("crypto_tx_hash")
        if _comment:
            ton_fraud_line += f"\n🔑 کد واریز (Comment): <code>{esc(_comment)}</code>"
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
        types.InlineKeyboardButton("✅ تأیید", callback_data=f"adm:pay:ap:{payment_id}"),
        types.InlineKeyboardButton("❌ رد",    callback_data=f"adm:pay:rj:{payment_id}"),
    )

    file_id = payment["receipt_file_id"]

    def _send_to_one(target_id):
        """Send payment notification to a single admin/sub-admin.
        
        Strategy:
        - If there is a receipt photo/document: send it FIRST, then the text
          with approve/reject buttons (so admin sees photo before the approval request).
        - If no media: send the text+buttons as a single message.
        
        Returns the tracked Message (the one that holds the approve/reject buttons).
        """
        try:
            # If there's a receipt image/document, send it FIRST (photo before approval text)
            if file_id:
                try:
                    bot.send_photo(target_id, file_id,
                                   caption="🖼 رسید کاربر",
                                   parse_mode="HTML")
                except Exception:
                    try:
                        bot.send_document(target_id, file_id,
                                          caption="📎 رسید کاربر",
                                          parse_mode="HTML")
                    except Exception:
                        pass  # Media forward failure is non-critical
            # Then send the full info text with the approve/reject buttons
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

    # Group topic: send text first, then photo separately if present
    grp_msg = send_to_topic("payment_approval", text, reply_markup=kb)
    if file_id and grp_msg:
        send_photo_to_topic("payment_approval", file_id, caption="🖼 رسید کاربر")
    elif file_id:
        send_photo_to_topic("payment_approval", file_id, caption=text[:1024])


# ── Card payment approval / rejection ─────────────────────────────────────────
def _clear_payment_admin_buttons(payment_id, status_text, file_id=None):
    """Remove approve/reject buttons from all admin notification messages."""
    msgs = get_payment_admin_messages(payment_id)
    for row in msgs:
        try:
            bot.edit_message_reply_markup(row["admin_id"], row["message_id"], reply_markup=None)
        except Exception:
            pass
        try:
            if file_id:
                # Send photo with full status text as caption (max 1024 chars)
                caption = status_text[:1024]
                sent = False
                try:
                    bot.send_photo(row["admin_id"], file_id, caption=caption, parse_mode="HTML")
                    sent = True
                except Exception:
                    try:
                        bot.send_document(row["admin_id"], file_id, caption=caption, parse_mode="HTML")
                        sent = True
                    except Exception:
                        pass
                # If media failed or text was truncated, also send as plain text
                if not sent or len(status_text) > 1024:
                    bot.send_message(row["admin_id"], status_text, parse_mode="HTML")
            else:
                bot.send_message(row["admin_id"], status_text, parse_mode="HTML")
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
                kind_label = "شارژ کیف پول" if payment["kind"] == "wallet_charge" else "خرید کانفیگ"
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
            if not complete_payment(payment_id):
                return False, True  # already processed
            update_balance(user_id, payment["amount"])
            notified = _safe_send(user_id, f"{ce('✅', '5900157489759916320')} واریزی شما تأیید شد.\n\n{esc(admin_note)}")
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
            if not complete_payment(payment_id):
                return False, True  # already processed
            notified = _safe_send(user_id,
                f"{ce('✅', '5900157489759916320')} واریزی شما تأیید شد.\n\n{esc(admin_note)}\n\n"
                "⏳ کانفیگ‌های شما در حال آماده‌سازی هستند...")
            purchase_ids, pending_ids = _deliver_bulk_configs(
                user_id, user_id, package_id,
                payment["amount"], payment["payment_method"], _qty_card, payment_id
            )
            _send_bulk_delivery_result(user_id, user_id, package_row,
                                       purchase_ids, pending_ids,
                                       payment["payment_method"])
            return True, notified

        elif payment["kind"] == "renewal":
            package_id  = payment["package_id"]
            package_row = get_package(package_id)
            config_id   = payment["config_id"]
            if not complete_payment(payment_id):
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
        return True, True
    else:
        reject_payment(payment_id, admin_note)
        if payment["config_id"]:
            release_reserved_config(payment["config_id"])
        notified = _safe_send(user_id, f"{ce('❌', '5215539470849288572')} رسید شما رد شد.\n\n{esc(admin_note)}")
        return True, notified
