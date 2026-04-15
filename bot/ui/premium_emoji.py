# -*- coding: utf-8 -*-
"""
Helpers for Telegram Premium / Custom Emoji support.

SCOPE: Only for dynamic texts entered and saved by admin/user.
       NOT for static/hardcoded bot strings.
"""
from __future__ import annotations

import html
import json


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
    Infer nearest context word/phrase for an emoji at (offset, length).
    Prefers text before the emoji, falls back to text after.
    """
    before = text[:offset].strip()
    after  = text[offset + length:].strip()
    if before:
        chunk = before[-30:]
        space = chunk.rfind(" ")
        return chunk[space + 1:].strip() if space >= 0 else chunk.strip()
    if after:
        chunk = after[:30]
        space = chunk.find(" ")
        return chunk[:space].strip() if space >= 0 else chunk.strip()
    return ""


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
    """
    if not items:
        return "❌ هیچ ایموجی پرمیوم (سفارشی) در این پیام یافت نشد."

    def _line(item: dict) -> str:
        ctx = item["context_text"]
        eid = item["custom_emoji_id"]
        em  = item["emoji"]
        if ctx:
            return f"{html.escape(ctx)} - {em} - <code>{eid}</code>"
        return f"{em} - <code>{eid}</code>"

    if len(items) == 1:
        return _line(items[0])

    return "\n".join(f"{i}) {_line(item)}" for i, item in enumerate(items, 1))
