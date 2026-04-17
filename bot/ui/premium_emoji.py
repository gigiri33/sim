# -*- coding: utf-8 -*-
"""
Helpers for Telegram Premium / Custom Emoji support.

SCOPE: Dynamic texts (admin/user) AND static bot strings (custom emoji HTML tags).
"""
from __future__ import annotations

import html
import json
import re

# Matches Persian/Arabic letters and digits only
_PERSIAN_WORD_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]+')


# ── Custom emoji HTML helper ──────────────────────────────────────────────────

# ── Centralized premium emoji map ────────────────────────────────────────────
# Format: key → (fallback_char, emoji_id)
EMOJI: dict[str, tuple[str, str]] = {
    # Crypto
    "tron":          ("🔵", "5794054896852409524"),
    "ton":           ("💎", "5796252975215156083"),
    "usdt":          ("🟢", "5796237685131582541"),
    "usdc":          ("🔵", "5796237685131582541"),
    "ltc":           ("🌊", "5796399747132563586"),
    "bnb":           ("🟡", "4956574641075258382"),
    # Main menu buttons
    "buy_config":    ("🛒", "5312361253610475399"),
    "my_configs":    ("🌐", "5447410659077661506"),
    "test_free":     ("🎁", "6283073379184415506"),
    "wallet_charge": ("💸", "5931368295545443065"),
    "support":       ("🎧", "5307746710682869587"),
    "agency_req":    ("🤝", "5372957680174384345"),
    "admin_panel":   ("⚙️", "5370935802844946281"),
    "back":          ("🔙", "5352759161945867747"),
    # Payment
    "card_payment":  ("💳", "5796315849241403403"),
    "crypto_pay":    ("💎", "5794002949222964817"),
    "amount":        ("💰", "5224257782013769471"),
    "wallet_addr":   ("👛", "5796280694934085416"),
    # Service delivery
    "check":         ("✅", "5427009714745517609"),
    "service_name":  ("🔮", "5361837567463399422"),
    "volume":        ("🔋", "5924538142198600679"),
    "duration":      ("⏰", "5413704112220949842"),
    "config_text":   ("💝", "5465263910414195580"),
    "sub_link":      ("🔗", "5375129357373165375"),
    # Profile
    "balance":       ("💰", "5375296873982604963"),
    "agency_acc":    ("🤝", "5908990051349434897"),
    # Start text
    "welcome":       ("✨", "5325547803936572038"),
    "vpn":           ("🛡",  "5017108172138087141"),
    "support_24":    ("📞", "5467539229468793355"),
}

# Old emoji IDs → new premium IDs (applied transparently inside ce())
_ID_REMAP: dict[str, str] = {
    "5260463209562776385": "5427009714745517609",  # ✅ check (service ready)
    "5343724178547691280": "5413704112220949842",  # ⏰ duration
    "5900197669178970457": "5465263910414195580",  # 💝 config text
    "5271604874419647061": "5375129357373165375",  # 🔗 sub link
    "5287478403530767368": "5908990051349434897",  # 🤝 agency account
    "5190458330719461749": "5307746710682869587",  # 🎧 support
    "5406865085471663921": "5796315849241403403",  # 💳 payment header
    "5318912792428814144": "5224257782013769471",  # 💰 amount (mablag)
    "5415963453997214172": "5908990051349434897",  # 🤝 agency payment note
    "5332618260703624145": "5447410659077661506",  # 📦 my configs header (old)
    "5258134813302332906": "5447410659077661506",  # 📦 my configs (prev premium)
    "5431499171045581032": "5312361253610475399",  # 🛒 buy config (prev premium)
    "5199749070830197566": "6283073379184415506",  # 🎁 test free (prev id)
}


def ce(emoji: str, eid: str | int) -> str:
    """Return a <tg-emoji> HTML tag for use with parse_mode='HTML'.

    The *emoji* argument is the visible fallback character shown on clients
    that do not support custom emoji.  Known old IDs are transparently
    remapped to their premium replacements via _ID_REMAP.
    """
    eid_str = _ID_REMAP.get(str(eid), str(eid))
    return f'<tg-emoji emoji-id="{eid_str}">{emoji}</tg-emoji>'


# ── Extraction ─────────────────────────────────────────────────────────────────

def extract_custom_emojis(message) -> list[dict]:
    """
    Extract all custom_emoji entities from a message (text or caption).

    Returns a list of dicts:
        {
            "emoji":           str,   # visible emoji character
            "custom_emoji_id": str,
            "offset":          int,
            "length":          int,
            "context_text":    str,   # nearest surrounding word/phrase
        }
    """
    text = message.text or message.caption or ""
    entities = list(message.entities or []) + list(message.caption_entities or [])
    result = []
    for e in entities:
        if e.type != "custom_emoji":
            continue
        emoji_char = text[e.offset: e.offset + e.length]
        context    = extract_context_text(text, e.offset, e.length)
        result.append({
            "emoji":           emoji_char,
            "custom_emoji_id": e.custom_emoji_id,
            "offset":          e.offset,
            "length":          e.length,
            "context_text":    context,
        })
    return result


def extract_context_text(text: str, offset: int, length: int) -> str:
    """
    Infer nearest Persian word/phrase for an emoji at (offset, length).
    Only looks at the same line as the emoji — ignores neighbouring lines.
    Prefers text before the emoji, falls back to text after.
    """
    def _persian_words(s: str) -> str:
        words = _PERSIAN_WORD_RE.findall(s)
        return " ".join(words[-3:]) if words else ""

    before = text[:offset]
    after  = text[offset + length:]

    # Limit to same line: only text after the last newline before the emoji
    last_nl = before.rfind('\n')
    same_line_before = before[last_nl + 1:] if last_nl >= 0 else before

    # Limit to same line: only text up to the next newline after the emoji
    next_nl = after.find('\n')
    same_line_after = after[:next_nl] if next_nl >= 0 else after

    ctx = _persian_words(same_line_before)
    if not ctx:
        ctx = _persian_words(same_line_after)
    return ctx[:25]


# ── Serialization ──────────────────────────────────────────────────────────────

def serialize_premium_text(text: str, entities) -> str:
    """
    Store text + custom_emoji entities in a JSON string.
    Falls back to returning plain text if no custom emojis are present
    (backward-compatible: old plain-text values still work).

    entities: iterable of telebot MessageEntity objects (or None)
    """
    if not entities:
        return text

    custom: list[dict] = []
    for e in (entities or []):
        if e.type == "custom_emoji":
            emoji_char = text[e.offset: e.offset + e.length]
            custom.append({
                "type":            "custom_emoji",
                "offset":          e.offset,
                "length":          e.length,
                "emoji":           emoji_char,
                "custom_emoji_id": e.custom_emoji_id,
            })

    if not custom:
        return text

    return json.dumps({"text": text, "entities": custom}, ensure_ascii=False)


def deserialize_premium_text(data: str) -> dict:
    """
    Load a stored text value (plain string or JSON-serialised premium text).
    Always returns {"text": str, "entities": list}.
    """
    if not data:
        return {"text": "", "entities": []}
    stripped = data.strip()
    if not stripped.startswith("{"):
        return {"text": data, "entities": []}
    try:
        obj = json.loads(stripped)
        return {
            "text":     obj.get("text", ""),
            "entities": obj.get("entities", []),
        }
    except (json.JSONDecodeError, ValueError):
        return {"text": data, "entities": []}


# ── Rendering ──────────────────────────────────────────────────────────────────

def render_premium_text_html(data: str, escape_plain_parts: bool = False) -> str:
    """
    Render stored text as an HTML string for Telegram parse_mode="HTML".

    Inserts <tg-emoji emoji-id="...">emoji</tg-emoji> tags at custom emoji
    positions.  Everything else is left as-is (or HTML-escaped if
    escape_plain_parts=True).

    escape_plain_parts=False  →  for start_text where admin writes raw HTML.
    escape_plain_parts=True   →  for rules_text / descriptions (plain text).

    If no custom emojis are stored, the raw value is returned unchanged
    (preserves old behaviour for every caller that previously used plain text).
    """
    parsed      = deserialize_premium_text(data)
    text        = parsed["text"]
    raw_ents    = parsed.get("entities", [])

    if not raw_ents:
        return html.escape(text) if escape_plain_parts else text

    sorted_ents = sorted(raw_ents, key=lambda e: e["offset"])
    result: list[str] = []
    cursor = 0

    for e in sorted_ents:
        if e.get("type") != "custom_emoji":
            continue
        if e["offset"] > cursor:
            chunk = text[cursor: e["offset"]]
            result.append(html.escape(chunk) if escape_plain_parts else chunk)
        emoji_id   = e["custom_emoji_id"]
        emoji_char = html.escape(e.get("emoji", text[e["offset"]: e["offset"] + e["length"]]))
        result.append(f'<tg-emoji emoji-id="{emoji_id}">{emoji_char}</tg-emoji>')
        cursor = e["offset"] + e["length"]

    if cursor < len(text):
        chunk = text[cursor:]
        result.append(html.escape(chunk) if escape_plain_parts else chunk)

    return "".join(result)


def render_premium_text_entities(data: str):
    """
    Return (text, entities | None) for direct sending without parse_mode.

    Use when you can pass entities= to bot.send_message() directly.
    The second value is None when there are no custom emojis (plain text).
    """
    from telebot import types as tg_types  # late import — avoids circular dep

    parsed   = deserialize_premium_text(data)
    text     = parsed["text"]
    raw_ents = parsed.get("entities", [])

    if not raw_ents:
        return text, None

    entities: list = []
    for e in raw_ents:
        if e.get("type") == "custom_emoji":
            me = tg_types.MessageEntity(
                type             = "custom_emoji",
                offset           = e["offset"],
                length           = e["length"],
                custom_emoji_id  = e["custom_emoji_id"],
            )
            entities.append(me)

    return text, (entities if entities else None)


# ── Report formatting ──────────────────────────────────────────────────────────

def format_extracted_emoji_report(items: list) -> str:
    """
    Build a human-readable HTML report for the admin emoji-extractor tool.
    Format per line:  شماره) ایموجی  متن‌فارسی  |  ID
    """
    if not items:
        return "❌ هیچ ایموجی پرمیوم (سفارشی) در این پیام یافت نشد."

    def _line(item: dict) -> str:
        ctx = (item.get("context_text") or "").strip()
        eid = item["custom_emoji_id"]
        em  = item["emoji"]
        ctx_part = f" {html.escape(ctx)}" if ctx else ""
        return f"{em}{ctx_part}  ←  <code>{eid}</code>"

    lines = [f"{i})  {_line(item)}" for i, item in enumerate(items, 1)]
    header = f"✅ <b>{len(items)} ایموجی پرمیوم یافت شد:</b>\n\n"
    return header + "\n".join(lines)
