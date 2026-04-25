# -*- coding: utf-8 -*-
"""
Main menu screens: home, profile, support, my configs.
"""
import urllib.parse
from telebot import types

from ..config import BRAND_TITLE, DEFAULT_ADMIN_HANDLE
from ..db import setting_get, get_user, get_user_purchases, get_referral_stats, has_pending_rewards, get_pending_rewards_summary, get_user_panel_configs, get_user_purchases_paged, get_user_panel_configs_paged, get_referral_restriction
from ..helpers import esc, fmt_price, display_username, back_button, move_leading_emoji
from ..bot_instance import bot
from .helpers import send_or_edit
from .keyboards import kb_main
from .premium_emoji import render_premium_text_html, render_premium_text_entities, deserialize_premium_text, ce


def show_main_menu(target):
    uid         = target.from_user.id if hasattr(target, "from_user") else target.chat.id
    custom_raw  = setting_get("start_text", "")
    if custom_raw:
        parsed = deserialize_premium_text(custom_raw)
        if parsed.get("entities"):  # has formatting or custom emoji entities
            # Has premium/custom emoji → send via entities (no parse_mode, no HTML issues)
            text, entities = render_premium_text_entities(custom_raw)
            chat_id = (
                target.message.chat.id if hasattr(target, "message") else target.chat.id
            )
            kb = kb_main(uid)
            try:
                if hasattr(target, "message"):
                    bot.edit_message_text(
                        text,
                        target.message.chat.id,
                        target.message.message_id,
                        parse_mode="",
                        entities=entities,
                        reply_markup=kb,
                        disable_web_page_preview=True,
                    )
                else:
                    bot.send_message(
                        chat_id, text,
                        parse_mode="",
                        entities=entities,
                        reply_markup=kb,
                        disable_web_page_preview=True,
                    )
            except Exception:
                try:
                    bot.send_message(
                        chat_id, text,
                        parse_mode="",
                        entities=entities,
                        reply_markup=kb,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    # Last resort: send without emoji formatting
                    bot.send_message(chat_id, text, reply_markup=kb,
                                     disable_web_page_preview=True)
            return
        else:
            text = render_premium_text_html(custom_raw)
    else:
        text = (
            f"{ce('✨', '5325547803936572038')} <b>به فروشگاه {BRAND_TITLE} خوش آمدید!</b>\n\n"
            f"{ce('🛡', '5017108172138087141')} ارائه انواع سرویس‌های VPN با کیفیت عالی\n"
            f"{ce('✅', '5427009714745517609')} تضمین امنیت ارتباطات شما\n"
            f"{ce('📞', '5467539229468793355')} پشتیبانی حرفه‌ای ۲۴ ساعته\n\n"
            "از منوی زیر بخش مورد نظر خود را انتخاب کنید."
        )
    send_or_edit(target, text, kb_main(uid))


def show_profile(target, user_id):
    user = get_user(user_id)
    if not user:
        return
    text = (
        f"{ce('👤', '5373012449597335010')} <b>پروفایل کاربری</b>\n\n"
        f"{ce('📱', '5258011929993026890')} نام: {esc(user['full_name'])}\n"
        f"{ce('🆔', '6118316934766266392')} نام کاربری: {esc(display_username(user['username']))}\n"
        f"{ce('🔢', '5875335525136602241')} آیدی: <code>{user['user_id']}</code>\n\n"
        f"{ce('💰', '5375296873982604963')} موجودی: <b>{fmt_price(user['balance'])}</b> تومان"
    )
    if user["is_agent"]:
        text += f"\n\n{ce('🤝', '5287478403530767368')} <b>حساب نمایندگی فعال است</b>"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(" بازگشت", callback_data="nav:main"))
    send_or_edit(target, text, kb)


def show_support(target):
    support_raw      = setting_get("support_username", DEFAULT_ADMIN_HANDLE)
    from ..helpers import safe_support_url
    support_url      = safe_support_url(support_raw)
    support_link     = setting_get("support_link", "")
    support_link_desc = setting_get("support_link_desc", "")

    kb = types.InlineKeyboardMarkup()
    has_any = False
    if support_url:
        kb.add(types.InlineKeyboardButton("پشتیبانی تلگرام", url=support_url))
        # NOTE: icon_custom_emoji_id not supported on url buttons via pyTelegramBotAPI types; fallback text kept
        has_any = True
    if support_link:
        kb.add(types.InlineKeyboardButton("پشتیبانی آنلاین", url=support_link))
        # NOTE: icon_custom_emoji_id not supported on url buttons via pyTelegramBotAPI types; fallback text kept
        has_any = True
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="nav:main"))

    if not has_any:
        send_or_edit(target, "⚠️ پشتیبانی هنوز تنظیم نشده است.", back_button("main"))
        return

    text = f"{ce('🎧', '5190458330719461749')} <b>ارتباط با پشتیبانی</b>\n\n"
    if support_link_desc:
        text += f"{esc(support_link_desc)}\n\n"
    else:
        text += "از طریق یکی از روش‌های زیر با ما در ارتباط باشید.\n\n"
    send_or_edit(target, text, kb)


# Per-user active search query for "My Configs" view (in-memory)
_user_cfg_search = {}

_MY_CFGS_PER_PAGE = 10


def show_my_configs(target, user_id, page=0, search=None):
    """Show paginated My Configs with optional search and navigation."""
    PER_PAGE = _MY_CFGS_PER_PAGE

    # Update search cache
    if search is not None:
        if search:
            _user_cfg_search[user_id] = search
        else:
            _user_cfg_search.pop(user_id, None)

    active_search = _user_cfg_search.get(user_id)

    # Get total counts (needed for pagination math)
    _, items_total = get_user_purchases_paged(user_id, page=0, per_page=1, search=active_search)
    _, panel_total = get_user_panel_configs_paged(user_id, page=0, per_page=1, search=active_search)
    total = items_total + panel_total

    if total == 0 and not active_search:
        send_or_edit(target, f"{ce('📭', '5258134813302332906')} هنوز کانفیگی برای حساب شما ثبت نشده است.", back_button("main"))
        return

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    offset = page * PER_PAGE

    # Compute per-source slice
    if offset < items_total:
        buy_count = min(PER_PAGE, items_total - offset)
        buy_start = offset
    else:
        buy_count = 0
        buy_start = 0

    panel_start = max(0, offset - items_total)
    panel_count = PER_PAGE - buy_count

    # Fetch page data from each source
    if buy_count > 0:
        all_items, _ = get_user_purchases_paged(
            user_id, page=0, per_page=buy_start + buy_count, search=active_search
        )
        items = list(all_items)[buy_start:]
    else:
        items = []

    if panel_count > 0 and panel_start < panel_total:
        actual_panel = min(panel_count, panel_total - panel_start)
        all_panel, _ = get_user_panel_configs_paged(
            user_id, page=0, per_page=panel_start + actual_panel, search=active_search
        )
        panel_items = list(all_panel)[panel_start:]
    else:
        panel_items = []

    kb = types.InlineKeyboardMarkup()

    # ── Search button row at top ──────────────────────────────────────────────
    if active_search:
        q_display = active_search[:18] + ("…" if len(active_search) > 18 else "")
        kb.row(
            types.InlineKeyboardButton(f"🔍 {q_display}", callback_data="my_configs:search"),
            types.InlineKeyboardButton("❌ پاک کردن جست‌وجو", callback_data="my_configs:csearch"),
        )
    else:
        kb.add(types.InlineKeyboardButton("🔍 جست‌وجو در کانفیگ‌ها", callback_data="my_configs:search"))

    # ── Config buttons (no inline renewal) ───────────────────────────────────
    for item in items:
        expired_mark = " ❌" if item["is_expired"] else ""
        svc_name     = move_leading_emoji(urllib.parse.unquote(item["service_name"] or ""))
        test_label   = ""
        if item["is_test"]:
            hours_left = item["test_hours_left"] if "test_hours_left" in item.keys() else None
            if item["is_expired"]:
                test_label = " 🎁❌"
            elif hours_left is not None:
                h = int(hours_left)
                time_str = f"{h // 24}d{h % 24}h" if h >= 24 else f"{h}h"
                test_label = f" 🎁⏰{time_str}"
            else:
                test_label = " 🎁"
        title = f"{svc_name}{test_label}{expired_mark}"
        kb.add(types.InlineKeyboardButton(title, callback_data=f"mycfg:{item['id']}"))

    # ── Panel configs ─────────────────────────────────────────────────────────
    for pc in panel_items:
        if pc["is_expired"]:
            marker = " ⌛"
        elif int(pc["is_disabled"] or 0):
            marker = " ⛔"
        else:
            marker = " 🟢"
        name = esc(pc["client_name"] or pc["package_name"] or "—")
        kb.add(types.InlineKeyboardButton(f"{name}{marker}", callback_data=f"mypnlcfg:d:{pc['id']}"))

    # ── Pagination row ────────────────────────────────────────────────────────
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"my_configs:p:{page - 1}"))
        nav.append(types.InlineKeyboardButton(f"📄 {page + 1} / {total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(types.InlineKeyboardButton("▶️ بعدی", callback_data=f"my_configs:p:{page + 1}"))
        kb.row(*nav)

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="nav:main"))

    # ── Header ────────────────────────────────────────────────────────────────
    header = f"{ce('📦', '5332618260703624145')} <b>کانفیگ‌های من</b>"
    if active_search:
        header += f"\n🔍 جست‌وجو: <code>{esc(active_search)}</code>"
    if total == 0:
        header += "\n\n📭 نتیجه‌ای یافت نشد."
    else:
        header += "\n\nیکی از سرویس‌ها را انتخاب کنید:"
    send_or_edit(target, header, kb)


def show_referral_menu(target, user_id):
    """Show referral/invite page with stats and share button."""
    if setting_get("referral_enabled", "1") != "1":
        send_or_edit(target,
            "⚠️ <b>سیستم دعوت دوستان</b>\n\n"
            "در حال حاضر سیستم زیرمجموعه‌گیری برای این ربات فعال نشده است.\n"
            "لطفاً بعداً مراجعه کنید یا با پشتیبانی تماس بگیرید.",
            back_button("main"))
        return

    # ── Referral restriction check ─────────────────────────────────────────────
    restriction = get_referral_restriction(user_id)
    if restriction:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="nav:main"))
        send_or_edit(target,
            "⛔️ <b>دسترسی محدود شده</b>\n\n"
            "شما به دلیل مشکوک بودن به تقلب در زیرمجموعه‌گیری، فعلاً از این بخش محدود شده‌اید.\n\n"
            "در صورت نیاز با پشتیبانی در ارتباط باشید.",
            kb)
        return

    stats = get_referral_stats(user_id)
    bot_info = bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    # Build reward info
    start_reward_enabled = setting_get("referral_start_reward_enabled", "0") == "1"
    purchase_reward_enabled = setting_get("referral_purchase_reward_enabled", "0") == "1"

    reward_text = ""
    if start_reward_enabled:
        sr_type = setting_get("referral_start_reward_type", "wallet")
        sr_count = setting_get("referral_start_reward_count", "1")
        if sr_type == "wallet":
            sr_amount = setting_get("referral_start_reward_amount", "0")
            reward_text += f"{ce('🎁', '5215628200578655810')} <b>هدیه عضویت:</b> به ازای هر {sr_count} زیرمجموعه، <b>{fmt_price(int(sr_amount))}</b> تومان شارژ کیف پول\n"
        else:
            reward_text += f"{ce('🎁', '5215628200578655810')} <b>هدیه عضویت:</b> به ازای هر {sr_count} زیرمجموعه، یک کانفیگ رایگان\n"

    if purchase_reward_enabled:
        pr_type = setting_get("referral_purchase_reward_type", "wallet")
        pr_count = setting_get("referral_purchase_reward_count", "1")
        if pr_type == "wallet":
            pr_amount = setting_get("referral_purchase_reward_amount", "0")
            reward_text += f"💸 <b>هدیه خرید:</b> به ازای هر {pr_count} خرید زیرمجموعه، <b>{fmt_price(int(pr_amount))}</b> تومان شارژ کیف پول\n"
        else:
            reward_text += f"💸 <b>هدیه خرید:</b> به ازای هر {pr_count} خرید زیرمجموعه، یک کانفیگ رایگان\n"
    # NOTE: 💸 هدیه خرید uses free emoji as fallback — no custom emoji mapping provided

    if not reward_text:
        reward_text = f"{ce('🎁', '5215628200578655810')} هدیه‌ها هنوز توسط ادمین تنظیم نشده است.\n"

    # ── Pending reward summary ─────────────────────────────────────────────────
    pending_summary = get_pending_rewards_summary(user_id)
    pending_wallet  = pending_summary["wallet_total"]
    pending_configs = pending_summary["config_count"]
    pending_text = ""
    if pending_wallet > 0 or pending_configs > 0:
        pending_lines = []
        if pending_wallet > 0:
            pending_lines.append(f"💰 <b>{fmt_price(pending_wallet)}</b> تومان کیف‌پول")
        if pending_configs > 0:
            pending_lines.append(f"🎁 <b>{pending_configs}</b> کانفیگ رایگان")
        pending_text = (
            f"\n\n{ce('🎁', '5215628200578655810')} <b>پاداش‌های آماده دریافت:</b>\n"
            + "\n".join(f"  • {ln}" for ln in pending_lines)
            + "\n\n⬇️ برای دریافت جایزه، روی دکمه «🎁 دریافت پاداش» کلیک کنید."
        )

    text = (
        f"{ce('💼', '5352896944496728039')} <b>زیرمجموعه‌گیری {ce('🎉', '5359785904535774578')} و دعوت دوستان</b>\n\n"
        "با دعوت دوستان از طریق لینک اختصاصی، بدون پرداخت حتی ۱ ریال "
        "کیف پولت شارژ می‌شه و از خدمات ربات استفاده می‌کنی! 🎉\n\n"
        f"{reward_text}\n"
        f"{ce('📊', '5199749070830197566')} <b>آمار شما:</b>\n"
        f"  {ce('👥', '5472030678633684592')} زیرمجموعه‌ها: <b>{stats['total_referrals']}</b> نفر\n"
        f"  {ce('🛒', '5431577498364158238')} خریدهای زیرمجموعه: <b>{stats['purchase_count']}</b> عدد\n"
        f"  {ce('💵', '5431499171045581032')} مجموع خرید زیرمجموعه: <b>{fmt_price(stats['total_purchase_amount'])}</b> تومان\n\n"
        f"{ce('🔗', '5409048419211682843')} <b>لینک دعوت شما:</b>\n<code>{ref_link}</code>\n\n"
        f"{ce('📢', '5271604874419647061')} <b>دعوت کن، هدیه بگیر، رشد کن!</b>"
        f"{pending_text}"
    )

    # Build share text — ref_link goes in url= param, text in text= param
    custom_banner = setting_get("referral_banner_text", "").strip()
    if custom_banner:
        share_body = custom_banner
    else:
        share_body = (
            f"🔥 می‌خوای با سرعت بالا و پایداری عالی به اینترنت آزاد وصل بشی؟\n\n"
            f"من از {BRAND_TITLE} سرویس VPN خریدم و کاملاً راضیم! 😍\n\n"
            f"✅ سرعت فوق‌العاده\n"
            f"✅ پایداری بالا\n"
            f"✅ پشتیبانی ۲۴ ساعته\n\n"
            # NOTE: share text uses plain emojis (custom emojis can't render outside bot context)
            f"تو هم از لینک من وارد شو و سرویست رو بخر 👇"
        )

    import urllib.parse as _up
    share_url = (
        f"https://t.me/share/url"
        f"?url={_up.quote(ref_link, safe='')}"
        f"&text={_up.quote(share_body, safe='')}"
    )

    kb = types.InlineKeyboardMarkup()

    # ── Pending reward claim button (top, most prominent) ──────────────────────
    if pending_wallet > 0 or pending_configs > 0:
        kb.add(types.InlineKeyboardButton("🎁 دریافت پاداش", callback_data="referral:claim_reward"))

    # ── Share buttons — side by side ───────────────────────────────────────────
    banner_photo = setting_get("referral_banner_photo", "").strip()
    if banner_photo:
        kb.row(
            types.InlineKeyboardButton("📤 دریافت پست آماده", callback_data="referral:get_banner"),
            types.InlineKeyboardButton("🔗 اشتراک‌گذاری لینک", url=share_url),
        )
    else:
        kb.add(types.InlineKeyboardButton("🔗 اشتراک‌گذاری لینک دعوت", url=share_url))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="nav:main"))

    # Send photo banner on the referral menu itself if configured, otherwise plain text
    chat_id = target.message.chat.id if hasattr(target, "message") else target.chat.id
    if banner_photo:
        try:
            if hasattr(target, "message"):
                try:
                    bot.delete_message(chat_id, target.message.message_id)
                except Exception:
                    pass
            bot.send_photo(chat_id, banner_photo, caption=text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass  # Fall through to plain text if photo fails

    send_or_edit(target, text, kb)
