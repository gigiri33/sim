# -*- coding: utf-8 -*-
"""
User and admin notification helpers: purchase delivery, admin alerts,
pending-order fulfillment.
"""
import io
import json
import random
import qrcode
import urllib.parse
from telebot import types

from ..config import ADMIN_IDS
from ..db import (
    get_purchase, get_user, get_package, get_conn,
    assign_config_to_user, get_available_configs_for_package,
    fulfill_pending_order, get_waiting_pending_orders_for_package,
    get_pending_order, get_all_admin_users, setting_get,
    count_referrals, get_unrewarded_start_referrals,
    mark_start_reward_given, get_unrewarded_purchase_referees,
    mark_purchase_reward_given, get_referral_by_referee,
    update_balance,
    set_referral_channel_joined, try_claim_start_reward_batch,
    try_claim_purchase_reward_batch,
    add_pending_reward,
    get_locked_channels,
    get_referral_restriction,
    add_referral_restriction,
    has_referral_spam_event,
    record_referral_spam_event,
    count_recent_referrals,
    set_user_restricted,
    set_referral_captcha_verified,
    set_referral_captcha_failed,
)
from ..helpers import esc, fmt_price, now_str, move_leading_emoji
from ..bot_instance import bot
from ..group_manager import send_to_topic
from .premium_emoji import ce

# ── Referral Captcha in-memory store ────────────────────────────────────────
# Maps referee_id → correct_answer (int). Cleared on answer (correct or wrong).
_PENDING_CAPTCHAS: dict = {}


def generate_referral_captcha() -> tuple:
    """Return (question_str, correct_answer) — simple 2-digit ± 1-digit math.
    First operand: 10-99 (2 digits), second: 1-9 (1 digit).
    Answer is always positive and at most 2 digits (≤ 99).
    """
    op = random.choice(["+", "-"])
    b = random.randint(1, 9)
    if op == "+":
        # a + b ≤ 99  →  a ≤ 99 - b
        a = random.randint(10, 99 - b)
        answer = a + b
    else:
        # a - b ≥ 1  →  a ≥ b + 1, also a - b ≤ 99 (always true)
        a = random.randint(b + 10, 99)   # at least b+10 so a is 2-digit and a-b >= 10+1=11
        answer = a - b
    question = f"{a} {op} {b}"
    return question, answer


def send_captcha_prompt(referee_id: int) -> None:
    """Generate a captcha, store the answer and send the prompt to the referee."""
    question, answer = generate_referral_captcha()
    _PENDING_CAPTCHAS[referee_id] = answer
    # \u200e = Left-to-Right Mark — forces the math expression to render LTR
    # even in RTL contexts (Telegram renders lines with mixed numbers/symbols RTL).
    try:
        bot.send_message(
            referee_id,
            "\U0001f916 <b>\u062a\u0623\u06cc\u06cc\u062f \u0647\u0648\u06cc\u062a (\u06a9\u067e\u0686\u0627)</b>\n\n"
            "\u0628\u0631\u0627\u06cc \u062a\u0627\u06cc\u06cc\u062f \u062d\u0633\u0627\u0628 \u0648 \u062b\u0628\u062a \u0632\u06cc\u0631\u0645\u062c\u0645\u0648\u0639\u0647\u060c \u0644\u0637\u0641\u0627\u064b \u06a9\u067e\u0686\u0627 \u0631\u0627 \u062d\u0644 \u06a9\u0646\u06cc\u062f:\n\n"
            f"<code>\u200e{question} = ?</code>\n\n"
            "\u067e\u0627\u0633\u062e \u0631\u0627 \u0628\u0647 \u0635\u0648\u0631\u062a \u0639\u062f\u062f \u0627\u0631\u0633\u0627\u0644 \u06a9\u0646\u06cc\u062f.",
            parse_mode="HTML",
        )
    except Exception:
        pass


def has_pending_captcha(user_id: int) -> bool:
    """Return True if user has an unanswered captcha."""
    return user_id in _PENDING_CAPTCHAS


def verify_and_process_captcha(referee_id: int, answer_text: str) -> bool:
    """
    Verify a captcha answer. Removes the pending captcha regardless of outcome.
    Returns True if correct, False if wrong or no pending captcha found.
    Non-numeric text is treated as wrong.
    """
    correct = _PENDING_CAPTCHAS.pop(referee_id, None)
    if correct is None:
        return False
    try:
        user_val = int(answer_text.strip())
    except (ValueError, AttributeError):
        return False
    return user_val == correct


def complete_referral_after_captcha(referee_id: int) -> None:
    """Mark captcha verified and try to give the start reward to the referrer."""
    set_referral_captcha_verified(referee_id)
    ref = get_referral_by_referee(referee_id)
    if not ref:
        return
    referrer_id = ref["referrer_id"]
    check_and_give_referral_start_reward(referrer_id)


def notify_referrer_captcha_failed(referee_id: int) -> None:
    """Mark the referee's captcha as failed and notify the referrer."""
    set_referral_captcha_failed(referee_id)
    ref = get_referral_by_referee(referee_id)
    if not ref:
        return
    referrer_id = ref["referrer_id"]
    referee = get_user(referee_id)
    if not referee:
        return
    ref_username = referee["username"]
    if ref_username:
        referee_link = f"@{esc(ref_username)}"
    else:
        referee_link = f"<a href=\"tg://user?id={referee_id}\">{esc(referee['full_name'] or 'کاربر جدید')}</a>"
    try:
        bot.send_message(
            referrer_id,
            f"⚠️ کاربر {referee_link} از طریق لینک دعوت شما وارد ربات شد، "
            f"اما کپچا را اشتباه حل کرد و به عنوان زیرمجموعه برای شما <b>حساب نشد</b>.",
            parse_mode="HTML",
        )
    except Exception:
        pass


def _bot_notif_on(key: str) -> bool:
    """Return True if bot (sub-admin) notifications for this key are enabled."""
    return setting_get(f"notif_bot_{key}", "1") == "1"


def _own_notif_on(key: str) -> bool:
    """Return True if owner (ADMIN_IDS) notifications for this key are enabled."""
    return setting_get(f"notif_own_{key}", "1") == "1"


# ── Purchase delivery ──────────────────────────────────────────────────────────
def _fmt_users_label_d(max_users):
    if not max_users:
        return "نامحدود"
    if max_users == 1:
        return "تک‌کاربره"
    if max_users == 2:
        return "دوکاربره"
    return f"{max_users} کاربره"


def _send_file_group_delivery(chat_id, file_ids, caption, kb):
    """Send files as media album; attach kb after group if multi-file."""
    if not file_ids:
        bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
        return
    if len(file_ids) == 1:
        bot.send_document(chat_id, file_ids[0], caption=caption, parse_mode="HTML", reply_markup=kb)
        return
    chunks = [file_ids[i:i + 10] for i in range(0, len(file_ids), 10)]
    for idx, chunk in enumerate(chunks):
        is_last = (idx == len(chunks) - 1)
        if is_last:
            media = [types.InputMediaDocument(fid) for fid in chunk[:-1]]
            media.append(types.InputMediaDocument(chunk[-1], caption=caption, parse_mode="HTML"))
        else:
            media = [types.InputMediaDocument(fid) for fid in chunk]
        bot.send_media_group(chat_id, media)
    # keyboard can't attach to media group — send separately
    bot.send_message(chat_id, f"{ce('⬆️', '5463122435425448565')} فایل‌های کانفیگ شما", reply_markup=kb)


def deliver_purchase_message(chat_id, purchase_id):
    item = get_purchase(purchase_id)
    if not item:
        bot.send_message(chat_id, f"{ce('❌', '5215642288071387368')} اطلاعات خرید یافت نشد.")
        return
    cfg          = item["config_text"]
    service_name = move_leading_emoji(urllib.parse.unquote(item["service_name"] or ""))
    inquiry_link = item["inquiry_link"] or ""
    show_pkg_name = ("show_name" not in item.keys()) or bool(item["show_name"])
    package_line = f"{ce('📦', '5258134813302332906')} پکیج: <b>{esc(item['package_name'])}</b>\n" if show_pkg_name and item["package_name"] else ""
    expired_note = ""
    if item["is_expired"]:
        if item["is_test"]:
            expired_note = f"\n\n{ce('⚠️', '5447644880824181073')} <b>مدت تست رایگان شما به پایان رسیده است.</b>"
        else:
            expired_note = f"\n\n{ce('⚠️', '5447644880824181073')} <b>این سرویس توسط ادمین منقضی شده است.</b>"
    title_line = "تست رایگان" if item["is_test"] else "سرویس شما آماده است"
    if item["is_test"] and not item["is_expired"]:
        hours_left = item["test_hours_left"] if "test_hours_left" in item.keys() else None
        if hours_left is not None:
            h = int(hours_left)
            time_str = f"{h // 24} روز و {h % 24} ساعت" if h >= 24 else f"{h} ساعت"
            title_line = f"تست رایگان — ⏰ {time_str} باقی‌مانده"

    kb = types.InlineKeyboardMarkup()
    if setting_get("manual_renewal_enabled", "1") == "1" and not item["is_test"]:
        kb.add(types.InlineKeyboardButton("♻️ تمدید", callback_data=f"renew:{purchase_id}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="my_configs"))

    # Detect file-based configs (OpenVPN / WireGuard)
    cfg_data = None
    try:
        parsed = json.loads(cfg)
        if isinstance(parsed, dict) and parsed.get("type") in ("ovpn", "wg"):
            cfg_data = parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    if cfg_data:
        file_ids    = cfg_data.get("file_ids", [])
        cfg_type    = cfg_data.get("type")
        vol_text    = "نامحدود" if not item["volume_gb"] else f"{item['volume_gb']} گیگ"
        dur_text    = "نامحدود" if not item["duration_days"] else f"{item['duration_days']} روز"
        users_label = _fmt_users_label_d(item["max_users"] if "max_users" in item.keys() else 0)
        inq_line    = f"\n� پنل استعلام حجم و زمان: {inquiry_link}" if inquiry_link else ""

        if cfg_type == "ovpn":
            username = cfg_data.get("username", "")
            password = cfg_data.get("password", "")
            caption = (
                f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>\n"
                f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(item['type_name'])}</b>\n"
                f"{package_line}"
                f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(vol_text)}</b>\n"
                f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(dur_text)}</b>\n"
                f"👤 کاربر: <b>{esc(users_label)}</b>\n"
                f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                f"{ce('🔐', '5472308992514464048')} اطلاعات اکانت\n"
                f"username: <code>{esc(username)}</code>\n"
                f"password: <code>{esc(password)}</code>"
                f"{inq_line}"
                f"{expired_note}"
            )
            _send_file_group_delivery(chat_id, file_ids, caption, kb)
        else:  # wg
            caption = (
                f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>\n"
                f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(item['type_name'])}</b>\n"
                f"{package_line}"
                f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(vol_text)}</b>\n"
                f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(dur_text)}</b>\n"
                f"{ce('👥', '5372926953978341366')} نوع کاربری: <b>{esc(users_label)}</b>"
                f"{inq_line}"
                f"{expired_note}"
            )
            # Generate QR from stored config text or downloaded file content
            qr_content = cfg_data.get("config_text", "").strip()
            if not qr_content and file_ids:
                try:
                    file_info = bot.get_file(file_ids[0])
                    downloaded = bot.download_file(file_info.file_path)
                    qr_content = downloaded.decode("utf-8", errors="ignore").strip()
                except Exception:
                    qr_content = ""
            if qr_content:
                try:
                    qr_img = qrcode.make(qr_content)
                    qr_bio = io.BytesIO()
                    qr_img.save(qr_bio, format="PNG")
                    qr_bio.seek(0)
                    qr_bio.name = "wg_qr.png"
                    bot.send_photo(chat_id, qr_bio, caption="📷 QR کانفیگ WireGuard", parse_mode="HTML")
                except Exception:
                    pass
            _send_file_group_delivery(chat_id, file_ids, caption, kb)
    else:
        # V2Ray / text-based delivery
        _vol_text_v2  = "نامحدود" if not item["volume_gb"] else f"{item['volume_gb']} گیگ"
        _dur_text_v2  = "نامحدود" if not item["duration_days"] else f"{item['duration_days']} روز"
        _max_u_v2     = item["max_users"] if "max_users" in item.keys() else 0
        _users_v2     = "نامحدود" if not _max_u_v2 else f"{_max_u_v2} کاربره"

        # Determine registration mode based on what's available
        has_config = bool(cfg and cfg.strip())
        has_sub    = bool(inquiry_link and inquiry_link.strip())

        if has_config and has_sub:
            # Mode: config + sub
            text = (
                f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>\n"
                f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(item['type_name'])}</b>\n"
                f"{package_line}"
                f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(_vol_text_v2)}</b>\n"
                f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(_dur_text_v2)}</b>\n"
                f"{ce('👥', '5372926953978341366')} تعداد کاربر: <b>{esc(_users_v2)}</b>\n\n"
                f"{ce('💝', '5900197669178970457')} <b>Config:</b>\n<code>{esc(cfg)}</code>\n\n"
                f"{ce('🔗', '5271604874419647061')} <b>لینک ساب:</b>\n{esc(inquiry_link)}"
                f"{expired_note}"
            )
            qr_source = cfg
        elif has_config:
            # Mode: config only
            text = (
                f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>\n"
                f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(item['type_name'])}</b>\n"
                f"{package_line}"
                f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(_vol_text_v2)}</b>\n"
                f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(_dur_text_v2)}</b>\n"
                f"{ce('👥', '5372926953978341366')} تعداد کاربر: <b>{esc(_users_v2)}</b>\n\n"
                f"{ce('💝', '5900197669178970457')} <b>Config:</b>\n<code>{esc(cfg)}</code>"
                f"{expired_note}"
            )
            qr_source = cfg
        elif has_sub:
            # Mode: sub only
            text = (
                f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>\n"
                f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(item['type_name'])}</b>\n"
                f"{package_line}"
                f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(_vol_text_v2)}</b>\n"
                f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(_dur_text_v2)}</b>\n"
                f"{ce('👥', '5372926953978341366')} تعداد کاربر: <b>{esc(_users_v2)}</b>\n\n"
                f"{ce('🔗', '5271604874419647061')} <b>لینک ساب:</b>\n{esc(inquiry_link)}"
                f"{expired_note}"
            )
            qr_source = inquiry_link
        else:
            # Fallback: legacy display
            text = (
                f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>\n"
                f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(item['type_name'])}</b>\n"
                f"{package_line}"
                f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(_vol_text_v2)}</b>\n"
                f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(_dur_text_v2)}</b>\n"
                f"{ce('👥', '5372926953978341366')} تعداد کاربر: <b>{esc(_users_v2)}</b>\n\n"
                f"{ce('💝', '5900197669178970457')} <b>Config:</b>\n<code>{esc(cfg or '-')}</code>\n\n"
                f"{ce('🔗', '5271604874419647061')} <b>لینک ساب:</b>\n{esc(inquiry_link or '-')}"
                f"{expired_note}"
            )
            qr_source = cfg or inquiry_link or ""

        if qr_source:
            qr_img = qrcode.make(qr_source)
            bio    = io.BytesIO()
            qr_img.save(bio, format="PNG")
            bio.seek(0)
            bio.name = "qrcode.png"
            bot.send_photo(chat_id, bio, caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

    # also mirror to is_test=1 → test_report topic, else → purchase_log topic
    if item["is_test"]:
        send_to_topic("test_report",
            f"🧪 <b>تست رایگان</b>\n\n"
            f"👤 کاربر: <code>{chat_id}</code>\n"
            f"🧩 نوع: {esc(item['type_name'])}\n"
            f"📦 پکیج: {esc(item['package_name'])}\n"
            f"🔮 سرویس: {esc(service_name)}"
        )
    type_desc = item["type_description"] if item["type_description"] else ""
    if type_desc:
        from .premium_emoji import render_premium_text_html as _rph_desc
        rendered_desc = _rph_desc(type_desc, escape_plain_parts=True)
        bot.send_message(chat_id, f"📌 <b>توضیحات سرویس:</b>\n\n{rendered_desc}", parse_mode="HTML")

    # Check referral purchase reward (only for non-test purchases)
    if not item["is_test"]:
        try:
            check_and_give_referral_purchase_reward(chat_id)
        except Exception:
            pass
        try:
            notify_referral_first_purchase(chat_id)
        except Exception:
            pass


# ── Stock notifications ───────────────────────────────────────────────────────
def _notify_all_admins(text: str):
    """Send a text message to all owner admins and sub-admins."""
    if _own_notif_on("stock"):
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass
    if _bot_notif_on("stock"):
        import json as _json
        for row in get_all_admin_users():
            sub_id = row["user_id"]
            if sub_id in ADMIN_IDS:
                continue
            perms = _json.loads(row["permissions"] or "{}")
            if not (perms.get("full") or perms.get("settings") or perms.get("approve_payments")):
                continue
            try:
                bot.send_message(sub_id, text, parse_mode="HTML")
            except Exception:
                pass
    send_to_topic("stock_alert", text)


def check_and_notify_stock(package_id: int, package_name: str):
    """Check remaining manual config stock for a package and notify admins if thresholds crossed.

    Thresholds:
      - < 3 remaining → low-stock warning (once per crossing)
      - == 0 remaining → empty-stock alert (once)

    Flags are reset when admin replenishes stock (add_config resets them via setting_set).
    """
    from ..db import count_available_manual_configs, setting_get, setting_set
    remaining = count_available_manual_configs(package_id)

    if remaining == 0:
        # Empty-stock alert (higher priority — send even if low-stock was skipped)
        if setting_get(f"stock_empty_notif_{package_id}", "0") != "1":
            setting_set(f"stock_empty_notif_{package_id}", "1")
            # Also mark low-stock as sent so we don't send a spurious low-stock after
            setting_set(f"stock_low_notif_{package_id}", "1")
            text = (
                f"🚨 <b>موجودی به پایان رسید</b>\n\n"
                f"📦 پکیج: <b>{esc(package_name)}</b>\n\n"
                "موجودی مخزن کانفیگ این پکیج به صفر رسیده است.\n"
                "تا بارگذاری مجدد، سفارش‌ها به صف انتظار می‌روند."
            )
            _notify_all_admins(text)
    elif remaining < 3:
        if setting_get(f"stock_low_notif_{package_id}", "0") != "1":
            setting_set(f"stock_low_notif_{package_id}", "1")
            text = (
                f"⚠️ <b>موجودی در حال اتمام</b>\n\n"
                f"📦 پکیج: <b>{esc(package_name)}</b>\n"
                f"🔢 تعداد باقی‌مانده: <b>{remaining}</b>\n\n"
                "لطفاً موجودی مخزن کانفیگ را افزایش دهید."
            )
            _notify_all_admins(text)


# ── Admin notifications ────────────────────────────────────────────────────────
def admin_purchase_notify(method_label, user_row, package_row, purchase_id=None, amount=None, service_name=None):
    svc_name = service_name  # may be overridden by purchase record below
    paid_amount = amount
    if purchase_id:
        try:
            _p = get_purchase(purchase_id)
            if _p:
                if svc_name is None:
                    svc_name = urllib.parse.unquote(_p["service_name"]) if _p["service_name"] else None
                if paid_amount is None:
                    paid_amount = _p["amount"]
        except Exception:
            pass
    svc_line = f"🏷 نام سرویس: {esc(svc_name)}\n" if svc_name else ""
    orig_price = package_row['price']
    is_agent = user_row['is_agent'] if 'is_agent' in user_row.keys() else 0

    # Method label mapping
    _method_map = {"wallet": "کیف پول", "card": "کارت به کارت"}
    method_display = _method_map.get(str(method_label).lower(), method_label)

    # Username with @ prefix
    raw_username = user_row['username'] or ''
    if raw_username and not raw_username.startswith('@'):
        username_display = f"@{raw_username}"
    elif raw_username:
        username_display = raw_username
    else:
        username_display = 'ندارد'

    # Clickable user name link
    user_link = f"<a href='tg://user?id={user_row['user_id']}'>{esc(user_row['full_name'])}</a>"

    if paid_amount is not None and paid_amount < orig_price:
        disc_amount = orig_price - paid_amount
        price_line = (
            f"💰 مبلغ اصلی: {fmt_price(orig_price)} تومان\n"
            f"🎟 تخفیف: {fmt_price(disc_amount)} تومان\n"
            f"💚 مبلغ نهایی: {fmt_price(paid_amount)} تومان\n"
        )
    elif paid_amount is not None:
        price_line = f"💰 مبلغ: {fmt_price(paid_amount)} تومان\n"
    else:
        price_line = f"💰 مبلغ: {fmt_price(orig_price)} تومان\n"

    text = (
        f"❗️ | خرید جدید ({method_display})\n\n"
        f"🕐 زمان: {now_str()}\n"
        f"▫️ آیدی کاربر: <code>{user_row['user_id']}</code>\n"
        f"👨‍💼 نام: {user_link}\n"
        f"⚡️ نام کاربری: {username_display}\n"
        f"{price_line}"
        f"🚦 سرور: {esc(package_row['type_name'])}\n"
        f"✏️ پکیج: {esc(package_row['name'])}\n"
        f"{svc_line}"
        f"🔋 حجم: {package_row['volume_gb']} گیگ\n"
        f"⏰ مدت: {package_row['duration_days']} روز\n"
        f"👥 تعداد کاربر: {'نامحدود' if not (package_row['max_users'] if 'max_users' in package_row.keys() else 0) else str(package_row['max_users']) + ' کاربره'}"
    )
    if _own_notif_on("purchase_log"):
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text)
            except Exception:
                pass
    if _bot_notif_on("purchase_log"):
        for row in get_all_admin_users():
            sub_id = row["user_id"]
            if sub_id in ADMIN_IDS:
                continue
            perms = json.loads(row["permissions"] or "{}")
            if not (perms.get("full") or perms.get("approve_payments")):
                continue
            try:
                bot.send_message(sub_id, text)
            except Exception:
                pass
    send_to_topic("purchase_log", text)
    # If the buyer is an agent, also mirror to agency_log
    if user_row["is_agent"]:
        send_to_topic("agency_log", text)


def admin_renewal_notify(user_id, purchase_item, package_row, amount, method_label):
    user_row  = get_user(user_id)
    config_id = purchase_item["config_id"]
    orig_price = package_row['price'] if package_row and 'price' in package_row.keys() else amount
    is_agent = user_row['is_agent'] if user_row and 'is_agent' in user_row.keys() else 0

    # Method label mapping
    _method_map = {"wallet": "کیف پول", "card": "کارت به کارت"}
    method_display = _method_map.get(str(method_label).lower(), method_label)

    # Username with @ prefix
    raw_username = (user_row['username'] or '') if user_row else ''
    if raw_username and not raw_username.startswith('@'):
        username_display = f"@{raw_username}"
    elif raw_username:
        username_display = raw_username
    else:
        username_display = 'ندارد'

    # Clickable user name link
    if user_row:
        user_link = f"<a href='tg://user?id={user_row['user_id']}'>{esc(user_row['full_name'])}</a>"
    else:
        user_link = str(user_id)

    if amount < orig_price:
        disc_amount = orig_price - amount
        price_block = (
            f"💰 مبلغ اصلی: {fmt_price(orig_price)} تومان\n"
            f"🎟 تخفیف: {fmt_price(disc_amount)} تومان\n"
            f"💚 مبلغ نهایی: <b>{fmt_price(amount)}</b> تومان\n"
        )
    else:
        price_block = f"💰 مبلغ پرداختی: <b>{fmt_price(amount)}</b> تومان\n"
    text = (
        f"♻️ | <b>درخواست تمدید</b> ({method_display})\n\n"
        f"\U0001f552 زمان: {now_str()}\n"
        f"👤 کاربر: {user_link}\n"
        f"⚡️ نام کاربری: {username_display}\n"
        f"🆔 آیدی: <code>{user_id}</code>\n"
        f"{price_block}\n"
        f"📌 <b>سرویس فعلی:</b>\n"
        f"🏷 نام سرویس: {esc(urllib.parse.unquote(purchase_item['service_name'] or ''))}\n"
        f"🧩 نوع: {esc(purchase_item['type_name'])}\n\n"
        f"📦 <b>پکیج تمدید:</b>\n"
        f"✏️ نام: {esc(package_row['name'])}\n"
        f"🔋 حجم: {package_row['volume_gb']} گیگ\n"
        f"⏰ مدت: {package_row['duration_days']} روز\n"
        f"👥 تعداد کاربر: {'نامحدود' if not (package_row['max_users'] if 'max_users' in package_row.keys() else 0) else str(package_row['max_users']) + ' کاربره'}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ تمدید انجام شد",
                                       callback_data=f"renew:confirm:{config_id}:{user_id}"))
    if _own_notif_on("renewal_request"):
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, reply_markup=kb)
            except Exception:
                pass
    if _bot_notif_on("renewal_request"):
        for row in get_all_admin_users():
            sub_id = row["user_id"]
            if sub_id in ADMIN_IDS:
                continue
            perms = json.loads(row["permissions"] or "{}")
            if not (perms.get("full") or perms.get("approve_renewal")):
                continue
            try:
                bot.send_message(sub_id, text, reply_markup=kb)
            except Exception:
                pass
    send_to_topic("renewal_request", text, reply_markup=kb)
    # If the user is an agent, also mirror to agency_log
    if user_row and user_row["is_agent"]:
        send_to_topic("agency_log", text, reply_markup=kb)


def admin_addon_notify(user_id, config_id, addon_type, sd, final_amount, payment_method):
    """Send addon purchase log to purchase_log topic and relevant admins."""
    from ..db import get_panel_config as _gcfg
    user_row = get_user(user_id)
    cfg_row  = _gcfg(config_id)
    if not user_row:
        return

    method_display = {"wallet": "کیف پول", "card": "کارت به کارت"}.get(str(payment_method).lower(), payment_method)

    raw_username = (user_row["username"] or "") if user_row else ""
    username_display = f"@{raw_username}" if raw_username else "ندارد"
    user_link = f"<a href='tg://user?id={user_id}'>{esc(user_row['full_name'])}</a>"

    subtotal        = int(sd.get("subtotal", final_amount) or final_amount)
    discount_amount = int(sd.get("discount_amount", 0) or 0)
    unit_price      = int(sd.get("unit_price", 0) or 0)

    if addon_type == "volume":
        amount_str = f"{sd.get('amount_gb', 0)} گیگ"
        unit_str   = "هر گیگ"
        emoji      = "📦"
        title      = "خرید حجم اضافه"
    else:
        amount_str = f"{sd.get('amount_days', 0)} روز"
        unit_str   = "هر روز"
        emoji      = "⏰"
        title      = "خرید زمان اضافه"

    disc_line = f"🎁 تخفیف: <b>{fmt_price(discount_amount)} تومان</b>\n" if discount_amount else ""
    text = (
        f"🛒 | <b>{title}</b>\n\n"
        f"\U0001f552 زمان: {now_str()}\n"
        f"👤 کاربر: {user_link}\n"
        f"⚡️ نام کاربری: {username_display}\n"
        f"🆔 آیدی: <code>{user_id}</code>\n\n"
        f"{emoji} {('حجم' if addon_type == 'volume' else 'زمان')} اضافه: <b>{amount_str}</b>\n"
        f"💵 قیمت {unit_str}: <b>{fmt_price(unit_price)} تومان</b>\n"
        f"💰 مبلغ کل: <b>{fmt_price(subtotal)} تومان</b>\n"
        f"{disc_line}"
        f"✅ مبلغ نهایی: <b>{fmt_price(final_amount)} تومان</b>\n"
        f"💳 روش پرداخت: {method_display}"
    )
    if _own_notif_on("purchase_log"):
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text)
            except Exception:
                pass
    send_to_topic("purchase_log", text)


def notify_pending_order_to_admins(pending_id, user_id, package_row, amount, method):
    user = get_user(user_id)
    text = (
        f"⚠️ <b>سفارش در انتظار کانفیگ</b>\n\n"
        f"👤 کاربر: {esc(user['full_name'])}\n"
        f"🆔 آیدی: <code>{user_id}</code>\n"
        f"💰 مبلغ: {fmt_price(amount)} تومان\n"
        f"💳 روش پرداخت: {method}\n\n"
        f"📦 <b>پکیج:</b>\n"
        f"🧩 نوع: {esc(package_row['type_name'])}\n"
        f"✏️ نام: {esc(package_row['name'])}\n"
        f"🔋 حجم: {package_row['volume_gb']} گیگ\n"
        f"⏰ مدت: {package_row['duration_days']} روز\n"
        f"👥 تعداد کاربر: {'نامحدود' if not (package_row['max_users'] if 'max_users' in package_row.keys() else 0) else str(package_row['max_users']) + ' کاربره'}\n"
        f"�💰 قیمت: {fmt_price(package_row['price'])} تومان\n\n"
        "⚠️ موجودی تحویل فوری برای این پکیج تمام شده است.\n"
        "لطفاً برای این سفارش یک کانفیگ ثبت کنید:"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📝 ثبت کانفیگ برای این سفارش",
                                       callback_data=f"adm:pending:addcfg:{pending_id}"))
    if _own_notif_on("payment_approval"):
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, reply_markup=kb)
            except Exception:
                pass
    if _bot_notif_on("payment_approval"):
        for row in get_all_admin_users():
            sub_id = row["user_id"]
            if sub_id in ADMIN_IDS:
                continue
            perms = json.loads(row["permissions"] or "{}")
            if not (perms.get("full") or perms.get("approve_payments") or perms.get("approve_renewal")):
                continue
            try:
                bot.send_message(sub_id, text, reply_markup=kb)
            except Exception:
                pass
    send_to_topic("payment_approval", text, reply_markup=kb)


# ── Pending order fulfillment ──────────────────────────────────────────────────
def _complete_pending_order(pending_id, cfg_name, cfg_text, inquiry_link):
    """Register a new config, assign it to the pending-order user, deliver it."""
    p_row = get_pending_order(pending_id)
    if not p_row or p_row["status"] == "fulfilled":
        return False
    package_id = p_row["package_id"]
    user_id    = p_row["user_id"]
    pkg        = get_package(package_id)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO configs(service_name, config_text, inquiry_link, package_id, type_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (cfg_name, cfg_text, inquiry_link, package_id, pkg["type_id"] if pkg else None)
        )
        config_id = cur.lastrowid
    purchase_id = assign_config_to_user(
        config_id, user_id, package_id,
        p_row["amount"], p_row["payment_method"], is_test=0
    )
    fulfill_pending_order(pending_id)
    user = get_user(user_id)
    try:
        bot.send_message(
            user_id,
            "🎉 <b>کانفیگ شما آماده شد!</b>\n\n"
            "سفارش شما توسط پشتیبانی تکمیل شد. جزئیات سرویس در ادامه ارسال می‌شود."
        )
    except Exception:
        pass
    deliver_purchase_message(user_id, purchase_id)
    if pkg:
        admin_purchase_notify(p_row["payment_method"], user, pkg, purchase_id=purchase_id)
    return True


def auto_fulfill_pending_orders(package_id):
    """After new configs are added for a package, automatically fill waiting orders."""
    pending_list    = get_waiting_pending_orders_for_package(package_id)
    fulfilled_count = 0
    for p_row in pending_list:
        available = get_available_configs_for_package(package_id)
        if not available:
            break
        cfg        = available[0]
        user_id    = p_row["user_id"]
        pending_id = p_row["id"]
        try:
            purchase_id = assign_config_to_user(
                cfg["id"], user_id, package_id,
                p_row["amount"], p_row["payment_method"], is_test=0
            )
            fulfill_pending_order(pending_id)
        except Exception as e:
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(
                        admin_id,
                        f"⚠️ خطا در تحویل سفارش #{pending_id} به کاربر {user_id}:\n<code>{e}</code>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            continue
        try:
            bot.send_message(
                user_id,
                "🎉 <b>کانفیگ شما آماده شد!</b>\n\n"
                "سفارش شما تکمیل شد. جزئیات سرویس در ادامه ارسال می‌شود.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        try:
            deliver_purchase_message(user_id, purchase_id)
        except Exception:
            pass
        try:
            pkg  = get_package(package_id)
            user = get_user(user_id)
            if pkg and user:
                admin_purchase_notify(p_row["payment_method"], user, pkg, purchase_id=purchase_id)
        except Exception:
            pass
        fulfilled_count += 1
    return fulfilled_count


# ── Referral Reward Logic ──────────────────────────────────────────────────────
def _give_referral_reward(referrer_id, reward_prefix):
    """Give a referral reward to referrer_id immediately.
    reward_prefix: 'referral_start_reward' or 'referral_purchase_reward'
    source: 'start' if start-reward, 'purchase' if purchase-reward
    """
    source = "start" if "start" in reward_prefix else "purchase"
    reward_type = setting_get(f"{reward_prefix}_type", "wallet")
    if reward_type == "wallet":
        amount = int(setting_get(f"{reward_prefix}_amount", "0"))
        if amount <= 0:
            return
        update_balance(referrer_id, amount)
        try:
            bot.send_message(
                referrer_id,
                "🎁 <b>پاداش زیرمجموعه‌گیری!</b>\n\n"
                f"💰 مبلغ <b>{fmt_price(amount)}</b> تومان به کیف‌پول شما اضافه شد! 🎉",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        # Config reward — auto-deliver immediately
        pkg_id = setting_get(f"{reward_prefix}_package", "")
        if not pkg_id or not pkg_id.isdigit():
            return
        pkg = get_package(int(pkg_id))
        if not pkg:
            return
        config_source = (pkg["config_source"] or "manual") if "config_source" in (pkg.keys() if hasattr(pkg, "keys") else {}) else "manual"

        if config_source == "panel":
            # Panel package — create config dynamically via _deliver_bulk_configs
            try:
                from ..handlers.callbacks import _deliver_bulk_configs
                delivered_ids, pending_ids = _deliver_bulk_configs(
                    chat_id=referrer_id,
                    uid=referrer_id,
                    package_id=int(pkg_id),
                    total_amount=0,
                    payment_method="referral_gift",
                    quantity=1,
                    payment_id=None,
                )
            except Exception as _exc:
                print(f"[referral_reward] panel delivery failed for uid={referrer_id} pkg={pkg_id}: {_exc}")
                import traceback as _tb; print(_tb.format_exc())
                add_pending_reward(referrer_id, "config", 0, int(pkg_id), source)
                try:
                    bot.send_message(
                        referrer_id,
                        "🎁 <b>پاداش زیرمجموعه‌گیری!</b>\n\n"
                        "⚠️ در حال حاضر امکان ساخت سرویس وجود ندارد.\n"
                        "پاداش شما ذخیره شد و از بخش دعوت دوستان → «🎁 دریافت پاداش» قابل دریافت است.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            else:
                if delivered_ids:
                    try:
                        bot.send_message(
                            referrer_id,
                            "🎁 <b>پاداش زیرمجموعه‌گیری!</b>\n\n"
                            "✅ یک کانفیگ رایگان به سرویس‌های شما اضافه شد! 🎉",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                else:
                    # Create pending if panel delivery queued it
                    add_pending_reward(referrer_id, "config", 0, int(pkg_id), source)
                    try:
                        bot.send_message(
                            referrer_id,
                            "🎁 <b>پاداش زیرمجموعه‌گیری!</b>\n\n"
                            "⚠️ سفارش شما ثبت شد و به محض آماده شدن تحویل داده خواهد شد.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
            return

        # Manual/stock packages
        available = get_available_configs_for_package(int(pkg_id))
        if available:
            cfg = available[0]
            try:
                purchase_id = assign_config_to_user(
                    cfg["id"], referrer_id, int(pkg_id), 0, "referral_gift", is_test=0
                )
                try:
                    bot.send_message(
                        referrer_id,
                        "🎁 <b>پاداش زیرمجموعه‌گیری!</b>\n\n"
                        "✅ یک کانفیگ رایگان به سرویس‌های شما اضافه شد! 🎉",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                try:
                    deliver_purchase_message(referrer_id, purchase_id)
                except Exception:
                    pass
                return
            except Exception:
                pass
        # Fallback: no stock or assign failed — queue as pending
        add_pending_reward(referrer_id, "config", 0, int(pkg_id), source)
        try:
            bot.send_message(
                referrer_id,
                "🎁 <b>پاداش زیرمجموعه‌گیری!</b>\n\n"
                "⚠️ در حال حاضر موجودی کانفیگ تمام شده.\n"
                "پاداش شما ذخیره شد و به محض اضافه شدن موجودی، از بخش دعوت دوستان → «🎁 دریافت پاداش» قابل دریافت است.",
                parse_mode="HTML"
            )
        except Exception:
            pass


def notify_referral_join(referrer_id, referee_id):
    """Send a join-referral log to admins (own/bot) and the referral_log topic.
    Also send a real-time notification to the inviter."""
    if setting_get("referral_enabled", "1") != "1":
        return
    referrer = get_user(referrer_id)
    referee  = get_user(referee_id)
    if not referrer or not referee:
        return
    total = count_referrals(referrer_id)

    # ── Notify the INVITER directly ────────────────────────────────────────
    try:
        # Build clickable referee link
        ref_username = referee["username"] if referee["username"] else None
        if ref_username:
            referee_link = f"@{esc(ref_username)}"
        else:
            referee_link = f"<a href=\"tg://user?id={referee_id}\">{esc(referee['full_name'] or 'کاربر جدید')}</a>"

        start_enabled = setting_get("referral_start_reward_enabled", "0") == "1"
        required_count = int(setting_get("referral_start_reward_count", "1") or "1")
        with get_conn() as conn:
            # Count all unrewarded referrals that have NOT failed captcha.
            # No channel/captcha filter here — we want raw "people who came via your link"
            # count (excluding those who explicitly failed captcha).
            unrewarded = conn.execute(
                "SELECT COUNT(*) AS n FROM referrals "
                "WHERE referrer_id=? AND start_reward_given=0 AND captcha_failed=0",
                (referrer_id,)
            ).fetchone()["n"]
        progress = unrewarded if unrewarded <= required_count else unrewarded % required_count or required_count

        progress_line = ""
        if start_enabled and required_count > 0:
            progress_line = f"\n\n⭐️ {progress} دعوت از {required_count} دعوت برای دریافت پاداش"

        inviter_text = (
            f"💃 <b>به به!</b>\n\n"
            f"کاربر {referee_link} از طریق لینک دعوتت اومد تو ربات! 🎉"
            f"{progress_line}\n\n"
            f"👥 تعداد دعوت‌های کل: <b>{total}</b>"
        )
        bot.send_message(referrer_id, inviter_text, parse_mode="HTML")
    except Exception:
        pass

    # ── Admin / topic log ──────────────────────────────────────────────────
    text = (
        f"🔗 <b>زیرمجموعه‌گیری جدید</b>\n\n"
        f"👤 <b>دعوت‌کننده:</b>\n"
        f"▫️ نام: {esc(referrer['full_name'])}\n"
        f"⚡️ نام کاربری: {esc(referrer['username'] or 'ندارد')}\n"
        f"🆔 آیدی: <code>{referrer_id}</code>\n"
        f"👥 کل زیرمجموعه‌ها: <b>{total}</b>\n\n"
        f"🆕 <b>کاربر جدید (زیرمجموعه):</b>\n"
        f"▫️ نام: {esc(referee['full_name'])}\n"
        f"⚡️ نام کاربری: {esc(referee['username'] or 'ندارد')}\n"
        f"🆔 آیدی: <code>{referee_id}</code>"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👤 دعوت‌کننده", url=f"tg://user?id={referrer_id}"),
        types.InlineKeyboardButton("🆕 زیرمجموعه",  url=f"tg://user?id={referee_id}"),
    )
    if _own_notif_on("referral_log"):
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass
    if _bot_notif_on("referral_log"):
        for row in get_all_admin_users():
            sub_id = row["user_id"]
            if sub_id in ADMIN_IDS:
                continue
            try:
                bot.send_message(sub_id, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass
    send_to_topic("referral_log", text, reply_markup=kb)

    # Anti-spam check — runs after join notification is sent
    try:
        check_referral_antispam(referrer_id)
    except Exception:
        pass


def notify_referral_first_purchase(referee_id):
    """Called after a purchase. If buyer was referred AND this is their first purchase, log the event to referral_log."""
    ref = get_referral_by_referee(referee_id)
    if not ref:
        return
    # Only notify for the very first non-test purchase
    with get_conn() as conn:
        purchase_count = conn.execute(
            "SELECT COUNT(*) AS n FROM purchases WHERE user_id=? AND is_test=0",
            (referee_id,)
        ).fetchone()["n"]
    if purchase_count != 1:
        return
    referrer_id = ref["referrer_id"]
    referrer = get_user(referrer_id)
    referee  = get_user(referee_id)
    if not referrer or not referee:
        return
    text = (
        f"🛍 <b>اولین خرید زیرمجموعه</b>\n\n"
        f"👤 <b>دعوت‌کننده:</b>\n"
        f"▫️ نام: {esc(referrer['full_name'])}\n"
        f"⚡️ نام کاربری: {esc(referrer['username'] or 'ندارد')}\n"
        f"🆔 آیدی: <code>{referrer_id}</code>\n\n"
        f"🛒 <b>خریدار (زیرمجموعه):</b>\n"
        f"▫️ نام: {esc(referee['full_name'])}\n"
        f"⚡️ نام کاربری: {esc(referee['username'] or 'ندارد')}\n"
        f"🆔 آیدی: <code>{referee_id}</code>"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👤 دعوت‌کننده", url=f"tg://user?id={referrer_id}"),
        types.InlineKeyboardButton("🛒 خریدار",      url=f"tg://user?id={referee_id}"),
    )
    if _own_notif_on("referral_log"):
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass
    if _bot_notif_on("referral_log"):
        for row in get_all_admin_users():
            sub_id = row["user_id"]
            if sub_id in ADMIN_IDS:
                continue
            try:
                bot.send_message(sub_id, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass
    send_to_topic("referral_log", text, reply_markup=kb)


def _channel_reward_required() -> bool:
    """Return True if channel membership is required before giving the start reward."""
    if setting_get("referral_reward_condition", "channel") != "channel":
        return False
    # Check legacy setting first
    if setting_get("channel_id", "").strip():
        return True
    # Check new locked_channels table
    try:
        return bool(get_locked_channels())
    except Exception:
        return False


def check_and_give_referral_start_reward(referrer_id):
    """
    Check if referrer qualifies for start reward(s) and give one per complete batch.
    Thread-safe: atomic SQL claim prevents double-rewarding across concurrent calls.
    Loops so that if user passed multiple thresholds (e.g. 10 invites, threshold=5)
    they get the correct number of rewards.
    """
    if setting_get("referral_start_reward_enabled", "0") != "1":
        return
    # Skip reward for referral-restricted or fully-restricted users
    if get_referral_restriction(referrer_id):
        return
    required_count = int(setting_get("referral_start_reward_count", "1") or "1")
    if required_count <= 0:
        return
    channel_required = _channel_reward_required()
    captcha_required = setting_get("referral_captcha_enabled", "1") == "1"
    # Loop: give one reward per complete batch claimed atomically
    while try_claim_start_reward_batch(referrer_id, required_count, channel_required, captcha_required):
        _give_referral_reward(referrer_id, "referral_start_reward")


def try_give_referral_start_reward_for_channel_join(referee_id: int) -> None:
    """
    Called when a referee confirms channel membership (via check_channel callback
    OR immediately at /start if they were already a member).

    Flow:
    1. Look up the referral record — if none, nothing to do.
    2. Atomically set channel_joined 0→1. If it was already 1, stop (dedup).
    3. If captcha enabled: send captcha prompt (reward deferred until captcha solved).
    4. If captcha disabled: notify the referee and try to give start reward.

    NOTE: We do NOT check referral_start_reward_enabled here so that
    channel_joined is always recorded regardless of whether the reward feature
    is currently on.  That way, turning the feature on later will correctly
    count already-joined referees.
    """
    if setting_get("referral_enabled", "1") != "1":
        return  # referral system fully disabled
    if not _channel_reward_required():
        return  # condition is start_only — reward already given at /start time

    # First look up the referral — bail early if this user wasn't referred
    ref = get_referral_by_referee(referee_id)
    if not ref:
        return

    referrer_id = ref["referrer_id"]

    # Atomic 0→1 transition; returns False if already set (join/leave dedup)
    was_new_join = set_referral_channel_joined(referee_id)
    if not was_new_join:
        return  # already processed — could be duplicate event or re-join

    captcha_enabled = setting_get("referral_captcha_enabled", "1") == "1"

    if captcha_enabled:
        # Defer reward until captcha is solved — send captcha to referee
        send_captcha_prompt(referee_id)
        return

    # Captcha disabled — original behaviour: notify referee and give reward
    try:
        bot.send_message(
            referee_id,
            "✅ <b>عضویت شما تأیید شد!</b>\n\n"
            "🎉 تبریک! دعوت شما کامل شد و اکنون می‌توانید از تمام امکانات ربات استفاده کنید.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Now try to give the start reward to the referrer
    check_and_give_referral_start_reward(referrer_id)


def check_and_give_referral_purchase_reward(buyer_user_id):
    """
    Called after a purchase. Check if buyer was referred and give purchase reward(s).
    Uses atomic SQL claim (try_claim_purchase_reward_batch) to prevent double-rewarding.
    Loops so multiple thresholds crossed in one purchase are all rewarded correctly.
    """
    if setting_get("referral_enabled", "1") != "1":
        return
    if setting_get("referral_purchase_reward_enabled", "0") != "1":
        return
    ref = get_referral_by_referee(buyer_user_id)
    if not ref:
        return
    referrer_id = ref["referrer_id"]
    # Skip reward for referral-restricted or fully-restricted users
    if get_referral_restriction(referrer_id):
        return
    required_count = int(setting_get("referral_purchase_reward_count", "1") or "1")
    if required_count <= 0:
        return
    # Loop: give one reward per complete batch claimed atomically
    while try_claim_purchase_reward_batch(referrer_id, required_count):
        _give_referral_reward(referrer_id, "referral_purchase_reward")


# ── Referral Anti-Spam Detection ───────────────────────────────────────────────

def _notify_admins_antispam(referrer_id: int, user, detected_count: int,
                             threshold: int, window: int, action: str) -> None:
    """Send anti-spam alert to all admins (owner + sub-admins)."""
    action_labels = {
        "referral_ban": "محدود کامل از زیرمجموعه‌گیری",
        "full_ban":     "محدود شدن از کل ربات",
        "report_only":  "فقط گزارش به ادمین (بدون محدودیت خودکار)",
    }
    action_fa = action_labels.get(action, action)
    name_fa   = esc(user["full_name"]) if user else f"<code>{referrer_id}</code>"
    uname_fa  = f"@{esc(user['username'])}" if user and user["username"] else "ندارد"
    text = (
        f"⚠️ <b>هشدار ضد اسپم زیرمجموعه‌گیری</b>\n\n"
        f"👤 <b>کاربر مشکوک:</b>\n"
        f"▫️ نام: {name_fa}\n"
        f"⚡️ نام کاربری: {uname_fa}\n"
        f"🆔 آیدی: <code>{referrer_id}</code>\n\n"
        f"📊 <b>جزئیات تشخیص:</b>\n"
        f"🔢 دعوت‌های تشخیص داده‌شده: <b>{detected_count}</b>\n"
        f"⏱ در بازه زمانی: <b>{window} ثانیه</b>\n"
        f"🎯 آستانه تنظیم‌شده: <b>{threshold} دعوت</b>\n\n"
        f"🛡 <b>اقدام انجام‌شده:</b> {action_fa}\n\n"
    )
    if action == "referral_ban":
        text += (
            "این کاربر به دلیل مشکوک بودن به تقلب در زیرمجموعه‌گیری، "
            "به‌صورت کامل از زیرمجموعه‌گیری محدود شد. "
            "تا زمان حذف از لیست محدودیت، جایزه‌ای به او تعلق نخواهد گرفت."
        )
    elif action == "full_ban":
        text += (
            "این کاربر به دلیل مشکوک بودن به تقلب در زیرمجموعه‌گیری، "
            "به‌صورت کامل از ربات محدود شد."
        )
    else:
        text += (
            "این شخص مشکوک به تقلب در زیرمجموعه‌گیری است. "
            "لطفاً بررسی کنید و در صورت نیاز او را به لیست محدودیت‌ها اضافه کنید."
        )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "👤 مشاهده کاربر", url=f"tg://user?id={referrer_id}"
    ))

    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
    for row in get_all_admin_users():
        sub_id = row["user_id"]
        if sub_id in ADMIN_IDS:
            continue
        try:
            bot.send_message(sub_id, text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
    send_to_topic("referral_log", text, reply_markup=kb)


def check_referral_antispam(referrer_id: int) -> None:
    """
    Check if referrer is doing burst invites and act according to configured action.
    Called after every successful referral registration (from notify_referral_join).
    Safe to call repeatedly — deduplicates via referral_spam_events table.
    """
    if setting_get("referral_antispam_enabled", "0") != "1":
        return

    # Already restricted → no need to re-evaluate
    if get_referral_restriction(referrer_id):
        return

    # Already flagged for spam → avoid duplicate admin notifications
    if has_referral_spam_event(referrer_id):
        return

    try:
        window    = max(1, int(setting_get("referral_antispam_window", "15") or "15"))
        threshold = max(1, int(setting_get("referral_antispam_threshold", "10") or "10"))
    except (ValueError, TypeError):
        return

    action = setting_get("referral_antispam_action", "report_only")

    recent_count = count_recent_referrals(referrer_id, window)
    if recent_count < threshold:
        return

    # ── Suspicious! Apply configured action ──────────────────────────────────
    user = get_user(referrer_id)

    if action == "referral_ban":
        add_referral_restriction(
            referrer_id, "referral_only",
            reason="auto_antispam", added_by=0,
        )
        record_referral_spam_event(referrer_id, "referral_ban")
        # Inform the user
        try:
            bot.send_message(
                referrer_id,
                "⛔️ <b>محدودیت موقت</b>\n\n"
                "به دلیل رفتار مشکوک در زیرمجموعه‌گیری، دسترسی شما به بخش دعوت دوستان "
                "به‌صورت موقت محدود شده است.\n\n"
                "در صورت نیاز با پشتیبانی تماس بگیرید.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    elif action == "full_ban":
        add_referral_restriction(
            referrer_id, "full",
            reason="auto_antispam", added_by=0,
        )
        set_user_restricted(referrer_id, 0)   # permanent full bot ban
        record_referral_spam_event(referrer_id, "full_ban")

    elif action == "report_only":
        record_referral_spam_event(referrer_id, "report_only")

    # Notify admins regardless of action
    try:
        _notify_admins_antispam(referrer_id, user, recent_count, threshold, window, action)
    except Exception:
        pass
