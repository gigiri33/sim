# -*- coding: utf-8 -*-
"""
Glass Buy Flow
==============
Handles the "منوی فاکتور شیشه‌ای" purchase mode.

Entry point: show_glass_buy(call, type_id)
Returns control to existing _show_naming_prompt / _show_discount_prompt /
_show_purchase_gateways helpers once the user confirms.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Custom-emoji IDs used in the glass invoice UI ────────────────────────────
_CE_SHOP    = "5987873465112204157"   # 🛍
_CE_VOLUME  = "5987617871608420127"   # 🔸
_CE_TIME    = "5987617871608420127"   # 🔹
_CE_USER    = "5348136664738839786"   # 👥
_CE_QTY     = "5221928131622883525"   # 🔢
_CE_MONEY   = "5987758377168540855"   # 💱
_CE_INFO    = "5895288113537748673"   # 💡
_CE_PLUS    = "5274008024585871702"   # ➕
_CE_MINUS   = "5339174274877904481"   # ➖


def _ce(eid: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'


# ─────────────────────────────────────────────────────────────────────────────
# Number → Persian words (simple, for common amounts up to billions)
# ─────────────────────────────────────────────────────────────────────────────
_ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه",
         "ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده",
         "هفده", "هجده", "نوزده"]
_TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد",
             "هفتصد", "هشتصد", "نهصد"]


def _three_digits(n: int) -> str:
    """Convert 0–999 to Persian words."""
    if n == 0:
        return ""
    parts = []
    h = n // 100
    r = n % 100
    if h:
        parts.append(_HUNDREDS[h])
    if r < 20:
        if r:
            parts.append(_ONES[r])
    else:
        t = r // 10
        o = r % 10
        parts.append(_TENS[t])
        if o:
            parts.append(_ONES[o])
    return " و ".join(parts)


def num_to_persian_words(n: int) -> str:
    """Convert a non-negative integer to its Persian verbal form."""
    if n == 0:
        return "صفر"
    if n < 0:
        return "منهای " + num_to_persian_words(-n)
    parts = []
    billions = n // 1_000_000_000
    millions = (n % 1_000_000_000) // 1_000_000
    thousands = (n % 1_000_000) // 1_000
    remainder = n % 1_000
    if billions:
        parts.append(_three_digits(billions) + " میلیارد")
    if millions:
        parts.append(_three_digits(millions) + " میلیون")
    if thousands:
        parts.append(_three_digits(thousands) + " هزار")
    if remainder:
        parts.append(_three_digits(remainder))
    return " و ".join(p for p in parts if p)


# ─────────────────────────────────────────────────────────────────────────────
# Sort key helpers for packages
# ─────────────────────────────────────────────────────────────────────────────
_UNLIMITED_SORT = 999_999_999


def _vol_sort(gb) -> float:
    """0 (unlimited) sorts last."""
    f = float(gb or 0)
    return _UNLIMITED_SORT if f == 0 else f


def _dur_sort(days: int) -> int:
    return _UNLIMITED_SORT if int(days or 0) == 0 else int(days)


def _users_sort(mu: int) -> int:
    return _UNLIMITED_SORT if int(mu or 0) == 0 else int(mu)


def sort_packages(packages) -> list:
    """Sort packages: duration ASC, volume ASC, user_limit ASC, price ASC.
    Unlimited values of any dimension are placed last within that dimension."""
    return sorted(packages, key=lambda p: (
        _dur_sort(p["duration_days"]),
        _vol_sort(p["volume_gb"]),
        _users_sort(p["max_users"] if "max_users" in p.keys() else 0),
        int(p["price"]),
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Glass Buy Session  (stored in USER_STATE data)
# ─────────────────────────────────────────────────────────────────────────────

class GlassSession:
    """Mutable session object for the glass buy flow."""

    def __init__(
        self,
        type_id: int,
        packages: list,
        max_qty: int,
        enabled_dims: Optional[set] = None,
    ):
        self.type_id  = type_id
        self.packages = sort_packages([p for p in packages if p["price"] > 0])
        self.max_qty  = max(1, max_qty)

        if not self.packages:
            raise ValueError("no_packages")

        # Unique sorted dimension lists (0 = unlimited stays, sorts last)
        self.volumes      = self._unique_vals("volume_gb",   _vol_sort)
        self.durations    = self._unique_vals("duration_days", _dur_sort)
        self.user_limits  = self._unique_vals_mu()

        # Start from first sorted package
        first = self.packages[0]
        self.sel_volume     = float(first["volume_gb"])
        self.sel_duration   = int(first["duration_days"])
        self.sel_user_limit = int(first["max_users"] if "max_users" in first.keys() else 0)
        self.sel_quantity   = 1

        self.enabled_dims = set(enabled_dims) if enabled_dims else {"v", "d", "u", "q"}
        self._sync_package()  # find matched package + amount + stock

    # ── dim list builders ────────────────────────────────────────────────────

    def _unique_vals(self, field: str, sort_key) -> list:
        raw = [float(p[field]) if field == "volume_gb" else int(p[field]) for p in self.packages]
        return sorted(set(raw), key=sort_key)

    def _unique_vals_mu(self) -> list:
        raw = [int(p["max_users"] if "max_users" in p.keys() else 0) for p in self.packages]
        return sorted(set(raw), key=_users_sort)

    # ── package matching ─────────────────────────────────────────────────────

    def _sync_package(self):
        """Find the best matching active package for current selections."""
        pkg = self._find_package(self.sel_volume, self.sel_duration, self.sel_user_limit)
        if pkg is None:
            # Fallback: first package with selected_volume
            pkg = next((p for p in self.packages if float(p["volume_gb"]) == self.sel_volume), None)
        if pkg is None:
            pkg = self.packages[0]
        # Update selections to match actual package
        self.sel_volume     = float(pkg["volume_gb"])
        self.sel_duration   = int(pkg["duration_days"])
        self.sel_user_limit = int(pkg["max_users"] if "max_users" in pkg.keys() else 0)
        self.matched_pkg    = pkg
        self.unit_price     = int(pkg["price"])
        raw_stock = pkg["stock"] if "stock" in pkg.keys() else None
        self.stock          = int(raw_stock) if raw_stock is not None else None   # None = unlimited

    def _find_package(self, vol, dur, mu) -> Optional[Any]:
        """Exact match first, then closest."""
        exact = [p for p in self.packages
                 if float(p["volume_gb"]) == vol
                 and int(p["duration_days"]) == dur
                 and int(p["max_users"] if "max_users" in p.keys() else 0) == mu]
        if exact:
            return exact[0]
        # Relax user_limit
        partial = [p for p in self.packages
                   if float(p["volume_gb"]) == vol and int(p["duration_days"]) == dur]
        if partial:
            return partial[0]
        return None

    # ── dimension navigation ─────────────────────────────────────────────────

    def _step(self, lst: list, cur, delta: int):
        """Move current value one step in list. Returns (new_val, alert)."""
        if cur not in lst:
            return cur, None
        idx = lst.index(cur)
        new_idx = idx + delta
        if new_idx < 0:
            return cur, "min"
        if new_idx >= len(lst):
            return cur, "max"
        return lst[new_idx], None

    def change_volume(self, delta: int) -> Optional[str]:
        new_val, alert = self._step(self.volumes, self.sel_volume, delta)
        if alert:
            return alert
        self.sel_volume = new_val
        self._sync_package()
        return None

    def change_duration(self, delta: int) -> Optional[str]:
        new_val, alert = self._step(self.durations, self.sel_duration, delta)
        if alert:
            return alert
        self.sel_duration = new_val
        self._sync_package()
        return None

    def change_user_limit(self, delta: int) -> Optional[str]:
        new_val, alert = self._step(self.user_limits, self.sel_user_limit, delta)
        if alert:
            return alert
        self.sel_user_limit = new_val
        self._sync_package()
        return None

    def change_quantity(self, delta: int) -> Optional[str]:
        new_qty = self.sel_quantity + delta
        if new_qty < 1:
            return "qty_min"
        if new_qty > self.max_qty:
            return "qty_max"
        self.sel_quantity = new_qty
        return None

    # ── derived values ───────────────────────────────────────────────────────

    @property
    def total_price(self) -> int:
        return self.unit_price * self.sel_quantity

    @property
    def stock_ok(self) -> bool:
        if self.stock is None:
            return True
        return self.stock >= self.sel_quantity

    # ── dimension flags ──────────────────────────────────────────────────────

    @property
    def all_vol_unlimited(self) -> bool:
        return all(float(p["volume_gb"]) == 0 for p in self.packages)

    @property
    def all_dur_unlimited(self) -> bool:
        return all(int(p["duration_days"]) == 0 for p in self.packages)

    @property
    def all_mu_unlimited(self) -> bool:
        return all(int(p["max_users"] if "max_users" in p.keys() else 0) == 0 for p in self.packages)

    # ── serialise/restore (to/from state dict) ───────────────────────────────

    def to_state(self) -> dict:
        return {
            "_glass": True,
            "type_id":        self.type_id,
            "sel_volume":     self.sel_volume,
            "sel_duration":   self.sel_duration,
            "sel_user_limit": self.sel_user_limit,
            "sel_quantity":   self.sel_quantity,
            "max_qty":        self.max_qty,
            "enabled_dims":   list(self.enabled_dims),
        }

    @classmethod
    def from_state(cls, state_dict: dict, packages: list) -> "GlassSession":
        obj = object.__new__(cls)
        obj.type_id      = state_dict["type_id"]
        obj.max_qty      = state_dict["max_qty"]
        obj.packages     = sort_packages([p for p in packages if p["price"] > 0])
        obj.volumes      = obj._unique_vals("volume_gb",   _vol_sort)
        obj.durations    = obj._unique_vals("duration_days", _dur_sort)
        obj.user_limits  = obj._unique_vals_mu()
        obj.sel_volume     = state_dict["sel_volume"]
        obj.sel_duration   = state_dict["sel_duration"]
        obj.sel_user_limit = state_dict["sel_user_limit"]
        obj.sel_quantity   = state_dict["sel_quantity"]
        obj.enabled_dims   = set(state_dict.get("enabled_dims", ["v", "d", "u", "q"]))
        obj._sync_package()
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# Text & Keyboard builders
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_vol(gb) -> str:
    from ..helpers import fmt_vol
    return fmt_vol(gb)


def _fmt_dur(days: int) -> str:
    from ..helpers import fmt_dur
    return fmt_dur(days)


def _fmt_mu(mu: int) -> str:
    return "بدون محدودیت" if mu == 0 else f"{mu} کاربر"


def _build_title(ses: GlassSession) -> str:
    vol_s = "حجم نامحدود" if ses.sel_volume == 0 else _fmt_vol(ses.sel_volume)
    dur_s = "زمان نامحدود" if ses.sel_duration == 0 else _fmt_dur(ses.sel_duration)
    if ses.sel_volume == 0 and ses.sel_duration == 0:
        inner = "سرویس نامحدود"
    elif ses.sel_volume == 0:
        inner = f"{dur_s} حجم نامحدود"
    elif ses.sel_duration == 0:
        inner = f"زمان نامحدود {vol_s}"
    else:
        inner = f"{dur_s} {vol_s}"
    return f'{_ce(_CE_SHOP, "🛍")} <b>فاکتور خرید [ {inner} ]</b>'


def build_glass_invoice_text(ses: GlassSession, invoice_description: str = "") -> str:
    from ..helpers import fmt_price

    vol_s = "حجم نامحدود" if ses.sel_volume == 0 else _fmt_vol(ses.sel_volume)
    dur_s = "زمان نامحدود" if ses.sel_duration == 0 else _fmt_dur(ses.sel_duration)
    mu_s  = _fmt_mu(ses.sel_user_limit)
    price_s = fmt_price(ses.total_price)
    try:
        price_words = num_to_persian_words(ses.total_price)
        price_line = f"{price_s} ({price_words}) تومان"
    except Exception:
        price_line = f"{price_s} تومان"

    if ses.stock is None:
        stock_line = "نامحدود"
    else:
        stock_line = f"{ses.stock} کانفیگ"

    lines = [_build_title(ses), ""]
    if "v" in ses.enabled_dims:
        lines += [f'{_ce(_CE_VOLUME, "🔸")} حجم: <b>{vol_s}</b>', ""]
    if "d" in ses.enabled_dims:
        lines += [f'{_ce(_CE_TIME,   "🔹")} زمان: <b>{dur_s}</b>', ""]
    if "u" in ses.enabled_dims:
        lines += [f'{_ce(_CE_USER,   "👥")} محدودیت کاربر: <b>{mu_s}</b>', ""]
    if "q" in ses.enabled_dims:
        lines += [f'{_ce(_CE_QTY,    "🔢")} تعداد: <b>{ses.sel_quantity} عدد</b>', ""]
    lines.append(f'{_ce(_CE_MONEY,  "💱")} مبلغ: <b>{price_line}</b>')

    if invoice_description:
        lines += [
            "",
            f'{_ce(_CE_INFO, "💡")} توضیحات:',
            f"<blockquote>{invoice_description}</blockquote>",
        ]

    return "\n".join(lines)


def build_glass_invoice_keyboard(ses: GlassSession, type_id: int) -> str:
    """Build an inline keyboard JSON string for the glass buy menu."""

    tid = type_id
    rows = []

    _PLUS  = "5274008024585871702"
    _MINUS = "5339174274877904481"

    def _plus_btn(cb):
        return {"text": "افزایش", "callback_data": cb, "icon_custom_emoji_id": _PLUS}

    def _minus_btn(cb):
        return {"text": "کاهش", "callback_data": cb, "icon_custom_emoji_id": _MINUS}

    # ── Volume row ────────────────────────────────────────────────────────────
    if "v" in ses.enabled_dims:
        vol_s = "حجم نامحدود" if ses.sel_volume == 0 else _fmt_vol(ses.sel_volume)
        rows.append([
            _plus_btn(f"buyg:{tid}:v:+"),
            {"text": vol_s, "callback_data": "noop", "style": "primary"},
            _minus_btn(f"buyg:{tid}:v:-"),
        ])

    # ── Duration row ──────────────────────────────────────────────────────────
    if "d" in ses.enabled_dims:
        dur_s = "زمان نامحدود" if ses.sel_duration == 0 else _fmt_dur(ses.sel_duration)
        rows.append([
            _plus_btn(f"buyg:{tid}:d:+"),
            {"text": dur_s, "callback_data": "noop", "style": "primary"},
            _minus_btn(f"buyg:{tid}:d:-"),
        ])

    # ── User limit row ────────────────────────────────────────────────────────
    if "u" in ses.enabled_dims:
        mu_s = _fmt_mu(ses.sel_user_limit)
        rows.append([
            _plus_btn(f"buyg:{tid}:u:+"),
            {"text": mu_s, "callback_data": "noop", "style": "primary"},
            _minus_btn(f"buyg:{tid}:u:-"),
        ])

    # ── Quantity row ──────────────────────────────────────────────────────────
    if "q" in ses.enabled_dims:
        rows.append([
            _plus_btn(f"buyg:{tid}:q:+"),
            {"text": f"{ses.sel_quantity} عدد", "callback_data": "noop", "style": "primary"},
            _minus_btn(f"buyg:{tid}:q:-"),
        ])

    # ── Confirm / Back ────────────────────────────────────────────────────────
    rows.append([{"text": "تایید", "callback_data": f"buyg:{tid}:confirm", "style": "success", "icon_custom_emoji_id": "5357069174512303778"}])
    rows.append([{"text": "بازگشت", "callback_data": f"buyg:{tid}:back", "icon_custom_emoji_id": "5253997076169115797"}])

    return json.dumps({"inline_keyboard": rows})


# ─────────────────────────────────────────────────────────────────────────────
# Alert messages
# ─────────────────────────────────────────────────────────────────────────────

_ALERTS = {
    "min":      "به حداقل مقدار مجاز رسیده‌اید.",
    "max":      "به حداکثر مقدار مجاز رسیده‌اید.",
    "qty_min":  "تعداد نمی‌تواند کمتر از ۱ باشد.",
    "qty_max":  "تعداد از حداکثر مجاز بیشتر است.",
    "no_stock": "موجودی کافی نیست.",
    "no_pkg":   "برای این ترکیب، پکیج فعالی وجود ندارد.",
    "empty":    "برای این دسته‌بندی هنوز پکیجی ثبت نشده است.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Package filter helpers (inline to avoid circular import with callbacks.py)
# ─────────────────────────────────────────────────────────────────────────────

def _br_ok(p, is_agent: bool) -> bool:
    br = p["buyer_role"] if "buyer_role" in p.keys() else "all"
    if br == "nobody":
        return False
    if br == "agents" and not is_agent:
        return False
    if br == "public" and is_agent:
        return False
    return True


def _pkg_has_stock(p, stock_only: bool) -> bool:
    try:
        if (p["config_source"] or "manual") == "panel":
            return True
    except (IndexError, KeyError):
        pass
    return not stock_only or p["stock"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Public API imported into callbacks.py
# ─────────────────────────────────────────────────────────────────────────────

def show_glass_buy(call, type_id: int):
    """Entry point — called from buy:t: handler when purchase_mode='glass'."""
    from ..bot_instance import bot
    from ..db import get_packages, get_type, setting_get
    from ..helpers import state_set, esc
    from ..ui.helpers import send_or_edit

    uid = call.from_user.id

    type_row = get_type(type_id)
    if not type_row:
        bot.answer_callback_query(call.id, "نوع سرویس یافت نشد.", show_alert=True)
        return

    user_row = None
    try:
        from ..db import get_user as _gu
        user_row = _gu(uid)
    except Exception:
        pass
    _is_agent = bool(user_row and user_row["is_agent"])

    stock_only = setting_get("preorder_mode", "0") == "1"
    packages = [p for p in get_packages(type_id=type_id)
                if p["price"] > 0 and _br_ok(p, _is_agent) and _pkg_has_stock(p, stock_only)]

    if not packages:
        bot.answer_callback_query(call.id, _ALERTS["empty"], show_alert=True)
        return

    try:
        max_qty = int(setting_get("max_order_quantity", "10") or "10")
    except Exception:
        max_qty = 10

    # Read admin-configured enabled dims from DB
    try:
        _dims_str = type_row["glass_enabled_dims"] if "glass_enabled_dims" in type_row.keys() else "v,d,u,q"
        enabled_dims = set((_dims_str or "v,d,u,q").split(","))
    except Exception:
        enabled_dims = {"v", "d", "u", "q"}

    try:
        ses = GlassSession(type_id=type_id, packages=packages, max_qty=max_qty, enabled_dims=enabled_dims)
    except ValueError:
        bot.answer_callback_query(call.id, _ALERTS["empty"], show_alert=True)
        return

    state_set(uid, "glass_buy", **ses.to_state())

    inv_desc = ""
    try:
        inv_desc = type_row["invoice_description"] if "invoice_description" in type_row.keys() else ""
    except Exception:
        pass

    text = build_glass_invoice_text(ses, inv_desc)
    kb   = build_glass_invoice_keyboard(ses, type_id)
    bot.answer_callback_query(call.id)
    send_or_edit(call, text, kb)


def _reload_session(uid: int, type_id: int) -> Optional[GlassSession]:
    """Restore session from USER_STATE."""
    from ..helpers import state_name as _sn, state_data as _sd
    from ..db import get_packages, setting_get
    if _sn(uid) != "glass_buy":
        return None
    sd = _sd(uid)
    if not sd.get("_glass") or sd.get("type_id") != type_id:
        return None
    try:
        max_qty = int(setting_get("max_order_quantity", "10") or "10")
    except Exception:
        max_qty = 10
    sd["max_qty"] = max_qty

    user_row = None
    try:
        from ..db import get_user as _gu2
        user_row = _gu2(uid)
    except Exception:
        pass
    _is_agent = bool(user_row and user_row["is_agent"])
    stock_only = setting_get("preorder_mode", "0") == "1"

    packages = [p for p in get_packages(type_id=type_id)
                if p["price"] > 0 and _br_ok(p, _is_agent) and _pkg_has_stock(p, stock_only)]
    try:
        return GlassSession.from_state(sd, packages)
    except Exception:
        return None


def _refresh_invoice(call, ses: GlassSession, type_id: int):
    """Edit the existing message with updated invoice text + keyboard. Never sends a new message."""
    from ..bot_instance import bot
    from ..db import get_type

    inv_desc = ""
    try:
        tr = get_type(type_id)
        if tr:
            inv_desc = tr["invoice_description"] if "invoice_description" in tr.keys() else ""
    except Exception:
        pass

    text = build_glass_invoice_text(ses, inv_desc)
    kb   = build_glass_invoice_keyboard(ses, type_id)

    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception as _e:
        # "message is not modified" is harmless; log everything else
        if "message is not modified" not in str(_e).lower():
            log.warning("_refresh_invoice edit failed: %s", _e)


def handle_glass_callback(call, data: str):
    """
    Handle all buyg:{type_id}:{action} callbacks.
    Returns True if handled, False if unknown.
    """
    from ..bot_instance import bot
    from ..helpers import state_set, state_clear

    parts = data.split(":")          # ["buyg", tid, action, dir?]
    if len(parts) < 3:
        return False

    try:
        type_id = int(parts[1])
    except (ValueError, IndexError):
        return False

    action = parts[2]
    uid = call.from_user.id

    # ── back ─────────────────────────────────────────────────────────────────
    if action == "back":
        state_clear(uid)
        bot.answer_callback_query(call.id)
        from ..admin.renderers import _fake_call
        _fake_call(call, "buy:start")
        return True

    # ── dimension changes (invoice step) ──────────────────────────────────────
    ses = _reload_session(uid, type_id)
    if ses is None:
        # Session expired — restart
        bot.answer_callback_query(call.id, "جلسه منقضی شد. دوباره امتحان کنید.", show_alert=True)
        state_clear(uid)
        return True

    direction_map = {"+": 1, "-": -1}

    if action in ("v", "d", "u", "q"):
        if len(parts) < 4 or parts[3] not in ("+", "-"):
            bot.answer_callback_query(call.id)
            return True
        delta = direction_map[parts[3]]

        if action == "v":
            alert = ses.change_volume(delta)
        elif action == "d":
            alert = ses.change_duration(delta)
        elif action == "u":
            alert = ses.change_user_limit(delta)
        else:
            alert = ses.change_quantity(delta)

        if alert:
            bot.answer_callback_query(call.id, _ALERTS.get(alert, ""), show_alert=True)
            return True

        # Save updated state
        state_set(uid, "glass_buy", **ses.to_state())
        bot.answer_callback_query(call.id)
        _refresh_invoice(call, ses, type_id)
        return True

    # ── confirm ───────────────────────────────────────────────────────────────
    if action == "confirm":
        if not ses.stock_ok:
            bot.answer_callback_query(call.id, _ALERTS["no_stock"], show_alert=True)
            return True

        package_id = ses.matched_pkg["id"]
        quantity   = ses.sel_quantity
        price      = ses.total_price
        unit_price = ses.unit_price
        package_row = ses.matched_pkg

        # Save into buy_select_method so existing payment flow works unchanged
        from ..helpers import state_set as _ss
        _ss(uid, "buy_select_method",
            package_id=package_id,
            amount=price,
            original_amount=price,
            discount_amount=0,
            kind="config_purchase",
            unit_price=unit_price,
            quantity=quantity)

        bot.answer_callback_query(call.id)

        # Re-use existing _show_naming_prompt / _show_discount_prompt / _show_purchase_gateways
        from ..handlers.callbacks import (
            _is_panel_package, _show_naming_prompt,
            _show_discount_prompt, _show_purchase_gateways,
        )
        if _is_panel_package(package_row):
            _show_naming_prompt(call, package_id, quantity)
            return True
        if _show_discount_prompt(call, price):
            return True
        from ..db import get_user as _gu3
        _show_purchase_gateways(call, uid, package_id, price, package_row)
        return True

    return False
