# -*- coding: utf-8 -*-
import os
import traceback
import sqlite3
import threading
import time
import urllib.parse
from datetime import datetime
from telebot import types
from ..config import ADMIN_IDS, ADMIN_PERMS, PERM_FULL_SET, CONFIGS_PER_PAGE, DB_NAME
from ..bot_instance import bot
from ..helpers import (
    esc, fmt_price, fmt_vol, fmt_dur, now_str, display_name, display_username,
    is_admin, admin_has_perm, back_button,
    state_set, state_clear, state_name, state_data, parse_int, parse_volume, normalize_text_number,
    normalize_iranian_phone,
    validate_service_name, normalize_service_name, generate_random_name, parse_bulk_names,
)
from ..db import (
    setting_get, setting_set,
    ensure_user, get_user, get_users, set_user_status,
    set_user_agent, update_balance, get_user_purchases, get_purchase,
    get_all_types, get_active_types, get_packages, get_package, add_package, update_package_field, delete_package,
    add_type, update_type, update_type_description, delete_type, reorder_type,
    get_registered_packages_stock, get_configs_paginated, count_configs,
    expire_config, add_config,
    assign_config_to_user, reserve_first_config,
    get_payment, create_payment, approve_payment, reject_payment, complete_payment,
    update_payment_receipt,
    get_agency_price, set_agency_price,
    get_agency_price_config, set_agency_price_config,
    get_agency_type_discount, set_agency_type_discount,
    get_all_admin_users, get_admin_user, add_admin_user, update_admin_permissions, remove_admin_user,
    get_conn, create_pending_order, get_pending_order, search_users,
    notify_first_start_if_needed, update_config_field,
    add_pinned_message, update_pinned_message,
    save_pinned_send, get_pinned_sends,
    save_agency_request_message,
    get_discount_code, add_discount_code, update_discount_code_field,
    validate_discount_code, record_discount_usage, has_eligible_discount_codes,
    add_voucher_batch, get_voucher_code_by_code, redeem_voucher_code,
    set_phone_number, get_phone_number,
    get_bulk_qty_limits,
    get_panel_client_package,
    update_panel_client_package_field,
    bulk_add_balance, bulk_zero_balance, bulk_set_status, count_users_by_filter,
    set_user_restricted, check_and_release_restriction,
    get_wallet_pay_exceptions, add_wallet_pay_exception,
    add_referral_restriction,
    add_payment_card, update_payment_card,
    set_per_gb_price,
    create_reseller_request, get_reseller_request,
)
from ..gateways.base import is_gateway_available, is_card_info_complete, get_global_amount_range, get_gateway_range_text, is_gateway_in_range, build_gateway_range_guide
from ..gateways.tetrapay import create_tetrapay_order, verify_tetrapay_order
from ..ui.helpers import send_or_edit, check_channel_membership, channel_lock_message
from ..ui.keyboards import kb_main, kb_admin_panel
from ..ui.menus import show_main_menu, show_profile, show_support, show_my_configs
from ..ui.notifications import (
    deliver_purchase_message, admin_purchase_notify, admin_renewal_notify,
    notify_pending_order_to_admins, _complete_pending_order, auto_fulfill_pending_orders,
)
from ..payments import (
    get_effective_price, show_payment_method_selection,
    show_crypto_selection, show_crypto_payment_info,
    send_payment_to_admins, finish_card_payment_approval,
)
from ..group_manager import send_to_topic, get_group_id, log_admin_action
from ..admin.renderers import (
    _show_admin_types, _show_admin_stock, _show_admin_admins_panel,
    _show_perm_selection, _show_admin_users_list, _show_admin_user_detail,
    _show_admin_user_detail_msg, _show_admin_assign_config_type, _fake_call,
)
from .callbacks import (
    _DISCOUNT_PROMPT_TEXT, _show_discount_prompt,
    _show_purchase_gateways, _show_renewal_gateways, _show_wallet_gateways,
    _render_discount_admin_list, _render_discount_code_detail,
    _generate_voucher_codes, _render_voucher_admin_list, _render_voucher_batch_detail,
    _ovpn_finish_single, _ovpn_deliver_bulk_shared, _ovpn_deliver_bulk_diff,
    _ovpn_send_file_group, _ovpn_caption, _fmt_users_label,
    _wg_finish_single, _wg_deliver_bulk_shared, _wg_deliver_bulk_diff,
    _wg_send_file_group, _wg_caption, _wg_service_name_from_filename,
    _wg_extract_name_from_text, _wg_upload_conf,
    _qty_order_summary_text,
    _v2_name_from_config, _v2_name_from_sub, _v2_bulk_data_prompt,
    _is_panel_package, _show_naming_prompt,
)

# ── Popup dispatch: suppress answer_callback_query for fake calls ─────────────
# When a popup-mode menu button is pressed, the bot receives a text message and
# routes it as a fake callback. Since there's no real callback query ID,
# answer_callback_query would throw an ApiTelegramException and abort the handler
# before any content is sent. We use a thread-local flag to suppress those calls.
_popup_suppress_acq = threading.local()
_popup_acq_orig = bot.answer_callback_query


def _popup_patched_acq(cq_id, *a, **kw):
    if getattr(_popup_suppress_acq, 'active', False):
        # If the call carries an alert text, forward it as a regular message
        # so the user isn't left without feedback in popup mode.
        _text = kw.get('text') or (a[0] if a else None)
        if _text:
            _cid = getattr(_popup_suppress_acq, 'chat_id', None)
            if _cid:
                try:
                    bot.send_message(_cid, str(_text))
                except Exception:
                    pass
        return None
    return _popup_acq_orig(cq_id, *a, **kw)


bot.answer_callback_query = _popup_patched_acq


# ── Broadcast helpers ──────────────────────────────────────────────────────────


def _parse_type_emoji(text_in, entities):
    """Parse admin-entered emoji input for config type buttons.

    Returns the emoji value to store:
      - "" if text is 'ندارد' or empty
      - <tg-emoji> HTML tag if a custom_emoji entity is present or text is numeric ID
      - plain text (emoji char) otherwise
    """
    import re as _re2
    from ..ui.premium_emoji import serialize_premium_text as _spte
    if not text_in or text_in in ("ندارد", "none", "بدون"):
        return ""
    # Numeric ID → wrap as tg-emoji tag
    if text_in.isdigit():
        return f'<tg-emoji emoji-id="{text_in}">🔹</tg-emoji>'
    # Already a tg-emoji HTML tag
    if text_in.startswith("<tg-emoji"):
        return text_in
    # Has custom_emoji entity → serialize with entity info
    if any(getattr(e, "type", None) == "custom_emoji" for e in (entities or [])):
        return _spte(text_in, entities)
    # Plain text / plain emoji
    return text_in

def _bc_progress_text(title: str, total: int, done: int, ok: int, fail: int) -> str:
    bar_fill = 10
    filled = int(done / total * bar_fill) if total > 0 else 0
    bar = "▓" * filled + "░" * (bar_fill - filled)
    pct = (done / total * 100) if total > 0 else 0.0
    from ..helpers import now_str as _now_str
    return (
        f"📊 <b>وضعیت {title}</b>\n\n"
        f"🚀 پیام شما به <b>{total}</b> نفر ارسال می‌شود.\n"
        f"📊 {bar} {pct:.1f}% {done}/{total}\n"
        f"✅ موفق: <b>{ok}</b> | ❌ ناموفق: <b>{fail}</b>\n"
        f"🕚 {_now_str()}"
    )


def _bc_source(message):
    """Return (from_chat_id, msg_id) for broadcast.
    If the admin forwarded a channel post, use the original channel as source
    so forward_message shows 'Forwarded from [channel]' and counts channel views.
    """
    if (message.forward_from_chat and
            message.forward_from_message_id and
            message.forward_from_chat.id < 0):
        return message.forward_from_chat.id, message.forward_from_message_id
    return message.chat.id, message.message_id


def _do_broadcast(user_ids: list, title: str, mode: str,
                  admin_uid: int, from_chat_id: int, msg_id: int,
                  reply_markup, progress_msg_id: int) -> None:
    """Background thread: broadcast/pin message to list of user IDs.
    mode: 'forward' | 'pin'
    """
    total = len(user_ids)
    done = ok = fail = 0
    last_edit = time.time()

    def _upd():
        nonlocal last_edit
        try:
            bot.edit_message_text(
                _bc_progress_text(title, total, done, ok, fail),
                admin_uid, progress_msg_id, parse_mode="HTML")
            last_edit = time.time()
        except Exception:
            pass

    # If the source is a channel message, use forward_message to preserve channel header/view counts
    _is_channel_src = isinstance(from_chat_id, int) and from_chat_id < 0

    for tgt_uid in user_ids:
        try:
            if _is_channel_src:
                sent_msg = bot.forward_message(tgt_uid, from_chat_id, msg_id)
            else:
                sent_msg = bot.copy_message(
                    tgt_uid, from_chat_id, msg_id, reply_markup=reply_markup)
            if mode == "pin" and sent_msg:
                try:
                    bot.pin_chat_message(
                        tgt_uid, sent_msg.message_id, disable_notification=True)
                except Exception:
                    pass
            ok += 1
        except Exception:
            fail += 1
        done += 1
        time.sleep(0.05)
        if done % 50 == 0 or (time.time() - last_edit) >= 5:
            _upd()

    # Final progress update
    from ..helpers import now_str as _now_str
    final_text = (
        f"📊 <b>وضعیت {title}</b>\n\n"
        f"🚀 پیام شما به <b>{total}</b> نفر ارسال شد.\n"
        f"📊 {'▓' * 10} 100.0% {total}/{total}\n"
        f"✅ موفق: <b>{ok}</b> | ❌ ناموفق: <b>{fail}</b>\n"
        f"🕚 {_now_str()}\n\n"
        f"✅ <b>عملیات پایان یافت.</b>"
    )
    try:
        bot.edit_message_text(final_text, admin_uid, progress_msg_id, parse_mode="HTML")
    except Exception:
        pass

    from ..group_manager import send_to_topic as _stt
    _stt("broadcast_report",
         f"📢 <b>{title}</b>\n\n"
         f"👤 ارسال‌کننده: <code>{admin_uid}</code>\n"
         f"✅ موفق: <b>{ok}</b> | ❌ ناموفق: <b>{fail}</b> | 📊 کل: <b>{total}</b>")


# ── V2Ray bulk helpers ─────────────────────────────────────────────────────────

def _v2_read_raw(message, uid) -> "str | None":
    """Read raw text from a message or .txt file attachment.
    Returns None if an error is shown to the admin.
    """
    if message.document:
        doc = message.document
        fname = (doc.file_name or "").lower()
        if not fname.endswith(".txt"):
            bot.send_message(uid,
                "⚠️ فقط فایل با فرمت <b>.txt</b> پشتیبانی می‌شود.",
                parse_mode="HTML")
            return None
        try:
            file_info = bot.get_file(doc.file_id)
            downloaded = bot.download_file(file_info.file_path)
            return downloaded.decode("utf-8", errors="ignore").strip()
        except Exception:
            bot.send_message(uid,
                "⚠️ خطا در دانلود فایل. لطفاً دوباره ارسال کنید.")
            return None
    raw = (message.text or "").strip()
    if not raw:
        bot.send_message(uid, "⚠️ متنی ارسال نشده.")
        return None
    return raw


def _v2_save_bulk(uid, type_id, package_id, pairs, mode, prefix, suffix, pending_id=None):
    """Save a list of (config_text, sub_url) pairs as V2Ray configs.

    mode 1 — config+sub interleaved
    mode 2 — config+sub index-paired (large)
    mode 3 — config only
    mode 4 — sub only
    """
    success_count = 0
    success_names = []
    errors = []

    for idx, (cfg_text, sub_link) in enumerate(pairs, 1):
        cfg_text  = (cfg_text  or "").strip()
        sub_link  = (sub_link  or "").strip()

        # Determine service name
        if mode == 4:
            svc_name = _v2_name_from_sub(sub_link) if sub_link else f"sub-{idx}"
        else:
            svc_name = _v2_name_from_config(cfg_text, prefix, suffix) if cfg_text else f"config-{idx}"

        if not svc_name:
            svc_name = f"item-{idx}"

        # Validate required fields
        if mode in (1, 2) and not cfg_text:
            errors.append(f"آیتم {idx}: کانفیگ خالی است")
            continue
        if mode in (1, 2) and not sub_link:
            # sub missing — still register with empty sub
            sub_link = ""
        if mode == 3 and not cfg_text:
            errors.append(f"آیتم {idx}: کانفیگ خالی است")
            continue
        if mode == 4 and not sub_link:
            errors.append(f"آیتم {idx}: ساب خالی است")
            continue

        try:
            add_config(type_id, package_id, svc_name, cfg_text, sub_link)
            success_count += 1
            success_names.append(svc_name)
        except Exception as e:
            errors.append(f"آیتم {idx}: {str(e)}")

    # Auto-fulfill pending orders
    auto_fulfilled = 0
    auto_fulfill_err = ""
    if success_count > 0:
        try:
            auto_fulfilled = auto_fulfill_pending_orders(package_id)
        except Exception as e:
            auto_fulfill_err = str(e)
        # If called from a specific pending-order flow, deliver that order directly
        if pending_id:
            try:
                from ..ui.notifications import _complete_pending_order as _cpo
                last_name = success_names[-1] if success_names else ""
                last_cfg  = pairs[-1][0] if pairs else ""
                last_sub  = pairs[-1][1] if pairs else ""
                _cpo(pending_id, last_name, last_cfg, last_sub)
            except Exception:
                pass

    state_clear(uid)
    mode_labels = {1: "کانفیگ + ساب (تعداد کم)", 2: "کانفیگ + ساب (تعداد زیاد)",
                   3: "کانفیگ تنها", 4: "ساب تنها"}
    mode_label = mode_labels.get(mode, "")

    if success_count > 0:
        log_admin_action(uid,
            f"{success_count} کانفیگ V2Ray دسته‌ای ({mode_label}) برای پکیج #{package_id} ثبت شد")

    result = (
        f"✅ <b>{success_count}</b> آیتم با موفقیت ثبت شد.\n"
        f"📌 نوع ثبت: {mode_label}"
    )
    if success_names:
        names_text = "\n".join(f"  • {esc(n)}" for n in success_names[:50])
        if len(success_names) > 50:
            names_text += f"\n  … و {len(success_names) - 50} مورد دیگر"
        result += f"\n\n📝 <b>نام سرویس‌های ثبت‌شده:</b>\n{names_text}"
    if auto_fulfilled > 0:
        result += f"\n\n🚀 <b>{auto_fulfilled}</b> سفارش در انتظار به‌صورت خودکار تحویل داده شد."
    if auto_fulfill_err:
        result += f"\n\n⚠️ خطا در تحویل سفارش‌های در انتظار:\n<code>{esc(auto_fulfill_err)}</code>"
    if errors:
        result += "\n\n❌ <b>خطاها:</b>\n" + "\n".join(errors[:20])
    bot.send_message(uid, result, parse_mode="HTML", reply_markup=kb_admin_panel())


def _send_codes_to_admin(admin_id, header, code_lines, chunk_size=3600):
    """Send header + list of code lines to admin, splitting at chunk_size if needed."""
    all_text = header + "\n".join(code_lines)
    if len(all_text) <= chunk_size:
        try:
            bot.send_message(admin_id, all_text, parse_mode="HTML")
        except Exception:
            pass
        return
    # Send header first, then codes in chunks
    try:
        bot.send_message(admin_id, header, parse_mode="HTML")
    except Exception:
        pass
    chunk = []
    cur_len = 0
    for line in code_lines:
        if cur_len + len(line) + 1 > chunk_size:
            try:
                bot.send_message(admin_id, "\n".join(chunk), parse_mode="HTML")
            except Exception:
                pass
            chunk, cur_len = [], 0
        chunk.append(line)
        cur_len += len(line) + 1
    if chunk:
        try:
            bot.send_message(admin_id, "\n".join(chunk), parse_mode="HTML")
        except Exception:
            pass


@bot.message_handler(content_types=["text", "photo", "document", "contact", "video", "animation", "voice", "audio", "video_note", "sticker"])
def universal_handler(message):
    uid    = message.from_user.id
    ensure_user(message.from_user)

    # ── Layer 8: License enforcement in universal handler ─────────────────────
    from ..license_manager import is_limited_mode as _is_limited
    if _is_limited() and not is_admin(uid):
        bot.send_message(
            message.chat.id,
            "🚫 ربات در حال حاضر غیرفعال است.",
        )
        return
    _u = get_user(uid)
    if _u:
        _u = check_and_release_restriction(_u)
    if _u and _u["status"] == "restricted" and not is_admin(uid):
        import time as _t
        _until = _u.get("restricted_until", 0)
        if _until and _until > 0:
            import datetime as _dt
            _exp = _dt.datetime.fromtimestamp(_until, tz=_dt.timezone.utc).astimezone(
                _dt.timezone(_dt.timedelta(hours=3, minutes=30)))
            _exp_str = _exp.strftime("%Y/%m/%d — %H:%M")
            _dur_txt = f"تا <b>{_exp_str}</b> نمی‌توانید از ربات استفاده کنید."
        else:
            _dur_txt = "<b>برای همیشه</b> نمی‌توانید از ربات استفاده کنید."
        _sup_raw  = setting_get("support_username", "")
        _sup_link = setting_get("support_link", "")
        _sup_url  = safe_support_url(_sup_raw) or (_sup_link if _sup_link else None)
        _sup_line = f"\n\n🎧 برای پیگیری رفع محدودیت به پشتیبانی پیام دهید:\n{_sup_url}" if _sup_url else \
                    "\n\n🎧 برای پیگیری رفع محدودیت با پشتیبانی در تماس باشید."
        bot.send_message(
            message.chat.id,
            f"🚫 <b>دسترسی شما محدود شده است</b>\n\n"
            f"⛔ به دلیل ارسال رسید جعلی، حساب شما محدود شد.\n"
            f"{_dur_txt}"
            f"{_sup_line}",
            parse_mode="HTML"
        )
        return

    # Bot status check for non-admins
    if not is_admin(uid):
        _bot_status = setting_get("bot_status", "on")
        if _bot_status == "off":
            return
        if _bot_status == "update":
            bot.send_message(
                message.chat.id,
                "🔄 <b>ربات در حال بروزرسانی است</b>\n\n"
                "فعلاً ربات در حال بروزرسانی می‌باشد، لطفاً بعداً اقدام نمایید. 🙏\n\n"
                "در صورتی که کار فوری دارید، می‌توانید با پشتیبانی در ارتباط باشید.",
                parse_mode="HTML"
            )
            return

    # Channel check
    if not check_channel_membership(uid):
        channel_lock_message(message)
        return

    # ── Referral captcha check ────────────────────────────────────────────────
    # Checked before the phone gate so the answer is always processed.
    # Only acts when there is a pending captcha AND the message is plain text.
    if message.text and not message.text.startswith("/"):
        from ..ui.notifications import (
            has_pending_captcha, verify_and_process_captcha, complete_referral_after_captcha,
            notify_referrer_captcha_failed,
        )
        if has_pending_captcha(uid):
            answer_text = message.text.strip()
            # Only consume the captcha if the message looks like a number; otherwise
            # let it fall through to the normal message dispatcher (captcha stays pending).
            if answer_text.lstrip("-").isdigit():
                correct = verify_and_process_captcha(uid, answer_text)
                if correct:
                    bot.send_message(
                        message.chat.id,
                        "✅ <b>احراز هویت با موفقیت انجام شد.</b>\n\n"
                        "دعوت شما به عنوان زیرمجموعه معتبر ثبت شد.",
                        parse_mode="HTML",
                    )
                    try:
                        complete_referral_after_captcha(uid)
                    except Exception:
                        pass
                else:
                    bot.send_message(
                        message.chat.id,
                        "❌ <b>پاسخ نادرست بود.</b>\n\n"
                        "زیرمجموعه برای دعوت‌کننده ثبت نشد، اما می‌توانید از ربات استفاده کنید.",
                        parse_mode="HTML",
                    )
                    try:
                        notify_referrer_captcha_failed(uid)
                    except Exception:
                        pass
                # Either way, let execution continue so the main menu is available
                return

    # Phone gate — enforce for all incoming messages, not just /start
    sn = state_name(uid)
    if not is_admin(uid) and sn not in ("waiting_for_phone", "waiting_for_phone_card",
                                        "await_purchase_receipt", "await_renewal_receipt", "await_wallet_receipt"):
        from ..handlers.start import _phone_required_for_user, _send_phone_request
        if _phone_required_for_user(uid):
            _send_phone_request(message.chat.id, uid)
            return

    sn = state_name(uid)
    sd = state_data(uid)

    # ── Popup menu routing ────────────────────────────────────────────────────
    # When start_menu_mode == "popup", the start menu is a ReplyKeyboardMarkup.
    # Button presses arrive as text messages. Always route them as navigation —
    # clear any active state so they act as an "escape" from mid-flow operations.
    # Exception: admin text-input states (admin_*) are never cleared by popup
    # buttons so the admin can type their content without accidentally navigating.
    if (message.content_type == "text"
            and setting_get("start_menu_mode", "inline") == "popup"):
        from ..ui.start_menu import find_button_callback_by_text
        _popup_cb = find_button_callback_by_text(message.text or "")
        if _popup_cb:
            # If we're in an admin-panel text-input state, don't intercept;
            # let the state handler below finish collecting the admin's input.
            if sn and sn.startswith("admin_"):
                pass  # fall through to the normal state handlers
            else:
                # Cancel any in-progress user operation before navigating
                if sn:
                    state_clear(uid)
                from .callbacks import _dispatch_callback as _dcb
                _src_user = message.from_user

                # Before dispatching, send a ReplyKeyboardRemove so the popup
                # bottom-keyboard is hidden for screens with inline buttons.
                # The bot's own dismiss message is used as the edit target so
                # send_or_edit can replace it cleanly instead of creating extra
                # messages. For nav:main the popup keyboard comes back on its own.
                _dismiss_msg = None
                if _popup_cb != "nav:main":
                    try:
                        _dismiss_msg = bot.send_message(
                            message.chat.id, "⏳",
                            reply_markup=types.ReplyKeyboardRemove(),
                            message_thread_id=getattr(message, "message_thread_id", None),
                        )
                    except Exception:
                        _dismiss_msg = None

                # Build a fake CallbackQuery; point .message at the dismiss msg
                # so send_or_edit can edit it (bots can edit their own messages).
                _target_msg = _dismiss_msg if _dismiss_msg else message

                class _FakeCQ:
                    id = "0"
                    from_user = _src_user
                    data = _popup_cb
                    message = _target_msg

                _popup_suppress_acq.active = True
                _popup_suppress_acq.chat_id = message.chat.id
                try:
                    _dcb(_FakeCQ(), uid, _popup_cb)
                finally:
                    _popup_suppress_acq.active = False
                    _popup_suppress_acq.chat_id = None
                return

    try:
        # ── My Configs search ─────────────────────────────────────────────────
        if sn == "my_cfgs_search":
            query = (message.text or "").strip()
            state_clear(uid)
            if not query or query in ("/cancel", "لغو"):
                show_my_configs(message, uid, page=0)
            else:
                show_my_configs(message, uid, page=0, search=query)
            return

        # ── License activation state — step 1: API Key ───────────────────────
        if sn == "license:waiting_api_key" and is_admin(uid):
            text = (message.text or "").strip()
            if text in ("/cancel", "لغو"):
                state_clear(uid)
                bot.send_message(message.chat.id, "❌ فعال‌سازی لغو شد.")
                return
            api_key = text
            # Move to step 2: ask for API URL
            from ..license_manager import API_URL_PROMPT_TEXT
            state_set(uid, "license:waiting_api_url", pending_api_key=api_key)
            bot.send_message(message.chat.id, API_URL_PROMPT_TEXT, parse_mode="HTML")
            return

        # ── License activation state — step 2: API URL ───────────────────────
        if sn == "license:waiting_api_url" and is_admin(uid):
            text = (message.text or "").strip()
            if text in ("/cancel", "لغو"):
                state_clear(uid)
                bot.send_message(message.chat.id, "❌ فعال‌سازی لغو شد.")
                return
            api_url = text
            api_key = state_data(uid).get("pending_api_key", "")
            state_clear(uid)
            from ..license_manager import (
                activate_license, get_or_create_machine_id,
                ACTIVATION_SUCCESS_TEXT, ACTIVATION_FAIL_TEXT,
            )
            get_or_create_machine_id()
            bot_username = ""
            try:
                me = bot.get_me()
                bot_username = me.username or ""
            except Exception:
                pass
            bot.send_message(message.chat.id, "⏳ در حال فعال‌سازی لایسنس...", parse_mode="HTML")
            result = activate_license(
                api_key=api_key,
                api_url=api_url,
                bot_username=bot_username,
                owner_telegram_id=uid,
            )
            if result.get("ok"):
                expires = result.get("expires_at", "نامشخص")
                success_text = ACTIVATION_SUCCESS_TEXT.format(expires_at=expires)
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("📊 مدیریت لایسنس", callback_data="license:status"))
                bot.send_message(message.chat.id, success_text, parse_mode="HTML", reply_markup=kb)
            else:
                error_msg = result.get("message", "خطای نامشخص")
                fail_text = ACTIVATION_FAIL_TEXT.format(message=error_msg)
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("🔄 تلاش مجدد", callback_data="license:activate"))
                bot.send_message(message.chat.id, fail_text, parse_mode="HTML", reply_markup=kb)
            return

        # ── License edit: API Key ─────────────────────────────────────────────
        if sn == "license:edit_api_key" and is_admin(uid):
            new_key = (message.text or "").strip()
            state_clear(uid)
            if not new_key or new_key in ("/cancel", "لغو"):
                bot.send_message(message.chat.id, "❌ لغو شد.")
                return
            from ..license_manager import _setting_set as _lic_set, _SETTINGS_KEY_API_KEY, _invalidate_cache as _lic_inv
            _lic_set(_SETTINGS_KEY_API_KEY, new_key)
            _lic_inv()
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("📊 مدیریت لایسنس", callback_data="license:status"))
            bot.send_message(
                message.chat.id,
                "✅ <b>API Key با موفقیت ذخیره شد.</b>\n\n"
                "برای اعمال تغییر، از دکمه «بررسی مجدد» استفاده کنید.",
                parse_mode="HTML", reply_markup=kb,
            )
            return

        # ── License edit: API URL ─────────────────────────────────────────────
        if sn == "license:edit_api_url" and is_admin(uid):
            new_url = (message.text or "").strip()
            state_clear(uid)
            if not new_url or new_url in ("/cancel", "لغو"):
                bot.send_message(message.chat.id, "❌ لغو شد.")
                return
            from ..license_manager import _setting_set as _lic_set, _SETTINGS_KEY_API_URL, _invalidate_cache as _lic_inv
            _lic_set(_SETTINGS_KEY_API_URL, new_url.rstrip("/"))
            _lic_inv()
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("📊 مدیریت لایسنس", callback_data="license:status"))
            bot.send_message(
                message.chat.id,
                "✅ <b>API URL با موفقیت ذخیره شد.</b>\n\n"
                "برای اعمال تغییر، از دکمه «بررسی مجدد» استفاده کنید.",
                parse_mode="HTML", reply_markup=kb,
            )
            return

        # ── Analytics date input ─────────────────────────────────────────────
        def _parse_jalali_date(text):
            """Parse 'YYYY/MM/DD' or 'YYYY-MM-DD' jalali string → 'YYYY-MM-DD'."""
            import re as _re
            text = (text or "").strip()
            m = _re.fullmatch(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", text)
            if not m:
                return None
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        if sn == "admin_stats_date" and is_admin(uid):
            raw = (message.text or "").strip()
            jdate = _parse_jalali_date(raw)
            state_clear(uid)
            if not jdate:
                bot.send_message(uid, "⚠️ تاریخ معتبر وارد کنید. مثال: <code>1403/06/15</code>", parse_mode="HTML")
                return
            from ..admin.analytics import _report_type_kb, _period_label
            label = _period_label("custom_day", custom_start=jdate)
            text = f"📊 <b>آمار — {label}</b>\n\nنوع گزارش را انتخاب کنید:"
            kb = _report_type_kb("custom_day", jdate, None)
            bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            return

        if sn == "admin_stats_range_start" and is_admin(uid):
            raw = (message.text or "").strip()
            jdate = _parse_jalali_date(raw)
            if not jdate:
                bot.send_message(uid, "⚠️ تاریخ معتبر وارد کنید. مثال: <code>1403/06/01</code>", parse_mode="HTML")
                return
            state_set(uid, "admin_stats_range_end", range_start=jdate)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:stats", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid,
                "📆 تاریخ پایان بازه را وارد کنید (جلالی):\n\n"
                "مثال: <code>1403/06/30</code>", parse_mode="HTML",
                reply_markup=kb)
            return

        if sn == "admin_stats_range_end" and is_admin(uid):
            raw = (message.text or "").strip()
            jdate_end = _parse_jalali_date(raw)
            jdate_start = sd.get("range_start", "")
            state_clear(uid)
            if not jdate_end or not jdate_start:
                bot.send_message(uid, "⚠️ تاریخ معتبر وارد کنید.", parse_mode="HTML")
                return
            from ..admin.analytics import _report_type_kb, _period_label
            label = _period_label("custom", custom_start=jdate_start, custom_end=jdate_end)
            text = f"📊 <b>آمار — {label}</b>\n\nنوع گزارش را انتخاب کنید:"
            kb = _report_type_kb("custom", jdate_start, jdate_end)
            bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            return

        # ── Broadcast ─────────────────────────────────────────────────────────

        if sn == "admin_broadcast_all" and is_admin(uid):
            user_ids = [u["user_id"] for u in get_users()]
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("فوروارد همگانی — همه کاربران", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "فوروارد همگانی — همه کاربران", "forward",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_broadcast_customers" and is_admin(uid):
            user_ids = [u["user_id"] for u in get_users(has_purchase=True)]
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("فوروارد همگانی — مشتریان", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "فوروارد همگانی — مشتریان", "forward",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_broadcast_normal" and is_admin(uid):
            from ..db import get_all_admin_users as _get_admins
            admin_ids_set = set(ADMIN_IDS)
            for _ar in _get_admins():
                admin_ids_set.add(_ar["user_id"])
            user_ids = [
                u["user_id"] for u in get_users(has_purchase=True)
                if u["user_id"] not in admin_ids_set and not u["is_agent"]
            ]
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("فوروارد همگانی — مشتریان عادی", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "فوروارد همگانی — مشتریان عادی", "forward",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_broadcast_agents" and is_admin(uid):
            user_ids = [u["user_id"] for u in get_users() if u["is_agent"]]
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("فوروارد همگانی — نمایندگان", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "فوروارد همگانی — نمایندگان", "forward",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_broadcast_admins" and is_admin(uid):
            from ..db import get_all_admin_users as _get_admins
            seen = set()
            user_ids = []
            for aid in ADMIN_IDS:
                if aid not in seen:
                    seen.add(aid)
                    user_ids.append(aid)
            for _ar in _get_admins():
                if _ar["user_id"] not in seen:
                    seen.add(_ar["user_id"])
                    user_ids.append(_ar["user_id"])
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("فوروارد همگانی — ادمین‌ها", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "فوروارد همگانی — ادمین‌ها", "forward",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        # ── Pin Broadcast ──────────────────────────────────────────────────────

        if sn == "admin_pin_broadcast_all" and is_admin(uid):
            user_ids = [u["user_id"] for u in get_users()]
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("پین همگانی — همه کاربران", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "پین همگانی — همه کاربران", "pin",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_pin_broadcast_customers" and is_admin(uid):
            user_ids = [u["user_id"] for u in get_users(has_purchase=True)]
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("پین همگانی — مشتریان", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "پین همگانی — مشتریان", "pin",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_pin_broadcast_normal" and is_admin(uid):
            from ..db import get_all_admin_users as _get_admins
            admin_ids_set = set(ADMIN_IDS)
            for _ar in _get_admins():
                admin_ids_set.add(_ar["user_id"])
            user_ids = [
                u["user_id"] for u in get_users(has_purchase=True)
                if u["user_id"] not in admin_ids_set and not u["is_agent"]
            ]
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("پین همگانی — مشتریان عادی", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "پین همگانی — مشتریان عادی", "pin",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_pin_broadcast_agents" and is_admin(uid):
            user_ids = [u["user_id"] for u in get_users() if u["is_agent"]]
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("پین همگانی — نمایندگان", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "پین همگانی — نمایندگان", "pin",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_pin_broadcast_admins" and is_admin(uid):
            from ..db import get_all_admin_users as _get_admins
            seen = set()
            user_ids = []
            for aid in ADMIN_IDS:
                if aid not in seen:
                    seen.add(aid)
                    user_ids.append(aid)
            for _ar in _get_admins():
                if _ar["user_id"] not in seen:
                    seen.add(_ar["user_id"])
                    user_ids.append(_ar["user_id"])
            state_clear(uid)
            prog = bot.send_message(
                uid, _bc_progress_text("پین همگانی — ادمین‌ها", len(user_ids), 0, 0, 0),
                parse_mode="HTML")
            threading.Thread(
                target=_do_broadcast,
                args=(user_ids, "پین همگانی — ادمین‌ها", "pin",
                      uid, *_bc_source(message),
                      message.reply_markup, prog.message_id),
                daemon=True).start()
            return

        if sn == "admin_reject_all_note" and is_admin(uid):
            note_text = message.text.strip() if message.text else ""
            state_clear(uid)
            if not note_text:
                bot.send_message(uid, "❌ متن خالی است. عملیات لغو شد.", parse_mode="HTML")
                return
            from .callbacks import _do_reject_all
            # Create a fake call-like object so _do_reject_all can answer/edit
            class _FakeCall:
                id = None
                message = message
                from_user = message.from_user
            _do_reject_all(_FakeCall(), uid, note=note_text)
            return

        if sn == "admin_dm_user" and is_admin(uid):
            target_uid = sd.get("target_user_id")
            state_clear(uid)
            try:
                bot.copy_message(target_uid, message.chat.id, message.message_id)
                bot.send_message(uid,
                    f"✅ پیام با موفقیت به کاربر <code>{target_uid}</code> ارسال شد.",
                    parse_mode="HTML", reply_markup=kb_admin_panel())
                log_admin_action(uid, f"پیام خصوصی به کاربر <code>{target_uid}</code> ارسال شد")
            except Exception as e:
                bot.send_message(uid,
                    f"❌ <b>ارسال ناموفق</b>\n\n"
                    f"کاربر <code>{target_uid}</code> پیام را دریافت نکرد.\n"
                    f"احتمالاً ربات را بلاک کرده یا چت فعالی ندارد.\n\n"
                    f"<code>{esc(str(e)[:200])}</code>",
                    parse_mode="HTML", reply_markup=kb_admin_panel())
            return

        if sn == "waiting_for_phone":
            phone_iran_only = setting_get("phone_iran_only", "0") == "1"
            phone_raw = None
            # Accept contact message
            if message.contact and message.contact.user_id == uid:
                phone_raw = message.contact.phone_number
            # Accept text message with phone number
            elif message.text:
                phone_raw = message.text.strip()

            if phone_raw:
                normalized = normalize_iranian_phone(phone_raw)
                if phone_iran_only and not normalized:
                    bot.send_message(
                        message.chat.id,
                        "❌ <b>شماره نامعتبر</b>\n\n"
                        "لطفاً یک شماره موبایل ایرانی معتبر (شروع با ۰۹) وارد کنید\n"
                        "یا دکمه «ارسال شماره تلفن» را بزنید.",
                        parse_mode="HTML",
                    )
                    return
                final_phone = normalized if normalized else phone_raw
                set_phone_number(uid, final_phone)
                state_clear(uid)
                from telebot.types import ReplyKeyboardRemove
                bot.send_message(
                    message.chat.id,
                    f"✅ <b>شماره تلفن ثبت شد</b>\n\n"
                    f"شماره <code>{final_phone}</code> با موفقیت ذخیره شد.",
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove(),
                )
                show_main_menu(message)
            else:
                bot.send_message(
                    message.chat.id,
                    "⚠️ لطفاً با دکمه زیر شماره تلفن خود را ارسال کنید.",
                    parse_mode="HTML",
                )
            return

        if sn == "waiting_for_phone_card":
            phone_iran_only = setting_get("phone_iran_only", "0") == "1"
            phone_raw = None
            if message.contact and message.contact.user_id == uid:
                phone_raw = message.contact.phone_number
            elif message.text:
                phone_raw = message.text.strip()

            if phone_raw:
                normalized = normalize_iranian_phone(phone_raw)
                if phone_iran_only and not normalized:
                    bot.send_message(
                        message.chat.id,
                        "❌ <b>شماره نامعتبر</b>\n\n"
                        "لطفاً یک شماره موبایل ایرانی معتبر (شروع با ۰۹) وارد کنید\n"
                        "یا دکمه «ارسال شماره تلفن» را بزنید.",
                        parse_mode="HTML",
                    )
                    return
                final_phone = normalized if normalized else phone_raw
                set_phone_number(uid, final_phone)
                pending_callback = sd.get("pending_callback")
                # Preserve any state data needed for the resumed callback
                _preserved_sd = {k: v for k, v in sd.items()
                                 if k not in ("state", "pending_callback")}
                from telebot.types import ReplyKeyboardRemove
                bot.send_message(
                    message.chat.id,
                    f"✅ شماره <code>{final_phone}</code> ثبت شد. در حال ادامه خرید...",
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove(),
                )
                if pending_callback:
                    # Restore the preserved state (quantity, service_names, amount etc.)
                    # then replay the original callback as if the user pressed the button again
                    if _preserved_sd:
                        state_set(uid, "_phone_resume_", **_preserved_sd)
                    else:
                        state_clear(uid)
                    from ..handlers.callbacks import _dispatch_callback as _dc

                    class _FakeUser:
                        def __init__(self, uid_):
                            self.id = uid_

                    class _FakeMsg:
                        def __init__(self, msg):
                            self.chat       = msg.chat
                            self.message_id = msg.message_id
                            self.text       = ""

                    class _FakeCall:
                        def __init__(self, msg, uid_, cb_data):
                            self.from_user = _FakeUser(uid_)
                            self.message   = _FakeMsg(msg)
                            self.data      = cb_data
                            self.id        = "0"

                    # bot.answer_callback_query("0") would fail with a Telegram API error
                    # because "0" is not a valid callback query ID.  Temporarily replace it
                    # with a version that silently ignores our fake sentinel so the rest of
                    # the dispatched handler (send_or_edit, create_payment, …) can proceed.
                    _orig_acq = bot.answer_callback_query
                    def _silent_acq(cid, *_a, **_kw):
                        if str(cid) == "0":
                            return None
                        return _orig_acq(cid, *_a, **_kw)
                    bot.answer_callback_query = _silent_acq
                    try:
                        _dc(_FakeCall(message, uid, pending_callback), uid, pending_callback)
                    finally:
                        bot.answer_callback_query = _orig_acq
                else:
                    state_clear(uid)
                    show_main_menu(message)
            else:
                bot.send_message(
                    message.chat.id,
                    "⚠️ لطفاً با دکمه زیر شماره تلفن خود را ارسال کنید.",
                    parse_mode="HTML",
                )
            return

        if sn == "admin_broadcast_all" and is_admin(uid):
            users = get_users()
            sent  = 0
            for u in users:
                try:
                    _bc_send(u["user_id"])
                    sent += 1
                except Exception:
                    pass
            state_clear(uid)
            bot.send_message(uid, f"✅ پیام برای {sent} کاربر ارسال شد.", reply_markup=kb_admin_panel())
            from ..group_manager import send_to_topic as _stt
            _bc_preview = (message.text or message.caption or "")[:200].strip()
            _stt("broadcast_report",
                f"📢 <b>اطلاع‌رسانی (همه کاربران)</b>\n\n"
                f"👤 ارسال‌کننده: <code>{uid}</code>\n"
                f"📤 ارسال شده: <b>{sent}</b> کاربر\n\n"
                f"📝 <b>متن پیام:</b>\n{esc(_bc_preview) if _bc_preview else '(فایل/مدیا)'}")
            return

        if sn == "admin_broadcast_customers" and is_admin(uid):
            users = get_users(has_purchase=True)
            sent  = 0
            for u in users:
                try:
                    _bc_send(u["user_id"])
                    sent += 1
                except Exception:
                    pass
            state_clear(uid)
            bot.send_message(uid, f"✅ پیام برای {sent} مشتری ارسال شد.", reply_markup=kb_admin_panel())
            from ..group_manager import send_to_topic as _stt
            _bc_preview = (message.text or message.caption or "")[:200].strip()
            _stt("broadcast_report",
                f"📢 <b>اطلاع‌رسانی (مشتریان)</b>\n\n"
                f"👤 ارسال‌کننده: <code>{uid}</code>\n"
                f"📤 ارسال شده: <b>{sent}</b> مشتری\n\n"
                f"📝 <b>متن پیام:</b>\n{esc(_bc_preview) if _bc_preview else '(فایل/مدیا)'}")
            return

        if sn == "admin_broadcast_normal" and is_admin(uid):
            from ..db import get_all_admin_users as _get_admins
            admin_ids_set = set(ADMIN_IDS)
            for _ar in _get_admins():
                admin_ids_set.add(_ar["user_id"])
            users = get_users(has_purchase=True)
            sent  = 0
            for u in users:
                if u["user_id"] in admin_ids_set:
                    continue
                if u["is_agent"]:
                    continue
                try:
                    _bc_send(u["user_id"])
                    sent += 1
                except Exception:
                    pass
            state_clear(uid)
            bot.send_message(uid, f"✅ پیام برای {sent} مشتری عادی ارسال شد.", reply_markup=kb_admin_panel())
            from ..group_manager import send_to_topic as _stt
            _bc_preview = (message.text or message.caption or "")[:200].strip()
            _stt("broadcast_report",
                f"📢 <b>اطلاع‌رسانی (مشتریان عادی)</b>\n\n"
                f"👤 ارسال‌کننده: <code>{uid}</code>\n"
                f"📤 ارسال شده: <b>{sent}</b> کاربر\n\n"
                f"📝 <b>متن پیام:</b>\n{esc(_bc_preview) if _bc_preview else '(فایل/مدیا)'}")
            return

        if sn == "admin_broadcast_agents" and is_admin(uid):
            users = get_users()
            sent  = 0
            for u in users:
                if not u["is_agent"]:
                    continue
                try:
                    _bc_send(u["user_id"])
                    sent += 1
                except Exception:
                    pass
            state_clear(uid)
            bot.send_message(uid, f"✅ پیام برای {sent} نماینده ارسال شد.", reply_markup=kb_admin_panel())
            from ..group_manager import send_to_topic as _stt
            _bc_preview = (message.text or message.caption or "")[:200].strip()
            _stt("broadcast_report",
                f"📢 <b>اطلاع‌رسانی (نمایندگان)</b>\n\n"
                f"👤 ارسال‌کننده: <code>{uid}</code>\n"
                f"📤 ارسال شده: <b>{sent}</b> نماینده\n\n"
                f"📝 <b>متن پیام:</b>\n{esc(_bc_preview) if _bc_preview else '(فایل/مدیا)'}")
            return

        if sn == "admin_broadcast_admins" and is_admin(uid):
            from ..db import get_all_admin_users as _get_admins
            sent  = 0
            # ADMIN_IDS
            for aid in ADMIN_IDS:
                try:
                    _bc_send(aid)
                    sent += 1
                except Exception:
                    pass
            # Sub-admins
            for _ar in _get_admins():
                if _ar["user_id"] in ADMIN_IDS:
                    continue
                try:
                    _bc_send(_ar["user_id"])
                    sent += 1
                except Exception:
                    pass
            state_clear(uid)
            bot.send_message(uid, f"✅ پیام برای {sent} ادمین ارسال شد.", reply_markup=kb_admin_panel())
            from ..group_manager import send_to_topic as _stt
            _bc_preview = (message.text or message.caption or "")[:200].strip()
            _stt("broadcast_report",
                f"📢 <b>اطلاع‌رسانی (ادمین‌ها)</b>\n\n"
                f"👤 ارسال‌کننده: <code>{uid}</code>\n"
                f"📤 ارسال شده: <b>{sent}</b> ادمین\n\n"
                f"📝 <b>متن پیام:</b>\n{esc(_bc_preview) if _bc_preview else '(فایل/مدیا)'}")
            return

        # ── Wallet amount ──────────────────────────────────────────────────────
        if sn == "await_wallet_amount":
            amount = parse_int(message.text or "")
            if not amount or amount <= 0:
                bot.send_message(uid, "⚠️ لطفاً مبلغ معتبر وارد کنید.", reply_markup=back_button("main"))
                return
            # Validate against global gateway range
            g_min, g_max = get_global_amount_range(uid)
            if g_min is not None and amount < g_min:
                bot.send_message(uid,
                    f"❗️ حداقل مبلغ قابل پرداخت <b>{fmt_price(g_min)}</b> تومان است.\n"
                    f"لطفاً مبلغی بین <b>{fmt_price(g_min)}</b>"
                    f"{f' تا <b>{fmt_price(g_max)}</b>' if g_max else ''} تومان وارد کنید.",
                    reply_markup=back_button("main"))
                return
            if g_max is not None and amount > g_max:
                bot.send_message(uid,
                    f"❗️ حداکثر مبلغ قابل پرداخت <b>{fmt_price(g_max)}</b> تومان است.\n"
                    f"لطفاً مبلغی بین <b>{fmt_price(g_min)}</b>"
                    f"{f' تا <b>{fmt_price(g_max)}</b>' if g_max else ''} تومان وارد کنید."
                    if g_min else
                    f"❗️ حداکثر مبلغ قابل پرداخت <b>{fmt_price(g_max)}</b> تومان است.\n"
                    f"لطفاً مبلغی تا <b>{fmt_price(g_max)}</b> تومان وارد کنید.",
                    reply_markup=back_button("main"))
                return
            state_set(uid, "wallet_charge_method", amount=amount, original_amount=amount)
            _show_wallet_gateways(message, uid, amount)
            return

        # ── Bulk quantity entry ───────────────────────────────────────────────
        if sn == "await_qty":
            raw = (message.text or "").strip()
            normalized = normalize_text_number(raw)
            qty = parse_int(normalized)

            min_qty, max_qty = get_bulk_qty_limits()
            max_label = "بدون محدودیت" if max_qty == 0 else str(max_qty)

            if not qty or qty <= 0:
                bot.send_message(uid,
                    "⚠️ <b>تعداد وارد‌شده نامعتبر است.</b>\n\n"
                    "لطفاً یک عدد صحیح و مثبت وارد کنید.\n\n"
                    f"📌 بازه مجاز: <b>{min_qty}</b> تا <b>{max_label}</b>\n"
                    f"مثال: <code>{min_qty}</code>",
                    parse_mode="HTML")
                return

            if qty < min_qty:
                bot.send_message(uid,
                    f"⚠️ <b>تعداد وارد‌شده کمتر از حداقل مجاز است.</b>\n\n"
                    f"📌 حداقل تعداد مجاز در هر سفارش: <b>{min_qty} عدد</b>\n\n"
                    "لطفاً مقدار بیشتری وارد کنید.",
                    parse_mode="HTML")
                return

            if max_qty > 0 and qty > max_qty:
                bot.send_message(uid,
                    f"⚠️ <b>تعداد وارد‌شده بیشتر از حداکثر مجاز است.</b>\n\n"
                    f"📌 حداکثر تعداد مجاز در هر سفارش: <b>{max_qty} عدد</b>\n\n"
                    "لطفاً مقدار کمتری وارد کنید.",
                    parse_mode="HTML")
                return

            package_id = sd.get("package_id")
            unit_price = int(sd.get("unit_price", 0) or 0)
            package_row = get_package(package_id)
            if not package_row or not unit_price:
                state_clear(uid)
                bot.send_message(uid, "⚠️ خطا در اطلاعات سفارش. لطفاً دوباره شروع کنید.", reply_markup=kb_main(uid))
                return
            total = unit_price * qty
            state_set(uid, "buy_select_method",
                      package_id=package_id, amount=total, original_amount=total,
                      unit_price=unit_price, quantity=qty, kind="config_purchase")
            # Naming step for panel packages
            if _is_panel_package(package_row):
                _show_naming_prompt(message, package_id, qty)
                return
            if setting_get("discount_codes_enabled", "0") == "1":
                if _show_discount_prompt(message, total):
                    return
            _show_purchase_gateways(message, uid, package_id, total, package_row)
            return

        # ── Custom service name (single) ──────────────────────────────────────
        if sn == "await_service_name":
            raw        = (message.text or "").strip()
            normalized = normalize_service_name(raw)
            package_id = sd.get("package_id")
            unit_price = int(sd.get("unit_price", 0) or 0)
            package_row = get_package(package_id) if package_id else None
            if not package_row or not unit_price:
                state_clear(uid)
                bot.send_message(uid, "⚠️ خطا در اطلاعات سفارش. لطفاً دوباره شروع کنید.", reply_markup=kb_main(uid))
                return
            # Fallback to random if invalid
            if not validate_service_name(normalized):
                chosen_name = generate_random_name()
            else:
                chosen_name = normalized
            total = unit_price * 1
            state_set(uid, "buy_select_method",
                      package_id=package_id, amount=total, original_amount=total,
                      unit_price=unit_price, quantity=1, kind="config_purchase",
                      service_names=[chosen_name])
            if _show_discount_prompt(message, total):
                return
            _show_purchase_gateways(message, uid, package_id, total, package_row)
            return

        # ── Custom service names (bulk) ───────────────────────────────────────
        if sn == "await_bulk_service_names":
            package_id = sd.get("package_id")
            unit_price = int(sd.get("unit_price", 0) or 0)
            quantity   = int(sd.get("quantity", 1) or 1)
            package_row = get_package(package_id) if package_id else None
            if not package_row or not unit_price:
                state_clear(uid)
                bot.send_message(uid, "⚠️ خطا در اطلاعات سفارش. لطفاً دوباره شروع کنید.", reply_markup=kb_main(uid))
                return
            chosen_names = parse_bulk_names(message.text or "", quantity)
            total = unit_price * quantity
            state_set(uid, "buy_select_method",
                      package_id=package_id, amount=total, original_amount=total,
                      unit_price=unit_price, quantity=quantity, kind="config_purchase",
                      service_names=chosen_names)
            if _show_discount_prompt(message, total):
                return
            _show_purchase_gateways(message, uid, package_id, total, package_row)
            return

        # ── Discount code entry ───────────────────────────────────────────────
        if sn == "await_discount_code":
            code = (message.text or message.caption or "").strip()
            if not code:
                bot.send_message(uid, "⚠️ کد تخفیف را وارد کنید.")
                return
            prev_state = sd.get("prev_state", "buy_select_method")
            original_amount = int(sd.get("original_amount", sd.get("amount", 0)) or 0)
            if original_amount <= 0:
                state_clear(uid)
                bot.send_message(uid, "⚠️ مبلغی برای اعمال تخفیف پیدا نشد.", reply_markup=kb_main(uid))
                return
            _user_for_disc = get_user(uid)
            _is_agent_disc = bool(_user_for_disc and _user_for_disc["is_agent"])
            _pkg_id_for_disc = sd.get("package_id")
            ok, row, disc_amount, final_amount, err = validate_discount_code(code, uid, original_amount, is_agent=_is_agent_disc, package_id=_pkg_id_for_disc)
            if not ok:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("🔙 ادامه بدون تخفیف", callback_data="disc:no"))
                bot.send_message(uid,
                    f"{err}\n\nلطفاً دوباره تلاش کنید یا از دکمه زیر استفاده کنید.",
                    reply_markup=kb)
                return
            record_discount_usage(row["id"], uid)
            new_data = {k: v for k, v in sd.items() if k != "prev_state"}
            new_data.update({
                "amount": final_amount,
                "original_amount": original_amount,
                "discount_amount": disc_amount,
                "discount_code_id": row["id"],
                "discount_code": row["code"],
            })
            state_set(uid, prev_state, **new_data)
            if prev_state == "buy_select_method":
                package_id = new_data.get("package_id")
                package_row = get_package(package_id) if package_id else None
                if package_row:
                    _show_purchase_gateways(message, uid, package_id, final_amount, package_row)
                return
            if prev_state == "renew_select_method":
                purchase_id = new_data.get("purchase_id")
                package_id = new_data.get("package_id")
                item = get_purchase(purchase_id) if purchase_id else None
                package_row = get_package(package_id) if package_id else None
                if item and package_row:
                    _show_renewal_gateways(message, uid, purchase_id, package_id, final_amount, package_row, item)
                return
            bot.send_message(uid, "✅ تخفیف ثبت شد.", reply_markup=kb_main(uid))
            return

        # ── Addon discount code (separate from regular discount flow) ──────────
        if sn == "await_addon_discount":
            from ..db import (
                validate_discount_code as _vdc,
                get_addon_price as _gap,
                get_panel_config as _gcfg2,
                get_package as _gpkg2,
            )
            from ..handlers.callbacks import _show_addon_invoice
            code       = (message.text or "").strip().upper()
            addon_type = sd.get("prev_addon_type", "volume")
            config_id  = sd.get("prev_addon_config")
            original_amount = int(sd.get("original_amount", sd.get("subtotal", 0)))
            _user2      = get_user(uid)
            _is_agent2  = bool(_user2 and _user2["is_agent"])
            usage_scope = f"addon_{addon_type}"
            ok2, row2, disc2, final2, err2 = _vdc(
                code, uid, original_amount,
                is_agent=_is_agent2, package_id=None, usage_scope=usage_scope,
            )
            if not ok2:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("بدون تخفیف", callback_data=f"addon:nodisc:{config_id}:{addon_type}"))
                bot.send_message(uid,
                    f"{err2}\n\nمجدداً کد تخفیف وارد کنید یا ادامه دهید.",
                    reply_markup=kb)
                return
            prev = f"addon_{'vol' if addon_type == 'volume' else 'time'}_flow"
            unit_price = int(sd.get("unit_price", 0))
            new_sd = {k: v for k, v in sd.items()
                      if k not in ("prev_addon_type", "prev_addon_config", "original_amount")}
            new_sd.update({
                "discount_amount": disc2,
                "final_amount": final2,
                "discount_code_id": row2["id"],
                "subtotal": original_amount,
            })
            state_set(uid, prev, **new_sd)
            bot.send_message(uid, f"✅ کد تخفیف اعمال شد! مبلغ تخفیف: <b>{fmt_price(disc2)} تومان</b>")
            _show_addon_invoice(message, uid, addon_type)
            return

        # ── User: Custom volume amount ─────────────────────────────────────────
        if sn == "addon_vol_custom":
            from ..db import get_addon_price as _gap2, get_panel_config as _gcfg3, get_package as _gpkg3
            from ..handlers.callbacks import _show_addon_invoice as _sai
            config_id = sd.get("config_id")
            try:
                gb = float((message.text or "").replace(",", "."))
                if gb <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                bot.send_message(uid, "⚠️ مقدار معتبر وارد کنید (مثال: 5 یا 2.5)")
                return
            cfg3  = _gcfg3(config_id)
            pkg3  = _gpkg3(cfg3["package_id"]) if cfg3 else None
            if not pkg3:
                bot.send_message(uid, "⚠️ سرویس یافت نشد.")
                return
            pr = _gap2(pkg3["type_id"], "volume")
            _usr3 = get_user(uid)
            _agt3 = bool(_usr3 and _usr3["is_agent"])
            unit_price = None
            if pr:
                if _agt3 and pr["reseller_unit_price"] is not None:
                    unit_price = pr["reseller_unit_price"]
                elif pr["normal_unit_price"] is not None:
                    unit_price = pr["normal_unit_price"]
            if unit_price is None:
                bot.send_message(uid, "قیمت این افزودنی تعیین نشده است.")
                return
            subtotal = int(gb * unit_price)
            state_set(uid, "addon_vol_flow",
                      config_id=config_id, unit_price=unit_price,
                      amount_gb=gb, subtotal=subtotal, discount_amount=0, final_amount=subtotal)
            _sai(message, uid, "volume")
            return

        # ── User: Custom time amount ───────────────────────────────────────────
        if sn == "addon_time_custom":
            from ..db import get_addon_price as _gap4, get_panel_config as _gcfg4, get_package as _gpkg4
            from ..handlers.callbacks import _show_addon_invoice as _sai2
            config_id = sd.get("config_id")
            val4 = parse_int(message.text or "")
            if val4 is None or val4 <= 0:
                bot.send_message(uid, "⚠️ عدد صحیح مثبت وارد کنید.")
                return
            cfg4  = _gcfg4(config_id)
            pkg4  = _gpkg4(cfg4["package_id"]) if cfg4 else None
            if not pkg4:
                bot.send_message(uid, "⚠️ سرویس یافت نشد.")
                return
            pr4 = _gap4(pkg4["type_id"], "time")
            _usr4 = get_user(uid)
            _agt4 = bool(_usr4 and _usr4["is_agent"])
            unit_price4 = None
            if pr4:
                if _agt4 and pr4["reseller_unit_price"] is not None:
                    unit_price4 = pr4["reseller_unit_price"]
                elif pr4["normal_unit_price"] is not None:
                    unit_price4 = pr4["normal_unit_price"]
            if unit_price4 is None:
                bot.send_message(uid, "قیمت این افزودنی تعیین نشده است.")
                return
            subtotal4 = val4 * unit_price4
            state_set(uid, "addon_time_flow",
                      config_id=config_id, unit_price=unit_price4,
                      amount_days=val4, subtotal=subtotal4, discount_amount=0, final_amount=subtotal4)
            _sai2(message, uid, "time")
            return


        if sn == "await_wallet_receipt":
            payment_id  = sd.get("payment_id")
            if not payment_id:
                state_clear(uid)
                bot.send_message(uid, "⚠️ اطلاعات پرداخت یافت نشد. لطفاً دوباره از منو اقدام کنید.", reply_markup=kb_main(uid))
                return
            file_id     = None
            text_value  = (message.caption or message.text or "").strip()
            if message.photo:
                file_id = message.photo[-1].file_id
            elif message.document:
                file_id = message.document.file_id
            # Ignore messages that contain no receipt content (no text, no media).
            # This prevents unrelated messages (contacts, stickers, voice, …) sent
            # while the user is viewing the payment-info page from being recorded
            # as a receipt submission.
            if not text_value and not file_id:
                bot.send_message(uid,
                    "⚠️ لطفاً هش تراکنش را به صورت متن، یا تصویر/فایل رسید را ارسال کنید.")
                return
            try:
                update_payment_receipt(payment_id, file_id, text_value.strip())
            except Exception as _e:
                print(f"[wallet_receipt] update_payment_receipt failed: {_e}")
                bot.send_message(uid, "⚠️ خطایی در ثبت رسید رخ داد. لطفاً دوباره تلاش کنید.", reply_markup=kb_main(uid))
                return
            state_clear(uid)
            bot.send_message(
                uid,
                '<tg-emoji emoji-id="5987671584469422871">✅</tg-emoji> کاربر گرامی ، رسید شما ارسال شد.\n'
                'بزودی رسید شما ، توسط ادمین بررسی خواهد شد.\n\n'
                'از صبر و شکیبایی شما سپاسگذاریم <tg-emoji emoji-id="5987790963085415158">🙏</tg-emoji>',
                parse_mode="HTML",
                reply_markup=kb_main(uid),
            )
            try:
                send_payment_to_admins(payment_id)
            except Exception as _e:
                print(f"[wallet_receipt] send_payment_to_admins failed: {_e}")
                import traceback as _tb; print(_tb.format_exc())
            return

        # ── Purchase receipt ───────────────────────────────────────────────────
        if sn == "await_purchase_receipt":
            payment_id  = sd.get("payment_id")
            if not payment_id:
                state_clear(uid)
                bot.send_message(uid, "⚠️ اطلاعات پرداخت یافت نشد. لطفاً دوباره از منو اقدام کنید.", reply_markup=kb_main(uid))
                return
            file_id     = None
            text_value  = (message.caption or message.text or "").strip()
            if message.photo:
                file_id = message.photo[-1].file_id
            elif message.document:
                file_id = message.document.file_id
            if not text_value and not file_id:
                bot.send_message(uid,
                    "⚠️ لطفاً هش تراکنش را به صورت متن، یا تصویر/فایل رسید را ارسال کنید.")
                return
            try:
                update_payment_receipt(payment_id, file_id, text_value.strip())
            except Exception as _e:
                print(f"[purchase_receipt] update_payment_receipt failed: {_e}")
                bot.send_message(uid, "⚠️ خطایی در ثبت رسید رخ داد. لطفاً دوباره تلاش کنید.", reply_markup=kb_main(uid))
                return
            state_clear(uid)
            bot.send_message(
                uid,
                '<tg-emoji emoji-id="5987671584469422871">✅</tg-emoji> کاربر گرامی ، رسید شما ارسال شد.\n'
                'بزودی رسید شما ، توسط ادمین بررسی خواهد شد.\n\n'
                'از صبر و شکیبایی شما سپاسگذاریم <tg-emoji emoji-id="5987790963085415158">🙏</tg-emoji>',
                parse_mode="HTML",
                reply_markup=kb_main(uid),
            )
            try:
                send_payment_to_admins(payment_id)
            except Exception as _e:
                print(f"[purchase_receipt] send_payment_to_admins failed: {_e}")
                import traceback as _tb; print(_tb.format_exc())
            return

        # ── Renewal receipt ────────────────────────────────────────────────────
        if sn == "await_renewal_receipt":
            payment_id  = sd.get("payment_id")
            if not payment_id:
                state_clear(uid)
                bot.send_message(uid, "⚠️ اطلاعات پرداخت یافت نشد. لطفاً دوباره از منو اقدام کنید.", reply_markup=kb_main(uid))
                return
            file_id     = None
            text_value  = (message.caption or message.text or "").strip()
            if message.photo:
                file_id = message.photo[-1].file_id
            elif message.document:
                file_id = message.document.file_id
            if not text_value and not file_id:
                bot.send_message(uid,
                    "⚠️ لطفاً هش تراکنش را به صورت متن، یا تصویر/فایل رسید را ارسال کنید.")
                return
            try:
                update_payment_receipt(payment_id, file_id, text_value.strip())
            except Exception as _e:
                print(f"[renewal_receipt] update_payment_receipt failed: {_e}")
                bot.send_message(uid, "⚠️ خطایی در ثبت رسید رخ داد. لطفاً دوباره تلاش کنید.", reply_markup=kb_main(uid))
                return
            state_clear(uid)
            bot.send_message(uid, "✅ رسید تمدید شما ارسال شد. لطفاً تا تأیید ادمین صبر کنید.",
                             reply_markup=kb_main(uid))
            try:
                send_payment_to_admins(payment_id)
            except Exception as _e:
                print(f"[renewal_receipt] send_payment_to_admins failed: {_e}")
                import traceback as _tb; print(_tb.format_exc())
            return

        # ── Fallback: user sends photo/text but no receipt state ──────────────
        # Handles the case where the user pressed "بازگشت" (which clears state)
        # and then sends their receipt — we recover by looking up their latest
        # pending manual payment (card or manual crypto) that still needs a receipt.
        _is_receipt_content = bool(
            message.photo or message.document or
            (message.text and len((message.text or "").strip()) > 5)
        )
        if _is_receipt_content and not is_admin(uid):
            with get_conn() as _rc:
                _pending_pay = _rc.execute(
                    "SELECT * FROM payments WHERE user_id=? AND status='pending'"
                    " AND payment_method IN ('card','crypto')"
                    " AND (receipt_file_id IS NULL OR receipt_file_id='')"
                    " ORDER BY id DESC LIMIT 1",
                    (uid,)
                ).fetchone()
            if _pending_pay:
                _rc_payment_id = _pending_pay["id"]
                _rc_file_id    = None
                _rc_text       = (message.caption or message.text or "").strip()
                if message.photo:
                    _rc_file_id = message.photo[-1].file_id
                elif message.document:
                    _rc_file_id = message.document.file_id
                if _rc_file_id or _rc_text:
                    try:
                        update_payment_receipt(_rc_payment_id, _rc_file_id, _rc_text)
                    except Exception as _re:
                        print(f"[fallback_receipt] update_payment_receipt failed: {_re}")
                        bot.send_message(uid, "⚠️ خطایی در ثبت رسید رخ داد. لطفاً دوباره تلاش کنید.",
                                         reply_markup=kb_main(uid))
                        return
                    _kind_label = "تمدید" if _pending_pay["kind"] in ("renewal", "pnlcfg_renewal") else \
                                  "شارژ کیف پول" if _pending_pay["kind"] == "wallet_charge" else "خرید"
                    bot.send_message(uid,
                        f"✅ رسید {_kind_label} شما ثبت شد و ارسال به ادمین در حال انجام است.\n"
                        "لطفاً تا تأیید صبر کنید.",
                        reply_markup=kb_main(uid))
                    try:
                        send_payment_to_admins(_rc_payment_id)
                    except Exception as _re2:
                        print(f"[fallback_receipt] send_payment_to_admins failed: {_re2}")
                    return

        # ── Admin: Discount codes ─────────────────────────────────────────────
        if sn == "admin_discount_add_code" and is_admin(uid):
            code = (message.text or "").strip().upper()
            if not code:
                bot.send_message(uid, "⚠️ متن کد تخفیف را وارد کنید.", reply_markup=back_button("admin:discounts"))
                return
            state_set(uid, "admin_discount_add_type", code=code)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("٪ درصدی", callback_data="admin:disc:add_type:pct"),
                types.InlineKeyboardButton("💰 مبلغ ثابت", callback_data="admin:disc:add_type:amount"),
            )
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:discounts", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid,
                f"🎟 کد: <code>{esc(code)}</code>\n\n"
                "مرحله ۲/۵: نوع تخفیف را انتخاب کنید:",
                reply_markup=kb)
            return

        if sn == "admin_discount_add_value" and is_admin(uid):
            val = parse_int(message.text or "")
            disc_type = sd.get("disc_type", "pct")
            if val is None or val <= 0:
                bot.send_message(uid, "⚠️ مقدار معتبر وارد کنید.")
                return
            if disc_type == "pct" and val > 100:
                bot.send_message(uid, "⚠️ درصد باید بین 1 تا 100 باشد.")
                return
            state_set(uid, "admin_discount_add_total",
                      code=sd.get("code", ""), disc_type=disc_type, discount_value=val)
            bot.send_message(uid,
                "مرحله ۳/۵: حداکثر تعداد استفاده کل را وارد کنید:\n"
                "(۰ = نامحدود)",
                reply_markup=back_button("admin:discounts"))
            return

        if sn == "admin_discount_add_total" and is_admin(uid):
            total = parse_int(message.text or "")
            if total is None or total < 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید. ۰ به معنی نامحدود است.")
                return
            state_set(uid, "admin_discount_add_per",
                      code=sd.get("code", ""), disc_type=sd.get("disc_type", "pct"),
                      discount_value=sd.get("discount_value", 0), max_uses_total=total)
            bot.send_message(uid,
                "مرحله ۴/۵: حداکثر تعداد استفاده هر کاربر را وارد کنید:\n"
                "(۰ = نامحدود)",
                reply_markup=back_button("admin:discounts"))
            return

        if sn == "admin_discount_add_per" and is_admin(uid):
            per_user = parse_int(message.text or "")
            if per_user is None or per_user < 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید. ۰ به معنی نامحدود است.")
                return
            state_set(uid, "admin_discount_add_audience",
                      code=sd.get("code", ""),
                      disc_type=sd.get("disc_type", "pct"),
                      discount_value=sd.get("discount_value", 0),
                      max_uses_total=sd.get("max_uses_total", 0),
                      max_uses_per_user=per_user)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("👥 همه", callback_data="admin:disc:add_audience:all"))
            kb.add(types.InlineKeyboardButton("🙋 فقط عموم (کاربران عادی)", callback_data="admin:disc:add_audience:public"))
            kb.add(types.InlineKeyboardButton("🤝 فقط نمایندگان", callback_data="admin:disc:add_audience:agents"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:discounts", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid,
                "🎟 <b>افزودن کد تخفیف</b>\n\n"
                "مرحله ۵/۵: این کد تخفیف برای چه کسانی است؟\n\n"
                "👥 <b>همه</b> — هم کاربران عادی و هم نمایندگان\n"
                "🙋 <b>فقط عموم</b> — فقط کاربران عادی\n"
                "🤝 <b>فقط نمایندگان</b> — فقط نمایندگان",
                parse_mode="HTML",
                reply_markup=kb)
            return

        if sn == "admin_discount_edit_code" and is_admin(uid):
            code = (message.text or "").strip().upper()
            if not code:
                bot.send_message(uid, "⚠️ متن کد تخفیف نمی‌تواند خالی باشد.")
                return
            try:
                update_discount_code_field(sd.get("edit_id"), "code", code)
            except sqlite3.IntegrityError:
                bot.send_message(uid, "⚠️ این کد قبلاً ثبت شده است.")
                return
            state_clear(uid)
            log_admin_action(uid, f"کد تخفیف #{sd.get('edit_id')} ویرایش شد")
            bot.send_message(uid, "✅ کد تخفیف ویرایش شد.")
            _render_discount_code_detail(message, uid, sd.get("edit_id"))
            return

        if sn == "admin_discount_edit_val" and is_admin(uid):
            code_id = sd.get("edit_id")
            row = get_discount_code(code_id)
            val = parse_int(message.text or "")
            if val is None or val <= 0:
                bot.send_message(uid, "⚠️ مقدار معتبر وارد کنید.")
                return
            if row and row["discount_type"] == "pct" and val > 100:
                bot.send_message(uid, "⚠️ درصد باید بین 1 تا 100 باشد.")
                return
            update_discount_code_field(code_id, "discount_value", val)
            state_clear(uid)
            bot.send_message(uid, "✅ مقدار تخفیف ویرایش شد.")
            _render_discount_code_detail(message, uid, code_id)
            return

        if sn == "admin_discount_edit_total" and is_admin(uid):
            code_id = sd.get("edit_id")
            val = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید. ۰ = نامحدود")
                return
            update_discount_code_field(code_id, "max_uses_total", val)
            state_clear(uid)
            bot.send_message(uid, "✅ حداکثر استفاده کل ویرایش شد.")
            _render_discount_code_detail(message, uid, code_id)
            return

        if sn == "admin_discount_edit_per" and is_admin(uid):
            code_id = sd.get("edit_id")
            val = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید. ۰ = نامحدود")
                return
            update_discount_code_field(code_id, "max_uses_per_user", val)
            state_clear(uid)
            bot.send_message(uid, "✅ حداکثر استفاده هر کاربر ویرایش شد.")
            _render_discount_code_detail(message, uid, code_id)
            return

        # ── User: Voucher code redemption ─────────────────────────────────────
        if sn == "await_voucher_code":
            code = (message.text or "").strip()
            if not code:
                bot.send_message(uid, "⚠️ کد کارت هدیه نمی‌تواند خالی باشد.")
                return
            vc = get_voucher_code_by_code(code)
            if not vc:
                bot.send_message(uid,
                    "❌ <b>کد کارت هدیه معتبر نیست.</b>\n\n"
                    "لطفاً کد را با دقت بررسی کنید و دوباره وارد نمایید.",
                    reply_markup=back_button("main"))
                state_clear(uid)
                return
            if vc["is_used"]:
                bot.send_message(uid,
                    "❌ <b>این کارت هدیه قبلاً استفاده شده است.</b>\n\n"
                    "هر کد کارت هدیه تنها یک بار قابل استفاده می‌باشد.",
                    reply_markup=back_button("main"))
                state_clear(uid)
                return
            redeemed = redeem_voucher_code(vc["id"], uid)
            if not redeemed:
                bot.send_message(uid,
                    "⚠️ متأسفانه این کد در همین لحظه توسط شخص دیگری استفاده شد.\n"
                    "لطفاً با پشتیبانی تماس بگیرید.",
                    reply_markup=back_button("main"))
                state_clear(uid)
                return
            state_clear(uid)
            if vc["gift_type"] == "wallet":
                amount = int(vc["gift_amount"] or 0)
                update_balance(uid, amount)
                bot.send_message(uid,
                    "🎉✨ <b>کارت هدیه با موفقیت ثبت شد!</b> ✨🎉\n\n"
                    f"🎫 کد: <code>{esc(vc['code'])}</code>\n"
                    f"💰 هدیه شما: <b>{fmt_price(amount)}</b> تومان\n\n"
                    "💳 موجودی کیف پول شما به همین مقدار شارژ شد.\n"
                    "🛒 اکنون می‌توانید از موجودی برای خرید یا تمدید سرویس استفاده کنید.\n\n"
                    "🙏 از انتخاب شما متشکریم!",
                    reply_markup=kb_main(uid))
            else:
                # Config gift — reserve and assign a config from the package
                pkg_id = vc["package_id"]
                pkg = get_package(pkg_id) if pkg_id else None
                if not pkg:
                    bot.send_message(uid,
                        "⚠️ متأسفانه پکیج مرتبط با این کارت هدیه یافت نشد.\n"
                        "لطفاً با پشتیبانی تماس بگیرید.",
                        reply_markup=back_button("main"))
                    return
                config_id = reserve_first_config(pkg_id)
                if not config_id:
                    bot.send_message(uid,
                        "⚠️ متأسفانه موجودی کانفیگ برای این کارت هدیه به پایان رسیده است.\n"
                        "لطفاً با پشتیبانی تماس بگیرید.",
                        reply_markup=back_button("main"))
                    return
                try:
                    purchase_id = assign_config_to_user(config_id, uid, pkg_id, 0, "voucher", is_test=0)
                except Exception:
                    bot.send_message(uid,
                        "⚠️ خطایی هنگام ثبت هدیه رخ داد. لطفاً با پشتیبانی تماس بگیرید.",
                        reply_markup=back_button("main"))
                    return
                from ..ui.notifications import deliver_purchase_message
                bot.send_message(uid,
                    "🎉✨ <b>کارت هدیه با موفقیت ثبت شد!</b> ✨🎉\n\n"
                    f"🎫 کد: <code>{esc(vc['code'])}</code>\n"
                    f"🎁 هدیه شما: سرویس از پکیج <b>{esc(pkg['name'])}</b>\n\n"
                    "📦 کانفیگ هدیه به بخش «کانفیگ‌های من» اضافه شد.\n"
                    "🚀 همین الان می‌توانید از سرویس خود لذت ببرید!\n\n"
                    "🙏 از انتخاب شما سپاسگزاریم.",
                    reply_markup=kb_main(uid))
                deliver_purchase_message(uid, purchase_id)
            return

        # ── Admin: Voucher creation ───────────────────────────────────────────
        if sn == "admin_vch_add_name" and is_admin(uid):
            name = (message.text or "").strip()
            if not name:
                bot.send_message(uid, "⚠️ نام نمی‌تواند خالی باشد.", reply_markup=back_button("admin:vouchers"))
                return
            state_set(uid, "admin_vch_pick_gift_type", vch_name=name)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("💰 هدیه موجودی کیف پول", callback_data="admin:vch:gift_type:wallet"),
                types.InlineKeyboardButton("📦 هدیه کانفیگ",          callback_data="admin:vch:gift_type:config"),
            )
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:vouchers", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid,
                f"🎫 نام: <b>{esc(name)}</b>\n\n"
                "مرحله ۲: نوع هدیه را انتخاب کنید:", reply_markup=kb)
            return

        if sn == "admin_vch_add_amount" and is_admin(uid):
            amount = parse_int(message.text or "")
            if not amount or amount <= 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر وارد کنید (بزرگتر از صفر).")
                return
            state_set(uid, "admin_vch_add_count_wallet",
                      vch_name=sd.get("vch_name", ""), gift_amount=amount)
            bot.send_message(uid,
                "🎫 <b>افزودن کارت هدیه</b>\n\n"
                "مرحله آخر: تعداد کدهای کارت هدیه را وارد کنید:\n"
                "<i>مثال: ۵۰</i>",
                reply_markup=back_button("admin:vouchers"))
            return

        if sn == "admin_vch_add_count_wallet" and is_admin(uid):
            count = parse_int(message.text or "")
            if not count or count <= 0 or count > 2000:
                bot.send_message(uid, "⚠️ تعداد باید بین ۱ تا ۲۰۰۰ باشد.")
                return
            vch_name = sd.get("vch_name", "")
            gift_amount = int(sd.get("gift_amount", 0) or 0)
            prefix = (setting_get("brand_title", "") or "GIFT").upper().replace(" ", "")[:6]
            codes = _generate_voucher_codes(count, prefix)
            batch_id = add_voucher_batch(vch_name, "wallet", gift_amount, None, codes)
            log_admin_action(uid, f"دسته کارت هدیه '{vch_name}' با {count} کد ساخته شد")
            state_clear(uid)
            # Send confirmation + all codes in one or more messages
            header = (
                f"✅ <b>کارت هدیه ساخته شد!</b>\n\n"
                f"🎫 نام: {esc(vch_name)}\n"
                f"💰 هدیه: {fmt_price(gift_amount)} تومان\n"
                f"📊 تعداد کدها: {count}\n\n"
                "─────────────────────\n"
                "کدها (قابل کپی):\n\n"
            )
            code_lines = [f"<code>{c}</code>" for c in codes]
            _send_codes_to_admin(uid, header, code_lines)
            _render_voucher_admin_list(message, uid)
            return

        if sn == "admin_vch_add_count_config" and is_admin(uid):
            count = parse_int(message.text or "")
            if not count or count <= 0 or count > 2000:
                bot.send_message(uid, "⚠️ تعداد باید بین ۱ تا ۲۰۰۰ باشد.")
                return
            vch_name  = sd.get("vch_name", "")
            package_id = int(sd.get("package_id", 0) or 0)
            pkg = get_package(package_id) if package_id else None
            prefix = (setting_get("brand_title", "") or "GIFT").upper().replace(" ", "")[:6]
            codes = _generate_voucher_codes(count, prefix)
            batch_id = add_voucher_batch(vch_name, "config", None, package_id, codes)
            log_admin_action(uid, f"دسته کارت هدیه (کانفیگ) '{vch_name}' با {count} کد ساخته شد")
            state_clear(uid)
            pkg_label = f"{esc(pkg['name'])} | {fmt_vol(pkg['volume_gb'])} | {fmt_dur(pkg['duration_days'])}" if pkg else "-"
            header = (
                f"✅ <b>کارت هدیه ساخته شد!</b>\n\n"
                f"🎫 نام: {esc(vch_name)}\n"
                f"📦 هدیه: {pkg_label}\n"
                f"📊 تعداد کدها: {count}\n\n"
                "─────────────────────\n"
                "کدها (قابل کپی):\n\n"
            )
            code_lines = [f"<code>{c}</code>" for c in codes]
            _send_codes_to_admin(uid, header, code_lines)
            _render_voucher_admin_list(message, uid)
            return

        # ── Admin: Type add/edit ───────────────────────────────────────────────
        if sn == "admin_add_type" and is_admin(uid):
            name = (message.text or "").strip()
            if not name:
                bot.send_message(uid, "⚠️ نام نوع نمی‌تواند خالی باشد.", reply_markup=back_button("admin:types"))
                return
            state_set(uid, "admin_add_type_emoji", type_name=name)
            import json as _json_ate
            _emoji_kb = _json_ate.dumps({"inline_keyboard": [
                [{"text": "بدون ایموجی", "callback_data": "admin:type:pickemoji:none"}],
                [{"text": "بازگشت", "callback_data": "admin:types", "icon_custom_emoji_id": "5253997076169115797"}],
            ]})
            bot.send_message(uid,
                f"🎨 ایموجی نوع <b>{esc(name)}</b> را ارسال کنید.\n\n"
                "می‌توانید ایموجی ساده یا ایموجی پرمیوم بفرستید.\n"
                "اگر ایموجی نمی‌خواهید، دکمه زیر را بزنید.",
                reply_markup=_emoji_kb)
            return

        if sn == "admin_add_type_emoji" and is_admin(uid):
            text_in = (message.text or "").strip()
            entities = message.entities or []
            emoji_val = _parse_type_emoji(text_in, entities)
            state_set(uid, "admin_add_type_color", type_name=sd["type_name"], type_emoji=emoji_val)
            import json as _json_atc
            _color_kb = _json_atc.dumps({"inline_keyboard": [
                [
                    {"text": "🟢 سبز", "callback_data": "admin:type:pickcolor:green", "style": "success"},
                    {"text": "🔵 آبی", "callback_data": "admin:type:pickcolor:blue", "style": "primary"},
                ],
                [
                    {"text": "🔴 قرمز", "callback_data": "admin:type:pickcolor:red", "style": "danger"},
                    {"text": "⬜ شیشه‌ای", "callback_data": "admin:type:pickcolor:glass"},
                ],
                [{"text": "بازگشت", "callback_data": "admin:types", "icon_custom_emoji_id": "5253997076169115797"}],
            ]})
            bot.send_message(uid, "🎨 رنگ دکمه دسته‌بندی را انتخاب کنید:", reply_markup=_color_kb)
            return

        if sn == "admin_edit_type_emoji" and is_admin(uid):
            from ..db import update_type_emoji as _ute
            text_in = (message.text or "").strip()
            entities = message.entities or []
            emoji_val = _parse_type_emoji(text_in, entities)
            type_id = sd["type_id"]
            _ute(type_id, emoji_val)
            log_admin_action(uid, f"ایموجی نوع #{type_id} ویرایش شد")
            state_clear(uid)
            bot.send_message(uid, "✅ ایموجی نوع سرویس ذخیره شد.")
            _show_admin_types(message)
            return

        if sn == "admin_edit_type" and is_admin(uid):
            new_name = (message.text or "").strip()
            if not new_name:
                bot.send_message(uid, "⚠️ نام معتبر وارد کنید.", reply_markup=back_button("admin:types"))
                return
            update_type(sd["type_id"], new_name)
            log_admin_action(uid, f"نوع #{sd['type_id']} به '{new_name}' ویرایش شد")
            state_clear(uid)
            bot.send_message(uid, "✅ نوع با موفقیت ویرایش شد.")
            _show_admin_types(message)
            return

        if sn == "admin_edit_type_desc" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt
            desc     = (message.text or message.caption or "").strip()
            entities = message.entities or message.caption_entities or []
            update_type_description(sd["type_id"], _spt(desc, entities))
            state_clear(uid)
            bot.send_message(uid, "✅ توضیحات با موفقیت ویرایش شد.")
            _show_admin_types(message)
            return

        if sn == "admin_edit_type_invdesc" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt_id
            from ..db import update_type_invoice_description as _utid
            raw_text = message.text or message.caption or ""
            entities = message.entities or message.caption_entities or []
            # Store raw with premium emoji preserved — do NOT escape
            inv_desc = _spt_id(raw_text.strip(), entities) if raw_text.strip() else ""
            _utid(sd["type_id"], inv_desc)
            log_admin_action(uid, f"توضیحات فاکتور نوع #{sd['type_id']} ویرایش شد")
            state_clear(uid)
            bot.send_message(uid, "✅ توضیحات فاکتور ذخیره شد.")
            _show_admin_types(message)
            return

        if sn == "admin_add_type_invdesc" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt_aid
            from ..db import add_type as _add_type
            raw_text = message.text or message.caption or ""
            entities = message.entities or message.caption_entities or []
            inv_desc = _spt_aid(raw_text.strip(), entities) if raw_text.strip() else ""
            name  = sd.get("type_name", "")
            emoji = sd.get("type_emoji", "")
            color = sd.get("type_color", "glass")
            pmode = sd.get("type_purchase_mode", "step")
            try:
                _add_type(name, "", emoji, color, pmode, inv_desc)
                log_admin_action(uid, f"نوع جدید '{name}' ثبت شد")
                state_clear(uid)
                bot.send_message(uid, "✅ نوع جدید ثبت شد.")
                _show_admin_types(message)
            except Exception as _e_ait:
                if "UNIQUE" in str(_e_ait).upper() or "unique" in str(_e_ait):
                    state_clear(uid)
                    bot.send_message(uid, "⚠️ این نوع قبلاً ثبت شده.")
                else:
                    bot.send_message(uid, f"⚠️ خطا: {_e_ait}")
            return

        if sn == "admin_edit_type_order" and is_admin(uid):
            val = (message.text or "").strip()
            if not val.isdigit() or int(val) < 1:
                bot.send_message(uid, "⚠️ یک عدد صحیح مثبت وارد کنید.", reply_markup=back_button(f"admin:type:edit:{sd['type_id']}"))
                return
            reorder_type(sd["type_id"], int(val))
            log_admin_action(uid, f"جایگاه نوع #{sd['type_id']} به {val} تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, f"✅ جایگاه با موفقیت به <b>{val}</b> تغییر کرد.", parse_mode="HTML")
            _show_admin_types(message)
            return

        # ── Admin: Package add ─────────────────────────────────────────────────
        if sn == "admin_add_package_name" and is_admin(uid):
            name = (message.text or "").strip()
            if not name:
                bot.send_message(uid, "⚠️ نام پکیج معتبر وارد کنید.", reply_markup=back_button("admin:types"))
                return
            state_set(uid, "admin_add_package_show_name", type_id=sd["type_id"], package_name=name)
            kb = types.InlineKeyboardMarkup()
            kb.row(
                types.InlineKeyboardButton("✅ بله", callback_data="admin:pkg:add:sn:1"),
                types.InlineKeyboardButton("❌ خیر", callback_data="admin:pkg:add:sn:0"),
            )
            bot.send_message(uid,
                f"📦 نام پکیج: <b>{esc(name)}</b>\n\n"
                "👁 آیا نام پکیج به کاربر نشان داده شود؟",
                reply_markup=kb)
            return

        if sn == "admin_add_package_volume" and is_admin(uid):
            volume = parse_volume(message.text or "")
            if volume is None:
                bot.send_message(uid, "⚠️ حجم معتبر وارد کنید.", reply_markup=back_button("admin:types"))
                return
            vol_label = "حجم نامحدود" if volume == 0 else fmt_vol(volume)
            state_set(uid, "admin_add_package_duration",
                      type_id=sd["type_id"], package_name=sd["package_name"],
                      volume=volume, show_name=sd.get("show_name", 1))
            bot.send_message(uid,
                f"✅ حجم: <b>{vol_label}</b>\n\n"
                "⏰ مدت پکیج را به روز وارد کنید:\n"
                "💡 برای بدون محدودیت زمانی عدد <b>0</b> بفرستید.",
                reply_markup=back_button("admin:types"))
            return

        if sn == "admin_add_package_duration" and is_admin(uid):
            duration = parse_int(message.text or "")
            if duration is None or duration < 0:
                bot.send_message(uid, "⚠️ مدت معتبر وارد کنید.", reply_markup=back_button("admin:types"))
                return
            dur_label = "زمان نامحدود" if duration == 0 else f"{duration} روز"
            state_set(uid, "admin_add_package_price",
                      type_id=sd["type_id"], package_name=sd["package_name"],
                      volume=sd["volume"], duration=duration,
                      show_name=sd.get("show_name", 1))
            bot.send_message(uid,
                f"✅ مدت: <b>{dur_label}</b>\n\n"
                "💰 قیمت پکیج را به تومان وارد کنید.\nبرای تست رایگان عدد <b>0</b> بفرستید:",
                reply_markup=back_button("admin:types"))
            return

        if sn == "admin_add_package_price" and is_admin(uid):
            price = parse_int(message.text or "")
            if price is None or price < 0:
                bot.send_message(uid, "⚠️ قیمت معتبر وارد کنید.", reply_markup=back_button("admin:types"))
                return
            state_set(uid, "admin_add_package_max_users",
                      type_id=sd["type_id"], package_name=sd["package_name"],
                      volume=sd["volume"], duration=sd["duration"],
                      price=price, show_name=sd.get("show_name", 1))
            bot.send_message(uid,
                f"✅ قیمت: <b>{'رایگان' if price == 0 else fmt_price(price) + ' تومان'}</b>\n\n"
                "👥 محدودیت تعداد کاربر را وارد کنید:\n"
                "💡 برای نامحدود عدد <b>0</b> بفرستید.",
                reply_markup=back_button("admin:types"))
            return

        if sn == "admin_add_package_max_users" and is_admin(uid):
            max_users = parse_int(message.text or "")
            if max_users is None or max_users < 0:
                bot.send_message(uid, "⚠️ عدد معتبر (صفر یا بیشتر) وارد کنید.", reply_markup=back_button("admin:types"))
                return
            mu_label = "نامحدود" if max_users == 0 else f"{max_users} کاربره"
            state_set(uid, "admin_add_package_buyer_role",
                      type_id=sd["type_id"], package_name=sd["package_name"],
                      volume=sd["volume"], duration=sd["duration"],
                      price=sd["price"], show_name=sd.get("show_name", 1),
                      max_users=max_users)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("همه", callback_data="admin:pkg:add:br:all"))
            kb.add(types.InlineKeyboardButton("فقط نمایندگان", callback_data="admin:pkg:add:br:agents"))
            kb.add(types.InlineKeyboardButton("فقط کاربران عادی", callback_data="admin:pkg:add:br:public"))
            kb.add(types.InlineKeyboardButton("هیچ‌کس (فقط هدیه)", callback_data="admin:pkg:add:br:nobody"))
            bot.send_message(uid,
                f"✅ محدودیت کاربر: <b>{mu_label}</b>\n\n"
                "👥 چه کسانی بتوانند این پکیج را بخرند?\n"
                "💡 <i>«هیچ‌کس» یعنی پکیج در خرید عادی نمایش داده نمی‌شود، فقط برای تحویل هدیه زیرمجموعه‌گیری قابل استفاده است.</i>",
                reply_markup=kb)
            return

        # ── Admin: Package panel inbound ID (new package add flow) ─────────────
        if sn == "admin_add_package_port" and is_admin(uid):
            inbound_id_val = parse_int(message.text or "")
            if inbound_id_val is None or inbound_id_val <= 0:
                bot.send_message(uid, "⚠️ شماره ID اینباند معتبر وارد کنید (عدد مثبت مثل 1).", reply_markup=back_button("admin:types"))
                return
            state_set(uid, "admin_add_package_delivery_mode", panel_port=inbound_id_val,
                      **{k: v for k, v in sd.items() if k != "panel_port"})
            kb_dm = types.InlineKeyboardMarkup()
            kb_dm.add(types.InlineKeyboardButton("📄 فقط کانفیگ",      callback_data="admin:pkg:add:dm:config_only"))
            kb_dm.add(types.InlineKeyboardButton("🔗 فقط ساب",          callback_data="admin:pkg:add:dm:sub_only"))
            kb_dm.add(types.InlineKeyboardButton("📄+🔗 کانفیگ + ساب", callback_data="admin:pkg:add:dm:both"))
            bot.send_message(uid,
                f"✅ اینباند ID: <b>{inbound_id_val}</b>\n\n"
                "📤 نحوه تحویل کانفیگ به کاربر را انتخاب کنید:",
                reply_markup=kb_dm)
            return

        # ── Admin: Package panel inbound ID (package edit flow) ─────────────────
        if sn == "admin_edit_pkg_panel_port" and is_admin(uid):
            inbound_id_val = parse_int(message.text or "")
            package_id = sd.get("package_id")
            panel_id   = sd.get("panel_id")
            if inbound_id_val is None or inbound_id_val <= 0:
                bot.send_message(uid, "⚠️ شماره ID اینباند معتبر وارد کنید (عدد مثبت مثل 1).", reply_markup=back_button("admin:types"))
                return
            state_set(uid, "admin_edit_pkg_sdm", package_id=package_id, panel_id=panel_id, panel_port=inbound_id_val)
            kb_dm = types.InlineKeyboardMarkup()
            kb_dm.add(types.InlineKeyboardButton("📄 فقط کانفیگ",      callback_data=f"admin:pkg:sdm:config_only:{package_id}"))
            kb_dm.add(types.InlineKeyboardButton("🔗 فقط ساب",          callback_data=f"admin:pkg:sdm:sub_only:{package_id}"))
            kb_dm.add(types.InlineKeyboardButton("📄+🔗 کانفیگ + ساب", callback_data=f"admin:pkg:sdm:both:{package_id}"))
            bot.send_message(uid,
                f"✅ اینباند ID: <b>{inbound_id_val}</b>\n\n"
                "📤 نحوه تحویل کانفیگ به کاربر را انتخاب کنید:",
                reply_markup=kb_dm)
            return

        # ── Admin: Client Package — inbound ID step ────────────────────────────
        if sn == "cpkg_add_inbound" and is_admin(uid):
            inbound_id_val = parse_int(message.text or "")
            panel_id = sd.get("panel_id")
            if inbound_id_val is None or inbound_id_val <= 0:
                bot.send_message(uid, "⚠️ شماره ID اینباند معتبر وارد کنید (عدد مثبت مثل 1).",
                                 reply_markup=back_button(f"adm:pnl:cpkgs:{panel_id}"))
                return
            state_clear(uid)
            kb_dm = types.InlineKeyboardMarkup()
            kb_dm.add(types.InlineKeyboardButton("📄 فقط کانفیگ",       callback_data=f"adm:pnl:cpkg:dm:config_only:{panel_id}:{inbound_id_val}"))
            kb_dm.add(types.InlineKeyboardButton("🔗 فقط ساب",           callback_data=f"adm:pnl:cpkg:dm:sub_only:{panel_id}:{inbound_id_val}"))
            kb_dm.add(types.InlineKeyboardButton("📄+🔗 کانفیگ + ساب",  callback_data=f"adm:pnl:cpkg:dm:both:{panel_id}:{inbound_id_val}"))
            kb_dm.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:pnl:cpkgs:{panel_id}",
                                                  icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid,
                f"✅ اینباند ID: <b>{inbound_id_val}</b>\n\n"
                "📤 نحوه تحویل کانفیگ در این کلاینت پکیج را انتخاب کنید:",
                parse_mode="HTML", reply_markup=kb_dm)
            return

        # ── Admin: Panel configs search ────────────────────────────────────────
        if sn == "admin_pcfg_search" and is_admin(uid):
            search_text = (message.text or "").strip()
            state_clear(uid)
            from ..admin.renderers import _show_panel_config_list
            _show_panel_config_list(message, filter_type="all", search=search_text if search_text else None)
            return

        # ── Admin: User config list search ────────────────────────────────────
        if sn == "admin_usr_cfg_search" and is_admin(uid):
            search_text = (message.text or "").strip()
            target_user_id = sd.get("target_user_id")
            state_clear(uid)
            if target_user_id:
                from ..handlers.callbacks import _show_admin_user_configs
                _show_admin_user_configs(message, uid, target_user_id, page=0, search=search_text if search_text else "")
            return

        # ── Admin: wallet pay exceptions — search ─────────────────────────────
        if sn == "admin_wallet_exc_search" and is_admin(uid):
            query = (message.text or "").strip()
            state_clear(uid)
            if query:
                state_set(uid, "admin_wallet_exc_search_active", query=query)
            from types import SimpleNamespace as _SN
            fake = _SN(id=None, from_user=message.from_user, message=message, data="adm:ops:wallet_pay_exc")
            from ..handlers.callbacks import _dispatch_callback
            _dispatch_callback(fake, uid, "adm:ops:wallet_pay_exc")
            return

        # ── Admin: wallet pay exceptions — add user ───────────────────────────
        if sn == "admin_wallet_exc_add" and is_admin(uid):
            query = (message.text or "").strip()
            if not query:
                bot.send_message(uid, "⚠️ لطفاً یک مقدار وارد کنید.", parse_mode="HTML",
                                 reply_markup=back_button("adm:ops:wallet_pay_exc"))
                return
            found = search_users(query)[:10]
            if not found:
                bot.send_message(uid, "❌ کاربری یافت نشد.", parse_mode="HTML",
                                 reply_markup=back_button("adm:ops:wallet_pay_exc"))
                return
            kb = types.InlineKeyboardMarkup(row_width=1)
            for u in found:
                name = u["full_name"] or u["username"] or str(u["user_id"])
                kb.add(types.InlineKeyboardButton(
                    f"👤 {name}",
                    callback_data=f"adm:wpe:pick:{u['user_id']}"
                ))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:ops:wallet_pay_exc",
                                              icon_custom_emoji_id="5253997076169115797"))
            state_clear(uid)
            bot.send_message(uid, "👤 <b>کاربر مورد نظر را انتخاب کنید:</b>",
                             parse_mode="HTML", reply_markup=kb)
            return

        # ── Admin: Client Package — sample config step ────────────────────────
        if sn == "cpkg_sample_config" and is_admin(uid):
            sample_config = (message.text or "").strip()
            panel_id   = sd.get("panel_id")
            inbound_id = sd.get("inbound_id")
            mode       = sd.get("mode", "config_only")
            if not sample_config:
                bot.send_message(uid, "⚠️ کانفیگ نمونه نمی‌تواند خالی باشد.",
                                 reply_markup=back_button(f"adm:pnl:cpkgs:{panel_id}"))
                return
            if mode == "config_only":
                # Save directly, no sub URL needed
                from ..db import add_panel_client_package as _acp, get_panel as _gp
                _p = _gp(panel_id)
                inb_name = f"اینباند #{inbound_id}"
                cpkg_id = _acp(panel_id=panel_id, inbound_id=inbound_id,
                                delivery_mode=mode, sample_config=sample_config,
                                sample_sub_url="", name=inb_name)
                state_clear(uid)
                from ..ui.helpers import back_button as _bb
                bot.send_message(uid,
                    f"✅ <b>کلاینت پکیج ذخیره شد</b> (ID: {cpkg_id})\n\n"
                    f"🔌 اینباند: <b>{inbound_id}</b>\n"
                    "📤 تحویل: 📄 فقط کانفیگ\n\n"
                    f"📄 <b>نمونه کانفیگ:</b>\n<code>{esc(sample_config[:200])}</code>",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:pnl:cpkgs:{panel_id}"))
            else:  # both
                state_set(uid, "cpkg_sample_sub",
                          panel_id=panel_id, inbound_id=inbound_id,
                          mode=mode, sample_config=sample_config)
                bot.send_message(uid,
                    "🔗 <b>لینک ساب نمونه</b> را ارسال کنید:\n\n"
                    "یک URL ساب واقعی از این اینباند کپی کنید.\n"
                    "مثال:\n"
                    "<code>http://example.com:2096/sub/abc123xyz456</code>",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:pnl:cpkgs:{panel_id}"))
            return

        # ── Admin: Client Package — sample sub URL step ───────────────────────
        if sn == "cpkg_sample_sub" and is_admin(uid):
            sample_sub = (message.text or "").strip()
            panel_id      = sd.get("panel_id")
            inbound_id    = sd.get("inbound_id")
            mode          = sd.get("mode", "sub_only")
            sample_config = sd.get("sample_config", "")
            if not sample_sub:
                bot.send_message(uid, "⚠️ لینک ساب نمی‌تواند خالی باشد.",
                                 reply_markup=back_button(f"adm:pnl:cpkgs:{panel_id}"))
                return
            from ..db import add_panel_client_package as _acp
            cpkg_id = _acp(panel_id=panel_id, inbound_id=inbound_id,
                            delivery_mode=mode,
                            sample_config=sample_config,
                            sample_sub_url=sample_sub,
                            name=f"اینباند #{inbound_id}")
            state_clear(uid)
            _DM = {"config_only": "📄 فقط کانفیگ", "sub_only": "🔗 فقط ساب", "both": "📄+🔗 هر دو"}
            parts = [
                f"✅ <b>کلاینت پکیج ذخیره شد</b> (ID: {cpkg_id})\n",
                f"🔌 اینباند: <b>{inbound_id}</b>",
                f"📤 تحویل: {_DM.get(mode, mode)}",
            ]
            if sample_config:
                parts.append(f"\n📄 <b>نمونه کانفیگ:</b>\n<code>{esc(sample_config[:200])}</code>")
            if sample_sub:
                parts.append(f"\n🔗 <b>نمونه ساب:</b>\n<code>{esc(sample_sub)}</code>")
            bot.send_message(uid, "\n".join(parts), parse_mode="HTML",
                             reply_markup=back_button(f"adm:pnl:cpkgs:{panel_id}"))
            return

        # ── Admin: Delivery mode wizard — sample config step (edit flow) ──────
        if sn == "cpkg_dm_ef_sample_config" and is_admin(uid):
            sample_config = (message.text or "").strip()
            cpkg_id = sd.get("cpkg_id")
            mode    = sd.get("mode", "config_only")
            if not sample_config:
                bot.send_message(uid, "⚠️ کانفیگ نمونه نمی‌تواند خالی باشد.",
                                 reply_markup=back_button(f"adm:pnl:cpkg:edit:{cpkg_id}"))
                return
            update_panel_client_package_field(cpkg_id, "sample_config", sample_config)
            try:
                from .callbacks import _rebuild_panel_configs_for_cpkg
                rebuilt = _rebuild_panel_configs_for_cpkg(cpkg_id)
                rebuild_note = f"\n🔄 <b>{rebuilt}</b> کانفیگ فروخته‌شده بازسازی شد." if rebuilt else ""
            except Exception as _rb_exc:
                rebuild_note = f"\n⚠️ بازسازی کانفیگ‌های قدیمی ناموفق: {_rb_exc}"
            if mode == "both":
                state_set(uid, "cpkg_dm_ef_sample_sub", cpkg_id=cpkg_id, mode=mode)
                bot.send_message(uid,
                    f"✅ کانفیگ نمونه ذخیره شد.{rebuild_note}\n\n"
                    "🔗 <b>لینک ساب نمونه</b> را ارسال کنید:\n\n"
                    "یک URL ساب واقعی از این اینباند کپی کنید.\n"
                    "مثال:\n"
                    "<code>http://example.com:2096/sub/abc123xyz456</code>",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:pnl:cpkg:edit:{cpkg_id}"))
            else:  # config_only
                state_clear(uid)
                kb_done = types.InlineKeyboardMarkup()
                kb_done.add(types.InlineKeyboardButton("✏️ ویرایش پکیج", callback_data=f"adm:pnl:cpkg:edit:{cpkg_id}"))
                bot.send_message(uid,
                    f"✅ <b>کانفیگ نمونه ذخیره شد.</b>{rebuild_note}\n\n"
                    f"📄 <code>{esc(sample_config[:200])}</code>",
                    parse_mode="HTML", reply_markup=kb_done)
            return

        # ── Admin: Delivery mode wizard — sample sub URL step (edit flow) ──────
        if sn == "cpkg_dm_ef_sample_sub" and is_admin(uid):
            sample_sub = (message.text or "").strip()
            cpkg_id = sd.get("cpkg_id")
            if not sample_sub:
                bot.send_message(uid, "⚠️ لینک ساب نمی‌تواند خالی باشد.",
                                 reply_markup=back_button(f"adm:pnl:cpkg:edit:{cpkg_id}"))
                return
            update_panel_client_package_field(cpkg_id, "sample_sub_url", sample_sub)
            try:
                from .callbacks import _rebuild_panel_configs_for_cpkg
                rebuilt = _rebuild_panel_configs_for_cpkg(cpkg_id)
                rebuild_note = f"\n🔄 <b>{rebuilt}</b> کانفیگ فروخته‌شده بازسازی شد." if rebuilt else ""
            except Exception as _rb_exc:
                rebuild_note = f"\n⚠️ بازسازی کانفیگ‌های قدیمی ناموفق: {_rb_exc}"
            state_clear(uid)
            kb_done = types.InlineKeyboardMarkup()
            kb_done.add(types.InlineKeyboardButton("✏️ ویرایش پکیج", callback_data=f"adm:pnl:cpkg:edit:{cpkg_id}"))
            bot.send_message(uid,
                f"✅ <b>ساب نمونه ذخیره شد.</b>{rebuild_note}\n\n"
                f"🔗 <code>{esc(sample_sub)}</code>",
                parse_mode="HTML", reply_markup=kb_done)
            return

        # ── Admin: Cpkg field edit ─────────────────────────────────────────────
        for _ef_field in ("inbound_id", "sample_config", "sample_sub_url", "sample_client_name"):
            if sn == f"cpkg_ef_{_ef_field}" and is_admin(uid):
                raw     = (message.text or "").strip()
                cpkg_id = sd.get("cpkg_id")
                panel_id = sd.get("panel_id")
                if not raw:
                    bot.send_message(uid, "⚠️ مقدار نمی‌تواند خالی باشد.",
                                     reply_markup=back_button(f"adm:pnl:cpkg:edit:{cpkg_id}"))
                    return
                if _ef_field == "inbound_id":
                    val = parse_int(raw)
                    if val is None:
                        bot.send_message(uid, "⚠️ شماره اینباند باید عدد باشد.",
                                         reply_markup=back_button(f"adm:pnl:cpkg:edit:{cpkg_id}"))
                        return
                else:
                    val = raw
                update_panel_client_package_field(cpkg_id, _ef_field, val)
                state_clear(uid)
                _FIELD_LABELS = {
                    "inbound_id":        "شماره اینباند",
                    "sample_config":     "نمونه کانفیگ",
                    "sample_sub_url":    "نمونه آدرس ساب",
                    "sample_client_name": "نام نمونه در فرگمنت",
                }

                # When the config or sub template changes, rebuild all sold configs
                # that were created from this template so users always see the new format
                if _ef_field in ("sample_config", "sample_sub_url"):
                    try:
                        from .callbacks import _rebuild_panel_configs_for_cpkg
                        rebuilt = _rebuild_panel_configs_for_cpkg(cpkg_id)
                        extra = f"\n🔄 <b>{rebuilt}</b> کانفیگ فروخته‌شده بازسازی شد." if rebuilt else ""
                    except Exception as _rb_exc:
                        extra = f"\n⚠️ بازسازی کانفیگ‌های قدیمی ناموفق: {_rb_exc}"
                else:
                    extra = ""

                bot.send_message(uid,
                    f"✅ <b>{_FIELD_LABELS.get(_ef_field, _ef_field)}</b> بروزرسانی شد.{extra}",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:pnl:cpkg:edit:{cpkg_id}"))
                return

        # ── Admin: Bulk operation amount ──────────────────────────────────────
        if sn == "bulk_amount" and is_admin(uid):
            raw  = (message.text or "").strip()
            val  = parse_int(raw)
            if val is None or val <= 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر (عدد مثبت) وارد کنید.",
                                 reply_markup=back_button("adm:usr:bulk"))
                return
            op          = sd.get("op", "")
            filter_type = sd.get("filter_type", "all")
            selected    = sd.get("selected", [])
            state_clear(uid)

            _FLT = {"all": "همه کاربران", "public": "کاربران عادی", "agents": "نمایندگان", "pick": "کاربران انتخاب‌شده"}
            _OP_L = {"add_balance": "افزودن موجودی", "sub_balance": "کاهش موجودی"}

            if filter_type == "pick":
                count = len(selected)
                sel_str = ",".join(str(x) for x in selected[:50])
                exec_cb = f"adm:bulk:exec:{op}:pick:{sel_str}:{val}"
            else:
                count = count_users_by_filter(filter_type)
                exec_cb = f"adm:bulk:exec:{op}:{filter_type}:{val}"

            from telebot import types as _types
            kb2 = _types.InlineKeyboardMarkup()
            kb2.add(_types.InlineKeyboardButton(
                f"✅ تایید — {_OP_L.get(op, op)} {val:,} تومان به {count} کاربر",
                callback_data=exec_cb))
            kb2.add(_types.InlineKeyboardButton("لغو", callback_data="adm:usr:bulk"))
            bot.send_message(uid,
                f"⚡ <b>تایید عملیات گروهی</b>\n\n"
                f"عملیات: <b>{_OP_L.get(op, op)}</b>\n"
                f"مبلغ: <b>{val:,} تومان</b>\n"
                f"هدف: <b>{_FLT.get(filter_type, filter_type)}</b>\n"
                f"تعداد: <b>{count}</b>",
                parse_mode="HTML",
                reply_markup=kb2)
            return


        if sn == "admin_edit_pkg_field" and is_admin(uid):
            field_key  = sd["field_key"]
            package_id = sd["package_id"]
            db_field_map = {"name": "name", "price": "price", "volume": "volume_gb", "dur": "duration_days", "position": "position", "maxusers": "max_users"}
            db_field   = db_field_map.get(field_key)
            raw        = (message.text or "").strip()
            if field_key == "name":
                if not raw:
                    bot.send_message(uid, "⚠️ نام معتبر وارد کنید.", reply_markup=back_button("admin:types"))
                    return
                update_package_field(package_id, db_field, raw)
            elif field_key == "volume":
                val = parse_volume(raw)
                if val is None:
                    bot.send_message(uid, "⚠️ حجم معتبر وارد کنید (مثلاً <b>0.5</b> یا <b>10</b>).", reply_markup=back_button("admin:types"))
                    return
                update_package_field(package_id, db_field, val)
            else:
                val = parse_int(raw)
                if val is None or (field_key != "position" and val < 0) or (field_key == "position" and val < 1):
                    bot.send_message(uid, "⚠️ مقدار عددی معتبر وارد کنید.", reply_markup=back_button("admin:types"))
                    return
                update_package_field(package_id, db_field, val)
            log_admin_action(uid, f"پکیج #{package_id} فیلد {field_key} ویرایش شد")
            state_clear(uid)
            package_row = get_package(package_id)
            if package_row:
                from .callbacks import _pkg_edit_text_kb as _peth
                from ..ui.helpers import send_or_edit as _soe
                text, kb = _peth(package_row)
                text = "✅ ویرایش انجام شد\n\n" + text.replace("📦 <b>ویرایش پکیج</b>\n\n", "")
                _soe(message, text, kb)
            else:
                bot.send_message(uid, "✅ پکیج با موفقیت ویرایش شد.")
                _show_admin_types(message)
            return

        # ── Admin: Config edit (inline) ────────────────────────────────────────
        if sn == "admin_cfg_edit_svc" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ نام نمی‌تواند خالی باشد.", reply_markup=back_button(f"adm:stk:edt:{sd['config_id']}"))
                return
            update_config_field(sd["config_id"], "service_name", urllib.parse.quote(val))
            log_admin_action(uid, f"نام سرویس کانفیگ #{sd['config_id']} تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, f"✅ نام سرویس تغییر کرد:\n<b>{esc(val)}</b>",
                             reply_markup=back_button(f"adm:stk:cfg:{sd['config_id']}"))
            return

        if sn == "admin_cfg_edit_text" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ متن کانفیگ نمی‌تواند خالی باشد.", reply_markup=back_button(f"adm:stk:edt:{sd['config_id']}"))
                return
            update_config_field(sd["config_id"], "config_text", val)
            log_admin_action(uid, f"متن کانفیگ #{sd['config_id']} بروزرسانی شد")
            state_clear(uid)
            bot.send_message(uid, "✅ متن کانفیگ بروزرسانی شد.",
                             reply_markup=back_button(f"adm:stk:cfg:{sd['config_id']}"))
            return

        if sn == "admin_cfg_edit_inq" and is_admin(uid):
            val = (message.text or "").strip()
            update_config_field(sd["config_id"], "inquiry_link", "" if val == "-" else val)
            log_admin_action(uid, f"لینک استعلام کانفیگ #{sd['config_id']} بروزرسانی شد")
            state_clear(uid)
            bot.send_message(uid, "✅ لینک استعلام بروزرسانی شد.",
                             reply_markup=back_button(f"adm:stk:cfg:{sd['config_id']}"))
            return

        # ── Admin: Config add (legacy single — kept for back-compat) ──────────
        if sn == "admin_add_config_service" and is_admin(uid):
            service_name = (message.text or "").strip()
            if not service_name:
                bot.send_message(uid, "⚠️ نام سرویس را وارد کنید.", reply_markup=back_button("admin:add_config"))
                return
            state_set(uid, "admin_add_config_text",
                      package_id=sd["package_id"], type_id=sd["type_id"], service_name=service_name)
            bot.send_message(uid, "💝 متن کانفیگ را ارسال کنید:", reply_markup=back_button("admin:add_config"))
            return

        if sn == "admin_add_config_text" and is_admin(uid):
            config_text = (message.text or "").strip()
            if not config_text:
                bot.send_message(uid, "⚠️ متن کانفیگ را وارد کنید.", reply_markup=back_button("admin:add_config"))
                return
            state_set(uid, "admin_add_config_link",
                      package_id=sd["package_id"], type_id=sd["type_id"],
                      service_name=sd["service_name"], config_text=config_text)
            bot.send_message(uid, "🔗 لینک استعلام را ارسال کنید.\nاگر ندارید، <code>-</code> بفرستید.",
                             reply_markup=back_button("admin:add_config"))
            return

        if sn == "admin_add_config_link" and is_admin(uid):
            inquiry_link = (message.text or "").strip()
            if inquiry_link == "-":
                inquiry_link = ""
            add_config(sd["type_id"], sd["package_id"], sd["service_name"], sd["config_text"], inquiry_link)
            log_admin_action(uid, f"کانفیگ '{sd['service_name']}' ثبت شد")
            state_clear(uid)
            bot.send_message(uid, "✅ کانفیگ با موفقیت ثبت شد.", reply_markup=kb_admin_panel())
            return

        if sn == "admin_add_config_bulk" and is_admin(uid):
            # Legacy fallback
            state_clear(uid)
            bot.send_message(uid, "⚠️ لطفاً دوباره از منو اقدام کنید.", reply_markup=kb_admin_panel())
            return

        # ── V2Ray: Single — Step 1: service name ──────────────────────────────
        if sn == "v2_single_name" and is_admin(uid):
            service_name = (message.text or "").strip()
            if not service_name:
                bot.send_message(uid, "⚠️ نام سرویس نمی‌تواند خالی باشد.",
                                 reply_markup=back_button(f"adm:v2:single:{sd['package_id']}"))
                return
            mode = sd.get("mode", 1)
            _pnd = sd.get("pending_id")  # preserve for pending-order flow
            if mode == 1:
                state_set(uid, "v2_single_config",
                          package_id=sd["package_id"], type_id=sd["type_id"],
                          mode=mode, service_name=service_name, **({"pending_id": _pnd} if _pnd else {}))
                bot.send_message(uid,
                    "📡 <b>کانفیگ را ارسال کنید:</b>\n\n"
                    "یک لینک کانفیگ (vless/vmess/trojan/ss) وارد کنید:",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:v2:single:{sd['package_id']}"))
            elif mode == 2:
                state_set(uid, "v2_single_config",
                          package_id=sd["package_id"], type_id=sd["type_id"],
                          mode=mode, service_name=service_name, **({"pending_id": _pnd} if _pnd else {}))
                bot.send_message(uid,
                    "📡 <b>کانفیگ را ارسال کنید:</b>\n\n"
                    "یک لینک کانفیگ (vless/vmess/trojan/ss) وارد کنید:",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:v2:single:{sd['package_id']}"))
            else:  # mode 3: sub only
                state_set(uid, "v2_single_sub",
                          package_id=sd["package_id"], type_id=sd["type_id"],
                          mode=mode, service_name=service_name, **({"pending_id": _pnd} if _pnd else {}))
                bot.send_message(uid,
                    "🔗 <b>لینک ساب را ارسال کنید:</b>\n\n"
                    "مثال: <code>http://s1.example.xyz:2096/sub/token123</code>",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:v2:single:{sd['package_id']}"))
            return

        # ── V2Ray: Single — Step 2 (mode 1 & 2): config text ─────────────────
        if sn == "v2_single_config" and is_admin(uid):
            config_text = (message.text or "").strip()
            if not config_text:
                bot.send_message(uid, "⚠️ متن کانفیگ نمی‌تواند خالی باشد.",
                                 reply_markup=back_button(f"adm:v2:single:{sd['package_id']}"))
                return
            mode = sd.get("mode", 1)
            _pnd = sd.get("pending_id")
            if mode == 1:
                state_set(uid, "v2_single_sub",
                          package_id=sd["package_id"], type_id=sd["type_id"],
                          mode=mode, service_name=sd["service_name"],
                          config_text=config_text, **({"pending_id": _pnd} if _pnd else {}))
                bot.send_message(uid,
                    "🔗 <b>لینک ساب را ارسال کنید:</b>\n\n"
                    "مثال: <code>http://s1.example.xyz:2096/sub/token123</code>",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:v2:single:{sd['package_id']}"))
            else:  # mode 2: config only
                svc = sd["service_name"]
                add_config(sd["type_id"], sd["package_id"], svc, config_text, "")
                log_admin_action(uid, f"کانفیگ V2Ray تکی (کانفیگ تنها) '{svc}' ثبت شد")
                auto_fulfilled = 0
                try:
                    auto_fulfilled = auto_fulfill_pending_orders(sd["package_id"])
                except Exception:
                    pass
                # If came from a specific pending order, deliver it specifically too
                if _pnd:
                    try:
                        from ..ui.notifications import _complete_pending_order as _cpo
                        _cpo(_pnd, svc, config_text, "")
                    except Exception:
                        pass
                state_clear(uid)
                msg = (
                    f"✅ <b>کانفیگ با موفقیت ثبت شد.</b>\n\n"
                    f"🔮 نام سرویس: <b>{esc(svc)}</b>\n"
                    f"📌 نوع ثبت: کانفیگ تنها"
                )
                if auto_fulfilled:
                    msg += f"\n\n🚀 <b>{auto_fulfilled}</b> سفارش در انتظار تحویل داده شد."
                bot.send_message(uid, msg, parse_mode="HTML", reply_markup=kb_admin_panel())
            return

        # ── V2Ray: Single — Step 3: sub link ──────────────────────────────────
        if sn == "v2_single_sub" and is_admin(uid):
            sub_link = (message.text or "").strip()
            if not sub_link:
                bot.send_message(uid, "⚠️ لینک ساب نمی‌تواند خالی باشد.",
                                 reply_markup=back_button(f"adm:v2:single:{sd['package_id']}"))
                return
            mode = sd.get("mode", 1)
            svc = sd["service_name"]
            config_text = sd.get("config_text", "")  # empty for sub-only
            _pnd = sd.get("pending_id")

            if mode == 3:
                add_config(sd["type_id"], sd["package_id"], svc, "", sub_link)
                log_admin_action(uid, f"کانفیگ V2Ray تکی (ساب تنها) '{svc}' ثبت شد")
            else:
                add_config(sd["type_id"], sd["package_id"], svc, config_text, sub_link)
                log_admin_action(uid, f"کانفیگ V2Ray تکی (کانفیگ+ساب) '{svc}' ثبت شد")

            auto_fulfilled = 0
            try:
                auto_fulfilled = auto_fulfill_pending_orders(sd["package_id"])
            except Exception:
                pass
            if _pnd:
                try:
                    from ..ui.notifications import _complete_pending_order as _cpo
                    _cpo(_pnd, svc, config_text, sub_link)
                except Exception:
                    pass
            state_clear(uid)
            mode_label = "ساب تنها" if mode == 3 else "کانفیگ + ساب"
            msg = (
                f"✅ <b>کانفیگ با موفقیت ثبت شد.</b>\n\n"
                f"🔮 نام سرویس: <b>{esc(svc)}</b>\n"
                f"📌 نوع ثبت: {mode_label}"
            )
            if auto_fulfilled:
                msg += f"\n\n🚀 <b>{auto_fulfilled}</b> سفارش در انتظار تحویل داده شد."
            bot.send_message(uid, msg, parse_mode="HTML", reply_markup=kb_admin_panel())
            return

        # ── V2Ray: Bulk — prefix input ─────────────────────────────────────────
        if sn == "v2_bulk_pre" and is_admin(uid):
            prefix = (message.text or "").strip()
            pkg_id = sd["package_id"]
            mode   = sd.get("mode", 1)
            _pnd   = sd.get("pending_id")
            state_set(uid, "v2_bulk_suf",
                      package_id=pkg_id, type_id=sd["type_id"],
                      mode=mode, prefix=prefix, **({"pending_id": _pnd} if _pnd else {}))
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏭ بدون پسوند", callback_data=f"adm:v2:bulk:suf:skip:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:v2:bulk:{pkg_id}", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid,
                "✂️ <b>پسوند حذفی از نام کانفیگ</b>\n\n"
                "اگر انتهای نام کانفیگ‌ها متن اضافه‌ای دارد، اینجا وارد کنید.\n\n"
                "💡 مثال: <code>-main</code>\n\n"
                "اگر پسوندی ندارید دکمه «بدون پسوند» را بزنید.",
                parse_mode="HTML", reply_markup=kb)
            return

        # ── V2Ray: Bulk — suffix input ─────────────────────────────────────────
        if sn == "v2_bulk_suf" and is_admin(uid):
            suffix = (message.text or "").strip()
            pkg_id = sd["package_id"]
            mode   = sd.get("mode", 1)
            _pnd   = sd.get("pending_id")
            state_set(uid, "v2_bulk_data",
                      package_id=pkg_id, type_id=sd["type_id"],
                      mode=mode, prefix=sd.get("prefix", ""), suffix=suffix,
                      **({"pending_id": _pnd} if _pnd else {}))
            prompt = _v2_bulk_data_prompt(mode)
            bot.send_message(uid, prompt, parse_mode="HTML",
                             reply_markup=back_button(f"adm:v2:bulk:{pkg_id}"))
            return

        # ── V2Ray: Bulk — receive data ─────────────────────────────────────────
        if sn == "v2_bulk_data" and is_admin(uid):
            raw = _v2_read_raw(message, uid)
            if raw is None:
                return
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            mode       = sd.get("mode", 1)
            prefix     = sd.get("prefix", "")
            suffix     = sd.get("suffix", "")
            type_id    = sd["type_id"]
            package_id = sd["package_id"]
            _pnd_bulk  = sd.get("pending_id")  # for pending-order flow

            if mode == 1:
                # Interleaved: config, sub, config, sub ...
                pairs = []
                i = 0
                while i < len(lines):
                    cfg_line = lines[i]
                    if i + 1 < len(lines) and lines[i + 1].lower().startswith("http"):
                        sub_line = lines[i + 1]
                        i += 2
                    else:
                        sub_line = ""
                        i += 1
                    pairs.append((cfg_line, sub_line))
                _v2_save_bulk(uid, type_id, package_id, pairs,
                              mode=1, prefix=prefix, suffix=suffix, pending_id=_pnd_bulk)

            elif mode == 2:
                # Config+sub separated (large) — step 1: collect configs, wait for subs
                configs_block = [l for l in lines if not l.lower().startswith("http")]
                if not configs_block:
                    bot.send_message(uid,
                        "⚠️ هیچ کانفیگی در متن ارسال‌شده یافت نشد.\n"
                        "مطمئن شوید کانفیگ‌ها در ابتدا آمده‌اند.",
                        parse_mode="HTML",
                        reply_markup=back_button(f"adm:v2:bulk:{package_id}"))
                    return
                state_set(uid, "v2_bulk_configs_large",
                          package_id=package_id, type_id=type_id,
                          prefix=prefix, suffix=suffix,
                          v2_configs=configs_block)
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton(
                    f"✅ {len(configs_block)} کانفیگ دریافت شد — ادامه (ارسال ساب‌ها)",
                    callback_data=f"adm:v2:bm2subs:{package_id}"
                ))
                kb.add(types.InlineKeyboardButton("بازگشت", callback_data=f"adm:v2:bulk:{package_id}", icon_custom_emoji_id="5253997076169115797"))
                bot.send_message(uid,
                    f"✅ <b>{len(configs_block)}</b> کانفیگ دریافت شد.\n\n"
                    "حالا دکمه «ادامه» را بزنید تا ساب‌ها را وارد کنید.",
                    parse_mode="HTML", reply_markup=kb)
                return

            elif mode == 3:
                # Config only — each line is a config
                pairs = [(l, "") for l in lines]
                _v2_save_bulk(uid, type_id, package_id, pairs,
                              mode=3, prefix=prefix, suffix=suffix, pending_id=_pnd_bulk)

            elif mode == 4:
                # Sub only — each line is a sub
                pairs = [("", l) for l in lines]
                _v2_save_bulk(uid, type_id, package_id, pairs,
                              mode=4, prefix="", suffix="", pending_id=_pnd_bulk)
            return

        # ── V2Ray: Bulk Large — receive subs ──────────────────────────────────
        if sn == "v2_bulk_subs_large" and is_admin(uid):
            raw = _v2_read_raw(message, uid)
            if raw is None:
                return
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            configs  = sd.get("v2_configs", [])
            if len(lines) != len(configs):
                bot.send_message(uid,
                    f"❌ <b>خطا: تعداد ساب‌ها با کانفیگ‌ها برابر نیست.</b>\n\n"
                    f"تعداد کانفیگ‌ها: <b>{len(configs)}</b>\n"
                    f"تعداد ساب‌های دریافت‌شده: <b>{len(lines)}</b>\n\n"
                    "لطفاً دوباره ارسال کنید. تعداد ساب‌ها باید دقیقاً برابر کانفیگ‌ها باشد.",
                    parse_mode="HTML",
                    reply_markup=back_button(f"adm:v2:bulk:{sd['package_id']}"))
                return
            pairs = list(zip(configs, lines))
            _v2_save_bulk(uid, sd["type_id"], sd["package_id"], pairs,
                          mode=2, prefix=sd.get("prefix", ""), suffix=sd.get("suffix", ""))
            return

        if sn == "admin_bulk_prefix" and is_admin(uid):
            prefix = (message.text or "").strip()
            pkg_id = sd["package_id"]
            state_set(uid, "admin_bulk_suffix",
                      package_id=sd["package_id"], type_id=sd["type_id"],
                      has_inquiry=sd["has_inquiry"], prefix=prefix)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏭ بعدی (بدون پسوند)", callback_data=f"adm:cfg:bulk:skipsuf:{pkg_id}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:add_config", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid,
                "✂️ <b>پسوند حذفی از نام کانفیگ</b>\n\n"
                "وقتی چندتا <b>اکسترنال پروکسی</b> ست می‌کنید، انتهای نام کانفیگ متن‌های اضافه اکسترنال‌ها اضافه می‌شود.\n"
                "اگر نمی‌خواهید آن‌ها در نام کانفیگ بیاید، پسوند را اینجا وارد کنید.\n\n"
                "💡 مثال: <code>-main</code>",
                reply_markup=kb)
            return

        if sn == "admin_bulk_suffix" and is_admin(uid):
            suffix = (message.text or "").strip()
            has_inq = sd.get("has_inquiry", False)
            prefix = sd.get("prefix", "")
            state_set(uid, "admin_bulk_data",
                      package_id=sd["package_id"], type_id=sd["type_id"],
                      has_inquiry=has_inq, prefix=prefix, suffix=suffix)
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
            bot.send_message(uid, fmt_text, reply_markup=back_button("admin:add_config"))
            return

        if sn == "admin_bulk_data" and is_admin(uid):
            # ── Extract raw text from message or TXT file ──
            raw = ""
            if message.document:
                # User sent a file — only accept .txt
                doc = message.document
                fname = (doc.file_name or "").lower()
                if not fname.endswith(".txt"):
                    bot.send_message(uid, "⚠️ فقط فایل با فرمت <b>.txt</b> پشتیبانی می‌شود.", parse_mode="HTML",
                                     reply_markup=back_button("admin:add_config"))
                    return
                try:
                    file_info = bot.get_file(doc.file_id)
                    downloaded = bot.download_file(file_info.file_path)
                    raw = downloaded.decode("utf-8", errors="ignore").strip()
                except Exception:
                    bot.send_message(uid, "⚠️ خطا در دانلود فایل. لطفاً دوباره ارسال کنید.",
                                     reply_markup=back_button("admin:add_config"))
                    return
            else:
                raw = (message.text or "").strip()

            if not raw:
                bot.send_message(uid, "⚠️ متنی ارسال نشده.", reply_markup=back_button("admin:add_config"))
                return
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            has_inq = sd.get("has_inquiry", False)
            prefix = sd.get("prefix", "")
            suffix = sd.get("suffix", "")
            type_id = sd["type_id"]
            package_id = sd["package_id"]

            configs = []
            if has_inq:
                # Pair lines: config, inquiry, config, inquiry...
                i = 0
                while i < len(lines):
                    cfg_line = lines[i]
                    inq_line = lines[i + 1] if i + 1 < len(lines) and lines[i + 1].lower().startswith("http") else ""
                    configs.append((cfg_line, inq_line))
                    i += 2 if inq_line else 1
            else:
                for line in lines:
                    configs.append((line, ""))

            success_count = 0
            success_names = []
            errors = []
            for idx, (cfg_text, inq_link) in enumerate(configs, 1):
                # Extract name from after #
                if "#" in cfg_text:
                    raw_name = cfg_text.rsplit("#", 1)[1]
                else:
                    raw_name = f"config-{idx}"
                # URL-decode the name
                try:
                    svc_name = urllib.parse.unquote(raw_name)
                except Exception:
                    svc_name = raw_name
                # Strip prefix
                if prefix and svc_name.startswith(prefix):
                    svc_name = svc_name[len(prefix):]
                # Also try URL-decoded prefix
                if prefix:
                    try:
                        decoded_prefix = urllib.parse.unquote(prefix)
                        if decoded_prefix != prefix and svc_name.startswith(decoded_prefix):
                            svc_name = svc_name[len(decoded_prefix):]
                    except Exception:
                        pass
                # Strip suffix
                if suffix and svc_name.endswith(suffix):
                    svc_name = svc_name[:-len(suffix)]
                if suffix:
                    try:
                        decoded_suffix = urllib.parse.unquote(suffix)
                        if decoded_suffix != suffix and svc_name.endswith(decoded_suffix):
                            svc_name = svc_name[:-len(decoded_suffix)]
                    except Exception:
                        pass
                svc_name = svc_name.strip().strip("-").strip("_").strip()
                if not svc_name:
                    svc_name = f"config-{idx}"
                if not cfg_text:
                    errors.append(f"کانفیگ {idx}: متن خالی")
                    continue
                try:
                    add_config(type_id, package_id, svc_name, cfg_text, inq_link)
                    success_count += 1
                    success_names.append(svc_name)
                except Exception as e:
                    errors.append(f"کانفیگ {idx}: {str(e)}")

            # Auto-fulfill any waiting pending orders for this package
            auto_fulfilled = 0
            auto_fulfill_err = ""
            if success_count > 0:
                try:
                    auto_fulfilled = auto_fulfill_pending_orders(package_id)
                except Exception as e:
                    auto_fulfill_err = str(e)

            state_clear(uid)
            if success_count > 0:
                log_admin_action(uid, f"{success_count} کانفیگ دسته‌جمعی برای پکیج #{package_id} ثبت شد")
            result = f"✅ <b>{success_count}</b> کانفیگ با موفقیت ثبت شد."
            if success_names:
                names_text = "\n".join(f"  • {esc(n)}" for n in success_names)
                result += f"\n\n📝 <b>نام کانفیگ‌های ثبت‌شده:</b>\n{names_text}"
            if auto_fulfilled > 0:
                result += f"\n\n🚀 <b>{auto_fulfilled}</b> سفارش در انتظار به صورت خودکار تحویل داده شد."
            if auto_fulfill_err:
                result += f"\n\n⚠️ خطا در تحویل سفارش‌های در انتظار:\n<code>{esc(auto_fulfill_err)}</code>"
            if errors:
                result += "\n\n❌ خطاها:\n" + "\n".join(errors[:20])
            bot.send_message(uid, result, reply_markup=kb_admin_panel())
            return

        # ── OpenVPN: Single — collect .ovpn files ────────────────────────────
        if sn == "ovpn_single_file" and is_admin(uid):
            # Accept .ovpn document; accumulate multiple files
            if message.document:
                doc   = message.document
                fname = (doc.file_name or "").lower()
                if not fname.endswith(".ovpn"):
                    bot.send_message(uid, "⚠️ فقط فایل با فرمت <b>.ovpn</b> پذیرفته می‌شود.", parse_mode="HTML")
                    return
                files = sd.get("ovpn_files", [])
                files.append(doc.file_id)
                state_set(uid, "ovpn_single_file", package_id=sd["package_id"], ovpn_files=files)
                done_kb = types.InlineKeyboardMarkup()
                done_kb.add(types.InlineKeyboardButton(
                    f"✅ فایل‌ها کامل‌اند ({len(files)} فایل) — ادامه",
                    callback_data=f"adm:ovpn:single_done:{sd['package_id']}"
                ))
                bot.send_message(uid,
                    f"✅ فایل <code>{esc(doc.file_name)}</code> دریافت شد. (مجموع: {len(files)})\n"
                    "اگر فایل دیگری دارید ارسال کنید، وگرنه دکمه ادامه را بزنید.",
                    reply_markup=done_kb)
            else:
                bot.send_message(uid, "⚠️ لطفاً فایل <code>.ovpn</code> ارسال کنید.", parse_mode="HTML")
            return

        # ── OpenVPN: Single — after files done ───────────────────────────────
        if sn == "ovpn_single_username" and is_admin(uid):
            username = (message.text or "").strip()
            if not username:
                bot.send_message(uid, "⚠️ نام کاربری را وارد کنید.")
                return
            state_set(uid, "ovpn_single_password",
                      package_id=sd["package_id"], ovpn_files=sd.get("ovpn_files", []),
                      ovpn_username=username)
            bot.send_message(uid, "🔑 <b>Password</b> اکانت را وارد کنید:", parse_mode="HTML")
            return

        if sn == "ovpn_single_password" and is_admin(uid):
            password = (message.text or "").strip()
            if not password:
                bot.send_message(uid, "⚠️ رمز عبور را وارد کنید.")
                return
            state_set(uid, "ovpn_single_inquiry",
                      package_id=sd["package_id"], ovpn_files=sd.get("ovpn_files", []),
                      ovpn_username=sd["ovpn_username"], ovpn_password=password)
            skip_kb = types.InlineKeyboardMarkup()
            skip_kb.add(types.InlineKeyboardButton("⏭ Skip (بدون لینک استعلام)", callback_data=f"adm:ovpn:sinq_skip:{sd['package_id']}"))
            bot.send_message(uid,
                "🔋 <b>لینک استعلام حجم</b> را وارد کنید یا Skip بزنید:\n"
                "(مثال: <code>http://panel.example.com/sub/abc</code>)",
                reply_markup=skip_kb, parse_mode="HTML")
            return

        if sn == "ovpn_single_inquiry" and is_admin(uid):
            inquiry = (message.text or "").strip()
            _ovpn_finish_single(uid, sd, inquiry)
            return

        # ── OpenVPN: Bulk shared — collect .ovpn files ───────────────────────
        if sn == "ovpn_bulk_shared_file" and is_admin(uid):
            if message.document:
                doc   = message.document
                fname = (doc.file_name or "").lower()
                if not fname.endswith(".ovpn"):
                    bot.send_message(uid, "⚠️ فقط فایل با فرمت <b>.ovpn</b> پذیرفته می‌شود.", parse_mode="HTML")
                    return
                files = sd.get("shared_files", [])
                files.append(doc.file_id)
                state_set(uid, "ovpn_bulk_shared_file", package_id=sd["package_id"], shared_files=files)
                done_kb = types.InlineKeyboardMarkup()
                done_kb.add(types.InlineKeyboardButton(
                    f"✅ فایل‌ها کامل‌اند ({len(files)} فایل) — ادامه",
                    callback_data=f"adm:ovpn:sharedok:{sd['package_id']}"
                ))
                bot.send_message(uid,
                    f"✅ فایل <code>{esc(doc.file_name)}</code> دریافت شد. (مجموع: {len(files)})\n"
                    "فایل دیگر ارسال کنید یا دکمه زیر را بزنید.",
                    reply_markup=done_kb, parse_mode="HTML")
            else:
                bot.send_message(uid, "⚠️ لطفاً فایل <code>.ovpn</code> ارسال کنید.", parse_mode="HTML")
            return

        # ── OpenVPN: Bulk shared — account list (text) ───────────────────────
        if sn == "ovpn_bulk_shared_data" and is_admin(uid):
            raw     = (message.text or "").strip()
            has_inq = sd.get("has_inquiry", False)
            lines   = [l for l in raw.splitlines() if l.strip()]
            step    = 3 if has_inq else 2
            if len(lines) % step != 0:
                expected = "۳ خطی (username / password / volume web)" if has_inq else "۲ خطی (username / password)"
                bot.send_message(uid,
                    f"⚠️ تعداد خطوط ({len(lines)}) با فرمت {expected} مطابقت ندارد.\n"
                    "لطفاً دوباره ارسال کنید.")
                return
            accounts = []
            for i in range(0, len(lines), step):
                acc = {"username": lines[i], "password": lines[i + 1],
                       "inquiry": lines[i + 2] if has_inq else ""}
                accounts.append(acc)
            shared_files = sd.get("shared_files", [])
            pkg_row = get_package(sd["package_id"])
            _ovpn_deliver_bulk_shared(uid, pkg_row, shared_files, accounts)
            state_clear(uid)
            return

        # ── OpenVPN: Bulk diff — how many accounts ────────────────────────────
        if sn == "ovpn_bulk_diff_count" and is_admin(uid):
            total = parse_int(message.text or "")
            if not total or total <= 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.")
                return
            state_set(uid, "ovpn_bulk_diff_files",
                      package_id=sd["package_id"], total_accts=total,
                      acct_files={}, current_acct=1, pending_acct_files=[])
            done_kb = types.InlineKeyboardMarkup()
            done_kb.add(types.InlineKeyboardButton(
                "✅ فایل‌های اکانت ۱ کامل‌اند",
                callback_data=f"adm:ovpn:diffok:{sd['package_id']}:1"
            ))
            bot.send_message(uid,
                f"📎 فایل‌های <code>.ovpn</code> <b>اکانت ۱</b> از {total} را ارسال کنید:",
                reply_markup=done_kb, parse_mode="HTML")
            return

        # ── OpenVPN: Bulk diff — collect per-account files ───────────────────
        if sn == "ovpn_bulk_diff_files" and is_admin(uid):
            if message.document:
                doc   = message.document
                fname = (doc.file_name or "").lower()
                if not fname.endswith(".ovpn"):
                    bot.send_message(uid, "⚠️ فقط فایل با فرمت <b>.ovpn</b> پذیرفته می‌شود.", parse_mode="HTML")
                    return
                pending = sd.get("pending_acct_files", [])
                pending.append(doc.file_id)
                current = sd.get("current_acct", 1)
                state_set(uid, "ovpn_bulk_diff_files",
                          package_id=sd["package_id"], total_accts=sd.get("total_accts", 0),
                          acct_files=sd.get("acct_files", {}), current_acct=current,
                          pending_acct_files=pending)
                done_kb = types.InlineKeyboardMarkup()
                done_kb.add(types.InlineKeyboardButton(
                    f"✅ فایل‌های اکانت {current} کامل‌اند",
                    callback_data=f"adm:ovpn:diffok:{sd['package_id']}:{current}"
                ))
                bot.send_message(uid,
                    f"✅ فایل <code>{esc(doc.file_name)}</code> برای اکانت {current} دریافت شد. (مجموع: {len(pending)})",
                    reply_markup=done_kb, parse_mode="HTML")
            else:
                bot.send_message(uid, "⚠️ لطفاً فایل <code>.ovpn</code> ارسال کنید.", parse_mode="HTML")
            return

        # ── OpenVPN: Bulk diff — account list (text) ──────────────────────────
        if sn == "ovpn_bulk_diff_data" and is_admin(uid):
            raw        = (message.text or "").strip()
            has_inq    = sd.get("has_inquiry", False)
            lines      = [l for l in raw.splitlines() if l.strip()]
            total      = sd.get("total_accts", 0)
            step       = 3 if has_inq else 2
            if len(lines) != total * step:
                expected = f"{total * step}"
                bot.send_message(uid,
                    f"⚠️ تعداد خطوط ({len(lines)}) با {total} اکانت × {step} خط = {expected} خط مطابقت ندارد.\n"
                    "لطفاً دوباره درست وارد کنید.")
                return
            accounts = []
            for i in range(0, len(lines), step):
                acc = {"username": lines[i], "password": lines[i + 1],
                       "inquiry": lines[i + 2] if has_inq else ""}
                accounts.append(acc)
            acct_files = sd.get("acct_files", {})
            pkg_row    = get_package(sd["package_id"])
            _ovpn_deliver_bulk_diff(uid, pkg_row, acct_files, accounts)
            state_clear(uid)
            return

        # ── WireGuard: Single — collect files ─────────────────────────────────
        if sn == "wg_single_file" and is_admin(uid):
            if message.document:
                doc   = message.document
                fname = (doc.file_name or "")
                files = sd.get("wg_files", [])
                names = sd.get("wg_names", [])
                files.append(doc.file_id)
                names.append(fname)
                state_set(uid, "wg_single_file",
                          package_id=sd["package_id"], wg_files=files, wg_names=names)
                done_kb = types.InlineKeyboardMarkup()
                done_kb.add(types.InlineKeyboardButton(
                    f"✅ فایل‌ها کامل‌اند ({len(files)} فایل) — ادامه",
                    callback_data=f"adm:wg:single_done:{sd['package_id']}"
                ))
                bot.send_message(uid,
                    f"✅ فایل <code>{esc(fname)}</code> دریافت شد. (مجموع: {len(files)})\n"
                    "فایل دیگر ارسال کنید یا دکمه ادامه را بزنید.",
                    reply_markup=done_kb, parse_mode="HTML")
            else:
                bot.send_message(uid, "⚠️ لطفاً فایل کانفیگ WireGuard را ارسال کنید.",
                                 parse_mode="HTML")
            return

        # ── WireGuard: Single — inquiry text ─────────────────────────────────
        if sn == "wg_single_inquiry" and is_admin(uid):
            inquiry = (message.text or "").strip()
            _wg_finish_single(uid, sd, inquiry)
            return

        # ── WireGuard: Single — text config input ─────────────────────────────
        if sn == "wg_single_text" and is_admin(uid):
            config_text = (message.text or "").strip()
            if not config_text or "[Interface]" not in config_text:
                bot.send_message(uid,
                    "⚠️ متن کانفیگ معتبر نیست.\n"
                    "لطفاً یک کانفیگ WireGuard کامل (با بخش <code>[Interface]</code>) ارسال کنید.",
                    parse_mode="HTML")
                return
            file_id, fname = _wg_upload_conf(uid, config_text)
            state_set(uid, "wg_single_sub_yn",
                      package_id=sd["package_id"],
                      wg_files=[file_id], wg_names=[fname],
                      wg_config_text=config_text)
            sub_kb = types.InlineKeyboardMarkup()
            sub_kb.row(
                types.InlineKeyboardButton("✅ بله، دارد", callback_data=f"adm:wg:sinq:y:{sd['package_id']}"),
                types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:wg:sinq:n:{sd['package_id']}"),
            )
            bot.send_message(uid,
                f"✅ فایل <code>{esc(fname)}</code> ساخته شد.\n\n"
                "🔗 آیا این کانفیگ <b>لینک ساب</b> دارد؟",
                reply_markup=sub_kb, parse_mode="HTML")
            return

        # ── WireGuard: Bulk text — how many configs ───────────────────────────
        if sn == "wg_bulk_text_count" and is_admin(uid):
            total = parse_int(message.text or "")
            if not total or total <= 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.")
                return
            state_set(uid, "wg_bulk_text_collect",
                      package_id=sd["package_id"],
                      total_accts=total,
                      collected_texts=[], collected_names=[])
            bot.send_message(uid,
                f"✏️ <b>پیام ۱ از {total}:</b>\n"
                "متن کانفیگ اول را ارسال کنید:",
                parse_mode="HTML")
            return

        # ── WireGuard: Bulk text — collect config texts ───────────────────────
        if sn == "wg_bulk_text_collect" and is_admin(uid):
            config_text = (message.text or "").strip()
            if not config_text or "[Interface]" not in config_text:
                bot.send_message(uid,
                    "⚠️ متن کانفیگ معتبر نیست.\n"
                    "لطفاً یک کانفیگ WireGuard کامل (با بخش <code>[Interface]</code>) ارسال کنید.",
                    parse_mode="HTML")
                return
            total    = sd.get("total_accts", 0)
            texts    = sd.get("collected_texts", [])
            names_l  = sd.get("collected_names", [])
            fids     = sd.get("collected_file_ids", [])
            # Upload .conf file
            file_id, fname = _wg_upload_conf(uid, config_text)
            texts.append(config_text)
            names_l.append(fname)
            fids.append(file_id)
            current = len(texts)
            if current < total:
                state_set(uid, "wg_bulk_text_collect",
                          package_id=sd["package_id"],
                          total_accts=total,
                          collected_texts=texts,
                          collected_names=names_l,
                          collected_file_ids=fids)
                bot.send_message(uid,
                    f"✅ کانفیگ {current} دریافت شد.\n\n"
                    f"✏️ <b>پیام {current + 1} از {total}:</b>\n"
                    "متن کانفیگ بعدی را ارسال کنید:",
                    parse_mode="HTML")
            else:
                # All collected → build acct_files/acct_names/acct_texts
                acct_files = {i + 1: [fids[i]] for i in range(total)}
                acct_names = {i + 1: [names_l[i]] for i in range(total)}
                acct_texts = {i + 1: texts[i] for i in range(total)}
                state_set(uid, "wg_bulk_text_sub_yn",
                          package_id=sd["package_id"],
                          total_accts=total,
                          acct_files=acct_files,
                          acct_names=acct_names,
                          acct_texts=acct_texts)
                sub_kb = types.InlineKeyboardMarkup()
                sub_kb.row(
                    types.InlineKeyboardButton("✅ بله، دارند", callback_data=f"adm:wg:btextsub:y:{sd['package_id']}"),
                    types.InlineKeyboardButton("❌ خیر", callback_data=f"adm:wg:btextsub:n:{sd['package_id']}"),
                )
                bot.send_message(uid,
                    f"✅ همه {total} کانفیگ دریافت شد.\n\n"
                    "🔗 آیا کانفیگ‌ها <b>لینک ساب</b> دارند؟",
                    reply_markup=sub_kb, parse_mode="HTML")
            return

        # ── WireGuard: Bulk text — sub link collection ────────────────────────
        if sn == "wg_bulk_text_sub" and is_admin(uid):
            raw   = (message.text or "").strip()
            total = sd.get("total_accts", 0)
            inquiries = [l.strip() for l in raw.splitlines() if l.strip()]
            if len(inquiries) != total:
                bot.send_message(uid,
                    f"⚠️ تعداد لینک‌های ساب ({len(inquiries)}) با تعداد کانفیگ‌ها ({total}) مطابقت ندارد.\n"
                    "لطفاً دوباره وارد کنید.")
                return
            pkg_row = get_package(sd["package_id"])
            _wg_deliver_bulk_diff(uid, pkg_row,
                                  sd.get("acct_files", {}),
                                  sd.get("acct_names", {}),
                                  inquiries,
                                  sd.get("acct_texts", {}))
            state_clear(uid)
            return


        if sn == "wg_bulk_shared_file" and is_admin(uid):
            if message.document:
                doc   = message.document
                fname = (doc.file_name or "")
                files = sd.get("shared_files", [])
                names = sd.get("shared_names", [])
                files.append(doc.file_id)
                names.append(fname)
                state_set(uid, "wg_bulk_shared_file",
                          package_id=sd["package_id"], shared_files=files, shared_names=names)
                done_kb = types.InlineKeyboardMarkup()
                done_kb.add(types.InlineKeyboardButton(
                    f"✅ فایل‌ها کامل‌اند ({len(files)} فایل) — ادامه",
                    callback_data=f"adm:wg:sharedok:{sd['package_id']}"
                ))
                bot.send_message(uid,
                    f"✅ فایل <code>{esc(fname)}</code> دریافت شد. (مجموع: {len(files)})\n"
                    "فایل دیگر ارسال کنید یا دکمه زیر را بزنید.",
                    reply_markup=done_kb, parse_mode="HTML")
            else:
                bot.send_message(uid, "⚠️ لطفاً فایل کانفیگ WireGuard را ارسال کنید.",
                                 parse_mode="HTML")
            return

        # ── WireGuard: Bulk shared — inquiry links list OR count ──────────────
        if sn == "wg_bulk_shared_data" and is_admin(uid):
            raw     = (message.text or "").strip()
            has_inq = sd.get("has_inquiry", False)
            pkg_row = get_package(sd["package_id"])
            if has_inq:
                inquiries = [l.strip() for l in raw.splitlines() if l.strip()]
                if not inquiries:
                    bot.send_message(uid, "⚠️ لیست لینک‌های استعلام خالی است.")
                    return
                _wg_deliver_bulk_shared(uid, pkg_row,
                                        sd.get("shared_files", []),
                                        sd.get("shared_names", []),
                                        inquiries)
            else:
                # No inquiry: user types a count
                count = parse_int(raw)
                if not count or count <= 0:
                    bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.")
                    return
                _wg_deliver_bulk_shared(uid, pkg_row,
                                        sd.get("shared_files", []),
                                        sd.get("shared_names", []),
                                        [""] * count)
            state_clear(uid)
            return

        # ── WireGuard: Bulk diff — how many configs ───────────────────────────
        if sn == "wg_bulk_diff_count" and is_admin(uid):
            total = parse_int(message.text or "")
            if not total or total <= 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.")
                return
            state_set(uid, "wg_bulk_diff_files",
                      package_id=sd["package_id"], total_accts=total,
                      acct_files={}, acct_names={}, current_acct=1,
                      pending_acct_files=[], pending_acct_names=[])
            done_kb = types.InlineKeyboardMarkup()
            done_kb.add(types.InlineKeyboardButton(
                "✅ فایل‌های کانفیگ ۱ کامل‌اند",
                callback_data=f"adm:wg:diffok:{sd['package_id']}:1"
            ))
            bot.send_message(uid,
                f"📎 فایل‌های <b>کانفیگ ۱</b> از {total} را ارسال کنید:",
                reply_markup=done_kb, parse_mode="HTML")
            return

        # ── WireGuard: Bulk diff — collect per-config files ───────────────────
        if sn == "wg_bulk_diff_files" and is_admin(uid):
            if message.document:
                doc   = message.document
                fname = (doc.file_name or "")
                pending_files = sd.get("pending_acct_files", [])
                pending_names = sd.get("pending_acct_names", [])
                pending_files.append(doc.file_id)
                pending_names.append(fname)
                current = sd.get("current_acct", 1)
                state_set(uid, "wg_bulk_diff_files",
                          package_id=sd["package_id"], total_accts=sd.get("total_accts", 0),
                          acct_files=sd.get("acct_files", {}), acct_names=sd.get("acct_names", {}),
                          current_acct=current,
                          pending_acct_files=pending_files, pending_acct_names=pending_names)
                done_kb = types.InlineKeyboardMarkup()
                done_kb.add(types.InlineKeyboardButton(
                    f"✅ فایل‌های کانفیگ {current} کامل‌اند",
                    callback_data=f"adm:wg:diffok:{sd['package_id']}:{current}"
                ))
                bot.send_message(uid,
                    f"✅ فایل <code>{esc(fname)}</code> برای کانفیگ {current} دریافت شد. (مجموع: {len(pending_files)})",
                    reply_markup=done_kb, parse_mode="HTML")
            else:
                bot.send_message(uid, "⚠️ لطفاً فایل کانفیگ WireGuard را ارسال کنید.",
                                 parse_mode="HTML")
            return

        # ── WireGuard: Bulk diff — inquiry links list ─────────────────────────
        if sn == "wg_bulk_diff_data" and is_admin(uid):
            raw     = (message.text or "").strip()
            has_inq = sd.get("has_inquiry", False)
            total   = sd.get("total_accts", 0)
            if has_inq:
                inquiries = [l.strip() for l in raw.splitlines() if l.strip()]
                if len(inquiries) != total:
                    bot.send_message(uid,
                        f"⚠️ تعداد لینک‌های استعلام ({len(inquiries)}) با تعداد کانفیگ‌ها ({total}) مطابقت ندارد.\n"
                        "لطفاً دوباره وارد کنید.")
                    return
            else:
                inquiries = []
            pkg_row = get_package(sd["package_id"])
            _wg_deliver_bulk_diff(uid, pkg_row,
                                  sd.get("acct_files", {}),
                                  sd.get("acct_names", {}),
                                  inquiries)
            state_clear(uid)
            return

        # ── Admin: Settings ────────────────────────────────────────────────────
        if sn == "admin_set_support" and is_admin(uid):
            setting_set("support_username", (message.text or "").strip())
            log_admin_action(uid, "آیدی پشتیبانی تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ آیدی پشتیبانی ذخیره شد.", reply_markup=back_button("adm:sup"))
            return

        if sn == "admin_set_support_link" and is_admin(uid):
            val = (message.text or "").strip()
            setting_set("support_link", "" if val == "-" else val)
            log_admin_action(uid, "لینک پشتیبانی تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ لینک پشتیبانی ذخیره شد.", reply_markup=back_button("adm:sup"))
            return

        if sn == "admin_set_support_desc" and is_admin(uid):
            val = (message.text or "").strip()
            setting_set("support_link_desc", "" if val == "-" else val)
            log_admin_action(uid, "توضیحات پشتیبانی تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ توضیحات پشتیبانی ذخیره شد.", reply_markup=back_button("adm:sup"))
            return

        # ── New dynamic support system state handlers ──────────────────────────
        if sn == "admin_sup_faq_edit" and is_admin(uid):
            raw = message.text or message.caption or ""
            ents = message.entities or message.caption_entities or []
            from ..ui.premium_emoji import serialize_premium_text as _spt
            _serialized = _spt(raw, ents)
            setting_set("support_faq_text", _serialized)
            log_admin_action(uid, "متن سوالات متداول پشتیبانی ذخیره شد")
            state_clear(uid)
            _pe_count = sum(1 for e in (ents or []) if getattr(e, "type", "") == "custom_emoji")
            _confirm = "✅ متن سوالات متداول ذخیره شد."
            if _pe_count:
                _confirm += f"\n\n<code>ایموجی پرمیوم: {_pe_count} عدد</code>"
            bot.send_message(uid, _confirm, parse_mode="HTML", reply_markup=back_button("adm:sup:faq"))
            return

        if sn == "admin_sup_add_title" and is_admin(uid):
            title = (message.text or "").strip()
            if not title:
                bot.send_message(uid, "⚠️ متن دکمه نمی‌تواند خالی باشد.",
                                 reply_markup=back_button("adm:sup"))
                return
            state_set(uid, "admin_sup_add_emoji", sup_title=title)
            import json as _json_ae
            _ae_kb = _json_ae.dumps({"inline_keyboard": [
                [{"text": "بدون ایموجی", "callback_data": "adm:sup:add:noemoji"}],
                [{"text": "بازگشت", "callback_data": "adm:sup",
                  "icon_custom_emoji_id": "5253997076169115797"}],
            ]})
            bot.send_message(uid,
                "🎨 <b>مرحله ۲ از ۴: ایموجی دکمه</b>\n\n"
                "ایموجی دکمه را ارسال کنید یا «بدون ایموجی» را انتخاب کنید.\n\n"
                "• عدد emoji_id: فقط عدد را بفرستید\n"
                "• تگ &lt;tg-emoji&gt;: همان را بفرستید\n"
                "• ایموجی عادی: همان را بفرستید\n"
                "• «ندارد» یا «بدون»: بدون ایموجی",
                parse_mode="HTML", reply_markup=_ae_kb)
            return

        if sn == "admin_sup_add_emoji" and is_admin(uid):
            text_in = (message.text or "").strip()
            entities = message.entities or []
            emoji_val = _parse_type_emoji(text_in, entities)
            _cur_sd = state_data(uid)
            state_set(uid, "admin_sup_add_color",
                      sup_title=_cur_sd.get("sup_title", ""),
                      sup_emoji=emoji_val)
            import json as _json_ac
            _ac_kb = _json_ac.dumps({"inline_keyboard": [
                [{"text": "⬜ پیش‌فرض", "callback_data": "adm:sup:add:color:default"}],
                [{"text": "🔵 آبی",   "callback_data": "adm:sup:add:color:blue"},
                 {"text": "🟢 سبز",   "callback_data": "adm:sup:add:color:green"},
                 {"text": "🔴 قرمز", "callback_data": "adm:sup:add:color:red"}],
                [{"text": "بازگشت", "callback_data": "adm:sup",
                  "icon_custom_emoji_id": "5253997076169115797"}],
            ]})
            bot.send_message(uid,
                "🎨 <b>مرحله ۳ از ۴: رنگ دکمه</b>\n\n"
                "رنگ دکمه را انتخاب کنید.\n\n"
                "<i>رنگ برای قالب‌هایی که پشتیبانی کنند نمایش داده می‌شود.</i>",
                parse_mode="HTML", reply_markup=_ac_kb)
            return

        if sn == "admin_sup_add_url" and is_admin(uid):
            url_in = (message.text or "").strip()
            if url_in.startswith("@"):
                url_in = "https://t.me/" + url_in[1:]
            if not (url_in.startswith("http://") or url_in.startswith("https://")):
                bot.send_message(uid,
                    "⚠️ لینک باید با https:// یا http:// شروع شود.\n"
                    "@username هم قابل قبول است.\n\nدوباره وارد کنید:")
                return
            _cur_sd = state_data(uid)
            import re as _re_su, json as _json_ap
            _tag_re = _re_su.compile(r'<[^>]+>')
            _emoji_disp = _tag_re.sub("", _cur_sd.get("sup_emoji", "")).strip()
            _btn_preview = ((_emoji_disp + " ") if _emoji_disp else "") + _cur_sd["sup_title"]
            state_set(uid, "admin_sup_add_preview",
                      sup_title=_cur_sd["sup_title"],
                      sup_emoji=_cur_sd.get("sup_emoji", ""),
                      sup_color=_cur_sd.get("sup_color", "default"),
                      sup_url=url_in)
            _ap_kb = _json_ap.dumps({"inline_keyboard": [
                [{"text": "✅ تأیید و ذخیره", "callback_data": "adm:sup:add:confirm"}],
                [{"text": "❌ لغو", "callback_data": "adm:sup:add:cancel"}],
            ]})
            bot.send_message(uid,
                f"<b>مرحله ۴ از ۴: تأیید نهایی</b>\n\n"
                f"📌 دکمه: <b>{esc(_btn_preview)}</b>\n"
                f"🔗 لینک: <code>{esc(url_in)}</code>\n"
                f"🎨 رنگ: {esc(_cur_sd.get('sup_color', 'default'))}\n\n"
                "آیا اطلاعات صحیح است؟",
                parse_mode="HTML", reply_markup=_ap_kb)
            return

        if sn == "admin_sup_edit_title" and is_admin(uid):
            title = (message.text or "").strip()
            if not title:
                bot.send_message(uid, "⚠️ متن نمی‌تواند خالی باشد.")
                return
            _cur_sd = state_data(uid)
            from ..db import update_support_method_field as _usmf
            _usmf(_cur_sd["method_id"], "title", title)
            log_admin_action(uid, f"متن دکمه روش پشتیبانی #{_cur_sd['method_id']} ویرایش شد")
            state_clear(uid)
            bot.send_message(uid, "✅ متن دکمه ذخیره شد.",
                             reply_markup=back_button(f"adm:sup:m:{_cur_sd['method_id']}"))
            return

        if sn == "admin_sup_edit_emoji" and is_admin(uid):
            text_in = (message.text or "").strip()
            entities = message.entities or []
            emoji_val = _parse_type_emoji(text_in, entities)
            _cur_sd = state_data(uid)
            from ..db import update_support_method_field as _usmf2
            _usmf2(_cur_sd["method_id"], "emoji", emoji_val)
            log_admin_action(uid, f"ایموجی روش پشتیبانی #{_cur_sd['method_id']} ویرایش شد")
            state_clear(uid)
            bot.send_message(uid, "✅ ایموجی ذخیره شد.",
                             reply_markup=back_button(f"adm:sup:m:{_cur_sd['method_id']}"))
            return

        if sn == "admin_sup_edit_url" and is_admin(uid):
            url_in = (message.text or "").strip()
            if url_in.startswith("@"):
                url_in = "https://t.me/" + url_in[1:]
            if not (url_in.startswith("http://") or url_in.startswith("https://")):
                bot.send_message(uid,
                    "⚠️ لینک باید با https:// یا http:// شروع شود.\n"
                    "@username هم قابل قبول است.\n\nدوباره وارد کنید:")
                return
            _cur_sd = state_data(uid)
            from ..db import update_support_method_field as _usmf3
            _usmf3(_cur_sd["method_id"], "url", url_in)
            log_admin_action(uid, f"لینک روش پشتیبانی #{_cur_sd['method_id']} ویرایش شد")
            state_clear(uid)
            bot.send_message(uid, "✅ لینک ذخیره شد.",
                             reply_markup=back_button(f"adm:sup:m:{_cur_sd['method_id']}"))
            return

        # ── Referral settings inputs ───────────────────────────────────────────
        if sn == "admin_ref_banner" and is_admin(uid):
            if message.photo:
                photo_id = message.photo[-1].file_id
                caption = (message.caption or "").strip()
                setting_set("referral_banner_photo", photo_id)
                setting_set("referral_banner_text", caption)
            else:
                setting_set("referral_banner_text", (message.text or "").strip())
                setting_set("referral_banner_photo", "")
            log_admin_action(uid, "بنر اشتراک‌گذاری تنظیم شد")
            state_clear(uid)
            bot.send_message(uid, "✅ بنر اشتراک‌گذاری ذخیره شد.", reply_markup=back_button("adm:ref:settings"))
            return

        if sn == "admin_ref_sr_count" and is_admin(uid):
            count = parse_int(message.text or "")
            if not count or count <= 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.", reply_markup=back_button("adm:ref:settings"))
                return
            setting_set("referral_start_reward_count", str(count))
            log_admin_action(uid, f"تعداد زیرمجموعه هدیه استارت: {count}")
            state_clear(uid)
            bot.send_message(uid, f"✅ تعداد زیرمجموعه برای هدیه استارت: {count}", reply_markup=back_button("adm:ref:settings"))
            return

        if sn == "admin_ref_sr_amount" and is_admin(uid):
            amount = parse_int(message.text or "")
            if amount is None or amount < 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر وارد کنید.", reply_markup=back_button("adm:ref:settings"))
                return
            setting_set("referral_start_reward_amount", str(amount))
            log_admin_action(uid, f"مبلغ هدیه استارت: {amount} تومان")
            state_clear(uid)
            bot.send_message(uid, f"✅ مبلغ هدیه استارت: {fmt_price(amount)} تومان", reply_markup=back_button("adm:ref:settings"))
            return

        if sn == "admin_ref_pr_count" and is_admin(uid):
            count = parse_int(message.text or "")
            if not count or count <= 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.", reply_markup=back_button("adm:ref:settings"))
                return
            setting_set("referral_purchase_reward_count", str(count))
            log_admin_action(uid, f"تعداد خرید هدیه: {count}")
            state_clear(uid)
            bot.send_message(uid, f"✅ تعداد خرید برای هدیه: {count}", reply_markup=back_button("adm:ref:settings"))
            return

        if sn == "admin_ref_pr_amount" and is_admin(uid):
            amount = parse_int(message.text or "")
            if amount is None or amount < 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر وارد کنید.", reply_markup=back_button("adm:ref:settings"))
                return
            setting_set("referral_purchase_reward_amount", str(amount))
            log_admin_action(uid, f"مبلغ هدیه خرید: {amount} تومان")
            state_clear(uid)
            bot.send_message(uid, f"✅ مبلغ هدیه خرید: {fmt_price(amount)} تومان", reply_markup=back_button("adm:ref:settings"))
            return

        if sn == "admin_ref_btn_title" and is_admin(uid):
            raw = (message.text or "").strip()
            if raw.lower() == "default":
                setting_set("referral_button_title", "")
                log_admin_action(uid, "نام دکمه دعوت دوستان به پیش‌فرض بازگشت")
                state_clear(uid)
                bot.send_message(uid, "✅ نام دکمه به پیش‌فرض بازگشت.", reply_markup=back_button("adm:ref:settings"))
            elif not raw:
                bot.send_message(uid, "⚠️ نام دکمه نمی‌تواند خالی باشد.", reply_markup=back_button("adm:ref:settings"))
            else:
                setting_set("referral_button_title", raw)
                log_admin_action(uid, f"نام دکمه دعوت دوستان: {raw}")
                state_clear(uid)
                bot.send_message(uid, f"✅ نام دکمه تنظیم شد: {esc(raw)}", parse_mode="HTML", reply_markup=back_button("adm:ref:settings"))
            return

        if sn == "admin_ref_ir_amount" and is_admin(uid):
            amount = parse_int(message.text or "")
            if amount is None or amount < 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر وارد کنید.", reply_markup=back_button("adm:ref:settings"))
                return
            setting_set("ref_invitee_reward_amount", str(amount))
            log_admin_action(uid, f"مبلغ جایزه دعوت‌شونده: {amount} تومان")
            state_clear(uid)
            bot.send_message(uid, f"✅ مبلغ جایزه دعوت‌شونده: {fmt_price(amount)} تومان", reply_markup=back_button("adm:ref:settings"))
            return

        # ── Anti-Spam Settings ────────────────────────────────────────────────
        if sn == "admin_ref_as_window" and is_admin(uid):
            val = parse_int(normalize_text_number(message.text or ""))
            if not val or val <= 0:
                bot.send_message(uid,
                    "⚠️ <b>مقدار نامعتبر است.</b>\n\nیک عدد مثبت (ثانیه) وارد کنید. مثال: ۱۵",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:ref:antispam"))
                return
            setting_set("referral_antispam_window", str(val))
            log_admin_action(uid, f"بازه زمانی ضد اسپم: {val} ثانیه")
            state_clear(uid)
            bot.send_message(uid,
                f"✅ بازه زمانی ضد اسپم به <b>{val} ثانیه</b> تنظیم شد.",
                parse_mode="HTML",
                reply_markup=back_button("adm:ref:antispam"))
            return

        if sn == "admin_ref_as_threshold" and is_admin(uid):
            val = parse_int(normalize_text_number(message.text or ""))
            if not val or val <= 0:
                bot.send_message(uid,
                    "⚠️ <b>مقدار نامعتبر است.</b>\n\nتعداد دعوت مثبت وارد کنید. مثال: ۱۰",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:ref:antispam"))
                return
            setting_set("referral_antispam_threshold", str(val))
            log_admin_action(uid, f"آستانه ضد اسپم: {val} دعوت")
            state_clear(uid)
            bot.send_message(uid,
                f"✅ آستانه ضد اسپم به <b>{val} دعوت</b> تنظیم شد.",
                parse_mode="HTML",
                reply_markup=back_button("adm:ref:antispam"))
            return

        if sn == "admin_ref_restriction_add_uid" and is_admin(uid):
            raw = (message.text or "").strip()
            # Try to resolve user from ID or username
            target_user = None
            if raw.isdigit():
                target_user = get_user(int(raw))
                if target_user:
                    target_uid = int(raw)
                else:
                    target_uid = int(raw)  # unknown user, still allow
            else:
                uname = raw.lstrip("@")
                results = search_users(uname) if uname else []
                if results:
                    target_user = results[0]
                    target_uid = target_user["user_id"]
                else:
                    bot.send_message(uid,
                        "⚠️ <b>کاربری با این مشخصات یافت نشد.</b>\n\n"
                        "لطفاً شناسه عددی (User ID) یا نام کاربری را دقیق وارد کنید.",
                        parse_mode="HTML",
                        reply_markup=back_button("adm:ref:restrictions:0"))
                    return
            # Ask for restriction type via inline buttons
            from telebot import types as _t
            kb2 = _t.InlineKeyboardMarkup()
            kb2.add(_t.InlineKeyboardButton(
                "⛔ محدود از زیرمجموعه‌گیری",
                callback_data=f"adm:ref:restrictions:settype:{target_uid}:referral_only"
            ))
            kb2.add(_t.InlineKeyboardButton(
                "🚫 محدود کامل از ربات",
                callback_data=f"adm:ref:restrictions:settype:{target_uid}:full"
            ))
            kb2.add(_t.InlineKeyboardButton(
                "بازگشت", callback_data="adm:ref:restrictions:0",
                icon_custom_emoji_id="5253997076169115797"
            ))
            name_fa = (target_user["full_name"] if target_user else "") or str(target_uid)
            state_clear(uid)
            bot.send_message(uid,
                f"👤 <b>کاربر پیدا شد:</b> {esc(name_fa)} (<code>{target_uid}</code>)\n\n"
                "نوع محدودیت را انتخاب کنید:",
                parse_mode="HTML",
                reply_markup=kb2)
            return

        # ── Bulk sale qty limits ──────────────────────────────────────────────
        if sn == "admin_bulk_min_qty" and is_admin(uid):
            val = parse_int(normalize_text_number(message.text or ""))
            if not val or val <= 0:
                bot.send_message(uid,
                    "⚠️ <b>مقدار نامعتبر است.</b>\n\nلطفاً یک عدد صحیح و مثبت وارد کنید (مثلاً ۱).",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:ops:bulk_menu"))
                return
            _, cur_max = get_bulk_qty_limits()
            if cur_max > 0 and val > cur_max:
                bot.send_message(uid,
                    f"⚠️ <b>حداقل نمی‌تواند بیشتر از حداکثر ({cur_max}) باشد.</b>\n\n"
                    "لطفاً مقدار کمتری وارد کنید.",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:ops:bulk_menu"))
                return
            setting_set("bulk_min_qty", str(val))
            log_admin_action(uid, f"حداقل تعداد فروش عمده: {val}")
            state_clear(uid)
            bot.send_message(uid,
                f"✅ <b>حداقل تعداد خرید به {val} عدد تنظیم شد.</b>",
                parse_mode="HTML",
                reply_markup=back_button("adm:ops:bulk_menu"))
            return

        if sn == "admin_bulk_max_qty" and is_admin(uid):
            raw_text = normalize_text_number(message.text or "")
            val = parse_int(raw_text)
            if val is None or val < 0:
                bot.send_message(uid,
                    "⚠️ <b>مقدار نامعتبر است.</b>\n\n"
                    "یک عدد صحیح مثبت وارد کنید، یا <b>0</b> برای «بدون محدودیت».",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:ops:bulk_menu"))
                return
            cur_min, _ = get_bulk_qty_limits()
            if val > 0 and val < cur_min:
                bot.send_message(uid,
                    f"⚠️ <b>حداکثر نمی‌تواند کمتر از حداقل ({cur_min}) باشد.</b>\n\n"
                    "لطفاً مقدار بیشتری وارد کنید یا 0 برای بدون محدودیت.",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:ops:bulk_menu"))
                return
            setting_set("bulk_max_qty", str(val))
            log_admin_action(uid, f"حداکثر تعداد فروش عمده: {val if val > 0 else 'نامحدود'}")
            state_clear(uid)
            label = "بدون محدودیت" if val == 0 else f"{val} عدد"
            bot.send_message(uid,
                f"✅ <b>حداکثر تعداد خرید به {label} تنظیم شد.</b>",
                parse_mode="HTML",
                reply_markup=back_button("adm:ops:bulk_menu"))
            return

        if sn == "admin_set_invoice_expiry_minutes" and is_admin(uid):
            raw_text = normalize_text_number(message.text or "")
            val = parse_int(raw_text)
            if not val or val <= 0:
                bot.send_message(uid,
                    "⚠️ <b>مقدار نامعتبر است.</b>\n\n"
                    "لطفاً یک عدد صحیح مثبت وارد کنید (مثلاً ۳۰).",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:ops:invoice_expiry"))
                return
            setting_set("invoice_expiry_minutes", str(val))
            log_admin_action(uid, f"مدت اعتبار فاکتور پرداخت: {val} دقیقه")
            state_clear(uid)
            bot.send_message(uid,
                f"✅ <b>مدت اعتبار فاکتور به {val} دقیقه تنظیم شد.</b>",
                parse_mode="HTML",
                reply_markup=back_button("adm:ops:invoice_expiry"))
            return

        if sn == "admin_set_card" and is_admin(uid):
            setting_set("payment_card", normalize_text_number(message.text or ""))
            log_admin_action(uid, "شماره کارت تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ شماره کارت ذخیره شد.", reply_markup=back_button("adm:set:gw:card"))
            return

        if sn == "admin_set_bank" and is_admin(uid):
            setting_set("payment_bank", (message.text or "").strip())
            log_admin_action(uid, "نام بانک تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ نام بانک ذخیره شد.", reply_markup=back_button("adm:set:gw:card"))
            return

        if sn == "admin_set_owner" and is_admin(uid):
            setting_set("payment_owner", (message.text or "").strip())
            log_admin_action(uid, "نام صاحب کارت تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ نام صاحب کارت ذخیره شد.", reply_markup=back_button("adm:set:gw:card"))
            return

        if sn == "admin_card_add_number" and is_admin(uid):
            raw = normalize_text_number((message.text or "").strip())
            if not raw or len(raw) < 16:
                bot.send_message(uid, "⚠️ شماره کارت معتبر وارد کنید (حداقل ۱۶ رقم).",
                                 reply_markup=back_button("adm:gw:card:cards"))
                return
            state_set(uid, "admin_card_add_bank", card_number=raw)
            bot.send_message(uid, "🏦 نام بانک را ارسال کنید:", reply_markup=back_button("adm:gw:card:cards"))
            return

        if sn == "admin_card_add_bank" and is_admin(uid):
            bank = (message.text or "").strip()
            state_set(uid, "admin_card_add_bank_emoji", card_number=sd["card_number"], bank_name=bank)
            bot.send_message(uid, "ایموجی بانک را ارسال کنید:\n(مثلاً 💙 برای بلوبانک، 🟢 برای ملت و ...)", reply_markup=back_button("adm:gw:card:cards"))
            return

        if sn == "admin_card_add_bank_emoji" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt_bk
            emoji_text = (message.text or "").strip()
            emoji_ents = message.entities or []
            emoji_stored = _spt_bk(emoji_text, emoji_ents) if emoji_text else ""
            bank_name_base = sd.get("bank_name", "")
            bank_with_emoji = f"{bank_name_base} {emoji_stored}".strip() if emoji_stored else bank_name_base
            state_set(uid, "admin_card_add_holder", card_number=sd["card_number"], bank_name=bank_with_emoji)
            bot.send_message(uid, "👤 نام صاحب کارت را ارسال کنید:", reply_markup=back_button("adm:gw:card:cards"))
            return

        if sn == "admin_card_add_holder" and is_admin(uid):
            holder = (message.text or "").strip()
            add_payment_card(sd["card_number"], sd.get("bank_name", ""), holder)
            log_admin_action(uid, f"کارت جدید اضافه شد: {sd['card_number']}")
            state_clear(uid)
            bot.send_message(uid, "✅ کارت با موفقیت اضافه شد.", reply_markup=back_button("adm:gw:card:cards"))
            return

        if sn == "admin_card_edit_number" and is_admin(uid):
            card_id = sd["card_id"]
            raw = normalize_text_number((message.text or "").strip())
            if not raw or len(raw) < 16:
                bot.send_message(uid, "⚠️ شماره کارت معتبر وارد کنید.",
                                 reply_markup=back_button(f"adm:gw:card:cards:cfg:{card_id}"))
                return
            state_set(uid, "admin_card_edit_bank", card_id=card_id, card_number=raw)
            bot.send_message(uid, "🏦 نام بانک جدید را ارسال کنید:",
                             reply_markup=back_button(f"adm:gw:card:cards:cfg:{card_id}"))
            return

        if sn == "admin_card_edit_bank" and is_admin(uid):
            bank = (message.text or "").strip()
            state_set(uid, "admin_card_edit_bank_emoji", card_id=sd["card_id"],
                      card_number=sd["card_number"], bank_name=bank)
            bot.send_message(uid, "ایموجی بانک را ارسال کنید:\n(مثلاً 💙 برای بلوبانک، 🟢 برای ملت و ...)",
                             reply_markup=back_button(f"adm:gw:card:cards:cfg:{sd['card_id']}"))
            return

        if sn == "admin_card_edit_bank_emoji" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt_bk2
            emoji_text = (message.text or "").strip()
            emoji_ents = message.entities or []
            emoji_stored = _spt_bk2(emoji_text, emoji_ents) if emoji_text else ""
            bank_name_base = sd.get("bank_name", "")
            bank_with_emoji = f"{bank_name_base} {emoji_stored}".strip() if emoji_stored else bank_name_base
            state_set(uid, "admin_card_edit_holder", card_id=sd["card_id"],
                      card_number=sd["card_number"], bank_name=bank_with_emoji)
            bot.send_message(uid, "👤 نام صاحب کارت جدید را ارسال کنید:",
                             reply_markup=back_button(f"adm:gw:card:cards:cfg:{sd['card_id']}"))
            return

        if sn == "admin_card_edit_holder" and is_admin(uid):
            holder = (message.text or "").strip()
            update_payment_card(sd["card_id"], sd["card_number"], sd.get("bank_name", ""), holder)
            log_admin_action(uid, f"کارت {sd['card_id']} ویرایش شد")
            state_clear(uid)
            bot.send_message(uid, "✅ مشخصات کارت به‌روزرسانی شد.",
                             reply_markup=back_button(f"adm:gw:card:cards:cfg:{sd['card_id']}"))
            return

        if sn == "admin_gw_set_fee_val" and is_admin(uid):
            gw = sd.get("gw", "")
            fee_type = setting_get(f"gw_{gw}_fee_type", "fixed")
            raw_val = normalize_text_number(message.text or "").strip().replace(",", ".")
            try:
                val = float(raw_val) if fee_type == "pct" else parse_int(raw_val)
            except Exception:
                val = 0
            if not val or val <= 0 or (fee_type == "pct" and val > 100):
                bot.send_message(uid, "⚠️ مقدار نامعتبر است.", reply_markup=back_button(f"adm:gw:{gw}:fee"))
                return
            val_text = str(int(val)) if isinstance(val, float) and val.is_integer() else str(val)
            setting_set(f"gw_{gw}_fee_value", val_text)
            log_admin_action(uid, f"کارمزد درگاه {gw}: {val}")
            state_clear(uid)
            bot.send_message(uid, f"✅ مقدار کارمزد تنظیم شد: {val_text}", reply_markup=back_button(f"adm:gw:{gw}:fee"))
            return

        if sn == "admin_gw_set_bonus_val" and is_admin(uid):
            gw = sd.get("gw", "")
            bonus_type = setting_get(f"gw_{gw}_bonus_type", "fixed")
            raw_val = normalize_text_number(message.text or "").strip().replace(",", ".")
            try:
                val = float(raw_val) if bonus_type == "pct" else parse_int(raw_val)
            except Exception:
                val = 0
            if not val or val <= 0 or (bonus_type == "pct" and val > 100):
                bot.send_message(uid, "⚠️ مقدار نامعتبر است.", reply_markup=back_button(f"adm:gw:{gw}:bonus"))
                return
            val_text = str(int(val)) if isinstance(val, float) and val.is_integer() else str(val)
            setting_set(f"gw_{gw}_bonus_value", val_text)
            log_admin_action(uid, f"بونس درگاه {gw}: {val}")
            state_clear(uid)
            bot.send_message(uid, f"✅ مقدار بونس تنظیم شد: {val_text}", reply_markup=back_button(f"adm:gw:{gw}:bonus"))
            return

        if sn == "admin_set_gw_fee_percent" and is_admin(uid):
            gw = sd.get("gw", "")
            raw = (message.text or "").strip().replace(",", ".")
            try:
                val = float(raw)
                assert 0 <= val <= 100
            except Exception:
                bot.send_message(uid, "⚠️ درصد معتبر وارد کنید (مثال: 2.5):", reply_markup=back_button(f"adm:gw:{gw}:feebonus"))
                return
            setting_set(f"gw_{gw}_fee_percent", str(val))
            # also sync to generic fee system so calculations work
            setting_set(f"gw_{gw}_fee_type", "pct")
            setting_set(f"gw_{gw}_fee_value", str(int(val)) if val == int(val) else str(val))
            log_admin_action(uid, f"درصد کارمزد درگاه {gw}: {val}%")
            state_clear(uid)
            bot.send_message(uid, f"✅ درصد کارمزد ذخیره شد: {val}%", reply_markup=back_button(f"adm:gw:{gw}:feebonus"))
            return

        if sn == "admin_set_gw_bonus_percent" and is_admin(uid):
            gw = sd.get("gw", "")
            raw = (message.text or "").strip().replace(",", ".")
            try:
                val = float(raw)
                assert 0 <= val <= 100
            except Exception:
                bot.send_message(uid, "⚠️ درصد معتبر وارد کنید (مثال: 5):", reply_markup=back_button(f"adm:gw:{gw}:feebonus"))
                return
            setting_set(f"gw_{gw}_bonus_percent", str(val))
            # also sync to generic bonus system so calculations work
            setting_set(f"gw_{gw}_bonus_type", "pct")
            setting_set(f"gw_{gw}_bonus_value", str(int(val)) if val == int(val) else str(val))
            log_admin_action(uid, f"درصد بونس درگاه {gw}: {val}%")
            state_clear(uid)
            bot.send_message(uid, f"✅ درصد بونس ذخیره شد: {val}%", reply_markup=back_button(f"adm:gw:{gw}:feebonus"))
            return

        if sn == "admin_set_crypto_wallet" and is_admin(uid):
            coin_key = sd["coin_key"]
            val      = (message.text or "").strip()
            setting_set(f"crypto_{coin_key}", "" if val == "-" else val)
            log_admin_action(uid, f"آدرس ولت {coin_key} تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ آدرس ولت ذخیره شد.", reply_markup=back_button("adm:set:gw:crypto"))
            return

        if sn == "admin_set_tetrapay_key" and is_admin(uid):
            val = (message.text or "").strip()
            setting_set("tetrapay_api_key", val)
            log_admin_action(uid, "کلید API تتراپی تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API تتراپی ذخیره شد.", reply_markup=back_button("adm:set:gw:tetrapay"))
            return

        if sn == "admin_set_swapwallet_crypto_key" and is_admin(uid):
            val = (message.text or "").strip()
            setting_set("swapwallet_crypto_api_key", val)
            log_admin_action(uid, "کلید API سواپ‌ولت کریپتو تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API سواپ ولت (کریپتو) ذخیره شد.", reply_markup=back_button("adm:set:gw:swapwallet_crypto"))
            return

        if sn == "admin_set_swapwallet_crypto_username" and is_admin(uid):
            val = (message.text or "").strip()
            setting_set("swapwallet_crypto_username", "" if val == "-" else val)
            log_admin_action(uid, "نام کاربری سواپ‌ولت کریپتو تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ نام کاربری فروشگاه سواپ ولت (کریپتو) ذخیره شد.", reply_markup=back_button("adm:set:gw:swapwallet_crypto"))
            return

        if sn == "admin_set_gw_display_name" and is_admin(uid):
            gw = sd.get("gw", "")
            val = (message.text or "").strip()
            setting_set(f"gw_{gw}_display_name", "" if val == "-" else val)
            log_admin_action(uid, f"نام نمایشی درگاه {gw} تغییر کرد")
            state_clear(uid)
            msg = "✅ نام نمایشی درگاه ذخیره شد." if val != "-" else "✅ نام نمایشی به پیش‌فرض بازگشت داده شد."
            bot.send_message(uid, msg, reply_markup=back_button(f"adm:set:gw:{gw}"))
            return

        if sn == "admin_set_tronpays_rial_key" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ کلید API نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:tronpays_rial"))
                return
            setting_set("tronpays_rial_api_key", val)
            log_admin_action(uid, "کلید API TronPays تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API TronPays ذخیره شد.", reply_markup=back_button("adm:set:gw:tronpays_rial"))
            return

        if sn == "admin_set_pazzlenet_key" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ کلید API نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:pazzlenet"))
                return
            setting_set("pazzlenet_api_key", val)
            log_admin_action(uid, "کلید API PazzleNet تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API PazzleNet ذخیره شد.", reply_markup=back_button("adm:set:gw:pazzlenet"))
            return

        if sn == "admin_set_tronado_key" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ کلید API نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:tronado"))
                return
            setting_set("tronado_api_key", val)
            log_admin_action(uid, "کلید API ترونادو تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API ترونادو ذخیره شد.", reply_markup=back_button("adm:set:gw:tronado"))
            return

        if sn == "admin_set_tronado_wallet" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ آدرس کیف پول نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:tronado"))
                return
            setting_set("tronado_wallet_address", val)
            log_admin_action(uid, "آدرس کیف پول ترونادو تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ آدرس کیف پول ترون ذخیره شد.", reply_markup=back_button("adm:set:gw:tronado"))
            return

        if sn == "admin_set_tronado_cb_url" and is_admin(uid):
            val = (message.text or "").strip()
            if val and not val.startswith("https://"):
                bot.send_message(uid, "⚠️ Callback URL باید با <code>https://</code> شروع شود. دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:tronado"))
                return
            setting_set("tronado_callback_url", val)
            log_admin_action(uid, f"Callback URL ترونادو تغییر کرد: {val}")
            state_clear(uid)
            bot.send_message(uid, f"✅ Callback URL ذخیره شد:\n<code>{esc(val) if val else 'حذف شد'}</code>", reply_markup=back_button("adm:set:gw:tronado"))
            return

        if sn == "admin_set_centralpay_key" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ کلید API نمی‌تواند خالی باشد.", reply_markup=back_button("adm:set:gw:centralpay"))
                return
            setting_set("centralpay_api_key", val)
            log_admin_action(uid, "کلید API سنترال‌پی تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API سنترال‌پی ذخیره شد.", reply_markup=back_button("adm:set:gw:centralpay"))
            return

        if sn == "admin_set_centralpay_link_type" and is_admin(uid):
            val = (message.text or "").strip()
            if val == "-":
                val = "deposit"
            if not val:
                bot.send_message(uid, "⚠️ نوع لینک نمی‌تواند خالی باشد.", reply_markup=back_button("adm:set:gw:centralpay"))
                return
            if len(val) > 50 or any(ch.isspace() for ch in val):
                bot.send_message(uid, "⚠️ نوع لینک باید یک مقدار کوتاه بدون فاصله باشد. مثال: <code>deposit</code>", reply_markup=back_button("adm:set:gw:centralpay"))
                return
            setting_set("centralpay_link_type", val)
            log_admin_action(uid, f"نوع لینک getLink سنترال‌پی تغییر کرد: {val}")
            state_clear(uid)
            bot.send_message(uid, f"✅ نوع لینک سنترال‌پی ذخیره شد:\n<code>{esc(val)}</code>", reply_markup=back_button("adm:set:gw:centralpay"))
            return

        if sn == "admin_set_centralpay_cb_url" and is_admin(uid):
            val = (message.text or "").strip()
            if val == "-":
                val = ""
            if val and not (val.startswith("https://") or val.startswith("http://")):
                bot.send_message(uid, "⚠️ URL باید با <code>https://</code> شروع شود.", reply_markup=back_button("adm:set:gw:centralpay"))
                return
            setting_set("centralpay_callback_base_url", val)
            log_admin_action(uid, f"Callback Base URL سنترال‌پی تغییر کرد: {val or '(حذف شد)'}")
            state_clear(uid)
            bot.send_message(uid, f"✅ Callback Base URL ذخیره شد:\n<code>{esc(val) if val else 'حذف شد'}</code>", reply_markup=back_button("adm:set:gw:centralpay"))
            return

        if sn == "admin_set_tronpays_rial_cb_url" and is_admin(uid):
            val = (message.text or "").strip()
            if val and not (val.startswith("http://") or val.startswith("https://")):
                bot.send_message(uid, "⚠️ URL باید با <code>https://</code> یا <code>http://</code> شروع شود:", reply_markup=back_button("adm:set:gw:tronpays_rial"))
                return
            setting_set("tronpays_rial_callback_url", val)
            log_admin_action(uid, "Callback URL TronPays تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, f"✅ Callback URL ذخیره شد:\n<code>{val or 'https://example.com/'}</code>", reply_markup=back_button("adm:set:gw:tronpays_rial"))
            return

        if sn == "admin_set_rialpay_key" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ کلید API نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:rialpay"))
                return
            setting_set("rialpay_api_key", val)
            log_admin_action(uid, "کلید API ریال‌پی تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API ریال‌پی ذخیره شد.", reply_markup=back_button("adm:set:gw:rialpay"))
            return

        if sn == "admin_set_rialpay_webhook_secret" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ Webhook Secret نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:rialpay"))
                return
            setting_set("rialpay_webhook_secret", val)
            log_admin_action(uid, "Webhook Secret ریال‌پی تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ Webhook Secret ریال‌پی ذخیره شد.", reply_markup=back_button("adm:set:gw:rialpay"))
            return

        if sn == "admin_set_rialpay_cb_url" and is_admin(uid):
            val = (message.text or "").strip().rstrip("/")
            if val and not (val.startswith("http://") or val.startswith("https://")):
                bot.send_message(uid, "⚠️ URL باید با <code>https://</code> یا <code>http://</code> شروع شود:", reply_markup=back_button("adm:set:gw:rialpay"))
                return
            setting_set("rialpay_callback_base_url", val)
            log_admin_action(uid, "Callback Base URL ریال‌پی تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, f"✅ Callback Base URL ریال‌پی ذخیره شد:\n<code>{esc(val or '(خالی)')}</code>", reply_markup=back_button("adm:set:gw:rialpay"))
            return

        if sn == "admin_set_plisio_key" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ کلید API نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:plisio"))
                return
            setting_set("plisio_api_key", val)
            log_admin_action(uid, "کلید API Plisio تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API Plisio ذخیره شد.", reply_markup=back_button("adm:set:gw:plisio"))
            return

        if sn == "admin_set_nowpayments_key" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ کلید API نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:nowpayments"))
                return
            setting_set("nowpayments_api_key", val)
            log_admin_action(uid, "کلید API NowPayments تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کلید API NowPayments ذخیره شد.", reply_markup=back_button("adm:set:gw:nowpayments"))
            return

        if sn == "admin_set_nowpayments_ipn" and is_admin(uid):
            val = (message.text or "").strip()
            if not val:
                bot.send_message(uid, "⚠️ IPN Secret نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:", reply_markup=back_button("adm:set:gw:nowpayments"))
                return
            setting_set("nowpayments_ipn_secret", val)
            log_admin_action(uid, "IPN Secret NowPayments تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ IPN Secret Key NowPayments ذخیره شد.", reply_markup=back_button("adm:set:gw:nowpayments"))
            return

        if sn == "admin_set_server_public_url" and is_admin(uid):
            val = (message.text or "").strip().rstrip("/")
            if val == "-":
                val = ""
            if val and not (val.startswith("http://") or val.startswith("https://")):
                bot.send_message(uid, "⚠️ URL باید با <code>https://</code> یا <code>http://</code> شروع شود:", reply_markup=back_button("adm:set:gw:plisio"))
                return
            setting_set("server_public_url", val)
            log_admin_action(uid, f"Server Public URL تغییر کرد: {val or '(پاک شد — تشخیص خودکار)'}")
            state_clear(uid)
            if val:
                bot.send_message(uid, f"✅ Server Public URL ذخیره شد:\n<code>{val}</code>", parse_mode="HTML", reply_markup=back_button("adm:set:gw:plisio"))
            else:
                bot.send_message(uid, "✅ Server Public URL پاک شد. از این پس آدرس به‌صورت خودکار از IP عمومی سرور تشخیص داده می‌شود.", reply_markup=back_button("adm:set:gw:plisio"))
            return

        if sn == "admin_gw_range_min" and is_admin(uid):
            gw = sd.get("gw", "")
            val = (message.text or "").strip()
            if val in ("0", "-", "بدون حداقل"):
                setting_set(f"gw_{gw}_range_min", "")
            elif val.isdigit():
                setting_set(f"gw_{gw}_range_min", val)
            else:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید یا <code>0</code> برای بدون حداقل:", reply_markup=back_button(f"adm:gw:{gw}:range"))
                return
            state_set(uid, "admin_gw_range_max", gw=gw)
            bot.send_message(uid,
                "📊 <b>حداکثر مبلغ</b> (تومان) را وارد کنید.\n\n"
                "برای <b>بدون حداکثر</b>، عدد <code>0</code> یا <code>-</code> ارسال کنید:")
            return

        if sn == "admin_gw_range_max" and is_admin(uid):
            gw = sd.get("gw", "")
            val = (message.text or "").strip()
            if val in ("0", "-", "بدون حداکثر"):
                setting_set(f"gw_{gw}_range_max", "")
            elif val.isdigit():
                setting_set(f"gw_{gw}_range_max", val)
            else:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید یا <code>0</code> برای بدون حداکثر:", reply_markup=back_button(f"adm:gw:{gw}:range"))
                return
            state_clear(uid)
            log_admin_action(uid, f"بازه پرداختی درگاه {gw} تنظیم شد")
            bot.send_message(uid, "✅ بازه پرداختی ذخیره شد.", reply_markup=back_button(f"adm:gw:{gw}:range"))
            return

        if sn == "admin_set_channel" and is_admin(uid):
            val = (message.text or "").strip()
            setting_set("channel_id", "" if val == "-" else val)
            log_admin_action(uid, "کانال تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ کانال ذخیره شد.", reply_markup=back_button("admin:settings"))
            return

        if sn == "admin_add_locked_channel" and is_admin(uid):
            from ..db import add_locked_channel
            from ..ui.helpers import _invalidate_channel_cache
            val = (message.text or "").strip()
            if not val or val == "-":
                state_clear(uid)
                bot.send_message(uid, "❌ لغو شد.", reply_markup=back_button("adm:locked_channels"))
                return
            ok = add_locked_channel(val)
            _invalidate_channel_cache()
            state_clear(uid)
            if ok:
                log_admin_action(uid, f"کانال قفل {val} افزوده شد")
                bot.send_message(uid, f"✅ کانال <code>{esc(val)}</code> افزوده شد.",
                                 parse_mode="HTML", reply_markup=back_button("adm:locked_channels"))
            else:
                bot.send_message(uid, f"⚠️ کانال <code>{esc(val)}</code> قبلاً ثبت شده بود.",
                                 parse_mode="HTML", reply_markup=back_button("adm:locked_channels"))
            return

        if sn == "admin_set_start_text" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt
            raw_text = (message.text or message.caption or "").strip()
            entities = message.entities or message.caption_entities or []
            if raw_text == "-":
                setting_set("start_text", "")
                log_admin_action(uid, "متن استارت تغییر کرد")
                state_clear(uid)
                bot.send_message(uid, "✅ متن استارت به پیش‌فرض برگشت.", reply_markup=back_button("adm:bot_texts"))
            else:
                serialized = _spt(raw_text, entities)
                setting_set("start_text", serialized)
                custom_count = sum(1 for e in entities if e.type == "custom_emoji")
                is_json = serialized.strip().startswith("{")
                log_admin_action(uid, "متن استارت تغییر کرد")
                state_clear(uid)
                bot.send_message(uid,
                    f"✅ متن استارت ذخیره شد.\n"
                    f"<code>ایموجی پرمیوم: {custom_count} | فرمت: {'JSON' if is_json else 'plain'}</code>",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:bot_texts"))
            return

        if sn == "admin_set_start_prefix_emoji" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt
            raw_text = (message.text or message.caption or "").strip()
            entities = message.entities or message.caption_entities or []
            state_clear(uid)
            if raw_text == "-":
                setting_set("start_prefix_emoji", "")
                log_admin_action(uid, "ایموجی پرمیوم قبل از استارت حذف شد")
                bot.send_message(uid, "✅ ایموجی پرمیوم قبل از استارت حذف شد.", reply_markup=back_button("adm:bot_texts"))
            else:
                serialized = _spt(raw_text, entities)
                setting_set("start_prefix_emoji", serialized)
                custom_count = sum(1 for e in entities if e.type == "custom_emoji")
                log_admin_action(uid, "ایموجی پرمیوم قبل از استارت تنظیم شد")
                bot.send_message(uid,
                    f"✅ ایموجی پرمیوم ذخیره شد.\n"
                    f"<code>ایموجی پرمیوم: {custom_count}</code>",
                    parse_mode="HTML",
                    reply_markup=back_button("adm:bot_texts"))
            return

        if sn == "admin_set_start_photo" and is_admin(uid):
            state_clear(uid)
            if message.content_type == "photo":
                file_id = message.photo[-1].file_id
                setting_set("start_photo_file_id", file_id)
                log_admin_action(uid, "پوستر منوی استارت تنظیم شد")
                bot.send_message(uid, "✅ پوستر منوی استارت ذخیره شد.", reply_markup=back_button("adm:bot_texts"))
            elif (message.text or "").strip() == "-":
                setting_set("start_photo_file_id", "")
                log_admin_action(uid, "پوستر منوی استارت حذف شد")
                bot.send_message(uid, "✅ پوستر منوی استارت حذف شد.", reply_markup=back_button("adm:bot_texts"))
            else:
                bot.send_message(uid, "⚠️ لطفاً یک عکس ارسال کنید یا <code>-</code> برای حذف پوستر.", parse_mode="HTML", reply_markup=back_button("adm:set:start_photo"))
            return

        if sn == "admin_edit_tariff_text" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt
            raw_text = message.text if message.text is not None else (message.caption or "")
            entities = message.entities or message.caption_entities or []
            if raw_text.strip() == "-":
                setting_set("tariff_text", "")
                log_admin_action(uid, "متن تعرفه پاک شد")
                state_clear(uid)
                bot.send_message(uid, "✅ متن تعرفه پاک شد.", reply_markup=back_button("adm:tariff:view"))
            else:
                _serialized = _spt(raw_text, entities)
                setting_set("tariff_text", _serialized)
                log_admin_action(uid, "متن تعرفه تغییر کرد")
                state_clear(uid)
                _pe_count = sum(1 for e in (entities or []) if getattr(e, "type", "") == "custom_emoji")
                _confirm = "✅ متن تعرفه ذخیره شد."
                if _pe_count:
                    _confirm += f"\n\n<code>ایموجی پرمیوم: {_pe_count} عدد</code>"
                bot.send_message(uid, _confirm, parse_mode="HTML", reply_markup=back_button("adm:tariff:view"))
            return

        if sn == "admin_startmenu_edit_text" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt, render_premium_text_html as _rph
            from ..ui.start_menu import BUTTONS
            key = state_data(uid).get("button_key")
            if key not in BUTTONS:
                state_clear(uid)
                bot.send_message(uid, "⚠️ کلید دکمه نامعتبر است.", reply_markup=back_button("admin:startmenu:texts"))
                return
            raw_text = message.text if message.text is not None else (message.caption or "")
            if raw_text.strip() == "-":
                setting_set(f"start_menu_text:{key}", "")
                log_admin_action(uid, f"متن دکمه {key} به پیش‌فرض برگشت")
                state_clear(uid)
                bot.send_message(uid, "✅ متن دکمه به پیش‌فرض برگشت.", reply_markup=back_button("admin:startmenu:texts"))
            else:
                entities = message.entities or message.caption_entities or []
                html_text = _rph(_spt(raw_text, entities))
                setting_set(f"start_menu_text:{key}", html_text)
                log_admin_action(uid, f"متن دکمه منوی استارت {key} تغییر کرد")
                state_clear(uid)
                preview = (
                    f"✅ متن دکمه ذخیره شد.\n\n"
                    f"پیش‌نمایش:\n{html_text}"
                )
                bot.send_message(uid, preview, parse_mode="HTML", reply_markup=back_button("admin:startmenu:texts"))
            return

        if sn == "admin_startmenu_edit_emoji" and is_admin(uid):
            from ..ui.start_menu import BUTTONS, get_button_emoji_id
            from ..ui.premium_emoji import tg_emoji as _tge
            key = state_data(uid).get("button_key")
            if key not in BUTTONS:
                state_clear(uid)
                bot.send_message(uid, "⚠️ کلید دکمه نامعتبر است.", reply_markup=back_button("admin:startmenu:texts"))
                return
            raw_text = (message.text or "").strip()
            if raw_text == "-":
                setting_set(f"start_menu_emoji:{key}", "")
                log_admin_action(uid, f"ایموجی دکمه {key} به پیش‌فرض برگشت")
                state_clear(uid)
                bot.send_message(uid, "✅ ایموجی دکمه به پیش‌فرض برگشت.", reply_markup=back_button(f"admin:startmenu:text:{key}"))
                return
            # Try to extract custom_emoji_id from message entities
            entities = message.entities or []
            custom_emoji_id = None
            for e in entities:
                if e.type == "custom_emoji":
                    custom_emoji_id = e.custom_emoji_id
                    break
            # Fall back to plain numeric ID if admin typed it directly
            if not custom_emoji_id and raw_text.isdigit() and len(raw_text) >= 10:
                custom_emoji_id = raw_text
            if not custom_emoji_id:
                bot.send_message(uid,
                    "⚠️ ایموجی پرمیوم پیدا نشد.\n\n"
                    "یک پیام حاوی ایموجی پرمیوم بفرستید، یا آیدی عددی آن را بنویسید.\n"
                    "برای لغو: <code>-</code>",
                    parse_mode="HTML")
                return
            setting_set(f"start_menu_emoji:{key}", custom_emoji_id)
            log_admin_action(uid, f"ایموجی دکمه {key} تغییر کرد به {custom_emoji_id}")
            state_clear(uid)
            preview_emoji = _tge(custom_emoji_id, "✨")
            bot.send_message(uid,
                f"✅ ایموجی دکمه ذخیره شد.\n\nآیدی: <code>{custom_emoji_id}</code>\nپیش‌نمایش: {preview_emoji}",
                parse_mode="HTML",
                reply_markup=back_button(f"admin:startmenu:text:{key}"))
            return

        if sn == "admin_startmenu_edit_layout" and is_admin(uid):
            import json as _json
            from ..ui.start_menu import parse_layout_text, BUTTONS, button_admin_enabled
            raw_text = message.text or ""
            layout, err = parse_layout_text(raw_text)
            if err:
                bot.send_message(uid, f"⚠️ {err}\n\nلطفاً چیدمان را دوباره ارسال کنید.", reply_markup=back_button("admin:startmenu"))
                return
            setting_set("start_menu_layout", _json.dumps(layout, ensure_ascii=False))
            missing = [k for k in BUTTONS if button_admin_enabled(k) and all(k not in row for row in layout)]
            warn = ""
            if missing:
                warn = "\n\n⚠️ این دکمه‌های فعال در چیدمان نیامده‌اند و انتهای منو اضافه می‌شوند:\n" + ", ".join(missing)
            log_admin_action(uid, "چیدمان منوی استارت تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, f"✅ چیدمان منوی استارت ذخیره شد.{warn}", reply_markup=back_button("admin:startmenu"))
            return

        # ── Admin: Free Test settings ──────────────────────────────────────────
        if sn == "admin_set_agent_test_limit" and is_admin(uid):
            val = (message.text or "").strip()
            if val == "0":
                setting_set("agent_test_limit", "0")
                log_admin_action(uid, "محدودیت تست همکاران غیرفعال شد")
                state_clear(uid)
                bot.send_message(uid, "✅ محدودیت تست همکاران غیرفعال شد.", reply_markup=back_button("adm:set:freetest"))
                return
            parts = val.split()
            if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in ("day", "week", "month"):
                bot.send_message(uid,
                    "⚠️ فرمت نادرست. مثال: <code>5 day</code> یا <code>10 week</code> یا <code>20 month</code>\nبرای غیرفعال: <code>0</code>",
                    reply_markup=back_button("adm:set:freetest"))
                return
            setting_set("agent_test_limit", parts[0])
            setting_set("agent_test_period", parts[1])
            log_admin_action(uid, f"محدودیت تست همکاران: {parts[0]} در {parts[1]}")
            state_clear(uid)
            period_labels = {"day": "روز", "week": "هفته", "month": "ماه"}
            bot.send_message(uid,
                f"✅ تست همکاران: {parts[0]} عدد در {period_labels[parts[1]]}",
                reply_markup=back_button("adm:set:freetest"))
            return

        # ── Admin: Backup settings ─────────────────────────────────────────────
        if sn == "admin_set_backup_interval" and is_admin(uid):
            val = parse_int(message.text or "")
            if not val or val < 1:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.", reply_markup=back_button("admin:backup"))
                return
            setting_set("backup_interval", str(val))
            log_admin_action(uid, f"بازه بکاپ به {val} دقیقه تنظیم شد")
            state_clear(uid)
            bot.send_message(uid, f"✅ بازه بکاپ به {val} دقیقه تنظیم شد.", reply_markup=back_button("admin:backup"))
            return

        if sn == "admin_set_backup_target" and is_admin(uid):
            val = (message.text or "").strip()
            setting_set("backup_target_id", val)
            log_admin_action(uid, "مقصد بکاپ تغییر کرد")
            state_clear(uid)
            bot.send_message(uid, "✅ مقصد بکاپ ذخیره شد.", reply_markup=back_button("admin:backup"))
            return

        if sn == "admin_set_group_id" and is_admin(uid):
            from ..group_manager import ensure_group_topics
            val = (message.text or "").strip()
            if not val.lstrip("-").isdigit():
                bot.send_message(uid,
                    "⚠️ آیدی گروه باید عددی باشد.\nمثال: <code>-1001234567890</code>",
                    reply_markup=back_button("admin:group"))
                return
            setting_set("group_id", val)
            log_admin_action(uid, f"آیدی گروه به {val} تغییر کرد")
            state_clear(uid)
            bot.send_message(uid,
                f"✅ آیدی گروه <code>{val}</code> ذخیره شد.\n\n"
                "در حال ساخت تاپیک‌ها...", parse_mode="HTML")
            result = ensure_group_topics()
            bot.send_message(uid, f"🛠 <b>نتیجه ساخت تاپیک:</b>\n\n{result}",
                             parse_mode="HTML", reply_markup=back_button("admin:group"))
            return

        if sn == "admin_restore_backup" and is_admin(uid):
            if not message.document:
                bot.send_message(uid, "⚠️ لطفاً فایل بکاپ (.db) را ارسال کنید.", reply_markup=back_button("admin:backup"))
                return
            file_name = message.document.file_name or ""
            if not file_name.lower().endswith(".db"):
                bot.send_message(uid, "⚠️ فقط فایل با پسوند <code>.db</code> قابل قبول است.", parse_mode="HTML", reply_markup=back_button("admin:backup"))
                return
            try:
                from ..admin.backup import safe_restore_db
                file_info  = bot.get_file(message.document.file_id)
                downloaded = bot.download_file(file_info.file_path)
                ok, msg    = safe_restore_db(downloaded, file_name)
                state_clear(uid)
                icon = "✅" if ok else "❌"
                bot.send_message(uid, f"{icon} {msg}", parse_mode="HTML", reply_markup=back_button("admin:backup"))
            except Exception as e:
                bot.send_message(uid, f"❌ خطا در بازیابی بکاپ: {esc(str(e))}", parse_mode="HTML", reply_markup=back_button("admin:backup"))
            return

        # ── Admin: User Search ────────────────────────────────────────────────
        if sn == "admin_user_search" and is_admin(uid):
            query_text = (message.text or "").strip()
            if not query_text:
                bot.send_message(uid, "⚠️ متن جستجو را ارسال کنید.")
                return
            state_clear(uid)
            rows = search_users(query_text)
            if not rows:
                bot.send_message(uid, "❌ کاربری یافت نشد.", reply_markup=back_button("admin:users"))
                return
            kb = types.InlineKeyboardMarkup()
            for row in rows:
                status_icon = "🔘" if row["status"] == "safe" else "⚠️"
                agent_icon  = "🤝 " if row["is_agent"] else ""
                uname       = f"@{row['username']}" if row["username"] else str(row["user_id"])
                name_part   = row["full_name"] or f"(آیدی: {row['user_id']})"
                buy_tag     = f" 🛍{row['purchase_count']}" if row["purchase_count"] else ""
                label = f"{status_icon} {agent_icon}{name_part} | {uname}{buy_tag}"
                kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:usr:v:{row['user_id']}"))
            kb.add(types.InlineKeyboardButton("🔍 جستجوی جدید", callback_data="adm:usr:search"))
            kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin:users"))
            bot.send_message(uid, f"🔍 <b>نتایج جستجو</b> — {len(rows)} کاربر یافت شد:", reply_markup=kb)
            return

        # ── Admin: Stock Search ────────────────────────────────────────────────
        if sn in ("admin_search_by_link", "admin_search_by_config", "admin_search_by_name") and is_admin(uid):
            query_text = (message.text or "").strip()
            if not query_text:
                bot.send_message(uid, "⚠️ متن جستجو را ارسال کنید.")
                return
            state_clear(uid)
            search_param = f"%{query_text}%"
            if sn == "admin_search_by_link":
                col_filter = "c.inquiry_link LIKE ?"
            elif sn == "admin_search_by_config":
                col_filter = "c.config_text LIKE ?"
            else:
                col_filter = "c.service_name LIKE ?"
            with get_conn() as conn:
                rows = conn.execute(
                    f"SELECT c.id, c.service_name, c.sold_to, c.is_expired FROM configs c WHERE {col_filter} ORDER BY c.id DESC LIMIT 50",
                    (search_param,)
                ).fetchall()
            if not rows:
                bot.send_message(uid, "❌ نتیجه‌ای یافت نشد.", reply_markup=back_button("adm:stk:search"))
                return
            kb = types.InlineKeyboardMarkup()
            for r in rows:
                label = urllib.parse.unquote(r["service_name"] or "") or f"#{r['id']}"
                if r["is_expired"]:
                    label = "⛔ " + label
                elif r["sold_to"]:
                    label = "✅ " + label
                else:
                    label = "📦 " + label
                kb.add(types.InlineKeyboardButton(label, callback_data=f"adm:stk:cfg:{r['id']}"))
            kb.add(types.InlineKeyboardButton("بازگشت", callback_data="adm:stk:search", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid, f"🔍 نتایج جستجو ({len(rows)}):", reply_markup=kb)
            return

        # ── Admin: Balance edit ────────────────────────────────────────────────
        if sn in ("admin_bal_add", "admin_bal_sub") and is_admin(uid):
            amount        = parse_int(message.text or "")
            target_user_id = sd["target_user_id"]
            if not amount or amount <= 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر وارد کنید.", reply_markup=back_button("admin:users"))
                return
            delta = amount if sn == "admin_bal_add" else -amount
            update_balance(target_user_id, delta)
            try:
                from ..db import update_admin_adjusted
                update_admin_adjusted(target_user_id, delta)
            except Exception:
                pass
            state_clear(uid)
            action_label = "اضافه" if delta > 0 else "کاهش"
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("🔙 بازگشت به کاربر", callback_data=f"adm:usr:v:{target_user_id}"))
            target_info = get_user(target_user_id)
            try:
                _tname   = (target_info['first_name'] or '').strip()
                _tuname  = (target_info['username']   or '').strip()
                _new_bal = target_info['balance']
                if _tuname:
                    _uname_line = f"👤 کاربر: @{esc(_tuname)}\n"
                elif _tname:
                    _uname_line = f"👤 کاربر: <b>{esc(_tname)}</b>\n"
                else:
                    _uname_line = ""
            except Exception:
                _uname_line = ""
                _new_bal    = 0
            bot.send_message(
                uid,
                f"✅ موجودی {action_label} یافت.\n\n"
                f"{_uname_line}"
                f"🆔 آیدی: <code>{target_user_id}</code>\n"
                f"💰 مبلغ: <b>{fmt_price(abs(amount))}</b> تومان\n"
                f"💳 موجودی جدید: <b>{fmt_price(_new_bal)}</b> تومان",
                reply_markup=kb, parse_mode="HTML")
            try:
                msg = f"{'➕' if delta > 0 else '➖'} موجودی شما توسط ادمین {action_label} یافت.\n💰 مبلغ: {fmt_price(abs(amount))} تومان"
                bot.send_message(target_user_id, msg)
            except Exception:
                pass
            return

        # ── Admin: Agency price (per-package, mode=package) ─────────────────
        if sn == "admin_set_agency_price_cfg" and is_admin(uid):
            target_user_id = sd["target_user_id"]
            package_id     = sd["package_id"]
            val            = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر وارد کنید.",
                                 reply_markup=back_button(f"adm:agcfg:pkg:{target_user_id}"))
                return
            if val == 0:
                with get_conn() as conn:
                    conn.execute("DELETE FROM agency_prices WHERE user_id=? AND package_id=?",
                                 (target_user_id, package_id))
                state_clear(uid)
                bot.send_message(uid, "✅ قیمت اختصاصی حذف شد (قیمت پیش‌فرض اعمال می‌شود).",
                                 reply_markup=back_button(f"adm:agcfg:pkg:{target_user_id}"))
            else:
                set_agency_price(target_user_id, package_id, val)
                state_clear(uid)
                bot.send_message(uid, f"✅ قیمت اختصاصی {fmt_price(val)} تومان ثبت شد.",
                                 reply_markup=back_button(f"adm:agcfg:pkg:{target_user_id}"))
            return

        if sn == "admin_set_agency_price" and is_admin(uid):
            target_user_id = sd["target_user_id"]
            package_id     = sd["package_id"]
            val            = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر وارد کنید.", reply_markup=back_button("admin:users"))
                return
            if val == 0:
                with get_conn() as conn:
                    conn.execute("DELETE FROM agency_prices WHERE user_id=? AND package_id=?",
                                 (target_user_id, package_id))
                state_clear(uid)
                bot.send_message(uid, "✅ قیمت اختصاصی حذف شد (قیمت پیش‌فرض اعمال می‌شود).",
                                 reply_markup=kb_admin_panel())
            else:
                set_agency_price(target_user_id, package_id, val)
                state_clear(uid)
                bot.send_message(uid, f"✅ قیمت اختصاصی {fmt_price(val)} تومان ثبت شد.",
                                 reply_markup=kb_admin_panel())
            return

        # ── Admin: Agency global discount value ────────────────────────────────
        if sn == "admin_agcfg_global_val" and is_admin(uid):
            target_user_id = sd["target_user_id"]
            dtype          = sd.get("dtype", "pct")
            val            = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.")
                return
            if dtype == "pct" and val > 100:
                bot.send_message(uid, "⚠️ درصد بیشتر از 100 مجاز نیست.")
                return
            set_agency_price_config(target_user_id, "global",
                "pct" if dtype == "pct" else "toman", val)
            state_clear(uid)
            label = f"{val}%" if dtype == "pct" else f"{fmt_price(val)} تومان"
            log_admin_action(uid, f"تخفیف کل نماینده {target_user_id}: {label}")
            bot.send_message(uid,
                f"✅ تخفیف کل محصولات: <b>{label}</b> تنظیم شد.",
                reply_markup=kb_admin_panel())
            return

        # ── Admin: Agency type discount value ──────────────────────────────────
        if sn == "admin_agcfg_type_val" and is_admin(uid):
            target_user_id = sd["target_user_id"]
            type_id        = sd.get("type_id")
            dtype          = sd.get("dtype", "pct")
            val            = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ عدد معتبر وارد کنید.")
                return
            if dtype == "pct" and val > 100:
                bot.send_message(uid, "⚠️ درصد بیشتر از 100 مجاز نیست.")
                return
            set_agency_type_discount(target_user_id, type_id,
                "pct" if dtype == "pct" else "toman", val)
            state_clear(uid)
            label = f"{val}%" if dtype == "pct" else f"{fmt_price(val)} تومان"
            log_admin_action(uid, f"تخفیف دسته #{type_id} نماینده {target_user_id}: {label}")
            bot.send_message(uid,
                f"✅ تخفیف دسته #{type_id}: <b>{label}</b> تنظیم شد.",
                reply_markup=kb_admin_panel())
            return

        if sn == "admin_agcfg_pergb_val" and is_admin(uid):
            target_user_id = sd["target_user_id"]
            type_id        = sd.get("type_id")
            val            = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ عدد معتبر (مثبت یا صفر) وارد کنید.")
                return
            set_per_gb_price(target_user_id, type_id, val)
            state_clear(uid)
            log_admin_action(uid, f"قیمت هر گیگ دسته #{type_id} نماینده {target_user_id}: {fmt_price(val)} تومان")
            bot.send_message(uid,
                f"✅ قیمت هر گیگ دسته #{type_id}: <b>{fmt_price(val)} تومان</b> تنظیم شد.",
                reply_markup=kb_admin_panel())
            return

        if sn == "admin_resreq_reject_reason" and is_admin(uid):
            from ..db import reject_reseller_request as _rr_reject, get_reseller_request_by_id as _rr_get
            from ..db import delete_agency_request_messages as _del_arm, get_agency_request_messages as _get_arm
            req_id     = sd.get("req_id")
            target_uid = sd.get("target_uid")
            reason     = (message.text or "").strip()
            req        = _rr_get(req_id)
            if req:
                _rr_reject(req_id, uid)
                for row in _get_arm(target_uid):
                    try:
                        bot.edit_message_reply_markup(row["chat_id"], row["message_id"], reply_markup=None)
                    except Exception:
                        pass
                _del_arm(target_uid)
                try:
                    notify_msg = "❌ <b>درخواست نمایندگی شما رد شد.</b>"
                    if reason:
                        notify_msg += f"\n\n💬 دلیل: {esc(reason)}"
                    bot.send_message(target_uid, notify_msg, parse_mode="HTML")
                except Exception:
                    pass
                log_admin_action(uid, f"درخواست نمایندگی #{req_id} (کاربر {target_uid}) رد شد: {reason}")
            state_clear(uid)
            bot.send_message(uid, f"❌ درخواست #{req_id} رد شد.", reply_markup=kb_admin_panel())
            return

        if sn == "admin_set_resreq_min_wallet" and is_admin(uid):
            val = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ عدد معتبر (0 یا بیشتر) وارد کنید.")
                return
            setting_set("agency_request_min_wallet", str(val))
            state_clear(uid)
            log_admin_action(uid, f"حداقل موجودی درخواست نمایندگی: {fmt_price(val)} تومان")
            bot.send_message(uid,
                f"✅ حداقل موجودی درخواست نمایندگی: <b>{fmt_price(val)} تومان</b> تنظیم شد.",
                reply_markup=kb_admin_panel())
            return

        if sn == "admin_set_credit_limit" and is_admin(uid):
            from ..db import set_user_purchase_credit as _set_credit, get_user as _get_user
            target_user_id = sd.get("target_user_id")
            val = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ عدد معتبر (0 یا بیشتر) وارد کنید.")
                return
            existing = _get_user(target_user_id)
            credit_enabled = existing["purchase_credit_enabled"] if existing and "purchase_credit_enabled" in existing.keys() else 0
            _set_credit(target_user_id, credit_enabled, val)
            state_clear(uid)
            log_admin_action(uid, f"سقف اعتبار کاربر {target_user_id}: {fmt_price(val)} تومان")
            bot.send_message(uid,
                f"✅ سقف اعتبار کاربر <code>{target_user_id}</code>: <b>{fmt_price(val)} تومان</b> تنظیم شد.",
                reply_markup=back_button(f"adm:credit:{target_user_id}"))
            return

        # ── Admin: Addon unit price ────────────────────────────────────────────
        if sn == "admin_addon_price_set" and is_admin(uid):
            from ..db import set_addon_price as _set_ap
            addon_type = sd.get("addon_type")
            type_id    = sd.get("type_id")
            role       = sd.get("role")  # 'normal' | 'res'
            val = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ عدد معتبر (0 یا بیشتر) وارد کنید.")
                return
            db_role = "normal" if role == "normal" else "reseller"
            _set_ap(type_id, addon_type, db_role, val)
            state_clear(uid)
            unit = "گیگابایت" if addon_type == "volume" else "روز"
            role_fa = "کاربران عادی" if role == "normal" else "نمایندگان"
            log_admin_action(uid, f"قیمت افزودنی {addon_type} نوع {type_id} ({role_fa}): {fmt_price(val)} تومان/{unit}")
            bot.send_message(uid,
                f"✅ قیمت تنظیم شد: <b>{fmt_price(val)} تومان / {unit}</b> ({role_fa})",
                reply_markup=kb_admin_panel())
            return


        if sn == "admin_set_default_discount_pct" and is_admin(uid):
            val = parse_int(message.text or "")
            if val is None or val < 0 or val > 100:
                bot.send_message(uid, "⚠️ عددی بین 0 تا 100 وارد کنید.")
                return
            setting_set("agency_default_discount_pct", str(val))
            log_admin_action(uid, f"تخفیف پیش‌فرض نمایندگی به {val}% تغییر یافت")
            state_clear(uid)
            bot.send_message(uid, f"✅ تخفیف پیش‌فرض نمایندگی به <b>{val}%</b> تغییر یافت.",
                             reply_markup=back_button("admin:settings"))
            return

        # ── Admin: Add agent (search) ─────────────────────────────────────────
        if sn == "admin_agent_add_search" and is_admin(uid):
            raw = (message.text or "").strip()
            target_user = None
            if raw.lstrip("-").isdigit():
                target_user = get_user(int(raw))
            if not target_user:
                results = search_users(raw)
                if results:
                    target_user = results[0]
            if not target_user:
                bot.send_message(uid, "⚠️ کاربری با این شناسه یافت نشد.",
                                 reply_markup=back_button("admin:agents"))
                return
            state_clear(uid)
            if target_user["is_agent"]:
                bot.send_message(uid,
                    f"ℹ️ کاربر <b>{esc(target_user['full_name'])}</b> قبلاً نماینده است.",
                    reply_markup=back_button("admin:agents"))
                return
            set_user_agent(target_user["user_id"], 1)
            kb_r = types.InlineKeyboardMarkup()
            kb_r.add(types.InlineKeyboardButton(
                "💰 قیمت نمایندگی",
                callback_data=f"adm:agcfg:{target_user['user_id']}"
            ))
            kb_r.add(types.InlineKeyboardButton("بازگشت", callback_data="admin:agents", icon_custom_emoji_id="5253997076169115797"))
            bot.send_message(uid,
                f"✅ کاربر <b>{esc(target_user['full_name'])}</b> (کد <code>{target_user['user_id']}</code>) به نماینده تبدیل شد.",
                reply_markup=kb_r)
            try:
                bot.send_message(target_user["user_id"],
                    "🎉 <b>شما به عنوان نماینده تمام سیستم اضافه شدید!</b>")
            except Exception:
                pass
            return
            target_user_id = sd["target_user_id"]
            package_id     = sd["package_id"]
            val            = parse_int(message.text or "")
            if val is None or val < 0:
                bot.send_message(uid, "⚠️ مبلغ معتبر وارد کنید.", reply_markup=back_button("admin:users"))
                return
            if val == 0:
                with get_conn() as conn:
                    conn.execute("DELETE FROM agency_prices WHERE user_id=? AND package_id=?",
                                 (target_user_id, package_id))
                state_clear(uid)
                bot.send_message(uid, "✅ قیمت اختصاصی حذف شد (قیمت پیش‌فرض اعمال می‌شود).",
                                 reply_markup=kb_admin_panel())
            else:
                set_agency_price(target_user_id, package_id, val)
                state_clear(uid)
                bot.send_message(uid, f"✅ قیمت اختصاصی {fmt_price(val)} تومان ثبت شد.",
                                 reply_markup=kb_admin_panel())
            return

        # ── Admin: Add admin — resolve user ID ────────────────────────────────
        if sn == "admin_mgr_await_id" and uid in ADMIN_IDS:
            raw = (message.text or "").strip()
            target_id = None
            # Try numeric ID first
            if raw.lstrip("-").isdigit():
                target_id = int(raw)
            else:
                # Try username lookup (remove leading @)
                uname = raw.lstrip("@").lower()
                with get_conn() as conn:
                    row_u = conn.execute(
                        "SELECT user_id FROM users WHERE LOWER(username)=? LIMIT 1",
                        (uname,)
                    ).fetchone()
                if row_u:
                    target_id = row_u["user_id"]
            if not target_id:
                bot.send_message(uid,
                    "⚠️ کاربر یافت نشد. آیدی عددی یا یوزرنیم را دقیق وارد کنید.",
                    reply_markup=back_button("admin:admins"))
                return
            if target_id in ADMIN_IDS:
                bot.send_message(uid,
                    "⚠️ این کاربر اونر است و نیاز به ثبت ادمین ندارد.",
                    reply_markup=back_button("admin:admins"))
                state_clear(uid)
                return
            state_set(uid, "admin_mgr_select_perms", target_user_id=target_id, perms="{}")
            _show_perm_selection(message, uid, target_id, {}, edit_mode=False)
            return

        # ── Admin: Payment approval ────────────────────────────────────────────
        if sn == "admin_payment_approve_note" and is_admin(uid):
            payment_id = sd["payment_id"]
            raw_note   = (message.text or "").strip()
            note = "" if (not raw_note or raw_note == "➖") else raw_note
            finish_card_payment_approval(payment_id, note, approved=True)
            state_clear(uid)
            bot.send_message(uid, "✅ درخواست با موفقیت تأیید شد.", reply_markup=kb_admin_panel())
            return

        if sn == "admin_payment_reject_note" and is_admin(uid):
            payment_id = sd["payment_id"]
            raw_note   = (message.text or "").strip()
            note = "رسید شما رد شد." if (not raw_note or raw_note == "➖") else raw_note
            finish_card_payment_approval(payment_id, note, approved=False)
            state_clear(uid)
            bot.send_message(uid, "✅ درخواست با موفقیت رد شد.", reply_markup=kb_admin_panel())
            return

        # ── Admin: Pending order config entry ─────────────────────────────────
        if sn == "admin_pending_cfg_name" and is_admin(uid):
            cfg_name = (message.text or "").strip()
            if not cfg_name:
                bot.send_message(uid, "⚠️ نام سرویس نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:")
                return
            state_set(uid, "admin_pending_cfg_text", pending_id=sd["pending_id"], cfg_name=cfg_name)
            bot.send_message(uid, "✅ نام ثبت شد.\n\nحالا <b>متن کانفیگ</b> را ارسال کنید:")
            return

        if sn == "admin_pending_cfg_text" and is_admin(uid):
            cfg_text = (message.text or "").strip()
            if not cfg_text:
                bot.send_message(uid, "⚠️ متن کانفیگ نمی‌تواند خالی باشد. لطفاً دوباره ارسال کنید:")
                return
            state_set(uid, "admin_pending_cfg_link",
                      pending_id=sd["pending_id"], cfg_name=sd["cfg_name"], cfg_text=cfg_text)
            bot.send_message(uid,
                "✅ کانفیگ ثبت شد.\n\n"
                "اگر <b>لینک استعلام</b> دارد ارسال کنید، در غیر اینصورت <b>ندارد</b> بنویسید:")
            return

        if sn == "admin_pending_cfg_link" and is_admin(uid):
            raw_link = (message.text or "").strip()
            inquiry_link = None if raw_link.lower() in ("ندارد", "no", "-", "") else raw_link
            pending_id = sd["pending_id"]
            cfg_name   = sd["cfg_name"]
            cfg_text   = sd["cfg_text"]
            state_clear(uid)
            # Deliver config to the user
            ok = _complete_pending_order(pending_id, cfg_name, cfg_text, inquiry_link)
            if ok:
                bot.send_message(uid, "✅ کانفیگ برای کاربر ارسال شد.", reply_markup=kb_admin_panel())
            else:
                bot.send_message(uid, "⚠️ خطا در تکمیل سفارش. ممکن است قبلاً تکمیل شده باشد.",
                                 reply_markup=kb_admin_panel())
            return

        # ── Agency request text ────────────────────────────────────────────────
        if sn == "agency_request_text":
            req_text = (message.text or "").strip() or "بدون متن"
            state_clear(uid)
            user = get_user(uid)
            bot.send_message(uid, "✅ درخواست نمایندگی شما ارسال شد.\n⏳ لطفاً منتظر بررسی ادمین باشید.",
                             reply_markup=kb_main(uid))
            # Save to reseller_requests table
            req_id = create_reseller_request(
                uid,
                user["username"] if user else None,
                user["full_name"] if user else str(uid),
                req_text if req_text != "بدون متن" else None
            )
            text = (
                f"🤝 <b>درخواست نمایندگی جدید</b>\n\n"
                f"👤 نام: {esc(user['full_name'])}\n"
                f"🆔 نام کاربری: {esc(display_username(user['username']))}\n"
                f"🔢 آیدی: <code>{user['user_id']}</code>\n\n"
                f"📝 متن درخواست:\n{esc(req_text)}"
            )
            admin_kb = types.InlineKeyboardMarkup()
            admin_kb.row(
                types.InlineKeyboardButton("✅ تأیید", callback_data=f"adm:resreq:approve:{req_id}"),
                types.InlineKeyboardButton("❌ رد", callback_data=f"adm:resreq:reject:{req_id}"),
            )
            for admin_id in ADMIN_IDS:
                try:
                    from ..db import save_agency_request_message as _sarm
                    msg = bot.send_message(admin_id, text, reply_markup=admin_kb)
                    _sarm(uid, admin_id, msg.message_id)
                except Exception:
                    pass
            for row in get_all_admin_users():
                import json as _json
                sub_id = row["user_id"]
                if sub_id in ADMIN_IDS:
                    continue
                perms = _json.loads(row["permissions"] or "{}")
                if not (perms.get("full") or perms.get("agency")):
                    continue
                try:
                    from ..db import save_agency_request_message as _sarm
                    msg = bot.send_message(sub_id, text, reply_markup=admin_kb)
                    _sarm(uid, sub_id, msg.message_id)
                except Exception:
                    pass
            grp_msg = send_to_topic("agency_request", text, reply_markup=admin_kb)
            if grp_msg:
                try:
                    from ..db import save_agency_request_message as _sarm
                    _sarm(uid, grp_msg.chat.id, grp_msg.message_id)
                except Exception:
                    pass
            return

        # ── Agency approval note ───────────────────────────────────────────────
        if sn == "agency_approve_note" and is_admin(uid):
            note = (message.text or "").strip()
            target_uid = sd["target_user_id"]
            state_clear(uid)
            with get_conn() as conn:
                conn.execute("UPDATE users SET is_agent=1 WHERE user_id=?", (target_uid,))
            kb_conf = types.InlineKeyboardMarkup()
            kb_conf.add(types.InlineKeyboardButton(
                "💰 قیمت نمایندگی کاربر", callback_data=f"adm:agcfg:{target_uid}"))
            kb_conf.add(types.InlineKeyboardButton(
                "بازگشت", callback_data="admin:users"))
            bot.send_message(uid,
                "✅ نمایندگی تأیید شد.",
                reply_markup=kb_conf)
            _show_admin_user_detail_msg(uid, target_uid)
            try:
                msg = "🎉 <b>درخواست نمایندگی شما تأیید شد!</b>\n\nاکنون شما نماینده هستید."
                if note:
                    msg += f"\n\n📝 پیام ادمین:\n{esc(note)}"
                bot.send_message(target_uid, msg)
            except Exception:
                pass
            return

        # ── Agency rejection reason ────────────────────────────────────────────
        if sn == "agency_reject_reason" and is_admin(uid):
            reason = (message.text or "").strip() or "بدون دلیل"
            target_uid = sd["target_user_id"]
            state_clear(uid)
            bot.send_message(uid, "✅ درخواست نمایندگی رد شد.", reply_markup=kb_admin_panel())
            try:
                bot.send_message(target_uid,
                    f"❌ <b>درخواست نمایندگی شما رد شد.</b>\n\n📝 دلیل:\n{esc(reason)}")
            except Exception:
                pass
            return

        # ── Admin: Edit rules text ─────────────────────────────────────────────
        if sn == "admin_edit_rules_text" and is_admin(uid):
            from ..ui.premium_emoji import serialize_premium_text as _spt
            text_val = (message.text or message.caption or "").strip()
            if not text_val:
                bot.send_message(uid, "⚠️ متن خالی مجاز نیست.", reply_markup=back_button("adm:set:rules"))
                return
            entities = message.entities or message.caption_entities or []
            setting_set("purchase_rules_text", _spt(text_val, entities))
            log_admin_action(uid, "متن قوانین خرید ویرایش شد")
            state_clear(uid)
            _pe_count = sum(1 for e in (entities or []) if getattr(e, "type", "") == "custom_emoji")
            _confirm = "✅ متن قوانین خرید ذخیره شد."
            if _pe_count:
                _confirm += f"\n\n<code>ایموجی پرمیوم: {_pe_count} عدد</code>"
            bot.send_message(uid, _confirm, parse_mode="HTML", reply_markup=back_button("adm:set:rules"))
            return

        # ── Admin: Premium Emoji — Extract IDs ────────────────────────────────
        if sn == "admin_emoji_extract" and is_admin(uid):
            from ..ui.premium_emoji import extract_custom_emojis, format_extracted_emoji_report
            items  = extract_custom_emojis(message)
            report = format_extracted_emoji_report(items)
            state_clear(uid)
            bot.send_message(uid, report, parse_mode="HTML",
                             reply_markup=back_button("adm:emoji:menu"))
            return

        # ── Pinned Messages ───────────────────────────────────────────────────
        if sn == "admin_pin_add" and admin_has_perm(uid, "settings"):
            text = (message.text or "").strip()
            if not text:
                bot.send_message(uid, "⚠️ متن پیام نمی‌تواند خالی باشد.")
                return
            add_pinned_message(text)
            log_admin_action(uid, "پیام پین جدید ارسال شد")
            state_clear(uid)
            # Broadcast to all users and pin in each chat
            from ..db import get_all_pinned_messages as _get_pins
            from telebot import types as _types
            users = get_users()
            sent = 0
            pinned = 0
            all_pins = _get_pins()
            pin_id = all_pins[-1]["id"] if all_pins else None
            for u in users:
                try:
                    sent_msg = bot.send_message(u["user_id"], text, parse_mode="HTML")
                    if pin_id:
                        save_pinned_send(pin_id, u["user_id"], sent_msg.message_id)
                    sent += 1
                    try:
                        bot.pin_chat_message(u["user_id"], sent_msg.message_id, disable_notification=True)
                        pinned += 1
                    except Exception:
                        pass
                except Exception:
                    pass
            pins = _get_pins()
            kb = _types.InlineKeyboardMarkup()
            kb.add(_types.InlineKeyboardButton("➕ افزودن پیام پین", callback_data="adm:pin:add"))
            for p in pins:
                preview = (p["text"] or "")[:30].replace("\n", " ")
                kb.row(
                    _types.InlineKeyboardButton(f"📌 {preview}", callback_data="noop"),
                    _types.InlineKeyboardButton("✏️", callback_data=f"adm:pin:edit:{p['id']}"),
                    _types.InlineKeyboardButton("🗑", callback_data=f"adm:pin:del:{p['id']}"),
                )
            kb.add(_types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
            count_text = f"{len(pins)} پیام" if pins else "هیچ پیامی ثبت نشده"
            bot.send_message(uid,
                f"✅ پیام پین ارسال شد.\n📤 فرستاده شده: {sent} کاربر\n📌 پین شده: {pinned} کاربر\n\n"
                f"📌 <b>پیام‌های پین شده</b>\n\n{count_text}",
                reply_markup=kb, parse_mode="HTML")
            from ..group_manager import send_to_topic as _stt
            _pin_preview = text[:200].strip()
            _stt("broadcast_report",
                f"📌 <b>پیام پین جدید</b>\n\n"
                f"👤 ارسال‌کننده: <code>{uid}</code>\n"
                f"📤 ارسال شده: <b>{sent}</b> کاربر\n"
                f"📌 پین شده: <b>{pinned}</b> کاربر\n\n"
                f"📝 <b>متن پیام:</b>\n{esc(_pin_preview)}")
            return

        if sn == "admin_pin_edit" and admin_has_perm(uid, "settings"):
            text = (message.text or "").strip()
            if not text:
                bot.send_message(uid, "⚠️ متن پیام نمی‌تواند خالی باشد.")
                return
            pin_id = sd.get("pin_id")
            if pin_id:
                update_pinned_message(pin_id, text)
                # Edit the sent messages in all user chats
                sends = get_pinned_sends(pin_id)
                edited = 0
                for s in sends:
                    try:
                        bot.edit_message_text(text, s["user_id"], s["message_id"], parse_mode="HTML")
                        edited += 1
                    except Exception:
                        pass
            state_clear(uid)
            from ..db import get_all_pinned_messages as _get_pins
            from telebot import types as _types
            pins = _get_pins()
            kb = _types.InlineKeyboardMarkup()
            kb.add(_types.InlineKeyboardButton("➕ افزودن پیام پین", callback_data="adm:pin:add"))
            for p in pins:
                preview = (p["text"] or "")[:30].replace("\n", " ")
                kb.row(
                    _types.InlineKeyboardButton(f"📌 {preview}", callback_data="noop"),
                    _types.InlineKeyboardButton("✏️", callback_data=f"adm:pin:edit:{p['id']}"),
                    _types.InlineKeyboardButton("🗑", callback_data=f"adm:pin:del:{p['id']}"),
                )
            kb.add(_types.InlineKeyboardButton("بازگشت", callback_data="admin:settings", icon_custom_emoji_id="5253997076169115797"))
            count_text = f"{len(pins)} پیام" if pins else "هیچ پیامی ثبت نشده"
            edited_count = edited if pin_id else 0
            bot.send_message(uid,
                f"✅ پیام پین ویرایش شد.\n✏️ آپدیت شده: {edited_count} کاربر\n\n"
                f"📌 <b>پیام‌های پین شده</b>\n\n{count_text}",
                reply_markup=kb, parse_mode="HTML")
            from ..group_manager import send_to_topic as _stt
            _pin_preview = text[:200].strip()
            _stt("broadcast_report",
                f"✏️ <b>ویرایش پیام پین</b>\n\n"
                f"👤 ویرایش‌کننده: <code>{uid}</code>\n"
                f"✏️ آپدیت شده: <b>{edited_count}</b> کاربر\n\n"
                f"📝 <b>متن جدید:</b>\n{esc(_pin_preview)}")
            return



        # ── Panel add / edit states ───────────────────────────────────────────────

        if sn == "pnl_add_name":
            name = (message.text or "").strip()
            if not name:
                bot.send_message(uid, "⚠️ نام نمی‌تواند خالی باشد. دوباره ارسال کنید.")
                return
            sd = state_data(uid)
            state_set(uid, "pnl_add_proto", pnl_name=name, panel_type=sd.get("panel_type", "sanaei"))
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb_proto = InlineKeyboardMarkup()
            kb_proto.row(
                InlineKeyboardButton("http",  callback_data="adm:pnl:add_proto:http"),
                InlineKeyboardButton("https", callback_data="adm:pnl:add_proto:https"),
            )
            bot.send_message(uid,
                "مرحله ۳/۸ — <b>پروتکل</b>\n\nپروتکل اتصال به پنل را انتخاب کنید:",
                parse_mode="HTML", reply_markup=kb_proto)
            return

        if sn == "pnl_add_host":
            host = (message.text or "").strip()
            if not host:
                bot.send_message(uid, "⚠️ آدرس نمی‌تواند خالی باشد.")
                return
            sd = state_data(uid)
            state_set(uid, "pnl_add_port", pnl_name=sd.get("pnl_name"), protocol=sd.get("protocol"), host=host, panel_type=sd.get("panel_type", "sanaei"))
            bot.send_message(uid,
                "مرحله ۵/۸ — <b>پورت</b>\n\nشماره پورت پنل را ارسال کنید (مثال: 2053):",
                parse_mode="HTML", reply_markup=back_button("admin:panels"))
            return

        if sn == "pnl_add_port":
            port_raw = (message.text or "").strip()
            port = parse_int(port_raw)
            if not port or port <= 0 or port > 65535:
                bot.send_message(uid, "⚠️ پورت باید یک عدد بین ۱ تا ۶۵۵۳۵ باشد.")
                return
            sd = state_data(uid)
            state_set(uid, "pnl_add_path",
                      pnl_name=sd.get("pnl_name"), protocol=sd.get("protocol"),
                      host=sd.get("host"), port=port, panel_type=sd.get("panel_type", "sanaei"))
            bot.send_message(uid,
                "مرحله ۶/۸ — <b>مسیر (path)</b>\n\n"
                "مسیر مخفی پنل را ارسال کنید.\n"
                "به عنوان مثال: <code>/path/</code>\n"
                "اگر پنل مسیر مخفی ندارد، <b>/</b> ارسال کنید.",
                parse_mode="HTML", reply_markup=back_button("admin:panels"))
            return

        if sn == "pnl_add_path":
            raw_path = (message.text or "").strip()
            if raw_path in ("", "/"):
                path = ""
            else:
                path = raw_path if raw_path.startswith("/") else "/" + raw_path
            sd = state_data(uid)
            state_set(uid, "pnl_add_user",
                      pnl_name=sd.get("pnl_name"), protocol=sd.get("protocol"),
                      host=sd.get("host"), port=sd.get("port"), path=path, panel_type=sd.get("panel_type", "sanaei"))
            bot.send_message(uid,
                "مرحله ۷/۸ — <b>نام کاربری</b>\n\nنام کاربری پنل را ارسال کنید:",
                parse_mode="HTML", reply_markup=back_button("admin:panels"))
            return

        if sn == "pnl_add_user":
            username = (message.text or "").strip()
            if not username:
                bot.send_message(uid, "⚠️ نام کاربری نمی‌تواند خالی باشد.")
                return
            sd = state_data(uid)
            state_set(uid, "pnl_add_pass",
                      pnl_name=sd.get("pnl_name"), protocol=sd.get("protocol"),
                      host=sd.get("host"), port=sd.get("port"),
                      path=sd.get("path", ""), username=username, panel_type=sd.get("panel_type", "sanaei"))
            bot.send_message(uid,
                "مرحله ۸/۸ — <b>رمز عبور</b>\n\nرمز عبور پنل را ارسال کنید:",
                parse_mode="HTML", reply_markup=back_button("admin:panels"))
            return

        if sn == "pnl_add_pass":
            password = (message.text or "").strip()
            if not password:
                bot.send_message(uid, "⚠️ رمز عبور نمی‌تواند خالی باشد.")
                return
            sd = state_data(uid)
            state_set(uid, "pnl_add_sub_url",
                      pnl_name=sd.get("pnl_name"), protocol=sd.get("protocol"),
                      host=sd.get("host"), port=sd.get("port"),
                      path=sd.get("path", ""), username=sd.get("username"),
                      password=password, panel_type=sd.get("panel_type", "sanaei"))
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb_skip = InlineKeyboardMarkup()
            kb_skip.add(InlineKeyboardButton("⏭ رد کردن (بدون ساب مجزا)", callback_data="adm:pnl:skip_sub_url"))
            bot.send_message(uid,
                "مرحله ۹/۹ — <b>آدرس ساب (Subscription URL Base)</b>\n\n"
                "اگر پنل شما برای لینک ساب از یک دامنه/آدرس جداگانه استفاده می‌کند، اینجا وارد کنید.\n\n"
                "مثال: <code>http://stareh.parhiiz.top:2096</code>\n\n"
                "⚠️ این آدرس باید همان پایه‌ای باشد که کاربران برای دریافت کانفیگ‌شان به آن وصل می‌شوند.\n"
                "اگر پنل شما ساب مجزا ندارد، دکمه رد کردن را بزنید.",
                parse_mode="HTML", reply_markup=kb_skip)
            return

        if sn == "pnl_add_sub_url":
            raw_sub = (message.text or "").strip().rstrip("/")
            sd = state_data(uid)
            pnl_name    = sd.get("pnl_name", "")
            protocol    = sd.get("protocol", "http")
            host        = sd.get("host", "")
            port        = sd.get("port", 2053)
            path        = sd.get("path", "")
            username    = sd.get("username", "")
            password    = sd.get("password", "")
            sub_url_base = raw_sub

            bot.send_message(uid, "⏳ در حال بررسی اتصال به پنل…")

            try:
                from ..panels.client import PanelClient
                client = PanelClient(protocol=protocol, host=host, port=int(port),
                                     path=path, username=username, password=password,
                                     sub_url_base=sub_url_base)
                ok, err = client.health_check()
            except Exception as exc:
                ok, err = False, str(exc)

            try:
                if ok:
                    state_clear(uid)
                    from ..db import add_panel as _add_panel, adopt_all_orphaned_configs as _adopt
                    panel_id = _add_panel(name=pnl_name or "بدون نام", protocol=protocol,
                                          host=host, port=int(port or 2053), path=path,
                                          username=username, password=password,
                                          sub_url_base=sub_url_base)
                    from ..db import update_panel_status
                    update_panel_status(panel_id, "connected", "")
                    _adopted = _adopt(panel_id)
                    _adopted_note = f"\n\n📥 {_adopted} کانفیگ قدیمی به این پنل منتقل شدند." if _adopted else ""
                    from ..admin.renderers import _show_panel_detail

                    class _FakeCall:
                        def __init__(self, msg, cb_data):
                            class _FU:
                                id = uid
                            self.from_user = _FU()
                            self.message   = msg
                            self.data      = cb_data
                            self.id        = 0

                    bot.send_message(uid, f"✅ اتصال موفق! پنل ذخیره شد.{_adopted_note}", parse_mode="HTML")
                    _show_panel_detail(_FakeCall(message, f"adm:pnl:detail:{panel_id}"), panel_id)
                else:
                    state_set(uid, "pnl_add_save_fail",
                              pnl_name=pnl_name, protocol=protocol, host=host, port=int(port or 2053),
                              path=path, username=username, password=password,
                              sub_url_base=sub_url_base, error=err or "")
                    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                    kb_fail = InlineKeyboardMarkup()
                    kb_fail.row(
                        InlineKeyboardButton("💾 ذخیره به‌عنوان غیرفعال",
                                             callback_data="adm:pnl:save_as_inactive"),
                        InlineKeyboardButton("❌ لغو", callback_data="adm:pnl:add_cancel"),
                    )
                    err_display = (err or "نامشخص")[:300]
                    bot.send_message(uid,
                        f"❌ <b>اتصال ناموفق</b>\n\n"
                        f"خطا: <code>{esc(err_display)}</code>\n\n"
                        "می‌توانید پنل را به‌صورت غیرفعال ذخیره کنید تا بعداً ویرایش شود.",
                        parse_mode="HTML", reply_markup=kb_fail)
            except Exception as panel_exc:
                import traceback as _tb
                _tb.print_exc()
                err_txt = str(panel_exc)[:200]
                state_set(uid, "pnl_add_save_fail",
                          pnl_name=pnl_name, protocol=protocol, host=host,
                          port=int(port or 2053), path=path, username=username,
                          password=password, sub_url_base=sub_url_base, error=err_txt)
                from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                kb_fail2 = InlineKeyboardMarkup()
                kb_fail2.row(
                    InlineKeyboardButton("💾 ذخیره به‌عنوان غیرفعال",
                                         callback_data="adm:pnl:save_as_inactive"),
                    InlineKeyboardButton("❌ لغو", callback_data="adm:pnl:add_cancel"),
                )
                bot.send_message(uid,
                    f"⚠️ <b>خطای داخلی</b>\n\n"
                    f"<code>{esc(err_txt)}</code>\n\n"
                    "می‌توانید پنل را به‌صورت غیرفعال ذخیره کنید.",
                    parse_mode="HTML", reply_markup=kb_fail2)
            return

        if sn == "pnl_edit_field":
            sd       = state_data(uid)
            field    = sd.get("field")
            panel_id = sd.get("panel_id")
            new_val  = (message.text or "").strip()

            if not new_val and field != "sub_url_base":
                bot.send_message(uid, "⚠️ مقدار نمی‌تواند خالی باشد. دوباره ارسال کنید.")
                return

            if field == "port":
                port_v = parse_int(new_val)
                if not port_v or port_v <= 0 or port_v > 65535:
                    bot.send_message(uid, "⚠️ پورت باید عدد ۱–۶۵۵۳۵ باشد.")
                    return
                new_val = port_v

            if field == "path":
                if new_val in ("", "/"):
                    new_val = ""
                elif not new_val.startswith("/"):
                    new_val = "/" + new_val

            if field == "sub_url_base":
                # Allow /skip to clear the field
                if new_val.lower() in ("/skip", "skip", "-", "ندارد"):
                    new_val = ""
                else:
                    new_val = new_val.rstrip("/")

            from ..db import update_panel_field as _upf
            _upf(panel_id, field, new_val)
            state_clear(uid)

            from ..admin.renderers import _show_panel_detail

            class _FakeCall2:
                def __init__(self, msg, cb_data):
                    class _FU:
                        id = uid
                    self.from_user = _FU()
                    self.message   = msg
                    self.data      = cb_data
                    self.id        = 0

            bot.send_message(uid, "✅ ویرایش ذخیره شد.")
            _show_panel_detail(_FakeCall2(message, f"adm:pnl:detail:{panel_id}"), panel_id)
            return

    except Exception as e:
        print("TEXT_HANDLER_ERROR:", e)
        traceback.print_exc()
        state_clear(uid)
        bot.send_message(uid, "⚠️ خطایی رخ داد. لطفاً دوباره از منو ادامه دهید.", reply_markup=kb_main(uid))
        return

    # ── Auto-detect: admin sends a .db file without restore state ─────────
    if message.content_type == "document" and is_admin(uid):
        file_name = message.document.file_name or ""
        if file_name.lower().endswith(".db"):
            try:
                from ..admin.backup import safe_restore_db
                file_info  = bot.get_file(message.document.file_id)
                downloaded = bot.download_file(file_info.file_path)
                ok, msg    = safe_restore_db(downloaded, file_name)
                state_clear(uid)
                icon = "✅" if ok else "❌"
                bot.send_message(uid, f"{icon} {msg}", parse_mode="HTML", reply_markup=back_button("admin:backup"))
            except Exception as e:
                bot.send_message(uid, f"❌ خطا در بازیابی بکاپ: {esc(str(e))}", parse_mode="HTML", reply_markup=back_button("admin:backup"))
            return

    # Fallback
    if message.content_type == "text":
        if message.text == "/start":
            return
        bot.send_message(uid, "لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=kb_main(uid))


