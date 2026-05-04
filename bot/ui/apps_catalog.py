# -*- coding: utf-8 -*-
"""
Apps catalog — default list of client applications per OS.

Each app entry:
  key  : short ASCII key used in callback_data and settings
  name : display name (Persian/English)
  desc : one-line Persian description
  url  : official download/website URL
"""

from .premium_emoji import ce

OS_LIST = [
    {"key": "and", "legacy_key": "android", "label": "اندروید", "emoji": "🤖", "emoji_id": "6008224489039466126"},
    {"key": "ios", "legacy_key": "ios",     "label": "iOS",     "emoji": "🍎", "emoji_id": "5764747723651684781"},
    {"key": "win", "legacy_key": "windows", "label": "ویندوز",  "emoji": "🪟", "emoji_id": "6005916300600152073"},
    {"key": "mac", "legacy_key": "mac",     "label": "مک",      "emoji": "💻", "emoji_id": "6008199565344248075"},
    {"key": "lin", "legacy_key": "linux",   "label": "لینوکس",  "emoji": "🐧", "emoji_id": "6008107257907122096"},
]

OS_BY_KEY = {item["key"]: item for item in OS_LIST}
LEGACY_TO_KEY = {item["legacy_key"]: item["key"] for item in OS_LIST}

APPS: dict[str, list[dict]] = {
    "and": [
        {"key": "hiddify",     "name": "Hiddify",         "url": "https://github.com/hiddify/hiddify-app/releases/latest"},
        {"key": "v2rayng",     "name": "v2RayNG",         "url": "https://github.com/2dust/v2rayNG/releases/latest"},
        {"key": "nekobox",     "name": "NekoBox",         "url": "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest"},
        {"key": "v2raytun",    "name": "v2RayTun",        "url": "https://play.google.com/store/apps/details?id=com.v2raytun.android"},
        {"key": "v2box",       "name": "V2Box",           "url": "https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box"},
        {"key": "napsternetv", "name": "NapsternetV",     "url": "https://play.google.com/store/apps/details?id=com.napsternetlabs.napsternetv"},
        {"key": "wireguard",   "name": "WireGuard",       "url": "https://www.wireguard.com/install/"},
        {"key": "openvpn",     "name": "OpenVPN Connect", "url": "https://openvpn.net/client/"},
    ],
    "ios": [
        {"key": "hiddify",     "name": "Hiddify",         "url": "https://hiddify.com/"},
        {"key": "streisand",   "name": "Streisand",       "url": "https://apps.apple.com/us/app/streisand/id6450534064"},
        {"key": "foxray",      "name": "FoXray",          "url": "https://apps.apple.com/nz/app/foxray/id6448898396"},
        {"key": "v2raytun",    "name": "v2RayTun",        "url": "https://apps.apple.com/us/app/v2raytun/id6476628951"},
        {"key": "v2box",       "name": "V2Box",           "url": "https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690"},
        {"key": "wireguard",   "name": "WireGuard",       "url": "https://www.wireguard.com/install/"},
        {"key": "openvpn",     "name": "OpenVPN Connect", "url": "https://openvpn.net/client/"},
    ],
    "win": [
        {"key": "hiddify",   "name": "Hiddify",         "url": "https://github.com/hiddify/hiddify-app/releases/latest"},
        {"key": "v2rayn",    "name": "v2rayN",          "url": "https://github.com/2dust/v2rayN/releases/latest"},
        {"key": "nekoray",   "name": "NekoRay",         "url": "https://github.com/MatsuriDayo/nekoray/releases/latest"},
        {"key": "wireguard", "name": "WireGuard",       "url": "https://www.wireguard.com/install/"},
        {"key": "openvpn",   "name": "OpenVPN Connect", "url": "https://openvpn.net/client/"},
    ],
    "mac": [
        {"key": "hiddify",   "name": "Hiddify",         "url": "https://github.com/hiddify/hiddify-app/releases/latest"},
        {"key": "v2rayn",    "name": "v2rayN",          "url": "https://github.com/2dust/v2rayN/releases/latest"},
        {"key": "nekoray",   "name": "NekoRay",         "url": "https://github.com/MatsuriDayo/nekoray/releases/latest"},
        {"key": "foxray",    "name": "FoXray",          "url": "https://apps.apple.com/nz/app/foxray/id6448898396"},
        {"key": "v2box",     "name": "V2Box",           "url": "https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690"},
        {"key": "wireguard", "name": "WireGuard",       "url": "https://www.wireguard.com/install/"},
        {"key": "openvpn",   "name": "OpenVPN Connect", "url": "https://openvpn.net/client/"},
    ],
    "lin": [
        {"key": "hiddify",   "name": "Hiddify",   "url": "https://github.com/hiddify/hiddify-app/releases/latest"},
        {"key": "v2rayn",    "name": "v2rayN",    "url": "https://github.com/2dust/v2rayN/releases/latest"},
        {"key": "nekoray",   "name": "NekoRay",   "url": "https://github.com/MatsuriDayo/nekoray/releases/latest"},
        {"key": "wireguard", "name": "WireGuard", "url": "https://www.wireguard.com/install/"},
        {"key": "openvpn",   "name": "OpenVPN",   "url": "https://openvpn.net/client/"},
    ],
}

def normalize_os_key(os_key: str) -> str:
    """Accept old and new OS keys and return the short key."""
    key = str(os_key or "").strip().lower()
    return LEGACY_TO_KEY.get(key, key)

def get_os_label(os_key: str) -> str:
    item = OS_BY_KEY.get(normalize_os_key(os_key))
    return item["label"] if item else str(os_key)

def os_button_label(os_key: str) -> str:
    """Return HTML label with premium emoji for OS menu messages."""
    item = OS_BY_KEY.get(normalize_os_key(os_key))
    if not item:
        return str(os_key)
    return f"{ce(item['emoji'], item['emoji_id'])} {item['label']}"

def os_button_text(os_key: str) -> str:
    """Return fallback text for inline keyboard buttons."""
    item = OS_BY_KEY.get(normalize_os_key(os_key))
    if not item:
        return str(os_key)
    return f"{item['emoji']} {item['label']}"

def get_os_emoji_id(os_key: str) -> str:
    item = OS_BY_KEY.get(normalize_os_key(os_key))
    return item["emoji_id"] if item else ""

def get_active_apps(os_key: str, setting_get_fn) -> list[dict]:
    """Return enabled apps; default is enabled. Also respects old long-key settings."""
    key = normalize_os_key(os_key)
    legacy = OS_BY_KEY.get(key, {}).get("legacy_key", key)
    result = []
    for app in APPS.get(key, []):
        new_setting = f"app_item_enabled:{key}:{app['key']}"
        old_setting = f"app_item_enabled:{legacy}:{app['key']}"
        enabled = setting_get_fn(new_setting, setting_get_fn(old_setting, "1"))
        if enabled == "1":
            result.append(app)
    return result
