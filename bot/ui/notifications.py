# -*- coding: utf-8 -*-
"""
User and admin notification helpers: purchase delivery, admin alerts,
pending-order fulfillment.
"""
import io
import json
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
)
from ..helpers import esc, fmt_price, now_str, move_leading_emoji
from ..bot_instance import bot
from ..group_manager import send_to_topic
from .premium_emoji import ce


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
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="nav:main"))

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
        inq_line    = f"\n🔋 Volume web: {inquiry_link}" if inquiry_link else ""

        if cfg_type == "ovpn":
            username = cfg_data.get("username", "")
            password = cfg_data.get("password", "")
            caption = (
                f"{ce('✅', '5260463209562776385')} <b>{title_line}</b>\n\n"
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
        else:  # wg
            caption = (
                f"{ce('✅', '5260463209562776385')} <b>{title_line}</b>\n\n"
                f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(item['type_name'])}</b>\n"
                f"{package_line}"
                f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(vol_text)}</b>\n"
                f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(dur_text)}</b>\n"
                f"{ce('👥', '5372926953978341366')} نوع کاربری: <b>{esc(users_label)}</b>\n"
                f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>"
                f"{inq_line}"
                f"{expired_note}"
            )
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
                f"{ce('✅', '5260463209562776385')} <b>{title_line}</b>\n\n"
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
                f"{ce('✅', '5260463209562776385')} <b>{title_line}</b>\n\n"
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
                f"{ce('✅', '5260463209562776385')} <b>{title_line}</b>\n\n"
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
                f"{ce('✅', '5260463209562776385')} <b>{title_line}</b>\n\n"
                f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>\n"
                f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(item['type_name'])}</b>\n"
                f"{package_line}"
                f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(_vol_text_v2)}</b>\n"
                f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(_dur_text_v2)}</b>\n"
                f"{ce('👥', '5372926953978341366')} تعداد کاربر: <b>{esc(_users_v2)}</b>\n\n"
                f"{ce('💝', '5900197669178970457')} <b>Config:</b>\n<code>{esc(cfg or '-')}</code>\n\n"
                f"🔋 Volume web: {esc(inquiry_link or '-')}"
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


# ── Admin notifications ────────────────────────────────────────────────────────
def admin_purchase_notify(method_label, user_row, package_row, purchase_id=None):
    svc_name = None
    if purchase_id:
        try:
            _p = get_purchase(purchase_id)
            svc_name = urllib.parse.unquote(_p["service_name"]) if _p and _p["service_name"] else None
        except Exception:
            pass
    svc_line = f"🏷 نام سرویس: {esc(svc_name)}\n" if svc_name else ""
    text = (
        f"❗️ | خرید جدید ({method_label})\n\n"
        f"🕐 زمان: {now_str()}\n"
        f"▫️ آیدی کاربر: <code>{user_row['user_id']}</code>\n"
        f"👨‍💼 نام: {esc(user_row['full_name'])}\n"
        f"⚡️ نام کاربری: {esc(user_row['username'] or 'ندارد')}\n"
        f"💰 مبلغ: {fmt_price(package_row['price'])} تومان\n"
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
    text = (
        f"♻️ | <b>درخواست تمدید</b> ({method_label})\n\n"
        f"� زمان: {now_str()}\n"
        f"👤 کاربر: {esc(user_row['full_name'])}\n"
        f"⚡️ نام کاربری: {esc(user_row['username'] or 'ندارد')}\n"
        f"🆔 آیدی: <code>{user_row['user_id']}</code>\n"
        f"💰 مبلغ پرداختی: <b>{fmt_price(amount)}</b> تومان\n\n"
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
        channel_required = _channel_reward_required()
        ch = "AND channel_joined=1" if channel_required else ""
        with get_conn() as conn:
            unrewarded = conn.execute(
                f"SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=? AND start_reward_given=0 {ch}",
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
    return (
        setting_get("referral_reward_condition", "channel") == "channel"
        and bool(setting_get("channel_id", "").strip())
    )


def check_and_give_referral_start_reward(referrer_id):
    """
    Check if referrer qualifies for start reward(s) and give one per complete batch.
    Thread-safe: atomic SQL claim prevents double-rewarding across concurrent calls.
    Loops so that if user passed multiple thresholds (e.g. 10 invites, threshold=5)
    they get the correct number of rewards.
    """
    if setting_get("referral_start_reward_enabled", "0") != "1":
        return
    required_count = int(setting_get("referral_start_reward_count", "1") or "1")
    if required_count <= 0:
        return
    channel_required = _channel_reward_required()
    # Loop: give one reward per complete batch claimed atomically
    while try_claim_start_reward_batch(referrer_id, required_count, channel_required):
        _give_referral_reward(referrer_id, "referral_start_reward")


def try_give_referral_start_reward_for_channel_join(referee_id: int) -> None:
    """
    Called when a referee confirms channel membership (via check_channel callback
    OR immediately at /start if they were already a member).

    Flow:
    1. Look up the referral record — if none, nothing to do.
    2. Atomically set channel_joined 0→1. If it was already 1, stop (dedup).
    3. Notify the referee that their join is complete.
    4. Try to give the start reward to the referrer (atomic claim).

    NOTE: We do NOT check referral_start_reward_enabled here so that
    channel_joined is always recorded regardless of whether the reward feature
    is currently on.  That way, turning the feature on later will correctly
    count already-joined referees.
    """
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

    # Notify the referee (friendly UX — non-critical)
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
    if setting_get("referral_purchase_reward_enabled", "0") != "1":
        return
    ref = get_referral_by_referee(buyer_user_id)
    if not ref:
        return
    referrer_id = ref["referrer_id"]
    required_count = int(setting_get("referral_purchase_reward_count", "1") or "1")
    if required_count <= 0:
        return
    # Loop: give one reward per complete batch claimed atomically
    while try_claim_purchase_reward_batch(referrer_id, required_count):
        _give_referral_reward(referrer_id, "referral_purchase_reward")
