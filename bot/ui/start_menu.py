# -*- coding: utf-8 -*-
"""Dynamic /start main menu registry and layout helpers."""
import html
import json
import re
from dataclasses import dataclass
from typing import Callable, Optional

from ..db import setting_get, wallet_pay_enabled_for
from ..helpers import is_admin


DEFAULT_LAYOUT = [
    ["buy_service", "my_services"],
    ["free_test"],
    ["wallet", "account"],
    ["voucher", "referral"],
    ["tariff", "apps"],
    ["support"],
    ["agency"],
    ["admin_panel"],
]

DEFAULT_LAYOUT_JSON = json.dumps(DEFAULT_LAYOUT, ensure_ascii=False)


@dataclass(frozen=True)
class StartMenuButton:
    key: str
    default_text: str
    callback_data: str
    emoji_id: str = ""
    enabled_setting: Optional[str] = None
    admin_only: bool = False
    condition: Optional[Callable[[int], bool]] = None


def _user_is_agent(user_id) -> bool:
    try:
        from ..db import get_user
        u = get_user(user_id)
        return bool(u and u["is_agent"])
    except Exception:
        return False


def _free_test_visible(user_id: int) -> bool:
    mode = setting_get("free_test_mode", "everyone")
    return mode == "everyone" or (mode == "agents_only" and _user_is_agent(user_id))


BUTTONS: dict[str, StartMenuButton] = {
    "buy_service": StartMenuButton("buy_service", "خرید سرویس جدید", "buy:start", "5312361253610475399"),
    "my_services": StartMenuButton("my_services", "سرویس‌های من", "my_configs", "5361741454685256344"),
    "free_test": StartMenuButton("free_test", "تست رایگان", "test:start", "6283073379184415506", "free_test_enabled", condition=_free_test_visible),
    "wallet": StartMenuButton("wallet", "کیف پول", "wallet:menu", "5256186332669035163", condition=wallet_pay_enabled_for),
    "account": StartMenuButton("account", "حساب کاربری", "profile", "5373012449597335010"),
    "voucher": StartMenuButton("voucher", "ثبت کارت هدیه", "voucher:redeem", "5418010521309815154", "vouchers_enabled"),
    "referral": StartMenuButton("referral", "زیرمجموعه‌گیری", "referral:menu", "5453957997418004470", "referral_enabled"),
    "tariff": StartMenuButton("tariff", "تعرفه", "tariff:show", "5431722320366429593", "tariff_enabled"),
    "apps": StartMenuButton("apps", "دریافت اپلیکیشن‌ها", "apps:menu", "5244612521087749872", "apps_enabled"),
    "support": StartMenuButton("support", "پشتیبانی", "support", "5467539229468793355"),
    "agency": StartMenuButton("agency", "درخواست نمایندگی", "agency:request", "5372957680174384345", "agency_request_enabled"),
    "admin_panel": StartMenuButton("admin_panel", "ورود به پنل مدیریت", "admin:panel", "5370935802844946281", admin_only=True),
}


def _specific_enabled(button: StartMenuButton) -> bool:
    if button.enabled_setting:
        return setting_get(button.enabled_setting, "1") == "1"
    return True


def button_is_enabled(key: str, user_id: int) -> bool:
    button = BUTTONS.get(key)
    if not button:
        return False
    if button.admin_only and not is_admin(user_id):
        return False
    if setting_get(f"start_menu_enabled:{key}", "1") != "1":
        return False
    if not _specific_enabled(button):
        return False
    if button.condition and not button.condition(user_id):
        return False
    return True


def button_admin_enabled(key: str) -> bool:
    button = BUTTONS.get(key)
    if not button:
        return False
    if setting_get(f"start_menu_enabled:{key}", "1") != "1":
        return False
    return _specific_enabled(button)


def get_button_raw_text(key: str) -> str:
    button = BUTTONS[key]
    custom = setting_get(f"start_menu_text:{key}", "")
    return custom if custom else button.default_text


def get_button_emoji_id(key: str) -> str:
    """Return per-button emoji_id override from settings, falling back to default."""
    button = BUTTONS[key]
    return setting_get(f"start_menu_emoji:{key}", "") or button.emoji_id


def get_button_style(key: str) -> str:
    """Return button style (primary/success/danger) for Telegram API or empty string."""
    return setting_get(f"start_menu_style:{key}", "")


_TG_EMOJI_RE = re.compile(r'<tg-emoji\s+emoji-id=["\'][^"\']+["\']\s*>(.*?)</tg-emoji>', re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def button_text_for_telegram(raw_text: str) -> str:
    """Inline keyboard button text does not parse HTML; return a safe fallback."""
    text = _TG_EMOJI_RE.sub(lambda m: m.group(1), raw_text or "")
    text = _TAG_RE.sub("", text)
    return html.unescape(text).strip()


def get_button_payload(key: str) -> dict:
    sty = get_button_style(key)
    return {
        "text": button_text_for_telegram(get_button_raw_text(key)),
        "callback_data": BUTTONS[key].callback_data,
        "emoji_id": get_button_emoji_id(key) or None,
        "style": sty or None,
    }


def get_layout() -> list[list[str]]:
    raw = setting_get("start_menu_layout", DEFAULT_LAYOUT_JSON)
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            rows = []
            for row in data:
                if isinstance(row, list):
                    clean = [str(k) for k in row if str(k) in BUTTONS]
                    if clean:
                        rows.append(clean[:3])
            if rows:
                return rows
    except Exception:
        pass
    return [list(r) for r in DEFAULT_LAYOUT]


def build_main_menu_rows(user_id: int) -> list[list[dict]]:
    rows: list[list[dict]] = []
    seen = set()
    for layout_row in get_layout():
        row = []
        for key in layout_row[:3]:
            seen.add(key)
            if button_is_enabled(key, user_id):
                row.append(get_button_payload(key))
        if row:
            rows.append(row)

    for key in BUTTONS:
        if key not in seen and button_is_enabled(key, user_id):
            rows.append([get_button_payload(key)])
    return rows


def parse_layout_text(text: str) -> tuple[list[list[str]] | None, str]:
    rows = []
    seen = set()
    valid = set(BUTTONS.keys())
    for line_no, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        keys = line.split()
        if len(keys) > 3:
            return None, f"خط {line_no}: هر ردیف حداکثر ۳ دکمه می‌تواند داشته باشد."
        for key in keys:
            if key not in valid:
                return None, f"خط {line_no}: کلید نامعتبر است: {key}"
            if key in seen:
                return None, f"خط {line_no}: کلید تکراری است: {key}"
            seen.add(key)
        rows.append(keys)
    if not rows:
        return None, "چیدمان نمی‌تواند خالی باشد."
    return rows, ""


def layout_to_text(layout: list[list[str]] | None = None) -> str:
    layout = layout or get_layout()
    return "\n".join(" ".join(row) for row in layout)


def valid_keys_text() -> str:
    return "\n".join(f"<code>{key}</code> — {button_text_for_telegram(BUTTONS[key].default_text)}" for key in BUTTONS)
