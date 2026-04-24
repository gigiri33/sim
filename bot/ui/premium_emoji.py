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
    "my_configs":    ("🌐", "5361741454685256344"),
    "test_free":     ("🎁", "6283073379184415506"),
    "wallet_charge": ("💸", "5931368295545443065"),
    "support":       ("🎧", "5467539229468793355"),
    "agency_req":    ("🤝", "5372957680174384345"),
    "admin_panel":   ("⚙️", "5370935802844946281"),
    "back":          ("🔙", "5253997076169115797"),
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
    Store text + entities (custom_emoji AND formatting: bold, italic, etc.) in JSON.
    Falls back to returning plain text if no relevant entities are present.
    """
    _FORMAT_TYPES = {"bold", "italic", "underline", "strikethrough", "spoiler",
                     "code", "pre", "text_link", "custom_emoji"}
    if not entities:
        return text

    stored: list[dict] = []
    for e in (entities or []):
        if e.type not in _FORMAT_TYPES:
            continue
        entry: dict = {
            "type":   e.type,
            "offset": e.offset,
            "length": e.length,
        }
        if e.type == "custom_emoji":
            emoji_char = text[e.offset: e.offset + e.length]
            entry["emoji"]           = emoji_char
            entry["custom_emoji_id"] = e.custom_emoji_id
        elif e.type == "text_link":
            entry["url"] = getattr(e, "url", "") or ""
        elif e.type == "pre":
            entry["language"] = getattr(e, "language", "") or ""
        stored.append(entry)

    if not stored:
        return text

    return json.dumps({"text": text, "entities": stored}, ensure_ascii=False)


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

    Handles custom_emoji, bold, italic, underline, strikethrough, code, pre,
    spoiler, and text_link entities.  Plain parts are optionally HTML-escaped.
    """
    _TAG_MAP = {
        "bold":          ("<b>",  "</b>"),
        "italic":        ("<i>",  "</i>"),
        "underline":     ("<u>",  "</u>"),
        "strikethrough": ("<s>",  "</s>"),
        "spoiler":       ("<tg-spoiler>", "</tg-spoiler>"),
        "code":          ("<code>", "</code>"),
    }

    parsed      = deserialize_premium_text(data)
    text        = parsed["text"]
    raw_ents    = parsed.get("entities", [])

    if not raw_ents:
        return html.escape(text) if escape_plain_parts else text

    sorted_ents = sorted(raw_ents, key=lambda e: e["offset"])
    result: list[str] = []
    cursor = 0

    for e in sorted_ents:
        etype = e.get("type", "")
        offset = e["offset"]
        length = e["length"]
        if offset > cursor:
            chunk = text[cursor:offset]
            result.append(html.escape(chunk) if escape_plain_parts else chunk)
        inner = text[offset: offset + length]
        if etype == "custom_emoji":
            emoji_id   = e["custom_emoji_id"]
            emoji_char = html.escape(e.get("emoji", inner))
            result.append(f'<tg-emoji emoji-id="{emoji_id}">{emoji_char}</tg-emoji>')
        elif etype in _TAG_MAP:
            open_tag, close_tag = _TAG_MAP[etype]
            result.append(f"{open_tag}{html.escape(inner)}{close_tag}")
        elif etype == "pre":
            lang = e.get("language", "")
            if lang:
                result.append(f'<pre><code class="language-{html.escape(lang)}">{html.escape(inner)}</code></pre>')
            else:
                result.append(f"<pre>{html.escape(inner)}</pre>")
        elif etype == "text_link":
            url = html.escape(e.get("url", ""))
            result.append(f'<a href="{url}">{html.escape(inner)}</a>')
        else:
            result.append(html.escape(inner) if escape_plain_parts else inner)
        cursor = offset + length

    if cursor < len(text):
        chunk = text[cursor:]
        result.append(html.escape(chunk) if escape_plain_parts else chunk)

    return "".join(result)


def render_premium_text_entities(data: str):
    """
    Return (text, entities | None) for direct sending without parse_mode.

    Handles custom_emoji, bold, italic, underline, strikethrough, code, pre,
    spoiler, and text_link entities.  Returns None for entities when none found.
    """
    from telebot import types as tg_types  # late import — avoids circular dep

    parsed   = deserialize_premium_text(data)
    text     = parsed["text"]
    raw_ents = parsed.get("entities", [])

    if not raw_ents:
        return text, None

    entities: list = []
    for e in raw_ents:
        etype = e.get("type", "")
        if etype == "custom_emoji":
            me = tg_types.MessageEntity(
                type             = "custom_emoji",
                offset           = e["offset"],
                length           = e["length"],
                custom_emoji_id  = e["custom_emoji_id"],
            )
        elif etype in ("bold", "italic", "underline", "strikethrough",
                       "spoiler", "code"):
            me = tg_types.MessageEntity(
                type   = etype,
                offset = e["offset"],
                length = e["length"],
            )
        elif etype == "pre":
            me = tg_types.MessageEntity(
                type     = "pre",
                offset   = e["offset"],
                length   = e["length"],
                language = e.get("language", ""),
            )
        elif etype == "text_link":
            me = tg_types.MessageEntity(
                type   = "text_link",
                offset = e["offset"],
                length = e["length"],
                url    = e.get("url", ""),
            )
        else:
            continue
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
