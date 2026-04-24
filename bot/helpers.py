# -*- coding: utf-8 -*-
import html
import json
import re
from datetime import datetime, timezone, timedelta

import jdatetime
from telebot import types

_TZ_TEHRAN = timezone(timedelta(hours=3, minutes=30))

from .config import ADMIN_IDS, PERM_USER_FULL
from .bot_instance import bot, USER_STATE, PERSIAN_DIGITS


# ── Time ───────────────────────────────────────────────────────────────────────
def now_str():
    """Return current Tehran time as a Jalali date-time string: ۱۴۰۴-۰۱-۲۸ ۱۰:۳۰:۰۰"""
    dt = datetime.now(_TZ_TEHRAN)
    jdt = jdatetime.datetime.fromgregorian(datetime=dt)
    return jdt.strftime("%Y-%m-%d %H:%M:%S")


# ── Admin auth ─────────────────────────────────────────────────────────────────
def is_admin(uid):
    if uid in ADMIN_IDS:
        return True
    try:
        from .db import get_admin_user
        return get_admin_user(uid) is not None
    except Exception:
        return False


def admin_has_perm(uid, perm):
    if uid in ADMIN_IDS:
        return True
    try:
        from .db import get_admin_user
        row = get_admin_user(uid)
    except Exception:
        return False
    if not row:
        return False
    perms = json.loads(row["permissions"] or "{}")
    if perms.get("full"):
        return True
    if perm in PERM_USER_FULL and perms.get("full_users"):
        return True
    return bool(perms.get(perm, False))


# ── Text / number helpers ──────────────────────────────────────────────────────
def normalize_text_number(v):
    v = (v or "").translate(PERSIAN_DIGITS)
    v = v.replace(",", "").replace("٬", "").replace(" ", "")
    v = v.replace("تومان", "").replace("ریال", "")
    return v.strip()


def parse_int(v):
    c = normalize_text_number(v)
    if not c or not re.fullmatch(r"\d+", c):
        return None
    return int(c)


def parse_volume(v):
    """Parse a volume string that may be integer or decimal (e.g. 0.5, 10).
    Returns float or None. Accepts both . and , as decimal separator."""
    c = normalize_text_number(v)
    if not c:
        return None
    c = c.replace(",", ".")
    try:
        num = float(c)
    except ValueError:
        return None
    if num < 0:
        return None
    return num


def fmt_price(a):
    return f"{int(a):,}"


def fmt_vol(gb):
    """Return 'حجم نامحدود' if gb == 0, else '{gb} گیگ'."""
    if float(gb) == 0:
        return "حجم نامحدود"
    # Show as integer if whole number, otherwise show up to 3 decimal places
    f = float(gb)
    return f"{int(f)} گیگ" if f == int(f) else f"{f:g} گیگ"


def fmt_dur(days):
    """Return 'زمان نامحدود' if days == 0, else '{days} روز'."""
    return "زمان نامحدود" if int(days) == 0 else f"{days} روز"


def display_name(u):
    n = " ".join(p for p in [u.first_name or "", u.last_name or ""] if p).strip()
    return n or "ㅤ"


def normalize_iranian_phone(phone: str):
    """Normalize a phone number to Iranian format (09XXXXXXXXX).
    Returns normalized string or None if not a valid Iranian mobile number."""
    phone = re.sub(r"\D", "", str(phone or ""))
    if phone.startswith("98") and len(phone) == 12:
        phone = "0" + phone[2:]
    if len(phone) == 11 and phone.startswith("09"):
        return phone
    return None


def display_username(u):
    return f"@{u}" if u else "@ ندارد"


def safe_support_url(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.replace("t.me/", "").replace("telegram.me/", "").replace("@", "").strip()
    return f"https://t.me/{raw}" if raw else None


def esc(t):
    return html.escape(str(t or ""))


# ── Service name display helper ────────────────────────────────────────────────
_LEADING_EMOJI_RE = re.compile(
    r'^((?:[\U00002600-\U000027BF'
    r'\U0001F300-\U0001FAFF'
    r'\U00002702-\U000027B0'
    r'\uFE0F\u200D\u20E3\u00A9\u00AE'
    r']\s*)+)'
)

def move_leading_emoji(name: str) -> str:
    """Move leading emojis to the end of a service name string.
    e.g. '🚀 SPACE VPN-xxx' → 'SPACE VPN-xxx 🚀'
    """
    if not name:
        return name
    m = _LEADING_EMOJI_RE.match(name)
    if not m:
        return name
    prefix = m.group(1)
    rest = name[len(prefix):]
    if not rest.strip():
        return name
    return rest.strip() + " " + prefix.strip()


# ── State management ───────────────────────────────────────────────────────────
def state_set(uid, name, **data):
    USER_STATE[uid] = {"state_name": name, "data": data}


def state_clear(uid):
    USER_STATE.pop(uid, None)


def state_name(uid):
    s = USER_STATE.get(uid)
    return s["state_name"] if s else None


def state_data(uid):
    s = USER_STATE.get(uid)
    return s["data"] if s else {}


# ── UI shortcut ────────────────────────────────────────────────────────────────
def back_button(target="main"):
    import json
    return json.dumps({"inline_keyboard": [[{
        "text": "بازگشت",
        "callback_data": f"nav:{target}",
        "icon_custom_emoji_id": "5253997076169115797",
    }]]})


# ── Service name validation & normalization ────────────────────────────────────
_SERVICE_NAME_RE = re.compile(r'^[a-z0-9]+$')


def validate_service_name(name: str) -> bool:
    """Return True if name contains only lowercase ASCII letters and digits."""
    return bool(name) and bool(_SERVICE_NAME_RE.match(name))


def normalize_service_name(raw: str) -> "str | None":
    """Lowercase, strip, then validate.  Returns None for empty or invalid input.

    Converts uppercase to lowercase; rejects anything with non-[a-z0-9] chars
    (Farsi, spaces, special chars, styled Unicode, emoji, …).
    """
    if not raw:
        return None
    name = raw.strip().lower()
    if validate_service_name(name):
        return name
    return None


def generate_random_service_name(uid: int) -> str:
    """Generate a random service name in the format ``{uid}_{6-char random}``.

    The underscore is intentional for system-generated names to distinguish
    them visually from user-chosen names (which are ``[a-z0-9]+`` only).
    """
    import random
    import string as _string
    rand = "".join(random.choices(_string.ascii_lowercase + _string.digits, k=6))
    return f"{uid}_{rand}"


def parse_service_names_multiline(text: str, count: int, uid: int) -> list:
    """Parse a multiline string into exactly ``count`` valid service names.

    Rules:
    - Each non-empty line is trimmed and normalised (lowercased).
    - Valid lines (``[a-z0-9]+``) are used as-is.
    - Invalid lines are silently replaced with a random name.
    - If fewer lines than ``count`` are present, remaining slots are random.
    - Extra lines beyond ``count`` are ignored.

    Returns a list of exactly ``count`` strings.
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    result: list = []
    for line in lines[:count]:
        norm = normalize_service_name(line)
        result.append(norm if norm else generate_random_service_name(uid))
    # Pad with random names if fewer lines than required
    while len(result) < count:
        result.append(generate_random_service_name(uid))
    return result
