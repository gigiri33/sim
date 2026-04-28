# -*- coding: utf-8 -*-
import json
import time
import threading
import traceback
import urllib.parse
from datetime import datetime
from telebot import types
from ..config import ADMIN_IDS, ADMIN_PERMS, PERM_FULL_SET, PERM_USER_FULL, CRYPTO_COINS, CRYPTO_API_SYMBOLS, CONFIGS_PER_PAGE
from ..bot_instance import bot
from ..helpers import (
    esc, fmt_price, fmt_vol, fmt_dur, now_str, display_name, display_username, safe_support_url,
    is_admin, admin_has_perm, back_button,
    state_set, state_clear, state_name, state_data, parse_int, normalize_text_number,
)
from ..db import (
    setting_get, setting_set,
    ensure_user, get_user, get_users, count_all_users, set_user_status,
    set_user_agent, update_balance, get_user_detail, get_user_purchases,
    get_purchase, get_available_configs_for_package,
    get_all_types, get_active_types, get_type, add_type, update_type, update_type_description, update_type_active, delete_type,
    get_packages, get_package, add_package, update_package_field, toggle_package_active, delete_package,
    get_registered_packages_stock, get_configs_paginated, count_configs,
    expire_config, add_config,
    assign_config_to_user, reserve_first_config, release_reserved_config,
    update_config_field,
    get_payment, get_pending_payments_page, create_payment, approve_payment, reject_payment, complete_payment,
    get_agency_price, set_agency_price,
    get_agency_price_config, set_agency_price_config,
    get_agency_type_discount, set_agency_type_discount,
    get_agencies,
    get_all_admin_users, get_admin_user, add_admin_user, update_admin_permissions, remove_admin_user,
    get_all_panels, get_panel, add_panel, delete_panel,
    get_panel_packages, add_panel_package, delete_panel_package, update_panel_field,
    get_conn, create_pending_order, get_pending_order, add_config, search_users,
    reset_all_free_tests, user_has_any_test,
    get_all_pinned_messages, get_pinned_message, add_pinned_message,
    update_pinned_message, delete_pinned_message,
    save_pinned_send, get_pinned_sends, delete_pinned_sends,
    save_payment_admin_message, get_payment_admin_messages, delete_payment_admin_messages,
    save_agency_request_message, get_agency_request_messages, delete_agency_request_messages,
    get_all_discount_codes, get_discount_code, add_discount_code,
    toggle_discount_code, update_discount_code_field, delete_discount_code,
    validate_discount_code, record_discount_usage,
    add_voucher_batch, get_all_voucher_batches, get_voucher_batch,
    get_voucher_codes_for_batch, get_voucher_code_by_code,
    redeem_voucher_code, delete_voucher_batch,
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
)
from ..admin.renderers import (
    _show_admin_types, _show_admin_stock, _show_admin_admins_panel,
    _show_perm_selection, _show_admin_users_list, _show_admin_user_detail,
    _show_admin_user_detail_msg, _show_admin_assign_config_type, _fake_call,
    _show_admin_panels, _show_panel_packages, _show_panel_edit,
)
from ..admin.backup import _send_backup


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
        mark     = "Γ£à" if c["id"] in selected else "Γ¼£∩╕Å"
        svc_name = urllib.parse.unquote(c["service_name"] or "")
        kb.add(types.InlineKeyboardButton(f"{mark} {svc_name}", callback_data=f"adm:stk:btog:{c['id']}"))

    if not all_sel:
        kb.add(types.InlineKeyboardButton("Γÿæ∩╕Å ╪º┘å╪¬╪«╪º╪¿ ┘ç┘à┘ç ╪º█î┘å ╪╡┘ü╪¡┘ç", callback_data="adm:stk:bsall"))
    else:
        kb.add(types.InlineKeyboardButton("≡ƒö▓ ┘ä╪║┘ê ╪º┘å╪¬╪«╪º╪¿ ╪º█î┘å ╪╡┘ü╪¡┘ç", callback_data="adm:stk:bclr"))
    if selected:
        kb.add(types.InlineKeyboardButton("≡ƒÜ½ ┘ä╪║┘ê ┘ç┘à┘ç ╪º┘å╪¬╪«╪º╪¿ΓÇî┘ç╪º", callback_data="adm:stk:bclrall"))

    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton("Γ¼à∩╕Å ┘é╪¿┘ä", callback_data=f"adm:stk:bnav:{page-1}"))
    nav_row.append(types.InlineKeyboardButton(f"≡ƒôä {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(types.InlineKeyboardButton("╪¿╪╣╪» Γ₧í∩╕Å", callback_data=f"adm:stk:bnav:{page+1}"))
    if len(nav_row) > 1:
        kb.row(*nav_row)

    if selected:
        sel_count = len(selected)
        if kind in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton(f"≡ƒùæ ╪¡╪░┘ü ({sel_count})", callback_data="adm:stk:bdel"),
                types.InlineKeyboardButton(f"Γ¥î ┘à┘å┘é╪╢█î ({sel_count})", callback_data="adm:stk:bexp"),
            )
        else:
            kb.add(types.InlineKeyboardButton(f"≡ƒùæ ╪¡╪░┘ü ({sel_count})", callback_data="adm:stk:bdel"))

    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:stk:bcanc"))

    kind_labels = {"av": "≡ƒƒó ┘à┘ê╪¼┘ê╪»", "sl": "≡ƒö┤ ┘ü╪▒┘ê╪«╪¬┘ç", "ex": "Γ¥î ┘à┘å┘é╪╢█î"}
    heading = (
        f"Γÿæ∩╕Å <b>╪º┘å╪¬╪«╪º╪¿ ┌»╪▒┘ê┘ç█î ΓÇö {kind_labels.get(kind, '')}</b>\n\n"
        f"Γ£à {len(selected)} ┘à┘ê╪▒╪» ╪º┘å╪¬╪«╪º╪¿ ╪┤╪»┘ç | ╪╡┘ü╪¡┘ç {page+1}/{total_pages} ╪º╪▓ {total} ┌⌐╪º┘å┘ü█î┌»"
    )
    send_or_edit(call, heading, kb)


# ΓöÇΓöÇ Per-user callback serialisation ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
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
    amount_line = f"\n≡ƒÆ░ ┘à╪¿┘ä╪║ ┘é╪º╪¿┘ä ┘╛╪▒╪»╪º╪«╪¬: <b>{fmt_price(amount)}</b> ╪¬┘ê┘à╪º┘å\n" if amount else ""
    return (
        "≡ƒÄƒΓ£¿ <b>┌⌐╪» ╪¬╪«┘ü█î┘ü ┘ê█î┌ÿ┘ç</b> Γ£¿≡ƒÄƒ\n"
        f"{amount_line}\n"
        "≡ƒî╕ ┘╛█î╪┤ ╪º╪▓ ┘╛╪▒╪»╪º╪«╪¬╪î ╪º┌»╪▒ ┌⌐╪» ╪¬╪«┘ü█î┘ü ╪º╪«╪¬╪╡╪º╪╡█î ╪»╪º╪▒█î╪» ┘ê╪º╪▒╪» ┌⌐┘å█î╪»\n"
        "┘ê ╪º╪▓ ┘à╪▓╪º█î╪º█î ┘ê█î┌ÿ┘çΓÇî█î ╪ó┘å ╪¿┘ç╪▒┘çΓÇî┘à┘å╪» ╪┤┘ê█î╪»! ≡ƒÄü\n\n"
        "≡ƒöû ╪ó█î╪º ┌⌐╪» ╪¬╪«┘ü█î┘ü ╪»╪º╪▒█î╪»╪ƒ"
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


def _show_discount_prompt(call, amount=None):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("Γ£à ╪¿┘ä┘ç╪î ╪»╪º╪▒┘à", callback_data="disc:yes"),
        types.InlineKeyboardButton("Γ¥î ╪«█î╪▒╪î ╪º╪»╪º┘à┘ç", callback_data="disc:no"),
    )
    send_or_edit(call, _build_discount_prompt_text(amount), kb)


def _show_purchase_gateways(target, uid, package_id, price, package_row):
    """Build and show gateway selection keyboard for config purchase."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("≡ƒÆ░ ┘╛╪▒╪»╪º╪«╪¬ ╪º╪▓ ┘à┘ê╪¼┘ê╪»█î", callback_data=f"pay:wallet:{package_id}"))
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "≡ƒÆ│ ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:card:{package_id}"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "≡ƒÆÄ ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:crypto:{package_id}"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:tetrapay:{package_id}"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ ┘ê ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:swapwallet_crypto:{package_id}"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TronsPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"pay:tronpays_rial:{package_id}"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"buy:t:{package_row['type_id']}"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    _pkg_sn = package_row['show_name'] if 'show_name' in package_row.keys() else 1
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", price)
    if disc_amount:
        _price_line = (
            f"≡ƒÆ░ ┘é█î┘à╪¬ ╪º╪╡┘ä█î: {fmt_price(orig_amount)} ╪¬┘ê┘à╪º┘å\n"
            f"≡ƒÄƒ ╪¬╪«┘ü█î┘ü: {fmt_price(disc_amount)} ╪¬┘ê┘à╪º┘å\n"
            f"≡ƒÆÜ ┘é█î┘à╪¬ ┘å┘ç╪º█î█î: {fmt_price(price)} ╪¬┘ê┘à╪º┘å"
        )
    else:
        _price_line = f"≡ƒÆ░ ┘é█î┘à╪¬: {fmt_price(price)} ╪¬┘ê┘à╪º┘å"
    text = (
        "≡ƒÆ│ <b>╪º┘å╪¬╪«╪º╪¿ ╪▒┘ê╪┤ ┘╛╪▒╪»╪º╪«╪¬</b>\n\n"
        f"≡ƒº⌐ ┘å┘ê╪╣: {esc(package_row['type_name'])}\n"
        + (f"≡ƒôª ┘╛┌⌐█î╪¼: {esc(package_row['name'])}\n" if _pkg_sn else "")
        + f"≡ƒöï ╪¡╪¼┘à: {fmt_vol(package_row['volume_gb'])}\n"
        f"ΓÅ░ ┘à╪»╪¬: {fmt_dur(package_row['duration_days'])}\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "╪▒┘ê╪┤ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:"
    )
    send_or_edit(target, text, kb)


def _show_renewal_gateways(target, uid, purchase_id, package_id, price, package_row, item):
    """Build and show gateway selection keyboard for renewal."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("≡ƒÆ░ ┘╛╪▒╪»╪º╪«╪¬ ╪º╪▓ ┘à┘ê╪¼┘ê╪»█î", callback_data=f"rpay:wallet:{purchase_id}:{package_id}"))
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "≡ƒÆ│ ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:card:{purchase_id}:{package_id}"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "≡ƒÆÄ ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:crypto:{purchase_id}:{package_id}"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:tetrapay:{purchase_id}:{package_id}"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ ┘ê ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:swapwallet_crypto:{purchase_id}:{package_id}"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TronsPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data=f"rpay:tronpays_rial:{purchase_id}:{package_id}"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"renew:{purchase_id}"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    _pkg_sn_renew = package_row['show_name'] if 'show_name' in package_row.keys() else 1
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", price)
    if disc_amount:
        _price_line = (
            f"≡ƒÆ░ ┘é█î┘à╪¬ ╪º╪╡┘ä█î: {fmt_price(orig_amount)} ╪¬┘ê┘à╪º┘å\n"
            f"≡ƒÄƒ ╪¬╪«┘ü█î┘ü: {fmt_price(disc_amount)} ╪¬┘ê┘à╪º┘å\n"
            f"≡ƒÆÜ ┘é█î┘à╪¬ ┘å┘ç╪º█î█î: {fmt_price(price)} ╪¬┘ê┘à╪º┘å"
        )
    else:
        _price_line = f"≡ƒÆ░ ┘é█î┘à╪¬: {fmt_price(price)} ╪¬┘ê┘à╪º┘å"
    text = (
        "ΓÖ╗∩╕Å <b>╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│</b>\n\n"
        f"≡ƒö« ╪│╪▒┘ê█î╪│ ┘ü╪╣┘ä█î: {esc(urllib.parse.unquote(item['service_name'] or ''))}\n"
        + (f"≡ƒôª ┘╛┌⌐█î╪¼ ╪¬┘à╪»█î╪»: {esc(package_row['name'])}\n" if _pkg_sn_renew else "")
        + f"≡ƒöï ╪¡╪¼┘à: {fmt_vol(package_row['volume_gb'])}\n"
        f"ΓÅ░ ┘à╪»╪¬: {fmt_dur(package_row['duration_days'])}\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "╪▒┘ê╪┤ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:"
    )
    send_or_edit(target, text, kb)


def _show_wallet_gateways(target, uid, amount):
    """Build and show gateway selection keyboard for wallet charge."""
    _gw_labels = []
    kb = types.InlineKeyboardMarkup()
    if is_gateway_available("card", uid) and is_card_info_complete():
        _lbl = setting_get("gw_card_display_name", "").strip() or "≡ƒÆ│ ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:card"))
        _gw_labels.append(("card", _lbl))
    if is_gateway_available("crypto", uid):
        _lbl = setting_get("gw_crypto_display_name", "").strip() or "≡ƒÆÄ ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:crypto"))
        _gw_labels.append(("crypto", _lbl))
    if is_gateway_available("tetrapay", uid):
        _lbl = setting_get("gw_tetrapay_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TetraPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:tetrapay"))
        _gw_labels.append(("tetrapay", _lbl))
    if is_gateway_available("swapwallet_crypto", uid):
        _lbl = setting_get("gw_swapwallet_crypto_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ ┘ê ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä (SwapWallet)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:swapwallet_crypto"))
        _gw_labels.append(("swapwallet_crypto", _lbl))
    if is_gateway_available("tronpays_rial", uid):
        _lbl = setting_get("gw_tronpays_rial_display_name", "").strip() or "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TronsPay)"
        kb.add(types.InlineKeyboardButton(_lbl, callback_data="wallet:charge:tronpays_rial"))
        _gw_labels.append(("tronpays_rial", _lbl))
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
    _range_guide = build_gateway_range_guide(_gw_labels)
    sd = state_data(uid)
    disc_amount = sd.get("discount_amount", 0)
    orig_amount = sd.get("original_amount", amount)
    if disc_amount:
        _price_line = (
            f"≡ƒÆ░ ┘à╪¿┘ä╪║ ╪º╪╡┘ä█î: {fmt_price(orig_amount)} ╪¬┘ê┘à╪º┘å\n"
            f"≡ƒÄƒ ╪¬╪«┘ü█î┘ü: {fmt_price(disc_amount)} ╪¬┘ê┘à╪º┘å\n"
            f"≡ƒÆÜ ┘à╪¿┘ä╪║ ┘å┘ç╪º█î█î: {fmt_price(amount)} ╪¬┘ê┘à╪º┘å"
        )
    else:
        _price_line = f"≡ƒÆ░ ┘à╪¿┘ä╪║: {fmt_price(amount)} ╪¬┘ê┘à╪º┘å"
    text = (
        "≡ƒÆ│ <b>╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä</b>\n\n"
        f"{_price_line}\n\n"
        + (_range_guide + "\n\n" if _range_guide else "")
        + "╪▒┘ê╪┤ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:"
    )
    send_or_edit(target, text, kb)


# ΓöÇΓöÇ Voucher helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
import random
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
        bot.answer_callback_query(call.id, "╪»╪│╪¬┘ç █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
        return
    codes = get_voucher_codes_for_batch(batch_id)
    used_count  = batch["used_count"]
    total_count = batch["total_count"]
    remain      = total_count - used_count
    gift_fa = f"{fmt_price(batch['gift_amount'])} ╪¬┘ê┘à╪º┘å" if batch["gift_type"] == "wallet" else "┌⌐╪º┘å┘ü█î┌»"
    if batch["gift_type"] == "config" and batch["package_id"]:
        pkg = get_package(batch["package_id"])
        if pkg:
            gift_fa = f"┌⌐╪º┘å┘ü█î┌»: {esc(pkg['name'])} | {fmt_vol(pkg['volume_gb'])} | {fmt_dur(pkg['duration_days'])}"
    text = (
        f"≡ƒÄ½ <b>┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç: {esc(batch['name'])}</b>\n\n"
        f"≡ƒÄü ┘å┘ê╪╣ ┘ç╪»█î┘ç: {gift_fa}\n"
        f"≡ƒôè ┌⌐┘ä: {total_count} | ╪º╪│╪¬┘ü╪º╪»┘ç ╪┤╪»┘ç: {used_count} | ┘à╪º┘å╪»┘ç: {remain}\n"
        f"≡ƒôà ╪º█î╪¼╪º╪»: {batch['created_at'][:16]}\n\n"
        "ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ\n"
    )
    code_lines = []
    for vc in codes:
        if vc["is_used"]:
            used_time = (vc["used_at"] or "")[:16]
            code_lines.append(
                f"Γ£à <code>{vc['code']}</code>\n"
                f"   ≡ƒæñ <code>{vc['used_by']}</code>  ≡ƒòÉ {used_time}"
            )
        else:
            code_lines.append(f"Γ¥î <code>{vc['code']}</code>")
    # Telegram message limit 4096 chars ΓÇö split if needed
    MAX_MSG = 3800
    full_codes_text = "\n".join(code_lines)
    combined = text + full_codes_text
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ╪º█î┘å ╪»╪│╪¬┘ç", callback_data=f"admin:vch:del:{batch_id}"),
    )
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:vouchers"))
    if len(combined) <= MAX_MSG:
        send_or_edit(call, combined, kb)
    else:
        # Send header + buttons first, then codes in a follow-up message
        send_or_edit(call, text + "(┌⌐╪»┘ç╪º ╪»╪▒ ┘╛█î╪º┘à ╪¿╪╣╪»█î)", kb)
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
    toggle_lbl = "Γ£à ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç: ┘ü╪╣╪º┘ä" if enabled else "Γ¥î ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç: ╪║█î╪▒┘ü╪╣╪º┘ä"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data="admin:vch:toggle_global"),
        types.InlineKeyboardButton("Γ₧ò ╪º┘ü╪▓┘ê╪»┘å ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç", callback_data="admin:vch:add"),
    )
    for b in batches:
        used  = b["used_count"]
        total = b["total_count"]
        remain = total - used
        kb.row(
            types.InlineKeyboardButton(f"≡ƒÄ½ {b['name']} ({remain}/{total})", callback_data=f"admin:vch:view:{b['id']}"),
            types.InlineKeyboardButton("≡ƒôï ╪º╪╖┘ä╪º╪╣╪º╪¬", callback_data=f"admin:vch:view:{b['id']}"),
        )
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:panel"))
    text = (
        "≡ƒÄ½ <b>┘à╪»█î╪▒█î╪¬ ┌⌐╪º╪▒╪¬ΓÇî┘ç╪º█î ┘ç╪»█î┘ç</b>\n\n"
        f"┘ê╪╢╪╣█î╪¬ ╪│█î╪│╪¬┘à: {'Γ£à ┘ü╪╣╪º┘ä' if enabled else 'Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä'}\n"
        f"╪¬╪╣╪»╪º╪» ╪»╪│╪¬┘çΓÇî┘ç╪º: {len(batches)}\n\n"
        + ("╪»╪│╪¬┘çΓÇî╪º█î ╪½╪¿╪¬ ┘å╪┤╪»┘ç ╪º╪│╪¬." if not batches else "╪¿╪▒╪º█î ┘à╪┤╪º┘ç╪»┘ç ╪¼╪▓╪ª█î╪º╪¬ ╪▒┘ê█î ┘ç╪▒ ╪»╪│╪¬┘ç ┌⌐┘ä█î┌⌐ ┌⌐┘å█î╪»:")
    )
    send_or_edit(call, text, kb)


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
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:panel"))
        send_or_edit(call, "Γ£à ╪▒╪│█î╪» ╪¿╪▒╪▒╪│█î ┘å╪┤╪»┘çΓÇî╪º█î ┘ê╪¼┘ê╪» ┘å╪»╪º╪▒╪».", kb)
        return
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    KIND = {"wallet_charge": "╪┤╪º╪▒┌ÿ ┌⌐█î┘üΓÇî┘╛┘ê┘ä", "buy": "╪«╪▒█î╪»", "renew": "╪¬┘à╪»█î╪»"}
    header = (
        f"≡ƒôï <b>╪▒╪│█î╪»┘ç╪º█î ╪¿╪▒╪▒╪│█î ┘å╪┤╪»┘ç</b>\n"
        f"╪╡┘ü╪¡┘ç {page + 1} ╪º╪▓ {total_pages} | ╪¬╪╣╪»╪º╪» ┌⌐┘ä: {total}\n"
        "ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ\n"
    )
    lines = []
    kb = types.InlineKeyboardMarkup(row_width=3)
    for i, r in enumerate(rows, start=1):
        t_str    = r.get("created_at") or ""
        date_part = t_str[:10] if len(t_str) >= 10 else ""
        time_part = t_str[11:16] if len(t_str) >= 16 else ""
        kind_lbl = KIND.get(r.get("kind", ""), r.get("kind", ""))
        lines.append(
            f"{i}. ≡ƒòÉ {date_part} {time_part} | {kind_lbl} | ≡ƒÆ░ {fmt_price(r['amount'])} ╪¬┘ê┘à╪º┘å"
        )
        kb.row(
            types.InlineKeyboardButton(f"≡ƒôï #{i} ╪¿█î╪┤╪¬╪▒", callback_data=f"admin:pr:det:{r['id']}:{page}"),
            types.InlineKeyboardButton("Γ£à",              callback_data=f"admin:pr:ap:{r['id']}:{page}"),
            types.InlineKeyboardButton("Γ¥î",              callback_data=f"admin:pr:rj:{r['id']}:{page}"),
        )
    text = header + "\n".join(lines)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("ΓùÇ∩╕Å ┘é╪¿┘ä█î", callback_data=f"admin:pr:list:{page - 1}"))
    if (page + 1) < total_pages:
        nav.append(types.InlineKeyboardButton("╪¿╪╣╪»█î Γû╢∩╕Å", callback_data=f"admin:pr:list:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:panel"))
    send_or_edit(call, text, kb)


def _render_discount_admin_list(call, uid):
    """Render the admin discount codes management panel."""
    codes = get_all_discount_codes()
    enabled = setting_get("discount_codes_enabled", "0") == "1"
    toggle_lbl = "Γ£à ┌⌐╪» ╪¬╪«┘ü█î┘ü: ┘ü╪╣╪º┘ä" if enabled else "Γ¥î ┌⌐╪» ╪¬╪«┘ü█î┘ü: ╪║█î╪▒┘ü╪╣╪º┘ä"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data="admin:disc:toggle_global"),
        types.InlineKeyboardButton("Γ₧ò ╪º┘ü╪▓┘ê╪»┘å ┌⌐╪»", callback_data="admin:disc:add"),
    )
    for row in codes:
        status_icon = "Γ£à" if row["is_active"] else "Γ¥î"
        kb.row(
            types.InlineKeyboardButton(f"{status_icon} {row['code']}", callback_data=f"admin:disc:view:{row['id']}"),
            types.InlineKeyboardButton("ΓÜÖ∩╕Å ╪¬┘å╪╕█î┘à╪º╪¬", callback_data=f"admin:disc:view:{row['id']}"),
        )
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:panel"))
    total = len(codes)
    text = (
        "≡ƒÄƒ <b>┘à╪»█î╪▒█î╪¬ ┌⌐╪»┘ç╪º█î ╪¬╪«┘ü█î┘ü</b>\n\n"
        f"┘ê╪╢╪╣█î╪¬ ╪│█î╪│╪¬┘à: {'Γ£à ┘ü╪╣╪º┘ä' if enabled else 'Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä'}\n"
        f"╪¬╪╣╪»╪º╪» ┌⌐╪»┘ç╪º: {total}\n\n"
        + ("┌⌐╪»█î ╪½╪¿╪¬ ┘å╪┤╪»┘ç ╪º╪│╪¬." if not codes else "╪¿╪▒╪º█î ┘à╪»█î╪▒█î╪¬ ┘ç╪▒ ┌⌐╪»╪î ╪▒┘ê█î ╪ó┘å ┌⌐┘ä█î┌⌐ ┌⌐┘å█î╪»:")
    )
    send_or_edit(call, text, kb)


def _render_discount_code_detail(call, uid, code_id):
    """Render detail page for a single discount code."""
    row = get_discount_code(code_id)
    if not row:
        bot.answer_callback_query(call.id, "┌⌐╪» ╪¬╪«┘ü█î┘ü ┘╛█î╪»╪º ┘å╪┤╪».", show_alert=True)
        return
    disc_type_fa = "╪»╪▒╪╡╪»" if row["discount_type"] == "pct" else "┘à╪¿┘ä╪║ ╪½╪º╪¿╪¬"
    disc_val_fa = f"{row['discount_value']}┘¬" if row["discount_type"] == "pct" else f"{fmt_price(row['discount_value'])} ╪¬┘ê┘à╪º┘å"
    max_total = str(row["max_uses_total"]) if row["max_uses_total"] > 0 else "┘å╪º┘à╪¡╪»┘ê╪»"
    max_per = str(row["max_uses_per_user"]) if row["max_uses_per_user"] > 0 else "┘å╪º┘à╪¡╪»┘ê╪»"
    actual_uses = row["actual_uses"]
    status_fa = "Γ£à ┘ü╪╣╪º┘ä" if row["is_active"] else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
    toggle_lbl = "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä ┌⌐┘å" if row["is_active"] else "Γ£à ┘ü╪╣╪º┘ä ┌⌐┘å"
    text = (
        f"≡ƒÄƒ <b>┌⌐╪» ╪¬╪«┘ü█î┘ü: {esc(row['code'])}</b>\n\n"
        f"≡ƒÆ░ ┘å┘ê╪╣ ╪¬╪«┘ü█î┘ü: {disc_type_fa} ΓÇö {disc_val_fa}\n"
        f"≡ƒôè ╪º╪│╪¬┘ü╪º╪»┘ç ╪┤╪»┘ç: {actual_uses} / {max_total}\n"
        f"≡ƒæñ ┘ç╪▒ ┌⌐╪º╪▒╪¿╪▒: {max_per} ╪¿╪º╪▒\n"
        f"≡ƒö╡ ┘ê╪╢╪╣█î╪¬: {status_fa}\n"
        f"≡ƒôà ╪º█î╪¼╪º╪»: {row['created_at'][:10]}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(toggle_lbl, callback_data=f"admin:disc:toggle:{code_id}"),
        types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü", callback_data=f"admin:disc:del:{code_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤ ┌⌐╪»", callback_data=f"admin:disc:edit_code:{code_id}"),
        types.InlineKeyboardButton("Γ£Å∩╕Å ┘à┘é╪»╪º╪▒ ╪¬╪«┘ü█î┘ü", callback_data=f"admin:disc:edit_val:{code_id}"),
    )
    kb.row(
        types.InlineKeyboardButton("Γ£Å∩╕Å ┌⌐┘ä ╪º╪│╪¬┘ü╪º╪»┘ç", callback_data=f"admin:disc:edit_total:{code_id}"),
        types.InlineKeyboardButton("Γ£Å∩╕Å ┘ç╪▒ ┌⌐╪º╪▒╪¿╪▒", callback_data=f"admin:disc:edit_per:{code_id}"),
    )
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:discounts"))
    send_or_edit(call, text, kb)





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
                bot.answer_callback_query(call.id, "Γ£à ╪╣╪╢┘ê█î╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                show_main_menu(call)
            else:
                bot.answer_callback_query(call.id, "Γ¥î ┘ç┘å┘ê╪▓ ╪╣╪╢┘ê ┌⌐╪º┘å╪º┘ä ┘å╪┤╪»┘çΓÇî╪º█î╪».", show_alert=True)
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
            bot.answer_callback_query(call.id, "ΓÅ│ ┘ä╪╖┘ü╪º┘ï ╪╡╪¿╪▒ ┌⌐┘å█î╪»...", show_alert=False)
        except Exception:
            pass
        return

    try:
        ensure_user(call.from_user)

        if not check_channel_membership(uid):
            bot.answer_callback_query(call.id)
            channel_lock_message(call)
            return

        # Restricted user check (admins bypass)
        if not is_admin(uid):
            _u = get_user(uid)
            if _u and _u["status"] == "restricted":
                bot.answer_callback_query(
                    call.id,
                    "≡ƒÜ½ ╪┤┘à╪º ╪º╪▓ ╪▒╪¿╪º╪¬ ┘à╪¡╪»┘ê╪» ╪┤╪»┘çΓÇî╪º█î╪» ┘ê ┘å┘à█îΓÇî╪¬┘ê╪º┘å█î╪» ╪º╪▓ ╪ó┘å ╪º╪│╪¬┘ü╪º╪»┘ç ┌⌐┘å█î╪».",
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
                bot.answer_callback_query(call.id, f"ΓÜá∩╕Å ╪«╪╖╪º: {short}", show_alert=True)
            except Exception:
                try:
                    bot.answer_callback_query(call.id, "╪«╪╖╪º█î█î ╪▒╪« ╪»╪º╪».", show_alert=True)
                except Exception:
                    pass
    finally:
        lock.release()


def _swapwallet_error_inline(call, err_msg):
    """┘å┘à╪º█î╪┤ ╪«╪╖╪º█î SwapWallet ╪¿┘ç ╪╡┘ê╪▒╪¬ inline ╪¿╪º ╪▒╪º┘ç┘å┘à╪º█î ╪¬┘å╪╕█î┘à╪º╪¬."""
    if "APPLICATION_NOT_FOUND" in err_msg or "Application not found" in err_msg or "┌⌐╪│╪¿\u200c┘ê┌⌐╪º╪▒" in err_msg:
        msg = (
            "Γ¥î <b>╪«╪╖╪º: ┌⌐╪│╪¿\u200c┘ê┌⌐╪º╪▒ █î╪º┘ü╪¬ ┘å╪┤╪»</b>\n\n"
            "╪»╪▒┌»╪º┘ç SwapWallet ┘å█î╪º╪▓ ╪¿┘ç █î┌⌐ <b>Application (┌⌐╪│╪¿\u200c┘ê┌⌐╪º╪▒)</b> ╪¼╪»╪º┌»╪º┘å┘ç ╪»╪º╪▒╪».\n"
            "╪º┌⌐╪º┘å╪¬ ╪┤╪«╪╡█î ╪¿╪▒╪º█î ╪»╪▒█î╪º┘ü╪¬ ┘╛╪▒╪»╪º╪«╪¬ ┌⌐╪º╪▒ ┘å┘à█î\u200c┌⌐┘å╪».\n\n"
            "<b>┘à╪▒╪º╪¡┘ä ╪▒┘ü╪╣:</b>\n"
            "1\ufe0f\u20e3 ╪▒╪¿╪º╪¬ @SwapWalletBot ╪▒╪º ╪¿╪º╪▓ ┌⌐┘å█î╪»\n"
            "2\ufe0f\u20e3 ╪¿┘ç ╪¿╪«╪┤ <b>┌⌐╪│╪¿\u200c┘ê┌⌐╪º╪▒</b> ╪¿╪▒┘ê█î╪»\n"
            "3\ufe0f\u20e3 █î┌⌐ ┌⌐╪│╪¿\u200c┘ê┌⌐╪º╪▒ ╪¼╪»█î╪» ╪¿╪│╪º╪▓█î╪»\n"
            "4\ufe0f\u20e3 <b>┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î ╪ó┘å ┌⌐╪│╪¿\u200c┘ê┌⌐╪º╪▒</b> ╪▒╪º ╪»╪▒ ┘╛┘å┘ä ╪º╪»┘à█î┘å ΓåÉ ╪»╪▒┌»╪º┘ç\u200c┘ç╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»"
        )
    else:
        msg = f"Γ¥î <b>╪«╪╖╪º ╪»╪▒ ╪º╪¬╪╡╪º┘ä ╪¿┘ç SwapWallet</b>\n\n<code>{err_msg[:300]}</code>"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
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


# ΓöÇΓöÇ TetraPay auto-verify thread ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
def _tetrapay_auto_verify(payment_id, authority, uid, chat_id, message_id, kind,
                          package_id=None):
    """Background thread: polls TetraPay every 15s for up to 60 minutes."""
    max_tries = 240  # 240 ├ù 15s = 60 minutes
    for attempt in range(max_tries):
        time.sleep(15)
        payment = get_payment(payment_id)
        if not payment or payment["status"] != "pending":
            return  # Already processed by another path
        success, result = verify_tetrapay_order(authority)
        print(f"[TetraPay auto-verify] attempt={attempt+1} payment={payment_id} ok={success} result={result!r}")
        if not success:
            continue
        # Payment confirmed ΓÇö process it
        try:
            if kind == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one thread wins
                    return
                update_balance(uid, payment["amount"])
                state_clear(uid)
                try:
                    bot.edit_message_text(
                        f"Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ┌⌐█î┘ü ┘╛┘ê┘ä ╪┤╪º╪▒┌ÿ ╪┤╪».\n\n≡ƒÆ░ ┘à╪¿┘ä╪║: {fmt_price(payment['amount'])} ╪¬┘ê┘à╪º┘å",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        f"Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ┌⌐█î┘ü ┘╛┘ê┘ä ╪┤╪º╪▒┌ÿ ╪┤╪».\n\n≡ƒÆ░ ┘à╪¿┘ä╪║: {fmt_price(payment['amount'])} ╪¬┘ê┘à╪º┘å",
                        parse_mode="HTML", reply_markup=back_button("main"))

            elif kind == "config_purchase":
                pkg_row = get_package(package_id)
                cfg_id = payment["config_id"]
                if not cfg_id:
                    cfg_id = reserve_first_config(package_id, payment_id)
                if not cfg_id:
                    pending_id = create_pending_order(uid, package_id, payment_id, payment["amount"], "tetrapay")
                    complete_payment(payment_id)
                    state_clear(uid)
                    msg_text = (
                        "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪».\n\n"
                        "ΓÜá∩╕Å <b>┘à┘ê╪¼┘ê╪»█î ╪¬╪¡┘ê█î┘ä ┘ü┘ê╪▒█î ╪▒╪¿╪º╪¬ ╪¿┘ç ╪º╪¬┘à╪º┘à ╪▒╪│█î╪».</b>\n"
                        "╪»╪▒╪«┘ê╪º╪│╪¬ ╪┤┘à╪º ╪¿╪▒╪º█î ╪º╪»┘à█î┘å ╪º╪▒╪│╪º┘ä ╪┤╪». ╪»╪▒ ┌⌐┘à╪¬╪▒█î┘å ┘ü╪▒╪╡╪¬ ┌⌐╪º┘å┘ü█î┌» ╪┤┘à╪º ╪¬╪¡┘ê█î┘ä ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                        "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à."
                    )
                    try:
                        bot.edit_message_text(msg_text, chat_id, message_id, parse_mode="HTML",
                                              reply_markup=back_button("main"))
                    except Exception:
                        bot.send_message(uid, msg_text, parse_mode="HTML", reply_markup=back_button("main"))
                    notify_pending_order_to_admins(pending_id, uid, pkg_row, payment["amount"], "tetrapay")
                    return
                purchase_id_new = assign_config_to_user(cfg_id, uid, package_id, payment["amount"], "tetrapay", is_test=0)
                complete_payment(payment_id)
                state_clear(uid)
                try:
                    bot.edit_message_text("Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ╪│╪▒┘ê█î╪│ ╪ó┘à╪º╪»┘ç ╪º╪│╪¬.",
                                          chat_id, message_id, parse_mode="HTML",
                                          reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ╪│╪▒┘ê█î╪│ ╪ó┘à╪º╪»┘ç ╪º╪│╪¬.",
                                     reply_markup=back_button("main"))
                deliver_purchase_message(chat_id, purchase_id_new)
                admin_purchase_notify("TetraPay", get_user(uid), pkg_row, purchase_id=purchase_id_new)

            elif kind == "renewal":
                pkg_row = get_package(package_id)
                cfg_id = payment["config_id"]
                with get_conn() as conn:
                    row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (cfg_id,)).fetchone()
                pid = row["purchase_id"] if row else 0
                item = get_purchase(pid) if pid else None
                complete_payment(payment_id)
                state_clear(uid)
                msg_text = (
                    "Γ£à <b>╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪º╪▒╪│╪º┘ä ╪┤╪»</b>\n\n"
                    "≡ƒöä ╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│ ╪┤┘à╪º ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪½╪¿╪¬ ┘ê ╪¿╪▒╪º█î ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪º╪▒╪│╪º┘ä ╪┤╪».\n"
                    "ΓÅ│ ┘ä╪╖┘ü╪º┘ï ┌⌐┘à█î ╪╡╪¿╪▒ ┌⌐┘å█î╪»╪î ┘╛╪│ ╪º╪▓ ╪º┘å╪¼╪º┘à ╪¬┘à╪»█î╪» ╪¿┘ç ╪┤┘à╪º ╪º╪╖┘ä╪º╪╣ ╪»╪º╪»┘ç ╪«┘ê╪º┘ç╪» ╪┤╪».\n\n"
                    "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ┘ê ╪┤┌⌐█î╪¿╪º█î█î ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à."
                )
                try:
                    bot.edit_message_text(msg_text, chat_id, message_id, parse_mode="HTML",
                                          reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid, msg_text, parse_mode="HTML", reply_markup=back_button("main"))
                if item:
                    admin_renewal_notify(uid, item, pkg_row, payment["amount"], "TetraPay")

        except Exception as e:
            print("TETRAPAY_AUTO_VERIFY_ERROR:", e)
        return  # Processed (success or error)

    # Timeout ΓÇö not verified after 60 minutes
    payment = get_payment(payment_id)
    if payment and payment["status"] == "pending":
        state_clear(uid)
        verify_cb = f"rpay:tetrapay:verify:{payment_id}" if kind == "renewal" else f"pay:tetrapay:verify:{payment_id}"
        timeout_msg = (
            "ΓÅ░ <b>╪¿╪▒╪▒╪│█î ╪«┘ê╪»┌⌐╪º╪▒ ┘╛╪▒╪»╪º╪«╪¬ ┘╛╪º█î╪º┘å █î╪º┘ü╪¬</b>\n\n"
            "┘ê┘é╪¬█î ┘╛╪▒╪»╪º╪«╪¬ΓÇî╪¬┘ê┘å ╪¬┘ê ╪▒╪¿╪º╪¬ ╪¬╪¬╪▒╪º┘╛█î ╪¬╪º█î█î╪» ╪┤╪»╪î ╪»┌⌐┘à┘ç <b>╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬</b> ╪▓█î╪▒ ╪▒╪º ╪¿╪▓┘å█î╪» "
            "╪¬╪º ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»┘ç ┘ê ╪º╪»╪º┘à┘ç ╪╣┘à┘ä█î╪º╪¬ ╪º┘å╪¼╪º┘à ╪┤┘ê╪».\n\n"
            "╪º┌»╪▒ ┘à╪¿┘ä╪║ ╪º╪▓ ╪¡╪│╪º╪¿ ╪┤┘à╪º ┌⌐╪│╪▒ ╪┤╪»┘ç ┘ê ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ┘å╪┤╪»┘ç╪î ┘ä╪╖┘ü╪º┘ï ╪¿╪º ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪¬┘à╪º╪│ ╪¿┌»█î╪▒█î╪»."
        )
        timeout_kb = types.InlineKeyboardMarkup()
        timeout_kb.add(types.InlineKeyboardButton("≡ƒöì ╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬", callback_data=verify_cb))
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


# ΓöÇΓöÇ TronPays Rial auto-verify thread ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
def _tronpays_rial_auto_verify(payment_id, invoice_id, uid, chat_id, message_id, kind,
                               package_id=None):
    """Background thread: polls TronPays every 15s for up to 60 minutes."""
    max_tries = 240  # 240 ├ù 15s = 60 minutes
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
                    bot.edit_message_text(
                        f"Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ┌⌐█î┘ü ┘╛┘ê┘ä ╪┤╪º╪▒┌ÿ ╪┤╪».\n\n≡ƒÆ░ ┘à╪¿┘ä╪║: {fmt_price(payment['amount'])} ╪¬┘ê┘à╪º┘å",
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid,
                        f"Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ┌⌐█î┘ü ┘╛┘ê┘ä ╪┤╪º╪▒┌ÿ ╪┤╪».\n\n≡ƒÆ░ ┘à╪¿┘ä╪║: {fmt_price(payment['amount'])} ╪¬┘ê┘à╪º┘å",
                        parse_mode="HTML", reply_markup=back_button("main"))

            elif kind == "config_purchase":
                pkg_row = get_package(package_id)
                cfg_id = payment["config_id"]
                if not cfg_id:
                    cfg_id = reserve_first_config(package_id, payment_id)
                if not cfg_id:
                    pending_id = create_pending_order(uid, package_id, payment_id, payment["amount"], "tronpays_rial")
                    complete_payment(payment_id)
                    state_clear(uid)
                    msg_text = (
                        "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪».\n\n"
                        "ΓÜá∩╕Å <b>┘à┘ê╪¼┘ê╪»█î ╪¬╪¡┘ê█î┘ä ┘ü┘ê╪▒█î ╪▒╪¿╪º╪¬ ╪¿┘ç ╪º╪¬┘à╪º┘à ╪▒╪│█î╪».</b>\n"
                        "╪»╪▒╪«┘ê╪º╪│╪¬ ╪┤┘à╪º ╪¿╪▒╪º█î ╪º╪»┘à█î┘å ╪º╪▒╪│╪º┘ä ╪┤╪». ╪»╪▒ ┌⌐┘à╪¬╪▒█î┘å ┘ü╪▒╪╡╪¬ ┌⌐╪º┘å┘ü█î┌» ╪┤┘à╪º ╪¬╪¡┘ê█î┘ä ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                        "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à."
                    )
                    try:
                        bot.edit_message_text(msg_text, chat_id, message_id, parse_mode="HTML",
                                              reply_markup=back_button("main"))
                    except Exception:
                        bot.send_message(uid, msg_text, parse_mode="HTML", reply_markup=back_button("main"))
                    notify_pending_order_to_admins(pending_id, uid, pkg_row, payment["amount"], "tronpays_rial")
                    return
                purchase_id_new = assign_config_to_user(cfg_id, uid, package_id, payment["amount"], "tronpays_rial", is_test=0)
                complete_payment(payment_id)
                state_clear(uid)
                try:
                    bot.edit_message_text("Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ╪│╪▒┘ê█î╪│ ╪ó┘à╪º╪»┘ç ╪º╪│╪¬.",
                                          chat_id, message_id, parse_mode="HTML",
                                          reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ╪│╪▒┘ê█î╪│ ╪ó┘à╪º╪»┘ç ╪º╪│╪¬.",
                                     reply_markup=back_button("main"))
                deliver_purchase_message(chat_id, purchase_id_new)
                admin_purchase_notify("TronPays", get_user(uid), pkg_row, purchase_id=purchase_id_new)

            elif kind == "renewal":
                pkg_row = get_package(package_id)
                cfg_id = payment["config_id"]
                with get_conn() as conn:
                    row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (cfg_id,)).fetchone()
                pid = row["purchase_id"] if row else 0
                item = get_purchase(pid) if pid else None
                complete_payment(payment_id)
                state_clear(uid)
                msg_text = (
                    "Γ£à <b>╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪º╪▒╪│╪º┘ä ╪┤╪»</b>\n\n"
                    "≡ƒöä ╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│ ╪┤┘à╪º ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪½╪¿╪¬ ┘ê ╪¿╪▒╪º█î ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪º╪▒╪│╪º┘ä ╪┤╪».\n"
                    "ΓÅ│ ┘ä╪╖┘ü╪º┘ï ┌⌐┘à█î ╪╡╪¿╪▒ ┌⌐┘å█î╪»╪î ┘╛╪│ ╪º╪▓ ╪º┘å╪¼╪º┘à ╪¬┘à╪»█î╪» ╪¿┘ç ╪┤┘à╪º ╪º╪╖┘ä╪º╪╣ ╪»╪º╪»┘ç ╪«┘ê╪º┘ç╪» ╪┤╪».\n\n"
                    "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ┘ê ╪┤┌⌐█î╪¿╪º█î█î ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à."
                )
                try:
                    bot.edit_message_text(msg_text, chat_id, message_id, parse_mode="HTML",
                                          reply_markup=back_button("main"))
                except Exception:
                    bot.send_message(uid, msg_text, parse_mode="HTML", reply_markup=back_button("main"))
                if item:
                    admin_renewal_notify(uid, item, pkg_row, payment["amount"], "TronPays")

        except Exception as e:
            print("TRONPAYS_RIAL_AUTO_VERIFY_ERROR:", e)
        return

    # Timeout
    payment = get_payment(payment_id)
    if payment and payment["status"] == "pending":
        state_clear(uid)
        verify_cb = f"rpay:tronpays_rial:verify:{payment_id}" if kind == "renewal" else f"pay:tronpays_rial:verify:{payment_id}"
        timeout_msg = (
            "ΓÅ░ <b>╪¿╪▒╪▒╪│█î ╪«┘ê╪»┌⌐╪º╪▒ ┘╛╪▒╪»╪º╪«╪¬ ┘╛╪º█î╪º┘å █î╪º┘ü╪¬</b>\n\n"
            "┘ê┘é╪¬█î ┘╛╪▒╪»╪º╪«╪¬ΓÇî╪¬┘ê┘å ╪¬┘ê TronPays ╪¬╪º█î█î╪» ╪┤╪»╪î ╪»┌⌐┘à┘ç <b>╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬</b> ╪▓█î╪▒ ╪▒╪º ╪¿╪▓┘å█î╪» "
            "╪¬╪º ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»┘ç ┘ê ╪º╪»╪º┘à┘ç ╪╣┘à┘ä█î╪º╪¬ ╪º┘å╪¼╪º┘à ╪┤┘ê╪».\n\n"
            "╪º┌»╪▒ ┘à╪¿┘ä╪║ ╪º╪▓ ╪¡╪│╪º╪¿ ╪┤┘à╪º ┌⌐╪│╪▒ ╪┤╪»┘ç ┘ê ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ┘å╪┤╪»┘ç╪î ┘ä╪╖┘ü╪º┘ï ╪¿╪º ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪¬┘à╪º╪│ ╪¿┌»█î╪▒█î╪»."
        )
        timeout_kb = types.InlineKeyboardMarkup()
        timeout_kb.add(types.InlineKeyboardButton("≡ƒöì ╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬", callback_data=verify_cb))
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

    # ΓöÇΓöÇ Discount code flow ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "disc:yes":
        sn = state_name(uid)
        sd = state_data(uid)
        if sn not in {"buy_select_method", "renew_select_method", "wallet_charge_method"}:
            bot.answer_callback_query(call.id, "╪»╪▒╪«┘ê╪º╪│╪¬█î ╪¿╪▒╪º█î ╪º╪╣┘à╪º┘ä ╪¬╪«┘ü█î┘ü ┘╛█î╪»╪º ┘å╪┤╪».", show_alert=True)
            return
        original_amount = sd.get("original_amount", sd.get("amount", 0))
        new_sd = dict(sd)
        new_sd["prev_state"] = sn
        new_sd["original_amount"] = original_amount
        state_set(uid, "await_discount_code", **new_sd)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬ (╪¿╪»┘ê┘å ╪¬╪«┘ü█î┘ü)", callback_data="disc:no"))
        send_or_edit(call,
            "≡ƒÄƒ <b>┌⌐╪» ╪¬╪«┘ü█î┘ü</b>\n\n"
            "Γ£ì∩╕Å ┘ä╪╖┘ü╪º┘ï ┌⌐╪» ╪¬╪«┘ü█î┘ü ╪«┘ê╪» ╪▒╪º ╪¬╪º█î┘╛ ┌⌐╪▒╪»┘ç ┘ê ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:\n\n"
            "≡ƒÆí <i>┌⌐╪»┘ç╪º ┘à╪╣┘à┘ê┘ä╪º┘ï ╪¬╪▒┌⌐█î╪¿█î ╪º╪▓ ╪¡╪▒┘ê┘ü ╪º┘å┌»┘ä█î╪│█î ┘ê ╪º╪╣╪»╪º╪» ┘ç╪│╪¬┘å╪».</i>",
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
        if sn == "wallet_charge_method":
            amount = int(sd.get("amount", 0) or 0)
            _show_wallet_gateways(call, uid, amount)
            return
        bot.answer_callback_query(call.id, "╪»╪▒╪«┘ê╪º╪│╪¬█î ╪¿╪▒╪º█î ╪º╪»╪º┘à┘ç ┘╛█î╪»╪º ┘å╪┤╪».", show_alert=True)
        return

    # ΓöÇΓöÇ Agency request ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "agency:request":
        user = get_user(uid)
        if user and user["is_agent"]:
            bot.answer_callback_query(call.id, "╪┤┘à╪º ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ┘å┘à╪º█î┘å╪»┘ç ┘ç╪│╪¬█î╪».", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒôñ ╪º╪▒╪│╪º┘ä ╪»╪▒╪«┘ê╪º╪│╪¬ (╪¿╪»┘ê┘å ┘à╪¬┘å)", callback_data="agency:send_empty"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        state_set(uid, "agency_request_text")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒñ¥ <b>╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î</b>\n\n"
            "┘ä╪╖┘ü╪º┘ï ┘à╪¬┘å ╪»╪▒╪«┘ê╪º╪│╪¬ ╪«┘ê╪» ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪». ┘à┘ê╪º╪▒╪» ╪▓█î╪▒ ╪▒╪º ╪»╪▒ ┘à╪¬┘å ╪░┌⌐╪▒ ┌⌐┘å█î╪»:\n\n"
            "≡ƒôè ┘à█î╪▓╪º┘å ┘ü╪▒┘ê╪┤ ╪┤┘à╪º ╪»╪▒ ╪▒┘ê╪▓ █î╪º ┘ç┘ü╪¬┘ç\n"
            "≡ƒôó ┌⌐╪º┘å╪º┘ä █î╪º ┘ü╪▒┘ê╪┤┌»╪º┘ç█î ┌⌐┘ç ╪»╪º╪▒█î╪» (╪ó╪»╪▒╪│ ┌⌐╪º┘å╪º┘ä ╪¬┘ä┌»╪▒╪º┘à)\n"
            "≡ƒÄº ╪ó█î╪»█î ┘╛╪┤╪¬█î╪¿╪º┘å█î ┘à╪¼┘à┘ê╪╣┘ç ╪┤┘à╪º\n"
            "≡ƒô¥ ┘ç╪▒ ╪¬┘ê╪╢█î╪¡ ╪»█î┌»╪▒█î ┌⌐┘ç ┘ä╪º╪▓┘à ┘à█îΓÇî╪»╪º┘å█î╪»\n\n"
            "╪º┌»╪▒ ┘å┘à█îΓÇî╪«┘ê╪º┘ç█î╪» ┘à╪¬┘å█î ╪¿┘å┘ê█î╪│█î╪»╪î ╪»┌⌐┘à┘ç ╪▓█î╪▒ ╪▒╪º ╪¿╪▓┘å█î╪»:", kb)
        return

    if data == "agency:send_empty":
        state_clear(uid)
        user = get_user(uid)
        if user and user["is_agent"]:
            bot.answer_callback_query(call.id, "╪┤┘à╪º ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ┘å┘à╪º█î┘å╪»┘ç ┘ç╪│╪¬█î╪».", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, "Γ£à ╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ╪┤┘à╪º ╪º╪▒╪│╪º┘ä ╪┤╪».\nΓÅ│ ┘ä╪╖┘ü╪º┘ï ┘à┘å╪¬╪╕╪▒ ╪¿╪▒╪▒╪│█î ╪º╪»┘à█î┘å ╪¿╪º╪┤█î╪».", back_button("main"))
        # Notify admins
        text = (
            f"≡ƒñ¥ <b>╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ╪¼╪»█î╪»</b>\n\n"
            f"≡ƒæñ ┘å╪º┘à: {esc(user['full_name'])}\n"
            f"≡ƒåö ┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î: {esc(display_username(user['username']))}\n"
            f"≡ƒöó ╪ó█î╪»█î: <code>{user['user_id']}</code>\n\n"
            f"≡ƒô¥ ┘à╪¬┘å ╪»╪▒╪«┘ê╪º╪│╪¬: <i>╪¿╪»┘ê┘å ┘à╪¬┘å</i>"
        )
        admin_kb = types.InlineKeyboardMarkup()
        admin_kb.row(
            types.InlineKeyboardButton("Γ£à ╪¬╪ú█î█î╪»", callback_data=f"agency:approve_now:{uid}"),
            types.InlineKeyboardButton("Γ¥î ╪▒╪»", callback_data=f"agency:reject_now:{uid}"),
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
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_set(uid, "agency_approve_note", target_user_id=target_uid)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("ΓÅ¡ ╪¿╪»┘ê┘å ┘╛█î╪º┘à", callback_data=f"agency:approve_now:{target_uid}"))
        bot.send_message(call.message.chat.id,
            f"Γ£à ╪»╪▒ ╪¡╪º┘ä ╪¬╪ú█î█î╪» ┘å┘à╪º█î┘å╪»┌»█î ┌⌐╪º╪▒╪¿╪▒ <code>{target_uid}</code>\n\n"
            "╪º┌»╪▒ ┘à█îΓÇî╪«┘ê╪º┘ç█î╪» ┘╛█î╪º┘à█î ╪¿╪▒╪º█î ┌⌐╪º╪▒╪¿╪▒ ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»╪î ┘à╪¬┘å ╪▒╪º ╪¿┘å┘ê█î╪│█î╪».\n"
            "╪»╪▒ ╪║█î╪▒ ╪º█î┘å ╪╡┘ê╪▒╪¬ ╪»┌⌐┘à┘ç ╪▓█î╪▒ ╪▒╪º ╪¿╪▓┘å█î╪»:", reply_markup=kb)
        return

    if data.startswith("agency:approve_now:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_clear(uid)
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_agent=1 WHERE user_id=?", (target_uid,))
        default_pct = int(setting_get("agency_default_discount_pct", "20") or "20")
        if default_pct > 0:
            set_agency_price_config(target_uid, "global", "pct", default_pct)
        bot.answer_callback_query(call.id, "Γ£à ┘å┘à╪º█î┘å╪»┌»█î ╪¬╪ú█î█î╪» ╪┤╪».")
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
                "≡ƒÄë <b>╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪»!</b>\n\n╪º┌⌐┘å┘ê┘å ╪┤┘à╪º ┘å┘à╪º█î┘å╪»┘ç ┘ç╪│╪¬█î╪».",
                parse_mode="HTML")
        except Exception:
            pass
        # Log to agency_log topic
        user_row = get_user(target_uid)
        send_to_topic("agency_log",
            f"Γ£à <b>┘å┘à╪º█î┘å╪»┌»█î ╪¬╪ú█î█î╪» ╪┤╪»</b>\n\n"
            f"≡ƒæñ ┘å╪º┘à: {esc(user_row['full_name'] if user_row else str(target_uid))}\n"
            f"≡ƒåö ┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î: {esc(user_row['username'] or '┘å╪»╪º╪▒╪»' if user_row else '-')}\n"
            f"≡ƒåö ╪ó█î╪»█î: <code>{target_uid}</code>\n"
            f"≡ƒôè ╪¬╪«┘ü█î┘ü ┘╛█î╪┤ΓÇî┘ü╪▒╪╢: <b>{default_pct}%</b>\n"
            f"╪¬╪ú█î█î╪»┌⌐┘å┘å╪»┘ç: <code>{uid}</code>"
        )
        # If called from admin DM, show user detail panel
        if call.message.chat.type == "private":
            _show_admin_user_detail(call, target_uid)
        else:
            try:
                bot.send_message(call.message.chat.id,
                    f"Γ£à ┘å┘à╪º█î┘å╪»┌»█î ┌⌐╪º╪▒╪¿╪▒ <code>{target_uid}</code> ╪¬╪ú█î█î╪» ╪┤╪».",
                    message_thread_id=call.message.message_thread_id,
                    parse_mode="HTML")
            except Exception:
                pass
        return

    if data.startswith("agency:reject_now:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        bot.answer_callback_query(call.id, "Γ¥î ╪▒╪» ╪┤╪».")
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
                "Γ¥î <b>╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ╪┤┘à╪º ╪▒╪» ╪┤╪».</b>",
                parse_mode="HTML")
        except Exception:
            pass
        # Log to agency_log topic
        user_row = get_user(target_uid)
        send_to_topic("agency_log",
            f"Γ¥î <b>┘å┘à╪º█î┘å╪»┌»█î ╪▒╪» ╪┤╪»</b>\n\n"
            f"≡ƒæñ ┘å╪º┘à: {esc(user_row['full_name'] if user_row else str(target_uid))}\n"
            f"≡ƒåö ╪ó█î╪»█î: <code>{target_uid}</code>\n"
            f"╪▒╪»┌⌐┘å┘å╪»┘ç: <code>{uid}</code>"
        )
        return

    if data.startswith("agency:reject:"):
        if not is_admin(uid) or not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        target_uid = int(data.split(":")[2])
        state_set(uid, "agency_reject_reason", target_user_id=target_uid)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(call.message.chat.id,
            f"Γ¥î ╪»╪▒ ╪¡╪º┘ä ╪▒╪» ╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ┌⌐╪º╪▒╪¿╪▒ <code>{target_uid}</code>\n\n"
            "┘ä╪╖┘ü╪º┘ï ╪»┘ä█î┘ä ╪▒╪» ╪▒╪º ╪¿┘å┘ê█î╪│█î╪»:")
        return

    if data == "my_configs":
        bot.answer_callback_query(call.id)
        show_my_configs(call, uid)
        return

    if data.startswith("mycfg:"):
        purchase_id = int(data.split(":")[1])
        item = get_purchase(purchase_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        deliver_purchase_message(call.message.chat.id, purchase_id)
        return

    # ΓöÇΓöÇ Renewal flow ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("renew:") and not data.startswith("renew:p:") and not data.startswith("renew:confirm:"):
        if setting_get("manual_renewal_enabled", "1") != "1" and not is_admin(uid):
            bot.answer_callback_query(call.id, "Γ¢ö ╪¬┘à╪»█î╪» ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ╪║█î╪▒┘ü╪╣╪º┘ä ╪º╪│╪¬.", show_alert=True)
            return
        purchase_id = int(data.split(":")[1])
        item = get_purchase(purchase_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        # Show packages of same type for renewal
        with get_conn() as conn:
            type_id = conn.execute("SELECT type_id FROM packages WHERE id=?", (item["package_id"],)).fetchone()["type_id"]
        packages = [p for p in get_packages(type_id=type_id) if p["price"] > 0]
        kb = types.InlineKeyboardMarkup()
        user = get_user(uid)
        for p in packages:
            price = get_effective_price(uid, p)
            _sn = p['show_name'] if 'show_name' in p.keys() else 1
            _name_part = f"{p['name']} | " if _sn else ""
            title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)} ╪¬"
            kb.add(types.InlineKeyboardButton(title, callback_data=f"renew:p:{purchase_id}:{p['id']}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"mycfg:{purchase_id}"))
        bot.answer_callback_query(call.id)
        agent_note = "\n\n≡ƒñ¥ <i>╪º█î┘å ┘é█î┘à╪¬ΓÇî┘ç╪º ┘à╪«╪╡┘ê╪╡ ┘ç┘à┌⌐╪º╪▒█î ╪┤┘à╪º╪│╪¬</i>" if user and user["is_agent"] else ""
        if not packages:
            send_or_edit(call, "≡ƒô¡ ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ┘╛┌⌐█î╪¼█î ╪¿╪▒╪º█î ╪¬┘à╪»█î╪» ┘à┘ê╪¼┘ê╪» ┘å█î╪│╪¬.", kb)
        else:
            send_or_edit(call, f"ΓÖ╗∩╕Å <b>╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│</b>\n\n┘╛┌⌐█î╪¼ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪¿╪▒╪º█î ╪¬┘à╪»█î╪» ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:{agent_note}", kb)
        return

    if data.startswith("renew:p:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        price = get_effective_price(uid, package_row)
        state_set(uid, "renew_select_method",
                  package_id=package_id, amount=price, original_amount=price,
                  kind="renewal", purchase_id=purchase_id)
        bot.answer_callback_query(call.id)
        if setting_get("discount_codes_enabled", "0") == "1":
            _show_discount_prompt(call, price)
            return
        _show_renewal_gateways(call, uid, purchase_id, package_id, price, package_row, item)
        return


    # ΓöÇΓöÇ Renewal payment handlers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("rpay:wallet:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        user = get_user(uid)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if user["balance"] < price:
            bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ┌⌐█î┘ü ┘╛┘ê┘ä ┌⌐╪º┘ü█î ┘å█î╪│╪¬.", show_alert=True)
            return
        update_balance(uid, -price)
        payment_id = create_payment("renewal", uid, package_id, price, "wallet",
                                     status="completed", config_id=item["config_id"])
        complete_payment(payment_id)
        bot.answer_callback_query(call.id, "┘╛╪▒╪»╪º╪«╪¬ ┘à┘ê┘ü┘é ╪¿┘ê╪».")
        send_or_edit(call,
            "Γ£à <b>╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪º╪▒╪│╪º┘ä ╪┤╪»</b>\n\n"
            "≡ƒöä ╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│ ╪┤┘à╪º ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪½╪¿╪¬ ┘ê ╪¿╪▒╪º█î ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪º╪▒╪│╪º┘ä ╪┤╪».\n"
            "ΓÅ│ ┘ä╪╖┘ü╪º┘ï ┌⌐┘à█î ╪╡╪¿╪▒ ┌⌐┘å█î╪»╪î ┘╛╪│ ╪º╪▓ ╪º┘å╪¼╪º┘à ╪¬┘à╪»█î╪» ╪¿┘ç ╪┤┘à╪º ╪º╪╖┘ä╪º╪╣ ╪»╪º╪»┘ç ╪«┘ê╪º┘ç╪» ╪┤╪».\n\n"
            "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ┘ê ╪┤┌⌐█î╪¿╪º█î█î ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à.",
            back_button("main"))
        admin_renewal_notify(uid, item, package_row, price, "┌⌐█î┘ü ┘╛┘ê┘ä")
        state_clear(uid)
        return

    if data.startswith("rpay:card:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        card  = setting_get("payment_card", "")
        bank  = setting_get("payment_bank", "")
        owner = setting_get("payment_owner", "")
        if not card:
            bot.answer_callback_query(call.id, "╪º╪╖┘ä╪º╪╣╪º╪¬ ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪½╪¿╪¬ ┘å╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("card", price):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪º█î┘å ╪»╪▒┌»╪º┘ç ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        payment_id = create_payment("renewal", uid, package_id, price, "card", status="pending",
                                     config_id=item["config_id"])
        state_set(uid, "await_renewal_receipt", payment_id=payment_id, purchase_id=purchase_id)
        text = (
            "≡ƒÆ│ <b>┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (╪¬┘à╪»█î╪»)</b>\n\n"
            f"┘ä╪╖┘ü╪º┘ï ┘à╪¿┘ä╪║ <b>{fmt_price(price)}</b> ╪¬┘ê┘à╪º┘å ╪▒╪º ╪¿┘ç ┌⌐╪º╪▒╪¬ ╪▓█î╪▒ ┘ê╪º╪▒█î╪▓ ┌⌐┘å█î╪»:\n\n"
            f"≡ƒÅª {esc(bank or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}\n"
            f"≡ƒæñ {esc(owner or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}\n"
            f"≡ƒÆ│ <code>{esc(card)}</code>\n\n"
            "≡ƒô╕ ┘╛╪│ ╪º╪▓ ┘ê╪º╪▒█î╪▓╪î ╪¬╪╡┘ê█î╪▒ ╪▒╪│█î╪» █î╪º ╪┤┘à╪º╪▒┘ç ┘╛█î┌»█î╪▒█î ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("rpay:crypto:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("crypto", price):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪º█î┘å ╪»╪▒┌»╪º┘ç ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
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
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
            return
        authority = payment["receipt_text"]
        success, result = verify_tetrapay_order(authority)
        if success:
            complete_payment(payment_id)
            package_row = get_package(payment["package_id"])
            config_id = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
            send_or_edit(call,
                "Γ£à <b>╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪º╪▒╪│╪º┘ä ╪┤╪»</b>\n\n"
                "≡ƒöä ╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│ ╪┤┘à╪º ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪½╪¿╪¬ ┘ê ╪¿╪▒╪º█î ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪º╪▒╪│╪º┘ä ╪┤╪».\n"
                "ΓÅ│ ┘ä╪╖┘ü╪º┘ï ┌⌐┘à█î ╪╡╪¿╪▒ ┌⌐┘å█î╪»╪î ┘╛╪│ ╪º╪▓ ╪º┘å╪¼╪º┘à ╪¬┘à╪»█î╪» ╪¿┘ç ╪┤┘à╪º ╪º╪╖┘ä╪º╪╣ ╪»╪º╪»┘ç ╪«┘ê╪º┘ç╪» ╪┤╪».\n\n"
                "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ┘ê ╪┤┌⌐█î╪¿╪º█î█î ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à.",
                back_button("main"))
            if item:
                admin_renewal_notify(uid, item, package_row, payment["amount"], "TetraPay")
            state_clear(uid)
        else:
            _st = result.get("status", "") if isinstance(result, dict) else ""
            bot.answer_callback_query(call.id,
                f"Γ¥î ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪¬╪º█î█î╪» ┘å╪┤╪»┘ç.\n┘ê╪╢╪╣█î╪¬ TetraPay: {_st}\n\n┘ä╪╖┘ü╪º┘ï ╪º╪¿╪¬╪»╪º ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪»╪▒ ╪»╪▒┌»╪º┘ç ╪¬╪¬╪▒╪º┘╛█î ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».",
                show_alert=True)
        return

    if data.startswith("rpay:tetrapay:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("tetrapay", price):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç TetraPay ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        hash_id = f"rnw-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"╪¬┘à╪»█î╪» {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"╪¬┘à╪»█î╪» {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tetrapay_order(price, hash_id, order_label)
        if not success:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ╪»╪▒╪«┘ê╪º╪│╪¬ ┘╛╪▒╪»╪º╪«╪¬ ╪ó┘å┘ä╪º█î┘å.", show_alert=True)
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
            "≡ƒÅª <b>┘╛╪▒╪»╪º╪«╪¬ ╪ó┘å┘ä╪º█î┘å (╪¬┘à╪»█î╪»)</b>\n\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(price)}</b> ╪¬┘ê┘à╪º┘å\n\n"
            "┘ä╪╖┘ü╪º┘ï ╪º╪▓ █î┌⌐█î ╪º╪▓ ┘ä█î┘å┌⌐ΓÇî┘ç╪º█î ╪▓█î╪▒ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».\n\n"
            "ΓÅ│ <b>╪¬╪º █î┌⌐ ╪│╪º╪╣╪¬</b> ╪º┌»╪▒ ┘╛╪▒╪»╪º╪«╪¬ΓÇî╪¬┘ê┘å ╪¬╪º█î█î╪» ╪¿╪┤┘ç ╪¿┘ç ╪╡┘ê╪▒╪¬ ╪«┘ê╪»┌⌐╪º╪▒ ╪╣┘à┘ä█î╪º╪¬ ╪º┘å╪¼╪º┘à ┘à█îΓÇî╪┤┘ê╪».\n"
            "╪»╪▒ ╪║█î╪▒ ╪º█î┘å ╪╡┘ê╪▒╪¬ ╪»┌⌐┘à┘ç <b>╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬</b> ╪▒╪º ╪¿╪▓┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("≡ƒÆ│ ┘╛╪▒╪»╪º╪«╪¬ ╪»╪▒ ╪¬┘ä┌»╪▒╪º┘à", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("≡ƒîÉ ┘╛╪▒╪»╪º╪«╪¬ ╪»╪▒ ┘à╪▒┘ê╪▒┌»╪▒", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("≡ƒöì ╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬", callback_data=f"rpay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "renewal", package_id=package_id)
        return

    if data.startswith("rpay:tetrapay:verify:"):
        # NOTE: this block is now unreachable (handled above) ΓÇö kept as safety guard
        bot.answer_callback_query(call.id)
        return

    # ΓöÇΓöÇ TronPays Rial: renewal ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("rpay:tronpays_rial:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        ok, status = check_tronpays_rial_invoice(invoice_id)
        if not ok:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ╪¿╪▒╪▒╪│█î ┘ê╪╢╪╣█î╪¬ ┘ü╪º┌⌐╪¬┘ê╪▒.", show_alert=True)
            return
        if is_tronpays_paid(status):
            complete_payment(payment_id)
            package_row = get_package(payment["package_id"])
            config_id   = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
            send_or_edit(call,
                "Γ£à <b>╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪º╪▒╪│╪º┘ä ╪┤╪»</b>\n\n"
                "≡ƒöä ╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│ ╪┤┘à╪º ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪½╪¿╪¬ ┘ê ╪¿╪▒╪º█î ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪º╪▒╪│╪º┘ä ╪┤╪».\n"
                "ΓÅ│ ┘ä╪╖┘ü╪º┘ï ┌⌐┘à█î ╪╡╪¿╪▒ ┌⌐┘å█î╪»╪î ┘╛╪│ ╪º╪▓ ╪º┘å╪¼╪º┘à ╪¬┘à╪»█î╪» ╪¿┘ç ╪┤┘à╪º ╪º╪╖┘ä╪º╪╣ ╪»╪º╪»┘ç ╪«┘ê╪º┘ç╪» ╪┤╪».\n\n"
                "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ┘ê ╪┤┌⌐█î╪¿╪º█î█î ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à.",
                back_button("main"))
            if item:
                admin_renewal_notify(uid, item, package_row, payment["amount"], "TronPays")
            state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "Γ¥î ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪¬╪ú█î█î╪» ┘å╪┤╪»┘ç. ┘ä╪╖┘ü╪º┘ï ╪º╪¿╪¬╪»╪º ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».", show_alert=True)
        return

    if data.startswith("rpay:tronpays_rial:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("tronpays_rial", price):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç TronsPay ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        hash_id = f"rnw-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"╪¬┘à╪»█î╪» {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"╪¬┘à╪»█î╪» {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tronpays_rial_invoice(price, hash_id, order_label)
        if not success:
            err_msg = result.get("error", "╪«╪╖╪º█î ┘å╪º╪┤┘å╪º╪«╪¬┘ç") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"ΓÜá∩╕Å <b>╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ╪»╪▒┌»╪º┘ç TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "≡ƒÆí ┘à╪╖┘à╪ª┘å ╪┤┘ê█î╪» ┌⌐┘ä█î╪» API ╪╡╪¡█î╪¡ ┘ê╪º╪▒╪» ╪┤╪»┘ç ╪¿╪º╪┤╪».",
                back_button(f"renew:{purchase_id}"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"ΓÜá∩╕Å <b>╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ┘ü╪º┌⌐╪¬┘ê╪▒ TronPays</b>\n\n"
                f"<code>┘╛╪º╪│╪« API: {esc(str(result)[:400])}</code>",
                back_button(f"renew:{purchase_id}"))
            return
        payment_id = create_payment("renewal", uid, package_id, price, "tronpays_rial", status="pending",
                                    config_id=item["config_id"])
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_renewal_tronpays_rial_verify", payment_id=payment_id,
                  invoice_id=invoice_id, purchase_id=purchase_id)
        text = (
            "≡ƒÆ│ <b>┘╛╪▒╪»╪º╪«╪¬ ╪▒█î╪º┘ä█î (TronPays) ΓÇö ╪¬┘à╪»█î╪»</b>\n\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(price)}</b> ╪¬┘ê┘à╪º┘å\n\n"
            "╪º╪▓ ┘ä█î┘å┌⌐ ╪▓█î╪▒ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».\n\n"
            "ΓÅ│ <b>╪¬╪º █î┌⌐ ╪│╪º╪╣╪¬</b> ┘╛╪▒╪»╪º╪«╪¬ ╪¿┘ç ╪╡┘ê╪▒╪¬ ╪«┘ê╪»┌⌐╪º╪▒ ╪¿╪▒╪▒╪│█î ┘à█îΓÇî╪┤┘ê╪».\n"
            "╪»╪▒ ╪║█î╪▒ ╪º█î┘å ╪╡┘ê╪▒╪¬ ╪»┌⌐┘à┘ç ┬½╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬┬╗ ╪▒╪º ╪¿╪▓┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒÆ│ ┘╛╪▒╪»╪º╪«╪¬ ╪º╪▓ ╪»╪▒┌»╪º┘ç TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("≡ƒöì ╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬", callback_data=f"rpay:tronpays_rial:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tronpays_rial_auto_verify(
            payment_id, invoice_id, uid,
            call.message.chat.id, call.message.message_id,
            "renewal", package_id=package_id)
        return

    # ΓöÇΓöÇ Admin: Confirm renewal ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("renew:confirm:"):
        if not admin_has_perm(uid, "approve_renewal"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        parts = data.split(":")
        config_id  = int(parts[2])
        target_uid = int(parts[3])
        # Un-expire config if it was expired
        with get_conn() as conn:
            conn.execute("UPDATE configs SET is_expired=0 WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "Γ£à ╪¬┘à╪»█î╪» ╪¬╪ú█î█î╪» ╪┤╪».")
        # Update admin's message
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        try:
            bot.send_message(call.message.chat.id, "Γ£à ╪¬┘à╪»█î╪» ╪¬╪ú█î█î╪» ┘ê ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒ ╪º╪╖┘ä╪º╪╣ ╪»╪º╪»┘ç ╪┤╪».")
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
                f"≡ƒÄë <b>╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│ ╪º┘å╪¼╪º┘à ╪┤╪»!</b>\n\n"
                f"Γ£à ╪│╪▒┘ê█î╪│ <b>{esc(svc_name)}</b> ╪┤┘à╪º ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪¬┘à╪»█î╪» ╪┤╪».\n"
                "╪º╪▓ ╪º╪╣╪¬┘à╪º╪» ╪┤┘à╪º ╪│┘╛╪º╪│┌»╪▓╪º╪▒█î┘à. ≡ƒÖÅ")
        except Exception:
            pass
        # Renewal log ΓÇö find the payment method from the original admin message
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
                f"≡ƒöä | <b>╪¬┘à╪»█î╪» ╪¬╪ú█î█î╪» ╪┤╪»</b>"
                f"{(' (' + esc(renewal_method) + ')') if renewal_method else ''}\n\n"
                f"Γû½∩╕Å ╪ó█î╪»█î ┌⌐╪º╪▒╪¿╪▒: <code>{target_uid}</code>\n"
                f"≡ƒæ¿ΓÇì≡ƒÆ╝ ┘å╪º┘à: {esc(user_row['full_name'] if user_row else '')}\n"
                f"ΓÜí∩╕Å ┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î: {esc((user_row['username'] or '┘å╪»╪º╪▒╪»') if user_row else '┘å╪»╪º╪▒╪»')}\n"
                f"≡ƒö« ┘å╪º┘à ╪│╪▒┘ê█î╪│: {esc(svc_name or str(config_id))}\n"
            )
            if cfg_row:
                log_text += (
                    f"≡ƒÜª ╪│╪▒┘ê╪▒: {esc(cfg_row['type_name'])}\n"
                    f"Γ£Å∩╕Å ┘╛┌⌐█î╪¼: {esc(cfg_row['package_name'])}\n"
                    f"≡ƒöï ╪¡╪¼┘à: {cfg_row['volume_gb']} ┌»█î┌»\n"
                    f"ΓÅ░ ┘à╪»╪¬: {cfg_row['duration_days']} ╪▒┘ê╪▓\n"
                    f"≡ƒÆ░ ┘é█î┘à╪¬: {fmt_price(cfg_row['price'])} ╪¬┘ê┘à╪º┘å"
                )
            send_to_topic("renewal_log", log_text)
        except Exception:
            pass
        return

    # ΓöÇΓöÇ Buy flow ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "buy:start":
        # Check purchase rules
        if setting_get("purchase_rules_enabled", "0") == "1":
            accepted = setting_get(f"rules_accepted_{uid}", "0")
            if accepted != "1":
                rules_text = setting_get("purchase_rules_text", "")
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("Γ£à ┘à┘å ┘é┘ê╪º┘å█î┘å ╪▒╪º ╪«┘ê╪º┘å╪»┘à ┘ê ┘╛╪░█î╪▒┘ü╪¬┘à", callback_data="buy:accept_rules"))
                kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
                bot.answer_callback_query(call.id)
                send_or_edit(call, f"≡ƒô£ <b>┘é┘ê╪º┘å█î┘å ╪«╪▒█î╪»</b>\n\n{esc(rules_text)}", kb)
                return
        # Fall through to actual buy
        data = "buy:start_real"

    if data == "buy:start_real":
        # Check if shop is open
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "≡ƒö┤ <b>┘ü╪▒┘ê╪┤┌»╪º┘ç ┘à┘ê┘é╪¬╪º┘ï ╪¬╪╣╪╖█î┘ä ╪º╪│╪¬.</b>\n\n┘ä╪╖┘ü╪º┘ï ╪¿╪╣╪»╪º┘ï ┘à╪▒╪º╪¼╪╣┘ç ┌⌐┘å█î╪».", kb)
            return
        stock_only = setting_get("preorder_mode", "0") == "1"
        items = get_active_types()
        kb = types.InlineKeyboardMarkup()
        has_any = False
        for item in items:
            if stock_only:
                packs = [p for p in get_packages(type_id=item['id']) if p['price'] > 0 and p['stock'] > 0]
            else:
                packs = [p for p in get_packages(type_id=item['id']) if p['price'] > 0]
            if packs:
                kb.add(types.InlineKeyboardButton(f"≡ƒº⌐ {item['name']}", callback_data=f"buy:t:{item['id']}"))
                has_any = True
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        bot.answer_callback_query(call.id)
        if not has_any:
            send_or_edit(call, "≡ƒô¡ ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ╪¿╪│╪¬┘çΓÇî╪º█î ╪¿╪▒╪º█î ┘ü╪▒┘ê╪┤ ┘à┘ê╪¼┘ê╪» ┘å█î╪│╪¬.", kb)
        else:
            send_or_edit(call, "≡ƒ¢Æ <b>╪«╪▒█î╪» ┌⌐╪º┘å┘ü█î┌» ╪¼╪»█î╪»</b>\n\n┘å┘ê╪╣ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("buy:t:"):
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "≡ƒö┤ <b>┘ü╪▒┘ê╪┤┌»╪º┘ç ┘à┘ê┘é╪¬╪º┘ï ╪¬╪╣╪╖█î┘ä ╪º╪│╪¬.</b>

┘ä╪╖┘ü╪º┘ï ╪¿╪╣╪»╪º┘ï ┘à╪▒╪º╪¼╪╣┘ç ┌⌐┘å█î╪».", kb)
            return
        type_id   = int(data.split(":")[2])
        stock_only = setting_get("preorder_mode", "0") == "1"
        if stock_only:
            packages = [p for p in get_packages(type_id=type_id) if p["price"] > 0 and p["stock"] > 0]
        else:
            packages = [p for p in get_packages(type_id=type_id) if p["price"] > 0]
        kb   = types.InlineKeyboardMarkup()
        user = get_user(uid)
        for p in packages:
            price = get_effective_price(uid, p)
            stock_tag = "" if p["stock"] > 0 else " ΓÅ│"
            _sn = p['show_name'] if 'show_name' in p.keys() else 1
            _name_part = f"{p['name']}{stock_tag} | " if _sn else (f"{stock_tag} | " if stock_tag else "")
            title = f"{_name_part}{fmt_vol(p['volume_gb'])} | {fmt_dur(p['duration_days'])} | {fmt_price(price)} ╪¬"
            kb.add(types.InlineKeyboardButton(title, callback_data=f"buy:p:{p['id']}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="buy:start"))
        bot.answer_callback_query(call.id)
        agent_note = "\n\n≡ƒñ¥ <i>╪º█î┘å ┘é█î┘à╪¬ΓÇî┘ç╪º ┘à╪«╪╡┘ê╪╡ ┘ç┘à┌⌐╪º╪▒█î ╪┤┘à╪º╪│╪¬</i>" if user and user["is_agent"] else ""
        if not packages:
            send_or_edit(call, "≡ƒô¡ ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ╪¿╪│╪¬┘çΓÇî╪º█î ╪¿╪▒╪º█î ┘ü╪▒┘ê╪┤ ╪»╪▒ ╪º█î┘å ┘å┘ê╪╣ ┘à┘ê╪¼┘ê╪» ┘å█î╪│╪¬.", kb)
        else:
            send_or_edit(call, f"≡ƒôª █î┌⌐█î ╪º╪▓ ┘╛┌⌐█î╪¼ΓÇî┘ç╪º ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:{agent_note}", kb)
        return

    if data.startswith("buy:p:"):
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "≡ƒö┤ <b>┘ü╪▒┘ê╪┤┌»╪º┘ç ┘à┘ê┘é╪¬╪º┘ï ╪¬╪╣╪╖█î┘ä ╪º╪│╪¬.</b>

┘ä╪╖┘ü╪º┘ï ╪¿╪╣╪»╪º┘ï ┘à╪▒╪º╪¼╪╣┘ç ┌⌐┘å█î╪».", kb)
            return
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        price = get_effective_price(uid, package_row)
        state_set(uid, "buy_select_method",
                  package_id=package_id, amount=price, original_amount=price,
                  kind="config_purchase")
        bot.answer_callback_query(call.id)
        if setting_get("discount_codes_enabled", "0") == "1":
            _show_discount_prompt(call, price)
            return
        _show_purchase_gateways(call, uid, package_id, price, package_row)
        return

    if data.startswith("pay:wallet:"):
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        user        = get_user(uid)
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        preorder_on = setting_get("preorder_mode", "0") == "1"
        if preorder_on and package_row["stock"] <= 0:
            bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ╪º█î┘å ┘╛┌⌐█î╪¼ ╪¬┘à╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "buy_select_method")
        if user["balance"] < price:
            bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ┌⌐█î┘ü ┘╛┘ê┘ä ┌⌐╪º┘ü█î ┘å█î╪│╪¬.", show_alert=True)
            return
        config_id = reserve_first_config(package_id)
        if not config_id:
            if preorder_on:
                bot.answer_callback_query(call.id, "┘ü╪╣┘ä╪º┘ï ┌⌐╪º┘å┘ü█î┌»█î ┘à┘ê╪¼┘ê╪» ┘å█î╪│╪¬.", show_alert=True)
                return
            # preorder_mode OFF ΓÇö deduct balance, create pending order, notify admin
            update_balance(uid, -price)
            payment_id = create_payment("config_purchase", uid, package_id, price, "wallet", status="completed")
            complete_payment(payment_id)
            pending_id = create_pending_order(uid, package_id, payment_id, price, "wallet")
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪º╪▓ ┌⌐█î┘ü ┘╛┘ê┘ä ╪º┘å╪¼╪º┘à ╪┤╪».\n\n"
                "ΓÜá∩╕Å <b>┘à┘ê╪¼┘ê╪»█î ╪¬╪¡┘ê█î┘ä ┘ü┘ê╪▒█î ╪▒╪¿╪º╪¬ ╪¿┘ç ╪º╪¬┘à╪º┘à ╪▒╪│█î╪».</b>\n"
                "╪»╪▒╪«┘ê╪º╪│╪¬ ╪┤┘à╪º ╪¿╪▒╪º█î ╪º╪»┘à█î┘å ╪º╪▒╪│╪º┘ä ╪┤╪». ╪»╪▒ ┌⌐┘à╪¬╪▒█î┘å ┘ü╪▒╪╡╪¬ ┌⌐╪º┘å┘ü█î┌» ╪┤┘à╪º ╪¬╪¡┘ê█î┘ä ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à.", back_button("main"))
            notify_pending_order_to_admins(pending_id, uid, package_row, price, "wallet")
            state_clear(uid)
            return
        update_balance(uid, -price)
        try:
            purchase_id = assign_config_to_user(config_id, uid, package_id, price, "wallet", is_test=0)
        except Exception:
            update_balance(uid, price)
            release_reserved_config(config_id)
            bot.answer_callback_query(call.id, "ΓÜá∩╕Å ╪«╪╖╪º█î█î ╪▒╪« ╪»╪º╪»╪î ┘à╪¿┘ä╪║ ╪¿┘ç ┌⌐█î┘ü ┘╛┘ê┘ä ╪¿╪º╪▓┌»╪▒╪»╪º┘å╪»┘ç ╪┤╪».", show_alert=True)
            return
        payment_id  = create_payment("config_purchase", uid, package_id, price, "wallet",
                                     status="completed", config_id=config_id)
        complete_payment(payment_id)
        bot.answer_callback_query(call.id, "╪«╪▒█î╪» ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪º┘å╪¼╪º┘à ╪┤╪».")
        send_or_edit(call, "Γ£à ╪«╪▒█î╪» ╪┤┘à╪º ╪º┘å╪¼╪º┘à ╪┤╪» ┘ê ╪│╪▒┘ê█î╪│ ╪»╪▒ ┘╛█î╪º┘à ╪¿╪╣╪»█î ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘ê╪».", back_button("main"))
        deliver_purchase_message(call.message.chat.id, purchase_id)
        admin_purchase_notify("┌⌐█î┘ü ┘╛┘ê┘ä", get_user(uid), package_row, purchase_id=purchase_id)
        state_clear(uid)
        return

    if data.startswith("pay:card:"):
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or (setting_get("preorder_mode", "0") == "1" and package_row["stock"] <= 0):
            bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ╪º█î┘å ┘╛┌⌐█î╪¼ ╪¬┘à╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        card  = setting_get("payment_card", "")
        bank  = setting_get("payment_bank", "")
        owner = setting_get("payment_owner", "")
        if not card:
            bot.answer_callback_query(call.id, "╪º╪╖┘ä╪º╪╣╪º╪¬ ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪½╪¿╪¬ ┘å╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        price      = _get_state_price(uid, package_row, "buy_select_method")
        if not is_gateway_in_range("card", price):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪º█î┘å ╪»╪▒┌»╪º┘ç ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        payment_id = create_payment("config_purchase", uid, package_id, price, "card", status="pending")
        state_set(uid, "await_purchase_receipt", payment_id=payment_id)
        text = (
            "≡ƒÆ│ <b>┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬</b>\n\n"
            f"┘ä╪╖┘ü╪º┘ï ┘à╪¿┘ä╪║ <b>{fmt_price(price)}</b> ╪¬┘ê┘à╪º┘å ╪▒╪º ╪¿┘ç ┌⌐╪º╪▒╪¬ ╪▓█î╪▒ ┘ê╪º╪▒█î╪▓ ┌⌐┘å█î╪»:\n\n"
            f"≡ƒÅª {esc(bank or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}\n"
            f"≡ƒæñ {esc(owner or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}\n"
            f"≡ƒÆ│ <code>{esc(card)}</code>\n\n"
            "≡ƒô╕ ┘╛╪│ ╪º╪▓ ┘ê╪º╪▒█î╪▓╪î ╪¬╪╡┘ê█î╪▒ ╪▒╪│█î╪» █î╪º ╪┤┘à╪º╪▒┘ç ┘╛█î┌»█î╪▒█î ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("pay:crypto:"):
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or (setting_get("preorder_mode", "0") == "1" and package_row["stock"] <= 0):
            bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ╪º█î┘å ┘╛┌⌐█î╪¼ ╪¬┘à╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "buy_select_method")
        if not is_gateway_in_range("crypto", price):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪º█î┘å ╪»╪▒┌»╪º┘ç ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        state_set(uid, "buy_crypto_select_coin", package_id=package_id, amount=price)
        bot.answer_callback_query(call.id)
        show_crypto_selection(call, amount=price)
        return

    # Crypto coin selection (after buy)
    if data.startswith("pm:crypto:"):
        coin_key = data.split(":")[2]
        sd       = state_data(uid)
        sn       = state_name(uid)
        if sn == "buy_crypto_select_coin":
            package_id  = sd.get("package_id")
            amount      = sd.get("amount")
            package_row = get_package(package_id)
            if not package_row or (setting_get("preorder_mode", "0") == "1" and package_row["stock"] <= 0):
                bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ╪¬┘à╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
                return
            payment_id = create_payment("config_purchase", uid, package_id, amount, "crypto",
                                        status="pending", crypto_coin=coin_key)
            state_set(uid, "await_purchase_receipt", payment_id=payment_id)
            bot.answer_callback_query(call.id)
            show_crypto_payment_info(call, uid, coin_key, amount)
        elif sn == "wallet_crypto_select_coin":
            amount     = sd.get("amount")
            payment_id = sd.get("payment_id") or create_payment("wallet_charge", uid, None, amount, "crypto",
                                                                  status="pending", crypto_coin=coin_key)
            state_set(uid, "await_wallet_receipt", payment_id=payment_id, amount=amount)
            bot.answer_callback_query(call.id)
            show_crypto_payment_info(call, uid, coin_key, amount)
        elif sn == "renew_crypto_select_coin":
            package_id  = sd.get("package_id")
            amount      = sd.get("amount")
            config_id_r = sd.get("config_id")
            purchase_id = sd.get("purchase_id")
            payment_id = create_payment("renewal", uid, package_id, amount, "crypto",
                                        status="pending", crypto_coin=coin_key, config_id=config_id_r)
            state_set(uid, "await_renewal_receipt", payment_id=payment_id, purchase_id=purchase_id)
            bot.answer_callback_query(call.id)
            show_crypto_payment_info(call, uid, coin_key, amount)
        else:
            bot.answer_callback_query(call.id)
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
        show_main_menu(call)
        return

    # ΓöÇΓöÇ TetraPay ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("pay:tetrapay:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
            return
        authority = payment["receipt_text"]
        success, result = verify_tetrapay_order(authority)
        if success:
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                send_or_edit(call, f"Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ┘ê ┌⌐█î┘ü ┘╛┘ê┘ä ╪┤╪º╪▒┌ÿ ╪┤╪».\n\n≡ƒÆ░ ┘à╪¿┘ä╪║: {fmt_price(payment['amount'])} ╪¬┘ê┘à╪º┘å", back_button("main"))
                state_clear(uid)
            else:
                config_id = payment["config_id"]
                package_id = payment["package_id"]
                package_row = get_package(package_id)
                if not config_id:
                    config_id = reserve_first_config(package_id, payment_id)
                if not config_id:
                    pending_id = create_pending_order(uid, package_id, payment_id, payment["amount"], "tetrapay")
                    complete_payment(payment_id)
                    bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                    send_or_edit(call,
                        "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪».\n\n"
                        "ΓÜá∩╕Å <b>┘à┘ê╪¼┘ê╪»█î ╪¬╪¡┘ê█î┘ä ┘ü┘ê╪▒█î ╪▒╪¿╪º╪¬ ╪¿┘ç ╪º╪¬┘à╪º┘à ╪▒╪│█î╪».</b>\n"
                        "╪»╪▒╪«┘ê╪º╪│╪¬ ╪┤┘à╪º ╪¿╪▒╪º█î ╪º╪»┘à█î┘å ╪º╪▒╪│╪º┘ä ╪┤╪». ╪»╪▒ ┌⌐┘à╪¬╪▒█î┘å ┘ü╪▒╪╡╪¬ ┌⌐╪º┘å┘ü█î┌» ╪┤┘à╪º ╪¬╪¡┘ê█î┘ä ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                        "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à.", back_button("main"))
                    notify_pending_order_to_admins(pending_id, uid, package_row, payment["amount"], "tetrapay")
                    state_clear(uid)
                    return
                purchase_id = assign_config_to_user(config_id, uid, package_id, payment["amount"], "tetrapay", is_test=0)
                complete_payment(payment_id)
                bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                send_or_edit(call, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ╪│╪▒┘ê█î╪│ ╪ó┘à╪º╪»┘ç ╪º╪│╪¬.", back_button("main"))
                deliver_purchase_message(call.message.chat.id, purchase_id)
                admin_purchase_notify("TetraPay", get_user(uid), package_row, purchase_id=purchase_id)
                state_clear(uid)
        else:
            _st = result.get("status", "") if isinstance(result, dict) else ""
            bot.answer_callback_query(call.id,
                f"Γ¥î ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪¬╪º█î█î╪» ┘å╪┤╪»┘ç.\n┘ê╪╢╪╣█î╪¬ TetraPay: {_st}\n\n┘ä╪╖┘ü╪º┘ï ╪º╪¿╪¬╪»╪º ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪»╪▒ ╪»╪▒┌»╪º┘ç ╪¬╪¬╪▒╪º┘╛█î ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».",
                show_alert=True)
        return

    if data.startswith("pay:tetrapay:"):
        package_id = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or (setting_get("preorder_mode", "0") == "1" and package_row["stock"] <= 0):
            bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ╪º█î┘å ┘╛┌⌐█î╪¼ ╪¬┘à╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "buy_select_method")
        if not is_gateway_in_range("tetrapay", price):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç TetraPay ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        hash_id = f"cfg-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"╪«╪▒█î╪» {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"╪«╪▒█î╪» {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tetrapay_order(price, hash_id, order_label)
        if not success:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ╪»╪▒╪«┘ê╪º╪│╪¬ ┘╛╪▒╪»╪º╪«╪¬ ╪ó┘å┘ä╪º█î┘å.", show_alert=True)
            return
        authority = result.get("Authority", "")
        pay_url_bot = result.get("payment_url_bot", "")
        pay_url_web = result.get("payment_url_web", "")
        payment_id = create_payment("config_purchase", uid, package_id, price, "tetrapay", status="pending")
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (authority, payment_id))
        state_set(uid, "await_tetrapay_verify", payment_id=payment_id, authority=authority)
        text = (
            "≡ƒÅª <b>┘╛╪▒╪»╪º╪«╪¬ ╪ó┘å┘ä╪º█î┘å (TetraPay)</b>\n\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(price)}</b> ╪¬┘ê┘à╪º┘å\n\n"
            "┘ä╪╖┘ü╪º┘ï ╪º╪▓ █î┌⌐█î ╪º╪▓ ┘ä█î┘å┌⌐ΓÇî┘ç╪º█î ╪▓█î╪▒ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».\n\n"
            "ΓÅ│ <b>╪¬╪º █î┌⌐ ╪│╪º╪╣╪¬</b> ╪º┌»╪▒ ┘╛╪▒╪»╪º╪«╪¬ΓÇî╪¬┘ê┘å ╪¬╪º█î█î╪» ╪¿╪┤┘ç ╪¿┘ç ╪╡┘ê╪▒╪¬ ╪«┘ê╪»┌⌐╪º╪▒ ╪╣┘à┘ä█î╪º╪¬ ╪º┘å╪¼╪º┘à ┘à█îΓÇî╪┤┘ê╪».\n"
            "╪»╪▒ ╪║█î╪▒ ╪º█î┘å ╪╡┘ê╪▒╪¬ ╪»┌⌐┘à┘ç <b>╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬</b> ╪▒╪º ╪¿╪▓┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("≡ƒÆ│ ┘╛╪▒╪»╪º╪«╪¬ ╪»╪▒ ╪¬┘ä┌»╪▒╪º┘à", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("≡ƒîÉ ┘╛╪▒╪»╪º╪«╪¬ ╪»╪▒ ┘à╪▒┘ê╪▒┌»╪▒", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("≡ƒöì ╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬", callback_data=f"pay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "config_purchase", package_id=package_id)
        return

    # ΓöÇΓöÇ TronPays Rial: purchase ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("pay:tronpays_rial:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        ok, status = check_tronpays_rial_invoice(invoice_id)
        if not ok:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ╪¿╪▒╪▒╪│█î ┘ê╪╢╪╣█î╪¬ ┘ü╪º┌⌐╪¬┘ê╪▒.", show_alert=True)
            return
        if is_tronpays_paid(status):
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                send_or_edit(call, f"Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ┘ê ┌⌐█î┘ü ┘╛┘ê┘ä ╪┤╪º╪▒┌ÿ ╪┤╪».\n\n≡ƒÆ░ ┘à╪¿┘ä╪║: {fmt_price(payment['amount'])} ╪¬┘ê┘à╪º┘å",
                             back_button("main"))
                state_clear(uid)
            else:
                config_id  = payment["config_id"]
                package_id = payment["package_id"]
                package_row = get_package(package_id)
                if not config_id:
                    config_id = reserve_first_config(package_id, payment_id)
                if not config_id:
                    pending_id = create_pending_order(uid, package_id, payment_id, payment["amount"], "tronpays_rial")
                    complete_payment(payment_id)
                    bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                    send_or_edit(call,
                        "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪».\n\n"
                        "ΓÜá∩╕Å <b>┘à┘ê╪¼┘ê╪»█î ╪¬╪¡┘ê█î┘ä ┘ü┘ê╪▒█î ╪▒╪¿╪º╪¬ ╪¿┘ç ╪º╪¬┘à╪º┘à ╪▒╪│█î╪».</b>\n"
                        "╪»╪▒╪«┘ê╪º╪│╪¬ ╪┤┘à╪º ╪¿╪▒╪º█î ╪º╪»┘à█î┘å ╪º╪▒╪│╪º┘ä ╪┤╪». ╪»╪▒ ┌⌐┘à╪¬╪▒█î┘å ┘ü╪▒╪╡╪¬ ┌⌐╪º┘å┘ü█î┌» ╪┤┘à╪º ╪¬╪¡┘ê█î┘ä ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                        "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à.", back_button("main"))
                    notify_pending_order_to_admins(pending_id, uid, package_row, payment["amount"], "tronpays_rial")
                    state_clear(uid)
                    return
                purchase_id = assign_config_to_user(config_id, uid, package_id, payment["amount"], "tronpays_rial", is_test=0)
                complete_payment(payment_id)
                bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                send_or_edit(call, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ╪│╪▒┘ê█î╪│ ╪ó┘à╪º╪»┘ç ╪º╪│╪¬.", back_button("main"))
                deliver_purchase_message(call.message.chat.id, purchase_id)
                admin_purchase_notify("TronPays", get_user(uid), package_row, purchase_id=purchase_id)
                state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "Γ¥î ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪¬╪ú█î█î╪» ┘å╪┤╪»┘ç. ┘ä╪╖┘ü╪º┘ï ╪º╪¿╪¬╪»╪º ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».", show_alert=True)
        return

    if data.startswith("pay:tronpays_rial:"):
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or (setting_get("preorder_mode", "0") == "1" and package_row["stock"] <= 0):
            bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ╪º█î┘å ┘╛┌⌐█î╪¼ ╪¬┘à╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        price   = _get_state_price(uid, package_row, "buy_select_method")
        if not is_gateway_in_range("tronpays_rial", price):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç TronsPay ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        hash_id = f"cfg-{uid}-{package_id}-{int(datetime.now().timestamp())}"
        order_label = (
            f"╪«╪▒█î╪» {package_row['name']}"
            if ('show_name' not in package_row.keys() or package_row['show_name'])
            else f"╪«╪▒█î╪» {fmt_vol(package_row['volume_gb'])} | {fmt_dur(package_row['duration_days'])}"
        )
        success, result = create_tronpays_rial_invoice(price, hash_id, order_label)
        if not success:
            err_msg = result.get("error", "╪«╪╖╪º█î ┘å╪º╪┤┘å╪º╪«╪¬┘ç") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"ΓÜá∩╕Å <b>╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ╪»╪▒┌»╪º┘ç TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "≡ƒÆí ┘à╪╖┘à╪ª┘å ╪┤┘ê█î╪» ┌⌐┘ä█î╪» API ╪╡╪¡█î╪¡ ┘ê╪º╪▒╪» ╪┤╪»┘ç ╪¿╪º╪┤╪».",
                back_button(f"buy:p:{package_id}"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"ΓÜá∩╕Å <b>╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ┘ü╪º┌⌐╪¬┘ê╪▒ TronPays</b>\n\n"
                f"<code>┘╛╪º╪│╪« API: {esc(str(result)[:400])}</code>",
                back_button(f"buy:p:{package_id}"))
            return
        payment_id = create_payment("config_purchase", uid, package_id, price, "tronpays_rial", status="pending")
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_tronpays_rial_verify", payment_id=payment_id, invoice_id=invoice_id)
        text = (
            "≡ƒÆ│ <b>┘╛╪▒╪»╪º╪«╪¬ ╪▒█î╪º┘ä█î (TronPays)</b>\n\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(price)}</b> ╪¬┘ê┘à╪º┘å\n\n"
            "╪º╪▓ ┘ä█î┘å┌⌐ ╪▓█î╪▒ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».\n\n"
            "ΓÅ│ <b>╪¬╪º █î┌⌐ ╪│╪º╪╣╪¬</b> ┘╛╪▒╪»╪º╪«╪¬ ╪¿┘ç ╪╡┘ê╪▒╪¬ ╪«┘ê╪»┌⌐╪º╪▒ ╪¿╪▒╪▒╪│█î ┘à█îΓÇî╪┤┘ê╪».\n"
            "╪»╪▒ ╪║█î╪▒ ╪º█î┘å ╪╡┘ê╪▒╪¬ ╪»┌⌐┘à┘ç ┬½╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬┬╗ ╪▒╪º ╪¿╪▓┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒÆ│ ┘╛╪▒╪»╪º╪«╪¬ ╪º╪▓ ╪»╪▒┌»╪º┘ç TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("≡ƒöì ╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬", callback_data=f"pay:tronpays_rial:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tronpays_rial_auto_verify(
            payment_id, invoice_id, uid,
            call.message.chat.id, call.message.message_id,
            "config_purchase", package_id=package_id)
        return

    # ΓöÇΓöÇ Free test ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "test:start":
        if setting_get("free_test_enabled", "1") != "1":
            bot.answer_callback_query(call.id, "╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ╪║█î╪▒┘ü╪╣╪º┘ä ╪º╪│╪¬.", show_alert=True)
            return
        user = get_user(uid)
        is_agent_user = user and user["is_agent"]
        if is_agent_user:
            agent_limit = int(setting_get("agent_test_limit", "0") or "0")
            agent_period = setting_get("agent_test_period", "day")
            if agent_limit > 0:
                used = agent_test_count_in_period(uid, agent_period)
                if used >= agent_limit:
                    period_labels = {"day": "╪▒┘ê╪▓", "week": "┘ç┘ü╪¬┘ç", "month": "┘à╪º┘ç"}
                    bot.answer_callback_query(call.id,
                        f"╪┤┘à╪º ╪│┘é┘ü ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ({agent_limit} ╪╣╪»╪» ╪»╪▒ {period_labels.get(agent_period, agent_period)}) ╪▒╪º ╪º╪│╪¬┘ü╪º╪»┘ç ┌⌐╪▒╪»┘çΓÇî╪º█î╪».",
                        show_alert=True)
                    return
        else:
            if user_has_any_test(uid):
                bot.answer_callback_query(call.id, "╪┤┘à╪º ┘é╪¿┘ä╪º┘ï ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ╪«┘ê╪» ╪▒╪º ╪»╪▒█î╪º┘ü╪¬ ┌⌐╪▒╪»┘çΓÇî╪º█î╪».", show_alert=True)
                return
        items = get_active_types()
        kb    = types.InlineKeyboardMarkup()
        has_any = False
        for item in items:
            packs = [p for p in get_packages(type_id=item['id'], price_only=0) if p['stock'] > 0]
            if packs:
                kb.add(types.InlineKeyboardButton(f"≡ƒÄü {item['name']}", callback_data=f"test:t:{item['id']}"))
                has_any = True
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        bot.answer_callback_query(call.id)
        if not has_any:
            send_or_edit(call, "≡ƒô¡ ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å█î ┘à┘ê╪¼┘ê╪» ┘å█î╪│╪¬.", kb)
        else:
            send_or_edit(call, "≡ƒÄü <b>╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å</b>\n\n┘å┘ê╪╣ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("test:t:"):
        if setting_get("free_test_enabled", "1") != "1":
            bot.answer_callback_query(call.id, "╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ╪║█î╪▒┘ü╪╣╪º┘ä ╪º╪│╪¬.", show_alert=True)
            return
        user = get_user(uid)
        is_agent_user = user and user["is_agent"]
        if is_agent_user:
            agent_limit = int(setting_get("agent_test_limit", "0") or "0")
            agent_period = setting_get("agent_test_period", "day")
            if agent_limit > 0:
                used = agent_test_count_in_period(uid, agent_period)
                if used >= agent_limit:
                    period_labels = {"day": "╪▒┘ê╪▓", "week": "┘ç┘ü╪¬┘ç", "month": "┘à╪º┘ç"}
                    bot.answer_callback_query(call.id,
                        f"╪┤┘à╪º ╪│┘é┘ü ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ({agent_limit} ╪╣╪»╪» ╪»╪▒ {period_labels.get(agent_period, agent_period)}) ╪▒╪º ╪º╪│╪¬┘ü╪º╪»┘ç ┌⌐╪▒╪»┘çΓÇî╪º█î╪».",
                        show_alert=True)
                    return
        else:
            if user_has_any_test(uid):
                bot.answer_callback_query(call.id, "╪┤┘à╪º ┘é╪¿┘ä╪º┘ï ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ╪«┘ê╪» ╪▒╪º ╪»╪▒█î╪º┘ü╪¬ ┌⌐╪▒╪»┘çΓÇî╪º█î╪».", show_alert=True)
                return
        type_id     = int(data.split(":")[2])
        type_row    = get_type(type_id)
        package_row = None
        for item in get_packages(type_id=type_id, price_only=0):
            if item["stock"] > 0:
                package_row = item
                break
        if not package_row:
            bot.answer_callback_query(call.id, "╪¿╪▒╪º█î ╪º█î┘å ┘å┘ê╪╣ ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ┘à┘ê╪¼┘ê╪» ┘å█î╪│╪¬.", show_alert=True)
            return
        config_id = reserve_first_config(package_row["id"])
        if not config_id:
            bot.answer_callback_query(call.id, "╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ╪º█î┘å ┘å┘ê╪╣ ╪¬┘à╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        try:
            purchase_id = assign_config_to_user(config_id, uid, package_row["id"], 0, "free_test", is_test=1)
        except Exception:
            release_reserved_config(config_id)
            bot.answer_callback_query(call.id, "ΓÜá∩╕Å ╪«╪╖╪º█î█î ╪▒╪« ╪»╪º╪»╪î ┘ä╪╖┘ü╪º┘ï ╪»┘ê╪¿╪º╪▒┘ç ╪¬┘ä╪º╪┤ ┌⌐┘å█î╪».", show_alert=True)
            return
        bot.answer_callback_query(call.id, "╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ╪º╪▒╪│╪º┘ä ╪┤╪».")
        send_or_edit(call, f"Γ£à ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ┘å┘ê╪╣ <b>{esc(type_row['name'])}</b> ╪ó┘à╪º╪»┘ç ╪┤╪».", back_button("main"))
        deliver_purchase_message(call.message.chat.id, purchase_id)
        return

    # ΓöÇΓöÇ Wallet charge ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "wallet:charge":
        if setting_get("shop_open", "1") != "1":
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "≡ƒö┤ <b>┘ü╪▒┘ê╪┤┌»╪º┘ç ┘à┘ê┘é╪¬╪º┘ï ╪¬╪╣╪╖█î┘ä ╪º╪│╪¬.</b>

╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ╪º┘à┌⌐╪º┘åΓÇî┘╛╪░█î╪▒ ┘å█î╪│╪¬.", kb)
            return
        state_set(uid, "await_wallet_amount")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÆ│ <b>╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä</b>\n\n┘à╪¿┘ä╪║ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪¿┘ç ╪¬┘ê┘à╪º┘å ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:", kb)
        return

    if data == "wallet:charge:card":
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "╪º╪¿╪¬╪»╪º ┘à╪¿┘ä╪║ ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».", show_alert=True)
            return
        if not is_gateway_in_range("card", amount):
            _rng = get_gateway_range_text("card")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(amount)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪º█î┘å ╪»╪▒┌»╪º┘ç ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        card  = setting_get("payment_card", "")
        bank  = setting_get("payment_bank", "")
        owner = setting_get("payment_owner", "")
        if not card:
            bot.answer_callback_query(call.id, "╪º╪╖┘ä╪º╪╣╪º╪¬ ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪½╪¿╪¬ ┘å╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        payment_id = create_payment("wallet_charge", uid, None, amount, "card", status="pending")
        state_set(uid, "await_wallet_receipt", payment_id=payment_id, amount=amount)
        text = (
            "≡ƒÆ│ <b>┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬</b>\n\n"
            f"┘ä╪╖┘ü╪º┘ï ┘à╪¿┘ä╪║ <b>{fmt_price(amount)}</b> ╪¬┘ê┘à╪º┘å ╪▒╪º ╪¿┘ç ┌⌐╪º╪▒╪¬ ╪▓█î╪▒ ┘ê╪º╪▒█î╪▓ ┌⌐┘å█î╪»:\n\n"
            f"≡ƒÅª {esc(bank or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}\n"
            f"≡ƒæñ {esc(owner or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}\n"
            f"≡ƒÆ│ <code>{esc(card)}</code>\n\n"
            "≡ƒô╕ ┘╛╪│ ╪º╪▓ ┘ê╪º╪▒█î╪▓╪î ╪¬╪╡┘ê█î╪▒ ╪▒╪│█î╪» █î╪º ╪┤┘à╪º╪▒┘ç ┘╛█î┌»█î╪▒█î ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "wallet:charge:crypto":
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "╪º╪¿╪¬╪»╪º ┘à╪¿┘ä╪║ ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».", show_alert=True)
            return
        if not is_gateway_in_range("crypto", amount):
            _rng = get_gateway_range_text("crypto")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(amount)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪º█î┘å ╪»╪▒┌»╪º┘ç ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        state_set(uid, "wallet_crypto_select_coin", amount=amount)
        bot.answer_callback_query(call.id)
        show_crypto_selection(call, amount=amount)
        return

    if data == "wallet:charge:tetrapay":
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "╪º╪¿╪¬╪»╪º ┘à╪¿┘ä╪║ ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».", show_alert=True)
            return
        if not is_gateway_in_range("tetrapay", amount):
            _rng = get_gateway_range_text("tetrapay")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(amount)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç TetraPay ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        hash_id = f"wallet-{uid}-{int(datetime.now().timestamp())}"
        success, result = create_tetrapay_order(amount, hash_id, "╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä")
        if not success:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ╪»╪▒╪«┘ê╪º╪│╪¬ ┘╛╪▒╪»╪º╪«╪¬ ╪ó┘å┘ä╪º█î┘å.", show_alert=True)
            return
        authority = result.get("Authority", "")
        pay_url_bot = result.get("payment_url_bot", "")
        pay_url_web = result.get("payment_url_web", "")
        payment_id = create_payment("wallet_charge", uid, None, amount, "tetrapay", status="pending")
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (authority, payment_id))
        state_set(uid, "await_tetrapay_verify", payment_id=payment_id, authority=authority)
        text = (
            "≡ƒÅª <b>╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä - ┘╛╪▒╪»╪º╪«╪¬ ╪ó┘å┘ä╪º█î┘å (TetraPay)</b>\n\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(amount)}</b> ╪¬┘ê┘à╪º┘å\n\n"
            "┘ä╪╖┘ü╪º┘ï ╪º╪▓ █î┌⌐█î ╪º╪▓ ┘ä█î┘å┌⌐ΓÇî┘ç╪º█î ╪▓█î╪▒ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».\n\n"
            "ΓÅ│ <b>╪¬╪º █î┌⌐ ╪│╪º╪╣╪¬</b> ╪º┌»╪▒ ┘╛╪▒╪»╪º╪«╪¬ΓÇî╪¬┘ê┘å ╪¬╪º█î█î╪» ╪¿╪┤┘ç ╪¿┘ç ╪╡┘ê╪▒╪¬ ╪«┘ê╪»┌⌐╪º╪▒ ┌⌐█î┘ü ┘╛┘ê┘ä ╪┤╪º╪▒┌ÿ ┘à█îΓÇî╪┤┘ê╪».\n"
            "╪»╪▒ ╪║█î╪▒ ╪º█î┘å ╪╡┘ê╪▒╪¬ ╪»┌⌐┘à┘ç <b>╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬</b> ╪▒╪º ╪¿╪▓┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        if pay_url_bot and setting_get("tetrapay_mode_bot", "1") == "1":
            kb.add(types.InlineKeyboardButton("≡ƒÆ│ ┘╛╪▒╪»╪º╪«╪¬ ╪»╪▒ ╪¬┘ä┌»╪▒╪º┘à", url=pay_url_bot))
        if pay_url_web and setting_get("tetrapay_mode_web", "1") == "1":
            kb.add(types.InlineKeyboardButton("≡ƒîÉ ┘╛╪▒╪»╪º╪«╪¬ ╪»╪▒ ┘à╪▒┘ê╪▒┌»╪▒", url=pay_url_web))
        kb.add(types.InlineKeyboardButton("≡ƒöì ╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬", callback_data=f"pay:tetrapay:verify:{payment_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        _start_tetrapay_auto_verify(
            payment_id, authority, uid,
            call.message.chat.id, call.message.message_id,
            "wallet_charge")
        return

    # ΓöÇΓöÇ SwapWallet Crypto (network selection) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "wallet:charge:swapwallet_crypto":
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "╪º╪¿╪¬╪»╪º ┘à╪¿┘ä╪║ ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».", show_alert=True)
            return
        if not is_gateway_in_range("swapwallet_crypto", amount):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(amount)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç SwapWallet ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import SWAPWALLET_CRYPTO_NETWORKS, NETWORK_LABELS as SW_NET_LABELS
        state_set(uid, "swcrypto_network_select", kind="wallet_charge", amount=amount)
        kb = types.InlineKeyboardMarkup()
        for net, _ in SWAPWALLET_CRYPTO_NETWORKS:
            kb.add(types.InlineKeyboardButton(SW_NET_LABELS.get(net, net), callback_data=f"swcrypto:net:{net}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÆÄ <b>┘╛╪▒╪»╪º╪«╪¬ ┌⌐╪▒█î┘╛╪¬┘ê (SwapWallet)</b>\n\n╪┤╪¿┌⌐┘ç ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data == "wallet:charge:tronpays_rial":
        sd     = state_data(uid)
        amount = sd.get("amount")
        if not amount:
            bot.answer_callback_query(call.id, "╪º╪¿╪¬╪»╪º ┘à╪¿┘ä╪║ ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».", show_alert=True)
            return
        if not is_gateway_in_range("tronpays_rial", amount):
            _rng = get_gateway_range_text("tronpays_rial")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(amount)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç TronsPay ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        order_id = f"wallet-{uid}-{int(datetime.now().timestamp())}"
        success, result = create_tronpays_rial_invoice(amount, order_id, "╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä")
        if not success:
            err_msg = result.get("error", "╪«╪╖╪º█î ┘å╪º╪┤┘å╪º╪«╪¬┘ç") if isinstance(result, dict) else str(result)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"ΓÜá∩╕Å <b>╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ╪»╪▒┌»╪º┘ç TronPays</b>\n\n"
                f"<code>{esc(err_msg[:400])}</code>\n\n"
                "≡ƒÆí ┘à╪╖┘à╪ª┘å ╪┤┘ê█î╪» ┌⌐┘ä█î╪» API ╪╡╪¡█î╪¡ ┘ê╪º╪▒╪» ╪┤╪»┘ç ╪¿╪º╪┤╪».",
                back_button("wallet:charge"))
            return
        invoice_id = result.get("invoice_id")
        invoice_url = result.get("invoice_url")
        if not invoice_id or not invoice_url:
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"ΓÜá∩╕Å <b>╪«╪╖╪º ╪»╪▒ ╪º█î╪¼╪º╪» ┘ü╪º┌⌐╪¬┘ê╪▒ TronPays</b>\n\n"
                f"<code>┘╛╪º╪│╪« API: {esc(str(result)[:400])}</code>",
                back_button("wallet:charge"))
            return
        payment_id = create_payment("wallet_charge", uid, None, amount, "tronpays_rial", status="pending")
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_tronpays_rial_verify", payment_id=payment_id, invoice_id=invoice_id)
        text = (
            "≡ƒÆ│ <b>╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä ΓÇö TronPays</b>\n\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(amount)}</b> ╪¬┘ê┘à╪º┘å\n\n"
            "╪º╪▓ ┘ä█î┘å┌⌐ ╪▓█î╪▒ ┘╛╪▒╪»╪º╪«╪¬ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».\n\n"
            "ΓÅ│ <b>╪¬╪º █î┌⌐ ╪│╪º╪╣╪¬</b> ┘╛╪▒╪»╪º╪«╪¬ ╪¿┘ç ╪╡┘ê╪▒╪¬ ╪«┘ê╪»┌⌐╪º╪▒ ╪¿╪▒╪▒╪│█î ┘à█îΓÇî╪┤┘ê╪».\n"
            "╪»╪▒ ╪║█î╪▒ ╪º█î┘å ╪╡┘ê╪▒╪¬ ╪»┌⌐┘à┘ç ┬½╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬┬╗ ╪▒╪º ╪¿╪▓┘å█î╪»."
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒÆ│ ┘╛╪▒╪»╪º╪«╪¬ ╪º╪▓ ╪»╪▒┌»╪º┘ç TronPays", url=invoice_url))
        kb.add(types.InlineKeyboardButton("≡ƒöì ╪¿╪▒╪▒╪│█î ┘╛╪▒╪»╪º╪«╪¬", callback_data=f"pay:tronpays_rial:verify:{payment_id}"))
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
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        success, inv = check_swapwallet_crypto_invoice(invoice_id)
        if not success:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ╪¿╪▒╪▒╪│█î ┘ê╪╢╪╣█î╪¬ ┘ü╪º┌⌐╪¬┘ê╪▒.", show_alert=True)
            return
        inv_status = inv.get("status", "")
        if inv_status in ("PAID", "COMPLETED") or inv.get("paidAt"):
            if payment["kind"] == "wallet_charge":
                if not complete_payment(payment_id):  # atomic: only one path wins
                    bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
                    return
                update_balance(uid, payment["amount"])
                bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                send_or_edit(call, f"Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ┘ê ┌⌐█î┘ü ┘╛┘ê┘ä ╪┤╪º╪▒┌ÿ ╪┤╪».\n\n≡ƒÆ░ ┘à╪¿┘ä╪║: {fmt_price(payment['amount'])} ╪¬┘ê┘à╪º┘å",
                             back_button("main"))
                state_clear(uid)
            else:
                config_id  = payment["config_id"]
                package_id = payment["package_id"]
                package_row = get_package(package_id)
                if not config_id:
                    config_id = reserve_first_config(package_id, payment_id)
                if not config_id:
                    pending_id = create_pending_order(uid, package_id, payment_id, payment["amount"], "swapwallet_crypto")
                    complete_payment(payment_id)
                    bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                    send_or_edit(call,
                        "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪».\n\n"
                        "ΓÜá∩╕Å <b>┘à┘ê╪¼┘ê╪»█î ╪¬╪¡┘ê█î┘ä ┘ü┘ê╪▒█î ╪▒╪¿╪º╪¬ ╪¿┘ç ╪º╪¬┘à╪º┘à ╪▒╪│█î╪».</b>\n"
                        "╪»╪▒╪«┘ê╪º╪│╪¬ ╪┤┘à╪º ╪¿╪▒╪º█î ╪º╪»┘à█î┘å ╪º╪▒╪│╪º┘ä ╪┤╪». ╪»╪▒ ┌⌐┘à╪¬╪▒█î┘å ┘ü╪▒╪╡╪¬ ┌⌐╪º┘å┘ü█î┌» ╪┤┘à╪º ╪¬╪¡┘ê█î┘ä ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                        "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à.", back_button("main"))
                    notify_pending_order_to_admins(pending_id, uid, package_row, payment["amount"], "swapwallet_crypto")
                    state_clear(uid)
                    return
                purchase_id = assign_config_to_user(config_id, uid, package_id, payment["amount"], "swapwallet_crypto", is_test=0)
                complete_payment(payment_id)
                bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
                send_or_edit(call, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪» ┘ê ╪│╪▒┘ê█î╪│ ╪ó┘à╪º╪»┘ç ╪º╪│╪¬.", back_button("main"))
                deliver_purchase_message(call.message.chat.id, purchase_id)
                admin_purchase_notify("SwapWallet Crypto", get_user(uid), package_row, purchase_id=purchase_id)
                state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "Γ¥î ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪¬╪ú█î█î╪» ┘å╪┤╪»┘ç. ┘ä╪╖┘ü╪º┘ï ╪º╪¿╪¬╪»╪º ┘ê╪º╪▒█î╪▓ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».", show_alert=True)
        return

    if data.startswith("pay:swapwallet_crypto:"):
        package_id  = int(data.split(":")[2])
        package_row = get_package(package_id)
        if not package_row or (setting_get("preorder_mode", "0") == "1" and package_row["stock"] <= 0):
            bot.answer_callback_query(call.id, "┘à┘ê╪¼┘ê╪»█î ╪º█î┘å ┘╛┌⌐█î╪¼ ╪¬┘à╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "buy_select_method")
        if not is_gateway_in_range("swapwallet_crypto", price):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç SwapWallet ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import SWAPWALLET_CRYPTO_NETWORKS, NETWORK_LABELS as SW_NET_LABELS
        state_set(uid, "swcrypto_network_select", kind="config_purchase", package_id=package_id, amount=price)
        kb = types.InlineKeyboardMarkup()
        for net, _ in SWAPWALLET_CRYPTO_NETWORKS:
            kb.add(types.InlineKeyboardButton(SW_NET_LABELS.get(net, net), callback_data=f"swcrypto:net:{net}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"buy:p:{package_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÆÄ <b>┘╛╪▒╪»╪º╪«╪¬ ┌⌐╪▒█î┘╛╪¬┘ê (SwapWallet)</b>\n\n╪┤╪¿┌⌐┘ç ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("rpay:swapwallet_crypto:verify:"):
        payment_id = int(data.split(":")[3])
        payment = get_payment(payment_id)
        if not payment or payment["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "╪º█î┘å ┘╛╪▒╪»╪º╪«╪¬ ┘é╪¿┘ä╪º┘ï ┘╛╪▒╪»╪º╪▓╪┤ ╪┤╪»┘ç.", show_alert=True)
            return
        invoice_id = payment["receipt_text"]
        success, inv = check_swapwallet_crypto_invoice(invoice_id)
        if not success:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ╪¿╪▒╪▒╪│█î ┘ê╪╢╪╣█î╪¬ ┘ü╪º┌⌐╪¬┘ê╪▒.", show_alert=True)
            return
        if inv.get("status") in ("PAID", "COMPLETED") or inv.get("paidAt"):
            complete_payment(payment_id)
            package_row = get_package(payment["package_id"])
            config_id   = payment["config_id"]
            with get_conn() as conn:
                row = conn.execute("SELECT purchase_id FROM configs WHERE id=?", (config_id,)).fetchone()
            purchase_id = row["purchase_id"] if row else 0
            item = get_purchase(purchase_id) if purchase_id else None
            bot.answer_callback_query(call.id, "Γ£à ┘╛╪▒╪»╪º╪«╪¬ ╪¬╪ú█î█î╪» ╪┤╪»!")
            send_or_edit(call,
                "Γ£à <b>╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪º╪▒╪│╪º┘ä ╪┤╪»</b>\n\n"
                "≡ƒöä ╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪» ╪│╪▒┘ê█î╪│ ╪┤┘à╪º ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪½╪¿╪¬ ┘ê ╪¿╪▒╪º█î ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪º╪▒╪│╪º┘ä ╪┤╪».\n"
                "ΓÅ│ ┘ä╪╖┘ü╪º┘ï ┌⌐┘à█î ╪╡╪¿╪▒ ┌⌐┘å█î╪»╪î ┘╛╪│ ╪º╪▓ ╪º┘å╪¼╪º┘à ╪¬┘à╪»█î╪» ╪¿┘ç ╪┤┘à╪º ╪º╪╖┘ä╪º╪╣ ╪»╪º╪»┘ç ╪«┘ê╪º┘ç╪» ╪┤╪».\n\n"
                "≡ƒÖÅ ╪º╪▓ ╪╡╪¿╪▒ ┘ê ╪┤┌⌐█î╪¿╪º█î█î ╪┤┘à╪º ┘à╪¬╪┤┌⌐╪▒█î┘à.",
                back_button("main"))
            if item:
                admin_renewal_notify(uid, item, package_row, payment["amount"], "SwapWallet Crypto")
            state_clear(uid)
        else:
            bot.answer_callback_query(call.id, "Γ¥î ┘╛╪▒╪»╪º╪«╪¬ ┘ç┘å┘ê╪▓ ╪¬╪ú█î█î╪» ┘å╪┤╪»┘ç. ┘ä╪╖┘ü╪º┘ï ╪º╪¿╪¬╪»╪º ┘ê╪º╪▒█î╪▓ ╪▒╪º ╪º┘å╪¼╪º┘à ╪»┘ç█î╪».", show_alert=True)
        return

    if data.startswith("rpay:swapwallet_crypto:"):
        parts = data.split(":")
        purchase_id = int(parts[2])
        package_id  = int(parts[3])
        item = get_purchase(purchase_id)
        package_row = get_package(package_id)
        if not item or item["user_id"] != uid:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        price = _get_state_price(uid, package_row, "renew_select_method")
        if not is_gateway_in_range("swapwallet_crypto", price):
            _rng = get_gateway_range_text("swapwallet_crypto")
            bot.answer_callback_query(call.id,
                f"Γ¢ö∩╕Å ┘à╪¿┘ä╪║ {fmt_price(price)} ╪¬┘ê┘à╪º┘å ╪¿╪▒╪º█î ╪»╪▒┌»╪º┘ç SwapWallet ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.\n"
                f"┘à╪¡╪»┘ê╪»┘ç ┘à╪¼╪º╪▓: {_rng}\n\n"
                "┘ä╪╖┘ü╪º┘ï ╪»╪▒┌»╪º┘ç ╪»█î┌»╪▒█î ┘à╪¬┘å╪º╪│╪¿ ╪¿╪º ╪º█î┘å ┘à╪¿┘ä╪║ ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».",
                show_alert=True)
            return
        from ..gateways.swapwallet_crypto import SWAPWALLET_CRYPTO_NETWORKS, NETWORK_LABELS as SW_NET_LABELS
        state_set(uid, "swcrypto_network_select", kind="renewal",
                  purchase_id=purchase_id, package_id=package_id,
                  amount=price, config_id=item["config_id"])
        kb = types.InlineKeyboardMarkup()
        for net, _ in SWAPWALLET_CRYPTO_NETWORKS:
            kb.add(types.InlineKeyboardButton(SW_NET_LABELS.get(net, net), callback_data=f"swcrypto:net:{net}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"renew:{purchase_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÆÄ <b>┘╛╪▒╪»╪º╪«╪¬ ┌⌐╪▒█î┘╛╪¬┘ê (SwapWallet)</b>\n\n╪┤╪¿┌⌐┘ç ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    # ΓöÇΓöÇ SwapWallet Crypto: network selected ΓåÆ create invoice ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("swcrypto:net:"):
        network = data.split(":")[2]
        sd      = state_data(uid)
        kind    = sd.get("kind", "")
        amount  = sd.get("amount", 0)
        if not amount:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ╪º╪╖┘ä╪º╪╣╪º╪¬ ╪│┘ü╪º╪▒╪┤.", show_alert=True)
            return
        order_id = f"swc-{uid}-{int(datetime.now().timestamp())}"
        desc = "╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä" if kind == "wallet_charge" else "┘╛╪▒╪»╪º╪«╪¬ ┌⌐╪▒█î┘╛╪¬┘ê"
        success, result = create_swapwallet_crypto_invoice(amount, order_id, network, desc)
        if not success:
            err_msg = result.get("error", "╪«╪╖╪º█î ┘å╪º╪┤┘å╪º╪«╪¬┘ç") if isinstance(result, dict) else str(result)
            _swapwallet_error_inline(call, err_msg)
            return
        invoice_id = result.get("id", "")
        if kind == "wallet_charge":
            payment_id = create_payment("wallet_charge", uid, None, amount, "swapwallet_crypto", status="pending")
            verify_cb  = f"pay:swapwallet_crypto:verify:{payment_id}"
        elif kind == "config_purchase":
            package_id = sd.get("package_id")
            payment_id = create_payment("config_purchase", uid, package_id, amount, "swapwallet_crypto", status="pending")
            verify_cb  = f"pay:swapwallet_crypto:verify:{payment_id}"
        elif kind == "renewal":
            package_id  = sd.get("package_id")
            config_id_r = sd.get("config_id")
            payment_id  = create_payment("renewal", uid, package_id, amount, "swapwallet_crypto",
                                          status="pending", config_id=config_id_r)
            verify_cb   = f"rpay:swapwallet_crypto:verify:{payment_id}"
        else:
            bot.answer_callback_query(call.id, "╪«╪╖╪º ╪»╪▒ ┘å┘ê╪╣ ┘╛╪▒╪»╪º╪«╪¬.", show_alert=True)
            return
        with get_conn() as conn:
            conn.execute("UPDATE payments SET receipt_text=? WHERE id=?", (invoice_id, payment_id))
        state_set(uid, "await_swapwallet_crypto_verify", payment_id=payment_id, invoice_id=invoice_id)
        bot.answer_callback_query(call.id)
        show_swapwallet_crypto_page(call, amount_toman=amount, invoice_id=invoice_id,
                                    result=result, payment_id=payment_id, verify_cb=verify_cb)
        return

    # ΓöÇΓöÇ Admin panel ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if not is_admin(uid):
        # Non-admin shouldn't reach admin callbacks, just ignore
        if data.startswith("admin:") or data.startswith("adm:"):
            bot.answer_callback_query(call.id, "╪º╪¼╪º╪▓┘ç ╪»╪│╪¬╪▒╪│█î ┘å╪»╪º╪▒█î╪».", show_alert=True)
            return

    if data == "admin:panel":
        bot.answer_callback_query(call.id)
        text = (
            "ΓÜÖ∩╕Å <b>┘╛┘å┘ä ┘à╪»█î╪▒█î╪¬</b>\n\n"
            "╪¿╪«╪┤ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:\n\n"
            "ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ\n"
            "≡ƒÆí <b>ConfigFlow v2.0</b>\n"
            "≡ƒæ¿ΓÇì≡ƒÆ╗ Developer: @Emad_Habibnia\n"
            "≡ƒîÉ <a href='https://github.com/Emadhabibnia1385/ConfigFlow'>GitHub ConfigFlow</a>\n"
            "Γ¥ñ∩╕Å <a href='https://t.me/EmadHabibnia/4'>donate</a>"
        )
        send_or_edit(call, text, kb_admin_panel(uid))
        return

    # ΓöÇΓöÇ Admin: Types ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:types":
        if not admin_has_perm(uid, "types_packages"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        _show_admin_types(call)
        bot.answer_callback_query(call.id)
        return

    if data == "admin:type:add":
        state_set(uid, "admin_add_type")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒº⌐ ┘å╪º┘à ┘å┘ê╪╣ ╪¼╪»█î╪» ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("admin:types"))
        return

    if data.startswith("admin:type:edit:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "┘å┘ê╪╣ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤ ┘å╪º┘à", callback_data=f"admin:type:editname:{type_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒô¥ ┘ê█î╪▒╪º█î╪┤ ╪¬┘ê╪╢█î╪¡╪º╪¬", callback_data=f"admin:type:editdesc:{type_id}"))
        if row["description"]:
            kb.add(types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ╪¬┘ê╪╢█î╪¡╪º╪¬", callback_data=f"admin:type:deldesc:{type_id}"))
        is_active = row["is_active"] if "is_active" in row.keys() else 1
        status_label = "Γ£à ┘ü╪╣╪º┘ä ΓÇö ┌⌐┘ä█î┌⌐ ╪¿╪▒╪º█î ╪║█î╪▒┘ü╪╣╪º┘ä" if is_active else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä ΓÇö ┌⌐┘ä█î┌⌐ ╪¿╪▒╪º█î ┘ü╪╣╪º┘ä"
        kb.add(types.InlineKeyboardButton(status_label, callback_data=f"admin:type:toggleactive:{type_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:types"))
        desc_preview = f"\n≡ƒô¥ ╪¬┘ê╪╢█î╪¡╪º╪¬: {esc(row['description'][:80])}..." if row["description"] and len(row["description"]) > 80 else (f"\n≡ƒô¥ ╪¬┘ê╪╢█î╪¡╪º╪¬: {esc(row['description'])}" if row["description"] else "\n≡ƒô¥ ╪¬┘ê╪╢█î╪¡╪º╪¬: ┘å╪»╪º╪▒╪»")
        status_line  = "\n≡ƒöÿ ┘ê╪╢╪╣█î╪¬: <b>┘ü╪╣╪º┘ä</b>" if is_active else "\n≡ƒöÿ ┘ê╪╢╪╣█î╪¬: <b>╪║█î╪▒┘ü╪╣╪º┘ä</b>"
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ┘å┘ê╪╣:</b> {esc(row['name'])}{desc_preview}{status_line}", kb)
        return

    if data.startswith("admin:type:editname:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "┘å┘ê╪╣ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        state_set(uid, "admin_edit_type", type_id=type_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"Γ£Å∩╕Å ┘å╪º┘à ╪¼╪»█î╪» ╪¿╪▒╪º█î ┘å┘ê╪╣ <b>{esc(row['name'])}</b> ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:",
                     back_button("admin:types"))
        return

    if data.startswith("admin:type:editdesc:"):
        type_id = int(data.split(":")[3])
        row     = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "┘å┘ê╪╣ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        state_set(uid, "admin_edit_type_desc", type_id=type_id)
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("ΓÅ¡ ╪¬┘ê╪╢█î╪¡╪º╪¬█î ┘å┘à█îΓÇî╪«┘ê╪º┘ç┘à ┘ê╪º╪▒╪» ┌⌐┘å┘à", callback_data=f"admin:type:deldesc:{type_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"admin:type:edit:{type_id}"))
        send_or_edit(call,
            f"≡ƒô¥ ╪¬┘ê╪╢█î╪¡╪º╪¬ ╪¼╪»█î╪» ╪¿╪▒╪º█î ┘å┘ê╪╣ <b>{esc(row['name'])}</b> ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:\n\n"
            "╪º█î┘å ╪¬┘ê╪╢█î╪¡╪º╪¬ ┘╛╪│ ╪º╪▓ ╪º╪▒╪│╪º┘ä ┌⌐╪º┘å┘ü█î┌» ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒ ┘å┘à╪º█î╪┤ ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪».", kb)
        return

    if data == "admin:type:skipdesc":
        sn = state_name(uid)
        sd_val = state_data(uid)
        if sn == "admin_add_type_desc":
            name = sd_val.get("type_name", "")
            try:
                add_type(name, "")
                state_clear(uid)
                bot.answer_callback_query(call.id, "Γ£à ┘å┘ê╪╣ ╪½╪¿╪¬ ╪┤╪».")
                bot.send_message(call.message.chat.id, "Γ£à ┘å┘ê╪╣ ╪¼╪»█î╪» ╪½╪¿╪¬ ╪┤╪».", reply_markup=kb_admin_panel())
                log_admin_action(uid, f"┘å┘ê╪╣ ╪¼╪»█î╪» ╪½╪¿╪¬ ╪┤╪»: <b>{esc(name)}</b>")
            except sqlite3.IntegrityError:
                state_clear(uid)
                bot.answer_callback_query(call.id, "ΓÜá∩╕Å ╪º█î┘å ┘å┘ê╪╣ ┘é╪¿┘ä╪º┘ï ╪½╪¿╪¬ ╪┤╪»┘ç.", show_alert=True)
        else:
            bot.answer_callback_query(call.id)
        return

    if data.startswith("admin:type:deldesc:"):
        type_id = int(data.split(":")[3])
        update_type_description(type_id, "")
        state_clear(uid)
        bot.answer_callback_query(call.id, "Γ£à ╪¬┘ê╪╢█î╪¡╪º╪¬ ╪¡╪░┘ü ╪┤╪».")
        log_admin_action(uid, f"╪¬┘ê╪╢█î╪¡╪º╪¬ ┘å┘ê╪╣ #{type_id} ╪¡╪░┘ü ╪┤╪»")
        _show_admin_types(call)
        return

    if data.startswith("admin:type:toggleactive:"):
        type_id = int(data.split(":")[3])
        row = get_type(type_id)
        if not row:
            bot.answer_callback_query(call.id, "┘å┘ê╪╣ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        cur = row["is_active"] if "is_active" in row.keys() else 1
        update_type_active(type_id, 0 if cur else 1)
        new_status = "╪║█î╪▒┘ü╪╣╪º┘ä" if cur else "┘ü╪╣╪º┘ä"
        bot.answer_callback_query(call.id, f"Γ£à ┘å┘ê╪╣ {new_status} ╪┤╪».")
        log_admin_action(uid, f"┘å┘ê╪╣ <b>{esc(row['name'])}</b> {new_status} ╪┤╪»")
        # re-open the edit screen with updated state
        call.data = f"admin:type:edit:{type_id}"
        data      = call.data

    if data.startswith("admin:pkg:toggleactive:"):
        package_id = int(data.split(":")[3])
        pkg = get_package(package_id)
        if not pkg:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        toggle_package_active(package_id)
        cur = pkg["active"] if "active" in pkg.keys() else 1
        new_status = "╪║█î╪▒┘ü╪╣╪º┘ä" if cur else "┘ü╪╣╪º┘ä"
        bot.answer_callback_query(call.id, f"Γ£à ┘╛┌⌐█î╪¼ {new_status} ╪┤╪».")
        log_admin_action(uid, f"┘╛┌⌐█î╪¼ <b>{esc(pkg['name'])}</b> {new_status} ╪┤╪»")
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
                bot.answer_callback_query(call.id, f"Γ¥î {sold_in_type} ┌⌐╪º┘å┘ü█î┌» ┘ü╪▒┘ê╪«╪¬┘çΓÇî╪┤╪»┘ç ╪»╪▒ ╪º█î┘å ┘å┘ê╪╣ ┘ê╪¼┘ê╪» ╪»╪º╪▒╪».", show_alert=True)
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
                types.InlineKeyboardButton("Γ£à ╪¿┘ä┘ç╪î ┘ç┘à┘ç ╪¡╪░┘ü ╪┤┘ê╪»", callback_data=f"admin:type:delok:{type_id}"),
                types.InlineKeyboardButton("Γ¥î ╪º┘å╪╡╪▒╪º┘ü", callback_data="admin:types"),
            )
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"ΓÜá∩╕Å <b>╪¬╪ú█î█î╪» ╪¡╪░┘ü ┘å┘ê╪╣</b>\n\n"
                f"{pack_count} ┘╛┌⌐█î╪¼ ┘ê {total_cfg} ┌⌐╪º┘å┘ü█î┌» (┘à┘ê╪¼┘ê╪»/┘à┘å┘é╪╢█î) ┘ç┘à╪▒╪º┘ç ╪¿╪º ╪º█î┘å ┘å┘ê╪╣ ╪¡╪░┘ü ╪«┘ê╪º┘ç┘å╪» ╪┤╪».\n"
                "╪ó█î╪º ┘à╪╖┘à╪ª┘å ┘ç╪│╪¬█î╪»╪ƒ", kb_c)
            return
        delete_type(type_id)
        bot.answer_callback_query(call.id, "Γ£à ┘å┘ê╪╣ ╪¡╪░┘ü ╪┤╪».")
        log_admin_action(uid, f"┘å┘ê╪╣ #{type_id} ╪¡╪░┘ü ╪┤╪»")
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
            bot.answer_callback_query(call.id, "Γ¥î ╪»╪▒ ╪º█î┘å ┘ü╪º╪╡┘ä┘ç ┌⌐╪º┘å┘ü█î┌» ┘ü╪▒┘ê╪«╪¬┘ç ╪┤╪». ╪¡╪░┘ü ┘à┘à┌⌐┘å ┘å█î╪│╪¬.", show_alert=True)
            _show_admin_types(call)
            return
        delete_type(type_id)
        bot.answer_callback_query(call.id, "Γ£à ┘å┘ê╪╣ ┘ê ╪¬┘à╪º┘à ┘╛┌⌐█î╪¼ΓÇî┘ç╪º█î ╪ó┘å ╪¡╪░┘ü ╪┤╪»┘å╪».")
        log_admin_action(uid, f"┘å┘ê╪╣ #{type_id} ╪¿╪º ╪¬┘à╪º┘à ┘╛┌⌐█î╪¼ΓÇî┘ç╪º ╪¡╪░┘ü ╪┤╪»")
        _show_admin_types(call)
        return

    if data.startswith("admin:pkg:add:t:"):
        type_id  = int(data.split(":")[4])
        type_row = get_type(type_id)
        state_set(uid, "admin_add_package_name", type_id=type_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"Γ£Å∩╕Å ┘å╪º┘à ┘╛┌⌐█î╪¼ ╪¿╪▒╪º█î ┘å┘ê╪╣ <b>{esc(type_row['name'])}</b> ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
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
            "≡ƒöï ╪¡╪¼┘à ┘╛┌⌐█î╪¼ ╪▒╪º ╪¿┘ç ┌»█î┌» ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:\n"
            "≡ƒÆí ╪¿╪▒╪º█î ╪¡╪¼┘à ┘å╪º┘à╪¡╪»┘ê╪» ╪╣╪»╪» <b>0</b> ╪¿┘ü╪▒╪│╪¬█î╪».\n"
            "≡ƒÆí ╪¿╪▒╪º█î ┌⌐┘à╪¬╪▒ ╪º╪▓ █▒ ┌»█î┌» ╪º╪╣╪┤╪º╪▒ ┘ê╪º╪▒╪» ┌⌐┘å█î╪» (┘à╪½┘ä╪º┘ï <b>0.5</b>).",
            back_button("admin:types"))
        return

    if data.startswith("admin:pkg:edit:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        show_name_val = package_row['show_name'] if 'show_name' in package_row.keys() else 1
        show_name_lbl = "≡ƒæü ┘å┘à╪º█î╪┤ ┘å╪º┘à ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒: Γ£à ╪¿┘ä┘ç" if show_name_val else "≡ƒæü ┘å┘à╪º█î╪┤ ┘å╪º┘à ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒: Γ¥î ╪«█î╪▒"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤ ┘å╪º┘à",   callback_data=f"admin:pkg:ef:name:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒÆ░ ┘ê█î╪▒╪º█î╪┤ ┘é█î┘à╪¬",  callback_data=f"admin:pkg:ef:price:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöï ┘ê█î╪▒╪º█î╪┤ ╪¡╪¼┘à",   callback_data=f"admin:pkg:ef:volume:{package_id}"))
        kb.add(types.InlineKeyboardButton("ΓÅ░ ┘ê█î╪▒╪º█î╪┤ ┘à╪»╪¬",   callback_data=f"admin:pkg:ef:dur:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒôî ╪¼╪º█î┌»╪º┘ç ┘å┘à╪º█î╪┤",  callback_data=f"admin:pkg:ef:position:{package_id}"))
        kb.add(types.InlineKeyboardButton(show_name_lbl,      callback_data=f"admin:pkg:toggle_sn:{package_id}"))
        pkg_active = package_row['active'] if 'active' in package_row.keys() else 1
        pkg_status_label = "Γ£à ┘ü╪╣╪º┘ä ΓÇö ┌⌐┘ä█î┌⌐ ╪¿╪▒╪º█î ╪║█î╪▒┘ü╪╣╪º┘ä" if pkg_active else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä ΓÇö ┌⌐┘ä█î┌⌐ ╪¿╪▒╪º█î ┘ü╪╣╪º┘ä"
        kb.add(types.InlineKeyboardButton(pkg_status_label, callback_data=f"admin:pkg:toggleactive:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬",       callback_data="admin:types"))
        bot.answer_callback_query(call.id)
        cur_pos = package_row['position'] if 'position' in package_row.keys() else 0
        pkg_status_line = "Γ£à ┘ü╪╣╪º┘ä" if pkg_active else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
        sn_line = "Γ£à ╪¿┘ä┘ç" if show_name_val else "Γ¥î ╪«█î╪▒"
        text = (
            f"≡ƒôª <b>┘ê█î╪▒╪º█î╪┤ ┘╛┌⌐█î╪¼</b>\n\n"
            f"┘å╪º┘à: {esc(package_row['name'])}\n"
            f"┘é█î┘à╪¬: {fmt_price(package_row['price'])} ╪¬┘ê┘à╪º┘å\n"
            f"╪¡╪¼┘à: {fmt_vol(package_row['volume_gb'])}\n"
            f"┘à╪»╪¬: {fmt_dur(package_row['duration_days'])}\n"
            f"╪¼╪º█î┌»╪º┘ç: {cur_pos}\n"
            f"┘å┘à╪º█î╪┤ ┘å╪º┘à ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒: {sn_line}\n"
            f"┘ê╪╢╪╣█î╪¬: {pkg_status_line}"
        )
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pkg:toggle_sn:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        if not package_row:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        cur_sn  = package_row['show_name'] if 'show_name' in package_row.keys() else 1
        new_sn  = 0 if cur_sn else 1
        update_package_field(package_id, "show_name", new_sn)
        log_admin_action(uid, f"┘å┘à╪º█î╪┤ ┘å╪º┘à ┘╛┌⌐█î╪¼ #{package_id} {'┘ü╪╣╪º┘ä' if new_sn else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "Γ£à ╪¬┘å╪╕█î┘à ┘å┘à╪º█î╪┤ ┘å╪º┘à ╪¿╪▒┘ê╪▓╪▒╪│╪º┘å█î ╪┤╪».")
        # Refresh edit panel
        package_row = get_package(package_id)
        show_name_val = package_row['show_name'] if 'show_name' in package_row.keys() else 1
        show_name_lbl = "≡ƒæü ┘å┘à╪º█î╪┤ ┘å╪º┘à ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒: Γ£à ╪¿┘ä┘ç" if show_name_val else "≡ƒæü ┘å┘à╪º█î╪┤ ┘å╪º┘à ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒: Γ¥î ╪«█î╪▒"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤ ┘å╪º┘à",   callback_data=f"admin:pkg:ef:name:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒÆ░ ┘ê█î╪▒╪º█î╪┤ ┘é█î┘à╪¬",  callback_data=f"admin:pkg:ef:price:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöï ┘ê█î╪▒╪º█î╪┤ ╪¡╪¼┘à",   callback_data=f"admin:pkg:ef:volume:{package_id}"))
        kb.add(types.InlineKeyboardButton("ΓÅ░ ┘ê█î╪▒╪º█î╪┤ ┘à╪»╪¬",   callback_data=f"admin:pkg:ef:dur:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒôî ╪¼╪º█î┌»╪º┘ç ┘å┘à╪º█î╪┤",  callback_data=f"admin:pkg:ef:position:{package_id}"))
        kb.add(types.InlineKeyboardButton(show_name_lbl,      callback_data=f"admin:pkg:toggle_sn:{package_id}"))
        pkg_active = package_row['active'] if 'active' in package_row.keys() else 1
        pkg_status_label = "Γ£à ┘ü╪╣╪º┘ä ΓÇö ┌⌐┘ä█î┌⌐ ╪¿╪▒╪º█î ╪║█î╪▒┘ü╪╣╪º┘ä" if pkg_active else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä ΓÇö ┌⌐┘ä█î┌⌐ ╪¿╪▒╪º█î ┘ü╪╣╪º┘ä"
        kb.add(types.InlineKeyboardButton(pkg_status_label, callback_data=f"admin:pkg:toggleactive:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬",       callback_data="admin:types"))
        cur_pos = package_row['position'] if 'position' in package_row.keys() else 0
        pkg_status_line = "Γ£à ┘ü╪╣╪º┘ä" if pkg_active else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
        sn_line = "Γ£à ╪¿┘ä┘ç" if show_name_val else "Γ¥î ╪«█î╪▒"
        text = (
            f"≡ƒôª <b>┘ê█î╪▒╪º█î╪┤ ┘╛┌⌐█î╪¼</b>\n\n"
            f"┘å╪º┘à: {esc(package_row['name'])}\n"
            f"┘é█î┘à╪¬: {fmt_price(package_row['price'])} ╪¬┘ê┘à╪º┘å\n"
            f"╪¡╪¼┘à: {fmt_vol(package_row['volume_gb'])}\n"
            f"┘à╪»╪¬: {fmt_dur(package_row['duration_days'])}\n"
            f"╪¼╪º█î┌»╪º┘ç: {cur_pos}\n"
            f"┘å┘à╪º█î╪┤ ┘å╪º┘à ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒: {sn_line}\n"
            f"┘ê╪╢╪╣█î╪¬: {pkg_status_line}"
        )
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pkg:ef:"):
        parts      = data.split(":")
        field_key  = parts[3]
        package_id = int(parts[4])
        state_set(uid, "admin_edit_pkg_field", field_key=field_key, package_id=package_id)
        labels     = {"name": "┘å╪º┘à", "price": "┘é█î┘à╪¬ (╪¬┘ê┘à╪º┘å)", "volume": "╪¡╪¼┘à (GB)", "dur": "┘à╪»╪¬ (╪▒┘ê╪▓)", "position": "╪¼╪º█î┌»╪º┘ç ┘å┘à╪º█î╪┤"}
        bot.answer_callback_query(call.id)
        send_or_edit(call, f"Γ£Å∩╕Å ┘à┘é╪»╪º╪▒ ╪¼╪»█î╪» ╪¿╪▒╪º█î <b>{labels.get(field_key, field_key)}</b> ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
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
                bot.answer_callback_query(call.id, f"Γ¥î ╪º█î┘å ┘╛┌⌐█î╪¼ {sold_count} ┌⌐╪º┘å┘ü█î┌» ┘ü╪▒┘ê╪«╪¬┘çΓÇî╪┤╪»┘ç ╪»╪º╪▒╪» ┘ê ┘é╪º╪¿┘ä ╪¡╪░┘ü ┘å█î╪│╪¬.", show_alert=True)
                return
            unsold_cfg = conn.execute(
                "SELECT COUNT(*) AS n FROM configs WHERE package_id=?",
                (package_id,)
            ).fetchone()["n"]
        if unsold_cfg > 0:
            kb_c = types.InlineKeyboardMarkup()
            kb_c.row(
                types.InlineKeyboardButton("Γ£à ╪¿┘ä┘ç╪î ╪¡╪░┘ü ╪┤┘ê╪»", callback_data=f"admin:pkg:delok:{package_id}"),
                types.InlineKeyboardButton("Γ¥î ╪º┘å╪╡╪▒╪º┘ü", callback_data="admin:types"),
            )
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"ΓÜá∩╕Å <b>╪¬╪ú█î█î╪» ╪¡╪░┘ü ┘╛┌⌐█î╪¼</b>\n\n"
                f"{unsold_cfg} ┌⌐╪º┘å┘ü█î┌» ┘à┘ê╪¼┘ê╪»/┘à┘å┘é╪╢█î ┘ç┘à╪▒╪º┘ç ╪¿╪º ┘╛┌⌐█î╪¼ ╪¡╪░┘ü ╪«┘ê╪º┘ç┘å╪» ╪┤╪».\n"
                "╪ó█î╪º ┘à╪╖┘à╪ª┘å ┘ç╪│╪¬█î╪»╪ƒ", kb_c)
            return
        delete_package(package_id)
        bot.answer_callback_query(call.id, "Γ£à ┘╛┌⌐█î╪¼ ╪¡╪░┘ü ╪┤╪».")
        log_admin_action(uid, f"┘╛┌⌐█î╪¼ #{package_id} ╪¡╪░┘ü ╪┤╪»")
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
            bot.answer_callback_query(call.id, "Γ¥î ╪»╪▒ ╪º█î┘å ┘ü╪º╪╡┘ä┘ç ┌⌐╪º┘å┘ü█î┌» ┘ü╪▒┘ê╪«╪¬┘ç ╪┤╪». ╪¡╪░┘ü ┘à┘à┌⌐┘å ┘å█î╪│╪¬.", show_alert=True)
            _show_admin_types(call)
            return
        delete_package(package_id)
        bot.answer_callback_query(call.id, "Γ£à ┘╛┌⌐█î╪¼ ┘ê ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º█î ╪ó┘å ╪¡╪░┘ü ╪┤╪»┘å╪».")
        log_admin_action(uid, f"┘╛┌⌐█î╪¼ #{package_id} ╪¿╪º ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º ╪¡╪░┘ü ╪┤╪»")
        _show_admin_types(call)
        return

    # ΓöÇΓöÇ Admin: Add Config ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:add_config":
        types_list = get_all_types()
        kb = types.InlineKeyboardMarkup()
        for item in types_list:
            kb.add(types.InlineKeyboardButton(f"≡ƒº⌐ {item['name']}", callback_data=f"adm:cfg:t:{item['id']}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:panel"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒô¥ <b>╪½╪¿╪¬ ┌⌐╪º┘å┘ü█î┌»</b>\n\n┘å┘ê╪╣ ┌⌐╪º┘å┘ü█î┌» ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
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
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:add_config"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôª ┘╛┌⌐█î╪¼ ┘à╪▒╪¿┘ê╪╖┘ç ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("adm:cfg:p:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒô¥ ╪½╪¿╪¬ ╪¬┌⌐█î", callback_data=f"adm:cfg:single:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒôï ╪½╪¿╪¬ ╪»╪│╪¬┘çΓÇî╪º█î", callback_data=f"adm:cfg:bulk:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:cfg:t:{package_row['type_id']}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒô¥ ╪▒┘ê╪┤ ╪½╪¿╪¬ ┌⌐╪º┘å┘ü█î┌» ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("adm:cfg:single:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        state_set(uid, "admin_add_config_service", package_id=package_id, type_id=package_row["type_id"])
        bot.answer_callback_query(call.id)
        send_or_edit(call, "Γ£Å∩╕Å ┘å╪º┘à ╪│╪▒┘ê█î╪│ ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:", back_button("admin:add_config"))
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
                "Γ£é∩╕Å <b>┘╛╪│┘ê┘å╪» ╪¡╪░┘ü█î ╪º╪▓ ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌»</b>\n\n"
                "┘ê┘é╪¬█î ┌å┘å╪»╪¬╪º ╪º┌⌐╪│╪¬╪▒┘å╪º┘ä ┘╛╪▒┘ê┌⌐╪│█î ╪│╪¬ ┘à█îΓÇî┌⌐┘å█î╪»╪î ╪º┘å╪¬┘ç╪º█î ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌» ┘à╪¬┘åΓÇî┘ç╪º█î ╪º╪╢╪º┘ü┘ç ╪º┌⌐╪│╪¬╪▒┘å╪º┘äΓÇî┘ç╪º ╪º╪╢╪º┘ü┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                "╪º┌»╪▒ ┘å┘à█îΓÇî╪«┘ê╪º┘ç█î╪» ╪ó┘åΓÇî┘ç╪º ╪»╪▒ ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌» ╪¿█î╪º█î╪»╪î ┘╛╪│┘ê┘å╪» ╪▒╪º ╪º█î┘å╪¼╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».\n\n"
                "≡ƒÆí ┘à╪½╪º┘ä: <code>-main</code>",
                back_button("admin:add_config"))
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("ΓÅ¡ ╪¿╪╣╪»█î (╪¿╪»┘ê┘å ┘╛╪│┘ê┘å╪»)", callback_data=f"adm:cfg:bulk:skipsuf:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:add_config"))
            send_or_edit(call,
                "Γ£é∩╕Å <b>┘╛╪│┘ê┘å╪» ╪¡╪░┘ü█î ╪º╪▓ ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌»</b>\n\n"
                "┘ê┘é╪¬█î ┌å┘å╪»╪¬╪º ╪º┌⌐╪│╪¬╪▒┘å╪º┘ä ┘╛╪▒┘ê┌⌐╪│█î ╪│╪¬ ┘à█îΓÇî┌⌐┘å█î╪»╪î ╪º┘å╪¬┘ç╪º█î ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌» ┘à╪¬┘åΓÇî┘ç╪º█î ╪º╪╢╪º┘ü┘ç ╪º┌⌐╪│╪¬╪▒┘å╪º┘äΓÇî┘ç╪º ╪º╪╢╪º┘ü┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                "╪º┌»╪▒ ┘å┘à█îΓÇî╪«┘ê╪º┘ç█î╪» ╪ó┘åΓÇî┘ç╪º ╪»╪▒ ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌» ╪¿█î╪º█î╪»╪î ┘╛╪│┘ê┘å╪» ╪▒╪º ╪º█î┘å╪¼╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».\n\n"
                "≡ƒÆí ┘à╪½╪º┘ä: <code>-main</code>", kb)
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
                    "≡ƒôï <b>╪º╪▒╪│╪º┘ä ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º</b>\n\n"
                    "┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪». ╪»┘ê ╪▒┘ê╪┤ ┘ê╪¼┘ê╪» ╪»╪º╪▒╪»:\n\n"
                    "<b>≡ƒô¥ ╪▒┘ê╪┤ ╪º┘ê┘ä: ╪º╪▒╪│╪º┘ä ┘à╪¬┘å█î</b>\n"
                    "┘ç╪▒ ┌⌐╪º┘å┘ü█î┌» <b>╪»┘ê ╪«╪╖</b> ╪»╪º╪▒╪»:\n"
                    "╪«╪╖ ╪º┘ê┘ä: ┘ä█î┘å┌⌐ ┌⌐╪º┘å┘ü█î┌»\n"
                    "╪«╪╖ ╪»┘ê┘à: ┘ä█î┘å┌⌐ ╪º╪│╪¬╪╣┘ä╪º┘à (╪┤╪▒┘ê╪╣ ╪¿╪º http)\n\n"
                    "≡ƒÆí ┘à╪½╪º┘ä:\n"
                    "<code>vless://abc...#name1\n"
                    "http://panel.com/sub/1\n"
                    "vless://def...#name2\n"
                    "http://panel.com/sub/2</code>\n\n"
                    "<b>≡ƒôÄ ╪▒┘ê╪┤ ╪»┘ê┘à: ╪º╪▒╪│╪º┘ä ┘ü╪º█î┘ä TXT</b>\n"
                    "╪º┌»╪▒ ╪¬╪╣╪»╪º╪» ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º█î╪¬╪º┘å ╪▓█î╪º╪» ╪º╪│╪¬ (╪¿█î╪┤ ╪º╪▓ █▒█░-█▒█╡ ╪╣╪»╪»)╪î "
                    "█î┌⌐ ┘ü╪º█î┘ä <b>.txt</b> ╪¿╪│╪º╪▓█î╪» ┘ê ╪¬┘à╪º┘à ┘ä█î┘å┌⌐ΓÇî┘ç╪º ╪▒╪º ╪»╪▒ ╪ó┘å ┘é╪▒╪º╪▒ ╪»┘ç█î╪» "
                    "(┘ç╪▒ ╪«╪╖ █î┌⌐ ┌⌐╪º┘å┘ü█î┌» + ╪«╪╖ ╪¿╪╣╪»█î ┘ä█î┘å┌⌐ ╪º╪│╪¬╪╣┘ä╪º┘à)╪î ╪│┘╛╪│ ┘ü╪º█î┘ä ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»."
                )
            else:
                fmt_text = (
                    "≡ƒôï <b>╪º╪▒╪│╪º┘ä ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º</b>\n\n"
                    "┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪». ╪»┘ê ╪▒┘ê╪┤ ┘ê╪¼┘ê╪» ╪»╪º╪▒╪»:\n\n"
                    "<b>≡ƒô¥ ╪▒┘ê╪┤ ╪º┘ê┘ä: ╪º╪▒╪│╪º┘ä ┘à╪¬┘å█î</b>\n"
                    "┘ç╪▒ ╪«╪╖ █î┌⌐ ┘ä█î┘å┌⌐ ┌⌐╪º┘å┘ü█î┌»:\n\n"
                    "≡ƒÆí ┘à╪½╪º┘ä:\n"
                    "<code>vless://abc...#name1\n"
                    "vless://def...#name2</code>\n\n"
                    "<b>≡ƒôÄ ╪▒┘ê╪┤ ╪»┘ê┘à: ╪º╪▒╪│╪º┘ä ┘ü╪º█î┘ä TXT</b>\n"
                    "╪º┌»╪▒ ╪¬╪╣╪»╪º╪» ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º█î╪¬╪º┘å ╪▓█î╪º╪» ╪º╪│╪¬ (╪¿█î╪┤ ╪º╪▓ █▒█░-█▒█╡ ╪╣╪»╪»)╪î "
                    "█î┌⌐ ┘ü╪º█î┘ä <b>.txt</b> ╪¿╪│╪º╪▓█î╪» ┘ê ╪¬┘à╪º┘à ┘ä█î┘å┌⌐ ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º ╪▒╪º ╪»╪▒ ╪ó┘å ┘é╪▒╪º╪▒ ╪»┘ç█î╪» "
                    "(┘ç╪▒ ╪«╪╖ █î┌⌐ ┌⌐╪º┘å┘ü█î┌»)╪î ╪│┘╛╪│ ┘ü╪º█î┘ä ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»."
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
            kb.add(types.InlineKeyboardButton("ΓÅ¡ ╪¿╪╣╪»█î (╪¿╪»┘ê┘å ┘╛█î╪┤┘ê┘å╪»)", callback_data=f"adm:cfg:bulk:skippre:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:add_config"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "Γ£é∩╕Å <b>┘╛█î╪┤┘ê┘å╪» ╪¡╪░┘ü█î ╪º╪▓ ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌»</b>\n\n"
                "╪▓┘à╪º┘å█î ┌⌐┘ç ┌⌐╪º┘å┘ü█î┌» ╪▒╪º ╪»╪▒ ┘╛┘å┘ä ┘à█îΓÇî╪│╪º╪▓█î╪»╪î ╪º┌»╪▒ ╪º█î┘å╪¿╪º┘å╪» <b>╪▒█î┘à╪º╪▒┌⌐ (Remark)</b> ╪»╪º╪▒╪»╪î "
                "╪º╪¿╪¬╪»╪º█î ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌» ╪º╪╢╪º┘ü┘ç ┘à█îΓÇî╪┤┘ê╪».\n"
                "╪º┌»╪▒ ┘å┘à█îΓÇî╪«┘ê╪º┘ç█î╪» ╪ó┘å ╪»╪▒ ┘å╪º┘à ┌⌐╪º┘å┘ü█î┌» ╪¿█î╪º█î╪»╪î ┘╛█î╪┤┘ê┘å╪» ╪▒╪º ╪º█î┘å╪¼╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».\n\n"
                "≡ƒÆí ┘à╪½╪º┘ä: <code>%E2%9A%95%EF%B8%8FTUN_-</code>\n"
                "█î╪º: <code>ΓÜò∩╕ÅTUN_-</code>", kb)
            return

        # Initial: ask about inquiry links
        package_id  = int(rest)
        package_row = get_package(package_id)
        state_set(uid, "admin_bulk_init", package_id=package_id, type_id=package_row["type_id"])
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("Γ£à ╪¿┘ä┘ç", callback_data=f"adm:cfg:bulk:inq:y:{package_id}"),
            types.InlineKeyboardButton("Γ¥î ╪«█î╪▒", callback_data=f"adm:cfg:bulk:inq:n:{package_id}"),
        )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:cfg:p:{package_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒöù ╪ó█î╪º ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º <b>┘ä█î┘å┌⌐ ╪º╪│╪¬╪╣┘ä╪º┘à</b> ┘ç┘à ╪»╪º╪▒┘å╪»╪ƒ", kb)
        return

    # ΓöÇΓöÇ Admin: Stock / Config management ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:stock":
        if not (admin_has_perm(uid, "view_configs") or admin_has_perm(uid, "register_config") or admin_has_perm(uid, "manage_configs")):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
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
                mark = "Γ¥î"
            elif c["sold_to"]:
                mark = "≡ƒö┤"
            else:
                mark = "≡ƒƒó"
            svc = urllib.parse.unquote(c["service_name"] or "")
            kb.add(types.InlineKeyboardButton(f"{mark} {svc}", callback_data=f"adm:stk:cfg:{c['id']}"))
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton("Γ¼à∩╕Å ┘é╪¿┘ä█î", callback_data=f"adm:stk:all:{kind_str}:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton("╪¿╪╣╪»█î Γ₧í∩╕Å", callback_data=f"adm:stk:all:{kind_str}:{page+1}"))
        if nav_row:
            kb.row(*nav_row)
        # Bulk action buttons
        if kind_str in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ┘ç┘à┌»╪º┘å█î",   callback_data=f"adm:stk:blkA:{kind_str}"),
                types.InlineKeyboardButton("Γ¥î ┘à┘å┘é╪╢█î ┘ç┘à┌»╪º┘å█î", callback_data=f"adm:stk:blkA:{kind_str}"),
            )
        else:
            kb.add(types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ┘ç┘à┌»╪º┘å█î", callback_data=f"adm:stk:blkA:{kind_str}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:stock"))
        bot.answer_callback_query(call.id)
        if kind_str == "sl":
            label_kind = "≡ƒö┤ ┌⌐┘ä ┘ü╪▒┘ê╪«╪¬┘ç ╪┤╪»┘ç"
        elif kind_str == "ex":
            label_kind = "Γ¥î ┌⌐┘ä ┘à┘å┘é╪╢█î ╪┤╪»┘ç"
        else:
            label_kind = "≡ƒƒó ┌⌐┘ä ┘à┘ê╪¼┘ê╪»"
        send_or_edit(call, f"≡ƒôï {label_kind} | ╪╡┘ü╪¡┘ç {page+1}/{total_pages} | ╪¬╪╣╪»╪º╪» ┌⌐┘ä: {total}", kb)
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
            types.InlineKeyboardButton(f"≡ƒƒó ┘à╪º┘å╪»┘ç ({avail})",       callback_data=f"adm:stk:av:{package_id}:0"),
            types.InlineKeyboardButton(f"≡ƒö┤ ┘ü╪▒┘ê╪«╪¬┘ç ({sold})",       callback_data=f"adm:stk:sl:{package_id}:0"),
        )
        kb.add(types.InlineKeyboardButton(f"Γ¥î ┘à┘å┘é╪╢█î ({expired})",  callback_data=f"adm:stk:ex:{package_id}:0"))
        if pending_c > 0:
            kb.add(types.InlineKeyboardButton(
                f"ΓÅ│ ╪¬╪¡┘ê█î┘ä {pending_c} ╪│┘ü╪º╪▒╪┤ ╪»╪▒ ╪º┘å╪¬╪╕╪º╪▒",
                callback_data=f"adm:stk:fulfill:{package_id}"
            ))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:stock"))
        bot.answer_callback_query(call.id)
        pending_line = f"\nΓÅ│ ╪│┘ü╪º╪▒╪┤ ╪»╪▒ ╪º┘å╪¬╪╕╪º╪▒: {pending_c}" if pending_c > 0 else ""
        text = (
            f"≡ƒôª <b>{esc(package_row['name'])}</b>\n\n"
            f"≡ƒƒó ┘à┘ê╪¼┘ê╪»: {avail}\n"
            f"≡ƒö┤ ┘ü╪▒┘ê╪«╪¬┘ç ╪┤╪»┘ç: {sold}\n"
            f"Γ¥î ┘à┘å┘é╪╢█î ╪┤╪»┘ç: {expired}"
            f"{pending_line}"
        )
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:stk:fulfill:"):
        package_id  = int(data.split(":")[3])
        package_row = get_package(package_id)
        bot.answer_callback_query(call.id, "ΓÅ│ ╪»╪▒ ╪¡╪º┘ä ╪¬╪¡┘ê█î┘ä ╪│┘ü╪º╪▒╪┤ΓÇî┘ç╪º...")
        try:
            fulfilled = auto_fulfill_pending_orders(package_id)
            if fulfilled > 0:
                send_or_edit(call,
                    f"Γ£à <b>{fulfilled}</b> ╪│┘ü╪º╪▒╪┤ ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪¬╪¡┘ê█î┘ä ╪»╪º╪»┘ç ╪┤╪».",
                    back_button(f"adm:stk:pk:{package_id}"))
            else:
                # Check if there are still pending orders (no stock available)
                with get_conn() as conn:
                    remaining = conn.execute(
                        "SELECT COUNT(*) AS n FROM pending_orders WHERE package_id=? AND status='waiting'",
                        (package_id,)
                    ).fetchone()["n"]
                if remaining > 0:
                    send_or_edit(call,
                        f"ΓÜá∩╕Å <b>{remaining}</b> ╪│┘ü╪º╪▒╪┤ ╪»╪▒ ╪º┘å╪¬╪╕╪º╪▒ ┘ê╪¼┘ê╪» ╪»╪º╪▒╪» ┘ê┘ä█î ┘à┘ê╪¼┘ê╪»█î ┌⌐╪º┘ü█î ┘å█î╪│╪¬.\n\n"
                        "┘ä╪╖┘ü╪º┘ï ╪º╪¿╪¬╪»╪º ┌⌐╪º┘å┘ü█î┌» ╪½╪¿╪¬ ┌⌐┘å█î╪».",
                        back_button(f"adm:stk:pk:{package_id}"))
                else:
                    send_or_edit(call,
                        "Γ£à ┘ç█î┌å ╪│┘ü╪º╪▒╪┤ ╪»╪▒ ╪º┘å╪¬╪╕╪º╪▒█î ┘ê╪¼┘ê╪» ┘å╪»╪º╪▒╪».",
                        back_button(f"adm:stk:pk:{package_id}"))
        except Exception as e:
            send_or_edit(call,
                f"Γ¥î ╪«╪╖╪º ╪»╪▒ ╪¬╪¡┘ê█î┘ä ╪│┘ü╪º╪▒╪┤ΓÇî┘ç╪º:\n<code>{esc(str(e))}</code>",
                back_button(f"adm:stk:pk:{package_id}"))
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
                mark = "Γ¥î"
            elif c["sold_to"]:
                mark = "≡ƒö┤"
            else:
                mark = "≡ƒƒó"
            svc = urllib.parse.unquote(c["service_name"] or "")
            kb.add(types.InlineKeyboardButton(f"{mark} {svc}", callback_data=f"adm:stk:cfg:{c['id']}"))
        # Pagination
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton("Γ¼à∩╕Å ┘é╪¿┘ä", callback_data=f"adm:stk:{kind_str}:{package_id}:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton("╪¿╪╣╪» Γ₧í∩╕Å", callback_data=f"adm:stk:{kind_str}:{package_id}:{page+1}"))
        if nav_row:
            kb.row(*nav_row)
        # Bulk action buttons
        if kind_str in ("av", "sl"):
            kb.row(
                types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ┘ç┘à┌»╪º┘å█î",   callback_data=f"adm:stk:blk:{kind_str}:{package_id}"),
                types.InlineKeyboardButton("Γ¥î ┘à┘å┘é╪╢█î ┘ç┘à┌»╪º┘å█î", callback_data=f"adm:stk:blk:{kind_str}:{package_id}"),
            )
        else:
            kb.add(types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ┘ç┘à┌»╪º┘å█î", callback_data=f"adm:stk:blk:{kind_str}:{package_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:stk:pk:{package_id}"))
        bot.answer_callback_query(call.id)
        if kind_str == "sl":
            label_kind = "≡ƒö┤ ┘ü╪▒┘ê╪«╪¬┘ç ╪┤╪»┘ç"
        elif kind_str == "ex":
            label_kind = "Γ¥î ┘à┘å┘é╪╢█î ╪┤╪»┘ç"
        else:
            label_kind = "≡ƒƒó ┘à┘ê╪¼┘ê╪»"
        send_or_edit(call, f"≡ƒôï {label_kind} | ╪╡┘ü╪¡┘ç {page+1}/{total_pages} | ╪¬╪╣╪»╪º╪» ┌⌐┘ä: {total}", kb)
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
            bot.answer_callback_query(call.id, "█î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        text = (
            f"≡ƒö« ┘å╪º┘à ╪│╪▒┘ê█î╪│: <b>{esc(urllib.parse.unquote(row['service_name'] or ''))}</b>\n"
            f"≡ƒº⌐ ┘å┘ê╪╣ ╪│╪▒┘ê█î╪│: {esc(row['type_name'])}\n"
            f"≡ƒöï ╪¡╪¼┘à: {fmt_vol(row['volume_gb'])}\n"
            f"ΓÅ░ ┘à╪»╪¬: {fmt_dur(row['duration_days'])}\n\n"
            f"≡ƒÆ¥ Config:\n<code>{esc(row['config_text'])}</code>\n\n"
            f"≡ƒöï Subscription: {esc(row['inquiry_link'] or '-')}\n"
            f"≡ƒùô ╪½╪¿╪¬: {esc(row['created_at'])}"
        )
        kb = types.InlineKeyboardMarkup()
        if row["sold_to"]:
            buyer = get_user_detail(row["sold_to"])
            if buyer:
                text += (
                    f"\n\n≡ƒ¢Æ <b>╪«╪▒█î╪»╪º╪▒:</b>\n"
                    f"┘å╪º┘à: {esc(buyer['full_name'])}\n"
                    f"┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î: {esc(display_username(buyer['username']))}\n"
                    f"╪ó█î╪»█î: <code>{buyer['user_id']}</code>\n"
                    f"╪▓┘à╪º┘å ╪«╪▒█î╪»: {esc(row['sold_at'] or '-')}"
                )
        if not row["is_expired"]:
            kb.add(types.InlineKeyboardButton("Γ¥î ┘à┘å┘é╪╢█î ┌⌐╪▒╪»┘å", callback_data=f"adm:stk:exp:{config_id}:{row['package_id']}"))
        else:
            text += "\n\nΓÜá∩╕Å ╪º█î┘å ╪│╪▒┘ê█î╪│ ┘à┘å┘é╪╢█î ╪┤╪»┘ç ╪º╪│╪¬."
        kb.row(
            types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤", callback_data=f"adm:stk:edt:{config_id}"),
            types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ┌⌐╪º┘å┘ü█î┌»", callback_data=f"adm:stk:del:{config_id}:{row['package_id']}"),
        )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:stk:pk:{row['package_id']}"))
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
        # adm:stk:edt:{config_id}                 ΓåÆ edit menu
        # adm:stk:edt:pkg:{config_id}             ΓåÆ choose type for package edit
        # adm:stk:edt:pkgt:{config_id}:{type_id}  ΓåÆ choose package within type
        # adm:stk:edt:pkgp:{config_id}:{pkg_id}   ΓåÆ confirm package change
        # adm:stk:edt:svc:{config_id}             ΓåÆ edit service name
        # adm:stk:edt:cfg:{config_id}             ΓåÆ edit config text
        # adm:stk:edt:inq:{config_id}             ΓåÆ edit inquiry link

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
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:stk:edt:{config_id}"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "≡ƒº⌐ ┘å┘ê╪╣ ╪│╪▒┘ê█î╪│ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
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
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:stk:edt:pkg:{config_id}"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "≡ƒôª ┘╛┌⌐█î╪¼ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
            return

        if sub == "pkgp":
            config_id  = int(parts[4])
            package_id = int(parts[5])
            pkg = get_package(package_id)
            update_config_field(config_id, "package_id", package_id)
            if pkg:
                update_config_field(config_id, "type_id", pkg["type_id"])
            log_admin_action(uid, f"┘╛┌⌐█î╪¼ ┌⌐╪º┘å┘ü█î┌» #{config_id} ╪¿┘ç #{package_id} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
            bot.answer_callback_query(call.id, "Γ£à ┘╛┌⌐█î╪¼ ╪¬╪║█î█î╪▒ ┌⌐╪▒╪».")
            _fake_call(call, f"adm:stk:cfg:{config_id}")
            return

        if sub == "svc":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_svc", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, "Γ£Å∩╕Å ┘å╪º┘à ╪│╪▒┘ê█î╪│ ╪¼╪»█î╪» ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button(f"adm:stk:edt:{config_id}"))
            return

        if sub == "cfg":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_text", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, "≡ƒÆ¥ ┘à╪¬┘å ┌⌐╪º┘å┘ü█î┌» ╪¼╪»█î╪» ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button(f"adm:stk:edt:{config_id}"))
            return

        if sub == "inq":
            config_id = int(parts[4])
            state_set(uid, "admin_cfg_edit_inq", config_id=config_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                "≡ƒöù ┘ä█î┘å┌⌐ ╪º╪│╪¬╪╣┘ä╪º┘à ╪¼╪»█î╪» ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n"
                "╪¿╪▒╪º█î ╪¡╪░┘ü ┘ä█î┘å┌⌐╪î <code>-</code> ╪¿┘ü╪▒╪│╪¬█î╪».",
                back_button(f"adm:stk:edt:{config_id}"))
            return

        # Default: show edit menu
        config_id = int(sub)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒôª ┘ê█î╪▒╪º█î╪┤ ┘╛┌⌐█î╪¼",         callback_data=f"adm:stk:edt:pkg:{config_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒö« ┘ê█î╪▒╪º█î╪┤ ┘å╪º┘à ╪│╪▒┘ê█î╪│",    callback_data=f"adm:stk:edt:svc:{config_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒÆ¥ ┘ê█î╪▒╪º█î╪┤ ┘à╪¬┘å ┌⌐╪º┘å┘ü█î┌»",   callback_data=f"adm:stk:edt:cfg:{config_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöù ┘ê█î╪▒╪º█î╪┤ ┘ä█î┘å┌⌐ ╪º╪│╪¬╪╣┘ä╪º┘à", callback_data=f"adm:stk:edt:inq:{config_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬",               callback_data=f"adm:stk:cfg:{config_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ┌⌐╪º┘å┘ü█î┌»</b>\n\n┌å┘ç ┌å█î╪▓█î ╪▒╪º ┘ê█î╪▒╪º█î╪┤ ┘à█îΓÇî┌⌐┘å█î╪»╪ƒ", kb)
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
                    "ΓÜá∩╕Å █î┌⌐█î ╪º╪▓ ╪│╪▒┘ê█î╪│ΓÇî┘ç╪º█î ╪┤┘à╪º ╪¬┘ê╪│╪╖ ╪º╪»┘à█î┘å ┘à┘å┘é╪╢█î ╪º╪╣┘ä╪º┘à ╪┤╪»┘ç ╪º╪│╪¬.\n╪¿╪▒╪º█î ╪¬┘à╪»█î╪» ╪¿╪º ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪¬┘à╪º╪│ ╪¿┌»█î╪▒█î╪»."
                )
            except Exception:
                pass
        bot.answer_callback_query(call.id, "╪│╪▒┘ê█î╪│ ┘à┘å┘é╪╢█î ╪┤╪».")
        back = back_button(f"adm:stk:pk:{package_id}") if package_id else back_button("admin:stock")
        send_or_edit(call, "Γ£à ╪│╪▒┘ê█î╪│ ┘à┘å┘é╪╢█î ╪º╪╣┘ä╪º┘à ╪┤╪».", back)
        return

    if data.startswith("adm:stk:del:"):
        parts = data.split(":")
        config_id  = int(parts[3])
        package_id = int(parts[4]) if len(parts) > 4 else 0
        with get_conn() as conn:
            conn.execute("DELETE FROM configs WHERE id=?", (config_id,))
        bot.answer_callback_query(call.id, "┌⌐╪º┘å┘ü█î┌» ╪¡╪░┘ü ╪┤╪».")
        back = back_button(f"adm:stk:pk:{package_id}") if package_id else back_button("admin:stock")
        send_or_edit(call, "Γ£à ┌⌐╪º┘å┘ü█î┌» ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪¡╪░┘ü ╪┤╪».", back)
        return

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö All packages entry (must be before blk: check) ΓöÇΓöÇ
    if data.startswith("adm:stk:blkA:"):
        kind = data.split(":")[3]  # av / sl / ex
        if not (admin_has_perm(uid, "manage_configs") or uid in ADMIN_IDS):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "stk_bulk", kind=kind, scope="all", pkg_id=0, page=0, selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Per-package entry ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("adm:stk:blk:"):
        parts  = data.split(":")
        kind   = parts[3]         # av / sl / ex
        pkg_id = int(parts[4])    # package_id
        if not (admin_has_perm(uid, "manage_configs") or uid in ADMIN_IDS):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "stk_bulk", kind=kind, scope="pk", pkg_id=pkg_id, page=0, selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Toggle individual config ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
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

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Select all on current page ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
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

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Deselect current page ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
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

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Clear all selections ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:stk:bclrall":
        sd = state_data(uid)
        state_set(uid, "stk_bulk",
                  kind=sd.get("kind", "av"), scope=sd.get("scope", "pk"),
                  pkg_id=sd.get("pkg_id", 0), page=sd.get("page", 0),
                  selected="")
        bot.answer_callback_query(call.id)
        _render_bulk_page(call, uid)
        return

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Navigate pages ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
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

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Execute delete ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:stk:bdel":
        sd      = state_data(uid)
        sel_raw = sd.get("selected", "")
        ids     = [int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit()]
        if not ids:
            bot.answer_callback_query(call.id, "ΓÜá∩╕Å ┘ç█î┌å ┘à┘ê╪▒╪»█î ╪º┘å╪¬╪«╪º╪¿ ┘å╪┤╪»┘ç.", show_alert=True)
            return
        with get_conn() as conn:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM configs WHERE id IN ({placeholders})", ids)
        state_clear(uid)
        bot.answer_callback_query(call.id, f"Γ£à {len(ids)} ┌⌐╪º┘å┘ü█î┌» ╪¡╪░┘ü ╪┤╪».", show_alert=True)
        send_or_edit(call, f"Γ£à <b>{len(ids)}</b> ┌⌐╪º┘å┘ü█î┌» ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪¡╪░┘ü ╪┤╪».", back_button("admin:stock"))
        return

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Execute expire ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:stk:bexp":
        sd      = state_data(uid)
        sel_raw = sd.get("selected", "")
        ids     = [int(x) for x in sel_raw.split(",") if x.strip().lstrip("-").isdigit()]
        if not ids:
            bot.answer_callback_query(call.id, "ΓÜá∩╕Å ┘ç█î┌å ┘à┘ê╪▒╪»█î ╪º┘å╪¬╪«╪º╪¿ ┘å╪┤╪»┘ç.", show_alert=True)
            return
        with get_conn() as conn:
            for cfg_id in ids:
                conn.execute("UPDATE configs SET is_expired=1 WHERE id=?", (cfg_id,))
        state_clear(uid)
        bot.answer_callback_query(call.id, f"Γ£à {len(ids)} ┌⌐╪º┘å┘ü█î┌» ┘à┘å┘é╪╢█î ╪┤╪».", show_alert=True)
        send_or_edit(call, f"Γ£à <b>{len(ids)}</b> ┌⌐╪º┘å┘ü█î┌» ┘à┘å┘é╪╢█î ╪º╪╣┘ä╪º┘à ╪┤╪».", back_button("admin:stock"))
        return

    # ΓöÇΓöÇ Admin: Bulk select ΓÇö Cancel / back ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
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

    # ΓöÇΓöÇ Admin: Stock Search ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:stk:search":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöù ┘ä█î┘å┌⌐ ╪º╪│╪¬╪╣┘ä╪º┘à", callback_data="adm:stk:srch:link"))
        kb.add(types.InlineKeyboardButton("≡ƒÆ¥ ┘à╪¬┘å ┌⌐╪º┘å┘ü█î┌»", callback_data="adm:stk:srch:cfg"))
        kb.add(types.InlineKeyboardButton("≡ƒö« ┘å╪º┘à ╪│╪▒┘ê█î╪│", callback_data="adm:stk:srch:name"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:stock"))
        send_or_edit(call, "≡ƒöì ╪¼╪│╪¬╪¼┘ê ╪¿╪▒ ╪º╪│╪º╪│:", kb)
        bot.answer_callback_query(call.id)
        return

    if data == "adm:stk:srch:link":
        state_set(call.from_user.id, "admin_search_by_link")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒöù ┘ä█î┘å┌⌐ ╪º╪│╪¬╪╣┘ä╪º┘à (█î╪º ╪¿╪«╪┤█î ╪º╪▓ ╪ó┘å) ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:stk:search"))
        return

    if data == "adm:stk:srch:cfg":
        state_set(call.from_user.id, "admin_search_by_config")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÆ¥ ┘à╪¬┘å ┌⌐╪º┘å┘ü█î┌» (█î╪º ╪¿╪«╪┤█î ╪º╪▓ ╪ó┘å) ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:stk:search"))
        return

    if data == "adm:stk:srch:name":
        state_set(call.from_user.id, "admin_search_by_name")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒö« ┘å╪º┘à ╪│╪▒┘ê█î╪│ (█î╪º ╪¿╪«╪┤█î ╪º╪▓ ╪ó┘å) ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:stk:search"))
        return

    # ΓöÇΓöÇ Admin: Users ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:users":
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        _show_admin_users_list(call)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("admin:users:pg:"):
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        page = int(data.split(":")[-1])
        _show_admin_users_list(call, page=page)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("adm:usr:fl:"):
        if not (admin_has_perm(uid, "view_users") or admin_has_perm(uid, "full_users") or
                any(admin_has_perm(uid, p) for p in PERM_USER_FULL)):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        parts       = data.split(":")
        filter_mode = parts[3]
        page        = int(parts[4]) if len(parts) > 4 else 0
        _show_admin_users_list(call, page=page, filter_mode=filter_mode)
        bot.answer_callback_query(call.id)
        return

    # ΓöÇΓöÇ Admin: User search ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:usr:search":
        state_set(uid, "admin_user_search")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöì <b>╪¼╪│╪¬╪¼┘ê█î ┌⌐╪º╪▒╪¿╪▒</b>\n\n"
            "┘à█îΓÇî╪¬┘ê╪º┘å█î╪» ╪¿╪▒ ╪º╪│╪º╪│ ┘à┘ê╪º╪▒╪» ╪▓█î╪▒ ╪¼╪│╪¬╪¼┘ê ┌⌐┘å█î╪»:\n"
            "ΓÇó <b>╪ó█î╪»█î ╪╣╪»╪»█î</b> (┘à╪½╪º┘ä: <code>123456789</code>)\n"
            "ΓÇó <b>┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î</b> (┘à╪½╪º┘ä: <code>@username</code>)\n"
            "ΓÇó <b>┘å╪º┘à ╪º┌⌐╪º┘å╪¬</b> (┘à╪½╪º┘ä: <code>╪╣┘ä█î</code>)\n\n"
            "┘à┘é╪»╪º╪▒ ╪¼╪│╪¬╪¼┘ê ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:",
            back_button("admin:users"))
        return

    # ΓöÇΓöÇ Admin: Admins management ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:admins":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "┘ü┘é╪╖ ╪º┘ê┘å╪▒ ┘à█îΓÇî╪¬┘ê╪º┘å╪» ╪º╪»┘à█î┘åΓÇî┘ç╪º ╪▒╪º ┘à╪»█î╪▒█î╪¬ ┌⌐┘å╪».", show_alert=True)
            return
        _show_admin_admins_panel(call)
        bot.answer_callback_query(call.id)
        return

    if data == "adm:mgr:add":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_mgr_await_id")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "Γ₧ò <b>╪º┘ü╪▓┘ê╪»┘å ╪º╪»┘à█î┘å ╪¼╪»█î╪»</b>\n\n"
            "╪ó█î╪»█î ╪╣╪»╪»█î █î╪º █î┘ê╪▓╪▒┘å█î┘à ┌⌐╪º╪▒╪¿╪▒ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:\n\n"
            "┘à╪½╪º┘ä: <code>123456789</code> █î╪º <code>@username</code>",
            back_button("admin:admins"))
        return

    if data.startswith("adm:mgr:del:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        if target_id in ADMIN_IDS:
            bot.answer_callback_query(call.id, "╪º┘ê┘å╪▒┘ç╪º ╪▒╪º ┘å┘à█îΓÇî╪¬┘ê╪º┘å ╪¡╪░┘ü ┌⌐╪▒╪».", show_alert=True)
            return
        remove_admin_user(target_id)
        bot.answer_callback_query(call.id, "Γ£à ╪º╪»┘à█î┘å ╪¡╪░┘ü ╪┤╪».")
        log_admin_action(uid, f"╪º╪»┘à█î┘å <code>{target_id}</code> ╪¡╪░┘ü ╪┤╪»")
        _show_admin_admins_panel(call)
        return

    if data.startswith("adm:mgr:v:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        row = get_admin_user(target_id)
        user_row = get_user(target_id)
        if not row:
            bot.answer_callback_query(call.id, "╪º╪»┘à█î┘å █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        perms = json.loads(row["permissions"] or "{}")
        perm_lines = "\n".join(
            f"{'Γ£à' if perms.get(k) or perms.get('full') else 'ΓÿÉ'} {lbl}"
            for k, lbl in ADMIN_PERMS if k != "full"
        )
        name = user_row["full_name"] if user_row else f"┌⌐╪º╪▒╪¿╪▒ {target_id}"
        text = (
            f"≡ƒæ« <b>╪º╪╖┘ä╪º╪╣╪º╪¬ ╪º╪»┘à█î┘å</b>\n\n"
            f"≡ƒæñ ┘å╪º┘à: {esc(name)}\n"
            f"≡ƒåö ╪ó█î╪»█î: <code>{target_id}</code>\n"
            f"≡ƒôà ╪º┘ü╪▓┘ê╪»┘ç ╪┤╪»┘ç: {esc(row['added_at'])}\n\n"
            f"≡ƒöæ <b>╪»╪│╪¬╪▒╪│█îΓÇî┘ç╪º:</b>\n{perm_lines}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ╪º╪»┘à█î┘å", callback_data=f"adm:mgr:del:{target_id}"))
        kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤ ╪»╪│╪¬╪▒╪│█îΓÇî┘ç╪º", callback_data=f"adm:mgr:edit:{target_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:admins"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:mgr:edit:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        target_id = int(data.split(":")[3])
        row = get_admin_user(target_id)
        if not row:
            bot.answer_callback_query(call.id, "╪º╪»┘à█î┘å █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        perms = json.loads(row["permissions"] or "{}")
        state_set(uid, "admin_mgr_select_perms", target_user_id=target_id, perms=json.dumps(perms), edit_mode=True)
        bot.answer_callback_query(call.id)
        _show_perm_selection(call, uid, target_id, perms, edit_mode=True)
        return

    if data.startswith("adm:mgr:pt:"):
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        perm_key = data[len("adm:mgr:pt:"):]
        sd2 = state_data(uid)
        if state_name(uid) != "admin_mgr_select_perms" or not sd2:
            bot.answer_callback_query(call.id, "╪¼┘ä╪│┘ç ┘à┘å┘é╪╢█î ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
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
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        sd2 = state_data(uid)
        if state_name(uid) != "admin_mgr_select_perms" or not sd2:
            bot.answer_callback_query(call.id, "╪¼┘ä╪│┘ç ┘à┘å┘é╪╢█î ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        target_id = sd2.get("target_user_id")
        perms = json.loads(sd2.get("perms", "{}"))
        if not any(perms.values()):
            bot.answer_callback_query(call.id, "╪¡╪»╪º┘é┘ä █î┌⌐ ╪│╪╖╪¡ ╪»╪│╪¬╪▒╪│█î ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪».", show_alert=True)
            return
        edit_mode = sd2.get("edit_mode", False)
        # Build human-readable permission list for notification
        perms_labels = {k: v for k, v in ADMIN_PERMS}
        active_perm_names = [perms_labels.get(k, k) for k, v in perms.items() if v]
        perm_text = "\n".join(f"ΓÇó {p}" for p in active_perm_names) or "ΓÇö ╪¿╪»┘ê┘å ╪»╪│╪¬╪▒╪│█î ΓÇö"
        if edit_mode:
            update_admin_permissions(target_id, perms)
            log_admin_action(uid, f"╪»╪│╪¬╪▒╪│█îΓÇî┘ç╪º█î ╪º╪»┘à█î┘å {target_id} ╪¿┘çΓÇî╪▒┘ê╪▓╪▒╪│╪º┘å█î ╪┤╪»")
            state_clear(uid)
            bot.answer_callback_query(call.id, "Γ£à ╪»╪│╪¬╪▒╪│█îΓÇî┘ç╪º ╪¿┘çΓÇî╪▒┘ê╪▓ ╪┤╪».")
            try:
                bot.send_message(target_id,
                    "≡ƒöæ <b>╪»╪│╪¬╪▒╪│█îΓÇî┘ç╪º█î ╪┤┘à╪º ╪¿┘çΓÇî╪▒┘ê╪▓╪▒╪│╪º┘å█î ╪┤╪»</b>\n\n"
                    f"<b>╪»╪│╪¬╪▒╪│█îΓÇî┘ç╪º█î ┘ü╪╣╪º┘ä:</b>\n{perm_text}\n\n"
                    "╪¿╪▒╪º█î ╪º╪│╪¬┘ü╪º╪»┘ç ╪º╪▓ ╪»╪│╪¬╪▒╪│█îΓÇî┘ç╪º█î ╪¼╪»█î╪» ╪º╪▓ /start ╪º╪│╪¬┘ü╪º╪»┘ç ┌⌐┘å█î╪».")
            except Exception:
                pass
        else:
            add_admin_user(target_id, uid, perms)
            log_admin_action(uid, f"╪º╪»┘à█î┘å ╪¼╪»█î╪» {target_id} ╪º╪╢╪º┘ü┘ç ╪┤╪»")
            state_clear(uid)
            bot.answer_callback_query(call.id, "Γ£à ╪º╪»┘à█î┘å ╪º╪╢╪º┘ü┘ç ╪┤╪».")
            try:
                bot.send_message(target_id,
                    "≡ƒæ« <b>╪┤┘à╪º ╪¿┘ç ╪╣┘å┘ê╪º┘å ╪º╪»┘à█î┘å ╪º╪╢╪º┘ü┘ç ╪┤╪»█î╪»!</b>\n\n"
                    f"<b>╪»╪│╪¬╪▒╪│█îΓÇî┘ç╪º█î ╪┤┘à╪º:</b>\n{perm_text}\n\n"
                    "╪¿╪▒╪º█î ╪»╪│╪¬╪▒╪│█î ╪¿┘ç ┘╛┘å┘ä ┘à╪»█î╪▒█î╪¬ ╪º╪▓ ╪»╪│╪¬┘ê╪▒ /start ╪º╪│╪¬┘ü╪º╪»┘ç ┌⌐┘å█î╪».")
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

        if sub == "sts":  # cycle status: safe ΓåÆ unsafe ΓåÆ restricted ΓåÆ safe
            user = get_user(target_id)
            current = user["status"] if user else "safe"
            if current == "safe":
                new_status = "unsafe"
                label = "┘å╪º╪º┘à┘å"
            elif current == "unsafe":
                new_status = "restricted"
                label = "┘à╪¡╪»┘ê╪»"
            else:
                new_status = "safe"
                label = "╪º┘à┘å"
            set_user_status(target_id, new_status)
            bot.answer_callback_query(call.id, f"┘ê╪╢╪╣█î╪¬ ┌⌐╪º╪▒╪¿╪▒ ╪¿┘ç {label} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪».")
            log_admin_action(uid, f"┘ê╪╢╪╣█î╪¬ ┌⌐╪º╪▒╪¿╪▒ <code>{target_id}</code> ╪¿┘ç {label} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
            _show_admin_user_detail(call, target_id)
            return

        if sub == "ag":  # toggle agent
            user     = get_user(target_id)
            new_flag = 0 if user["is_agent"] else 1
            set_user_agent(target_id, new_flag)
            label = "┘ü╪╣╪º┘ä" if new_flag else "╪║█î╪▒┘ü╪╣╪º┘ä"
            bot.answer_callback_query(call.id, f"┘å┘à╪º█î┘å╪»┌»█î {label} ╪┤╪».")
            log_admin_action(uid, f"┘å┘à╪º█î┘å╪»┌»█î ┌⌐╪º╪▒╪¿╪▒ <code>{target_id}</code> {label} ╪┤╪»")
            _show_admin_user_detail(call, target_id)
            return

        if sub == "bal":  # balance menu
            user = get_user(target_id)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("Γ₧ò ╪º┘ü╪▓╪º█î╪┤", callback_data=f"adm:usr:bal+:{target_id}"),
                types.InlineKeyboardButton("Γ₧û ┌⌐╪º┘ç╪┤",  callback_data=f"adm:usr:bal-:{target_id}"),
            )
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:usr:v:{target_id}"))
            bot.answer_callback_query(call.id)
            send_or_edit(call,
                f"≡ƒÆ░ <b>┘à┘ê╪¼┘ê╪»█î ┌⌐╪º╪▒╪¿╪▒</b>\n\n"
                f"≡ƒÆ░ ┘à┘ê╪¼┘ê╪»█î ┘ü╪╣┘ä█î: <b>{fmt_price(user['balance'])}</b> ╪¬┘ê┘à╪º┘å",
                kb)
            return

        if sub == "bal+":  # add balance
            state_set(uid, "admin_bal_add", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"≡ƒÆ░ ┘à╪¿┘ä╪║█î ┌⌐┘ç ┘à█îΓÇî╪«┘ê╪º┘ç█î╪» <b>╪º╪╢╪º┘ü┘ç</b> ╪┤┘ê╪» ╪▒╪º ╪¿┘ç ╪¬┘ê┘à╪º┘å ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
                         back_button(f"adm:usr:v:{target_id}"))
            return

        if sub == "bal-":  # reduce balance
            state_set(uid, "admin_bal_sub", target_user_id=target_id)
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"≡ƒÆ░ ┘à╪¿┘ä╪║█î ┌⌐┘ç ┘à█îΓÇî╪«┘ê╪º┘ç█î╪» <b>┌⌐╪º┘ç╪┤</b> █î╪º╪¿╪» ╪▒╪º ╪¿┘ç ╪¬┘ê┘à╪º┘å ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
                         back_button(f"adm:usr:v:{target_id}"))
            return

        if sub == "cfgs":  # user configs
            purchases = get_user_purchases(target_id)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("Γ₧ò ╪º┘ü╪▓┘ê╪»┘å ┌⌐╪º┘å┘ü█î┌»", callback_data=f"adm:usr:acfg:{target_id}"))
            if purchases:
                for p in purchases:
                    expired_mark = " Γ¥î" if p["is_expired"] else ""
                    svc = urllib.parse.unquote(p["service_name"] or "")
                    kb.add(types.InlineKeyboardButton(
                        f"{svc}{expired_mark}",
                        callback_data=f"adm:usrcfg:{target_id}:{p['config_id']}"
                    ))
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:usr:v:{target_id}"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, f"≡ƒôª ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º█î ┌⌐╪º╪▒╪¿╪▒:", kb)
            return

        if sub == "acfg":  # assign config to user
            _show_admin_assign_config_type(call, target_id)
            bot.answer_callback_query(call.id)
            return

        if sub == "agp":  # agency prices list
            packs = get_packages()
            if not packs:
                bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼█î ┘à┘ê╪¼┘ê╪» ┘å█î╪│╪¬.", show_alert=True)
                return
            kb = types.InlineKeyboardMarkup()
            for p in packs:
                ap    = get_agency_price(target_id, p["id"])
                price = fmt_price(ap) if ap is not None else fmt_price(p["price"])
                label = f"{p['name']} | {price} ╪¬"
                kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:usr:agpe:{target_id}:{p['id']}"))
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:usr:v:{target_id}"))
            bot.answer_callback_query(call.id)
            send_or_edit(call, "≡ƒÅ╖ <b>┘é█î┘à╪¬ΓÇî┘ç╪º█î ╪º╪«╪¬╪╡╪º╪╡█î ┘å┘à╪º█î┘å╪»┌»█î</b>\n\n╪¿╪▒╪º█î ┘ê█î╪▒╪º█î╪┤ ╪▒┘ê█î ┘╛┌⌐█î╪¼ ╪¿╪▓┘å█î╪»:", kb)
            return

    if data.startswith("adm:usr:agpe:"):
        parts      = data.split(":")
        target_id  = int(parts[3])
        package_id = int(parts[4])
        state_set(uid, "admin_set_agency_price", target_user_id=target_id, package_id=package_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÆ░ ┘é█î┘à╪¬ ╪º╪«╪¬╪╡╪º╪╡█î (╪¬┘ê┘à╪º┘å) ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».\n╪¿╪▒╪º█î ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘é█î┘à╪¬ ╪╣╪º╪»█î╪î ╪╣╪»╪» <b>0</b> ╪¿┘ü╪▒╪│╪¬█î╪»:",
                     back_button(f"adm:usr:v:{target_id}"))
        return

    # Admin user config detail (with unassign/delete)
    if data.startswith("adm:usrcfg:unassign:"):
        parts     = data.split(":")
        target_id = int(parts[3])
        config_id = int(parts[4])
        with get_conn() as conn:
            # Reset config to available
            conn.execute("UPDATE configs SET sold_to=NULL, purchase_id=NULL, sold_at=NULL, reserved_payment_id=NULL, is_expired=0 WHERE id=?", (config_id,))
            # Delete the purchase record
            conn.execute("DELETE FROM purchases WHERE config_id=? AND user_id=?", (config_id, target_id))
        bot.answer_callback_query(call.id, "┌⌐╪º┘å┘ü█î┌» ╪º╪▓ ┌⌐╪º╪▒╪¿╪▒ ╪¡╪░┘ü ╪┤╪».")
        send_or_edit(call, "Γ£à ┌⌐╪º┘å┘ü█î┌» ╪º╪▓ ┌⌐╪º╪▒╪¿╪▒ ╪¡╪░┘ü ┘ê ╪¿┘ç ┘à╪º┘å╪»┘çΓÇî┘ç╪º ╪¿╪▒┌»╪┤╪¬.", back_button(f"adm:usr:v:{target_id}"))
        return

    if data.startswith("adm:usrcfg:"):
        parts     = data.split(":")
        target_id = int(parts[2])
        config_id = int(parts[3])
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM configs WHERE id=?", (config_id,)).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "█î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        text = (
            f"≡ƒö« ┘å╪º┘à ╪│╪▒┘ê█î╪│: <b>{esc(urllib.parse.unquote(row['service_name'] or ''))}</b>\n\n"
            f"≡ƒÆ¥ Config:\n<code>{esc(row['config_text'])}</code>\n\n"
            f"≡ƒöï Volume web: {esc(row['inquiry_link'] or '-')}\n"
            f"≡ƒùô ╪½╪¿╪¬: {esc(row['created_at'])}\n"
            f"≡ƒùô ┘ü╪▒┘ê╪┤: {esc(row['sold_at'] or '-')}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöä ╪¡╪░┘ü ╪º╪▓ ┌⌐╪º╪▒╪¿╪▒ (╪¿╪▒┌»╪┤╪¬ ╪¿┘ç ┘à╪º┘å╪»┘çΓÇî┘ç╪º)", callback_data=f"adm:usrcfg:unassign:{target_id}:{config_id}"))
        if not row["is_expired"]:
            kb.add(types.InlineKeyboardButton("≡ƒö┤ ┘à┘å┘é╪╢█î ┌⌐╪▒╪»┘å", callback_data=f"adm:stk:exp:{config_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:usr:cfgs:{target_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
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
                    f"{p['name']} | ┘à┘ê╪¼┘ê╪»: {avail}",
                    callback_data=f"adm:acfg:p:{target_id}:{p['id']}"
                ))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:usr:v:{target_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôª ┘╛┌⌐█î╪¼ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
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
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:usr:v:{target_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒöº ┌⌐╪º┘å┘ü█î┌» ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("adm:acfg:do:"):  # do assign config
        parts      = data.split(":")
        target_id  = int(parts[3])
        config_id  = int(parts[4])
        with get_conn() as conn:
            cfg_row = conn.execute("SELECT * FROM configs WHERE id=?", (config_id,)).fetchone()
        if not cfg_row:
            bot.answer_callback_query(call.id, "┌⌐╪º┘å┘ü█î┌» █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        purchase_id = assign_config_to_user(config_id, target_id, cfg_row["package_id"], 0, "admin_gift", is_test=0)
        bot.answer_callback_query(call.id, "┌⌐╪º┘å┘ü█î┌» ┘à┘å╪¬┘é┘ä ╪┤╪»!")
        send_or_edit(call, "Γ£à ┌⌐╪º┘å┘ü█î┌» ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒ ╪º╪«╪¬╪╡╪º╪╡ █î╪º┘ü╪¬.", back_button("admin:users"))
        try:
            deliver_purchase_message(target_id, purchase_id)
        except Exception:
            pass
        return

    # ΓöÇΓöÇ Admin: Agents management ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:agents":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        agents    = get_agencies()
        req_flag  = setting_get("agency_request_enabled", "1")
        req_icon  = "≡ƒƒó" if req_flag == "1" else "≡ƒö┤"
        req_label = "╪▒┘ê╪┤┘å" if req_flag == "1" else "╪«╪º┘à┘ê╪┤"
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} ╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ΓÇö {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("Γ₧ò ╪º╪╢╪º┘ü┘ç ┌⌐╪▒╪»┘å ┘å┘à╪º█î┘å╪»┘ç", callback_data="adm:agt:add"))
        # Inline list: each agent on one row with remove button
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"≡ƒñ¥ {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "≡ƒùæ ╪¡╪░┘ü",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:panel"))
        send_or_edit(call,
            f"≡ƒñ¥ <b>┘à╪»█î╪▒█î╪¬ ┘å┘à╪º█î┘å╪»┌»╪º┘å</b>\n\n"
            f"≡ƒæÑ ╪¬╪╣╪»╪º╪» ┘å┘à╪º█î┘å╪»┌»╪º┘å ┘ü╪╣┘ä█î: <b>{len(agents)}</b>\n"
            f"≡ƒô¿ ┘ê╪╢╪╣█î╪¬ ╪»╪▒╪«┘ê╪º╪│╪¬: <b>{req_label}</b>",
            kb)
        return

    if data == "adm:agt:add":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_agent_add_search")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöì <b>╪¼╪│╪¬╪¼┘ê█î ┌⌐╪º╪▒╪¿╪▒ ╪¿╪▒╪º█î ╪º┘ü╪▓┘ê╪»┘å ╪¿┘ç ┘å┘à╪º█î┘å╪»┌»█î</b>\n\n"
            "╪ó█î╪»█î ╪╣╪»╪»█î █î╪º █î┘ê╪▓╪▒┘å█î┘à ┌⌐╪º╪▒╪¿╪▒ ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:",
            back_button("admin:agents"))
        return

    if data.startswith("adm:agt:u:"):
        target_uid = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _show_admin_user_detail(call, target_uid)
        return

    if data.startswith("adm:agt:rm:"):
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        target_uid = int(data.split(":")[3])
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_agent=0 WHERE user_id=?", (target_uid,))
        bot.answer_callback_query(call.id, "Γ£à ┌⌐╪º╪▒╪¿╪▒ ╪º╪▓ ┘å┘à╪º█î┘å╪»┌»█î ╪¡╪░┘ü ╪┤╪».")
        # re-render agents menu
        agents    = get_agencies()
        req_flag  = setting_get("agency_request_enabled", "1")
        req_icon  = "≡ƒƒó" if req_flag == "1" else "≡ƒö┤"
        req_label = "╪▒┘ê╪┤┘å" if req_flag == "1" else "╪«╪º┘à┘ê╪┤"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} ╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ΓÇö {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("Γ₧ò ╪º╪╢╪º┘ü┘ç ┌⌐╪▒╪»┘å ┘å┘à╪º█î┘å╪»┘ç", callback_data="adm:agt:add"))
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"≡ƒñ¥ {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "≡ƒùæ ╪¡╪░┘ü",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:panel"))
        send_or_edit(call,
            f"≡ƒñ¥ <b>┘à╪»█î╪▒█î╪¬ ┘å┘à╪º█î┘å╪»┌»╪º┘å</b>\n\n"
            f"≡ƒæÑ ╪¬╪╣╪»╪º╪» ┘å┘à╪º█î┘å╪»┌»╪º┘å ┘ü╪╣┘ä█î: <b>{len(agents)}</b>\n"
            f"≡ƒô¿ ┘ê╪╢╪╣█î╪¬ ╪»╪▒╪«┘ê╪º╪│╪¬: <b>{req_label}</b>",
            kb)
        return

    if data == "adm:agt:toggle":
        if not admin_has_perm(uid, "agency"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur      = setting_get("agency_request_enabled", "1")
        new      = "0" if cur == "1" else "1"
        setting_set("agency_request_enabled", new)
        log_admin_action(uid, f"╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î {'┘ü╪╣╪º┘ä' if new == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        req_icon  = "≡ƒƒó" if new == "1" else "≡ƒö┤"
        req_label = "╪▒┘ê╪┤┘å" if new == "1" else "╪«╪º┘à┘ê╪┤"
        bot.answer_callback_query(call.id, f"╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î: {req_label}")
        agents = get_agencies()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{req_icon} ╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ΓÇö {req_label}",
            callback_data="adm:agt:toggle"))
        kb.add(types.InlineKeyboardButton("Γ₧ò ╪º╪╢╪º┘ü┘ç ┌⌐╪▒╪»┘å ┘å┘à╪º█î┘å╪»┘ç", callback_data="adm:agt:add"))
        for ag in agents:
            name = esc(ag["full_name"]) if ag["full_name"] else str(ag["user_id"])
            kb.row(
                types.InlineKeyboardButton(
                    f"≡ƒñ¥ {name}",
                    callback_data=f"adm:agt:u:{ag['user_id']}"),
                types.InlineKeyboardButton(
                    "≡ƒùæ ╪¡╪░┘ü",
                    callback_data=f"adm:agt:rm:{ag['user_id']}")
            )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:panel"))
        send_or_edit(call,
            f"≡ƒñ¥ <b>┘à╪»█î╪▒█î╪¬ ┘å┘à╪º█î┘å╪»┌»╪º┘å</b>\n\n"
            f"≡ƒæÑ ╪¬╪╣╪»╪º╪» ┘å┘à╪º█î┘å╪»┌»╪º┘å ┘ü╪╣┘ä█î: <b>{len(agents)}</b>\n"
            f"≡ƒô¿ ┘ê╪╢╪╣█î╪¬ ╪»╪▒╪«┘ê╪º╪│╪¬: <b>{req_label}</b>",
            kb)
        return

    # ΓöÇΓöÇ Agency price config (3-mode) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("adm:agcfg:") and data.count(":") == 2:
        # adm:agcfg:{target_id}  ΓÇö show mode selector
        parts     = data.split(":")
        target_id = int(parts[2])
        if not admin_has_perm(uid, "agency") and not admin_has_perm(uid, "full_users"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cfg  = get_agency_price_config(target_id)
        mode = cfg["price_mode"]
        tick = {m: "Γ£à " for m in ["global", "type", "package"]}
        for k in tick:
            tick[k] = "Γ£à " if mode == k else ""
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{tick['global']}≡ƒîì ╪¬╪«┘ü█î┘ü ╪▒┘ê█î ┌⌐┘ä ┘à╪¡╪╡┘ê┘ä╪º╪¬",
            callback_data=f"adm:agcfg:global:{target_id}"))
        kb.add(types.InlineKeyboardButton(
            f"{tick['type']}≡ƒº⌐ ╪¬╪«┘ü█î┘ü ╪▒┘ê█î ┘ç╪▒ ╪»╪│╪¬┘ç",
            callback_data=f"adm:agcfg:type:{target_id}"))
        kb.add(types.InlineKeyboardButton(
            f"{tick['package']}≡ƒôª ┘é█î┘à╪¬ ╪¼╪»╪º┌»╪º┘å┘ç ┘ç╪▒ ┘╛┌⌐█î╪¼",
            callback_data=f"adm:agcfg:pkg:{target_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:usr:v:{target_id}"))
        bot.answer_callback_query(call.id)
        target_user = get_user(target_id)
        uname = esc(target_user["full_name"]) if target_user else str(target_id)
        mode_labels = {"global": "≡ƒîì ╪¬╪«┘ü█î┘ü ┌⌐┘ä ┘à╪¡╪╡┘ê┘ä╪º╪¬", "type": "≡ƒº⌐ ╪¬╪«┘ü█î┘ü ┘ç╪▒ ╪»╪│╪¬┘ç", "package": "≡ƒôª ┘é█î┘à╪¬ ┘ç╪▒ ┘╛┌⌐█î╪¼"}
        send_or_edit(call,
            f"≡ƒÆ░ <b>┘é█î┘à╪¬ ┘å┘à╪º█î┘å╪»┌»█î ┌⌐╪º╪▒╪¿╪▒</b>\n"
            f"≡ƒæñ {uname}\n\n"
            f"╪¡╪º┘ä╪¬ ┘ü╪╣┘ä█î: <b>{mode_labels.get(mode, mode)}</b>\n\n"
            "╪¡╪º┘ä╪¬ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("adm:agcfg:global:") and data.count(":") == 3:
        # adm:agcfg:global:{target_id}  ΓÇö choose pct or toman
        target_id = int(data.split(":")[3])
        cfg = get_agency_price_config(target_id)
        g_type = cfg["global_type"]
        g_val  = cfg["global_val"]
        cur_label = f"{'╪»╪▒╪╡╪»' if g_type == 'pct' else '╪¬┘ê┘à╪º┘å'} ΓÇö ┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: {g_val}"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("≡ƒôè ╪»╪▒╪╡╪»", callback_data=f"adm:agcfg:glb:pct:{target_id}"),
            types.InlineKeyboardButton("≡ƒÆ╡ ╪¬┘ê┘à╪º┘å", callback_data=f"adm:agcfg:glb:tmn:{target_id}"),
        )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:agcfg:{target_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"≡ƒîì <b>╪¬╪«┘ü█î┘ü ┌⌐┘ä ┘à╪¡╪╡┘ê┘ä╪º╪¬</b>\n\n"
            f"╪¬┘å╪╕█î┘à ┘ü╪╣┘ä█î: <b>{cur_label}</b>\n\n"
            "┘à█îΓÇî╪«┘ê╪º┘ç█î ╪»╪▒╪╡╪» ┌⌐┘à ╪¿╪┤┘ç █î╪º ┘à╪¿┘ä╪║ ╪½╪º╪¿╪¬ (╪¬┘ê┘à╪º┘å)╪ƒ", kb)
        return

    if data.startswith("adm:agcfg:glb:"):
        # adm:agcfg:glb:pct:{target_id}  or  adm:agcfg:glb:tmn:{target_id}
        parts     = data.split(":")
        dtype     = parts[3]   # pct or tmn
        target_id = int(parts[4])
        set_agency_price_config(target_id, "global", "pct" if dtype == "pct" else "toman", 0)
        state_set(uid, "admin_agcfg_global_val", target_user_id=target_id, dtype=dtype)
        bot.answer_callback_query(call.id)
        label = "╪»╪▒╪╡╪» ╪¬╪«┘ü█î┘ü (┘à╪½╪º┘ä: 20)" if dtype == "pct" else "┘à╪¿┘ä╪║ ╪¬╪«┘ü█î┘ü ╪¿┘ç ╪¬┘ê┘à╪º┘å (┘à╪½╪º┘ä: 50000)"
        send_or_edit(call,
            f"≡ƒîì <b>╪¬╪«┘ü█î┘ü ┌⌐┘ä ┘à╪¡╪╡┘ê┘ä╪º╪¬</b>\n\n"
            f"{'≡ƒôè' if dtype == 'pct' else '≡ƒÆ╡'} {label} ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
            back_button(f"adm:agcfg:global:{target_id}"))
        return

    if data.startswith("adm:agcfg:type:") and data.count(":") == 3:
        # adm:agcfg:type:{target_id}  ΓÇö show types list
        target_id = int(data.split(":")[3])
        types_list = get_all_types()
        if not types_list:
            bot.answer_callback_query(call.id, "┘ç█î┌å ┘å┘ê╪╣█î ╪¬╪╣╪▒█î┘ü ┘å╪┤╪»┘ç.", show_alert=True)
            return
        set_agency_price_config(target_id, "type",
            get_agency_price_config(target_id)["global_type"],
            get_agency_price_config(target_id)["global_val"])
        kb = types.InlineKeyboardMarkup()
        for t in types_list:
            td = get_agency_type_discount(target_id, t["id"])
            if td:
                dot = "Γ£à"
                val_lbl = f"{td['discount_value']}{'%' if td['discount_type']=='pct' else '╪¬'}"
            else:
                dot = "Γ¼£∩╕Å"
                val_lbl = "╪¬┘å╪╕█î┘à ┘å╪┤╪»┘ç"
            kb.add(types.InlineKeyboardButton(
                f"{dot} {t['name']} | {val_lbl}",
                callback_data=f"adm:agcfg:td:{target_id}:{t['id']}"
            ))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:agcfg:{target_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒº⌐ <b>╪¬╪«┘ü█î┘ü ┘ç╪▒ ╪»╪│╪¬┘ç</b>\n\n╪»╪│╪¬┘ç ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("adm:agcfg:td:") and data.count(":") == 4:
        # adm:agcfg:td:{target_id}:{type_id}  ΓÇö choose pct or toman for this type
        parts     = data.split(":")
        target_id = int(parts[3])
        type_id   = int(parts[4])
        type_row  = get_type(type_id) if hasattr(__import__('bot.db', fromlist=['get_type']), 'get_type') else None
        td = get_agency_type_discount(target_id, type_id)
        cur_label = f"{'╪»╪▒╪╡╪»' if td['discount_type']=='pct' else '╪¬┘ê┘à╪º┘å'} ΓÇö {td['discount_value']}" if td else "╪¬┘å╪╕█î┘à ┘å╪┤╪»┘ç"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("≡ƒôè ╪»╪▒╪╡╪»", callback_data=f"adm:agcfg:tdt:{target_id}:{type_id}:pct"),
            types.InlineKeyboardButton("≡ƒÆ╡ ╪¬┘ê┘à╪º┘å", callback_data=f"adm:agcfg:tdt:{target_id}:{type_id}:tmn"),
        )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:agcfg:type:{target_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"≡ƒº⌐ <b>╪»╪│╪¬┘ç #{type_id}</b>\n\n"
            f"╪¬┘å╪╕█î┘à ┘ü╪╣┘ä█î: <b>{cur_label}</b>\n\n"
            "┘à█îΓÇî╪«┘ê╪º┘ç█î ╪»╪▒╪╡╪» ┌⌐┘à ╪¿╪┤┘ç █î╪º ┘à╪¿┘ä╪║ ╪½╪º╪¿╪¬╪ƒ", kb)
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
        label = "╪»╪▒╪╡╪» (┘à╪½╪º┘ä: 15)" if dtype == "pct" else "┘à╪¿┘ä╪║ ╪¬┘ê┘à╪º┘å (┘à╪½╪º┘ä: 30000)"
        send_or_edit(call,
            f"≡ƒº⌐ ╪»╪│╪¬┘ç #{type_id}\n\n"
            f"{'≡ƒôè' if dtype == 'pct' else '≡ƒÆ╡'} {label} ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
            back_button(f"adm:agcfg:td:{target_id}:{type_id}"))
        return

    if data.startswith("adm:agcfg:pkg:"):
        # adm:agcfg:pkg:{target_id}  ΓÇö show packages (existing flow)
        target_id = int(data.split(":")[3])
        set_agency_price_config(target_id, "package",
            get_agency_price_config(target_id)["global_type"],
            get_agency_price_config(target_id)["global_val"])
        packs = get_packages()
        if not packs:
            bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼█î ┘à┘ê╪¼┘ê╪» ┘å█î╪│╪¬.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        for p in packs:
            ap    = get_agency_price(target_id, p["id"])
            price = fmt_price(ap) if ap is not None else fmt_price(p["price"])
            label = f"{p['name']} | {price} ╪¬"
            kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:usr:agpe:{target_id}:{p['id']}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:agcfg:{target_id}"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôª <b>┘é█î┘à╪¬ ┘ç╪▒ ┘╛┌⌐█î╪¼</b>\n\n╪¿╪▒╪º█î ┘ê█î╪▒╪º█î╪┤ ╪▒┘ê█î ┘╛┌⌐█î╪¼ ╪¿╪▓┘å█î╪»:", kb)
        return

    # ΓöÇΓöÇ Admin: Broadcast ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:broadcast":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒôú ┘ç┘à┘ç ┌⌐╪º╪▒╪¿╪▒╪º┘å",             callback_data="adm:bc:all"))
        kb.add(types.InlineKeyboardButton("≡ƒ¢ì ┘ü┘é╪╖ ┘à╪┤╪¬╪▒█î╪º┘å (┘ç┘à┘ç)",       callback_data="adm:bc:cust"))
        kb.add(types.InlineKeyboardButton("≡ƒæñ ┘ü┘é╪╖ ┘à╪┤╪¬╪▒█î╪º┘å ╪╣╪º╪»█î",        callback_data="adm:bc:normal"))
        kb.add(types.InlineKeyboardButton("≡ƒñ¥ ┘ü┘é╪╖ ┘å┘à╪º█î┘å╪»┌»╪º┘å",           callback_data="adm:bc:agents"))
        kb.add(types.InlineKeyboardButton("≡ƒææ ┘ü┘é╪╖ ╪º╪»┘à█î┘åΓÇî┘ç╪º",            callback_data="adm:bc:admins"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬",                  callback_data="admin:panel"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôú <b>┘ü┘ê╪▒┘ê╪º╪▒╪» ┘ç┘à┌»╪º┘å█î</b>\n\n┌»█î╪▒┘å╪»┘çΓÇî┘ç╪º ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data == "adm:bc:all":
        state_set(uid, "admin_broadcast_all")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôú ┘╛█î╪º┘à ╪«┘ê╪» ╪▒╪º ┘ü┘ê╪▒┘ê╪º╪▒╪» █î╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n╪¿╪▒╪º█î <b>┘ç┘à┘ç ┌⌐╪º╪▒╪¿╪▒╪º┘å</b> ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘ê╪».",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:cust":
        state_set(uid, "admin_broadcast_customers")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒ¢ì ┘╛█î╪º┘à ╪«┘ê╪» ╪▒╪º ┘ü┘ê╪▒┘ê╪º╪▒╪» █î╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n┘ü┘é╪╖ ╪¿╪▒╪º█î <b>┘à╪┤╪¬╪▒█î╪º┘å</b> ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘ê╪».",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:normal":
        state_set(uid, "admin_broadcast_normal")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒæñ ┘╛█î╪º┘à ╪«┘ê╪» ╪▒╪º ┘ü┘ê╪▒┘ê╪º╪▒╪» █î╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n┘ü┘é╪╖ ╪¿╪▒╪º█î <b>┘à╪┤╪¬╪▒█î╪º┘å ╪╣╪º╪»█î</b> (╪¿╪»┘ê┘å ┘å┘à╪º█î┘å╪»┌»╪º┘å ┘ê ╪º╪»┘à█î┘åΓÇî┘ç╪º) ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘ê╪».",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:agents":
        state_set(uid, "admin_broadcast_agents")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒñ¥ ┘╛█î╪º┘à ╪«┘ê╪» ╪▒╪º ┘ü┘ê╪▒┘ê╪º╪▒╪» █î╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n┘ü┘é╪╖ ╪¿╪▒╪º█î <b>┘å┘à╪º█î┘å╪»┌»╪º┘å</b> ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘ê╪».",
                     back_button("admin:broadcast"))
        return

    if data == "adm:bc:admins":
        state_set(uid, "admin_broadcast_admins")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒææ ┘╛█î╪º┘à ╪«┘ê╪» ╪▒╪º ┘ü┘ê╪▒┘ê╪º╪▒╪» █î╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n┘ü┘é╪╖ ╪¿╪▒╪º█î <b>╪º╪»┘à█î┘åΓÇî┘ç╪º</b> ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘ê╪».",
                     back_button("admin:broadcast"))
        return

    # ΓöÇΓöÇ Admin: Group management ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:group":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        gid      = get_group_id()
        active_c = _count_active_topics()
        total_c  = len(TOPICS)
        gid_text = f"<code>{gid}</code>" if gid else "╪¬┘å╪╕█î┘à ┘å╪┤╪»┘ç"
        text = (
            "≡ƒÅó <b>┘à╪»█î╪▒█î╪¬ ┌»╪▒┘ê┘ç ╪º╪»┘à█î┘å</b>\n\n"
            "≡ƒôî <b>╪▒╪º┘ç┘å┘à╪º:</b>\n"
            "█▒. █î┌⌐ ╪│┘ê┘╛╪▒┌»╪▒┘ê┘ç ╪¬┘ä┌»╪▒╪º┘à ╪¿╪│╪º╪▓█î╪» ┘ê Topics ╪▒╪º ┘ü╪╣╪º┘ä ┌⌐┘å█î╪».\n"
            "█▓. ╪▒╪¿╪º╪¬ ╪▒╪º ╪¿┘ç ┌»╪▒┘ê┘ç ╪º╪╢╪º┘ü┘ç ┘ê ╪º╪»┘à█î┘å ┌⌐┘å█î╪».\n"
            "█│. ╪ó█î╪»█î ╪╣╪»╪»█î ┌»╪▒┘ê┘ç ╪▒╪º ╪¿╪º @getidsbot ╪»╪▒█î╪º┘ü╪¬ ┌⌐┘å█î╪».\n"
            "█┤. ╪»┌⌐┘à┘ç ┬½╪½╪¿╪¬ ╪ó█î╪»█î ┌»╪▒┘ê┘ç┬╗ ╪▒╪º ╪¿╪▓┘å█î╪» ┘ê ╪ó█î╪»█î ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n\n"
            "Γä╣∩╕Å ╪ó█î╪»█î ┌»╪▒┘ê┘ç ╪¿╪º <code>-100</code> ╪┤╪▒┘ê╪╣ ┘à█îΓÇî╪┤┘ê╪». ┘à╪½╪º┘ä: <code>-1001234567890</code>\n\n"
            f"≡ƒôè <b>┘ê╪╢╪╣█î╪¬:</b> ┌»╪▒┘ê┘ç {gid_text} | ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º: {active_c}/{total_c}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöó ╪½╪¿╪¬ ╪ó█î╪»█î ┌»╪▒┘ê┘ç",      callback_data="adm:grp:setid"))
        kb.add(types.InlineKeyboardButton("≡ƒ¢á ╪│╪º╪«╪¬ ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º█î ╪¼╪»█î╪»",  callback_data="adm:grp:create"))
        kb.add(types.InlineKeyboardButton("ΓÖ╗∩╕Å ╪¿╪º╪▓╪│╪º╪▓█î ┘ç┘à┘ç ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º", callback_data="adm:grp:reset"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:grp:setid":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_set_group_id")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöó <b>╪ó█î╪»█î ╪╣╪»╪»█î ┌»╪▒┘ê┘ç</b> ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:\n\n"
            "┘à╪½╪º┘ä: <code>-1001234567890</code>\n\n"
            "╪¿╪▒╪º█î ╪»╪▒█î╪º┘ü╪¬ ╪ó█î╪»█î ┌»╪▒┘ê┘ç╪î ╪▒╪¿╪º╪¬ <b>@getidsbot</b> ╪▒╪º ╪¿┘ç ┌»╪▒┘ê┘ç ╪º╪╢╪º┘ü┘ç ┌⌐┘å█î╪» ┘ê <code>/id</code> ╪¿┘ü╪▒╪│╪¬█î╪».",
            back_button("admin:group"))
        return

    if data == "adm:grp:create":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "╪»╪▒ ╪¡╪º┘ä ╪│╪º╪«╪¬ ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º...", show_alert=False)
        result = ensure_group_topics()
        log_admin_action(uid, "╪│╪º╪«╪¬ ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º█î ┌»╪▒┘ê┘ç")
        send_or_edit(call, f"≡ƒ¢á <b>╪│╪º╪«╪¬ ╪¬╪º┘╛█î┌⌐</b>\n\n{result}", back_button("admin:group"))
        return

    if data == "adm:grp:reset":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "╪»╪▒ ╪¡╪º┘ä ╪¿╪º╪▓╪│╪º╪▓█î...", show_alert=False)
        result = reset_and_recreate_topics()
        log_admin_action(uid, "╪¿╪º╪▓╪│╪º╪▓█î ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º█î ┌»╪▒┘ê┘ç")
        send_or_edit(call, f"ΓÖ╗∩╕Å <b>╪¿╪º╪▓╪│╪º╪▓█î ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º</b>\n\n{result}", back_button("admin:group"))
        return

    # ΓöÇΓöÇ Admin: Settings ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:settings":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("≡ƒÄº ┘╛╪┤╪¬█î╪¿╪º┘å█î",           callback_data="adm:set:support"),
            types.InlineKeyboardButton("≡ƒÆ│ ╪»╪▒┌»╪º┘çΓÇî┘ç╪º█î ┘╛╪▒╪»╪º╪«╪¬",   callback_data="adm:set:gateways"),
        )
        kb.add(types.InlineKeyboardButton("≡ƒôó ┌⌐╪º┘å╪º┘ä ┘é┘ü┘ä",        callback_data="adm:set:channel"))
        kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤ ┘à╪¬┘å ╪º╪│╪¬╪º╪▒╪¬", callback_data="adm:set:start_text"))
        kb.add(types.InlineKeyboardButton("≡ƒÄü ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å",      callback_data="adm:set:freetest"))
        kb.add(types.InlineKeyboardButton("≡ƒô£ ┘é┘ê╪º┘å█î┘å ╪«╪▒█î╪»",     callback_data="adm:set:rules"))
        kb.add(types.InlineKeyboardButton("≡ƒÅ¬ ┘à╪»█î╪▒█î╪¬ ┘ü╪▒┘ê╪┤",    callback_data="adm:set:shop"))
        kb.add(types.InlineKeyboardButton("≡ƒñû ┘à╪»█î╪▒█î╪¬ ╪╣┘à┘ä█î╪º╪¬ ╪▒╪¿╪º╪¬", callback_data="adm:ops"))
        kb.add(types.InlineKeyboardButton("≡ƒÅó ┘à╪»█î╪▒█î╪¬ ┌»╪▒┘ê┘ç",    callback_data="admin:group"))
        kb.add(types.InlineKeyboardButton("≡ƒôî ┘╛█î╪º┘àΓÇî┘ç╪º█î ┘╛█î┘å ╪┤╪»┘ç", callback_data="adm:pin"))
        kb.add(types.InlineKeyboardButton("∩┐╜ ┘à╪»█î╪▒█î╪¬ ╪º╪╣┘ä╪º┘åΓÇî┘ç╪º",  callback_data="adm:notif"))
        kb.add(types.InlineKeyboardButton("∩┐╜≡ƒÆ╛ ╪¿┌⌐╪º┘╛",            callback_data="admin:backup"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬",        callback_data="admin:panel"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "ΓÜÖ∩╕Å <b>╪¬┘å╪╕█î┘à╪º╪¬</b>", kb)
        return

    if data == "adm:set:agency_toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("agency_request_enabled", "1")
        new = "0" if cur == "1" else "1"
        setting_set("agency_request_enabled", new)
        log_admin_action(uid, f"╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î ╪º╪▓ ╪¬┘å╪╕█î┘à╪º╪¬ {'┘ü╪╣╪º┘ä' if new == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        label = "┘ü╪╣╪º┘ä" if new == "1" else "╪║█î╪▒┘ü╪╣╪º┘ä"
        bot.answer_callback_query(call.id, f"╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î: {label}")
        # re-render settings
        _fake_call_data = type('obj', (object,), {
            'id': call.id, 'message': call.message,
            'data': 'admin:settings', 'from_user': call.from_user
        })()
        _fake_call_data.id = call.id
        try:
            agency_flag  = new
            agency_icon  = "Γ£à" if agency_flag == "1" else "Γ¥î"
            pct          = setting_get("agency_default_discount_pct", "20")
            kb           = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("≡ƒÄº ┘╛╪┤╪¬█î╪¿╪º┘å█î",           callback_data="adm:set:support"),
                types.InlineKeyboardButton("≡ƒÆ│ ╪»╪▒┌»╪º┘çΓÇî┘ç╪º█î ┘╛╪▒╪»╪º╪«╪¬",   callback_data="adm:set:gateways"),
            )
            kb.add(types.InlineKeyboardButton("≡ƒôó ┌⌐╪º┘å╪º┘ä ┘é┘ü┘ä",        callback_data="adm:set:channel"))
            kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤ ┘à╪¬┘å ╪º╪│╪¬╪º╪▒╪¬", callback_data="adm:set:start_text"))
            kb.add(types.InlineKeyboardButton("≡ƒÄü ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å",      callback_data="adm:set:freetest"))
            kb.add(types.InlineKeyboardButton("≡ƒô£ ┘é┘ê╪º┘å█î┘å ╪«╪▒█î╪»",     callback_data="adm:set:rules"))
            kb.add(types.InlineKeyboardButton("≡ƒÅ╖ ╪¬┘å╪╕█î┘à╪º╪¬ ┘ü╪▒┘ê╪┤",    callback_data="adm:set:shop"))
            kb.add(types.InlineKeyboardButton("≡ƒÅó ┘à╪»█î╪▒█î╪¬ ┌»╪▒┘ê┘ç",    callback_data="admin:group"))
            kb.add(types.InlineKeyboardButton("≡ƒôî ┘╛█î╪º┘àΓÇî┘ç╪º█î ┘╛█î┘å ╪┤╪»┘ç", callback_data="adm:pin"))
            kb.add(types.InlineKeyboardButton(f"{agency_icon} ╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î", callback_data="adm:set:agency_toggle"))
            kb.add(types.InlineKeyboardButton("≡ƒôè ╪¬╪«┘ü█î┘ü ┘╛█î╪┤ΓÇî┘ü╪▒╪╢ ┘å┘à╪º█î┘å╪»┌»█î", callback_data="adm:set:agency_defpct"))
            kb.add(types.InlineKeyboardButton("∩┐╜ ┘à╪»█î╪▒█î╪¬ ╪º╪╣┘ä╪º┘åΓÇî┘ç╪º",  callback_data="adm:notif"))
            kb.add(types.InlineKeyboardButton("∩┐╜≡ƒÆ╛ ╪¿┌⌐╪º┘╛",            callback_data="admin:backup"))
            kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬",        callback_data="admin:panel"))
            send_or_edit(call, "ΓÜÖ∩╕Å <b>╪¬┘å╪╕█î┘à╪º╪¬</b>", kb)
        except Exception:
            pass
        return

    if data == "adm:set:agency_defpct":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur_pct = setting_get("agency_default_discount_pct", "20")
        state_set(uid, "admin_set_default_discount_pct")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"≡ƒôè <b>╪¬╪«┘ü█î┘ü ┘╛█î╪┤ΓÇî┘ü╪▒╪╢ ┘å┘à╪º█î┘å╪»┌»█î</b>\n\n"
            f"╪¬┘å╪╕█î┘à ┘ü╪╣┘ä█î: <b>{cur_pct}%</b>\n\n"
            "╪»╪▒╪╡╪» ╪¼╪»█î╪» ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪» (╪╣╪»╪» ╪¿█î┘å 0 ╪¬╪º 100):",
            back_button("admin:settings"))
        return

    # ΓöÇΓöÇ Notification Management ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    # Notification types: (key, label)
    _NOTIF_TYPES = [
        ("new_users",        "≡ƒæï ┌⌐╪º╪▒╪¿╪▒ ╪¼╪»█î╪»"),
        ("payment_approval", "≡ƒÆ│ ╪¬╪ú█î█î╪» ┘╛╪▒╪»╪º╪«╪¬"),
        ("renewal_request",  "ΓÖ╗∩╕Å ╪»╪▒╪«┘ê╪º╪│╪¬ ╪¬┘à╪»█î╪»"),
        ("purchase_log",     "≡ƒôª ┘ä╪º┌» ╪«╪▒█î╪»"),
        ("renewal_log",      "≡ƒöä ┘ä╪º┌» ╪¬┘à╪»█î╪»"),
        ("wallet_log",       "≡ƒÆ░ ┘ä╪º┌» ┌⌐█î┘üΓÇî┘╛┘ê┘ä"),
        ("test_report",      "≡ƒº¬ ┌»╪▓╪º╪▒╪┤ ╪¬╪│╪¬"),
        ("broadcast_report", "≡ƒôó ╪º╪╖┘ä╪º╪╣ΓÇî╪▒╪│╪º┘å█î ┘ê ┘╛█î┘å"),
        ("referral_log",     "≡ƒöù ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘çΓÇî┌»█î╪▒█î"),
        ("agency_request",   "≡ƒñ¥ ╪»╪▒╪«┘ê╪º╪│╪¬ ┘å┘à╪º█î┘å╪»┌»█î"),
        ("agency_log",       "≡ƒÅó ┘ä╪º┌» ┘å┘à╪º█î┘å╪»┌»╪º┘å"),
        ("admin_ops_log",    "≡ƒô¥ ┘ä╪º┌» ╪╣┘à┘ä█î╪º╪¬█î"),
        ("error_log",        "Γ¥î ┌»╪▓╪º╪▒╪┤ ╪«╪╖╪º"),
        ("backup",           "≡ƒÆ╛ ╪¿┌⌐╪º┘╛"),
    ]

    if data == "adm:notif":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒææ ╪º╪╣┘ä╪º┘å ┘ç╪º█î ╪▒╪¿╪º╪¬ ╪º┘ê┘å╪▒",   callback_data="adm:notif:own"))
        kb.add(types.InlineKeyboardButton("≡ƒñû ╪º╪╣┘ä╪º┘å ┘ç╪º█î ╪▒╪¿╪º╪¬ ╪º╪»┘à█î┘å",   callback_data="adm:notif:bot"))
        kb.add(types.InlineKeyboardButton("≡ƒôó ┌»╪▒┘ê┘ç",  callback_data="adm:notif:grp"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        send_or_edit(call,
            "≡ƒöö <b>┘à╪»█î╪▒█î╪¬ ╪º╪╣┘ä╪º┘åΓÇî┘ç╪º</b>\n\n"
            "≡ƒææ <b>╪º╪╣┘ä╪º┘å ┘ç╪º█î ╪▒╪¿╪º╪¬ ╪º┘ê┘å╪▒</b>: ╪º╪╣┘ä╪º┘å ╪¿╪▒╪º█î ╪º┘ê┘å╪▒ ╪»╪▒ ╪▒╪¿╪º╪¬\n"
            "≡ƒñû <b>╪º╪╣┘ä╪º┘å ┘ç╪º█î ╪▒╪¿╪º╪¬ ╪º╪»┘à█î┘å</b>: ╪º╪╣┘ä╪º┘å ╪¿╪▒╪º█î ╪º╪»┘à█î┘åΓÇî┘ç╪º█î ┘ü╪▒╪╣█î (╪¿╪▒ ╪º╪│╪º╪│ ╪»╪│╪¬╪▒╪│█î)\n"
            "≡ƒôó <b>┌»╪▒┘ê┘ç</b>: ╪º╪╣┘ä╪º┘å ╪»╪▒ ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º█î ┌»╪▒┘ê┘ç",
            kb)
        return

    if data == "adm:notif:own":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_own_{key}", "1") == "1"
            icon = "Γ£à" if on else "Γ¥î"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:otg:{key}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:notif"))
        send_or_edit(call,
            "≡ƒææ <b>╪º╪╣┘ä╪º┘å ┘ç╪º█î ╪▒╪¿╪º╪¬ ╪º┘ê┘å╪▒</b>\n\n"
            "╪º╪╣┘ä╪º┘åΓÇî┘ç╪º█î█î ┌⌐┘ç ┘à╪│╪¬┘é█î┘à╪º┘ï ╪¿╪▒╪º█î <b>ADMIN_IDS</b> (╪º█î╪» ╪½╪º╪¿╪¬ ╪¬┘ê config.py) ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘å:"
            "\nΓ£à = ┘ü╪╣╪º┘ä  |  Γ¥î = ╪║█î╪▒┘ü╪╣╪º┘ä",
            kb)
        return

    if data.startswith("adm:notif:otg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        key = data[len("adm:notif:otg:"):]
        cur = setting_get(f"notif_own_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_own_{key}", new)
        log_admin_action(uid, f"╪º╪╣┘ä╪º┘å ╪┤╪«╪╡█î {key} {'┘ü╪╣╪º┘ä' if new == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "┘ü╪╣╪º┘ä" if new == "1" else "╪║█î╪▒┘ü╪╣╪º┘ä"
        bot.answer_callback_query(call.id, f"{status_lbl} ╪┤╪»: {lbl}")
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_own_{k}", "1") == "1"
            icon = "Γ£à" if on else "Γ¥î"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:otg:{k}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:notif"))
        send_or_edit(call,
            "≡ƒææ <b>╪º╪╣┘ä╪º┘å ┘ç╪º█î ╪▒╪¿╪º╪¬ ╪º┘ê┘å╪▒</b>\n\n"
            "╪º╪╣┘ä╪º┘åΓÇî┘ç╪º█î█î ┌⌐┘ç ┘à╪│╪¬┘é█î┘à╪º┘ï ╪¿╪▒╪º█î <b>ADMIN_IDS</b> ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘å:"
            "\nΓ£à = ┘ü╪╣╪º┘ä  |  Γ¥î = ╪║█î╪▒┘ü╪╣╪º┘ä",
            kb)
        return

    if data == "adm:notif:grp":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_grp_{key}", "1") == "1"
            icon = "Γ£à" if on else "Γ¥î"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:gtg:{key}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:notif"))
        send_or_edit(call,
            "≡ƒôó <b>┌»╪▒┘ê┘ç</b>\n\n"
            "╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪» ┌⌐╪»╪º┘à ╪º╪╣┘ä╪º┘åΓÇî┘ç╪º ╪»╪▒ ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º█î ┌»╪▒┘ê┘ç ╪º╪▒╪│╪º┘ä ╪┤┘ê┘å╪»:\n"
            "Γ£à = ┘ü╪╣╪º┘ä  |  Γ¥î = ╪║█î╪▒┘ü╪╣╪º┘ä",
            kb)
        return

    if data == "adm:notif:bot":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        for key, label in _NOTIF_TYPES:
            on = setting_get(f"notif_bot_{key}", "1") == "1"
            icon = "Γ£à" if on else "Γ¥î"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"adm:notif:btg:{key}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:notif"))
        send_or_edit(call,
            "≡ƒñû <b>╪º╪╣┘ä╪º┘å ┘ç╪º█î ╪▒╪¿╪º╪¬ ╪º╪»┘à█î┘å</b>\n\n"
            "╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪» ┌⌐╪»╪º┘à ╪º╪╣┘ä╪º┘åΓÇî┘ç╪º ╪¿┘ç ╪╡┘ê╪▒╪¬ ┘à╪│╪¬┘é█î┘à ╪¿╪▒╪º█î ╪º╪»┘à█î┘åΓÇî┘ç╪º ╪º╪▒╪│╪º┘ä ╪┤┘ê┘å╪»:\n"
            "Γ£à = ┘ü╪╣╪º┘ä  |  Γ¥î = ╪║█î╪▒┘ü╪╣╪º┘ä",
            kb)
        return

    if data.startswith("adm:notif:gtg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        key = data[len("adm:notif:gtg:"):]
        cur = setting_get(f"notif_grp_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_grp_{key}", new)
        log_admin_action(uid, f"╪º╪╣┘ä╪º┘å ┌»╪▒┘ê┘ç {key} {'┘ü╪╣╪º┘ä' if new == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "┘ü╪╣╪º┘ä" if new == "1" else "╪║█î╪▒┘ü╪╣╪º┘ä"
        bot.answer_callback_query(call.id, f"{status_lbl} ╪┤╪»: {lbl}")
        # re-render group list
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_grp_{k}", "1") == "1"
            icon = "Γ£à" if on else "Γ¥î"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:gtg:{k}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:notif"))
        send_or_edit(call,
            "≡ƒôó <b>┌»╪▒┘ê┘ç</b>\n\n"
            "╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪» ┌⌐╪»╪º┘à ╪º╪╣┘ä╪º┘åΓÇî┘ç╪º ╪»╪▒ ╪¬╪º┘╛█î┌⌐ΓÇî┘ç╪º█î ┌»╪▒┘ê┘ç ╪º╪▒╪│╪º┘ä ╪┤┘ê┘å╪»:\n"
            "Γ£à = ┘ü╪╣╪º┘ä  |  Γ¥î = ╪║█î╪▒┘ü╪╣╪º┘ä",
            kb)
        return

    if data.startswith("adm:notif:btg:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        key = data[len("adm:notif:btg:"):]
        cur = setting_get(f"notif_bot_{key}", "1")
        new = "0" if cur == "1" else "1"
        setting_set(f"notif_bot_{key}", new)
        log_admin_action(uid, f"╪º╪╣┘ä╪º┘å ╪▒╪¿╪º╪¬ {key} {'┘ü╪╣╪º┘ä' if new == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        label_map = dict(_NOTIF_TYPES)
        lbl = label_map.get(key, key)
        status_lbl = "┘ü╪╣╪º┘ä" if new == "1" else "╪║█î╪▒┘ü╪╣╪º┘ä"
        bot.answer_callback_query(call.id, f"{status_lbl} ╪┤╪»: {lbl}")
        # re-render bot list
        kb = types.InlineKeyboardMarkup()
        for k, l in _NOTIF_TYPES:
            on = setting_get(f"notif_bot_{k}", "1") == "1"
            icon = "Γ£à" if on else "Γ¥î"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {l}",
                callback_data=f"adm:notif:btg:{k}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:notif"))
        send_or_edit(call,
            "≡ƒñû <b>╪º╪╣┘ä╪º┘å ┘ç╪º█î ╪▒╪¿╪º╪¬ ╪º╪»┘à█î┘å</b>\n\n"
            "╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪» ┌⌐╪»╪º┘à ╪º╪╣┘ä╪º┘åΓÇî┘ç╪º ╪¿┘ç ╪╡┘ê╪▒╪¬ ┘à╪│╪¬┘é█î┘à ╪¿╪▒╪º█î ╪º╪»┘à█î┘åΓÇî┘ç╪º ╪º╪▒╪│╪º┘ä ╪┤┘ê┘å╪»:\n"
            "Γ£à = ┘ü╪╣╪º┘ä  |  Γ¥î = ╪║█î╪▒┘ü╪╣╪º┘ä",
            kb)
        return
    # ΓöÇΓöÇ End Notification Management ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    if data == "adm:set:support":
        support_raw = setting_get("support_username", "")
        support_link = setting_get("support_link", "")
        support_link_desc = setting_get("support_link_desc", "")
        kb = types.InlineKeyboardMarkup()
        tg_status = "Γ£à" if support_raw else "Γ¥î"
        link_status = "Γ£à" if support_link else "Γ¥î"
        kb.add(types.InlineKeyboardButton(f"{tg_status} ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪¬┘ä┌»╪▒╪º┘à", callback_data="adm:set:support_tg"))
        kb.add(types.InlineKeyboardButton(f"{link_status} ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪ó┘å┘ä╪º█î┘å (┘ä█î┘å┌⌐)", callback_data="adm:set:support_link"))
        kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ╪¬┘ê╪╢█î╪¡╪º╪¬ ┘╛╪┤╪¬█î╪¿╪º┘å█î", callback_data="adm:set:support_desc"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        text = (
            "≡ƒÄº <b>╪¬┘å╪╕█î┘à╪º╪¬ ┘╛╪┤╪¬█î╪¿╪º┘å█î</b>\n\n"
            f"≡ƒô▒ ╪¬┘ä┌»╪▒╪º┘à: <code>{esc(support_raw or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}</code>\n"
            f"≡ƒîÉ ┘ä█î┘å┌⌐: <code>{esc(support_link or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}</code>\n"
            f"≡ƒô¥ ╪¬┘ê╪╢█î╪¡╪º╪¬: {esc(support_link_desc or '┘╛█î╪┤ΓÇî┘ü╪▒╪╢')}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:set:support_tg":
        state_set(uid, "admin_set_support")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÄº ╪ó█î╪»█î █î╪º ┘ä█î┘å┌⌐ ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪¬┘ä┌»╪▒╪º┘à ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n┘à╪½╪º┘ä: <code>@username</code>",
                     back_button("adm:set:support"))
        return

    if data == "adm:set:support_link":
        state_set(uid, "admin_set_support_link")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒîÉ ┘ä█î┘å┌⌐ ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪ó┘å┘ä╪º█î┘å ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n┘à╪½╪º┘ä: <code>https://example.com/chat</code>\n\n╪¿╪▒╪º█î ╪¡╪░┘ü╪î <code>-</code> ╪¿┘ü╪▒╪│╪¬█î╪».",
                     back_button("adm:set:support"))
        return

    if data == "adm:set:support_desc":
        state_set(uid, "admin_set_support_desc")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒô¥ ╪¬┘ê╪╢█î╪¡╪º╪¬ ┘å┘à╪º█î╪┤█î ╪¿╪º┘ä╪º█î ╪»┌⌐┘à┘çΓÇî┘ç╪º█î ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪▒╪º ╪¿┘å┘ê█î╪│█î╪».\n\n╪¿╪▒╪º█î ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘╛█î╪┤ΓÇî┘ü╪▒╪╢╪î <code>-</code> ╪¿┘ü╪▒╪│╪¬█î╪».",
                     back_button("adm:set:support"))
        return

    # ΓöÇΓöÇ Shop management settings ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:set:shop":
        shop_open     = setting_get("shop_open", "1")
        preorder_mode = setting_get("preorder_mode", "0")
        open_icon  = "≡ƒƒó" if shop_open     == "1" else "≡ƒö┤"
        stock_icon = "≡ƒƒó" if preorder_mode == "1" else "≡ƒö┤"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            f"{open_icon} ┘ê╪╢╪╣█î╪¬ ┘ü╪▒┘ê╪┤: {'╪¿╪º╪▓' if shop_open == '1' else '╪¿╪│╪¬┘ç'}",
            callback_data="adm:shop:toggle_open"))
        kb.add(types.InlineKeyboardButton(
            f"{stock_icon} ┘ü╪▒┘ê╪┤ ╪¿╪▒ ╪º╪│╪º╪│ ┘à┘ê╪¼┘ê╪»█î: {'┘ü╪╣╪º┘ä' if preorder_mode == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'}",
            callback_data="adm:shop:toggle_stock"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        text = (
            "≡ƒÅ¬ <b>┘à╪»█î╪▒█î╪¬ ┘ü╪▒┘ê╪┤</b>\n\n"
            f"≡ƒö╣ <b>┘ê╪╢╪╣█î╪¬ ┘ü╪▒┘ê╪┤:</b> {'≡ƒƒó ╪¿╪º╪▓' if shop_open == '1' else '≡ƒö┤ ╪¿╪│╪¬┘ç'}\n"
            f"≡ƒö╣ <b>┘ü╪▒┘ê╪┤ ╪¿╪▒ ╪º╪│╪º╪│ ┘à┘ê╪¼┘ê╪»█î:</b> {'≡ƒƒó ┘ü╪╣╪º┘ä ΓÇô ┘ü┘é╪╖ ┘╛┌⌐█î╪¼ΓÇî┘ç╪º█î ╪»╪º╪▒╪º█î ┘à┘ê╪¼┘ê╪»█î ┘å┘à╪º█î╪┤ ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê┘å╪».' if preorder_mode == '1' else '≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä ΓÇô ┘ç┘à┘ç ┘╛┌⌐█î╪¼ΓÇî┘ç╪º ┘å┘à╪º█î╪┤ ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê┘å╪». ╪»╪▒ ╪╡┘ê╪▒╪¬ ┘å╪¿┘ê╪» ┘à┘ê╪¼┘ê╪»█î╪î ╪│┘ü╪º╪▒╪┤ ╪¿┘ç ┘╛╪┤╪¬█î╪¿╪º┘å█î ╪º╪▒╪│╪º┘ä ┘à█îΓÇî╪┤┘ê╪».'}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:shop:toggle_open":
        current = setting_get("shop_open", "1")
        setting_set("shop_open", "0" if current == "1" else "1")
        log_admin_action(uid, f"┘ü╪▒┘ê╪┤┌»╪º┘ç {'╪¿╪│╪¬┘ç' if current == '1' else '╪¿╪º╪▓'} ╪┤╪»")
        bot.answer_callback_query(call.id, "┘ê╪╢╪╣█î╪¬ ┘ü╪▒┘ê╪┤ ╪¬╪║█î█î╪▒ ┌⌐╪▒╪».")
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
        log_admin_action(uid, f"╪¡╪º┘ä╪¬ ┘╛█î╪┤ΓÇî┘ü╪▒┘ê╪┤ {'╪║█î╪▒┘ü╪╣╪º┘ä' if current == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬┘å╪╕█î┘à ┘ü╪▒┘ê╪┤ ╪¿╪▒ ╪º╪│╪º╪│ ┘à┘ê╪¼┘ê╪»█î ╪¬╪║█î█î╪▒ ┌⌐╪▒╪».")
        from types import SimpleNamespace as _SN
        fake = _SN(id=call.id, from_user=call.from_user, message=call.message, data="adm:set:shop")
        _dispatch_callback(fake, uid, "adm:set:shop")
        return

    # ΓöÇΓöÇ Bot Operations Management ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    def _build_ops_kb():
        bot_status      = setting_get("bot_status", "on")
        renewal_enabled = setting_get("manual_renewal_enabled", "1")
        referral_enabled = setting_get("referral_enabled", "1")
        status_map = {"on": "≡ƒƒó ╪▒┘ê╪┤┘å", "off": "≡ƒö┤ ╪«╪º┘à┘ê╪┤", "update": "≡ƒöä ╪¿╪▒┘ê╪▓╪▒╪│╪º┘å█î"}
        renewal_map = {"1": "Γ£à ┘ü╪╣╪º┘ä", "0": "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"}
        referral_map = {"1": "Γ£à ┘ü╪╣╪º┘ä", "0": "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"}
        status_label  = status_map.get(bot_status, "≡ƒƒó ╪▒┘ê╪┤┘å")
        renewal_label = renewal_map.get(renewal_enabled, "Γ£à ┘ü╪╣╪º┘ä")
        referral_label = referral_map.get(referral_enabled, "Γ£à ┘ü╪╣╪º┘ä")
        ops_kb = types.InlineKeyboardMarkup(row_width=2)
        ops_kb.row(
            types.InlineKeyboardButton(status_label,  callback_data="adm:ops:status"),
            types.InlineKeyboardButton("≡ƒñû ┘ê╪╢╪╣█î╪¬ ╪▒╪¿╪º╪¬", callback_data="adm:ops:noop"),
        )
        ops_kb.row(
            types.InlineKeyboardButton(renewal_label, callback_data="adm:ops:renewal"),
            types.InlineKeyboardButton("ΓÖ╗∩╕Å ╪¬┘à╪»█î╪» ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º█î ╪½╪¿╪¬ ╪»╪│╪¬█î", callback_data="adm:ops:noop"),
        )
        ops_kb.row(
            types.InlineKeyboardButton(referral_label, callback_data="adm:ops:referral_toggle"),
            types.InlineKeyboardButton("≡ƒÄü ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘çΓÇî┌»█î╪▒█î", callback_data="adm:ops:noop"),
        )
        ops_kb.add(types.InlineKeyboardButton("ΓÜÖ∩╕Å ╪¬┘å╪╕█î┘à╪º╪¬ ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘çΓÇî┌»█î╪▒█î", callback_data="adm:ref:settings"))
        ops_kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        return ops_kb

    def _ops_menu_text():
        bot_status      = setting_get("bot_status", "on")
        renewal_enabled = setting_get("manual_renewal_enabled", "1")
        referral_enabled = setting_get("referral_enabled", "1")
        status_fa  = {"on": "≡ƒƒó ╪▒┘ê╪┤┘å", "off": "≡ƒö┤ ╪«╪º┘à┘ê╪┤", "update": "≡ƒöä ╪¿╪▒┘ê╪▓╪▒╪│╪º┘å█î"}.get(bot_status, "≡ƒƒó ╪▒┘ê╪┤┘å")
        renewal_fa = "Γ£à ┘ü╪╣╪º┘ä" if renewal_enabled == "1" else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
        referral_fa = "Γ£à ┘ü╪╣╪º┘ä" if referral_enabled == "1" else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
        return (
            "≡ƒñû <b>┘à╪»█î╪▒█î╪¬ ╪╣┘à┘ä█î╪º╪¬ ╪▒╪¿╪º╪¬</b>\n\n"
            f"≡ƒö╣ <b>┘ê╪╢╪╣█î╪¬ ╪▒╪¿╪º╪¬:</b> {status_fa}\n"
            f"≡ƒö╣ <b>╪¬┘à╪»█î╪» ┌⌐╪º┘å┘ü█î┌»ΓÇî┘ç╪º█î ╪½╪¿╪¬ ╪»╪│╪¬█î:</b> {renewal_fa}\n"
            f"≡ƒö╣ <b>╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘çΓÇî┌»█î╪▒█î:</b> {referral_fa}\n\n"
            "╪¿╪▒╪º█î ╪¬╪║█î█î╪▒ ┘ç╪▒ ┘à┘ê╪▒╪»╪î ╪»┌⌐┘à┘ç ┘ê╪╢╪╣█î╪¬ ┘ü╪╣┘ä█î ╪ó┘å ╪▒╪º ┘ä┘à╪│ ┌⌐┘å█î╪»."
        )

    if data == "adm:ops":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:noop":
        bot.answer_callback_query(call.id)
        return

    if data == "adm:ops:status":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("bot_status", "on")
        cycle = {"on": "off", "off": "update", "update": "on"}
        new_status = cycle.get(cur, "on")
        setting_set("bot_status", new_status)
        labels = {"on": "╪▒┘ê╪┤┘å", "off": "╪«╪º┘à┘ê╪┤", "update": "╪¿╪▒┘ê╪▓╪▒╪│╪º┘å█î"}
        log_admin_action(uid, f"┘ê╪╢╪╣█î╪¬ ╪▒╪¿╪º╪¬ ╪¿┘ç {labels[new_status]} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
        bot.answer_callback_query(call.id, f"┘ê╪╢╪╣█î╪¬ ╪▒╪¿╪º╪¬: {labels[new_status]}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:renewal":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("manual_renewal_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("manual_renewal_enabled", new_val)
        log_admin_action(uid, f"╪¬┘à╪»█î╪» ╪»╪│╪¬█î {'┘ü╪╣╪º┘ä' if new_val == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        label = "┘ü╪╣╪º┘ä" if new_val == "1" else "╪║█î╪▒┘ü╪╣╪º┘ä"
        bot.answer_callback_query(call.id, f"╪¬┘à╪»█î╪» ╪»╪│╪¬█î: {label}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    if data == "adm:ops:referral_toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("referral_enabled", "1")
        new_val = "0" if cur == "1" else "1"
        setting_set("referral_enabled", new_val)
        log_admin_action(uid, f"╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘çΓÇî┌»█î╪▒█î {'┘ü╪╣╪º┘ä' if new_val == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        label = "┘ü╪╣╪º┘ä" if new_val == "1" else "╪║█î╪▒┘ü╪╣╪º┘ä"
        bot.answer_callback_query(call.id, f"╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘çΓÇî┌»█î╪▒█î: {label}")
        send_or_edit(call, _ops_menu_text(), _build_ops_kb())
        return

    # ΓöÇΓöÇ Referral Settings ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    def _ref_settings_kb():
        sr_enabled = setting_get("referral_start_reward_enabled", "0")
        pr_enabled = setting_get("referral_purchase_reward_enabled", "0")
        sr_label = "Γ£à ┘ü╪╣╪º┘ä" if sr_enabled == "1" else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
        pr_label = "Γ£à ┘ü╪╣╪º┘ä" if pr_enabled == "1" else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
        sr_type = setting_get("referral_start_reward_type", "wallet")
        pr_type = setting_get("referral_purchase_reward_type", "wallet")
        sr_count = setting_get("referral_start_reward_count", "1")
        pr_count = setting_get("referral_purchase_reward_count", "1")
        sr_type_label = "≡ƒÆ░ ┌⌐█î┘ü ┘╛┘ê┘ä" if sr_type == "wallet" else "≡ƒôª ┌⌐╪º┘å┘ü█î┌»"
        pr_type_label = "≡ƒÆ░ ┌⌐█î┘ü ┘╛┘ê┘ä" if pr_type == "wallet" else "≡ƒôª ┌⌐╪º┘å┘ü█î┌»"

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒô╕ ╪¬┘å╪╕█î┘à ╪¿┘å╪▒ ╪º╪┤╪¬╪▒╪º┌⌐ΓÇî┌»╪░╪º╪▒█î", callback_data="adm:ref:banner"))
        # Start reward section
        kb.add(types.InlineKeyboardButton("ΓöÇΓöÇ ≡ƒÄü ┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬ ΓöÇΓöÇ", callback_data="adm:ops:noop"))
        kb.row(
            types.InlineKeyboardButton(sr_label, callback_data="adm:ref:sr:toggle"),
            types.InlineKeyboardButton("┘ê╪╢╪╣█î╪¬ ┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬", callback_data="adm:ops:noop"),
        )
        kb.add(types.InlineKeyboardButton(f"≡ƒôè ╪¬╪╣╪»╪º╪»: {sr_count} ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘ç", callback_data="adm:ref:sr:count"))
        kb.add(types.InlineKeyboardButton(f"≡ƒÄ» ┘å┘ê╪╣ ┘ç╪»█î┘ç: {sr_type_label}", callback_data="adm:ref:sr:type"))
        if sr_type == "wallet":
            sr_amount = setting_get("referral_start_reward_amount", "0")
            kb.add(types.InlineKeyboardButton(f"≡ƒÆ╡ ┘à╪¿┘ä╪║: {fmt_price(int(sr_amount))} ╪¬┘ê┘à╪º┘å", callback_data="adm:ref:sr:amount"))
        else:
            sr_pkg = setting_get("referral_start_reward_package", "")
            pkg_name = "╪º┘å╪¬╪«╪º╪¿ ┘å╪┤╪»┘ç"
            if sr_pkg:
                _p = get_package(int(sr_pkg)) if sr_pkg.isdigit() else None
                if _p:
                    pkg_name = _p["name"]
            kb.add(types.InlineKeyboardButton(f"≡ƒôª ┘╛┌⌐█î╪¼: {pkg_name}", callback_data="adm:ref:sr:pkg"))

        # Purchase reward section
        kb.add(types.InlineKeyboardButton("ΓöÇΓöÇ ≡ƒÆ╕ ┘ç╪»█î┘ç ╪«╪▒█î╪» ΓöÇΓöÇ", callback_data="adm:ops:noop"))
        kb.row(
            types.InlineKeyboardButton(pr_label, callback_data="adm:ref:pr:toggle"),
            types.InlineKeyboardButton("┘ê╪╢╪╣█î╪¬ ┘ç╪»█î┘ç ╪«╪▒█î╪»", callback_data="adm:ops:noop"),
        )
        kb.add(types.InlineKeyboardButton(f"≡ƒôè ╪¬╪╣╪»╪º╪»: {pr_count} ╪«╪▒█î╪»", callback_data="adm:ref:pr:count"))
        kb.add(types.InlineKeyboardButton(f"≡ƒÄ» ┘å┘ê╪╣ ┘ç╪»█î┘ç: {pr_type_label}", callback_data="adm:ref:pr:type"))
        if pr_type == "wallet":
            pr_amount = setting_get("referral_purchase_reward_amount", "0")
            kb.add(types.InlineKeyboardButton(f"≡ƒÆ╡ ┘à╪¿┘ä╪║: {fmt_price(int(pr_amount))} ╪¬┘ê┘à╪º┘å", callback_data="adm:ref:pr:amount"))
        else:
            pr_pkg = setting_get("referral_purchase_reward_package", "")
            pkg_name = "╪º┘å╪¬╪«╪º╪¿ ┘å╪┤╪»┘ç"
            if pr_pkg:
                _p = get_package(int(pr_pkg)) if pr_pkg.isdigit() else None
                if _p:
                    pkg_name = _p["name"]
            kb.add(types.InlineKeyboardButton(f"≡ƒôª ┘╛┌⌐█î╪¼: {pkg_name}", callback_data="adm:ref:pr:pkg"))

        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:ops"))
        return kb

    def _ref_settings_text():
        sr_enabled = "Γ£à ┘ü╪╣╪º┘ä" if setting_get("referral_start_reward_enabled", "0") == "1" else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
        pr_enabled = "Γ£à ┘ü╪╣╪º┘ä" if setting_get("referral_purchase_reward_enabled", "0") == "1" else "Γ¥î ╪║█î╪▒┘ü╪╣╪º┘ä"
        return (
            "ΓÜÖ∩╕Å <b>╪¬┘å╪╕█î┘à╪º╪¬ ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘çΓÇî┌»█î╪▒█î</b>\n\n"
            f"≡ƒÄü ┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬: {sr_enabled}\n"
            f"≡ƒÆ╕ ┘ç╪»█î┘ç ╪«╪▒█î╪» ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘ç: {pr_enabled}\n\n"
            "┘ç╪▒ ╪¿╪«╪┤ ╪▒╪º ╪¿╪º ╪»┌⌐┘à┘çΓÇî┘ç╪º█î ╪▓█î╪▒ ╪¬┘å╪╕█î┘à ┌⌐┘å█î╪»."
        )

    if data == "adm:ref:settings":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:banner":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_ref_banner")
        bot.answer_callback_query(call.id)
        cur_text = setting_get("referral_banner_text", "")
        cur_photo = setting_get("referral_banner_photo", "")
        status = ""
        if cur_text:
            status += f"\n\n≡ƒô¥ ┘à╪¬┘å ┘ü╪╣┘ä█î:\n{esc(cur_text[:200])}"
        if cur_photo:
            status += "\n≡ƒû╝ ╪╣┌⌐╪│: Γ£à ╪│╪¬ ╪┤╪»┘ç"
        kb = types.InlineKeyboardMarkup()
        if cur_text or cur_photo:
            kb.add(types.InlineKeyboardButton("≡ƒùæ ╪¡╪░┘ü ╪¿┘å╪▒ ╪│┘ü╪º╪▒╪┤█î", callback_data="adm:ref:banner:del"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:ref:settings"))
        send_or_edit(call,
            "≡ƒô╕ <b>╪¬┘å╪╕█î┘à ╪¿┘å╪▒ ╪º╪┤╪¬╪▒╪º┌⌐ΓÇî┌»╪░╪º╪▒█î</b>\n\n"
            "┘à╪¬┘å █î╪º ╪╣┌⌐╪│+┌⌐┘╛╪┤┘å ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪¿╪▒╪º█î ╪º╪┤╪¬╪▒╪º┌⌐ΓÇî┌»╪░╪º╪▒█î ┘ä█î┘å┌⌐ ╪»╪╣┘ê╪¬ ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n"
            "╪º█î┘å ┘à╪¬┘å/╪╣┌⌐╪│ ┘ç┘å┌»╪º┘à ╪º╪┤╪¬╪▒╪º┌⌐ΓÇî┌»╪░╪º╪▒█î ┘ä█î┘å┌⌐ ╪»╪╣┘ê╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¿╪▒╪º┘å ┘å┘à╪º█î╪┤ ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪».\n\n"
            "≡ƒÆí ┘ä█î┘å┌⌐ ╪»╪╣┘ê╪¬ ┌⌐╪º╪▒╪¿╪▒ ╪¿┘ç ╪╡┘ê╪▒╪¬ ╪«┘ê╪»┌⌐╪º╪▒ ╪¿┘ç ╪º┘å╪¬┘ç╪º█î ┘à╪¬┘å ╪º╪╢╪º┘ü┘ç ┘à█îΓÇî╪┤┘ê╪»."
            f"{status}", kb)
        return

    if data == "adm:ref:banner:del":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        setting_set("referral_banner_text", "")
        setting_set("referral_banner_photo", "")
        log_admin_action(uid, "╪¿┘å╪▒ ╪º╪┤╪¬╪▒╪º┌⌐ΓÇî┌»╪░╪º╪▒█î ╪¡╪░┘ü ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¿┘å╪▒ ╪│┘ü╪º╪▒╪┤█î ╪¡╪░┘ü ╪┤╪».")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # Start reward toggles
    if data == "adm:ref:sr:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("referral_start_reward_enabled", "0")
        setting_set("referral_start_reward_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬ ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘ç {'╪║█î╪▒┘ü╪╣╪º┘ä' if cur == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:sr:count":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_ref_sr_count")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöó <b>╪¬╪╣╪»╪º╪» ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘ç ╪¿╪▒╪º█î ┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬</b>\n\n"
            "╪º╪»┘à█î┘å ╪╣╪▓█î╪▓╪î ┘ê╪º╪▒╪» ┌⌐┘å█î╪» ╪¿╪╣╪» ╪º╪▓ ┌å┘å╪» ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘ç ╪¼╪»█î╪»╪î ┘ç╪»█î┘ç ╪¿┘ç ┘à╪╣╪▒┘ü ╪»╪º╪»┘ç ╪┤┘ê╪».\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <b>{setting_get('referral_start_reward_count', '1')}</b>",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:sr:type":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("referral_start_reward_type", "wallet")
        new_val = "config" if cur == "wallet" else "wallet"
        setting_set("referral_start_reward_type", new_val)
        log_admin_action(uid, f"┘å┘ê╪╣ ┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬ ╪¿┘ç {'┌⌐█î┘ü ┘╛┘ê┘ä' if new_val == 'wallet' else '┌⌐╪º┘å┘ü█î┌»'} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
        bot.answer_callback_query(call.id, f"┘å┘ê╪╣ ┘ç╪»█î┘ç: {'┌⌐█î┘ü ┘╛┘ê┘ä' if new_val == 'wallet' else '┌⌐╪º┘å┘ü█î┌»'}")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:sr:amount":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_ref_sr_amount")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒÆ╡ <b>┘à╪¿┘ä╪║ ╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä (┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬)</b>\n\n"
            "┘à╪¿┘ä╪║ ╪¿┘ç ╪¬┘ê┘à╪º┘å ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <b>{fmt_price(int(setting_get('referral_start_reward_amount', '0')))}</b> ╪¬┘ê┘à╪º┘å",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:sr:pkg":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
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
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:ref:settings"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôª <b>╪º┘å╪¬╪«╪º╪¿ ┘╛┌⌐█î╪¼ ┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬</b>\n\n┘╛┌⌐█î╪¼█î ┌⌐┘ç ┘à█îΓÇî╪«┘ê╪º┘ç█î╪» ╪¿┘ç ╪╣┘å┘ê╪º┘å ┘ç╪»█î┘ç ╪»╪º╪»┘ç ╪┤┘ê╪» ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("adm:ref:sr:pkgsel:"):
        pkg_id = data.split(":")[4]
        setting_set("referral_start_reward_package", pkg_id)
        log_admin_action(uid, f"┘╛┌⌐█î╪¼ ┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬ ╪¿┘ç #{pkg_id} ╪¬┘å╪╕█î┘à ╪┤╪»")
        bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ ┘ç╪»█î┘ç ╪º╪│╪¬╪º╪▒╪¬ ╪¬┘å╪╕█î┘à ╪┤╪».")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # Purchase reward toggles
    if data == "adm:ref:pr:toggle":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("referral_purchase_reward_enabled", "0")
        setting_set("referral_purchase_reward_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"┘ç╪»█î┘ç ╪«╪▒█î╪» ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘ç {'╪║█î╪▒┘ü╪╣╪º┘ä' if cur == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id)
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:pr:count":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_ref_pr_count")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöó <b>╪¬╪╣╪»╪º╪» ╪«╪▒█î╪» ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘ç ╪¿╪▒╪º█î ┘ç╪»█î┘ç</b>\n\n"
            "┘ê╪º╪▒╪» ┌⌐┘å█î╪» ╪¿╪╣╪» ╪º╪▓ ┌å┘å╪» ╪«╪▒█î╪» ╪º┘ê┘ä ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘çΓÇî┘ç╪º╪î ┘ç╪»█î┘ç ╪¿┘ç ┘à╪╣╪▒┘ü ╪»╪º╪»┘ç ╪┤┘ê╪».\n"
            "ΓÜá∩╕Å ┘ü┘é╪╖ ╪º┘ê┘ä█î┘å ╪«╪▒█î╪» ┘ç╪▒ ╪▓█î╪▒┘à╪¼┘à┘ê╪╣┘ç ╪»╪▒ ┘å╪╕╪▒ ┌»╪▒┘ü╪¬┘ç ┘à█îΓÇî╪┤┘ê╪».\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <b>{setting_get('referral_purchase_reward_count', '1')}</b>",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:pr:type":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("referral_purchase_reward_type", "wallet")
        new_val = "config" if cur == "wallet" else "wallet"
        setting_set("referral_purchase_reward_type", new_val)
        log_admin_action(uid, f"┘å┘ê╪╣ ┘ç╪»█î┘ç ╪«╪▒█î╪» ╪¿┘ç {'┌⌐█î┘ü ┘╛┘ê┘ä' if new_val == 'wallet' else '┌⌐╪º┘å┘ü█î┌»'} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
        bot.answer_callback_query(call.id, f"┘å┘ê╪╣ ┘ç╪»█î┘ç: {'┌⌐█î┘ü ┘╛┘ê┘ä' if new_val == 'wallet' else '┌⌐╪º┘å┘ü█î┌»'}")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    if data == "adm:ref:pr:amount":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_ref_pr_amount")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒÆ╡ <b>┘à╪¿┘ä╪║ ╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä (┘ç╪»█î┘ç ╪«╪▒█î╪»)</b>\n\n"
            "┘à╪¿┘ä╪║ ╪¿┘ç ╪¬┘ê┘à╪º┘å ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <b>{fmt_price(int(setting_get('referral_purchase_reward_amount', '0')))}</b> ╪¬┘ê┘à╪º┘å",
            back_button("adm:ref:settings"))
        return

    if data == "adm:ref:pr:pkg":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
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
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:ref:settings"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôª <b>╪º┘å╪¬╪«╪º╪¿ ┘╛┌⌐█î╪¼ ┘ç╪»█î┘ç ╪«╪▒█î╪»</b>\n\n┘╛┌⌐█î╪¼█î ┌⌐┘ç ┘à█îΓÇî╪«┘ê╪º┘ç█î╪» ╪¿┘ç ╪╣┘å┘ê╪º┘å ┘ç╪»█î┘ç ╪»╪º╪»┘ç ╪┤┘ê╪» ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("adm:ref:pr:pkgsel:"):
        pkg_id = data.split(":")[4]
        setting_set("referral_purchase_reward_package", pkg_id)
        log_admin_action(uid, f"┘╛┌⌐█î╪¼ ┘ç╪»█î┘ç ╪«╪▒█î╪» ╪¿┘ç #{pkg_id} ╪¬┘å╪╕█î┘à ╪┤╪»")
        bot.answer_callback_query(call.id, "┘╛┌⌐█î╪¼ ┘ç╪»█î┘ç ╪«╪▒█î╪» ╪¬┘å╪╕█î┘à ╪┤╪».")
        send_or_edit(call, _ref_settings_text(), _ref_settings_kb())
        return

    # ΓöÇΓöÇ Gateway settings ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:set:gateways":
        kb = types.InlineKeyboardMarkup()
        for gw_key, gw_default in [
            ("card",             "≡ƒÆ│ ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬"),
            ("crypto",           "≡ƒÆÄ ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä"),
            ("tetrapay",         "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TetraPay)"),
            ("swapwallet_crypto","≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ ┘ê ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä (SwapWallet)"),
            ("tronpays_rial",    "≡ƒÆ│ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TronsPay)"),
        ]:
            enabled = setting_get(f"gw_{gw_key}_enabled", "0")
            status_icon = "≡ƒƒó" if enabled == "1" else "≡ƒö┤"
            gw_label = setting_get(f"gw_{gw_key}_display_name", "").strip() or gw_default
            kb.add(types.InlineKeyboardButton(f"{status_icon} {gw_label}", callback_data=f"adm:set:gw:{gw_key}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÆ│ <b>╪»╪▒┌»╪º┘çΓÇî┘ç╪º█î ┘╛╪▒╪»╪º╪«╪¬</b>\n\n╪»╪▒┌»╪º┘ç ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data == "adm:set:gw:card":
        enabled = setting_get("gw_card_enabled", "0")
        vis = setting_get("gw_card_visibility", "public")
        card = setting_get("payment_card", "")
        bank = setting_get("payment_bank", "")
        owner = setting_get("payment_owner", "")
        range_enabled = setting_get("gw_card_range_enabled", "0")
        display_name = setting_get("gw_card_display_name", "")
        enabled_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if enabled == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        vis_label = "≡ƒæÑ ╪╣┘à┘ê┘à█î" if vis == "public" else "≡ƒöÆ ┌⌐╪º╪▒╪¿╪▒╪º┘å ╪º┘à┘å"
        range_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if range_enabled == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"┘ê╪╢╪╣█î╪¬: {enabled_label}", callback_data="adm:gw:card:toggle"),
            types.InlineKeyboardButton(f"┘å┘à╪º█î╪┤: {vis_label}", callback_data="adm:gw:card:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"≡ƒôè ╪¿╪º╪▓┘ç ┘╛╪▒╪»╪º╪«╪¬█î: {range_label}", callback_data="adm:gw:card:range"))
        kb.add(types.InlineKeyboardButton("≡ƒÅ╖ ┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç", callback_data="adm:gw:card:set_name"))
        kb.add(types.InlineKeyboardButton("≡ƒÆ│ ╪┤┘à╪º╪▒┘ç ┌⌐╪º╪▒╪¬", callback_data="adm:set:card"))
        kb.add(types.InlineKeyboardButton("≡ƒÅª ┘å╪º┘à ╪¿╪º┘å┌⌐", callback_data="adm:set:bank"))
        kb.add(types.InlineKeyboardButton("≡ƒæñ ┘å╪º┘à ╪╡╪º╪¡╪¿ ┌⌐╪º╪▒╪¬", callback_data="adm:set:owner"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:set:gateways"))
        name_display = display_name or "<i>┘╛█î╪┤ΓÇî┘ü╪▒╪╢: ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬</i>"
        text = (
            "≡ƒÆ│ <b>╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬</b>\n\n"
            f"┘ê╪╢╪╣█î╪¬: {enabled_label}\n"
            f"┘å┘à╪º█î╪┤: {vis_label}\n"
            f"┘å╪º┘à ┘å┘à╪º█î╪┤█î: {name_display}\n\n"
            f"┌⌐╪º╪▒╪¬: <code>{esc(card or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}</code>\n"
            f"╪¿╪º┘å┌⌐: {esc(bank or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}\n"
            f"╪╡╪º╪¡╪¿: {esc(owner or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:card:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="card")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_card_display_name", "")
        send_or_edit(call,
            f"≡ƒÅ╖ <b>┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬</b>\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <code>{esc(current or '┘╛█î╪┤ΓÇî┘ü╪▒╪╢')}</code>\n\n"
            "┘å╪º┘à ╪»┘ä╪«┘ê╪º┘ç ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n"
            "╪¿╪▒╪º█î ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘╛█î╪┤ΓÇî┘ü╪▒╪╢╪î <code>-</code> ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».",
            back_button("adm:set:gw:card"))
        return

    if data == "adm:gw:card:toggle":
        enabled = setting_get("gw_card_enabled", "0")
        setting_set("gw_card_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ {'╪║█î╪▒┘ü╪╣╪º┘ä' if enabled == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:card")
        return

    if data == "adm:gw:card:vis":
        vis = setting_get("gw_card_visibility", "public")
        setting_set("gw_card_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"┘å┘à╪º█î╪┤ ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç {'secure' if vis == 'public' else 'public'} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:card")
        return

    if data == "adm:set:gw:crypto":
        enabled = setting_get("gw_crypto_enabled", "0")
        vis = setting_get("gw_crypto_visibility", "public")
        range_enabled = setting_get("gw_crypto_range_enabled", "0")
        enabled_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if enabled == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        vis_label = "≡ƒæÑ ╪╣┘à┘ê┘à█î" if vis == "public" else "≡ƒöÆ ┌⌐╪º╪▒╪¿╪▒╪º┘å ╪º┘à┘å"
        range_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if range_enabled == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"┘ê╪╢╪╣█î╪¬: {enabled_label}", callback_data="adm:gw:crypto:toggle"),
            types.InlineKeyboardButton(f"┘å┘à╪º█î╪┤: {vis_label}", callback_data="adm:gw:crypto:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"≡ƒôè ╪¿╪º╪▓┘ç ┘╛╪▒╪»╪º╪«╪¬█î: {range_label}", callback_data="adm:gw:crypto:range"))
        kb.add(types.InlineKeyboardButton("≡ƒÅ╖ ┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç", callback_data="adm:gw:crypto:set_name"))
        for coin_key, coin_label in CRYPTO_COINS:
            addr = setting_get(f"crypto_{coin_key}", "")
            status_icon = "Γ£à" if addr else "Γ¥î"
            kb.add(types.InlineKeyboardButton(f"{status_icon} {coin_label}", callback_data=f"adm:set:cw:{coin_key}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:set:gateways"))
        display_name_crypto = setting_get("gw_crypto_display_name", "")
        name_display_crypto = display_name_crypto or "<i>┘╛█î╪┤ΓÇî┘ü╪▒╪╢: ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä</i>"
        text = (
            "≡ƒÆÄ <b>╪»╪▒┌»╪º┘ç ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä</b>\n\n"
            f"┘ê╪╢╪╣█î╪¬: {enabled_label}\n"
            f"┘å┘à╪º█î╪┤: {vis_label}\n"
            f"┘å╪º┘à ┘å┘à╪º█î╪┤█î: {name_display_crypto}\n\n"
            "╪¿╪▒╪º█î ┘ê█î╪▒╪º█î╪┤ ╪ó╪»╪▒╪│ ┘ê┘ä╪¬ ╪▒┘ê█î ┘ç╪▒ ╪º╪▒╪▓ ╪¿╪▓┘å█î╪»:"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:crypto:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="crypto")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_crypto_display_name", "")
        send_or_edit(call,
            f"≡ƒÅ╖ <b>┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä</b>\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <code>{esc(current or '┘╛█î╪┤ΓÇî┘ü╪▒╪╢')}</code>\n\n"
            "┘å╪º┘à ╪»┘ä╪«┘ê╪º┘ç ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n"
            "╪¿╪▒╪º█î ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘╛█î╪┤ΓÇî┘ü╪▒╪╢╪î <code>-</code> ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».",
            back_button("adm:set:gw:crypto"))
        return

    if data == "adm:gw:crypto:toggle":
        enabled = setting_get("gw_crypto_enabled", "0")
        setting_set("gw_crypto_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"╪»╪▒┌»╪º┘ç ┌⌐╪▒█î┘╛╪¬┘ê {'╪║█î╪▒┘ü╪╣╪º┘ä' if enabled == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:crypto")
        return

    if data == "adm:gw:crypto:vis":
        vis = setting_get("gw_crypto_visibility", "public")
        setting_set("gw_crypto_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"┘å┘à╪º█î╪┤ ╪»╪▒┌»╪º┘ç ┌⌐╪▒█î┘╛╪¬┘ê ╪¿┘ç {'secure' if vis == 'public' else 'public'} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:crypto")
        return

    if data == "adm:set:gw:tetrapay":
        enabled = setting_get("gw_tetrapay_enabled", "0")
        vis = setting_get("gw_tetrapay_visibility", "public")
        api_key = setting_get("tetrapay_api_key", "")
        mode_bot = setting_get("tetrapay_mode_bot", "1")
        mode_web = setting_get("tetrapay_mode_web", "1")
        enabled_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if enabled == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        vis_label = "≡ƒæÑ ╪╣┘à┘ê┘à█î" if vis == "public" else "≡ƒöÆ ┌⌐╪º╪▒╪¿╪▒╪º┘å ╪º┘à┘å"
        bot_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if mode_bot == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        web_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if mode_web == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"┘ê╪╢╪╣█î╪¬: {enabled_label}", callback_data="adm:gw:tetrapay:toggle"),
            types.InlineKeyboardButton(f"┘å┘à╪º█î╪┤: {vis_label}", callback_data="adm:gw:tetrapay:vis"),
        )
        kb.row(
            types.InlineKeyboardButton(f"╪¬┘ä┌»╪▒╪º┘à: {bot_label}", callback_data="adm:gw:tetrapay:mode_bot"),
            types.InlineKeyboardButton(f"┘à╪▒┘ê╪▒┌»╪▒: {web_label}", callback_data="adm:gw:tetrapay:mode_web"),
        )
        range_enabled_tp = setting_get("gw_tetrapay_range_enabled", "0")
        range_label_tp = "≡ƒƒó ┘ü╪╣╪º┘ä" if range_enabled_tp == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        kb.add(types.InlineKeyboardButton(f"≡ƒôè ╪¿╪º╪▓┘ç ┘╛╪▒╪»╪º╪«╪¬█î: {range_label_tp}", callback_data="adm:gw:tetrapay:range"))
        kb.add(types.InlineKeyboardButton("≡ƒÅ╖ ┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç", callback_data="adm:gw:tetrapay:set_name"))
        kb.add(types.InlineKeyboardButton("≡ƒöæ ╪¬┘å╪╕█î┘à ┌⌐┘ä█î╪» API", callback_data="adm:set:tetrapay_key"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("≡ƒîÉ ╪»╪▒█î╪º┘ü╪¬ ┌⌐┘ä█î╪» API ╪º╪▓ ╪│╪º█î╪¬ TetraPay", url="https://tetra98.com"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:set:gateways"))
        if api_key:
            key_display = f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>"
        else:
            key_display = "Γ¥î <b>╪½╪¿╪¬ ┘å╪┤╪»┘ç</b> ΓÇö ╪º╪¿╪¬╪»╪º ╪º╪▓ ╪│╪º█î╪¬ TetraPay ┌⌐┘ä█î╪» API ╪«┘ê╪» ╪▒╪º ╪»╪▒█î╪º┘ü╪¬ ┌⌐┘å█î╪»"
        display_name_tp = setting_get("gw_tetrapay_display_name", "")
        name_display_tp = display_name_tp or "<i>┘╛█î╪┤ΓÇî┘ü╪▒╪╢: ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TetraPay)</i>"
        text = (
            "≡ƒÆ│ <b>╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TetraPay)</b>\n\n"
            f"┘ê╪╢╪╣█î╪¬: {enabled_label}\n"
            f"┘å┘à╪º█î╪┤: {vis_label}\n"
            f"┘å╪º┘à ┘å┘à╪º█î╪┤█î: {name_display_tp}\n\n"
            f"≡ƒÆ│ ┘╛╪▒╪»╪º╪«╪¬ ╪º╪▓ ╪¬┘ä┌»╪▒╪º┘à: {bot_label}\n"
            f"≡ƒîÉ ┘╛╪▒╪»╪º╪«╪¬ ╪º╪▓ ┘à╪▒┘ê╪▒┌»╪▒: {web_label}\n\n"
            f"┌⌐┘ä█î╪» API: {key_display}"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:tetrapay:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="tetrapay")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_tetrapay_display_name", "")
        send_or_edit(call,
            f"≡ƒÅ╖ <b>┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç TetraPay</b>\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <code>{esc(current or '┘╛█î╪┤ΓÇî┘ü╪▒╪╢')}</code>\n\n"
            "┘å╪º┘à ╪»┘ä╪«┘ê╪º┘ç ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n"
            "╪¿╪▒╪º█î ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘╛█î╪┤ΓÇî┘ü╪▒╪╢╪î <code>-</code> ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».",
            back_button("adm:set:gw:tetrapay"))
        return

    if data == "adm:gw:tetrapay:toggle":
        enabled = setting_get("gw_tetrapay_enabled", "0")
        setting_set("gw_tetrapay_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"╪»╪▒┌»╪º┘ç ╪¬╪¬╪▒╪º┘╛█î {'╪║█î╪▒┘ü╪╣╪º┘ä' if enabled == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:vis":
        vis = setting_get("gw_tetrapay_visibility", "public")
        setting_set("gw_tetrapay_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"┘å┘à╪º█î╪┤ ╪»╪▒┌»╪º┘ç ╪¬╪¬╪▒╪º┘╛█î ╪¿┘ç {'secure' if vis == 'public' else 'public'} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:mode_bot":
        cur = setting_get("tetrapay_mode_bot", "1")
        setting_set("tetrapay_mode_bot", "0" if cur == "1" else "1")
        log_admin_action(uid, f"╪¡╪º┘ä╪¬ bot ╪¬╪¬╪▒╪º┘╛█î {'╪║█î╪▒┘ü╪╣╪º┘ä' if cur == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:gw:tetrapay:mode_web":
        cur = setting_get("tetrapay_mode_web", "1")
        setting_set("tetrapay_mode_web", "0" if cur == "1" else "1")
        log_admin_action(uid, f"╪¡╪º┘ä╪¬ web ╪¬╪¬╪▒╪º┘╛█î {'╪║█î╪▒┘ü╪╣╪º┘ä' if cur == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:tetrapay")
        return

    if data == "adm:set:tetrapay_key":
        state_set(uid, "admin_set_tetrapay_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒöæ ┌⌐┘ä█î╪» API ╪¬╪¬╪▒╪º┘╛█î ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:set:gw:tetrapay"))
        return

    if data == "adm:set:gw:swapwallet_crypto":
        from ..gateways.swapwallet_crypto import NETWORK_LABELS as SW_CRYPTO_LABELS
        enabled  = setting_get("gw_swapwallet_crypto_enabled", "0")
        vis      = setting_get("gw_swapwallet_crypto_visibility", "public")
        api_key  = setting_get("swapwallet_crypto_api_key", "")
        username = setting_get("swapwallet_crypto_username", "")
        enabled_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if enabled == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        vis_label     = "≡ƒæÑ ╪╣┘à┘ê┘à█î" if vis == "public" else "≡ƒöÆ ┌⌐╪º╪▒╪¿╪▒╪º┘å ╪º┘à┘å"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"┘ê╪╢╪╣█î╪¬: {enabled_label}", callback_data="adm:gw:swapwallet_crypto:toggle"),
            types.InlineKeyboardButton(f"┘å┘à╪º█î╪┤: {vis_label}",    callback_data="adm:gw:swapwallet_crypto:vis"),
        )
        range_en = setting_get("gw_swapwallet_crypto_range_enabled", "0")
        range_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if range_en == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        kb.add(types.InlineKeyboardButton(f"≡ƒôè ╪¿╪º╪▓┘ç ┘╛╪▒╪»╪º╪«╪¬█î: {range_label}", callback_data="adm:gw:swapwallet_crypto:range"))
        kb.add(types.InlineKeyboardButton("≡ƒöæ ╪¬┘å╪╕█î┘à ┌⌐┘ä█î╪» API",        callback_data="adm:set:swapwallet_crypto_key"))
        kb.add(types.InlineKeyboardButton("≡ƒæñ ┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î ┘ü╪▒┘ê╪┤┌»╪º┘ç",     callback_data="adm:set:swapwallet_crypto_username"))
        kb.add(types.InlineKeyboardButton("≡ƒÅ╖ ┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç", callback_data="adm:gw:swapwallet_crypto:set_name"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("≡ƒîÉ ╪»╪▒█î╪º┘ü╪¬ ┌⌐┘ä█î╪» API ╪º╪▓ ╪│┘ê╪º┘╛ ┘ê┘ä╪¬", url="https://swapwallet.app"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:set:gateways"))
        key_display = f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>" if api_key else "Γ¥î <b>╪½╪¿╪¬ ┘å╪┤╪»┘ç ΓÇö ╪º┘ä╪▓╪º┘à█î</b>"
        user_status = "Γ£à ╪½╪¿╪¬ ╪┤╪»┘ç" if username else "Γ¥î ╪½╪¿╪¬ ┘å╪┤╪»┘ç"
        display_name_sw = setting_get("gw_swapwallet_crypto_display_name", "")
        name_display_sw = display_name_sw or "<i>┘╛█î╪┤ΓÇî┘ü╪▒╪╢: ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ ┘ê ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä (SwapWallet)</i>"
        text = (
            "≡ƒÆ│ <b>╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ ┘ê ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä (SwapWallet)</b>\n\n"
            f"┘ê╪╢╪╣█î╪¬: {enabled_label}\n"
            f"┘å┘à╪º█î╪┤: {vis_label}\n"
            f"┘å╪º┘à ┘å┘à╪º█î╪┤█î: {name_display_sw}\n\n"
            f"≡ƒæñ ┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î Application: <code>{esc(username or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}</code> {user_status}\n"
            f"≡ƒöæ ┌⌐┘ä█î╪» API: {key_display}\n\n"
            "≡ƒôû <b>╪┤╪¿┌⌐┘çΓÇî┘ç╪º█î ┘╛╪┤╪¬█î╪¿╪º┘å█î:</b> TRON ┬╖ TON ┬╖ BSC\n\n"
            "≡ƒôû <b>┘à╪▒╪º╪¡┘ä ╪▒╪º┘çΓÇî╪º┘å╪»╪º╪▓█î:</b>\n"
            "1∩╕ÅΓâú ╪»╪▒ ┘à█î┘å█îΓÇî╪º┘╛ ╪│┘ê╪º┘╛ΓÇî┘ê┘ä╪¬ ╪º╪│╪¬╪º╪▒╪¬ ╪¿╪▓┘å█î╪»:\n"
            "   ≡ƒæë @SwapWalletBot\n"
            "2∩╕ÅΓâú ╪»╪▒ ┘╛┘å┘ä ╪¿█î╪▓┘å╪│ ╪¿╪º ╪¬┘ä┌»╪▒╪º┘à ┘ä╪º┌»█î┘å ┌⌐┘å█î╪»:\n"
            "   ≡ƒæë business.swapwallet.app\n"
            "3∩╕ÅΓâú █î┌⌐ ┘ü╪▒┘ê╪┤┌»╪º┘ç ╪¼╪»█î╪» ╪¿╪│╪º╪▓█î╪»\n"
            "4∩╕ÅΓâú <b>┘å╪º┘à ┘ü╪▒┘ê╪┤┌»╪º┘ç</b> ╪▒┘ê ╪¿┘ç ╪╣┘å┘ê╪º┘å ┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î ╪º█î┘å╪¼╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»\n"
            "5∩╕ÅΓâú ╪º╪▓ ╪¬╪¿ <b>┘╛╪▒┘ê┘ü╪º█î┘ä ΓåÉ ┌⌐┘ä█î╪» API</b> ┌⌐┘ä█î╪» ╪¿┌»█î╪▒█î╪» ┘ê ┘ê╪º╪▒╪» ┌⌐┘å█î╪»"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:swapwallet_crypto:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="swapwallet_crypto")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_swapwallet_crypto_display_name", "")
        send_or_edit(call,
            f"≡ƒÅ╖ <b>┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç SwapWallet</b>\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <code>{esc(current or '┘╛█î╪┤ΓÇî┘ü╪▒╪╢')}</code>\n\n"
            "┘å╪º┘à ╪»┘ä╪«┘ê╪º┘ç ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n"
            "╪¿╪▒╪º█î ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘╛█î╪┤ΓÇî┘ü╪▒╪╢╪î <code>-</code> ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:gw:swapwallet_crypto:toggle":
        enabled = setting_get("gw_swapwallet_crypto_enabled", "0")
        setting_set("gw_swapwallet_crypto_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"╪»╪▒┌»╪º┘ç ╪│┘ê╪º┘╛ΓÇî┘ê┘ä╪¬ ┌⌐╪▒█î┘╛╪¬┘ê {'╪║█î╪▒┘ü╪╣╪º┘ä' if enabled == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:swapwallet_crypto")
        return

    if data == "adm:gw:swapwallet_crypto:vis":
        vis = setting_get("gw_swapwallet_crypto_visibility", "public")
        setting_set("gw_swapwallet_crypto_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"┘å┘à╪º█î╪┤ ╪»╪▒┌»╪º┘ç ╪│┘ê╪º┘╛ΓÇî┘ê┘ä╪¬ ┌⌐╪▒█î┘╛╪¬┘ê ╪¿┘ç {'secure' if vis == 'public' else 'public'} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:swapwallet_crypto")
        return

    if data == "adm:set:swapwallet_crypto_key":
        state_set(uid, "admin_set_swapwallet_crypto_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöæ <b>┌⌐┘ä█î╪» API (SwapWallet ┌⌐╪▒█î┘╛╪¬┘ê) ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»</b>\n\n"
            "┘ü╪▒┘à╪¬: <code>apikey-xxx...</code>\n\n"
            "≡ƒôì ╪¿╪▒╪º█î ╪»╪▒█î╪º┘ü╪¬:\n"
            "╪º┘╛ ╪│┘ê╪º┘╛ΓÇî┘ê┘ä╪¬ ΓåÉ ┘╛╪▒┘ê┘ü╪º█î┘ä ΓåÉ <b>┌⌐┘ä█î╪» API</b>",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:set:swapwallet_crypto_username":
        state_set(uid, "admin_set_swapwallet_crypto_username")
        bot.answer_callback_query(call.id)
        current = setting_get("swapwallet_crypto_username", "")
        send_or_edit(call,
            f"≡ƒæñ <b>┘å╪º┘à ┌⌐╪º╪▒╪¿╪▒█î ┘ü╪▒┘ê╪┤┌»╪º┘ç (SwapWallet ┌⌐╪▒█î┘╛╪¬┘ê) ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»</b>\n\n"
            f"╪º█î┘å ┘ç┘à╪º┘å <b>┘å╪º┘à ┘ü╪▒┘ê╪┤┌»╪º┘ç</b> ╪┤┘à╪º ╪»╪▒ ┘╛┘å┘ä ╪¿█î╪▓┘å╪│ ╪º╪│╪¬.\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <code>{esc(current or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}</code>",
            back_button("adm:set:gw:swapwallet_crypto"))
        return

    if data == "adm:set:gw:tronpays_rial":
        enabled = setting_get("gw_tronpays_rial_enabled", "0")
        vis     = setting_get("gw_tronpays_rial_visibility", "public")
        api_key = setting_get("tronpays_rial_api_key", "")
        enabled_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if enabled == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        vis_label     = "≡ƒæÑ ╪╣┘à┘ê┘à█î" if vis == "public" else "≡ƒöÆ ┌⌐╪º╪▒╪¿╪▒╪º┘å ╪º┘à┘å"
        range_en      = setting_get("gw_tronpays_rial_range_enabled", "0")
        range_label   = "≡ƒƒó ┘ü╪╣╪º┘ä" if range_en == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton(f"┘ê╪╢╪╣█î╪¬: {enabled_label}", callback_data="adm:gw:tronpays_rial:toggle"),
            types.InlineKeyboardButton(f"┘å┘à╪º█î╪┤: {vis_label}",     callback_data="adm:gw:tronpays_rial:vis"),
        )
        kb.add(types.InlineKeyboardButton(f"≡ƒôè ╪¿╪º╪▓┘ç ┘╛╪▒╪»╪º╪«╪¬█î: {range_label}", callback_data="adm:gw:tronpays_rial:range"))
        kb.add(types.InlineKeyboardButton("≡ƒöæ ╪¬┘å╪╕█î┘à ┌⌐┘ä█î╪» API", callback_data="adm:set:tronpays_rial_key"))
        kb.add(types.InlineKeyboardButton("≡ƒöù ╪¬┘å╪╕█î┘à Callback URL", callback_data="adm:set:tronpays_rial_cb_url"))
        kb.add(types.InlineKeyboardButton("≡ƒÅ╖ ┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç", callback_data="adm:gw:tronpays_rial:set_name"))
        if not api_key:
            kb.add(types.InlineKeyboardButton("≡ƒñû ╪»╪▒█î╪º┘ü╪¬ API Key ╪º╪▓ @TronPaysBot", url="https://t.me/TronPaysBot"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="adm:set:gateways"))
        key_display = (f"<code>{esc(api_key[:8])}...{esc(api_key[-4:])}</code>"
                       if api_key else "Γ¥î <b>╪½╪¿╪¬ ┘å╪┤╪»┘ç</b> ΓÇö ╪º╪¿╪¬╪»╪º ╪º╪▓ ╪▒╪¿╪º╪¬ @TronPaysBot ┌⌐┘ä█î╪» API ╪»╪▒█î╪º┘ü╪¬ ┌⌐┘å█î╪»")
        cb_url = setting_get("tronpays_rial_callback_url", "").strip() or "https://example.com/"
        display_name_tp_rial = setting_get("gw_tronpays_rial_display_name", "")
        name_display_tp_rial = display_name_tp_rial or "<i>┘╛█î╪┤ΓÇî┘ü╪▒╪╢: ╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TronsPay)</i>"
        text = (
            "≡ƒÆ│ <b>╪»╪▒┌»╪º┘ç ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬ (TronsPay)</b>\n\n"
            f"┘ê╪╢╪╣█î╪¬: {enabled_label}\n"
            f"┘å┘à╪º█î╪┤: {vis_label}\n"
            f"┘å╪º┘à ┘å┘à╪º█î╪┤█î: {name_display_tp_rial}\n\n"
            f"≡ƒöæ ┌⌐┘ä█î╪» API: {key_display}\n"
            f"≡ƒöù Callback URL: <code>{esc(cb_url)}</code>\n\n"
            "≡ƒôï <b>╪▒╪º┘ç┘å┘à╪º█î ╪»╪▒█î╪º┘ü╪¬ API Key:</b>\n"
            "█▒. ╪▒╪¿╪º╪¬ @TronPaysBot ╪▒╪º ╪º╪│╪¬╪º╪▒╪¬ ┌⌐┘å█î╪»\n"
            "█▓. ╪½╪¿╪¬ΓÇî┘å╪º┘à ┘ê ╪º╪¡╪▒╪º╪▓ ┘ç┘ê█î╪¬ ╪▒╪º ╪¬┌⌐┘à█î┘ä ┌⌐┘å█î╪»\n"
            "█│. ┌⌐┘ä█î╪» API ╪▒╪º ╪º╪▓ ┘╛╪▒┘ê┘ü╪º█î┘ä ╪»╪▒█î╪º┘ü╪¬ ┌⌐┘å█î╪»"
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data == "adm:gw:tronpays_rial:set_name":
        state_set(uid, "admin_set_gw_display_name", gw="tronpays_rial")
        bot.answer_callback_query(call.id)
        current = setting_get("gw_tronpays_rial_display_name", "")
        send_or_edit(call,
            f"≡ƒÅ╖ <b>┘å╪º┘à ┘å┘à╪º█î╪┤█î ╪»╪▒┌»╪º┘ç TronsPay</b>\n\n"
            f"┘à┘é╪»╪º╪▒ ┘ü╪╣┘ä█î: <code>{esc(current or '┘╛█î╪┤ΓÇî┘ü╪▒╪╢')}</code>\n\n"
            "┘å╪º┘à ╪»┘ä╪«┘ê╪º┘ç ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».\n"
            "╪¿╪▒╪º█î ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘╛█î╪┤ΓÇî┘ü╪▒╪╢╪î <code>-</code> ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪».",
            back_button("adm:set:gw:tronpays_rial"))
        return

    if data == "adm:gw:tronpays_rial:toggle":
        enabled = setting_get("gw_tronpays_rial_enabled", "0")
        setting_set("gw_tronpays_rial_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"╪»╪▒┌»╪º┘ç ╪¬╪▒┘ê┘åΓÇî┘╛█î╪▓ ╪▒█î╪º┘ä█î {'╪║█î╪▒┘ü╪╣╪º┘ä' if enabled == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:tronpays_rial")
        return

    if data == "adm:gw:tronpays_rial:vis":
        vis = setting_get("gw_tronpays_rial_visibility", "public")
        setting_set("gw_tronpays_rial_visibility", "secure" if vis == "public" else "public")
        log_admin_action(uid, f"┘å┘à╪º█î╪┤ ╪»╪▒┌»╪º┘ç ╪¬╪▒┘ê┘åΓÇî┘╛█î╪▓ ╪▒█î╪º┘ä█î ╪¿┘ç {'secure' if vis == 'public' else 'public'} ╪¬╪║█î█î╪▒ ┌⌐╪▒╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:gw:tronpays_rial")
        return

    if data == "adm:set:tronpays_rial_key":
        state_set(uid, "admin_set_tronpays_rial_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒöæ ┌⌐┘ä█î╪» API TronPays ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:set:gw:tronpays_rial"))
        return

    if data == "adm:set:tronpays_rial_cb_url":
        state_set(uid, "admin_set_tronpays_rial_cb_url")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöù <b>Callback URL ╪»╪▒┌»╪º┘ç TronPays</b>\n\n"
            "█î┌⌐ URL ┘à╪╣╪¬╪¿╪▒ ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪» (┘à╪½┘ä╪º┘ï ╪ó╪»╪▒╪│ ╪│╪º█î╪¬ █î╪º ┘ê╪¿┘ç┘ê┌⌐ ╪┤┘à╪º).\n"
            "╪º┌»╪▒ ┘å╪»╪º╪▒█î╪»╪î <code>https://example.com/</code> ╪▒╪º ╪¿┘ü╪▒╪│╪¬█î╪».",
            back_button("adm:set:gw:tronpays_rial"))
        return

    _GW_RANGE_LABELS = {"card": "≡ƒÆ│ ┌⌐╪º╪▒╪¬ ╪¿┘ç ┌⌐╪º╪▒╪¬", "crypto": "≡ƒÆÄ ╪º╪▒╪▓ ╪»█î╪¼█î╪¬╪º┘ä", "tetrapay": "≡ƒÅª TetraPay", "swapwallet": "≡ƒÆÄ SwapWallet", "swapwallet_crypto": "≡ƒÆÄ SwapWallet ┌⌐╪▒█î┘╛╪¬┘ê", "tronpays_rial": "≡ƒÆ│ TronPays"}

    if data.startswith("adm:gw:") and data.endswith(":range"):
        gw_name = data.split(":")[2]
        gw_label = _GW_RANGE_LABELS.get(gw_name, gw_name)
        range_enabled = setting_get(f"gw_{gw_name}_range_enabled", "0")
        range_min = setting_get(f"gw_{gw_name}_range_min", "")
        range_max = setting_get(f"gw_{gw_name}_range_max", "")
        enabled_label = "≡ƒƒó ┘ü╪╣╪º┘ä" if range_enabled == "1" else "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä"
        min_label = fmt_price(int(range_min)) + " ╪¬┘ê┘à╪º┘å" if range_min else "╪¿╪»┘ê┘å ╪¡╪»╪º┘é┘ä"
        max_label = fmt_price(int(range_max)) + " ╪¬┘ê┘à╪º┘å" if range_max else "╪¿╪»┘ê┘å ╪¡╪»╪º┌⌐╪½╪▒"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"┘ê╪╢╪╣█î╪¬ ╪¿╪º╪▓┘ç: {enabled_label}", callback_data=f"adm:gw:{gw_name}:range:toggle"))
        kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ╪¬┘å╪╕█î┘à ╪¿╪º╪▓┘ç", callback_data=f"adm:gw:{gw_name}:range:set"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data=f"adm:set:gw:{gw_name}"))
        text = (
            f"≡ƒôè <b>╪¿╪º╪▓┘ç ┘╛╪▒╪»╪º╪«╪¬█î ΓÇö {gw_label}</b>\n\n"
            f"┘ê╪╢╪╣█î╪¬: {enabled_label}\n"
            f"╪¡╪»╪º┘é┘ä ┘à╪¿┘ä╪║: {min_label}\n"
            f"╪¡╪»╪º┌⌐╪½╪▒ ┘à╪¿┘ä╪║: {max_label}\n\n"
            "ΓÜá∩╕Å ╪º┌»╪▒ ╪¿╪º╪▓┘ç ┘ü╪╣╪º┘ä ╪¿╪º╪┤╪»╪î ╪º█î┘å ╪»╪▒┌»╪º┘ç ┘ü┘é╪╖ ╪¿╪▒╪º█î ┘à╪¿╪º┘ä╪║ ╪»╪º╪«┘ä ╪¿╪º╪▓┘ç ┘å┘à╪º█î╪┤ ╪»╪º╪»┘ç ┘à█îΓÇî╪┤┘ê╪»."
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:gw:") and data.endswith(":range:toggle"):
        gw_name = data.split(":")[2]
        cur = setting_get(f"gw_{gw_name}_range_enabled", "0")
        setting_set(f"gw_{gw_name}_range_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"╪¿╪º╪▓┘ç ┘à╪¿┘ä╪║ ╪»╪▒┌»╪º┘ç {gw_name} {'╪║█î╪▒┘ü╪╣╪º┘ä' if cur == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, f"adm:gw:{gw_name}:range")
        return

    if data.startswith("adm:gw:") and data.endswith(":range:set"):
        gw_name = data.split(":")[2]
        state_set(uid, "admin_gw_range_min", gw=gw_name)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒôè <b>╪¡╪»╪º┘é┘ä ┘à╪¿┘ä╪║</b> (╪¬┘ê┘à╪º┘å) ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».\n\n"
            "╪¿╪▒╪º█î <b>╪¿╪»┘ê┘å ╪¡╪»╪º┘é┘ä</b>╪î ╪╣╪»╪» <code>0</code> █î╪º <code>-</code> ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:",
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
        send_or_edit(call, "≡ƒÆ│ ╪┤┘à╪º╪▒┘ç ┌⌐╪º╪▒╪¬ ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:set:gw:card"))
        return

    if data == "adm:set:bank":
        state_set(uid, "admin_set_bank")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒÅª ┘å╪º┘à ╪¿╪º┘å┌⌐ ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:set:gw:card"))
        return

    if data == "adm:set:owner":
        state_set(uid, "admin_set_owner")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒæñ ┘å╪º┘à ┘ê ┘å╪º┘à ╪«╪º┘å┘ê╪º╪»┌»█î ╪╡╪º╪¡╪¿ ┌⌐╪º╪▒╪¬ ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:set:gw:card"))
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
            f"≡ƒÆÄ ╪ó╪»╪▒╪│ ┘ê┘ä╪¬ <b>{coin_label}</b> ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».\n"
            f"╪ó╪»╪▒╪│ ┘ü╪╣┘ä█î: <code>{esc(current or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}</code>\n\n"
            "╪¿╪▒╪º█î ╪¡╪░┘ü╪î ╪╣╪»╪» <code>-</code> ╪¿┘ü╪▒╪│╪¬█î╪».",
            back_button("adm:set:gw:crypto")
        )
        return

    if data == "adm:set:channel":
        current = setting_get("channel_id", "")
        state_set(uid, "admin_set_channel")
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"≡ƒôó <b>┌⌐╪º┘å╪º┘ä ┘é┘ü┘ä</b>\n\n"
            f"┌⌐╪º┘å╪º┘ä ┘ü╪╣┘ä█î: {esc(current or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}\n\n"
            "@username ┌⌐╪º┘å╪º┘ä ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»\n"
            "╪¿╪▒╪º█î ╪║█î╪▒┘ü╪╣╪º┘ä ┌⌐╪▒╪»┘å╪î <code>-</code> ╪¿┘ü╪▒╪│╪¬█î╪»\n\n"
            "ΓÜá∩╕Å ╪▒╪¿╪º╪¬ ╪¿╪º█î╪» ╪º╪»┘à█î┘å ┌⌐╪º┘å╪º┘ä ╪¿╪º╪┤╪»",
            back_button("admin:settings")
        )
        return

    if data == "adm:set:start_text":
        current = setting_get("start_text", "")
        state_set(uid, "admin_set_start_text")
        bot.answer_callback_query(call.id)
        preview = esc(current[:200]) + "..." if len(current) > 200 else esc(current or "┘╛█î╪┤ΓÇî┘ü╪▒╪╢")
        send_or_edit(
            call,
            f"Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ┘à╪¬┘å ╪º╪│╪¬╪º╪▒╪¬</b>\n\n"
            f"┘à╪¬┘å ┘ü╪╣┘ä█î:\n{preview}\n\n"
            "┘à╪¬┘å ╪¼╪»█î╪» ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪». ┘à█îΓÇî╪¬┘ê╪º┘å█î╪» ╪º╪▓ ╪¬┌»ΓÇî┘ç╪º█î HTML ╪º╪│╪¬┘ü╪º╪»┘ç ┌⌐┘å█î╪».\n"
            "╪¿╪▒╪º█î ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘à╪¬┘å ┘╛█î╪┤ΓÇî┘ü╪▒╪╢╪î <code>-</code> ╪¿┘ü╪▒╪│╪¬█î╪».",
            back_button("admin:settings")
        )
        return

    # ΓöÇΓöÇ Admin: Free Test Settings ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:set:freetest":
        enabled = setting_get("free_test_enabled", "1")
        agent_limit = setting_get("agent_test_limit", "0")
        agent_period = setting_get("agent_test_period", "day")
        period_labels = {"day": "╪▒┘ê╪▓", "week": "┘ç┘ü╪¬┘ç", "month": "┘à╪º┘ç"}
        kb = types.InlineKeyboardMarkup()
        toggle_label = "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä ┌⌐╪▒╪»┘å" if enabled == "1" else "≡ƒƒó ┘ü╪╣╪º┘ä ┌⌐╪▒╪»┘å"
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:ft:toggle"))
        kb.add(types.InlineKeyboardButton("≡ƒöä ╪▒█î╪│╪¬ ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ┘ç┘à┘ç ┌⌐╪º╪▒╪¿╪▒╪º┘å", callback_data="adm:ft:reset"))
        kb.add(types.InlineKeyboardButton(f"≡ƒñ¥ ╪¬╪╣╪»╪º╪» ╪¬╪│╪¬ ┘ç┘à┌⌐╪º╪▒╪º┘å: {agent_limit} ╪»╪▒ {period_labels.get(agent_period, agent_period)}", callback_data="adm:ft:agent"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"≡ƒÄü <b>╪¬┘å╪╕█î┘à╪º╪¬ ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å</b>\n\n"
            f"┘ê╪╢╪╣█î╪¬: {'≡ƒƒó ┘ü╪╣╪º┘ä' if enabled == '1' else '≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä'}\n"
            f"╪¬╪│╪¬ ┘ç┘à┌⌐╪º╪▒╪º┘å: <b>{agent_limit}</b> ╪╣╪»╪» ╪»╪▒ {period_labels.get(agent_period, agent_period)}",
            kb
        )
        return

    if data == "adm:ft:toggle":
        enabled = setting_get("free_test_enabled", "1")
        setting_set("free_test_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å {'╪║█î╪▒┘ü╪╣╪º┘ä' if enabled == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:freetest")
        return

    if data == "adm:ft:reset":
        reset_all_free_tests()
        bot.answer_callback_query(call.id, "Γ£à ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ┘ç┘à┘ç ┌⌐╪º╪▒╪¿╪▒╪º┘å ╪▒█î╪│╪¬ ╪┤╪».", show_alert=True)
        _fake_call(call, "adm:set:freetest")
        return

    if data == "adm:ft:agent":
        state_set(uid, "admin_set_agent_test_limit")
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            "≡ƒñ¥ <b>╪¬╪╣╪»╪º╪» ╪¬╪│╪¬ ┘ç┘à┌⌐╪º╪▒╪º┘å</b>\n\n"
            "╪¬╪╣╪»╪º╪» ╪¬╪│╪¬ ╪▒╪º█î┌»╪º┘å ┘ç┘à┌⌐╪º╪▒╪º┘å ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪».\n"
            "┘ü╪▒┘à╪¬: <code>╪¬╪╣╪»╪º╪» ╪¿╪º╪▓┘ç</code>\n\n"
            "┘à╪½╪º┘ä:\n"
            "<code>5 day</code> ΓåÆ █╡ ╪¬╪│╪¬ ╪»╪▒ ╪▒┘ê╪▓\n"
            "<code>10 week</code> ΓåÆ █▒█░ ╪¬╪│╪¬ ╪»╪▒ ┘ç┘ü╪¬┘ç\n"
            "<code>20 month</code> ΓåÆ █▓█░ ╪¬╪│╪¬ ╪»╪▒ ┘à╪º┘ç\n\n"
            "╪¿╪▒╪º█î ╪║█î╪▒┘ü╪╣╪º┘ä ┌⌐╪▒╪»┘å ┘à╪¡╪»┘ê╪»█î╪¬╪î <code>0</code> ╪¿┘ü╪▒╪│╪¬█î╪».",
            back_button("adm:set:freetest")
        )
        return

    # ΓöÇΓöÇ Admin: Purchase Rules ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:set:rules":
        enabled = setting_get("purchase_rules_enabled", "0")
        kb = types.InlineKeyboardMarkup()
        toggle_label = "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä ┌⌐╪▒╪»┘å" if enabled == "1" else "≡ƒƒó ┘ü╪╣╪º┘ä ┌⌐╪▒╪»┘å"
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:rules:toggle"))
        kb.add(types.InlineKeyboardButton("Γ£Å∩╕Å ┘ê█î╪▒╪º█î╪┤ ┘à╪¬┘å ┘é┘ê╪º┘å█î┘å", callback_data="adm:rules:edit"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"≡ƒô£ <b>┘é┘ê╪º┘å█î┘å ╪«╪▒█î╪»</b>\n\n"
            f"┘ê╪╢╪╣█î╪¬: {'≡ƒƒó ┘ü╪╣╪º┘ä' if enabled == '1' else '≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä'}\n\n"
            "┘ê┘é╪¬█î ┘ü╪╣╪º┘ä ╪¿╪º╪┤╪»╪î ┌⌐╪º╪▒╪¿╪▒ ┘é╪¿┘ä ╪º╪▓ ╪º┘ê┘ä█î┘å ╪«╪▒█î╪» ╪¿╪º█î╪» ┘é┘ê╪º┘å█î┘å ╪▒╪º ╪¿┘╛╪░█î╪▒╪».", kb)
        return

    if data == "adm:rules:toggle":
        enabled = setting_get("purchase_rules_enabled", "0")
        setting_set("purchase_rules_enabled", "0" if enabled == "1" else "1")
        log_admin_action(uid, f"┘é┘ê╪º┘å█î┘å ╪«╪▒█î╪» {'╪║█î╪▒┘ü╪╣╪º┘ä' if enabled == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "adm:set:rules")
        return

    if data == "adm:rules:edit":
        state_set(uid, "admin_edit_rules_text")
        bot.answer_callback_query(call.id)
        current_text = setting_get("purchase_rules_text", "")
        preview = f"\n\n≡ƒô¥ ┘à╪¬┘å ┘ü╪╣┘ä█î:\n{esc(current_text[:200])}..." if len(current_text) > 200 else (f"\n\n≡ƒô¥ ┘à╪¬┘å ┘ü╪╣┘ä█î:\n{esc(current_text)}" if current_text else "")
        send_or_edit(call,
            f"Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ┘à╪¬┘å ┘é┘ê╪º┘å█î┘å ╪«╪▒█î╪»</b>{preview}\n\n"
            "┘à╪¬┘å ╪¼╪»█î╪» ┘é┘ê╪º┘å█î┘å ╪«╪▒█î╪» ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:",
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
        # Proceed to buy flow
        _fake_call(call, "buy:start_real")
        return

    # ΓöÇΓöÇ Admin: Pinned Messages ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "adm:pin":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        pins = get_all_pinned_messages()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Γ₧ò ╪º┘ü╪▓┘ê╪»┘å ┘╛█î╪º┘à ┘╛█î┘å", callback_data="adm:pin:add"))
        for p in pins:
            preview = (p["text"] or "")[:30].replace("\n", " ")
            kb.row(
                types.InlineKeyboardButton(f"≡ƒôî {preview}", callback_data="noop"),
                types.InlineKeyboardButton("Γ£Å∩╕Å", callback_data=f"adm:pin:edit:{p['id']}"),
                types.InlineKeyboardButton("≡ƒùæ", callback_data=f"adm:pin:del:{p['id']}"),
            )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        count_text = f"{len(pins)} ┘╛█î╪º┘à" if pins else "┘ç█î┌å ┘╛█î╪º┘à█î ╪½╪¿╪¬ ┘å╪┤╪»┘ç"
        send_or_edit(call, f"≡ƒôî <b>┘╛█î╪º┘àΓÇî┘ç╪º█î ┘╛█î┘å ╪┤╪»┘ç</b>\n\n{count_text}", kb)
        return

    if data == "adm:pin:add":
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_pin_add")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôî <b>╪º┘ü╪▓┘ê╪»┘å ┘╛█î╪º┘à ┘╛█î┘å</b>\n\n┘à╪¬┘å ┘╛█î╪º┘à ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:", back_button("adm:pin"))
        return

    if data.startswith("adm:pin:del:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
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
        log_admin_action(uid, f"┘╛█î╪º┘à ┘╛█î┘å #{pin_id} ╪¡╪░┘ü ╪┤╪»")
        bot.answer_callback_query(call.id, "≡ƒùæ ┘╛█î╪º┘à ╪¡╪░┘ü ┘ê ╪ó┘å┘╛█î┘å ╪┤╪».")
        send_to_topic("broadcast_report",
            f"≡ƒùæ <b>╪¡╪░┘ü ┘╛█î╪º┘à ┘╛█î┘å</b>\n\n"
            f"≡ƒæñ ╪¡╪░┘üΓÇî┌⌐┘å┘å╪»┘ç: <code>{uid}</code>\n"
            f"≡ƒùæ ╪¡╪░┘ü ╪┤╪»┘ç ╪º╪▓: <b>{removed_count}</b> ┌⌐╪º╪▒╪¿╪▒\n\n"
            f"≡ƒô¥ <b>┘à╪¬┘å ┘╛█î╪º┘à:</b>\n{esc(_pin_text_preview) if _pin_text_preview else '(╪«╪º┘ä█î)'}")
        _fake_call(call, "adm:pin")
        return

    if data.startswith("adm:pin:edit:"):
        if not admin_has_perm(uid, "settings"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        pin_id = int(data.split(":")[3])
        pin = get_pinned_message(pin_id)
        if not pin:
            bot.answer_callback_query(call.id, "┘╛█î╪º┘à █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        state_set(uid, "admin_pin_edit", pin_id=pin_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ┘╛█î╪º┘à ┘╛█î┘å</b>\n\n┘à╪¬┘å ┘ü╪╣┘ä█î:\n<code>{esc(pin['text'])}</code>\n\n┘à╪¬┘å ╪¼╪»█î╪» ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:",
            back_button("adm:pin"))
        return

    # ΓöÇΓöÇ Admin: Backup ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:backup":
        enabled  = setting_get("backup_enabled", "0")
        interval = setting_get("backup_interval", "24")
        target   = setting_get("backup_target_id", "")
        kb       = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒÆ╛ ╪¿┌⌐╪º┘╛ ╪»╪│╪¬█î", callback_data="adm:bkp:manual"))
        kb.add(types.InlineKeyboardButton("≡ƒôÑ ╪¿╪º╪▓█î╪º╪¿█î ╪¿┌⌐╪º┘╛", callback_data="adm:bkp:restore"))
        toggle_label = "≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä ┌⌐╪▒╪»┘å ╪¿┌⌐╪º┘╛ ╪«┘ê╪»┌⌐╪º╪▒" if enabled == "1" else "≡ƒƒó ┘ü╪╣╪º┘ä ┌⌐╪▒╪»┘å ╪¿┌⌐╪º┘╛ ╪«┘ê╪»┌⌐╪º╪▒"
        kb.add(types.InlineKeyboardButton(toggle_label, callback_data="adm:bkp:toggle"))
        kb.add(types.InlineKeyboardButton(f"ΓÅ░ ╪▓┘à╪º┘åΓÇî╪¿┘å╪»█î: ┘ç╪▒ {interval} ╪│╪º╪╣╪¬", callback_data="adm:bkp:interval"))
        kb.add(types.InlineKeyboardButton("≡ƒôñ ╪¬┘å╪╕█î┘à ┘à┘é╪╡╪»", callback_data="adm:bkp:target"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:settings"))
        bot.answer_callback_query(call.id)
        send_or_edit(
            call,
            f"≡ƒÆ╛ <b>╪¿┌⌐╪º┘╛</b>\n\n"
            f"╪¿┌⌐╪º┘╛ ╪«┘ê╪»┌⌐╪º╪▒: {'≡ƒƒó ┘ü╪╣╪º┘ä' if enabled == '1' else '≡ƒö┤ ╪║█î╪▒┘ü╪╣╪º┘ä'}\n"
            f"┘ç╪▒ {interval} ╪│╪º╪╣╪¬\n"
            f"┘à┘é╪╡╪»: <code>{esc(target or '╪½╪¿╪¬ ┘å╪┤╪»┘ç')}</code>",
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
        log_admin_action(uid, f"╪¿┌⌐╪º┘╛ ╪«┘ê╪»┌⌐╪º╪▒ {'╪║█î╪▒┘ü╪╣╪º┘ä' if enabled == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _fake_call(call, "admin:backup")
        return

    if data == "adm:bkp:interval":
        state_set(uid, "admin_set_backup_interval")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "ΓÅ░ ╪¿╪º╪▓┘ç ╪¿┌⌐╪º┘╛ ╪«┘ê╪»┌⌐╪º╪▒ ╪▒╪º ╪¿┘ç ╪│╪º╪╣╪¬ ┘ê╪º╪▒╪» ┌⌐┘å█î╪» (┘à╪½╪º┘ä: 6╪î 12╪î 24):",
                     back_button("admin:backup"))
        return

    if data == "adm:bkp:target":
        state_set(uid, "admin_set_backup_target")
        bot.answer_callback_query(call.id)
        send_or_edit(call, "≡ƒôñ ╪ó█î╪»█î ╪╣╪»╪»█î ┌⌐╪º╪▒╪¿╪▒ █î╪º ┌⌐╪º┘å╪º┘ä ╪¿╪▒╪º█î ╪»╪▒█î╪º┘ü╪¬ ╪¿┌⌐╪º┘╛ ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
                     back_button("admin:backup"))
        return

    if data == "adm:bkp:restore":
        state_set(uid, "admin_restore_backup")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒôÑ <b>╪¿╪º╪▓█î╪º╪¿█î ╪¿┌⌐╪º┘╛</b>\n\n"
            "ΓÜá∩╕Å <b>╪¬┘ê╪¼┘ç:</b> ╪¿╪º ╪¿╪º╪▓█î╪º╪¿█î ╪¿┌⌐╪º┘╛╪î ╪»█î╪¬╪º╪¿█î╪│ ┘ü╪╣┘ä█î ╪▒╪¿╪º╪¬ ╪¡╪░┘ü ┘ê ╪¿╪º ┘ü╪º█î┘ä ╪¿┌⌐╪º┘╛ ╪¼╪º█î┌»╪▓█î┘å ┘à█îΓÇî╪┤┘ê╪».\n\n"
            "┘ü╪º█î┘ä ╪¿┌⌐╪º┘╛ (<code>.db</code>) ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:",
            back_button("admin:backup"))
        return

    # ΓöÇΓöÇ Admin: Discount Codes ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:discounts":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _render_discount_admin_list(call, uid)
        return

    if data == "admin:vouchers":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _render_voucher_admin_list(call, uid)
        return

    if data == "admin:vch:toggle_global":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("vouchers_enabled", "1")
        setting_set("vouchers_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"╪│█î╪│╪¬┘à ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç {'╪║█î╪▒┘ü╪╣╪º┘ä' if cur == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _render_voucher_admin_list(call, uid)
        return

    if data == "admin:vch:add":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_vch_add_name")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒÄ½ <b>╪º┘ü╪▓┘ê╪»┘å ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç</b>\n\n"
            "┘à╪▒╪¡┘ä┘ç █▒: █î┌⌐ <b>┘å╪º┘à</b> ╪¿╪▒╪º█î ╪º█î┘å ╪»╪│╪¬┘ç ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:\n"
            "<i>┘à╪½╪º┘ä: ╪¼╪┤┘å┘ê╪º╪▒┘ç ┘å┘ê╪▒┘ê╪▓</i>",
            back_button("admin:vouchers"))
        return

    if data == "admin:vch:gift_type:wallet":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        sd = state_data(uid)
        state_set(uid, "admin_vch_add_amount", vch_name=sd.get("vch_name", ""))
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒÄ½ <b>╪º┘ü╪▓┘ê╪»┘å ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç</b>\n\n"
            "┘à╪▒╪¡┘ä┘ç █│: ┘à╪¿┘ä╪║ ╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä ╪▒╪º ╪¿┘ç <b>╪¬┘ê┘à╪º┘å</b> ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
            back_button("admin:vch:add"))
        return

    if data == "admin:vch:gift_type:config":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        sd = state_data(uid)
        state_set(uid, "admin_vch_pick_type", vch_name=sd.get("vch_name", ""))
        bot.answer_callback_query(call.id)
        types_list = get_active_types()
        kb = types.InlineKeyboardMarkup()
        for t in types_list:
            kb.add(types.InlineKeyboardButton(t["name"], callback_data=f"admin:vch:pick_type:{t['id']}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:vch:add"))
        send_or_edit(call,
            "≡ƒÄ½ <b>╪º┘ü╪▓┘ê╪»┘å ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç ΓÇô ╪º┘å╪¬╪«╪º╪¿ ┘å┘ê╪╣</b>\n\n"
            "┘å┘ê╪╣ ┌⌐╪º┘å┘ü█î┌» ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("admin:vch:pick_type:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
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
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="admin:vch:gift_type:config"))
        send_or_edit(call, "≡ƒÄ½ <b>╪º┘ü╪▓┘ê╪»┘å ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç ΓÇô ╪º┘å╪¬╪«╪º╪¿ ┘╛┌⌐█î╪¼</b>\n\n┘╛┌⌐█î╪¼ ┘à┘ê╪▒╪» ┘å╪╕╪▒ ╪▒╪º ╪º┘å╪¬╪«╪º╪¿ ┌⌐┘å█î╪»:", kb)
        return

    if data.startswith("admin:vch:pick_pkg:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        pkg_id = int(data.split(":")[3])
        sd = state_data(uid)
        state_set(uid, "admin_vch_add_count_config",
                  vch_name=sd.get("vch_name", ""), package_id=pkg_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒÄ½ <b>╪º┘ü╪▓┘ê╪»┘å ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç</b>\n\n"
            "┘à╪▒╪¡┘ä┘ç ╪ó╪«╪▒: ╪¬╪╣╪»╪º╪» ┌⌐╪»┘ç╪º█î ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:\n"
            "<i>┘à╪½╪º┘ä: █╡█░</i>",
            back_button("admin:vouchers"))
        return

    if data.startswith("admin:vch:view:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _render_voucher_batch_detail(call, uid, batch_id)
        return

    if data.startswith("admin:vch:del:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        batch = get_voucher_batch(batch_id)
        if not batch:
            bot.answer_callback_query(call.id, "╪»╪│╪¬┘ç █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("≡ƒùæ ╪¿┘ä┘ç╪î ╪¡╪░┘ü ╪┤┘ê╪»", callback_data=f"admin:vch:del_confirm:{batch_id}"),
            types.InlineKeyboardButton("Γ¥î ┘ä╪║┘ê", callback_data=f"admin:vch:view:{batch_id}"),
        )
        send_or_edit(call,
            f"≡ƒùæ <b>╪¡╪░┘ü ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç</b>\n\n"
            f"╪ó█î╪º ╪º╪▓ ╪¡╪░┘ü ╪»╪│╪¬┘ç ┬½{esc(batch['name'])}┬╗ ┘ê ╪¬┘à╪º┘à ┌⌐╪»┘ç╪º█î ╪ó┘å ┘à╪╖┘à╪ª┘å ┘ç╪│╪¬█î╪»╪ƒ",
            kb)
        return

    if data.startswith("admin:vch:del_confirm:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        batch_id = int(data.split(":")[3])
        delete_voucher_batch(batch_id)
        log_admin_action(uid, f"╪»╪│╪¬┘ç ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç #{batch_id} ╪¡╪░┘ü ╪┤╪»")
        bot.answer_callback_query(call.id, "Γ£à ╪»╪│╪¬┘ç ╪¡╪░┘ü ╪┤╪».")
        _render_voucher_admin_list(call, uid)
        return

    # ΓöÇΓöÇ User: voucher redemption ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "voucher:redeem":
        if setting_get("vouchers_enabled", "1") != "1":
            bot.answer_callback_query(call.id, "ΓÜá∩╕Å ╪│█î╪│╪¬┘à ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç ╪»╪▒ ╪¡╪º┘ä ╪¡╪º╪╢╪▒ ╪║█î╪▒┘ü╪╣╪º┘ä ╪º╪│╪¬.", show_alert=True)
            return
        state_set(uid, "await_voucher_code")
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬", callback_data="nav:main"))
        send_or_edit(call,
            "≡ƒÄ½Γ£¿ <b>╪½╪¿╪¬ ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç</b> Γ£¿≡ƒÄ½\n\n"
            "≡ƒîƒ ╪º╪▓ ╪º█î┘å┌⌐┘ç ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘çΓÇî╪º█î ╪»╪▒█î╪º┘ü╪¬ ┌⌐╪▒╪»┘çΓÇî╪º█î╪» ╪«┘ê╪┤╪¡╪º┘ä█î┘à!\n\n"
            "Γ£ì∩╕Å ┘ä╪╖┘ü╪º┘ï ┌⌐╪» ┌⌐╪º╪▒╪¬ ┘ç╪»█î┘ç ╪«┘ê╪» ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪» ╪¬╪º ┘ç╪»█î┘çΓÇî╪¬╪º┘å ┘ü┘ê╪▒█î ╪¿┘ç ╪¡╪│╪º╪¿ ╪┤┘à╪º ╪º╪╢╪º┘ü┘ç ╪┤┘ê╪»:",
            kb)
        return

    if data == "admin:disc:toggle_global":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        cur = setting_get("discount_codes_enabled", "0")
        setting_set("discount_codes_enabled", "0" if cur == "1" else "1")
        log_admin_action(uid, f"╪│█î╪│╪¬┘à ┌⌐╪» ╪¬╪«┘ü█î┘ü {'╪║█î╪▒┘ü╪╣╪º┘ä' if cur == '1' else '┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _render_discount_admin_list(call, uid)
        return

    if data == "admin:disc:add":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_discount_add_code")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒÄƒ <b>╪º┘ü╪▓┘ê╪»┘å ┌⌐╪» ╪¬╪«┘ü█î┘ü</b>\n\n"
            "┘à╪▒╪¡┘ä┘ç █▒/█┤: ┘à╪¬┘å ┌⌐╪» ╪¬╪«┘ü█î┘ü ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:\n"
            "(╪¡╪▒┘ê┘ü ╪º┘å┌»┘ä█î╪│█î╪î ╪º╪╣╪»╪º╪»╪î ╪«╪╖ ╪¬█î╪▒┘ç ΓÇö ┘à╪½╪º┘ä: NEWUSER20)",
            back_button("admin:discounts"))
        return

    if data.startswith("admin:disc:add_type:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        disc_type = data.split(":")[3]
        sd = state_data(uid)
        state_set(uid, "admin_discount_add_value",
                  code=sd.get("code", ""), disc_type=disc_type)
        bot.answer_callback_query(call.id)
        if disc_type == "pct":
            send_or_edit(call,
                "≡ƒÄƒ <b>╪º┘ü╪▓┘ê╪»┘å ┌⌐╪» ╪¬╪«┘ü█î┘ü</b>\n\n"
                "┘à╪▒╪¡┘ä┘ç █▓/█┤: ┘à┘é╪»╪º╪▒ ╪¬╪«┘ü█î┘ü ╪▒╪º ╪¿┘ç <b>╪»╪▒╪╡╪»</b> ┘ê╪º╪▒╪» ┌⌐┘å█î╪» (█▒ ╪¬╪º █▒█░█░):",
                back_button("admin:disc:add"))
        else:
            send_or_edit(call,
                "≡ƒÄƒ <b>╪º┘ü╪▓┘ê╪»┘å ┌⌐╪» ╪¬╪«┘ü█î┘ü</b>\n\n"
                "┘à╪▒╪¡┘ä┘ç █▓/█┤: ┘à┘é╪»╪º╪▒ ╪¬╪«┘ü█î┘ü ╪▒╪º ╪¿┘ç <b>╪¬┘ê┘à╪º┘å</b> ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
                back_button("admin:disc:add"))
        return

    if data.startswith("admin:disc:view:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _render_discount_code_detail(call, uid, code_id)
        return

    if data.startswith("admin:disc:toggle:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        toggle_discount_code(code_id)
        bot.answer_callback_query(call.id, "┘ê╪╢╪╣█î╪¬ ╪¬╪║█î█î╪▒ █î╪º┘ü╪¬.")
        _render_discount_code_detail(call, uid, code_id)
        return

    if data.startswith("admin:disc:del:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        if not row:
            bot.answer_callback_query(call.id, "┌⌐╪» ┘╛█î╪»╪º ┘å╪┤╪».", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("≡ƒùæ ╪¿┘ä┘ç╪î ╪¡╪░┘ü ┌⌐┘å", callback_data=f"admin:disc:del_confirm:{code_id}"),
            types.InlineKeyboardButton("Γ¥î ┘ä╪║┘ê", callback_data=f"admin:disc:view:{code_id}"),
        )
        send_or_edit(call,
            f"≡ƒùæ <b>╪¡╪░┘ü ┌⌐╪» ╪¬╪«┘ü█î┘ü</b>\n\n"
            f"╪ó█î╪º ╪º╪▓ ╪¡╪░┘ü ┌⌐╪» <code>{esc(row['code'])}</code> ┘à╪╖┘à╪ª┘å ┘ç╪│╪¬█î╪»╪ƒ",
            kb)
        return

    if data.startswith("admin:disc:del_confirm:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        delete_discount_code(code_id)
        log_admin_action(uid, f"┌⌐╪» ╪¬╪«┘ü█î┘ü #{code_id} ╪¡╪░┘ü ╪┤╪»")
        bot.answer_callback_query(call.id, "Γ£à ┌⌐╪» ╪¡╪░┘ü ╪┤╪».")
        _render_discount_admin_list(call, uid)
        return

    if data.startswith("admin:disc:edit_code:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_code", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ┌⌐╪» ╪¬╪«┘ü█î┘ü</b>\n\n┘à╪¬┘å ╪¼╪»█î╪» ┌⌐╪» ╪¬╪«┘ü█î┘ü ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_val:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        row = get_discount_code(code_id)
        type_fa = "╪»╪▒╪╡╪»" if row and row["discount_type"] == "pct" else "╪¬┘ê┘à╪º┘å"
        state_set(uid, f"admin_discount_edit_val", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ┘à┘é╪»╪º╪▒ ╪¬╪«┘ü█î┘ü</b>\n\n"
            f"┘å┘ê╪╣ ╪¬╪«┘ü█î┘ü: {type_fa}\n\n"
            "┘à┘é╪»╪º╪▒ ╪¼╪»█î╪» ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪»:",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_total:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_total", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ╪¡╪»╪º┌⌐╪½╪▒ ╪º╪│╪¬┘ü╪º╪»┘ç ┌⌐┘ä</b>\n\n"
            "╪¬╪╣╪»╪º╪» ╪¼╪»█î╪» ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪» (█░ = ┘å╪º┘à╪¡╪»┘ê╪»):",
            back_button(f"admin:disc:view:{code_id}"))
        return

    if data.startswith("admin:disc:edit_per:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        code_id = int(data.split(":")[3])
        state_set(uid, f"admin_discount_edit_per", edit_id=code_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "Γ£Å∩╕Å <b>┘ê█î╪▒╪º█î╪┤ ╪¡╪»╪º┌⌐╪½╪▒ ╪º╪│╪¬┘ü╪º╪»┘ç ┘ç╪▒ ┌⌐╪º╪▒╪¿╪▒</b>\n\n"
            "╪¬╪╣╪»╪º╪» ╪¼╪»█î╪» ╪▒╪º ┘ê╪º╪▒╪» ┌⌐┘å█î╪» (█░ = ┘å╪º┘à╪¡╪»┘ê╪»):",
            back_button(f"admin:disc:view:{code_id}"))
        return

    # ΓöÇΓöÇ Admin: Payment approve/reject ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data.startswith("adm:pay:ap:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "╪¬╪▒╪º┌⌐┘å╪┤ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "╪º█î┘å ╪¬╪▒╪º┌⌐┘å╪┤ ┘é╪¿┘ä╪º┘ï ╪¿╪▒╪▒╪│█î ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        user_row    = get_user(payment["user_id"])
        package_row = get_package(payment["package_id"]) if payment["package_id"] else None
        kind_label  = "╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä" if payment["kind"] == "wallet_charge" else "╪«╪▒█î╪» ┌⌐╪º┘å┘ü█î┌»"
        pkg_text    = ""
        if package_row:
            pkg_text = (
                f"\n≡ƒº⌐ ┘å┘ê╪╣: {esc(package_row['type_name'])}"
                f"\n≡ƒôª ┘╛┌⌐█î╪¼: {esc(package_row['name'])}"
                f"\n≡ƒöï ╪¡╪¼┘à: {fmt_vol(package_row['volume_gb'])} | ΓÅ░ {fmt_dur(package_row['duration_days'])}"
            )
        text = (
            f"Γ£à <b>╪¬╪ú█î█î╪» ╪¬╪▒╪º┌⌐┘å╪┤</b>\n\n"
            f"≡ƒº╛ ┘å┘ê╪╣: {kind_label}\n"
            f"≡ƒæñ ┌⌐╪º╪▒╪¿╪▒: {esc(user_row['full_name'] if user_row else '-')}\n"
            f"≡ƒåö ╪ó█î╪»█î: <code>{payment['user_id']}</code>\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(payment['amount'])}</b> ╪¬┘ê┘à╪º┘å"
            f"{pkg_text}\n\n"
            f"≡ƒô¥ ┘╛█î╪º┘à ╪¿╪▒╪º█î ┌⌐╪º╪▒╪¿╪▒ ╪▒╪º ╪¬╪º█î┘╛ ┌⌐┘å█î╪»╪î █î╪º ╪»┌⌐┘à┘çΓÇî█î ╪▓█î╪▒ ╪▒╪º ╪¿╪▓┘å█î╪»:"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Γ£à ╪¬╪ú█î█î╪» ╪¿╪»┘ê┘å ╪¬┘ê╪╢█î╪¡╪º╪¬", callback_data=f"adm:pay:apc:{payment_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪º┘å╪╡╪▒╪º┘ü", callback_data="nav:admin:panel"))
        state_set(uid, "admin_payment_approve_note", payment_id=payment_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:pay:apc:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "╪¬╪▒╪º┌⌐┘å╪┤ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "╪º█î┘å ╪¬╪▒╪º┌⌐┘å╪┤ ┘é╪¿┘ä╪º┘ï ╪¿╪▒╪▒╪│█î ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        state_clear(uid)
        finish_card_payment_approval(payment_id, "┘ê╪º╪▒█î╪▓█î ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪».", approved=True)
        bot.answer_callback_query(call.id, "Γ£à ╪¬╪ú█î█î╪» ╪┤╪».")
        send_or_edit(call, "Γ£à ╪¬╪▒╪º┌⌐┘å╪┤ ╪¿╪º ┘à┘ê┘ü┘é█î╪¬ ╪¬╪ú█î█î╪» ╪┤╪».", kb_admin_panel(uid))
        return

    if data.startswith("adm:pay:rj:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "╪¬╪▒╪º┌⌐┘å╪┤ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "╪º█î┘å ╪¬╪▒╪º┌⌐┘å╪┤ ┘é╪¿┘ä╪º┘ï ╪¿╪▒╪▒╪│█î ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        user_row   = get_user(payment["user_id"])
        package_row = get_package(payment["package_id"]) if payment["package_id"] else None
        kind_label = "╪┤╪º╪▒┌ÿ ┌⌐█î┘ü ┘╛┘ê┘ä" if payment["kind"] == "wallet_charge" else "╪«╪▒█î╪» ┌⌐╪º┘å┘ü█î┌»"
        pkg_text   = ""
        if package_row:
            pkg_text = (
                f"\n≡ƒº⌐ ┘å┘ê╪╣: {esc(package_row['type_name'])}"
                f"\n≡ƒôª ┘╛┌⌐█î╪¼: {esc(package_row['name'])}"
                f"\n≡ƒöï ╪¡╪¼┘à: {fmt_vol(package_row['volume_gb'])} | ΓÅ░ {fmt_dur(package_row['duration_days'])}"
            )
        text = (
            f"Γ¥î <b>╪▒╪» ╪¬╪▒╪º┌⌐┘å╪┤</b>\n\n"
            f"≡ƒº╛ ┘å┘ê╪╣: {kind_label}\n"
            f"≡ƒæñ ┌⌐╪º╪▒╪¿╪▒: {esc(user_row['full_name'] if user_row else '-')}\n"
            f"≡ƒåö ╪ó█î╪»█î: <code>{payment['user_id']}</code>\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(payment['amount'])}</b> ╪¬┘ê┘à╪º┘å"
            f"{pkg_text}\n\n"
            f"≡ƒô¥ ╪»┘ä█î┘ä ╪▒╪» ╪▒╪º ╪¬╪º█î┘╛ ┌⌐┘å█î╪»╪î █î╪º ╪»┌⌐┘à┘çΓÇî█î ╪▓█î╪▒ ╪▒╪º ╪¿╪▓┘å█î╪»:"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Γ¥î ╪▒╪» ╪¿╪»┘ê┘å ╪¬┘ê╪╢█î╪¡╪º╪¬", callback_data=f"adm:pay:rjc:{payment_id}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪º┘å╪╡╪▒╪º┘ü", callback_data="nav:admin:panel"))
        state_set(uid, "admin_payment_reject_note", payment_id=payment_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call, text, kb)
        return

    if data.startswith("adm:pay:rjc:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        payment_id = int(data.split(":")[3])
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "╪¬╪▒╪º┌⌐┘å╪┤ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        if payment["status"] not in ("pending",):
            bot.answer_callback_query(call.id, "╪º█î┘å ╪¬╪▒╪º┌⌐┘å╪┤ ┘é╪¿┘ä╪º┘ï ╪¿╪▒╪▒╪│█î ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        state_clear(uid)
        finish_card_payment_approval(payment_id, "╪▒╪│█î╪» ╪┤┘à╪º ╪▒╪» ╪┤╪».", approved=False)
        bot.answer_callback_query(call.id, "Γ¥î ╪▒╪» ╪┤╪».")
        send_or_edit(call, "Γ¥î ╪¬╪▒╪º┌⌐┘å╪┤ ╪▒╪» ╪┤╪».", kb_admin_panel(uid))
        return

    # ΓöÇΓöÇ Admin: Pending receipts panel ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:pr" or data.startswith("admin:pr:list:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
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
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "╪¬╪▒╪º┌⌐┘å╪┤ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        user_row    = get_user(payment["user_id"])
        package_row = get_package(payment["package_id"]) if payment["package_id"] else None
        kind_label  = {"wallet_charge": "╪┤╪º╪▒┌ÿ ┌⌐█î┘üΓÇî┘╛┘ê┘ä", "buy": "╪«╪▒█î╪» ┌⌐╪º┘å┘ü█î┌»", "renew": "╪¬┘à╪»█î╪» ┌⌐╪º┘å┘ü█î┌»"}.get(
            payment["kind"], payment["kind"]
        )
        pkg_text = ""
        if package_row:
            pkg_text = (
                f"\n≡ƒº⌐ ┘å┘ê╪╣: {esc(package_row['type_name'])}"
                f"\n≡ƒôª ┘╛┌⌐█î╪¼: {esc(package_row['name'])}"
                f"\n≡ƒöï ╪¡╪¼┘à: {fmt_vol(package_row['volume_gb'])} | ΓÅ░ {fmt_dur(package_row['duration_days'])}"
            )
        receipt_note = esc(payment["receipt_text"] or "ΓÇö")
        uname = "@" + esc(user_row["username"]) if (user_row and user_row["username"]) else "ΓÇö"
        text = (
            f"≡ƒôï <b>╪¼╪▓╪ª█î╪º╪¬ ╪▒╪│█î╪» #{payment_id}</b>\n\n"
            f"≡ƒº╛ ┘å┘ê╪╣: <b>{kind_label}</b>\n"
            f"≡ƒæñ ┌⌐╪º╪▒╪¿╪▒: {esc(user_row['full_name'] if user_row else 'ΓÇö')}\n"
            f"≡ƒåö ╪ó█î╪»█î: <code>{payment['user_id']}</code>\n"
            f"≡ƒô₧ █î┘ê╪▓╪▒┘å█î┘à: {uname}\n"
            f"≡ƒÆ░ ┘à╪¿┘ä╪║: <b>{fmt_price(payment['amount'])}</b> ╪¬┘ê┘à╪º┘å\n"
            f"≡ƒÆ│ ╪▒┘ê╪┤ ┘╛╪▒╪»╪º╪«╪¬: {esc(payment['payment_method'])}"
            f"{pkg_text}\n\n"
            f"≡ƒô¥ ╪¬┘ê╪╢█î╪¡╪º╪¬ ┘à╪┤╪¬╪▒█î: {receipt_note}\n"
            f"≡ƒòÉ ╪½╪¿╪¬ ╪┤╪»┘ç: {payment['created_at']}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("Γ£à ╪¬╪ú█î█î╪» ╪▒╪│█î╪»", callback_data=f"admin:pr:ap:{payment_id}:{page}"),
            types.InlineKeyboardButton("Γ¥î ╪▒╪» ╪▒╪│█î╪»",    callback_data=f"admin:pr:rj:{payment_id}:{page}"),
        )
        kb.add(types.InlineKeyboardButton("≡ƒöÖ ╪¿╪º╪▓┌»╪┤╪¬ ╪¿┘ç ┘ä█î╪│╪¬", callback_data=f"admin:pr:list:{page}"))
        file_id = payment["receipt_file_id"]
        if file_id:
            try:
                bot.send_photo(uid, file_id, caption="≡ƒû╝ ╪▒╪│█î╪» ┌⌐╪º╪▒╪¿╪▒")
            except Exception:
                try:
                    bot.send_document(uid, file_id, caption="≡ƒôÄ ╪▒╪│█î╪» ┌⌐╪º╪▒╪¿╪▒")
                except Exception:
                    pass
        send_or_edit(call, text, kb)
        return

    if data.startswith("admin:pr:ap:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "╪¬╪▒╪º┌⌐┘å╪┤ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "╪º█î┘å ╪¬╪▒╪º┌⌐┘å╪┤ ┘é╪¿┘ä╪º┘ï ╪¿╪▒╪▒╪│█î ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        finish_card_payment_approval(payment_id, "┘ê╪º╪▒█î╪▓█î ╪┤┘à╪º ╪¬╪ú█î█î╪» ╪┤╪».", approved=True)
        bot.answer_callback_query(call.id, "Γ£à ╪¬╪ú█î█î╪» ╪┤╪».")
        _render_pending_receipts_page(call, uid, page)
        return

    if data.startswith("admin:pr:rj:"):
        if not admin_has_perm(uid, "approve_payments"):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        parts      = data.split(":")
        payment_id = int(parts[3])
        page       = int(parts[4]) if len(parts) > 4 else 0
        payment    = get_payment(payment_id)
        if not payment:
            bot.answer_callback_query(call.id, "╪¬╪▒╪º┌⌐┘å╪┤ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        if payment["status"] != "pending":
            bot.answer_callback_query(call.id, "╪º█î┘å ╪¬╪▒╪º┌⌐┘å╪┤ ┘é╪¿┘ä╪º┘ï ╪¿╪▒╪▒╪│█î ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        finish_card_payment_approval(payment_id, "╪▒╪│█î╪» ╪┤┘à╪º ╪▒╪» ╪┤╪».", approved=False)
        bot.answer_callback_query(call.id, "Γ¥î ╪▒╪» ╪┤╪».")
        _render_pending_receipts_page(call, uid, page)
        return

    if data.startswith("adm:pending:addcfg:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        pending_id = int(data.split(":")[3])
        p_row = get_pending_order(pending_id)
        if not p_row:
            bot.answer_callback_query(call.id, "╪│┘ü╪º╪▒╪┤ █î╪º┘ü╪¬ ┘å╪┤╪».", show_alert=True)
            return
        if p_row["status"] == "fulfilled":
            bot.answer_callback_query(call.id, "╪º█î┘å ╪│┘ü╪º╪▒╪┤ ┘é╪¿┘ä╪º┘ï ╪¬┌⌐┘à█î┘ä ╪┤╪»┘ç ╪º╪│╪¬.", show_alert=True)
            return
        state_set(uid, "admin_pending_cfg_name", pending_id=pending_id)
        bot.answer_callback_query(call.id)
        pkg = get_package(p_row["package_id"])
        pkg_info = ""
        if pkg:
            pkg_info = (
                f"\n\n≡ƒôª <b>╪º╪╖┘ä╪º╪╣╪º╪¬ ┘╛┌⌐█î╪¼:</b>\n"
                f"≡ƒº⌐ ┘å┘ê╪╣: {esc(pkg['type_name'])}\n"
                f"Γ£Å∩╕Å ┘å╪º┘à: {esc(pkg['name'])}\n"
                f"≡ƒöï ╪¡╪¼┘à: {fmt_vol(pkg['volume_gb'])}\n"
                f"ΓÅ░ ┘à╪»╪¬: {fmt_dur(pkg['duration_days'])}\n"
                f"≡ƒÆ░ ┘é█î┘à╪¬: {fmt_price(pkg['price'])} ╪¬┘ê┘à╪º┘å"
            )
        send_or_edit(call,
            f"≡ƒô¥ <b>╪½╪¿╪¬ ┌⌐╪º┘å┘ü█î┌» ╪¿╪▒╪º█î ╪│┘ü╪º╪▒╪┤ #{pending_id}</b>{pkg_info}\n\n"
            "┘ä╪╖┘ü╪º┘ï <b>┘å╪º┘à ╪│╪▒┘ê█î╪│</b> ╪▒╪º ╪º╪▒╪│╪º┘ä ┌⌐┘å█î╪»:",
            back_button("admin:panel"))
        return

    # ΓöÇΓöÇ 3x-ui Panel management ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if data == "admin:panels":
        if not is_admin(uid) or not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _show_admin_panels(call)
        return

    if data == "adm:panel:add":
        if not is_admin(uid) or not (uid in ADMIN_IDS or admin_has_perm(uid, "manage_panels")):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "panel_add_name")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒûÑ <b>Register Panel Config</b>\n\nStep 1/5: Enter Panel <b>Name</b>:",
            back_button("admin:panels"))
        return

    if data.startswith("adm:panel:pkgs:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        panel_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _show_panel_packages(call, panel_id)
        return

    if data.startswith("adm:panel:pkadd:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        panel_id = int(data.split(":")[3])
        state_set(uid, "panel_pkg_add_name", panel_id=panel_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒôª <b>Add Traffic Package</b>\n\nStep 1/3: Enter Package <b>Name</b>:",
            back_button("admin:panels"))
        return

    if data.startswith("adm:panel:pkdel:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        pp_id = int(data.split(":")[3])
        pp = get_panel_package(pp_id)
        if not pp:
            bot.answer_callback_query(call.id, "Package not found.", show_alert=True)
            return
        delete_panel_package(pp_id)
        bot.answer_callback_query(call.id, "Γ£à Package deleted.")
        log_admin_action(uid, f"┘╛┌⌐█î╪¼ ┘╛┘å┘ä #{pp_id} ╪º╪▓ ┘╛┘å┘ä #{pp['panel_id']} ╪¡╪░┘ü ╪┤╪»")
        _show_panel_packages(call, pp["panel_id"])
        return

    if data.startswith("adm:panel:edit:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        panel_id = int(data.split(":")[3])
        bot.answer_callback_query(call.id)
        _show_panel_edit(call, panel_id)
        return

    if data.startswith("adm:panel:ef:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        parts    = data.split(":")
        field    = parts[3]
        panel_id = int(parts[4])
        state_set(uid, "panel_edit_field", field=field, panel_id=panel_id)
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"Γ£Å∩╕Å Enter new value for <b>{field}</b>:",
            back_button("admin:panels"))
        return

    if data.startswith("adm:panel:toggle:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        parts    = data.split(":")
        panel_id = int(parts[3])
        new_val  = int(parts[4])
        update_panel_field(panel_id, "is_active", new_val)
        log_admin_action(uid, f"┘╛┘å┘ä #{panel_id} {'┘ü╪╣╪º┘ä' if new_val else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "Γ£à Updated.")
        _show_panel_edit(call, panel_id)
        return

    if data.startswith("adm:panel:del:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        panel_id = int(data.split(":")[3])
        panel    = get_panel(panel_id)
        if not panel:
            bot.answer_callback_query(call.id, "Panel not found.", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("Γ£à Yes, Delete", callback_data=f"adm:panel:delok:{panel_id}"),
            types.InlineKeyboardButton("Γ¥î Cancel",      callback_data="admin:panels"),
        )
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            f"ΓÜá∩╕Å Delete panel <b>{esc(panel['name'])}</b>?\n"
            "All packages and jobs linked to it will also be removed.", kb)
        return

    if data.startswith("adm:panel:delok:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        panel_id = int(data.split(":")[3])
        delete_panel(panel_id)
        bot.answer_callback_query(call.id, "Γ£à Panel deleted.")
        log_admin_action(uid, f"┘╛┘å┘ä #{panel_id} ╪¡╪░┘ü ╪┤╪»")
        _show_admin_panels(call)
        return

    if data == "adm:panel:api_settings":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        current_key     = setting_get("worker_api_key", "")
        current_port    = setting_get("worker_api_port", "8080")
        current_enabled = setting_get("worker_api_enabled", "0")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("≡ƒöæ Set API Key",  callback_data="adm:panel:set_api_key"))
        kb.add(types.InlineKeyboardButton("≡ƒöî Set API Port", callback_data="adm:panel:set_api_port"))
        toggle_lbl = "≡ƒö┤ Disable API" if current_enabled == "1" else "≡ƒƒó Enable API"
        new_enabled = "0" if current_enabled == "1" else "1"
        kb.add(types.InlineKeyboardButton(toggle_lbl, callback_data=f"adm:panel:api_toggle:{new_enabled}"))
        kb.add(types.InlineKeyboardButton("≡ƒöÖ Back", callback_data="admin:panels"))
        bot.answer_callback_query(call.id)
        masked_key = (current_key[:6] + "ΓÇª") if current_key else "(not set)"
        send_or_edit(call,
            "ΓÜÖ∩╕Å <b>Worker API Settings</b>\n\n"
            f"≡ƒöæ API Key: <code>{masked_key}</code>\n"
            f"≡ƒöî Port: <code>{current_port}</code>\n"
            f"Status: {'≡ƒƒó Enabled' if current_enabled == '1' else '≡ƒö┤ Disabled'}\n\n"
            "Share the API Key with your Iran Worker's config.env",
            kb)
        return

    if data.startswith("adm:panel:api_toggle:"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        new_val = data.split(":")[3]
        setting_set("worker_api_enabled", new_val)
        log_admin_action(uid, f"Worker API {'┘ü╪╣╪º┘ä' if new_val == '1' else '╪║█î╪▒┘ü╪╣╪º┘ä'} ╪┤╪»")
        bot.answer_callback_query(call.id, "Γ£à Updated.")
        _fake_call(call, "adm:panel:api_settings")
        return

    if data == "adm:panel:set_api_key":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "panel_set_api_key")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöæ Enter new <b>Worker API Key</b>:\n(min 16 characters, letters and digits only)",
            back_button("admin:panels"))
        return

    if data == "adm:panel:set_api_port":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "╪»╪│╪¬╪▒╪│█î ┘à╪¼╪º╪▓ ┘å█î╪│╪¬.", show_alert=True)
            return
        state_set(uid, "panel_set_api_port")
        bot.answer_callback_query(call.id)
        send_or_edit(call,
            "≡ƒöî Enter new <b>API Server Port</b> (default 8080):",
            back_button("admin:panels"))
        return

    if data == "noop":
        bot.answer_callback_query(call.id)
        return

    bot.answer_callback_query(call.id)

