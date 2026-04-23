# -*- coding: utf-8 -*-
import json
import logging
import time
import threading
import traceback
import urllib.parse
from datetime import datetime, timedelta
from telebot import types

log = logging.getLogger(__name__)
from ..config import ADMIN_IDS, ADMIN_PERMS, PERM_FULL_SET, PERM_USER_FULL, PERM_EMOJI_IDS, CRYPTO_COINS, CRYPTO_API_SYMBOLS, CRYPTO_EMOJI_IDS, CONFIGS_PER_PAGE
from ..bot_instance import bot
from ..helpers import (
    esc, fmt_price, fmt_vol, fmt_dur, now_str, display_name, display_username, safe_support_url,
    is_admin, admin_has_perm, back_button,
    state_set, state_clear, state_name, state_data, parse_int, normalize_text_number,
    move_leading_emoji, _TZ_TEHRAN,
)
from ..db import (
    setting_get, setting_set,
    ensure_user, get_user, get_users, count_all_users, set_user_status,
    set_user_restricted, check_and_release_restriction,
    set_user_agent, update_balance, get_user_detail, get_user_purchases,
    get_purchase, get_available_configs_for_package,
    get_all_types, get_active_types, get_type, add_type, update_type, update_type_description, update_type_active, delete_type,
    get_packages, get_package, add_package, update_package_field, toggle_package_active, delete_package,
    get_registered_packages_stock, get_configs_paginated, count_configs,
    expire_config, add_config,
    assign_config_to_user, reserve_first_config, release_reserved_config,
    update_config_field,
    get_payment, get_pending_payments_page, create_payment, approve_payment, reject_payment, complete_payment,
    update_payment_final_amount,
    get_agency_price, set_agency_price,
    get_agency_price_config, set_agency_price_config,
    get_agency_type_discount, set_agency_type_discount,
    get_agencies,
    get_all_admin_users, get_admin_user, add_admin_user, update_admin_permissions, remove_admin_user,
    get_conn, create_pending_order, get_pending_order, add_config, search_users,
    should_show_bulk_qty, get_bulk_qty_limits,
    reset_all_free_tests, user_has_any_test, agent_test_count_in_period,
    get_all_pinned_messages, get_pinned_message, add_pinned_message,
    update_pinned_message, delete_pinned_message,
    save_pinned_send, get_pinned_sends, delete_pinned_sends,
    save_payment_admin_message, get_payment_admin_messages, delete_payment_admin_messages,
    save_agency_request_message, get_agency_request_messages, delete_agency_request_messages,
    get_all_discount_codes, get_discount_code, add_discount_code,
    toggle_discount_code, update_discount_code_field, delete_discount_code,
    validate_discount_code, record_discount_usage, has_eligible_discount_codes,
    get_discount_code_targets, set_discount_code_targets,
    reject_all_pending_payments,
    add_voucher_batch, get_all_voucher_batches, get_voucher_batch,
    get_voucher_codes_for_batch, get_voucher_code_by_code,
    redeem_voucher_code, delete_voucher_batch,
    get_phone_number,
    has_pending_rewards, get_unclaimed_rewards, mark_rewards_claimed, mark_reward_claimed_by_id,
    get_locked_channels, add_locked_channel, remove_locked_channel_by_id,
    wallet_pay_enabled_for, get_wallet_pay_exceptions, add_wallet_pay_exception, remove_wallet_pay_exception,
    get_referral_restriction, add_referral_restriction,
    remove_referral_restriction_by_id, remove_referral_restriction_by_user,
    toggle_referral_restriction_type, get_referral_restrictions_paged,
    set_user_restricted as _set_user_restricted_db,
    # Card management
    get_payment_cards, get_payment_card, add_payment_card, update_payment_card,
    toggle_payment_card_active, delete_payment_card, pick_card_for_payment,
    # Fee / Bonus
    get_gateway_fee_amount, get_gateway_bonus_amount, apply_gateway_fee,
)
from ..gateways.base import is_gateway_available, is_card_info_complete, get_gateway_range_text, is_gateway_in_range, build_gateway_range_guide
from ..gateways.crypto import fetch_crypto_prices
from ..gateways.tetrapay import create_tetrapay_order, verify_tetrapay_order
from ..gateways.swapwallet_crypto import (
    create_swapwallet_crypto_invoice, check_swapwallet_crypto_invoice,
    show_swapwallet_crypto_page,
)
from ..gateways.tronpays_rial import (
    create_tronpays_rial_invoice, check_tronpays_rial_invoice, is_tronpays_paid,
)
from ..ui.helpers import send_or_edit, check_channel_membership, channel_lock_message
from ..ui.helpers import _invalidate_channel_cache
from ..ui.keyboards import kb_main, kb_admin_panel
from ..ui.menus import show_main_menu, show_profile, show_support, show_my_configs, show_referral_menu
from ..ui.notifications import (
    deliver_purchase_message, admin_purchase_notify, admin_renewal_notify,
    notify_pending_order_to_admins, _complete_pending_order, auto_fulfill_pending_orders,
)
from ..group_manager import (
    ensure_group_topics, reset_and_recreate_topics, get_group_id,
    _count_active_topics, TOPICS, send_to_topic, log_admin_action,
)
from ..payments import (
    get_effective_price, show_payment_method_selection,
    show_crypto_selection, show_crypto_payment_info,
    send_payment_to_admins, finish_card_payment_approval,
    apply_gateway_bonus_if_needed,
)
from ..admin.renderers import (
    _show_admin_types, _show_admin_stock, _show_admin_admins_panel,
    _show_perm_selection, _show_admin_users_list, _show_admin_user_detail,
    _show_admin_user_detail_msg, _show_admin_assign_config_type, _fake_call,
    _show_admin_panels, _show_panel_detail,
    _show_panel_client_packages, _show_panel_client_package_preview,
    _show_panel_edit_menu, _show_cpkg_edit_menu,
)
from ..admin.backup import _send_backup
from ..db import (
    get_all_panels, get_panel, add_panel, update_panel_field,
    toggle_panel_active, update_panel_status, delete_panel,
    update_package_panel_settings,
    add_panel_config, get_panel_configs, get_panel_configs_count,
    add_panel_client_package, get_panel_client_packages,
    get_panel_client_package, get_panel_client_package_by_inbound,
    delete_panel_client_package,
    update_panel_client_package_samples, update_panel_client_package_field,
    get_panel_configs_by_cpkg, update_panel_config_texts,
    bulk_add_balance, bulk_zero_balance, bulk_set_status, count_users_by_filter,
    get_user_purchases_paged, get_user_panel_configs_paged,
    get_referrals_paged, count_referrals,
)


# ── OpenVPN helpers (shared with messages.py) ─────────────────────────────────

def _fmt_users_label(max_users):
    if not max_users or max_users == 0:
        return "نامحدود"
    if max_users == 1:
        return "تک‌کاربره"
    if max_users == 2:
        return "دوکاربره"
    return f"{max_users} کاربره"


# ── V2Ray helpers ─────────────────────────────────────────────────────────────

def _v2_name_from_sub(sub_url: str) -> str:
    """Extract service name from the last path segment of a subscription URL.

    Example:
        http://s1.example.xyz:2096/sub/n1lw9my64qykgz4n → n1lw9my64qykgz4n
    """
    if not sub_url:
        return "sub"
    try:
        path = urllib.parse.urlparse(sub_url.strip()).path
        segments = [s for s in path.split("/") if s]
        return segments[-1] if segments else "sub"
    except Exception:
        return (sub_url.rsplit("/", 1)[-1] or "sub")


def _v2_name_from_vmess(cfg_text: str) -> str:
    """Extract the 'ps' (presentation name) field from a VMess base64 config.
    Falls back to host:port or 'VMess Config' on any error.
    """
    import base64, json as _json
    try:
        # Strip vmess:// prefix and any trailing #tag
        body = cfg_text[8:].split("#")[0]
        # Pad to multiple of 4
        padded = body + "=" * (-len(body) % 4)
        data = _json.loads(base64.b64decode(padded).decode("utf-8"))
        ps = (data.get("ps") or "").strip()
        if ps:
            return ps
        host = (data.get("add") or data.get("host") or "").strip()
        port = str(data.get("port", "")).strip()
        return f"{host}:{port}" if host else "VMess Config"
    except Exception:
        return "VMess Config"


def _v2_name_from_config(cfg_text: str, prefix: str = "", suffix: str = "") -> str:
    """Extract and clean service name from a V2Ray config's URL-encoded #tag.

    For vmess:// configs that lack a #tag, decodes the base64 JSON and uses
    the 'ps' field (then host:port) as name.
    """
    # VMess special handling: decode base64 JSON for the ps field
    if cfg_text.startswith("vmess://"):
        if "#" not in cfg_text:
            return _v2_name_from_vmess(cfg_text)
        # Has a #tag — use the tag (normal path below), but fall back to ps if empty
        raw_tag = cfg_text.rsplit("#", 1)[1].strip()
        if not raw_tag:
            return _v2_name_from_vmess(cfg_text)

    if "#" in cfg_text:
        raw = cfg_text.rsplit("#", 1)[1]
    else:
        return "config"
    try:
        name = urllib.parse.unquote(raw)
    except Exception:
        name = raw
    # Strip prefix
    if prefix:
        if name.startswith(prefix):
            name = name[len(prefix):]
        try:
            dp = urllib.parse.unquote(prefix)
            if dp != prefix and name.startswith(dp):
                name = name[len(dp):]
        except Exception:
            pass
    # Strip suffix
    if suffix:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
        try:
            ds = urllib.parse.unquote(suffix)
            if ds != suffix and name.endswith(ds):
                name = name[:-len(ds)]
        except Exception:
            pass
    return name.strip().strip("-").strip("_").strip() or "config"


def _v2_bulk_data_prompt(mode: int) -> str:
    """Return the instruction message for the admin based on bulk V2Ray mode."""
    if mode == 1:  # config+sub interleaved (few)
        return (
            "📋 <b>ثبت عمده V2Ray — کانفیگ + ساب (مناسب تعداد کم)</b>\n\n"
            "کانفیگ‌ها و ساب‌ها را به‌صورت <b>یکی در میان</b> وارد کنید:\n\n"
            "💡 فرمت:\n"
            "<code>vless://abc...#name1\n"
            "http://panel.com/sub/token1\n"
            "vless://def...#name2\n"
            "http://panel.com/sub/token2</code>\n\n"
            "یعنی هر کانفیگ بلافاصله با ساب مربوط به خودش بیاید.\n\n"
            "📎 یا می‌توانید محتوا را در یک فایل <b>.txt</b> ارسال کنید."
        )
    if mode == 3:  # config only
        return (
            "📋 <b>ثبت عمده V2Ray — کانفیگ تنها</b>\n\n"
            "همه کانفیگ‌ها را ارسال کنید. هر خط یک کانفیگ:\n\n"
            "💡 مثال:\n"
            "<code>vless://abc...#name1\n"
            "vless://def...#name2</code>\n\n"
            "📎 یا می‌توانید محتوا را در یک فایل <b>.txt</b> ارسال کنید."
        )
    if mode == 4:  # sub only
        return (
            "📋 <b>ثبت عمده V2Ray — ساب تنها</b>\n\n"
            "همه لینک‌های ساب را ارسال کنید. هر خط یک ساب:\n\n"
            "💡 مثال:\n"
            "<code>http://s1.example.com:2096/sub/token1\n"
            "http://s1.example.com:2096/sub/token2</code>\n\n"
            "نام سرویس هر ساب به‌صورت خودکار از انتهای لینک استخراج می‌شود.\n\n"
            "📎 یا می‌توانید محتوا را در یک فایل <b>.txt</b> ارسال کنید."
        )
    if mode == 2:  # config+sub separated (many) — step 1: configs
        return (
            "📋 <b>ثبت عمده V2Ray — کانفیگ + ساب (مناسب تعداد زیاد) — مرحله اول</b>\n\n"
            "ابتدا <b>همه کانفیگ‌ها</b> را ارسال کنید (هر خط یک کانفیگ):\n\n"
            "💡 مثال:\n"
            "<code>vless://abc...#name1\n"
            "vless://def...#name2</code>\n\n"
            "📎 یا می‌توانید محتوا را در یک فایل <b>.txt</b> ارسال کنید."
        )
    return ""


def _ovpn_caption(pkg_row, username, password, inquiry):
    users_label = _fmt_users_label(pkg_row["max_users"] if "max_users" in pkg_row.keys() else 0)
    vol_text    = "نامحدود" if not pkg_row["volume_gb"] else f"{pkg_row['volume_gb']} گیگ"
    dur_text    = "نامحدود" if not pkg_row["duration_days"] else f"{pkg_row['duration_days']} روز"
    inq_line    = f"\n🔋 Volume web: {inquiry}" if inquiry else ""
    return (
        f"🧩 نوع سرویس: <code>{esc(pkg_row['type_name'])}</code>\n"
        f"📦 پکیج: <code>{esc(pkg_row['name'])}</code>\n"
        f"🔋 حجم: <code>{esc(vol_text)}</code>\n"
        f"⏰ مدت: <code>{esc(dur_text)}</code>\n"
        f"👤 کاربر: <code>{esc(users_label)}</code>\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"🔐 اطلاعات اکانت\n"
        f"username: <code>{esc(username)}</code>\n"
        f"password: <code>{esc(password)}</code>"
        f"{inq_line}"
    )


def _ovpn_send_file_group(chat_id, file_ids, caption):
    if not file_ids:
        return
    if len(file_ids) == 1:
        bot.send_document(chat_id, file_ids[0], caption=caption, parse_mode="HTML")
        return
    # Chunk into groups of 10 (Telegram media group limit)
    chunks = [file_ids[i:i + 10] for i in range(0, len(file_ids), 10)]
    for idx, chunk in enumerate(chunks):
        is_last = (idx == len(chunks) - 1)
        if is_last:
            media = [types.InputMediaDocument(fid) for fid in chunk[:-1]]
            media.append(types.InputMediaDocument(chunk[-1], caption=caption, parse_mode="HTML"))
        else:
            media = [types.InputMediaDocument(fid) for fid in chunk]
        bot.send_media_group(chat_id, media)


def _ovpn_finish_single(admin_id, sd, inquiry):
    pkg_row    = get_package(sd["package_id"])
    ovpn_files = sd.get("ovpn_files", [])
    username   = sd.get("ovpn_username", "")
    password   = sd.get("ovpn_password", "")
    state_clear(admin_id)
    if not ovpn_files:
        bot.send_message(admin_id, "⚠️ هیچ فایل .ovpn ثبت نشده بود.", parse_mode="HTML")
        return
    config_data = json.dumps({"type": "ovpn", "file_ids": ovpn_files, "username": username, "password": password}, ensure_ascii=False)
    add_config(pkg_row["type_id"], sd["package_id"], username or "ovpn", config_data, inquiry or "")
    bot.send_message(admin_id,
        f"✅ <b>1</b> کانفیگ OpenVPN با موفقیت ثبت شد.\n\n"
        f"📋 یوزرنیم: <code>{esc(username)}</code>",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _ovpn_deliver_bulk_shared(admin_id, pkg_row, shared_files, accounts):
    if not shared_files:
        bot.send_message(admin_id, "⚠️ فایل مشترک وجود ندارد.")
        return
    if not accounts:
        bot.send_message(admin_id, "⚠️ اطلاعات اکانتی وجود ندارد.")
        return
    for acct in accounts:
        config_data = json.dumps({"type": "ovpn", "file_ids": shared_files, "username": acct["username"], "password": acct["password"]}, ensure_ascii=False)
        add_config(pkg_row["type_id"], pkg_row["id"], acct["username"] or "ovpn", config_data, acct.get("inquiry", ""))
    lines = "\n".join(f"{i}. <code>{esc(a['username'])}</code>" for i, a in enumerate(accounts, 1))
    bot.send_message(admin_id,
        f"✅ <b>{len(accounts)}</b> کانفیگ OpenVPN با موفقیت ثبت شد.\n\n"
        f"📋 لیست یوزرنیم‌ها:\n{lines}",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _ovpn_deliver_bulk_diff(admin_id, pkg_row, acct_files, accounts):
    total = len(accounts)
    if not acct_files or not accounts:
        bot.send_message(admin_id, "⚠️ فایل یا اطلاعات اکانت‌ها وجود ندارد.")
        return
    for i, acct in enumerate(accounts, 1):
        files = acct_files.get(i, [])
        config_data = json.dumps({"type": "ovpn", "file_ids": files, "username": acct["username"], "password": acct["password"]}, ensure_ascii=False)
        add_config(pkg_row["type_id"], pkg_row["id"], acct["username"] or "ovpn", config_data, acct.get("inquiry", ""))
    lines = "\n".join(f"{i}. <code>{esc(a['username'])}</code>" for i, a in enumerate(accounts, 1))
    bot.send_message(admin_id,
        f"✅ <b>{total}</b> کانفیگ OpenVPN با موفقیت ثبت شد.\n\n"
        f"📋 لیست یوزرنیم‌ها:\n{lines}",
        parse_mode="HTML", reply_markup=kb_admin_panel())


# ── WireGuard helpers ─────────────────────────────────────────────────────────

def _wg_service_name_from_filename(filename):
    """Strip extension from filename to get service name."""
    if not filename:
        return "wireguard"
    name = filename
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name or "wireguard"


def _wg_caption(pkg_row, service_name, inquiry):
    users_label = _fmt_users_label(pkg_row["max_users"] if "max_users" in pkg_row.keys() else 0)
    vol_text    = "نامحدود" if not pkg_row["volume_gb"] else f"{pkg_row['volume_gb']} گیگ"
    dur_text    = "نامحدود" if not pkg_row["duration_days"] else f"{pkg_row['duration_days']} روز"
    inq_line    = f"\n🔋 Volume web: {inquiry}" if inquiry else ""
    return (
        f"🧩 نوع سرویس: <code>{esc(pkg_row['type_name'])}</code>\n"
        f"📦 پکیج: <code>{esc(pkg_row['name'])}</code>\n"
        f"🔋 حجم: <code>{esc(vol_text)}</code>\n"
        f"⏰ مدت: <code>{esc(dur_text)}</code>\n"
        f"👥 نوع کاربری: <code>{esc(users_label)}</code>\n"
        f"🔮 نام سرویس: <code>{esc(service_name)}</code>"
        f"{inq_line}"
    )


def _wg_send_file_group(chat_id, file_ids, file_names, caption):
    """Send WireGuard file group as media album; caption on the last file."""
    if not file_ids:
        return
    if len(file_ids) == 1:
        bot.send_document(chat_id, file_ids[0], caption=caption, parse_mode="HTML")
        return
    # Chunk into groups of 10 (Telegram media group limit)
    chunks = [file_ids[i:i + 10] for i in range(0, len(file_ids), 10)]
    for idx, chunk in enumerate(chunks):
        is_last = (idx == len(chunks) - 1)
        if is_last:
            media = [types.InputMediaDocument(fid) for fid in chunk[:-1]]
            media.append(types.InputMediaDocument(chunk[-1], caption=caption, parse_mode="HTML"))
        else:
            media = [types.InputMediaDocument(fid) for fid in chunk]
        bot.send_media_group(chat_id, media)


def _wg_finish_single(admin_id, sd, inquiry):
    pkg_row      = get_package(sd["package_id"])
    wg_files     = sd.get("wg_files", [])
    wg_names     = sd.get("wg_names", [])
    service_name = _wg_service_name_from_filename(wg_names[-1] if wg_names else "")
    state_clear(admin_id)
    if not wg_files:
        bot.send_message(admin_id, "⚠️ هیچ فایل WireGuard ثبت نشده بود.", parse_mode="HTML")
        return
    config_data = json.dumps({"type": "wg", "file_ids": wg_files}, ensure_ascii=False)
    add_config(pkg_row["type_id"], sd["package_id"], service_name, config_data, inquiry or "")
    bot.send_message(admin_id,
        f"✅ <b>1</b> کانفیگ WireGuard با موفقیت ثبت شد.\n\n"
        f"📋 نام سرویس: <code>{esc(service_name)}</code>",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _wg_deliver_bulk_shared(admin_id, pkg_row, shared_files, shared_names, inquiries):
    """Deliver bulk WireGuard configs where all configs share the same files."""
    if not shared_files:
        bot.send_message(admin_id, "⚠️ فایل مشترک وجود ندارد.")
        return
    service_name = _wg_service_name_from_filename(shared_names[-1] if shared_names else "")
    count = len(inquiries) if inquiries else 1
    for inq in (inquiries if inquiries else [""]):
        config_data = json.dumps({"type": "wg", "file_ids": shared_files}, ensure_ascii=False)
        add_config(pkg_row["type_id"], pkg_row["id"], service_name, config_data, inq or "")
    lines = "\n".join(f"{i}. <code>{esc(service_name)}</code>" for i in range(1, count + 1))
    bot.send_message(admin_id,
        f"✅ <b>{count}</b> کانفیگ WireGuard با موفقیت ثبت شد.\n\n"
        f"📋 لیست نام سرویس‌ها:\n{lines}",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _wg_deliver_bulk_diff(admin_id, pkg_row, acct_files, acct_names, inquiries):
    """Deliver bulk WireGuard configs where each config has different files."""
    total = len(acct_files)
    if not acct_files:
        bot.send_message(admin_id, "⚠️ فایلی برای ارسال وجود ندارد.")
        return
    service_names = []
    for i in range(1, total + 1):
        files = acct_files.get(i, [])
        names = acct_names.get(i, [])
        inq   = inquiries[i - 1] if inquiries and i - 1 < len(inquiries) else ""
        service_name = _wg_service_name_from_filename(names[-1] if names else "")
        service_names.append(service_name)
        config_data = json.dumps({"type": "wg", "file_ids": files}, ensure_ascii=False)
        add_config(pkg_row["type_id"], pkg_row["id"], service_name, config_data, inq or "")
    lines = "\n".join(f"{i}. <code>{esc(sn)}</code>" for i, sn in enumerate(service_names, 1))
    bot.send_message(admin_id,
        f"✅ <b>{total}</b> کانفیگ WireGuard با موفقیت ثبت شد.\n\n"
        f"📋 لیست نام سرویس‌ها:\n{lines}",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _get_bulk_page_ids(sd):
    """Return config IDs for the current page of a bulk selection state."""
    kind   = sd.get("kind", "av")
    scope  = sd.get("scope", "pk")
    pkg_id = int(sd.get("pkg_id", 0))
    page   = int(sd.get("page", 0))
    offset = page * CONFIGS_PER_PAGE
    with get_conn() as conn:
        if scope == "pk":
            if kind == "sl":
                rows = conn.execute(
                    "SELECT id FROM configs WHERE package_id=? AND sold_to IS NOT NULL ORDER BY id DESC LIMIT ? OFFSET ?",
                    (pkg_id, CONFIGS_PER_PAGE, offset)).fetchall()
            elif kind == "ex":
                rows = conn.execute(
                    "SELECT id FROM configs WHERE package_id=? AND is_expired=1 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (pkg_id, CONFIGS_PER_PAGE, offset)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM configs WHERE package_id=? AND sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (pkg_id, CONFIGS_PER_PAGE, offset)).fetchall()
        else:
            if kind == "sl":
                rows = conn.execute(
                    "SELECT id FROM configs WHERE sold_to IS NOT NULL ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)).fetchall()
            elif kind == "ex":
                rows = conn.execute(
                    "SELECT id FROM configs WHERE is_expired=1 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM configs WHERE sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)).fetchall()
    return [r["id"] for r in rows]


def _render_bulk_page(call, uid):
    """Render the bulk selection page for stock/config management."""
    sd       = state_data(uid)
    kind     = sd.get("kind", "av")   # av / sl / ex
    scope    = sd.get("scope", "pk")  # pk / all
    pkg_id   = int(sd.get("pkg_id", 0))
    page     = int(sd.get("page", 0))
    sel_raw  = sd.get("selected", "")
    selected = set(int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit())
    offset   = page * CONFIGS_PER_PAGE

    with get_conn() as conn:
        if scope == "pk":
            if kind == "sl":
                cfgs  = conn.execute(
                    "SELECT id, service_name, sold_to, is_expired FROM configs WHERE package_id=? AND sold_to IS NOT NULL ORDER BY id DESC LIMIT ? OFFSET ?",
                    (pkg_id, CONFIGS_PER_PAGE, offset)).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND sold_to IS NOT NULL", (pkg_id,)).fetchone()["n"]
            elif kind == "ex":
                cfgs  = conn.execute(
                    "SELECT id, service_name, sold_to, is_expired FROM configs WHERE package_id=? AND is_expired=1 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (pkg_id, CONFIGS_PER_PAGE, offset)).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND is_expired=1", (pkg_id,)).fetchone()["n"]
            else:
                cfgs  = conn.execute(
                    "SELECT id, service_name, sold_to, is_expired FROM configs WHERE package_id=? AND sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (pkg_id, CONFIGS_PER_PAGE, offset)).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0", (pkg_id,)).fetchone()["n"]
        else:
            if kind == "sl":
                cfgs  = conn.execute(
                    "SELECT id, service_name, sold_to, is_expired FROM configs WHERE sold_to IS NOT NULL ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE sold_to IS NOT NULL").fetchone()["n"]
            elif kind == "ex":
                cfgs  = conn.execute(
                    "SELECT id, service_name, sold_to, is_expired FROM configs WHERE is_expired=1 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE is_expired=1").fetchone()["n"]
            else:
                cfgs  = conn.execute(
                    "SELECT id, service_name, sold_to, is_expired FROM configs WHERE sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0").fetchone()["n"]

    total_pages = max(1, (total + CONFIGS_PER_PAGE - 1) // CONFIGS_PER_PAGE)
    page_ids    = [c["id"] for c in cfgs]
    all_sel     = bool(page_ids) and all(cid in selected for cid in page_ids)

    kb = types.InlineKeyboardMarkup()
    for c in cfgs:
        mark     = "✅" if c["id"] in selected else "⬜️"
        svc_name = urllib.parse.unquote(c["service_name"] or "")
        kb.add(types.InlineKeyboardButton(f"{mark} {svc_name}", callback_data=f"adm:stk:btog:{c['id']}"))

    if not all_sel:
        kb.add(types.InlineKeyboardButton("☑️ انتخاب همه این صفحه", callback_data="adm:stk:bsall"))
    else:
        kb.add(types.InlineKeyboardButton("🔲 لغو انتخاب این صفحه", callback_data="adm:stk:bclr"))
    if selected:
        kb.add(types.InlineKeyboardButton("🚫 لغو همه انتخاب‌ها", callback_data="adm:stk:bclrall"))

    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton("⬅️ قبل", callback_data=f"adm:stk:bnav:{page-1}"))
    nav_row.append(types.InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(types.InlineKeyboardButton("بعد ➡️", callback_data=f"adm:stk:bnav:{page+1}"))
    if len(nav_row) > 1:
        kb.row(*nav_row)

    if selected:
        sel_count = len(selected)
        if kind in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton(f"🗑 حذف ({sel_count})", callback_data="adm:stk:bdel"),
                types.InlineKeyboardButton(f"❌ منقضی ({sel_count})", callback_data="adm:stk:bexp"),
            )
        else:
            kb.add(types.InlineKeyboardButton(f"🗑 حذف ({sel_count})", callback_data="adm:stk:bdel"))

    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:stk:bcanc", icon_custom_emoji_id="5253997076169115797"))

    kind_labels = {"av": "🟢 موجود", "sl": "🔴 فروخته", "ex": "❌ منقضی"}
    heading = (
        f"☑️ <b>انتخاب گروهی — {kind_labels.get(kind, '')}</b>\n\n"
        f"✅ {len(selected)} مورد انتخاب شده | صفحه {page+1}/{total_pages} از {total} کانفیگ"
    )
    send_or_edit(call, heading, kb)


# ── Per-user callback serialisation ──────────────────────────────────────────
# Prevents a user from triggering the same handler multiple times concurrently
# by rapid-clicking.  Only one callback per user is processed at a time;
# additional clicks while the lock is held are silently answered and dropped.
_USER_CB_LOCKS: dict = {}
_USER_CB_LOCKS_MUTEX = threading.Lock()

def _get_user_cb_lock(uid: int) -> threading.Lock:
    with _USER_CB_LOCKS_MUTEX:
        if uid not in _USER_CB_LOCKS:
            _USER_CB_LOCKS[uid] = threading.Lock()
        return _USER_CB_LOCKS[uid]

# Callbacks that are purely visual / informational and need no deduplication.
_PASSTHROUGH_CALLBACKS = frozenset({"noop", "check_channel"})

def _build_discount_prompt_text(amount=None):
    amount_line = f"\n💰 مبلغ قابل پرداخت: <b>{fmt_price(amount)}</b> تومان\n" if amount else ""
    return (
        "🎟✨ <b>کد تخفیف ویژه</b> ✨🎟\n"
        f"{amount_line}\n"
        "🌸 پیش از پرداخت، اگر کد تخفیف اختصاصی دارید وارد کنید\n"
        "و از مزایای ویژه‌ی آن بهره‌مند شوید! 🎁\n\n"
        "🔖 آیا کد تخفیف دارید؟"
    )


# Keep for backwards-compat import in messages.py
_DISCOUNT_PROMPT_TEXT = _build_discount_prompt_text()


def _get_state_price(uid, package_row, state_key):
    """Return the final payment amount considering discounts stored in state."""
    if state_name(uid) == state_key:
        stored = state_data(uid).get("amount")
        if stored:
            return stored
    return get_effective_price(uid, package_row)


# ── Invoice expiry helpers ─────────────────────────────────────────────────────

def _invoice_expiry_minutes() -> int:
    """Return configured invoice expiry duration in minutes (default 30)."""
    try:
        return max(1, int(setting_get("invoice_expiry_minutes", "30") or "30"))
    except (ValueError, TypeError):
        return 30


def _invoice_expiry_enabled() -> bool:
    """Return True if invoice expiry feature is enabled."""
    return setting_get("invoice_expiry_enabled", "1") == "1"


def _invoice_expiry_line() -> str:
    """Return the validity notice line to append inside the invoice text."""
    if not _invoice_expiry_enabled():
        return ""
    mins = _invoice_expiry_minutes()
    expiry_dt = datetime.now(_TZ_TEHRAN) + timedelta(minutes=mins)
    expiry_str = expiry_dt.strftime("%H:%M")
    return (
        f"\n\n⏳ اعتبار این فاکتور تا ساعت <b>{expiry_str}</b> است."
    )


def _stamp_invoice(uid: int) -> None:
    """Write invoice_created_at timestamp into the user's current state."""
    sd = state_data(uid)
    sn = state_name(uid)
    if not sn:
        return
    new_sd = dict(sd)
    new_sd["invoice_created_at"] = int(time.time())
    state_set(uid, sn, **new_sd)
    log.debug("_stamp_invoice: uid=%s state=%s ts=%s", uid, sn, new_sd["invoice_created_at"])


def _check_invoice_valid(uid: int) -> bool:
    """Return True if the invoice is still within its validity window."""
    if not _invoice_expiry_enabled():
        return True
    sn = state_name(uid)
    # Only enforce expiry when in a recognised invoice-bearing state.
    # If the state is something else (or None), the timestamp may belong to
    # a completely different flow — allow the payment through.
    _INVOICE_STATES = {
        "buy_select_method", "renew_select_method", "wallet_charge_method",
    }
    if sn not in _INVOICE_STATES:
        return True
    sd = state_data(uid)
    created_at = sd.get("invoice_created_at")
    if not created_at:
        return True  # no timestamp yet — backward-compatible, allow
    elapsed = time.time() - float(created_at)
    limit = _invoice_expiry_minutes() * 60
    valid = elapsed <= limit
    if not valid:
        log.warning(
            "_check_invoice_valid: uid=%s EXPIRED — elapsed=%.0fs limit=%.0fs state=%s",
            uid, elapsed, limit, sn
        )
    return valid


_INVOICE_EXPIRED_MSG = (
    "⏰ زمان پرداخت شما با این فاکتور به پایان رسیده است.\n"
    "لطفا دوباره اقدام کنید."
)


def _show_invoice_expired(call) -> None:
    """Edit the invoice message in-place to show expiry notice with a restart button."""
    uid = call.from_user.id
    state_clear(uid)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔄 شروع مجدد", callback_data="invoice:restart"))
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    try:
        bot.edit_message_text(
            _INVOICE_EXPIRED_MSG,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        try:
            bot.send_message(
                call.message.chat.id,
                _INVOICE_EXPIRED_MSG,
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:
            pass


def _br_ok(p, is_agent: bool) -> bool:
    """Return True if the package is visible/purchasable for this user type."""
    br = p["buyer_role"] if "buyer_role" in p.keys() else "all"
    if br == "nobody":
        return False  # hidden — only for referral gifts, not regular purchase
    if br == "agents" and not is_agent:
        return False
    if br == "public" and is_agent:
        return False
    return True


def _pkg_has_stock(p, stock_only: bool) -> bool:
    """Return True if the package is purchasable considering stock mode.
    Panel-based packages always have availability (no manual stock needed)."""
    try:
        if (p["config_source"] or "manual") == "panel":
            return True
    except (IndexError, KeyError):
        pass
    return not stock_only or p["stock"] > 0


def _show_discount_prompt(call, amount=None):
    """Show the discount code prompt. Returns True if shown, False if skipped."""
    # Check if any eligible discount codes exist for this user
    from telebot.types import Message
    uid = call.from_user.id if hasattr(call, "from_user") else call.chat.id
    user = get_user(uid)
    is_agent = bool(user and user["is_agent"])
    if not has_eligible_discount_codes(is_agent):
        # No eligible codes — skip this step entirely, return False so caller can proceed
        return False
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ بله، دارم", callback_data="disc:yes"),
        types.InlineKeyboardButton("❌ خیر، ادامه", callback_data="disc:no"),
    )
    send_or_edit(call, _build_discount_prompt_text(amount), kb)
    return True


def _show_purchase_gateways(target, uid, package_id, price, package_row):
    """Build and show gateway selection keyboard for config purchase."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    if wallet_pay_enabled_for(uid):
        kb.add(types.InlineKeyboardButton("💰 پرداخت از موجودی", callback_data=f"pay:wallet:{package_id}"))
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "💳 کارت به کارت"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:card:{package_id}"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "💎 ارز دیجیتال"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:crypto:{package_id}"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "💳 درگاه کارت به کارت (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:tetrapay:{package_id}"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "💳 درگاه کارت به کارت و ارز دیجیتال (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:swapwallet_crypto:{package_id}"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "💳 درگاه کارت به کارت (TronPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:tronpays_rial:{package_id}"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"buy:t:{package_row['type_id']}", icon_custom_emoji_id="5253997076169115797"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    _pkg_sn = package_row['show_name'] if 'show_name' in package_row.keys() else 1
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", price)
    quantity    = int(sd.get("quantity", 1) or 1)
    unit_price  = int(sd.get("unit_price", 0) or 0) or (orig_amount // quantity if quantity > 1 else orig_amount)

    # Build price / quantity lines
    _qty_line = f"🔢 تعداد: <b>{quantity}</b> عدد\n" if quantity > 1 else ""
    if quantity > 1:
        _unit_line = f"💵 قیمت هر عدد: <b>{fmt_price(unit_price)}</b> تومان\n"
    else:
        _unit_line = ""

    if disc_amount:
        _price_line = (
            f"💰 مبلغ اصلی: {fmt_price(orig_amount)} تومان\n"
            f"🎟 تخفیف: {fmt_price(disc_amount)} تومان\n"
            f"💚 مبلغ نهایی: {fmt_price(price)} تومان"
        )
    else:
        if quantity > 1:
            _price_line = f"💰 مبلغ کل: <b>{fmt_price(price)}</b> تومان"
        else:
            _price_line = f"💰 قیمت: {fmt_price(price)} تومان"
    _stamp_invoice(uid)
    text = (
        "💳 <b>انتخاب روش پرداخت</b>\n\n"
        f"🧩 نوع: {esc(package_row['type_name'])}\n"
        + (f"📦 پکیج: {esc(package_row['name'])}\n" if _pkg_sn else "")
        + f"🔋 حجم: {fmt_vol(package_row['volume_gb'])}\n"
        f"⏰ مدت: {fmt_dur(package_row['duration_days'])}\n"
        f"{_qty_line}"
        f"{_unit_line}"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "روش پرداخت را انتخاب کنید:"
        + _invoice_expiry_line()
    )
    send_or_edit(target, text, kb)


def _show_renewal_gateways(target, uid, purchase_id, package_id, price, package_row, item):
    """Build and show gateway selection keyboard for renewal."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    if wallet_pay_enabled_for(uid):
        kb.add(types.InlineKeyboardButton("💰 پرداخت از موجودی", callback_data=f"rpay:wallet:{purchase_id}:{package_id}"))
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "💳 کارت به کارت"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:card:{purchase_id}:{package_id}"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "💎 ارز دیجیتال"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:crypto:{purchase_id}:{package_id}"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "💳 درگاه کارت به کارت (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:tetrapay:{purchase_id}:{package_id}"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "💳 درگاه کارت به کارت و ارز دیجیتال (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:swapwallet_crypto:{purchase_id}:{package_id}"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "💳 درگاه کارت به کارت (TronPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:tronpays_rial:{purchase_id}:{package_id}"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"renew:{purchase_id}", icon_custom_emoji_id="5253997076169115797"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    _pkg_sn_renew = package_row['show_name'] if 'show_name' in package_row.keys() else 1
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", price)
    if disc_amount:
        _price_line = (
            f"💰 قیمت اصلی: {fmt_price(orig_amount)} تومان\n"
            f"🎟 تخفیف: {fmt_price(disc_amount)} تومان\n"
            f"💚 قیمت نهایی: {fmt_price(price)} تومان"
        )
    else:
        _price_line = f"💰 قیمت: {fmt_price(price)} تومان"
    _stamp_invoice(uid)
    text = (
        "♻️ <b>تمدید سرویس</b>\n\n"
        f"🔮 سرویس فعلی: {esc(move_leading_emoji(urllib.parse.unquote(item['service_name'] or '')))}\n"
        + (f"📦 پکیج تمدید: {esc(package_row['name'])}\n" if _pkg_sn_renew else "")
        + f"🔋 حجم: {fmt_vol(package_row['volume_gb'])}\n"
        f"⏰ مدت: {fmt_dur(package_row['duration_days'])}\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "روش پرداخت را انتخاب کنید:"
        + _invoice_expiry_line()
    )
    send_or_edit(target, text, kb)


def _execute_pnlcfg_renewal(config_id, package_id, chat_id=None, uid=None):
    """
    Execute panel config renewal: reset traffic + enable_client with new expiry.
    Retries indefinitely on connection errors (up to 8 hours).
    On non-connection failures retries up to 3 minutes then gives up.
    Returns (True, None) on success or (False, user_friendly_msg) on fatal failure.
    Admins are notified via _notify_panel_error on any fatal failure.
    """
    import time as _time
    from ..db import get_panel_config as _get_pcfg, update_panel_config_field as _upf
    from ..db import get_panel as _get_pnl, get_package as _get_pkg3
    from ..panels.client import PanelClient
    from datetime import datetime as _dt, timedelta as _td

    cfg = _get_pcfg(config_id)
    if not cfg:
        return False, "کانفیگ یافت نشد."
    cfg = dict(cfg)
    _uid = uid or cfg["user_id"]
    pkg = _get_pkg3(package_id)
    if not pkg:
        return False, "پکیج یافت نشد."
    panel = _get_pnl(cfg["panel_id"])
    if not panel:
        return False, "پنل یافت نشد."

    pc_api = PanelClient(
        protocol=panel["protocol"], host=panel["host"], port=panel["port"],
        path=panel["path"] or "", username=panel["username"], password=panel["password"]
    )

    def _is_conn_err(e):
        s = str(e).lower()
        return any(x in s for x in [
            "connection refused", "max retries exceeded", "failed to establish",
            "newconnectionerror", "httpsconnectionpool", "remotedisconnected",
            "connection timed out", "read timed out", "timeout",
            "connection reset", "connection aborted", "connectionreseterror",
            "econnreset", "broken pipe", "reset by peer",
        ])

    CONN_RETRY_DELAY   = 30
    FUNC_RETRY_TIMEOUT = 180
    FUNC_RETRY_DELAY   = 15
    MAX_WAIT           = 28800  # 8-hour hard cap
    PERIODIC_INTERVAL  = 300

    _t_start          = _time.time()
    _waiting_notified = False
    _last_periodic    = 0.0

    def _maybe_notify_waiting():
        nonlocal _waiting_notified, _last_periodic
        if not chat_id:
            return
        now = _time.time()
        if not _waiting_notified:
            try:
                bot.send_message(
                    chat_id,
                    "⏳ <b>سرور پنل در حال حاضر در دسترس نیست</b>\n\n"
                    "تمدید سرویس در صف انتظار قرار گرفت. "
                    "به محض بازگشت اتصال، سرویس شما تمدید خواهد شد.",
                    parse_mode="HTML",
                )
                _waiting_notified = True
                _last_periodic = now
            except Exception:
                pass
        elif now - _last_periodic >= PERIODIC_INTERVAL:
            try:
                bot.send_message(chat_id, "⏳ هنوز در حال تلاش برای اتصال به پنل...", parse_mode="HTML")
                _last_periodic = now
            except Exception:
                pass

    def _notify_reconnected():
        if _waiting_notified and chat_id:
            try:
                bot.send_message(chat_id, "✅ اتصال به پنل برقرار شد، در حال تمدید سرویس...", parse_mode="HTML")
            except Exception:
                pass

    # ── Step 1: login ─────────────────────────────────────────────────────────
    login_err = None
    _t0 = _time.time()
    while True:
        if _time.time() - _t_start > MAX_WAIT:
            login_err = "حداکثر زمان انتظار (8 ساعت) تمام شد"
            break
        ok, login_err = pc_api.login()
        if ok:
            login_err = None
            _notify_reconnected()
            break
        elapsed = _time.time() - _t0
        if _is_conn_err(login_err):
            _maybe_notify_waiting()
            log.warning("_execute_pnlcfg_renewal: login CONN_ERR (%.0fs elapsed), retry in %ds: %s",
                        elapsed, CONN_RETRY_DELAY, login_err)
            _time.sleep(CONN_RETRY_DELAY)
        else:
            log.warning("_execute_pnlcfg_renewal: login failed (%.0fs elapsed): %s", elapsed, login_err)
            if elapsed + FUNC_RETRY_DELAY >= FUNC_RETRY_TIMEOUT:
                break
            _time.sleep(FUNC_RETRY_DELAY)
    if login_err is not None:
        _notify_panel_error(_uid, pkg, "login (تمدید)", login_err, config_id, cfg["panel_id"])
        return False, "تمدید سرویس با خطا مواجه شد. لطفاً با پشتیبانی ارتباط بگیرید."

    # ── Step 2: reset traffic ──────────────────────────────────────────────────
    reset_err = None
    _t0 = _time.time()
    while True:
        if _time.time() - _t_start > MAX_WAIT:
            reset_err = "حداکثر زمان انتظار تمام شد"
            break
        ok_rt, err_rt = pc_api.reset_client_traffic(cfg["inbound_id"], cfg["client_name"] or "")
        if ok_rt:
            reset_err = None
            break
        reset_err = str(err_rt)
        elapsed = _time.time() - _t0
        if _is_conn_err(reset_err):
            _maybe_notify_waiting()
            log.warning("_execute_pnlcfg_renewal: reset_traffic CONN_ERR (%.0fs elapsed), retry in %ds: %s",
                        elapsed, CONN_RETRY_DELAY, reset_err)
            _time.sleep(CONN_RETRY_DELAY)
        else:
            log.warning("_execute_pnlcfg_renewal: reset_traffic failed (%.0fs elapsed): %s", elapsed, reset_err)
            if elapsed + FUNC_RETRY_DELAY >= FUNC_RETRY_TIMEOUT:
                break
            _time.sleep(FUNC_RETRY_DELAY)
    if reset_err is not None:
        _notify_panel_error(_uid, pkg, "reset_traffic (تمدید)", reset_err, config_id, cfg["panel_id"])
        return False, "تمدید سرویس با خطا مواجه شد. لطفاً با پشتیبانی ارتباط بگیرید."

    # ── Step 3: enable_client with new expiry ─────────────────────────────────
    dur_days = int(pkg["duration_days"] or 0)
    if dur_days:
        new_exp_dt  = _dt.utcnow() + _td(days=dur_days)
        new_exp_str = new_exp_dt.strftime("%Y-%m-%d %H:%M:%S")
        new_exp_ms  = int(new_exp_dt.timestamp() * 1000)
    else:
        new_exp_str = None
        new_exp_ms  = 0

    enable_err = None
    _t0 = _time.time()
    while True:
        if _time.time() - _t_start > MAX_WAIT:
            enable_err = "حداکثر زمان انتظار تمام شد"
            break
        ok_e, res_e = pc_api.enable_client(
            inbound_id=cfg["inbound_id"], client_uuid=cfg["client_uuid"],
            email=cfg["client_name"] or "",
            traffic_bytes=int((pkg["volume_gb"] or 0) * 1073741824),
            expire_ms=new_exp_ms,
        )
        if ok_e:
            enable_err = None
            break
        enable_err = str(res_e)
        elapsed = _time.time() - _t0
        if _is_conn_err(enable_err):
            _maybe_notify_waiting()
            log.warning("_execute_pnlcfg_renewal: enable_client CONN_ERR (%.0fs elapsed), retry in %ds: %s",
                        elapsed, CONN_RETRY_DELAY, enable_err)
            _time.sleep(CONN_RETRY_DELAY)
        else:
            log.warning("_execute_pnlcfg_renewal: enable_client failed (%.0fs elapsed): %s", elapsed, enable_err)
            if elapsed + FUNC_RETRY_DELAY >= FUNC_RETRY_TIMEOUT:
                break
            _time.sleep(FUNC_RETRY_DELAY)
    if enable_err is not None:
        _notify_panel_error(_uid, pkg, "enable_client (تمدید)", enable_err, config_id, cfg["panel_id"])
        return False, "تمدید سرویس با خطا مواجه شد. لطفاً با پشتیبانی ارتباط بگیرید."

    # ── Step 4: update DB ──────────────────────────────────────────────────────
    _upf(config_id, "expire_at",  new_exp_str)
    _upf(config_id, "is_expired",  0)
    _upf(config_id, "is_disabled", 0)
    if int(pkg["id"]) != int(cfg.get("package_id") or 0):
        _upf(config_id, "package_id", pkg["id"])
    return True, None


def _show_pnlcfg_renewal_gateways(target, uid, config_id, package_id, price, package_row, cfg):
    """Build and show gateway selection keyboard for panel config renewal."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    if wallet_pay_enabled_for(uid):
        kb.add(types.InlineKeyboardButton("💰 پرداخت از موجودی",
               callback_data=f"mypnlcfgrpay:wallet:{config_id}:{package_id}"))
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "💳 کارت به کارت"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:card:{config_id}:{package_id}"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "💎 ارز دیجیتال"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:crypto:{config_id}:{package_id}"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "💳 درگاه کارت به کارت (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:tetrapay:{config_id}:{package_id}"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "💳 درگاه کارت به کارت و ارز دیجیتال (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:swapwallet_crypto:{config_id}:{package_id}"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "💳 درگاه کارت به کارت (TronPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:tronpays_rial:{config_id}:{package_id}"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"mypnlcfg:renewconfirm:{config_id}",
           icon_custom_emoji_id="5253997076169115797"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    _pkg_sn_renew = package_row['show_name'] if 'show_name' in package_row.keys() else 1
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", price)
    if disc_amount:
        _price_line = (
            f"💰 قیمت اصلی: {fmt_price(orig_amount)} تومان\n"
            f"🎟 تخفیف: {fmt_price(disc_amount)} تومان\n"
            f"💚 قیمت نهایی: {fmt_price(price)} تومان"
        )
    else:
        _price_line = f"💰 قیمت: {fmt_price(price)} تومان"
    _stamp_invoice(uid)
    svc_name = cfg.get("client_name") or ""
    text = (
        "♻️ <b>تمدید سرویس</b>\n\n"
        f"🔮 سرویس: {esc(svc_name)}\n"
        + (f"📦 پکیج تمدید: {esc(package_row['name'])}\n" if _pkg_sn_renew else "")
        + f"🔋 حجم: {fmt_vol(package_row['volume_gb'])}\n"
        f"⏰ مدت: {fmt_dur(package_row['duration_days'])}\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "روش پرداخت را انتخاب کنید:"
        + _invoice_expiry_line()
    )
    send_or_edit(target, text, kb)


def _show_wallet_gateways(target, uid, amount):
    """Build and show gateway selection keyboard for wallet charge."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "💳 کارت به کارت"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:card"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "💎 ارز دیجیتال"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:crypto"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "💳 درگاه کارت به کارت (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:tetrapay"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "💳 درگاه کارت به کارت و ارز دیجیتال (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:swapwallet_crypto"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "💳 درگاه کارت به کارت (TronPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:tronpays_rial"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", amount)
    if disc_amount:
        _price_line = (
            f"💰 مبلغ اصلی: {fmt_price(orig_amount)} تومان\n"
            f"🎟 تخفیف: {fmt_price(disc_amount)} تومان\n"
            f"💚 مبلغ نهایی: {fmt_price(amount)} تومان"
        )
    else:
        _price_line = f"💰 مبلغ: {fmt_price(amount)} تومان"
    _stamp_invoice(uid)
    text = (
        "💳 <b>شارژ کیف پول</b>\n\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "روش پرداخت را انتخاب کنید:"
        + _invoice_expiry_line()
    )
    send_or_edit(target, text, kb)


# ── Bulk/Quantity Purchase Helpers ─────────────────────────────────────────────

def _show_qty_prompt(call, package_row, unit_price):
    """Show the quantity-selection prompt to the user."""
    from ..db import should_show_bulk_qty, get_bulk_qty_limits
    uid = call.from_user.id
    _pkg_sn   = package_row.get("show_name", 1) if not hasattr(package_row, "keys") else (package_row["show_name"] if "show_name" in package_row.keys() else 1)
    _pkg_name = package_row["name"] if _pkg_sn else ""
    _name_line = f"📦 پکیج: <b>{esc(_pkg_name)}</b>\n" if _pkg_name else ""

    min_qty, max_qty = get_bulk_qty_limits()
    max_label = "بدون محدودیت" if max_qty == 0 else str(max_qty)
    limit_line = (
        f"📌 حداقل: <b>{min_qty}</b>  |  حداکثر: <b>{max_label}</b>\n\n"
    )

    state_set(uid, "await_qty",
              package_id=package_row["id"],
              unit_price=unit_price,
              kind="config_purchase")
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"buy:t:{package_row['type_id']}", icon_custom_emoji_id="5253997076169115797"))
    text = (
        "🛒 <b>خرید تعدادی</b>\n\n"
        f"🧩 نوع سرویس: <b>{esc(package_row['type_name'])}</b>\n"
        f"{_name_line}"
        f"🔋 حجم: {fmt_vol(package_row['volume_gb'])}  |  ⏰ مدت: {fmt_dur(package_row['duration_days'])}\n"
        f"💰 قیمت هر عدد: <b>{fmt_price(unit_price)}</b> تومان\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔢 چه تعداد کانفیگ نیاز دارید؟\n\n"
        f"{limit_line}"
        "📝 <i>عدد موردنظر را تایپ کنید (مثلاً ۱، ۲، ۵)</i>"
    )
    send_or_edit(call, text, kb)


def _qty_order_summary_text(package_row, unit_price, quantity):
    """Build the order-summary text shown after qty entry."""
    _pkg_sn   = package_row.get("show_name", 1) if not hasattr(package_row, "keys") else (package_row["show_name"] if "show_name" in package_row.keys() else 1)
    _pkg_name = package_row["name"] if _pkg_sn else ""
    _name_line = f"📦 پکیج: <b>{esc(_pkg_name)}</b>\n" if _pkg_name else ""
    total = unit_price * quantity
    return (
        "📋 <b>خلاصه سفارش</b>\n\n"
        f"🧩 نوع سرویس: <b>{esc(package_row['type_name'])}</b>\n"
        f"{_name_line}"
        f"🔋 حجم: {fmt_vol(package_row['volume_gb'])}  |  ⏰ مدت: {fmt_dur(package_row['duration_days'])}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔢 تعداد: <b>{quantity}</b> عدد\n"
        f"💵 قیمت هر عدد: <b>{fmt_price(unit_price)}</b> تومان\n"
        f"💰 مبلغ کل: <b>{fmt_price(total)}</b> تومان\n"
        "━━━━━━━━━━━━━━━━━━"
    )


def _notify_panel_error(uid, package_row, stage: str, detail: str = "", panel_config_id=None, panel_id=None):
    """
    Alert owner admins (ADMIN_IDS) and the error_log group topic
    when a panel config creation or delivery fails.
    """
    try:
        def _row_get(row, key, default="؟"):
            if row is None:
                return default
            try:
                return row[key] if key in row.keys() else default
            except Exception:
                return default
        pkg_name  = _row_get(package_row, "name")
        type_name = _row_get(package_row, "type_name")
        cfg_line  = f"\n🗂 panel_config_id: <code>{panel_config_id}</code>" if panel_config_id else ""

        # Try to get panel name
        panel_name = "نامشخص"
        pid = panel_id or _row_get(package_row, "panel_id", None)
        if pid:
            try:
                _panel = get_panel(pid)
                if _panel:
                    panel_name = _panel["name"] or str(pid)
            except Exception:
                panel_name = str(pid)

        text = (
            "🚨 <b>اتصال ربات با پنل قطع شد</b>\n\n"
            f"🖥 پنل: <b>{esc(str(panel_name))}</b>\n"
            f"👤 کاربر: <code>{uid}</code>\n"
            f"🧩 نوع: {esc(str(type_name))}\n"
            f"📦 پکیج: {esc(str(pkg_name))}\n"
            f"🔧 مرحله: {esc(stage)}"
            f"{cfg_line}\n\n"
            f"⚠️ جزئیات:\n<code>{esc(str(detail)[:600])}</code>"
        )
        log.error("[PANEL_ERROR] panel=%s uid=%s stage=%s detail=%s", panel_name, uid, stage, detail)
        # Send to owner admin IDs
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass
        # Send to error_log group topic
        try:
            from ..group_manager import send_to_topic
            send_to_topic("error_log", text)
        except Exception:
            pass
    except Exception as _ne:
        log.error("_notify_panel_error itself failed: %s", _ne)


def _panel_connect_with_retry(uid, protocol, host, port, path, username, password,
                               panel_name="", panel_id=None, notify_chat_id=None):
    """
    Try to connect (login) to a panel, retrying on connection errors indefinitely.
    If the panel is still unreachable after ADMIN_NOTIFY_AFTER seconds,
    notifies all ADMIN_IDS and the error_log topic once.
    Returns (ok: bool, err: str|None).
    """
    import time as _t
    from ..panels.client import PanelClient as _PC

    CONN_RETRY_DELAY   = 15    # seconds between retries on connection error
    FUNC_RETRY_TIMEOUT = 120   # 2 min cap for non-connection errors before giving up
    FUNC_RETRY_DELAY   = 10
    ADMIN_NOTIFY_AFTER = 300   # 5 minutes before alerting admin

    def _is_conn_err(e):
        s = str(e).lower()
        return any(x in s for x in [
            "connection refused", "max retries exceeded", "failed to establish",
            "newconnectionerror", "httpsconnectionpool", "remotedisconnected",
            "connection timed out", "read timed out", "timeout",
            "name or service not known", "nameresolutionerror", "failed to resolve",
            "connection reset", "connection aborted", "connectionreseterror",
            "econnreset", "broken pipe", "reset by peer",
        ])

    cl = _PC(protocol=protocol, host=host, port=int(port),
             path=path, username=username, password=password)

    _t_start         = _t.time()
    _admin_notified  = False
    _t0              = _t.time()

    while True:
        elapsed_total = _t.time() - _t_start
        # Admin notification after 5 minutes of continuous failure
        if not _admin_notified and elapsed_total >= ADMIN_NOTIFY_AFTER:
            _admin_notified = True
            _label = f"<b>{esc(str(panel_name))}</b>" if panel_name else f"<code>{esc(str(host))}:{port}</code>"
            _text  = (
                "⚠️ <b>پنل در دسترس نیست — بررسی اتصال ادامه دارد</b>\n\n"
                f"🖥 پنل: {_label}\n"
                f"👤 ادمین: <code>{uid}</code>\n\n"
                "ربات به‌طور خودکار در حال تلاش مجدد است."
            )
            for _a in ADMIN_IDS:
                try:
                    bot.send_message(_a, _text, parse_mode="HTML")
                except Exception:
                    pass
            try:
                from ..group_manager import send_to_topic as _stt
                _stt("error_log", _text)
            except Exception:
                pass
            if notify_chat_id:
                try:
                    bot.send_message(notify_chat_id,
                        "⏳ پنل بیش از ۵ دقیقه در دسترس نیست. در صورت رفع مشکل ادامه می‌دهیم…",
                        parse_mode="HTML")
                except Exception:
                    pass

        try:
            ok, err = cl.login()
        except Exception as exc:
            ok, err = False, str(exc)

        if ok:
            return True, None

        elapsed_step = _t.time() - _t0
        if _is_conn_err(err):
            log.warning("_panel_connect_with_retry: CONN_ERR (%.0fs total): %s", elapsed_total, err)
            _t.sleep(CONN_RETRY_DELAY)
        else:
            log.warning("_panel_connect_with_retry: non-conn err (%.0fs step): %s", elapsed_step, err)
            if elapsed_step + FUNC_RETRY_DELAY >= FUNC_RETRY_TIMEOUT:
                return False, err
            _t.sleep(FUNC_RETRY_DELAY)


def _deliver_bulk_configs(chat_id, uid, package_id, total_amount, payment_method,
                          quantity, payment_id):
    """
    Deliver `quantity` configs to user after successful payment.
    Returns (delivered_purchase_ids, pending_ids).
    For panel packages, creates configs in the panel automatically.
    For manual packages, pulls from stock; creates pending_orders if no stock.
    """
    from ..ui.notifications import deliver_purchase_message, admin_purchase_notify
    package_row   = get_package(package_id)
    unit_price    = max(0, total_amount // quantity) if quantity > 0 else total_amount

    # ── Panel-based packages ──────────────────────────────────────────────────
    try:
        config_source = package_row["config_source"] or "manual"
    except (IndexError, KeyError):
        config_source = "manual"

    if config_source == "panel":
        panel_config_ids = []
        failed_count = 0
        for _ in range(quantity):
            ok, result, pc_id = _create_panel_config(uid, package_id, payment_id, chat_id=chat_id)
            if ok:
                panel_config_ids.append(pc_id)
            else:
                failed_count += 1
                # Refund the unit price to wallet regardless of original payment method
                try:
                    refund_amount = unit_price
                    update_balance(uid, refund_amount)
                    log.warning("[PANEL_DELIVERY] refunded %s to uid=%s after create failure", refund_amount, uid)
                except Exception as _rf_exc:
                    log.error("[PANEL_DELIVERY] refund failed for uid=%s: %s", uid, _rf_exc)
                # Send only the simple error message to user (no technical details)
                try:
                    bot.send_message(
                        chat_id,
                        "⚠️ <b>خطا در تحویل سرویس</b>\n\n"
                        "متأسفانه در تحویل سرویس مشکلی پیش آمد و مبلغ به کیف پول شما بازگردانده شد.\n"
                        "لطفاً با پشتیبانی تماس بگیرید.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                # Notify admins with full technical details
                try:
                    _pid = package_row["panel_id"] if "panel_id" in (package_row.keys() if hasattr(package_row, "keys") else {}) else None
                except Exception:
                    _pid = None
                _notify_panel_error(
                    uid=uid, package_row=package_row,
                    stage="ساخت کلاینت در پنل", detail=result,
                    panel_id=_pid,
                )
        # Deliver each panel config
        for pc_id in panel_config_ids:
            try:
                _deliver_panel_config_to_user(chat_id, pc_id, package_row)
            except Exception as e:
                log.error("[PANEL_DELIVERY] Error delivering panel_config %s: %s", pc_id, e)
                _notify_panel_error(
                    uid=uid, package_row=package_row,
                    stage="تحویل کانفیگ به کاربر",
                    detail=str(e), panel_config_id=pc_id
                )
        # Check referral purchase reward for panel deliveries
        if panel_config_ids:
            try:
                from ..ui.notifications import check_and_give_referral_purchase_reward
                check_and_give_referral_purchase_reward(uid)
            except Exception:
                pass
            try:
                admin_purchase_notify(payment_method, get_user(uid), package_row, purchase_id=None)
            except Exception:
                pass
        return panel_config_ids, []

    # ── Manual / stock-based packages (original logic) ────────────────────────
    purchase_ids  = []
    pending_ids   = []

    for i in range(quantity):
        # Reserve one config at a time
        cfg_id = reserve_first_config(package_id)
        if not cfg_id:
            # No stock — create a pending order for this slot
            p_id = create_pending_order(uid, package_id, payment_id, unit_price, payment_method, quantity=1)
            pending_ids.append(p_id)
            continue
        try:
            purchase_id = assign_config_to_user(
                cfg_id, uid, package_id, unit_price, payment_method, is_test=0
            )
            purchase_ids.append(purchase_id)
        except Exception:
            release_reserved_config(cfg_id)
            p_id = create_pending_order(uid, package_id, payment_id, unit_price, payment_method, quantity=1)
            pending_ids.append(p_id)

    # Check stock level and notify admins if thresholds crossed
    try:
        from ..ui.notifications import check_and_notify_stock
        _pkg_name = package_row["name"] if package_row else str(package_id)
        check_and_notify_stock(package_id, _pkg_name)
    except Exception:
        pass

    return purchase_ids, pending_ids


def _build_config_from_template(cpkg, client_uuid, client_name):
    """
    Build a VLESS/VMess/Trojan config URL from a saved sample template.

    Only two dynamic parts are replaced:
      1. The UUID in the URL body (regex, first occurrence).
      2. The #fragment — if cpkg['sample_client_name'] is non-empty and is found
         inside the decoded fragment, ONLY that substring is replaced with
         client_name, preserving any prefix / suffix (e.g. ⚕️TUN_-NAME-main).
         If sample_client_name is empty or not found, the entire fragment is
         replaced with client_name (safe backward-compat fallback).

    Everything else (domain, port, path, host header, query params order, …)
    is taken verbatim from the template — the panel IP is never used.
    """
    import re as _re
    import urllib.parse as _up

    # sqlite3.Row doesn't support .get() — normalise to dict
    if not isinstance(cpkg, dict):
        cpkg = dict(cpkg)

    tmpl = (cpkg.get("sample_config") or "").strip()
    if not tmpl:
        return None

    _UUID_RE = _re.compile(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        _re.IGNORECASE
    )

    # Step 1: replace UUID (only first occurrence — the one right after the scheme)
    config = _UUID_RE.sub(client_uuid, tmpl, count=1)

    # Step 2: replace the fragment while preserving template prefix/suffix
    if "#" in config:
        base_part, frag_encoded = config.rsplit("#", 1)
        frag_decoded = _up.unquote(frag_encoded)

        sample_name = (cpkg.get("sample_client_name") or "").strip()
        if sample_name and sample_name in frag_decoded:
            # Replace ONLY the sample name portion — prefix/suffix stays intact
            new_frag = frag_decoded.replace(sample_name, client_name, 1)
        else:
            # Fallback: replace entire fragment
            new_frag = client_name

        # Re-encode so special chars (emojis, /, …) are preserved correctly
        new_frag_encoded = _up.quote(new_frag, safe="")
        config = base_part + "#" + new_frag_encoded
    else:
        config = config + "#" + _up.quote(client_name, safe="")

    return config


def _build_sub_from_template(cpkg, sub_id):
    """
    Build a subscription URL from the saved sample sub URL template.

    Only the last path segment (the unique per-client token) is replaced with
    sub_id. The base URL, port, and path structure are taken from the template,
    so the panel's path prefix (e.g. /emadhb/) is NEVER included unless the
    admin explicitly put it in the sample_sub_url.

    Example:
      template : http://stareh.parhiiz.top:2096/sub/vn4tzbq10exfcep9
      sub_id   : 3721ec6100d94a4b
      result   : http://stareh.parhiiz.top:2096/sub/3721ec6100d94a4b
    """
    # sqlite3.Row doesn't support .get() — normalise to dict
    if not isinstance(cpkg, dict):
        cpkg = dict(cpkg)

    tmpl = (cpkg.get("sample_sub_url") or "").strip().rstrip("/")
    if not tmpl:
        return None

    # Replace the last path segment (the sub identifier)
    if "/" in tmpl:
        base = tmpl.rsplit("/", 1)[0]
        return f"{base}/{sub_id}"
    # Degenerate case — just append
    return f"{tmpl}/{sub_id}"


def _rebuild_panel_configs_for_cpkg(cpkg_id):
    """
    Called after admin edits sample_config or sample_sub_url on a client package.

    Fetches every sold panel_config that was created from this template (cpkg_id)
    and re-renders client_config_text / client_sub_url using the updated template.

    Dynamic per-user values that are PRESERVED:
      - client_uuid  (never regenerated)
      - client_name  (service name, never changed)
      - sub_id       (derived from uuid, always the same)

    Everything else is taken from the new template.

    Returns the number of configs rebuilt.
    """
    cpkg = get_panel_client_package(cpkg_id)
    if not cpkg:
        log.warning("[TEMPLATE_REBUILD] cpkg %s not found", cpkg_id)
        return 0

    # sqlite3.Row doesn't support .get() — normalise to dict
    if not isinstance(cpkg, dict):
        cpkg = dict(cpkg)

    configs = get_panel_configs_by_cpkg(cpkg_id)
    rebuilt = 0

    for pc in configs:
        try:
            client_uuid = (pc["client_uuid"] or "").strip()
            client_name = (pc["client_name"] or "").strip()
            # sub_id is always first-16-hex-chars of UUID (same as create_client)
            sub_id = client_uuid.replace("-", "")[:16] if client_uuid else ""

            new_config = (
                _build_config_from_template(cpkg, client_uuid, client_name)
                if cpkg["sample_config"]
                else pc["client_config_text"]
            )
            new_sub = (
                _build_sub_from_template(cpkg, sub_id)
                if cpkg["sample_sub_url"]
                else pc["client_sub_url"]
            )

            update_panel_config_texts(
                pc["id"],
                new_config or pc["client_config_text"],
                new_sub    or pc["client_sub_url"],
            )
            rebuilt += 1
        except Exception as exc:
            log.warning("[TEMPLATE_REBUILD] failed for panel_config %s: %s", pc["id"], exc)

    log.info("[TEMPLATE_REBUILD] rebuilt %d configs for cpkg %s", rebuilt, cpkg_id)
    return rebuilt


def _build_config_from_inbound(inbound, client_uuid, client_name, panel, real_port):
    """
    Build a config URL by parsing the inbound's streamSettings.
    This is a fallback used when we cannot fetch the sub URL.
    Handles ExternalProxy settings (CDN / tunnel addresses).
    Returns a config string or None.
    """
    import json as _json, base64 as _b64, urllib.parse as _up
    try:
        proto  = (inbound.get("protocol") or "").lower()
        ss_raw = inbound.get("streamSettings") or "{}"
        if isinstance(ss_raw, str):
            ss = _json.loads(ss_raw)
        else:
            ss = ss_raw

        network  = (ss.get("network") or "tcp").lower()
        security = (ss.get("security") or "none").lower()

        # ── ExternalProxy (CDN / FluxTunnel / Cloudflare, etc.) ──────────────
        # 3x-ui stores externalProxy as a JSON string or list in the inbound.
        # If present, the first entry's dest+port override the connection address/port.
        ext_proxy_addr = None
        ext_proxy_port = None
        ep_raw = inbound.get("externalProxy")
        if ep_raw:
            try:
                if isinstance(ep_raw, str):
                    ep_raw = _json.loads(ep_raw)
                if isinstance(ep_raw, list) and ep_raw:
                    ep0 = ep_raw[0]
                    ext_proxy_addr = (ep0.get("dest") or "").strip() or None
                    if ep0.get("port"):
                        ext_proxy_port = int(ep0["port"])
            except Exception:
                pass

        # Collect query params
        params = {"type": network}

        # WS settings
        if network == "ws":
            ws = ss.get("wsSettings") or ss.get("wsConfig") or {}
            ws_path = ws.get("path") or "/"
            ws_host = (ws.get("headers") or {}).get("Host") or ""
            params["path"] = ws_path
            if ws_host:
                params["host"] = ws_host

        # gRPC settings
        elif network == "grpc":
            grpc = ss.get("grpcSettings") or ss.get("grpcConfig") or {}
            params["serviceName"] = grpc.get("serviceName") or ""
            params["mode"]        = grpc.get("multiMode") and "multi" or "gun"

        # TCP with HTTP obfs
        elif network == "tcp":
            tcp = ss.get("tcpSettings") or {}
            hdr = tcp.get("header") or {}
            if (hdr.get("type") or "").lower() == "http":
                req   = hdr.get("request") or {}
                hosts = req.get("headers", {}).get("Host") or []
                t_path = (req.get("path") or ["/"])[0]
                params["headerType"] = "http"
                params["path"]       = t_path
                if isinstance(hosts, list) and hosts:
                    params["host"] = hosts[0]

        # TLS / reality
        if security == "tls":
            params["security"] = "tls"
            tls = ss.get("tlsSettings") or {}
            sni = tls.get("serverName") or ""
            if sni:
                params["sni"] = sni
            fp = tls.get("fingerprint") or ""
            if fp:
                params["fp"] = fp
        elif security == "reality":
            params["security"] = "reality"
            rs = ss.get("realitySettings") or {}
            params["sni"] = rs.get("serverNames", [""])[0] if isinstance(rs.get("serverNames"), list) else ""
            params["pbk"] = rs.get("publicKey") or ""
            params["fp"]  = rs.get("fingerprint") or "chrome"
            sid = rs.get("shortIds", [""])[0] if isinstance(rs.get("shortIds"), list) else ""
            if sid:
                params["sid"] = sid
        else:
            params["security"] = "none"
            params["encryption"] = "none"

        # Connection address priority:
        # 1. ExternalProxy dest (CDN/tunnel address configured in 3x-ui)
        # 2. WS host header / SNI
        # 3. Panel host (fallback)
        conn_addr = ext_proxy_addr or params.get("host") or params.get("sni") or panel["host"]
        # Use ExternalProxy port if available (overrides inbound listen port)
        conn_port = ext_proxy_port or real_port

        qs = _up.urlencode({k: v for k, v in params.items() if v})
        remark = _up.quote(client_name)

        if proto == "vless":
            return f"vless://{client_uuid}@{conn_addr}:{conn_port}?{qs}#{remark}"

        elif proto == "vmess":
            vmess_obj = {
                "v": "2", "ps": client_name,
                "add": conn_addr, "port": str(conn_port),
                "id": client_uuid, "aid": "0",
                "net": network, "type": "none",
                "path": params.get("path", ""),
                "host": params.get("host", ""),
                "tls": "tls" if security == "tls" else "",
            }
            return "vmess://" + _b64.b64encode(_json.dumps(vmess_obj).encode()).decode()

        elif proto == "trojan":
            return f"trojan://{client_uuid}@{conn_addr}:{conn_port}?{qs}#{remark}"

    except Exception as exc:
        log.warning("_build_config_from_inbound error: %s", exc)
    return None


def _create_panel_config(uid, package_id, payment_id, chat_id=None):
    """
    Create a config in the panel for uid/package_id.
    If the package has a client_package_id, the sample config/sub URL from that
    client package is used as a template (only UUID and name are substituted).
    Otherwise falls back to fetching from the panel API.
    Returns (True, delivery_mode, panel_config_id) or (False, error_str, None).
    """
    import random
    import string
    import re as _re
    from ..panels.client import PanelClient

    package_row = get_package(package_id)
    if not package_row:
        return False, "پکیج یافت نشد", None

    try:
        panel_id      = package_row["panel_id"]
        panel_inbound = int(package_row["panel_port"] or 0)   # stored as inbound ID
        delivery_mode = package_row["delivery_mode"] or "config_only"
        panel_type    = package_row["panel_type"] or "sanaei"
        cpkg_id       = package_row["client_package_id"] if "client_package_id" in package_row.keys() else None
    except (IndexError, KeyError):
        return False, "اطلاعات پنل پکیج ناقص است", None

    if not panel_id or not panel_inbound:
        return False, "پنل یا شماره اینباند پکیج تنظیم نشده", None

    panel = get_panel(panel_id)
    if not panel:
        return False, "پنل مرتبط یافت نشد", None

    # Load client package template — first try explicit link, then auto-detect by panel+inbound
    cpkg = get_panel_client_package(cpkg_id) if cpkg_id else None
    if not cpkg:
        cpkg = get_panel_client_package_by_inbound(panel_id, panel_inbound)
    # sqlite3.Row doesn't support .get() — normalise to dict
    if cpkg is not None and not isinstance(cpkg, dict):
        cpkg = dict(cpkg)

    client = PanelClient(
        protocol=panel["protocol"],
        host=panel["host"],
        port=panel["port"],
        path=panel["path"] or "",
        username=panel["username"],
        password=panel["password"],
        sub_url_base=panel["sub_url_base"] if panel["sub_url_base"] else "",
    )

    # ── Connection-error detector ─────────────────────────────────────────────
    def _is_conn_err(e):
        s = str(e).lower()
        return any(x in s for x in [
            "connection refused", "max retries exceeded", "failed to establish",
            "newconnectionerror", "httpsconnectionpool", "remotedisconnected",
            "connection timed out", "read timed out", "timeout",
            "connection reset", "connection aborted", "connectionreseterror",
            "econnreset", "broken pipe", "reset by peer",
        ])

    CONN_RETRY_DELAY   = 30    # seconds between retries when server is down
    FUNC_RETRY_TIMEOUT = 180   # 3 min timeout for non-connection errors
    FUNC_RETRY_DELAY   = 15
    MAX_WAIT           = 28800 # 8-hour absolute hard cap

    _t_start           = time.time()
    _waiting_notified  = False
    _last_periodic     = 0.0
    PERIODIC_INTERVAL  = 300   # notify user every 5 minutes while waiting

    def _maybe_notify_waiting():
        nonlocal _waiting_notified, _last_periodic
        if not chat_id:
            return
        now = time.time()
        if not _waiting_notified:
            try:
                bot.send_message(
                    chat_id,
                    "⏳ <b>سرور پنل در حال حاضر در دسترس نیست</b>\n\n"
                    "سفارش شما در صف انتظار قرار گرفت. "
                    "به محض بازگشت اتصال، سرویس شما ساخته و تحویل داده می‌شود.",
                    parse_mode="HTML",
                )
                _waiting_notified = True
                _last_periodic = now
            except Exception:
                pass
        elif now - _last_periodic >= PERIODIC_INTERVAL:
            try:
                bot.send_message(chat_id, "⏳ هنوز در حال تلاش برای اتصال به پنل...",
                                 parse_mode="HTML")
                _last_periodic = now
            except Exception:
                pass

    def _notify_reconnected():
        if _waiting_notified and chat_id:
            try:
                bot.send_message(chat_id, "✅ اتصال به پنل برقرار شد، در حال ساخت سرویس...",
                                 parse_mode="HTML")
            except Exception:
                pass

    # ── Step 1: login ─────────────────────────────────────────────────────────
    login_err = None
    _t0 = time.time()
    while True:
        if time.time() - _t_start > MAX_WAIT:
            login_err = "حداکثر زمان انتظار (8 ساعت) تمام شد"
            break
        ok, login_err = client.login()
        if ok:
            login_err = None
            _notify_reconnected()
            break
        elapsed = time.time() - _t0
        if _is_conn_err(login_err):
            _maybe_notify_waiting()
            log.warning("_create_panel_config: login CONN_ERR (%.0fs elapsed), retry in %ds: %s",
                        elapsed, CONN_RETRY_DELAY, login_err)
            time.sleep(CONN_RETRY_DELAY)
        else:
            log.warning("_create_panel_config: login failed (%.0fs elapsed): %s", elapsed, login_err)
            if elapsed + FUNC_RETRY_DELAY >= FUNC_RETRY_TIMEOUT:
                break
            time.sleep(FUNC_RETRY_DELAY)
    if login_err is not None:
        return False, f"اتصال به پنل ناموفق: {login_err}", None

    # ── Step 2: fetch inbound ─────────────────────────────────────────────────
    inbound_remark = ""
    real_port    = 0
    inbound = None
    _last_inb_err = None
    _t0 = time.time()
    while True:
        if time.time() - _t_start > MAX_WAIT:
            break
        inbound = client.find_inbound_by_id(panel_inbound)
        if inbound:
            break
        elapsed = time.time() - _t0
        # find_inbound doesn't return an error string — re-login to check connectivity
        _ok_chk, _chk_err = client.login()
        if not _ok_chk and _is_conn_err(_chk_err):
            _maybe_notify_waiting()
            log.warning("_create_panel_config: find_inbound CONN_ERR (%.0fs elapsed), retry in %ds",
                        elapsed, CONN_RETRY_DELAY)
            time.sleep(CONN_RETRY_DELAY)
        else:
            log.warning("_create_panel_config: find_inbound failed (%.0fs elapsed)", elapsed)
            if elapsed + FUNC_RETRY_DELAY >= FUNC_RETRY_TIMEOUT:
                break
            time.sleep(FUNC_RETRY_DELAY)
    if not inbound:
        return False, f"اینباند با شماره {panel_inbound} در پنل یافت نشد", None

    inbound_id     = inbound["id"]
    real_port      = int(inbound.get("port") or 0)
    inbound_remark = (inbound.get("remark") or inbound.get("tag") or "").strip()

    # Generate config name: {user_id}_{random6}
    rand_str    = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    client_name = f"{uid}_{rand_str}"

    # Calculate traffic & expiry
    volume_gb     = float(package_row["volume_gb"] or 0)
    duration_days = int(package_row["duration_days"] or 0)
    traffic_bytes = int(volume_gb * 1024 * 1024 * 1024) if volume_gb > 0 else 0

    if duration_days > 0:
        expire_dt  = datetime.now() + timedelta(days=duration_days)
        expire_ms  = int(expire_dt.timestamp() * 1000)
        expire_str = expire_dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        expire_ms  = 0
        expire_str = None

    # ── Step 3: create client ─────────────────────────────────────────────────
    result = None
    create_err = None
    _t0 = time.time()
    while True:
        if time.time() - _t_start > MAX_WAIT:
            create_err = "حداکثر زمان انتظار (8 ساعت) تمام شد"
            break
        ok, result = client.create_client(inbound_id, client_name, traffic_bytes, expire_ms)
        if ok:
            create_err = None
            break
        create_err = result
        elapsed = time.time() - _t0
        if _is_conn_err(create_err):
            _maybe_notify_waiting()
            log.warning("_create_panel_config: create_client CONN_ERR (%.0fs elapsed), retry in %ds: %s",
                        elapsed, CONN_RETRY_DELAY, create_err)
            time.sleep(CONN_RETRY_DELAY)
        else:
            log.warning("_create_panel_config: create_client failed (%.0fs elapsed): %s", elapsed, create_err)
            if elapsed + FUNC_RETRY_DELAY >= FUNC_RETRY_TIMEOUT:
                break
            # rotate client name to avoid duplicate key conflicts on retry
            rand_str    = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            client_name = f"{uid}_{rand_str}"
            time.sleep(FUNC_RETRY_DELAY)
    if create_err is not None:
        return False, f"خطا در ساخت کلاینت: {create_err}", None

    client_uuid, sub_id = result
    # Default sub URL from panel — may be overridden by template below
    sub_url = client.get_sub_url(client_uuid)

    config_text = None

    # ── Step 4a: Build config from client package template (preferred path) ──
    # Uses _build_config_from_template which:
    #   • replaces ONLY the UUID in the URL body
    #   • in the #fragment, replaces only cpkg['sample_client_name'] with
    #     client_name — preserving emoji prefix / -main suffix etc.
    #   • keeps domain, port, host header, path, query params from template
    if cpkg and cpkg["sample_config"]:
        config_text = _build_config_from_template(cpkg, client_uuid, client_name)
        log.info("_create_panel_config: built config from template for uid=%s", uid)

    # ── Step 4b: Build sub URL from template (always, when available) ────────
    # NOT limited to sub_only/both — the sub URL is stored in DB regardless of
    # delivery_mode and must be correct for future reference / re-renders.
    # The panel's path prefix (e.g. /emadhb/) is NEVER injected here.
    if cpkg and cpkg["sample_sub_url"]:
        sub_url = _build_sub_from_template(cpkg, sub_id) or sub_url

    # ── Step 4c: Fetch from panel API (fallback when no config template) ─────
    if not config_text and delivery_mode in ("config_only", "both"):
        fetch_ok, fetch_result = client.fetch_client_config(sub_id)
        if fetch_ok and fetch_result:
            for line in fetch_result:
                if not line.startswith("http://") and not line.startswith("https://"):
                    config_text = line
                    break
            if not config_text:
                config_text = fetch_result[0]
        else:
            log.warning("_create_panel_config: sub fetch failed (%s), building from streamSettings", fetch_result)

    # ── Step 4d: Build from streamSettings (last fallback) ───────────────────
    if not config_text:
        config_text = _build_config_from_inbound(
            inbound=inbound,
            client_uuid=client_uuid,
            client_name=client_name,
            panel=panel,
            real_port=real_port,
        ) or sub_url

    pc_id = add_panel_config(
        user_id=uid,
        package_id=package_id,
        panel_id=panel_id,
        panel_type=panel_type,
        inbound_id=inbound_id,
        inbound_port=real_port,
        client_name=client_name,
        client_uuid=client_uuid,
        client_sub_url=sub_url,
        client_config_text=config_text,
        inbound_remark=inbound_remark,
        expire_at=expire_str,
        payment_id=payment_id,
        cpkg_id=cpkg["id"] if cpkg else None,  # store which template was used
    )

    return True, delivery_mode, pc_id


def _deliver_panel_config_to_user(chat_id, panel_config_id, package_row):
    """Send the panel-created config to the user based on delivery_mode."""
    from ..db import get_panel_config
    from ..helpers import fmt_vol, fmt_dur

    pc = get_panel_config(panel_config_id)
    if not pc:
        log.error("[PANEL_DELIVERY] panel_config %s not found in DB", panel_config_id)
        _notify_panel_error(
            uid=chat_id, package_row=package_row,
            stage="تحویل کانفیگ — رکورد در دیتابیس یافت نشد",
            detail=f"panel_config_id={panel_config_id}",
            panel_config_id=panel_config_id,
        )
        try:
            bot.send_message(chat_id,
                "⚠️ <b>خطا در تحویل سرویس</b>\n\n"
                "متأسفانه در تحویل سرویس مشکلی پیش آمد.\n"
                "لطفاً با پشتیبانی تماس بگیرید.",
                parse_mode="HTML")
        except Exception:
            pass
        return

    # ── Pull raw values first (needed for emergency fallback) ─────────────────
    raw_config_text = pc["client_config_text"] or ""
    raw_sub_url     = pc["client_sub_url"] or ""

    try:
        _deliver_panel_config_inner(chat_id, panel_config_id, package_row, pc)
    except Exception as _inner_exc:
        # Something went wrong in the rendering/QR path — send plain-text fallback
        log.error("[PANEL_DELIVERY] inner delivery failed for pc=%s: %s", panel_config_id, _inner_exc, exc_info=True)
        _notify_panel_error(
            uid=chat_id, package_row=package_row,
            stage="تحویل کانفیگ — خطای داخلی رندرینگ",
            detail=str(_inner_exc),
            panel_config_id=panel_config_id,
        )
        # Emergency plain-text fallback — send the config to user without formatting
        try:
            fallback_lines = ["🎉 <b>سرویس شما آماده است!</b>\n"]
            if raw_config_text.strip():
                fallback_lines.append(f"📄 <b>Config:</b>\n<code>{esc(raw_config_text)}</code>")
            if raw_sub_url.strip():
                fallback_lines.append(f"🔗 <b>لینک ساب:</b>\n{esc(raw_sub_url)}")
            if raw_config_text.strip() or raw_sub_url.strip():
                kb_back = types.InlineKeyboardMarkup()
                kb_back.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="nav:main"))
                bot.send_message(chat_id, "\n\n".join(fallback_lines),
                                 parse_mode="HTML", reply_markup=kb_back)
        except Exception as _fb_exc:
            log.error("[PANEL_DELIVERY] even fallback failed for pc=%s: %s", panel_config_id, _fb_exc)


def _deliver_panel_config_inner(chat_id, panel_config_id, package_row, pc):
    """Inner delivery — builds message with premium emoji + QR and sends it."""
    from ..helpers import fmt_vol, fmt_dur
    import io as _io
    import qrcode as _qrcode
    from ..ui.premium_emoji import ce

    try:
        delivery_mode = package_row["delivery_mode"] or "config_only"
    except (IndexError, KeyError):
        delivery_mode = "config_only"

    vol_label  = "نامحدود" if not package_row["volume_gb"]     else fmt_vol(package_row["volume_gb"])
    dur_label  = "نامحدود" if not package_row["duration_days"] else fmt_dur(package_row["duration_days"])
    max_u      = package_row["max_users"] if "max_users" in (package_row.keys() if hasattr(package_row, "keys") else {}) else 0
    users_label = "نامحدود" if not max_u else (
        "تک‌کاربره" if max_u == 1 else f"{max_u} کاربره"
    )

    service_name  = pc["client_name"] or ""
    config_text   = pc["client_config_text"] or ""
    sub_url       = pc["client_sub_url"] or ""

    # Extract the actual service name from the config's #tag (panel may add prefix/suffix)
    if config_text and "#" in config_text:
        try:
            raw_remark = config_text.rsplit("#", 1)[1].strip()
            if raw_remark:
                service_name = urllib.parse.unquote(raw_remark)
        except Exception:
            pass

    inbound_remark = pc["inbound_remark"] if "inbound_remark" in (pc.keys() if hasattr(pc, "keys") else {}) else ""
    type_label    = inbound_remark or (package_row["type_name"] if "type_name" in (package_row.keys() if hasattr(package_row, "keys") else {}) else "")
    show_pkg      = int(package_row["show_name"]) if "show_name" in package_row.keys() else 1
    pkg_line      = f"{ce('📦', '5258134813302332906')} پکیج: <b>{esc(package_row['name'])}</b>\n" if show_pkg else ""
    _expire_at    = pc["expire_at"] if "expire_at" in pc.keys() else ""
    expire_line   = f"{ce('📅', '5379748062124056162')} انقضا: <b>{_expire_at[:10]}</b>\n" if _expire_at else ""

    header = f"{ce('✅', '5260463209562776385')} <b>سرویس شما آماده است!</b>"

    info_block = (
        f"{ce('🔮', '5361837567463399422')} نام سرویس: <b>{esc(service_name)}</b>\n"
        f"{ce('🧩', '5463224921935082813')} نوع سرویس: <b>{esc(type_label)}</b>\n"
        f"{pkg_line}"
        f"{ce('🔋', '5924538142198600679')} حجم: <b>{esc(vol_label)}</b>\n"
        f"{ce('⏰', '5343724178547691280')} مدت: <b>{esc(dur_label)}</b>\n"
        f"{ce('👥', '5372926953978341366')} تعداد کاربر: <b>{esc(users_label)}</b>\n"
        f"{expire_line}"
    )

    has_cfg     = bool(config_text.strip())
    has_sub     = bool(sub_url.strip())

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="nav:main"))

    def _send_with_qr(qr_source, text):
        try:
            qr_img = _qrcode.make(qr_source)
            bio    = _io.BytesIO()
            qr_img.save(bio, format="PNG")
            bio.seek(0)
            bio.name = "qrcode.png"
            bot.send_photo(chat_id, bio, caption=text, parse_mode="HTML", reply_markup=kb)
        except Exception as _qr_exc:
            log.warning("_deliver_panel_config QR generation failed: %s", _qr_exc)
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

    def _fail_no_content(reason: str):
        """Notify user and alert admins when config content is missing."""
        bot.send_message(chat_id,
            f"{header}\n\n{info_block}\n"
            f"⚠️ <b>خطا در تحویل سرویس:</b> {esc(reason)}\n"
            "لطفاً با پشتیبانی تماس بگیرید.",
            parse_mode="HTML", reply_markup=kb)
        _notify_panel_error(
            uid=chat_id,
            package_row=package_row,
            stage="تحویل کانفیگ — محتوا یافت نشد",
            detail=f"{reason} | config_id={panel_config_id} | mode={delivery_mode}",
            panel_config_id=panel_config_id,
        )

    if delivery_mode == "config_only":
        if has_cfg:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('💝', '5900197669178970457')} <b>Config:</b>\n<code>{esc(config_text)}</code>"
            )
            _send_with_qr(config_text, text)
        else:
            _fail_no_content("کانفیگ در دسترس نیست")

    elif delivery_mode == "sub_only":
        if has_sub:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('🔗', '5271604874419647061')} <b>لینک ساب:</b>\n{esc(sub_url)}"
            )
            _send_with_qr(sub_url, text)
        else:
            _fail_no_content("لینک ساب در دسترس نیست")

    else:  # both
        if has_cfg and has_sub:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('💝', '5900197669178970457')} <b>Config:</b>\n<code>{esc(config_text)}</code>\n\n"
                f"{ce('🔗', '5271604874419647061')} <b>لینک ساب:</b>\n{esc(sub_url)}"
            )
            _send_with_qr(config_text, text)  # QR for config when both present
        elif has_cfg:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('💝', '5900197669178970457')} <b>Config:</b>\n<code>{esc(config_text)}</code>"
            )
            _send_with_qr(config_text, text)
        elif has_sub:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('🔗', '5271604874419647061')} <b>لینک ساب:</b>\n{esc(sub_url)}"
            )
            _send_with_qr(sub_url, text)
        else:
            _fail_no_content("کانفیگ و ساب هر دو در دسترس نیستند")



def _send_bulk_delivery_result(chat_id, uid, package_row, purchase_ids, pending_ids,
                               method_label):
    """
    Send delivery messages to user after bulk purchase.
    For panel packages, delivery is already done inside _deliver_bulk_configs.
    For manual packages, delivers all purchased configs then informs about pending ones.
    """
    from ..ui.notifications import deliver_purchase_message, admin_purchase_notify

    # Panel packages already delivered their configs; just show a summary
    try:
        config_source = package_row["config_source"] or "manual"
    except (IndexError, KeyError):
        config_source = "manual"

    if config_source == "panel":
        if not purchase_ids:
            try:
                bot.send_message(
                    chat_id,
                    "⚠️ <b>مشکل در تحویل سرویس پنل</b>\n\n"
                    "لطفاً با پشتیبانی تماس بگیرید.",
                    parse_mode="HTML",
                    reply_markup=back_button("main"),
                )
            except Exception:
                pass
        return

    total = len(purchase_ids) + len(pending_ids)

    if purchase_ids:
        if len(purchase_ids) > 1:
            try:
                bot.send_message(
                    chat_id,
                    f"🎉 <b>خرید شما با موفقیت انجام شد!</b>\n\n"
                    f"📦 تعداد کانفیگ‌های آماده: <b>{len(purchase_ids)}</b> از <b>{total}</b>\n\n"
                    "⬇️ کانفیگ‌های شما یکی‌یکی در پیام‌های بعدی ارسال می‌شوند.",
                    parse_mode="HTML",
                    reply_markup=back_button("main")
                )
            except Exception:
                pass
        for pid in purchase_ids:
            try:
                deliver_purchase_message(chat_id, pid)
                admin_purchase_notify(method_label, get_user(uid), package_row, purchase_id=pid)
            except Exception as e:
                print(f"[BULK_DELIVERY] Error delivering purchase {pid}: {e}")

    if pending_ids:
        from ..ui.notifications import notify_pending_order_to_admins
        count_pending = len(pending_ids)
        try:
            bot.send_message(
                chat_id,
                f"⚠️ <b>بخشی از سفارش در انتظار تأمین موجودی</b>\n\n"
                f"✅ {len(purchase_ids)} کانفیگ تحویل داده شد.\n"
                f"⏳ {count_pending} کانفیگ دیگر در صف انتظار قرار گرفت.\n\n"
                "به‌محض تأمین موجودی، کانفیگ‌های باقیمانده به‌صورت خودکار ارسال می‌شوند.\n"
                "🙏 از صبر شما متشکریم.",
                parse_mode="HTML",
                reply_markup=back_button("main")
            )
        except Exception:
            pass
        for p_id in pending_ids:
            try:
                notify_pending_order_to_admins(p_id, uid, package_row, package_row["price"], method_label)
            except Exception:
                pass


# ── Voucher helpers ────────────────────────────────────────────────────────────
import random


def _generate_card_final_amount(base_amount, payment_id):
    """Replace last 3 digits of base_amount with a random suffix (001-999).
    Tries to avoid duplicates among currently pending card payments."""
    base = (base_amount // 1000) * 1000
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT final_amount FROM payments "
            "WHERE payment_method='card' AND status='pending' "
            "AND final_amount IS NOT NULL AND id!=?",
            (payment_id,)
        ).fetchall()
    used = {r["final_amount"] for r in rows}
    for _ in range(50):
        suffix = random.randint(1, 999)
        candidate = base + suffix
        if candidate not in used:
            return candidate
    return base + random.randint(1, 999)


def _build_card_payment_page(card, bank, owner, price, final_amount):
    """Return (text, kb) for the card-to-card payment page.
    When final_amount != price (random mode active), shows prominent amount
    with warning + copy buttons. Otherwise shows the standard layout.
    """
    is_random = (final_amount is not None and final_amount != price)
    display_amount = final_amount if is_random else price
    card_clean = card.replace("-", "").replace(" ", "")

    card_info = (
        f"🏦 {esc(bank or 'ثبت نشده')}\n"
        f"👤 {esc(owner or 'ثبت نشده')}\n"
        f"💳 <code>{esc(card)}</code>\n\n"
    )

    if is_random:
        amount_rial = display_amount * 10
        text = (
            "💳 <b>کارت به کارت</b>\n\n"
            f"{card_info}"
            "┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅\n"
            f"💰 <b>مبلغ قابل پرداخت</b>\n"
            f"<b>{fmt_price(display_amount)} تومان</b>\n\n"
            "⚠️ <b>حتما مبلغ را دقیقا به همین مقدار واریز نمایید.\n"
            "در صورت واریز مبلغ غیر دقیق، مسئولیت تایید نشدن رسید بر عهده خود شما خواهد بود.</b>\n\n"
            "📸 پس از واریز، تصویر رسید یا شماره پیگیری را ارسال کنید."
        )
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("📋 کپی قیمت به تومان",
                                       copy_text=types.CopyTextButton(text=str(display_amount))),
            types.InlineKeyboardButton("📋 کپی قیمت به ریال",
                                       copy_text=types.CopyTextButton(text=str(amount_rial))),
        )
        kb.add(types.InlineKeyboardButton("💳 کپی شماره کارت",
                                          copy_text=types.CopyTextButton(text=card_clean)))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
    else:
        text = (
            "💳 <b>کارت به کارت</b>\n\n"
            f"لطفاً مبلغ <b>{fmt_price(price)}</b> تومان را به کارت زیر واریز کنید:\n\n"
            f"{card_info}"
            "📸 پس از واریز، تصویر رسید یا شماره پیگیری را ارسال کنید."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))

    return text, kb
import string

def _generate_voucher_codes(count, prefix="GIFT"):
    """Generate `count` unique random voucher codes with a prefix."""
    codes = set()
    chars = string.ascii_uppercase + string.digits
    while len(codes) < count:
        suffix = "".join(random.choices(chars, k=8))
        codes.add(f"{prefix}-{suffix}")
    return list(codes)


def _render_voucher_batch_detail(call, uid, batch_id):
    """Render detail page for a single voucher batch with all individual codes."""
    batch = get_voucher_batch(batch_id)
    if not batch:
        bot.answer_callback_query(call.id, "دسته یافت نشد.", show_alert=True)
        return
    codes = get_voucher_codes_for_batch(batch_id)
    used_count  = batch["used_count"]
    total_count = batch["total_count"]
    remain      = total_count - used_count
    gift_fa = f"{fmt_price(batch['gift_amount'])} تومان" if batch["gift_type"] == "wallet" else "کانفیگ"
    if batch["gift_type"] == "config" and batch["package_id"]:
        pkg = get_package(batch["package_id"])
        if pkg:
            gift_fa = f"کانفیگ: {esc(pkg['name'])} | {fmt_vol(pkg['volume_gb'])} | {fmt_dur(pkg['duration_days'])}"
    text = (
        f"🎫 <b>کارت هدیه: {esc(batch['name'])}</b>\n\n"
        f"🎁 نوع هدیه: {gift_fa}\n"
        f"📊 کل: {total_count} | استفاده شده: {used_count} | مانده: {remain}\n"
        f"📅 ایجاد: {batch['created_at'][:16]}\n\n"
        "─────────────────────\n"
    )
    code_lines = []
    for vc in codes:
        if vc["is_used"]:
            used_time = (vc["used_at"] or "")[:16]
            code_lines.append(
                f"✅ <code>{vc['code']}</code>\n"
                f"   👤 <code>{vc['used_by']}</code>  🕐 {used_time}"
            )
        else:
            code_lines.append(f"❌ <code>{vc['code']}</code>")
    # Telegram message limit 4096 chars — split if needed
    MAX_MSG = 3800
    full_codes_text = "\n".join(code_lines)
    combined = text + full_codes_text
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🗑 حذف این دسته", callback_data=f"admin:vch:del:{batch_id}"),
    )
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:vouchers", icon_custom_emoji_id="5253997076169115797"))
    if len(combined) <= MAX_MSG:
        send_or_edit(call, combined, kb)
    else:
        # Send header + buttons first, then codes in a follow-up message
        send_or_edit(call, text + "(کدها در پیام بعدی)", kb)
        # Split codes into chunks
        chunk, chunks = [], []
        cur_len = 0
        for line in code_lines:
            if cur_len + len(line) + 1 > MAX_MSG:
                chunks.append("\n".join(chunk))
                chunk, cur_len = [], 0
            chunk.append(line)
            cur_len += len(line) + 1
        if chunk:
            chunks.append("\n".join(chunk))
        chat_id = call.message.chat.id
        for ch in chunks:
            try:
                bot.send_message(chat_id, ch, parse_mode="HTML")
            except Exception:
                pass


def _render_voucher_admin_list(call, uid):
    """Render the admin voucher batches management panel."""
    batches = get_all_voucher_batches()
    enabled = setting_get("vouchers_enabled", "1") == "1"
    toggle_lbl = "✅ کارت هدیه: فعال" if enabled else "❌ کارت هدیه: غیرفعال"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data="admin:vch:toggle_global"),
        types.InlineKeyboardButton("➕ افزودن کارت هدیه", callback_data="admin:vch:add"),
    )
    for b in batches:
        used  = b["used_count"]
        total = b["total_count"]
        remain = total - used
        kb.row(
            types.InlineKeyboardButton(f"🎫 {b['name']} ({remain}/{total})", callback_data=f"admin:vch:view:{b['id']}"),
            types.InlineKeyboardButton("📋 اطلاعات", callback_data=f"admin:vch:view:{b['id']}"),
        )
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
    text = (
        "🎫 <b>مدیریت کارت‌های هدیه</b>\n\n"
        f"وضعیت سیستم: {'✅ فعال' if enabled else '❌ غیرفعال'}\n"
        f"تعداد دسته‌ها: {len(batches)}\n\n"
        + ("دسته‌ای ثبت نشده است." if not batches else "برای مشاهده جزئیات روی هر دسته کلیک کنید:")
    )
    send_or_edit(call, text, kb)


def _build_locked_channels_menu():
    """Build the locked-channels admin panel text+keyboard. Returns (text, kb)."""
    rows = get_locked_channels()
    kb = types.InlineKeyboardMarkup()
    # Add button at the top
    kb.add(types.InlineKeyboardButton("➕ افزودن کانال/گروه جدید", callback_data="adm:lch:add"))
    # Two-column rows: channel name (right) | delete (left)
    for row in rows:
        ch = row["channel_id"]
        label = ch if ch.startswith("@") else f"🔢 {ch}"
        kb.row(
            types.InlineKeyboardButton(f"📢 {label}", callback_data="noop"),
            types.InlineKeyboardButton("🗑 حذف", callback_data=f"adm:lch:del:{row['id']}"),
        )
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings",
                                      icon_custom_emoji_id="5253997076169115797"))
    legacy = setting_get("channel_id", "").strip()
    legacy_note = f"\n⚠️ کانال قدیمی (تنظیمات): <code>{esc(legacy)}</code>" if legacy else ""
    text = (
        "📢 <b>مدیریت کانال‌های اجباری / قفل</b>\n\n"
        "ربات تنها زمانی اجازه ورود می‌دهد که کاربر در <b>همه</b> کانال‌های زیر عضو باشد.\n\n"
        f"تعداد کانال‌های فعال: <b>{len(rows)}</b>{legacy_note}"
    )
    return text, kb


def _do_reject_all(call, uid, note):
    """Bulk-reject all pending receipts. note=None means no custom message."""
    from ..db import get_conn as _get_conn, reject_all_pending_payments as _reject_all
    import threading as _threading, time as _time

    with _get_conn() as _c:
        _pending_snap = _c.execute(
            "SELECT id, user_id FROM payments WHERE status='pending'"
            " AND payment_method IN ('card', 'crypto')"
            " AND (receipt_file_id IS NOT NULL"
            " OR (receipt_text IS NOT NULL AND receipt_text != ''))"
        ).fetchall()

    rejected_count = _reject_all()
    log_admin_action(uid, f"رد همه رسیدها: {rejected_count} رسید رد شد")
    if call.id:
        bot.answer_callback_query(call.id, f"✅ {rejected_count} رسید رد شد.", show_alert=True)
    else:
        bot.send_message(uid, f"✅ {rejected_count} رسید رد شد.", parse_mode="HTML")
    _render_pending_receipts_page(call, uid, 0)

    def _notify(rows, custom_note):
        seen = set()
        for prow in rows:
            u = prow["user_id"]
            if u in seen:
                continue
            seen.add(u)
            try:
                if custom_note:
                    msg = f"❌ رسید پرداخت شما رد شد.\n\n📝 دلیل: {custom_note}"
                else:
                    msg = "❌ رسید پرداخت شما توسط ادمین رد شد."
                bot.send_message(u, msg)
            except Exception:
                pass
            _time.sleep(0.05)

    _threading.Thread(target=_notify, args=(_pending_snap, note), daemon=True).start()


def _render_pending_receipts_page(call, uid, page):
    """Render paginated pending receipts list for admin."""
    PAGE_SIZE = 10
    total, rows = get_pending_payments_page(page, PAGE_SIZE)
    # If this page became empty after approve/reject, fall back one page
    if not rows and page > 0:
        page -= 1
        total, rows = get_pending_payments_page(page, PAGE_SIZE)
    if not rows:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "✅ رسید بررسی نشده‌ای وجود ندارد.", kb)
        return
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    KIND = {"wallet_charge": "شارژ کیف‌پول", "buy": "خرید", "renew": "تمدید",
            "renewal": "تمدید", "pnlcfg_renewal": "تمدید (پنل)", "config_purchase": "خرید"}
    header = (
        f"📋 <b>رسیدهای بررسی نشده</b>\n"
        f"صفحه {page + 1} از {total_pages} | تعداد کل: {total}\n"
        "─────────────────────────────\n"
    )
    lines = []
    kb = types.InlineKeyboardMarkup(row_width=3)
    for i, r in enumerate(rows, start=1):
        t_str    = r.get("created_at") or ""
        date_part = t_str[:10] if len(t_str) >= 10 else ""
        time_part = t_str[11:16] if len(t_str) >= 16 else ""
        kind_lbl = KIND.get(r.get("kind", ""), r.get("kind", ""))
        lines.append(
            f"{i}. 🕐 {date_part} {time_part} | {kind_lbl} | 💰 {fmt_price(r['amount'])} تومان"
        )
        kb.row(
            types.InlineKeyboardButton(f"📋 #{i} بیشتر", callback_data=f"admin:pr:det:{r['id']}:{page}"),
            types.InlineKeyboardButton("✅",              callback_data=f"admin:pr:ap:{r['id']}:{page}"),
            types.InlineKeyboardButton("❌",              callback_data=f"admin:pr:rj:{r['id']}:{page}"),
        )
    text = header + "\n".join(lines)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"admin:pr:list:{page - 1}"))
    if (page + 1) < total_pages:
        nav.append(types.InlineKeyboardButton("بعدی ▶️", callback_data=f"admin:pr:list:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("� رد کردن همه", callback_data="admin:pr:reject_all"))
    kb.add(types.InlineKeyboardButton("�🔙 بازگشت", callback_data="admin:panel"))
    send_or_edit(call, text, kb)


def _render_discount_admin_list(call, uid):
    """Render the admin discount codes management panel."""
    codes = get_all_discount_codes()
    enabled = setting_get("discount_codes_enabled", "0") == "1"
    toggle_lbl = "✅ کد تخفیف: فعال" if enabled else "❌ کد تخفیف: غیرفعال"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data="admin:disc:toggle_global"),
        types.InlineKeyboardButton("➕ افزودن کد", callback_data="admin:disc:add"),
    )
    for row in codes:
        status_icon = "✅" if row["is_active"] else "❌"
        audience = row["audience"] if "audience" in row.keys() else "all"
        aud_icon = {"all": "👥", "public": "🙋", "agents": "🤝"}.get(audience, "👥")
        kb.row(
            types.InlineKeyboardButton(f"{status_icon} {aud_icon} {row['code']}", callback_data=f"admin:disc:view:{row['id']}"),
            types.InlineKeyboardButton("⚙️ تنظیمات", callback_data=f"admin:disc:view:{row['id']}"),
        )
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
    total = len(codes)
    text = (
        "🎟 <b>مدیریت کدهای تخفیف</b>\n\n"
        f"وضعیت سیستم: {'✅ فعال' if enabled else '❌ غیرفعال'}\n"
        f"تعداد کدها: {total}\n\n"
        + ("کدی ثبت نشده است." if not codes else "برای مدیریت هر کد، روی آن کلیک کنید:")
    )
    send_or_edit(call, text, kb)


_AUDIENCE_LABELS = {
    "all":     "👥 همه",
    "public":  "🙋 فقط عموم",
    "agents":  "🤝 فقط نمایندگان",
}


def _render_discount_scope_selection(call, uid, edit_code_id=None):
    """Render multi-select UI for discount code scope (types or packages)."""
    sd = state_data(uid)
    scope_type = sd.get("scope_type", "all")
    selected_str = sd.get("scope_selected", "") or ""
    selected = set(int(x) for x in selected_str.split(",") if x.strip())
    is_edit = edit_code_id is not None
    toggle_cb = "admin:disc:stgl_edit" if is_edit else "admin:disc:stgl"
    confirm_cb = "admin:disc:sconf_edit" if is_edit else "admin:disc:sconf"
    back_cb = f"admin:disc:edit_scope:{edit_code_id}" if is_edit else "admin:discounts"
    kb = types.InlineKeyboardMarkup()
    if scope_type == "types":
        items = get_all_types()
        title = "🧩 انتخاب نوع‌های مجاز"
        for item in items:
            check = "✅" if item["id"] in selected else "⬜"
            kb.add(types.InlineKeyboardButton(
                f"{check} {item['name']}",
                callback_data=f"{toggle_cb}:{item['id']}"
            ))
    else:
        items = get_packages(include_inactive=True)
        title = "📦 انتخاب پکیج‌های مجاز"
        for item in items:
            check = "✅" if item["id"] in selected else "⬜"
            kb.add(types.InlineKeyboardButton(
                f"{check} {item['type_name']} — {item['name']}",
                callback_data=f"{toggle_cb}:{item['id']}"
            ))
    sel_count = len(selected)
    if sel_count > 0:
        kb.add(types.InlineKeyboardButton(f"✅ تأیید ({sel_count} مورد انتخابی)", callback_data=confirm_cb))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data=back_cb, icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, f"📌 <b>{title}</b>\n\nموارد مورد نظر را انتخاب و سپس تأیید کنید:", kb)


def _render_discount_code_detail(call, uid, code_id):
    """Render detail page for a single discount code."""
    row = get_discount_code(code_id)
    if not row:
        bot.answer_callback_query(call.id, "کد تخفیف پیدا نشد.", show_alert=True)
        return
    disc_type_fa = "درصد" if row["discount_type"] == "pct" else "مبلغ ثابت"
    disc_val_fa = f"{row['discount_value']}٪" if row["discount_type"] == "pct" else f"{fmt_price(row['discount_value'])} تومان"
    max_total = str(row["max_uses_total"]) if row["max_uses_total"] > 0 else "نامحدود"
    max_per = str(row["max_uses_per_user"]) if row["max_uses_per_user"] > 0 else "نامحدود"
    actual_uses = row["actual_uses"]
    status_fa = "✅ فعال" if row["is_active"] else "❌ غیرفعال"
    toggle_lbl = "❌ غیرفعال کن" if row["is_active"] else "✅ فعال کن"
    audience = row["audience"] if "audience" in row.keys() else "all"
    audience_fa = _AUDIENCE_LABELS.get(audience, "👥 همه")
    scope_type = row["scope_type"] if "scope_type" in row.keys() else "all"
    _SCOPE_LABELS = {"all": "🌐 همه پکیج‌ها", "types": "🧩 نوع‌های خاص", "packages": "📦 پکیج‌های خاص"}
    scope_fa = _SCOPE_LABELS.get(scope_type, "🌐 همه پکیج‌ها")
    if scope_type != "all":
        targets = get_discount_code_targets(code_id)
        if targets:
            if scope_type == "types":
                names = []
                for t in targets:
                    tp = get_type(t["target_id"])
                    names.append(esc(tp["name"]) if tp else str(t["target_id"]))
                scope_fa += f" ({', '.join(names)})"
            else:
                names = []
                for t in targets:
                    pkg = get_package(t["target_id"])
                    names.append(esc(pkg["name"]) if pkg else str(t["target_id"]))
                scope_fa += f" ({', '.join(names)})"
    text = (
        f"🎟 <b>کد تخفیف: {esc(row['code'])}</b>\n\n"
        f"💰 نوع تخفیف: {disc_type_fa} — {disc_val_fa}\n"
        f"📊 استفاده شده: {actual_uses} / {max_total}\n"
        f"👤 هر کاربر: {max_per} بار\n"
        f"🎯 دسترسی: {audience_fa}\n"
        f"📌 محدوده: {scope_fa}\n"
        f"🔵 وضعیت: {status_fa}\n"
        f"📅 ایجاد: {row['created_at'][:10]}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data=f"admin:disc:toggle:{code_id}"),
        types.InlineKeyboardButton("🗑 حذف", callback_data=f"admin:disc:del:{code_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("✏️ ویرایش کد", callback_data=f"admin:disc:edit_code:{code_id}"),
        types.InlineKeyboardButton("✏️ مقدار تخفیف", callback_data=f"admin:disc:edit_val:{code_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("✏️ کل استفاده", callback_data=f"admin:disc:edit_total:{code_id}"),
        types.InlineKeyboardButton("✏️ هر کاربر", callback_data=f"admin:disc:edit_per:{code_id}"),
    )
    kb.add(types.InlineKeyboardButton("🎯 ویرایش دسترسی", callback_data=f"admin:disc:edit_audience:{code_id}"))
    kb.add(types.InlineKeyboardButton("📌 ویرایش محدوده", callback_data=f"admin:disc:edit_scope:{code_id}"))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:discounts", icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)





# ── Module-level helper: build package edit panel text + keyboard ────────────
def _pkg_edit_text_kb(package_row):
    _BR_LABELS = {"all": "همه", "agents": "فقط نمایندگان", "public": "فقط کاربران عادی", "nobody": "هیچ‌کس (فقط هدیه)"}
    _DM_LABELS = {"config_only": "فقط کانفیگ", "sub_only": "فقط ساب", "both": "کانفیگ + ساب"}
    package_id    = package_row["id"]
    show_name_val = package_row["show_name"] if "show_name" in package_row.keys() else 1
    show_name_lbl = "👁 نمایش نام به کاربر: ✅ بله" if show_name_val else "👁 نمایش نام به کاربر: ❌ خیر"
    pkg_active    = package_row["active"] if "active" in package_row.keys() else 1
    pkg_status_label = "✅ فعال — کلیک برای غیرفعال" if pkg_active else "❌ غیرفعال — کلیک برای فعال"
    buyer_role    = package_row["buyer_role"] if "buyer_role" in package_row.keys() else "all"
    br_label      = _BR_LABELS.get(buyer_role, "همه")
    try:
        config_source = package_row["config_source"] or "manual"
    except (IndexError, KeyError):
        config_source = "manual"
    try:
        panel_id   = package_row["panel_id"]
        panel_port = package_row["panel_port"]
        delivery_mode = package_row["delivery_mode"] or "config_only"
    except (IndexError, KeyError):
        panel_id = panel_port = None
        delivery_mode = "config_only"

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✏️ ویرایش نام",   callback_data=f"admin:pkg:ef:name:{package_id}"))
    kb.add(types.InlineKeyboardButton("💰 ویرایش قیمت",  callback_data=f"admin:pkg:ef:price:{package_id}"))
    kb.add(types.InlineKeyboardButton("🔋 ویرایش حجم",   callback_data=f"admin:pkg:ef:volume:{package_id}"))
    kb.add(types.InlineKeyboardButton("⏰ ویرایش مدت",   callback_data=f"admin:pkg:ef:dur:{package_id}"))
    kb.add(types.InlineKeyboardButton("📌 جایگاه نمایش",  callback_data=f"admin:pkg:ef:position:{package_id}"))
    kb.add(types.InlineKeyboardButton("👥 محدودیت کاربر", callback_data=f"admin:pkg:ef:maxusers:{package_id}"))
    kb.add(types.InlineKeyboardButton(show_name_lbl,      callback_data=f"admin:pkg:toggle_sn:{package_id}"))
    kb.add(types.InlineKeyboardButton(f"🔑 خریداران: {br_label} — تغییر", callback_data=f"admin:pkg:set_br:{package_id}"))
    src_lbl = "ثبت دستی" if config_source == "manual" else f"پنل #{panel_id} اینباند {panel_port}"
    kb.add(types.InlineKeyboardButton(f"🔌 منبع کانفیگ: {src_lbl} — تغییر", callback_data=f"admin:pkg:src:{package_id}"))
    kb.add(types.InlineKeyboardButton(pkg_status_label, callback_data=f"admin:pkg:toggleactive:{package_id}"))
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:types", icon_custom_emoji_id="5253997076169115797"))
    cur_pos      = package_row["position"] if "position" in package_row.keys() else 0
    pkg_status_line = "✅ فعال" if pkg_active else "❌ غیرفعال"
    sn_line      = "✅ بله" if show_name_val else "❌ خیر"
    mu_val       = package_row["max_users"] if "max_users" in package_row.keys() else 0
    mu_line      = "نامحدود" if not mu_val else f"{mu_val} کاربره"
    if config_source == "panel":
        src_info = f"پنل #{panel_id} | اینباند {panel_port} | {_DM_LABELS.get(delivery_mode, delivery_mode)}"
    else:
        src_info = "ثبت دستی"
    text = (
        f"📦 <b>ویرایش پکیج</b>\n\n"
        f"نام: {esc(package_row['name'])}\n"
        f"قیمت: {fmt_price(package_row['price'])} تومان\n"
        f"حجم: {fmt_vol(package_row['volume_gb'])}\n"
        f"مدت: {fmt_dur(package_row['duration_days'])}\n"
        f"جایگاه: {cur_pos}\n"
        f"محدودیت کاربر: {mu_line}\n"
        f"نمایش نام به کاربر: {sn_line}\n"
        f"خریداران مجاز: {br_label}\n"
        f"منبع کانفیگ: {src_info}\n"
        f"وضعیت: {pkg_status_line}"
    )
    return text, kb


# ── Per-admin search cache for user config list ────────────────────────────────
_admin_usr_cfg_search: dict = {}


def _show_admin_user_configs(call, admin_uid, target_id, page=0, search=None):
    """Paginated config list (manual + panel) for admin viewing a user."""
    PER_PAGE = 10
    if search is not None:
        if search:
            _admin_usr_cfg_search[admin_uid] = {"target_id": target_id, "query": search}
        else:
            _admin_usr_cfg_search.pop(admin_uid, None)
    cached = _admin_usr_cfg_search.get(admin_uid)
    active_search = cached["query"] if cached and cached.get("target_id") == target_id else None

    _, items_total = get_user_purchases_paged(target_id, page=0, per_page=1, search=active_search)
    _, panel_total = get_user_panel_configs_paged(target_id, page=0, per_page=1, search=active_search)
    total = items_total + panel_total

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    offset = page * PER_PAGE

    if offset < items_total:
        buy_count = min(PER_PAGE, items_total - offset)
        buy_start = offset
    else:
        buy_count = 0
        buy_start = 0

    panel_start = max(0, offset - items_total)
    panel_count = PER_PAGE - buy_count

    if buy_count > 0:
        all_items, _ = get_user_purchases_paged(
            target_id, page=0, per_page=buy_start + buy_count, search=active_search
        )
        items = list(all_items)[buy_start:]
    else:
        items = []

    if panel_count > 0 and panel_start < panel_total:
        actual_panel = min(panel_count, panel_total - panel_start)
        all_panel, _ = get_user_panel_configs_paged(
            target_id, page=0, per_page=panel_start + actual_panel, search=active_search
        )
        panel_items = list(all_panel)[panel_start:]
    else:
        panel_items = []

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ افزودن کانفیگ", callback_data=f"adm:usr:acfg:{target_id}"))

    if active_search:
        q_display = active_search[:18] + ("…" if len(active_search) > 18 else "")
        kb.row(
            types.InlineKeyboardButton(f"🔍 {q_display}", callback_data=f"adm:usr:cfgsrch:{target_id}"),
            types.InlineKeyboardButton("❌ پاک کردن", callback_data=f"adm:usr:cfgclr:{target_id}"),
        )
    else:
        kb.add(types.InlineKeyboardButton("🔍 جست‌وجو", callback_data=f"adm:usr:cfgsrch:{target_id}"))

    for item in items:
        expired_mark = " ❌" if item["is_expired"] else ""
        svc = urllib.parse.unquote(item["service_name"] or "")
        kb.add(types.InlineKeyboardButton(
            f"{svc}{expired_mark}",
            callback_data=f"adm:usrcfg:{target_id}:{item['config_id']}"
        ))

    for pc in panel_items:
        if pc["is_expired"]:
            marker = " ⌛"
        elif int(pc["is_disabled"] or 0):
            marker = " ⛔"
        else:
            marker = ""
        name = pc["client_name"] or pc["package_name"] or f"#{pc['id']}"
        kb.add(types.InlineKeyboardButton(
            f"🔮 {name}{marker}",
            callback_data=f"adm:usrpcfg:{target_id}:{pc['id']}"
        ))

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton(
                "◀️ قبلی", callback_data=f"adm:usr:cfgp:{target_id}:{page - 1}"
            ))
        nav_row.append(types.InlineKeyboardButton(
            f"صفحه {page + 1}/{total_pages}", callback_data="noop"
        ))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton(
                "بعدی ▶️", callback_data=f"adm:usr:cfgp:{target_id}:{page + 1}"
            ))
        kb.row(*nav_row)

    kb.add(types.InlineKeyboardButton(
        "بازگشت", callback_data=f"adm:usr:v:{target_id}",
        icon_custom_emoji_id="5253997076169115797"
    ))
    if hasattr(call, "message"):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
    send_or_edit(call, f"📦 کانفیگ‌های کاربر ({total} عدد):", kb)


@bot.callback_query_handler(func=lambda c: True)
def on_callback(call):
    uid  = call.from_user.id
    data = call.data or ""

    # Fast-path: purely informational callbacks bypass the lock entirely.
    if data in _PASSTHROUGH_CALLBACKS:
        if data == "check_channel":
            ensure_user(call.from_user)
            _invalidate_channel_cache(uid)   # force re-check after user joined
            if check_channel_membership(uid):
                bot.answer_callback_query(call.id, "✅ عضویت تأیید شد!")
                # If this user came via a referral link, trigger their referrer's start reward
                try:
                    from ..ui.notifications import try_give_referral_start_reward_for_channel_join
                    try_give_referral_start_reward_for_channel_join(uid)
                except Exception:
                    pass
                # Phone gate check
                from ..handlers.start import _phone_required_for_user, _send_phone_request
                if not is_admin(uid) and _phone_required_for_user(uid):
                    _send_phone_request(call.message.chat.id, uid)
                else:
                    # Send menu directly to guarantee delivery regardless of edit state
                    try:
                        show_main_menu(call)
                    except Exception:
                        try:
                            show_main_menu(call.message)
                        except Exception:
                            pass
            else:
                bot.answer_callback_query(call.id, "❌ هنوز عضو کانال نشده‌اید.", show_alert=True)
        else:
            try:
                bot.answer_callback_query(call.id)
            except Exception:
                pass
        return

    # Acquire per-user lock (non-blocking).
    # If another callback for this user is already being processed, drop this one.
    lock = _get_user_cb_lock(uid)
    if not lock.acquire(blocking=False):
        try:
            bot.answer_callback_query(call.id, "⏳ لطفاً صبر کنید...", show_alert=False)
        except Exception:
            pass
        return

    try:
        ensure_user(call.from_user)

        # ── Bot status gate (off / update) ───────────────────────────────────
        # Applies to ALL callbacks from non-admins, including old inline menus.
        # Admin callbacks pass through unconditionally.
        if not is_admin(uid):
            _bot_status = setting_get("bot_status", "on")
            if _bot_status == "off":
                bot.answer_callback_query(
                    call.id,
                    "🔴 ربات در حال حاضر خاموش است.",
                    show_alert=True
                )
                return
            if _bot_status == "update":
                bot.answer_callback_query(
                    call.id,
                    "🔄 ربات در حال بروزرسانی است.\n\nلطفاً کمی صبر کنید و دوباره امتحان کنید. 🙏",
                    show_alert=True
                )
                return

        # ── Stale callback guard ─────────────────────────────────────────────
        # If the inline button is from a message older than 48 h and it's a
        # payment/purchase action, warn the user and abort to avoid double-pay.
        _STALE_SENSITIVE = (
            "pay:", "rpay:", "renew:", "buy:p:", "wallet:charge:",
            "pay:approve:", "pay:reject:",
        )
        try:
            msg_date = getattr(call.message, "date", 0) or 0
            import time as _time
            if msg_date and (_time.time() - msg_date) > 172800:  # 48 hours
                if any(data.startswith(p) for p in _STALE_SENSITIVE):
                    bot.answer_callback_query(
                        call.id,
                        "⏰ این دکمه منقضی شده است. لطفاً دوباره از منو اقدام کنید.",
                        show_alert=True
                    )
                    return
        except Exception:
            pass

        if not check_channel_membership(uid):
            bot.answer_callback_query(call.id)
            channel_lock_message(call)
            return

        # Phone gate — enforce for all callbacks except phone-collection itself
        if not is_admin(uid) and data not in ("check_channel",):
            from ..handlers.start import _phone_required_for_user, _send_phone_request
            if _phone_required_for_user(uid):
                bot.answer_callback_query(call.id)
                _send_phone_request(call.message.chat.id, uid)
                return

        # ── Layer 9: License enforcement in callback dispatcher ───────────────
        # Allow license-related callbacks and admin panel always
        _LICENSE_PASSTHROUGH = {
            "nav:main", "admin:panel", "license:activate", "license:status",
            "license:recheck", "license:limited_info", "support",
            "license:edit_key", "license:edit_url",
        }
        from ..license_manager import is_limited_mode as _is_limited
        if _is_limited() and not is_admin(uid) and data not in _LICENSE_PASSTHROUGH:
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                "🚫 ربات در حال حاضر غیرفعال است.",
            )
            return

        # Restricted user check (admins bypass)
        if not is_admin(uid):
            _u = get_user(uid)
            if _u:
                _u = check_and_release_restriction(_u)
            if _u and _u["status"] == "restricted":
                import time as _t
                _until = _u.get("restricted_until", 0)
                if _until and _until > 0:
                    import datetime as _dt
                    _exp = _dt.datetime.fromtimestamp(_until, tz=_dt.timezone.utc).astimezone(
                        _dt.timezone(_dt.timedelta(hours=3, minutes=30)))
                    _dur_txt = f"تا {_exp.strftime('%Y/%m/%d — %H:%M')} نمی‌توانید از ربات استفاده کنید."
                else:
                    _dur_txt = "برای همیشه نمی‌توانید از ربات استفاده کنید."
                bot.answer_callback_query(
                    call.id,
                    f"🚫 دسترسی محدود شده — {_dur_txt}",
                    show_alert=True
                )
                return

        try:
            _dispatch_callback(call, uid, data)
        except Exception as e:
            import traceback as _tb
            err_detail = _tb.format_exc()
            print("CALLBACK_ERROR:", e)
            print(err_detail)
            try:
                short = str(e)[:120]
                bot.answer_callback_query(call.id, f"⚠️ خطا: {short}", show_alert=True)
            except Exception:
                try:
                    bot.answer_callback_query(call.id, "خطایی رخ داد.", show_alert=True)
                except Exception:
                    pass
    finally:
        lock.release()


def _swapwallet_error_inline(call, err_msg):
    """نمایش خطای SwapWallet به صورت inline با راهنمای تنظیمات."""
    if "APPLICATION_NOT_FOUND" in err_msg or "Application not found" in err_msg or "کسب\u200cوکار" in err_msg:
        msg = (
            "❌ <b>خطا: کسب\u200cوکار یافت نشد</b>\n\n"
            "درگاه SwapWallet نیاز به یک <b>Application (کسب\u200cوکار)</b> جداگانه دارد.\n"
            "اکانت شخصی برای دریافت پرداخت کار نمی\u200cکند.\n\n"
            "<b>مراحل رفع:</b>\n"
            "1\ufe0f\u20e3 ربات @SwapWalletBot را باز کنید\n"
            "2\ufe0f\u20e3 به بخش <b>کسب\u200cوکار</b> بروید\n"
            "3\ufe0f\u20e3 یک کسب\u200cوکار جدید بسازید\n"
            "4\ufe0f\u20e3 <b>نام کاربری آن کسب\u200cوکار</b> را در پنل ادمین ← درگاه\u200cها وارد کنید"
        )
    else:
        msg = f"❌ <b>خطا در اتصال به SwapWallet</b>\n\n<code>{err_msg[:300]}</code>"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    try:
        bot.edit_message_text(
            msg,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        try:
            bot.send_message(call.message.chat.id, msg, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


# ── TetraPay auto-verify thread ───────────────────────────────────────────────
def _tetrapay_auto_verify(payment_id, authority, uid, chat_id, message_id, kind,
                          package_id=None):
    """Background thread: polls TetraPay every 15s for up to 60 minutes."""
    max_tries = 240  # 240 × 15s = 60 minutes
    for attempt in range(max_tries):
        time.sleep(15)
        payment = get_payment(payment_id)
        if not payment or payment["status"] != "pending":
            return  # Already processed by another path
        success, result = verify_tetrapay_order(authority)
        print(f"[TetraPay auto-verify] attempt={attempt+1} payment={payment_id} ok={success} result={result!r}")
        if not success:
            continue
        # Payment confirmed — process it
        try:
            if kind == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one thread wins
                    return
                update_balance(uid, payment["amount"])
                state_clear(uid)
                try:
                    apply_gateway_bonus_if_needed(uid, "tetrapay", payment["amount"])
                except Exception:
                    pass
                try:
                    bot.edit_message_text(
                        f"✅ پرداخت شما تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(payment['amount'])} تومان",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        f"✅ پرداخت شما تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(payment['amount'])} تومان",
                        parse_mode="HTML", reply_markup=back_button("main"))

            elif kind == "config_purchase":
                pkg_row = get_package(package_id)
                _qty_tp_auto = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    return
                state_clear(uid)
                try:
                    bot.edit_message_text(
                        "✅ پرداخت شما تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        "✅ پرداخت شما تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                        parse_mode="HTML", reply_markup=back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    chat_id, uid, package_id,
                    payment["amount"], "tetrapay", _qty_tp_auto, payment_id
                )
                try:
                    apply_gateway_bonus_if_needed(uid, "tetrapay", payment["amount"])
                except Exception:
                    pass
                _send_bulk_delivery_result(chat_id, uid, pkg_row,
                                           purchase_ids, pending_ids, "TetraPay")

            elif kind == "renewal":
                pkg_row = get_package(package_id)
                cfg_id = payment["config_id"]
                with get_conn() as conn:
                    row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (cfg_id,)).fetchone()
                pid = row["purchase_id"] if row else 0
                item = get_purchase(pid) if pid else None
                if not complete_payment(payment_id):
                    return
                state_clear(uid)
                msg_text = (
                    "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                    "🔄 درخواست تمدید سرویس شما با موفقیت ثبت و برای پشتیبانی ارسال شد.\n"
                    "⏳ لطفاً کمی صبر کنید، پس از انجام تمدید به شما اطلاع داده خواهد شد.\n\n"
                    "🙏 از صبر و شکیبایی شما متشکریم."
                )
                try:
                    bot.edit_message_text(msg_text, chat_id, message_id, parse_mode="HTML",
                                          reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid, msg_text, parse_mode="HTML", reply_markup=back_button("main"))
                if item:
                    admin_renewal_notify(uid, item, pkg_row, payment["amount"], "TetraPay")
                try:
                    apply_gateway_bonus_if_needed(uid, "tetrapay", payment["amount"])
                except Exception:
                    pass

            elif kind == "pnlcfg_renewal":
                cfg_id_tp   = payment["config_id"]
                pkg_id_tp   = payment["package_id"]
                if not complete_payment(payment_id):
                    return
                state_clear(uid)
                ok_tp, err_tp = _execute_pnlcfg_renewal(cfg_id_tp, pkg_id_tp, chat_id=uid, uid=uid)
                if ok_tp:
                    try:
                        from ..admin.renderers import _show_panel_config_detail as _spcd_tp
                        class _FakeCall_tp:
                            class message:
                                chat_id = chat_id
                                message_id = message_id
                                class chat:
                                    id = chat_id
                                    type = "private"
                        try:
                            bot.edit_message_text("✅ پرداخت تأیید و سرویس تمدید شد.", chat_id, message_id,
                                                  parse_mode="HTML", reply_markup=back_button("my_configs"))
                        except Exception:
                            bot.send_message(uid, "✅ پرداخت تأیید و سرویس تمدید شد.",
                                             parse_mode="HTML", reply_markup=back_button("my_configs"))
                    except Exception:
                        pass
                else:
                    try:
                        bot.send_message(uid,
                            "✅ پرداخت تأیید شد اما تمدید سرویس با خطا مواجه شد.\nلطفاً با پشتیبانی ارتباط بگیرید.",
                            parse_mode="HTML", reply_markup=back_button("my_configs"))
                    except Exception:
                        pass

        except Exception as e:
            print("TETRAPAY_AUTO_VERIFY_ERROR:", e)
        return  # Processed (success or error)

    # Timeout — not verified after 60 minutes
    payment = get_payment(payment_id)
    if payment and payment["status"] == "pending":
        state_clear(uid)
        if kind == "pnlcfg_renewal":
            verify_cb = f"mypnlcfgrpay:tetrapay:verify:{payment_id}"
        elif kind == "renewal":
            verify_cb = f"rpay:tetrapay:verify:{payment_id}"
        else:
            verify_cb = f"pay:tetrapay:verify:{payment_id}"
        timeout_msg = (
            "⏰ <b>بررسی خودکار پرداخت پایان یافت</b>\n\n"
            "وقتی پرداخت‌تون تو ربات تتراپی تایید شد، دکمه <b>بررسی پرداخت</b> زیر را بزنید "
            "تا پرداخت تأیید شده و ادامه عملیات انجام شود.\n\n"
            "اگر مبلغ از حساب شما کسر شده و پرداخت تأیید نشده، لطفاً با پشتیبانی تماس بگیرید."
        )
        timeout_kb = types.InlineKeyboardMarkup()
        timeout_kb.add(types.InlineKeyboardButton("🔍 بررسی پرداخت", callback_data=verify_cb))
        try:
            bot.edit_message_text(timeout_msg, chat_id, message_id, parse_mode="HTML",
                                  reply_markup=timeout_kb)
        except Exception:
            try:
                bot.send_message(uid, timeout_msg, parse_mode="HTML", reply_markup=timeout_kb)
            except Exception:
                pass


def _start_tetrapay_auto_verify(payment_id, authority, uid, chat_id, message_id,
                                kind, package_id=None):
    t = threading.Thread(
        target=_tetrapay_auto_verify,
        args=(payment_id, authority, uid, chat_id, message_id, kind),
        kwargs={"package_id": package_id},
        daemon=True,
    )
    t.start()


# ── TronPays Rial auto-verify thread ──────────────────────────────────────────
def _tronpays_rial_auto_verify(payment_id, invoice_id, uid, chat_id, message_id, kind,
                               package_id=None):
    """Background thread: polls TronPays every 15s for up to 60 minutes."""
    max_tries = 240  # 240 × 15s = 60 minutes
    for attempt in range(max_tries):
        time.sleep(15)
        payment = get_payment(payment_id)
        if not payment or payment["status"] != "pending":
            return
        ok, status = check_tronpays_rial_invoice(invoice_id)
        print(f"[TronPays auto-verify] attempt={attempt+1} payment={payment_id} ok={ok} status={status!r}")
        if not ok or not is_tronpays_paid(status):
            continue
        try:
            if kind == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one thread wins
                    return
                update_balance(uid, payment["amount"])
                state_clear(uid)
                try:
                    apply_gateway_bonus_if_needed(uid, "tronpays_rial", payment["amount"])
                except Exception:
                    pass
                try:
                    bot.edit_message_text(
                        f"✅ پرداخت شما تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(payment['amount'])} تومان",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        f"✅ پرداخت شما تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(payment['amount'])} تومان",
                        parse_mode="HTML", reply_markup=back_button("main"))

            elif kind == "config_purchase":
                pkg_row = get_package(package_id)
                _qty_trp_auto = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    return
                state_clear(uid)
                try:
                    bot.edit_message_text(
                        "✅ پرداخت شما تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        "✅ پرداخت شما تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                        parse_mode="HTML", reply_markup=back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    chat_id, uid, package_id,
                    payment["amount"], "tronpays_rial", _qty_trp_auto, payment_id
                )
                try:
                    apply_gateway_bonus_if_needed(uid, "tronpays_rial", payment["amount"])
                except Exception:
                    pass
                _send_bulk_delivery_result(chat_id, uid, pkg_row,
                                           purchase_ids, pending_ids, "TronPays")

            elif kind == "renewal":
                pkg_row = get_package(package_id)
                cfg_id = payment["config_id"]
                with get_conn() as conn:
                    row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (cfg_id,)).fetchone()
                pid = row["purchase_id"] if row else 0
                item = get_purchase(pid) if pid else None
                if not complete_payment(payment_id):
                    return
                state_clear(uid)
                msg_text = (
                    "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                    "🔄 درخواست تمدید سرویس شما با موفقیت ثبت و برای پشتیبانی ارسال شد.\n"
                    "⏳ لطفاً کمی صبر کنید، پس از انجام تمدید به شما اطلاع داده خواهد شد.\n\n"
                    "🙏 از صبر و شکیبایی شما متشکریم."
                )
                try:
                    bot.edit_message_text(msg_text, chat_id, message_id, parse_mode="HTML",
                                          reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid, msg_text, parse_mode="HTML", reply_markup=back_button("main"))
                if item:
                    admin_renewal_notify(uid, item, pkg_row, payment["amount"], "TronPays")
                try:
                    apply_gateway_bonus_if_needed(uid, "tronpays_rial", payment["amount"])
                except Exception:
                    pass

            elif kind == "pnlcfg_renewal":
                cfg_id_trp  = payment["config_id"]
                pkg_id_trp  = payment["package_id"]
                if not complete_payment(payment_id):
                    return
                state_clear(uid)
                ok_trp, err_trp = _execute_pnlcfg_renewal(cfg_id_trp, pkg_id_trp, chat_id=uid, uid=uid)
                if ok_trp:
                    try:
                        bot.send_message(uid, "✅ پرداخت تأیید و سرویس تمدید شد.",
                                         parse_mode="HTML", reply_markup=back_button("my_configs"))
                    except Exception:
                        pass
                else:
                    try:
                        bot.send_message(uid,
                            "✅ پرداخت تأیید شد اما تمدید سرویس با خطا مواجه شد.\nلطفاً با پشتیبانی ارتباط بگیرید.",
                            parse_mode="HTML", reply_markup=back_button("my_configs"))
                    except Exception:
                        pass

        except Exception as e:
            print("TRONPAYS_RIAL_AUTO_VERIFY_ERROR:", e)
        return

    # Timeout
    payment = get_payment(payment_id)
    if payment and payment["status"] == "pending":
        state_clear(uid)
        if kind == "pnlcfg_renewal":
            verify_cb = f"mypnlcfgrpay:tronpays_rial:verify:{payment_id}"
        elif kind == "renewal":
            verify_cb = f"rpay:tronpays_rial:verify:{payment_id}"
        else:
            verify_cb = f"pay:tronpays_rial:verify:{payment_id}"
        timeout_msg = (
            "⏰ <b>بررسی خودکار پرداخت پایان یافت</b>\n\n"
            "وقتی پرداخت‌تون تو TronPays تایید شد، دکمه <b>بررسی پرداخت</b> زیر را بزنید "
            "تا پرداخت تأیید شده و ادامه عملیات انجام شود.\n\n"
            "اگر مبلغ از حساب شما کسر شده و پرداخت تأیید نشده، لطفاً با پشتیبانی تماس بگیرید."
        )
        timeout_kb = types.InlineKeyboardMarkup()
        timeout_kb.add(types.InlineKeyboardButton("🔍 بررسی پرداخت", callback_data=verify_cb))
        try:
            bot.edit_message_text(timeout_msg, chat_id, message_id, parse_mode="HTML",
                                  reply_markup=timeout_kb)
        except Exception:
            try:
                bot.send_message(uid, timeout_msg, parse_mode="HTML", reply_markup=timeout_kb)
            except Exception:
                pass


def _start_tronpays_rial_auto_verify(payment_id, invoice_id, uid, chat_id, message_id,
                                     kind, package_id=None):
    t = threading.Thread(
        target=_tronpays_rial_auto_verify,
        args=(payment_id, invoice_id, uid, chat_id, message_id, kind),
        kwargs={"package_id": package_id},
        daemon=True,
    )
    t.start()


def _dispatch_callback(call, uid, data):
    # ── License callbacks ────────────────────────────────────────────────────
    if data.startswith("license:"):
        from ..license_manager import (
            is_limited_mode, get_license_status_text, check_license, _invalidate_cache,
            activate_license, get_or_create_machine_id,
            API_KEY_PROMPT_TEXT, API_URL_PROMPT_TEXT, ACTIVATION_SUCCESS_TEXT, ACTIVATION_FAIL_TEXT,
        )
        from ..config import ADMIN_IDS as _AIDS

        if data == "license:activate":
            if uid not in _AIDS and not is_admin(uid):
                bot.answer_callback_query(call.id, "⛔ دسترسی فقط برای مالک/ادمین.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            state_set(uid, "license:waiting_api_key")
            bot.send_message(call.message.chat.id, API_KEY_PROMPT_TEXT, parse_mode="HTML")
            return

        if data in ("license:status", "license:recheck"):
            if uid not in _AIDS and not is_admin(uid):
                bot.answer_callback_query(call.id, "⛔ دسترسی فقط برای مالک/ادمین.", show_alert=True)
                return
            if data == "license:recheck":
                bot.answer_callback_query(call.id, "⏳ در حال بررسی...")
                _invalidate_cache()
                check_license(force=True)
            else:
                bot.answer_callback_query(call.id)
            text = get_license_status_text()
            kb = types.InlineKeyboardMarkup()
            if is_limited_mode():
                kb.add(types.InlineKeyboardButton("🔐 فعال‌سازی لایسنس", callback_data="license:activate"))
            kb.add(types.InlineKeyboardButton("🔄 بررسی مجدد", callback_data="license:recheck"))
            kb.row(
                types.InlineKeyboardButton("ویرایش 🔑 API Key", callback_data="license:edit_key"),
                types.InlineKeyboardButton("ویرایش 🌐 API URL", callback_data="license:edit_url"),
            )
            kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin:panel"))
            try:
                bot.edit_message_text(
                    text, call.message.chat.id, call.message.message_id,
                    parse_mode="HTML", reply_markup=kb,
                )
            except Exception:
                bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)
            return

        if data == "license:edit_key":
            if uid not in _AIDS and not is_admin(uid):
                bot.answer_callback_query(call.id, "⛔ دسترسی فقط برای مالک/ادمین.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            state_set(uid, "license:edit_api_key")
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("❌ لغو", callback_data="license:status"))
            bot.send_message(
                call.message.chat.id,
                "🔑 <b>ویرایش API Key</b>\n\n"
                "کلید API جدید را وارد کنید:",
                parse_mode="HTML", reply_markup=kb,
            )
            return

        if data == "license:edit_url":
            if uid not in _AIDS and not is_admin(uid):
                bot.answer_callback_query(call.id, "⛔ دسترسی فقط برای مالک/ادمین.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            state_set(uid, "license:edit_api_url")
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("❌ لغو", callback_data="license:status"))
            bot.send_message(
                call.message.chat.id,
                "🌐 <b>ویرایش API URL</b>\n\n"
                "آدرس URL جدید سرور لایسنس را وارد کنید:\n"
                "<i>مثال: https://license.example.com</i>",
                parse_mode="HTML", reply_markup=kb,
            )
            return

        if data == "license:limited_info":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                "🔒 <b>ربات در حالت محدود اجرا می‌شود.</b>\n\n"
                "برای فعال‌سازی کامل ربات، با مالک تماس بگیرید.\n"
                "یا برای خرید اشتراک به @Emad_Habibnia پیام دهید.",
                parse_mode="HTML",
            )
            return

        bot.answer_callback_query(call.id)
        return

    # Navigation
    if data.startswith("nav:"):
        target = data[4:]
        state_clear(uid)
        bot.answer_callback_query(call.id)
        if target == "main":
            show_main_menu(call)
        else:
            _fake_call(call, target)
        return

    if data == "profile":
        bot.answer_callback_query(call.id)
        show_profile(call, uid)
        return

    if data == "support":
        bot.answer_callback_query(call.id)
        show_support(call)
        return

    if data == "referral:menu":
        bot.answer_callback_query(call.id)
        show_referral_menu(call, uid)
        return

    if data == "referral:claim_reward":
        rewards = get_unclaimed_rewards(uid)
        if not rewards:
            bot.answer_callback_query(call.id, "هیچ پاداش دریافت‌نشده‌ای وجود ندارد.", show_alert=True)
            return
        delivered_wallet = 0
        delivered_config = 0
        failed_config    = 0
        for row in rewards:
            if row["reward_type"] == "wallet":
                amt = int(row["amount"] or 0)
                if amt > 0:
                    update_balance(uid, amt)
                    delivered_wallet += amt
                mark_reward_claimed_by_id(row["id"])
            else:
                pkg_id = row["package_id"]
                if not pkg_id:
                    failed_config += 1
                    continue  # leave unclaimed — admin must fix package config
                available = get_available_configs_for_package(int(pkg_id))
                if not available:
                    failed_config += 1
                    continue  # leave unclaimed — no stock; user can retry later
                cfg = available[0]
                try:
                    purchase_id = assign_config_to_user(
                        cfg["id"], uid, int(pkg_id), 0, "referral_gift", is_test=0
                    )
                    mark_reward_claimed_by_id(row["id"])
                    delivered_config += 1
                    try:
                        deliver_purchase_message(uid, purchase_id)
                    except Exception:
                        pass
                except Exception:
                    failed_config += 1
        # Build result message
        parts_msg = []
        if delivered_wallet:
            parts_msg.append(
                f"💰 مبلغ <b>{fmt_price(delivered_wallet)}</b> تومان با موفقیت به کیف‌پول شما اضافه شد."
            )
        if delivered_config:
            parts_msg.append(
                f"🎁 <b>{delivered_config}</b> کانفیگ رایگان با موفقیت به سرویس‌های شما اضافه شد."
            )
        if failed_config:
            parts_msg.append(
                f"⚠️ <b>{failed_config}</b> پاداش کانفیگ به دلیل عدم موجودی تحویل داده نشد.\n"
                "لطفاً بعداً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
            )
        if parts_msg:
            bot.answer_callback_query(call.id, "✅ پاداش دریافت شد!", show_alert=False)
            summary = "\n\n".join(parts_msg)
            try:
                bot.send_message(
                    uid,
                    f"🎁 <b>پاداش زیرمجموعه‌گیری</b>\n\n{summary}",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            bot.answer_callback_query(call.id, "پاداشی برای دریافت وجود نداشت.", show_alert=True)
        show_referral_menu(call, uid)
        return

    if data == "referral:get_banner":
        banner_photo = setting_get("referral_banner_photo", "").strip()
        if not banner_photo:
            bot.answer_callback_query(call.id, "بنری تنظیم نشده است.", show_alert=True)
            return
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
        custom_banner = setting_get("referral_banner_text", "").strip()
        from ..config import BRAND_TITLE
        if custom_banner:
            caption = f"{custom_banner}\n\n{ref_link}"
        else:
            caption = (
                f"🔥 می‌خوای با سرعت بالا و پایداری عالی به اینترنت آزاد وصل بشی؟\n\n"
                f"من از {BRAND_TITLE} سرویس VPN خریدم و کاملاً راضیم! 😍\n\n"
                f"✅ سرعت فوق‌العاده\n"
                f"✅ پایداری بالا\n"
                f"✅ پشتیبانی ۲۴ ساعته\n\n"
                f"تو هم از لینک من وارد شو و سرویست رو بخر 👇\n{ref_link}"
            )
        bot.answer_callback_query(call.id)
        bot.send_photo(call.message.chat.id, banner_photo, caption=caption, parse_mode="HTML")
        return

    # ── Discount code flow ───────────────────────────────────────────────────
    if data == "disc:yes":
        sn = state_name(uid)
        sd = state_data(uid)
        if sn not in {"buy_select_method", "renew_select_method"}:
            bot.answer_callback_query(call.id, "درخواستی برای اعمال تخفیف پیدا نشد.", show_alert=True)
            return
        original_amount = sd.get("original_amount", sd.get("amount", 0))
        new_sd = dict(sd)
        new_sd["prev_state"] = sn
        new_sd["original_amount"] = original_amount
        state_set(uid, "await_discount_code", **new_sd)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت (بدون تخفیف)", callback_data="disc:no"))
        send_or_edit(call,
            "🎟 <b>کد تخفیف</b>\n\n"
            "✍️ لطفاً کد تخفیف خود را تایپ کرده و ارسال کنید:\n\n"
            "💡 <i>کدها معمولاً ترکیبی از حروف انگلیسی و اعداد هستند.</i>",
            kb)
        return

    if data == "disc:no":
        sn = state_name(uid)
        sd = state_data(uid)
        if sn == "await_discount_code":
            prev_state = sd.get("prev_state", "buy_select_method")
            new_data = {k: v for k, v in sd.items() if k != "prev_state"}
            state_set(uid, prev_state, **new_data)
            sd = new_data
            sn = prev_state
        bot.answer_callback_query(call.id)
        if sn == "buy_select_method":
            package_id = int(sd.get("package_id", 0))
            package_row = get_package(package_id)
            if package_row:
                price = sd.get("amount") or get_effective_price(uid, package_row)
                _show_purchase_gateways(call, uid, package_id, price, package_row)
            return
        if sn == "renew_select_method":
            purchase_id = int(sd.get("purchase_id", 0))
            package_id = int(sd.get("package_id", 0))
            item = get_purchase(purchase_id)
            package_row = get_package(package_id)
            if item and package_row:
                price = sd.get("amount") or get_effective_price(uid, package_row)
                _show_renewal_gateways(call, uid, purchase_id, package_id, price, package_row, item)
            return
        bot.answer_callback_query(call.id, "درخواستی برای ادامه پیدا نشد.", show_alert=True)
        return

    # ── Agency request ────────────────────────────────────────────────────────
    if data == "agency:request":
        user = get_user(uid)
        if user and user["is_agent"]:
            bot.answer_callback_query(call.id, "شما در حال حاضر نماینده هستید.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📤 ارسال درخواست (بدون متن)", callback_data="agency:send_empty"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        state_set(uid, "agency_request_text")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🤝 <b>درخواست نمایندگی</b>\n\n"
            "لطفاً متن درخواست خود را ارسال کنید. موارد زیر را در متن ذکر کنید:\n\n"
            "📊 میزان فروش شما در روز یا هفته\n"
            "📢 کانال یا فروشگاهی که دارید (آدرس کانال تلگرام)\n"
            "🎧 آیدی پشتیبانی مجموعه شما\n"
            "📝 هر توضیح دیگری که لازم می‌دانید\n\n"
            "اگر نمی‌خواهید متنی بنویسید، دکمه زیر را بزنید:", kb)
        return

    if data == "agency:send_empty":
        state_clear(uid)
        user = get_user(uid)
        if user and user["is_agent"]:
            bot.answer_callback_query(call.id, "شما در حال حاضر نماینده هستید.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, "✅ درخواست نمایندگی شما ارسال شد.\n⏳ لطفاً منتظر بررسی ادمین باشید.", back_button("main"))
        # Notify admins
        text = (
            f"🤝 <b>درخواست نمایندگی جدید</b>\n\n"
            f"👤 نام: {esc(user['full_name'])}\n"
            f"🆔 نام کاربری: {esc(display_username(user['username']))}\n"
            f"🔢 آیدی: <code>{user['user_id']}</code>\n\n"
            f"📝 متن درخواست: <i>بدون متن</i>"
        )
        admin_kb = types.InlineKeyboardMarkup()
        admin_kb.row(
            types.InlineKeyboardButton("✅ تأیید", callback_data=f"agency:approve_now:{uid}"),
            types.InlineKeyboardButton("❌ رد", callback_data=f"agency:reject_now:{uid}"),
        )
        for admin_id in ADMIN_IDS:
            try:
                msg = bot.send_message(admin_id, text, reply_markup=admin_kb)
                save_agency_request_message(uid, admin_id, msg.message_id)
            except Exception:
                pass
        for row in get_all_admin_users():
            sub_id = row["user_id"]
            if sub_id in ADMIN_IDS:
                continue
            import json as _json
            perms = _json.loads(row["permissions"] or "{}")
            if not (perms.get("full") or perms.get("agency")):
                continue
            try:
                msg = bot.send_message(sub_id, text, reply_markup=admin_kb)
                save_agency_request_message(uid, sub_id, msg.message_id)
            except Exception:
                pass
        if setting_get("notif_own_agency_request", "1") == "1" or True:
            grp_msg = send_to_topic("agency_request", text, reply_markup=admin_kb)
            if grp_msg:
                save_agency_request_message(uid, grp_msg.chat.id, grp_msg.message_id)
        return

    if data.startswith("agency:approve:"):
        if not is_admin(uid) or not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_set(uid, "agency_approve_note", target_user_id=target_uid)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⏭ بدون پیام", callback_data=f"agency:approve_now:{target_uid}"))
        bot.send_message(call.message.chat.id,
            f"✅ در حال تأیید نمایندگی کاربر <code>{target_uid}</code>\n\n"
            "اگر می‌خواهید پیامی برای کاربر ارسال کنید، متن را بنویسید.\n"
            "در غیر این صورت دکمه زیر را بزنید:", reply_markup=kb)
        return

    if data.startswith("agency:approve_now:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_clear(uid)
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_agent=1 WHERE user_id=?", (target_uid,))
        bot.answer_callback_query(call.id, "✅ نمایندگی تأیید شد.")
        # Remove buttons from all tracked messages
        for row in get_agency_request_messages(target_uid):
            try:
                bot.edit_message_reply_markup(row["chat_id"], row["message_id"], reply_markup=None)
            except Exception:
                pass
        delete_agency_request_messages(target_uid)
        # Notify user
        try:
            bot.send_message(target_uid,
                "🎉 <b>درخواست نمایندگی شما تأیید شد!</b>\n\nاکنون شما نماینده هستید.",
                parse_mode="HTML")
        except Exception:
            pass
        # Log to agency_log topic
        user_row = get_user(target_uid)
        send_to_topic("agency_log",
            f"✅ <b>نمایندگی تأیید شد</b>\n\n"
            f"👤 نام: {esc(user_row['full_name'] if user_row else str(target_uid))}\n"
            f"🆔 نام کاربری: {esc(user_row['username'] or 'ندارد' if user_row else '-')}\n"
            f"🆔 آیدی: <code>{target_uid}</code>\n"
            f"📊 تخفیف پیش‌فرض: <b>{default_pct}%</b>\n"
            f"تأییدکننده: <code>{uid}</code>"
        )
        # If called from admin DM, show user detail panel
        if call.message.chat.type == "private":
            _show_admin_user_detail(call, target_uid)
        else:
            try:
                bot.send_message(call.message.chat.id,
                    f"✅ نمایندگی کاربر <code>{target_uid}</code> تأیید شد.",
                    message_thread_id=call.message.message_thread_id,
                    parse_mode="HTML")
            except Exception:
                pass
        return

    if data.startswith("agency:reject_now:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        bot.answer_callback_query(call.id, "❌ رد شد.")
        # Remove buttons from all tracked messages
        for row in get_agency_request_messages(target_uid):
            try:
                bot.edit_message_reply_markup(row["chat_id"], row["message_id"], reply_markup=None)
            except Exception:
                pass
        delete_agency_request_messages(target_uid)
        # Notify user
        try:
            bot.send_message(target_uid,
                "❌ <b>درخواست نمایندگی شما رد شد.</b>",
                parse_mode="HTML")
        except Exception:
            pass
        # Log to agency_log topic
        user_row = get_user(target_uid)
        send_to_topic("agency_log",
            f"❌ <b>نمایندگی رد شد</b>\n\n"
            f"👤 نام: {esc(user_row['full_name'] if user_row else str(target_uid))}\n"
            f"🆔 آیدی: <code>{target_uid}</code>\n"
            f"ردکننده: <code>{uid}</code>"
        )
        return

    if data.startswith("agency:reject:"):
        if not is_admin(uid) or not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_set(uid, "agency_reject_reason", target_user_id=target_uid)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(call.message.chat.id,
            f"❌ در حال رد درخواست نمایندگی کاربر <code>{target_uid}</code>\n\n"
            "لطفاً دلیل رد را بنویسید:")
        return

    if data == "my_configs":
        bot.answer_callback_query(call.id)
        show_my_configs(call, uid, page=0, search="")  # clear search on fresh entry
        return

    if data.startswith("my_configs:p:"):
        # Paginate: my_configs:p:{page}
        bot.answer_callback_query(call.id)
        try:
            page = int(data.split(":")[-1])
        except (ValueError, IndexError):
            page = 0
        show_my_configs(call, uid, page=page)
        return

    if data == "my_configs:search":
        # Enter search mode — ask user to type a query
        state_set(uid, "my_cfgs_search")
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("❌ لغو", callback_data="my_configs"))
        send_or_edit(call,
            "🔍 <b>جست‌وجو در کانفیگ‌ها</b>\n\n"
            "متن مورد نظر را ارسال کنید:\n"
            "• نام کانفیگ\n"
            "• متن کانفیگ (config link)\n"
            "• لینک ساب‌اسکرایب\n\n"
            "<i>برای لغو دکمه لغو را بزنید.</i>",
            kb)
        return

    if data == "my_configs:csearch":
        # Clear active search and return to page 0
        bot.answer_callback_query(call.id)
        show_my_configs(call, uid, page=0, search="")
        return

    if data.startswith("mycfg:"):
        purchase_id = int(data.split(":")[1])
        item = get_purchase(purchase_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        deliver_purchase_message(call.message.chat.id, purchase_id)
        return

    # ── Renewal flow ──────────────────────────────────────────────────────────
    if data.startswith("renew:") and not data.startswith("renew:p:") and not data.startswith("renew:confirm:"):
        if setting_get("manual_renewal_enabled", "1") != "1" and not is_admin(uid):
            bot.answer_callback_query(call.id, "⛔ تمدید در حال حاضر غیرفعال است.", show_alert=True)
            return
        purchase_id = int(data.split(":")[1])
        item = get_purchase(purchase_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        # Show packages of same type for renewal
        with get_conn() as conn:
            type_id = conn.execute("SELECT type_id FROM packages WHERE id=?", (item["package_id"],)).fetchone()["type_id"]
        user = get_user(uid)
        _is_agent = bool(user and user["is_agent"])
        packages = [p for p in get_packages(type_id=type_id) if p["price"] > 0 and _br_ok(p, _is_agent)]
        kb = types.InlineKeyboardMarkup()
        for p in packages:
            price = get_effective_price(uid, p)
            _sn = p['show_name'] if 'show_name' in p.keys() else 1
            _name_part = f"{p['name']} | " if _sn else ""
            title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)} ت"
            kb.add(types.InlineKeyboardButton(title, callback_data=f"renew:p:{purchase_id}:{p['id']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="my_configs", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        agent_note = "\n\n🤝 <i>این قیمت‌ها مخصوص همکاری شماست</i>" if user and user["is_agent"] else ""
        if not packages:
            send_or_edit(call, "📭 در حال حاضر پکیجی برای تمدید موجود نیست.", kb)
        else:
            send_or_edit(call, f"♻️ <b>تمدید سرویس</b>\n\nپکیج مورد نظر برای تمدید را انتخاب کنید:{agent_note}", kb)
        return

    if data.startswith("renew:p:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        price = get_effective_price(uid, package_row)
        state_set(uid, "renew_select_method",
                  package_id=package_id, amount=price, original_amount=price,
                  kind="renewal", purchase_id=purchase_id)
        bot.answer_callback_query(call.id)
        if setting_get("discount_codes_enabled", "0") == "1":
            if _show_discount_prompt(call, price):
                return
        _show_renewal_gateways(call, uid, purchase_id, package_id, price, package_row, item)
        return


    # ── Renewal payment handlers ──────────────────────────────────────────────
    if data.startswith("rpay:wallet:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        user = get_user(uid)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if user["balance"] < price:
            bot.answer_callback_query(call.id, "موجودی کیف پول کافی نیست.", show_alert=True)
            return
        update_balance(uid, -price)
        payment_id = create_payment("renewal", uid, package_id, price, "wallet",
                                     status="completed", config_id=item["config_id"])
        complete_payment(payment_id)
        bot.answer_callback_query(call.id, "پرداخت موفق بود.")
        send_or_edit(call,
            "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
            "🔄 درخواست تمدید سرویس شما با موفقیت ثبت و برای پشتیبانی ارسال شد.\n"
            "⏳ لطفاً کمی صبر کنید، پس از انجام تمدید به شما اطلاع داده خواهد شد.\n\n"
            "🙏 از صبر و شکیبایی شما متشکریم.",
            back_button("main"))
        admin_renewal_notify(uid, item, package_row, price, "کیف پول")
        state_clear(uid)
        return

    if data.startswith("rpay:card:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        _ci = pick_card_for_payment()
        if not _ci:
            bot.answer_callback_query(call.id, "اطلاعات پرداخت هنوز ثبت نشده است.", show_alert=True)
            return
        card, bank, owner = _ci["card_number"], _ci["bank_name"], _ci["holder_name"]
        price = _get_state_price(uid, package_row, "renew_select_method")
        price = apply_gateway_fee("card", price)
        if not is_gateway_in_range("card", price):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای این درگاه مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        payment_id = create_payment("renewal", uid, package_id, price, "card", status="pending",
                                     config_id=item["config_id"])
        # Generate random amount if enabled
        final_amount = None
        if setting_get("gw_card_random_amount", "0") == "1":
            final_amount = _generate_card_final_amount(price, payment_id)
            update_payment_final_amount(payment_id, final_amount)
        state_set(uid, "await_renewal_receipt", payment_id=payment_id, purchase_id=purchase_id)
        text, kb = _build_card_payment_page(card, bank, owner, price, final_amount)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("rpay:crypto:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("crypto", price):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای این درگاه مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        state_set(uid, "renew_crypto_select_coin", package_id=package_id, amount=price,
                  purchase_id=purchase_id, config_id=item["config_id"])
        bot.answer_callback_query(call.id)
        show_crypto_selection(call, amount=price)
        return

    if data.startswith("rpay:tetrapay:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
            return
        authority = payment["receipt_text"]
        success, result = verify_tetrapay_order(authority)
        if success:
            if not complete_payment(payment_id):
                bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                return
            package_row = get_package(payment["package_id"])
            config_id = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
            send_or_edit(call,
                "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                "🔄 درخواست تمدید سرویس شما با موفقیت ثبت و برای پشتیبانی ارسال شد.\n"
                "⏳ لطفاً کمی صبر کنید، پس از انجام تمدید به شما اطلاع داده خواهد شد.\n\n"
                "🙏 از صبر و شکیبایی شما متشکریم.",
                back_button("main"))
            if item:
                admin_renewal_notify(uid, item, package_row, payment["amount"], "TetraPay")
            try:
                apply_gateway_bonus_if_needed(uid, "tetrapay", payment["amount"])
            except Exception:
                pass
            state_clear(uid)
        else:
            _st = result.get("status", "") if isinstance(result, dict) else ""
            bot.answer_callback_query(call.id,
                f"❌ پرداخت هنوز تایید نشده.\nوضعیت TetraPay: {_st}\n\nلطفاً ابتدا پرداخت را در درگاه تتراپی انجام دهید.",
                show_alert=True)
        return

    if data.startswith("rpay:tetrapay:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("tetrapay", price):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه TetraPay مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        hash_id = f"rnw-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"تمدید {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"تمدید {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tetrapay_order(price, hash_id, order_label)
        if not success:
            bot.answer_callback_query(call.id, "خطا در ایجاد درخواست پرداخت آنلاین.", show_alert=True)
            return
        authority = result.get("Authority", "")
        pay_url_bot = result.get("payment_url_bot", "")
        pay_url_web = result.get("payment_url_web", "")
        payment_id = create_payment("renewal", uid, package_id, price, "tetrapay", status="pending",
                                     config_id=item["config_id"])
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (authority, payment_id))
        state_set(uid, "await_renewal_tetrapay_verify", payment_id=payment_id, authority=authority,
                  purchase_id=purchase_id)
        text = (
            "🏦 <b>پرداخت آنلاین (تمدید)</b>\n\n"
            f"💰 مبلغ: <b>{fmt_price(price)}</b> تومان\n\n"
            "لطفاً از یکی از لینک‌های زیر پرداخت را انجام دهید.\n\n"
            "⏳ <b>تا یک ساعت</b> اگر پرداخت‌تون تایید بشه به صورت خودکار عملیات انجام می‌شود.\n"
            "در غیر این صورت دکمه <b>بررسی پرداخت</b> را بزنید."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("💳 پرداخت در تلگرام", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("🌐 پرداخت در مرورگر", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("🔍 بررسی پرداخت", callback_data=f"rpay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "renewal", package_id=package_id)
        return

    if data.startswith("rpay:tetrapay:verify:"):
        # NOTE: this block is now unreachable (handled above) — kept as safety guard
        bot.answer_callback_query(call.id)
        return

    # ── TronPays Rial: renewal ────────────────────────────────────────────────
    if data.startswith("rpay:tronpays_rial:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        ok, status = check_tronpays_rial_invoice(invoice_id)
        if not ok:
            bot.answer_callback_query(call.id, "خطا در بررسی وضعیت فاکتور.", show_alert=True)
            return
        if is_tronpays_paid(status):
            if not complete_payment(payment_id):
                bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                return
            package_row = get_package(payment["package_id"])
            config_id   = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
            send_or_edit(call,
                "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                "🔄 درخواست تمدید سرویس شما با موفقیت ثبت و برای پشتیبانی ارسال شد.\n"
                "⏳ لطفاً کمی صبر کنید، پس از انجام تمدید به شما اطلاع داده خواهد شد.\n\n"
                "🙏 از صبر و شکیبایی شما متشکریم.",
                back_button("main"))
            if item:
                admin_renewal_notify(uid, item, package_row, payment["amount"], "TronPays")
            try:
                apply_gateway_bonus_if_needed(uid, "tronpays_rial", payment["amount"])
            except Exception:
                pass
            state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "❌ پرداخت هنوز تأیید نشده. لطفاً ابتدا پرداخت را انجام دهید.", show_alert=True)
        return

    if data.startswith("rpay:tronpays_rial:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("tronpays_rial", price):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه TronPay مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        hash_id = f"rnw-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"تمدید {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"تمدید {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tronpays_rial_invoice(price, hash_id, order_label)
        if not success:
            err_msg = result.get("error", "خطای ناشناخته") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"⚠️ <b>خطا در ایجاد درگاه TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "💡 مطمئن شوید کلید API صحیح وارد شده باشد.",
                back_button(f"renew:{purchase_id}"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"⚠️ <b>خطا در ایجاد فاکتور TronPays</b>\n\n"
                f"<code>پاسخ API: {esc(str(result)[:400])}</code>",
                back_button(f"renew:{purchase_id}"))
            return
        payment_id = create_payment("renewal", uid, package_id, price, "tronpays_rial", status="pending",
                                    config_id=item["config_id"])
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_renewal_tronpays_rial_verify", payment_id=payment_id,
                  invoice_id=invoice_id, purchase_id=purchase_id)
        text = (
            "💳 <b>پرداخت ریالی (TronPays) — تمدید</b>\n\n"
            f"💰 مبلغ: <b>{fmt_price(price)}</b> تومان\n\n"
            "از لینک زیر پرداخت را انجام دهید.\n\n"
            "⏳ <b>تا یک ساعت</b> پرداخت به صورت خودکار بررسی می‌شود.\n"
            "در غیر این صورت دکمه «بررسی پرداخت» را بزنید."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 پرداخت از درگاه TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("🔍 بررسی پرداخت", callback_data=f"rpay:tronpays_rial:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tronpays_rial_auto_verify(
            payment_id, invoice_id, uid,
            call.message.chat.id, call.message.message_id,
            "renewal", package_id=package_id)
        return

    # ── Admin: Confirm renewal ────────────────────────────────────────────────
    if data.startswith("renew:confirm:"):
        if not admin_has_perm(uid, "approve_renewal"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        config_id  = int(parts[2])
        target_uid = int(parts[3])
        # Un-expire config if it was expired
        with get_conn() as conn:
            conn.execute("UPDATE configs SET is_expired=0 WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "✅ تمدید تأیید شد.")
        # Update admin's message
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        try:
            bot.send_message(call.message.chat.id, "✅ تمدید تأیید و به کاربر اطلاع داده شد.")
        except Exception:
            pass
        # Notify user
        svc_name = ""
        try:
            with get_conn() as conn:
                cfg_row = conn.execute(
                    "SELECT c.service_name, c.package_id, p.name AS package_name, "
                    "p.volume_gb, p.duration_days, p.price, t.name AS type_name "
                    "FROM configs c "
                    "JOIN packages p ON p.id = c.package_id "
                    "JOIN config_types t ON t.id = p.type_id "
                    "WHERE c.id=?", (config_id,)
                ).fetchone()
            svc_name = urllib.parse.unquote(cfg_row["service_name"] or "") if cfg_row else ""
            bot.send_message(target_uid,
                f"🎉 <b>تمدید سرویس انجام شد!</b>\n\n"
                f"✅ سرویس <b>{esc(svc_name)}</b> شما با موفقیت تمدید شد.\n"
                "از اعتماد شما سپاسگزاریم. 🙏")
        except Exception:
            pass
        # Renewal log — find the payment method from the original admin message
        renewal_method = ""
        try:
            orig_text = call.message.text or call.message.caption or ""
            if "(" in orig_text and ")" in orig_text:
                renewal_method = orig_text.split("(", 1)[1].split(")", 1)[0]
        except Exception:
            pass
        try:
            user_row = get_user(target_uid)
            log_text = (
                f"🔄 | <b>تمدید تأیید شد</b>"
                f"{(' (' + esc(renewal_method) + ')') if renewal_method else ''}\n\n"
                f"▫️ آیدی کاربر: <code>{target_uid}</code>\n"
                f"👨‍💼 نام: {esc(user_row['full_name'] if user_row else '')}\n"
                f"⚡️ نام کاربری: {esc((user_row['username'] or 'ندارد') if user_row else 'ندارد')}\n"
                f"🔮 نام سرویس: {esc(svc_name or str(config_id))}\n"
            )
            if cfg_row:
                log_text += (
                    f"🚦 سرور: {esc(cfg_row['type_name'])}\n"
                    f"✏️ پکیج: {esc(cfg_row['package_name'])}\n"
                    f"🔋 حجم: {cfg_row['volume_gb']} گیگ\n"
                    f"⏰ مدت: {cfg_row['duration_days']} روز\n"
                    f"💰 قیمت: {fmt_price(cfg_row['price'])} تومان"
                )
            send_to_topic("renewal_log", log_text)
        except Exception:
            pass
        return

    # ── Buy flow ──────────────────────────────────────────────────────────────
    if data == "buy:start":
        # Check purchase rules
        if setting_get("purchase_rules_enabled", "0") == "1":
            accepted = setting_get(f"rules_accepted_{uid}", "0")
            if accepted != "1":
                rules_text = setting_get("purchase_rules_text", "")
                from ..ui.premium_emoji import render_premium_text_html as _rph
                rendered_rules = _rph(rules_text, escape_plain_parts=True)
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("✅ من قوانین را خواندم و پذیرفتم", callback_data="buy:accept_rules"))
                kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
                bot.answer_callback_query(call.id)
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception:
                    pass
                bot.send_message(
                    call.message.chat.id,
                    f"📜 <b>قوانین خرید</b>\n\n{rendered_rules}",
                    parse_mode="HTML",
                    reply_markup=kb,
                    disable_web_page_preview=True,
                )
                return
        # Fall through to actual buy
        data = "buy:start_real"

    if data == "buy:start_real":
        # Check if shop is open
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "🔴 <b>فروشگاه موقتاً تعطیل است.</b>\n\nلطفاً بعداً مراجعه کنید.", kb)
            return
        stock_only = setting_get("preorder_mode", "0") == "1"
        items = get_active_types()
        kb = types.InlineKeyboardMarkup()
        has_any = False
        for item in items:
            packs = [p for p in get_packages(type_id=item['id']) if p['price'] > 0 and _pkg_has_stock(p, stock_only)]
            if packs:
                kb.add(types.InlineKeyboardButton(f"🧩 {item['name']}", callback_data=f"buy:t:{item['id']}"))
                has_any = True
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        if not has_any:
            send_or_edit(call, "📭 در حال حاضر بسته‌ای برای فروش موجود نیست.", kb)
        else:
            send_or_edit(call, "🛒 <b>خرید کانفیگ جدید</b>\n\nنوع مورد نظر را انتخاب کنید:", kb)
        return

    if data.startswith("buy:t:"):
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "🔴 <b>فروشگاه موقتاً تعطیل است.</b>\n\nلطفاً بعداً مراجعه کنید.", kb)
            return
        type_id   = int(data.split(":")[2])
        stock_only = setting_get("preorder_mode", "0") == "1"
        user = get_user(uid)
        _is_agent = bool(user and user["is_agent"])
        packages = [p for p in get_packages(type_id=type_id) if p["price"] > 0 and _br_ok(p, _is_agent) and _pkg_has_stock(p, stock_only)]
        # For user-count selector, check ALL packages regardless of stock
        all_type_packages = [p for p in get_packages(type_id=type_id) if p["price"] > 0 and _br_ok(p, _is_agent)]
        user_limits = sorted(set(p["max_users"] if "max_users" in p.keys() else 0 for p in all_type_packages))
        if any(u != 0 for u in user_limits):
            kb = types.InlineKeyboardMarkup()
            for u in user_limits:
                label = "👥 نامحدود" if u == 0 else f"👥 {u} کاربره"
                kb.add(types.InlineKeyboardButton(label, callback_data=f"buy:mu:{u}:{type_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="buy:start", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "👥 تعداد کاربر مورد نظر را انتخاب کنید:", kb)
            return
        kb   = types.InlineKeyboardMarkup()
        for p in packages:
            price = get_effective_price(uid, p)
            stock_tag = "" if _pkg_has_stock(p, True) else " ⏳"
            _sn = p['show_name'] if 'show_name' in p.keys() else 1
            _name_part = f"{p['name']}{stock_tag} | " if _sn else (f"{stock_tag} | " if stock_tag else "")
            title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)} ت"
            kb.add(types.InlineKeyboardButton(title, callback_data=f"buy:p:{p['id']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="buy:start", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        agent_note = "\n\n🤝 <i>این قیمت‌ها مخصوص همکاری شماست</i>" if user and user["is_agent"] else ""
        if not packages:
            send_or_edit(call, "📭 در حال حاضر بسته‌ای برای فروش در این نوع موجود نیست.", kb)
        else:
            send_or_edit(call, f"📦 یکی از پکیج‌ها را انتخاب کنید:{agent_note}", kb)
        return

    if data.startswith("buy:mu:"):
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "🔴 <b>فروشگاه موقتاً تعطیل است.</b>\n\nلطفاً بعداً مراجعه کنید.", kb)
            return
        parts_mu     = data.split(":")
        selected_mu  = int(parts_mu[2])
        type_id      = int(parts_mu[3])
        stock_only   = setting_get("preorder_mode", "0") == "1"
        user = get_user(uid)
        _is_agent = bool(user and user["is_agent"])
        all_pkgs = [p for p in get_packages(type_id=type_id) if p["price"] > 0 and _br_ok(p, _is_agent) and _pkg_has_stock(p, stock_only)]
        packages = [p for p in all_pkgs if (p["max_users"] if "max_users" in p.keys() else 0) == selected_mu]
        kb   = types.InlineKeyboardMarkup()
        for p in packages:
            price     = get_effective_price(uid, p)
            stock_tag = "" if _pkg_has_stock(p, True) else " ⏳"
            _sn       = p['show_name'] if 'show_name' in p.keys() else 1
            _name_part = f"{p['name']}{stock_tag} | " if _sn else (f"{stock_tag} | " if stock_tag else "")
            title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)} ت"
            kb.add(types.InlineKeyboardButton(title, callback_data=f"buy:p:{p['id']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"buy:t:{type_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        agent_note = "\n\n🤝 <i>این قیمت‌ها مخصوص همکاری شماست</i>" if user and user["is_agent"] else ""
        if not packages:
            send_or_edit(call, "📭 در حال حاضر بسته‌ای برای فروش در این نوع موجود نیست.", kb)
        else:
            send_or_edit(call, f"📦 یکی از پکیج‌ها را انتخاب کنید:{agent_note}", kb)
        return

    if data.startswith("buy:p:"):
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "🔴 <b>فروشگاه موقتاً تعطیل است.</b>\n\nلطفاً بعداً مراجعه کنید.", kb)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        # ── Buyer role enforcement ────────────────────────────────────────────
        buyer_role = package_row["buyer_role"] if "buyer_role" in package_row.keys() else "all"
        if buyer_role == "nobody":
            bot.answer_callback_query(call.id,
                "🔒 این پکیج در دسترس عموم نیست.",
                show_alert=True)
            return
        if buyer_role != "all":
            _user = get_user(uid)
            _is_agent = bool(_user and _user["is_agent"])
            if buyer_role == "agents" and not _is_agent:
                bot.answer_callback_query(call.id,
                    "🔒 این پکیج فقط برای نمایندگان فعال است.\n\n"
                    "برای تهیه این پکیج باید نماینده باشید.",
                    show_alert=True)
                return
            if buyer_role == "public" and _is_agent:
                bot.answer_callback_query(call.id,
                    "🔒 این پکیج فقط برای کاربران عادی قابل خرید است.\n\n"
                    "نمایندگان مجاز به خرید این پکیج نیستند.",
                    show_alert=True)
                return
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        price = get_effective_price(uid, package_row)
        state_set(uid, "buy_select_method",
                  package_id=package_id, amount=price, original_amount=price,
                  kind="config_purchase", unit_price=price, quantity=1)
        bot.answer_callback_query(call.id)
        if should_show_bulk_qty(uid):
            _show_qty_prompt(call, package_row, price)
            return
        if setting_get("discount_codes_enabled", "0") == "1":
            if _show_discount_prompt(call, price):
                return
        _show_purchase_gateways(call, uid, package_id, price, package_row)
        return

    if data.startswith("pay:wallet:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        user        = get_user(uid)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        preorder_on = setting_get("preorder_mode", "0") == "1"
        if not _pkg_has_stock(package_row, preorder_on):
            bot.answer_callback_query(call.id, "موجودی این پکیج تمام شده است.", show_alert=True)
            return
        price    = _get_state_price(uid, package_row, "buy_select_method")
        quantity = int(state_data(uid).get("quantity", 1) or 1)
        if user["balance"] < price:
            bot.answer_callback_query(call.id, "موجودی کیف پول کافی نیست.", show_alert=True)
            return
        # Deduct total and create payment record first
        update_balance(uid, -price)
        payment_id = create_payment("config_purchase", uid, package_id, price, "wallet",
                                    status="completed", quantity=quantity)
        complete_payment(payment_id)
        bot.answer_callback_query(call.id, "خرید با موفقیت انجام شد.")
        send_or_edit(call, "✅ پرداخت از کیف پول انجام شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                     back_button("main"))
        purchase_ids, pending_ids = _deliver_bulk_configs(
            call.message.chat.id, uid, package_id, price, "wallet", quantity, payment_id
        )
        if not purchase_ids and not pending_ids:
            # Exceptional: refund and abort
            update_balance(uid, price)
            bot.send_message(uid,
                "⚠️ <b>خطا در تحویل سرویس</b>\n\n"
                "متأسفانه در تحویل سرویس مشکلی پیش آمد و مبلغ به کیف پول شما بازگردانده شد.\n"
                "لطفاً با پشتیبانی تماس بگیرید.",
                parse_mode="HTML", reply_markup=back_button("main"))
            state_clear(uid)
            return
        _send_bulk_delivery_result(call.message.chat.id, uid, package_row,
                                   purchase_ids, pending_ids, "کیف پول")
        state_clear(uid)
        return

    if data.startswith("pay:card:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "موجودی این پکیج تمام شده است.", show_alert=True)
            return
        # Phone gate for card_only mode
        if setting_get("phone_mode", "disabled") == "card_only" and not get_phone_number(uid):
            from telebot.types import ReplyKeyboardMarkup, KeyboardButton
            state_set(uid, "waiting_for_phone_card", pending_package_id=package_id)
            bot.answer_callback_query(call.id)
            kb_phone = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            kb_phone.add(KeyboardButton("📱 ارسال شماره تلفن", request_contact=True))
            bot.send_message(call.message.chat.id,
                "📱 <b>ثبت شماره تلفن</b>\n\n"
                "برای پرداخت کارت به کارت، ابتدا باید شماره تلفن خود را ثبت کنید.\n"
                "با دکمه زیر شماره خود را ارسال کنید:",
                parse_mode="HTML", reply_markup=kb_phone)
            return
        _ci = pick_card_for_payment()
        if not _ci:
            bot.answer_callback_query(call.id, "اطلاعات پرداخت هنوز ثبت نشده است.", show_alert=True)
            return
        card, bank, owner = _ci["card_number"], _ci["bank_name"], _ci["holder_name"]
        price      = _get_state_price(uid, package_row, "buy_select_method")
        price = apply_gateway_fee("card", price)
        if not is_gateway_in_range("card", price):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای این درگاه مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        _qty_card = int(state_data(uid).get("quantity", 1) or 1)
        payment_id = create_payment("config_purchase", uid, package_id, price, "card",
                                    status="pending", quantity=_qty_card)
        # Generate random amount if enabled
        final_amount = None
        if setting_get("gw_card_random_amount", "0") == "1":
            final_amount = _generate_card_final_amount(price, payment_id)
            update_payment_final_amount(payment_id, final_amount)
        state_set(uid, "await_purchase_receipt", payment_id=payment_id)
        text, kb = _build_card_payment_page(card, bank, owner, price, final_amount)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("pay:crypto:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "موجودی این پکیج تمام شده است.", show_alert=True)
            return
        price    = _get_state_price(uid, package_row, "buy_select_method")
        _qty_cr  = int(state_data(uid).get("quantity", 1) or 1)
        if not is_gateway_in_range("crypto", price):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای این درگاه مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        state_set(uid, "buy_crypto_select_coin", package_id=package_id, amount=price, quantity=_qty_cr)
        bot.answer_callback_query(call.id)
        show_crypto_selection(call, amount=price)
        return

    # Crypto coin selection (after buy)
    if data.startswith("pm:crypto:"):
        coin_key = data.split(":")[2]
        sd       = state_data(uid)
        sn       = state_name(uid)
        try:
            if sn == "buy_crypto_select_coin":
                package_id  = sd.get("package_id")
                amount      = sd.get("amount")
                _qty_coin   = int(sd.get("quantity", 1) or 1)
                package_row = get_package(package_id)
                if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
                    bot.answer_callback_query(call.id, "موجودی تمام شده است.", show_alert=True)
                    return
                payment_id = create_payment("config_purchase", uid, package_id, amount, "crypto",
                                            status="pending", crypto_coin=coin_key, quantity=_qty_coin)
                bot.answer_callback_query(call.id)
                if show_crypto_payment_info(call, uid, coin_key, amount, payment_id=payment_id):
                    state_set(uid, "await_purchase_receipt", payment_id=payment_id)
            elif sn == "wallet_crypto_select_coin":
                amount     = sd.get("amount")
                payment_id = sd.get("payment_id") or create_payment("wallet_charge", uid, None, amount, "crypto",
                                                                      status="pending", crypto_coin=coin_key)
                bot.answer_callback_query(call.id)
                if show_crypto_payment_info(call, uid, coin_key, amount, payment_id=payment_id):
                    state_set(uid, "await_wallet_receipt", payment_id=payment_id, amount=amount)
            elif sn == "renew_crypto_select_coin":
                package_id  = sd.get("package_id")
                amount      = sd.get("amount")
                config_id_r = sd.get("config_id")
                purchase_id = sd.get("purchase_id")
                payment_id = create_payment("renewal", uid, package_id, amount, "crypto",
                                            status="pending", crypto_coin=coin_key, config_id=config_id_r)
                bot.answer_callback_query(call.id)
                if show_crypto_payment_info(call, uid, coin_key, amount, payment_id=payment_id):
                    state_set(uid, "await_renewal_receipt", payment_id=payment_id, purchase_id=purchase_id)
            elif sn == "pnlcfg_renew_crypto_select_coin":
                package_id  = sd.get("package_id")
                amount      = sd.get("amount")
                config_id_r = sd.get("config_id")
                payment_id = create_payment("pnlcfg_renewal", uid, package_id, amount, "crypto",
                                            status="pending", crypto_coin=coin_key, config_id=config_id_r)
                bot.answer_callback_query(call.id)
                if show_crypto_payment_info(call, uid, coin_key, amount, payment_id=payment_id):
                    state_set(uid, "await_renewal_receipt", payment_id=payment_id, config_id=config_id_r)
            else:
                bot.answer_callback_query(call.id)
        except Exception as _ex:
            log.exception("pm:crypto: handler error for uid=%s coin=%s: %s", uid, coin_key, _ex)
            try:
                bot.answer_callback_query(call.id)
            except Exception:
                pass
            bot.send_message(uid, "⚠️ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
                             reply_markup=kb_main(uid))
        return

    if data == "pm:crypto":
        sd = state_data(uid)
        amount = sd.get("amount")
        if state_name(uid) == "wallet_charge_method":
            payment_id = create_payment("wallet_charge", uid, None, amount, "crypto", status="pending")
            state_set(uid, "wallet_crypto_select_coin", amount=amount, payment_id=payment_id)
        bot.answer_callback_query(call.id)
        show_crypto_selection(call, amount=amount)
        return

    if data == "pm:back":
        bot.answer_callback_query(call.id)

    # ── Crypto copy buttons use CopyTextButton (Bot API 7.0) ─────────────────
    # No callback handlers needed — buttons copy directly to clipboard.
        show_main_menu(call)
        return

    # ── Invoice expired restart ───────────────────────────────────────────────
    if data == "invoice:restart":
        bot.answer_callback_query(call.id)
        state_clear(uid)
        show_main_menu(call)
        return

    # ── TetraPay ──────────────────────────────────────────────────────────────
    if data.startswith("pay:tetrapay:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
            return
        authority = payment["receipt_text"]
        success, result = verify_tetrapay_order(authority)
        if success:
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                try:
                    apply_gateway_bonus_if_needed(uid, "tetrapay", payment["amount"])
                except Exception:
                    pass
                bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
                send_or_edit(call, f"✅ پرداخت شما تأیید و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(payment['amount'])} تومان", back_button("main"))
                state_clear(uid)
            else:
                config_id  = payment["config_id"]
                package_id = payment["package_id"]
                package_row = get_package(package_id)
                _qty_tp    = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                    return
                bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
                send_or_edit(call, "✅ پرداخت شما تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                             back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    call.message.chat.id, uid, package_id,
                    payment["amount"], "tetrapay", _qty_tp, payment_id
                )
                try:
                    apply_gateway_bonus_if_needed(uid, "tetrapay", payment["amount"])
                except Exception:
                    pass
                _send_bulk_delivery_result(call.message.chat.id, uid, package_row,
                                           purchase_ids, pending_ids, "TetraPay")
                state_clear(uid)
        else:
            _st = result.get("status", "") if isinstance(result, dict) else ""
            bot.answer_callback_query(call.id,
                f"❌ پرداخت هنوز تایید نشده.\nوضعیت TetraPay: {_st}\n\nلطفاً ابتدا پرداخت را در درگاه تتراپی انجام دهید.",
                show_alert=True)
        return

    if data.startswith("pay:tetrapay:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "موجودی این پکیج تمام شده است.", show_alert=True)
            return
        price    = _get_state_price(uid, package_row, "buy_select_method")
        _qty_tetra = int(state_data(uid).get("quantity", 1) or 1)
        if not is_gateway_in_range("tetrapay", price):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه TetraPay مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        hash_id = f"cfg-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"خرید {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"خرید {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tetrapay_order(price, hash_id, order_label)
        if not success:
            bot.answer_callback_query(call.id, "خطا در ایجاد درخواست پرداخت آنلاین.", show_alert=True)
            return
        authority = result.get("Authority", "")
        pay_url_bot = result.get("payment_url_bot", "")
        pay_url_web = result.get("payment_url_web", "")
        payment_id = create_payment("config_purchase", uid, package_id, price, "tetrapay",
                                    status="pending", quantity=_qty_tetra)
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (authority, payment_id))
        state_set(uid, "await_tetrapay_verify", payment_id=payment_id, authority=authority)
        text = (
            "🏦 <b>پرداخت آنلاین (TetraPay)</b>\n\n"
            f"💰 مبلغ: <b>{fmt_price(price)}</b> تومان\n\n"
            "لطفاً از یکی از لینک‌های زیر پرداخت را انجام دهید.\n\n"
            "⏳ <b>تا یک ساعت</b> اگر پرداخت‌تون تایید بشه به صورت خودکار عملیات انجام می‌شود.\n"
            "در غیر این صورت دکمه <b>بررسی پرداخت</b> را بزنید."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("💳 پرداخت در تلگرام", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("🌐 پرداخت در مرورگر", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("🔍 بررسی پرداخت", callback_data=f"pay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "config_purchase", package_id=package_id)
        return

    # ── TronPays Rial: purchase ───────────────────────────────────────────────
    if data.startswith("pay:tronpays_rial:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        ok, status = check_tronpays_rial_invoice(invoice_id)
        if not ok:
            bot.answer_callback_query(call.id, "خطا در بررسی وضعیت فاکتور.", show_alert=True)
            return
        if is_tronpays_paid(status):
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
                send_or_edit(call, f"✅ پرداخت شما تأیید و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(payment['amount'])} تومان",
                             back_button("main"))
                try:
                    apply_gateway_bonus_if_needed(uid, "tronpays_rial", payment["amount"])
                except Exception:
                    pass
                state_clear(uid)
            else:
                config_id  = payment["config_id"]
                package_id = payment["package_id"]
                package_row = get_package(package_id)
                _qty_tron  = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                    return
                bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
                send_or_edit(call, "✅ پرداخت شما تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                             back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    call.message.chat.id, uid, package_id,
                    payment["amount"], "tronpays_rial", _qty_tron, payment_id
                )
                try:
                    apply_gateway_bonus_if_needed(uid, "tronpays_rial", payment["amount"])
                except Exception:
                    pass
                _send_bulk_delivery_result(call.message.chat.id, uid, package_row,
                                           purchase_ids, pending_ids, "TronPays")
                state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "❌ پرداخت هنوز تأیید نشده. لطفاً ابتدا پرداخت را انجام دهید.", show_alert=True)
        return

    if data.startswith("pay:tronpays_rial:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "موجودی این پکیج تمام شده است.", show_alert=True)
            return
        price   = _get_state_price(uid, package_row, "buy_select_method")
        _qty_tp_rial = int(state_data(uid).get("quantity", 1) or 1)
        if not is_gateway_in_range("tronpays_rial", price):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه TronPay مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        hash_id = f"cfg-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"خرید {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"خرید {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tronpays_rial_invoice(price, hash_id, order_label)
        if not success:
            err_msg = result.get("error", "خطای ناشناخته") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"⚠️ <b>خطا در ایجاد درگاه TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "💡 مطمئن شوید کلید API صحیح وارد شده باشد.",
                back_button(f"buy:p:{package_id}"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"⚠️ <b>خطا در ایجاد فاکتور TronPays</b>\n\n"
                f"<code>پاسخ API: {esc(str(result)[:400])}</code>",
                back_button(f"buy:p:{package_id}"))
            return
        payment_id = create_payment("config_purchase", uid, package_id, price, "tronpays_rial",
                                    status="pending", quantity=_qty_tp_rial)
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_tronpays_rial_verify", payment_id=payment_id, invoice_id=invoice_id)
        text = (
            "💳 <b>پرداخت ریالی (TronPays)</b>\n\n"
            f"💰 مبلغ: <b>{fmt_price(price)}</b> تومان\n\n"
            "از لینک زیر پرداخت را انجام دهید.\n\n"
            "⏳ <b>تا یک ساعت</b> پرداخت به صورت خودکار بررسی می‌شود.\n"
            "در غیر این صورت دکمه «بررسی پرداخت» را بزنید."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 پرداخت از درگاه TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("🔍 بررسی پرداخت", callback_data=f"pay:tronpays_rial:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tronpays_rial_auto_verify(
            payment_id, invoice_id, uid,
            call.message.chat.id, call.message.message_id,
            "config_purchase", package_id=package_id)
        return

    # ── Free test ─────────────────────────────────────────────────────────────
    if data == "test:start":
        _ft_mode = setting_get("free_test_mode", "everyone")
        user = get_user(uid)
        is_agent_user = user and user["is_agent"]
        if _ft_mode == "disabled":
            bot.answer_callback_query(call.id, "تست رایگان غیرفعال است.", show_alert=True)
            return
        if _ft_mode == "agents_only" and not is_agent_user:
            bot.answer_callback_query(call.id, "تست رایگان فقط برای نمایندگان فعال است.", show_alert=True)
            return
        if is_agent_user:
            agent_limit = int(setting_get("agent_test_limit", "0") or "0")
            agent_period = setting_get("agent_test_period", "day")
            if agent_limit > 0:
                used = agent_test_count_in_period(uid, agent_period)
                if used >= agent_limit:
                    period_labels = {"day": "روز", "week": "هفته", "month": "ماه"}
                    bot.answer_callback_query(call.id,
                        f"شما سقف تست رایگان ({agent_limit} عدد در {period_labels.get(agent_period, agent_period)}) را استفاده کرده‌اید.",
                        show_alert=True)
                    return
        else:
            if user_has_any_test(uid):
                bot.answer_callback_query(call.id, "شما قبلاً تست رایگان خود را دریافت کرده‌اید.", show_alert=True)
                return
        items = get_active_types()
        kb    = types.InlineKeyboardMarkup()
        has_any = False
        for item in items:
            packs = [p for p in get_packages(type_id=item['id'], price_only=0) if p['stock'] > 0]
            if packs:
                kb.add(types.InlineKeyboardButton(f"🎁 {item['name']}", callback_data=f"test:t:{item['id']}"))
                has_any = True
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        if not has_any:
            send_or_edit(call, "📭 در حال حاضر تست رایگانی موجود نیست.", kb)
        else:
            send_or_edit(call, "🎁 <b>تست رایگان</b>\n\nنوع مورد نظر را انتخاب کنید:", kb)
        return

    if data.startswith("test:t:"):
        _ft_mode = setting_get("free_test_mode", "everyone")
        user = get_user(uid)
        is_agent_user = user and user["is_agent"]
        if _ft_mode == "disabled":
            bot.answer_callback_query(call.id, "تست رایگان غیرفعال است.", show_alert=True)
            return
        if _ft_mode == "agents_only" and not is_agent_user:
            bot.answer_callback_query(call.id, "تست رایگان فقط برای نمایندگان فعال است.", show_alert=True)
            return
        if is_agent_user:
            agent_limit = int(setting_get("agent_test_limit", "0") or "0")
            agent_period = setting_get("agent_test_period", "day")
            if agent_limit > 0:
                used = agent_test_count_in_period(uid, agent_period)
                if used >= agent_limit:
                    period_labels = {"day": "روز", "week": "هفته", "month": "ماه"}
                    bot.answer_callback_query(call.id,
                        f"شما سقف تست رایگان ({agent_limit} عدد در {period_labels.get(agent_period, agent_period)}) را استفاده کرده‌اید.",
                        show_alert=True)
                    return
        else:
            if user_has_any_test(uid):
                bot.answer_callback_query(call.id, "شما قبلاً تست رایگان خود را دریافت کرده‌اید.", show_alert=True)
                return
        type_id     = int(data.split(":")[2])
        type_row    = get_type(type_id)
        package_row = None
        for item in get_packages(type_id=type_id, price_only=0):
            if item["stock"] > 0:
                package_row = item
                break
        if not package_row:
            bot.answer_callback_query(call.id, "برای این نوع تست رایگان موجود نیست.", show_alert=True)
            return
        config_id = reserve_first_config(package_row["id"])
        if not config_id:
            bot.answer_callback_query(call.id, "تست رایگان این نوع تمام شده است.", show_alert=True)
            return
        try:
            purchase_id = assign_config_to_user(config_id, uid, package_row["id"], 0, "free_test", is_test=1)
        except Exception:
            release_reserved_config(config_id)
            bot.answer_callback_query(call.id, "⚠️ خطایی رخ داد، لطفاً دوباره تلاش کنید.", show_alert=True)
            return
        # Check stock level and notify admins if thresholds crossed (free test delivery)
        try:
            from ..ui.notifications import check_and_notify_stock
            check_and_notify_stock(package_row["id"], package_row["name"])
        except Exception:
            pass
        bot.answer_callback_query(call.id, "تست رایگان ارسال شد.")
        send_or_edit(call, f"✅ تست رایگان نوع <b>{esc(type_row['name'])}</b> آماده شد.", back_button("main"))
        deliver_purchase_message(call.message.chat.id, purchase_id)
        return

    # ── Wallet charge ─────────────────────────────────────────────────────────
    if data == "wallet:charge":
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "🔴 <b>فروشگاه موقتاً تعطیل است.</b>\n\nشارژ کیف پول در حال حاضر امکان‌پذیر نیست.", kb)
            return
        if not wallet_pay_enabled_for(uid):
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "❌ <b>شارژ کیف پول</b>\n\nامکان استفاده از کیف پول در حال حاضر برای شما فعال نیست.", kb)
            return
        state_set(uid, "await_wallet_amount")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "💳 <b>شارژ کیف پول</b>\n\nمبلغ مورد نظر را به تومان وارد کنید:", kb)
        return

    if data == "wallet:charge:card":
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "ابتدا مبلغ را وارد کنید.", show_alert=True)
            return
        if not is_gateway_in_range("card", amount):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(amount)} تومان برای این درگاه مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        _ci = pick_card_for_payment()
        if not _ci:
            bot.answer_callback_query(call.id, "اطلاعات پرداخت هنوز ثبت نشده است.", show_alert=True)
            return
        card, bank, owner = _ci["card_number"], _ci["bank_name"], _ci["holder_name"]
        amount = apply_gateway_fee("card", amount)
        payment_id = create_payment("wallet_charge", uid, None, amount, "card", status="pending")
        # Generate random amount if enabled
        final_amount = None
        if setting_get("gw_card_random_amount", "0") == "1":
            final_amount = _generate_card_final_amount(amount, payment_id)
            update_payment_final_amount(payment_id, final_amount)
        state_set(uid, "await_wallet_receipt", payment_id=payment_id, amount=amount)
        text, kb = _build_card_payment_page(card, bank, owner, amount, final_amount)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "wallet:charge:crypto":
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "ابتدا مبلغ را وارد کنید.", show_alert=True)
            return
        if not is_gateway_in_range("crypto", amount):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(amount)} تومان برای این درگاه مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        state_set(uid, "wallet_crypto_select_coin", amount=amount)
        bot.answer_callback_query(call.id)
        show_crypto_selection(call, amount=amount)
        return

    if data == "wallet:charge:tetrapay":
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "ابتدا مبلغ را وارد کنید.", show_alert=True)
            return
        if not is_gateway_in_range("tetrapay", amount):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(amount)} تومان برای درگاه TetraPay مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        hash_id = f"wallet-{uid}-{int(datetime.now().timestamp())}"
        success, result = create_tetrapay_order(amount, hash_id, "شارژ کیف پول")
        if not success:
            bot.answer_callback_query(call.id, "خطا در ایجاد درخواست پرداخت آنلاین.", show_alert=True)
            return
        authority = result.get("Authority", "")
        pay_url_bot = result.get("payment_url_bot", "")
        pay_url_web = result.get("payment_url_web", "")
        payment_id = create_payment("wallet_charge", uid, None, amount, "tetrapay", status="pending")
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (authority, payment_id))
        state_set(uid, "await_tetrapay_verify", payment_id=payment_id, authority=authority)
        text = (
            "🏦 <b>شارژ کیف پول - پرداخت آنلاین (TetraPay)</b>\n\n"
            f"💰 مبلغ: <b>{fmt_price(amount)}</b> تومان\n\n"
            "لطفاً از یکی از لینک‌های زیر پرداخت را انجام دهید.\n\n"
            "⏳ <b>تا یک ساعت</b> اگر پرداخت‌تون تایید بشه به صورت خودکار کیف پول شارژ می‌شود.\n"
            "در غیر این صورت دکمه <b>بررسی پرداخت</b> را بزنید."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("💳 پرداخت در تلگرام", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("🌐 پرداخت در مرورگر", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("🔍 بررسی پرداخت", callback_data=f"pay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "wallet_charge")
        return

    # ── SwapWallet Crypto (network selection) ─────────────────────────────────
    if data == "wallet:charge:swapwallet_crypto":
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "ابتدا مبلغ را وارد کنید.", show_alert=True)
            return
        if not is_gateway_in_range("swapwallet_crypto", amount):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(amount)} تومان برای درگاه SwapWallet مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import get_active_swapwallet_networks, NETWORK_LABELS as SW_NET_LABELS
        _active_nets = get_active_swapwallet_networks()
        if not _active_nets:
            bot.answer_callback_query(call.id, "هیچ ارزی برای SwapWallet فعال نشده است.", show_alert=True)
            return
        state_set(uid, "swcrypto_network_select", kind="wallet_charge", amount=amount)
        kb = types.InlineKeyboardMarkup()
        if len(_active_nets) == 1:
            # Skip selection — go directly with the only available network
            net = _active_nets[0][0]
            state_set(uid, "swcrypto_network_select", kind="wallet_charge", amount=amount)
            # Emit synthetic callback — handled by swcrypto:net: branch below (force inline)
            _swc_sd = state_data(uid)
            _swc_sd["_auto_net"] = net
            order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
            success, result = create_swapwallet_crypto_invoice(amount, order_id, net, "شارژ کیف پول")
            if not success:
                err_msg = result.get("error", "خطای ناشناخته") if isinstance(result, dict) else str(result)
                _swapwallet_error_inline(call, err_msg)
                return
            invoice_id = result.get("id", "")
            payment_id = create_payment("wallet_charge", uid, None, amount, "swapwallet_crypto", status="pending")
            with get_conn() as conn:
                conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
            state_set(uid, "await_swapwallet_crypto_verify", payment_id=payment_id, invoice_id=invoice_id)
            verify_cb = f"pay:swapwallet_crypto:verify:{payment_id}"
            show_swapwallet_crypto_page(call, amount_toman=amount, invoice_id=invoice_id,
                                        result=result, payment_id=payment_id, verify_cb=verify_cb)
        else:
            for net, _ in _active_nets:
                kb.add(types.InlineKeyboardButton(SW_NET_LABELS.get(net, net), callback_data=f"swcrypto:net:{net}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "💎 <b>پرداخت کریپتو (SwapWallet)</b>\n\nشبکه مورد نظر را انتخاب کنید:", kb)
        return

    if data == "wallet:charge:tronpays_rial":
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "ابتدا مبلغ را وارد کنید.", show_alert=True)
            return
        if not is_gateway_in_range("tronpays_rial", amount):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(amount)} تومان برای درگاه TronPay مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        order_id = f"wallet-{uid}-{int(datetime.now().timestamp())}"
        success, result = create_tronpays_rial_invoice(amount, order_id, "شارژ کیف پول")
        if not success:
            err_msg = result.get("error", "خطای ناشناخته") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"⚠️ <b>خطا در ایجاد درگاه TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "💡 مطمئن شوید کلید API صحیح وارد شده باشد.",
                back_button("wallet:charge"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"⚠️ <b>خطا در ایجاد فاکتور TronPays</b>\n\n"
                f"<code>پاسخ API: {esc(str(result)[:400])}</code>",
                back_button("wallet:charge"))
            return
        payment_id = create_payment("wallet_charge", uid, None, amount, "tronpays_rial", status="pending")
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_tronpays_rial_verify", payment_id=payment_id, invoice_id=invoice_id)
        text = (
            "💳 <b>شارژ کیف پول — TronPays</b>\n\n"
            f"💰 مبلغ: <b>{fmt_price(amount)}</b> تومان\n\n"
            "از لینک زیر پرداخت را انجام دهید.\n\n"
            "⏳ <b>تا یک ساعت</b> پرداخت به صورت خودکار بررسی می‌شود.\n"
            "در غیر این صورت دکمه «بررسی پرداخت» را بزنید."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 پرداخت از درگاه TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("🔍 بررسی پرداخت", callback_data=f"pay:tronpays_rial:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tronpays_rial_auto_verify(
            payment_id, invoice_id, uid,
            call.message.chat.id, call.message.message_id,
            "wallet_charge")
        return

    if data.startswith("pay:swapwallet_crypto:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        success, inv = check_swapwallet_crypto_invoice(invoice_id)
        if not success:
            bot.answer_callback_query(call.id, "خطا در بررسی وضعیت فاکتور.", show_alert=True)
            return
        inv_status = inv.get("status", "")
        if inv_status in ("PAID", "COMPLETED") or inv.get("paidAt"):
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
                send_or_edit(call, f"✅ پرداخت شما تأیید و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(payment['amount'])} تومان",
                             back_button("main"))
                state_clear(uid)
            else:
                config_id  = payment["config_id"]
                package_id = payment["package_id"]
                package_row = get_package(package_id)
                _qty_sw = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                    return
                bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
                send_or_edit(call, "✅ پرداخت شما تأیید شد. کانفیگ‌های شما در حال آماده‌سازی هستند...",
                             back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    call.message.chat.id, uid, package_id,
                    payment["amount"], "swapwallet_crypto", _qty_sw, payment_id
                )
                try:
                    apply_gateway_bonus_if_needed(uid, "swapwallet_crypto", payment["amount"])
                except Exception:
                    pass
                _send_bulk_delivery_result(call.message.chat.id, uid, package_row,
                                           purchase_ids, pending_ids, "SwapWallet Crypto")
                state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "❌ پرداخت هنوز تأیید نشده. لطفاً ابتدا واریز را انجام دهید.", show_alert=True)
        return

    if data.startswith("pay:swapwallet_crypto:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "موجودی این پکیج تمام شده است.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "buy_select_method")
        _qty_sw_init = int(state_data(uid).get("quantity", 1) or 1)
        if not is_gateway_in_range("swapwallet_crypto", price):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه SwapWallet مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import get_active_swapwallet_networks, NETWORK_LABELS as SW_NET_LABELS
        _active_nets2 = get_active_swapwallet_networks()
        if not _active_nets2:
            bot.answer_callback_query(call.id, "هیچ ارزی برای SwapWallet فعال نشده است.", show_alert=True)
            return
        state_set(uid, "swcrypto_network_select", kind="config_purchase", package_id=package_id, amount=price,
                  quantity=_qty_sw_init)
        kb = types.InlineKeyboardMarkup()
        if len(_active_nets2) == 1:
            # Only one network — auto-select and go directly to payment
            net = _active_nets2[0][0]
            order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
            success, result = create_swapwallet_crypto_invoice(price, order_id, net, "پرداخت کریپتو")
            if not success:
                err_msg = result.get("error", "خطای ناشناخته") if isinstance(result, dict) else str(result)
                _swapwallet_error_inline(call, err_msg)
                return
            invoice_id = result.get("id", "")
            payment_id = create_payment("config_purchase", uid, package_id, price, "swapwallet_crypto",
                                        status="pending", quantity=_qty_sw_init)
            with get_conn() as conn:
                conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
            state_set(uid, "await_swapwallet_crypto_verify", payment_id=payment_id, invoice_id=invoice_id)
            verify_cb = f"pay:swapwallet_crypto:verify:{payment_id}"
            bot.answer_callback_query(call.id)
            show_swapwallet_crypto_page(call, amount_toman=price, invoice_id=invoice_id,
                                        result=result, payment_id=payment_id, verify_cb=verify_cb)
        else:
            for net, _ in _active_nets2:
                kb.add(types.InlineKeyboardButton(SW_NET_LABELS.get(net, net), callback_data=f"swcrypto:net:{net}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"buy:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "💎 <b>پرداخت کریپتو (SwapWallet)</b>\n\nشبکه مورد نظر را انتخاب کنید:", kb)
        return

    if data.startswith("rpay:swapwallet_crypto:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        success, inv = check_swapwallet_crypto_invoice(invoice_id)
        if not success:
            bot.answer_callback_query(call.id, "خطا در بررسی وضعیت فاکتور.", show_alert=True)
            return
        if inv.get("status") in ("PAID", "COMPLETED") or inv.get("paidAt"):
            if not complete_payment(payment_id):
                bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True)
                return
            package_row = get_package(payment["package_id"])
            config_id   = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد!")
            send_or_edit(call,
                "✅ <b>درخواست تمدید ارسال شد</b>\n\n"
                "🔄 درخواست تمدید سرویس شما با موفقیت ثبت و برای پشتیبانی ارسال شد.\n"
                "⏳ لطفاً کمی صبر کنید، پس از انجام تمدید به شما اطلاع داده خواهد شد.\n\n"
                "🙏 از صبر و شکیبایی شما متشکریم.",
                back_button("main"))
            if item:
                admin_renewal_notify(uid, item, package_row, payment["amount"], "SwapWallet Crypto")
            try:
                apply_gateway_bonus_if_needed(uid, "swapwallet_crypto", payment["amount"])
            except Exception:
                pass
            state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "❌ پرداخت هنوز تأیید نشده. لطفاً ابتدا واریز را انجام دهید.", show_alert=True)
        return

    if data.startswith("rpay:swapwallet_crypto:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("swapwallet_crypto", price):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه SwapWallet مجاز نیست.\n"
                f"محدوده مجاز: {_rng}\n\n"
                "لطفاً درگاه دیگری متناسب با این مبلغ انتخاب کنید.",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import get_active_swapwallet_networks, NETWORK_LABELS as SW_NET_LABELS
        _active_nets3 = get_active_swapwallet_networks()
        if not _active_nets3:
            bot.answer_callback_query(call.id, "هیچ ارزی برای SwapWallet فعال نشده است.", show_alert=True)
            return
        state_set(uid, "swcrypto_network_select", kind="renewal",
                  purchase_id=purchase_id, package_id=package_id,
                  amount=price, config_id=item["config_id"])
        kb = types.InlineKeyboardMarkup()
        if len(_active_nets3) == 1:
            # Only one network — auto-select and go directly to payment
            net = _active_nets3[0][0]
            order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
            success, result = create_swapwallet_crypto_invoice(price, order_id, net, "پرداخت کریپتو")
            if not success:
                err_msg = result.get("error", "خطای ناشناخته") if isinstance(result, dict) else str(result)
                _swapwallet_error_inline(call, err_msg)
                return
            invoice_id = result.get("id", "")
            payment_id = create_payment("renewal", uid, package_id, price, "swapwallet_crypto",
                                        status="pending", config_id=item["config_id"])
            with get_conn() as conn:
                conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
            state_set(uid, "await_swapwallet_crypto_verify", payment_id=payment_id, invoice_id=invoice_id)
            verify_cb = f"rpay:swapwallet_crypto:verify:{payment_id}"
            bot.answer_callback_query(call.id)
            show_swapwallet_crypto_page(call, amount_toman=price, invoice_id=invoice_id,
                                        result=result, payment_id=payment_id, verify_cb=verify_cb)
        else:
            for net, _ in _active_nets3:
                kb.add(types.InlineKeyboardButton(SW_NET_LABELS.get(net, net), callback_data=f"swcrypto:net:{net}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"renew:{purchase_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "💎 <b>پرداخت کریپتو (SwapWallet)</b>\n\nشبکه مورد نظر را انتخاب کنید:", kb)
        return

    # ── SwapWallet Crypto: network selected → create invoice ─────────────────
    if data.startswith("swcrypto:net:"):
        network = data.split(":")[2]
        sd      = state_data(uid)
        kind    = sd.get("kind", "")
        amount  = sd.get("amount", 0)
        if not amount:
            bot.answer_callback_query(call.id, "خطا در اطلاعات سفارش.", show_alert=True)
            return
        order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
        desc = "شارژ کیف پول" if kind == "wallet_charge" else "پرداخت کریپتو"
        success, result = create_swapwallet_crypto_invoice(amount, order_id, network, desc)
        if not success:
            err_msg = result.get("error", "خطای ناشناخته") if isinstance(result, dict) else str(result)
            _swapwallet_error_inline(call, err_msg)
            return
        invoice_id = result.get("id", "")
        if kind == "wallet_charge":
            payment_id = create_payment("wallet_charge", uid, None, amount, "swapwallet_crypto", status="pending")
            verify_cb  = f"pay:swapwallet_crypto:verify:{payment_id}"
        elif kind == "config_purchase":
            package_id = sd.get("package_id")
            _qty_swc   = int(sd.get("quantity", 1) or 1)
            payment_id = create_payment("config_purchase", uid, package_id, amount, "swapwallet_crypto",
                                        status="pending", quantity=_qty_swc)
            verify_cb  = f"pay:swapwallet_crypto:verify:{payment_id}"
        elif kind == "renewal":
            package_id  = sd.get("package_id")
            config_id_r = sd.get("config_id")
            payment_id  = create_payment("renewal", uid, package_id, amount, "swapwallet_crypto",
                                          status="pending", config_id=config_id_r)
            verify_cb   = f"rpay:swapwallet_crypto:verify:{payment_id}"
        elif kind == "pnlcfg_renewal":
            package_id  = sd.get("package_id")
            config_id_r = sd.get("config_id")
            payment_id  = create_payment("pnlcfg_renewal", uid, package_id, amount, "swapwallet_crypto",
                                          status="pending", config_id=config_id_r)
            verify_cb   = f"mypnlcfgrpay:swapwallet_crypto:verify:{payment_id}"
        else:
            bot.answer_callback_query(call.id, "خطا در نوع پرداخت.", show_alert=True)
            return
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_swapwallet_crypto_verify", payment_id=payment_id, invoice_id=invoice_id)
        bot.answer_callback_query(call.id)
        show_swapwallet_crypto_page(call, amount_toman=amount, invoice_id=invoice_id,
                                    result=result, payment_id=payment_id, verify_cb=verify_cb)
        return

    # ── Admin panel ────────────────────────────────────────────────────────────
    if not is_admin(uid):
        # Non-admin shouldn't reach admin callbacks, just ignore
        if data.startswith("admin:") or data.startswith("adm:"):
            bot.answer_callback_query(call.id, "اجازه دسترسی ندارید.", show_alert=True)
            return

    if data == "admin:panel":
        bot.answer_callback_query(call.id)
        footer = ""
        if uid in ADMIN_IDS:
            footer = (
                "\n\n────────────────\n"
                "💡 <b>Seamless Premium</b>\n"
                "👨‍💻 Developer: @EmadHabibnia"
            )
        text = (
            "⚙️ <b>پنل مدیریت</b>\n\n"
            "بخش مورد نظر را انتخاب کنید:"
            f"{footer}"
        )
        send_or_edit(call, text, kb_admin_panel(uid))
        return

    # ── Admin: Types ──────────────────────────────────────────────────────────
    if data == "admin:types":
        if not admin_has_perm(uid, "types_packages"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        _show_admin_types(call)
        bot.answer_callback_query(call.id)
        return

    if data == "admin:type:add":
        state_set(uid, "admin_add_type")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🧩 نام نوع جدید را ارسال کنید:", back_button("admin:types"))
        return

    if data.startswith("admin:type:edit:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "نوع یافت نشد.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"admin:type:editname:{type_id}"))
        kb.add(types.InlineKeyboardButton("📝 ویرایش توضیحات", callback_data=f"admin:type:editdesc:{type_id}"))
        if row["description"]:
            kb.add(types.InlineKeyboardButton("🗑 حذف توضیحات", callback_data=f"admin:type:deldesc:{type_id}"))
        is_active = row["is_active"] if "is_active" in row.keys() else 1
        status_label = "✅ فعال — کلیک برای غیرفعال" if is_active else "❌ غیرفعال — کلیک برای فعال"
        kb.add(types.InlineKeyboardButton(status_label, callback_data=f"admin:type:toggleactive:{type_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:types", icon_custom_emoji_id="5253997076169115797"))
        desc_preview = f"\n📝 توضیحات: {esc(row['description'][:80])}..." if row["description"] and len(row["description"]) > 80 else (f"\n📝 توضیحات: {esc(row['description'])}" if row["description"] else "\n📝 توضیحات: ندارد")
        status_line  = "\n🔘 وضعیت: <b>فعال</b>" if is_active else "\n🔘 وضعیت: <b>غیرفعال</b>"
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"✏️ <b>ویرایش نوع:</b> {esc(row['name'])}{desc_preview}{status_line}", kb)
        return

    if data.startswith("admin:type:editname:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "نوع یافت نشد.", show_alert=True)
            return
        state_set(uid, "admin_edit_type", type_id=type_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"✏️ نام جدید برای نوع <b>{esc(row['name'])}</b> را ارسال کنید:",
                     back_button("admin:types"))
        return

    if data.startswith("admin:type:editdesc:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "نوع یافت نشد.", show_alert=True)
            return
        state_set(uid, "admin_edit_type_desc", type_id=type_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⏭ توضیحاتی نمی‌خواهم وارد کنم", callback_data=f"admin:type:deldesc:{type_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"admin:type:edit:{type_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"📝 توضیحات جدید برای نوع <b>{esc(row['name'])}</b> را ارسال کنید:\n\n"
            "این توضیحات پس از ارسال کانفیگ به کاربر نمایش داده می‌شود.", kb)
        return

    if data == "admin:type:skipdesc":
        sn = state_name(uid)
        sd_val = state_data(uid)
        if sn == "admin_add_type_desc":
            name = sd_val.get("type_name", "")
            try:
                add_type(name, "")
                state_clear(uid)
                bot.answer_callback_query(call.id, "✅ نوع ثبت شد.")
                bot.send_message(call.message.chat.id, "✅ نوع جدید ثبت شد.", reply_markup=kb_admin_panel())
                log_admin_action(uid, f"نوع جدید ثبت شد: <b>{esc(name)}</b>")
            except sqlite3.IntegrityError:
                state_clear(uid)
                bot.answer_callback_query(call.id, "⚠️ این نوع قبلاً ثبت شده.", show_alert=True)
        else:
            bot.answer_callback_query(call.id)
        return

    if data.startswith("admin:type:deldesc:"):
        type_id = int(data.split(":")[3])
        update_type_description(type_id, "")
        state_clear(uid)
        bot.answer_callback_query(call.id, "✅ توضیحات حذف شد.")
        log_admin_action(uid, f"توضیحات نوع #{type_id} حذف شد")
        _show_admin_types(call)
        return

    if data.startswith("admin:type:toggleactive:"):
        type_id = int(data.split(":")[3])
        row = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "نوع یافت نشد.", show_alert=True)
            return
        cur = row["is_active"] if "is_active" in row.keys() else 1
        update_type_active(type_id, 0 if cur else 1)
        new_status = "غیرفعال" if cur else "فعال"
        bot.answer_callback_query(call.id, f"✅ نوع {new_status} شد.")
        log_admin_action(uid, f"نوع <b>{esc(row['name'])}</b> {new_status} شد")
        # re-open the edit screen with updated state
        call.data = f"admin:type:edit:{type_id}"
        data      = call.data

    if data.startswith("admin:pkg:toggleactive:"):
        package_id = int(data.split(":")[3])
        pkg = get_package(package_id)
        if not pkg:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        toggle_package_active(package_id)
        cur = pkg["active"] if "active" in pkg.keys() else 1
        new_status = "غیرفعال" if cur else "فعال"
        bot.answer_callback_query(call.id, f"✅ پکیج {new_status} شد.")
        log_admin_action(uid, f"پکیج <b>{esc(pkg['name'])}</b> {new_status} شد")
        call.data = f"admin:pkg:edit:{package_id}"
        data      = call.data

    if data.startswith("admin:type:del:"):
        type_id = int(data.split(":")[3])
        with get_conn() as conn:
            sold_in_type = conn.execute(
                "SELECT COUNT(*) AS n FROM configs c "
                "JOIN packages p ON p.id=c.package_id "
                "WHERE p.type_id=? AND c.sold_to IS NOT NULL",
                (type_id,)
            ).fetchone()["n"]
            if sold_in_type > 0:
                bot.answer_callback_query(call.id, f"❌ {sold_in_type} کانفیگ فروخته‌شده در این نوع وجود دارد.", show_alert=True)
                return
            pack_count = conn.execute(
                "SELECT COUNT(*) AS n FROM packages WHERE type_id=?", (type_id,)
            ).fetchone()["n"]
            total_cfg = conn.execute(
                "SELECT COUNT(*) AS n FROM configs c "
                "JOIN packages p ON p.id=c.package_id WHERE p.type_id=?",
                (type_id,)
            ).fetchone()["n"]
        if pack_count > 0 or total_cfg > 0:
            kb_c = types.InlineKeyboardMarkup()
            kb_c.row(
                types.InlineKeyboardButton("✅ بله، همه حذف شود", callback_data=f"admin:type:delok:{type_id}"),
                types.InlineKeyboardButton("❌ انصراف", callback_data="admin:types"),
            )
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"⚠️ <b>تأیید حذف نوع</b>\n\n"
                f"{pack_count} پکیج و {total_cfg} کانفیگ (موجود/منقضی) همراه با این نوع حذف خواهند شد.\n"
                "آیا مطمئن هستید؟", kb_c)
            return
        delete_type(type_id)
        bot.answer_callback_query(call.id, "✅ نوع حذف شد.")
        log_admin_action(uid, f"نوع #{type_id} حذف شد")
        _show_admin_types(call)
        return

    if data.startswith("admin:type:delok:"):
        type_id = int(data.split(":")[3])
        with get_conn() as conn:
            sold_in_type = conn.execute(
                "SELECT COUNT(*) AS n FROM configs c "
                "JOIN packages p ON p.id=c.package_id "
                "WHERE p.type_id=? AND c.sold_to IS NOT NULL",
                (type_id,)
            ).fetchone()["n"]
        if sold_in_type > 0:
            bot.answer_callback_query(call.id, "❌ در این فاصله کانفیگ فروخته شد. حذف ممکن نیست.", show_alert=True)
            _show_admin_types(call)
            return
        delete_type(type_id)
        bot.answer_callback_query(call.id, "✅ نوع و تمام پکیج‌های آن حذف شدند.")
        log_admin_action(uid, f"نوع #{type_id} با تمام پکیج‌ها حذف شد")
        _show_admin_types(call)
        return

    if data.startswith("admin:pkg:add:t:"):
        type_id  = int(data.split(":")[4])
        type_row = get_type(type_id)
        state_set(uid, "admin_add_package_name", type_id=type_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"✏️ نام پکیج برای نوع <b>{esc(type_row['name'])}</b> را وارد کنید:",
                     back_button("admin:types"))
        return

    if data.startswith("admin:pkg:add:sn:"):
        # step: admin clicked yes/no for show_name during package creation
        if state_name(uid) != "admin_add_package_show_name" or not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        show_name_val = int(data.split(":")[4])  # 1 or 0
        sd = state_data(uid)
        state_set(uid, "admin_add_package_volume",
                  type_id=sd["type_id"], package_name=sd["package_name"],
                  show_name=show_name_val)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔋 حجم پکیج را به گیگ وارد کنید:\n"
            "💡 برای حجم نامحدود عدد <b>0</b> بفرستید.\n"
            "💡 برای کمتر از ۱ گیگ اعشار وارد کنید (مثلاً <b>0.5</b>).",
            back_button("admin:types"))
        return

    if data.startswith("admin:pkg:add:br:"):
        # step: admin selects buyer_role during package creation
        if state_name(uid) != "admin_add_package_buyer_role" or not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        buyer_role = data.split(":")[4]  # 'all' | 'agents' | 'public' | 'nobody'
        if buyer_role not in ("all", "agents", "public", "nobody"):
            bot.answer_callback_query(call.id)
            return
        sd = state_data(uid)
        state_set(uid, "admin_add_package_config_source",
                  type_id=sd["type_id"], package_name=sd["package_name"],
                  volume=sd["volume"], duration=sd["duration"],
                  price=sd["price"], show_name=sd.get("show_name", 1),
                  max_users=int(sd.get("max_users", 0) or 0),
                  buyer_role=buyer_role)
        bot.answer_callback_query(call.id)
        kb_cs = types.InlineKeyboardMarkup()
        kb_cs.row(
            types.InlineKeyboardButton("✏️ ثبت دستی",    callback_data="admin:pkg:add:cs:manual"),
            types.InlineKeyboardButton("🔌 اتصال به پنل", callback_data="admin:pkg:add:cs:panel"),
        )
        send_or_edit(call,
            "🔌 <b>منبع کانفیگ</b>\n\n"
            "کانفیگ‌های این پکیج چطور تامین می‌شوند?\n\n"
            "• <b>ثبت دستی</b> — کانفیگ را از بخش موجودی آپلود کنید\n"
            "• <b>اتصال به پنل</b> — پس از خرید، کانفیگ به‌صورت خودکار در پنل ساخته می‌شود",
            kb_cs)
        return

    if data == "admin:pkg:add:cs:manual":
        if state_name(uid) != "admin_add_package_config_source" or not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        sd = state_data(uid)
        show_name_val = sd.get("show_name", 1)
        max_users     = int(sd.get("max_users", 0) or 0)
        buyer_role    = sd.get("buyer_role", "all")
        pkg_id = add_package(sd["type_id"], sd["package_name"], sd["volume"], sd["duration"], sd["price"],
                             show_name=show_name_val, max_users=max_users, buyer_role=buyer_role)
        update_package_panel_settings(pkg_id, "manual")
        log_admin_action(uid, f"پکیج '{sd['package_name']}' (دستی) ثبت شد")
        state_clear(uid)
        _br_labels = {"all": "همه", "agents": "فقط نمایندگان", "public": "فقط کاربران عادی", "nobody": "هیچ‌کس (فقط هدیه)"}
        vol_label = "حجم نامحدود" if sd["volume"] == 0 else fmt_vol(sd["volume"])
        dur_label = "زمان نامحدود" if sd["duration"] == 0 else f"{sd['duration']} روز"
        pri_label = "رایگان" if sd["price"] == 0 else f"{fmt_price(sd['price'])} تومان"
        bot.answer_callback_query(call.id, "✅ پکیج ثبت شد.")
        send_or_edit(call,
            f"✅ پکیج دستی با موفقیت ثبت شد.\n\n"
            f"📦 <b>{esc(sd['package_name'])}</b>\n"
            f"🔋 حجم: {vol_label}\n"
            f"⏰ مدت: {dur_label}\n"
            f"💰 قیمت: {pri_label}\n"
            f"🔑 خریداران: {_br_labels.get(buyer_role, buyer_role)}\n"
            f"📂 منبع: ثبت دستی",
            back_button("admin:types"))
        return

    if data == "admin:pkg:add:cs:panel":
        if state_name(uid) != "admin_add_package_config_source" or not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        panels = get_all_panels()
        if not panels:
            bot.answer_callback_query(call.id, "هیچ پنلی ثبت نشده است. ابتدا یک پنل اضافه کنید.", show_alert=True)
            return
        sd = state_data(uid)
        state_set(uid, "admin_add_package_panel", **{k: v for k, v in sd.items()})
        kb_pnl = types.InlineKeyboardMarkup()
        for p in panels:
            icon = "🟢" if p["connection_status"] == "connected" else "🔴"
            kb_pnl.add(types.InlineKeyboardButton(f"{icon} {p['name']}", callback_data=f"admin:pkg:add:pnl:{p['id']}"))
        kb_pnl.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:types",
                                               icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🖥 پنلی را که کانفیگ‌های این پکیج روی آن ساخته می‌شوند انتخاب کنید:", kb_pnl)
        return

    if data.startswith("admin:pkg:add:pnl:"):
        if state_name(uid) != "admin_add_package_panel" or not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        panel_id = int(data.split(":")[4])
        panel    = get_panel(panel_id)
        if not panel:
            bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
            return
        # Show client packages for this panel
        cpkgs = get_panel_client_packages(panel_id)
        if not cpkgs:
            bot.answer_callback_query(call.id,
                "این پنل هیچ کلاینت پکیجی ندارد.\n"
                "ابتدا از مدیریت پنل → کلاینت پکیج‌ها یک کلاینت پکیج اضافه کنید.",
                show_alert=True)
            return
        _DM = {"config_only": "📄 کانفیگ", "sub_only": "🔗 ساب", "both": "📄+🔗 هر دو"}
        sd = state_data(uid)
        state_set(uid, "admin_add_package_cpkg_select", panel_id=panel_id,
                  **{k: v for k, v in sd.items() if k != "panel_id"})
        kb_cp = types.InlineKeyboardMarkup()
        for cp in cpkgs:
            name = cp["name"] or f"اینباند #{cp['inbound_id']}"
            dm_label = _DM.get(cp["delivery_mode"], cp["delivery_mode"])
            kb_cp.add(types.InlineKeyboardButton(
                f"🔹 {name}  ({dm_label})",
                callback_data=f"admin:pkg:add:cpkg:{cp['id']}",
            ))
        kb_cp.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:types",
                                              icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📦 پنل: <b>{esc(panel['name'])}</b>\n\n"
            "یک <b>کلاینت پکیج</b> را انتخاب کنید:",
            kb_cp)
        return

    if data.startswith("admin:pkg:add:cpkg:"):
        # Client package selected during new package add flow
        if state_name(uid) != "admin_add_package_cpkg_select" or not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        cpkg_id = int(data.split(":")[4])
        cp = get_panel_client_package(cpkg_id)
        if not cp:
            bot.answer_callback_query(call.id, "کلاینت پکیج یافت نشد.", show_alert=True)
            return
        sd = state_data(uid)
        show_name_val = sd.get("show_name", 1)
        max_users     = int(sd.get("max_users", 0) or 0)
        buyer_role    = sd.get("buyer_role", "all")
        pkg_id = add_package(sd["type_id"], sd["package_name"], sd["volume"], sd["duration"], sd["price"],
                             show_name=show_name_val, max_users=max_users, buyer_role=buyer_role)
        update_package_panel_settings(pkg_id, "panel",
                                       panel_id=cp["panel_id"],
                                       panel_type="sanaei",
                                       panel_port=cp["inbound_id"],
                                       delivery_mode=cp["delivery_mode"],
                                       client_package_id=cpkg_id)
        log_admin_action(uid, f"پکیج پنلی '{sd['package_name']}' با کلاینت پکیج #{cpkg_id} ثبت شد")
        state_clear(uid)
        _DM_LABELS = {"config_only": "فقط کانفیگ", "sub_only": "فقط ساب", "both": "کانفیگ + ساب"}
        bot.answer_callback_query(call.id, "✅ پکیج ثبت شد.")
        send_or_edit(call,
            f"✅ پکیج پنلی با موفقیت ثبت شد.\n\n"
            f"📦 <b>{esc(sd['package_name'])}</b>\n"
            f"🔋 حجم: {'نامحدود' if sd['volume'] == 0 else fmt_vol(sd['volume'])}\n"
            f"⏰ مدت: {'نامحدود' if sd['duration'] == 0 else str(sd['duration']) + ' روز'}\n"
            f"💰 قیمت: {'رایگان' if sd['price'] == 0 else fmt_price(sd['price']) + ' تومان'}\n"
            f"📦 کلاینت پکیج: {cp['name'] or 'اینباند #' + str(cp['inbound_id'])}\n"
            f"📤 تحویل: {_DM_LABELS[cp['delivery_mode']]}",
            back_button("admin:types"))
        return



    if data.startswith("admin:pkg:edit:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        show_name_val = package_row['show_name'] if 'show_name' in package_row.keys() else 1
        bot.answer_callback_query(call.id)
        text, kb = _pkg_edit_text_kb(package_row)
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pkg:toggle_sn:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        cur_sn  = package_row['show_name'] if 'show_name' in package_row.keys() else 1
        new_sn  = 0 if cur_sn else 1
        update_package_field(package_id, "show_name", new_sn)
        log_admin_action(uid, f"نمایش نام پکیج #{package_id} {'فعال' if new_sn else 'غیرفعال'} شد")
        bot.answer_callback_query(call.id, "✅ تنظیم نمایش نام بروزرسانی شد.")
        package_row = get_package(package_id)
        text, kb = _pkg_edit_text_kb(package_row)
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pkg:set_br:"):
        # Show buyer_role selection for a package
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        buyer_role = package_row["buyer_role"] if "buyer_role" in package_row.keys() else "all"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ همه"               if buyer_role == "all"     else "همه",
                                       callback_data=f"admin:pkg:br:all:{package_id}"),
            types.InlineKeyboardButton("✅ فقط نمایندگان"     if buyer_role == "agents"  else "فقط نمایندگان",
                                       callback_data=f"admin:pkg:br:agents:{package_id}"),
            types.InlineKeyboardButton("✅ فقط کاربران عادی"  if buyer_role == "public"  else "فقط کاربران عادی",
                                       callback_data=f"admin:pkg:br:public:{package_id}"),
        )
        kb.add(types.InlineKeyboardButton("✅ هیچ‌کس (فقط هدیه)" if buyer_role == "nobody" else "هیچ‌کس (فقط هدیه)",
                                          callback_data=f"admin:pkg:br:nobody:{package_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"admin:pkg:edit:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📦 <b>{esc(package_row['name'])}</b>\n\n"
            "👥 چه کسانی بتوانند این پکیج را بخرند؟\n\n"
            "• <b>همه</b> — هم کاربران عادی، هم نمایندگان\n"
            "• <b>فقط نمایندگان</b> — فقط کاربران نماینده\n"
            "• <b>فقط کاربران عادی</b> — فقط کاربران غیرنماینده\n"
            "• <b>هیچ‌کس</b> — پکیج در خرید عادی نمایش داده نمی‌شود، فقط برای تحویل هدیه", kb)
        return

    if data.startswith("admin:pkg:br:"):
        # Admin selects buyer_role for existing package
        parts      = data.split(":")
        role       = parts[3]   # 'all' | 'agents' | 'public' | 'nobody'
        package_id = int(parts[4])
        if role not in ("all", "agents", "public", "nobody"):
            bot.answer_callback_query(call.id)
            return
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        update_package_field(package_id, "buyer_role", role)
        log_admin_action(uid, f"buyer_role پکیج #{package_id} به {role} تغییر کرد")
        bot.answer_callback_query(call.id, "✅ محدودیت خریدار بروزرسانی شد.")
        package_row = get_package(package_id)
        text, kb = _pkg_edit_text_kb(package_row)
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pkg:ef:"):
        parts      = data.split(":")
        field_key  = parts[3]
        package_id = int(parts[4])
        state_set(uid, "admin_edit_pkg_field", field_key=field_key, package_id=package_id)
        labels     = {"name": "نام", "price": "قیمت (تومان)", "volume": "حجم (GB)", "dur": "مدت (روز)", "position": "جایگاه نمایش", "maxusers": "محدودیت کاربر (0=نامحدود)"}
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"✏️ مقدار جدید برای <b>{labels.get(field_key, field_key)}</b> را وارد کنید:",
                     back_button("admin:types"))
        return

    if data.startswith("admin:pkg:del:"):
        package_id = int(data.split(":")[3])
        with get_conn() as conn:
            sold_count = conn.execute(
                "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND sold_to IS NOT NULL",
                (package_id,)
            ).fetchone()["n"]
            if sold_count > 0:
                bot.answer_callback_query(call.id, f"❌ این پکیج {sold_count} کانفیگ فروخته‌شده دارد و قابل حذف نیست.", show_alert=True)
                return
            unsold_cfg = conn.execute(
                "SELECT COUNT(*) AS n FROM configs WHERE package_id=?",
                (package_id,)
            ).fetchone()["n"]
        if unsold_cfg > 0:
            kb_c = types.InlineKeyboardMarkup()
            kb_c.row(
                types.InlineKeyboardButton("✅ بله، حذف شود", callback_data=f"admin:pkg:delok:{package_id}"),
                types.InlineKeyboardButton("❌ انصراف", callback_data="admin:types"),
            )
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"⚠️ <b>تأیید حذف پکیج</b>\n\n"
                f"{unsold_cfg} کانفیگ موجود/منقضی همراه با پکیج حذف خواهند شد.\n"
                "آیا مطمئن هستید؟", kb_c)
            return
        delete_package(package_id)
        bot.answer_callback_query(call.id, "✅ پکیج حذف شد.")
        log_admin_action(uid, f"پکیج #{package_id} حذف شد")
        _show_admin_types(call)
        return

    if data.startswith("admin:pkg:delok:"):
        package_id = int(data.split(":")[3])
        with get_conn() as conn:
            sold_count = conn.execute(
                "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND sold_to IS NOT NULL",
                (package_id,)
            ).fetchone()["n"]
        if sold_count > 0:
            bot.answer_callback_query(call.id, "❌ در این فاصله کانفیگ فروخته شد. حذف ممکن نیست.", show_alert=True)
            _show_admin_types(call)
            return
        delete_package(package_id)
        bot.answer_callback_query(call.id, "✅ پکیج و کانفیگ‌های آن حذف شدند.")
        log_admin_action(uid, f"پکیج #{package_id} با کانفیگ‌ها حذف شد")
        _show_admin_types(call)
        return

    # ── Admin: Package config_source edit ─────────────────────────────────────
    if data.startswith("admin:pkg:src:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row or not is_admin(uid):
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        try:
            config_source = package_row["config_source"] or "manual"
        except (IndexError, KeyError):
            config_source = "manual"
        kb_src = types.InlineKeyboardMarkup()
        kb_src.row(
            types.InlineKeyboardButton(
                "✅ ثبت دستی" if config_source == "manual" else "ثبت دستی",
                callback_data=f"admin:pkg:scs:manual:{package_id}"),
            types.InlineKeyboardButton(
                "✅ اتصال به پنل" if config_source == "panel" else "اتصال به پنل",
                callback_data=f"admin:pkg:scs:panel:{package_id}"),
        )
        kb_src.add(types.InlineKeyboardButton("بازگشت", callback_data=f"admin:pkg:edit:{package_id}",
                                              icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📦 <b>{esc(package_row['name'])}</b>\n\n"
            "🔌 منبع کانفیگ این پکیج را انتخاب کنید:", kb_src)
        return

    if data.startswith("admin:pkg:scs:manual:"):
        package_id = int(data.split(":")[4])
        if not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        package_row = get_package(package_id)
        # Preserve existing delivery_mode so NOT NULL constraint is not violated
        existing_delivery_mode = (package_row["delivery_mode"] if package_row else None) or "config_only"
        update_package_panel_settings(package_id, "manual", delivery_mode=existing_delivery_mode)
        log_admin_action(uid, f"پکیج #{package_id} منبع کانفیگ به دستی تغییر کرد")
        bot.answer_callback_query(call.id, "✅ منبع کانفیگ به دستی تغییر کرد.")
        package_row = get_package(package_id)
        text, kb = _pkg_edit_text_kb(package_row)
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pkg:scs:panel:"):
        package_id = int(data.split(":")[4])
        if not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        panels = get_all_panels()
        if not panels:
            bot.answer_callback_query(call.id, "هیچ پنلی ثبت نشده است.", show_alert=True)
            return
        state_set(uid, "admin_edit_pkg_panel_select", package_id=package_id)
        kb_pnl = types.InlineKeyboardMarkup()
        for p in panels:
            icon = "🟢" if p["connection_status"] == "connected" else "🔴"
            kb_pnl.add(types.InlineKeyboardButton(f"{icon} {p['name']}", callback_data=f"admin:pkg:spnl:{p['id']}:{package_id}"))
        kb_pnl.add(types.InlineKeyboardButton("بازگشت", callback_data=f"admin:pkg:src:{package_id}",
                                               icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🖥 پنل مقصد را انتخاب کنید:", kb_pnl)
        return

    if data.startswith("admin:pkg:spnl:"):
        parts      = data.split(":")
        panel_id   = int(parts[3])
        package_id = int(parts[4])
        if not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        panel = get_panel(panel_id)
        if not panel:
            bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
            return
        # Show client packages for this panel
        cpkgs = get_panel_client_packages(panel_id)
        if not cpkgs:
            bot.answer_callback_query(call.id,
                "این پنل هیچ کلاینت پکیجی ندارد.\n"
                "ابتدا از مدیریت پنل → کلاینت پکیج‌ها یک کلاینت پکیج اضافه کنید.",
                show_alert=True)
            return
        _DM = {"config_only": "📄 کانفیگ", "sub_only": "🔗 ساب", "both": "📄+🔗 هر دو"}
        kb_cp = types.InlineKeyboardMarkup()
        for cp in cpkgs:
            name = cp["name"] or f"اینباند #{cp['inbound_id']}"
            dm_label = _DM.get(cp["delivery_mode"], cp["delivery_mode"])
            kb_cp.add(types.InlineKeyboardButton(
                f"🔹 {name}  ({dm_label})",
                callback_data=f"admin:pkg:cpkg:{cp['id']}:{package_id}",
            ))
        kb_cp.add(types.InlineKeyboardButton("بازگشت", callback_data=f"admin:pkg:src:{package_id}",
                                              icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📦 پنل: <b>{esc(panel['name'])}</b>\n\n"
            "یک <b>کلاینت پکیج</b> را انتخاب کنید:\n"
            "<i>(هر کلاینت پکیج = اینباند + نوع تحویل + قالب کانفیگ)</i>",
            kb_cp)
        return

    if data.startswith("admin:pkg:cpkg:"):
        # Client package selected for a package
        parts      = data.split(":")
        cpkg_id    = int(parts[3])
        package_id = int(parts[4])
        if not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        cp = get_panel_client_package(cpkg_id)
        if not cp:
            bot.answer_callback_query(call.id, "کلاینت پکیج یافت نشد.", show_alert=True)
            return
        update_package_panel_settings(
            package_id, "panel",
            panel_id=cp["panel_id"],
            panel_type="sanaei",
            panel_port=cp["inbound_id"],
            delivery_mode=cp["delivery_mode"],
            client_package_id=cpkg_id,
        )
        log_admin_action(uid, f"پکیج #{package_id} به کلاینت پکیج #{cpkg_id} (پنل #{cp['panel_id']}) متصل شد")
        state_clear(uid)
        bot.answer_callback_query(call.id, "✅ اتصال پنل تنظیم شد.")
        package_row = get_package(package_id)
        text, kb = _pkg_edit_text_kb(package_row)
        send_or_edit(call, text, kb)
        return



    # ── Admin: Panel Configs list ──────────────────────────────────────────────
    if data == "admin:panel_configs":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        from ..admin.renderers import _show_panel_configs
        _show_panel_configs(call)
        return

    if data.startswith("admin:pcfg:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        from ..admin.renderers import (
            _show_panel_configs, _show_panel_config_list,
            _show_panel_config_pkg, _show_panel_config_detail,
        )
        from ..db import (
            get_panel_config, get_panel_config_full,
            update_panel_config_field,
            delete_panel_config,
        )
        bot.answer_callback_query(call.id)

        if data == "admin:pcfg:search":
            state_set(uid, "admin_pcfg_search")
            send_or_edit(call,
                "🔍 عبارت جستجو را وارد کنید:\n"
                "(نام کلاینت، نام پکیج، لینک کانفیگ یا لینک ساب)",
                back_button("admin:panel_configs"))
            return

        # admin:pcfg:fl:{filter_type}:{page}[:{package_id}]
        if data.startswith("admin:pcfg:fl:"):
            parts      = data.split(":")
            flt        = parts[3]
            page       = int(parts[4]) if len(parts) > 4 else 0
            pkg_id     = int(parts[5]) if len(parts) > 5 else None
            _show_panel_config_list(call, filter_type=flt, package_id=pkg_id, page=page)
            return

        # admin:pcfg:pkg:{package_id}
        if data.startswith("admin:pcfg:pkg:"):
            package_id = int(data.split(":")[-1])
            _show_panel_config_pkg(call, package_id)
            return

        # admin:pcfg:d:{config_id}  — detail view
        if data.startswith("admin:pcfg:d:"):
            config_id = int(data.split(":")[-1])
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:qrc:{config_id}  — QR for config
        if data.startswith("admin:pcfg:qrc:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if cfg and cfg["client_config_text"]:
                try:
                    import qrcode as _qrcode
                    from io import BytesIO
                    qr_img = _qrcode.make(cfg["client_config_text"])
                    bio = BytesIO(); qr_img.save(bio, format="PNG"); bio.seek(0)
                    bio.name = "qr_config.png"
                    bot.send_photo(uid, bio, caption="📷 QR کانفیگ")
                except Exception as e:
                    bot.send_message(uid, f"خطا در QR: {e}")
            else:
                bot.answer_callback_query(call.id, "کانفیگ موجود نیست.", show_alert=True)
            return

        # admin:pcfg:qrs:{config_id}  — QR for subscription
        if data.startswith("admin:pcfg:qrs:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if cfg and cfg["client_sub_url"]:
                try:
                    import qrcode as _qrcode
                    from io import BytesIO
                    qr_img = _qrcode.make(cfg["client_sub_url"])
                    bio = BytesIO(); qr_img.save(bio, format="PNG"); bio.seek(0)
                    bio.name = "qr_sub.png"
                    bot.send_photo(uid, bio, caption="📷 QR سابسکرایب")
                except Exception as e:
                    bot.send_message(uid, f"خطا در QR: {e}")
            else:
                bot.answer_callback_query(call.id, "لینک ساب موجود نیست.", show_alert=True)
            return

        # admin:pcfg:autorenew:{config_id}  — toggle auto-renew
        if data.startswith("admin:pcfg:autorenew:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True); return
            new_val = 0 if int(cfg["auto_renew"] or 0) else 1
            update_panel_config_field(config_id, "auto_renew", new_val)
            label = "فعال" if new_val else "غیرفعال"
            bot.answer_callback_query(call.id, f"تمدید خودکار {label} شد.")
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:toggle:{config_id}  — enable/disable on panel
        if data.startswith("admin:pcfg:toggle:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            if not panel:
                bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True); return
            cur_disabled = int(cfg.get("is_disabled") or 0)
            send_or_edit(call, "⏳ در حال ارتباط با پنل…")
            from ..panels.client import PanelClient
            pc_api = PanelClient(
                protocol=panel["protocol"], host=panel["host"], port=panel["port"],
                path=panel["path"] or "", username=panel["username"], password=panel["password"]
            )
            if cur_disabled:
                ok, err = pc_api.enable_client(
                    inbound_id=cfg["inbound_id"], client_uuid=cfg["client_uuid"],
                    email=cfg["client_name"] or "", traffic_bytes=0, expire_ms=0,
                )
                if ok:
                    update_panel_config_field(config_id, "is_disabled", 0)
                else:
                    send_or_edit(call, f"❌ خطا در فعال‌سازی:\n<code>{esc(str(err))}</code>",
                                 back_button(f"admin:pcfg:d:{config_id}")); return
            else:
                ok, err = pc_api.disable_client(
                    inbound_id=cfg["inbound_id"], client_uuid=cfg["client_uuid"],
                    email=cfg["client_name"] or "", traffic_bytes=0, expire_ms=0,
                )
                if ok:
                    update_panel_config_field(config_id, "is_disabled", 1)
                else:
                    send_or_edit(call, f"❌ خطا در غیرفعال‌سازی:\n<code>{esc(str(err))}</code>",
                                 back_button(f"admin:pcfg:d:{config_id}")); return
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:rsub:{config_id}  — regenerate subscription link
        if data.startswith("admin:pcfg:rsub:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            cpkg = get_panel_client_package(cfg["cpkg_id"]) if cfg.get("cpkg_id") else None
            if not cpkg or not cfg.get("client_uuid"):
                bot.answer_callback_query(call.id, "اطلاعات قالب کانفیگ ناقص است.", show_alert=True); return
            import uuid as _uuid
            new_sub_id = str(_uuid.uuid4()).replace("-", "")[:16]
            cpkg_d = dict(cpkg)
            new_sub_url = _build_sub_from_template(cpkg_d, new_sub_id) if cpkg_d.get("sample_sub_url") else None
            if not new_sub_url:
                bot.answer_callback_query(call.id, "قالب ساب در cpkg تنظیم نشده.", show_alert=True); return
            # Update panel
            if panel:
                send_or_edit(call, "⏳ در حال ارتباط با پنل…")
                from ..panels.client import PanelClient
                pc_api = PanelClient(
                    protocol=panel["protocol"], host=panel["host"], port=panel["port"],
                    path=panel["path"] or "", username=panel["username"], password=panel["password"]
                )
                ok_sub, err_sub = pc_api.update_client_sub(
                    inbound_id=cfg["inbound_id"], client_uuid=cfg["client_uuid"],
                    email=cfg["client_name"] or "", new_sub_id=new_sub_id,
                )
                if not ok_sub:
                    send_or_edit(call, f"❌ خطا در بروزرسانی ساب روی پنل:\n<code>{esc(str(err_sub))}</code>",
                                 back_button(f"admin:pcfg:d:{config_id}")); return
            # Save to DB
            update_panel_config_texts(config_id, cfg["client_config_text"], new_sub_url)
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:ruuid:{config_id}  — regenerate UUID / config
        if data.startswith("admin:pcfg:ruuid:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            cpkg = get_panel_client_package(cfg["cpkg_id"]) if cfg.get("cpkg_id") else None
            if not cpkg or not panel:
                bot.answer_callback_query(call.id, "اطلاعات قالب یا پنل ناقص.", show_alert=True); return
            cpkg_d = dict(cpkg)
            import uuid as _uuid
            new_uuid   = str(_uuid.uuid4())
            new_sub_id = new_uuid.replace("-", "")[:16]
            new_sub    = _build_sub_from_template(cpkg_d, new_sub_id) if cpkg_d.get("sample_sub_url") else cfg["client_sub_url"]
            send_or_edit(call, "⏳ در حال ارتباط با پنل…")
            from ..panels.client import PanelClient
            pc_api = PanelClient(
                protocol=panel["protocol"], host=panel["host"], port=panel["port"],
                path=panel["path"] or "", username=panel["username"], password=panel["password"]
            )
            # Get current client data from panel to preserve totalGB and expiryTime
            import time as _time
            exp_ms     = 0
            traffic_gb = 0
            ok_td, td = pc_api.get_client_traffics(cfg["client_name"] or "")
            if ok_td and td:
                exp_ms     = int(td.get("expiryTime") or 0)
                total_b    = int(td.get("total") or 0)
                traffic_gb = int(total_b / (1024 ** 3)) if total_b > 0 else 0
            else:
                # Fallback to DB expire_at
                if cfg.get("expire_at"):
                    try:
                        exp_dt = datetime.strptime(str(cfg["expire_at"])[:19], "%Y-%m-%d %H:%M:%S")
                        exp_ms = int(exp_dt.timestamp() * 1000)
                    except Exception:
                        pass
            # Delete old client from panel
            pc_api.delete_client(
                inbound_id=cfg["inbound_id"], client_uuid=cfg["client_uuid"],
            )
            # Create new client with same traffic/expiry settings
            ok, res = pc_api.create_client(
                inbound_id=cfg["inbound_id"], email=cfg["client_name"] or "",
                traffic_bytes=traffic_gb * (1024 ** 3), expire_ms=exp_ms,
            )
            if not ok:
                send_or_edit(call, f"❌ خطا در ساخت کلاینت جدید:\n<code>{esc(str(res))}</code>",
                             back_button(f"admin:pcfg:d:{config_id}")); return
            actual_uuid, actual_sub_id = res
            # If we have a sub template, rebuild sub with new sub_id; otherwise keep old
            if cpkg_d.get("sample_sub_url"):
                actual_sub = _build_sub_from_template(cpkg_d, actual_sub_id) or new_sub
            else:
                actual_sub = cfg["client_sub_url"] or ""
            actual_config = _build_config_from_template(cpkg_d, actual_uuid, cfg["client_name"] or "")
            # Update DB
            update_panel_config_field(config_id, "client_uuid", actual_uuid)
            update_panel_config_texts(config_id, actual_config or "", actual_sub)
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:renew:{config_id}  — manual renew: show package list
        if data.startswith("admin:pcfg:renew:") and not data.startswith("admin:pcfg:renewok:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config_full(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True); return
            cfg = dict(cfg)
            type_id = cfg.get("type_id")
            pkgs = [p for p in (get_packages(type_id=type_id, include_inactive=False) or []) if p["active"]]
            if not pkgs:
                bot.answer_callback_query(call.id, "پکیج سازگار یافت نشد.", show_alert=True); return
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup()
            for p in pkgs:
                kb.add(InlineKeyboardButton(
                    f"📦 {esc(p['name'])} | {fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(p['price'])}ت",
                    callback_data=f"admin:pcfg:renewok:{config_id}:{p['id']}"
                ))
            kb.add(InlineKeyboardButton("لغو", callback_data=f"admin:pcfg:d:{config_id}",
                                        icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call, f"📦 پکیج مورد نظر برای تمدید را انتخاب کنید:", kb)
            return

        # admin:pcfg:renewok:{config_id}:{package_id}
        if data.startswith("admin:pcfg:renewok:"):
            parts     = data.split(":")
            config_id = int(parts[3])
            pkg_id    = int(parts[4])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True); return
            pkg = get_package(pkg_id)
            if not pkg:
                bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            if not panel:
                bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True); return
            send_or_edit(call, "⏳ در حال تمدید روی پنل…")
            from ..panels.client import PanelClient
            pc_api = PanelClient(
                protocol=panel["protocol"], host=panel["host"], port=panel["port"],
                path=panel["path"] or "", username=panel["username"], password=panel["password"]
            )
            # Reset traffic
            pc_api.reset_client_traffic(cfg["inbound_id"], cfg["client_name"] or "")
            # Calculate new expiry
            dur_days = int(pkg["duration_days"] or 0)
            if dur_days:
                new_exp_dt = datetime.utcnow() + timedelta(days=dur_days)
                new_exp_str = new_exp_dt.strftime("%Y-%m-%d %H:%M:%S")
                new_exp_ms  = int(new_exp_dt.timestamp() * 1000)
            else:
                new_exp_str = None
                new_exp_ms  = 0
            # Update on panel: set new expiryTime + re-enable
            ok_renew, err_renew = pc_api.enable_client(
                inbound_id=cfg["inbound_id"], client_uuid=cfg["client_uuid"],
                email=cfg["client_name"] or "",
                traffic_bytes=int((pkg["volume_gb"] or 0) * 1073741824),
                expire_ms=new_exp_ms,
            )
            if not ok_renew:
                send_or_edit(call, f"❌ خطا در بروزرسانی پنل:\n<code>{esc(str(err_renew))}</code>",
                             back_button(f"admin:pcfg:d:{config_id}")); return
            # Update DB
            update_panel_config_field(config_id, "expire_at",  new_exp_str)
            update_panel_config_field(config_id, "is_expired",  0)
            update_panel_config_field(config_id, "is_disabled", 0)
            update_panel_config_field(config_id, "package_id",  pkg_id)
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:del:{config_id}  — confirm deletion
        if data.startswith("admin:pcfg:del:") and not data.startswith("admin:pcfg:delok:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True); return
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup()
            kb.row(
                InlineKeyboardButton("✅ بله، حذف کن",  callback_data=f"admin:pcfg:delok:{config_id}"),
                InlineKeyboardButton("❌ لغو",           callback_data=f"admin:pcfg:d:{config_id}"),
            )
            send_or_edit(call,
                "⚠️ <b>تأیید حذف کانفیگ</b>\n\n"
                "این کانفیگ به صورت <b>دائمی</b> حذف می‌شود.\n"
                "سرویس قابل تمدید نخواهد بود و هیچ مبلغی برگشت داده نمی‌شود.\n\n"
                "آیا مطمئن هستید؟", kb)
            return

        # admin:pcfg:delok:{config_id}
        if data.startswith("admin:pcfg:delok:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True); return
            # Delete from panel
            panel = get_panel(cfg["panel_id"])
            if panel and cfg.get("client_uuid"):
                send_or_edit(call, "\u23f3 \u062f\u0631 \u062d\u0627\u0644 \u062d\u0630\u0641 \u0627\u0632 \u067e\u0646\u0644\u2026")
                try:
                    from ..panels.client import PanelClient
                    pc_api = PanelClient(
                        protocol=panel["protocol"], host=panel["host"], port=panel["port"],
                        path=panel["path"] or "", username=panel["username"], password=panel["password"]
                    )
                    pc_api.delete_client(cfg["inbound_id"], cfg["client_uuid"])
                except Exception:
                    pass
            # Delete from DB
            delete_panel_config(config_id)
            _show_panel_configs(call)
            return

        # Legacy compat: admin:pcfg:f:* (old filter pattern)
        if data.startswith("admin:pcfg:f:"):
            parts = data.split(":")
            flt   = parts[3]
            page  = int(parts[4]) if len(parts) > 4 else 0
            _show_panel_config_list(call, filter_type=flt, page=page)
            return

        # Legacy compat: admin:pcfg:pg:* (old pagination)
        if data.startswith("admin:pcfg:pg:"):
            parts = data.split(":")
            page  = int(parts[3])
            flt   = parts[4] if len(parts) > 4 else "all"
            _show_panel_config_list(call, filter_type=flt, page=page)
            return

        if data == "admin:pcfg:noop":
            return

        return

    # ── User: My Panel Configs ─────────────────────────────────────────────────
    if data.startswith("mypnlcfg:") or data.startswith("mypnlcfgrpay:"):
        from ..db import (
            get_panel_config, update_panel_config_field,
        )
        from ..admin.renderers import _show_panel_config_detail

        # mypnlcfg:d:{config_id}
        if data.startswith("mypnlcfg:d:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            bot.answer_callback_query(call.id)
            _show_panel_config_detail(call, config_id, back_data="my_configs",
                                      is_user_view=True)
            return

        # mypnlcfg:renewconfirm:{config_id}  — show package list for panel config renewal
        if data.startswith("mypnlcfg:renewconfirm:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            cfg = dict(cfg)
            # Find packages of same type
            with get_conn() as conn:
                type_row = conn.execute(
                    "SELECT type_id FROM packages WHERE id=?", (cfg.get("package_id") or 0,)
                ).fetchone()
            type_id = type_row["type_id"] if type_row else None
            user = get_user(uid)
            _is_agent = bool(user and user["is_agent"])
            packages = [p for p in get_packages(type_id=type_id) if p["price"] > 0 and _br_ok(p, _is_agent)] if type_id else []
            kb = types.InlineKeyboardMarkup()
            for p in packages:
                price = get_effective_price(uid, p)
                _sn = p['show_name'] if 'show_name' in p.keys() else 1
                _name_part = f"{p['name']} | " if _sn else ""
                title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)} ت"
                kb.add(types.InlineKeyboardButton(title, callback_data=f"mypnlcfg:renewp:{config_id}:{p['id']}"))
            kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"mypnlcfg:d:{config_id}",
                   icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            agent_note = "\n\n🤝 <i>این قیمت‌ها مخصوص همکاری شماست</i>" if user and user["is_agent"] else ""
            if not packages:
                send_or_edit(call, "📭 در حال حاضر پکیجی برای تمدید موجود نیست.", kb)
            else:
                send_or_edit(call,
                    "⚡ <b>تمدید سرویس</b>\n\n"
                    "پکیج مورد نظر برای تمدید را انتخاب کنید:"
                    f"{agent_note}", kb)
            return

        # mypnlcfg:renewp:{config_id}:{package_id}  — show payment gateways for selected package
        if data.startswith("mypnlcfg:renewp:"):
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            cfg = dict(cfg)
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True); return
            price = get_effective_price(uid, package_row)
            state_set(uid, "pnlcfg_renew_select_method",
                      config_id=config_id, package_id=package_id,
                      amount=price, original_amount=price, kind="pnlcfg_renewal")
            bot.answer_callback_query(call.id)
            _show_pnlcfg_renewal_gateways(call, uid, config_id, package_id, price, package_row, cfg)
            return

        # ── Panel config renewal payment handlers ─────────────────────────────

        # mypnlcfgrpay:wallet:{config_id}:{package_id}
        if data.startswith("mypnlcfgrpay:wallet:"):
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True); return
            user = get_user(uid)
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if user["balance"] < price:
                bot.answer_callback_query(call.id, "موجودی کیف پول کافی نیست.", show_alert=True); return
            update_balance(uid, -price)
            create_payment("pnlcfg_renewal", uid, package_id, price, "wallet",
                           status="completed", config_id=config_id)
            bot.answer_callback_query(call.id, "⏳ در حال تمدید…")
            ok_r, err_r = _execute_pnlcfg_renewal(config_id, package_id, chat_id=uid, uid=uid)
            state_clear(uid)
            if not ok_r:
                send_or_edit(call, "❌ تمدید سرویس با خطا مواجه شد.\nلطفاً با پشتیبانی ارتباط بگیرید.",
                             back_button("my_configs"))
                return
            _show_panel_config_detail(call, config_id, back_data="my_configs", is_user_view=True)
            return

        # mypnlcfgrpay:card:{config_id}:{package_id}
        if data.startswith("mypnlcfgrpay:card:"):
            if not _check_invoice_valid(uid):
                _show_invoice_expired(call); return
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True); return
            _ci = pick_card_for_payment()
            if not _ci:
                bot.answer_callback_query(call.id, "اطلاعات پرداخت هنوز ثبت نشده است.", show_alert=True); return
            card, bank, owner = _ci["card_number"], _ci["bank_name"], _ci["holder_name"]
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            price = apply_gateway_fee("card", price)
            if not is_gateway_in_range("card", price):
                _rng = get_gateway_range_text("card")
                bot.answer_callback_query(call.id,
                    f"⛔️ مبلغ {fmt_price(price)} تومان برای این درگاه مجاز نیست.\n"
                    f"محدوده مجاز: {_rng}\n\nلطفاً درگاه دیگری انتخاب کنید.",
                    show_alert=True); return
            payment_id = create_payment("pnlcfg_renewal", uid, package_id, price, "card",
                                        status="pending", config_id=config_id)
            final_amount = None
            if setting_get("gw_card_random_amount", "0") == "1":
                final_amount = _generate_card_final_amount(price, payment_id)
                update_payment_final_amount(payment_id, final_amount)
            state_set(uid, "await_renewal_receipt", payment_id=payment_id, config_id=config_id)
            text, kb = _build_card_payment_page(card, bank, owner, price, final_amount)
            bot.answer_callback_query(call.id)
            send_or_edit(call, text, kb)
            return

        # mypnlcfgrpay:crypto:{config_id}:{package_id}
        if data.startswith("mypnlcfgrpay:crypto:"):
            if not _check_invoice_valid(uid):
                _show_invoice_expired(call); return
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True); return
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if not is_gateway_in_range("crypto", price):
                _rng = get_gateway_range_text("crypto")
                bot.answer_callback_query(call.id,
                    f"⛔️ مبلغ {fmt_price(price)} تومان برای این درگاه مجاز نیست.\n"
                    f"محدوده مجاز: {_rng}\n\nلطفاً درگاه دیگری انتخاب کنید.",
                    show_alert=True); return
            state_set(uid, "pnlcfg_renew_crypto_select_coin",
                      config_id=config_id, package_id=package_id, amount=price)
            bot.answer_callback_query(call.id)
            show_crypto_selection(call, amount=price)
            return

        # mypnlcfgrpay:tetrapay:{config_id}:{package_id}
        if data.startswith("mypnlcfgrpay:tetrapay:"):
            if not _check_invoice_valid(uid):
                _show_invoice_expired(call); return
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True); return
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if not is_gateway_in_range("tetrapay", price):
                _rng = get_gateway_range_text("tetrapay")
                bot.answer_callback_query(call.id,
                    f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه TetraPay مجاز نیست.\n"
                    f"محدوده مجاز: {_rng}\n\nلطفاً درگاه دیگری انتخاب کنید.",
                    show_alert=True); return
            order_id_tp = f"pnlr-{uid}-{config_id}-{int(datetime.now().timestamp())}"
            order_label_tp = (
                f"تمدید {package_row['name']}"
                if ('show_name' not in package_row.keys() or package_row['show_name'])
                else f"تمدید {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
            )
            success_tp, result_tp = create_tetrapay_order(price, order_id_tp, order_label_tp)
            if not success_tp:
                err_msg_tp = result_tp.get("error", "خطای ناشناخته") if isinstance(result_tp, dict) else str(result_tp)
                bot.answer_callback_query(call.id)
                send_or_edit(call,
                    f"⚠️ <b>خطا در ایجاد درگاه TetraPay</b>\n\n<code>{esc(err_msg_tp[:400])}</code>",
                    back_button(f"mypnlcfg:renewconfirm:{config_id}")); return
            authority_tp = result_tp.get("Authority", "")
            pay_url_bot_tp = result_tp.get("payment_url_bot", "")
            pay_url_web_tp = result_tp.get("payment_url_web", "")
            payment_id = create_payment("pnlcfg_renewal", uid, package_id, price, "tetrapay",
                                        status="pending", config_id=config_id)
            with get_conn() as conn:
                conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (authority_tp, payment_id))
            state_set(uid, "await_pnlcfg_renewal_tetrapay_verify",
                      payment_id=payment_id, authority=authority_tp, config_id=config_id)
            text_tp = (
                "🏦 <b>پرداخت آنلاین (تمدید)</b>\n\n"
                f"💰 مبلغ: <b>{fmt_price(price)}</b> تومان\n\n"
                "لطفاً از یکی از لینک‌های زیر پرداخت را انجام دهید.\n\n"
                "⏳ <b>تا یک ساعت</b> اگر پرداخت‌تون تایید بشه به صورت خودکار عملیات انجام می‌شود.\n"
                "در غیر این صورت دکمه <b>بررسی پرداخت</b> را بزنید."
            )
            kb_tp = types.InlineKeyboardMarkup()
            if pay_url_bot_tp and setting_get("tetrapay_mode_bot", "1") == "1":
                kb_tp.add(types.InlineKeyboardButton("💳 پرداخت در تلگرام", url=pay_url_bot_tp))
            if pay_url_web_tp and setting_get("tetrapay_mode_web", "1") == "1":
                kb_tp.add(types.InlineKeyboardButton("🌐 پرداخت در مرورگر", url=pay_url_web_tp))
            kb_tp.add(types.InlineKeyboardButton("🔍 بررسی پرداخت",
                       callback_data=f"mypnlcfgrpay:tetrapay:verify:{payment_id}"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, text_tp, kb_tp)
            _start_tetrapay_auto_verify(
                payment_id, authority_tp, uid,
                call.message.chat.id, call.message.message_id,
                "pnlcfg_renewal", package_id=package_id)
            return

        # mypnlcfgrpay:tetrapay:verify:{payment_id}
        if data.startswith("mypnlcfgrpay:tetrapay:verify:"):
            bot.answer_callback_query(call.id)
            return

        # mypnlcfgrpay:tronpays_rial:{config_id}:{package_id}
        if data.startswith("mypnlcfgrpay:tronpays_rial:") and not data.startswith("mypnlcfgrpay:tronpays_rial:verify:"):
            if not _check_invoice_valid(uid):
                _show_invoice_expired(call); return
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True); return
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if not is_gateway_in_range("tronpays_rial", price):
                _rng = get_gateway_range_text("tronpays_rial")
                bot.answer_callback_query(call.id,
                    f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه TronPay مجاز نیست.\n"
                    f"محدوده مجاز: {_rng}\n\nلطفاً درگاه دیگری انتخاب کنید.",
                    show_alert=True); return
            hash_id_trp = f"pnlr-{uid}-{config_id}-{int(datetime.now().timestamp())}"
            order_label_trp = (
                f"تمدید {package_row['name']}"
                if ('show_name' not in package_row.keys() or package_row['show_name'])
                else f"تمدید {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
            )
            success_trp, result_trp = create_tronpays_rial_invoice(price, hash_id_trp, order_label_trp)
            if not success_trp:
                err_msg_trp = result_trp.get("error", "خطای ناشناخته") if isinstance(result_trp, dict) else str(result_trp)
                bot.answer_callback_query(call.id)
                send_or_edit(call,
                    f"⚠️ <b>خطا در ایجاد فاکتور TronPays</b>\n\n<code>{esc(err_msg_trp[:400])}</code>",
                    back_button(f"mypnlcfg:renewconfirm:{config_id}")); return
            invoice_id_trp = result_trp.get("invoice_id")
            invoice_url_trp = result_trp.get("invoice_url")
            if not invoice_id_trp or not invoice_url_trp:
                bot.answer_callback_query(call.id)
                send_or_edit(call, "⚠️ خطا در ایجاد فاکتور TronPays. لطفاً دوباره تلاش کنید.",
                             back_button(f"mypnlcfg:renewconfirm:{config_id}")); return
            payment_id = create_payment("pnlcfg_renewal", uid, package_id, price, "tronpays_rial",
                                        status="pending", config_id=config_id)
            with get_conn() as conn:
                conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id_trp, payment_id))
            state_set(uid, "await_pnlcfg_renewal_tronpays_verify",
                      payment_id=payment_id, invoice_id=invoice_id_trp, config_id=config_id)
            kb_trp = types.InlineKeyboardMarkup()
            kb_trp.add(types.InlineKeyboardButton("💳 پرداخت", url=invoice_url_trp))
            kb_trp.add(types.InlineKeyboardButton("🔍 بررسی پرداخت",
                        callback_data=f"mypnlcfgrpay:tronpays_rial:verify:{payment_id}"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "🏦 <b>پرداخت آنلاین TronPays (تمدید)</b>\n\n"
                f"💰 مبلغ: <b>{fmt_price(price)}</b> تومان\n\n"
                "⏳ پس از پرداخت، دکمه <b>بررسی پرداخت</b> را بزنید.",
                kb_trp)
            _start_tronpays_rial_auto_verify(
                payment_id, invoice_id_trp, uid,
                call.message.chat.id, call.message.message_id,
                "pnlcfg_renewal", package_id=package_id)
            return

        # mypnlcfgrpay:tronpays_rial:verify:{payment_id}
        if data.startswith("mypnlcfgrpay:tronpays_rial:verify:"):
            payment_id = int(data.split(":")[-1])
            payment = get_payment(payment_id)
            if not payment or payment["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            if payment["status"] != "pending":
                bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True); return
            invoice_id_v = payment["receipt_text"]
            ok_v, status_v = check_tronpays_rial_invoice(invoice_id_v)
            if not ok_v:
                bot.answer_callback_query(call.id, "خطا در بررسی وضعیت فاکتور.", show_alert=True); return
            if is_tronpays_paid(status_v):
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True); return
                config_id_v  = payment["config_id"]
                package_id_v = payment["package_id"]
                bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد! در حال تمدید…")
                ok_r, err_r = _execute_pnlcfg_renewal(config_id_v, package_id_v, chat_id=uid, uid=uid)
                state_clear(uid)
                if not ok_r:
                    send_or_edit(call, "❌ پرداخت انجام شد اما تمدید سرویس با خطا مواجه شد.\nلطفاً با پشتیبانی ارتباط بگیرید.",
                                 back_button("my_configs"))
                    return
                _show_panel_config_detail(call, config_id_v, back_data="my_configs", is_user_view=True)
            else:
                bot.answer_callback_query(call.id, "❌ پرداخت هنوز تأیید نشده. لطفاً ابتدا پرداخت را انجام دهید.", show_alert=True)
            return

        # mypnlcfgrpay:swapwallet_crypto:{config_id}:{package_id}
        if data.startswith("mypnlcfgrpay:swapwallet_crypto:") and not data.startswith("mypnlcfgrpay:swapwallet_crypto:verify:"):
            if not _check_invoice_valid(uid):
                _show_invoice_expired(call); return
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True); return
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if not is_gateway_in_range("swapwallet_crypto", price):
                _rng = get_gateway_range_text("swapwallet_crypto")
                bot.answer_callback_query(call.id,
                    f"⛔️ مبلغ {fmt_price(price)} تومان برای درگاه SwapWallet مجاز نیست.\n"
                    f"محدوده مجاز: {_rng}\n\nلطفاً درگاه دیگری انتخاب کنید.",
                    show_alert=True); return
            from ..gateways.swapwallet_crypto import get_active_swapwallet_networks, NETWORK_LABELS as SW_NET_LABELS2
            _active_nets_pnl = get_active_swapwallet_networks()
            if not _active_nets_pnl:
                bot.answer_callback_query(call.id, "هیچ ارزی برای SwapWallet فعال نشده است.", show_alert=True); return
            state_set(uid, "swcrypto_network_select", kind="pnlcfg_renewal",
                      config_id=config_id, package_id=package_id, amount=price)
            kb_sw = types.InlineKeyboardMarkup()
            if len(_active_nets_pnl) == 1:
                net_pnl = _active_nets_pnl[0][0]
                order_id_sw = f"pnlswc-{uid}-{int(datetime.now().timestamp())}"
                success_sw, result_sw = create_swapwallet_crypto_invoice(price, order_id_sw, net_pnl, "تمدید سرویس")
                if not success_sw:
                    err_sw = result_sw.get("error", "خطای ناشناخته") if isinstance(result_sw, dict) else str(result_sw)
                    _swapwallet_error_inline(call, err_sw); return
                invoice_id_sw = result_sw.get("id", "")
                payment_id = create_payment("pnlcfg_renewal", uid, package_id, price, "swapwallet_crypto",
                                            status="pending", config_id=config_id)
                with get_conn() as conn:
                    conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id_sw, payment_id))
                state_set(uid, "await_swapwallet_crypto_verify", payment_id=payment_id,
                          invoice_id=invoice_id_sw, config_id=config_id)
                verify_cb_sw = f"mypnlcfgrpay:swapwallet_crypto:verify:{payment_id}"
                bot.answer_callback_query(call.id)
                show_swapwallet_crypto_page(call, amount_toman=price, invoice_id=invoice_id_sw,
                                            result=result_sw, payment_id=payment_id, verify_cb=verify_cb_sw)
            else:
                for net_sw, _ in _active_nets_pnl:
                    kb_sw.add(types.InlineKeyboardButton(SW_NET_LABELS2.get(net_sw, net_sw),
                               callback_data=f"swcrypto:net:{net_sw}"))
                kb_sw.add(types.InlineKeyboardButton("بازگشت", callback_data=f"mypnlcfg:renewconfirm:{config_id}",
                           icon_custom_emoji_id="5253997076169115797"))
                bot.answer_callback_query(call.id)
                send_or_edit(call, "💎 <b>پرداخت کریپتو (SwapWallet)</b>\n\nشبکه مورد نظر را انتخاب کنید:", kb_sw)
            return

        # mypnlcfgrpay:swapwallet_crypto:verify:{payment_id}
        if data.startswith("mypnlcfgrpay:swapwallet_crypto:verify:"):
            payment_id = int(data.split(":")[-1])
            payment = get_payment(payment_id)
            if not payment or payment["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            if payment["status"] != "pending":
                bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True); return
            invoice_id_sv = payment["receipt_text"]
            success_sv, inv_sv = check_swapwallet_crypto_invoice(invoice_id_sv)
            if not success_sv:
                bot.answer_callback_query(call.id, "خطا در بررسی وضعیت فاکتور.", show_alert=True); return
            if inv_sv.get("status") in ("PAID", "COMPLETED") or inv_sv.get("paidAt"):
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "این پرداخت قبلاً پردازش شده.", show_alert=True); return
                config_id_sv  = payment["config_id"]
                package_id_sv = payment["package_id"]
                bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد! در حال تمدید…")
                ok_r, err_r = _execute_pnlcfg_renewal(config_id_sv, package_id_sv, chat_id=uid, uid=uid)
                state_clear(uid)
                if not ok_r:
                    send_or_edit(call, "❌ پرداخت انجام شد اما تمدید سرویس با خطا مواجه شد.\nلطفاً با پشتیبانی ارتباط بگیرید.",
                                 back_button("my_configs"))
                    return
                _show_panel_config_detail(call, config_id_sv, back_data="my_configs", is_user_view=True)
            else:
                bot.answer_callback_query(call.id, "❌ پرداخت هنوز تأیید نشده.", show_alert=True)
            return

        # mypnlcfg:autorenew:{config_id}
        if data.startswith("mypnlcfg:autorenew:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            cfg = dict(cfg)
            new_val = 0 if int(cfg["auto_renew"] or 0) else 1
            # When enabling auto-renew, check if user has enough balance
            if new_val == 1 and cfg.get("package_id"):
                from ..db import get_package as _get_pkg2
                from ..payments import get_effective_price as _gep
                _pkg = _get_pkg2(cfg["package_id"])
                _usr = get_user(uid)
                if _pkg and _usr:
                    _price   = _gep(uid, _pkg)
                    _balance = int(_usr["balance"] or 0)
                    if _price > 0 and _balance < _price:
                        bot.answer_callback_query(
                            call.id,
                            f"⛔ موجودی کافی ندارید.\n"
                            f"برای فعال‌سازی تمدید خودکار این کانفیگ، "
                            f"کیف پول خود را به میزان {fmt_price(_price)} تومان "
                            f"(معادل هزینه سرویس) شارژ کنید.",
                            show_alert=True
                        )
                        return
            update_panel_config_field(config_id, "auto_renew", new_val)
            bot.answer_callback_query(call.id, f"تمدید خودکار {'فعال' if new_val else 'غیرفعال'} شد.")
            _show_panel_config_detail(call, config_id, back_data="my_configs",
                                      is_user_view=True)
            return

        # mypnlcfg:rsub:{config_id}
        if data.startswith("mypnlcfg:rsub:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            cpkg = get_panel_client_package(cfg["cpkg_id"]) if cfg.get("cpkg_id") else None
            if not cpkg:
                bot.answer_callback_query(call.id, "قالب ساب موجود نیست.", show_alert=True); return
            cpkg_d = dict(cpkg)
            import uuid as _uuid
            new_sub_id  = str(_uuid.uuid4()).replace("-", "")[:16]
            new_sub_url = _build_sub_from_template(cpkg_d, new_sub_id)
            if not new_sub_url:
                bot.answer_callback_query(call.id, "خطا در ساخت لینک ساب.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            if panel:
                from ..panels.client import PanelClient
                pc_api = PanelClient(
                    protocol=panel["protocol"], host=panel["host"], port=panel["port"],
                    path=panel["path"] or "", username=panel["username"], password=panel["password"]
                )
                pc_api.update_client_sub(
                    inbound_id=cfg["inbound_id"], client_uuid=cfg["client_uuid"],
                    email=cfg["client_name"] or "", new_sub_id=new_sub_id,
                )
            update_panel_config_texts(config_id, cfg["client_config_text"], new_sub_url)
            bot.answer_callback_query(call.id, "✅ لینک ساب جدید ساخته شد.")
            _show_panel_config_detail(call, config_id, back_data="my_configs",
                                      is_user_view=True)
            return

        # mypnlcfg:qrc:{config_id}
        if data.startswith("mypnlcfg:qrc:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            if cfg["client_config_text"]:
                try:
                    import qrcode as _qrcode
                    from io import BytesIO
                    bio = BytesIO(); _qrcode.make(cfg["client_config_text"]).save(bio, format="PNG"); bio.seek(0)
                    bio.name = "qr_config.png"
                    bot.answer_callback_query(call.id)
                    bot.send_photo(uid, bio, caption="📷 QR کانفیگ")
                except Exception as e:
                    bot.answer_callback_query(call.id, str(e), show_alert=True)
            else:
                bot.answer_callback_query(call.id, "کانفیگ موجود نیست.", show_alert=True)
            return

        # mypnlcfg:qrs:{config_id}
        if data.startswith("mypnlcfg:qrs:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True); return
            if cfg["client_sub_url"]:
                try:
                    import qrcode as _qrcode
                    from io import BytesIO
                    bio = BytesIO(); _qrcode.make(cfg["client_sub_url"]).save(bio, format="PNG"); bio.seek(0)
                    bio.name = "qr_sub.png"
                    bot.answer_callback_query(call.id)
                    bot.send_photo(uid, bio, caption="📷 QR سابسکرایب")
                except Exception as e:
                    bot.answer_callback_query(call.id, str(e), show_alert=True)
            else:
                bot.answer_callback_query(call.id, "لینک ساب موجود نیست.", show_alert=True)
            return

        # mypnlcfg:list:{filter}:{page}  →  user's filtered panel config list
        if data.startswith("mypnlcfg:list:"):
            parts = data.split(":")
            flt   = parts[2]  # all | expiring | expired
            page  = int(parts[3]) if len(parts) > 3 else 0
            if flt not in ("all", "expiring", "expired"):
                flt = "all"
            PER = 10
            with get_conn() as _c:
                _base = (
                    "SELECT COUNT(*) AS n FROM panel_configs pc "
                    "LEFT JOIN packages p ON pc.package_id=p.id "
                    "WHERE pc.user_id=?"
                )
                _params = [uid]
                if flt == "expired":
                    _base += " AND pc.is_expired=1"
                elif flt == "expiring":
                    _base += (
                        " AND pc.is_expired=0"
                        " AND pc.expire_at IS NOT NULL"
                        " AND pc.expire_at > datetime('now')"
                        " AND (julianday(pc.expire_at)-julianday('now')) < "
                        "0.2*CAST(CASE WHEN p.duration_days>0 THEN p.duration_days ELSE 9999 END AS REAL)"
                    )
                user_total = _c.execute(_base, _params).fetchone()["n"]
                total_pages = max(1, (user_total + PER - 1) // PER)
                page = max(0, min(page, total_pages - 1))
                _base2 = (
                    "SELECT pc.*, p.name AS package_name, p.volume_gb, p.duration_days,"
                    " t.name AS type_name"
                    " FROM panel_configs pc"
                    " LEFT JOIN packages p ON pc.package_id=p.id"
                    " LEFT JOIN config_types t ON t.id=p.type_id"
                    " WHERE pc.user_id=?"
                )
                _p2 = [uid]
                if flt == "expired":
                    _base2 += " AND pc.is_expired=1"
                elif flt == "expiring":
                    _base2 += (
                        " AND pc.is_expired=0"
                        " AND pc.expire_at IS NOT NULL"
                        " AND pc.expire_at > datetime('now')"
                        " AND (julianday(pc.expire_at)-julianday('now')) < "
                        "0.2*CAST(CASE WHEN p.duration_days>0 THEN p.duration_days ELSE 9999 END AS REAL)"
                    )
                _base2 += " ORDER BY pc.id DESC LIMIT ? OFFSET ?"
                _p2 += [PER, page * PER]
                rows = _c.execute(_base2, _p2).fetchall()

            flt_labels = {"all": "📋 همه", "expiring": "⚠️ رو به پایان", "expired": "❌ منقضی"}
            bot.answer_callback_query(call.id)
            kb = types.InlineKeyboardMarkup()
            for row in rows:
                if row["is_expired"]:
                    marker = " ⌛"
                elif int(row["is_disabled"] or 0):
                    marker = " ⛔"
                else:
                    marker = " 🟢"
                name = esc(row["client_name"] or row["package_name"] or "—")
                kb.add(types.InlineKeyboardButton(f"{name}{marker}", callback_data=f"mypnlcfg:d:{row['id']}"))
            if total_pages > 1:
                nav = []
                if page > 0:
                    nav.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"mypnlcfg:list:{flt}:{page-1}"))
                nav.append(types.InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
                if page < total_pages - 1:
                    nav.append(types.InlineKeyboardButton("▶️ بعدی", callback_data=f"mypnlcfg:list:{flt}:{page+1}"))
                kb.row(*nav)
            kb.add(types.InlineKeyboardButton("🔙 بازگشت به سرویس‌ها", callback_data="my_configs"))
            header = f"{flt_labels.get(flt, '📋')} <b>کانفیگ‌های پنل</b>"
            if not rows:
                header += "\n\n📭 موردی یافت نشد."
            else:
                header += f"\n\nیکی از سرویس‌ها را انتخاب کنید:"
            send_or_edit(call, header, kb)
            return

    if data == "admin:add_config":
        if not (admin_has_perm(uid, "register_config") or admin_has_perm(uid, "manage_configs")):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        types_list = get_all_types()
        kb = types.InlineKeyboardMarkup()
        for item in types_list:
            kb.add(types.InlineKeyboardButton(f"🧩 {item['name']}", callback_data=f"adm:cfg:t:{item['id']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📝 <b>ثبت کانفیگ</b>\n\nنوع کانفیگ را انتخاب کنید:", kb)
        return


    if data.startswith("adm:cfg:t:"):
        type_id = int(data.split(":")[3])
        packs   = get_packages(type_id=type_id)
        kb      = types.InlineKeyboardMarkup()
        for p in packs:
            kb.add(types.InlineKeyboardButton(
                f"{p['name']} | {fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])}",
                callback_data=f"adm:cfg:p:{p['id']}"
            ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:add_config", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📦 پکیج مربوطه را انتخاب کنید:", kb)
        return

    if data.startswith("adm:cfg:p:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        state_set(uid, "admin_cfg_proto_select", package_id=package_id, type_id=package_row["type_id"])
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🌐 V2Ray",    callback_data=f"adm:cfg:proto:v2ray:{package_id}"))
        kb.add(types.InlineKeyboardButton("🔒 OpenVPN",  callback_data=f"adm:cfg:proto:ovpn:{package_id}"))
        kb.add(types.InlineKeyboardButton("🛡 WireGuard", callback_data=f"adm:cfg:proto:wg:{package_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:t:{package_row['type_id']}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔌 پروتکل کانفیگ را انتخاب کنید:", kb)
        return

    # ── Protocol selector ─────────────────────────────────────────────────────
    if data.startswith("adm:cfg:proto:"):
        parts      = data.split(":")
        proto      = parts[3]           # v2ray | ovpn | wg
        package_id = int(parts[4])
        package_row = get_package(package_id)

        # ── V2Ray: new structured flow ────────────────────────────────────────
        if proto == "v2ray":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",    callback_data=f"adm:v2:single:{package_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:v2:bulk:{package_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "📝 روش ثبت کانفیگ V2Ray را انتخاب کنید:", kb)
            return

        # ── OpenVPN ───────────────────────────────────────────────────────────
        if proto == "ovpn":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",   callback_data=f"adm:ovpn:single:{package_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:ovpn:bulk:{package_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "📝 روش ثبت کانفیگ OpenVPN را انتخاب کنید:", kb)
            return

        # ── WireGuard ─────────────────────────────────────────────────────────
        if proto == "wg":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",    callback_data=f"adm:wg:single:{package_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:wg:bulk:{package_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "📝 روش ثبت کانفیگ WireGuard را انتخاب کنید:", kb)
            return

        bot.answer_callback_query(call.id, "پروتکل ناشناخته", show_alert=True)
        return

    # ── OpenVPN — Single ─────────────────────────────────────────────────────
    if data.startswith("adm:ovpn:single:"):
        package_id = int(data.split(":")[3])
        state_set(uid, "ovpn_single_file", package_id=package_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:proto:ovpn:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📎 <b>ثبت تکی OpenVPN</b>\n\n"
            "فایل یا فایل‌های <code>.ovpn</code> را ارسال کنید.\n"
            "اگر چند فایل دارید، همه را یکجا بفرستید — همه متعلق به یک اکانت در نظر گرفته می‌شوند.\n\n"
            "⚠️ فقط فرمت <b>.ovpn</b> پذیرفته می‌شود.", kb)
        return

    # ── OpenVPN — Bulk (shared vs different files) ────────────────────────────
    if data.startswith("adm:ovpn:bulk:"):
        rest       = data[len("adm:ovpn:bulk:"):]

        # adm:ovpn:bulk:{pkg_id}  → first question: same file?
        if rest.isdigit():
            package_id = int(rest)
            state_set(uid, "ovpn_bulk_init", package_id=package_id)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("✅ بله", callback_data=f"adm:ovpn:bulk:shared:{package_id}"),
                types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:ovpn:bulk:diff:{package_id}"),
            )
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:proto:ovpn:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "📂 آیا فایل کانفیگ <b>همه اکانت‌ها یکی</b> است؟", kb)
            return

        # adm:ovpn:bulk:shared:{pkg_id}  → send shared ovpn files
        if rest.startswith("shared:"):
            package_id = int(rest.split(":")[1])
            state_set(uid, "ovpn_bulk_shared_file", package_id=package_id, shared_files=[])
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:ovpn:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "📎 <b>ثبت دسته‌ای OpenVPN — فایل مشترک</b>\n\n"
                "فایل یا فایل‌های <code>.ovpn</code> مشترک را ارسال کنید.\n"
                "اگر چند فایل مشترک دارید همه را بفرستید.\n\n"
                "وقتی تمام فایل‌ها را فرستادید دکمه ✅ را بزنید.",
                kb)
            # We send a separate message with Done button since state must settle
            done_kb = types.InlineKeyboardMarkup()
            done_kb.add(types.InlineKeyboardButton("✅ فایل‌ها کامل‌اند، ادامه", callback_data=f"adm:ovpn:sharedok:{package_id}"))
            bot.send_message(uid, "پس از ارسال همه فایل‌های مشترک، این دکمه را بزنید:", reply_markup=done_kb)
            return

        # adm:ovpn:bulk:diff:{pkg_id}  → how many accounts?
        if rest.startswith("diff:"):
            package_id = int(rest.split(":")[1])
            state_set(uid, "ovpn_bulk_diff_count", package_id=package_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:ovpn:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "🔢 <b>ثبت دسته‌ای OpenVPN — فایل متفاوت</b>\n\n"
                "چند اکانت می‌خواهید ثبت کنید؟\n"
                "عدد را تایپ کنید:", kb)
            return

        bot.answer_callback_query(call.id, "مسیر ناشناخته", show_alert=True)
        return

    # ── OpenVPN — shared files done, ask about inquiry ────────────────────────
    if data.startswith("adm:ovpn:sharedok:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        shared_files = sd.get("shared_files", [])
        if not shared_files:
            bot.answer_callback_query(call.id, "هیچ فایل .ovpn دریافت نشد. لطفاً ابتدا فایل ارسال کنید.", show_alert=True)
            return
        state_set(uid, "ovpn_bulk_shared_inq", package_id=package_id, shared_files=shared_files)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ بله", callback_data=f"adm:ovpn:shinq:y:{package_id}"),
            types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:ovpn:shinq:n:{package_id}"),
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔗 آیا اکانت‌ها <b>لینک استعلام حجم</b> دارند؟", kb)
        return

    # ── OpenVPN — shared: has inquiry or not ─────────────────────────────────
    if data.startswith("adm:ovpn:shinq:"):
        parts      = data.split(":")
        yn         = parts[3]
        package_id = int(parts[4])
        has_inq    = (yn == "y")
        sd = state_data(uid)
        shared_files = sd.get("shared_files", [])
        state_set(uid, "ovpn_bulk_shared_data",
                  package_id=package_id, shared_files=shared_files, has_inquiry=has_inq)
        bot.answer_callback_query(call.id)
        if has_inq:
            fmt_text = (
                "📋 <b>اطلاعات اکانت‌ها — فایل مشترک (با لینک استعلام)</b>\n\n"
                "هر اکانت <b>۳ خط</b>:\n"
                "خط ۱: username\n"
                "خط ۲: password\n"
                "خط ۳: volume web (لینک استعلام)\n\n"
                "💡 مثال:\n"
                "<code>user1\npass1\nhttp://panel.com/sub/1\n"
                "user2\npass2\nhttp://panel.com/sub/2</code>"
            )
        else:
            fmt_text = (
                "📋 <b>اطلاعات اکانت‌ها — فایل مشترک (بدون لینک استعلام)</b>\n\n"
                "هر اکانت <b>۲ خط</b>:\n"
                "خط ۱: username\n"
                "خط ۲: password\n\n"
                "💡 مثال:\n"
                "<code>user1\npass1\nuser2\npass2</code>"
            )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:ovpn:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, fmt_text, kb)
        return

    # ── OpenVPN — diff: per-account files done, ask inquiry ──────────────────
    if data.startswith("adm:ovpn:diffok:"):
        # adm:ovpn:diffok:{pkg_id}:{account_idx}  — all files for that account received
        parts      = data.split(":")
        package_id = int(parts[3])
        acct_idx   = int(parts[4])
        sd         = state_data(uid)
        acct_files = sd.get("acct_files", {})
        files_for_acct = sd.get("pending_acct_files", [])
        if not files_for_acct:
            bot.answer_callback_query(call.id, "هیچ فایل .ovpn برای این اکانت دریافت نشد.", show_alert=True)
            return
        acct_files[acct_idx] = files_for_acct
        total_accts = sd.get("total_accts", 0)
        next_idx    = acct_idx + 1
        if next_idx <= total_accts:
            state_set(uid, "ovpn_bulk_diff_files",
                      package_id=package_id, total_accts=total_accts,
                      acct_files=acct_files, current_acct=next_idx, pending_acct_files=[])
            done_kb = types.InlineKeyboardMarkup()
            done_kb.add(types.InlineKeyboardButton(
                f"✅ فایل‌های اکانت {next_idx} کامل‌اند",
                callback_data=f"adm:ovpn:diffok:{package_id}:{next_idx}"
            ))
            bot.answer_callback_query(call.id)
            bot.send_message(uid,
                f"📎 فایل‌های <code>.ovpn</code> <b>اکانت {next_idx}</b> از {total_accts} را ارسال کنید:",
                reply_markup=done_kb)
        else:
            # All account files received → ask inquiry
            state_set(uid, "ovpn_bulk_diff_inq",
                      package_id=package_id, total_accts=total_accts, acct_files=acct_files)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("✅ بله", callback_data=f"adm:ovpn:dinq:y:{package_id}"),
                types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:ovpn:dinq:n:{package_id}"),
            )
            bot.answer_callback_query(call.id)
            bot.send_message(uid, "🔗 آیا اکانت‌ها <b>لینک استعلام حجم</b> دارند؟", reply_markup=kb)
        return

    # ── OpenVPN — diff: has inquiry or not ───────────────────────────────────
    if data.startswith("adm:ovpn:dinq:"):
        parts      = data.split(":")
        yn         = parts[3]
        package_id = int(parts[4])
        has_inq    = (yn == "y")
        sd = state_data(uid)
        state_set(uid, "ovpn_bulk_diff_data",
                  package_id=package_id, total_accts=sd.get("total_accts", 0),
                  acct_files=sd.get("acct_files", {}), has_inquiry=has_inq)
        bot.answer_callback_query(call.id)
        if has_inq:
            fmt_text = (
                "📋 <b>اطلاعات اکانت‌ها — فایل متفاوت (با لینک استعلام)</b>\n\n"
                "هر اکانت <b>۳ خط</b> به ترتیب:\n"
                "خط ۱: username\n"
                "خط ۲: password\n"
                "خط ۳: volume web (لینک استعلام)\n\n"
                "💡 مثال:\n"
                "<code>user1\npass1\nhttp://panel.com/sub/1\n"
                "user2\npass2\nhttp://panel.com/sub/2</code>"
            )
        else:
            fmt_text = (
                "📋 <b>اطلاعات اکانت‌ها — فایل متفاوت (بدون لینک استعلام)</b>\n\n"
                "هر اکانت <b>۲ خط</b> به ترتیب:\n"
                "خط ۱: username\n"
                "خط ۲: password\n\n"
                "💡 مثال:\n"
                "<code>user1\npass1\nuser2\npass2</code>"
            )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:ovpn:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.send_message(uid, fmt_text, reply_markup=kb)
        return

    # ── OpenVPN — Single: files done, ask username ────────────────────────────
    if data.startswith("adm:ovpn:single_done:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        ovpn_files = sd.get("ovpn_files", [])
        if not ovpn_files:
            bot.answer_callback_query(call.id, "هیچ فایل .ovpn دریافت نشد.", show_alert=True)
            return
        state_set(uid, "ovpn_single_username", package_id=package_id, ovpn_files=ovpn_files)
        bot.answer_callback_query(call.id)
        bot.send_message(uid, "👤 <b>Username</b> اکانت را وارد کنید:", parse_mode="HTML")
        return

    # ── OpenVPN — Single: skip inquiry link ──────────────────────────────────
    if data.startswith("adm:ovpn:sinq_skip:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        _ovpn_finish_single(uid, sd, "")
        bot.answer_callback_query(call.id)
        return

    # ── WireGuard — Single ────────────────────────────────────────────────────
    if data.startswith("adm:wg:single:"):
        package_id = int(data.split(":")[3])
        state_set(uid, "wg_single_file", package_id=package_id, wg_files=[], wg_names=[])
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:proto:wg:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📎 <b>ثبت تکی WireGuard</b>\n\n"
            "فایل یا فایل‌های کانفیگ WireGuard را ارسال کنید.\n"
            "اگر چند فایل دارید، همه را بفرستید — همه متعلق به یک کانفیگ در نظر گرفته می‌شوند.\n\n"
            "نام سرویس به صورت خودکار از نام فایل خوانده می‌شود.", kb)
        return

    # ── WireGuard — Single: files done ───────────────────────────────────────
    if data.startswith("adm:wg:single_done:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        wg_files = sd.get("wg_files", [])
        if not wg_files:
            bot.answer_callback_query(call.id, "هیچ فایلی دریافت نشد.", show_alert=True)
            return
        state_set(uid, "wg_single_inquiry",
                  package_id=package_id,
                  wg_files=wg_files, wg_names=sd.get("wg_names", []))
        bot.answer_callback_query(call.id)
        skip_kb = types.InlineKeyboardMarkup()
        skip_kb.add(types.InlineKeyboardButton("⏭ Skip (بدون لینک استعلام)", callback_data=f"adm:wg:sinq_skip:{package_id}"))
        bot.send_message(uid,
            "🔋 <b>لینک استعلام حجم</b> را وارد کنید یا Skip بزنید:\n"
            "(مثال: <code>http://panel.example.com/sub/abc</code>)",
            reply_markup=skip_kb, parse_mode="HTML")
        return

    # ── WireGuard — Single: skip inquiry ─────────────────────────────────────
    if data.startswith("adm:wg:sinq_skip:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        _wg_finish_single(uid, sd, "")
        bot.answer_callback_query(call.id)
        return

    # ── WireGuard — Bulk ──────────────────────────────────────────────────────
    if data.startswith("adm:wg:bulk:"):
        rest = data[len("adm:wg:bulk:"):]

        # adm:wg:bulk:{pkg_id} → ask same/different files
        if rest.isdigit():
            package_id = int(rest)
            state_set(uid, "wg_bulk_init", package_id=package_id)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("✅ بله", callback_data=f"adm:wg:bulk:shared:{package_id}"),
                types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:wg:bulk:diff:{package_id}"),
            )
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:proto:wg:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "📂 آیا فایل‌های <b>همه کانفیگ‌ها یکی</b> هستند؟", kb)
            return

        # adm:wg:bulk:shared:{pkg_id} → collect shared files
        if rest.startswith("shared:"):
            package_id = int(rest.split(":")[1])
            state_set(uid, "wg_bulk_shared_file", package_id=package_id, shared_files=[], shared_names=[])
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:wg:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "📎 <b>ثبت دسته‌ای WireGuard — فایل مشترک</b>\n\n"
                "فایل یا فایل‌های مشترک WireGuard را ارسال کنید.\n"
                "وقتی تمام فایل‌ها را فرستادید دکمه ✅ را بزنید.", kb)
            done_kb = types.InlineKeyboardMarkup()
            done_kb.add(types.InlineKeyboardButton("✅ فایل‌ها کامل‌اند، ادامه", callback_data=f"adm:wg:sharedok:{package_id}"))
            bot.send_message(uid, "پس از ارسال همه فایل‌های مشترک، این دکمه را بزنید:", reply_markup=done_kb)
            return

        # adm:wg:bulk:diff:{pkg_id} → how many configs?
        if rest.startswith("diff:"):
            package_id = int(rest.split(":")[1])
            state_set(uid, "wg_bulk_diff_count", package_id=package_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:wg:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "🔢 <b>ثبت دسته‌ای WireGuard — فایل متفاوت</b>\n\n"
                "چند کانفیگ می‌خواهید ثبت کنید؟\n"
                "عدد را تایپ کنید:", kb)
            return

        bot.answer_callback_query(call.id, "مسیر ناشناخته", show_alert=True)
        return

    # ── WireGuard — Shared files done, ask inquiry ────────────────────────────
    if data.startswith("adm:wg:sharedok:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        shared_files = sd.get("shared_files", [])
        if not shared_files:
            bot.answer_callback_query(call.id, "هیچ فایلی دریافت نشد. لطفاً ابتدا فایل ارسال کنید.", show_alert=True)
            return
        state_set(uid, "wg_bulk_shared_inq",
                  package_id=package_id,
                  shared_files=shared_files, shared_names=sd.get("shared_names", []))
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ بله", callback_data=f"adm:wg:shinq:y:{package_id}"),
            types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:wg:shinq:n:{package_id}"),
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔗 آیا کانفیگ‌ها <b>لینک استعلام حجم</b> دارند؟", kb)
        return

    # ── WireGuard — Shared: with/without inquiry ──────────────────────────────
    if data.startswith("adm:wg:shinq:"):
        parts      = data.split(":")
        yn         = parts[3]
        package_id = int(parts[4])
        has_inq    = (yn == "y")
        sd = state_data(uid)
        state_set(uid, "wg_bulk_shared_data",
                  package_id=package_id,
                  shared_files=sd.get("shared_files", []),
                  shared_names=sd.get("shared_names", []),
                  has_inquiry=has_inq)
        bot.answer_callback_query(call.id)
        if has_inq:
            fmt_text = (
                "📋 <b>لینک‌های استعلام — فایل مشترک</b>\n\n"
                "هر خط یک لینک استعلام برای یک کانفیگ:\n\n"
                "💡 مثال:\n"
                "<code>http://panel.com/sub/1\n"
                "http://panel.com/sub/2\n"
                "http://panel.com/sub/3</code>"
            )
        else:
            fmt_text = (
                "🔢 <b>تعداد کانفیگ‌ها</b>\n\n"
                "چند نسخه از این فایل‌های مشترک می‌خواهید ارسال شود؟\n"
                "عدد را وارد کنید:"
            )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:wg:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, fmt_text, kb)
        return

    # ── WireGuard — Diff: per-config files done ───────────────────────────────
    if data.startswith("adm:wg:diffok:"):
        parts      = data.split(":")
        package_id = int(parts[3])
        cfg_idx    = int(parts[4])
        sd         = state_data(uid)
        acct_files = sd.get("acct_files", {})
        acct_names = sd.get("acct_names", {})
        pending_files = sd.get("pending_acct_files", [])
        pending_names = sd.get("pending_acct_names", [])
        if not pending_files:
            bot.answer_callback_query(call.id, "هیچ فایلی برای این کانفیگ دریافت نشد.", show_alert=True)
            return
        acct_files[cfg_idx] = pending_files
        acct_names[cfg_idx] = pending_names
        total_cfgs = sd.get("total_accts", 0)
        next_idx   = cfg_idx + 1
        if next_idx <= total_cfgs:
            state_set(uid, "wg_bulk_diff_files",
                      package_id=package_id, total_accts=total_cfgs,
                      acct_files=acct_files, acct_names=acct_names,
                      current_acct=next_idx,
                      pending_acct_files=[], pending_acct_names=[])
            done_kb = types.InlineKeyboardMarkup()
            done_kb.add(types.InlineKeyboardButton(
                f"✅ فایل‌های کانفیگ {next_idx} کامل‌اند",
                callback_data=f"adm:wg:diffok:{package_id}:{next_idx}"
            ))
            bot.answer_callback_query(call.id)
            bot.send_message(uid,
                f"📎 فایل‌های <b>کانفیگ {next_idx}</b> از {total_cfgs} را ارسال کنید:",
                reply_markup=done_kb, parse_mode="HTML")
        else:
            # All files collected → ask inquiry
            state_set(uid, "wg_bulk_diff_inq",
                      package_id=package_id, total_accts=total_cfgs,
                      acct_files=acct_files, acct_names=acct_names)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("✅ بله", callback_data=f"adm:wg:dinq:y:{package_id}"),
                types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:wg:dinq:n:{package_id}"),
            )
            bot.answer_callback_query(call.id)
            bot.send_message(uid, "🔗 آیا کانفیگ‌ها <b>لینک استعلام حجم</b> دارند؟", reply_markup=kb)
        return

    # ── WireGuard — Diff: with/without inquiry ────────────────────────────────
    if data.startswith("adm:wg:dinq:"):
        parts      = data.split(":")
        yn         = parts[3]
        package_id = int(parts[4])
        has_inq    = (yn == "y")
        sd = state_data(uid)
        state_set(uid, "wg_bulk_diff_data",
                  package_id=package_id, total_accts=sd.get("total_accts", 0),
                  acct_files=sd.get("acct_files", {}), acct_names=sd.get("acct_names", {}),
                  has_inquiry=has_inq)
        bot.answer_callback_query(call.id)
        if has_inq:
            fmt_text = (
                "📋 <b>لینک‌های استعلام — فایل متفاوت</b>\n\n"
                "هر خط یک لینک استعلام به ترتیب کانفیگ‌ها:\n\n"
                "💡 مثال:\n"
                "<code>http://panel.com/sub/1\n"
                "http://panel.com/sub/2</code>"
            )
        else:
            fmt_text = "✅ فایل‌ها دریافت شدند. در حال ارسال کانفیگ‌ها..."
            # No inquiry → deliver immediately
            pkg_row = get_package(package_id)
            _wg_deliver_bulk_diff(uid, pkg_row,
                                  sd.get("acct_files", {}),
                                  sd.get("acct_names", {}), [])
            state_clear(uid)
            send_or_edit(call, fmt_text, types.InlineKeyboardMarkup())
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:wg:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.send_message(uid, fmt_text, reply_markup=kb)
        return

    # ── V2Ray: Single ─────────────────────────────────────────────────────────
    # adm:v2:single:{pkg_id}  → choose single-registration mode
    if data.startswith("adm:v2:single:"):
        package_id = int(data.split(":")[3])
        package_row = get_package(package_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "1️⃣ ثبت کانفیگ + ساب جداگانه",
            callback_data=f"adm:v2:sm:1:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton(
            "2️⃣ ثبت کانفیگ تنها",
            callback_data=f"adm:v2:sm:2:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton(
            "3️⃣ ثبت ساب تنها",
            callback_data=f"adm:v2:sm:3:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:proto:v2ray:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "📝 <b>ثبت تکی V2Ray</b>\n\n"
            "نوع کانفیگی که می‌خواهید ثبت کنید را انتخاب کنید:\n\n"
            "1️⃣ <b>کانفیگ + ساب</b>\n"
            "   هم کانفیگ (مثل vless://) دارید هم لینک ساب‌اسکریپشن.\n"
            "   کاربر هر دو را دریافت می‌کند.\n\n"
            "2️⃣ <b>کانفیگ تنها</b>\n"
            "   فقط کانفیگ (مثل vless://) دارید، لینک ساب ندارید.\n"
            "   کاربر فقط کانفیگ را دریافت می‌کند.\n\n"
            "3️⃣ <b>ساب تنها</b>\n"
            "   فقط لینک ساب‌اسکریپشن دارید، کانفیگ مستقیم ندارید.\n"
            "   کاربر فقط لینک ساب را دریافت می‌کند.", kb)
        return

    # adm:v2:sm:{mode}:{pkg_id} → start single-mode flow (ask service name)
    if data.startswith("adm:v2:sm:"):
        parts = data.split(":")
        mode       = int(parts[3])
        package_id = int(parts[4])
        package_row = get_package(package_id)
        state_set(uid, "v2_single_name",
                  package_id=package_id, type_id=package_row["type_id"], mode=mode)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس</b> را وارد کنید:\n"
            "<i>(این نام برای شناسایی سرویس در پنل ادمین و نمایش به کاربر استفاده می‌شود.)</i>",
            back_button(f"adm:v2:single:{package_id}"))
        return

    # ── V2Ray: Bulk ───────────────────────────────────────────────────────────
    # adm:v2:bulk:{pkg_id}  → choose bulk-registration mode
    if data.startswith("adm:v2:bulk:"):
        rest = data[len("adm:v2:bulk:"):]

        # adm:v2:bulk:{pkg_id}  → mode selection
        if rest.isdigit():
            package_id = int(rest)
            package_row = get_package(package_id)
            state_set(uid, "v2_bulk_init",
                      package_id=package_id, type_id=package_row["type_id"])
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(
                "1️⃣ کانفیگ + ساب — مناسب تعداد کم",
                callback_data=f"adm:v2:bm:1:{package_id}"
            ))
            kb.add(types.InlineKeyboardButton(
                "2️⃣ کانفیگ + ساب — مناسب تعداد زیاد",
                callback_data=f"adm:v2:bm:2:{package_id}"
            ))
            kb.add(types.InlineKeyboardButton(
                "3️⃣ کانفیگ تنها",
                callback_data=f"adm:v2:bm:3:{package_id}"
            ))
            kb.add(types.InlineKeyboardButton(
                "4️⃣ ساب تنها",
                callback_data=f"adm:v2:bm:4:{package_id}"
            ))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:proto:v2ray:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "📋 <b>ثبت دسته‌ای V2Ray</b>\n\n"
                "نوع کانفیگ‌هایی که می‌خواهید ثبت کنید را انتخاب کنید:\n\n"
                "1️⃣ <b>کانفیگ + ساب — تعداد کم</b>\n"
                "   هر کانفیگ یک ساب جداگانه دارد و تعداد کمی هستند (زیر ~۳۰).\n"
                "   کانفیگ و ساب را یکی در میان وارد می‌کنید.\n\n"
                "2️⃣ <b>کانفیگ + ساب — تعداد زیاد</b>\n"
                "   هر کانفیگ یک ساب جداگانه دارد و تعداد زیادی هستند.\n"
                "   ابتدا همه کانفیگ‌ها، سپس همه ساب‌ها را جداگانه ارسال می‌کنید.\n\n"
                "3️⃣ <b>کانفیگ تنها</b>\n"
                "   فقط کانفیگ (مثل vless://) دارید، هیچ ساب‌اسکریپشنی ندارید.\n\n"
                "4️⃣ <b>ساب تنها</b>\n"
                "   فقط لینک‌های ساب‌اسکریپشن دارید، کانفیگ مستقیم ندارید.", kb)
            return

        # adm:v2:bulk:pref:skip:{pkg_id}  or  adm:v2:bulk:suf:skip:{pkg_id}
        # (used only for config-bearing modes that need prefix/suffix stripping)
        if rest.startswith("pref:skip:"):
            pkg_id = int(rest.split(":")[2])
            s = state_data(uid)
            state_set(uid, "v2_bulk_suf",
                      package_id=s["package_id"], type_id=s["type_id"],
                      mode=s["mode"], prefix="")
            bot.answer_callback_query(call.id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏭ بدون پسوند", callback_data=f"adm:v2:bulk:suf:skip:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:v2:bulk:{pkg_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "✂️ <b>پسوند حذفی از نام کانفیگ</b>\n\n"
                "اگر انتهای نام کانفیگ‌ها متن اضافه‌ای دارد که نمی‌خواهید نمایش داده شود، اینجا وارد کنید.\n\n"
                "💡 مثال: <code>-main</code>\n\n"
                "اگر پسوندی ندارید دکمه «بدون پسوند» را بزنید.", kb)
            return

        if rest.startswith("suf:skip:"):
            pkg_id = int(rest.split(":")[2])
            s = state_data(uid)
            mode = s.get("mode", 1)
            state_set(uid, "v2_bulk_data",
                      package_id=s["package_id"], type_id=s["type_id"],
                      mode=mode, prefix=s.get("prefix", ""), suffix="")
            bot.answer_callback_query(call.id)
            prompt = _v2_bulk_data_prompt(mode)
            send_or_edit(call, prompt, back_button(f"adm:v2:bulk:{pkg_id}"))
            return

        return

    # adm:v2:bm:{mode}:{pkg_id}  → bulk mode selected → ask prefix (for configs) or go straight
    if data.startswith("adm:v2:bm:"):
        parts = data.split(":")
        mode       = int(parts[3])
        package_id = int(parts[4])
        s = state_data(uid)
        bot.answer_callback_query(call.id)

        if mode in (1, 2, 3):
            # Modes with configs → ask prefix
            state_set(uid, "v2_bulk_pre",
                      package_id=package_id, type_id=s.get("type_id", 0), mode=mode)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏭ بدون پیشوند", callback_data=f"adm:v2:bulk:pref:skip:{package_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:v2:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "✂️ <b>پیشوند حذفی از نام کانفیگ</b>\n\n"
                "اگر ابتدای نام کانفیگ‌ها متن اضافه‌ای (مثل ریمارک اینباند) دارد که نمی‌خواهید در نام سرویس باشد، اینجا وارد کنید.\n\n"
                "💡 مثال: <code>⚕️TUN_-</code>\n\n"
                "اگر پیشوندی ندارید دکمه «بدون پیشوند» را بزنید.", kb)
        else:  # mode 4: sub only — no prefix/suffix needed
            state_set(uid, "v2_bulk_data",
                      package_id=package_id, type_id=s.get("type_id", 0),
                      mode=4, prefix="", suffix="")
            prompt = _v2_bulk_data_prompt(4)
            send_or_edit(call, prompt, back_button(f"adm:v2:bulk:{package_id}"))
        return

    # ── V2Ray Mode 2 Bulk: Step 2 — receive subs after configs ───────────────
    # adm:v2:bm2subs:{pkg_id}  (button sent after config-block received)
    if data.startswith("adm:v2:bm2subs:"):
        package_id = int(data.split(":")[3])
        s = state_data(uid)
        config_count = len(s.get("v2_configs", []))
        state_set(uid, "v2_bulk_subs_large",
                  package_id=package_id, type_id=s.get("type_id", 0),
                  prefix=s.get("prefix", ""), suffix=s.get("suffix", ""),
                  v2_configs=s.get("v2_configs", []))
        bot.answer_callback_query(call.id)
        bot.send_message(uid,
            f"✅ <b>{config_count}</b> کانفیگ دریافت شد.\n\n"
            "📋 <b>حالا همه ساب‌ها را ارسال کنید.</b>\n\n"
            f"⚠️ باید دقیقاً <b>{config_count}</b> ساب ارسال کنید تا با کانفیگ‌ها جفت شوند.\n"
            "ترتیب مهم است: ساب اول با کانفیگ اول جفت می‌شود، ساب دوم با کانفیگ دوم و ...\n\n"
            "📎 می‌توانید یک فایل <b>.txt</b> (هر خط یک ساب) ارسال کنید.",
            parse_mode="HTML",
            reply_markup=back_button(f"adm:v2:bulk:{package_id}"))
        return

    # ── Legacy: adm:cfg:single / adm:cfg:bulk (redirect) ─────────────────────
    if data.startswith("adm:cfg:single:"):
        package_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        # Redirect to new V2Ray single flow
        package_row = get_package(package_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("1️⃣ ثبت کانفیگ + ساب جداگانه", callback_data=f"adm:v2:sm:1:{package_id}"))
        kb.add(types.InlineKeyboardButton("2️⃣ ثبت کانفیگ تنها",          callback_data=f"adm:v2:sm:2:{package_id}"))
        kb.add(types.InlineKeyboardButton("3️⃣ ثبت ساب تنها",             callback_data=f"adm:v2:sm:3:{package_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:proto:v2ray:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📝 <b>ثبت تکی V2Ray</b>\n\nنوع ثبت را انتخاب کنید:", kb)
        return

    if data.startswith("adm:cfg:bulk:"):
        # Could be adm:cfg:bulk:{pkg_id} or adm:cfg:bulk:inq:y/n:{pkg_id} or adm:cfg:bulk:skip:...
        rest = data[len("adm:cfg:bulk:"):]

        # Skip prefix
        if rest.startswith("skippre:"):
            pkg_id = int(rest.split(":")[1])
            s = state_data(uid)
            state_set(uid, "admin_bulk_suffix",
                      package_id=s["package_id"], type_id=s["type_id"],
                      has_inquiry=s["has_inquiry"], prefix="")
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "✂️ <b>پسوند حذفی از نام کانفیگ</b>\n\n"
                "وقتی چندتا اکسترنال پروکسی ست می‌کنید، انتهای نام کانفیگ متن‌های اضافه اکسترنال‌ها اضافه می‌شود.\n"
                "اگر نمی‌خواهید آن‌ها در نام کانفیگ بیاید، پسوند را اینجا وارد کنید.\n\n"
                "💡 مثال: <code>-main</code>",
                back_button("admin:add_config"))
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏭ بعدی (بدون پسوند)", callback_data=f"adm:cfg:bulk:skipsuf:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:add_config", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "✂️ <b>پسوند حذفی از نام کانفیگ</b>\n\n"
                "وقتی چندتا اکسترنال پروکسی ست می‌کنید، انتهای نام کانفیگ متن‌های اضافه اکسترنال‌ها اضافه می‌شود.\n"
                "اگر نمی‌خواهید آن‌ها در نام کانفیگ بیاید، پسوند را اینجا وارد کنید.\n\n"
                "💡 مثال: <code>-main</code>", kb)
            return

        # Skip suffix
        if rest.startswith("skipsuf:"):
            pkg_id = int(rest.split(":")[1])
            s = state_data(uid)
            has_inq = s.get("has_inquiry", False)
            prefix = s.get("prefix", "")
            state_set(uid, "admin_bulk_data",
                      package_id=s["package_id"], type_id=s["type_id"],
                      has_inquiry=has_inq, prefix=prefix, suffix="")
            bot.answer_callback_query(call.id)
            if has_inq:
                fmt_text = (
                    "📋 <b>ارسال کانفیگ‌ها</b>\n\n"
                    "کانفیگ‌ها را ارسال کنید. دو روش وجود دارد:\n\n"
                    "<b>📝 روش اول: ارسال متنی</b>\n"
                    "هر کانفیگ <b>دو خط</b> دارد:\n"
                    "خط اول: لینک کانفیگ\n"
                    "خط دوم: لینک استعلام (شروع با http)\n\n"
                    "💡 مثال:\n"
                    "<code>vless://abc...#name1\n"
                    "http://panel.com/sub/1\n"
                    "vless://def...#name2\n"
                    "http://panel.com/sub/2</code>\n\n"
                    "<b>📎 روش دوم: ارسال فایل TXT</b>\n"
                    "اگر تعداد کانفیگ‌هایتان زیاد است (بیش از ۱۰-۱۵ عدد)، "
                    "یک فایل <b>.txt</b> بسازید و تمام لینک‌ها را در آن قرار دهید "
                    "(هر خط یک کانفیگ + خط بعدی لینک استعلام)، سپس فایل را ارسال کنید."
                )
            else:
                fmt_text = (
                    "📋 <b>ارسال کانفیگ‌ها</b>\n\n"
                    "کانفیگ‌ها را ارسال کنید. دو روش وجود دارد:\n\n"
                    "<b>📝 روش اول: ارسال متنی</b>\n"
                    "هر خط یک لینک کانفیگ:\n\n"
                    "💡 مثال:\n"
                    "<code>vless://abc...#name1\n"
                    "vless://def...#name2</code>\n\n"
                    "<b>📎 روش دوم: ارسال فایل TXT</b>\n"
                    "اگر تعداد کانفیگ‌هایتان زیاد است (بیش از ۱۰-۱۵ عدد)، "
                    "یک فایل <b>.txt</b> بسازید و تمام لینک کانفیگ‌ها را در آن قرار دهید "
                    "(هر خط یک کانفیگ)، سپس فایل را ارسال کنید."
                )
            send_or_edit(call, fmt_text, back_button("admin:add_config"))
            return

        # Inquiry yes/no
        if rest.startswith("inq:"):
            sub_parts = rest.split(":")
            yn = sub_parts[1]
            pkg_id = int(sub_parts[2])
            has_inq = (yn == "y")
            state_set(uid, "admin_bulk_prefix",
                      package_id=pkg_id, type_id=state_data(uid).get("type_id", 0),
                      has_inquiry=has_inq)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏭ بعدی (بدون پیشوند)", callback_data=f"adm:cfg:bulk:skippre:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:add_config", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "✂️ <b>پیشوند حذفی از نام کانفیگ</b>\n\n"
                "زمانی که کانفیگ را در پنل می‌سازید، اگر اینباند <b>ریمارک (Remark)</b> دارد، "
                "ابتدای نام کانفیگ اضافه می‌شود.\n"
                "اگر نمی‌خواهید آن در نام کانفیگ بیاید، پیشوند را اینجا وارد کنید.\n\n"
                "💡 مثال: <code>%E2%9A%95%EF%B8%8FTUN_-</code>\n"
                "یا: <code>⚕️TUN_-</code>", kb)
            return

        # Initial: ask about inquiry links
        package_id  = int(rest)
        package_row = get_package(package_id)
        state_set(uid, "admin_bulk_init", package_id=package_id, type_id=package_row["type_id"])
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ بله", callback_data=f"adm:cfg:bulk:inq:y:{package_id}"),
            types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:cfg:bulk:inq:n:{package_id}"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:cfg:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔗 آیا کانفیگ‌ها <b>لینک استعلام</b> هم دارند؟", kb)
        return

    # ── Admin: Stock / Config management ─────────────────────────────────────
    if data == "admin:stock":
        if not (admin_has_perm(uid, "view_configs") or admin_has_perm(uid, "register_config") or admin_has_perm(uid, "manage_configs")):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        _show_admin_stock(call)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("adm:stk:all:"):
        parts     = data.split(":")
        kind_str  = parts[3]
        page      = int(parts[4])
        # Query all configs across packages
        offset = page * CONFIGS_PER_PAGE
        with get_conn() as conn:
            if kind_str == "sl":
                cfgs = conn.execute(
                    "SELECT * FROM configs WHERE sold_to IS NOT NULL ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) AS n FROM configs WHERE sold_to IS NOT NULL").fetchone()["n"]
            elif kind_str == "ex":
                cfgs = conn.execute(
                    "SELECT * FROM configs WHERE is_expired=1 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) AS n FROM configs WHERE is_expired=1").fetchone()["n"]
            else:
                cfgs = conn.execute(
                    "SELECT * FROM configs WHERE sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (CONFIGS_PER_PAGE, offset)
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) AS n FROM configs WHERE sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0").fetchone()["n"]
        total_pages = max(1, (total + CONFIGS_PER_PAGE - 1) // CONFIGS_PER_PAGE)
        kb         = types.InlineKeyboardMarkup()
        for c in cfgs:
            if c["is_expired"]:
                mark = "❌"
            elif c["sold_to"]:
                mark = "🔴"
            else:
                mark = "🟢"
            svc = urllib.parse.unquote(c["service_name"] or "")
            kb.add(types.InlineKeyboardButton(f"{mark} {svc}", callback_data=f"adm:stk:cfg:{c['id']}"))
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"adm:stk:all:{kind_str}:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"adm:stk:all:{kind_str}:{page+1}"))
        if nav_row:
            kb.row(*nav_row)
        # Bulk action buttons
        if kind_str in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton("🗑 حذف همگانی",   callback_data=f"adm:stk:blkA:{kind_str}"),
                types.InlineKeyboardButton("❌ منقضی همگانی", callback_data=f"adm:stk:blkA:{kind_str}"),
            )
        else:
            kb.add(types.InlineKeyboardButton("🗑 حذف همگانی", callback_data=f"adm:stk:blkA:{kind_str}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:stock", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        if kind_str == "sl":
            label_kind = "🔴 کل فروخته شده"
        elif kind_str == "ex":
            label_kind = "❌ کل منقضی شده"
        else:
            label_kind = "🟢 کل موجود"
        send_or_edit(call, f"📋 {label_kind} | صفحه {page+1}/{total_pages} | تعداد کل: {total}", kb)
        return

    if data.startswith("adm:stk:pk:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        avail = count_configs(package_id, sold=False)
        sold  = count_configs(package_id, sold=True)
        with get_conn() as conn:
            expired = conn.execute(
                "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND is_expired=1",
                (package_id,)
            ).fetchone()["n"]
            pending_c = conn.execute(
                "SELECT COUNT(*) AS n FROM pending_orders WHERE package_id=? AND status='waiting'",
                (package_id,)
            ).fetchone()["n"]
        kb    = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"🟢 مانده ({avail})",       callback_data=f"adm:stk:av:{package_id}:0"),
            types.InlineKeyboardButton(f"🔴 فروخته ({sold})",       callback_data=f"adm:stk:sl:{package_id}:0"),
        )
        kb.add(types.InlineKeyboardButton(f"❌ منقضی ({expired})",  callback_data=f"adm:stk:ex:{package_id}:0"))
        if pending_c > 0:
            kb.add(types.InlineKeyboardButton(
                f"⏳ تحویل {pending_c} سفارش در انتظار",
                callback_data=f"adm:stk:fulfill:{package_id}"
            ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:stock", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        pending_line = f"\n⏳ سفارش در انتظار: {pending_c}" if pending_c > 0 else ""
        text = (
            f"📦 <b>{esc(package_row['name'])}</b>\n\n"
            f"🟢 موجود: {avail}\n"
            f"🔴 فروخته شده: {sold}\n"
            f"❌ منقضی شده: {expired}"
            f"{pending_line}"
        )
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:stk:fulfill:") and data.split(":")[3].isdigit():
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        with get_conn() as conn:
            pending_c = conn.execute(
                "SELECT COUNT(*) AS n FROM pending_orders WHERE package_id=? AND status='waiting'",
                (package_id,)
            ).fetchone()["n"]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "⚡ تحویل خودکار از موجودی",
            callback_data=f"adm:stk:fulfill:auto:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton(
            "📝 ثبت کانفیگ جدید (تکی/عمده) + تحویل",
            callback_data=f"adm:stk:fulfill:addcfg:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:stk:pk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"⏳ <b>تحویل {pending_c} سفارش در انتظار</b>\n\n"
            f"📦 پکیج: <b>{esc(package_row['name'])}</b>\n\n"
            "روش تحویل را انتخاب کنید:", kb)
        return

    # adm:stk:fulfill:auto:{pkg_id}  →  auto-deliver from existing stock
    if data.startswith("adm:stk:fulfill:auto:"):
        package_id = int(data.split(":")[4])
        bot.answer_callback_query(call.id, "⏳ در حال تحویل سفارش‌ها...")
        try:
            fulfilled = auto_fulfill_pending_orders(package_id)
            if fulfilled > 0:
                send_or_edit(call,
                    f"✅ <b>{fulfilled}</b> سفارش با موفقیت از موجودی تحویل داده شد.",
                    back_button(f"adm:stk:pk:{package_id}"))
            else:
                with get_conn() as conn:
                    remaining = conn.execute(
                        "SELECT COUNT(*) AS n FROM pending_orders WHERE package_id=? AND status='waiting'",
                        (package_id,)
                    ).fetchone()["n"]
                if remaining > 0:
                    send_or_edit(call,
                        f"⚠️ <b>{remaining}</b> سفارش در انتظار وجود دارد ولی موجودی کافی نیست.\n\n"
                        "برای ثبت کانفیگ جدید روی دکمه «ثبت کانفیگ جدید» بزنید.",
                        back_button(f"adm:stk:pk:{package_id}"))
                else:
                    send_or_edit(call, "✅ هیچ سفارش در انتظاری وجود ندارد.",
                                 back_button(f"adm:stk:pk:{package_id}"))
        except Exception as e:
            send_or_edit(call,
                f"❌ خطا:\n<code>{esc(str(e))}</code>",
                back_button(f"adm:stk:pk:{package_id}"))
        return

    # adm:stk:fulfill:addcfg:{pkg_id}  →  register new config(s) then auto-deliver
    if data.startswith("adm:stk:fulfill:addcfg:"):
        package_id  = int(data.split(":")[4])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        # Redirect to the normal config-registration protocol selector,
        # but save fulfill_after=True in state so after registration runs auto_fulfill.
        state_set(uid, "admin_cfg_proto_select",
                  package_id=package_id,
                  type_id=package_row["type_id"],
                  fulfill_after=True)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🌐 V2Ray",    callback_data=f"adm:cfg:proto:v2ray:{package_id}"))
        kb.add(types.InlineKeyboardButton("🔒 OpenVPN",  callback_data=f"adm:cfg:proto:ovpn:{package_id}"))
        kb.add(types.InlineKeyboardButton("🛡 WireGuard", callback_data=f"adm:cfg:proto:wg:{package_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:stk:fulfill:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📦 <b>{esc(package_row['name'])}</b>\n\n"
            "🔌 <b>پروتکل کانفیگ جدید را انتخاب کنید:</b>\n"
            "<i>پس از ثبت، سفارش‌های در انتظار به‌صورت خودکار تحویل داده می‌شوند.</i>", kb)
        return

    # adm:stk:fulfill:addcfg:{pkg_id}  →  register new config(s) then auto-deliver
    if data.startswith("adm:stk:fulfill:addcfg:"):
        package_id  = int(data.split(":")[4])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "پکیج یافت نشد.", show_alert=True)
            return
        # Redirect to the normal config-registration protocol selector,
        # but save fulfill_after=True in state so after registration runs auto_fulfill.
        state_set(uid, "admin_cfg_proto_select",
                  package_id=package_id,
                  type_id=package_row["type_id"],
                  fulfill_after=True)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🌐 V2Ray",    callback_data=f"adm:cfg:proto:v2ray:{package_id}"))
        kb.add(types.InlineKeyboardButton("🔒 OpenVPN",  callback_data=f"adm:cfg:proto:ovpn:{package_id}"))
        kb.add(types.InlineKeyboardButton("🛡 WireGuard", callback_data=f"adm:cfg:proto:wg:{package_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:stk:fulfill:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📦 <b>{esc(package_row['name'])}</b>\n\n"
            "🔌 <b>پروتکل کانفیگ جدید را انتخاب کنید:</b>\n"
            "<i>پس از ثبت، سفارش‌های در انتظار به‌صورت خودکار تحویل داده می‌شوند.</i>", kb)
        return

    if data.startswith("adm:stk:av:") or data.startswith("adm:stk:sl:") or data.startswith("adm:stk:ex:"):
        parts      = data.split(":")
        kind_str   = parts[2]
        package_id = int(parts[3])
        page       = int(parts[4])
        offset     = page * CONFIGS_PER_PAGE
        with get_conn() as conn:
            if kind_str == "sl":
                cfgs = conn.execute(
                    "SELECT * FROM configs WHERE package_id=? AND sold_to IS NOT NULL ORDER BY id DESC LIMIT ? OFFSET ?",
                    (package_id, CONFIGS_PER_PAGE, offset)
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND sold_to IS NOT NULL",
                    (package_id,)
                ).fetchone()["n"]
            elif kind_str == "ex":
                cfgs = conn.execute(
                    "SELECT * FROM configs WHERE package_id=? AND is_expired=1 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (package_id, CONFIGS_PER_PAGE, offset)
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND is_expired=1",
                    (package_id,)
                ).fetchone()["n"]
            else:
                cfgs = conn.execute(
                    "SELECT * FROM configs WHERE package_id=? AND sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (package_id, CONFIGS_PER_PAGE, offset)
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND sold_to IS NULL AND reserved_payment_id IS NULL AND is_expired=0",
                    (package_id,)
                ).fetchone()["n"]
        total_pages = max(1, (total + CONFIGS_PER_PAGE - 1) // CONFIGS_PER_PAGE)
        kb         = types.InlineKeyboardMarkup()
        for c in cfgs:
            if c["is_expired"]:
                mark = "❌"
            elif c["sold_to"]:
                mark = "🔴"
            else:
                mark = "🟢"
            svc = urllib.parse.unquote(c["service_name"] or "")
            kb.add(types.InlineKeyboardButton(f"{mark} {svc}", callback_data=f"adm:stk:cfg:{c['id']}"))
        # Pagination
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton("⬅️ قبل", callback_data=f"adm:stk:{kind_str}:{package_id}:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton("بعد ➡️", callback_data=f"adm:stk:{kind_str}:{package_id}:{page+1}"))
        if nav_row:
            kb.row(*nav_row)
        # Bulk action buttons
        if kind_str in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton("🗑 حذف همگانی",   callback_data=f"adm:stk:blk:{kind_str}:{package_id}"),
                types.InlineKeyboardButton("❌ منقضی همگانی", callback_data=f"adm:stk:blk:{kind_str}:{package_id}"),
            )
        else:
            kb.add(types.InlineKeyboardButton("🗑 حذف همگانی", callback_data=f"adm:stk:blk:{kind_str}:{package_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:stk:pk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        if kind_str == "sl":
            label_kind = "🔴 فروخته شده"
        elif kind_str == "ex":
            label_kind = "❌ منقضی شده"
        else:
            label_kind = "🟢 موجود"
        send_or_edit(call, f"📋 {label_kind} | صفحه {page+1}/{total_pages} | تعداد کل: {total}", kb)
        return

    if data.startswith("adm:stk:cfg:"):
        config_id = int(data.split(":")[3])
        with get_conn() as conn:
            row = conn.execute(
                """SELECT c.*, p.name AS pkg_name, p.volume_gb, p.duration_days, t.name AS type_name
                   FROM configs c
                   JOIN packages p ON p.id=c.package_id
                   JOIN config_types t ON t.id=c.type_id
                   WHERE c.id=?""",
                (config_id,)
            ).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "یافت نشد.", show_alert=True)
            return
        _has_cfg = bool(row['config_text'] and row['config_text'].strip())
        _has_sub = bool(row['inquiry_link'] and row['inquiry_link'].strip())
        if _has_cfg and _has_sub:
            _reg_mode = "کانفیگ + ساب"
        elif _has_cfg:
            _reg_mode = "کانفیگ تنها"
        elif _has_sub:
            _reg_mode = "ساب تنها"
        else:
            _reg_mode = "—"
        text = (
            f"🔮 نام سرویس: <b>{esc(urllib.parse.unquote(row['service_name'] or ''))}</b>\n"
            f"🧩 نوع سرویس: {esc(row['type_name'])}\n"
            f"📌 نوع ثبت: {_reg_mode}\n"
            f"🔋 حجم: {fmt_vol(row['volume_gb'])}\n"
            f"⏰ مدت: {fmt_dur(row['duration_days'])}\n\n"
        )
        if _has_cfg:
            text += f"💝 Config:\n<code>{esc(row['config_text'])}</code>\n\n"
        if _has_sub:
            text += f"🔗 Subscription:\n<code>{esc(row['inquiry_link'])}</code>\n\n"
        text += f"🗓 ثبت: {esc(row['created_at'])}"
        kb = types.InlineKeyboardMarkup()
        if row["sold_to"]:
            buyer = get_user_detail(row["sold_to"])
            if buyer:
                text += (
                    f"\n\n🛒 <b>خریدار:</b>\n"
                    f"نام: {esc(buyer['full_name'])}\n"
                    f"نام کاربری: {esc(display_username(buyer['username']))}\n"
                    f"آیدی: <code>{buyer['user_id']}</code>\n"
                    f"زمان خرید: {esc(row['sold_at'] or '-')}"
                )
        if not row["is_expired"]:
            kb.add(types.InlineKeyboardButton("❌ منقضی کردن", callback_data=f"adm:stk:exp:{config_id}:{row['package_id']}"))
        else:
            text += "\n\n⚠️ این سرویس منقضی شده است."
        kb.row(
            types.InlineKeyboardButton("✏️ ویرایش", callback_data=f"adm:stk:edt:{config_id}"),
            types.InlineKeyboardButton("🗑 حذف کانفیگ", callback_data=f"adm:stk:del:{config_id}:{row['package_id']}"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:stk:pk:{row['package_id']}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        # Send with QR code
        try:
            qr_img = qrcode.make(row['config_text'])
            bio = io.BytesIO()
            qr_img.save(bio, format="PNG")
            bio.seek(0)
            bio.name = "qrcode.png"
            chat_id = call.message.chat.id
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            bot.send_photo(chat_id, bio, caption=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            send_or_edit(call, text, kb)
        return

    if data.startswith("adm:stk:edt:"):
        parts = data.split(":")
        # adm:stk:edt:{config_id}                 → edit menu
        # adm:stk:edt:pkg:{config_id}             → choose type for package edit
        # adm:stk:edt:pkgt:{config_id}:{type_id}  → choose package within type
        # adm:stk:edt:pkgp:{config_id}:{pkg_id}   → confirm package change
        # adm:stk:edt:svc:{config_id}             → edit service name
        # adm:stk:edt:cfg:{config_id}             → edit config text
        # adm:stk:edt:inq:{config_id}             → edit inquiry link

        sub = parts[3] if len(parts) > 3 else ""

        if sub == "pkg":
            config_id  = int(parts[4])
            types_list = get_all_types()
            kb = types.InlineKeyboardMarkup()
            for t in types_list:
                kb.add(types.InlineKeyboardButton(
                    esc(t["name"]),
                    callback_data=f"adm:stk:edt:pkgt:{config_id}:{t['id']}"
                ))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:stk:edt:{config_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "🧩 نوع سرویس را انتخاب کنید:", kb)
            return

        if sub == "pkgt":
            config_id = int(parts[4])
            type_id   = int(parts[5])
            pkgs = get_packages(type_id)
            kb = types.InlineKeyboardMarkup()
            for p in pkgs:
                label = f"{esc(p['name'])} | {fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])}"
                kb.add(types.InlineKeyboardButton(
                    label,
                    callback_data=f"adm:stk:edt:pkgp:{config_id}:{p['id']}"
                ))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:stk:edt:pkg:{config_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "📦 پکیج را انتخاب کنید:", kb)
            return

        if sub == "pkgp":
            config_id  = int(parts[4])
            package_id = int(parts[5])
            pkg = get_package(package_id)
            update_config_field(config_id, "package_id", package_id)
            if pkg:
                update_config_field(config_id, "type_id", pkg["type_id"])
            log_admin_action(uid, f"پکیج کانفیگ #{config_id} به #{package_id} تغییر کرد")
            bot.answer_callback_query(call.id, "✅ پکیج تغییر کرد.")
            _fake_call(call, f"adm:stk:cfg:{config_id}")
            return

        if sub == "svc":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_svc", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, "✏️ نام سرویس جدید را ارسال کنید:", back_button(f"adm:stk:edt:{config_id}"))
            return

        if sub == "cfg":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_text", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, "💝 متن کانفیگ جدید را ارسال کنید:", back_button(f"adm:stk:edt:{config_id}"))
            return

        if sub == "inq":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_inq", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "🔗 لینک استعلام جدید را ارسال کنید.\n"
                "برای حذف لینک، <code>-</code> بفرستید.",
                back_button(f"adm:stk:edt:{config_id}"))
            return

        # Default: show edit menu
        config_id = int(sub)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📦 ویرایش پکیج",         callback_data=f"adm:stk:edt:pkg:{config_id}"))
        kb.add(types.InlineKeyboardButton("🔮 ویرایش نام سرویس",    callback_data=f"adm:stk:edt:svc:{config_id}"))
        kb.add(types.InlineKeyboardButton("💝 ویرایش متن کانفیگ",   callback_data=f"adm:stk:edt:cfg:{config_id}"))
        kb.add(types.InlineKeyboardButton("🔗 ویرایش لینک استعلام", callback_data=f"adm:stk:edt:inq:{config_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:stk:cfg:{config_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "✏️ <b>ویرایش کانفیگ</b>\n\nچه چیزی را ویرایش می‌کنید؟", kb)
        return

    if data.startswith("adm:stk:exp:"):
        parts = data.split(":")
        config_id  = int(parts[3])
        package_id = int(parts[4]) if len(parts) > 4 else 0
        # Notify buyer if any
        with get_conn() as conn:
            row = conn.execute("SELECT sold_to FROM configs WHERE id=?", (config_id,)).fetchone()
        if row and row["sold_to"]:
            try:
                bot.send_message(
                    row["sold_to"],
                    "⚠️ یکی از سرویس‌های شما توسط ادمین منقضی اعلام شده است.\nبرای تمدید با پشتیبانی تماس بگیرید."
                )
            except Exception:
                pass
        bot.answer_callback_query(call.id, "سرویس منقضی شد.")
        back = back_button(f"adm:stk:pk:{package_id}") if package_id else back_button("admin:stock")
        send_or_edit(call, "✅ سرویس منقضی اعلام شد.", back)
        return

    if data.startswith("adm:stk:del:"):
        parts = data.split(":")
        config_id  = int(parts[3])
        package_id = int(parts[4]) if len(parts) > 4 else 0
        with get_conn() as conn:
            conn.execute("DELETE FROM configs WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "کانفیگ حذف شد.")
        back = back_button(f"adm:stk:pk:{package_id}") if package_id else back_button("admin:stock")
        send_or_edit(call, "✅ کانفیگ با موفقیت حذف شد.", back)
        return

    # ── Admin: Bulk select — All packages entry (must be before blk: check) ──
    if data.startswith("adm:stk:blkA:"):
        kind = data.split(":")[3]  # av / sl / ex
        if not (admin_has_perm(uid, "manage_configs") or uid in ADMIN_IDS):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "stk_bulk", kind=kind, scope="all", pkg_id=0, page=0, selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ── Admin: Bulk select — Per-package entry ────────────────────────────────
    if data.startswith("adm:stk:blk:"):
        parts  = data.split(":")
        kind   = parts[3]         # av / sl / ex
        pkg_id = int(parts[4])    # package_id
        if not (admin_has_perm(uid, "manage_configs") or uid in ADMIN_IDS):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "stk_bulk", kind=kind, scope="pk", pkg_id=pkg_id, page=0, selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ── Admin: Bulk select — Toggle individual config ─────────────────────────
    if data.startswith("adm:stk:btog:"):
        cfg_id   = int(data.split(":")[3])
        sd       = state_data(uid)
        sel_raw  = sd.get("selected", "")
        selected = set(int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit())
        if cfg_id in selected:
            selected.discard(cfg_id)
        else:
            selected.add(cfg_id)
        state_set(uid, "stk_bulk",
                  kind=sd.get("kind", "av"), scope=sd.get("scope", "pk"),
                  pkg_id=sd.get("pkg_id", 0), page=sd.get("page", 0),
                  selected=",".join(str(x) for x in selected))
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ── Admin: Bulk select — Select all on current page ───────────────────────
    if data == "adm:stk:bsall":
        sd       = state_data(uid)
        sel_raw  = sd.get("selected", "")
        selected = set(int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit())
        selected.update(_get_bulk_page_ids(sd))
        state_set(uid, "stk_bulk",
                  kind=sd.get("kind", "av"), scope=sd.get("scope", "pk"),
                  pkg_id=sd.get("pkg_id", 0), page=sd.get("page", 0),
                  selected=",".join(str(x) for x in selected))
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ── Admin: Bulk select — Deselect current page ────────────────────────────
    if data == "adm:stk:bclr":
        sd       = state_data(uid)
        sel_raw  = sd.get("selected", "")
        selected = set(int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit())
        for cid in _get_bulk_page_ids(sd):
            selected.discard(cid)
        state_set(uid, "stk_bulk",
                  kind=sd.get("kind", "av"), scope=sd.get("scope", "pk"),
                  pkg_id=sd.get("pkg_id", 0), page=sd.get("page", 0),
                  selected=",".join(str(x) for x in selected))
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ── Admin: Bulk select — Clear all selections ─────────────────────────────
    if data == "adm:stk:bclrall":
        sd = state_data(uid)
        state_set(uid, "stk_bulk",
                  kind=sd.get("kind", "av"), scope=sd.get("scope", "pk"),
                  pkg_id=sd.get("pkg_id", 0), page=sd.get("page", 0),
                  selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ── Admin: Bulk select — Navigate pages ───────────────────────────────────
    if data.startswith("adm:stk:bnav:"):
        new_page = int(data.split(":")[3])
        sd = state_data(uid)
        state_set(uid, "stk_bulk",
                  kind=sd.get("kind", "av"), scope=sd.get("scope", "pk"),
                  pkg_id=sd.get("pkg_id", 0), page=new_page,
                  selected=sd.get("selected", ""))
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ── Admin: Bulk select — Execute delete ───────────────────────────────────
    if data == "adm:stk:bdel":
        sd      = state_data(uid)
        sel_raw = sd.get("selected", "")
        ids     = [int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit()]
        if not ids:
            bot.answer_callback_query(call.id, "⚠️ هیچ موردی انتخاب نشده.", show_alert=True)
            return
        with get_conn() as conn:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM configs WHERE id IN ({placeholders})", ids)
        state_clear(uid)
        bot.answer_callback_query(call.id, f"✅ {len(ids)} کانفیگ حذف شد.", show_alert=True)
        send_or_edit(call, f"✅ <b>{len(ids)}</b> کانفیگ با موفقیت حذف شد.", back_button("admin:stock"))
        return

    # ── Admin: Bulk select — Execute expire ───────────────────────────────────
    if data == "adm:stk:bexp":
        sd      = state_data(uid)
        sel_raw = sd.get("selected", "")
        ids     = [int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit()]
        if not ids:
            bot.answer_callback_query(call.id, "⚠️ هیچ موردی انتخاب نشده.", show_alert=True)
            return
        with get_conn() as conn:
            for cfg_id in ids:
                conn.execute("UPDATE configs SET is_expired=1 WHERE id=?", (cfg_id,))
        state_clear(uid)
        bot.answer_callback_query(call.id, f"✅ {len(ids)} کانفیگ منقضی شد.", show_alert=True)
        send_or_edit(call, f"✅ <b>{len(ids)}</b> کانفیگ منقضی اعلام شد.", back_button("admin:stock"))
        return

    # ── Admin: Bulk select — Cancel / back ────────────────────────────────────
    if data == "adm:stk:bcanc":
        sd     = state_data(uid)
        kind   = sd.get("kind", "av")
        scope  = sd.get("scope", "pk")
        pkg_id = int(sd.get("pkg_id", 0))
        state_clear(uid)
        bot.answer_callback_query(call.id)
        if scope == "pk":
            _fake_call(call, f"adm:stk:{kind}:{pkg_id}:0")
        else:
            _fake_call(call, f"adm:stk:all:{kind}:0")
        return

    # ── Admin: Stock Search ───────────────────────────────────────────────────
    if data == "adm:stk:search":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔗 لینک استعلام", callback_data="adm:stk:srch:link"))
        kb.add(types.InlineKeyboardButton("💝 متن کانفیگ", callback_data="adm:stk:srch:cfg"))
        kb.add(types.InlineKeyboardButton("🔮 نام سرویس", callback_data="adm:stk:srch:name"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:stock", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "🔍 جستجو بر اساس:", kb)
        bot.answer_callback_query(call.id)
        return

    if data == "adm:stk:srch:link":
        state_set(call.from_user.id, "admin_search_by_link")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔗 لینک استعلام (یا بخشی از آن) را ارسال کنید:", back_button("adm:stk:search"))
        return

    if data == "adm:stk:srch:cfg":
        state_set(call.from_user.id, "admin_search_by_config")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "💝 متن کانفیگ (یا بخشی از آن) را ارسال کنید:", back_button("adm:stk:search"))
        return

    if data == "adm:stk:srch:name":
        state_set(call.from_user.id, "admin_search_by_name")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔮 نام سرویس (یا بخشی از آن) را ارسال کنید:", back_button("adm:stk:search"))
        return

    # ── Admin: Users ──────────────────────────────────────────────────────────
    if data == "admin:users":
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        _show_admin_users_list(call)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("admin:users:pg:"):
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        page = int(data.split(":")[-1])
        _show_admin_users_list(call, page=page)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("adm:usr:fl:"):
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts       = data.split(":")
        filter_mode = parts[3]
        page        = int(parts[4]) if len(parts) > 4 else 0
        _show_admin_users_list(call, page=page, filter_mode=filter_mode)
        bot.answer_callback_query(call.id)
        return

    # ── Admin: User search ────────────────────────────────────────────────────
    if data == "adm:usr:search":
        state_set(uid, "admin_user_search")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔍 <b>جستجوی کاربر</b>\n\n"
            "می‌توانید بر اساس موارد زیر جستجو کنید:\n"
            "• <b>آیدی عددی</b> (مثال: <code>123456789</code>)\n"
            "• <b>نام کاربری</b> (مثال: <code>@username</code>)\n"
            "• <b>نام اکانت</b> (مثال: <code>علی</code>)\n\n"
            "مقدار جستجو را ارسال کنید:",
            back_button("admin:users"))
        return

    # ── Admin: Bulk user operations ──────────────────────────────────────────
    if data == "adm:usr:bulk":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ اضافه کردن موجودی",      callback_data="adm:bulk:op:add_balance"))
        kb.add(types.InlineKeyboardButton("➖ کاهش موجودی",            callback_data="adm:bulk:op:sub_balance"))
        kb.add(types.InlineKeyboardButton("0️⃣ صفر کردن همه موجودی",    callback_data="adm:bulk:op:zero_balance"))
        kb.add(types.InlineKeyboardButton("🔘 امن کردن کاربران",        callback_data="adm:bulk:op:set_safe"))
        kb.add(types.InlineKeyboardButton("⚠️ ناامن کردن کاربران",      callback_data="adm:bulk:op:set_unsafe"))
        kb.add(types.InlineKeyboardButton("🚫 محدود کردن کاربران",      callback_data="adm:bulk:op:set_restricted"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:users",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "⚡ <b>عملیات گروهی</b>\n\nعملیات مورد نظر را انتخاب کنید:",
            kb)
        return

    if data.startswith("adm:bulk:op:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        op = data.split(":")[3]
        bot.answer_callback_query(call.id)
        _OP_LABELS = {
            "add_balance":    "➕ اضافه کردن موجودی",
            "sub_balance":    "➖ کاهش موجودی",
            "zero_balance":   "0️⃣ صفر کردن همه موجودی",
            "set_safe":       "🔘 امن کردن",
            "set_unsafe":     "⚠️ ناامن کردن",
            "set_restricted": "🚫 محدود کردن",
        }
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("👥 همه کاربران",        callback_data=f"adm:bulk:tgt:{op}:all"))
        kb.add(types.InlineKeyboardButton("👤 فقط کاربران عادی",   callback_data=f"adm:bulk:tgt:{op}:public"))
        kb.add(types.InlineKeyboardButton("🤝 فقط نمایندگان",      callback_data=f"adm:bulk:tgt:{op}:agents"))
        kb.add(types.InlineKeyboardButton("🔎 انتخاب کاربران خاص", callback_data=f"adm:bulk:tgt:{op}:pick:0"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:usr:bulk",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"⚡ <b>عملیات گروهی</b>: {_OP_LABELS.get(op, op)}\n\nروی چه دسته‌ای اعمال شود؟",
            kb)
        return

    if data.startswith("adm:bulk:tgt:"):
        # adm:bulk:tgt:{op}:{filter}  OR  adm:bulk:tgt:{op}:pick:{page}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        op     = parts[3]
        filt   = parts[4]

        if filt == "pick":
            # Paginated user picker
            page = int(parts[5]) if len(parts) > 5 else 0
            bot.answer_callback_query(call.id)
            _PER = 10
            all_users = get_users()
            total     = len(all_users)
            page_users = all_users[page * _PER:(page + 1) * _PER]
            total_pages = max(1, (total + _PER - 1) // _PER)

            # Load selected IDs from state
            sd = state_data(uid) if state_name(uid) == "bulk_pick" else {}
            selected = set(sd.get("selected", []))
            state_set(uid, "bulk_pick", op=op, selected=list(selected))

            kb = types.InlineKeyboardMarkup()
            for u in page_users:
                check = "✅" if u["user_id"] in selected else "⬜"
                name  = u["full_name"] or str(u["user_id"])
                kb.add(types.InlineKeyboardButton(
                    f"{check} {name[:25]}",
                    callback_data=f"adm:bulk:pick:{u['user_id']}:{page}"))

            nav = []
            if page > 0:
                nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm:bulk:tgt:{op}:pick:{page-1}"))
            nav.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav.append(types.InlineKeyboardButton("➡️", callback_data=f"adm:bulk:tgt:{op}:pick:{page+1}"))
            if nav:
                kb.row(*nav)
            kb.add(types.InlineKeyboardButton(
                f"✅ تایید و اجرا ({len(selected)} نفر انتخاب شده)",
                callback_data=f"adm:bulk:confirm:{op}:pick"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:bulk:op:{op}",
                                              icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                f"🔎 <b>انتخاب کاربران</b> — صفحه {page+1}/{total_pages}\n"
                f"✅ {len(selected)} نفر انتخاب شده\n\nکلیک کنید تا انتخاب/لغو شود:",
                kb)
            return

        # filter = all / public / agents → ask for amount if needed, else confirm
        bot.answer_callback_query(call.id)
        _needs_amount = op in ("add_balance", "sub_balance")
        if _needs_amount:
            state_set(uid, "bulk_amount", op=op, filter_type=filt)
            _FLT = {"all": "همه کاربران", "public": "کاربران عادی", "agents": "نمایندگان"}
            _OP_L = {"add_balance": "افزودن", "sub_balance": "کاهش"}
            send_or_edit(call,
                f"⚡ <b>عملیات گروهی</b>: {_OP_L[op]} موجودی\n"
                f"🎯 هدف: {_FLT.get(filt, filt)}\n\n"
                "💰 <b>مبلغ</b> (تومان) را وارد کنید:",
                back_button(f"adm:bulk:op:{op}"))
        else:
            count = count_users_by_filter(filt)
            state_set(uid, "bulk_confirm_ready", op=op, filter_type=filt, selected=[], amount=0)
            _FLT = {"all": "همه کاربران", "public": "کاربران عادی", "agents": "نمایندگان"}
            _OP_L2 = {
                "zero_balance": "صفر کردن موجودی",
                "set_safe": "امن کردن",
                "set_unsafe": "ناامن کردن",
                "set_restricted": "محدود کردن",
            }
            kb2 = types.InlineKeyboardMarkup()
            kb2.add(types.InlineKeyboardButton(
                f"✅ تایید — اجرا روی {count} کاربر",
                callback_data=f"adm:bulk:exec:{op}:{filt}:0"))
            kb2.add(types.InlineKeyboardButton("لغو", callback_data="adm:usr:bulk",
                                               icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                f"⚡ <b>تایید عملیات گروهی</b>\n\n"
                f"عملیات: <b>{_OP_L2.get(op, op)}</b>\n"
                f"هدف: <b>{_FLT.get(filt, filt)}</b>\n"
                f"تعداد کاربران: <b>{count}</b>",
                kb2)
        return

    if data.startswith("adm:bulk:pick:"):
        # Toggle a user in pick list
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id)
            return
        parts    = data.split(":")
        pick_uid = int(parts[3])
        page     = int(parts[4]) if len(parts) > 4 else 0
        sd       = state_data(uid) if state_name(uid) == "bulk_pick" else {}
        op       = sd.get("op", "")
        selected = set(sd.get("selected", []))
        if pick_uid in selected:
            selected.discard(pick_uid)
        else:
            selected.add(pick_uid)
        state_set(uid, "bulk_pick", op=op, selected=list(selected))
        bot.answer_callback_query(call.id, f"{'✅ انتخاب شد' if pick_uid in selected else '❌ لغو شد'}")
        # Re-render same page
        _PER      = 10
        all_users = get_users()
        total     = len(all_users)
        page_users = all_users[page * _PER:(page + 1) * _PER]
        total_pages = max(1, (total + _PER - 1) // _PER)
        kb = types.InlineKeyboardMarkup()
        for u in page_users:
            check = "✅" if u["user_id"] in selected else "⬜"
            name  = u["full_name"] or str(u["user_id"])
            kb.add(types.InlineKeyboardButton(
                f"{check} {name[:25]}",
                callback_data=f"adm:bulk:pick:{u['user_id']}:{page}"))
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm:bulk:tgt:{op}:pick:{page-1}"))
        nav.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(types.InlineKeyboardButton("➡️", callback_data=f"adm:bulk:tgt:{op}:pick:{page+1}"))
        if nav:
            kb.row(*nav)
        kb.add(types.InlineKeyboardButton(
            f"✅ تایید و اجرا ({len(selected)} نفر انتخاب شده)",
            callback_data=f"adm:bulk:confirm:{op}:pick"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:bulk:op:{op}",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"🔎 <b>انتخاب کاربران</b> — صفحه {page+1}/{total_pages}\n"
            f"✅ {len(selected)} نفر انتخاب شده:",
            kb)
        return

    if data.startswith("adm:bulk:confirm:"):
        # Confirm after manual pick — ask for amount if needed
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts    = data.split(":")
        op       = parts[3]
        sd       = state_data(uid) if state_name(uid) == "bulk_pick" else {}
        selected = sd.get("selected", [])
        if not selected:
            bot.answer_callback_query(call.id, "هیچ کاربری انتخاب نشده.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        if op in ("add_balance", "sub_balance"):
            state_set(uid, "bulk_amount", op=op, filter_type="pick", selected=selected)
            _OP_L = {"add_balance": "افزودن", "sub_balance": "کاهش"}
            send_or_edit(call,
                f"⚡ <b>عملیات گروهی</b>: {_OP_L[op]} موجودی\n"
                f"🎯 {len(selected)} کاربر انتخاب شده\n\n"
                "💰 <b>مبلغ</b> (تومان) را وارد کنید:",
                back_button(f"adm:bulk:op:{op}"))
        else:
            count = len(selected)
            _OP_L2 = {
                "zero_balance": "صفر کردن موجودی",
                "set_safe": "امن کردن",
                "set_unsafe": "ناامن کردن",
                "set_restricted": "محدود کردن",
            }
            sel_str = ",".join(str(x) for x in selected[:50])
            kb2 = types.InlineKeyboardMarkup()
            kb2.add(types.InlineKeyboardButton(
                f"✅ تایید — اجرا روی {count} کاربر",
                callback_data=f"adm:bulk:exec:{op}:pick:{sel_str}"))
            kb2.add(types.InlineKeyboardButton("لغو", callback_data="adm:usr:bulk",
                                               icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                f"⚡ <b>تایید عملیات گروهی</b>\n\n"
                f"عملیات: <b>{_OP_L2.get(op, op)}</b>\n"
                f"تعداد کاربران انتخاب شده: <b>{count}</b>",
                kb2)
        return

    if data.startswith("adm:bulk:exec:"):
        # Execute bulk operation
        # format: adm:bulk:exec:{op}:{filter_type}:{amount_or_sel}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts       = data.split(":")
        op          = parts[3]
        filter_type = parts[4]
        amount_or_sel = parts[5] if len(parts) > 5 else "0"

        if filter_type == "pick":
            user_ids = [int(x) for x in amount_or_sel.split(",") if x.isdigit()]
            amount   = int(parts[6]) if len(parts) > 6 else 0
        else:
            user_ids = []
            amount   = int(amount_or_sel) if amount_or_sel.isdigit() else 0

        bot.answer_callback_query(call.id, "⏳ در حال اجرا…")
        state_clear(uid)

        count = 0
        try:
            if op == "add_balance":
                count = bulk_add_balance(filter_type, user_ids, amount)
                result_msg = f"✅ موجودی {amount:,} تومان به {count} کاربر اضافه شد."
            elif op == "sub_balance":
                count = bulk_add_balance(filter_type, user_ids, -amount)
                result_msg = f"✅ موجودی {amount:,} تومان از {count} کاربر کم شد."
            elif op == "zero_balance":
                count = bulk_zero_balance(filter_type, user_ids)
                result_msg = f"✅ موجودی {count} کاربر صفر شد."
            elif op == "set_safe":
                count = bulk_set_status(filter_type, user_ids, "safe")
                result_msg = f"✅ {count} کاربر امن شدند."
            elif op == "set_unsafe":
                count = bulk_set_status(filter_type, user_ids, "unsafe")
                result_msg = f"✅ {count} کاربر ناامن شدند."
            elif op == "set_restricted":
                count = bulk_set_status(filter_type, user_ids, "restricted")
                result_msg = f"✅ {count} کاربر محدود شدند."
            else:
                result_msg = "❌ عملیات ناشناخته."
        except Exception as _e:
            result_msg = f"❌ خطا: {esc(str(_e)[:200])}"

        log_admin_action(uid, f"عملیات گروهی: {op} | filter={filter_type} | count={count}")
        kb_back = types.InlineKeyboardMarkup()
        kb_back.add(types.InlineKeyboardButton("بازگشت به کاربران", callback_data="admin:users",
                                               icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, result_msg, kb_back)
        return

    # ── Admin: Admins management ──────────────────────────────────────────────
    if data == "admin:admins":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "فقط اونر می‌تواند ادمین‌ها را مدیریت کند.", show_alert=True)
            return
        _show_admin_admins_panel(call)
        bot.answer_callback_query(call.id)
        return

    if data == "adm:mgr:add":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_mgr_await_id")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "➕ <b>افزودن ادمین جدید</b>\n\n"
            "آیدی عددی یا یوزرنیم کاربر مورد نظر را ارسال کنید:\n\n"
            "مثال: <code>123456789</code> یا <code>@username</code>",
            back_button("admin:admins"))
        return

    if data.startswith("adm:mgr:del:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        if target_id in ADMIN_IDS:
            bot.answer_callback_query(call.id, "اونرها را نمی‌توان حذف کرد.", show_alert=True)
            return
        remove_admin_user(target_id)
        bot.answer_callback_query(call.id, "✅ ادمین حذف شد.")
        log_admin_action(uid, f"ادمین <code>{target_id}</code> حذف شد")
        _show_admin_admins_panel(call)
        return

    if data.startswith("adm:mgr:v:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        row = get_admin_user(target_id)
        user_row = get_user(target_id)
        if not row:
            bot.answer_callback_query(call.id, "ادمین یافت نشد.", show_alert=True)
            return
        perms = json.loads(row["permissions"] or "{}")
        from ..ui.premium_emoji import ce as _ce
        def _perm_line(k, lbl):
            check = '✅' if perms.get(k) or perms.get('full') else '☐'
            eid = PERM_EMOJI_IDS.get(k)
            emoji_tag = _ce('⭐', eid) + ' ' if eid else ''
            return f"{check} {emoji_tag}{lbl}"
        perm_lines = "\n".join(
            _perm_line(k, lbl)
            for k, lbl in ADMIN_PERMS if k != "full"
        )
        name = user_row["full_name"] if user_row else f"کاربر {target_id}"
        text = (
            f"👮 <b>اطلاعات ادمین</b>\n\n"
            f"👤 نام: {esc(name)}\n"
            f"🆔 آیدی: <code>{target_id}</code>\n"
            f"📅 افزوده شده: {esc(row['added_at'])}\n\n"
            f"🔑 <b>دسترسی‌ها:</b>\n{perm_lines}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🗑 حذف ادمین", callback_data=f"adm:mgr:del:{target_id}"))
        kb.add(types.InlineKeyboardButton("✏️ ویرایش دسترسی‌ها", callback_data=f"adm:mgr:edit:{target_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:admins", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:mgr:edit:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        row = get_admin_user(target_id)
        if not row:
            bot.answer_callback_query(call.id, "ادمین یافت نشد.", show_alert=True)
            return
        perms = json.loads(row["permissions"] or "{}")
        state_set(uid, "admin_mgr_select_perms", target_user_id=target_id, perms=json.dumps(perms), edit_mode=True)
        bot.answer_callback_query(call.id)
        _show_perm_selection(call, uid, target_id, perms, edit_mode=True)
        return

    if data.startswith("adm:mgr:pt:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        perm_key = data[len("adm:mgr:pt:"):]
        sd2 = state_data(uid)
        if state_name(uid) != "admin_mgr_select_perms" or not sd2:
            bot.answer_callback_query(call.id, "جلسه منقضی شده است.", show_alert=True)
            return
        target_id = sd2.get("target_user_id")
        perms = json.loads(sd2.get("perms", "{}"))
        current = bool(perms.get(perm_key))

        if perm_key == "full":
            if not current:
                perms = {k: True for k, _ in ADMIN_PERMS}
            else:
                perms = {}
        elif perm_key == "full_users":
            if not current:
                perms["full_users"] = True
                perms["view_users"] = False
                for p in PERM_USER_FULL:
                    perms[p] = True
            else:
                perms["full_users"] = False
                for p in PERM_USER_FULL:
                    perms[p] = False
        elif perm_key == "view_users":
            if not current:
                perms["view_users"] = True
                perms["full_users"] = False
                for p in PERM_USER_FULL:
                    perms[p] = False
            else:
                perms["view_users"] = False
        else:
            perms[perm_key] = not current
            if perm_key in PERM_USER_FULL and perms.get(perm_key):
                perms["view_users"] = False
            if all(perms.get(p) for p in PERM_USER_FULL):
                perms["full_users"] = True
                perms["view_users"] = False
            if all(perms.get(k) for k, _ in ADMIN_PERMS if k != "full"):
                perms["full"] = True

        edit_mode = sd2.get("edit_mode", False)
        state_set(uid, "admin_mgr_select_perms",
                  target_user_id=target_id, perms=json.dumps(perms), edit_mode=edit_mode)
        bot.answer_callback_query(call.id)
        _show_perm_selection(call, uid, target_id, perms, edit_mode=edit_mode)
        return

    if data == "adm:mgr:confirm":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        sd2 = state_data(uid)
        if state_name(uid) != "admin_mgr_select_perms" or not sd2:
            bot.answer_callback_query(call.id, "جلسه منقضی شده است.", show_alert=True)
            return
        target_id = sd2.get("target_user_id")
        perms = json.loads(sd2.get("perms", "{}"))
        if not any(perms.values()):
            bot.answer_callback_query(call.id, "حداقل یک سطح دسترسی انتخاب کنید.", show_alert=True)
            return
        edit_mode = sd2.get("edit_mode", False)
        # Build human-readable permission list for notification
        perms_labels = {k: v for k, v in ADMIN_PERMS}
        active_perm_names = [perms_labels.get(k, k) for k, v in perms.items() if v]
        perm_text = "\n".join(f"• {p}" for p in active_perm_names) or "— بدون دسترسی —"
        if edit_mode:
            update_admin_permissions(target_id, perms)
            log_admin_action(uid, f"دسترسی‌های ادمین {target_id} به‌روزرسانی شد")
            state_clear(uid)
            bot.answer_callback_query(call.id, "✅ دسترسی‌ها به‌روز شد.")
            try:
                bot.send_message(target_id,
                    "🔑 <b>دسترسی‌های شما به‌روزرسانی شد</b>\n\n"
                    f"<b>دسترسی‌های فعال:</b>\n{perm_text}\n\n"
                    "برای استفاده از دسترسی‌های جدید از /start استفاده کنید.")
            except Exception:
                pass
        else:
            add_admin_user(target_id, uid, perms)
            log_admin_action(uid, f"ادمین جدید {target_id} اضافه شد")
            state_clear(uid)
            bot.answer_callback_query(call.id, "✅ ادمین اضافه شد.")
            try:
                bot.send_message(target_id,
                    "👮 <b>شما به عنوان ادمین اضافه شدید!</b>\n\n"
                    f"<b>دسترسی‌های شما:</b>\n{perm_text}\n\n"
                    "برای دسترسی به پنل مدیریت از دستور /start استفاده کنید.")
            except Exception:
                pass
        _show_admin_admins_panel(call)
        return

    if data.startswith("adm:usr:"):
        parts     = data.split(":")
        sub       = parts[2]
        target_id = int(parts[3]) if len(parts) > 3 else 0

        if sub == "v":   # view user
            _show_admin_user_detail(call, target_id)
            bot.answer_callback_query(call.id)
            return

        if sub == "sts":  # cycle status: safe → unsafe → restricted → safe
            user = get_user(target_id)
            current = user["status"] if user else "safe"
            if current == "safe":
                new_status = "unsafe"
                label = "ناامن"
            elif current == "unsafe":
                new_status = "restricted"
                label = "محدود"
            else:
                new_status = "safe"
                label = "امن"
            set_user_status(target_id, new_status)
            bot.answer_callback_query(call.id, f"وضعیت کاربر به {label} تغییر کرد.")
            log_admin_action(uid, f"وضعیت کاربر <code>{target_id}</code> به {label} تغییر کرد")
            _show_admin_user_detail(call, target_id)
            return

        if sub == "ag":  # toggle agent
            user     = get_user(target_id)
            new_flag = 0 if user["is_agent"] else 1
            set_user_agent(target_id, new_flag)
            label = "فعال" if new_flag else "غیرفعال"
            bot.answer_callback_query(call.id, f"نمایندگی {label} شد.")
            log_admin_action(uid, f"نمایندگی کاربر <code>{target_id}</code> {label} شد")
            _show_admin_user_detail(call, target_id)
            return

        if sub == "bal":  # balance menu
            user = get_user(target_id)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("➕ افزایش", callback_data=f"adm:usr:bal+:{target_id}"),
                types.InlineKeyboardButton("➖ کاهش",  callback_data=f"adm:usr:bal-:{target_id}"),
            )
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"💰 <b>موجودی کاربر</b>\n\n"
                f"💰 موجودی فعلی: <b>{fmt_price(user['balance'])}</b> تومان",
                kb)
            return

        if sub == "bal+":  # add balance
            state_set(uid, "admin_bal_add", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"💰 مبلغی که می‌خواهید <b>اضافه</b> شود را به تومان وارد کنید:",
                         back_button(f"adm:usr:v:{target_id}"))
            return

        if sub == "bal-":  # reduce balance
            state_set(uid, "admin_bal_sub", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"💰 مبلغی که می‌خواهید <b>کاهش</b> یابد را به تومان وارد کنید:",
                         back_button(f"adm:usr:v:{target_id}"))
            return

        if sub == "cfgs":  # user configs (paginated + search)
            _show_admin_user_configs(call, uid, target_id, page=0)
            return

        if sub == "cfgp":  # config list: paginate
            page = int(parts[4]) if len(parts) > 4 else 0
            _show_admin_user_configs(call, uid, target_id, page=page)
            return

        if sub == "cfgsrch":  # config list: start search
            state_set(uid, "admin_usr_cfg_search", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, "🔍 عبارت جست‌وجو را ارسال کنید:", back_button(f"adm:usr:cfgs:{target_id}"))
            return

        if sub == "cfgclr":  # config list: clear search
            _show_admin_user_configs(call, uid, target_id, page=0, search="")
            return

        if sub == "refs":  # referrals list
            page = int(parts[4]) if len(parts) > 4 else 0
            PER_PAGE = 10
            refs, total = get_referrals_paged(target_id, page=page, per_page=PER_PAGE)
            total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
            page = max(0, min(page, total_pages - 1))
            kb = types.InlineKeyboardMarkup()
            for r in refs:
                name = r["full_name"] or str(r["referee_id"])
                username = f" (@{r['username']})" if r["username"] else ""
                kb.add(types.InlineKeyboardButton(
                    f"👤 {name}{username}",
                    callback_data=f"adm:usr:v:{r['referee_id']}"
                ))
            if total_pages > 1:
                nav_row = []
                if page > 0:
                    nav_row.append(types.InlineKeyboardButton(
                        "◀️ قبلی", callback_data=f"adm:usr:refs:{target_id}:{page - 1}"
                    ))
                nav_row.append(types.InlineKeyboardButton(
                    f"{page + 1}/{total_pages}", callback_data="noop"
                ))
                if page < total_pages - 1:
                    nav_row.append(types.InlineKeyboardButton(
                        "بعدی ▶️", callback_data=f"adm:usr:refs:{target_id}:{page + 1}"
                    ))
                kb.row(*nav_row)
            kb.add(types.InlineKeyboardButton(
                "بازگشت", callback_data=f"adm:usr:v:{target_id}",
                icon_custom_emoji_id="5253997076169115797"
            ))
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"👥 <b>زیرمجموعه‌ها</b>\n\nتعداد کل: <b>{total}</b>", kb)
            return

        if sub == "acfg":  # assign config to user
            _show_admin_assign_config_type(call, target_id)
            bot.answer_callback_query(call.id)
            return

        if sub == "dm":  # send direct message to user
            if not is_admin(uid):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            state_set(uid, "admin_dm_user", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("🔙 لغو", callback_data=f"adm:usr:v:{target_id}"))
            send_or_edit(call,
                f"✉️ <b>پیام خصوصی به کاربر</b>\n\n"
                f"شناسه کاربر: <code>{target_id}</code>\n\n"
                "پیام مورد نظر را ارسال کنید.\n"
                "می‌توانید متن، عکس، ویدیو، فایل یا هر محتوای دیگری بفرستید.",
                kb)
            return

        if sub == "agp":  # agency prices list
            packs = get_packages()
            if not packs:
                bot.answer_callback_query(call.id, "پکیجی موجود نیست.", show_alert=True)
                return
            kb = types.InlineKeyboardMarkup()
            for p in packs:
                ap    = get_agency_price(target_id, p["id"])
                price = fmt_price(ap) if ap is not None else fmt_price(p["price"])
                label = f"{p['name']} | {price} ت"
                kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:usr:agpe:{target_id}:{p['id']}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "🏷 <b>قیمت‌های اختصاصی نمایندگی</b>\n\nبرای ویرایش روی پکیج بزنید:", kb)
            return

    if data.startswith("adm:usr:agpe:"):
        parts      = data.split(":")
        target_id  = int(parts[3])
        package_id = int(parts[4])
        state_set(uid, "admin_set_agency_price", target_user_id=target_id, package_id=package_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, "💰 قیمت اختصاصی (تومان) را وارد کنید.\nبرای بازگشت به قیمت عادی، عدد <b>0</b> بفرستید:",
                     back_button(f"adm:usr:v:{target_id}"))
        return

    # Admin user config detail (with unassign/delete)
    if data.startswith("adm:usrcfg:unassign_sold:"):
        parts     = data.split(":")
        target_id = int(parts[3])
        config_id = int(parts[4])
        with get_conn() as conn:
            conn.execute("DELETE FROM purchases WHERE config_id=? AND user_id=?", (config_id, target_id))
            conn.execute("UPDATE configs SET purchase_id=NULL WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "کانفیگ از کاربر حذف شد (فروخته شده).")
        send_or_edit(call, "✅ کانفیگ از کاربر حذف شد و در وضعیت فروخته شده باقی ماند.", back_button(f"adm:usr:v:{target_id}"))
        return

    if data.startswith("adm:usrcfg:unassign_exp:"):
        parts     = data.split(":")
        target_id = int(parts[3])
        config_id = int(parts[4])
        with get_conn() as conn:
            conn.execute("DELETE FROM purchases WHERE config_id=? AND user_id=?", (config_id, target_id))
            conn.execute("UPDATE configs SET sold_to=NULL, purchase_id=NULL, sold_at=NULL, reserved_payment_id=NULL, is_expired=1 WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "کانفیگ از کاربر حذف شد (منقضی).")
        send_or_edit(call, "✅ کانفیگ از کاربر حذف شد و در وضعیت منقضی قرار گرفت.", back_button(f"adm:usr:v:{target_id}"))
        return

    if data.startswith("adm:usrcfg:unassign:"):

        parts     = data.split(":")
        target_id = int(parts[3])
        config_id = int(parts[4])
        with get_conn() as conn:
            # Reset config to available
            conn.execute("UPDATE configs SET sold_to=NULL, purchase_id=NULL, sold_at=NULL, reserved_payment_id=NULL, is_expired=0 WHERE id=?", (config_id,))
            # Delete the purchase record
            conn.execute("DELETE FROM purchases WHERE config_id=? AND user_id=?", (config_id, target_id))
        bot.answer_callback_query(call.id, "کانفیگ از کاربر حذف شد.")
        send_or_edit(call, "✅ کانفیگ از کاربر حذف و به مانده‌ها برگشت.", back_button(f"adm:usr:v:{target_id}"))
        return

    if data.startswith("adm:usrcfg:"):
        parts     = data.split(":")
        target_id = int(parts[2])
        config_id = int(parts[3])
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM configs WHERE id=?", (config_id,)).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "یافت نشد.", show_alert=True)
            return
        text = (
            f"🔮 نام سرویس: <b>{esc(urllib.parse.unquote(row['service_name'] or ''))}</b>\n\n"
            f"💝 Config:\n<code>{esc(row['config_text'])}</code>\n\n"
            f"🔋 Volume web: {esc(row['inquiry_link'] or '-')}\n"
            f"🗓 ثبت: {esc(row['created_at'])}\n"
            f"🗓 فروش: {esc(row['sold_at'] or '-')}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 حذف از کاربر (برگشت به مانده‌ها)", callback_data=f"adm:usrcfg:unassign:{target_id}:{config_id}"))
        kb.add(types.InlineKeyboardButton("🔄 حذف از کاربر (برگشت به فروخته شده‌ها)", callback_data=f"adm:usrcfg:unassign_sold:{target_id}:{config_id}"))
        kb.add(types.InlineKeyboardButton("🔄 حذف از کاربر (برگشت به منقضی‌ها)", callback_data=f"adm:usrcfg:unassign_exp:{target_id}:{config_id}"))
        if not row["is_expired"]:
            kb.add(types.InlineKeyboardButton("🔴 منقضی کردن", callback_data=f"adm:stk:exp:{config_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:usr:cfgs:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:usrpcfg:"):  # panel config detail for user (admin view)
        parts     = data.split(":")
        target_id = int(parts[2])
        pc_id     = int(parts[3])
        from ..admin.renderers import _show_panel_config_detail
        _show_panel_config_detail(call, pc_id, back_data=f"adm:usr:cfgs:{target_id}")
        bot.answer_callback_query(call.id)
        return

    if data.startswith("adm:acfg:t:"):  # assign config: type selected
        parts     = data.split(":")
        target_id = int(parts[3])
        type_id   = int(parts[4])
        packs     = get_packages(type_id=type_id)
        kb        = types.InlineKeyboardMarkup()
        for p in packs:
            avail = len(get_available_configs_for_package(p["id"]))
            if avail > 0:
                kb.add(types.InlineKeyboardButton(
                    f"{p['name']} | موجود: {avail}",
                    callback_data=f"adm:acfg:p:{target_id}:{p['id']}"
                ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📦 پکیج مورد نظر را انتخاب کنید:", kb)
        return

    if data.startswith("adm:acfg:p:"):  # assign config: package selected
        parts      = data.split(":")
        target_id  = int(parts[3])
        package_id = int(parts[4])
        cfgs       = get_available_configs_for_package(package_id)
        kb         = types.InlineKeyboardMarkup()
        for c in cfgs[:50]:
            svc = urllib.parse.unquote(c["service_name"] or "")
            kb.add(types.InlineKeyboardButton(svc,
                                              callback_data=f"adm:acfg:do:{target_id}:{c['id']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔧 کانفیگ مورد نظر را انتخاب کنید:", kb)
        return

    if data.startswith("adm:acfg:do:"):  # do assign config
        parts      = data.split(":")
        target_id  = int(parts[3])
        config_id  = int(parts[4])
        with get_conn() as conn:
            cfg_row = conn.execute("SELECT * FROM configs WHERE id=?", (config_id,)).fetchone()
        if not cfg_row:
            bot.answer_callback_query(call.id, "کانفیگ یافت نشد.", show_alert=True)
            return
        purchase_id = assign_config_to_user(config_id, target_id, cfg_row["package_id"], 0, "admin_gift", is_test=0)
        bot.answer_callback_query(call.id, "کانفیگ منتقل شد!")
        send_or_edit(call, "✅ کانفیگ با موفقیت به کاربر اختصاص یافت.", back_button("admin:users"))
        try:
            deliver_purchase_message(target_id, purchase_id)
        except Exception:
            pass
        return

    # ── Admin: Agents management ──────────────────────────────────────────────
    if data == "admin:agents":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        agents    = get_agencies()
        req_flag  = setting_get("agency_request_enabled", "1")
        req_icon  = "🟢" if req_flag == "1" else "🔴"
        req_label = "روشن" if req_flag == "1" else "خاموش"
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} درخواست نمایندگی — {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("➕ اضافه کردن نماینده", callback_data="adm:agt:add"))
        # Inline list: each agent on one row with remove button
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"🤝 {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "🗑 حذف",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"🤝 <b>مدیریت نمایندگان</b>\n\n"
            f"👥 تعداد نمایندگان فعلی: <b>{len(agents)}</b>\n"
            f"📨 وضعیت درخواست: <b>{req_label}</b>",
            kb)
        return

    if data == "adm:agt:add":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_agent_add_search")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔍 <b>جستجوی کاربر برای افزودن به نمایندگی</b>\n\n"
            "آیدی عددی یا یوزرنیم کاربر را ارسال کنید:",
            back_button("admin:agents"))
        return

    if data.startswith("adm:agt:u:"):
        target_uid = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _show_admin_user_detail(call, target_uid)
        return

    if data.startswith("adm:agt:rm:"):
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        target_uid = int(data.split(":")[3])
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_agent=0 WHERE user_id=?", (target_uid,))
        bot.answer_callback_query(call.id, "✅ کاربر از نمایندگی حذف شد.")
        # re-render agents menu
        agents    = get_agencies()
        req_flag  = setting_get("agency_request_enabled", "1")
        req_icon  = "🟢" if req_flag == "1" else "🔴"
        req_label = "روشن" if req_flag == "1" else "خاموش"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} درخواست نمایندگی — {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("➕ اضافه کردن نماینده", callback_data="adm:agt:add"))
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"🤝 {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "🗑 حذف",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"🤝 <b>مدیریت نمایندگان</b>\n\n"
            f"👥 تعداد نمایندگان فعلی: <b>{len(agents)}</b>\n"
            f"📨 وضعیت درخواست: <b>{req_label}</b>",
            kb)
        return

    if data == "adm:agt:toggle":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur      = setting_get("agency_request_enabled", "1")
        new      = "0" if cur == "1" else "1"
        setting_set("agency_request_enabled", new)
        log_admin_action(uid, f"درخواست نمایندگی {'فعال' if new == '1' else 'غیرفعال'} شد")
        req_icon  = "🟢" if new == "1" else "🔴"
        req_label = "روشن" if new == "1" else "خاموش"
        bot.answer_callback_query(call.id, f"درخواست نمایندگی: {req_label}")
        agents = get_agencies()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} درخواست نمایندگی — {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("➕ اضافه کردن نماینده", callback_data="adm:agt:add"))
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"🤝 {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "🗑 حذف",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"🤝 <b>مدیریت نمایندگان</b>\n\n"
            f"👥 تعداد نمایندگان فعلی: <b>{len(agents)}</b>\n"
            f"📨 وضعیت درخواست: <b>{req_label}</b>",
            kb)
        return

    # ── Agency price config (3-mode) ──────────────────────────────────────────
    if data.startswith("adm:agcfg:") and data.count(":") == 2:
        # adm:agcfg:{target_id}  — show mode selector
        parts     = data.split(":")
        target_id = int(parts[2])
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cfg  = get_agency_price_config(target_id)
        mode = cfg["price_mode"]
        tick = {m: "✅ " for m in ["global", "type", "package"]}
        for k in tick:
            tick[k] = "✅ " if mode == k else ""
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{tick['global']}🌍 تخفیف روی کل محصولات",
            callback_data=f"adm:agcfg:global:{target_id}"))
        kb.add(types.InlineKeyboardButton(
            f"{tick['type']}🧩 تخفیف روی هر دسته",
            callback_data=f"adm:agcfg:type:{target_id}"))
        kb.add(types.InlineKeyboardButton(
            f"{tick['package']}📦 قیمت جداگانه هر پکیج",
            callback_data=f"adm:agcfg:pkg:{target_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        target_user = get_user(target_id)
        uname = esc(target_user["full_name"]) if target_user else str(target_id)
        mode_labels = {"global": "🌍 تخفیف کل محصولات", "type": "🧩 تخفیف هر دسته", "package": "📦 قیمت هر پکیج"}
        send_or_edit(call,
            f"💰 <b>قیمت نمایندگی کاربر</b>\n"
            f"👤 {uname}\n\n"
            f"حالت فعلی: <b>{mode_labels.get(mode, mode)}</b>\n\n"
            "حالت مورد نظر را انتخاب کنید:", kb)
        return

    if data.startswith("adm:agcfg:global:") and data.count(":") == 3:
        # adm:agcfg:global:{target_id}  — choose pct or toman
        target_id = int(data.split(":")[3])
        cfg = get_agency_price_config(target_id)
        g_type = cfg["global_type"]
        g_val  = cfg["global_val"]
        cur_label = f"{'درصد' if g_type == 'pct' else 'تومان'} — مقدار فعلی: {g_val}"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("📊 درصد", callback_data=f"adm:agcfg:glb:pct:{target_id}"),
            types.InlineKeyboardButton("💵 تومان", callback_data=f"adm:agcfg:glb:tmn:{target_id}"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:agcfg:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"🌍 <b>تخفیف کل محصولات</b>\n\n"
            f"تنظیم فعلی: <b>{cur_label}</b>\n\n"
            "می‌خواهی درصد کم بشه یا مبلغ ثابت (تومان)؟", kb)
        return

    if data.startswith("adm:agcfg:glb:"):
        # adm:agcfg:glb:pct:{target_id}  or  adm:agcfg:glb:tmn:{target_id}
        parts     = data.split(":")
        dtype     = parts[3]   # pct or tmn
        target_id = int(parts[4])
        set_agency_price_config(target_id, "global", "pct" if dtype == "pct" else "toman", 0)
        state_set(uid, "admin_agcfg_global_val", target_user_id=target_id, dtype=dtype)
        bot.answer_callback_query(call.id)
        label = "درصد تخفیف (مثال: 20)" if dtype == "pct" else "مبلغ تخفیف به تومان (مثال: 50000)"
        send_or_edit(call,
            f"🌍 <b>تخفیف کل محصولات</b>\n\n"
            f"{'📊' if dtype == 'pct' else '💵'} {label} را وارد کنید:",
            back_button(f"adm:agcfg:global:{target_id}"))
        return

    if data.startswith("adm:agcfg:type:") and data.count(":") == 3:
        # adm:agcfg:type:{target_id}  — show types list
        target_id = int(data.split(":")[3])
        types_list = get_all_types()
        if not types_list:
            bot.answer_callback_query(call.id, "هیچ نوعی تعریف نشده.", show_alert=True)
            return
        set_agency_price_config(target_id, "type",
            get_agency_price_config(target_id)["global_type"],
            get_agency_price_config(target_id)["global_val"])
        kb = types.InlineKeyboardMarkup()
        for t in types_list:
            td = get_agency_type_discount(target_id, t["id"])
            if td:
                dot = "✅"
                val_lbl = f"{td['discount_value']}{'%' if td['discount_type']=='pct' else 'ت'}"
            else:
                dot = "⬜️"
                val_lbl = "تنظیم نشده"
            kb.add(types.InlineKeyboardButton(
                f"{dot} {t['name']} | {val_lbl}",
                callback_data=f"adm:agcfg:td:{target_id}:{t['id']}"
            ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:agcfg:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🧩 <b>تخفیف هر دسته</b>\n\nدسته مورد نظر را انتخاب کنید:", kb)
        return

    if data.startswith("adm:agcfg:td:") and data.count(":") == 4:
        # adm:agcfg:td:{target_id}:{type_id}  — choose pct or toman for this type
        parts     = data.split(":")
        target_id = int(parts[3])
        type_id   = int(parts[4])
        type_row  = get_type(type_id) if hasattr(__import__('bot.db', fromlist=['get_type']), 'get_type') else None
        td = get_agency_type_discount(target_id, type_id)
        cur_label = f"{'درصد' if td['discount_type']=='pct' else 'تومان'} — {td['discount_value']}" if td else "تنظیم نشده"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("📊 درصد", callback_data=f"adm:agcfg:tdt:{target_id}:{type_id}:pct"),
            types.InlineKeyboardButton("💵 تومان", callback_data=f"adm:agcfg:tdt:{target_id}:{type_id}:tmn"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:agcfg:type:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"🧩 <b>دسته #{type_id}</b>\n\n"
            f"تنظیم فعلی: <b>{cur_label}</b>\n\n"
            "می‌خواهی درصد کم بشه یا مبلغ ثابت؟", kb)
        return

    if data.startswith("adm:agcfg:tdt:"):
        # adm:agcfg:tdt:{target_id}:{type_id}:pct  or  :tmn
        parts     = data.split(":")
        target_id = int(parts[3])
        type_id   = int(parts[4])
        dtype     = parts[5]
        state_set(uid, "admin_agcfg_type_val",
                  target_user_id=target_id, type_id=type_id, dtype=dtype)
        bot.answer_callback_query(call.id)
        label = "درصد (مثال: 15)" if dtype == "pct" else "مبلغ تومان (مثال: 30000)"
        send_or_edit(call,
            f"🧩 دسته #{type_id}\n\n"
            f"{'📊' if dtype == 'pct' else '💵'} {label} را وارد کنید:",
            back_button(f"adm:agcfg:td:{target_id}:{type_id}"))
        return

    if data.startswith("adm:agcfg:pkg:"):
        # adm:agcfg:pkg:{target_id}  — show packages (existing flow)
        target_id = int(data.split(":")[3])
        set_agency_price_config(target_id, "package",
            get_agency_price_config(target_id)["global_type"],
            get_agency_price_config(target_id)["global_val"])
        packs = get_packages()
        if not packs:
            bot.answer_callback_query(call.id, "پکیجی موجود نیست.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        for p in packs:
            ap    = get_agency_price(target_id, p["id"])
            price = fmt_price(ap) if ap is not None else fmt_price(p["price"])
            label = f"{p['name']} | {price} ت"
            kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:usr:agpe:{target_id}:{p['id']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:agcfg:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📦 <b>قیمت هر پکیج</b>\n\nبرای ویرایش روی پکیج بزنید:", kb)
        return

    # ── Admin: Broadcast ──────────────────────────────────────────────────────
    if data == "admin:broadcast":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📣 همه کاربران",             callback_data="adm:bc:all"))
        kb.add(types.InlineKeyboardButton("🛍 فقط مشتریان (همه)",       callback_data="adm:bc:cust"))
        kb.add(types.InlineKeyboardButton("👤 فقط مشتریان عادی",        callback_data="adm:bc:normal"))
        kb.add(types.InlineKeyboardButton("🤝 فقط نمایندگان",           callback_data="adm:bc:agents"))
        kb.add(types.InlineKeyboardButton("👑 فقط ادمین‌ها",            callback_data="adm:bc:admins"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📣 <b>فوروارد همگانی</b>\n\nگیرنده‌ها را انتخاب کنید:", kb)
        return

    if data == "adm:bc:all":
        state_set(uid, "admin_broadcast_all")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📣 پیام خود را فوروارد یا ارسال کنید.\nبرای <b>همه کاربران</b> ارسال می‌شود.",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:cust":
        state_set(uid, "admin_broadcast_customers")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🛍 پیام خود را فوروارد یا ارسال کنید.\nفقط برای <b>مشتریان</b> ارسال می‌شود.",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:normal":
        state_set(uid, "admin_broadcast_normal")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "👤 پیام خود را فوروارد یا ارسال کنید.\nفقط برای <b>مشتریان عادی</b> (بدون نمایندگان و ادمین‌ها) ارسال می‌شود.",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:agents":
        state_set(uid, "admin_broadcast_agents")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🤝 پیام خود را فوروارد یا ارسال کنید.\nفقط برای <b>نمایندگان</b> ارسال می‌شود.",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:admins":
        state_set(uid, "admin_broadcast_admins")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "👑 پیام خود را فوروارد یا ارسال کنید.\nفقط برای <b>ادمین‌ها</b> ارسال می‌شود.",
                     back_button("admin:broadcast"))
        return

    # ── Admin: Group management ───────────────────────────────────────────────
    if data == "admin:group":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        gid      = get_group_id()
        active_c = _count_active_topics()
        total_c  = len(TOPICS)
        gid_text = f"<code>{gid}</code>" if gid else "تنظیم نشده"
        text = (
            "🏢 <b>مدیریت گروه ادمین</b>\n\n"
            "📌 <b>راهنما:</b>\n"
            "۱. یک سوپرگروه تلگرام بسازید و Topics را فعال کنید.\n"
            "۲. ربات را به گروه اضافه و ادمین کنید.\n"
            "۳. آیدی عددی گروه را با @getidsbot دریافت کنید.\n"
            "۴. دکمه «ثبت آیدی گروه» را بزنید و آیدی را ارسال کنید.\n\n"
            "ℹ️ آیدی گروه با <code>-100</code> شروع می‌شود. مثال: <code>-1001234567890</code>\n\n"
            f"📊 <b>وضعیت:</b> گروه {gid_text} | تاپیک‌ها: {active_c}/{total_c}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔢 ثبت آیدی گروه",      callback_data="adm:grp:setid"))
        kb.add(types.InlineKeyboardButton("🛠 ساخت تاپیک‌های جدید",  callback_data="adm:grp:create"))
        kb.add(types.InlineKeyboardButton("♻️ بازسازی همه تاپیک‌ها", callback_data="adm:grp:reset"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:grp:setid":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_set_group_id")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔢 <b>آیدی عددی گروه</b> را ارسال کنید:\n\n"
            "مثال: <code>-1001234567890</code>\n\n"
            "برای دریافت آیدی گروه، ربات <b>@getidsbot</b> را به گروه اضافه کنید و <code>/id</code> بفرستید.",
            back_button("admin:group"))
        return

    if data == "adm:grp:create":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "در حال ساخت تاپیک‌ها...", show_alert=False)
        result = ensure_group_topics()
        log_admin_action(uid, "ساخت تاپیک‌های گروه")
        send_or_edit(call, f"🛠 <b>ساخت تاپیک</b>\n\n{result}", back_button("admin:group"))
        return

    if data == "adm:grp:reset":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "در حال بازسازی...", show_alert=False)
        result = reset_and_recreate_topics()
        log_admin_action(uid, "بازسازی تاپیک‌های گروه")
        send_or_edit(call, f"♻️ <b>بازسازی تاپیک‌ها</b>\n\n{result}", back_button("admin:group"))
        return

    # ── Admin: Settings ───────────────────────────────────────────────────────
    if data == "admin:settings":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("🎧 پشتیبانی",           callback_data="adm:set:support"),
            types.InlineKeyboardButton("💳 درگاه‌های پرداخت",   callback_data="adm:set:gateways"),
        )
        kb.add(types.InlineKeyboardButton("📢 کانال قفل",           callback_data="adm:locked_channels"))
        kb.add(types.InlineKeyboardButton("🎁 تست رایگان",      callback_data="adm:set:freetest"))
        kb.add(types.InlineKeyboardButton("� متن‌های ربات",    callback_data="adm:bot_texts"))
        kb.add(types.InlineKeyboardButton("🏪 مدیریت فروش",    callback_data="adm:set:shop"))
        kb.add(types.InlineKeyboardButton("📱 جمع‌آوری شماره تلفن", callback_data="adm:set:phone"))
        kb.add(types.InlineKeyboardButton("🤖 مدیریت عملیات ربات", callback_data="adm:ops"))
        kb.add(types.InlineKeyboardButton("🏢 مدیریت گروه",    callback_data="admin:group"))
        kb.add(types.InlineKeyboardButton("📌 پیام‌های پین شده", callback_data="adm:pin"))
        kb.add(types.InlineKeyboardButton("⭐ آیدی ایموجی پرمیوم", callback_data="adm:emoji:menu"))
        kb.add(types.InlineKeyboardButton("� مدیریت اعلان‌ها",  callback_data="adm:notif"))
        kb.add(types.InlineKeyboardButton("�💾 بکاپ",            callback_data="admin:backup"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "⚙️ <b>تنظیمات</b>", kb)
        return

    # ── Admin: Premium Emoji Tools ────────────────────────────────────────────
    if data == "adm:emoji:menu":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔍 تبدیل پیام به آیدی ایموجی", callback_data="adm:emoji:extract"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            "⭐ <b>آیدی ایموجی پرمیوم</b>\n\n"
            "ابزارهای مدیریت ایموجی‌های سفارشی تلگرام پرمیوم:",
            kb,
        )
        return

    if data == "adm:emoji:extract":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_emoji_extract")
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            "🔍 <b>تبدیل پیام به آیدی ایموجی</b>\n\n"
            "یک پیام حاوی ایموجی پرمیوم (سفارشی) ارسال کنید.\n"
            "می‌توانید چند ایموجی در یک پیام بفرستید.\n\n"
            "<i>متن همراه ایموجی نیز شناسایی می‌شود.</i>",
            back_button("adm:emoji:menu"),
        )
        return

    if data == "adm:set:agency_toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("agency_request_enabled", "1")
        new = "0" if cur == "1" else "1"
        setting_set("agency_request_enabled", new)
        log_admin_action(uid, f"درخواست نمایندگی از تنظیمات {'فعال' if new == '1' else 'غیرفعال'} شد")
        label = "فعال" if new == "1" else "غیرفعال"
        bot.answer_callback_query(call.id, f"درخواست نمایندگی: {label}")
        # re-render settings
        _fake_call_data = type('obj', (object,), {
            'id': call.id, 'message': call.message,
            'data': 'admin:settings', 'from_user': call.from_user
        })()
        _fake_call_data.id = call.id
        try:
            agency_flag  = new
            agency_icon  = "✅" if agency_flag == "1" else "❌"
            pct          = setting_get("agency_default_discount_pct", "20")
            kb           = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("🎧 پشتیبانی",           callback_data="adm:set:support"),
                types.InlineKeyboardButton("💳 درگاه‌های پرداخت",   callback_data="adm:set:gateways"),
            )
            kb.add(types.InlineKeyboardButton("📢 کانال قفل",           callback_data="adm:locked_channels"))
            kb.add(types.InlineKeyboardButton("✏️ ویرایش متن استارت", callback_data="adm:set:start_text"))
            kb.add(types.InlineKeyboardButton("📜 قوانین خرید",     callback_data="adm:set:rules"))
            kb.add(types.InlineKeyboardButton("🏷 تنظیمات فروش",    callback_data="adm:set:shop"))
            kb.add(types.InlineKeyboardButton("🏢 مدیریت گروه",    callback_data="admin:group"))
            kb.add(types.InlineKeyboardButton("📌 پیام‌های پین شده", callback_data="adm:pin"))
            kb.add(types.InlineKeyboardButton(f"{agency_icon} درخواست نمایندگی", callback_data="adm:set:agency_toggle"))
            kb.add(types.InlineKeyboardButton("📊 تخفیف پیش‌فرض نمایندگی", callback_data="adm:set:agency_defpct"))
            kb.add(types.InlineKeyboardButton("� مدیریت اعلان‌ها",  callback_data="adm:notif"))
            kb.add(types.InlineKeyboardButton("�💾 بکاپ",            callback_data="admin:backup"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call, "⚙️ <b>تنظیمات</b>", kb)
        except Exception:
            pass
        return

    if data == "adm:set:agency_defpct":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur_pct = setting_get("agency_default_discount_pct", "20")
        state_set(uid, "admin_set_default_discount_pct")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📊 <b>تخفیف پیش‌فرض نمایندگی</b>\n\n"
            f"تنظیم فعلی: <b>{cur_pct}%</b>\n\n"
            "درصد جدید را وارد کنید (عدد بین 0 تا 100):",
            back_button("admin:settings"))
        return

    # ── Notification Management ───────────────────────────────────────────────
    # Notification types: (key, label)
    _NOTIF_TYPES = [
        ("new_users",        "👋 کاربر جدید"),
        ("payment_approval", "💳 تأیید پرداخت"),
        ("renewal_request",  "♻️ درخواست تمدید"),
        ("purchase_log",     "📦 لاگ خرید"),
        ("renewal_log",      "🔄 لاگ تمدید"),
        ("wallet_log",       "💰 لاگ کیف‌پول"),
        ("test_report",      "🧪 گزارش تست"),
        ("broadcast_report", "📢 اطلاع‌رسانی و پین"),
        ("referral_log",     "🔗 زیرمجموعه‌گیری"),
        ("agency_request",   "🤝 درخواست نمایندگی"),
        ("agency_log",       "🏢 لاگ نمایندگان"),
        ("admin_ops_log",    "📝 لاگ عملیاتی"),
        ("error_log",        "❌ گزارش خطا"),
        ("backup",           "💾 بکاپ"),
    ]

    if data == "adm:notif":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("👑 اعلان های ربات اونر",   callback_data="adm:notif:own"))
        kb.add(types.InlineKeyboardButton("🤖 اعلان های ربات ادمین",   callback_data="adm:notif:bot"))
        kb.add(types.InlineKeyboardButton("📢 گروه",  callback_data="adm:notif:grp"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "🔔 <b>مدیریت اعلان‌ها</b>\n\n"
            "👑 <b>اعلان های ربات اونر</b>: اعلان برای اونر در ربات\n"
            "🤖 <b>اعلان های ربات ادمین</b>: اعلان برای ادمین‌های فرعی (بر اساس دسترسی)\n"
            "📢 <b>گروه</b>: اعلان در تاپیک‌های گروه",
            kb)
        return

    if data == "adm:notif:own":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_own_{key}", "1") == "1"
            icon = "✅" if on else "❌"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:otg:{key}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "👑 <b>اعلان های ربات اونر</b>\n\n"
            "اعلان‌هایی که مستقیماً برای <b>ADMIN_IDS</b> (اید ثابت تو config.py) ارسال می‌شن:"
            "\n✅ = فعال  |  ❌ = غیرفعال",
            kb)
        return

    if data.startswith("adm:notif:otg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        key = data[len("adm:notif:otg:"):]
        cur = setting_get(f"notif_own_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_own_{key}", new)
        log_admin_action(uid, f"اعلان شخصی {key} {'فعال' if new == '1' else 'غیرفعال'} شد")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "فعال" if new == "1" else "غیرفعال"
        bot.answer_callback_query(call.id, f"{status_lbl} شد: {lbl}")
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_own_{k}", "1") == "1"
            icon = "✅" if on else "❌"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:otg:{k}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "👑 <b>اعلان های ربات اونر</b>\n\n"
            "اعلان‌هایی که مستقیماً برای <b>ADMIN_IDS</b> ارسال می‌شن:"
            "\n✅ = فعال  |  ❌ = غیرفعال",
            kb)
        return

    if data == "adm:notif:grp":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_grp_{key}", "1") == "1"
            icon = "✅" if on else "❌"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:gtg:{key}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📢 <b>گروه</b>\n\n"
            "انتخاب کنید کدام اعلان‌ها در تاپیک‌های گروه ارسال شوند:\n"
            "✅ = فعال  |  ❌ = غیرفعال",
            kb)
        return

    if data == "adm:notif:bot":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_bot_{key}", "1") == "1"
            icon = "✅" if on else "❌"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:btg:{key}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "🤖 <b>اعلان های ربات ادمین</b>\n\n"
            "انتخاب کنید کدام اعلان‌ها به صورت مستقیم برای ادمین‌ها ارسال شوند:\n"
            "✅ = فعال  |  ❌ = غیرفعال",
            kb)
        return

    if data.startswith("adm:notif:gtg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        key = data[len("adm:notif:gtg:"):]
        cur = setting_get(f"notif_grp_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_grp_{key}", new)
        log_admin_action(uid, f"اعلان گروه {key} {'فعال' if new == '1' else 'غیرفعال'} شد")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "فعال" if new == "1" else "غیرفعال"
        bot.answer_callback_query(call.id, f"{status_lbl} شد: {lbl}")
        # re-render group list
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_grp_{k}", "1") == "1"
            icon = "✅" if on else "❌"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:gtg:{k}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📢 <b>گروه</b>\n\n"
            "انتخاب کنید کدام اعلان‌ها در تاپیک‌های گروه ارسال شوند:\n"
            "✅ = فعال  |  ❌ = غیرفعال",
            kb)
        return

    if data.startswith("adm:notif:btg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        key = data[len("adm:notif:btg:"):]
        cur = setting_get(f"notif_bot_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_bot_{key}", new)
        log_admin_action(uid, f"اعلان ربات {key} {'فعال' if new == '1' else 'غیرفعال'} شد")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "فعال" if new == "1" else "غیرفعال"
        bot.answer_callback_query(call.id, f"{status_lbl} شد: {lbl}")
        # re-render bot list
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_bot_{k}", "1") == "1"
            icon = "✅" if on else "❌"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:btg:{k}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "🤖 <b>اعلان های ربات ادمین</b>\n\n"
            "انتخاب کنید کدام اعلان‌ها به صورت مستقیم برای ادمین‌ها ارسال شوند:\n"
            "✅ = فعال  |  ❌ = غیرفعال",
            kb)
        return
    # ── End Notification Management ───────────────────────────────────────────

    if data == "adm:set:support":
        support_raw = setting_get("support_username", "")
        support_link = setting_get("support_link", "")
        support_link_desc = setting_get("support_link_desc", "")
        kb = types.InlineKeyboardMarkup()
        tg_status = "✅" if support_raw else "❌"
        link_status = "✅" if support_link else "❌"
        kb.add(types.InlineKeyboardButton(f"{tg_status} پشتیبانی تلگرام", callback_data="adm:set:support_tg"))
        kb.add(types.InlineKeyboardButton(f"{link_status} پشتیبانی آنلاین (لینک)", callback_data="adm:set:support_link"))
        kb.add(types.InlineKeyboardButton("✏️ توضیحات پشتیبانی", callback_data="adm:set:support_desc"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        text = (
            "🎧 <b>تنظیمات پشتیبانی</b>\n\n"
            f"📱 تلگرام: <code>{esc(support_raw or 'ثبت نشده')}</code>\n"
            f"🌐 لینک: <code>{esc(support_link or 'ثبت نشده')}</code>\n"
            f"📝 توضیحات: {esc(support_link_desc or 'پیش‌فرض')}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:set:support_tg":
        state_set(uid, "admin_set_support")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🎧 آیدی یا لینک پشتیبانی تلگرام را ارسال کنید.\nمثال: <code>@username</code>",
                     back_button("adm:set:support"))
        return

    if data == "adm:set:support_link":
        state_set(uid, "admin_set_support_link")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🌐 لینک پشتیبانی آنلاین را ارسال کنید.\nمثال: <code>https://example.com/chat</code>\n\nبرای حذف، <code>-</code> بفرستید.",
                     back_button("adm:set:support"))
        return

    if data == "adm:set:support_desc":
        state_set(uid, "admin_set_support_desc")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📝 توضیحات نمایشی بالای دکمه‌های پشتیبانی را بنویسید.\n\nبرای بازگشت به پیش‌فرض، <code>-</code> بفرستید.",
                     back_button("adm:set:support"))
        return

    # ── Shop management settings ─────────────────────────────────────────────
    if data == "adm:set:shop":
        shop_open     = setting_get("shop_open", "1")
        preorder_mode = setting_get("preorder_mode", "0")
        open_icon  = "🟢" if shop_open     == "1" else "🔴"
        stock_icon = "🟢" if preorder_mode == "1" else "🔴"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{open_icon} وضعیت فروش: {'باز' if shop_open == '1' else 'بسته'}",
            callback_data="adm:shop:toggle_open"))
        kb.add(types.InlineKeyboardButton(
            f"{stock_icon} فروش بر اساس موجودی: {'فعال' if preorder_mode == '1' else 'غیرفعال'}",
            callback_data="adm:shop:toggle_stock"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        text = (
            "🏪 <b>مدیریت فروش</b>\n\n"
            f"🔹 <b>وضعیت فروش:</b> {'🟢 باز' if shop_open == '1' else '🔴 بسته'}\n"
            f"🔹 <b>فروش بر اساس موجودی:</b> {'🟢 فعال – فقط پکیج‌های دارای موجودی نمایش داده می‌شوند.' if preorder_mode == '1' else '🔴 غیرفعال – همه پکیج‌ها نمایش داده می‌شوند. در صورت نبود موجودی، سفارش به پشتیبانی ارسال می‌شود.'}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:shop:toggle_open":
        current = setting_get("shop_open", "1")
        setting_set("shop_open", "0" if current == "1" else "1")
        log_admin_action(uid, f"فروشگاه {'بسته' if current == '1' else 'باز'} شد")
        bot.answer_callback_query(call.id, "وضعیت فروش تغییر کرد.")
        # Re-show shop settings
        data = "adm:set:shop"
        # fall through by calling the handler again via fake callback
        from types import SimpleNamespace as _SN
        fake = _SN(id=call.id, from_user=call.from_user, message=call.message, data=data)
        _dispatch_callback(fake, uid, data)
        return

    if data == "adm:shop:toggle_stock":
        current = setting_get("preorder_mode", "0")
        setting_set("preorder_mode", "0" if current == "1" else "1")
        log_admin_action(uid, f"حالت پیش‌فروش {'غیرفعال' if current == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تنظیم فروش بر اساس موجودی تغییر کرد.")
        from types import SimpleNamespace as _SN
        fake = _SN(id=call.id, from_user=call.from_user, message=call.message, data="adm:set:shop")
        _dispatch_callback(fake, uid, "adm:set:shop")
        return

    # ── Bot Operations Management ─────────────────────────────────────────────
    def _build_ops_kb():
        bot_status      = setting_get("bot_status", "on")
        renewal_enabled = setting_get("manual_renewal_enabled", "1")
        referral_enabled = setting_get("referral_enabled", "1")
        bulk_mode       = setting_get("bulk_sale_mode", "everyone")
        status_map = {"on": "🟢 روشن", "off": "🔴 خاموش", "update": "🔄 بروزرسانی"}
        renewal_map = {"1": "✅ فعال", "0": "❌ غیرفعال"}
        referral_map = {"1": "✅ فعال", "0": "❌ غیرفعال"}
        bulk_map = {"everyone": "✅ همه کاربران", "agents_only": "🤝 فقط نمایندگان", "disabled": "❌ غیرفعال"}
        status_label  = status_map.get(bot_status, "🟢 روشن")
        renewal_label = renewal_map.get(renewal_enabled, "✅ فعال")
        referral_label = referral_map.get(referral_enabled, "✅ فعال")
        bulk_label    = bulk_map.get(bulk_mode, "✅ همه کاربران")
        ops_kb = types.InlineKeyboardMarkup(row_width=2)
        ops_kb.row(
            types.InlineKeyboardButton(status_label,  callback_data="adm:ops:status"),
            types.InlineKeyboardButton("🤖 وضعیت ربات", callback_data="adm:ops:noop"),
        )
        ops_kb.row(
            types.InlineKeyboardButton(renewal_label, callback_data="adm:ops:renewal"),
            types.InlineKeyboardButton("♻️ تمدید کانفیگ‌های ثبت دستی", callback_data="adm:ops:noop"),
        )
        ops_kb.row(
            types.InlineKeyboardButton(referral_label, callback_data="adm:ops:referral_toggle"),
            types.InlineKeyboardButton("🎁 زیرمجموعه‌گیری  ⚙️ تنظیمات", callback_data="adm:ref:settings"),
        )
        ops_kb.row(
            types.InlineKeyboardButton(bulk_label, callback_data="adm:ops:bulk_menu"),
            types.InlineKeyboardButton("📦 فروش عمده", callback_data="adm:ops:noop"),
        )
        _inv_enabled = setting_get("invoice_expiry_enabled", "1")
        _inv_mins    = setting_get("invoice_expiry_minutes", "30")
        _inv_label   = (
            f"✅ فعال — {_inv_mins} دقیقه"
            if _inv_enabled == "1" else "❌ غیرفعال"
        )
        ops_kb.row(
            types.InlineKeyboardButton(_inv_label, callback_data="adm:ops:invoice_expiry"),
            types.InlineKeyboardButton("📄 اعتبار فاکتور پرداخت", callback_data="adm:ops:noop"),
        )
        _wp_enabled = setting_get("wallet_pay_enabled", "1")
        _wp_label   = "✅ فعال" if _wp_enabled == "1" else "❌ غیرفعال"
        ops_kb.row(
            types.InlineKeyboardButton(_wp_label, callback_data="adm:ops:wallet_pay_toggle"),
            types.InlineKeyboardButton("💰 پرداخت با موجودی  ⚙️ استثناها", callback_data="adm:ops:wallet_pay_exc"),
        )
        ops_kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        return ops_kb

    def _ops_menu_text():
        bot_status      = setting_get("bot_status", "on")
        renewal_enabled = setting_get("manual_renewal_enabled", "1")
        referral_enabled = setting_get("referral_enabled", "1")
        bulk_mode       = setting_get("bulk_sale_mode", "everyone")
        min_qty, max_qty = get_bulk_qty_limits()
        max_label = "بدون محدودیت" if max_qty == 0 else str(max_qty)
        status_fa  = {"on": "🟢 روشن", "off": "🔴 خاموش", "update": "🔄 بروزرسانی"}.get(bot_status, "🟢 روشن")
        renewal_fa = "✅ فعال" if renewal_enabled == "1" else "❌ غیرفعال"
        referral_fa = "✅ فعال" if referral_enabled == "1" else "❌ غیرفعال"
        bulk_fa = {"everyone": "✅ همه کاربران", "agents_only": "🤝 فقط نمایندگان", "disabled": "❌ غیرفعال"}.get(bulk_mode, "✅ همه کاربران")
        _inv_exp_enabled = setting_get("invoice_expiry_enabled", "1")
        _inv_exp_mins    = setting_get("invoice_expiry_minutes", "30")
        _inv_fa = (
            f"✅ فعال — هر فاکتور تا <b>{_inv_exp_mins} دقیقه</b> معتبر است."
            if _inv_exp_enabled == "1"
            else "❌ غیرفعال — فاکتورها محدودیت زمانی ندارند."
        )
        _wp_enabled = setting_get("wallet_pay_enabled", "1")
        _wp_fa = "✅ فعال" if _wp_enabled == "1" else "❌ غیرفعال"
        return (
            "🤖 <b>مدیریت عملیات ربات</b>\n\n"
            f"🔹 <b>وضعیت ربات:</b> {status_fa}\n"
            f"🔹 <b>تمدید کانفیگ‌های ثبت دستی:</b> {renewal_fa}\n"
            f"🔹 <b>زیرمجموعه‌گیری:</b> {referral_fa}\n"
            f"🔹 <b>فروش عمده:</b> {bulk_fa}\n"
            f"   ↳ حداقل تعداد: <b>{min_qty}</b> | حداکثر تعداد: <b>{max_label}</b>\n"
            f"🔹 <b>اعتبار فاکتور پرداخت:</b> {_inv_fa}\n"
            f"🔹 <b>پرداخت با موجودی:</b> {_wp_fa}\n\n"
            "برای تغییر هر مورد، دکمه وضعیت فعلی آن را لمس کنید."
        )

    if data == "adm:ops":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:noop":
        bot.answer_callback_query(call.id)
        return

    if data == "adm:ops:status":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("bot_status", "on")
        cycle = {"on": "off", "off": "update", "update": "on"}
        new_status = cycle.get(cur, "on")
        setting_set("bot_status", new_status)
        labels = {"on": "روشن", "off": "خاموش", "update": "بروزرسانی"}
        log_admin_action(uid, f"وضعیت ربات به {labels[new_status]} تغییر کرد")
        bot.answer_callback_query(call.id, f"وضعیت ربات: {labels[new_status]}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:renewal":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("manual_renewal_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("manual_renewal_enabled", new_val)
        log_admin_action(uid, f"تمدید دستی {'فعال' if new_val == '1' else 'غیرفعال'} شد")
        label = "فعال" if new_val == "1" else "غیرفعال"
        bot.answer_callback_query(call.id, f"تمدید دستی: {label}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:referral_toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("referral_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("referral_enabled", new_val)
        log_admin_action(uid, f"زیرمجموعه‌گیری {'فعال' if new_val == '1' else 'غیرفعال'} شد")
        label = "فعال" if new_val == "1" else "غیرفعال"
        bot.answer_callback_query(call.id, f"زیرمجموعه‌گیری: {label}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:bulk_sale":
        # Legacy — redirect to the sub-menu
        bot.answer_callback_query(call.id)
        from types import SimpleNamespace as _SN
        fake = _SN(id=call.id, from_user=call.from_user, message=call.message, data="adm:ops:bulk_menu")
        _dispatch_callback(fake, uid, "adm:ops:bulk_menu")
        return

    # ── Bulk Sale Sub-menu ────────────────────────────────────────────────────
    def _bulk_menu_kb():
        bulk_mode = setting_get("bulk_sale_mode", "everyone")
        min_qty, max_qty = get_bulk_qty_limits()
        max_label = "بدون محدودیت" if max_qty == 0 else str(max_qty)
        bulk_map  = {
            "everyone":    "✅ همه کاربران",
            "agents_only": "🤝 فقط نمایندگان",
            "disabled":    "❌ غیرفعال",
        }
        mode_label = bulk_map.get(bulk_mode, "✅ همه کاربران")
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(
            types.InlineKeyboardButton(mode_label,       callback_data="adm:ops:bulk_mode"),
            types.InlineKeyboardButton("📦 وضعیت فروش عمده", callback_data="adm:ops:noop"),
        )
        kb.row(
            types.InlineKeyboardButton(f"⬇️ حداقل: {min_qty} عدد",     callback_data="adm:ops:bulk_min"),
            types.InlineKeyboardButton(f"⬆️ حداکثر: {max_label}",      callback_data="adm:ops:bulk_max"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ops", icon_custom_emoji_id="5253997076169115797"))
        return kb

    def _bulk_menu_text():
        bulk_mode = setting_get("bulk_sale_mode", "everyone")
        min_qty, max_qty = get_bulk_qty_limits()
        max_label = "بدون محدودیت" if max_qty == 0 else f"{max_qty} عدد"
        bulk_fa   = {
            "everyone":    "✅ همه کاربران",
            "agents_only": "🤝 فقط نمایندگان",
            "disabled":    "❌ غیرفعال",
        }.get(bulk_mode, "✅ همه کاربران")
        return (
            "📦 <b>تنظیمات فروش عمده</b>\n\n"
            f"🔹 <b>وضعیت:</b> {bulk_fa}\n"
            f"🔹 <b>حداقل تعداد خرید:</b> {min_qty} عدد\n"
            f"🔹 <b>حداکثر تعداد خرید:</b> {max_label}\n\n"
            "برای تغییر هر گزینه، دکمه مربوطه را لمس کنید."
        )

    if data == "adm:ops:bulk_menu":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _bulk_menu_text(), _bulk_menu_kb())
        return

    if data == "adm:ops:bulk_mode":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("bulk_sale_mode", "everyone")
        cycle = {"everyone": "agents_only", "agents_only": "disabled", "disabled": "everyone"}
        new_val = cycle.get(cur, "everyone")
        setting_set("bulk_sale_mode", new_val)
        labels = {"everyone": "همه کاربران", "agents_only": "فقط نمایندگان", "disabled": "غیرفعال"}
        log_admin_action(uid, f"فروش عمده: {labels[new_val]}")
        bot.answer_callback_query(call.id, f"فروش عمده: {labels[new_val]}")
        send_or_edit(call, _bulk_menu_text(), _bulk_menu_kb())
        return

    if data == "adm:ops:bulk_min":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_bulk_min_qty")
        bot.answer_callback_query(call.id)
        cur_min = setting_get("bulk_min_qty", "1")
        send_or_edit(call,
            "⬇️ <b>تنظیم حداقل تعداد خرید</b>\n\n"
            "تعداد حداقل کانفیگ در هر سفارش فروش عمده را وارد کنید.\n\n"
            f"📌 مقدار فعلی: <b>{cur_min}</b>\n\n"
            "📝 <i>یک عدد صحیح و مثبت وارد کنید (مثلاً ۱، ۲، ۵)</i>",
            back_button("adm:ops:bulk_menu"))
        return

    if data == "adm:ops:bulk_max":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_bulk_max_qty")
        bot.answer_callback_query(call.id)
        cur_max = setting_get("bulk_max_qty", "0")
        cur_max_label = "بدون محدودیت" if cur_max == "0" else cur_max
        send_or_edit(call,
            "⬆️ <b>تنظیم حداکثر تعداد خرید</b>\n\n"
            "تعداد حداکثر کانفیگ در هر سفارش فروش عمده را وارد کنید.\n\n"
            f"📌 مقدار فعلی: <b>{cur_max_label}</b>\n\n"
            "📝 <i>یک عدد صحیح مثبت وارد کنید، یا <b>0</b> برای «بدون محدودیت»</i>",
            back_button("adm:ops:bulk_menu"))
        return

    # ── Invoice Expiry Sub-menu ───────────────────────────────────────────────
    def _invoice_expiry_menu_kb():
        enabled = setting_get("invoice_expiry_enabled", "1")
        mins    = setting_get("invoice_expiry_minutes", "30")
        toggle_label = "✅ فعال — کلیک کنید تا غیرفعال شود" if enabled == "1" else "❌ غیرفعال — کلیک کنید تا فعال شود"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:ops:inv_exp:toggle"))
        if enabled == "1":
            kb.add(types.InlineKeyboardButton(f"⏱ تنظیم زمان فاکتور: {mins} دقیقه", callback_data="adm:ops:inv_exp:set_mins"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ops", icon_custom_emoji_id="5253997076169115797"))
        return kb

    def _invoice_expiry_menu_text():
        enabled = setting_get("invoice_expiry_enabled", "1")
        mins    = setting_get("invoice_expiry_minutes", "30")
        status_fa = f"✅ فعال — هر فاکتور تا <b>{mins} دقیقه</b> معتبر است." if enabled == "1" else "❌ غیرفعال — فاکتورها محدودیت زمانی ندارند."
        return (
            "📄 <b>تنظیمات اعتبار فاکتور پرداخت</b>\n\n"
            f"🔹 <b>وضعیت:</b> {status_fa}\n\n"
            "وقتی فعال باشد، هر فاکتور پرداخت (خرید، تمدید، شارژ کیف پول) "
            "فقط تا مدت تعیین‌شده معتبر است. پس از اتمام زمان، کاربر نمی‌تواند "
            "از آن فاکتور برای پرداخت استفاده کند.\n\n"
            "مقدار پیش‌فرض: <b>30 دقیقه</b>"
        )

    if data == "adm:ops:invoice_expiry":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _invoice_expiry_menu_text(), _invoice_expiry_menu_kb())
        return

    if data == "adm:ops:inv_exp:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("invoice_expiry_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("invoice_expiry_enabled", new_val)
        label = "فعال" if new_val == "1" else "غیرفعال"
        log_admin_action(uid, f"اعتبار فاکتور پرداخت {label} شد")
        bot.answer_callback_query(call.id, f"اعتبار فاکتور: {label}")
        send_or_edit(call, _invoice_expiry_menu_text(), _invoice_expiry_menu_kb())
        return

    if data == "adm:ops:inv_exp:set_mins":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur_mins = setting_get("invoice_expiry_minutes", "30")
        state_set(uid, "admin_set_invoice_expiry_minutes")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "⏱ <b>تنظیم زمان اعتبار فاکتور</b>\n\n"
            "مدت زمان اعتبار فاکتور پرداخت را به دقیقه وارد کنید.\n\n"
            f"📌 مقدار فعلی: <b>{cur_mins} دقیقه</b>\n\n"
            "📝 <i>یک عدد صحیح مثبت وارد کنید (مثلاً ۱۰، ۳۰، ۶۰)</i>",
            back_button("adm:ops:invoice_expiry"))
        return

    # ── Wallet Pay Toggle ─────────────────────────────────────────────────────
    if data == "adm:ops:wallet_pay_toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("wallet_pay_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("wallet_pay_enabled", new_val)
        label = "فعال" if new_val == "1" else "غیرفعال"
        log_admin_action(uid, f"پرداخت با موجودی {label} شد")
        bot.answer_callback_query(call.id, f"پرداخت با موجودی: {label}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    # ── Wallet Pay Exceptions Sub-menu ────────────────────────────────────────
    def _wpe_page_from_data(d):
        """Extract page number from adm:wpe:list:{page}"""
        parts = d.split(":")
        try:
            return int(parts[3]) if len(parts) > 3 else 0
        except (ValueError, IndexError):
            return 0

    def _wpe_kb(page=0, search=None):
        PER_PAGE = 8
        rows, total = get_wallet_pay_exceptions(page=page, per_page=PER_PAGE, search=search)
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        kb = types.InlineKeyboardMarkup(row_width=1)
        # Search / clear
        if search:
            kb.add(types.InlineKeyboardButton(f"🔍 جستجو: {search}  ❌ پاک کردن", callback_data="adm:wpe:clr"))
        else:
            kb.add(types.InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="adm:wpe:srch"))
        kb.add(types.InlineKeyboardButton("➕ افزودن استثنا", callback_data="adm:wpe:add"))
        # User rows
        for r in rows:
            name = r["full_name"] or r["username"] or str(r["user_id"])
            kb.row(
                types.InlineKeyboardButton(f"👤 {name}", callback_data=f"adm:wpe:noop"),
                types.InlineKeyboardButton("❌ حذف", callback_data=f"adm:wpe:rm:{r['id']}"),
            )
        # Pagination
        nav_btns = []
        if page > 0:
            nav_btns.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"adm:wpe:list:{page - 1}"))
        nav_btns.append(types.InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="adm:wpe:noop"))
        if page + 1 < total_pages:
            nav_btns.append(types.InlineKeyboardButton("بعدی ▶️", callback_data=f"adm:wpe:list:{page + 1}"))
        if nav_btns:
            kb.row(*nav_btns)
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ops", icon_custom_emoji_id="5253997076169115797"))
        return kb

    def _wpe_text(page=0, search=None):
        PER_PAGE = 8
        _rows, total = get_wallet_pay_exceptions(page=page, per_page=PER_PAGE, search=search)
        wp_fa = "✅ فعال" if setting_get("wallet_pay_enabled", "1") == "1" else "❌ غیرفعال"
        return (
            "💰 <b>پرداخت با موجودی — استثناها</b>\n\n"
            f"🔹 وضعیت کلی: {wp_fa}\n"
            f"🔹 تعداد استثناها: <b>{total}</b> کاربر\n\n"
            "کاربران موجود در این لیست حتی وقتی پرداخت با موجودی <b>غیرفعال</b> باشد، "
            "می‌توانند از کیف پول استفاده کنند."
        )

    if data == "adm:ops:wallet_pay_exc" or data.startswith("adm:wpe:list:"):
        if not admin_has_perm(uid, "settings"):
            if call.id:
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        if call.id:
            bot.answer_callback_query(call.id)
        page = _wpe_page_from_data(data)
        sd = state_data(uid) if state_name(uid) == "admin_wallet_exc_search_active" else {}
        search = sd.get("query")
        send_or_edit(call, _wpe_text(page, search), _wpe_kb(page, search))
        return

    if data == "adm:wpe:noop":
        bot.answer_callback_query(call.id)
        return

    if data == "adm:wpe:srch":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_wallet_exc_search", back_cb="adm:ops:wallet_pay_exc")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔍 <b>جستجوی استثناها</b>\n\n"
            "نام کاربری، نام کامل یا شناسه کاربری را وارد کنید:",
            back_button("adm:ops:wallet_pay_exc"))
        return

    if data == "adm:wpe:clr":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_clear(uid)
        bot.answer_callback_query(call.id)
        send_or_edit(call, _wpe_text(0, None), _wpe_kb(0, None))
        return

    if data == "adm:wpe:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_wallet_exc_add", back_cb="adm:ops:wallet_pay_exc")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "➕ <b>افزودن استثنا</b>\n\n"
            "نام کاربری، نام کامل یا شناسه عددی کاربر را وارد کنید:",
            back_button("adm:ops:wallet_pay_exc"))
        return

    if data.startswith("adm:wpe:rm:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        try:
            row_id = int(data.split(":")[-1])
        except ValueError:
            bot.answer_callback_query(call.id, "خطا")
            return
        remove_wallet_pay_exception(row_id)
        log_admin_action(uid, f"استثنا پرداخت موجودی حذف شد (id={row_id})")
        bot.answer_callback_query(call.id, "حذف شد ✅")
        send_or_edit(call, _wpe_text(0, None), _wpe_kb(0, None))
        return

    if data.startswith("adm:wpe:pick:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        try:
            target_uid = int(data.split(":")[-1])
        except ValueError:
            bot.answer_callback_query(call.id, "خطا")
            return
        added = add_wallet_pay_exception(target_uid)
        state_clear(uid)
        if added:
            log_admin_action(uid, f"استثنا پرداخت موجودی اضافه شد (user_id={target_uid})")
            bot.answer_callback_query(call.id, "اضافه شد ✅")
        else:
            bot.answer_callback_query(call.id, "این کاربر قبلاً در لیست است.", show_alert=True)
        send_or_edit(call, _wpe_text(0, None), _wpe_kb(0, None))
        return

    # ── Referral Settings ─────────────────────────────────────────────────────
    def _ref_settings_kb():
        sr_enabled = setting_get("referral_start_reward_enabled", "0")
        pr_enabled = setting_get("referral_purchase_reward_enabled", "0")
        sr_label = "✅ فعال" if sr_enabled == "1" else "❌ غیرفعال"
        pr_label = "✅ فعال" if pr_enabled == "1" else "❌ غیرفعال"
        sr_type = setting_get("referral_start_reward_type", "wallet")
        pr_type = setting_get("referral_purchase_reward_type", "wallet")
        sr_count = setting_get("referral_start_reward_count", "1")
        pr_count = setting_get("referral_purchase_reward_count", "1")
        sr_type_label = "💰 کیف پول" if sr_type == "wallet" else "📦 کانفیگ"
        pr_type_label = "💰 کیف پول" if pr_type == "wallet" else "📦 کانفیگ"
        reward_condition = setting_get("referral_reward_condition", "channel")
        rc_label = "📢 دعوت + عضویت در کانال" if reward_condition == "channel" else "🚀 فقط دعوت به ربات"

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📸 تنظیم بنر اشتراک‌گذاری", callback_data="adm:ref:banner"))
        # Reward condition
        kb.add(types.InlineKeyboardButton("── 🔐 شرط دریافت پاداش ──", callback_data="adm:ops:noop"))
        kb.row(
            types.InlineKeyboardButton(rc_label, callback_data="adm:ref:reward_condition"),
            types.InlineKeyboardButton("شرط ریوارد استارت", callback_data="adm:ops:noop"),
        )
        # Start reward section
        kb.add(types.InlineKeyboardButton("── 🎁 هدیه استارت ──", callback_data="adm:ops:noop"))
        kb.row(
            types.InlineKeyboardButton(sr_label, callback_data="adm:ref:sr:toggle"),
            types.InlineKeyboardButton("وضعیت هدیه استارت", callback_data="adm:ops:noop"),
        )
        kb.add(types.InlineKeyboardButton(f"📊 تعداد: {sr_count} زیرمجموعه", callback_data="adm:ref:sr:count"))
        kb.add(types.InlineKeyboardButton(f"🎯 نوع هدیه: {sr_type_label}", callback_data="adm:ref:sr:type"))
        if sr_type == "wallet":
            sr_amount = setting_get("referral_start_reward_amount", "0")
            kb.add(types.InlineKeyboardButton(f"💵 مبلغ: {fmt_price(int(sr_amount))} تومان", callback_data="adm:ref:sr:amount"))
        else:
            sr_pkg = setting_get("referral_start_reward_package", "")
            pkg_name = "انتخاب نشده"
            if sr_pkg:
                _p = get_package(int(sr_pkg)) if sr_pkg.isdigit() else None
                if _p:
                    pkg_name = _p["name"]
            kb.add(types.InlineKeyboardButton(f"📦 پکیج: {pkg_name}", callback_data="adm:ref:sr:pkg"))

        # Purchase reward section
        kb.add(types.InlineKeyboardButton("── 💸 هدیه خرید ──", callback_data="adm:ops:noop"))
        kb.row(
            types.InlineKeyboardButton(pr_label, callback_data="adm:ref:pr:toggle"),
            types.InlineKeyboardButton("وضعیت هدیه خرید", callback_data="adm:ops:noop"),
        )
        kb.add(types.InlineKeyboardButton(f"📊 تعداد: {pr_count} خرید", callback_data="adm:ref:pr:count"))
        kb.add(types.InlineKeyboardButton(f"🎯 نوع هدیه: {pr_type_label}", callback_data="adm:ref:pr:type"))
        if pr_type == "wallet":
            pr_amount = setting_get("referral_purchase_reward_amount", "0")
            kb.add(types.InlineKeyboardButton(f"💵 مبلغ: {fmt_price(int(pr_amount))} تومان", callback_data="adm:ref:pr:amount"))
        else:
            pr_pkg = setting_get("referral_purchase_reward_package", "")
            pkg_name = "انتخاب نشده"
            if pr_pkg:
                _p = get_package(int(pr_pkg)) if pr_pkg.isdigit() else None
                if _p:
                    pkg_name = _p["name"]
            kb.add(types.InlineKeyboardButton(f"📦 پکیج: {pkg_name}", callback_data="adm:ref:pr:pkg"))

        # Anti-spam section
        kb.add(types.InlineKeyboardButton("── 🛡 سیستم ضد اسپم ──", callback_data="adm:ops:noop"))
        as_enabled = setting_get("referral_antispam_enabled", "0")
        as_label = "✅ فعال" if as_enabled == "1" else "❌ غیرفعال"
        kb.add(types.InlineKeyboardButton(f"🛡 ضد اسپم: {as_label}", callback_data="adm:ref:antispam"))

        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ops", icon_custom_emoji_id="5253997076169115797"))
        return kb

    def _ref_settings_text():
        sr_enabled = "✅ فعال" if setting_get("referral_start_reward_enabled", "0") == "1" else "❌ غیرفعال"
        pr_enabled = "✅ فعال" if setting_get("referral_purchase_reward_enabled", "0") == "1" else "❌ غیرفعال"
        reward_condition = setting_get("referral_reward_condition", "channel")
        rc_fa = "📢 دعوت + عضویت در کانال" if reward_condition == "channel" else "🚀 فقط دعوت به ربات"
        return (
            "⚙️ <b>تنظیمات زیرمجموعه‌گیری</b>\n\n"
            f"🔐 <b>شرط دریافت پاداش:</b> {rc_fa}\n"
            f"🎁 هدیه استارت: {sr_enabled}\n"
            f"💸 هدیه خرید زیرمجموعه: {pr_enabled}\n\n"
            "هر بخش را با دکمه‌های زیر تنظیم کنید."
        )

    if data == "adm:ref:settings":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:banner":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_ref_banner")
        bot.answer_callback_query(call.id)
        cur_text = setting_get("referral_banner_text", "")
        cur_photo = setting_get("referral_banner_photo", "")
        status = ""
        if cur_text:
            status += f"\n\n📝 متن فعلی:\n{esc(cur_text[:200])}"
        if cur_photo:
            status += "\n🖼 عکس: ✅ ست شده"
        kb = types.InlineKeyboardMarkup()
        if cur_text or cur_photo:
            kb.add(types.InlineKeyboardButton("🗑 حذف بنر سفارشی", callback_data="adm:ref:banner:del"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ref:settings", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📸 <b>تنظیم بنر اشتراک‌گذاری</b>\n\n"
            "متن یا عکس+کپشن مورد نظر برای اشتراک‌گذاری لینک دعوت ارسال کنید.\n"
            "این متن/عکس هنگام اشتراک‌گذاری لینک دعوت به کاربران نمایش داده می‌شود.\n\n"
            "💡 لینک دعوت کاربر به صورت خودکار به انتهای متن اضافه می‌شود."
            f"{status}", kb)
        return

    if data == "adm:ref:banner:del":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        setting_set("referral_banner_text", "")
        setting_set("referral_banner_photo", "")
        log_admin_action(uid, "بنر اشتراک‌گذاری حذف شد")
        bot.answer_callback_query(call.id, "بنر سفارشی حذف شد.")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # Reward condition toggle
    if data == "adm:ref:reward_condition":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("referral_reward_condition", "channel")
        new_val = "start_only" if cur == "channel" else "channel"
        setting_set("referral_reward_condition", new_val)
        labels = {
            "channel":    "دعوت + عضویت در کانال",
            "start_only": "فقط دعوت به ربات",
        }
        log_admin_action(uid, f"شرط پاداش زیرمجموعه به «{labels[new_val]}» تغییر کرد")
        bot.answer_callback_query(call.id, f"شرط پاداش: {labels[new_val]}")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # Start reward toggles
    if data == "adm:ref:sr:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("referral_start_reward_enabled", "0")
        setting_set("referral_start_reward_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"هدیه استارت زیرمجموعه {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:sr:count":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_ref_sr_count")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔢 <b>تعداد زیرمجموعه برای هدیه استارت</b>\n\n"
            "ادمین عزیز، وارد کنید بعد از چند زیرمجموعه جدید، هدیه به معرف داده شود.\n\n"
            f"مقدار فعلی: <b>{setting_get('referral_start_reward_count', '1')}</b>",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:sr:type":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("referral_start_reward_type", "wallet")
        new_val = "config" if cur == "wallet" else "wallet"
        setting_set("referral_start_reward_type", new_val)
        log_admin_action(uid, f"نوع هدیه استارت به {'کیف پول' if new_val == 'wallet' else 'کانفیگ'} تغییر کرد")
        bot.answer_callback_query(call.id, f"نوع هدیه: {'کیف پول' if new_val == 'wallet' else 'کانفیگ'}")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:sr:amount":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_ref_sr_amount")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "💵 <b>مبلغ شارژ کیف پول (هدیه استارت)</b>\n\n"
            "مبلغ به تومان وارد کنید:\n\n"
            f"مقدار فعلی: <b>{fmt_price(int(setting_get('referral_start_reward_amount', '0')))}</b> تومان",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:sr:pkg":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        # Show package list for selection
        all_types = get_all_types()
        kb = types.InlineKeyboardMarkup()
        for t in all_types:
            pkgs = get_packages(t["id"])
            for p in pkgs:
                kb.add(types.InlineKeyboardButton(
                    f"{t['name']} - {p['name']}",
                    callback_data=f"adm:ref:sr:pkgsel:{p['id']}"
                ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ref:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📦 <b>انتخاب پکیج هدیه استارت</b>\n\nپکیجی که می‌خواهید به عنوان هدیه داده شود انتخاب کنید:", kb)
        return

    if data.startswith("adm:ref:sr:pkgsel:"):
        pkg_id = data.split(":")[4]
        setting_set("referral_start_reward_package", pkg_id)
        log_admin_action(uid, f"پکیج هدیه استارت به #{pkg_id} تنظیم شد")
        bot.answer_callback_query(call.id, "پکیج هدیه استارت تنظیم شد.")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # Purchase reward toggles
    if data == "adm:ref:pr:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("referral_purchase_reward_enabled", "0")
        setting_set("referral_purchase_reward_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"هدیه خرید زیرمجموعه {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:pr:count":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_ref_pr_count")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔢 <b>تعداد خرید زیرمجموعه برای هدیه</b>\n\n"
            "وارد کنید بعد از چند خرید اول زیرمجموعه‌ها، هدیه به معرف داده شود.\n"
            "⚠️ فقط اولین خرید هر زیرمجموعه در نظر گرفته می‌شود.\n\n"
            f"مقدار فعلی: <b>{setting_get('referral_purchase_reward_count', '1')}</b>",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:pr:type":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("referral_purchase_reward_type", "wallet")
        new_val = "config" if cur == "wallet" else "wallet"
        setting_set("referral_purchase_reward_type", new_val)
        log_admin_action(uid, f"نوع هدیه خرید به {'کیف پول' if new_val == 'wallet' else 'کانفیگ'} تغییر کرد")
        bot.answer_callback_query(call.id, f"نوع هدیه: {'کیف پول' if new_val == 'wallet' else 'کانفیگ'}")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:pr:amount":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_ref_pr_amount")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "💵 <b>مبلغ شارژ کیف پول (هدیه خرید)</b>\n\n"
            "مبلغ به تومان وارد کنید:\n\n"
            f"مقدار فعلی: <b>{fmt_price(int(setting_get('referral_purchase_reward_amount', '0')))}</b> تومان",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:pr:pkg":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        all_types = get_all_types()
        kb = types.InlineKeyboardMarkup()
        for t in all_types:
            pkgs = get_packages(t["id"])
            for p in pkgs:
                kb.add(types.InlineKeyboardButton(
                    f"{t['name']} - {p['name']}",
                    callback_data=f"adm:ref:pr:pkgsel:{p['id']}"
                ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ref:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📦 <b>انتخاب پکیج هدیه خرید</b>\n\nپکیجی که می‌خواهید به عنوان هدیه داده شود انتخاب کنید:", kb)
        return

    if data.startswith("adm:ref:pr:pkgsel:"):
        pkg_id = data.split(":")[4]
        setting_set("referral_purchase_reward_package", pkg_id)
        log_admin_action(uid, f"پکیج هدیه خرید به #{pkg_id} تنظیم شد")
        bot.answer_callback_query(call.id, "پکیج هدیه خرید تنظیم شد.")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # ── Anti-Spam Settings ────────────────────────────────────────────────────

    _ANTISPAM_ACTION_LABELS = {
        "report_only":  "فقط گزارش به ادمین",
        "referral_ban": "محدود کامل از زیرمجموعه‌گیری",
        "full_ban":     "محدود شدن از کل ربات",
    }
    _RESTRICTIONS_PER_PAGE = 8

    def _antispam_text():
        enabled   = setting_get("referral_antispam_enabled", "0")
        window    = setting_get("referral_antispam_window", "15")
        threshold = setting_get("referral_antispam_threshold", "10")
        action    = setting_get("referral_antispam_action", "report_only")
        status_fa = "✅ فعال" if enabled == "1" else "❌ غیرفعال"
        action_fa = _ANTISPAM_ACTION_LABELS.get(action, action)
        return (
            "🛡 <b>سیستم ضد اسپم زیرمجموعه‌گیری</b>\n\n"
            f"📌 وضعیت: <b>{status_fa}</b>\n"
            f"⏱ مدت زمان بازه: <b>{window} ثانیه</b>\n"
            f"🔢 آستانه دعوت: <b>{threshold} دعوت</b>\n"
            f"🎯 نتیجه در صورت تشخیص: <b>{action_fa}</b>\n\n"
            "اگر یک کاربر در بازه زمانی تنظیم‌شده، به اندازه آستانه یا بیشتر دعوت انجام دهد، "
            "به‌عنوان مشکوک شناسایی می‌شود و اقدام تنظیم‌شده اعمال خواهد شد."
        )

    def _antispam_kb():
        enabled   = setting_get("referral_antispam_enabled", "0")
        window    = setting_get("referral_antispam_window", "15")
        threshold = setting_get("referral_antispam_threshold", "10")
        action    = setting_get("referral_antispam_action", "report_only")
        action_fa = _ANTISPAM_ACTION_LABELS.get(action, action)
        en_label  = "✅ فعال" if enabled == "1" else "❌ غیرفعال"
        kb2 = types.InlineKeyboardMarkup()
        kb2.row(
            types.InlineKeyboardButton("✅ فعال کردن",    callback_data="adm:ref:as:enable"),
            types.InlineKeyboardButton("❌ غیرفعال کردن", callback_data="adm:ref:as:disable"),
        )
        kb2.add(types.InlineKeyboardButton(f"⏱ مدت زمان: {window} ثانیه", callback_data="adm:ref:as:window"))
        kb2.add(types.InlineKeyboardButton(f"🔢 تعداد: {threshold} دعوت",  callback_data="adm:ref:as:threshold"))
        kb2.add(types.InlineKeyboardButton(f"🎯 تنظیم نتیجه: {action_fa}", callback_data="adm:ref:as:action"))
        kb2.add(types.InlineKeyboardButton("👥 مدیریت اشخاص محدود شده",   callback_data="adm:ref:restrictions:0"))
        kb2.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ref:settings",
                                            icon_custom_emoji_id="5253997076169115797"))
        return kb2

    def _restrictions_text(page):
        rows, total = get_referral_restrictions_paged(page, _RESTRICTIONS_PER_PAGE)
        total_pages = max(1, (total + _RESTRICTIONS_PER_PAGE - 1) // _RESTRICTIONS_PER_PAGE)
        t = (
            "👥 <b>مدیریت اشخاص محدود شده</b>\n\n"
            f"تعداد کل محدودیت‌ها: <b>{total}</b>\n"
            f"صفحه <b>{page + 1}</b> از <b>{total_pages}</b>\n\n"
        )
        if not rows:
            t += "هیچ کاربری در لیست محدودیت نیست."
        return t

    def _restrictions_kb(page):
        rows, total = get_referral_restrictions_paged(page, _RESTRICTIONS_PER_PAGE)
        total_pages = max(1, (total + _RESTRICTIONS_PER_PAGE - 1) // _RESTRICTIONS_PER_PAGE)
        kb2 = types.InlineKeyboardMarkup()
        kb2.add(types.InlineKeyboardButton("➕ اضافه کردن", callback_data="adm:ref:restrictions:add"))
        for row in rows:
            rtype_fa = "🚫 محدود کامل" if row["restriction_type"] == "full" else "⛔ محدود از زیرمجموعه‌گیری"
            name = row["username"] and f"@{row['username']}" or row["full_name"] or str(row["user_id"])
            kb2.row(
                types.InlineKeyboardButton(f"{name[:18]}", callback_data="adm:ops:noop"),
                types.InlineKeyboardButton(rtype_fa, callback_data=f"adm:ref:restrictions:toggle:{row['user_id']}"),
                types.InlineKeyboardButton("🗑 حذف", callback_data=f"adm:ref:restrictions:rm:{row['id']}"),
            )
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"adm:ref:restrictions:{page - 1}"))
        nav.append(types.InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="adm:ops:noop"))
        if page < total_pages - 1:
            nav.append(types.InlineKeyboardButton("▶️ بعدی", callback_data=f"adm:ref:restrictions:{page + 1}"))
        if nav:
            kb2.row(*nav)
        kb2.add(types.InlineKeyboardButton("بازگشت به ضد اسپم", callback_data="adm:ref:antispam",
                                            icon_custom_emoji_id="5253997076169115797"))
        return kb2

    if data == "adm:ref:antispam":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data == "adm:ref:as:enable":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        setting_set("referral_antispam_enabled", "1")
        log_admin_action(uid, "سیستم ضد اسپم زیرمجموعه‌گیری فعال شد")
        bot.answer_callback_query(call.id, "✅ سیستم ضد اسپم فعال شد.")
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data == "adm:ref:as:disable":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        setting_set("referral_antispam_enabled", "0")
        log_admin_action(uid, "سیستم ضد اسپم زیرمجموعه‌گیری غیرفعال شد")
        bot.answer_callback_query(call.id, "❌ سیستم ضد اسپم غیرفعال شد.")
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data == "adm:ref:as:window":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_ref_as_window")
        bot.answer_callback_query(call.id)
        cur = setting_get("referral_antispam_window", "15")
        send_or_edit(call,
            "⏱ <b>تنظیم مدت زمان بازه (ثانیه)</b>\n\n"
            "تعداد ثانیه‌ای که سیستم برای شمارش دعوت‌ها در نظر می‌گیرد را وارد کنید.\n\n"
            f"مقدار فعلی: <b>{cur} ثانیه</b>",
            back_button("adm:ref:antispam"))
        return

    if data == "adm:ref:as:threshold":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_ref_as_threshold")
        bot.answer_callback_query(call.id)
        cur = setting_get("referral_antispam_threshold", "10")
        send_or_edit(call,
            "🔢 <b>تنظیم آستانه تعداد دعوت</b>\n\n"
            "تعداد دعوت در بازه زمانی را وارد کنید که باعث تشخیص مشکوک می‌شود.\n\n"
            f"مقدار فعلی: <b>{cur} دعوت</b>",
            back_button("adm:ref:antispam"))
        return

    if data == "adm:ref:as:action":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur_action = setting_get("referral_antispam_action", "report_only")
        kb2 = types.InlineKeyboardMarkup()
        for act_key, act_fa in _ANTISPAM_ACTION_LABELS.items():
            tick = "✅ " if act_key == cur_action else ""
            kb2.add(types.InlineKeyboardButton(f"{tick}{act_fa}", callback_data=f"adm:ref:as:setaction:{act_key}"))
        kb2.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ref:antispam",
                                            icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🎯 <b>تنظیم نتیجه در صورت تشخیص اسپم</b>\n\n"
            "یکی از گزینه‌های زیر را انتخاب کنید:\n\n"
            "▫️ <b>محدود کامل از زیرمجموعه‌گیری</b> — فقط بخش دعوت مسدود می‌شود\n"
            "▫️ <b>محدود شدن از کل ربات</b> — دسترسی کامل کاربر قطع می‌شود\n"
            "▫️ <b>فقط گزارش به ادمین</b> — محدودیتی اعمال نمی‌شود، فقط ادمین مطلع می‌شود",
            kb2)
        return

    if data.startswith("adm:ref:as:setaction:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        new_action = parts[4] if len(parts) > 4 else ""
        if new_action not in _ANTISPAM_ACTION_LABELS:
            bot.answer_callback_query(call.id, "گزینه نامعتبر است.", show_alert=True)
            return
        setting_set("referral_antispam_action", new_action)
        log_admin_action(uid, f"نتیجه ضد اسپم به «{_ANTISPAM_ACTION_LABELS[new_action]}» تغییر کرد")
        bot.answer_callback_query(call.id, f"✅ نتیجه: {_ANTISPAM_ACTION_LABELS[new_action]}")
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data.startswith("adm:ref:restrictions:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")  # adm:ref:restrictions:<page|add|rm|toggle>[:extra]

        # Pagination: adm:ref:restrictions:<page_number>
        if len(parts) == 4 and parts[3].isdigit():
            page = int(parts[3])
            bot.answer_callback_query(call.id)
            send_or_edit(call, _restrictions_text(page), _restrictions_kb(page))
            return

        sub = parts[3] if len(parts) > 3 else ""

        if sub == "add":
            state_set(uid, "admin_ref_restriction_add_uid", back_cb="adm:ref:restrictions:0")
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "➕ <b>افزودن کاربر به لیست محدودیت</b>\n\n"
                "شناسه عددی کاربر (User ID) یا نام کاربری (@username) را وارد کنید:",
                back_button("adm:ref:restrictions:0"))
            return

        if sub == "rm" and len(parts) > 4:
            try:
                row_id = int(parts[4])
            except ValueError:
                bot.answer_callback_query(call.id, "خطا در شناسه.")
                return
            result = remove_referral_restriction_by_id(row_id)
            if result:
                removed_uid, removed_type = result
                # If it was a full ban, restore user status if their restriction was auto
                if removed_type == "full":
                    from ..db import set_user_status as _sus
                    try:
                        _sus(removed_uid, "unsafe")
                    except Exception:
                        pass
                log_admin_action(uid, f"محدودیت زیرمجموعه‌گیری کاربر {removed_uid} حذف شد")
                bot.answer_callback_query(call.id, "✅ محدودیت حذف شد.")
            else:
                bot.answer_callback_query(call.id, "⚠️ محدودیت یافت نشد.")
            send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
            return

        if sub == "toggle" and len(parts) > 4:
            try:
                target_uid = int(parts[4])
            except ValueError:
                bot.answer_callback_query(call.id, "خطا در شناسه.")
                return
            new_type = toggle_referral_restriction_type(target_uid)
            if new_type is None:
                bot.answer_callback_query(call.id, "⚠️ کاربر در لیست یافت نشد.", show_alert=True)
                send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
                return
            # Sync user status with restriction type
            if new_type == "full":
                _set_user_restricted_db(target_uid, 0)
            else:
                from ..db import set_user_status as _sus
                try:
                    _sus(target_uid, "unsafe")
                except Exception:
                    pass
            type_fa = "محدود کامل" if new_type == "full" else "محدود از زیرمجموعه‌گیری"
            log_admin_action(uid, f"نوع محدودیت کاربر {target_uid} به «{type_fa}» تغییر کرد")
            bot.answer_callback_query(call.id, f"✅ تغییر به: {type_fa}")
            send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
            return

        if sub == "pick" and len(parts) > 4:
            # adm:ref:restrictions:pick:<user_id>
            try:
                target_uid = int(parts[4])
            except ValueError:
                bot.answer_callback_query(call.id, "خطا در شناسه.")
                return
            # Show type selection
            kb2 = types.InlineKeyboardMarkup()
            kb2.add(types.InlineKeyboardButton(
                "⛔ محدود از زیرمجموعه‌گیری",
                callback_data=f"adm:ref:restrictions:settype:{target_uid}:referral_only"
            ))
            kb2.add(types.InlineKeyboardButton(
                "🚫 محدود کامل از ربات",
                callback_data=f"adm:ref:restrictions:settype:{target_uid}:full"
            ))
            kb2.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ref:restrictions:0",
                                                icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            tgt_user = get_user(target_uid)
            name_fa = (tgt_user["full_name"] if tgt_user else "") or str(target_uid)
            send_or_edit(call,
                f"👤 <b>انتخاب نوع محدودیت</b>\n\n"
                f"کاربر: <b>{esc(name_fa)}</b> (<code>{target_uid}</code>)\n\n"
                "نوع محدودیت را انتخاب کنید:",
                kb2)
            return

        if sub == "settype" and len(parts) > 5:
            # adm:ref:restrictions:settype:<user_id>:<type>
            try:
                target_uid = int(parts[4])
            except ValueError:
                bot.answer_callback_query(call.id, "خطا در شناسه.")
                return
            rtype = parts[5]
            if rtype not in ("referral_only", "full"):
                bot.answer_callback_query(call.id, "نوع نامعتبر است.", show_alert=True)
                return
            is_new = add_referral_restriction(target_uid, rtype, reason="manual_admin", added_by=uid)
            if rtype == "full":
                _set_user_restricted_db(target_uid, 0)
            else:
                # If previously fully banned due to referral, lift it
                from ..db import get_referral_restriction as _grr, set_user_status as _sus
                existing = _grr(target_uid)
                if not is_new and existing and existing["restriction_type"] == "full":
                    try:
                        _sus(target_uid, "unsafe")
                    except Exception:
                        pass
            state_clear(uid)
            type_fa = "محدود از زیرمجموعه‌گیری" if rtype == "referral_only" else "محدود کامل از ربات"
            log_admin_action(uid, f"محدودیت «{type_fa}» برای کاربر {target_uid} اعمال شد")
            bot.answer_callback_query(call.id, f"✅ محدودیت اعمال شد: {type_fa}")
            send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
            return

        # Fallback — unknown sub-command
        bot.answer_callback_query(call.id)
        send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
        return

    # ── Gateway settings ─────────────────────────────────────────────────────
    if data == "adm:set:gateways":
        kb = types.InlineKeyboardMarkup()
        for gw_key, gw_default in [
            ("card",             "💳 کارت به کارت"),
            ("crypto",           "💎 ارز دیجیتال"),
            ("tetrapay",         "💳 درگاه کارت به کارت (TetraPay)"),
            ("swapwallet_crypto","💳 درگاه کارت به کارت و ارز دیجیتال (SwapWallet)"),
            ("tronpays_rial",    "💳 درگاه کارت به کارت (TronPay)"),
        ]:
            enabled = setting_get(f"gw_{gw_key}_enabled", "0")
            status_icon = "🟢" if enabled == "1" else "🔴"
            gw_label = setting_get(f"gw_{gw_key}_display_name", "").strip() or gw_default
            kb.add(types.InlineKeyboardButton(f"{status_icon} {gw_label}", callback_data=f"adm:set:gw:{gw_key}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "💳 <b>درگاه‌های پرداخت</b>\n\nدرگاه مورد نظر را انتخاب کنید:", kb)
        return

    if data == "adm:set:gw:card":
        enabled = setting_get("gw_card_enabled", "0")
        vis = setting_get("gw_card_visibility", "public")
        range_enabled = setting_get("gw_card_range_enabled", "0")
        display_name = setting_get("gw_card_display_name", "")
        random_amount = setting_get("gw_card_random_amount", "0")
        rotation_on = setting_get("gw_card_rotation_enabled", "0")
        enabled_label = "🟢 فعال" if enabled == "1" else "🔴 غیرفعال"
        vis_label = "👥 عمومی" if vis == "public" else "🔒 کاربران امن"
        range_label = "🟢 فعال" if range_enabled == "1" else "🔴 غیرفعال"
        random_label = "🟢 فعال" if random_amount == "1" else "🔴 غیرفعال"
        rotation_label = "🟢 فعال" if rotation_on == "1" else "🔴 غیرفعال"
        active_cards = get_payment_cards(active_only=True)
        cards_count = len(get_payment_cards())
        fee_on = setting_get("gw_card_fee_enabled", "0") == "1"
        bonus_on = setting_get("gw_card_bonus_enabled", "0") == "1"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"وضعیت: {enabled_label}", callback_data="adm:gw:card:toggle"),
            types.InlineKeyboardButton(f"نمایش: {vis_label}", callback_data="adm:gw:card:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"📊 بازه پرداختی: {range_label}", callback_data="adm:gw:card:range"))
        kb.add(types.InlineKeyboardButton(f"🎲 قیمت رندوم: {random_label}", callback_data="adm:gw:card:randamt"))
        kb.add(types.InlineKeyboardButton("🏷 نام نمایشی درگاه", callback_data="adm:gw:card:set_name"))
        kb.add(types.InlineKeyboardButton(f"💳 مدیریت کارت‌ها ({cards_count} کارت)", callback_data="adm:gw:card:cards"))
        fee_bonus_lbl = ("🟢 کارمزد" if fee_on else "🔴 کارمزد") + " | " + ("🟢 بونس" if bonus_on else "🔴 بونس")
        kb.add(types.InlineKeyboardButton(f"🎁 بونس و کارمزد — {fee_bonus_lbl}", callback_data="adm:gw:card:feebonus"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        name_display = display_name or "<i>پیش‌فرض: کارت به کارت</i>"
        cards_status = f"{len(active_cards)} کارت فعال از {cards_count}" if cards_count else "⚠️ هیچ کارتی ثبت نشده"
        text = (
            "💳 <b>درگاه کارت به کارت</b>\n\n"
            f"وضعیت: {enabled_label}\n"
            f"نمایش: {vis_label}\n"
            f"نام نمایشی: {name_display}\n"
            f"🎲 قیمت رندوم: {random_label}\n"
            f"🔄 چرخش کارت: {rotation_label}\n"
            f"💳 کارت‌ها: {cards_status}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:card:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="card")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_card_display_name", "")
        send_or_edit(call,
            f"🏷 <b>نام نمایشی درگاه کارت به کارت</b>\n\n"
            f"مقدار فعلی: <code>{esc(current or 'پیش‌فرض')}</code>\n\n"
            "نام دلخواه را ارسال کنید.\n"
            "برای بازگشت به پیش‌فرض، <code>-</code> ارسال کنید.",
            back_button("adm:set:gw:card"))
        return

    if data == "adm:gw:card:toggle":
        enabled = setting_get("gw_card_enabled", "0")
        setting_set("gw_card_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"درگاه کارت {'غیرفعال' if enabled == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:card")
        return

    if data == "adm:gw:card:randamt":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("gw_card_random_amount", "0")
        setting_set("gw_card_random_amount", "0" if cur == "1" else "1")
        log_admin_action(uid, f"قیمت رندوم کارت {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:card")
        return

    if data == "adm:gw:card:vis":
        vis = setting_get("gw_card_visibility", "public")
        setting_set("gw_card_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"نمایش درگاه کارت به {'secure' if vis == 'public' else 'public'} تغییر کرد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:card")
        return

    # ── Card management ───────────────────────────────────────────────────────
    if data == "adm:gw:card:cards":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        # Auto-migrate legacy card from settings if not already in table
        _legacy_card = setting_get("payment_card", "").strip()
        if _legacy_card:
            _existing = get_payment_cards()
            if not any(c["card_number"] == _legacy_card for c in _existing):
                _legacy_bank  = setting_get("payment_bank",  "").strip()
                _legacy_owner = setting_get("payment_owner", "").strip()
                add_payment_card(_legacy_card, _legacy_bank, _legacy_owner)
        cards = get_payment_cards()
        rotation_on = setting_get("gw_card_rotation_enabled", "0") == "1"
        rotation_lbl = "🟢 فعال" if rotation_on else "🔴 غیرفعال"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ اضافه کردن کارت جدید", callback_data="adm:gw:card:cards:add"))
        kb.add(types.InlineKeyboardButton(f"🔀 رندم کارت‌ها: {rotation_lbl}", callback_data="adm:gw:card:cards:rotation"))
        for c in cards:
            status = "✅" if c["is_active"] else "⛔"
            kb.add(types.InlineKeyboardButton(
                f"{status} {c['card_number']} — {c['bank_name'] or 'بدون نام بانک'}",
                callback_data=f"adm:gw:card:cards:cfg:{c['id']}"
            ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:set:gw:card", icon_custom_emoji_id="5253997076169115797"))
        cards_count = len(cards)
        active_count = sum(1 for c in cards if c["is_active"])
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"💳 <b>مدیریت کارت‌ها</b>\n\n"
            f"تعداد کارت‌ها: <b>{cards_count}</b>\n"
            f"کارت‌های فعال: <b>{active_count}</b>\n"
            f"🔀 رندم: {rotation_lbl}\n\n"
            "برای مدیریت هر کارت روی آن بزنید:",
            kb)
        return

    if data == "adm:gw:card:cards:rotation":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("gw_card_rotation_enabled", "0")
        setting_set("gw_card_rotation_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"چرخش رندم کارت {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:gw:card:cards")
        return

    if data == "adm:gw:card:cards:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_card_add_number")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "💳 <b>اضافه کردن کارت جدید</b>\n\n"
            "شماره کارت را ارسال کنید (فقط اعداد):",
            back_button("adm:gw:card:cards"))
        return

    if data.startswith("adm:gw:card:cards:cfg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        card_id = int(data.split(":")[-1])
        card = get_payment_card(card_id)
        if not card:
            bot.answer_callback_query(call.id, "کارت یافت نشد.", show_alert=True)
            return
        status_lbl = "✅ فعال" if card["is_active"] else "⛔ غیرفعال"
        toggle_lbl = "⛔ غیرفعال کردن" if card["is_active"] else "✅ فعال کردن"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✏️ ویرایش مشخصات کارت", callback_data=f"adm:gw:card:cards:edit:{card_id}"))
        kb.add(types.InlineKeyboardButton(toggle_lbl, callback_data=f"adm:gw:card:cards:toggle:{card_id}"))
        kb.add(types.InlineKeyboardButton("🗑 حذف کارت", callback_data=f"adm:gw:card:cards:del:{card_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:gw:card:cards", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"💳 <b>تنظیمات کارت</b>\n\n"
            f"شماره: <code>{esc(card['card_number'])}</code>\n"
            f"بانک: {esc(card['bank_name'] or '—')}\n"
            f"صاحب کارت: {esc(card['holder_name'] or '—')}\n"
            f"وضعیت: {status_lbl}",
            kb)
        return

    if data.startswith("adm:gw:card:cards:toggle:"):
        card_id = int(data.split(":")[-1])
        new_state = toggle_payment_card_active(card_id)
        log_admin_action(uid, f"کارت {card_id} {'فعال' if new_state else 'غیرفعال'} شد")
        bot.answer_callback_query(call.id, "✅ وضعیت کارت تغییر یافت.")
        _fake_call(call, f"adm:gw:card:cards:cfg:{card_id}")
        return

    if data.startswith("adm:gw:card:cards:del:"):
        card_id = int(data.split(":")[-1])
        delete_payment_card(card_id)
        log_admin_action(uid, f"کارت {card_id} حذف شد")
        bot.answer_callback_query(call.id, "🗑 کارت حذف شد.")
        _fake_call(call, "adm:gw:card:cards")
        return

    if data.startswith("adm:gw:card:cards:edit:"):
        card_id = int(data.split(":")[-1])
        card = get_payment_card(card_id)
        if not card:
            bot.answer_callback_query(call.id, "کارت یافت نشد.", show_alert=True)
            return
        state_set(uid, "admin_card_edit_number", card_id=card_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"✏️ <b>ویرایش کارت</b>\n\n"
            f"شماره فعلی: <code>{esc(card['card_number'])}</code>\n\n"
            "شماره کارت جدید را ارسال کنید:",
            back_button(f"adm:gw:card:cards:cfg:{card_id}"))
        return

    # ── Fee / Bonus admin for all gateways ────────────────────────────────────
    _GW_NAMES_FEEBONUS = {
        "card":              "💳 کارت به کارت",
        "crypto":            "💎 ارز دیجیتال",
        "tetrapay":          "🏦 TetraPay",
        "swapwallet_crypto": "💎 SwapWallet",
        "tronpays_rial":     "💳 TronPays",
    }

    def _feebonus_text(gw):
        fee_on    = setting_get(f"gw_{gw}_fee_enabled",    "0") == "1"
        fee_type  = setting_get(f"gw_{gw}_fee_type",   "fixed")
        fee_val   = setting_get(f"gw_{gw}_fee_value",      "0")
        bonus_on  = setting_get(f"gw_{gw}_bonus_enabled",  "0") == "1"
        bonus_type= setting_get(f"gw_{gw}_bonus_type",  "fixed")
        bonus_val = setting_get(f"gw_{gw}_bonus_value",    "0")
        type_lbl  = lambda t: "درصد (%)" if t == "pct" else "مبلغ ثابت (تومان)"
        fee_txt   = (f"{'✅' if fee_on else '❌'} کارمزد: {type_lbl(fee_type)} — مقدار: {fee_val}")
        bonus_txt = (f"{'✅' if bonus_on else '❌'} بونس: {type_lbl(bonus_type)} — مقدار: {bonus_val}")
        return f"{fee_txt}\n{bonus_txt}"

    def _feebonus_kb(gw):
        kb2 = types.InlineKeyboardMarkup()
        fee_on   = setting_get(f"gw_{gw}_fee_enabled",   "0") == "1"
        bonus_on = setting_get(f"gw_{gw}_bonus_enabled", "0") == "1"
        kb2.add(types.InlineKeyboardButton(
            f"💸 کارمزد: {'✅ فعال' if fee_on else '❌ غیرفعال'}",
            callback_data=f"adm:gw:{gw}:fee"
        ))
        kb2.add(types.InlineKeyboardButton(
            f"🎁 بونس: {'✅ فعال' if bonus_on else '❌ غیرفعال'}",
            callback_data=f"adm:gw:{gw}:bonus"
        ))
        kb2.add(types.InlineKeyboardButton(
            "بازگشت", callback_data=f"adm:set:gw:{gw}",
            icon_custom_emoji_id="5253997076169115797"
        ))
        return kb2

    def _fee_setting_kb(gw):
        fee_on   = setting_get(f"gw_{gw}_fee_enabled",   "0") == "1"
        fee_type = setting_get(f"gw_{gw}_fee_type",   "fixed")
        kb2 = types.InlineKeyboardMarkup()
        kb2.add(types.InlineKeyboardButton(
            f"وضعیت: {'✅ فعال' if fee_on else '❌ غیرفعال'}",
            callback_data=f"adm:gw:{gw}:fee:toggle"
        ))
        kb2.row(
            types.InlineKeyboardButton(
                f"{'✅ ' if fee_type == 'fixed' else ''}مبلغ ثابت",
                callback_data=f"adm:gw:{gw}:fee:settype:fixed"
            ),
            types.InlineKeyboardButton(
                f"{'✅ ' if fee_type == 'pct' else ''}درصد",
                callback_data=f"adm:gw:{gw}:fee:settype:pct"
            ),
        )
        kb2.add(types.InlineKeyboardButton("✏️ تنظیم مقدار", callback_data=f"adm:gw:{gw}:fee:setval"))
        kb2.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:gw:{gw}:feebonus",
                                           icon_custom_emoji_id="5253997076169115797"))
        return kb2

    def _bonus_setting_kb(gw):
        bonus_on   = setting_get(f"gw_{gw}_bonus_enabled",   "0") == "1"
        bonus_type = setting_get(f"gw_{gw}_bonus_type",   "fixed")
        kb2 = types.InlineKeyboardMarkup()
        kb2.add(types.InlineKeyboardButton(
            f"وضعیت: {'✅ فعال' if bonus_on else '❌ غیرفعال'}",
            callback_data=f"adm:gw:{gw}:bonus:toggle"
        ))
        kb2.row(
            types.InlineKeyboardButton(
                f"{'✅ ' if bonus_type == 'fixed' else ''}مبلغ ثابت",
                callback_data=f"adm:gw:{gw}:bonus:settype:fixed"
            ),
            types.InlineKeyboardButton(
                f"{'✅ ' if bonus_type == 'pct' else ''}درصد",
                callback_data=f"adm:gw:{gw}:bonus:settype:pct"
            ),
        )
        kb2.add(types.InlineKeyboardButton("✏️ تنظیم مقدار", callback_data=f"adm:gw:{gw}:bonus:setval"))
        kb2.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:gw:{gw}:feebonus",
                                           icon_custom_emoji_id="5253997076169115797"))
        return kb2

    # feebonus entry for each gateway (adm:gw:<gw>:feebonus or adm:gw:card:feebonus)
    for _gw_fb in ("card", "crypto", "tetrapay", "swapwallet_crypto", "tronpays_rial"):
        if data == f"adm:gw:{_gw_fb}:feebonus":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            gw_lbl = _GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"🎁 <b>بونس و کارمزد — {gw_lbl}</b>\n\n"
                f"{_feebonus_text(_gw_fb)}\n\n"
                "کارمزد: مبلغ یا درصد اضافه به مبلغ فاکتور کاربر.\n"
                "بونس: مبلغ یا درصد به کیف پول کاربر پس از پرداخت موفق.",
                _feebonus_kb(_gw_fb))
            return
        if data == f"adm:gw:{_gw_fb}:fee":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            fee_val  = setting_get(f"gw_{_gw_fb}_fee_value", "0")
            fee_type = setting_get(f"gw_{_gw_fb}_fee_type",  "fixed")
            type_lbl = "درصد" if fee_type == "pct" else "تومان ثابت"
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"💸 <b>کارمزد — {_GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)}</b>\n\n"
                f"مقدار فعلی: <b>{fee_val}</b> {type_lbl}\n\n"
                "<i>کارمزد به مبلغ فاکتور کاربر اضافه می‌شود و مبلغ نهایی قابل پرداخت را تغییر می‌دهد.</i>",
                _fee_setting_kb(_gw_fb))
            return
        if data == f"adm:gw:{_gw_fb}:fee:toggle":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            cur = setting_get(f"gw_{_gw_fb}_fee_enabled", "0")
            setting_set(f"gw_{_gw_fb}_fee_enabled", "0" if cur == "1" else "1")
            bot.answer_callback_query(call.id, "تغییر یافت.")
            _fake_call(call, f"adm:gw:{_gw_fb}:fee")
            return
        if data.startswith(f"adm:gw:{_gw_fb}:fee:settype:"):
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            new_type = data.split(":")[-1]
            if new_type in ("fixed", "pct"):
                setting_set(f"gw_{_gw_fb}_fee_type", new_type)
                bot.answer_callback_query(call.id, "تغییر یافت.")
            _fake_call(call, f"adm:gw:{_gw_fb}:fee")
            return
        if data == f"adm:gw:{_gw_fb}:fee:setval":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            fee_type = setting_get(f"gw_{_gw_fb}_fee_type", "fixed")
            hint = "درصد (عدد بین ۱ تا ۱۰۰)" if fee_type == "pct" else "مبلغ به تومان (عدد مثبت)"
            state_set(uid, "admin_gw_set_fee_val", gw=_gw_fb)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"💸 <b>تنظیم کارمزد — {_GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)}</b>\n\n"
                f"نوع: {hint}\n\n"
                "مقدار را ارسال کنید:",
                back_button(f"adm:gw:{_gw_fb}:fee"))
            return
        if data == f"adm:gw:{_gw_fb}:bonus":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            bonus_val  = setting_get(f"gw_{_gw_fb}_bonus_value", "0")
            bonus_type = setting_get(f"gw_{_gw_fb}_bonus_type",  "fixed")
            type_lbl   = "درصد" if bonus_type == "pct" else "تومان ثابت"
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"🎁 <b>بونس — {_GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)}</b>\n\n"
                f"مقدار فعلی: <b>{bonus_val}</b> {type_lbl}\n\n"
                "<i>پس از پرداخت موفق از این درگاه، این مقدار به کیف پول کاربر اضافه می‌شود.</i>",
                _bonus_setting_kb(_gw_fb))
            return
        if data == f"adm:gw:{_gw_fb}:bonus:toggle":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            cur = setting_get(f"gw_{_gw_fb}_bonus_enabled", "0")
            setting_set(f"gw_{_gw_fb}_bonus_enabled", "0" if cur == "1" else "1")
            bot.answer_callback_query(call.id, "تغییر یافت.")
            _fake_call(call, f"adm:gw:{_gw_fb}:bonus")
            return
        if data.startswith(f"adm:gw:{_gw_fb}:bonus:settype:"):
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            new_type = data.split(":")[-1]
            if new_type in ("fixed", "pct"):
                setting_set(f"gw_{_gw_fb}_bonus_type", new_type)
                bot.answer_callback_query(call.id, "تغییر یافت.")
            _fake_call(call, f"adm:gw:{_gw_fb}:bonus")
            return
        if data == f"adm:gw:{_gw_fb}:bonus:setval":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
                return
            bonus_type = setting_get(f"gw_{_gw_fb}_bonus_type", "fixed")
            hint = "درصد (عدد بین ۱ تا ۱۰۰)" if bonus_type == "pct" else "مبلغ به تومان (عدد مثبت)"
            state_set(uid, "admin_gw_set_bonus_val", gw=_gw_fb)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"🎁 <b>تنظیم بونس — {_GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)}</b>\n\n"
                f"نوع: {hint}\n\n"
                "مقدار را ارسال کنید:",
                back_button(f"adm:gw:{_gw_fb}:bonus"))
            return

    if data == "adm:set:gw:crypto":
        enabled = setting_get("gw_crypto_enabled", "0")
        vis = setting_get("gw_crypto_visibility", "public")
        range_enabled = setting_get("gw_crypto_range_enabled", "0")
        enabled_label = "🟢 فعال" if enabled == "1" else "🔴 غیرفعال"
        vis_label = "👥 عمومی" if vis == "public" else "🔒 کاربران امن"
        range_label = "🟢 فعال" if range_enabled == "1" else "🔴 غیرفعال"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"وضعیت: {enabled_label}", callback_data="adm:gw:crypto:toggle"),
            types.InlineKeyboardButton(f"نمایش: {vis_label}", callback_data="adm:gw:crypto:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"📊 بازه پرداختی: {range_label}", callback_data="adm:gw:crypto:range"))
        kb.add(types.InlineKeyboardButton("🏷 نام نمایشی درگاه", callback_data="adm:gw:crypto:set_name"))
        kb.add(types.InlineKeyboardButton("🎁 بونس و کارمزد", callback_data="adm:gw:crypto:feebonus"))
        for coin_key, coin_label in CRYPTO_COINS:
            addr = setting_get(f"crypto_{coin_key}", "")
            status_icon = "✅" if addr else "❌"
            comment_on  = setting_get(f"crypto_{coin_key}_comment",    "0") == "1"
            randamt_on  = setting_get(f"crypto_{coin_key}_rand_amount", "0") == "1"
            comment_lbl = "کامنت: ✅" if comment_on else "کامنت: 🔴"
            randamt_lbl = "مبلغ رندم: ✅" if randamt_on else "مبلغ رندم: 🔴"
            kb.row(
                types.InlineKeyboardButton(f"{status_icon} {coin_label}", callback_data=f"adm:set:cw:{coin_key}"),
                types.InlineKeyboardButton(comment_lbl,  callback_data=f"adm:gw:cw:{coin_key}:comment"),
                types.InlineKeyboardButton(randamt_lbl, callback_data=f"adm:gw:cw:{coin_key}:randamt"),
            )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        display_name_crypto = setting_get("gw_crypto_display_name", "")
        name_display_crypto = display_name_crypto or "<i>پیش‌فرض: ارز دیجیتال</i>"
        text = (
            "💎 <b>درگاه ارز دیجیتال</b>\n\n"
            f"وضعیت: {enabled_label}\n"
            f"نمایش: {vis_label}\n"
            f"نام نمایشی: {name_display_crypto}\n\n"
            "ℹ️ <i>با فعال‌سازی <b>کامنت</b> یا <b>مبلغ رندم</b> برای هر ارز، "
            "هنگام نمایش صفحه پرداخت، کد کامنت تصادفی و/یا مبلغ ارزی با ارقام اعشاری رندم به کاربر نشان داده می‌شود.</i>\n\n"
            "برای ویرایش آدرس ولت روی نام ارز بزنید:"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:crypto:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="crypto")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_crypto_display_name", "")
        send_or_edit(call,
            f"🏷 <b>نام نمایشی درگاه ارز دیجیتال</b>\n\n"
            f"مقدار فعلی: <code>{esc(current or 'پیش‌فرض')}</code>\n\n"
            "نام دلخواه را ارسال کنید.\n"
            "برای بازگشت به پیش‌فرض، <code>-</code> ارسال کنید.",
            back_button("adm:set:gw:crypto"))
        return

    if data == "adm:gw:crypto:toggle":
        enabled = setting_get("gw_crypto_enabled", "0")
        setting_set("gw_crypto_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"درگاه کریپتو {'غیرفعال' if enabled == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:crypto")
        return

    if data == "adm:gw:crypto:vis":
        vis = setting_get("gw_crypto_visibility", "public")
        setting_set("gw_crypto_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"نمایش درگاه کریپتو به {'secure' if vis == 'public' else 'public'} تغییر کرد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:crypto")
        return

    if data == "adm:set:gw:tetrapay":
        enabled = setting_get("gw_tetrapay_enabled", "0")
        vis = setting_get("gw_tetrapay_visibility", "public")
        api_key = setting_get("tetrapay_api_key", "")
        mode_bot = setting_get("tetrapay_mode_bot", "1")
        mode_web = setting_get("tetrapay_mode_web", "1")
        enabled_label = "🟢 فعال" if enabled == "1" else "🔴 غیرفعال"
        vis_label = "👥 عمومی" if vis == "public" else "🔒 کاربران امن"
        bot_label = "🟢 فعال" if mode_bot == "1" else "🔴 غیرفعال"
        web_label = "🟢 فعال" if mode_web == "1" else "🔴 غیرفعال"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"وضعیت: {enabled_label}", callback_data="adm:gw:tetrapay:toggle"),
            types.InlineKeyboardButton(f"نمایش: {vis_label}", callback_data="adm:gw:tetrapay:vis"),
        )
        kb.row(
            types.InlineKeyboardButton(f"تلگرام: {bot_label}", callback_data="adm:gw:tetrapay:mode_bot"),
            types.InlineKeyboardButton(f"مرورگر: {web_label}", callback_data="adm:gw:tetrapay:mode_web"),
        )
        range_enabled_tp = setting_get("gw_tetrapay_range_enabled", "0")
        range_label_tp = "🟢 فعال" if range_enabled_tp == "1" else "🔴 غیرفعال"
        kb.add(types.InlineKeyboardButton(f"📊 بازه پرداختی: {range_label_tp}", callback_data="adm:gw:tetrapay:range"))
        kb.add(types.InlineKeyboardButton("🏷 نام نمایشی درگاه", callback_data="adm:gw:tetrapay:set_name"))
        kb.add(types.InlineKeyboardButton("🎁 بونس و کارمزد", callback_data="adm:gw:tetrapay:feebonus"))
        kb.add(types.InlineKeyboardButton("🔑 تنظیم کلید API", callback_data="adm:set:tetrapay_key"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("🌐 دریافت کلید API از سایت TetraPay", url="https://tetra98.com"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        if api_key:
            key_display = f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>"
        else:
            key_display = "❌ <b>ثبت نشده</b> — ابتدا از سایت TetraPay کلید API خود را دریافت کنید"
        display_name_tp = setting_get("gw_tetrapay_display_name", "")
        name_display_tp = display_name_tp or "<i>پیش‌فرض: درگاه کارت به کارت (TetraPay)</i>"
        text = (
            "💳 <b>درگاه کارت به کارت (TetraPay)</b>\n\n"
            f"وضعیت: {enabled_label}\n"
            f"نمایش: {vis_label}\n"
            f"نام نمایشی: {name_display_tp}\n\n"
            f"💳 پرداخت از تلگرام: {bot_label}\n"
            f"🌐 پرداخت از مرورگر: {web_label}\n\n"
            f"کلید API: {key_display}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:tetrapay:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="tetrapay")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_tetrapay_display_name", "")
        send_or_edit(call,
            f"🏷 <b>نام نمایشی درگاه TetraPay</b>\n\n"
            f"مقدار فعلی: <code>{esc(current or 'پیش‌فرض')}</code>\n\n"
            "نام دلخواه را ارسال کنید.\n"
            "برای بازگشت به پیش‌فرض، <code>-</code> ارسال کنید.",
            back_button("adm:set:gw:tetrapay"))
        return

    if data == "adm:gw:tetrapay:toggle":
        enabled = setting_get("gw_tetrapay_enabled", "0")
        setting_set("gw_tetrapay_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"درگاه تتراپی {'غیرفعال' if enabled == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:vis":
        vis = setting_get("gw_tetrapay_visibility", "public")
        setting_set("gw_tetrapay_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"نمایش درگاه تتراپی به {'secure' if vis == 'public' else 'public'} تغییر کرد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:mode_bot":
        cur = setting_get("tetrapay_mode_bot", "1")
        setting_set("tetrapay_mode_bot", "0" if cur == "1" else "1")
        log_admin_action(uid, f"حالت bot تتراپی {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:mode_web":
        cur = setting_get("tetrapay_mode_web", "1")
        setting_set("tetrapay_mode_web", "0" if cur == "1" else "1")
        log_admin_action(uid, f"حالت web تتراپی {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:set:tetrapay_key":
        state_set(uid, "admin_set_tetrapay_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔑 کلید API تتراپی را ارسال کنید:", back_button("adm:set:gw:tetrapay"))
        return

    if data == "adm:set:gw:swapwallet_crypto":
        from ..gateways.swapwallet_crypto import NETWORK_LABELS as SW_CRYPTO_LABELS
        enabled  = setting_get("gw_swapwallet_crypto_enabled", "0")
        vis      = setting_get("gw_swapwallet_crypto_visibility", "public")
        api_key  = setting_get("swapwallet_crypto_api_key", "")
        username = setting_get("swapwallet_crypto_username", "")
        enabled_label = "🟢 فعال" if enabled == "1" else "🔴 غیرفعال"
        vis_label     = "👥 عمومی" if vis == "public" else "🔒 کاربران امن"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"وضعیت: {enabled_label}", callback_data="adm:gw:swapwallet_crypto:toggle"),
            types.InlineKeyboardButton(f"نمایش: {vis_label}",    callback_data="adm:gw:swapwallet_crypto:vis"),
        )
        range_en = setting_get("gw_swapwallet_crypto_range_enabled", "0")
        range_label = "🟢 فعال" if range_en == "1" else "🔴 غیرفعال"
        kb.add(types.InlineKeyboardButton(f"📊 بازه پرداختی: {range_label}", callback_data="adm:gw:swapwallet_crypto:range"))
        kb.add(types.InlineKeyboardButton("🔑 تنظیم کلید API",        callback_data="adm:set:swapwallet_crypto_key"))
        kb.add(types.InlineKeyboardButton("👤 نام کاربری فروشگاه",     callback_data="adm:set:swapwallet_crypto_username"))
        kb.add(types.InlineKeyboardButton("🏷 نام نمایشی درگاه", callback_data="adm:gw:swapwallet_crypto:set_name"))
        kb.add(types.InlineKeyboardButton("🎁 بونس و کارمزد", callback_data="adm:gw:swapwallet_crypto:feebonus"))
        kb.add(types.InlineKeyboardButton("💎 ارزهای فعال", callback_data="adm:set:swc_currencies"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("🌐 دریافت کلید API از سواپ ولت", url="https://swapwallet.app"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        key_display = f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>" if api_key else "❌ <b>ثبت نشده — الزامی</b>"
        user_status = "✅ ثبت شده" if username else "❌ ثبت نشده"
        display_name_sw = setting_get("gw_swapwallet_crypto_display_name", "")
        name_display_sw = display_name_sw or "<i>پیش‌فرض: درگاه کارت به کارت و ارز دیجیتال (SwapWallet)</i>"
        text = (
            "💳 <b>درگاه کارت به کارت و ارز دیجیتال (SwapWallet)</b>\n\n"
            f"وضعیت: {enabled_label}\n"
            f"نمایش: {vis_label}\n"
            f"نام نمایشی: {name_display_sw}\n\n"
            f"👤 نام کاربری Application: <code>{esc(username or 'ثبت نشده')}</code> {user_status}\n"
            f"🔑 کلید API: {key_display}\n\n"
            "📖 <b>شبکه‌های پشتیبانی:</b> TRON · TON · BSC\n\n"
            "📖 <b>مراحل راه‌اندازی:</b>\n"
            "1️⃣ در مینی‌اپ سواپ‌ولت استارت بزنید:\n"
            "   👉 @SwapWalletBot\n"
            "2️⃣ در پنل بیزنس با تلگرام لاگین کنید:\n"
            "   👉 business.swapwallet.app\n"
            "3️⃣ یک فروشگاه جدید بسازید\n"
            "4️⃣ <b>نام فروشگاه</b> رو به عنوان نام کاربری اینجا وارد کنید\n"
            "5️⃣ از تب <b>پروفایل ← کلید API</b> کلید بگیرید و وارد کنید"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:swapwallet_crypto:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="swapwallet_crypto")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_swapwallet_crypto_display_name", "")
        send_or_edit(call,
            f"🏷 <b>نام نمایشی درگاه SwapWallet</b>\n\n"
            f"مقدار فعلی: <code>{esc(current or 'پیش‌فرض')}</code>\n\n"
            "نام دلخواه را ارسال کنید.\n"
            "برای بازگشت به پیش‌فرض، <code>-</code> ارسال کنید.",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:gw:swapwallet_crypto:toggle":
        enabled = setting_get("gw_swapwallet_crypto_enabled", "0")
        setting_set("gw_swapwallet_crypto_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"درگاه سواپ‌ولت کریپتو {'غیرفعال' if enabled == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:swapwallet_crypto")
        return

    if data == "adm:gw:swapwallet_crypto:vis":
        vis = setting_get("gw_swapwallet_crypto_visibility", "public")
        setting_set("gw_swapwallet_crypto_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"نمایش درگاه سواپ‌ولت کریپتو به {'secure' if vis == 'public' else 'public'} تغییر کرد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:swapwallet_crypto")
        return

    if data == "adm:set:swapwallet_crypto_key":
        state_set(uid, "admin_set_swapwallet_crypto_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔑 <b>کلید API (SwapWallet کریپتو) را ارسال کنید</b>\n\n"
            "فرمت: <code>apikey-xxx...</code>\n\n"
            "📍 برای دریافت:\n"
            "اپ سواپ‌ولت ← پروفایل ← <b>کلید API</b>",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:set:swapwallet_crypto_username":
        state_set(uid, "admin_set_swapwallet_crypto_username")
        bot.answer_callback_query(call.id)
        current = setting_get("swapwallet_crypto_username", "")
        send_or_edit(call,
            f"👤 <b>نام کاربری فروشگاه (SwapWallet کریپتو) را ارسال کنید</b>\n\n"
            f"این همان <b>نام فروشگاه</b> شما در پنل بیزنس است.\n"
            f"مقدار فعلی: <code>{esc(current or 'ثبت نشده')}</code>",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:set:gw:tronpays_rial":
        enabled = setting_get("gw_tronpays_rial_enabled", "0")
        vis     = setting_get("gw_tronpays_rial_visibility", "public")
        api_key = setting_get("tronpays_rial_api_key", "")
        enabled_label = "🟢 فعال" if enabled == "1" else "🔴 غیرفعال"
        vis_label     = "👥 عمومی" if vis == "public" else "🔒 کاربران امن"
        range_en      = setting_get("gw_tronpays_rial_range_enabled", "0")
        range_label   = "🟢 فعال" if range_en == "1" else "🔴 غیرفعال"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"وضعیت: {enabled_label}", callback_data="adm:gw:tronpays_rial:toggle"),
            types.InlineKeyboardButton(f"نمایش: {vis_label}",     callback_data="adm:gw:tronpays_rial:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"📊 بازه پرداختی: {range_label}", callback_data="adm:gw:tronpays_rial:range"))
        kb.add(types.InlineKeyboardButton("🔑 تنظیم کلید API", callback_data="adm:set:tronpays_rial_key"))
        kb.add(types.InlineKeyboardButton("🔗 تنظیم Callback URL", callback_data="adm:set:tronpays_rial_cb_url"))
        kb.add(types.InlineKeyboardButton("🏷 نام نمایشی درگاه", callback_data="adm:gw:tronpays_rial:set_name"))
        kb.add(types.InlineKeyboardButton("🎁 بونس و کارمزد", callback_data="adm:gw:tronpays_rial:feebonus"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("🤖 دریافت API Key از @TronPaysBot", url="https://t.me/TronPaysBot"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        key_display = (f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>"
                       if api_key else "❌ <b>ثبت نشده</b> — ابتدا از ربات @TronPaysBot کلید API دریافت کنید")
        cb_url = setting_get("tronpays_rial_callback_url", "").strip() or "https://example.com/"
        display_name_tp_rial = setting_get("gw_tronpays_rial_display_name", "")
        name_display_tp_rial = display_name_tp_rial or "<i>پیش‌فرض: درگاه کارت به کارت (TronPay)</i>"
        text = (
            "💳 <b>درگاه کارت به کارت (TronPay)</b>\n\n"
            f"وضعیت: {enabled_label}\n"
            f"نمایش: {vis_label}\n"
            f"نام نمایشی: {name_display_tp_rial}\n\n"
            f"🔑 کلید API: {key_display}\n"
            f"🔗 Callback URL: <code>{esc(cb_url)}</code>\n\n"
            "📋 <b>راهنمای دریافت API Key:</b>\n"
            "۱. ربات @TronPaysBot را استارت کنید\n"
            "۲. ثبت‌نام و احراز هویت را تکمیل کنید\n"
            "۳. کلید API را از پروفایل دریافت کنید"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:tronpays_rial:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="tronpays_rial")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_tronpays_rial_display_name", "")
        send_or_edit(call,
            f"🏷 <b>نام نمایشی درگاه TronPay</b>\n\n"
            f"مقدار فعلی: <code>{esc(current or 'پیش‌فرض')}</code>\n\n"
            "نام دلخواه را ارسال کنید.\n"
            "برای بازگشت به پیش‌فرض، <code>-</code> ارسال کنید.",
            back_button("adm:set:gw:tronpays_rial"))
        return

    if data == "adm:gw:tronpays_rial:toggle":
        enabled = setting_get("gw_tronpays_rial_enabled", "0")
        setting_set("gw_tronpays_rial_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"درگاه ترون‌پیز ریالی {'غیرفعال' if enabled == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:tronpays_rial")
        return

    if data == "adm:gw:tronpays_rial:vis":
        vis = setting_get("gw_tronpays_rial_visibility", "public")
        setting_set("gw_tronpays_rial_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"نمایش درگاه ترون‌پیز ریالی به {'secure' if vis == 'public' else 'public'} تغییر کرد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:gw:tronpays_rial")
        return

    if data == "adm:set:tronpays_rial_key":
        state_set(uid, "admin_set_tronpays_rial_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔑 کلید API TronPays را ارسال کنید:", back_button("adm:set:gw:tronpays_rial"))
        return

    if data == "adm:set:tronpays_rial_cb_url":
        state_set(uid, "admin_set_tronpays_rial_cb_url")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🔗 <b>Callback URL درگاه TronPays</b>\n\n"
            "یک URL معتبر ارسال کنید (مثلاً آدرس سایت یا وبهوک شما).\n"
            "اگر ندارید، <code>https://example.com/</code> را بفرستید.",
            back_button("adm:set:gw:tronpays_rial"))
        return

    _GW_RANGE_LABELS = {"card": "💳 کارت به کارت", "crypto": "💎 ارز دیجیتال", "tetrapay": "🏦 TetraPay", "swapwallet": "💎 SwapWallet", "swapwallet_crypto": "💎 SwapWallet کریپتو", "tronpays_rial": "💳 TronPays"}

    if data.startswith("adm:gw:") and data.endswith(":range"):
        gw_name = data.split(":")[2]
        gw_label = _GW_RANGE_LABELS.get(gw_name, gw_name)
        range_enabled = setting_get(f"gw_{gw_name}_range_enabled", "0")
        range_min = setting_get(f"gw_{gw_name}_range_min", "")
        range_max = setting_get(f"gw_{gw_name}_range_max", "")
        enabled_label = "🟢 فعال" if range_enabled == "1" else "🔴 غیرفعال"
        min_label = fmt_price(int(range_min)) + " تومان" if range_min else "بدون حداقل"
        max_label = fmt_price(int(range_max)) + " تومان" if range_max else "بدون حداکثر"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"وضعیت بازه: {enabled_label}", callback_data=f"adm:gw:{gw_name}:range:toggle"))
        kb.add(types.InlineKeyboardButton("✏️ تنظیم بازه", callback_data=f"adm:gw:{gw_name}:range:set"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:set:gw:{gw_name}", icon_custom_emoji_id="5253997076169115797"))
        text = (
            f"📊 <b>بازه پرداختی — {gw_label}</b>\n\n"
            f"وضعیت: {enabled_label}\n"
            f"حداقل مبلغ: {min_label}\n"
            f"حداکثر مبلغ: {max_label}\n\n"
            "⚠️ اگر بازه فعال باشد، این درگاه فقط برای مبالغ داخل بازه نمایش داده می‌شود."
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:gw:") and data.endswith(":range:toggle"):
        gw_name = data.split(":")[2]
        cur = setting_get(f"gw_{gw_name}_range_enabled", "0")
        setting_set(f"gw_{gw_name}_range_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"بازه مبلغ درگاه {gw_name} {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, f"adm:gw:{gw_name}:range")
        return

    if data.startswith("adm:gw:") and data.endswith(":range:set"):
        gw_name = data.split(":")[2]
        state_set(uid, "admin_gw_range_min", gw=gw_name)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "📊 <b>حداقل مبلغ</b> (تومان) را وارد کنید.\n\n"
            "برای <b>بدون حداقل</b>، عدد <code>0</code> یا <code>-</code> ارسال کنید:",
            back_button(f"adm:gw:{gw_name}:range"))
        return

    if data == "adm:set:payment":
        _fake_call(call, "adm:set:gw:card")
        bot.answer_callback_query(call.id)
        return

    if data == "adm:set:cardvis":
        _fake_call(call, "adm:gw:card:vis")
        bot.answer_callback_query(call.id)
        return

    if data == "adm:set:card":
        state_set(uid, "admin_set_card")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "💳 شماره کارت را ارسال کنید:", back_button("adm:set:gw:card"))
        return

    if data == "adm:set:bank":
        state_set(uid, "admin_set_bank")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🏦 نام بانک را ارسال کنید:", back_button("adm:set:gw:card"))
        return

    if data == "adm:set:owner":
        state_set(uid, "admin_set_owner")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "👤 نام و نام خانوادگی صاحب کارت را ارسال کنید:", back_button("adm:set:gw:card"))
        return

    if data == "adm:set:crypto":
        _fake_call(call, "adm:set:gw:crypto")
        bot.answer_callback_query(call.id)
        return

    if data.startswith("adm:set:cw:"):
        coin_key   = data.split(":")[3]
        coin_label = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
        state_set(uid, "admin_set_crypto_wallet", coin_key=coin_key)
        bot.answer_callback_query(call.id)
        current    = setting_get(f"crypto_{coin_key}", "")
        send_or_edit(
            call,
            f"💎 آدرس ولت <b>{coin_label}</b> را وارد کنید.\n"
            f"آدرس فعلی: <code>{esc(current or 'ثبت نشده')}</code>\n\n"
            "برای حذف، عدد <code>-</code> بفرستید.",
            back_button("adm:set:gw:crypto")
        )
        return

    if data.startswith("adm:gw:cw:"):
        parts = data.split(":")
        if len(parts) == 5 and parts[4] in ("comment", "randamt"):
            coin_key    = parts[3]
            setting_key = (f"crypto_{coin_key}_comment" if parts[4] == "comment"
                           else f"crypto_{coin_key}_rand_amount")
            cur = setting_get(setting_key, "0")
            setting_set(setting_key, "0" if cur == "1" else "1")
            bot.answer_callback_query(call.id, "تغییر یافت.")
            _fake_call(call, "adm:set:gw:crypto")
            return

    if data == "adm:set:channel":
        current = setting_get("channel_id", "")
        state_set(uid, "admin_set_channel")
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"📢 <b>کانال قفل</b>\n\n"
            f"کانال فعلی: {esc(current or 'ثبت نشده')}\n\n"
            "@username کانال را وارد کنید\n"
            "برای غیرفعال کردن، <code>-</code> بفرستید\n\n"
            "⚠️ ربات باید ادمین کانال باشد",
            back_button("admin:settings")
        )
        return

    if data == "adm:bot_texts":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✏️ ویرایش متن استارت", callback_data="adm:set:start_text"))
        kb.add(types.InlineKeyboardButton("📜 قوانین خرید",        callback_data="adm:set:rules"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📝 <b>متن‌های ربات</b>\n\nیکی از موارد زیر را انتخاب کنید:", kb)
        return

    if data == "adm:set:start_text":
        current = setting_get("start_text", "")
        state_set(uid, "admin_set_start_text")
        bot.answer_callback_query(call.id)
        preview = esc(current[:200]) + "..." if len(current) > 200 else esc(current or "پیش‌فرض")
        send_or_edit(
            call,
            f"✏️ <b>ویرایش متن استارت</b>\n\n"
            f"متن فعلی:\n{preview}\n\n"
            "متن جدید را ارسال کنید. می‌توانید از تگ‌های HTML استفاده کنید.\n"
            "برای بازگشت به متن پیش‌فرض، <code>-</code> بفرستید.",
            back_button("adm:bot_texts")
        )
        return

    # ── Admin: Locked Channels Management ────────────────────────────────────
    if data == "adm:locked_channels":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, *_build_locked_channels_menu())
        return

    if data == "adm:lch:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_add_locked_channel")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "📢 <b>افزودن کانال قفل</b>\n\n"
            "آیدی کانال یا گروه را وارد کنید.\n"
            "مثال: <code>@channelname</code> یا <code>-100123456789</code>\n\n"
            "⚠️ ربات باید عضو/ادمین کانال باشد.",
            back_button("adm:locked_channels"))
        return

    if data.startswith("adm:lch:del:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        row_id = int(data.split(":")[3])
        remove_locked_channel_by_id(row_id)
        _invalidate_channel_cache()
        bot.answer_callback_query(call.id, "✅ کانال حذف شد.")
        send_or_edit(call, *_build_locked_channels_menu())
        return

    # ── Admin: SwapWallet active currencies ───────────────────────────────────
    if data == "adm:set:swc_currencies":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        from ..gateways.swapwallet_crypto import SWAPWALLET_CRYPTO_NETWORKS, NETWORK_LABELS as SW_NET_LABELS
        active_str = setting_get("swapwallet_active_currencies", "TRON,TON,BSC")
        active_set = {x.strip().upper() for x in active_str.split(",") if x.strip()}
        kb = types.InlineKeyboardMarkup()
        for net, _ in SWAPWALLET_CRYPTO_NETWORKS:
            check = "✅" if net in active_set else "❌"
            kb.add(types.InlineKeyboardButton(
                f"{check} {SW_NET_LABELS.get(net, net)}",
                callback_data=f"adm:swc:cur:{net}"
            ))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:set:gw:swapwallet_crypto", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "💎 <b>ارزهای فعال SwapWallet</b>\n\n"
            "شبکه‌هایی که کاربر می‌تواند برای پرداخت انتخاب کند:\n"
            "✅ = فعال  |  ❌ = غیرفعال", kb)
        return

    if data.startswith("adm:swc:cur:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        net_toggle = data.split(":")[3].upper()
        active_str = setting_get("swapwallet_active_currencies", "TRON,TON,BSC")
        active_set = {x.strip().upper() for x in active_str.split(",") if x.strip()}
        if net_toggle in active_set:
            active_set.discard(net_toggle)
        else:
            active_set.add(net_toggle)
        setting_set("swapwallet_active_currencies", ",".join(sorted(active_set)))
        bot.answer_callback_query(call.id, f"✅ {net_toggle} {'فعال' if net_toggle in active_set else 'غیرفعال'} شد.")
        # Reload same menu
        from ..gateways.swapwallet_crypto import SWAPWALLET_CRYPTO_NETWORKS, NETWORK_LABELS as SW_NET_LABELS
        active_str2 = setting_get("swapwallet_active_currencies", "TRON,TON,BSC")
        active_set2 = {x.strip().upper() for x in active_str2.split(",") if x.strip()}
        kb = types.InlineKeyboardMarkup()
        for net, _ in SWAPWALLET_CRYPTO_NETWORKS:
            check = "✅" if net in active_set2 else "❌"
            kb.add(types.InlineKeyboardButton(f"{check} {SW_NET_LABELS.get(net, net)}", callback_data=f"adm:swc:cur:{net}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:set:gw:swapwallet_crypto", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "💎 <b>ارزهای فعال SwapWallet</b>\n\n"
            "شبکه‌هایی که کاربر می‌تواند برای پرداخت انتخاب کند:\n"
            "✅ = فعال  |  ❌ = غیرفعال", kb)
        return

    # ── Admin: Free Test Settings ─────────────────────────────────────────────
    if data == "adm:set:freetest":
        ft_mode = setting_get("free_test_mode", "everyone")
        agent_limit = setting_get("agent_test_limit", "0")
        agent_period = setting_get("agent_test_period", "day")
        period_labels = {"day": "روز", "week": "هفته", "month": "ماه"}
        mode_labels = {"everyone": "🟢 همه کاربران", "agents_only": "🔵 فقط نمایندگان", "disabled": "🔴 غیرفعال"}
        mode_label = mode_labels.get(ft_mode, ft_mode)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"🔄 وضعیت: {mode_label}", callback_data="adm:ft:toggle"))
        kb.add(types.InlineKeyboardButton("🔄 ریست تست رایگان همه کاربران", callback_data="adm:ft:reset"))
        kb.add(types.InlineKeyboardButton(f"🤝 تعداد تست همکاران: {agent_limit} در {period_labels.get(agent_period, agent_period)}", callback_data="adm:ft:agent"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"🎁 <b>تنظیمات تست رایگان</b>\n\n"
            f"وضعیت: {mode_label}\n"
            f"تست همکاران: <b>{agent_limit}</b> عدد در {period_labels.get(agent_period, agent_period)}",
            kb
        )
        return

    if data == "adm:ft:toggle":
        ft_mode = setting_get("free_test_mode", "everyone")
        cycle = {"everyone": "agents_only", "agents_only": "disabled", "disabled": "everyone"}
        new_mode = cycle.get(ft_mode, "everyone")
        setting_set("free_test_mode", new_mode)
        mode_labels_fa = {"everyone": "همه کاربران", "agents_only": "فقط نمایندگان", "disabled": "غیرفعال"}
        log_admin_action(uid, f"تست رایگان به حالت '{mode_labels_fa.get(new_mode, new_mode)}' تغییر کرد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:freetest")
        return

    if data == "adm:ft:reset":
        reset_all_free_tests()
        bot.answer_callback_query(call.id, "✅ تست رایگان همه کاربران ریست شد.", show_alert=True)
        _fake_call(call, "adm:set:freetest")
        return

    if data == "adm:ft:agent":
        state_set(uid, "admin_set_agent_test_limit")
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            "🤝 <b>تعداد تست همکاران</b>\n\n"
            "تعداد تست رایگان همکاران را وارد کنید.\n"
            "فرمت: <code>تعداد بازه</code>\n\n"
            "مثال:\n"
            "<code>5 day</code> → ۵ تست در روز\n"
            "<code>10 week</code> → ۱۰ تست در هفته\n"
            "<code>20 month</code> → ۲۰ تست در ماه\n\n"
            "برای غیرفعال کردن محدودیت، <code>0</code> بفرستید.",
            back_button("adm:set:freetest")
        )
        return

    # ── Admin: Phone Collection Settings ─────────────────────────────────────
    if data == "adm:set:phone":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        phone_mode = setting_get("phone_mode", "disabled")
        iran_only  = setting_get("phone_iran_only", "0")
        mode_labels = {
            "disabled":     "🔴 غیرفعال",
            "everyone":     "🟢 همه کاربران",
            "agents_only":  "🔵 فقط نمایندگان",
            "trusted_only": "🟡 کاربران مطمئن",
            "card_only":    "🟠 هنگام پرداخت کارت",
        }
        mode_cycle = {
            "disabled":     "everyone",
            "everyone":     "agents_only",
            "agents_only":  "trusted_only",
            "trusted_only": "card_only",
            "card_only":    "disabled",
        }
        mode_label = mode_labels.get(phone_mode, phone_mode)
        iran_label = "🟢 فعال (فقط ایرانی)" if iran_only == "1" else "🔴 غیرفعال (هر شماره)"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"🔄 حالت جمع‌آوری: {mode_label}", callback_data="adm:phone:toggle_mode"))
        kb.add(types.InlineKeyboardButton(f"🇮🇷 اعتبارسنجی ایرانی: {iran_label}", callback_data="adm:phone:toggle_iran"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📱 <b>تنظیمات جمع‌آوری شماره تلفن</b>\n\n"
            f"حالت: {mode_label}\n"
            f"اعتبارسنجی ایران: {iran_label}\n\n"
            "حالت‌های جمع‌آوری:\n"
            "• <b>غیرفعال</b> — شماره جمع‌آوری نمی‌شود\n"
            "• <b>همه کاربران</b> — همه باید شماره بدهند\n"
            "• <b>فقط نمایندگان</b> — فقط نمایندگان شماره می‌دهند\n"
            "• <b>کاربران مطمئن</b> — فقط کاربران با وضعیت «امن»\n"
            "• <b>هنگام پرداخت کارت</b> — قبل از پرداخت کارت به کارت",
            kb)
        return

    if data == "adm:phone:toggle_mode":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        phone_mode = setting_get("phone_mode", "disabled")
        mode_cycle = {
            "disabled":     "everyone",
            "everyone":     "agents_only",
            "agents_only":  "trusted_only",
            "trusted_only": "card_only",
            "card_only":    "disabled",
        }
        new_mode = mode_cycle.get(phone_mode, "disabled")
        setting_set("phone_mode", new_mode)
        log_admin_action(uid, f"حالت جمع‌آوری شماره تلفن به '{new_mode}' تغییر کرد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:phone")
        return

    if data == "adm:phone:toggle_iran":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("phone_iran_only", "0")
        new = "0" if cur == "1" else "1"
        setting_set("phone_iran_only", new)
        log_admin_action(uid, f"اعتبارسنجی شماره ایرانی {'فعال' if new == '1' else 'غیرفعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:phone")
        return

    # ── Admin: Purchase Rules ─────────────────────────────────────────────────
    if data == "adm:set:rules":
        enabled = setting_get("purchase_rules_enabled", "0")
        kb = types.InlineKeyboardMarkup()
        toggle_label = "🔴 غیرفعال کردن" if enabled == "1" else "🟢 فعال کردن"
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:rules:toggle"))
        kb.add(types.InlineKeyboardButton("✏️ ویرایش متن قوانین", callback_data="adm:rules:edit"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:bot_texts", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"📜 <b>قوانین خرید</b>\n\n"
            f"وضعیت: {'🟢 فعال' if enabled == '1' else '🔴 غیرفعال'}\n\n"
            "وقتی فعال باشد، کاربر قبل از اولین خرید باید قوانین را بپذیرد.", kb)
        return

    if data == "adm:rules:toggle":
        enabled = setting_get("purchase_rules_enabled", "0")
        setting_set("purchase_rules_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"قوانین خرید {'غیرفعال' if enabled == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "adm:set:rules")
        return

    if data == "adm:rules:edit":
        state_set(uid, "admin_edit_rules_text")
        bot.answer_callback_query(call.id)
        current_text = setting_get("purchase_rules_text", "")
        preview = f"\n\n📝 متن فعلی:\n{esc(current_text[:200])}..." if len(current_text) > 200 else (f"\n\n📝 متن فعلی:\n{esc(current_text)}" if current_text else "")
        send_or_edit(call,
            f"✏️ <b>ویرایش متن قوانین خرید</b>{preview}\n\n"
            "متن جدید قوانین خرید را ارسال کنید:",
            back_button("adm:set:rules"))
        return

    if data == "buy:accept_rules":
        # User accepted rules, mark and proceed to buy
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"rules_accepted_{uid}", "1")
            )
        bot.answer_callback_query(call.id)
        # Delete the rules message and send buy menu as a fresh message
        # (editing a tg-emoji message into a different message can silently fail)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        # Now dispatch buy:start_real via a fresh message-based call
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid, "🔴 <b>فروشگاه موقتاً تعطیل است.</b>\n\nلطفاً بعداً مراجعه کنید.",
                             parse_mode="HTML", reply_markup=kb)
            return
        stock_only = setting_get("preorder_mode", "0") == "1"
        items = get_active_types()
        kb = types.InlineKeyboardMarkup()
        has_any = False
        for item in items:
            packs = [p for p in get_packages(type_id=item['id']) if p['price'] > 0 and _pkg_has_stock(p, stock_only)]
            if packs:
                kb.add(types.InlineKeyboardButton(f"🧩 {item['name']}", callback_data=f"buy:t:{item['id']}"))
                has_any = True
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        if not has_any:
            bot.send_message(uid, "📭 در حال حاضر بسته‌ای برای فروش موجود نیست.",
                             parse_mode="HTML", reply_markup=kb)
        else:
            bot.send_message(uid, "🛒 <b>خرید کانفیگ جدید</b>\n\nنوع مورد نظر را انتخاب کنید:",
                             parse_mode="HTML", reply_markup=kb)
        return

    # ── Admin: Pinned Messages ─────────────────────────────────────────────────
    if data == "adm:pin":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        pins = get_all_pinned_messages()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ افزودن پیام پین", callback_data="adm:pin:add"))
        for p in pins:
            preview = (p["text"] or "")[:30].replace("\n", " ")
            kb.row(
                types.InlineKeyboardButton(f"📌 {preview}", callback_data="noop"),
                types.InlineKeyboardButton("✏️", callback_data=f"adm:pin:edit:{p['id']}"),
                types.InlineKeyboardButton("🗑", callback_data=f"adm:pin:del:{p['id']}"),
            )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        count_text = f"{len(pins)} پیام" if pins else "هیچ پیامی ثبت نشده"
        send_or_edit(call, f"📌 <b>پیام‌های پین شده</b>\n\n{count_text}", kb)
        return

    if data == "adm:pin:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_pin_add")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📌 <b>افزودن پیام پین</b>\n\nمتن پیام را ارسال کنید:", back_button("adm:pin"))
        return

    if data.startswith("adm:pin:del:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        pin_id = int(data.split(":")[3])
        # Get pin text before deleting for log
        _pin_row = get_pinned_message(pin_id)
        _pin_text_preview = ""
        if _pin_row:
            _pin_text_preview = (_pin_row["text"] or "")[:200].strip()
        # Unpin and delete sent messages from all user chats
        sends = get_pinned_sends(pin_id)
        removed_count = 0
        for s in sends:
            try:
                bot.unpin_chat_message(s["user_id"], s["message_id"])
            except Exception:
                pass
            try:
                bot.delete_message(s["user_id"], s["message_id"])
                removed_count += 1
            except Exception:
                pass
        delete_pinned_sends(pin_id)
        delete_pinned_message(pin_id)
        log_admin_action(uid, f"پیام پین #{pin_id} حذف شد")
        bot.answer_callback_query(call.id, "🗑 پیام حذف و آنپین شد.")
        send_to_topic("broadcast_report",
            f"🗑 <b>حذف پیام پین</b>\n\n"
            f"👤 حذف‌کننده: <code>{uid}</code>\n"
            f"🗑 حذف شده از: <b>{removed_count}</b> کاربر\n\n"
            f"📝 <b>متن پیام:</b>\n{esc(_pin_text_preview) if _pin_text_preview else '(خالی)'}")
        _fake_call(call, "adm:pin")
        return

    if data.startswith("adm:pin:edit:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        pin_id = int(data.split(":")[3])
        pin = get_pinned_message(pin_id)
        if not pin:
            bot.answer_callback_query(call.id, "پیام یافت نشد.", show_alert=True)
            return
        state_set(uid, "admin_pin_edit", pin_id=pin_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"✏️ <b>ویرایش پیام پین</b>\n\nمتن فعلی:\n<code>{esc(pin['text'])}</code>\n\nمتن جدید را ارسال کنید:",
            back_button("adm:pin"))
        return

    # ── Admin: Backup ─────────────────────────────────────────────────────────
    if data == "admin:backup":
        enabled  = setting_get("backup_enabled", "0")
        interval = setting_get("backup_interval", "24")
        target   = setting_get("backup_target_id", "")
        kb       = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💾 بکاپ دستی", callback_data="adm:bkp:manual"))
        kb.add(types.InlineKeyboardButton("📥 بازیابی بکاپ", callback_data="adm:bkp:restore"))
        toggle_label = "🔴 غیرفعال کردن بکاپ خودکار" if enabled == "1" else "🟢 فعال کردن بکاپ خودکار"
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:bkp:toggle"))
        kb.add(types.InlineKeyboardButton(f"⏰ زمان‌بندی: هر {interval} ساعت", callback_data="adm:bkp:interval"))
        kb.add(types.InlineKeyboardButton("📤 تنظیم مقصد", callback_data="adm:bkp:target"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"💾 <b>بکاپ</b>\n\n"
            f"بکاپ خودکار: {'🟢 فعال' if enabled == '1' else '🔴 غیرفعال'}\n"
            f"هر {interval} ساعت\n"
            f"مقصد: <code>{esc(target or 'ثبت نشده')}</code>",
            kb
        )
        return

    if data == "adm:bkp:manual":
        bot.answer_callback_query(call.id)
        _send_backup(uid)
        return

    if data == "adm:bkp:toggle":
        enabled = setting_get("backup_enabled", "0")
        setting_set("backup_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"بکاپ خودکار {'غیرفعال' if enabled == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _fake_call(call, "admin:backup")
        return

    if data == "adm:bkp:interval":
        state_set(uid, "admin_set_backup_interval")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "⏰ بازه بکاپ خودکار را به ساعت وارد کنید (مثال: 6، 12، 24):",
                     back_button("admin:backup"))
        return

    if data == "adm:bkp:target":
        state_set(uid, "admin_set_backup_target")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📤 آیدی عددی کاربر یا کانال برای دریافت بکاپ را وارد کنید:",
                     back_button("admin:backup"))
        return

    if data == "adm:bkp:restore":
        state_set(uid, "admin_restore_backup")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "📥 <b>بازیابی بکاپ</b>\n\n"
            "⚠️ <b>توجه:</b> با بازیابی بکاپ، دیتابیس فعلی ربات حذف و با فایل بکاپ جایگزین می‌شود.\n\n"
            "فایل بکاپ (<code>.db</code>) را ارسال کنید:",
            back_button("admin:backup"))
        return

    # ── Admin: Discount Codes ─────────────────────────────────────────────────
    if data == "admin:discounts":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _render_discount_admin_list(call, uid)
        return

    if data == "admin:vouchers":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _render_voucher_admin_list(call, uid)
        return

    if data == "admin:vch:toggle_global":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("vouchers_enabled", "1")
        setting_set("vouchers_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"سیستم کارت هدیه {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _render_voucher_admin_list(call, uid)
        return

    if data == "admin:vch:add":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_vch_add_name")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🎫 <b>افزودن کارت هدیه</b>\n\n"
            "مرحله ۱: یک <b>نام</b> برای این دسته کارت هدیه وارد کنید:\n"
            "<i>مثال: جشنواره نوروز</i>",
            back_button("admin:vouchers"))
        return

    if data == "admin:vch:gift_type:wallet":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        sd = state_data(uid)
        state_set(uid, "admin_vch_add_amount", vch_name=sd.get("vch_name", ""))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🎫 <b>افزودن کارت هدیه</b>\n\n"
            "مرحله ۳: مبلغ شارژ کیف پول را به <b>تومان</b> وارد کنید:",
            back_button("admin:vch:add"))
        return

    if data == "admin:vch:gift_type:config":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        sd = state_data(uid)
        state_set(uid, "admin_vch_pick_type", vch_name=sd.get("vch_name", ""))
        bot.answer_callback_query(call.id)
        types_list = get_active_types()
        kb = types.InlineKeyboardMarkup()
        for t in types_list:
            kb.add(types.InlineKeyboardButton(t["name"], callback_data=f"admin:vch:pick_type:{t['id']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:vch:add", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "🎫 <b>افزودن کارت هدیه – انتخاب نوع</b>\n\n"
            "نوع کانفیگ را انتخاب کنید:", kb)
        return

    if data.startswith("admin:vch:pick_type:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        type_id = int(data.split(":")[3])
        sd = state_data(uid)
        state_set(uid, "admin_vch_pick_pkg", vch_name=sd.get("vch_name", ""), type_id=type_id)
        bot.answer_callback_query(call.id)
        pkgs = [p for p in get_packages(type_id=type_id) if p.get("active", 1)]
        kb = types.InlineKeyboardMarkup()
        for p in pkgs:
            _sn = p['show_name'] if 'show_name' in p.keys() else 1
            label = (f"{p['name']} | " if _sn else "") + f"{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])}"
            kb.add(types.InlineKeyboardButton(label, callback_data=f"admin:vch:pick_pkg:{p['id']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:vch:gift_type:config", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "🎫 <b>افزودن کارت هدیه – انتخاب پکیج</b>\n\nپکیج مورد نظر را انتخاب کنید:", kb)
        return

    if data.startswith("admin:vch:pick_pkg:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        pkg_id = int(data.split(":")[3])
        sd = state_data(uid)
        state_set(uid, "admin_vch_add_count_config",
                  vch_name=sd.get("vch_name", ""), package_id=pkg_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🎫 <b>افزودن کارت هدیه</b>\n\n"
            "مرحله آخر: تعداد کدهای کارت هدیه را وارد کنید:\n"
            "<i>مثال: ۵۰</i>",
            back_button("admin:vouchers"))
        return

    if data.startswith("admin:vch:view:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _render_voucher_batch_detail(call, uid, batch_id)
        return

    if data.startswith("admin:vch:del:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        batch = get_voucher_batch(batch_id)
        if not batch:
            bot.answer_callback_query(call.id, "دسته یافت نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("🗑 بله، حذف شود", callback_data=f"admin:vch:del_confirm:{batch_id}"),
            types.InlineKeyboardButton("❌ لغو", callback_data=f"admin:vch:view:{batch_id}"),
        )
        send_or_edit(call,
            f"🗑 <b>حذف کارت هدیه</b>\n\n"
            f"آیا از حذف دسته «{esc(batch['name'])}» و تمام کدهای آن مطمئن هستید؟",
            kb)
        return

    if data.startswith("admin:vch:del_confirm:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        delete_voucher_batch(batch_id)
        log_admin_action(uid, f"دسته کارت هدیه #{batch_id} حذف شد")
        bot.answer_callback_query(call.id, "✅ دسته حذف شد.")
        _render_voucher_admin_list(call, uid)
        return

    # ── User: voucher redemption ──────────────────────────────────────────────
    if data == "voucher:redeem":
        if setting_get("vouchers_enabled", "1") != "1":
            bot.answer_callback_query(call.id, "⚠️ سیستم کارت هدیه در حال حاضر غیرفعال است.", show_alert=True)
            return
        state_set(uid, "await_voucher_code")
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "🎫✨ <b>ثبت کارت هدیه</b> ✨🎫\n\n"
            "🌟 از اینکه کارت هدیه‌ای دریافت کرده‌اید خوشحالیم!\n\n"
            "✍️ لطفاً کد کارت هدیه خود را وارد کنید تا هدیه‌تان فوری به حساب شما اضافه شود:",
            kb)
        return

    if data == "admin:disc:toggle_global":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        cur = setting_get("discount_codes_enabled", "0")
        setting_set("discount_codes_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"سیستم کد تخفیف {'غیرفعال' if cur == '1' else 'فعال'} شد")
        bot.answer_callback_query(call.id, "تغییر یافت.")
        _render_discount_admin_list(call, uid)
        return

    if data == "admin:disc:add":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        state_set(uid, "admin_discount_add_code")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🎟 <b>افزودن کد تخفیف</b>\n\n"
            "مرحله ۱/۵: متن کد تخفیف را وارد کنید:\n"
            "(حروف انگلیسی، اعداد، خط تیره — مثال: NEWUSER20)",
            back_button("admin:discounts"))
        return

    if data.startswith("admin:disc:add_type:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        disc_type = data.split(":")[3]
        sd = state_data(uid)
        state_set(uid, "admin_discount_add_value",
                  code=sd.get("code", ""), disc_type=disc_type)
        bot.answer_callback_query(call.id)
        if disc_type == "pct":
            send_or_edit(call,
                "🎟 <b>افزودن کد تخفیف</b>\n\n"
                "مرحله ۲/۵: مقدار تخفیف را به <b>درصد</b> وارد کنید (۱ تا ۱۰۰):",
                back_button("admin:disc:add"))
        else:
            send_or_edit(call,
                "🎟 <b>افزودن کد تخفیف</b>\n\n"
                "مرحله ۲/۵: مقدار تخفیف را به <b>تومان</b> وارد کنید:",
                back_button("admin:disc:add"))
        return

    if data.startswith("admin:disc:add_audience:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        audience = data.split(":")[3] if data.split(":")[3] in ("all", "public", "agents") else "all"
        sd = state_data(uid)
        state_set(uid, "admin_discount_add_scope",
                  code=sd.get("code", ""),
                  disc_type=sd.get("disc_type", "pct"),
                  discount_value=sd.get("discount_value", 0),
                  max_uses_total=sd.get("max_uses_total", 0),
                  max_uses_per_user=sd.get("max_uses_per_user", 0),
                  audience=audience)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🌐 همه پکیج‌ها", callback_data="admin:disc:scope:all"))
        kb.add(types.InlineKeyboardButton("🧩 فقط نوع‌های خاص", callback_data="admin:disc:scope:types"))
        kb.add(types.InlineKeyboardButton("📦 فقط پکیج‌های خاص", callback_data="admin:disc:scope:packages"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:discounts", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "🎟 <b>افزودن کد تخفیف</b>\n\n"
            "مرحله ۶/۶: محدوده استفاده از این کد را انتخاب کنید:\n\n"
            "🌐 <b>همه پکیج‌ها</b> — بدون محدودیت\n"
            "🧩 <b>نوع‌های خاص</b> — فقط برای نوع‌های انتخابی\n"
            "📦 <b>پکیج‌های خاص</b> — فقط برای پکیج‌های انتخابی",
            kb)
        return

    if data.startswith("admin:disc:scope:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        scope_val = data.split(":")[3] if len(data.split(":")) > 3 else "all"
        if scope_val not in ("all", "types", "packages"):
            scope_val = "all"
        sd = state_data(uid)
        if scope_val == "all":
            # Create code immediately with no scope restriction
            try:
                new_id = add_discount_code(
                    sd.get("code", ""),
                    sd.get("disc_type", "pct"),
                    int(sd.get("discount_value", 0) or 0),
                    int(sd.get("max_uses_total", 0) or 0),
                    int(sd.get("max_uses_per_user", 0) or 0),
                    audience=sd.get("audience", "all"),
                    scope_type="all",
                )
            except Exception:
                bot.answer_callback_query(call.id, "⚠️ این کد قبلاً ثبت شده است.", show_alert=True)
                return
            state_clear(uid)
            log_admin_action(uid, f"کد تخفیف جدید {sd.get('code', '')} ثبت شد (محدوده: همه)")
            bot.answer_callback_query(call.id, "✅ کد تخفیف ثبت شد.")
            _render_discount_admin_list(call, uid)
        else:
            # Show multi-select for types or packages
            state_set(uid, "admin_discount_scope_sel",
                      code=sd.get("code", ""),
                      disc_type=sd.get("disc_type", "pct"),
                      discount_value=sd.get("discount_value", 0),
                      max_uses_total=sd.get("max_uses_total", 0),
                      max_uses_per_user=sd.get("max_uses_per_user", 0),
                      audience=sd.get("audience", "all"),
                      scope_type=scope_val,
                      scope_selected="")
            bot.answer_callback_query(call.id)
            _render_discount_scope_selection(call, uid)
        return

    if data.startswith("admin:disc:stgl:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        item_id = int(parts[3])
        sd = state_data(uid)
        selected_str = sd.get("scope_selected", "") or ""
        selected = set(int(x) for x in selected_str.split(",") if x.strip())
        if item_id in selected:
            selected.discard(item_id)
        else:
            selected.add(item_id)
        state_set(uid, "admin_discount_scope_sel",
                  code=sd.get("code", ""),
                  disc_type=sd.get("disc_type", "pct"),
                  discount_value=sd.get("discount_value", 0),
                  max_uses_total=sd.get("max_uses_total", 0),
                  max_uses_per_user=sd.get("max_uses_per_user", 0),
                  audience=sd.get("audience", "all"),
                  scope_type=sd.get("scope_type", "all"),
                  scope_selected=",".join(str(x) for x in selected))
        bot.answer_callback_query(call.id)
        _render_discount_scope_selection(call, uid)
        return

    if data == "admin:disc:sconf":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        sd = state_data(uid)
        selected_str = sd.get("scope_selected", "") or ""
        selected_ids = [int(x) for x in selected_str.split(",") if x.strip()]
        if not selected_ids:
            bot.answer_callback_query(call.id, "⚠️ حداقل یک مورد را انتخاب کنید.", show_alert=True)
            return
        scope_type = sd.get("scope_type", "all")
        try:
            new_id = add_discount_code(
                sd.get("code", ""),
                sd.get("disc_type", "pct"),
                int(sd.get("discount_value", 0) or 0),
                int(sd.get("max_uses_total", 0) or 0),
                int(sd.get("max_uses_per_user", 0) or 0),
                audience=sd.get("audience", "all"),
                scope_type=scope_type,
            )
        except Exception:
            bot.answer_callback_query(call.id, "⚠️ این کد قبلاً ثبت شده است.", show_alert=True)
            return
        target_type = "type" if scope_type == "types" else "package"
        set_discount_code_targets(new_id, target_type, selected_ids)
        state_clear(uid)
        log_admin_action(uid, f"کد تخفیف جدید {sd.get('code', '')} ثبت شد (محدوده: {scope_type})")
        bot.answer_callback_query(call.id, "✅ کد تخفیف ثبت شد.")
        _render_discount_admin_list(call, uid)
        return

    if data.startswith("admin:disc:edit_scope:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        if not row:
            bot.answer_callback_query(call.id, "کد پیدا نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🌐 همه پکیج‌ها", callback_data=f"admin:disc:set_scope:{code_id}:all"))
        kb.add(types.InlineKeyboardButton("🧩 فقط نوع‌های خاص", callback_data=f"admin:disc:set_scope:{code_id}:types"))
        kb.add(types.InlineKeyboardButton("📦 فقط پکیج‌های خاص", callback_data=f"admin:disc:set_scope:{code_id}:packages"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"admin:disc:view:{code_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "📌 <b>ویرایش محدوده کد تخفیف</b>\n\nنوع محدوده را انتخاب کنید:", kb)
        return

    if data.startswith("admin:disc:set_scope:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        code_id   = int(parts[3])
        scope_val = parts[4] if len(parts) > 4 else "all"
        if scope_val not in ("all", "types", "packages"):
            scope_val = "all"
        if scope_val == "all":
            update_discount_code_field(code_id, "scope_type", "all")
            set_discount_code_targets(code_id, "type", [])
            set_discount_code_targets(code_id, "package", [])
            log_admin_action(uid, f"محدوده کد تخفیف #{code_id} به همه تغییر یافت")
            bot.answer_callback_query(call.id, "✅ محدوده به‌روز شد.")
            _render_discount_code_detail(call, uid, code_id)
        else:
            state_set(uid, "admin_discount_scope_edit",
                      edit_code_id=code_id,
                      scope_type=scope_val,
                      scope_selected="")
            bot.answer_callback_query(call.id)
            _render_discount_scope_selection(call, uid, edit_code_id=code_id)
        return

    if data.startswith("admin:disc:stgl_edit:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        item_id = int(parts[3])
        sd = state_data(uid)
        selected_str = sd.get("scope_selected", "") or ""
        selected = set(int(x) for x in selected_str.split(",") if x.strip())
        if item_id in selected:
            selected.discard(item_id)
        else:
            selected.add(item_id)
        state_set(uid, "admin_discount_scope_edit",
                  edit_code_id=sd.get("edit_code_id"),
                  scope_type=sd.get("scope_type", "all"),
                  scope_selected=",".join(str(x) for x in selected))
        bot.answer_callback_query(call.id)
        _render_discount_scope_selection(call, uid, edit_code_id=sd.get("edit_code_id"))
        return

    if data == "admin:disc:sconf_edit":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        sd = state_data(uid)
        selected_str = sd.get("scope_selected", "") or ""
        selected_ids = [int(x) for x in selected_str.split(",") if x.strip()]
        if not selected_ids:
            bot.answer_callback_query(call.id, "⚠️ حداقل یک مورد را انتخاب کنید.", show_alert=True)
            return
        code_id    = sd.get("edit_code_id")
        scope_type = sd.get("scope_type", "all")
        update_discount_code_field(code_id, "scope_type", scope_type)
        target_type = "type" if scope_type == "types" else "package"
        set_discount_code_targets(code_id, target_type, selected_ids)
        # Clear the other target type
        other = "package" if target_type == "type" else "type"
        set_discount_code_targets(code_id, other, [])
        state_clear(uid)
        log_admin_action(uid, f"محدوده کد تخفیف #{code_id} به‌روز شد")
        bot.answer_callback_query(call.id, "✅ محدوده به‌روز شد.")
        _render_discount_code_detail(call, uid, code_id)
        return

    if data.startswith("admin:disc:view:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _render_discount_code_detail(call, uid, code_id)
        return

    if data.startswith("admin:disc:toggle:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        toggle_discount_code(code_id)
        bot.answer_callback_query(call.id, "وضعیت تغییر یافت.")
        _render_discount_code_detail(call, uid, code_id)
        return

    if data.startswith("admin:disc:del:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        if not row:
            bot.answer_callback_query(call.id, "کد پیدا نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("🗑 بله، حذف کن", callback_data=f"admin:disc:del_confirm:{code_id}"),
            types.InlineKeyboardButton("❌ لغو", callback_data=f"admin:disc:view:{code_id}"),
        )
        send_or_edit(call,
            f"🗑 <b>حذف کد تخفیف</b>\n\n"
            f"آیا از حذف کد <code>{esc(row['code'])}</code> مطمئن هستید؟",
            kb)
        return

    if data.startswith("admin:disc:del_confirm:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        delete_discount_code(code_id)
        log_admin_action(uid, f"کد تخفیف #{code_id} حذف شد")
        bot.answer_callback_query(call.id, "✅ کد حذف شد.")
        _render_discount_admin_list(call, uid)
        return

    if data.startswith("admin:disc:edit_code:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_code", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>ویرایش کد تخفیف</b>\n\nمتن جدید کد تخفیف را وارد کنید:",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_val:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        type_fa = "درصد" if row and row["discount_type"] == "pct" else "تومان"
        state_set(uid, f"admin_discount_edit_val", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"✏️ <b>ویرایش مقدار تخفیف</b>\n\n"
            f"نوع تخفیف: {type_fa}\n\n"
            "مقدار جدید را وارد کنید:",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_total:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_total", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>ویرایش حداکثر استفاده کل</b>\n\n"
            "تعداد جدید را وارد کنید (۰ = نامحدود):",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_per:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_per", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>ویرایش حداکثر استفاده هر کاربر</b>\n\n"
            "تعداد جدید را وارد کنید (۰ = نامحدود):",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_audience:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        if not row:
            bot.answer_callback_query(call.id, "کد پیدا نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        current = row["audience"] if "audience" in row.keys() else "all"
        kb = types.InlineKeyboardMarkup()
        for aud_key, aud_label in [("all", "👥 همه"), ("public", "🙋 فقط عموم"), ("agents", "🤝 فقط نمایندگان")]:
            icon = "✅ " if current == aud_key else ""
            kb.add(types.InlineKeyboardButton(f"{icon}{aud_label}", callback_data=f"admin:disc:set_audience:{code_id}:{aud_key}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"admin:disc:view:{code_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"🎯 <b>ویرایش دسترسی کد تخفیف</b>\n\n"
            f"کد: <code>{esc(row['code'])}</code>\n\n"
            "این کد تخفیف برای چه کسانی قابل استفاده باشد؟",
            kb)
        return

    if data.startswith("admin:disc:set_audience:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        code_id = int(parts[3])
        audience = parts[4] if parts[4] in ("all", "public", "agents") else "all"
        update_discount_code_field(code_id, "audience", audience)
        audience_labels = {"all": "همه", "public": "فقط عموم", "agents": "فقط نمایندگان"}
        bot.answer_callback_query(call.id, f"✅ دسترسی به «{audience_labels.get(audience)}» تغییر یافت.")
        _render_discount_code_detail(call, uid, code_id)
        return

    # ── Admin: Payment approve/reject ─────────────────────────────────────────
    if data.startswith("adm:pay:ap:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "تراکنش یافت نشد.", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "این تراکنش قبلاً بررسی شده است.", show_alert=True)
            return
        text = (
            f"✅💬 <b>تأیید با توضیحات</b>\n\n"
            f"💰 مبلغ: <b>{fmt_price(payment['amount'])}</b> تومان\n"
            f"🆔 کاربر: <code>{payment['user_id']}</code>\n\n"
            f"📝 پیام تأیید برای کاربر را تایپ کنید و ارسال کنید:"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 انصراف", callback_data="nav:admin:panel"))
        state_set(uid, "admin_payment_approve_note", payment_id=payment_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:pay:apc:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "تراکنش یافت نشد.", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "این تراکنش قبلاً بررسی شده است.", show_alert=True)
            return
        # Answer immediately so Telegram stops showing spinner and won't retry
        bot.answer_callback_query(call.id, "⏳ در حال پردازش...")
        state_clear(uid)
        result = finish_card_payment_approval(payment_id, "واریزی شما تأیید شد.", approved=True)
        if not result:
            send_or_edit(call, "⚠️ این تراکنش قبلاً پردازش شده است.", kb_admin_panel(uid))
        else:
            send_or_edit(call, "✅ تراکنش با موفقیت تأیید شد.", kb_admin_panel(uid))
        return

    if data.startswith("adm:pay:rj:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "تراکنش یافت نشد.", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "این تراکنش قبلاً بررسی شده است.", show_alert=True)
            return
        text = (
            f"❌💬 <b>رد با توضیحات</b>\n\n"
            f"💰 مبلغ: <b>{fmt_price(payment['amount'])}</b> تومان\n"
            f"🆔 کاربر: <code>{payment['user_id']}</code>\n\n"
            f"📝 دلیل رد را تایپ کنید و ارسال کنید:"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "⛔ رسید فیک — محدود ۲۴ ساعت",
            callback_data=f"adm:pay:rjc:fake24:{payment_id}"))
        kb.add(types.InlineKeyboardButton(
            "🚫 رسید فیک — محدود همیشه",
            callback_data=f"adm:pay:rjc:fakeall:{payment_id}"))
        kb.add(types.InlineKeyboardButton("🔙 انصراف", callback_data="nav:admin:panel"))
        state_set(uid, "admin_payment_reject_note", payment_id=payment_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:pay:rjc:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts      = data.split(":")
        mode       = parts[3]             # plain | fake24 | fakeall
        payment_id = int(parts[4])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "تراکنش یافت نشد.", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "این تراکنش قبلاً بررسی شده است.", show_alert=True)
            return
        # Answer immediately so Telegram stops showing spinner and won't retry
        bot.answer_callback_query(call.id, "⏳ در حال پردازش...")
        state_clear(uid)
        finish_card_payment_approval(payment_id, "رسید شما رد شد.", approved=False)

        payer_id = payment["user_id"]

        if mode in ("fake24", "fakeall"):
            import time as _t
            if mode == "fake24":
                _until   = int(_t.time()) + 86400
                _dur_txt = "تا ۲۴ ساعت دیگر نمی‌توانید از ربات استفاده کنید."
            else:
                _until   = 0   # permanent
                _dur_txt = "برای همیشه نمی‌توانید از ربات استفاده کنید."

            set_user_restricted(payer_id, _until)
            log_admin_action(uid,
                f"رسید فیک | کاربر <code>{payer_id}</code> محدود شد | mode={mode}")

            # Build support line
            _sup_raw  = setting_get("support_username", "")
            _sup_link = setting_get("support_link", "")
            _sup_url  = safe_support_url(_sup_raw) or (_sup_link if _sup_link else None)
            _sup_line = (
                f"\n\n🎧 برای پیگیری رفع محدودیت به پشتیبانی پیام دهید:\n{_sup_url}"
                if _sup_url else
                "\n\n🎧 برای پیگیری رفع محدودیت با پشتیبانی در تماس باشید."
            )

            try:
                bot.send_message(
                    payer_id,
                    f"⛔ <b>حساب شما محدود شد</b>\n\n"
                    f"به دلیل ارسال رسید جعلی، حساب شما محدود شده است.\n"
                    f"🚫 {_dur_txt}"
                    f"{_sup_line}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        send_or_edit(call, "❌ تراکنش رد شد.", kb_admin_panel(uid))
        return

    # ── Admin: Pending receipts panel ─────────────────────────────────────────
    if data == "admin:pr" or data.startswith("admin:pr:list:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        try:
            page = int(data.split(":")[-1]) if data != "admin:pr" else 0
        except (ValueError, IndexError):
            page = 0
        bot.answer_callback_query(call.id)
        _render_pending_receipts_page(call, uid, page)
        return

    if data.startswith("admin:pr:det:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "تراکنش یافت نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        user_row    = get_user(payment["user_id"])
        package_row = get_package(payment["package_id"]) if payment["package_id"] else None
        kind_label  = {"wallet_charge": "شارژ کیف‌پول", "buy": "خرید کانفیگ", "renew": "تمدید کانفیگ"}.get(
            payment["kind"], payment["kind"]
        )
        pkg_text = ""
        if package_row:
            pkg_text = (
                f"\n🧩 نوع: {esc(package_row['type_name'])}"
                f"\n📦 پکیج: {esc(package_row['name'])}"
                f"\n🔋 حجم: {fmt_vol(package_row['volume_gb'])} | ⏰ {fmt_dur(package_row['duration_days'])}"
            )
        receipt_note = esc(payment["receipt_text"] or "—")
        uname = "@" + esc(user_row["username"]) if (user_row and user_row["username"]) else "—"
        _pay_dict = dict(payment)
        crypto_comment_line = ""
        if _pay_dict.get("crypto_comment"):
            crypto_comment_line = f"\n🔑 کد کامنت: <code>{esc(_pay_dict['crypto_comment'])}</code>"
        text = (
            f"📋 <b>جزئیات رسید #{payment_id}</b>\n\n"
            f"🧾 نوع: <b>{kind_label}</b>\n"
            f"👤 کاربر: {esc(user_row['full_name'] if user_row else '—')}\n"
            f"🆔 آیدی: <code>{payment['user_id']}</code>\n"
            f"📞 یوزرنیم: {uname}\n"
            f"💰 مبلغ: <b>{fmt_price(payment['amount'])}</b> تومان\n"
            f"💳 روش پرداخت: {esc(payment['payment_method'])}"
            f"{crypto_comment_line}"
            f"{pkg_text}\n\n"
            f"📝 توضیحات مشتری: {receipt_note}\n"
            f"🕐 ثبت شده: {payment['created_at']}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ تأیید", callback_data=f"admin:pr:ap:{payment_id}:{page}"),
            types.InlineKeyboardButton("❌ رد",    callback_data=f"admin:pr:rj:{payment_id}:{page}"),
        )
        kb.row(
            types.InlineKeyboardButton("✅💬 تأیید با توضیح", callback_data=f"adm:pay:ap:{payment_id}"),
            types.InlineKeyboardButton("❌💬 رد با توضیح",    callback_data=f"adm:pay:rj:{payment_id}"),
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=f"admin:pr:list:{page}"))
        file_id = payment["receipt_file_id"]
        if file_id:
            try:
                bot.send_photo(uid, file_id, caption="🖼 رسید کاربر")
            except Exception:
                try:
                    bot.send_document(uid, file_id, caption="📎 رسید کاربر")
                except Exception:
                    pass
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pr:ap:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "تراکنش یافت نشد.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این تراکنش قبلاً بررسی شده است.", show_alert=True)
            return
        # Answer immediately so Telegram stops showing spinner and won't retry
        bot.answer_callback_query(call.id, "⏳ در حال پردازش...")
        result = finish_card_payment_approval(payment_id, "واریزی شما تأیید شد.", approved=True)
        _render_pending_receipts_page(call, uid, page)
        return

    if data.startswith("admin:pr:rj:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "تراکنش یافت نشد.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این تراکنش قبلاً بررسی شده است.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "❌ رد بدون توضیح",
            callback_data=f"admin:pr:rjdo:plain:{payment_id}:{page}"))
        kb.add(types.InlineKeyboardButton(
            "⛔ رسید فیک — محدود ۲۴ ساعت",
            callback_data=f"admin:pr:rjdo:fake24:{payment_id}:{page}"))
        kb.add(types.InlineKeyboardButton(
            "🚫 رسید فیک — محدود همیشه",
            callback_data=f"admin:pr:rjdo:fakeall:{payment_id}:{page}"))
        kb.add(types.InlineKeyboardButton(
            "بازگشت", callback_data=f"admin:pr:det:{payment_id}:{page}",
            icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"❌ <b>رد رسید #{payment_id}</b>\n\nنوع رد کردن را انتخاب کنید:",
            kb)
        return

    if data.startswith("admin:pr:rjdo:"):
        # admin:pr:rjdo:{mode}:{payment_id}:{page}
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts      = data.split(":")
        mode       = parts[3]             # plain | fake24 | fakeall
        payment_id = int(parts[4])
        page       = int(parts[5]) if len(parts) > 5 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "تراکنش یافت نشد.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "این تراکنش قبلاً بررسی شده است.", show_alert=True)
            return

        # Answer immediately so Telegram stops showing spinner and won't retry
        bot.answer_callback_query(call.id, "⏳ در حال پردازش...")
        # Reject the payment
        finish_card_payment_approval(payment_id, "رسید شما رد شد.", approved=False)

        payer_id = payment["user_id"]

        if mode in ("fake24", "fakeall"):
            import time as _t
            if mode == "fake24":
                _until   = int(_t.time()) + 86400
                _dur_txt = "تا ۲۴ ساعت دیگر نمی‌توانید از ربات استفاده کنید."
            else:
                _until   = 0   # permanent
                _dur_txt = "برای همیشه نمی‌توانید از ربات استفاده کنید."

            set_user_restricted(payer_id, _until)
            log_admin_action(uid,
                f"رسید فیک | کاربر <code>{payer_id}</code> محدود شد | mode={mode}")

            # Build support line
            _sup_raw  = setting_get("support_username", "")
            _sup_link = setting_get("support_link", "")
            _sup_url  = safe_support_url(_sup_raw) or (_sup_link if _sup_link else None)
            _sup_line = (
                f"\n\n🎧 برای پیگیری رفع محدودیت به پشتیبانی پیام دهید:\n{_sup_url}"
                if _sup_url else
                "\n\n🎧 برای پیگیری رفع محدودیت با پشتیبانی در تماس باشید."
            )

            try:
                bot.send_message(
                    payer_id,
                    f"⛔ <b>حساب شما محدود شد</b>\n\n"
                    f"به دلیل ارسال رسید جعلی، حساب شما محدود شده است.\n"
                    f"🚫 {_dur_txt}"
                    f"{_sup_line}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        _render_pending_receipts_page(call, uid, page)
        return

    # adm:pnd:proto:{proto}:{pending_id}  →  ask single/bulk
    if data.startswith("adm:pnd:proto:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        proto      = parts[3]            # v2ray | ovpn | wg
        pending_id = int(parts[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت نشد یا قبلاً تکمیل شده است.", show_alert=True)
            return
        pkg = get_package(p_row["package_id"])
        # Save pending_id + proto in state so downstream flow can access it
        state_set(uid, "admin_cfg_proto_select",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        if proto == "v2ray":
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",    callback_data=f"adm:pnd:v2:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:pnd:v2:bulk:{pending_id}"))
        elif proto == "ovpn":
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",    callback_data=f"adm:pnd:ovpn:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}"))
        elif proto == "wg":
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",    callback_data=f"adm:pnd:wg:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:pnd:wg:bulk:{pending_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pending:addcfg:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, f"📝 روش ثبت کانفیگ را انتخاب کنید:", kb)
        return

    # adm:pnd:v2:single:{pending_id}  →  V2Ray single for pending order
    if data.startswith("adm:pnd:v2:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "v2_single_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  mode=1, pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس</b> را وارد کنید:",
            back_button(f"adm:pnd:proto:v2ray:{pending_id}"))
        return

    # adm:pnd:v2:bulk:{pending_id}  →  V2Ray bulk for pending order
    if data.startswith("adm:pnd:v2:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "v2_bulk_init",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("1️⃣ کانفیگ + ساب — تعداد کم",   callback_data=f"adm:pnd:v2bm:1:{pending_id}"))
        kb.add(types.InlineKeyboardButton("2️⃣ کانفیگ + ساب — تعداد زیاد", callback_data=f"adm:pnd:v2bm:2:{pending_id}"))
        kb.add(types.InlineKeyboardButton("3️⃣ کانفیگ تنها",               callback_data=f"adm:pnd:v2bm:3:{pending_id}"))
        kb.add(types.InlineKeyboardButton("4️⃣ ساب تنها",                  callback_data=f"adm:pnd:v2bm:4:{pending_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:proto:v2ray:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📋 <b>نوع ثبت دسته‌ای V2Ray</b> را انتخاب کنید:", kb)
        return

    # adm:pnd:v2bm:{mode}:{pending_id}  →  bulk mode selected for pending order
    if data.startswith("adm:pnd:v2bm:"):
        if not is_admin(uid): return
        parts = data.split(":")
        mode = int(parts[3]); pending_id = int(parts[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        s = state_data(uid)
        bot.answer_callback_query(call.id)
        if mode in (1, 2, 3):
            state_set(uid, "v2_bulk_pre",
                      package_id=p_row["package_id"],
                      type_id=pkg["type_id"] if pkg else 0,
                      mode=mode, pending_id=pending_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏭ بدون پیشوند", callback_data=f"adm:pnd:v2bpfx:skip:{pending_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:v2:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "✂️ <b>پیشوند حذفی از نام کانفیگ</b>\n\n"
                "اگر ابتدای نام کانفیگ‌ها متن اضافه‌ای دارد وارد کنید، در غیر اینصورت «بدون پیشوند» بزنید.", kb)
        else:  # mode 4: sub only
            state_set(uid, "v2_bulk_data",
                      package_id=p_row["package_id"],
                      type_id=pkg["type_id"] if pkg else 0,
                      mode=4, prefix="", suffix="", pending_id=pending_id)
            send_or_edit(call, _v2_bulk_data_prompt(4), back_button(f"adm:pnd:v2:bulk:{pending_id}"))
        return

    # adm:pnd:v2bpfx:skip:{pending_id}  →  skip prefix for pending bulk
    if data.startswith("adm:pnd:v2bpfx:skip:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        s = state_data(uid)
        state_set(uid, "v2_bulk_suf",
                  package_id=s["package_id"], type_id=s["type_id"],
                  mode=s["mode"], prefix="", pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⏭ بدون پسوند", callback_data=f"adm:pnd:v2bsfx:skip:{pending_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:v2:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "✂️ <b>پسوند حذفی از نام کانفیگ</b>\n\n"
            "اگر انتهای نام‌ها متن اضافه‌ای دارد وارد کنید، در غیر اینصورت «بدون پسوند» بزنید.", kb)
        return

    # adm:pnd:v2bsfx:skip:{pending_id}  →  skip suffix for pending bulk
    if data.startswith("adm:pnd:v2bsfx:skip:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        s = state_data(uid)
        mode = s.get("mode", 1)
        state_set(uid, "v2_bulk_data",
                  package_id=s["package_id"], type_id=s["type_id"],
                  mode=mode, prefix=s.get("prefix", ""), suffix="", pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, _v2_bulk_data_prompt(mode), back_button(f"adm:pnd:v2:bulk:{pending_id}"))
        return

    # adm:pnd:ovpn:single:{pending_id}  →  OpenVPN single for pending order
    if data.startswith("adm:pnd:ovpn:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        state_set(uid, "ovpn_single_file",
                  package_id=p_row["package_id"], pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:proto:ovpn:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📎 <b>ثبت تکی OpenVPN برای سفارش</b>\n\n"
            "فایل یا فایل‌های <code>.ovpn</code> را ارسال کنید:", kb)
        return

    # adm:pnd:ovpn:bulk:{pending_id}  →  OpenVPN bulk for pending order
    if data.startswith("adm:pnd:ovpn:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        state_set(uid, "ovpn_bulk_init",
                  package_id=p_row["package_id"], pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ بله — یک فایل",    callback_data=f"adm:pnd:ovpn:bshared:{pending_id}"),
            types.InlineKeyboardButton("❌ خیر — فایل جداگانه", callback_data=f"adm:pnd:ovpn:bdiff:{pending_id}"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:proto:ovpn:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "📎 <b>ثبت دسته‌ای OpenVPN برای سفارش</b>\n\n"
            "آیا همه کاربران از یک فایل <b>.ovpn</b> مشترک استفاده می‌کنند؟", kb)
        return

    # adm:pnd:ovpn:bshared:{pending_id}  →  shared ovpn file for pending
    if data.startswith("adm:pnd:ovpn:bshared:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        state_set(uid, "ovpn_bulk_shared_file",
                  package_id=p_row["package_id"], pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📎 فایل <code>.ovpn</code> مشترک را ارسال کنید:\n"
            "<i>این فایل برای همه سفارش‌های منتظر استفاده می‌شود.</i>", kb)
        return

    # adm:pnd:ovpn:bdiff:{pending_id}  →  different ovpn files for pending
    if data.startswith("adm:pnd:ovpn:bdiff:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        state_set(uid, "ovpn_bulk_diff_files",
                  package_id=p_row["package_id"], pending_id=pending_id,
                  ovpn_sets=[])
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📎 فایل‌های <code>.ovpn</code> کاربر اول را ارسال کنید.\n"
            "پس از تأیید، به کاربر بعدی می‌روید.", kb)
        return

    # adm:pnd:wg:single:{pending_id}  →  WireGuard single for pending order
    if data.startswith("adm:pnd:wg:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_single_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس WireGuard</b> را وارد کنید:",
            back_button(f"adm:pnd:proto:wg:{pending_id}"))
        return

    # adm:pnd:wg:bulk:{pending_id}  →  WireGuard bulk for pending order
    if data.startswith("adm:pnd:wg:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_bulk_init",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ بله — یک کانفیگ",    callback_data=f"adm:pnd:wg:bshared:{pending_id}"),
            types.InlineKeyboardButton("❌ خیر — کانفیگ جداگانه", callback_data=f"adm:pnd:wg:bdiff:{pending_id}"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:proto:wg:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🛡 <b>ثبت دسته‌ای WireGuard برای سفارش</b>\n\n"
            "آیا همه کاربران از یک کانفیگ مشترک استفاده می‌کنند؟", kb)
        return

    # adm:pnd:wg:bshared:{pending_id}  →  shared wg config for pending
    if data.startswith("adm:pnd:wg:bshared:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_bulk_shared_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس مشترک</b> را وارد کنید:",
            back_button(f"adm:pnd:wg:bulk:{pending_id}"))
        return

    # adm:pnd:wg:bdiff:{pending_id}  →  different wg configs for pending
    if data.startswith("adm:pnd:wg:bdiff:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_bulk_diff_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id,
                  wg_sets=[])
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس کاربر اول</b> را وارد کنید:",
            back_button(f"adm:pnd:wg:bulk:{pending_id}"))
        return

    if data == "admin:pr:reject_all":
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✏️ رد همه با توضیح برای کاربران", callback_data="admin:pr:reject_all:note"))
        kb.add(types.InlineKeyboardButton("🚫 رد همه بدون توضیح", callback_data="admin:pr:reject_all:do"))
        kb.add(types.InlineKeyboardButton("❌ لغو", callback_data="admin:pr"))
        send_or_edit(call,
            "⚠️ <b>آیا مطمئن هستید؟</b>\n\n"
            "همه رسیدهای بررسی‌نشده رد خواهند شد.\n\n"
            "• <b>رد همه با توضیح</b>: یک توضیح از شما می‌گیرد و به کاربران ارسال می‌شود.\n"
            "• <b>رد همه بدون توضیح</b>: فقط پیام رد شدن می‌رود، بدون دلیل.",
            kb)
        return

    if data == "admin:pr:reject_all:note":
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        state_set(uid, "admin_reject_all_note")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("❌ لغو", callback_data="admin:pr:reject_all"))
        bot.send_message(uid,
            "✏️ <b>توضیح رد رسیدها</b>\n\n"
            "متنی که می‌نویسید به همه کاربران ارسال می‌شود.\n"
            "مثال: <i>رسید تصویر واضح نیست</i>",
            parse_mode="HTML", reply_markup=kb)
        return

    if data == "admin:pr:reject_all:do":
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        _do_reject_all(call, uid, note=None)
        return

    if data.startswith("adm:pending:addcfg:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        pending_id = int(data.split(":")[3])
        p_row = get_pending_order(pending_id)
        if not p_row:
            bot.answer_callback_query(call.id, "سفارش یافت نشد.", show_alert=True)
            return
        if p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "این سفارش قبلاً تکمیل شده است.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        pkg = get_package(p_row["package_id"])
        pkg_info = ""
        if pkg:
            pkg_info = (
                f"\n\n📦 <b>اطلاعات پکیج:</b>\n"
                f"🧩 نوع: {esc(pkg['type_name'])}\n"
                f"✏️ نام: {esc(pkg['name'])}\n"
                f"🔋 حجم: {fmt_vol(pkg['volume_gb'])}\n"
                f"⏰ مدت: {fmt_dur(pkg['duration_days'])}\n"
                f"💰 قیمت: {fmt_price(pkg['price'])} تومان"
            )
        # Step 1: ask protocol (same as regular config registration)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🌐 V2Ray",    callback_data=f"adm:pnd:proto:v2ray:{pending_id}"))
        kb.add(types.InlineKeyboardButton("🔒 OpenVPN",  callback_data=f"adm:pnd:proto:ovpn:{pending_id}"))
        kb.add(types.InlineKeyboardButton("🛡 WireGuard", callback_data=f"adm:pnd:proto:wg:{pending_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"📝 <b>ثبت کانفیگ برای سفارش #{pending_id}</b>{pkg_info}\n\n"
            "🔌 <b>پروتکل کانفیگ را انتخاب کنید:</b>",
            kb)
        return

    # adm:pnd:proto:{proto}:{pending_id}  →  ask single/bulk
    if data.startswith("adm:pnd:proto:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی مجاز نیست.", show_alert=True)
            return
        parts = data.split(":")
        proto      = parts[3]            # v2ray | ovpn | wg
        pending_id = int(parts[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت نشد یا قبلاً تکمیل شده است.", show_alert=True)
            return
        pkg = get_package(p_row["package_id"])
        # Save pending_id + proto in state so downstream flow can access it
        state_set(uid, "admin_cfg_proto_select",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        if proto == "v2ray":
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",    callback_data=f"adm:pnd:v2:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:pnd:v2:bulk:{pending_id}"))
        elif proto == "ovpn":
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",    callback_data=f"adm:pnd:ovpn:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}"))
        elif proto == "wg":
            kb.add(types.InlineKeyboardButton("📝 ثبت تکی",    callback_data=f"adm:pnd:wg:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("📋 ثبت دسته‌ای", callback_data=f"adm:pnd:wg:bulk:{pending_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pending:addcfg:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, f"📝 روش ثبت کانفیگ را انتخاب کنید:", kb)
        return

    # adm:pnd:v2:single:{pending_id}  →  V2Ray single for pending order
    if data.startswith("adm:pnd:v2:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "v2_single_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  mode=1, pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس</b> را وارد کنید:",
            back_button(f"adm:pnd:proto:v2ray:{pending_id}"))
        return

    # adm:pnd:v2:bulk:{pending_id}  →  V2Ray bulk for pending order
    if data.startswith("adm:pnd:v2:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "v2_bulk_init",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("1️⃣ کانفیگ + ساب — تعداد کم",   callback_data=f"adm:pnd:v2bm:1:{pending_id}"))
        kb.add(types.InlineKeyboardButton("2️⃣ کانفیگ + ساب — تعداد زیاد", callback_data=f"adm:pnd:v2bm:2:{pending_id}"))
        kb.add(types.InlineKeyboardButton("3️⃣ کانفیگ تنها",               callback_data=f"adm:pnd:v2bm:3:{pending_id}"))
        kb.add(types.InlineKeyboardButton("4️⃣ ساب تنها",                  callback_data=f"adm:pnd:v2bm:4:{pending_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:proto:v2ray:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "📋 <b>نوع ثبت دسته‌ای V2Ray</b> را انتخاب کنید:", kb)
        return

    # adm:pnd:v2bm:{mode}:{pending_id}  →  bulk mode selected for pending order
    if data.startswith("adm:pnd:v2bm:"):
        if not is_admin(uid): return
        parts = data.split(":")
        mode = int(parts[3]); pending_id = int(parts[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        s = state_data(uid)
        bot.answer_callback_query(call.id)
        if mode in (1, 2, 3):
            state_set(uid, "v2_bulk_pre",
                      package_id=p_row["package_id"],
                      type_id=pkg["type_id"] if pkg else 0,
                      mode=mode, pending_id=pending_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏭ بدون پیشوند", callback_data=f"adm:pnd:v2bpfx:skip:{pending_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:v2:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "✂️ <b>پیشوند حذفی از نام کانفیگ</b>\n\n"
                "اگر ابتدای نام کانفیگ‌ها متن اضافه‌ای دارد وارد کنید، در غیر اینصورت «بدون پیشوند» بزنید.", kb)
        else:  # mode 4: sub only
            state_set(uid, "v2_bulk_data",
                      package_id=p_row["package_id"],
                      type_id=pkg["type_id"] if pkg else 0,
                      mode=4, prefix="", suffix="", pending_id=pending_id)
            send_or_edit(call, _v2_bulk_data_prompt(4), back_button(f"adm:pnd:v2:bulk:{pending_id}"))
        return

    # adm:pnd:v2bpfx:skip:{pending_id}  →  skip prefix for pending bulk
    if data.startswith("adm:pnd:v2bpfx:skip:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        s = state_data(uid)
        state_set(uid, "v2_bulk_suf",
                  package_id=s["package_id"], type_id=s["type_id"],
                  mode=s["mode"], prefix="", pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⏭ بدون پسوند", callback_data=f"adm:pnd:v2bsfx:skip:{pending_id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:v2:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "✂️ <b>پسوند حذفی از نام کانفیگ</b>\n\n"
            "اگر انتهای نام‌ها متن اضافه‌ای دارد وارد کنید، در غیر اینصورت «بدون پسوند» بزنید.", kb)
        return

    # adm:pnd:v2bsfx:skip:{pending_id}  →  skip suffix for pending bulk
    if data.startswith("adm:pnd:v2bsfx:skip:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        s = state_data(uid)
        mode = s.get("mode", 1)
        state_set(uid, "v2_bulk_data",
                  package_id=s["package_id"], type_id=s["type_id"],
                  mode=mode, prefix=s.get("prefix", ""), suffix="", pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, _v2_bulk_data_prompt(mode), back_button(f"adm:pnd:v2:bulk:{pending_id}"))
        return

    # adm:pnd:ovpn:single:{pending_id}  →  OpenVPN single for pending order
    if data.startswith("adm:pnd:ovpn:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        state_set(uid, "ovpn_single_file",
                  package_id=p_row["package_id"], pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:proto:ovpn:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📎 <b>ثبت تکی OpenVPN برای سفارش</b>\n\n"
            "فایل یا فایل‌های <code>.ovpn</code> را ارسال کنید:", kb)
        return

    # adm:pnd:ovpn:bulk:{pending_id}  →  OpenVPN bulk for pending order
    if data.startswith("adm:pnd:ovpn:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        state_set(uid, "ovpn_bulk_init",
                  package_id=p_row["package_id"], pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ بله — یک فایل",    callback_data=f"adm:pnd:ovpn:bshared:{pending_id}"),
            types.InlineKeyboardButton("❌ خیر — فایل جداگانه", callback_data=f"adm:pnd:ovpn:bdiff:{pending_id}"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:proto:ovpn:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "📎 <b>ثبت دسته‌ای OpenVPN برای سفارش</b>\n\n"
            "آیا همه کاربران از یک فایل <b>.ovpn</b> مشترک استفاده می‌کنند؟", kb)
        return

    # adm:pnd:ovpn:bshared:{pending_id}  →  shared ovpn file for pending
    if data.startswith("adm:pnd:ovpn:bshared:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        state_set(uid, "ovpn_bulk_shared_file",
                  package_id=p_row["package_id"], pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📎 فایل <code>.ovpn</code> مشترک را ارسال کنید:\n"
            "<i>این فایل برای همه سفارش‌های منتظر استفاده می‌شود.</i>", kb)
        return

    # adm:pnd:ovpn:bdiff:{pending_id}  →  different ovpn files for pending
    if data.startswith("adm:pnd:ovpn:bdiff:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        state_set(uid, "ovpn_bulk_diff_files",
                  package_id=p_row["package_id"], pending_id=pending_id,
                  ovpn_sets=[])
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "📎 فایل‌های <code>.ovpn</code> کاربر اول را ارسال کنید.\n"
            "پس از تأیید، به کاربر بعدی می‌روید.", kb)
        return

    # adm:pnd:wg:single:{pending_id}  →  WireGuard single for pending order
    if data.startswith("adm:pnd:wg:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_single_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس WireGuard</b> را وارد کنید:",
            back_button(f"adm:pnd:proto:wg:{pending_id}"))
        return

    # adm:pnd:wg:bulk:{pending_id}  →  WireGuard bulk for pending order
    if data.startswith("adm:pnd:wg:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "سفارش یافت/تکمیل نشد.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_bulk_init",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ بله — یک کانفیگ",    callback_data=f"adm:pnd:wg:bshared:{pending_id}"),
            types.InlineKeyboardButton("❌ خیر — کانفیگ جداگانه", callback_data=f"adm:pnd:wg:bdiff:{pending_id}"),
        )
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnd:proto:wg:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🛡 <b>ثبت دسته‌ای WireGuard برای سفارش</b>\n\n"
            "آیا همه کاربران از یک کانفیگ مشترک استفاده می‌کنند؟", kb)
        return

    # adm:pnd:wg:bshared:{pending_id}  →  shared wg config for pending
    if data.startswith("adm:pnd:wg:bshared:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_bulk_shared_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس مشترک</b> را وارد کنید:",
            back_button(f"adm:pnd:wg:bulk:{pending_id}"))
        return

    # adm:pnd:wg:bdiff:{pending_id}  →  different wg configs for pending
    if data.startswith("adm:pnd:wg:bdiff:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_bulk_diff_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id,
                  wg_sets=[])
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "✏️ <b>نام سرویس کاربر اول</b> را وارد کنید:",
            back_button(f"adm:pnd:wg:bulk:{pending_id}"))
        return

    if data == "noop":
        bot.answer_callback_query(call.id)
        return

    # ── Panel management ──────────────────────────────────────────────────────

    if data == "admin:panels":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _show_admin_panels(call)
        return

    if data == "adm:pnl:add":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        state_set(uid, "pnl_add_type")
        bot.answer_callback_query(call.id)
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb_type = InlineKeyboardMarkup()
        kb_type.add(InlineKeyboardButton("🖥 سناعی (3x-ui)", callback_data="adm:pnl:add_type:sanaei"))
        send_or_edit(call,
            "🖥 <b>افزودن پنل جدید</b>\n\n"
            "مرحله ۱/۸ — <b>نوع پنل</b>\n"
            "نوع پنل مدیریت را انتخاب کنید:",
            kb_type)
        return

    if data.startswith("adm:pnl:add_type:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        if state_name(uid) != "pnl_add_type":
            bot.answer_callback_query(call.id, "عملیات منقضی شده.", show_alert=True)
            return
        panel_type = data.split(":", 3)[3]
        state_set(uid, "pnl_add_name", panel_type=panel_type)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "🖥 <b>افزودن پنل جدید</b>\n\n"
            "مرحله ۲/۸ — <b>نام پنل</b>\n"
            "یک نام دلخواه برای شناسایی این پنل وارد کنید:",
            back_button("admin:panels"))
        return

    if data.startswith("adm:pnl:add_proto:"):
        # adm:pnl:add_proto:{http|https}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        sn = state_name(uid)
        if sn != "pnl_add_proto":
            bot.answer_callback_query(call.id, "عملیات منقضی شده.", show_alert=True)
            return
        protocol = data.split(":", 3)[3]
        sd = state_data(uid)
        state_set(uid, "pnl_add_host", pnl_name=sd.get("pnl_name", ""), protocol=protocol, panel_type=sd.get("panel_type", "sanaei"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"🖥 <b>افزودن پنل جدید</b>\n\n"
            f"مرحله ۴/۸ — <b>آدرس IP یا دامنه</b>\n"
            f"پروتکل انتخاب‌شده: <b>{protocol}</b>\n\n"
            "آدرس IP یا دامنه سرور پنل را ارسال کنید:",
            back_button("admin:panels"))
        return

    if data.startswith("adm:pnl:ef:protocol:"):
        # Edit protocol — show buttons
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("http",  callback_data=f"adm:pnl:set_proto:http:{panel_id}"),
            InlineKeyboardButton("https", callback_data=f"adm:pnl:set_proto:https:{panel_id}"),
        )
        kb.add(InlineKeyboardButton("لغو", callback_data=f"adm:pnl:detail:{panel_id}"))
        send_or_edit(call,
            f"🌐 <b>ویرایش پروتکل</b>\n\nپنل: {esc(p['name'])}\n\nپروتکل جدید را انتخاب کنید:",
            kb)
        return

    if data.startswith("adm:pnl:set_proto:"):
        # adm:pnl:set_proto:{http|https}:{panel_id}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        parts     = data.split(":")
        protocol  = parts[3]
        panel_id  = int(parts[4])
        if protocol not in ("http", "https"):
            bot.answer_callback_query(call.id, "پروتکل نامعتبر.", show_alert=True)
            return
        update_panel_field(panel_id, "protocol", protocol)
        bot.answer_callback_query(call.id, f"پروتکل به {protocol} تغییر یافت.")
        _show_panel_detail(call, panel_id)
        return

    if data.startswith("adm:pnl:ef:"):
        # adm:pnl:ef:{field}:{panel_id}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        parts    = data.split(":")
        field    = parts[3]
        panel_id = int(parts[4])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
            return
        field_labels = {
            "name":         "نام پنل",
            "host":         "آدرس IP / دامنه",
            "port":         "پورت",
            "path":         "مسیر مخفی — برای عدم وجود / ارسال کنید",
            "username":     "نام کاربری",
            "password":     "رمز عبور",
            "sub_url_base": "دامنه ساب (مثال: http://stareh.parhiiz.top:2096) — برای حذف /skip ارسال کنید",
        }
        label = field_labels.get(field, field)
        state_set(uid, "pnl_edit_field", field=field, panel_id=panel_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"✏️ <b>ویرایش — {label}</b>\n\nپنل: <b>{esc(p['name'])}</b>\n\n"
            f"مقدار فعلی: <code>{esc(str(p[field] or ''))}</code>\n\n"
            "مقدار جدید را ارسال کنید:",
            back_button(f"adm:pnl:detail:{panel_id}"))
        return

    if data.startswith("adm:pnl:detail:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_panel_detail(call, panel_id)
        return

    if data.startswith("adm:pnl:toggle:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        parts    = data.split(":")
        panel_id = int(parts[3])
        new_val  = int(parts[4])
        toggle_panel_active(panel_id, new_val)
        label = "فعال" if new_val else "غیرفعال"
        bot.answer_callback_query(call.id, f"پنل {label} شد.")
        _show_panel_detail(call, panel_id)
        return

    if data.startswith("adm:pnl:del:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("✅ بله، حذف کن",  callback_data=f"adm:pnl:delok:{panel_id}"),
            InlineKeyboardButton("❌ لغو",           callback_data=f"adm:pnl:detail:{panel_id}"),
        )
        send_or_edit(call,
            f"⚠️ آیا مطمئن هستید که می‌خواهید پنل <b>{esc(p['name'])}</b> را حذف کنید؟",
            kb)
        return

    if data.startswith("adm:pnl:delok:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        delete_panel(panel_id)
        bot.answer_callback_query(call.id, "پنل حذف شد.")
        _show_admin_panels(call)
        return

    if data.startswith("adm:pnl:recheck:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "در حال بررسی…")
        try:
            from ..panels.client import PanelClient
            ok, err = _panel_connect_with_retry(
                uid=uid, protocol=p["protocol"], host=p["host"], port=p["port"],
                path=p["path"] or "", username=p["username"], password=p["password"],
                panel_name=p.get("name", ""), panel_id=panel_id, notify_chat_id=uid,
            )
            status = "connected" if ok else "disconnected"
            update_panel_status(panel_id, status, err or "")
        except Exception as exc:
            update_panel_status(panel_id, "disconnected", str(exc))
        _show_panel_detail(call, panel_id)
        return

    if data == "adm:pnl:save_as_inactive":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        if state_name(uid) != "pnl_add_save_fail":
            bot.answer_callback_query(call.id, "عملیات منقضی شده.", show_alert=True)
            return
        sd = state_data(uid)
        state_clear(uid)
        panel_id = add_panel(
            name=sd.get("pnl_name", ""),
            protocol=sd.get("protocol", "http"),
            host=sd.get("host", ""),
            port=sd.get("port", 2053),
            path=sd.get("path", ""),
            username=sd.get("username", ""),
            password=sd.get("password", ""),
            sub_url_base=sd.get("sub_url_base", ""),
        )
        toggle_panel_active(panel_id, 0)
        bot.answer_callback_query(call.id, "پنل با وضعیت غیرفعال ذخیره شد.")
        _show_panel_detail(call, panel_id)
        return

    if data == "adm:pnl:skip_sub_url":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        if state_name(uid) != "pnl_add_sub_url":
            bot.answer_callback_query(call.id, "عملیات منقضی شده.", show_alert=True)
            return
        sd = state_data(uid)
        pnl_name = sd.get("pnl_name", "")
        protocol = sd.get("protocol", "http")
        host     = sd.get("host", "")
        port     = sd.get("port", 2053)
        path     = sd.get("path", "")
        username = sd.get("username", "")
        password = sd.get("password", "")
        bot.answer_callback_query(call.id)
        bot.send_message(uid, "⏳ در حال بررسی اتصال به پنل…")
        ok, err = _panel_connect_with_retry(
            uid=uid, protocol=protocol, host=host, port=int(port),
            path=path, username=username, password=password,
            panel_name=pnl_name, notify_chat_id=uid,
        )
        if ok:
            state_clear(uid)
            panel_id = add_panel(name=pnl_name or "بدون نام", protocol=protocol,
                                 host=host, port=int(port or 2053), path=path,
                                 username=username, password=password, sub_url_base="")
            from ..db import update_panel_status
            update_panel_status(panel_id, "connected", "")
            bot.send_message(uid, "✅ اتصال موفق! پنل ذخیره شد.")
            _show_panel_detail(call, panel_id)
        else:
            state_set(uid, "pnl_add_save_fail",
                      pnl_name=pnl_name, protocol=protocol, host=host, port=int(port or 2053),
                      path=path, username=username, password=password, sub_url_base="", error=err or "")
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb_fail = InlineKeyboardMarkup()
            kb_fail.row(
                InlineKeyboardButton("💾 ذخیره به‌عنوان غیرفعال", callback_data="adm:pnl:save_as_inactive"),
                InlineKeyboardButton("❌ لغو", callback_data="adm:pnl:add_cancel"),
            )
            bot.send_message(uid,
                "❌ <b>اتصال ناموفق</b>\n\n"
                "می‌توانید پنل را به‌صورت غیرفعال ذخیره کنید تا بعداً ویرایش شود.",
                parse_mode="HTML", reply_markup=kb_fail)
        return

    if data == "adm:pnl:add_cancel":
        state_clear(uid)
        bot.answer_callback_query(call.id, "لغو شد.")
        _show_admin_panels(call)
        return

    # ── Panel Client Packages management ──────────────────────────────────────
    if data.startswith("adm:pnl:cpkgs:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_panel_client_packages(call, panel_id)
        return

    if data.startswith("adm:pnl:cpkg:preview:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        cpkg_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_panel_client_package_preview(call, cpkg_id)
        return

    if data.startswith("adm:pnl:cpkg:edit:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        cpkg_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_cpkg_edit_menu(call, cpkg_id)
        return

    if data.startswith("adm:pnl:cpkg:ef:"):
        # adm:pnl:cpkg:ef:{field}:{cpkg_id}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        parts   = data.split(":")
        field   = parts[4]
        cpkg_id = int(parts[5])
        cp = get_panel_client_package(cpkg_id)
        if not cp:
            bot.answer_callback_query(call.id, "کلاینت پکیج یافت نشد.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _FIELD_LABELS = {
            "inbound_id":          "🔢 شماره ID اینباند",
            "sample_config":       "📋 نمونه کانفیگ",
            "sample_sub_url":      "🔗 نمونه آدرس سابسکرایب",
            "sample_client_name":  "🏷 نام نمونه در فرگمنت (مثلاً emad-tun)",
        }
        try:
            cur_val = cp[field]
        except (KeyError, IndexError):
            cur_val = ""
        cur_display = esc(str(cur_val)[:200]) if cur_val else "<i>خالی</i>"
        state_set(uid, f"cpkg_ef_{field}", cpkg_id=cpkg_id, panel_id=cp["panel_id"])
        send_or_edit(call,
            f"✏️ <b>ویرایش {_FIELD_LABELS.get(field, field)}</b>\n\n"
            f"مقدار فعلی:\n<code>{cur_display}</code>\n\n"
            "مقدار جدید را ارسال کنید:",
            back_button(f"adm:pnl:cpkg:edit:{cpkg_id}"))
        return

    if data.startswith("adm:pnl:editpanel:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_panel_edit_menu(call, panel_id)
        return

    if data.startswith("adm:pnl:cpkg:del:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        cpkg_id = int(data.split(":")[-1])
        cp = get_panel_client_package(cpkg_id)
        if not cp:
            bot.answer_callback_query(call.id, "یافت نشد.", show_alert=True)
            return
        panel_id = cp["panel_id"]
        delete_panel_client_package(cpkg_id)
        bot.answer_callback_query(call.id, "✅ کلاینت پکیج حذف شد.")
        _show_panel_client_packages(call, panel_id)
        return

    if data.startswith("adm:pnl:cpkg:add:"):
        # Start the "add client package" wizard
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "پنل یافت نشد.", show_alert=True)
            return
        state_set(uid, "cpkg_add_inbound", panel_id=panel_id)
        bot.answer_callback_query(call.id)
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        send_or_edit(call,
            f"📦 <b>افزودن کلاینت پکیج — پنل: {esc(p['name'])}</b>\n\n"
            "🔢 <b>شماره ID اینباند</b> را ارسال کنید:\n\n"
            "💡 در پنل ثنایی به Inbounds بروید و عدد ستون ID را بنویسید (مثلاً <code>3</code>).",
            back_button(f"adm:pnl:cpkgs:{panel_id}"))
        return

    if data.startswith("adm:pnl:cpkg:dm:"):
        # Delivery mode selected for new client package
        # format: adm:pnl:cpkg:dm:{mode}:{panel_id}:{inbound_id}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        parts     = data.split(":")
        mode      = parts[4]
        panel_id  = int(parts[5])
        inbound_id = int(parts[6])
        if mode not in ("config_only", "sub_only", "both"):
            bot.answer_callback_query(call.id)
            return

        bot.answer_callback_query(call.id)

        # ── Manual input flow: ask admin to type sample config / sub URL ──────
        if mode in ("config_only", "both"):
            state_set(uid, "cpkg_sample_config", panel_id=panel_id, inbound_id=inbound_id, mode=mode)
            send_or_edit(call,
                "📄 <b>کانفیگ نمونه</b> را ارسال کنید:\n\n"
                "یک خط کانفیگ از این اینباند کپی کنید.\n"
                "مثال:\n"
                "<code>vless://abcd1234efgh5678@example.com:2096"
                "?security=tls&type=tcp&sni=example.com#example-config</code>",
                back_button(f"adm:pnl:cpkgs:{panel_id}"))
        else:  # sub_only
            state_set(uid, "cpkg_sample_sub",
                      panel_id=panel_id, inbound_id=inbound_id, mode=mode, sample_config="")
            send_or_edit(call,
                "🔗 <b>لینک ساب نمونه</b> را ارسال کنید:\n\n"
                "یک URL ساب واقعی از این اینباند کپی کنید.\n"
                "مثال:\n"
                "<code>http://example.com:2096/sub/abc123xyz456</code>",
                back_button(f"adm:pnl:cpkgs:{panel_id}"))
        return

    bot.answer_callback_query(call.id)

