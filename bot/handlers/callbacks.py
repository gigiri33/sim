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
    validate_service_name, normalize_service_name, generate_random_name, parse_bulk_names,
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
    get_per_gb_price, set_per_gb_price, get_all_per_gb_prices,
    create_reseller_request, get_reseller_request, get_pending_reseller_requests,
    get_reseller_request_by_id, approve_reseller_request, reject_reseller_request,
    set_user_purchase_credit, can_use_credit,
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
    # Addon prices
    get_panel_connected_types, get_addon_price, set_addon_price, get_all_addon_prices_for_addon_type,
    # Panel config
    get_panel_config, get_panel_config_full,
    update_panel_config_field, delete_panel_config,
    # Service naming
    set_payment_service_names, get_payment_service_names,
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
    admin_addon_notify,
)
from ..group_manager import (
    ensure_group_topics, reset_and_recreate_topics, get_group_id,
    _count_active_topics, TOPICS, send_to_topic, log_admin_action,
)
from ..payments import (
    get_effective_price, calculate_effective_order_price, show_payment_method_selection,
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


# ?? OpenVPN helpers (shared with messages.py) ?????????????????????????????????

def _fmt_users_label(max_users):
    if not max_users or max_users == 0:
        return "‰«„ÕœÊœ"
    if max_users == 1:
        return " òùò«—»—Â"
    if max_users == 2:
        return "œÊò«—»—Â"
    return f"{max_users} ò«—»—Â"


# ?? V2Ray helpers ?????????????????????????????????????????????????????????????

def _v2_name_from_sub(sub_url: str) -> str:
    """Extract service name from the last path segment of a subscription URL.

    Example:
        http://s1.example.xyz:2096/sub/n1lw9my64qykgz4n ? n1lw9my64qykgz4n
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
        # Has a #tag ó use the tag (normal path below), but fall back to ps if empty
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
            "?? <b>À»  ⁄„œÂ V2Ray ó ò«‰›Ìê + ”«» („‰«”»  ⁄œ«œ ò„)</b>\n\n"
            "ò«‰›ÌêùÂ« Ê ”«»ùÂ« —« »Âù’Ê—  <b>ÌòÌ œ— „Ì«‰</b> Ê«—œ ò‰Ìœ:\n\n"
            "?? ›—„ :\n"
            "<code>vless://abc...#name1\n"
            "http://panel.com/sub/token1\n"
            "vless://def...#name2\n"
            "http://panel.com/sub/token2</code>\n\n"
            "Ì⁄‰Ì Â— ò«‰›Ìê »·«›«’·Â »« ”«» „—»Êÿ »Â ŒÊœ‘ »Ì«Ìœ.\n\n"
            "?? Ì« „Ìù Ê«‰Ìœ „Õ Ê« —« œ— Ìò ›«Ì· <b>.txt</b> «—”«· ò‰Ìœ."
        )
    if mode == 3:  # config only
        return (
            "?? <b>À»  ⁄„œÂ V2Ray ó ò«‰›Ìê  ‰Â«</b>\n\n"
            "Â„Â ò«‰›ÌêùÂ« —« «—”«· ò‰Ìœ. Â— Œÿ Ìò ò«‰›Ìê:\n\n"
            "?? „À«·:\n"
            "<code>vless://abc...#name1\n"
            "vless://def...#name2</code>\n\n"
            "?? Ì« „Ìù Ê«‰Ìœ „Õ Ê« —« œ— Ìò ›«Ì· <b>.txt</b> «—”«· ò‰Ìœ."
        )
    if mode == 4:  # sub only
        return (
            "?? <b>À»  ⁄„œÂ V2Ray ó ”«»  ‰Â«</b>\n\n"
            "Â„Â ·Ì‰òùÂ«Ì ”«» —« «—”«· ò‰Ìœ. Â— Œÿ Ìò ”«»:\n\n"
            "?? „À«·:\n"
            "<code>http://s1.example.com:2096/sub/token1\n"
            "http://s1.example.com:2096/sub/token2</code>\n\n"
            "‰«„ ”—ÊÌ” Â— ”«» »Âù’Ê—  ŒÊœò«— «“ «‰ Â«Ì ·Ì‰ò «” Œ—«Ã „Ìù‘Êœ.\n\n"
            "?? Ì« „Ìù Ê«‰Ìœ „Õ Ê« —« œ— Ìò ›«Ì· <b>.txt</b> «—”«· ò‰Ìœ."
        )
    if mode == 2:  # config+sub separated (many) ó step 1: configs
        return (
            "?? <b>À»  ⁄„œÂ V2Ray ó ò«‰›Ìê + ”«» („‰«”»  ⁄œ«œ “Ì«œ) ó „—Õ·Â «Ê·</b>\n\n"
            "«» œ« <b>Â„Â ò«‰›ÌêùÂ«</b> —« «—”«· ò‰Ìœ (Â— Œÿ Ìò ò«‰›Ìê):\n\n"
            "?? „À«·:\n"
            "<code>vless://abc...#name1\n"
            "vless://def...#name2</code>\n\n"
            "?? Ì« „Ìù Ê«‰Ìœ „Õ Ê« —« œ— Ìò ›«Ì· <b>.txt</b> «—”«· ò‰Ìœ."
        )
    return ""


def _ovpn_caption(pkg_row, username, password, inquiry):
    users_label = _fmt_users_label(pkg_row["max_users"] if "max_users" in pkg_row.keys() else 0)
    vol_text    = "‰«„ÕœÊœ" if not pkg_row["volume_gb"] else f"{pkg_row['volume_gb']} êÌê"
    dur_text    = "‰«„ÕœÊœ" if not pkg_row["duration_days"] else f"{pkg_row['duration_days']} —Ê“"
    inq_line    = f"\n?? Volume web: {inquiry}" if inquiry else ""
    return (
        f"?? ‰Ê⁄ ”—ÊÌ”: <code>{esc(pkg_row['type_name'])}</code>\n"
        f"?? ÅòÌÃ: <code>{esc(pkg_row['name'])}</code>\n"
        f"?? ÕÃ„: <code>{esc(vol_text)}</code>\n"
        f"? „œ : <code>{esc(dur_text)}</code>\n"
        f"?? ò«—»—: <code>{esc(users_label)}</code>\n"
        f"??????????????????\n"
        f"?? «ÿ·«⁄«  «ò«‰ \n"
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
        bot.send_message(admin_id, "?? ÂÌç ›«Ì· .ovpn À»  ‰‘œÂ »Êœ.", parse_mode="HTML")
        return
    config_data = json.dumps({"type": "ovpn", "file_ids": ovpn_files, "username": username, "password": password}, ensure_ascii=False)
    add_config(pkg_row["type_id"], sd["package_id"], username or "ovpn", config_data, inquiry or "")
    bot.send_message(admin_id,
        f"? <b>1</b> ò«‰›Ìê OpenVPN »« „Ê›ﬁÌ  À»  ‘œ.\n\n"
        f"?? ÌÊ“—‰Ì„: <code>{esc(username)}</code>",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _ovpn_deliver_bulk_shared(admin_id, pkg_row, shared_files, accounts):
    if not shared_files:
        bot.send_message(admin_id, "?? ›«Ì· „‘ —ò ÊÃÊœ ‰œ«—œ.")
        return
    if not accounts:
        bot.send_message(admin_id, "?? «ÿ·«⁄«  «ò«‰ Ì ÊÃÊœ ‰œ«—œ.")
        return
    for acct in accounts:
        config_data = json.dumps({"type": "ovpn", "file_ids": shared_files, "username": acct["username"], "password": acct["password"]}, ensure_ascii=False)
        add_config(pkg_row["type_id"], pkg_row["id"], acct["username"] or "ovpn", config_data, acct.get("inquiry", ""))
    lines = "\n".join(f"{i}. <code>{esc(a['username'])}</code>" for i, a in enumerate(accounts, 1))
    bot.send_message(admin_id,
        f"? <b>{len(accounts)}</b> ò«‰›Ìê OpenVPN »« „Ê›ﬁÌ  À»  ‘œ.\n\n"
        f"?? ·Ì”  ÌÊ“—‰Ì„ùÂ«:\n{lines}",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _ovpn_deliver_bulk_diff(admin_id, pkg_row, acct_files, accounts):
    total = len(accounts)
    if not acct_files or not accounts:
        bot.send_message(admin_id, "?? ›«Ì· Ì« «ÿ·«⁄«  «ò«‰ ùÂ« ÊÃÊœ ‰œ«—œ.")
        return
    for i, acct in enumerate(accounts, 1):
        files = acct_files.get(i, [])
        config_data = json.dumps({"type": "ovpn", "file_ids": files, "username": acct["username"], "password": acct["password"]}, ensure_ascii=False)
        add_config(pkg_row["type_id"], pkg_row["id"], acct["username"] or "ovpn", config_data, acct.get("inquiry", ""))
    lines = "\n".join(f"{i}. <code>{esc(a['username'])}</code>" for i, a in enumerate(accounts, 1))
    bot.send_message(admin_id,
        f"? <b>{total}</b> ò«‰›Ìê OpenVPN »« „Ê›ﬁÌ  À»  ‘œ.\n\n"
        f"?? ·Ì”  ÌÊ“—‰Ì„ùÂ«:\n{lines}",
        parse_mode="HTML", reply_markup=kb_admin_panel())


# ?? WireGuard helpers ?????????????????????????????????????????????????????????

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
    vol_text    = "‰«„ÕœÊœ" if not pkg_row["volume_gb"] else f"{pkg_row['volume_gb']} êÌê"
    dur_text    = "‰«„ÕœÊœ" if not pkg_row["duration_days"] else f"{pkg_row['duration_days']} —Ê“"
    inq_line    = f"\n?? Volume web: {inquiry}" if inquiry else ""
    return (
        f"?? ‰Ê⁄ ”—ÊÌ”: <code>{esc(pkg_row['type_name'])}</code>\n"
        f"?? ÅòÌÃ: <code>{esc(pkg_row['name'])}</code>\n"
        f"?? ÕÃ„: <code>{esc(vol_text)}</code>\n"
        f"? „œ : <code>{esc(dur_text)}</code>\n"
        f"?? ‰Ê⁄ ò«—»—Ì: <code>{esc(users_label)}</code>\n"
        f"?? ‰«„ ”—ÊÌ”: <code>{esc(service_name)}</code>"
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
        bot.send_message(admin_id, "?? ÂÌç ›«Ì· WireGuard À»  ‰‘œÂ »Êœ.", parse_mode="HTML")
        return
    config_data = json.dumps({"type": "wg", "file_ids": wg_files}, ensure_ascii=False)
    add_config(pkg_row["type_id"], sd["package_id"], service_name, config_data, inquiry or "")
    bot.send_message(admin_id,
        f"? <b>1</b> ò«‰›Ìê WireGuard »« „Ê›ﬁÌ  À»  ‘œ.\n\n"
        f"?? ‰«„ ”—ÊÌ”: <code>{esc(service_name)}</code>",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _wg_deliver_bulk_shared(admin_id, pkg_row, shared_files, shared_names, inquiries):
    """Deliver bulk WireGuard configs where all configs share the same files."""
    if not shared_files:
        bot.send_message(admin_id, "?? ›«Ì· „‘ —ò ÊÃÊœ ‰œ«—œ.")
        return
    service_name = _wg_service_name_from_filename(shared_names[-1] if shared_names else "")
    count = len(inquiries) if inquiries else 1
    for inq in (inquiries if inquiries else [""]):
        config_data = json.dumps({"type": "wg", "file_ids": shared_files}, ensure_ascii=False)
        add_config(pkg_row["type_id"], pkg_row["id"], service_name, config_data, inq or "")
    lines = "\n".join(f"{i}. <code>{esc(service_name)}</code>" for i in range(1, count + 1))
    bot.send_message(admin_id,
        f"? <b>{count}</b> ò«‰›Ìê WireGuard »« „Ê›ﬁÌ  À»  ‘œ.\n\n"
        f"?? ·Ì”  ‰«„ ”—ÊÌ”ùÂ«:\n{lines}",
        parse_mode="HTML", reply_markup=kb_admin_panel())


def _wg_deliver_bulk_diff(admin_id, pkg_row, acct_files, acct_names, inquiries):
    """Deliver bulk WireGuard configs where each config has different files."""
    total = len(acct_files)
    if not acct_files:
        bot.send_message(admin_id, "?? ›«Ì·Ì »—«Ì «—”«· ÊÃÊœ ‰œ«—œ.")
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
        f"? <b>{total}</b> ò«‰›Ìê WireGuard »« „Ê›ﬁÌ  À»  ‘œ.\n\n"
        f"?? ·Ì”  ‰«„ ”—ÊÌ”ùÂ«:\n{lines}",
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
        mark     = "?" if c["id"] in selected else "??"
        svc_name = urllib.parse.unquote(c["service_name"] or "")
        kb.add(types.InlineKeyboardButton(f"{mark} {svc_name}", callback_data=f"adm:stk:btog:{c['id']}"))

    if not all_sel:
        kb.add(types.InlineKeyboardButton("?? «‰ Œ«» Â„Â «Ì‰ ’›ÕÂ", callback_data="adm:stk:bsall"))
    else:
        kb.add(types.InlineKeyboardButton("?? ·€Ê «‰ Œ«» «Ì‰ ’›ÕÂ", callback_data="adm:stk:bclr"))
    if selected:
        kb.add(types.InlineKeyboardButton("?? ·€Ê Â„Â «‰ Œ«»ùÂ«", callback_data="adm:stk:bclrall"))

    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton("?? ﬁ»·", callback_data=f"adm:stk:bnav:{page-1}"))
    nav_row.append(types.InlineKeyboardButton(f"?? {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(types.InlineKeyboardButton("»⁄œ ??", callback_data=f"adm:stk:bnav:{page+1}"))
    if len(nav_row) > 1:
        kb.row(*nav_row)

    if selected:
        sel_count = len(selected)
        if kind in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton(f"?? Õ–› ({sel_count})", callback_data="adm:stk:bdel"),
                types.InlineKeyboardButton(f"? „‰ﬁ÷Ì ({sel_count})", callback_data="adm:stk:bexp"),
            )
        else:
            kb.add(types.InlineKeyboardButton(f"?? Õ–› ({sel_count})", callback_data="adm:stk:bdel"))

    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:stk:bcanc", icon_custom_emoji_id="5253997076169115797"))

    kind_labels = {"av": "?? „ÊÃÊœ", "sl": "?? ›—ÊŒ Â", "ex": "? „‰ﬁ÷Ì"}
    heading = (
        f"?? <b>«‰ Œ«» ê—ÊÂÌ ó {kind_labels.get(kind, '')}</b>\n\n"
        f"? {len(selected)} „Ê—œ «‰ Œ«» ‘œÂ | ’›ÕÂ {page+1}/{total_pages} «“ {total} ò«‰›Ìê"
    )
    send_or_edit(call, heading, kb)


# ?? Per-user callback serialisation ??????????????????????????????????????????
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
    amount_line = f"\n?? „»·€ ﬁ«»· Å—œ«Œ : <b>{fmt_price(amount)}</b>  Ê„«‰\n" if amount else ""
    return (
        "??? <b>òœ  Œ›Ì› ÊÌéÂ</b> ???\n"
        f"{amount_line}\n"
        "?? ÅÌ‘ «“ Å—œ«Œ ° «ê— òœ  Œ›Ì› «Œ ’«’Ì œ«—Ìœ Ê«—œ ò‰Ìœ\n"
        "Ê «“ „“«Ì«Ì ÊÌéÂùÌ ¬‰ »Â—Âù„‰œ ‘ÊÌœ! ??\n\n"
        "?? ¬Ì« òœ  Œ›Ì› œ«—Ìœø"
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


# ?? Invoice expiry helpers ?????????????????????????????????????????????????????

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
        f"\n\n? «⁄ »«— «Ì‰ ›«ò Ê—  « ”«⁄  <b>{expiry_str}</b> «” ."
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
    # a completely different flow ó allow the payment through.
    _INVOICE_STATES = {
        "buy_select_method", "renew_select_method", "wallet_charge_method",
    }
    if sn not in _INVOICE_STATES:
        return True
    sd = state_data(uid)
    created_at = sd.get("invoice_created_at")
    if not created_at:
        return True  # no timestamp yet ó backward-compatible, allow
    elapsed = time.time() - float(created_at)
    limit = _invoice_expiry_minutes() * 60
    valid = elapsed <= limit
    if not valid:
        log.warning(
            "_check_invoice_valid: uid=%s EXPIRED ó elapsed=%.0fs limit=%.0fs state=%s",
            uid, elapsed, limit, sn
        )
    return valid


_INVOICE_EXPIRED_MSG = (
    "? “„«‰ Å—œ«Œ  ‘„« »« «Ì‰ ›«ò Ê— »Â Å«Ì«‰ —”ÌœÂ «” .\n"
    "·ÿ›« œÊ»«—Â «ﬁœ«„ ò‰Ìœ."
)


def _show_invoice_expired(call) -> None:
    """Edit the invoice message in-place to show expiry notice with a restart button."""
    uid = call.from_user.id
    state_clear(uid)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("?? ‘—Ê⁄ „Ãœœ", callback_data="invoice:restart"))
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
        return False  # hidden ó only for referral gifts, not regular purchase
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
        # No eligible codes ó skip this step entirely, return False so caller can proceed
        return False
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("? »·Â° œ«—„", callback_data="disc:yes"),
        types.InlineKeyboardButton("? ŒÌ—° «œ«„Â", callback_data="disc:no"),
    )
    send_or_edit(call, _build_discount_prompt_text(amount), kb)
    return True


def _is_panel_package(package_row) -> bool:
    """Return True if this package is panel-based (creates configs via external panel API)."""
    try:
        src = package_row["config_source"] or "manual"
    except (IndexError, KeyError, TypeError):
        src = "manual"
    return src == "panel"


def _show_naming_prompt(target, package_id: int, quantity: int):
    """Show the naming-type selection step (random vs custom) for panel packages."""
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("?? ‰«„ —‰œÊ„",    callback_data=f"buy:naming:random:{package_id}:{quantity}"),
        types.InlineKeyboardButton("?? ‰«„ œ·ŒÊ«Â",   callback_data=f"buy:naming:custom:{package_id}:{quantity}"),
    )
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"buy:p:{package_id}",
                                      icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(target,
        "?? <b>«‰ Œ«» ‰«„ ”—ÊÌ”</b>\n\n"
        "·ÿ›« „‘Œ’ ò‰Ìœ ‰«„ ”—ÊÌ” ‘„« »Â çÂ ’Ê—  À»  ‘Êœ.",
        kb)


def _show_purchase_gateways(target, uid, package_id, price, package_row):
    """Build and show gateway selection keyboard for config purchase."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    if wallet_pay_enabled_for(uid):
        kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  «“ „ÊÃÊœÌ", callback_data=f"pay:wallet:{package_id}"))
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "?? ò«—  »Â ò«— "
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:card:{package_id}"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "?? «—“ œÌÃÌ «·"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:crypto:{package_id}"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:tetrapay:{package_id}"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  Ê «—“ œÌÃÌ «· (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:swapwallet_crypto:{package_id}"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  (TronPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:tronpays_rial:{package_id}"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"buy:t:{package_row['type_id']}", icon_custom_emoji_id="5253997076169115797"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    _pkg_sn = package_row['show_name'] if 'show_name' in package_row.keys() else 1
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", price)
    quantity    = int(sd.get("quantity", 1) or 1)
    unit_price  = int(sd.get("unit_price", 0) or 0) or (orig_amount // quantity if quantity > 1 else orig_amount)

    # Build price / quantity lines
    _qty_line = f"??  ⁄œ«œ: <b>{quantity}</b> ⁄œœ\n" if quantity > 1 else ""
    if quantity > 1:
        _unit_line = f"?? ﬁÌ„  Â— ⁄œœ: <b>{fmt_price(unit_price)}</b>  Ê„«‰\n"
    else:
        _unit_line = ""

    if disc_amount:
        _price_line = (
            f"?? „»·€ «’·Ì: {fmt_price(orig_amount)}  Ê„«‰\n"
            f"??  Œ›Ì›: {fmt_price(disc_amount)}  Ê„«‰\n"
            f"?? „»·€ ‰Â«ÌÌ: {fmt_price(price)}  Ê„«‰"
        )
    else:
        if quantity > 1:
            _price_line = f"?? „»·€ ò·: <b>{fmt_price(price)}</b>  Ê„«‰"
        else:
            _price_line = f"?? ﬁÌ„ : {fmt_price(price)}  Ê„«‰"
    _stamp_invoice(uid)
    text = (
        "?? <b>«‰ Œ«» —Ê‘ Å—œ«Œ </b>\n\n"
        f"?? ‰Ê⁄: {esc(package_row['type_name'])}\n"
        + (f"?? ÅòÌÃ: {esc(package_row['name'])}\n" if _pkg_sn else "")
        + f"?? ÕÃ„: {fmt_vol(package_row['volume_gb'])}\n"
        f"? „œ : {fmt_dur(package_row['duration_days'])}\n"
        f"{_qty_line}"
        f"{_unit_line}"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "—Ê‘ Å—œ«Œ  —« «‰ Œ«» ò‰Ìœ:"
        + _invoice_expiry_line()
    )
    send_or_edit(target, text, kb)


def _show_renewal_gateways(target, uid, purchase_id, package_id, price, package_row, item):
    """Build and show gateway selection keyboard for renewal."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    if wallet_pay_enabled_for(uid):
        kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  «“ „ÊÃÊœÌ", callback_data=f"rpay:wallet:{purchase_id}:{package_id}"))
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "?? ò«—  »Â ò«— "
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:card:{purchase_id}:{package_id}"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "?? «—“ œÌÃÌ «·"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:crypto:{purchase_id}:{package_id}"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:tetrapay:{purchase_id}:{package_id}"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  Ê «—“ œÌÃÌ «· (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:swapwallet_crypto:{purchase_id}:{package_id}"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  (TronPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:tronpays_rial:{purchase_id}:{package_id}"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"renew:{purchase_id}", icon_custom_emoji_id="5253997076169115797"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    _pkg_sn_renew = package_row['show_name'] if 'show_name' in package_row.keys() else 1
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", price)
    if disc_amount:
        _price_line = (
            f"?? ﬁÌ„  «’·Ì: {fmt_price(orig_amount)}  Ê„«‰\n"
            f"??  Œ›Ì›: {fmt_price(disc_amount)}  Ê„«‰\n"
            f"?? ﬁÌ„  ‰Â«ÌÌ: {fmt_price(price)}  Ê„«‰"
        )
    else:
        _price_line = f"?? ﬁÌ„ : {fmt_price(price)}  Ê„«‰"
    _stamp_invoice(uid)
    text = (
        "?? <b> „œÌœ ”—ÊÌ”</b>\n\n"
        f"?? ”—ÊÌ” ›⁄·Ì: {esc(move_leading_emoji(urllib.parse.unquote(item['service_name'] or '')))}\n"
        + (f"?? ÅòÌÃ  „œÌœ: {esc(package_row['name'])}\n" if _pkg_sn_renew else "")
        + f"?? ÕÃ„: {fmt_vol(package_row['volume_gb'])}\n"
        f"? „œ : {fmt_dur(package_row['duration_days'])}\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "—Ê‘ Å—œ«Œ  —« «‰ Œ«» ò‰Ìœ:"
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
        return False, "ò«‰›Ìê Ì«›  ‰‘œ."
    cfg = dict(cfg)
    _uid = uid or cfg["user_id"]
    pkg = _get_pkg3(package_id)
    if not pkg:
        return False, "ÅòÌÃ Ì«›  ‰‘œ."
    panel = _get_pnl(cfg["panel_id"])
    if not panel:
        return False, "Å‰· Ì«›  ‰‘œ."

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
                    "? <b>”—Ê— Å‰· œ— Õ«· Õ«÷— œ— œ” —” ‰Ì” </b>\n\n"
                    " „œÌœ ”—ÊÌ” œ— ’› «‰ Ÿ«— ﬁ—«— ê—› . "
                    "»Â „Õ÷ »«“ê‘  « ’«·° ”—ÊÌ” ‘„«  „œÌœ ŒÊ«Âœ ‘œ.",
                    parse_mode="HTML",
                )
                _waiting_notified = True
                _last_periodic = now
            except Exception:
                pass
        elif now - _last_periodic >= PERIODIC_INTERVAL:
            try:
                bot.send_message(chat_id, "? Â‰Ê“ œ— Õ«·  ·«‘ »—«Ì « ’«· »Â Å‰·...", parse_mode="HTML")
                _last_periodic = now
            except Exception:
                pass

    def _notify_reconnected():
        if _waiting_notified and chat_id:
            try:
                bot.send_message(chat_id, "? « ’«· »Â Å‰· »—ﬁ—«— ‘œ° œ— Õ«·  „œÌœ ”—ÊÌ”...", parse_mode="HTML")
            except Exception:
                pass

    # ?? Step 1: login ?????????????????????????????????????????????????????????
    login_err = None
    _t0 = _time.time()
    while True:
        if _time.time() - _t_start > MAX_WAIT:
            login_err = "Õœ«òÀ— “„«‰ «‰ Ÿ«— (8 ”«⁄ )  „«„ ‘œ"
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
        _notify_panel_error(_uid, pkg, "login ( „œÌœ)", login_err, config_id, cfg["panel_id"])
        return False, " „œÌœ ”—ÊÌ” »« Œÿ« „Ê«ÃÂ ‘œ. ·ÿ›« »« Å‘ Ì»«‰Ì «— »«ÿ »êÌ—Ìœ."

    # ?? Step 2: reset traffic ??????????????????????????????????????????????????
    reset_err = None
    _t0 = _time.time()
    while True:
        if _time.time() - _t_start > MAX_WAIT:
            reset_err = "Õœ«òÀ— “„«‰ «‰ Ÿ«—  „«„ ‘œ"
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
        _notify_panel_error(_uid, pkg, "reset_traffic ( „œÌœ)", reset_err, config_id, cfg["panel_id"])
        return False, " „œÌœ ”—ÊÌ” »« Œÿ« „Ê«ÃÂ ‘œ. ·ÿ›« »« Å‘ Ì»«‰Ì «— »«ÿ »êÌ—Ìœ."

    # ?? Step 3: enable_client with new expiry ?????????????????????????????????
    dur_days = int(pkg["duration_days"] or 0)
    if dur_days:
        new_exp_dt  = _dt.utcnow() + _td(days=dur_days)
        new_exp_str = new_exp_dt.strftime("%Y-%m-%d %H:%M:%S")
        new_exp_ms  = int(new_exp_dt.timestamp() * 1000)
    else:
        new_exp_str = None
        new_exp_ms  = 0

    new_traffic_bytes = int((pkg["volume_gb"] or 0) * 1073741824)

    enable_err = None
    _t0 = _time.time()
    while True:
        if _time.time() - _t_start > MAX_WAIT:
            enable_err = "Õœ«òÀ— “„«‰ «‰ Ÿ«—  „«„ ‘œ"
            break
        ok_e, res_e = pc_api._update_client(
            cfg["inbound_id"], cfg["client_uuid"],
            {
                "enable": True,
                "totalGB": new_traffic_bytes,
                "expiryTime": new_exp_ms,
            },
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
        _notify_panel_error(_uid, pkg, "enable_client ( „œÌœ)", enable_err, config_id, cfg["panel_id"])
        return False, " „œÌœ ”—ÊÌ” »« Œÿ« „Ê«ÃÂ ‘œ. ·ÿ›« »« Å‘ Ì»«‰Ì «— »«ÿ »êÌ—Ìœ."

    # ?? Step 4: update DB ??????????????????????????????????????????????????????
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
        kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  «“ „ÊÃÊœÌ",
               callback_data=f"mypnlcfgrpay:wallet:{config_id}:{package_id}"))
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "?? ò«—  »Â ò«— "
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:card:{config_id}:{package_id}"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "?? «—“ œÌÃÌ «·"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:crypto:{config_id}:{package_id}"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:tetrapay:{config_id}:{package_id}"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  Ê «—“ œÌÃÌ «· (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:swapwallet_crypto:{config_id}:{package_id}"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  (TronPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"mypnlcfgrpay:tronpays_rial:{config_id}:{package_id}"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"mypnlcfg:renewconfirm:{config_id}",
           icon_custom_emoji_id="5253997076169115797"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    _pkg_sn_renew = package_row['show_name'] if 'show_name' in package_row.keys() else 1
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", price)
    if disc_amount:
        _price_line = (
            f"?? ﬁÌ„  «’·Ì: {fmt_price(orig_amount)}  Ê„«‰\n"
            f"??  Œ›Ì›: {fmt_price(disc_amount)}  Ê„«‰\n"
            f"?? ﬁÌ„  ‰Â«ÌÌ: {fmt_price(price)}  Ê„«‰"
        )
    else:
        _price_line = f"?? ﬁÌ„ : {fmt_price(price)}  Ê„«‰"
    _stamp_invoice(uid)
    svc_name = cfg.get("client_name") or ""
    text = (
        "?? <b> „œÌœ ”—ÊÌ”</b>\n\n"
        f"?? ”—ÊÌ”: {esc(svc_name)}\n"
        + (f"?? ÅòÌÃ  „œÌœ: {esc(package_row['name'])}\n" if _pkg_sn_renew else "")
        + f"?? ÕÃ„: {fmt_vol(package_row['volume_gb'])}\n"
        f"? „œ : {fmt_dur(package_row['duration_days'])}\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "—Ê‘ Å—œ«Œ  —« «‰ Œ«» ò‰Ìœ:"
        + _invoice_expiry_line()
    )
    send_or_edit(target, text, kb)


def _show_wallet_gateways(target, uid, amount):
    """Build and show gateway selection keyboard for wallet charge."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "?? ò«—  »Â ò«— "
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:card"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "?? «—“ œÌÃÌ «·"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:crypto"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:tetrapay"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  Ê «—“ œÌÃÌ «· (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:swapwallet_crypto"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "?? œ—ê«Â ò«—  »Â ò«—  (TronPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:tronpays_rial"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", amount)
    if disc_amount:
        _price_line = (
            f"?? „»·€ «’·Ì: {fmt_price(orig_amount)}  Ê„«‰\n"
            f"??  Œ›Ì›: {fmt_price(disc_amount)}  Ê„«‰\n"
            f"?? „»·€ ‰Â«ÌÌ: {fmt_price(amount)}  Ê„«‰"
        )
    else:
        _price_line = f"?? „»·€: {fmt_price(amount)}  Ê„«‰"
    _stamp_invoice(uid)
    text = (
        "?? <b>‘«—é òÌ› ÅÊ·</b>\n\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "—Ê‘ Å—œ«Œ  —« «‰ Œ«» ò‰Ìœ:"
        + _invoice_expiry_line()
    )
    send_or_edit(target, text, kb)


# ?? Bulk/Quantity Purchase Helpers ?????????????????????????????????????????????

def _show_qty_prompt(call, package_row, unit_price):
    """Show the quantity-selection prompt to the user."""
    from ..db import should_show_bulk_qty, get_bulk_qty_limits
    uid = call.from_user.id
    _pkg_sn   = package_row.get("show_name", 1) if not hasattr(package_row, "keys") else (package_row["show_name"] if "show_name" in package_row.keys() else 1)
    _pkg_name = package_row["name"] if _pkg_sn else ""
    _name_line = f"?? ÅòÌÃ: <b>{esc(_pkg_name)}</b>\n" if _pkg_name else ""

    min_qty, max_qty = get_bulk_qty_limits()
    max_label = "»œÊ‰ „ÕœÊœÌ " if max_qty == 0 else str(max_qty)
    limit_line = (
        f"?? Õœ«ﬁ·: <b>{min_qty}</b>  |  Õœ«òÀ—: <b>{max_label}</b>\n\n"
    )

    state_set(uid, "await_qty",
              package_id=package_row["id"],
              unit_price=unit_price,
              kind="config_purchase")
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"buy:t:{package_row['type_id']}", icon_custom_emoji_id="5253997076169115797"))
    text = (
        "?? <b>Œ—Ìœ  ⁄œ«œÌ</b>\n\n"
        f"?? ‰Ê⁄ ”—ÊÌ”: <b>{esc(package_row['type_name'])}</b>\n"
        f"{_name_line}"
        f"?? ÕÃ„: {fmt_vol(package_row['volume_gb'])}  |  ? „œ : {fmt_dur(package_row['duration_days'])}\n"
        f"?? ﬁÌ„  Â— ⁄œœ: <b>{fmt_price(unit_price)}</b>  Ê„«‰\n\n"
        "??????????????????\n"
        f"?? çÂ  ⁄œ«œ ò«‰›Ìê ‰Ì«“ œ«—Ìœø\n\n"
        f"{limit_line}"
        "?? <i>⁄œœ „Ê—œ‰Ÿ— —«  «ÌÅ ò‰Ìœ („À·« ?° ?° ?)</i>"
    )
    send_or_edit(call, text, kb)


def _qty_order_summary_text(package_row, unit_price, quantity):
    """Build the order-summary text shown after qty entry."""
    _pkg_sn   = package_row.get("show_name", 1) if not hasattr(package_row, "keys") else (package_row["show_name"] if "show_name" in package_row.keys() else 1)
    _pkg_name = package_row["name"] if _pkg_sn else ""
    _name_line = f"?? ÅòÌÃ: <b>{esc(_pkg_name)}</b>\n" if _pkg_name else ""
    total = unit_price * quantity
    return (
        "?? <b>Œ·«’Â ”›«—‘</b>\n\n"
        f"?? ‰Ê⁄ ”—ÊÌ”: <b>{esc(package_row['type_name'])}</b>\n"
        f"{_name_line}"
        f"?? ÕÃ„: {fmt_vol(package_row['volume_gb'])}  |  ? „œ : {fmt_dur(package_row['duration_days'])}\n\n"
        "??????????????????\n"
        f"??  ⁄œ«œ: <b>{quantity}</b> ⁄œœ\n"
        f"?? ﬁÌ„  Â— ⁄œœ: <b>{fmt_price(unit_price)}</b>  Ê„«‰\n"
        f"?? „»·€ ò·: <b>{fmt_price(total)}</b>  Ê„«‰\n"
        "??????????????????"
    )


# ?? Admin add-on price list renderer ?????????????????????????????????????????

def _render_addon_price_list(call_or_target, addon_type):
    """Render the admin panel for setting per-unit addon prices for all panel types."""
    enabled_key  = f"addon_{addon_type}_enabled"
    is_enabled   = setting_get(enabled_key, "1") == "1"
    toggle_label = (
        f"{'? €Ì—›⁄«· ò—œ‰' if is_enabled else '? ›⁄«· ò—œ‰'} Œ—Ìœ "
        f"{'ÕÃ„' if addon_type == 'volume' else '“„«‰'} «÷«›Â"
    )
    toggle_cb  = f"adm:addons:{addon_type}:toggle"
    unit_label = "êÌê" if addon_type == "volume" else "—Ê“"
    cb_prefix  = "vol" if addon_type == "volume" else "time"
    title      = "??  ⁄ÌÌ‰ ﬁÌ„  ÕÃ„ «÷«›Â" if addon_type == "volume" else "?  ⁄ÌÌ‰ ﬁÌ„  “„«‰ «÷«›Â"

    rows = get_all_addon_prices_for_addon_type(addon_type)
    text = (
        f"{title}\n\n"
        f"Ê÷⁄Ì : {'? ›⁄«·' if is_enabled else '? €Ì—›⁄«·'}\n\n"
    )
    if rows:
        for r in rows:
            norm = (fmt_price(r["normal_unit_price"]) + "  Ê„«‰") if r["normal_unit_price"] is not None else " ⁄ÌÌ‰ ‰‘œÂ"
            res  = (fmt_price(r["reseller_unit_price"]) + "  Ê„«‰") if r["reseller_unit_price"] is not None else " ⁄ÌÌ‰ ‰‘œÂ"
            text += (
                f"?? <b>{esc(r['type_name'])}</b>\n"
                f"  ?? ò«—»—«‰ ⁄«œÌ: {norm} / {unit_label}\n"
                f"  ?? ‰„«Ì‰œê«‰: {res} / {unit_label}\n\n"
            )
    else:
        text += "ÂÌç ‰Ê⁄ ”—ÊÌ” Å‰·ù„ÕÊ—Ì Ì«›  ‰‘œ."

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(toggle_label, callback_data=toggle_cb))
    for r in rows:
        tid = r["type_id"]
        short_name = esc(r["type_name"][:15])
        kb.row(
            types.InlineKeyboardButton(f"?? {short_name} - ò«—»—",
                                       callback_data=f"adm:addons:{cb_prefix}:set:{tid}:normal"),
            types.InlineKeyboardButton(f"?? {short_name} - ‰„«Ì‰œÂ",
                                       callback_data=f"adm:addons:{cb_prefix}:set:{tid}:res"),
        )
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:addons",
                                      icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call_or_target, text, kb)


# ?? Addon flow helpers ????????????????????????????????????????????????????????

def _get_addon_unit_price(cfg_row, addon_type):
    """Resolve effective per-unit price for an addon (volume/time) given the config row.
    Returns (unit_price: int, error_msg: str|None).
    """
    from ..db import get_package as _gpkg
    pkg = _gpkg(cfg_row["package_id"])
    if not pkg:
        return None, "”—ÊÌ” Ì«›  ‰‘œ."
    price_row = get_addon_price(pkg["type_id"], addon_type)
    from ..db import get_user as _guser
    user = _guser(cfg_row["user_id"])
    is_agent = bool(user["is_agent"]) if user else False
    unit_price = None
    if price_row:
        if is_agent and price_row["reseller_unit_price"] is not None:
            unit_price = price_row["reseller_unit_price"]
        elif price_row["normal_unit_price"] is not None:
            unit_price = price_row["normal_unit_price"]
    if unit_price is None:
        return None, "ﬁÌ„  «Ì‰ «›“Êœ‰Ì «“ ”„  Å‘ Ì»«‰Ì  ⁄ÌÌ‰ ‰‘œÂ «” ."
    return unit_price, None


def _show_addon_invoice(target, uid, addon_type):
    """Build and send/edit the addon purchase invoice based on current state_data."""
    sd = state_data(uid)
    config_id       = sd.get("config_id")
    unit_price      = int(sd.get("unit_price", 0))
    subtotal        = int(sd.get("subtotal", 0))
    discount_amount = int(sd.get("discount_amount", 0))
    final_amount    = int(sd.get("final_amount", subtotal))

    from ..db import get_panel_config as _gcfg, get_package as _gpkg
    cfg = _gcfg(config_id) if config_id else None
    pkg = _gpkg(cfg["package_id"]) if cfg else None

    # Get type_name via joined query if possible
    from ..db import get_all_types as _gt
    type_name = "ó"
    if pkg:
        all_types = _gt()
        for t in all_types:
            if t["id"] == pkg["type_id"]:
                type_name = t["name"]
                break

    if addon_type == "volume":
        gb     = sd.get("amount_gb", 0)
        title  = "?? <b>›«ò Ê— Œ—Ìœ ÕÃ„ «÷«›Â</b>"
        detail = (
            f"?? ÕÃ„ «÷«›Â: <b>{gb} êÌê</b>\n"
            f"?? ﬁÌ„  Â— êÌê: <b>{fmt_price(unit_price)}  Ê„«‰</b>\n"
        )
    else:
        days   = sd.get("amount_days", 0)
        title  = "?? <b>›«ò Ê— Œ—Ìœ “„«‰ «÷«›Â</b>"
        detail = (
            f"? “„«‰ «÷«›Â: <b>{days} —Ê“</b>\n"
            f"?? ﬁÌ„  Â— —Ê“: <b>{fmt_price(unit_price)}  Ê„«‰</b>\n"
        )

    disc_line = f"?? „»·€  Œ›Ì›: <b>{fmt_price(discount_amount)}  Ê„«‰</b>\n" if discount_amount else ""
    text = (
        f"{title}\n\n"
        f"?? ‰Ê⁄ ”—ÊÌ”: {esc(type_name)}\n"
        f"{detail}"
        f"?? „»·€ ò·: <b>{fmt_price(subtotal)}  Ê„«‰</b>\n"
        f"{disc_line}"
        f"? „»·€ ‰Â«ÌÌ: <b>{fmt_price(final_amount)}  Ê„«‰</b>"
    )

    kb = types.InlineKeyboardMarkup()
    # Discount code button
    if setting_get("discount_codes_enabled", "1") == "1":
        from ..db import get_user as _gu
        user = _gu(uid)
        is_agent = bool(user["is_agent"]) if user else False
        if has_eligible_discount_codes(is_agent):
            kb.add(types.InlineKeyboardButton(
                "?? òœ  Œ›Ì›",
                callback_data=f"addon:disc:{config_id}:{addon_type}"))

    # Wallet pay
    if wallet_pay_enabled_for(uid):
        from ..db import get_user as _gu2
        user2 = _gu2(uid)
        balance = int(user2["balance"]) if user2 else 0
        bal_label = f"?? Å—œ«Œ  «“ „ÊÃÊœÌ ({fmt_price(balance)}  Ê„«‰)"
        kb.add(types.InlineKeyboardButton(bal_label,
                                          callback_data=f"addon:pay:{config_id}:{addon_type}:wallet"))

    # Card gateway
    if is_gateway_available("card", uid) and is_card_info_complete():
        lbl = setting_get("gw_card_display_name", "").strip() or "?? ò«—  »Â ò«— "
        kb.add(types.InlineKeyboardButton(lbl,
                                          callback_data=f"addon:pay:{config_id}:{addon_type}:card"))

    back_cb = f"addon:{'vol' if addon_type == 'volume' else 'time'}:{config_id}"
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=back_cb,
                                      icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(target, text, kb)


def _execute_addon_update(config_id, addon_type, sd, uid):
    """Apply volume/time addon to the panel client.
    Returns (True, None) or (False, user_friendly_error_str).
    """
    from ..db import get_panel_config as _gcfg, get_panel as _gpnl
    from ..panels.client import PanelClient
    cfg = _gcfg(config_id)
    if not cfg:
        return False, "ò«‰›Ìê Ì«›  ‰‘œ."
    panel = _gpnl(cfg["panel_id"])
    if not panel:
        return False, "Å‰· Ì«›  ‰‘œ."
    pc = PanelClient(
        protocol=panel["protocol"],
        host=panel["host"],
        port=panel["port"],
        path=panel.get("path") or "",
        username=panel["username"],
        password=panel["password"],
    )
    if addon_type == "volume":
        gb = float(sd.get("amount_gb", 0))
        ok, result = pc.add_client_volume(cfg["inbound_id"], cfg["client_uuid"], gb)
    else:
        days = int(sd.get("amount_days", 0))
        ok, result = pc.add_client_time(cfg["inbound_id"], cfg["client_uuid"], days)
    if not ok:
        _notify_panel_error(uid, None, f"addon_{addon_type}", str(result), config_id, cfg["panel_id"])
        return False, str(result)
    return True, None



    """
    Alert owner admins (ADMIN_IDS) and the error_log group topic
    when a panel config creation or delivery fails.
    """
    try:
        def _row_get(row, key, default="ø"):
            if row is None:
                return default
            try:
                return row[key] if key in row.keys() else default
            except Exception:
                return default
        pkg_name  = _row_get(package_row, "name")
        type_name = _row_get(package_row, "type_name")
        cfg_line  = f"\n?? panel_config_id: <code>{panel_config_id}</code>" if panel_config_id else ""

        # Try to get panel name
        panel_name = "‰«„‘Œ’"
        pid = panel_id or _row_get(package_row, "panel_id", None)
        if pid:
            try:
                _panel = get_panel(pid)
                if _panel:
                    panel_name = _panel["name"] or str(pid)
            except Exception:
                panel_name = str(pid)

        text = (
            "?? <b>« ’«· —»«  »« Å‰· ﬁÿ⁄ ‘œ</b>\n\n"
            f"?? Å‰·: <b>{esc(str(panel_name))}</b>\n"
            f"?? ò«—»—: <code>{uid}</code>\n"
            f"?? ‰Ê⁄: {esc(str(type_name))}\n"
            f"?? ÅòÌÃ: {esc(str(pkg_name))}\n"
            f"?? „—Õ·Â: {esc(stage)}"
            f"{cfg_line}\n\n"
            f"?? Ã“∆Ì« :\n<code>{esc(str(detail)[:600])}</code>"
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
                "?? <b>Å‰· œ— œ” —” ‰Ì”  ó »——”Ì « ’«· «œ«„Â œ«—œ</b>\n\n"
                f"?? Å‰·: {_label}\n"
                f"?? «œ„Ì‰: <code>{uid}</code>\n\n"
                "—»«  »ÂùÿÊ— ŒÊœò«— œ— Õ«·  ·«‘ „Ãœœ «” ."
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
                        "? Å‰· »Ì‘ «“ ? œﬁÌﬁÂ œ— œ” —” ‰Ì” . œ— ’Ê—  —›⁄ „‘ò· «œ«„Â „ÌùœÂÌ„Ö",
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
                          quantity, payment_id, service_names=None):
    """
    Deliver `quantity` configs to user after successful payment.
    Returns (delivered_purchase_ids, pending_ids).
    For panel packages, creates configs in the panel automatically.
    For manual packages, pulls from stock; creates pending_orders if no stock.
    `service_names`: optional list of pre-chosen names for panel configs.
    """
    from ..ui.notifications import deliver_purchase_message, admin_purchase_notify
    package_row   = get_package(package_id)
    unit_price    = max(0, total_amount // quantity) if quantity > 0 else total_amount

    # ?? Panel-based packages ??????????????????????????????????????????????????
    try:
        config_source = package_row["config_source"] or "manual"
    except (IndexError, KeyError):
        config_source = "manual"

    if config_source == "panel":
        panel_config_ids = []
        panel_client_names = []
        failed_count = 0
        for i in range(quantity):
            desired_name = (service_names[i] if service_names and i < len(service_names) else None)
            ok, result, pc_id, c_name = _create_panel_config(
                uid, package_id, payment_id, chat_id=chat_id, desired_name=desired_name
            )
            if ok:
                panel_config_ids.append(pc_id)
                panel_client_names.append(c_name or "")
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
                        "?? <b>Œÿ« œ—  ÕÊÌ· ”—ÊÌ”</b>\n\n"
                        "„ √”›«‰Â œ—  ÕÊÌ· ”—ÊÌ” „‘ò·Ì ÅÌ‘ ¬„œ Ê „»·€ »Â òÌ› ÅÊ· ‘„« »«“ê—œ«‰œÂ ‘œ.\n"
                        "·ÿ›« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ.",
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
                    stage="”«Œ  ò·«Ì‰  œ— Å‰·", detail=result,
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
                    stage=" ÕÊÌ· ò«‰›Ìê »Â ò«—»—",
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
                _svc_name = panel_client_names[0] if panel_client_names else None
                admin_purchase_notify(payment_method, get_user(uid), package_row,
                                      purchase_id=None, amount=unit_price, service_name=_svc_name)
            except Exception:
                pass
        # Debt notification: if user's balance is negative after purchase (used credit)
        try:
            _u_after = get_user(uid)
            if _u_after and _u_after["balance"] < 0:
                _debt = abs(_u_after["balance"])
                from ..helpers import fmt_price as _fp
                bot.send_message(
                    uid,
                    "?? <b>«ÿ·«⁄ÌÂ »œÂÌ</b>\n\n"
                    "„ÊÃÊœÌ ‘„« »Â Å«Ì«‰ —”ÌœÂ »Êœ Ê Â“Ì‰Â «Ì‰ ò«‰›Ìê «“ «⁄ »«— Ê‰ ò„ ‘œ.\n"
                    f"?? »œÂÌ ›⁄·Ì ‘„«: <b>{_fp(_debt)}</b>  Ê„«‰\n\n"
                    "·ÿ›« »« ‘«—é òÌ› ÅÊ· »œÂÌ ŒÊœ —« Å—œ«Œ  ò‰Ìœ. ”Å«” ??",
                    parse_mode="HTML",
                )
        except Exception:
            pass
        return panel_config_ids, []

    # ?? Manual / stock-based packages (original logic) ????????????????????????
    purchase_ids  = []
    pending_ids   = []

    for i in range(quantity):
        # Reserve one config at a time
        cfg_id = reserve_first_config(package_id)
        if not cfg_id:
            # No stock ó create a pending order for this slot
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
      2. The #fragment ó if cpkg['sample_client_name'] is non-empty and is found
         inside the decoded fragment, ONLY that substring is replaced with
         client_name, preserving any prefix / suffix (e.g. ??TUN_-NAME-main).
         If sample_client_name is empty or not found, the entire fragment is
         replaced with client_name (safe backward-compat fallback).

    Everything else (domain, port, path, host header, query params order, Ö)
    is taken verbatim from the template ó the panel IP is never used.
    """
    import re as _re
    import urllib.parse as _up

    # sqlite3.Row doesn't support .get() ó normalise to dict
    if not isinstance(cpkg, dict):
        cpkg = dict(cpkg)

    tmpl = (cpkg.get("sample_config") or "").strip()
    if not tmpl:
        return None

    _UUID_RE = _re.compile(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        _re.IGNORECASE
    )

    # Step 1: replace UUID (only first occurrence ó the one right after the scheme)
    config = _UUID_RE.sub(client_uuid, tmpl, count=1)

    # Step 2: replace the fragment while preserving template prefix/suffix
    if "#" in config:
        base_part, frag_encoded = config.rsplit("#", 1)
        frag_decoded = _up.unquote(frag_encoded)

        sample_name = (cpkg.get("sample_client_name") or "").strip()
        if sample_name and sample_name in frag_decoded:
            # Replace ONLY the sample name portion ó prefix/suffix stays intact
            new_frag = frag_decoded.replace(sample_name, client_name, 1)
        else:
            # Fallback: replace entire fragment
            new_frag = client_name

        # Re-encode so special chars (emojis, /, Ö) are preserved correctly
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
    # sqlite3.Row doesn't support .get() ó normalise to dict
    if not isinstance(cpkg, dict):
        cpkg = dict(cpkg)

    tmpl = (cpkg.get("sample_sub_url") or "").strip().rstrip("/")
    if not tmpl:
        return None

    # Replace the last path segment (the sub identifier)
    if "/" in tmpl:
        base = tmpl.rsplit("/", 1)[0]
        return f"{base}/{sub_id}"
    # Degenerate case ó just append
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

    # sqlite3.Row doesn't support .get() ó normalise to dict
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

        # ?? ExternalProxy (CDN / FluxTunnel / Cloudflare, etc.) ??????????????
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


def _create_panel_config(uid, package_id, payment_id, chat_id=None, desired_name=None):
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
        return False, "ÅòÌÃ Ì«›  ‰‘œ", None

    try:
        panel_id      = package_row["panel_id"]
        panel_inbound = int(package_row["panel_port"] or 0)   # stored as inbound ID
        delivery_mode = package_row["delivery_mode"] or "config_only"
        panel_type    = package_row["panel_type"] or "sanaei"
        cpkg_id       = package_row["client_package_id"] if "client_package_id" in package_row.keys() else None
    except (IndexError, KeyError):
        return False, "«ÿ·«⁄«  Å‰· ÅòÌÃ ‰«ﬁ’ «” ", None

    if not panel_id or not panel_inbound:
        return False, "Å‰· Ì« ‘„«—Â «Ì‰»«‰œ ÅòÌÃ  ‰ŸÌ„ ‰‘œÂ", None

    panel = get_panel(panel_id)
    if not panel:
        return False, "Å‰· „— »ÿ Ì«›  ‰‘œ", None

    # Load client package template ó first try explicit link, then auto-detect by panel+inbound
    cpkg = get_panel_client_package(cpkg_id) if cpkg_id else None
    if not cpkg:
        cpkg = get_panel_client_package_by_inbound(panel_id, panel_inbound)
    # sqlite3.Row doesn't support .get() ó normalise to dict
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

    # ?? Connection-error detector ?????????????????????????????????????????????
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
                    "? <b>”—Ê— Å‰· œ— Õ«· Õ«÷— œ— œ” —” ‰Ì” </b>\n\n"
                    "”›«—‘ ‘„« œ— ’› «‰ Ÿ«— ﬁ—«— ê—› . "
                    "»Â „Õ÷ »«“ê‘  « ’«·° ”—ÊÌ” ‘„« ”«Œ Â Ê  ÕÊÌ· œ«œÂ „Ìù‘Êœ.",
                    parse_mode="HTML",
                )
                _waiting_notified = True
                _last_periodic = now
            except Exception:
                pass
        elif now - _last_periodic >= PERIODIC_INTERVAL:
            try:
                bot.send_message(chat_id, "? Â‰Ê“ œ— Õ«·  ·«‘ »—«Ì « ’«· »Â Å‰·...",
                                 parse_mode="HTML")
                _last_periodic = now
            except Exception:
                pass

    def _notify_reconnected():
        if _waiting_notified and chat_id:
            try:
                bot.send_message(chat_id, "? « ’«· »Â Å‰· »—ﬁ—«— ‘œ° œ— Õ«· ”«Œ  ”—ÊÌ”...",
                                 parse_mode="HTML")
            except Exception:
                pass

    # ?? Step 1: login ?????????????????????????????????????????????????????????
    login_err = None
    _t0 = time.time()
    while True:
        if time.time() - _t_start > MAX_WAIT:
            login_err = "Õœ«òÀ— “„«‰ «‰ Ÿ«— (8 ”«⁄ )  „«„ ‘œ"
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
        return False, f"« ’«· »Â Å‰· ‰«„Ê›ﬁ: {login_err}", None

    # ?? Step 2: fetch inbound ?????????????????????????????????????????????????
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
        # find_inbound doesn't return an error string ó re-login to check connectivity
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
        return False, f"«Ì‰»«‰œ »« ‘„«—Â {panel_inbound} œ— Å‰· Ì«›  ‰‘œ", None

    inbound_id     = inbound["id"]
    real_port      = int(inbound.get("port") or 0)
    inbound_remark = (inbound.get("remark") or inbound.get("tag") or "").strip()

    # Generate config name: use desired_name if provided, else full random
    if desired_name:
        client_name = desired_name
    else:
        client_name = generate_random_name()

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

    # ?? Step 3: create client ?????????????????????????????????????????????????
    result = None
    create_err = None
    _t0 = time.time()
    _dup_retries = 0          # counts non-connection-error retries with a desired name
    _MAX_DUP_RETRIES = 3      # after this many suffix attempts, fall back to full random
    while True:
        if time.time() - _t_start > MAX_WAIT:
            create_err = "Õœ«òÀ— “„«‰ «‰ Ÿ«— (8 ”«⁄ )  „«„ ‘œ"
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
            # Rotate client name to avoid duplicate key conflicts on retry.
            # If a desired name was provided, try up to _MAX_DUP_RETRIES times
            # with a "name-xx" suffix; then fall back to a fully random name.
            _dup_retries += 1
            if desired_name and _dup_retries <= _MAX_DUP_RETRIES:
                _suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=2))
                client_name = f"{desired_name}-{_suffix}"
                log.info("_create_panel_config: duplicate retry %d/%d, new name=%s",
                         _dup_retries, _MAX_DUP_RETRIES, client_name)
            else:
                client_name = generate_random_name()
                log.info("_create_panel_config: falling back to random name=%s (dup_retries=%d)",
                         client_name, _dup_retries)
            time.sleep(FUNC_RETRY_DELAY)
    if create_err is not None:
        return False, f"Œÿ« œ— ”«Œ  ò·«Ì‰ : {create_err}", None

    client_uuid, sub_id = result
    # Default sub URL from panel ó may be overridden by template below
    sub_url = client.get_sub_url(client_uuid)

    config_text = None

    # ?? Step 4a: Build config from client package template (preferred path) ??
    # Uses _build_config_from_template which:
    #   ï replaces ONLY the UUID in the URL body
    #   ï in the #fragment, replaces only cpkg['sample_client_name'] with
    #     client_name ó preserving emoji prefix / -main suffix etc.
    #   ï keeps domain, port, host header, path, query params from template
    if cpkg and cpkg["sample_config"]:
        config_text = _build_config_from_template(cpkg, client_uuid, client_name)
        log.info("_create_panel_config: built config from template for uid=%s", uid)

    # ?? Step 4b: Build sub URL from template (always, when available) ????????
    # NOT limited to sub_only/both ó the sub URL is stored in DB regardless of
    # delivery_mode and must be correct for future reference / re-renders.
    # The panel's path prefix (e.g. /emadhb/) is NEVER injected here.
    if cpkg and cpkg["sample_sub_url"]:
        sub_url = _build_sub_from_template(cpkg, sub_id) or sub_url

    # ?? Step 4c: Fetch from panel API (fallback when no config template) ?????
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

    # ?? Step 4d: Build from streamSettings (last fallback) ???????????????????
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

    return True, delivery_mode, pc_id, client_name


def _deliver_panel_config_to_user(chat_id, panel_config_id, package_row):
    """Send the panel-created config to the user based on delivery_mode."""
    from ..db import get_panel_config
    from ..helpers import fmt_vol, fmt_dur

    pc = get_panel_config(panel_config_id)
    if not pc:
        log.error("[PANEL_DELIVERY] panel_config %s not found in DB", panel_config_id)
        _notify_panel_error(
            uid=chat_id, package_row=package_row,
            stage=" ÕÊÌ· ò«‰›Ìê ó —òÊ—œ œ— œÌ «»Ì” Ì«›  ‰‘œ",
            detail=f"panel_config_id={panel_config_id}",
            panel_config_id=panel_config_id,
        )
        try:
            bot.send_message(chat_id,
                "?? <b>Œÿ« œ—  ÕÊÌ· ”—ÊÌ”</b>\n\n"
                "„ √”›«‰Â œ—  ÕÊÌ· ”—ÊÌ” „‘ò·Ì ÅÌ‘ ¬„œ.\n"
                "·ÿ›« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ.",
                parse_mode="HTML")
        except Exception:
            pass
        return

    # ?? Pull raw values first (needed for emergency fallback) ?????????????????
    raw_config_text = pc["client_config_text"] or ""
    raw_sub_url     = pc["client_sub_url"] or ""

    try:
        _deliver_panel_config_inner(chat_id, panel_config_id, package_row, pc)
    except Exception as _inner_exc:
        # Something went wrong in the rendering/QR path ó send plain-text fallback
        log.error("[PANEL_DELIVERY] inner delivery failed for pc=%s: %s", panel_config_id, _inner_exc, exc_info=True)
        _notify_panel_error(
            uid=chat_id, package_row=package_row,
            stage=" ÕÊÌ· ò«‰›Ìê ó Œÿ«Ì œ«Œ·Ì —‰œ—Ì‰ê",
            detail=str(_inner_exc),
            panel_config_id=panel_config_id,
        )
        # Emergency plain-text fallback ó send the config to user without formatting
        try:
            fallback_lines = ["?? <b>”—ÊÌ” ‘„« ¬„«œÂ «” !</b>\n"]
            if raw_config_text.strip():
                fallback_lines.append(f"?? <b>Config:</b>\n<code>{esc(raw_config_text)}</code>")
            if raw_sub_url.strip():
                fallback_lines.append(f"?? <b>·Ì‰ò ”«»:</b>\n{esc(raw_sub_url)}")
            if raw_config_text.strip() or raw_sub_url.strip():
                kb_back = types.InlineKeyboardMarkup()
                kb_back.add(types.InlineKeyboardButton("?? »«“ê‘ ", callback_data="nav:main"))
                bot.send_message(chat_id, "\n\n".join(fallback_lines),
                                 parse_mode="HTML", reply_markup=kb_back)
        except Exception as _fb_exc:
            log.error("[PANEL_DELIVERY] even fallback failed for pc=%s: %s", panel_config_id, _fb_exc)


def _deliver_panel_config_inner(chat_id, panel_config_id, package_row, pc):
    """Inner delivery ó builds message with premium emoji + QR and sends it."""
    from ..helpers import fmt_vol, fmt_dur
    import io as _io
    import qrcode as _qrcode
    from ..ui.premium_emoji import ce

    try:
        delivery_mode = package_row["delivery_mode"] or "config_only"
    except (IndexError, KeyError):
        delivery_mode = "config_only"

    vol_label  = "‰«„ÕœÊœ" if not package_row["volume_gb"]     else fmt_vol(package_row["volume_gb"])
    dur_label  = "‰«„ÕœÊœ" if not package_row["duration_days"] else fmt_dur(package_row["duration_days"])
    max_u      = package_row["max_users"] if "max_users" in (package_row.keys() if hasattr(package_row, "keys") else {}) else 0
    users_label = "‰«„ÕœÊœ" if not max_u else (
        " òùò«—»—Â" if max_u == 1 else f"{max_u} ò«—»—Â"
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
    pkg_line      = f"{ce('??', '5258134813302332906')} ÅòÌÃ: <b>{esc(package_row['name'])}</b>\n" if show_pkg else ""
    _expire_at    = pc["expire_at"] if "expire_at" in pc.keys() else ""
    expire_line   = f"{ce('??', '5379748062124056162')} «‰ﬁ÷«: <b>{_expire_at[:10]}</b>\n" if _expire_at else ""

    header = f"{ce('?', '5260463209562776385')} <b>”—ÊÌ” ‘„« ¬„«œÂ «” !</b>"

    info_block = (
        f"{ce('??', '5361837567463399422')} ‰«„ ”—ÊÌ”: <b>{esc(service_name)}</b>\n"
        f"{ce('??', '5463224921935082813')} ‰Ê⁄ ”—ÊÌ”: <b>{esc(type_label)}</b>\n"
        f"{pkg_line}"
        f"{ce('??', '5924538142198600679')} ÕÃ„: <b>{esc(vol_label)}</b>\n"
        f"{ce('?', '5343724178547691280')} „œ : <b>{esc(dur_label)}</b>\n"
        f"{ce('??', '5372926953978341366')}  ⁄œ«œ ò«—»—: <b>{esc(users_label)}</b>\n"
        f"{expire_line}"
    )

    has_cfg     = bool(config_text.strip())
    has_sub     = bool(sub_url.strip())

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("?? »«“ê‘ ", callback_data="nav:main"))

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
            f"?? <b>Œÿ« œ—  ÕÊÌ· ”—ÊÌ”:</b> {esc(reason)}\n"
            "·ÿ›« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ.",
            parse_mode="HTML", reply_markup=kb)
        _notify_panel_error(
            uid=chat_id,
            package_row=package_row,
            stage=" ÕÊÌ· ò«‰›Ìê ó „Õ Ê« Ì«›  ‰‘œ",
            detail=f"{reason} | config_id={panel_config_id} | mode={delivery_mode}",
            panel_config_id=panel_config_id,
        )

    if delivery_mode == "config_only":
        if has_cfg:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('??', '5900197669178970457')} <b>Config:</b>\n<code>{esc(config_text)}</code>"
            )
            _send_with_qr(config_text, text)
        else:
            _fail_no_content("ò«‰›Ìê œ— œ” —” ‰Ì” ")

    elif delivery_mode == "sub_only":
        if has_sub:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('??', '5271604874419647061')} <b>·Ì‰ò ”«»:</b>\n{esc(sub_url)}"
            )
            _send_with_qr(sub_url, text)
        else:
            _fail_no_content("·Ì‰ò ”«» œ— œ” —” ‰Ì” ")

    else:  # both
        if has_cfg and has_sub:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('??', '5900197669178970457')} <b>Config:</b>\n<code>{esc(config_text)}</code>\n\n"
                f"{ce('??', '5271604874419647061')} <b>·Ì‰ò ”«»:</b>\n{esc(sub_url)}"
            )
            _send_with_qr(config_text, text)  # QR for config when both present
        elif has_cfg:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('??', '5900197669178970457')} <b>Config:</b>\n<code>{esc(config_text)}</code>"
            )
            _send_with_qr(config_text, text)
        elif has_sub:
            text = (
                f"{header}\n\n{info_block}\n"
                f"{ce('??', '5271604874419647061')} <b>·Ì‰ò ”«»:</b>\n{esc(sub_url)}"
            )
            _send_with_qr(sub_url, text)
        else:
            _fail_no_content("ò«‰›Ìê Ê ”«» Â— œÊ œ— œ” —” ‰Ì” ‰œ")



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
                    "?? <b>„‘ò· œ—  ÕÊÌ· ”—ÊÌ” Å‰·</b>\n\n"
                    "·ÿ›« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ.",
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
                    f"?? <b>Œ—Ìœ ‘„« »« „Ê›ﬁÌ  «‰Ã«„ ‘œ!</b>\n\n"
                    f"??  ⁄œ«œ ò«‰›ÌêùÂ«Ì ¬„«œÂ: <b>{len(purchase_ids)}</b> «“ <b>{total}</b>\n\n"
                    "?? ò«‰›ÌêùÂ«Ì ‘„« ÌòÌùÌòÌ œ— ÅÌ«„ùÂ«Ì »⁄œÌ «—”«· „Ìù‘Ê‰œ.",
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
                f"?? <b>»Œ‘Ì «“ ”›«—‘ œ— «‰ Ÿ«—  √„Ì‰ „ÊÃÊœÌ</b>\n\n"
                f"? {len(purchase_ids)} ò«‰›Ìê  ÕÊÌ· œ«œÂ ‘œ.\n"
                f"? {count_pending} ò«‰›Ìê œÌê— œ— ’› «‰ Ÿ«— ﬁ—«— ê—› .\n\n"
                "»Âù„Õ÷  √„Ì‰ „ÊÃÊœÌ° ò«‰›ÌêùÂ«Ì »«ﬁÌ„«‰œÂ »Âù’Ê—  ŒÊœò«— «—”«· „Ìù‘Ê‰œ.\n"
                "?? «“ ’»— ‘„« „ ‘ò—Ì„.",
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

    # Debt notification: if user's balance is negative after purchase (used credit)
    if purchase_ids:
        try:
            _u_after = get_user(uid)
            if _u_after and _u_after["balance"] < 0:
                _debt = abs(_u_after["balance"])
                bot.send_message(
                    uid,
                    "?? <b>«ÿ·«⁄ÌÂ »œÂÌ</b>\n\n"
                    "„ÊÃÊœÌ ‘„« »Â Å«Ì«‰ —”ÌœÂ »Êœ Ê Â“Ì‰Â «Ì‰ ò«‰›Ìê «“ «⁄ »«— Ê‰ ò„ ‘œ.\n"
                    f"?? »œÂÌ ›⁄·Ì ‘„«: <b>{fmt_price(_debt)}</b>  Ê„«‰\n\n"
                    "·ÿ›« »« ‘«—é òÌ› ÅÊ· »œÂÌ ŒÊœ —« Å—œ«Œ  ò‰Ìœ. ”Å«” ??",
                    parse_mode="HTML",
                )
        except Exception:
            pass


# ?? Voucher helpers ????????????????????????????????????????????????????????????
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
        f"?? {esc(bank or 'À»  ‰‘œÂ')}\n"
        f"?? {esc(owner or 'À»  ‰‘œÂ')}\n"
        f"?? <code>{esc(card)}</code>\n\n"
    )

    if is_random:
        amount_rial = display_amount * 10
        text = (
            "?? <b>ò«—  »Â ò«— </b>\n\n"
            f"{card_info}"
            "??????????????????\n"
            f"?? <b>„»·€ ﬁ«»· Å—œ«Œ </b>\n"
            f"<b>{fmt_price(display_amount)}  Ê„«‰</b>\n\n"
            "?? <b>Õ „« „»·€ —« œﬁÌﬁ« »Â Â„Ì‰ „ﬁœ«— Ê«—Ì“ ‰„«ÌÌœ.\n"
            "œ— ’Ê—  Ê«—Ì“ „»·€ €Ì— œﬁÌﬁ° „”∆Ê·Ì   «ÌÌœ ‰‘œ‰ —”Ìœ »— ⁄ÂœÂ ŒÊœ ‘„« ŒÊ«Âœ »Êœ.</b>\n\n"
            "?? Å” «“ Ê«—Ì“°  ’ÊÌ— —”Ìœ —« «—”«· ò‰Ìœ."
        )
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("?? òÅÌ ﬁÌ„  »Â  Ê„«‰",
                                       copy_text=types.CopyTextButton(text=str(display_amount))),
            types.InlineKeyboardButton("?? òÅÌ ﬁÌ„  »Â —Ì«·",
                                       copy_text=types.CopyTextButton(text=str(amount_rial))),
        )
        kb.add(types.InlineKeyboardButton("?? òÅÌ ‘„«—Â ò«— ",
                                          copy_text=types.CopyTextButton(text=card_clean)))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
    else:
        text = (
            "?? <b>ò«—  »Â ò«— </b>\n\n"
            f"·ÿ›« „»·€ <b>{fmt_price(price)}</b>  Ê„«‰ —« »Â ò«—  “Ì— Ê«—Ì“ ò‰Ìœ:\n\n"
            f"{card_info}"
            "?? Å” «“ Ê«—Ì“°  ’ÊÌ— —”Ìœ —« «—”«· ò‰Ìœ."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))

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
        bot.answer_callback_query(call.id, "œ” Â Ì«›  ‰‘œ.", show_alert=True)
        return
    codes = get_voucher_codes_for_batch(batch_id)
    used_count  = batch["used_count"]
    total_count = batch["total_count"]
    remain      = total_count - used_count
    gift_fa = f"{fmt_price(batch['gift_amount'])}  Ê„«‰" if batch["gift_type"] == "wallet" else "ò«‰›Ìê"
    if batch["gift_type"] == "config" and batch["package_id"]:
        pkg = get_package(batch["package_id"])
        if pkg:
            gift_fa = f"ò«‰›Ìê: {esc(pkg['name'])} | {fmt_vol(pkg['volume_gb'])} | {fmt_dur(pkg['duration_days'])}"
    text = (
        f"?? <b>ò«—  ÂœÌÂ: {esc(batch['name'])}</b>\n\n"
        f"?? ‰Ê⁄ ÂœÌÂ: {gift_fa}\n"
        f"?? ò·: {total_count} | «” ›«œÂ ‘œÂ: {used_count} | „«‰œÂ: {remain}\n"
        f"?? «ÌÃ«œ: {batch['created_at'][:16]}\n\n"
        "?????????????????????\n"
    )
    code_lines = []
    for vc in codes:
        if vc["is_used"]:
            used_time = (vc["used_at"] or "")[:16]
            code_lines.append(
                f"? <code>{vc['code']}</code>\n"
                f"   ?? <code>{vc['used_by']}</code>  ?? {used_time}"
            )
        else:
            code_lines.append(f"? <code>{vc['code']}</code>")
    # Telegram message limit 4096 chars ó split if needed
    MAX_MSG = 3800
    full_codes_text = "\n".join(code_lines)
    combined = text + full_codes_text
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("?? Õ–› «Ì‰ œ” Â", callback_data=f"admin:vch:del:{batch_id}"),
    )
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:vouchers", icon_custom_emoji_id="5253997076169115797"))
    if len(combined) <= MAX_MSG:
        send_or_edit(call, combined, kb)
    else:
        # Send header + buttons first, then codes in a follow-up message
        send_or_edit(call, text + "(òœÂ« œ— ÅÌ«„ »⁄œÌ)", kb)
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
    toggle_lbl = "? ò«—  ÂœÌÂ: ›⁄«·" if enabled else "? ò«—  ÂœÌÂ: €Ì—›⁄«·"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data="admin:vch:toggle_global"),
        types.InlineKeyboardButton("? «›“Êœ‰ ò«—  ÂœÌÂ", callback_data="admin:vch:add"),
    )
    for b in batches:
        used  = b["used_count"]
        total = b["total_count"]
        remain = total - used
        kb.row(
            types.InlineKeyboardButton(f"?? {b['name']} ({remain}/{total})", callback_data=f"admin:vch:view:{b['id']}"),
            types.InlineKeyboardButton("?? «ÿ·«⁄« ", callback_data=f"admin:vch:view:{b['id']}"),
        )
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
    text = (
        "?? <b>„œÌ—Ì  ò«— ùÂ«Ì ÂœÌÂ</b>\n\n"
        f"Ê÷⁄Ì  ”Ì” „: {'? ›⁄«·' if enabled else '? €Ì—›⁄«·'}\n"
        f" ⁄œ«œ œ” ÂùÂ«: {len(batches)}\n\n"
        + ("œ” Âù«Ì À»  ‰‘œÂ «” ." if not batches else "»—«Ì „‘«ÂœÂ Ã“∆Ì«  —ÊÌ Â— œ” Â ò·Ìò ò‰Ìœ:")
    )
    send_or_edit(call, text, kb)


def _build_locked_channels_menu():
    """Build the locked-channels admin panel text+keyboard. Returns (text, kb)."""
    rows = get_locked_channels()
    kb = types.InlineKeyboardMarkup()
    # Add button at the top
    kb.add(types.InlineKeyboardButton("? «›“Êœ‰ ò«‰«·/ê—ÊÂ ÃœÌœ", callback_data="adm:lch:add"))
    # Two-column rows: channel name (right) | delete (left)
    for row in rows:
        ch = row["channel_id"]
        label = ch if ch.startswith("@") else f"?? {ch}"
        kb.row(
            types.InlineKeyboardButton(f"?? {label}", callback_data="noop"),
            types.InlineKeyboardButton("?? Õ–›", callback_data=f"adm:lch:del:{row['id']}"),
        )
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings",
                                      icon_custom_emoji_id="5253997076169115797"))
    legacy = setting_get("channel_id", "").strip()
    legacy_note = f"\n?? ò«‰«· ﬁœÌ„Ì ( ‰ŸÌ„« ): <code>{esc(legacy)}</code>" if legacy else ""
    text = (
        "?? <b>„œÌ—Ì  ò«‰«·ùÂ«Ì «Ã»«—Ì / ﬁ›·</b>\n\n"
        "—»«   ‰Â« “„«‰Ì «Ã«“Â Ê—Êœ „ÌùœÂœ òÂ ò«—»— œ— <b>Â„Â</b> ò«‰«·ùÂ«Ì “Ì— ⁄÷Ê »«‘œ.\n\n"
        f" ⁄œ«œ ò«‰«·ùÂ«Ì ›⁄«·: <b>{len(rows)}</b>{legacy_note}"
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
    log_admin_action(uid, f"—œ Â„Â —”ÌœÂ«: {rejected_count} —”Ìœ —œ ‘œ")
    if call.id:
        bot.answer_callback_query(call.id, f"? {rejected_count} —”Ìœ —œ ‘œ.", show_alert=True)
    else:
        bot.send_message(uid, f"? {rejected_count} —”Ìœ —œ ‘œ.", parse_mode="HTML")
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
                    msg = f"? —”Ìœ Å—œ«Œ  ‘„« —œ ‘œ.\n\n?? œ·Ì·: {custom_note}"
                else:
                    msg = "? —”Ìœ Å—œ«Œ  ‘„«  Ê”ÿ «œ„Ì‰ —œ ‘œ."
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
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "? —”Ìœ »——”Ì ‰‘œÂù«Ì ÊÃÊœ ‰œ«—œ.", kb)
        return
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    KIND = {"wallet_charge": "‘«—é òÌ›ùÅÊ·", "buy": "Œ—Ìœ", "renew": " „œÌœ",
            "renewal": " „œÌœ", "pnlcfg_renewal": " „œÌœ (Å‰·)", "config_purchase": "Œ—Ìœ"}
    header = (
        f"?? <b>—”ÌœÂ«Ì »——”Ì ‰‘œÂ</b>\n"
        f"’›ÕÂ {page + 1} «“ {total_pages} |  ⁄œ«œ ò·: {total}\n"
        "?????????????????????????????\n"
    )
    lines = []
    kb = types.InlineKeyboardMarkup(row_width=3)
    for i, r in enumerate(rows, start=1):
        t_str    = r.get("created_at") or ""
        date_part = t_str[:10] if len(t_str) >= 10 else ""
        time_part = t_str[11:16] if len(t_str) >= 16 else ""
        kind_lbl = KIND.get(r.get("kind", ""), r.get("kind", ""))
        lines.append(
            f"{i}. ?? {date_part} {time_part} | {kind_lbl} | ?? {fmt_price(r['amount'])}  Ê„«‰"
        )
        kb.row(
            types.InlineKeyboardButton(f"?? #{i} »Ì‘ —", callback_data=f"admin:pr:det:{r['id']}:{page}"),
            types.InlineKeyboardButton("?",              callback_data=f"admin:pr:ap:{r['id']}:{page}"),
            types.InlineKeyboardButton("?",              callback_data=f"admin:pr:rj:{r['id']}:{page}"),
        )
    text = header + "\n".join(lines)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("?? ﬁ»·Ì", callback_data=f"admin:pr:list:{page - 1}"))
    if (page + 1) < total_pages:
        nav.append(types.InlineKeyboardButton("»⁄œÌ ??", callback_data=f"admin:pr:list:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("? —œ ò—œ‰ Â„Â", callback_data="admin:pr:reject_all"))
    kb.add(types.InlineKeyboardButton("??? »«“ê‘ ", callback_data="admin:panel"))
    send_or_edit(call, text, kb)


def _render_discount_admin_list(call, uid):
    """Render the admin discount codes management panel."""
    codes = get_all_discount_codes()
    enabled = setting_get("discount_codes_enabled", "0") == "1"
    toggle_lbl = "? òœ  Œ›Ì›: ›⁄«·" if enabled else "? òœ  Œ›Ì›: €Ì—›⁄«·"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data="admin:disc:toggle_global"),
        types.InlineKeyboardButton("? «›“Êœ‰ òœ", callback_data="admin:disc:add"),
    )
    for row in codes:
        status_icon = "?" if row["is_active"] else "?"
        audience = row["audience"] if "audience" in row.keys() else "all"
        aud_icon = {"all": "??", "public": "??", "agents": "??"}.get(audience, "??")
        kb.row(
            types.InlineKeyboardButton(f"{status_icon} {aud_icon} {row['code']}", callback_data=f"admin:disc:view:{row['id']}"),
            types.InlineKeyboardButton("??  ‰ŸÌ„« ", callback_data=f"admin:disc:view:{row['id']}"),
        )
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
    total = len(codes)
    text = (
        "?? <b>„œÌ—Ì  òœÂ«Ì  Œ›Ì›</b>\n\n"
        f"Ê÷⁄Ì  ”Ì” „: {'? ›⁄«·' if enabled else '? €Ì—›⁄«·'}\n"
        f" ⁄œ«œ òœÂ«: {total}\n\n"
        + ("òœÌ À»  ‰‘œÂ «” ." if not codes else "»—«Ì „œÌ—Ì  Â— òœ° —ÊÌ ¬‰ ò·Ìò ò‰Ìœ:")
    )
    send_or_edit(call, text, kb)


_AUDIENCE_LABELS = {
    "all":     "?? Â„Â",
    "public":  "?? ›ﬁÿ ⁄„Ê„",
    "agents":  "?? ›ﬁÿ ‰„«Ì‰œê«‰",
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
        title = "?? «‰ Œ«» ‰Ê⁄ùÂ«Ì „Ã«“"
        for item in items:
            check = "?" if item["id"] in selected else "?"
            kb.add(types.InlineKeyboardButton(
                f"{check} {item['name']}",
                callback_data=f"{toggle_cb}:{item['id']}"
            ))
    else:
        items = get_packages(include_inactive=True)
        title = "?? «‰ Œ«» ÅòÌÃùÂ«Ì „Ã«“"
        for item in items:
            check = "?" if item["id"] in selected else "?"
            kb.add(types.InlineKeyboardButton(
                f"{check} {item['type_name']} ó {item['name']}",
                callback_data=f"{toggle_cb}:{item['id']}"
            ))
    sel_count = len(selected)
    if sel_count > 0:
        kb.add(types.InlineKeyboardButton(f"?  √ÌÌœ ({sel_count} „Ê—œ «‰ Œ«»Ì)", callback_data=confirm_cb))
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=back_cb, icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, f"?? <b>{title}</b>\n\n„Ê«—œ „Ê—œ ‰Ÿ— —« «‰ Œ«» Ê ”Å”  √ÌÌœ ò‰Ìœ:", kb)


def _render_discount_code_detail(call, uid, code_id):
    """Render detail page for a single discount code."""
    row = get_discount_code(code_id)
    if not row:
        bot.answer_callback_query(call.id, "òœ  Œ›Ì› ÅÌœ« ‰‘œ.", show_alert=True)
        return
    disc_type_fa = "œ—’œ" if row["discount_type"] == "pct" else "„»·€ À«» "
    disc_val_fa = f"{row['discount_value']}?" if row["discount_type"] == "pct" else f"{fmt_price(row['discount_value'])}  Ê„«‰"
    max_total = str(row["max_uses_total"]) if row["max_uses_total"] > 0 else "‰«„ÕœÊœ"
    max_per = str(row["max_uses_per_user"]) if row["max_uses_per_user"] > 0 else "‰«„ÕœÊœ"
    actual_uses = row["actual_uses"]
    status_fa = "? ›⁄«·" if row["is_active"] else "? €Ì—›⁄«·"
    toggle_lbl = "? €Ì—›⁄«· ò‰" if row["is_active"] else "? ›⁄«· ò‰"
    audience = row["audience"] if "audience" in row.keys() else "all"
    audience_fa = _AUDIENCE_LABELS.get(audience, "?? Â„Â")
    scope_type = row["scope_type"] if "scope_type" in row.keys() else "all"
    _SCOPE_LABELS = {"all": "?? Â„Â ÅòÌÃùÂ«", "types": "?? ‰Ê⁄ùÂ«Ì Œ«’", "packages": "?? ÅòÌÃùÂ«Ì Œ«’"}
    scope_fa = _SCOPE_LABELS.get(scope_type, "?? Â„Â ÅòÌÃùÂ«")
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
        f"?? <b>òœ  Œ›Ì›: {esc(row['code'])}</b>\n\n"
        f"?? ‰Ê⁄  Œ›Ì›: {disc_type_fa} ó {disc_val_fa}\n"
        f"?? «” ›«œÂ ‘œÂ: {actual_uses} / {max_total}\n"
        f"?? Â— ò«—»—: {max_per} »«—\n"
        f"?? œ” —”Ì: {audience_fa}\n"
        f"?? „ÕœÊœÂ: {scope_fa}\n"
        f"?? Ê÷⁄Ì : {status_fa}\n"
        f"?? «ÌÃ«œ: {row['created_at'][:10]}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data=f"admin:disc:toggle:{code_id}"),
        types.InlineKeyboardButton("?? Õ–›", callback_data=f"admin:disc:del:{code_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("?? ÊÌ—«Ì‘ òœ", callback_data=f"admin:disc:edit_code:{code_id}"),
        types.InlineKeyboardButton("?? „ﬁœ«—  Œ›Ì›", callback_data=f"admin:disc:edit_val:{code_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("?? ò· «” ›«œÂ", callback_data=f"admin:disc:edit_total:{code_id}"),
        types.InlineKeyboardButton("?? Â— ò«—»—", callback_data=f"admin:disc:edit_per:{code_id}"),
    )
    kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ œ” —”Ì", callback_data=f"admin:disc:edit_audience:{code_id}"))
    kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ „ÕœÊœÂ", callback_data=f"admin:disc:edit_scope:{code_id}"))
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:discounts", icon_custom_emoji_id="5253997076169115797"))
    send_or_edit(call, text, kb)





# ?? Module-level helper: build package edit panel text + keyboard ????????????
def _pkg_edit_text_kb(package_row):
    _BR_LABELS = {"all": "Â„Â", "agents": "›ﬁÿ ‰„«Ì‰œê«‰", "public": "›ﬁÿ ò«—»—«‰ ⁄«œÌ", "nobody": "ÂÌçùò” (›ﬁÿ ÂœÌÂ)"}
    _DM_LABELS = {"config_only": "›ﬁÿ ò«‰›Ìê", "sub_only": "›ﬁÿ ”«»", "both": "ò«‰›Ìê + ”«»"}
    package_id    = package_row["id"]
    show_name_val = package_row["show_name"] if "show_name" in package_row.keys() else 1
    show_name_lbl = "?? ‰„«Ì‘ ‰«„ »Â ò«—»—: ? »·Â" if show_name_val else "?? ‰„«Ì‘ ‰«„ »Â ò«—»—: ? ŒÌ—"
    pkg_active    = package_row["active"] if "active" in package_row.keys() else 1
    pkg_status_label = "? ›⁄«· ó ò·Ìò »—«Ì €Ì—›⁄«·" if pkg_active else "? €Ì—›⁄«· ó ò·Ìò »—«Ì ›⁄«·"
    buyer_role    = package_row["buyer_role"] if "buyer_role" in package_row.keys() else "all"
    br_label      = _BR_LABELS.get(buyer_role, "Â„Â")
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
    kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ ‰«„",   callback_data=f"admin:pkg:ef:name:{package_id}"))
    kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ ﬁÌ„ ",  callback_data=f"admin:pkg:ef:price:{package_id}"))
    kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ ÕÃ„",   callback_data=f"admin:pkg:ef:volume:{package_id}"))
    kb.add(types.InlineKeyboardButton("? ÊÌ—«Ì‘ „œ ",   callback_data=f"admin:pkg:ef:dur:{package_id}"))
    kb.add(types.InlineKeyboardButton("?? Ã«Ìê«Â ‰„«Ì‘",  callback_data=f"admin:pkg:ef:position:{package_id}"))
    kb.add(types.InlineKeyboardButton("?? „ÕœÊœÌ  ò«—»—", callback_data=f"admin:pkg:ef:maxusers:{package_id}"))
    kb.add(types.InlineKeyboardButton(show_name_lbl,      callback_data=f"admin:pkg:toggle_sn:{package_id}"))
    kb.add(types.InlineKeyboardButton(f"?? Œ—Ìœ«—«‰: {br_label} ó  €ÌÌ—", callback_data=f"admin:pkg:set_br:{package_id}"))
    src_lbl = "À»  œ” Ì" if config_source == "manual" else f"Å‰· #{panel_id} «Ì‰»«‰œ {panel_port}"
    kb.add(types.InlineKeyboardButton(f"?? „‰»⁄ ò«‰›Ìê: {src_lbl} ó  €ÌÌ—", callback_data=f"admin:pkg:src:{package_id}"))
    kb.add(types.InlineKeyboardButton(pkg_status_label, callback_data=f"admin:pkg:toggleactive:{package_id}"))
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:types", icon_custom_emoji_id="5253997076169115797"))
    cur_pos      = package_row["position"] if "position" in package_row.keys() else 0
    pkg_status_line = "? ›⁄«·" if pkg_active else "? €Ì—›⁄«·"
    sn_line      = "? »·Â" if show_name_val else "? ŒÌ—"
    mu_val       = package_row["max_users"] if "max_users" in package_row.keys() else 0
    mu_line      = "‰«„ÕœÊœ" if not mu_val else f"{mu_val} ò«—»—Â"
    if config_source == "panel":
        src_info = f"Å‰· #{panel_id} | «Ì‰»«‰œ {panel_port} | {_DM_LABELS.get(delivery_mode, delivery_mode)}"
    else:
        src_info = "À»  œ” Ì"
    text = (
        f"?? <b>ÊÌ—«Ì‘ ÅòÌÃ</b>\n\n"
        f"‰«„: {esc(package_row['name'])}\n"
        f"ﬁÌ„ : {fmt_price(package_row['price'])}  Ê„«‰\n"
        f"ÕÃ„: {fmt_vol(package_row['volume_gb'])}\n"
        f"„œ : {fmt_dur(package_row['duration_days'])}\n"
        f"Ã«Ìê«Â: {cur_pos}\n"
        f"„ÕœÊœÌ  ò«—»—: {mu_line}\n"
        f"‰„«Ì‘ ‰«„ »Â ò«—»—: {sn_line}\n"
        f"Œ—Ìœ«—«‰ „Ã«“: {br_label}\n"
        f"„‰»⁄ ò«‰›Ìê: {src_info}\n"
        f"Ê÷⁄Ì : {pkg_status_line}"
    )
    return text, kb


# ?? Per-admin search cache for user config list ????????????????????????????????
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
    kb.add(types.InlineKeyboardButton("? «›“Êœ‰ ò«‰›Ìê", callback_data=f"adm:usr:acfg:{target_id}"))

    if active_search:
        q_display = active_search[:18] + ("Ö" if len(active_search) > 18 else "")
        kb.row(
            types.InlineKeyboardButton(f"?? {q_display}", callback_data=f"adm:usr:cfgsrch:{target_id}"),
            types.InlineKeyboardButton("? Å«ò ò—œ‰", callback_data=f"adm:usr:cfgclr:{target_id}"),
        )
    else:
        kb.add(types.InlineKeyboardButton("?? Ã” ùÊÃÊ", callback_data=f"adm:usr:cfgsrch:{target_id}"))

    for item in items:
        expired_mark = " ?" if item["is_expired"] else ""
        svc = urllib.parse.unquote(item["service_name"] or "")
        kb.add(types.InlineKeyboardButton(
            f"{svc}{expired_mark}",
            callback_data=f"adm:usrcfg:{target_id}:{item['config_id']}"
        ))

    for pc in panel_items:
        if pc["is_expired"]:
            marker = " ?"
        elif int(pc["is_disabled"] or 0):
            marker = " ?"
        else:
            marker = ""
        name = pc["client_name"] or pc["package_name"] or f"#{pc['id']}"
        kb.add(types.InlineKeyboardButton(
            f"?? {name}{marker}",
            callback_data=f"adm:usrpcfg:{target_id}:{pc['id']}"
        ))

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton(
                "?? ﬁ»·Ì", callback_data=f"adm:usr:cfgp:{target_id}:{page - 1}"
            ))
        nav_row.append(types.InlineKeyboardButton(
            f"’›ÕÂ {page + 1}/{total_pages}", callback_data="noop"
        ))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton(
                "»⁄œÌ ??", callback_data=f"adm:usr:cfgp:{target_id}:{page + 1}"
            ))
        kb.row(*nav_row)

    kb.add(types.InlineKeyboardButton(
        "»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}",
        icon_custom_emoji_id="5253997076169115797"
    ))
    if hasattr(call, "message"):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
    send_or_edit(call, f"?? ò«‰›ÌêùÂ«Ì ò«—»— ({total} ⁄œœ):", kb)


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
                bot.answer_callback_query(call.id, "? ⁄÷ÊÌ   √ÌÌœ ‘œ!")
                # If this user came via a referral link, trigger their referrer's start reward
                # (or show captcha if captcha is enabled ó in that case, skip menu).
                has_referral_captcha = False
                try:
                    from ..ui.notifications import (
                        try_give_referral_start_reward_for_channel_join,
                        has_pending_captcha,
                    )
                    try_give_referral_start_reward_for_channel_join(uid)
                    has_referral_captcha = has_pending_captcha(uid)
                except Exception:
                    pass
                if has_referral_captcha:
                    # Captcha prompt was just sent ó do NOT show menu yet.
                    return
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
                bot.answer_callback_query(call.id, "? Â‰Ê“ ⁄÷Ê ò«‰«· ‰‘œÂù«Ìœ.", show_alert=True)
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
            bot.answer_callback_query(call.id, "? ·ÿ›« ’»— ò‰Ìœ...", show_alert=False)
        except Exception:
            pass
        return

    try:
        ensure_user(call.from_user)

        # ?? Bot status gate (off / update) ???????????????????????????????????
        # Applies to ALL callbacks from non-admins, including old inline menus.
        # Admin callbacks pass through unconditionally.
        if not is_admin(uid):
            _bot_status = setting_get("bot_status", "on")
            if _bot_status == "off":
                bot.answer_callback_query(
                    call.id,
                    "?? —»«  œ— Õ«· Õ«÷— Œ«„Ê‘ «” .",
                    show_alert=True
                )
                return
            if _bot_status == "update":
                bot.answer_callback_query(
                    call.id,
                    "?? —»«  œ— Õ«· »—Ê“—”«‰Ì «” .\n\n·ÿ›« ò„Ì ’»— ò‰Ìœ Ê œÊ»«—Â «„ Õ«‰ ò‰Ìœ. ??",
                    show_alert=True
                )
                return

        # ?? Stale callback guard ?????????????????????????????????????????????
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
                        "? «Ì‰ œò„Â „‰ﬁ÷Ì ‘œÂ «” . ·ÿ›« œÊ»«—Â «“ „‰Ê «ﬁœ«„ ò‰Ìœ.",
                        show_alert=True
                    )
                    return
        except Exception:
            pass

        if not check_channel_membership(uid):
            bot.answer_callback_query(call.id)
            channel_lock_message(call)
            return

        # Phone gate ó enforce for all callbacks except phone-collection itself
        if not is_admin(uid) and data not in ("check_channel",):
            from ..handlers.start import _phone_required_for_user, _send_phone_request
            if _phone_required_for_user(uid):
                bot.answer_callback_query(call.id)
                _send_phone_request(call.message.chat.id, uid)
                return

        # ?? Layer 9: License enforcement in callback dispatcher ???????????????
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
                "?? —»«  œ— Õ«· Õ«÷— €Ì—›⁄«· «” .",
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
                    _dur_txt = f" « {_exp.strftime('%Y/%m/%d ó %H:%M')} ‰„Ìù Ê«‰Ìœ «“ —»«  «” ›«œÂ ò‰Ìœ."
                else:
                    _dur_txt = "»—«Ì Â„Ì‘Â ‰„Ìù Ê«‰Ìœ «“ —»«  «” ›«œÂ ò‰Ìœ."
                bot.answer_callback_query(
                    call.id,
                    f"?? œ” —”Ì „ÕœÊœ ‘œÂ ó {_dur_txt}",
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
                bot.answer_callback_query(call.id, f"?? Œÿ«: {short}", show_alert=True)
            except Exception:
                try:
                    bot.answer_callback_query(call.id, "Œÿ«ÌÌ —Œ œ«œ.", show_alert=True)
                except Exception:
                    pass
    finally:
        lock.release()


def _swapwallet_error_inline(call, err_msg):
    """‰„«Ì‘ Œÿ«Ì SwapWallet »Â ’Ê—  inline »« —«Â‰„«Ì  ‰ŸÌ„« ."""
    if "APPLICATION_NOT_FOUND" in err_msg or "Application not found" in err_msg or "ò”»\u200cÊò«—" in err_msg:
        msg = (
            "? <b>Œÿ«: ò”»\u200cÊò«— Ì«›  ‰‘œ</b>\n\n"
            "œ—ê«Â SwapWallet ‰Ì«“ »Â Ìò <b>Application (ò”»\u200cÊò«—)</b> Ãœ«ê«‰Â œ«—œ.\n"
            "«ò«‰  ‘Œ’Ì »—«Ì œ—Ì«›  Å—œ«Œ  ò«— ‰„Ì\u200cò‰œ.\n\n"
            "<b>„—«Õ· —›⁄:</b>\n"
            "1\ufe0f\u20e3 —»«  @SwapWalletBot —« »«“ ò‰Ìœ\n"
            "2\ufe0f\u20e3 »Â »Œ‘ <b>ò”»\u200cÊò«—</b> »—ÊÌœ\n"
            "3\ufe0f\u20e3 Ìò ò”»\u200cÊò«— ÃœÌœ »”«“Ìœ\n"
            "4\ufe0f\u20e3 <b>‰«„ ò«—»—Ì ¬‰ ò”»\u200cÊò«—</b> —« œ— Å‰· «œ„Ì‰ ? œ—ê«Â\u200cÂ« Ê«—œ ò‰Ìœ"
        )
    else:
        msg = f"? <b>Œÿ« œ— « ’«· »Â SwapWallet</b>\n\n<code>{err_msg[:300]}</code>"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
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


# ?? TetraPay auto-verify thread ???????????????????????????????????????????????
def _tetrapay_auto_verify(payment_id, authority, uid, chat_id, message_id, kind,
                          package_id=None):
    """Background thread: polls TetraPay every 15s for up to 60 minutes."""
    max_tries = 240  # 240 ◊ 15s = 60 minutes
    for attempt in range(max_tries):
        time.sleep(15)
        payment = get_payment(payment_id)
        if not payment or payment["status"] != "pending":
            return  # Already processed by another path
        success, result = verify_tetrapay_order(authority)
        print(f"[TetraPay auto-verify] attempt={attempt+1} payment={payment_id} ok={success} result={result!r}")
        if not success:
            continue
        # Payment confirmed ó process it
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
                        f"? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ Ê òÌ› ÅÊ· ‘«—é ‘œ.\n\n?? „»·€: {fmt_price(payment['amount'])}  Ê„«‰",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        f"? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ Ê òÌ› ÅÊ· ‘«—é ‘œ.\n\n?? „»·€: {fmt_price(payment['amount'])}  Ê„«‰",
                        parse_mode="HTML", reply_markup=back_button("main"))

            elif kind == "config_purchase":
                pkg_row = get_package(package_id)
                _qty_tp_auto = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    return
                state_clear(uid)
                try:
                    bot.edit_message_text(
                        "? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ. ò«‰›ÌêùÂ«Ì ‘„« œ— Õ«· ¬„«œÂù”«“Ì Â” ‰œ...",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        "? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ. ò«‰›ÌêùÂ«Ì ‘„« œ— Õ«· ¬„«œÂù”«“Ì Â” ‰œ...",
                        parse_mode="HTML", reply_markup=back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    chat_id, uid, package_id,
                    payment["amount"], "tetrapay", _qty_tp_auto, payment_id,
                    service_names=get_payment_service_names(payment_id)
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
                    "? <b>œ—ŒÊ«”   „œÌœ «—”«· ‘œ</b>\n\n"
                    "?? œ—ŒÊ«”   „œÌœ ”—ÊÌ” ‘„« »« „Ê›ﬁÌ  À»  Ê »—«Ì Å‘ Ì»«‰Ì «—”«· ‘œ.\n"
                    "? ·ÿ›« ò„Ì ’»— ò‰Ìœ° Å” «“ «‰Ã«„  „œÌœ »Â ‘„« «ÿ·«⁄ œ«œÂ ŒÊ«Âœ ‘œ.\n\n"
                    "?? «“ ’»— Ê ‘òÌ»«ÌÌ ‘„« „ ‘ò—Ì„."
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
                            bot.edit_message_text("? Å—œ«Œ   √ÌÌœ Ê ”—ÊÌ”  „œÌœ ‘œ.", chat_id, message_id,
                                                  parse_mode="HTML", reply_markup=back_button("my_configs"))
                        except Exception:
                            bot.send_message(uid, "? Å—œ«Œ   √ÌÌœ Ê ”—ÊÌ”  „œÌœ ‘œ.",
                                             parse_mode="HTML", reply_markup=back_button("my_configs"))
                    except Exception:
                        pass
                else:
                    try:
                        bot.send_message(uid,
                            "? Å—œ«Œ   √ÌÌœ ‘œ «„«  „œÌœ ”—ÊÌ” »« Œÿ« „Ê«ÃÂ ‘œ.\n·ÿ›« »« Å‘ Ì»«‰Ì «— »«ÿ »êÌ—Ìœ.",
                            parse_mode="HTML", reply_markup=back_button("my_configs"))
                    except Exception:
                        pass

        except Exception as e:
            print("TETRAPAY_AUTO_VERIFY_ERROR:", e)
        return  # Processed (success or error)

    # Timeout ó not verified after 60 minutes
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
            "? <b>»——”Ì ŒÊœò«— Å—œ«Œ  Å«Ì«‰ Ì«› </b>\n\n"
            "Êﬁ Ì Å—œ«Œ ù Ê‰  Ê —»«    —«ÅÌ  «ÌÌœ ‘œ° œò„Â <b>»——”Ì Å—œ«Œ </b> “Ì— —« »“‰Ìœ "
            " « Å—œ«Œ   √ÌÌœ ‘œÂ Ê «œ«„Â ⁄„·Ì«  «‰Ã«„ ‘Êœ.\n\n"
            "«ê— „»·€ «“ Õ”«» ‘„« ò”— ‘œÂ Ê Å—œ«Œ   √ÌÌœ ‰‘œÂ° ·ÿ›« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ."
        )
        timeout_kb = types.InlineKeyboardMarkup()
        timeout_kb.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ", callback_data=verify_cb))
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


# ?? TronPays Rial auto-verify thread ??????????????????????????????????????????
def _tronpays_rial_auto_verify(payment_id, invoice_id, uid, chat_id, message_id, kind,
                               package_id=None):
    """Background thread: polls TronPays every 15s for up to 60 minutes."""
    max_tries = 240  # 240 ◊ 15s = 60 minutes
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
                        f"? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ Ê òÌ› ÅÊ· ‘«—é ‘œ.\n\n?? „»·€: {fmt_price(payment['amount'])}  Ê„«‰",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        f"? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ Ê òÌ› ÅÊ· ‘«—é ‘œ.\n\n?? „»·€: {fmt_price(payment['amount'])}  Ê„«‰",
                        parse_mode="HTML", reply_markup=back_button("main"))

            elif kind == "config_purchase":
                pkg_row = get_package(package_id)
                _qty_trp_auto = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    return
                state_clear(uid)
                try:
                    bot.edit_message_text(
                        "? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ. ò«‰›ÌêùÂ«Ì ‘„« œ— Õ«· ¬„«œÂù”«“Ì Â” ‰œ...",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        "? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ. ò«‰›ÌêùÂ«Ì ‘„« œ— Õ«· ¬„«œÂù”«“Ì Â” ‰œ...",
                        parse_mode="HTML", reply_markup=back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    chat_id, uid, package_id,
                    payment["amount"], "tronpays_rial", _qty_trp_auto, payment_id,
                    service_names=get_payment_service_names(payment_id)
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
                    "? <b>œ—ŒÊ«”   „œÌœ «—”«· ‘œ</b>\n\n"
                    "?? œ—ŒÊ«”   „œÌœ ”—ÊÌ” ‘„« »« „Ê›ﬁÌ  À»  Ê »—«Ì Å‘ Ì»«‰Ì «—”«· ‘œ.\n"
                    "? ·ÿ›« ò„Ì ’»— ò‰Ìœ° Å” «“ «‰Ã«„  „œÌœ »Â ‘„« «ÿ·«⁄ œ«œÂ ŒÊ«Âœ ‘œ.\n\n"
                    "?? «“ ’»— Ê ‘òÌ»«ÌÌ ‘„« „ ‘ò—Ì„."
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
                        bot.send_message(uid, "? Å—œ«Œ   √ÌÌœ Ê ”—ÊÌ”  „œÌœ ‘œ.",
                                         parse_mode="HTML", reply_markup=back_button("my_configs"))
                    except Exception:
                        pass
                else:
                    try:
                        bot.send_message(uid,
                            "? Å—œ«Œ   √ÌÌœ ‘œ «„«  „œÌœ ”—ÊÌ” »« Œÿ« „Ê«ÃÂ ‘œ.\n·ÿ›« »« Å‘ Ì»«‰Ì «— »«ÿ »êÌ—Ìœ.",
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
            "? <b>»——”Ì ŒÊœò«— Å—œ«Œ  Å«Ì«‰ Ì«› </b>\n\n"
            "Êﬁ Ì Å—œ«Œ ù Ê‰  Ê TronPays  «ÌÌœ ‘œ° œò„Â <b>»——”Ì Å—œ«Œ </b> “Ì— —« »“‰Ìœ "
            " « Å—œ«Œ   √ÌÌœ ‘œÂ Ê «œ«„Â ⁄„·Ì«  «‰Ã«„ ‘Êœ.\n\n"
            "«ê— „»·€ «“ Õ”«» ‘„« ò”— ‘œÂ Ê Å—œ«Œ   √ÌÌœ ‰‘œÂ° ·ÿ›« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ."
        )
        timeout_kb = types.InlineKeyboardMarkup()
        timeout_kb.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ", callback_data=verify_cb))
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
    # ?? License callbacks ????????????????????????????????????????????????????
    if data.startswith("license:"):
        from ..license_manager import (
            is_limited_mode, get_license_status_text, check_license, _invalidate_cache,
            activate_license, get_or_create_machine_id,
            API_KEY_PROMPT_TEXT, API_URL_PROMPT_TEXT, ACTIVATION_SUCCESS_TEXT, ACTIVATION_FAIL_TEXT,
        )
        from ..config import ADMIN_IDS as _AIDS

        if data == "license:activate":
            if uid not in _AIDS and not is_admin(uid):
                bot.answer_callback_query(call.id, "? œ” —”Ì ›ﬁÿ »—«Ì „«·ò/«œ„Ì‰.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            state_set(uid, "license:waiting_api_key")
            bot.send_message(call.message.chat.id, API_KEY_PROMPT_TEXT, parse_mode="HTML")
            return

        if data in ("license:status", "license:recheck"):
            if uid not in _AIDS and not is_admin(uid):
                bot.answer_callback_query(call.id, "? œ” —”Ì ›ﬁÿ »—«Ì „«·ò/«œ„Ì‰.", show_alert=True)
                return
            if data == "license:recheck":
                bot.answer_callback_query(call.id, "? œ— Õ«· »——”Ì...")
                _invalidate_cache()
                check_license(force=True)
            else:
                bot.answer_callback_query(call.id)
            text = get_license_status_text()
            kb = types.InlineKeyboardMarkup()
            if is_limited_mode():
                kb.add(types.InlineKeyboardButton("?? ›⁄«·ù”«“Ì ·«Ì”‰”", callback_data="license:activate"))
            kb.add(types.InlineKeyboardButton("?? »——”Ì „Ãœœ", callback_data="license:recheck"))
            kb.row(
                types.InlineKeyboardButton("ÊÌ—«Ì‘ ?? API Key", callback_data="license:edit_key"),
                types.InlineKeyboardButton("ÊÌ—«Ì‘ ?? API URL", callback_data="license:edit_url"),
            )
            kb.add(types.InlineKeyboardButton("?? »«“ê‘ ", callback_data="admin:panel"))
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
                bot.answer_callback_query(call.id, "? œ” —”Ì ›ﬁÿ »—«Ì „«·ò/«œ„Ì‰.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            state_set(uid, "license:edit_api_key")
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("? ·€Ê", callback_data="license:status"))
            bot.send_message(
                call.message.chat.id,
                "?? <b>ÊÌ—«Ì‘ API Key</b>\n\n"
                "ò·Ìœ API ÃœÌœ —« Ê«—œ ò‰Ìœ:",
                parse_mode="HTML", reply_markup=kb,
            )
            return

        if data == "license:edit_url":
            if uid not in _AIDS and not is_admin(uid):
                bot.answer_callback_query(call.id, "? œ” —”Ì ›ﬁÿ »—«Ì „«·ò/«œ„Ì‰.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            state_set(uid, "license:edit_api_url")
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("? ·€Ê", callback_data="license:status"))
            bot.send_message(
                call.message.chat.id,
                "?? <b>ÊÌ—«Ì‘ API URL</b>\n\n"
                "¬œ—” URL ÃœÌœ ”—Ê— ·«Ì”‰” —« Ê«—œ ò‰Ìœ:\n"
                "<i>„À«·: https://license.example.com</i>",
                parse_mode="HTML", reply_markup=kb,
            )
            return

        if data == "license:limited_info":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                "?? <b>—»«  œ— Õ«·  „ÕœÊœ «Ã—« „Ìù‘Êœ.</b>\n\n"
                "»—«Ì ›⁄«·ù”«“Ì ò«„· —»« ° »« „«·ò  „«” »êÌ—Ìœ.\n"
                "Ì« »—«Ì Œ—Ìœ «‘ —«ò »Â @Emad_Habibnia ÅÌ«„ œÂÌœ.",
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
            bot.answer_callback_query(call.id, "ÂÌç Å«œ«‘ œ—Ì«› ù‰‘œÂù«Ì ÊÃÊœ ‰œ«—œ.", show_alert=True)
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
                    continue  # leave unclaimed ó admin must fix package config
                available = get_available_configs_for_package(int(pkg_id))
                if not available:
                    failed_config += 1
                    continue  # leave unclaimed ó no stock; user can retry later
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
                f"?? „»·€ <b>{fmt_price(delivered_wallet)}</b>  Ê„«‰ »« „Ê›ﬁÌ  »Â òÌ›ùÅÊ· ‘„« «÷«›Â ‘œ."
            )
        if delivered_config:
            parts_msg.append(
                f"?? <b>{delivered_config}</b> ò«‰›Ìê —«Ìê«‰ »« „Ê›ﬁÌ  »Â ”—ÊÌ”ùÂ«Ì ‘„« «÷«›Â ‘œ."
            )
        if failed_config:
            parts_msg.append(
                f"?? <b>{failed_config}</b> Å«œ«‘ ò«‰›Ìê »Â œ·Ì· ⁄œ„ „ÊÃÊœÌ  ÕÊÌ· œ«œÂ ‰‘œ.\n"
                "·ÿ›« »⁄œ« œÊ»«—Â  ·«‘ ò‰Ìœ Ì« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ."
            )
        if parts_msg:
            bot.answer_callback_query(call.id, "? Å«œ«‘ œ—Ì«›  ‘œ!", show_alert=False)
            summary = "\n\n".join(parts_msg)
            try:
                bot.send_message(
                    uid,
                    f"?? <b>Å«œ«‘ “Ì—„Ã„Ê⁄ÂùêÌ—Ì</b>\n\n{summary}",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            bot.answer_callback_query(call.id, "Å«œ«‘Ì »—«Ì œ—Ì«›  ÊÃÊœ ‰œ«‘ .", show_alert=True)
        show_referral_menu(call, uid)
        return

    if data == "referral:get_banner":
        banner_photo = setting_get("referral_banner_photo", "").strip()
        if not banner_photo:
            bot.answer_callback_query(call.id, "»‰—Ì  ‰ŸÌ„ ‰‘œÂ «” .", show_alert=True)
            return
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
        custom_banner = setting_get("referral_banner_text", "").strip()
        from ..config import BRAND_TITLE
        if custom_banner:
            caption = f"{custom_banner}\n\n{ref_link}"
        else:
            caption = (
                f"?? „ÌùŒÊ«Ì »« ”—⁄  »«·« Ê Å«Ìœ«—Ì ⁄«·Ì »Â «Ì‰ —‰  ¬“«œ Ê’· »‘Ìø\n\n"
                f"„‰ «“ {BRAND_TITLE} ”—ÊÌ” VPN Œ—Ìœ„ Ê ò«„·« —«÷Ì„! ??\n\n"
                f"? ”—⁄  ›Êﬁù«·⁄«œÂ\n"
                f"? Å«Ìœ«—Ì »«·«\n"
                f"? Å‘ Ì»«‰Ì ?? ”«⁄ Â\n\n"
                f" Ê Â„ «“ ·Ì‰ò „‰ Ê«—œ ‘Ê Ê ”—ÊÌ”  —Ê »Œ— ??\n{ref_link}"
            )
        bot.answer_callback_query(call.id)
        bot.send_photo(call.message.chat.id, banner_photo, caption=caption, parse_mode="HTML")
        return

    # ?? Discount code flow ???????????????????????????????????????????????????
    if data == "disc:yes":
        sn = state_name(uid)
        sd = state_data(uid)
        if sn not in {"buy_select_method", "renew_select_method"}:
            bot.answer_callback_query(call.id, "œ—ŒÊ«” Ì »—«Ì «⁄„«·  Œ›Ì› ÅÌœ« ‰‘œ.", show_alert=True)
            return
        original_amount = sd.get("original_amount", sd.get("amount", 0))
        new_sd = dict(sd)
        new_sd["prev_state"] = sn
        new_sd["original_amount"] = original_amount
        state_set(uid, "await_discount_code", **new_sd)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? »«“ê‘  (»œÊ‰  Œ›Ì›)", callback_data="disc:no"))
        send_or_edit(call,
            "?? <b>òœ  Œ›Ì›</b>\n\n"
            "?? ·ÿ›« òœ  Œ›Ì› ŒÊœ —«  «ÌÅ ò—œÂ Ê «—”«· ò‰Ìœ:\n\n"
            "?? <i>òœÂ« „⁄„Ê·«  —òÌ»Ì «“ Õ—Ê› «‰ê·Ì”Ì Ê «⁄œ«œ Â” ‰œ.</i>",
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
        bot.answer_callback_query(call.id, "œ—ŒÊ«” Ì »—«Ì «œ«„Â ÅÌœ« ‰‘œ.", show_alert=True)
        return

    # ?? Agency request ????????????????????????????????????????????????????????
    if data == "agency:request":
        user = get_user(uid)
        if user and user["is_agent"]:
            bot.answer_callback_query(call.id, "‘„« œ— Õ«· Õ«÷— ‰„«Ì‰œÂ Â” Ìœ.", show_alert=True)
            return
        if setting_get("agency_request_enabled", "1") != "1":
            bot.answer_callback_query(call.id, "œ—ŒÊ«”  ‰„«Ì‰œêÌ œ— Õ«· Õ«÷— €Ì—›⁄«· «” .", show_alert=True)
            return
        # Check min wallet balance
        min_wallet = int(setting_get("agency_request_min_wallet", "0") or "0")
        if min_wallet > 0 and (not user or (user["balance"] or 0) < min_wallet):
            bot.answer_callback_query(call.id,
                f"»—«Ì «—”«· œ—ŒÊ«”  ‰„«Ì‰œêÌ »«Ìœ Õœ«ﬁ· {fmt_price(min_wallet)}  Ê„«‰ „ÊÃÊœÌ òÌ› ÅÊ· œ«‘ Â »«‘Ìœ.",
                show_alert=True)
            return
        # Check for pending or recent rejected request (7-day cooldown)
        existing = get_reseller_request(uid)
        if existing:
            if existing["status"] == "pending":
                bot.answer_callback_query(call.id, "œ—ŒÊ«”  ‰„«Ì‰œêÌ ‘„« œ— Õ«· »——”Ì «” .", show_alert=True)
                return
            if existing["status"] == "rejected" and existing["rejected_at"]:
                import datetime as _dt
                try:
                    rej_dt = _dt.datetime.fromisoformat(existing["rejected_at"])
                    diff = (_dt.datetime.now() - rej_dt).days
                    if diff < 7:
                        bot.answer_callback_query(call.id,
                            f"œ—ŒÊ«”  ‘„« {diff} —Ê“ ÅÌ‘ —œ ‘œÂ «” . Å” «“ ? —Ê“ „Ìù Ê«‰Ìœ œÊ»«—Â œ—ŒÊ«”  œÂÌœ.",
                            show_alert=True)
                        return
                except Exception:
                    pass
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? «—”«· œ—ŒÊ«”  (»œÊ‰ „ ‰)", callback_data="agency:send_empty"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        state_set(uid, "agency_request_text")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>œ—ŒÊ«”  ‰„«Ì‰œêÌ</b>\n\n"
            "·ÿ›« „ ‰ œ—ŒÊ«”  ŒÊœ —« «—”«· ò‰Ìœ. „Ê«—œ “Ì— —« œ— „ ‰ –ò— ò‰Ìœ:\n\n"
            "?? „Ì“«‰ ›—Ê‘ ‘„« œ— —Ê“ Ì« Â› Â\n"
            "?? ò«‰«· Ì« ›—Ê‘ê«ÂÌ òÂ œ«—Ìœ (¬œ—” ò«‰«·  ·ê—«„)\n"
            "?? ¬ÌœÌ Å‘ Ì»«‰Ì „Ã„Ê⁄Â ‘„«\n"
            "?? Â—  Ê÷ÌÕ œÌê—Ì òÂ ·«“„ „Ìùœ«‰Ìœ\n\n"
            "«ê— ‰„ÌùŒÊ«ÂÌœ „ ‰Ì »‰ÊÌ”Ìœ° œò„Â “Ì— —« »“‰Ìœ:", kb)
        return

    if data == "agency:send_empty":
        state_clear(uid)
        user = get_user(uid)
        if user and user["is_agent"]:
            bot.answer_callback_query(call.id, "‘„« œ— Õ«· Õ«÷— ‰„«Ì‰œÂ Â” Ìœ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, "? œ—ŒÊ«”  ‰„«Ì‰œêÌ ‘„« «—”«· ‘œ.\n? ·ÿ›« „‰ Ÿ— »——”Ì «œ„Ì‰ »«‘Ìœ.", back_button("main"))
        # Save to reseller_requests table
        req_id = create_reseller_request(
            uid,
            user["username"] if user else None,
            user["full_name"] if user else str(uid),
            None
        )
        # Notify admins
        text = (
            f"?? <b>œ—ŒÊ«”  ‰„«Ì‰œêÌ ÃœÌœ</b>\n\n"
            f"?? ‰«„: {esc(user['full_name'])}\n"
            f"?? ‰«„ ò«—»—Ì: {esc(display_username(user['username']))}\n"
            f"?? ¬ÌœÌ: <code>{user['user_id']}</code>\n\n"
            f"?? „ ‰ œ—ŒÊ«” : <i>»œÊ‰ „ ‰</i>"
        )
        admin_kb = types.InlineKeyboardMarkup()
        admin_kb.row(
            types.InlineKeyboardButton("?  √ÌÌœ", callback_data=f"adm:resreq:approve:{req_id}"),
            types.InlineKeyboardButton("? —œ", callback_data=f"adm:resreq:reject:{req_id}"),
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_set(uid, "agency_approve_note", target_user_id=target_uid)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? »œÊ‰ ÅÌ«„", callback_data=f"agency:approve_now:{target_uid}"))
        bot.send_message(call.message.chat.id,
            f"? œ— Õ«·  √ÌÌœ ‰„«Ì‰œêÌ ò«—»— <code>{target_uid}</code>\n\n"
            "«ê— „ÌùŒÊ«ÂÌœ ÅÌ«„Ì »—«Ì ò«—»— «—”«· ò‰Ìœ° „ ‰ —« »‰ÊÌ”Ìœ.\n"
            "œ— €Ì— «Ì‰ ’Ê—  œò„Â “Ì— —« »“‰Ìœ:", reply_markup=kb)
        return

    if data.startswith("agency:approve_now:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_clear(uid)
        set_user_agent(target_uid, 1)
        # Also update any pending reseller_request for this user
        pending_req = get_reseller_request(target_uid, status="pending")
        if pending_req:
            approve_reseller_request(pending_req["id"], uid)
        bot.answer_callback_query(call.id, "? ‰„«Ì‰œêÌ  √ÌÌœ ‘œ.")
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
                "?? <b>œ—ŒÊ«”  ‰„«Ì‰œêÌ ‘„«  √ÌÌœ ‘œ!</b>\n\n«ò‰Ê‰ ‘„« ‰„«Ì‰œÂ Â” Ìœ.",
                parse_mode="HTML")
        except Exception:
            pass
        # Log to agency_log topic
        user_row = get_user(target_uid)
        send_to_topic("agency_log",
            f"? <b>‰„«Ì‰œêÌ  √ÌÌœ ‘œ</b>\n\n"
            f"?? ‰«„: {esc(user_row['full_name'] if user_row else str(target_uid))}\n"
            f"?? ‰«„ ò«—»—Ì: {esc(user_row['username'] or '‰œ«—œ' if user_row else '-')}\n"
            f"?? ¬ÌœÌ: <code>{target_uid}</code>\n"
            f" √ÌÌœò‰‰œÂ: <code>{uid}</code>"
        )
        # If called from admin DM, show user detail panel
        if call.message.chat.type == "private":
            _show_admin_user_detail(call, target_uid)
        else:
            try:
                bot.send_message(call.message.chat.id,
                    f"? ‰„«Ì‰œêÌ ò«—»— <code>{target_uid}</code>  √ÌÌœ ‘œ.",
                    message_thread_id=call.message.message_thread_id,
                    parse_mode="HTML")
            except Exception:
                pass
        return

    if data.startswith("agency:reject_now:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        bot.answer_callback_query(call.id, "? —œ ‘œ.")
        # Update reseller_request record
        pending_req = get_reseller_request(target_uid, status="pending")
        if pending_req:
            reject_reseller_request(pending_req["id"], uid)
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
                "? <b>œ—ŒÊ«”  ‰„«Ì‰œêÌ ‘„« —œ ‘œ.</b>",
                parse_mode="HTML")
        except Exception:
            pass
        # Log to agency_log topic
        user_row = get_user(target_uid)
        send_to_topic("agency_log",
            f"? <b>‰„«Ì‰œêÌ —œ ‘œ</b>\n\n"
            f"?? ‰«„: {esc(user_row['full_name'] if user_row else str(target_uid))}\n"
            f"?? ¬ÌœÌ: <code>{target_uid}</code>\n"
            f"—œò‰‰œÂ: <code>{uid}</code>"
        )
        return

    if data.startswith("agency:reject:"):
        if not is_admin(uid) or not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_set(uid, "agency_reject_reason", target_user_id=target_uid)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(call.message.chat.id,
            f"? œ— Õ«· —œ œ—ŒÊ«”  ‰„«Ì‰œêÌ ò«—»— <code>{target_uid}</code>\n\n"
            "·ÿ›« œ·Ì· —œ —« »‰ÊÌ”Ìœ:")
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
        # Enter search mode ó ask user to type a query
        state_set(uid, "my_cfgs_search")
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? ·€Ê", callback_data="my_configs"))
        send_or_edit(call,
            "?? <b>Ã” ùÊÃÊ œ— ò«‰›ÌêùÂ«</b>\n\n"
            "„ ‰ „Ê—œ ‰Ÿ— —« «—”«· ò‰Ìœ:\n"
            "ï ‰«„ ò«‰›Ìê\n"
            "ï „ ‰ ò«‰›Ìê (config link)\n"
            "ï ·Ì‰ò ”«»ù«”ò—«Ì»\n\n"
            "<i>»—«Ì ·€Ê œò„Â ·€Ê —« »“‰Ìœ.</i>",
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        deliver_purchase_message(call.message.chat.id, purchase_id)
        return

    # ?? Renewal flow ??????????????????????????????????????????????????????????
    if data.startswith("renew:") and not data.startswith("renew:p:") and not data.startswith("renew:confirm:"):
        if setting_get("manual_renewal_enabled", "1") != "1" and not is_admin(uid):
            bot.answer_callback_query(call.id, "?  „œÌœ œ— Õ«· Õ«÷— €Ì—›⁄«· «” .", show_alert=True)
            return
        purchase_id = int(data.split(":")[1])
        item = get_purchase(purchase_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
            title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)}  "
            kb.add(types.InlineKeyboardButton(title, callback_data=f"renew:p:{purchase_id}:{p['id']}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="my_configs", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        agent_note = "\n\n?? <i>«Ì‰ ﬁÌ„ ùÂ« „Œ’Ê’ Â„ò«—Ì ‘„«” </i>" if user and user["is_agent"] else ""
        if not packages:
            send_or_edit(call, "?? œ— Õ«· Õ«÷— ÅòÌÃÌ »—«Ì  „œÌœ „ÊÃÊœ ‰Ì” .", kb)
        else:
            send_or_edit(call, f"?? <b> „œÌœ ”—ÊÌ”</b>\n\nÅòÌÃ „Ê—œ ‰Ÿ— »—«Ì  „œÌœ —« «‰ Œ«» ò‰Ìœ:{agent_note}", kb)
        return

    if data.startswith("renew:p:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
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


    # ?? Renewal payment handlers ??????????????????????????????????????????????
    if data.startswith("rpay:wallet:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        user = get_user(uid)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if user["balance"] < price:
            if not can_use_credit(uid, price):
                bot.answer_callback_query(call.id, "„ÊÃÊœÌ òÌ› ÅÊ· ò«›Ì ‰Ì” .", show_alert=True)
                return
        update_balance(uid, -price)
        payment_id = create_payment("renewal", uid, package_id, price, "wallet",
                                     status="completed", config_id=item["config_id"])
        complete_payment(payment_id)
        bot.answer_callback_query(call.id, "Å—œ«Œ  „Ê›ﬁ »Êœ.")
        send_or_edit(call,
            "? <b>œ—ŒÊ«”   „œÌœ «—”«· ‘œ</b>\n\n"
            "?? œ—ŒÊ«”   „œÌœ ”—ÊÌ” ‘„« »« „Ê›ﬁÌ  À»  Ê »—«Ì Å‘ Ì»«‰Ì «—”«· ‘œ.\n"
            "? ·ÿ›« ò„Ì ’»— ò‰Ìœ° Å” «“ «‰Ã«„  „œÌœ »Â ‘„« «ÿ·«⁄ œ«œÂ ŒÊ«Âœ ‘œ.\n\n"
            "?? «“ ’»— Ê ‘òÌ»«ÌÌ ‘„« „ ‘ò—Ì„.",
            back_button("main"))
        admin_renewal_notify(uid, item, package_row, price, "òÌ› ÅÊ·")
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        _ci = pick_card_for_payment()
        if not _ci:
            bot.answer_callback_query(call.id, "«ÿ·«⁄«  Å—œ«Œ  Â‰Ê“ À»  ‰‘œÂ «” .", show_alert=True)
            return
        card, bank, owner = _ci["card_number"], _ci["bank_name"], _ci["holder_name"]
        price = _get_state_price(uid, package_row, "renew_select_method")
        price = apply_gateway_fee("card", price)
        if not is_gateway_in_range("card", price):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì «Ì‰ œ—ê«Â „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("crypto", price):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì «Ì‰ œ—ê«Â „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
            return
        authority = payment["receipt_text"]
        success, result = verify_tetrapay_order(authority)
        if success:
            if not complete_payment(payment_id):
                bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                return
            package_row = get_package(payment["package_id"])
            config_id = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
            send_or_edit(call,
                "? <b>œ—ŒÊ«”   „œÌœ «—”«· ‘œ</b>\n\n"
                "?? œ—ŒÊ«”   „œÌœ ”—ÊÌ” ‘„« »« „Ê›ﬁÌ  À»  Ê »—«Ì Å‘ Ì»«‰Ì «—”«· ‘œ.\n"
                "? ·ÿ›« ò„Ì ’»— ò‰Ìœ° Å” «“ «‰Ã«„  „œÌœ »Â ‘„« «ÿ·«⁄ œ«œÂ ŒÊ«Âœ ‘œ.\n\n"
                "?? «“ ’»— Ê ‘òÌ»«ÌÌ ‘„« „ ‘ò—Ì„.",
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
                f"? Å—œ«Œ  Â‰Ê“  «ÌÌœ ‰‘œÂ.\nÊ÷⁄Ì  TetraPay: {_st}\n\n·ÿ›« «» œ« Å—œ«Œ  —« œ— œ—ê«Â   —«ÅÌ «‰Ã«„ œÂÌœ.",
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("tetrapay", price):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â TetraPay „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        hash_id = f"rnw-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f" „œÌœ {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f" „œÌœ {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tetrapay_order(price, hash_id, order_label)
        if not success:
            bot.answer_callback_query(call.id, "Œÿ« œ— «ÌÃ«œ œ—ŒÊ«”  Å—œ«Œ  ¬‰·«Ì‰.", show_alert=True)
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
            "?? <b>Å—œ«Œ  ¬‰·«Ì‰ ( „œÌœ)</b>\n\n"
            f"?? „»·€: <b>{fmt_price(price)}</b>  Ê„«‰\n\n"
            "·ÿ›« «“ ÌòÌ «“ ·Ì‰òùÂ«Ì “Ì— Å—œ«Œ  —« «‰Ã«„ œÂÌœ.\n\n"
            "? <b> « Ìò ”«⁄ </b> «ê— Å—œ«Œ ù Ê‰  «ÌÌœ »‘Â »Â ’Ê—  ŒÊœò«— ⁄„·Ì«  «‰Ã«„ „Ìù‘Êœ.\n"
            "œ— €Ì— «Ì‰ ’Ê—  œò„Â <b>»——”Ì Å—œ«Œ </b> —« »“‰Ìœ."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  œ—  ·ê—«„", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  œ— „—Ê—ê—", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ", callback_data=f"rpay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "renewal", package_id=package_id)
        return

    if data.startswith("rpay:tetrapay:verify:"):
        # NOTE: this block is now unreachable (handled above) ó kept as safety guard
        bot.answer_callback_query(call.id)
        return

    # ?? TronPays Rial: renewal ????????????????????????????????????????????????
    if data.startswith("rpay:tronpays_rial:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        ok, status = check_tronpays_rial_invoice(invoice_id)
        if not ok:
            bot.answer_callback_query(call.id, "Œÿ« œ— »——”Ì Ê÷⁄Ì  ›«ò Ê—.", show_alert=True)
            return
        if is_tronpays_paid(status):
            if not complete_payment(payment_id):
                bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                return
            package_row = get_package(payment["package_id"])
            config_id   = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
            send_or_edit(call,
                "? <b>œ—ŒÊ«”   „œÌœ «—”«· ‘œ</b>\n\n"
                "?? œ—ŒÊ«”   „œÌœ ”—ÊÌ” ‘„« »« „Ê›ﬁÌ  À»  Ê »—«Ì Å‘ Ì»«‰Ì «—”«· ‘œ.\n"
                "? ·ÿ›« ò„Ì ’»— ò‰Ìœ° Å” «“ «‰Ã«„  „œÌœ »Â ‘„« «ÿ·«⁄ œ«œÂ ŒÊ«Âœ ‘œ.\n\n"
                "?? «“ ’»— Ê ‘òÌ»«ÌÌ ‘„« „ ‘ò—Ì„.",
                back_button("main"))
            if item:
                admin_renewal_notify(uid, item, package_row, payment["amount"], "TronPays")
            try:
                apply_gateway_bonus_if_needed(uid, "tronpays_rial", payment["amount"])
            except Exception:
                pass
            state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "? Å—œ«Œ  Â‰Ê“  √ÌÌœ ‰‘œÂ. ·ÿ›« «» œ« Å—œ«Œ  —« «‰Ã«„ œÂÌœ.", show_alert=True)
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("tronpays_rial", price):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â TronPay „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        hash_id = f"rnw-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f" „œÌœ {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f" „œÌœ {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tronpays_rial_invoice(price, hash_id, order_label)
        if not success:
            err_msg = result.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>Œÿ« œ— «ÌÃ«œ œ—ê«Â TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "?? „ÿ„∆‰ ‘ÊÌœ ò·Ìœ API ’ÕÌÕ Ê«—œ ‘œÂ »«‘œ.",
                back_button(f"renew:{purchase_id}"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>Œÿ« œ— «ÌÃ«œ ›«ò Ê— TronPays</b>\n\n"
                f"<code>Å«”Œ API: {esc(str(result)[:400])}</code>",
                back_button(f"renew:{purchase_id}"))
            return
        payment_id = create_payment("renewal", uid, package_id, price, "tronpays_rial", status="pending",
                                    config_id=item["config_id"])
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_renewal_tronpays_rial_verify", payment_id=payment_id,
                  invoice_id=invoice_id, purchase_id=purchase_id)
        text = (
            "?? <b>Å—œ«Œ  —Ì«·Ì (TronPays) ó  „œÌœ</b>\n\n"
            f"?? „»·€: <b>{fmt_price(price)}</b>  Ê„«‰\n\n"
            "«“ ·Ì‰ò “Ì— Å—œ«Œ  —« «‰Ã«„ œÂÌœ.\n\n"
            "? <b> « Ìò ”«⁄ </b> Å—œ«Œ  »Â ’Ê—  ŒÊœò«— »——”Ì „Ìù‘Êœ.\n"
            "œ— €Ì— «Ì‰ ’Ê—  œò„Â ´»——”Ì Å—œ«Œ ª —« »“‰Ìœ."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  «“ œ—ê«Â TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ", callback_data=f"rpay:tronpays_rial:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tronpays_rial_auto_verify(
            payment_id, invoice_id, uid,
            call.message.chat.id, call.message.message_id,
            "renewal", package_id=package_id)
        return

    # ?? Admin: Confirm renewal ????????????????????????????????????????????????
    if data.startswith("renew:confirm:"):
        if not admin_has_perm(uid, "approve_renewal"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts = data.split(":")
        config_id  = int(parts[2])
        target_uid = int(parts[3])
        # Un-expire config if it was expired
        with get_conn() as conn:
            conn.execute("UPDATE configs SET is_expired=0 WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "?  „œÌœ  √ÌÌœ ‘œ.")
        # Update admin's message
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        try:
            bot.send_message(call.message.chat.id, "?  „œÌœ  √ÌÌœ Ê »Â ò«—»— «ÿ·«⁄ œ«œÂ ‘œ.")
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
                f"?? <b> „œÌœ ”—ÊÌ” «‰Ã«„ ‘œ!</b>\n\n"
                f"? ”—ÊÌ” <b>{esc(svc_name)}</b> ‘„« »« „Ê›ﬁÌ   „œÌœ ‘œ.\n"
                "«“ «⁄ „«œ ‘„« ”Å«”ê“«—Ì„. ??")
        except Exception:
            pass
        # Renewal log ó find the payment method from the original admin message
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
                f"?? | <b> „œÌœ  √ÌÌœ ‘œ</b>"
                f"{(' (' + esc(renewal_method) + ')') if renewal_method else ''}\n\n"
                f"?? ¬ÌœÌ ò«—»—: <code>{target_uid}</code>\n"
                f"??û?? ‰«„: {esc(user_row['full_name'] if user_row else '')}\n"
                f"?? ‰«„ ò«—»—Ì: {esc((user_row['username'] or '‰œ«—œ') if user_row else '‰œ«—œ')}\n"
                f"?? ‰«„ ”—ÊÌ”: {esc(svc_name or str(config_id))}\n"
            )
            if cfg_row:
                log_text += (
                    f"?? ”—Ê—: {esc(cfg_row['type_name'])}\n"
                    f"?? ÅòÌÃ: {esc(cfg_row['package_name'])}\n"
                    f"?? ÕÃ„: {cfg_row['volume_gb']} êÌê\n"
                    f"? „œ : {cfg_row['duration_days']} —Ê“\n"
                    f"?? ﬁÌ„ : {fmt_price(cfg_row['price'])}  Ê„«‰"
                )
            send_to_topic("renewal_log", log_text)
        except Exception:
            pass
        return

    # ?? Buy flow ??????????????????????????????????????????????????????????????
    if data == "buy:start":
        # Check purchase rules
        if setting_get("purchase_rules_enabled", "0") == "1":
            accepted = setting_get(f"rules_accepted_{uid}", "0")
            if accepted != "1":
                rules_text = setting_get("purchase_rules_text", "")
                from ..ui.premium_emoji import render_premium_text_html as _rph
                rendered_rules = _rph(rules_text, escape_plain_parts=True)
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("? „‰ ﬁÊ«‰Ì‰ —« ŒÊ«‰œ„ Ê Å–Ì—› „", callback_data="buy:accept_rules"))
                kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
                bot.answer_callback_query(call.id)
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception:
                    pass
                bot.send_message(
                    call.message.chat.id,
                    f"?? <b>ﬁÊ«‰Ì‰ Œ—Ìœ</b>\n\n{rendered_rules}",
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
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>›—Ê‘ê«Â „Êﬁ «  ⁄ÿÌ· «” .</b>\n\n·ÿ›« »⁄œ« „—«Ã⁄Â ò‰Ìœ.", kb)
            return
        stock_only = setting_get("preorder_mode", "0") == "1"
        items = get_active_types()
        kb = types.InlineKeyboardMarkup()
        has_any = False
        for item in items:
            packs = [p for p in get_packages(type_id=item['id']) if p['price'] > 0 and _pkg_has_stock(p, stock_only)]
            if packs:
                kb.add(types.InlineKeyboardButton(f"?? {item['name']}", callback_data=f"buy:t:{item['id']}"))
                has_any = True
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        if not has_any:
            send_or_edit(call, "?? œ— Õ«· Õ«÷— »” Âù«Ì »—«Ì ›—Ê‘ „ÊÃÊœ ‰Ì” .", kb)
        else:
            send_or_edit(call, "?? <b>Œ—Ìœ ò«‰›Ìê ÃœÌœ</b>\n\n‰Ê⁄ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("buy:t:"):
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>›—Ê‘ê«Â „Êﬁ «  ⁄ÿÌ· «” .</b>\n\n·ÿ›« »⁄œ« „—«Ã⁄Â ò‰Ìœ.", kb)
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
                label = "?? ‰«„ÕœÊœ" if u == 0 else f"?? {u} ò«—»—Â"
                kb.add(types.InlineKeyboardButton(label, callback_data=f"buy:mu:{u}:{type_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="buy:start", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "??  ⁄œ«œ ò«—»— „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
            return
        kb   = types.InlineKeyboardMarkup()
        for p in packages:
            price = get_effective_price(uid, p)
            stock_tag = "" if _pkg_has_stock(p, True) else " ?"
            _sn = p['show_name'] if 'show_name' in p.keys() else 1
            _name_part = f"{p['name']}{stock_tag} | " if _sn else (f"{stock_tag} | " if stock_tag else "")
            title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)}  "
            kb.add(types.InlineKeyboardButton(title, callback_data=f"buy:p:{p['id']}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="buy:start", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        agent_note = "\n\n?? <i>«Ì‰ ﬁÌ„ ùÂ« „Œ’Ê’ Â„ò«—Ì ‘„«” </i>" if user and user["is_agent"] else ""
        if not packages:
            send_or_edit(call, "?? œ— Õ«· Õ«÷— »” Âù«Ì »—«Ì ›—Ê‘ œ— «Ì‰ ‰Ê⁄ „ÊÃÊœ ‰Ì” .", kb)
        else:
            send_or_edit(call, f"?? ÌòÌ «“ ÅòÌÃùÂ« —« «‰ Œ«» ò‰Ìœ:{agent_note}", kb)
        return

    if data.startswith("buy:mu:"):
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>›—Ê‘ê«Â „Êﬁ «  ⁄ÿÌ· «” .</b>\n\n·ÿ›« »⁄œ« „—«Ã⁄Â ò‰Ìœ.", kb)
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
            stock_tag = "" if _pkg_has_stock(p, True) else " ?"
            _sn       = p['show_name'] if 'show_name' in p.keys() else 1
            _name_part = f"{p['name']}{stock_tag} | " if _sn else (f"{stock_tag} | " if stock_tag else "")
            title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)}  "
            kb.add(types.InlineKeyboardButton(title, callback_data=f"buy:p:{p['id']}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"buy:t:{type_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        agent_note = "\n\n?? <i>«Ì‰ ﬁÌ„ ùÂ« „Œ’Ê’ Â„ò«—Ì ‘„«” </i>" if user and user["is_agent"] else ""
        if not packages:
            send_or_edit(call, "?? œ— Õ«· Õ«÷— »” Âù«Ì »—«Ì ›—Ê‘ œ— «Ì‰ ‰Ê⁄ „ÊÃÊœ ‰Ì” .", kb)
        else:
            send_or_edit(call, f"?? ÌòÌ «“ ÅòÌÃùÂ« —« «‰ Œ«» ò‰Ìœ:{agent_note}", kb)
        return

    if data.startswith("buy:p:"):
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>›—Ê‘ê«Â „Êﬁ «  ⁄ÿÌ· «” .</b>\n\n·ÿ›« »⁄œ« „—«Ã⁄Â ò‰Ìœ.", kb)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        # ?? Buyer role enforcement ????????????????????????????????????????????
        buyer_role = package_row["buyer_role"] if "buyer_role" in package_row.keys() else "all"
        if buyer_role == "nobody":
            bot.answer_callback_query(call.id,
                "?? «Ì‰ ÅòÌÃ œ— œ” —” ⁄„Ê„ ‰Ì” .",
                show_alert=True)
            return
        if buyer_role != "all":
            _user = get_user(uid)
            _is_agent = bool(_user and _user["is_agent"])
            if buyer_role == "agents" and not _is_agent:
                bot.answer_callback_query(call.id,
                    "?? «Ì‰ ÅòÌÃ ›ﬁÿ »—«Ì ‰„«Ì‰œê«‰ ›⁄«· «” .\n\n"
                    "»—«Ì  ÂÌÂ «Ì‰ ÅòÌÃ »«Ìœ ‰„«Ì‰œÂ »«‘Ìœ.",
                    show_alert=True)
                return
            if buyer_role == "public" and _is_agent:
                bot.answer_callback_query(call.id,
                    "?? «Ì‰ ÅòÌÃ ›ﬁÿ »—«Ì ò«—»—«‰ ⁄«œÌ ﬁ«»· Œ—Ìœ «” .\n\n"
                    "‰„«Ì‰œê«‰ „Ã«“ »Â Œ—Ìœ «Ì‰ ÅòÌÃ ‰Ì” ‰œ.",
                    show_alert=True)
                return
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        price = get_effective_price(uid, package_row)
        _price_info = calculate_effective_order_price(uid, package_row)
        state_set(uid, "buy_select_method",
                  package_id=package_id, amount=price, original_amount=_price_info["original_unit_price"],
                  discount_amount=_price_info["discount_amount"],
                  kind="config_purchase", unit_price=price, quantity=1)
        bot.answer_callback_query(call.id)
        if should_show_bulk_qty(uid):
            _show_qty_prompt(call, package_row, price)
            return
        # Naming step for panel packages (single purchase, qty=1)
        if _is_panel_package(package_row):
            _show_naming_prompt(call, package_id, 1)
            return
        if setting_get("discount_codes_enabled", "0") == "1":
            if _show_discount_prompt(call, price):
                return
        _show_purchase_gateways(call, uid, package_id, price, package_row)
        return

    # ?? Naming step for panel packages ????????????????????????????????????????
    # buy:naming:{random|custom}:{package_id}:{quantity}
    if data.startswith("buy:naming:"):
        parts      = data.split(":")
        naming     = parts[2]          # "random" or "custom"
        package_id = int(parts[3])
        quantity   = int(parts[4])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
        bot.answer_callback_query(call.id)
        sd = state_data(uid)
        unit_price = int(sd.get("unit_price", 0) or 0)
        if not unit_price:
            # Recalculate if state lost (e.g. after bot restart)
            unit_price = get_effective_price(uid, package_row)
        total = unit_price * quantity
        if naming == "random":
            # Generate random name(s) and store in state, proceed to payment
            if quantity == 1:
                chosen_names = [generate_random_name()]
            else:
                chosen_names = [generate_random_name() for _ in range(quantity)]
            state_set(uid, "buy_select_method",
                      package_id=package_id, amount=total, original_amount=total,
                      unit_price=unit_price, quantity=quantity, kind="config_purchase",
                      service_names=chosen_names)
            if setting_get("discount_codes_enabled", "0") == "1":
                if _show_discount_prompt(call, total):
                    return
            _show_purchase_gateways(call, uid, package_id, total, package_row)
            return
        # naming == "custom"
        if quantity == 1:
            state_set(uid, "await_service_name",
                      package_id=package_id, unit_price=unit_price,
                      quantity=quantity, kind="config_purchase")
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"buy:naming:random:{package_id}:{quantity}",
                                              icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "?? <b>‰«„ ”—ÊÌ”</b>\n\n"
                "·ÿ›« ‰«„ œ·ŒÊ«Â ”—ÊÌ” ŒÊœ —« Ê«—œ ò‰Ìœ.\n"
                "‰«„ »«Ìœ ›ﬁÿ ‘«„· <b>Õ—Ê› «‰ê·Ì”Ì òÊçò</b> Ê <b>⁄œœ</b> »«‘œ.\n\n"
                "„À«·: <code>ali</code>  Ì«  <code>user1</code>",
                kb)
        else:
            state_set(uid, "await_bulk_service_names",
                      package_id=package_id, unit_price=unit_price,
                      quantity=quantity, kind="config_purchase")
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"buy:naming:random:{package_id}:{quantity}",
                                              icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                f"?? <b>‰«„ ”—ÊÌ”ùÂ«</b>\n\n"
                f"·ÿ›« <b>{quantity}</b> ‰«„ ”—ÊÌ” —« œ— Ìò ÅÌ«„ Ê Â—òœ«„ œ— Ìò Œÿ «—”«· ò‰Ìœ.\n"
                "‰«„ùÂ« »«Ìœ ›ﬁÿ ‘«„· Õ—Ê› «‰ê·Ì”Ì òÊçò Ê ⁄œœ »«‘‰œ.\n"
                "‰«„ùÂ«Ì ‰«„⁄ »— »Â ’Ê—  ŒÊœò«— —‰œÊ„ Ã«Ìê“Ì‰ „Ìù‘Ê‰œ.\n\n"
                f"„À«·:\n<code>user1\nuser2\nuser3</code>",
                kb)
        return

    if data.startswith("pay:wallet:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        user        = get_user(uid)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        preorder_on = setting_get("preorder_mode", "0") == "1"
        if not _pkg_has_stock(package_row, preorder_on):
            bot.answer_callback_query(call.id, "„ÊÃÊœÌ «Ì‰ ÅòÌÃ  „«„ ‘œÂ «” .", show_alert=True)
            return
        price    = _get_state_price(uid, package_row, "buy_select_method")
        quantity = int(state_data(uid).get("quantity", 1) or 1)
        if user["balance"] < price:
            if not can_use_credit(uid, price):
                bot.answer_callback_query(call.id, "„ÊÃÊœÌ òÌ› ÅÊ· ò«›Ì ‰Ì” .", show_alert=True)
                return
        # Deduct total and create payment record first
        update_balance(uid, -price)
        payment_id = create_payment("config_purchase", uid, package_id, price, "wallet",
                                    status="completed", quantity=quantity)
        _snames_wallet = state_data(uid).get("service_names")
        if _snames_wallet:
            set_payment_service_names(payment_id, _snames_wallet)
        complete_payment(payment_id)
        bot.answer_callback_query(call.id, "Œ—Ìœ »« „Ê›ﬁÌ  «‰Ã«„ ‘œ.")
        send_or_edit(call, "? Å—œ«Œ  «“ òÌ› ÅÊ· «‰Ã«„ ‘œ. ò«‰›ÌêùÂ«Ì ‘„« œ— Õ«· ¬„«œÂù”«“Ì Â” ‰œ...",
                     back_button("main"))
        purchase_ids, pending_ids = _deliver_bulk_configs(
            call.message.chat.id, uid, package_id, price, "wallet", quantity, payment_id,
            service_names=_snames_wallet
        )
        if not purchase_ids and not pending_ids:
            # Exceptional: refund and abort
            update_balance(uid, price)
            bot.send_message(uid,
                "?? <b>Œÿ« œ—  ÕÊÌ· ”—ÊÌ”</b>\n\n"
                "„ √”›«‰Â œ—  ÕÊÌ· ”—ÊÌ” „‘ò·Ì ÅÌ‘ ¬„œ Ê „»·€ »Â òÌ› ÅÊ· ‘„« »«“ê—œ«‰œÂ ‘œ.\n"
                "·ÿ›« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ.",
                parse_mode="HTML", reply_markup=back_button("main"))
            state_clear(uid)
            return
        _send_bulk_delivery_result(call.message.chat.id, uid, package_row,
                                   purchase_ids, pending_ids, "òÌ› ÅÊ·")
        state_clear(uid)
        return

    if data.startswith("pay:card:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "„ÊÃÊœÌ «Ì‰ ÅòÌÃ  „«„ ‘œÂ «” .", show_alert=True)
            return
        # Phone gate for card_only mode
        if setting_get("phone_mode", "disabled") == "card_only" and not get_phone_number(uid):
            from telebot.types import ReplyKeyboardMarkup, KeyboardButton
            state_set(uid, "waiting_for_phone_card", pending_package_id=package_id)
            bot.answer_callback_query(call.id)
            kb_phone = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            kb_phone.add(KeyboardButton("?? «—”«· ‘„«—Â  ·›‰", request_contact=True))
            bot.send_message(call.message.chat.id,
                "?? <b>À»  ‘„«—Â  ·›‰</b>\n\n"
                "»—«Ì Å—œ«Œ  ò«—  »Â ò«— ° «» œ« »«Ìœ ‘„«—Â  ·›‰ ŒÊœ —« À»  ò‰Ìœ.\n"
                "»« œò„Â “Ì— ‘„«—Â ŒÊœ —« «—”«· ò‰Ìœ:",
                parse_mode="HTML", reply_markup=kb_phone)
            return
        _ci = pick_card_for_payment()
        if not _ci:
            bot.answer_callback_query(call.id, "«ÿ·«⁄«  Å—œ«Œ  Â‰Ê“ À»  ‰‘œÂ «” .", show_alert=True)
            return
        card, bank, owner = _ci["card_number"], _ci["bank_name"], _ci["holder_name"]
        price      = _get_state_price(uid, package_row, "buy_select_method")
        price = apply_gateway_fee("card", price)
        if not is_gateway_in_range("card", price):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì «Ì‰ œ—ê«Â „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        _qty_card = int(state_data(uid).get("quantity", 1) or 1)
        payment_id = create_payment("config_purchase", uid, package_id, price, "card",
                                    status="pending", quantity=_qty_card)
        _snames_card = state_data(uid).get("service_names")
        if _snames_card:
            set_payment_service_names(payment_id, _snames_card)
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
            bot.answer_callback_query(call.id, "„ÊÃÊœÌ «Ì‰ ÅòÌÃ  „«„ ‘œÂ «” .", show_alert=True)
            return
        price    = _get_state_price(uid, package_row, "buy_select_method")
        _qty_cr  = int(state_data(uid).get("quantity", 1) or 1)
        if not is_gateway_in_range("crypto", price):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì «Ì‰ œ—ê«Â „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
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
                    bot.answer_callback_query(call.id, "„ÊÃÊœÌ  „«„ ‘œÂ «” .", show_alert=True)
                    return
                payment_id = create_payment("config_purchase", uid, package_id, amount, "crypto",
                                            status="pending", crypto_coin=coin_key, quantity=_qty_coin)
                _snames_crypto = sd.get("service_names")
                if _snames_crypto:
                    set_payment_service_names(payment_id, _snames_crypto)
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
            bot.send_message(uid, "?? Œÿ«ÌÌ —Œ œ«œ. ·ÿ›« œÊ»«—Â  ·«‘ ò‰Ìœ.",
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

    # ?? Crypto copy buttons use CopyTextButton (Bot API 7.0) ?????????????????
    # No callback handlers needed ó buttons copy directly to clipboard.
        show_main_menu(call)
        return

    # ?? Invoice expired restart ???????????????????????????????????????????????
    if data == "invoice:restart":
        bot.answer_callback_query(call.id)
        state_clear(uid)
        show_main_menu(call)
        return

    # ?? TetraPay ??????????????????????????????????????????????????????????????
    if data.startswith("pay:tetrapay:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
            return
        authority = payment["receipt_text"]
        success, result = verify_tetrapay_order(authority)
        if success:
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                try:
                    apply_gateway_bonus_if_needed(uid, "tetrapay", payment["amount"])
                except Exception:
                    pass
                bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
                send_or_edit(call, f"? Å—œ«Œ  ‘„«  √ÌÌœ Ê òÌ› ÅÊ· ‘«—é ‘œ.\n\n?? „»·€: {fmt_price(payment['amount'])}  Ê„«‰", back_button("main"))
                state_clear(uid)
            else:
                config_id  = payment["config_id"]
                package_id = payment["package_id"]
                package_row = get_package(package_id)
                _qty_tp    = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                    return
                bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
                send_or_edit(call, "? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ. ò«‰›ÌêùÂ«Ì ‘„« œ— Õ«· ¬„«œÂù”«“Ì Â” ‰œ...",
                             back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    call.message.chat.id, uid, package_id,
                    payment["amount"], "tetrapay", _qty_tp, payment_id,
                    service_names=get_payment_service_names(payment_id)
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
                f"? Å—œ«Œ  Â‰Ê“  «ÌÌœ ‰‘œÂ.\nÊ÷⁄Ì  TetraPay: {_st}\n\n·ÿ›« «» œ« Å—œ«Œ  —« œ— œ—ê«Â   —«ÅÌ «‰Ã«„ œÂÌœ.",
                show_alert=True)
        return

    if data.startswith("pay:tetrapay:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "„ÊÃÊœÌ «Ì‰ ÅòÌÃ  „«„ ‘œÂ «” .", show_alert=True)
            return
        price    = _get_state_price(uid, package_row, "buy_select_method")
        _qty_tetra = int(state_data(uid).get("quantity", 1) or 1)
        if not is_gateway_in_range("tetrapay", price):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â TetraPay „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        hash_id = f"cfg-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"Œ—Ìœ {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"Œ—Ìœ {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tetrapay_order(price, hash_id, order_label)
        if not success:
            bot.answer_callback_query(call.id, "Œÿ« œ— «ÌÃ«œ œ—ŒÊ«”  Å—œ«Œ  ¬‰·«Ì‰.", show_alert=True)
            return
        authority = result.get("Authority", "")
        pay_url_bot = result.get("payment_url_bot", "")
        pay_url_web = result.get("payment_url_web", "")
        payment_id = create_payment("config_purchase", uid, package_id, price, "tetrapay",
                                    status="pending", quantity=_qty_tetra)
        _snames_tetra = state_data(uid).get("service_names")
        if _snames_tetra:
            set_payment_service_names(payment_id, _snames_tetra)
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (authority, payment_id))
        state_set(uid, "await_tetrapay_verify", payment_id=payment_id, authority=authority)
        text = (
            "?? <b>Å—œ«Œ  ¬‰·«Ì‰ (TetraPay)</b>\n\n"
            f"?? „»·€: <b>{fmt_price(price)}</b>  Ê„«‰\n\n"
            "·ÿ›« «“ ÌòÌ «“ ·Ì‰òùÂ«Ì “Ì— Å—œ«Œ  —« «‰Ã«„ œÂÌœ.\n\n"
            "? <b> « Ìò ”«⁄ </b> «ê— Å—œ«Œ ù Ê‰  «ÌÌœ »‘Â »Â ’Ê—  ŒÊœò«— ⁄„·Ì«  «‰Ã«„ „Ìù‘Êœ.\n"
            "œ— €Ì— «Ì‰ ’Ê—  œò„Â <b>»——”Ì Å—œ«Œ </b> —« »“‰Ìœ."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  œ—  ·ê—«„", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  œ— „—Ê—ê—", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ", callback_data=f"pay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "config_purchase", package_id=package_id)
        return

    # ?? TronPays Rial: purchase ???????????????????????????????????????????????
    if data.startswith("pay:tronpays_rial:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        ok, status = check_tronpays_rial_invoice(invoice_id)
        if not ok:
            bot.answer_callback_query(call.id, "Œÿ« œ— »——”Ì Ê÷⁄Ì  ›«ò Ê—.", show_alert=True)
            return
        if is_tronpays_paid(status):
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
                send_or_edit(call, f"? Å—œ«Œ  ‘„«  √ÌÌœ Ê òÌ› ÅÊ· ‘«—é ‘œ.\n\n?? „»·€: {fmt_price(payment['amount'])}  Ê„«‰",
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
                    bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                    return
                bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
                send_or_edit(call, "? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ. ò«‰›ÌêùÂ«Ì ‘„« œ— Õ«· ¬„«œÂù”«“Ì Â” ‰œ...",
                             back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    call.message.chat.id, uid, package_id,
                    payment["amount"], "tronpays_rial", _qty_tron, payment_id,
                    service_names=get_payment_service_names(payment_id)
                )
                try:
                    apply_gateway_bonus_if_needed(uid, "tronpays_rial", payment["amount"])
                except Exception:
                    pass
                _send_bulk_delivery_result(call.message.chat.id, uid, package_row,
                                           purchase_ids, pending_ids, "TronPays")
                state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "? Å—œ«Œ  Â‰Ê“  √ÌÌœ ‰‘œÂ. ·ÿ›« «» œ« Å—œ«Œ  —« «‰Ã«„ œÂÌœ.", show_alert=True)
        return

    if data.startswith("pay:tronpays_rial:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "„ÊÃÊœÌ «Ì‰ ÅòÌÃ  „«„ ‘œÂ «” .", show_alert=True)
            return
        price   = _get_state_price(uid, package_row, "buy_select_method")
        _qty_tp_rial = int(state_data(uid).get("quantity", 1) or 1)
        if not is_gateway_in_range("tronpays_rial", price):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â TronPay „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        hash_id = f"cfg-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"Œ—Ìœ {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"Œ—Ìœ {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tronpays_rial_invoice(price, hash_id, order_label)
        if not success:
            err_msg = result.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>Œÿ« œ— «ÌÃ«œ œ—ê«Â TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "?? „ÿ„∆‰ ‘ÊÌœ ò·Ìœ API ’ÕÌÕ Ê«—œ ‘œÂ »«‘œ.",
                back_button(f"buy:p:{package_id}"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>Œÿ« œ— «ÌÃ«œ ›«ò Ê— TronPays</b>\n\n"
                f"<code>Å«”Œ API: {esc(str(result)[:400])}</code>",
                back_button(f"buy:p:{package_id}"))
            return
        payment_id = create_payment("config_purchase", uid, package_id, price, "tronpays_rial",
                                    status="pending", quantity=_qty_tp_rial)
        _snames_tp = state_data(uid).get("service_names")
        if _snames_tp:
            set_payment_service_names(payment_id, _snames_tp)
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_tronpays_rial_verify", payment_id=payment_id, invoice_id=invoice_id)
        text = (
            "?? <b>Å—œ«Œ  —Ì«·Ì (TronPays)</b>\n\n"
            f"?? „»·€: <b>{fmt_price(price)}</b>  Ê„«‰\n\n"
            "«“ ·Ì‰ò “Ì— Å—œ«Œ  —« «‰Ã«„ œÂÌœ.\n\n"
            "? <b> « Ìò ”«⁄ </b> Å—œ«Œ  »Â ’Ê—  ŒÊœò«— »——”Ì „Ìù‘Êœ.\n"
            "œ— €Ì— «Ì‰ ’Ê—  œò„Â ´»——”Ì Å—œ«Œ ª —« »“‰Ìœ."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  «“ œ—ê«Â TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ", callback_data=f"pay:tronpays_rial:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tronpays_rial_auto_verify(
            payment_id, invoice_id, uid,
            call.message.chat.id, call.message.message_id,
            "config_purchase", package_id=package_id)
        return

    # ?? Free test ?????????????????????????????????????????????????????????????
    if data == "test:start":
        _ft_mode = setting_get("free_test_mode", "everyone")
        user = get_user(uid)
        is_agent_user = user and user["is_agent"]
        if _ft_mode == "disabled":
            bot.answer_callback_query(call.id, " ”  —«Ìê«‰ €Ì—›⁄«· «” .", show_alert=True)
            return
        if _ft_mode == "agents_only" and not is_agent_user:
            bot.answer_callback_query(call.id, " ”  —«Ìê«‰ ›ﬁÿ »—«Ì ‰„«Ì‰œê«‰ ›⁄«· «” .", show_alert=True)
            return
        if is_agent_user:
            agent_limit = int(setting_get("agent_test_limit", "0") or "0")
            agent_period = setting_get("agent_test_period", "day")
            if agent_limit > 0:
                used = agent_test_count_in_period(uid, agent_period)
                if used >= agent_limit:
                    period_labels = {"day": "—Ê“", "week": "Â› Â", "month": "„«Â"}
                    bot.answer_callback_query(call.id,
                        f"‘„« ”ﬁ›  ”  —«Ìê«‰ ({agent_limit} ⁄œœ œ— {period_labels.get(agent_period, agent_period)}) —« «” ›«œÂ ò—œÂù«Ìœ.",
                        show_alert=True)
                    return
        else:
            if user_has_any_test(uid):
                bot.answer_callback_query(call.id, "‘„« ﬁ»·«  ”  —«Ìê«‰ ŒÊœ —« œ—Ì«›  ò—œÂù«Ìœ.", show_alert=True)
                return
        items = get_active_types()
        kb    = types.InlineKeyboardMarkup()
        has_any = False
        for item in items:
            packs = [p for p in get_packages(type_id=item['id'], price_only=0) if p['stock'] > 0]
            if packs:
                kb.add(types.InlineKeyboardButton(f"?? {item['name']}", callback_data=f"test:t:{item['id']}"))
                has_any = True
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        if not has_any:
            send_or_edit(call, "?? œ— Õ«· Õ«÷—  ”  —«Ìê«‰Ì „ÊÃÊœ ‰Ì” .", kb)
        else:
            send_or_edit(call, "?? <b> ”  —«Ìê«‰</b>\n\n‰Ê⁄ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("test:t:"):
        _ft_mode = setting_get("free_test_mode", "everyone")
        user = get_user(uid)
        is_agent_user = user and user["is_agent"]
        if _ft_mode == "disabled":
            bot.answer_callback_query(call.id, " ”  —«Ìê«‰ €Ì—›⁄«· «” .", show_alert=True)
            return
        if _ft_mode == "agents_only" and not is_agent_user:
            bot.answer_callback_query(call.id, " ”  —«Ìê«‰ ›ﬁÿ »—«Ì ‰„«Ì‰œê«‰ ›⁄«· «” .", show_alert=True)
            return
        if is_agent_user:
            agent_limit = int(setting_get("agent_test_limit", "0") or "0")
            agent_period = setting_get("agent_test_period", "day")
            if agent_limit > 0:
                used = agent_test_count_in_period(uid, agent_period)
                if used >= agent_limit:
                    period_labels = {"day": "—Ê“", "week": "Â› Â", "month": "„«Â"}
                    bot.answer_callback_query(call.id,
                        f"‘„« ”ﬁ›  ”  —«Ìê«‰ ({agent_limit} ⁄œœ œ— {period_labels.get(agent_period, agent_period)}) —« «” ›«œÂ ò—œÂù«Ìœ.",
                        show_alert=True)
                    return
        else:
            if user_has_any_test(uid):
                bot.answer_callback_query(call.id, "‘„« ﬁ»·«  ”  —«Ìê«‰ ŒÊœ —« œ—Ì«›  ò—œÂù«Ìœ.", show_alert=True)
                return
        type_id     = int(data.split(":")[2])
        type_row    = get_type(type_id)
        package_row = None
        for item in get_packages(type_id=type_id, price_only=0):
            if item["stock"] > 0:
                package_row = item
                break
        if not package_row:
            bot.answer_callback_query(call.id, "»—«Ì «Ì‰ ‰Ê⁄  ”  —«Ìê«‰ „ÊÃÊœ ‰Ì” .", show_alert=True)
            return
        config_id = reserve_first_config(package_row["id"])
        if not config_id:
            bot.answer_callback_query(call.id, " ”  —«Ìê«‰ «Ì‰ ‰Ê⁄  „«„ ‘œÂ «” .", show_alert=True)
            return
        try:
            purchase_id = assign_config_to_user(config_id, uid, package_row["id"], 0, "free_test", is_test=1)
        except Exception:
            release_reserved_config(config_id)
            bot.answer_callback_query(call.id, "?? Œÿ«ÌÌ —Œ œ«œ° ·ÿ›« œÊ»«—Â  ·«‘ ò‰Ìœ.", show_alert=True)
            return
        # Check stock level and notify admins if thresholds crossed (free test delivery)
        try:
            from ..ui.notifications import check_and_notify_stock
            check_and_notify_stock(package_row["id"], package_row["name"])
        except Exception:
            pass
        bot.answer_callback_query(call.id, " ”  —«Ìê«‰ «—”«· ‘œ.")
        send_or_edit(call, f"?  ”  —«Ìê«‰ ‰Ê⁄ <b>{esc(type_row['name'])}</b> ¬„«œÂ ‘œ.", back_button("main"))
        deliver_purchase_message(call.message.chat.id, purchase_id)
        return

    # ?? Wallet charge ?????????????????????????????????????????????????????????
    if data == "wallet:charge":
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>›—Ê‘ê«Â „Êﬁ «  ⁄ÿÌ· «” .</b>\n\n‘«—é òÌ› ÅÊ· œ— Õ«· Õ«÷— «„ò«‰ùÅ–Ì— ‰Ì” .", kb)
            return
        if not wallet_pay_enabled_for(uid):
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "? <b>‘«—é òÌ› ÅÊ·</b>\n\n«„ò«‰ «” ›«œÂ «“ òÌ› ÅÊ· œ— Õ«· Õ«÷— »—«Ì ‘„« ›⁄«· ‰Ì” .", kb)
            return
        state_set(uid, "await_wallet_amount")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>‘«—é òÌ› ÅÊ·</b>\n\n„»·€ „Ê—œ ‰Ÿ— —« »Â  Ê„«‰ Ê«—œ ò‰Ìœ:", kb)
        return

    if data == "wallet:charge:card":
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "«» œ« „»·€ —« Ê«—œ ò‰Ìœ.", show_alert=True)
            return
        if not is_gateway_in_range("card", amount):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(amount)}  Ê„«‰ »—«Ì «Ì‰ œ—ê«Â „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        _ci = pick_card_for_payment()
        if not _ci:
            bot.answer_callback_query(call.id, "«ÿ·«⁄«  Å—œ«Œ  Â‰Ê“ À»  ‰‘œÂ «” .", show_alert=True)
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
            bot.answer_callback_query(call.id, "«» œ« „»·€ —« Ê«—œ ò‰Ìœ.", show_alert=True)
            return
        if not is_gateway_in_range("crypto", amount):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(amount)}  Ê„«‰ »—«Ì «Ì‰ œ—ê«Â „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
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
            bot.answer_callback_query(call.id, "«» œ« „»·€ —« Ê«—œ ò‰Ìœ.", show_alert=True)
            return
        if not is_gateway_in_range("tetrapay", amount):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(amount)}  Ê„«‰ »—«Ì œ—ê«Â TetraPay „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        hash_id = f"wallet-{uid}-{int(datetime.now().timestamp())}"
        success, result = create_tetrapay_order(amount, hash_id, "‘«—é òÌ› ÅÊ·")
        if not success:
            bot.answer_callback_query(call.id, "Œÿ« œ— «ÌÃ«œ œ—ŒÊ«”  Å—œ«Œ  ¬‰·«Ì‰.", show_alert=True)
            return
        authority = result.get("Authority", "")
        pay_url_bot = result.get("payment_url_bot", "")
        pay_url_web = result.get("payment_url_web", "")
        payment_id = create_payment("wallet_charge", uid, None, amount, "tetrapay", status="pending")
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (authority, payment_id))
        state_set(uid, "await_tetrapay_verify", payment_id=payment_id, authority=authority)
        text = (
            "?? <b>‘«—é òÌ› ÅÊ· - Å—œ«Œ  ¬‰·«Ì‰ (TetraPay)</b>\n\n"
            f"?? „»·€: <b>{fmt_price(amount)}</b>  Ê„«‰\n\n"
            "·ÿ›« «“ ÌòÌ «“ ·Ì‰òùÂ«Ì “Ì— Å—œ«Œ  —« «‰Ã«„ œÂÌœ.\n\n"
            "? <b> « Ìò ”«⁄ </b> «ê— Å—œ«Œ ù Ê‰  «ÌÌœ »‘Â »Â ’Ê—  ŒÊœò«— òÌ› ÅÊ· ‘«—é „Ìù‘Êœ.\n"
            "œ— €Ì— «Ì‰ ’Ê—  œò„Â <b>»——”Ì Å—œ«Œ </b> —« »“‰Ìœ."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  œ—  ·ê—«„", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  œ— „—Ê—ê—", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ", callback_data=f"pay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "wallet_charge")
        return

    # ?? SwapWallet Crypto (network selection) ?????????????????????????????????
    if data == "wallet:charge:swapwallet_crypto":
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "«» œ« „»·€ —« Ê«—œ ò‰Ìœ.", show_alert=True)
            return
        if not is_gateway_in_range("swapwallet_crypto", amount):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(amount)}  Ê„«‰ »—«Ì œ—ê«Â SwapWallet „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import get_active_swapwallet_networks, NETWORK_LABELS as SW_NET_LABELS
        _active_nets = get_active_swapwallet_networks()
        if not _active_nets:
            bot.answer_callback_query(call.id, "ÂÌç «—“Ì »—«Ì SwapWallet ›⁄«· ‰‘œÂ «” .", show_alert=True)
            return
        state_set(uid, "swcrypto_network_select", kind="wallet_charge", amount=amount)
        kb = types.InlineKeyboardMarkup()
        if len(_active_nets) == 1:
            # Skip selection ó go directly with the only available network
            net = _active_nets[0][0]
            state_set(uid, "swcrypto_network_select", kind="wallet_charge", amount=amount)
            # Emit synthetic callback ó handled by swcrypto:net: branch below (force inline)
            _swc_sd = state_data(uid)
            _swc_sd["_auto_net"] = net
            order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
            success, result = create_swapwallet_crypto_invoice(amount, order_id, net, "‘«—é òÌ› ÅÊ·")
            if not success:
                err_msg = result.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result, dict) else str(result)
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
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>Å—œ«Œ  ò—ÌÅ Ê (SwapWallet)</b>\n\n‘»òÂ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data == "wallet:charge:tronpays_rial":
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "«» œ« „»·€ —« Ê«—œ ò‰Ìœ.", show_alert=True)
            return
        if not is_gateway_in_range("tronpays_rial", amount):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(amount)}  Ê„«‰ »—«Ì œ—ê«Â TronPay „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        order_id = f"wallet-{uid}-{int(datetime.now().timestamp())}"
        success, result = create_tronpays_rial_invoice(amount, order_id, "‘«—é òÌ› ÅÊ·")
        if not success:
            err_msg = result.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>Œÿ« œ— «ÌÃ«œ œ—ê«Â TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "?? „ÿ„∆‰ ‘ÊÌœ ò·Ìœ API ’ÕÌÕ Ê«—œ ‘œÂ »«‘œ.",
                back_button("wallet:charge"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>Œÿ« œ— «ÌÃ«œ ›«ò Ê— TronPays</b>\n\n"
                f"<code>Å«”Œ API: {esc(str(result)[:400])}</code>",
                back_button("wallet:charge"))
            return
        payment_id = create_payment("wallet_charge", uid, None, amount, "tronpays_rial", status="pending")
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_tronpays_rial_verify", payment_id=payment_id, invoice_id=invoice_id)
        text = (
            "?? <b>‘«—é òÌ› ÅÊ· ó TronPays</b>\n\n"
            f"?? „»·€: <b>{fmt_price(amount)}</b>  Ê„«‰\n\n"
            "«“ ·Ì‰ò “Ì— Å—œ«Œ  —« «‰Ã«„ œÂÌœ.\n\n"
            "? <b> « Ìò ”«⁄ </b> Å—œ«Œ  »Â ’Ê—  ŒÊœò«— »——”Ì „Ìù‘Êœ.\n"
            "œ— €Ì— «Ì‰ ’Ê—  œò„Â ´»——”Ì Å—œ«Œ ª —« »“‰Ìœ."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Å—œ«Œ  «“ œ—ê«Â TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ", callback_data=f"pay:tronpays_rial:verify:{payment_id}"))
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        success, inv = check_swapwallet_crypto_invoice(invoice_id)
        if not success:
            bot.answer_callback_query(call.id, "Œÿ« œ— »——”Ì Ê÷⁄Ì  ›«ò Ê—.", show_alert=True)
            return
        inv_status = inv.get("status", "")
        if inv_status in ("PAID", "COMPLETED") or inv.get("paidAt"):
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
                send_or_edit(call, f"? Å—œ«Œ  ‘„«  √ÌÌœ Ê òÌ› ÅÊ· ‘«—é ‘œ.\n\n?? „»·€: {fmt_price(payment['amount'])}  Ê„«‰",
                             back_button("main"))
                state_clear(uid)
            else:
                config_id  = payment["config_id"]
                package_id = payment["package_id"]
                package_row = get_package(package_id)
                _qty_sw = int(payment["quantity"]) if "quantity" in payment.keys() else 1
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                    return
                bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
                send_or_edit(call, "? Å—œ«Œ  ‘„«  √ÌÌœ ‘œ. ò«‰›ÌêùÂ«Ì ‘„« œ— Õ«· ¬„«œÂù”«“Ì Â” ‰œ...",
                             back_button("main"))
                purchase_ids, pending_ids = _deliver_bulk_configs(
                    call.message.chat.id, uid, package_id,
                    payment["amount"], "swapwallet_crypto", _qty_sw, payment_id,
                    service_names=get_payment_service_names(payment_id)
                )
                try:
                    apply_gateway_bonus_if_needed(uid, "swapwallet_crypto", payment["amount"])
                except Exception:
                    pass
                _send_bulk_delivery_result(call.message.chat.id, uid, package_row,
                                           purchase_ids, pending_ids, "SwapWallet Crypto")
                state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "? Å—œ«Œ  Â‰Ê“  √ÌÌœ ‰‘œÂ. ·ÿ›« «» œ« Ê«—Ì“ —« «‰Ã«„ œÂÌœ.", show_alert=True)
        return

    if data.startswith("pay:swapwallet_crypto:"):
        if not _check_invoice_valid(uid):
            _show_invoice_expired(call)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or not _pkg_has_stock(package_row, setting_get("preorder_mode", "0") == "1"):
            bot.answer_callback_query(call.id, "„ÊÃÊœÌ «Ì‰ ÅòÌÃ  „«„ ‘œÂ «” .", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "buy_select_method")
        _qty_sw_init = int(state_data(uid).get("quantity", 1) or 1)
        if not is_gateway_in_range("swapwallet_crypto", price):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â SwapWallet „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import get_active_swapwallet_networks, NETWORK_LABELS as SW_NET_LABELS
        _active_nets2 = get_active_swapwallet_networks()
        if not _active_nets2:
            bot.answer_callback_query(call.id, "ÂÌç «—“Ì »—«Ì SwapWallet ›⁄«· ‰‘œÂ «” .", show_alert=True)
            return
        state_set(uid, "swcrypto_network_select", kind="config_purchase", package_id=package_id, amount=price,
                  quantity=_qty_sw_init)
        kb = types.InlineKeyboardMarkup()
        if len(_active_nets2) == 1:
            # Only one network ó auto-select and go directly to payment
            net = _active_nets2[0][0]
            order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
            success, result = create_swapwallet_crypto_invoice(price, order_id, net, "Å—œ«Œ  ò—ÌÅ Ê")
            if not success:
                err_msg = result.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result, dict) else str(result)
                _swapwallet_error_inline(call, err_msg)
                return
            invoice_id = result.get("id", "")
            payment_id = create_payment("config_purchase", uid, package_id, price, "swapwallet_crypto",
                                        status="pending", quantity=_qty_sw_init)
            _snames_sw_init = state_data(uid).get("service_names")
            if _snames_sw_init:
                set_payment_service_names(payment_id, _snames_sw_init)
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
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"buy:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>Å—œ«Œ  ò—ÌÅ Ê (SwapWallet)</b>\n\n‘»òÂ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("rpay:swapwallet_crypto:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        success, inv = check_swapwallet_crypto_invoice(invoice_id)
        if not success:
            bot.answer_callback_query(call.id, "Œÿ« œ— »——”Ì Ê÷⁄Ì  ›«ò Ê—.", show_alert=True)
            return
        if inv.get("status") in ("PAID", "COMPLETED") or inv.get("paidAt"):
            if not complete_payment(payment_id):
                bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True)
                return
            package_row = get_package(payment["package_id"])
            config_id   = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ!")
            send_or_edit(call,
                "? <b>œ—ŒÊ«”   „œÌœ «—”«· ‘œ</b>\n\n"
                "?? œ—ŒÊ«”   „œÌœ ”—ÊÌ” ‘„« »« „Ê›ﬁÌ  À»  Ê »—«Ì Å‘ Ì»«‰Ì «—”«· ‘œ.\n"
                "? ·ÿ›« ò„Ì ’»— ò‰Ìœ° Å” «“ «‰Ã«„  „œÌœ »Â ‘„« «ÿ·«⁄ œ«œÂ ŒÊ«Âœ ‘œ.\n\n"
                "?? «“ ’»— Ê ‘òÌ»«ÌÌ ‘„« „ ‘ò—Ì„.",
                back_button("main"))
            if item:
                admin_renewal_notify(uid, item, package_row, payment["amount"], "SwapWallet Crypto")
            try:
                apply_gateway_bonus_if_needed(uid, "swapwallet_crypto", payment["amount"])
            except Exception:
                pass
            state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "? Å—œ«Œ  Â‰Ê“  √ÌÌœ ‰‘œÂ. ·ÿ›« «» œ« Ê«—Ì“ —« «‰Ã«„ œÂÌœ.", show_alert=True)
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("swapwallet_crypto", price):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â SwapWallet „Ã«“ ‰Ì” .\n"
                f"„ÕœÊœÂ „Ã«“: {_rng}\n\n"
                "·ÿ›« œ—ê«Â œÌê—Ì „ ‰«”» »« «Ì‰ „»·€ «‰ Œ«» ò‰Ìœ.",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import get_active_swapwallet_networks, NETWORK_LABELS as SW_NET_LABELS
        _active_nets3 = get_active_swapwallet_networks()
        if not _active_nets3:
            bot.answer_callback_query(call.id, "ÂÌç «—“Ì »—«Ì SwapWallet ›⁄«· ‰‘œÂ «” .", show_alert=True)
            return
        state_set(uid, "swcrypto_network_select", kind="renewal",
                  purchase_id=purchase_id, package_id=package_id,
                  amount=price, config_id=item["config_id"])
        kb = types.InlineKeyboardMarkup()
        if len(_active_nets3) == 1:
            # Only one network ó auto-select and go directly to payment
            net = _active_nets3[0][0]
            order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
            success, result = create_swapwallet_crypto_invoice(price, order_id, net, "Å—œ«Œ  ò—ÌÅ Ê")
            if not success:
                err_msg = result.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result, dict) else str(result)
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
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"renew:{purchase_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>Å—œ«Œ  ò—ÌÅ Ê (SwapWallet)</b>\n\n‘»òÂ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    # ?? SwapWallet Crypto: network selected ? create invoice ?????????????????
    if data.startswith("swcrypto:net:"):
        network = data.split(":")[2]
        sd      = state_data(uid)
        kind    = sd.get("kind", "")
        amount  = sd.get("amount", 0)
        if not amount:
            bot.answer_callback_query(call.id, "Œÿ« œ— «ÿ·«⁄«  ”›«—‘.", show_alert=True)
            return
        order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
        desc = "‘«—é òÌ› ÅÊ·" if kind == "wallet_charge" else "Å—œ«Œ  ò—ÌÅ Ê"
        success, result = create_swapwallet_crypto_invoice(amount, order_id, network, desc)
        if not success:
            err_msg = result.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result, dict) else str(result)
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
            _snames_swc = sd.get("service_names")
            if _snames_swc:
                set_payment_service_names(payment_id, _snames_swc)
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
            bot.answer_callback_query(call.id, "Œÿ« œ— ‰Ê⁄ Å—œ«Œ .", show_alert=True)
            return
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_swapwallet_crypto_verify", payment_id=payment_id, invoice_id=invoice_id)
        bot.answer_callback_query(call.id)
        show_swapwallet_crypto_page(call, amount_toman=amount, invoice_id=invoice_id,
                                    result=result, payment_id=payment_id, verify_cb=verify_cb)
        return

    # ?? Admin panel ????????????????????????????????????????????????????????????
    if not is_admin(uid):
        # Non-admin shouldn't reach admin callbacks, just ignore
        if data.startswith("admin:") or data.startswith("adm:"):
            bot.answer_callback_query(call.id, "«Ã«“Â œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return

    if data == "admin:panel":
        bot.answer_callback_query(call.id)
        footer = ""
        if uid in ADMIN_IDS:
            footer = (
                "\n\n????????????????\n"
                "?? <b>Seamless Premium</b>\n"
                "??û?? Developer: @EmadHabibnia"
            )
        text = (
            "?? <b>Å‰· „œÌ—Ì </b>\n\n"
            "»Œ‘ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:"
            f"{footer}"
        )
        send_or_edit(call, text, kb_admin_panel(uid))
        return

    # ?? Admin: Types ??????????????????????????????????????????????????????????
    if data == "admin:types":
        if not admin_has_perm(uid, "types_packages"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        _show_admin_types(call)
        bot.answer_callback_query(call.id)
        return

    if data == "admin:type:add":
        state_set(uid, "admin_add_type")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ‰«„ ‰Ê⁄ ÃœÌœ —« «—”«· ò‰Ìœ:", back_button("admin:types"))
        return

    if data.startswith("admin:type:edit:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "‰Ê⁄ Ì«›  ‰‘œ.", show_alert=True)
            return
        # Compute current position of this type
        from ..db import get_all_types as _gat
        _all = _gat()
        _cur_pos = next((i + 1 for i, t in enumerate(_all) if t["id"] == type_id), "?")
        _total   = len(_all)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ ‰«„", callback_data=f"admin:type:editname:{type_id}"))
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘  Ê÷ÌÕ« ", callback_data=f"admin:type:editdesc:{type_id}"))
        if row["description"]:
            kb.add(types.InlineKeyboardButton("?? Õ–›  Ê÷ÌÕ« ", callback_data=f"admin:type:deldesc:{type_id}"))
        is_active = row["is_active"] if "is_active" in row.keys() else 1
        status_label = "? ›⁄«· ó ò·Ìò »—«Ì €Ì—›⁄«·" if is_active else "? €Ì—›⁄«· ó ò·Ìò »—«Ì ›⁄«·"
        kb.add(types.InlineKeyboardButton(status_label, callback_data=f"admin:type:toggleactive:{type_id}"))
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ ÅòÌÃùÂ«", callback_data=f"admin:type:pkgs:{type_id}"))
        kb.add(types.InlineKeyboardButton(f"?? Ã«Ìê«Â (›⁄·« {_cur_pos} «“ {_total})", callback_data=f"admin:type:sortorder:{type_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:types", icon_custom_emoji_id="5253997076169115797"))
        desc_preview = f"\n??  Ê÷ÌÕ« : {esc(row['description'][:80])}..." if row["description"] and len(row["description"]) > 80 else (f"\n??  Ê÷ÌÕ« : {esc(row['description'])}" if row["description"] else "\n??  Ê÷ÌÕ« : ‰œ«—œ")
        status_line  = "\n?? Ê÷⁄Ì : <b>›⁄«·</b>" if is_active else "\n?? Ê÷⁄Ì : <b>€Ì—›⁄«·</b>"
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"?? <b>ÊÌ—«Ì‘ ‰Ê⁄:</b> {esc(row['name'])}{desc_preview}{status_line}\n?? Ã«Ìê«Â: <b>{_cur_pos}</b> «“ <b>{_total}</b>", kb)
        return

    if data.startswith("admin:type:pkgs:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "‰Ê⁄ Ì«›  ‰‘œ.", show_alert=True)
            return
        packs = get_packages(type_id=type_id, include_inactive=True)
        kb    = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? «›“Êœ‰ ÅòÌÃ", callback_data=f"admin:pkg:add:t:{type_id}"))
        for p in packs:
            pkg_active      = p["active"] if "active" in p.keys() else 1
            pkg_status_icon = "?" if pkg_active else "?"
            kb.row(
                types.InlineKeyboardButton(
                    f"{pkg_status_icon} ?? {p['name']} | {p['volume_gb']}GB | {fmt_price(p['price'])} ",
                    callback_data="noop"
                ),
                types.InlineKeyboardButton("??", callback_data=f"admin:pkg:edit:{p['id']}"),
                types.InlineKeyboardButton("??",  callback_data=f"admin:pkg:del:{p['id']}"),
            )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"admin:type:edit:{type_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"?? <b>ÅòÌÃùÂ«Ì ‰Ê⁄: {esc(row['name'])}</b>", kb)
        return

    if data.startswith("admin:type:sortorder:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "‰Ê⁄ Ì«›  ‰‘œ.", show_alert=True)
            return
        from ..db import get_all_types as _gat2
        _total2 = len(_gat2())
        state_set(uid, "admin_edit_type_order", type_id=type_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b> €ÌÌ— Ã«Ìê«Â ‰Ê⁄: {esc(row['name'])}</b>\n\n"
            f" ⁄œ«œ ò· ‰Ê⁄ùÂ«: <b>{_total2}</b>\n\n"
            "⁄œœ Ã«Ìê«Â ÃœÌœ («“ ?) —« «—”«· ò‰Ìœ:",
            back_button(f"admin:type:edit:{type_id}"))
        return

    if data.startswith("admin:type:editname:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "‰Ê⁄ Ì«›  ‰‘œ.", show_alert=True)
            return
        state_set(uid, "admin_edit_type", type_id=type_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"?? ‰«„ ÃœÌœ »—«Ì ‰Ê⁄ <b>{esc(row['name'])}</b> —« «—”«· ò‰Ìœ:",
                     back_button("admin:types"))
        return

    if data.startswith("admin:type:editdesc:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "‰Ê⁄ Ì«›  ‰‘œ.", show_alert=True)
            return
        state_set(uid, "admin_edit_type_desc", type_id=type_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?  Ê÷ÌÕ« Ì ‰„ÌùŒÊ«Â„ Ê«—œ ò‰„", callback_data=f"admin:type:deldesc:{type_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"admin:type:edit:{type_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"??  Ê÷ÌÕ«  ÃœÌœ »—«Ì ‰Ê⁄ <b>{esc(row['name'])}</b> —« «—”«· ò‰Ìœ:\n\n"
            "«Ì‰  Ê÷ÌÕ«  Å” «“ «—”«· ò«‰›Ìê »Â ò«—»— ‰„«Ì‘ œ«œÂ „Ìù‘Êœ.", kb)
        return

    if data == "admin:type:skipdesc":
        sn = state_name(uid)
        sd_val = state_data(uid)
        if sn == "admin_add_type_desc":
            name = sd_val.get("type_name", "")
            try:
                add_type(name, "")
                state_clear(uid)
                bot.answer_callback_query(call.id, "? ‰Ê⁄ À»  ‘œ.")
                bot.send_message(call.message.chat.id, "? ‰Ê⁄ ÃœÌœ À»  ‘œ.", reply_markup=kb_admin_panel())
                log_admin_action(uid, f"‰Ê⁄ ÃœÌœ À»  ‘œ: <b>{esc(name)}</b>")
            except sqlite3.IntegrityError:
                state_clear(uid)
                bot.answer_callback_query(call.id, "?? «Ì‰ ‰Ê⁄ ﬁ»·« À»  ‘œÂ.", show_alert=True)
        else:
            bot.answer_callback_query(call.id)
        return

    if data.startswith("admin:type:deldesc:"):
        type_id = int(data.split(":")[3])
        update_type_description(type_id, "")
        state_clear(uid)
        bot.answer_callback_query(call.id, "?  Ê÷ÌÕ«  Õ–› ‘œ.")
        log_admin_action(uid, f" Ê÷ÌÕ«  ‰Ê⁄ #{type_id} Õ–› ‘œ")
        _show_admin_types(call)
        return

    if data.startswith("admin:type:toggleactive:"):
        type_id = int(data.split(":")[3])
        row = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "‰Ê⁄ Ì«›  ‰‘œ.", show_alert=True)
            return
        cur = row["is_active"] if "is_active" in row.keys() else 1
        update_type_active(type_id, 0 if cur else 1)
        new_status = "€Ì—›⁄«·" if cur else "›⁄«·"
        bot.answer_callback_query(call.id, f"? ‰Ê⁄ {new_status} ‘œ.")
        log_admin_action(uid, f"‰Ê⁄ <b>{esc(row['name'])}</b> {new_status} ‘œ")
        # re-open the edit screen with updated state
        call.data = f"admin:type:edit:{type_id}"
        data      = call.data

    if data.startswith("admin:pkg:toggleactive:"):
        package_id = int(data.split(":")[3])
        pkg = get_package(package_id)
        if not pkg:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        toggle_package_active(package_id)
        cur = pkg["active"] if "active" in pkg.keys() else 1
        new_status = "€Ì—›⁄«·" if cur else "›⁄«·"
        bot.answer_callback_query(call.id, f"? ÅòÌÃ {new_status} ‘œ.")
        log_admin_action(uid, f"ÅòÌÃ <b>{esc(pkg['name'])}</b> {new_status} ‘œ")
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
                bot.answer_callback_query(call.id, f"? {sold_in_type} ò«‰›Ìê ›—ÊŒ Âù‘œÂ œ— «Ì‰ ‰Ê⁄ ÊÃÊœ œ«—œ.", show_alert=True)
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
                types.InlineKeyboardButton("? »·Â° Â„Â Õ–› ‘Êœ", callback_data=f"admin:type:delok:{type_id}"),
                types.InlineKeyboardButton("? «‰’—«›", callback_data="admin:types"),
            )
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b> √ÌÌœ Õ–› ‰Ê⁄</b>\n\n"
                f"{pack_count} ÅòÌÃ Ê {total_cfg} ò«‰›Ìê („ÊÃÊœ/„‰ﬁ÷Ì) Â„—«Â »« «Ì‰ ‰Ê⁄ Õ–› ŒÊ«Â‰œ ‘œ.\n"
                "¬Ì« „ÿ„∆‰ Â” Ìœø", kb_c)
            return
        delete_type(type_id)
        bot.answer_callback_query(call.id, "? ‰Ê⁄ Õ–› ‘œ.")
        log_admin_action(uid, f"‰Ê⁄ #{type_id} Õ–› ‘œ")
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
            bot.answer_callback_query(call.id, "? œ— «Ì‰ ›«’·Â ò«‰›Ìê ›—ÊŒ Â ‘œ. Õ–› „„ò‰ ‰Ì” .", show_alert=True)
            _show_admin_types(call)
            return
        delete_type(type_id)
        bot.answer_callback_query(call.id, "? ‰Ê⁄ Ê  „«„ ÅòÌÃùÂ«Ì ¬‰ Õ–› ‘œ‰œ.")
        log_admin_action(uid, f"‰Ê⁄ #{type_id} »«  „«„ ÅòÌÃùÂ« Õ–› ‘œ")
        _show_admin_types(call)
        return

    if data.startswith("admin:pkg:add:t:"):
        type_id  = int(data.split(":")[4])
        type_row = get_type(type_id)
        state_set(uid, "admin_add_package_name", type_id=type_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"?? ‰«„ ÅòÌÃ »—«Ì ‰Ê⁄ <b>{esc(type_row['name'])}</b> —« Ê«—œ ò‰Ìœ:",
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
            "?? ÕÃ„ ÅòÌÃ —« »Â êÌê Ê«—œ ò‰Ìœ:\n"
            "?? »—«Ì ÕÃ„ ‰«„ÕœÊœ ⁄œœ <b>0</b> »›—” Ìœ.\n"
            "?? »—«Ì ò„ — «“ ? êÌê «⁄‘«— Ê«—œ ò‰Ìœ („À·« <b>0.5</b>).",
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
            types.InlineKeyboardButton("?? À»  œ” Ì",    callback_data="admin:pkg:add:cs:manual"),
            types.InlineKeyboardButton("?? « ’«· »Â Å‰·", callback_data="admin:pkg:add:cs:panel"),
        )
        send_or_edit(call,
            "?? <b>„‰»⁄ ò«‰›Ìê</b>\n\n"
            "ò«‰›ÌêùÂ«Ì «Ì‰ ÅòÌÃ çÿÊ—  «„Ì‰ „Ìù‘Ê‰œ?\n\n"
            "ï <b>À»  œ” Ì</b> ó ò«‰›Ìê —« «“ »Œ‘ „ÊÃÊœÌ ¬Å·Êœ ò‰Ìœ\n"
            "ï <b>« ’«· »Â Å‰·</b> ó Å” «“ Œ—Ìœ° ò«‰›Ìê »Âù’Ê—  ŒÊœò«— œ— Å‰· ”«Œ Â „Ìù‘Êœ",
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
        log_admin_action(uid, f"ÅòÌÃ '{sd['package_name']}' (œ” Ì) À»  ‘œ")
        state_clear(uid)
        _br_labels = {"all": "Â„Â", "agents": "›ﬁÿ ‰„«Ì‰œê«‰", "public": "›ﬁÿ ò«—»—«‰ ⁄«œÌ", "nobody": "ÂÌçùò” (›ﬁÿ ÂœÌÂ)"}
        vol_label = "ÕÃ„ ‰«„ÕœÊœ" if sd["volume"] == 0 else fmt_vol(sd["volume"])
        dur_label = "“„«‰ ‰«„ÕœÊœ" if sd["duration"] == 0 else f"{sd['duration']} —Ê“"
        pri_label = "—«Ìê«‰" if sd["price"] == 0 else f"{fmt_price(sd['price'])}  Ê„«‰"
        bot.answer_callback_query(call.id, "? ÅòÌÃ À»  ‘œ.")
        send_or_edit(call,
            f"? ÅòÌÃ œ” Ì »« „Ê›ﬁÌ  À»  ‘œ.\n\n"
            f"?? <b>{esc(sd['package_name'])}</b>\n"
            f"?? ÕÃ„: {vol_label}\n"
            f"? „œ : {dur_label}\n"
            f"?? ﬁÌ„ : {pri_label}\n"
            f"?? Œ—Ìœ«—«‰: {_br_labels.get(buyer_role, buyer_role)}\n"
            f"?? „‰»⁄: À»  œ” Ì",
            back_button("admin:types"))
        return

    if data == "admin:pkg:add:cs:panel":
        if state_name(uid) != "admin_add_package_config_source" or not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        panels = get_all_panels()
        if not panels:
            bot.answer_callback_query(call.id, "ÂÌç Å‰·Ì À»  ‰‘œÂ «” . «» œ« Ìò Å‰· «÷«›Â ò‰Ìœ.", show_alert=True)
            return
        sd = state_data(uid)
        state_set(uid, "admin_add_package_panel", **{k: v for k, v in sd.items()})
        kb_pnl = types.InlineKeyboardMarkup()
        for p in panels:
            icon = "??" if p["connection_status"] == "connected" else "??"
            kb_pnl.add(types.InlineKeyboardButton(f"{icon} {p['name']}", callback_data=f"admin:pkg:add:pnl:{p['id']}"))
        kb_pnl.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:types",
                                               icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? Å‰·Ì —« òÂ ò«‰›ÌêùÂ«Ì «Ì‰ ÅòÌÃ —ÊÌ ¬‰ ”«Œ Â „Ìù‘Ê‰œ «‰ Œ«» ò‰Ìœ:", kb_pnl)
        return

    if data.startswith("admin:pkg:add:pnl:"):
        if state_name(uid) != "admin_add_package_panel" or not is_admin(uid):
            bot.answer_callback_query(call.id)
            return
        panel_id = int(data.split(":")[4])
        panel    = get_panel(panel_id)
        if not panel:
            bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True)
            return
        # Show client packages for this panel
        cpkgs = get_panel_client_packages(panel_id)
        if not cpkgs:
            bot.answer_callback_query(call.id,
                "«Ì‰ Å‰· ÂÌç ò·«Ì‰  ÅòÌÃÌ ‰œ«—œ.\n"
                "«» œ« «“ „œÌ—Ì  Å‰· ? ò·«Ì‰  ÅòÌÃùÂ« Ìò ò·«Ì‰  ÅòÌÃ «÷«›Â ò‰Ìœ.",
                show_alert=True)
            return
        _DM = {"config_only": "?? ò«‰›Ìê", "sub_only": "?? ”«»", "both": "??+?? Â— œÊ"}
        sd = state_data(uid)
        state_set(uid, "admin_add_package_cpkg_select", panel_id=panel_id,
                  **{k: v for k, v in sd.items() if k != "panel_id"})
        kb_cp = types.InlineKeyboardMarkup()
        for cp in cpkgs:
            name = cp["name"] or f"«Ì‰»«‰œ #{cp['inbound_id']}"
            dm_label = _DM.get(cp["delivery_mode"], cp["delivery_mode"])
            kb_cp.add(types.InlineKeyboardButton(
                f"?? {name}  ({dm_label})",
                callback_data=f"admin:pkg:add:cpkg:{cp['id']}",
            ))
        kb_cp.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:types",
                                              icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? Å‰·: <b>{esc(panel['name'])}</b>\n\n"
            "Ìò <b>ò·«Ì‰  ÅòÌÃ</b> —« «‰ Œ«» ò‰Ìœ:",
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
            bot.answer_callback_query(call.id, "ò·«Ì‰  ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
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
        log_admin_action(uid, f"ÅòÌÃ Å‰·Ì '{sd['package_name']}' »« ò·«Ì‰  ÅòÌÃ #{cpkg_id} À»  ‘œ")
        state_clear(uid)
        _DM_LABELS = {"config_only": "›ﬁÿ ò«‰›Ìê", "sub_only": "›ﬁÿ ”«»", "both": "ò«‰›Ìê + ”«»"}
        bot.answer_callback_query(call.id, "? ÅòÌÃ À»  ‘œ.")
        send_or_edit(call,
            f"? ÅòÌÃ Å‰·Ì »« „Ê›ﬁÌ  À»  ‘œ.\n\n"
            f"?? <b>{esc(sd['package_name'])}</b>\n"
            f"?? ÕÃ„: {'‰«„ÕœÊœ' if sd['volume'] == 0 else fmt_vol(sd['volume'])}\n"
            f"? „œ : {'‰«„ÕœÊœ' if sd['duration'] == 0 else str(sd['duration']) + ' —Ê“'}\n"
            f"?? ﬁÌ„ : {'—«Ìê«‰' if sd['price'] == 0 else fmt_price(sd['price']) + '  Ê„«‰'}\n"
            f"?? ò·«Ì‰  ÅòÌÃ: {cp['name'] or '«Ì‰»«‰œ #' + str(cp['inbound_id'])}\n"
            f"??  ÕÊÌ·: {_DM_LABELS[cp['delivery_mode']]}",
            back_button("admin:types"))
        return



    if data.startswith("admin:pkg:edit:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
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
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        cur_sn  = package_row['show_name'] if 'show_name' in package_row.keys() else 1
        new_sn  = 0 if cur_sn else 1
        update_package_field(package_id, "show_name", new_sn)
        log_admin_action(uid, f"‰„«Ì‘ ‰«„ ÅòÌÃ #{package_id} {'›⁄«·' if new_sn else '€Ì—›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, "?  ‰ŸÌ„ ‰„«Ì‘ ‰«„ »—Ê“—”«‰Ì ‘œ.")
        package_row = get_package(package_id)
        text, kb = _pkg_edit_text_kb(package_row)
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pkg:set_br:"):
        # Show buyer_role selection for a package
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        buyer_role = package_row["buyer_role"] if "buyer_role" in package_row.keys() else "all"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("? Â„Â"               if buyer_role == "all"     else "Â„Â",
                                       callback_data=f"admin:pkg:br:all:{package_id}"),
            types.InlineKeyboardButton("? ›ﬁÿ ‰„«Ì‰œê«‰"     if buyer_role == "agents"  else "›ﬁÿ ‰„«Ì‰œê«‰",
                                       callback_data=f"admin:pkg:br:agents:{package_id}"),
            types.InlineKeyboardButton("? ›ﬁÿ ò«—»—«‰ ⁄«œÌ"  if buyer_role == "public"  else "›ﬁÿ ò«—»—«‰ ⁄«œÌ",
                                       callback_data=f"admin:pkg:br:public:{package_id}"),
        )
        kb.add(types.InlineKeyboardButton("? ÂÌçùò” (›ﬁÿ ÂœÌÂ)" if buyer_role == "nobody" else "ÂÌçùò” (›ﬁÿ ÂœÌÂ)",
                                          callback_data=f"admin:pkg:br:nobody:{package_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"admin:pkg:edit:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>{esc(package_row['name'])}</b>\n\n"
            "?? çÂ ò”«‰Ì » Ê«‰‰œ «Ì‰ ÅòÌÃ —« »Œ—‰œø\n\n"
            "ï <b>Â„Â</b> ó Â„ ò«—»—«‰ ⁄«œÌ° Â„ ‰„«Ì‰œê«‰\n"
            "ï <b>›ﬁÿ ‰„«Ì‰œê«‰</b> ó ›ﬁÿ ò«—»—«‰ ‰„«Ì‰œÂ\n"
            "ï <b>›ﬁÿ ò«—»—«‰ ⁄«œÌ</b> ó ›ﬁÿ ò«—»—«‰ €Ì—‰„«Ì‰œÂ\n"
            "ï <b>ÂÌçùò”</b> ó ÅòÌÃ œ— Œ—Ìœ ⁄«œÌ ‰„«Ì‘ œ«œÂ ‰„Ìù‘Êœ° ›ﬁÿ »—«Ì  ÕÊÌ· ÂœÌÂ", kb)
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
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        update_package_field(package_id, "buyer_role", role)
        log_admin_action(uid, f"buyer_role ÅòÌÃ #{package_id} »Â {role}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, "? „ÕœÊœÌ  Œ—Ìœ«— »—Ê“—”«‰Ì ‘œ.")
        package_row = get_package(package_id)
        text, kb = _pkg_edit_text_kb(package_row)
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pkg:ef:"):
        parts      = data.split(":")
        field_key  = parts[3]
        package_id = int(parts[4])
        state_set(uid, "admin_edit_pkg_field", field_key=field_key, package_id=package_id)
        labels     = {"name": "‰«„", "price": "ﬁÌ„  ( Ê„«‰)", "volume": "ÕÃ„ (GB)", "dur": "„œ  (—Ê“)", "position": "Ã«Ìê«Â ‰„«Ì‘", "maxusers": "„ÕœÊœÌ  ò«—»— (0=‰«„ÕœÊœ)"}
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"?? „ﬁœ«— ÃœÌœ »—«Ì <b>{labels.get(field_key, field_key)}</b> —« Ê«—œ ò‰Ìœ:",
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
                bot.answer_callback_query(call.id, f"? «Ì‰ ÅòÌÃ {sold_count} ò«‰›Ìê ›—ÊŒ Âù‘œÂ œ«—œ Ê ﬁ«»· Õ–› ‰Ì” .", show_alert=True)
                return
            unsold_cfg = conn.execute(
                "SELECT COUNT(*) AS n FROM configs WHERE package_id=?",
                (package_id,)
            ).fetchone()["n"]
        if unsold_cfg > 0:
            kb_c = types.InlineKeyboardMarkup()
            kb_c.row(
                types.InlineKeyboardButton("? »·Â° Õ–› ‘Êœ", callback_data=f"admin:pkg:delok:{package_id}"),
                types.InlineKeyboardButton("? «‰’—«›", callback_data="admin:types"),
            )
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b> √ÌÌœ Õ–› ÅòÌÃ</b>\n\n"
                f"{unsold_cfg} ò«‰›Ìê „ÊÃÊœ/„‰ﬁ÷Ì Â„—«Â »« ÅòÌÃ Õ–› ŒÊ«Â‰œ ‘œ.\n"
                "¬Ì« „ÿ„∆‰ Â” Ìœø", kb_c)
            return
        delete_package(package_id)
        bot.answer_callback_query(call.id, "? ÅòÌÃ Õ–› ‘œ.")
        log_admin_action(uid, f"ÅòÌÃ #{package_id} Õ–› ‘œ")
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
            bot.answer_callback_query(call.id, "? œ— «Ì‰ ›«’·Â ò«‰›Ìê ›—ÊŒ Â ‘œ. Õ–› „„ò‰ ‰Ì” .", show_alert=True)
            _show_admin_types(call)
            return
        delete_package(package_id)
        bot.answer_callback_query(call.id, "? ÅòÌÃ Ê ò«‰›ÌêùÂ«Ì ¬‰ Õ–› ‘œ‰œ.")
        log_admin_action(uid, f"ÅòÌÃ #{package_id} »« ò«‰›ÌêùÂ« Õ–› ‘œ")
        _show_admin_types(call)
        return

    # ?? Admin: Package config_source edit ?????????????????????????????????????
    if data.startswith("admin:pkg:src:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row or not is_admin(uid):
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        try:
            config_source = package_row["config_source"] or "manual"
        except (IndexError, KeyError):
            config_source = "manual"
        kb_src = types.InlineKeyboardMarkup()
        kb_src.row(
            types.InlineKeyboardButton(
                "? À»  œ” Ì" if config_source == "manual" else "À»  œ” Ì",
                callback_data=f"admin:pkg:scs:manual:{package_id}"),
            types.InlineKeyboardButton(
                "? « ’«· »Â Å‰·" if config_source == "panel" else "« ’«· »Â Å‰·",
                callback_data=f"admin:pkg:scs:panel:{package_id}"),
        )
        kb_src.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"admin:pkg:edit:{package_id}",
                                              icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>{esc(package_row['name'])}</b>\n\n"
            "?? „‰»⁄ ò«‰›Ìê «Ì‰ ÅòÌÃ —« «‰ Œ«» ò‰Ìœ:", kb_src)
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
        log_admin_action(uid, f"ÅòÌÃ #{package_id} „‰»⁄ ò«‰›Ìê »Â œ” Ì  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, "? „‰»⁄ ò«‰›Ìê »Â œ” Ì  €ÌÌ— ò—œ.")
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
            bot.answer_callback_query(call.id, "ÂÌç Å‰·Ì À»  ‰‘œÂ «” .", show_alert=True)
            return
        state_set(uid, "admin_edit_pkg_panel_select", package_id=package_id)
        kb_pnl = types.InlineKeyboardMarkup()
        for p in panels:
            icon = "??" if p["connection_status"] == "connected" else "??"
            kb_pnl.add(types.InlineKeyboardButton(f"{icon} {p['name']}", callback_data=f"admin:pkg:spnl:{p['id']}:{package_id}"))
        kb_pnl.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"admin:pkg:src:{package_id}",
                                               icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? Å‰· „ﬁ’œ —« «‰ Œ«» ò‰Ìœ:", kb_pnl)
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
            bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True)
            return
        # Show client packages for this panel
        cpkgs = get_panel_client_packages(panel_id)
        if not cpkgs:
            bot.answer_callback_query(call.id,
                "«Ì‰ Å‰· ÂÌç ò·«Ì‰  ÅòÌÃÌ ‰œ«—œ.\n"
                "«» œ« «“ „œÌ—Ì  Å‰· ? ò·«Ì‰  ÅòÌÃùÂ« Ìò ò·«Ì‰  ÅòÌÃ «÷«›Â ò‰Ìœ.",
                show_alert=True)
            return
        _DM = {"config_only": "?? ò«‰›Ìê", "sub_only": "?? ”«»", "both": "??+?? Â— œÊ"}
        kb_cp = types.InlineKeyboardMarkup()
        for cp in cpkgs:
            name = cp["name"] or f"«Ì‰»«‰œ #{cp['inbound_id']}"
            dm_label = _DM.get(cp["delivery_mode"], cp["delivery_mode"])
            kb_cp.add(types.InlineKeyboardButton(
                f"?? {name}  ({dm_label})",
                callback_data=f"admin:pkg:cpkg:{cp['id']}:{package_id}",
            ))
        kb_cp.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"admin:pkg:src:{package_id}",
                                              icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? Å‰·: <b>{esc(panel['name'])}</b>\n\n"
            "Ìò <b>ò·«Ì‰  ÅòÌÃ</b> —« «‰ Œ«» ò‰Ìœ:\n"
            "<i>(Â— ò·«Ì‰  ÅòÌÃ = «Ì‰»«‰œ + ‰Ê⁄  ÕÊÌ· + ﬁ«·» ò«‰›Ìê)</i>",
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
            bot.answer_callback_query(call.id, "ò·«Ì‰  ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        update_package_panel_settings(
            package_id, "panel",
            panel_id=cp["panel_id"],
            panel_type="sanaei",
            panel_port=cp["inbound_id"],
            delivery_mode=cp["delivery_mode"],
            client_package_id=cpkg_id,
        )
        log_admin_action(uid, f"ÅòÌÃ #{package_id} »Â ò·«Ì‰  ÅòÌÃ #{cpkg_id} (Å‰· #{cp['panel_id']}) „ ’· ‘œ")
        state_clear(uid)
        bot.answer_callback_query(call.id, "? « ’«· Å‰·  ‰ŸÌ„ ‘œ.")
        package_row = get_package(package_id)
        text, kb = _pkg_edit_text_kb(package_row)
        send_or_edit(call, text, kb)
        return



    # ?? Admin: Panel Configs list ??????????????????????????????????????????????
    if data == "admin:panel_configs":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        from ..admin.renderers import _show_panel_configs
        _show_panel_configs(call)
        return

    if data.startswith("admin:pcfg:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        from ..admin.renderers import (
            _show_panel_configs, _show_panel_config_list,
            _show_panel_config_pkg, _show_panel_config_detail,
        )
        bot.answer_callback_query(call.id)

        if data == "admin:pcfg:search":
            state_set(uid, "admin_pcfg_search")
            send_or_edit(call,
                "?? ⁄»«—  Ã” ÃÊ —« Ê«—œ ò‰Ìœ:\n"
                "(‰«„ ò·«Ì‰ ° ‰«„ ÅòÌÃ° ·Ì‰ò ò«‰›Ìê Ì« ·Ì‰ò ”«»)",
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

        # admin:pcfg:d:{config_id}  ó detail view
        if data.startswith("admin:pcfg:d:"):
            config_id = int(data.split(":")[-1])
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:qrc:{config_id}  ó QR for config
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
                    bot.send_photo(uid, bio, caption="?? QR ò«‰›Ìê")
                except Exception as e:
                    bot.send_message(uid, f"Œÿ« œ— QR: {e}")
            else:
                bot.answer_callback_query(call.id, "ò«‰›Ìê „ÊÃÊœ ‰Ì” .", show_alert=True)
            return

        # admin:pcfg:qrs:{config_id}  ó QR for subscription
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
                    bot.send_photo(uid, bio, caption="?? QR ”«»”ò—«Ì»")
                except Exception as e:
                    bot.send_message(uid, f"Œÿ« œ— QR: {e}")
            else:
                bot.answer_callback_query(call.id, "·Ì‰ò ”«» „ÊÃÊœ ‰Ì” .", show_alert=True)
            return

        # admin:pcfg:autorenew:{config_id}  ó toggle auto-renew
        if data.startswith("admin:pcfg:autorenew:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True); return
            new_val = 0 if int(cfg["auto_renew"] or 0) else 1
            update_panel_config_field(config_id, "auto_renew", new_val)
            label = "›⁄«·" if new_val else "€Ì—›⁄«·"
            bot.answer_callback_query(call.id, f" „œÌœ ŒÊœò«— {label} ‘œ.")
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:toggle:{config_id}  ó enable/disable on panel
        if data.startswith("admin:pcfg:toggle:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            if not panel:
                bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True); return
            cur_disabled = int(cfg.get("is_disabled") or 0)
            send_or_edit(call, "? œ— Õ«· «— »«ÿ »« Å‰·Ö")
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
                    send_or_edit(call, f"? Œÿ« œ— ›⁄«·ù”«“Ì:\n<code>{esc(str(err))}</code>",
                                 back_button(f"admin:pcfg:d:{config_id}")); return
            else:
                ok, err = pc_api.disable_client(
                    inbound_id=cfg["inbound_id"], client_uuid=cfg["client_uuid"],
                    email=cfg["client_name"] or "", traffic_bytes=0, expire_ms=0,
                )
                if ok:
                    update_panel_config_field(config_id, "is_disabled", 1)
                else:
                    send_or_edit(call, f"? Œÿ« œ— €Ì—›⁄«·ù”«“Ì:\n<code>{esc(str(err))}</code>",
                                 back_button(f"admin:pcfg:d:{config_id}")); return
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:rsub:{config_id}  ó regenerate subscription link
        if data.startswith("admin:pcfg:rsub:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            cpkg = get_panel_client_package(cfg["cpkg_id"]) if cfg.get("cpkg_id") else None
            if not cpkg or not cfg.get("client_uuid"):
                bot.answer_callback_query(call.id, "«ÿ·«⁄«  ﬁ«·» ò«‰›Ìê ‰«ﬁ’ «” .", show_alert=True); return
            import uuid as _uuid
            new_sub_id = str(_uuid.uuid4()).replace("-", "")[:16]
            cpkg_d = dict(cpkg)
            new_sub_url = _build_sub_from_template(cpkg_d, new_sub_id) if cpkg_d.get("sample_sub_url") else None
            if not new_sub_url:
                bot.answer_callback_query(call.id, "ﬁ«·» ”«» œ— cpkg  ‰ŸÌ„ ‰‘œÂ.", show_alert=True); return
            # Update panel
            if panel:
                send_or_edit(call, "? œ— Õ«· «— »«ÿ »« Å‰·Ö")
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
                    send_or_edit(call, f"? Œÿ« œ— »—Ê“—”«‰Ì ”«» —ÊÌ Å‰·:\n<code>{esc(str(err_sub))}</code>",
                                 back_button(f"admin:pcfg:d:{config_id}")); return
            # Save to DB
            update_panel_config_texts(config_id, cfg["client_config_text"], new_sub_url)
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:ruuid:{config_id}  ó regenerate UUID / config
        if data.startswith("admin:pcfg:ruuid:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            cpkg = get_panel_client_package(cfg["cpkg_id"]) if cfg.get("cpkg_id") else None
            if not cpkg or not panel:
                bot.answer_callback_query(call.id, "«ÿ·«⁄«  ﬁ«·» Ì« Å‰· ‰«ﬁ’.", show_alert=True); return
            cpkg_d = dict(cpkg)
            import uuid as _uuid
            new_uuid   = str(_uuid.uuid4())
            new_sub_id = new_uuid.replace("-", "")[:16]
            new_sub    = _build_sub_from_template(cpkg_d, new_sub_id) if cpkg_d.get("sample_sub_url") else cfg["client_sub_url"]
            send_or_edit(call, "? œ— Õ«· «— »«ÿ »« Å‰·Ö")
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
                send_or_edit(call, f"? Œÿ« œ— ”«Œ  ò·«Ì‰  ÃœÌœ:\n<code>{esc(str(res))}</code>",
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

        # admin:pcfg:renew:{config_id}  ó manual renew: show package list
        if data.startswith("admin:pcfg:renew:") and not data.startswith("admin:pcfg:renewok:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config_full(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True); return
            cfg = dict(cfg)
            type_id = cfg.get("type_id")
            pkgs = [p for p in (get_packages(type_id=type_id, include_inactive=False) or []) if p["active"]]
            if not pkgs:
                bot.answer_callback_query(call.id, "ÅòÌÃ ”«“ê«— Ì«›  ‰‘œ.", show_alert=True); return
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup()
            for p in pkgs:
                kb.add(InlineKeyboardButton(
                    f"?? {esc(p['name'])} | {fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(p['price'])} ",
                    callback_data=f"admin:pcfg:renewok:{config_id}:{p['id']}"
                ))
            kb.add(InlineKeyboardButton("·€Ê", callback_data=f"admin:pcfg:d:{config_id}",
                                        icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call, f"?? ÅòÌÃ „Ê—œ ‰Ÿ— »—«Ì  „œÌœ —« «‰ Œ«» ò‰Ìœ:", kb)
            return

        # admin:pcfg:renewok:{config_id}:{package_id}
        if data.startswith("admin:pcfg:renewok:"):
            parts     = data.split(":")
            config_id = int(parts[3])
            pkg_id    = int(parts[4])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True); return
            pkg = get_package(pkg_id)
            if not pkg:
                bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
            panel = get_panel(cfg["panel_id"])
            if not panel:
                bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True); return
            send_or_edit(call, "? œ— Õ«·  „œÌœ —ÊÌ Å‰·Ö")
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
                send_or_edit(call, f"? Œÿ« œ— »—Ê“—”«‰Ì Å‰·:\n<code>{esc(str(err_renew))}</code>",
                             back_button(f"admin:pcfg:d:{config_id}")); return
            # Update DB
            update_panel_config_field(config_id, "expire_at",  new_exp_str)
            update_panel_config_field(config_id, "is_expired",  0)
            update_panel_config_field(config_id, "is_disabled", 0)
            update_panel_config_field(config_id, "package_id",  pkg_id)
            _show_panel_config_detail(call, config_id, back_data="admin:panel_configs")
            return

        # admin:pcfg:del:{config_id}  ó confirm deletion
        if data.startswith("admin:pcfg:del:") and not data.startswith("admin:pcfg:delok:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True); return
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup()
            kb.row(
                InlineKeyboardButton("? »·Â° Õ–› ò‰",  callback_data=f"admin:pcfg:delok:{config_id}"),
                InlineKeyboardButton("? ·€Ê",           callback_data=f"admin:pcfg:d:{config_id}"),
            )
            send_or_edit(call,
                "?? <b> √ÌÌœ Õ–› ò«‰›Ìê</b>\n\n"
                "«Ì‰ ò«‰›Ìê »Â ’Ê—  <b>œ«∆„Ì</b> Õ–› „Ìù‘Êœ.\n"
                "”—ÊÌ” ﬁ«»·  „œÌœ ‰ŒÊ«Âœ »Êœ Ê ÂÌç „»·€Ì »—ê‘  œ«œÂ ‰„Ìù‘Êœ.\n\n"
                "¬Ì« „ÿ„∆‰ Â” Ìœø", kb)
            return

        # admin:pcfg:delok:{config_id}
        if data.startswith("admin:pcfg:delok:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg:
                bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True); return
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

    # ?? User: My Panel Configs ?????????????????????????????????????????????????
    if data.startswith("mypnlcfg:") or data.startswith("mypnlcfgrpay:"):
        from ..admin.renderers import _show_panel_config_detail

        # mypnlcfg:d:{config_id}
        if data.startswith("mypnlcfg:d:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            bot.answer_callback_query(call.id)
            _show_panel_config_detail(call, config_id, back_data="my_configs",
                                      is_user_view=True)
            return

        # mypnlcfg:renewwarn:{config_id}  ó confirmation warning before quick renewal
        if data.startswith("mypnlcfg:renewwarn:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            bot.answer_callback_query(call.id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("? »·Â°  „œÌœ ò‰", callback_data=f"mypnlcfg:renewconfirm:{config_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"mypnlcfg:d:{config_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "?? <b> „œÌœ ›Ê—Ì</b>\n\n"
                "»«  „œÌœ ›Ê—Ì° <b>ÕÃ„ Ê “„«‰</b> ò«‰›Ìê ‘„« —Ì”  „Ìù‘Êœ Ê «“ ‰Ê »« «ÿ·«⁄«  ÅòÌÃ ÃœÌœ ›⁄«· „Ìùê—œœ.\n\n"
                "¬Ì« „ÿ„∆‰ Â” Ìœø",
                kb)
            return

        # mypnlcfg:renewconfirm:{config_id}  ó show package list for panel config renewal
        if data.startswith("mypnlcfg:renewconfirm:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
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
                title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)}  "
                kb.add(types.InlineKeyboardButton(title, callback_data=f"mypnlcfg:renewp:{config_id}:{p['id']}"))
            kb.add(types.InlineKeyboardButton("?? »«“ê‘ ", callback_data=f"mypnlcfg:d:{config_id}",
                   icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            agent_note = "\n\n?? <i>«Ì‰ ﬁÌ„ ùÂ« „Œ’Ê’ Â„ò«—Ì ‘„«” </i>" if user and user["is_agent"] else ""
            if not packages:
                send_or_edit(call, "?? œ— Õ«· Õ«÷— ÅòÌÃÌ »—«Ì  „œÌœ „ÊÃÊœ ‰Ì” .", kb)
            else:
                send_or_edit(call,
                    "? <b> „œÌœ ”—ÊÌ”</b>\n\n"
                    "ÅòÌÃ „Ê—œ ‰Ÿ— »—«Ì  „œÌœ —« «‰ Œ«» ò‰Ìœ:"
                    f"{agent_note}", kb)
            return

        # mypnlcfg:renewp:{config_id}:{package_id}  ó show payment gateways for selected package
        if data.startswith("mypnlcfg:renewp:"):
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            cfg = dict(cfg)
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
            price = get_effective_price(uid, package_row)
            state_set(uid, "pnlcfg_renew_select_method",
                      config_id=config_id, package_id=package_id,
                      amount=price, original_amount=price, kind="pnlcfg_renewal")
            bot.answer_callback_query(call.id)
            _show_pnlcfg_renewal_gateways(call, uid, config_id, package_id, price, package_row, cfg)
            return

        # ?? Panel config renewal payment handlers ?????????????????????????????

        # mypnlcfgrpay:wallet:{config_id}:{package_id}
        if data.startswith("mypnlcfgrpay:wallet:"):
            parts = data.split(":")
            config_id  = int(parts[2])
            package_id = int(parts[3])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
            user = get_user(uid)
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if user["balance"] < price:
                if not can_use_credit(uid, price):
                    bot.answer_callback_query(call.id, "„ÊÃÊœÌ òÌ› ÅÊ· ò«›Ì ‰Ì” .", show_alert=True); return
            update_balance(uid, -price)
            create_payment("pnlcfg_renewal", uid, package_id, price, "wallet",
                           status="completed", config_id=config_id)
            bot.answer_callback_query(call.id, "? œ— Õ«·  „œÌœÖ")
            ok_r, err_r = _execute_pnlcfg_renewal(config_id, package_id, chat_id=uid, uid=uid)
            state_clear(uid)
            if not ok_r:
                send_or_edit(call, "?  „œÌœ ”—ÊÌ” »« Œÿ« „Ê«ÃÂ ‘œ.\n·ÿ›« »« Å‘ Ì»«‰Ì «— »«ÿ »êÌ—Ìœ.",
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
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
            _ci = pick_card_for_payment()
            if not _ci:
                bot.answer_callback_query(call.id, "«ÿ·«⁄«  Å—œ«Œ  Â‰Ê“ À»  ‰‘œÂ «” .", show_alert=True); return
            card, bank, owner = _ci["card_number"], _ci["bank_name"], _ci["holder_name"]
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            price = apply_gateway_fee("card", price)
            if not is_gateway_in_range("card", price):
                _rng = get_gateway_range_text("card")
                bot.answer_callback_query(call.id,
                    f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì «Ì‰ œ—ê«Â „Ã«“ ‰Ì” .\n"
                    f"„ÕœÊœÂ „Ã«“: {_rng}\n\n·ÿ›« œ—ê«Â œÌê—Ì «‰ Œ«» ò‰Ìœ.",
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
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if not is_gateway_in_range("crypto", price):
                _rng = get_gateway_range_text("crypto")
                bot.answer_callback_query(call.id,
                    f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì «Ì‰ œ—ê«Â „Ã«“ ‰Ì” .\n"
                    f"„ÕœÊœÂ „Ã«“: {_rng}\n\n·ÿ›« œ—ê«Â œÌê—Ì «‰ Œ«» ò‰Ìœ.",
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
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if not is_gateway_in_range("tetrapay", price):
                _rng = get_gateway_range_text("tetrapay")
                bot.answer_callback_query(call.id,
                    f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â TetraPay „Ã«“ ‰Ì” .\n"
                    f"„ÕœÊœÂ „Ã«“: {_rng}\n\n·ÿ›« œ—ê«Â œÌê—Ì «‰ Œ«» ò‰Ìœ.",
                    show_alert=True); return
            order_id_tp = f"pnlr-{uid}-{config_id}-{int(datetime.now().timestamp())}"
            order_label_tp = (
                f" „œÌœ {package_row['name']}"
                if ('show_name' not in package_row.keys() or package_row['show_name'])
                else f" „œÌœ {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
            )
            success_tp, result_tp = create_tetrapay_order(price, order_id_tp, order_label_tp)
            if not success_tp:
                err_msg_tp = result_tp.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result_tp, dict) else str(result_tp)
                bot.answer_callback_query(call.id)
                send_or_edit(call,
                    f"?? <b>Œÿ« œ— «ÌÃ«œ œ—ê«Â TetraPay</b>\n\n<code>{esc(err_msg_tp[:400])}</code>",
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
                "?? <b>Å—œ«Œ  ¬‰·«Ì‰ ( „œÌœ)</b>\n\n"
                f"?? „»·€: <b>{fmt_price(price)}</b>  Ê„«‰\n\n"
                "·ÿ›« «“ ÌòÌ «“ ·Ì‰òùÂ«Ì “Ì— Å—œ«Œ  —« «‰Ã«„ œÂÌœ.\n\n"
                "? <b> « Ìò ”«⁄ </b> «ê— Å—œ«Œ ù Ê‰  «ÌÌœ »‘Â »Â ’Ê—  ŒÊœò«— ⁄„·Ì«  «‰Ã«„ „Ìù‘Êœ.\n"
                "œ— €Ì— «Ì‰ ’Ê—  œò„Â <b>»——”Ì Å—œ«Œ </b> —« »“‰Ìœ."
            )
            kb_tp = types.InlineKeyboardMarkup()
            if pay_url_bot_tp and setting_get("tetrapay_mode_bot", "1") == "1":
                kb_tp.add(types.InlineKeyboardButton("?? Å—œ«Œ  œ—  ·ê—«„", url=pay_url_bot_tp))
            if pay_url_web_tp and setting_get("tetrapay_mode_web", "1") == "1":
                kb_tp.add(types.InlineKeyboardButton("?? Å—œ«Œ  œ— „—Ê—ê—", url=pay_url_web_tp))
            kb_tp.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ",
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
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if not is_gateway_in_range("tronpays_rial", price):
                _rng = get_gateway_range_text("tronpays_rial")
                bot.answer_callback_query(call.id,
                    f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â TronPay „Ã«“ ‰Ì” .\n"
                    f"„ÕœÊœÂ „Ã«“: {_rng}\n\n·ÿ›« œ—ê«Â œÌê—Ì «‰ Œ«» ò‰Ìœ.",
                    show_alert=True); return
            hash_id_trp = f"pnlr-{uid}-{config_id}-{int(datetime.now().timestamp())}"
            order_label_trp = (
                f" „œÌœ {package_row['name']}"
                if ('show_name' not in package_row.keys() or package_row['show_name'])
                else f" „œÌœ {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
            )
            success_trp, result_trp = create_tronpays_rial_invoice(price, hash_id_trp, order_label_trp)
            if not success_trp:
                err_msg_trp = result_trp.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result_trp, dict) else str(result_trp)
                bot.answer_callback_query(call.id)
                send_or_edit(call,
                    f"?? <b>Œÿ« œ— «ÌÃ«œ ›«ò Ê— TronPays</b>\n\n<code>{esc(err_msg_trp[:400])}</code>",
                    back_button(f"mypnlcfg:renewconfirm:{config_id}")); return
            invoice_id_trp = result_trp.get("invoice_id")
            invoice_url_trp = result_trp.get("invoice_url")
            if not invoice_id_trp or not invoice_url_trp:
                bot.answer_callback_query(call.id)
                send_or_edit(call, "?? Œÿ« œ— «ÌÃ«œ ›«ò Ê— TronPays. ·ÿ›« œÊ»«—Â  ·«‘ ò‰Ìœ.",
                             back_button(f"mypnlcfg:renewconfirm:{config_id}")); return
            payment_id = create_payment("pnlcfg_renewal", uid, package_id, price, "tronpays_rial",
                                        status="pending", config_id=config_id)
            with get_conn() as conn:
                conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id_trp, payment_id))
            state_set(uid, "await_pnlcfg_renewal_tronpays_verify",
                      payment_id=payment_id, invoice_id=invoice_id_trp, config_id=config_id)
            kb_trp = types.InlineKeyboardMarkup()
            kb_trp.add(types.InlineKeyboardButton("?? Å—œ«Œ ", url=invoice_url_trp))
            kb_trp.add(types.InlineKeyboardButton("?? »——”Ì Å—œ«Œ ",
                        callback_data=f"mypnlcfgrpay:tronpays_rial:verify:{payment_id}"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "?? <b>Å—œ«Œ  ¬‰·«Ì‰ TronPays ( „œÌœ)</b>\n\n"
                f"?? „»·€: <b>{fmt_price(price)}</b>  Ê„«‰\n\n"
                "? Å” «“ Å—œ«Œ ° œò„Â <b>»——”Ì Å—œ«Œ </b> —« »“‰Ìœ.",
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
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            if payment["status"] != "pending":
                bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True); return
            invoice_id_v = payment["receipt_text"]
            ok_v, status_v = check_tronpays_rial_invoice(invoice_id_v)
            if not ok_v:
                bot.answer_callback_query(call.id, "Œÿ« œ— »——”Ì Ê÷⁄Ì  ›«ò Ê—.", show_alert=True); return
            if is_tronpays_paid(status_v):
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True); return
                config_id_v  = payment["config_id"]
                package_id_v = payment["package_id"]
                bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ! œ— Õ«·  „œÌœÖ")
                ok_r, err_r = _execute_pnlcfg_renewal(config_id_v, package_id_v, chat_id=uid, uid=uid)
                state_clear(uid)
                if not ok_r:
                    send_or_edit(call, "? Å—œ«Œ  «‰Ã«„ ‘œ «„«  „œÌœ ”—ÊÌ” »« Œÿ« „Ê«ÃÂ ‘œ.\n·ÿ›« »« Å‘ Ì»«‰Ì «— »«ÿ »êÌ—Ìœ.",
                                 back_button("my_configs"))
                    return
                _show_panel_config_detail(call, config_id_v, back_data="my_configs", is_user_view=True)
            else:
                bot.answer_callback_query(call.id, "? Å—œ«Œ  Â‰Ê“  √ÌÌœ ‰‘œÂ. ·ÿ›« «» œ« Å—œ«Œ  —« «‰Ã«„ œÂÌœ.", show_alert=True)
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
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            package_row = get_package(package_id)
            if not package_row:
                bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True); return
            sd = state_data(uid)
            price = sd.get("amount") or get_effective_price(uid, package_row)
            if not is_gateway_in_range("swapwallet_crypto", price):
                _rng = get_gateway_range_text("swapwallet_crypto")
                bot.answer_callback_query(call.id,
                    f"?? „»·€ {fmt_price(price)}  Ê„«‰ »—«Ì œ—ê«Â SwapWallet „Ã«“ ‰Ì” .\n"
                    f"„ÕœÊœÂ „Ã«“: {_rng}\n\n·ÿ›« œ—ê«Â œÌê—Ì «‰ Œ«» ò‰Ìœ.",
                    show_alert=True); return
            from ..gateways.swapwallet_crypto import get_active_swapwallet_networks, NETWORK_LABELS as SW_NET_LABELS2
            _active_nets_pnl = get_active_swapwallet_networks()
            if not _active_nets_pnl:
                bot.answer_callback_query(call.id, "ÂÌç «—“Ì »—«Ì SwapWallet ›⁄«· ‰‘œÂ «” .", show_alert=True); return
            state_set(uid, "swcrypto_network_select", kind="pnlcfg_renewal",
                      config_id=config_id, package_id=package_id, amount=price)
            kb_sw = types.InlineKeyboardMarkup()
            if len(_active_nets_pnl) == 1:
                net_pnl = _active_nets_pnl[0][0]
                order_id_sw = f"pnlswc-{uid}-{int(datetime.now().timestamp())}"
                success_sw, result_sw = create_swapwallet_crypto_invoice(price, order_id_sw, net_pnl, " „œÌœ ”—ÊÌ”")
                if not success_sw:
                    err_sw = result_sw.get("error", "Œÿ«Ì ‰«‘‰«Œ Â") if isinstance(result_sw, dict) else str(result_sw)
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
                kb_sw.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"mypnlcfg:renewconfirm:{config_id}",
                           icon_custom_emoji_id="5253997076169115797"))
                bot.answer_callback_query(call.id)
                send_or_edit(call, "?? <b>Å—œ«Œ  ò—ÌÅ Ê (SwapWallet)</b>\n\n‘»òÂ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb_sw)
            return

        # mypnlcfgrpay:swapwallet_crypto:verify:{payment_id}
        if data.startswith("mypnlcfgrpay:swapwallet_crypto:verify:"):
            payment_id = int(data.split(":")[-1])
            payment = get_payment(payment_id)
            if not payment or payment["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            if payment["status"] != "pending":
                bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True); return
            invoice_id_sv = payment["receipt_text"]
            success_sv, inv_sv = check_swapwallet_crypto_invoice(invoice_id_sv)
            if not success_sv:
                bot.answer_callback_query(call.id, "Œÿ« œ— »——”Ì Ê÷⁄Ì  ›«ò Ê—.", show_alert=True); return
            if inv_sv.get("status") in ("PAID", "COMPLETED") or inv_sv.get("paidAt"):
                if not complete_payment(payment_id):
                    bot.answer_callback_query(call.id, "«Ì‰ Å—œ«Œ  ﬁ»·« Å—œ«“‘ ‘œÂ.", show_alert=True); return
                config_id_sv  = payment["config_id"]
                package_id_sv = payment["package_id"]
                bot.answer_callback_query(call.id, "? Å—œ«Œ   √ÌÌœ ‘œ! œ— Õ«·  „œÌœÖ")
                ok_r, err_r = _execute_pnlcfg_renewal(config_id_sv, package_id_sv, chat_id=uid, uid=uid)
                state_clear(uid)
                if not ok_r:
                    send_or_edit(call, "? Å—œ«Œ  «‰Ã«„ ‘œ «„«  „œÌœ ”—ÊÌ” »« Œÿ« „Ê«ÃÂ ‘œ.\n·ÿ›« »« Å‘ Ì»«‰Ì «— »«ÿ »êÌ—Ìœ.",
                                 back_button("my_configs"))
                    return
                _show_panel_config_detail(call, config_id_sv, back_data="my_configs", is_user_view=True)
            else:
                bot.answer_callback_query(call.id, "? Å—œ«Œ  Â‰Ê“  √ÌÌœ ‰‘œÂ.", show_alert=True)
            return

        # mypnlcfg:autorenew:{config_id}
        if data.startswith("mypnlcfg:autorenew:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
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
                            f"? „ÊÃÊœÌ ò«›Ì ‰œ«—Ìœ.\n"
                            f"»—«Ì ›⁄«·ù”«“Ì  „œÌœ ŒÊœò«— «Ì‰ ò«‰›Ìê° "
                            f"òÌ› ÅÊ· ŒÊœ —« »Â „Ì“«‰ {fmt_price(_price)}  Ê„«‰ "
                            f"(„⁄«œ· Â“Ì‰Â ”—ÊÌ”) ‘«—é ò‰Ìœ.",
                            show_alert=True
                        )
                        return
            update_panel_config_field(config_id, "auto_renew", new_val)
            bot.answer_callback_query(call.id, f" „œÌœ ŒÊœò«— {'›⁄«·' if new_val else '€Ì—›⁄«·'} ‘œ.")
            _show_panel_config_detail(call, config_id, back_data="my_configs",
                                      is_user_view=True)
            return

        # mypnlcfg:rsub:{config_id}
        if data.startswith("mypnlcfg:rsub:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            cpkg = get_panel_client_package(cfg["cpkg_id"]) if cfg.get("cpkg_id") else None
            if not cpkg:
                bot.answer_callback_query(call.id, "ﬁ«·» ”«» „ÊÃÊœ ‰Ì” .", show_alert=True); return
            cpkg_d = dict(cpkg)
            import uuid as _uuid
            new_sub_id  = str(_uuid.uuid4()).replace("-", "")[:16]
            new_sub_url = _build_sub_from_template(cpkg_d, new_sub_id)
            if not new_sub_url:
                bot.answer_callback_query(call.id, "Œÿ« œ— ”«Œ  ·Ì‰ò ”«».", show_alert=True); return
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
            bot.answer_callback_query(call.id, "? ·Ì‰ò ”«» ÃœÌœ ”«Œ Â ‘œ.")
            _show_panel_config_detail(call, config_id, back_data="my_configs",
                                      is_user_view=True)
            return

        # mypnlcfg:qrc:{config_id}
        if data.startswith("mypnlcfg:qrc:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            if cfg["client_config_text"]:
                try:
                    import qrcode as _qrcode
                    from io import BytesIO
                    bio = BytesIO(); _qrcode.make(cfg["client_config_text"]).save(bio, format="PNG"); bio.seek(0)
                    bio.name = "qr_config.png"
                    bot.answer_callback_query(call.id)
                    bot.send_photo(uid, bio, caption="?? QR ò«‰›Ìê")
                except Exception as e:
                    bot.answer_callback_query(call.id, str(e), show_alert=True)
            else:
                bot.answer_callback_query(call.id, "ò«‰›Ìê „ÊÃÊœ ‰Ì” .", show_alert=True)
            return

        # mypnlcfg:qrs:{config_id}
        if data.startswith("mypnlcfg:qrs:"):
            config_id = int(data.split(":")[-1])
            cfg = get_panel_config(config_id)
            if not cfg or cfg["user_id"] != uid:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
            if cfg["client_sub_url"]:
                try:
                    import qrcode as _qrcode
                    from io import BytesIO
                    bio = BytesIO(); _qrcode.make(cfg["client_sub_url"]).save(bio, format="PNG"); bio.seek(0)
                    bio.name = "qr_sub.png"
                    bot.answer_callback_query(call.id)
                    bot.send_photo(uid, bio, caption="?? QR ”«»”ò—«Ì»")
                except Exception as e:
                    bot.answer_callback_query(call.id, str(e), show_alert=True)
            else:
                bot.answer_callback_query(call.id, "·Ì‰ò ”«» „ÊÃÊœ ‰Ì” .", show_alert=True)
            return

        # mypnlcfg:list:{filter}:{page}  ?  user's filtered panel config list
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

            flt_labels = {"all": "?? Â„Â", "expiring": "?? —Ê »Â Å«Ì«‰", "expired": "? „‰ﬁ÷Ì"}
            bot.answer_callback_query(call.id)
            kb = types.InlineKeyboardMarkup()
            for row in rows:
                if row["is_expired"]:
                    marker = " ?"
                elif int(row["is_disabled"] or 0):
                    marker = " ?"
                else:
                    marker = " ??"
                name = esc(row["client_name"] or row["package_name"] or "ó")
                kb.add(types.InlineKeyboardButton(f"{name}{marker}", callback_data=f"mypnlcfg:d:{row['id']}"))
            if total_pages > 1:
                nav = []
                if page > 0:
                    nav.append(types.InlineKeyboardButton("?? ﬁ»·Ì", callback_data=f"mypnlcfg:list:{flt}:{page-1}"))
                nav.append(types.InlineKeyboardButton(f"?? {page+1}/{total_pages}", callback_data="noop"))
                if page < total_pages - 1:
                    nav.append(types.InlineKeyboardButton("?? »⁄œÌ", callback_data=f"mypnlcfg:list:{flt}:{page+1}"))
                kb.row(*nav)
            kb.add(types.InlineKeyboardButton("?? »«“ê‘  »Â ”—ÊÌ”ùÂ«", callback_data="my_configs"))
            header = f"{flt_labels.get(flt, '??')} <b>ò«‰›ÌêùÂ«Ì Å‰·</b>"
            if not rows:
                header += "\n\n?? „Ê—œÌ Ì«›  ‰‘œ."
            else:
                header += f"\n\nÌòÌ «“ ”—ÊÌ”ùÂ« —« «‰ Œ«» ò‰Ìœ:"
            send_or_edit(call, header, kb)
            return

    # ?? User: Volume add-on ??????????????????????????????????????????????????
    if data.startswith("addon:vol:") and len(data.split(":")) == 3:
        config_id = int(data.split(":")[2])
        cfg = get_panel_config(config_id)
        if not cfg or cfg["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
        if setting_get("addon_volume_enabled", "1") != "1":
            bot.answer_callback_query(call.id, "Œ—Ìœ ÕÃ„ «÷«›Â œ— Õ«· Õ«÷— €Ì—›⁄«· «” .", show_alert=True); return
        unit_price, err = _get_addon_unit_price(cfg, "volume")
        if unit_price is None:
            bot.answer_callback_query(call.id, err, show_alert=True); return
        bot.answer_callback_query(call.id)
        state_set(uid, "addon_vol_custom", config_id=config_id, unit_price=unit_price,
                  discount_amount=0, final_amount=0)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("1 êÌê",  callback_data=f"addon:va:{config_id}:1"),
            types.InlineKeyboardButton("2 êÌê",  callback_data=f"addon:va:{config_id}:2"),
            types.InlineKeyboardButton("3 êÌê",  callback_data=f"addon:va:{config_id}:3"),
            types.InlineKeyboardButton("4 êÌê",  callback_data=f"addon:va:{config_id}:4"),
            types.InlineKeyboardButton("5 êÌê",  callback_data=f"addon:va:{config_id}:5"),
        )
        kb.row(
            types.InlineKeyboardButton("10 êÌê", callback_data=f"addon:va:{config_id}:10"),
            types.InlineKeyboardButton("20 êÌê", callback_data=f"addon:va:{config_id}:20"),
            types.InlineKeyboardButton("30 êÌê", callback_data=f"addon:va:{config_id}:30"),
            types.InlineKeyboardButton("50 êÌê", callback_data=f"addon:va:{config_id}:50"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"mypnlcfg:d:{config_id}",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"?? <b>Œ—Ìœ ÕÃ„ «÷«›Â</b>\n\n"
            f"?? ﬁÌ„  Â— êÌê: <b>{fmt_price(unit_price)}  Ê„«‰</b>\n\n"
            "Ìò ê“Ì‰Â «‰ Œ«» ò‰Ìœ Ì« ÕÃ„ œ·ŒÊ«Â —« »Â ’Ê—  ⁄œœ Ê«—œ ò‰Ìœ („À«·: 8 Ì« 2.5):", kb)
        return

    if data.startswith("addon:va:"):
        # addon:va:{config_id}:{gb}
        parts     = data.split(":")
        config_id = int(parts[2])
        gb_str    = parts[3]
        gb = float(gb_str)
        sd = state_data(uid)
        unit_price = int(sd.get("unit_price", 0))
        subtotal   = int(gb * unit_price)
        state_set(uid, "addon_vol_flow",
                  config_id=config_id, unit_price=unit_price,
                  amount_gb=gb, subtotal=subtotal, discount_amount=0, final_amount=subtotal)
        bot.answer_callback_query(call.id)
        _show_addon_invoice(call, uid, "volume")
        return

    # ?? User: Time add-on ????????????????????????????????????????????????????
    if data.startswith("addon:time:") and len(data.split(":")) == 3:
        config_id = int(data.split(":")[2])
        cfg = get_panel_config(config_id)
        if not cfg or cfg["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
        if setting_get("addon_time_enabled", "1") != "1":
            bot.answer_callback_query(call.id, "Œ—Ìœ “„«‰ «÷«›Â œ— Õ«· Õ«÷— €Ì—›⁄«· «” .", show_alert=True); return
        unit_price, err = _get_addon_unit_price(cfg, "time")
        if unit_price is None:
            bot.answer_callback_query(call.id, err, show_alert=True); return
        bot.answer_callback_query(call.id)
        state_set(uid, "addon_time_custom", config_id=config_id, unit_price=unit_price,
                  discount_amount=0, final_amount=0)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("1 —Ê“",  callback_data=f"addon:ta:{config_id}:1"),
            types.InlineKeyboardButton("2 —Ê“",  callback_data=f"addon:ta:{config_id}:2"),
            types.InlineKeyboardButton("3 —Ê“",  callback_data=f"addon:ta:{config_id}:3"),
            types.InlineKeyboardButton("4 —Ê“",  callback_data=f"addon:ta:{config_id}:4"),
            types.InlineKeyboardButton("5 —Ê“",  callback_data=f"addon:ta:{config_id}:5"),
        )
        kb.row(
            types.InlineKeyboardButton("7 —Ê“",  callback_data=f"addon:ta:{config_id}:7"),
            types.InlineKeyboardButton("14 —Ê“", callback_data=f"addon:ta:{config_id}:14"),
            types.InlineKeyboardButton("30 —Ê“", callback_data=f"addon:ta:{config_id}:30"),
            types.InlineKeyboardButton("60 —Ê“", callback_data=f"addon:ta:{config_id}:60"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"mypnlcfg:d:{config_id}",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"? <b>Œ—Ìœ “„«‰ «÷«›Â</b>\n\n"
            f"?? ﬁÌ„  Â— —Ê“: <b>{fmt_price(unit_price)}  Ê„«‰</b>\n\n"
            "Ìò ê“Ì‰Â «‰ Œ«» ò‰Ìœ Ì«  ⁄œ«œ —Ê“ œ·ŒÊ«Â —« »Â ’Ê—  ⁄œœ Ê«—œ ò‰Ìœ („À«·: 10):", kb)
        return

    if data.startswith("addon:ta:"):
        # addon:ta:{config_id}:{days}
        parts     = data.split(":")
        config_id = int(parts[2])
        days_str  = parts[3]
        days       = int(days_str)
        sd         = state_data(uid)
        unit_price = int(sd.get("unit_price", 0))
        subtotal   = days * unit_price
        state_set(uid, "addon_time_flow",
                  config_id=config_id, unit_price=unit_price,
                  amount_days=days, subtotal=subtotal, discount_amount=0, final_amount=subtotal)
        bot.answer_callback_query(call.id)
        _show_addon_invoice(call, uid, "time")
        return

    # ?? User: Addon discount code ????????????????????????????????????????????
    if data.startswith("addon:disc:"):
        # addon:disc:{config_id}:{addon_type}
        parts      = data.split(":")
        config_id  = int(parts[2])
        addon_type = parts[3]
        sd         = state_data(uid)
        subtotal   = int(sd.get("subtotal", sd.get("final_amount", 0)))
        # Keep all state fields, just change state name
        new_sd = {k: v for k, v in sd.items()}
        new_sd["prev_addon_type"]    = addon_type
        new_sd["prev_addon_config"]  = config_id
        new_sd["original_amount"]    = subtotal
        state_set(uid, "await_addon_discount", **new_sd)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»œÊ‰  Œ›Ì›", callback_data=f"addon:nodisc:{config_id}:{addon_type}"))
        send_or_edit(call,
            "?? <b>òœ  Œ›Ì›</b>\n\nòœ  Œ›Ì› ŒÊœ —« Ê«—œ ò‰Ìœ:", kb)
        return

    if data.startswith("addon:nodisc:"):
        # addon:nodisc:{config_id}:{addon_type}
        parts      = data.split(":")
        config_id  = int(parts[2])
        addon_type = parts[3]
        sd         = state_data(uid)
        prev       = f"addon_{'vol' if addon_type == 'volume' else 'time'}_flow"
        state_set(uid, prev, **{k: v for k, v in sd.items()
                                if k not in ("prev_addon_type", "prev_addon_config", "original_amount")})
        bot.answer_callback_query(call.id)
        _show_addon_invoice(call, uid, addon_type)
        return

    # ?? User: Addon payment ??????????????????????????????????????????????????
    if data.startswith("addon:pay:"):
        # addon:pay:{config_id}:{addon_type}:{method}
        parts      = data.split(":")
        config_id  = int(parts[2])
        addon_type = parts[3]   # 'volume' or 'time'
        method     = parts[4]   # 'wallet' or 'card'
        cfg = get_panel_config(config_id)
        if not cfg or cfg["user_id"] != uid:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True); return
        sd           = state_data(uid)
        final_amount = int(sd.get("final_amount", sd.get("subtotal", 0)))
        subtotal     = int(sd.get("subtotal", final_amount))
        discount_id  = sd.get("discount_code_id")

        if method == "wallet":
            user = get_user(uid)
            balance = int(user["balance"]) if user else 0
            if balance < final_amount and not can_use_credit(uid, final_amount):
                bot.answer_callback_query(call.id, "„ÊÃÊœÌ òÌ› ÅÊ· ò«›Ì ‰Ì” .", show_alert=True); return
            # Deduct balance
            update_balance(uid, -final_amount)
            # Record discount usage
            if discount_id:
                record_discount_usage(discount_id, uid)
            # Apply panel change
            ok, err = _execute_addon_update(config_id, addon_type, sd, uid)
            if not ok:
                # Refund on failure
                update_balance(uid, final_amount)
                bot.answer_callback_query(call.id)
                send_or_edit(call,
                    "? Œÿ« œ— «⁄„«· «›“Êœ‰Ì.\n„»·€ »Â òÌ› ÅÊ· »«“ê—œ«‰œÂ ‘œ.\n·ÿ›« »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ.",
                    back_button(f"mypnlcfg:d:{config_id}"))
                return
            state_clear(uid)
            bot.answer_callback_query(call.id, "? «›“Êœ‰Ì »« „Ê›ﬁÌ  «⁄„«· ‘œ.")
            label = "ÕÃ„" if addon_type == "volume" else "“„«‰"
            send_or_edit(call,
                f"? <b>«›“Êœ‰Ì »« „Ê›ﬁÌ  «⁄„«· ‘œ</b>\n\n"
                f"{'??' if addon_type == 'volume' else '?'} {label} «÷«›Â »Â ”—ÊÌ” ‘„« «÷«›Â ‘œ.",
                back_button(f"mypnlcfg:d:{config_id}"))
            admin_addon_notify(uid, config_id, addon_type, sd, final_amount, "wallet")
            return

        if method == "card":
            # Card payment ó store current state and show card info
            from ..db import pick_card_for_payment as _pick_card
            card = _pick_card()
            if not card:
                bot.answer_callback_query(call.id, "œ— Õ«· Õ«÷— Å—œ«Œ  ò«—  »Â ò«—  «„ò«‰ùÅ–Ì— ‰Ì” .", show_alert=True); return
            state_set(uid, "addon_card_pending",
                      config_id=config_id, addon_type=addon_type,
                      final_amount=final_amount, subtotal=subtotal,
                      discount_code_id=discount_id,
                      **{k: v for k, v in sd.items()})
            bot.answer_callback_query(call.id)
            card_holder = card.get("holder_name", "")
            card_number = card.get("card_number", "")
            bank_name   = card.get("bank_name", "")
            label       = "ÕÃ„ «÷«›Â" if addon_type == "volume" else "“„«‰ «÷«›Â"
            text = (
                f"?? <b>Å—œ«Œ  {label}</b>\n\n"
                f"?? „»·€: <b>{fmt_price(final_amount)}  Ê„«‰</b>\n\n"
                f"?? »«‰ò: {esc(bank_name)}\n"
                f"?? ’«Õ» Õ”«»: {esc(card_holder)}\n"
                f"?? ‘„«—Â ò«— :\n<code>{esc(card_number)}</code>\n\n"
                f"Å” «“ Ê«—Ì“°  ’ÊÌ— —”Ìœ —« «—”«· ò‰Ìœ."
            )
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("? «‰’—«›", callback_data=f"addon:{'vol' if addon_type=='volume' else 'time'}:{config_id}"))
            send_or_edit(call, text, kb)
            return
        return

    if data == "admin:add_config":
        if not (admin_has_perm(uid, "register_config") or admin_has_perm(uid, "manage_configs")):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        types_list = get_all_types()
        kb = types.InlineKeyboardMarkup()
        for item in types_list:
            kb.add(types.InlineKeyboardButton(f"?? {item['name']}", callback_data=f"adm:cfg:t:{item['id']}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>À»  ò«‰›Ìê</b>\n\n‰Ê⁄ ò«‰›Ìê —« «‰ Œ«» ò‰Ìœ:", kb)
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
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:add_config", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ÅòÌÃ „—»ÊÿÂ —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("adm:cfg:p:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        state_set(uid, "admin_cfg_proto_select", package_id=package_id, type_id=package_row["type_id"])
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? V2Ray",    callback_data=f"adm:cfg:proto:v2ray:{package_id}"))
        kb.add(types.InlineKeyboardButton("?? OpenVPN",  callback_data=f"adm:cfg:proto:ovpn:{package_id}"))
        kb.add(types.InlineKeyboardButton("?? WireGuard", callback_data=f"adm:cfg:proto:wg:{package_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:t:{package_row['type_id']}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? Å—Ê ò· ò«‰›Ìê —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    # ?? Protocol selector ?????????????????????????????????????????????????????
    if data.startswith("adm:cfg:proto:"):
        parts      = data.split(":")
        proto      = parts[3]           # v2ray | ovpn | wg
        package_id = int(parts[4])
        package_row = get_package(package_id)

        # ?? V2Ray: new structured flow ????????????????????????????????????????
        if proto == "v2ray":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",    callback_data=f"adm:v2:single:{package_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:v2:bulk:{package_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? —Ê‘ À»  ò«‰›Ìê V2Ray —« «‰ Œ«» ò‰Ìœ:", kb)
            return

        # ?? OpenVPN ???????????????????????????????????????????????????????????
        if proto == "ovpn":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",   callback_data=f"adm:ovpn:single:{package_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:ovpn:bulk:{package_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? —Ê‘ À»  ò«‰›Ìê OpenVPN —« «‰ Œ«» ò‰Ìœ:", kb)
            return

        # ?? WireGuard ?????????????????????????????????????????????????????????
        if proto == "wg":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",    callback_data=f"adm:wg:single:{package_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:wg:bulk:{package_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? —Ê‘ À»  ò«‰›Ìê WireGuard —« «‰ Œ«» ò‰Ìœ:", kb)
            return

        bot.answer_callback_query(call.id, "Å—Ê ò· ‰«‘‰«Œ Â", show_alert=True)
        return

    # ?? OpenVPN ó Single ?????????????????????????????????????????????????????
    if data.startswith("adm:ovpn:single:"):
        package_id = int(data.split(":")[3])
        state_set(uid, "ovpn_single_file", package_id=package_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:proto:ovpn:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>À»   òÌ OpenVPN</b>\n\n"
            "›«Ì· Ì« ›«Ì·ùÂ«Ì <code>.ovpn</code> —« «—”«· ò‰Ìœ.\n"
            "«ê— ç‰œ ›«Ì· œ«—Ìœ° Â„Â —« ÌòÃ« »›—” Ìœ ó Â„Â „ ⁄·ﬁ »Â Ìò «ò«‰  œ— ‰Ÿ— ê—› Â „Ìù‘Ê‰œ.\n\n"
            "?? ›ﬁÿ ›—„  <b>.ovpn</b> Å–Ì—› Â „Ìù‘Êœ.", kb)
        return

    # ?? OpenVPN ó Bulk (shared vs different files) ????????????????????????????
    if data.startswith("adm:ovpn:bulk:"):
        rest       = data[len("adm:ovpn:bulk:"):]

        # adm:ovpn:bulk:{pkg_id}  ? first question: same file?
        if rest.isdigit():
            package_id = int(rest)
            state_set(uid, "ovpn_bulk_init", package_id=package_id)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("? »·Â", callback_data=f"adm:ovpn:bulk:shared:{package_id}"),
                types.InlineKeyboardButton("? ŒÌ—", callback_data=f"adm:ovpn:bulk:diff:{package_id}"),
            )
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:proto:ovpn:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? ¬Ì« ›«Ì· ò«‰›Ìê <b>Â„Â «ò«‰ ùÂ« ÌòÌ</b> «” ø", kb)
            return

        # adm:ovpn:bulk:shared:{pkg_id}  ? send shared ovpn files
        if rest.startswith("shared:"):
            package_id = int(rest.split(":")[1])
            state_set(uid, "ovpn_bulk_shared_file", package_id=package_id, shared_files=[])
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:ovpn:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "?? <b>À»  œ” Âù«Ì OpenVPN ó ›«Ì· „‘ —ò</b>\n\n"
                "›«Ì· Ì« ›«Ì·ùÂ«Ì <code>.ovpn</code> „‘ —ò —« «—”«· ò‰Ìœ.\n"
                "«ê— ç‰œ ›«Ì· „‘ —ò œ«—Ìœ Â„Â —« »›—” Ìœ.\n\n"
                "Êﬁ Ì  „«„ ›«Ì·ùÂ« —« ›—” «œÌœ œò„Â ? —« »“‰Ìœ.",
                kb)
            # We send a separate message with Done button since state must settle
            done_kb = types.InlineKeyboardMarkup()
            done_kb.add(types.InlineKeyboardButton("? ›«Ì·ùÂ« ò«„·ù«‰œ° «œ«„Â", callback_data=f"adm:ovpn:sharedok:{package_id}"))
            bot.send_message(uid, "Å” «“ «—”«· Â„Â ›«Ì·ùÂ«Ì „‘ —ò° «Ì‰ œò„Â —« »“‰Ìœ:", reply_markup=done_kb)
            return

        # adm:ovpn:bulk:diff:{pkg_id}  ? how many accounts?
        if rest.startswith("diff:"):
            package_id = int(rest.split(":")[1])
            state_set(uid, "ovpn_bulk_diff_count", package_id=package_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:ovpn:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "?? <b>À»  œ” Âù«Ì OpenVPN ó ›«Ì· „ ›«Ê </b>\n\n"
                "ç‰œ «ò«‰  „ÌùŒÊ«ÂÌœ À»  ò‰Ìœø\n"
                "⁄œœ —«  «ÌÅ ò‰Ìœ:", kb)
            return

        bot.answer_callback_query(call.id, "„”Ì— ‰«‘‰«Œ Â", show_alert=True)
        return

    # ?? OpenVPN ó shared files done, ask about inquiry ????????????????????????
    if data.startswith("adm:ovpn:sharedok:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        shared_files = sd.get("shared_files", [])
        if not shared_files:
            bot.answer_callback_query(call.id, "ÂÌç ›«Ì· .ovpn œ—Ì«›  ‰‘œ. ·ÿ›« «» œ« ›«Ì· «—”«· ò‰Ìœ.", show_alert=True)
            return
        state_set(uid, "ovpn_bulk_shared_inq", package_id=package_id, shared_files=shared_files)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("? »·Â", callback_data=f"adm:ovpn:shinq:y:{package_id}"),
            types.InlineKeyboardButton("? ŒÌ—", callback_data=f"adm:ovpn:shinq:n:{package_id}"),
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ¬Ì« «ò«‰ ùÂ« <b>·Ì‰ò «” ⁄·«„ ÕÃ„</b> œ«—‰œø", kb)
        return

    # ?? OpenVPN ó shared: has inquiry or not ?????????????????????????????????
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
                "?? <b>«ÿ·«⁄«  «ò«‰ ùÂ« ó ›«Ì· „‘ —ò (»« ·Ì‰ò «” ⁄·«„)</b>\n\n"
                "Â— «ò«‰  <b>? Œÿ</b>:\n"
                "Œÿ ?: username\n"
                "Œÿ ?: password\n"
                "Œÿ ?: volume web (·Ì‰ò «” ⁄·«„)\n\n"
                "?? „À«·:\n"
                "<code>user1\npass1\nhttp://panel.com/sub/1\n"
                "user2\npass2\nhttp://panel.com/sub/2</code>"
            )
        else:
            fmt_text = (
                "?? <b>«ÿ·«⁄«  «ò«‰ ùÂ« ó ›«Ì· „‘ —ò (»œÊ‰ ·Ì‰ò «” ⁄·«„)</b>\n\n"
                "Â— «ò«‰  <b>? Œÿ</b>:\n"
                "Œÿ ?: username\n"
                "Œÿ ?: password\n\n"
                "?? „À«·:\n"
                "<code>user1\npass1\nuser2\npass2</code>"
            )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:ovpn:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, fmt_text, kb)
        return

    # ?? OpenVPN ó diff: per-account files done, ask inquiry ??????????????????
    if data.startswith("adm:ovpn:diffok:"):
        # adm:ovpn:diffok:{pkg_id}:{account_idx}  ó all files for that account received
        parts      = data.split(":")
        package_id = int(parts[3])
        acct_idx   = int(parts[4])
        sd         = state_data(uid)
        acct_files = sd.get("acct_files", {})
        files_for_acct = sd.get("pending_acct_files", [])
        if not files_for_acct:
            bot.answer_callback_query(call.id, "ÂÌç ›«Ì· .ovpn »—«Ì «Ì‰ «ò«‰  œ—Ì«›  ‰‘œ.", show_alert=True)
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
                f"? ›«Ì·ùÂ«Ì «ò«‰  {next_idx} ò«„·ù«‰œ",
                callback_data=f"adm:ovpn:diffok:{package_id}:{next_idx}"
            ))
            bot.answer_callback_query(call.id)
            bot.send_message(uid,
                f"?? ›«Ì·ùÂ«Ì <code>.ovpn</code> <b>«ò«‰  {next_idx}</b> «“ {total_accts} —« «—”«· ò‰Ìœ:",
                reply_markup=done_kb)
        else:
            # All account files received ? ask inquiry
            state_set(uid, "ovpn_bulk_diff_inq",
                      package_id=package_id, total_accts=total_accts, acct_files=acct_files)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("? »·Â", callback_data=f"adm:ovpn:dinq:y:{package_id}"),
                types.InlineKeyboardButton("? ŒÌ—", callback_data=f"adm:ovpn:dinq:n:{package_id}"),
            )
            bot.answer_callback_query(call.id)
            bot.send_message(uid, "?? ¬Ì« «ò«‰ ùÂ« <b>·Ì‰ò «” ⁄·«„ ÕÃ„</b> œ«—‰œø", reply_markup=kb)
        return

    # ?? OpenVPN ó diff: has inquiry or not ???????????????????????????????????
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
                "?? <b>«ÿ·«⁄«  «ò«‰ ùÂ« ó ›«Ì· „ ›«Ê  (»« ·Ì‰ò «” ⁄·«„)</b>\n\n"
                "Â— «ò«‰  <b>? Œÿ</b> »Â  — Ì»:\n"
                "Œÿ ?: username\n"
                "Œÿ ?: password\n"
                "Œÿ ?: volume web (·Ì‰ò «” ⁄·«„)\n\n"
                "?? „À«·:\n"
                "<code>user1\npass1\nhttp://panel.com/sub/1\n"
                "user2\npass2\nhttp://panel.com/sub/2</code>"
            )
        else:
            fmt_text = (
                "?? <b>«ÿ·«⁄«  «ò«‰ ùÂ« ó ›«Ì· „ ›«Ê  (»œÊ‰ ·Ì‰ò «” ⁄·«„)</b>\n\n"
                "Â— «ò«‰  <b>? Œÿ</b> »Â  — Ì»:\n"
                "Œÿ ?: username\n"
                "Œÿ ?: password\n\n"
                "?? „À«·:\n"
                "<code>user1\npass1\nuser2\npass2</code>"
            )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:ovpn:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.send_message(uid, fmt_text, reply_markup=kb)
        return

    # ?? OpenVPN ó Single: files done, ask username ????????????????????????????
    if data.startswith("adm:ovpn:single_done:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        ovpn_files = sd.get("ovpn_files", [])
        if not ovpn_files:
            bot.answer_callback_query(call.id, "ÂÌç ›«Ì· .ovpn œ—Ì«›  ‰‘œ.", show_alert=True)
            return
        state_set(uid, "ovpn_single_username", package_id=package_id, ovpn_files=ovpn_files)
        bot.answer_callback_query(call.id)
        bot.send_message(uid, "?? <b>Username</b> «ò«‰  —« Ê«—œ ò‰Ìœ:", parse_mode="HTML")
        return

    # ?? OpenVPN ó Single: skip inquiry link ??????????????????????????????????
    if data.startswith("adm:ovpn:sinq_skip:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        _ovpn_finish_single(uid, sd, "")
        bot.answer_callback_query(call.id)
        return

    # ?? WireGuard ó Single ????????????????????????????????????????????????????
    if data.startswith("adm:wg:single:"):
        package_id = int(data.split(":")[3])
        state_set(uid, "wg_single_file", package_id=package_id, wg_files=[], wg_names=[])
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:proto:wg:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>À»   òÌ WireGuard</b>\n\n"
            "›«Ì· Ì« ›«Ì·ùÂ«Ì ò«‰›Ìê WireGuard —« «—”«· ò‰Ìœ.\n"
            "«ê— ç‰œ ›«Ì· œ«—Ìœ° Â„Â —« »›—” Ìœ ó Â„Â „ ⁄·ﬁ »Â Ìò ò«‰›Ìê œ— ‰Ÿ— ê—› Â „Ìù‘Ê‰œ.\n\n"
            "‰«„ ”—ÊÌ” »Â ’Ê—  ŒÊœò«— «“ ‰«„ ›«Ì· ŒÊ«‰œÂ „Ìù‘Êœ.", kb)
        return

    # ?? WireGuard ó Single: files done ???????????????????????????????????????
    if data.startswith("adm:wg:single_done:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        wg_files = sd.get("wg_files", [])
        if not wg_files:
            bot.answer_callback_query(call.id, "ÂÌç ›«Ì·Ì œ—Ì«›  ‰‘œ.", show_alert=True)
            return
        state_set(uid, "wg_single_inquiry",
                  package_id=package_id,
                  wg_files=wg_files, wg_names=sd.get("wg_names", []))
        bot.answer_callback_query(call.id)
        skip_kb = types.InlineKeyboardMarkup()
        skip_kb.add(types.InlineKeyboardButton("? Skip (»œÊ‰ ·Ì‰ò «” ⁄·«„)", callback_data=f"adm:wg:sinq_skip:{package_id}"))
        bot.send_message(uid,
            "?? <b>·Ì‰ò «” ⁄·«„ ÕÃ„</b> —« Ê«—œ ò‰Ìœ Ì« Skip »“‰Ìœ:\n"
            "(„À«·: <code>http://panel.example.com/sub/abc</code>)",
            reply_markup=skip_kb, parse_mode="HTML")
        return

    # ?? WireGuard ó Single: skip inquiry ?????????????????????????????????????
    if data.startswith("adm:wg:sinq_skip:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        _wg_finish_single(uid, sd, "")
        bot.answer_callback_query(call.id)
        return

    # ?? WireGuard ó Bulk ??????????????????????????????????????????????????????
    if data.startswith("adm:wg:bulk:"):
        rest = data[len("adm:wg:bulk:"):]

        # adm:wg:bulk:{pkg_id} ? ask same/different files
        if rest.isdigit():
            package_id = int(rest)
            state_set(uid, "wg_bulk_init", package_id=package_id)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("? »·Â", callback_data=f"adm:wg:bulk:shared:{package_id}"),
                types.InlineKeyboardButton("? ŒÌ—", callback_data=f"adm:wg:bulk:diff:{package_id}"),
            )
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:proto:wg:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? ¬Ì« ›«Ì·ùÂ«Ì <b>Â„Â ò«‰›ÌêùÂ« ÌòÌ</b> Â” ‰œø", kb)
            return

        # adm:wg:bulk:shared:{pkg_id} ? collect shared files
        if rest.startswith("shared:"):
            package_id = int(rest.split(":")[1])
            state_set(uid, "wg_bulk_shared_file", package_id=package_id, shared_files=[], shared_names=[])
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:wg:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "?? <b>À»  œ” Âù«Ì WireGuard ó ›«Ì· „‘ —ò</b>\n\n"
                "›«Ì· Ì« ›«Ì·ùÂ«Ì „‘ —ò WireGuard —« «—”«· ò‰Ìœ.\n"
                "Êﬁ Ì  „«„ ›«Ì·ùÂ« —« ›—” «œÌœ œò„Â ? —« »“‰Ìœ.", kb)
            done_kb = types.InlineKeyboardMarkup()
            done_kb.add(types.InlineKeyboardButton("? ›«Ì·ùÂ« ò«„·ù«‰œ° «œ«„Â", callback_data=f"adm:wg:sharedok:{package_id}"))
            bot.send_message(uid, "Å” «“ «—”«· Â„Â ›«Ì·ùÂ«Ì „‘ —ò° «Ì‰ œò„Â —« »“‰Ìœ:", reply_markup=done_kb)
            return

        # adm:wg:bulk:diff:{pkg_id} ? how many configs?
        if rest.startswith("diff:"):
            package_id = int(rest.split(":")[1])
            state_set(uid, "wg_bulk_diff_count", package_id=package_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:wg:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "?? <b>À»  œ” Âù«Ì WireGuard ó ›«Ì· „ ›«Ê </b>\n\n"
                "ç‰œ ò«‰›Ìê „ÌùŒÊ«ÂÌœ À»  ò‰Ìœø\n"
                "⁄œœ —«  «ÌÅ ò‰Ìœ:", kb)
            return

        bot.answer_callback_query(call.id, "„”Ì— ‰«‘‰«Œ Â", show_alert=True)
        return

    # ?? WireGuard ó Shared files done, ask inquiry ????????????????????????????
    if data.startswith("adm:wg:sharedok:"):
        package_id = int(data.split(":")[3])
        sd = state_data(uid)
        shared_files = sd.get("shared_files", [])
        if not shared_files:
            bot.answer_callback_query(call.id, "ÂÌç ›«Ì·Ì œ—Ì«›  ‰‘œ. ·ÿ›« «» œ« ›«Ì· «—”«· ò‰Ìœ.", show_alert=True)
            return
        state_set(uid, "wg_bulk_shared_inq",
                  package_id=package_id,
                  shared_files=shared_files, shared_names=sd.get("shared_names", []))
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("? »·Â", callback_data=f"adm:wg:shinq:y:{package_id}"),
            types.InlineKeyboardButton("? ŒÌ—", callback_data=f"adm:wg:shinq:n:{package_id}"),
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ¬Ì« ò«‰›ÌêùÂ« <b>·Ì‰ò «” ⁄·«„ ÕÃ„</b> œ«—‰œø", kb)
        return

    # ?? WireGuard ó Shared: with/without inquiry ??????????????????????????????
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
                "?? <b>·Ì‰òùÂ«Ì «” ⁄·«„ ó ›«Ì· „‘ —ò</b>\n\n"
                "Â— Œÿ Ìò ·Ì‰ò «” ⁄·«„ »—«Ì Ìò ò«‰›Ìê:\n\n"
                "?? „À«·:\n"
                "<code>http://panel.com/sub/1\n"
                "http://panel.com/sub/2\n"
                "http://panel.com/sub/3</code>"
            )
        else:
            fmt_text = (
                "?? <b> ⁄œ«œ ò«‰›ÌêùÂ«</b>\n\n"
                "ç‰œ ‰”ŒÂ «“ «Ì‰ ›«Ì·ùÂ«Ì „‘ —ò „ÌùŒÊ«ÂÌœ «—”«· ‘Êœø\n"
                "⁄œœ —« Ê«—œ ò‰Ìœ:"
            )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:wg:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, fmt_text, kb)
        return

    # ?? WireGuard ó Diff: per-config files done ???????????????????????????????
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
            bot.answer_callback_query(call.id, "ÂÌç ›«Ì·Ì »—«Ì «Ì‰ ò«‰›Ìê œ—Ì«›  ‰‘œ.", show_alert=True)
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
                f"? ›«Ì·ùÂ«Ì ò«‰›Ìê {next_idx} ò«„·ù«‰œ",
                callback_data=f"adm:wg:diffok:{package_id}:{next_idx}"
            ))
            bot.answer_callback_query(call.id)
            bot.send_message(uid,
                f"?? ›«Ì·ùÂ«Ì <b>ò«‰›Ìê {next_idx}</b> «“ {total_cfgs} —« «—”«· ò‰Ìœ:",
                reply_markup=done_kb, parse_mode="HTML")
        else:
            # All files collected ? ask inquiry
            state_set(uid, "wg_bulk_diff_inq",
                      package_id=package_id, total_accts=total_cfgs,
                      acct_files=acct_files, acct_names=acct_names)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("? »·Â", callback_data=f"adm:wg:dinq:y:{package_id}"),
                types.InlineKeyboardButton("? ŒÌ—", callback_data=f"adm:wg:dinq:n:{package_id}"),
            )
            bot.answer_callback_query(call.id)
            bot.send_message(uid, "?? ¬Ì« ò«‰›ÌêùÂ« <b>·Ì‰ò «” ⁄·«„ ÕÃ„</b> œ«—‰œø", reply_markup=kb)
        return

    # ?? WireGuard ó Diff: with/without inquiry ????????????????????????????????
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
                "?? <b>·Ì‰òùÂ«Ì «” ⁄·«„ ó ›«Ì· „ ›«Ê </b>\n\n"
                "Â— Œÿ Ìò ·Ì‰ò «” ⁄·«„ »Â  — Ì» ò«‰›ÌêùÂ«:\n\n"
                "?? „À«·:\n"
                "<code>http://panel.com/sub/1\n"
                "http://panel.com/sub/2</code>"
            )
        else:
            fmt_text = "? ›«Ì·ùÂ« œ—Ì«›  ‘œ‰œ. œ— Õ«· «—”«· ò«‰›ÌêùÂ«..."
            # No inquiry ? deliver immediately
            pkg_row = get_package(package_id)
            _wg_deliver_bulk_diff(uid, pkg_row,
                                  sd.get("acct_files", {}),
                                  sd.get("acct_names", {}), [])
            state_clear(uid)
            send_or_edit(call, fmt_text, types.InlineKeyboardMarkup())
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:wg:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.send_message(uid, fmt_text, reply_markup=kb)
        return

    # ?? V2Ray: Single ?????????????????????????????????????????????????????????
    # adm:v2:single:{pkg_id}  ? choose single-registration mode
    if data.startswith("adm:v2:single:"):
        package_id = int(data.split(":")[3])
        package_row = get_package(package_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "1?? À»  ò«‰›Ìê + ”«» Ãœ«ê«‰Â",
            callback_data=f"adm:v2:sm:1:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton(
            "2?? À»  ò«‰›Ìê  ‰Â«",
            callback_data=f"adm:v2:sm:2:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton(
            "3?? À»  ”«»  ‰Â«",
            callback_data=f"adm:v2:sm:3:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:proto:v2ray:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>À»   òÌ V2Ray</b>\n\n"
            "‰Ê⁄ ò«‰›ÌêÌ òÂ „ÌùŒÊ«ÂÌœ À»  ò‰Ìœ —« «‰ Œ«» ò‰Ìœ:\n\n"
            "1?? <b>ò«‰›Ìê + ”«»</b>\n"
            "   Â„ ò«‰›Ìê („À· vless://) œ«—Ìœ Â„ ·Ì‰ò ”«»ù«”ò—ÌÅ‘‰.\n"
            "   ò«—»— Â— œÊ —« œ—Ì«›  „Ìùò‰œ.\n\n"
            "2?? <b>ò«‰›Ìê  ‰Â«</b>\n"
            "   ›ﬁÿ ò«‰›Ìê („À· vless://) œ«—Ìœ° ·Ì‰ò ”«» ‰œ«—Ìœ.\n"
            "   ò«—»— ›ﬁÿ ò«‰›Ìê —« œ—Ì«›  „Ìùò‰œ.\n\n"
            "3?? <b>”«»  ‰Â«</b>\n"
            "   ›ﬁÿ ·Ì‰ò ”«»ù«”ò—ÌÅ‘‰ œ«—Ìœ° ò«‰›Ìê „” ﬁÌ„ ‰œ«—Ìœ.\n"
            "   ò«—»— ›ﬁÿ ·Ì‰ò ”«» —« œ—Ì«›  „Ìùò‰œ.", kb)
        return

    # adm:v2:sm:{mode}:{pkg_id} ? start single-mode flow (ask service name)
    if data.startswith("adm:v2:sm:"):
        parts = data.split(":")
        mode       = int(parts[3])
        package_id = int(parts[4])
        package_row = get_package(package_id)
        state_set(uid, "v2_single_name",
                  package_id=package_id, type_id=package_row["type_id"], mode=mode)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>‰«„ ”—ÊÌ”</b> —« Ê«—œ ò‰Ìœ:\n"
            "<i>(«Ì‰ ‰«„ »—«Ì ‘‰«”«ÌÌ ”—ÊÌ” œ— Å‰· «œ„Ì‰ Ê ‰„«Ì‘ »Â ò«—»— «” ›«œÂ „Ìù‘Êœ.)</i>",
            back_button(f"adm:v2:single:{package_id}"))
        return

    # ?? V2Ray: Bulk ???????????????????????????????????????????????????????????
    # adm:v2:bulk:{pkg_id}  ? choose bulk-registration mode
    if data.startswith("adm:v2:bulk:"):
        rest = data[len("adm:v2:bulk:"):]

        # adm:v2:bulk:{pkg_id}  ? mode selection
        if rest.isdigit():
            package_id = int(rest)
            package_row = get_package(package_id)
            state_set(uid, "v2_bulk_init",
                      package_id=package_id, type_id=package_row["type_id"])
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(
                "1?? ò«‰›Ìê + ”«» ó „‰«”»  ⁄œ«œ ò„",
                callback_data=f"adm:v2:bm:1:{package_id}"
            ))
            kb.add(types.InlineKeyboardButton(
                "2?? ò«‰›Ìê + ”«» ó „‰«”»  ⁄œ«œ “Ì«œ",
                callback_data=f"adm:v2:bm:2:{package_id}"
            ))
            kb.add(types.InlineKeyboardButton(
                "3?? ò«‰›Ìê  ‰Â«",
                callback_data=f"adm:v2:bm:3:{package_id}"
            ))
            kb.add(types.InlineKeyboardButton(
                "4?? ”«»  ‰Â«",
                callback_data=f"adm:v2:bm:4:{package_id}"
            ))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:proto:v2ray:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "?? <b>À»  œ” Âù«Ì V2Ray</b>\n\n"
                "‰Ê⁄ ò«‰›ÌêùÂ«ÌÌ òÂ „ÌùŒÊ«ÂÌœ À»  ò‰Ìœ —« «‰ Œ«» ò‰Ìœ:\n\n"
                "1?? <b>ò«‰›Ìê + ”«» ó  ⁄œ«œ ò„</b>\n"
                "   Â— ò«‰›Ìê Ìò ”«» Ãœ«ê«‰Â œ«—œ Ê  ⁄œ«œ ò„Ì Â” ‰œ (“Ì— ~??).\n"
                "   ò«‰›Ìê Ê ”«» —« ÌòÌ œ— „Ì«‰ Ê«—œ „Ìùò‰Ìœ.\n\n"
                "2?? <b>ò«‰›Ìê + ”«» ó  ⁄œ«œ “Ì«œ</b>\n"
                "   Â— ò«‰›Ìê Ìò ”«» Ãœ«ê«‰Â œ«—œ Ê  ⁄œ«œ “Ì«œÌ Â” ‰œ.\n"
                "   «» œ« Â„Â ò«‰›ÌêùÂ«° ”Å” Â„Â ”«»ùÂ« —« Ãœ«ê«‰Â «—”«· „Ìùò‰Ìœ.\n\n"
                "3?? <b>ò«‰›Ìê  ‰Â«</b>\n"
                "   ›ﬁÿ ò«‰›Ìê („À· vless://) œ«—Ìœ° ÂÌç ”«»ù«”ò—ÌÅ‘‰Ì ‰œ«—Ìœ.\n\n"
                "4?? <b>”«»  ‰Â«</b>\n"
                "   ›ﬁÿ ·Ì‰òùÂ«Ì ”«»ù«”ò—ÌÅ‘‰ œ«—Ìœ° ò«‰›Ìê „” ﬁÌ„ ‰œ«—Ìœ.", kb)
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
            kb.add(types.InlineKeyboardButton("? »œÊ‰ Å”Ê‰œ", callback_data=f"adm:v2:bulk:suf:skip:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:v2:bulk:{pkg_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "?? <b>Å”Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
                "«ê— «‰ Â«Ì ‰«„ ò«‰›ÌêùÂ« „ ‰ «÷«›Âù«Ì œ«—œ òÂ ‰„ÌùŒÊ«ÂÌœ ‰„«Ì‘ œ«œÂ ‘Êœ° «Ì‰Ã« Ê«—œ ò‰Ìœ.\n\n"
                "?? „À«·: <code>-main</code>\n\n"
                "«ê— Å”Ê‰œÌ ‰œ«—Ìœ œò„Â ´»œÊ‰ Å”Ê‰œª —« »“‰Ìœ.", kb)
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

    # adm:v2:bm:{mode}:{pkg_id}  ? bulk mode selected ? ask prefix (for configs) or go straight
    if data.startswith("adm:v2:bm:"):
        parts = data.split(":")
        mode       = int(parts[3])
        package_id = int(parts[4])
        s = state_data(uid)
        bot.answer_callback_query(call.id)

        if mode in (1, 2, 3):
            # Modes with configs ? ask prefix
            state_set(uid, "v2_bulk_pre",
                      package_id=package_id, type_id=s.get("type_id", 0), mode=mode)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("? »œÊ‰ ÅÌ‘Ê‰œ", callback_data=f"adm:v2:bulk:pref:skip:{package_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:v2:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "?? <b>ÅÌ‘Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
                "«ê— «» œ«Ì ‰«„ ò«‰›ÌêùÂ« „ ‰ «÷«›Âù«Ì („À· —Ì„«—ò «Ì‰»«‰œ) œ«—œ òÂ ‰„ÌùŒÊ«ÂÌœ œ— ‰«„ ”—ÊÌ” »«‘œ° «Ì‰Ã« Ê«—œ ò‰Ìœ.\n\n"
                "?? „À«·: <code>??TUN_-</code>\n\n"
                "«ê— ÅÌ‘Ê‰œÌ ‰œ«—Ìœ œò„Â ´»œÊ‰ ÅÌ‘Ê‰œª —« »“‰Ìœ.", kb)
        else:  # mode 4: sub only ó no prefix/suffix needed
            state_set(uid, "v2_bulk_data",
                      package_id=package_id, type_id=s.get("type_id", 0),
                      mode=4, prefix="", suffix="")
            prompt = _v2_bulk_data_prompt(4)
            send_or_edit(call, prompt, back_button(f"adm:v2:bulk:{package_id}"))
        return

    # ?? V2Ray Mode 2 Bulk: Step 2 ó receive subs after configs ???????????????
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
            f"? <b>{config_count}</b> ò«‰›Ìê œ—Ì«›  ‘œ.\n\n"
            "?? <b>Õ«·« Â„Â ”«»ùÂ« —« «—”«· ò‰Ìœ.</b>\n\n"
            f"?? »«Ìœ œﬁÌﬁ« <b>{config_count}</b> ”«» «—”«· ò‰Ìœ  « »« ò«‰›ÌêùÂ« Ã›  ‘Ê‰œ.\n"
            " — Ì» „Â„ «” : ”«» «Ê· »« ò«‰›Ìê «Ê· Ã›  „Ìù‘Êœ° ”«» œÊ„ »« ò«‰›Ìê œÊ„ Ê ...\n\n"
            "?? „Ìù Ê«‰Ìœ Ìò ›«Ì· <b>.txt</b> (Â— Œÿ Ìò ”«») «—”«· ò‰Ìœ.",
            parse_mode="HTML",
            reply_markup=back_button(f"adm:v2:bulk:{package_id}"))
        return

    # ?? Legacy: adm:cfg:single / adm:cfg:bulk (redirect) ?????????????????????
    if data.startswith("adm:cfg:single:"):
        package_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        # Redirect to new V2Ray single flow
        package_row = get_package(package_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("1?? À»  ò«‰›Ìê + ”«» Ãœ«ê«‰Â", callback_data=f"adm:v2:sm:1:{package_id}"))
        kb.add(types.InlineKeyboardButton("2?? À»  ò«‰›Ìê  ‰Â«",          callback_data=f"adm:v2:sm:2:{package_id}"))
        kb.add(types.InlineKeyboardButton("3?? À»  ”«»  ‰Â«",             callback_data=f"adm:v2:sm:3:{package_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:proto:v2ray:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>À»   òÌ V2Ray</b>\n\n‰Ê⁄ À»  —« «‰ Œ«» ò‰Ìœ:", kb)
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
                "?? <b>Å”Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
                "Êﬁ Ì ç‰œ « «ò” —‰«· Å—Êò”Ì ”  „Ìùò‰Ìœ° «‰ Â«Ì ‰«„ ò«‰›Ìê „ ‰ùÂ«Ì «÷«›Â «ò” —‰«·ùÂ« «÷«›Â „Ìù‘Êœ.\n"
                "«ê— ‰„ÌùŒÊ«ÂÌœ ¬‰ùÂ« œ— ‰«„ ò«‰›Ìê »Ì«Ìœ° Å”Ê‰œ —« «Ì‰Ã« Ê«—œ ò‰Ìœ.\n\n"
                "?? „À«·: <code>-main</code>",
                back_button("admin:add_config"))
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("? »⁄œÌ (»œÊ‰ Å”Ê‰œ)", callback_data=f"adm:cfg:bulk:skipsuf:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:add_config", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "?? <b>Å”Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
                "Êﬁ Ì ç‰œ « «ò” —‰«· Å—Êò”Ì ”  „Ìùò‰Ìœ° «‰ Â«Ì ‰«„ ò«‰›Ìê „ ‰ùÂ«Ì «÷«›Â «ò” —‰«·ùÂ« «÷«›Â „Ìù‘Êœ.\n"
                "«ê— ‰„ÌùŒÊ«ÂÌœ ¬‰ùÂ« œ— ‰«„ ò«‰›Ìê »Ì«Ìœ° Å”Ê‰œ —« «Ì‰Ã« Ê«—œ ò‰Ìœ.\n\n"
                "?? „À«·: <code>-main</code>", kb)
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
                    "?? <b>«—”«· ò«‰›ÌêùÂ«</b>\n\n"
                    "ò«‰›ÌêùÂ« —« «—”«· ò‰Ìœ. œÊ —Ê‘ ÊÃÊœ œ«—œ:\n\n"
                    "<b>?? —Ê‘ «Ê·: «—”«· „ ‰Ì</b>\n"
                    "Â— ò«‰›Ìê <b>œÊ Œÿ</b> œ«—œ:\n"
                    "Œÿ «Ê·: ·Ì‰ò ò«‰›Ìê\n"
                    "Œÿ œÊ„: ·Ì‰ò «” ⁄·«„ (‘—Ê⁄ »« http)\n\n"
                    "?? „À«·:\n"
                    "<code>vless://abc...#name1\n"
                    "http://panel.com/sub/1\n"
                    "vless://def...#name2\n"
                    "http://panel.com/sub/2</code>\n\n"
                    "<b>?? —Ê‘ œÊ„: «—”«· ›«Ì· TXT</b>\n"
                    "«ê—  ⁄œ«œ ò«‰›ÌêùÂ«Ì «‰ “Ì«œ «”  (»Ì‘ «“ ??-?? ⁄œœ)° "
                    "Ìò ›«Ì· <b>.txt</b> »”«“Ìœ Ê  „«„ ·Ì‰òùÂ« —« œ— ¬‰ ﬁ—«— œÂÌœ "
                    "(Â— Œÿ Ìò ò«‰›Ìê + Œÿ »⁄œÌ ·Ì‰ò «” ⁄·«„)° ”Å” ›«Ì· —« «—”«· ò‰Ìœ."
                )
            else:
                fmt_text = (
                    "?? <b>«—”«· ò«‰›ÌêùÂ«</b>\n\n"
                    "ò«‰›ÌêùÂ« —« «—”«· ò‰Ìœ. œÊ —Ê‘ ÊÃÊœ œ«—œ:\n\n"
                    "<b>?? —Ê‘ «Ê·: «—”«· „ ‰Ì</b>\n"
                    "Â— Œÿ Ìò ·Ì‰ò ò«‰›Ìê:\n\n"
                    "?? „À«·:\n"
                    "<code>vless://abc...#name1\n"
                    "vless://def...#name2</code>\n\n"
                    "<b>?? —Ê‘ œÊ„: «—”«· ›«Ì· TXT</b>\n"
                    "«ê—  ⁄œ«œ ò«‰›ÌêùÂ«Ì «‰ “Ì«œ «”  (»Ì‘ «“ ??-?? ⁄œœ)° "
                    "Ìò ›«Ì· <b>.txt</b> »”«“Ìœ Ê  „«„ ·Ì‰ò ò«‰›ÌêùÂ« —« œ— ¬‰ ﬁ—«— œÂÌœ "
                    "(Â— Œÿ Ìò ò«‰›Ìê)° ”Å” ›«Ì· —« «—”«· ò‰Ìœ."
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
            kb.add(types.InlineKeyboardButton("? »⁄œÌ (»œÊ‰ ÅÌ‘Ê‰œ)", callback_data=f"adm:cfg:bulk:skippre:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:add_config", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "?? <b>ÅÌ‘Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
                "“„«‰Ì òÂ ò«‰›Ìê —« œ— Å‰· „Ìù”«“Ìœ° «ê— «Ì‰»«‰œ <b>—Ì„«—ò (Remark)</b> œ«—œ° "
                "«» œ«Ì ‰«„ ò«‰›Ìê «÷«›Â „Ìù‘Êœ.\n"
                "«ê— ‰„ÌùŒÊ«ÂÌœ ¬‰ œ— ‰«„ ò«‰›Ìê »Ì«Ìœ° ÅÌ‘Ê‰œ —« «Ì‰Ã« Ê«—œ ò‰Ìœ.\n\n"
                "?? „À«·: <code>%E2%9A%95%EF%B8%8FTUN_-</code>\n"
                "Ì«: <code>??TUN_-</code>", kb)
            return

        # Initial: ask about inquiry links
        package_id  = int(rest)
        package_row = get_package(package_id)
        state_set(uid, "admin_bulk_init", package_id=package_id, type_id=package_row["type_id"])
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("? »·Â", callback_data=f"adm:cfg:bulk:inq:y:{package_id}"),
            types.InlineKeyboardButton("? ŒÌ—", callback_data=f"adm:cfg:bulk:inq:n:{package_id}"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:cfg:p:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ¬Ì« ò«‰›ÌêùÂ« <b>·Ì‰ò «” ⁄·«„</b> Â„ œ«—‰œø", kb)
        return

    # ?? Admin: Stock / Config management ?????????????????????????????????????
    if data == "admin:stock":
        if not (admin_has_perm(uid, "view_configs") or admin_has_perm(uid, "register_config") or admin_has_perm(uid, "manage_configs")):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
                mark = "?"
            elif c["sold_to"]:
                mark = "??"
            else:
                mark = "??"
            svc = urllib.parse.unquote(c["service_name"] or "")
            kb.add(types.InlineKeyboardButton(f"{mark} {svc}", callback_data=f"adm:stk:cfg:{c['id']}"))
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton("?? ﬁ»·Ì", callback_data=f"adm:stk:all:{kind_str}:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton("»⁄œÌ ??", callback_data=f"adm:stk:all:{kind_str}:{page+1}"))
        if nav_row:
            kb.row(*nav_row)
        # Bulk action buttons
        if kind_str in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton("?? Õ–› Â„ê«‰Ì",   callback_data=f"adm:stk:blkA:{kind_str}"),
                types.InlineKeyboardButton("? „‰ﬁ÷Ì Â„ê«‰Ì", callback_data=f"adm:stk:blkA:{kind_str}"),
            )
        else:
            kb.add(types.InlineKeyboardButton("?? Õ–› Â„ê«‰Ì", callback_data=f"adm:stk:blkA:{kind_str}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:stock", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        if kind_str == "sl":
            label_kind = "?? ò· ›—ÊŒ Â ‘œÂ"
        elif kind_str == "ex":
            label_kind = "? ò· „‰ﬁ÷Ì ‘œÂ"
        else:
            label_kind = "?? ò· „ÊÃÊœ"
        send_or_edit(call, f"?? {label_kind} | ’›ÕÂ {page+1}/{total_pages} |  ⁄œ«œ ò·: {total}", kb)
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
            types.InlineKeyboardButton(f"?? „«‰œÂ ({avail})",       callback_data=f"adm:stk:av:{package_id}:0"),
            types.InlineKeyboardButton(f"?? ›—ÊŒ Â ({sold})",       callback_data=f"adm:stk:sl:{package_id}:0"),
        )
        kb.add(types.InlineKeyboardButton(f"? „‰ﬁ÷Ì ({expired})",  callback_data=f"adm:stk:ex:{package_id}:0"))
        if pending_c > 0:
            kb.add(types.InlineKeyboardButton(
                f"?  ÕÊÌ· {pending_c} ”›«—‘ œ— «‰ Ÿ«—",
                callback_data=f"adm:stk:fulfill:{package_id}"
            ))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:stock", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        pending_line = f"\n? ”›«—‘ œ— «‰ Ÿ«—: {pending_c}" if pending_c > 0 else ""
        text = (
            f"?? <b>{esc(package_row['name'])}</b>\n\n"
            f"?? „ÊÃÊœ: {avail}\n"
            f"?? ›—ÊŒ Â ‘œÂ: {sold}\n"
            f"? „‰ﬁ÷Ì ‘œÂ: {expired}"
            f"{pending_line}"
        )
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:stk:fulfill:") and data.split(":")[3].isdigit():
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        with get_conn() as conn:
            pending_c = conn.execute(
                "SELECT COUNT(*) AS n FROM pending_orders WHERE package_id=? AND status='waiting'",
                (package_id,)
            ).fetchone()["n"]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "?  ÕÊÌ· ŒÊœò«— «“ „ÊÃÊœÌ",
            callback_data=f"adm:stk:fulfill:auto:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton(
            "?? À»  ò«‰›Ìê ÃœÌœ ( òÌ/⁄„œÂ) +  ÕÊÌ·",
            callback_data=f"adm:stk:fulfill:addcfg:{package_id}"
        ))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:stk:pk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"? <b> ÕÊÌ· {pending_c} ”›«—‘ œ— «‰ Ÿ«—</b>\n\n"
            f"?? ÅòÌÃ: <b>{esc(package_row['name'])}</b>\n\n"
            "—Ê‘  ÕÊÌ· —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    # adm:stk:fulfill:auto:{pkg_id}  ?  auto-deliver from existing stock
    if data.startswith("adm:stk:fulfill:auto:"):
        package_id = int(data.split(":")[4])
        bot.answer_callback_query(call.id, "? œ— Õ«·  ÕÊÌ· ”›«—‘ùÂ«...")
        try:
            fulfilled = auto_fulfill_pending_orders(package_id)
            if fulfilled > 0:
                send_or_edit(call,
                    f"? <b>{fulfilled}</b> ”›«—‘ »« „Ê›ﬁÌ  «“ „ÊÃÊœÌ  ÕÊÌ· œ«œÂ ‘œ.",
                    back_button(f"adm:stk:pk:{package_id}"))
            else:
                with get_conn() as conn:
                    remaining = conn.execute(
                        "SELECT COUNT(*) AS n FROM pending_orders WHERE package_id=? AND status='waiting'",
                        (package_id,)
                    ).fetchone()["n"]
                if remaining > 0:
                    send_or_edit(call,
                        f"?? <b>{remaining}</b> ”›«—‘ œ— «‰ Ÿ«— ÊÃÊœ œ«—œ Ê·Ì „ÊÃÊœÌ ò«›Ì ‰Ì” .\n\n"
                        "»—«Ì À»  ò«‰›Ìê ÃœÌœ —ÊÌ œò„Â ´À»  ò«‰›Ìê ÃœÌœª »“‰Ìœ.",
                        back_button(f"adm:stk:pk:{package_id}"))
                else:
                    send_or_edit(call, "? ÂÌç ”›«—‘ œ— «‰ Ÿ«—Ì ÊÃÊœ ‰œ«—œ.",
                                 back_button(f"adm:stk:pk:{package_id}"))
        except Exception as e:
            send_or_edit(call,
                f"? Œÿ«:\n<code>{esc(str(e))}</code>",
                back_button(f"adm:stk:pk:{package_id}"))
        return

    # adm:stk:fulfill:addcfg:{pkg_id}  ?  register new config(s) then auto-deliver
    if data.startswith("adm:stk:fulfill:addcfg:"):
        package_id  = int(data.split(":")[4])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        # Redirect to the normal config-registration protocol selector,
        # but save fulfill_after=True in state so after registration runs auto_fulfill.
        state_set(uid, "admin_cfg_proto_select",
                  package_id=package_id,
                  type_id=package_row["type_id"],
                  fulfill_after=True)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? V2Ray",    callback_data=f"adm:cfg:proto:v2ray:{package_id}"))
        kb.add(types.InlineKeyboardButton("?? OpenVPN",  callback_data=f"adm:cfg:proto:ovpn:{package_id}"))
        kb.add(types.InlineKeyboardButton("?? WireGuard", callback_data=f"adm:cfg:proto:wg:{package_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:stk:fulfill:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>{esc(package_row['name'])}</b>\n\n"
            "?? <b>Å—Ê ò· ò«‰›Ìê ÃœÌœ —« «‰ Œ«» ò‰Ìœ:</b>\n"
            "<i>Å” «“ À» ° ”›«—‘ùÂ«Ì œ— «‰ Ÿ«— »Âù’Ê—  ŒÊœò«—  ÕÊÌ· œ«œÂ „Ìù‘Ê‰œ.</i>", kb)
        return

    # adm:stk:fulfill:addcfg:{pkg_id}  ?  register new config(s) then auto-deliver
    if data.startswith("adm:stk:fulfill:addcfg:"):
        package_id  = int(data.split(":")[4])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        # Redirect to the normal config-registration protocol selector,
        # but save fulfill_after=True in state so after registration runs auto_fulfill.
        state_set(uid, "admin_cfg_proto_select",
                  package_id=package_id,
                  type_id=package_row["type_id"],
                  fulfill_after=True)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? V2Ray",    callback_data=f"adm:cfg:proto:v2ray:{package_id}"))
        kb.add(types.InlineKeyboardButton("?? OpenVPN",  callback_data=f"adm:cfg:proto:ovpn:{package_id}"))
        kb.add(types.InlineKeyboardButton("?? WireGuard", callback_data=f"adm:cfg:proto:wg:{package_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:stk:fulfill:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>{esc(package_row['name'])}</b>\n\n"
            "?? <b>Å—Ê ò· ò«‰›Ìê ÃœÌœ —« «‰ Œ«» ò‰Ìœ:</b>\n"
            "<i>Å” «“ À» ° ”›«—‘ùÂ«Ì œ— «‰ Ÿ«— »Âù’Ê—  ŒÊœò«—  ÕÊÌ· œ«œÂ „Ìù‘Ê‰œ.</i>", kb)
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
                mark = "?"
            elif c["sold_to"]:
                mark = "??"
            else:
                mark = "??"
            svc = urllib.parse.unquote(c["service_name"] or "")
            kb.add(types.InlineKeyboardButton(f"{mark} {svc}", callback_data=f"adm:stk:cfg:{c['id']}"))
        # Pagination
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton("?? ﬁ»·", callback_data=f"adm:stk:{kind_str}:{package_id}:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton("»⁄œ ??", callback_data=f"adm:stk:{kind_str}:{package_id}:{page+1}"))
        if nav_row:
            kb.row(*nav_row)
        # Bulk action buttons
        if kind_str in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton("?? Õ–› Â„ê«‰Ì",   callback_data=f"adm:stk:blk:{kind_str}:{package_id}"),
                types.InlineKeyboardButton("? „‰ﬁ÷Ì Â„ê«‰Ì", callback_data=f"adm:stk:blk:{kind_str}:{package_id}"),
            )
        else:
            kb.add(types.InlineKeyboardButton("?? Õ–› Â„ê«‰Ì", callback_data=f"adm:stk:blk:{kind_str}:{package_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:stk:pk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        if kind_str == "sl":
            label_kind = "?? ›—ÊŒ Â ‘œÂ"
        elif kind_str == "ex":
            label_kind = "? „‰ﬁ÷Ì ‘œÂ"
        else:
            label_kind = "?? „ÊÃÊœ"
        send_or_edit(call, f"?? {label_kind} | ’›ÕÂ {page+1}/{total_pages} |  ⁄œ«œ ò·: {total}", kb)
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
            bot.answer_callback_query(call.id, "Ì«›  ‰‘œ.", show_alert=True)
            return
        _has_cfg = bool(row['config_text'] and row['config_text'].strip())
        _has_sub = bool(row['inquiry_link'] and row['inquiry_link'].strip())
        if _has_cfg and _has_sub:
            _reg_mode = "ò«‰›Ìê + ”«»"
        elif _has_cfg:
            _reg_mode = "ò«‰›Ìê  ‰Â«"
        elif _has_sub:
            _reg_mode = "”«»  ‰Â«"
        else:
            _reg_mode = "ó"
        text = (
            f"?? ‰«„ ”—ÊÌ”: <b>{esc(urllib.parse.unquote(row['service_name'] or ''))}</b>\n"
            f"?? ‰Ê⁄ ”—ÊÌ”: {esc(row['type_name'])}\n"
            f"?? ‰Ê⁄ À» : {_reg_mode}\n"
            f"?? ÕÃ„: {fmt_vol(row['volume_gb'])}\n"
            f"? „œ : {fmt_dur(row['duration_days'])}\n\n"
        )
        if _has_cfg:
            text += f"?? Config:\n<code>{esc(row['config_text'])}</code>\n\n"
        if _has_sub:
            text += f"?? Subscription:\n<code>{esc(row['inquiry_link'])}</code>\n\n"
        text += f"?? À» : {esc(row['created_at'])}"
        kb = types.InlineKeyboardMarkup()
        if row["sold_to"]:
            buyer = get_user_detail(row["sold_to"])
            if buyer:
                text += (
                    f"\n\n?? <b>Œ—Ìœ«—:</b>\n"
                    f"‰«„: {esc(buyer['full_name'])}\n"
                    f"‰«„ ò«—»—Ì: {esc(display_username(buyer['username']))}\n"
                    f"¬ÌœÌ: <code>{buyer['user_id']}</code>\n"
                    f"“„«‰ Œ—Ìœ: {esc(row['sold_at'] or '-')}"
                )
        if not row["is_expired"]:
            kb.add(types.InlineKeyboardButton("? „‰ﬁ÷Ì ò—œ‰", callback_data=f"adm:stk:exp:{config_id}:{row['package_id']}"))
        else:
            text += "\n\n?? «Ì‰ ”—ÊÌ” „‰ﬁ÷Ì ‘œÂ «” ."
        kb.row(
            types.InlineKeyboardButton("?? ÊÌ—«Ì‘", callback_data=f"adm:stk:edt:{config_id}"),
            types.InlineKeyboardButton("?? Õ–› ò«‰›Ìê", callback_data=f"adm:stk:del:{config_id}:{row['package_id']}"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:stk:pk:{row['package_id']}", icon_custom_emoji_id="5253997076169115797"))
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
        # adm:stk:edt:{config_id}                 ? edit menu
        # adm:stk:edt:pkg:{config_id}             ? choose type for package edit
        # adm:stk:edt:pkgt:{config_id}:{type_id}  ? choose package within type
        # adm:stk:edt:pkgp:{config_id}:{pkg_id}   ? confirm package change
        # adm:stk:edt:svc:{config_id}             ? edit service name
        # adm:stk:edt:cfg:{config_id}             ? edit config text
        # adm:stk:edt:inq:{config_id}             ? edit inquiry link

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
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:stk:edt:{config_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? ‰Ê⁄ ”—ÊÌ” —« «‰ Œ«» ò‰Ìœ:", kb)
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
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:stk:edt:pkg:{config_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? ÅòÌÃ —« «‰ Œ«» ò‰Ìœ:", kb)
            return

        if sub == "pkgp":
            config_id  = int(parts[4])
            package_id = int(parts[5])
            pkg = get_package(package_id)
            update_config_field(config_id, "package_id", package_id)
            if pkg:
                update_config_field(config_id, "type_id", pkg["type_id"])
            log_admin_action(uid, f"ÅòÌÃ ò«‰›Ìê #{config_id} »Â #{package_id}  €ÌÌ— ò—œ")
            bot.answer_callback_query(call.id, "? ÅòÌÃ  €ÌÌ— ò—œ.")
            _fake_call(call, f"adm:stk:cfg:{config_id}")
            return

        if sub == "svc":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_svc", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? ‰«„ ”—ÊÌ” ÃœÌœ —« «—”«· ò‰Ìœ:", back_button(f"adm:stk:edt:{config_id}"))
            return

        if sub == "cfg":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_text", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? „ ‰ ò«‰›Ìê ÃœÌœ —« «—”«· ò‰Ìœ:", back_button(f"adm:stk:edt:{config_id}"))
            return

        if sub == "inq":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_inq", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "?? ·Ì‰ò «” ⁄·«„ ÃœÌœ —« «—”«· ò‰Ìœ.\n"
                "»—«Ì Õ–› ·Ì‰ò° <code>-</code> »›—” Ìœ.",
                back_button(f"adm:stk:edt:{config_id}"))
            return

        # Default: show edit menu
        config_id = int(sub)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ ÅòÌÃ",         callback_data=f"adm:stk:edt:pkg:{config_id}"))
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ ‰«„ ”—ÊÌ”",    callback_data=f"adm:stk:edt:svc:{config_id}"))
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ „ ‰ ò«‰›Ìê",   callback_data=f"adm:stk:edt:cfg:{config_id}"))
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ ·Ì‰ò «” ⁄·«„", callback_data=f"adm:stk:edt:inq:{config_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:stk:cfg:{config_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>ÊÌ—«Ì‘ ò«‰›Ìê</b>\n\nçÂ çÌ“Ì —« ÊÌ—«Ì‘ „Ìùò‰Ìœø", kb)
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
                    "?? ÌòÌ «“ ”—ÊÌ”ùÂ«Ì ‘„«  Ê”ÿ «œ„Ì‰ „‰ﬁ÷Ì «⁄·«„ ‘œÂ «” .\n»—«Ì  „œÌœ »« Å‘ Ì»«‰Ì  „«” »êÌ—Ìœ."
                )
            except Exception:
                pass
        bot.answer_callback_query(call.id, "”—ÊÌ” „‰ﬁ÷Ì ‘œ.")
        back = back_button(f"adm:stk:pk:{package_id}") if package_id else back_button("admin:stock")
        send_or_edit(call, "? ”—ÊÌ” „‰ﬁ÷Ì «⁄·«„ ‘œ.", back)
        return

    if data.startswith("adm:stk:del:"):
        parts = data.split(":")
        config_id  = int(parts[3])
        package_id = int(parts[4]) if len(parts) > 4 else 0
        with get_conn() as conn:
            conn.execute("DELETE FROM configs WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "ò«‰›Ìê Õ–› ‘œ.")
        back = back_button(f"adm:stk:pk:{package_id}") if package_id else back_button("admin:stock")
        send_or_edit(call, "? ò«‰›Ìê »« „Ê›ﬁÌ  Õ–› ‘œ.", back)
        return

    # ?? Admin: Bulk select ó All packages entry (must be before blk: check) ??
    if data.startswith("adm:stk:blkA:"):
        kind = data.split(":")[3]  # av / sl / ex
        if not (admin_has_perm(uid, "manage_configs") or uid in ADMIN_IDS):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "stk_bulk", kind=kind, scope="all", pkg_id=0, page=0, selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ?? Admin: Bulk select ó Per-package entry ????????????????????????????????
    if data.startswith("adm:stk:blk:"):
        parts  = data.split(":")
        kind   = parts[3]         # av / sl / ex
        pkg_id = int(parts[4])    # package_id
        if not (admin_has_perm(uid, "manage_configs") or uid in ADMIN_IDS):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "stk_bulk", kind=kind, scope="pk", pkg_id=pkg_id, page=0, selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ?? Admin: Bulk select ó Toggle individual config ?????????????????????????
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

    # ?? Admin: Bulk select ó Select all on current page ???????????????????????
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

    # ?? Admin: Bulk select ó Deselect current page ????????????????????????????
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

    # ?? Admin: Bulk select ó Clear all selections ?????????????????????????????
    if data == "adm:stk:bclrall":
        sd = state_data(uid)
        state_set(uid, "stk_bulk",
                  kind=sd.get("kind", "av"), scope=sd.get("scope", "pk"),
                  pkg_id=sd.get("pkg_id", 0), page=sd.get("page", 0),
                  selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ?? Admin: Bulk select ó Navigate pages ???????????????????????????????????
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

    # ?? Admin: Bulk select ó Execute delete ???????????????????????????????????
    if data == "adm:stk:bdel":
        sd      = state_data(uid)
        sel_raw = sd.get("selected", "")
        ids     = [int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit()]
        if not ids:
            bot.answer_callback_query(call.id, "?? ÂÌç „Ê—œÌ «‰ Œ«» ‰‘œÂ.", show_alert=True)
            return
        with get_conn() as conn:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM configs WHERE id IN ({placeholders})", ids)
        state_clear(uid)
        bot.answer_callback_query(call.id, f"? {len(ids)} ò«‰›Ìê Õ–› ‘œ.", show_alert=True)
        send_or_edit(call, f"? <b>{len(ids)}</b> ò«‰›Ìê »« „Ê›ﬁÌ  Õ–› ‘œ.", back_button("admin:stock"))
        return

    # ?? Admin: Bulk select ó Execute expire ???????????????????????????????????
    if data == "adm:stk:bexp":
        sd      = state_data(uid)
        sel_raw = sd.get("selected", "")
        ids     = [int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit()]
        if not ids:
            bot.answer_callback_query(call.id, "?? ÂÌç „Ê—œÌ «‰ Œ«» ‰‘œÂ.", show_alert=True)
            return
        with get_conn() as conn:
            for cfg_id in ids:
                conn.execute("UPDATE configs SET is_expired=1 WHERE id=?", (cfg_id,))
        state_clear(uid)
        bot.answer_callback_query(call.id, f"? {len(ids)} ò«‰›Ìê „‰ﬁ÷Ì ‘œ.", show_alert=True)
        send_or_edit(call, f"? <b>{len(ids)}</b> ò«‰›Ìê „‰ﬁ÷Ì «⁄·«„ ‘œ.", back_button("admin:stock"))
        return

    # ?? Admin: Bulk select ó Cancel / back ????????????????????????????????????
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

    # ?? Admin: Stock Search ???????????????????????????????????????????????????
    if data == "adm:stk:search":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? ·Ì‰ò «” ⁄·«„", callback_data="adm:stk:srch:link"))
        kb.add(types.InlineKeyboardButton("?? „ ‰ ò«‰›Ìê", callback_data="adm:stk:srch:cfg"))
        kb.add(types.InlineKeyboardButton("?? ‰«„ ”—ÊÌ”", callback_data="adm:stk:srch:name"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:stock", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "?? Ã” ÃÊ »— «”«”:", kb)
        bot.answer_callback_query(call.id)
        return

    if data == "adm:stk:srch:link":
        state_set(call.from_user.id, "admin_search_by_link")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ·Ì‰ò «” ⁄·«„ (Ì« »Œ‘Ì «“ ¬‰) —« «—”«· ò‰Ìœ:", back_button("adm:stk:search"))
        return

    if data == "adm:stk:srch:cfg":
        state_set(call.from_user.id, "admin_search_by_config")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? „ ‰ ò«‰›Ìê (Ì« »Œ‘Ì «“ ¬‰) —« «—”«· ò‰Ìœ:", back_button("adm:stk:search"))
        return

    if data == "adm:stk:srch:name":
        state_set(call.from_user.id, "admin_search_by_name")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ‰«„ ”—ÊÌ” (Ì« »Œ‘Ì «“ ¬‰) —« «—”«· ò‰Ìœ:", back_button("adm:stk:search"))
        return

    # ?? Admin: Users ??????????????????????????????????????????????????????????
    if data == "admin:users":
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        _show_admin_users_list(call)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("admin:users:pg:"):
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        page = int(data.split(":")[-1])
        _show_admin_users_list(call, page=page)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("adm:usr:fl:"):
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts       = data.split(":")
        filter_mode = parts[3]
        page        = int(parts[4]) if len(parts) > 4 else 0
        _show_admin_users_list(call, page=page, filter_mode=filter_mode)
        bot.answer_callback_query(call.id)
        return

    # ?? Admin: User search ????????????????????????????????????????????????????
    if data == "adm:usr:search":
        state_set(uid, "admin_user_search")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>Ã” ÃÊÌ ò«—»—</b>\n\n"
            "„Ìù Ê«‰Ìœ »— «”«” „Ê«—œ “Ì— Ã” ÃÊ ò‰Ìœ:\n"
            "ï <b>¬ÌœÌ ⁄œœÌ</b> („À«·: <code>123456789</code>)\n"
            "ï <b>‰«„ ò«—»—Ì</b> („À«·: <code>@username</code>)\n"
            "ï <b>‰«„ «ò«‰ </b> („À«·: <code>⁄·Ì</code>)\n\n"
            "„ﬁœ«— Ã” ÃÊ —« «—”«· ò‰Ìœ:",
            back_button("admin:users"))
        return

    # ?? Admin: Bulk user operations ??????????????????????????????????????????
    if data == "adm:usr:bulk":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? «÷«›Â ò—œ‰ „ÊÃÊœÌ",      callback_data="adm:bulk:op:add_balance"))
        kb.add(types.InlineKeyboardButton("? ò«Â‘ „ÊÃÊœÌ",            callback_data="adm:bulk:op:sub_balance"))
        kb.add(types.InlineKeyboardButton("0?? ’›— ò—œ‰ Â„Â „ÊÃÊœÌ",    callback_data="adm:bulk:op:zero_balance"))
        kb.add(types.InlineKeyboardButton("?? «„‰ ò—œ‰ ò«—»—«‰",        callback_data="adm:bulk:op:set_safe"))
        kb.add(types.InlineKeyboardButton("?? ‰««„‰ ò—œ‰ ò«—»—«‰",      callback_data="adm:bulk:op:set_unsafe"))
        kb.add(types.InlineKeyboardButton("?? „ÕœÊœ ò—œ‰ ò«—»—«‰",      callback_data="adm:bulk:op:set_restricted"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:users",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "? <b>⁄„·Ì«  ê—ÊÂÌ</b>\n\n⁄„·Ì«  „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:",
            kb)
        return

    if data.startswith("adm:bulk:op:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        op = data.split(":")[3]
        bot.answer_callback_query(call.id)
        _OP_LABELS = {
            "add_balance":    "? «÷«›Â ò—œ‰ „ÊÃÊœÌ",
            "sub_balance":    "? ò«Â‘ „ÊÃÊœÌ",
            "zero_balance":   "0?? ’›— ò—œ‰ Â„Â „ÊÃÊœÌ",
            "set_safe":       "?? «„‰ ò—œ‰",
            "set_unsafe":     "?? ‰««„‰ ò—œ‰",
            "set_restricted": "?? „ÕœÊœ ò—œ‰",
        }
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Â„Â ò«—»—«‰",        callback_data=f"adm:bulk:tgt:{op}:all"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ ò«—»—«‰ ⁄«œÌ",   callback_data=f"adm:bulk:tgt:{op}:public"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ ‰„«Ì‰œê«‰",      callback_data=f"adm:bulk:tgt:{op}:agents"))
        kb.add(types.InlineKeyboardButton("?? «‰ Œ«» ò«—»—«‰ Œ«’", callback_data=f"adm:bulk:tgt:{op}:pick:0"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:usr:bulk",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"? <b>⁄„·Ì«  ê—ÊÂÌ</b>: {_OP_LABELS.get(op, op)}\n\n—ÊÌ çÂ œ” Âù«Ì «⁄„«· ‘Êœø",
            kb)
        return

    if data.startswith("adm:bulk:tgt:"):
        # adm:bulk:tgt:{op}:{filter}  OR  adm:bulk:tgt:{op}:pick:{page}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
                check = "?" if u["user_id"] in selected else "?"
                name  = u["full_name"] or str(u["user_id"])
                kb.add(types.InlineKeyboardButton(
                    f"{check} {name[:25]}",
                    callback_data=f"adm:bulk:pick:{u['user_id']}:{page}"))

            nav = []
            if page > 0:
                nav.append(types.InlineKeyboardButton("??", callback_data=f"adm:bulk:tgt:{op}:pick:{page-1}"))
            nav.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav.append(types.InlineKeyboardButton("??", callback_data=f"adm:bulk:tgt:{op}:pick:{page+1}"))
            if nav:
                kb.row(*nav)
            kb.add(types.InlineKeyboardButton(
                f"?  «ÌÌœ Ê «Ã—« ({len(selected)} ‰›— «‰ Œ«» ‘œÂ)",
                callback_data=f"adm:bulk:confirm:{op}:pick"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:bulk:op:{op}",
                                              icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                f"?? <b>«‰ Œ«» ò«—»—«‰</b> ó ’›ÕÂ {page+1}/{total_pages}\n"
                f"? {len(selected)} ‰›— «‰ Œ«» ‘œÂ\n\nò·Ìò ò‰Ìœ  « «‰ Œ«»/·€Ê ‘Êœ:",
                kb)
            return

        # filter = all / public / agents ? ask for amount if needed, else confirm
        bot.answer_callback_query(call.id)
        _needs_amount = op in ("add_balance", "sub_balance")
        if _needs_amount:
            state_set(uid, "bulk_amount", op=op, filter_type=filt)
            _FLT = {"all": "Â„Â ò«—»—«‰", "public": "ò«—»—«‰ ⁄«œÌ", "agents": "‰„«Ì‰œê«‰"}
            _OP_L = {"add_balance": "«›“Êœ‰", "sub_balance": "ò«Â‘"}
            send_or_edit(call,
                f"? <b>⁄„·Ì«  ê—ÊÂÌ</b>: {_OP_L[op]} „ÊÃÊœÌ\n"
                f"?? Âœ›: {_FLT.get(filt, filt)}\n\n"
                "?? <b>„»·€</b> ( Ê„«‰) —« Ê«—œ ò‰Ìœ:",
                back_button(f"adm:bulk:op:{op}"))
        else:
            count = count_users_by_filter(filt)
            state_set(uid, "bulk_confirm_ready", op=op, filter_type=filt, selected=[], amount=0)
            _FLT = {"all": "Â„Â ò«—»—«‰", "public": "ò«—»—«‰ ⁄«œÌ", "agents": "‰„«Ì‰œê«‰"}
            _OP_L2 = {
                "zero_balance": "’›— ò—œ‰ „ÊÃÊœÌ",
                "set_safe": "«„‰ ò—œ‰",
                "set_unsafe": "‰««„‰ ò—œ‰",
                "set_restricted": "„ÕœÊœ ò—œ‰",
            }
            kb2 = types.InlineKeyboardMarkup()
            kb2.add(types.InlineKeyboardButton(
                f"?  «ÌÌœ ó «Ã—« —ÊÌ {count} ò«—»—",
                callback_data=f"adm:bulk:exec:{op}:{filt}:0"))
            kb2.add(types.InlineKeyboardButton("·€Ê", callback_data="adm:usr:bulk",
                                               icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                f"? <b> «ÌÌœ ⁄„·Ì«  ê—ÊÂÌ</b>\n\n"
                f"⁄„·Ì« : <b>{_OP_L2.get(op, op)}</b>\n"
                f"Âœ›: <b>{_FLT.get(filt, filt)}</b>\n"
                f" ⁄œ«œ ò«—»—«‰: <b>{count}</b>",
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
        bot.answer_callback_query(call.id, f"{'? «‰ Œ«» ‘œ' if pick_uid in selected else '? ·€Ê ‘œ'}")
        # Re-render same page
        _PER      = 10
        all_users = get_users()
        total     = len(all_users)
        page_users = all_users[page * _PER:(page + 1) * _PER]
        total_pages = max(1, (total + _PER - 1) // _PER)
        kb = types.InlineKeyboardMarkup()
        for u in page_users:
            check = "?" if u["user_id"] in selected else "?"
            name  = u["full_name"] or str(u["user_id"])
            kb.add(types.InlineKeyboardButton(
                f"{check} {name[:25]}",
                callback_data=f"adm:bulk:pick:{u['user_id']}:{page}"))
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton("??", callback_data=f"adm:bulk:tgt:{op}:pick:{page-1}"))
        nav.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(types.InlineKeyboardButton("??", callback_data=f"adm:bulk:tgt:{op}:pick:{page+1}"))
        if nav:
            kb.row(*nav)
        kb.add(types.InlineKeyboardButton(
            f"?  «ÌÌœ Ê «Ã—« ({len(selected)} ‰›— «‰ Œ«» ‘œÂ)",
            callback_data=f"adm:bulk:confirm:{op}:pick"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:bulk:op:{op}",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"?? <b>«‰ Œ«» ò«—»—«‰</b> ó ’›ÕÂ {page+1}/{total_pages}\n"
            f"? {len(selected)} ‰›— «‰ Œ«» ‘œÂ:",
            kb)
        return

    if data.startswith("adm:bulk:confirm:"):
        # Confirm after manual pick ó ask for amount if needed
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts    = data.split(":")
        op       = parts[3]
        sd       = state_data(uid) if state_name(uid) == "bulk_pick" else {}
        selected = sd.get("selected", [])
        if not selected:
            bot.answer_callback_query(call.id, "ÂÌç ò«—»—Ì «‰ Œ«» ‰‘œÂ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        if op in ("add_balance", "sub_balance"):
            state_set(uid, "bulk_amount", op=op, filter_type="pick", selected=selected)
            _OP_L = {"add_balance": "«›“Êœ‰", "sub_balance": "ò«Â‘"}
            send_or_edit(call,
                f"? <b>⁄„·Ì«  ê—ÊÂÌ</b>: {_OP_L[op]} „ÊÃÊœÌ\n"
                f"?? {len(selected)} ò«—»— «‰ Œ«» ‘œÂ\n\n"
                "?? <b>„»·€</b> ( Ê„«‰) —« Ê«—œ ò‰Ìœ:",
                back_button(f"adm:bulk:op:{op}"))
        else:
            count = len(selected)
            _OP_L2 = {
                "zero_balance": "’›— ò—œ‰ „ÊÃÊœÌ",
                "set_safe": "«„‰ ò—œ‰",
                "set_unsafe": "‰««„‰ ò—œ‰",
                "set_restricted": "„ÕœÊœ ò—œ‰",
            }
            sel_str = ",".join(str(x) for x in selected[:50])
            kb2 = types.InlineKeyboardMarkup()
            kb2.add(types.InlineKeyboardButton(
                f"?  «ÌÌœ ó «Ã—« —ÊÌ {count} ò«—»—",
                callback_data=f"adm:bulk:exec:{op}:pick:{sel_str}"))
            kb2.add(types.InlineKeyboardButton("·€Ê", callback_data="adm:usr:bulk",
                                               icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                f"? <b> «ÌÌœ ⁄„·Ì«  ê—ÊÂÌ</b>\n\n"
                f"⁄„·Ì« : <b>{_OP_L2.get(op, op)}</b>\n"
                f" ⁄œ«œ ò«—»—«‰ «‰ Œ«» ‘œÂ: <b>{count}</b>",
                kb2)
        return

    if data.startswith("adm:bulk:exec:"):
        # Execute bulk operation
        # format: adm:bulk:exec:{op}:{filter_type}:{amount_or_sel}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "full_users")):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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

        bot.answer_callback_query(call.id, "? œ— Õ«· «Ã—«Ö")
        state_clear(uid)

        count = 0
        try:
            if op == "add_balance":
                count = bulk_add_balance(filter_type, user_ids, amount)
                result_msg = f"? „ÊÃÊœÌ {amount:,}  Ê„«‰ »Â {count} ò«—»— «÷«›Â ‘œ."
            elif op == "sub_balance":
                count = bulk_add_balance(filter_type, user_ids, -amount)
                result_msg = f"? „ÊÃÊœÌ {amount:,}  Ê„«‰ «“ {count} ò«—»— ò„ ‘œ."
            elif op == "zero_balance":
                count = bulk_zero_balance(filter_type, user_ids)
                result_msg = f"? „ÊÃÊœÌ {count} ò«—»— ’›— ‘œ."
            elif op == "set_safe":
                count = bulk_set_status(filter_type, user_ids, "safe")
                result_msg = f"? {count} ò«—»— «„‰ ‘œ‰œ."
            elif op == "set_unsafe":
                count = bulk_set_status(filter_type, user_ids, "unsafe")
                result_msg = f"? {count} ò«—»— ‰««„‰ ‘œ‰œ."
            elif op == "set_restricted":
                count = bulk_set_status(filter_type, user_ids, "restricted")
                result_msg = f"? {count} ò«—»— „ÕœÊœ ‘œ‰œ."
            else:
                result_msg = "? ⁄„·Ì«  ‰«‘‰«Œ Â."
        except Exception as _e:
            result_msg = f"? Œÿ«: {esc(str(_e)[:200])}"

        log_admin_action(uid, f"⁄„·Ì«  ê—ÊÂÌ: {op} | filter={filter_type} | count={count}")
        kb_back = types.InlineKeyboardMarkup()
        kb_back.add(types.InlineKeyboardButton("»«“ê‘  »Â ò«—»—«‰", callback_data="admin:users",
                                               icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, result_msg, kb_back)
        return

    # ?? Admin: Admins management ??????????????????????????????????????????????
    if data == "admin:admins":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "›ﬁÿ «Ê‰— „Ìù Ê«‰œ «œ„Ì‰ùÂ« —« „œÌ—Ì  ò‰œ.", show_alert=True)
            return
        _show_admin_admins_panel(call)
        bot.answer_callback_query(call.id)
        return

    if data == "adm:mgr:add":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_mgr_await_id")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "? <b>«›“Êœ‰ «œ„Ì‰ ÃœÌœ</b>\n\n"
            "¬ÌœÌ ⁄œœÌ Ì« ÌÊ“—‰Ì„ ò«—»— „Ê—œ ‰Ÿ— —« «—”«· ò‰Ìœ:\n\n"
            "„À«·: <code>123456789</code> Ì« <code>@username</code>",
            back_button("admin:admins"))
        return

    if data.startswith("adm:mgr:del:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        if target_id in ADMIN_IDS:
            bot.answer_callback_query(call.id, "«Ê‰—Â« —« ‰„Ìù Ê«‰ Õ–› ò—œ.", show_alert=True)
            return
        remove_admin_user(target_id)
        bot.answer_callback_query(call.id, "? «œ„Ì‰ Õ–› ‘œ.")
        log_admin_action(uid, f"«œ„Ì‰ <code>{target_id}</code> Õ–› ‘œ")
        _show_admin_admins_panel(call)
        return

    if data.startswith("adm:mgr:v:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        row = get_admin_user(target_id)
        user_row = get_user(target_id)
        if not row:
            bot.answer_callback_query(call.id, "«œ„Ì‰ Ì«›  ‰‘œ.", show_alert=True)
            return
        perms = json.loads(row["permissions"] or "{}")
        from ..ui.premium_emoji import ce as _ce
        def _perm_line(k, lbl):
            check = '?' if perms.get(k) or perms.get('full') else '?'
            eid = PERM_EMOJI_IDS.get(k)
            emoji_tag = _ce('?', eid) + ' ' if eid else ''
            return f"{check} {emoji_tag}{lbl}"
        perm_lines = "\n".join(
            _perm_line(k, lbl)
            for k, lbl in ADMIN_PERMS if k != "full"
        )
        name = user_row["full_name"] if user_row else f"ò«—»— {target_id}"
        text = (
            f"?? <b>«ÿ·«⁄«  «œ„Ì‰</b>\n\n"
            f"?? ‰«„: {esc(name)}\n"
            f"?? ¬ÌœÌ: <code>{target_id}</code>\n"
            f"?? «›“ÊœÂ ‘œÂ: {esc(row['added_at'])}\n\n"
            f"?? <b>œ” —”ÌùÂ«:</b>\n{perm_lines}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Õ–› «œ„Ì‰", callback_data=f"adm:mgr:del:{target_id}"))
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ œ” —”ÌùÂ«", callback_data=f"adm:mgr:edit:{target_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:admins", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:mgr:edit:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        row = get_admin_user(target_id)
        if not row:
            bot.answer_callback_query(call.id, "«œ„Ì‰ Ì«›  ‰‘œ.", show_alert=True)
            return
        perms = json.loads(row["permissions"] or "{}")
        state_set(uid, "admin_mgr_select_perms", target_user_id=target_id, perms=json.dumps(perms), edit_mode=True)
        bot.answer_callback_query(call.id)
        _show_perm_selection(call, uid, target_id, perms, edit_mode=True)
        return

    if data.startswith("adm:mgr:pt:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        perm_key = data[len("adm:mgr:pt:"):]
        sd2 = state_data(uid)
        if state_name(uid) != "admin_mgr_select_perms" or not sd2:
            bot.answer_callback_query(call.id, "Ã·”Â „‰ﬁ÷Ì ‘œÂ «” .", show_alert=True)
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        sd2 = state_data(uid)
        if state_name(uid) != "admin_mgr_select_perms" or not sd2:
            bot.answer_callback_query(call.id, "Ã·”Â „‰ﬁ÷Ì ‘œÂ «” .", show_alert=True)
            return
        target_id = sd2.get("target_user_id")
        perms = json.loads(sd2.get("perms", "{}"))
        if not any(perms.values()):
            bot.answer_callback_query(call.id, "Õœ«ﬁ· Ìò ”ÿÕ œ” —”Ì «‰ Œ«» ò‰Ìœ.", show_alert=True)
            return
        edit_mode = sd2.get("edit_mode", False)
        # Build human-readable permission list for notification
        perms_labels = {k: v for k, v in ADMIN_PERMS}
        active_perm_names = [perms_labels.get(k, k) for k, v in perms.items() if v]
        perm_text = "\n".join(f"ï {p}" for p in active_perm_names) or "ó »œÊ‰ œ” —”Ì ó"
        if edit_mode:
            update_admin_permissions(target_id, perms)
            log_admin_action(uid, f"œ” —”ÌùÂ«Ì «œ„Ì‰ {target_id} »Âù—Ê“—”«‰Ì ‘œ")
            state_clear(uid)
            bot.answer_callback_query(call.id, "? œ” —”ÌùÂ« »Âù—Ê“ ‘œ.")
            try:
                bot.send_message(target_id,
                    "?? <b>œ” —”ÌùÂ«Ì ‘„« »Âù—Ê“—”«‰Ì ‘œ</b>\n\n"
                    f"<b>œ” —”ÌùÂ«Ì ›⁄«·:</b>\n{perm_text}\n\n"
                    "»—«Ì «” ›«œÂ «“ œ” —”ÌùÂ«Ì ÃœÌœ «“ /start «” ›«œÂ ò‰Ìœ.")
            except Exception:
                pass
        else:
            add_admin_user(target_id, uid, perms)
            log_admin_action(uid, f"«œ„Ì‰ ÃœÌœ {target_id} «÷«›Â ‘œ")
            state_clear(uid)
            bot.answer_callback_query(call.id, "? «œ„Ì‰ «÷«›Â ‘œ.")
            try:
                bot.send_message(target_id,
                    "?? <b>‘„« »Â ⁄‰Ê«‰ «œ„Ì‰ «÷«›Â ‘œÌœ!</b>\n\n"
                    f"<b>œ” —”ÌùÂ«Ì ‘„«:</b>\n{perm_text}\n\n"
                    "»—«Ì œ” —”Ì »Â Å‰· „œÌ—Ì  «“ œ” Ê— /start «” ›«œÂ ò‰Ìœ.")
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

        if sub == "sts":  # cycle status: safe ? unsafe ? restricted ? safe
            user = get_user(target_id)
            current = user["status"] if user else "safe"
            if current == "safe":
                new_status = "unsafe"
                label = "‰««„‰"
            elif current == "unsafe":
                new_status = "restricted"
                label = "„ÕœÊœ"
            else:
                new_status = "safe"
                label = "«„‰"
            set_user_status(target_id, new_status)
            bot.answer_callback_query(call.id, f"Ê÷⁄Ì  ò«—»— »Â {label}  €ÌÌ— ò—œ.")
            log_admin_action(uid, f"Ê÷⁄Ì  ò«—»— <code>{target_id}</code> »Â {label}  €ÌÌ— ò—œ")
            _show_admin_user_detail(call, target_id)
            return

        if sub == "ag":  # toggle agent
            user     = get_user(target_id)
            new_flag = 0 if user["is_agent"] else 1
            set_user_agent(target_id, new_flag)
            label = "›⁄«·" if new_flag else "€Ì—›⁄«·"
            bot.answer_callback_query(call.id, f"‰„«Ì‰œêÌ {label} ‘œ.")
            log_admin_action(uid, f"‰„«Ì‰œêÌ ò«—»— <code>{target_id}</code> {label} ‘œ")
            _show_admin_user_detail(call, target_id)
            return

        if sub == "bal":  # balance menu
            user = get_user(target_id)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("? «›“«Ì‘", callback_data=f"adm:usr:bal+:{target_id}"),
                types.InlineKeyboardButton("? ò«Â‘",  callback_data=f"adm:usr:bal-:{target_id}"),
            )
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>„ÊÃÊœÌ ò«—»—</b>\n\n"
                f"?? „ÊÃÊœÌ ›⁄·Ì: <b>{fmt_price(user['balance'])}</b>  Ê„«‰",
                kb)
            return

        if sub == "bal+":  # add balance
            state_set(uid, "admin_bal_add", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"?? „»·€Ì òÂ „ÌùŒÊ«ÂÌœ <b>«÷«›Â</b> ‘Êœ —« »Â  Ê„«‰ Ê«—œ ò‰Ìœ:",
                         back_button(f"adm:usr:v:{target_id}"))
            return

        if sub == "bal-":  # reduce balance
            state_set(uid, "admin_bal_sub", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"?? „»·€Ì òÂ „ÌùŒÊ«ÂÌœ <b>ò«Â‘</b> Ì«»œ —« »Â  Ê„«‰ Ê«—œ ò‰Ìœ:",
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
            send_or_edit(call, "?? ⁄»«—  Ã” ùÊÃÊ —« «—”«· ò‰Ìœ:", back_button(f"adm:usr:cfgs:{target_id}"))
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
                    f"?? {name}{username}",
                    callback_data=f"adm:usr:v:{r['referee_id']}"
                ))
            if total_pages > 1:
                nav_row = []
                if page > 0:
                    nav_row.append(types.InlineKeyboardButton(
                        "?? ﬁ»·Ì", callback_data=f"adm:usr:refs:{target_id}:{page - 1}"
                    ))
                nav_row.append(types.InlineKeyboardButton(
                    f"{page + 1}/{total_pages}", callback_data="noop"
                ))
                if page < total_pages - 1:
                    nav_row.append(types.InlineKeyboardButton(
                        "»⁄œÌ ??", callback_data=f"adm:usr:refs:{target_id}:{page + 1}"
                    ))
                kb.row(*nav_row)
            kb.add(types.InlineKeyboardButton(
                "»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}",
                icon_custom_emoji_id="5253997076169115797"
            ))
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"?? <b>“Ì—„Ã„Ê⁄ÂùÂ«</b>\n\n ⁄œ«œ ò·: <b>{total}</b>", kb)
            return

        if sub == "acfg":  # assign config to user
            _show_admin_assign_config_type(call, target_id)
            bot.answer_callback_query(call.id)
            return

        if sub == "dm":  # send direct message to user
            if not is_admin(uid):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            state_set(uid, "admin_dm_user", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("?? ·€Ê", callback_data=f"adm:usr:v:{target_id}"))
            send_or_edit(call,
                f"?? <b>ÅÌ«„ Œ’Ê’Ì »Â ò«—»—</b>\n\n"
                f"‘‰«”Â ò«—»—: <code>{target_id}</code>\n\n"
                "ÅÌ«„ „Ê—œ ‰Ÿ— —« «—”«· ò‰Ìœ.\n"
                "„Ìù Ê«‰Ìœ „ ‰° ⁄ò”° ÊÌœÌÊ° ›«Ì· Ì« Â— „Õ Ê«Ì œÌê—Ì »›—” Ìœ.",
                kb)
            return

        if sub == "agp":  # agency prices list
            packs = get_packages()
            if not packs:
                bot.answer_callback_query(call.id, "ÅòÌÃÌ „ÊÃÊœ ‰Ì” .", show_alert=True)
                return
            kb = types.InlineKeyboardMarkup()
            for p in packs:
                ap    = get_agency_price(target_id, p["id"])
                price = fmt_price(ap) if ap is not None else fmt_price(p["price"])
                label = f"{p['name']} | {price}  "
                kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:usr:agpe:{target_id}:{p['id']}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "?? <b>ﬁÌ„ ùÂ«Ì «Œ ’«’Ì ‰„«Ì‰œêÌ</b>\n\n»—«Ì ÊÌ—«Ì‘ —ÊÌ ÅòÌÃ »“‰Ìœ:", kb)
            return

    if data.startswith("adm:usr:agpe:"):
        parts      = data.split(":")
        target_id  = int(parts[3])
        package_id = int(parts[4])
        state_set(uid, "admin_set_agency_price", target_user_id=target_id, package_id=package_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ﬁÌ„  «Œ ’«’Ì ( Ê„«‰) —« Ê«—œ ò‰Ìœ.\n»—«Ì »«“ê‘  »Â ﬁÌ„  ⁄«œÌ° ⁄œœ <b>0</b> »›—” Ìœ:",
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
        bot.answer_callback_query(call.id, "ò«‰›Ìê «“ ò«—»— Õ–› ‘œ (›—ÊŒ Â ‘œÂ).")
        send_or_edit(call, "? ò«‰›Ìê «“ ò«—»— Õ–› ‘œ Ê œ— Ê÷⁄Ì  ›—ÊŒ Â ‘œÂ »«ﬁÌ „«‰œ.", back_button(f"adm:usr:v:{target_id}"))
        return

    if data.startswith("adm:usrcfg:unassign_exp:"):
        parts     = data.split(":")
        target_id = int(parts[3])
        config_id = int(parts[4])
        with get_conn() as conn:
            conn.execute("DELETE FROM purchases WHERE config_id=? AND user_id=?", (config_id, target_id))
            conn.execute("UPDATE configs SET sold_to=NULL, purchase_id=NULL, sold_at=NULL, reserved_payment_id=NULL, is_expired=1 WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "ò«‰›Ìê «“ ò«—»— Õ–› ‘œ („‰ﬁ÷Ì).")
        send_or_edit(call, "? ò«‰›Ìê «“ ò«—»— Õ–› ‘œ Ê œ— Ê÷⁄Ì  „‰ﬁ÷Ì ﬁ—«— ê—› .", back_button(f"adm:usr:v:{target_id}"))
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
        bot.answer_callback_query(call.id, "ò«‰›Ìê «“ ò«—»— Õ–› ‘œ.")
        send_or_edit(call, "? ò«‰›Ìê «“ ò«—»— Õ–› Ê »Â „«‰œÂùÂ« »—ê‘ .", back_button(f"adm:usr:v:{target_id}"))
        return

    if data.startswith("adm:usrcfg:"):
        parts     = data.split(":")
        target_id = int(parts[2])
        config_id = int(parts[3])
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM configs WHERE id=?", (config_id,)).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "Ì«›  ‰‘œ.", show_alert=True)
            return
        text = (
            f"?? ‰«„ ”—ÊÌ”: <b>{esc(urllib.parse.unquote(row['service_name'] or ''))}</b>\n\n"
            f"?? Config:\n<code>{esc(row['config_text'])}</code>\n\n"
            f"?? Volume web: {esc(row['inquiry_link'] or '-')}\n"
            f"?? À» : {esc(row['created_at'])}\n"
            f"?? ›—Ê‘: {esc(row['sold_at'] or '-')}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Õ–› «“ ò«—»— (»—ê‘  »Â „«‰œÂùÂ«)", callback_data=f"adm:usrcfg:unassign:{target_id}:{config_id}"))
        kb.add(types.InlineKeyboardButton("?? Õ–› «“ ò«—»— (»—ê‘  »Â ›—ÊŒ Â ‘œÂùÂ«)", callback_data=f"adm:usrcfg:unassign_sold:{target_id}:{config_id}"))
        kb.add(types.InlineKeyboardButton("?? Õ–› «“ ò«—»— (»—ê‘  »Â „‰ﬁ÷ÌùÂ«)", callback_data=f"adm:usrcfg:unassign_exp:{target_id}:{config_id}"))
        if not row["is_expired"]:
            kb.add(types.InlineKeyboardButton("?? „‰ﬁ÷Ì ò—œ‰", callback_data=f"adm:stk:exp:{config_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:usr:cfgs:{target_id}", icon_custom_emoji_id="5253997076169115797"))
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
                    f"{p['name']} | „ÊÃÊœ: {avail}",
                    callback_data=f"adm:acfg:p:{target_id}:{p['id']}"
                ))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ÅòÌÃ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
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
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ò«‰›Ìê „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("adm:acfg:do:"):  # do assign config
        parts      = data.split(":")
        target_id  = int(parts[3])
        config_id  = int(parts[4])
        with get_conn() as conn:
            cfg_row = conn.execute("SELECT * FROM configs WHERE id=?", (config_id,)).fetchone()
        if not cfg_row:
            bot.answer_callback_query(call.id, "ò«‰›Ìê Ì«›  ‰‘œ.", show_alert=True)
            return
        purchase_id = assign_config_to_user(config_id, target_id, cfg_row["package_id"], 0, "admin_gift", is_test=0)
        bot.answer_callback_query(call.id, "ò«‰›Ìê „‰ ﬁ· ‘œ!")
        send_or_edit(call, "? ò«‰›Ìê »« „Ê›ﬁÌ  »Â ò«—»— «Œ ’«’ Ì«› .", back_button("admin:users"))
        try:
            deliver_purchase_message(target_id, purchase_id)
        except Exception:
            pass
        return

    # ?? Admin: Agents management ??????????????????????????????????????????????
    if data == "admin:agents":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        agents    = get_agencies()
        req_flag  = setting_get("agency_request_enabled", "1")
        req_icon  = "??" if req_flag == "1" else "??"
        req_label = "—Ê‘‰" if req_flag == "1" else "Œ«„Ê‘"
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} œ—ŒÊ«”  ‰„«Ì‰œêÌ ó {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("?? œ—ŒÊ«” ùÂ«Ì »——”Ì ‰‘œÂ", callback_data="adm:resreq:list:0"))
        kb.add(types.InlineKeyboardButton("?? Õœ«ﬁ· „ÊÃÊœÌ œ—ŒÊ«” ", callback_data="adm:resreq:minwallet"))
        kb.add(types.InlineKeyboardButton("? «÷«›Â ò—œ‰ ‰„«Ì‰œÂ", callback_data="adm:agt:add"))
        # Inline list: each agent on one row with remove button
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"?? {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "?? Õ–›",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"?? <b>„œÌ—Ì  ‰„«Ì‰œê«‰</b>\n\n"
            f"??  ⁄œ«œ ‰„«Ì‰œê«‰ ›⁄·Ì: <b>{len(agents)}</b>\n"
            f"?? Ê÷⁄Ì  œ—ŒÊ«” : <b>{req_label}</b>",
            kb)
        return

    if data == "adm:agt:add":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_agent_add_search")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>Ã” ÃÊÌ ò«—»— »—«Ì «›“Êœ‰ »Â ‰„«Ì‰œêÌ</b>\n\n"
            "¬ÌœÌ ⁄œœÌ Ì« ÌÊ“—‰Ì„ ò«—»— —« «—”«· ò‰Ìœ:",
            back_button("admin:agents"))
        return

    if data.startswith("adm:agt:u:"):
        target_uid = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _show_admin_user_detail(call, target_uid)
        return

    if data.startswith("adm:agt:rm:"):
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        target_uid = int(data.split(":")[3])
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_agent=0 WHERE user_id=?", (target_uid,))
        bot.answer_callback_query(call.id, "? ò«—»— «“ ‰„«Ì‰œêÌ Õ–› ‘œ.")
        # re-render agents menu
        agents    = get_agencies()
        req_flag  = setting_get("agency_request_enabled", "1")
        req_icon  = "??" if req_flag == "1" else "??"
        req_label = "—Ê‘‰" if req_flag == "1" else "Œ«„Ê‘"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} œ—ŒÊ«”  ‰„«Ì‰œêÌ ó {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("?? œ—ŒÊ«” ùÂ«Ì »——”Ì ‰‘œÂ", callback_data="adm:resreq:list:0"))
        kb.add(types.InlineKeyboardButton("?? Õœ«ﬁ· „ÊÃÊœÌ œ—ŒÊ«” ", callback_data="adm:resreq:minwallet"))
        kb.add(types.InlineKeyboardButton("? «÷«›Â ò—œ‰ ‰„«Ì‰œÂ", callback_data="adm:agt:add"))
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"?? {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "?? Õ–›",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"?? <b>„œÌ—Ì  ‰„«Ì‰œê«‰</b>\n\n"
            f"??  ⁄œ«œ ‰„«Ì‰œê«‰ ›⁄·Ì: <b>{len(agents)}</b>\n"
            f"?? Ê÷⁄Ì  œ—ŒÊ«” : <b>{req_label}</b>",
            kb)
        return

    if data == "adm:agt:toggle":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur      = setting_get("agency_request_enabled", "1")
        new      = "0" if cur == "1" else "1"
        setting_set("agency_request_enabled", new)
        log_admin_action(uid, f"œ—ŒÊ«”  ‰„«Ì‰œêÌ {'›⁄«·' if new == '1' else '€Ì—›⁄«·'} ‘œ")
        req_icon  = "??" if new == "1" else "??"
        req_label = "—Ê‘‰" if new == "1" else "Œ«„Ê‘"
        bot.answer_callback_query(call.id, f"œ—ŒÊ«”  ‰„«Ì‰œêÌ: {req_label}")
        agents = get_agencies()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} œ—ŒÊ«”  ‰„«Ì‰œêÌ ó {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("?? œ—ŒÊ«” ùÂ«Ì »——”Ì ‰‘œÂ", callback_data="adm:resreq:list:0"))
        kb.add(types.InlineKeyboardButton("?? Õœ«ﬁ· „ÊÃÊœÌ œ—ŒÊ«” ", callback_data="adm:resreq:minwallet"))
        kb.add(types.InlineKeyboardButton("? «÷«›Â ò—œ‰ ‰„«Ì‰œÂ", callback_data="adm:agt:add"))
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"?? {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "?? Õ–›",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"?? <b>„œÌ—Ì  ‰„«Ì‰œê«‰</b>\n\n"
            f"??  ⁄œ«œ ‰„«Ì‰œê«‰ ›⁄·Ì: <b>{len(agents)}</b>\n"
            f"?? Ê÷⁄Ì  œ—ŒÊ«” : <b>{req_label}</b>",
            kb)
        return

    # ?? Admin: Purchase Credit ????????????????????????????????????????????????
    if data.startswith("adm:credit:") and data.split(":")[2].isdigit():
        parts     = data.split(":")
        target_id = int(parts[2])
        if not admin_has_perm(uid, "full_users") and not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        user = get_user(target_id)
        if not user:
            bot.answer_callback_query(call.id, "ò«—»— Ì«›  ‰‘œ.", show_alert=True)
            return
        credit_enabled = user["purchase_credit_enabled"] if "purchase_credit_enabled" in user.keys() else 0
        credit_limit   = user["purchase_credit_limit"]   if "purchase_credit_limit"   in user.keys() else 0
        kb = types.InlineKeyboardMarkup()
        toggle_label = "? €Ì—›⁄«· ò—œ‰" if credit_enabled else "? ›⁄«· ò—œ‰"
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data=f"adm:credit:tog:{target_id}"))
        kb.add(types.InlineKeyboardButton("??  €ÌÌ— ”ﬁ› «⁄ »«—", callback_data=f"adm:credit:setlimit:{target_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>«⁄ »«— Œ—Ìœ</b>\n\n"
            f"ò«—»—: {esc(user['full_name'])} (<code>{target_id}</code>)\n"
            f"Ê÷⁄Ì : {'? ›⁄«·' if credit_enabled else '? €Ì—›⁄«·'}\n"
            f"”ﬁ› «⁄ »«—: <b>{fmt_price(credit_limit)}  Ê„«‰</b>",
            kb)
        return

    if data.startswith("adm:credit:tog:"):
        target_id = int(data.split(":")[3])
        user = get_user(target_id)
        if not user:
            bot.answer_callback_query(call.id, "ò«—»— Ì«›  ‰‘œ.", show_alert=True)
            return
        credit_enabled = user["purchase_credit_enabled"] if "purchase_credit_enabled" in user.keys() else 0
        credit_limit   = user["purchase_credit_limit"]   if "purchase_credit_limit"   in user.keys() else 0
        new_enabled    = 0 if credit_enabled else 1
        set_user_purchase_credit(target_id, new_enabled, credit_limit)
        bot.answer_callback_query(call.id, "? Ê÷⁄Ì  «⁄ »«—  €ÌÌ— Ì«› .")
        log_admin_action(uid, f"«⁄ »«— Œ—Ìœ ò«—»— {target_id}: {'›⁄«·' if new_enabled else '€Ì—›⁄«·'}")
        # Re-render
        user2 = get_user(target_id)
        credit_enabled2 = user2["purchase_credit_enabled"] if user2 and "purchase_credit_enabled" in user2.keys() else 0
        credit_limit2   = user2["purchase_credit_limit"]   if user2 and "purchase_credit_limit"   in user2.keys() else 0
        kb = types.InlineKeyboardMarkup()
        toggle_label2 = "? €Ì—›⁄«· ò—œ‰" if credit_enabled2 else "? ›⁄«· ò—œ‰"
        kb.add(types.InlineKeyboardButton(toggle_label2, callback_data=f"adm:credit:tog:{target_id}"))
        kb.add(types.InlineKeyboardButton("??  €ÌÌ— ”ﬁ› «⁄ »«—", callback_data=f"adm:credit:setlimit:{target_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"?? <b>«⁄ »«— Œ—Ìœ</b>\n\n"
            f"ò«—»—: {esc(user2['full_name'])} (<code>{target_id}</code>)\n"
            f"Ê÷⁄Ì : {'? ›⁄«·' if credit_enabled2 else '? €Ì—›⁄«·'}\n"
            f"”ﬁ› «⁄ »«—: <b>{fmt_price(credit_limit2)}  Ê„«‰</b>",
            kb)
        return

    if data.startswith("adm:credit:setlimit:"):
        target_id = int(data.split(":")[3])
        state_set(uid, "admin_set_credit_limit", target_user_id=target_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b> €ÌÌ— ”ﬁ› «⁄ »«—</b>\n\n”ﬁ› «⁄ »«— ÃœÌœ —« »Â  Ê„«‰ Ê«—œ ò‰Ìœ („À«·: 500000):",
            back_button(f"adm:credit:{target_id}"))
        return

    # ?? Admin: Reseller Requests ??????????????????????????????????????????????
    if data.startswith("adm:resreq:list:"):
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        page = int(data.split(":")[3])
        per_page = 5
        rows, total = get_pending_reseller_requests(page=page, per_page=per_page)
        bot.answer_callback_query(call.id)
        if not rows:
            send_or_edit(call,
                "?? <b>œ—ŒÊ«” ùÂ«Ì »——”Ì ‰‘œÂ</b>\n\nÂÌç œ—ŒÊ«”  »——”Ì ‰‘œÂù«Ì ÊÃÊœ ‰œ«—œ.",
                back_button("admin:agents"))
            return
        text = f"?? <b>œ—ŒÊ«” ùÂ«Ì »——”Ì ‰‘œÂ</b> ({total} ⁄œœ)\n\n"
        kb = types.InlineKeyboardMarkup()
        for r in rows:
            uname = r["username"] or "ó"
            if uname != "ó" and not uname.startswith("@"):
                uname = f"@{uname}"
            btn_label = f"?? {r['full_name'] or r['user_id']} | {uname}"
            kb.add(types.InlineKeyboardButton(btn_label, callback_data=f"adm:resreq:view:{r['id']}"))
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton("?? ﬁ»·Ì", callback_data=f"adm:resreq:list:{page-1}"))
        if (page + 1) * per_page < total:
            nav_row.append(types.InlineKeyboardButton("?? »⁄œÌ", callback_data=f"adm:resreq:list:{page+1}"))
        if nav_row:
            kb.row(*nav_row)
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:agents", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:resreq:view:"):
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        req_id = int(data.split(":")[3])
        req = get_reseller_request_by_id(req_id)
        if not req:
            bot.answer_callback_query(call.id, "œ—ŒÊ«”  Ì«›  ‰‘œ.", show_alert=True)
            return
        uname = req["username"] or "ó"
        if uname != "ó" and not uname.startswith("@"):
            uname = f"@{uname}"
        desc = esc(req["description"] or "»œÊ‰ „ ‰")
        text = (
            f"?? <b>œ—ŒÊ«”  ‰„«Ì‰œêÌ</b> #{req_id}\n\n"
            f"?? ‰«„: {esc(req['full_name'] or 'ó')}\n"
            f"?? ‰«„ ò«—»—Ì: {uname}\n"
            f"?? ¬ÌœÌ: <code>{req['user_id']}</code>\n"
            f"??  «—ÌŒ: {req['created_at']}\n\n"
            f"?? „ ‰ œ—ŒÊ«” :\n{desc}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("?  √ÌÌœ", callback_data=f"adm:resreq:approve:{req_id}"),
            types.InlineKeyboardButton("? —œ", callback_data=f"adm:resreq:reject:{req_id}"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:resreq:list:0", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:resreq:approve:"):
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        req_id = int(data.split(":")[3])
        req = get_reseller_request_by_id(req_id)
        if not req:
            bot.answer_callback_query(call.id, "œ—ŒÊ«”  Ì«›  ‰‘œ.", show_alert=True)
            return
        target_uid = req["user_id"]
        approve_reseller_request(req_id, uid)
        set_user_agent(target_uid, 1)
        # Remove buttons from tracked messages
        for row in get_agency_request_messages(target_uid):
            try:
                bot.edit_message_reply_markup(row["chat_id"], row["message_id"], reply_markup=None)
            except Exception:
                pass
        delete_agency_request_messages(target_uid)
        bot.answer_callback_query(call.id, "? ‰„«Ì‰œêÌ  √ÌÌœ ‘œ.")
        try:
            bot.send_message(target_uid,
                "?? <b>œ—ŒÊ«”  ‰„«Ì‰œêÌ ‘„«  √ÌÌœ ‘œ!</b>\n\n«ò‰Ê‰ ‘„« ‰„«Ì‰œÂ Â” Ìœ.",
                parse_mode="HTML")
        except Exception:
            pass
        user_row = get_user(target_uid)
        send_to_topic("agency_log",
            f"? <b>‰„«Ì‰œêÌ  √ÌÌœ ‘œ</b>\n\n"
            f"?? ‰«„: {esc(user_row['full_name'] if user_row else str(target_uid))}\n"
            f"?? ¬ÌœÌ: <code>{target_uid}</code>\n"
            f" √ÌÌœò‰‰œÂ: <code>{uid}</code>"
        )
        log_admin_action(uid, f"œ—ŒÊ«”  ‰„«Ì‰œêÌ #{req_id} (ò«—»— {target_uid})  √ÌÌœ ‘œ")
        send_or_edit(call, f"? ‰„«Ì‰œêÌ ò«—»— <code>{target_uid}</code>  √ÌÌœ ‘œ.", back_button("adm:resreq:list:0"))
        return

    if data.startswith("adm:resreq:reject:"):
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        req_id = int(data.split(":")[3])
        req = get_reseller_request_by_id(req_id)
        if not req:
            bot.answer_callback_query(call.id, "œ—ŒÊ«”  Ì«›  ‰‘œ.", show_alert=True)
            return
        target_uid = req["user_id"]
        state_set(uid, "admin_resreq_reject_reason", req_id=req_id, target_uid=target_uid)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? »œÊ‰ œ·Ì·", callback_data=f"adm:resreq:reject_now:{req_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:resreq:view:{req_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"? <b>—œ œ—ŒÊ«”  #{req_id}</b>\n\nœ·Ì· —œ —« »‰ÊÌ”Ìœ (Ì« œò„Â “Ì— —« »“‰Ìœ):",
            kb)
        return

    if data.startswith("adm:resreq:reject_now:"):
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        req_id = int(data.split(":")[3])
        req = get_reseller_request_by_id(req_id)
        if not req:
            bot.answer_callback_query(call.id, "œ—ŒÊ«”  Ì«›  ‰‘œ.", show_alert=True)
            return
        target_uid = req["user_id"]
        state_clear(uid)
        reject_reseller_request(req_id, uid)
        # Remove buttons from tracked messages
        for row in get_agency_request_messages(target_uid):
            try:
                bot.edit_message_reply_markup(row["chat_id"], row["message_id"], reply_markup=None)
            except Exception:
                pass
        delete_agency_request_messages(target_uid)
        bot.answer_callback_query(call.id, "? —œ ‘œ.")
        try:
            bot.send_message(target_uid,
                "? <b>œ—ŒÊ«”  ‰„«Ì‰œêÌ ‘„« —œ ‘œ.</b>",
                parse_mode="HTML")
        except Exception:
            pass
        user_row = get_user(target_uid)
        send_to_topic("agency_log",
            f"? <b>‰„«Ì‰œêÌ —œ ‘œ</b>\n\n"
            f"?? ‰«„: {esc(user_row['full_name'] if user_row else str(target_uid))}\n"
            f"?? ¬ÌœÌ: <code>{target_uid}</code>\n"
            f"—œò‰‰œÂ: <code>{uid}</code>"
        )
        log_admin_action(uid, f"œ—ŒÊ«”  ‰„«Ì‰œêÌ #{req_id} (ò«—»— {target_uid}) —œ ‘œ")
        send_or_edit(call, f"? œ—ŒÊ«”  #{req_id} —œ ‘œ.", back_button("adm:resreq:list:0"))
        return

    if data == "adm:resreq:minwallet":
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur_val = setting_get("agency_request_min_wallet", "0")
        state_set(uid, "admin_set_resreq_min_wallet")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>Õœ«ﬁ· „ÊÃÊœÌ »—«Ì œ—ŒÊ«”  ‰„«Ì‰œêÌ</b>\n\n"
            f"„ﬁœ«— ›⁄·Ì: <b>{fmt_price(int(cur_val or 0))}  Ê„«‰</b>\n\n"
            "„ﬁœ«— ÃœÌœ —« »Â  Ê„«‰ Ê«—œ ò‰Ìœ (0 = »œÊ‰ „ÕœÊœÌ ):",
            back_button("admin:agents"))
        return

    # ?? Agency price config (3-mode) ??????????????????????????????????????????
    if data.startswith("adm:agcfg:") and data.count(":") == 2:
        # adm:agcfg:{target_id}  ó show mode selector
        parts     = data.split(":")
        target_id = int(parts[2])
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cfg  = get_agency_price_config(target_id)
        mode = cfg["price_mode"]
        tick = {m: "? " for m in ["global", "type", "package", "per_gb"]}
        for k in tick:
            tick[k] = "? " if mode == k else ""
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{tick['global']}??  Œ›Ì› —ÊÌ ò· „Õ’Ê·« ",
            callback_data=f"adm:agcfg:global:{target_id}"))
        kb.add(types.InlineKeyboardButton(
            f"{tick['type']}??  Œ›Ì› —ÊÌ Â— œ” Â",
            callback_data=f"adm:agcfg:type:{target_id}"))
        kb.add(types.InlineKeyboardButton(
            f"{tick['package']}?? ﬁÌ„  Ãœ«ê«‰Â Â— ÅòÌÃ",
            callback_data=f"adm:agcfg:pkg:{target_id}"))
        kb.add(types.InlineKeyboardButton(
            f"{tick['per_gb']}?? ﬁÌ„  »Â «“«Ì Â— êÌê",
            callback_data=f"adm:agcfg:pergb:{target_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:usr:v:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        target_user = get_user(target_id)
        uname = esc(target_user["full_name"]) if target_user else str(target_id)
        mode_labels = {"global": "??  Œ›Ì› ò· „Õ’Ê·« ", "type": "??  Œ›Ì› Â— œ” Â", "package": "?? ﬁÌ„  Â— ÅòÌÃ", "per_gb": "?? ﬁÌ„  »Â «“«Ì Â— êÌê"}
        send_or_edit(call,
            f"?? <b>ﬁÌ„  ‰„«Ì‰œêÌ ò«—»—</b>\n"
            f"?? {uname}\n\n"
            f"Õ«·  ›⁄·Ì: <b>{mode_labels.get(mode, mode)}</b>\n\n"
            "Õ«·  „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("adm:agcfg:global:") and data.count(":") == 3:
        # adm:agcfg:global:{target_id}  ó choose pct or toman
        target_id = int(data.split(":")[3])
        cfg = get_agency_price_config(target_id)
        g_type = cfg["global_type"]
        g_val  = cfg["global_val"]
        cur_label = f"{'œ—’œ' if g_type == 'pct' else ' Ê„«‰'} ó „ﬁœ«— ›⁄·Ì: {g_val}"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("?? œ—’œ", callback_data=f"adm:agcfg:glb:pct:{target_id}"),
            types.InlineKeyboardButton("??  Ê„«‰", callback_data=f"adm:agcfg:glb:tmn:{target_id}"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:agcfg:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b> Œ›Ì› ò· „Õ’Ê·« </b>\n\n"
            f" ‰ŸÌ„ ›⁄·Ì: <b>{cur_label}</b>\n\n"
            "„ÌùŒÊ«ÂÌ œ—’œ ò„ »‘Â Ì« „»·€ À«»  ( Ê„«‰)ø", kb)
        return

    if data.startswith("adm:agcfg:glb:"):
        # adm:agcfg:glb:pct:{target_id}  or  adm:agcfg:glb:tmn:{target_id}
        parts     = data.split(":")
        dtype     = parts[3]   # pct or tmn
        target_id = int(parts[4])
        set_agency_price_config(target_id, "global", "pct" if dtype == "pct" else "toman", 0)
        state_set(uid, "admin_agcfg_global_val", target_user_id=target_id, dtype=dtype)
        bot.answer_callback_query(call.id)
        label = "œ—’œ  Œ›Ì› („À«·: 20)" if dtype == "pct" else "„»·€  Œ›Ì› »Â  Ê„«‰ („À«·: 50000)"
        send_or_edit(call,
            f"?? <b> Œ›Ì› ò· „Õ’Ê·« </b>\n\n"
            f"{'??' if dtype == 'pct' else '??'} {label} —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:agcfg:global:{target_id}"))
        return

    if data.startswith("adm:agcfg:type:") and data.count(":") == 3:
        # adm:agcfg:type:{target_id}  ó show types list
        target_id = int(data.split(":")[3])
        types_list = get_all_types()
        if not types_list:
            bot.answer_callback_query(call.id, "ÂÌç ‰Ê⁄Ì  ⁄—Ì› ‰‘œÂ.", show_alert=True)
            return
        set_agency_price_config(target_id, "type",
            get_agency_price_config(target_id)["global_type"],
            get_agency_price_config(target_id)["global_val"])
        kb = types.InlineKeyboardMarkup()
        for t in types_list:
            td = get_agency_type_discount(target_id, t["id"])
            if td:
                dot = "?"
                val_lbl = f"{td['discount_value']}{'%' if td['discount_type']=='pct' else ' '}"
            else:
                dot = "??"
                val_lbl = " ‰ŸÌ„ ‰‘œÂ"
            kb.add(types.InlineKeyboardButton(
                f"{dot} {t['name']} | {val_lbl}",
                callback_data=f"adm:agcfg:td:{target_id}:{t['id']}"
            ))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:agcfg:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b> Œ›Ì› Â— œ” Â</b>\n\nœ” Â „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("adm:agcfg:td:") and data.count(":") == 4:
        # adm:agcfg:td:{target_id}:{type_id}  ó choose pct or toman for this type
        parts     = data.split(":")
        target_id = int(parts[3])
        type_id   = int(parts[4])
        type_row  = get_type(type_id) if hasattr(__import__('bot.db', fromlist=['get_type']), 'get_type') else None
        td = get_agency_type_discount(target_id, type_id)
        cur_label = f"{'œ—’œ' if td['discount_type']=='pct' else ' Ê„«‰'} ó {td['discount_value']}" if td else " ‰ŸÌ„ ‰‘œÂ"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("?? œ—’œ", callback_data=f"adm:agcfg:tdt:{target_id}:{type_id}:pct"),
            types.InlineKeyboardButton("??  Ê„«‰", callback_data=f"adm:agcfg:tdt:{target_id}:{type_id}:tmn"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:agcfg:type:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>œ” Â #{type_id}</b>\n\n"
            f" ‰ŸÌ„ ›⁄·Ì: <b>{cur_label}</b>\n\n"
            "„ÌùŒÊ«ÂÌ œ—’œ ò„ »‘Â Ì« „»·€ À«» ø", kb)
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
        label = "œ—’œ („À«·: 15)" if dtype == "pct" else "„»·€  Ê„«‰ („À«·: 30000)"
        send_or_edit(call,
            f"?? œ” Â #{type_id}\n\n"
            f"{'??' if dtype == 'pct' else '??'} {label} —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:agcfg:td:{target_id}:{type_id}"))
        return

    if data.startswith("adm:agcfg:pkg:"):
        # adm:agcfg:pkg:{target_id}  ó show packages (existing flow)
        target_id = int(data.split(":")[3])
        set_agency_price_config(target_id, "package",
            get_agency_price_config(target_id)["global_type"],
            get_agency_price_config(target_id)["global_val"])
        packs = get_packages()
        if not packs:
            bot.answer_callback_query(call.id, "ÅòÌÃÌ „ÊÃÊœ ‰Ì” .", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        for p in packs:
            ap    = get_agency_price(target_id, p["id"])
            price = fmt_price(ap) if ap is not None else fmt_price(p["price"])
            label = f"{p['name']} | {price}  "
            kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:usr:agpe:{target_id}:{p['id']}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:agcfg:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>ﬁÌ„  Â— ÅòÌÃ</b>\n\n»—«Ì ÊÌ—«Ì‘ —ÊÌ ÅòÌÃ »“‰Ìœ:", kb)
        return

    if data.startswith("adm:agcfg:pergb:") and data.count(":") == 3:
        # adm:agcfg:pergb:{target_id} ó show types list with per-GB prices
        target_id = int(data.split(":")[3])
        set_agency_price_config(target_id, "per_gb",
            get_agency_price_config(target_id)["global_type"],
            get_agency_price_config(target_id)["global_val"])
        types_list = get_all_types()
        if not types_list:
            bot.answer_callback_query(call.id, "ÂÌç ‰Ê⁄Ì  ⁄—Ì› ‰‘œÂ.", show_alert=True)
            return
        pgb_rows = {r["type_id"]: r["price_per_gb"] for r in get_all_per_gb_prices(target_id)}
        kb = types.InlineKeyboardMarkup()
        for t in types_list:
            pgb = pgb_rows.get(t["id"])
            dot = "?" if pgb is not None else "??"
            val_lbl = f"{fmt_price(pgb)}  /êÌê" if pgb is not None else " ‰ŸÌ„ ‰‘œÂ"
            kb.add(types.InlineKeyboardButton(
                f"{dot} {t['name']} | {val_lbl}",
                callback_data=f"adm:agcfg:pgbt:{target_id}:{t['id']}"
            ))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:agcfg:{target_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>ﬁÌ„  »Â «“«Ì Â— êÌê (Â— œ” Â)</b>\n\n»—«Ì ÊÌ—«Ì‘ —ÊÌ œ” Â »“‰Ìœ:", kb)
        return

    if data.startswith("adm:agcfg:pgbt:") and data.count(":") == 4:
        # adm:agcfg:pgbt:{target_id}:{type_id}
        parts     = data.split(":")
        target_id = int(parts[3])
        type_id   = int(parts[4])
        pgb = get_per_gb_price(target_id, type_id)
        cur_label = f"{fmt_price(pgb)}  Ê„«‰/êÌê" if pgb is not None else " ‰ŸÌ„ ‰‘œÂ"
        state_set(uid, "admin_agcfg_pergb_val", target_user_id=target_id, type_id=type_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>ﬁÌ„  »Â «“«Ì Â— êÌê</b>\n\n"
            f" ‰ŸÌ„ ›⁄·Ì: <b>{cur_label}</b>\n\n"
            "ﬁÌ„  »Â «“«Ì Â— êÌê —« »Â  Ê„«‰ Ê«—œ ò‰Ìœ („À«·: 5000):",
            back_button(f"adm:agcfg:pergb:{target_id}"))
        return

    # ?? Admin: Broadcast ??????????????????????????????????????????????????????
    if data == "admin:broadcast":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Â„Â ò«—»—«‰",             callback_data="adm:bc:all"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ „‘ —Ì«‰ (Â„Â)",       callback_data="adm:bc:cust"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ „‘ —Ì«‰ ⁄«œÌ",        callback_data="adm:bc:normal"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ ‰„«Ì‰œê«‰",           callback_data="adm:bc:agents"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ «œ„Ì‰ùÂ«",            callback_data="adm:bc:admins"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>›Ê—Ê«—œ Â„ê«‰Ì</b>\n\nêÌ—‰œÂùÂ« —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data == "adm:bc:all":
        state_set(uid, "admin_broadcast_all")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ÅÌ«„ ŒÊœ —« ›Ê—Ê«—œ Ì« «—”«· ò‰Ìœ.\n»—«Ì <b>Â„Â ò«—»—«‰</b> «—”«· „Ìù‘Êœ.",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:cust":
        state_set(uid, "admin_broadcast_customers")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ÅÌ«„ ŒÊœ —« ›Ê—Ê«—œ Ì« «—”«· ò‰Ìœ.\n›ﬁÿ »—«Ì <b>„‘ —Ì«‰</b> «—”«· „Ìù‘Êœ.",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:normal":
        state_set(uid, "admin_broadcast_normal")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ÅÌ«„ ŒÊœ —« ›Ê—Ê«—œ Ì« «—”«· ò‰Ìœ.\n›ﬁÿ »—«Ì <b>„‘ —Ì«‰ ⁄«œÌ</b> (»œÊ‰ ‰„«Ì‰œê«‰ Ê «œ„Ì‰ùÂ«) «—”«· „Ìù‘Êœ.",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:agents":
        state_set(uid, "admin_broadcast_agents")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ÅÌ«„ ŒÊœ —« ›Ê—Ê«—œ Ì« «—”«· ò‰Ìœ.\n›ﬁÿ »—«Ì <b>‰„«Ì‰œê«‰</b> «—”«· „Ìù‘Êœ.",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:admins":
        state_set(uid, "admin_broadcast_admins")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ÅÌ«„ ŒÊœ —« ›Ê—Ê«—œ Ì« «—”«· ò‰Ìœ.\n›ﬁÿ »—«Ì <b>«œ„Ì‰ùÂ«</b> «—”«· „Ìù‘Êœ.",
                     back_button("admin:broadcast"))
        return

    # ?? Admin: Group management ???????????????????????????????????????????????
    if data == "admin:group":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        gid      = get_group_id()
        active_c = _count_active_topics()
        total_c  = len(TOPICS)
        gid_text = f"<code>{gid}</code>" if gid else " ‰ŸÌ„ ‰‘œÂ"
        text = (
            "?? <b>„œÌ—Ì  ê—ÊÂ «œ„Ì‰</b>\n\n"
            "?? <b>—«Â‰„«:</b>\n"
            "?. Ìò ”ÊÅ—ê—ÊÂ  ·ê—«„ »”«“Ìœ Ê Topics —« ›⁄«· ò‰Ìœ.\n"
            "?. —»«  —« »Â ê—ÊÂ «÷«›Â Ê «œ„Ì‰ ò‰Ìœ.\n"
            "?. ¬ÌœÌ ⁄œœÌ ê—ÊÂ —« »« @getidsbot œ—Ì«›  ò‰Ìœ.\n"
            "?. œò„Â ´À»  ¬ÌœÌ ê—ÊÂª —« »“‰Ìœ Ê ¬ÌœÌ —« «—”«· ò‰Ìœ.\n\n"
            "?? ¬ÌœÌ ê—ÊÂ »« <code>-100</code> ‘—Ê⁄ „Ìù‘Êœ. „À«·: <code>-1001234567890</code>\n\n"
            f"?? <b>Ê÷⁄Ì :</b> ê—ÊÂ {gid_text} |  «ÅÌòùÂ«: {active_c}/{total_c}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? À»  ¬ÌœÌ ê—ÊÂ",      callback_data="adm:grp:setid"))
        kb.add(types.InlineKeyboardButton("?? ”«Œ   «ÅÌòùÂ«Ì ÃœÌœ",  callback_data="adm:grp:create"))
        kb.add(types.InlineKeyboardButton("?? »«“”«“Ì Â„Â  «ÅÌòùÂ«", callback_data="adm:grp:reset"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:grp:setid":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_set_group_id")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>¬ÌœÌ ⁄œœÌ ê—ÊÂ</b> —« «—”«· ò‰Ìœ:\n\n"
            "„À«·: <code>-1001234567890</code>\n\n"
            "»—«Ì œ—Ì«›  ¬ÌœÌ ê—ÊÂ° —»«  <b>@getidsbot</b> —« »Â ê—ÊÂ «÷«›Â ò‰Ìœ Ê <code>/id</code> »›—” Ìœ.",
            back_button("admin:group"))
        return

    if data == "adm:grp:create":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id, "œ— Õ«· ”«Œ   «ÅÌòùÂ«...", show_alert=False)
        result = ensure_group_topics()
        log_admin_action(uid, "”«Œ   «ÅÌòùÂ«Ì ê—ÊÂ")
        send_or_edit(call, f"?? <b>”«Œ   «ÅÌò</b>\n\n{result}", back_button("admin:group"))
        return

    if data == "adm:grp:reset":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id, "œ— Õ«· »«“”«“Ì...", show_alert=False)
        result = reset_and_recreate_topics()
        log_admin_action(uid, "»«“”«“Ì  «ÅÌòùÂ«Ì ê—ÊÂ")
        send_or_edit(call, f"?? <b>»«“”«“Ì  «ÅÌòùÂ«</b>\n\n{result}", back_button("admin:group"))
        return

    # ?? Admin: Settings ???????????????????????????????????????????????????????
    if data == "admin:settings":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("?? Å‘ Ì»«‰Ì",           callback_data="adm:set:support"),
            types.InlineKeyboardButton("?? œ—ê«ÂùÂ«Ì Å—œ«Œ ",   callback_data="adm:set:gateways"),
        )
        kb.add(types.InlineKeyboardButton("?? ò«‰«· ﬁ›·",           callback_data="adm:locked_channels"))
        kb.add(types.InlineKeyboardButton("??  ”  —«Ìê«‰",      callback_data="adm:set:freetest"))
        kb.add(types.InlineKeyboardButton("? „ ‰ùÂ«Ì —»« ",    callback_data="adm:bot_texts"))
        kb.add(types.InlineKeyboardButton("?? „œÌ—Ì  ›—Ê‘",    callback_data="adm:set:shop"))
        kb.add(types.InlineKeyboardButton("?? Ã„⁄ù¬Ê—Ì ‘„«—Â  ·›‰", callback_data="adm:set:phone"))
        kb.add(types.InlineKeyboardButton("?? „œÌ—Ì  ⁄„·Ì«  —»« ", callback_data="adm:ops"))
        kb.add(types.InlineKeyboardButton("?? „œÌ—Ì  ê—ÊÂ",    callback_data="admin:group"))
        kb.add(types.InlineKeyboardButton("?? ÅÌ«„ùÂ«Ì ÅÌ‰ ‘œÂ", callback_data="adm:pin"))
        kb.add(types.InlineKeyboardButton("? ¬ÌœÌ «Ì„ÊÃÌ Å—„ÌÊ„", callback_data="adm:emoji:menu"))
        kb.add(types.InlineKeyboardButton("? „œÌ—Ì  «⁄·«‰ùÂ«",  callback_data="adm:notif"))
        kb.add(types.InlineKeyboardButton("??? »ò«Å",            callback_data="admin:backup"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b> ‰ŸÌ„« </b>", kb)
        return

    # ?? Admin: Premium Emoji Tools ????????????????????????????????????????????
    if data == "adm:emoji:menu":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("??  »œÌ· ÅÌ«„ »Â ¬ÌœÌ «Ì„ÊÃÌ", callback_data="adm:emoji:extract"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            "? <b>¬ÌœÌ «Ì„ÊÃÌ Å—„ÌÊ„</b>\n\n"
            "«»“«—Â«Ì „œÌ—Ì  «Ì„ÊÃÌùÂ«Ì ”›«—‘Ì  ·ê—«„ Å—„ÌÊ„:",
            kb,
        )
        return

    if data == "adm:emoji:extract":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_emoji_extract")
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            "?? <b> »œÌ· ÅÌ«„ »Â ¬ÌœÌ «Ì„ÊÃÌ</b>\n\n"
            "Ìò ÅÌ«„ Õ«ÊÌ «Ì„ÊÃÌ Å—„ÌÊ„ (”›«—‘Ì) «—”«· ò‰Ìœ.\n"
            "„Ìù Ê«‰Ìœ ç‰œ «Ì„ÊÃÌ œ— Ìò ÅÌ«„ »›—” Ìœ.\n\n"
            "<i>„ ‰ Â„—«Â «Ì„ÊÃÌ ‰Ì“ ‘‰«”«ÌÌ „Ìù‘Êœ.</i>",
            back_button("adm:emoji:menu"),
        )
        return

    if data == "adm:set:agency_toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("agency_request_enabled", "1")
        new = "0" if cur == "1" else "1"
        setting_set("agency_request_enabled", new)
        log_admin_action(uid, f"œ—ŒÊ«”  ‰„«Ì‰œêÌ «“  ‰ŸÌ„«  {'›⁄«·' if new == '1' else '€Ì—›⁄«·'} ‘œ")
        label = "›⁄«·" if new == "1" else "€Ì—›⁄«·"
        bot.answer_callback_query(call.id, f"œ—ŒÊ«”  ‰„«Ì‰œêÌ: {label}")
        # re-render settings
        _fake_call_data = type('obj', (object,), {
            'id': call.id, 'message': call.message,
            'data': 'admin:settings', 'from_user': call.from_user
        })()
        _fake_call_data.id = call.id
        try:
            agency_flag  = new
            agency_icon  = "?" if agency_flag == "1" else "?"
            pct          = setting_get("agency_default_discount_pct", "20")
            kb           = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("?? Å‘ Ì»«‰Ì",           callback_data="adm:set:support"),
                types.InlineKeyboardButton("?? œ—ê«ÂùÂ«Ì Å—œ«Œ ",   callback_data="adm:set:gateways"),
            )
            kb.add(types.InlineKeyboardButton("?? ò«‰«· ﬁ›·",           callback_data="adm:locked_channels"))
            kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ „ ‰ «” «— ", callback_data="adm:set:start_text"))
            kb.add(types.InlineKeyboardButton("?? ﬁÊ«‰Ì‰ Œ—Ìœ",     callback_data="adm:set:rules"))
            kb.add(types.InlineKeyboardButton("??  ‰ŸÌ„«  ›—Ê‘",    callback_data="adm:set:shop"))
            kb.add(types.InlineKeyboardButton("?? „œÌ—Ì  ê—ÊÂ",    callback_data="admin:group"))
            kb.add(types.InlineKeyboardButton("?? ÅÌ«„ùÂ«Ì ÅÌ‰ ‘œÂ", callback_data="adm:pin"))
            kb.add(types.InlineKeyboardButton(f"{agency_icon} œ—ŒÊ«”  ‰„«Ì‰œêÌ", callback_data="adm:set:agency_toggle"))
            kb.add(types.InlineKeyboardButton("??  Œ›Ì› ÅÌ‘ù›—÷ ‰„«Ì‰œêÌ", callback_data="adm:set:agency_defpct"))
            kb.add(types.InlineKeyboardButton("? „œÌ—Ì  «⁄·«‰ùÂ«",  callback_data="adm:notif"))
            kb.add(types.InlineKeyboardButton("??? »ò«Å",            callback_data="admin:backup"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call, "?? <b> ‰ŸÌ„« </b>", kb)
        except Exception:
            pass
        return

    if data == "adm:set:agency_defpct":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur_pct = setting_get("agency_default_discount_pct", "20")
        state_set(uid, "admin_set_default_discount_pct")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b> Œ›Ì› ÅÌ‘ù›—÷ ‰„«Ì‰œêÌ</b>\n\n"
            f" ‰ŸÌ„ ›⁄·Ì: <b>{cur_pct}%</b>\n\n"
            "œ—’œ ÃœÌœ —« Ê«—œ ò‰Ìœ (⁄œœ »Ì‰ 0  « 100):",
            back_button("admin:settings"))
        return

    # ?? Notification Management ???????????????????????????????????????????????
    # Notification types: (key, label)
    _NOTIF_TYPES = [
        ("new_users",        "?? ò«—»— ÃœÌœ"),
        ("payment_approval", "??  √ÌÌœ Å—œ«Œ "),
        ("renewal_request",  "?? œ—ŒÊ«”   „œÌœ"),
        ("purchase_log",     "?? ·«ê Œ—Ìœ"),
        ("renewal_log",      "?? ·«ê  „œÌœ"),
        ("wallet_log",       "?? ·«ê òÌ›ùÅÊ·"),
        ("test_report",      "?? ê“«—‘  ” "),
        ("broadcast_report", "?? «ÿ·«⁄ù—”«‰Ì Ê ÅÌ‰"),
        ("referral_log",     "?? “Ì—„Ã„Ê⁄ÂùêÌ—Ì"),
        ("agency_request",   "?? œ—ŒÊ«”  ‰„«Ì‰œêÌ"),
        ("agency_log",       "?? ·«ê ‰„«Ì‰œê«‰"),
        ("admin_ops_log",    "?? ·«ê ⁄„·Ì« Ì"),
        ("error_log",        "? ê“«—‘ Œÿ«"),
        ("backup",           "?? »ò«Å"),
    ]

    if data == "adm:notif":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? «⁄·«‰ Â«Ì —»«  «Ê‰—",   callback_data="adm:notif:own"))
        kb.add(types.InlineKeyboardButton("?? «⁄·«‰ Â«Ì —»«  «œ„Ì‰",   callback_data="adm:notif:bot"))
        kb.add(types.InlineKeyboardButton("?? ê—ÊÂ",  callback_data="adm:notif:grp"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>„œÌ—Ì  «⁄·«‰ùÂ«</b>\n\n"
            "?? <b>«⁄·«‰ Â«Ì —»«  «Ê‰—</b>: «⁄·«‰ »—«Ì «Ê‰— œ— —»« \n"
            "?? <b>«⁄·«‰ Â«Ì —»«  «œ„Ì‰</b>: «⁄·«‰ »—«Ì «œ„Ì‰ùÂ«Ì ›—⁄Ì (»— «”«” œ” —”Ì)\n"
            "?? <b>ê—ÊÂ</b>: «⁄·«‰ œ—  «ÅÌòùÂ«Ì ê—ÊÂ",
            kb)
        return

    if data == "adm:notif:own":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_own_{key}", "1") == "1"
            icon = "?" if on else "?"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:otg:{key}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>«⁄·«‰ Â«Ì —»«  «Ê‰—</b>\n\n"
            "«⁄·«‰ùÂ«ÌÌ òÂ „” ﬁÌ„« »—«Ì <b>ADMIN_IDS</b> («Ìœ À«»   Ê config.py) «—”«· „Ìù‘‰:"
            "\n? = ›⁄«·  |  ? = €Ì—›⁄«·",
            kb)
        return

    if data.startswith("adm:notif:otg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        key = data[len("adm:notif:otg:"):]
        cur = setting_get(f"notif_own_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_own_{key}", new)
        log_admin_action(uid, f"«⁄·«‰ ‘Œ’Ì {key} {'›⁄«·' if new == '1' else '€Ì—›⁄«·'} ‘œ")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "›⁄«·" if new == "1" else "€Ì—›⁄«·"
        bot.answer_callback_query(call.id, f"{status_lbl} ‘œ: {lbl}")
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_own_{k}", "1") == "1"
            icon = "?" if on else "?"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:otg:{k}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>«⁄·«‰ Â«Ì —»«  «Ê‰—</b>\n\n"
            "«⁄·«‰ùÂ«ÌÌ òÂ „” ﬁÌ„« »—«Ì <b>ADMIN_IDS</b> «—”«· „Ìù‘‰:"
            "\n? = ›⁄«·  |  ? = €Ì—›⁄«·",
            kb)
        return

    if data == "adm:notif:grp":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_grp_{key}", "1") == "1"
            icon = "?" if on else "?"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:gtg:{key}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>ê—ÊÂ</b>\n\n"
            "«‰ Œ«» ò‰Ìœ òœ«„ «⁄·«‰ùÂ« œ—  «ÅÌòùÂ«Ì ê—ÊÂ «—”«· ‘Ê‰œ:\n"
            "? = ›⁄«·  |  ? = €Ì—›⁄«·",
            kb)
        return

    if data == "adm:notif:bot":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_bot_{key}", "1") == "1"
            icon = "?" if on else "?"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:btg:{key}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>«⁄·«‰ Â«Ì —»«  «œ„Ì‰</b>\n\n"
            "«‰ Œ«» ò‰Ìœ òœ«„ «⁄·«‰ùÂ« »Â ’Ê—  „” ﬁÌ„ »—«Ì «œ„Ì‰ùÂ« «—”«· ‘Ê‰œ:\n"
            "? = ›⁄«·  |  ? = €Ì—›⁄«·",
            kb)
        return

    if data.startswith("adm:notif:gtg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        key = data[len("adm:notif:gtg:"):]
        cur = setting_get(f"notif_grp_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_grp_{key}", new)
        log_admin_action(uid, f"«⁄·«‰ ê—ÊÂ {key} {'›⁄«·' if new == '1' else '€Ì—›⁄«·'} ‘œ")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "›⁄«·" if new == "1" else "€Ì—›⁄«·"
        bot.answer_callback_query(call.id, f"{status_lbl} ‘œ: {lbl}")
        # re-render group list
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_grp_{k}", "1") == "1"
            icon = "?" if on else "?"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:gtg:{k}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>ê—ÊÂ</b>\n\n"
            "«‰ Œ«» ò‰Ìœ òœ«„ «⁄·«‰ùÂ« œ—  «ÅÌòùÂ«Ì ê—ÊÂ «—”«· ‘Ê‰œ:\n"
            "? = ›⁄«·  |  ? = €Ì—›⁄«·",
            kb)
        return

    if data.startswith("adm:notif:btg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        key = data[len("adm:notif:btg:"):]
        cur = setting_get(f"notif_bot_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_bot_{key}", new)
        log_admin_action(uid, f"«⁄·«‰ —»«  {key} {'›⁄«·' if new == '1' else '€Ì—›⁄«·'} ‘œ")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "›⁄«·" if new == "1" else "€Ì—›⁄«·"
        bot.answer_callback_query(call.id, f"{status_lbl} ‘œ: {lbl}")
        # re-render bot list
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_bot_{k}", "1") == "1"
            icon = "?" if on else "?"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:btg:{k}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:notif", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>«⁄·«‰ Â«Ì —»«  «œ„Ì‰</b>\n\n"
            "«‰ Œ«» ò‰Ìœ òœ«„ «⁄·«‰ùÂ« »Â ’Ê—  „” ﬁÌ„ »—«Ì «œ„Ì‰ùÂ« «—”«· ‘Ê‰œ:\n"
            "? = ›⁄«·  |  ? = €Ì—›⁄«·",
            kb)
        return
    # ?? End Notification Management ???????????????????????????????????????????

    if data == "adm:set:support":
        support_raw = setting_get("support_username", "")
        support_link = setting_get("support_link", "")
        support_link_desc = setting_get("support_link_desc", "")
        kb = types.InlineKeyboardMarkup()
        tg_status = "?" if support_raw else "?"
        link_status = "?" if support_link else "?"
        kb.add(types.InlineKeyboardButton(f"{tg_status} Å‘ Ì»«‰Ì  ·ê—«„", callback_data="adm:set:support_tg"))
        kb.add(types.InlineKeyboardButton(f"{link_status} Å‘ Ì»«‰Ì ¬‰·«Ì‰ (·Ì‰ò)", callback_data="adm:set:support_link"))
        kb.add(types.InlineKeyboardButton("??  Ê÷ÌÕ«  Å‘ Ì»«‰Ì", callback_data="adm:set:support_desc"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        text = (
            "?? <b> ‰ŸÌ„«  Å‘ Ì»«‰Ì</b>\n\n"
            f"??  ·ê—«„: <code>{esc(support_raw or 'À»  ‰‘œÂ')}</code>\n"
            f"?? ·Ì‰ò: <code>{esc(support_link or 'À»  ‰‘œÂ')}</code>\n"
            f"??  Ê÷ÌÕ« : {esc(support_link_desc or 'ÅÌ‘ù›—÷')}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:set:support_tg":
        state_set(uid, "admin_set_support")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ¬ÌœÌ Ì« ·Ì‰ò Å‘ Ì»«‰Ì  ·ê—«„ —« «—”«· ò‰Ìœ.\n„À«·: <code>@username</code>",
                     back_button("adm:set:support"))
        return

    if data == "adm:set:support_link":
        state_set(uid, "admin_set_support_link")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ·Ì‰ò Å‘ Ì»«‰Ì ¬‰·«Ì‰ —« «—”«· ò‰Ìœ.\n„À«·: <code>https://example.com/chat</code>\n\n»—«Ì Õ–›° <code>-</code> »›—” Ìœ.",
                     back_button("adm:set:support"))
        return

    if data == "adm:set:support_desc":
        state_set(uid, "admin_set_support_desc")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "??  Ê÷ÌÕ«  ‰„«Ì‘Ì »«·«Ì œò„ÂùÂ«Ì Å‘ Ì»«‰Ì —« »‰ÊÌ”Ìœ.\n\n»—«Ì »«“ê‘  »Â ÅÌ‘ù›—÷° <code>-</code> »›—” Ìœ.",
                     back_button("adm:set:support"))
        return

    # ?? Shop management settings ?????????????????????????????????????????????
    if data == "adm:set:shop":
        shop_open     = setting_get("shop_open", "1")
        preorder_mode = setting_get("preorder_mode", "0")
        open_icon  = "??" if shop_open     == "1" else "??"
        stock_icon = "??" if preorder_mode == "1" else "??"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{open_icon} Ê÷⁄Ì  ›—Ê‘: {'»«“' if shop_open == '1' else '»” Â'}",
            callback_data="adm:shop:toggle_open"))
        kb.add(types.InlineKeyboardButton(
            f"{stock_icon} ›—Ê‘ »— «”«” „ÊÃÊœÌ: {'›⁄«·' if preorder_mode == '1' else '€Ì—›⁄«·'}",
            callback_data="adm:shop:toggle_stock"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        text = (
            "?? <b>„œÌ—Ì  ›—Ê‘</b>\n\n"
            f"?? <b>Ê÷⁄Ì  ›—Ê‘:</b> {'?? »«“' if shop_open == '1' else '?? »” Â'}\n"
            f"?? <b>›—Ê‘ »— «”«” „ÊÃÊœÌ:</b> {'?? ›⁄«· ñ ›ﬁÿ ÅòÌÃùÂ«Ì œ«—«Ì „ÊÃÊœÌ ‰„«Ì‘ œ«œÂ „Ìù‘Ê‰œ.' if preorder_mode == '1' else '?? €Ì—›⁄«· ñ Â„Â ÅòÌÃùÂ« ‰„«Ì‘ œ«œÂ „Ìù‘Ê‰œ. œ— ’Ê—  ‰»Êœ „ÊÃÊœÌ° ”›«—‘ »Â Å‘ Ì»«‰Ì «—”«· „Ìù‘Êœ.'}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:shop:toggle_open":
        current = setting_get("shop_open", "1")
        setting_set("shop_open", "0" if current == "1" else "1")
        log_admin_action(uid, f"›—Ê‘ê«Â {'»” Â' if current == '1' else '»«“'} ‘œ")
        bot.answer_callback_query(call.id, "Ê÷⁄Ì  ›—Ê‘  €ÌÌ— ò—œ.")
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
        log_admin_action(uid, f"Õ«·  ÅÌ‘ù›—Ê‘ {'€Ì—›⁄«·' if current == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " ‰ŸÌ„ ›—Ê‘ »— «”«” „ÊÃÊœÌ  €ÌÌ— ò—œ.")
        from types import SimpleNamespace as _SN
        fake = _SN(id=call.id, from_user=call.from_user, message=call.message, data="adm:set:shop")
        _dispatch_callback(fake, uid, "adm:set:shop")
        return

    # ?? Bot Operations Management ?????????????????????????????????????????????
    def _build_ops_kb():
        bot_status      = setting_get("bot_status", "on")
        renewal_enabled = setting_get("manual_renewal_enabled", "1")
        referral_enabled = setting_get("referral_enabled", "1")
        bulk_mode       = setting_get("bulk_sale_mode", "everyone")
        status_map = {"on": "?? —Ê‘‰", "off": "?? Œ«„Ê‘", "update": "?? »—Ê“—”«‰Ì"}
        renewal_map = {"1": "? ›⁄«·", "0": "? €Ì—›⁄«·"}
        referral_map = {"1": "? ›⁄«·", "0": "? €Ì—›⁄«·"}
        bulk_map = {"everyone": "? Â„Â ò«—»—«‰", "agents_only": "?? ›ﬁÿ ‰„«Ì‰œê«‰", "disabled": "? €Ì—›⁄«·"}
        status_label  = status_map.get(bot_status, "?? —Ê‘‰")
        renewal_label = renewal_map.get(renewal_enabled, "? ›⁄«·")
        referral_label = referral_map.get(referral_enabled, "? ›⁄«·")
        bulk_label    = bulk_map.get(bulk_mode, "? Â„Â ò«—»—«‰")
        ops_kb = types.InlineKeyboardMarkup(row_width=2)
        ops_kb.row(
            types.InlineKeyboardButton(status_label,  callback_data="adm:ops:status"),
            types.InlineKeyboardButton("?? Ê÷⁄Ì  —»« ", callback_data="adm:ops:noop"),
        )
        ops_kb.row(
            types.InlineKeyboardButton(renewal_label, callback_data="adm:ops:renewal"),
            types.InlineKeyboardButton("??  „œÌœ ò«‰›ÌêùÂ«Ì À»  œ” Ì", callback_data="adm:ops:noop"),
        )
        ops_kb.row(
            types.InlineKeyboardButton(referral_label, callback_data="adm:ops:referral_toggle"),
            types.InlineKeyboardButton("?? “Ì—„Ã„Ê⁄ÂùêÌ—Ì  ??  ‰ŸÌ„« ", callback_data="adm:ref:settings"),
        )
        ops_kb.row(
            types.InlineKeyboardButton(bulk_label, callback_data="adm:ops:bulk_menu"),
            types.InlineKeyboardButton("?? ›—Ê‘ ⁄„œÂ", callback_data="adm:ops:noop"),
        )
        _inv_enabled = setting_get("invoice_expiry_enabled", "1")
        _inv_mins    = setting_get("invoice_expiry_minutes", "30")
        _inv_label   = (
            f"? ›⁄«· ó {_inv_mins} œﬁÌﬁÂ"
            if _inv_enabled == "1" else "? €Ì—›⁄«·"
        )
        ops_kb.row(
            types.InlineKeyboardButton(_inv_label, callback_data="adm:ops:invoice_expiry"),
            types.InlineKeyboardButton("?? «⁄ »«— ›«ò Ê— Å—œ«Œ ", callback_data="adm:ops:noop"),
        )
        _wp_enabled = setting_get("wallet_pay_enabled", "1")
        _wp_label   = "? ›⁄«·" if _wp_enabled == "1" else "? €Ì—›⁄«·"
        ops_kb.row(
            types.InlineKeyboardButton(_wp_label, callback_data="adm:ops:wallet_pay_toggle"),
            types.InlineKeyboardButton("?? Å—œ«Œ  »« „ÊÃÊœÌ  ?? «” À‰«Â«", callback_data="adm:ops:wallet_pay_exc"),
        )
        ops_kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        return ops_kb

    def _ops_menu_text():
        bot_status      = setting_get("bot_status", "on")
        renewal_enabled = setting_get("manual_renewal_enabled", "1")
        referral_enabled = setting_get("referral_enabled", "1")
        bulk_mode       = setting_get("bulk_sale_mode", "everyone")
        min_qty, max_qty = get_bulk_qty_limits()
        max_label = "»œÊ‰ „ÕœÊœÌ " if max_qty == 0 else str(max_qty)
        status_fa  = {"on": "?? —Ê‘‰", "off": "?? Œ«„Ê‘", "update": "?? »—Ê“—”«‰Ì"}.get(bot_status, "?? —Ê‘‰")
        renewal_fa = "? ›⁄«·" if renewal_enabled == "1" else "? €Ì—›⁄«·"
        referral_fa = "? ›⁄«·" if referral_enabled == "1" else "? €Ì—›⁄«·"
        bulk_fa = {"everyone": "? Â„Â ò«—»—«‰", "agents_only": "?? ›ﬁÿ ‰„«Ì‰œê«‰", "disabled": "? €Ì—›⁄«·"}.get(bulk_mode, "? Â„Â ò«—»—«‰")
        _inv_exp_enabled = setting_get("invoice_expiry_enabled", "1")
        _inv_exp_mins    = setting_get("invoice_expiry_minutes", "30")
        _inv_fa = (
            f"? ›⁄«· ó Â— ›«ò Ê—  « <b>{_inv_exp_mins} œﬁÌﬁÂ</b> „⁄ »— «” ."
            if _inv_exp_enabled == "1"
            else "? €Ì—›⁄«· ó ›«ò Ê—Â« „ÕœÊœÌ  “„«‰Ì ‰œ«—‰œ."
        )
        _wp_enabled = setting_get("wallet_pay_enabled", "1")
        _wp_fa = "? ›⁄«·" if _wp_enabled == "1" else "? €Ì—›⁄«·"
        return (
            "?? <b>„œÌ—Ì  ⁄„·Ì«  —»« </b>\n\n"
            f"?? <b>Ê÷⁄Ì  —»« :</b> {status_fa}\n"
            f"?? <b> „œÌœ ò«‰›ÌêùÂ«Ì À»  œ” Ì:</b> {renewal_fa}\n"
            f"?? <b>“Ì—„Ã„Ê⁄ÂùêÌ—Ì:</b> {referral_fa}\n"
            f"?? <b>›—Ê‘ ⁄„œÂ:</b> {bulk_fa}\n"
            f"   ? Õœ«ﬁ·  ⁄œ«œ: <b>{min_qty}</b> | Õœ«òÀ—  ⁄œ«œ: <b>{max_label}</b>\n"
            f"?? <b>«⁄ »«— ›«ò Ê— Å—œ«Œ :</b> {_inv_fa}\n"
            f"?? <b>Å—œ«Œ  »« „ÊÃÊœÌ:</b> {_wp_fa}\n\n"
            "»—«Ì  €ÌÌ— Â— „Ê—œ° œò„Â Ê÷⁄Ì  ›⁄·Ì ¬‰ —« ·„” ò‰Ìœ."
        )

    if data == "adm:ops":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:noop":
        bot.answer_callback_query(call.id)
        return

    if data == "adm:ops:status":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("bot_status", "on")
        cycle = {"on": "off", "off": "update", "update": "on"}
        new_status = cycle.get(cur, "on")
        setting_set("bot_status", new_status)
        labels = {"on": "—Ê‘‰", "off": "Œ«„Ê‘", "update": "»—Ê“—”«‰Ì"}
        log_admin_action(uid, f"Ê÷⁄Ì  —»«  »Â {labels[new_status]}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, f"Ê÷⁄Ì  —»« : {labels[new_status]}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:renewal":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("manual_renewal_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("manual_renewal_enabled", new_val)
        log_admin_action(uid, f" „œÌœ œ” Ì {'›⁄«·' if new_val == '1' else '€Ì—›⁄«·'} ‘œ")
        label = "›⁄«·" if new_val == "1" else "€Ì—›⁄«·"
        bot.answer_callback_query(call.id, f" „œÌœ œ” Ì: {label}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:referral_toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("referral_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("referral_enabled", new_val)
        log_admin_action(uid, f"“Ì—„Ã„Ê⁄ÂùêÌ—Ì {'›⁄«·' if new_val == '1' else '€Ì—›⁄«·'} ‘œ")
        label = "›⁄«·" if new_val == "1" else "€Ì—›⁄«·"
        bot.answer_callback_query(call.id, f"“Ì—„Ã„Ê⁄ÂùêÌ—Ì: {label}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:bulk_sale":
        # Legacy ó redirect to the sub-menu
        bot.answer_callback_query(call.id)
        from types import SimpleNamespace as _SN
        fake = _SN(id=call.id, from_user=call.from_user, message=call.message, data="adm:ops:bulk_menu")
        _dispatch_callback(fake, uid, "adm:ops:bulk_menu")
        return

    # ?? Bulk Sale Sub-menu ????????????????????????????????????????????????????
    def _bulk_menu_kb():
        bulk_mode = setting_get("bulk_sale_mode", "everyone")
        min_qty, max_qty = get_bulk_qty_limits()
        max_label = "»œÊ‰ „ÕœÊœÌ " if max_qty == 0 else str(max_qty)
        bulk_map  = {
            "everyone":    "? Â„Â ò«—»—«‰",
            "agents_only": "?? ›ﬁÿ ‰„«Ì‰œê«‰",
            "disabled":    "? €Ì—›⁄«·",
        }
        mode_label = bulk_map.get(bulk_mode, "? Â„Â ò«—»—«‰")
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(
            types.InlineKeyboardButton(mode_label,       callback_data="adm:ops:bulk_mode"),
            types.InlineKeyboardButton("?? Ê÷⁄Ì  ›—Ê‘ ⁄„œÂ", callback_data="adm:ops:noop"),
        )
        kb.row(
            types.InlineKeyboardButton(f"?? Õœ«ﬁ·: {min_qty} ⁄œœ",     callback_data="adm:ops:bulk_min"),
            types.InlineKeyboardButton(f"?? Õœ«òÀ—: {max_label}",      callback_data="adm:ops:bulk_max"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ops", icon_custom_emoji_id="5253997076169115797"))
        return kb

    def _bulk_menu_text():
        bulk_mode = setting_get("bulk_sale_mode", "everyone")
        min_qty, max_qty = get_bulk_qty_limits()
        max_label = "»œÊ‰ „ÕœÊœÌ " if max_qty == 0 else f"{max_qty} ⁄œœ"
        bulk_fa   = {
            "everyone":    "? Â„Â ò«—»—«‰",
            "agents_only": "?? ›ﬁÿ ‰„«Ì‰œê«‰",
            "disabled":    "? €Ì—›⁄«·",
        }.get(bulk_mode, "? Â„Â ò«—»—«‰")
        return (
            "?? <b> ‰ŸÌ„«  ›—Ê‘ ⁄„œÂ</b>\n\n"
            f"?? <b>Ê÷⁄Ì :</b> {bulk_fa}\n"
            f"?? <b>Õœ«ﬁ·  ⁄œ«œ Œ—Ìœ:</b> {min_qty} ⁄œœ\n"
            f"?? <b>Õœ«òÀ—  ⁄œ«œ Œ—Ìœ:</b> {max_label}\n\n"
            "»—«Ì  €ÌÌ— Â— ê“Ì‰Â° œò„Â „—»ÊÿÂ —« ·„” ò‰Ìœ."
        )

    if data == "adm:ops:bulk_menu":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _bulk_menu_text(), _bulk_menu_kb())
        return

    if data == "adm:ops:bulk_mode":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("bulk_sale_mode", "everyone")
        cycle = {"everyone": "agents_only", "agents_only": "disabled", "disabled": "everyone"}
        new_val = cycle.get(cur, "everyone")
        setting_set("bulk_sale_mode", new_val)
        labels = {"everyone": "Â„Â ò«—»—«‰", "agents_only": "›ﬁÿ ‰„«Ì‰œê«‰", "disabled": "€Ì—›⁄«·"}
        log_admin_action(uid, f"›—Ê‘ ⁄„œÂ: {labels[new_val]}")
        bot.answer_callback_query(call.id, f"›—Ê‘ ⁄„œÂ: {labels[new_val]}")
        send_or_edit(call, _bulk_menu_text(), _bulk_menu_kb())
        return

    if data == "adm:ops:bulk_min":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_bulk_min_qty")
        bot.answer_callback_query(call.id)
        cur_min = setting_get("bulk_min_qty", "1")
        send_or_edit(call,
            "?? <b> ‰ŸÌ„ Õœ«ﬁ·  ⁄œ«œ Œ—Ìœ</b>\n\n"
            " ⁄œ«œ Õœ«ﬁ· ò«‰›Ìê œ— Â— ”›«—‘ ›—Ê‘ ⁄„œÂ —« Ê«—œ ò‰Ìœ.\n\n"
            f"?? „ﬁœ«— ›⁄·Ì: <b>{cur_min}</b>\n\n"
            "?? <i>Ìò ⁄œœ ’ÕÌÕ Ê „À»  Ê«—œ ò‰Ìœ („À·« ?° ?° ?)</i>",
            back_button("adm:ops:bulk_menu"))
        return

    if data == "adm:ops:bulk_max":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_bulk_max_qty")
        bot.answer_callback_query(call.id)
        cur_max = setting_get("bulk_max_qty", "0")
        cur_max_label = "»œÊ‰ „ÕœÊœÌ " if cur_max == "0" else cur_max
        send_or_edit(call,
            "?? <b> ‰ŸÌ„ Õœ«òÀ—  ⁄œ«œ Œ—Ìœ</b>\n\n"
            " ⁄œ«œ Õœ«òÀ— ò«‰›Ìê œ— Â— ”›«—‘ ›—Ê‘ ⁄„œÂ —« Ê«—œ ò‰Ìœ.\n\n"
            f"?? „ﬁœ«— ›⁄·Ì: <b>{cur_max_label}</b>\n\n"
            "?? <i>Ìò ⁄œœ ’ÕÌÕ „À»  Ê«—œ ò‰Ìœ° Ì« <b>0</b> »—«Ì ´»œÊ‰ „ÕœÊœÌ ª</i>",
            back_button("adm:ops:bulk_menu"))
        return

    # ?? Invoice Expiry Sub-menu ???????????????????????????????????????????????
    def _invoice_expiry_menu_kb():
        enabled = setting_get("invoice_expiry_enabled", "1")
        mins    = setting_get("invoice_expiry_minutes", "30")
        toggle_label = "? ›⁄«· ó ò·Ìò ò‰Ìœ  « €Ì—›⁄«· ‘Êœ" if enabled == "1" else "? €Ì—›⁄«· ó ò·Ìò ò‰Ìœ  « ›⁄«· ‘Êœ"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:ops:inv_exp:toggle"))
        if enabled == "1":
            kb.add(types.InlineKeyboardButton(f"?  ‰ŸÌ„ “„«‰ ›«ò Ê—: {mins} œﬁÌﬁÂ", callback_data="adm:ops:inv_exp:set_mins"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ops", icon_custom_emoji_id="5253997076169115797"))
        return kb

    def _invoice_expiry_menu_text():
        enabled = setting_get("invoice_expiry_enabled", "1")
        mins    = setting_get("invoice_expiry_minutes", "30")
        status_fa = f"? ›⁄«· ó Â— ›«ò Ê—  « <b>{mins} œﬁÌﬁÂ</b> „⁄ »— «” ." if enabled == "1" else "? €Ì—›⁄«· ó ›«ò Ê—Â« „ÕœÊœÌ  “„«‰Ì ‰œ«—‰œ."
        return (
            "?? <b> ‰ŸÌ„«  «⁄ »«— ›«ò Ê— Å—œ«Œ </b>\n\n"
            f"?? <b>Ê÷⁄Ì :</b> {status_fa}\n\n"
            "Êﬁ Ì ›⁄«· »«‘œ° Â— ›«ò Ê— Å—œ«Œ  (Œ—Ìœ°  „œÌœ° ‘«—é òÌ› ÅÊ·) "
            "›ﬁÿ  « „œ   ⁄ÌÌ‰ù‘œÂ „⁄ »— «” . Å” «“ « „«„ “„«‰° ò«—»— ‰„Ìù Ê«‰œ "
            "«“ ¬‰ ›«ò Ê— »—«Ì Å—œ«Œ  «” ›«œÂ ò‰œ.\n\n"
            "„ﬁœ«— ÅÌ‘ù›—÷: <b>30 œﬁÌﬁÂ</b>"
        )

    if data == "adm:ops:invoice_expiry":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _invoice_expiry_menu_text(), _invoice_expiry_menu_kb())
        return

    if data == "adm:ops:inv_exp:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("invoice_expiry_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("invoice_expiry_enabled", new_val)
        label = "›⁄«·" if new_val == "1" else "€Ì—›⁄«·"
        log_admin_action(uid, f"«⁄ »«— ›«ò Ê— Å—œ«Œ  {label} ‘œ")
        bot.answer_callback_query(call.id, f"«⁄ »«— ›«ò Ê—: {label}")
        send_or_edit(call, _invoice_expiry_menu_text(), _invoice_expiry_menu_kb())
        return

    if data == "adm:ops:inv_exp:set_mins":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur_mins = setting_get("invoice_expiry_minutes", "30")
        state_set(uid, "admin_set_invoice_expiry_minutes")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "? <b> ‰ŸÌ„ “„«‰ «⁄ »«— ›«ò Ê—</b>\n\n"
            "„œ  “„«‰ «⁄ »«— ›«ò Ê— Å—œ«Œ  —« »Â œﬁÌﬁÂ Ê«—œ ò‰Ìœ.\n\n"
            f"?? „ﬁœ«— ›⁄·Ì: <b>{cur_mins} œﬁÌﬁÂ</b>\n\n"
            "?? <i>Ìò ⁄œœ ’ÕÌÕ „À»  Ê«—œ ò‰Ìœ („À·« ??° ??° ??)</i>",
            back_button("adm:ops:invoice_expiry"))
        return

    # ?? Wallet Pay Toggle ?????????????????????????????????????????????????????
    if data == "adm:ops:wallet_pay_toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("wallet_pay_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("wallet_pay_enabled", new_val)
        label = "›⁄«·" if new_val == "1" else "€Ì—›⁄«·"
        log_admin_action(uid, f"Å—œ«Œ  »« „ÊÃÊœÌ {label} ‘œ")
        bot.answer_callback_query(call.id, f"Å—œ«Œ  »« „ÊÃÊœÌ: {label}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    # ?? Wallet Pay Exceptions Sub-menu ????????????????????????????????????????
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
            kb.add(types.InlineKeyboardButton(f"?? Ã” ÃÊ: {search}  ? Å«ò ò—œ‰", callback_data="adm:wpe:clr"))
        else:
            kb.add(types.InlineKeyboardButton("?? Ã” ÃÊÌ ò«—»—", callback_data="adm:wpe:srch"))
        kb.add(types.InlineKeyboardButton("? «›“Êœ‰ «” À‰«", callback_data="adm:wpe:add"))
        # User rows
        for r in rows:
            name = r["full_name"] or r["username"] or str(r["user_id"])
            kb.row(
                types.InlineKeyboardButton(f"?? {name}", callback_data=f"adm:wpe:noop"),
                types.InlineKeyboardButton("? Õ–›", callback_data=f"adm:wpe:rm:{r['id']}"),
            )
        # Pagination
        nav_btns = []
        if page > 0:
            nav_btns.append(types.InlineKeyboardButton("?? ﬁ»·Ì", callback_data=f"adm:wpe:list:{page - 1}"))
        nav_btns.append(types.InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="adm:wpe:noop"))
        if page + 1 < total_pages:
            nav_btns.append(types.InlineKeyboardButton("»⁄œÌ ??", callback_data=f"adm:wpe:list:{page + 1}"))
        if nav_btns:
            kb.row(*nav_btns)
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ops", icon_custom_emoji_id="5253997076169115797"))
        return kb

    def _wpe_text(page=0, search=None):
        PER_PAGE = 8
        _rows, total = get_wallet_pay_exceptions(page=page, per_page=PER_PAGE, search=search)
        wp_fa = "? ›⁄«·" if setting_get("wallet_pay_enabled", "1") == "1" else "? €Ì—›⁄«·"
        return (
            "?? <b>Å—œ«Œ  »« „ÊÃÊœÌ ó «” À‰«Â«</b>\n\n"
            f"?? Ê÷⁄Ì  ò·Ì: {wp_fa}\n"
            f"??  ⁄œ«œ «” À‰«Â«: <b>{total}</b> ò«—»—\n\n"
            "ò«—»—«‰ „ÊÃÊœ œ— «Ì‰ ·Ì”  Õ Ì Êﬁ Ì Å—œ«Œ  »« „ÊÃÊœÌ <b>€Ì—›⁄«·</b> »«‘œ° "
            "„Ìù Ê«‰‰œ «“ òÌ› ÅÊ· «” ›«œÂ ò‰‰œ."
        )

    if data == "adm:ops:wallet_pay_exc" or data.startswith("adm:wpe:list:"):
        if not admin_has_perm(uid, "settings"):
            if call.id:
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_wallet_exc_search", back_cb="adm:ops:wallet_pay_exc")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>Ã” ÃÊÌ «” À‰«Â«</b>\n\n"
            "‰«„ ò«—»—Ì° ‰«„ ò«„· Ì« ‘‰«”Â ò«—»—Ì —« Ê«—œ ò‰Ìœ:",
            back_button("adm:ops:wallet_pay_exc"))
        return

    if data == "adm:wpe:clr":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_clear(uid)
        bot.answer_callback_query(call.id)
        send_or_edit(call, _wpe_text(0, None), _wpe_kb(0, None))
        return

    if data == "adm:wpe:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_wallet_exc_add", back_cb="adm:ops:wallet_pay_exc")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "? <b>«›“Êœ‰ «” À‰«</b>\n\n"
            "‰«„ ò«—»—Ì° ‰«„ ò«„· Ì« ‘‰«”Â ⁄œœÌ ò«—»— —« Ê«—œ ò‰Ìœ:",
            back_button("adm:ops:wallet_pay_exc"))
        return

    if data.startswith("adm:wpe:rm:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        try:
            row_id = int(data.split(":")[-1])
        except ValueError:
            bot.answer_callback_query(call.id, "Œÿ«")
            return
        remove_wallet_pay_exception(row_id)
        log_admin_action(uid, f"«” À‰« Å—œ«Œ  „ÊÃÊœÌ Õ–› ‘œ (id={row_id})")
        bot.answer_callback_query(call.id, "Õ–› ‘œ ?")
        send_or_edit(call, _wpe_text(0, None), _wpe_kb(0, None))
        return

    if data.startswith("adm:wpe:pick:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        try:
            target_uid = int(data.split(":")[-1])
        except ValueError:
            bot.answer_callback_query(call.id, "Œÿ«")
            return
        added = add_wallet_pay_exception(target_uid)
        state_clear(uid)
        if added:
            log_admin_action(uid, f"«” À‰« Å—œ«Œ  „ÊÃÊœÌ «÷«›Â ‘œ (user_id={target_uid})")
            bot.answer_callback_query(call.id, "«÷«›Â ‘œ ?")
        else:
            bot.answer_callback_query(call.id, "«Ì‰ ò«—»— ﬁ»·« œ— ·Ì”  «” .", show_alert=True)
        send_or_edit(call, _wpe_text(0, None), _wpe_kb(0, None))
        return

    # ?? Referral Settings ?????????????????????????????????????????????????????
    def _ref_settings_kb():
        sr_enabled = setting_get("referral_start_reward_enabled", "0")
        pr_enabled = setting_get("referral_purchase_reward_enabled", "0")
        sr_label = "? ›⁄«·" if sr_enabled == "1" else "? €Ì—›⁄«·"
        pr_label = "? ›⁄«·" if pr_enabled == "1" else "? €Ì—›⁄«·"
        sr_type = setting_get("referral_start_reward_type", "wallet")
        pr_type = setting_get("referral_purchase_reward_type", "wallet")
        sr_count = setting_get("referral_start_reward_count", "1")
        pr_count = setting_get("referral_purchase_reward_count", "1")
        sr_type_label = "?? òÌ› ÅÊ·" if sr_type == "wallet" else "?? ò«‰›Ìê"
        pr_type_label = "?? òÌ› ÅÊ·" if pr_type == "wallet" else "?? ò«‰›Ìê"
        reward_condition = setting_get("referral_reward_condition", "channel")
        rc_label = "?? œ⁄Ê  + ⁄÷ÊÌ  œ— ò«‰«·" if reward_condition == "channel" else "?? ›ﬁÿ œ⁄Ê  »Â —»« "

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("??  ‰ŸÌ„ »‰— «‘ —«òùê–«—Ì", callback_data="adm:ref:banner"))
        # Reward condition
        kb.add(types.InlineKeyboardButton("?? ?? ‘—ÿ œ—Ì«›  Å«œ«‘ ??", callback_data="adm:ops:noop"))
        kb.row(
            types.InlineKeyboardButton(rc_label, callback_data="adm:ref:reward_condition"),
            types.InlineKeyboardButton("‘—ÿ —ÌÊ«—œ «” «— ", callback_data="adm:ops:noop"),
        )
        # Start reward section
        kb.add(types.InlineKeyboardButton("?? ?? ÂœÌÂ «” «—  ??", callback_data="adm:ops:noop"))
        kb.row(
            types.InlineKeyboardButton(sr_label, callback_data="adm:ref:sr:toggle"),
            types.InlineKeyboardButton("Ê÷⁄Ì  ÂœÌÂ «” «— ", callback_data="adm:ops:noop"),
        )
        kb.add(types.InlineKeyboardButton(f"??  ⁄œ«œ: {sr_count} “Ì—„Ã„Ê⁄Â", callback_data="adm:ref:sr:count"))
        kb.add(types.InlineKeyboardButton(f"?? ‰Ê⁄ ÂœÌÂ: {sr_type_label}", callback_data="adm:ref:sr:type"))
        if sr_type == "wallet":
            sr_amount = setting_get("referral_start_reward_amount", "0")
            kb.add(types.InlineKeyboardButton(f"?? „»·€: {fmt_price(int(sr_amount))}  Ê„«‰", callback_data="adm:ref:sr:amount"))
        else:
            sr_pkg = setting_get("referral_start_reward_package", "")
            pkg_name = "«‰ Œ«» ‰‘œÂ"
            if sr_pkg:
                _p = get_package(int(sr_pkg)) if sr_pkg.isdigit() else None
                if _p:
                    pkg_name = _p["name"]
            kb.add(types.InlineKeyboardButton(f"?? ÅòÌÃ: {pkg_name}", callback_data="adm:ref:sr:pkg"))

        # Purchase reward section
        kb.add(types.InlineKeyboardButton("?? ?? ÂœÌÂ Œ—Ìœ ??", callback_data="adm:ops:noop"))
        kb.row(
            types.InlineKeyboardButton(pr_label, callback_data="adm:ref:pr:toggle"),
            types.InlineKeyboardButton("Ê÷⁄Ì  ÂœÌÂ Œ—Ìœ", callback_data="adm:ops:noop"),
        )
        kb.add(types.InlineKeyboardButton(f"??  ⁄œ«œ: {pr_count} Œ—Ìœ", callback_data="adm:ref:pr:count"))
        kb.add(types.InlineKeyboardButton(f"?? ‰Ê⁄ ÂœÌÂ: {pr_type_label}", callback_data="adm:ref:pr:type"))
        if pr_type == "wallet":
            pr_amount = setting_get("referral_purchase_reward_amount", "0")
            kb.add(types.InlineKeyboardButton(f"?? „»·€: {fmt_price(int(pr_amount))}  Ê„«‰", callback_data="adm:ref:pr:amount"))
        else:
            pr_pkg = setting_get("referral_purchase_reward_package", "")
            pkg_name = "«‰ Œ«» ‰‘œÂ"
            if pr_pkg:
                _p = get_package(int(pr_pkg)) if pr_pkg.isdigit() else None
                if _p:
                    pkg_name = _p["name"]
            kb.add(types.InlineKeyboardButton(f"?? ÅòÌÃ: {pkg_name}", callback_data="adm:ref:pr:pkg"))

        # Anti-spam section
        kb.add(types.InlineKeyboardButton("?? ?? ”Ì” „ ÷œ «”Å„ ??", callback_data="adm:ops:noop"))
        as_enabled = setting_get("referral_antispam_enabled", "0")
        as_label = "? ›⁄«·" if as_enabled == "1" else "? €Ì—›⁄«·"
        kb.add(types.InlineKeyboardButton(f"?? ÷œ «”Å„: {as_label}", callback_data="adm:ref:antispam"))

        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ops", icon_custom_emoji_id="5253997076169115797"))
        return kb

    def _ref_settings_text():
        sr_enabled = "? ›⁄«·" if setting_get("referral_start_reward_enabled", "0") == "1" else "? €Ì—›⁄«·"
        pr_enabled = "? ›⁄«·" if setting_get("referral_purchase_reward_enabled", "0") == "1" else "? €Ì—›⁄«·"
        reward_condition = setting_get("referral_reward_condition", "channel")
        rc_fa = "?? œ⁄Ê  + ⁄÷ÊÌ  œ— ò«‰«·" if reward_condition == "channel" else "?? ›ﬁÿ œ⁄Ê  »Â —»« "
        return (
            "?? <b> ‰ŸÌ„«  “Ì—„Ã„Ê⁄ÂùêÌ—Ì</b>\n\n"
            f"?? <b>‘—ÿ œ—Ì«›  Å«œ«‘:</b> {rc_fa}\n"
            f"?? ÂœÌÂ «” «— : {sr_enabled}\n"
            f"?? ÂœÌÂ Œ—Ìœ “Ì—„Ã„Ê⁄Â: {pr_enabled}\n\n"
            "Â— »Œ‘ —« »« œò„ÂùÂ«Ì “Ì—  ‰ŸÌ„ ò‰Ìœ."
        )

    if data == "adm:ref:settings":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:banner":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_ref_banner")
        bot.answer_callback_query(call.id)
        cur_text = setting_get("referral_banner_text", "")
        cur_photo = setting_get("referral_banner_photo", "")
        status = ""
        if cur_text:
            status += f"\n\n?? „ ‰ ›⁄·Ì:\n{esc(cur_text[:200])}"
        if cur_photo:
            status += "\n?? ⁄ò”: ? ”  ‘œÂ"
        kb = types.InlineKeyboardMarkup()
        if cur_text or cur_photo:
            kb.add(types.InlineKeyboardButton("?? Õ–› »‰— ”›«—‘Ì", callback_data="adm:ref:banner:del"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ref:settings", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b> ‰ŸÌ„ »‰— «‘ —«òùê–«—Ì</b>\n\n"
            "„ ‰ Ì« ⁄ò”+òÅ‘‰ „Ê—œ ‰Ÿ— »—«Ì «‘ —«òùê–«—Ì ·Ì‰ò œ⁄Ê  «—”«· ò‰Ìœ.\n"
            "«Ì‰ „ ‰/⁄ò” Â‰ê«„ «‘ —«òùê–«—Ì ·Ì‰ò œ⁄Ê  »Â ò«—»—«‰ ‰„«Ì‘ œ«œÂ „Ìù‘Êœ.\n\n"
            "?? ·Ì‰ò œ⁄Ê  ò«—»— »Â ’Ê—  ŒÊœò«— »Â «‰ Â«Ì „ ‰ «÷«›Â „Ìù‘Êœ."
            f"{status}", kb)
        return

    if data == "adm:ref:banner:del":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        setting_set("referral_banner_text", "")
        setting_set("referral_banner_photo", "")
        log_admin_action(uid, "»‰— «‘ —«òùê–«—Ì Õ–› ‘œ")
        bot.answer_callback_query(call.id, "»‰— ”›«—‘Ì Õ–› ‘œ.")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # Reward condition toggle
    if data == "adm:ref:reward_condition":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("referral_reward_condition", "channel")
        new_val = "start_only" if cur == "channel" else "channel"
        setting_set("referral_reward_condition", new_val)
        labels = {
            "channel":    "œ⁄Ê  + ⁄÷ÊÌ  œ— ò«‰«·",
            "start_only": "›ﬁÿ œ⁄Ê  »Â —»« ",
        }
        log_admin_action(uid, f"‘—ÿ Å«œ«‘ “Ì—„Ã„Ê⁄Â »Â ´{labels[new_val]}ª  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, f"‘—ÿ Å«œ«‘: {labels[new_val]}")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # Start reward toggles
    if data == "adm:ref:sr:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("referral_start_reward_enabled", "0")
        setting_set("referral_start_reward_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"ÂœÌÂ «” «—  “Ì—„Ã„Ê⁄Â {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:sr:count":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_ref_sr_count")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b> ⁄œ«œ “Ì—„Ã„Ê⁄Â »—«Ì ÂœÌÂ «” «— </b>\n\n"
            "«œ„Ì‰ ⁄“Ì“° Ê«—œ ò‰Ìœ »⁄œ «“ ç‰œ “Ì—„Ã„Ê⁄Â ÃœÌœ° ÂœÌÂ »Â „⁄—› œ«œÂ ‘Êœ.\n\n"
            f"„ﬁœ«— ›⁄·Ì: <b>{setting_get('referral_start_reward_count', '1')}</b>",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:sr:type":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("referral_start_reward_type", "wallet")
        new_val = "config" if cur == "wallet" else "wallet"
        setting_set("referral_start_reward_type", new_val)
        log_admin_action(uid, f"‰Ê⁄ ÂœÌÂ «” «—  »Â {'òÌ› ÅÊ·' if new_val == 'wallet' else 'ò«‰›Ìê'}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, f"‰Ê⁄ ÂœÌÂ: {'òÌ› ÅÊ·' if new_val == 'wallet' else 'ò«‰›Ìê'}")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:sr:amount":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_ref_sr_amount")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>„»·€ ‘«—é òÌ› ÅÊ· (ÂœÌÂ «” «— )</b>\n\n"
            "„»·€ »Â  Ê„«‰ Ê«—œ ò‰Ìœ:\n\n"
            f"„ﬁœ«— ›⁄·Ì: <b>{fmt_price(int(setting_get('referral_start_reward_amount', '0')))}</b>  Ê„«‰",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:sr:pkg":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ref:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>«‰ Œ«» ÅòÌÃ ÂœÌÂ «” «— </b>\n\nÅòÌÃÌ òÂ „ÌùŒÊ«ÂÌœ »Â ⁄‰Ê«‰ ÂœÌÂ œ«œÂ ‘Êœ «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("adm:ref:sr:pkgsel:"):
        pkg_id = data.split(":")[4]
        setting_set("referral_start_reward_package", pkg_id)
        log_admin_action(uid, f"ÅòÌÃ ÂœÌÂ «” «—  »Â #{pkg_id}  ‰ŸÌ„ ‘œ")
        bot.answer_callback_query(call.id, "ÅòÌÃ ÂœÌÂ «” «—   ‰ŸÌ„ ‘œ.")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # Purchase reward toggles
    if data == "adm:ref:pr:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("referral_purchase_reward_enabled", "0")
        setting_set("referral_purchase_reward_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"ÂœÌÂ Œ—Ìœ “Ì—„Ã„Ê⁄Â {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:pr:count":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_ref_pr_count")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b> ⁄œ«œ Œ—Ìœ “Ì—„Ã„Ê⁄Â »—«Ì ÂœÌÂ</b>\n\n"
            "Ê«—œ ò‰Ìœ »⁄œ «“ ç‰œ Œ—Ìœ «Ê· “Ì—„Ã„Ê⁄ÂùÂ«° ÂœÌÂ »Â „⁄—› œ«œÂ ‘Êœ.\n"
            "?? ›ﬁÿ «Ê·Ì‰ Œ—Ìœ Â— “Ì—„Ã„Ê⁄Â œ— ‰Ÿ— ê—› Â „Ìù‘Êœ.\n\n"
            f"„ﬁœ«— ›⁄·Ì: <b>{setting_get('referral_purchase_reward_count', '1')}</b>",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:pr:type":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("referral_purchase_reward_type", "wallet")
        new_val = "config" if cur == "wallet" else "wallet"
        setting_set("referral_purchase_reward_type", new_val)
        log_admin_action(uid, f"‰Ê⁄ ÂœÌÂ Œ—Ìœ »Â {'òÌ› ÅÊ·' if new_val == 'wallet' else 'ò«‰›Ìê'}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, f"‰Ê⁄ ÂœÌÂ: {'òÌ› ÅÊ·' if new_val == 'wallet' else 'ò«‰›Ìê'}")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:pr:amount":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_ref_pr_amount")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>„»·€ ‘«—é òÌ› ÅÊ· (ÂœÌÂ Œ—Ìœ)</b>\n\n"
            "„»·€ »Â  Ê„«‰ Ê«—œ ò‰Ìœ:\n\n"
            f"„ﬁœ«— ›⁄·Ì: <b>{fmt_price(int(setting_get('referral_purchase_reward_amount', '0')))}</b>  Ê„«‰",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:pr:pkg":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ref:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>«‰ Œ«» ÅòÌÃ ÂœÌÂ Œ—Ìœ</b>\n\nÅòÌÃÌ òÂ „ÌùŒÊ«ÂÌœ »Â ⁄‰Ê«‰ ÂœÌÂ œ«œÂ ‘Êœ «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("adm:ref:pr:pkgsel:"):
        pkg_id = data.split(":")[4]
        setting_set("referral_purchase_reward_package", pkg_id)
        log_admin_action(uid, f"ÅòÌÃ ÂœÌÂ Œ—Ìœ »Â #{pkg_id}  ‰ŸÌ„ ‘œ")
        bot.answer_callback_query(call.id, "ÅòÌÃ ÂœÌÂ Œ—Ìœ  ‰ŸÌ„ ‘œ.")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # ?? Anti-Spam Settings ????????????????????????????????????????????????????

    _ANTISPAM_ACTION_LABELS = {
        "report_only":  "›ﬁÿ ê“«—‘ »Â «œ„Ì‰",
        "referral_ban": "„ÕœÊœ ò«„· «“ “Ì—„Ã„Ê⁄ÂùêÌ—Ì",
        "full_ban":     "„ÕœÊœ ‘œ‰ «“ ò· —»« ",
    }
    _RESTRICTIONS_PER_PAGE = 8

    def _antispam_text():
        enabled   = setting_get("referral_antispam_enabled", "0")
        window    = setting_get("referral_antispam_window", "15")
        threshold = setting_get("referral_antispam_threshold", "10")
        action    = setting_get("referral_antispam_action", "report_only")
        captcha   = setting_get("referral_captcha_enabled", "1")
        status_fa = "? ›⁄«·" if enabled == "1" else "? €Ì—›⁄«·"
        action_fa = _ANTISPAM_ACTION_LABELS.get(action, action)
        captcha_fa = "? ›⁄«·" if captcha == "1" else "? €Ì—›⁄«·"
        return (
            "?? <b>”Ì” „ ÷œ «”Å„ “Ì—„Ã„Ê⁄ÂùêÌ—Ì</b>\n\n"
            f"?? Ê÷⁄Ì : <b>{status_fa}</b>\n"
            f"? „œ  “„«‰ »«“Â: <b>{window} À«‰ÌÂ</b>\n"
            f"?? ¬” «‰Â œ⁄Ê : <b>{threshold} œ⁄Ê </b>\n"
            f"?? ‰ ÌÃÂ œ— ’Ê—   ‘ŒÌ’: <b>{action_fa}</b>\n"
            f"?? òÅç«Ì —›—«·: <b>{captcha_fa}</b>\n\n"
            "«ê— Ìò ò«—»— œ— »«“Â “„«‰Ì  ‰ŸÌ„ù‘œÂ° »Â «‰œ«“Â ¬” «‰Â Ì« »Ì‘ — œ⁄Ê  «‰Ã«„ œÂœ° "
            "»Âù⁄‰Ê«‰ „‘òÊò ‘‰«”«ÌÌ „Ìù‘Êœ Ê «ﬁœ«„  ‰ŸÌ„ù‘œÂ «⁄„«· ŒÊ«Âœ ‘œ.\n\n"
            "?? <b>òÅç«Ì —›—«·</b>: «ê— ›⁄«· »«‘œ° ò«—»— œ⁄Ê ù‘œÂ »«Ìœ Ìò ”Ê«· —Ì«÷Ì ”«œÂ —« Õ· ò‰œ "
            " « »Â ⁄‰Ê«‰ “Ì—„Ã„Ê⁄Â „⁄ »— À»  ‘Êœ Ê Å«œ«‘ »Â œ⁄Ê ùò‰‰œÂ  ⁄·ﬁ êÌ—œ."
        )

    def _antispam_kb():
        enabled   = setting_get("referral_antispam_enabled", "0")
        window    = setting_get("referral_antispam_window", "15")
        threshold = setting_get("referral_antispam_threshold", "10")
        action    = setting_get("referral_antispam_action", "report_only")
        captcha   = setting_get("referral_captcha_enabled", "1")
        action_fa = _ANTISPAM_ACTION_LABELS.get(action, action)
        en_label  = "? ›⁄«·" if enabled == "1" else "? €Ì—›⁄«·"
        captcha_toggle_label = "€Ì— ›⁄«· ”«“Ì òÅç«" if captcha == "1" else "›⁄«· ”«“Ì òÅç«"
        kb2 = types.InlineKeyboardMarkup()
        kb2.row(
            types.InlineKeyboardButton("? ›⁄«· ò—œ‰",    callback_data="adm:ref:as:enable"),
            types.InlineKeyboardButton("? €Ì—›⁄«· ò—œ‰", callback_data="adm:ref:as:disable"),
        )
        kb2.add(types.InlineKeyboardButton(f"? „œ  “„«‰: {window} À«‰ÌÂ", callback_data="adm:ref:as:window"))
        kb2.add(types.InlineKeyboardButton(f"??  ⁄œ«œ: {threshold} œ⁄Ê ",  callback_data="adm:ref:as:threshold"))
        kb2.add(types.InlineKeyboardButton(f"??  ‰ŸÌ„ ‰ ÌÃÂ: {action_fa}", callback_data="adm:ref:as:action"))
        kb2.add(types.InlineKeyboardButton(f"?? {captcha_toggle_label}",   callback_data="adm:ref:as:captcha:toggle"))
        kb2.add(types.InlineKeyboardButton("?? „œÌ—Ì  «‘Œ«’ „ÕœÊœ ‘œÂ",   callback_data="adm:ref:restrictions:0"))
        kb2.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ref:settings",
                                            icon_custom_emoji_id="5253997076169115797"))
        return kb2

    def _restrictions_text(page):
        rows, total = get_referral_restrictions_paged(page, _RESTRICTIONS_PER_PAGE)
        total_pages = max(1, (total + _RESTRICTIONS_PER_PAGE - 1) // _RESTRICTIONS_PER_PAGE)
        t = (
            "?? <b>„œÌ—Ì  «‘Œ«’ „ÕœÊœ ‘œÂ</b>\n\n"
            f" ⁄œ«œ ò· „ÕœÊœÌ ùÂ«: <b>{total}</b>\n"
            f"’›ÕÂ <b>{page + 1}</b> «“ <b>{total_pages}</b>\n\n"
        )
        if not rows:
            t += "ÂÌç ò«—»—Ì œ— ·Ì”  „ÕœÊœÌ  ‰Ì” ."
        return t

    def _restrictions_kb(page):
        rows, total = get_referral_restrictions_paged(page, _RESTRICTIONS_PER_PAGE)
        total_pages = max(1, (total + _RESTRICTIONS_PER_PAGE - 1) // _RESTRICTIONS_PER_PAGE)
        kb2 = types.InlineKeyboardMarkup()
        kb2.add(types.InlineKeyboardButton("? «÷«›Â ò—œ‰", callback_data="adm:ref:restrictions:add"))
        for row in rows:
            rtype_fa = "?? „ÕœÊœ ò«„·" if row["restriction_type"] == "full" else "? „ÕœÊœ «“ “Ì—„Ã„Ê⁄ÂùêÌ—Ì"
            name = row["username"] and f"@{row['username']}" or row["full_name"] or str(row["user_id"])
            kb2.row(
                types.InlineKeyboardButton(f"{name[:18]}", callback_data="adm:ops:noop"),
                types.InlineKeyboardButton(rtype_fa, callback_data=f"adm:ref:restrictions:toggle:{row['user_id']}"),
                types.InlineKeyboardButton("?? Õ–›", callback_data=f"adm:ref:restrictions:rm:{row['id']}"),
            )
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton("?? ﬁ»·Ì", callback_data=f"adm:ref:restrictions:{page - 1}"))
        nav.append(types.InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="adm:ops:noop"))
        if page < total_pages - 1:
            nav.append(types.InlineKeyboardButton("?? »⁄œÌ", callback_data=f"adm:ref:restrictions:{page + 1}"))
        if nav:
            kb2.row(*nav)
        kb2.add(types.InlineKeyboardButton("»«“ê‘  »Â ÷œ «”Å„", callback_data="adm:ref:antispam",
                                            icon_custom_emoji_id="5253997076169115797"))
        return kb2

    if data == "adm:ref:antispam":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data == "adm:ref:as:enable":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        setting_set("referral_antispam_enabled", "1")
        log_admin_action(uid, "”Ì” „ ÷œ «”Å„ “Ì—„Ã„Ê⁄ÂùêÌ—Ì ›⁄«· ‘œ")
        bot.answer_callback_query(call.id, "? ”Ì” „ ÷œ «”Å„ ›⁄«· ‘œ.")
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data == "adm:ref:as:disable":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        setting_set("referral_antispam_enabled", "0")
        log_admin_action(uid, "”Ì” „ ÷œ «”Å„ “Ì—„Ã„Ê⁄ÂùêÌ—Ì €Ì—›⁄«· ‘œ")
        bot.answer_callback_query(call.id, "? ”Ì” „ ÷œ «”Å„ €Ì—›⁄«· ‘œ.")
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data == "adm:ref:as:window":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_ref_as_window")
        bot.answer_callback_query(call.id)
        cur = setting_get("referral_antispam_window", "15")
        send_or_edit(call,
            "? <b> ‰ŸÌ„ „œ  “„«‰ »«“Â (À«‰ÌÂ)</b>\n\n"
            " ⁄œ«œ À«‰ÌÂù«Ì òÂ ”Ì” „ »—«Ì ‘„«—‘ œ⁄Ê ùÂ« œ— ‰Ÿ— „ÌùêÌ—œ —« Ê«—œ ò‰Ìœ.\n\n"
            f"„ﬁœ«— ›⁄·Ì: <b>{cur} À«‰ÌÂ</b>",
            back_button("adm:ref:antispam"))
        return

    if data == "adm:ref:as:threshold":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_ref_as_threshold")
        bot.answer_callback_query(call.id)
        cur = setting_get("referral_antispam_threshold", "10")
        send_or_edit(call,
            "?? <b> ‰ŸÌ„ ¬” «‰Â  ⁄œ«œ œ⁄Ê </b>\n\n"
            " ⁄œ«œ œ⁄Ê  œ— »«“Â “„«‰Ì —« Ê«—œ ò‰Ìœ òÂ »«⁄À  ‘ŒÌ’ „‘òÊò „Ìù‘Êœ.\n\n"
            f"„ﬁœ«— ›⁄·Ì: <b>{cur} œ⁄Ê </b>",
            back_button("adm:ref:antispam"))
        return

    if data == "adm:ref:as:action":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur_action = setting_get("referral_antispam_action", "report_only")
        kb2 = types.InlineKeyboardMarkup()
        for act_key, act_fa in _ANTISPAM_ACTION_LABELS.items():
            tick = "? " if act_key == cur_action else ""
            kb2.add(types.InlineKeyboardButton(f"{tick}{act_fa}", callback_data=f"adm:ref:as:setaction:{act_key}"))
        kb2.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ref:antispam",
                                            icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b> ‰ŸÌ„ ‰ ÌÃÂ œ— ’Ê—   ‘ŒÌ’ «”Å„</b>\n\n"
            "ÌòÌ «“ ê“Ì‰ÂùÂ«Ì “Ì— —« «‰ Œ«» ò‰Ìœ:\n\n"
            "?? <b>„ÕœÊœ ò«„· «“ “Ì—„Ã„Ê⁄ÂùêÌ—Ì</b> ó ›ﬁÿ »Œ‘ œ⁄Ê  „”œÊœ „Ìù‘Êœ\n"
            "?? <b>„ÕœÊœ ‘œ‰ «“ ò· —»« </b> ó œ” —”Ì ò«„· ò«—»— ﬁÿ⁄ „Ìù‘Êœ\n"
            "?? <b>›ﬁÿ ê“«—‘ »Â «œ„Ì‰</b> ó „ÕœÊœÌ Ì «⁄„«· ‰„Ìù‘Êœ° ›ﬁÿ «œ„Ì‰ „ÿ·⁄ „Ìù‘Êœ",
            kb2)
        return

    if data.startswith("adm:ref:as:setaction:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts = data.split(":")
        new_action = parts[4] if len(parts) > 4 else ""
        if new_action not in _ANTISPAM_ACTION_LABELS:
            bot.answer_callback_query(call.id, "ê“Ì‰Â ‰«„⁄ »— «” .", show_alert=True)
            return
        setting_set("referral_antispam_action", new_action)
        log_admin_action(uid, f"‰ ÌÃÂ ÷œ «”Å„ »Â ´{_ANTISPAM_ACTION_LABELS[new_action]}ª  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, f"? ‰ ÌÃÂ: {_ANTISPAM_ACTION_LABELS[new_action]}")
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data == "adm:ref:as:captcha:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("referral_captcha_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("referral_captcha_enabled", new_val)
        state_fa = "›⁄«·" if new_val == "1" else "€Ì—›⁄«·"
        log_admin_action(uid, f"òÅç«Ì —›—«· {state_fa} ‘œ")
        bot.answer_callback_query(call.id, f"? òÅç«Ì —›—«· {state_fa} ‘œ.")
        send_or_edit(call, _antispam_text(), _antispam_kb())
        return

    if data.startswith("adm:ref:restrictions:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
                "? <b>«›“Êœ‰ ò«—»— »Â ·Ì”  „ÕœÊœÌ </b>\n\n"
                "‘‰«”Â ⁄œœÌ ò«—»— (User ID) Ì« ‰«„ ò«—»—Ì (@username) —« Ê«—œ ò‰Ìœ:",
                back_button("adm:ref:restrictions:0"))
            return

        if sub == "rm" and len(parts) > 4:
            try:
                row_id = int(parts[4])
            except ValueError:
                bot.answer_callback_query(call.id, "Œÿ« œ— ‘‰«”Â.")
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
                log_admin_action(uid, f"„ÕœÊœÌ  “Ì—„Ã„Ê⁄ÂùêÌ—Ì ò«—»— {removed_uid} Õ–› ‘œ")
                bot.answer_callback_query(call.id, "? „ÕœÊœÌ  Õ–› ‘œ.")
            else:
                bot.answer_callback_query(call.id, "?? „ÕœÊœÌ  Ì«›  ‰‘œ.")
            send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
            return

        if sub == "toggle" and len(parts) > 4:
            try:
                target_uid = int(parts[4])
            except ValueError:
                bot.answer_callback_query(call.id, "Œÿ« œ— ‘‰«”Â.")
                return
            new_type = toggle_referral_restriction_type(target_uid)
            if new_type is None:
                bot.answer_callback_query(call.id, "?? ò«—»— œ— ·Ì”  Ì«›  ‰‘œ.", show_alert=True)
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
            type_fa = "„ÕœÊœ ò«„·" if new_type == "full" else "„ÕœÊœ «“ “Ì—„Ã„Ê⁄ÂùêÌ—Ì"
            log_admin_action(uid, f"‰Ê⁄ „ÕœÊœÌ  ò«—»— {target_uid} »Â ´{type_fa}ª  €ÌÌ— ò—œ")
            bot.answer_callback_query(call.id, f"?  €ÌÌ— »Â: {type_fa}")
            send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
            return

        if sub == "pick" and len(parts) > 4:
            # adm:ref:restrictions:pick:<user_id>
            try:
                target_uid = int(parts[4])
            except ValueError:
                bot.answer_callback_query(call.id, "Œÿ« œ— ‘‰«”Â.")
                return
            # Show type selection
            kb2 = types.InlineKeyboardMarkup()
            kb2.add(types.InlineKeyboardButton(
                "? „ÕœÊœ «“ “Ì—„Ã„Ê⁄ÂùêÌ—Ì",
                callback_data=f"adm:ref:restrictions:settype:{target_uid}:referral_only"
            ))
            kb2.add(types.InlineKeyboardButton(
                "?? „ÕœÊœ ò«„· «“ —»« ",
                callback_data=f"adm:ref:restrictions:settype:{target_uid}:full"
            ))
            kb2.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:ref:restrictions:0",
                                                icon_custom_emoji_id="5253997076169115797"))
            bot.answer_callback_query(call.id)
            tgt_user = get_user(target_uid)
            name_fa = (tgt_user["full_name"] if tgt_user else "") or str(target_uid)
            send_or_edit(call,
                f"?? <b>«‰ Œ«» ‰Ê⁄ „ÕœÊœÌ </b>\n\n"
                f"ò«—»—: <b>{esc(name_fa)}</b> (<code>{target_uid}</code>)\n\n"
                "‰Ê⁄ „ÕœÊœÌ  —« «‰ Œ«» ò‰Ìœ:",
                kb2)
            return

        if sub == "settype" and len(parts) > 5:
            # adm:ref:restrictions:settype:<user_id>:<type>
            try:
                target_uid = int(parts[4])
            except ValueError:
                bot.answer_callback_query(call.id, "Œÿ« œ— ‘‰«”Â.")
                return
            rtype = parts[5]
            if rtype not in ("referral_only", "full"):
                bot.answer_callback_query(call.id, "‰Ê⁄ ‰«„⁄ »— «” .", show_alert=True)
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
            type_fa = "„ÕœÊœ «“ “Ì—„Ã„Ê⁄ÂùêÌ—Ì" if rtype == "referral_only" else "„ÕœÊœ ò«„· «“ —»« "
            log_admin_action(uid, f"„ÕœÊœÌ  ´{type_fa}ª »—«Ì ò«—»— {target_uid} «⁄„«· ‘œ")
            bot.answer_callback_query(call.id, f"? „ÕœÊœÌ  «⁄„«· ‘œ: {type_fa}")
            send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
            return

        # Fallback ó unknown sub-command
        bot.answer_callback_query(call.id)
        send_or_edit(call, _restrictions_text(0), _restrictions_kb(0))
        return

    # ?? Gateway settings ?????????????????????????????????????????????????????
    if data == "adm:set:gateways":
        kb = types.InlineKeyboardMarkup()
        for gw_key, gw_default in [
            ("card",             "?? ò«—  »Â ò«— "),
            ("crypto",           "?? «—“ œÌÃÌ «·"),
            ("tetrapay",         "?? œ—ê«Â ò«—  »Â ò«—  (TetraPay)"),
            ("swapwallet_crypto","?? œ—ê«Â ò«—  »Â ò«—  Ê «—“ œÌÃÌ «· (SwapWallet)"),
            ("tronpays_rial",    "?? œ—ê«Â ò«—  »Â ò«—  (TronPay)"),
        ]:
            enabled = setting_get(f"gw_{gw_key}_enabled", "0")
            status_icon = "??" if enabled == "1" else "??"
            gw_label = setting_get(f"gw_{gw_key}_display_name", "").strip() or gw_default
            kb.add(types.InlineKeyboardButton(f"{status_icon} {gw_label}", callback_data=f"adm:set:gw:{gw_key}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>œ—ê«ÂùÂ«Ì Å—œ«Œ </b>\n\nœ—ê«Â „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data == "adm:set:gw:card":
        enabled = setting_get("gw_card_enabled", "0")
        vis = setting_get("gw_card_visibility", "public")
        range_enabled = setting_get("gw_card_range_enabled", "0")
        display_name = setting_get("gw_card_display_name", "")
        random_amount = setting_get("gw_card_random_amount", "0")
        rotation_on = setting_get("gw_card_rotation_enabled", "0")
        enabled_label = "?? ›⁄«·" if enabled == "1" else "?? €Ì—›⁄«·"
        vis_label = "?? ⁄„Ê„Ì" if vis == "public" else "?? ò«—»—«‰ «„‰"
        range_label = "?? ›⁄«·" if range_enabled == "1" else "?? €Ì—›⁄«·"
        random_label = "?? ›⁄«·" if random_amount == "1" else "?? €Ì—›⁄«·"
        rotation_label = "?? ›⁄«·" if rotation_on == "1" else "?? €Ì—›⁄«·"
        active_cards = get_payment_cards(active_only=True)
        cards_count = len(get_payment_cards())
        fee_on = setting_get("gw_card_fee_enabled", "0") == "1"
        bonus_on = setting_get("gw_card_bonus_enabled", "0") == "1"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"Ê÷⁄Ì : {enabled_label}", callback_data="adm:gw:card:toggle"),
            types.InlineKeyboardButton(f"‰„«Ì‘: {vis_label}", callback_data="adm:gw:card:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"?? »«“Â Å—œ«Œ Ì: {range_label}", callback_data="adm:gw:card:range"))
        kb.add(types.InlineKeyboardButton(f"?? ﬁÌ„  —‰œÊ„: {random_label}", callback_data="adm:gw:card:randamt"))
        kb.add(types.InlineKeyboardButton("?? ‰«„ ‰„«Ì‘Ì œ—ê«Â", callback_data="adm:gw:card:set_name"))
        kb.add(types.InlineKeyboardButton(f"?? „œÌ—Ì  ò«— ùÂ« ({cards_count} ò«— )", callback_data="adm:gw:card:cards"))
        fee_bonus_lbl = ("?? ò«—„“œ" if fee_on else "?? ò«—„“œ") + " | " + ("?? »Ê‰”" if bonus_on else "?? »Ê‰”")
        kb.add(types.InlineKeyboardButton(f"?? »Ê‰” Ê ò«—„“œ ó {fee_bonus_lbl}", callback_data="adm:gw:card:feebonus"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        name_display = display_name or "<i>ÅÌ‘ù›—÷: ò«—  »Â ò«— </i>"
        cards_status = f"{len(active_cards)} ò«—  ›⁄«· «“ {cards_count}" if cards_count else "?? ÂÌç ò«— Ì À»  ‰‘œÂ"
        text = (
            "?? <b>œ—ê«Â ò«—  »Â ò«— </b>\n\n"
            f"Ê÷⁄Ì : {enabled_label}\n"
            f"‰„«Ì‘: {vis_label}\n"
            f"‰«„ ‰„«Ì‘Ì: {name_display}\n"
            f"?? ﬁÌ„  —‰œÊ„: {random_label}\n"
            f"?? ç—Œ‘ ò«— : {rotation_label}\n"
            f"?? ò«— ùÂ«: {cards_status}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:card:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="card")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_card_display_name", "")
        send_or_edit(call,
            f"?? <b>‰«„ ‰„«Ì‘Ì œ—ê«Â ò«—  »Â ò«— </b>\n\n"
            f"„ﬁœ«— ›⁄·Ì: <code>{esc(current or 'ÅÌ‘ù›—÷')}</code>\n\n"
            "‰«„ œ·ŒÊ«Â —« «—”«· ò‰Ìœ.\n"
            "»—«Ì »«“ê‘  »Â ÅÌ‘ù›—÷° <code>-</code> «—”«· ò‰Ìœ.",
            back_button("adm:set:gw:card"))
        return

    if data == "adm:gw:card:toggle":
        enabled = setting_get("gw_card_enabled", "0")
        setting_set("gw_card_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"œ—ê«Â ò«—  {'€Ì—›⁄«·' if enabled == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:card")
        return

    if data == "adm:gw:card:randamt":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("gw_card_random_amount", "0")
        setting_set("gw_card_random_amount", "0" if cur == "1" else "1")
        log_admin_action(uid, f"ﬁÌ„  —‰œÊ„ ò«—  {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:card")
        return

    if data == "adm:gw:card:vis":
        vis = setting_get("gw_card_visibility", "public")
        setting_set("gw_card_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"‰„«Ì‘ œ—ê«Â ò«—  »Â {'secure' if vis == 'public' else 'public'}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:card")
        return

    # ?? Card management ???????????????????????????????????????????????????????
    if data == "adm:gw:card:cards":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
        rotation_lbl = "?? ›⁄«·" if rotation_on else "?? €Ì—›⁄«·"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? «÷«›Â ò—œ‰ ò«—  ÃœÌœ", callback_data="adm:gw:card:cards:add"))
        kb.add(types.InlineKeyboardButton(f"?? —‰œ„ ò«— ùÂ«: {rotation_lbl}", callback_data="adm:gw:card:cards:rotation"))
        for c in cards:
            status = "?" if c["is_active"] else "?"
            kb.add(types.InlineKeyboardButton(
                f"{status} {c['card_number']} ó {c['bank_name'] or '»œÊ‰ ‰«„ »«‰ò'}",
                callback_data=f"adm:gw:card:cards:cfg:{c['id']}"
            ))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:set:gw:card", icon_custom_emoji_id="5253997076169115797"))
        cards_count = len(cards)
        active_count = sum(1 for c in cards if c["is_active"])
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>„œÌ—Ì  ò«— ùÂ«</b>\n\n"
            f" ⁄œ«œ ò«— ùÂ«: <b>{cards_count}</b>\n"
            f"ò«— ùÂ«Ì ›⁄«·: <b>{active_count}</b>\n"
            f"?? —‰œ„: {rotation_lbl}\n\n"
            "»—«Ì „œÌ—Ì  Â— ò«—  —ÊÌ ¬‰ »“‰Ìœ:",
            kb)
        return

    if data == "adm:gw:card:cards:rotation":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("gw_card_rotation_enabled", "0")
        setting_set("gw_card_rotation_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"ç—Œ‘ —‰œ„ ò«—  {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:gw:card:cards")
        return

    if data == "adm:gw:card:cards:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_card_add_number")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>«÷«›Â ò—œ‰ ò«—  ÃœÌœ</b>\n\n"
            "‘„«—Â ò«—  —« «—”«· ò‰Ìœ (›ﬁÿ «⁄œ«œ):",
            back_button("adm:gw:card:cards"))
        return

    if data.startswith("adm:gw:card:cards:cfg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        card_id = int(data.split(":")[-1])
        card = get_payment_card(card_id)
        if not card:
            bot.answer_callback_query(call.id, "ò«—  Ì«›  ‰‘œ.", show_alert=True)
            return
        status_lbl = "? ›⁄«·" if card["is_active"] else "? €Ì—›⁄«·"
        toggle_lbl = "? €Ì—›⁄«· ò—œ‰" if card["is_active"] else "? ›⁄«· ò—œ‰"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ „‘Œ’«  ò«— ", callback_data=f"adm:gw:card:cards:edit:{card_id}"))
        kb.add(types.InlineKeyboardButton(toggle_lbl, callback_data=f"adm:gw:card:cards:toggle:{card_id}"))
        kb.add(types.InlineKeyboardButton("?? Õ–› ò«— ", callback_data=f"adm:gw:card:cards:del:{card_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:gw:card:cards", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b> ‰ŸÌ„«  ò«— </b>\n\n"
            f"‘„«—Â: <code>{esc(card['card_number'])}</code>\n"
            f"»«‰ò: {esc(card['bank_name'] or 'ó')}\n"
            f"’«Õ» ò«— : {esc(card['holder_name'] or 'ó')}\n"
            f"Ê÷⁄Ì : {status_lbl}",
            kb)
        return

    if data.startswith("adm:gw:card:cards:toggle:"):
        card_id = int(data.split(":")[-1])
        new_state = toggle_payment_card_active(card_id)
        log_admin_action(uid, f"ò«—  {card_id} {'›⁄«·' if new_state else '€Ì—›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, "? Ê÷⁄Ì  ò«—   €ÌÌ— Ì«› .")
        _fake_call(call, f"adm:gw:card:cards:cfg:{card_id}")
        return

    if data.startswith("adm:gw:card:cards:del:"):
        card_id = int(data.split(":")[-1])
        delete_payment_card(card_id)
        log_admin_action(uid, f"ò«—  {card_id} Õ–› ‘œ")
        bot.answer_callback_query(call.id, "?? ò«—  Õ–› ‘œ.")
        _fake_call(call, "adm:gw:card:cards")
        return

    if data.startswith("adm:gw:card:cards:edit:"):
        card_id = int(data.split(":")[-1])
        card = get_payment_card(card_id)
        if not card:
            bot.answer_callback_query(call.id, "ò«—  Ì«›  ‰‘œ.", show_alert=True)
            return
        state_set(uid, "admin_card_edit_number", card_id=card_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>ÊÌ—«Ì‘ ò«— </b>\n\n"
            f"‘„«—Â ›⁄·Ì: <code>{esc(card['card_number'])}</code>\n\n"
            "‘„«—Â ò«—  ÃœÌœ —« «—”«· ò‰Ìœ:",
            back_button(f"adm:gw:card:cards:cfg:{card_id}"))
        return

    # ?? Fee / Bonus admin for all gateways ????????????????????????????????????
    _GW_NAMES_FEEBONUS = {
        "card":              "?? ò«—  »Â ò«— ",
        "crypto":            "?? «—“ œÌÃÌ «·",
        "tetrapay":          "?? TetraPay",
        "swapwallet_crypto": "?? SwapWallet",
        "tronpays_rial":     "?? TronPays",
    }

    def _feebonus_text(gw):
        fee_on    = setting_get(f"gw_{gw}_fee_enabled",    "0") == "1"
        fee_type  = setting_get(f"gw_{gw}_fee_type",   "fixed")
        fee_val   = setting_get(f"gw_{gw}_fee_value",      "0")
        bonus_on  = setting_get(f"gw_{gw}_bonus_enabled",  "0") == "1"
        bonus_type= setting_get(f"gw_{gw}_bonus_type",  "fixed")
        bonus_val = setting_get(f"gw_{gw}_bonus_value",    "0")
        type_lbl  = lambda t: "œ—’œ (%)" if t == "pct" else "„»·€ À«»  ( Ê„«‰)"
        fee_txt   = (f"{'?' if fee_on else '?'} ò«—„“œ: {type_lbl(fee_type)} ó „ﬁœ«—: {fee_val}")
        bonus_txt = (f"{'?' if bonus_on else '?'} »Ê‰”: {type_lbl(bonus_type)} ó „ﬁœ«—: {bonus_val}")
        return f"{fee_txt}\n{bonus_txt}"

    def _feebonus_kb(gw):
        kb2 = types.InlineKeyboardMarkup()
        fee_on   = setting_get(f"gw_{gw}_fee_enabled",   "0") == "1"
        bonus_on = setting_get(f"gw_{gw}_bonus_enabled", "0") == "1"
        kb2.add(types.InlineKeyboardButton(
            f"?? ò«—„“œ: {'? ›⁄«·' if fee_on else '? €Ì—›⁄«·'}",
            callback_data=f"adm:gw:{gw}:fee"
        ))
        kb2.add(types.InlineKeyboardButton(
            f"?? »Ê‰”: {'? ›⁄«·' if bonus_on else '? €Ì—›⁄«·'}",
            callback_data=f"adm:gw:{gw}:bonus"
        ))
        kb2.add(types.InlineKeyboardButton(
            "»«“ê‘ ", callback_data=f"adm:set:gw:{gw}",
            icon_custom_emoji_id="5253997076169115797"
        ))
        return kb2

    def _fee_setting_kb(gw):
        fee_on   = setting_get(f"gw_{gw}_fee_enabled",   "0") == "1"
        fee_type = setting_get(f"gw_{gw}_fee_type",   "fixed")
        kb2 = types.InlineKeyboardMarkup()
        kb2.add(types.InlineKeyboardButton(
            f"Ê÷⁄Ì : {'? ›⁄«·' if fee_on else '? €Ì—›⁄«·'}",
            callback_data=f"adm:gw:{gw}:fee:toggle"
        ))
        kb2.row(
            types.InlineKeyboardButton(
                f"{'? ' if fee_type == 'fixed' else ''}„»·€ À«» ",
                callback_data=f"adm:gw:{gw}:fee:settype:fixed"
            ),
            types.InlineKeyboardButton(
                f"{'? ' if fee_type == 'pct' else ''}œ—’œ",
                callback_data=f"adm:gw:{gw}:fee:settype:pct"
            ),
        )
        kb2.add(types.InlineKeyboardButton("??  ‰ŸÌ„ „ﬁœ«—", callback_data=f"adm:gw:{gw}:fee:setval"))
        kb2.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:gw:{gw}:feebonus",
                                           icon_custom_emoji_id="5253997076169115797"))
        return kb2

    def _bonus_setting_kb(gw):
        bonus_on   = setting_get(f"gw_{gw}_bonus_enabled",   "0") == "1"
        bonus_type = setting_get(f"gw_{gw}_bonus_type",   "fixed")
        kb2 = types.InlineKeyboardMarkup()
        kb2.add(types.InlineKeyboardButton(
            f"Ê÷⁄Ì : {'? ›⁄«·' if bonus_on else '? €Ì—›⁄«·'}",
            callback_data=f"adm:gw:{gw}:bonus:toggle"
        ))
        kb2.row(
            types.InlineKeyboardButton(
                f"{'? ' if bonus_type == 'fixed' else ''}„»·€ À«» ",
                callback_data=f"adm:gw:{gw}:bonus:settype:fixed"
            ),
            types.InlineKeyboardButton(
                f"{'? ' if bonus_type == 'pct' else ''}œ—’œ",
                callback_data=f"adm:gw:{gw}:bonus:settype:pct"
            ),
        )
        kb2.add(types.InlineKeyboardButton("??  ‰ŸÌ„ „ﬁœ«—", callback_data=f"adm:gw:{gw}:bonus:setval"))
        kb2.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:gw:{gw}:feebonus",
                                           icon_custom_emoji_id="5253997076169115797"))
        return kb2

    # feebonus entry for each gateway (adm:gw:<gw>:feebonus or adm:gw:card:feebonus)
    for _gw_fb in ("card", "crypto", "tetrapay", "swapwallet_crypto", "tronpays_rial"):
        if data == f"adm:gw:{_gw_fb}:feebonus":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            gw_lbl = _GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>»Ê‰” Ê ò«—„“œ ó {gw_lbl}</b>\n\n"
                f"{_feebonus_text(_gw_fb)}\n\n"
                "ò«—„“œ: „»·€ Ì« œ—’œ «÷«›Â »Â „»·€ ›«ò Ê— ò«—»—.\n"
                "»Ê‰”: „»·€ Ì« œ—’œ »Â òÌ› ÅÊ· ò«—»— Å” «“ Å—œ«Œ  „Ê›ﬁ.",
                _feebonus_kb(_gw_fb))
            return
        if data == f"adm:gw:{_gw_fb}:fee":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            fee_val  = setting_get(f"gw_{_gw_fb}_fee_value", "0")
            fee_type = setting_get(f"gw_{_gw_fb}_fee_type",  "fixed")
            type_lbl = "œ—’œ" if fee_type == "pct" else " Ê„«‰ À«» "
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>ò«—„“œ ó {_GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)}</b>\n\n"
                f"„ﬁœ«— ›⁄·Ì: <b>{fee_val}</b> {type_lbl}\n\n"
                "<i>ò«—„“œ »Â „»·€ ›«ò Ê— ò«—»— «÷«›Â „Ìù‘Êœ Ê „»·€ ‰Â«ÌÌ ﬁ«»· Å—œ«Œ  —«  €ÌÌ— „ÌùœÂœ.</i>",
                _fee_setting_kb(_gw_fb))
            return
        if data == f"adm:gw:{_gw_fb}:fee:toggle":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            cur = setting_get(f"gw_{_gw_fb}_fee_enabled", "0")
            setting_set(f"gw_{_gw_fb}_fee_enabled", "0" if cur == "1" else "1")
            bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
            _fake_call(call, f"adm:gw:{_gw_fb}:fee")
            return
        if data.startswith(f"adm:gw:{_gw_fb}:fee:settype:"):
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            new_type = data.split(":")[-1]
            if new_type in ("fixed", "pct"):
                setting_set(f"gw_{_gw_fb}_fee_type", new_type)
                bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
            _fake_call(call, f"adm:gw:{_gw_fb}:fee")
            return
        if data == f"adm:gw:{_gw_fb}:fee:setval":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            fee_type = setting_get(f"gw_{_gw_fb}_fee_type", "fixed")
            hint = "œ—’œ (⁄œœ »Ì‰ ?  « ???)" if fee_type == "pct" else "„»·€ »Â  Ê„«‰ (⁄œœ „À» )"
            state_set(uid, "admin_gw_set_fee_val", gw=_gw_fb)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b> ‰ŸÌ„ ò«—„“œ ó {_GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)}</b>\n\n"
                f"‰Ê⁄: {hint}\n\n"
                "„ﬁœ«— —« «—”«· ò‰Ìœ:",
                back_button(f"adm:gw:{_gw_fb}:fee"))
            return
        if data == f"adm:gw:{_gw_fb}:bonus":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            bonus_val  = setting_get(f"gw_{_gw_fb}_bonus_value", "0")
            bonus_type = setting_get(f"gw_{_gw_fb}_bonus_type",  "fixed")
            type_lbl   = "œ—’œ" if bonus_type == "pct" else " Ê„«‰ À«» "
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b>»Ê‰” ó {_GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)}</b>\n\n"
                f"„ﬁœ«— ›⁄·Ì: <b>{bonus_val}</b> {type_lbl}\n\n"
                "<i>Å” «“ Å—œ«Œ  „Ê›ﬁ «“ «Ì‰ œ—ê«Â° «Ì‰ „ﬁœ«— »Â òÌ› ÅÊ· ò«—»— «÷«›Â „Ìù‘Êœ.</i>",
                _bonus_setting_kb(_gw_fb))
            return
        if data == f"adm:gw:{_gw_fb}:bonus:toggle":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            cur = setting_get(f"gw_{_gw_fb}_bonus_enabled", "0")
            setting_set(f"gw_{_gw_fb}_bonus_enabled", "0" if cur == "1" else "1")
            bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
            _fake_call(call, f"adm:gw:{_gw_fb}:bonus")
            return
        if data.startswith(f"adm:gw:{_gw_fb}:bonus:settype:"):
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            new_type = data.split(":")[-1]
            if new_type in ("fixed", "pct"):
                setting_set(f"gw_{_gw_fb}_bonus_type", new_type)
                bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
            _fake_call(call, f"adm:gw:{_gw_fb}:bonus")
            return
        if data == f"adm:gw:{_gw_fb}:bonus:setval":
            if not admin_has_perm(uid, "settings"):
                bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
                return
            bonus_type = setting_get(f"gw_{_gw_fb}_bonus_type", "fixed")
            hint = "œ—’œ (⁄œœ »Ì‰ ?  « ???)" if bonus_type == "pct" else "„»·€ »Â  Ê„«‰ (⁄œœ „À» )"
            state_set(uid, "admin_gw_set_bonus_val", gw=_gw_fb)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"?? <b> ‰ŸÌ„ »Ê‰” ó {_GW_NAMES_FEEBONUS.get(_gw_fb, _gw_fb)}</b>\n\n"
                f"‰Ê⁄: {hint}\n\n"
                "„ﬁœ«— —« «—”«· ò‰Ìœ:",
                back_button(f"adm:gw:{_gw_fb}:bonus"))
            return

    if data == "adm:set:gw:crypto":
        enabled = setting_get("gw_crypto_enabled", "0")
        vis = setting_get("gw_crypto_visibility", "public")
        range_enabled = setting_get("gw_crypto_range_enabled", "0")
        enabled_label = "?? ›⁄«·" if enabled == "1" else "?? €Ì—›⁄«·"
        vis_label = "?? ⁄„Ê„Ì" if vis == "public" else "?? ò«—»—«‰ «„‰"
        range_label = "?? ›⁄«·" if range_enabled == "1" else "?? €Ì—›⁄«·"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"Ê÷⁄Ì : {enabled_label}", callback_data="adm:gw:crypto:toggle"),
            types.InlineKeyboardButton(f"‰„«Ì‘: {vis_label}", callback_data="adm:gw:crypto:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"?? »«“Â Å—œ«Œ Ì: {range_label}", callback_data="adm:gw:crypto:range"))
        kb.add(types.InlineKeyboardButton("?? ‰«„ ‰„«Ì‘Ì œ—ê«Â", callback_data="adm:gw:crypto:set_name"))
        kb.add(types.InlineKeyboardButton("?? »Ê‰” Ê ò«—„“œ", callback_data="adm:gw:crypto:feebonus"))
        for coin_key, coin_label in CRYPTO_COINS:
            addr = setting_get(f"crypto_{coin_key}", "")
            status_icon = "?" if addr else "?"
            comment_on  = setting_get(f"crypto_{coin_key}_comment",    "0") == "1"
            randamt_on  = setting_get(f"crypto_{coin_key}_rand_amount", "0") == "1"
            comment_lbl = "ò«„‰ : ?" if comment_on else "ò«„‰ : ??"
            randamt_lbl = "„»·€ —‰œ„: ?" if randamt_on else "„»·€ —‰œ„: ??"
            kb.row(
                types.InlineKeyboardButton(f"{status_icon} {coin_label}", callback_data=f"adm:set:cw:{coin_key}"),
                types.InlineKeyboardButton(comment_lbl,  callback_data=f"adm:gw:cw:{coin_key}:comment"),
                types.InlineKeyboardButton(randamt_lbl, callback_data=f"adm:gw:cw:{coin_key}:randamt"),
            )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        display_name_crypto = setting_get("gw_crypto_display_name", "")
        name_display_crypto = display_name_crypto or "<i>ÅÌ‘ù›—÷: «—“ œÌÃÌ «·</i>"
        text = (
            "?? <b>œ—ê«Â «—“ œÌÃÌ «·</b>\n\n"
            f"Ê÷⁄Ì : {enabled_label}\n"
            f"‰„«Ì‘: {vis_label}\n"
            f"‰«„ ‰„«Ì‘Ì: {name_display_crypto}\n\n"
            "?? <i>»« ›⁄«·ù”«“Ì <b>ò«„‰ </b> Ì« <b>„»·€ —‰œ„</b> »—«Ì Â— «—“° "
            "Â‰ê«„ ‰„«Ì‘ ’›ÕÂ Å—œ«Œ ° òœ ò«„‰   ’«œ›Ì Ê/Ì« „»·€ «—“Ì »« «—ﬁ«„ «⁄‘«—Ì —‰œ„ »Â ò«—»— ‰‘«‰ œ«œÂ „Ìù‘Êœ.</i>\n\n"
            "»—«Ì ÊÌ—«Ì‘ ¬œ—” Ê·  —ÊÌ ‰«„ «—“ »“‰Ìœ:"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:crypto:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="crypto")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_crypto_display_name", "")
        send_or_edit(call,
            f"?? <b>‰«„ ‰„«Ì‘Ì œ—ê«Â «—“ œÌÃÌ «·</b>\n\n"
            f"„ﬁœ«— ›⁄·Ì: <code>{esc(current or 'ÅÌ‘ù›—÷')}</code>\n\n"
            "‰«„ œ·ŒÊ«Â —« «—”«· ò‰Ìœ.\n"
            "»—«Ì »«“ê‘  »Â ÅÌ‘ù›—÷° <code>-</code> «—”«· ò‰Ìœ.",
            back_button("adm:set:gw:crypto"))
        return

    if data == "adm:gw:crypto:toggle":
        enabled = setting_get("gw_crypto_enabled", "0")
        setting_set("gw_crypto_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"œ—ê«Â ò—ÌÅ Ê {'€Ì—›⁄«·' if enabled == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:crypto")
        return

    if data == "adm:gw:crypto:vis":
        vis = setting_get("gw_crypto_visibility", "public")
        setting_set("gw_crypto_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"‰„«Ì‘ œ—ê«Â ò—ÌÅ Ê »Â {'secure' if vis == 'public' else 'public'}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:crypto")
        return

    if data == "adm:set:gw:tetrapay":
        enabled = setting_get("gw_tetrapay_enabled", "0")
        vis = setting_get("gw_tetrapay_visibility", "public")
        api_key = setting_get("tetrapay_api_key", "")
        mode_bot = setting_get("tetrapay_mode_bot", "1")
        mode_web = setting_get("tetrapay_mode_web", "1")
        enabled_label = "?? ›⁄«·" if enabled == "1" else "?? €Ì—›⁄«·"
        vis_label = "?? ⁄„Ê„Ì" if vis == "public" else "?? ò«—»—«‰ «„‰"
        bot_label = "?? ›⁄«·" if mode_bot == "1" else "?? €Ì—›⁄«·"
        web_label = "?? ›⁄«·" if mode_web == "1" else "?? €Ì—›⁄«·"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"Ê÷⁄Ì : {enabled_label}", callback_data="adm:gw:tetrapay:toggle"),
            types.InlineKeyboardButton(f"‰„«Ì‘: {vis_label}", callback_data="adm:gw:tetrapay:vis"),
        )
        kb.row(
            types.InlineKeyboardButton(f" ·ê—«„: {bot_label}", callback_data="adm:gw:tetrapay:mode_bot"),
            types.InlineKeyboardButton(f"„—Ê—ê—: {web_label}", callback_data="adm:gw:tetrapay:mode_web"),
        )
        range_enabled_tp = setting_get("gw_tetrapay_range_enabled", "0")
        range_label_tp = "?? ›⁄«·" if range_enabled_tp == "1" else "?? €Ì—›⁄«·"
        kb.add(types.InlineKeyboardButton(f"?? »«“Â Å—œ«Œ Ì: {range_label_tp}", callback_data="adm:gw:tetrapay:range"))
        kb.add(types.InlineKeyboardButton("?? ‰«„ ‰„«Ì‘Ì œ—ê«Â", callback_data="adm:gw:tetrapay:set_name"))
        kb.add(types.InlineKeyboardButton("?? »Ê‰” Ê ò«—„“œ", callback_data="adm:gw:tetrapay:feebonus"))
        kb.add(types.InlineKeyboardButton("??  ‰ŸÌ„ ò·Ìœ API", callback_data="adm:set:tetrapay_key"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("?? œ—Ì«›  ò·Ìœ API «“ ”«Ì  TetraPay", url="https://tetra98.com"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        if api_key:
            key_display = f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>"
        else:
            key_display = "? <b>À»  ‰‘œÂ</b> ó «» œ« «“ ”«Ì  TetraPay ò·Ìœ API ŒÊœ —« œ—Ì«›  ò‰Ìœ"
        display_name_tp = setting_get("gw_tetrapay_display_name", "")
        name_display_tp = display_name_tp or "<i>ÅÌ‘ù›—÷: œ—ê«Â ò«—  »Â ò«—  (TetraPay)</i>"
        text = (
            "?? <b>œ—ê«Â ò«—  »Â ò«—  (TetraPay)</b>\n\n"
            f"Ê÷⁄Ì : {enabled_label}\n"
            f"‰„«Ì‘: {vis_label}\n"
            f"‰«„ ‰„«Ì‘Ì: {name_display_tp}\n\n"
            f"?? Å—œ«Œ  «“  ·ê—«„: {bot_label}\n"
            f"?? Å—œ«Œ  «“ „—Ê—ê—: {web_label}\n\n"
            f"ò·Ìœ API: {key_display}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:tetrapay:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="tetrapay")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_tetrapay_display_name", "")
        send_or_edit(call,
            f"?? <b>‰«„ ‰„«Ì‘Ì œ—ê«Â TetraPay</b>\n\n"
            f"„ﬁœ«— ›⁄·Ì: <code>{esc(current or 'ÅÌ‘ù›—÷')}</code>\n\n"
            "‰«„ œ·ŒÊ«Â —« «—”«· ò‰Ìœ.\n"
            "»—«Ì »«“ê‘  »Â ÅÌ‘ù›—÷° <code>-</code> «—”«· ò‰Ìœ.",
            back_button("adm:set:gw:tetrapay"))
        return

    if data == "adm:gw:tetrapay:toggle":
        enabled = setting_get("gw_tetrapay_enabled", "0")
        setting_set("gw_tetrapay_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"œ—ê«Â   —«ÅÌ {'€Ì—›⁄«·' if enabled == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:vis":
        vis = setting_get("gw_tetrapay_visibility", "public")
        setting_set("gw_tetrapay_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"‰„«Ì‘ œ—ê«Â   —«ÅÌ »Â {'secure' if vis == 'public' else 'public'}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:mode_bot":
        cur = setting_get("tetrapay_mode_bot", "1")
        setting_set("tetrapay_mode_bot", "0" if cur == "1" else "1")
        log_admin_action(uid, f"Õ«·  bot   —«ÅÌ {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:mode_web":
        cur = setting_get("tetrapay_mode_web", "1")
        setting_set("tetrapay_mode_web", "0" if cur == "1" else "1")
        log_admin_action(uid, f"Õ«·  web   —«ÅÌ {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:set:tetrapay_key":
        state_set(uid, "admin_set_tetrapay_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ò·Ìœ API   —«ÅÌ —« «—”«· ò‰Ìœ:", back_button("adm:set:gw:tetrapay"))
        return

    if data == "adm:set:gw:swapwallet_crypto":
        from ..gateways.swapwallet_crypto import NETWORK_LABELS as SW_CRYPTO_LABELS
        enabled  = setting_get("gw_swapwallet_crypto_enabled", "0")
        vis      = setting_get("gw_swapwallet_crypto_visibility", "public")
        api_key  = setting_get("swapwallet_crypto_api_key", "")
        username = setting_get("swapwallet_crypto_username", "")
        enabled_label = "?? ›⁄«·" if enabled == "1" else "?? €Ì—›⁄«·"
        vis_label     = "?? ⁄„Ê„Ì" if vis == "public" else "?? ò«—»—«‰ «„‰"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"Ê÷⁄Ì : {enabled_label}", callback_data="adm:gw:swapwallet_crypto:toggle"),
            types.InlineKeyboardButton(f"‰„«Ì‘: {vis_label}",    callback_data="adm:gw:swapwallet_crypto:vis"),
        )
        range_en = setting_get("gw_swapwallet_crypto_range_enabled", "0")
        range_label = "?? ›⁄«·" if range_en == "1" else "?? €Ì—›⁄«·"
        kb.add(types.InlineKeyboardButton(f"?? »«“Â Å—œ«Œ Ì: {range_label}", callback_data="adm:gw:swapwallet_crypto:range"))
        kb.add(types.InlineKeyboardButton("??  ‰ŸÌ„ ò·Ìœ API",        callback_data="adm:set:swapwallet_crypto_key"))
        kb.add(types.InlineKeyboardButton("?? ‰«„ ò«—»—Ì ›—Ê‘ê«Â",     callback_data="adm:set:swapwallet_crypto_username"))
        kb.add(types.InlineKeyboardButton("?? ‰«„ ‰„«Ì‘Ì œ—ê«Â", callback_data="adm:gw:swapwallet_crypto:set_name"))
        kb.add(types.InlineKeyboardButton("?? »Ê‰” Ê ò«—„“œ", callback_data="adm:gw:swapwallet_crypto:feebonus"))
        kb.add(types.InlineKeyboardButton("?? «—“Â«Ì ›⁄«·", callback_data="adm:set:swc_currencies"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("?? œ—Ì«›  ò·Ìœ API «“ ”Ê«Å Ê· ", url="https://swapwallet.app"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        key_display = f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>" if api_key else "? <b>À»  ‰‘œÂ ó «·“«„Ì</b>"
        user_status = "? À»  ‘œÂ" if username else "? À»  ‰‘œÂ"
        display_name_sw = setting_get("gw_swapwallet_crypto_display_name", "")
        name_display_sw = display_name_sw or "<i>ÅÌ‘ù›—÷: œ—ê«Â ò«—  »Â ò«—  Ê «—“ œÌÃÌ «· (SwapWallet)</i>"
        text = (
            "?? <b>œ—ê«Â ò«—  »Â ò«—  Ê «—“ œÌÃÌ «· (SwapWallet)</b>\n\n"
            f"Ê÷⁄Ì : {enabled_label}\n"
            f"‰„«Ì‘: {vis_label}\n"
            f"‰«„ ‰„«Ì‘Ì: {name_display_sw}\n\n"
            f"?? ‰«„ ò«—»—Ì Application: <code>{esc(username or 'À»  ‰‘œÂ')}</code> {user_status}\n"
            f"?? ò·Ìœ API: {key_display}\n\n"
            "?? <b>‘»òÂùÂ«Ì Å‘ Ì»«‰Ì:</b> TRON ∑ TON ∑ BSC\n\n"
            "?? <b>„—«Õ· —«Âù«‰œ«“Ì:</b>\n"
            "1?? œ— „Ì‰Ìù«Å ”Ê«ÅùÊ·  «” «—  »“‰Ìœ:\n"
            "   ?? @SwapWalletBot\n"
            "2?? œ— Å‰· »Ì“‰” »«  ·ê—«„ ·«êÌ‰ ò‰Ìœ:\n"
            "   ?? business.swapwallet.app\n"
            "3?? Ìò ›—Ê‘ê«Â ÃœÌœ »”«“Ìœ\n"
            "4?? <b>‰«„ ›—Ê‘ê«Â</b> —Ê »Â ⁄‰Ê«‰ ‰«„ ò«—»—Ì «Ì‰Ã« Ê«—œ ò‰Ìœ\n"
            "5?? «“  » <b>Å—Ê›«Ì· ? ò·Ìœ API</b> ò·Ìœ »êÌ—Ìœ Ê Ê«—œ ò‰Ìœ"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:swapwallet_crypto:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="swapwallet_crypto")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_swapwallet_crypto_display_name", "")
        send_or_edit(call,
            f"?? <b>‰«„ ‰„«Ì‘Ì œ—ê«Â SwapWallet</b>\n\n"
            f"„ﬁœ«— ›⁄·Ì: <code>{esc(current or 'ÅÌ‘ù›—÷')}</code>\n\n"
            "‰«„ œ·ŒÊ«Â —« «—”«· ò‰Ìœ.\n"
            "»—«Ì »«“ê‘  »Â ÅÌ‘ù›—÷° <code>-</code> «—”«· ò‰Ìœ.",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:gw:swapwallet_crypto:toggle":
        enabled = setting_get("gw_swapwallet_crypto_enabled", "0")
        setting_set("gw_swapwallet_crypto_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"œ—ê«Â ”Ê«ÅùÊ·  ò—ÌÅ Ê {'€Ì—›⁄«·' if enabled == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:swapwallet_crypto")
        return

    if data == "adm:gw:swapwallet_crypto:vis":
        vis = setting_get("gw_swapwallet_crypto_visibility", "public")
        setting_set("gw_swapwallet_crypto_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"‰„«Ì‘ œ—ê«Â ”Ê«ÅùÊ·  ò—ÌÅ Ê »Â {'secure' if vis == 'public' else 'public'}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:swapwallet_crypto")
        return

    if data == "adm:set:swapwallet_crypto_key":
        state_set(uid, "admin_set_swapwallet_crypto_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>ò·Ìœ API (SwapWallet ò—ÌÅ Ê) —« «—”«· ò‰Ìœ</b>\n\n"
            "›—„ : <code>apikey-xxx...</code>\n\n"
            "?? »—«Ì œ—Ì«› :\n"
            "«Å ”Ê«ÅùÊ·  ? Å—Ê›«Ì· ? <b>ò·Ìœ API</b>",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:set:swapwallet_crypto_username":
        state_set(uid, "admin_set_swapwallet_crypto_username")
        bot.answer_callback_query(call.id)
        current = setting_get("swapwallet_crypto_username", "")
        send_or_edit(call,
            f"?? <b>‰«„ ò«—»—Ì ›—Ê‘ê«Â (SwapWallet ò—ÌÅ Ê) —« «—”«· ò‰Ìœ</b>\n\n"
            f"«Ì‰ Â„«‰ <b>‰«„ ›—Ê‘ê«Â</b> ‘„« œ— Å‰· »Ì“‰” «” .\n"
            f"„ﬁœ«— ›⁄·Ì: <code>{esc(current or 'À»  ‰‘œÂ')}</code>",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:set:gw:tronpays_rial":
        enabled = setting_get("gw_tronpays_rial_enabled", "0")
        vis     = setting_get("gw_tronpays_rial_visibility", "public")
        api_key = setting_get("tronpays_rial_api_key", "")
        enabled_label = "?? ›⁄«·" if enabled == "1" else "?? €Ì—›⁄«·"
        vis_label     = "?? ⁄„Ê„Ì" if vis == "public" else "?? ò«—»—«‰ «„‰"
        range_en      = setting_get("gw_tronpays_rial_range_enabled", "0")
        range_label   = "?? ›⁄«·" if range_en == "1" else "?? €Ì—›⁄«·"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"Ê÷⁄Ì : {enabled_label}", callback_data="adm:gw:tronpays_rial:toggle"),
            types.InlineKeyboardButton(f"‰„«Ì‘: {vis_label}",     callback_data="adm:gw:tronpays_rial:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"?? »«“Â Å—œ«Œ Ì: {range_label}", callback_data="adm:gw:tronpays_rial:range"))
        kb.add(types.InlineKeyboardButton("??  ‰ŸÌ„ ò·Ìœ API", callback_data="adm:set:tronpays_rial_key"))
        kb.add(types.InlineKeyboardButton("??  ‰ŸÌ„ Callback URL", callback_data="adm:set:tronpays_rial_cb_url"))
        kb.add(types.InlineKeyboardButton("?? ‰«„ ‰„«Ì‘Ì œ—ê«Â", callback_data="adm:gw:tronpays_rial:set_name"))
        kb.add(types.InlineKeyboardButton("?? »Ê‰” Ê ò«—„“œ", callback_data="adm:gw:tronpays_rial:feebonus"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("?? œ—Ì«›  API Key «“ @TronPaysBot", url="https://t.me/TronPaysBot"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:set:gateways", icon_custom_emoji_id="5253997076169115797"))
        key_display = (f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>"
                       if api_key else "? <b>À»  ‰‘œÂ</b> ó «» œ« «“ —»«  @TronPaysBot ò·Ìœ API œ—Ì«›  ò‰Ìœ")
        cb_url = setting_get("tronpays_rial_callback_url", "").strip() or "https://example.com/"
        display_name_tp_rial = setting_get("gw_tronpays_rial_display_name", "")
        name_display_tp_rial = display_name_tp_rial or "<i>ÅÌ‘ù›—÷: œ—ê«Â ò«—  »Â ò«—  (TronPay)</i>"
        text = (
            "?? <b>œ—ê«Â ò«—  »Â ò«—  (TronPay)</b>\n\n"
            f"Ê÷⁄Ì : {enabled_label}\n"
            f"‰„«Ì‘: {vis_label}\n"
            f"‰«„ ‰„«Ì‘Ì: {name_display_tp_rial}\n\n"
            f"?? ò·Ìœ API: {key_display}\n"
            f"?? Callback URL: <code>{esc(cb_url)}</code>\n\n"
            "?? <b>—«Â‰„«Ì œ—Ì«›  API Key:</b>\n"
            "?. —»«  @TronPaysBot —« «” «—  ò‰Ìœ\n"
            "?. À» ù‰«„ Ê «Õ—«“ ÂÊÌ  —«  ò„Ì· ò‰Ìœ\n"
            "?. ò·Ìœ API —« «“ Å—Ê›«Ì· œ—Ì«›  ò‰Ìœ"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:tronpays_rial:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="tronpays_rial")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_tronpays_rial_display_name", "")
        send_or_edit(call,
            f"?? <b>‰«„ ‰„«Ì‘Ì œ—ê«Â TronPay</b>\n\n"
            f"„ﬁœ«— ›⁄·Ì: <code>{esc(current or 'ÅÌ‘ù›—÷')}</code>\n\n"
            "‰«„ œ·ŒÊ«Â —« «—”«· ò‰Ìœ.\n"
            "»—«Ì »«“ê‘  »Â ÅÌ‘ù›—÷° <code>-</code> «—”«· ò‰Ìœ.",
            back_button("adm:set:gw:tronpays_rial"))
        return

    if data == "adm:gw:tronpays_rial:toggle":
        enabled = setting_get("gw_tronpays_rial_enabled", "0")
        setting_set("gw_tronpays_rial_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"œ—ê«Â  —Ê‰ùÅÌ“ —Ì«·Ì {'€Ì—›⁄«·' if enabled == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:tronpays_rial")
        return

    if data == "adm:gw:tronpays_rial:vis":
        vis = setting_get("gw_tronpays_rial_visibility", "public")
        setting_set("gw_tronpays_rial_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"‰„«Ì‘ œ—ê«Â  —Ê‰ùÅÌ“ —Ì«·Ì »Â {'secure' if vis == 'public' else 'public'}  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:gw:tronpays_rial")
        return

    if data == "adm:set:tronpays_rial_key":
        state_set(uid, "admin_set_tronpays_rial_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ò·Ìœ API TronPays —« «—”«· ò‰Ìœ:", back_button("adm:set:gw:tronpays_rial"))
        return

    if data == "adm:set:tronpays_rial_cb_url":
        state_set(uid, "admin_set_tronpays_rial_cb_url")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>Callback URL œ—ê«Â TronPays</b>\n\n"
            "Ìò URL „⁄ »— «—”«· ò‰Ìœ („À·« ¬œ—” ”«Ì  Ì« Ê»ÂÊò ‘„«).\n"
            "«ê— ‰œ«—Ìœ° <code>https://example.com/</code> —« »›—” Ìœ.",
            back_button("adm:set:gw:tronpays_rial"))
        return

    _GW_RANGE_LABELS = {"card": "?? ò«—  »Â ò«— ", "crypto": "?? «—“ œÌÃÌ «·", "tetrapay": "?? TetraPay", "swapwallet": "?? SwapWallet", "swapwallet_crypto": "?? SwapWallet ò—ÌÅ Ê", "tronpays_rial": "?? TronPays"}

    if data.startswith("adm:gw:") and data.endswith(":range"):
        gw_name = data.split(":")[2]
        gw_label = _GW_RANGE_LABELS.get(gw_name, gw_name)
        range_enabled = setting_get(f"gw_{gw_name}_range_enabled", "0")
        range_min = setting_get(f"gw_{gw_name}_range_min", "")
        range_max = setting_get(f"gw_{gw_name}_range_max", "")
        enabled_label = "?? ›⁄«·" if range_enabled == "1" else "?? €Ì—›⁄«·"
        min_label = fmt_price(int(range_min)) + "  Ê„«‰" if range_min else "»œÊ‰ Õœ«ﬁ·"
        max_label = fmt_price(int(range_max)) + "  Ê„«‰" if range_max else "»œÊ‰ Õœ«òÀ—"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"Ê÷⁄Ì  »«“Â: {enabled_label}", callback_data=f"adm:gw:{gw_name}:range:toggle"))
        kb.add(types.InlineKeyboardButton("??  ‰ŸÌ„ »«“Â", callback_data=f"adm:gw:{gw_name}:range:set"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:set:gw:{gw_name}", icon_custom_emoji_id="5253997076169115797"))
        text = (
            f"?? <b>»«“Â Å—œ«Œ Ì ó {gw_label}</b>\n\n"
            f"Ê÷⁄Ì : {enabled_label}\n"
            f"Õœ«ﬁ· „»·€: {min_label}\n"
            f"Õœ«òÀ— „»·€: {max_label}\n\n"
            "?? «ê— »«“Â ›⁄«· »«‘œ° «Ì‰ œ—ê«Â ›ﬁÿ »—«Ì „»«·€ œ«Œ· »«“Â ‰„«Ì‘ œ«œÂ „Ìù‘Êœ."
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:gw:") and data.endswith(":range:toggle"):
        gw_name = data.split(":")[2]
        cur = setting_get(f"gw_{gw_name}_range_enabled", "0")
        setting_set(f"gw_{gw_name}_range_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"»«“Â „»·€ œ—ê«Â {gw_name} {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, f"adm:gw:{gw_name}:range")
        return

    if data.startswith("adm:gw:") and data.endswith(":range:set"):
        gw_name = data.split(":")[2]
        state_set(uid, "admin_gw_range_min", gw=gw_name)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>Õœ«ﬁ· „»·€</b> ( Ê„«‰) —« Ê«—œ ò‰Ìœ.\n\n"
            "»—«Ì <b>»œÊ‰ Õœ«ﬁ·</b>° ⁄œœ <code>0</code> Ì« <code>-</code> «—”«· ò‰Ìœ:",
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
        send_or_edit(call, "?? ‘„«—Â ò«—  —« «—”«· ò‰Ìœ:", back_button("adm:set:gw:card"))
        return

    if data == "adm:set:bank":
        state_set(uid, "admin_set_bank")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ‰«„ »«‰ò —« «—”«· ò‰Ìœ:", back_button("adm:set:gw:card"))
        return

    if data == "adm:set:owner":
        state_set(uid, "admin_set_owner")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ‰«„ Ê ‰«„ Œ«‰Ê«œêÌ ’«Õ» ò«—  —« «—”«· ò‰Ìœ:", back_button("adm:set:gw:card"))
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
            f"?? ¬œ—” Ê·  <b>{coin_label}</b> —« Ê«—œ ò‰Ìœ.\n"
            f"¬œ—” ›⁄·Ì: <code>{esc(current or 'À»  ‰‘œÂ')}</code>\n\n"
            "»—«Ì Õ–›° ⁄œœ <code>-</code> »›—” Ìœ.",
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
            bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
            _fake_call(call, "adm:set:gw:crypto")
            return

    if data == "adm:set:channel":
        current = setting_get("channel_id", "")
        state_set(uid, "admin_set_channel")
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"?? <b>ò«‰«· ﬁ›·</b>\n\n"
            f"ò«‰«· ›⁄·Ì: {esc(current or 'À»  ‰‘œÂ')}\n\n"
            "@username ò«‰«· —« Ê«—œ ò‰Ìœ\n"
            "»—«Ì €Ì—›⁄«· ò—œ‰° <code>-</code> »›—” Ìœ\n\n"
            "?? —»«  »«Ìœ «œ„Ì‰ ò«‰«· »«‘œ",
            back_button("admin:settings")
        )
        return

    if data == "adm:bot_texts":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ „ ‰ «” «— ", callback_data="adm:set:start_text"))
        kb.add(types.InlineKeyboardButton("?? ﬁÊ«‰Ì‰ Œ—Ìœ",        callback_data="adm:set:rules"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>„ ‰ùÂ«Ì —»« </b>\n\nÌòÌ «“ „Ê«—œ “Ì— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data == "adm:set:start_text":
        current = setting_get("start_text", "")
        state_set(uid, "admin_set_start_text")
        bot.answer_callback_query(call.id)
        preview = esc(current[:200]) + "..." if len(current) > 200 else esc(current or "ÅÌ‘ù›—÷")
        send_or_edit(
            call,
            f"?? <b>ÊÌ—«Ì‘ „ ‰ «” «— </b>\n\n"
            f"„ ‰ ›⁄·Ì:\n{preview}\n\n"
            "„ ‰ ÃœÌœ —« «—”«· ò‰Ìœ. „Ìù Ê«‰Ìœ «“  êùÂ«Ì HTML «” ›«œÂ ò‰Ìœ.\n"
            "»—«Ì »«“ê‘  »Â „ ‰ ÅÌ‘ù›—÷° <code>-</code> »›—” Ìœ.",
            back_button("adm:bot_texts")
        )
        return

    # ?? Admin: Locked Channels Management ????????????????????????????????????
    if data == "adm:locked_channels":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, *_build_locked_channels_menu())
        return

    if data == "adm:lch:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_add_locked_channel")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>«›“Êœ‰ ò«‰«· ﬁ›·</b>\n\n"
            "¬ÌœÌ ò«‰«· Ì« ê—ÊÂ —« Ê«—œ ò‰Ìœ.\n"
            "„À«·: <code>@channelname</code> Ì« <code>-100123456789</code>\n\n"
            "?? —»«  »«Ìœ ⁄÷Ê/«œ„Ì‰ ò«‰«· »«‘œ.",
            back_button("adm:locked_channels"))
        return

    if data.startswith("adm:lch:del:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        row_id = int(data.split(":")[3])
        remove_locked_channel_by_id(row_id)
        _invalidate_channel_cache()
        bot.answer_callback_query(call.id, "? ò«‰«· Õ–› ‘œ.")
        send_or_edit(call, *_build_locked_channels_menu())
        return

    # ?? Admin: SwapWallet active currencies ???????????????????????????????????
    if data == "adm:set:swc_currencies":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        from ..gateways.swapwallet_crypto import SWAPWALLET_CRYPTO_NETWORKS, NETWORK_LABELS as SW_NET_LABELS
        active_str = setting_get("swapwallet_active_currencies", "TRON,TON,BSC")
        active_set = {x.strip().upper() for x in active_str.split(",") if x.strip()}
        kb = types.InlineKeyboardMarkup()
        for net, _ in SWAPWALLET_CRYPTO_NETWORKS:
            check = "?" if net in active_set else "?"
            kb.add(types.InlineKeyboardButton(
                f"{check} {SW_NET_LABELS.get(net, net)}",
                callback_data=f"adm:swc:cur:{net}"
            ))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:set:gw:swapwallet_crypto", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>«—“Â«Ì ›⁄«· SwapWallet</b>\n\n"
            "‘»òÂùÂ«ÌÌ òÂ ò«—»— „Ìù Ê«‰œ »—«Ì Å—œ«Œ  «‰ Œ«» ò‰œ:\n"
            "? = ›⁄«·  |  ? = €Ì—›⁄«·", kb)
        return

    if data.startswith("adm:swc:cur:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        net_toggle = data.split(":")[3].upper()
        active_str = setting_get("swapwallet_active_currencies", "TRON,TON,BSC")
        active_set = {x.strip().upper() for x in active_str.split(",") if x.strip()}
        if net_toggle in active_set:
            active_set.discard(net_toggle)
        else:
            active_set.add(net_toggle)
        setting_set("swapwallet_active_currencies", ",".join(sorted(active_set)))
        bot.answer_callback_query(call.id, f"? {net_toggle} {'›⁄«·' if net_toggle in active_set else '€Ì—›⁄«·'} ‘œ.")
        # Reload same menu
        from ..gateways.swapwallet_crypto import SWAPWALLET_CRYPTO_NETWORKS, NETWORK_LABELS as SW_NET_LABELS
        active_str2 = setting_get("swapwallet_active_currencies", "TRON,TON,BSC")
        active_set2 = {x.strip().upper() for x in active_str2.split(",") if x.strip()}
        kb = types.InlineKeyboardMarkup()
        for net, _ in SWAPWALLET_CRYPTO_NETWORKS:
            check = "?" if net in active_set2 else "?"
            kb.add(types.InlineKeyboardButton(f"{check} {SW_NET_LABELS.get(net, net)}", callback_data=f"adm:swc:cur:{net}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:set:gw:swapwallet_crypto", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>«—“Â«Ì ›⁄«· SwapWallet</b>\n\n"
            "‘»òÂùÂ«ÌÌ òÂ ò«—»— „Ìù Ê«‰œ »—«Ì Å—œ«Œ  «‰ Œ«» ò‰œ:\n"
            "? = ›⁄«·  |  ? = €Ì—›⁄«·", kb)
        return

    # ?? Admin: Free Test Settings ?????????????????????????????????????????????
    if data == "adm:set:freetest":
        ft_mode = setting_get("free_test_mode", "everyone")
        agent_limit = setting_get("agent_test_limit", "0")
        agent_period = setting_get("agent_test_period", "day")
        period_labels = {"day": "—Ê“", "week": "Â› Â", "month": "„«Â"}
        mode_labels = {"everyone": "?? Â„Â ò«—»—«‰", "agents_only": "?? ›ﬁÿ ‰„«Ì‰œê«‰", "disabled": "?? €Ì—›⁄«·"}
        mode_label = mode_labels.get(ft_mode, ft_mode)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"?? Ê÷⁄Ì : {mode_label}", callback_data="adm:ft:toggle"))
        kb.add(types.InlineKeyboardButton("?? —Ì”   ”  —«Ìê«‰ Â„Â ò«—»—«‰", callback_data="adm:ft:reset"))
        kb.add(types.InlineKeyboardButton(f"??  ⁄œ«œ  ”  Â„ò«—«‰: {agent_limit} œ— {period_labels.get(agent_period, agent_period)}", callback_data="adm:ft:agent"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"?? <b> ‰ŸÌ„«   ”  —«Ìê«‰</b>\n\n"
            f"Ê÷⁄Ì : {mode_label}\n"
            f" ”  Â„ò«—«‰: <b>{agent_limit}</b> ⁄œœ œ— {period_labels.get(agent_period, agent_period)}",
            kb
        )
        return

    if data == "adm:ft:toggle":
        ft_mode = setting_get("free_test_mode", "everyone")
        cycle = {"everyone": "agents_only", "agents_only": "disabled", "disabled": "everyone"}
        new_mode = cycle.get(ft_mode, "everyone")
        setting_set("free_test_mode", new_mode)
        mode_labels_fa = {"everyone": "Â„Â ò«—»—«‰", "agents_only": "›ﬁÿ ‰„«Ì‰œê«‰", "disabled": "€Ì—›⁄«·"}
        log_admin_action(uid, f" ”  —«Ìê«‰ »Â Õ«·  '{mode_labels_fa.get(new_mode, new_mode)}'  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:freetest")
        return

    if data == "adm:ft:reset":
        reset_all_free_tests()
        bot.answer_callback_query(call.id, "?  ”  —«Ìê«‰ Â„Â ò«—»—«‰ —Ì”  ‘œ.", show_alert=True)
        _fake_call(call, "adm:set:freetest")
        return

    if data == "adm:ft:agent":
        state_set(uid, "admin_set_agent_test_limit")
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            "?? <b> ⁄œ«œ  ”  Â„ò«—«‰</b>\n\n"
            " ⁄œ«œ  ”  —«Ìê«‰ Â„ò«—«‰ —« Ê«—œ ò‰Ìœ.\n"
            "›—„ : <code> ⁄œ«œ »«“Â</code>\n\n"
            "„À«·:\n"
            "<code>5 day</code> ? ?  ”  œ— —Ê“\n"
            "<code>10 week</code> ? ??  ”  œ— Â› Â\n"
            "<code>20 month</code> ? ??  ”  œ— „«Â\n\n"
            "»—«Ì €Ì—›⁄«· ò—œ‰ „ÕœÊœÌ ° <code>0</code> »›—” Ìœ.",
            back_button("adm:set:freetest")
        )
        return

    # ?? Admin: Phone Collection Settings ?????????????????????????????????????
    if data == "adm:set:phone":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        phone_mode = setting_get("phone_mode", "disabled")
        iran_only  = setting_get("phone_iran_only", "0")
        mode_labels = {
            "disabled":     "?? €Ì—›⁄«·",
            "everyone":     "?? Â„Â ò«—»—«‰",
            "agents_only":  "?? ›ﬁÿ ‰„«Ì‰œê«‰",
            "trusted_only": "?? ò«—»—«‰ „ÿ„∆‰",
            "card_only":    "?? Â‰ê«„ Å—œ«Œ  ò«— ",
        }
        mode_cycle = {
            "disabled":     "everyone",
            "everyone":     "agents_only",
            "agents_only":  "trusted_only",
            "trusted_only": "card_only",
            "card_only":    "disabled",
        }
        mode_label = mode_labels.get(phone_mode, phone_mode)
        iran_label = "?? ›⁄«· (›ﬁÿ «Ì—«‰Ì)" if iran_only == "1" else "?? €Ì—›⁄«· (Â— ‘„«—Â)"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"?? Õ«·  Ã„⁄ù¬Ê—Ì: {mode_label}", callback_data="adm:phone:toggle_mode"))
        kb.add(types.InlineKeyboardButton(f"???? «⁄ »«—”‰ÃÌ «Ì—«‰Ì: {iran_label}", callback_data="adm:phone:toggle_iran"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b> ‰ŸÌ„«  Ã„⁄ù¬Ê—Ì ‘„«—Â  ·›‰</b>\n\n"
            f"Õ«· : {mode_label}\n"
            f"«⁄ »«—”‰ÃÌ «Ì—«‰: {iran_label}\n\n"
            "Õ«· ùÂ«Ì Ã„⁄ù¬Ê—Ì:\n"
            "ï <b>€Ì—›⁄«·</b> ó ‘„«—Â Ã„⁄ù¬Ê—Ì ‰„Ìù‘Êœ\n"
            "ï <b>Â„Â ò«—»—«‰</b> ó Â„Â »«Ìœ ‘„«—Â »œÂ‰œ\n"
            "ï <b>›ﬁÿ ‰„«Ì‰œê«‰</b> ó ›ﬁÿ ‰„«Ì‰œê«‰ ‘„«—Â „ÌùœÂ‰œ\n"
            "ï <b>ò«—»—«‰ „ÿ„∆‰</b> ó ›ﬁÿ ò«—»—«‰ »« Ê÷⁄Ì  ´«„‰ª\n"
            "ï <b>Â‰ê«„ Å—œ«Œ  ò«— </b> ó ﬁ»· «“ Å—œ«Œ  ò«—  »Â ò«— ",
            kb)
        return

    if data == "adm:phone:toggle_mode":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
        log_admin_action(uid, f"Õ«·  Ã„⁄ù¬Ê—Ì ‘„«—Â  ·›‰ »Â '{new_mode}'  €ÌÌ— ò—œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:phone")
        return

    if data == "adm:phone:toggle_iran":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("phone_iran_only", "0")
        new = "0" if cur == "1" else "1"
        setting_set("phone_iran_only", new)
        log_admin_action(uid, f"«⁄ »«—”‰ÃÌ ‘„«—Â «Ì—«‰Ì {'›⁄«·' if new == '1' else '€Ì—›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:phone")
        return

    # ?? Admin: Purchase Rules ?????????????????????????????????????????????????
    if data == "adm:set:rules":
        enabled = setting_get("purchase_rules_enabled", "0")
        kb = types.InlineKeyboardMarkup()
        toggle_label = "?? €Ì—›⁄«· ò—œ‰" if enabled == "1" else "?? ›⁄«· ò—œ‰"
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:rules:toggle"))
        kb.add(types.InlineKeyboardButton("?? ÊÌ—«Ì‘ „ ‰ ﬁÊ«‰Ì‰", callback_data="adm:rules:edit"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="adm:bot_texts", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>ﬁÊ«‰Ì‰ Œ—Ìœ</b>\n\n"
            f"Ê÷⁄Ì : {'?? ›⁄«·' if enabled == '1' else '?? €Ì—›⁄«·'}\n\n"
            "Êﬁ Ì ›⁄«· »«‘œ° ò«—»— ﬁ»· «“ «Ê·Ì‰ Œ—Ìœ »«Ìœ ﬁÊ«‰Ì‰ —« »Å–Ì—œ.", kb)
        return

    if data == "adm:rules:toggle":
        enabled = setting_get("purchase_rules_enabled", "0")
        setting_set("purchase_rules_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"ﬁÊ«‰Ì‰ Œ—Ìœ {'€Ì—›⁄«·' if enabled == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "adm:set:rules")
        return

    if data == "adm:rules:edit":
        state_set(uid, "admin_edit_rules_text")
        bot.answer_callback_query(call.id)
        current_text = setting_get("purchase_rules_text", "")
        preview = f"\n\n?? „ ‰ ›⁄·Ì:\n{esc(current_text[:200])}..." if len(current_text) > 200 else (f"\n\n?? „ ‰ ›⁄·Ì:\n{esc(current_text)}" if current_text else "")
        send_or_edit(call,
            f"?? <b>ÊÌ—«Ì‘ „ ‰ ﬁÊ«‰Ì‰ Œ—Ìœ</b>{preview}\n\n"
            "„ ‰ ÃœÌœ ﬁÊ«‰Ì‰ Œ—Ìœ —« «—”«· ò‰Ìœ:",
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
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid, "?? <b>›—Ê‘ê«Â „Êﬁ «  ⁄ÿÌ· «” .</b>\n\n·ÿ›« »⁄œ« „—«Ã⁄Â ò‰Ìœ.",
                             parse_mode="HTML", reply_markup=kb)
            return
        stock_only = setting_get("preorder_mode", "0") == "1"
        items = get_active_types()
        kb = types.InlineKeyboardMarkup()
        has_any = False
        for item in items:
            packs = [p for p in get_packages(type_id=item['id']) if p['price'] > 0 and _pkg_has_stock(p, stock_only)]
            if packs:
                kb.add(types.InlineKeyboardButton(f"?? {item['name']}", callback_data=f"buy:t:{item['id']}"))
                has_any = True
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        if not has_any:
            bot.send_message(uid, "?? œ— Õ«· Õ«÷— »” Âù«Ì »—«Ì ›—Ê‘ „ÊÃÊœ ‰Ì” .",
                             parse_mode="HTML", reply_markup=kb)
        else:
            bot.send_message(uid, "?? <b>Œ—Ìœ ò«‰›Ìê ÃœÌœ</b>\n\n‰Ê⁄ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:",
                             parse_mode="HTML", reply_markup=kb)
        return

    # ?? Admin: Pinned Messages ?????????????????????????????????????????????????
    if data == "adm:pin":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        pins = get_all_pinned_messages()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? «›“Êœ‰ ÅÌ«„ ÅÌ‰", callback_data="adm:pin:add"))
        for p in pins:
            preview = (p["text"] or "")[:30].replace("\n", " ")
            kb.row(
                types.InlineKeyboardButton(f"?? {preview}", callback_data="noop"),
                types.InlineKeyboardButton("??", callback_data=f"adm:pin:edit:{p['id']}"),
                types.InlineKeyboardButton("??", callback_data=f"adm:pin:del:{p['id']}"),
            )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        count_text = f"{len(pins)} ÅÌ«„" if pins else "ÂÌç ÅÌ«„Ì À»  ‰‘œÂ"
        send_or_edit(call, f"?? <b>ÅÌ«„ùÂ«Ì ÅÌ‰ ‘œÂ</b>\n\n{count_text}", kb)
        return

    if data == "adm:pin:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_pin_add")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>«›“Êœ‰ ÅÌ«„ ÅÌ‰</b>\n\n„ ‰ ÅÌ«„ —« «—”«· ò‰Ìœ:", back_button("adm:pin"))
        return

    if data.startswith("adm:pin:del:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
        log_admin_action(uid, f"ÅÌ«„ ÅÌ‰ #{pin_id} Õ–› ‘œ")
        bot.answer_callback_query(call.id, "?? ÅÌ«„ Õ–› Ê ¬‰ÅÌ‰ ‘œ.")
        send_to_topic("broadcast_report",
            f"?? <b>Õ–› ÅÌ«„ ÅÌ‰</b>\n\n"
            f"?? Õ–›ùò‰‰œÂ: <code>{uid}</code>\n"
            f"?? Õ–› ‘œÂ «“: <b>{removed_count}</b> ò«—»—\n\n"
            f"?? <b>„ ‰ ÅÌ«„:</b>\n{esc(_pin_text_preview) if _pin_text_preview else '(Œ«·Ì)'}")
        _fake_call(call, "adm:pin")
        return

    if data.startswith("adm:pin:edit:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        pin_id = int(data.split(":")[3])
        pin = get_pinned_message(pin_id)
        if not pin:
            bot.answer_callback_query(call.id, "ÅÌ«„ Ì«›  ‰‘œ.", show_alert=True)
            return
        state_set(uid, "admin_pin_edit", pin_id=pin_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>ÊÌ—«Ì‘ ÅÌ«„ ÅÌ‰</b>\n\n„ ‰ ›⁄·Ì:\n<code>{esc(pin['text'])}</code>\n\n„ ‰ ÃœÌœ —« «—”«· ò‰Ìœ:",
            back_button("adm:pin"))
        return

    # ?? Admin: Backup ?????????????????????????????????????????????????????????
    if data == "admin:backup":
        enabled  = setting_get("backup_enabled", "0")
        interval = setting_get("backup_interval", "24")
        target   = setting_get("backup_target_id", "")
        kb       = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? »ò«Å œ” Ì", callback_data="adm:bkp:manual"))
        kb.add(types.InlineKeyboardButton("?? »«“Ì«»Ì »ò«Å", callback_data="adm:bkp:restore"))
        toggle_label = "?? €Ì—›⁄«· ò—œ‰ »ò«Å ŒÊœò«—" if enabled == "1" else "?? ›⁄«· ò—œ‰ »ò«Å ŒÊœò«—"
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:bkp:toggle"))
        kb.add(types.InlineKeyboardButton(f"? “„«‰ù»‰œÌ: Â— {interval} ”«⁄ ", callback_data="adm:bkp:interval"))
        kb.add(types.InlineKeyboardButton("??  ‰ŸÌ„ „ﬁ’œ", callback_data="adm:bkp:target"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"?? <b>»ò«Å</b>\n\n"
            f"»ò«Å ŒÊœò«—: {'?? ›⁄«·' if enabled == '1' else '?? €Ì—›⁄«·'}\n"
            f"Â— {interval} ”«⁄ \n"
            f"„ﬁ’œ: <code>{esc(target or 'À»  ‰‘œÂ')}</code>",
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
        log_admin_action(uid, f"»ò«Å ŒÊœò«— {'€Ì—›⁄«·' if enabled == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _fake_call(call, "admin:backup")
        return

    if data == "adm:bkp:interval":
        state_set(uid, "admin_set_backup_interval")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "? »«“Â »ò«Å ŒÊœò«— —« »Â ”«⁄  Ê«—œ ò‰Ìœ („À«·: 6° 12° 24):",
                     back_button("admin:backup"))
        return

    if data == "adm:bkp:target":
        state_set(uid, "admin_set_backup_target")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? ¬ÌœÌ ⁄œœÌ ò«—»— Ì« ò«‰«· »—«Ì œ—Ì«›  »ò«Å —« Ê«—œ ò‰Ìœ:",
                     back_button("admin:backup"))
        return

    if data == "adm:bkp:restore":
        state_set(uid, "admin_restore_backup")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>»«“Ì«»Ì »ò«Å</b>\n\n"
            "?? <b> ÊÃÂ:</b> »« »«“Ì«»Ì »ò«Å° œÌ «»Ì” ›⁄·Ì —»«  Õ–› Ê »« ›«Ì· »ò«Å Ã«Ìê“Ì‰ „Ìù‘Êœ.\n\n"
            "›«Ì· »ò«Å (<code>.db</code>) —« «—”«· ò‰Ìœ:",
            back_button("admin:backup"))
        return

    # ?? Admin: Discount Codes ?????????????????????????????????????????????????
    if data == "admin:discounts":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _render_discount_admin_list(call, uid)
        return

    if data == "admin:vouchers":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _render_voucher_admin_list(call, uid)
        return

    if data == "admin:vch:toggle_global":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("vouchers_enabled", "1")
        setting_set("vouchers_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"”Ì” „ ò«—  ÂœÌÂ {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _render_voucher_admin_list(call, uid)
        return

    if data == "admin:vch:add":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_vch_add_name")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>«›“Êœ‰ ò«—  ÂœÌÂ</b>\n\n"
            "„—Õ·Â ?: Ìò <b>‰«„</b> »—«Ì «Ì‰ œ” Â ò«—  ÂœÌÂ Ê«—œ ò‰Ìœ:\n"
            "<i>„À«·: Ã‘‰Ê«—Â ‰Ê—Ê“</i>",
            back_button("admin:vouchers"))
        return

    if data == "admin:vch:gift_type:wallet":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        sd = state_data(uid)
        state_set(uid, "admin_vch_add_amount", vch_name=sd.get("vch_name", ""))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>«›“Êœ‰ ò«—  ÂœÌÂ</b>\n\n"
            "„—Õ·Â ?: „»·€ ‘«—é òÌ› ÅÊ· —« »Â <b> Ê„«‰</b> Ê«—œ ò‰Ìœ:",
            back_button("admin:vch:add"))
        return

    if data == "admin:vch:gift_type:config":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        sd = state_data(uid)
        state_set(uid, "admin_vch_pick_type", vch_name=sd.get("vch_name", ""))
        bot.answer_callback_query(call.id)
        types_list = get_active_types()
        kb = types.InlineKeyboardMarkup()
        for t in types_list:
            kb.add(types.InlineKeyboardButton(t["name"], callback_data=f"admin:vch:pick_type:{t['id']}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:vch:add", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>«›“Êœ‰ ò«—  ÂœÌÂ ñ «‰ Œ«» ‰Ê⁄</b>\n\n"
            "‰Ê⁄ ò«‰›Ìê —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("admin:vch:pick_type:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:vch:gift_type:config", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "?? <b>«›“Êœ‰ ò«—  ÂœÌÂ ñ «‰ Œ«» ÅòÌÃ</b>\n\nÅòÌÃ „Ê—œ ‰Ÿ— —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("admin:vch:pick_pkg:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        pkg_id = int(data.split(":")[3])
        sd = state_data(uid)
        state_set(uid, "admin_vch_add_count_config",
                  vch_name=sd.get("vch_name", ""), package_id=pkg_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>«›“Êœ‰ ò«—  ÂœÌÂ</b>\n\n"
            "„—Õ·Â ¬Œ—:  ⁄œ«œ òœÂ«Ì ò«—  ÂœÌÂ —« Ê«—œ ò‰Ìœ:\n"
            "<i>„À«·: ??</i>",
            back_button("admin:vouchers"))
        return

    if data.startswith("admin:vch:view:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _render_voucher_batch_detail(call, uid, batch_id)
        return

    if data.startswith("admin:vch:del:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        batch = get_voucher_batch(batch_id)
        if not batch:
            bot.answer_callback_query(call.id, "œ” Â Ì«›  ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("?? »·Â° Õ–› ‘Êœ", callback_data=f"admin:vch:del_confirm:{batch_id}"),
            types.InlineKeyboardButton("? ·€Ê", callback_data=f"admin:vch:view:{batch_id}"),
        )
        send_or_edit(call,
            f"?? <b>Õ–› ò«—  ÂœÌÂ</b>\n\n"
            f"¬Ì« «“ Õ–› œ” Â ´{esc(batch['name'])}ª Ê  „«„ òœÂ«Ì ¬‰ „ÿ„∆‰ Â” Ìœø",
            kb)
        return

    if data.startswith("admin:vch:del_confirm:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        delete_voucher_batch(batch_id)
        log_admin_action(uid, f"œ” Â ò«—  ÂœÌÂ #{batch_id} Õ–› ‘œ")
        bot.answer_callback_query(call.id, "? œ” Â Õ–› ‘œ.")
        _render_voucher_admin_list(call, uid)
        return

    # ?? User: voucher redemption ??????????????????????????????????????????????
    if data == "voucher:redeem":
        if setting_get("vouchers_enabled", "1") != "1":
            bot.answer_callback_query(call.id, "?? ”Ì” „ ò«—  ÂœÌÂ œ— Õ«· Õ«÷— €Ì—›⁄«· «” .", show_alert=True)
            return
        state_set(uid, "await_voucher_code")
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="nav:main", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "??? <b>À»  ò«—  ÂœÌÂ</b> ???\n\n"
            "?? «“ «Ì‰òÂ ò«—  ÂœÌÂù«Ì œ—Ì«›  ò—œÂù«Ìœ ŒÊ‘Õ«·Ì„!\n\n"
            "?? ·ÿ›« òœ ò«—  ÂœÌÂ ŒÊœ —« Ê«—œ ò‰Ìœ  « ÂœÌÂù «‰ ›Ê—Ì »Â Õ”«» ‘„« «÷«›Â ‘Êœ:",
            kb)
        return

    if data == "admin:disc:toggle_global":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        cur = setting_get("discount_codes_enabled", "0")
        setting_set("discount_codes_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"”Ì” „ òœ  Œ›Ì› {'€Ì—›⁄«·' if cur == '1' else '›⁄«·'} ‘œ")
        bot.answer_callback_query(call.id, " €ÌÌ— Ì«› .")
        _render_discount_admin_list(call, uid)
        return

    if data == "admin:disc:add":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        state_set(uid, "admin_discount_add_code")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>«›“Êœ‰ òœ  Œ›Ì›</b>\n\n"
            "„—Õ·Â ?/?: „ ‰ òœ  Œ›Ì› —« Ê«—œ ò‰Ìœ:\n"
            "(Õ—Ê› «‰ê·Ì”Ì° «⁄œ«œ° Œÿ  Ì—Â ó „À«·: NEWUSER20)",
            back_button("admin:discounts"))
        return

    if data.startswith("admin:disc:add_type:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        disc_type = data.split(":")[3]
        sd = state_data(uid)
        state_set(uid, "admin_discount_add_value",
                  code=sd.get("code", ""), disc_type=disc_type)
        bot.answer_callback_query(call.id)
        if disc_type == "pct":
            send_or_edit(call,
                "?? <b>«›“Êœ‰ òœ  Œ›Ì›</b>\n\n"
                "„—Õ·Â ?/?: „ﬁœ«—  Œ›Ì› —« »Â <b>œ—’œ</b> Ê«—œ ò‰Ìœ (?  « ???):",
                back_button("admin:disc:add"))
        else:
            send_or_edit(call,
                "?? <b>«›“Êœ‰ òœ  Œ›Ì›</b>\n\n"
                "„—Õ·Â ?/?: „ﬁœ«—  Œ›Ì› —« »Â <b> Ê„«‰</b> Ê«—œ ò‰Ìœ:",
                back_button("admin:disc:add"))
        return

    if data.startswith("admin:disc:add_audience:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        audience = data.split(":")[3] if data.split(":")[3] in ("all", "public", "agents") else "all"
        sd = state_data(uid)
        state_set(uid, "admin_discount_add_usage",
                  code=sd.get("code", ""),
                  disc_type=sd.get("disc_type", "pct"),
                  discount_value=sd.get("discount_value", 0),
                  max_uses_total=sd.get("max_uses_total", 0),
                  max_uses_per_user=sd.get("max_uses_per_user", 0),
                  audience=audience)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Â„Â Œ—ÌœÂ«",          callback_data="admin:disc:add_usage:all"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ Œ—Ìœ ÅòÌÃ",       callback_data="admin:disc:add_usage:package"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ Œ—Ìœ ÕÃ„ «÷«›Â", callback_data="admin:disc:add_usage:addon_volume"))
        kb.add(types.InlineKeyboardButton("? ›ﬁÿ Œ—Ìœ “„«‰ «÷«›Â", callback_data="admin:disc:add_usage:addon_time"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:discounts",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>«›“Êœ‰ òœ  Œ›Ì›</b>\n\n"
            "„—Õ·Â ?/?: «Ì‰ òœ  Œ›Ì› »—«Ì òœ«„ ‰Ê⁄ Œ—Ìœ ﬁ«»· «” ›«œÂ »«‘œø",
            kb)
        return

    if data.startswith("admin:disc:add_usage:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        usage_scope = data.split(":")[3]
        if usage_scope not in ("all", "package", "addon_volume", "addon_time"):
            usage_scope = "all"
        sd = state_data(uid)
        state_set(uid, "admin_discount_add_scope",
                  code=sd.get("code", ""),
                  disc_type=sd.get("disc_type", "pct"),
                  discount_value=sd.get("discount_value", 0),
                  max_uses_total=sd.get("max_uses_total", 0),
                  max_uses_per_user=sd.get("max_uses_per_user", 0),
                  audience=sd.get("audience", "all"),
                  usage_scope=usage_scope)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Â„Â ÅòÌÃùÂ«",          callback_data="admin:disc:scope:all"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ ‰Ê⁄ùÂ«Ì Œ«’",      callback_data="admin:disc:scope:types"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ ÅòÌÃùÂ«Ì Œ«’",    callback_data="admin:disc:scope:packages"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:discounts",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>«›“Êœ‰ òœ  Œ›Ì›</b>\n\n"
            "„—Õ·Â ?/?: „ÕœÊœÂ ÅòÌÃ —« «‰ Œ«» ò‰Ìœ:\n\n"
            "?? <b>Â„Â ÅòÌÃùÂ«</b> ó »œÊ‰ „ÕœÊœÌ \n"
            "?? <b>‰Ê⁄ùÂ«Ì Œ«’</b> ó ›ﬁÿ »—«Ì ‰Ê⁄ùÂ«Ì «‰ Œ«»Ì\n"
            "?? <b>ÅòÌÃùÂ«Ì Œ«’</b> ó ›ﬁÿ »—«Ì ÅòÌÃùÂ«Ì «‰ Œ«»Ì",
            kb)
        return


    if data.startswith("admin:disc:scope:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
                    usage_scope=sd.get("usage_scope", "all"),
                )
            except Exception:
                bot.answer_callback_query(call.id, "?? «Ì‰ òœ ﬁ»·« À»  ‘œÂ «” .", show_alert=True)
                return
            state_clear(uid)
            log_admin_action(uid, f"òœ  Œ›Ì› ÃœÌœ {sd.get('code', '')} À»  ‘œ („ÕœÊœÂ: Â„Â)")
            bot.answer_callback_query(call.id, "? òœ  Œ›Ì› À»  ‘œ.")
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        sd = state_data(uid)
        selected_str = sd.get("scope_selected", "") or ""
        selected_ids = [int(x) for x in selected_str.split(",") if x.strip()]
        if not selected_ids:
            bot.answer_callback_query(call.id, "?? Õœ«ﬁ· Ìò „Ê—œ —« «‰ Œ«» ò‰Ìœ.", show_alert=True)
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
                usage_scope=sd.get("usage_scope", "all"),
            )
        except Exception:
            bot.answer_callback_query(call.id, "?? «Ì‰ òœ ﬁ»·« À»  ‘œÂ «” .", show_alert=True)
            return
        target_type = "type" if scope_type == "types" else "package"
        set_discount_code_targets(new_id, target_type, selected_ids)
        state_clear(uid)
        log_admin_action(uid, f"òœ  Œ›Ì› ÃœÌœ {sd.get('code', '')} À»  ‘œ („ÕœÊœÂ: {scope_type})")
        bot.answer_callback_query(call.id, "? òœ  Œ›Ì› À»  ‘œ.")
        _render_discount_admin_list(call, uid)
        return

    if data.startswith("admin:disc:edit_scope:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        if not row:
            bot.answer_callback_query(call.id, "òœ ÅÌœ« ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? Â„Â ÅòÌÃùÂ«", callback_data=f"admin:disc:set_scope:{code_id}:all"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ ‰Ê⁄ùÂ«Ì Œ«’", callback_data=f"admin:disc:set_scope:{code_id}:types"))
        kb.add(types.InlineKeyboardButton("?? ›ﬁÿ ÅòÌÃùÂ«Ì Œ«’", callback_data=f"admin:disc:set_scope:{code_id}:packages"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"admin:disc:view:{code_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "?? <b>ÊÌ—«Ì‘ „ÕœÊœÂ òœ  Œ›Ì›</b>\n\n‰Ê⁄ „ÕœÊœÂ —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data.startswith("admin:disc:set_scope:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
            log_admin_action(uid, f"„ÕœÊœÂ òœ  Œ›Ì› #{code_id} »Â Â„Â  €ÌÌ— Ì«› ")
            bot.answer_callback_query(call.id, "? „ÕœÊœÂ »Âù—Ê“ ‘œ.")
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        sd = state_data(uid)
        selected_str = sd.get("scope_selected", "") or ""
        selected_ids = [int(x) for x in selected_str.split(",") if x.strip()]
        if not selected_ids:
            bot.answer_callback_query(call.id, "?? Õœ«ﬁ· Ìò „Ê—œ —« «‰ Œ«» ò‰Ìœ.", show_alert=True)
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
        log_admin_action(uid, f"„ÕœÊœÂ òœ  Œ›Ì› #{code_id} »Âù—Ê“ ‘œ")
        bot.answer_callback_query(call.id, "? „ÕœÊœÂ »Âù—Ê“ ‘œ.")
        _render_discount_code_detail(call, uid, code_id)
        return

    if data.startswith("admin:disc:view:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _render_discount_code_detail(call, uid, code_id)
        return

    if data.startswith("admin:disc:toggle:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        toggle_discount_code(code_id)
        bot.answer_callback_query(call.id, "Ê÷⁄Ì   €ÌÌ— Ì«› .")
        _render_discount_code_detail(call, uid, code_id)
        return

    if data.startswith("admin:disc:del:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        if not row:
            bot.answer_callback_query(call.id, "òœ ÅÌœ« ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("?? »·Â° Õ–› ò‰", callback_data=f"admin:disc:del_confirm:{code_id}"),
            types.InlineKeyboardButton("? ·€Ê", callback_data=f"admin:disc:view:{code_id}"),
        )
        send_or_edit(call,
            f"?? <b>Õ–› òœ  Œ›Ì›</b>\n\n"
            f"¬Ì« «“ Õ–› òœ <code>{esc(row['code'])}</code> „ÿ„∆‰ Â” Ìœø",
            kb)
        return

    if data.startswith("admin:disc:del_confirm:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        delete_discount_code(code_id)
        log_admin_action(uid, f"òœ  Œ›Ì› #{code_id} Õ–› ‘œ")
        bot.answer_callback_query(call.id, "? òœ Õ–› ‘œ.")
        _render_discount_admin_list(call, uid)
        return

    if data.startswith("admin:disc:edit_code:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_code", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>ÊÌ—«Ì‘ òœ  Œ›Ì›</b>\n\n„ ‰ ÃœÌœ òœ  Œ›Ì› —« Ê«—œ ò‰Ìœ:",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_val:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        type_fa = "œ—’œ" if row and row["discount_type"] == "pct" else " Ê„«‰"
        state_set(uid, f"admin_discount_edit_val", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>ÊÌ—«Ì‘ „ﬁœ«—  Œ›Ì›</b>\n\n"
            f"‰Ê⁄  Œ›Ì›: {type_fa}\n\n"
            "„ﬁœ«— ÃœÌœ —« Ê«—œ ò‰Ìœ:",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_total:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_total", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>ÊÌ—«Ì‘ Õœ«òÀ— «” ›«œÂ ò·</b>\n\n"
            " ⁄œ«œ ÃœÌœ —« Ê«—œ ò‰Ìœ (? = ‰«„ÕœÊœ):",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_per:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_per", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>ÊÌ—«Ì‘ Õœ«òÀ— «” ›«œÂ Â— ò«—»—</b>\n\n"
            " ⁄œ«œ ÃœÌœ —« Ê«—œ ò‰Ìœ (? = ‰«„ÕœÊœ):",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_audience:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        if not row:
            bot.answer_callback_query(call.id, "òœ ÅÌœ« ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        current = row["audience"] if "audience" in row.keys() else "all"
        kb = types.InlineKeyboardMarkup()
        for aud_key, aud_label in [("all", "?? Â„Â"), ("public", "?? ›ﬁÿ ⁄„Ê„"), ("agents", "?? ›ﬁÿ ‰„«Ì‰œê«‰")]:
            icon = "? " if current == aud_key else ""
            kb.add(types.InlineKeyboardButton(f"{icon}{aud_label}", callback_data=f"admin:disc:set_audience:{code_id}:{aud_key}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"admin:disc:view:{code_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"?? <b>ÊÌ—«Ì‘ œ” —”Ì òœ  Œ›Ì›</b>\n\n"
            f"òœ: <code>{esc(row['code'])}</code>\n\n"
            "«Ì‰ òœ  Œ›Ì› »—«Ì çÂ ò”«‰Ì ﬁ«»· «” ›«œÂ »«‘œø",
            kb)
        return

    if data.startswith("admin:disc:set_audience:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts = data.split(":")
        code_id = int(parts[3])
        audience = parts[4] if parts[4] in ("all", "public", "agents") else "all"
        update_discount_code_field(code_id, "audience", audience)
        audience_labels = {"all": "Â„Â", "public": "›ﬁÿ ⁄„Ê„", "agents": "›ﬁÿ ‰„«Ì‰œê«‰"}
        bot.answer_callback_query(call.id, f"? œ” —”Ì »Â ´{audience_labels.get(audience)}ª  €ÌÌ— Ì«› .")
        _render_discount_code_detail(call, uid, code_id)
        return

    # ?? Admin: Payment approve/reject ?????????????????????????????????????????
    if data.startswith("adm:pay:ap:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, " —«ò‰‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "«Ì‰  —«ò‰‘ ﬁ»·« »——”Ì ‘œÂ «” .", show_alert=True)
            return
        text = (
            f"??? <b> √ÌÌœ »«  Ê÷ÌÕ« </b>\n\n"
            f"?? „»·€: <b>{fmt_price(payment['amount'])}</b>  Ê„«‰\n"
            f"?? ò«—»—: <code>{payment['user_id']}</code>\n\n"
            f"?? ÅÌ«„  √ÌÌœ »—«Ì ò«—»— —«  «ÌÅ ò‰Ìœ Ê «—”«· ò‰Ìœ:"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?  √ÌÌœ »œÊ‰  Ê÷ÌÕ« ", callback_data=f"adm:pay:apc:{payment_id}"))
        kb.add(types.InlineKeyboardButton("?? «‰’—«›", callback_data="nav:admin:panel"))
        state_set(uid, "admin_payment_approve_note", payment_id=payment_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:pay:apc:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, " —«ò‰‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "«Ì‰  —«ò‰‘ ﬁ»·« »——”Ì ‘œÂ «” .", show_alert=True)
            return
        # Answer immediately so Telegram stops showing spinner and won't retry
        bot.answer_callback_query(call.id, "? œ— Õ«· Å—œ«“‘...")
        state_clear(uid)
        result = finish_card_payment_approval(payment_id, "Ê«—Ì“Ì ‘„«  √ÌÌœ ‘œ.", approved=True)
        if not result:
            send_or_edit(call, "?? «Ì‰  —«ò‰‘ ﬁ»·« Å—œ«“‘ ‘œÂ «” .", kb_admin_panel(uid))
        else:
            send_or_edit(call, "?  —«ò‰‘ »« „Ê›ﬁÌ   √ÌÌœ ‘œ.", kb_admin_panel(uid))
        return

    if data.startswith("adm:pay:rj:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, " —«ò‰‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "«Ì‰  —«ò‰‘ ﬁ»·« »——”Ì ‘œÂ «” .", show_alert=True)
            return
        text = (
            f"??? <b>—œ »«  Ê÷ÌÕ« </b>\n\n"
            f"?? „»·€: <b>{fmt_price(payment['amount'])}</b>  Ê„«‰\n"
            f"?? ò«—»—: <code>{payment['user_id']}</code>\n\n"
            f"?? œ·Ì· —œ —«  «ÌÅ ò‰Ìœ Ê «—”«· ò‰Ìœ:"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "? —”Ìœ ›Ìò ó „ÕœÊœ ?? ”«⁄ ",
            callback_data=f"adm:pay:rjc:fake24:{payment_id}"))
        kb.add(types.InlineKeyboardButton(
            "?? —”Ìœ ›Ìò ó „ÕœÊœ Â„Ì‘Â",
            callback_data=f"adm:pay:rjc:fakeall:{payment_id}"))
        kb.add(types.InlineKeyboardButton("?? «‰’—«›", callback_data="nav:admin:panel"))
        state_set(uid, "admin_payment_reject_note", payment_id=payment_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:pay:rjc:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts      = data.split(":")
        mode       = parts[3]             # plain | fake24 | fakeall
        payment_id = int(parts[4])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, " —«ò‰‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "«Ì‰  —«ò‰‘ ﬁ»·« »——”Ì ‘œÂ «” .", show_alert=True)
            return
        # Answer immediately so Telegram stops showing spinner and won't retry
        bot.answer_callback_query(call.id, "? œ— Õ«· Å—œ«“‘...")
        state_clear(uid)
        finish_card_payment_approval(payment_id, "—”Ìœ ‘„« —œ ‘œ.", approved=False)

        payer_id = payment["user_id"]

        if mode in ("fake24", "fakeall"):
            import time as _t
            if mode == "fake24":
                _until   = int(_t.time()) + 86400
                _dur_txt = " « ?? ”«⁄  œÌê— ‰„Ìù Ê«‰Ìœ «“ —»«  «” ›«œÂ ò‰Ìœ."
            else:
                _until   = 0   # permanent
                _dur_txt = "»—«Ì Â„Ì‘Â ‰„Ìù Ê«‰Ìœ «“ —»«  «” ›«œÂ ò‰Ìœ."

            set_user_restricted(payer_id, _until)
            log_admin_action(uid,
                f"—”Ìœ ›Ìò | ò«—»— <code>{payer_id}</code> „ÕœÊœ ‘œ | mode={mode}")

            # Build support line
            _sup_raw  = setting_get("support_username", "")
            _sup_link = setting_get("support_link", "")
            _sup_url  = safe_support_url(_sup_raw) or (_sup_link if _sup_link else None)
            _sup_line = (
                f"\n\n?? »—«Ì ÅÌêÌ—Ì —›⁄ „ÕœÊœÌ  »Â Å‘ Ì»«‰Ì ÅÌ«„ œÂÌœ:\n{_sup_url}"
                if _sup_url else
                "\n\n?? »—«Ì ÅÌêÌ—Ì —›⁄ „ÕœÊœÌ  »« Å‘ Ì»«‰Ì œ—  „«” »«‘Ìœ."
            )

            try:
                bot.send_message(
                    payer_id,
                    f"? <b>Õ”«» ‘„« „ÕœÊœ ‘œ</b>\n\n"
                    f"»Â œ·Ì· «—”«· —”Ìœ Ã⁄·Ì° Õ”«» ‘„« „ÕœÊœ ‘œÂ «” .\n"
                    f"?? {_dur_txt}"
                    f"{_sup_line}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        send_or_edit(call, "?  —«ò‰‘ —œ ‘œ.", kb_admin_panel(uid))
        return

    # ?? Admin: Pending receipts panel ?????????????????????????????????????????
    if data == "admin:pr" or data.startswith("admin:pr:list:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
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
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, " —«ò‰‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        user_row    = get_user(payment["user_id"])
        package_row = get_package(payment["package_id"]) if payment["package_id"] else None
        kind_label  = {"wallet_charge": "‘«—é òÌ›ùÅÊ·", "buy": "Œ—Ìœ ò«‰›Ìê", "renew": " „œÌœ ò«‰›Ìê"}.get(
            payment["kind"], payment["kind"]
        )
        pkg_text = ""
        if package_row:
            pkg_text = (
                f"\n?? ‰Ê⁄: {esc(package_row['type_name'])}"
                f"\n?? ÅòÌÃ: {esc(package_row['name'])}"
                f"\n?? ÕÃ„: {fmt_vol(package_row['volume_gb'])} | ? {fmt_dur(package_row['duration_days'])}"
            )
        receipt_note = esc(payment["receipt_text"] or "ó")
        uname = "@" + esc(user_row["username"]) if (user_row and user_row["username"]) else "ó"
        _pay_dict = dict(payment)
        crypto_comment_line = ""
        if _pay_dict.get("crypto_comment"):
            crypto_comment_line = f"\n?? òœ ò«„‰ : <code>{esc(_pay_dict['crypto_comment'])}</code>"
        text = (
            f"?? <b>Ã“∆Ì«  —”Ìœ #{payment_id}</b>\n\n"
            f"?? ‰Ê⁄: <b>{kind_label}</b>\n"
            f"?? ò«—»—: {esc(user_row['full_name'] if user_row else 'ó')}\n"
            f"?? ¬ÌœÌ: <code>{payment['user_id']}</code>\n"
            f"?? ÌÊ“—‰Ì„: {uname}\n"
            f"?? „»·€: <b>{fmt_price(payment['amount'])}</b>  Ê„«‰\n"
            f"?? —Ê‘ Å—œ«Œ : {esc(payment['payment_method'])}"
            f"{crypto_comment_line}"
            f"{pkg_text}\n\n"
            f"??  Ê÷ÌÕ«  „‘ —Ì: {receipt_note}\n"
            f"?? À»  ‘œÂ: {payment['created_at']}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("?  √ÌÌœ", callback_data=f"admin:pr:ap:{payment_id}:{page}"),
            types.InlineKeyboardButton("? —œ",    callback_data=f"admin:pr:rj:{payment_id}:{page}"),
        )
        kb.row(
            types.InlineKeyboardButton("???  √ÌÌœ »«  Ê÷ÌÕ", callback_data=f"adm:pay:ap:{payment_id}"),
            types.InlineKeyboardButton("??? —œ »«  Ê÷ÌÕ",    callback_data=f"adm:pay:rj:{payment_id}"),
        )
        kb.add(types.InlineKeyboardButton("?? »«“ê‘  »Â ·Ì” ", callback_data=f"admin:pr:list:{page}"))
        file_id = payment["receipt_file_id"]
        if file_id:
            try:
                bot.send_photo(uid, file_id, caption="?? —”Ìœ ò«—»—")
            except Exception:
                try:
                    bot.send_document(uid, file_id, caption="?? —”Ìœ ò«—»—")
                except Exception:
                    pass
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pr:ap:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, " —«ò‰‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰  —«ò‰‘ ﬁ»·« »——”Ì ‘œÂ «” .", show_alert=True)
            return
        # Answer immediately so Telegram stops showing spinner and won't retry
        bot.answer_callback_query(call.id, "? œ— Õ«· Å—œ«“‘...")
        result = finish_card_payment_approval(payment_id, "Ê«—Ì“Ì ‘„«  √ÌÌœ ‘œ.", approved=True)
        _render_pending_receipts_page(call, uid, page)
        return

    if data.startswith("admin:pr:rj:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, " —«ò‰‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰  —«ò‰‘ ﬁ»·« »——”Ì ‘œÂ «” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "? —œ »œÊ‰  Ê÷ÌÕ",
            callback_data=f"admin:pr:rjdo:plain:{payment_id}:{page}"))
        kb.add(types.InlineKeyboardButton(
            "? —”Ìœ ›Ìò ó „ÕœÊœ ?? ”«⁄ ",
            callback_data=f"admin:pr:rjdo:fake24:{payment_id}:{page}"))
        kb.add(types.InlineKeyboardButton(
            "?? —”Ìœ ›Ìò ó „ÕœÊœ Â„Ì‘Â",
            callback_data=f"admin:pr:rjdo:fakeall:{payment_id}:{page}"))
        kb.add(types.InlineKeyboardButton(
            "»«“ê‘ ", callback_data=f"admin:pr:det:{payment_id}:{page}",
            icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"? <b>—œ —”Ìœ #{payment_id}</b>\n\n‰Ê⁄ —œ ò—œ‰ —« «‰ Œ«» ò‰Ìœ:",
            kb)
        return

    if data.startswith("admin:pr:rjdo:"):
        # admin:pr:rjdo:{mode}:{payment_id}:{page}
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts      = data.split(":")
        mode       = parts[3]             # plain | fake24 | fakeall
        payment_id = int(parts[4])
        page       = int(parts[5]) if len(parts) > 5 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, " —«ò‰‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "«Ì‰  —«ò‰‘ ﬁ»·« »——”Ì ‘œÂ «” .", show_alert=True)
            return

        # Answer immediately so Telegram stops showing spinner and won't retry
        bot.answer_callback_query(call.id, "? œ— Õ«· Å—œ«“‘...")
        # Reject the payment
        finish_card_payment_approval(payment_id, "—”Ìœ ‘„« —œ ‘œ.", approved=False)

        payer_id = payment["user_id"]

        if mode in ("fake24", "fakeall"):
            import time as _t
            if mode == "fake24":
                _until   = int(_t.time()) + 86400
                _dur_txt = " « ?? ”«⁄  œÌê— ‰„Ìù Ê«‰Ìœ «“ —»«  «” ›«œÂ ò‰Ìœ."
            else:
                _until   = 0   # permanent
                _dur_txt = "»—«Ì Â„Ì‘Â ‰„Ìù Ê«‰Ìœ «“ —»«  «” ›«œÂ ò‰Ìœ."

            set_user_restricted(payer_id, _until)
            log_admin_action(uid,
                f"—”Ìœ ›Ìò | ò«—»— <code>{payer_id}</code> „ÕœÊœ ‘œ | mode={mode}")

            # Build support line
            _sup_raw  = setting_get("support_username", "")
            _sup_link = setting_get("support_link", "")
            _sup_url  = safe_support_url(_sup_raw) or (_sup_link if _sup_link else None)
            _sup_line = (
                f"\n\n?? »—«Ì ÅÌêÌ—Ì —›⁄ „ÕœÊœÌ  »Â Å‘ Ì»«‰Ì ÅÌ«„ œÂÌœ:\n{_sup_url}"
                if _sup_url else
                "\n\n?? »—«Ì ÅÌêÌ—Ì —›⁄ „ÕœÊœÌ  »« Å‘ Ì»«‰Ì œ—  „«” »«‘Ìœ."
            )

            try:
                bot.send_message(
                    payer_id,
                    f"? <b>Õ”«» ‘„« „ÕœÊœ ‘œ</b>\n\n"
                    f"»Â œ·Ì· «—”«· —”Ìœ Ã⁄·Ì° Õ”«» ‘„« „ÕœÊœ ‘œÂ «” .\n"
                    f"?? {_dur_txt}"
                    f"{_sup_line}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        _render_pending_receipts_page(call, uid, page)
        return

    # adm:pnd:proto:{proto}:{pending_id}  ?  ask single/bulk
    if data.startswith("adm:pnd:proto:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts = data.split(":")
        proto      = parts[3]            # v2ray | ovpn | wg
        pending_id = int(parts[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«›  ‰‘œ Ì« ﬁ»·«  ò„Ì· ‘œÂ «” .", show_alert=True)
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
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",    callback_data=f"adm:pnd:v2:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:pnd:v2:bulk:{pending_id}"))
        elif proto == "ovpn":
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",    callback_data=f"adm:pnd:ovpn:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}"))
        elif proto == "wg":
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",    callback_data=f"adm:pnd:wg:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:pnd:wg:bulk:{pending_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pending:addcfg:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, f"?? —Ê‘ À»  ò«‰›Ìê —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    # adm:pnd:v2:single:{pending_id}  ?  V2Ray single for pending order
    if data.startswith("adm:pnd:v2:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "v2_single_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  mode=1, pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>‰«„ ”—ÊÌ”</b> —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:pnd:proto:v2ray:{pending_id}"))
        return

    # adm:pnd:v2:bulk:{pending_id}  ?  V2Ray bulk for pending order
    if data.startswith("adm:pnd:v2:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "v2_bulk_init",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("1?? ò«‰›Ìê + ”«» ó  ⁄œ«œ ò„",   callback_data=f"adm:pnd:v2bm:1:{pending_id}"))
        kb.add(types.InlineKeyboardButton("2?? ò«‰›Ìê + ”«» ó  ⁄œ«œ “Ì«œ", callback_data=f"adm:pnd:v2bm:2:{pending_id}"))
        kb.add(types.InlineKeyboardButton("3?? ò«‰›Ìê  ‰Â«",               callback_data=f"adm:pnd:v2bm:3:{pending_id}"))
        kb.add(types.InlineKeyboardButton("4?? ”«»  ‰Â«",                  callback_data=f"adm:pnd:v2bm:4:{pending_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:proto:v2ray:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>‰Ê⁄ À»  œ” Âù«Ì V2Ray</b> —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    # adm:pnd:v2bm:{mode}:{pending_id}  ?  bulk mode selected for pending order
    if data.startswith("adm:pnd:v2bm:"):
        if not is_admin(uid): return
        parts = data.split(":")
        mode = int(parts[3]); pending_id = int(parts[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        s = state_data(uid)
        bot.answer_callback_query(call.id)
        if mode in (1, 2, 3):
            state_set(uid, "v2_bulk_pre",
                      package_id=p_row["package_id"],
                      type_id=pkg["type_id"] if pkg else 0,
                      mode=mode, pending_id=pending_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("? »œÊ‰ ÅÌ‘Ê‰œ", callback_data=f"adm:pnd:v2bpfx:skip:{pending_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:v2:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "?? <b>ÅÌ‘Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
                "«ê— «» œ«Ì ‰«„ ò«‰›ÌêùÂ« „ ‰ «÷«›Âù«Ì œ«—œ Ê«—œ ò‰Ìœ° œ— €Ì— «Ì‰’Ê—  ´»œÊ‰ ÅÌ‘Ê‰œª »“‰Ìœ.", kb)
        else:  # mode 4: sub only
            state_set(uid, "v2_bulk_data",
                      package_id=p_row["package_id"],
                      type_id=pkg["type_id"] if pkg else 0,
                      mode=4, prefix="", suffix="", pending_id=pending_id)
            send_or_edit(call, _v2_bulk_data_prompt(4), back_button(f"adm:pnd:v2:bulk:{pending_id}"))
        return

    # adm:pnd:v2bpfx:skip:{pending_id}  ?  skip prefix for pending bulk
    if data.startswith("adm:pnd:v2bpfx:skip:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        s = state_data(uid)
        state_set(uid, "v2_bulk_suf",
                  package_id=s["package_id"], type_id=s["type_id"],
                  mode=s["mode"], prefix="", pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? »œÊ‰ Å”Ê‰œ", callback_data=f"adm:pnd:v2bsfx:skip:{pending_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:v2:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>Å”Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
            "«ê— «‰ Â«Ì ‰«„ùÂ« „ ‰ «÷«›Âù«Ì œ«—œ Ê«—œ ò‰Ìœ° œ— €Ì— «Ì‰’Ê—  ´»œÊ‰ Å”Ê‰œª »“‰Ìœ.", kb)
        return

    # adm:pnd:v2bsfx:skip:{pending_id}  ?  skip suffix for pending bulk
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

    # adm:pnd:ovpn:single:{pending_id}  ?  OpenVPN single for pending order
    if data.startswith("adm:pnd:ovpn:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        state_set(uid, "ovpn_single_file",
                  package_id=p_row["package_id"], pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:proto:ovpn:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>À»   òÌ OpenVPN »—«Ì ”›«—‘</b>\n\n"
            "›«Ì· Ì« ›«Ì·ùÂ«Ì <code>.ovpn</code> —« «—”«· ò‰Ìœ:", kb)
        return

    # adm:pnd:ovpn:bulk:{pending_id}  ?  OpenVPN bulk for pending order
    if data.startswith("adm:pnd:ovpn:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        state_set(uid, "ovpn_bulk_init",
                  package_id=p_row["package_id"], pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("? »·Â ó Ìò ›«Ì·",    callback_data=f"adm:pnd:ovpn:bshared:{pending_id}"),
            types.InlineKeyboardButton("? ŒÌ— ó ›«Ì· Ãœ«ê«‰Â", callback_data=f"adm:pnd:ovpn:bdiff:{pending_id}"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:proto:ovpn:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>À»  œ” Âù«Ì OpenVPN »—«Ì ”›«—‘</b>\n\n"
            "¬Ì« Â„Â ò«—»—«‰ «“ Ìò ›«Ì· <b>.ovpn</b> „‘ —ò «” ›«œÂ „Ìùò‰‰œø", kb)
        return

    # adm:pnd:ovpn:bshared:{pending_id}  ?  shared ovpn file for pending
    if data.startswith("adm:pnd:ovpn:bshared:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        state_set(uid, "ovpn_bulk_shared_file",
                  package_id=p_row["package_id"], pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? ›«Ì· <code>.ovpn</code> „‘ —ò —« «—”«· ò‰Ìœ:\n"
            "<i>«Ì‰ ›«Ì· »—«Ì Â„Â ”›«—‘ùÂ«Ì „‰ Ÿ— «” ›«œÂ „Ìù‘Êœ.</i>", kb)
        return

    # adm:pnd:ovpn:bdiff:{pending_id}  ?  different ovpn files for pending
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
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? ›«Ì·ùÂ«Ì <code>.ovpn</code> ò«—»— «Ê· —« «—”«· ò‰Ìœ.\n"
            "Å” «“  √ÌÌœ° »Â ò«—»— »⁄œÌ „Ìù—ÊÌœ.", kb)
        return

    # adm:pnd:wg:single:{pending_id}  ?  WireGuard single for pending order
    if data.startswith("adm:pnd:wg:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_single_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>‰«„ ”—ÊÌ” WireGuard</b> —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:pnd:proto:wg:{pending_id}"))
        return

    # adm:pnd:wg:bulk:{pending_id}  ?  WireGuard bulk for pending order
    if data.startswith("adm:pnd:wg:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_bulk_init",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("? »·Â ó Ìò ò«‰›Ìê",    callback_data=f"adm:pnd:wg:bshared:{pending_id}"),
            types.InlineKeyboardButton("? ŒÌ— ó ò«‰›Ìê Ãœ«ê«‰Â", callback_data=f"adm:pnd:wg:bdiff:{pending_id}"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:proto:wg:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>À»  œ” Âù«Ì WireGuard »—«Ì ”›«—‘</b>\n\n"
            "¬Ì« Â„Â ò«—»—«‰ «“ Ìò ò«‰›Ìê „‘ —ò «” ›«œÂ „Ìùò‰‰œø", kb)
        return

    # adm:pnd:wg:bshared:{pending_id}  ?  shared wg config for pending
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
            "?? <b>‰«„ ”—ÊÌ” „‘ —ò</b> —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:pnd:wg:bulk:{pending_id}"))
        return

    # adm:pnd:wg:bdiff:{pending_id}  ?  different wg configs for pending
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
            "?? <b>‰«„ ”—ÊÌ” ò«—»— «Ê·</b> —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:pnd:wg:bulk:{pending_id}"))
        return

    if data == "admin:pr:reject_all":
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? —œ Â„Â »«  Ê÷ÌÕ »—«Ì ò«—»—«‰", callback_data="admin:pr:reject_all:note"))
        kb.add(types.InlineKeyboardButton("?? —œ Â„Â »œÊ‰  Ê÷ÌÕ", callback_data="admin:pr:reject_all:do"))
        kb.add(types.InlineKeyboardButton("? ·€Ê", callback_data="admin:pr"))
        send_or_edit(call,
            "?? <b>¬Ì« „ÿ„∆‰ Â” Ìœø</b>\n\n"
            "Â„Â —”ÌœÂ«Ì »——”Ìù‰‘œÂ —œ ŒÊ«Â‰œ ‘œ.\n\n"
            "ï <b>—œ Â„Â »«  Ê÷ÌÕ</b>: Ìò  Ê÷ÌÕ «“ ‘„« „ÌùêÌ—œ Ê »Â ò«—»—«‰ «—”«· „Ìù‘Êœ.\n"
            "ï <b>—œ Â„Â »œÊ‰  Ê÷ÌÕ</b>: ›ﬁÿ ÅÌ«„ —œ ‘œ‰ „Ìù—Êœ° »œÊ‰ œ·Ì·.",
            kb)
        return

    if data == "admin:pr:reject_all:note":
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        state_set(uid, "admin_reject_all_note")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? ·€Ê", callback_data="admin:pr:reject_all"))
        bot.send_message(uid,
            "?? <b> Ê÷ÌÕ —œ —”ÌœÂ«</b>\n\n"
            "„ ‰Ì òÂ „Ìù‰ÊÌ”Ìœ »Â Â„Â ò«—»—«‰ «—”«· „Ìù‘Êœ.\n"
            "„À«·: <i>—”Ìœ  ’ÊÌ— Ê«÷Õ ‰Ì” </i>",
            parse_mode="HTML", reply_markup=kb)
        return

    if data == "admin:pr:reject_all:do":
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        _do_reject_all(call, uid, note=None)
        return

    if data.startswith("adm:pending:addcfg:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        pending_id = int(data.split(":")[3])
        p_row = get_pending_order(pending_id)
        if not p_row:
            bot.answer_callback_query(call.id, "”›«—‘ Ì«›  ‰‘œ.", show_alert=True)
            return
        if p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "«Ì‰ ”›«—‘ ﬁ»·«  ò„Ì· ‘œÂ «” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        pkg = get_package(p_row["package_id"])
        pkg_info = ""
        if pkg:
            pkg_info = (
                f"\n\n?? <b>«ÿ·«⁄«  ÅòÌÃ:</b>\n"
                f"?? ‰Ê⁄: {esc(pkg['type_name'])}\n"
                f"?? ‰«„: {esc(pkg['name'])}\n"
                f"?? ÕÃ„: {fmt_vol(pkg['volume_gb'])}\n"
                f"? „œ : {fmt_dur(pkg['duration_days'])}\n"
                f"?? ﬁÌ„ : {fmt_price(pkg['price'])}  Ê„«‰"
            )
        # Step 1: ask protocol (same as regular config registration)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("?? V2Ray",    callback_data=f"adm:pnd:proto:v2ray:{pending_id}"))
        kb.add(types.InlineKeyboardButton("?? OpenVPN",  callback_data=f"adm:pnd:proto:ovpn:{pending_id}"))
        kb.add(types.InlineKeyboardButton("?? WireGuard", callback_data=f"adm:pnd:proto:wg:{pending_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            f"?? <b>À»  ò«‰›Ìê »—«Ì ”›«—‘ #{pending_id}</b>{pkg_info}\n\n"
            "?? <b>Å—Ê ò· ò«‰›Ìê —« «‰ Œ«» ò‰Ìœ:</b>",
            kb)
        return

    # adm:pnd:proto:{proto}:{pending_id}  ?  ask single/bulk
    if data.startswith("adm:pnd:proto:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        parts = data.split(":")
        proto      = parts[3]            # v2ray | ovpn | wg
        pending_id = int(parts[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«›  ‰‘œ Ì« ﬁ»·«  ò„Ì· ‘œÂ «” .", show_alert=True)
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
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",    callback_data=f"adm:pnd:v2:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:pnd:v2:bulk:{pending_id}"))
        elif proto == "ovpn":
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",    callback_data=f"adm:pnd:ovpn:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}"))
        elif proto == "wg":
            kb.add(types.InlineKeyboardButton("?? À»   òÌ",    callback_data=f"adm:pnd:wg:single:{pending_id}"))
            kb.add(types.InlineKeyboardButton("?? À»  œ” Âù«Ì", callback_data=f"adm:pnd:wg:bulk:{pending_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pending:addcfg:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, f"?? —Ê‘ À»  ò«‰›Ìê —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    # adm:pnd:v2:single:{pending_id}  ?  V2Ray single for pending order
    if data.startswith("adm:pnd:v2:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "v2_single_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  mode=1, pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>‰«„ ”—ÊÌ”</b> —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:pnd:proto:v2ray:{pending_id}"))
        return

    # adm:pnd:v2:bulk:{pending_id}  ?  V2Ray bulk for pending order
    if data.startswith("adm:pnd:v2:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "v2_bulk_init",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("1?? ò«‰›Ìê + ”«» ó  ⁄œ«œ ò„",   callback_data=f"adm:pnd:v2bm:1:{pending_id}"))
        kb.add(types.InlineKeyboardButton("2?? ò«‰›Ìê + ”«» ó  ⁄œ«œ “Ì«œ", callback_data=f"adm:pnd:v2bm:2:{pending_id}"))
        kb.add(types.InlineKeyboardButton("3?? ò«‰›Ìê  ‰Â«",               callback_data=f"adm:pnd:v2bm:3:{pending_id}"))
        kb.add(types.InlineKeyboardButton("4?? ”«»  ‰Â«",                  callback_data=f"adm:pnd:v2bm:4:{pending_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:proto:v2ray:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "?? <b>‰Ê⁄ À»  œ” Âù«Ì V2Ray</b> —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    # adm:pnd:v2bm:{mode}:{pending_id}  ?  bulk mode selected for pending order
    if data.startswith("adm:pnd:v2bm:"):
        if not is_admin(uid): return
        parts = data.split(":")
        mode = int(parts[3]); pending_id = int(parts[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        s = state_data(uid)
        bot.answer_callback_query(call.id)
        if mode in (1, 2, 3):
            state_set(uid, "v2_bulk_pre",
                      package_id=p_row["package_id"],
                      type_id=pkg["type_id"] if pkg else 0,
                      mode=mode, pending_id=pending_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("? »œÊ‰ ÅÌ‘Ê‰œ", callback_data=f"adm:pnd:v2bpfx:skip:{pending_id}"))
            kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:v2:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
            send_or_edit(call,
                "?? <b>ÅÌ‘Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
                "«ê— «» œ«Ì ‰«„ ò«‰›ÌêùÂ« „ ‰ «÷«›Âù«Ì œ«—œ Ê«—œ ò‰Ìœ° œ— €Ì— «Ì‰’Ê—  ´»œÊ‰ ÅÌ‘Ê‰œª »“‰Ìœ.", kb)
        else:  # mode 4: sub only
            state_set(uid, "v2_bulk_data",
                      package_id=p_row["package_id"],
                      type_id=pkg["type_id"] if pkg else 0,
                      mode=4, prefix="", suffix="", pending_id=pending_id)
            send_or_edit(call, _v2_bulk_data_prompt(4), back_button(f"adm:pnd:v2:bulk:{pending_id}"))
        return

    # adm:pnd:v2bpfx:skip:{pending_id}  ?  skip prefix for pending bulk
    if data.startswith("adm:pnd:v2bpfx:skip:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        s = state_data(uid)
        state_set(uid, "v2_bulk_suf",
                  package_id=s["package_id"], type_id=s["type_id"],
                  mode=s["mode"], prefix="", pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("? »œÊ‰ Å”Ê‰œ", callback_data=f"adm:pnd:v2bsfx:skip:{pending_id}"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:v2:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>Å”Ê‰œ Õ–›Ì «“ ‰«„ ò«‰›Ìê</b>\n\n"
            "«ê— «‰ Â«Ì ‰«„ùÂ« „ ‰ «÷«›Âù«Ì œ«—œ Ê«—œ ò‰Ìœ° œ— €Ì— «Ì‰’Ê—  ´»œÊ‰ Å”Ê‰œª »“‰Ìœ.", kb)
        return

    # adm:pnd:v2bsfx:skip:{pending_id}  ?  skip suffix for pending bulk
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

    # adm:pnd:ovpn:single:{pending_id}  ?  OpenVPN single for pending order
    if data.startswith("adm:pnd:ovpn:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        state_set(uid, "ovpn_single_file",
                  package_id=p_row["package_id"], pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:proto:ovpn:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? <b>À»   òÌ OpenVPN »—«Ì ”›«—‘</b>\n\n"
            "›«Ì· Ì« ›«Ì·ùÂ«Ì <code>.ovpn</code> —« «—”«· ò‰Ìœ:", kb)
        return

    # adm:pnd:ovpn:bulk:{pending_id}  ?  OpenVPN bulk for pending order
    if data.startswith("adm:pnd:ovpn:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        state_set(uid, "ovpn_bulk_init",
                  package_id=p_row["package_id"], pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("? »·Â ó Ìò ›«Ì·",    callback_data=f"adm:pnd:ovpn:bshared:{pending_id}"),
            types.InlineKeyboardButton("? ŒÌ— ó ›«Ì· Ãœ«ê«‰Â", callback_data=f"adm:pnd:ovpn:bdiff:{pending_id}"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:proto:ovpn:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>À»  œ” Âù«Ì OpenVPN »—«Ì ”›«—‘</b>\n\n"
            "¬Ì« Â„Â ò«—»—«‰ «“ Ìò ›«Ì· <b>.ovpn</b> „‘ —ò «” ›«œÂ „Ìùò‰‰œø", kb)
        return

    # adm:pnd:ovpn:bshared:{pending_id}  ?  shared ovpn file for pending
    if data.startswith("adm:pnd:ovpn:bshared:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row: return
        state_set(uid, "ovpn_bulk_shared_file",
                  package_id=p_row["package_id"], pending_id=pending_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? ›«Ì· <code>.ovpn</code> „‘ —ò —« «—”«· ò‰Ìœ:\n"
            "<i>«Ì‰ ›«Ì· »—«Ì Â„Â ”›«—‘ùÂ«Ì „‰ Ÿ— «” ›«œÂ „Ìù‘Êœ.</i>", kb)
        return

    # adm:pnd:ovpn:bdiff:{pending_id}  ?  different ovpn files for pending
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
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:ovpn:bulk:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call,
            "?? ›«Ì·ùÂ«Ì <code>.ovpn</code> ò«—»— «Ê· —« «—”«· ò‰Ìœ.\n"
            "Å” «“  √ÌÌœ° »Â ò«—»— »⁄œÌ „Ìù—ÊÌœ.", kb)
        return

    # adm:pnd:wg:single:{pending_id}  ?  WireGuard single for pending order
    if data.startswith("adm:pnd:wg:single:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_single_name",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>‰«„ ”—ÊÌ” WireGuard</b> —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:pnd:proto:wg:{pending_id}"))
        return

    # adm:pnd:wg:bulk:{pending_id}  ?  WireGuard bulk for pending order
    if data.startswith("adm:pnd:wg:bulk:"):
        if not is_admin(uid): return
        pending_id = int(data.split(":")[4])
        p_row = get_pending_order(pending_id)
        if not p_row or p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "”›«—‘ Ì«› / ò„Ì· ‰‘œ.", show_alert=True); return
        pkg = get_package(p_row["package_id"])
        state_set(uid, "wg_bulk_init",
                  package_id=p_row["package_id"],
                  type_id=pkg["type_id"] if pkg else 0,
                  pending_id=pending_id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("? »·Â ó Ìò ò«‰›Ìê",    callback_data=f"adm:pnd:wg:bshared:{pending_id}"),
            types.InlineKeyboardButton("? ŒÌ— ó ò«‰›Ìê Ãœ«ê«‰Â", callback_data=f"adm:pnd:wg:bdiff:{pending_id}"),
        )
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data=f"adm:pnd:proto:wg:{pending_id}", icon_custom_emoji_id="5253997076169115797"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>À»  œ” Âù«Ì WireGuard »—«Ì ”›«—‘</b>\n\n"
            "¬Ì« Â„Â ò«—»—«‰ «“ Ìò ò«‰›Ìê „‘ —ò «” ›«œÂ „Ìùò‰‰œø", kb)
        return

    # adm:pnd:wg:bshared:{pending_id}  ?  shared wg config for pending
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
            "?? <b>‰«„ ”—ÊÌ” „‘ —ò</b> —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:pnd:wg:bulk:{pending_id}"))
        return

    # adm:pnd:wg:bdiff:{pending_id}  ?  different wg configs for pending
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
            "?? <b>‰«„ ”—ÊÌ” ò«—»— «Ê·</b> —« Ê«—œ ò‰Ìœ:",
            back_button(f"adm:pnd:wg:bulk:{pending_id}"))
        return

    if data == "noop":
        bot.answer_callback_query(call.id)
        return

    # ?? Panel management ??????????????????????????????????????????????????????

    if data == "admin:panels":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _show_admin_panels(call)
        return

    # ?? Admin: Add-on purchase settings ?????????????????????????????????????
    if data == "adm:addons":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("??  ⁄ÌÌ‰ ﬁÌ„  ÕÃ„ «÷«›Â",  callback_data="adm:addons:volume"))
        kb.add(types.InlineKeyboardButton("?  ⁄ÌÌ‰ ﬁÌ„  “„«‰ «÷«›Â", callback_data="adm:addons:time"))
        kb.add(types.InlineKeyboardButton("»«“ê‘ ", callback_data="admin:panel",
                                          icon_custom_emoji_id="5253997076169115797"))
        send_or_edit(call, "?? <b>«›“Êœ‰Ì Â«Ì Œ—Ìœ</b>\n\n‰Ê⁄ «›“Êœ‰Ì —« «‰ Œ«» ò‰Ìœ:", kb)
        return

    if data in ("adm:addons:volume", "adm:addons:time"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        addon_kind = "volume" if data.endswith(":volume") else "time"
        bot.answer_callback_query(call.id)
        _render_addon_price_list(call, addon_kind)
        return

    if data in ("adm:addons:volume:toggle", "adm:addons:time:toggle"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        addon_kind = "volume" if ":volume:" in data else "time"
        enabled_key = f"addon_{addon_kind}_enabled"
        cur = setting_get(enabled_key, "1")
        setting_set(enabled_key, "0" if cur == "1" else "1")
        bot.answer_callback_query(call.id, "?  €ÌÌ— «⁄„«· ‘œ.")
        _render_addon_price_list(call, addon_kind)
        return

    if data.startswith("adm:addons:vol:set:") or data.startswith("adm:addons:time:set:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "œ” —”Ì „Ã«“ ‰Ì” .", show_alert=True)
            return
        # Format: adm:addons:vol:set:{type_id}:{normal|res}
        parts     = data.split(":")
        cb_prefix = parts[2]           # 'vol' or 'time'
        type_id   = int(parts[4])
        role      = parts[5]           # 'normal' or 'res'
        addon_kind = "volume" if cb_prefix == "vol" else "time"
        state_set(uid, "admin_addon_price_set",
                  addon_type=addon_kind, type_id=type_id, role=role)
        bot.answer_callback_query(call.id)
        unit_name = "êÌê«»«Ì " if addon_kind == "volume" else "—Ê“"
        send_or_edit(call,
            f"?? ﬁÌ„  Â— {unit_name} —« »Â  Ê„«‰ Ê«—œ ò‰Ìœ\n(0 = —«Ìê«‰):",
            back_button(f"adm:addons:{addon_kind}"))
        return


    if data == "adm:pnl:add":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        state_set(uid, "pnl_add_type")
        bot.answer_callback_query(call.id)
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb_type = InlineKeyboardMarkup()
        kb_type.add(InlineKeyboardButton("?? ”‰«⁄Ì (3x-ui)", callback_data="adm:pnl:add_type:sanaei"))
        send_or_edit(call,
            "?? <b>«›“Êœ‰ Å‰· ÃœÌœ</b>\n\n"
            "„—Õ·Â ?/? ó <b>‰Ê⁄ Å‰·</b>\n"
            "‰Ê⁄ Å‰· „œÌ—Ì  —« «‰ Œ«» ò‰Ìœ:",
            kb_type)
        return

    if data.startswith("adm:pnl:add_type:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        if state_name(uid) != "pnl_add_type":
            bot.answer_callback_query(call.id, "⁄„·Ì«  „‰ﬁ÷Ì ‘œÂ.", show_alert=True)
            return
        panel_type = data.split(":", 3)[3]
        state_set(uid, "pnl_add_name", panel_type=panel_type)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "?? <b>«›“Êœ‰ Å‰· ÃœÌœ</b>\n\n"
            "„—Õ·Â ?/? ó <b>‰«„ Å‰·</b>\n"
            "Ìò ‰«„ œ·ŒÊ«Â »—«Ì ‘‰«”«ÌÌ «Ì‰ Å‰· Ê«—œ ò‰Ìœ:",
            back_button("admin:panels"))
        return

    if data.startswith("adm:pnl:add_proto:"):
        # adm:pnl:add_proto:{http|https}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        sn = state_name(uid)
        if sn != "pnl_add_proto":
            bot.answer_callback_query(call.id, "⁄„·Ì«  „‰ﬁ÷Ì ‘œÂ.", show_alert=True)
            return
        protocol = data.split(":", 3)[3]
        sd = state_data(uid)
        state_set(uid, "pnl_add_host", pnl_name=sd.get("pnl_name", ""), protocol=protocol, panel_type=sd.get("panel_type", "sanaei"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>«›“Êœ‰ Å‰· ÃœÌœ</b>\n\n"
            f"„—Õ·Â ?/? ó <b>¬œ—” IP Ì« œ«„‰Â</b>\n"
            f"Å—Ê ò· «‰ Œ«»ù‘œÂ: <b>{protocol}</b>\n\n"
            "¬œ—” IP Ì« œ«„‰Â ”—Ê— Å‰· —« «—”«· ò‰Ìœ:",
            back_button("admin:panels"))
        return

    if data.startswith("adm:pnl:ef:protocol:"):
        # Edit protocol ó show buttons
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("http",  callback_data=f"adm:pnl:set_proto:http:{panel_id}"),
            InlineKeyboardButton("https", callback_data=f"adm:pnl:set_proto:https:{panel_id}"),
        )
        kb.add(InlineKeyboardButton("·€Ê", callback_data=f"adm:pnl:detail:{panel_id}"))
        send_or_edit(call,
            f"?? <b>ÊÌ—«Ì‘ Å—Ê ò·</b>\n\nÅ‰·: {esc(p['name'])}\n\nÅ—Ê ò· ÃœÌœ —« «‰ Œ«» ò‰Ìœ:",
            kb)
        return

    if data.startswith("adm:pnl:set_proto:"):
        # adm:pnl:set_proto:{http|https}:{panel_id}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        parts     = data.split(":")
        protocol  = parts[3]
        panel_id  = int(parts[4])
        if protocol not in ("http", "https"):
            bot.answer_callback_query(call.id, "Å—Ê ò· ‰«„⁄ »—.", show_alert=True)
            return
        update_panel_field(panel_id, "protocol", protocol)
        bot.answer_callback_query(call.id, f"Å—Ê ò· »Â {protocol}  €ÌÌ— Ì«› .")
        _show_panel_detail(call, panel_id)
        return

    if data.startswith("adm:pnl:ef:"):
        # adm:pnl:ef:{field}:{panel_id}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        parts    = data.split(":")
        field    = parts[3]
        panel_id = int(parts[4])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True)
            return
        field_labels = {
            "name":         "‰«„ Å‰·",
            "host":         "¬œ—” IP / œ«„‰Â",
            "port":         "ÅÊ— ",
            "path":         "„”Ì— „Œ›Ì ó »—«Ì ⁄œ„ ÊÃÊœ / «—”«· ò‰Ìœ",
            "username":     "‰«„ ò«—»—Ì",
            "password":     "—„“ ⁄»Ê—",
            "sub_url_base": "œ«„‰Â ”«» („À«·: http://stareh.parhiiz.top:2096) ó »—«Ì Õ–› /skip «—”«· ò‰Ìœ",
        }
        label = field_labels.get(field, field)
        state_set(uid, "pnl_edit_field", field=field, panel_id=panel_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"?? <b>ÊÌ—«Ì‘ ó {label}</b>\n\nÅ‰·: <b>{esc(p['name'])}</b>\n\n"
            f"„ﬁœ«— ›⁄·Ì: <code>{esc(str(p[field] or ''))}</code>\n\n"
            "„ﬁœ«— ÃœÌœ —« «—”«· ò‰Ìœ:",
            back_button(f"adm:pnl:detail:{panel_id}"))
        return

    if data.startswith("adm:pnl:detail:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_panel_detail(call, panel_id)
        return

    if data.startswith("adm:pnl:toggle:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        parts    = data.split(":")
        panel_id = int(parts[3])
        new_val  = int(parts[4])
        toggle_panel_active(panel_id, new_val)
        label = "›⁄«·" if new_val else "€Ì—›⁄«·"
        bot.answer_callback_query(call.id, f"Å‰· {label} ‘œ.")
        _show_panel_detail(call, panel_id)
        return

    if data.startswith("adm:pnl:del:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("? »·Â° Õ–› ò‰",  callback_data=f"adm:pnl:delok:{panel_id}"),
            InlineKeyboardButton("? ·€Ê",           callback_data=f"adm:pnl:detail:{panel_id}"),
        )
        send_or_edit(call,
            f"?? ¬Ì« „ÿ„∆‰ Â” Ìœ òÂ „ÌùŒÊ«ÂÌœ Å‰· <b>{esc(p['name'])}</b> —« Õ–› ò‰Ìœø",
            kb)
        return

    if data.startswith("adm:pnl:delok:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        delete_panel(panel_id)
        bot.answer_callback_query(call.id, "Å‰· Õ–› ‘œ.")
        _show_admin_panels(call)
        return

    if data.startswith("adm:pnl:recheck:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "œ— Õ«· »——”ÌÖ")
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
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        if state_name(uid) != "pnl_add_save_fail":
            bot.answer_callback_query(call.id, "⁄„·Ì«  „‰ﬁ÷Ì ‘œÂ.", show_alert=True)
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
        bot.answer_callback_query(call.id, "Å‰· »« Ê÷⁄Ì  €Ì—›⁄«· –ŒÌ—Â ‘œ.")
        _show_panel_detail(call, panel_id)
        return

    if data == "adm:pnl:skip_sub_url":
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        if state_name(uid) != "pnl_add_sub_url":
            bot.answer_callback_query(call.id, "⁄„·Ì«  „‰ﬁ÷Ì ‘œÂ.", show_alert=True)
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
        bot.send_message(uid, "? œ— Õ«· »——”Ì « ’«· »Â Å‰·Ö")
        ok, err = _panel_connect_with_retry(
            uid=uid, protocol=protocol, host=host, port=int(port),
            path=path, username=username, password=password,
            panel_name=pnl_name, notify_chat_id=uid,
        )
        if ok:
            state_clear(uid)
            panel_id = add_panel(name=pnl_name or "»œÊ‰ ‰«„", protocol=protocol,
                                 host=host, port=int(port or 2053), path=path,
                                 username=username, password=password, sub_url_base="")
            from ..db import update_panel_status
            update_panel_status(panel_id, "connected", "")
            bot.send_message(uid, "? « ’«· „Ê›ﬁ! Å‰· –ŒÌ—Â ‘œ.")
            _show_panel_detail(call, panel_id)
        else:
            state_set(uid, "pnl_add_save_fail",
                      pnl_name=pnl_name, protocol=protocol, host=host, port=int(port or 2053),
                      path=path, username=username, password=password, sub_url_base="", error=err or "")
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb_fail = InlineKeyboardMarkup()
            kb_fail.row(
                InlineKeyboardButton("?? –ŒÌ—Â »Âù⁄‰Ê«‰ €Ì—›⁄«·", callback_data="adm:pnl:save_as_inactive"),
                InlineKeyboardButton("? ·€Ê", callback_data="adm:pnl:add_cancel"),
            )
            bot.send_message(uid,
                "? <b>« ’«· ‰«„Ê›ﬁ</b>\n\n"
                "„Ìù Ê«‰Ìœ Å‰· —« »Âù’Ê—  €Ì—›⁄«· –ŒÌ—Â ò‰Ìœ  « »⁄œ« ÊÌ—«Ì‘ ‘Êœ.",
                parse_mode="HTML", reply_markup=kb_fail)
        return

    if data == "adm:pnl:add_cancel":
        state_clear(uid)
        bot.answer_callback_query(call.id, "·€Ê ‘œ.")
        _show_admin_panels(call)
        return

    # ?? Panel Client Packages management ??????????????????????????????????????
    if data.startswith("adm:pnl:cpkgs:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_panel_client_packages(call, panel_id)
        return

    if data.startswith("adm:pnl:cpkg:preview:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        cpkg_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_panel_client_package_preview(call, cpkg_id)
        return

    if data.startswith("adm:pnl:cpkg:edit:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        cpkg_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_cpkg_edit_menu(call, cpkg_id)
        return

    if data.startswith("adm:pnl:cpkg:ef:"):
        # adm:pnl:cpkg:ef:{field}:{cpkg_id}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        parts   = data.split(":")
        field   = parts[4]
        cpkg_id = int(parts[5])
        cp = get_panel_client_package(cpkg_id)
        if not cp:
            bot.answer_callback_query(call.id, "ò·«Ì‰  ÅòÌÃ Ì«›  ‰‘œ.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _FIELD_LABELS = {
            "inbound_id":          "?? ‘„«—Â ID «Ì‰»«‰œ",
            "sample_config":       "?? ‰„Ê‰Â ò«‰›Ìê",
            "sample_sub_url":      "?? ‰„Ê‰Â ¬œ—” ”«»”ò—«Ì»",
            "sample_client_name":  "?? ‰«„ ‰„Ê‰Â œ— ›—ê„‰  („À·« emad-tun)",
        }
        try:
            cur_val = cp[field]
        except (KeyError, IndexError):
            cur_val = ""
        cur_display = esc(str(cur_val)[:200]) if cur_val else "<i>Œ«·Ì</i>"
        state_set(uid, f"cpkg_ef_{field}", cpkg_id=cpkg_id, panel_id=cp["panel_id"])
        send_or_edit(call,
            f"?? <b>ÊÌ—«Ì‘ {_FIELD_LABELS.get(field, field)}</b>\n\n"
            f"„ﬁœ«— ›⁄·Ì:\n<code>{cur_display}</code>\n\n"
            "„ﬁœ«— ÃœÌœ —« «—”«· ò‰Ìœ:",
            back_button(f"adm:pnl:cpkg:edit:{cpkg_id}"))
        return

    if data.startswith("adm:pnl:editpanel:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        bot.answer_callback_query(call.id)
        _show_panel_edit_menu(call, panel_id)
        return

    if data.startswith("adm:pnl:cpkg:del:"):
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        cpkg_id = int(data.split(":")[-1])
        cp = get_panel_client_package(cpkg_id)
        if not cp:
            bot.answer_callback_query(call.id, "Ì«›  ‰‘œ.", show_alert=True)
            return
        panel_id = cp["panel_id"]
        delete_panel_client_package(cpkg_id)
        bot.answer_callback_query(call.id, "? ò·«Ì‰  ÅòÌÃ Õ–› ‘œ.")
        _show_panel_client_packages(call, panel_id)
        return

    if data.startswith("adm:pnl:cpkg:add:"):
        # Start the "add client package" wizard
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        panel_id = int(data.split(":")[-1])
        p = get_panel(panel_id)
        if not p:
            bot.answer_callback_query(call.id, "Å‰· Ì«›  ‰‘œ.", show_alert=True)
            return
        state_set(uid, "cpkg_add_inbound", panel_id=panel_id)
        bot.answer_callback_query(call.id)
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        send_or_edit(call,
            f"?? <b>«›“Êœ‰ ò·«Ì‰  ÅòÌÃ ó Å‰·: {esc(p['name'])}</b>\n\n"
            "?? <b>‘„«—Â ID «Ì‰»«‰œ</b> —« «—”«· ò‰Ìœ:\n\n"
            "?? œ— Å‰· À‰«ÌÌ »Â Inbounds »—ÊÌœ Ê ⁄œœ ” Ê‰ ID —« »‰ÊÌ”Ìœ („À·« <code>3</code>).",
            back_button(f"adm:pnl:cpkgs:{panel_id}"))
        return

    if data.startswith("adm:pnl:cpkg:dm:"):
        # Delivery mode selected for new client package
        # format: adm:pnl:cpkg:dm:{mode}:{panel_id}:{inbound_id}
        if not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "œ” —”Ì ‰œ«—Ìœ.", show_alert=True)
            return
        parts     = data.split(":")
        mode      = parts[4]
        panel_id  = int(parts[5])
        inbound_id = int(parts[6])
        if mode not in ("config_only", "sub_only", "both"):
            bot.answer_callback_query(call.id)
            return

        bot.answer_callback_query(call.id)

        # ?? Manual input flow: ask admin to type sample config / sub URL ??????
        if mode in ("config_only", "both"):
            state_set(uid, "cpkg_sample_config", panel_id=panel_id, inbound_id=inbound_id, mode=mode)
            send_or_edit(call,
                "?? <b>ò«‰›Ìê ‰„Ê‰Â</b> —« «—”«· ò‰Ìœ:\n\n"
                "Ìò Œÿ ò«‰›Ìê «“ «Ì‰ «Ì‰»«‰œ òÅÌ ò‰Ìœ.\n"
                "„À«·:\n"
                "<code>vless://abcd1234efgh5678@example.com:2096"
                "?security=tls&type=tcp&sni=example.com#example-config</code>",
                back_button(f"adm:pnl:cpkgs:{panel_id}"))
        else:  # sub_only
            state_set(uid, "cpkg_sample_sub",
                      panel_id=panel_id, inbound_id=inbound_id, mode=mode, sample_config="")
            send_or_edit(call,
                "?? <b>·Ì‰ò ”«» ‰„Ê‰Â</b> —« «—”«· ò‰Ìœ:\n\n"
                "Ìò URL ”«» Ê«ﬁ⁄Ì «“ «Ì‰ «Ì‰»«‰œ òÅÌ ò‰Ìœ.\n"
                "„À«·:\n"
                "<code>http://example.com:2096/sub/abc123xyz456</code>",
                back_button(f"adm:pnl:cpkgs:{panel_id}"))
        return

    bot.answer_callback_query(call.id)

